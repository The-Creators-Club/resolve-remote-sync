"""GET /media/proxy/{id}.mp4, /media/sprite/{id}.jpg, /media/poster/{id}.jpg."""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, Request
from starlette.responses import Response

from app import config
from app.db import get_db
from app.media import serve_file_with_range

router = APIRouter(prefix="/media")


def _proxy_path(conn: sqlite3.Connection, video_id: int):
    """Where this clip's playable proxy actually is.

    Prefers `videos.archive_path` -- its home in the shared archive tree, e.g.
    `Downloads/energy/nuclear/Proxy/<name>.mp4`. That tree is the same media
    editors link against in Resolve, so serving from it means one copy on the
    NAS rather than 54.7 GB here and another 54.7 GB there.

    Falls back to the flat `proxies/{id}.mp4` layout for any clip indexed but
    not yet placed in the archive -- a build is incremental, and a clip that
    landed between builds must still preview.

    The stored path is relative and only ever written by build_archive.py, but
    it is still resolved against DATA_ROOT and checked to stay inside it: a
    row's text should never be able to address the rest of the filesystem.
    """
    root = config.get_data_root()
    row = conn.execute(
        "SELECT archive_path FROM videos WHERE id = ?", (video_id,)
    ).fetchone()
    rel = row["archive_path"] if row else None
    if rel:
        candidate = (root / rel).resolve()
        if candidate.is_relative_to(root.resolve()) and candidate.is_file():
            return candidate
    return config.get_proxies_dir() / f"{video_id}.mp4"


@router.get("/proxy/{video_id}.mp4")
def proxy(video_id: int, request: Request,
          conn: sqlite3.Connection = Depends(get_db)) -> Response:
    return serve_file_with_range(request, _proxy_path(conn, video_id), "video/mp4")


@router.get("/sprite/{video_id}.jpg")
def sprite(video_id: int, request: Request) -> Response:
    path = config.get_sprites_dir() / f"{video_id}.jpg"
    return serve_file_with_range(request, path, "image/jpeg")


@router.get("/poster/{video_id}.jpg")
def poster(video_id: int, request: Request) -> Response:
    path = config.get_posters_dir() / f"{video_id}.jpg"
    return serve_file_with_range(request, path, "image/jpeg")
