"""bug-hunt 2026-09-11b, territory dash-db (CR-258).

Six findings, five of them the same shape: a fix from earlier the same day
that landed on one side of a seam. The dashboard never read the `state` the
companion started answering (comp-app-1); the collector's liveness flag was
moved out of its Syncthing gate and kept a Syncthing-shaped threshold
(dash-collector-alerts-1); the rollback push learned its direction on one of
four doors (dash-db-1); "a cancelled job does not come back" was taught to
two of the three routes back to `queued` (dash-db-2); and the includes cap
bounded the rows it produced but not the work it did first (dash-db-3).
"""
from __future__ import annotations

import sqlite3
import time

import pytest

from ccsync_dashboard import db as dbmod
from ccsync_dashboard import assignments as assignments_mod
from ccsync_dashboard import links

NOW = "2026-09-11T10:00:00+00:00"


def _iso_ago(seconds: float, now: str = NOW) -> str:
    return (dbmod.parse_iso(now) - dbmod.dt.timedelta(seconds=seconds)).isoformat()


# --------------------------------------------------------------- comp-app-1

def _delivered_move(conn, *, delivered_ago_days: float = 8.0) -> int:
    dbmod.record_known_editor(conn, "ed", source="admin", now=NOW)
    dbmod.upsert_machine(conn, "ed", "LAP", NOW)
    move_id = dbmod.record_file_move(
        conn, from_slug="ff5", from_project_rel="2026/FF5", from_rel="A/clip.mp4",
        to_slug="ff5", to_project_rel="2026/FF5", to_rel="B/clip.mp4",
        is_dir=False, proxies_moved=0, requested_by="admin", now=NOW,
        targets=[("ed", "LAP")], state=dbmod.FILE_MOVE_DONE)
    dbmod.mark_file_moves_delivered(
        conn, [move_id], "ed", "LAP", _iso_ago(delivered_ago_days * 86400))
    conn.commit()
    return move_id


def test_a_machine_still_answering_retrying_is_not_expired(conn):
    """comp-sync-20 taught the companion to answer `retrying` while the sync
    drive is out, on the stated ground that the dashboard expires a move
    "told and never answered" - and the expiry never read `state`, so an
    editor on a fortnight's shoot had the command retired on day 7 while
    their machine answered it every thirty seconds. Lane A then re-uploads
    the file at the old path and the move is undone on the server."""
    move_id = _delivered_move(conn)
    dbmod.mark_file_move_applied(
        conn, move_id, "ed", "LAP", False, "waiting for the sync drive (P: drive)",
        NOW, state=dbmod.FILE_MOVE_TARGET_RETRYING, attempts=200)
    dbmod.upsert_machine_state(conn, "ed", "LAP", None, _iso_ago(30))
    conn.commit()

    assert dbmod.expire_delivered_file_moves(conn, NOW) == []
    pending = dbmod.pending_file_moves(conn, "ed", "LAP", NOW)
    assert [p["id"] for p in pending] == [move_id]


def test_a_machine_that_went_silent_while_retrying_still_expires(conn):
    """The other direction, and why this is not simply "never expire a
    retrying row": the clock has to measure SILENCE. A machine that answered
    once and then vanished for a fortnight is exactly what the expiry is
    for."""
    move_id = _delivered_move(conn)
    dbmod.mark_file_move_applied(
        conn, move_id, "ed", "LAP", False, "waiting for the sync drive",
        NOW, state=dbmod.FILE_MOVE_TARGET_RETRYING, attempts=3)
    dbmod.upsert_machine_state(conn, "ed", "LAP", None, _iso_ago(14 * 86400))
    conn.commit()

    expired = dbmod.expire_delivered_file_moves(conn, NOW)
    assert [(r["move_id"], r["machine"]) for r in expired] == [(move_id, "LAP")]


