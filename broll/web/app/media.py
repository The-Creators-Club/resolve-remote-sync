"""HTTP Range support for proxy/sprite/poster media serving.

SPEC.md: "GET /media/proxy/{id}.mp4 -- must support HTTP Range requests
(seeking)." Supports explicit (bytes=0-499), open-ended (bytes=500-), and
suffix (bytes=-500) range forms.
"""
from __future__ import annotations

import os
import re
from collections.abc import Iterator
from pathlib import Path

from fastapi import HTTPException, Request
from starlette.responses import Response, StreamingResponse

_RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")
_CHUNK_SIZE = 64 * 1024


def _iter_file(path: Path, start: int, length: int) -> Iterator[bytes]:
    remaining = length
    with path.open("rb") as f:
        f.seek(start)
        while remaining > 0:
            chunk = f.read(min(_CHUNK_SIZE, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


def _etag(stat: os.stat_result) -> str:
    """A validator over size + mtime.

    MEDIA-22 (resilience sweep 2026-08-28): the public share routes used to
    hand a client an hour of private cache, so revoking a link that had got
    away did not stop the clip playing (or being re-fetched) for that hour.
    They now send `no-cache`, which means "ask every time", not "do not
    store" -- an ETag keeps the bandwidth win, because the re-ask is a 304 on
    a link that is still live and a 404 on one that is not. Weak, since it
    describes the file's metadata rather than its bytes; these files are
    written once by the indexer and never edited in place.
    """
    return f'W/"{stat.st_size:x}-{int(stat.st_mtime):x}"'


def serve_file_with_range(request: Request, path: Path, media_type: str) -> Response:
    if not path.is_file():
        raise HTTPException(status_code=404, detail="file not found")

    stat = path.stat()
    file_size = stat.st_size
    etag = _etag(stat)
    range_header = request.headers.get("range")

    if_none_match = request.headers.get("if-none-match")
    if if_none_match and etag in [t.strip() for t in if_none_match.split(",")]:
        # A conditional GET on an unchanged file. 304 carries no body, so it
        # is answered whether or not a Range was asked for: the client already
        # holds the bytes it would have got.
        return Response(status_code=304, headers={"ETag": etag, "Accept-Ranges": "bytes"})

    if not range_header:
        headers = {"Content-Length": str(file_size), "Accept-Ranges": "bytes",
                   "ETag": etag}
        return StreamingResponse(
            _iter_file(path, 0, file_size), media_type=media_type, headers=headers
        )

    match = _RANGE_RE.fullmatch(range_header.strip())
    if not match:
        return Response(status_code=416, headers={"Content-Range": f"bytes */{file_size}"})

    start_s, end_s = match.group(1), match.group(2)
    if start_s == "" and end_s == "":
        return Response(status_code=416, headers={"Content-Range": f"bytes */{file_size}"})

    if start_s == "":
        # Suffix range: last N bytes of the file.
        suffix_len = int(end_s)
        if suffix_len <= 0:
            return Response(status_code=416, headers={"Content-Range": f"bytes */{file_size}"})
        start = max(file_size - suffix_len, 0)
        end = file_size - 1
    else:
        start = int(start_s)
        end = int(end_s) if end_s != "" else file_size - 1

    if start > end or start >= file_size:
        return Response(status_code=416, headers={"Content-Range": f"bytes */{file_size}"})

    end = min(end, file_size - 1)
    length = end - start + 1

    headers = {
        "Content-Range": f"bytes {start}-{end}/{file_size}",
        "Accept-Ranges": "bytes",
        "Content-Length": str(length),
        "ETag": etag,
    }
    return StreamingResponse(
        _iter_file(path, start, length),
        status_code=206,
        media_type=media_type,
        headers=headers,
    )
