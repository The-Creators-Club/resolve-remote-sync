"""The ninth fleet hunt's dashboard-side highs (2026-09-18).

dash-api-2 (= dash-db-3 = dash-core-2), res-fleet-1 and dash-cards-1. Each
test is named for the behaviour it pins; the finding id is in the docstring
and at the code site.
"""
from __future__ import annotations

import sqlite3
import threading
import time

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth, db as dbmod, notices
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "test-secret-not-a-real-one"


def _settings(tmp_path, **over):
    kwargs = dict(db_path=str(tmp_path / "hunt.db"), session_secret=SECRET,
                  admin_users=frozenset({"admin"}))
    kwargs.update(over)
    return Settings(**kwargs)


# ---------------------------------------------------------------------------
# dash-api-2: the busy handler must not do its own blocking write on the loop
# ---------------------------------------------------------------------------


def test_the_busy_notice_is_written_off_the_event_loop(tmp_path, monkeypatch):
    """dash-api-2: `unhandled_error` is `async def`, so on a --workers 1
    container its body runs ON the event loop - and the branch that gets here
    is the one whose precondition is that somebody has held the write lock
    longer than the busy timeout already. The second connection, INSERT and
    commit therefore blocked the whole loop for another busy timeout (5.4 s
    measured) and then raised `database is locked` itself, swallowed: every
    companion report and htmx poll stalled behind it, and the notice the
    rework exists to write was the one that did not get written."""
    settings = _settings(tmp_path)
    app = create_app(settings)
    threads = {}

    @app.get("/api/v1/locked-async")
    async def locked():
        # An `async def` route runs on the event loop, so this IS the loop's
        # thread, which is what the record must not be made on.
        threads["loop"] = threading.get_ident()
        raise sqlite3.OperationalError("database is locked")

    real_record = notices.record_db_busy

    def record(conn, *args, **kwargs):
        threads["record"] = threading.get_ident()
        return real_record(conn, *args, **kwargs)

    monkeypatch.setattr(notices, "record_db_busy", record)

    with TestClient(app, raise_server_exceptions=False) as client:
        client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "admin"))
        r = client.get("/api/v1/locked-async")

    assert r.status_code == 503
    assert threads["record"] != threads["loop"]


def test_a_held_write_lock_does_not_make_the_503_wait_for_it(tmp_path):
    """The same defect, priced: with the lock really held, the answer used to
    cost another full busy timeout. The notice may be lost (it is logged);
    the 503 must not wait."""
    settings = _settings(tmp_path)
    app = create_app(settings)

    @app.get("/api/v1/locked-contended")
    def locked():
        raise sqlite3.OperationalError("database is locked")

    with TestClient(app, raise_server_exceptions=False) as client:
        # Inside the lifespan: the schema exists only once the app has booted.
        holder = dbmod.connect(settings.db_path)
        try:
            holder.execute("BEGIN IMMEDIATE")
            holder.execute("UPDATE meta SET value=value WHERE key='schema_version'")
            client.cookies.set(auth.COOKIE_NAME,
                               auth.make_session_cookie(SECRET, "admin"))
            started = time.monotonic()
            r = client.get("/api/v1/locked-contended")
            elapsed = time.monotonic() - started
        finally:
            holder.rollback()
            holder.close()

    assert r.status_code == 503
    # The default busy timeout is 5 s and the handler used to pay it in full.
    assert elapsed < 2.0, f"the 503 waited {elapsed:.1f}s on the database"


def test_a_server_error_notice_is_written_off_the_loop_too(tmp_path, monkeypatch):
    """The branch one hunk down has the same shape and the same fix."""
    settings = _settings(tmp_path)
    app = create_app(settings)
    threads = {}

    @app.get("/api/v1/broken-async")
    async def broken():
        threads["loop"] = threading.get_ident()
        raise sqlite3.OperationalError("disk I/O error")

    real_record = notices.record_server_error

    def record(conn, *args, **kwargs):
        threads["record"] = threading.get_ident()
        return real_record(conn, *args, **kwargs)

    monkeypatch.setattr(notices, "record_server_error", record)

    with TestClient(app, raise_server_exceptions=False) as client:
        client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "admin"))
        r = client.get("/api/v1/broken-async")

    assert r.status_code == 500
    assert threads["record"] != threads["loop"]


