"""Tray surfacing of the safety latches (COMMERCIAL_READINESS.md item 9,
2026-08-17): the breaker line and its resume action, the halt line and its
stop/start actions, the trash size and the "won't upload" counter.

Menu construction only -- no Tk, no pystray icon (see test_tray.py's note).
"""

from __future__ import annotations

from ccsync_companion.sync.base import LaneStatus
from ccsync_companion.tray import (
    _breaker_line,
    _build_menu,
    _guard_fingerprint,
    _halt_line,
    _menu_fingerprint,
    _skipped_exists_line,
    _trash_line,
    _tray_snapshot,
    remove_blocker_body,
)


class _FakeIdentity:
    def valid(self):
        return True

    @property
    def username(self):
        return "owen"


class _FakeApp:
    def __init__(self, guard):
        self.config = {"dashboard_url": ""}
        self.log_path = "x.log"
        self.identity = _FakeIdentity()
        self.config_problems: list[str] = []
        self._require_login = True
        self._sync_enabled = True
        self._guard = guard

    def lane_statuses(self):
        return [LaneStatus(name="lane_b_proxy_down", state="paused")]

    def is_paused(self):
        return False

    def sync_guard(self):
        return self._guard


def _labels(menu):
    out = []
    for item in menu.items:
        out.append(str(item.text))
        submenu = getattr(item, "submenu", None)
        if submenu is not None:
            for sub in submenu.items:
                out.append(str(sub.text))
    return out


TRIPPED = {"lane_b_breaker": {"tripped": True, "reason": "the NAS listed the tree as EMPTY"}}
HALTED_LOCAL = {"halt": {"active": True, "scope": "local", "reason": "I stopped it"}}
HALTED_FLEET = {"halt": {"active": True, "scope": "fleet", "reason": "NAS maintenance"}}


# -- the lines --------------------------------------------------------------


def test_the_breaker_line_names_the_reason():
    line = _breaker_line(TRIPPED)
    assert "PROXY DOWNLOAD STOPPED" in line
    assert "EMPTY" in line


def test_no_breaker_line_when_nothing_is_tripped():
    assert _breaker_line({}) is None
    assert _breaker_line({"lane_b_breaker": {"tripped": False}}) is None


def test_the_halt_line_distinguishes_a_fleet_halt():
    assert "this machine" in _halt_line(HALTED_LOCAL)
    assert "everyone" in _halt_line(HALTED_FLEET)
    assert _halt_line({}) is None


def test_the_trash_line_appears_only_once_there_is_something_to_say():
    assert _trash_line({"trash": {"bytes": 1000, "count": 2}}) is None
    line = _trash_line({"trash": {"bytes": 4 * 1024**3, "count": 40}})
    assert "4.0 GB" in line and "40 files" in line


def test_the_skipped_exists_line_says_what_will_not_happen():
    line = _skipped_exists_line({"skipped_exists": {"count": 3}})
    assert "will NOT upload" in line
    assert _skipped_exists_line({"skipped_exists": {"count": 0}}) is None


# -- the menu ---------------------------------------------------------------


def test_a_tripped_breaker_puts_the_line_and_the_resume_action_in_the_menu():
    """The full advisory line (_breaker_line's own words, with the reason)
    moved to Settings -> SYNC LANES (2026-08-27); the reduced tray menu says
    only the short Sync: summary (_sync_line) plus the RESUME action, which
    stays top-level -- an editor whose syncing has stopped must not have to
    go looking for it."""
    labels = _labels(_build_menu(_FakeApp(TRIPPED)))
    assert "Sync: proxy download stopped (see Settings)" in labels
    assert "► Resume proxy download…" in labels


def test_a_healthy_machine_offers_no_resume_action():
    labels = _labels(_build_menu(_FakeApp({})))
    assert not any("Resume proxy download" in text for text in labels)


def test_stop_all_syncing_lives_in_settings_and_the_tray_only_flips_to_start():
    """"Stop ALL syncing…" moved wholly into Settings -> ADVANCED
    (2026-08-27, settings_window.py) -- it is never in the reduced tray menu
    at all, halted or not. "► Start syncing again" is the one half that
    stays top-level: an editor staring at a stopped tray must not have to go
    looking for it."""
    labels = _labels(_build_menu(_FakeApp({})))
    assert "Stop ALL syncing on this machine…" not in labels
    assert "► Start syncing again" not in labels

    labels = _labels(_build_menu(_FakeApp(HALTED_LOCAL)))
    assert "► Start syncing again" in labels
    assert "Stop ALL syncing on this machine…" not in labels


