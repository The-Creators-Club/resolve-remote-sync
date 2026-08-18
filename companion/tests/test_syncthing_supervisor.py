"""The Syncthing supervisor (SYNC-17, 2026-08-18).

NO PROCESS IS EVER SPAWNED HERE. Every launch goes through the injected
`spawn` seam, and `_no_real_spawn` below replaces `subprocess.Popen` inside
the module with something that fails the test loudly -- a supervisor test
that could start a real daemon on the developer's machine would be a worse
bug than the one this module fixes.

The clock is injected too: nothing sleeps, and the backoff schedule is
asserted by moving a fake wall clock forward rather than by waiting.
"""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

import pytest

from ccsync_companion.sync import syncthing_supervisor as sup
from ccsync_companion.sync.syncthing_supervisor import (
    BALLOON_RESTARTED,
    LANE_ERROR_RESTARTING,
    SyncthingLauncher,
    SyncthingSupervisor,
    backoff_seconds,
    supervision_enabled,
)


@pytest.fixture(autouse=True)
def _no_real_spawn(monkeypatch):
    """The one guarantee this file makes about the developer's machine."""
    def _boom(*args, **kwargs):
        raise AssertionError(
            f"a test tried to spawn a real process: {args!r} {kwargs!r}")

    monkeypatch.setattr(sup.subprocess, "Popen", _boom)
    monkeypatch.setattr(sup.subprocess, "run", _boom)


class FakeClock:
    def __init__(self, now: float = 1_000_000.0) -> None:
        self.now = float(now)

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += float(seconds)


class FakeLauncher:
    """A SyncthingLauncher-shaped stand-in that records instead of starting."""

    def __init__(self, ok: bool = True, error: str = "", available: bool = True) -> None:
        self.ok = ok
        self.error = error
        self._available = available
        self.launches = 0

    def available(self) -> bool:
        return self._available

    def missing_reason(self) -> str:
        return "the sync engine launcher is missing (X:\\nowhere\\CCSyncSyncthing.vbs)"

    def command(self) -> list[str]:
        return ["wscript.exe", "//B", "//Nologo", "C:\\fake\\CCSyncSyncthing.vbs"]

    def launch(self) -> tuple[bool, str]:
        self.launches += 1
        return self.ok, self.error


def _supervisor(tmp_path, clock, launcher=None, probe=None, notify=None,
                suppressed=None, cfg=None, sleeps=None):
    def _sleep(seconds: float) -> None:
        # The fake sleep MOVES THE FAKE CLOCK. A no-op sleep next to a clock
        # that never advances is how a bounded wait becomes a hung test (and,
        # with a real clock stepped backwards, a hung poll thread) -- see
        # _wait_for_api, which is bounded by an iteration count as well.
        if sleeps is not None:
            sleeps.append(seconds)
        clock.advance(seconds)

    return SyncthingSupervisor(
        tmp_path / "state" / sup.STATE_FILENAME,
        cfg or {},
        launcher=launcher or FakeLauncher(),
        notify=notify,
        suppressed=suppressed,
        probe=probe,
        clock=clock,
        sleep=_sleep,
    )


# -- the core state machine -------------------------------------------------


def test_a_short_outage_starts_nothing(tmp_path):
    """A Syncthing restarting mid-config-commit is back inside the grace
    window; supervising THAT is a restart storm, not a fix."""
    clock = FakeClock()
    launcher = FakeLauncher()
    s = _supervisor(tmp_path, clock, launcher)

    s.tick(reachable=False)
    clock.advance(15)
    s.tick(reachable=False)
    assert launcher.launches == 0

    clock.advance(5)
    s.tick(reachable=True)
    assert launcher.launches == 0
    assert not s.incident_open


def test_unreachable_past_the_grace_window_starts_it_and_confirms(tmp_path):
    clock = FakeClock()
    launcher = FakeLauncher()
    balloons: list[tuple[str, str]] = []
    answers = [False, True]
    s = _supervisor(
        tmp_path, clock, launcher,
        probe=lambda: answers.pop(0) if answers else True,
        notify=lambda msg, title="": balloons.append((msg, title)),
    )

    s.tick(reachable=False)
    clock.advance(31)
    s.tick(reachable=False)

    assert launcher.launches == 1
    # The probe said yes, so the incident is closed inside the same tick.
    assert not s.incident_open
    assert s.lane_error() is None
    assert [msg for msg, _t in balloons] == [BALLOON_RESTARTED]


