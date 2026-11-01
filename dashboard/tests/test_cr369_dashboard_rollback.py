"""CR-369 (2026-10-07): GL-20 and GL-21 of the prelaunch review.

GL-20: a dashboard bundle that crash-loops and is reverted must not be
re-applied by the release-feed poller 10 s later, for ever.
GL-21: a volume tree that boots but cannot serve exits 75 so the next start
counts it and, at two, reverts it.
"""
from __future__ import annotations

import json
import types

import pytest

from ccsync_dashboard import dashboard_update, release_feed as rf
from ccsync_dashboard.settings import Settings

# The subprocess harness test_select_code_root.py already owns.
from test_select_code_root import (  # noqa: F401
    NEW_VERSION, install_tree, make_record, run, set_current, world)

NOW = "2026-10-07T12:00:00+00:00"
SECRET = "n" * 32
_APP = types.SimpleNamespace()


def _settings(world):
    return Settings(db_path=str(world["data"] / "dashboard.db"), session_secret=SECRET)


def _offer(monkeypatch, versions):
    monkeypatch.setattr(dashboard_update, "status", lambda s, a: {
        "image_mode": True, "in_progress": False, "runtime_updates": [],
        "code_updates": [{"version": v, "published_at": "2026-01-01T00:00:00Z"}
                         for v in versions]})
    # The apply of a crash-looping bundle ends at step "done", not "failed".
    monkeypatch.setattr(dashboard_update, "read_state",
                        lambda s: {"step": "done", "version": versions[0]})


def _revert_it(world):
    install_tree(world, version="0.8.0", record=make_record(version="0.8.0"))
    install_tree(world)
    set_current(world, NEW_VERSION, previous="0.8.0")
    run(world)
    run(world)
    run(world)       # the third start reverts
    assert json.loads((world["code"] / "current.json").read_text())[
        "reverted_from"] == NEW_VERSION


# ------------------------------------------------------------------ GL-20

def test_revert_writes_the_durable_marker(world):
    _revert_it(world)
    marker = json.loads((world["code"] / "no_auto_apply.json").read_text())
    assert marker["version"] == NEW_VERSION and marker["reason"] and marker["at"]


def test_apply_revert_poll_does_not_reapply(world, conn, monkeypatch):
    """The whole loop: bundle applied, boots fail, revert, next poll."""
    settings = _settings(world)
    _offer(monkeypatch, [NEW_VERSION])
    # Before the incident the poller would take it.
    assert rf._dashboard_auto_apply_reason(conn, settings, _APP, NOW)[0] == NEW_VERSION
    _revert_it(world)
    version, why = rf._dashboard_auto_apply_reason(conn, settings, _APP, NOW)
    assert version == ""
    assert "reverted" in why and NEW_VERSION in why and "—" not in why


def test_reverted_from_alone_is_enough(world, conn, monkeypatch):
    """A site reverted before this fix has current.json but no marker."""
    settings = _settings(world)
    (world["code"] / "current.json").write_text(json.dumps(
        {"version": "0.8.0", "reverted_from": NEW_VERSION}))
    _offer(monkeypatch, [NEW_VERSION])
    assert rf._dashboard_auto_apply_reason(conn, settings, _APP, NOW)[0] == ""


def test_a_newer_version_is_taken_as_usual(world, conn, monkeypatch):
    settings = _settings(world)
    _revert_it(world)
    _offer(monkeypatch, ["9.9.10"])
    assert rf._dashboard_auto_apply_reason(conn, settings, _APP, NOW) == ("9.9.10", "")


def test_an_admin_apply_clears_the_marker_and_the_poller_does_not(world, monkeypatch):
    settings = _settings(world)
    _revert_it(world)
    monkeypatch.setattr(dashboard_update, "preflight", lambda *a, **k: {})
    monkeypatch.setattr(dashboard_update, "apply", lambda *a, **k: None)
    monkeypatch.setattr(dashboard_update, "_set_state", lambda *a, **k: None)
    dashboard_update.start_apply(settings, None, version=NEW_VERSION, force=False,
                                 started_by="release-feed (policy=current)")
    assert dashboard_update.read_no_auto_apply(settings)["version"] == NEW_VERSION
    dashboard_update.start_apply(settings, None, version=NEW_VERSION, force=False,
                                 started_by="alex")
    assert dashboard_update.read_no_auto_apply(settings) == {}


