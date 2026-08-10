"""v0 -> v1: `tracks.share` lands on a database that already holds a library.

The real thing this protects is `music/web/data/music.db`: 376 tracks, 4263
windows, 6392 tags, written before `share` or `PRAGMA user_version` existed.
The migration must add the column in place -- ALTER TABLE ... ADD COLUMN, no
rebuild -- backfill every existing row to 'music', and be safe to run again on
every startup thereafter.

Built from a frozen copy of the v0 schema rather than from schema.sql, which
has moved on; the point of the fixture is to exercise the upgrade path from a
database that predates the column.
"""
import re
import sqlite3

import pytest

from musicweb import config, db


def _sql_without_comments(sql):
    return re.sub(r'--[^\n]*', '', sql)

# Frozen copy of schema.sql as it was before migrations/001_track_share.sql,
# i.e. no `share` column and no PRAGMA user_version at all. Do NOT update this
# to match the current schema.sql.
V0_SCHEMA_SQL = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS tracks (
    id          INTEGER PRIMARY KEY,
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
    t0          REAL,
    t1          REAL,
    embedding   BLOB,
    PRIMARY KEY (track_id, idx)
);

CREATE TABLE IF NOT EXISTS tags (
    track_id    INTEGER NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
    category    TEXT NOT NULL,
    label       TEXT NOT NULL,
    score       REAL,
    pct         REAL,
    rank        INTEGER,
    PRIMARY KEY (track_id, category, label)
);