def test_the_balloon_fires_once_per_incident_not_once_per_tick(tmp_path):
    clock = FakeClock()
    launcher = FakeLauncher()
    balloons: list[str] = []
    s = _supervisor(tmp_path, clock, launcher, probe=lambda: True,
                    notify=lambda msg, title="": balloons.append(msg))

    s.tick(reachable=False)
    clock.advance(31)
    s.tick(reachable=False)
    for _ in range(5):
        clock.advance(15)
        s.tick(reachable=True)

    assert launcher.launches == 1
    assert balloons == [BALLOON_RESTARTED]


def test_it_never_loops_hot(tmp_path):
    """A hundred polls inside one backoff window buy exactly one attempt."""
    clock = FakeClock()
    launcher = FakeLauncher()
    s = _supervisor(tmp_path, clock, launcher, probe=lambda: False)

    s.tick(reachable=False)
    clock.advance(31)
    for _ in range(100):
        clock.advance(0.1)
        s.tick(reachable=False)
    assert launcher.launches == 1


def test_the_backoff_schedule_is_30s_1m_2m_capped_at_10m(tmp_path):
    assert backoff_seconds(0) == 0
    assert backoff_seconds(1) == 30
    assert backoff_seconds(2) == 60
    assert backoff_seconds(3) == 120
    assert backoff_seconds(4) == 240
    assert backoff_seconds(5) == 480
    assert backoff_seconds(6) == 600
    assert backoff_seconds(50) == 600


def test_attempts_are_spaced_by_the_backoff(tmp_path):
    """The window is measured from when an attempt FINISHED -- the post-launch
    wait for the API is part of the attempt, not part of the backoff."""
    clock = FakeClock()
    launcher = FakeLauncher()
    # No probe: the attempt returns immediately, so the arithmetic below is
    # about the backoff and nothing else.
    s = _supervisor(tmp_path, clock, launcher, probe=None)

    s.tick(reachable=False)
    clock.advance(31)
    s.tick(reachable=False)
    assert launcher.launches == 1

    # 29 s later is inside the 30 s backoff.
    clock.advance(29)
    s.tick(reachable=False)
    assert launcher.launches == 1

    clock.advance(2)
    s.tick(reachable=False)
    assert launcher.launches == 2

    # Attempt 3 waits a full minute.
    clock.advance(59)
    s.tick(reachable=False)
    assert launcher.launches == 2
    clock.advance(2)
    s.tick(reachable=False)
    assert launcher.launches == 3


def test_the_wait_for_the_api_is_part_of_the_attempt_not_the_backoff(tmp_path):
    clock = FakeClock()
    launcher = FakeLauncher()
    s = _supervisor(tmp_path, clock, launcher, probe=lambda: False)

    s.tick(reachable=False)
    clock.advance(31)
    s.tick(reachable=False)
    assert launcher.launches == 1
    # The attempt burned the api-wait window on its probe loop; the next one
    # is still a full backoff away from the moment it gave up.
    spent = clock.now
    clock.advance(29)
    s.tick(reachable=False)
    assert launcher.launches == 1
    assert clock.now - spent < 30
    clock.advance(2)
    s.tick(reachable=False)
    assert launcher.launches == 2


def test_three_failures_warn_the_log_and_the_editor(tmp_path, caplog):
    clock = FakeClock()
    launcher = FakeLauncher(ok=False, error="Load failed: 5: Input/output error")
    balloons: list[str] = []
    s = _supervisor(tmp_path, clock, launcher,
                    notify=lambda msg, title="": balloons.append(msg))

    with caplog.at_level(logging.INFO, logger="ccsync.sync.supervisor"):
        s.tick(reachable=False)
        clock.advance(31)
        s.tick(reachable=False)          # attempt 1
        clock.advance(31)
        s.tick(reachable=False)          # attempt 2
        assert balloons == []
        assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
        clock.advance(61)
        s.tick(reachable=False)          # attempt 3

    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warnings, "three failed starts must reach WARNING"
    assert "Input/output error" in warnings[0].getMessage()
    assert balloons == ["Sync engine will not start: Load failed: 5: Input/output error"]
    # ...and it is said once, not on every later attempt.
    clock.advance(3600)
    s.tick(reachable=False)
    assert len(balloons) == 1


