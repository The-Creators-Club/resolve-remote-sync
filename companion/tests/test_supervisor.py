"""The relaunch-on-abort supervisor (CR-93's safety net, 2026-08-30).

Nothing here waits on a real process or spawns a real exe: the waiter, the
liveness probe, the spawn, the clock and the sleep are all injected. What is
pinned is the VERDICT -- when a dead companion is brought back and when it is
left alone -- and the two files that carry it to the next start.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from ccsync_companion import supervisor

PID = 4242
NOW = 1_800_000_000.0


def _marker(pid: int = PID) -> dict:
    return {"pid": pid, "version": "0.9.62", "started": "2026-08-30T13:50:57+00:00"}


# -- decide(): the verdict ----------------------------------------------------


def test_an_abort_with_the_marker_left_behind_is_relaunched():
    verdict = supervisor.decide(3, _marker(), PID, [], NOW)
    assert verdict.relaunch is True
    assert "without starting a shutdown" in verdict.reason


@pytest.mark.parametrize("code", [0x80000003, 0xC0000005, 0xC00000FD, 0xC0000409, 2, 137])
def test_every_native_death_code_is_a_crash(code):
    assert supervisor.decide(code, _marker(), PID, [], NOW).relaunch is True


def test_a_process_that_could_not_be_waited_on_but_left_its_marker_is_a_crash():
    """The companion died between spawning the supervisor and the supervisor
    opening its handle: exit code unknown, marker present, still a death."""
    assert supervisor.decide(None, _marker(), PID, [], NOW).relaunch is True


def test_no_marker_means_the_companion_meant_to_stop():
    """shutdown() deletes the marker first thing -- a Quit, a fleet halt, a
    crash-loop revert, the self-upgrade: none of them may be fought."""
    verdict = supervisor.decide(3, None, PID, [], NOW)
    assert verdict.relaunch is False
    assert "deliberate" in verdict.reason


def test_a_marker_naming_another_pid_is_a_replacement_not_a_death():
    """A self-upgrade's newcomer wrote its own marker before the old build
    exited; a person may also have started one by hand."""
    verdict = supervisor.decide(3, _marker(pid=PID + 1), PID, [], NOW)
    assert verdict.relaunch is False
    assert "replaced" in verdict.reason


@pytest.mark.parametrize("code", sorted(supervisor.DELIBERATE_EXIT_CODES))
def test_deliberate_exit_codes_are_respected_even_with_the_marker(code):
    """Stop-Process (-1), End task (1), a console closed (0xC000013A) and a
    plain exit 0 are people and tools; a build whose constructor raised
    (Python exits 1, before shutdown() could clear the marker) must not be
    relaunched into the same failure."""
    verdict = supervisor.decide(code, _marker(), PID, [], NOW)
    assert verdict.relaunch is False
    assert "deliberate" in verdict.reason


def test_a_missing_exe_is_nothing_to_relaunch():
    assert supervisor.decide(3, _marker(), PID, [], NOW, exe_exists=False).relaunch is False


def test_three_relaunches_in_an_hour_is_a_build_that_cannot_stay_up():
    recent = [NOW - 300, NOW - 1200, NOW - 2400]
    verdict = supervisor.decide(3, _marker(), PID, recent, NOW)
    assert verdict.relaunch is False
    assert "cannot stay up" in verdict.reason
    # ...but relaunches older than the window no longer count.
    old = [NOW - 4000, NOW - 5000, NOW - 6000]
    assert supervisor.decide(3, _marker(), PID, old, NOW).relaunch is True
    # Two inside the window: the third is still allowed, and says which it is.
    two = [NOW - 300, NOW - 1200]
    verdict = supervisor.decide(3, _marker(), PID, two, NOW)
    assert verdict.relaunch is True
    assert "relaunch 3 of 3" in verdict.reason


def test_a_garbage_marker_pid_is_not_ours():
    assert supervisor.decide(3, {"pid": "??"}, PID, [], NOW).relaunch is False


# -- main(): one supervised life ---------------------------------------------


class _Spawn:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], Path, dict[str, str]]] = []

    def __call__(self, argv, cwd, env):
        self.calls.append((list(argv), Path(cwd), dict(env)))

        class _Child:
            pid = 777

        return _Child()


def _dirs(tmp_path: Path) -> tuple[Path, Path, Path]:
    crash = tmp_path / "crashes"
    state = tmp_path / "state"
    exe = tmp_path / "bin" / "ccsync-companion.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"MZ")
    crash.mkdir()
    return crash, state, exe


def _argv(pid: int, exe: Path, crash: Path, state: Path) -> list[str]:
    return supervisor.supervisor_argv(exe, pid, crash, state)[1:]


def test_main_relaunches_a_crashed_companion_and_records_it(tmp_path, monkeypatch):
    crash, state, exe = _dirs(tmp_path)
    (crash / "running.marker").write_text(json.dumps(_marker()), encoding="utf-8")
    spawn = _Spawn()
    slept: list[float] = []
    monkeypatch.setenv("PYTHONHOME", r"C:\Temp\_MEI1234")   # the dead parent's
    monkeypatch.setenv("_MEIPASS2", r"C:\Temp\_MEI1234")

    code = supervisor.main(
        _argv(PID, exe, crash, state),
        waiter=lambda pid: 0x80000003 if pid == PID else None,
        pid_alive=lambda pid: False,
        spawn=spawn, sleep_fn=slept.append, clock=lambda: NOW)

    assert code == 0
    assert slept == [supervisor.RELAUNCH_DELAY_SECONDS]
    assert len(spawn.calls) == 1
    argv, cwd, env = spawn.calls[0]
    assert argv == [str(exe)] and cwd == exe.parent
    # The relaunched companion gets a CLEAN environment: a frozen parent's
    # extraction dir and the PYTHONHOME pinned at it vanish with the parent.
    assert "PYTHONHOME" not in env and "_MEIPASS2" not in env
    assert env["PYINSTALLER_RESET_ENVIRONMENT"] == "1"
    # The note the relaunched companion reads on its next start...
    note = json.loads((crash / supervisor.RELAUNCH_NOTE_FILENAME).read_text(encoding="utf-8"))
    assert note["previous_pid"] == PID
    assert note["exit_code"] == 0x80000003
    assert note["attempt"] == 1
    assert "without starting a shutdown" in note["reason"]
    # ...the history the NEXT supervisor counts against...
    history = json.loads((state / supervisor.HISTORY_FILENAME).read_text(encoding="utf-8"))
    assert history["relaunches"] == [NOW]
    # ...and its own log, which says what it did and why.
    log_text = (crash / supervisor.LOG_FILENAME).read_text(encoding="utf-8")
    assert "RELAUNCHING" in log_text and f"relaunched {exe} as pid 777" in log_text


def test_main_stands_down_after_a_clean_exit(tmp_path):
    crash, state, exe = _dirs(tmp_path)
    # no marker: shutdown() removed it
    spawn = _Spawn()
    code = supervisor.main(_argv(PID, exe, crash, state), waiter=lambda pid: 0,
                           pid_alive=lambda pid: False, spawn=spawn,
                           sleep_fn=lambda s: None, clock=lambda: NOW)
    assert code == 0
    assert spawn.calls == []
    assert not (crash / supervisor.RELAUNCH_NOTE_FILENAME).exists()
    assert "standing down" in (crash / supervisor.LOG_FILENAME).read_text(encoding="utf-8")


def test_main_stands_down_when_a_person_got_there_first(tmp_path):
    """During the relaunch delay somebody double-clicked the exe: the marker
    now names a living pid that is not ours. The single-instance guard would
    refuse our copy anyway; the supervisor just does not try."""
    crash, state, exe = _dirs(tmp_path)
    (crash / "running.marker").write_text(json.dumps(_marker()), encoding="utf-8")
    spawn = _Spawn()

    def _sleep(_seconds):
        (crash / "running.marker").write_text(json.dumps(_marker(pid=PID + 7)),
                                              encoding="utf-8")

    code = supervisor.main(_argv(PID, exe, crash, state), waiter=lambda pid: 3,
                           pid_alive=lambda pid: pid == PID + 7, spawn=spawn,
                           sleep_fn=_sleep, clock=lambda: NOW)
    assert code == 0
    assert spawn.calls == []
    assert "started while waiting" in (crash / supervisor.LOG_FILENAME).read_text(encoding="utf-8")


def test_main_stops_relaunching_a_build_that_keeps_dying(tmp_path):
    crash, state, exe = _dirs(tmp_path)
    (crash / "running.marker").write_text(json.dumps(_marker()), encoding="utf-8")
    supervisor.write_history(state, [NOW - 100, NOW - 200, NOW - 300])
    spawn = _Spawn()
    code = supervisor.main(_argv(PID, exe, crash, state), waiter=lambda pid: 3,
                           pid_alive=lambda pid: False, spawn=spawn,
                           sleep_fn=lambda s: None, clock=lambda: NOW)
    assert code == 0
    assert spawn.calls == []
    assert "cannot stay up" in (crash / supervisor.LOG_FILENAME).read_text(encoding="utf-8")


def test_main_reports_a_failed_relaunch(tmp_path):
    crash, state, exe = _dirs(tmp_path)
    (crash / "running.marker").write_text(json.dumps(_marker()), encoding="utf-8")

    def _spawn(argv, cwd, env):
        raise OSError("access denied")

    code = supervisor.main(_argv(PID, exe, crash, state), waiter=lambda pid: 3,
                           pid_alive=lambda pid: False, spawn=_spawn,
                           sleep_fn=lambda s: None, clock=lambda: NOW)
    assert code == 1
    assert "relaunch FAILED" in (crash / supervisor.LOG_FILENAME).read_text(encoding="utf-8")


def test_main_needs_its_arguments():
    with pytest.raises(SystemExit):
        supervisor.main(["--supervise"])
    with pytest.raises(SystemExit):
        supervisor.main(["--exe", "x"])


# -- spawn_for(): the companion's side ---------------------------------------


def test_spawn_for_starts_a_detached_supervisor_with_a_clean_environment(tmp_path):
    crash, state, exe = _dirs(tmp_path)
    spawn = _Spawn()
    child = supervisor.spawn_for(
        PID, exe, crash, state, frozen=True, platform="win32", spawn=spawn,
        environ={"PATH": "x", "PYTHONHOME": "gone", "_MEIPASS2": "gone", "_PYI_APP": "gone"})
    assert child is not None
    argv, cwd, env = spawn.calls[0]
    assert argv == [str(exe), supervisor.FLAG, str(PID), "--exe", str(exe),
                    "--crash-dir", str(crash), "--state-dir", str(state)]
    assert cwd == exe.parent
    assert env == {"PATH": "x", "PYINSTALLER_RESET_ENVIRONMENT": "1"}


@pytest.mark.parametrize("frozen, platform, environ", [
    (False, "win32", {}),                       # a source run has nothing to relaunch
    (True, "linux", {}),
    (True, "win32", {supervisor.DISABLE_ENV: "1"}),
])
def test_spawn_for_declines_where_it_does_not_apply(tmp_path, frozen, platform, environ):
    crash, state, exe = _dirs(tmp_path)
    spawn = _Spawn()
    assert supervisor.spawn_for(PID, exe, crash, state, frozen=frozen, platform=platform,
                                spawn=spawn, environ=environ) is None
    assert spawn.calls == []


def test_spawn_for_declines_when_the_exe_is_gone(tmp_path):
    crash, state, exe = _dirs(tmp_path)
    exe.unlink()
    assert supervisor.spawn_for(PID, exe, crash, state, frozen=True, platform="win32",
                                spawn=_Spawn(), environ={}) is None


# -- the re-entry: `ccsync-companion --supervise` never loads the app ---------


def test_the_flag_is_handled_before_the_app_is_imported(tmp_path):
    """launcher.py and __main__.py branch on the flag first: a supervisor is a
    process that lives for hours doing nothing, and must not carry the
    companion, tkinter and the rest to do it. Run for real, in a child, on a
    pid that is already gone: the supervisor stands down and exits 0 without
    `ccsync_companion.app` ever having been imported."""
    crash = tmp_path / "crashes"
    exe = tmp_path / "ccsync-companion.exe"
    exe.write_bytes(b"MZ")
    src = Path(supervisor.__file__).resolve().parent.parent
    code = (
        "import sys, runpy\n"
        f"sys.argv = ['ccsync-companion', '--supervise', '999999999', '--exe', {str(exe)!r}, "
        f"'--crash-dir', {str(crash)!r}]\n"
        "try:\n"
        "    runpy.run_module('ccsync_companion', run_name='__main__', alter_sys=True)\n"
        "except SystemExit as exc:\n"
        "    assert exc.code == 0, exc.code\n"
        "assert 'ccsync_companion.app' not in sys.modules, 'the app was imported'\n"
        "print('stood down cleanly')\n"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(src) + os.pathsep + env.get("PYTHONPATH", "")
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                            timeout=60, env=env)
    assert result.returncode == 0, result.stderr[-2000:]
    assert "stood down cleanly" in result.stdout
    assert "standing down" in (crash / supervisor.LOG_FILENAME).read_text(encoding="utf-8")


# -- macOS (2026-09-26): the same supervisor, POSIX substitutes ---------------


def test_an_interpreter_exit_stamped_on_the_marker_is_deliberate():
    """A Mac supervisor never learns the exit code; crash_report's atexit
    hook stamps the marker instead. sys.exit and an uncaught error run
    atexit, an abort or a SIGKILL do not."""
    marker = dict(_marker(), **{supervisor.MARKER_EXITING_KEY: True})
    verdict = supervisor.decide(None, marker, PID, [], NOW)
    assert verdict.relaunch is False
    assert "deliberate" in verdict.reason
    # Unknown code, unstamped marker: the Mac shape of a crash.
    assert supervisor.decide(None, _marker(), PID, [], NOW).relaunch is True


def test_spawn_for_starts_one_on_a_mac_and_carries_the_launchd_label(tmp_path):
    crash, state, exe = _dirs(tmp_path)
    spawn = _Spawn()
    child = supervisor.spawn_for(
        PID, exe, crash, state, frozen=True, platform="darwin", spawn=spawn,
        environ={"PATH": "x", "XPC_SERVICE_NAME": "com.ccsync.companion"})
    assert child is not None
    argv = spawn.calls[0][0]
    assert argv[argv.index(supervisor.LAUNCHD_LABEL_FLAG) + 1] == "com.ccsync.companion"


@pytest.mark.parametrize("value", ["", "0", "com.x; rm -rf ~", "a" * 300])
def test_no_usable_launchd_label_means_no_label_flag(tmp_path, value):
    """Started from Terminal (no XPC_SERVICE_NAME, or "0"), or a value that
    is not a label: the supervisor falls back to starting the exe itself."""
    crash, state, exe = _dirs(tmp_path)
    spawn = _Spawn()
    supervisor.spawn_for(PID, exe, crash, state, frozen=True, platform="darwin",
                         spawn=spawn, environ={"XPC_SERVICE_NAME": value})
    assert supervisor.LAUNCHD_LABEL_FLAG not in spawn.calls[0][0]


def test_windows_never_carries_a_launchd_label(tmp_path):
    crash, state, exe = _dirs(tmp_path)
    spawn = _Spawn()
    supervisor.spawn_for(PID, exe, crash, state, frozen=True, platform="win32",
                         spawn=spawn, environ={"XPC_SERVICE_NAME": "com.ccsync.companion"})
    assert supervisor.LAUNCHD_LABEL_FLAG not in spawn.calls[0][0]


def _mac_argv(exe, crash, state, label="com.ccsync.companion"):
    return supervisor.supervisor_argv(exe, PID, crash, state, label=label)[1:]


def test_a_mac_relaunch_goes_back_through_launchd(tmp_path):
    """kickstart puts the new companion back under the LaunchAgent, so an
    installer's bootout still stops it; nothing is spawned directly."""
    crash, state, exe = _dirs(tmp_path)
    (crash / "running.marker").write_text(json.dumps(_marker()), encoding="utf-8")
    spawn, kicked = _Spawn(), []
    code = supervisor.main(
        _mac_argv(exe, crash, state), waiter=lambda pid: None,
        pid_alive=lambda pid: False, spawn=spawn, sleep_fn=lambda s: None,
        clock=lambda: NOW, kickstart=lambda label: kicked.append(label) or True,
        platform="darwin")
    assert code == 0
    assert kicked == ["com.ccsync.companion"] and spawn.calls == []
    assert "through launchd" in (crash / supervisor.LOG_FILENAME).read_text(encoding="utf-8")
    # The ceiling still counts it.
    assert json.loads((state / supervisor.HISTORY_FILENAME).read_text(
        encoding="utf-8"))["relaunches"] == [NOW]


