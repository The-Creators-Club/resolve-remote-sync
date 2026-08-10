"""128k mp3 preview proxies -- port step 6.

The library is 9.5 GB across 376 tracks and 199 of them are `.wav`, up to 60 MB
each. Streaming those to a remote editor so they can decide whether a cue fits
is the wrong trade: preview is a listening decision, and 128k mp3 is plenty for
one. Resolve is untouched by any of this -- it links the ORIGINAL from `P:`
directly, never over HTTP -- so nothing that ends up in a timeline is degraded,
which is the same bargain broll makes with its 540p video proxies.

Proxies are keyed by **track id**, not by rel_path: `DATA_ROOT/proxies/{id}.mp3`.
A rename in the library changes rel_path and leaves the id alone, so the proxy
survives it, and there is deliberately no database column recording that a proxy
exists -- `is_file()` cannot go stale, and a flag written by a job that can be
interrupted at any point certainly can.

Base rig only. This needs ffmpeg and the library on a local mount; the NAS
container has neither, and just serves whatever files were shipped to it.
"""
import os
import json
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from music_index import config

# Imported from musicweb.config directly rather than through music_index.config:
# the proxy layout is a property of the DATA_ROOT the *web app* serves out of,
# and the reader (routes_media.py) has to agree with this writer about the exact
# filename. One definition, imported by both -- same reasoning as the shared
# schema.
from musicweb.config import (  # noqa: E402
    PROXIES_DIR, PROXY_KBPS, ensure_proxies_dir, proxy_path,
)

# Outcomes. Every track lands in exactly one of these.
BUILT = 'built'
FRESH = 'fresh'                  # proxy already there and newer than the source
ALREADY_SMALL = 'already-mp3'    # source is mp3 at/below the proxy bitrate
MISSING = 'missing'              # source file is not on this host
FAILED = 'failed'

# How far above PROXY_KBPS a source mp3 may measure and still be left alone.
# A VBR mp3 targeted at 128k routinely reports 130-133 kbps overall, and
# re-encoding one of those to 128k CBR saves nothing while running the audio
# through a second lossy generation -- the artefacts of the two encoders
# compound, and a preview that sounds swirly is a preview an editor distrusts.
BITRATE_TOLERANCE = 1.05


def _ffprobe(path):
    """Format + audio-stream facts, including bitrate. {} if unreadable."""
    out = subprocess.run(
        [config.FFPROBE, '-v', 'quiet', '-print_format', 'json',
         '-show_format', '-show_streams', str(path)],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=120)
    try:
        j = json.loads(out.stdout.decode('utf-8', errors='replace'))
    except ValueError:
        return {}
    fmt = j.get('format', {})
    aud = next((s for s in j.get('streams', []) if s.get('codec_type') == 'audio'), {})
    return {'format': fmt, 'stream': aud}


def _num(*values):
    for v in values:
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if f > 0:
            return f
    return 0.0


def source_info(path):
    """{codec, kbps, duration, channels} for a source file.

    The bitrate is taken from the audio stream, then the container, then
    computed from size and duration. The fallbacks matter: a VBR mp3 written
    without an Xing header reports no stream bitrate at all, and treating that
    as 0 would send every one of them through a pointless re-encode.
    """
    info = _ffprobe(path)
    if not info:
        return {}
    fmt, aud = info['format'], info['stream']
    if not aud:
        return {}
    duration = _num(fmt.get('duration'), aud.get('duration'))
    size = _num(fmt.get('size')) or float(Path(path).stat().st_size)
    computed = (size * 8.0 / duration / 1000.0) if duration else 0.0
    return {
        'codec': aud.get('codec_name', ''),
        'kbps': _num(aud.get('bit_rate'), fmt.get('bit_rate')) / 1000.0 or computed,
        'duration': duration,
        'channels': int(_num(aud.get('channels')) or 0),
        'bytes': int(size),
    }


_TIME_RE = re.compile(rb'time=(\d+):(\d\d):(\d\d(?:\.\d+)?)')


def decoded_duration(path):
    """Seconds of audio ffmpeg can actually decode. 0.0 if it cannot tell.

    A second opinion for when the container's duration is not trustworthy, and
    on this library it frequently is not: the 89 `.aac` files are raw ADTS with
    no index, so ffprobe reports `size * 8 / bit_rate` -- an ESTIMATE off an
    average bitrate. Measured on the real library, it overshoots by 6% to 53%
    (`Lars_Bork_Andersen_-_Darker_Days....aac` probes at 260.8 s and decodes
    121.9 s). Twenty-five perfectly complete proxies were reported as truncated
    against that yardstick before this existed.

    Cheap enough to use as a tie-breaker: a full decode of a 4-minute track
    runs at over 1000x realtime (~0.1 s) because nothing is being encoded.
    """
    r = subprocess.run(
        [config.FFMPEG, '-v', 'error', '-stats', '-nostdin', '-i', str(path),
         '-f', 'null', '-'],
        capture_output=True, timeout=900)
    last = None
    for last in _TIME_RE.finditer(r.stderr):
        pass
    if not last:
        return 0.0
    h, m, s = last.groups()
    return int(h) * 3600 + int(m) * 60 + float(s)


