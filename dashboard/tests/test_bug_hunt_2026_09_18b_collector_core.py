"""The 2026-09-18b mediums wave, collector/notices/app group (CR-298).

One test per finding, named for the behaviour it pins; the finding id is in
the docstring and at the code site.
"""
from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import (alerts, app as appmod, collector as collector_mod,
                              db as dbmod, mount_status, notices)
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "test-secret-not-a-real-one-at-all"
NOW = "2026-09-18T12:00:00+00:00"


def _settings(tmp_path, **over):
    kwargs = dict(db_path=str(tmp_path / "hunt.db"), session_secret=SECRET,
                  admin_users=frozenset({"owen"}))
    kwargs.update(over)
    return Settings(**kwargs)


@pytest.fixture
def conn(tmp_path):
    c = dbmod.connect(tmp_path / "hunt.db")
    dbmod.migrate(c)
    yield c
    c.close()


# ---------------------------------------------------------------------------
# dash-collector-alerts-2: the archive check asks the question that can answer
# ---------------------------------------------------------------------------


def test_a_mount_point_left_behind_by_an_unmount_is_not_a_readable_archive(
        conn, tmp_path):
    """dash-collector-alerts-2: both copies of the check scandir'd the
    recorded ROOT and called success healthy. A bind mount that goes away
    leaves its mount point behind, so that is the one probe an unmounted
    dataset passes - the outage the check exists for. The WITNESS (b-roll's
    proxies directory) and an empty root are what tell them apart."""
    root = tmp_path / "broll-data"
    root.mkdir()
    mount_status.reset()
    mount_status.record_root("broll", str(root), witness=str(root / "proxies"))

    notices._check_broll_archive(conn, _settings(tmp_path), NOW)
    card = {r["kind"]: r for r in dbmod.open_notices(conn)}[notices.BROLL_ARCHIVE_KIND]
    assert card["severity"] == "error"
    # ...and the mail half, which is the whole reason the alert row exists.
    findings = alerts._check_broll_archive(_AlertCtx())
    assert findings and str(root) in findings[0]["subject"]

    # The dataset comes back: the witness is there and the root has content.
    (root / "proxies").mkdir()
    (root / "Creators_Club").mkdir()
    notices._check_broll_archive(conn, _settings(tmp_path), NOW)
    assert notices.BROLL_ARCHIVE_KIND not in {r["kind"] for r in dbmod.open_notices(conn)}
    assert alerts._check_broll_archive(_AlertCtx()) == []
    mount_status.reset()


class _AlertCtx:
    """Enough of `alerts.Ctx` for a check that reads neither. The archive
    probe is deliberately a filesystem question, not a database one."""

    now = NOW
    conn = None
    settings = None


# ---------------------------------------------------------------------------
# dash-collector-alerts-3: a first inventory is not evidence of an arrival
# ---------------------------------------------------------------------------


def _walk(slug, old, new):
    return collector_mod.InventoryWalk(slug=slug, project_rel=slug, old=old, new=new)


def _half(kind, slug, rel, seen_at=""):
    return collector_mod._Half(kind, rel.rsplit("/", 1)[-1], 4096, 1_700_000,
                               slug, f"2026/{slug}", rel, rel, seen_at)


def test_a_file_cannot_arrive_before_it_leaves():
    """dash-collector-alerts-3: `InventoryWalk.old` is empty for a project
    this collector has never walked, so every file of a newly activated
    episode is an "appeared" half and stays live pairing evidence for two
    days. Paired with a LATER deletion somewhere else in the fleet that reads
    as a hand move: a file_moves row in state DONE that every holding machine
    applies to its own disk, with no admin in the path. The halves are kept
    (a folder moved INTO a brand-new project is the common case and is a
    first walk); what is refused is the impossible ORDER."""
    yesterday = "2026-09-17T12:00:00+00:00"
    # The arrival was recorded first; the vanish is this pass. Not a move.
    moves, plan = collector_mod.pair_across_cycles(
        [_half(dbmod.HALF_APPEARED, "new-episode", "Footage/a.mov", yesterday)],
        [_half(dbmod.HALF_VANISHED, "old-episode", "B-roll/a.mov")])
    assert moves == []
    # Neither half is consumed: the vanish may still pair with a real arrival.
    assert plan.delete == []
    assert [h.slug for h in plan.persist] == ["old-episode"]

    # The honest order still pairs, including into a project walked for the
    # first time in this pass.
    moves, _plan = collector_mod.pair_across_cycles(
        [_half(dbmod.HALF_VANISHED, "old-episode", "B-roll/a.mov", yesterday)],
        [_half(dbmod.HALF_APPEARED, "new-episode", "Footage/a.mov")])
    assert [(m.from_slug, m.to_slug) for m in moves] == [("old-episode", "new-episode")]


def test_a_first_walks_arrivals_are_still_kept_as_halves():
    """dash-collector-alerts-3, the other side: dropping a first walk's
    arrivals outright would stop a folder moved INTO a brand-new project from
    ever pairing, which is the shape the feature exists for."""
    files = [(f"Footage/clip{i}.mov", "video", 1000 + i, 5_000 + i) for i in range(4)]
    halves = collector_mod.unpaired_halves([_walk("new-project", [], files)])
    assert [h.half for h in halves] == [dbmod.HALF_APPEARED] * 4


