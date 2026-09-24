"""CR-320 (2026-09-24): a resolved problem goes away without [ DISMISS ].

The owner: "for errors in future if they are resolved they should go away
without needing dismiss to be clicked". The state-shaped notice kinds always
cleared themselves; these pin the EVENT-shaped ones `notices.RESOLVE_RULES`
now closes, the audit record every auto-clear leaves ("auto: <reason>"), the
cases that must stay open (still true, not yet quiet long enough, no
evidence), and the one alert kind that needed its own recovery rule
(`weekly_send_failed`).
"""

from __future__ import annotations

import datetime as dt
import json
import os
import types

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import alerts
from ccsync_dashboard import db as dbmod
from ccsync_dashboard import notices
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

T0 = "2026-09-24T08:00:00+00:00"


def _at(hours: float) -> str:
    return (dt.datetime.fromisoformat(T0) + dt.timedelta(hours=hours)).isoformat()


def _open(conn, kind, subject=None):
    rows = [r for r in dbmod.open_notices(conn, limit=500) if r["kind"] == kind]
    if subject is not None:
        rows = [r for r in rows if r["subject"] == subject]
    return rows


def _auto_audit(conn, kind):
    rows = conn.execute(
        "SELECT actor, action, subject, detail_json FROM fleet_audit "
        "WHERE action=? AND subject=? ORDER BY id", (dbmod.NOTICE_AUTO_CLEAR_ACTION, kind),
    ).fetchall()
    return [dict(r, detail=json.loads(r["detail_json"])) for r in rows]


# ------------------------------------------------------------ the registry

def test_every_rule_names_a_registered_kind_and_a_way_to_resolve():
    for kind, rule in notices.RESOLVE_RULES.items():
        assert kind in dbmod.NOTICE_KINDS, kind
        assert rule.get("evidence") or rule.get("quiet_hours"), kind


def test_the_lost_moves_card_is_deliberately_not_auto_resolved():
    """Nothing this server can observe says the operator finished the moves
    it lost the record of: could-not-check is not resolved."""
    assert "file_moves_dropped" not in notices.RESOLVE_RULES


# ------------------------------------------------- auto_clear_notice itself

def test_auto_clear_records_cleared_at_and_why_in_the_audit_ledger(conn):
    dbmod.notice(conn, "server_error", "error", "/api/v1/x (TypeError)",
                 body="1 time(s)", now=T0)
    assert dbmod.auto_clear_notice(conn, "server_error", "/api/v1/x (TypeError)",
                                   "because", now=_at(1)) is True
    row = conn.execute("SELECT cleared_at FROM notices WHERE kind='server_error'").fetchone()
    assert row["cleared_at"] == _at(1)
    audit = _auto_audit(conn, "server_error")
    assert len(audit) == 1
    assert audit[0]["actor"] == "auto"
    assert audit[0]["detail"]["cleared_by"] == "auto: because"
    assert audit[0]["detail"]["subject"] == "/api/v1/x (TypeError)"
    # Nothing open left: no second audit row.
    assert dbmod.auto_clear_notice(conn, "server_error", "/api/v1/x (TypeError)",
                                   "because", now=_at(2)) is False
    assert len(_auto_audit(conn, "server_error")) == 1


def test_auto_clear_does_not_stamp_check_evidence(conn):
    """The resolution sweep is not the pass that looks for the condition."""
    conn.execute(
        "INSERT INTO notices (kind, severity, subject, first_seen, last_seen) "
        "VALUES ('server_error', 'error', 's', ?, ?)", (T0, T0))
    dbmod.auto_clear_notice(conn, "server_error", "s", "why", now=_at(30))
    assert "server_error" not in dbmod.notice_check_times(conn)


def test_a_recurrence_reopens_an_auto_cleared_card(conn):
    dbmod.notice(conn, "server_error", "error", "s", now=T0)
    dbmod.auto_clear_notice(conn, "server_error", "s", "why", now=_at(25))
    assert not _open(conn, "server_error")
    dbmod.notice(conn, "server_error", "error", "s", now=_at(26))
    assert _open(conn, "server_error", "s")


# ------------------------------------------------------ the quiet periods

