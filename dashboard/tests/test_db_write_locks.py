"""Who holds the write lock, and for how long (2026-09-03 "database is
locked", api_report held the lock).

Twelve distinct `sqlite3.OperationalError: database is locked` failures in 27
minutes on the live studio dashboard, every victim blocked on its
transaction's FIRST write: the session touch, the collector's file-move
reconcile, another machine's report. The holder was api_report -- ONE write
transaction that looped `replace_editor_media` (DELETE + up to 2000 rows) and
`replace_media_tree` (up to 4000) for every ticked project, per machine, every
60 s, on ZFS with synchronous=FULL.

What this file pins:

* the report is N short locks now, not one long one -- and the fleet state is
  committed before the media loops even start;
* every connection runs synchronous=NORMAL, and the two background
  connections (the collector's, the session store's) wait longer for the lock
  than a request's does;
* neither a notice check's syscall on the NAS mount nor an alert's network
  call sits inside an open write transaction;
* a slow poll and a slow report say so in the log, because nothing used to
  time either and the log could not name the pass that was holding the lock.
"""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import alerts
from ccsync_dashboard import api
from ccsync_dashboard import auth
from ccsync_dashboard import collector as collector_mod
from ccsync_dashboard import db as dbmod
from ccsync_dashboard import notices
from ccsync_dashboard import sessions as sessions_mod
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "s"
NOW = "2026-09-03T12:00:00+00:00"


def report_headers(editor="jsmith", token="sekrit"):
    return {"X-CCSync-Token": token,
            "X-CCSync-Identity": auth.make_identity_token(SECRET, editor)}


def payload(**extra):
    body = {
        "editor_name": "JSmith",
        "machine": "EDIT-PC",
        "companion_version": "0.9.65",
        "reported_at": NOW,
        "lanes": [
            {"name": "lane_a_video_up", "state": "idle", "queued": 0, "transferring": 0,
             "last_error": None, "last_sync": None, "detail": None},
        ],
    }
    body.update(extra)
    return body


TWO_PROJECTS = {
    "2026/One": {"n_originals": 1, "bytes_originals": 10,
                 "n_proxies": 0, "bytes_proxies": 0,
                 "originals": [["a.mov", 10]]},
    "2026/Two": {"n_originals": 1, "bytes_originals": 10,
                 "n_proxies": 0, "bytes_proxies": 0,
                 "originals": [["b.mov", 10]]},
}


@pytest.fixture
def env(tmp_path):
    db_path = tmp_path / "dash.db"
    app = create_app(Settings(db_path=str(db_path), report_token="sekrit",
                              session_secret=SECRET, admin_users=frozenset({"owen"})))
    with TestClient(app) as client:
        conn = dbmod.connect(db_path)
        yield client, conn, str(db_path), app.state.settings
        conn.close()


# ------------------------------------------------- 1. the report's own locks

def _probe(db_path, sql, args=()):
    """Read the file from a SECOND connection, i.e. see only what is
    COMMITTED. WAL, so this never waits on the writer."""
    probe = dbmod.connect(db_path)
    try:
        return probe.execute(sql, args).fetchone()[0]
    finally:
        probe.close()


def test_the_report_commits_the_fleet_state_before_it_touches_the_media(env, monkeypatch):
    """The lane rows, machine_state and the live transfers are durable before
    the first big DELETE + executemany opens its lock."""
    _client, _conn, db_path, _settings = env
    client = _client
    seen: list[int] = []
    real = dbmod.replace_editor_media

    def spy(conn, editor, machine, slug, files, now):
        seen.append(_probe(db_path,
                           "SELECT COUNT(*) FROM machine_state WHERE machine = ?",
                           ("EDIT-PC",)))
        return real(conn, editor, machine, slug, files, now)

    monkeypatch.setattr(dbmod, "replace_editor_media", spy)
    resp = client.post("/api/v1/report", json=payload(local_manifest=TWO_PROJECTS),
                       headers=report_headers())
    assert resp.status_code == 200
    assert len(seen) == 2
    assert seen[0] == 1, "the fleet state was still uncommitted when the media loop began"


def test_the_report_commits_after_each_project(env, monkeypatch):
    """One project, one short lock. A machine with thirty ticked projects
    must not be thirty projects' worth of rows under a single lock."""
    client, _conn, db_path, _settings = env
    seen: list[int] = []
    real = dbmod.replace_editor_media

    def spy(conn, editor, machine, slug, files, now):
        seen.append(_probe(db_path,
                           "SELECT COUNT(DISTINCT project_slug) FROM editor_media"))
        return real(conn, editor, machine, slug, files, now)

    monkeypatch.setattr(dbmod, "replace_editor_media", spy)
    resp = client.post("/api/v1/report", json=payload(local_manifest=TWO_PROJECTS),
                       headers=report_headers())
    assert resp.status_code == 200
    assert seen == [0, 1], "the first project's rows were still uncommitted"


def test_the_report_still_stores_everything_it_was_sent(env):
    """The contract change is atomicity, not content: a report that succeeds
    writes exactly what it always did."""
    client, conn, _db_path, _settings = env
    resp = client.post("/api/v1/report", json=payload(local_manifest=TWO_PROJECTS),
                       headers=report_headers())
    assert resp.status_code == 200
    assert conn.execute("SELECT COUNT(*) FROM editor_media").fetchone()[0] == 2
    assert conn.execute(
        "SELECT COUNT(*) FROM editor_media_project").fetchone()[0] == 2
    assert conn.execute(
        "SELECT COUNT(*) FROM lane_report_current").fetchone()[0] == 1


