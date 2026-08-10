"""The write routes: drag-and-drop ingest, Resolve actions, reveal-in-Explorer.

Everything here needs something the NAS container does not have -- a GPU for
the inline half of ingest, a local Resolve and a local Explorer for the rest --
so all of it imports its machinery lazily and fails with a readable message
rather than at startup. Port step 8 moves the Resolve actions into
ccsync_companion on 127.0.0.1:8899.

Ingest (port step 7, done) has two shapes and picks between them by what this
host can actually do:

  inline  the indexer imports here, so decode -> CLAP embed -> tag -> retag all
          happen inside the request and the track is searchable when the
          response lands. That is the base rig, and its behaviour is unchanged.

  queued  no indexer (or no torch behind it): validate the upload, apply both
          duplicate defences, transcode .ogg, land the file in the share, write
          a `pending` row and answer "queued". A base-rig
          `index_music.py --queue` fills in the embeddings/tags/waveform.

The queued half is what runs in the container, so it must work with nothing
importable from `music/indexer` -- which is why its duplicate defences and its
naming come from `musicweb.db`, the one module both halves share. **ffmpeg is
the single native dependency it does have**: an upload is not accepted at all
without ffprobe to prove it is audio, and .ogg cannot be transcoded without
ffmpeg. A host missing either answers 503 for the whole request rather than
half-ingesting some of the files.
"""
import json
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import List

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from musicweb import config, db
from musicweb.db import con
from musicweb.routes_api import TRACK_COLS, hydrate
from musicweb.routes_media import track_path
from musicweb.search import index

log = logging.getLogger(__name__)
router = APIRouter()

# Mirrors music_index.config.AUDIO_EXTS / TRANSCODE_EXTS. The indexer's copies
# are the ones that decide what a full library scan picks up, so the two must
# agree -- tests/test_ingest_queue.py asserts it whenever the indexer happens to
# be importable. They cannot simply be imported: on the container there is no
# music_index to import them from, and that is the host this path exists for.
AUDIO_EXTS = {'.wav', '.mp3', '.flac', '.aac', '.m4a', '.ogg', '.aiff', '.aif', '.opus'}
TRANSCODE_EXTS = {'.ogg'}
MP3_BITRATE = '320k'

# Where an upload is written before anything decides whether to keep it. Never
# straight into the library, so a half-written file is never visible to a
# re-index or to Resolve.
STAGING = 'staging'

# Last resort only. The indexer half reads FFMPEG/FFPROBE with this same
# default; the web half prefers PATH, because in the container ffmpeg is a
# distro package and this Windows path means nothing.
_FALLBACK_BIN = Path(r'C:\Users\alex\tools\ffmpeg\bin')


def _tool(name):
    """Absolute path to ffmpeg/ffprobe, or None. env -> PATH -> base-rig tools."""
    env = os.environ.get(name.upper())
    if env:
        return env
    found = shutil.which(name)
    if found:
        return found
    p = _FALLBACK_BIN / (name + '.exe')
    return str(p) if p.is_file() else None


def _require_ffmpeg():
    """-> (ffmpeg, ffprobe), or 503. Checked before a single byte is written.

    Without ffprobe there is no way to tell audio from a renamed .zip, and
    without ffmpeg an .ogg cannot be transcoded -- so a host missing either
    would accept some files and reject others for reasons that have nothing to
    do with the files. Refusing the whole request is the honest answer, and the
    fix is a deployment one (see DEPLOY.md).
    """
    ffmpeg, ffprobe = _tool('ffmpeg'), _tool('ffprobe')
    if not ffmpeg or not ffprobe:
        missing = ' and '.join(n for n, v in (('ffmpeg', ffmpeg),
                                              ('ffprobe', ffprobe)) if not v)
        raise HTTPException(503,
                            f'ingest needs {missing}: not on PATH here, and no '
                            'FFMPEG/FFPROBE override is set. Install ffmpeg in '
                            'the image (or point FFMPEG/FFPROBE at it). The whole '
                            'request is refused rather than half-applied.')
    return ffmpeg, ffprobe


def _probe(path):
    """ffprobe -> {'duration', 'codec', ...}; duration 0 when it is not audio.

    Mirrors music_index.audio.probe, which the queued path cannot import.
    """
    try:
        out = subprocess.run(
            [_tool('ffprobe'), '-v', 'quiet', '-print_format', 'json',
             '-show_format', '-show_streams', str(path)],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=120)
        j = json.loads(out.stdout.decode('utf-8', errors='replace'))
    except (OSError, ValueError, subprocess.SubprocessError):
        return {'duration': 0.0, 'samplerate': 0, 'channels': 0, 'codec': ''}
    fmt = j.get('format', {})
    aud = next((s for s in j.get('streams', [])
                if s.get('codec_type') == 'audio'), None)
    if aud is None:
        # a video-only container, or a .zip someone renamed to .mp3
        return {'duration': 0.0, 'samplerate': 0, 'channels': 0, 'codec': ''}
    return {
        'duration': float(fmt.get('duration', 0) or 0),
        'samplerate': int(aud.get('sample_rate', 0) or 0),
        'channels': int(aud.get('channels', 0) or 0),
        'codec': aud.get('codec_name', ''),
    }


