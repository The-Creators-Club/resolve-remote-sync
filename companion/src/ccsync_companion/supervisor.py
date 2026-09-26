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

ON macOS (2026-09-26, the owner: "it should be able to auto start after a
crash"). The same process, with three POSIX substitutes for the Windows
parts. WAITING is a kqueue EVFILT_PROC/NOTE_EXIT on the pid, but macOS hands
an exit status only to a PARENT and the supervisor is the companion's child,
so the exit code is always unknown there. The DELIBERATE-EXIT test therefore
moves into the marker: crash_report registers an atexit hook that stamps
`"exiting": true` on it, and atexit runs on every interpreter exit (sys.exit,
an uncaught exception, the "Python-level failure" that is exit code 1 on
Windows) and on none of the deaths this exists for (SIGABRT from Tcl_Panic,
SIGSEGV, SIGKILL from jetsam or the kernel's code-signing check). A Quit,
logout and `launchctl bootout` (SIGTERM, which shutdown_guard turns into
shutdown()) already delete the marker. RELAUNCHING goes through launchd when
the companion was started by its LaunchAgent (XPC_SERVICE_NAME, carried on
argv as LAUNCHD_LABEL_FLAG): `launchctl kickstart` puts the new companion
back under the job, so an installer's bootout still stops it. A direct spawn
is the fallback when that fails. What a Mac cannot tell apart: a Force Quit
from Activity Monitor is SIGKILL and reads as a crash, so it is relaunched
(bounded by the same three an hour); the tray's Quit is the way to stop it.
A `pkill -f` on the exe path matches the supervisor too, which is the
Stop-Process guarantee again. What this does NOT cover: a build that dies
before it spawns a supervisor (the 2026-09-26 OS_REASON_CODESIGNING kill of
a binary copied over in place) -- there is no process yet to watch it.

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
# macOS: the LaunchAgent label the companion was started under (its
# XPC_SERVICE_NAME), so a relaunch can go back through launchd. Omitted when
# there is none; a supervisor one release older never sees it.
LAUNCHD_LABEL_FLAG = "--launchd-label"
# Where a supervisor runs. Linux has no frozen build and no tray.
SUPPORTED_PLATFORMS = ("win32", "darwin")
# The run-marker key crash_report's atexit hook sets on an interpreter exit.
# Spelled here and there (this module imports nothing of the companion's);
# the suite pins the two spellings equal.
MARKER_EXITING_KEY = "exiting"
# Written by the supervisor into the crash directory just before it relaunches;
# read (and removed) by crash_report.install_native on the relaunched
# companion's start, so the relaunch reaches the log and the crash report.
RELAUNCH_NOTE_FILENAME = "relaunched.json"
# Relaunch timestamps, in the state directory, so a crash loop is recognised
# across supervisor processes (each one lives for exactly one companion).
HISTORY_FILENAME = "supervisor.json"
# How many relaunch stamps are kept, in the file and on the child's argv.
HISTORY_MAX_ENTRIES = 20
# comp-ui-2 (2026-09-11): the flag that carries the relaunch history to the
# NEXT supervisor in the chain, through the companion, so the ceiling does not
# depend on a file that may not be writable. Comma-separated epoch seconds.
PRIOR_FLAG = "--prior"
# res-companion-3 (2026-09-11b): upgrade._OLD_SUFFIX, spelled here rather
# than imported. This module deliberately imports nothing from the companion
# package (see the docstring): it runs in a process whose whole job is to
# outlive one that could not start, and an import of upgrade.py would drag
# config, logging and the release keys in with it. The two spellings must
# stay in step; both are covered by the regression test.
_UPGRADE_OLD_SUFFIX = ".old"
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
    if marker.get(MARKER_EXITING_KEY):
        # macOS's only view of a deliberate exit (no exit status for a
        # non-parent); on Windows the same exits are already codes 0/1.
        return Decision(False, "the companion's interpreter exited normally (sys.exit, "
                               "an uncaught error or a startup failure): a deliberate "
                               "stop, not a crash; not fighting it")
    if exit_code is not None and exit_code in DELIBERATE_EXIT_CODES:
        return Decision(False, f"exit code {_fmt_code(exit_code)} is a deliberate stop "
                               "(a Quit, Stop-Process, End task, or a startup failure); "
                               "not fighting it")
    if not exe_exists:
        return Decision(False, "the companion exe is no longer on disk: nothing to relaunch")
    # comp-ui-2 / res-companion-4 (2026-09-11): the window test used to be
    # `0 <= now - t`, i.e. a stamp in the FUTURE did not count. `clock` is the
    # wall clock, so an NTP correction or a resume that steps it backwards
    # forgave every relaunch this build had just made and the ceiling started
    # again from zero -- on a codebase that treats clock skew as a first-class
    # fault. abs() is symmetric: a stamp we cannot place is still a relaunch.
    recent = [t for t in history if abs(now - t) <= RELAUNCH_WINDOW_SECONDS]
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
    """Every relaunch stamp the file holds, newest last.

    comp-app-5 (2026-09-18): ONE unparseable entry used to cost the whole
    history. The comprehension sat inside the try that answers `[]`, while
    `merge_history` -- written in the same pass, for the same data -- skips a
    bad item and keeps the rest. Two readers of one list disagreeing is how a
    machine that has already been relaunched three times starts its ceiling
    again from zero.
    """
    try:
        data = json.loads((state_dir / HISTORY_FILENAME).read_text(encoding="utf-8"))
        raw = data.get("relaunches", [])
    except Exception:  # noqa: BLE001
        return []
    out: list[float] = []
    for item in raw or []:
        try:
            out.append(float(item))
        except (TypeError, ValueError):
            continue
    return out


def write_history(state_dir: Path, times: list[float]) -> bool:
    """-> whether it was written.

    comp-ui-2 / res-companion-4 (2026-09-11): this used to return None and
    swallow every failure, and `decide`'s ceiling was computed ONLY from what
    `read_history` could read back. A state directory that cannot be written
    (an AV lock on this one file, an ACL, `supervisor.json` existing as a
    directory) therefore handed every supervisor in the chain an empty
    history, and a build that could not stay up was relaunched for ever. The
    caller now says so in its log, and `merge_history` gives the ceiling a
    second source that does not need a filesystem at all.

    comp-app-2 (2026-09-18): tmp+replace, the same as `write_relaunch_note`
    eleven lines below and for the reason its own docstring gives - "a kill
    mid-write cannot leave half a note behind either". This is the source
    `decide` reads on a cold chain, written by the one process that exists
    BECAUSE machines die abruptly: a power cut inside the write left
    truncated JSON, `read_history` answered `[]`, and a build that could not
    stay up was relaunched three more times an hour with nothing anywhere
    saying the ceiling had been lost.
    """
    path = state_dir / HISTORY_FILENAME
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        tmp.write_text(
            json.dumps({"relaunches": times[-HISTORY_MAX_ENTRIES:]}), encoding="utf-8")
        os.replace(tmp, path)
        return True
    except Exception:  # noqa: BLE001 - a history that cannot be written is not a reason to stop
        try:
            tmp.unlink()
        except Exception:  # noqa: BLE001
            pass
        return False


def merge_history(*sources: Optional[list[float]]) -> list[float]:
    """The union of every relaunch history we have, newest last, bounded.

    comp-ui-2: the chain is supervisor -> companion -> supervisor, and the
    file is only one of the two ways a count can travel along it; the other
    is the relaunch note the companion hands back on argv (`--prior`). The
    HIGHER count is the safe one here: a ceiling that under-counts relaunches
    a build that cannot stay up, and a ceiling that over-counts leaves a
    machine to its logon autostart, which is the failure a human notices.

    comp-ui-3 (2026-09-11b): the stamps are QUANTISED to milliseconds before
    the union, because the two sources spell the same relaunch differently -
    the file keeps `time.time()`'s full precision and `supervisor_argv`
    formats `%.3f`. They were two different floats, so every hop through the
    chain contributed a second entry per relaunch: `decide` reached
    MAX_RELAUNCHES after two relaunches, refused the third with "already
    relaunched 4 times", and the editor-facing "relaunch N of 3" in the
    unclean-exit report was off by the same factor. Milliseconds is finer
    than anything here measures, so the quantisation loses nothing.
    """
    seen: set[float] = set()
    for source in sources:
        for item in source or []:
            try:
                seen.add(round(float(item), 3))
            except (TypeError, ValueError):
                continue
    return sorted(seen)[-HISTORY_MAX_ENTRIES:]


def write_relaunch_note(crash_dir: Path, note: dict[str, Any]) -> bool:
    """-> whether it was written.

    regression-21 (2026-09-11b): `merge_history`'s docstring calls the argv
    copy "a source that does not need a filesystem at all", but the count
    only reaches the relaunched COMPANION through this file (crash_report
    reads it and passes it to the supervisor it spawns for itself). This
    used to return None, swallow every failure with a bare `pass` and write
    in place. So a `relaunched.json` that cannot be written -- an AV lock, or
    it exists as a directory -- while `<state>/supervisor.json` is also
    unwritable left `decide` an empty history for ever: a build that cannot
    stay up relaunched every ten seconds with nothing anywhere saying the
    ceiling had been lost. tmp+replace as everywhere else in the package, so
    a kill mid-write cannot leave half a note behind either.
    """
    path = crash_dir / RELAUNCH_NOTE_FILENAME
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        crash_dir.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(note), encoding="utf-8")
        os.replace(tmp, path)
        return True
    except Exception:  # noqa: BLE001 - the caller logs; a note is not a reason to stop
        try:
            tmp.unlink()
        except Exception:  # noqa: BLE001
            pass
        return False


def restore_interrupted_upgrade(exe: Path, log: Callable[[str], None]) -> bool:
    """Put `<exe>.old` back when the companion exe is MISSING. -> did it.

    res-companion-3 / regression-12 (2026-09-11b): a self-upgrade is two
    os.replace calls (`upgrade.py`: exe -> exe.old, then the download -> exe).
    Killed between them - a power cut, a reboot, an AV quarantine of the new
    binary - the machine is left with no `ccsync-companion.exe` at all. Every
    in-companion recovery lives inside a companion that cannot start, the Run
    key points at a name that is not there, and the supervisor, the one awake
    process outside it, used to log "the companion exe is no longer on disk:
    nothing to relaunch" and exit. The machine then synced nothing until a
    human renamed the file.

    Tightly guarded on purpose. It fills a HOLE and never overwrites: an
    `.old` beside a companion that IS on disk is the ordinary post-upgrade
    state (`upgrade.cleanup_old_exe` deletes it on the next start), and
    renaming over that would silently downgrade the machine. Loud in the
    supervisor log either way, because `installer/windows_upgrade.ps1` swaps
    the same two paths and a human may be mid-install.
    """
    old = Path(str(exe) + _UPGRADE_OLD_SUFFIX)
    try:
        if exe.exists():
            return False
        if not old.is_file() or old.stat().st_size <= 0:
            return False
    except OSError as exc:
        log(f"could not tell whether {exe} needs restoring: {exc!r}")
        return False
    try:
        os.replace(old, exe)
    except Exception as exc:  # noqa: BLE001
        log(f"an interrupted self-upgrade left no {exe.name} and {old.name} "
            f"could not be renamed back: {exc!r}. This machine needs a human.")
        return False
    log(f"an interrupted self-upgrade left no {exe.name}: renamed {old.name} "
        "back to it (the previous build) so there is something to relaunch")
    return True


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


def wait_for_exit_kqueue(pid: int, poll_seconds: float = 2.0) -> Optional[int]:
    """macOS: block until `pid` exits. Always returns None: the kernel gives
    an exit status only to the parent, and the companion is ours to watch,
    not ours to reap. decide() reads the run marker instead.

    A registration that fails for any reason other than "no such process"
    falls back to polling, so a supervisor never mistakes "could not watch"
    for "it died" and relaunches over a live companion."""
    import errno  # noqa: PLC0415
    import select  # noqa: PLC0415

    try:
        kq = select.kqueue()  # type: ignore[attr-defined]
        try:
            event = select.kevent(  # type: ignore[attr-defined]
                pid, filter=select.KQ_FILTER_PROC,  # type: ignore[attr-defined]
                flags=select.KQ_EV_ADD | select.KQ_EV_ONESHOT,  # type: ignore[attr-defined]
                fflags=select.KQ_NOTE_EXIT)  # type: ignore[attr-defined]
            kq.control([event], 0, 0)
            while True:
                if kq.control(None, 1, None):
                    return None
        finally:
            kq.close()
    except OSError as exc:
        if exc.errno == errno.ESRCH:
            return None
    except Exception:  # noqa: BLE001 - no kqueue here: poll instead
        pass
    while pid_is_alive_posix(pid):
        time.sleep(poll_seconds)
    return None


def pid_is_alive_posix(pid: int) -> bool:
    """Fail-safe: "cannot tell" (EPERM, anything odd) is alive."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except Exception:  # noqa: BLE001
        return True


def launchd_label(environ: Optional[dict[str, str]] = None) -> Optional[str]:
    """The LaunchAgent label this process runs under, or None. launchd sets
    XPC_SERVICE_NAME to the job's label; a process started from Terminal has
    none, or "0". Restricted to label characters because it ends up on a
    launchctl command line."""
    value = str((os.environ if environ is None else environ).get("XPC_SERVICE_NAME") or "")
    value = value.strip()
    if not value or value == "0" or len(value) > 200:
        return None
    if not all(ch.isalnum() or ch in "._-" for ch in value):
        return None
    return value


def kickstart_launchd(label: str, run: Optional[Callable[..., Any]] = None) -> bool:
    """`launchctl kickstart gui/<uid>/<label>` -> whether launchd took it.
    Without -k: a job that is somehow running already is left alone."""
    runner = run or subprocess.run
    try:
        result = runner(["/bin/launchctl", "kickstart", f"gui/{os.getuid()}/{label}"],
                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL, timeout=30)
    except Exception:  # noqa: BLE001
        return False
    return getattr(result, "returncode", 1) == 0


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


def supervisor_argv(exe: Path, pid: int, crash_dir: Path, state_dir: Path,
                    prior: Optional[list[float]] = None,
                    label: Optional[str] = None) -> list[str]:
    argv = [str(exe), FLAG, str(pid), "--exe", str(exe),
            "--crash-dir", str(crash_dir), "--state-dir", str(state_dir)]
    if label:
        argv += [LAUNCHD_LABEL_FLAG, label]
    # comp-ui-2: omitted entirely when there is nothing to carry, so a
    # companion one release older (which passes none) produces the argv this
    # function always produced.
    stamps = merge_history(prior)
    if stamps:
        argv += [PRIOR_FLAG, ",".join(f"{t:.3f}" for t in stamps)]
    return argv


def spawn_for(pid: int, exe: Path, crash_dir: Path, state_dir: Path, *,
              frozen: Optional[bool] = None, platform: Optional[str] = None,
              enabled: bool = True, environ: Optional[dict[str, str]] = None,
              spawn: Optional[Callable[..., Any]] = None,
              prior: Optional[list[float]] = None) -> Optional[Any]:
    """Companion side: start a supervisor for `pid`. Returns the Popen, or
    None with the reason logged by the caller: frozen Windows and macOS
    builds only, and a source run has nothing to relaunch.

    macOS since 2026-09-26 (see the module docstring). Before that a Mac had
    no net at all (bug-hunt-2026-09-03 comp-core-2): the companion LaunchAgent
    is RunAtLoad with, deliberately, no KeepAlive (a self-upgrade would
    otherwise leave two companions), so a companion that aborted stayed dead
    until the next logon."""
    environ = os.environ if environ is None else environ
    if not enabled or environ.get(DISABLE_ENV):
        return None
    plat = sys.platform if platform is None else platform
    if plat not in SUPPORTED_PLATFORMS:
        return None
    if not (bool(getattr(sys, "frozen", False)) if frozen is None else frozen):
        return None
    if not exe.is_file():
        return None
    run = spawn or _detached_popen
    label = launchd_label(environ) if plat == "darwin" else None
    return run(supervisor_argv(exe, pid, crash_dir, state_dir, prior=prior, label=label),
               exe.parent, child_env(environ))


# -- the supervisor process --------------------------------------------------


def _parse_prior(value: str) -> list[float]:
    out: list[float] = []
    for chunk in str(value or "").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            out.append(float(chunk))
        except ValueError:
            continue
    return merge_history(out)


def _parse(argv: list[str]) -> dict[str, Any]:
    args: dict[str, Any] = {"pid": None, "exe": None, "crash_dir": None,
                            "state_dir": None, "prior": [], "label": None}
    usage = (f"usage: {FLAG} <pid> --exe <path> --crash-dir <dir> "
             f"[--state-dir <dir>] [{PRIOR_FLAG} <t,t,t>]")
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
            elif item == LAUNCHD_LABEL_FLAG:
                args["label"] = launchd_label({"XPC_SERVICE_NAME": next(it)})
            elif item == PRIOR_FLAG:
                # comp-ui-2: never a SystemExit. A malformed value is a
                # supervisor that falls back to the file, not one that
                # refuses to watch the companion at all.
                args["prior"] = _parse_prior(next(it))
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
         clock: Callable[[], float] = time.time,
         kickstart: Optional[Callable[[str], bool]] = None,
         platform: Optional[str] = None) -> int:
    """The supervisor process. Waits for one companion, relaunches it at most
    once, exits. Every collaborator is injectable for the suite; the
    defaults are this platform's."""
    args = _parse(argv)
    pid: int = args["pid"]
    exe: Path = args["exe"]
    crash_dir: Path = args["crash_dir"]
    state_dir: Path = args["state_dir"]
    label: Optional[str] = args.get("label")
    log = _Log(crash_dir)
    windows = (sys.platform if platform is None else platform) == "win32"
    wait = waiter or (wait_for_exit_win32 if windows else wait_for_exit_kqueue)
    alive = pid_alive or (pid_is_alive_win32 if windows else pid_is_alive_posix)
    run = spawn or _detached_popen
    kick = kickstart or kickstart_launchd

    log(f"watching companion pid {pid} ({exe})")
    try:
        code = wait(pid)
    except Exception as exc:  # noqa: BLE001 - cannot wait: nothing to supervise
        log(f"could not wait on pid {pid}: {exc!r}; standing down")
        return 0
    marker = read_marker(crash_dir)
    if marker is not None and not exe.is_file():
        # res-companion-3 (2026-09-11b): only with a marker in hand, i.e.
        # only for a companion that died without starting a shutdown. A
        # missing exe with no marker is a deliberate uninstall, and decide()
        # is the one that reads the marker's pid.
        restore_interrupted_upgrade(exe, log)
    # comp-ui-2 / res-companion-4: the file is one source, the count carried
    # in on argv the other. Whichever is higher wins, so the ceiling holds
    # even where <state>/supervisor.json cannot be read or written.
    history = merge_history(read_history(state_dir), args.get("prior"))
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
    updated = merge_history(history, [when])
    note = {
        "when": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(when)),
        "previous_pid": pid,
        "exit_code": code,
        "reason": decision.reason,
        "attempt": len([t for t in history if abs(when - t) <= RELAUNCH_WINDOW_SECONDS]) + 1,
        "supervisor_pid": os.getpid(),
        # comp-ui-2: what the relaunched companion hands to the supervisor it
        # spawns for itself (crash_report.note_relaunch_history). Optional on
        # read: a companion one release older ignores it and the chain is
        # exactly as file-dependent as it was.
        "history": updated,
    }
    if not write_history(state_dir, updated):
        log(f"WARNING: could not record this relaunch in {state_dir / HISTORY_FILENAME} "
            "-- the 'three relaunches an hour' ceiling now rests entirely on the "
            "count carried to the relaunched companion. A state directory that "
            "cannot be written needs a human.")
    if not write_relaunch_note(crash_dir, note):
        # regression-21 (2026-09-11b): the same loud line write_history's
        # failure gets. This file is how the count reaches the relaunched
        # companion, and with both writers failing the ceiling is gone.
        log(f"WARNING: could not write {crash_dir / RELAUNCH_NOTE_FILENAME} "
            "-- the relaunched companion will not know how many times this "
            "build has been relaunched, and cannot pass the count on.")
    if label and not windows:
        # Back under the LaunchAgent, so an installer's bootout stops it and
        # the job's environment (RESOLVE_SCRIPT_*) is the one it starts with.
        if kick(label):
            log(f"relaunched {exe} through launchd (launchctl kickstart {label})")
            return 0
        log(f"launchctl kickstart {label} failed; starting {exe} directly")
    try:
        child = run([str(exe)], exe.parent, child_env())
    except Exception as exc:  # noqa: BLE001
        log(f"relaunch FAILED: {exc!r}")
        return 1
    log(f"relaunched {exe} as pid {getattr(child, 'pid', '?')}")
    return 0