def test_after_three_failures_lane_c_says_why_not_that_it_is_restarting(tmp_path):
    clock = FakeClock()
    s = _supervisor(tmp_path, clock, FakeLauncher(ok=False, error="no such service"))

    s.tick(reachable=False)
    assert s.lane_error() == LANE_ERROR_RESTARTING
    for _ in range(3):
        clock.advance(700)
        s.tick(reachable=False)
    assert s.attempts >= 3
    assert s.lane_error() == (
        "the sync engine (Syncthing) could not be started: no such service")


def test_a_missing_launcher_is_a_failure_not_a_crash(tmp_path):
    clock = FakeClock()
    launcher = FakeLauncher(available=False)
    s = _supervisor(tmp_path, clock, launcher)

    s.tick(reachable=False)
    clock.advance(31)
    s.tick(reachable=False)

    assert launcher.launches == 0
    assert "launcher is missing" in s.last_error
    assert s.attempts == 1


def test_an_unconfirmed_launch_becomes_a_failure_on_the_next_poll(tmp_path):
    """With no probe wired the verdict is deferred, NOT dropped -- otherwise
    the commonest shape of "it will not start" (the shim runs, Syncthing
    exits) could never reach three strikes."""
    clock = FakeClock()
    launcher = FakeLauncher()
    s = _supervisor(tmp_path, clock, launcher, probe=None)

    s.tick(reachable=False)
    clock.advance(31)
    s.tick(reachable=False)
    assert launcher.launches == 1
    assert s.last_error == ""

    clock.advance(sup.API_WAIT_SECONDS + 1)
    s.tick(reachable=False)
    assert "still does not answer" in s.last_error


# -- the latches ------------------------------------------------------------


def test_a_halted_machine_is_left_alone(tmp_path, caplog):
    clock = FakeClock()
    launcher = FakeLauncher()
    s = _supervisor(tmp_path, clock, launcher,
                    suppressed=lambda: "syncing is halted on this machine")

    with caplog.at_level(logging.INFO, logger="ccsync.sync.supervisor"):
        s.tick(reachable=False)
        for _ in range(10):
            clock.advance(120)
            s.tick(reachable=False)

    assert launcher.launches == 0
    assert any("halted" in r.getMessage() for r in caplog.records), (
        "the refusal has to say why, or it looks like the supervisor is broken")
    # Lane C is still an ERROR -- the files are still not moving.
    assert s.lane_error() == (
        "the sync engine (Syncthing) is not running on this machine, and it is "
        "not being restarted: syncing is halted on this machine")


def test_the_refusal_is_logged_once_not_every_poll(tmp_path, caplog):
    clock = FakeClock()
    s = _supervisor(tmp_path, clock, FakeLauncher(),
                    suppressed=lambda: "syncing is paused from the tray")
    with caplog.at_level(logging.INFO, logger="ccsync.sync.supervisor"):
        for _ in range(20):
            clock.advance(60)
            s.tick(reachable=False)
    said = [r for r in caplog.records if "paused from the tray" in r.getMessage()]
    assert len(said) == 1


def test_a_suppression_check_that_raises_stands_off(tmp_path):
    """Fail towards not touching anything: a check that cannot answer "is
    this machine deliberately stopped" must not be read as "no"."""
    def _boom():
        raise RuntimeError("no")

    clock = FakeClock()
    launcher = FakeLauncher()
    s = _supervisor(tmp_path, clock, launcher, suppressed=_boom)
    s.tick(reachable=False)
    clock.advance(120)
    s.tick(reachable=False)
    assert launcher.launches == 0


def test_pause_lifting_lets_the_next_poll_start_it(tmp_path):
    clock = FakeClock()
    launcher = FakeLauncher()
    paused = {"yes": True}
    s = _supervisor(tmp_path, clock, launcher, probe=lambda: True,
                    suppressed=lambda: "syncing is paused from the tray" if paused["yes"] else "")

    s.tick(reachable=False)
    clock.advance(120)
    s.tick(reachable=False)
    assert launcher.launches == 0

    paused["yes"] = False
    clock.advance(15)
    s.tick(reachable=False)
    assert launcher.launches == 1


# -- the kill switch --------------------------------------------------------


