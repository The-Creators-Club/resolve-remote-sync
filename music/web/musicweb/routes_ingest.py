"""The write route: drag-and-drop ingest.

What is left here needs something the NAS container does not have -- a GPU for
the inline half of ingest -- so it imports its machinery lazily and fails with
a readable message rather than at startup. Everything that needed the EDITOR'S
machine (the Resolve actions, and reveal after MUSIC-6) has moved onto
ccsync_companion's loopback on 127.0.0.1:8899, where the editor's browser can
reach it and this process cannot.

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

WHO MAY CALL IT (2026-08-17, COMMERCIAL_READINESS.md item 15). Mounted in the
dashboard the session is the credential and always was. Run STANDALONE there is
no login in front of this app at all, so ingest now demands MUSIC_INGEST_TOKEN
and refuses (503) when none is configured -- fail-closed, the rule b-roll's
routes_ingest.py adopted the same day. And one request is bounded: file count
and total bytes, because the dashboard's body_size_gate deliberately only makes
a DECLARATION check on this path. See config's "ingest credentials" block.
"""
import hmac
import importlib.util
import json
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import List

from fastapi import APIRouter, File, Header, HTTPException, UploadFile

from musicweb import config, db
from musicweb.db import con
from musicweb.routes_api import TRACK_COLS, hydrate
from musicweb.search import index, refresh

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

# Last resort only, and OPT-IN: this used to be one operator's
# C:\Users\<name>\tools\ffmpeg\bin, which is PII and is wrong on every other
# host (2026-08-17, COMMERCIAL_READINESS.md item 10). Empty by default -- in
# the container ffmpeg is a distro package on PATH, and a Windows rig that
# keeps a private build sets MUSIC_FFMPEG_DIR (or FFMPEG/FFPROBE outright) in
# its own environment / the git-ignored site.toml, not here.
# Read per call, not bound at import: the app is imported long before an
# operator's environment is necessarily complete, and a mounted musicweb
# inherits the dashboard container's env.
def _fallback_bin():
    d = os.environ.get('MUSIC_FFMPEG_DIR', '').strip()
    return Path(d) if d else None


def _require_ingest_credentials(x_ingest_token):
    """Who may write into the library. 503/401, or None. See config's
    "ingest credentials" block for why the answer depends on the host.

    Fail-closed on purpose (COMMERCIAL_READINESS.md item 15, 2026-08-17): a
    standalone musicweb with no MUSIC_INGEST_TOKEN refuses ingest rather than
    serving an unauthenticated write path that lands files in the shared
    library and spends 900 s ffmpeg transcodes on them.
    """
    expected = config.ingest_token()
    if expected is None:
        if config.login_gated():
            return          # the dashboard's session gate already ran
        log.error('ingest refused: MUSIC_INGEST_TOKEN is not set and nothing is '
                  'authenticating this app (it is not mounted behind the dashboard '
                  'login), so the write path is closed.')
        raise HTTPException(503, 'ingest is not configured on this server '
                                 '(MUSIC_INGEST_TOKEN unset)')
    # A configured token is accepted in EITHER posture, so an operator who sets
    # one on the dashboard container does not break the SPA's drag-and-drop:
    # behind the login gate the session still stands on its own.
    try:
        ok = hmac.compare_digest(x_ingest_token or '', expected)
    except TypeError:
        # compare_digest refuses a non-ASCII str, and a header is
        # attacker-shaped input -- a refusal, never a 500 (DASH-5's lesson).
        ok = False
    if ok or config.login_gated():
        return
    raise HTTPException(401, 'missing or invalid X-Ingest-Token')


def _upload_size(up):
    """Bytes in one UploadFile, without reading it into memory. -1 if unknown.

    Starlette has already spooled the part to disk (or to a BytesIO under the
    1 MB threshold), so seeking to the end is the whole measurement.
    """
    size = getattr(up, 'size', None)
    if isinstance(size, int) and size >= 0:
        return size
    fh = getattr(up, 'file', None)
    try:
        here = fh.tell()
        fh.seek(0, os.SEEK_END)
        end = fh.tell()
        fh.seek(here)
        return end
    except (AttributeError, OSError, ValueError):
        return -1


