"""All DaVinci Resolve scripting-API interaction lives here.

Nothing in this module ever crashes the caller: every public function
returns None / False / a friendly {"ok": False, "message": ...} dict on any
failure (Resolve not running, no project, no timeline, import failure, etc).

We lazy-import DaVinciResolveScript and lazy-connect (scriptapp("Resolve"))
on every call rather than caching a connection, since Resolve may not be
running yet, may be restarted, etc.

Forked near-verbatim from the b-roll platform's standalone companion (env
bootstrap + never-raise connect + _norm_path). That companion has since been
absorbed into this one and retired (2026-08-10), so this file is now the only
copy — its last unique function, perform_insert, is near the bottom (the
YouTube auto-import pair below it is newer). Everything between `_norm_path`
and there is this app's own: timeline-item enumeration + ReplaceClip-based
relinking for the watcher and fixer.
"""

from __future__ import annotations

import logging
import os
import platform
import re
import sys
import threading
import time
import unicodedata
from pathlib import Path
from typing import Any, Optional

from . import (
    canon, library, proxy_relink, resolve_journal, resolve_prefs, script_server,
    ui_state,
)

log = logging.getLogger("ccsync.resolve")

# Serializes EVERY call into the Resolve C extension.
#
# Four threads call this module concurrently: the timeline watcher (every
# poll_interval), the media-tree refresh thread (every 120 s), tray daemon
# threads (Scan whole project / Copy this project's media in), and the
# FIX-ALL worker (replace_clip per row). fusionscript.dll is not documented
# as thread-safe and this module's own _pin_frozen_python3_home docstring
# records it faulting 0xc0000005 -- which takes the whole windowed companion
# down with zero log output. Reentrant because the public functions call
# connect() internally (AUDIT_2 CORE-H4).
_API_LOCK = threading.RLock()

# -- when a fusionscript call does not come back ---------------------------
#
# Nothing bounds a native call. ImportMedia against a P: mapping that has
# gone away, a media-pool walk on a stalled SMB mount, R12's stale-fusionscript
# wedge: any of them holds _API_LOCK (and the GIL) indefinitely, and every
# other thread that talks to Resolve -- the timeline watcher, the media-tree
# refresh, the tray's "Scan whole project", the b-roll /insert handler --
# parks behind it with NOTHING in the log, because the call that would have
# logged is the one that never returned (COMP-MEDIA-9, 2026-08-14).
#
# This does not make the wedge recoverable in process, and deliberately does
# not pretend to: a native call cannot be interrupted, and abandoning the
# thread that owns an RLock would leave it owned for ever. What it does is
# make the wedge VISIBLE and attributable -- "ImportMedia has been inside
# Resolve for 4 minutes" instead of "the companion froze" -- both in the log
# and in bridge_activity(), which is cheap enough for a status reader.
# Everything queues exactly as it did before; no call gains a new failure
# mode. The real fix is music_worker's shape (a killable child process), and
# resolve_bridge:1216-1220 records why the importer is not there yet.
BRIDGE_WEDGE_SECONDS = 30.0
# One line per episode, not one per waiting thread per 30 s: four threads
# behind a wedged call would otherwise write 480 WARNINGs an hour into the
# same 5 MB-rotating log the R15 investigation lost its history to.
BRIDGE_WEDGE_REPEAT_SECONDS = 300.0

_CALL_STATE_LOCK = threading.Lock()
# (name, owning thread ident, started monotonic) for the call inside the lock.
_call_in_flight: Optional[tuple[str, int, float]] = None
_last_wedge_warning_at: Optional[float] = None


def _note_wedge(waiting_for: str, waited: float) -> None:
    """Say that `waiting_for` has been waiting `waited` seconds. Never raises."""
    global _last_wedge_warning_at
    with _CALL_STATE_LOCK:
        current = _call_in_flight
        now = time.monotonic()
        if (_last_wedge_warning_at is not None
                and (now - _last_wedge_warning_at) < BRIDGE_WEDGE_REPEAT_SECONDS):
            return
        _last_wedge_warning_at = now
    if current is None:
        # The holder took the lock without going through this guard, or let
        # go between the timeout and this read. Either way the wait is real.
        held, holder = waited, "another Resolve call"
    else:
        holder, _ident, started = current
        held = max(0.0, time.monotonic() - started)
    log.warning(
        "resolve: %s has been inside Resolve for %.0fs and everything else that "
        "talks to it is waiting (%s has waited %.0fs). Resolve is busy, modal, or "
        "its media is on a share that has gone away -- nothing here can interrupt "
        "a scripting call, so if this does not clear, quit and reopen Resolve",
        holder, held, waiting_for, waited,
    )


class _bridge_call:
    """Take _API_LOCK for a named call, and say so when the wait is not normal.

    A class rather than @contextmanager so a nested (reentrant) take costs
    nothing: the public functions call connect() with the lock already held,
    and that must stay as free as a plain `with _API_LOCK`.
    """

    __slots__ = ("_name", "_nested")

    def __init__(self, name: str) -> None:
        self._name = name
        self._nested = False

    def __enter__(self) -> "_bridge_call":
        global _call_in_flight
        ident = threading.get_ident()
        with _CALL_STATE_LOCK:
            current = _call_in_flight
        if current is not None and current[1] == ident:
            # Same thread, same call: the RLock lets it straight through and
            # the outer name is the one worth reporting.
            self._nested = True
            _API_LOCK.acquire()
            return self
        started = time.monotonic()
        while not _API_LOCK.acquire(timeout=BRIDGE_WEDGE_SECONDS):
            _note_wedge(self._name, time.monotonic() - started)
        with _CALL_STATE_LOCK:
            _call_in_flight = (self._name, ident, time.monotonic())
        return self

    def __exit__(self, *exc_info) -> None:
        global _call_in_flight
        if not self._nested:
            with _CALL_STATE_LOCK:
                if (_call_in_flight is not None
                        and _call_in_flight[1] == threading.get_ident()):
                    _call_in_flight = None
        _API_LOCK.release()
        return None


def bridge_activity() -> dict[str, Any]:
    """{"call": str, "seconds": float} for the fusionscript call in flight.

    Empty when nothing is inside Resolve. Cached facts only -- no lock on the
    bridge itself, no probe, no I/O -- so a tray snapshot or the reporter may
    call it on their own threads, which is the whole point: the one thread
    that knows a call is wedged is the one that cannot say so.
    """
    with _CALL_STATE_LOCK:
        current = _call_in_flight
    if current is None:
        return {}
    name, _ident, started = current
    return {"call": name, "seconds": max(0.0, time.monotonic() - started)}


def reset_bridge_activity() -> None:
    """Forget the in-flight call and the wedge-warning cooldown -- tests only."""
    global _call_in_flight, _last_wedge_warning_at
    with _CALL_STATE_LOCK:
        _call_in_flight = None
        _last_wedge_warning_at = None


# Set process-wide by _pin_frozen_python3_home() so fusionscript.dll loads
# OUR python3.dll. They must not be inherited by children: they point at the
# outgoing process's _MEI... extraction dir, which the PyInstaller bootloader
# deletes seconds later -- and the self-upgrade spawn, every rclone child,
# os.startfile() and webbrowser.open() all inherit them (AUDIT_2 CORE-M6).
PINNED_PYTHON_ENV_VARS = ("PYTHONHOME", "PYTHON3HOME")


def sanitized_child_env(base: Optional[dict] = None) -> dict:
    """A copy of the environment safe to hand to a child process."""
    env = dict(os.environ if base is None else base)
    for name in PINNED_PYTHON_ENV_VARS:
        env.pop(name, None)
    return env


def _default_modules_dir() -> Optional[str]:
    system = platform.system()
    if system == "Windows":
        base = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
        return os.path.join(
            base,
            "Blackmagic Design",
            "DaVinci Resolve",
            "Support",
            "Developer",
            "Scripting",
            "Modules",
        )
    if system == "Darwin":
        # "Developer/Scripting/Modules", NOT "Scripting/Modules" -- the macOS
        # installer puts DaVinciResolveScript.py under Developer/ exactly like
        # the Windows branch above does, and the shorter path exists on no
        # machine. Getting it wrong is SILENT: the import fails, connect()
        # returns None at debug level, and the watcher reports "Resolve is not
        # running" on every poll forever -- so no out-of-tree popup, no mapping
        # warnings, no project name on the dashboard, with an INFO log that
        # looks perfectly healthy (MAC-?, found 2026-08-05).
        return (
            "/Library/Application Support/Blackmagic Design/DaVinci Resolve/"
            "Developer/Scripting/Modules"
        )
    return None


def _default_script_lib() -> Optional[str]:
    system = platform.system()
    if system == "Windows":
        pf = os.environ.get("PROGRAMFILES", r"C:\Program Files")
        return os.path.join(pf, "Blackmagic Design", "DaVinci Resolve", "fusionscript.dll")
    if system == "Darwin":
        return (
            "/Applications/DaVinci Resolve/DaVinci Resolve.app/"
            "Contents/Libraries/Fusion/fusionscript.so"
        )
    return None