def test_a_machine_that_never_answered_at_all_still_expires(conn):
    """The original UX-5 case is untouched: delivered, no answer of any kind,
    older than the bound."""
    move_id = _delivered_move(conn)
    dbmod.upsert_machine_state(conn, "ed", "LAP", None, _iso_ago(30))
    conn.commit()
    assert [r["move_id"] for r in dbmod.expire_delivered_file_moves(conn, NOW)] == [move_id]


# ------------------------------------------------- dash-collector-alerts-1

def _poll_cycle(conn, kind: str, started: str, ok: bool = True) -> None:
    dbmod.record_poll_run(conn, kind, started, started, ok, None)


def test_a_syncthing_less_collector_turning_normally_is_not_stale(conn):
    """dash-collector-alerts-3 moved `collector_stale` out of the `reachable`
    branch (right) and left it measured against a flat 180 s (wrong). With no
    `syncthing_url` the collector runs only prune/invariants/alerts, the
    fastest of which is ten minutes, so the newest start is ALWAYS older than
    180 s: a healthy vendor or zero-touch dashboard raised a permanent error
    finding about its own collector, red-chipped the topbar and mailed it
    daily."""
    for kind, interval in (("alerts", 600.0), ("invariants", 900.0), ("prune", 3600.0)):
        _poll_cycle(conn, kind, _iso_ago(interval * 2 + 60))
        _poll_cycle(conn, kind, _iso_ago(interval + 60))
    conn.commit()
    status = dbmod.fetch_collector_status(conn, now=NOW)
    assert status["collector_stale"] is False


def test_a_collector_that_has_actually_stopped_is_still_stale(conn):
    """The bound widens to the deployment's own cadence; it does not go
    away. The same Syncthing-less deployment with nothing started for three
    hours reads as stopped, which is the one question the flag exists to
    answer."""
    for kind, interval in (("alerts", 600.0), ("invariants", 900.0), ("prune", 3600.0)):
        _poll_cycle(conn, kind, _iso_ago(3 * 3600 + interval))
        _poll_cycle(conn, kind, _iso_ago(3 * 3600))
    conn.commit()
    assert dbmod.fetch_collector_status(conn, now=NOW)["collector_stale"] is True


def test_a_fast_deployment_keeps_the_three_minute_floor(conn):
    """A Syncthing-backed deployment cycles in tens of seconds, so its bound
    stays the constant: the cadence is a floor to raise, never one to lower."""
    _poll_cycle(conn, "connections", _iso_ago(80))
    _poll_cycle(conn, "connections", _iso_ago(50))
    conn.commit()
    assert dbmod.collector_stale_bound(conn) == pytest.approx(
        dbmod.COLLECTOR_STALE_SECONDS)


# ----------------------------------------------------------------- dash-db-1

def test_a_per_machine_push_records_the_version_the_machine_is_on(conn):
    """dash-api-3 recorded `update_requested_from` so a push DOWN is not
    retired before it is delivered, and only the fleet route passed it. The
    three per-machine doors ([ UPDATE NOW ], its "update to current" twin and
    the admin API) wrote NULL, so a rollback aimed at one machine was cleared
    on that machine's next report with `commands.upgrade` never emitted."""
    dbmod.record_known_editor(conn, "ed", source="admin", now=NOW)
    dbmod.upsert_machine(conn, "ed", "LAP", NOW)
    dbmod.upsert_machine_state(conn, "ed", "LAP", None, NOW, companion_version="0.9.71")
    conn.commit()

    assert dbmod.request_machine_update(conn, "ed", "LAP", "0.9.70", "admin", NOW)
    row = dbmod.machine_update_request(conn, "ed", "LAP")
    assert row["from_version"] == "0.9.71"

    from ccsync_dashboard import api as api_mod
    assert api_mod._update_push_done(row, "0.9.71") is False


