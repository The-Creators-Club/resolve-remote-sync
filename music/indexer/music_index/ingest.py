"""Drag-and-drop ingest: land a file in the library, analyse it, index it.

This is the INLINE half -- the base rig, where the GPU is. The steps up to the
analysis are shared with the queued half in `musicweb/routes_ingest.py`, which
serves the same route on a host that has no indexer to import; both take their
duplicate defences and their naming from `musicweb.db` so the two cannot drift.

Steps per file:
  1. write the upload to a staging dir (never straight into the library, so a
     half-written file is never visible to Resolve or a re-index)
  2. probe it -- anything ffprobe finds no audio stream in is rejected
  3. .ogg is transcoded to 320k mp3; the dropped .ogg itself is left alone
  4. de-duplicate against the library by content hash
  5. move into the share root under a collision-free flat name
  6. CLAP embed + DSP features + DB row
  7. caller re-tags so percentiles account for the new track
"""
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from musicweb import db
# One copy of each, in the storage layer both halves share: the queued path has
# to reject exactly the duplicates this one rejects, on a host where nothing in
# this package can even be imported.
from musicweb.db import content_hash, find_reencode, unique_dest  # noqa: F401

from music_index import audio, config
import index_music        # the CLI's analyse_one/upsert, reused verbatim here

TRANSCODE_EXTS = {'.ogg'}
MP3_BITRATE = '320k'
STAGING = config.DATA_ROOT / 'staging'

_safe_name = db.safe_upload_name


def library_hashes():
    """content hash -> rel_path for everything already in the library."""
    out = {}
    root = config.share_root()
    for p in root.rglob('*'):
        if not p.is_file() or p.suffix.lower() not in config.AUDIO_EXTS:
            continue
        rel = p.relative_to(root)
        if any(part in config.EXCLUDE_DIRS for part in rel.parts[:-1]):
            continue
        try:
            out[content_hash(p)] = rel.as_posix()
        except OSError:
            pass
    return out


def transcode_to_mp3(src: Path, dest_dir: Path):
    """Return the new mp3 path. Raises if ffmpeg produced nothing usable."""
    dest = dest_dir / (src.stem + '.mp3')
    cmd = [config.FFMPEG, '-v', 'error', '-y', '-i', str(src),
           '-c:a', 'libmp3lame', '-b:a', MP3_BITRATE, '-map_metadata', '0',
           str(dest)]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          timeout=900)
    if proc.returncode != 0 or not dest.exists() or dest.stat().st_size == 0:
        err = (proc.stderr or b'').decode('utf-8', errors='replace').strip()
        raise RuntimeError('transcode failed: %s' % (err.splitlines()[-1] if err
                                                     else 'ffmpeg produced nothing'))
    # a transcode that dropped the audio is worse than no transcode
    got = audio.probe(dest)
    if got['duration'] <= 0:
        raise RuntimeError('transcode produced a file with no audio')
    return dest


def ingest_one(upload_name, data, clap, con, known=None):
    """data: bytes. Returns a result dict (never raises for expected failures)."""
    STAGING.mkdir(parents=True, exist_ok=True)
    name = _safe_name(upload_name)
    ext = os.path.splitext(name)[1].lower()
    result = {'name': name, 'ok': False}

    if ext not in config.AUDIO_EXTS:
        result['error'] = 'not an audio file (%s)' % (ext or 'no extension')
        return result

    work = Path(tempfile.mkdtemp(prefix='ing-', dir=str(STAGING)))
    try:
        staged = work / name
        staged.write_bytes(data)

        probed = audio.probe(staged)
        if probed['duration'] <= 0:
            result['error'] = 'no decodable audio stream'
            return result

        # check the re-encode match BEFORE transcoding: the incoming name and
        # duration are what identify it, and transcoding is wasted work if it
        # is already held
        same = find_reencode(con, name, probed['duration'])
        if same:
            result['error'] = 'already in the library as %s (same track)' % same
            result['duplicate'] = True
            return result

        if ext in TRANSCODE_EXTS:
            staged = transcode_to_mp3(staged, work)
            result['transcoded'] = True
            result['name'] = staged.name

        if known is None:
            known = library_hashes()
        h = content_hash(staged)
        if h in known:
            result['error'] = 'already in the library as %s' % known[h]
            result['duplicate'] = True
            return result

        dest = unique_dest(staged.name)
        config.share_root().mkdir(parents=True, exist_ok=True)
        shutil.move(str(staged), str(dest))
        known[h] = dest.name

        fields, windows = index_music.analyse_one(dest, clap)
        if fields is None:
            dest.unlink(missing_ok=True)
            result['error'] = 'could not analyse the audio'
            return result
        rel = dest.relative_to(config.share_root()).as_posix()
        tid = index_music.upsert(con, rel, dest, fields, windows, clap.name)

        result.update({'ok': True, 'id': tid, 'share': config.SHARE,
                       'rel_path': rel,
                       'name': dest.name,
                       'duration': fields.get('duration'),
                       'bpm': fields.get('bpm'),
                       'key': fields.get('music_key')})
        return result
    except Exception as exc:                                   # noqa: BLE001
        result['error'] = str(exc)
        return result
    finally:
        shutil.rmtree(work, ignore_errors=True)
