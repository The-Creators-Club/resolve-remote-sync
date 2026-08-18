"""v1 -> v4 stepped migration: on-screen text (v2), transcript tables (v3),
search_norm + embeddings (v4), all applied in one ensure_schema() call.

Builds a DB from the *old* v1 schema (fixture DDL below, frozen at the point
schema.sql was v1 -- this is deliberately NOT read from schema.sql/
migrations/, since those have moved on), seeds it directly (bypassing the app
entirely, the way an existing production DB would look), then runs the same
startup migration path main.py uses (app.db.ensure_schema) and asserts:

- PRAGMA user_version ends at 4 (CURRENT_SCHEMA_VERSION), in one call, even
  though the DB started at v1 -- the stepped loop walks 1->2->3->4 without
  any intermediate ensure_schema() calls.
- Pre-existing segments survive, with onscreen_text/onscreen_text_en and
  search_norm defaulted to '' (not NULL, not dropped).
- All four FTS tables (segments_fts, segments_cjk_fts, transcript_fts,
  transcript_cjk_fts) exist and return correct hits after the migrations'
  DROP + recreate + rebuild -- proving the 'rebuild' steps actually
  repopulate them from the surviving segments rows.
- transcript_segments and embeddings tables exist and are queryable (a v1 DB
  has neither).
"""
from __future__ import annotations

import sqlite3
import struct

import pytest

from app.db import CURRENT_SCHEMA_VERSION, ensure_schema

