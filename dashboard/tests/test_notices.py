"""notices.py and its half of db.py (UX-10, resilience sweep 2026-08-28).

Pins the resilience sweep 2026-08-28 fix pass: the (kind, subject) upsert
contract, DISMISS semantics, `run_checks()` never raising and leaving a
failing check's own notices alone, the "checked" evidence mechanism that
tells `[ OK ]` from `[ NOT CHECKED ]` (finding 1), and `plan_without_share`,
which had no writer at all before this fix pass (finding 1).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth
from ccsync_dashboard import db as dbmod
from ccsync_dashboard import notices
from ccsync_dashboard import ui
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

NOW = "2026-08-28T12:00:00+00:00"
LATER = "2026-08-28T12:05:00+00:00"
EVEN_LATER = "2026-08-28T13:00:00+00:00"

SECRET = "s"


# --------------------------------------------------------- notice() / clear_notice()

def test_notice_upserts_keyed_by_kind_and_subject_not_duplicated(conn):
    first = dbmod.notice(conn, "server_error", "error", "subj-a",
                         body="first", fix="do x", now=NOW)
    second = dbmod.notice(conn, "server_error", "error", "subj-a",
                          body="second", fix="do y", now=LATER)
    assert first == second
    rows = conn.execute(
        "SELECT * FROM notices WHERE kind='server_error' AND subject='subj-a'").fetchall()
    assert len(rows) == 1
    row = rows[0]
    assert row["first_seen"] == NOW          # kept, not bumped
    assert row["last_seen"] == LATER          # bumped
    assert row["body"] == "second"
    assert row["cleared_at"] is None


def test_clear_notice_closes_the_open_row_and_is_idempotent(conn):
    dbmod.notice(conn, "server_error", "error", "subj-b", body="x", fix="y", now=NOW)
    assert dbmod.clear_notice(conn, "server_error", "subj-b", now=LATER) is True
    row = conn.execute(
        "SELECT cleared_at FROM notices WHERE kind='server_error' AND subject='subj-b'"
    ).fetchone()
    assert row["cleared_at"] == LATER
    # Nothing open left to close: reports no change rather than raising.
    assert dbmod.clear_notice(conn, "server_error", "subj-b", now=EVEN_LATER) is False


def test_clear_notices_of_kind_keeps_only_the_still_failing_subjects(conn):
    dbmod.notice(conn, "provision_failed", "error", "slug-a", now=NOW)
    dbmod.notice(conn, "provision_failed", "error", "slug-b", now=NOW)
    closed = dbmod.clear_notices_of_kind(conn, "provision_failed", ["slug-b"], now=LATER)
    assert closed == 1
    open_subjects = {r["subject"] for r in dbmod.open_notices(conn)
                     if r["kind"] == "provision_failed"}
    assert open_subjects == {"slug-b"}


# ------------------------------------------------------------------- DISMISS

def test_dismiss_hides_but_a_still_true_condition_comes_back(conn):
    """docs/SELF_DIAGNOSIS.md section 2: DISMISS hides, it does not fix. The
    next `notice()` for a condition that is STILL true reopens it, keeping the
    original `first_seen` -- a dismissal cannot silence a live condition."""
    dbmod.notice(conn, "server_error", "error", "subj-c", body="x", fix="y", now=NOW)
    row = conn.execute("SELECT id FROM notices WHERE subject='subj-c'").fetchone()
    dismissed = dbmod.dismiss_notice(conn, row["id"], "owen", now=LATER)
    assert dismissed is not None
    still = conn.execute(
        "SELECT cleared_at FROM notices WHERE subject='subj-c'").fetchone()
    assert still["cleared_at"] == LATER
    assert "subj-c" not in {r["subject"] for r in dbmod.open_notices(conn)}

    # The pass that owns this kind runs again and the condition is STILL true.
    dbmod.notice(conn, "server_error", "error", "subj-c", body="x", fix="y", now=EVEN_LATER)
    reopened = conn.execute(
        "SELECT first_seen, cleared_at FROM notices WHERE subject='subj-c'").fetchone()
    assert reopened["cleared_at"] is None
    assert reopened["first_seen"] == NOW      # the original, not the reopen time


def test_dismiss_on_an_already_gone_notice_answers_none(conn):
    assert dbmod.dismiss_notice(conn, 999999, "owen", now=NOW) is None


# ------------------------------------------------------- run_checks() safety

def test_run_checks_never_raises_and_leaves_the_failing_checks_notices_alone(conn, tmp_path):
    """"could not check" must never render as "fine": a check that raises
    must not clear the notices it would otherwise have cleared."""
    settings = Settings(db_path=str(tmp_path / "test.db"))
    dbmod.notice(conn, "projects_dir_missing", "error", "/nope", body="x", fix="y", now=NOW)
    original = notices._check_tree

    def boom(_conn, _settings, _now):
        raise RuntimeError("boom")

    notices._check_tree = boom
    try:
        ran = notices.run_checks(conn, settings, NOW)
    finally:
        notices._check_tree = original
    assert ran >= 0                            # never raised
    row = conn.execute(
        "SELECT cleared_at FROM notices WHERE kind='projects_dir_missing'").fetchone()
    assert row["cleared_at"] is None            # left alone, not cleared


def test_run_checks_never_raises_with_every_check_broken(conn, monkeypatch):
    """A more thorough version of the same rule: even if EVERY check raises
    (a database on its way out, say), the pass that is reporting on the
    fleet's health must not itself become the thing that is down."""
    settings = Settings(db_path="/nonexistent/dash.db")

    def boom(*_a, **_k):
        raise RuntimeError("boom")

    for name in ("_check_collector_jobs", "_check_collector_alarms", "_check_tree",
                "_check_identity_collisions", "_check_machine_space",
                "_check_dashboard_space", "_check_release_feed", "_check_accounts",
                # wave 2 of the usability sweep 2026-09-03 (DDIAG-3, DDIAG-7,
                # SYS-1c, DDIAG-10): every check in the tuple, or this stops
                # being the rule it says it is.
                "_check_forgotten_machines", "_check_feature_mounts",
                "_check_alerts_sink", "_check_server_crashes",
                "_check_pending_devices", "_check_plan_without_share"):
        monkeypatch.setattr(notices, name, boom)
    ran = notices.run_checks(conn, settings, NOW, pending_devices={}, folder_devices={})
    assert ran == 0


