"""Relaunch the companion after a death nobody asked for (CR-93's safety net).

WHY A SEPARATE PROCESS. A native abort -- Tcl_Panic, an access violation, a
fail-fast -- takes every thread of the process with it in the same
instruction: no `finally`, no atexit, no watchdog thread, nothing of ours
runs again. The Windows Run key fires at logon and never again, so a
companion that aborts at 22:40 stays dead until somebody notices the tray
icon is missing (47 minutes on 2026-08-30; three hours the same morning).
The only thing that can bring it back is something OUTSIDE the process, and
the lightest such thing is another copy of the exe that does nothing but wait
on the companion's process handle.

HOW IT DECIDES. The companion spawns `ccsync-companion.exe --supervise <pid>`
right after it has taken the single-instance slot and written its run marker
(crash_report.install_native). The supervisor waits for that pid to exit and
then asks two questions:

  1. Is the run marker still there, and does it still name that pid?
     crash_report.mark_clean_exit() deletes the marker at the top of
     shutdown() -- the moment the companion DECIDES to stop. So a Quit from
     the tray, a self-upgrade hand-off (the new build writes its OWN marker
     with its own pid), a fleet halt, a crash-loop revert: all read as "no
     marker for that pid" and the supervisor stands down. Only a death that
     never reached shutdown() leaves the marker behind.
  2. Was the exit code one a person or a tool hands out on purpose?
     0 (exited), 1 (a Python-level failure, or Task Manager's End task),
     0xFFFFFFFF (PowerShell Stop-Process / .Kill()) and 0xC000013A (a console
     closed on it) are DELIBERATE_EXIT_CODES and are respected: the
     installer's `Get-Process ccsync-companion | Stop-Process -Force` must
     not be fought (it kills this supervisor too, since it shares the image
     name -- which is the other half of that guarantee), and a build that
     cannot even construct itself must not be relaunched into the same
     failure. Everything else with the marker still present -- abort() is 3
     or 0x80000003, an access violation 0xC0000005 -- is a crash.

It then waits RELAUNCH_DELAY_SECONDS (WER is still writing the dump; the
single-instance mutex is released the instant the process dies), re-reads the
marker in case a person got there first, records the relaunch, and starts
the exe exactly the way the self-upgrade does (detached, no window, a clean
environment, its own PyInstaller extraction). The relaunched companion takes
the slot, finds the old marker, writes the UncleanExit crash report it always
would have, and now ALSO finds the supervisor's note (RELAUNCH_NOTE_FILENAME)
and says in the log and the report that it was brought back and why. Then
it spawns a fresh supervisor for itself, so the chain continues.

NEVER A LOOP. Three relaunches inside an hour is a build that cannot stay
up, and relaunching it a fourth time is what the first three were: the
supervisor stands down and says so in its log, leaving the logon Run key and
the admin to it. The companion's own start counter (upgrade.note_version_start,
APP-5) is the other half: a build that dies within minutes of starting a few
times in a row reverts itself to the previous build, and THAT is a clean exit
this supervisor does not touch. A relaunch always goes through the
single-instance guard, so a companion already started by hand makes the
relaunched copy exit 0 with "already running" -- there is never a second
tray.

STDLIB ONLY, and imported by launcher.py BEFORE the app package: the
supervisor process is a 50 MB frozen exe already; it must not also import
the companion, its config, its logging or tkinter. Everything it needs comes
in on the command line.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

FLAG = "--supervise"
# Written by the supervisor into the crash directory just before it relaunches;
# read (and removed) by crash_report.install_native on the relaunched
# companion's start, so the relaunch reaches the log and the crash report.
RELAUNCH_NOTE_FILENAME = "relaunched.json"
# Relaunch timestamps, in the state directory, so a crash loop is recognised
# across supervisor processes (each one lives for exactly one companion).
HISTORY_FILENAME = "supervisor.json"
# The supervisor's own log, beside the crash reports. Small and self-capping.
LOG_FILENAME = "supervisor.log"
LOG_MAX_BYTES = 256_000

RELAUNCH_DELAY_SECONDS = 10.0
MAX_RELAUNCHES = 3
RELAUNCH_WINDOW_SECONDS = 3600.0
# Exit codes that mean somebody, or something of ours, MEANT it. See the
# module docstring; 0xC000013A is STATUS_CONTROL_C_EXIT.
DELIBERATE_EXIT_CODES = frozenset({0, 1, 0xFFFFFFFF, 0xC000013A})
# Environment: set to anything to keep a companion from spawning a supervisor
# (a developer's source run never does; this is for a frozen build under test).
DISABLE_ENV = "CCSYNC_NO_SUPERVISOR"
# The same three keys upgrade._default_spawn strips: a frozen parent's
# PyInstaller extraction dir and the PYTHONHOME resolve_bridge pins at it,
# both of which vanish with the parent (AUDIT_2 CORE-M6).
_STRIPPED_ENV_PREFIXES = ("_PYI", "_MEI")
_STRIPPED_ENV_KEYS = ("PYTHONHOME", "PYTHON3HOME")

_STILL_ACTIVE = 259
_INFINITE = 0xFFFFFFFF
_SYNCHRONIZE = 0x00100000
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


@dataclass(frozen=True)
class Decision:
    relaunch: bool
    reason: str


def decide(exit_code: Optional[int], marker: Optional[dict[str, Any]],
           supervised_pid: int, history: list[float], now: float,
           exe_exists: bool = True) -> Decision:
    """Pure: should the supervised companion be relaunched?

    `exit_code` None means the process could not be waited on (it was gone
    before the supervisor opened it); with the marker still naming it, that
    is a death too.
    """
    if marker is None:
        return Decision(False, "the companion began a shutdown (no run marker): a "
                               "deliberate exit")
    try:
        marker_pid = int(marker.get("pid", -1))
    except (TypeError, ValueError):
        marker_pid = -1
    if marker_pid != supervised_pid:
        return Decision(False, f"the run marker names pid {marker_pid}, not {supervised_pid}: "
                               "this companion was replaced (self-upgrade or a start by hand)")
    if exit_code is not None and exit_code in DELIBERATE_EXIT_CODES:
        return Decision(False, f"exit code {_fmt_code(exit_code)} is a deliberate stop "
                               "(a Quit, Stop-Process, End task, or a startup failure); "
                               "not fighting it")
    if not exe_exists:
        return Decision(False, "the companion exe is no longer on disk: nothing to relaunch")
    recent = [t for t in history if 0 <= now - t <= RELAUNCH_WINDOW_SECONDS]
    if len(recent) >= MAX_RELAUNCHES:
        return Decision(False, f"already relaunched {len(recent)} times in the last "
                               f"{RELAUNCH_WINDOW_SECONDS / 60:.0f} minutes: this build "
                               "cannot stay up, leaving it to the logon autostart and the admin")
    return Decision(True, f"pid {supervised_pid} died with exit code {_fmt_code(exit_code)} "
                          "without starting a shutdown (relaunch "
                          f"{len(recent) + 1} of {MAX_RELAUNCHES} this hour)")


def _fmt_code(code: Optional[int]) -> str:
    if code is None:
        return "unknown"
    return f"{code} (0x{code & 0xFFFFFFFF:08X})" if code > 255 or code < 0 else str(code)


# -- files ------------------------------------------------------------------


def read_marker(crash_dir: Path) -> Optional[dict[str, Any]]:
    # The file name is crash_report.RUN_MARKER_FILENAME; spelled here so the
    # supervisor does not import that module (see the docstring).
    try:
        data = json.loads((crash_dir / "running.marker").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - absent, empty or half-written: no marker
        return None
    return data if isinstance(data, dict) else None


def read_history(state_dir: Path) -> list[float]:
    try:
        data = json.loads((state_dir / HISTORY_FILENAME).read_text(encoding="utf-8"))
        return [float(t) for t in data.get("relaunches", [])]
    except Exception:  # noqa: BLE001
        return []


def write_history(state_dir: Path, times: list[float]) -> None:
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / HISTORY_FILENAME).write_text(
            json.dumps({"relaunches": times[-20:]}), encoding="utf-8")
    except Exception:  # noqa: BLE001 - a history that cannot be written is not a reason to stop
        pass


def write_relaunch_note(crash_dir: Path, note: dict[str, Any]) -> None:
    try:
        crash_dir.mkdir(parents=True, exist_ok=True)
        (crash_dir / RELAUNCH_NOTE_FILENAME).write_text(json.dumps(note), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def read_relaunch_note(crash_dir: Path, remove: bool = True) -> Optional[dict[str, Any]]:
    path = crash_dir / RELAUNCH_NOTE_FILENAME
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    if remove:
        try:
            path.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass
    return data if isinstance(data, dict) else None


class _Log:
    """Append-only, timestamped, self-capping. The companion's logging is not
    available here and must not be imported."""

    def __init__(self, crash_dir: Path) -> None:
        self.path = crash_dir / LOG_FILENAME

    def __call__(self, message: str) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            try:
                if self.path.is_file() and self.path.stat().st_size > LOG_MAX_BYTES:
                    self.path.unlink(missing_ok=True)
            except Exception:  # noqa: BLE001
                pass
            stamp = time.strftime("%Y-%m-%d %H:%M:%S")
            with open(self.path, "a", encoding="utf-8", errors="replace") as handle:
                handle.write(f"{stamp} supervisor[{os.getpid()}]: {message}\n")
        except Exception:  # noqa: BLE001
            pass


# -- process plumbing --------------------------------------------------------


def wait_for_exit_win32(pid: int) -> Optional[int]:
    """Block until `pid` exits; return its exit code, or None if it could not
    be opened (already gone, or not ours)."""
    import ctypes  # noqa: PLC0415
    from ctypes import wintypes  # noqa: PLC0415

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = kernel32.OpenProcess(_SYNCHRONIZE | _PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        kernel32.WaitForSingleObject(handle, _INFINITE)
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return None
        if code.value == _STILL_ACTIVE:
            return None
        return int(code.value)
    finally:
        kernel32.CloseHandle(handle)


def pid_is_alive_win32(pid: int) -> bool:
    import ctypes  # noqa: PLC0415
    from ctypes import wintypes  # noqa: PLC0415

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ctypes.get_last_error() == 5  # access denied: exists, not ours
    try:
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return True
        return code.value == _STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def child_env(base: Optional[dict[str, str]] = None) -> dict[str, str]:
    """The environment a fresh, independent companion (or supervisor) gets."""
    env = {
        k: v for k, v in (os.environ if base is None else base).items()
        if not k.startswith(_STRIPPED_ENV_PREFIXES) and k not in _STRIPPED_ENV_KEYS
    }
    # Without this, PyInstaller >= 6 has the child REUSE the parent's _MEI
    # dir, which the parent's bootloader deletes on exit (upgrade.py, 2026-07-25).
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return env


def _detached_popen(argv: list[str], cwd: Path, env: dict[str, str]) -> Any:
    detach: dict[str, Any] = {}
    if sys.platform == "win32":
        detach["creationflags"] = (
            subprocess.DETACHED_PROCESS
            | subprocess.CREATE_NEW_PROCESS_GROUP
            | subprocess.CREATE_NO_WINDOW
        )
    else:
        detach["start_new_session"] = True
    return subprocess.Popen(
        argv, cwd=str(cwd), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, close_fds=True, env=env, **detach,
    )


def supervisor_argv(exe: Path, pid: int, crash_dir: Path, state_dir: Path) -> list[str]:
    return [str(exe), FLAG, str(pid), "--exe", str(exe),
            "--crash-dir", str(crash_dir), "--state-dir", str(state_dir)]


def spawn_for(pid: int, exe: Path, crash_dir: Path, state_dir: Path, *,
              frozen: Optional[bool] = None, platform: Optional[str] = None,
              enabled: bool = True, environ: Optional[dict[str, str]] = None,
              spawn: Optional[Callable[..., Any]] = None) -> Optional[Any]:
    """Companion side: start a supervisor for `pid`. Returns the Popen, or
    None with the reason logged by the caller: frozen win32 builds only, and a
    source run has nothing to relaunch.

    macOS is NOT covered, and the docstring used to claim launchd covered it
    (bug-hunt-2026-09-03 comp-core-2). It does not: the companion LaunchAgent
    `installer/macos_bootstrap.sh` writes is RunAtLoad with, deliberately and
    with a comment saying so, no KeepAlive -- and the installer rewrites any
    plist that HAS one. So a Mac companion that aborts (the CR-93 shape) stays
    dead until the next logon, and crash_report.start_supervisor says so at
    WARNING there. Porting this is not mechanical: decide() is
    platform-neutral, but DELIBERATE_EXIT_CODES and the 0xFFFFFFFF
    Stop-Process test are Windows semantics and need POSIX equivalents."""
    environ = os.environ if environ is None else environ
    if not enabled or environ.get(DISABLE_ENV):
        return None
    if not (sys.platform if platform is None else platform) == "win32":
        return None
    if not (bool(getattr(sys, "frozen", False)) if frozen is None else frozen):
        return None
    if not exe.is_file():
        return None
    run = spawn or _detached_popen
    return run(supervisor_argv(exe, pid, crash_dir, state_dir), exe.parent, child_env(environ))


# -- the supervisor process --------------------------------------------------


def _parse(argv: list[str]) -> dict[str, Any]:
    args: dict[str, Any] = {"pid": None, "exe": None, "crash_dir": None, "state_dir": None}
    usage = f"usage: {FLAG} <pid> --exe <path> --crash-dir <dir> [--state-dir <dir>]"
    it = iter(argv)
    try:
        for item in it:
            if item == FLAG:
                args["pid"] = int(next(it))
            elif item == "--exe":
                args["exe"] = Path(next(it))
            elif item == "--crash-dir":
                args["crash_dir"] = Path(next(it))
            elif item == "--state-dir":
                args["state_dir"] = Path(next(it))
    except (StopIteration, ValueError):
        raise SystemExit(usage) from None
    if args["pid"] is None or args["exe"] is None or args["crash_dir"] is None:
        raise SystemExit(usage)
    if args["state_dir"] is None:
        args["state_dir"] = args["crash_dir"].parent / "state"
    return args


def main(argv: list[str], *,
         waiter: Optional[Callable[[int], Optional[int]]] = None,
         pid_alive: Optional[Callable[[int], bool]] = None,
         spawn: Optional[Callable[..., Any]] = None,
         sleep_fn: Callable[[float], None] = time.sleep,
         clock: Callable[[], float] = time.time) -> int:
    """The supervisor process. Waits for one companion, relaunches it at most
    once, exits. Every collaborator is injectable for the suite; the
    defaults are the Windows ones."""
    args = _parse(argv)
    pid: int = args["pid"]
    exe: Path = args["exe"]
    crash_dir: Path = args["crash_dir"]
    state_dir: Path = args["state_dir"]
    log = _Log(crash_dir)
    wait = waiter or wait_for_exit_win32
    alive = pid_alive or pid_is_alive_win32
    run = spawn or _detached_popen

    log(f"watching companion pid {pid} ({exe})")
    try:
        code = wait(pid)
    except Exception as exc:  # noqa: BLE001 - cannot wait: nothing to supervise
        log(f"could not wait on pid {pid}: {exc!r}; standing down")
        return 0
    marker = read_marker(crash_dir)
    history = read_history(state_dir)
    now = clock()
    decision = decide(code, marker, pid, history, now, exe_exists=exe.is_file())
    log(f"pid {pid} exited with code {_fmt_code(code)}: "
        f"{'RELAUNCHING' if decision.relaunch else 'standing down'} -- {decision.reason}")
    if not decision.relaunch:
        return 0

    sleep_fn(RELAUNCH_DELAY_SECONDS)
    # A person may have restarted it during the delay: a marker that now
    # names a different, living pid is a companion that needs no help. (The
    # single-instance guard would refuse ours anyway; this just says why.)
    marker = read_marker(crash_dir)
    try:
        newcomer = int((marker or {}).get("pid", -1))
    except (TypeError, ValueError):
        newcomer = -1
    if newcomer not in (-1, pid):
        try:
            if alive(newcomer):
                log(f"a companion (pid {newcomer}) started while waiting; standing down")
                return 0
        except Exception:  # noqa: BLE001 - cannot tell: relaunch, the guard sorts it out
            pass

    when = clock()
    note = {
        "when": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(when)),
        "previous_pid": pid,
        "exit_code": code,
        "reason": decision.reason,
        "attempt": len([t for t in history if 0 <= when - t <= RELAUNCH_WINDOW_SECONDS]) + 1,
        "supervisor_pid": os.getpid(),
    }
    write_history(state_dir, history + [when])
    write_relaunch_note(crash_dir, note)
    try:
        child = run([str(exe)], exe.parent, child_env())
    except Exception as exc:  # noqa: BLE001
        log(f"relaunch FAILED: {exc!r}")
        return 1
    log(f"relaunched {exe} as pid {getattr(child, 'pid', '?')}")
    return 0