@pytest.mark.parametrize("kind,hours", [
    ("server_error", notices.SERVER_ERROR_QUIET_HOURS),
    ("db_busy", notices.DB_BUSY_QUIET_HOURS),
    ("slow_write", notices.SLOW_WRITE_QUIET_HOURS),
    ("collector_watchdog_restart", notices.WATCHDOG_RESTART_QUIET_HOURS),
])
def test_quiet_period_clears_after_the_period_and_not_before(conn, kind, hours):
    dbmod.notice(conn, kind, "warn", "the subject", body="1 time(s)", now=T0)
    assert notices._check_resolved(conn, None, _at(hours - 0.5)) == 0
    assert _open(conn, kind, "the subject")
    assert notices._check_resolved(conn, None, _at(hours)) == 1
    assert not _open(conn, kind, "the subject")
    audit = _auto_audit(conn, kind)
    assert audit and audit[-1]["detail"]["cleared_by"].startswith(
        f"auto: not seen again for {hours} h")


def test_a_recurring_server_error_is_never_quiet(conn):
    """Every recurrence re-stamps last_seen, so a route that keeps failing
    never ages out, however old its first occurrence."""
    subject = "/api/v1/y (KeyError)"
    for h in range(0, 72, 6):
        dbmod.notice(conn, "server_error", "error", subject, now=_at(h))
        notices._check_resolved(conn, None, _at(h + 1))
        assert _open(conn, "server_error", subject), h


def test_record_server_error_after_an_auto_clear_counts_on(conn):
    """The count survives the auto-clear, so a route that fails again reads
    as '2 time(s)', not as a new fault."""
    notices.record_server_error(conn, "/api/v1/z", TypeError("boom"), now=T0,
                                route="/api/v1/z")
    notices._check_resolved(conn, None, _at(25))
    assert not _open(conn, "server_error")
    notices.record_server_error(conn, "/api/v1/z", TypeError("boom"), now=_at(26),
                                route="/api/v1/z")
    rows = _open(conn, "server_error")
    assert rows and rows[0]["body"].startswith("2 time(s)")


def test_a_kind_with_no_rule_is_never_touched(conn):
    """State-shaped kinds are their own pass's business, and the dropped-moves
    card has no honest resolution signal."""
    dbmod.notice(conn, "provision_failed", "error", "slug-a", now=T0)
    dbmod.notice(conn, "file_moves_dropped", "error", "the last inventory pass", now=T0)
    notices._check_resolved(conn, None, _at(24 * 60))
    assert _open(conn, "provision_failed", "slug-a")
    assert _open(conn, "file_moves_dropped")


def test_the_sweep_runs_inside_run_checks(conn, tmp_path):
    dbmod.notice(conn, "db_busy", "warn", "/api/v1/report (database busy)", now=T0)
    settings = types.SimpleNamespace(db_path=str(tmp_path / "dash.db"), projects_dir="",
                                     release_feed_url="")
    notices.run_checks(conn, settings, now=_at(48))
    assert not _open(conn, "db_busy")


# ---------------------------------------------- triage_reply_refused

def _reply(conn, mid, sender, verdict, detail, when):
    conn.execute(
        "INSERT INTO triage_replies (message_id, received_at, from_addr, run_id, "
        "verdict, detail) VALUES (?, ?, ?, NULL, ?, ?)",
        (mid, when, sender, verdict, detail))


def test_triage_refusal_clears_when_the_same_sender_is_later_acted_on(conn):
    """The live case: the owner's first reply failed the authentication
    check, the next one from the same address was accepted and acted on."""
    _reply(conn, "<a@x>", "Alex@thecreatorsclub.co", "refused",
           "authentication: no Authentication-Results", T0)
    dbmod.notice(conn, "triage_reply_refused", "warn", "authentication", now=T0)
    assert notices._check_resolved(conn, None, _at(0.1)) == 0
    assert _open(conn, "triage_reply_refused", "authentication")
    _reply(conn, "<b@x>", "alex@thecreatorsclub.co", "acted", "1=done", _at(0.5))
    assert notices._check_resolved(conn, None, _at(0.6)) == 1
    assert not _open(conn, "triage_reply_refused")
    why = _auto_audit(conn, "triage_reply_refused")[-1]["detail"]["cleared_by"]
    assert "alex@thecreatorsclub.co" in why and "acted on" in why


def test_triage_refusal_stays_when_only_a_different_sender_succeeds(conn):
    _reply(conn, "<a@x>", "stranger@example.test", "refused",
           "sender: it came from an address this server does not send to", T0)
    dbmod.notice(conn, "triage_reply_refused", "warn", "sender", now=T0)
    _reply(conn, "<b@x>", "alex@thecreatorsclub.co", "acted", "1=done", _at(1))
    notices._check_resolved(conn, None, _at(2))
    assert _open(conn, "triage_reply_refused", "sender")


