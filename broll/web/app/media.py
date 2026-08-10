"""HTTP Range support for proxy/sprite/poster media serving.

SPEC.md: "GET /media/proxy/{id}.mp4 -- must support HTTP Range requests
(seeking)." Supports explicit (bytes=0-499), open-ended (bytes=500-), and
suffix (bytes=-500) range forms.
"""
from __future__ import annotations

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


def serve_file_with_range(request: Request, path: Path, media_type: str) -> Response:
    if not path.is_file():
        raise HTTPException(status_code=404, detail="file not found")

    file_size = path.stat().st_size
    range_header = request.headers.get("range")

    if not range_header:
        headers = {"Content-Length": str(file_size), "Accept-Ranges": "bytes"}
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
    }
    return StreamingResponse(
        _iter_file(path, start, length),
        status_code=206,
        media_type=media_type,
        headers=headers,
    )
