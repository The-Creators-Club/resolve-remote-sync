"""SYS-2 (resilience sweep 2026-08-28): supervision for the companion's own
loop threads.

The failure this closes: the sequencer thread died on one unhandled exception
and NOTHING noticed. The machine stayed online, kept reporting its frozen lane
state every 30 s, and the fleet grid showed it healthy for as long as the
editor left the tray running.

No threads that sleep for minutes and no real clock: LaneWatchdog.check() is
the whole policy and takes injected `now`/`monotonic`, and the app it watches
is duck-typed (a handful of attributes), so every decision here is tested
without a CompanionApp and without waiting.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Optional

from ccsync_companion.app import (
    LANE_WATCHDOG_WEDGED_SECONDS,
    WATCHDOG_STATE_FILENAME,
    LaneWatchdog,
)
from ccsync_companion.tray import RESTART_ADVISORY_COUNT, _restarts_line


# -- doubles ---------------------------------------------------------------


class _FakeSequencer:
    def __init__(self, rotation: float = 600.0) -> None:
        self.project_rotation_seconds = rotation
        self.starts = 0
        self.died = False
        self.silent = 0.0
        self.error: Optional[str] = None
        self.start_raises = False

    def thread_died(self) -> bool:
        return self.died

    def seconds_since_heartbeat(self) -> float:
        return self.silent

    def last_error(self) -> Optional[str]:
        return self.error

    def start(self) -> None:
        self.starts += 1
        if self.start_raises:
            raise RuntimeError("selection client is gone")
        self.died = False
        self.silent = 0.0


class _DeadThread:
    """A thread object that is simply not alive -- what app._watcher_thread
    looks like after the thread has ended."""

    name = "ccsync-watcher"

    def __init__(self, alive: bool = False) -> None:
        self._alive = alive

    def is_alive(self) -> bool:
        return self._alive


class _FakeApp:
    def __init__(self, sequencer: Any = None) -> None:
        self.sequencer = sequencer if sequencer is not None else _FakeSequencer()
        self._shutdown_started = False
        self._stop_event = threading.Event()
        self._media_tree_stop_event = threading.Event()
        self._watcher_thread: Any = None
        self._watcher_thread_error: Optional[str] = None
        self._media_tree_thread: Any = None
        self._media_tree_thread_error: Optional[str] = None
        self._media_tree_heartbeat: Optional[float] = None
        self.watcher: Any = None
        self.blocker = ""
        self.watcher_starts = 0
        self.media_tree_starts = 0

    def _standing_down_would_kill_work(self) -> str:
        return self.blocker

    def _start_watcher_thread(self) -> None:
        self.watcher_starts += 1
        self._watcher_thread = _DeadThread(alive=True)

    def _start_media_tree_thread(self) -> None:
        self.media_tree_starts += 1
        self._media_tree_thread = _DeadThread(alive=True)


class _Clock:
    def __init__(self, start: float = 1_700_000_000.0) -> None:
        self.t = start

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def _watchdog(app: _FakeApp, tmp_path: Path, clock: Optional[_Clock] = None,
              monotonic: Optional[_Clock] = None) -> LaneWatchdog:
    """interval=0 so start() would be a no-op: nothing here needs the loop
    thread, only check()."""
    return LaneWatchdog(
        app, interval=0.0,
        state_path=tmp_path / "state" / WATCHDOG_STATE_FILENAME,
        now=clock or _Clock(), monotonic=monotonic or _Clock(1000.0),
    )


# -- a dead sequencer ------------------------------------------------------


def test_a_dead_sequencer_is_restarted_and_recorded(tmp_path):
    app = _FakeApp()
    app.sequencer.died = True
    app.sequencer.error = "OSError: [WinError 53] P:\\ is gone"
    clock = _Clock()
    watchdog = _watchdog(app, tmp_path, clock=clock)

    assert watchdog.check() == ["sequencer"]
    assert app.sequencer.starts == 1

    report = watchdog.report()
    assert report["sequencer"]["count_24h"] == 1
    assert report["sequencer"]["count_1h"] == 1
    assert report["sequencer"]["last_error"] == "OSError: [WinError 53] P:\\ is gone"
    assert report["sequencer"]["last_at"].startswith("20")


def test_the_record_outlives_the_process(tmp_path):
    """A crash loop that takes the whole companion with it must not reset the
    counter that is the evidence of the crash loop."""
    app = _FakeApp()
    app.sequencer.died = True
    clock = _Clock()
    _watchdog(app, tmp_path, clock=clock).check()

    path = tmp_path / "state" / WATCHDOG_STATE_FILENAME
    assert json.loads(path.read_text(encoding="utf-8"))["threads"]["sequencer"]["events"]

    later = _Clock(clock.t + 120.0)
    reloaded = _watchdog(_FakeApp(), tmp_path, clock=later)
    assert reloaded.report()["sequencer"]["count_1h"] == 1


def test_an_event_older_than_a_day_falls_out_of_the_count(tmp_path):
    app = _FakeApp()
    app.sequencer.died = True
    clock = _Clock()
    watchdog = _watchdog(app, tmp_path, clock=clock)
    watchdog.check()

    clock.advance(2.0 * 3600.0)
    app.sequencer.died = True
    watchdog.check()
    entry = watchdog.report()["sequencer"]
    assert (entry["count_24h"], entry["count_1h"]) == (2, 1)

    clock.advance(25.0 * 3600.0)
    assert watchdog.report() == {}


def test_nothing_is_reported_while_nothing_has_been_restarted(tmp_path):
    watchdog = _watchdog(_FakeApp(), tmp_path)
    assert watchdog.check() == []
    assert watchdog.report() == {}


# -- a wedged sequencer ----------------------------------------------------


def test_the_sequencer_bound_is_three_rotations_or_thirty_minutes(tmp_path):
    """A big upload is not a wedge: one project turn is budgeted
    project_rotation_seconds per rclone lane, so the bound has to be a
    multiple of it."""
    app = _FakeApp(_FakeSequencer(rotation=600.0))
    app.sequencer.silent = LANE_WATCHDOG_WEDGED_SECONDS + 1.0
    assert _watchdog(app, tmp_path).check() == ["sequencer"]

    # A four-hour rotation moves the bound with it (3 x 14400 s).
    slow = _FakeApp(_FakeSequencer(rotation=4.0 * 3600.0))
    slow.sequencer.silent = LANE_WATCHDOG_WEDGED_SECONDS + 1.0
    assert _watchdog(slow, tmp_path).check() == []
    assert slow.sequencer.starts == 0


def test_a_busy_sequencer_inside_the_bound_is_left_alone(tmp_path):
    app = _FakeApp()
    app.sequencer.silent = LANE_WATCHDOG_WEDGED_SECONDS - 1.0
    assert _watchdog(app, tmp_path).check() == []
    assert app.sequencer.starts == 0


# -- the stand-downs -------------------------------------------------------


def test_nothing_is_restarted_while_the_companion_is_shutting_down(tmp_path):
    for field in ("_shutdown_started", "_stop_event"):
        app = _FakeApp()
        app.sequencer.died = True
        app._watcher_thread = _DeadThread(alive=False)
        app._media_tree_thread = _DeadThread(alive=False)
        if field == "_shutdown_started":
            app._shutdown_started = True
        else:
            app._stop_event.set()

        watchdog = _watchdog(app, tmp_path)
        assert watchdog.check() == []
        assert (app.sequencer.starts, app.watcher_starts,
                app.media_tree_starts) == (0, 0, 0)
        assert watchdog.report() == {}


def test_nothing_is_restarted_mid_popup_or_mid_consolidate(tmp_path):
    for blocker in ("popup", "consolidate"):
        app = _FakeApp()
        app.sequencer.died = True
        app.blocker = blocker
        assert _watchdog(app, tmp_path).check() == []
        assert app.sequencer.starts == 0


def test_a_sequencer_that_cannot_answer_is_assumed_fine(tmp_path):
    class _Broken(_FakeSequencer):
        def thread_died(self):
            raise RuntimeError("state read failed")

    app = _FakeApp(_Broken())
    assert _watchdog(app, tmp_path).check() == []
    assert app.sequencer.starts == 0


def test_a_failed_restart_is_recorded_rather_than_raised(tmp_path):
    app = _FakeApp()
    app.sequencer.died = True
    app.sequencer.start_raises = True
    watchdog = _watchdog(app, tmp_path)

    assert watchdog.check() == []
    entry = watchdog.report()["sequencer"]
    assert entry["count_24h"] == 1
    assert "restart failed" in entry["last_error"]


# -- the watcher and the media-tree thread --------------------------------


def test_a_dead_watcher_and_media_tree_thread_are_restarted(tmp_path):
    app = _FakeApp()
    app._watcher_thread = _DeadThread(alive=False)
    app._watcher_thread_error = "OSError: fusionscript went away"
    app._media_tree_thread = _DeadThread(alive=False)
    watchdog = _watchdog(app, tmp_path)

    assert watchdog.check() == ["watcher", "media_tree"]
    assert (app.watcher_starts, app.media_tree_starts) == (1, 1)
    assert watchdog.report()["watcher"]["last_error"] == "OSError: fusionscript went away"
    assert watchdog.report()["media_tree"]["last_error"] is None


def test_a_thread_that_was_never_started_is_not_a_fault(tmp_path):
    app = _FakeApp()
    app.sequencer = None
    assert _watchdog(app, tmp_path).check() == []


def test_a_deliberately_stopped_media_tree_thread_is_left_alone(tmp_path):
    app = _FakeApp()
    app._media_tree_thread = _DeadThread(alive=False)
    app._media_tree_stop_event.set()
    assert _watchdog(app, tmp_path).check() == []
    assert app.media_tree_starts == 0


def test_a_wedged_watcher_is_restarted_on_its_heartbeat(tmp_path):
    class _Watcher:
        pass

    app = _FakeApp()
    app._watcher_thread = _DeadThread(alive=True)
    watcher = _Watcher()
    app.watcher = watcher
    monotonic = _Clock(10_000.0)
    watcher._heartbeat = monotonic.t - (LANE_WATCHDOG_WEDGED_SECONDS + 1.0)

    assert _watchdog(app, tmp_path, monotonic=monotonic).check() == ["watcher"]

    # ...and a watcher whose build stamps no heartbeat at all is absent
    # evidence, never evidence of a fault.
    plain = _FakeApp()
    plain._watcher_thread = _DeadThread(alive=True)
    plain.watcher = _Watcher()
    assert _watchdog(plain, tmp_path, monotonic=monotonic).check() == []


def test_a_wedged_media_tree_thread_is_restarted_on_its_heartbeat(tmp_path):
    app = _FakeApp()
    app._media_tree_thread = _DeadThread(alive=True)
    monotonic = _Clock(10_000.0)
    app._media_tree_heartbeat = monotonic.t - (LANE_WATCHDOG_WEDGED_SECONDS + 1.0)
    assert _watchdog(app, tmp_path, monotonic=monotonic).check() == ["media_tree"]


# -- the tray advisory ----------------------------------------------------


def test_the_tray_line_appears_only_at_three_restarts_in_an_hour():
    assert _restarts_line({}) is None
    assert _restarts_line({"restarts": {}}) is None
    assert _restarts_line({"restarts": {"sequencer": {"count_24h": 9, "count_1h": 2}}}) is None

    line = _restarts_line({"restarts": {
        "sequencer": {"count_24h": 9, "count_1h": RESTART_ADVISORY_COUNT},
        "watcher": {"count_24h": 1, "count_1h": 1},
    }})
    assert "keeps restarting its sync engine" in line
    assert "diagnostics" in line
    assert "\u2014" not in line  # no em dashes in anything an editor reads


def test_a_junk_restarts_section_never_takes_the_line_down():
    for junk in ({"restarts": 7}, {"restarts": {"sequencer": "nope"}},
                 {"restarts": {"sequencer": {"count_1h": "x"}}}):
        assert _restarts_line(junk) is None or isinstance(_restarts_line(junk), str)


# -- the app's side: the report section, diagnostics, and the wiring -------


def _app(tmp_path):
    from ccsync_companion.app import CompanionApp

    root = tmp_path / "root"
    root.mkdir(parents=True, exist_ok=True)
    return CompanionApp({
        "editor_name": "owen",
        "local_root": str(root),
        "canonical_prefix": "P:\\",
        "remote": "creators_club_sftp",
        "remote_root": "/mnt/tank/Creators_Club",
        "log_path": str(tmp_path / "companion.log"),
        "dashboard_url": "",
        "sync_enabled": False,
        "lane_b_enabled": False,
    })


class _StubWatchdog:
    _state_path = Path("watchdog.json")

    def __init__(self, report):
        self._report = report

    def report(self):
        return self._report


def test_the_report_carries_restarts_only_once_something_was_restarted(tmp_path):
    app = _app(tmp_path)
    assert "restarts" not in app.sync_guard()

    app._lane_watchdog = _StubWatchdog({
        "sequencer": {"count_24h": 4, "count_1h": 3, "last_at": "2026-08-28T10:00:00+00:00",
                      "last_error": "OSError: P: is gone"}})
    guard = app.sync_guard()
    assert guard["restarts"]["sequencer"]["count_24h"] == 4

    # ...and a watchdog that cannot answer must never take the report down:
    # the whole section is a diagnostic, and a diagnostic that fails the
    # report cycle would take the alarm with it.
    class _Broken:
        def report(self):
            raise RuntimeError("no")

    app._lane_watchdog = _Broken()
    assert "restarts" not in app.sync_guard()


def test_diagnostics_names_the_restarts_and_the_record(tmp_path):
    app = _app(tmp_path)
    app._lane_watchdog = _StubWatchdog({
        "sequencer": {"count_24h": 4, "count_1h": 3, "last_at": "2026-08-28T10:00:00+00:00",
                      "last_error": "OSError: P: is gone"}})

    text = app.build_diagnostics()
    assert "background thread restarts" in text
    assert "sequencer: 4 restart(s) in 24h, 3 in the last hour" in text
    assert "OSError: P: is gone" in text

    app._lane_watchdog = None
    assert "the thread watchdog is not running" in app.build_diagnostics()


def test_diagnostics_says_none_rather_than_nothing(tmp_path):
    """"Could not check" and "nothing has happened" must never render the
    same way."""
    app = _app(tmp_path)
    app._lane_watchdog = _StubWatchdog({})
    assert "no background thread has needed restarting" in app.build_diagnostics()


def test_the_watchdog_is_built_once_and_writes_beside_the_other_latches(tmp_path):
    app = _app(tmp_path)
    try:
        app._start_lane_watchdog()
        first = app._lane_watchdog
        assert first is not None
        assert first._state_path == Path(app._state_dir) / WATCHDOG_STATE_FILENAME
        app._start_lane_watchdog()
        assert app._lane_watchdog is first
    finally:
        if app._lane_watchdog is not None:
            app._lane_watchdog.stop()


def test_the_watcher_thread_records_what_killed_it(tmp_path):
    """LaneWatchdog's record says WHY, which means the thread wrapper has to
    catch the exception on its way past -- and re-raise it, so
    threading.excepthook and crash_report still see it (SYS-2)."""
    import pytest

    app = _app(tmp_path)

    class _Watcher:
        def run(self, stop_event):
            raise OSError("fusionscript went away")

    app.watcher = _Watcher()
    with pytest.raises(OSError):
        app._watcher_thread_target()
    assert app._watcher_thread_error == "OSError: fusionscript went away"


def test_the_media_tree_loop_stamps_a_heartbeat(tmp_path):
    app = _app(tmp_path)
    app._media_tree_heartbeat = 0.0
    app._media_tree_stop_event.set()   # one iteration is all this needs...

    app._media_tree_loop()             # ...and it exits before doing any work
    assert app._media_tree_heartbeat == 0.0

    app._media_tree_stop_event.clear()
    calls = []

    def once():
        calls.append(1)
        app._media_tree_stop_event.set()

    app._refresh_media_tree_once = once
    app._refresh_p_mapping_mode = lambda: None
    app._media_tree_loop()
    assert calls == [1]
    assert app._media_tree_heartbeat > 0.0
