"""Bug hunt 2026-09-11, comp-app (CR-233): the companion app core.

One section per finding. Nothing here touches a real Resolve, a real Tk root,
a real socket or a real clock: the app is built the way test_app.py builds it,
the watchdog's policy is called directly (its own hatch), and the loopback
retry's elapsed time is moved by resetting the deadline the retry itself
wrote.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from ccsync_companion import broll_server as broll_server_mod
from ccsync_companion import eula as eula_mod
from ccsync_companion import machine as machine_mod
from ccsync_companion import ui_copy
from ccsync_companion.app import (
    LANE_WATCHDOG_BACKOFF_SECONDS,
    LANE_WATCHDOG_MAX_RESTARTS_PER_HOUR,
    LOOPBACK_RETRY_MAX_SECONDS,
    LOOPBACK_RETRY_MIN_SECONDS,
    MAX_REPORTED_LIST,
    WATCHDOG_STATE_FILENAME,
    CompanionApp,
    LaneWatchdog,
)


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
        "dashboard_url": "",
        "popup_enabled": False,
        "sync_enabled": True,
        "require_login": False,
        "lane_b_enabled": False,
    }
    cfg.update(overrides)
    return cfg


def _app(tmp_path, **overrides) -> CompanionApp:
    return CompanionApp(_cfg(tmp_path, **overrides))


# -- comp-app-1: one predicate behind both doors ----------------------------
#
# "Sync now" is the most-clicked item in the menu. It answered "Sync
# requested: lane_a_video_up, lane_b_proxy_down, lane_c_syncthing" on five of
# the six machines _start_lanes() refuses to start, i.e. exactly the machines
# where nothing was going to happen.


def test_sync_now_refuses_while_syncing_is_paused_from_the_tray(tmp_path):
    app = _app(tmp_path)
    app._paused = True
    verdict = app.sync_now_result()
    assert verdict["accepted"] is False
    assert verdict["lanes"] == []
    assert "paused" in verdict["reason"].lower()


def test_sync_now_refuses_and_says_so_while_the_fleet_is_halted(tmp_path):
    app = _app(tmp_path)
    app.halt.engage("the NAS is being rebuilt", scope="fleet")
    verdict = app.sync_now_result()
    assert verdict["accepted"] is False
    assert "STOPPED" in verdict["reason"]
    assert "the NAS is being rebuilt" in verdict["reason"]


def test_sync_now_refuses_on_a_config_problem_that_stops_syncing(tmp_path):
    app = _app(tmp_path, remote_root="not-absolute")
    assert app.config_problems, "a non-absolute remote_root must be an error"
    verdict = app.sync_now_result()
    assert verdict["accepted"] is False
    assert verdict["reason"]


def test_sync_now_refuses_behind_the_licence_gate(tmp_path):
    """The CR-27 population: parked by a new EULA version, clicking the one
    item that used to tell them a pass was running."""
    app = _app(tmp_path)
    eula_mod.acceptance_path().unlink(missing_ok=True)
    verdict = app.sync_now_result()
    assert verdict["accepted"] is False
    assert "licence" in verdict["reason"].lower()
    assert ui_copy.ACCEPT_LICENCE_SETTINGS in verdict["reason"]


def test_sync_now_refuses_while_the_sync_drive_is_disconnected(tmp_path):
    app = _app(tmp_path)
    app._root_absent = True
    verdict = app.sync_now_result()
    assert verdict["accepted"] is False
    assert "disconnected" in verdict["reason"]


def test_sync_now_does_not_trigger_a_pass_on_a_halted_machine(tmp_path):
    """The half that matters: the toast was wrong AND the pass was asked for
    on a sequencer _start_lanes deliberately never started."""
    triggered: list[str] = []

    class _Seq:
        def trigger_pass_now(self) -> None:
            triggered.append("now")

    app = _app(tmp_path)
    app._managed = True
    app.sequencer = _Seq()
    app.halt.engage("stopped from the tray on this machine")

    verdict = app.sync_now()
    assert verdict["accepted"] is False
    assert triggered == []


def test_sync_now_still_accepts_on_a_healthy_machine(tmp_path):
    """The shared predicate must not turn into a sixth refusal of its own."""
    app = _app(tmp_path)
    verdict = app.sync_now_result()
    assert verdict["accepted"] is True
    assert "lane_a_video_up" in verdict["lanes"]


def test_every_gate_start_lanes_refuses_on_is_one_sync_now_can_name(tmp_path):
    """The structural half: _start_lanes() dispatches on _lanes_refusal()'s
    gate ids, so a gate added to one door exists at the other by
    construction."""
    app = _app(tmp_path)
    gates = {app.LANE_GATE_PAUSED, app.LANE_GATE_HALT, app.LANE_GATE_CONFIG,
             app.LANE_GATE_EULA, app.LANE_GATE_ROOT_ABSENT,
             app.LANE_GATE_SYNC_DISABLED}
    assert len(gates) == 6
    app._paused = True
    assert app._lanes_refusal()[0] == app.LANE_GATE_PAUSED
    app._paused = False
    app.halt.engage("x")
    assert app._lanes_refusal()[0] == app.LANE_GATE_HALT


def test_a_paused_machine_still_does_not_start_its_lanes(tmp_path):
    """_start_lanes() keeps every refusal it had (the refactor's own risk)."""
    app = _app(tmp_path)
    started: list[str] = []
    for lane in app.lanes:
        lane.start = lambda name=lane.name: started.append(name)
    app._paused = True
    app._start_lanes()
    assert started == [] and app._lanes_started is False


# -- comp-app-2 / comp-app-4: the reported payload, and its ceiling ---------


class _StubWatcher:
    """Only what resolve_health() reads."""

    def __init__(self, refused: int = 0, missing: int = 0) -> None:
        self.last_counts = {"out_of_tree": 1, "bad_prefix": 0, "missing": missing}
        self.last_scan_at = "2026-09-11T09:00:00+00:00"
        self.last_resolve_project = "FF5"
        self._refused = [{"name": f"clip{i}.mov", "path": f"D:/x/clip{i}.mov"}
                         for i in range(refused)]
        self._missing = [{"name": f"gone{i}.mov", "path": f"P:/x/gone{i}.mov"}
                         for i in range(missing)]

    def non_canonical_refused(self) -> list[dict[str, str]]:
        return list(self._refused)

    def missing_clips(self) -> list[dict[str, str]]:
        return list(self._missing)

    def bridge_is_connected(self) -> bool:
        return True


def test_non_canonical_refused_is_capped_on_the_wire(tmp_path):
    """comp-app-4: only a SUCCESSFUL relink ever leaves that dict, so a
    project in the "Energy Transition" shape put its whole media pool on
    every 30 s report."""
    app = _app(tmp_path)
    app.watcher = _StubWatcher(refused=400, missing=400)
    health = app.resolve_health()
    assert len(health["non_canonical_refused"]) == MAX_REPORTED_LIST
    assert len(health["missing_clips"]) == MAX_REPORTED_LIST


def test_resolve_health_sends_the_documented_keys_and_nothing_else(tmp_path):
    """comp-app-2: the payload is the contract the dashboard declares against
    (SYS-3's lesson, three recurrences in). A key added here without the
    other half is dropped in silence, so the set is pinned."""
    app = _app(tmp_path)
    app.watcher = _StubWatcher(refused=2)
    health = app.resolve_health()
    assert set(health) == {
        "out_of_tree", "bad_prefix", "missing",
        "connected", "project_open", "wedged_seconds", "wedged_call",
        "missing_clips", "non_canonical_refused",
        "proxy_attach", "proxy_gaps", "stills",
        "ignored_this_session", "ignored_folders", "skipped_ever",
        "last_scan_at", "open_project",
    }


# -- comp-app-3: the licence refusal names the button's real home -----------


def test_the_licence_refusal_points_at_the_section_the_button_is_in(tmp_path):
    eula_mod.acceptance_path().unlink(missing_ok=True)
    problem = eula_mod.acceptance_problem()
    assert problem
    assert ui_copy.ACCEPT_LICENCE_SETTINGS in problem
    assert "THIS COMPUTER" not in problem


def test_every_licence_refusal_uses_the_one_route(tmp_path):
    path = tmp_path / "eula_accepted.json"
    path.write_text(json.dumps({"accepted_at": "2026-09-11T00:00:00+00:00"}),
                    encoding="utf-8")
    assert ui_copy.ACCEPT_LICENCE_SETTINGS in (eula_mod.acceptance_problem(path) or "")

    eula_mod.record_acceptance("0.1", path=path)
    assert ui_copy.ACCEPT_LICENCE_SETTINGS in (eula_mod.acceptance_problem(path) or "")


def test_the_route_ends_at_a_button_that_exists() -> None:
    src = Path(__file__).resolve().parents[1] / "src" / "ccsync_companion"
    settings = (src / "settings_window.py").read_text(encoding="utf-8")
    assert ui_copy.ROUTE_ROWS[ui_copy.ACCEPT_LICENCE_SETTINGS] in settings


# -- comp-app-5: an unreadable machine.json is not an absent one ------------


@pytest.mark.parametrize("payload", [b"", b"{\"machine_id\": \"abc", b"[]"])
def test_a_corrupt_machine_file_is_not_re_minted(tmp_path, payload):
    path = tmp_path / "machine.json"
    path.write_bytes(payload)
    assert machine_mod.machine_id(path) == ""
    assert path.read_bytes() == payload, (
        "an unreadable id file was overwritten with a new id: the dashboard "
        "reads that as another computer, and the old id is gone for good")


def test_an_absent_machine_file_still_mints(tmp_path):
    path = tmp_path / "machine.json"
    minted = machine_mod.machine_id(path)
    assert minted and machine_mod.machine_id(path) == minted


def test_read_record_tells_absent_from_unreadable(tmp_path):
    path = tmp_path / "machine.json"
    assert machine_mod.read_record(path) == (None, True)
    path.write_text("{oh no", encoding="utf-8")
    assert machine_mod.read_record(path) == (None, False)
    path.write_text(json.dumps({"machine_id": "abc"}), encoding="utf-8")
    record, readable = machine_mod.read_record(path)
    assert readable and record["machine_id"] == "abc"


# -- comp-app-6: the loopback retry backs off -------------------------------


def test_the_loopback_retry_backs_off_while_the_port_stays_held(tmp_path, monkeypatch):
    """It is not "one bind attempt a minute": every attempt re-reads the
    config, re-resolves the mounts and writes a six-line WARNING naming the
    retired standalone companion. ~720 of those a day through a 5 MB rotating
    log is the day's real evidence gone."""
    app = _app(tmp_path)
    attempts: list[int] = []

    monkeypatch.setattr(broll_server_mod, "is_enabled", lambda cfg: True)
    monkeypatch.setattr(broll_server_mod, "last_bind_error",
                        lambda: "port 8899 is in use")
    monkeypatch.setattr(app, "_start_broll_server",
                        lambda: attempts.append(1))

    assert app.retry_loopback_bind() is False
    assert len(attempts) == 1
    first_delay = app._loopback_retry_delay
    assert first_delay >= LOOPBACK_RETRY_MIN_SECONDS

    # The next tick comes round while the port is still held: no attempt.
    assert app.retry_loopback_bind() is False
    assert len(attempts) == 1

    # The wait elapses: one more attempt, and the wait doubles.
    app._loopback_retry_after = 0.0
    assert app.retry_loopback_bind() is False
    assert len(attempts) == 2
    assert app._loopback_retry_delay == min(first_delay * 2, LOOPBACK_RETRY_MAX_SECONDS)

    # A DIFFERENT error is new evidence: try it straight away.
    monkeypatch.setattr(broll_server_mod, "last_bind_error", lambda: "permission denied")
    app._loopback_retry_after = 0.0
    assert app.retry_loopback_bind() is False
    assert app._loopback_retry_delay == first_delay


def test_the_loopback_retry_clears_its_backoff_once_the_port_is_ours(tmp_path, monkeypatch):
    app = _app(tmp_path)
    monkeypatch.setattr(broll_server_mod, "is_enabled", lambda cfg: True)
    monkeypatch.setattr(broll_server_mod, "last_bind_error", lambda: "in use")
    monkeypatch.setattr(app, "_start_broll_server", lambda: None)
    app.retry_loopback_bind()
    assert app._loopback_retry_after > 0

    def _win() -> None:
        app._broll_server = object()

    monkeypatch.setattr(app, "_start_broll_server", _win)
    app._loopback_retry_after = 0.0
    assert app.retry_loopback_bind() is True
    assert app._loopback_retry_delay == 0.0
    app._broll_server = None


# -- comp-app-7: the watchdog's ledger is a policy input --------------------


class _Clock:
    def __init__(self, start: float = 1_700_000_000.0) -> None:
        self.t = start

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


class _DeadSequencer:
    """A sequencer whose start() never fixes anything: the crash-loop shape."""

    project_rotation_seconds = 600.0

    def __init__(self) -> None:
        self.starts = 0

    def thread_died(self) -> bool:
        return True

    def seconds_since_heartbeat(self) -> float:
        return 0.0

    def last_error(self) -> str:
        return "RuntimeError: the selection client is gone"

    def start(self) -> None:
        self.starts += 1


class _FakeApp:
    def __init__(self) -> None:
        import threading

        self.sequencer = _DeadSequencer()
        self._shutdown_started = False
        self._stop_event = threading.Event()
        self._media_tree_stop_event = threading.Event()
        self._watcher_thread = None
        self._watcher_thread_error = None
        self._media_tree_thread = None
        self._media_tree_thread_error = None
        self._media_tree_heartbeat = None
        self.watcher = None

    def _standing_down_would_kill_work(self) -> str:
        return ""

    def _start_watcher_thread(self) -> None:
        pass

    def _start_media_tree_thread(self) -> None:
        pass


def _watchdog(app, tmp_path, clock) -> LaneWatchdog:
    return LaneWatchdog(app, interval=0.0,
                        state_path=tmp_path / "state" / WATCHDOG_STATE_FILENAME,
                        now=clock, monotonic=_Clock(1000.0))


def test_a_thread_that_dies_again_is_not_restarted_every_tick(tmp_path):
    """No backoff and no ceiling meant one restart per LANE_WATCHDOG_INTERVAL
    for ever, and one JSON write per tick with it."""
    app = _FakeApp()
    clock = _Clock()
    watchdog = _watchdog(app, tmp_path, clock)

    assert watchdog.check() == ["sequencer"]
    clock.advance(60.0)
    assert watchdog.check() == [], "a restart 60s after the last one is a spin"
    assert app.sequencer.starts == 1

    clock.advance(LANE_WATCHDOG_BACKOFF_SECONDS)  # the wait after one restart
    assert watchdog.check() == ["sequencer"]
    assert app.sequencer.starts == 2


def test_the_watchdog_stops_trying_after_the_hourly_ceiling(tmp_path):
    app = _FakeApp()
    clock = _Clock()
    watchdog = _watchdog(app, tmp_path, clock)

    for _ in range(60):
        watchdog.check()
        clock.advance(60.0)
    assert app.sequencer.starts <= LANE_WATCHDOG_MAX_RESTARTS_PER_HOUR, (
        "a restart that has not worked N times in an hour is a fault to show, "
        "not a loop to keep spinning")
    assert watchdog.report()["sequencer"]["count_1h"] >= 1


def test_the_ceiling_lifts_once_the_hour_has_passed(tmp_path):
    """Refused, not disabled: the thread is still down and still wanted."""
    app = _FakeApp()
    clock = _Clock()
    watchdog = _watchdog(app, tmp_path, clock)
    for _ in range(60):
        watchdog.check()
        clock.advance(60.0)
    before = app.sequencer.starts

    clock.advance(2.0 * 3600.0)
    assert watchdog.check() == ["sequencer"]
    assert app.sequencer.starts == before + 1


def test_a_clock_that_steps_backwards_does_not_erase_the_evidence(tmp_path):
    """_load_record dropped every event stamped in what is now the future, so
    one NTP correction wiped the crash-loop record the file is persisted to
    survive - and the ceiling above reads exactly those events."""
    app = _FakeApp()
    clock = _Clock()
    _watchdog(app, tmp_path, clock).check()

    earlier = _Clock(clock.t - 600.0)
    reloaded = _watchdog(_FakeApp(), tmp_path, earlier)
    assert reloaded.report().get("sequencer", {}).get("count_1h") == 1


# -- comp-resolve-2 (owed here by the comp-resolve builder): a REHEARSAL ----
#
# fixer_dry_run's arm answers {"ok": True, "dry_run": True} for every op: it
# did what it was asked, which was nothing. The consolidate toast counted
# those as files brought in and the upload phase ran a lane A push behind
# them, so a rehearsal read as a finished copy-and-upload.


class _FakeProgress:
    def __init__(self, title: str, subtitle: str = "") -> None:
        self.title = title

    def publish(self, info: dict) -> None:
        pass

    def should_stop(self) -> bool:
        return False

    def cancelled(self) -> bool:
        return False

    def run(self, worker) -> None:
        worker(self.publish, self.should_stop)


class _Tray:
    def __init__(self) -> None:
        self.notifications: list[tuple[str, str]] = []

    def notify(self, msg, title) -> None:
        self.notifications.append((msg, title))


def _consolidate_app(tmp_path, monkeypatch, results):
    from ccsync_companion import consolidate, popup, resolve_bridge

    other = tmp_path / "other"
    other.mkdir()
    stray = other / "A001.braw"
    stray.write_bytes(b"x" * 10)

    app = _app(tmp_path, active_project="Projects/2026/X/Y", popup_enabled=False)
    tray = _Tray()
    app._tray_icon = tray
    monkeypatch.setattr(resolve_bridge, "get_media_pool_items", lambda: {
        "ok": True, "message": "", "project_name": "MyProject",
        "items": [{"file_path": str(stray), "media_pool_item": object(),
                   "clip_name": "clip", "resolve_project_name": "MyProject"}],
    })
    monkeypatch.setattr(consolidate, "reconcile_with_nas",
                        lambda *a, **k: {"ok": True,
                                         "uploads": {"count": 1, "bytes": 1},
                                         "downloads": {"count": 0, "bytes": 0}})
    monkeypatch.setattr("ccsync_companion.popup.confirm_dialog", lambda *a, **k: True)
    monkeypatch.setattr(popup, "ProgressWindow", _FakeProgress)
    monkeypatch.setattr(consolidate, "run_consolidation",
                        lambda *a, **k: list(results))
    lanes: list[str] = []
    app._lane_a.run_once = lambda subpath=None: lanes.append("lane_a")
    app._lane_b.run_once = lambda subpath=None: lanes.append("lane_b")
    return app, tray, lanes


def test_a_rehearsed_consolidate_is_not_reported_as_copied(tmp_path, monkeypatch):
    results = [{"ok": True, "dry_run": True, "file_path": "A001.braw"},
               {"ok": True, "dry_run": True, "file_path": "A002.braw"}]
    app, tray, lanes = _consolidate_app(tmp_path, monkeypatch, results)

    app.consolidate_project()

    messages = [msg for msg, _title in tray.notifications]
    assert any("Rehearsal finished" in m for m in messages), messages
    assert not any("Copy & upload finished" in m for m in messages), messages
    assert lanes == [], "a rehearsal copied nothing, so there is nothing to upload"


def test_a_real_consolidate_still_copies_uploads_and_says_so(tmp_path, monkeypatch):
    results = [{"ok": True, "file_path": "A001.braw"}]
    app, tray, lanes = _consolidate_app(tmp_path, monkeypatch, results)

    app.consolidate_project()

    messages = [msg for msg, _title in tray.notifications]
    assert any("Copy & upload finished" in m for m in messages), messages
    assert "lane_a" in lanes


# -- comp-ui-1 (owed here by the comp-ui builder): the startup line ---------
#
# A Windows tray icon whose registration fails leaves a running companion
# with no icon and no pump, and every toast after it is discarded in silence.
# The log said "tray icon started" either way, so the machine whose editor was
# told nothing all day read exactly like a healthy one.


class _Icon:
    def __init__(self, registered) -> None:
        if registered is not None:
            self.registered = registered


def test_the_startup_line_says_whether_the_icon_is_actually_there(tmp_path, caplog):
    app = _app(tmp_path)

    with caplog.at_level("INFO", logger="ccsync.app"):
        app._log_tray_state(_Icon(True))
    assert "registered with the desktop" in caplog.text
    assert "NOT in the notification area" not in caplog.text

    caplog.clear()
    with caplog.at_level("INFO", logger="ccsync.app"):
        app._log_tray_state(_Icon(False))
    assert "NOT in the notification area" in caplog.text
    assert [r for r in caplog.records if r.levelname == "WARNING"]


def test_a_backend_that_cannot_answer_is_not_reported_as_a_failure(tmp_path, caplog):
    """macOS, a test double, an older build: absent evidence is not a fault."""
    app = _app(tmp_path)
    with caplog.at_level("INFO", logger="ccsync.app"):
        app._log_tray_state(_Icon(None))
    assert "tray icon started" in caplog.text
    assert "NOT in the notification area" not in caplog.text
    assert not [r for r in caplog.records if r.levelname == "WARNING"]


# -- the comp-sync hand-offs, app.py's half --------------------------------


def test_the_report_carries_the_two_readers_nothing_called(tmp_path):
    """comp-sync-4: SYNC-101/SYNC-102's producers were computed every pass
    and reached nobody - not the tray, not the report."""
    app = _app(tmp_path)

    class _Seq:
        def shared_folder_problems(self):
            return ["The shared LUT library is not linked on this computer."]

        def repath_events(self):
            return [{"old": "Projects/A", "new": "Projects/B",
                     "at": "2026-09-11T09:00:00+00:00", "relinked": 4}]

    app.sequencer = _Seq()
    guard = app.sync_guard()
    assert guard["shared_folder_problems"] == [
        "The shared LUT library is not linked on this computer."]
    assert guard["repath_events"][0]["new"] == "Projects/B"


def test_a_quiet_machine_sends_neither_section(tmp_path):
    """Absent is how "the shared folders are fine" is spelled."""
    app = _app(tmp_path)
    guard = app.sync_guard()
    assert "shared_folder_problems" not in guard
    assert "repath_events" not in guard


class _Reminder:
    def __init__(self) -> None:
        self.begun: list[str] = []
        self.state_episodes: list[tuple[str, str]] = []
        self.ended = 0
        self.remembered = False
        self.resume_states: list = []

    def begin(self, summary) -> None:
        self.begun.append(summary)

    def begin_state(self, state, sentence) -> None:
        self.state_episodes.append((state, sentence))

    def end_state_episode(self) -> None:
        self.ended += 1

    def resume_remembered(self, state=None) -> bool:
        self.resume_states.append(state)
        return self.remembered

    def clear(self) -> None:
        pass


def test_a_drive_that_wedges_after_it_vanished_opens_an_episode(tmp_path, monkeypatch):
    """comp-sync-9: absent -> not_answering (an SMB mapping that drops and
    comes back as a stale session) opened no episode at all - the editor got
    the calm "disconnected" line and then silence."""
    from ccsync_companion import root_guard as root_guard_mod

    app = _app(tmp_path)
    reminder = _Reminder()
    app._drive_reminder = reminder
    monkeypatch.setattr(app, "_unfinished_before_pause", lambda: None)
    monkeypatch.setattr(app, "_root_pause_lanes", lambda: None)
    app._tray_icon = _Tray()

    app._on_root_absent(root_guard_mod.ROOT_ABSENT)
    assert reminder.state_episodes == []

    app._on_root_absent(root_guard_mod.ROOT_NOT_ANSWERING)
    assert [state for state, _s in reminder.state_episodes] == [
        root_guard_mod.ROOT_NOT_ANSWERING]

    # ...and the same state again is not a second balloon.
    app._on_root_absent(root_guard_mod.ROOT_NOT_ANSWERING)
    assert len(reminder.state_episodes) == 1


def test_the_unfinished_judgement_is_made_once_per_outage(tmp_path, monkeypatch):
    """CR-92: work owed is judged at the moment the drive goes. A state
    change inside the same outage must not re-ask (the lanes are paused by
    then, so the answer would be "nothing owed")."""
    from ccsync_companion import root_guard as root_guard_mod

    app = _app(tmp_path)
    reminder = _Reminder()
    app._drive_reminder = reminder
    asked: list[int] = []

    def _unfinished():
        asked.append(1)
        return "2 files still to upload"

    monkeypatch.setattr(app, "_unfinished_before_pause", _unfinished)
    monkeypatch.setattr(app, "_root_pause_lanes", lambda: None)
    app._tray_icon = _Tray()

    app._on_root_absent(root_guard_mod.ROOT_ABSENT)
    app._on_root_absent(root_guard_mod.ROOT_NOT_ANSWERING)
    assert asked == [1]
    assert reminder.begun == ["2 files still to upload"]


def test_the_current_state_is_passed_to_resume_remembered(tmp_path, monkeypatch):
    """comp-sync-8: without it a wedge remembered from the previous run is
    replayed at a drive now in the editor's bag."""
    from ccsync_companion import root_guard as root_guard_mod

    app = _app(tmp_path)
    reminder = _Reminder()
    app._drive_reminder = reminder
    monkeypatch.setattr(app, "_unfinished_before_pause", lambda: None)
    monkeypatch.setattr(app, "_root_pause_lanes", lambda: None)
    app._tray_icon = _Tray()

    app._on_root_absent(root_guard_mod.ROOT_ABSENT)
    assert reminder.resume_states == [root_guard_mod.ROOT_ABSENT]


def test_the_restored_drive_sentence_uses_the_sites_own_letter(tmp_path, monkeypatch):
    """comp-sync-21: it said "P:" to every customer whose canonical_prefix is
    not P:, about a drive it had just restored under a different letter."""
    from ccsync_companion import drive_swap

    app = _app(tmp_path, canonical_prefix="R:\\")
    monkeypatch.setattr(app, "canonical_drive_letter", lambda: "R:")
    monkeypatch.setattr(app, "p_swap_available", lambda: True)
    monkeypatch.setattr(app, "_server_p_unc", lambda: r"\\nas\share")
    monkeypatch.setattr(drive_swap, "swap_to_server",
                        lambda *a, **k: (False, "the server refused"))
    monkeypatch.setattr(drive_swap, "swap_to_local",
                        lambda *a, **k: (True, "restored"))

    ok, message = app.swap_p_to_server()

    assert ok is False
    assert "R: was restored to your local copy." in message
    assert "P: was restored" not in message


def _move_command(move_id=7):
    return {"id": move_id, "from_project_rel": "Projects/A", "from_rel": "a.mov",
            "to_project_rel": "Projects/B", "to_rel": "a.mov",
            "requested_by": "alex"}


def test_a_move_delivered_while_the_drive_is_out_answers_retrying(tmp_path):
    """comp-sync-20: the dashboard expires a command after 7 days of "told
    and never answered", so silence dropped the move for an editor who was
    away with the drive in their bag."""
    app = _app(tmp_path)
    app._root_absent = True
    app._apply_file_moves({"commands": {"file_moves": [_move_command()]}})

    answers = app._file_move_answers
    assert len(answers) == 1
    assert answers[0]["id"] == 7
    assert answers[0]["state"] == "retrying"
    assert "sync drive" in answers[0]["detail"]
    # Waiting for a drive is not an attempt: it must not spend the budget a
    # real failure needs.
    assert "attempts" not in answers[0]
    assert app.file_moves.entry(7) is None, "nothing was decided about the move"


def test_the_move_is_applied_through_the_ledger(tmp_path, monkeypatch):
    """res-companion-1: without the ledger, apply_move cannot write the
    `applying` intent row and the crash window stays open."""
    from ccsync_companion import file_moves as file_moves_mod

    app = _app(tmp_path)
    seen: dict[str, Any] = {}

    def _apply(move, local_root, ledger=None):
        seen["ledger"] = ledger
        return False, "nothing at the old path on this machine", None

    monkeypatch.setattr(file_moves_mod, "apply_move", _apply)
    app._apply_file_moves({"commands": {"file_moves": [_move_command(9)]}})
    assert seen["ledger"] is app.file_moves


def test_the_watchers_repeat_offers_are_de_duped_too(tmp_path, monkeypatch):
    """comp-sync-13: the de-dupe was inside `if user_initiated:` and the
    comment said both producers latch once per process. RES-19's cooldown
    made that untrue, so a project Resolve keeps refusing queued the same
    clip every 15 minutes for the life of the process."""
    from ccsync_companion import resolve_bridge

    app = _app(tmp_path)
    monkeypatch.setattr(resolve_bridge, "media_pool_item_is_reachable",
                        lambda item: True)
    # Single-flight: the worker never starts, so the queue is observable.
    app._canon_relink_busy = True

    items = [{"file_path": r"D:\Stock\A001.mov", "media_pool_item": object()}]
    app._handle_non_canonical(list(items))
    app._handle_non_canonical(list(items))
    app._handle_non_canonical(list(items))

    assert len(app._canon_relink_pending) == 1


def test_the_relink_queue_has_a_ceiling(tmp_path, monkeypatch):
    from ccsync_companion import resolve_bridge
    from ccsync_companion.app import MAX_CANON_RELINK_PENDING

    app = _app(tmp_path)
    monkeypatch.setattr(resolve_bridge, "media_pool_item_is_reachable",
                        lambda item: True)
    app._canon_relink_busy = True

    app._handle_non_canonical(
        [{"file_path": f"D:\\Stock\\A{i:05d}.mov", "media_pool_item": object()}
         for i in range(MAX_CANON_RELINK_PENDING + 25)])

    assert len(app._canon_relink_pending) == MAX_CANON_RELINK_PENDING
    # The NEWEST offers survive: a full queue that nothing new can enter is
    # the queue that never drains the clip the editor is looking at.
    assert app._canon_relink_pending[-1]["file_path"].endswith(
        f"A{MAX_CANON_RELINK_PENDING + 24:05d}.mov")
