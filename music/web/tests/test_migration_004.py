"""v3 -> v4: the ingest batch ledger lands on a database that already exists.

The database this protects is the live one on the NAS: 376 tracks, an
`ingest_queue` with editors' uploads in it, and `user_version = 3`. Migration
004 adds two tables and must not touch a byte of any of that -- in particular
`ingest_queue` STAYS, because it is the fallback the plan deliberately keeps
(a companion with no CLAP sidecar uploads and lets the base rig drain it).

The fixture is built from the v3 END STATE rather than from schema.sql, which
has moved on: the point is the upgrade path from a database that predates
these tables.
"""
import sqlite3

import pytest

from musicweb import config, db, ingest_batches

# schema.sql as it stood at user_version = 3 -- tracks with `share`,
# ingest_queue with `uid`, and no ingest_batches/ingest_items. Do NOT update
# this to match the current schema.sql.
V3_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS tracks (
    id          INTEGER PRIMARY KEY,
    share       TEXT NOT NULL DEFAULT 'music',
    rel_path    TEXT UNIQUE NOT NULL,
    filename    TEXT NOT NULL,
    ext         TEXT,
    bytes       INTEGER,
    duration    REAL,
    samplerate  INTEGER,
    channels    INTEGER,
    codec       TEXT,
    bpm         REAL,
    music_key   TEXT,
    key_conf    REAL,
    lufs        REAL,
    peak_db     REAL,
    embedding   BLOB,
    dim         INTEGER,
    file_hash   TEXT,
    model       TEXT,
    analyzed_at TEXT
);
CREATE TABLE IF NOT EXISTS windows (
    track_id    INTEGER NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
    idx         INTEGER NOT NULL,
    t0          REAL, t1 REAL, embedding BLOB,
    PRIMARY KEY (track_id, idx)
);
CREATE TABLE IF NOT EXISTS tags (
    track_id    INTEGER NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
    category    TEXT NOT NULL, label TEXT NOT NULL,
    score REAL, pct REAL, rank INTEGER,
    PRIMARY KEY (track_id, category, label)
);
CREATE TABLE IF NOT EXISTS axes (
    track_id    INTEGER NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
    axis TEXT NOT NULL, raw REAL, pct REAL,
    PRIMARY KEY (track_id, axis)
);
CREATE TABLE IF NOT EXISTS peaks (
    track_id INTEGER PRIMARY KEY REFERENCES tracks(id) ON DELETE CASCADE,
    n INTEGER, data BLOB
);
CREATE TABLE IF NOT EXISTS debias (idx INTEGER PRIMARY KEY, vec BLOB);
CREATE TABLE IF NOT EXISTS ingest_queue (
    id           INTEGER PRIMARY KEY,
    uid          TEXT,
    share        TEXT NOT NULL DEFAULT 'music',
    rel_path     TEXT UNIQUE NOT NULL,
    orig_name    TEXT NOT NULL,
    bytes        INTEGER,
    duration     REAL,
    content_hash TEXT,
    transcoded   INTEGER NOT NULL DEFAULT 0,
    state        TEXT NOT NULL DEFAULT 'pending'
                 CHECK (state IN ('pending', 'done', 'failed')),
    error        TEXT,
    attempts     INTEGER NOT NULL DEFAULT 0,
    track_id     INTEGER REFERENCES tracks(id) ON DELETE SET NULL,
    queued_at    TEXT NOT NULL,
    updated_at   TEXT
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
PRAGMA user_version = 3;
"""


def _build_v3_db(path):
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(V3_SCHEMA_SQL)
    con.execute("INSERT INTO tracks(id, rel_path, filename, bpm) "
                "VALUES(1,'ES_Tense Pulse.wav','ES_Tense Pulse.wav',128.0)")
    con.execute("INSERT INTO ingest_queue(id, uid, rel_path, orig_name, state, "
                "queued_at) VALUES(7,'"
                + 'b' * 32 + "','Queued Cue.wav','Queued Cue.wav','pending',"
                "'2026-08-18T00:00:00+00:00')")
    con.commit()
    return con


def test_v3_gains_the_two_tables_and_loses_nothing(tmp_path):
    con = _build_v3_db(tmp_path / 'music.db')
    try:
        assert con.execute('PRAGMA user_version').fetchone()[0] == 3
        assert not db._table_exists(con, 'ingest_items')

        db.ensure_schema(con)

        assert con.execute('PRAGMA user_version').fetchone()[0] == 4
        assert db._table_exists(con, 'ingest_batches')
        assert db._table_exists(con, 'ingest_items')
        # the library and the QUEUE are untouched -- the queue is the fallback
        # path, not a thing this migration replaces
        assert con.execute('SELECT COUNT(*) c FROM tracks').fetchone()['c'] == 1
        row = con.execute('SELECT * FROM ingest_queue WHERE id=7').fetchone()
        assert row['state'] == 'pending' and row['uid'] == 'b' * 32
    finally:
        con.close()


def test_the_migration_is_idempotent(tmp_path):
    """ensure_schema runs on every startup AND on every new connection."""
    con = _build_v3_db(tmp_path / 'music.db')
    try:
        db.ensure_schema(con)
        db.ensure_schema(con)
        db.ensure_schema(con)
        assert con.execute('PRAGMA user_version').fetchone()[0] == 4
        assert con.execute("SELECT COUNT(*) c FROM sqlite_master WHERE "
                           "name='ingest_items'").fetchone()['c'] == 1
    finally:
        con.close()


def test_a_db_stamped_4_but_missing_the_tables_is_repaired(tmp_path):
    """The 2026-08-10 lesson, applied to this migration: user_version is the
    fast record and the already-applied predicate is the truth. A stray stamp
    must not skip the tables forever."""
    con = _build_v3_db(tmp_path / 'music.db')
    try:
        con.execute('PRAGMA user_version = 4')
        con.commit()
        db.ensure_schema(con)
        assert db._table_exists(con, 'ingest_items')
    finally:
        con.close()


def test_a_fresh_db_gets_the_tables_straight_from_schema_sql(tmp_path):
    """No migration involved: schema.sql already carries them, and the two
    copies must not have drifted."""
    con = sqlite3.connect(tmp_path / 'fresh.db')
    con.row_factory = sqlite3.Row
    try:
        db.ensure_schema(con)
        assert con.execute('PRAGMA user_version').fetchone()[0] == 4
        for table in ('ingest_batches', 'ingest_items'):
            assert db._table_exists(con, table)
    finally:
        con.close()


def test_the_two_definitions_of_the_tables_agree(tmp_path):
    """schema.sql (a fresh database) and migrations/004 (an upgraded one) must
    produce the SAME columns. They are two files, and the day they disagree the
    difference only shows up on whichever kind of database the operator has."""
    fresh = sqlite3.connect(tmp_path / 'fresh.db')
    fresh.row_factory = sqlite3.Row
    db.ensure_schema(fresh)

    upgraded = _build_v3_db(tmp_path / 'upgraded.db')
    db.ensure_schema(upgraded)

    try:
        for table in ('ingest_batches', 'ingest_items'):
            a = [(r[1], r[2], r[3], r[4]) for r in
                 fresh.execute(f'PRAGMA table_info({table})')]
            b = [(r[1], r[2], r[3], r[4]) for r in
                 upgraded.execute(f'PRAGMA table_info({table})')]
            assert a == b, table
    finally:
        fresh.close()
        upgraded.close()


def test_an_upgraded_db_enforces_the_same_state_check(tmp_path):
    con = _build_v3_db(tmp_path / 'music.db')
    db.ensure_schema(con)
    try:
        con.execute("INSERT INTO ingest_batches(uid, editor, settings_json, "
                    "created_at) VALUES('u','jsmith','{}','now')")
        con.execute("INSERT INTO ingest_items(uid, batch_uid, ord, orig_name, "
                    "source, state, updated_at) "
                    "VALUES('i','u',0,'x.wav','upload','embedding','now')")
        with pytest.raises(sqlite3.IntegrityError):
            con.execute("INSERT INTO ingest_items(uid, batch_uid, ord, orig_name, "
                        "source, state, updated_at) "
                        "VALUES('j','u',1,'y.wav','upload','banana','now')")
    finally:
        con.close()


def test_the_migration_file_is_the_version_it_stamps():
    """The runner is told version 4 lives in this file; the file says so too.
    A mismatch stamps a database with a version whose migration never ran."""
    name, _predicate = db._MIGRATIONS[4]
    assert name == '004_ingest_batches.sql'
    sql = (config.MIGRATIONS_DIR / name).read_text(encoding='utf-8')
    assert 'PRAGMA user_version = 4' in sql
    assert db.CURRENT_SCHEMA_VERSION == 4


def test_the_check_constraint_lists_exactly_the_code_s_item_states(tmp_path):
    """The migration's CHECK and `ingest_batches.ITEM_STATES` are two
    statements of one list; a state the code writes and the table refuses is a
    500 in a fleet call."""
    sql = (config.MIGRATIONS_DIR / '004_ingest_batches.sql').read_text(encoding='utf-8')
    for state in ingest_batches.ITEM_STATES:
        assert f"'{state}'" in sql, state
    for state in ingest_batches.BATCH_STATES:
        assert f"'{state}'" in sql, state