# --------------------------------------------------- "checked" evidence (finding 1)

def test_notice_check_times_only_records_kinds_a_pass_actually_touched(conn):
    assert dbmod.notice_check_times(conn) == {}
    # clear_notices_of_kind always stamps evidence, even with nothing to close.
    dbmod.clear_notices_of_kind(conn, "dashboard_disk_low", [], now=NOW)
    checked = dbmod.notice_check_times(conn)
    assert checked == {"dashboard_disk_low": NOW}
    assert "plan_without_share" not in checked


def test_notices_context_marks_ok_only_for_kinds_with_evidence(conn):
    """The exact bug this fix pass closes: a kind in the registry with no
    writer must not render as checked."""
    dbmod.clear_notices_of_kind(conn, "dashboard_disk_low", [], now=NOW)  # ran, clean
    dbmod.notice(conn, "machine_disk_low", "warn", "jsmith/PC", now=NOW)   # ran, found something
    ctx = ui._notices_context(conn)
    assert "dashboard_disk_low" in ctx["checked_kinds"]
    assert "machine_disk_low" in ctx["checked_kinds"]
    assert "machine_disk_low" in ctx["open_kinds"]
    # A kind nothing in this cycle touched is neither open nor checked, so the
    # template's [ NOT CHECKED ] branch is the one that fires for it.
    untouched = [k["kind"] for k in ctx["notice_kinds"]
                if k["kind"] not in ctx["checked_kinds"] and k["kind"] not in ctx["open_kinds"]]
    assert untouched                            # at least one kind genuinely untouched


