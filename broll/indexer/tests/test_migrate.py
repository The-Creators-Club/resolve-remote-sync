from __future__ import annotations

import sqlite3

import pytest

from broll_index.migrate import LATEST_VERSION, MigrationError, migrate_sqlite_db

# The exact v1 DDL (schema.sql before the v2 on-screen-text change), used as a fixture to
# reproduce an existing pre-migration database. Do NOT read this from the repo-root
# schema.sql — that file is v2 now; this is deliberately frozen so the test still exercises
# a real v1 -> v2 upgrade regardless of future schema changes.
V1_SCHEMA = """
PRAGMA journal_mode = WAL;

CREATE TABLE videos (
    id          INTEGER PRIMARY KEY,
    share       TEXT NOT NULL,
    rel_path    TEXT NOT NULL,
    hash        TEXT,
    size_bytes  INTEGER,
    duration_s  REAL,
    fps         REAL,
    width       INTEGER,
    height      INTEGER,
    codec       TEXT,
    shot_date   TEXT,
    category    TEXT,
    category_hint TEXT,
    in_inbox    INTEGER NOT NULL DEFAULT 0,
    status      TEXT NOT NULL DEFAULT 'discovered',
    error       TEXT,
    indexed_at  TEXT,
    model       TEXT,
    UNIQUE (share, rel_path)
);

CREATE TABLE segments (
    id          INTEGER PRIMARY KEY,
    video_id    INTEGER NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    t_start     REAL NOT NULL,
    t_end       REAL NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    objects     TEXT NOT NULL DEFAULT '',
    setting     TEXT NOT NULL DEFAULT '',
    motion      TEXT NOT NULL DEFAULT ''
);
CREATE INDEX idx_segments_video ON segments(video_id);

CREATE VIRTUAL TABLE segments_fts USING fts5(
    description, objects, setting,
    content='segments', content_rowid='id',
    tokenize='porter unicode61'
);
CREATE TRIGGER segments_ai AFTER INSERT ON segments BEGIN
    INSERT INTO segments_fts(rowid, description, objects, setting)
    VALUES (new.id, new.description, new.objects, new.setting);
END;
CREATE TRIGGER segments_ad AFTER DELETE ON segments BEGIN
    INSERT INTO segments_fts(segments_fts, rowid, description, objects, setting)
    VALUES ('delete', old.id, old.description, old.objects, old.setting);
END;
CREATE TRIGGER segments_au AFTER UPDATE ON segments BEGIN
    INSERT INTO segments_fts(segments_fts, rowid, description, objects, setting)
    VALUES ('delete', old.id, old.description, old.objects, old.setting);
    INSERT INTO segments_fts(rowid, description, objects, setting)
    VALUES (new.id, new.description, new.objects, new.setting);
END;

CREATE TABLE themes (
    video_id    INTEGER NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    text        TEXT NOT NULL
);
CREATE INDEX idx_themes_video ON themes(video_id);

CREATE TABLE quality_flags (
    video_id    INTEGER NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    flag        TEXT NOT NULL
                CHECK (flag IN ('shaky','soft_focus','overexposed','underexposed','noisy','rolling_shutter'))
);
CREATE INDEX idx_flags_video ON quality_flags(video_id);

CREATE TABLE categories (
    slug        TEXT PRIMARY KEY,
    label       TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT ''
);

PRAGMA user_version = 1;
"""


@pytest.fixture
def v1_db(tmp_path):
    """A temp sqlite DB at schema v1, with one video + one segment already indexed."""
    path = tmp_path / "v1.db"
    conn = sqlite3.connect(str(path))
    conn.executescript(V1_SCHEMA)
    conn.execute(
        "INSERT INTO videos (share, rel_path, status) VALUES (?, ?, ?)",
        ("broll", "news/clip1.mov", "indexed"),
    )
    conn.execute(
        "INSERT INTO segments (video_id, t_start, t_end, description, objects, setting, motion) "
        "VALUES (1, 0.0, 8.0, 'a shootout scene', 'police, gun', 'street, night', 'static')"
    )
    conn.commit()
    conn.close()
    return path


