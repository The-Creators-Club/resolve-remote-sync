"""Main supervised loop tying together the watcher, fixer/popup, sync lanes,
and tray — the entry point started by `ccsync-companion` (see pyproject.toml
[project.scripts] and __main__.py).
"""

from __future__ import annotations

# Eagerly load the idna codec ON THE MAIN THREAD, before any worker thread
# exists. socket.getaddrinfo() lazily imports it on first use; when that
# first use is the reporter thread racing the main thread's own imports
# (tray/PIL, ~2s after start), the lazy import can fail under import-lock
# contention in the frozen exe -- and Python's codec registry CACHES the
# failure, so every network call in the process then fails with "unknown
# encoding: idna" until restart. Seen live 2026-07-25 on the v0.3.0 build.
import encodings.idna  # noqa: F401

import json
import logging
import logging.handlers
import os
import subprocess
import sys
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from . import broll_ingest as broll_ingest_mod
from . import music_ingest as music_ingest_mod
from . import broll_server as broll_server_mod
from . import canon
from . import capabilities as capabilities_mod
from . import jobs_runner as jobs_runner_mod
from . import config as config_mod
from . import crash_report
from . import eula as eula_mod
from . import file_moves as file_moves_mod
from . import machine as machine_mod
from . import idle as idle_mod
from . import luts as luts_mod
from . import music_worker
from . import paths as paths_mod
from . import popup
from . import bpg as bpg_mod
from . import proxy_gen as proxy_gen_mod
from . import proxy_relink
from . import reporter as reporter_mod
from . import resolve_bridge
from . import resolve_journal
from . import resolve_prefs as resolve_prefs_mod
from . import resolve_undo as resolve_undo_mod
from . import root_guard as root_guard_mod
from . import drive_reminder as drive_reminder_mod
from . import shutdown_guard as shutdown_guard_mod
from . import stills as stills_mod
from . import theme
from . import ui_dispatch
from . import upgrade as upgrade_mod
from . import site as site_mod
from . import youtube_import as youtube_import_mod
from . import ytdl_executor as ytdl_executor_mod
from . import ytdlp_manager as ytdlp_mod
from .fixer import IgnoreTracker, _dest_dir_is_contained
from .identity import IdentityManager
from .manifest import ManifestCache
from .paths import OUT_OF_TREE, classify_path
from .project_setup import ProjectSetupPrompter
from .reporter import DashboardReporter
from .selection import SelectionClient
from .sync import lane_guard
from .sync.base import STATE_ERROR, LaneAdapter, LaneStatus
from .sync.rclone_lane import DIRECTION_DOWN, DIRECTION_UP, VIDEO_EXTS, RcloneLane
from .sync.sequencer import PROJECTS_PREFIX, STATE_NO_SELECTION, Sequencer
from .sync.syncthing_admin import SyncthingAdmin
from .sync.syncthing_lane import SyncthingLane
from .sync.syncthing_supervisor import STATE_FILENAME as SUPERVISOR_STATE_FILENAME
from .sync.syncthing_supervisor import SyncthingSupervisor
from .watcher import TimelineWatcher

log = logging.getLogger("ccsync.app")

# The log window an editor's diagnostics bundle can carry back.
# ops-efficiency-9 (CR-66, CR-67 item 9, 2026-08-21): this was 5 MB x 3 = 20 MB,
# and a machine turned up to log_level = "DEBUG" for an incident rotates through
# the whole of it in about half an hour -- so by the time the editor is asked
# for the log, the event that prompted the ask is already gone. 10 keeps the
# same 5 MB files and buys ~2.5 hours at DEBUG, ~days at INFO, for 30 MB more
# disk on a machine that holds terabytes of video.
LOG_MAX_BYTES = 5_000_000
LOG_BACKUP_COUNT = 10

# The diagnostics channel's own state (SYS-7, resilience sweep 2026-08-28):
# one upload per lane per hour, and which admin request has already been
# answered. ON DISK beside the breaker and halt latches, because the machine
# this rate limit protects the dashboard from is a machine that keeps
# restarting -- an in-memory limiter would upload a bundle per restart.
DIAGNOSTICS_STATE_FILENAME = "diagnostics_sent.json"
DIAGNOSTICS_LANE_ERROR_INTERVAL_SECONDS = 3600.0

# UX-13 / OPS-6 (resilience sweep 2026-08-28). The onboarding wizard writes
# this file before its clean-slate phase and deletes it on Finish. It is the
# ONLY record that an install was interrupted: the wizard's worker is a daemon
# thread, so closing the window kills it wherever it happens to be -- after
# the tree drive was unmapped, after the autostart entries were deleted,
# possibly with a config.toml from either side of the wipe. This companion
# finding the file means it is the leftover of a half-installed machine.
INSTALL_BREADCRUMB_FILENAME = "install_in_progress.json"


def install_in_progress_problem(cfg: Optional[dict[str, Any]] = None,
                                config_dir: Optional[Path] = None) -> str:
    """The config-problem sentence when an install never finished, else "".

    Reads ~/.ccsync/state, not the configured log directory's state dir: the
    wizard cannot know a log_path that a config it is about to overwrite might
    name, so the two halves agree on one fixed location
    (onboarding/steps.py install_breadcrumb_path).

    Never raises. An unreadable directory means "no breadcrumb": this is a
    refusal to sync, and a permissions hiccup must not manufacture one.
    """
    try:
        base = Path(config_dir) if config_dir is not None else config_mod.CONFIG_DIR
        if not (Path(base) / "state" / INSTALL_BREADCRUMB_FILENAME).exists():
            return ""
    except OSError:
        return ""
    prefix = str((cfg or {}).get("canonical_prefix", "") or "").strip()
    letter = prefix.rstrip("\\/") or "your media drive"
    return (
        "The last install of CCSync on this computer did not finish, so this "
        f"machine may have no {letter} drive and a half-written setup. Nothing "
        "will sync until it is finished. Run the CCSync installer again and "
        "choose FINISH THE INSTALL."
    )


class RotatingLogHandler(logging.handlers.RotatingFileHandler):
    """RotatingFileHandler that records its own rotations.

    ops-efficiency-9 (CR-66, 2026-08-21): nothing in a rotated log said that
    anything had been dropped, so "the log does not mention it" read as "it
    never happened" in exactly the incidents where the window had simply been
    exhausted. One INFO line at the head of each new file makes the truncation
    visible to whoever reads it.
    """

    def doRollover(self) -> None:
        super().doRollover()
        try:
            # Emitted through the handler rather than the `ccsync` logger:
            # logging a rotation from inside the rotation is how a handler
            # recurses. The fresh file cannot roll over again on one line.
            self.emit(logging.LogRecord(
                "ccsync.log", logging.INFO, __file__, 0,
                "log rotated: %d file(s) of ~%d MB are kept, anything older is gone",
                (self.backupCount, self.maxBytes // 1_000_000), None,
            ))
        except Exception:
            pass


def setup_logging(cfg: dict[str, Any]) -> None:
    log_path = config_mod.resolved_log_path(cfg)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    level = getattr(logging, str(cfg.get("log_level", "INFO")).upper(), logging.INFO)

    root = logging.getLogger("ccsync")
    root.setLevel(level)
    root.handlers.clear()

    file_handler = RotatingLogHandler(
        log_path, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT, encoding="utf-8"
    )
    handlers: list[logging.Handler] = [file_handler]
    # In the windowed (console=False) build sys.stderr is None -- a
    # StreamHandler would just swallow every record via handleError. Only
    # attach it when there's a real stream (source runs, console builds).
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler())
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    for handler in handlers:
        handler.setFormatter(fmt)
        root.addHandler(handler)

    # pystray logged under its own "pystray" root, which had no handler at all:
    # in the windowed build sys.stderr is None, so logging's last-resort
    # handler had nowhere to write either, and everything the tray backend said
    # about itself was invisible on exactly the machines where the tray
    # misbehaves. tray_native (2026-08-17, COMMERCIAL_READINESS.md item 3) logs
    # under "ccsync.tray.native" and needs none of this; the wiring stays for
    # the CCSYNC_TRAY_BACKEND=pystray dev escape hatch, which is the only way
    # that logger can still exist.
    pystray_log = logging.getLogger("pystray")
    pystray_log.setLevel(level)
    pystray_log.handlers.clear()
    for handler in handlers:
        pystray_log.addHandler(handler)


# -- the shutdown backstop (MAC-11's follow-up) ---------------------------
#
# ui_dispatch.stop() now destroys the dialog the UI thread is parked in, and
# that is the FIX. This is the answer to "and what if that doesn't work
# either" -- a Tk interpreter too far gone to service a destroy, an AppKit
# modal session nothing of ours owns. shutdown() has by then stopped every
# lane, the reporter and the manifest cache and joined the Resolve-touching
# threads, and the self-upgrade does its binary swap BEFORE it asks for a
# shutdown, so there is nothing left to flush and nothing left to corrupt --
# the only thing still owed is `serve()` returning. If it has not returned
# within this grace, exiting hard beats the alternative, which is measured:
# a process alive forever holding the single-instance slot, so every
# relaunch exits with "another ccsync-companion is already running" and the
# machine has no companion until someone finds a terminal (2026-08-05).
UI_SHUTDOWN_GRACE_SECONDS = 10.0

# How long a thread that is about to let go of a work-progress window waits
# for that window's OWN thread to finish tearing it down (CR-93, 2026-08-29).
# A Tk root's Tcl interpreter must be freed on the thread that made it, and a
# window still holding its widgets when another thread drops the last
# reference is Tcl_AsyncDelete -- an abort, not an exception. Bounded because
# a window that will not close must not stall the click that replaced it, and
# must not stall shutdown; the graveyard in ui_dispatch.release_root is what
# covers the case where the wait was not enough.
WORK_WINDOW_CLOSE_WAIT_SECONDS = 3.0


def _close_work_window(window: Any, what: str) -> None:
    """Close a work-progress window and WAIT for it to finish tearing itself
    down, before this thread lets go of it.

    The wait is the point (CR-93). That window's Tk root was built on its own
    thread, and a Tcl interpreter freed anywhere else calls Tcl_Panic --
    abort(), no traceback, the whole tray gone. `close()` only ASKS; the
    window's thread does the destroying, and `wait_closed` is how we know it
    has. Both callers reach here from another thread entirely: a tray click
    replacing one window with another, and shutdown() on the main thread.

    getattr for `wait_closed`: the doubles tests inject implement close() and
    nothing else, and a missing method must not turn "close the window" into
    a swallowed AttributeError.
    """
    try:
        window.close()
        waiter = getattr(window, "wait_closed", None)
        if waiter is not None and not waiter(WORK_WINDOW_CLOSE_WAIT_SECONDS):
            log.warning(
                "%s did not finish closing within %.0fs -- letting go of it "
                "anyway. If its Tk objects are still up, ui_dispatch's "
                "graveyard is what stops that becoming a CR-93 abort.",
                what, WORK_WINDOW_CLOSE_WAIT_SECONDS)
    except Exception:
        log.debug("could not close %s", what, exc_info=True)

# How often the licence offer is retried while the gate is live and the
# dialog has never actually been SHOWN (KNOWN_BUGS CR-27, 2026-08-18). It is
# not a nag interval: the loop stops the moment the document has been put in
# front of somebody, accepted or declined. It exists because the first
# attempt loses a race it will keep losing -- the out-of-tree clip popup
# takes `_popup_active_lock` about three seconds before the licence dialog
# asks for it, on every start, on any machine whose Resolve projects
# reference clips outside the tree (measured on ruskin's PC: 65 clips, then
# 102, every start, for hours). One-shot meant the only route back was a
# tray item nobody knew to look for, with all three lanes parked.
LICENCE_RETRY_SECONDS = 60.0
# A pushed update that could not swap (a CCSync window open, a consolidate
# in flight, a failed download) is RETRIED, not latched off (ultrareview
# 2026-08-19): the request rides every report until the dashboard sees the
# new version, so the attempt must be allowed to recur -- but not every 30 s,
# and not with a fresh toast each time. A stand-down is transient (the editor
# closes the window); a failed download probably is not, so it waits longer.
PUSHED_UPDATE_RETRY_SECONDS = 90.0
PUSHED_UPDATE_FAILED_RETRY_SECONDS = 600.0


def _hard_exit(code: int) -> None:
    """os._exit, via a seam the tests can hold. Flushes the log first: _exit
    skips atexit and every handler's buffer, and the line explaining why the
    process vanished is the whole point of the exercise."""
    try:
        for handler in list(logging.getLogger("ccsync").handlers):
            try:
                handler.flush()
            except Exception:
                pass
    finally:
        os._exit(code)


# -- single-instance guard (AUDIT_2 CORE-M7) ------------------------------
# Two companions = two watchers hammering the Resolve C extension from four
# more threads, two rclone lane sets writing the same tree and the same
# state/ files, two reporters POSTing under one identity, and two self-
# upgrades renaming the same exe. The trigger is the single most likely user
# action after "it looks like it's not running": double-clicking the desktop
# exe while the Run-key instance is already live.
_SINGLE_INSTANCE_MUTEX = "Local\\ccsync-companion-single-instance"
_SINGLE_INSTANCE_LOCKFILE = "companion.pid"
_ERROR_ALREADY_EXISTS = 183
# Module-global purely to keep the handle/file object alive for the process
# lifetime -- Windows releases a mutex when its last handle closes.
_single_instance_token: Any = None

# Set by upgrade._default_spawn on the CHILD it launches, naming the pid the
# child is replacing. The self-upgrade spawns the new build BEFORE the old
# process has exited (it has to: request_shutdown() comes after the spawn, so
# a failed launch can still roll the whole swap back) -- so for a second or
# two there really are two companions, and BOTH guards must let the newcomer
# wait out its predecessor. On posix the pid file is a liveness check on the
# recorded pid; on Windows the named mutex lives until the predecessor's
# LAST HANDLE closes at process exit. Either way the dying predecessor holds
# the slot for exactly as long as its lanes take to stop, and a newcomer
# that refuses instead of waiting leaves the machine with NO companion until
# the next logon (posix: seen live pre-0.7.0; win32: R11, a remote editor's
# machine 2026-08-12 -- the old "the mutex is released the instant we die
# and the child wins by timing" assumption was backwards, the child reaches
# the guard ~1s in while the parent is still tearing down lanes). The wait
# is deliberately narrow: only the pid we were told we replace, only for as
# long as a normal shutdown takes.
_REPLACES_PID_ENV = "CCSYNC_REPLACES_PID"
# What a normal shutdown actually costs, summed from the bounded joins
# shutdown() and _stop_lanes() perform in series (comp-app-core-1,
# 2026-08-21):
#
#   sequencer.stop()      5  (_wait_for_lane_c_turn_idle)
#                       + 10 (worker join -- rclone_lane.run_once never sees
#                             the sequencer's _interrupt, so a worker parked
#                             on an rclone child sits out the whole join)
#   lane C stop            5
#   lane B stop            5 (periodic join) + 5 (observer join)
#   watcher + media tree   5 + 5 (a fusionscript call that does not return)
#   proxy generator        5, b-roll ingest 5, youtube importer 5
#   lane A stop, reporter, manifest cache, 8899 socket, tray: the rest
#
# 55 s of joins before anything unbounded, which is why the wait below is
# not 20 s any more. It WAS, and 20 s is less than the teardown it waits
# for: the child reaches the guard ~1 s after being spawned, gave up while
# the parent was still inside those joins, and the machine was left with no
# companion until the next logon -- R11's outcome, reached through the timer
# R11 introduced. The wait costs nothing when the predecessor exits early
# (it polls) and only ever applies to an upgrade hand-off, never to an
# editor double-clicking the exe.
SHUTDOWN_WORST_CASE_SECONDS = 55.0
PREDECESSOR_WAIT_SECONDS = 90.0
PREDECESSOR_POLL_SECONDS = 0.25


_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_ERROR_ACCESS_DENIED = 5
_STILL_ACTIVE = 259


def _pid_is_alive_win32(pid: int) -> bool:
    """SYNC-9 (2026-08-11): os.kill(pid, 0) is NOT a liveness probe on
    Windows. CPython's posixmodule maps any signal other than
    CTRL_C/CTRL_BREAK_EVENT to TerminateProcess(handle, sig) -- so it would
    KILL the pid it was asked about (with exit code 0), and for a pid that is
    already gone OpenProcess fails and the OSError arm below reads "alive".
    Wrong in both directions. A frozen build reaches this only through the
    CreateMutexW-unavailable fallback, which is why it went unnoticed."""
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        # Access denied means it exists and belongs to someone else -- the
        # same answer the posix PermissionError arm gives.
        return ctypes.get_last_error() == _ERROR_ACCESS_DENIED
    try:
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return True  # can't tell -- assume alive, i.e. fail safe
        # A process that genuinely exited with 259 reads as alive; the cost is
        # one predecessor wait, versus killing a live companion.
        return code.value == _STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def _pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        try:
            return _pid_is_alive_win32(pid)
        except Exception:
            log.debug("single-instance: could not probe pid %s", pid, exc_info=True)
            return True  # can't tell -- assume alive, i.e. fail safe
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, owned by someone else
    except OSError:
        return True  # can't tell -- assume alive, i.e. fail safe
    return True


def _replaced_pid() -> Optional[int]:
    """The pid this process was spawned to replace, or None. READS AND
    REMOVES the variable: it describes exactly one hand-off, and leaving it
    in os.environ would have every child we ever launch (rclone, osascript,
    the NEXT self-upgrade's spawn) inherit a stale claim."""
    raw = os.environ.pop(_REPLACES_PID_ENV, None)
    try:
        pid = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return pid if pid > 0 else None


def _wait_for_predecessor(
    pid: int,
    replaces_pid: Optional[int],
    alive_fn: Callable[[int], bool],
    clock: Callable[[], float] = time.monotonic,
    sleep_fn: Callable[[float], None] = time.sleep,
    timeout: float = PREDECESSOR_WAIT_SECONDS,
    poll_seconds: float = PREDECESSOR_POLL_SECONDS,
) -> bool:
    """Wait (briefly) for the process we are replacing to let go of the slot.

    True means it died and the slot is ours. False means "not our
    predecessor, or it never went away" -- and then the caller behaves
    exactly as it always did, i.e. this instance exits with the
    already-running message. Bounded on purpose: a predecessor that is wedged
    rather than shutting down is a genuine second instance, and starting a
    second companion over it is what the guard exists to prevent."""
    if replaces_pid is None or replaces_pid != pid:
        return False
    log.info(
        "single-instance: pid %s holds the slot and is the build we are replacing "
        "-- waiting up to %.0fs for it to exit", pid, timeout,
    )
    deadline = clock() + timeout
    while clock() < deadline:
        if not alive_fn(pid):
            log.info("single-instance: pid %s has exited -- taking the slot", pid)
            return True
        sleep_fn(poll_seconds)
    log.warning(
        "single-instance: pid %s is still running %.0fs after the self-upgrade "
        "spawned this build -- treating it as a live second instance", pid, timeout,
    )
    return False


# Distinguishes "caller already popped CCSYNC_REPLACES_PID" from "no
# predecessor": None is a meaningful value here.
_REPLACES_PID_NOT_GIVEN: Any = object()


def _acquire_lock_file(
    alive_fn: Optional[Callable[[int], bool]] = None,
    clock: Callable[[], float] = time.monotonic,
    sleep_fn: Callable[[float], None] = time.sleep,
    wait_seconds: float = PREDECESSOR_WAIT_SECONDS,
    replaces_pid: Any = _REPLACES_PID_NOT_GIVEN,
) -> bool:
    """Portable fallback: a pid file with a liveness check. A stale file from
    a crashed/killed companion must never lock the editor out permanently."""
    global _single_instance_token
    path = config_mod.CONFIG_DIR / _SINGLE_INSTANCE_LOCKFILE
    if replaces_pid is _REPLACES_PID_NOT_GIVEN:
        # Popped unconditionally, before any early return: it must not
        # survive into a child of ours whatever happens below. The win32
        # caller pops it before its own guard and hands the value through --
        # a second pop here would read nothing and silently lose the
        # predecessor wait exactly when the mutex guard is broken.
        replaces_pid = _replaced_pid()
    # Resolved by NAME, not bound as a default: tests monkeypatch the module
    # global, and a default argument would have captured the real one at
    # import time.
    is_alive = alive_fn if alive_fn is not None else _pid_is_alive
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            existing = int(path.read_text(encoding="utf-8").strip() or 0)
        except (OSError, ValueError):
            existing = 0
        if existing and existing != os.getpid() and is_alive(existing):
            if not _wait_for_predecessor(
                existing, replaces_pid, is_alive, clock=clock, sleep_fn=sleep_fn,
                timeout=wait_seconds,
            ):
                return False
        path.write_text(str(os.getpid()), encoding="utf-8")
        _single_instance_token = path
        return True
    except Exception:
        log.debug("single-instance lock file unavailable", exc_info=True)
        return True  # never block startup on the guard itself failing


def _acquire_mutex_win32(
    try_create: Callable[[], "tuple[Any, int]"],
    close_handle: Callable[[Any], Any],
    replaces_pid: Optional[int],
    alive_fn: Optional[Callable[[int], bool]] = None,
    clock: Callable[[], float] = time.monotonic,
    sleep_fn: Callable[[float], None] = time.sleep,
    timeout: float = PREDECESSOR_WAIT_SECONDS,
    poll_seconds: float = PREDECESSOR_POLL_SECONDS,
) -> bool:
    """R11 (2026-08-12): the named-mutex twin of _acquire_lock_file's
    predecessor wait. The branch used to return False the moment CreateMutexW
    reported ERROR_ALREADY_EXISTS, on the assumption the mutex "is released
    the instant the predecessor dies and the child wins by timing". Backwards:
    the self-upgrade's child reaches this guard ~1s after being spawned while
    the predecessor is still tearing down its lanes and holding the mutex --
    the child exited, the predecessor finished exiting, and the machine was
    left with NO companion until the next logon.

    A mutex cannot be asked WHO holds it, so the holder==predecessor check
    the lock file does against its contents is keyed on CCSYNC_REPLACES_PID
    alone, and the wait retries CreateMutexW itself rather than reusing
    _wait_for_predecessor's liveness-only loop: _pid_is_alive_win32 can read
    a DEAD process as alive (exit code 259, plus both fail-safe arms), and a
    wait keyed on liveness alone would then sit out the full timeout and
    refuse -- re-creating the mutex each poll takes the slot the moment it is
    actually free, whatever the probe says."""
    global _single_instance_token
    is_alive = alive_fn if alive_fn is not None else _pid_is_alive
    handle, last_error = try_create()
    if not handle:
        return True  # the guard itself failed -- never block a legitimate start
    if last_error != _ERROR_ALREADY_EXISTS:
        _single_instance_token = handle
        return True
    # Our probe handle keeps the named object ALIVE: while we hold it the
    # mutex outlives the predecessor and every retry below would read
    # ALREADY_EXISTS forever. Dropped before any wait, and after every
    # failed retry.
    close_handle(handle)
    if replaces_pid is None:
        return False  # not an upgrade hand-off: refuse immediately, as always
    log.info(
        "single-instance: the slot is held and this build replaces pid %s "
        "-- waiting up to %.0fs for it to exit", replaces_pid, timeout,
    )
    deadline = clock() + timeout
    while clock() < deadline:
        # Sampled BEFORE the create attempt: dead before the attempt means
        # its handles were already gone, so a mutex that still exists is some
        # OTHER companion's -- while dead-after could just be the predecessor
        # exiting between the two calls.
        was_alive = is_alive(replaces_pid)
        sleep_fn(poll_seconds)
        handle, last_error = try_create()
        if not handle:
            return True
        if last_error != _ERROR_ALREADY_EXISTS:
            log.info(
                "single-instance: predecessor pid %s released the slot -- taking it",
                replaces_pid,
            )
            _single_instance_token = handle
            return True
        close_handle(handle)
        if not was_alive:
            log.warning(
                "single-instance: pid %s is gone but the slot is still held "
                "-- a different companion owns it", replaces_pid,
            )
            return False
    log.warning(
        "single-instance: the slot is still held %.0fs after the self-upgrade "
        "spawned this build -- treating the holder as a live second instance",
        timeout,
    )
    return False


def acquire_single_instance() -> bool:
    """True when this process may run. False means another companion already
    holds the slot. Never raises; any failure of the guard itself returns
    True rather than blocking a legitimate start."""
    if sys.platform != "win32":
        return _acquire_lock_file()
    # Popped here, before anything can fail: it must not inherit into every
    # rclone this process goes on to launch. The value feeds whichever guard
    # actually runs below.
    replaces_pid = _replaced_pid()
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

        def _try_create() -> "tuple[Any, int]":
            handle = kernel32.CreateMutexW(None, False, _SINGLE_INSTANCE_MUTEX)
            return handle, ctypes.get_last_error()

        return _acquire_mutex_win32(_try_create, kernel32.CloseHandle, replaces_pid)
    except Exception:
        log.debug("single-instance mutex unavailable", exc_info=True)
        return _acquire_lock_file(replaces_pid=replaces_pid)


def _osascript_run(argv: list) -> None:
    """Run an osascript argv with a sanitized environment. A module-level
    seam so tests can assert what would be shown without spawning anything.

    sanitized_child_env because PYTHONHOME/PYTHON3HOME are pinned at this
    process's _MEI dir for fusionscript, and a child inheriting them starts a
    Python pointed at a directory that is about to vanish (AUDIT_2 CORE-M6).
    Blocking, deliberately: this is the last thing the process does before
    exiting, so there is nothing left to keep responsive."""
    subprocess.run(  # noqa: S603 -- fixed argv, no shell
        argv,
        check=False,
        timeout=120,
        env=resolve_bridge.sanitized_child_env(),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _warn_already_running() -> None:
    log.warning("another ccsync-companion is already running -- this instance is exiting")
    if sys.platform == "darwin":
        # The macOS twin of the MessageBoxW below. Without it, double-clicking
        # the companion while it is already running does nothing visible at
        # all -- so the editor clicks it again, and again, and concludes it is
        # broken. `display alert` (not `display notification`): this is an
        # answer to something the user just did, and a banner that auto-
        # dismisses is exactly what they will miss.
        try:
            _osascript_run([
                "/usr/bin/osascript", "-e",
                'display alert "CCSync is already running." message '
                '"Look for the CCSync icon in the menu bar."',
            ])
        except Exception:
            log.debug("could not show the already-running alert", exc_info=True)
        return
    if sys.platform != "win32":
        return
    try:
        import ctypes

        # MB_OK | MB_ICONINFORMATION | MB_SETFOREGROUND
        ctypes.windll.user32.MessageBoxW(
            None,
            "CCSync is already running.\n\nLook for the CCSync icon in your system tray "
            "(you may need to click the ^ arrow next to the clock).",
            "CCSync",
            0x00000040 | 0x00010000,
        )
    except Exception:
        log.debug("could not show the already-running message box", exc_info=True)


# NSApplicationActivationPolicyAccessory. A menu-bar-only agent: no Dock
# icon, no application menu, no window that can be Cmd-Tabbed to.
_NS_ACTIVATION_POLICY_ACCESSORY = 1


def _set_darwin_activation_policy() -> None:
    """Make the companion a menu-bar accessory rather than a Dock app.

    macOS decides an app's shape from its activation policy, and a bare
    PyInstaller binary (no .app bundle, no Info.plist LSUIElement) defaults to
    Regular: a Dock icon that bounces at login, an application menu, and a
    Cmd-Tab entry -- for a background agent whose entire UI is one menu-bar
    icon. Worse, the Dock icon is a Quit button an editor will find and press.

    Lazy import inside the try, like shutdown_guard's AppKit paths: this
    module must import on a machine that has never heard of pyobjc, and a Mac
    without it simply keeps the Dock icon. Never raises, never on Windows.
    """
    if sys.platform != "darwin":
        return
    try:
        import AppKit

        AppKit.NSApplication.sharedApplication().setActivationPolicy_(
            _NS_ACTIVATION_POLICY_ACCESSORY
        )
        log.debug("macOS activation policy set to Accessory (menu bar only)")
    except Exception:
        log.debug("could not set the macOS activation policy -- the companion may "
                  "show a Dock icon", exc_info=True)


def _fallback_logging(cfg: dict[str, Any]) -> None:
    """Last-resort logging setup after setup_logging(cfg) raised.

    `log_path` is used unvalidated by resolved_log_path()/setup_logging():
    a non-str (TypeError), a path on a drive not mounted at logon
    (FileNotFoundError) or a blank string (PermissionError) all raise. That
    happened OUTSIDE any try, so the windowed exe vanished with no log, no
    tray and no toast -- the exact S-10 symptom the original fix was written
    to eliminate (AUDIT_2 CORE-H2). Fall back to the packaged default, and
    if even that fails, to a bare stderr/NullHandler setup so the process
    still starts."""
    broken = cfg.get("log_path")
    try:
        setup_logging({**cfg, "log_path": config_mod.DEFAULTS["log_path"]})
        log.error(
            "log_path %r is unusable -- logging to the default %s instead; "
            "fix log_path in %s",
            broken, config_mod.DEFAULTS["log_path"], config_mod.CONFIG_PATH,
        )
        return
    except Exception:
        pass
    root = logging.getLogger("ccsync")
    root.handlers.clear()
    root.setLevel(logging.INFO)
    root.addHandler(
        logging.StreamHandler() if sys.stderr is not None else logging.NullHandler()
    )
    log.error("log_path %r is unusable and the default failed too -- no log file", broken)


# The exact validate_config() problem that a disconnected sync drive
# produces. Matched as a prefix, not a substring: "local_root is blank" is a
# different failure with the same first word and must NOT be demoted (see
# CompanionApp._demote_removable_root_problem).
_LOCAL_ROOT_MISSING_PREFIX = "local_root does not exist:"

# What a lane says while the tree is not there. Read by tray.py through the
# normal detail channel, same as the pending-login/misconfigured details.
#
# A FUNCTION, not a constant: the drive's name comes from the site manifest
# (site.drive_phrase), which this machine may not have cached yet at import
# time -- an install whose first manifest fetch happens after start() would
# otherwise say "your studio drive" for the life of the process
# (2026-08-17, docs/COMMERCIAL_READINESS.md item 10).
def _lane_root_absent_detail() -> str:
    return (f"PAUSED: {site_mod.drive_phrase()} is disconnected -- plug it "
            f"back in and syncing resumes on its own")


def _leaf_name(path: str) -> str:
    """The last path component whichever separator the string uses."""
    return path.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]


def _proxy_state_note(state: str) -> str:
    """proxy_gen's gate, in the sentence the progress window shows.

    Deliberately not the tray's words: the tray says "Making proxies... 12
    left" to somebody glancing at a menu, and this is for somebody watching a
    window and wondering why the bar is not moving.
    """
    return {
        proxy_gen_mod.STATE_USER_ACTIVE: "waiting until you're away from the keyboard",
        proxy_gen_mod.STATE_RESOLVE_OPEN: "waiting: DaVinci Resolve is open",
        proxy_gen_mod.STATE_PAUSED: "paused",
        proxy_gen_mod.STATE_NO_FFMPEG: "waiting: ffmpeg is not installed here",
        proxy_gen_mod.STATE_DRIVE_ABSENT: "waiting: the sync drive is not connected",
        proxy_gen_mod.STATE_MISCONFIGURED: "waiting: this machine's sync config needs fixing",
    }.get(state, "")


# -- thread supervision (SYS-2, resilience sweep 2026-08-28) ---------------
#
# The companion runs its own unsupervised loop threads: the sequencer, the
# timeline watcher and the media-tree cache. Until this sweep NOTHING watched
# any of them. A sequencer that died on one OSError left the machine online,
# reporting, and frozen on its last lane state forever -- "green while dead",
# the ledger class the fleet dashboard has never once been the discoverer of.
# The dashboard solved exactly this on its own side (collector.thread_died /
# seconds_since_heartbeat / restart, driven by app.CollectorWatchdog); this is
# the same pattern applied to the side where the failure was actually
# observed, with one addition: every restart is RECORDED and REPORTED, because
# a machine that needs restarting three times an hour is a fault to see and
# not a fault to quietly paper over.
WATCHDOG_STATE_FILENAME = "watchdog.json"
LANE_WATCHDOG_INTERVAL_SECONDS = 60.0
# How long a thread may be inside one iteration before it counts as wedged.
# The sequencer gets max(3 x project_rotation_seconds, this): one project turn
# is budgeted project_rotation_seconds per rclone lane, so a heartbeat older
# than three of them is a turn that overran its own budget, not a big upload.
LANE_WATCHDOG_WEDGED_SECONDS = 30.0 * 60.0
# Restarts of ONE thread within an hour that earn the editor a tray line. Two
# is a machine that recovered; three is a machine that needs a human.
LANE_WATCHDOG_ADVISORY_RESTARTS = 3
_WATCHDOG_EVENTS_KEPT = 50
_WATCHDOG_DAY_SECONDS = 24.0 * 3600.0
_WATCHDOG_HOUR_SECONDS = 3600.0


def _watchdog_iso(when: float) -> str:
    return datetime.fromtimestamp(when, timezone.utc).isoformat()


class _SupervisedThread:
    """One thread the watchdog owns, as answers rather than objects: whether
    it is gone, how long it has been silent, how long silence is allowed, what
    killed it, and how to start a replacement.

    A plain value object on purpose -- the whole restart policy is then
    testable with no threads, no clock and no CompanionApp."""

    __slots__ = ("name", "died", "silent_for", "bound", "error", "restart")

    def __init__(self, name: str, *, died: bool, silent_for: float,
                 bound: float, error: Optional[str],
                 restart: Callable[[], Any]) -> None:
        self.name = name
        self.died = died
        self.silent_for = silent_for
        self.bound = bound
        self.error = error
        self.restart = restart


class LaneWatchdog:
    """Watches the companion's own loop threads and restarts the dead ones.

    `check()` is the whole policy and is deliberately callable on its own, so
    the decision can be tested without a thread and without a clock (the same
    hatch CollectorWatchdog.check() is). It never raises: a state it cannot
    read is not evidence of a fault, and spawning a second sequencer over a
    misread is worse than the outage it would be answering.
    """

    def __init__(self, app: Any, *,
                 interval: float = LANE_WATCHDOG_INTERVAL_SECONDS,
                 wedged_after: float = LANE_WATCHDOG_WEDGED_SECONDS,
                 state_path: Optional[Path] = None,
                 monotonic: Callable[[], float] = time.monotonic,
                 now: Callable[[], float] = time.time) -> None:
        self.app = app
        self.interval = float(interval)
        self.wedged_after = float(wedged_after)
        self._state_path = state_path
        self._monotonic = monotonic
        self._now = now
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        # name -> [epoch seconds of each restart]. Loaded from disk at
        # construction: a crash loop that restarts the whole companion must
        # not reset the counter that is the evidence of the crash loop
        # (never make a safety latch in-memory-only).
        self._events: dict[str, list[float]] = {}
        self._last_error: dict[str, Optional[str]] = {}
        self._load_record()

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        if self.interval <= 0:
            log.info("thread watchdog disabled (interval=%s)", self.interval)
            return
        self._thread = threading.Thread(target=self._loop,
                                        name="ccsync-thread-watchdog", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=5)

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                self.check()
            except Exception:  # noqa: BLE001 - a watchdog that dies is worse
                log.exception("thread watchdog: the check failed; continuing")

    # -- policy ------------------------------------------------------------
    def check(self) -> list[str]:
        """One tick. Returns the names restarted, in check order."""
        blocked = self._must_not_restart()
        if blocked:
            log.debug("thread watchdog: standing down (%s)", blocked)
            return []
        restarted: list[str] = []
        for target in self._targets():
            if target is None:
                continue
            if target.died:
                reason = ("the thread is gone: "
                          f"{target.error or 'no exception was recorded'}")
            elif target.bound > 0 and target.silent_for > target.bound:
                reason = (f"no heartbeat for {target.silent_for:.0f}s "
                          f"(the bound is {target.bound:.0f}s)")
            else:
                continue
            log.error("thread watchdog: restarting the %s -- %s", target.name, reason)
            if self._restart(target):
                restarted.append(target.name)
        return restarted

    def _must_not_restart(self) -> str:
        """"" when a restart is allowed, else why not.

        Two stand-downs, both about spawning work into a process that is about
        to end or is mid-operation: shutdown (a restarted sequencer would
        outlive the teardown that already stopped it) and the upgrade/popup
        stand-down predicate every caller of restart_self shares -- a
        consolidate or an open popup is exactly when a fresh lane pass must
        not start underneath it."""
        app = self.app
        if getattr(app, "_shutdown_started", False):
            return "the companion is shutting down"
        stop_event = getattr(app, "_stop_event", None)
        if stop_event is not None and stop_event.is_set():
            return "the companion is shutting down"
        try:
            blocker = app._standing_down_would_kill_work()
        except Exception:  # noqa: BLE001
            log.debug("thread watchdog: could not read the stand-down state",
                      exc_info=True)
            blocker = ""
        if blocker:
            return f"a {blocker} is in flight"
        return ""

    def _targets(self) -> tuple[Optional[_SupervisedThread], ...]:
        return (self._sequencer_target(), self._watcher_target(),
                self._media_tree_target())

    def _sequencer_target(self) -> Optional[_SupervisedThread]:
        seq = getattr(self.app, "sequencer", None)
        if seq is None or getattr(seq, "thread_died", None) is None:
            # No sequencer at all (unmanaged mode), or a build/double whose
            # liveness contract predates SYS-2. Absent evidence, not a fault.
            return None
        try:
            died = bool(seq.thread_died())
            silent = 0.0 if died else float(seq.seconds_since_heartbeat())
            error = seq.last_error() if died else None
        except Exception:  # noqa: BLE001
            log.exception("thread watchdog: could not read the sequencer's "
                          "state; assuming it is fine")
            return None
        try:
            rotation = float(getattr(seq, "project_rotation_seconds", 0) or 0)
        except (TypeError, ValueError):
            rotation = 0.0
        bound = max(3.0 * rotation, self.wedged_after)
        return _SupervisedThread("sequencer", died=died, silent_for=silent,
                                 bound=bound, error=error, restart=seq.start)

    def _watcher_target(self) -> Optional[_SupervisedThread]:
        app = self.app
        thread = getattr(app, "_watcher_thread", None)
        stopping = getattr(app, "_stop_event", None)
        if thread is None or (stopping is not None and stopping.is_set()):
            return None
        died = not thread.is_alive()
        silent = 0.0
        if not died:
            silent = self._silence(getattr(app, "watcher", None), "_heartbeat")
        return _SupervisedThread(
            "watcher", died=died, silent_for=silent, bound=self.wedged_after,
            error=getattr(app, "_watcher_thread_error", None),
            restart=app._start_watcher_thread)

    def _media_tree_target(self) -> Optional[_SupervisedThread]:
        app = self.app
        thread = getattr(app, "_media_tree_thread", None)
        stopping = getattr(app, "_media_tree_stop_event", None)
        if thread is None or (stopping is not None and stopping.is_set()):
            return None
        died = not thread.is_alive()
        silent = 0.0
        if not died:
            silent = self._silence(app, "_media_tree_heartbeat")
        return _SupervisedThread(
            "media_tree", died=died, silent_for=silent, bound=self.wedged_after,
            error=getattr(app, "_media_tree_thread_error", None),
            restart=app._start_media_tree_thread)

    def _silence(self, owner: Any, attribute: str) -> float:
        """Seconds since `owner.<attribute>` was stamped, or 0.0 when there is
        no stamp to read. A missing heartbeat is a thread whose loop does not
        publish one, which must never be restarted on that basis alone."""
        beat = getattr(owner, attribute, None) if owner is not None else None
        if not isinstance(beat, (int, float)) or isinstance(beat, bool):
            return 0.0
        return max(0.0, self._monotonic() - float(beat))

    def _restart(self, target: _SupervisedThread) -> bool:
        error = target.error
        try:
            target.restart()
        except Exception as exc:  # noqa: BLE001
            log.exception("thread watchdog: could not restart the %s", target.name)
            error = f"restart failed: {type(exc).__name__}: {exc}"
            self._record(target.name, error)
            return False
        self._record(target.name, error)
        return True

    # -- the record --------------------------------------------------------
    def _record(self, name: str, error: Optional[str]) -> None:
        when = float(self._now())
        with self._lock:
            events = [t for t in self._events.get(name, [])
                      if when - t <= _WATCHDOG_DAY_SECONDS]
            events.append(when)
            self._events[name] = events[-_WATCHDOG_EVENTS_KEPT:]
            self._last_error[name] = error or None
        self._write_record()

    def report(self) -> dict[str, dict[str, Any]]:
        """The `sync_guard.restarts` section: per thread, count_24h, count_1h,
        last_at and last_error.

        {} when no thread has ever been restarted, so an absent key is how
        "nothing has needed restarting" is spelled -- which is also what
        clears the chip. Never raises."""
        now = float(self._now())
        out: dict[str, dict[str, Any]] = {}
        with self._lock:
            items = [(name, list(events)) for name, events in self._events.items()]
            errors = dict(self._last_error)
        for name, events in items:
            day = [t for t in events if now - t <= _WATCHDOG_DAY_SECONDS]
            if not day:
                continue
            out[name] = {
                "count_24h": len(day),
                # NOT in the wire contract's three keys, and additive on
                # purpose: the tray advisory is "3 restarts in an HOUR", and
                # the alternative is every reader re-deriving it from a
                # timestamp list nobody else needs.
                "count_1h": len([t for t in day if now - t <= _WATCHDOG_HOUR_SECONDS]),
                "last_at": _watchdog_iso(max(day)),
                "last_error": errors.get(name),
            }
        return out

    def _write_record(self) -> None:
        path = self._state_path
        if path is None:
            return
        with self._lock:
            payload = {
                "written_at": _watchdog_iso(float(self._now())),
                "threads": {
                    name: {"events": list(events),
                           "last_error": self._last_error.get(name)}
                    for name, events in self._events.items()
                },
            }
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            os.replace(tmp, path)
        except Exception:  # noqa: BLE001
            log.debug("thread watchdog: could not write %s", path, exc_info=True)

    def _load_record(self) -> None:
        path = self._state_path
        if path is None:
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            return
        except Exception:  # noqa: BLE001
            log.debug("thread watchdog: unreadable record", exc_info=True)
            return
        if not isinstance(data, dict):
            return
        threads = data.get("threads")
        if not isinstance(threads, dict):
            return
        now = float(self._now())
        for name, entry in threads.items():
            if not isinstance(name, str) or not isinstance(entry, dict):
                continue
            events = [float(t) for t in (entry.get("events") or [])
                      if isinstance(t, (int, float))
                      and 0 < now - float(t) <= _WATCHDOG_DAY_SECONDS]
            if events:
                self._events[name] = sorted(events)[-_WATCHDOG_EVENTS_KEPT:]
            error = entry.get("last_error")
            self._last_error[name] = error if isinstance(error, str) else None


class CompanionApp:
    """Owns the timeline watcher, all three sync lanes, and (optionally) the
    tray icon. Every public method is safe to call from any thread (the
    tray runs its callbacks on its own thread)."""

    def __init__(self, cfg: dict[str, Any], exists_fn: Callable[[str], bool] = os.path.exists) -> None:
        self.config = cfg
        # The bridge reads no config of its own; the six library keys are
        # pushed in here so the walk knows which project library to read and
        # whether to read one at all (library walk, 2026-08-26).
        resolve_bridge.configure_library(cfg)
        self.log_path = config_mod.resolved_log_path(cfg)
        # Injectable for tests -- see get_media_tree()/_refresh_media_tree_once().
        self._exists_fn = exists_fn
        # RES-12 / UX-4 (resilience sweep 2026-08-28): the tracker now has a
        # persisted half -- the folders an editor said to leave alone for
        # good, and the ledger of everything ever skipped. Both live under
        # <log dir>/state/ (see fixer's note on why NOT beside config.toml,
        # unlike the two safety latches APP-3 moved). self.log_path is
        # resolved_log_path(cfg), so a `log_path = ""` config cannot put this
        # in C:\Windows\system32 the way AUDIT_3 M-7 describes.
        self.ignore_tracker = IgnoreTracker(self.log_path.parent / "state")
        # Paths recently shown in a popup the user closed without acting:
        # snoozed so the dialog doesn't re-pop every poll cycle forever.
        # GUARDED BY _popup_snooze_lock: the WATCHER thread prunes/reads this
        # dict while a ccsync-popup thread inserts into it, and mutating a
        # dict mid-iteration raises RuntimeError -- inside the watcher's poll
        # loop, whose out-of-tree handler would then be skipped for that
        # cycle (AUDIT_3 L-9).
        self._popup_snooze: dict[str, float] = {}
        self._popup_snooze_lock = threading.Lock()
        self.popup_snooze_seconds = config_mod.coerce_numeric(cfg, "popup_snooze_seconds", 300)
        # popup.show_popup blocks (it runs a Tk mainloop) and Tk is not
        # thread-safe -- this guards against the passive watcher-driven
        # popup and the user-initiated "Scan whole project" tray action
        # both trying to open a Tk root at once.
        self._popup_active_lock = threading.Lock()
        # The one live work-progress window (popup.WorkProgressWindow), as
        # (key, window). One at a time: two Tk roots in this process is
        # CORE-M3's wedged interpreter.
        self._work_window: Any = None
        self._work_window_lock = threading.Lock()
        # Batches that turned up while a popup was ON SCREEN, shown the
        # moment it closes (2026-08-01). Tk still permits only one root at a
        # time, but "one at a time" no longer means "the rest are thrown
        # away" -- see _show_out_of_tree_popup. GUARDED BY _popup_queue_lock.
        self._popup_queue: list[dict[str, Any]] = []
        self._popup_queue_keys: set[str] = set()
        self._popup_showing_keys: set[str] = set()
        self._popup_queue_lock = threading.Lock()
        # Serializes consolidate_project() with itself, and lets the
        # self-upgrade refuse to swap the exe mid-copy (AUDIT_2 CORE-H8/M13).
        # Separate from _popup_active_lock on purpose: consolidate holds THIS
        # for hours but the popup lock only for its dialogs.
        self._consolidate_lock = threading.Lock()
        self._consolidate_active = False
        # Scratch/utility Resolve project names (config `ignored_resolve_
        # projects`), normalized the same way watcher.TimelineWatcher does
        # -- used by _refresh_media_tree_once() so the media-tree reporter
        # honors the same "pretend this project doesn't exist" contract the
        # watcher already enforces (see X-7: this cache used to have no
        # ignore check at all, so an ignored scratch project's clips could
        # get reported under "media_tree" and, server-side, fuzzy-match
        # onto and overwrite a real project's bin tree).
        self._ignored_resolve_projects = config_mod.normalize_ignored_projects(
            cfg.get("ignored_resolve_projects")
        )
        self._paused = False
        self._stop_event = threading.Event()
        self._watcher_thread: Optional[threading.Thread] = None
        # What killed the watcher thread, for LaneWatchdog's record (SYS-2).
        self._watcher_thread_error: Optional[str] = None
        # Token-expiry watcher (CORE-M11) -- see _identity_watch_loop().
        self.identity_check_interval = config_mod.coerce_numeric(cfg, "identity_check_interval", 60)
        self._identity_stop_event = threading.Event()
        self._identity_thread: Optional[threading.Thread] = None
        # Warns on the Windows shutdown screen while a sync is in flight --
        # see shutdown_guard.py. Built in start(), because until then there
        # are no lanes to have a status.
        self._shutdown_guard: Optional[shutdown_guard_mod.ShutdownGuard] = None
        self._keep_awake: Optional[shutdown_guard_mod.KeepAwakeGuard] = None
        # Shared by BOTH power guards: "busy" alone is not a reason to keep a
        # machine awake or interrupt a shutdown, and this is what remembers
        # whether anything has actually MOVED. The keep-awake loop's 30 s poll
        # is what keeps its samples fresh. Both thresholds are config keys
        # because editors run a prebuilt exe: tuning them must not need a
        # rebuild. coerce_numeric never raises here (construction must survive
        # a hand-edited value) and PendingTracker screens them again.
        self._pending_tracker = shutdown_guard_mod.PendingTracker(
            stale_seconds=config_mod.coerce_numeric(
                cfg, "keep_awake_stale_seconds",
                shutdown_guard_mod.PROGRESS_STALE_SECONDS),
            max_hold_seconds=config_mod.coerce_numeric(
                cfg, "keep_awake_max_hold_seconds",
                shutdown_guard_mod.MAX_HOLD_SECONDS),
        )
        # shutdown() is called from the tray's Quit AND from run()'s finally
        # (and by the self-upgrade); running the teardown twice raced two
        # _stop_lanes()/reporter.stop() sequences against each other.
        self._shutdown_lock = threading.Lock()
        self._shutdown_started = False
        self._tray_icon = None
        # Config errors that STOP syncing. Computed HERE, not just in run(),
        # because the gates that consume it (the out-of-tree popup, FIX ALL,
        # Consolidate) can all fire before/without run() -- and it was
        # previously written and never read at all, despite the comment
        # claiming it reached the tray (AUDIT_2 DEL-3 + §2-low). run() logs
        # it, _start_lanes() refuses to start on it, and the tray renders it.
        try:
            self.config_problems, self.config_warnings = config_mod.validate_config(cfg)
        except Exception:
            log.exception("validate_config() failed")
            self.config_problems, self.config_warnings = [], []
        # UX-13 / OPS-6 (resilience sweep 2026-08-28): an install that never
        # finished. The onboarding wizard writes the breadcrumb before its
        # clean-slate phase (which unmaps the tree drive, kills this app and
        # deletes every autostart entry) and clears it on Finish. Finding it
        # here means we are the leftover of a half-installed machine -- the
        # config on disk may be from either side of the wipe, and syncing
        # against it is how an editor spends a week believing they are set up.
        # A config PROBLEM, deliberately: that is the one gate every lane,
        # the popup, FIX ALL and Consolidate already obey (DEL-3).
        interrupted = install_in_progress_problem(cfg)
        if interrupted:
            self.config_problems = list(self.config_problems or []) + [interrupted]
            log.error("%s", interrupted)

        # -- external-SSD root state (root_guard.py) ----------------------
        # An editor's tree lives on a drive that gets unplugged. That is a
        # RUNTIME state, not a broken install, and it must be recoverable
        # without restarting the companion -- see _demote_removable_root_
        # problem() for the startup half and _on_root_absent/_on_root_present
        # for the running half. Plain bools: they are written by the guard
        # thread and read by the tray/watcher/lane gates, and under the GIL a
        # bool assignment is the one thing that needs no lock.
        self._root_absent = False
        self._root_state = root_guard_mod.ROOT_UNKNOWN
        # When it last CHANGED (SYNC-15): `blocked.since` for the three root
        # reasons, and the one number that says whether a wedged mount has
        # been wedged for a minute or since last night.
        self._root_state_since = ""
        self._root_guard: Optional[root_guard_mod.RootGuard] = None
        # Once-per-episode gates: an unplugged drive is a state, not an event,
        # and the guard is free to re-fire (absent -> misplaced) within one.
        self._root_absent_announced = False
        self._root_misplaced_announced = False
        # The drive went with work still to go (CR-92, drive_reminder.py):
        # the first balloon names what was owed and a reminder repeats every
        # drive_reminder_minutes until it is back. Built here, before any
        # lane exists, for the same reason the breaker is: the guard's first
        # probe can fire on_absent before _start_lanes() ever runs, and that
        # is exactly when a remembered episode has to be picked back up.
        self._drive_reminder = drive_reminder_mod.DriveReminder(
            notify_fn=self._notify_tray,
            drive_phrase_fn=lambda: site_mod.drive_phrase(capitalised=True),
            interval=drive_reminder_mod.interval_seconds(cfg),
            state_path=(config_mod.resolved_log_path(cfg).parent / "state"
                        / drive_reminder_mod.STATE_FILENAME),
        )
        # The licence dialog is offered ONCE per run, on the same reasoning:
        # an unaccepted licence is a state the tray already shows, and a modal
        # that keeps coming back is how an editor learns to dismiss it without
        # reading. Declining leaves the tray item (Accept the licence
        # agreement…) as the way back.
        self._licence_prompted = False
        # ...but "offered once" has to mean once SHOWN, not once attempted
        # (CR-27, 2026-08-18). This flag is what _licence_watch() stops on:
        # it is set when the document has actually been put in front of
        # somebody (accepted, declined or dismissed), and stays False when
        # the attempt never got a window at all -- the popup-lock race that
        # left a whole machine parked with nothing on screen to explain it.
        self._licence_asked = False
        # One INFO line per run for that deferral, then DEBUG: the retry runs
        # every LICENCE_RETRY_SECONDS for as long as the editor keeps the
        # other window open, and the same sentence once a minute forever is
        # how a log stops being read (upgrade.py's _log_refusal precedent).
        self._licence_defer_logged = False
        # Pushed updates (2026-08-18): one attempt IN FLIGHT per request,
        # and one log line per refused version -- the request rides EVERY
        # report until the dashboard sees the new version, so both of these
        # would otherwise repeat every 30 seconds for as long as it stands.
        # `_applying` is the request key (version@requested_at) of the
        # attempt currently running; it is CLEARED when that attempt comes
        # back without swapping, and `_retry_at` then holds the next attempt
        # off. Before 0.9.41 it was set once and never cleared, so the first
        # "Can't update while a CCSync window is open" parked the push for
        # the life of the process (ultrareview 2026-08-19).
        self._pushed_update_applying = ""
        self._pushed_update_refused = ""
        self._pushed_update_announced = ""
        self._pushed_update_retry_at = 0.0
        # UNATTENDED updates (site [features] auto_update) get the same
        # treatment, and for the same reason (comp-app-core-4, 2026-08-21).
        # The auto path fired exactly once per offer -- on_available is only
        # called when the offered version CHANGES -- so a stand-down ("a
        # CCSync window is open", a consolidate) or a failed download left
        # the flag dead for that build until the tray was restarted. On the
        # machines §9 named as the reason for auto_update (an out-of-tree
        # popup takes the lock seconds after every launch, CR-27) the restart
        # loses the race too, so "unattended" meant "never".
        self._auto_update_version = ""
        self._auto_update_applying = ""
        self._auto_update_announced = ""
        self._auto_update_retry_at = 0.0
        # REL-8 / APP-5 (resilience sweep 2026-08-28): the PERSISTED half of
        # the same story. `_upgrade_attempts` is the ledger under
        # state/upgrade_attempts.json (loaded in run(), so a restart does not
        # reset the back-off), `_upgrade_reverted_from` is the build the
        # crash-loop guard took this machine off, and `_report_accepted` is
        # the one health signal both the revert marker and the rollback copy
        # wait on -- one report the dashboard actually took.
        self._upgrade_attempts: dict[str, Any] = {}
        self._upgrade_reverted_from = ""
        self._version_starts = 1
        self._report_accepted = threading.Event()
        # macOS took the tree away from us, rather than the editor unplugging
        # it: the ad-hoc-signed companion loses its Full Disk Access grant on
        # every self-upgrade (item 16). Checked once after an upgrade, read by
        # diagnostics.
        self._macos_access_blocked = False
        # The "local_root does not exist" problem demoted out of
        # config_problems, kept for diagnostics.
        self._root_demoted_problem: Optional[str] = None
        self._demote_removable_root_problem()

        # Managed mode: the dashboard decides which projects this editor
        # has and in what order (see selection.py / sync/sequencer.py).
        # Non-managed ("legacy") mode is the original whole-tree,
        # all-lanes-run-continuously behavior, unchanged.
        self._managed = bool(str(cfg.get("dashboard_url", "")).strip())
        self._lane_b_enabled = bool(cfg.get("lane_b_enabled", True))
        # Static fallback: what sync_enabled would be from config.toml's
        # mode/sync_enabled alone, used pre-login, when require_login is
        # off, or if the dashboard didn't return a role (see
        # _apply_identity_role()). self._sync_enabled itself may be
        # overridden dynamically by that method once a role is known.
        self._configured_sync_enabled = bool(cfg.get("sync_enabled", True))
        self._sync_enabled = self._configured_sync_enabled

        # Verified editor identity (addition; see identity.py). When
        # require_login is on, this -- not the raw editor_name config key --
        # is this companion's identity: sync lanes/the sequencer don't start
        # and the reporter doesn't report until the editor signs in (tray
        # "Sign in..."). See editor_identity()/start()/on_signed_in().
        self.identity = IdentityManager(cfg)
        self._require_login = bool(cfg.get("require_login", True))
        # Covers the case where identity.json already held a valid,
        # role-bearing identity from a previous run (companion restarted
        # while still signed in) -- the role must apply immediately, not
        # only after a fresh sign_in() call.
        self._apply_identity_role()
        # True once start() has actually started the lanes/sequencer --
        # lets on_signed_in() know whether it's doing the FIRST start or
        # re-starting after an earlier require_login gate.
        self._lanes_started = False

        # -- the two safety latches (COMMERCIAL_READINESS.md item 9) --------
        # Both are read HERE so their state is in hand before a single lane
        # exists: a breaker that only latches once lane B has run, or a halt
        # that only applies after the first report, is a latch an editor
        # clears by restarting the tray.
        #
        # They live in config_mod.CONFIG_DIR, beside machine.json and
        # upgrade_floor.json, NOT under <log dir>/state/ (APP-3, resilience
        # sweep 2026-08-28): state/ is what support sessions are told to
        # delete, and deleting it cleared the breaker only a human may reset
        # and a fleet halt an admin had set. lane_guard.adopt_legacy_latch
        # carries a live latch across the move, once.
        guard_state_dir = config_mod.resolved_log_path(cfg).parent / "state"
        latch_dir = config_mod.CONFIG_DIR
        self.lane_b_breaker = lane_guard.LaneBBreaker(
            lane_guard.adopt_legacy_latch(
                latch_dir / lane_guard.BREAKER_STATE_FILENAME,
                guard_state_dir / lane_guard.BREAKER_STATE_FILENAME,
            ),
            cfg,
            on_trip=self._notify_breaker_tripped,
        )
        self.halt = lane_guard.HaltState(lane_guard.adopt_legacy_latch(
            latch_dir / lane_guard.HALT_STATE_FILENAME,
            guard_state_dir / lane_guard.HALT_STATE_FILENAME,
        ))
        # ...and the third latch (SYS-5 / SYNC-7, resilience sweep
        # 2026-08-28): lane B stands down when the sync drive is nearly full.
        # Here, beside the other two, for the same reason and with the same
        # file-in-CONFIG_DIR discipline -- a park an editor clears by
        # restarting the tray would let the lane fill the disk on every
        # restart. No adopt_legacy_latch: this file has never existed
        # anywhere else.
        self.disk_floor = lane_guard.DiskFloorLatch(
            latch_dir / lane_guard.DISK_FLOOR_STATE_FILENAME,
            cfg,
            on_park=self._notify_disk_floor_park,
        )
        # Memoised `sync_guard.disk` (measured once per heavy report tick, not
        # once per light one) and the reason string the tray and the grid both
        # read -- see disk_report()/blocked_report().
        self._disk_snapshot: dict[str, Any] = {}
        self._disk_snapshot_at = 0.0
        self._blocked_since: dict[str, str] = {}
        # -- the sync engine's own supervisor (SYNC-17, 2026-08-18) ---------
        # Built here, beside the latches, for the same reason they are: its
        # incident state has to be in hand before lane C's first poll, or a
        # companion that self-upgrades every few hours resets the three-strike
        # counter forever and nobody is ever told. Driven from lane C's poll
        # (see _build_lanes) -- there is no thread of its own, on purpose.
        self.syncthing_supervisor = SyncthingSupervisor(
            guard_state_dir / SUPERVISOR_STATE_FILENAME,
            cfg,
            notify=self._notify_tray,
            suppressed=self._syncthing_supervision_suppressed,
        )
        # Overridden "Remove from this machine" actions awaiting a report.
        # Bounded: this is an audit trail on the wire, not a ledger -- the
        # WARNING in the log is the record that cannot be lost.
        self._removal_overrides: deque = deque(maxlen=20)

        self.lanes: list[LaneAdapter] = self._build_lanes()
        self.selection_client: Optional[SelectionClient] = None
        self.syncthing_admin: Optional[SyncthingAdmin] = None
        self.sequencer: Optional[Sequencer] = None
        if self._managed:
            self.selection_client = SelectionClient(
                cfg, self._state_dir, editor_name_fn=self.editor_identity,
                # The dashboard's selection endpoint now requires the signed
                # identity token alongside the shared dashboard token (the
                # rule /api/v1/report already followed) -- without this every
                # managed editor's fetch 401s and falls back to the cached
                # selection forever. Same getter the reporter uses.
                identity_token_fn=lambda: self.identity.token,
            )
            self.syncthing_admin = SyncthingAdmin(
                syncthing_url=cfg.get("syncthing_url", "http://127.0.0.1:8384"),
                api_key=cfg.get("syncthing_api_key", ""),
            )
            self.sequencer = Sequencer(
                self._lane_a, self._lane_b, self.syncthing_admin, self.selection_client, cfg,
                # sync-safety-2 (CR-48, CR-67 item 1): the once-per-pass shared
                # asset-folder reconcile RELEASES a paused folder, so without
                # this predicate a halt held the LUT, B-roll archive and music
                # libraries down for exactly one sequencer pass and then let
                # them sync again while every tray still said nothing was.
                # `self.halt` is built above, before _build_lanes, precisely so
                # this closure has something to read on the first pass.
                halted=lambda: self.halt.active,
            )

        # Local disk media manifest (per-project file rollups + per-file
        # lists for selected/current projects) -- refreshed on its own slow
        # background thread, never scanned inline. See manifest.py.
        self.manifest_cache = ManifestCache(
            cfg,
            get_selected_rels=self._selected_project_rels if self._managed else None,
            # An empty scan while the drive is out reads as a mass deletion on
            # the dashboard's presence view -- see ManifestCache.refresh_once.
            root_present_fn=self.root_is_present,
        )

        # Resolve media-pool BIN tree cache (get_media_tree()) -- refreshed
        # on its own slow background thread; see _refresh_media_tree_once().
        self.media_tree_refresh_interval = config_mod.coerce_numeric(cfg, "media_tree_refresh_interval", 120)
        self._media_tree_cache: dict[str, list[dict[str, Any]]] = {}
        # {file_path: (present, monotonic when probed)} -- see
        # _media_presence() (ops-efficiency-8, CR-66/CR-67 item 9). Touched
        # only from the media-tree thread, so it needs no lock of its own.
        self._media_presence_cache: dict[str, tuple[bool, float]] = {}
        self._media_tree_lock = threading.Lock()
        self._media_tree_stop_event = threading.Event()
        self._media_tree_thread: Optional[threading.Thread] = None
        self._media_tree_thread_error: Optional[str] = None
        # Stamped at the top of every media-tree iteration, for the same
        # reason the sequencer stamps one (SYS-2): a thread that is alive but
        # wedged inside one call is a different fault from a thread that died.
        self._media_tree_heartbeat = time.monotonic()
        # Built in start(), once the threads it supervises exist.
        self._lane_watchdog: Optional[LaneWatchdog] = None
        # Once-per-process latches for _classify_pool_once, mirroring the
        # watcher's own pair (see TimelineWatcher._offered_non_canonical) --
        # separate sets because the two loops have different lifecycles and
        # sharing them would let one loop swallow the other's first offer.
        self._pool_offered_non_canonical: set[str] = set()
        self._pool_warned_foreign: set[str] = set()
        # The non-canonical relink batch runs on its OWN thread (see
        # _handle_non_canonical): the watcher calls that handler inline from
        # poll_once, and one ReplaceClip per clip over a 158-clip backlog
        # parked the watcher thread for minutes (COMP-GUARD-5, 2026-08-14).
        # Single-flight with a pending list, so overlapping polls extend the
        # batch instead of stacking threads -- and nothing offered is dropped,
        # since each path is offered only once per process.
        self._canon_relink_lock = threading.Lock()
        self._canon_relink_pending: list[dict[str, Any]] = []
        self._canon_relink_busy = False
        # Once-per-process latch for _maybe_recover_stale_bridge -- the
        # replacement process starts unlatched, and a second restart from the
        # SAME process could only mean the first one failed to take.
        self._bridge_restart_started = False

        # _maybe_warn_scripting_dead: "Resolve is open but scripting is dead"
        # is the ONE broken state the editor can neither see nor is told
        # about -- every Resolve feature (the fixer, proxy attach, b-roll and
        # music inserts, YouTube import) is silently gone while Resolve looks
        # perfectly normal on screen, and it cost an editor's rig
        # a full session on 2026-08-12. So this one nags, on a timer, until
        # it is fixed or the editor silences it.
        #   _since        monotonic stamp of the first poll in the bad state
        #                 (None = not in it) -- the "held continuously"
        #                 clock, reset by ANY good poll;
        #   _warned_at    when the last dialog was shown;
        #   _silenced     the editor pressed STOP WARNING ME (cleared when
        #                 the link recovers, so the next breakage warns again);
        #   _open         a dialog is on screen right now -- the watcher polls
        #                 every 3 s and must not stack 100 of them.
        self._scripting_bad_since: Optional[float] = None
        self._scripting_warned_at: Optional[float] = None
        self._scripting_warn_silenced = False
        self._scripting_warn_open = False
        self._scripting_warn_lock = threading.Lock()
        # ONE clock for the whole interaction: the check runs on the watcher
        # thread and the re-stamp runs on the dialog thread when the window
        # closes, and the two comparing different time sources is only
        # invisible because both happen to be time.monotonic in production
        # (BpgLauncher/RateEstimator take theirs the same way).
        self._scripting_clock: Callable[[], float] = time.monotonic

        # The b-roll web UI's "Send to Resolve" loopback server
        # (broll_server.py), absorbed from the standalone broll-companion.
        # None whenever it is switched off or could not take its port --
        # which must never be more than a missing convenience.
        self._broll_server: Any = None

        # Shared LUT library (luts.py): the link manager plus the cached
        # stray scan the tray reads. Built here so stray_lut_count() is safe
        # to call before _start_lut_link() has run (the tray builds its menu
        # from the moment it starts).
        self._lut_links: Any = None
        self._stills: Any = None
        self._lut_lock = threading.Lock()
        self._stray_luts: list[dict[str, Any]] = []

        # Missing-proxy notifier + ffmpeg proxy generator (proxy_gen.py).
        # Built here, like the LUT block above, so proxy_gap()/proxy_coverage()
        # are safe to call from the moment the tray starts -- and behind its
        # own try, because an advisory feature must never be the reason a
        # companion fails to construct (the windowed exe vanishing with no
        # tray and no log line is this file's oldest failure mode).
        self.proxy_generator: Any = None
        try:
            self.proxy_generator = proxy_gen_mod.ProxyGenerator(
                cfg,
                self._state_dir,
                root_present_fn=self.root_is_present,
                paused_fn=self.is_paused,
                # config_problems, the same DEL-3 gate the lanes use: a
                # half-configured install must not be quietly encoding into a
                # tree whose local_root is wrong -- AND, since 2026-08-18,
                # b-roll indexing, which now takes precedence over proxy
                # generation (BROLL_INGEST_PLAN.md owner review (a)). The seam
                # answers a REASON there, so the tray can say "waiting:
                # indexing b-roll first" instead of the misconfigured line.
                blocked_fn=self._proxy_block_reason,
                get_selected_rels=self._selected_project_rels if self._managed else None,
                notify=self._notify_tray,
                idle_probe=idle_mod.make_idle_probe(True),
                resolve_running_fn=resolve_prefs_mod.resolve_is_running,
                # BRAW/R3D/CRM: ffmpeg cannot decode them, so the generator
                # counts them and hands them to BPG once its own queue is
                # empty. None on a machine without Resolve installed.
                bpg_launcher=bpg_mod.BpgLauncher(
                    cfg,
                    generation_enabled=config_mod.proxy_generation_enabled(cfg),
                    clock=time.monotonic,
                ),
            )
        except Exception:
            log.exception("failed to build the proxy generator")

        # B-roll ingest (broll_ingest.py, 2026-08-18): the editor drops clips
        # on the dashboard's b-roll page and THIS machine indexes them. Behind
        # its own try for the same reason the generator above is -- a feature
        # that runs when somebody drags something must never be why a
        # companion fails to construct -- and constructed AFTER it, because
        # the generator's blocked_fn reads this attribute (through
        # _proxy_block_reason, which is called per gate, not now).
        self.broll_ingestor: Any = None
        self._broll_ingest_deps: Any = None
        try:
            self._broll_ingest_deps = self._ingest_deps()
            if self._broll_ingest_deps is not None:
                self.broll_ingestor = broll_ingest_mod.BrollIngestor(
                    cfg,
                    self._state_dir,
                    deps=self._broll_ingest_deps,
                    root_present_fn=self.root_is_present,
                    paused_fn=self.is_paused,
                    blocked_fn=lambda: bool(self.config_problems),
                    idle_probe=idle_mod.make_idle_probe(True),
                    resolve_running_fn=resolve_prefs_mod.resolve_is_running,
                    notify=self._notify_tray,
                    # The window opens itself when a batch starts crunching
                    # (or downloading a model) -- the owner's requirement, and
                    # the moment there is something to watch.
                    show_window=self.show_ingest_progress,
                )
        except Exception:
            log.exception("failed to build the b-roll ingest orchestrator")
            self.broll_ingestor = None

        # Music ingest (music_ingest.py, 2026-08-18): the same object with the
        # music kind and the CLAP sidecar. Its own try for the same reason as
        # the b-roll one above, and its own state file, its own batch and its
        # own progress window -- the two run side by side, because music needs
        # no GPU and therefore never has to wait for b-roll.
        self.music_ingestor: Any = None
        self._music_ingest_deps: Any = None
        try:
            self._music_ingest_deps = self._ingest_deps(
                kind=music_ingest_mod.ingest_kinds.MUSIC_KIND)
            if self._music_ingest_deps is not None:
                self.music_ingestor = music_ingest_mod.MusicIngestor(
                    cfg,
                    self._state_dir,
                    deps=self._music_ingest_deps,
                    root_present_fn=self.root_is_present,
                    paused_fn=self.is_paused,
                    blocked_fn=lambda: bool(self.config_problems),
                    idle_probe=idle_mod.make_idle_probe(True),
                    resolve_running_fn=resolve_prefs_mod.resolve_is_running,
                    notify=self._notify_tray,
                    show_window=self.show_music_ingest_progress,
                )
        except Exception:
            log.exception("failed to build the music ingest orchestrator")
            self.music_ingestor = None

        # YouTube auto-import (youtube_import.py): files the clips the
        # dashboard's YouTube page downloaded into <project>\Youtube\<term>\
        # into the open Resolve project's Master/Youtube/<term> bins. Its own
        # try for the same reason as the block above -- a convenience bolted
        # onto the thing that keeps the fleet's media in sync must never be
        # the reason a companion fails to construct.
        self.youtube_importer: Any = None
        try:
            self.youtube_importer = youtube_import_mod.YoutubeImporter(
                cfg,
                root_present_fn=self.root_is_present,
                paused_fn=self.is_paused,
                # Deferred: self.watcher is constructed below. Same lambda as
                # the reporter's, and the same meaning -- None when Resolve is
                # closed, unreachable, or sitting on an ignored project.
                get_resolve_project=lambda: getattr(self.watcher, "last_resolve_project", None),
                # The dashboard's authoritative project -> tree-path mapping.
                # Absent in unmanaged mode, where the importer falls back to
                # the same token-overlap match the popup fixer uses.
                get_project_roots=(
                    self.selection_client.project_roots_result
                    if self.selection_client is not None else None
                ),
                import_fn=resolve_bridge.import_files_to_bin_path,
            )
        except Exception:
            log.exception("failed to build the youtube importer")

        # The yt-dlp sidecar (ytdlp_manager.py): the standalone binary that
        # will let this machine download its OWN YouTube clips instead of
        # waiting for the NAS to fetch and sync them. Built here, behind its
        # own try, for the same reason as the two blocks above -- and with a
        # sharper edge: this one downloads a binary off the internet, and a
        # third-party release being unreachable, renamed or unverifiable must
        # cost a log line and nothing else. Absent capability = the fleet's
        # long-standing server-side download path, which is what every editor
        # has today.
        self.ytdlp: Any = None
        try:
            self.ytdlp = ytdlp_mod.YtDlpManager(cfg)
        except Exception:
            log.exception("failed to build the yt-dlp sidecar manager")

        # Self-upgrade channel (upgrade.py): availability is fed by the
        # reporter's response callback below and by sign_in()'s verify
        # response; the tray surfaces it ("Update now") and apply() swaps
        # the exe + restarts via shutdown().
        self.upgrade = upgrade_mod.UpgradeManager(
            cfg,
            request_shutdown=self.shutdown,
            # offer_toast, not a hardcoded "Update available": the dashboard
            # advertises whatever it publishes as `current`, which may be
            # OLDER than what this machine runs (upgrade.py's "different, not
            # newer"). Calling a downgrade an update is how a rollback offer
            # becomes a one-click loss of everything the running build fixed
            # (seen live 2026-07-25: v0.4.5 offered "Update ... → v0.4.3").
            on_available=self._on_upgrade_available,
        )

        # New-project onboarding (project_setup.py): the report response's
        # `resolve_project_unmapped` flag drives a once-ever prompt + a
        # conditional tray item deep-linking to the dashboard's
        # /project-setup page. Dashboard-dependent, so managed mode only.
        self.project_setup: Optional[ProjectSetupPrompter] = None
        if self._managed:
            self.project_setup = ProjectSetupPrompter(
                cfg,
                self._state_dir,
                popup_lock=self._popup_active_lock,
                notify=self._notify_tray,
                # Deferred: self.watcher is constructed below.
                get_current_project=lambda: getattr(self.watcher, "last_resolve_project", None),
            )

        # ONE idle probe for the fleet-job half of this companion: the
        # capabilities section reports what it says, and the job runner gates
        # on what it says. Two probes would be two answers to "is anybody
        # here", and the machine would advertise itself as free while
        # refusing to work (or worse, the other way round).
        self._jobs_idle_probe = idle_mod.make_idle_probe(True)

        self.reporter = DashboardReporter(
            self.lane_statuses, cfg,
            get_queue_info=self._queue_info if self._managed else None,
            get_resolve_project=lambda: getattr(self.watcher, "last_resolve_project", None),
            get_local_manifest=self.manifest_cache.get,
            get_media_tree=self.get_media_tree,
            # effective_mode, NOT the raw config key: a signed-in role must
            # be what the dashboard sees, or a base-role machine with
            # mode="editor" left in config.toml reports the wrong mode.
            get_mode=self.effective_mode,
            # WP1 (MULTI_MACHINE_PLAN.md): who this COMPUTER is, so a person
            # with two machines can have two sync plans, and a renamed PC
            # keeps the one it had.
            get_machine_id=machine_mod.machine_id,
            get_syncthing_device_id=self.syncthing_device_id,
            get_editor_name=self.editor_identity,
            get_identity_token=lambda: self.identity.token,
            on_report_response=self._on_report_response,
            get_transport_health=self.transport_health,
            get_completions=self._pop_lane_completions,
            # Which of this machine's originals nobody else can see. A cached,
            # zero-I/O read (proxy_gen.coverage()), so it rides every tick
            # rather than only the heavy ones.
            get_proxy_coverage=self.proxy_coverage,
            # Same shape, same rules: "the clips you asked for are in your
            # bins" is a handful of counters, and the dashboard's YouTube page
            # wants to show it beside the download it started.
            get_youtube_import=self.youtube_import_status,
            # The b-roll batch this machine is crunching, if any. Same shape
            # and the same rules as the two above: a cached zero-I/O read that
            # rides every tick, because the page that started the batch and
            # the admin watching the fleet grid are both looking for exactly
            # this and neither should wait for a heavy cycle.
            get_broll_ingest=self.broll_ingest_status,
            get_music_ingest=self.music_ingest_status,
            # What this computer CAN DO (TIMELINE-CARDS-INTO-CCSYNC.md §4.3).
            # Every tick, light ones included: `idle_seconds` is what the
            # dashboard's job scheduler decides on and it changes second by
            # second.
            get_capabilities=self.job_capabilities,
            # The safety latches (item 9). Every tick, not just the heavy
            # ones: a tripped breaker and a halted machine are the two states
            # an admin must not learn about a report interval late.
            get_sync_guard=self.sync_guard,
            # Answers to the dashboard's file-move commands
            # (docs/FILE_MOVES.md): read lazily, the ledger is built below.
            get_file_moves_applied=self._file_move_results,
            # SYS-15b (2026-08-29): which clip-path changes this machine has
            # recorded, so an admin can name one to put back, and the answers
            # to the ones they already asked for. Names and counts only -- the
            # journals themselves name this editor's own paths and stay here.
            get_resolve_journals=self._resolve_journals,
            get_resolve_undo_applied=self._resolve_undo_results,
            # APP-1 (resilience sweep 2026-08-28): the ONE thing the reporter
            # says out loud. A revoked credential is a human's problem, and
            # nothing else on this machine can tell the editor about it -- the
            # lanes keep working and the tray stays green.
            notify=self._notify_tray,
        )
        # The fleet job runner (TIMELINE-CARDS-INTO-CCSYNC.md phase 0): work
        # the DASHBOARD queued that this machine may do while nobody is at it.
        # Its own thread and its own gate, exactly like the proxy generator
        # and the two ingestors, and behind its own try for the same reason --
        # a feature that runs when nobody is here must never be why a
        # companion fails to construct.
        self.job_runner: Any = None
        try:
            self.job_runner = jobs_runner_mod.JobRunner(
                cfg,
                editor_fn=self.editor_identity,
                identity_token_fn=lambda: self.identity.token,
                capabilities_fn=self.job_capabilities,
                # THE SAME PROBE the capabilities section reports from: what
                # this machine tells the dashboard and what it will agree to
                # do must not be two different answers.
                idle_probe=self._jobs_idle_probe,
                resolve_running_fn=resolve_prefs_mod.resolve_is_running,
                halted_fn=lambda: bool(self.halt.active),
                notify=self._notify_tray,
            )
        except Exception:
            log.exception("failed to build the fleet job runner")
            self.job_runner = None

        self.watcher = TimelineWatcher(
            local_root=cfg["local_root"],
            canonical_prefix=cfg["canonical_prefix"],
            poll_interval=config_mod.coerce_numeric(cfg, "poll_interval", 3),
            on_out_of_tree=self._handle_out_of_tree,
            on_mapping_warning=self._handle_mapping_warning,
            on_non_canonical=self._handle_non_canonical,
            on_foreign=self._handle_foreign,
            ignore_tracker=self.ignore_tracker,
            on_project_changed=self._on_resolve_project_changed,
            ignored_projects=cfg.get("ignored_resolve_projects"),
            # While the sync drive is out, nothing on the timeline can be
            # classified honestly: every clip is either OUT_OF_TREE (an
            # unfixable popup) or BAD_PREFIX (a warning storm), and neither
            # names the actual problem. The watcher stands down instead.
            root_present_fn=self.root_is_present,
            on_bridge_state=self._handle_bridge_state,
            # RES-10 (2026-08-28): a MISSING clip we ourselves moved on the
            # server's instruction is a one-click relink, not a DEBUG line.
            moved_lookup=self.file_moves.moved_to,
            on_moved_clip=self._on_moved_clip_missing,
        )

    def _on_report_response(self, resp: Any) -> None:
        """Fan the report response out to every consumer, isolating each --
        the upgrade channel and the new-project prompter both piggyback on
        the same reply."""
        # FIRST, and unconditionally: getting here at all means the dashboard
        # accepted a report from this build (APP-5 / REL-2). That is the
        # health signal the rollback copy waits on, and it is also what
        # clears the revert marker -- the payload that just landed carried
        # it, so the dashboard has now seen it once.
        self._note_report_accepted()
        try:
            self.upgrade.note_report_response(resp)
        except Exception:
            log.exception("upgrade.note_report_response failed")
        if self.project_setup is not None:
            try:
                self.project_setup.note_report_response(resp)
            except Exception:
                log.exception("project_setup.note_report_response failed")
        # A b-roll ingest cancel rides it too (BROLL_INGEST_PLAN.md §4.2):
        # the heartbeat's 410 is still the authoritative stop, this just makes
        # it arrive within one report interval instead of one heartbeat.
        if self.music_ingestor is not None:
            try:
                self.music_ingestor.note_report_response(resp)
            except Exception:
                log.exception("music_ingest.note_report_response failed")
        if self.broll_ingestor is not None:
            try:
                self.broll_ingestor.note_report_response(resp)
            except Exception:
                log.exception("broll_ingest.note_report_response failed")
        # Which fleet jobs this machine has been OFFERED (phase 0). Ids only:
        # the claim is a separate call whose compare-and-set is what actually
        # decides, so a duplicated or stale reply costs nothing.
        if self.job_runner is not None:
            try:
                self.job_runner.note_report_reply(resp)
            except Exception:
                log.exception("jobs_runner.note_report_reply failed")
        # The fleet halt rides the same reply (item 9, 2026-08-17) -- see
        # _apply_fleet_halt for why it is not its own request.
        self._apply_fleet_halt(resp)
        # ...and so does a PUSHED UPDATE (2026-08-18). AFTER
        # note_report_response above, which is what put the signed offer in
        # self.upgrade.available -- the push names a version, never a URL.
        self._apply_pushed_update(resp)
        # ...and an admin clearing this machine's lane B breaker (CR-45,
        # 2026-08-20).
        self._apply_resume_lane_b(resp)
        # ...and an admin asking this computer WHY it is not syncing (SYS-7,
        # resilience sweep 2026-08-28): the answer is build_diagnostics()'s
        # bundle, uploaded on the report channel, with no inbound connection
        # to this PC and nobody having to click anything on it.
        self._apply_diagnostics_request(resp)
        # A lane that has just fallen into `error` uploads its own bundle,
        # once per lane per hour (SYS-7). Here rather than in the lane because
        # this is the one place that runs on every report cycle and holds the
        # whole set of lane states at once.
        self._note_lane_error_diagnostics()
        # ...and files the admin moved on the server, which this machine's
        # copies have to follow (docs/FILE_MOVES.md, 2026-08-27).
        self._apply_file_moves(resp)
        # ...and an admin undoing a clip-path change CC Sync made here
        # (SYS-15b, 2026-08-29): the same journal the tray's own undo replays,
        # asked for from the dashboard because until now the only way to press
        # it was to be sitting at this computer.
        self._apply_resolve_undo(resp)
        # An unattended update that stood down (an open window, a consolidate,
        # a failed download) gets its next go here rather than waiting for a
        # NEW version to be published (comp-app-core-4, 2026-08-21).
        self._maybe_auto_update()

    def _on_resolve_project_changed(self, name: str) -> None:
        if self.project_setup is not None:
            try:
                self.project_setup.note_project_changed(name)
            except Exception:
                log.exception("project_setup.note_project_changed failed")
        # RES-10 (2026-08-28): the media pool that had to be walked to finish
        # a move may only have opened now. Nothing else ever revisited them.
        self._relink_pending_moves()

    def _build_lanes(self) -> list[LaneAdapter]:
        cfg = self.config
        # config.resolved_log_path(), NOT a raw Path(cfg["log_path"]): its own
        # docstring names _build_lanes as one of its three callers, but this
        # line never used it. `log_path = 5` raised TypeError right here --
        # inside CompanionApp.__init__, i.e. the windowed exe vanishing with
        # no tray and no log line -- and `log_path = ""` put every lane's
        # state dir (filter files, express lists) in Path("")/"state", which
        # is the process CWD: C:\Windows\system32 for a Run-key autostart
        # (AUDIT_3 M-7, the CORE-H2 twin).
        state_dir = config_mod.resolved_log_path(cfg).parent / "state"
        self._state_dir = state_dir
        # Moves the admin made on the server that this machine has followed,
        # or refused (docs/FILE_MOVES.md). Before the lanes: lane A reads it.
        self.file_moves = file_moves_mod.FileMoveLedger(Path(state_dir))
        self._file_move_answers: list[dict[str, Any]] = []
        # SYS-15b (2026-08-29): what this machine has already answered about
        # an admin's Resolve undo. Beside the file-move ledger, on disk, for
        # the same reason: a command redelivered after a restart is answered
        # from what happened the first time rather than replayed.
        self.resolve_undos = resolve_undo_mod.UndoLedger(Path(state_dir))
        self._resolve_undo_answers: list[dict[str, Any]] = []
        # RES-10: one relink offer per move per process. The watcher re-reports
        # the same MISSING clip every poll (3 s), and a dialog per poll is the
        # popup-storm shape comp-resolve-5 fixed one layer up.
        self._moved_clip_offered: set[Any] = set()
        # on_change hands per-project file events straight to the sequencer
        # (managed mode only) instead of triggering a debounced whole-tree
        # pass -- RcloneLane never falls back to its own debounced-run
        # behavior once on_change is set, so it must stay None in legacy
        # mode to preserve the original watchdog behavior.
        on_change = self._on_tree_change if self._managed else None
        lane_a = RcloneLane(
            direction=DIRECTION_UP,
            local_root=cfg["local_root"],
            remote=cfg["remote"],
            remote_root=cfg["remote_root"],
            rclone_path=cfg.get("rclone_path", "rclone"),
            transfers=int(config_mod.coerce_numeric(cfg, "transfers", 4)),
            scan_interval=config_mod.coerce_numeric(cfg, "scan_interval_up", 300),
            watch_debounce_seconds=config_mod.coerce_numeric(cfg, "watch_debounce_seconds", 10),
            state_dir=state_dir,
            on_change=on_change,
            # Any-depth project attribution for watchdog events (deferred:
            # the sequencer is constructed after the lanes).
            known_rels_fn=(
                (lambda: self.sequencer.known_rels() if self.sequencer else [])
                if self._managed else None
            ),
            # Transport tuning (sftp_chunk_size/concurrency/connections,
            # checkers, rclone_ignore_checksum, order_by_*) is read off cfg
            # by RcloneTuning.from_cfg -- without this the lane silently
            # keeps its own defaults and none of those keys do anything.
            cfg=cfg,
            # Lane A refusing to start its file watcher because the sync
            # drive's filesystem has stopped answering opens (MAC-12) is a
            # capability the editor loses, so it must reach the tray and not
            # only the log.
            on_watch_blocked=self._notify_watch_state,
            # Old paths of files the server has moved away from stay out of
            # lane A for a day, or the copy still here re-uploads itself.
            extra_excludes_fn=self.file_moves.recent_excludes,
        )
        lane_b = RcloneLane(
            direction=DIRECTION_DOWN,
            local_root=cfg["local_root"],
            remote=cfg["remote"],
            remote_root=cfg["remote_root"],
            rclone_path=cfg.get("rclone_path", "rclone"),
            transfers=int(config_mod.coerce_numeric(cfg, "transfers", 4)),
            scan_interval=config_mod.coerce_numeric(cfg, "scan_interval_down", 120),
            state_dir=state_dir,
            cfg=cfg,
            # Lane B is `sync` with --backup-dir: a proxy the editor made
            # locally and hasn't uploaded yet is moved out of the project
            # folder into .ccsync-trash. That used to happen in total
            # silence (AUDIT_3 L-12).
            on_trash=self._notify_trash_recovery,
            # The circuit breaker (COMMERCIAL_READINESS.md item 9,
            # 2026-08-17). Built HERE rather than left to the lane so the
            # tray's "Resume proxy download" action, the report field and the
            # lane all read one object -- and so its state file sits beside
            # every other piece of persisted companion state.
            breaker=self.lane_b_breaker,
            # The free-space floor, on the same terms as the breaker above
            # (SYS-5 / SYNC-7, resilience sweep 2026-08-28): one object, so
            # the tray line, the report field and the lane's own preflight
            # cannot disagree about whether proxy download is parked.
            disk_floor=self.disk_floor,
        )
        lane_c = SyncthingLane(
            base_url=cfg.get("syncthing_url", "http://127.0.0.1:8384"),
            api_key=cfg.get("syncthing_api_key", ""),
            expected_folder_ids=cfg.get("syncthing_folder_ids", []),
            # Late-bound on purpose: the lanes are built before the sequencer
            # exists, and the folder set changes with every selection fetch,
            # so this is evaluated fresh on every poll. Without it lane C
            # iterated the config's `syncthing_folder_ids` -- written as a
            # literal [] by every installer and populated by nothing -- so it
            # reported idle/queued=0/last_sync=now unconditionally for every
            # managed editor while carrying all the audio, GFX and subtitles
            # (AUDIT_2 L-6/UX-3).
            expected_folder_ids_fn=(
                (lambda: self.sequencer.expected_folder_slugs() if self.sequencer else [])
                if self._managed else None
            ),
            # SYNC-5 (resilience sweep 2026-08-28): late-bound for the same
            # reason as the folder list above. This is the one path by which
            # "that project's folder is parked without its filter list"
            # leaves the sequencer at all.
            unfiltered_folders_fn=(
                (lambda: self.sequencer.unconfirmed_slugs() if self.sequencer else [])
                if self._managed else None
            ),
            # SYNC-17 (2026-08-18): the poll that discovers "the API did not
            # answer" is also the thing that restarts the daemon and the
            # thing that must never then report idle. One object, one
            # verdict per poll.
            supervisor=self.syncthing_supervisor,
        )
        self._lane_a = lane_a
        self._lane_b = lane_b
        self._lane_c = lane_c
        # Late-bound because the supervisor is built before the lanes are
        # (its incident state has to be in hand first): this is how a start
        # attempt gets a verdict inside its own tick rather than 15 s later,
        # and it is bounded by the supervisor's own api_wait_seconds.
        self.syncthing_supervisor.probe = lane_c.api_reachable
        return [lane_a, lane_b, lane_c]

    # -- external-SSD root guard (root_guard.py) --------------------------
    def _demote_removable_root_problem(self) -> None:
        """Turn "local_root does not exist" into a runtime state, for the one
        local_root that legitimately comes and goes.

        config_problems is computed ONCE, in __init__, and _start_lanes()
        refuses to start on any entry in it (DEL-3). That is right for a
        typo'd remote_root and wrong for a Mac whose SSD was unplugged at
        login: the install is perfect, the drive is simply out, and the
        editor would find sync permanently dead until they thought to restart
        the companion -- with a tray line telling them the machine "isn't set
        up", which is not true and names nothing they can fix.

        Deliberately narrow. It demotes only when local_root-existence is the
        ONLY failing condition (anything else genuinely does need fixing
        first), only for the exact "does not exist" problem (a BLANK
        local_root is a real misconfiguration and stays one), and only for a
        root the machine has reason to believe is removable -- macOS +
        /Volumes, or a root the volume record knows. validate_config() itself
        is untouched: `ccsync-companion` run from a terminal, and the
        dashboard, must still be told the truth about the tree.

        The lanes then start on the first on_present() instead of at
        startup. Never raises: a failure here just leaves the problem in
        place, i.e. today's behaviour.
        """
        try:
            problems = list(self.config_problems or [])
            if len(problems) != 1:
                return
            problem = str(problems[0])
            if not problem.startswith(_LOCAL_ROOT_MISSING_PREFIX):
                return
            local_root = str(self.config.get("local_root", "") or "").strip()
            if not root_guard_mod.local_root_is_removable(local_root):
                return
            self.config_problems = []
            self._root_demoted_problem = problem
            self._root_absent = True
            self._root_state = root_guard_mod.ROOT_ABSENT
            log.warning(
                "local_root %s is not there at startup, but it is on a removable "
                "volume -- treating this as a disconnected drive rather than a "
                "broken install. Sync lanes will start on their own when it comes "
                "back.", local_root,
            )
        except Exception:
            log.exception("could not classify the missing local_root -- leaving it "
                          "as a config problem")

    def root_is_present(self) -> bool:
        """False only while the tree is KNOWN to be gone. Read by the watcher
        gate and the lane/scan refusals; "can't tell" is always True, because
        a probe that has not answered must not switch anything off."""
        return not self._root_absent

    def drive_unfinished_summary(self) -> str:
        """"2 uploads (2.3 GB left)" while the drive is out with work owed,
        else "". Read by the tray snapshot on every render: two attribute
        reads, no I/O."""
        reminder = getattr(self, "_drive_reminder", None)
        if reminder is None or not self._root_absent:
            return ""
        return str(reminder.summary or "")

    def _unfinished_before_pause(self) -> Optional[str]:
        """What was still to go at the moment the drive went, or None.

        Asked BEFORE _root_pause_lanes(): pausing rewrites every status to
        `paused`, which busy_lanes() rightly ignores. Through the power
        guards' PendingTracker, not busy_lanes() directly, so a lane stuck
        in `syncing` with nothing moving (CR-91) is not reported as an
        upload the editor must plug the drive back in for. Never raises: a
        failure here costs the detail, and the plain "Sync paused" balloon
        still goes out."""
        try:
            statuses = [lane.status() for lane in self.lanes]
            busy = self._pending_tracker.live_busy(statuses, self._lane_peer_states())
            work = drive_reminder_mod.unfinished_work(busy)
            return work.summary() if work is not None else None
        except Exception:
            log.exception("root guard: could not tell what was still syncing")
            return None

    def _start_root_guard(self) -> None:
        """Watch for the sync drive coming and going.

        Never fatal: a guard that fails to start leaves the companion exactly
        as it was before this existed -- the per-lane isdir() gates
        (rclone_lane, sequencer, manifest) are the defence that holds even
        with no guard at all."""
        if self._root_guard is not None:
            return
        try:
            self._root_guard = root_guard_mod.RootGuard(
                str(self.config.get("local_root", "") or ""),
                on_present=self._on_root_present,
                on_absent=self._on_root_absent,
            )
            self._root_guard.start()
        except Exception:
            log.exception("failed to start the sync-drive guard")

    def _on_root_absent(self, state: str) -> None:
        """The tree is gone (unplugged, ghost directory, or mounted at the
        wrong path). Stop cleanly and say so, ONCE.

        Pausing here deliberately does NOT touch self._paused: that is the
        editor's own tray toggle, and flipping it from a background thread
        would leave "Resume syncing" ticked with nobody having clicked
        anything -- and would then be un-resumed by the drive coming back."""
        try:
            if str(state) != self._root_state:
                self._root_state_since = datetime.now(timezone.utc).isoformat()
            self._root_state = str(state)
            # Judged before the pause below, and before _root_absent flips
            # (nothing here reads it, but the order is the point).
            unfinished = (self._unfinished_before_pause()
                          if not self._root_absent_announced else None)
            self._root_absent = True
            if not self._root_absent_announced:
                self._root_absent_announced = True
                log.warning(
                    "sync paused: local_root %s is not available (%s)",
                    self.config.get("local_root"), state,
                )
                # Three sentences for one event (CR-92): work was owed at
                # the moment it went -> the warning that names it, and the
                # half-hourly reminders after; nothing was owed but a
                # previous run recorded that something still is -> those
                # reminders carry on; otherwise the calm one-liner, which is
                # the common case and must stay calm.
                if unfinished:
                    self._drive_reminder.begin(unfinished)
                elif not self._drive_reminder.resume_remembered():
                    # SYNC-2: a wedged filesystem gets its OWN sentence. The
                    # drive is plugged in, so "is disconnected" sends the
                    # editor to check a cable that is fine and leaves the one
                    # thing that does fix it (a restart) unsaid.
                    if state == root_guard_mod.ROOT_NOT_ANSWERING:
                        self._notify_tray(
                            f"Sync paused: {site_mod.drive_phrase(capitalised=True)} is "
                            "not answering - reconnect it or restart this computer.",
                            "ccsync-companion",
                        )
                    else:
                        self._notify_tray(
                            f"Sync paused: {site_mod.drive_phrase()} is disconnected.",
                            "ccsync-companion",
                        )
            self._root_pause_lanes()
            if state == root_guard_mod.ROOT_MISPLACED:
                self._warn_root_misplaced()
        except Exception:
            log.exception("root guard: could not pause for a disconnected drive")

    def _on_root_present(self) -> None:
        """The tree is back. Re-record the volume, resume, and go now."""
        try:
            was_absent = self._root_absent
            self._root_absent = False
            if self._root_state != root_guard_mod.ROOT_PRESENT:
                self._root_state_since = datetime.now(timezone.utc).isoformat()
            self._root_state = root_guard_mod.ROOT_PRESENT
            self._root_absent_announced = False
            self._root_misplaced_announced = False
            # The drive is back, so whatever it went out owing is about to
            # be synced: end the reminders and forget the record. Also on
            # the first healthy sighting, which is what retires a record
            # left by a run that ended with the drive out.
            self._drive_reminder.clear()
            # Best effort, and only ever a no-op on Windows: this is what
            # keeps the recorded UUID/mount point true after a reformat or a
            # rename, which is what makes `misplaced` detectable next time.
            try:
                root_guard_mod.refresh_volume_record(
                    str(self.config.get("local_root", "") or "")
                )
            except Exception:
                log.debug("root guard: volume record refresh failed", exc_info=True)
            # The prefix probe memoises "does P:\ land under local_root" for a
            # couple of seconds, and every sample taken while the drive was
            # out said no. Drop them rather than let a stale one produce one
            # last BAD_PREFIX warning after the drive is back.
            try:
                paths_mod.clear_prefix_cache()
            except Exception:
                log.debug("could not clear the prefix cache", exc_info=True)
            if not was_absent:
                # The guard's first sighting on a healthy machine. Nothing was
                # paused, so there is nothing to resume and nothing to say.
                return
            log.info("local_root %s is back -- resuming sync",
                     self.config.get("local_root"))
            self._root_resume_lanes()
            self._notify_tray("Drive reconnected, sync resumed.", "ccsync-companion")
        except Exception:
            log.exception("root guard: could not resume after the drive came back")

    def _check_macos_volume_access(self) -> None:
        """Did this upgrade cost us macOS's permission to read the tree?

        The companion is ad-hoc signed, so as far as TCC is concerned every
        build is a different program and the Full Disk Access grant does not
        survive a self-upgrade (item 16). On a Mac whose root is an external
        volume the tree then simply stops being readable, and nothing in the
        product names the cause -- the drive is plugged in, the folder is
        right there, and every lane reports something that is not the truth.
        Signing with a stable identity is the real fix; this is the fallback
        the bug asks for until we can: say the sentence, name the setting.

        Called once, off the startup path, on a timer thread -- one listdir,
        only on darwin, only after an upgrade. A no-op everywhere else.
        """
        try:
            if not root_guard_mod.access_is_blocked(
                str(self.config.get("local_root", "") or "")
            ):
                return
            self._macos_access_blocked = True
            log.error(
                "macOS is blocking access to %s. CCSync is ad-hoc signed, so this "
                "update looks like a different program to macOS and its Full Disk "
                "Access grant did not carry over -- re-grant it in System Settings -> "
                "Privacy & Security -> Full Disk Access. Nothing has been deleted: "
                "the tree is unreadable, not gone.",
                self.config.get("local_root"),
            )
            self._notify_tray(
                "macOS is blocking access to the sync volume after the update. "
                "Re-grant CCSync Full Disk Access in System Settings → Privacy & "
                "Security → Full Disk Access.", "ccsync-companion")
        except Exception:
            log.exception("could not check whether macOS is blocking the sync volume")

    def _warn_root_misplaced(self) -> None:
        """The one case the editor MUST act on: the drive is mounted, but at
        /Volumes/<Name> 1 because a leftover empty directory occupies the
        real path. Nothing the companion can do fixes that -- adopting the
        numbered path would be worse, since it changes on every replug -- so
        this is a dialog, once per episode.

        Routed through the EXISTING popup plumbing (_popup_active_lock +
        popup.confirm_dialog on a daemon thread), because Tk permits one root
        in this process and every other dialog in the companion goes through
        the same door."""
        if self._root_misplaced_announced:
            return
        self._root_misplaced_announced = True
        local_root = str(self.config.get("local_root", "") or "")
        mount_point = root_guard_mod.mount_point_for(local_root) or local_root
        log.error(
            "the sync drive is mounted somewhere other than %s -- a leftover "
            "directory is occupying it", mount_point,
        )
        self._notify_tray(
            f"{site_mod.drive_phrase(capitalised=True)} is mounted at the wrong "
            f"path. Sync is paused until it is fixed. See the CCSync window.",
            "ccsync-companion")
        body = (
            f"{site_mod.drive_phrase(capitalised=True)} is plugged in, but macOS "
            f"mounted it somewhere other than {mount_point}.\n\n"
            f"That happens when an empty leftover folder is already sitting at "
            f"{mount_point}, so the drive gets a numbered name instead "
            f"({mount_point} 1). The numbered name changes every time you plug "
            f"in, so CCSync will not sync into it.\n\n"
            f"To fix it:\n"
            f"  1. Eject the drive.\n"
            f"  2. Delete the leftover empty folder at {mount_point}.\n"
            f"  3. Plug the drive back in and check it appears as {mount_point}.\n\n"
            f"Syncing resumes on its own once it does. Nothing has been deleted "
            f"and nothing has been synced to the wrong place."
        )
        threading.Thread(
            target=self._show_root_misplaced_dialog, args=(body,),
            name="ccsync-root-misplaced", daemon=True,
        ).start()

    def _show_root_misplaced_dialog(self, body: str) -> None:
        """The misplaced-drive dialog, on its own thread and under the popup
        lock like every other Tk root here. If a window is already open the
        toast above has already carried the message -- do not queue a modal
        the editor will meet minutes later with no context."""
        if not self._popup_active_lock.acquire(blocking=False):
            log.info("misplaced-drive dialog: another CCSync window is open -- "
                     "the tray notification carried the message instead")
            return
        try:
            popup.confirm_dialog(
                "CCSYNC.EXE: drive mounted at the wrong path", body, ok_label="OK",
            )
        except Exception:
            log.exception("could not show the misplaced-drive dialog")
        finally:
            self._popup_active_lock.release()

    def _root_pause_lanes(self) -> None:
        """Stop everything that writes to the tree, cleanly."""
        if self._managed and self.sequencer is not None:
            try:
                self.sequencer.pause()
            except Exception:
                log.exception("root guard: sequencer.pause() failed")
        elif self._lanes_started:
            try:
                self._stop_lanes()
            except Exception:
                log.exception("root guard: could not stop the lanes")
            self._lanes_started = False
        # The sequencer only owns the ROTATION; lane A's express upload runs
        # off the watchdog on its own timer (AUDIT_3 M-3).
        self._set_express_paused(True)

    def _root_resume_lanes(self) -> None:
        """The counterpart. Honours every OTHER reason sync might be down --
        the editor's own pause, the sign-in gate, a real config problem --
        because a returning drive is not consent to start syncing."""
        if self._paused:
            log.info("drive is back, but syncing is paused from the tray -- leaving it")
            return
        # RESTAMP before refusing. start()'s _root_absent branch deliberately
        # outranks the sign-in gate, so all three lanes read "PAUSED: your
        # <site> drive is disconnected" -- and with the drive back that
        # sentence names nothing the editor can fix, while the real blocker
        # (sign in / a config problem) appears nowhere in the menu. Every
        # sibling refusal path stamps its own reason; this one didn't
        # (COMP-CORE-7, 2026-08-14).
        if self.config_problems:
            self._mark_lanes_misconfigured()
            log.warning(
                "drive is back, but %d config problem(s) still stop syncing",
                len(self.config_problems),
            )
            return
        if self._login_gate_blocks_sync():
            self._mark_lanes_pending_login()
            log.info("drive is back, but nobody is signed in -- lanes stay down")
            return
        if not self._lanes_started:
            try:
                self._start_lanes()
            except Exception:
                log.exception("root guard: failed to start the sync lanes")
        elif self._managed and self.sequencer is not None:
            try:
                self.sequencer.resume()
            except Exception:
                log.exception("root guard: sequencer.resume() failed")
        self._set_express_paused(False)
        # Do not make the editor wait a whole rotation for the work that piled
        # up while the drive was out.
        if self._managed and self.sequencer is not None:
            try:
                self.sequencer.trigger_pass_now()
            except Exception:
                log.exception("root guard: could not trigger an immediate pass")

    def _mark_lanes_root_absent(self) -> None:
        for lane in self.lanes:
            try:
                with lane._lock:
                    lane._status.detail = _lane_root_absent_detail()
            except Exception:
                pass

    # -- watcher callbacks -----------------------------------------------
    def _local_root_is_broken(self) -> bool:
        """True when config validation flagged local_root itself. With a
        blank local_root, classify_path() returns OUT_OF_TREE for EVERY clip
        and Path("").resolve() == the process CWD, so one FIX ALL scatters
        the whole project's media into the autostart working directory
        (C:\\Windows\\system32 for a Run-key launch) and relinks Resolve
        there. The popup must not be offered at all in that state (AUDIT_2
        CORE-H1).

        A disconnected sync drive counts, and for the same reason with a
        different cause: every clip classifies OUT_OF_TREE, and a FIX ALL
        would copy the project's media into a ghost directory on the Mac's
        internal disk."""
        if self._root_absent:
            return True
        return any("local_root" in str(problem) for problem in self.config_problems)

    def _prune_popup_snooze(self, now: float) -> None:
        """Drop entries past their snooze window. Unbounded growth here was
        one interned path string per distinct out-of-tree clip ever seen,
        never evicted (AUDIT_2 §2-low).

        The snapshot + lock is not decoration: the popup thread writes this
        dict from _show_out_of_tree_popup while the watcher thread iterates
        it here (AUDIT_3 L-9)."""
        window = self.popup_snooze_seconds
        with self._popup_snooze_lock:
            stale = [k for k, at in list(self._popup_snooze.items()) if (now - at) >= window]
            for key in stale:
                self._popup_snooze.pop(key, None)

    def _popup_snooze_snapshot(self) -> dict[str, float]:
        with self._popup_snooze_lock:
            return dict(self._popup_snooze)

    def _popup_snooze_stamp(self, keys: list[str], now: float) -> None:
        with self._popup_snooze_lock:
            for key in keys:
                self._popup_snooze[key] = now

    def _handle_out_of_tree(self, items: list[dict[str, Any]]) -> None:
        from .watcher import _norm_key

        now = time.monotonic()
        self._prune_popup_snooze(now)
        snoozed = self._popup_snooze_snapshot()
        fresh = []
        for item in items:
            key = _norm_key(item.get("file_path", ""))
            shown_at = snoozed.get(key)
            if shown_at is not None and (now - shown_at) < self.popup_snooze_seconds:
                continue
            fresh.append(item)
        if not fresh:
            return

        if not bool(self.config.get("popup_enabled", True)):
            log.debug("popup suppressed (popup_enabled=false): %d clip(s) outside %s",
                      len(fresh), self.config.get("local_root"))
            return
        if self._local_root_is_broken():
            log.error(
                "popup suppressed: local_root is misconfigured, so every clip looks "
                "out-of-tree and FIX ALL would copy media outside the sync folder"
            )
            return

        log.info("popup: %d clip(s) outside %s", len(fresh), self.config.get("local_root"))
        # The popup runs a blocking Tk mainloop. Calling it inline froze the
        # WATCHER thread for as long as the dialog stayed on screen:
        # last_resolve_project stopped updating (the dashboard reported a
        # project already closed), no further out-of-tree detection happened,
        # and _stop_event went unobserved so shutdown/self-upgrade couldn't
        # stop the watcher cleanly (AUDIT_2 CORE-M2).
        threading.Thread(
            target=self._show_out_of_tree_popup, args=(fresh,), kwargs={"snooze": True},
            name="ccsync-popup", daemon=True,
        ).start()

    def _notify_trash_recovery(self, trash_dir: str) -> None:
        """Toast naming the recovery directory after a lane B run moved local
        files out of a project folder (see RcloneLane._notify_trash). The
        message must name the DIRECTORY, since that is the only action the
        editor can take."""
        self._notify_tray(
            f"Some files in your project folder weren't on the server, so CCSync moved "
            f"them (never deleted) to:\n{trash_dir}\nCopy anything you still need back "
            f"out of there.",
            "ccsync-companion: files moved to .ccsync-trash",
        )

    def _notify_breaker_tripped(self, reason: str) -> None:
        """One toast on the EDGE of a lane B trip (item 9, 2026-08-17).

        The sentence has to say three things or it produces a support call:
        nothing was deleted, uploads are still running, and there is a tray
        action that fixes it. The tray line and the dashboard alarm carry the
        same reason string."""
        self._notify_tray(
            "CCSync STOPPED downloading proxies as a safety measure:\n"
            f"{reason}\n"
            "Your uploads are still running and nothing has been deleted. When your "
            'admin says the server is fine, use the tray\'s "Resume proxy download".',
            "ccsync-companion: proxy download stopped",
        )

    def _notify_disk_floor_park(self, reason: str) -> None:
        """One toast on the EDGE of a free-space park (SYS-5 / SYNC-7,
        resilience sweep 2026-08-28).

        The three things this one has to say are different from the breaker's:
        which lane stopped, that uploads did not, and that it starts again by
        itself once there is room -- so nobody goes looking for a button that
        they do not need."""
        self._notify_tray(
            "CCSync is not downloading proxies:\n"
            f"{reason}\n"
            "Your uploads are still running. Free up some space and it starts again "
            "on its own.",
            "ccsync-companion: proxy download paused",
        )

    def _syncthing_supervision_suppressed(self) -> str:
        """Why the supervisor must NOT restart Syncthing right now, or "".

        SYNC-17 (2026-08-18). Every entry here is a state somebody chose:

          * the halt stops lanes A and B AND pauses every lane C folder, so
            starting the engine back up is starting the thing that was
            stopped on purpose (and, for a FLEET halt, the thing one editor's
            machine is not allowed to override);
          * pause is the tray's "my laptop is on a hotspot". Lane C keeps
            running through an ordinary pause, but an editor who paused and
            then killed Syncthing themselves gets to keep it dead;
          * sync_enabled=false is the base rig, which works straight off the
            NAS and has no lane C at all.

        A drive that is merely unplugged is deliberately NOT here: Syncthing
        with an absent folder is a folder error, which is honest, and the
        engine has to be running for the drive coming back to fix itself.
        """
        try:
            if self.halt.active:
                scope = self.halt.scope
                return (
                    "syncing is halted on this machine"
                    + (" by your administrator" if scope == lane_guard.HALT_SCOPE_FLEET else "")
                )
        except Exception:
            log.exception("supervision check: halt state unreadable")
            return "the halt state could not be read"
        if self._paused:
            return "syncing is paused from the tray"
        if not self._sync_enabled:
            return "syncing is switched off on this machine"
        return ""

    def _notify_watch_state(self, message: str) -> None:
        """Lane A's file watcher went away (or came back) because of the sync
        drive itself -- see RcloneLane._watch_root_answers (MAC-12).

        A toast, not a dialog: nothing here is a decision the editor makes in
        a window, and the one action that fixes it (replug the drive) is in
        the message. The lane latches this so a wedged drive costs one toast,
        not one per re-check.
        """
        self._notify_tray(message, "ccsync-companion")

    def _handle_mapping_warning(self, item: dict[str, Any]) -> None:
        path = item.get("file_path", "")
        # While the user has DELIBERATELY pointed P: at the server (the
        # tray's grade-swap), canonical paths resolving off-machine is the
        # chosen state, not a broken mapping. Same while a swap is MID-FLIGHT:
        # P: is briefly unmapped between the unmap and the remap, and warning
        # about that window scared an editor into thinking the swap broke
        # their setup (seen live 2026-07-26).
        if getattr(self, "_p_swap_busy", False):
            log.debug("mapping warning suppressed (P: swap in progress): %s", path)
            return
        try:
            if self.p_mapping_mode() == "server":
                log.debug("mapping warning suppressed (P: is grade-swapped to the server): %s", path)
                return
        except Exception:
            pass
        # The log line keeps the internals (that's what diagnostics are for);
        # the toast an editor actually reads must name the thing they can fix
        # (AUDIT_2 UX-16).
        log.warning(
            "clip on canonical prefix (%s) doesn't resolve under local_root (%s): %s",
            self.config.get("canonical_prefix"), self.config.get("local_root"), path,
        )
        # UX-15 (resilience sweep 2026-08-28). Both halves of the old
        # sentence were wrong for the person reading it: lanes A and B run
        # off local_root and are entirely unaffected (what is broken is
        # RESOLVE's view of the media), and an editor has no EDITOR_SETUP to
        # look step 6 up in. It also offered no way out, though
        # drive_swap.swap_to_local is exactly the repair -- which is now a
        # button in Settings.
        letter = self.canonical_prefix_label()
        self._notify_tray(
            f"Resolve is looking for your media on {letter} but {letter} is not "
            "pointing at your synced folder, so clips will show offline. Your "
            f"uploads and downloads are still running. Tray > Settings > REPAIR "
            f"{letter} NOW.",
            "ccsync-companion: mapping warning",
        )

    def _handle_non_canonical(self, items: list[dict[str, Any]],
                              user_initiated: bool = False) -> None:
        """Auto-relink in-tree clips stored under the LOCAL spelling.

        The 2026-08-12 Energy Transition incident's importing-side class:
        the file is here and healthy, only its stored spelling
        (`F:\\Creators_Club\\...`) is machine-private. The fix is a pure
        ReplaceClip to canon.local_to_canonical's spelling -- no copy, no
        question to ask the editor, so no popup. Refusals are logged; the
        watcher offers each path once per process, so a refusal never
        storms.

        HANDED OFF to a daemon thread, exactly as _handle_out_of_tree is and
        for the same reason: the watcher calls this synchronously from
        poll_once, every ReplaceClip waits on the Resolve menu and takes the
        API lock, and the batch is unbounded (158 clips in the incident that
        motivated the handler). Inline, that parked the watcher thread for
        minutes -- last_resolve_project stale on the dashboard, no further
        detection, and _stop_event unobserved so a Quit or self-upgrade could
        not stop the watcher cleanly (AUDIT_2 CORE-M2 / COMP-GUARD-5,
        2026-08-14).

        `user_initiated` is Tray -> Advanced -> Scan whole project asking, and
        it skips the rate limit below (comp-resolve-1, 2026-08-21): the
        limiter exists because nobody consented to the unprompted pass, and
        this is the consent. It is also the only thing that drains a burst
        the limiter refused -- which the refusal's own log line has been
        promising since the limiter shipped.
        """
        # "has an object OR a uid to find one with", not "has an object"
        # (library walk, 2026-08-26). The project-library walk carries no
        # fusionscript objects, so the old `is not None` test would have
        # dropped every clip here -- silently, and the pass would have
        # reported a clean sweep having relinked nothing. The object is
        # resolved at the moment of the ReplaceClip instead, in
        # _relink_non_canonical.
        fresh = [
            item for item in items
            if item.get("file_path")
            and resolve_bridge.media_pool_item_is_reachable(item)
        ]
        with self._canon_relink_lock:
            if fresh:
                if user_initiated:
                    # The scan re-offers paths the watcher already handed over
                    # (both producers latch once per process, this one does
                    # not), so a path already waiting must not be queued twice.
                    from .watcher import _norm_key

                    waiting = {_norm_key(str(item.get("file_path") or ""))
                               for item in self._canon_relink_pending}
                    fresh = [item for item in fresh
                             if _norm_key(str(item.get("file_path") or "")) not in waiting]
                self._canon_relink_pending.extend(fresh)
            if not self._canon_relink_pending:
                return
            if self._canon_relink_busy:
                return
            self._canon_relink_busy = True
        # RATE LIMIT, because nobody consented to this pass (item 9,
        # 2026-08-17). It rewrites the project database with no popup, and on
        # a machine whose canonical_prefix or local_root is wrong the same
        # rewrite is re-offered every sweep -- hundreds of ReplaceClips an
        # hour, plus a save point and a journal burst each. Checked HERE, at
        # the start of a burst, rather than per batch: a batch arriving while
        # the worker is draining extends that same burst (the single-flight
        # design above), and splitting one burst in half would be arbitrary.
        # The refused clips stay in _canon_relink_pending -- the watcher
        # offers each path once per process, so dropping them strands them.
        project = resolve_bridge.current_project_name()
        if not user_initiated and not resolve_journal.allow_automatic(project, "canon-relink"):
            with self._canon_relink_lock:
                self._canon_relink_busy = False
                waiting = len(self._canon_relink_pending)
            log.info(
                "non-canonical relink: holding %d clip(s) -- this project was "
                "auto-relinked less than %.0f minutes ago and the unprompted path "
                "is rate-limited. Tray → Advanced → Scan whole project runs it now",
                waiting, resolve_journal.AUTOMATIC_MIN_INTERVAL_SECONDS / 60.0,
            )
            return
        try:
            threading.Thread(
                target=self._canon_relink_loop, name="ccsync-canon-relink", daemon=True,
            ).start()
        except Exception:
            with self._canon_relink_lock:
                self._canon_relink_busy = False
            log.exception("could not start the non-canonical relink thread")

    def _canon_relink_loop(self) -> None:
        """Drain _canon_relink_pending until it is empty, then stand down.

        Draining (rather than one thread per batch) is what makes the
        single-flight flag safe: a poll landing mid-relink extends the work
        instead of being dropped, which matters because the watcher offers
        each path exactly once per process."""
        try:
            while not self._stop_event.is_set():
                with self._canon_relink_lock:
                    batch, self._canon_relink_pending = self._canon_relink_pending, []
                    if not batch:
                        self._canon_relink_busy = False
                        return
                self._relink_non_canonical(batch)
        except Exception:
            log.exception("non-canonical relink pass failed")
        finally:
            with self._canon_relink_lock:
                self._canon_relink_busy = False

    def _relink_non_canonical(self, items: list[dict[str, Any]]) -> None:
        """One batch of ReplaceClips, on the relink thread. Never raises.

        The rate limit for this unprompted path lives in
        _handle_non_canonical, at the start of a burst -- see the note there."""
        fixed = 0
        for item in items:
            if self._stop_event.is_set():
                # Teardown/self-upgrade: stop between clips rather than
                # holding the process open for the rest of a 158-clip batch.
                log.info("non-canonical relink stopped part-way: shutting down")
                break
            path = item.get("file_path", "")
            if not path:
                continue
            # Resolved HERE, immediately before the ReplaceClip, so a walk
            # that carried only uids still ends in a real relink and a clip
            # the pool no longer holds is skipped BY NAME rather than
            # counted as fixed (library walk, 2026-08-26).
            #
            # For an item the library reached INSIDE a multicam or compound
            # clip, this uid is the ANGLE's own pool clip, so the ReplaceClip
            # below repoints that angle rather than the container. That is
            # the intended behaviour and the only one that works: the
            # container has no media path of its own, and the angle is where
            # the non-canonical path actually is (item["via_multicam"] names
            # the multicam it was reached through).
            mpi = resolve_bridge.resolve_media_pool_item(item)
            if mpi is None:
                log.warning(
                    "non-canonical relink: no media pool item for %s (uid %r) "
                    "-- skipped",
                    item.get("clip_name") or path, item.get("media_pool_uid", ""),
                )
                continue
            try:
                target = canon.local_to_canonical(
                    path, self.config.get("local_root", ""),
                    self.config.get("canonical_prefix", ""),
                )
            except Exception:
                log.debug("canonical translation failed for %r", path, exc_info=True)
                continue
            if not target or canon.norm(str(target)) == canon.norm(path):
                continue
            result = resolve_bridge.replace_clip(
                mpi, str(target), tries=1, source="auto-canonical")
            if result.get("ok"):
                fixed += 1
                log.info("relinked non-canonical clip %s -> %s", path, target)
            else:
                log.warning(
                    "could not relink non-canonical clip %s -> %s: %s",
                    path, target, result.get("message"),
                )
        if fixed:
            self._notify_tray(
                f"Re-addressed {fixed} clip(s) to {self.config.get('canonical_prefix')} "
                "so they stay online for every editor.",
                "ccsync-companion",
            )

    def undo_last_relink(self) -> None:
        """Tray → Advanced → "Undo the last clip-path change CCSync made".

        The user-facing half of item 9's save point/journal (2026-08-17).
        Resolve's own Undo does not cover a scripted ReplaceClip, so without
        this an editor who watches the companion re-address 158 clips has no
        way back short of importing the exported `.drp` by hand. Runs on the
        tray's spawned thread like every other action; never raises.
        """
        try:
            # Describe the journal the undo will actually replay (comp-resolve-2,
            # CR-51, CR-67 item 9). describe_latest() with no project reads the
            # newest journal of ANY project, so an editor undoing in one project
            # was told the clip count of a pass made in another -- while
            # resolve_bridge.undo_last_relink now chooses the OPEN project's
            # journal and refuses a mismatch. The no-project fallback mirrors
            # the bridge's own fallback: a journal that names no project (the
            # pre-2026-08-21 shape) is still replayable, and this summary is
            # only ever shown when something was undone.
            project = resolve_bridge.current_project_name()
            summary = resolve_journal.describe_latest(project) if project else ""
            if not summary:
                summary = resolve_journal.describe_latest()
            result = resolve_bridge.undo_last_relink()
        except Exception:
            log.exception("undo of the last relink failed")
            self._notify_tray(
                "CCSync could not undo the last clip-path change. Tray → Open log, "
                "and send it to your admin.", "ccsync-companion: undo failed",
            )
            return
        message = result.get("message") or "Nothing to undo."
        if summary and result.get("undone"):
            message += f" (that pass changed {summary})"
        log.info("undo last relink: %s", message)
        self._notify_tray(message, "ccsync-companion: undo")

    def _handle_foreign(self, item: dict[str, Any]) -> None:
        """One tray warning per clip stored under ANOTHER machine's path.

        Nothing on this machine can fix it -- there is no local file to copy
        or relink -- but silence is how the Energy Transition project
        accumulated 200+ of these (2026-08-12). The companion on the machine
        that HAS the file auto-fixes it (NON_CANONICAL there); this warning
        exists so the clip's owner gets asked instead of nobody noticing.
        """
        path = item.get("file_path", "")
        name = item.get("clip_name") or os.path.basename(path) or "a clip"
        log.warning("clip stored under another machine's path (unfixable here): %s", path)
        self._notify_tray(
            f"\u201c{name}\u201d points at {path[:60]}\u2026 - a path that only exists on "
            "another editor's machine, so it can never sync or come online here. "
            "Whoever imported it should re-import it through the P: drive (their "
            "companion will offer the fix).",
            "ccsync-companion: foreign clip",
        )

    # -- popup plumbing (shared by the passive watcher and the manual
    # "Scan whole project" tray action) -------------------------------
    def _notify_tray(self, msg: str, title: str = "ccsync-companion") -> None:
        if self._tray_icon is not None:
            try:
                self._tray_icon.notify(msg, title)
            except Exception:
                log.debug("tray notify failed (backend may not support it)")

    def _queue_popup_batch(self, items: list[dict[str, Any]], snooze: bool) -> int:
        """Hold a batch that arrived while a popup was up. Returns the number
        of clips newly queued.

        Deduped against BOTH the batch on screen and everything already
        queued: the watcher re-reports the same out-of-tree clips on every
        poll (3 s), so without this an editor who left one popup open for ten
        minutes would close it into a couple of hundred identical dialogs --
        which is the opposite of being allowed to decide."""
        from .watcher import _norm_key

        fresh: list[dict[str, Any]] = []
        with self._popup_queue_lock:
            for item in items:
                key = _norm_key(item.get("file_path", ""))
                if key in self._popup_showing_keys or key in self._popup_queue_keys:
                    continue
                self._popup_queue_keys.add(key)
                fresh.append(item)
            if fresh:
                self._popup_queue.append({"items": fresh, "snooze": snooze})
        return len(fresh)

    def _take_popup_batch(self) -> Optional[dict[str, Any]]:
        """Next queued batch, or None. Also republishes `_popup_showing_keys`
        so anything arriving during THAT dialog dedupes against it.

        Skips clips the editor dismissed while the batch was waiting: SKIP in
        one dialog has to mean skipped, not "asked again in four seconds"."""
        from .watcher import _norm_key

        while True:
            with self._popup_queue_lock:
                if not self._popup_queue:
                    self._popup_showing_keys = set()
                    return None
                batch = self._popup_queue.pop(0)
                self._popup_queue_keys -= {
                    _norm_key(item.get("file_path", "")) for item in batch["items"]
                }
            items = [
                item for item in batch["items"]
                if not self.ignore_tracker.is_ignored(item.get("file_path", ""))
            ]
            if not items:
                continue
            with self._popup_queue_lock:
                self._popup_showing_keys = {
                    _norm_key(item.get("file_path", "")) for item in items
                }
            return {"items": items, "snooze": batch["snooze"]}

    def _show_out_of_tree_popup(self, items: list[dict[str, Any]], snooze: bool = False) -> None:
        """Build server_roots and show the popup for `items`. Blocks until
        the dialog (and anything queued behind it) closes -- popup.show_popup
        runs a Tk mainloop. Safe to call from any thread.

        `_popup_active_lock` still serializes the dialogs, because Tk permits
        only one live root in this process: a second one is what stranded the
        sign-in and update dialogs (AUDIT_2 CORE-M3 -> CORE-H8). What changed
        (2026-08-01) is the fate of a batch that loses that race. It used to
        be DROPPED with a "popup already open" toast that the watcher re-fired
        every 3 s, and every clip found while the editor was reading a dialog
        was silently lost. Now it is QUEUED and shown the instant the current
        popup closes: as many popups as there are batches, and the editor
        decides on every clip. The drain at the end closes the gap in that
        hand-off (see _drain_stranded_popup_batches).

        `snooze` stamps the batch's paths AFTER the lock is won. Stamping
        before the attempt meant a batch that merely LOST the lock race was
        snoozed the full 300 s despite never having been shown (AUDIT_2
        CORE-M2) -- a queued batch is stamped instead, which is not the same
        thing: it IS going to be shown, and the stamp is what stops the
        watcher re-queueing it on every poll while it waits."""
        from .watcher import _norm_key

        if not self._popup_active_lock.acquire(blocking=False):
            queued = self._queue_popup_batch(items, snooze)
            if snooze:
                self._popup_snooze_stamp(
                    [_norm_key(item.get("file_path", "")) for item in items],
                    time.monotonic(),
                )
            if queued:
                log.info("popup already open -- %d clip(s) queued for when it closes", queued)
            return
        self._run_popup_batches({"items": items, "snooze": snooze})
        # A batch queued in the gap between this thread's last
        # _take_popup_batch() (which saw an empty queue) and its release of
        # the lock had nobody left to show it -- and because its paths STAY in
        # _popup_queue_keys, _queue_popup_batch() dedupes every later sighting
        # of the same clips against a batch that will never be shown, so those
        # clips are lost for the rest of the session.
        self._drain_stranded_popup_batches()

    def _run_popup_batches(self, batch: Optional[dict[str, Any]]) -> None:
        """Show `batch` and everything queued behind it, then release the
        popup lock. THE CALLER MUST ALREADY HOLD `_popup_active_lock`."""
        from .watcher import _norm_key

        try:
            while batch is not None:
                with self._popup_queue_lock:
                    self._popup_showing_keys = {
                        _norm_key(item.get("file_path", "")) for item in batch["items"]
                    }
                self._show_one_popup(batch["items"], snooze=bool(batch["snooze"]))
                batch = self._take_popup_batch()
        finally:
            with self._popup_queue_lock:
                self._popup_showing_keys = set()
            self._popup_active_lock.release()

    def _drain_stranded_popup_batches(self) -> None:
        """Show anything left in the queue with no dialog thread to show it.

        Called after releasing the popup lock (by the popup path and by
        consolidate). A failed acquire is not a problem: whoever holds the
        lock now runs the same drain when they finish."""
        while True:
            with self._popup_queue_lock:
                if not self._popup_queue:
                    return
            if not self._popup_active_lock.acquire(blocking=False):
                return
            batch = self._take_popup_batch()
            if batch is None:
                self._popup_active_lock.release()
                return
            self._run_popup_batches(batch)

    def _show_one_popup(self, items: list[dict[str, Any]], snooze: bool) -> None:
        """One dialog, start to finish. The caller holds
        `_popup_active_lock`; returning here means the next queued batch (if
        any) gets its turn."""
        if snooze:
            from .watcher import _norm_key

            self._popup_snooze_stamp(
                [_norm_key(item.get("file_path", "")) for item in items],
                time.monotonic(),
            )
        server_roots, source = self._server_roots_result()
        if source == "unreachable":
            # Falling through to fixer.match_project_dir's token-overlap
            # guess means the SAME clip gets a different destination than
            # it had five minutes ago, silently (AUDIT_2 CORE-H9).
            log.error("popup suppressed: cannot reach the dashboard for project roots")
            self._notify_tray(
                "Can't reach the server right now, so CCSync doesn't know where this "
                "media belongs. It'll ask again once the connection is back. Nothing "
                "was changed.", "ccsync-companion")
            return

        popup.show_popup(
            items, self.config["local_root"], self.editor_identity() or "", self.ignore_tracker,
            project_prefix=self.config.get("active_project", ""),
            server_roots=server_roots,
            # Relinks must store the CANONICAL path (P:\...), never this
            # machine's physical local_root -- the Resolve project
            # travels, the drive layout does not (2026-07-26).
            canonical_prefix=str(self.config.get("canonical_prefix", "")),
        )

    def scan_whole_project(self) -> None:
        """User-initiated (tray) full media-pool scan for out-of-tree media.

        Unlike the passive watcher (which only sees clips cut onto the
        current timeline), this walks every bin in the media pool via
        resolve_bridge.get_media_pool_items -- so it also finds media that
        was imported but never edited in.

        Deliberately does NOT gate on popup_enabled (this is an explicit,
        one-off ask -- it must work even on a base rig with popups
        suppressed) and does NOT apply the passive popup's snooze filter
        (the user wants to see everything right now, including clips
        recently dismissed). Since APP-2 (resilience sweep 2026-08-28) it
        also CLEARS the session skip set first, for the same reason: an
        editor who pressed SKIP FOR NOW / IGNORE ALL this morning got "all
        media is in the tree" from this scan at noon, with 65 clips hidden
        behind an in-memory set that had no clear() caller anywhere in the
        product -- the only cure was restarting the tray, which nobody knew.
        The persisted FOLDER ignores (RES-12) survive: those are a standing
        decision with a [ FORGET ] in Settings, not a dismissal.

        Safe to call from the tray thread; blocks until any resulting popup
        is closed.
        """
        if self._root_absent:
            log.warning("scan whole project refused: the sync drive is disconnected")
            self._notify_tray(
                f"{site_mod.drive_phrase(capitalised=True)} is disconnected, so "
                f"CCSync can't tell where your media is. Plug it back in and try "
                f"again.", "ccsync-companion")
            return
        if self._local_root_is_broken():
            log.error("scan whole project refused: local_root is misconfigured")
            self._notify_tray(
                "CCSync's sync folder isn't set up correctly, so it can't tell which media "
                "is in the wrong place. Tray → Copy diagnostics for your admin.", "ccsync-companion")
            return
        result = resolve_bridge.get_media_pool_items()
        if not result.get("ok"):
            message = result.get("message", "unknown error")
            log.warning("scan whole project: %s", message)
            self._notify_tray(f"Whole-project scan failed: {message}", "ccsync-companion")
            return

        # AFTER the Resolve call and its refusals: a scan that could not run
        # must not silently spend the editor's skip decisions.
        cleared = self.ignore_tracker.session_count()
        if cleared:
            log.info("whole-project scan: clearing %d clip(s) skipped this session "
                     "-- this scan shows everything (APP-2)", cleared)
        self.ignore_tracker.clear()

        local_root = self.config.get("local_root", "")
        canonical_prefix = self.config.get("canonical_prefix", "")
        out_of_tree: list[dict[str, Any]] = []
        for item in result.get("items", []):
            path = item.get("file_path", "")
            if not path:
                continue
            if self.ignore_tracker.is_ignored(path):
                continue
            if classify_path(path, local_root, canonical_prefix) == OUT_OF_TREE:
                out_of_tree.append(item)

        # comp-resolve-1 (2026-08-21). The auto-relink limiter's refusal has
        # always said "Tray -> Advanced -> Scan whole project runs it now",
        # and this scan did not: the held clips sat in _canon_relink_pending
        # for the life of the process (both producers latch per path per
        # process, so nothing ever re-offered them) and stayed spelled for
        # this machine only -- Media Offline for every other editor who opens
        # the project. Draining it here is what makes that sentence true.
        # Nothing is re-classified: an in-tree clip is in the tree whatever
        # its spelling, which is what the message below says and what this
        # scan is for. user_initiated=True skips the limiter, because the
        # limiter guards the UNPROMPTED path and a tray click is the consent
        # it is waiting for.
        self._drain_held_relinks()

        if not out_of_tree:
            # The folder ignores are named here because "all media is in the
            # tree" is not true of a machine that has been told to look past
            # a folder, and this is the one screen where the editor asked.
            folders = self.ignore_tracker.folder_count()
            extra = (f" ({folders} folder(s) are set to be left alone - "
                     f"Settings shows them)" if folders else "")
            log.info("whole-project scan: all media is in the tree%s", extra)
            self._notify_tray(
                f"Whole-project scan: all media is in the tree{extra}",
                "ccsync-companion")
            return

        log.info("whole-project scan: %d clip(s) outside %s", len(out_of_tree), local_root)
        self._show_out_of_tree_popup(out_of_tree)

    def _drain_held_relinks(self) -> None:
        """Run the non-canonical relinks the rate limiter deferred, now.

        comp-resolve-1 (2026-08-21). Never raises: this is a side errand of
        whatever the editor actually asked for."""
        try:
            with self._canon_relink_lock:
                waiting = len(self._canon_relink_pending)
            if not waiting:
                return
            log.info("whole-project scan: re-addressing %d held clip(s) that the "
                     "automatic pass deferred", waiting)
            self._handle_non_canonical([], user_initiated=True)
        except Exception:
            log.exception("could not drain the held non-canonical relinks")

    def _server_roots_result(self) -> tuple[Optional[dict[str, str]], str]:
        """(mapping, source) -- source "unreachable" means DO NOT resolve a
        destination from a local guess (AUDIT_2 CORE-H9)."""
        client = self.selection_client
        if client is None:
            return None, "none"
        getter = getattr(client, "project_roots_result", None)
        if getter is not None:
            try:
                return getter()
            except Exception:
                log.exception("project_roots_result() failed")
                return None, "unreachable"
        if hasattr(client, "get_project_roots"):
            try:
                return client.get_project_roots(), "live"
            except Exception:
                log.exception("get_project_roots() failed")
                return None, "unreachable"
        return None, "none"

    def _server_roots(self) -> Optional[dict[str, str]]:
        mapping, _source = self._server_roots_result()
        return mapping

    def consolidate_in_flight(self) -> bool:
        """True while consolidate_project() is between the user's confirm and
        the end of its lane runs -- read by the self-upgrade path, which must
        not swap the exe and exit out from under a multi-hour copy (AUDIT_2
        CORE-H8)."""
        return self._consolidate_active

    def consolidate_project(self) -> None:
        """User-initiated (tray): onboard a pre-existing project. Scans the
        whole media pool, plans copying every out-of-tree clip into the
        canonical project folder, dry-runs both rclone lanes against the NAS
        for a reconciliation report, and -- on confirm -- consolidates
        (copy+relink) then uploads originals and downloads proxies for the
        open project. Runs on the tray thread.

        The popup lock is held ONLY for the dialogs, never across the copy or
        the rclone runs: it used to be held for the whole (potentially
        multi-hour) operation, during which every watcher popup was dropped
        with "A popup is already open" and the new-project prompt starved
        (AUDIT_2 CORE-M13). `_consolidate_lock` is what actually keeps two
        consolidates from overlapping.
        """
        from . import consolidate

        # This runs real rclone lanes against the tree, so it must respect
        # the same three gates every other sync path does -- it used to run
        # lane A even on a base rig with a blank remote_root, and even while
        # the user had Pause ticked (AUDIT_2 CORE-M13).
        if not self._sync_enabled:
            log.info("consolidate ignored: sync_enabled=false on this machine")
            self._notify_tray(
                "This machine works directly off the NAS, so there's nothing to copy in.",
                "ccsync-companion",
            )
            return
        if self._paused:
            self._notify_tray(
                "Syncing is paused. Resume it from the tray first.", "ccsync-companion")
            return
        if self.config_problems:
            self._notify_tray(
                "CCSync isn't fully set up on this machine yet, so nothing can be copied in. "
                "Tray → Copy diagnostics for your admin.", "ccsync-companion")
            return
        if self._root_absent or self._local_root_is_broken():
            # SYNC-6 (2026-08-11): the fourth gate, missing here while both
            # sibling copy-and-relink entry points had it (scan_whole_project).
            # _root_absent is invisible to a config_problems check --
            # _demote_removable_root_problem strips it at startup -- so with an
            # external SSD unplugged fixer.fix_clip (which refuses only a BLANK
            # local_root) would mkdir the tree onto the boot volume, copy the
            # originals there and relink Resolve to canonical P:\... paths that
            # lane A then correctly refuses to upload.
            log.warning("consolidate refused: the sync drive is disconnected or misconfigured")
            self._notify_tray(
                f"{site_mod.drive_phrase(capitalised=True)} is disconnected, so "
                f"CCSync can't copy media in. Plug it back in and try again.",
                "ccsync-companion")
            return
        if not self._consolidate_lock.acquire(blocking=False):
            self._notify_tray("Already copying a project's media in. Let it finish.",
                              "ccsync-companion")
            return
        try:
            self._consolidate_active = True
            self._consolidate_project_inner(consolidate)
        finally:
            self._consolidate_active = False
            self._consolidate_lock.release()

    def _consolidate_project_inner(self, consolidate) -> None:
        result = resolve_bridge.get_media_pool_items()
        if not result.get("ok"):
            message = result.get("message", "unknown error")
            log.warning("consolidate: %s", message)
            self._notify_tray(f"Consolidate failed: {message}", "ccsync-companion")
            return

        local_root = self.config.get("local_root", "")
        canonical_prefix = self.config.get("canonical_prefix", "")
        resolve_project = result.get("project_name", "") or ""
        server_roots, roots_source = self._server_roots_result()
        if roots_source == "unreachable":
            log.error("consolidate: cannot reach the dashboard for project roots -- refusing")
            self._notify_tray(
                "Can't reach the server, so CCSync doesn't know where this project lives. "
                "Nothing was copied or uploaded. Try again once you're back online.",
                "ccsync-companion")
            return

        out_of_tree = [
            item for item in result.get("items", [])
            if item.get("file_path")
            and not self.ignore_tracker.is_ignored(item["file_path"])
            and classify_path(item["file_path"], local_root, canonical_prefix) == OUT_OF_TREE
        ]

        project_prefix = self.config.get("active_project", "")
        if server_roots and resolve_project:
            project_prefix = server_roots.get(resolve_project.strip().lower(), project_prefix)
        # subtree for the rclone dry-run/upload: the project's tree location,
        # or the whole tree if we can't pin one down.
        subpath = project_prefix.strip("/").replace("\\", "/") or None

        # HARD ABORT before the dialog, not after it. reconcile_with_nas()
        # already refuses a None subpath (D-2), but line 489 used to call
        # self._lane_a.run_once(None) regardless, which builds
        # `rclone copy <the whole local_root>` to the NAS -- unquantified and
        # unmentioned by the dialog the user consented to (AUDIT_2 CORE-C2).
        if subpath is None:
            log.error("consolidate: no active project resolved -- refusing whole-tree consolidate")
            self._notify_tray(
                "CCSync can't tell which project this is, so it won't copy anything in. "
                "Open the project in Resolve and set it up on the dashboard first.",
                "ccsync-companion",
            )
            return

        # SECOND LAYER on the dashboard's rel_path (selection.py drops unsafe
        # project_roots entries; this is the assertion right before the lanes
        # run). `subpath` is "Projects/<rel>" built from a dashboard-supplied
        # rel_path, or from config's active_project -- both hand-editable,
        # neither validated here before. It becomes lane A's SOURCE, so a
        # traversal turns this into `rclone copy <somewhere outside the tree>
        # nas:...`, uploading whatever lives there (AUDIT_3 H-2). Same
        # containment check the popup fixer applies to its destination.
        if not self._subpath_is_contained(subpath):
            log.error(
                "consolidate: refusing -- %r does not resolve under local_root %r",
                subpath, local_root,
            )
            self._notify_tray(
                "CCSync got a project location that points outside your sync folder, so "
                "nothing was copied or uploaded. Tray → Copy diagnostics for your admin.",
                "ccsync-companion",
            )
            return

        results: list[dict[str, Any]] = []
        if not self._popup_active_lock.acquire(blocking=False):
            self._notify_tray("A popup is already open. Close it first.", "ccsync-companion")
            return
        try:
            plan = consolidate.plan_local_consolidation(
                out_of_tree, local_root, self.editor_identity() or "",
                project_prefix, server_roots,
            )
            self._notify_tray("Checking the NAS…", "ccsync-companion: consolidate")
            reconcile = consolidate.reconcile_with_nas(self.config, subpath, self._state_dir)
            report = consolidate.build_report(plan, reconcile)
            if not reconcile.get("ok"):
                # Every number in the report is unknown, and both lane runs
                # below are gated on this anyway -- do not offer a button
                # that can only do something we couldn't describe.
                log.warning("consolidate: NAS check failed (%s) -- not offering the copy",
                            reconcile.get("error"))
                self._notify_tray(
                    "Couldn't check the server, so nothing was copied or uploaded. "
                    "Tray → Copy diagnostics for your admin.", "ccsync-companion")
                return
            if plan["count"] == 0 and (reconcile["uploads"] or {}).get("count", 0) == 0:
                self._notify_tray("Nothing to copy in: this project is already tidy.",
                                  "ccsync-companion")
                return
            if not popup.confirm_dialog(
                "COPY THIS PROJECT'S MEDIA IN", report, ok_label="COPY & UPLOAD"
            ):
                log.info("consolidate: cancelled by user")
                return
            log.info("consolidate: copying %d clip(s) into %s",
                     plan["count"], project_prefix or "tree")
            # UX-10: this used to be a MULTI-HOUR silence between two toasts,
            # with no progress and no cancel -- even though run_consolidation
            # already accepted a progress_fn and rclone_lane already populates
            # bytes_done/speed_bps/eta_seconds every 10 s. One window covers
            # both phases: the local copy, then the lane A upload.
            #
            # STILL UNDER THE POPUP LOCK, deliberately: this REVERSES half of
            # AUDIT_2 CORE-M13, and that reversal was reviewed and kept -- do
            # not "restore" the early release. ProgressWindow opens a real tk.Tk()
            # ROOT and keeps it for the whole copy, so releasing the lock first
            # left a live root with the lock free -- any watcher popup landing
            # in that window opened a SECOND root, which is the exact condition
            # the lock exists to prevent (CORE-M3 -> CORE-H8: a wedged Tcl
            # interpreter, and for PopupDialog a batch that gets auto-ignored
            # and never re-offered this session). What made holding it
            # unaffordable in CORE-M13 was that a losing batch was DROPPED;
            # since 2026-08-01 it is QUEUED instead, and _drain_stranded_popup_
            # batches() below shows the queue the moment this window closes.
            window = popup.ProgressWindow(
                "COPYING THIS PROJECT'S MEDIA IN",
                "Your original files are COPIED, never moved. Everything stays where it is.",
            )

            def _work(publish, should_stop):
                # window.control carries [ SKIP THIS FILE ] / [ CANCEL ALL ]
                # down to the per-chunk abort check inside the copy;
                # should_stop is still the between-files
                # [ STOP AFTER THIS FILE ].
                results.extend(consolidate.run_consolidation(
                    plan["ops"], local_root, state_fn=publish, should_stop=should_stop,
                    # getattr: a progress-window double without the newer
                    # attribute (tests, and anything injected) must degrade to
                    # "no mid-file controls", not crash the copy.
                    control=getattr(window, "control", None),
                    canonical_prefix=str(self.config.get("canonical_prefix", "")),
                ))
                if should_stop():
                    return
                self._consolidate_upload_phase(
                    subpath, reconcile, consolidate, publish, should_stop)

            window.run(_work)
        finally:
            self._popup_active_lock.release()
        # Anything the watcher found while that window was up is queued, not
        # lost -- show it now rather than making the editor wait for the next
        # 300 s snooze cycle.
        self._drain_stranded_popup_batches()

        # Skipped-by-the-user is its own outcome: fix_clip has already deleted
        # the half-copied file and relinked nothing, so it is neither a
        # success nor a malfunction and must not be reported as either.
        skipped = [r for r in results if r.get("aborted")]
        failures = [r for r in results if not r.get("ok") and not r.get("aborted")]
        skipped_part = f", {len(skipped)} skipped by you" if skipped else ""
        if failures:
            log.warning("consolidate: %d/%d copies failed", len(failures), len(results))
            self._notify_tray(
                f"{len(results) - len(failures) - len(skipped)}/{len(results)} copied in"
                f"{skipped_part}, {len(failures)} failed. "
                f"Tray → Copy diagnostics for your admin.",
                "ccsync-companion")
            # SYNC-12 (2026-08-11): this branch fell through to the
            # "Copy & upload finished" toast below, so the editor read the
            # failure report and then, a beat later, an unqualified success.
            return
        elif window.should_stop():
            done = len(results) - len(skipped)
            # Same tolerance as `control` above: an older window double has
            # no cancelled() and must read as the graceful stop.
            verb = "Cancelled" if getattr(window, "cancelled", lambda: False)() else "Stopped"
            self._notify_tray(
                f"{verb}: {done} of {plan['count']} copied in{skipped_part}, the rest "
                f"were left alone. Nothing was moved or deleted.", "ccsync-companion")
            return
        self._notify_tray(
            f"Copy & upload finished ({len(results) - len(failures) - len(skipped)} "
            f"copied in{skipped_part})." if skipped else "Copy & upload finished.",
            "ccsync-companion: consolidate")

    def _subpath_is_contained(self, subpath: str) -> bool:
        """True when `local_root/<subpath>` really lands under local_root.

        Mirrors fixer._dest_dir_is_contained (which guards the popup's
        editable destination) for the OTHER path a rel_path reaches: the
        subpath handed to lane A/B run_once. Never raises -- a blank
        local_root, an unresolvable path or a different drive is False, i.e.
        "refuse"."""
        root = str(self.config.get("local_root", "") or "").strip()
        if not root or not str(subpath or "").strip():
            return False
        try:
            return _dest_dir_is_contained(
                Path(root) / subpath, Path(root).resolve(), subpath)
        except Exception:
            log.debug("containment check failed for %r", subpath, exc_info=True)
            return False

    def _consolidate_upload_phase(self, subpath, reconcile, consolidate, publish, should_stop):
        """Lane A upload + optional lane B pull, rendering the same progress
        line from LaneStatus (UX-10). Runs on the ProgressWindow's worker
        thread, so it may only call `publish`."""
        stop_poll = threading.Event()

        def _poll_lane_a():
            while not stop_poll.wait(2.0):
                try:
                    status = self._lane_a.status()
                except Exception:
                    continue
                publish({
                    "headline": (
                        f"Uploading to the server: {status.current_project or 'this project'}"
                    ),
                    "name": "",
                    "file_bytes_done": status.bytes_done or 0,
                    "file_bytes_total": status.bytes_total or 0,
                    "batch_bytes_done": status.bytes_done or 0,
                    "batch_bytes_total": status.bytes_total or 0,
                    "speed_bps": status.speed_bps,
                    "eta_seconds": status.eta_seconds,
                    "index": 0,
                    "total": 0,
                })

        publish({"headline": "Uploading originals to the server…", "name": "",
                 "index": 0, "total": 0})
        poller = threading.Thread(target=_poll_lane_a, name="ccsync-consolidate-poll",
                                  daemon=True)
        poller.start()
        try:
            self._lane_a.run_once(subpath)
        except Exception:
            log.exception("consolidate: lane A upload failed")
        finally:
            stop_poll.set()
            poller.join(timeout=3.0)
        if self._lane_b_enabled and not consolidate.lane_b_allowed(reconcile):
            # The dry run saw deletions: `rclone sync` down would delete local
            # proxy files the NAS doesn't have (D-1) -- the report already
            # told the user lane B is being skipped.
            log.warning("consolidate: skipping lane B pull -- dry run reported deletions")
        elif self._lane_b_enabled:
            publish({"headline": "Downloading proxies from the server…", "name": "",
                     "index": 0, "total": 0})
            try:
                self._lane_b.run_once(subpath)
            except Exception:
                log.exception("consolidate: lane B proxy pull failed")

    # -- sequencer hand-off (managed mode) -----------------------------------------------
    def _on_tree_change(self, rel: str) -> None:
        if self.sequencer is None:
            return
        try:
            self.sequencer.notify_change(rel)
        except Exception:
            log.exception("_on_tree_change: sequencer.notify_change(%s) failed", rel)

    def _queue_info(self) -> tuple[list[str], Optional[str]]:
        if self.sequencer is None:
            return [], None
        return self.sequencer.queue_slugs, self.sequencer.current_slug

    def _selected_project_rels(self) -> Optional[set]:
        """Project rels ("<year>/<series>/<project>") the dashboard has
        selected for this editor -- passed to ManifestCache so per-file
        lists are only built for projects actually being synced. None (all
        rollup-only) when not in managed mode or the sequencer has no
        selection yet."""
        if self.sequencer is None:
            return None
        return set(self.sequencer.rel_to_slug.keys())

    # -- media pool BIN tree (dashboard reporting) -----------------------------------------------
    @staticmethod
    def _classify_media_kind(file_path: str) -> str:
        parts = Path(file_path).parts if file_path else ()
        if any(p.lower() == "proxy" for p in parts):
            return "proxy"
        ext = os.path.splitext(file_path)[1].lower()
        if ext in VIDEO_EXTS:
            return "original"
        return "other"

    def get_media_tree(self) -> dict[str, list[dict[str, Any]]]:
        """Cached getter -- cheap/non-blocking, mirrors lane_statuses().

        KEYING DECISION: the media pool API only ever exposes the CURRENTLY
        OPEN Resolve project, so this dict has at most one key. Resolve's
        scripting API only gives us that project's live NAME (GetName()),
        not its tree year/series/project rel path -- so media_tree is keyed
        by the resolve_project NAME string, same as the reporter's
        "resolve_project" field. The dashboard already resolves a live
        Resolve project NAME to a tree rel path for sticky-root matching
        (see selection.py's get_project_roots()), so it does the same
        NAME -> project mapping here rather than this module guessing it.
        """
        with self._media_tree_lock:
            return dict(self._media_tree_cache)

    # How long a clip that WAS on disk is believed without another stat().
    # Not forever: a file really can go away, and a media tree that never
    # notices is worse than a slow one. Fifteen minutes is ~7 media-tree
    # cycles at the default interval, so a deletion still surfaces well
    # inside the ten-minute report window CR-62 opened up.
    MEDIA_PRESENCE_TTL_SECONDS = 900.0

    def _media_presence(self, paths: list[str]) -> dict[str, bool]:
        """{file_path: present} for this pass, re-statting as little as it can.

        ops-efficiency-8 (CR-66, CR-67 item 9, 2026-08-21): a wired rig's media
        pool lives on the SMB share, and this walk stat()ed EVERY clip in it
        every media_tree_refresh_interval (120 s by default) -- a thousand-clip
        project is a thousand round trips a minute over SMB to answer a
        question whose answer almost never changes. The answer that DOES change
        is "absent", because that is the one a lane B download flips, so an
        absent path (and a path never seen before) is probed every pass while a
        present one is trusted for MEDIA_PRESENCE_TTL_SECONDS.

        Pruned to the paths in this pass, so closing a project does not leave
        its clips in here for the life of the process. Never raises: a stat
        that throws is "absent", exactly as before."""
        now = time.monotonic()
        fresh: dict[str, tuple[bool, float]] = {}
        out: dict[str, bool] = {}
        for path in paths:
            if not path:
                out[path] = False
                continue
            if path in out:
                # The same clip can be in two bins. One stat, not two.
                continue
            cached = self._media_presence_cache.get(path)
            if (cached is not None and cached[0]
                    and (now - cached[1]) < self.MEDIA_PRESENCE_TTL_SECONDS):
                out[path] = True
                fresh[path] = cached
                continue
            try:
                present = bool(self._exists_fn(path))
            except Exception:
                present = False
            out[path] = present
            fresh[path] = (present, now)
        self._media_presence_cache = fresh
        return out

    def _refresh_media_tree_once(self) -> None:
        """Rescan the media pool and update the cache. Fault-isolated: never
        raises, and any failure just leaves the previous cache in place
        (except an explicit not-ok result, which clears it -- Resolve
        closing/switching projects should not keep reporting stale data)."""
        self._maybe_recover_stale_bridge()
        try:
            result = resolve_bridge.get_media_pool_items()
        except Exception:
            log.exception("media tree refresh: get_media_pool_items() failed")
            return
        if not result.get("ok"):
            with self._media_tree_lock:
                self._media_tree_cache = {}
            return

        project_name = str(result.get("project_name") or "").strip()
        if project_name and config_mod.is_ignored_project(
            project_name, self._ignored_resolve_projects
        ):
            # Same "pretend this project doesn't exist" contract the
            # watcher enforces for ignored_resolve_projects (config.py) --
            # never cache/report a scratch project's clips as "media_tree"
            # (see X-7).
            with self._media_tree_lock:
                self._media_tree_cache = {}
            return

        items = result.get("items", [])
        presence = self._media_presence(
            [str(item.get("file_path", "") or "") for item in items]
        )
        clips: list[dict[str, Any]] = []
        for item in items:
            file_path = item.get("file_path", "") or ""
            present = presence.get(file_path, False)
            clips.append(
                {
                    "bin_path": item.get("bin_path", "") or "",
                    "clip_name": item.get("clip_name", "") or "",
                    "file_path": file_path,
                    "kind": self._classify_media_kind(file_path),
                    "present": present,
                }
            )
        tree = {project_name: clips} if project_name else {}
        with self._media_tree_lock:
            self._media_tree_cache = tree

        # Piggy-backed on this walk rather than given its own thread: it needs
        # exactly the same media pool enumeration, and that call is the
        # expensive part (one locked trip into fusionscript per clip).
        self._relink_proxies_once(result.get("items", []))
        self._classify_pool_once(result.get("items", []))

    def _handle_bridge_state(self, connected: bool, reason: str) -> None:
        """Every poll's Resolve-bridge state, from the watcher. Never raises.

        Only one state warrants nagging: Resolve RUNNING with its scripting
        server dead. Resolve simply being closed is normal (and is
        _maybe_recover_stale_bridge's business, not this one's), so any other
        state resets the clock -- including a recovery, which also clears the
        silence so the NEXT breakage is warned about again.
        """
        try:
            if connected or reason != resolve_bridge.NO_SCRIPTING_MESSAGE:
                self._scripting_bad_since = None
                self._scripting_warned_at = None
                self._scripting_warn_silenced = False
                return
            self._maybe_warn_scripting_dead()
        except Exception:
            log.exception("bridge-state handling failed")

    def _scripting_warn_interval(self) -> float:
        """Seconds between warnings; <= 0 switches the warning off entirely
        (as does resolve_scripting_warning = false)."""
        if not bool(self.config.get("resolve_scripting_warning", True)):
            return 0.0
        try:
            return float(self.config.get("resolve_scripting_warning_interval", 300))
        except (TypeError, ValueError):
            # validate_config coerces this, but a hand-edited config that
            # skipped it must not silence the warning by accident.
            return 300.0

    def _maybe_warn_scripting_dead(self, now: Optional[float] = None) -> None:
        """Nag, on a timer, while Resolve is up but not accepting scripting.

        The editor cannot see this state: Resolve is on screen and behaving,
        while every companion feature that needs it is dead. It is also the
        one state that does NOT heal itself -- Resolve never retries a script
        server that failed at launch (item 19), and a stale fusionscript
        client can wedge the new session's server for every client on the
        machine (2026-08-12). So unlike every other warning here, this one
        repeats until it is fixed.

        The first dialog waits a full interval rather than firing on the
        first bad poll: Resolve's script server takes a moment to come up
        after launch, and a popup in the editor's face three seconds into
        every Resolve start would train them to dismiss the one warning that
        matters. Thereafter every interval, silenceable from the dialog.
        """
        interval = self._scripting_warn_interval()
        if interval <= 0:
            return
        if self._scripting_warn_silenced:
            return
        now = self._scripting_clock() if now is None else now
        if self._scripting_bad_since is None:
            self._scripting_bad_since = now
            return
        last = self._scripting_warned_at
        waited = now - (last if last is not None else self._scripting_bad_since)
        if waited < interval:
            return
        # Everything cheap first: this runs on the watcher's 3 s poll and the
        # probe below SHELLS OUT (tasklist/pgrep). Behind the interval gate
        # that is one spawn per warning instead of twenty a minute -- the
        # same arithmetic as resolve_bridge's _PROBE_TTL_SECONDS. The slot is
        # spent whether or not the probe confirms, so an inconclusive answer
        # costs one attempt per interval rather than one every 3 s for as
        # long as the bridge stays down.
        self._scripting_warned_at = now
        # A POSITIVE sighting only. describe_disconnection() reaches its
        # NO_SCRIPTING verdict through a probe that fails CLOSED (an
        # unspawnable tasklist, an unsupported platform -> "running"), which
        # is right for its callers and wrong here: it would nag forever on a
        # machine with Resolve shut. See resolve_prefs.resolve_process_state.
        if resolve_prefs_mod.resolve_process_state() is not True:
            return
        with self._scripting_warn_lock:
            if self._scripting_warn_open:
                # Still on screen from last time (the editor is reading it,
                # or has left it up). The timer restarts when it closes.
                return
            self._scripting_warn_open = True
        self._scripting_warned_at = now
        log.warning(
            "Resolve is running but its scripting server is not answering -- "
            "warning the editor (every %.0fs until it is fixed)", interval,
        )
        threading.Thread(
            target=self._show_scripting_warning,
            name="ccsync-scripting-warning", daemon=True,
        ).start()

    def _show_scripting_warning(self) -> None:
        """The dialog thread. NEVER the watcher's: a Tk mainloop on that
        thread freezes timeline polling for as long as the window is up
        (AUDIT_2 CORE-M2, the same reason the fixer popup gets its own)."""
        try:
            from . import tray as tray_mod

            if tray_mod.show_scripting_warning(self):
                self._scripting_warn_silenced = True
                log.info("scripting warning silenced by the editor until the link recovers")
        except Exception:
            log.exception("could not show the Resolve scripting warning")
            self._notify_tray(
                resolve_bridge.NO_SCRIPTING_MESSAGE, "ccsync-companion")
        finally:
            with self._scripting_warn_lock:
                self._scripting_warn_open = False
            # The interval is measured from the moment the editor is DONE
            # reading, not from when the dialog opened -- otherwise a window
            # left up for an hour re-pops the instant it is closed.
            self._scripting_warned_at = self._scripting_clock()

    def _maybe_recover_stale_bridge(self) -> None:
        """Restart the companion when the Resolve it connected to has exited.

        fusionscript.dll keeps process-global IPC state. Proven live
        2026-08-12 (an editor's rig): after their Resolve restarted,
        this process's stale client wedged every NEW Resolve session's
        scripting server -- for every client on the machine, across three
        Resolve restarts -- until the companion was restarted FIRST. The
        safe moment to shed the stale state is while Resolve is DOWN:
        nothing to wedge, and the fresh process greets the next Resolve
        with a clean DLL.

        Guards, in order: feature flag; once per process (the replacement
        starts unlatched); ever_connected (a fresh DLL has no stale state);
        currently disconnected; the Resolve process actually ABSENT --
        resolve_is_running fails closed (True), so an inconclusive probe
        never triggers a restart; and finally apply_upgrade's own
        stand-down test. Never raises.
        """
        if not bool(self.config.get("bridge_auto_restart", True)):
            return
        if self._bridge_restart_started:
            return
        try:
            state = resolve_bridge.session_state()
            if state.get("connected") or not state.get("ever_connected"):
                return
            if resolve_prefs_mod.resolve_is_running():
                return
        except Exception:
            return
        blocker = self._standing_down_would_kill_work()
        if blocker:
            # DEFERRED, not abandoned -- the latch stays unset so the next
            # media-tree tick tries again once the work is done. Quitting
            # Resolve part-way through a "Copy this project's media in" is
            # enough to pass every guard above, and standing the process down
            # there kills the consolidate worker mid-shutil.copy2
            # (COMP-CORE-2, 2026-08-14).
            log.info(
                "stale-bridge restart deferred: %s in progress -- retrying on a "
                "later pass", blocker,
            )
            return
        self._bridge_restart_started = True
        log.info(
            "the Resolve this companion was connected to has exited -- "
            "restarting the companion so its scripting link starts clean "
            "(see resolve_bridge.NO_SCRIPTING_MESSAGE's note)"
        )
        try:
            upgrade_mod.restart_self(request_shutdown=self.shutdown)
        except Exception:
            log.exception("stale-bridge self-restart failed")

    def _classify_pool_once(self, items: list[dict[str, Any]]) -> None:
        """The watcher's path classification, over the WHOLE media pool.

        The passive watcher sees only the current timeline's video/audio
        tracks, so clips sitting in bins accumulated broken paths with zero
        signal -- the 2026-08-12 Energy Transition incident built up 200+
        that way. Piggy-backed on the media-tree walk (same enumeration, no
        extra Resolve calls) every media_tree_refresh_interval:

          NON_CANONICAL -> auto-relink (once per path -- a fixed path never
                           reappears, a refusal must not retry every pass);
          FOREIGN       -> one batched tray warning per pass, warn-once per
                           path;
          OUT_OF_TREE   -> the popup queue, through the same snooze/ignore
                           plumbing as the watcher's batches.

        BAD_PREFIX stays the watcher's (a broken mapping warns fine from the
        timeline, and warning twice helps nobody). Fault-isolated: never
        raises.
        """
        try:
            if self._local_root_is_broken():
                return
            if getattr(self, "_p_swap_busy", False):
                return
            try:
                if self.p_mapping_mode() == "server":
                    return
            except Exception:
                pass
            from .watcher import _norm_key

            local_root = self.config.get("local_root", "")
            prefix = str(self.config.get("canonical_prefix", ""))
            out_of_tree: list[dict[str, Any]] = []
            non_canonical: list[dict[str, Any]] = []
            foreign: list[dict[str, Any]] = []
            for item in items:
                path = item.get("file_path", "")
                if not path:
                    continue
                cls = classify_path(path, local_root, prefix)
                key = _norm_key(path)
                if cls == OUT_OF_TREE:
                    if not self.ignore_tracker.is_ignored(path):
                        out_of_tree.append(item)
                elif cls == paths_mod.NON_CANONICAL:
                    if key not in self._pool_offered_non_canonical:
                        self._pool_offered_non_canonical.add(key)
                        non_canonical.append(item)
                elif cls == paths_mod.FOREIGN:
                    if key not in self._pool_warned_foreign:
                        self._pool_warned_foreign.add(key)
                        foreign.append(item)
            if non_canonical:
                self._handle_non_canonical(non_canonical)
            if foreign:
                self._handle_foreign_batch(foreign)
            if out_of_tree:
                self._handle_out_of_tree(out_of_tree)
        except Exception:
            log.exception("media pool classification pass failed")

    def _handle_foreign_batch(self, items: list[dict[str, Any]]) -> None:
        """One toast for a sweep's worth of FOREIGN clips, not one each.

        The first sweep after this ships can meet a project-lifetime backlog
        (Energy Transition held 161 at once) -- a toast per clip would be a
        notification storm nobody reads. Every path still gets its own log
        line.
        """
        for item in items:
            log.warning(
                "clip stored under another machine's path (unfixable here): %s",
                item.get("file_path", ""),
            )
        first = items[0].get("clip_name") or os.path.basename(
            items[0].get("file_path", "")) or "a clip"
        more = f" and {len(items) - 1} other clip(s)" if len(items) > 1 else ""
        self._notify_tray(
            f"“{first}”{more} point at paths that only exist on another "
            "editor's machine, so they can never sync or come online here. "
            "Whoever imported them should re-import through the P: drive "
            "(their companion will offer the fix). Details in the log.",
            "ccsync-companion: foreign clips",
        )

    def _relink_proxies_once(self, items: list[dict[str, Any]]) -> None:
        """Repoint stale/unlinked proxy attachments at the copies lane B
        synced into the tree. Fault-isolated: never raises, never blocks the
        media-tree refresh.

        Costs nothing in the steady state -- once every clip's proxy resolves,
        plan_relinks() returns [] and no Resolve calls are made at all.
        """
        if not bool(self.config.get("proxy_relink_enabled", True)):
            return
        if self._local_root_is_broken():
            # With a blank local_root nothing classifies as in-tree, so this
            # would either no-op or (worse) act on the wrong clips.
            return
        try:
            ops = proxy_relink.plan_relinks(
                items,
                self.config.get("local_root", ""),
                str(self.config.get("canonical_prefix", "")),
                exists_fn=self._exists_fn,
            )
            if not ops:
                return
            log.info("proxy relink: %d clip(s) need their proxy repointed", len(ops))
            # The second unprompted media-pool rewrite, rate-limited on the
            # same terms as the canonical one (item 9, 2026-08-17). Refusals
            # are already remembered per proxy file, so the steady state is
            # zero ops; this bounds the case where they are NOT remembered --
            # a mis-set local_root that makes every clip look repointable.
            project = resolve_bridge.current_project_name()
            if not resolve_journal.allow_automatic(project, "auto-proxy-relink"):
                log.info("proxy relink: rate-limited for this project -- %d op(s) "
                         "left for the next pass", len(ops))
                return
            proxy_relink.apply_relinks(
                ops,
                lambda mpi, path: resolve_bridge.link_proxy_media(
                    mpi, path, source="auto-proxy-relink"),
            )
        except Exception:
            log.exception("proxy relink pass failed")

    def _media_tree_loop(self) -> None:
        while not self._media_tree_stop_event.is_set():
            self._media_tree_heartbeat = time.monotonic()
            try:
                self._refresh_media_tree_once()
            except Exception:
                log.exception("media tree refresh loop failed")
            # Piggy-backed here because it is the one slow background tick
            # this process already has: it keeps the tray's cache-only read of
            # the P: mapping fresh without the tray forking `net use` every
            # 10 s (COMP-CORE-6, 2026-08-14).
            self._refresh_p_mapping_mode()
            if self._media_tree_stop_event.wait(self.media_tree_refresh_interval):
                break

    # -- identity / login gating (see identity.py) -----------------------------------------------
    def _apply_identity_role(self) -> None:
        """Set self._sync_enabled from config.toml's own `mode`/`sync_enabled`
        -- nothing else.

        BEFORE 2026-08-27 this also consulted identity.py's `role`, sourced
        from the dashboard's /verify (api.py's DASH_ADMIN_USERS list) --
        i.e. from whether the SIGNED-IN PERSON is an admin, not from what
        this MACHINE is. That made an admin's own laptop, signed in as the
        admin account, report itself as "base" and get its sync disabled
        (and, upstream of this function, refused a sync plan by a dashboard
        that also derived the role from the person) even though the laptop
        is an ordinary editor computer with its own local_root
        (MULTI_BASE_RIG_PLAN.md WP0/WP1: the role belongs to the COMPUTER).
        config.toml's `mode` -- read by MODE_PROFILES in config.py's
        load_config(), which already turns sync_enabled/lane_b_enabled off
        for mode="base" -- is the one thing this function now reads, via
        self._configured_sync_enabled (set once at __init__ from that same
        merged config). That MODE_PROFILES path is unchanged: a machine
        whose config.toml says mode="base" still syncs nothing.

        Only touches self._sync_enabled -- popup_enabled deliberately stays
        whatever config.toml says either way (see config.py's MODE_PROFILES
        comment: a careless base-rig editor can still cut in media from
        outside the tree, so the popup should still catch it).

        Idempotent and cheap to call whenever identity state changes
        (constructor, sign_in(), sign_out()) -- kept as its own method
        rather than inlined at __init__ because those call sites still need
        to re-apply it (identity.role remains readable for diagnostics, so a
        future signal could reuse this hook without callers changing).
        """
        self._sync_enabled = self._configured_sync_enabled

    def _pop_lane_completions(self) -> list:
        """Drain every lane's completed-file events for the reporter (the
        dashboard's transfer HISTORY). Lanes without the accessor (tests,
        the Syncthing lane) contribute nothing."""
        out: list = []
        for lane in self.lanes:
            pop = getattr(lane, "pop_completions", None)
            if pop is None:
                continue
            try:
                out.extend(pop())
            except Exception:
                log.exception("pop_completions failed for %s", getattr(lane, "name", lane))
        return out

    def syncthing_device_id(self) -> str:
        """This machine's own Syncthing device ID, or "" when Syncthing is
        not reachable (an unmanaged machine has no admin client at all).

        The dashboard needs it to share a folder with THIS computer rather
        than with every device named after its owner (WP3). Never raises:
        the reporter treats "" as "ask again next tick"."""
        admin = self.syncthing_admin
        if admin is None:
            return ""
        try:
            return str((admin.system_status() or {}).get("myID", "") or "")
        except Exception:
            log.debug("syncthing device id unavailable", exc_info=True)
            return ""

    def effective_mode(self) -> str:
        """"base" or "editor" -- what this MACHINE actually is, for dashboard
        reporting (get_mode) and every tray/menu/Settings question that asks.

        CONFIG ONLY since 2026-08-27 (MULTI_BASE_RIG_PLAN.md WP0/WP1's
        follow-up): config.toml's own `mode` -> "base" if it says "base",
        "editor" otherwise. identity.role (the dashboard's /verify, derived
        from api.py's ADMIN list -- i.e. from the signed-in PERSON, not from
        this machine) is no longer consulted here at all. It used to win
        whenever the dashboard sent one, which put the role switch in the
        wrong hands: the owner's own laptop, signed in as the admin account,
        reported itself "base" and was refused a sync plan by a dashboard
        that derives the SAME thing from the SAME admin list -- an ordinary
        editor computer, punished for who happened to be signed into it. The
        role now belongs to the computer (config.toml's `mode`, writable from
        the tray's Settings -> THIS COMPUTER, settings_window.py), the way
        Resolve's own project/database settings do. Older dashboards still
        SEND a role in the /verify response; this build ignores it (identity
        stays readable for diagnostics -- see identity.role's own docstring).

        Same monotonic direction as before: a machine whose config says
        mode="base" stays that way (MODE_PROFILES already turns its lanes
        off); nothing here can start a lane."""
        return ("base"
                if str(self.config.get("mode", "") or "").strip().lower() == "base"
                else "editor")

    # -- P: grade-swap (drive_swap.py) ----------------------------------

    def _server_p_unc(self) -> str:
        """The grade-swap target: the explicit config value when set,
        "none"/"off" to disable, else DERIVED from dashboard_url +
        remote_root so every companion gets the feature with no setup."""
        from . import drive_swap

        value = str(self.config.get("server_p_unc", "")).strip()
        if value.lower() in ("none", "off", "disabled"):
            return ""
        if value:
            return value
        return drive_swap.derive_server_unc(
            str(self.config.get("dashboard_url", "")),
            str(self.config.get("remote_root", "")),
        )

    def p_swap_available(self) -> bool:
        """The tray shows the grade-swap only when it can work: Windows,
        editor role (the base rig's P: already IS the server), and a
        resolvable server UNC (explicit or derived)."""
        import os as _os

        if _os.name != "nt":
            return False
        if not self._server_p_unc():
            return False
        try:
            return self.effective_mode() != "base"
        except Exception:
            return False

    def p_mapping_mode(self) -> str:
        """"local" | "server" | "other" | "none", cached briefly -- the
        watcher consults this on every mapping warning."""
        if os.name != "nt":
            # No drive namespace off Windows: there is no P: to classify, and
            # drive_swap's default runner would try to spawn `net`/`subst`,
            # which don't exist on macOS -- once per mapping warning. Resolve's
            # Mapped Mount preference is the equivalent there and isn't
            # machine-inspectable, so answer "none" and stay quiet.
            return "none"
        now = time.monotonic()
        cached = getattr(self, "_p_mode_cache", None)
        if cached is not None and now - cached[0] < 10.0:
            return cached[1]
        mode = self._probe_p_mapping_mode()
        self._p_mode_cache = (now, mode)
        return mode

    def _probe_p_mapping_mode(self) -> str:
        """One `net use P:` (plus a `subst` on a subst-mapped rig). Never
        raises -- "none" is the "we could not tell" answer every caller
        already treats as "say nothing"."""
        from . import drive_swap

        try:
            return drive_swap.classify_p_target(
                drive_swap.current_p_target(),
                str(self.config.get("local_root", "")),
                self._server_p_unc(),
            )
        except Exception:
            return "none"

    def p_mapping_mode_cached(self) -> str:
        """The TRAY's read: whatever the cache holds, never a fresh probe.

        _tray_snapshot pulls this on every 2 s refresh tick, which guaranteed
        the 10 s memo above expired and re-populated forever -- ~8,600 `net
        use` processes a day (up to ~17,000 with the subst fallback) on every
        Windows machine in the fleet, to re-derive a value that normally
        changes never, from the one place documented as where nothing may
        stall (COMP-CORE-6, 2026-08-14). Both in-process mutators
        (swap_p_to_server / swap_p_to_local) already invalidate the cache
        explicitly, and _refresh_p_mapping_mode re-derives it on the slow
        media-tree tick so an out-of-process remap (the installer's
        CCSync-SubstP logon task, a manual `net use`) still lands. Only a
        cold cache -- first tick of the process, or straight after a swap --
        pays for a probe.
        """
        cached = getattr(self, "_p_mode_cache", None)
        if cached is not None:
            return cached[1]
        return self.p_mapping_mode()

    def _refresh_p_mapping_mode(self) -> None:
        """Re-derive the P: classification in the background (COMP-CORE-6).

        Called from the media-tree loop, i.e. once per
        media_tree_refresh_interval, which is what keeps the tray's
        cache-only read honest about a mapping changed from OUTSIDE this
        process. Never raises."""
        if os.name != "nt":
            return
        try:
            self._p_mode_cache = (time.monotonic(), self._probe_p_mapping_mode())
        except Exception:
            log.debug("P: mapping refresh failed", exc_info=True)

    def swap_p_to_server(self, username: str = "", password: str = "") -> tuple[bool, str]:
        """Remap P: to the server tree for full-res grading. On failure the
        LOCAL map is restored before returning -- the worst outcome is
        "nothing changed", never an unmapped P:.

        username/password are the retry path: when the plain attempt fails
        with an auth error (no stored Windows credentials for the server),
        the tray asks for the editor's server login and calls again. On a
        successful credentialed swap the login is persisted to Credential
        Manager so every later swap is silent."""
        from . import drive_swap

        if not self.p_swap_available():
            return False, "grade-swap is not available on this machine"
        unc = self._server_p_unc()
        self._p_swap_busy = True
        try:
            # local_root so drive_swap can tell a LEGACY subst mapping of this
            # machine's own copy from somebody else's P: before it unmaps
            # anything (UX-6, resilience sweep 2026-08-28).
            ok, message = drive_swap.swap_to_server(unc, username=username,
                                                    password=password,
                                                    local_root=str(self.config.get("local_root", "")))
            if ok and username:
                drive_swap.persist_credentials(unc, username, password)
            if not ok:
                restored, restore_msg = drive_swap.swap_to_local(
                    str(self.config.get("local_root", "")))
                suffix = " P: was restored to your local copy." if restored else f" AND {restore_msg}"
                message = message + suffix
        finally:
            self._p_swap_busy = False
        self._p_mode_cache = None
        log.info("grade-swap to server: ok=%s (%s)", ok, message)
        return ok, message

    def canonical_prefix_label(self) -> str:
        """"P:" -- the drive as the editor's copy names it (UX-15).

        SITE DATA, never a literal (COMMERCIAL_READINESS item 11): the
        canonical prefix comes from the site manifest, and a second customer
        on Q: must not read a sentence about P:. Falls back to a phrase
        rather than to a guessed letter, because a wrong letter in a repair
        instruction is worse than no letter.
        """
        prefix = str(self.config.get("canonical_prefix", "") or "").strip()
        return prefix.rstrip("\\/") or "your media drive"

    def p_repair_available(self) -> bool:
        """Whether [ REPAIR P: NOW ] can do anything on this machine.

        Windows only: there is no drive namespace to repair on macOS (the
        equivalent is Resolve's own Mapped Mount preference, which is not
        machine-inspectable), and drive_swap's runner would try to spawn
        `net`/`subst` there.
        """
        if os.name != "nt":
            return False
        return bool(str(self.config.get("local_root", "") or "").strip())

    def repair_p_mapping(self) -> tuple[bool, str]:
        """Point the canonical prefix back at THIS machine's synced folder.

        UX-15 (resilience sweep 2026-08-28): the repair the broken-mapping
        toast has always described and never offered.

        Keeps UX-6's ownership check, which lives in swap_to_server and not
        in swap_to_local: a P: that CCSync did not create is somebody else's
        mapping, and swap_to_local's first act is an unconditional unmap
        that cannot put it back. So a foreign target is REFUSED here, before
        anything is unmapped, and the editor is told what it is pointing at.
        `none` -- P: mapped to nothing that could be read -- is the state the
        toast actually fires for, and is the one this button exists to fix.
        """
        from . import drive_swap

        letter = self.canonical_prefix_label()
        if not self.p_repair_available():
            return False, (f"{letter} cannot be repaired from here on this computer. "
                           "Tray > Settings > COPY DIAGNOSTICS FOR YOUR ADMIN.")
        mode = self.p_mapping_mode()
        if mode == "local":
            return True, f"{letter} is already pointing at your synced folder."
        if mode == "server":
            return False, (
                f"{letter} is showing the server originals because you asked for a "
                "grade swap. Use FINISH GRADING to put it back.")
        if mode == "other":
            target = ""
            try:
                target = drive_swap.current_p_target()
            except Exception:
                log.debug("could not re-read the P: target for the refusal", exc_info=True)
            return False, (
                f"{letter} is mapped to {target or 'something else'}, which CCSync did "
                "not create. Nothing was changed. Ask your admin before removing it.")
        ok, message = self.swap_p_to_local()
        log.info("repair %s: ok=%s (%s)", letter, ok, message)
        return ok, message

    def resolve_health(self) -> dict[str, Any]:
        """`sync_guard.resolve_health` (UX-4 / RES-12 / APP-2).

        The one editor mistake that guarantees unsynced footage -- media cut
        in from the Desktop -- used to be visible to nobody but the editor
        dismissing the dialog about it: poll_once computed these numbers and
        threw them away, and no field in the report carried them.

        `last_scan_at` is None until a full poll has completed, and that is
        load-bearing: with Resolve closed every count here is zero, and a
        zero that means "we have not looked" must not render as "nothing is
        wrong". The reader shows the counts only alongside a scan time.
        """
        counts = getattr(self.watcher, "last_counts", None) or {}
        return {
            "out_of_tree": int(counts.get("out_of_tree") or 0),
            "bad_prefix": int(counts.get("bad_prefix") or 0),
            "missing": int(counts.get("missing") or 0),
            "ignored_this_session": self.ignore_tracker.session_count(),
            "ignored_folders": self.ignore_tracker.folder_count(),
            # Not in the reported contract (the dashboard drops what it does
            # not declare) -- it is the tray's own line: how many clips this
            # machine has EVER been told to leave un-synced, across restarts.
            "skipped_ever": self.ignore_tracker.skipped_count(),
            "last_scan_at": getattr(self.watcher, "last_scan_at", None),
            "open_project": getattr(self.watcher, "last_resolve_project", None),
        }

    def swap_p_to_local(self) -> tuple[bool, str]:
        from . import drive_swap

        self._p_swap_busy = True
        try:
            ok, message = drive_swap.swap_to_local(str(self.config.get("local_root", "")))
        finally:
            self._p_swap_busy = False
        self._p_mode_cache = None
        log.info("grade-swap to local: ok=%s (%s)", ok, message)
        return ok, message

    def removable_projects(self) -> list[dict[str, str]]:
        """[{"slug", "rel"}] of the projects this machine currently syncs --
        what the tray's "Remove a project from this machine" submenu lists.
        Empty on the base rig (its tree IS the server tree), in legacy mode,
        and when no selection is known."""
        if not self._managed or self.selection_client is None:
            return []
        try:
            if self.effective_mode() == "base":
                return []
        except Exception:
            return []
        try:
            entries, _source = self.selection_client.get()
        except Exception:
            log.exception("removable_projects: selection read failed")
            return []
        out: list[dict[str, Any]] = []
        for entry in entries or []:
            slug = str(entry.get("slug") or "").strip()
            rel = str(entry.get("rel_path") or entry.get("label") or "").strip()
            if slug and rel:
                out.append({
                    "slug": slug, "rel": rel,
                    # docs/UPLOAD_ONLY_TICK.md: the removal gate and the tray
                    # menu both read it. Only the exact string counts; the
                    # sequencer's fail-closed reading of an unknown mode
                    # matters there, not here, where the worst case is a
                    # question asked of a folder that does not exist.
                    "upload_only": str(entry.get("sync_mode") or "").strip().lower()
                                   == "upload_only",
                })
        return out

    def removal_blockers(self, slug: str) -> dict[str, Any]:
        """Is it safe to delete this project's local copy right now?

        Answers with {"blocked", "reasons", "pending_uploads", "lane_c",
        "unknown"} -- the gate on remove_project_from_machine's `rmtree`
        (COMMERCIAL_READINESS.md item 9, 2026-08-17). Two questions, one per
        outbound lane:

          * lane A -- a --dry-run of the real lane A command for this
            project (RcloneLane.pending_uploads). Counts exactly the files
            the lane would upload, with the lane's own filters and age/size
            floors, so a growing card ingest blocks and a `.DS_Store` does
            not.
          * lane C -- Syncthing's own aggregate completion for the folder
            (`/rest/db/completion?folder=X`) plus its local needTotalItems.
            Anything under 100% means bytes this editor made have reached
            nobody yet.

        FAILS CLOSED. A probe that could not answer blocks the removal, the
        opposite of the fail-open posture everywhere else in this file: for
        every other guard "I could not tell" costs a warning, for this one it
        costs footage that exists nowhere else. Never raises."""
        out: dict[str, Any] = {
            "blocked": False, "reasons": [], "pending_uploads": 0,
            "lane_c": {}, "unknown": False,
        }
        mine = next((p for p in self.removable_projects() if p["slug"] == slug), None)
        if mine is None:
            out["blocked"] = True
            out["reasons"].append("that project is not selected on this machine")
            return out
        rel = mine["rel"]
        # An upload-only project has no shared folder on this machine
        # (docs/UPLOAD_ONLY_TICK.md): "have my originals reached the server"
        # is the only honest question, so the lane C half below is skipped
        # rather than asked of a folder Syncthing may not even have.
        upload_only = bool(mine.get("upload_only"))

        # Borrowed folders (SHARED_FOLDERS_PLAN.md §3.2/§5). Two extra
        # questions, both answered from the cached selection's `includes`:
        #   * removing a BORROWER: its borrowed dirs were this machine's to
        #     upload from too, so each include subpath gets the same lane A
        #     dry-run as the project's own dir below.
        #   * removing a LENDER while a borrower is still selected here:
        #     rmtree takes the borrowed subtree with it. Blocked with a
        #     reason (the next pass re-pulls it, but the editor should know
        #     what they are detaching).
        my_includes: list[dict[str, Any]] = []
        try:
            entries, _source = (self.selection_client.get()
                                if self.selection_client is not None else ([], ""))
        except Exception:
            entries = []
        for entry in entries or []:
            raw = entry.get("includes")
            if not isinstance(raw, list):
                continue
            for inc in raw:
                if not isinstance(inc, dict):
                    continue
                if str(entry.get("slug") or "") == slug and not inc.get("covered"):
                    my_includes.append(inc)
                if str(inc.get("lender_slug") or "") == slug:
                    borrower = str(entry.get("label") or entry.get("slug") or "")
                    sub = str(inc.get("sub_rel") or "")
                    out["blocked"] = True
                    out["reasons"].append(
                        f"part of this project ('{sub}') is shared into {borrower}, "
                        f"which is still selected here"
                    )

        subpath = f"{PROJECTS_PREFIX}{rel}"
        try:
            pending = self._lane_a.pending_uploads(subpath)
            for inc in my_includes:
                inc_sub = str(inc.get("subpath") or "").strip()
                if not inc_sub or pending is None:
                    continue
                more = self._lane_a.pending_uploads(f"{PROJECTS_PREFIX}{inc_sub}")
                if more is None:
                    pending = None
                    break
                pending = {
                    "count": int(pending.get("count") or 0) + int(more.get("count") or 0),
                    "samples": (list(pending.get("samples") or [])
                                + list(more.get("samples") or [])),
                }
        except Exception:
            log.exception("removal gate: pending_uploads failed for %s", subpath)
            pending = None
        if pending is None:
            out["unknown"] = True
            out["blocked"] = True
            out["reasons"].append(
                "CCSync could not reach the server to check whether your footage has "
                "been uploaded"
            )
        else:
            count = int(pending.get("count") or 0)
            out["pending_uploads"] = count
            if count:
                sample = ", ".join((pending.get("samples") or [])[:3])
                out["blocked"] = True
                out["reasons"].append(
                    f"{count} video file(s) have not been uploaded yet"
                    + (f" (e.g. {sample})" if sample else "")
                )
        if self.syncthing_admin is not None and not upload_only:
            try:
                completion = self.syncthing_admin.folder_completion(slug) or {}
                status = self.syncthing_admin.folder_status(slug) or {}
            except Exception:
                log.exception("removal gate: Syncthing status failed for %s", slug)
                out["unknown"] = True
                out["blocked"] = True
                out["reasons"].append(
                    "CCSync could not ask Syncthing whether this project is fully shared"
                )
                completion, status = {}, {}
            try:
                pct = float(completion.get("completion", 100.0))
            except (TypeError, ValueError):
                pct = 100.0
            need_local = int(status.get("needTotalItems") or 0)
            out["lane_c"] = {
                "completion": pct,
                "need_bytes": int(completion.get("needBytes") or 0),
                "need_local_items": need_local,
                "state": str(status.get("state") or ""),
            }
            if pct < 100.0:
                out["blocked"] = True
                out["reasons"].append(
                    f"the shared files for this project are only {pct:.0f}% synced to "
                    "the server"
                )
            if need_local:
                out["blocked"] = True
                out["reasons"].append(
                    f"{need_local} shared file(s) have not arrived on this machine yet"
                )
        return out

    def _note_removal_override(self, slug: str, rel: str, blockers: dict[str, Any]) -> None:
        """Remember an overridden removal so the dashboard sees it too.

        Bounded and best-effort: it rides the next report's `sync_guard`
        section, which means a machine that is taken offline immediately
        afterwards never reports it -- the log line above is the record that
        cannot be lost."""
        try:
            self._removal_overrides.append({
                "slug": slug, "rel": rel,
                "at": datetime.now(timezone.utc).isoformat(),
                "pending_uploads": int(blockers.get("pending_uploads") or 0),
                "reasons": list(blockers.get("reasons") or [])[:4],
            })
        except Exception:
            log.exception("could not record the removal override")

    def remove_project_from_machine(
        self, slug: str, override: bool = False
    ) -> tuple[bool, str]:
        """The safe order for "I'm done with this project here":

          1. untick it on the dashboard (the server unshares the Syncthing
             folder; lanes stop scheduling it);
          2. drop the folder from the LOCAL Syncthing config, so the
             deletion below can never be read as content to propagate and
             never strands the folder in marker-missing;
          3. delete the local copy.

        Any failure stops BEFORE the deletion step -- the worst outcome is
        "nothing was deleted". The server's copy is never touched: lane A
        never mirrors deletions, and by step 3 nothing is watching. Returns
        (ok, human message); never raises. Runs on a tray worker thread."""
        from .sync.repath import normalized_safe_rel

        slug = str(slug or "").strip()
        if not slug:
            return False, "no project given"
        if not self._managed or self.selection_client is None:
            return False, "not in managed mode"
        if self.effective_mode() == "base":
            return False, "refusing on the base rig: its tree IS the server tree"
        if self._root_absent:
            # SYNC-13 (2026-08-11): with the drive merely unplugged the steps
            # below all "succeed" -- untick, unshare, then target.exists() is
            # False and the editor is told the folder was already gone. The
            # multi-GB copy is still on the SSD, now unticked and unshared so
            # nothing will ever reclaim it, while they believe the space is
            # back.
            return False, (
                f"{site_mod.drive_phrase()} is disconnected, so nothing was "
                f"removed. Plug it back in and try again."
            )
        rel = next((p["rel"] for p in self.removable_projects() if p["slug"] == slug), None)
        if rel is None:
            return False, "that project is not selected on this machine"
        safe_rel = normalized_safe_rel(rel)
        if not safe_rel:
            return False, f"unsafe project path {rel!r} -- nothing was deleted"

        # THE CAUGHT-UP GATE (COMMERCIAL_READINESS.md item 9, 2026-08-17).
        # Until now the only guard on the one irreversible delete in this
        # system was a sentence in the confirm dialog asking the editor to go
        # and check the dashboard's TRANSFERS page themselves. Nobody does.
        blockers = self.removal_blockers(slug)
        if blockers["blocked"] and not override:
            return False, (
                f"'{rel}' still has work that has not reached the server, so nothing "
                f"was deleted:\n  - " + "\n  - ".join(blockers["reasons"]) + "\n"
                "Leave CCSync running until it is finished, then try again."
            )
        if blockers["blocked"] and override:
            # An override is a decision to destroy un-uploaded footage. It is
            # allowed (an editor with a dead NAS and a full disk has to be
            # able to act) but it is never quiet: log line, report field,
            # and the dialog made them type the project's name.
            log.warning(
                "remove_project: OVERRIDE -- deleting %s (%s) with work still pending: %s",
                slug, rel, "; ".join(blockers["reasons"]),
            )
            self._note_removal_override(slug, rel, blockers)

        ok, message = self.selection_client.untick(slug)
        if not ok:
            return False, f"could not untick on the dashboard ({message}) -- nothing was deleted"
        log.info("remove_project: unticked %s on the dashboard", slug)

        if self.syncthing_admin is not None:
            try:
                self.syncthing_admin.remove_folder(slug)
                log.info("remove_project: removed local Syncthing folder %s", slug)
            except Exception as exc:
                # A folder that was never configured locally is fine; any
                # other failure means Syncthing may still be watching --
                # deleting now would propagate or error, so stop here.
                if "404" not in str(exc):
                    log.exception("remove_project: could not remove local folder %s", slug)
                    return False, (
                        "the project was unticked, but the local Syncthing folder could "
                        "not be removed -- nothing was deleted. Try again in a minute."
                    )

        local_root = str(self.config.get("local_root", "")).strip()
        if not local_root:
            return False, "the project was unticked, but local_root is not configured -- nothing was deleted"
        target = (Path(local_root) / "Projects" / Path(*safe_rel.split("/"))).resolve()
        projects_root = (Path(local_root) / "Projects").resolve()
        if projects_root not in target.parents:
            return False, f"refusing to delete {target} (outside {projects_root})"
        if not target.exists():
            return True, f"'{rel}' is no longer synced here (its folder was already gone)"
        try:
            import shutil

            shutil.rmtree(target)
        except Exception as exc:
            log.exception("remove_project: rmtree failed for %s", target)
            return False, (
                f"'{rel}' was unticked and unshared, but some files could not be "
                f"deleted ({exc}). Delete the folder by hand -- it is safe now."
            )
        log.info("remove_project: deleted %s", target)
        return True, f"'{rel}' removed from this machine. The server copy is untouched."

    def editor_identity(self) -> Optional[str]:
        """The editor name to use for reporting/destination-suggestion
        (instead of trusting raw cfg["editor_name"]): the verified sign-in
        identity when one exists, else -- only when require_login is OFF --
        the raw config value. Returns None when require_login is on and no
        one has signed in yet; passed to the reporter as get_editor_name, so
        returning None is what makes it SKIP reporting rather than post
        under a bogus identity (see reporter.py's post_once)."""
        if self.identity.valid():
            return self.identity.username
        if self._require_login:
            return None
        # A blank/whitespace editor_name is not a usable identity either --
        # returning "" here used to let post_once() proceed and POST every
        # report under editor_name="", which the dashboard's ReportIn
        # (min_length=1) 422s forever, invisibly (see S-15). None makes
        # post_once() SKIP the cycle instead, same as the require_login gate.
        name = str(self.config.get("editor_name", "")).strip()
        return name or None

    def _lane_pending_login_detail(self) -> str:
        return 'sign in required -- use the tray\'s "Sign in..." to authenticate before syncing'

    def _lane_config_problem_detail(self) -> str:
        return (
            "NOT SYNCING: this machine isn't fully set up -- "
            f"{self.config_problems[0] if self.config_problems else 'see companion.log'}"
        )

    def _mark_lanes_pending_login(self) -> None:
        for lane in self.lanes:
            try:
                with lane._lock:
                    lane._status.detail = self._lane_pending_login_detail()
            except Exception:
                pass

    def _mark_lanes_misconfigured(self) -> None:
        detail = self._lane_config_problem_detail()
        for lane in self.lanes:
            try:
                with lane._lock:
                    lane._status.detail = detail
            except Exception:
                pass

    def _mark_lanes_eula_not_accepted(self, problem: str) -> None:
        detail = f"NOT SYNCING: {problem}"
        for lane in self.lanes:
            try:
                with lane._lock:
                    lane._status.detail = detail
            except Exception:
                pass

    def eula_problem(self) -> Optional[str]:
        """One sentence saying why this machine may not sync for licence
        reasons, or None. Read by the gate below and by run()'s startup
        notification, so the tray toast and the lane detail cannot disagree
        (2026-08-17, COMMERCIAL_READINESS.md item 3)."""
        try:
            return eula_mod.acceptance_problem()
        except Exception:
            # A licence check that throws must not be the thing that stops
            # an editor syncing -- same fail-open reasoning as a missing
            # bundled document (eula.py's docstring).
            log.exception("EULA acceptance check failed -- treating it as accepted")
            return None

    # -- the licence, and the one click that clears it ---------------------
    #
    # 2026-08-18. Item 3 put consent in the WIZARD and nowhere else, which was
    # right for a clean install and wrong for an upgrade: editors get builds
    # through the companion's own upgrade channel (upgrade.py), which never
    # runs the wizard, so 0.8.0 reached a machine, refused to start its lanes,
    # and rendered that as "this machine isn't set up yet" on all three tray
    # lines. Getting a wizard back onto that machine means downloading the
    # whole installer again -- ten minutes of drive mapping and account checks
    # to produce a three-line JSON file.
    #
    # So the companion asks, showing the SAME document it would have shown:
    # eula.BUNDLED_TEXT is assets/EULA.md, the copy tests/test_eula.py pins
    # byte-identical to docs/legal/EULA.md. The wizard still asks on a fresh
    # install; this is the upgrade path it never covered.

    def prompt_licence_acceptance(self, force: bool = False) -> None:
        """Offer the licence agreement, on its own thread. No-op when there is
        nothing to accept.

        `force` is the tray item: an editor who declined (or closed the window)
        asking to see it again, which must work however many times they ask.
        """
        if not self.eula_problem():
            return
        if not force:
            if self._licence_prompted:
                return
            self._licence_prompted = True
        threading.Thread(
            target=self._show_licence_dialog, name="ccsync-licence", daemon=True,
        ).start()

    def _licence_watch(self, first_delay: float = 3.0,
                       interval: float = LICENCE_RETRY_SECONDS) -> None:
        """Keep offering the licence until it has actually been SHOWN once.

        CR-27, 2026-08-18. The startup offer used to be a single
        `threading.Timer(3.0, prompt_licence_acceptance)`, and on the first
        machine in the fleet to self-upgrade past the gate it never produced
        a window: the out-of-tree clip popup takes `_popup_active_lock` about
        three seconds earlier, every start, and that machine had 65 clips
        outside the tree (then 102). The lost-race branch resets
        `_licence_prompted` "so the next start still asks" -- but the next
        start loses the same race, because the clips are still outside the
        tree. Three lanes sat parked for hours behind a dialog nobody could
        see.

        This is the re-arm. It stops on `_licence_asked` (the document
        reached a person -- accepting or declining is their call, and a modal
        that comes back after a DECLINE is how an editor learns to dismiss it
        unread) and on the gate clearing. `first_delay` is the original three
        seconds: the tray icon thread has only just started, and this
        dialog's failure path wants somewhere to put a notification.
        """
        if self._stop_event.wait(first_delay):
            return
        while True:
            if not self.eula_problem():
                return          # accepted here, or in the wizard, or fails open
            if self._licence_asked:
                return
            self._show_licence_dialog()
            if self._licence_asked or not self.eula_problem():
                return
            if self._stop_event.wait(interval):
                return

    def _show_licence_dialog(self) -> None:
        """The dialog, under the popup lock like every other Tk root here."""
        document = eula_mod.bundled_text()
        if not document:
            # eula.acceptance_problem() fails OPEN on a missing document, so
            # reaching here with none means the gate is live and the text is
            # not -- a packaging fault we must not paper over by recording an
            # acceptance of nothing.
            log.error("licence dialog: this build bundles no assets/EULA.md -- "
                      "cannot ask anyone to accept it")
            self._notify_tray(
                "NOT SYNCING: this build is missing its licence document. "
                "Tray → Copy diagnostics for your admin.", "ccsync-companion")
            # Settled, for _licence_watch's purposes: retrying a packaging
            # fault every minute produces the same ERROR forever and no
            # window. The tray item still reaches this path on request.
            self._licence_asked = True
            return
        if not self._popup_active_lock.acquire(blocking=False):
            # NOT the end of the attempt any more (CR-27): _licence_asked
            # stays False, so _licence_watch comes back in a minute and keeps
            # coming back until this window is closed. The clip popup wins
            # this race on every start of an affected machine, so "the next
            # start still asks" was a promise the next start could not keep.
            if not self._licence_defer_logged:
                self._licence_defer_logged = True
                log.info("licence dialog: another CCSync window is open -- not "
                         "stacking a second modal on it; retrying every %.0fs "
                         "until it can be shown", LICENCE_RETRY_SECONDS)
            else:
                log.debug("licence dialog: still behind another CCSync window")
            self._licence_prompted = False   # ...so the next start still asks
            return
        try:
            accepted = popup.licence_dialog(
                "CCSYNC.EXE: licence agreement",
                (f"This machine is NOT SYNCING until someone here accepts the "
                 f"{site_mod.product_name()} licence agreement (version "
                 f"{eula_mod.EULA_VERSION}).\n\n"
                 f"Read it below. Accepting records your agreement on this "
                 f"machine only, and syncing starts straight away."),
                document,
            )
        except Exception:
            # Left UNSETTLED on purpose: a Tk root that cannot be built at
            # logon (no window station yet) is the one failure here that a
            # retry a minute later genuinely fixes.
            log.exception("could not show the licence dialog")
            return
        finally:
            self._popup_active_lock.release()

        # It has been read by somebody. Whatever they answered, the automatic
        # offer is done (CR-27) -- the tray item is the way back from here.
        self._licence_asked = True

        if not accepted:
            log.warning("licence agreement DECLINED (or dismissed) -- this "
                        "machine stays not-syncing")
            self._notify_tray(
                "NOT SYNCING: the licence agreement was not accepted. "
                "Tray → Accept the licence agreement…", "ccsync-companion")
            return
        try:
            eula_mod.record_acceptance()
        except OSError:
            # record_acceptance raises OSError precisely so this is not
            # swallowed: an "accepted" that did not persist would show the
            # same dialog forever with no explanation.
            log.exception("licence accepted but the record could not be written")
            self._notify_tray(
                "Couldn't save your acceptance. Check disk space and try again.",
                "ccsync-companion")
            return
        log.info("licence agreement v%s accepted on this machine", eula_mod.EULA_VERSION)
        # STRAIGHT BACK INTO SYNC, no restart. _start_lanes() is the one door
        # every start path goes through and re-checks every other gate (pause,
        # halt, config, drive), so calling it here cannot start lanes that some
        # OTHER refusal is holding down.
        try:
            self._start_lanes()
        except Exception:
            log.exception("could not start the sync lanes after the licence was accepted")
        self._notify_tray("Licence accepted, syncing is starting.", "ccsync-companion")

    def _start_lanes(self) -> None:
        """Actually start the sync lanes/sequencer, per sync_enabled/managed
        mode. Extracted from start() so on_signed_in() can (re)run it once a
        require_login gate clears, without repeating the reporter/manifest/
        watcher startup that only ever needs to happen once."""
        if self._paused:
            # SYNC-3 (2026-08-11): sign-in must not override the tray's Pause.
            # on_signed_in() gated on _lanes_started and the login gate only,
            # so signing in with "Pause syncing" ticked resumed the full
            # rotation AND express uploads while the checkbox still rendered
            # checked. Every other restart entry point already refuses
            # (_root_resume_lanes at the top); this makes the refusal belong
            # to _start_lanes() itself so no future caller can miss it.
            log.info("sync lanes/sequencer NOT started: syncing is paused from the tray")
            return
        if self.halt.active:
            # Above every other refusal below except the tray's own pause:
            # a halt survives restarts precisely so it cannot be cleared by
            # the first thing anyone tries, and _start_lanes() is the ONE
            # door every start path goes through (COMMERCIAL_READINESS.md
            # item 9, 2026-08-17).
            for lane in self.lanes:
                try:
                    with lane._lock:
                        lane._status.detail = self._halt_detail()
                except Exception:
                    pass
            log.warning("sync lanes/sequencer NOT started: %s", self._halt_detail())
            return
        if self.config_problems:
            # validate_config()'s "errors that STOP syncing" used to stop
            # nothing: they were logged and then start() ran anyway. A typo'd
            # remote_root makes lane B's `rclone sync` delete every local
            # proxy tree-wide; a blank local_root makes every destination
            # CWD-relative (AUDIT_2 DEL-3). Same shape as the pending-login
            # gate: lanes stay down with a reason, everything else runs so
            # the machine is still visible and fixable.
            self._mark_lanes_misconfigured()
            log.error(
                "sync lanes/sequencer NOT started: %d config problem(s) that stop syncing "
                "-- fix them in %s and restart",
                len(self.config_problems), config_mod.CONFIG_PATH,
            )
            return
        eula_problem = self.eula_problem()
        if eula_problem:
            # 2026-08-17, COMMERCIAL_READINESS.md item 3: nobody on this
            # machine has agreed to the licence (or agreed to an older
            # version of it), so the lanes do not run. Same shape as the
            # pending-login and DEL-3 gates above -- lanes stay down with a
            # reason on them, everything else (watcher, reporter, tray)
            # still starts, so the machine stays visible and the editor has
            # a route back. The wizard, not the tray, is what records
            # consent: it is the only place the document is actually read.
            # A MISSING BUNDLED DOCUMENT does not land here at all --
            # eula.acceptance_problem() fails open on that (see its
            # docstring); this refusal only ever means "no one accepted".
            self._mark_lanes_eula_not_accepted(eula_problem)
            log.warning("sync lanes/sequencer NOT started: %s", eula_problem)
            return
        if self._root_absent:
            # The tree is not there. Unlike a config problem this needs no
            # restart and no admin: _on_root_present() calls back in here the
            # moment the drive returns.
            self._mark_lanes_root_absent()
            log.warning(
                "sync lanes/sequencer NOT started: local_root %s is not available "
                "(the drive is disconnected)", self.config.get("local_root"),
            )
            return
        if not self._sync_enabled:
            # Base rig: works directly off the NAS share; no lanes, no
            # sequencer, no watchdog. Watcher/fixer/reporter still run.
            for lane in self.lanes:
                try:
                    with lane._lock:
                        lane._status.detail = "sync disabled: this machine works directly off the NAS"
                except Exception:
                    pass
            log.info("sync disabled by config (sync_enabled=false) -- no lanes started")
        elif self._managed:
            try:
                self._lane_c.start()
            except Exception:
                log.exception("failed to start lane %s", getattr(self._lane_c, "name", self._lane_c))
            if self.sequencer is not None:
                try:
                    self.sequencer.start()
                except Exception:
                    log.exception("failed to start sequencer")
            # File events must still reach the sequencer even though lane A's
            # periodic loop stays off in managed mode.
            try:
                self._lane_a.start_watchdog_only()
            except Exception:
                log.exception("failed to start lane A watchdog")
        else:
            for lane in self.lanes:
                if lane is self._lane_b and not self._lane_b_enabled:
                    continue
                try:
                    lane.start()
                except Exception:
                    log.exception("failed to start lane %s", getattr(lane, "name", lane))
        if not self._lane_b_enabled:
            # Surface the why on the tray/dashboard instead of a silent idle.
            try:
                with self._lane_b._lock:
                    self._lane_b._status.detail = "disabled: direct NAS access (lane_b_enabled=false)"
            except Exception:
                pass
            log.info("lane B disabled by config (lane_b_enabled=false)")
        self._lanes_started = True

    def _stop_lanes(self) -> None:
        """Counterpart to _start_lanes() -- stops just the sync lanes/
        sequencer (used by sign_out()); shutdown() also calls this as part
        of full teardown."""
        if self._managed:
            if self.sequencer is not None:
                try:
                    self.sequencer.stop()
                except Exception:
                    log.exception("failed to stop sequencer")
            try:
                self._lane_c.stop()
            except Exception:
                log.exception("failed to stop lane %s", getattr(self._lane_c, "name", self._lane_c))
            # Mirror _start_lanes()'s start_watchdog_only() call: lane A's
            # watchdog observer keeps running otherwise -- feeding
            # sequencer.notify_change() on a now-stopped sequencer after
            # sign-out, or staying live in the outgoing process alongside a
            # freshly self-upgraded instance's own observer on the same
            # tree (see the managed-_stop_lanes finding).
            try:
                self._lane_a.stop()
            except Exception:
                log.exception("failed to stop lane %s", getattr(self._lane_a, "name", self._lane_a))
            # SYNC-1 (2026-08-11): lane B was never stopped in managed mode --
            # and RcloneLane.stop() is the ONLY path to _kill_running_process().
            # sequencer.stop() joins its worker with timeout=10 and returns
            # while it may still be inside lane_b.run_once(); on Windows the
            # rclone child outlives the parent, so a self-upgrade left the old
            # delete-authorised `rclone sync` racing the new process's lane B
            # over one destination (AUDIT_2 L-12/C-7).
            try:
                self._lane_b.stop()
            except Exception:
                log.exception("failed to stop lane %s", getattr(self._lane_b, "name", self._lane_b))
        else:
            for lane in self.lanes:
                try:
                    lane.stop()
                except Exception:
                    log.exception("failed to stop lane %s", getattr(lane, "name", lane))

    def sign_in(self, username: str, password: str) -> tuple[bool, Optional[str]]:
        """Tray-facing: verify credentials against the dashboard and, on
        success, start sync lanes/reporting under the newly-verified
        identity (see on_signed_in()). Safe to call from any thread."""
        ok, error = self.identity.sign_in(username, password)
        if ok:
            log.info("signed in as %s (role=%s)", self.identity.username, self.identity.role)
            self._apply_identity_role()
            # The verify response may have carried the upgrade advertisement
            # -- adopt it now instead of waiting a full report interval.
            # (An absent/None value correctly CLEARS any stale offer.)
            self.upgrade.note_report_response({"upgrade": self.identity.last_upgrade_info})
            try:
                self.on_signed_in()
            except Exception:
                log.exception("sign_in: on_signed_in() failed")
        else:
            log.info("sign-in failed: %s", error)
        return ok, error

    def on_signed_in(self) -> None:
        """Starts sync lanes/the sequencer once a valid identity exists --
        called after a successful sign_in() when require_login had gated
        start() from ever starting them. Idempotent: a no-op once lanes are
        already running, or if login is still not actually satisfied."""
        if self._lanes_started:
            return
        if self._login_gate_blocks_sync():
            return
        try:
            self._start_lanes()
        except Exception:
            log.exception("on_signed_in: failed to start sync lanes")

    def sign_out(self) -> None:
        """Tray-facing: drop the verified identity and, if require_login is
        on, stop sync lanes/the sequencer again (reporting stops too, since
        editor_identity() now returns None -- see reporter.py's post_once).
        Safe to call from any thread."""
        self.identity.sign_out()
        log.info("signed out")
        self._apply_identity_role()  # revert to config.toml's static sync_enabled
        if self._require_login and self._lanes_started:
            try:
                self._stop_lanes()
            except Exception:
                log.exception("sign_out: failed to stop sync lanes")
            self._mark_lanes_pending_login()
            self._lanes_started = False

    # -- tray-facing API ---------------------------------------------------
    def upgrade_available(self) -> Optional[dict[str, Any]]:
        """The available-update info dict ({version, url, sha256, ...}), or
        None. Also None on source (non-frozen) runs -- a self-swap of a
        .py process is meaningless, so the tray item never appears there."""
        if not upgrade_mod.is_frozen():
            return None
        return self.upgrade.available

    def setup_project_available(self) -> Optional[str]:
        """The unmapped Resolve project name the tray should offer to set
        up, or None (mapped / no project open / legacy mode)."""
        if self.project_setup is None:
            return None
        return self.project_setup.unmapped_project

    def setup_current_project(self) -> None:
        """Tray-facing: open the dashboard's /project-setup deep link for
        the currently flagged project."""
        if self.project_setup is not None:
            self.project_setup.trigger_setup()

    def _standing_down_would_kill_work(self) -> str:
        """"" when this process may spawn a replacement and exit, else the
        name of the work that says otherwise ("popup" | "consolidate").

        ONE predicate for every caller of upgrade.restart_self. apply_upgrade
        was hardened against standing this process down mid-copy -- the
        spawned copy is killed inside shutil.copy2, leaving a partial
        .ccsync-tmp and a project where some clips are relinked and some are
        not (AUDIT_2 CORE-H8/H5) -- and R12's stale-bridge recovery then
        reused the same spawn+shutdown sequence with none of those guards, so
        quitting Resolve mid-consolidate was enough to reproduce exactly that
        outcome (COMP-CORE-2, 2026-08-14). A third caller must inherit the
        test rather than have to remember it.
        """
        if self._popup_active_lock.locked():
            return "popup"
        if self._consolidate_active:
            return "consolidate"
        return ""

    def apply_upgrade(self, *, quiet_refusals: bool = False) -> str:
        """Download, verify, swap the exe and restart. Blocking (a ~20 MB
        download) -- the tray calls this on a daemon thread. On failure the
        current build keeps running and the tray says so.

        Returns "" when the swap went through (the process is on its way
        out), else why not: "popup" | "consolidate" (stood down, transient)
        | "failed" | "no-offer". The pushed-update path reads this to decide
        whether to try again (ultrareview 2026-08-19); the tray click and
        auto-update ignore it. `quiet_refusals` skips the stand-down toasts
        -- a retry of a push the editor has already been told about must not
        repeat the same balloon every minute while their window stays open.
        """
        info = self.upgrade.available
        if info is None:
            return "no-offer"
        blocker = self._standing_down_would_kill_work()
        if blocker == "popup":
            if not quiet_refusals:
                self._notify_tray(
                    "Can't update while a CCSync window is open. Close it and try again.",
                    "ccsync-companion")
            return "popup"
        if blocker:
            if not quiet_refusals:
                self._notify_tray(
                    "Can't update while media is being copied in. Let it finish, then try again.",
                    "ccsync-companion")
            return "consolidate"
        # "Installing", not "Updating": the offered build may be OLDER than
        # the running one (upgrade.py's "different, not newer"), and every
        # other string on this path now refuses to call that an update.
        self._notify_tray(f"Installing v{info['version']}…", "ccsync-companion")
        try:
            applied = self.upgrade.apply()
        except Exception:
            log.exception("apply_upgrade: upgrade.apply() raised")
            applied = False
        if not applied:
            self._notify_tray(
                f"Update failed. You're still on v{config_mod.VERSION}, nothing is broken. "
                "Tray → Copy diagnostics for your admin.",
                "ccsync-companion",
            )
            return "failed"
        return ""

    # -- the update ledger (REL-8 / APP-5, resilience sweep 2026-08-28) ----
    def _upgrade_attempts_path(self) -> Path:
        return upgrade_mod.attempts_path(self._state_dir)

    def _load_upgrade_state(self) -> None:
        """Adopt the ledger the last run left behind. Never raises.

        Running AT ALL on the version the ledger was counting failures for
        means the attempt succeeded, however many tries it cost, so the
        counter is cleared here rather than anywhere in the success path (the
        process that swaps the exe is on its way out and cannot write it)."""
        try:
            path = self._upgrade_attempts_path()
            record = upgrade_mod.read_attempts(path)
            if str(record.get("version") or "") == config_mod.VERSION:
                upgrade_mod.clear_upgrade_attempts(path, config_mod.VERSION)
                record = upgrade_mod.read_attempts(path)
            self._upgrade_attempts = record
            self._upgrade_reverted_from = str(record.get("reverted_from") or "")
        except Exception:
            log.exception("could not read the update ledger")

    def _note_report_accepted(self) -> None:
        """One accepted dashboard report: this build works well enough to be
        seen. Never raises -- it runs on the reporter thread."""
        try:
            self._report_accepted.set()
            if self._upgrade_reverted_from:
                # It rode the payload the dashboard just took, so it has been
                # seen once and must not ride every report for the life of
                # the install.
                self._upgrade_reverted_from = ""
                upgrade_mod.clear_reverted_from(self._upgrade_attempts_path())
                self._upgrade_attempts = upgrade_mod.read_attempts(
                    self._upgrade_attempts_path())
        except Exception:
            log.exception("could not clear the crash-loop revert marker")

    def _upgrade_attempt_blocked(self, wanted: str) -> str:
        """"" when another attempt at `wanted` is due, else why not (REL-8).

        The gate is PERSISTED, not the in-memory retry timer: a machine whose
        AV quarantines every download restarts too, and until this existed
        each restart bought the NAS another ~20 MB download every ten
        minutes for ever."""
        try:
            record = self._upgrade_attempts
            if upgrade_mod.upgrade_attempts_exhausted(record, wanted):
                return "given up"
            if not upgrade_mod.upgrade_retry_due(record, wanted):
                return "backing off"
        except Exception:
            log.exception("update back-off check failed")
        return ""

    def _note_upgrade_failure(self, wanted: str) -> float:
        """Count one failed install of `wanted` and return the wait before the
        next try. Never raises."""
        try:
            error = str(getattr(self.upgrade, "last_failure", "") or "") or "failed"
            record = upgrade_mod.note_upgrade_attempt(
                self._upgrade_attempts_path(), wanted, error)
            self._upgrade_attempts = record
            attempts = int(record.get("attempts") or 0)
            if attempts >= upgrade_mod.MAX_UPGRADE_ATTEMPTS:
                log.error(
                    "update to v%s has failed %d times (%s) -- this machine has "
                    "STOPPED trying. The tray says so; the report carries it",
                    wanted, attempts, error)
                return float(upgrade_mod.UPGRADE_BACKOFF_SECONDS[-1])
            return upgrade_mod.upgrade_backoff_seconds(attempts)
        except Exception:
            log.exception("could not record the failed update attempt")
            return PUSHED_UPDATE_FAILED_RETRY_SECONDS

    def transport_health(self) -> dict[str, Any]:
        """Connection-path + orphan diagnostics for the report payload
        (AUDIT_2 C-6).

        This signal does not exist anywhere in production today, which is why
        a RELAYED editor and a merely slow one are indistinguishable on the
        fleet grid. Syncthing devices are added with addresses:["dynamic"]
        and relaysEnabled/globalAnnounceEnabled left at their `true`
        defaults, so lane C can silently ride the public relay pool at
        1-5 MB/s -- and the NAS peer is measurably DERP-relayed right now.
        `syncthing.relayed` being non-empty is the whole answer.

        Never raises: each half is isolated, because a diagnostic that can
        fail the report cycle is worse than no diagnostic.
        """
        health: dict[str, Any] = {}
        try:
            summary = getattr(self._lane_c, "connection_path_summary", None)
            if summary is not None:
                health["syncthing"] = summary()
        except Exception:
            log.exception("connection_path_summary() failed")
        for lane, key in ((self._lane_a, "lane_a"), (self._lane_b, "lane_b")):
            try:
                getter = getattr(lane, "orphan_report", None)
                if getter is None:
                    continue
                report = getter()
                if report:
                    health.setdefault("orphans", {})[key] = report
            except Exception:
                log.exception("orphan_report() failed for %s", getattr(lane, "name", lane))
        # Express-lane counters (AUDIT_2 P9/C-2). An express failure is
        # deliberately a warning + counter rather than STATE_ERROR, so
        # without this the server has no way to see one at all.
        try:
            getter = getattr(self._lane_a, "express_report", None)
            if getter is not None:
                report = getter()
                if report:
                    health["express"] = report
        except Exception:
            log.exception("express_report() failed")
        return health

    # -- the safety latches (COMMERCIAL_READINESS.md item 9, 2026-08-17) ----
    def job_capabilities(self) -> dict[str, Any]:
        """The `capabilities` report section (phase 0). Never raises.

        The idle probe is THE SAME OBJECT the job runner gates on, so what
        this machine tells the dashboard and what it will actually agree to do
        cannot drift apart. Resolve is asked only whether its PROCESS is
        running (resolve_prefs, fails closed) -- nothing here goes near
        scriptapp() on a 30 s cadence (CR-68).
        """
        try:
            return capabilities_mod.build(
                self.config,
                idle_probe=self._jobs_idle_probe,
                resolve_running_fn=resolve_prefs_mod.resolve_is_running,
                resolve_project_fn=lambda: getattr(
                    self.watcher, "last_resolve_project", None),
            )
        except Exception:
            log.exception("could not build the capabilities section")
            return {}

    def sync_guard(self) -> dict[str, Any]:
        """The `sync_guard` report section: breaker, trash, halt, and lane A's
        "skipped, exists" counter.

        These are the four states an admin cannot see any other way. A tripped
        breaker on one editor's machine looks EXACTLY like a quiet lane B on
        the fleet grid -- idle, green, no error -- which is why it is a
        reported field and a dashboard alarm rather than only a tray line.

        Never raises: same contract as transport_health, and for a stronger
        reason -- a diagnostic that can fail the report cycle would take the
        alarm down with it."""
        guard: dict[str, Any] = {}
        try:
            guard.update(self._lane_b.sync_guard_report())
        except Exception:
            log.exception("lane B sync_guard_report() failed")
        try:
            mismatches = getattr(self._lane_a, "size_mismatch_report", lambda: None)()
            if mismatches:
                guard["skipped_exists"] = mismatches
        except Exception:
            log.exception("size_mismatch_report() failed")
        try:
            # UX-3 (resilience sweep 2026-08-28): a project folder that was
            # here last pass and has gone. Absent while every selected project
            # is where it should be -- an absent key is how "nothing has been
            # renamed under us" is spelled, and it is what clears the chip.
            moved = getattr(self._lane_a, "moved_project_dirs", lambda: [])()
            if moved:
                guard["moved_project_dirs"] = list(moved)[:20]
        except Exception:
            log.exception("moved_project_dirs() failed")
        try:
            # SYNC-10: project folders in no sync plan at all. Absent until
            # the first scan has run, because "we have not looked" and "there
            # are none" must not render the same.
            strays = getattr(self._lane_a, "stray_projects", lambda: None)()
            if strays and strays.get("count"):
                guard["stray_projects"] = strays
        except Exception:
            log.exception("stray_projects() failed")
        try:
            # MEDIA-3: how much staging the ingest feature is holding, so the
            # disk it fills is attributable before it refuses the next drop.
            staging = self.ingest_staging_report()
            if staging and staging.get("bytes"):
                guard["ingest_staging"] = staging
        except Exception:
            log.exception("ingest_staging_report() failed")
        try:
            guard["halt"] = self.halt.report()
        except Exception:
            log.exception("halt.report() failed")
        try:
            # APP-1 (resilience sweep 2026-08-28): whether the dashboard is
            # ACCEPTING this machine's reports. It rides the report it is
            # about, which sounds circular and is not: what an admin reads on
            # the grid is the streak that ENDED, i.e. "this machine was
            # rejected 40 times before this one got through", and the machine
            # that is being rejected right now shows its last accepted report
            # ageing on the grid with the reason in the tray and in
            # diagnostics.
            guard["reporter"] = self.reporter.health()
        except Exception:
            log.exception("reporter health() failed")
        try:
            # APP-13/SYS-4: the dashboard's own received_at against this
            # machine's clock. Absent until a reply has carried one, because
            # "we could not check" must never render as zero skew.
            skew = getattr(self.reporter, "clock_skew_seconds", None)
            if skew is not None:
                guard["clock_skew_seconds"] = skew
        except Exception:
            log.exception("reporter clock skew read failed")
        try:
            # APP-6: a background thread died and the tray stayed green.
            # Omitted while the count is zero, on the same terms as
            # skipped_exists: an absent key is how "nothing has crashed" is
            # spelled, which is also what clears the chip.
            crashes = crash_report.crash_summary(self.config)
            if crashes.get("count"):
                guard["crashes"] = crashes
        except Exception:
            log.exception("crash_summary() failed")
        try:
            # SYNC-5 (resilience sweep 2026-08-28): the projects lane C is
            # deliberately keeping paused because their .stignore never
            # landed. Absent while nothing is parked, so an absent key is how
            # "every selected folder is filtered" is spelled. Lane C's own
            # state/last_error carries the sentence for the tray and the grid;
            # this is the machine-readable half, so the dashboard can name the
            # projects without parsing a string.
            unfiltered = getattr(self._lane_c, "unfiltered_folders", lambda: [])()
            if unfiltered:
                guard["folders_unfiltered"] = list(unfiltered)[:20]
        except Exception:
            log.exception("unfiltered_folders() failed")
        try:
            # UX-7 (resilience sweep 2026-08-28): Syncthing conflict copies
            # this machine holds. Free: the manifest walk already visited
            # every file, so this is a cached dict read. Absent when there are
            # none. Reported, not acted on -- which side of a conflict is
            # wanted is the owner's judgement, never ours.
            conflicts = self.manifest_cache.sync_conflicts()
            if conflicts:
                guard["sync_conflicts"] = conflicts
        except Exception:
            log.exception("sync_conflicts() failed")
        try:
            # Empty while the sync engine is up, so an absent section is how
            # "Syncthing is running" is spelled (SYNC-17, 2026-08-18). The
            # lane C error says it too, but the lane says only what is wrong
            # NOW -- this one carries how long it has been down and how many
            # restarts have failed, which is the difference between "he
            # rebooted" and "that machine has needed a human since Tuesday".
            #
            # THE DASHBOARD DOES NOT READ THIS YET: `SyncGuardIn` does not
            # declare the key, and `extra="ignore"` drops it (BROLL-ING-1 is
            # what that costs when nobody says so out loud). What raises the
            # alarm today is lane C's own `state`/`last_error`, which are
            # declared and do reach the grid. This section is here so the
            # dashboard half is a schema change and not a fleet-wide
            # companion release.
            supervisor = self.syncthing_supervisor.report()
            if supervisor:
                guard["syncthing_supervisor"] = supervisor
        except Exception:
            log.exception("syncthing supervisor report() failed")
        try:
            # SYS-2 (resilience sweep 2026-08-28): the loop threads the
            # watchdog has had to restart. Absent while it has never had to,
            # which is the normal state and the thing that clears the chip.
            # Reported rather than only self-healed on purpose: a machine that
            # needs its sequencer restarted three times an hour is syncing in
            # fits and starts, and self-healing silently is how that stays
            # invisible for a month.
            watchdog = self._lane_watchdog
            restarts = watchdog.report() if watchdog is not None else {}
            if restarts:
                guard["restarts"] = restarts
        except Exception:
            log.exception("thread watchdog report() failed")
        if self._removal_overrides:
            # Not drained: an overridden removal is small and must survive a
            # failed POST, unlike the completed-file feed (which is a
            # history and can afford to lose a tick).
            guard["removal_overrides"] = list(self._removal_overrides)[-5:]
        try:
            # SYS-1 (resilience sweep 2026-08-28): the server's stall rule is
            # THREE ROTATIONS, so it needs this machine's rotation. Absent
            # (older build) leaves health.lane_stall on its 30 min floor.
            rotation = float(self.config.get("project_rotation_seconds", 0) or 0)
            if rotation > 0:
                guard["rotation_seconds"] = rotation
        except Exception:
            log.exception("rotation_seconds report failed")
        try:
            # REL-8 / APP-5 (resilience sweep 2026-08-28): what this machine's
            # updates are DOING. Always present, including the all-zero
            # shape: "this computer has never failed an update" is an answer
            # the fleet grid needs, and an absent section could only mean "a
            # companion too old to send one". `reverted_from` rides until one
            # report has been accepted with it (_note_report_accepted).
            record = dict(self._upgrade_attempts or {})
            record["reverted_from"] = self._upgrade_reverted_from
            guard["upgrade"] = upgrade_mod.upgrade_report(
                record, self._version_starts)
        except Exception:
            log.exception("upgrade report failed")
        try:
            # SYNC-2: the root guard's answer as a plain string, so the grid
            # can tell "the drive is out" from "the drive is wedged" without
            # parsing a lane detail. Always present -- including `unknown`,
            # which is "we could not tell" and must not read as `present`.
            guard["root_state"] = str(self._root_state)
        except Exception:
            log.exception("root_state read failed")
        try:
            # SYS-5 / SYNC-7: free space on the sync drive and the OS drive.
            # Measured once per HEAVY tick and memoised, because the guard
            # section rides every light tick too.
            disk = self.disk_snapshot()
            if disk:
                guard["disk"] = disk
        except Exception:
            log.exception("disk snapshot failed")
        try:
            # UX-4 / RES-12 / APP-2 (resilience sweep 2026-08-28): what
            # Resolve can and cannot see on this machine. ALWAYS present,
            # including the all-zero shape -- an absent section could only
            # mean "a companion too old to send one", and `last_scan_at`
            # carries the difference between zero and never-looked.
            guard["resolve_health"] = self.resolve_health()
        except Exception:
            log.exception("resolve_health() failed")
        try:
            # SYNC-15, and it is LAST on purpose: it is derived from the keys
            # above (and from the lane/latch state), so assembling it here
            # means one place reads one already-built picture.
            blocked = self.blocked_report(guard)
            if blocked:
                guard["blocked"] = blocked
        except Exception:
            log.exception("blocked_report() failed")
        return guard

    # -- free space (SYS-5 / SYNC-7, resilience sweep 2026-08-28) ----------
    def disk_snapshot(self) -> dict[str, Any]:
        """`sync_guard.disk`, at most once per heavy report interval.

        Two `shutil.disk_usage` calls is nothing, but the sync_guard section
        is rebuilt on every LIGHT tick as well (every 5 s while a lane is
        active), and two stat-family syscalls against a drive that has just
        stopped answering is exactly the hot path SYNC-2 is about. The heavy
        cadence is `dashboard_report_interval`, the same one the manifest
        refresh runs on. Never raises."""
        try:
            ttl = max(30.0, float(config_mod.coerce_numeric(
                self.config, "dashboard_report_interval", 60)))
        except Exception:
            ttl = 60.0
        now = time.monotonic()
        if self._disk_snapshot and (now - self._disk_snapshot_at) < ttl:
            return dict(self._disk_snapshot)
        snapshot = lane_guard.disk_report(self.config.get("local_root", ""))
        self._disk_snapshot = snapshot
        self._disk_snapshot_at = now
        return dict(snapshot)

    # -- a project folder that moved (UX-3, resilience sweep 2026-08-28) ---
    def put_project_dir_back(self, subpath: str = "") -> str:
        """Move a renamed/moved project folder back where CCSync expects it.

        The self-heal half of UX-3, and it is DELIBERATELY a click rather
        than something lane A does on its own: the folder in the wrong place
        is the one the editor has been working in, and moving an editor's
        directory without asking is not a thing this system does. Goes
        through `repath._move_dir`, the same move the server-side repath
        uses -- which refuses when the target already exists and never
        deletes anything.

        Returns the sentence to show. Never raises."""
        try:
            moved = list(self._lane_a.moved_project_dirs())
        except Exception:
            log.exception("put_project_dir_back: could not read the moved list")
            return "CCSync could not check where that folder is. See the log."
        key = str(subpath or "").strip().replace("\\", "/").strip("/")
        if key:
            moved = [m for m in moved
                     if str(m.get("subpath") or "").strip("/") == key]
        candidates = [m for m in moved if m.get("found") and m.get("expected")]
        if not candidates:
            return ("CCSync cannot find that project folder anywhere on this "
                    "computer. If you moved it to another drive, move it back by "
                    "hand.")
        repather = None
        try:
            repather = self.sequencer.repather if self.sequencer else None
        except Exception:
            repather = None
        if repather is None:
            return "CCSync is still starting up. Try again in a moment."
        done, failed = [], []
        for entry in candidates:
            slug = str(entry.get("slug") or "")
            found = str(entry.get("found") or "")
            expected = str(entry.get("expected") or "")
            try:
                ok = repather._move_dir(slug or "a project", found, expected)
            except Exception:
                log.exception("put_project_dir_back: move failed for %s", slug)
                ok = False
            (done if ok else failed).append(expected)
        if failed and not done:
            return ("CCSync could not move that folder back. Close Resolve and "
                    "Explorer on it and try again.")
        if failed:
            return (f"{len(done)} folder(s) put back; {len(failed)} could not be "
                    "moved. Close Resolve and Explorer on them and try again.")
        return (f"{len(done)} project folder(s) put back where CCSync expects "
                "them. Syncing starts again on the next pass.")

    # -- ingest staging (MEDIA-3, resilience sweep 2026-08-28) -------------
    def _ingestors(self) -> list[Any]:
        return [i for i in (self.broll_ingestor, self.music_ingestor) if i is not None]

    def ingest_staging_report(self) -> dict[str, Any]:
        """`sync_guard.ingest_staging`: bytes/batches/oldest across both
        ingest kinds. {} when neither is wired. Never raises."""
        total, batches = 0, 0
        oldest: Optional[str] = None
        for ingestor in self._ingestors():
            try:
                one = ingestor.staging_report()
            except Exception:
                log.debug("staging_report() failed", exc_info=True)
                continue
            total += int(one.get("bytes") or 0)
            batches += int(one.get("batches") or 0)
            at = one.get("oldest_at")
            if at and (oldest is None or str(at) < oldest):
                oldest = str(at)
        if not batches and not total:
            return {}
        return {"bytes": total, "batches": batches, "oldest_at": oldest}

    def clear_finished_ingest_staging(self) -> str:
        """Delete every staging directory whose batch is over, now.

        The button behind MEDIA-3's space refusal: the feature filled its own
        disk with a dot-folder no editor has any UI to see, and then blamed
        the editor for it. Only FINISHED batches -- the running one is never
        touched."""
        removed, freed = 0, 0
        for ingestor in self._ingestors():
            try:
                one = ingestor.prune_staging(max_age_days=0)
            except Exception:
                log.exception("prune_staging() failed")
                continue
            removed += int(one.get("removed") or 0)
            freed += int(one.get("bytes") or 0)
        if not removed:
            return "There is no finished staging to clear on this computer."
        return (f"Cleared {removed} finished staging folder(s), "
                f"{freed / 1e9:.1f} GB.")

    # -- the one sentence: why is this machine not syncing? (SYNC-15) -------
    #
    # Each of these latches already had its own state, its own file and its
    # own (or no) report field, and the fleet page had to infer "why is this
    # machine doing nothing" from a lane state that SYNC-1/5/9 all show can
    # be wrong. Nothing new is computed here: every value is already in
    # memory, and the whole point is that ONE ordered list decides which of
    # them an admin is shown first. The order is the contract the dashboard's
    # health.why_not_syncing mirrors, and it is ordered by what the reader can
    # ACT on: the editor's own sign-in before the admin's halt, a wedged
    # drive before a tripped breaker, a real blockage before a mere pause.
    _BLOCKED_ORDER = (
        "not_signed_in", "licence_pending", "clock_skew", "root_absent",
        "root_not_answering", "root_misplaced", "disk_full", "fleet_halt",
        "local_halt", "paused", "breaker_tripped", "no_selection",
        # UX-3 (sweep 2026-08-28): after no_selection, because a machine with
        # no plan at all is the bigger fact -- but ahead of the filter/stall
        # reasons, since a folder that is not where we expect it is a thing
        # the editor themselves can put back in a minute.
        "project_dir_moved",
        "folders_unfiltered", "lane_stalled", "syncthing_down",
        "transport_offline",
    )

    def blocked_report(self, guard: Optional[dict] = None) -> Optional[dict[str, Any]]:
        """`sync_guard.blocked` = {reason, detail, since}, or None.

        None means nothing is blocking, and it is the ONLY thing that means
        that: an absent key is how "this machine is syncing" is spelled, the
        same shape `crashes` and `folders_unfiltered` use. Never raises -- a
        diagnostic that can fail the report cycle would take the alarm down
        with it, and every candidate is isolated so one broken getter cannot
        hide a lower-priority reason.
        """
        found: dict[str, tuple[str, Optional[str]]] = {}
        for reason in self._BLOCKED_ORDER:
            try:
                answer = self._blocked_candidate(reason, guard or {})
            except Exception:
                log.exception("blocked_report: the %s check failed", reason)
                continue
            if answer is not None:
                found[reason] = answer
        for reason in self._BLOCKED_ORDER:
            if reason not in found:
                continue
            detail, since = found[reason]
            # `since` for a reason that carries no timestamp of its own: the
            # first report that named it. Kept in memory only -- it is a
            # display nicety, not a latch, and a restart honestly resets it.
            if not since:
                since = self._blocked_since.get(reason) or ""
                if not since:
                    since = datetime.now(timezone.utc).isoformat()
            self._blocked_since = {reason: since}
            return {"reason": reason, "detail": detail, "since": since or None}
        self._blocked_since = {}
        return None

    def _blocked_candidate(
        self, reason: str, guard: dict
    ) -> Optional[tuple[str, Optional[str]]]:
        """(detail, since) when `reason` applies right now, else None.

        One function rather than sixteen so the order above is the only place
        priority lives. Every `detail` is a sentence an editor can read: it is
        what the tray shows and what the dashboard renders at the top of the
        machine's row."""
        if reason == "not_signed_in":
            if self._login_gate_blocks_sync():
                return ("Nobody is signed in to CCSync on this computer, so nothing "
                        "is syncing", None)
            return None
        if reason == "licence_pending":
            problem = self.eula_problem()
            if problem:
                return (str(problem), None)
            return None
        if reason == "clock_skew":
            skew = getattr(self.reporter, "clock_skew_seconds", None)
            if skew is None:
                return None
            if abs(float(skew)) < reporter_mod.CLOCK_SKEW_WARN_SECONDS:
                return None
            return (f"This computer's clock is "
                    f"{reporter_mod.skew_phrase(float(skew))} the server's, so proxy "
                    "download will not transfer anything", None)
        if reason in ("root_absent", "root_not_answering", "root_misplaced"):
            wanted = {
                "root_absent": root_guard_mod.ROOT_ABSENT,
                "root_not_answering": root_guard_mod.ROOT_NOT_ANSWERING,
                "root_misplaced": root_guard_mod.ROOT_MISPLACED,
            }[reason]
            if self._root_state != wanted:
                return None
            return (root_guard_mod.state_sentence(wanted),
                    self._root_state_since or None)
        if reason == "disk_full":
            floor = (guard.get("disk_floor") or {})
            if not floor.get("parked"):
                return None
            return (f"Not downloading proxies: "
                    f"{floor.get('reason') or 'this drive is nearly full'}",
                    str(floor.get("at") or "") or None)
        if reason in ("fleet_halt", "local_halt"):
            halt = guard.get("halt") or {}
            if not halt.get("active"):
                return None
            is_fleet = str(halt.get("scope") or "") == lane_guard.HALT_SCOPE_FLEET
            if is_fleet != (reason == "fleet_halt"):
                return None
            return (self._halt_detail(), str(halt.get("at") or "") or None)
        if reason == "paused":
            if not self._paused:
                return None
            return ("Syncing is paused from this computer's tray", None)
        if reason == "breaker_tripped":
            breaker = guard.get("lane_b_breaker") or {}
            if not breaker.get("tripped"):
                return None
            return (f"Proxy download is stopped as a safety measure: "
                    f"{breaker.get('reason') or 'a safety check failed'}",
                    str(breaker.get("tripped_at") or "") or None)
        if reason == "no_selection":
            state, detail = self.sequencer_state()
            if state != STATE_NO_SELECTION:
                return None
            return ("No projects are ticked for this computer"
                    + (f" ({detail})" if detail else ""), None)
        if reason == "project_dir_moved":
            moved = [m for m in (guard.get("moved_project_dirs") or [])
                     if isinstance(m, dict)]
            if not moved:
                return None
            first = moved[0]
            label = str(first.get("subpath") or "").rstrip("/").split("/")[-1] \
                or str(first.get("slug") or "a project")
            sentence = (f"Your project folder for {label} is not where CCSync "
                        "expects it. Did you rename or move it?")
            if len(moved) > 1:
                sentence += f" ({len(moved)} project folders are missing)"
            return (sentence, None)
        if reason == "folders_unfiltered":
            slugs = [str(s) for s in (guard.get("folders_unfiltered") or []) if s]
            if not slugs:
                return None
            return (f"{len(slugs)} project(s) are not sharing yet - waiting for their "
                    f"filter list: {', '.join(slugs[:3])}", None)
        if reason == "lane_stalled":
            stalled = guard.get("stalled") or self._lane_stall_record()
            if not isinstance(stalled, dict) or not stalled.get("lane"):
                return None
            try:
                minutes = max(1, int(float(stalled.get("seconds") or 0) // 60))
            except (TypeError, ValueError):
                minutes = 1
            return (f"Lane {stalled.get('lane')} stopped making progress for "
                    f"{minutes} minute(s) and was restarted",
                    str(stalled.get("at") or "") or None)
        if reason == "syncthing_down":
            supervisor = guard.get("syncthing_supervisor") or {}
            since = str(supervisor.get("down_since") or "")
            if not since:
                return None
            return ("The sync engine (Syncthing) is not running on this computer, so "
                    "project files are not being shared", since)
        if reason == "transport_offline":
            # LAST, and deliberately the weakest evidence in the list: both
            # rclone lanes failing at once is what "the NAS is unreachable"
            # looks like from here, and it is only ever reported when nothing
            # more specific applies.
            states = {}
            for lane in (self._lane_a, self._lane_b):
                try:
                    status = lane.status()
                except Exception:
                    return None
                states[status.name] = status
            errors = [s for s in states.values() if s.state == STATE_ERROR]
            if len(errors) < 2:
                return None
            return ("This computer cannot reach the server: "
                    + str(errors[-1].last_error or "both sync lanes are failing"), None)
        return None

    # The stall record another agent's watchdog writes (wave 2, SYNC-1).
    # Read, never written, here: a file that does not exist is simply a
    # companion that has never killed a stalled lane.
    _LANE_STALL_FILENAME = "lane_stall.json"

    def _lane_stall_record(self) -> dict[str, Any]:
        try:
            path = (config_mod.resolved_log_path(self.config).parent / "state"
                    / self._LANE_STALL_FILENAME)
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        except Exception:
            log.debug("could not read the lane stall record", exc_info=True)
            return {}
        return data if isinstance(data, dict) else {}

    def resume_lane_b(self, by: str = "tray",
                      request_id: Optional[str] = None) -> tuple[bool, str]:
        """Clear the lane B breaker after the operator has checked the
        server. Returns (ok, message); never raises.

        `by` is only ever a log label -- "tray" for the editor's own click,
        an admin's username when the dashboard asked (CR-45). Both are the
        same assertion about the server; neither is more privileged.

        `request_id` is the dashboard request's `requested_at` stamp, and it
        is what makes a remote resume ONE-SHOT (comp-lanes-ab-2,
        2026-08-21): the dashboard keeps the request standing on every reply
        until a report says the breaker is clear, so a pass that re-trips
        inside the report interval used to be resumed again by the next
        reply, and again, moving another --max-delete 100 proxies into
        .ccsync-trash each cycle from a single admin click -- the unbounded
        sequence the breaker exists to stop. One click resumes once; a later
        trip is a later judgement and needs a fresh one. Persisted, because a
        latch that lives only in memory is cleared by the tray restart an
        editor tries first (the breaker's own state file, beside the latch
        it clears -- see LaneBBreaker.resume)."""
        # The SAME button clears the free-space park (SYS-5 / SYNC-7,
        # resilience sweep 2026-08-28). One [ RESUME ] rather than a second
        # one beside it: from the editor's side both are "proxy download is
        # stopped and I have done something about it", and a second button
        # that is dark most of the time is a button nobody finds. The park is
        # cleared FIRST so a machine parked for space and not tripped at all
        # still gets its pass.
        disk_cleared = False
        try:
            latch = getattr(self, "disk_floor", None)
            if latch is not None:
                disk_cleared = bool(latch.resume(by))
        except Exception:
            log.exception("resume_lane_b: could not clear the free-space park")
        try:
            if not self._resume_lane_b_breaker(by, request_id) and not disk_cleared:
                # Not tripped, or this request has already been applied here.
                return False, "proxy download is not stopped"
        except Exception:
            log.exception("resume_lane_b failed")
            return False, "could not resume proxy download -- see the log"
        # A resumed lane must actually get a turn: without this the editor
        # waits a whole rotation to find out whether the button worked.
        try:
            self._lane_b.arm()
        except Exception:
            log.exception("resume_lane_b: arm() failed")
        if self._managed and self.sequencer is not None:
            try:
                self.sequencer.trigger_pass_now()
            except Exception:
                log.exception("resume_lane_b: could not trigger a pass")
        # OFF-CYCLE, before that pass can re-trip (comp-lanes-ab-2,
        # 2026-08-21). The reporter's next tick was chosen before this reply
        # arrived -- 60 s with nothing SYNCING, which is exactly the parked
        # state a resume ends -- and the dashboard only drops the standing
        # request when it sees a report with the breaker clear. Telling it
        # now is what keeps a re-trip inside that window from being resumed
        # by a request nobody renewed.
        self._report_off_cycle("lane B resumed")
        return True, "Proxy download resumed."

    def _resume_lane_b_breaker(self, by: str, request_id: Optional[str]) -> bool:
        """rclone_lane.resume_after_trip, with the request id when that half
        accepts one (comp-lanes-ab-2, 2026-08-21).

        The breaker is where the one-shot rule lives -- it persists the
        applied request beside the latch it clears -- so this only has to
        hand the id over. Probed rather than assumed, because a lane double
        or an older build may not take one: such a lane still RESUMES (a
        button that stops working is worse than the repeat), and says so, so
        the missing half is discoverable from the log rather than from a
        second afternoon of proxies in the trash."""
        resume = self._lane_b.resume_after_trip
        if not request_id:
            return bool(resume(by))
        try:
            import inspect

            params = inspect.signature(resume).parameters
            takes_id = "request_id" in params or any(
                p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())
        except (TypeError, ValueError):
            takes_id = False
        if not takes_id:
            log.warning("this lane does not remember which resume request it has "
                        "applied -- a standing dashboard request can resume more "
                        "than one trip (comp-lanes-ab-2)")
            return bool(resume(by))
        return bool(resume(by, request_id=request_id))

    def _report_off_cycle(self, why: str) -> None:
        """Post ONE light report now, on a thread of its own. Never raises.

        Its own thread because every caller so far is the reporter thread
        itself, inside on_report_response -- posting inline would nest a
        report inside a report (comp-lanes-ab-2, 2026-08-21). Light: the
        sync_guard section rides every tick including light ones, and that
        section is the whole reason to post early."""
        def _post() -> None:
            try:
                self.reporter.post_once(light=True)
            except Exception:
                log.debug("off-cycle report (%s) failed", why, exc_info=True)

        try:
            threading.Thread(target=_post, name="ccsync-report-off-cycle",
                             daemon=True).start()
        except Exception:
            log.debug("could not post an off-cycle report (%s)", why, exc_info=True)

    def halt_all_sync(self, reason: str, scope: str = lane_guard.HALT_SCOPE_LOCAL) -> tuple[bool, str]:
        """STOP -- not pause. Stops lanes A and B AND pauses every lane C
        folder through Syncthing's own REST API, and persists it so a restart
        does not undo it.

        Pause (toggle_pause) deliberately leaves lane C running: it exists for
        "my uplink is bad", and the assets lane is small. This is the other
        button, the one an editor or an admin reaches for when something is
        wrong and the answer is "stop touching the files" -- lane C carries
        project files, Fusion comps and audio, so a halt that left it running
        would not be a halt (COMMERCIAL_READINESS.md item 9)."""
        changed = self.halt.engage(reason, scope)
        try:
            self._stop_lanes()
        except Exception:
            log.exception("halt: could not stop the rclone lanes")
        self._lanes_started = False
        self._set_express_paused(True)
        paused = self._pause_lane_c_folders(True)
        for lane in self.lanes:
            try:
                with lane._lock:
                    lane._status.detail = self._halt_detail()
            except Exception:
                pass
        if changed:
            self._notify_tray(
                f"SYNCING IS STOPPED on this machine.\n{reason}\n"
                "Nothing is uploading, downloading or sharing until it is started "
                "again.", "ccsync-companion: syncing stopped",
            )
        log.warning("sync halted (%s): %s -- %d lane C folder(s) paused",
                    scope, reason, paused)
        return True, "Syncing is stopped."

    def release_halt(self, by: str = "tray", force: bool = False) -> tuple[bool, str]:
        """Undo halt_all_sync. A FLEET halt refuses here (force=True is the
        dashboard's own release, applied from the report reply)."""
        ok, message = self.halt.release(by=by, force=force)
        if not ok:
            return False, message
        self._release_lane_c_folders()
        self._set_express_paused(self._paused)
        try:
            self._start_lanes()
        except Exception:
            log.exception("halt release: could not start the lanes")
        return True, message

    def _halt_detail(self) -> str:
        reason = self.halt.reason
        who = ("your administrator stopped syncing for the whole fleet"
               if self.halt.scope == lane_guard.HALT_SCOPE_FLEET
               else "syncing is STOPPED on this machine")
        return f"STOPPED: {who}" + (f" -- {reason}" if reason else "")

    def _release_lane_c_folders(self) -> None:
        """Put lane C back after a halt is lifted. Never raises.

        Through the sequencer, NOT by PATCHing `paused: false` onto every
        folder the halt paused (sync-safety-4, CR-48, CR-67 item 1): that
        bypassed the "its .stignore never landed, stay paused" latch, so a
        release could put an unfiltered `sendreceive` folder online and offer
        every original and every Proxy/ file to the fleet. release_for_halt()
        goes through _unpause_all's existing ignores-confirmed filter and
        re-reconciles the shared asset libraries, which the halt now pauses
        too. A failure here is logged and left paused: staying paused is the
        safe side of this decision, and the next pass sweeps it up.

        The direct unpause survives only as the no-sequencer fallback (legacy
        mode, and any sequencer double that predates release_for_halt), where
        nothing else would ever release the folders at all."""
        release = getattr(self.sequencer, "release_for_halt", None)
        if release is None:
            self._pause_lane_c_folders(False)
            return
        try:
            release()
        except Exception:
            log.exception("halt release: the sequencer could not release lane C "
                          "-- the folders stay paused until the next pass")

    def _pause_lane_c_folders(self, paused: bool) -> int:
        """Pause/unpause every lane C folder through Syncthing's REST API.

        Lane C is not a process this companion owns -- Syncthing runs as its
        own service and would happily keep syncing through a stopped
        companion -- so stopping it means PAUSING ITS FOLDERS, which is a
        config write per folder (see SyncthingAdmin.set_folder_paused; each
        commits and restarts the folder, hence the long write timeout).

        Only the folders this editor is actually assigned: a halt must not
        touch some other tool's folders on a shared machine. Returns how many
        were written; never raises."""
        if self.syncthing_admin is None:
            return 0
        try:
            # halt_folder_ids() is the project selection PLUS the fleet-wide
            # asset libraries (sync-safety-2, CR-48, CR-67 item 1). This walked
            # expected_folder_slugs() alone, which names no shared folder, so a
            # halt pressed BECAUSE a bad ingest or a mass rename in the B-roll
            # archive was spreading left exactly those folders syncing on every
            # machine in the fleet. getattr, not a hard call: a sequencer
            # double (and any build older than this one) has only the
            # selection list, and the halt must still pause what it can.
            lister = getattr(self.sequencer, "halt_folder_ids", None)
            if lister is None:
                lister = getattr(self.sequencer, "expected_folder_slugs", None)
            folders = lister() if lister is not None else []
        except Exception:
            log.exception("halt: could not list lane C folders")
            return 0
        written = 0
        for folder_id in folders or []:
            try:
                self.syncthing_admin.set_folder_paused(folder_id, paused)
                written += 1
            except Exception:
                log.warning("halt: could not %s Syncthing folder %s",
                            "pause" if paused else "resume", folder_id, exc_info=True)
        return written

    def _on_upgrade_available(self, info: dict[str, Any]) -> None:
        """A new offer arrived. Tell the editor, and -- where the site has
        turned unattended updates on -- take it without waiting for a click.

        The toast wording comes from offer_toast, not a hardcoded "Update
        available": the dashboard advertises whatever it publishes as
        `current`, which may be OLDER than what this machine runs
        (upgrade.py's "different, not newer"). Calling a downgrade an update
        is how a rollback offer became a one-click loss of everything the
        running build fixed (seen live 2026-07-25: v0.4.5 offered
        "Update ... -> v0.4.3").

        AUTO-APPLY (2026-08-18) is the same distinction, with teeth: a site
        that turned `auto_update` on is saying "take new builds", not "take
        whatever the dashboard says", so a rollback is still offered and
        never taken silently. An admin pushing one deliberately has its own
        path (_apply_pushed_update), which is explicit about being a
        rollback. site.feature_enabled fails CLOSED: no manifest, an older
        dashboard, an unreadable cache all mean "wait for the click"."""
        try:
            self._notify_tray(
                upgrade_mod.offer_toast(info["version"]), "ccsync-companion")
        except Exception:
            log.exception("could not notify about the available build")
        try:
            if not site_mod.feature_enabled("auto_update"):
                return
            rank = upgrade_mod.compare_to_running(info.get("version"))
            if rank != upgrade_mod.VERSION_NEWER:
                log.info(
                    "auto-update: v%s is not newer than v%s -- leaving it to the "
                    "tray. Rolling a fleet BACKWARDS is an admin decision, not "
                    "something that happens because a flag is on",
                    info.get("version"), config_mod.VERSION,
                )
                return
            # ARMED, not fired-and-forgotten (comp-app-core-4, 2026-08-21):
            # _maybe_auto_update() re-attempts from the next report while
            # this version is still the offer in hand, with the pushed
            # update's back-off. See _run_auto_update.
            self._auto_update_version = str(info.get("version") or "").strip()
            self._auto_update_retry_at = 0.0
            self._maybe_auto_update()
        except Exception:
            log.exception("auto-update check failed -- leaving the offer to the tray")

    def _maybe_auto_update(self) -> None:
        """Take the armed unattended update, now or on a later report.

        The gate is the OFFER, not the clock: an offer that has moved on
        re-arms through _on_upgrade_available (which fires on a version
        change), and one that has been withdrawn stops this dead. Never
        raises -- called from the reporter thread."""
        try:
            wanted = self._auto_update_version
            if not wanted or wanted == config_mod.VERSION:
                return
            if not site_mod.feature_enabled("auto_update"):
                # The site turned unattended updates back off while this one
                # was waiting out a retry. Fails closed, as everywhere else.
                self._auto_update_version = ""
                return
            if self._auto_update_applying == wanted:
                return              # already on it; the swap takes a few seconds
            if time.monotonic() < self._auto_update_retry_at:
                return              # stood down a moment ago
            blocked = self._upgrade_attempt_blocked(wanted)
            if blocked:
                return              # REL-8: cap reached, or still backing off
            offer = self.upgrade.available
            if offer is None or str(offer.get("version") or "") != wanted:
                # Withdrawn, or replaced by an offer _on_upgrade_available
                # has judged for itself. Either way this one is over.
                self._auto_update_version = ""
                return
            self._auto_update_applying = wanted
            first_attempt = self._auto_update_announced != wanted
            if first_attempt:
                self._auto_update_announced = wanted
                log.info("auto-update: applying v%s (this site has unattended "
                         "updates on)", wanted)
            else:
                log.info("auto-update: retrying v%s", wanted)
            threading.Thread(
                target=self._run_auto_update, args=(wanted, first_attempt),
                name="ccsync-auto-upgrade", daemon=True,
            ).start()
        except Exception:
            log.exception("auto-update attempt failed -- leaving the offer to the tray")

    def _run_auto_update(self, wanted: str, first_attempt: bool) -> None:
        """The unattended-update thread body: _run_pushed_update's shape on
        the auto path (CR-41 fixed the latch-once bug for the admin PUSH and
        left this path a single fire -- comp-app-core-4, 2026-08-21). `quiet_refusals` from the
        second attempt on: an editor whose window stays open must not get the
        same balloon every 90 seconds."""
        outcome = "failed"
        try:
            outcome = self.apply_upgrade(quiet_refusals=not first_attempt)
            if outcome is None:     # a stub with no return value: treat as applied
                outcome = ""
        except Exception:
            log.exception("auto-update to v%s raised", wanted)
        finally:
            if outcome:
                # A stand-down is not a failed install (the editor has a
                # window open): it keeps the short timer and is not counted
                # towards REL-8's cap. Only "failed" -- a download, a sha, a
                # swap or an exec that did not work -- is.
                if outcome == "failed":
                    wait = self._note_upgrade_failure(wanted)
                else:
                    wait = (PUSHED_UPDATE_FAILED_RETRY_SECONDS if outcome == "no-offer"
                            else PUSHED_UPDATE_RETRY_SECONDS)
                self._auto_update_retry_at = time.monotonic() + wait
                if self._auto_update_applying == wanted:
                    self._auto_update_applying = ""
                log.info("auto-update to v%s did not apply (%s); will try again "
                         "in %ds", wanted, outcome, int(wait))

    def _apply_pushed_update(self, resp: Any) -> None:
        """Apply the build an admin asked this machine to take.

        2026-08-18. Until now the ONLY thing that could install a published
        build was the editor clicking "Update now" in their own tray, so a
        fleet-wide fix landed whenever each owner happened to notice a
        balloon -- ruskin's PC sat two versions behind for a day while its
        lanes were parked, and nobody could do anything about it from here.

        WHAT THIS DOES NOT DO. It does not fetch anything the tray click
        would not have fetched: the bytes come from `self.upgrade.available`,
        the offer this dashboard advertised in THIS reply, already checked
        against the release public keys baked into the running build and
        against this machine's downgrade floor (upgrade._accept_offer). The
        command carries a version and nothing else, and a version that does
        not match the offer in hand is refused. It also cannot interrupt
        work: apply_upgrade's stand-down test (an open window, a consolidate
        in flight) applies exactly as it does for the click.

        Never raises: this runs on the reporter thread."""
        try:
            command = None
            if isinstance(resp, dict):
                commands = resp.get("commands")
                if isinstance(commands, dict):
                    command = commands.get("upgrade")
            if not isinstance(command, dict) or not command.get("apply"):
                return
            wanted = str(command.get("version") or "").strip()
            if not wanted or wanted == config_mod.VERSION:
                return
            offer = self.upgrade.available
            if offer is None or str(offer.get("version") or "") != wanted:
                # The dashboard asked for a build it is not currently
                # offering us (a rollback published between two ticks, a
                # platform mismatch, an offer this machine's floor refused).
                # Say so once per version rather than every 30 seconds.
                if self._pushed_update_refused != wanted:
                    self._pushed_update_refused = wanted
                    log.warning(
                        "pushed update to v%s IGNORED: this machine is not being "
                        "offered that build (holding %s)", wanted,
                        (offer or {}).get("version") or "nothing",
                    )
                return
            # The key is the REQUEST, not the version: an admin who cancels
            # and pushes the same build again gets a fresh attempt at once
            # (new requested_at), instead of waiting out the retry timer.
            key = f"{wanted}@{command.get('requested_at') or ''}"
            if self._pushed_update_applying == key:
                return          # already on it; the swap takes a few seconds
            if self._pushed_update_announced == key and time.monotonic() < self._pushed_update_retry_at:
                return          # stood down a moment ago; give the editor time to close the window
            blocked = self._upgrade_attempt_blocked(wanted)
            if blocked:
                # REL-8: the request rides EVERY report until this machine
                # reports the new version, so a machine that cannot take the
                # build downloaded it every ten minutes for ever. The
                # dashboard is told through sync_guard.upgrade instead.
                return
            self._pushed_update_applying = key
            first_attempt = self._pushed_update_announced != key
            if first_attempt:
                self._pushed_update_announced = key
                log.info("applying pushed update to v%s (requested by %s)",
                         wanted, command.get("requested_by") or "an admin")
                self._notify_tray(
                    f"Your administrator is updating CCSync to v{wanted}.",
                    "ccsync-companion",
                )
            else:
                log.info("retrying pushed update to v%s", wanted)
            threading.Thread(
                target=self._run_pushed_update, args=(key, wanted, first_attempt),
                name="ccsync-pushed-upgrade", daemon=True,
            ).start()
        except Exception:
            log.exception("could not apply the pushed update")

    def _run_pushed_update(self, key: str, wanted: str, first_attempt: bool) -> None:
        """The pushed-update thread body: one apply_upgrade, and if it came
        back without swapping, release the latch so the next report can try
        again after a pause. Before this (0.9.3) the latch was set on the
        reporter thread and never released: ruskin's PC, whose out-of-tree
        popup holds the lock from three seconds after launch (CR-27), got
        ONE "Can't update while a CCSync window is open", then silently
        ignored the push until the tray was restarted -- on precisely the
        machine unattended updates were built for (ultrareview 2026-08-19)."""
        outcome = "failed"
        try:
            outcome = self.apply_upgrade(quiet_refusals=not first_attempt)
            if outcome is None:     # a stub with no return value: treat as applied
                outcome = ""
        except Exception:
            log.exception("pushed update to v%s raised", wanted)
        finally:
            if outcome:
                # Same split as the auto path (REL-8).
                if outcome == "failed":
                    wait = self._note_upgrade_failure(wanted)
                else:
                    wait = (PUSHED_UPDATE_FAILED_RETRY_SECONDS if outcome == "no-offer"
                            else PUSHED_UPDATE_RETRY_SECONDS)
                self._pushed_update_retry_at = time.monotonic() + wait
                if self._pushed_update_applying == key:
                    self._pushed_update_applying = ""
                log.info("pushed update to v%s did not apply (%s); will try again in %ds",
                         wanted, outcome, int(wait))

    def _apply_resume_lane_b(self, resp: Any) -> None:
        """An admin cleared this machine's lane B breaker from the dashboard
        (KNOWN_BUGS CR-45, 2026-08-20).

        The breaker is deliberately an OPERATOR decision -- resuming asserts
        that the server is in a state worth syncing from, which is the exact
        judgement the software could not make. What it was not, until now, is
        an operator decision the operator could reach: only the editor's own
        tray could clear it, so a remote machine sat parked until its owner
        was next at the keyboard (ruskin's PC, 2026-08-19, a day of it). The
        admin who checked the NAS is *more* qualified to make that call than
        the editor being asked to click through a warning about it.

        ONE CLICK, ONE RESUME (comp-lanes-ab-2, 2026-08-21). This used to
        test `tripped` and nothing else, on the reasoning that "the dashboard
        has dropped the request by then" -- but the dashboard only drops it
        when a report arrives with the breaker CLEAR, and the reporter's next
        tick is up to a report interval away. A pass that re-trips inside
        that window (a deleting pass moves its --max-delete 100 in seconds)
        was resumed again by the next reply, and again, every cycle, from one
        admin click: the unbounded sequence the breaker was built to stop.
        The request's `requested_at` is now carried into resume_lane_b, which
        applies each one exactly once and persists that. A later, unrelated
        trip is a later judgement and needs a fresh click.

        Never raises: this runs on the reporter thread."""
        try:
            command = None
            if isinstance(resp, dict):
                commands = resp.get("commands")
                if isinstance(commands, dict):
                    command = commands.get("resume_lane_b")
            if not isinstance(command, dict) or not command.get("apply"):
                return
            if not self.lane_b_breaker.tripped:
                return
            by = str(command.get("requested_by") or "your administrator").strip()
            request_id = str(command.get("requested_at") or "").strip()
            ok, message = self.resume_lane_b(by=f"{by} (dashboard)",
                                             request_id=request_id)
            if not ok:
                log.warning("dashboard asked to resume proxy download: %s", message)
                return
            log.warning("lane B breaker resumed by %s from the dashboard", by)
            self._notify_tray(
                f"{by} checked the server and started proxy download again.",
                "ccsync-companion: proxy download resumed",
            )
        except Exception:
            log.exception("could not apply the dashboard's resume-proxy-download request")

    def _apply_file_moves(self, resp: Any) -> None:
        """Follow the server's file moves (docs/FILE_MOVES.md, 2026-08-27).

        An admin moved a file between project folders on the NAS; this
        machine holds a copy at the old path, and lane A -- a one-way copy
        that never deletes -- would otherwise put it straight back on its
        next pass. So the copy here is moved the same way, its proxies with
        it, every Resolve clip that pointed at the old path is repointed, and
        the outcome goes back in the next report.

        Once per move: the on-disk ledger answers a redelivered command with
        the outcome it already had, so a lost report costs one interval and
        never a second move. NOTHING here deletes: a refused move leaves the
        file where it was and says so. Never raises: reporter thread."""
        try:
            commands = resp.get("commands") if isinstance(resp, dict) else None
            raw_moves = commands.get("file_moves") if isinstance(commands, dict) else None
            if not isinstance(raw_moves, list) or not raw_moves:
                return
            local_root = str(self.config.get("local_root", "")).strip()
            for raw in raw_moves[:file_moves_mod.LEDGER_MAX_ENTRIES]:
                move = file_moves_mod.parse_command(raw)
                if move is None:
                    log.warning("file moves: ignoring a malformed command (%r)", raw)
                    continue
                done = self.file_moves.entry(move["id"])
                if done is not None and not self.file_moves.retry_due(done):
                    # RES-1 (2026-08-28): a failure is no longer final. An
                    # entry still in `retryable` re-answers as "retrying" --
                    # which the dashboard records WITHOUT retiring the
                    # command -- until its next attempt is due.
                    state = done.get("state")
                    if state == file_moves_mod.STATE_RETRYABLE:
                        self._queue_file_move_answer(
                            move["id"], False, done["detail"], state="retrying",
                            attempts=int(done.get("attempts") or 0))
                    else:
                        self._queue_file_move_answer(
                            move["id"], done["ok"], done["detail"],
                            state=("blocked" if state == file_moves_mod.STATE_BLOCKED
                                   else None),
                            attempts=int(done.get("attempts") or 0),
                            relink_pending=bool(done.get("relink_pending")))
                    continue
                if not local_root or self._root_absent:
                    # Not an answer: the drive may be back next report, and
                    # "nothing at the old path" would be a lie.
                    log.info("file moves: #%s waits for the sync drive", move["id"])
                    continue
                ok, detail, paths = file_moves_mod.apply_move(move, local_root)
                relink_pending = False
                if ok and paths is not None:
                    matched, relinked = self._relink_moved_result(
                        paths[0], paths[1], move["is_dir"])
                    # RES-10 (2026-08-28): "Resolve was not open" is not
                    # "there was nothing to relink". The move stays on the
                    # books as a pending relink until a media pool walk has
                    # actually matched it, and every project change re-runs
                    # it -- otherwise the clip is simply offline the next
                    # time the editor opens THAT project, with a DEBUG line
                    # as the only trace anywhere.
                    relink_pending = not matched
                    if relinked:
                        detail = f"{detail}; {relinked}"
                if ok:
                    self.file_moves.record(move, True, detail, paths=paths,
                                           relink_pending=relink_pending)
                    self._queue_file_move_answer(move["id"], True, detail,
                                                 relink_pending=relink_pending)
                else:
                    entry = self.file_moves.record_attempt_failed(move, detail)
                    blocked = entry.get("state") == file_moves_mod.STATE_BLOCKED
                    self._queue_file_move_answer(
                        move["id"], False, detail,
                        state="blocked" if blocked else "retrying",
                        attempts=int(entry.get("attempts") or 0))
                who = move["requested_by"]
                name = move["from_rel"].rsplit("/", 1)[-1]
                where = f"{move['to_project_rel']}/{move['to_rel'].rsplit('/', 1)[0]}".rstrip("/")
                if ok:
                    log.info("file move #%s by %s: %s -> %s/%s (%s)", move["id"], who,
                             move["from_rel"], move["to_project_rel"], move["to_rel"], detail)
                    if paths is not None:
                        self._notify_tray(
                            f"{who} moved '{name}' to {where} on the server. Your copy "
                            f"followed and Resolve was relinked.",
                            "ccsync-companion: file moved")
                else:
                    log.warning("file move #%s by %s could not be applied here "
                                "(attempt %s): %s", move["id"],
                                who, entry.get("attempts"), detail)
                    # One toast on the FIRST attempt and one when it gives up.
                    # The retries in between are the companion's business, not
                    # an hourly notification (RES-1, 2026-08-28).
                    if int(entry.get("attempts") or 0) == 1:
                        self._notify_tray(
                            f"{who} moved '{name}' to {where} on the server, but your copy "
                            f"could not follow yet: {detail}. Nothing was deleted and "
                            f"CCSync will keep trying.",
                            "ccsync-companion: file move needs attention")
                    elif entry.get("state") == file_moves_mod.STATE_BLOCKED:
                        self._notify_tray(
                            f"Your copy of '{name}' still could not be moved to {where} "
                            f"after a week of trying: {detail}. Nothing was deleted; ask "
                            f"your admin.",
                            "ccsync-companion: file move blocked")
        except Exception:
            log.exception("could not apply the dashboard's file moves")

    def _queue_file_move_answer(self, move_id: int, ok: bool, detail: str,
                                state: str | None = None, attempts: int = 0,
                                relink_pending: bool = False) -> None:
        self._file_move_answers = [a for a in self._file_move_answers if a["id"] != move_id]
        answer: dict[str, Any] = {"id": int(move_id), "ok": bool(ok),
                                  "detail": str(detail or "")[:512]}
        # RES-1 / RES-10: the extra fields a dashboard below the same sweep
        # ignores (`extra="ignore"` on FileMoveResultIn), and which tell a
        # newer one the difference between "still trying", "given up" and
        # "moved, but Resolve has not been repointed yet".
        if state:
            answer["state"] = state
        if attempts:
            answer["attempts"] = int(attempts)
        if relink_pending:
            answer["relink_pending"] = True
        self._file_move_answers.append(answer)

    def _file_move_results(self) -> list[dict[str, Any]]:
        """Drained by the reporter: the answers queued since the last report."""
        answers, self._file_move_answers = self._file_move_answers, []
        return answers

    # -- the admin-side Resolve undo (SYS-15b, 2026-08-29) -----------------

    def _resolve_journals(self) -> list[dict[str, Any]]:
        """The clip-path changes this machine has recorded, for the report.

        NAMES AND COUNTS ONLY. The journal entries are this editor's own
        paths and the dashboard has no use for them: an admin picks a change
        to undo by project and time. Never raises: reporter thread."""
        try:
            return resolve_journal.summaries()
        except Exception:
            log.exception("could not list this machine's undo journals")
            return []

    def _resolve_undo_results(self) -> list[dict[str, Any]]:
        answers, self._resolve_undo_answers = self._resolve_undo_answers, []
        return answers

    def _queue_resolve_undo_answer(self, request_id: int, ok: bool, detail: str,
                                   state: str, attempts: int = 0) -> None:
        self._resolve_undo_answers = [
            a for a in self._resolve_undo_answers if a["id"] != request_id]
        answer: dict[str, Any] = {"id": int(request_id), "ok": bool(ok),
                                  "detail": str(detail or "")[:512], "state": state}
        if attempts:
            answer["attempts"] = int(attempts)
        self._resolve_undo_answers.append(answer)

    def _apply_resolve_undo(self, resp: Any) -> None:
        """Put clip paths back because an admin asked, not because the editor
        clicked (SYS-15b, 2026-08-29).

        Replays the SAME journal the tray's own undo replays, through the same
        `resolve_bridge.undo_last_relink` -- there is one place in this
        product where a media-pool write happens and this is not a second one.

        An undo that cannot run YET (Resolve closed, the change was made in a
        project that is not the one open) is answered `retrying`: the
        dashboard records the attempt without retiring the command, and it
        comes back on the next report. Retiring it would leave the wrong paths
        in place with an admin believing they had been put back.

        Once per request: the on-disk ledger answers a redelivered command
        with the outcome it already had. Never raises: reporter thread."""
        try:
            commands = resp.get("commands") if isinstance(resp, dict) else None
            raw = commands.get("resolve_undo") if isinstance(commands, dict) else None
            if not isinstance(raw, list) or not raw:
                return
            for entry in raw[:8]:
                command = resolve_undo_mod.parse_command(entry)
                if command is None:
                    log.warning("resolve undo: ignoring a malformed command (%r)", entry)
                    continue
                done = self.resolve_undos.entry(command["id"])
                if done is not None and done.get("state") != "retrying":
                    self._queue_resolve_undo_answer(
                        command["id"], bool(done.get("ok")), str(done.get("detail") or ""),
                        str(done.get("state") or "done"),
                        int(done.get("attempts") or 0))
                    continue
                ok, detail, state = resolve_undo_mod.apply_undo(command)
                if state == "retrying" and done is not None \
                        and self.resolve_undos.gave_up(done):
                    # A week of "ask me again" is an answer. Anything else
                    # leaves the admin watching a request that never ends.
                    state = "failed"
                    detail = (f"{detail} (this computer has been unable to do it for a "
                              "week)")
                    ok = False
                recorded = self.resolve_undos.record(command["id"], ok, detail, state)
                self._queue_resolve_undo_answer(
                    command["id"], ok, detail, state,
                    int(recorded.get("attempts") or 0))
                who = command["requested_by"]
                if ok:
                    log.warning("resolve undo #%s (asked for by %s): %s",
                                command["id"], who, detail)
                    self._notify_tray(
                        f"{who} put back the clip paths CC Sync changed in Resolve.",
                        "ccsync-companion: clip paths put back")
                else:
                    log.warning("resolve undo #%s (asked for by %s) %s: %s",
                                command["id"], who, state, detail)
        except Exception:
            log.exception("could not apply the dashboard's Resolve undo")

    def _relink_moved_result(self, old_local: str, new_local: str,
                             is_dir: bool) -> tuple[bool, str]:
        """(matched, text). `matched` is "a media pool walk actually found
        clips at the old path", which is the only thing that retires a
        pending relink (RES-10): a Resolve that is closed, or open on another
        project, has not answered the question."""
        text = self._relink_moved(old_local, new_local, is_dir)
        matched = bool(text) and not text.startswith(("Resolve not relinked",
                                                      "Resolve relink failed"))
        return matched, text

    def _relink_pending_moves(self) -> None:
        """Re-run the relink for every applied move that has not matched yet.

        RES-10 (2026-08-28): `_relink_moved` only ever walked the media pool
        that happened to be open when the move landed. A move of project B's
        footage while project A was open reported "Resolve not relinked (not
        open)", the ledger called it done, and the clip was simply offline the
        next time anyone opened B. Called on every project change; never
        raises (watcher thread)."""
        try:
            for entry in self.file_moves.pending_relinks():
                matched, text = self._relink_moved_result(
                    entry.get("old_local", ""), entry.get("new_local", ""),
                    bool(entry.get("is_dir")))
                if matched:
                    self.file_moves.clear_relink_pending(entry["id"])
                    log.info("file move #%s: %s after the project changed",
                             entry["id"], text)
                    self._queue_file_move_answer(
                        entry["id"], True, f"{entry.get('detail', 'moved')}; {text}")
        except Exception:
            log.exception("could not re-run the pending file-move relinks")

    def _on_moved_clip_missing(self, item: dict[str, Any], entry: dict[str, Any]) -> None:
        """A clip whose file is gone is not a mystery when WE moved it
        (RES-10): the new path is known exactly, so this offers the repoint
        rather than leaving a DEBUG line as the only trace. One dialog per
        move per process, under the popup lock like every other Tk root
        here."""
        move_id = entry.get("id")
        if move_id in self._moved_clip_offered:
            return
        self._moved_clip_offered.add(move_id)
        name = str(entry.get("from_rel", "")).rsplit("/", 1)[-1] or "a clip"
        self._notify_tray(
            f"'{name}' moved on the server. CCSync can repoint Resolve to where it is now.",
            "ccsync-companion: this clip moved")
        threading.Thread(
            target=self._show_moved_clip_dialog, args=(entry, name),
            name="ccsync-moved-clip", daemon=True,
        ).start()

    def _show_moved_clip_dialog(self, entry: dict[str, Any], name: str) -> None:
        if not self._popup_active_lock.acquire(blocking=False):
            log.info("moved-clip dialog: another CCSync window is open -- the tray "
                     "notification carried the message instead")
            return
        try:
            body = (
                f"'{name}' is offline in this project because it was moved on the "
                f"server.\n\n"
                f"It is now at:\n  {entry.get('new_local', '')}\n\n"
                f"Your copy has already been moved to match. CCSync can point this "
                f"project's clips at the new location for you. Nothing is deleted and "
                f"the change is journalled, so it can be undone."
            )
            if not popup.confirm_dialog("CCSYNC.EXE: this clip moved on the server",
                                        body, ok_label="RELINK IT"):
                return
            matched, text = self._relink_moved_result(
                entry.get("old_local", ""), entry.get("new_local", ""),
                bool(entry.get("is_dir")))
            if matched:
                self.file_moves.clear_relink_pending(entry["id"])
            self._notify_tray(
                text or "Nothing in this project pointed at the old location.",
                "ccsync-companion: relink")
        except Exception:
            log.exception("could not offer the moved-clip relink")
        finally:
            self._popup_active_lock.release()

    def _relink_moved(self, old_local: str, new_local: str, is_dir: bool) -> str:
        """Repoint every media pool clip under `old_local` to `new_local`,
        through replace_clip (save point + undo journal, like every other
        Resolve mutation). Returns a short outcome for the report, "" when
        there was nothing to do. Never raises: a Resolve that is closed or
        busy is reported, not treated as a failed move -- the file HAS moved,
        and the fixer popup will meet the offline clip like any other."""
        try:
            from . import canon, resolve_bridge

            result = resolve_bridge.get_media_pool_items()
            if not result.get("ok"):
                return f"Resolve not relinked ({result.get('message') or 'not open'})"
            local_root = str(self.config.get("local_root", ""))
            prefix = str(self.config.get("canonical_prefix", ""))
            old_n = os.path.normcase(os.path.normpath(old_local))
            relinked = failed = 0
            for item in result.get("items") or []:
                file_path = str(item.get("file_path") or "")
                local = canon.canonical_to_local(file_path, local_root, prefix) or file_path
                local_n = os.path.normcase(os.path.normpath(local))
                if is_dir:
                    if not (local_n == old_n or local_n.startswith(old_n.rstrip("\\/") + os.sep)):
                        continue
                    target = os.path.join(new_local, os.path.relpath(local, old_local)) \
                        if local_n != old_n else new_local
                elif local_n == old_n:
                    target = new_local
                else:
                    continue
                clip = resolve_bridge.resolve_media_pool_item(item)
                if clip is None:
                    failed += 1
                    continue
                canonical = canon.local_to_canonical(target, local_root, prefix)
                outcome = resolve_bridge.replace_clip(clip, canonical, source="file_move")
                if outcome.get("ok"):
                    relinked += 1
                else:
                    failed += 1
                    log.warning("file move: could not relink %s -> %s: %s",
                                file_path, canonical, outcome.get("message"))
            if not relinked and not failed:
                return ""
            text = f"{relinked} Resolve clip(s) relinked"
            if failed:
                text += f", {failed} could not be"
            return text
        except Exception:
            log.exception("file move: Resolve relink failed")
            return "Resolve relink failed (see the log)"

    def _apply_fleet_halt(self, resp: Any) -> None:
        """Adopt the dashboard's fleet halt flag from a report reply.

        The reply already carries the upgrade advertisement and the
        unmapped-project prompt, so the halt rides the same channel rather
        than costing a second request -- an admin's stop reaches every tray
        within one report interval. Never raises: this runs on the reporter
        thread."""
        try:
            command = None
            if isinstance(resp, dict):
                commands = resp.get("commands")
                if isinstance(commands, dict):
                    command = commands.get("halt")
            engaged = self.halt.note_fleet_flag(command)
            if engaged is True:
                self.halt_all_sync(self.halt.reason, lane_guard.HALT_SCOPE_FLEET)
            elif engaged is False:
                log.warning("the dashboard released the fleet halt -- restarting sync")
                # Same filtered release the tray's own [ RESUME ] takes
                # (sync-safety-4, CR-48, CR-67 item 1): an admin's release must
                # not be the one path that can put a folder with no .stignore
                # online.
                self._release_lane_c_folders()
                self._set_express_paused(self._paused)
                self._start_lanes()
                self._notify_tray(
                    "Your administrator started syncing again.",
                    "ccsync-companion: syncing resumed",
                )
        except Exception:
            log.exception("could not apply the fleet halt flag")

    def sequencer_state(self) -> tuple[str, str]:
        """(state, human detail) for the sequencer, or ("", "") in legacy
        mode. The sequencer computes exactly the strings an editor needs and
        they appeared in no tray line, no log line and no report (UX-4)."""
        if self.sequencer is None:
            return "", ""
        try:
            return str(self.sequencer.state), str(self.sequencer.status_detail())
        except Exception:
            log.exception("sequencer state read failed")
            return "", ""

    # How far back from the end of companion.log to read for the tail. 64 KB
    # is ~200 lines of this formatter, comfortably more than the 40 asked for.
    _LOG_TAIL_WINDOW_BYTES = 64 * 1024

    def _diagnostic_log_tail(self, lines: int = 40) -> list[str]:
        # Seek, don't readlines(): setup_logging rotates at 5 MB and R15 fix 4
        # documents machines that sit at that ceiling, so keeping 40 lines
        # decoded 5 MB of UTF-8 and allocated tens of thousands of strings --
        # on the tray worker thread, inside "Copy diagnostics"
        # (COMP-CORE-8, 2026-08-14). The except arm still answers with the
        # explanatory placeholder for an unreadable (or mid-rotation) file.
        try:
            with open(self.log_path, "rb") as fh:
                fh.seek(0, os.SEEK_END)
                size = fh.tell()
                window = min(size, self._LOG_TAIL_WINDOW_BYTES)
                fh.seek(size - window)
                chunk = fh.read(window)
            text = chunk.decode("utf-8", errors="replace")
            tail = text.splitlines()
            # The first line of a mid-file window is almost always a partial
            # one; drop it unless the window covers the whole file.
            if window < size and tail:
                tail = tail[1:]
            return tail[-lines:]
        except Exception as exc:
            return [f"(could not read {self.log_path}: {exc})"]

    # -- the diagnostics channel (SYS-7, resilience sweep 2026-08-28) ------
    #
    # build_diagnostics() is genuinely good and went to the CLIPBOARD, with
    # the instruction "Paste them to your admin in a message" -- and to the
    # LOG instead, silently, if any CCSync window happened to be open. So the
    # one artefact that answers "why is my footage not syncing" existed only
    # if a non-technical editor performed a manual step at the right moment,
    # on the machine that was broken. Three triggers now put it on the
    # dashboard instead: the button (which still fills the clipboard), a lane
    # falling into `error`, and an admin's [ ASK THIS MACHINE WHY ].

    def _diagnostics_state_path(self) -> Optional[Path]:
        state_dir = getattr(self, "_state_dir", None)
        if state_dir is None:
            return None
        return Path(state_dir) / DIAGNOSTICS_STATE_FILENAME

    def _read_diagnostics_state(self) -> dict:
        """The rate-limit stamps and the last applied admin request.

        ON DISK, not in memory (the sweep's rule for every latch): the
        lane-error trigger fires on a machine that fails every pass, and a
        companion that restarts on every crash would upload a bundle per
        restart from an in-memory limiter. An unreadable file is an empty
        state, which costs at most one extra upload."""
        path = self._diagnostics_state_path()
        if path is None:
            return {}
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except FileNotFoundError:
            return {}
        except Exception:
            log.debug("could not read %s", path, exc_info=True)
            return {}

    def _write_diagnostics_state(self, state: dict) -> None:
        """tmp + os.replace, like identity.save_identity: a half-written
        limiter is what turns a broken machine into an upload loop."""
        path = self._diagnostics_state_path()
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(state, fh, indent=2, sort_keys=True)
            os.replace(tmp, path)
        except Exception:
            log.debug("could not write %s", path, exc_info=True)

    def _upload_diagnostics(self, trigger: str) -> bool:
        """Build the bundle and post it. Never raises.

        NEVER WITHOUT A VERIFIED IDENTITY: a bundle names this machine's
        paths, its Resolve project and its editor's tree, so posting one while
        signed out would file it under whatever name happened to be in
        config.toml. The reporter refuses too (post_diagnostics); this is the
        cheap check that also saves building the bundle at all.
        """
        try:
            if self.editor_identity() is None:
                log.debug("diagnostics upload skipped (%s): not signed in", trigger)
                return False
            poster = getattr(self.reporter, "post_diagnostics", None)
            if poster is None:
                # A lane double or a reporter stub in a test. Discoverable
                # from the log rather than a traceback on the reporter thread.
                log.debug("this reporter cannot upload diagnostics")
                return False
            return bool(poster(self.build_diagnostics(), trigger))
        except Exception:
            # A diagnostics upload must never be the reason anything else
            # stops: the dashboard being unreachable is one of the states this
            # bundle exists to describe.
            log.debug("diagnostics upload (%s) failed", trigger, exc_info=True)
            return False

    def _upload_diagnostics_async(self, trigger: str) -> None:
        """...on a thread of its own, for _report_off_cycle's reason: every
        caller here is either the reporter thread inside on_report_response or
        a tray callback, and neither may block on an upload over an editor's
        home uplink."""
        threading.Thread(
            target=self._upload_diagnostics, args=(trigger,),
            name="ccsync-diagnostics-upload", daemon=True,
        ).start()

    def _note_lane_error_diagnostics(self) -> None:
        """Upload a bundle when a lane FALLS INTO `error`. Never raises.

        The transition, not the state: a machine that has been in error since
        Tuesday would otherwise upload one bundle per report interval for
        ever. And at most one per lane per hour on top of that, persisted, for
        the flapping case -- a lane that errors, retries, errors again inside a
        pass is one incident, not forty.

        Called from _on_report_response, i.e. once per report cycle on the
        reporter thread: the same cadence the dashboard learns the lane state
        on, so the bundle and the red chip arrive together.
        """
        try:
            statuses = self.lane_statuses()
        except Exception:
            log.debug("could not read lane states for diagnostics", exc_info=True)
            return
        state = self._read_diagnostics_state()
        lanes = state.get("lanes")
        if not isinstance(lanes, dict):
            lanes = {}
        now = time.time()
        changed = False
        fire: list[str] = []
        for status in statuses:
            name = str(getattr(status, "name", "") or "")
            if not name:
                continue
            current = str(getattr(status, "state", "") or "")
            record = lanes.get(name)
            if not isinstance(record, dict):
                record = {}
            was = str(record.get("state") or "")
            if current != was:
                record["state"] = current
                changed = True
            if current == STATE_ERROR and was != STATE_ERROR:
                last_sent = record.get("sent_at")
                try:
                    quiet = now - float(last_sent) if last_sent is not None else None
                except (TypeError, ValueError):
                    quiet = None
                if quiet is None or quiet >= DIAGNOSTICS_LANE_ERROR_INTERVAL_SECONDS:
                    record["sent_at"] = now
                    changed = True
                    fire.append(name)
                else:
                    log.debug("lane %s errored again inside the diagnostics "
                              "rate limit (%.0f s ago)", name, quiet)
            lanes[name] = record
        if changed:
            state["lanes"] = lanes
            # BEFORE the upload, not after: a crash between the two costs one
            # missed bundle, whereas the other order costs an upload per
            # restart from the machine least able to afford it.
            self._write_diagnostics_state(state)
        for name in fire:
            log.info("lane %s entered error -- uploading diagnostics", name)
            self._upload_diagnostics_async("lane_error")

    def _apply_diagnostics_request(self, resp: Any) -> None:
        """An admin clicked [ ASK THIS MACHINE WHY ] (v33, SYS-7).

        The dashboard keeps this command standing on every reply until the
        BUNDLE ARRIVES (unlike resume_lane_b, which it drops as soon as the
        reply goes out) -- because a lost reply there costs one more admin
        click and here would cost an unanswerable question. Which means the
        `requested_at` comparison is what stops one click becoming an upload
        every 30 seconds: each ask is applied exactly once, and the record is
        on disk beside the rate-limit stamps, because a companion that
        restarted mid-ask must not answer it twice.

        Never raises: this runs on the reporter thread."""
        try:
            command = None
            if isinstance(resp, dict):
                commands = resp.get("commands")
                if isinstance(commands, dict):
                    command = commands.get("diagnostics")
            if not isinstance(command, dict):
                return
            request_id = str(command.get("requested_at") or "").strip()
            state = self._read_diagnostics_state()
            if request_id and str(state.get("applied_request") or "") == request_id:
                return
            by = str(command.get("requested_by") or "your administrator").strip()
            state["applied_request"] = request_id
            self._write_diagnostics_state(state)
            log.warning("%s asked this computer for its diagnostics from the "
                        "dashboard", by)
            self._upload_diagnostics_async("admin_request")
        except Exception:
            log.exception("could not apply the dashboard's diagnostics request")

    def _resolve_health_text(self) -> str:
        """One diagnostics line for what Resolve can see (APP-2 (c) / UX-4).

        The count an admin most needs is the one the editor dismissed: a
        machine where somebody pressed IGNORE ALL at nine o'clock looked
        identical, in every artefact support ever sees, to one with nothing
        wrong at all."""
        health = self.resolve_health()
        if not health.get("last_scan_at"):
            return "no timeline scan has completed yet (is Resolve open?)"
        parts = [
            f"{health['out_of_tree']} clip(s) outside the tree",
            f"{health['bad_prefix']} on a broken {self.canonical_prefix_label()} mapping",
            f"{health['missing']} missing on disk",
            f"{health['ignored_this_session']} skipped this session",
            f"{health['skipped_ever']} skipped ever",
            f"{health['ignored_folders']} folder(s) left alone on purpose",
        ]
        return ", ".join(parts) + f" (last scan {health['last_scan_at']})"

    def build_diagnostics(self) -> str:
        """Everything an admin needs to diagnose this machine, as one block of
        text for the clipboard (AUDIT_2 UX-19).

        The support instruction everywhere is "send your admin a screenshot
        of the tray menu" -- which said `OK` on all three lanes whatever was
        wrong.
        Never raises: every section is independently fault-isolated, because
        a diagnostics gather that crashes on the one broken subsystem is
        worse than useless."""
        from .sync import rclone_lane as _rclone_lane

        out: list[str] = []

        def section(label: str, fn: Callable[[], Any]) -> None:
            try:
                out.append(f"{label}: {fn()}")
            except Exception as exc:
                out.append(f"{label}: <failed: {exc}>")

        out.append("=== CCSYNC DIAGNOSTICS ===")
        section("time", lambda: time.strftime("%Y-%m-%d %H:%M:%S %z"))
        section("companion version", lambda: config_mod.VERSION)
        section("platform", lambda: f"{sys.platform} / {os.name}")
        # REL-16: which BINARY this machine can run. An Intel Mac offered the
        # arm64 build downloads it, verifies it, swaps it in and cannot exec
        # it, and nothing on the machine said which architecture it was.
        section("arch", upgrade_mod.arch_key)
        section("frozen exe", upgrade_mod.is_frozen)
        section("config file", lambda: config_mod.CONFIG_PATH)
        section("log file", lambda: self.log_path)
        section("effective mode", self.effective_mode)
        section("signed in as", lambda: self.editor_identity() or "NOT SIGNED IN")
        section("token expires", self._token_expiry_text)
        section("sync enabled", lambda: self._sync_enabled)
        section("paused", lambda: self._paused)
        section("managed mode", lambda: self._managed)
        section("lanes started", lambda: self._lanes_started)
        section("local_root", lambda: self.config.get("local_root"))
        section("sync drive", lambda: (
            f"{self._root_state}"
            + (" (root-absent problem demoted from config: "
               f"{self._root_demoted_problem})" if self._root_demoted_problem else "")
            + (" -- macOS is BLOCKING access to it (Full Disk Access lost in the "
               "last update; re-grant it in System Settings)"
               if self._macos_access_blocked else "")
        ))
        section("remote", lambda: f"{self.config.get('remote')}:{self.config.get('remote_root')}")
        section("dashboard_url", lambda: self.config.get("dashboard_url"))
        section("rclone available", lambda: _rclone_lane.rclone_available(
            str(self.config.get("rclone_path", "rclone"))))
        section("resolve project", lambda: getattr(self.watcher, "last_resolve_project", None))
        section("resolve bridge", self._resolve_bridge_text)
        section("resolve media", self._resolve_health_text)

        out.append("")
        out.append("-- updates --")
        try:
            report = upgrade_mod.upgrade_report(
                dict(self._upgrade_attempts or {},
                     reverted_from=self._upgrade_reverted_from),
                self._version_starts)
            out.append(f"  starts on this version: {report['starts_this_version']}")
            out.append(f"  last attempted build: {report['version'] or 'none'}")
            out.append(f"  failed attempts: {report['attempts']}"
                       + (f" (last error: {report['last_error']}"
                          f" at {report['last_attempt_at']})"
                          if report["attempts"] else ""))
            if report["attempts"] >= upgrade_mod.MAX_UPGRADE_ATTEMPTS:
                out.append("  GIVEN UP on that build: it has failed "
                           f"{report['attempts']} times")
            if report["reverted_from"]:
                out.append("  rolled back automatically from v"
                           f"{report['reverted_from']} (it kept crashing)")
            old = upgrade_mod.old_exe_path()
            out.append(f"  rollback copy: {old if old and old.exists() else 'none'}")
        except Exception as exc:
            out.append(f"  <failed: {exc}>")

        out.append("")
        out.append("-- config problems (these STOP syncing) --")
        if self.config_problems:
            out.extend(f"  ERROR: {p}" for p in self.config_problems)
        else:
            out.append("  none")
        for warning in self.config_warnings:
            out.append(f"  warning: {warning}")

        out.append("")
        out.append("-- sequencer --")
        state, detail = self.sequencer_state()
        out.append(f"  state: {state or '(legacy mode: no sequencer)'}")
        out.append(f"  detail: {detail}")
        try:
            out.append(f"  selected project rels: {sorted(self._selected_project_rels() or [])}")
        except Exception as exc:
            out.append(f"  selected project rels: <failed: {exc}>")

        out.append("")
        out.append("-- fleet jobs (docs/TIMELINE-CARDS-INTO-CCSYNC.md) --")
        try:
            if self.job_runner is None:
                out.append("  runner: not built")
            else:
                status = self.job_runner.status()
                # The GATE is the whole answer to "why is this machine taking
                # no work", and it is the one thing an admin cannot see from
                # the dashboard: the offer is theirs, the refusal is ours.
                out.append(f"  gate: {status['state']}")
                out.append(f"  offered: {status['offered']}")
                out.append(f"  holding: {status['job'] or 'nothing'}")
                caps = self.job_capabilities()
                out.append(f"  whisper: {caps.get('whisper')}"
                           + (f" ({caps.get('whisper_detail')})"
                              if caps.get("whisper_detail") else ""))
                out.append(f"  mounts: {caps.get('mounts')}")
                out.append(f"  idle seconds: {caps.get('idle_seconds')}"
                           " (None = cannot tell = not idle)")
        except Exception as exc:
            out.append(f"  <failed: {exc}>")

        out.append("")
        out.append("-- lanes --")
        try:
            for status in self.lane_statuses():
                out.append(f"  {vars(status)}")
        except Exception as exc:
            out.append(f"  <failed: {exc}>")

        out.append("")
        out.append("-- syncthing --")
        try:
            # CACHED, not check_once() (comp-lane-c-5, CR-50, CR-67 item 9).
            # check_once() walks every shared folder through Syncthing's REST
            # API, which is up to 20 s of a worker thread on the slow or
            # half-dead Syncthing that is the exact condition a diagnostics
            # bundle is collected under. Lane C's own poll loop refreshes this
            # every cycle, so the cache is at most one poll interval stale.
            cached = self._lane_c.status()
            out.append(f"  reachable: {cached.state != 'error'} ({cached.state}) "
                       "[last poll, not a fresh sweep]")
            out.append(f"  detail: {cached.detail or cached.last_error or ''}")
        except Exception as exc:
            out.append(f"  <failed: {exc}>")
        try:
            # The one live question the cache cannot answer, and the cheap one:
            # api_reachable() is a single localhost ping, not a per-folder
            # sweep (see SyncthingLane.api_reachable).
            probe = getattr(self._lane_c, "api_reachable", None)
            if probe is not None:
                out.append(f"  api answers right now: {bool(probe())}")
        except Exception as exc:
            out.append(f"  api answers right now: <failed: {exc}>")

        out.append("")
        out.append("-- transport health (relay path / orphaned uploads) --")
        try:
            health = self.transport_health()
            relayed = ((health.get("syncthing") or {}).get("relayed")) or []
            if relayed:
                out.append(f"  RELAYED: {len(relayed)} Syncthing device(s) are NOT on a "
                           f"direct path -- {relayed}")
            out.append(f"  {health}")
        except Exception as exc:
            out.append(f"  <failed: {exc}>")

        out.append("")
        out.append("-- last dashboard report --")
        # APP-1: the section that was missing. `dashboard_url` was printed
        # right at the top of this bundle and "has anything this machine sent
        # ever been accepted" was not, so a revoked token and a healthy fleet
        # produced identical diagnostics.
        try:
            health = self.reporter.health()
            accepted = health.get("last_success_at") or (
                "NEVER (nothing this machine has sent was accepted)")
            out.append(f"  last ACCEPTED: {accepted}")
            out.append(f"  last status: {health.get('last_status') or '(no report yet)'}")
            out.append(f"  failures in a row: {health.get('consecutive_failures')}")
            skew = getattr(self.reporter, "clock_skew_seconds", None)
            if skew is None:
                out.append("  clock vs the server: not measured yet (no reply has "
                           "carried the server's time)")
            else:
                which = "this computer is AHEAD" if skew > 0 else "this computer is BEHIND"
                out.append(f"  clock vs the server: {skew:+.0f}s ({which})")
        except Exception as exc:
            out.append(f"  <failed: {exc}>")

        out.append("")
        out.append("-- background task failures (crash reports) --")
        # APP-6: crash_report's own docstring names "the tray stayed up with a
        # dead lane" as what it exists to fix, and nothing surfaced the files
        # it wrote -- least of all the bundle an admin actually asks for.
        try:
            summary = crash_report.crash_summary(self.config)
            out.append(f"  directory: {crash_report.crash_dir(self.config)}")
            out.append(f"  count: {summary.get('count')}")
            for entry in crash_report.recent_reports(self.config):
                out.append(f"  {entry.get('when')} {entry.get('type')} "
                           f"in thread {entry.get('thread')} ({entry.get('name')})")
        except Exception as exc:
            out.append(f"  <failed: {exc}>")

        out.append("")
        out.append("-- background thread restarts (the watchdog) --")
        # SYS-2: the counter that separates "it recovered on its own" from
        # "this machine has needed a human since Tuesday". The record outlives
        # the process (~/.ccsync/state/watchdog.json), so a companion that has
        # itself been restarted still shows the last 24 hours.
        try:
            watchdog = self._lane_watchdog
            if watchdog is None:
                out.append("  the thread watchdog is not running")
            else:
                out.append(f"  record: {watchdog._state_path}")
                report = watchdog.report()
                if not report:
                    out.append("  none: no background thread has needed restarting")
                for name, entry in sorted(report.items()):
                    out.append(
                        f"  {name}: {entry.get('count_24h')} restart(s) in 24h, "
                        f"{entry.get('count_1h')} in the last hour, last at "
                        f"{entry.get('last_at')} "
                        f"({entry.get('last_error') or 'no exception was recorded'})")
        except Exception as exc:
            out.append(f"  <failed: {exc}>")

        out.append("")
        out.append(f"-- last 40 log lines ({self.log_path}) --")
        out.extend(f"  {line}" for line in self._diagnostic_log_tail(40))
        return "\n".join(out)

    def resolve_bridge_state(self) -> dict[str, Any]:
        """Cached "has the Resolve bridge connected this session, and is it up
        now?" for the tray. A plain dict read -- nothing here talks to
        Resolve, because the tray's render path may not hold the GIL through
        a fusionscript call (see resolve_bridge.session_state)."""
        try:
            return resolve_bridge.session_state()
        except Exception:
            log.debug("resolve bridge session state unavailable", exc_info=True)
            return {"connected": None, "ever_connected": False, "reason": ""}

    def _resolve_bridge_text(self) -> str:
        """The diagnostics line for the same question. Two incidents (MAC-10,
        item 19) turned entirely on it and the bundle an admin was sent could
        not answer it."""
        state = self.resolve_bridge_state()
        ever = "yes" if state.get("ever_connected") else "NO"
        connected = state.get("connected")
        if connected is None:
            return f"never polled this session (has connected this session: {ever})"
        if connected:
            return f"connected (has connected this session: {ever})"
        reason = str(state.get("reason") or "no reason recorded")
        return f"NOT CONNECTED -- {reason} (has connected this session: {ever})"

    def _token_expiry_text(self) -> str:
        from . import identity as identity_mod
        from .identity import parse_token

        # Deliberately NOT identity.token (which returns None once expired --
        # and "when did it expire" is exactly what diagnostics need).
        raw = getattr(self.identity, "_identity", None) or {}
        _user, expires = parse_token(raw.get("token"))
        if expires is None:
            return "(no token)"
        remaining = expires - time.time()
        stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(expires))
        # Tokens minted since CR-86 (2026-08-27) do not expire -- the server
        # still stamps a field, a century out, because the wire shape is fixed
        # (auth.IDENTITY_TTL_SECONDS). Printing "876000.0h from now" reads
        # like a bug; say what it means, and keep the date for the pre-CR-86
        # tokens still in the field, where "when did it expire" is the
        # question diagnostics are being read to answer.
        if remaining > identity_mod.NON_EXPIRING_AFTER_SECONDS:
            return f"never (non-expiring token; nominal {stamp})"
        return f"{stamp} ({remaining / 3600:.1f}h from now)"

    def copy_diagnostics(self) -> bool:
        """Put build_diagnostics() on the clipboard. Returns success.

        Takes `_popup_active_lock` like every other tk.Tk() site in this
        process. It is a hidden root, but Tk does not care: opening it while
        the fixer dialog is up is the "another Tk root has run on a sibling
        thread" condition that wedges the Tcl interpreter, and the dialog it
        wedges is the one whose batch then gets auto-ignored (AUDIT_2
        CORE-M3/H8). It also bypassed apply_upgrade's `if
        self._popup_active_lock.locked()` guard, so a self-upgrade could swap
        the exe out from under a live root.

        Never leaves the admin with nothing: if a window is already open the
        diagnostics go to the log instead, which is what the fallback path
        below does too."""
        text = self.build_diagnostics()
        if not self._popup_active_lock.acquire(blocking=False):
            log.info("copy diagnostics: another CCSync window is open -- logging instead")
            log.info("DIAGNOSTICS:\n%s", text)
            # The UPLOAD needs no Tk root, so this path still gets the bundle
            # to the admin (SYS-7): "if any CCSync window is open it silently
            # goes to the log instead" was the worst of the three ways this
            # artefact used to reach nobody.
            self._upload_diagnostics_async("button")
            self._notify_tray(
                "Another CCSync window is open, so the diagnostics went to the log "
                "and to your admin's dashboard instead of the clipboard.",
                "ccsync-companion")
            return False
        try:
            import tkinter as tk

            # Hidden or not, it is a Tk root: same door as every dialog, so on
            # macOS it is built on the main thread instead of this tray worker
            # (ui_dispatch); on Windows it runs inline, exactly as before.
            def _copy_via_tk() -> None:
                root = tk.Tk()
                try:
                    root.withdraw()
                    root.clipboard_clear()
                    root.clipboard_append(text)
                    root.update()
                finally:
                    # Destroy AND make sure the interpreter dies here, on the
                    # tray worker that built it (CR-93).
                    ui_dispatch.release_root(root, "the clipboard root")

            ui_dispatch.dispatch(_copy_via_tk)
            log.info("diagnostics copied to clipboard (%d chars)", len(text))
            # ...AND to the dashboard (SYS-7, resilience sweep 2026-08-28).
            # The clipboard stays: an editor who is already pasting into a
            # message must not have that taken away, and the upload is the
            # half that works when they never do. On its own thread, so a slow
            # or unreachable dashboard cannot hold the tray callback open.
            self._upload_diagnostics_async("button")
            self._notify_tray(
                "Diagnostics copied, and sent to your admin's dashboard.",
                "ccsync-companion")
            return True
        except Exception:
            log.exception("could not copy diagnostics to the clipboard")
            log.info("DIAGNOSTICS:\n%s", text)
            self._upload_diagnostics_async("button")
            self._notify_tray(
                "Couldn't reach the clipboard. The diagnostics were written to the log "
                "and sent to your admin's dashboard.", "ccsync-companion")
            return False
        finally:
            self._popup_active_lock.release()

    def lane_statuses(self) -> list[LaneStatus]:
        statuses = [lane.status() for lane in self.lanes]
        if not self._managed or self.sequencer is None:
            return statuses

        # Managed mode: the dashboard tracks projects by Syncthing folder
        # slug, not by local subtree path, so translate current_project
        # ("Projects/<year>/<series>/<project>") to the matching slug
        # before reporting -- leave it as-is if unmapped (defensive: a
        # transient selection gap shouldn't make status reporting blow up).
        # Borrowed rels map to their BORROWER: it is the borrower's turn that
        # runs the borrowed subpath, and the dashboard's queue is keyed on
        # the borrower's slug (SHARED_FOLDERS_PLAN.md §3.1).
        getter = getattr(self.sequencer, "rel_to_slug_with_borrowed", None)
        rel_to_slug = getter() if getter is not None else self.sequencer.rel_to_slug
        mapped: list[LaneStatus] = []
        for status in statuses:
            copy = LaneStatus(**vars(status))
            rel = copy.current_project
            if rel:
                if rel.startswith(PROJECTS_PREFIX):
                    rel = rel[len(PROJECTS_PREFIX):]
                slug = rel_to_slug.get(rel)
                if slug is not None:
                    copy.current_project = slug
            mapped.append(copy)
        return mapped

    def sync_now(self) -> None:
        if not self._sync_enabled:
            log.info("sync_now ignored: sync_enabled=false on this machine")
            return
        if self._managed and self.sequencer is not None:
            try:
                self.sequencer.trigger_pass_now()
            except Exception:
                log.exception("sync_now: sequencer trigger failed")
            return
        for lane in self.lanes:
            try:
                lane.run_once()
            except Exception:
                log.exception("sync_now: lane %s failed", getattr(lane, "name", lane))

    def is_paused(self) -> bool:
        return self._paused

    def _set_express_paused(self, paused: bool) -> None:
        """Pause/resume lane A's express upload.

        Public lane API (pause_express/resume_express), never the lane's
        privates. getattr-guarded because tests and future lane adapters may
        not implement it; fault-isolated because pause must never raise out
        of a tray callback (or, since the root guard, out of a poll thread)."""
        for lane in (getattr(self, "_lane_a", None), getattr(self, "_lane_b", None)):
            fn = getattr(lane, "pause_express" if paused else "resume_express", None)
            if fn is None:
                continue
            try:
                fn()
            except Exception:
                log.exception(
                    "failed to %s express on %s",
                    "pause" if paused else "resume", getattr(lane, "name", lane),
                )

    def _toggle_express_pause(self) -> None:
        """Match the express lane to the tray's pause state."""
        self._set_express_paused(self._paused)

    def _login_gate_blocks_sync(self) -> bool:
        """The one gate start() and on_signed_in() both apply before letting
        any lane run: require_login with no verified identity."""
        return bool(self._require_login and not self.identity.valid())

    def toggle_pause(self) -> None:
        self._paused = not self._paused
        if not self._sync_enabled:
            log.info("pause toggled but sync_enabled=false -- nothing to pause")
            return
        if not self._paused and self._login_gate_blocks_sync():
            # RESUME IS A START. start() and on_signed_in() both refuse to
            # run lanes without a verified identity; this path called
            # _start_lanes() (legacy) / sequencer.resume() (managed) with no
            # such check, so on a machine that had correctly left its lanes
            # down, clicking Pause then Resume synced everything under an
            # unverified identity and set _lanes_started=True. Same after a
            # token expiry, which sets _lanes_started=False for exactly this
            # reason.
            self._mark_lanes_pending_login()
            log.warning(
                "resume ignored: sign-in required (require_login=true) and nobody is "
                "signed in -- sync lanes stay down"
            )
            self._notify_tray(
                "You're not signed in, so nothing will sync. Right-click the tray icon "
                "→ Sign in…", "ccsync-companion")
            return
        if self._managed and self.sequencer is not None:
            try:
                self.sequencer.pause() if self._paused else self.sequencer.resume()
            except Exception:
                log.exception("toggle_pause: sequencer failed")
            # The sequencer only owns the ROTATION. Lane A's express upload
            # runs off the watchdog on its own timer, so "Pause syncing" left
            # the editor still pushing every new clip to the NAS -- the one
            # thing the button is for (AUDIT_3 M-3).
            self._toggle_express_pause()
            # Lane C's poll loop is read-only status reporting -- it keeps
            # running regardless of pause state.
        else:
            # Delegate to _start_lanes()/_stop_lanes() rather than looping
            # over self.lanes directly: the old loop called lane.start()
            # unconditionally on EVERY lane regardless of lane_b_enabled,
            # so a base rig with lane_b_enabled=false would start
            # mirroring proxies -- something config says must never
            # happen -- on the very first Pause->Resume. _start_lanes()
            # already skips lane B correctly (see the toggle_pause
            # finding).
            try:
                self._stop_lanes() if self._paused else self._start_lanes()
            except Exception:
                log.exception(
                    "toggle_pause: failed to %s lanes",
                    "stop" if self._paused else "start",
                )
        log.info("sync %s", "paused" if self._paused else "resumed")

    # -- lifecycle ---------------------------------------------------
    def start(self) -> None:
        if self.config_problems:
            # DEL-3: takes precedence over the sign-in gate -- signing in
            # would not fix it, and the lane detail must name the real
            # blocker rather than telling the editor to sign in again.
            self._mark_lanes_misconfigured()
            log.error(
                "sync lanes/sequencer NOT started: %d config problem(s) that stop syncing",
                len(self.config_problems),
            )
        elif self._root_absent:
            # Deferred, not refused: the drive was out when the companion
            # launched (an SSD that was unplugged at login, or a Mac that woke
            # up before it mounted). _start_root_guard() below is what starts
            # the lanes for real, on the first present sighting.
            self._mark_lanes_root_absent()
            log.warning(
                "sync lanes/sequencer deferred: local_root %s is not available yet "
                "-- they start on their own when the drive comes back",
                self.config.get("local_root"),
            )
        elif self._login_gate_blocks_sync():
            # Not signed in yet: do NOT start sync lanes/the sequencer (same
            # spirit as the sync_enabled=False path above -- lanes stay
            # idle with a clear reason). The watcher, popup fixer, and tray
            # still start below so the editor has a way to sign in; the
            # reporter also still starts, but editor_identity() returning
            # None makes it skip every cycle until sign-in (see
            # reporter.py's post_once). on_signed_in() starts the lanes for
            # real once sign_in() succeeds.
            self._mark_lanes_pending_login()
            log.info(
                "sign-in required (require_login=true) -- sync lanes/sequencer will not "
                "start until the editor signs in (tray \"Sign in...\")"
            )
        else:
            self._start_lanes()
        try:
            self.reporter.start()
        except Exception:
            log.exception("failed to start dashboard reporter")
        try:
            self.manifest_cache.start()
        except Exception:
            log.exception("failed to start manifest cache")
        try:
            self._start_media_tree_thread()
        except Exception:
            log.exception("failed to start media tree cache thread")
        # Report (never delete) partial copies an interrupted FIX ALL left
        # behind -- see fixer.sweep_stale_tmp_files (AUDIT_2 CORE-H5). Off
        # the main thread: it walks local_root.
        try:
            threading.Thread(
                target=self._sweep_stale_tmp_files, name="ccsync-tmp-sweep", daemon=True
            ).start()
        except Exception:
            log.exception("failed to start stale-tmp sweep")
        try:
            self._identity_stop_event.clear()
            self._identity_thread = threading.Thread(
                target=self._identity_watch_loop, name="ccsync-identity", daemon=True
            )
            self._identity_thread.start()
        except Exception:
            log.exception("failed to start identity expiry watcher")
        # Refresh the site manifest (~/.ccsync/state/site.json) once per start,
        # off the main thread: the installer wrote it on install day, and it
        # goes stale when the admin re-provisions (SMB UNC, NAS Syncthing ID,
        # rclone SFTP tuning). refresh_site() falls back to the cache on any
        # failure, so a dashboard that predates /api/v1/site or is unreachable
        # costs one debug line (2026-08-17, SYNOLOGY_PORT_PLAN WP0/WP5).
        dashboard_url = str(self.config.get("dashboard_url", "") or "").strip()
        if dashboard_url:
            try:
                threading.Thread(
                    target=site_mod.refresh_site, args=(dashboard_url,),
                    name="ccsync-site-refresh", daemon=True,
                ).start()
            except Exception:
                log.exception("failed to start site manifest refresh")
        self._start_watcher_thread()
        # OUTSIDE the lanes branch above, and behind its own try, for the same
        # reason _start_lut_link() is: the base rig runs sync_enabled=false and
        # is the machine that needs proxy generation MOST (its local_root IS
        # the NAS tree, so a proxy made there fans out over lane B). An editor
        # whose lanes are gated on sign-in still gets the notifier.
        try:
            if self.proxy_generator is not None:
                self.proxy_generator.start()
            # With it, and for the same reasons: its own thread, its own
            # gate, and nothing to do on a machine nobody drops clips on.
            if self.broll_ingestor is not None:
                self.broll_ingestor.start()
            # ...and the music one beside it: separate thread, separate gate,
            # and nothing to do on a machine nobody drops music on.
            if self.music_ingestor is not None:
                self.music_ingestor.start()
            # ...and the fleet job runner: same shape again, and it does
            # nothing at all until a dashboard offers this machine work it
            # has the capability and the idleness to take.
            if self.job_runner is not None:
                self.job_runner.start()
        except Exception:
            log.exception("failed to start the proxy generator")
        # Next to it, and behind its own try for the same reason: it needs no
        # lanes and no sign-in (the clips are already on this disk), only a
        # project open in Resolve.
        try:
            if self.youtube_importer is not None:
                self.youtube_importer.start()
        except Exception:
            log.exception("failed to start the youtube importer")
        # Each behind its own try, on the same terms as the features above:
        # start() runs BEFORE the tray icon exists, so anything raising out of
        # here leaves the editor with no tray, no toast and only a log line
        # they have no menu item to open. _start_lut_link's first statement
        # reads local_root, which a hand-edited `local_root = 5` made raise
        # (COMP-CORE-4, 2026-08-14) -- but the rule is the general one, not
        # that one value.
        for name, starter in (
            ("shutdown guard", self._start_shutdown_guard),
            ("keep-awake", self._start_keep_awake),
            ("LUT/stills link", self._start_lut_link),
            ("root guard", self._start_root_guard),
            ("b-roll server", self._start_broll_server),
            ("yt-dlp manager", self._start_ytdlp_manager),
            # LAST: it supervises the threads everything above it started
            # (SYS-2). See _start_lane_watchdog.
            ("thread watchdog", self._start_lane_watchdog),
        ):
            try:
                starter()
            except Exception:
                log.exception("failed to start the %s", name)

    def _start_watcher_thread(self) -> None:
        """Start (or replace) the timeline watcher's thread.

        ONE start path, called from start() and from LaneWatchdog (SYS-2,
        resilience sweep 2026-08-28) -- a watchdog with a restart route of its
        own would be a second, untested way to spawn this thread.

        Clears the stop latch first: on a restart the event is still clear
        (shutdown is the only thing that sets it, and the watchdog stands down
        for that), but a future caller that stopped the watcher on purpose
        must not get a thread that exits immediately.
        """
        self._stop_event.clear()
        self._watcher_thread_error = None
        self._watcher_thread = threading.Thread(
            target=self._watcher_thread_target, name="ccsync-watcher", daemon=True
        )
        self._watcher_thread.start()

    def _watcher_thread_target(self) -> None:
        """watcher.run, with the exception that ends the thread recorded.

        The record is what makes LaneWatchdog's watchdog.json say WHY rather
        than "restarted for no stated reason". Re-raised, so
        threading.excepthook -- and through it crash_report -- still sees it
        exactly as before (SYS-2)."""
        try:
            self.watcher.run(self._stop_event)
        except BaseException as exc:
            self._watcher_thread_error = f"{type(exc).__name__}: {exc}"
            raise

    def _start_media_tree_thread(self) -> None:
        """Start (or replace) the media-tree cache thread. Same contract as
        _start_watcher_thread: the one start path, shared with the
        watchdog."""
        self._media_tree_stop_event.clear()
        self._media_tree_thread_error = None
        self._media_tree_heartbeat = time.monotonic()
        self._media_tree_thread = threading.Thread(
            target=self._media_tree_thread_target, name="ccsync-media-tree", daemon=True
        )
        self._media_tree_thread.start()

    def _media_tree_thread_target(self) -> None:
        try:
            self._media_tree_loop()
        except BaseException as exc:
            self._media_tree_thread_error = f"{type(exc).__name__}: {exc}"
            raise

    def _start_lane_watchdog(self) -> None:
        """The thing that notices when a loop thread stops (SYS-2).

        LAST in start()'s starter tuple, deliberately: it supervises threads
        the statements above it created, and a watchdog that ran first would
        read "not started yet" as "died". Its own thread is a daemon that
        wakes once a minute; the check itself never raises.
        """
        if self._lane_watchdog is not None:
            return
        watchdog = LaneWatchdog(
            self, state_path=Path(self._state_dir) / WATCHDOG_STATE_FILENAME)
        watchdog.start()
        self._lane_watchdog = watchdog

    def _start_ytdlp_manager(self) -> None:
        """Keep this machine's yt-dlp binary present and current.

        LAST, next to the b-roll server, and behind its own try for the same
        reason: its own daemon thread, no lanes, no sign-in and no Resolve --
        and a failure means one capability this fleet has never had is still
        missing, while everything that moves footage carries on. The thread
        itself waits 30 s before its first check so a 17 MB download never
        competes with startup (ytdlp_manager.INITIAL_DELAY_SECONDS).
        """
        try:
            if self.ytdlp is not None:
                self.ytdlp.start()
        except Exception:
            log.exception("failed to start the yt-dlp sidecar manager")

    def _start_broll_server(self) -> None:
        """Serve the b-roll web UI's "Send to Resolve" button.

        LAST in start(), and behind its own try: it is a convenience endpoint
        for one button in a web page, and everything above it is what moves
        the footage. broll_server.start() already swallows a failed bind
        (a stale standalone broll-companion holding 8899 is the expected
        cause and it says so in the log) -- this catch is for the rest.
        """
        try:
            self._broll_server = broll_server_mod.start(
                self.config, ytdl_deps=self._ytdl_deps(),
                # THE SAME deps object the orchestrator was built with -- it
                # carries `.ingestor`, which is how the /broll/ingest/* routes
                # reach the live batch. A second one would answer every route
                # "this machine cannot index".
                ingest_deps=self._broll_ingest_deps,
                # The SAME deps object the music orchestrator was built with,
                # for the same reason: it carries `.ingestor`, which is how
                # the /music/ingest/* routes reach the live batch.
                music_ingest_deps=self._music_ingest_deps)
        except Exception:
            log.exception("failed to start the b-roll Send-to-Resolve server")
            self._broll_server = None

    def _ytdl_deps(self) -> Any:
        """What the /ytdl download executor is allowed to know about this
        machine (ytdl_executor.Deps, docs/YTDL_LOCAL_DOWNLOAD.md §7).

        Three live seams, and each of them is the app's answer rather than a
        config key on purpose:

          - the yt-dlp sidecar manager itself, because its CACHED daily check
            is what lets GET /ytdl/capabilities answer inside the SPA's 1 s
            probe budget -- running the binary there would blow it;
          - editor_identity, not cfg["editor_name"], because a lease needs the
            VERIFIED holder (reporter.post_once's rule);
          - the project selection, because the manifest's project_label is
            validated against it before anything is written to disk -- a
            project this machine does not sync is refused.

        Returns None on any failure, which the server reads as "no local
        download capability": the fleet then downloads on the NAS exactly as it
        did before 0.8.0.
        """
        try:
            selection = self.selection_client
            return ytdl_executor_mod.Deps(
                self.config,
                ytdlp=self.ytdlp,
                editor_fn=self.editor_identity,
                # get() is live-then-cache-then-None; None is "we could not
                # ask", which the executor refuses on rather than guessing.
                selection_fn=(
                    (lambda: selection.get()[0]) if selection is not None else None
                ),
                # The dashboard-signed identity token. The fleet routes VERIFY
                # it since 2026-08-17 (H5): the shared report token proves
                # "a fleet machine" and this proves whose. Same getter shape
                # the reporter uses, so a sign-out stops claims at once.
                identity_token_fn=lambda: self.identity.token,
                # ...and the root guard, which every other feature that writes
                # into the tree already asks (comp-ytdl-1, 2026-08-21). The
                # cached verdict, for the same reason the ytdlp status is
                # cached: the capability probe has a 1 s budget. The executor
                # runs the full probe itself before it creates a directory.
                root_present_fn=self.root_is_present,
            )
        except Exception:
            log.exception("failed to build the ytdl executor dependencies")
            return None

    def _start_lut_link(self) -> None:
        """Keep Resolve's LUT directory pointed at the synced LUT library.

        Runs on EVERY machine including the base rig: the base rig syncs
        nothing (its local_root IS the NAS share) but it is where the library
        is curated, so it needs the link most of all.

        Its own thread, and never fatal: the check touches the filesystem and,
        on a first run, copies files -- neither belongs on the startup path,
        and an editor whose link cannot be made simply keeps the LUTs they
        already have."""
        local_root = config_mod.resolved_local_root(self.config)
        try:
            self._lut_links = luts_mod.LutLinkManager(self.config, local_root)
        except Exception:
            log.exception("failed to build the LUT link manager")
        try:
            self._stills = stills_mod.StillsManager(self.config, local_root)
        except Exception:
            log.exception("failed to build the stills manager")
        if self._lut_links is None and self._stills is None:
            return
        if not (
            (self._lut_links is not None and self._lut_links.enabled)
            or (self._stills is not None and self._stills.enabled)
        ):
            log.info("Resolve preference sync disabled by config (LUTs and stills both off)")
            return
        try:
            threading.Thread(
                target=self._lut_link_loop, name="ccsync-luts", daemon=True
            ).start()
        except Exception:
            log.exception("failed to start the LUT link thread")

    def _lut_link_loop(self) -> None:
        interval = config_mod.coerce_numeric(self.config, "lut_check_interval", 900)
        if interval <= 0:
            interval = 900
        while not self._stop_event.is_set():
            try:
                if self._lut_links is not None:
                    self._lut_links.check()
            except Exception:
                log.debug("luts: periodic check failed", exc_info=True)
            try:
                # Same thread and the same "only while Resolve is quit"
                # constraint, so the two reconciles land in the same window
                # rather than racing each other for it.
                if self._stills is not None:
                    self._stills.check()
            except Exception:
                log.debug("stills: periodic check failed", exc_info=True)
            try:
                # Cached for the tray: the scan walks Resolve's LUT folder,
                # which must never happen on the tray's message loop.
                strays = self._lut_links.find_strays()
                with self._lut_lock:
                    self._stray_luts = strays
            except Exception:
                log.debug("luts: stray scan failed", exc_info=True)
            if self._stop_event.wait(interval):
                return

    def stray_lut_count(self) -> int:
        """How many LUTs this machine has that the shared library does not.
        Cheap accessor for the tray -- the scan itself runs on the LUT
        thread above."""
        with self._lut_lock:
            return len(self._stray_luts)

    # -- missing proxies (proxy_gen.py) ---------------------------------
    # All four are NULL-SAFE: the generator is optional (its constructor is
    # allowed to fail without taking the companion with it), and the tray
    # calls these on its refresh thread where a None would be an AttributeError
    # inside the snapshot -- which degrades the whole menu, not one line.
    def proxy_gap(self) -> dict[str, Any]:
        """What the tray renders about missing proxies. Cheap: a lock-guarded
        read of the generator's cached scan, never a walk."""
        if self.proxy_generator is None:
            return {}
        return self.proxy_generator.gap()

    def proxy_coverage(self) -> dict[str, Any]:
        """The reporter's section. Same cached read as proxy_gap()."""
        if self.proxy_generator is None:
            return {}
        return self.proxy_generator.coverage()

    def youtube_import_status(self) -> dict[str, Any]:
        """The reporter's YouTube auto-import section. NULL-SAFE and cached
        for the same reasons as proxy_coverage() above: the importer's
        constructor is allowed to fail without taking the companion with it,
        and status() is a lock-guarded read that does no I/O."""
        if self.youtube_importer is None:
            return {}
        return self.youtube_importer.status()

    # -- the shared work-progress window (popup.WorkProgressWindow) --------
    #
    # ONE window at a time, deliberately: two live Tk roots in this process is
    # CORE-M3's wedged interpreter, and the b-roll batch and the proxy run are
    # never both crunching anyway (indexing blocks the generator). Opening the
    # second closes the first rather than refusing, because the click that
    # asked for it is the editor telling us which one they want to watch.
    def _open_work_window(self, key: str, title: str, subtitle: str,
                          snapshot_fn: Any, action_fn: Any) -> None:
        with self._work_window_lock:
            existing = self._work_window
            if existing is not None and existing[0] == key and existing[1].is_open():
                return
            if existing is not None:
                _close_work_window(existing[1], "the open work window")
            window = popup.WorkProgressWindow(title, subtitle, snapshot_fn, action_fn)
            self._work_window = (key, window)
        try:
            window.open()
        except Exception:
            log.exception("could not open the %s progress window", key)

    def close_work_window(self) -> None:
        with self._work_window_lock:
            existing, self._work_window = self._work_window, None
        if existing is not None:
            _close_work_window(existing[1], "the work window")

    def show_ingest_progress(self) -> None:
        """Tray action / automatic on a batch start: the b-roll window."""
        if self.broll_ingestor is None:
            return
        self._open_work_window(
            "ingest", "INDEXING B-ROLL",
            "Your clips are indexed on this machine and uploaded to the archive. "
            "Closing this window does not stop it.",
            self.broll_ingestor.progress_model, self._ingest_window_action)

    def show_music_ingest_progress(self) -> None:
        """Tray action / automatic on a batch start: the music window."""
        if self.music_ingestor is None:
            return
        self._open_work_window(
            "music_ingest", "INDEXING MUSIC",
            "Your tracks are analysed on this machine and uploaded to the "
            "library. Closing this window does not stop it.",
            self.music_ingestor.progress_model, self._music_ingest_window_action)

    def _music_ingest_window_action(self, name: str) -> None:
        if self.music_ingestor is None:
            return
        {
            "pause": self.pause_music_ingest,
            "resume": self.resume_music_ingest,
            "start_now": self.index_music_now,
            "cancel": self.cancel_music_ingest,
        }.get(name, lambda: None)()

    def _ingest_window_action(self, name: str) -> None:
        """The window's buttons are the tray's actions -- one object, two
        surfaces, so a pause from either means the same thing."""
        if self.broll_ingestor is None:
            return
        {
            "pause": self.pause_broll_ingest,
            "resume": self.resume_broll_ingest,
            "start_now": self.index_broll_now,
            "cancel": self.cancel_broll_ingest,
        }.get(name, lambda: None)()

    def show_proxy_progress(self) -> None:
        """Tray action / automatic on "make them now": the proxy window."""
        if self.proxy_generator is None:
            return
        self._open_work_window(
            "proxy", "MAKING PROXIES",
            "Proxies let the rest of the team see this footage. Closing this "
            "window does not stop them.",
            self._proxy_progress_model, self._proxy_window_action)

    def _proxy_progress_model(self) -> Any:
        """proxy_gen.gap() as the shared window draws it.

        The per-clip percentage and ETA are the generator's OWN numbers
        (`encoding_detail`, the history rollup) rather than a second estimate
        computed here: two ETAs for one queue is two ETAs that disagree.
        """
        gap = self.proxy_gap() or {}
        detail = [d for d in (gap.get("encoding_detail") or []) if isinstance(d, dict)]
        first = detail[0] if detail else {}
        encoding = bool(gap.get("encoding"))
        left = int(gap.get("left") or 0)
        made = int(gap.get("generated") or 0)
        eta = (gap.get("history") or {}).get("eta_seconds")
        return popup.ProgressModel(
            title="MAKING PROXIES",
            phase=str(gap.get("state") or ""),
            # Not os.path.basename: the path in encoding_detail is whatever
            # the generator recorded, and a Windows path shown by a Mac
            # companion (or a Windows-recorded state file read on macOS, or
            # simply the suite running on the macOS release runner) has
            # backslashes posix basename() does not split on (2026-08-18).
            item_label=(_leaf_name(str(first.get("path") or "")) if first
                        else ""),
            item_percent=first.get("percent"),
            done=made, total=made + left,
            failed=int(gap.get("failed") or 0),
            eta_seconds=eta,
            note=("" if encoding else
                  str(gap.get("blocked_reason") or "")
                  or _proxy_state_note(str(gap.get("state") or ""))),
            actions=("cancel",) if encoding else ("start_now",),
            finished=not encoding and left == 0,
        )

    def _proxy_window_action(self, name: str) -> None:
        if self.proxy_generator is None:
            return
        if name == "cancel":
            self.stop_proxy_generation()
        elif name == "start_now":
            self.proxy_generator.request_run()

    def _proxy_block_reason(self) -> Any:
        """`ProxyGenerator.blocked_fn`: True, a reason string, or False.

        Two answers on one seam because they are different states. True is the
        DEL-3 config gate the lanes use -- a half-configured install must not
        be quietly encoding into a tree whose local_root is wrong. A STRING is
        the 2026-08-18 precedence reversal: while a b-roll batch is crunching,
        proxy generation stands aside and the tray says why ("waiting:
        indexing b-roll first"). Indexing wins because it is the thing an
        editor is waiting on and it needs the same GPU.
        """
        if self.config_problems:
            return True
        ingestor = getattr(self, "broll_ingestor", None)
        if ingestor is None:
            return False
        try:
            return ingestor.blocking_reason() or False
        except Exception:
            log.debug("broll ingest: blocking_reason() failed", exc_info=True)
            return False

    # -- b-roll ingest (broll_ingest.py) --------------------------------
    # NULL-SAFE like the proxy accessors above and for the same reason: the
    # orchestrator's constructor is allowed to fail without taking the
    # companion with it, and the tray reads these on its refresh thread.
    def _ingest_deps(self, kind: Any = None) -> Any:
        """What an ingest orchestrator (and the 8899 routes) are allowed to
        know about this machine.

        The three live seams are the app's answers rather than config keys,
        exactly as _ytdl_deps' are: `editor_identity` because a lease needs
        the VERIFIED holder, `identity.token` because the fleet routes check
        the dashboard's signature (H5) and a signed-out machine must stop
        claiming at once, and the machine name because the server compares it
        against the leaseholder on every call after the claim (API.md §6a).
        """
        try:
            import platform

            return broll_ingest_mod.IngestDeps(
                self.config,
                editor_fn=self.editor_identity,
                identity_token_fn=lambda: self.identity.token,
                machine_name=platform.node(),
                kind=kind,
            )
        except Exception:
            log.exception("failed to build the ingest dependencies")
            return None

    def broll_ingest_status(self) -> dict[str, Any]:
        """The reporter's `broll_ingest` section -- the dashboard's
        BrollIngestIn fields only. Empty when nothing is happening, which is
        how an absent section clears the fleet grid's chip."""
        if self.broll_ingestor is None:
            return {}
        try:
            return self.broll_ingestor.report()
        except Exception:
            log.debug("broll ingest: report() failed", exc_info=True)
            return {}

    def broll_ingest_view(self) -> dict[str, Any]:
        """The TRAY's fuller view of the same snapshot (zero I/O)."""
        if self.broll_ingestor is None:
            return {}
        try:
            return self.broll_ingestor.status()
        except Exception:
            log.debug("broll ingest: status() failed", exc_info=True)
            return {}

    def music_ingest_status(self) -> dict[str, Any]:
        """The reporter's `music_ingest` section -- the dashboard's
        MusicIngestIn fields only. Empty when nothing is happening, which is
        how an absent section clears the fleet grid's chip."""
        if self.music_ingestor is None:
            return {}
        try:
            return self.music_ingestor.report()
        except Exception:
            log.debug("music ingest: report() failed", exc_info=True)
            return {}

    def music_ingest_view(self) -> dict[str, Any]:
        """The TRAY's fuller view of the same snapshot (zero I/O)."""
        if self.music_ingestor is None:
            return {}
        try:
            return self.music_ingestor.status()
        except Exception:
            log.debug("music ingest: status() failed", exc_info=True)
            return {}

    def index_music_now(self) -> None:
        """Tray action: "don't wait until I'm away" for the current batch."""
        if self.music_ingestor is None:
            self._notify_tray("Music indexing is not set up on this machine.")
            return
        self.music_ingestor.request_run()
        self._notify_tray(
            "Analysing the music batch now. It keeps going while you work.",
            "ccsync-companion: music")

    def pause_music_ingest(self) -> None:
        if self.music_ingestor is None:
            return
        self.music_ingestor.pause()
        self._notify_tray("Music indexing paused. Nothing already indexed is lost.",
                          "ccsync-companion: music")

    def resume_music_ingest(self) -> None:
        if self.music_ingestor is None:
            return
        self.music_ingestor.resume()
        self._notify_tray("Music indexing will carry on from where it stopped.",
                          "ccsync-companion: music")

    def cancel_music_ingest(self) -> None:
        """Tray action, CONFIRMED: the tracks already in the library stay, the
        rest are dropped."""
        if self.music_ingestor is None:
            return
        snap = self.music_ingest_view()
        if not snap.get("batch_uid"):
            return
        if not self._popup_active_lock.acquire(blocking=False):
            log.info("music ingest: not asking about the cancel -- a dialog is open")
            return
        try:
            confirmed = popup.confirm_dialog(
                "STOP INDEXING THIS MUSIC BATCH",
                f"{snap.get('done', 0)} of {snap.get('total', 0)} tracks are "
                "already in the library and they stay there.\n\nThe rest will "
                "not be indexed. The files themselves are not deleted.",
                ok_label="STOP INDEXING",
            )
        finally:
            self._popup_active_lock.release()
        if not confirmed:
            return
        self.music_ingestor.cancel("cancelled from the tray")
        self._notify_tray("Music indexing stopped.", "ccsync-companion: music")

    def index_broll_now(self) -> None:
        """Tray action: "don't wait until I'm away" for the current batch."""
        if self.broll_ingestor is None:
            self._notify_tray("B-roll indexing is not set up on this machine.")
            return
        self.broll_ingestor.request_run()
        self._notify_tray(
            "Indexing the b-roll batch now. It keeps going while you work.",
            "ccsync-companion: b-roll")
        # The window follows from the tick that starts crunching (the
        # `show_window` seam), not from here: one place decides, so a batch
        # that is still gated on something else does not get a window with
        # nothing in it.

    def pause_broll_ingest(self) -> None:
        if self.broll_ingestor is None:
            return
        self.broll_ingestor.pause()
        self._notify_tray("B-roll indexing paused. Nothing already indexed is lost.",
                          "ccsync-companion: b-roll")

    def resume_broll_ingest(self) -> None:
        if self.broll_ingestor is None:
            return
        self.broll_ingestor.resume()
        self._notify_tray("B-roll indexing will carry on from where it stopped.",
                          "ccsync-companion: b-roll")

    def cancel_broll_ingest(self) -> None:
        """Tray action, CONFIRMED: a cancel throws away an evening of GPU time
        and cannot be undone from here (the clips already live stay live)."""
        if self.broll_ingestor is None:
            return
        snap = self.broll_ingest_view()
        if not snap.get("batch_uid"):
            return
        if not self._popup_active_lock.acquire(blocking=False):
            log.info("broll ingest: not asking about the cancel -- a dialog is open")
            return
        try:
            confirmed = popup.confirm_dialog(
                "STOP INDEXING THIS B-ROLL BATCH",
                f"{snap.get('done', 0)} of {snap.get('total', 0)} clips are already "
                "in the archive and they stay there.\n\nThe rest will not be "
                "indexed. The clips themselves are not deleted.",
                ok_label="STOP INDEXING",
            )
        finally:
            self._popup_active_lock.release()
        if not confirmed:
            return
        self.broll_ingestor.cancel("cancelled from the tray")
        self._notify_tray("B-roll indexing stopped.", "ccsync-companion: b-roll")

    def generate_proxies_now(self) -> None:
        """Tray action: scan now and encode without waiting for idle."""
        if self.proxy_generator is None:
            self._notify_tray("Proxy generation is not set up on this machine.")
            return
        self.proxy_generator.request_run()
        # The window the owner asked for (2026-08-18): a six-hour encode
        # behind two tray lines is what "the lack of feedback is disturbing"
        # was about. Only on a run the editor ASKED for -- an idle-time run
        # must not put a window in front of whatever they left open.
        self.show_proxy_progress()
        self._notify_tray(
            "Making the missing proxies now. It stops on its own when they're done.",
            "ccsync-companion",
        )

    def stop_proxy_generation(self) -> None:
        """Tray action: stop encoding (the queue is rebuilt on the next scan)."""
        if self.proxy_generator is None:
            return
        self.proxy_generator.cancel_run()
        self._notify_tray("Stopped making proxies.", "ccsync-companion")

    def proxy_history_report(self) -> str:
        """Render the ledger as text and return the file's path ("" if none).

        The tray opens what this returns with its own _open_log(), which is
        the one place that knows to strip PYTHONHOME/PYTHON3HOME from a
        child's environment (AUDIT_2 CORE-M6) -- so this writes and does not
        launch. Rendered fresh on every call: proxy_history.jsonl is the
        store, the .txt is a view of it.
        """
        history = getattr(self.proxy_generator, "history", None)
        if history is None:
            self._notify_tray("Proxy generation is not set up on this machine.")
            return ""
        try:
            path = history.write_report()
        except Exception:
            log.exception("could not write the proxy history report")
            path = None
        if not path:
            self._notify_tray("The proxy history could not be written.")
            return ""
        return str(path)

    def share_stray_luts(self) -> None:
        """Tray action: copy this machine's unshared LUTs into the library.

        Confirms first, naming what would be copied: this publishes files to
        every other editor in the fleet, which is not something to do on a
        single mis-click. Copies only -- the editor's own copy stays exactly
        where Resolve already knows about it.
        """
        if self._lut_links is None:
            self._notify_tray("LUT sharing is not set up on this machine.")
            return
        with self._lut_lock:
            strays = list(self._stray_luts)
        if not strays:
            self._notify_tray("No LUTs to share -- the library already has everything here.")
            return
        library = self._lut_links.library()
        if not library.is_dir():
            self._notify_tray(
                "The shared LUT library hasn't synced to this machine yet -- try again later."
            )
            return
        total_mb = sum(int(s.get("size") or 0) for s in strays) / (1024 * 1024)
        preview = "\n".join(f"  • {s['name']}" for s in strays[:12])
        if len(strays) > 12:
            preview += f"\n  … and {len(strays) - 12} more"
        # SYNC-5 (2026-08-11): this was the ONE confirm_dialog site in the
        # companion that built a Tk root without the lock -- the sibling-root
        # condition that wedges the Tcl interpreter when a watcher out-of-tree
        # popup is already up (AUDIT_2 CORE-M3/H8). The adopt() is inside it
        # too: without the lock apply_upgrade's `_popup_active_lock.locked()`
        # guard saw nothing, so a self-upgrade could request_shutdown()
        # mid-copy and leave a truncated LUT under a final name -- which lane
        # A then publishes fleet-wide.
        if not self._popup_active_lock.acquire(blocking=False):
            log.info("share LUTs: another CCSync window is open -- not opening a second")
            self._notify_tray(
                "Another CCSync window is open. Close it and try sharing again.",
                "ccsync-companion")
            return
        try:
            confirmed = popup.confirm_dialog(
                "Share these LUTs with the team?",
                f"{len(strays)} LUT(s) on this machine ({total_mb:.1f} MB) are not in the shared "
                f"library.\n\nCopying them to {library} puts them on every editor's machine. "
                f"Your own copies stay where they are.\n\n{preview}",
                ok_label="SHARE",
            )
            if not confirmed:
                return
            result = self._lut_links.adopt(strays)
            with self._lut_lock:
                self._stray_luts = self._lut_links.find_strays()
        finally:
            self._popup_active_lock.release()
        errors = result.get("errors") or []
        message = f"Shared {result.get('copied', 0)} LUT(s) with the team."
        if errors:
            message += f" {len(errors)} could not be copied -- see the log."
            for err in errors:
                log.warning("luts: %s", err)
        self._notify_tray(message)

    def _start_keep_awake(self) -> None:
        """Stop the idle timer sleeping the machine mid-transfer.

        The shutdown guard only sees deliberate shutdowns; a machine that
        simply idles into sleep never sends WM_QUERYENDSESSION at all, and
        that is the likelier way an overnight upload dies."""
        if self._keep_awake is not None:
            return
        try:
            self._keep_awake = shutdown_guard_mod.make_keep_awake_guard(
                lambda: self._shutdown_block_reason() is not None,
                enabled=bool(self.config.get("keep_awake_while_syncing", True)),
            )
            self._keep_awake.start()
        except Exception:
            log.exception("failed to start the keep-awake guard")

    def _start_shutdown_guard(self) -> None:
        """Ask Windows to say "still syncing" on the shutdown screen.

        Never fatal: an editor whose guard fails to start syncs exactly as
        before, they just do not get the warning."""
        if self._shutdown_guard is not None:
            return
        try:
            self._shutdown_guard = shutdown_guard_mod.make_shutdown_guard(
                self._shutdown_block_reason,
                enabled=bool(self.config.get("shutdown_warning_enabled", True)),
                # macOS only: logout and `launchctl bootout` arrive as SIGTERM,
                # whose default disposition kills the interpreter mid-write.
                # Without a callback to run, shutdown_guard deliberately leaves
                # SIGTERM alone (a handler with nothing to call would swallow it
                # and hang the bootout) -- so this argument is the whole feature.
                on_shutdown=self.shutdown,
            )
            self._shutdown_guard.start()
        except Exception:
            log.exception("failed to start the shutdown guard")

    def _shutdown_block_reason(self) -> Optional[str]:
        """What to show on the shutdown screen, or None to let it proceed.

        Called by Windows on its own thread with a few seconds of patience at
        most, so it does nothing but read the lane statuses (documented cheap
        and non-blocking) and a cached connection summary -- no Resolve calls,
        no disk, no network.
        """
        # A disconnected drive means nothing CAN be moving, whatever the lanes
        # still say about their last backlog -- and telling an editor their
        # unplugged machine is "still syncing" on the shutdown screen is the
        # cry-wolf failure this guard is written to avoid.
        if self._paused or self.config_problems or self._root_absent:
            return None
        try:
            statuses = [lane.status() for lane in self.lanes]
        except Exception:
            log.exception("shutdown guard: could not read lane statuses")
            return None
        # PendingTracker, not the stateless describe_pending(): a lane reports
        # "syncing" from a NEED COUNT, so a NAS that went away overnight kept
        # this machine awake and un-shutdownable indefinitely with nothing in
        # flight.
        reason = self._pending_tracker.describe(statuses, self._lane_peer_states())
        if reason is not None:
            return reason
        # A proxy encode in flight blocks the same two things a transfer does:
        # the shutdown screen says why, and the keep-awake guard (which reads
        # this same function, _start_keep_awake) holds the machine awake so it
        # cannot idle-sleep mid-encode. Deliberate: the generator only runs
        # while the user is away, i.e. exactly when the idle timer fires. The
        # hold ends by itself when the queue drains. Cheap by contract --
        # block_reason() is a lock-guarded read with no I/O.
        # B-roll indexing before proxies, in the same order the two features
        # now hold the GPU: a batch only runs BECAUSE the editor walked away,
        # which is exactly when the idle timer would put the machine to sleep
        # on top of it.
        try:
            if self.broll_ingestor is not None:
                reason = self.broll_ingestor.block_reason()
                if reason:
                    return reason
        except Exception:
            log.debug("broll ingest block_reason() failed", exc_info=True)
        try:
            if self.proxy_generator is not None:
                return self.proxy_generator.block_reason()
        except Exception:
            log.debug("proxy generator block_reason() failed", exc_info=True)
        return None

    def _lane_peer_states(self) -> dict[str, Optional[bool]]:
        """{lane name: True/False/None} -- False ONLY where we positively know
        there is nobody to move bytes to.

        Lane C is the one lane that can answer this cheaply: its poll loop
        already caches /rest/system/connections for the relay diagnostics, and
        an empty connected-device set means the server is unreachable, so its
        outstanding need count is a backlog, not a transfer. Lanes A/B (rclone
        over SFTP) have no equivalent signal, so they are left unknown -- and
        unknown never vetoes a warning.
        """
        states: dict[str, Optional[bool]] = {}
        lane_c = getattr(self, "_lane_c", None)
        summary_fn = getattr(lane_c, "connection_path_summary", None)
        if summary_fn is None:
            return states
        try:
            summary = summary_fn() or {}
        except Exception:
            log.debug("connection_path_summary() failed", exc_info=True)
            return states
        if not isinstance(summary, dict) or "devices" not in summary:
            # No poll has succeeded yet (or an older lane): "can't tell".
            return states
        devices = summary.get("devices")
        states[str(getattr(lane_c, "name", "") or "")] = bool(devices)
        return states

    def _sweep_stale_tmp_files(self) -> None:
        from . import fixer as fixer_mod

        local_root = str(self.config.get("local_root", ""))
        try:
            # ONE walk of the tree feeds both sweeps below.
            tmp_files = fixer_mod.walk_ccsync_tmp_files(local_root)
            leftovers = fixer_mod.sweep_stale_tmp_files(local_root, tmp_files=tmp_files)
        except Exception:
            log.exception("stale-tmp sweep failed")
            return
        if leftovers:
            self._notify_tray(
                f"Found {len(leftovers)} half-copied file(s) from an interrupted copy. "
                "Nothing was deleted. Tray → Copy diagnostics for your admin.",
                "ccsync-companion")
        # ...and the OTHER half of an interrupted FIX ALL: the 0-byte final
        # name it reserved before starting the copy. Unlike the partial above
        # that one is deleted -- it is empty, so it is provably not the
        # editor's data, and left alone lane A uploads it and
        # --ignore-existing makes the empty file permanent for the whole
        # fleet (COMP-GUARD-1, 2026-08-14). No toast: there is nothing for
        # the editor to do, and their next FIX ALL now lands on the right
        # name instead of "<clip> (2).braw".
        try:
            reservations = fixer_mod.sweep_orphan_reservations(
                local_root, tmp_files=tmp_files)
        except Exception:
            log.exception("orphan reservation sweep failed")
            reservations = []
        if reservations:
            log.warning(
                "removed %d empty placeholder file(s) left by an interrupted copy "
                "-- see the lines above", len(reservations),
            )
        # Half-made proxies from an encode that was killed (power cut, kill -9,
        # a publish that hit an SMB sharing violation). REPORTED, never
        # deleted -- the same refusal as the .ccsync-tmp sweep above, and the
        # same reasoning: nothing on the filesystem proves some other process
        # isn't writing that file this second. They cost only disk: every lane
        # filter in both directions excludes `*.partial`, and the next scan
        # simply encodes the clip again.
        try:
            partials = proxy_gen_mod.sweep_stale_partials(local_root)
        except Exception:
            log.exception("stale proxy .partial sweep failed")
            return
        if partials:
            log.warning(
                "%d half-made proxy file(s) are left over from interrupted encodes "
                "-- see the lines above; nothing was deleted", len(partials),
            )
        self._recheck_orphan_reservations(local_root, tmp_files)

    def _recheck_orphan_reservations(
        self, local_root: str, tmp_files: list[tuple[float, str]]
    ) -> None:
        """Second look at the candidates that were too FRESH to judge.

        The self-upgrade restarts in seconds, so the residue of the copy it
        killed is usually younger than fixer.RESERVATION_IDLE_SECONDS when
        the startup sweep reaches it -- and lane A releases the 0-byte
        reservation 120 s after it was created, after which
        --ignore-existing makes the empty file permanent on the NAS
        (COMP-GUARD-1, 2026-08-14). Re-checks the paths the walk ALREADY
        found rather than walking the tree again, and waits on _stop_event so
        a Quit in that window is not held up. Never raises.
        """
        from . import fixer as fixer_mod

        try:
            now = time.time()
            fresh = [
                entry for entry in tmp_files
                if (now - entry[0]) < fixer_mod.RESERVATION_IDLE_SECONDS
            ]
            if not fresh:
                return
            if self._stop_event.wait(fixer_mod.RESERVATION_IDLE_SECONDS + 1.0):
                return
            removed = fixer_mod.sweep_orphan_reservations(
                local_root,
                idle_seconds=fixer_mod.RESERVATION_IDLE_SECONDS,
                tmp_files=fresh,
            )
            if removed:
                log.warning(
                    "removed %d empty placeholder file(s) left by a copy this "
                    "process's own restart interrupted", len(removed),
                )
        except Exception:
            log.exception("orphan reservation re-check failed")

    def _identity_expired_text(self) -> str:
        """What to say when the identity token stops being valid (APP-13).

        A clock hours out of true expires a pre-CR-86 token the instant it is
        issued, so "sign in again" sends the editor round a loop that cannot
        terminate. Past CLOCK_SKEW_WARN_SECONDS of measured skew, name the
        clock -- that IS the thing they can fix. With no measurement (an
        older dashboard, or no report accepted yet) the old sentence stands:
        a guess dressed as a diagnosis is worse than the plain instruction."""
        skew = getattr(self.reporter, "clock_skew_seconds", None)
        try:
            large = skew is not None and abs(float(skew)) >= reporter_mod.CLOCK_SKEW_WARN_SECONDS
        except (TypeError, ValueError):
            large = False
        if large:
            phrase = reporter_mod.skew_phrase(skew)
            return (f"This computer's clock is {phrase} the server's, which is why your "
                    "CCSync sign-in looks expired. Fix the clock (Windows: Date and time "
                    "-> Sync now) and syncing will start again.")
        return ("Your CCSync sign-in has expired, so syncing has stopped. "
                "Right-click the tray icon → Sign in…")

    def _identity_watch_loop(self) -> None:
        """Notice a token EXPIRING, not just a sign-out.

        At the instant the token expires, editor_identity() starts returning
        None so the reporter silently skips every cycle and the machine
        vanishes from the fleet grid -- but _apply_identity_role() was never
        re-run, so the lanes kept running under the now-stale role and
        effective_mode() silently reverted to config `mode` (AUDIT_2
        CORE-M11). Clock skew produces the same state instantly."""
        was_valid = self.identity.valid()
        while not self._identity_stop_event.wait(self.identity_check_interval):
            try:
                now_valid = self.identity.valid()
                if now_valid == was_valid:
                    continue
                was_valid = now_valid
                self._apply_identity_role()
                if not now_valid:
                    log.warning("identity token is no longer valid -- sign in again")
                    if self._require_login and self._lanes_started:
                        try:
                            self._stop_lanes()
                        except Exception:
                            log.exception("identity expiry: failed to stop sync lanes")
                        self._mark_lanes_pending_login()
                        self._lanes_started = False
                    # APP-13: a badly wrong clock invalidates a pre-CR-86
                    # token INSTANTLY, and "your sign-in has expired" is then
                    # a lie the editor cannot act on -- signing in again
                    # produces a token the same clock rejects again. Name the
                    # clock instead when we have measured it.
                    self._notify_tray(self._identity_expired_text(), "ccsync-companion")
                else:
                    self.on_signed_in()
            except Exception:
                log.exception("identity expiry watcher failed")

    def shutdown(self) -> None:
        # ONCE. The tray's Quit calls shutdown() and then icon.stop(), which
        # lets run()'s `finally` call it again; the self-upgrade calls it too
        # (request_shutdown). Two overlapping teardowns raced two
        # _stop_lanes()/reporter.stop() sequences -- including RcloneLane.stop
        # racing itself over `self._observer = None`.
        with self._shutdown_lock:
            if self._shutdown_started:
                log.debug("shutdown() already ran -- ignoring the repeat call")
                return
            self._shutdown_started = True
        # FIRST, before any teardown can wedge: this process has now DECIDED
        # to stop, so the next start must not report it as a crash. Everything
        # after this line -- including the hard-exit backstop for a thread that
        # will not join -- is a deliberate exit (CR-93).
        crash_report.mark_clean_exit(self.config)
        self._stop_event.set()
        # BEFORE the guards below: its whole job is to START threads, and one
        # tick landing during teardown would spawn a sequencer into a process
        # that is exiting. check() reads _shutdown_started too, so this is
        # belt and braces (SYS-2).
        try:
            if self._lane_watchdog is not None:
                self._lane_watchdog.stop()
        except Exception:
            log.exception("failed to stop the thread watchdog")
        # First: a guard still holding a block reason would make the machine
        # refuse to shut down on behalf of a companion that is exiting.
        # Likewise a keep-awake guard still holding ES_SYSTEM_REQUIRED would
        # leave the machine unable to sleep with nothing left to sync.
        guard, self._shutdown_guard = self._shutdown_guard, None
        awake, self._keep_awake = self._keep_awake, None
        # The root guard goes with them: its callbacks START LANES, and one
        # firing during teardown would leave a sequencer and an rclone child
        # running in a process that is exiting.
        root, self._root_guard = self._root_guard, None
        # The drive reminder's thread goes too, but its RECORD stays: a
        # companion that quits with the drive out owing work restarts with
        # the drive out owing work (drive_reminder.resume_remembered).
        try:
            self._drive_reminder.suspend()
        except Exception:
            log.exception("failed to stop the sync-drive reminder")
        for power_guard, label in ((guard, "shutdown"), (awake, "keep-awake"),
                                   (root, "sync-drive")):
            if power_guard is None:
                continue
            try:
                power_guard.stop()
            except Exception:
                log.exception("failed to stop the %s guard", label)
        # Right behind the power guards, before the lanes: this is what kills
        # a running ffmpeg child (really, since MEDIA-2, resilience sweep
        # 2026-08-28 -- the claim predates the code by months), and it is the
        # one thing in this teardown
        # that is still burning the machine's CPU while we work through the
        # rest. Its thread is joined in the bounded loop below.
        # BEFORE the proxy generator, because it owns more: an ffmpeg child,
        # a llama-server holding 4-12 GB of VRAM, and an rclone pushing a 40 GB
        # original. Its batch's lease then expires and this machine re-claims
        # it from the last checkpoint on the next start (plan §6).
        # BEFORE the ingestors, and first among the job-shaped things: it may
        # be holding a GPU with a whisper child on it, and its lease expires
        # by itself -- so stopping it hands the job back to the fleet rather
        # than losing it.
        try:
            if self.job_runner is not None:
                self.job_runner.stop()
        except Exception:
            log.exception("failed to stop the fleet job runner")
        try:
            if self.broll_ingestor is not None:
                self.broll_ingestor.stop()
        except Exception:
            log.exception("failed to stop the b-roll ingest orchestrator")
        # A work-progress window is a live Tk root; leaving one up while the
        # dispatcher shuts down is MAC-11's shape.
        try:
            self.close_work_window()
        except Exception:
            log.debug("failed to close the work window", exc_info=True)
        try:
            if self.proxy_generator is not None:
                self.proxy_generator.stop()
        except Exception:
            log.exception("failed to stop the proxy generator")
        # With it: the importer holds the Resolve scripting lock in bursts,
        # and a self-upgrade must not swap the exe out from under one.
        try:
            if self.youtube_importer is not None:
                self.youtube_importer.stop()
        except Exception:
            log.exception("failed to stop the youtube importer")
        # With them: its thread is usually asleep until tomorrow, but it may be
        # mid-download of a yt-dlp binary, and stop() only sets an event -- it
        # never waits, so this costs teardown nothing. NOT joined below: the
        # partial download is a `.new` temp file that the next install()
        # truncates, so nothing is left in a state anyone has to clean up.
        try:
            if self.ytdlp is not None:
                self.ytdlp.stop()
        except Exception:
            log.exception("failed to stop the yt-dlp sidecar manager")
        self._stop_lanes()
        try:
            self.reporter.stop()
        except Exception:
            log.exception("failed to stop dashboard reporter")
        try:
            self.manifest_cache.stop()
        except Exception:
            log.exception("failed to stop manifest cache")
        self._media_tree_stop_event.set()
        self._identity_stop_event.set()
        # Releases port 8899 before the process goes: the self-upgrade
        # relaunches within seconds, and a socket still held by the outgoing
        # process is exactly the bind failure the new one would report as a
        # stale standalone companion.
        broll_server_mod.stop(self._broll_server)
        self._broll_server = None
        # Join both Resolve-touching threads (bounded). A self-upgrade used
        # to exit the process while get_media_pool_items() was inside the
        # fusionscript C extension (AUDIT_2 §2-low). Bounded so a wedged
        # extension can still never block shutdown indefinitely.
        for thread in (self._watcher_thread, self._media_tree_thread):
            if thread is None or not thread.is_alive():
                continue
            try:
                thread.join(timeout=5.0)
                if thread.is_alive():
                    log.warning("shutdown: %s did not stop within 5s", thread.name)
            except Exception:
                log.exception("shutdown: failed to join %s", getattr(thread, "name", thread))
        # Bounded too, and for the same reason: the generator's worker may be
        # inside a kill+wait on an ffmpeg that is stuck in a kernel read on a
        # disconnected share, and a self-upgrade must not wait for it.
        try:
            if self.proxy_generator is not None:
                self.proxy_generator.join(timeout=5.0)
            if self.broll_ingestor is not None:
                self.broll_ingestor.join(timeout=5.0)
        except Exception:
            log.exception("shutdown: failed to join the proxy generator")
        # Bounded for the same reason again: its worker may be inside a
        # fusionscript ImportMedia call on a Resolve that has stopped
        # answering, and nothing in teardown may wait on that indefinitely.
        try:
            if self.youtube_importer is not None:
                self.youtube_importer.join(timeout=5.0)
        except Exception:
            log.exception("shutdown: failed to join the youtube importer")

        # LAST, after every thread that can ask for a window has been told to
        # stop and joined: on macOS this is the main thread's Tk pump, so
        # stopping it any earlier would leave a mid-shutdown dialog (the
        # watcher's popup, a confirm) blocked forever on a main thread that
        # no longer services the queue. Anything still waiting is unblocked
        # with UIDispatchStopped and takes its no-display default. On Windows
        # there is no dispatcher and this is a no-op.
        try:
            ui_dispatch.stop()
        except Exception:
            log.exception("shutdown: failed to stop the UI dispatcher")
        # APP-5: reaching the end of teardown is what makes this run a clean
        # one, so the next start does not count it towards the crash loop. An
        # editor quitting the tray three times in a morning is not a build
        # that cannot stay up.
        try:
            upgrade_mod.note_clean_shutdown(self._state_dir)
        except Exception:
            log.exception("shutdown: could not record the clean shutdown")
        self._arm_ui_shutdown_backstop()

    def _arm_ui_shutdown_backstop(self) -> None:
        """If the UI thread is STILL in serve() a grace period from now, end
        the process rather than leaving it alive with nothing running.

        Only ever arms on macOS (there is no dispatcher anywhere else), and
        only while serve() is actually running -- everything else exits
        through run()'s finally on its own. Daemon timer, so a normal exit
        takes it with us and nothing is delayed by it.
        """
        try:
            dispatcher = ui_dispatch.active()
            # getattr, not attribute access: this is a last-resort exit, and
            # a dispatcher shape it does not recognise must make it stand
            # down quietly rather than raise inside a SIGTERM handler.
            if dispatcher is None or not getattr(dispatcher, "serving", False):
                return
            timer = threading.Timer(UI_SHUTDOWN_GRACE_SECONDS, self._hard_exit_if_ui_wedged)
            timer.daemon = True
            timer.start()
        except Exception:
            log.exception("shutdown: could not arm the UI shutdown backstop")

    def _hard_exit_if_ui_wedged(self) -> None:
        dispatcher = ui_dispatch.active()
        if dispatcher is None or not getattr(dispatcher, "serving", False):
            # The mainloop returned -- run()'s finally is doing the rest.
            return
        windows = ", ".join(ui_dispatch.window_label(w)
                            for w in getattr(dispatcher, "open_dialogs", [])) or "none"
        log.error(
            "shutdown: the UI thread is still inside its event loop %.0fs after "
            "everything else stopped (windows still open: %s). Nothing is left to "
            "flush -- lanes, reporter and manifest cache are all stopped -- so this "
            "process is exiting hard rather than sitting here holding the "
            "single-instance slot against the next launch.",
            UI_SHUTDOWN_GRACE_SECONDS, windows,
        )
        _hard_exit(1)

    def _revert_crashing_build(self) -> bool:
        """This build has come up three times in ten minutes: put the previous
        one back (APP-5 / REL-2, resilience sweep 2026-08-28).

        True means the previous build is running and this process must exit.
        False means nothing was restored -- no rollback copy, an unknown
        previous version, the downgrade floor, or a restore that failed -- and
        the reason is logged rather than swallowed: a machine stuck in a crash
        loop with no way back is exactly the machine whose log an admin reads
        next. Never raises."""
        try:
            restored, refusal = upgrade_mod.revert_to_previous_build(
                self._state_dir, self.config,
                request_shutdown=self._stop_event.set,
            )
            if restored:
                return True
            log.error(
                "v%s has restarted %d times in under %d minutes and looks like it "
                "cannot stay up, but this machine did NOT roll back: %s",
                config_mod.VERSION, self._version_starts,
                int(upgrade_mod.CRASH_LOOP_WINDOW_SECONDS // 60),
                refusal or "no reason given",
            )
        except Exception:
            log.exception("the crash-loop guard failed")
        return False

    def run(self) -> None:
        try:
            setup_logging(self.config)
        except Exception:
            _fallback_logging(self.config)
        log.info("ccsync-companion v%s starting", config_mod.VERSION)
        log.info("config: %s", config_mod.CONFIG_PATH)

        # "Is this the first start on a new build?" now comes from a version
        # marker file, NOT from whether an `.old` happened to be unlinkable.
        # The old derivation fired the "Update complete" toast on an unrelated
        # later restart whenever an AV hold had deferred the unlink (AUDIT_2
        # CORE-H6). Since APP-5 the same record also counts STARTS, which is
        # what makes a build that boots and dies three minutes later
        # recoverable without an admin.
        start_record = upgrade_mod.note_version_start(self._state_dir)
        just_upgraded = bool(start_record.get("upgraded"))
        self._version_starts = int(start_record.get("starts") or 1)
        self._load_upgrade_state()
        if start_record.get("crash_loop") and self._revert_crashing_build():
            # The previous build is back on disk and running; this process is
            # the one that could not stay up. Nothing has been started yet, so
            # returning IS the shutdown.
            return

        # A half-configured install is the single most common failure mode and
        # is otherwise completely silent — nothing syncs and no lane says why.
        # (Computed in __init__ so the popup/FIX ALL/Consolidate gates see it
        # too; re-logged here where the log file actually exists.)
        errors, warnings = self.config_problems, self.config_warnings
        if errors:
            log.error(
                "config has %d problem(s) that STOP syncing -- fix these in %s:",
                len(errors), config_mod.CONFIG_PATH,
            )
            for problem in errors:
                log.error("  - %s", problem)
        for problem in warnings:
            log.warning("config: %s", problem)
        if not errors:
            log.info("config OK: remote=%s remote_root=%s local_root=%s",
                     self.config.get("remote"), self.config.get("remote_root"),
                     self.config.get("local_root"))

        # start() and the toast timer below are INSIDE the try/finally that
        # runs shutdown(): an exception from the watcher thread start or the
        # timer used to propagate past run() with shutdown() never called,
        # and rclone children are Popen'd, not daemon threads -- they keep
        # transferring against the tree after the companion is gone (AUDIT_2
        # CORE-M8).
        try:
            # BEFORE start() and before the tray: start() launches the watcher,
            # which can ask for a popup within a poll interval, and on macOS
            # the tray icon is installed against the runloop this dispatcher's
            # hidden root brings up. A dialog requested before serve() begins
            # waits in the queue instead of building a root on a worker thread.
            # On Windows start() does nothing at all and dispatch stays inline.
            try:
                ui_dispatch.start()
            except Exception:
                log.exception(
                    "could not start main-thread UI dispatch -- dialogs will be built "
                    "on their calling threads (fine on Windows, unreliable on macOS)")

            # AFTER the Tk root, and the order is load-bearing on macOS.
            # NSApp is a singleton and the FIRST caller decides its class.
            # Tk-Aqua installs its own NSApplication subclass (TKApplication)
            # and then sends it selectors only that subclass implements. When
            # this ran first -- it used to, above the "starting" line -- pyobjc
            # created a plain NSApplication, and Tk's very first colour lookup
            # died in the ObjC runtime, not in Python:
            #     -[NSApplication macOSVersion]: unrecognized selector
            #     … GetRGBA → TkpGetColor → Tk_GetColor → Tk_InitOptions
            # An uncaught NSException aborts the process (libc++abi), so the
            # try/except around ui_dispatch.start() cannot see it and the
            # companion vanished at startup with nothing after "config OK"
            # in the log. Verified on macOS 15.7.4 / Tk 9.0, 2026-08-04.
            # Once Tk owns NSApp, sharedApplication() returns the TKApplication
            # -- an NSApplication subclass -- so the policy call still works.
            # shutdown_guard's AppKit half is safe for the same reason: it is
            # started from self.start(), below.
            _set_darwin_activation_policy()

            self.start()

            try:
                from . import tray as tray_mod

                self._tray_icon = tray_mod.start_tray(self)
                log.info("tray icon started")
            except ImportError:
                self._tray_icon = None
                log.warning("pystray/Pillow not installed -- running headless (Ctrl+C to stop)")
            except Exception:
                # pystray.Icon(...) / _make_icon_image / _build_menu can raise
                # OSError/TclError/PIL errors too (no interactive session,
                # Explorer's tray not up yet at login, shell restart) -- only
                # catching ImportError here let any of those escape past the
                # try/finally below, skipping shutdown() entirely (lanes,
                # sequencer, reporter, watchdog observer all left running --
                # see S-11). Fall back to headless instead.
                self._tray_icon = None
                log.exception("tray icon failed to start -- running headless (Ctrl+C to stop)")

            if errors:
                self._notify_tray(
                    "NOT SYNCING: CCSync isn't fully set up on this machine. "
                    "Tray → Copy diagnostics for your admin.", "ccsync-companion")
            else:
                # The licence gate (_start_lanes) is silent apart from the log
                # and the lane detail, and an editor whose sync simply never
                # starts does not go looking in either. Only when there is no
                # config error to report first -- two "NOT SYNCING" toasts at
                # once tells them nothing (2026-08-17, item 3).
                eula_problem = self.eula_problem()
                if eula_problem:
                    self._notify_tray(f"NOT SYNCING: {eula_problem}", "ccsync-companion")
                    # ...and ASK, rather than leaving a toast the editor has to
                    # decode into an action (2026-08-18). A toast said the same
                    # thing on the machines that upgraded to 0.8.0 and every one
                    # of them sat there not syncing. Deferred a few seconds for
                    # the same reason the update toast below is: the tray icon
                    # thread has only just started, and this dialog's failure
                    # path wants somewhere to put a notification.
                    #
                    # A THREAD, not a one-shot Timer, since CR-27: the first
                    # attempt loses the popup lock on any machine with clips
                    # outside the tree, and losing it must not end the offer.
                    threading.Thread(
                        target=self._licence_watch, name="ccsync-licence-watch",
                        daemon=True,
                    ).start()

            if self._upgrade_reverted_from and not self._upgrade_attempts.get(
                    "reverted_announced"):
                # APP-5: this build IS the rollback. Same 3 s delay as the
                # update toast below, and for the same reason -- the tray icon
                # thread has only just started.
                bad = self._upgrade_reverted_from
                upgrade_mod.mark_revert_announced(self._upgrade_attempts_path())
                self._upgrade_attempts["reverted_announced"] = True
                revert_timer = threading.Timer(3.0, lambda: self._notify_tray(
                    f"The last update kept crashing, so CCSync went back to "
                    f"v{config_mod.VERSION}.",
                    "ccsync-companion",
                ))
                revert_timer.daemon = True
                revert_timer.start()
                log.warning("this build is a crash-loop rollback from v%s", bad)

            if just_upgraded:
                log.info("self-upgrade to v%s completed", config_mod.VERSION)
                # Slight delay: the tray icon thread has only just started and
                # Windows drops notify() calls for icons not yet registered.
                timer = threading.Timer(3.0, lambda: self._notify_tray(
                    f"Update complete. Now running v{config_mod.VERSION}.",
                    "ccsync-companion",
                ))
                timer.daemon = True
                timer.start()
                # ...and on macOS, did the update cost us the Full Disk Access
                # grant the tree needs? (item 16: ad-hoc signing means every
                # build is a new program to TCC.) Same delay, same reason --
                # the tray icon has only just started -- and off the startup
                # thread because it reads the disk.
                access_timer = threading.Timer(3.0, self._check_macos_volume_access)
                access_timer.daemon = True
                access_timer.start()

            # Only NOW is the rollback copy expendable: the new build has
            # constructed itself, validated config, started its lanes and put
            # a tray icon on screen. Deleting it as run()'s third statement
            # meant a build that crashed one line later left the machine with
            # a broken exe and no way back (AUDIT_2 CORE-H6).
            #
            # ...and 60 s after that was still far too early (APP-5 / REL-2,
            # resilience sweep 2026-08-28). The faults this rollback copy
            # exists for -- a Tk failure in the first dialog, an exception on
            # a code path only one editor's config reaches, a lane touching a
            # surrogate path -- happen minutes in, by which time the timer had
            # long since deleted the only way back. The signal is EVIDENCE
            # now: one report the dashboard accepted, or an hour of uptime for
            # a machine that cannot reach it. A shutdown before either leaves
            # the `.old` on disk, and the next start tries again.
            cleanup_thread = threading.Thread(
                target=upgrade_mod.keep_old_exe_until_healthy,
                args=(self._stop_event, self._report_accepted.is_set),
                name="ccsync-old-exe", daemon=True,
            )
            cleanup_thread.start()

            dispatcher = ui_dispatch.active()
            if dispatcher is not None:
                # macOS: the main thread belongs to Tk/AppKit from here until
                # shutdown -- serve() runs the hidden root's mainloop and
                # returns when _stop_event is set (tray Quit, self-upgrade).
                dispatcher.serve(self._stop_event)
            else:
                while not self._stop_event.is_set():
                    self._stop_event.wait(1.0)
        except KeyboardInterrupt:
            log.info("shutting down (KeyboardInterrupt)")
        finally:
            self.shutdown()
            if self._tray_icon is not None:
                try:
                    self._tray_icon.stop()
                except Exception:
                    pass


def setup_resolve_prefs_cli(argv: Optional[list[str]] = None) -> int:
    """`ccsync-companion --setup-resolve-prefs [--wait-for-resolve N]`.

    Point Resolve at the shared LUT library and the shared gallery, from the
    installers, using the SAME code the running companion uses -- rather
    than a second implementation in PowerShell and a third in bash, each
    with its own idea of how to edit a preference file that Resolve
    overwrites on exit.

    Resolve must be quit. With --wait-for-resolve, an open Resolve is
    reported and waited on rather than failed on, so the installer can ask
    the editor to quit it and carry straight on when they do.

    Exit codes: 0 = everything applied or already correct, 1 = nothing was
    applied. Deliberately NOT fatal to an install either way: the companion
    retries both on its own schedule, so the worst case is that these
    settings arrive the next time Resolve is closed rather than now.
    """
    import argparse

    parser = argparse.ArgumentParser(prog="ccsync-companion --setup-resolve-prefs")
    parser.add_argument("--setup-resolve-prefs", action="store_true")
    parser.add_argument(
        "--wait-for-resolve", type=float, default=0.0, metavar="SECONDS",
        help="wait up to SECONDS for a running Resolve to be quit (0 = do not wait)",
    )
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    cfg = config_mod.load_config()
    try:
        setup_logging(cfg)
    except Exception:
        _fallback_logging(cfg)
    local_root = config_mod.resolved_local_root(cfg)

    deadline = time.monotonic() + max(0.0, args.wait_for_resolve)
    announced = False
    while resolve_prefs_mod.resolve_is_running():
        if not announced:
            announced = True
            print(
                "DaVinci Resolve is running. It rewrites its own preferences when it "
                "exits, so anything set now would be thrown away.\n"
                "  --> Please quit DaVinci Resolve. This will continue automatically.",
                flush=True,
            )
        if time.monotonic() >= deadline:
            if announced:
                print("Still running -- skipping. The companion will apply these settings "
                      "the next time Resolve is closed.", flush=True)
            return 1
        time.sleep(3)
    if announced:
        print("Resolve is closed -- continuing.", flush=True)

    applied = 0
    for label, manager in (
        ("LUT library", luts_mod.LutLinkManager(cfg, local_root)),
        ("stills/gallery", stills_mod.StillsManager(cfg, local_root)),
    ):
        try:
            result = manager.check()
        except Exception as exc:
            print(f"  {label}: failed ({exc})", flush=True)
            continue
        status = str(result.get("status"))
        if result.get("changed"):
            applied += 1
            print(f"  {label}: set", flush=True)
        elif status in (resolve_prefs_mod.ALREADY, "already-present"):
            applied += 1
            print(f"  {label}: already correct", flush=True)
        else:
            print(f"  {label}: not set ({result.get('message') or status})", flush=True)
    return 0 if applied else 1


def run() -> None:
    # The installers call the exe with this flag to set Resolve's LUT and
    # gallery preferences at install time. Checked before anything else --
    # it must not acquire the single-instance lock or start a tray.
    if "--setup-resolve-prefs" in sys.argv[1:]:
        sys.exit(setup_resolve_prefs_cli())

    # The music library's "Send to Resolve" buttons run their Resolve call in
    # a killable CHILD process (music_server.call), because the scripting API
    # blocks indefinitely when Resolve is modal or on the Project Manager
    # window and that must never wedge the tray. In a frozen build there is no
    # interpreter to hand a script to -- sys.executable IS this exe -- so the
    # child is another copy of it, re-entered here. Same rule as the flag
    # above: no single-instance lock, no config, no tray.
    if music_worker.WORKER_FLAG in sys.argv[1:]:
        sys.exit(music_worker.main(sys.argv[1:]))

    # Before the first window of any kind: the taskbar decides which app a
    # window belongs to when its button is created, and without this it is
    # "the exe" and wears the exe's icon rather than the branded window mark
    # (theme.claim_app_identity, 2026-08-18).
    theme.claim_app_identity()

    cfg = config_mod.load_config()
    # Logging (and a first validate_config pass) must exist BEFORE
    # CompanionApp() is constructed -- a hand-edited bad value (e.g.
    # poll_interval = "fast") raises inside __init__, and in the windowed
    # (console=False) PyInstaller build sys.stderr is None, so without
    # logging already active the exe would just vanish with no log line,
    # no tray, no toast (see S-10). CompanionApp.run() also calls
    # setup_logging()/validate_config() itself -- harmless repeats
    # (setup_logging() just re-clears/re-adds handlers; idempotent).
    try:
        setup_logging(cfg)
    except Exception:
        # setup_logging() itself was the one unguarded statement here, so a
        # bad log_path took the windowed exe down before anything could say
        # why (AUDIT_2 CORE-H2).
        _fallback_logging(cfg)
    # AFTER logging, before anything that can throw. crash_report writes
    # ~/.ccsync/crashes/<ts>.json for every unhandled exception -- main thread
    # and worker threads alike -- carrying the tail of companion.log with it,
    # which is the half that has usually rotated away by the time an editor
    # reports the symptom. Local and silent by default; the network sender is
    # opt-in twice over (crash_reporting + crash_dsn, and sentry_sdk is not in
    # the frozen build). install() chains onto the existing hooks and never
    # raises, so nothing below it changes (2026-08-17, COMMERCIAL_READINESS.md
    # item 13).
    crash_report.install(cfg)
    errors, _warnings = config_mod.validate_config(cfg)
    if errors:
        log.error(
            "config has %d problem(s) that STOP syncing -- fix these in %s:",
            len(errors), config_mod.CONFIG_PATH,
        )
        for problem in errors:
            log.error("  - %s", problem)
    if not acquire_single_instance():
        _warn_already_running()
        return
    # AFTER the single-instance lock, deliberately: install_native writes a
    # run marker for THIS pid, and the instance that just lost the race is
    # about to exit -- it must not touch the live one's marker (CR-93). From
    # here on, a death that never reaches shutdown() is reported on the next
    # start, and a native abort leaves its thread dump in <crashes>/native.log.
    crash_report.install_native(cfg)
    try:
        app = CompanionApp(cfg)
        app.run()
    except Exception:
        log.exception("ccsync-companion crashed during startup/run")
        raise


if __name__ == "__main__":
    run()
