"""comp-app-core-1 / comp-app-core-4 (2026-08-21): the two ways an update
lands on a machine, and the two ways that used to leave it behind.

  * the single-instance hand-off waited 20 s for a predecessor whose bounded
    teardown joins sum to more than that, so the CHILD gave up and exited
    while the parent was still stopping lanes -- R11's outcome (no companion
    until the next logon) reached through the timer R11 introduced;
  * unattended updates (site [features] auto_update) fired exactly once per
    offer, so a stand-down ("a CCSync window is open", a consolidate) or a
    failed download parked the flag for that build until the tray restarted.
"""

from __future__ import annotations

import threading
from typing import Any

from ccsync_companion import app as app_mod
from ccsync_companion import site as site_mod
from ccsync_companion.app import CompanionApp


# -- comp-app-core-1: the predecessor wait ----------------------------------


def test_the_predecessor_wait_outlasts_a_normal_shutdown():
    """The two constants were unrelated numbers in two files; app.py's own
    comment ("only for as long as a normal shutdown takes") was unenforced."""
    assert app_mod.PREDECESSOR_WAIT_SECONDS >= app_mod.SHUTDOWN_WORST_CASE_SECONDS


def test_the_child_waits_out_a_slow_teardown():
    """Mid lane-B download, Resolve open, the watcher inside a fusionscript
    call: the parent's joins run past 20 s and the mutex is still held. The
    child must still take the slot rather than exit."""
    now = [0.0]
    slow = app_mod.SHUTDOWN_WORST_CASE_SECONDS - 1.0

    def clock():
        return now[0]

    def sleep(seconds):
        now[0] += seconds

    def alive(pid):
        return now[0] < slow

    assert app_mod._wait_for_predecessor(4242, 4242, alive, clock=clock,
                                         sleep_fn=sleep) is True
    assert now[0] >= slow


def test_a_wedged_predecessor_is_still_refused():
    """Bounded on purpose: a predecessor that is wedged rather than shutting
    down is a genuine second instance, and two companions is the failure the
    guard exists to prevent."""
    now = [0.0]

    def clock():
        return now[0]

    def sleep(seconds):
        now[0] += seconds

    assert app_mod._wait_for_predecessor(4242, 4242, lambda pid: True,
                                         clock=clock, sleep_fn=sleep) is False


# -- comp-app-core-4: the unattended update ---------------------------------


def _cfg(tmp_path, **overrides) -> dict[str, Any]:
    root = tmp_path / "root"
    root.mkdir(parents=True, exist_ok=True)
    cfg = {
        "editor_name": "owen",
        "local_root": str(root),
        "canonical_prefix": "P:\\",
        "remote": "creators_club_sftp",
        "remote_root": "/mnt/tank/Creators_Club",
        "active_project": "",
        "log_path": str(tmp_path / "companion.log"),
        "dashboard_url": "http://dash.example.com",
        "popup_enabled": False,
        "sync_enabled": False,
        "lane_b_enabled": False,
    }
    cfg.update(overrides)
    return cfg


def _join_upgrade_threads() -> None:
    for thread in list(threading.enumerate()):
        if thread.name in {"ccsync-pushed-upgrade", "ccsync-auto-upgrade"}:
            thread.join(timeout=5)


def _auto_update_app(tmp_path, monkeypatch, outcomes):
    """An app whose site has unattended updates on, holding an offer, with
    apply_upgrade answering from `outcomes` in order ("" = swapped)."""
    app = CompanionApp(_cfg(tmp_path))
    monkeypatch.setattr(site_mod, "feature_enabled",
                        lambda name, site=None: name == "auto_update")
    monkeypatch.setattr(app, "_notify_tray", lambda *a, **kw: None)
    app.upgrade._available = {"version": "9.9.9", "url": "/x",
                              "sha256": "0" * 64, "size_bytes": 1}
    calls: list[bool] = []

    def fake_apply(*, quiet_refusals=False):
        calls.append(quiet_refusals)
        return outcomes.pop(0) if outcomes else ""

    monkeypatch.setattr(app, "apply_upgrade", fake_apply)
    return app, calls


