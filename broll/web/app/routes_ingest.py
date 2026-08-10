"""Ingest endpoints used by indexer/ when not co-located with the DB.

Token check: header X-Ingest-Token, checked against env BROLL_INGEST_TOKEN.
If that env var is unset, ingest is allowed without a token (dev mode).
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException

from app import config
from app.db import get_db
from app.schemas import IndexIn, MovedIn, ShareRootIn, VideoIn

router = APIRouter(prefix="/api/ingest")


def verify_ingest_token(x_ingest_token: str | None = Header(default=None)) -> None:
    expected = config.get_ingest_token()
    if expected is None:
        return  # dev mode: no token configured, ingest is open
    if x_ingest_token != expected:
        raise HTTPException(status_code=401, detail="missing or invalid X-Ingest-Token")


@router.post("/video", dependencies=[Depends(verify_ingest_token)])
def ingest_video(body: VideoIn, conn: sqlite3.Connection = Depends(get_db)) -> dict:
    with conn:
        conn.execute(
            """
            INSERT INTO videos
                (share, rel_path, hash, size_bytes, duration_s, fps, width,
                 height, codec, shot_date, category, category_hint, in_inbox, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE(?, 'discovered'))
            ON CONFLICT(share, rel_path) DO UPDATE SET
                hash = excluded.hash,
                size_bytes = excluded.size_bytes,
                duration_s = excluded.duration_s,
                fps = excluded.fps,
                width = excluded.width,
                height = excluded.height,
                codec = excluded.codec,
                shot_date = excluded.shot_date,
                category = COALESCE(excluded.category, videos.category),
                category_hint = COALESCE(excluded.category_hint, videos.category_hint),
                in_inbox = excluded.in_inbox,
                status = CASE WHEN excluded.status IS NOT NULL
                              THEN excluded.status ELSE videos.status END
            """,
            (
                body.share,
                body.rel_path,
                body.hash,
                body.size_bytes,
                body.duration_s,
                body.fps,
                body.width,
                body.height,
                body.codec,
                body.shot_date,
                body.category,
                body.category_hint,
                1 if body.in_inbox else 0,
                body.status,
            ),
        )
    row = conn.execute(
        "SELECT id FROM videos WHERE share = ? AND rel_path = ?",
        (body.share, body.rel_path),
    ).fetchone()
    return {"id": row["id"]}


@router.post("/index", dependencies=[Depends(verify_ingest_token)])
def ingest_index(body: IndexIn, conn: sqlite3.Connection = Depends(get_db)) -> dict:
    video = conn.execute(
        "SELECT id FROM videos WHERE id = ?", (body.video_id,)
    ).fetchone()
    if video is None:
        raise HTTPException(status_code=404, detail="video not found")

    now = datetime.now(timezone.utc).isoformat()
    try:
        with conn:
            # Atomic replace: delete then re-insert within one transaction.
            conn.execute("DELETE FROM segments WHERE video_id = ?", (body.video_id,))
            conn.execute("DELETE FROM themes WHERE video_id = ?", (body.video_id,))
            conn.execute(
                "DELETE FROM quality_flags WHERE video_id = ?", (body.video_id,)
            )

            for seg in body.segments:
                conn.execute(
                    """
                    INSERT INTO segments
                        (video_id, t_start, t_end, description, objects, setting, motion,
                         onscreen_text, onscreen_text_en)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        body.video_id,
                        seg.t_start,
                        seg.t_end,
                        seg.description,
                        ", ".join(seg.objects),
                        seg.setting,
                        seg.motion,
                        seg.onscreen_text,
                        seg.onscreen_text_en,
                    ),
                )

            for theme in body.themes:
                conn.execute(
                    "INSERT INTO themes (video_id, text) VALUES (?, ?)",
                    (body.video_id, theme),
                )

            for flag in body.quality_flags:
                conn.execute(
                    "INSERT INTO quality_flags (video_id, flag) VALUES (?, ?)",
                    (body.video_id, flag),
                )

            conn.execute(
                """
                UPDATE videos
                SET category_hint = ?, status = 'indexed', indexed_at = ?, model = ?
                WHERE id = ?
                """,
                (body.category_hint, now, body.model, body.video_id),
            )
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=400, detail=f"invalid ingest data: {exc}") from exc

    return {"ok": True}


@router.post("/moved", dependencies=[Depends(verify_ingest_token)])
def ingest_moved(body: MovedIn, conn: sqlite3.Connection = Depends(get_db)) -> dict:
    video = conn.execute(
        "SELECT id FROM videos WHERE id = ?", (body.video_id,)
    ).fetchone()
    if video is None:
        raise HTTPException(status_code=404, detail="video not found")

    try:
        with conn:
            conn.execute(
                """
                UPDATE videos
                SET rel_path = ?, in_inbox = 0, status = 'sorted'
                WHERE id = ?
                """,
                (body.new_rel_path, body.video_id),
            )
    except sqlite3.IntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail=f"a video already exists at that share/rel_path: {exc}",
        ) from exc

    return {"ok": True}


@router.post("/shares", dependencies=[Depends(verify_ingest_token)])
def ingest_shares(body: list[ShareRootIn], conn: sqlite3.Connection = Depends(get_db)) -> dict:
    """Record where each share's footage lives, pushed by the indexer.

    The web app cannot derive this: share -> source root, and whether a share
    archives originals or proxies, live in the indexer's config.queue.yaml,
    which app/config.py notes it does not read and may not even be able to see.
    Pushing beats sharing the file — config.queue.yaml edits then flow on the
    next run with nothing to keep in sync by hand.

    Upsert, never delete: a share dropped from the config still has videos in
    the table whose origin must stay resolvable at conform time.
    """
    now = datetime.now(timezone.utc).isoformat()
    with conn:
        for s in body:
            conn.execute(
                "INSERT INTO share_roots (share, root, source, description, indexed, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(share) DO UPDATE SET root=excluded.root, "
                "source=excluded.source, description=excluded.description, "
                "indexed=excluded.indexed, updated_at=excluded.updated_at",
                (s.share, s.root, s.source, s.description, int(s.indexed), now),
            )
    return {"ok": True, "shares": len(body)}