def test_the_rendered_panel_shows_not_checked_ok_and_found(tmp_path):
    """Full-stack: renders the actual partial and reads the three chip texts
    back out of the HTML, so a future template edit that breaks the contract
    fails here rather than only in the context-builder unit test above."""
    app = create_app(Settings(
        db_path=str(tmp_path / "dash.db"), report_token="sekrit",
        session_secret=SECRET, admin_users=frozenset({"owen"}),
    ))
    with TestClient(app) as client:
        conn = dbmod.connect(tmp_path / "dash.db")
        try:
            dbmod.clear_notices_of_kind(conn, "dashboard_disk_low", [], now=NOW)
            dbmod.notice(conn, "machine_disk_low", "warn", "jsmith/PC", now=NOW,
                        body="low", fix="clear space")
            conn.commit()
            client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "owen"))
            resp = client.get("/partials/notices")
            assert resp.status_code == 200
            html = resp.text
            assert "[ FOUND ]" in html          # machine_disk_low (open)
            assert "[ OK ]" in html              # dashboard_disk_low (checked, clean)
            assert "[ NOT CHECKED ]" in html     # plan_without_share and others: no writer ran
        finally:
            conn.close()


# --------------------------------------------------------------- plan_without_share

def _seed_machine(conn, editor, machine, device_id, now=NOW):
    dbmod.upsert_machine(conn, editor, machine, now, syncthing_device_id=device_id)


def test_plan_without_share_fires_for_a_full_tick_with_no_share(conn):
    _seed_machine(conn, "jsmith", "EDIT-PC", "DEV-1")
    dbmod.add_selection(conn, "jsmith", "proj-a", "test", NOW, machine="EDIT-PC",
                        sync_mode=dbmod.SYNC_MODE_FULL)
    notices._check_plan_without_share(conn, NOW, {"proj-a": []})
    open_subjects = {r["subject"] for r in dbmod.open_notices(conn)
                     if r["kind"] == "plan_without_share"}
    assert any("proj-a" in s for s in open_subjects)

    # Sharing it clears the notice on the next pass.
    notices._check_plan_without_share(conn, LATER, {"proj-a": ["DEV-1"]})
    still_open = {r["subject"] for r in dbmod.open_notices(conn)
                 if r["kind"] == "plan_without_share"}
    assert not any("proj-a" in s for s in still_open)


def test_plan_without_share_excludes_upload_only_ticks(conn):
    """Upload-only is lane A alone and is never a Syncthing share by design
    (docs/UPLOAD_ONLY_TICK.md) -- it must never be reported as a missing
    share."""
    _seed_machine(conn, "jsmith", "EDIT-PC", "DEV-1")
    dbmod.add_selection(conn, "jsmith", "proj-b", "test", NOW, machine="EDIT-PC",
                        sync_mode=dbmod.SYNC_MODE_UPLOAD_ONLY)
    notices._check_plan_without_share(conn, NOW, {"proj-b": []})
    open_subjects = {r["subject"] for r in dbmod.open_notices(conn)
                     if r["kind"] == "plan_without_share"}
    assert not any("proj-b" in s for s in open_subjects)


def test_plan_without_share_is_silent_with_no_folder_snapshot_yet(conn):
    """`folder_devices is None` (a fresh boot, or Syncthing unreachable) is
    not evidence every plan is satisfied: nothing is written, and nothing
    already open is cleared either."""
    _seed_machine(conn, "jsmith", "EDIT-PC", "DEV-1")
    dbmod.add_selection(conn, "jsmith", "proj-a", "test", NOW, machine="EDIT-PC",
                        sync_mode=dbmod.SYNC_MODE_FULL)
    notices._check_plan_without_share(conn, NOW, None)
    assert dbmod.open_notices(conn) == []
    assert "plan_without_share" not in dbmod.notice_check_times(conn)


def test_plan_without_share_skips_the_unassigned_bucket(conn):
    """A tick with no computer to check a device id against is not a fault --
    it is what "not assigned to a machine yet" means."""
    dbmod.add_selection(conn, "jsmith", "proj-a", "test", NOW)  # ANY_MACHINE
    notices._check_plan_without_share(conn, NOW, {"proj-a": []})
    assert dbmod.open_notices(conn) == []


# -------------------------------------------------------------------- disk floor