def _transcode_to_mp3(src: Path, dest_dir: Path):
    """Return the new mp3 path. Raises if ffmpeg produced nothing usable.

    The same command music_index.ingest.transcode_to_mp3 runs; kept separate
    only because that module is not importable on the host this path serves.
    """
    dest = dest_dir / (src.stem + '.mp3')
    proc = subprocess.run(
        [_tool('ffmpeg'), '-v', 'error', '-y', '-i', str(src),
         '-c:a', 'libmp3lame', '-b:a', MP3_BITRATE, '-map_metadata', '0',
         str(dest)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=900)
    if proc.returncode != 0 or not dest.exists() or dest.stat().st_size == 0:
        err = (proc.stderr or b'').decode('utf-8', errors='replace').strip()
        raise RuntimeError('transcode failed: %s' % (err.splitlines()[-1] if err
                                                     else 'ffmpeg produced nothing'))
    # a transcode that dropped the audio is worse than no transcode
    if _probe(dest)['duration'] <= 0:
        raise RuntimeError('transcode produced a file with no audio')
    return dest


def _load_indexer():
    """-> (music_index.ingest, index_music), or None if this host has neither.

    None is not an error here, it is the container: `add_indexer_to_path()`
    finds nothing, or it finds the tree and the import dies on torch/librosa.
    Either way the answer is to queue, not to 503.
    """
    if not config.add_indexer_to_path():
        return None
    try:
        from music_index import ingest as _ingest
        import index_music
    except ImportError:
        return None
    return _ingest, index_music


def _make_readable_to_the_fleet(path):
    """Widen an ingested file's mode so editors can actually see it.

    The dashboard container runs `umask 077` (deploy/run.sh), so a file this
    process lands in the share is mode 0600 owned by uid 3000 -- present on
    disk, in the index, and **invisible over SMB to every editor**, which is
    the one thing a shared library must not be. The share directory is
    `broll:editors 2770` setgid, so the group is already right; only the file
    mode is wrong.

    Widening to 0664 here rather than loosening the container's umask is
    deliberate: umask is process-wide and `007` would hand group `editors`
    write access to `dashboard.db` sitting in the same container.

    A no-op on Windows, and non-fatal everywhere -- a file that landed but
    could not be chmod'ed is still better than a failed upload, and the
    symptom (editors cannot see it) is visible rather than silent corruption.
    """
    if os.name == 'nt':
        return
    try:
        os.chmod(path, 0o664)
    except OSError as exc:                                     # noqa: BLE001
        log.warning('could not widen mode on %s (%s); editors may not see it '
                    'over SMB until it is chmod 664', path, exc)


def queue_one(upload_name, data, c):
    """Validate, de-duplicate, land and enqueue one upload. Never raises.

    Every step that the inline path does before it needs the GPU, in the same
    order and for the same reasons -- in particular the re-encode check runs
    BEFORE transcoding, so a duplicate .ogg costs no ffmpeg time at all.
    """
    staging = config.DATA_ROOT / STAGING
    staging.mkdir(parents=True, exist_ok=True)
    name = db.safe_upload_name(upload_name)
    ext = os.path.splitext(name)[1].lower()
    result = {'name': name, 'ok': False, 'status': 'error'}

    if ext not in AUDIO_EXTS:
        result['error'] = 'not an audio file (%s)' % (ext or 'no extension')
        return result

    work = Path(tempfile.mkdtemp(prefix='ing-', dir=str(staging)))
    try:
        staged = work / name
        staged.write_bytes(data)

        probed = _probe(staged)
        if probed['duration'] <= 0:
            result['error'] = 'no decodable audio stream'
            return result

        # defence 1: the same recording under (near enough) the same name.
        # Hashing cannot see this one -- a re-encode changes every byte.
        same = db.find_reencode(c, name, probed['duration'])
        if same:
            result['error'] = 'already in the library as %s (same track)' % same
            result['duplicate'] = True
            return result

        if ext in TRANSCODE_EXTS:
            staged = _transcode_to_mp3(staged, work)
            result['transcoded'] = True
            result['name'] = staged.name

        # defence 2: byte-identical content, wherever it is filed
        digest = db.content_hash(staged)
        dup = db.find_content_duplicate(c, staged, digest)
        if dup:
            result['error'] = 'already in the library as %s' % dup
            result['duplicate'] = True
            return result

        dest = db.unique_dest(staged.name)
        config.share_root().mkdir(parents=True, exist_ok=True)
        shutil.move(str(staged), str(dest))
        _make_readable_to_the_fleet(dest)

        rel = dest.relative_to(config.share_root()).as_posix()
        qid = db.queue_add(c, rel, name, share=config.SHARE,
                           bytes_=dest.stat().st_size,
                           duration=probed['duration'], digest=digest,
                           transcoded=bool(result.get('transcoded')))
        result.update({'ok': True, 'status': 'queued', 'queued': True,
                       'queue_id': qid, 'state': db.PENDING,
                       'share': config.SHARE, 'rel_path': rel,
                       'name': dest.name, 'duration': probed['duration']})
        return result
    except Exception as exc:                                   # noqa: BLE001
        result['error'] = str(exc)
        return result
    finally:
        shutil.rmtree(work, ignore_errors=True)


@router.post('/api/ingest')
async def ingest_files(files: List[UploadFile] = File(...)):
    """Drag-and-drop ingest: analysed here, or queued for the base rig."""
    indexer = _load_indexer()
    if indexer is None:
        return await _ingest_queued(files)
    return await _ingest_inline(files, *indexer)


async def _ingest_queued(files):
    """No GPU here: land the files and let a base-rig indexer run analyse them."""
    _require_ffmpeg()                      # before anything is written anywhere
    c = con()
    results = []
    for up in files:
        data = await up.read()
        results.append(queue_one(up.filename, data, c))
    return {'mode': 'queued', 'results': results, 'added': 0,
            'queued': sum(1 for r in results if r['status'] == 'queued'),
            'pending': db.queue_counts(c)['pending']}


async def _ingest_inline(files, _ingest, index_music):
    """The base rig: analyse and index each accepted file in the request."""
    clap = index().clap                    # reuse the already-loaded model
    c = con()
    known = _ingest.library_hashes()
    results = []
    for up in files:
        data = await up.read()
        r = _ingest.ingest_one(up.filename, data, clap, c, known)
        r['status'] = 'added' if r.get('ok') else 'error'
        results.append(r)

    added = [r for r in results if r.get('ok')]
    if added:
        # percentiles are library-relative, so every track is re-scored once a
        # new one lands -- seconds, straight from the stored embeddings
        index_music.retag(c, clap)
        index().reload(c)
        ids = [r['id'] for r in added]
        ph = ','.join('?' * len(ids))
        rows = {r['id']: r for r in hydrate(
            c.execute(f'SELECT {TRACK_COLS} FROM tracks WHERE id IN ({ph})',
                      ids).fetchall())}
        for r in added:
            r['track'] = rows.get(r['id'])
    return {'mode': 'inline', 'results': results, 'added': len(added), 'queued': 0}


@router.get('/api/ingest/queue')
def ingest_queue(limit: int = 50):
    """What the queue holds, and every failure in it.

    A queued upload that cannot be analysed is parked, not retried, so without
    somewhere to read it the reason would only ever exist in the log of
    whichever indexer run happened to hit it.
    """
    c = con()
    return {
        'counts': db.queue_counts(c),
        'failed': [dict(r) for r in db.queue_rows(c, db.FAILED, limit)],
        'pending': [dict(r) for r in db.queue_rows(c, db.PENDING, limit)],
    }


# There are deliberately NO /api/resolve routes here any more (port step 8,
# 2026-08-10). They drove Resolve on whatever host served the page, which is
# right on the base rig and useless-to-wrong once this app is mounted on the
# NAS: the container's 127.0.0.1 is the container.
#
# "Send to Resolve" now goes browser -> the editor's own ccsync companion on
# 127.0.0.1:8899 (`POST /music/send`, `GET /music/status`), carrying
# {action, share, rel_path}. The companion translates that pair against its own
# mount table and runs the Resolve call locally. See ccsync_companion/
# music_server.py and music_worker.py, and the same arrangement for b-roll in
# CLAUDE.md's "How the pieces join".


@router.get('/api/reveal/{track_id}')
def reveal(track_id: int):
    """Open the containing folder in Explorer with the file selected."""
    r = con().execute('SELECT share, rel_path FROM tracks WHERE id=?',
                      (track_id,)).fetchone()
    if not r:
        raise HTTPException(404, 'unknown track')
    path = track_path(r)
    if os.name == 'nt' and path.exists():
        os.spawnl(os.P_NOWAIT, os.environ.get('COMSPEC', 'cmd.exe'),
                  'cmd', '/c', 'explorer', f'/select,{path}')
        return {'ok': True, 'path': str(path)}
    return {'ok': False, 'path': str(path)}