def test_an_explicit_from_version_still_wins(conn):
    """The fleet route knows the version it is rolling back FROM even when a
    machine's last report is older than the decision."""
    dbmod.record_known_editor(conn, "ed", source="admin", now=NOW)
    dbmod.upsert_machine(conn, "ed", "LAP", NOW)
    dbmod.upsert_machine_state(conn, "ed", "LAP", None, NOW, companion_version="0.9.71")
    conn.commit()
    dbmod.request_machine_update(conn, "ed", "LAP", "0.9.70", "admin", NOW,
                                 from_version="0.9.69")
    assert dbmod.machine_update_request(conn, "ed", "LAP")["from_version"] == "0.9.69"


def test_a_machine_that_has_never_reported_a_version_keeps_the_old_shape(conn):
    """Nothing to look up is the pre-v52 behaviour, not a guess."""
    dbmod.record_known_editor(conn, "ed", source="admin", now=NOW)
    dbmod.upsert_machine(conn, "ed", "LAP", NOW)
    conn.commit()
    dbmod.request_machine_update(conn, "ed", "LAP", "0.9.72", "admin", NOW)
    assert dbmod.machine_update_request(conn, "ed", "LAP")["from_version"] == ""


# ----------------------------------------------------------------- dash-db-2

def _held_job(conn) -> int:
    job_id = dbmod.create_job(conn, "proxy-480p", {"root": "vault", "rel": "a.mp4"},
                              created_by="admin", now=NOW)
    assert dbmod.claim_job(conn, job_id, "ed", "LAP", now=NOW)
    conn.commit()
    return job_id


def test_a_cancelled_job_an_old_companion_fails_retryably_goes_terminal(conn):
    """`expire_leases` learned "a cancelled job does not come back" and
    `queued_jobs`/`claim_job` were belted with it, but `fail_job` is the
    third route from held back to `queued`. A companion on 0.9.65..0.9.70
    predates `commands.jobs.cancel`: it never says "cancelled, not
    retryable", it reports whatever its ffmpeg did. The row parked in
    `queued` carrying `cancel_requested_at` - invisible to the scheduler,
    refused by every claim, never terminal."""
    job_id = _held_job(conn)
    assert dbmod.request_job_cancel(conn, job_id, "admin", now=NOW) == "requested"
    state = dbmod.fail_job(conn, job_id, "ed", "LAP", "ffmpeg exited 1",
                           now=NOW, retryable=True)
    conn.commit()

    assert state == dbmod.JOB_FAILED
    assert dbmod.get_job(conn, job_id)["state"] == dbmod.JOB_FAILED
    assert dbmod.queued_jobs(conn) == []
    assert dbmod.claim_next_job(conn, "ed", "LAP") is None


def test_the_queue_depth_counts_what_the_scheduler_would_hand_out(conn):
    """The depth rides the report reply and a companion BACKS OFF on it, so
    a row no machine can ever be given must not appear in it: a fleet with
    nothing to do otherwise looks like a fleet with a permanent backlog, with
    `oldest_age_s` growing without bound."""
    job_id = dbmod.create_job(conn, "whisper", {"root": "vault", "rel": "a.mov"},
                              created_by="admin", now=NOW)
    conn.execute("UPDATE jobs SET cancel_requested_at=?, state=? WHERE id=?",
                 (NOW, dbmod.JOB_QUEUED, job_id))
    conn.commit()
    depth = dbmod.queue_depth(conn, now=NOW)
    assert depth["queued"] == 0
    assert depth["oldest_age_s"] is None


def test_an_ordinary_retryable_failure_still_comes_back(conn):
    """The rule is about the cancel flag, not about failures: a job nobody
    asked to stop still returns to the queue and still cools its machine
    down."""
    job_id = _held_job(conn)
    state = dbmod.fail_job(conn, job_id, "ed", "LAP", "ffmpeg exited 1",
                           now=NOW, retryable=True)
    conn.commit()
    assert state == dbmod.JOB_QUEUED
    assert [j["id"] for j in dbmod.queued_jobs(conn)] == [job_id]
    assert dbmod.queue_depth(conn, now=NOW)["queued"] == 1