def test_migrate_upgrades_v1_to_latest_preserving_rows(v1_db):
    report = migrate_sqlite_db(v1_db)
    assert "applied" in report
    # all four steps applied, in order, in one invocation
    assert "002_onscreen_text.sql" in report
    assert "003_transcripts.sql" in report
    assert "004_hybrid_search.sql" in report
    assert "005_duplicates.sql" in report
    assert report.index("002_onscreen_text.sql") < report.index("003_transcripts.sql")
    assert report.index("003_transcripts.sql") < report.index("004_hybrid_search.sql")
    assert report.index("004_hybrid_search.sql") < report.index("005_duplicates.sql")

    conn = sqlite3.connect(str(v1_db))
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == LATEST_VERSION == 10

        cols = {r[1] for r in conn.execute("PRAGMA table_info(segments)").fetchall()}
        assert "onscreen_text" in cols
        assert "onscreen_text_en" in cols
        assert "search_norm" in cols

        video_cols = {r[1] for r in conn.execute("PRAGMA table_info(videos)").fetchall()}
        assert "transcribed_at" in video_cols
        assert "transcript_lang" in video_cols
        assert "full_hash" in video_cols
        assert "duplicate_of" in video_cols

        transcript_cols = {r[1] for r in conn.execute("PRAGMA table_info(transcript_segments)").fetchall()}
        assert "search_norm" in transcript_cols

        indexes = {r[1] for r in conn.execute("PRAGMA index_list(videos)").fetchall()}
        assert "idx_videos_hash" in indexes
        assert "idx_videos_full_hash" in indexes
        assert "idx_videos_duplicate_of" in indexes

        row = conn.execute(
            "SELECT rel_path, status FROM videos WHERE id = 1"
        ).fetchone()
        assert row == ("news/clip1.mov", "indexed")  # pre-existing row untouched

        seg = conn.execute(
            "SELECT description, onscreen_text, onscreen_text_en, search_norm FROM segments WHERE video_id = 1"
        ).fetchone()
        assert seg[0] == "a shootout scene"  # pre-existing column untouched
        assert seg[1] == ""  # new column defaulted
        assert seg[2] == ""
        assert seg[3] == ""

        # new FTS/tables exist and are queryable
        conn.execute("SELECT * FROM segments_cjk_fts LIMIT 0")
        conn.execute("SELECT * FROM segments_fts LIMIT 0")
        conn.execute("SELECT * FROM transcript_segments LIMIT 0")
        conn.execute("SELECT * FROM transcript_fts LIMIT 0")
        conn.execute("SELECT * FROM transcript_cjk_fts LIMIT 0")
        conn.execute("SELECT * FROM embeddings LIMIT 0")

        # a real hit against the rebuilt FTS tables (rebuild ran as part of 004)
        hits = conn.execute(
            "SELECT rowid FROM segments_fts WHERE segments_fts MATCH 'shootout'"
        ).fetchall()
        assert len(hits) == 1
    finally:
        conn.close()


def test_migrate_is_idempotent(v1_db):
    first = migrate_sqlite_db(v1_db)
    assert "applied" in first

    second = migrate_sqlite_db(v1_db)
    assert "already at user_version 10" in second
    assert "nothing to do" in second

    conn = sqlite3.connect(str(v1_db))
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 10
        # still exactly one video, one segment — second run inserted nothing extra
        assert conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM segments").fetchone()[0] == 1
    finally:
        conn.close()


def test_migrate_fresh_db_is_a_no_op_not_an_upgrade(tmp_path):
    path = tmp_path / "fresh.db"
    report = migrate_sqlite_db(path)  # sqlite3.connect creates an empty file, user_version 0
    assert "user_version 0" in report

    conn = sqlite3.connect(str(path))
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 0
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert tables == set()  # migrate did not create any schema
    finally:
        conn.close()


def test_migrate_uses_bundled_fallback_when_repo_root_migrations_missing(v1_db, monkeypatch):
    import broll_index.migrate as migrate_mod

    # Simulate an installed package without the repo checked out: point the repo-root
    # lookup at a directory that doesn't have the migration file, forcing the fallback.
    monkeypatch.setattr(migrate_mod, "_REPO_ROOT_MIGRATIONS_DIR", migrate_mod._BUNDLED_MIGRATIONS_DIR.parent / "nope")
    report = migrate_mod.migrate_sqlite_db(v1_db)
    assert "applied" in report
    assert "002_onscreen_text.sql" in report
    assert "003_transcripts.sql" in report
    assert "004_hybrid_search.sql" in report
    assert "005_duplicates.sql" in report
    conn = sqlite3.connect(str(v1_db))
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 10
        conn.execute("SELECT * FROM embeddings LIMIT 0")
        video_cols = {r[1] for r in conn.execute("PRAGMA table_info(videos)").fetchall()}
        assert "full_hash" in video_cols and "duplicate_of" in video_cols
    finally:
        conn.close()


def test_migrate_missing_migration_file_raises_clear_error(v1_db, monkeypatch):
    import broll_index.migrate as migrate_mod

    monkeypatch.setattr(migrate_mod, "_REPO_ROOT_MIGRATIONS_DIR", migrate_mod._BUNDLED_MIGRATIONS_DIR.parent / "nope")
    monkeypatch.setattr(migrate_mod, "_BUNDLED_MIGRATIONS_DIR", migrate_mod._BUNDLED_MIGRATIONS_DIR.parent / "also-nope")
    with pytest.raises(MigrationError, match="not found"):
        migrate_mod.migrate_sqlite_db(v1_db)
