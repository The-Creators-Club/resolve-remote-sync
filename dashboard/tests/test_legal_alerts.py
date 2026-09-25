"""G2b's alert kinds for the legal-gap features (docs/LEGAL_GAP_FEATURES_PLAN.md,
2026-09-25): `dashboard_reached_over_public_http` (LG-4) fires on positive
evidence of plain http from the internet and never for a private network;
`collector_kind_overdue` (LG-17) is late-not-failed, debounced by one alerts
cycle and blind to kinds this site does not schedule; and a computer that
switches reporting off (LG-1) neither raises nor RECOVERS a finding about
what it no longer sends; an open one is closed without a message.
"""
from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import alerts
from ccsync_dashboard import db as dbmod
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

NOW = "2026-09-25T12:00:00+00:00"


def _ago(seconds: float) -> str:
    return (dt.datetime.fromisoformat(NOW) - dt.timedelta(seconds=seconds)).isoformat()


@pytest.fixture
def env(tmp_path):
    app = create_app(Settings(db_path=str(tmp_path / "dash.db"), report_token="sekrit",
                              session_secret="s", admin_users=frozenset({"owen"})))
    with TestClient(app) as client:
        client.app.state.collector.stop()
        conn = dbmod.connect(tmp_path / "dash.db")
        for table in ("alert_log", "notices", "poll_runs"):
            conn.execute(f"DELETE FROM {table}")
        conn.commit()
        try:
            yield conn, app.state.settings
        finally:
            conn.close()


def _machine(conn, editor, machine, **cols):
    dbmod.upsert_machine(conn, editor, machine, now=NOW)
    conn.execute(
        "INSERT OR IGNORE INTO machine_state (editor_username, machine, reported_at,"
        " received_at, companion_version) VALUES (?, ?, ?, ?, '0.9.80')",
        (editor, machine, NOW, NOW))
    for key, value in cols.items():
        conn.execute(f"UPDATE machine_state SET {key}=? WHERE editor_username=? AND machine=?",
                     (value, editor, machine))
    conn.commit()


def _found(conn, settings, kind):
    return [f for f in alerts.scan(conn, settings, NOW) if f["kind"] == kind]


def test_both_kinds_are_registered_with_an_evaluator():
    by_name = {k.kind: k for k in alerts.ALERT_KINDS}
    for kind in ("dashboard_reached_over_public_http", "collector_kind_overdue"):
        assert kind in by_name and callable(by_name[kind].check)


# ------------------------------------------------------------------ LG-4

def test_public_http_fires_only_for_http_public(env):
    conn, settings = env
    _machine(conn, "tchen", "RIG", report_via="http_public")
    _machine(conn, "leso", "MAC", report_via="http_local")
    _machine(conn, "owen", "BASE", report_via="https")
    _machine(conn, "old", "PC")                                   # not seen since v59
    found = _found(conn, settings, "dashboard_reached_over_public_http")
    assert [f["subject"] for f in found] == ["tchen/RIG"]
    assert found[0]["severity"] == alerts.SEV_ERROR
    assert "password" in found[0]["diagnosis"]
    assert "—" not in found[0]["diagnosis"] + found[0]["fix"]


def test_a_private_network_fleet_raises_nothing(env):
    conn, settings = env
    _machine(conn, "leso", "MAC", report_via="http_local")
    assert _found(conn, settings, "dashboard_reached_over_public_http") == []


# ----------------------------------------------------------------- LG-17

def _runs(conn, prune_finished_ago: float, prune_ok: bool = True):
    # A live fast kind, so a late prune is "overdue" and not "the collector
    # stopped" (collector_health marks nothing overdue while it is stale).
    dbmod.record_poll_run(conn, "alerts", _ago(12), _ago(10), True, None)
    dbmod.record_poll_run(conn, "prune", _ago(prune_finished_ago + 1),
                          _ago(prune_finished_ago), prune_ok,
                          None if prune_ok else "disk I/O error")
    conn.commit()


def test_a_retention_pass_long_overdue_is_alerted_in_its_own_words(env):
    conn, settings = env
    _runs(conn, prune_finished_ago=4 * 3600)
    found = _found(conn, settings, "collector_kind_overdue")
    assert [f["subject"] for f in found] == ["poll prune"]
    assert "retention" in found[0]["diagnosis"]
    assert _found(conn, settings, "collector_kind_failed") == []


def test_just_past_the_bound_is_amber_on_the_panel_but_not_mailed(env):
    conn, settings = env
    # interval_prune 3600 s -> bound 7200 s (+ the ~1 s cycle); the alert
    # waits one more alerts interval (600 s) on top.
    _runs(conn, prune_finished_ago=7200 + 200)
    health = dbmod.collector_health(conn, now=NOW, settings=settings)
    prune = next(k for k in health["kinds"] if k["kind"] == "prune")
    assert prune["overdue"] and prune["status"] == "amber"
    assert _found(conn, settings, "collector_kind_overdue") == []


def test_on_time_is_nothing(env):
    conn, settings = env
    _runs(conn, prune_finished_ago=1800)
    assert _found(conn, settings, "collector_kind_overdue") == []


def test_a_failed_kind_is_the_failed_alert_not_the_overdue_one(env):
    conn, settings = env
    _runs(conn, prune_finished_ago=4 * 3600, prune_ok=False)
    assert _found(conn, settings, "collector_kind_overdue") == []
    assert [f["subject"] for f in _found(conn, settings, "collector_kind_failed")] == [
        "poll prune"]