# ---------------------------------------------------------------------------
# res-fleet-1: the pinned-job executor must be started when Cards is mounted
# ---------------------------------------------------------------------------


def test_the_pinned_executor_starts_even_though_no_episode_is_open(tmp_path,
                                                                   monkeypatch):
    """res-fleet-1: `PinnedExecutor.start()` was un-gated for the lazily built
    engine pool, but its caller still read `if executor.available():`, which at
    boot asks a pool with no engines and gets None. So the drain thread was
    never created and `release_pinned_jobs()` never ran - while `jobs.can_pin`
    asks the same object later, after an editor has opened an episode, and
    answers yes. A spent job then goes `pinned` with no worker, is not
    `abandoned`, and waits for ever."""
    from ccsync_dashboard import cards, cards_exec

    settings = _settings(tmp_path)
    started = {}

    def fake_mount(app, s):
        # What a mounted Cards with no open episode looks like: a pool object
        # on app.state whose any_engine() is None.
        class _EmptyPool:
            def any_engine(self):
                return None

        app.state.cards_pool = _EmptyPool()
        app.state.cards_engine = None
        return cards.MOUNTED, "mounted (test)"

    monkeypatch.setattr(cards, "mount_cards", fake_mount)
    real_start = cards_exec.PinnedExecutor.start

    def start(self):
        started["called"] = True
        return real_start(self)

    monkeypatch.setattr(cards_exec.PinnedExecutor, "start", start)

    app = create_app(settings)
    with TestClient(app) as client:      # the lifespan is the thing under test
        assert started.get("called") is True
        assert cards_exec.is_running() is True
        assert client is not None
    # ...and stopping the app takes the flag back down, so the check below
    # cannot fire against a dashboard that is shutting down.
    assert cards_exec.is_running() is False


def test_the_boot_line_no_longer_claims_cards_is_not_mounted(tmp_path):
    """The log line was the operator's only evidence, and it was untrue: a
    mounted Cards with no episode open is not an unmounted one."""
    from ccsync_dashboard import cards_exec

    executor = cards_exec.PinnedExecutor(_settings(tmp_path), lambda: None)
    assert "not mounted" not in executor.why_not()
    assert "no episode is open yet" in executor.why_not()

    absent = cards_exec.PinnedExecutor(_settings(tmp_path), None)
    assert absent.why_not() == "Timeline Cards is not mounted in this dashboard"


def test_a_pinned_job_with_no_worker_running_is_a_finding(tmp_path, monkeypatch):
    """DDIAG-6 could not see the shape that shipped: its two shapes need
    "not mounted" or a claimed machine, and this one has neither."""
    from ccsync_dashboard import alerts, cards_exec, mount_status

    conn = dbmod.connect(tmp_path / "alerts.db")
    dbmod.migrate(conn)
    conn.execute(
        "INSERT INTO jobs (kind, state, created_at, updated_at) "
        "VALUES ('proxy-480p', 'pinned', ?, ?)",
        ("2026-09-18T10:00:00Z", "2026-09-18T10:00:00Z"))
    conn.commit()
    mount_status.reset()
    mount_status.record("cards", "mounted", "mounted (test)")
    cards_exec._note_running(False)
    try:
        ctx = alerts.Ctx(conn, _settings(tmp_path), "2026-09-18T11:00:00Z")
        findings = alerts._check_jobs_pinned_no_executor(ctx)
        assert findings, "a pinned job with no drain thread raised nothing"
        assert "not running" in findings[0]["detail"]

        cards_exec._note_running(True)
        assert alerts._check_jobs_pinned_no_executor(ctx) == []
    finally:
        cards_exec._note_running(False)
        mount_status.reset()
        conn.close()