# ---------------------------------------------------------------------------
# res-fleet-2: one pass cannot fill the window it is read out of
# ---------------------------------------------------------------------------


def test_one_pass_cannot_fill_the_carried_halves_window(tmp_path, monkeypatch):
    """res-fleet-2: the write had no bound and the read has one (oldest 4000
    inside two days), so a 6,000-clip upload crowded every later half out of
    the read and cross-cycle detection turned itself off silently."""
    calls: list[int] = []
    monkeypatch.setattr(collector_mod.db, "record_pending_move_halves",
                        lambda conn, rows, now: calls.append(len(rows)))
    monkeypatch.setattr(collector_mod.db, "delete_pending_move_halves",
                        lambda conn, keys: None)
    monkeypatch.setattr(collector_mod, "PENDING_MOVE_HALF_WRITE_LIMIT", 3)

    def halves(n):
        return [collector_mod._Half(dbmod.HALF_APPEARED, f"c{i}.mov", 10 + i, 20 + i,
                                    "slug", "2026/Ep", f"Footage/c{i}.mov",
                                    f"Footage/c{i}.mov") for i in range(n)]

    plan = collector_mod._HalfPlan(persist=halves(3), delete=[], by_move={})
    collector_mod._settle_halves(None, plan, (), NOW)
    assert calls == [3]

    calls.clear()
    plan = collector_mod._HalfPlan(persist=halves(4), delete=[], by_move={})
    collector_mod._settle_halves(None, plan, (), NOW)
    assert calls == []


# ---------------------------------------------------------------------------
# dash-core-1 / dash-core-2: one record per failed request, under its own name
# ---------------------------------------------------------------------------


def _busy_handler(app):
    for key, fn in getattr(app, "exception_handlers", {}).items():
        if key is Exception:
            return fn
    raise AssertionError("the parent app has no catch-all exception handler")


def _mounted_failure(tmp_path, exc, prefix="/broll"):
    from fastapi import FastAPI

    from ccsync_dashboard import auth

    dbmod.migrate(dbmod.connect(tmp_path / "hunt.db"))
    app = create_app(_settings(tmp_path))
    sub = FastAPI()

    @sub.get("/api/ingest")
    def ingest():
        raise exc

    app.mount(prefix, sub)
    # This checkout may already mount the real /broll or /music app at the
    # same prefix, and Starlette matches in order: ours goes first, so the
    # request reaches the route that raises.
    app.routes.insert(0, app.routes.pop())
    appmod._install_busy_handler_on_mounts(app, _busy_handler(app))
    client = TestClient(app, raise_server_exceptions=False)
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "owen"))
    return client.get(f"{prefix}/api/ingest")


def _notice_rows(tmp_path, kind):
    c = dbmod.connect(tmp_path / "hunt.db")
    try:
        return [dict(r) for r in c.execute(
            "SELECT subject, body FROM notices WHERE kind=?", (kind,))]
    finally:
        c.close()


def test_a_failure_under_a_mount_is_recorded_once_and_under_its_own_path(tmp_path):
    """dash-core-1: wire-2 put the parent's handler on every mounted sub-app,
    and Starlette re-raises after the sub-app answers - so one failure logged
    twice and performed TWO connect-write-close cycles against the database
    whose contention the notice exists to report.

    dash-core-2: the route template the handler sees inside a mount is the
    sub-app's INNER one, which names no path on this dashboard and is shared
    verbatim by /broll and /music."""
    assert _mounted_failure(tmp_path, RuntimeError("a genuine defect")).status_code == 500
    rows = _notice_rows(tmp_path, "server_error")
    assert len(rows) == 1
    assert rows[0]["subject"] == "/broll/api/ingest (RuntimeError)"
    assert rows[0]["body"].split()[0] == "1"


def test_two_mounts_with_the_same_inner_route_are_two_notices(tmp_path):
    """dash-core-2: /broll and /music expose twelve identical inner templates,
    so one row and one count served two features."""
    _mounted_failure(tmp_path, RuntimeError("x"), prefix="/broll")
    _mounted_failure(tmp_path, RuntimeError("x"), prefix="/music")
    subjects = {r["subject"] for r in _notice_rows(tmp_path, "server_error")}
    assert subjects == {"/broll/api/ingest (RuntimeError)",
                        "/music/api/ingest (RuntimeError)"}


def test_a_busy_database_under_a_mount_is_counted_once(tmp_path):
    """dash-core-1, the branch that matters most: the busy notice is the one
    whose precondition is that the write lock is already held."""
    resp = _mounted_failure(tmp_path, sqlite3.OperationalError("database is locked"))
    assert resp.status_code == 503
    rows = _notice_rows(tmp_path, notices.DB_BUSY_KIND)
    assert len(rows) == 1 and rows[0]["body"].split()[0] == "1"
    assert rows[0]["subject"].startswith("/broll/api/ingest")