# ------------------------------------------------------------------ GL-21

def _volume_world(world, monkeypatch, *, source="volume", with_attempts=True):
    settings = _settings(world)
    monkeypatch.setattr(dashboard_update, "running_source", lambda s: source)
    if with_attempts:
        dashboard_update.boot_attempts_path(settings).write_text(
            json.dumps({"version": NEW_VERSION, "attempts": 1}))
    exits: list[int] = []
    monkeypatch.setattr(dashboard_update, "_exit_process", exits.append)
    return settings, exits


def test_a_volume_tree_that_cannot_serve_exits_75(world, monkeypatch):
    settings, exits = _volume_world(world, monkeypatch)
    monkeypatch.setattr(dashboard_update, "BOOT_HEALTHY_SECONDS", 0.0)
    monkeypatch.setattr(dashboard_update, "BOOT_HEALTH_PROBE_SECONDS", 0.0)
    monkeypatch.setattr(dashboard_update, "wait_until_serving",
                        lambda s, **k: (False, "500"))
    dashboard_update.start_boot_watchdog(settings).join(timeout=10)
    assert exits == [75]
    assert dashboard_update.boot_attempts_path(settings).exists()


@pytest.mark.parametrize("source,attempts", [("image", True), ("checkout", True),
                                             ("volume", False)])
def test_image_code_and_unjudged_trees_stay_log_only(world, monkeypatch, source, attempts):
    settings, exits = _volume_world(world, monkeypatch, source=source,
                                    with_attempts=attempts)
    assert dashboard_update.exit_for_revert(settings, "x") is False
    assert exits == []
    assert dashboard_update.arm_lifespan_deadline(settings, 0.01) is None


def test_the_lifespan_deadline_exits_75_and_cancels(world, monkeypatch):
    settings, exits = _volume_world(world, monkeypatch)
    timer = dashboard_update.arm_lifespan_deadline(settings, 0.05)
    timer.join(timeout=5)
    assert exits == [75]
    exits.clear()
    timer = dashboard_update.arm_lifespan_deadline(settings, 5)
    timer.cancel()
    timer.join(timeout=2)
    assert exits == []


def test_the_failed_boots_converge_on_a_revert(world):
    """Exit 75 means run.sh re-selects: boots 1 and 2 are counted, boot 3
    reverts, which is exactly the select_code_root contract this relies on."""
    _revert_it(world)


# ------------------------------------------- overseer defects (2026-10-07)

def _set_schema(world, live, previous_schema, previous="0.8.0"):
    import sqlite3
    conn = sqlite3.connect(str(world["data"] / "dashboard.db"))
    conn.execute(f"PRAGMA user_version = {live}")
    conn.commit()
    conn.close()
    install_tree(world, version=previous, record=make_record(version=previous))
    mpath = world["code"] / previous / "manifest.json"
    manifest = json.loads(mpath.read_text())
    manifest["schema_version"] = previous_schema
    mpath.write_text(json.dumps(manifest))
    cur = world["code"] / "current.json"
    cur.write_text(json.dumps({"version": dashboard_update.VERSION, "previous": previous}))


def test_a_refused_revert_keeps_the_process_up(world, monkeypatch):
    """Defect 1: the watchdog must not exit 75 when select_code_root would
    refuse the revert (live schema above the previous tree's)."""
    settings, exits = _volume_world(world, monkeypatch)
    _set_schema(world, live=99, previous_schema=10)
    monkeypatch.setattr(dashboard_update, "BOOT_HEALTHY_SECONDS", 0.0)
    monkeypatch.setattr(dashboard_update, "BOOT_HEALTH_PROBE_SECONDS", 0.0)
    monkeypatch.setattr(dashboard_update, "wait_until_serving",
                        lambda s, **k: (False, "500"))
    dashboard_update.start_boot_watchdog(settings).join(timeout=10)
    assert exits == []
    assert dashboard_update.boot_attempts_path(settings).exists()


def test_a_standing_refusal_for_this_version_keeps_the_process_up(world, monkeypatch):
    settings, exits = _volume_world(world, monkeypatch)
    (world["code"] / "current.json").write_text(json.dumps(
        {"version": dashboard_update.VERSION, "previous": "",
         "revert_refused_from": dashboard_update.VERSION}))
    assert dashboard_update.exit_for_revert(settings, "x") is False
    assert exits == []


