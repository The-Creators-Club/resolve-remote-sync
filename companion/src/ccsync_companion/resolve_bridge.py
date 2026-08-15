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
from typing import Any, Optional

from . import canon, proxy_relink, resolve_prefs, ui_state

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
# The order matters and is not obvious: fusionscript.dll keeps process-global
# IPC state, and a long-running client whose Resolve has restarted underneath
# it can wedge the NEW Resolve's scripting server for EVERY client -- at which
# point restarting Resolve alone can never fix it (proven live 2026-08-12:
# three Resolve restarts changed nothing; companion-then-Resolve connected
# first try). The companion now restarts itself when its Resolve goes away
# (app._maybe_recover_stale_bridge), so this advice is the manual fallback.
NO_SCRIPTING_MESSAGE = (
    "DaVinci Resolve is running but isn't accepting scripting connections. "
    "Restart the companion first (tray → Exit, then relaunch), THEN quit and "
    "reopen Resolve."
)

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
    return NO_SCRIPTING_MESSAGE if _resolve_process_present() else NOT_RUNNING_MESSAGE


DISCONNECTION_MESSAGES = (NOT_RUNNING_MESSAGE, NO_SCRIPTING_MESSAGE)


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


def get_timeline_items(allow_cached: bool = False) -> dict[str, Any]:
    """Enumerate every video+audio timeline item on the current timeline.

    Returns {"ok": bool, "message": str, "items": [...], "project_name": str}.
    Never raises.

    Each item dict: {
        "file_path": str,               # GetClipProperty()["File Path"]
        "media_pool_item": <object>,    # for ReplaceClip / identity checks
        "clip_name": str,
        "track_type": "video" | "audio",
        "track_index": int,             # 1-based, per Resolve's own convention
        "item_index": int,              # 0-based position within the track
    }

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
    with _bridge_call("get_timeline_items"):
        result = _get_timeline_items_locked(allow_cached=allow_cached)
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
# State is written and read only under _API_LOCK, by the two functions below.
_FULL_WALK_EVERY_POLLS = 10

_timeline_cache_fingerprint: Optional[tuple] = None
_timeline_cache_result: Optional[dict[str, Any]] = None
_polls_since_full_walk = 0


def reset_timeline_cache() -> None:
    """Forget the last poll — for tests only; the companion polls one
    timeline for its whole life and never calls this."""
    global _timeline_cache_fingerprint, _timeline_cache_result, _polls_since_full_walk
    with _bridge_call("reset_timeline_cache"):
        _timeline_cache_fingerprint = None
        _timeline_cache_result = None
        _polls_since_full_walk = 0


def _cached_timeline_result(fingerprint: tuple) -> Optional[dict[str, Any]]:
    """The previous poll's answer if this poll is provably the same one, else
    None meaning "walk it properly". Caller holds _API_LOCK."""
    global _polls_since_full_walk
    if _timeline_cache_result is None or fingerprint != _timeline_cache_fingerprint:
        return None
    if _polls_since_full_walk >= _FULL_WALK_EVERY_POLLS - 1:
        return None  # safety valve: walk it anyway
    _polls_since_full_walk += 1
    # A fresh outer dict and list: the watcher and the fixer own what they are
    # handed, and a caller appending to `items` must not edit the cache.
    return {**_timeline_cache_result, "items": list(_timeline_cache_result["items"])}


def _remember_timeline_result(fingerprint: tuple, result: dict[str, Any]) -> None:
    """Caller holds _API_LOCK."""
    global _timeline_cache_fingerprint, _timeline_cache_result, _polls_since_full_walk
    _timeline_cache_fingerprint = fingerprint
    _timeline_cache_result = {**result, "items": list(result.get("items") or [])}
    _polls_since_full_walk = 0


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
                try:
                    props = media_pool_item.GetClipProperty() or {}
                except Exception:
                    props = {}
                file_path = (props.get("File Path") or "").strip()
                if not file_path:
                    continue
                items.append(
                    {
                        "file_path": file_path,
                        "media_pool_item": media_pool_item,
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
        try:
            props = clip.GetClipProperty() or {}
        except Exception:
            props = {}
        file_path = (props.get("File Path") or "").strip()
        if not file_path:
            continue  # timelines, compound clips, generators have no File Path
        items.append(
            {
                "file_path": file_path,
                "media_pool_item": clip,
                "clip_name": _safe_clip_name(clip),
                "resolve_project_name": project_name,
                "bin_path": bin_path,
                # The clip's SECOND path. Independent of "File Path" and not
                # shown by Reveal in Folder, so a clip can look correctly
                # linked while its proxy points at a drive that has never
                # existed here -- see proxy_relink.py.
                "proxy_path": (props.get("Proxy Media Path") or "").strip(),
                # "1920x1080" when the proxy resolves, "Offline" when
                # attached but unreachable, "None" when there is none.
                "proxy_state": (props.get("Proxy") or "").strip(),
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
        "media_pool_item": <object>,    # for ReplaceClip / identity checks
        "clip_name": str,
        "resolve_project_name": str,    # the current project's GetName()
    }

    Unlike get_timeline_items (where the watcher attaches
    "resolve_project_name" itself), this function includes it directly on
    every item, since there's no separate watcher layer in between here and
    the popup/fixer for a manual whole-project scan (see app.scan_whole_project).

    Items with no media pool item, or an empty "File Path" (timelines,
    compound clips, generators, titles), are skipped entirely — same rule as
    get_timeline_items.
    """
    ui_state.wait_while_menu_open()  # same GIL courtesy as get_timeline_items
    with _bridge_call("get_media_pool_items"):
        result = _get_media_pool_items_locked()
    return _explain_disconnection(result)


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


def replace_clip(media_pool_item, new_path: str, tries: int = 3) -> dict[str, Any]:
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

    raised = 0
    for attempt in range(max(1, tries)):
        ui_state.wait_while_menu_open()
        with _bridge_call("replace_clip"):
            try:
                media_pool_item.ReplaceClip(new_path)
            except Exception as exc:
                raised += 1
                log.warning("resolve: ReplaceClip(%s) raised: %s", new_path, exc, exc_info=True)
            after = _file_path_locked()
        if after is not None and _norm_path(after) == norm_new:
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


def link_proxy_media(media_pool_item, proxy_path: str) -> dict[str, Any]:
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
    with _bridge_call("link_proxy_media"):
        try:
            result = media_pool_item.LinkProxyMedia(proxy_path)
        except Exception as exc:
            log.warning("resolve: LinkProxyMedia(%s) raised: %s", proxy_path, exc, exc_info=True)
            return {"ok": False, "message": _SCRIPTING_ERROR_MESSAGE}
    if not result:
        return {
            "ok": False,
            "message": f"Resolve wouldn't accept {proxy_path} as this clip's proxy",
        }
    return {"ok": True, "message": f"Proxy relinked to {proxy_path}"}


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
    "Resolve wouldn't create the B-Roll/Archive bin — the project is locked "
    "(or open elsewhere in a collaboration). Unlock it and try again."
)

NOTHING_PLACED_MESSAGE = (
    "Resolve reported no error but nothing landed on the timeline — check the "
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
        return {"ok": False, "message": "no timeline open — create one first"}

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
        result = replace_clip(item, str(target), tries=1)
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
