"""Small helpers for seeding a test DB directly (bypassing the API)."""
from __future__ import annotations

import sqlite3
import struct
from typing import Any


def insert_video(conn: sqlite3.Connection, **kwargs: Any) -> int:
    defaults: dict[str, Any] = {
        "share": "broll",
        "rel_path": "misc/clip.mov",
        "hash": None,
        "size_bytes": None,
        "duration_s": 10.0,
        "fps": 24.0,
        "width": 1920,
        "height": 1080,
        "codec": "h264",
        "shot_date": None,
        "category": None,
        "category_hint": None,
        "in_inbox": 0,
        "status": "indexed",
    }
    defaults.update(kwargs)
    cols = ", ".join(defaults.keys())
    placeholders = ", ".join("?" for _ in defaults)
    cur = conn.execute(
        f"INSERT INTO videos ({cols}) VALUES ({placeholders})",
        list(defaults.values()),
    )
    conn.commit()
    return cur.lastrowid


def insert_segment(conn: sqlite3.Connection, video_id: int, **kwargs: Any) -> int:
    defaults: dict[str, Any] = {
        "video_id": video_id,
        "t_start": 0.0,
        "t_end": 5.0,
        "description": "",
        "objects": "",
        "setting": "",
        "motion": "",
        "onscreen_text": "",
        "onscreen_text_en": "",
    }
    defaults.update(kwargs)
    defaults["video_id"] = video_id
    cols = ", ".join(defaults.keys())
    placeholders = ", ".join("?" for _ in defaults)
    cur = conn.execute(
        f"INSERT INTO segments ({cols}) VALUES ({placeholders})",
        list(defaults.values()),
    )
    conn.commit()
    return cur.lastrowid


def insert_transcript_segment(conn: sqlite3.Connection, video_id: int, **kwargs: Any) -> int:
    defaults: dict[str, Any] = {
        "video_id": video_id,
        "t_start": 0.0,
        "t_end": 5.0,
        "text": "",
    }
    defaults.update(kwargs)
    defaults["video_id"] = video_id
    cols = ", ".join(defaults.keys())
    placeholders = ", ".join("?" for _ in defaults)
    cur = conn.execute(
        f"INSERT INTO transcript_segments ({cols}) VALUES ({placeholders})",
        list(defaults.values()),
    )
    conn.commit()
    return cur.lastrowid


def insert_embedding(
    conn: sqlite3.Connection,
    *,
    source: str,
    source_id: int,
    video_id: int,
    vec: list[float],
    model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
) -> None:
    """`vec` should already be L2-normalized if the test cares about cosine
    scores being meaningful (matches migration 004: vectors are stored
    normalized so brute-force search can use a plain dot product)."""
    blob = struct.pack(f"<{len(vec)}f", *vec)
    conn.execute(
        "INSERT INTO embeddings (source, source_id, video_id, model, dim, vec) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (source, source_id, video_id, model, len(vec), blob),
    )
    conn.commit()


def insert_flag(conn: sqlite3.Connection, video_id: int, flag: str) -> None:
    conn.execute(
        "INSERT INTO quality_flags (video_id, flag) VALUES (?, ?)", (video_id, flag)
    )
    conn.commit()


def insert_theme(conn: sqlite3.Connection, video_id: int, text: str) -> None:
    conn.execute("INSERT INTO themes (video_id, text) VALUES (?, ?)", (video_id, text))
    conn.commit()


def insert_category(conn: sqlite3.Connection, slug: str, label: str, description: str = "") -> None:
    conn.execute(
        "INSERT INTO categories (slug, label, description) VALUES (?, ?, ?)",
        (slug, label, description),
    )
    conn.commit()