def test_a_failed_kickstart_falls_back_to_starting_the_exe(tmp_path):
    crash, state, exe = _dirs(tmp_path)
    (crash / "running.marker").write_text(json.dumps(_marker()), encoding="utf-8")
    spawn = _Spawn()
    code = supervisor.main(
        _mac_argv(exe, crash, state), waiter=lambda pid: None,
        pid_alive=lambda pid: False, spawn=spawn, sleep_fn=lambda s: None,
        clock=lambda: NOW, kickstart=lambda label: False, platform="darwin")
    assert code == 0
    assert spawn.calls and spawn.calls[0][0] == [str(exe)]
    assert "kickstart com.ccsync.companion failed" in (
        crash / supervisor.LOG_FILENAME).read_text(encoding="utf-8")


def test_a_mac_quit_is_not_fought(tmp_path):
    """Quit / logout / bootout: SIGTERM -> shutdown() -> no marker."""
    crash, state, exe = _dirs(tmp_path)
    kicked: list[str] = []
    code = supervisor.main(
        _mac_argv(exe, crash, state), waiter=lambda pid: None,
        pid_alive=lambda pid: False, spawn=_Spawn(), sleep_fn=lambda s: None,
        clock=lambda: NOW, kickstart=lambda label: kicked.append(label) or True,
        platform="darwin")
    assert code == 0 and kicked == []