def test_triage_refusal_stays_when_the_acted_reply_came_before_the_refusal(conn):
    _reply(conn, "<b@x>", "alex@thecreatorsclub.co", "acted", "1=done", T0)
    _reply(conn, "<a@x>", "alex@thecreatorsclub.co", "refused",
           "reference: the reference has expired", _at(1))
    dbmod.notice(conn, "triage_reply_refused", "warn", "reference", now=_at(1))
    notices._check_resolved(conn, None, _at(2))
    assert _open(conn, "triage_reply_refused", "reference")


def test_triage_refusal_with_no_success_ages_out_after_a_week(conn):
    _reply(conn, "<a@x>", "stranger@example.test", "refused", "sender: no", T0)
    dbmod.notice(conn, "triage_reply_refused", "warn", "sender", now=T0)
    notices._check_resolved(conn, None, _at(notices.TRIAGE_REFUSED_QUIET_HOURS - 1))
    assert _open(conn, "triage_reply_refused", "sender")
    notices._check_resolved(conn, None, _at(notices.TRIAGE_REFUSED_QUIET_HOURS))
    assert not _open(conn, "triage_reply_refused", "sender")


# --------------------------------------------------- file_move_detected

def _detected_move(conn, targets):
    cur = conn.execute(
        "INSERT INTO file_moves (from_slug, from_project_rel, from_rel, to_slug, "
        "to_project_rel, to_rel, requested_by, requested_at, source) "
        "VALUES ('p', 'Projects/P', 'a/clip.mov', 'p', 'Projects/P', 'b/clip.mov', "
        "'detected', ?, ?)", (T0, dbmod.FILE_MOVE_SOURCE_DETECTED))
    move_id = cur.lastrowid
    for machine, applied, ok in targets:
        conn.execute(
            "INSERT INTO file_move_targets (move_id, editor_username, machine, "
            "applied_at, ok) VALUES (?, 'ed', ?, ?, ?)", (move_id, machine, applied, ok))
    dbmod.notice(conn, "file_move_detected", "info", "Projects/P/b/clip.mov", now=T0)


def test_file_move_card_clears_once_every_computer_followed_and_it_was_shown(conn):
    _detected_move(conn, [("PC1", _at(0.2), 1), ("PC2", _at(0.3), 1)])
    # Every computer followed within minutes, but an FYI nobody has had a
    # chance to read stays for its minimum time.
    notices._check_resolved(conn, None, _at(1))
    assert _open(conn, "file_move_detected")
    notices._check_resolved(conn, None, _at(notices.FILE_MOVE_DETECTED_MIN_HOURS))
    assert not _open(conn, "file_move_detected")
    why = _auto_audit(conn, "file_move_detected")[-1]["detail"]["cleared_by"]
    assert why == "auto: all 2 computer(s) moved their copy"


def test_file_move_card_stays_while_a_computer_has_not_followed(conn):
    _detected_move(conn, [("PC1", _at(0.2), 1), ("PC2", None, None)])
    notices._check_resolved(conn, None, _at(48))
    assert _open(conn, "file_move_detected")
    notices._check_resolved(conn, None, _at(notices.FILE_MOVE_DETECTED_QUIET_HOURS))
    assert not _open(conn, "file_move_detected")


def test_file_move_card_stays_when_a_computer_failed_the_move(conn):
    _detected_move(conn, [("PC1", _at(0.2), 0)])
    notices._check_resolved(conn, None, _at(48))
    assert _open(conn, "file_move_detected")


# --------------------------------------------------- server_crash_report

class _CrashSettings:
    def __init__(self, db_path):
        self.db_path = str(db_path)


def _crash_file(tmp_path, when):
    directory = tmp_path / "crashes"
    directory.mkdir(exist_ok=True)
    path = directory / "20260924T080000-Collector.json"
    path.write_text('{"exception": {"message": "boom"}}', encoding="utf-8")
    os.utime(path, (when, when))


def _iso(epoch: float) -> str:
    return dt.datetime.fromtimestamp(epoch, dt.timezone.utc).isoformat()


