"""Ingest endpoints used by indexer/ when not co-located with the DB.

Token check: header X-Ingest-Token, checked against env BROLL_INGEST_TOKEN.
FAIL-CLOSED: no BROLL_INGEST_TOKEN means no ingest at all (503). There used to
be a "dev mode" branch here that returned early when the env var was unset, so
a checkout run straight out of the repo -- or any deployment that lost the
variable -- served an unauthenticated write path that can repoint every clip's
archive path. Only the dashboard's BrollGate stood between that branch and a
logged-in editor, and one gate is not a design (COMMERCIAL_READINESS.md item
15, 2026-08-17). Developers set BROLL_INGEST_TOKEN like any other deployment.
"""
from __future__ import annotations

import hmac
import logging
import sqlite3
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException

from app import config, ingest_batches
from app.db import bump_search_generation, get_db
from app.schemas import IndexIn, MovedIn, ShareRootIn, VideoIn

log = logging.getLogger("broll.ingest")

router = APIRouter(prefix="/api/ingest")


def verify_ingest_token(x_ingest_token: str | None = Header(default=None)) -> None:
    expected = config.get_ingest_token()
    if expected is None:
        # 503, not 401: nothing the caller can send would help, and an
        # operator reading the log needs to know it is the SERVER that is
        # unconfigured. Logged every time on purpose -- an ingest run that
        # silently does nothing is how an archive goes stale unnoticed.
        log.error("ingest refused: BROLL_INGEST_TOKEN is not set on this server, so the "
                  "write path is closed. Set it (e.g. `openssl rand -hex 24`) on both "
                  "the server and the indexer.")
        raise HTTPException(
            status_code=503,
            detail="ingest is not configured on this server (BROLL_INGEST_TOKEN unset)",
        )
    # compare_digest, not ==: the token is a shared secret and `==` leaks its
    # length and matching prefix through timing. It refuses non-ASCII str, and
    # a header is attacker-shaped input -- a TypeError here must be a 401, not
    # a 500 (the dashboard gate learned this as DASH-5).
    try:
        ok = hmac.compare_digest(x_ingest_token or "", expected)
    except TypeError:
        ok = False
    if not ok:
        raise HTTPException(status_code=401, detail="missing or invalid X-Ingest-Token")