def test_supervision_enabled_defaults_to_true_and_reads_both_spellings():
    assert supervision_enabled({}) is True
    assert supervision_enabled(None) is True
    assert supervision_enabled({"supervise_syncthing": False}) is False
    assert supervision_enabled({"supervise_syncthing": "false"}) is False
    assert supervision_enabled({"sync": {"supervise_syncthing": False}}) is False
    # A flat key always wins over the table, and garbage keeps supervision on.
    assert supervision_enabled({"supervise_syncthing": True,
                                "sync": {"supervise_syncthing": False}}) is True
    assert supervision_enabled({"supervise_syncthing": "yes please"}) is True


def test_the_kill_switch_starts_nothing_but_still_reports_the_error(tmp_path, caplog):
    clock = FakeClock()
    launcher = FakeLauncher()
    s = _supervisor(tmp_path, clock, launcher, cfg={"supervise_syncthing": False})

    with caplog.at_level(logging.INFO, logger="ccsync.sync.supervisor"):
        s.tick(reachable=False)
        for _ in range(5):
            clock.advance(600)
            s.tick(reachable=False)

    assert launcher.launches == 0
    assert "supervise_syncthing" in s.lane_error()
    assert any(r.levelno >= logging.WARNING for r in caplog.records)


# -- persistence ------------------------------------------------------------


def test_the_incident_survives_a_new_supervisor(tmp_path):
    """The companion self-upgrades. A counter that resets on restart is not a
    counter, and a three-strike rule that never reaches three warns nobody."""
    clock = FakeClock()
    state = tmp_path / "state" / sup.STATE_FILENAME
    first = _supervisor(tmp_path, clock, FakeLauncher(ok=False, error="nope"))

    first.tick(reachable=False)
    clock.advance(31)
    first.tick(reachable=False)
    clock.advance(31)
    first.tick(reachable=False)
    assert first.attempts == 2
    assert state.exists()

    balloons: list[str] = []
    second = _supervisor(tmp_path, clock, FakeLauncher(ok=False, error="nope"),
                         notify=lambda msg, title="": balloons.append(msg))
    assert second.attempts == 2
    assert second.incident_open
    clock.advance(61)
    second.tick(reachable=False)
    assert second.attempts == 3
    assert balloons == ["Sync engine will not start: nope"]


def test_the_state_file_is_removed_once_it_is_answering_again(tmp_path):
    clock = FakeClock()
    state = tmp_path / "state" / sup.STATE_FILENAME
    s = _supervisor(tmp_path, clock, FakeLauncher(ok=False, error="nope"))

    s.tick(reachable=False)
    clock.advance(31)
    s.tick(reachable=False)
    assert json.loads(state.read_text(encoding="utf-8"))["attempts"] == 1

    s.tick(reachable=True)
    assert not state.exists()
    assert s.attempts == 0
    assert s.lane_error() is None


def test_the_report_section_is_empty_while_the_engine_is_up(tmp_path):
    clock = FakeClock()
    s = _supervisor(tmp_path, clock, FakeLauncher(ok=False, error="nope"))
    assert s.report() == {}

    s.tick(reachable=False)
    clock.advance(31)
    s.tick(reachable=False)
    report = s.report()
    assert report["attempts"] == 1
    assert report["last_error"] == "nope"
    assert report["down_since"]
    assert report["supervising"] is True


def test_a_corrupt_state_file_reads_as_no_incident(tmp_path):
    state = tmp_path / "state" / sup.STATE_FILENAME
    state.parent.mkdir(parents=True)
    state.write_text("{not json", encoding="utf-8")
    s = _supervisor(tmp_path, FakeClock(), FakeLauncher())
    assert not s.incident_open
    assert s.attempts == 0


# -- the launcher seam ------------------------------------------------------


class SpawnRecorder:
    def __init__(self, returncode: int = 0, stderr: bytes = b"") -> None:
        self.calls: list[tuple[tuple, dict]] = []
        self.returncode = returncode
        self.stderr = stderr

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self

    # the Popen shape _launch_capturing uses
    def communicate(self, timeout=None):
        return b"", self.stderr

    def kill(self):
        pass