def _check_request_ceilings(files):
    """Refuse a whole ingest request that is too big to be a real drop.

    413 and nothing written: half-applying a batch is the one outcome this
    route already refuses everywhere else (_require_ffmpeg does the same).
    """
    if len(files) > config.MAX_INGEST_FILES:
        raise HTTPException(413, f'too many files in one ingest request '
                                 f'({len(files)}; the limit is {config.MAX_INGEST_FILES}). '
                                 f'Drop them in smaller batches.')
    total = 0
    for up in files:
        size = _upload_size(up)
        if size < 0:
            continue        # unmeasurable stream: the per-file write still bounds it
        if size > config.MAX_INGEST_FILE_BYTES:
            raise HTTPException(413, f'{up.filename!r} is {size} bytes; the per-file '
                                     f'limit is {config.MAX_INGEST_FILE_BYTES}')
        total += size
    if total > config.MAX_INGEST_TOTAL_BYTES:
        raise HTTPException(413, f'ingest request is {total} bytes; the limit is '
                                 f'{config.MAX_INGEST_TOTAL_BYTES}')


def _tool(name):
    """Absolute path to ffmpeg/ffprobe, or None. env -> PATH -> MUSIC_FFMPEG_DIR."""
    env = os.environ.get(name.upper())
    if env:
        return env
    found = shutil.which(name)
    if found:
        return found
    bin_dir = _fallback_bin()
    if bin_dir is None:
        return None
    p = bin_dir / (name + '.exe')
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
                            'FFMPEG/FFPROBE/MUSIC_FFMPEG_DIR override is set. '
                            'Install ffmpeg in the image (or point FFMPEG/FFPROBE '
                            'at it). The whole request is refused rather than '
                            'half-applied.')
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
    """-> (music_index.ingest, index_music), or None if this host cannot analyse.

    None is not an error here, it is the container: `add_indexer_to_path()`
    finds nothing, or it finds the tree and cannot run the CLAP AUDIO tower.
    Either way the answer is to queue, not to 503.

    The torch check is EXPLICIT, and it has to be (2026-08-18). Until the
    tagging code moved to `musicweb.rescore`, `import index_music` reached
    `music_index.tagging` -> `clap_model` -> torch, so a torch-less host was
    sorted into the queued path by an import that failed on the way past. That
    accident disappeared the moment index_music stopped importing tagging, and
    a checkout-carrying container went straight down the INLINE path and 500'd
    on `index().clap` -- the one thing this function exists to prevent. What
    inline ingest actually needs is the audio tower; the audio tower needs
    torch; so that is what is asked.
    """
    if not config.add_indexer_to_path():
        return None
    if importlib.util.find_spec('torch') is None:
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


def _create_share_root_on_first_run(c):
    """mkdir the library root, but only where that cannot mean "not mounted".

    bug-hunt-2026-09-03 music-1. This used to be an unconditional
    `share_root().mkdir(parents=True, exist_ok=True)`, which is what turned an
    absent mount into a directory the upload was moved into. Creating the
    library root is a deployment act; the one case where an ingest may do it is
    the first ever upload on a fresh deployment -- the mountpoint's parent is
    there and the index names no tracks to be missing. That is the same case
    config.share_root_ready() lets through, so the gate and this agree.
    """
    root = Path(config.share_root())
    if root.is_dir():
        return
    if root.parent.is_dir() and not config.library_has_tracks(c):
        root.mkdir(parents=True, exist_ok=True)


