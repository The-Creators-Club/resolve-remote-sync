"""Storage layer: percentile ranks, blob round-trips, thread-local connections."""
import os
import sqlite3
import threading
import time

import numpy as np
import pytest

from musicweb import db


def test_percentile_ranks_span_the_range():
    p = db.percentile_ranks([1, 2, 3, 4, 5])
    assert p[0] == 0.0 and p[-1] == 100.0


def test_ties_get_the_same_rank():
    p = db.percentile_ranks([1, 1, 2, 2])
    assert p[0] == p[1] and p[2] == p[3]


def test_percentile_edge_cases():
    assert db.percentile_ranks([]).size == 0
    assert list(db.percentile_ranks([7.0])) == [50.0]


def test_blob_round_trip():
    v = np.array([0.5, -0.25, 1.0], dtype=np.float32)
    assert np.array_equal(db.from_blob(db.to_blob(v)), v)


def test_con_is_per_thread(seeded_db):
    """A sqlite3 connection may only be used on the thread that created it;
    FastAPI dispatches sync endpoints across a threadpool, so sharing one
    raises "SQLite objects created in a thread can only be used in that same
    thread" as soon as two requests land on different workers."""
    got = {}

    def grab(key):
        got[key] = db.con()

    t1 = threading.Thread(target=grab, args=('a',))
    t2 = threading.Thread(target=grab, args=('b',))
    t1.start(); t1.join()
    t2.start(); t2.join()
    assert got['a'] is not got['b']
    assert db.con() is db.con()          # same thread reuses its own


def test_only_one_thread_runs_the_migrations(seeded_db, monkeypatch):
    """MUSIC-11 (2026-08-11): `_schema_ready` was an unlocked global, so two
    threads whose first request landed together both ran the migrations. On the
    request that upgrades a live database the loser got `duplicate column name`
    and 500'd -- once, on the one deploy where it mattered."""
    ran = []
    real_init = db.init

    def slow_init(c):
        # widen the window the old code raced in: without the lock, seven other
        # threads walk straight past the flag while this one is still working
        ran.append(threading.current_thread().name)
        time.sleep(0.05)
        real_init(c)

    monkeypatch.setattr(db, 'init', slow_init)
    monkeypatch.setattr(db, '_schema_ready', False)

    errors = []

    def open_one():
        try:
            db.con().execute('SELECT COUNT(*) FROM tracks').fetchone()
        except Exception as exc:                                # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=open_one) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, errors
    assert len(ran) == 1, f'migrations ran {len(ran)} times: {ran}'
    assert db._schema_ready is True


# --- MUSIC-10: a REPLACED database file, not a rewritten one ------------------

def _isolated_pool(monkeypatch, path):
    """A con() cache of this test's own, pointed at `path`."""
    monkeypatch.setattr(db.config, 'DB_PATH', path)
    monkeypatch.setattr(db, '_local', threading.local())
    monkeypatch.setattr(db, '_schema_ready', False)


def test_invalidate_reopens_the_database_by_path(tmp_path, monkeypatch):
    """A sqlite3 connection is bound to an INODE, not to a path. The deploy
    ships a new index by renaming the live music.db aside and moving the staged
    copy in, so every cached connection went on reading the unlinked old file
    and /api/reload rebuilt the matrices from it -- a 200 with the old numbers
    (MUSIC-10, 2026-08-14).

    The swap is done here by repointing DB_PATH rather than by renaming: the
    rename is what the NAS does, and Windows will not rename a file that this
    process still has open -- which is the same "the connection still holds
    it" fact from the other side.
    """
    live, staged = tmp_path / 'music.db', tmp_path / 'staged.db'
    _isolated_pool(monkeypatch, live)

    first = db.con()
    first.execute("INSERT INTO tracks(rel_path,filename) VALUES('a.wav','a.wav')")
    first.commit()

    fresh = db.connect(staged)
    db.init(fresh)
    for rel in ('a.wav', 'b.wav'):
        fresh.execute('INSERT INTO tracks(rel_path,filename) VALUES(?,?)', (rel, rel))
    fresh.commit()
    fresh.close()
    monkeypatch.setattr(db.config, 'DB_PATH', staged)

    # cached: the request thread is still on the old database, as it was
    assert db.con() is first
    assert first.execute('SELECT COUNT(*) FROM tracks').fetchone()[0] == 1

    db.invalidate()
    after = db.con()
    assert after is not first
    assert after.execute('SELECT COUNT(*) FROM tracks').fetchone()[0] == 2