# ----------------------------------------------------------------- dash-db-3

def test_a_tampered_marker_cannot_buy_unbounded_work(tmp_path):
    """The 2026-09-11 fix capped the ROWS: the results loop breaks at
    MAX_INCLUDES. Both dedupe passes still ran over every declared entry
    first, each O(n^2), so a 20,000-entry marker (about 700 KB on a share
    every editor can write) cost 23 s of CPU per provision cycle inside the
    collector's guarded loop. Measured on this machine: 0.05 s at 1,000
    entries, 22.9 s at 20,000.
    """
    raw = [f"Projects/2026/Lender/Folder{i:05d}" for i in range(20000)]
    started = time.monotonic()
    results = links.resolve_marker_includes(tmp_path / "projects", "2026/Borrower", raw)
    elapsed = time.monotonic() - started

    assert len(results) <= links.MAX_INCLUDES + 1   # + the one refusal row
    assert elapsed < 5.0, f"the dedupe passes are still quadratic ({elapsed:.1f}s)"


def test_the_refusal_still_names_how_many_the_marker_declared(tmp_path):
    """The entry cap must not shrink the number an admin is shown: that
    number is how big the file on the share is, and the tampering is the
    thing worth seeing."""
    raw = [f"Projects/2026/Lender/Folder{i:05d}" for i in range(5000)]
    results = links.resolve_marker_includes(tmp_path / "projects", "2026/Borrower", raw)
    last = results[-1]
    assert last.status == links.STATUS_INVALID
    assert f"{5000 - links.MAX_INCLUDES} ignored" in last.detail


def test_nesting_and_duplicates_collapse_exactly_as_before(tmp_path):
    """The single-scan nesting pass has to answer what the nested `next(...)`
    answered, including the ordering trap: `a!` sorts between `a` and `a/b`,
    so a bare sort key would let `a/b` escape its ancestor."""
    raw = [
        "Projects/2026/L/A",
        "Projects/2026/L/A",              # exact duplicate
        "Projects/2026/L/A/Inner/Deep",   # inside A, two levels down
        "Projects/2026/L/A!",             # sorts between the two above
        "Projects/2026/L/B",
    ]
    results = links.resolve_marker_includes(tmp_path / "projects", "2026/Borrower", raw)
    assert [r.declared for r in results] == [
        "Projects/2026/L/A", "Projects/2026/L/A!", "Projects/2026/L/B"]


# ----------------------------------------------------------------- dash-db-5

class _LockOnArchived:
    """A connection that raises a REAL `database is locked` for the archived
    projects read alone, the way a busy timeout expires against one statement
    while the rest of a page's reads get through."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def execute(self, sql, *args, **kwargs):
        if "p.archived_at IS NOT NULL" in sql:
            raise sqlite3.OperationalError("database is locked")
        return self._conn.execute(sql, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._conn, name)


def test_the_assignments_grid_renders_when_the_archive_read_is_locked(conn):
    """dash-db-2 made the five archive/suspension readers raise on a lock
    instead of answering empty, which is right where the empty answer was a
    fail-OPEN. This page only renders, and a 500 here takes away the
    [ UNARCHIVE ] button the admin came for."""
    dbmod.upsert_project(conn, "ff5", "2026/FF5", "/ff5", NOW)
    conn.commit()
    view = assignments_mod._assignments_view(_LockOnArchived(conn))
    assert view["archived_projects"] == []
    assert view["archived_unreadable"] is True


def test_the_grid_still_lists_archived_projects_when_the_read_works(conn):
    dbmod.upsert_project(conn, "ff5", "2026/FF5", "/ff5", NOW)
    dbmod.archive_project(conn, "ff5", by="admin", now=NOW)
    conn.commit()
    view = assignments_mod._assignments_view(conn)
    assert [p["slug"] for p in view["archived_projects"]] == ["ff5"]
    assert view["archived_unreadable"] is False