def queue_one(upload_name, src, c):
    """Validate, de-duplicate, land and enqueue one upload. Never raises.

    Every step that the inline path does before it needs the GPU, in the same
    order and for the same reasons -- in particular the re-encode check runs
    BEFORE transcoding, so a duplicate .ogg costs no ffmpeg time at all.

    `src` is the upload's FILE OBJECT, not its bytes (MUSIC-9, 2026-08-14).
    Starlette has already spooled anything over 1 MB to disk, so `await
    up.read()` was pulling a 60 MB wav back into the dashboard container's heap
    only to write it straight out again -- a third pass over the file and a
    resident spike per upload, in the process that also serves the fleet.
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
        db.stream_to(src, staged)

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
        _create_share_root_on_first_run(c)
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


# SYNCHRONOUS `def`, all three of them, and it is load-bearing (MUSIC-2,
# 2026-08-14). They used to be `async def`, which means Starlette runs them ON
# THE EVENT LOOP -- and every step below blocks it: writing the upload to
# staging, ffprobe (120 s timeout), a 900 s ffmpeg transcode, hashing library
# files off the share mount, and a cross-mount shutil.move that degrades to
# copy+unlink. This app is mounted IN-PROCESS inside the fleet dashboard behind
# a single uvicorn worker, so for the 30-60 s an eight-file drop takes, nothing
# else was served at all -- not the sync-status pages, not /api/report from
# every companion, not the container healthcheck. A plain `def` is dispatched to
# the threadpool, where blocking is what the threads are for.
@router.post('/api/ingest')
def ingest_files(files: List[UploadFile] = File(...),
                 x_ingest_token: str = Header(default=None)):
    """Drag-and-drop ingest: analysed here, or queued for the base rig."""
    _require_ingest_credentials(x_ingest_token)
    _check_request_ceilings(files)
    indexer = _load_indexer()
    if indexer is None:
        return _ingest_queued(files)
    return _ingest_inline(files, *indexer)


def _require_share(c):
    """503 unless this host is really looking at the library. Beside ffmpeg.

    bug-hunt-2026-09-03 music-1. An unmounted bind mount is an empty directory,
    not an error, so every check below here (unique_dest's collision loop, the
    move itself) succeeds against nothing and the editor is told "queued" for
    bytes that landed under the mountpoint. Refused as a whole request for the
    same reason _require_ffmpeg() refuses one: a deployment fault must not be
    served as a half-applied ingest.
    """
    ok, reason = config.share_root_ready(c)
    if not ok:
        raise HTTPException(503, reason)


def _ingest_queued(files):
    """No GPU here: land the files and let a base-rig indexer run analyse them."""
    _require_ffmpeg()                      # before anything is written anywhere
    c = con()
    _require_share(c)
    results = []
    for up in files:
        results.append(queue_one(up.filename, up.file, c))
    return {'mode': 'queued', 'results': results, 'added': 0,
            'queued': sum(1 for r in results if r['status'] == 'queued'),
            'pending': db.queue_counts(c)['pending']}


def _ingest_inline(files, _ingest, index_music):
    """The base rig: analyse and index each accepted file in the request.

    No `library_hashes()` here any more (MUSIC-7, 2026-08-14): it rglob'ed the
    share root and blake2b-hashed all 376 files -- 9.5 GB, and W: is an SMB
    mount of the same NAS, not local disk -- once per request, to answer a
    question `db.find_content_duplicate` answers from the bytes index in one or
    two file reads. ingest_one now asks that instead, so both halves run the
    same duplicate defence off the same index.
    """
    c = con()
    _require_share(c)                      # music-1: the base rig mounts it too
    clap = index().clap                    # reuse the already-loaded model
    results = []
    for up in files:
        r = _ingest.ingest_one(up.filename, up.file, clap, c)
        r['status'] = 'added' if r.get('ok') else 'error'
        results.append(r)

    added = [r for r in results if r.get('ok')]
    if added:
        # percentiles are library-relative, so every track is re-scored once a
        # new one lands -- seconds, straight from the stored embeddings
        index_music.retag(c, clap)
        refresh(c)
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


# There is deliberately no /api/reveal here any more either (MUSIC-6,
# 2026-08-14) -- it was left behind by port step 8 and had been a dead control
# ever since. It ran `explorer /select,<path>` on the host serving the page:
# right on the base rig, and on the NAS container `os.name != 'nt'`, so it fell
# through to a 200 {"ok": false} that app.js discarded. The editor clicked and
# nothing happened, forever, with no message. It also handed the browser the
# NAS's absolute filesystem path, which the (share, rel_path) model exists to
# keep out of the payload.
#
# Reveal now goes browser -> the editor's own companion, `POST /music/reveal`
# with {share, rel_path}, beside /music/send and the same arrangement ytdl's
# reveal got on 2026-08-11. Editors on a companion older than that 404 on it
# and the page says so, which is strictly better than the silence.