def test_dashboard_disk_low_fires_below_the_floor_and_clears_above_it(conn, tmp_path, monkeypatch):
    settings = Settings(db_path=str(tmp_path / "dash.db"))

    class _Low:
        free = notices.DASHBOARD_DISK_FLOOR_BYTES - 1
        total = 100 * 1024 ** 3

    monkeypatch.setattr(notices.shutil, "disk_usage", lambda _path: _Low())
    notices._check_dashboard_space(conn, settings, NOW)
    assert any(r["kind"] == "dashboard_disk_low" for r in dbmod.open_notices(conn))

    class _Plenty:
        free = notices.DASHBOARD_DISK_FLOOR_BYTES + 1024 ** 3
        total = 100 * 1024 ** 3

    monkeypatch.setattr(notices.shutil, "disk_usage", lambda _path: _Plenty())
    notices._check_dashboard_space(conn, settings, LATER)
    assert not any(r["kind"] == "dashboard_disk_low" for r in dbmod.open_notices(conn))


def test_dashboard_disk_low_fires_when_the_volume_cannot_be_measured(conn, tmp_path, monkeypatch):
    settings = Settings(db_path=str(tmp_path / "dash.db"))

    def raises(_path):
        raise OSError("no such volume")

    monkeypatch.setattr(notices.shutil, "disk_usage", raises)
    notices._check_dashboard_space(conn, settings, NOW)
    assert any(r["kind"] == "dashboard_disk_low" for r in dbmod.open_notices(conn))


# --------------------------------------------- bug-hunt-2026-09-03 fix pass

def _seed_disk(conn, editor, machine, free, disk_at):
    conn.execute(
        "INSERT INTO machine_state (editor_username, machine, reported_at, "
        "received_at, disk_root_free_bytes, disk_root_total_bytes, disk_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (editor, machine, disk_at, disk_at, free, 500 * 1024 ** 3, disk_at))


def test_machine_disk_low_ignores_a_reading_older_than_the_silent_threshold(conn):
    """dash-collector-6: nothing but that machine reporting again with more
    space could clear this notice, so a retired laptop's last reading kept a
    warn open for ever, with a fix nobody could act on."""
    now = "2026-08-28T12:00:00+00:00"
    stale = "2026-08-01T12:00:00+00:00"
    _seed_disk(conn, "jsmith", "OLD-LAPTOP", 30 * 1024 ** 3, stale)
    notices._check_machine_space(conn, None, now)
    assert [r for r in dbmod.open_notices(conn)
            if r["kind"] == "machine_disk_low"] == []
    # ...and the kind is still CHECKED, so the panel does not read as a gap.
    assert "machine_disk_low" in dbmod.notice_check_times(conn)


def test_machine_disk_low_still_fires_on_a_fresh_reading(conn):
    now = "2026-08-28T12:00:00+00:00"
    fresh = "2026-08-28T11:00:00+00:00"
    _seed_disk(conn, "jsmith", "EDIT-PC", 30 * 1024 ** 3, fresh)
    notices._check_machine_space(conn, None, now)
    assert [r["subject"] for r in dbmod.open_notices(conn)
            if r["kind"] == "machine_disk_low"] == ["jsmith/EDIT-PC"]


def test_a_stale_reading_lets_an_open_disk_notice_clear(conn):
    fresh = "2026-08-28T11:00:00+00:00"
    _seed_disk(conn, "jsmith", "EDIT-PC", 30 * 1024 ** 3, fresh)
    notices._check_machine_space(conn, None, "2026-08-28T12:00:00+00:00")
    assert any(r["kind"] == "machine_disk_low" for r in dbmod.open_notices(conn))
    notices._check_machine_space(conn, None, "2026-09-28T12:00:00+00:00")
    assert not any(r["kind"] == "machine_disk_low" for r in dbmod.open_notices(conn))


def test_the_feed_kinds_are_checked_on_a_site_with_no_feed(conn):
    """dash-collector-7: the early return stamped no evidence at all, so both
    kinds sat at [ NOT CHECKED ] for ever on the vendor default - which the
    panel's contract reads as "no writer runs anywhere in this build"."""
    class _NoFeed:
        release_feed_url = ""

    notices._check_release_feed(conn, _NoFeed(), NOW)
    checked = dbmod.notice_check_times(conn)
    assert "feed_unreachable" in checked
    assert "feed_runtime_mismatch" in checked
    assert dbmod.open_notices(conn) == []