def is_pointless(info, kbps=PROXY_KBPS):
    """True when encoding a proxy from this source would gain nothing.

    The rule is bitrate, not codec: a source already at or below the proxy
    bitrate cannot come out smaller, whatever it is. Measured on this library
    before the rule was generalised -- a 4.6 MB .ogg produced a **6.7 MB**
    proxy and a 3.8 MB .aac produced 3.7 MB, i.e. the "saving" was negative.
    Those files are already preview-sized; the 9.5 GB problem is wav and flac.

    For mp3 there is a second, independent reason to leave it alone: a 128k
    source re-encoded to 128k runs the audio through a second lossy generation
    and the two encoders' artefacts compound, so the proxy sounds worse than
    the file it replaced while saving nothing.

    A lossless source never trips this (pcm is ~1400 kbps, flac ~900), which is
    what keeps the rule from quietly declining the files that matter.
    """
    return 0 < info.get('kbps', 0) <= kbps * BITRATE_TOLERANCE


def is_fresh(src, dst):
    """True if `dst` is a usable proxy for `src` -- present and not older.

    This, and only this, is what makes a run resumable: interrupt the generator
    and re-run it and every finished track costs one stat() instead of an
    encode. Encodes land via an atomic rename (see build_one), so a proxy that
    exists is a proxy that finished.
    """
    try:
        d, s = dst.stat(), src.stat()
    except OSError:
        return False
    return d.st_size > 0 and d.st_mtime >= s.st_mtime


def build_one(src, dst, kbps=PROXY_KBPS, channels=0, duration=0.0):
    """Encode one proxy. Returns its size in bytes. Raises on failure.

    Written to `<dst>.part` and renamed only after it verifies, so an
    interrupted run (or a half-written file on a share that dropped) can never
    be mistaken for a finished proxy by is_fresh().
    """
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + '.part')

    cmd = [config.FFMPEG, '-y', '-v', 'error', '-nostdin', '-i', str(src),
           # -vn drops embedded cover art, which is an attached_pic *video*
           # stream and would otherwise be copied into the proxy -- a 5 MB
           # cover on a 2 MB preview defeats the entire exercise.
           '-vn', '-map', '0:a:0',
           '-c:a', 'libmp3lame', '-b:a', f'{int(kbps)}k']
    # Downmix surround; leave mono alone rather than inflating it to stereo.
    # Sample rate is deliberately not pinned: ffmpeg inserts a resampler for
    # rates libmp3lame cannot take, and forcing 44.1k would resample the 48 kHz
    # majority of this library for no reason.
    if channels > 2:
        cmd += ['-ac', '2']
    # -f is required, not tidiness: the output is written to `<id>.mp3.part`
    # and ffmpeg picks its muxer from the extension, which for `.part` is
    # nothing at all ("Unable to choose an output format").
    cmd += ['-f', 'mp3', str(tmp)]

    try:
        r = subprocess.run(cmd, capture_output=True, timeout=900)
        if r.returncode != 0:
            err = r.stderr.decode('utf-8', errors='replace').strip()
            raise RuntimeError(f'ffmpeg exited {r.returncode}: {err[:200]}')

        size = tmp.stat().st_size if tmp.exists() else 0
        if size <= 0:
            raise RuntimeError('ffmpeg wrote nothing')
        # A truncated proxy decodes cleanly and then simply stops early, so
        # the size check above does not catch it -- broll learned this the
        # expensive way on its video proxies. Compare durations.
        #
        # A shortfall is not proof on its own, because `duration` came from the
        # source's container and raw ADTS .aac only estimates that (see
        # decoded_duration). So a suspected truncation is re-checked against
        # what the source really decodes to, and only a proxy short of THAT is
        # rejected. The cheap check still guards the common case; the decode is
        # paid for only by the handful that trip it.
        if duration:
            got = source_info(tmp).get('duration', 0)
            if got and got < duration * 0.97:
                real = decoded_duration(src)
                if not real or got < real * 0.97:
                    raise RuntimeError(
                        f'truncated: {got:.0f}s of '
                        f'{real or duration:.0f}s'
                        f'{"" if real else " (container duration)"}')
        os.replace(tmp, dst)
        return size
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def build_track(track_id, src, kbps=PROXY_KBPS, force=False, dest=None):
    """Make (or decide not to make) one track's proxy.

    -> (outcome, before_bytes, after_bytes, codec). `after_bytes` is what a
    previewing editor now pulls: the proxy where there is one, the original
    where the fallback applies, which is what makes the saving figure honest
    rather than a total over only the files that happened to encode.

    `force` re-encodes, but does NOT override is_pointless(): forcing a second
    lossy generation onto an already-small file is never the intent, and would
    make some of them bigger.
    """
    src = Path(src)
    dst = Path(dest) if dest else proxy_path(track_id)
    if not src.is_file():
        return MISSING, 0, 0, ''

    before = src.stat().st_size
    if not force and is_fresh(src, dst):
        return FRESH, before, dst.stat().st_size, ''

    info = source_info(src)
    if not info:
        raise RuntimeError('no decodable audio stream')
    codec = info.get('codec', '')
    if is_pointless(info, kbps):
        # No proxy on disk, on purpose: routes_media falls back to the
        # original, which is already no bigger than what we would have made.
        return ALREADY_SMALL, before, before, codec

    size = build_one(src, dst, kbps=kbps,
                     channels=info.get('channels', 0),
                     duration=info.get('duration', 0.0))
    return BUILT, before, size, codec