def test_a_fleet_halt_offers_no_local_start_button():
    """The full "...for everyone" sentence (_halt_line) moved to Settings;
    the reduced tray menu's Sync: line says the short version."""
    labels = _labels(_build_menu(_FakeApp(HALTED_FLEET)))
    assert "Sync: stopped by your admin" in labels
    assert "► Start syncing again" not in labels


# -- the rebuild trigger ----------------------------------------------------


def test_the_fingerprint_moves_when_the_breaker_trips():
    # Without this the resume ACTION would not appear until something
    # unrelated changed -- the bug UI-3 was.
    healthy = _tray_snapshot(_FakeApp({}))
    tripped = _tray_snapshot(_FakeApp(TRIPPED))
    assert _menu_fingerprint(healthy) != _menu_fingerprint(tripped)


def test_the_fingerprint_ignores_trash_growth_below_a_gigabyte():
    a = _guard_fingerprint({"trash": {"bytes": 1_000_000}})
    b = _guard_fingerprint({"trash": {"bytes": 900_000_000}})
    assert a == b
    assert _guard_fingerprint({"trash": {"bytes": 3 * 1024**3}}) != a


def test_a_broken_sync_guard_getter_does_not_take_the_tray_down():
    class _Broken(_FakeApp):
        def sync_guard(self):
            raise RuntimeError("boom")

    snap = _tray_snapshot(_Broken({}))
    assert snap["sync_guard"] == {}
    _build_menu(_Broken({}))       # must not raise


# -- the removal dialog body ------------------------------------------------


def test_the_blocked_removal_body_names_what_is_pending_and_the_word_to_type():
    body = remove_blocker_body("2026/CCT/Website Highlights", {
        "reasons": ["3 video file(s) have not been uploaded yet (e.g. A001.braw)"],
    })
    assert "A001.braw" in body
    assert "Website Highlights" in body
    assert "type the" in body


# -- the stall line (SYNC-1, resilience sweep 2026-08-28, CR-91) -------------


def test_the_stall_line_names_the_lane_and_stays_off_when_nothing_stalled():
    """Until this, a lane whose rclone had wedged on a drive that stopped
    answering said NOTHING on the machine it was happening on -- the fleet
    page was the only place the failure could ever have been seen, and there
    it read as `syncing`."""
    from datetime import datetime, timezone

    from ccsync_companion.tray import _stalled_line

    assert _stalled_line({}) is None
    assert _stalled_line({"stalled": {}}) is None
    now = datetime.now(timezone.utc).isoformat()
    line = _stalled_line({"stalled": {
        "lane": "B", "seconds": 1800, "killed": True, "at": now}})
    assert line is not None
    assert "Proxy download" in line
    assert "30 min" in line
    assert "drive" in line
    assert "—" not in line, "no em dashes in text an editor reads"
    assert "Uploading" in _stalled_line({"stalled": {
        "lane": "A", "seconds": 900, "killed": True, "at": now}})


def test_a_stall_from_last_week_is_history_not_a_menu_line():
    from ccsync_companion.tray import _stalled_line

    assert _stalled_line({"stalled": {
        "lane": "A", "seconds": 900, "killed": True,
        "at": "2026-08-01T10:00:00+00:00"}}) is None
    # An unreadable stamp is not silently treated as "just now" either.
    assert _stalled_line({"stalled": {"lane": "A", "at": "not a date"}}) is not None


def test_the_fingerprint_moves_when_a_stall_is_recorded():
    before = _guard_fingerprint({})
    after = _guard_fingerprint({"stalled": {
        "lane": "B", "seconds": 60, "killed": True,
        "at": "2026-08-28T10:00:00+00:00"}})
    assert before != after


# -- REL-8 / APP-5 (resilience sweep 2026-08-28) ----------------------------


def test_the_update_line_appears_only_once_the_machine_has_given_up():
    from ccsync_companion import upgrade as upgrade_mod
    from ccsync_companion.tray import _upgrade_line

    assert _upgrade_line({}) is None
    assert _upgrade_line({"upgrade": {"version": "9.9.9", "attempts": 3}}) is None

    line = _upgrade_line({"upgrade": {
        "version": "9.9.9", "attempts": upgrade_mod.MAX_UPGRADE_ATTEMPTS,
        "last_error": "sha-mismatch"}})
    assert line is not None
    assert "9.9.9" in line and "8 times" in line
    assert "\u2014" not in line


def test_the_rollback_line_names_the_build_that_kept_crashing():
    from ccsync_companion.tray import _reverted_line

    assert _reverted_line({"upgrade": {"attempts": 0}}) is None
    line = _reverted_line({"upgrade": {"reverted_from": "9.9.9"}})
    assert line is not None and "v9.9.9" in line
    assert "\u2014" not in line
