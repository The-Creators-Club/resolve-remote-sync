"""CR-351 (2026-09-26): a busy thread made every report hold the write lock.

Three machines filed `slow_write` cards at once (6.2, 9.6 and up to 17.6 s)
with at most 12,000 media rows each, while the dashboard process sat at 122 %
CPU. The cause was executemany inside the write transaction: the sqlite3
module takes the GIL back for every row, and beside a CPU-bound thread each
take waits out the switch interval with the lock held. Measured on the live
NAS against a copy of dashboard.db, one 3,800-row editor_media replace: 0.08 s
quiet, 28 s beside one busy thread, 181 s beside two; as one json_each
statement 0.09 / 0.14 / 0.97 s.

What this file pins:

* `db.bulk_insert` stores exactly what the binding did (types, NULLs, a Mac's
  decomposed spelling byte for byte, big ints, order, ON CONFLICT tails);
* no report-path or collector-path replace calls executemany any more;
* beside a busy thread a 4,000-row replace stays fast;
* the `slow_write` card is fed the longest LOCK HOLD, not the handler's wall
  time, which also counted the report's own waits for somebody else's lock.
"""

from __future__ import annotations

import threading
import time
import unicodedata

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import api
from ccsync_dashboard import auth
from ccsync_dashboard import db as dbmod
from ccsync_dashboard import notices
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "s"
NOW = "2026-09-26T12:00:00+00:00"
NFD = unicodedata.normalize("NFD", "Matej Šimalčík")


class _NoExecutemany:
    """A connection that refuses executemany, delegating everything else."""

    def __init__(self, conn):
        self._conn = conn

    def executemany(self, *_a, **_k):
        raise AssertionError("executemany inside a write transaction (CR-351)")

    def __getattr__(self, name):
        return getattr(self._conn, name)


@pytest.fixture
def conn(tmp_path):
    c = dbmod.connect(tmp_path / "d.db")
    dbmod.migrate(c)
    yield c
    c.close()


# ----------------------------------------------------------- 1. bulk_insert

def test_bulk_insert_stores_what_binding_stored(conn):
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY AUTOINCREMENT, s TEXT, "
                 "i INTEGER, f REAL, n TEXT)")
    rows = [(NFD, 1_758_000_000_123_456_789, 1.5, None),
            ("台灣/地震園區/A014.braw", -1, 0.0, "x"),
            ("emoji 🎬 and 'quotes' \"too\"", 0, 2.25, None)]
    assert dbmod.bulk_insert(conn, "INSERT INTO t", ("s", "i", "f", "n"), rows) == 3
    got = conn.execute("SELECT s, i, f, n, typeof(i), typeof(f) FROM t ORDER BY id").fetchall()
    assert [tuple(r)[:4] for r in got] == rows            # and in the list's order
    assert got[0]["s"].encode() == NFD.encode()          # never normalised here
    assert {(r[4], r[5]) for r in got} == {("integer", "real")}


def test_bulk_insert_on_conflict_tail_and_empty_list(conn):
    conn.execute("CREATE TABLE u (k TEXT PRIMARY KEY, v INTEGER)")
    assert dbmod.bulk_insert(conn, "INSERT INTO u", ("k", "v"), []) == 0
    dbmod.bulk_insert(conn, "INSERT INTO u", ("k", "v"), [("a", 1), ("b", 2)])
    written = dbmod.bulk_insert(conn, "INSERT INTO u", ("k", "v"), [("a", 9), ("c", 3)],
                                tail="ON CONFLICT(k) DO NOTHING")
    assert written == 1
    assert dict(conn.execute("SELECT k, v FROM u").fetchall()) == {"a": 1, "b": 2, "c": 3}