# ---------------------------------------------------------------------------
# dash-cards-1: an agent whose editor is in no episode must not spin
# ---------------------------------------------------------------------------


class _Pool:
    """A cards pool with no engine for anybody, until `engine` is set."""

    def __init__(self):
        self.engine = None

    def engine_for(self, editor):
        return self.engine

    def any_engine(self):
        return self.engine


@pytest.fixture
def agent_client(tmp_path, monkeypatch):
    """A dashboard with Cards mounted and nobody in an episode, plus a fake
    clock so the 25 s hold costs the suite nothing."""
    settings = _settings(tmp_path, report_token="companion-token-not-a-real-one")
    app = create_app(settings)
    pool = _Pool()
    slept = []
    clock = {"t": 0.0}

    from ccsync_dashboard import cards_tunnel

    monkeypatch.setattr(cards_tunnel, "_monotonic", lambda: clock["t"])

    def sleep(seconds):
        slept.append(seconds)
        clock["t"] += seconds

    monkeypatch.setattr(cards_tunnel, "_sleep", sleep)

    with TestClient(app) as client:
        app.state.cards_pool = pool
        app.state.cards_engine = None
        yield client, pool, slept, clock


def _fleet_headers(editor="jsmith"):
    return {"X-CCSync-Token": "companion-token-not-a-real-one",
            "X-CCSync-Identity": auth.make_identity_token(SECRET, editor)}


def test_an_agent_in_no_episode_is_held_for_the_wait_it_asked_for(agent_client):
    """dash-cards-1: phase 1a made this path answer IMMEDIATELY, and the
    companion's pull loop has no sleep of its own on a 200 - its pacing was
    always this route's hold. So every machine with the cards role on issued
    this GET continuously, from every container restart until somebody opened
    an episode, each one a full fleet-credential check on a single-worker
    dashboard."""
    client, _pool, slept, _clock = agent_client

    r = client.get("/cards/agent/pending?wait=25", headers=_fleet_headers())

    assert r.status_code == 200
    assert "note" in r.json()
    assert sum(slept) == pytest.approx(25.0)


def test_the_hold_ends_early_when_an_episode_opens(agent_client):
    """Interruptible, not one sleep: an editor who opens an episode gets their
    agent attached within a step, not at the end of the hold."""
    client, pool, slept, _clock = agent_client

    class _Engine:
        def agent_pending(self, wait):
            return {"id": 7, "waited": wait}

        def tick(self):
            pass

    calls = {"n": 0}

    def open_the_episode(seconds):
        calls["n"] += 1
        if calls["n"] == 2:
            pool.engine = _Engine()

    from ccsync_dashboard import cards_tunnel

    # Wrap the fixture's sleep so the engine appears mid-hold.
    outer = cards_tunnel._sleep

    def sleep(seconds):
        outer(seconds)
        open_the_episode(seconds)

    cards_tunnel._sleep = sleep
    try:
        r = client.get("/cards/agent/pending?wait=25", headers=_fleet_headers())
    finally:
        cards_tunnel._sleep = outer

    assert r.status_code == 200
    assert r.json()["id"] == 7
    # It woke on the second step, not at the end of the hold...
    assert sum(slept) < 25.0
    # ...and the engine was asked for what was LEFT of the wait, not for a
    # second full one: the companion's read timeout is this plus its margin.
    assert int(r.json()["waited"]) < 25


def test_a_zero_wait_still_answers_at_once(agent_client):
    """`wait=0` is a caller asking not to be held - the shape a test or a
    one-shot probe uses."""
    client, _pool, slept, _clock = agent_client

    r = client.get("/cards/agent/pending?wait=0", headers=_fleet_headers())

    assert r.status_code == 200 and "note" in r.json()
    assert slept == []