def test_windows_runs_the_run_key_shim_detached(tmp_path):
    """The detach is the whole point: a Syncthing started as an ordinary
    child of the companion dies with the tray -- and with its self-upgrade --
    which would make this module a slower route to the same eighteen hours."""
    vbs = tmp_path / "CCSyncSyncthing.vbs"
    vbs.write_text("' shim", encoding="utf-8")
    rec = SpawnRecorder()
    launcher = SyncthingLauncher(spawn=rec, system="win32", launcher_path=vbs)

    assert launcher.available()
    assert launcher.command() == ["wscript.exe", "//B", "//Nologo", str(vbs)]
    assert launcher.launch() == (True, "")

    (argv,), kwargs = rec.calls[0]
    assert argv == ["wscript.exe", "//B", "//Nologo", str(vbs)]
    assert kwargs["creationflags"] == 0x00000008 | 0x00000200  # DETACHED | NEW_GROUP
    assert kwargs["close_fds"] is True
    assert kwargs["stdout"] == subprocess.DEVNULL
    assert kwargs["stderr"] == subprocess.DEVNULL
    assert "start_new_session" not in kwargs


def test_the_detached_flags_are_the_documented_windows_constants():
    assert sup.detached_creationflags() == 0x00000008 | 0x00000200


def test_macos_kickstarts_the_launch_agent(tmp_path):
    plist = tmp_path / "com.ccsync.syncthing.plist"
    plist.write_text("<plist/>", encoding="utf-8")
    rec = SpawnRecorder()
    launcher = SyncthingLauncher(
        spawn=rec, system="darwin", launcher_path=plist, uid_fn=lambda: 501)

    assert launcher.command() == [
        "launchctl", "kickstart", "-k", "gui/501/com.ccsync.syncthing"]
    assert launcher.launch() == (True, "")
    (argv,), kwargs = rec.calls[0]
    assert argv == ["launchctl", "kickstart", "-k", "gui/501/com.ccsync.syncthing"]
    assert kwargs["stderr"] == subprocess.PIPE
    # No Windows creation flags on POSIX -- passing one raises there.
    assert "creationflags" not in kwargs


def test_macos_reports_launchctls_last_stderr_line(tmp_path):
    plist = tmp_path / "com.ccsync.syncthing.plist"
    plist.write_text("<plist/>", encoding="utf-8")
    rec = SpawnRecorder(
        returncode=3,
        stderr=b"Boot-out failed: 3: No such process\nCould not find service\n")
    launcher = SyncthingLauncher(
        spawn=rec, system="darwin", launcher_path=plist, uid_fn=lambda: 501)

    ok, error = launcher.launch()
    assert ok is False
    assert error == "Could not find service"


def test_a_launcher_that_will_not_execute_is_an_error_not_an_exception(tmp_path):
    vbs = tmp_path / "CCSyncSyncthing.vbs"
    vbs.write_text("' shim", encoding="utf-8")

    def _raise(*_a, **_k):
        raise FileNotFoundError("wscript.exe")

    launcher = SyncthingLauncher(spawn=_raise, system="win32", launcher_path=vbs)
    ok, error = launcher.launch()
    assert ok is False
    assert "FileNotFoundError" in error


def test_an_absent_shim_is_reported_and_never_launched(tmp_path):
    rec = SpawnRecorder()
    launcher = SyncthingLauncher(
        spawn=rec, system="win32", launcher_path=tmp_path / "gone.vbs")
    assert launcher.available() is False
    assert "re-run the CC Sync installer" in launcher.missing_reason()
    assert rec.calls == []


def test_the_windows_shim_is_looked_for_beside_the_companion(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert sup.windows_launcher_path() == (
        Path(tmp_path) / "ccsync" / "bin" / "CCSyncSyncthing.vbs")


def test_last_line_takes_the_last_non_blank_line_bounded():
    assert sup.last_line("a\nb\n\n") == "b"
    assert sup.last_line(b"x\r\nCould not find service\r\n".decode()) == (
        "Could not find service")
    assert sup.last_line("") == ""
    assert len(sup.last_line("z" * 500)) == 200


def test_a_clock_that_steps_backwards_does_not_stop_supervision(tmp_path):
    """Every "has it been 30 s yet" here is a subtraction, so a timestamp in
    the future makes all of them false -- and an NTP step of an hour would
    park the supervisor for an hour."""
    clock = FakeClock()
    launcher = FakeLauncher()
    s = _supervisor(tmp_path, clock, launcher, probe=None)

    s.tick(reachable=False)
    clock.advance(-3600)             # the clock is corrected backwards
    s.tick(reachable=False)
    assert launcher.launches == 0    # re-based, so the grace window restarts

    clock.advance(31)
    s.tick(reachable=False)
    assert launcher.launches == 1
