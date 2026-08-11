"""Fresh-install schema.sql vs a real v1->v5 migration chain must land in the same
place, column-for-column, on `videos` (the table v5's duplicate-detection columns
land on). See schema.sql's fold-in of migrations/005_duplicates.sql and
broll_index/migrate.py's LATEST_VERSION."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from broll_index.migrate import LATEST_VERSION, migrate_sqlite_db
from test_migrate import V1_SCHEMA


def _table_info(conn: sqlite3.Connection, table: str) -> list[tuple]:
    return conn.execute(f"PRAGMA table_info({table})").fetchall()


def _index_names(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA index_list({table})").fetchall()}


def test_fresh_schema_is_at_latest_version(schema_path: Path):
    conn = sqlite3.connect(":memory:")
    conn.executescript(schema_path.read_text(encoding="utf-8"))
    assert conn.execute("PRAGMA user_version").fetchone()[0] == LATEST_VERSION == 10
    conn.close()


def test_fresh_vs_migrated_videos_table_column_parity(tmp_path: Path, schema_path: Path):
    fresh_conn = sqlite3.connect(":memory:")
    fresh_conn.executescript(schema_path.read_text(encoding="utf-8"))
    fresh_cols = _table_info(fresh_conn, "videos")
    fresh_indexes = _index_names(fresh_conn, "videos")
    fresh_conn.close()

    migrated_path = tmp_path / "migrated.db"
    conn = sqlite3.connect(str(migrated_path))
    conn.executescript(V1_SCHEMA)
    conn.close()
    report = migrate_sqlite_db(migrated_path)
    assert "applied" in report

    migrated_conn = sqlite3.connect(str(migrated_path))
    migrated_cols = _table_info(migrated_conn, "videos")
    migrated_indexes = _index_names(migrated_conn, "videos")
    migrated_conn.close()

    assert fresh_cols == migrated_cols
    assert fresh_indexes == migrated_indexes


def test_fresh_vs_migrated_meta_table_parity(tmp_path: Path, schema_path: Path):
    """Migration 010 adds `meta` and seeds `search_generation`. A fresh install
    that skipped the chain must land on the same table AND the same seed row --
    an unseeded counter would leave the web app's caches keying on a value that
    never moves (KNOWN_BUGS R2)."""
    fresh_conn = sqlite3.connect(":memory:")
    fresh_conn.executescript(schema_path.read_text(encoding="utf-8"))
    fresh_cols = _table_info(fresh_conn, "meta")
    fresh_seed = fresh_conn.execute(
        "SELECT key, value FROM meta ORDER BY key"
    ).fetchall()
    fresh_conn.close()

    migrated_path = tmp_path / "migrated.db"
    conn = sqlite3.connect(str(migrated_path))
    conn.executescript(V1_SCHEMA)
    conn.close()
    migrate_sqlite_db(migrated_path)

    migrated_conn = sqlite3.connect(str(migrated_path))
    migrated_cols = _table_info(migrated_conn, "meta")
    migrated_seed = migrated_conn.execute(
        "SELECT key, value FROM meta ORDER BY key"
    ).fetchall()
    migrated_conn.close()

    assert fresh_cols == migrated_cols
    assert fresh_seed == migrated_seed == [("search_generation", "0")]


def test_fresh_schema_videos_has_duplicate_detection_columns(schema_path: Path):
    conn = sqlite3.connect(":memory:")
    conn.executescript(schema_path.read_text(encoding="utf-8"))
    cols = {r[1] for r in conn.execute("PRAGMA table_info(videos)").fetchall()}
    assert {"full_hash", "duplicate_of"} <= cols
    indexes = _index_names(conn, "videos")
    assert {"idx_videos_hash", "idx_videos_full_hash", "idx_videos_duplicate_of"} <= indexes
    conn.close()