def test_the_label_on_argv_is_checked_again(tmp_path):
    crash, state, exe = _dirs(tmp_path)
    argv = _mac_argv(exe, crash, state, label=None) + [supervisor.LAUNCHD_LABEL_FLAG, "a b"]
    assert supervisor._parse(argv)["label"] is None


def test_kickstart_builds_the_gui_domain_target():
    if not hasattr(os, "getuid"):
        pytest.skip("POSIX only")
    calls = []

    class _R:
        returncode = 0

    assert supervisor.kickstart_launchd(
        "com.ccsync.companion", run=lambda argv, **kw: calls.append(argv) or _R()) is True
    assert calls[0] == ["/bin/launchctl", "kickstart", f"gui/{os.getuid()}/com.ccsync.companion"]


@pytest.mark.skipif(not hasattr(__import__("select"), "kqueue"), reason="kqueue is BSD/macOS")
def test_kqueue_wait_returns_when_a_real_process_exits():
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(0.5)"])
    try:
        assert supervisor.wait_for_exit_kqueue(child.pid) is None
    finally:
        child.wait(timeout=10)
    # Already gone: ESRCH, not a hang.
    assert supervisor.wait_for_exit_kqueue(child.pid) is None


@pytest.mark.skipif(sys.platform == "win32", reason="os.kill(pid, 0) is a POSIX probe")
def test_posix_liveness_probe():
    assert supervisor.pid_is_alive_posix(os.getpid()) is True
    assert supervisor.pid_is_alive_posix(0) is False
