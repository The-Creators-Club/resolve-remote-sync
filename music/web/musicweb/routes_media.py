"""Audio streaming and waveform overviews.

The audio route answers HTTP Range with a real 206 so the player can seek. That
is why the app is mounted in-process by the dashboard rather than proxied: a
reverse proxy in front of this reintroduces the "pass Range through unmodified"
problem (same reasoning as broll's /media/proxy route).

Preview traffic is served from a 128k mp3 proxy when one exists (port step 6),
falling back to the original file when it does not -- so a host with no proxies
generated yet, or a track added since the last generator run, still plays.
"""
import mimetypes
import re

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response, StreamingResponse

from musicweb import config
from musicweb.db import con

router = APIRouter()


# parse_range's "this request cannot be satisfied" answer, as distinct from
# "there is no range to serve here" (None). Both are error-ish; only one is 416.
UNSATISFIABLE = object()


def parse_range(header, size):
    """RFC 7233 single byte range -> (start, end) inclusive, None, UNSATISFIABLE.

    None means "ignore the header and serve a plain 200". That covers no Range
    at all, a unit this app does not speak, a multi-range request, and a
    syntactically invalid one (an inverted `bytes=100-50`) -- RFC 7233 says an
    invalid Range is ignored, not 416'd, and answering a 206 for a header the
    server did not understand is worse than not supporting ranges at all. Both
    of those were wrong before MUSIC-1 (2026-08-11).

    `bytes=-N` is a SUFFIX range: the LAST N bytes. It used to be read as
    `bytes=0-N`, so a client probing an mp3's ID3v1/Xing/LAME tail (or an m4a
    `moov` atom) with `bytes=-128` got the FIRST 129 bytes labelled as the last
    ones, and reported a wrong duration or refused to seek.
    """
    m = re.fullmatch(r'\s*bytes\s*=\s*(\d*)\s*-\s*(\d*)\s*', header or '')
    if not m or not (m.group(1) or m.group(2)):
        return None
    if size == 0:
        return UNSATISFIABLE
    if not m.group(1):
        n = int(m.group(2))
        if n == 0:                       # "the last zero bytes" satisfies nothing
            return UNSATISFIABLE
        return max(0, size - n), size - 1
    start = int(m.group(1))
    if start >= size:
        return UNSATISFIABLE
    if not m.group(2):                   # open-ended: run to the end
        return start, size - 1
    end = int(m.group(2))
    if end < start:                      # inverted: invalid, so ignored
        return None
    return start, min(end, size - 1)


def track_path(row):
    """(share, rel_path) -> a real path, or a 4xx.

    Never joins the two by hand: rel_path reaches this process from the
    database, and the database is written by an indexer and an upload route, so
    the validated resolver is the only thing standing between a bad row and
    serving a file from outside the library.
    """
    try:
        return config.resolve_path(row['share'], row['rel_path'])
    except (config.PathTraversalError, config.UnknownShareError) as exc:
        raise HTTPException(400, str(exc)) from None


def audio_source(track_id, row, original=False):
    """(path, kind) for a track: its 128k mp3 proxy, or the original file.

    The proxy is chosen on nothing but existence -- there is no database column
    saying whether one was made. Generation is a separate, resumable base-rig
    job over a library the web app cannot even decode, so any flag here would
    be a second source of truth that goes stale the moment the generator is
    interrupted, a file is deleted, or the data root is shipped without it.
    An `is_file()` cannot go stale.

    A track whose source is already a small mp3 deliberately has no proxy (see
    music_index/proxies.py) and lands on the same fallback: re-encoding it would
    save nothing and compound the lossy artefacts.
    """
    if not original:
        proxy = config.proxy_path(track_id)
        if proxy.is_file():
            return proxy, 'proxy'
    path = track_path(row)
    if not path.exists():
        raise HTTPException(404, f'file missing: {row["rel_path"]}')
    return path, 'original'


@router.get('/api/audio/{track_id}')
def audio_stream(track_id: int, request: Request, original: bool = False):
    """Serve the audio with HTTP range support so the player can seek.

    Serves the preview proxy when there is one. `?original=1` forces the source
    file -- kept because "what does the master actually sound like" is a real
    question, and because a 128k mp3 is a preview, not the asset. Resolve does
    not use it either way: it links the original from P: directly, not over
    HTTP, so no timeline is ever fed a proxy.
    """
    r = con().execute('SELECT share, rel_path FROM tracks WHERE id=?',
                      (track_id,)).fetchone()
    if not r:
        raise HTTPException(404, 'unknown track')
    path, kind = audio_source(track_id, r, original=original)

    size = path.stat().st_size
    mime = mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
    # Which of the two was served is otherwise invisible (both are audio/*),
    # and "is the proxy being used at all" is the first question anyone
    # debugging Tailscale preview bandwidth asks.
    src_header = {'X-Audio-Source': kind}
    rng_header = request.headers.get('range')
    if not rng_header:
        return FileResponse(path, media_type=mime, headers=src_header)

    rng = parse_range(rng_header, size)
    if rng is UNSATISFIABLE:
        return Response(status_code=416, headers={'Content-Range': f'bytes */{size}'})
    if rng is None:
        # A Range this app will not act on: whole entity, plain 200. Served by
        # the streamer below rather than by FileResponse, because starlette
        # (>= 0.37) parses Range inside FileResponse itself -- handing it the
        # request would undo the decision to ignore the header.
        start, end, status = 0, size - 1, 200
    else:
        (start, end), status = rng, 206
    length = end - start + 1

    def chunks(chunk=256 * 1024):
        with open(path, 'rb') as f:
            f.seek(start)
            left = length
            while left > 0:
                data = f.read(min(chunk, left))
                if not data:
                    break
                left -= len(data)
                yield data

    headers = {'Accept-Ranges': 'bytes', 'Content-Length': str(length), **src_header}
    if status == 206:
        # Every byte offset here is the SERVED file's, proxy or original. The
        # two have different sizes, so a client that started a range request
        # against one must not be answered from the other -- which is why
        # ?original is a request parameter and never a per-request fallback.
        headers['Content-Range'] = f'bytes {start}-{end}/{size}'
    return StreamingResponse(chunks(), status_code=status, media_type=mime,
                             headers=headers)


@router.get('/api/peaks/{track_id}')
def peaks(track_id: int):
    """Waveform overview as uint8 values. Built on demand if missing."""
    r = con().execute('SELECT data FROM peaks WHERE track_id=?', (track_id,)).fetchone()
    if r and r['data']:
        return Response(bytes(r['data']), media_type='application/octet-stream')

    t = con().execute('SELECT share, rel_path FROM tracks WHERE id=?',
                      (track_id,)).fetchone()
    if not t:
        raise HTTPException(404, 'unknown track')
    path = track_path(t)
    if not path.exists():
        raise HTTPException(404, 'file missing')
    # Building one costs an ffmpeg decode, so it lives with the indexer. Every
    # indexed track already has its 900 bytes stored (index_music.py --peaks
    # backfills), which is why this path is a fallback and not a feature: a
    # web-only host answers 404 rather than pretending it can decode audio.
    config.add_indexer_to_path()
    try:
        from music_index import audio as _audio
    except ImportError as exc:
        raise HTTPException(404, 'no stored waveform and no indexer on this '
                                 'host to build one: %s' % exc)
    data = _audio.peaks_from_file(path)
    if data:
        con().execute('INSERT OR REPLACE INTO peaks(track_id,n,data) VALUES(?,?,?)',
                      (track_id, len(data), data))
        con().commit()
    return Response(bytes(data), media_type='application/octet-stream')