def test_invalidate_closes_nothing_another_thread_is_using(tmp_path, monkeypatch):
    """Each thread drops its OWN connection, on its next con(). Closing one
    from here would break whatever request is mid-query on it."""
    _isolated_pool(monkeypatch, tmp_path / 'music.db')
    invalidated = threading.Event()
    done = threading.Event()
    errors = []

    def worker():
        c = db.con()
        invalidated.wait(timeout=5)
        try:
            c.execute('SELECT COUNT(*) FROM tracks').fetchone()   # still open
            assert db.con() is not c                              # next one is fresh
        except Exception as exc:                                  # noqa: BLE001
            errors.append(exc)
        finally:
            done.set()

    t = threading.Thread(target=worker)
    t.start()
    time.sleep(0.05)
    db.invalidate()
    invalidated.set()
    t.join(timeout=5)
    assert done.is_set() and not errors, errors


# --- music-2: nobody calls invalidate() after a publish ------------------------

def test_a_file_replaced_at_the_same_path_is_noticed_without_api_reload(
        tmp_path, monkeypatch):
    """MUSIC-10 taught /api/reload to drop the cached connections. Nothing
    taught anything else to (music-2, 2026-08-21): `publish_db.py --which music
    --apply` swaps the index by rename and restarts nothing, and anyio hands
    the next request the most recently idle thread -- which on a dashboard
    polled every 2 s never dies. Browse, facets, audio lookups and search all
    went on answering from the deleted inode, indefinitely.
    """
    live, staged = tmp_path / 'music.db', tmp_path / 'staged.db'
    _isolated_pool(monkeypatch, live)
    monkeypatch.setattr(db, '_open_identity', None)

    first = db.con()
    first.execute("INSERT INTO tracks(rel_path,filename) VALUES('a.wav','a.wav')")
    first.commit()
    assert db.con() is first             # a second request, same thread, cached

    fresh = db.connect(staged)
    db.init(fresh)
    for rel in ('a.wav', 'b.wav'):
        fresh.execute('INSERT INTO tracks(rel_path,filename) VALUES(?,?)', (rel, rel))
    fresh.commit()
    fresh.close()
    # Windows will not replace a file this process holds open, and what is
    # under test is the STAT, not the handle -- so the cached connection is
    # closed by hand here. It is still the cached one: only con() replaces it.
    first.close()
    os.replace(staged, live)

    after = db.con()
    assert after is not first
    assert after.execute('SELECT COUNT(*) FROM tracks').fetchone()[0] == 2


def test_repointing_the_path_is_not_a_swap(tmp_path, monkeypatch):
    """Only "this path now names a different file" is a swap. An eval sweep or
    a test that repoints DB_PATH has changed database, and must not be able to
    close connections it does not own (music-2, 2026-08-21)."""
    one, two = tmp_path / 'one.db', tmp_path / 'two.db'
    _isolated_pool(monkeypatch, one)
    monkeypatch.setattr(db, '_open_identity', None)

    first = db.con()
    assert db.con() is first
    other = db.connect(two)
    db.init(other)
    other.close()
    monkeypatch.setattr(db.config, 'DB_PATH', two)
    assert db.con() is first


def test_file_state_changes_when_another_process_writes(tmp_path, monkeypatch):
    """The fingerprint search.index() watches. A drain apply commits from its
    own connection, so the -wal half is what moves first on a busy container."""
    live = tmp_path / 'music.db'
    _isolated_pool(monkeypatch, live)
    con = db.con()
    con.execute("INSERT INTO tracks(rel_path,filename) VALUES('a.wav','a.wav')")
    con.commit()
    before = db.file_state()

    other = db.connect(live)
    other.execute("INSERT INTO tracks(rel_path,filename) VALUES('b.wav','b.wav')")
    other.commit()
    other.close()

    assert before is not None
    assert db.file_state() != before


# --- MUSIC-3: a row whose file has gone ---------------------------------------

def _library(path, rel_paths):
    con = db.connect(path)
    db.init(con)
    for i, rel in enumerate(rel_paths, start=1):
        con.execute('INSERT INTO tracks(id,rel_path,filename,embedding,dim) '
                    'VALUES(?,?,?,?,?)', (i, rel, rel, db.to_blob([0.5] * 4), 4))
        con.execute('INSERT INTO windows(track_id,idx,t0,t1,embedding) '
                    'VALUES(?,0,0.0,10.0,?)', (i, db.to_blob([0.5] * 4)))
        con.execute('INSERT INTO tags(track_id,category,label,score,pct,rank) '
                    "VALUES(?,'mood','tense',0.5,50.0,1)", (i,))
        con.execute("INSERT INTO axes(track_id,axis,raw,pct) VALUES(?,'arousal',0.1,50.0)",
                    (i,))
        con.execute('INSERT INTO peaks(track_id,n,data) VALUES(?,1,?)', (i, b'\x01'))
    con.commit()
    return con