def test_a_slow_report_says_so_in_the_log(env, monkeypatch, caplog):
    client, _conn, _db_path, _settings = env
    monkeypatch.setattr(api, "SLOW_REPORT_SECONDS", -1.0)
    with caplog.at_level(logging.INFO, logger="ccsync.dashboard.api"):
        client.post("/api/v1/report", json=payload(local_manifest=TWO_PROJECTS),
                    headers=report_headers())
    assert any("to write" in r.getMessage() and "2 project manifests" in r.getMessage()
               for r in caplog.records)


# ------------------------------------------------------------ 2/3. connections

def test_every_connection_runs_synchronous_normal(tmp_path):
    conn = dbmod.connect(tmp_path / "a.db")
    try:
        assert conn.execute("PRAGMA synchronous").fetchone()[0] == 1
    finally:
        conn.close()


def test_a_request_waits_five_seconds_and_a_background_thread_waits_longer(tmp_path):
    conn = dbmod.connect(tmp_path / "a.db")
    try:
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == dbmod.BUSY_TIMEOUT_MS
    finally:
        conn.close()
    assert dbmod.BUSY_TIMEOUT_BACKGROUND_MS >= 15000

    settings = Settings(db_path=str(tmp_path / "a.db"))
    conn = collector_mod.Collector(settings, client=object())._open_conn()
    try:
        assert (conn.execute("PRAGMA busy_timeout").fetchone()[0]
                == dbmod.BUSY_TIMEOUT_BACKGROUND_MS)
    finally:
        conn.close()

    conn = sessions_mod.SessionStore(tmp_path / "a.db")._connect()
    try:
        assert (conn.execute("PRAGMA busy_timeout").fetchone()[0]
                == dbmod.BUSY_TIMEOUT_BACKGROUND_MS)
    finally:
        conn.close()


# ------------------------------------------------------- 4. the notice checks

def test_no_notice_check_runs_inside_an_open_write_transaction(env, monkeypatch):
    """_check_tree stats and lists the NAS mount; _check_dashboard_space calls
    disk_usage. Both used to run with the write lock held by whichever check
    wrote a notice first."""
    _client, conn, _db_path, settings = env
    inside: dict[str, bool] = {}
    for name in ("_check_tree", "_check_dashboard_space"):
        real = getattr(notices, name)

        def spy(conn_, settings_, now, _real=real, _name=name):
            inside[_name] = bool(conn_.in_transaction)
            return _real(conn_, settings_, now)

        monkeypatch.setattr(notices, name, spy)

    notices.run_checks(conn, settings, NOW)
    assert inside == {"_check_tree": False, "_check_dashboard_space": False}


def test_the_checks_still_all_run_and_are_committed(env):
    _client, conn, db_path, settings = env
    ran = notices.run_checks(conn, settings, NOW)
    assert ran >= 8
    assert not conn.in_transaction
    # Visible from a second connection, i.e. actually committed.
    _probe(db_path, "SELECT COUNT(*) FROM notices")


# ------------------------------------------------------------- 5. the alerts

class _WatchingOpener:
    """Records whether a write transaction was open when the POST went out."""

    def __init__(self, conn):
        self.conn = conn
        self.in_transaction: list[bool] = []

    def open(self, request, timeout=None):     # noqa: A003 - urllib's name
        self.in_transaction.append(bool(self.conn.in_transaction))
        return _FakeResponse()


class _FakeResponse:
    status = 200

    def read(self, *_a, **_k):
        return b"{}"

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


def test_no_alert_is_sent_with_the_write_lock_held(env, monkeypatch):
    _client, conn, _db_path, settings = env
    alerts.set_settings(conn, {"alerts_sink": "webhook",
                               "alerts_webhook_url": "https://alerts.example.test/hook"},
                        "owen")
    conn.commit()
    opener = _WatchingOpener(conn)
    monkeypatch.setattr(alerts, "_webhook_opener", lambda: opener)

    findings = [
        {"kind": "breaker_tripped", "subject": "jsmith/EDIT-PC", "severity": "error",
         "diagnosis": "one", "fix": "do a thing"},
        {"kind": "breaker_tripped", "subject": "jsmith/OTHER-PC", "severity": "error",
         "diagnosis": "two", "fix": "do a thing"},
    ]
    result = alerts.deliver(conn, settings, findings, NOW)
    assert result["sent"] == 2
    # More than two POSTs go out: this cycle also RECOVERS every subject left
    # open by the fixture's own boot. Every one of them matters -- each was a
    # network call under the write lock.
    assert len(opener.in_transaction) >= 2
    assert not any(opener.in_transaction)
    # Each attempt is durable as it happens, not at the end of the cycle.
    assert len(dbmod.fetch_alerts(conn, limit=50)) >= 2


# ------------------------------------------------------- 6. instrumentation

def test_a_slow_poll_says_so_in_the_log(env, monkeypatch, caplog):
    _client, conn, db_path, settings = env
    monkeypatch.setattr(collector_mod, "SLOW_POLL_SECONDS", -1.0)
    c = collector_mod.Collector(settings, client=object())
    with caplog.at_level(logging.INFO, logger="ccsync.dashboard.collector"):
        assert c._timed(conn, "prune", lambda _conn: None) is True
    assert any("poll prune took" in r.getMessage() for r in caplog.records)


def test_a_quick_poll_stays_quiet(env, caplog):
    _client, conn, _db_path, settings = env
    c = collector_mod.Collector(settings, client=object())
    with caplog.at_level(logging.INFO, logger="ccsync.dashboard.collector"):
        c._timed(conn, "prune", lambda _conn: None)
    assert not any("poll prune took" in r.getMessage() for r in caplog.records)