def test_a_revertable_schema_still_exits_75(world, monkeypatch):
    settings, exits = _volume_world(world, monkeypatch)
    _set_schema(world, live=10, previous_schema=10)
    assert dashboard_update.exit_for_revert(settings, "x") is True or exits == [75]
    assert exits == [75]


def test_rollback_then_poll_does_not_reapply(world, conn, monkeypatch):
    """Defect 2: an admin's rollback away from NEW_VERSION must hold at the
    next poll, and an admin APPLY of it clears that."""
    settings = _settings(world)
    install_tree(world, version="0.8.0", record=make_record(version="0.8.0"))
    (world["code"] / "current.json").write_text(json.dumps(
        {"version": NEW_VERSION, "previous": "0.8.0"}))
    monkeypatch.setattr(dashboard_update, "image_mode", lambda: True)
    monkeypatch.setattr(dashboard_update, "request_restart", lambda s: None)
    monkeypatch.setattr(dashboard_update, "_set_state", lambda *a, **k: None)
    monkeypatch.setattr(dashboard_update, "read_state", lambda s: {"in_progress": False,
                                                                   "step": "done"})
    monkeypatch.setattr(dashboard_update, "schema_rollback_check",
                        lambda s, t: {"safe": True, "live": 1, "target": 1, "backup": ""})
    dashboard_update.rollback(settings, started_by="alex")
    assert dashboard_update.read_no_auto_apply(settings)["version"] == NEW_VERSION
    _offer(monkeypatch, [NEW_VERSION])
    version, why = rf._dashboard_auto_apply_reason(conn, settings, _APP, NOW)
    assert version == "" and "rolled back" in why and "—" not in why


def _stub_rollback(monkeypatch):
    monkeypatch.setattr(dashboard_update, "image_mode", lambda: True)
    monkeypatch.setattr(dashboard_update, "request_restart", lambda s: None)
    monkeypatch.setattr(dashboard_update, "_set_state", lambda *a, **k: None)
    monkeypatch.setattr(dashboard_update, "read_state",
                        lambda s: {"in_progress": False, "step": "done"})
    monkeypatch.setattr(dashboard_update, "schema_rollback_check",
                        lambda s, t: {"safe": True, "live": 1, "target": 1, "backup": ""})


def test_revert_then_unrelated_rollback_keeps_the_crashed_version(world, conn, monkeypatch):
    """Round 2 (GL-20): the marker is per version, so a rollback of 0.8.0 ADDS
    its entry and the crash-looping NEW_VERSION is still refused at the poll."""
    settings = _settings(world)
    _revert_it(world)
    _stub_rollback(monkeypatch)
    dashboard_update.rollback(settings, started_by="alex")
    entries = dashboard_update.no_auto_apply_entries(
        dashboard_update.read_no_auto_apply(settings))
    assert set(entries) == {NEW_VERSION, "0.8.0"}
    _offer(monkeypatch, [NEW_VERSION])
    version, why = rf._dashboard_auto_apply_reason(conn, settings, _APP, NOW)
    assert version == "" and "would not start" in why


def test_revert_then_admin_apply_of_another_version_keeps_the_marker(world, conn, monkeypatch):
    settings = _settings(world)
    _revert_it(world)
    monkeypatch.setattr(dashboard_update, "preflight", lambda *a, **k: {})
    monkeypatch.setattr(dashboard_update, "apply", lambda *a, **k: None)
    monkeypatch.setattr(dashboard_update, "_set_state", lambda *a, **k: None)
    dashboard_update.start_apply(settings, None, version="0.8.1", force=False,
                                 started_by="alex")
    assert NEW_VERSION in dashboard_update.no_auto_apply_entries(
        dashboard_update.read_no_auto_apply(settings))
    _offer(monkeypatch, [NEW_VERSION])
    version, _why = rf._dashboard_auto_apply_reason(conn, settings, _APP, NOW)
    assert version == ""


def test_the_legacy_single_key_marker_is_read_as_one_entry(world):
    assert dashboard_update.no_auto_apply_entries(
        {"version": "0.9.0", "reason": "r", "at": "t"}) == {"0.9.0": {"reason": "r", "at": "t"}}