def test_an_unscheduled_kind_is_never_overdue(env):
    """No syncthing_url: the Syncthing-backed kinds do not run here, so an
    old `enforce` row is a feature switched off, not a stuck job (safety
    L5)."""
    conn, settings = env
    _runs(conn, prune_finished_ago=60)
    dbmod.record_poll_run(conn, "enforce", _ago(10 * 3600), _ago(10 * 3600 - 1), True, None)
    conn.commit()
    assert _found(conn, settings, "collector_kind_overdue") == []


# ------------------------------------------------------------------ LG-1

def test_a_withholding_computer_never_raised_says_nothing(env):
    conn, settings = env
    _machine(conn, "leso", "MAC", moved_project_dirs_count=2,
             report_optouts='["local_manifest"]')
    assert _found(conn, settings, "moved_project_dir") == []
    assert _found(conn, settings, "stray_projects") == []


def test_a_computer_that_reports_its_file_list_is_judged_as_before(env):
    conn, settings = env
    _machine(conn, "leso", "MAC", moved_project_dirs_count=2,
             report_optouts='["input_idle"]')
    found = _found(conn, settings, "moved_project_dir")
    assert [f["subject"] for f in found] == ["leso/MAC"]
    assert not found[0].get("quiet")


# ------------------------------------------ review round (2026-09-25)

def _deliver(conn, settings, kind):
    findings = [f for f in alerts.scan(conn, settings, NOW) if f["kind"] == kind]
    return findings, alerts.deliver(conn, settings, findings, NOW)


def test_switching_reporting_off_closes_an_open_finding_without_a_message(env):
    """The quiet hold kept the row open for as long as the switch stayed off,
    with a stale count and in every digest's "still open from before"."""
    conn, settings = env
    _machine(conn, "tchen", "RIG", stray_projects_count=3, stray_projects_bytes=10)
    dbmod.record_alert(conn, "stray_projects", "tchen/RIG", "none", True, now=_ago(3600))
    conn.execute("UPDATE machine_state SET report_optouts='[\"local_manifest\"]'")
    conn.commit()
    findings, result = _deliver(conn, settings, "stray_projects")
    assert len(findings) == 1 and findings[0].get("withdrawn") is True
    assert not findings[0].get("quiet")
    assert result["recovered"] == 0 and result["sent"] == 0
    assert not alerts._is_open(conn, "stray_projects", "tchen/RIG")
    closed = conn.execute(
        "SELECT sent_to, detail FROM alert_log WHERE kind='stray_projects.ok'").fetchall()
    assert [(r["sent_to"], r["detail"].startswith("closed without a message")) for r in closed] \
        == [("", True)]
    # Next cycle: closed and withheld, so nothing at all.
    assert _found(conn, settings, "stray_projects") == []


def test_an_open_overdue_job_is_held_quiet_when_its_last_run_failed(env):
    conn, settings = env
    _runs(conn, prune_finished_ago=4 * 3600, prune_ok=False)
    dbmod.record_alert(conn, "collector_kind_overdue", "poll prune", "none", True,
                       now=_ago(3600))
    conn.commit()
    findings, result = _deliver(conn, settings, "collector_kind_overdue")
    assert [(f["subject"], f.get("quiet")) for f in findings] == [("poll prune", True)]
    assert result["recovered"] == 0
    assert alerts._is_open(conn, "collector_kind_overdue", "poll prune")


def test_an_open_overdue_job_is_held_quiet_while_the_collector_is_stopped(env):
    conn, settings = env
    # Every kind last ran hours ago: the collector itself has stopped.
    dbmod.record_poll_run(conn, "alerts", _ago(6 * 3600 + 2), _ago(6 * 3600), True, None)
    dbmod.record_poll_run(conn, "prune", _ago(6 * 3600 + 2), _ago(6 * 3600), True, None)
    dbmod.record_alert(conn, "collector_kind_overdue", "poll prune", "none", True,
                       now=_ago(3600))
    conn.commit()
    assert dbmod.collector_health(conn, now=NOW, settings=settings)["collector_stale"]
    findings, result = _deliver(conn, settings, "collector_kind_overdue")
    assert [(f["subject"], f.get("quiet")) for f in findings] == [("poll prune", True)]
    assert result["recovered"] == 0
    assert alerts._is_open(conn, "collector_kind_overdue", "poll prune")


def test_a_job_that_ran_again_on_time_still_recovers(env):
    conn, settings = env
    _runs(conn, prune_finished_ago=60)
    dbmod.record_alert(conn, "collector_kind_overdue", "poll prune", "none", True,
                       now=_ago(3600))
    conn.commit()
    findings, result = _deliver(conn, settings, "collector_kind_overdue")
    assert findings == [] and result["recovered"] == 1


def test_public_http_says_when_and_stops_repeating_for_a_quiet_computer(env):
    conn, settings = env
    _machine(conn, "tchen", "RIG", report_via="http_public")
    _machine(conn, "old", "LAPTOP", report_via="http_public",
             received_at=_ago(40 * 86400), reported_at=_ago(40 * 86400))
    found = {f["subject"]: f for f in _found(conn, settings,
                                             "dashboard_reached_over_public_http")}
    assert set(found) == {"tchen/RIG", "old/LAPTOP"}
    assert found["tchen/RIG"]["repeat"] is True
    assert found["old/LAPTOP"]["repeat"] is False
    assert "40 days ago" in found["old/LAPTOP"]["diagnosis"]
    assert "—" not in found["old/LAPTOP"]["diagnosis"] + found["old/LAPTOP"]["fix"]
