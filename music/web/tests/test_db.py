"""Storage layer: percentile ranks, blob round-trips, thread-local connections."""
import sqlite3
import threading
import time

import numpy as np

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


def test_load_matrix_shapes(seeded_db):
    con = db.connect()
    ids, mat = db.load_matrix(con)
    assert len(ids) == mat.shape[0] == 4
    tids, wmat = db.load_window_matrix(con)
    assert wmat.shape[0] == len(tids) == 8
    assert db.load_debias(con).shape == (1, mat.shape[1])
    con.close()