# Frozen copy of schema.sql as it was at user_version=1, i.e. before
# migrations/002_onscreen_text.sql existed. Do NOT update this to match the
# current schema.sql -- the whole point of this fixture is to exercise the
# upgrade path from a real pre-existing v1 database.
V1_SCHEMA_SQL = """
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


def _build_v1_db(db_path) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(V1_SCHEMA_SQL)
        conn.execute(
            "INSERT INTO videos (id, share, rel_path, category) VALUES (1, 'broll', 'news/clip_1.mov', 'news')"
        )
        conn.execute(
            """
            INSERT INTO segments (id, video_id, t_start, t_end, description, objects, setting, motion)
            VALUES (1, 1, 0.0, 8.0,
                    'Police briefing outside a courthouse',
                    'police officer, press conference, courthouse, reporters',
                    'urban, daytime', 'static')
            """
        )
        conn.commit()
    finally:
        conn.close()


def test_v1_to_v4_migration_in_one_startup(tmp_path):
    db_path = tmp_path / "broll.db"
    _build_v1_db(db_path)

    # Sanity check on the fixture itself before migrating.
    pre_conn = sqlite3.connect(db_path)
    assert pre_conn.execute("PRAGMA user_version").fetchone()[0] == 1
    pre_conn.close()

    ensure_schema(db_path)  # one call, must walk 1 -> 2 -> 3 -> 4

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        # Asserted against the constant, not a literal: this test is about the
        # stepped chain reaching the latest version in one call, and hardcoding
        # the number means every schema bump breaks it for no real reason.
        assert conn.execute("PRAGMA user_version").fetchone()[0] == CURRENT_SCHEMA_VERSION

        # Pre-existing segment survives, with every column added by v2/v4
        # defaulted to '' (not NULL, not dropped).
        row = conn.execute("SELECT * FROM segments WHERE id = 1").fetchone()
        assert row is not None
        assert row["description"] == "Police briefing outside a courthouse"
        assert row["onscreen_text"] == ""
        assert row["onscreen_text_en"] == ""
        assert row["search_norm"] == ""

        # segments_fts (porter unicode61) still finds the old data after
        # two rounds of DROP + recreate + rebuild.
        en_hit = conn.execute(
            "SELECT s.id FROM segments s JOIN segments_fts ON segments_fts.rowid = s.id "
            "WHERE segments_fts MATCH ?",
            ('"courthouse"',),
        ).fetchall()
        assert [r["id"] for r in en_hit] == [1]

        # segments_cjk_fts (trigram) exists and returns a substring hit
        # against the surviving `objects` column.
        cjk_hit = conn.execute(
            "SELECT s.id FROM segments s JOIN segments_cjk_fts ON segments_cjk_fts.rowid = s.id "
            "WHERE segments_cjk_fts MATCH ?",
            ('"press conf"',),
        ).fetchall()
        assert [r["id"] for r in cjk_hit] == [1]

        # v3: transcript_segments + its dual FTS exist and are queryable
        # (a v1 DB has none of this).
        conn.execute(
            "INSERT INTO transcript_segments (id, video_id, t_start, t_end, text) "
            "VALUES (1, 1, 0.0, 5.0, 'suspect named in the raid')"
        )
        conn.commit()
        t_hit = conn.execute(
            "SELECT ts.id FROM transcript_segments ts "
            "JOIN transcript_fts ON transcript_fts.rowid = ts.id "
            "WHERE transcript_fts MATCH ?",
            ('"suspect"',),
        ).fetchall()
        assert [r["id"] for r in t_hit] == [1]
        assert conn.execute(
            "SELECT text FROM transcript_segments WHERE id = 1"
        ).fetchone()["text"] == "suspect named in the raid"

        cjk_t_hit_table_exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='transcript_cjk_fts'"
        ).fetchone()
        assert cjk_t_hit_table_exists is not None

        # v4: embeddings table exists and is queryable (insert + select a
        # real float32 blob round-trips correctly).
        vec = struct.pack("<3f", 0.1, 0.2, 0.3)
        conn.execute(
            "INSERT INTO embeddings (source, source_id, video_id, model, dim, vec) "
            "VALUES ('segment', 1, 1, 'test-model', 3, ?)",
            (vec,),
        )
        conn.commit()
        emb_row = conn.execute(
            "SELECT source, source_id, video_id, model, dim, vec FROM embeddings "
            "WHERE source = 'segment' AND source_id = 1"
        ).fetchone()
        assert emb_row["video_id"] == 1
        assert emb_row["dim"] == 3
        assert struct.unpack("<3f", emb_row["vec"]) == pytest.approx((0.1, 0.2, 0.3))
    finally:
        conn.close()


def test_migration_is_idempotent_at_v4(tmp_path):
    """Once fully migrated, calling ensure_schema again must be a no-op, not an error."""
    db_path = tmp_path / "broll.db"
    _build_v1_db(db_path)
    ensure_schema(db_path)
    ensure_schema(db_path)  # should not raise

    conn = sqlite3.connect(db_path)
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == CURRENT_SCHEMA_VERSION
    finally:
        conn.close()


def test_migration_seeds_the_search_generation_counter(tmp_path):
    """v10 (migrations/010_search_generation.sql): both the stepped chain and a
    from-scratch schema.sql application must leave `meta.search_generation`
    seeded. The counter is what lets the semantic/fuzzy caches see a re-index
    that lands the same number of rows on the same rowids (KNOWN_BUGS R2); an
    absent or unseeded row would silently put them back on
    (count, MAX(rowid)) alone.
    """
    migrated = tmp_path / "migrated.db"
    _build_v1_db(migrated)
    ensure_schema(migrated)

    scratch = tmp_path / "scratch.db"
    ensure_schema(scratch)

    for db_path in (migrated, scratch):
        conn = sqlite3.connect(db_path)
        try:
            assert conn.execute(
                "SELECT value FROM meta WHERE key = 'search_generation'"
            ).fetchone() == ("0",), db_path
        finally:
            conn.close()


def test_migration_011_adds_the_ingest_tables_on_both_paths(tmp_path):
    """v10 -> v11 (migrations/011_ingest_batches.sql), and the from-scratch
    schema.sql twin, must produce the SAME tables and the same columns.

    The two paths are how a real database and a fresh one get here, and they
    have diverged before -- a version added in one describer and not the other
    produces a startup failure on exactly one of them (app/db.py's own
    docstring says so). Column-for-column rather than "the table exists":
    `share_roots.collection` missing from the fresh path would make
    creators_shares fall back on every new deployment, and a whole customer's
    own footage would file itself under Downloads with nothing in a log.
    """
    migrated = tmp_path / "migrated.db"
    _build_v1_db(migrated)
    ensure_schema(migrated)

    scratch = tmp_path / "scratch.db"
    ensure_schema(scratch)

    shapes = []
    for db_path in (migrated, scratch):
        conn = sqlite3.connect(db_path)
        try:
            assert conn.execute("PRAGMA user_version").fetchone()[0] == 11, db_path
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'")}
            assert "ingest_batches" in tables, db_path
            assert "ingest_items" in tables, db_path
            indexes = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'")}
            assert {"idx_ingest_batches_editor", "idx_ingest_batches_state",
                    "idx_ingest_items_batch", "idx_ingest_items_video"} <= indexes, db_path
            shape = {}
            for table in ("ingest_batches", "ingest_items", "share_roots", "videos"):
                shape[table] = sorted(
                    (r[1], r[2].upper(), r[3], r[4])
                    for r in conn.execute(f"PRAGMA table_info({table})"))
            shapes.append(shape)
            assert "collection" in [c[0] for c in shape["share_roots"]], db_path
        finally:
            conn.close()
    assert shapes[0] == shapes[1], (
        "the stepped chain and schema.sql describe different databases -- "
        "migrations/011_ingest_batches.sql and schema.sql have drifted")


def test_the_ingest_state_checks_are_enforced_by_the_database(tmp_path):
    """The CHECK constraints are the last line, not decoration: the fleet
    routes validate transitions, and a bug there must still not be able to
    write a state nothing downstream can read (the tray, the grid chip and the
    SPA all switch on these strings)."""
    db_path = tmp_path / "broll.db"
    ensure_schema(db_path)
    conn = sqlite3.connect(db_path)
    try:
        # Before any statement opens a transaction: SQLite silently ignores
        # this pragma inside one, and a cascade test that never had foreign
        # keys on is a test that passes for the wrong reason.
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            "INSERT INTO ingest_batches (uid, editor, share, settings_json, created_at) "
            "VALUES ('a', 'jsmith', 'shoot', '{}', 'now')")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE ingest_batches SET state = 'nonsense' WHERE uid = 'a'")
        conn.execute(
            "INSERT INTO ingest_items (uid, batch_uid, ord, orig_name, source) "
            "VALUES ('i', 'a', 0, 'A001.MP4', 'upload')")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE ingest_items SET state = 'nonsense' WHERE uid = 'i'")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO ingest_items (uid, batch_uid, ord, orig_name, source) "
                "VALUES ('j', 'a', 1, 'B.MP4', 'telepathy')")
        # ...and the cascade: deleting a batch must not leave orphan items
        # behind for a later batch's counters to pick up.
        conn.execute("DELETE FROM ingest_batches WHERE uid = 'a'")
        assert conn.execute("SELECT COUNT(*) FROM ingest_items").fetchone()[0] == 0
    finally:
        conn.close()


def test_ensure_schema_rejects_future_version(tmp_path):
    db_path = tmp_path / "broll.db"
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA user_version = 99")
    conn.commit()
    conn.close()

    with pytest.raises(RuntimeError):
        ensure_schema(db_path)


def test_ensure_schema_from_scratch_reaches_v4(tmp_path):
    """v0 -> full schema.sql application (lands on v3, schema.sql predates
    the v4 migration) -> the stepped loop continues it on to v4."""
    db_path = tmp_path / "broll.db"
    ensure_schema(db_path)
    conn = sqlite3.connect(db_path)
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == CURRENT_SCHEMA_VERSION
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
            ).fetchall()
        }
        assert "segments_fts" in tables
        assert "segments_cjk_fts" in tables
        assert "transcript_segments" in tables
        assert "transcript_fts" in tables
        assert "transcript_cjk_fts" in tables
        assert "embeddings" in tables

        # search_norm columns exist on both tables (schema-level check --
        # actual population is the indexer's job, out of scope here).
        seg_cols = {r[1] for r in conn.execute("PRAGMA table_info(segments)").fetchall()}
        assert "search_norm" in seg_cols
        tr_cols = {
            r[1] for r in conn.execute("PRAGMA table_info(transcript_segments)").fetchall()
        }
        assert "search_norm" in tr_cols
    finally:
        conn.close()