def test_an_unattended_update_refused_by_an_open_window_is_retried(tmp_path, monkeypatch):
    """CR-41 fixed this shape for the admin PUSH and left the auto path a
    single fire -- on the machines auto_update exists for (an out-of-tree
    popup takes the lock seconds after every launch, CR-27), which is where
    the "just restart the tray" answer loses the race too."""
    app, calls = _auto_update_app(tmp_path, monkeypatch, ["popup", "popup", ""])
    clock = [1000.0]
    monkeypatch.setattr(app_mod.time, "monotonic", lambda: clock[0])

    app._on_upgrade_available({"version": "9.9.9"})
    _join_upgrade_threads()
    assert calls == [False]                     # first attempt, toasts allowed
    assert app._auto_update_applying == ""      # the latch is RELEASED on refusal

    # The very next report does not hammer: the retry is held off. (The
    # trigger is _on_report_response -- see the wiring test below; the offer
    # itself rides that same reply, so it is fed directly here.)
    clock[0] += 30
    app._maybe_auto_update()
    _join_upgrade_threads()
    assert calls == [False]

    clock[0] += app_mod.PUSHED_UPDATE_RETRY_SECONDS
    app._maybe_auto_update()
    _join_upgrade_threads()
    assert calls == [False, True]               # quiet: the editor was told once

    clock[0] += app_mod.PUSHED_UPDATE_RETRY_SECONDS
    app._maybe_auto_update()
    _join_upgrade_threads()
    assert calls == [False, True, True]         # ...and this one swapped


def test_a_failed_unattended_download_waits_the_longer_back_off(tmp_path, monkeypatch):
    app, calls = _auto_update_app(tmp_path, monkeypatch, ["failed", ""])
    clock = [1000.0]
    monkeypatch.setattr(app_mod.time, "monotonic", lambda: clock[0])
    # REL-8's back-off is persisted, so it is measured on the wall clock.
    wall = [10_000.0]
    monkeypatch.setattr(app_mod.time, "time", lambda: wall[0])

    def _advance(seconds):
        clock[0] += seconds
        wall[0] += seconds

    app._on_upgrade_available({"version": "9.9.9"})
    _join_upgrade_threads()
    _advance(app_mod.PUSHED_UPDATE_RETRY_SECONDS)
    app._maybe_auto_update()
    _join_upgrade_threads()
    assert calls == [False]                     # not yet: a failure waits longer

    _advance(app_mod.PUSHED_UPDATE_FAILED_RETRY_SECONDS)
    app._maybe_auto_update()
    _join_upgrade_threads()
    assert calls == [False, True]


def test_a_withdrawn_offer_stops_the_unattended_retries(tmp_path, monkeypatch):
    """The gate is the offer in hand, not a version this machine once saw:
    an admin who unpublishes a bad build must not be chased by it."""
    app, calls = _auto_update_app(tmp_path, monkeypatch, ["popup", ""])
    clock = [1000.0]
    monkeypatch.setattr(app_mod.time, "monotonic", lambda: clock[0])

    app._on_upgrade_available({"version": "9.9.9"})
    _join_upgrade_threads()
    app.upgrade._available = None
    clock[0] += app_mod.PUSHED_UPDATE_RETRY_SECONDS
    app._maybe_auto_update()
    _join_upgrade_threads()
    assert calls == [False]
    assert app._auto_update_version == ""


def test_the_site_turning_auto_update_off_stops_the_retries(tmp_path, monkeypatch):
    app, calls = _auto_update_app(tmp_path, monkeypatch, ["popup", ""])
    clock = [1000.0]
    monkeypatch.setattr(app_mod.time, "monotonic", lambda: clock[0])

    app._on_upgrade_available({"version": "9.9.9"})
    _join_upgrade_threads()
    monkeypatch.setattr(site_mod, "feature_enabled", lambda name, site=None: False)
    clock[0] += app_mod.PUSHED_UPDATE_RETRY_SECONDS
    app._maybe_auto_update()
    _join_upgrade_threads()
    assert calls == [False]


def test_every_report_is_a_chance_to_retry(tmp_path, monkeypatch):
    """The retry has to ride the report reply: that is the only thing that
    happens on a parked machine, and it is the channel the offer arrives on."""
    app = CompanionApp(_cfg(tmp_path))
    monkeypatch.setattr(app, "_notify_tray", lambda *a, **kw: None)
    tried: list[bool] = []
    monkeypatch.setattr(app, "_maybe_auto_update", lambda: tried.append(True))

    app._on_report_response({"ok": True})
    assert tried == [True]