@router.post("/video", dependencies=[Depends(verify_ingest_token)])
def ingest_video(body: VideoIn, conn: sqlite3.Connection = Depends(get_db)) -> dict:
    # Say so when the indexer sends a field this contract does not carry.
    # Pydantic drops unknown keys silently, which is how `error` reached this
    # endpoint on every failed clip for months and was never written: the row
    # said 'error' and would not say why (broll-5, 2026-08-21). A write the
    # server cannot honour in full is still better than a refused write here
    # (see VideoIn), so this is a log line and not a 422 -- but it is not
    # nothing.
    unknown = sorted(body.model_extra or ())
    if unknown:
        log.warning("ingest video %s/%s: ignoring field(s) the ingest contract does "
                    "not carry: %s", body.share, body.rel_path, ", ".join(unknown))
    with conn:
        conn.execute(
            """
            INSERT INTO videos
                (share, rel_path, hash, size_bytes, duration_s, fps, width,
                 height, codec, shot_date, category, category_hint, in_inbox, status,
                 error, full_hash, duplicate_of, archive_path, original_path,
                 original_size_bytes, original_verified_at,
                 sprite_cell_w, sprite_cell_h, sprite_cols, sprite_cells,
                 sprite_interval_s)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE(?, 'discovered'),
                    ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?)
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
                              THEN excluded.status ELSE videos.status END,
                -- COALESCE, so a later scan/probe upsert (which sends none of
                -- these) cannot blank what the error, duplicates or origins
                -- pass recorded. Same rule the indexer's own sqlite backend
                -- follows -- update_video writes the fields it was given and
                -- leaves the rest alone (broll-5, 2026-08-21).
                error = COALESCE(excluded.error, videos.error),
                full_hash = COALESCE(excluded.full_hash, videos.full_hash),
                duplicate_of = COALESCE(excluded.duplicate_of, videos.duplicate_of),
                archive_path = COALESCE(excluded.archive_path, videos.archive_path),
                original_path = COALESCE(excluded.original_path, videos.original_path),
                original_size_bytes = COALESCE(excluded.original_size_bytes,
                                               videos.original_size_bytes),
                original_verified_at = COALESCE(excluded.original_verified_at,
                                                videos.original_verified_at),
                -- COALESCE, like category above: only the proxy stage sends
                -- sprite geometry, and a later scan/probe upsert must not
                -- blank it back to "unknown" (BROLL-1, 2026-08-11).
                sprite_cell_w = COALESCE(excluded.sprite_cell_w, videos.sprite_cell_w),
                sprite_cell_h = COALESCE(excluded.sprite_cell_h, videos.sprite_cell_h),
                sprite_cols = COALESCE(excluded.sprite_cols, videos.sprite_cols),
                sprite_cells = COALESCE(excluded.sprite_cells, videos.sprite_cells),
                sprite_interval_s = COALESCE(excluded.sprite_interval_s,
                                             videos.sprite_interval_s)
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
                body.error,
                body.full_hash,
                body.duplicate_of,
                body.archive_path,
                body.original_path,
                body.original_size_bytes,
                body.original_verified_at,
                body.sprite_cell_w,
                body.sprite_cell_h,
                body.sprite_cols,
                body.sprite_cells,
                body.sprite_interval_s,
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
            # The segments' embeddings go with them (BROLL-13, 2026-08-11):
            # `embeddings` cascades on video_id only, and its source_id points
            # at segment rows with no foreign key at all, so a re-ingest left
            # vectors for dead segments behind. Semantic search still scores
            # them, search_videos then silently drops the unresolvable hits, and
            # they spend the SEMANTIC_ONLY_MAX_VIDEOS budget -- so the clip's
            # real content is unreachable until stage_embed runs again.
            # Transcript embeddings are NOT touched: this endpoint does not own
            # transcript_segments.
            conn.execute(
                "DELETE FROM embeddings WHERE source = 'segment' AND video_id = ?",
                (body.video_id,),
            )
            conn.execute("DELETE FROM segments WHERE video_id = ?", (body.video_id,))
            conn.execute("DELETE FROM themes WHERE video_id = ?", (body.video_id,))
            conn.execute(
                "DELETE FROM quality_flags WHERE video_id = ?", (body.video_id,)
            )

            for seg in body.segments:
                objects = ", ".join(seg.objects)
                conn.execute(
                    """
                    INSERT INTO segments
                        (video_id, t_start, t_end, description, objects, setting, motion,
                         onscreen_text, onscreen_text_en, search_norm)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        body.video_id,
                        seg.t_start,
                        seg.t_end,
                        seg.description,
                        objects,
                        seg.setting,
                        seg.motion,
                        seg.onscreen_text,
                        seg.onscreen_text_en,
                        # Computed HERE since 2026-08-18
                        # (docs/BROLL_INGEST_PLAN.md §3.1, PR-D). It used to be
                        # left at '' with the indexer's http_backend saying
                        # search_norm "is not supported over the ingest API" --
                        # which meant every clip indexed over HTTP was
                        # keyword-searchable only after somebody remembered to
                        # run a base-rig `broll-index run --stages embed`. A
                        # two-character CJK on-screen-text term is not findable
                        # at all without this blob (migrations/004), so the gap
                        # was silent: the clip was in the archive, indexed,
                        # and unreachable by the words on its own screen.
                        # app/normalize.py is the indexer's own module,
                        # vendored byte-for-byte so both ends tokenise
                        # identically.
                        ingest_batches.segment_norm(seg, objects),
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

            # Inside the same transaction as the replace, deliberately: this is
            # the only thing that tells the semantic/fuzzy caches about a
            # re-index that hands back exactly as many rows on exactly the same
            # rowids (KNOWN_BUGS R2, the BROLL-17 residual -- both halves of
            # their (count, MAX(rowid)) key are unchanged in that shape). The
            # indexer's sqlite_backend.write_index_result twin does the same.
            bump_search_generation(conn)
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