CREATE TABLE IF NOT EXISTS meta (
    key         TEXT PRIMARY KEY,
    value       TEXT
);
"""


def _build_v0_db(path):
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(V0_SCHEMA_SQL)
    for i, rel in enumerate(['01HWP6E7E82AZ8NWEBKNGZX7PZ.mp3',
                             'ES_Tense Pulse.wav',
                             'sub dir/Winter Rain.flac'], start=1):
        con.execute('INSERT INTO tracks(id,rel_path,filename,bpm) VALUES(?,?,?,?)',
                    (i, rel, rel.rsplit('/', 1)[-1], 90.0 + i))
        con.execute('INSERT INTO windows(track_id,idx,t0,t1) VALUES(?,?,?,?)',
                    (i, 0, 0.0, 10.0))
    con.commit()
    return con


def test_v0_db_gains_share_without_losing_data(tmp_path):
    path = tmp_path / 'music.db'
    con = _build_v0_db(path)
    try:
        # the fixture is genuinely pre-share and pre-user_version
        assert con.execute('PRAGMA user_version').fetchone()[0] == 0
        assert 'share' not in db._columns(con, 'tracks')

        db.ensure_schema(con)

        assert con.execute('PRAGMA user_version').fetchone()[0] == db.CURRENT_SCHEMA_VERSION
        assert 'share' in db._columns(con, 'tracks')
        assert con.execute('SELECT COUNT(*) FROM tracks').fetchone()[0] == 3
        assert con.execute('SELECT COUNT(*) FROM windows').fetchone()[0] == 3
        # every existing row backfilled by the ALTER's own DEFAULT
        assert [r[0] for r in con.execute('SELECT DISTINCT share FROM tracks')] == ['music']
        # and the rest of the row is untouched
        r = con.execute('SELECT rel_path, filename, bpm FROM tracks WHERE id=3').fetchone()
        assert (r['rel_path'], r['filename'], r['bpm']) == (
            'sub dir/Winter Rain.flac', 'Winter Rain.flac', 93.0)
    finally:
        con.close()


def test_the_table_is_altered_in_place_not_rebuilt(tmp_path):
    """A rebuild would renumber rowids and break every foreign key pointing at
    them (windows, tags, axes, peaks all reference tracks(id))."""
    path = tmp_path / 'music.db'
    con = _build_v0_db(path)
    try:
        before = con.execute('SELECT id, rel_path FROM tracks ORDER BY id').fetchall()
        db.ensure_schema(con)
        after = con.execute('SELECT id, rel_path FROM tracks ORDER BY id').fetchall()
        assert [tuple(r) for r in after] == [tuple(r) for r in before]
    finally:
        con.close()


def test_migration_is_idempotent(tmp_path):
    """ensure_schema runs on every startup and on every new connection."""
    path = tmp_path / 'music.db'
    con = _build_v0_db(path)
    try:
        db.ensure_schema(con)
        db.ensure_schema(con)          # must not raise "duplicate column name"
        db.ensure_schema(con)
        assert con.execute('PRAGMA user_version').fetchone()[0] == db.CURRENT_SCHEMA_VERSION
        cols = [r[1] for r in con.execute('PRAGMA table_info(tracks)')]
        assert cols.count('share') == 1          # added once, not once per call
        assert con.execute('SELECT COUNT(*) FROM tracks').fetchone()[0] == 3
        assert [r[0] for r in con.execute('SELECT DISTINCT share FROM tracks')] == ['music']
    finally:
        con.close()


def test_a_db_that_already_grew_the_column_is_only_stamped(tmp_path):
    """user_version is younger than this database, so v0 cannot be trusted to
    mean "nothing applied" -- the ALTER runs only if the column is absent."""
    path = tmp_path / 'music.db'
    con = _build_v0_db(path)
    try:
        con.execute("ALTER TABLE tracks ADD COLUMN share TEXT NOT NULL DEFAULT 'music'")
        con.commit()
        assert con.execute('PRAGMA user_version').fetchone()[0] == 0

        db.ensure_schema(con)          # would raise if it ran the ALTER again

        assert con.execute('PRAGMA user_version').fetchone()[0] == db.CURRENT_SCHEMA_VERSION
        assert con.execute('SELECT COUNT(*) FROM tracks').fetchone()[0] == 3
    finally:
        con.close()


def test_a_db_stamped_current_but_missing_the_column_is_repaired(tmp_path):
    """The actual 2026-08-10 incident: schema.sql (which is re-applied to
    existing databases) carried `PRAGMA user_version = 1` and stamped the live
    376-track index to 1 without adding tracks.share. A purely version-driven
    runner then skips migration 001 forever. The migration's already-applied
    predicate, not the stamp, is what decides."""
    path = tmp_path / 'music.db'
    con = _build_v0_db(path)
    try:
        con.execute('PRAGMA user_version = 1')          # says v1
        con.commit()
        assert 'share' not in db._columns(con, 'tracks')  # but is not

        db.ensure_schema(con)

        assert 'share' in db._columns(con, 'tracks')
        assert [r[0] for r in con.execute('SELECT DISTINCT share FROM tracks')] == ['music']
        assert con.execute('SELECT COUNT(*) FROM tracks').fetchone()[0] == 3
    finally:
        con.close()


def test_schema_sql_never_stamps_a_version():
    """It is applied to existing databases, so a stamp in it marks an
    unmigrated database as current. ensure_schema owns the version."""
    assert 'user_version' not in _sql_without_comments(
        config.SCHEMA_PATH.read_text(encoding='utf-8'))


def test_a_fresh_db_gets_share_straight_from_schema_sql(tmp_path):
    """No migration involved: schema.sql already carries the column and stamps
    the version itself."""
    con = sqlite3.connect(tmp_path / 'fresh.db')
    try:
        db.ensure_schema(con)
        assert con.execute('PRAGMA user_version').fetchone()[0] == db.CURRENT_SCHEMA_VERSION
        assert 'share' in db._columns(con, 'tracks')
        con.execute("INSERT INTO tracks(rel_path,filename) VALUES('a.wav','a.wav')")
        assert con.execute('SELECT share FROM tracks').fetchone()[0] == 'music'
    finally:
        con.close()


def test_additive_tables_still_arrive_without_a_migration(tmp_path):
    """The v0 fixture has no peaks/axes/debias table; schema.sql is re-run on
    every open and that is how those landed on the live index."""
    path = tmp_path / 'music.db'
    con = _build_v0_db(path)
    try:
        db.ensure_schema(con)
        for table in ('peaks', 'axes', 'debias'):
            assert db._table_exists(con, table)
    finally:
        con.close()


def test_a_future_database_is_refused(tmp_path):
    """A database migrated by a newer app must not be limped along."""
    path = tmp_path / 'music.db'
    con = _build_v0_db(path)
    try:
        con.execute('PRAGMA user_version = 99')
        with pytest.raises(RuntimeError):
            db.ensure_schema(con)
    finally:
        con.close()


def test_every_registered_migration_exists_and_stops_at_the_current_version():
    """A file added to migrations/ but not to _MIGRATIONS (or vice versa) only
    breaks one of the two upgrade paths, and not the one you are testing."""
    assert max(db._MIGRATIONS) == db.CURRENT_SCHEMA_VERSION
    on_disk = sorted(p.name for p in config.MIGRATIONS_DIR.glob('*.sql'))
    assert sorted(name for name, _ in db._MIGRATIONS.values()) == on_disk
    for name, predicate in db._MIGRATIONS.values():
        assert (config.MIGRATIONS_DIR / name).exists()
        assert callable(predicate)