def test_the_replaces_never_executemany(conn):
    guarded = _NoExecutemany(conn)
    dbmod.replace_editor_media(guarded, "ed", "m", "p",
                               [(NFD + ".mov", "original", 10), ("b.mov", "proxy", None)], NOW)
    dbmod.replace_media_tree(guarded, "ed", "m", "p",
                             [("Master/A", NFD, "P:/x.mov", "original", True)], NOW)
    dbmod.replace_active_transfers(guarded, "ed", "m", [
        {"lane": "a", "name": "x.mov", "direction": "up", "bytes_done": 5,
         "bytes_total": 10, "percentage": 50.0, "speed_bps": 1.5,
         "eta_seconds": 3, "project_slug": "p"}], NOW)
    dbmod.add_transfer_history(guarded, "ed", "m", [
        {"lane": "a", "name": "1.mov", "direction": "up", "at": NOW},
        {"lane": "a", "name": "2.mov", "direction": "up", "at": NOW}], NOW)
    dbmod.record_standins_placed(guarded, "ed", "m", [NFD, "x/y.mov"], NOW)
    half = ("vanished", "x.mov", 10, 123, "p", "2026/P", "x.mov", "/raw/x.mov")
    assert dbmod.record_pending_move_halves(guarded, [half], NOW) == 1
    assert dbmod.record_pending_move_halves(guarded, [half], NOW) == 0   # DO NOTHING
    assert dbmod.delete_pending_move_halves(
        guarded, [("vanished", "x.mov", 10, 123, "p", "x.mov")]) == 1

    # The rows are what the executemany wrote: rel keys normalised (CR-90),
    # clip names as sent, bools as ints, history in the order it arrived.
    assert {r[0] for r in conn.execute("SELECT rel_path FROM editor_media")} == {
        unicodedata.normalize("NFC", NFD + ".mov"), "b.mov"}
    clip = conn.execute("SELECT clip_name, present FROM media_tree_clips").fetchone()
    assert clip["clip_name"].encode() == NFD.encode() and clip["present"] == 1
    assert [r[0] for r in conn.execute(
        "SELECT name FROM transfer_history ORDER BY id")] == ["1.mov", "2.mov"]
    t = conn.execute("SELECT percentage, eta_seconds FROM active_transfers").fetchone()
    assert (t["percentage"], t["eta_seconds"]) == (50.0, 3)
    assert conn.execute("SELECT COUNT(*) FROM nas_media_pending_moves").fetchone()[0] == 0


def test_a_big_replace_stays_fast_beside_a_busy_thread(conn):
    """The live shape: 28 s per project with executemany beside ONE busy
    thread. The bound is loose on purpose (a slow CI box), and still an
    order of magnitude under what the old path takes."""
    files = [(f"Footage/clip_{i:05d}.mov", "original" if i % 2 else "proxy", i)
             for i in range(4000)]
    stop = threading.Event()

    def burn():
        while not stop.is_set():
            pass

    t = threading.Thread(target=burn, daemon=True)
    t.start()
    try:
        started = time.monotonic()
        dbmod.replace_editor_media(conn, "ed", "m", "p", files, NOW)
        conn.commit()
        took = time.monotonic() - started
    finally:
        stop.set()
        t.join()
    assert conn.execute("SELECT COUNT(*) FROM editor_media").fetchone()[0] == 4000
    assert took < 3.0, f"4,000-row replace took {took:.1f}s beside a busy thread"


# ------------------------------------------------ 2. what the card is fed

def _headers():
    return {"X-CCSync-Token": "sekrit",
            "X-CCSync-Identity": auth.make_identity_token(SECRET, "jsmith")}


def _payload():
    return {
        "editor_name": "jsmith", "machine": "EDIT-PC", "companion_version": "0.9.84",
        "reported_at": NOW,
        "lanes": [{"name": "lane_a_video_up", "state": "idle", "queued": 0,
                   "transferring": 0, "last_error": None, "last_sync": None,
                   "detail": None}],
        "local_manifest": {"2026/One": {"n_originals": 1, "bytes_originals": 10,
                                        "n_proxies": 0, "bytes_proxies": 0,
                                        "originals": [["a.mov", 10]]}},
    }


@pytest.fixture
def client(tmp_path, monkeypatch):
    # A lock hold "longer than a request waits" at test speed.
    monkeypatch.setattr(dbmod, "BUSY_TIMEOUT_MS", 100)
    db_path = tmp_path / "dash.db"
    app = create_app(Settings(db_path=str(db_path), report_token="sekrit",
                              session_secret=SECRET, admin_users=frozenset({"owen"})))
    with TestClient(app) as c:
        conn = dbmod.connect(db_path)
        yield c, conn
        conn.close()


def _slow_writes(conn):
    return [r for r in dbmod.open_notices(conn) if r["kind"] == notices.SLOW_WRITE_KIND]


def test_time_outside_a_transaction_is_not_a_lock_hold(client, monkeypatch):
    """The old card's number: wall time. A report that spent it OUTSIDE any
    transaction (here the slug lookup; live, waiting for somebody else's
    lock) was filed as the culprit of the wait it suffered."""
    c, conn = client
    real = api._slug_for_rel

    def slow_lookup(conn_, rel):
        time.sleep(0.3)
        return real(conn_, rel)

    monkeypatch.setattr(api, "_slug_for_rel", slow_lookup)
    assert c.post("/api/v1/report", json=_payload(), headers=_headers()).status_code == 200
    assert _slow_writes(conn) == []


def test_a_long_hold_is_filed_with_the_hold(client, monkeypatch):
    c, conn = client
    real = dbmod.replace_editor_media

    def slow_replace(*a, **k):
        time.sleep(0.3)
        return real(*a, **k)

    monkeypatch.setattr(dbmod, "replace_editor_media", slow_replace)
    assert c.post("/api/v1/report", json=_payload(), headers=_headers()).status_code == 200
    rows = _slow_writes(conn)
    assert [r["subject"] for r in rows] == ["report from jsmith/EDIT-PC"]
    assert "untick the projects" not in rows[0]["fix"]   # the old, wrong advice