def _pin_frozen_python3_home() -> None:
    """Point fusionscript at the frozen bundle's own python3.dll.

    fusionscript.dll has no static Python import: at load time it locates a
    Python 3 itself -- PYTHON3HOME/PYTHONHOME first, else the PEP 514
    registry (HK**\\SOFTWARE\\Python\\PythonCore\\<ver>\\InstallPath) -- and
    LoadLibrary()s that install's python3.dll by full path. Inside the
    PyInstaller exe that is fatal whenever the editor's registered Python
    doesn't match our bundled 3.12: the stable-ABI forwarder drags a second,
    uninitialized python3XY runtime into the process and the first C-API
    call segfaults (0xc0000005). No installed Python at all just as
    silently disables the bridge.

    So when frozen, pin PYTHON3HOME/PYTHONHOME to sys._MEIPASS, where
    build.spec now bundles the build interpreter's python3.dll -- that
    forwarder resolves (by module name) to the python312.dll already loaded
    in this process, on any machine, whatever Python is or isn't installed.
    Deliberately overwrites any inherited value: inside this exe, the only
    correct Python is our own.

    fusionscript.so on macOS locates its Python the same way, so the darwin
    branch is the same pin -- but only when the bundle actually carries a
    libpython to point at. Pinning PYTHONHOME at a directory with no Python
    in it breaks the interpreter far more thoroughly than an unpinned
    fusionscript ever could, so a bundle without one is left alone
    (fail-open) and the bridge falls back to whatever Python the machine has.
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if not meipass:
        return
    if sys.platform == "darwin":
        bundled = (
            "libpython3.12.dylib",
            os.path.join("Python3.framework", "Versions", "3.12", "Python3"),
            "Python3",
        )
        if not any(os.path.exists(os.path.join(meipass, name)) for name in bundled):
            return
        os.environ["PYTHON3HOME"] = meipass
        os.environ["PYTHONHOME"] = meipass
        return
    if os.path.exists(os.path.join(meipass, "python3.dll")):
        os.environ["PYTHON3HOME"] = meipass
        os.environ["PYTHONHOME"] = meipass


def _ensure_env_and_syspath() -> None:
    """Set up sys.path/env vars the standard Resolve way, honoring overrides.

    RESOLVE_SCRIPT_API / RESOLVE_SCRIPT_LIB, if already set in the
    environment, are left untouched (the whole point of the override).
    """
    _pin_frozen_python3_home()
    api_dir = os.environ.get("RESOLVE_SCRIPT_API")
    if api_dir:
        modules_dir = os.path.join(api_dir, "Modules")
    else:
        modules_dir = _default_modules_dir()
        if modules_dir:
            # "Modules" is one level below the Scripting dir that
            # RESOLVE_SCRIPT_API is documented to point at.
            os.environ.setdefault("RESOLVE_SCRIPT_API", os.path.dirname(modules_dir))

    if modules_dir and modules_dir not in sys.path:
        sys.path.append(modules_dir)

    if "RESOLVE_SCRIPT_LIB" not in os.environ:
        lib = _default_script_lib()
        if lib:
            os.environ["RESOLVE_SCRIPT_LIB"] = lib


def connect():
    """Return the Resolve scriptapp object, or None if unavailable. Never raises.

    Logs WHY on failure. Without this, a wrong RESOLVE_SCRIPT_LIB, a missing
    fusionscript.dll, a failed import and "Resolve simply isn't running" were
    all indistinguishable -- same message to the caller, nothing in the log,
    impossible to diagnose remotely (AUDIT_2 §2-low)."""
    with _bridge_call("connect"):
        # BEFORE anything touches fusionscript: a client that connects to the
        # script server while Resolve is still launching -- server spawned,
        # Resolve not yet registered with it -- takes the server down, and
        # Resolve gives up on scripting for its whole session (CR-68,
        # 2026-08-21; the mechanism and the log proof are in
        # script_server.py). The probe reads the TCP table, opens nothing,
        # and fails OPEN, so the only thing it can ever withhold is a
        # connection that would have killed the API.
        try:
            phase, why = script_server.state()
        except Exception:  # pragma: no cover -- state() never raises
            phase, why = script_server.UNKNOWN, ""
        if phase == script_server.STARTING:
            _note_starting(why)
            return None
        if phase == script_server.ABSENT:
            # No server at all: Resolve is closed, or launching and not there
            # yet. scriptapp() here would sit in a ~4 s retry loop and greet
            # the server the moment it appears -- the 0.9.45 failure. Quiet:
            # this is the normal state for hours at a time.
            _note_starting(None)
            return None
        _note_starting(None)
        try:
            _ensure_env_and_syspath()
        except Exception:
            log.warning("resolve: could not set up the scripting environment", exc_info=True)
            return None
        try:
            import DaVinciResolveScript as dvr_script  # type: ignore
        except Exception as exc:
            log.debug(
                "resolve: DaVinciResolveScript import failed (%s) -- RESOLVE_SCRIPT_API=%r "
                "RESOLVE_SCRIPT_LIB=%r",
                exc, os.environ.get("RESOLVE_SCRIPT_API"), os.environ.get("RESOLVE_SCRIPT_LIB"),
            )
            return None
        try:
            app = dvr_script.scriptapp("Resolve")
        except Exception as exc:
            log.debug("resolve: scriptapp('Resolve') raised (%s)", exc)
            return None
        if app is None:
            # NOT the same as "Resolve is not running" -- it also returns None
            # for a running Resolve whose script server never came up. See
            # describe_disconnection() below.
            log.debug("resolve: scriptapp('Resolve') returned None -- no connection")
        return app


# One INFO line per launch window, not one per poll per thread: the watcher
# asks every 3 s and the window is usually under a second, but a Resolve that
# is slow to register (a stalled project library) could hold it for minutes.
_starting_lock = threading.Lock()
_starting_since: Optional[float] = None


def _note_starting(why: Optional[str]) -> None:
    global _starting_since
    with _starting_lock:
        if why is None:
            if _starting_since is not None:
                log.info(
                    "resolve: script server has its host now -- connecting "
                    "(held off for %.1fs)", time.monotonic() - _starting_since,
                )
            _starting_since = None
            return
        if _starting_since is None:
            _starting_since = time.monotonic()
            log.info(
                "resolve: Resolve is starting up (%s) -- holding off every "
                "scripting call until it has registered, so the server is not "
                "taken down with a premature connection (CR-68)", why,
            )


def script_server_starting() -> bool:
    """Is Resolve in its launch window right now? Cheap; never raises."""
    try:
        return script_server.is_starting()
    except Exception:
        return False


def try_connect() -> bool:
    """Tolerant connectivity check (e.g. for tray status). Never raises."""
    try:
        return connect() is not None
    except Exception:
        return False


# -- why the bridge has no connection --------------------------------------
#
# connect() returning None has four causes and they need different actions
# from the user: Resolve isn't running (start it), the scripting environment
# is wrong (an admin fixes it), the import failed (same), or Resolve IS
# running and its script server is dead (quit and reopen it). Reporting all
# four as "DaVinci Resolve is not running" sent this rig looking for a
# companion bug for an hour on 2026-08-05 while Resolve sat open on screen --
# its Fusion script server had failed three start attempts at launch
# ("Failed to connect to script server" in davinci_resolve.log) and Resolve
# never retries, so the API was dead for that process's whole lifetime.
#
# The message the locked helpers put in their result. Replaced with real text
# by _explain_disconnection OUTSIDE _API_LOCK: the probe shells out, and a
# subprocess must never run with the bridge lock held (every other thread --
# watcher, tray, fix-all -- would block behind it).
_NOT_CONNECTED = "\x00ccsync:not-connected"

NOT_RUNNING_MESSAGE = "DaVinci Resolve is not running"
# The launch window (CR-68): Resolve is up, its script server is up, and it
# has not registered yet. Not a fault and not the NO_SCRIPTING state below,
# which is what a premature connection in THIS state used to produce.
STARTING_MESSAGE = "DaVinci Resolve is starting up"
# The order matters and is not obvious: fusionscript.dll keeps process-global
# IPC state, and a long-running client whose Resolve has restarted underneath
# it can wedge the NEW Resolve's scripting server for EVERY client -- at which
# point restarting Resolve alone can never fix it (proven live 2026-08-12:
# three Resolve restarts changed nothing; companion-then-Resolve connected
# first try). The companion now restarts itself when its Resolve goes away
# (app._maybe_recover_stale_bridge), so this advice is the manual fallback.
NO_SCRIPTING_MESSAGE = (
    "DaVinci Resolve is running but isn't accepting scripting connections. "
    "Quit and reopen Resolve. If that does not help, also restart the companion "
    "(tray → Exit, then relaunch) before reopening Resolve."
)
# No script server and a Resolve process: for the first minutes that is a
# Resolve launching (the server is spawned 90-470 s in) or shutting down
# (Resolve.exe lingers well after its windows go, and the process probe is
# cached 30 s on top). Only when it STAYS that way is it the dead-at-launch
# state NO_SCRIPTING_MESSAGE describes (owner report 2026-08-21: the tray
# gave the restart-everything advice within seconds of a normal quit).
NO_SERVER_MESSAGE = (
    "DaVinci Resolve is open but its scripting isn't available right now "
    "(starting up or shutting down)"
)
NO_SERVER_GRACE_SECONDS = 600.0
_no_server_lock = threading.Lock()
_no_server_since: Optional[float] = None

# A process probe costs a spawn (tasklist/pgrep) and the watcher asks on every
# failed poll -- every 3 s with Resolve closed. Cached so that costs two spawns
# a minute rather than twenty.
_PROBE_TTL_SECONDS = 30.0
_PROBE_LOCK = threading.Lock()
_probe_cache: Optional[tuple[float, bool]] = None


def _resolve_process_present() -> bool:
    """Is there a Resolve process at all? TTL-cached. Never raises.

    resolve_prefs.resolve_is_running() fails CLOSED -- an inconclusive check
    reports True. That bias is right here too: "quit and reopen Resolve" is
    survivable advice for someone whose Resolve is actually shut (they reopen
    it either way), while telling someone staring at an open Resolve that it
    "is not running" is the exact dead end this whole helper exists to end.
    """
    global _probe_cache
    with _PROBE_LOCK:
        cached = _probe_cache
        if cached is not None and (time.monotonic() - cached[0]) < _PROBE_TTL_SECONDS:
            return cached[1]
    try:
        present = resolve_prefs.resolve_is_running()
    except Exception:  # pragma: no cover -- resolve_is_running never raises
        present = True
    with _PROBE_LOCK:
        _probe_cache = (time.monotonic(), present)
    return present


def describe_disconnection() -> str:
    """User-facing reason the scripting bridge has no connection.

    Call only when connect() has already returned None -- this does not
    itself test the connection.
    """
    global _no_server_since
    if script_server_starting():
        return STARTING_MESSAGE
    if not _resolve_process_present():
        with _no_server_lock:
            _no_server_since = None
        return NOT_RUNNING_MESSAGE
    with _no_server_lock:
        now = time.monotonic()
        if _no_server_since is None:
            _no_server_since = now
        stale = (now - _no_server_since) >= NO_SERVER_GRACE_SECONDS
    return NO_SCRIPTING_MESSAGE if stale else NO_SERVER_MESSAGE


def _reset_no_server_clock() -> None:
    global _no_server_since
    with _no_server_lock:
        _no_server_since = None


DISCONNECTION_MESSAGES = (
    NOT_RUNNING_MESSAGE, NO_SCRIPTING_MESSAGE, STARTING_MESSAGE, NO_SERVER_MESSAGE,
)


def is_disconnection_message(message: Any) -> bool:
    """Does this result message mean "no connection at all"?

    Every OTHER unhappy answer a public enumerator returns ("no project open
    in Resolve", "no timeline open in Resolve", _SCRIPTING_ERROR_MESSAGE)
    comes from a bridge that DID connect -- Resolve is there, it just has
    nothing to show us. The watcher's transition logging and the tray's
    session line both need that distinction and neither should have to know
    which strings this module uses to draw it.
    """
    return str(message or "") in DISCONNECTION_MESSAGES


def _explain_disconnection(result: dict[str, Any]) -> dict[str, Any]:
    """Swap the _NOT_CONNECTED sentinel for the real reason, and record what
    the bridge's connection state turned out to be. Must be called with
    _API_LOCK released."""
    if result.get("message") == _NOT_CONNECTED:
        result["message"] = describe_disconnection()
        note_connection(False, result["message"])
    else:
        # Past connect(), whatever else went wrong: the bridge is up.
        _reset_no_server_clock()
        note_connection(True)
    return result


# -- has the bridge connected THIS SESSION? ---------------------------------
#
# The second follow-up of items 17 and 19, and the reason both cost hours:
# nothing anywhere said the bridge was dead. The tray showed three healthy
# lanes, the log at the shipped INFO level showed nothing at all, and the
# only way to find out was to probe the scripting API by hand.
#
# So the outcome of every enumeration is recorded here, at the one chokepoint
# both public enumerators already share (_explain_disconnection above), and
# the tray and Copy diagnostics READ it. Deliberately a cached fact and not a
# probe: a fusionscript call holds the GIL for its full native duration, and
# the tray render path is the last place that may pay for one.

_SESSION_LOCK = threading.Lock()
# None until something has actually asked Resolve -- "not connected" and "not
# checked yet" are different sentences and only one of them is alarming.
_session_connected: Optional[bool] = None
_session_ever_connected = False
_session_reason = ""


def note_connection(connected: bool, reason: str = "") -> None:
    """Record the bridge's connection state. Cheap, and never raises."""
    global _session_connected, _session_ever_connected, _session_reason
    with _SESSION_LOCK:
        _session_connected = bool(connected)
        _session_reason = "" if connected else str(reason or "")
        if connected:
            _session_ever_connected = True


def session_state() -> dict[str, Any]:
    """{"connected": True/False/None, "ever_connected": bool, "reason": str}.

    `connected` is None before the first enumeration of the process.
    `ever_connected` is the one an admin actually wants: a bridge that has
    never once connected this session is a broken install (MAC-10's wrong
    modules path), while one that connected and then went is Resolve being
    closed, restarted, or its script server dying (item 19).
    """
    with _SESSION_LOCK:
        return {
            "connected": _session_connected,
            "ever_connected": _session_ever_connected,
            "reason": _session_reason,
        }


def reset_session_state() -> None:
    """Forget everything recorded above -- for tests only; the companion has
    exactly one session and never calls this."""
    global _session_connected, _session_ever_connected, _session_reason
    with _SESSION_LOCK:
        _session_connected = None
        _session_ever_connected = False
        _session_reason = ""


def _norm_path(p: str) -> str:
    """Normalize for use as a dedupe/ignore KEY.

    Delegates to canon.norm rather than using the host's os.path directly:
    the strings that reach here are Resolve clip paths, which on a Mac may be
    canonical `P:\\...` spellings. posixpath.normcase is a no-op and treats
    `\\` as an ordinary filename character, so the host version silently
    stopped folding case and separators on macOS -- taking the popup dedupe,
    IgnoreTracker and the watcher's warn-once key down with it (MAC-3, first
    real macOS run 2026-08-04). Unchanged on Windows, and unchanged for real
    posix paths.
    """
    return canon.norm(p)


def _safe_clip_name(media_pool_item) -> str:
    try:
        name = media_pool_item.GetName()
        return name if name else ""
    except Exception:
        return ""


def _safe_folder_name(folder) -> str:
    try:
        name = folder.GetName()
        return name if name else ""
    except Exception:
        return ""


def _safe_project_name(project) -> str:
    try:
        name = project.GetName()
        return name if name else ""
    except Exception:
        return ""


def _safe_attr_str(obj, method_name: str) -> str:
    """`obj.<method_name>()` as a string, or "" for anything that goes wrong.

    Used for the timeline identity below: GetUniqueId exists on current API
    builds and not on older ones, and a missing method must cost a weaker
    fingerprint, never an exception on the watcher's path.
    """
    method = getattr(obj, method_name, None)
    if method is None:
        return ""
    try:
        return str(method() or "")
    except Exception:
        return ""


# -- handing the GIL back mid-sweep ----------------------------------------
#
# Every fusionscript call holds the GIL for its full native duration, and the
# timeline sweep makes three or four of them PER CLIP. On a large project
# that is a 1-3 s GIL blackout every poll_interval (3 s) -- and pystray's
# win32 message pump is a Python window procedure, so it cannot process the
# WM_RBUTTONUP that opens the tray menu until the sweep lets go. The menu
# then opens seconds late, or (the click having been consumed elsewhere) not
# at all. ui_state.wait_while_menu_open() cannot help here: it defers Resolve
# calls while the menu is ALREADY open, so it protects the open menu's
# highlight and not the click trying to open it.
#
# A real sleep -- not a no-op, not a lock release -- is what drops the GIL and
# lets a runnable thread be scheduled, so the pump is never more than
# _SWEEP_YIELD_EVERY clips away from a slot. The cost is bounded and tiny: at
# 2 ms per 25 clips, a 1000-clip timeline pays 80 ms per sweep.
_SWEEP_YIELD_EVERY = 25
_SWEEP_YIELD_SECONDS = 0.002


def _sweep_yield(counter: list[int]) -> None:
    """Count one swept clip, and yield the GIL every _SWEEP_YIELD_EVERY."""
    counter[0] += 1
    if counter[0] % _SWEEP_YIELD_EVERY == 0:
        time.sleep(_SWEEP_YIELD_SECONDS)


# -- one clip property, the cheap way (library walk, 2026-08-26) -----------
#
# GetClipProperty() with NO argument builds the whole property dictionary --
# 60-odd keys, every one of them formatted -- and measured 12.5 ms per clip
# on the base rig against 0.1 ms for the one-argument form. Over the 1,298
# clips of the open project the two agreed on "File Path" for every clip and
# every clip KIND (BRAW, R3D, ProRes, PNG sequence, multicam, compound), so
# the dict was buying nothing but time. A missing key answers None rather
# than raising.
#
# The one-arg form is not documented for every Resolve version we support,
# so the FIRST call decides for the process: an exception means this build
# has no such overload, and a None where the full dict has a value means it
# has one that does not work. Either way we say so once and use the dict for
# the rest of the session.
_ONE_ARG_CLIP_PROPERTY: Optional[bool] = None


def _reset_clip_property_probe() -> None:
    """Forget which form of GetClipProperty this build supports (tests)."""
    global _ONE_ARG_CLIP_PROPERTY
    _ONE_ARG_CLIP_PROPERTY = None


def _clip_property_dict(media_pool_item) -> dict:
    try:
        return media_pool_item.GetClipProperty() or {}
    except Exception:
        return {}


def _clip_property(media_pool_item, key: str) -> str:
    """One clip property, stripped. "" when the clip has no such value.

    Never raises. Caller holds _API_LOCK, like every other native call.
    """
    global _ONE_ARG_CLIP_PROPERTY
    if _ONE_ARG_CLIP_PROPERTY is False:
        return str(_clip_property_dict(media_pool_item).get(key) or "").strip()

    try:
        value = media_pool_item.GetClipProperty(key)
    except Exception as exc:
        if _ONE_ARG_CLIP_PROPERTY is None:
            _ONE_ARG_CLIP_PROPERTY = False
            log.info(
                "resolve: GetClipProperty(<key>) is not available on this build "
                "(%s) -- reading the full property dict per clip instead", exc,
            )
        return str(_clip_property_dict(media_pool_item).get(key) or "").strip()

    if value is not None:
        _ONE_ARG_CLIP_PROPERTY = True
        return str(value).strip()
    if _ONE_ARG_CLIP_PROPERTY:
        # Already proven good, so None here is the honest answer: this clip
        # has no such property (a still has no "Proxy Media Path").
        return ""
    # Undecided and unanswered. Only the dict can tell "no such property on
    # this clip" from "no such overload on this build", and getting that
    # backwards would cost every path the walk finds.
    answer = str(_clip_property_dict(media_pool_item).get(key) or "").strip()
    if answer:
        _ONE_ARG_CLIP_PROPERTY = False
        log.info(
            "resolve: GetClipProperty(%r) answered None where the full dict "
            "has a value -- reading the full property dict per clip instead", key,
        )
    return answer


# -- the project library session (library walk, 2026-08-26) ----------------
#
# One ProjectLibrary per (library, project), created lazily on whichever
# thread walks first and kept for as long as the project stays open. Its
# reads are SELECTs against PostgreSQL (or a disk library's SQLite) and must
# NEVER run under _API_LOCK: a library that has gone away takes the module's
# 5 s statement timeout to say so, and _API_LOCK is what the tray's message
# pump and every other Resolve client on the machine are waiting behind.
#
# Lock order is _LIBRARY_LOCK then _API_LOCK, never the reverse -- locate()
# asks Resolve which library this is, and the proxy enrichment below asks
# Resolve about clips the library has already named.
_LIBRARY_LOCK = threading.RLock()

# How long after a failure before we try the library again. NOT every poll:
# a NAS that is off answers a connect attempt in 5 s of stalled watcher
# thread, and doing that every 3 s would make the fallback more expensive
# than the API walk it exists to avoid.
_LIBRARY_RETRY_SECONDS = 60.0

# The fallback is a permanent, load-bearing state on plenty of machines (a
# disk library we have no reader for, a laptop off the NAS's network), so it
# is said ONCE at WARNING and then kept at INFO on a long cadence -- a line
# every 3 s poll would be the loudest thing in the log and the least useful.
_LIBRARY_FALLBACK_LOG_SECONDS = 300.0

# A CEILING on how stale a library answer may be, independent of
# ProjectLibrary.changed(). That signal rides on Sm2Sequence.DbSavedTime,
# which only moves when the project is SAVED -- so with Live Save switched
# off (and it is a per-machine preference, not something this companion
# controls) an editor can relink a clip and changed() will keep saying "no"
# until they press Ctrl-S, which might be after lunch. The valve costs one
# extra walk a minute of an operation measured in milliseconds (wave-1
# review, 2026-08-26).
_LIBRARY_CACHE_MAX_SECONDS = 60.0

_library: Optional[library.ProjectLibrary] = None
_library_read_stamp = 0.0
_library_project = ""
_library_next_attempt = 0.0
_library_generation = 0
_library_fallback_warned = False
_library_fallback_logged_at = 0.0
_library_settings_cache: Optional[dict[str, Any]] = None
_library_state: dict[str, Any] = {
    "source": "", "error": "", "walk_ms": 0.0, "library": "", "project": "",
}

_LIBRARY_CONFIG_KEYS = (
    "library_walk", "library_db_host", "library_db_port", "library_db_name",
    "library_db_user", "library_db_password",
)


def configure_library(cfg: dict[str, Any]) -> None:
    """Hand this module the config the library walk needs.

    This is the ONLY config the bridge reads, and it is pushed in rather
    than loaded here so the module stays what it has always been: a thing
    that talks to Resolve and nothing else. app.py calls this at startup.
    Anything that never calls it (a tool, a test) gets one lazy
    load_config() the first time a walk happens.

    Changing any of the six keys drops the open library, so an editor who
    fixes a wrong host does not have to restart the companion.

    Each key falls back to config.DEFAULTS, not to None: a PARTIAL cfg (the
    dashboard hands one, and so does every test that builds a dict by hand)
    used to switch the walk off silently, because `library_walk` came back
    None and None is false (library walk review 2, 2026-08-26).
    """
    global _library_settings_cache
    from . import config as config_mod

    settings = {key: cfg.get(key, config_mod.DEFAULTS.get(key))
                for key in _LIBRARY_CONFIG_KEYS}
    with _LIBRARY_LOCK:
        if settings != _library_settings_cache:
            _close_library("configuration changed")
            _library_settings_cache = settings
            # A new address deserves a fresh attempt, not the old backoff.
            _arm_library_retry(0.0)


def _config_without_creating() -> dict[str, Any]:
    """config.toml if it is there, DEFAULTS if it is not. Never WRITES one.

    config_mod.load_config() calls ensure_config_exists() first, so every
    lazy read in this module was a first-run config.toml waiting to happen
    on a rig that has none -- a tool, a test or a bare import creating the
    installer's file (library walk review 2, 2026-08-26). Nothing here needs
    that: absent config means defaults, which is what the merge would give.

    Imported here, not at module scope: config.py is imported by almost
    everything and this module is imported BY config's callers, so keeping
    it lazy keeps the import graph one-way.
    """
    from . import config as config_mod

    try:
        if config_mod.CONFIG_PATH.exists():
            return config_mod.load_config()
    except Exception:
        log.debug("resolve: could not load config", exc_info=True)
    return dict(config_mod.DEFAULTS)


def _library_settings() -> dict[str, Any]:
    """The six library keys, from configure_library() or from config.toml."""
    global _library_settings_cache
    with _LIBRARY_LOCK:
        if _library_settings_cache is None:
            from . import config as config_mod

            cfg = _config_without_creating()
            _library_settings_cache = {key: cfg.get(key, config_mod.DEFAULTS.get(key))
                                       for key in _LIBRARY_CONFIG_KEYS}
        return dict(_library_settings_cache)


def _library_walk_enabled() -> bool:
    return bool(_library_settings().get("library_walk", True))


def _arm_library_retry(seconds: float) -> None:
    global _library_next_attempt
    _library_next_attempt = time.monotonic() + seconds


def reset_library_state() -> None:
    """Drop the library session and everything remembered about it (tests,
    and anything that knows the answer has changed)."""
    global _library_settings_cache, _library_generation, _library_read_stamp
    global _library_fallback_warned, _library_fallback_logged_at
    with _LIBRARY_LOCK:
        _close_library("reset")
        _library_settings_cache = None
        _library_generation = 0
        _library_read_stamp = 0.0
        _library_fallback_warned = False
        _library_fallback_logged_at = 0.0
        _arm_library_retry(0.0)
        _library_state.update({"source": "", "error": "", "walk_ms": 0.0,
                               "library": "", "project": ""})


def library_status() -> dict[str, Any]:
    """What the last walk did -- a DIAGNOSTIC entry point, not a UI feed.

    Nothing in the running companion calls this: the tray is deliberately
    not wired to it (a menu item that says "library" or "api" is a support
    question, not a control), and it exists for tools/library_walk_check.py,
    tools/library_walk_timing.py and the tests (library walk review 2,
    2026-08-26). Anything that DOES start reading it should know the answer
    is whatever the last walk on any thread left behind.

    {"enabled", "source": "library"|"api"|"", "library", "project", "error",
     "walk_ms", "retry_in"}. Never raises, never calls Resolve.
    """
    with _LIBRARY_LOCK:
        # Deliberately does NOT load config.toml: a status read must not be
        # the thing that creates a first-run config file.
        enabled = True if _library_settings_cache is None else bool(
            _library_settings_cache.get("library_walk", True))
        retry_in = max(0.0, _library_next_attempt - time.monotonic())
        return {
            "enabled": enabled,
            "connected": _library is not None,
            "retry_in": round(retry_in, 1),
            **{key: value for key, value in _library_state.items()},
        }


def _close_library(why: str) -> None:
    """Drop the open library. Caller holds _LIBRARY_LOCK."""
    global _library, _library_project
    if _library is not None:
        log.debug("resolve: closing the project library (%s)", why)
        try:
            _library.close()
        except Exception:
            log.debug("resolve: closing the project library failed", exc_info=True)
    _library = None
    _library_project = ""


def _note_library_fallback(why: str) -> None:
    """Say -- once loudly, then rarely -- that we are back on the API walk."""
    global _library_fallback_warned, _library_fallback_logged_at
    message = (
        "library walk unavailable (%s) -- using the API walk; clicks in other "
        "Resolve clients will lag during walks" % why
    )
    now = time.monotonic()
    _library_state.update({"source": "api", "error": str(why)})
    if not _library_fallback_warned:
        _library_fallback_warned = True
        _library_fallback_logged_at = now
        log.warning("resolve: %s", message)
        return
    if now - _library_fallback_logged_at >= _LIBRARY_FALLBACK_LOG_SECONDS:
        _library_fallback_logged_at = now
        log.info("resolve: %s", message)
    else:
        log.debug("resolve: %s", message)


def _library_attempt_due() -> bool:
    """Is a library walk worth ATTEMPTING at all right now?

    Answered without touching Resolve, so a machine that will never have a
    library pays nothing per poll but this comparison -- the whole point of
    the backoff.
    """
    with _LIBRARY_LOCK:
        if not _library_walk_enabled():
            return False
        if _library is not None:
            return True
        return time.monotonic() >= _library_next_attempt


def _project_library(resolve, project_name: str) -> Optional[library.ProjectLibrary]:
    """The ProjectLibrary for the open project, or None. Never raises.

    Caller holds _LIBRARY_LOCK and does NOT hold _API_LOCK: locating takes
    two cheap Resolve calls (which take the API lock themselves) but
    CONNECTING is a database call with a 5 s timeout.
    """
    global _library, _library_project
    if _library is not None and _library_project == project_name:
        return _library
    if _library is not None:
        # Project change: this library object is scoped to one project's
        # rows and cannot answer for another.
        _close_library("project changed to %r" % project_name)
    if time.monotonic() < _library_next_attempt:
        return None

    _arm_library_retry(_LIBRARY_RETRY_SECONDS)
    # _API_LOCK for the API question ONLY. The rest of locate() is
    # filesystem work -- it reads the whole Resolve log and walks
    # "Resolve Project Library/*/Resolve Projects/..." for a disk library --
    # and doing that under the lock put a cold-cache directory walk in front
    # of the tray's message pump and every other scripting client on the
    # machine (library walk review 2, 2026-08-26).
    with _bridge_call("library.locate"):
        api_info = library.database_info(resolve)
    info = library.locate(None, project_name, _library_settings(),
                          api_info=api_info)
    if info is None:
        _note_library_fallback("no project library found for %r" % project_name)
        return None
    try:
        opened = library.ProjectLibrary(info, project_name)
    except library.LibraryUnavailable as exc:
        _note_library_fallback(str(exc))
        return None
    except Exception as exc:                     # pragma: no cover - defensive
        _note_library_fallback("%s: %s" % (info.describe(), exc))
        return None

    _library = opened
    _library_project = project_name
    _arm_library_retry(0.0)
    _library_state.update({"library": info.describe(), "project": project_name,
                           "error": ""})
    log.info("resolve: reading clips from the project library %s for %r",
             info.describe(), project_name)
    return opened


def _library_failed(exc: Exception) -> None:
    """A library that answered before has stopped. Caller holds _LIBRARY_LOCK."""
    _close_library("read failed")
    _arm_library_retry(_LIBRARY_RETRY_SECONDS)
    _note_library_fallback(str(exc))


def _library_answers_are_stale() -> bool:
    """Has it been long enough that we re-read whatever changed() says?"""
    return (time.monotonic() - _library_read_stamp) >= _LIBRARY_CACHE_MAX_SECONDS


def _library_read_done() -> None:
    """A walk really went to the database just now. Caller holds _LIBRARY_LOCK."""
    global _library_read_stamp
    _library_read_stamp = time.monotonic()


def _drop_library_path_cache(project_library) -> None:
    """Make the next read fetch pool paths from the database again.

    ProjectLibrary caches uid -> path until changed() says the library moved,
    and changed() cannot see an unsaved edit (see _LIBRARY_CACHE_MAX_SECONDS).
    `invalidate()` is asked for first so that a future library.py can offer
    one; the attribute reset is the fallback and is deliberately harmless if
    it is ever renamed away.
    """
    invalidate = getattr(project_library, "invalidate", None)
    if callable(invalidate):
        try:
            invalidate()
            return
        except Exception:
            log.debug("resolve: library invalidate() failed", exc_info=True)
    try:
        project_library._paths = None
    except Exception:                            # pragma: no cover - defensive
        log.debug("resolve: could not drop the library's path cache", exc_info=True)


def _current_project_locked() -> tuple[Optional[dict[str, Any]], Any, Any, str]:
    """(error result, resolve, project, project name). Caller holds _API_LOCK.

    The error result is None when there IS a project; otherwise it is the
    dict every enumerator in this module returns for that condition, so the
    caller can hand it straight back instead of walking anything. `resolve`
    comes back with it so no caller pays for a second connect().
    """
    resolve = connect()
    if resolve is None:
        return ({"ok": False, "message": _NOT_CONNECTED, "items": [],
                 "project_name": ""}, None, None, "")
    try:
        project_manager = resolve.GetProjectManager()
        project = project_manager.GetCurrentProject() if project_manager else None
    except Exception:
        project = None
    if project is None:
        return ({"ok": False, "message": "no project open in Resolve", "items": [],
                 "project_name": ""}, resolve, None, "")
    return (None, resolve, project, _safe_project_name(project))


def get_timeline_items(allow_cached: bool = False) -> dict[str, Any]:
    """Enumerate every video+audio timeline item on the current timeline.

    Returns {"ok": bool, "message": str, "items": [...], "project_name": str}.
    Never raises.

    Each item dict: {
        "file_path": str,               # GetClipProperty()["File Path"]
        "media_pool_item": <object>,    # None from a walk that had no objects
        "media_pool_uid": str,          # MediaPoolItem.GetUniqueId(), "" if unavailable
        "source": "api" | "library",
        "via_multicam": str | None,     # uid of the multicam this angle came through
        "clip_name": str,
        "track_type": "video" | "audio",
        "track_index": int,             # 1-based, per Resolve's own convention
        "item_index": int,              # 0-based position within the track
    }

    NEVER read "media_pool_item" to act on a clip -- call
    resolve_media_pool_item(item), which falls back to a cached lookup by uid
    (library walk, 2026-08-26).

    Items come from the PROJECT LIBRARY when one can be read (source
    "library") and from the scripting API otherwise (source "api"); the
    dicts are the same shape either way. Two things about the library's
    extra reach are worth knowing at every call site:

    * A multicam or compound clip is expanded to its ANGLES, and an angle's
      "media_pool_uid" is the angle's OWN pool clip -- so anything that acts
      on one (replace_clip, link_proxy_media) acts on the angle inside the
      multicam, not on the multicam. That is the intent: the angle is the
      clip with the offline path. "via_multicam" carries the container's uid
      for anyone who needs to say which multicam it came from.
    * Only the FIRST cut of a multicam expands. Later cuts of it, and
      anything else with no media path, are dropped here exactly as the API
      walk drops a clip whose "File Path" is "".

    "project_name" is the current Resolve project's GetName() (empty string
    if unavailable) — the watcher attaches it to OUT_OF_TREE items so the
    popup fixer can suggest a destination inside the project actually being
    edited, instead of a static config value (see fixer.match_project_dir).

    Items with no media pool item (generators, titles, adjustment clips) or
    an empty "File Path" are skipped entirely — per SPEC.md's watcher spec.

    `allow_cached` arms the poll cache described below; only the watcher's
    poll_timeline_items() passes it. Every other caller (and the default)
    gets a full walk of the live timeline.
    """
    # Defer while the tray menu is open: a fusionscript call holds the GIL
    # for its full native duration, and the open menu's highlight repaints
    # run through a Python window procedure that needs that same GIL -- one
    # poll here froze the hover highlight for a second-plus (2026-07-26).
    ui_state.wait_while_menu_open()
    result = _library_timeline_items(allow_cached=allow_cached)
    if result is None:
        with _bridge_call("get_timeline_items"):
            result = _get_timeline_items_locked(allow_cached=allow_cached)
        _library_state.update({"source": "api"})
    return _explain_disconnection(result)


def poll_timeline_items() -> dict[str, Any]:
    """get_timeline_items() with the poll cache armed — the WATCHER'S entry
    point and nobody else's.

    Kept as its own named function rather than a default: `allow_cached` must
    never be reachable by accident from tray → Scan whole project or the
    fixer, which act on what they are shown and must therefore always see the
    live timeline.
    """
    return get_timeline_items(allow_cached=True)


# -- the watcher's poll cache ----------------------------------------------
#
# The other half of the GIL-blackout fix above: most polls have nothing to
# find. The editor is watching a cut back, not re-editing it, and three
# seconds later the timeline is the same timeline with the same clips on it.
# So the sweep first gathers a CHEAP fingerprint -- timeline name + unique id
# + one GetItemListInTrack per track, a handful of calls rather than four per
# clip -- and skips the per-clip walk entirely when it matches.
#
# SAFETY VALVE: a full walk at least every _FULL_WALK_EVERY_POLLS polls (~30 s
# at the default 3 s interval). A relink (or any other in-place File Path
# change) alters no name and no count, and the watcher feeds the popup fixer,
# which must not go blind to it.
#
# The LIBRARY walk uses the same cache and the same safety valve, with a
# fingerprint it can gather without touching a clip at all: project name,
# timeline name, timeline uid, and a counter bumped every time
# ProjectLibrary.changed() says the library has moved (library walk,
# 2026-08-26). A relink that alters no name and no count moves DbSavedTime,
# so the library sees the change the API walk needed the safety valve for --
# the valve stays anyway, because a fingerprint is a claim and the walk is
# the evidence.
#
# State below has a lock of its own rather than riding on _API_LOCK: the
# library walk reaches it with _API_LOCK deliberately released, and taking
# that lock just to read three module globals would put the watcher back
# behind whatever native call is in flight.
_TIMELINE_CACHE_LOCK = threading.Lock()
_FULL_WALK_EVERY_POLLS = 10

_timeline_cache_fingerprint: Optional[tuple] = None
_timeline_cache_result: Optional[dict[str, Any]] = None
_polls_since_full_walk = 0


def reset_timeline_cache() -> None:
    """Forget the last poll — for tests only; the companion polls one
    timeline for its whole life and never calls this."""
    global _timeline_cache_fingerprint, _timeline_cache_result, _polls_since_full_walk
    with _TIMELINE_CACHE_LOCK:
        _timeline_cache_fingerprint = None
        _timeline_cache_result = None
        _polls_since_full_walk = 0


def _cached_timeline_result(fingerprint: tuple) -> Optional[dict[str, Any]]:
    """The previous poll's answer if this poll is provably the same one, else
    None meaning "walk it properly"."""
    global _polls_since_full_walk
    with _TIMELINE_CACHE_LOCK:
        if _timeline_cache_result is None or fingerprint != _timeline_cache_fingerprint:
            return None
        if _polls_since_full_walk >= _FULL_WALK_EVERY_POLLS - 1:
            return None  # safety valve: walk it anyway
        _polls_since_full_walk += 1
        # A fresh outer dict and list: the watcher and the fixer own what they
        # are handed, and a caller appending to `items` must not edit the cache.
        return {**_timeline_cache_result, "items": list(_timeline_cache_result["items"])}


def _remember_timeline_result(fingerprint: tuple, result: dict[str, Any]) -> None:
    global _timeline_cache_fingerprint, _timeline_cache_result, _polls_since_full_walk
    with _TIMELINE_CACHE_LOCK:
        _timeline_cache_fingerprint = fingerprint
        _timeline_cache_result = {**result, "items": list(result.get("items") or [])}
        _polls_since_full_walk = 0


def _timeline_head_locked() -> tuple[Optional[dict[str, Any]], Any, str, str, str]:
    """(error result, resolve, project name, timeline name, timeline uid).

    The FOUR cheap calls a library walk needs from Resolve -- the project,
    its name, the current timeline, its name and uid. Nothing per track and
    nothing per clip; the library supplies all of that. Caller holds
    _API_LOCK and must release it before reading the library.
    """
    error, resolve, project, project_name = _current_project_locked()
    if error is not None:
        return (error, None, "", "", "")
    try:
        timeline = project.GetCurrentTimeline()
    except Exception:
        timeline = None
    if timeline is None:
        return ({"ok": False, "message": "no timeline open in Resolve", "items": [],
                 "project_name": project_name}, resolve, project_name, "", "")
    return (None, resolve, project_name,
            _safe_attr_str(timeline, "GetName"),
            _safe_attr_str(timeline, "GetUniqueId"))


def _library_timeline_items(allow_cached: bool = False) -> Optional[dict[str, Any]]:
    """The open timeline's items out of the project library, or None.

    None means "the API walk, please" -- the walk is switched off, no
    library could be located, the one we had stopped answering, or there is
    no project/timeline/Resolve to name one. That last case falls THROUGH
    rather than returning the error itself, so the exact dict callers have
    always been handed for it keeps coming from one place.

    The database read happens with _API_LOCK RELEASED, which is the entire
    point of this module's half of the library walk: the read has a 5 s
    statement timeout, and 5 s of _API_LOCK is 5 s of frozen tray menu and
    five seconds of every other scripting client on the machine queueing.
    """
    global _library_generation
    if not _library_attempt_due():
        return None
    with _LIBRARY_LOCK:
        with _bridge_call("get_timeline_items"):
            error, resolve, project_name, timeline_name, timeline_uid = \
                _timeline_head_locked()
        if error is not None:
            return None
        if not timeline_uid:
            # No uid, no way to find the sequence. An old API build; the
            # walk below cannot be scoped, so the API keeps this one.
            #
            # Backed off like any other failure: this is a property of the
            # BUILD, so it will be true again in 3 s and again 3 s after
            # that, and saying it every poll was a fallback note per poll
            # with nothing armed to stop it (library walk review 2,
            # 2026-08-26).
            if time.monotonic() >= _library_next_attempt:
                _note_library_fallback(
                    "this Resolve build's timeline has no unique id")
            _arm_library_retry(_LIBRARY_RETRY_SECONDS)
            return None

        project_library = _project_library(resolve, project_name)
        if project_library is None:
            return None

        started = time.monotonic()
        try:
            stale = _library_answers_are_stale()
            if project_library.changed() or stale:
                _library_generation += 1
            if stale:
                _drop_library_path_cache(project_library)
            fingerprint = ("library", project_name, timeline_name, timeline_uid,
                           _library_generation)
            if allow_cached:
                cached = _cached_timeline_result(fingerprint)
                if cached is not None:
                    return cached
            walked = project_library.timeline_items(timeline_uid)
        except library.LibraryUnavailable as exc:
            _library_failed(exc)
            return None
        except Exception as exc:                 # pragma: no cover - defensive
            _library_failed(exc)
            return None

        # Same rule as the API walk ("no File Path -> skipped"), and it does
        # most of the work here: on Civil Defence - E1 the library returns
        # ~994 items of which ~44 carry a path, because every REPEAT cut of a
        # multicam comes back as the multicam itself -- uid of the container,
        # no path, angles already emitted at its first appearance. Letting
        # those through would hand the watcher 950 pathless "clips" to
        # classify, and classify_path("") is not a question anyone asked.
        items = [item for item in walked if str(item.get("file_path") or "").strip()]
        _library_read_done()
        elapsed_ms = (time.monotonic() - started) * 1000.0
        _library_state.update({"source": "library", "error": "",
                               "walk_ms": round(elapsed_ms, 1)})
        log.debug("resolve: library walk of %r found %d items, %d with a path, in %.1f ms",
                  timeline_name, len(walked), len(items), elapsed_ms)
        result = {"ok": True, "message": "", "items": items,
                  "project_name": project_name}
        _remember_timeline_result(fingerprint, result)
        return result


def _timeline_tracks(timeline) -> list[tuple[str, int, list]]:
    """(track_type, track_index, items) for every track, in sweep order.

    One GetItemListInTrack per track -- the calls the sweep would make
    anyway, gathered once so the fingerprint below and the per-clip walk
    share them.
    """
    tracks: list[tuple[str, int, list]] = []
    for track_type in ("video", "audio"):
        try:
            track_count = timeline.GetTrackCount(track_type) or 0
        except Exception:
            track_count = 0
        for track_index in range(1, track_count + 1):
            try:
                track_items = timeline.GetItemListInTrack(track_type, track_index) or []
            except Exception:
                track_items = []
            tracks.append((track_type, track_index, track_items))
    return tracks


def _timeline_fingerprint(
    project_name: str, timeline, tracks: list[tuple[str, int, list]]
) -> tuple:
    """What has to change before the per-clip walk is worth paying for."""
    return (
        project_name,
        _safe_attr_str(timeline, "GetName"),
        _safe_attr_str(timeline, "GetUniqueId"),
        tuple((track_type, track_index, len(items)) for track_type, track_index, items in tracks),
    )


def _get_timeline_items_locked(allow_cached: bool = False) -> dict[str, Any]:
    resolve = connect()
    if resolve is None:
        return {"ok": False, "message": _NOT_CONNECTED, "items": [], "project_name": ""}

    try:
        project_manager = resolve.GetProjectManager()
        project = project_manager.GetCurrentProject() if project_manager else None
    except Exception:
        project = None
    if project is None:
        return {"ok": False, "message": "no project open in Resolve", "items": [], "project_name": ""}

    project_name = _safe_project_name(project)

    try:
        timeline = project.GetCurrentTimeline()
    except Exception:
        timeline = None
    if timeline is None:
        return {"ok": False, "message": "no timeline open in Resolve", "items": [], "project_name": project_name}

    items: list[dict[str, Any]] = []
    swept = [0]
    try:
        tracks = _timeline_tracks(timeline)
        fingerprint = _timeline_fingerprint(project_name, timeline, tracks)
        if allow_cached:
            cached = _cached_timeline_result(fingerprint)
            if cached is not None:
                return cached
        for track_type, track_index, track_items in tracks:
            for item_index, timeline_item in enumerate(track_items):
                _sweep_yield(swept)
                try:
                    media_pool_item = timeline_item.GetMediaPoolItem()
                except Exception:
                    media_pool_item = None
                if media_pool_item is None:
                    continue  # generator/title/adjustment clip — no source file
                # One-arg, not the whole property dict: 0.1 ms against 12.5
                # ms per clip, same string on all 1,298 clips of the open
                # project (library walk, 2026-08-26). On a timeline the
                # library cannot be read for, this alone takes the walk from
                # 11 s to under 1 s.
                file_path = _clip_property(media_pool_item, "File Path")
                if not file_path:
                    continue
                items.append(
                    {
                        "file_path": file_path,
                        "media_pool_item": media_pool_item,
                        # The uid is what survives a walk that carried no
                        # objects (library walk, 2026-08-26): the project
                        # library's Sm2MpMedia_id IS
                        # MediaPoolItem.GetUniqueId(), so every consumer can
                        # re-find the live object through
                        # media_pool_item_by_uid() when it has to act. "" on
                        # an API build without GetUniqueId -- such a build
                        # simply never gets the library walk.
                        "media_pool_uid": _safe_attr_str(media_pool_item, "GetUniqueId"),
                        "source": "api",
                        # Only the library walk can see INSIDE a multicam or
                        # compound clip; the API reports the container, so
                        # nothing here was reached through one.
                        "via_multicam": None,
                        "clip_name": _safe_clip_name(media_pool_item),
                        "track_type": track_type,
                        "track_index": track_index,
                        "item_index": item_index,
                    }
                )
    except Exception as exc:
        log.warning("resolve: timeline enumeration failed: %s", exc, exc_info=True)
        return {"ok": False, "message": _SCRIPTING_ERROR_MESSAGE, "items": [],
                "project_name": project_name}

    _log_darwin_clip_path_flavor(items)
    result = {"ok": True, "message": "", "items": items, "project_name": project_name}
    _remember_timeline_result(fingerprint, result)
    return result


# One-shot, first successful poll of the process only.
_darwin_path_flavor_logged = False


def _log_darwin_clip_path_flavor(items: list[dict[str, Any]]) -> None:
    """Record ONCE, on macOS, which spelling Resolve hands back for clips.

    Open hardware question: the fleet's project databases store canonical
    `P:\\Projects\\...` strings, and a Mac reaches them through Resolve's
    Mapped Mount preference. Whether GetClipProperty then reports the stored
    canonical string or the mount-resolved local path decides what
    classification, the fixer and the proxy relinker are actually looking at
    -- and it can only be answered on real hardware. One INFO line in the
    editor's log answers it without asking anyone to run anything.
    """
    global _darwin_path_flavor_logged
    if _darwin_path_flavor_logged or sys.platform != "darwin" or not items:
        return
    _darwin_path_flavor_logged = True
    try:
        paths = [str(item.get("file_path") or "") for item in items]
        # Drive-rooted ("P:\...") is the canonical spelling; anything else on
        # a Mac is the Mapped Mount already resolved to a local path.
        canonical = [p for p in paths if p[1:2] == ":"]
        log.info(
            "resolve (macOS): %d of %d timeline clip paths came back in canonical "
            "drive spelling; first canonical=%r first other=%r",
            len(canonical), len(paths),
            canonical[0] if canonical else "",
            next((p for p in paths if p[1:2] != ":"), ""),
        )
    except Exception:
        log.debug("resolve: could not sample the macOS clip path flavor", exc_info=True)


# Editor-facing. The raw f"Resolve scripting error: {exc}" reached tray
# toasts and the fixer dialog verbatim, where it means nothing to anyone and
# suggests no action (AUDIT_2 UX-16). The exception itself is logged.
_SCRIPTING_ERROR_MESSAGE = "Resolve didn't answer. Make sure a project is open, then try again."


# Defensive cap on media pool folder recursion depth: a real Resolve
# project tree is never anywhere near this deep, but a malformed/circular
# folder graph (or a test double) must not hang the watcher/tray thread.
_MAX_MEDIA_POOL_DEPTH = 64


def _walk_media_pool_folder(
    folder, project_name: str, items: list[dict[str, Any]], depth: int = 0, bin_path: str = "",
    swept: Optional[list[int]] = None,
) -> None:
    """Recurse the media pool, tagging every clip with its bin path.

    `bin_path` is the "/"-joined chain of folder names BELOW the root
    folder (the root itself is excluded) -- root-level clips get "", a
    clip one bin deep gets e.g. "Interviews", two deep "Master/Interviews".

    `swept` is the shared clip counter behind _sweep_yield -- one per walk,
    threaded through the recursion so the GIL is handed back every
    _SWEEP_YIELD_EVERY clips across the whole tree, not per bin.
    """
    if depth > _MAX_MEDIA_POOL_DEPTH:
        return
    if swept is None:
        swept = [0]

    try:
        clips = folder.GetClipList() or []
    except Exception:
        clips = []
    for clip in clips:
        _sweep_yield(swept)
        # Three one-arg reads rather than one whole-dict read: measured 0.3 ms
        # against 12.5 ms per clip (library walk, 2026-08-26).
        file_path = _clip_property(clip, "File Path")
        if not file_path:
            continue  # timelines, compound clips, generators have no File Path
        items.append(
            {
                "file_path": file_path,
                "media_pool_item": clip,
                # See the timeline walk's note (library walk, 2026-08-26):
                # the uid is the handle a walk with no objects hands on.
                "media_pool_uid": _safe_attr_str(clip, "GetUniqueId"),
                "source": "api",
                "clip_name": _safe_clip_name(clip),
                "resolve_project_name": project_name,
                "bin_path": bin_path,
                # The clip's SECOND path. Independent of "File Path" and not
                # shown by Reveal in Folder, so a clip can look correctly
                # linked while its proxy points at a drive that has never
                # existed here -- see proxy_relink.py.
                "proxy_path": _clip_property(clip, "Proxy Media Path"),
                # "1920x1080" when the proxy resolves, "Offline" when
                # attached but unreachable, "None" when there is none.
                "proxy_state": _clip_property(clip, "Proxy"),
            }
        )

    try:
        subfolders = folder.GetSubFolderList() or []
    except Exception:
        subfolders = []
    for subfolder in subfolders:
        subfolder_name = _safe_folder_name(subfolder)
        child_bin_path = f"{bin_path}/{subfolder_name}" if bin_path else subfolder_name
        _walk_media_pool_folder(
            subfolder, project_name, items, depth + 1, child_bin_path, swept
        )


def get_media_pool_items() -> dict[str, Any]:
    """Enumerate every media pool item (clip) anywhere in the current
    project's media pool, recursively walking every bin — unlike
    get_timeline_items, this finds media imported but never cut onto a
    timeline.

    Returns {"ok": bool, "message": str, "items": [...], "project_name": str}.
    Never raises.

    Each item dict: {
        "file_path": str,               # GetClipProperty()["File Path"]
        "media_pool_item": <object>,    # None from a walk that had no objects
        "media_pool_uid": str,          # MediaPoolItem.GetUniqueId(), "" if unavailable
        "source": "api" | "library",
        "clip_name": str,
        "resolve_project_name": str,    # the current project's GetName()
    }

    NEVER read "media_pool_item" to act on a clip -- call
    resolve_media_pool_item(item) (library walk, 2026-08-26).

    Unlike get_timeline_items (where the watcher attaches
    "resolve_project_name" itself), this function includes it directly on
    every item, since there's no separate watcher layer in between here and
    the popup/fixer for a manual whole-project scan (see app.scan_whole_project).

    Items with no media pool item, or an empty "File Path" (timelines,
    compound clips, generators, titles), are skipped entirely — same rule as
    get_timeline_items.
    """
    ui_state.wait_while_menu_open()  # same GIL courtesy as get_timeline_items
    result = _library_media_pool_items()
    if result is None:
        with _bridge_call("get_media_pool_items"):
            result = _get_media_pool_items_locked()
        _library_state.update({"source": "api"})
    return _explain_disconnection(result)


def _library_media_pool_items() -> Optional[dict[str, Any]]:
    """Every clip in the project's bins, out of the project library, or None.

    Same contract as _library_timeline_items: None means "the API walk", and
    the database read happens with _API_LOCK released.
    """
    if not _library_attempt_due():
        return None
    result = _library_pool_read()
    if result is None:
        return None
    # Enrichment asks RESOLVE about clips, and touches no library object at
    # all, so it runs with _LIBRARY_LOCK RELEASED: holding it for the whole
    # 5 s run parked the watcher's _library_attempt_due(), library_status()
    # and configure_library() behind a walk -- including the wedge warning
    # whose entire job is to fire while a walk is stuck (library walk review
    # 2, 2026-08-26).
    #
    # A PARTIAL enrichment is not an answer: an item left at proxy_state ""
    # reads as "no proxy" to proxy_relink, which then plans a relink for
    # every clip in the pool. Half a pool walk goes back as None and the API
    # walk answers instead.
    if not _enrich_proxy_keys(result["items"]):
        return None
    return result


def _library_pool_read() -> Optional[dict[str, Any]]:
    """The library half of _library_media_pool_items -- everything that
    needs _LIBRARY_LOCK, and nothing that does not."""
    with _LIBRARY_LOCK:
        with _bridge_call("get_media_pool_items"):
            error, resolve, _project, project_name = _current_project_locked()
        if error is not None:
            return None

        project_library = _project_library(resolve, project_name)
        if project_library is None:
            return None

        started = time.monotonic()
        try:
            # Not gated on changed(): unlike the timeline this is asked for
            # every 120 s at most (the media-tree refresh) or by an editor
            # who just pressed a button, and both want the truth now.
            project_library.changed()
            if _library_answers_are_stale():
                _drop_library_path_cache(project_library)
            walked = project_library.pool_items()
        except library.LibraryUnavailable as exc:
            _library_failed(exc)
            return None
        except Exception as exc:                 # pragma: no cover - defensive
            _library_failed(exc)
            return None

        items = [item for item in walked if str(item.get("file_path") or "").strip()]
        _library_read_done()
        elapsed_ms = (time.monotonic() - started) * 1000.0
        _library_state.update({"source": "library", "error": "",
                               "walk_ms": round(elapsed_ms, 1)})
        log.debug("resolve: library pool walk of %r found %d clips, %d with a path, "
                  "in %.1f ms", project_name, len(walked), len(items), elapsed_ms)
        return {"ok": True, "message": "", "items": items,
                "project_name": project_name}


def _enrich_proxy_keys(items: list[dict[str, Any]]) -> bool:
    """Fill in proxy_path / proxy_state on library items, from the API.

    True when the answer can be handed out: every item enriched, or nothing
    on this machine reads these keys. FALSE means the run stopped part way
    and the caller must throw the whole list away -- see below.

    The library cannot give these cheaply (see ProjectLibrary.pool_items:
    BtVideoInfo.Proxy is a stub with no path and no state, and the real
    proxy path sits behind a SECOND nested zstd frame inside FieldsBlob).
    So they come from Resolve -- but ONLY where something is going to read
    them.

    Two things read them, not one: proxy generation (proxy_gen_enabled) and
    the PROXY RELINK pass (app._relink_proxies_once, proxy_relink_enabled,
    default True). Gating on generation alone left every lane-B editor rig
    -- where proxy_gen_enabled derives False and lane B syncs the proxies
    down -- reporting proxy_state "" for all 1,298 clips, which
    proxy_relink reads as "no proxy is linked" and answers with ~1,300
    LinkProxyMedia calls against a pool that was already right. The API walk
    always read these properties, so anything less is a regression (library
    walk review 2, 2026-08-26).

    One folder walk for the whole list, not one lookup per clip: the uid map
    the fixer already builds (media_pool_item_by_uid) is exactly the map
    needed here, so the two share it and the TTL cache means a refresh that
    follows a FIX ALL pays for neither.
    """
    if not items:
        return True
    try:
        from . import config as config_mod

        cfg = _config_without_creating()
        wanted = (config_mod.proxy_generation_enabled(cfg)
                  or bool(cfg.get("proxy_relink_enabled",
                                  config_mod.DEFAULTS["proxy_relink_enabled"])))
        if not wanted:
            return True
    except Exception:
        log.debug("resolve: could not decide whether to enrich proxy keys",
                  exc_info=True)
        return True

    # In CHUNKS, each taking _API_LOCK for itself. Two property reads over
    # 1,298 clips measured 5.5 s on the base rig -- better than the 9.4 s the
    # whole API pool walk used to take, but still 5.5 s in which nothing else
    # on the machine can talk to Resolve if it is one hold. Letting go
    # between chunks means a card click in Timeline Cards waits for a chunk,
    # not for the walk (library walk, 2026-08-26).
    swept = [0]
    for start in range(0, len(items), _PROXY_ENRICH_CHUNK):
        chunk = items[start:start + _PROXY_ENRICH_CHUNK]
        with _bridge_call("get_media_pool_items"):
            _error, _resolve, project, project_name = _current_project_locked()
            if project is None:
                # Mid-list: the project closed, or the pool cannot be walked
                # any more. The chunks already done are enriched and the rest
                # are still "", and a half-enriched list is WORSE than none
                # -- "" means "no proxy" to every reader. Say so and let the
                # caller fall back (library walk review 2, 2026-08-26).
                log.debug("resolve: proxy enrichment stopped after %d of %d "
                          "clips (no project)", start, len(items))
                return False
            found = _media_pool_uid_map_locked(project, project_name)
            if not found:
                log.debug("resolve: proxy enrichment stopped after %d of %d "
                          "clips (empty uid map)", start, len(items))
                return False
            for item in chunk:
                clip = found.get(str(item.get("media_pool_uid") or ""))
                if clip is None:
                    continue
                _sweep_yield(swept)
                item["proxy_path"] = _clip_property(clip, "Proxy Media Path")
                item["proxy_state"] = _clip_property(clip, "Proxy")
    return True


def _get_media_pool_items_locked() -> dict[str, Any]:
    resolve = connect()
    if resolve is None:
        return {"ok": False, "message": _NOT_CONNECTED, "items": [], "project_name": ""}

    try:
        project_manager = resolve.GetProjectManager()
        project = project_manager.GetCurrentProject() if project_manager else None
    except Exception:
        project = None
    if project is None:
        return {"ok": False, "message": "no project open in Resolve", "items": [], "project_name": ""}

    project_name = _safe_project_name(project)

    try:
        media_pool = project.GetMediaPool()
    except Exception:
        media_pool = None
    if media_pool is None:
        return {"ok": False, "message": "no media pool available", "items": [], "project_name": project_name}

    try:
        root_folder = media_pool.GetRootFolder()
    except Exception:
        root_folder = None
    if root_folder is None:
        return {"ok": False, "message": "no root folder in media pool", "items": [], "project_name": project_name}

    items: list[dict[str, Any]] = []
    try:
        _walk_media_pool_folder(root_folder, project_name, items)
    except Exception as exc:
        log.warning("resolve: media pool walk failed: %s", exc, exc_info=True)
        return {"ok": False, "message": _SCRIPTING_ERROR_MESSAGE, "items": [],
                "project_name": project_name}

    return {"ok": True, "message": "", "items": items, "project_name": project_name}


# -- uid -> live MediaPoolItem (library walk, 2026-08-26) ------------------
#
# The project-library walk reads clips out of PostgreSQL/SQLite and so has no
# fusionscript objects to hand back -- only Sm2MpMedia_id, which IS
# MediaPoolItem.GetUniqueId(). Anything that must ACT on a clip (ReplaceClip,
# LinkProxyMedia, GetName) still needs the object, so it is re-found here, on
# demand: GetClipList per folder + GetUniqueId per clip, ~0.15 s for 1,318
# clips. That only ever runs when there is something to fix, unlike the walk
# it replaces, which ran every poll.
#
# Cached for _MEDIA_POOL_UID_TTL_SECONDS and keyed by project name AND by the
# live project OBJECT, so a FIX ALL over 50 clips pays for one walk, not 50. A
# MISS is cached too (as the freshness of the map, not as an entry): an unknown
# uid must not re-walk the pool once per clip when a stale library row names a
# clip that has since been deleted.
#
# The identity check is what makes the name safe to key on. Close a project and
# reopen it inside the TTL -- an editor bouncing a project to clear a Resolve
# glitch does exactly that -- and the name matches while every MediaPoolItem in
# the map is a dead fusionscript pointer; handing one to ReplaceClip is the
# 0xc0000005 this module's header warns about (library walk review 2,
# 2026-08-26). A reopened project is a NEW object, so `is` catches it and the
# only cost is one pool walk that was going to be needed anyway.
#
# Every global below is read and written ONLY under _API_LOCK (inside the
# _bridge_call in media_pool_item_by_uid), which is why they carry no lock of
# their own.
_MEDIA_POOL_UID_TTL_SECONDS = 60.0

# How many clips one hold of _API_LOCK enriches with proxy keys. Small
# enough that another client never waits long, large enough that the four
# cheap calls per chunk stay noise (library walk, 2026-08-26).
_PROXY_ENRICH_CHUNK = 100

_uid_cache: dict[str, Any] = {}
_uid_cache_project = ""
_uid_cache_project_object: Any = None
_uid_cache_stamp = 0.0


def _reset_media_pool_uid_cache() -> None:
    """Forget the uid map (tests, and anything that knows the pool changed)."""
    global _uid_cache, _uid_cache_project, _uid_cache_stamp
    global _uid_cache_project_object
    _uid_cache = {}
    _uid_cache_project = ""
    _uid_cache_project_object = None
    _uid_cache_stamp = 0.0


def _walk_media_pool_uids(folder, found: dict[str, Any], depth: int = 0,
                          swept: Optional[list[int]] = None) -> None:
    """Recurse the pool collecting uid -> clip. Same shape (and same
    depth cap, same _sweep_yield courtesy) as _walk_media_pool_folder, but
    it reads GetUniqueId instead of the far more expensive GetClipProperty."""
    if depth > _MAX_MEDIA_POOL_DEPTH:
        return
    if swept is None:
        swept = [0]
    try:
        clips = folder.GetClipList() or []
    except Exception:
        clips = []
    for clip in clips:
        _sweep_yield(swept)
        uid = _safe_attr_str(clip, "GetUniqueId")
        if uid and uid not in found:
            found[uid] = clip
    try:
        subfolders = folder.GetSubFolderList() or []
    except Exception:
        subfolders = []
    for subfolder in subfolders:
        _walk_media_pool_uids(subfolder, found, depth + 1, swept)


def _media_pool_uid_map_locked(project, project_name: str) -> dict[str, Any]:
    """uid -> live MediaPoolItem for the open project. Caller holds _API_LOCK.

    ONE walk shared by everything that needs to turn a library uid back into
    an object -- media_pool_item_by_uid below and the pool walk's proxy
    enrichment above -- so a refresh and the FIX ALL that follows it pay for
    a single GetClipList sweep between them.

    Empty dict means "could not walk it"; that answer is deliberately NOT
    cached, unlike a walk that found nothing.
    """
    global _uid_cache, _uid_cache_project, _uid_cache_stamp
    global _uid_cache_project_object
    now = time.monotonic()
    if (project_name == _uid_cache_project
            and project is _uid_cache_project_object
            and (now - _uid_cache_stamp) < _MEDIA_POOL_UID_TTL_SECONDS):
        return _uid_cache
    try:
        media_pool = project.GetMediaPool()
        root_folder = media_pool.GetRootFolder() if media_pool is not None else None
    except Exception:
        root_folder = None
    if root_folder is None:
        return {}
    found: dict[str, Any] = {}
    _walk_media_pool_uids(root_folder, found)
    _uid_cache = found
    _uid_cache_project = project_name
    _uid_cache_project_object = project
    _uid_cache_stamp = now
    return found


def media_pool_item_by_uid(uid: str):
    """The live MediaPoolItem with this GetUniqueId(), or None. Never raises.

    None means "not findable right now" -- no Resolve, no project, a uid from
    another project, or a clip that has been removed from the pool. Every
    caller must treat it as "skip this clip", never as "nothing to do".
    """
    if not uid:
        return None
    ui_state.wait_while_menu_open()  # same GIL courtesy as the enumerators
    with _bridge_call("media_pool_item_by_uid"):
        try:
            _error, _resolve, project, project_name = _current_project_locked()
            if project is None:
                return None
            # A MISS from a fresh map is an answer: the map was built less
            # than a TTL ago, so a uid that is not in it is not in the pool.
            return _media_pool_uid_map_locked(project, project_name).get(uid)
        except Exception:
            log.debug("resolve: uid lookup for %r failed", uid, exc_info=True)
            return None


def _is_item_dict(value) -> bool:
    """Is this one of this module's item dicts, or an opaque MediaPoolItem?

    ANY dict is an item dict. A real MediaPoolItem is a fusionscript object
    and is never a dict, so the test needs nothing else -- and keying off
    "does it carry media_pool_uid or media_pool_item" was actively wrong: a
    bare `{}` failed it, was therefore taken for a MediaPoolItem, and came
    back out of resolve_media_pool_item() as itself, on its way to
    ReplaceClip (wave-1 review, 2026-08-26). An item dict missing both keys
    is a dict with no clip in it, which is exactly the None case.
    """
    return isinstance(value, dict)


def resolve_media_pool_item(item):
    """THE accessor for the object behind an item dict. None when there is none.

    `item` is a get_timeline_items/get_media_pool_items dict (or any dict
    carrying "media_pool_item"/"media_pool_uid" -- a proxy-relink op, a popup
    row). A bare MediaPoolItem is passed straight back, so batches that
    collected objects before this existed keep working unchanged.

    The resolved object is deliberately NOT written back onto the dict.
    Item dicts outlive the objects in them: popup._relink_entry keeps the
    watcher's own dicts while a dialog is open and _canon_relink_pending can
    hold them for hours, so a cached handle would survive a project close and
    reopen and hand a DEAD fusionscript object to ReplaceClip (wave-1 review,
    2026-08-26). Repeat lookups are already free -- the uid map behind
    media_pool_item_by_uid is one walk per project per
    _MEDIA_POOL_UID_TTL_SECONDS -- and that map is the thing that knows when
    the project changed.
    """
    if item is None:
        return None
    if not _is_item_dict(item):
        return item  # already the object (legacy batch entry / test double)
    media_pool_item = item.get("media_pool_item")
    if media_pool_item is not None:
        return media_pool_item
    return media_pool_item_by_uid(str(item.get("media_pool_uid") or ""))


def media_pool_item_is_reachable(item) -> bool:
    """Could resolve_media_pool_item(item) plausibly find an object?

    A pure, call-free predicate for FILTERS -- "has an object, or has a uid to
    look one up with". The filters that used `is not None` would drop every
    item a library walk produced before anything had a chance to look it up
    (library walk, 2026-08-26).
    """
    if item is None:
        return False
    if not _is_item_dict(item):
        return True
    return (item.get("media_pool_item") is not None
            or bool(str(item.get("media_pool_uid") or "")))


# -- save point + undo journal (COMMERCIAL_READINESS.md item 9, 2026-08-17) --
#
# Every media-pool MUTATION in this module goes through _before_mutation()
# first. Putting it here rather than at the four call sites is deliberate:
# fixer.py, app.py's two automatic passes, music_worker and
# _canonicalize_imported all reach Resolve through replace_clip /
# link_proxy_media, so one hook covers paths that have not been written yet.
# See resolve_journal.py for what is written and why.

# How long a cached project name is trusted. The name is read for the journal
# on every edit and a media-pool walk already costs a fusionscript call; the
# window only has to be shorter than the time it takes a human to switch
# projects.
_PROJECT_NAME_TTL_SECONDS = 20.0

_project_name_cache: Optional[tuple[str, float]] = None


def current_project_name(max_age: float = _PROJECT_NAME_TTL_SECONDS) -> str:
    """The open project's name, "" when there is none. Cached for `max_age`."""
    global _project_name_cache
    cached = _project_name_cache
    now = time.monotonic()
    if cached is not None and (now - cached[1]) < max_age:
        return cached[0]
    name = ""
    try:
        with _bridge_call("current_project_name"):
            resolve = connect()
            if resolve is not None:
                project = resolve.GetProjectManager().GetCurrentProject()
                if project is not None:
                    name = _safe_project_name(project)
    except Exception:
        log.debug("resolve: could not read the current project name", exc_info=True)
    _project_name_cache = (name, now)
    return name


def save_project(project_name: str = "") -> dict[str, Any]:
    """`SaveProject()` + `ExportProject()` into ~/.ccsync/resolve_edits.

    BEST EFFORT, both halves. `ProjectManager.SaveProject` is the documented
    spelling but some builds only carry `Project.SaveProject`; `ExportProject`
    is missing entirely from older API builds and is refused outright for a
    project open in a collaboration. Neither may stop the relink that
    follows -- an editor staring at Media Offline is a worse outcome than an
    un-exported project -- so this reports what it managed and never raises.
    """
    result: dict[str, Any] = {"saved": False, "backup": "", "message": ""}
    try:
        with _bridge_call("save_project"):
            resolve = connect()
            if resolve is None:
                result["message"] = "Resolve is not running"
                return result
            manager = resolve.GetProjectManager()
            project = manager.GetCurrentProject()
            if project is None:
                result["message"] = "no project open"
                return result
            name = project_name or _safe_project_name(project)
            for owner in (manager, project):
                saver = getattr(owner, "SaveProject", None)
                if saver is None:
                    continue
                try:
                    saver()
                    result["saved"] = True
                    break
                except Exception:
                    log.debug("resolve: SaveProject via %r failed", owner, exc_info=True)
            exporter = getattr(manager, "ExportProject", None)
            if exporter is None:
                result["message"] = "this Resolve build cannot export projects"
                return result
            slug = resolve_journal.project_slug(name)
            directory = resolve_journal.journal_root() / slug
            stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
            target = directory / f"{stamp}.drp"
            try:
                directory.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                result["message"] = f"could not make {directory} ({exc})"
                return result
            try:
                # withStillsAndLUTs=False: this is a rollback copy of the
                # project DATABASE, not an archive. Stills and LUTs turn
                # seconds into minutes and are not what a bad relink lost.
                ok = exporter(name, str(target), False)
            except Exception as exc:
                result["message"] = f"ExportProject refused ({exc})"
                return result
            if ok and target.exists():
                result["backup"] = str(target)
            else:
                result["message"] = (
                    "Resolve refused to export a backup copy (a project open in a "
                    "collaboration cannot be exported)"
                )
    except Exception as exc:
        result["message"] = f"could not take a save point ({exc})"
        log.debug("resolve: save point failed", exc_info=True)
    return result


def _before_mutation(source: str) -> str:
    """Take a save point if one is due, and return the project name to
    journal against. Never raises: see save_project()."""
    try:
        name = current_project_name()
        if resolve_journal.save_point_due(name):
            outcome = save_project(name)
            resolve_journal.note_save_point(
                name, saved=bool(outcome.get("saved")),
                backup=str(outcome.get("backup") or ""),
            )
            if outcome.get("backup"):
                log.info("resolve: saved %r and exported a rollback copy to %s "
                         "before the %s pass", name or "the project",
                         outcome["backup"], source)
            else:
                log.warning(
                    "resolve: no rollback copy before the %s pass -- %s. The undo "
                    "journal under ~/.ccsync/%s is the fallback",
                    source, outcome.get("message") or "export unavailable",
                    resolve_journal.JOURNAL_DIRNAME,
                )
        return name
    except Exception:
        log.debug("resolve: could not take a save point", exc_info=True)
        return ""


def replace_clip(media_pool_item, new_path: str, tries: int = 3, *,
                 source: str = "manual", journal: bool = True) -> dict[str, Any]:
    """Relink `media_pool_item` to `new_path` via ReplaceClip.

    This preserves every timeline usage of the clip (per SPEC.md's fixer
    spec) rather than re-importing + re-editing. Returns
    {"ok": bool, "message": str}. Never raises.

    ReplaceClip's return value is unreliable: Resolve returns None even when
    the relink SUCCEEDED, and also returns None while momentarily busy (a
    large project can spend seconds updating every timeline that references
    the clip). Treating a falsy return as failure misreported every success
    and made retry loops storm. The truth signal is the clip's File Path
    actually changing -- re-read it, and retry (briefly, off-lock) through
    transient stalls. Same battle-tested pattern as resolve-relink's
    relink_one().
    """
    if media_pool_item is None:
        return {"ok": False, "message": "no media pool item to relink"}

    def _file_path_locked() -> Optional[str]:
        # No-arg form (full property dict), same as the import dedupe loop --
        # the one-arg form is not implemented by every API build.
        try:
            props = media_pool_item.GetClipProperty() or {}
            return props.get("File Path")
        except Exception:
            return None

    norm_new = _norm_path(new_path)
    ui_state.wait_while_menu_open()  # same GIL courtesy as the enumerators
    with _bridge_call("replace_clip (read)"):
        before = _file_path_locked()
    if before is not None and _norm_path(before) == norm_new:
        return {"ok": True, "message": f"Already linked to {new_path}"}

    # Save point BEFORE the first ReplaceClip of the burst, journal entry
    # after it takes -- the entry names the inverse edit, so it must not be
    # written for a swap that never happened (item 9, 2026-08-17).
    project_name = _before_mutation(source) if journal else ""

    raised = 0
    for attempt in range(max(1, tries)):
        ui_state.wait_while_menu_open()
        clip_name = ""
        with _bridge_call("replace_clip"):
            try:
                media_pool_item.ReplaceClip(new_path)
            except Exception as exc:
                raised += 1
                log.warning("resolve: ReplaceClip(%s) raised: %s", new_path, exc, exc_info=True)
            after = _file_path_locked()
            took = after is not None and _norm_path(after) == norm_new
            # GetName() UNDER THE LOCK, not at the record() call below
            # (comp-resolve-3, 2026-08-21). It is a call into
            # fusionscript.dll like any other, and the journal line
            # used to read it after the `with` had closed: the FIX ALL worker
            # calling GetName() while the watcher was mid-GetClipProperty() is
            # exactly the concurrent-native-call shape this module's header
            # says faults 0xc0000005 and takes the windowed tray down with no
            # log. The journal takes a STRING, so read it here and pass it.
            if took and journal:
                clip_name = _safe_clip_name(media_pool_item)
        if took:
            if journal:
                resolve_journal.record(
                    resolve_journal.KIND_REPLACE_CLIP, project_name,
                    clip_name=clip_name,
                    old_path=before or "", new_path=new_path, source=source,
                )
            return {"ok": True, "message": f"Relinked to {new_path}"}
        if attempt + 1 < max(1, tries):
            # Off-lock backoff: give Resolve's main thread room to finish the
            # swap (or recover) before the next attempt.
            time.sleep(1.0 * (attempt + 1))

    if raised == max(1, tries):
        # Every attempt raised -- Resolve went away, not a refusal.
        return {"ok": False, "message": _SCRIPTING_ERROR_MESSAGE}
    log.warning("resolve: ReplaceClip did not take for %s (path still %r)", new_path, before)
    return {
        "ok": False,
        "message": (
            "Copied the file in, but Resolve wouldn't relink it. Close the clip's "
            "timeline and use tray → Scan whole project again."
        ),
    }


def refresh_lut_list() -> bool:
    """Make a running Resolve re-read its LUT directory. Never raises.

    Resolve caches the LUT list at project open, so a LUT that syncs in while
    an editor is working is invisible to them until they restart Resolve or
    hit Project Settings -> Color Management -> Update Lists. This is that
    button (`Project.RefreshLUTList()`), called after the LUT library changes
    on disk.

    Returns False for every "could not" -- Resolve not running, no project
    open, an older API without the method. All of them are routine: the LUT
    is on disk either way, and Resolve picks it up at its next start.
    """
    ui_state.wait_while_menu_open()  # same GIL courtesy as the enumerators
    with _bridge_call("refresh_lut_list"):
        try:
            resolve = connect()
            if resolve is None:
                return False
            project = resolve.GetProjectManager().GetCurrentProject()
            if project is None:
                log.debug("resolve: no project open -- skipping RefreshLUTList")
                return False
            refresh = getattr(project, "RefreshLUTList", None)
            if refresh is None:
                log.debug("resolve: this API build has no RefreshLUTList")
                return False
            return bool(refresh())
        except Exception as exc:
            log.debug("resolve: RefreshLUTList failed (%s)", exc)
            return False


def link_proxy_media(media_pool_item, proxy_path: str, *,
                     source: str = "manual", journal: bool = True) -> dict[str, Any]:
    """Point `media_pool_item`'s PROXY at `proxy_path`. Never raises.

    Distinct from replace_clip: that repoints the ORIGINAL, this repoints the
    separate proxy attachment (see proxy_relink.py for why the two drift
    apart). Resolve validates the pairing itself and returns False on a
    timecode/frame-count mismatch, so a same-named but wrong file is refused
    rather than silently attached.
    """
    if media_pool_item is None:
        return {"ok": False, "message": "no media pool item to relink"}
    if not proxy_path:
        return {"ok": False, "message": "no proxy path given"}
    ui_state.wait_while_menu_open()  # same GIL courtesy as the enumerators
    project_name = _before_mutation(source) if journal else ""
    clip_name = ""
    clip_path = ""
    with _bridge_call("link_proxy_media"):
        try:
            old_proxy = _safe_clip_property(media_pool_item, "Proxy Media Path")
            result = media_pool_item.LinkProxyMedia(proxy_path)
            # The journal's clip name and original path are read HERE, inside
            # the lock, for the reason written at replace_clip's own read
            # (comp-resolve-3, 2026-08-21): GetName/GetClipProperty are calls
            # into fusionscript.dll, and this bookkeeping used to make them
            # after the `with` closed, on the proxy-relink thread, while the
            # watcher was inside its own call.
            if result and journal:
                clip_name = _safe_clip_name(media_pool_item)
                clip_path = _safe_clip_property(media_pool_item, "File Path")
        except Exception as exc:
            log.warning("resolve: LinkProxyMedia(%s) raised: %s", proxy_path, exc, exc_info=True)
            return {"ok": False, "message": _SCRIPTING_ERROR_MESSAGE}
    if not result:
        return {
            "ok": False,
            "message": f"Resolve wouldn't accept {proxy_path} as this clip's proxy",
        }
    if journal:
        resolve_journal.record(
            resolve_journal.KIND_LINK_PROXY, project_name,
            clip_name=clip_name,
            clip_path=clip_path,
            old_path=old_proxy, new_path=proxy_path, source=source,
        )
    return {"ok": True, "message": f"Proxy relinked to {proxy_path}"}


def _safe_clip_property(media_pool_item, key: str) -> str:
    """One clip property as a string, "" for anything that goes wrong.

    No-arg GetClipProperty() like the rest of this module: the one-arg form
    is not implemented by every API build (see replace_clip)."""
    try:
        props = media_pool_item.GetClipProperty() or {}
        value = props.get(key)
        return str(value) if value else ""
    except Exception:
        return ""


def unlink_proxy_media(media_pool_item) -> dict[str, Any]:
    """Detach whatever proxy is attached. Never raises.

    Exists for the UNDO path only (item 9, 2026-08-17): the inverse of
    linking a proxy to a clip that had none is detaching it again, and
    ReplaceClip cannot express that. Not journalled -- it IS the journal
    being replayed, and recording an undo as a new edit would make the next
    undo redo it.
    """
    if media_pool_item is None:
        return {"ok": False, "message": "no media pool item"}
    ui_state.wait_while_menu_open()
    with _bridge_call("unlink_proxy_media"):
        try:
            unlink = getattr(media_pool_item, "UnlinkProxyMedia", None)
            if unlink is None:
                return {"ok": False, "message": "this Resolve build cannot unlink proxies"}
            result = unlink()
        except Exception as exc:
            log.warning("resolve: UnlinkProxyMedia raised: %s", exc, exc_info=True)
            return {"ok": False, "message": _SCRIPTING_ERROR_MESSAGE}
    if not result:
        return {"ok": False, "message": "Resolve refused to unlink the proxy"}
    return {"ok": True, "message": "Proxy detached"}


def undo_last_relink(session_path: Any = None) -> dict[str, Any]:
    """Put every clip in the newest journal back where it was.

    THE ROLLBACK OF LAST RESORT (item 9, 2026-08-17). Resolve's own Undo does
    not cover a scripted ReplaceClip, and `save_project`'s exported `.drp` is
    best effort -- older builds and collaboration projects refuse it. This
    replays the journal in REVERSE, so a clip touched twice in one burst ends
    up at the path it had before the burst started.

    Entries whose clip is no longer in the media pool (removed since) are
    counted as `skipped`, never guessed at. Never raises.

    THE JOURNAL AND THE OPEN PROJECT MUST MATCH (comp-resolve-2, 2026-08-21).
    This used to replay the newest journal of ANY project against whatever
    project happened to be open, matching clips by file path alone -- and
    every project shares the paths under Assets (music beds, archive b-roll),
    so project A's journal could rewrite project B's music clip to A's
    machine-private `F:\\...` spelling, unjournalled and therefore not itself
    undoable. The journal is now chosen for the OPEN project, and a journal
    that names a different one is refused rather than replayed.
    """
    # max_age=0: the cached name is up to 20 s old, and an editor who just
    # switched projects is exactly the person pressing this menu item.
    open_project = current_project_name(max_age=0.0)
    if session_path is not None:
        path: Optional[Path] = Path(session_path)
    else:
        path = resolve_journal.latest_session(open_project) if open_project else None
        if path is None:
            elsewhere = resolve_journal.latest_session()
            other = (str(resolve_journal.read_session(elsewhere).get("project") or "")
                     if elsewhere is not None else "")
            # A journal that names no project at all (the bridge could not
            # read the name when the edit was made) stays replayable: it is
            # the pre-2026-08-21 shape, and refusing it would leave an editor
            # with no rollback at all.
            if elsewhere is not None and open_project and other:
                return {"ok": False, "undone": 0, "skipped": 0, "message": (
                    f"CCSync has not changed any clip paths in \u201c{open_project}\u201d. "
                    f"The last change it made was in \u201c{other}\u201d: open that "
                    "project and undo there.")}
            path = elsewhere
    if path is None:
        return {"ok": False, "undone": 0, "skipped": 0,
                "message": "CCSync has not changed any clip paths on this machine."}
    data = resolve_journal.read_session(path)
    entries = data.get("entries") or []
    if not entries:
        return {"ok": False, "undone": 0, "skipped": 0,
                "message": f"{Path(path).name} records no changes."}

    pool = get_media_pool_items()
    if not pool.get("ok"):
        return {"ok": False, "undone": 0, "skipped": len(entries),
                "message": pool.get("message") or NOT_RUNNING_MESSAGE}
    # The pool walk names the project it walked, which is the authority here:
    # an explicit session_path, or a project name the bridge could not read a
    # moment ago, both land in this check (comp-resolve-2, 2026-08-21).
    open_name = str(pool.get("project_name") or "") or open_project
    journal_project = str(data.get("project") or "")
    if (journal_project and open_name
            and resolve_journal.project_slug(journal_project)
            != resolve_journal.project_slug(open_name)):
        return {"ok": False, "undone": 0, "skipped": len(entries), "message": (
            f"That change was made in \u201c{journal_project}\u201d but "
            f"\u201c{open_name}\u201d is open. Open "
            f"\u201c{journal_project}\u201d and undo there: replaying it here would "
            "re-address clips the two projects share.")}
    # ITEM DICTS, not objects (library walk, 2026-08-26). A walk that
    # carried no objects would otherwise leave this map empty and the undo
    # would report "0 put back, N could not be undone -- no longer in this
    # project's media pool" for a pool that holds every one of them. The
    # object is looked up at the ReplaceClip below.
    by_path: dict[str, Any] = {}
    for item in pool.get("items") or []:
        if item.get("file_path") and media_pool_item_is_reachable(item):
            by_path.setdefault(_norm_path(str(item["file_path"])), item)

    undone = 0
    skipped = 0
    for entry in reversed(entries):
        kind = str(entry.get("kind") or "")
        old = str(entry.get("old") or "")
        new = str(entry.get("new") or "")
        if kind == resolve_journal.KIND_REPLACE_CLIP:
            found = by_path.get(_norm_path(new))
            mpi = resolve_media_pool_item(found)
            if mpi is None or not old:
                skipped += 1
                continue
            result = replace_clip(mpi, old, tries=1, journal=False)
            if result.get("ok"):
                undone += 1
                by_path[_norm_path(old)] = found
            else:
                skipped += 1
        elif kind == resolve_journal.KIND_LINK_PROXY:
            # The clip is addressed by its ORIGINAL's path, which a proxy
            # relink never changed -- the journal's old/new are proxy paths.
            found = by_path.get(_norm_path(str(entry.get("clip_path") or "")))
            if found is None:
                found = _find_by_clip_name(pool.get("items") or [], entry.get("clip"))
            mpi = resolve_media_pool_item(found)
            if mpi is None:
                skipped += 1
                continue
            result = (link_proxy_media(mpi, old, journal=False) if old
                      else unlink_proxy_media(mpi))
            if result.get("ok"):
                undone += 1
            else:
                skipped += 1
        else:
            skipped += 1

    message = (f"Put {undone} clip path(s) back the way they were "
               f"(from {Path(path).name}).")
    if skipped:
        message += (f" {skipped} could not be undone: those clips are no longer in "
                    "this project's media pool.")
    log.info("resolve: undo replayed %s -- %d undone, %d skipped", path, undone, skipped)
    return {"ok": undone > 0, "undone": undone, "skipped": skipped, "message": message}


def _find_by_clip_name(items: list[dict[str, Any]], name: Any) -> Any:
    """The ITEM DICT whose clip_name matches, or None -- the caller resolves
    the object (library walk, 2026-08-26)."""
    text = str(name or "")
    if not text:
        return None
    for item in items:
        if item.get("clip_name") == text:
            return item
    return None


# -- b-roll "Send to Resolve" ----------------------------------------------
#
# Absorbed from the standalone b-roll companion when it was retired
# (2026-08-10) -- the fork's upstream, and the only function this module did
# not already carry. Driven by broll_server.py's POST /insert, i.e. by a
# button in the b-roll web page, so its result dict is user-visible text.

# Media-pool bin path the archive clips land in. A SUB-bin, not a flat
# "B-Roll" (2026-08-11, admin request): the parent stays the editors'
# working b-roll bin, and clips arriving from the archive keep to their own
# shelf under it instead of mixing into hand-imported material.
BROLL_BIN_PATH = ("B-Roll", "Archive")

# The video track a b-roll clip is appended to. EXPLICIT because
# AppendToTimeline without a trackIndex obeys the timeline's destination-track
# buttons: with the video destination toggled off (normal while an editor is
# working on audio) it places NOTHING and reports no error, so "Send to
# Resolve" said `Inserted A001 (240 frames)` over an unchanged timeline
# (MED-4, 2026-08-11; music_worker.py:35-40 is where that landmine is written
# down). `mediaType` is deliberately NOT sent with it, unlike music_worker's
# audio-only place(): it would restrict the append to one stream, and a b-roll
# clip arriving without its nat sound is the same silent wrongness in the
# other direction.
BROLL_TRACK_INDEX = 1

# What an editor is told when Resolve accepted the append and the timeline did
# not change. Names the cause, because the cause is a button they can see.
# What an editor is told when Resolve will not create the bin the clip has to
# land in. Names the real cause: the generic "Resolve didn't answer, make sure
# a project is open" they used to get is advice they cannot act on, with a
# project open in front of them (COMP-MEDIA-8, 2026-08-14).
BIN_REFUSED_MESSAGE = (
    "Resolve wouldn't create the B-Roll/Archive bin: the project is locked "
    "(or open elsewhere in a collaboration). Unlock it and try again."
)

NOTHING_PLACED_MESSAGE = (
    "Resolve reported no error but nothing landed on the timeline. Check the "
    "destination track buttons (V1/A1) at the left of the timeline; with the "
    "video destination off, an append is silently dropped."
)

# The /insert modes. "append" is v1's only behaviour; "playhead" (2026-08-14)
# places the clip at the playhead on the lowest free overlay track instead of
# at the end of the timeline. The string values are the wire contract with
# the web page (broll/SPEC.md) — broll_server refuses anything else before it
# reaches this module.
INSERT_MODE_APPEND = "append"
INSERT_MODE_PLAYHEAD = "playhead"

# The lowest track "place at playhead" will consider. V1 is the edit itself,
# so an overlay starts looking at V2 — music_worker's FIRST_MUSIC_TRACK
# reasoning (keep the base lane for the base material), mirrored vertically.
# Even over an empty stretch of V1 the clip goes above: "on top" that
# sometimes means "into the cut" would make the button's behaviour depend on
# where the playhead happens to be parked.
FIRST_OVERLAY_TRACK = 2


def _timeline_fps(timeline) -> float:
    """The timeline frame rate, 24.0 when it cannot be read (music_worker's
    exact_fps fallback — only used for ruler math, never persisted)."""
    try:
        return float(timeline.GetSetting("timelineFrameRate"))
    except Exception:
        return 24.0


def _tc_to_frame(tc: Any, base: int) -> Optional[int]:
    """music_worker.tc_to_frame, duplicated because that module imports this
    one. Drop-frame aware (";" separator); None for anything not H:M:S:F."""
    try:
        drop = ";" in tc
        parts = [int(p) for p in re.split(r"[:;]", tc)]
    except (TypeError, ValueError):
        return None
    if len(parts) != 4:
        return None
    h, m, s, f = parts
    frame = (3600 * h + 60 * m + s) * base + f
    if drop:
        dropped = 4 if base == 60 else 2
        total_min = 60 * h + m
        frame -= dropped * (total_min - total_min // 10)
    return frame


def _playhead_frame(timeline) -> Optional[int]:
    """Where the playhead is, in absolute timeline frames, or None.

    Absolute (the 1-hour start counts) because that is what AppendToTimeline's
    recordFrame wants — music_worker.playhead() computes it the same way and
    its placements land, which is the live verification for this math. NOT
    the GetStartFrame-relative convention SetMarkInOut uses.
    """
    base = int(round(_timeline_fps(timeline)))
    try:
        tc = timeline.GetCurrentTimecode()
    except Exception:
        tc = None
    frame = _tc_to_frame(tc, base) if tc else None
    if frame is not None:
        return frame
    try:
        return int(timeline.GetStartFrame())
    except Exception:
        return None


def _track_count(timeline, kind: str) -> Optional[int]:
    try:
        return int(timeline.GetTrackCount(kind))
    except Exception:
        return None


def _span_is_free(timeline, kind: str, index: int, rec: int, span: int) -> bool:
    """Nothing on that track crosses [rec, rec+span).

    An unreadable TRACK answers True — "cannot tell" must never veto, the
    same rule as _video_track_count. An unreadable ITEM answers False: a
    specific thing is sitting there and its extent is unknown, and placing
    blind on top of it is the silent wrongness this scan exists to avoid.
    """
    try:
        items = timeline.GetItemListInTrack(kind, index)
    except Exception:
        return True
    for item in items or []:
        try:
            if int(item.GetStart()) < rec + span and int(item.GetEnd()) > rec:
                return False
        except Exception:
            return False
    return True


def _overlay_track(timeline, rec: int, span: int) -> Optional[tuple[int, bool]]:
    """(track index, any_track_is_new) for the lowest slot whose video AND
    audio lanes are both clear across [rec, rec+span), or None when the
    track layout cannot be read at all.

    One index serves both streams because AppendToTimeline takes a single
    trackIndex — the clip's nat sound rides to the same-numbered audio
    track, so a slot only counts as free when both lanes are. max+1 always
    exists as an answer: a track index past both counts is free by
    definition (the tracks get created before the place).
    """
    v_count = _track_count(timeline, "video")
    a_count = _track_count(timeline, "audio")
    if v_count is None or a_count is None:
        return None
    top = max(v_count, a_count) + 1
    for index in range(FIRST_OVERLAY_TRACK, top + 1):
        video_ok = index > v_count or _span_is_free(timeline, "video", index, rec, span)
        audio_ok = index > a_count or _span_is_free(timeline, "audio", index, rec, span)
        if video_ok and audio_ok:
            return index, index > v_count or index > a_count
    return top, True


def _ensure_track(timeline, kind: str, index: int) -> bool:
    """Grow `kind` until track `index` exists.

    AddTrack only ever appends at the top, so reaching an index can mean
    creating the tracks under it too (a timeline with V1 and four busy audio
    tracks sends the overlay to slot 5 — V2..V5 all get made). Appending to
    a track that does not exist returns an item yet places NOTHING
    (music_worker's landmine list), which is why this runs first.
    """
    count = _track_count(timeline, kind)
    if count is None:
        return False
    while count < index:
        try:
            added = (timeline.AddTrack(kind, "stereo") if kind == "audio"
                     else timeline.AddTrack(kind))
        except Exception:
            return False
        if not added:
            return False
        count += 1
    return True


def _estimated_timeline_span(media_pool_item, n_source_frames: int, timeline) -> int:
    """The timeline frames the clip will cover, best effort.

    in/out arrive in ORIGINAL-media frames (SPEC's /insert contract); on a
    timeline running at a different rate the placed extent differs, and the
    free-track scan must not measure with the wrong ruler. An unreadable
    clip fps falls back to the raw source count — close enough for a scan
    that only picks a shelf, and the post-place verification catches any
    real collision regardless.
    """
    try:
        props = media_pool_item.GetClipProperty() or {}
        src_fps = float(props.get("FPS") or 0)
    except Exception:
        src_fps = 0.0
    tl_fps = _timeline_fps(timeline)
    if src_fps > 0 and tl_fps > 0:
        return max(1, int(round(n_source_frames * tl_fps / src_fps)))
    return max(1, n_source_frames)


def _video_track_count(timeline, track_index: int) -> Optional[int]:
    """How many items are on that video track, or None if it cannot be read.

    None is "cannot tell", and every caller treats that as "believe the API" --
    the check below must never turn a successful insert into a failure message
    just because a Resolve version answered this differently.
    """
    try:
        items = timeline.GetItemListInTrack("video", track_index)
    except Exception:
        return None
    try:
        return len(items) if items is not None else None
    except TypeError:
        return None


def _placement_landed(timeline, track_index: int, before: Optional[int], appended: Any) -> bool:
    """Did the append actually put something on the timeline?

    Two independent checks because neither is sufficient alone: a returned
    item is not proof of placement (music_worker.py:42) and GetStart() is what
    tells them apart, and a track whose item count did not grow means nothing
    landed even when the API handed back an object.
    """
    item = appended[0] if isinstance(appended, (list, tuple)) and appended else None
    if item is not None:
        try:
            start = item.GetStart()
        except Exception:
            start = None
        if start is None:
            return False
    after = _video_track_count(timeline, track_index)
    if before is None or after is None:
        return True
    return after > before


def _find_or_create_bin(media_pool, root_folder, name: str):
    """The direct child bin called `name`, creating it if it is not there.

    None when Resolve REFUSES to make it. AddSubFolder returns None/False on a
    locked project rather than raising -- documented and handled by
    _ensure_bin_path below -- and returning that raw made the caller walk the
    second segment of BROLL_BIN_PATH off None, so a locked project told the
    editor "Resolve didn't answer. Make sure a project is open" while their
    project was open and the real problem was the bin (COMP-MEDIA-8,
    2026-08-14).
    """
    for sub in root_folder.GetSubFolderList() or []:
        if sub.GetName() == name:
            return sub
    created = media_pool.AddSubFolder(root_folder, name)
    if not created:
        log.warning("resolve: Resolve would not create the bin %r", name)
        return None
    return created


def _attach_adjacent_proxy(media_pool_item, local_path: str) -> None:
    """Attach `<dir>/Proxy/<stem>.*` to a freshly inserted clip. Best-effort.

    Scripted ImportMedia does NOT run Resolve's adjacent-Proxy auto-attach
    (measured live 2026-08-12: an archive clip imported by this bridge showed
    Proxy: None with its preview sitting right there), so the insert does it
    itself. Called with _API_LOCK already held -- do NOT route through
    link_proxy_media(), which takes the same non-reentrant lock.

    A refusal is logged and swallowed: Resolve validates the pairing itself,
    and a preview with no embedded timecode is refused against a source that
    has one (KNOWN_BUGS R10 -- proven by remuxing the same bytes with
    -timecode, after which the identical link succeeds). The insert still
    stands; the editor just edits the original until the previews are fixed.
    """
    try:
        props = media_pool_item.GetClipProperty() or {}
        if str(props.get("Proxy") or "None") != "None":
            return
    except Exception:
        return
    for candidate in proxy_relink.expected_proxy_paths(local_path):
        if not os.path.isfile(candidate):
            continue
        try:
            if media_pool_item.LinkProxyMedia(candidate):
                log.info("resolve: attached proxy %s", candidate)
                # Journalled but with NO save point: the clip was imported
                # seconds ago by this same call, so there is no prior state
                # an export would preserve -- only the attachment is worth
                # being able to reverse (item 9, 2026-08-17).
                resolve_journal.record(
                    resolve_journal.KIND_LINK_PROXY, current_project_name(),
                    clip_name=_safe_clip_name(media_pool_item),
                    clip_path=local_path, old_path="", new_path=candidate,
                    source="insert-adjacent-proxy",
                )
            else:
                log.warning(
                    "resolve: refused %s as this clip's proxy -- no embedded "
                    "timecode in the preview is the usual cause (R10)", candidate,
                )
        except Exception:
            log.warning("resolve: LinkProxyMedia(%s) raised", candidate, exc_info=True)
        return


def _find_existing_clip(bin_folder, local_path: str, canonical_fn: Any = None):
    """The MediaPoolItem already holding `local_path`, or None.

    Matched by FILE PATH, not by name: the archive routinely has the same
    filename in two categories, and re-importing a clip the bin already has
    would add a duplicate media pool item per insert.

    `canonical_fn` folds the path's canonical spelling into the match: a
    clip this module imported and then stored canonically (see
    _canonicalize_imported) no longer matches its local spelling textually,
    and without the fold every repeat insert would file a duplicate.
    """
    targets = {_norm_path(local_path)}
    if canonical_fn is not None:
        try:
            spelled = canonical_fn(local_path)
        except Exception:
            spelled = None
        if spelled:
            targets.add(_norm_path(str(spelled)))
    for clip in bin_folder.GetClipList() or []:
        try:
            props = clip.GetClipProperty() or {}
        except Exception:
            props = {}
        if _norm_path(props.get("File Path", "")) in targets:
            return clip
    return None


def perform_insert(
    local_path: str, in_frame: int, out_frame: int, canonical_fn: Any = None,
    mode: str = INSERT_MODE_APPEND,
) -> dict[str, Any]:
    """Insert `local_path`, trimmed in_frame..out_frame, into the current timeline.

    The behaviour broll/SPEC.md's Companion API contract specifies: import
    into the "B-Roll/Archive" bin (reusing the MediaPoolItem if it is
    already there) then place it. `mode` "append" adds it at the end of the
    timeline on V1 (v1's only behaviour); "playhead" places it at the
    playhead on the lowest overlay track (V2+) whose video and audio lanes
    are both clear, adding tracks when none is. Returns {"ok": bool,
    "message": str} -- the shape the web UI renders straight into its
    toast. Never raises.

    `canonical_fn`: import_files_to_bin_path's contract -- the spelling to
    STORE for a freshly imported clip. For an archive insert (the usual
    case: the file is outside the sync tree) canon.local_to_canonical falls
    back to the physical path and this is a no-op; for an in-tree file it is
    what keeps the shared project portable (2026-08-12 Energy Transition
    incident).
    """
    ui_state.wait_while_menu_open()  # same GIL courtesy as the enumerators
    with _bridge_call("perform_insert"):
        result = _perform_insert_locked(
            local_path, in_frame, out_frame, canonical_fn, mode
        )
    return _explain_disconnection(result)


def _perform_insert_locked(
    local_path: str, in_frame: int, out_frame: int, canonical_fn: Any = None,
    mode: str = INSERT_MODE_APPEND,
) -> dict[str, Any]:
    if mode not in (INSERT_MODE_APPEND, INSERT_MODE_PLAYHEAD):
        # broll_server refuses unknown modes before spawning the worker, so
        # reaching this is a caller bug, not an editor state -- but this
        # module's contract is "never raise", so it answers like one.
        return {"ok": False, "message": f"unknown insert mode {mode!r}"}
    resolve = connect()
    if resolve is None:
        return {"ok": False, "message": _NOT_CONNECTED}

    try:
        project_manager = resolve.GetProjectManager()
        project = project_manager.GetCurrentProject() if project_manager else None
    except Exception:
        project = None
    if project is None:
        return {"ok": False, "message": "no project open in Resolve"}

    try:
        timeline = project.GetCurrentTimeline()
    except Exception:
        timeline = None
    if timeline is None:
        return {"ok": False, "message": "no timeline open - create one first"}

    try:
        media_pool = project.GetMediaPool()
        root_folder = media_pool.GetRootFolder()
        broll_bin = root_folder
        for name in BROLL_BIN_PATH:
            broll_bin = _find_or_create_bin(media_pool, broll_bin, name)
            if broll_bin is None:
                return {"ok": False, "message": BIN_REFUSED_MESSAGE}

        media_pool_item = _find_existing_clip(broll_bin, local_path, canonical_fn)
        freshly_imported = False
        if media_pool_item is None:
            media_pool.SetCurrentFolder(broll_bin)
            imported = media_pool.ImportMedia([local_path])
            if not imported:
                return {"ok": False, "message": f"failed to import media at {local_path}"}
            media_pool_item = imported[0]
            freshly_imported = True

        _attach_adjacent_proxy(media_pool_item, local_path)
        if freshly_imported and canonical_fn is not None:
            # After the proxy attach (which probes the LOCAL filesystem), and
            # only for a clip this call created -- an existing clip's spelling
            # is the editor's business, not an insert's.
            _canonicalize_imported(
                [local_path], {_norm_path(local_path): media_pool_item}, canonical_fn,
            )

        if mode == INSERT_MODE_PLAYHEAD:
            return _place_at_playhead(
                timeline, media_pool, media_pool_item, in_frame, out_frame
            )

        before = _video_track_count(timeline, BROLL_TRACK_INDEX)
        appended = media_pool.AppendToTimeline(
            [{"mediaPoolItem": media_pool_item,
              "startFrame": in_frame,
              "endFrame": out_frame,
              "trackIndex": BROLL_TRACK_INDEX}]
        )
        if not appended:
            return {"ok": False, "message": "failed to append clip to timeline"}
        if not _placement_landed(timeline, BROLL_TRACK_INDEX, before, appended):
            return {"ok": False, "message": NOTHING_PLACED_MESSAGE}

        name = _safe_clip_name(media_pool_item)
        n_frames = out_frame - in_frame
        return {"ok": True, "message": f"Inserted {name} ({n_frames} frames)"}
    except Exception as exc:
        # The raw f"Resolve scripting error: {exc}" the b-roll companion
        # returned went straight into the web UI's toast, where it named no
        # action (AUDIT_2 UX-16, same finding as _SCRIPTING_ERROR_MESSAGE's).
        log.warning("resolve: b-roll insert failed: %s", exc, exc_info=True)
        return {"ok": False, "message": _SCRIPTING_ERROR_MESSAGE}


def _place_at_playhead(
    timeline, media_pool, media_pool_item, in_frame: int, out_frame: int,
) -> dict[str, Any]:
    """Place the clip at the playhead on the lowest free overlay track.

    Nothing moves: this is music_worker's act_under ("place, don't ripple"),
    mirrored to video. recordFrame + an explicit trackIndex, no mediaType --
    the nat sound comes along, per the append's own rule above. The one
    AppendToTimeline behaviour this leans on that music_worker's audio-only
    place() never exercised is a DUAL-stream clip riding one trackIndex to
    the same-numbered A track; the post-place GetStart verification catches
    a Resolve that answers differently, but a live check on a real timeline
    is owed at ship time (the R1 rule).

    Runs inside _perform_insert_locked's try, so an unexpected raise becomes
    _SCRIPTING_ERROR_MESSAGE like everything else in the insert.
    """
    rec = _playhead_frame(timeline)
    if rec is None:
        return {"ok": False,
                "message": "couldn't read the playhead position from Resolve"}
    span = _estimated_timeline_span(media_pool_item, out_frame - in_frame, timeline)
    slot = _overlay_track(timeline, rec, span)
    if slot is None:
        return {"ok": False, "message": "couldn't read the timeline's tracks"}
    track, is_new = slot
    for kind in ("video", "audio"):
        if not _ensure_track(timeline, kind, track):
            return {"ok": False,
                    "message": f"couldn't add a {kind} track for the overlay -- "
                               "is the timeline locked?"}

    appended = media_pool.AppendToTimeline(
        [{"mediaPoolItem": media_pool_item,
          "startFrame": in_frame,
          "endFrame": out_frame,
          "recordFrame": rec,
          "trackIndex": track}]
    )
    item = appended[0] if isinstance(appended, (list, tuple)) and appended else None
    start = None
    if item is not None:
        try:
            start = int(item.GetStart())
        except Exception:
            start = None
    if item is None or start != rec:
        # A returned item is not proof of placement, and for a placement the
        # ONLY acceptable landing is the requested frame -- music_worker's
        # place() verification, including its cleanup of a clip that landed
        # somewhere else.
        if item is not None:
            try:
                timeline.DeleteClips([item], False)
            except Exception:
                log.warning("resolve: couldn't remove a misplaced overlay",
                            exc_info=True)
        return {"ok": False,
                "message": f"placement failed on V{track} at the playhead -- "
                           "something already occupies that span, or the track "
                           "is locked"}

    name = _safe_clip_name(media_pool_item)
    suffix = " (new track)" if is_new else ""
    return {"ok": True,
            "message": f"Placed {name} on V{track} at the playhead{suffix}"}


# -- YouTube auto-import (Master/Youtube/<term>) ---------------------------
#
# Driven by youtube_import.py, which watches <project>/Youtube/<term>/ on disk
# and hands the settled files here. In-process, like the b-roll insert above
# and unlike music_worker's child process: the companion already walks the
# media pool on background threads (get_media_pool_items), and a child would
# have to pay for a full pool walk PER FILE.
#
# Nothing in here raises. The importer treats a refusal as a state to retry
# next cycle, never as a per-file failure -- see youtube_import's gate.

# What the media pool's root folder is called in Resolve's own UI. Only used
# in log lines: _ensure_bin_path is handed the root folder itself.
MASTER_BIN_NAME = "Master"

# A bin name Resolve will accept for a term folder that sanitises down to
# nothing (a directory called "..." or "   " -- rare, but the alternative is
# AddSubFolder("") and a bin nobody can find).
FALLBACK_BIN_NAME = "Untitled"


def _safe_bin_name(segment: Any) -> str:
    """A term folder's name, made safe to hand to AddSubFolder.

    Three narrow rules, each for something a downloaded term folder really
    carries: `/` and `\\` become `-` (they would read as a bin PATH inside a
    single name), edge whitespace goes (a folder named "algal reef " and one
    named "algal reef" must not become two bins), and trailing dots go with
    it -- Windows silently strips them from directory names, so the folder on
    disk and the name we would compare against differ by one character.
    """
    text = str(segment or "").replace("/", "-").replace("\\", "-")
    # rstrip(" .") rather than rstrip(".") -- "term . " has to lose both, and
    # in either order.
    text = text.strip().rstrip(" .").strip()
    return text or FALLBACK_BIN_NAME


def _nfc(name: Any) -> str:
    """A bin/folder name folded to Unicode NFC for comparison ONLY.

    macOS hands out filenames in NFD (decomposed) and Resolve stores whatever
    it was given, so "藻礁" from a macOS listdir and "藻礁" read back off a bin
    Resolve made are different STRINGS that render identically. Comparing them
    raw means no existing bin is ever recognised, so every cycle adds another
    bin with the same visible name and re-imports into it -- which is exactly
    the CJK-term failure this whole helper exists to avoid.
    """
    try:
        return unicodedata.normalize("NFC", str(name or ""))
    except Exception:
        return str(name or "")


def _ensure_bin_path(media_pool, root_folder, segments) -> Any:
    """Walk/create `root_folder/<seg>/<seg>/...` and return the last folder.

    `root_folder` IS "Master" -- the media pool root, which Resolve creates
    and which nothing here may add or rename.

    Each segment is matched against the parent's DIRECT children only
    (`GetSubFolderList()`), never recursively: music_worker.find_folder
    searches the whole tree by name, which is right for one well-known bin
    ("Music") and wrong here -- an editor with their own "Youtube" bin three
    levels down would otherwise capture every import.

    Returns None when Resolve refuses to make a bin (AddSubFolder returns
    None/False on a locked project, and has been seen to return False rather
    than raise). The caller treats that as "not this cycle", never as a file
    failure.
    """
    folder = root_folder
    for segment in segments:
        name = _safe_bin_name(segment)
        target = _nfc(name)
        try:
            children = folder.GetSubFolderList() or []
        except Exception:
            log.debug("resolve: could not list sub-bins of %s",
                      _safe_folder_name(folder) or MASTER_BIN_NAME, exc_info=True)
            children = []
        found = None
        for child in children:
            if _nfc(_safe_folder_name(child)) == target:
                found = child
                break
        if found is None:
            try:
                found = media_pool.AddSubFolder(folder, name)
            except Exception:
                log.warning("resolve: AddSubFolder(%r) raised", name, exc_info=True)
                return None
            if not found:
                log.warning("resolve: Resolve would not create the bin %r", name)
                return None
        folder = found
    return folder


def import_files_to_bin_path(
    paths: Any, bin_segments: Any, expected_project_name: str = "",
    path_alias_fn: Any = None, canonical_fn: Any = None,
) -> dict[str, Any]:
    """Import `paths` into `Master/<bin_segments...>`, once each. Never raises.

    Returns {"ok", "message", "imported": [...], "skipped_existing": [...],
    "failed": [...]} -- every list a list of the paths as they were passed in.

    "skipped_existing" is POOL-WIDE, not bin-wide (music_worker.existing_item's
    precedent): a clip the editor dragged out of Master/Youtube/<term> into
    their own bin must never be re-imported, and the pool walk that answers
    that question is the same one either way. It is matched on FILE PATH, so
    the same video downloaded into two different term folders lands in both
    bins -- each term bin is self-contained on purpose.

    `expected_project_name` is the project the CALLER scanned the disk for.
    Resolve is a moving target between a background scan and this call: the
    editor can close one project and open another in that window, and a bin
    full of another project's YouTube clips is a mess somebody has to undo by
    hand. Blank means "whatever is open" (the b-roll insert's behaviour).

    `path_alias_fn` folds a SECOND spelling of each pool path into the dedupe
    set: called once per pool clip, returning an equivalent path or None.
    Fleet projects hold the same file under two spellings -- clips an editor
    imported by hand through the P: drive are stored canonically
    (`P:\\Projects\\...`), while this module is handed local_root paths
    (broll_server.default_broll_mount's reason: ImportMedia cannot resolve
    "P:\\" on a Mac). Without the fold, `_norm_path` never matches the two and
    the first scan of a pre-existing Youtube folder would duplicate every
    hand-imported clip in it. The caller owns the translation because only it
    knows local_root/canonical_prefix (canon.canonical_to_local); this stays
    config-free.

    `canonical_fn` is the OTHER half of the same two-spellings problem:
    ImportMedia is handed local_root paths (it cannot resolve "P:\\" on a
    Mac), so left alone it STORES the local spelling -- which is offline on
    every other machine in the fleet (the 2026-08-12 "Energy Transition"
    incident: 158 F:\\-spelled clips). Called once per imported item with its
    File Path; a canonical spelling that differs is written back with
    ReplaceClip, the fixer's own mechanism (fixer.py stores canonical on
    every platform -- macOS resolves it through Resolve's Mapped Mount).
    Best-effort: a refusal keeps the local spelling and is logged, never
    failed -- the media is in the pool either way.
    """
    wanted = [str(p) for p in (paths or [])]
    if not wanted:
        return {"ok": True, "message": "nothing to import",
                "imported": [], "skipped_existing": [], "failed": []}
    ui_state.wait_while_menu_open()  # same GIL courtesy as the enumerators
    with _bridge_call("import_files_to_bin_path"):
        result = _import_files_to_bin_path_locked(
            wanted, list(bin_segments or []), str(expected_project_name or ""),
            path_alias_fn, canonical_fn,
        )
    return _explain_disconnection(result)


def _canonicalize_imported(
    imported: list[str], item_by_path: dict[str, Any], canonical_fn: Any,
) -> None:
    """Rewrite freshly imported items' stored paths to the canonical spelling.

    One ReplaceClip attempt per item, verified by re-reading File Path (the
    return value is unreliable -- see replace_clip). Refusals are logged and
    left alone: the clip plays either way on THIS machine, it is merely not
    yet portable. Caller already holds _API_LOCK (re-entrant).
    """
    for local_path in imported:
        item = item_by_path.get(_norm_path(local_path))
        if item is None:
            continue
        try:
            target = canonical_fn(local_path)
        except Exception:
            log.debug("resolve: canonical_fn raised for %r", local_path, exc_info=True)
            continue
        if not target or _norm_path(str(target)) == _norm_path(local_path):
            continue
        result = replace_clip(item, str(target), tries=1, source="import-canonicalise")
        if result.get("ok"):
            log.info("resolve: stored %s canonically as %s", local_path, target)
        else:
            log.warning(
                "resolve: imported %s but could not store the canonical spelling %s "
                "(kept the local one): %s", local_path, target, result.get("message"),
            )


def _refused(message: str) -> dict[str, Any]:
    """An import that never got as far as ImportMedia.

    `failed` is deliberately EMPTY: the caller counts per-file failures and
    gives up on a file after three of them, and "Resolve is closed" / "you
    opened a different project" is a state of the world, not something wrong
    with the file. Charging them to the file would blacklist a perfectly good
    clip for the rest of the session (proxy_gen's same rule, its :346-349).
    """
    return {"ok": False, "message": message,
            "imported": [], "skipped_existing": [], "failed": []}


def _import_files_to_bin_path_locked(
    paths: list[str], bin_segments: list[Any], expected_project_name: str,
    path_alias_fn: Any = None, canonical_fn: Any = None,
) -> dict[str, Any]:
    resolve = connect()
    if resolve is None:
        return _refused(_NOT_CONNECTED)

    try:
        project_manager = resolve.GetProjectManager()
        project = project_manager.GetCurrentProject() if project_manager else None
    except Exception:
        project = None
    if project is None:
        return _refused("no project open in Resolve")

    project_name = _safe_project_name(project)
    if expected_project_name and project_name.strip() != expected_project_name.strip():
        log.info(
            "resolve: not importing into %r -- the open project is now %r",
            expected_project_name, project_name,
        )
        return _refused("project changed")

    try:
        media_pool = project.GetMediaPool()
    except Exception:
        media_pool = None
    if media_pool is None:
        return _refused("no media pool available")

    try:
        root_folder = media_pool.GetRootFolder()
    except Exception:
        root_folder = None
    if root_folder is None:
        return _refused("no root folder in media pool")

    # ONE walk for the whole batch. The pool walk is the expensive part of
    # this function (four fusionscript calls per clip); doing it per file is
    # what the batching in youtube_import exists to avoid.
    existing: list[dict[str, Any]] = []
    try:
        _walk_media_pool_folder(root_folder, project_name, existing)
    except Exception as exc:
        log.warning("resolve: media pool walk failed before import: %s", exc, exc_info=True)
        return _refused(_SCRIPTING_ERROR_MESSAGE)
    in_pool = {_norm_path(item.get("file_path") or "") for item in existing}
    if path_alias_fn is not None:
        # Each alias is one more spelling of a file already in the pool, and a
        # raising/None alias just means "no second spelling for this one".
        for item in existing:
            try:
                alias = path_alias_fn(item.get("file_path") or "")
            except Exception:
                alias = None
            if alias:
                in_pool.add(_norm_path(alias))

    skipped: list[str] = []
    to_import: list[str] = []
    queued: set[str] = set()
    for path in paths:
        key = _norm_path(path)
        if key in in_pool:
            skipped.append(path)
            continue
        if key in queued:
            # The same file twice in one batch: ImportMedia would happily make
            # two media pool items out of it.
            continue
        queued.add(key)
        to_import.append(path)

    if not to_import:
        return {"ok": True, "message": "already in the media pool",
                "imported": [], "skipped_existing": skipped, "failed": []}

    bin_folder = _ensure_bin_path(media_pool, root_folder, bin_segments)
    if bin_folder is None:
        return {"ok": False, "message": "could not create the bin",
                "imported": [], "skipped_existing": skipped, "failed": []}

    # Remember/restore the editor's current bin around the import
    # (music_worker.import_clip's shape). ImportMedia files into whatever
    # SetCurrentFolder last named, and leaving the media pool selection parked
    # somewhere the editor did not put it is a visible, confusing side effect
    # of a background job they never asked to see.
    try:
        previous = media_pool.GetCurrentFolder()
    except Exception:
        previous = None
    imported_items: Any = []
    try:
        media_pool.SetCurrentFolder(bin_folder)
        imported_items = media_pool.ImportMedia(to_import) or []
    except Exception as exc:
        log.warning("resolve: ImportMedia raised for %d file(s): %s",
                    len(to_import), exc, exc_info=True)
        return {"ok": False, "message": _SCRIPTING_ERROR_MESSAGE,
                "imported": [], "skipped_existing": skipped, "failed": []}
    finally:
        # In a finally, and guarded: a raising ImportMedia must not leave the
        # editor's media pool pointing at a bin this job made.
        if previous is not None:
            try:
                media_pool.SetCurrentFolder(previous)
            except Exception:
                log.debug("resolve: could not restore the current bin", exc_info=True)

    landed = set()
    item_by_path: dict[str, Any] = {}
    for item in imported_items or []:
        try:
            props = item.GetClipProperty() or {}
        except Exception:
            props = {}
        fp = (props.get("File Path") or "").strip()
        landed.add(_norm_path(fp))
        if fp:
            item_by_path.setdefault(_norm_path(fp), item)

    imported = [p for p in to_import if _norm_path(p) in landed]
    missing = [p for p in to_import if _norm_path(p) not in landed]
    if missing:
        # ImportMedia's return is not the whole truth: it has been seen to
        # answer with fewer items than it filed (and a clip Resolve merges
        # into an existing one comes back not at all). Re-read the bin before
        # calling anything failed -- a file reported as failed here is
        # retried, and after three retries left alone for the session.
        try:
            bin_clips = bin_folder.GetClipList() or []
        except Exception:
            bin_clips = []
        in_bin = set()
        for clip in bin_clips:
            try:
                props = clip.GetClipProperty() or {}
            except Exception:
                props = {}
            fp = (props.get("File Path") or "").strip()
            in_bin.add(_norm_path(fp))
            if fp:
                item_by_path.setdefault(_norm_path(fp), clip)
        verified = [p for p in missing if _norm_path(p) in in_bin]
        missing = [p for p in missing if _norm_path(p) not in in_bin]
        imported = [p for p in to_import if p in set(imported) | set(verified)]

    if canonical_fn is not None and imported:
        # LAST, after all bookkeeping: the dedupe/verification above matches
        # on the local spellings ImportMedia was handed, and ReplaceClip
        # changes the stored one. Single attempt, best-effort -- a clip left
        # on its local spelling is what every import stored before this
        # existed, and the media-tree sweep re-offers the fix later.
        _canonicalize_imported(imported, item_by_path, canonical_fn)

    if missing:
        log.warning(
            "resolve: Resolve would not import %d of %d YouTube file(s) into %s",
            len(missing), len(to_import), "/".join(
                [MASTER_BIN_NAME] + [_safe_bin_name(s) for s in bin_segments]
            ),
        )
    return {
        "ok": not missing,
        "message": "" if not missing else f"Resolve refused {len(missing)} file(s)",
        "imported": imported,
        "skipped_existing": skipped,
        "failed": missing,
    }