def new_summary():
    return {'total': 0, BUILT: 0, FRESH: 0, ALREADY_SMALL: 0, MISSING: 0,
            FAILED: 0, 'before_bytes': 0, 'after_bytes': 0, 'failures': [],
            # which codecs the skips came from -- "how many were already mp3"
            # is the number this decision has to justify itself with
            'skipped_codecs': {}}


def build_all(items, kbps=PROXY_KBPS, force=False, jobs=4, log=print):
    """Build proxies for (track_id, src_path) pairs. -> the summary dict.

    Threads, not processes: every unit of work is an ffmpeg subprocess plus a
    read off the SMB share, so the GIL is irrelevant and the run is bound by
    the share and the CPU, both of which like a handful of concurrent readers.
    A failure is counted and reported, never raised -- one damaged file must
    not cost the other 375 their proxies.
    """
    items = list(items)
    ensure_proxies_dir()
    summary = new_summary()
    summary['total'] = len(items)

    def one(item):
        track_id, src = item
        try:
            return (track_id, src) + build_track(track_id, src, kbps=kbps,
                                                 force=force) + (None,)
        except Exception as exc:
            return track_id, src, FAILED, 0, 0, '', f'{type(exc).__name__}: {exc}'

    done = 0
    with ThreadPoolExecutor(max_workers=max(1, int(jobs))) as pool:
        for track_id, src, outcome, before, after, codec, err in pool.map(one, items):
            done += 1
            summary[outcome] += 1
            summary['before_bytes'] += before
            summary['after_bytes'] += after
            if outcome == ALREADY_SMALL:
                summary['skipped_codecs'][codec] = \
                    summary['skipped_codecs'].get(codec, 0) + 1
            if outcome == FAILED:
                summary['failures'].append((track_id, str(src), err))
                log(f'  [{done}/{len(items)}] FAIL {Path(src).name}: {err}', flush=True)
            elif outcome == MISSING:
                summary['failures'].append((track_id, str(src), 'source not found'))
                log(f'  [{done}/{len(items)}] MISSING {src}', flush=True)
            elif outcome == BUILT:
                log(f'  [{done}/{len(items)}] {Path(src).name[:52]:54s} '
                    f'{before/1e6:7.1f} -> {after/1e6:5.1f} MB', flush=True)
            elif done % 50 == 0:
                log(f'  [{done}/{len(items)}] ...', flush=True)
    return summary


def orphans(known_ids, directory=None):
    """Proxy files whose track id is no longer in the database.

    Worth having a broom for, because `tracks.id` is a plain INTEGER PRIMARY
    KEY and SQLite reuses the highest free rowid: delete the last track, index
    a new one, and it inherits the old id -- and with it a proxy of completely
    different audio. is_fresh() would not save you either, since the library's
    files are older than any proxy. So an orphan is not merely wasted disk.
    """
    directory = Path(directory or PROXIES_DIR)
    if not directory.is_dir():
        return []
    known = {int(i) for i in known_ids}
    out = []
    for p in sorted(directory.iterdir()):
        if p.suffix == '.part' or p.name.endswith('.mp3.part'):
            out.append(p)                        # interrupted encode; always junk
            continue
        if p.suffix != '.mp3':
            continue
        try:
            if int(p.stem) not in known:
                out.append(p)
        except ValueError:
            out.append(p)                        # not id-shaped; not ours
    return out