def test_server_crash_card_closes_a_day_after_the_newest_crash(conn, tmp_path):
    settings = _CrashSettings(tmp_path / "dash.db")
    # Whole seconds: an isoformat round trip keeps microseconds only, so a
    # float start could land a hair under the 24 h line and flake.
    crashed = float(int(notices._PROCESS_STARTED) + 10)
    _crash_file(tmp_path, crashed)
    notices._check_server_crashes(conn, settings, _iso(crashed + 60))
    assert _open(conn, "server_crash_report")
    notices._check_server_crashes(conn, settings, _iso(crashed + 23 * 3600))
    assert _open(conn, "server_crash_report")
    notices._check_server_crashes(conn, settings, _iso(crashed + 24 * 3600 + 1))
    assert not _open(conn, "server_crash_report")
    why = _auto_audit(conn, "server_crash_report")[-1]["detail"]["cleared_by"]
    assert why.startswith("auto: no new crash for 24 h")
    # The next pass finds nothing open and writes no second record.
    notices._check_server_crashes(conn, settings, _iso(crashed + 25 * 3600))
    assert len(_auto_audit(conn, "server_crash_report")) == 1
    assert "server_crash_report" in dbmod.notice_check_times(conn)


# ------------------------------------------ stale-subject state-shaped kinds

def test_a_healthy_projects_dir_clears_a_card_about_an_old_path(conn, tmp_path):
    projects = tmp_path / "projects"
    (projects / "one").mkdir(parents=True)
    dbmod.notice(conn, "projects_dir_missing", "error", "/old/projects", now=T0)
    settings = types.SimpleNamespace(projects_dir=str(projects))
    notices._check_tree(conn, settings, _at(1))
    assert not _open(conn, "projects_dir_missing")


def test_a_missing_projects_dir_is_not_cleared(conn, tmp_path):
    settings = types.SimpleNamespace(projects_dir=str(tmp_path / "gone"))
    notices._check_tree(conn, settings, T0)
    notices._check_resolved(conn, None, _at(24 * 30))
    notices._check_tree(conn, settings, _at(24 * 30))
    assert _open(conn, "projects_dir_missing", str(tmp_path / "gone"))


# ------------------------------------------- alerts: weekly_send_failed

@pytest.fixture
def env(tmp_path):
    app = create_app(Settings(
        db_path=str(tmp_path / "dash.db"), report_token="sekrit",
        session_secret="s", admin_users=frozenset({"owen"}),
    ))
    with TestClient(app) as client:
        # The same reset test_alerts.py's fixture does, for the same race.
        client.app.state.collector.stop()
        conn = dbmod.connect(tmp_path / "dash.db")
        conn.execute("DELETE FROM alert_log")
        conn.execute("DELETE FROM notices")
        conn.commit()
        try:
            yield conn, app.state.settings
        finally:
            conn.close()


def _weekly_failed(conn):
    dbmod.record_alert(conn, alerts.KIND_WEEKLY, "weekly", "ops@example.test",
                       False, "SMTP 535", T0)
    conn.commit()


def _kinds(conn, settings, now):
    return {f["kind"] for f in alerts.scan(conn, settings, now)}


def test_weekly_send_failed_recovers_once_the_channel_delivers_again(env):
    conn, settings = env
    _weekly_failed(conn)
    assert "weekly_send_failed" in _kinds(conn, settings, _at(1))
    # A test that went through the same channel afterwards.
    dbmod.record_alert(conn, alerts.KIND_TEST, "test", "ops@example.test", True,
                       "sent", _at(2))
    conn.commit()
    assert "weekly_send_failed" not in _kinds(conn, settings, _at(3))


@pytest.mark.parametrize("sent_to,ok,detail", [
    ("ops@example.test", False, "SMTP 535"),        # the test failed too
    ("", True, alerts.NO_SINK_DETAIL),               # nothing was sent anywhere
])
def test_weekly_send_failed_stays_without_a_real_delivery(env, sent_to, ok, detail):
    conn, settings = env
    _weekly_failed(conn)
    dbmod.record_alert(conn, alerts.KIND_TEST, "test", sent_to, ok, detail, _at(2))
    conn.commit()
    assert "weekly_send_failed" in _kinds(conn, settings, _at(3))


def test_a_resolver_that_raises_keeps_the_finding():
    def boom(ctx, finding):
        raise RuntimeError("no")
    kind = alerts.AlertKind("x", alerts.SEV_ERROR, "t", "w", lambda ctx: [],
                            resolved=boom)
    assert alerts._is_resolved(object(), kind, {"subject": "s"}) is False