def test_prune_deletes_the_ghost_and_everything_hanging_off_it(tmp_path):
    """A renamed cue used to leave its old row forever: it ranked in search,
    skewed every other track's percentile, and previewed correctly off its
    id-keyed proxy -- the only place it failed was the companion, with "file
    not found ... is the share mounted?" (MUSIC-3, 2026-08-14)."""
    con = _library(tmp_path / 'ghosts.db', ['a.wav', 'b.wav', '12345_67.aac'])
    try:
        gone = db.prune_missing(con, ['a.wav', 'b.wav', 'Neon City.aac'])

        assert gone == ['12345_67.aac']
        assert [r[0] for r in con.execute('SELECT rel_path FROM tracks ORDER BY id')] \
            == ['a.wav', 'b.wav']
        for table in ('windows', 'tags', 'axes', 'peaks'):
            left = con.execute(f'SELECT COUNT(*) FROM {table} WHERE track_id=3'
                               ).fetchone()[0]
            assert left == 0, f'{table} kept the pruned track'
    finally:
        con.close()


def test_prune_is_a_no_op_when_every_file_is_still_there(tmp_path):
    con = _library(tmp_path / 'intact.db', ['a.wav', 'b.wav'])
    try:
        assert db.prune_missing(con, ['a.wav', 'b.wav', 'new.wav']) == []
        assert con.execute('SELECT COUNT(*) FROM tracks').fetchone()[0] == 2
    finally:
        con.close()


def test_prune_refuses_an_empty_scan(tmp_path):
    """A share that is not mounted looks exactly like a library somebody
    emptied, and this is the one operation here that destroys embeddings."""
    con = _library(tmp_path / 'unmounted.db', ['a.wav', 'b.wav'])
    try:
        with pytest.raises(db.PruneRefused):
            db.prune_missing(con, [])
        assert con.execute('SELECT COUNT(*) FROM tracks').fetchone()[0] == 2
    finally:
        con.close()


def test_prune_refuses_a_bulk_disappearance_unless_forced(tmp_path):
    rels = [f'{i}.wav' for i in range(20)]
    con = _library(tmp_path / 'bulk.db', rels)
    try:
        with pytest.raises(db.PruneRefused):
            db.prune_missing(con, rels[:5])
        assert con.execute('SELECT COUNT(*) FROM tracks').fetchone()[0] == 20

        gone = db.prune_missing(con, rels[:5], force=True)
        assert len(gone) == 15
        assert con.execute('SELECT COUNT(*) FROM tracks').fetchone()[0] == 5
    finally:
        con.close()


def test_prune_refuses_without_the_cascade(tmp_path):
    """Foreign keys off would orphan windows/tags/axes/peaks instead."""
    con = _library(tmp_path / 'nofk.db', ['a.wav', 'b.wav'])
    try:
        con.execute('PRAGMA foreign_keys=OFF')
        with pytest.raises(db.PruneRefused):
            db.prune_missing(con, ['a.wav'])
    finally:
        con.close()


# --- MUSIC-4: a scratch copy for anything that scribbles ----------------------

def test_backup_to_copies_the_committed_index(tmp_path):
    """eval.py --sweep re-scores tags per alpha, and write_scores starts with
    DELETE FROM tags -- against the live index, which is the file that ships
    (MUSIC-4, 2026-08-14). It works on one of these now."""
    con = _library(tmp_path / 'live.db', ['a.wav', 'b.wav'])
    try:
        copy_path = db.backup_to(con, tmp_path / 'scratch' / 'sweep.db')
        assert copy_path.is_file()

        copy = db.connect(copy_path)
        try:
            assert copy.execute('SELECT COUNT(*) FROM tracks').fetchone()[0] == 2
            copy.execute('DELETE FROM tags')
            copy.commit()
        finally:
            copy.close()

        # the scribble stayed in the copy
        assert con.execute('SELECT COUNT(*) FROM tags').fetchone()[0] == 2
    finally:
        con.close()


def test_load_matrix_shapes(seeded_db):
    con = db.connect()
    ids, mat = db.load_matrix(con)
    assert len(ids) == mat.shape[0] == 4
    tids, wmat = db.load_window_matrix(con)
    assert wmat.shape[0] == len(tids) == 8
    assert db.load_debias(con).shape == (1, mat.shape[1])
    con.close()
