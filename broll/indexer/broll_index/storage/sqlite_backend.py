"""Direct sqlite storage backend (co-located dev mode).

Applies schema.sql idempotently via PRAGMA user_version, per SPEC.md: "Applied idempotently
... using PRAGMA user_version migrations, v1 = the full schema."
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..transcribe import TranscriptCue
from .base import Storage

# schema.sql lives at the repo root, two levels above this package's parent (indexer/).
# indexer/broll_index/storage/sqlite_backend.py -> parents[2] == indexer/ -> parents[3] == repo root.
_DEFAULT_SCHEMA_PATH = Path(__file__).resolve().parents[3] / "schema.sql"

# The `meta` key the web app's search caches key on (migration 010). Upsert-and-
# increment; the INSERT arm only fires on a DB whose seed row went missing.
SEARCH_GENERATION_KEY = "search_generation"
_BUMP_SEARCH_GENERATION_SQL = (
    "INSERT INTO meta (key, value) VALUES (?, '1') "
    "ON CONFLICT(key) DO UPDATE SET value = CAST(CAST(meta.value AS INTEGER) + 1 AS TEXT)"
)


def bump_search_generation(conn: sqlite3.Connection) -> None:
    """Tell web/app/semantic.py's matrix cache and web/app/fuzzy.py's vocabulary
    cache that what they hold is out of date. Must run in the SAME transaction
    as the write it describes -- i.e. before the commit, not after.

    Those caches key on (row count, MAX(rowid)) as well, which sees every
    ordinary re-index but not one whose replacement rows land back on the very
    same rowids: same count, same high-water mark, entirely different vectors
    (KNOWN_BUGS R2, the BROLL-17 residual). This counter is the only thing that
    sees that shape, so every path here that inserts/replaces/deletes
    `embeddings` or the segments/transcript_segments rows the vocabulary is
    built from calls it -- as does the web app's routes_ingest twin. Loud by
    design: a DB that predates migration 010 raises here rather than quietly
    leaving a reader on stale vectors (`broll-index migrate` is the fix).
    """
    conn.execute(_BUMP_SEARCH_GENERATION_SQL, (SEARCH_GENERATION_KEY,))


class SqliteBackend(Storage):
    def __init__(self, db_path: str | Path, schema_path: str | Path | None = None):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.schema_path = Path(schema_path) if schema_path else _DEFAULT_SCHEMA_PATH
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        version = self.conn.execute("PRAGMA user_version").fetchone()[0]
        if version == 0:
            sql = self.schema_path.read_text(encoding="utf-8")
            self.conn.executescript(sql)
            self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # -- videos -----------------------------------------------------------

    def upsert_video(self, share: str, rel_path: str, **fields: Any) -> int:
        existing = self.get_video_by_path(share, rel_path)
        if existing is not None:
            if fields:
                self.update_video(existing["id"], **fields)
            return existing["id"]
        columns = {"share": share, "rel_path": rel_path, **fields}
        cols = ", ".join(columns)
        placeholders = ", ".join(f":{c}" for c in columns)
        cur = self.conn.execute(f"INSERT INTO videos ({cols}) VALUES ({placeholders})", columns)
        self.conn.commit()
        return cur.lastrowid

    def get_video(self, video_id: int) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM videos WHERE id = ?", (video_id,)).fetchone()
        return dict(row) if row else None

    def get_video_by_path(self, share: str, rel_path: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM videos WHERE share = ? AND rel_path = ?", (share, rel_path)
        ).fetchone()
        return dict(row) if row else None

    def videos_by_status(self, statuses: list[str], limit: int | None = None) -> list[dict[str, Any]]:
        # duplicate_of IS NULL: a confirmed duplicate is excluded from the eligible-videos
        # query at the source (not filtered after the fact) so `run_pipeline`'s own
        # LIMIT still means "N videos actually worth spending model calls on" — see
        # pipeline.py's run_pipeline and broll_index/duplicates.py.
        placeholders = ", ".join("?" for _ in statuses)
        sql = f"SELECT * FROM videos WHERE status IN ({placeholders}) AND duplicate_of IS NULL ORDER BY id"
        params: list[Any] = list(statuses)
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        rows = self.conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def sortable_videos(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM videos WHERE in_inbox = 1 AND category IS NOT NULL AND status = 'indexed'"
            " ORDER BY id"
        ).fetchall()
        return [dict(r) for r in rows]

    def all_videos(self) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM videos ORDER BY id").fetchall()
        return [dict(r) for r in rows]

    def segment_counts(self) -> dict[int, int]:
        rows = self.conn.execute(
            "SELECT video_id, COUNT(*) AS n FROM segments GROUP BY video_id"
        ).fetchall()
        return {r["video_id"]: r["n"] for r in rows}

    def delete_video(self, video_id: int) -> None:
        # Explicit child deletes: sqlite enforces ON DELETE CASCADE only when
        # PRAGMA foreign_keys is on, which we don't rely on here.
        self.conn.execute("DELETE FROM segments WHERE video_id = ?", (video_id,))
        self.conn.execute("DELETE FROM themes WHERE video_id = ?", (video_id,))
        self.conn.execute("DELETE FROM quality_flags WHERE video_id = ?", (video_id,))
        self.conn.execute("DELETE FROM videos WHERE id = ?", (video_id,))
        # Segments leave the vocabulary, and the embeddings cascade off the
        # videos row.
        bump_search_generation(self.conn)
        self.conn.commit()

    def update_video(self, video_id: int, **fields: Any) -> None:
        if not fields:
            return
        set_clause = ", ".join(f"{k} = :{k}" for k in fields)
        params = {**fields, "id": video_id}
        self.conn.execute(f"UPDATE videos SET {set_clause} WHERE id = :id", params)
        self.conn.commit()

    def set_error(self, video_id: int, message: str) -> None:
        self.update_video(video_id, status="error", error=message)

    def write_index_result(
        self,
        video_id: int,
        *,
        themes: list[str],
        quality_flags: list[str],
        category_hint: str | None,
        segments: list[dict[str, Any]],
        model: str,
    ) -> None:
        conn = self.conn
        # The segments' embeddings go with the segments (BROLL-13, 2026-08-11):
        # `embeddings.source_id` has no foreign key onto segments, so re-indexing
        # a video otherwise leaves vectors behind for rows that no longer exist.
        # They keep scoring in semantic search, resolve to nothing, and eat the
        # per-query semantic-only budget. Same fix as the web app's /api/ingest/
        # index twin; transcript embeddings are untouched (different owner).
        conn.execute("DELETE FROM embeddings WHERE source = 'segment' AND video_id = ?", (video_id,))
        conn.execute("DELETE FROM segments WHERE video_id = ?", (video_id,))
        conn.execute("DELETE FROM themes WHERE video_id = ?", (video_id,))
        conn.execute("DELETE FROM quality_flags WHERE video_id = ?", (video_id,))
        for seg in segments:
            conn.execute(
                "INSERT INTO segments (video_id, t_start, t_end, description, objects, setting, motion, "
                "onscreen_text, onscreen_text_en) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    video_id,
                    seg["t_start"],
                    seg["t_end"],
                    seg.get("description", ""),
                    ", ".join(seg.get("objects", [])),
                    seg.get("setting", ""),
                    seg.get("motion", ""),
                    seg.get("onscreen_text", ""),
                    seg.get("onscreen_text_en", ""),
                ),
            )
        for text in themes:
            conn.execute("INSERT INTO themes (video_id, text) VALUES (?, ?)", (video_id, text))
        for flag in quality_flags:
            conn.execute("INSERT INTO quality_flags (video_id, flag) VALUES (?, ?)", (video_id, flag))
        conn.execute(
            "UPDATE videos SET category_hint = ?, status = 'indexed', indexed_at = ?, model = ? WHERE id = ?",
            (category_hint, datetime.now(timezone.utc).isoformat(), model, video_id),
        )
        bump_search_generation(conn)
        conn.commit()

    def write_transcript(
        self, video_id: int, cues: list[TranscriptCue], lang: str | None
    ) -> None:
        conn = self.conn
        conn.execute("DELETE FROM transcript_segments WHERE video_id = ?", (video_id,))
        for cue in cues:
            conn.execute(
                "INSERT INTO transcript_segments (video_id, t_start, t_end, text) VALUES (?, ?, ?, ?)",
                (video_id, cue.t_start, cue.t_end, cue.text),
            )
        conn.execute(
            "UPDATE videos SET transcribed_at = ?, transcript_lang = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), lang, video_id),
        )
        bump_search_generation(conn)
        conn.commit()

    def get_transcript(self, video_id: int) -> list[TranscriptCue]:
        rows = self.conn.execute(
            "SELECT t_start, t_end, text FROM transcript_segments WHERE video_id = ? ORDER BY t_start",
            (video_id,),
        ).fetchall()
        return [TranscriptCue(t_start=r["t_start"], t_end=r["t_end"], text=r["text"]) for r in rows]

    # -- hybrid search (v4): CJK normalization + semantic embeddings ------

    _SEARCH_NORM_TABLES = {"segment": "segments", "transcript": "transcript_segments"}

    def get_segments(self, video_id: int) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM segments WHERE video_id = ? ORDER BY t_start", (video_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_transcript_segments(self, video_id: int) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM transcript_segments WHERE video_id = ? ORDER BY t_start", (video_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def update_search_norm(self, source: str, source_id: int, search_norm: str) -> None:
        table = self._SEARCH_NORM_TABLES.get(source)
        if table is None:
            raise ValueError(f"unknown search_norm source {source!r} (expected 'segment' or 'transcript')")
        self.conn.execute(f"UPDATE {table} SET search_norm = ? WHERE id = ?", (search_norm, source_id))
        # search_norm is one of the columns the vocabulary is built from, and an
        # UPDATE moves neither the row count nor the high-water mark.
        bump_search_generation(self.conn)
        self.conn.commit()

    def update_search_norms(self, rows: list[tuple[str, int, str]]) -> None:
        """One transaction for a whole video's normalized blobs (BROLL-IDX-8, 2026-08-14).

        Same writes as update_search_norm, and the generation bump is still in the
        same transaction as them — only the fsync-per-row and the repeated UPDATE of
        the single hot `meta` row go away. Shape borrowed from embed_transcripts.py,
        which has always batched this work.
        """
        if not rows:
            return
        by_table: dict[str, list[tuple[str, int]]] = {}
        for source, source_id, search_norm in rows:
            table = self._SEARCH_NORM_TABLES.get(source)
            if table is None:
                raise ValueError(
                    f"unknown search_norm source {source!r} (expected 'segment' or 'transcript')")
            by_table.setdefault(table, []).append((search_norm, source_id))
        for table, params in by_table.items():
            self.conn.executemany(
                f"UPDATE {table} SET search_norm = ? WHERE id = ?", params)
        bump_search_generation(self.conn)
        self.conn.commit()

    def upsert_embeddings(
        self, rows: list[tuple[str, int, int, str, int, bytes]]
    ) -> None:
        """One transaction for a whole video's vectors (BROLL-IDX-8, 2026-08-14)."""
        if not rows:
            return
        self.conn.executemany(
            "INSERT INTO embeddings (source, source_id, video_id, model, dim, vec) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(source, source_id) DO UPDATE SET "
            "video_id = excluded.video_id, model = excluded.model, dim = excluded.dim, vec = excluded.vec",
            rows,
        )
        # Same reason as the single-row arm: a replaced vector on the same rowid
        # is the one shape the readers' caches cannot see for themselves.
        bump_search_generation(self.conn)
        self.conn.commit()

    def get_embedding_models(self, video_id: int) -> dict[tuple[str, int], str]:
        rows = self.conn.execute(
            "SELECT source, source_id, model FROM embeddings WHERE video_id = ?", (video_id,)
        ).fetchall()
        return {(r["source"], r["source_id"]): r["model"] for r in rows}

    def upsert_embedding(
        self, source: str, source_id: int, video_id: int, model: str, dim: int, vec: bytes
    ) -> None:
        self.conn.execute(
            "INSERT INTO embeddings (source, source_id, video_id, model, dim, vec) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(source, source_id) DO UPDATE SET "
            "video_id = excluded.video_id, model = excluded.model, dim = excluded.dim, vec = excluded.vec",
            (source, source_id, video_id, model, dim, vec),
        )
        # The DO UPDATE arm is the exact shape the cache keys cannot see: same
        # row, same rowid, a different vector.
        bump_search_generation(self.conn)
        self.conn.commit()

    def record_moved(self, video_id: int, new_rel_path: str) -> None:
        self.conn.execute(
            "UPDATE videos SET rel_path = ?, in_inbox = 0, status = 'sorted' WHERE id = ?",
            (new_rel_path, video_id),
        )
        self.conn.commit()

    def all_themes(self) -> list[str]:
        rows = self.conn.execute("SELECT text FROM themes").fetchall()
        return [r["text"] for r in rows]

    def themes_with_video_ids(self) -> list[tuple[int, str]]:
        """(video_id, theme) for indexed videos only — rule-based category
        assignment needs to know WHICH clip each theme came from, which
        all_themes() (a flat bag for the taxonomy-proposal prompt) discards."""
        rows = self.conn.execute(
            "SELECT t.video_id, t.text FROM themes t "
            "JOIN videos v ON v.id = t.video_id WHERE v.status = 'indexed'"
        ).fetchall()
        return [(r["video_id"], r["text"]) for r in rows]

    def get_categories(self) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT slug, label, description FROM categories ORDER BY slug").fetchall()
        return [dict(r) for r in rows]

    def apply_taxonomy(self, categories: list[dict[str, Any]]) -> None:
        for c in categories:
            self.conn.execute(
                "INSERT INTO categories (slug, label, description) VALUES (:slug, :label, :description) "
                "ON CONFLICT(slug) DO UPDATE SET label = excluded.label, description = excluded.description",
                {"slug": c["slug"], "label": c["label"], "description": c.get("description", "")},
            )
        self.conn.commit()

    def push_shares(self, payload: list[dict]) -> None:
        """Write share roots straight to the table (no HTTP hop when co-located).

        Upsert, never delete: a share dropped from the config still has videos
        whose origin must stay resolvable at conform time.
        """
        now = datetime.now(timezone.utc).isoformat()
        for s in payload:
            self.conn.execute(
                "INSERT INTO share_roots (share, root, source, description, indexed, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(share) DO UPDATE SET root=excluded.root, "
                "source=excluded.source, description=excluded.description, "
                "indexed=excluded.indexed, updated_at=excluded.updated_at",
                (s["share"], s["root"], s.get("source", "originals"),
                 s.get("description", ""), int(s.get("indexed", True)), now),
            )
        self.conn.commit()
