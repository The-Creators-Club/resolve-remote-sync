"""A busy database is contention, not a defect (2026-09-17).

The field report the CR-240i ledger note said to wait for: the live
dashboard's home page carried "9 time(s) a request to /api/v1/report failed
with an error (OperationalError) ... database is locked", every one at
clear_report_refused -- the FIRST write of a report, so the request had
waited its whole busy timeout (5 s) and somebody else still held the write
lock. That was recorded as a server error whose fix line says "send the
detail to support", and the container log that could have named the long
writer was gone at the next recreate.

Now: the handler answers such a request 503 + Retry-After (a companion's
next cycle lands by itself), counts it under a warn notice of its own kind,
and the long writers -- a report over the busy timeout, a collector poll
over it -- record THEMSELVES as 'slow write' notices, so the survivable
record says who held the lock, not only who lost the wait.
"""
from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth, notices
from ccsync_dashboard import db as dbmod
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "test-secret"
NOW = "2026-09-15T10:00:00Z"


@pytest.fixture
def conn(tmp_path):
    c = dbmod.connect(tmp_path / "dash.db")
    dbmod.migrate(c)
    yield c
    c.close()


def _rows(conn, kind):
    return [dict(r) for r in conn.execute(
        "SELECT kind, severity, subject, body, fix FROM notices WHERE kind=? "
        "ORDER BY id", (kind,))]


def test_only_the_lock_is_busy():
    assert notices.is_db_busy(sqlite3.OperationalError("database is locked"))
    assert not notices.is_db_busy(sqlite3.OperationalError("disk I/O error"))
    assert not notices.is_db_busy(RuntimeError("database is locked"))


def test_a_busy_wait_is_one_warn_notice_counted_never_an_error(conn):
    notices.record_db_busy(conn, "/api/v1/report", now=NOW, route="/api/v1/report")
    notices.record_db_busy(conn, "/api/v1/report", now=NOW, route="/api/v1/report")
    rows = _rows(conn, notices.DB_BUSY_KIND)
    assert len(rows) == 1
    assert rows[0]["severity"] == "warn"
    assert rows[0]["body"].startswith("2 time(s) a request to /api/v1/report waited")
    assert "told to try again" in rows[0]["body"]
    assert "slow write" in rows[0]["fix"]
    assert _rows(conn, "server_error") == []


def test_a_slow_writer_names_itself_with_its_last_duration(conn):
    notices.record_slow_write(conn, "report from alex/creator-1", 7.3, now=NOW)
    notices.record_slow_write(conn, "report from alex/creator-1", 12.0, now=NOW)
    notices.record_slow_write(conn, "collector poll reconcile", 6.1, now=NOW)
    rows = _rows(conn, notices.SLOW_WRITE_KIND)
    assert [r["subject"] for r in rows] == ["report from alex/creator-1",
                                            "collector poll reconcile"]
    assert rows[0]["body"].startswith("2 time(s) report from alex/creator-1 held")
    assert "12.0 s" in rows[0]["body"]
    assert all(r["severity"] == "warn" for r in rows)


def _make(tmp_path):
    return Settings(db_path=str(tmp_path / "busy.db"), session_secret=SECRET,
                    admin_users=frozenset({"admin"}))


def test_the_handler_answers_a_locked_database_503_with_retry_after(tmp_path):
    settings = _make(tmp_path)
    app = create_app(settings)

    @app.get("/api/v1/locked")
    def locked():
        raise sqlite3.OperationalError("database is locked")

    with TestClient(app, raise_server_exceptions=False) as client:
        client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "admin"))
        r = client.get("/api/v1/locked")
    assert r.status_code == 503
    assert r.headers.get("retry-after") == "30"
    assert "busy" in r.json()["detail"] and "try again" in r.json()["detail"]
    c = dbmod.connect(settings.db_path)
    try:
        busy = _rows(c, notices.DB_BUSY_KIND)
        assert len(busy) == 1 and busy[0]["subject"] == "/api/v1/locked (database busy)"
        assert _rows(c, "server_error") == []
    finally:
        c.close()


def test_any_other_operational_error_is_still_a_server_error(tmp_path):
    settings = _make(tmp_path)
    app = create_app(settings)

    @app.get("/api/v1/broken")
    def broken():
        raise sqlite3.OperationalError("disk I/O error")

    with TestClient(app, raise_server_exceptions=False) as client:
        client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "admin"))
        r = client.get("/api/v1/broken")
    assert r.status_code == 500
    assert r.json() == {"detail": "internal error"}
    c = dbmod.connect(settings.db_path)
    try:
        assert len(_rows(c, "server_error")) == 1
        assert _rows(c, notices.DB_BUSY_KIND) == []
    finally:
        c.close()
