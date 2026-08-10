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

import logging
import logging.handlers
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

from . import broll_server as broll_server_mod
from . import config as config_mod
from . import luts as luts_mod
from . import paths as paths_mod
from . import popup
from . import proxy_relink
from . import resolve_bridge
from . import resolve_prefs as resolve_prefs_mod
from . import root_guard as root_guard_mod
from . import shutdown_guard as shutdown_guard_mod
from . import stills as stills_mod
from . import ui_dispatch
from . import upgrade as upgrade_mod
from .fixer import IgnoreTracker, _dest_dir_is_contained
from .identity import IdentityManager
from .manifest import ManifestCache
from .paths import OUT_OF_TREE, classify_path
from .project_setup import ProjectSetupPrompter
from .reporter import DashboardReporter
from .selection import SelectionClient
from .sync.base import LaneAdapter, LaneStatus
from .sync.rclone_lane import DIRECTION_DOWN, DIRECTION_UP, VIDEO_EXTS, RcloneLane
from .sync.sequencer import PROJECTS_PREFIX, Sequencer
from .sync.syncthing_admin import SyncthingAdmin
from .sync.syncthing_lane import SyncthingLane
from .watcher import TimelineWatcher

log = logging.getLogger("ccsync.app")


def setup_logging(cfg: dict[str, Any]) -> None:
    log_path = config_mod.resolved_log_path(cfg)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    level = getattr(logging, str(cfg.get("log_level", "INFO")).upper(), logging.INFO)

    root = logging.getLogger("ccsync")
    root.setLevel(level)
    root.handlers.clear()

    file_handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=5_000_000, backupCount=3, encoding="utf-8"
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

    # pystray logs under its own "pystray" root, which had no handler at all:
    # in the windowed build sys.stderr is None, so logging's last-resort
    # handler had nowhere to write either. Everything the tray backend says
    # about itself -- "An error occurred in the main loop" included -- was
    # therefore invisible on exactly the machines where the tray misbehaves.
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
# a failed launch can still roll the whole swap back). On Windows the named
# mutex is released the instant the old process dies and the new one simply
# wins by timing; on posix the pid file is a LIVENESS check, and the dying
# predecessor is very much alive for the second or two its lanes take to stop
# -- so the freshly-installed build exited immediately with "another
# ccsync-companion is already running", leaving the machine with NO companion
# until the next login. The wait below is the fix, and it is deliberately
# narrow: only the pid we were told we replace, only for as long as a normal
# shutdown takes.
_REPLACES_PID_ENV = "CCSYNC_REPLACES_PID"
PREDECESSOR_WAIT_SECONDS = 20.0
PREDECESSOR_POLL_SECONDS = 0.25


def _pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
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


def _acquire_lock_file(
    alive_fn: Optional[Callable[[int], bool]] = None,
    clock: Callable[[], float] = time.monotonic,
    sleep_fn: Callable[[float], None] = time.sleep,
    wait_seconds: float = PREDECESSOR_WAIT_SECONDS,
) -> bool:
    """Portable fallback: a pid file with a liveness check. A stale file from
    a crashed/killed companion must never lock the editor out permanently."""
    global _single_instance_token
    path = config_mod.CONFIG_DIR / _SINGLE_INSTANCE_LOCKFILE
    # Popped unconditionally, before any early return: it must not survive
    # into a child of ours whatever happens below.
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


def acquire_single_instance() -> bool:
    """True when this process may run. False means another companion already
    holds the slot. Never raises; any failure of the guard itself returns
    True rather than blocking a legitimate start."""
    global _single_instance_token
    if sys.platform != "win32":
        return _acquire_lock_file()
    # Windows never has to WAIT for the build it replaces: the named mutex is
    # released the instant the predecessor's last handle closes, so the
    # newcomer wins by timing. Read (and drop) the variable anyway, so it
    # cannot inherit into every rclone this process goes on to launch.
    _replaced_pid()
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
        handle = kernel32.CreateMutexW(None, False, _SINGLE_INSTANCE_MUTEX)
        last_error = ctypes.get_last_error()
        if not handle:
            return True
        if last_error == _ERROR_ALREADY_EXISTS:
            return False
        _single_instance_token = handle
        return True
    except Exception:
        log.debug("single-instance mutex unavailable", exc_info=True)
        return _acquire_lock_file()


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
_LANE_ROOT_ABSENT_DETAIL = (
    "PAUSED: your Creators Club drive is disconnected -- plug it back in and "
    "syncing resumes on its own"
)


class CompanionApp:
    """Owns the timeline watcher, all three sync lanes, and (optionally) the
    tray icon. Every public method is safe to call from any thread (the
    tray runs its callbacks on its own thread)."""

    def __init__(self, cfg: dict[str, Any], exists_fn: Callable[[str], bool] = os.path.exists) -> None:
        self.config = cfg
        self.log_path = config_mod.resolved_log_path(cfg)
        # Injectable for tests -- see get_media_tree()/_refresh_media_tree_once().
        self._exists_fn = exists_fn
        self.ignore_tracker = IgnoreTracker()
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
        self._root_guard: Optional[root_guard_mod.RootGuard] = None
        # Once-per-episode gates: an unplugged drive is a state, not an event,
        # and the guard is free to re-fire (absent -> misplaced) within one.
        self._root_absent_announced = False
        self._root_misplaced_announced = False
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
                self._lane_a, self._lane_b, self.syncthing_admin, self.selection_client, cfg
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
        self._media_tree_lock = threading.Lock()
        self._media_tree_stop_event = threading.Event()
        self._media_tree_thread: Optional[threading.Thread] = None

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
            on_available=lambda info: self._notify_tray(
                upgrade_mod.offer_toast(info["version"]),
                "ccsync-companion",
            ),
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
            get_editor_name=self.editor_identity,
            get_identity_token=lambda: self.identity.token,
            on_report_response=self._on_report_response,
            get_transport_health=self.transport_health,
            get_completions=self._pop_lane_completions,
        )
        self.watcher = TimelineWatcher(
            local_root=cfg["local_root"],
            canonical_prefix=cfg["canonical_prefix"],
            poll_interval=config_mod.coerce_numeric(cfg, "poll_interval", 3),
            on_out_of_tree=self._handle_out_of_tree,
            on_mapping_warning=self._handle_mapping_warning,
            ignore_tracker=self.ignore_tracker,
            on_project_changed=self._on_resolve_project_changed,
            ignored_projects=cfg.get("ignored_resolve_projects"),
            # While the sync drive is out, nothing on the timeline can be
            # classified honestly: every clip is either OUT_OF_TREE (an
            # unfixable popup) or BAD_PREFIX (a warning storm), and neither
            # names the actual problem. The watcher stands down instead.
            root_present_fn=self.root_is_present,
        )

    def _on_report_response(self, resp: Any) -> None:
        """Fan the report response out to every consumer, isolating each --
        the upgrade channel and the new-project prompter both piggyback on
        the same reply."""
        try:
            self.upgrade.note_report_response(resp)
        except Exception:
            log.exception("upgrade.note_report_response failed")
        if self.project_setup is not None:
            try:
                self.project_setup.note_report_response(resp)
            except Exception:
                log.exception("project_setup.note_report_response failed")

    def _on_resolve_project_changed(self, name: str) -> None:
        if self.project_setup is not None:
            try:
                self.project_setup.note_project_changed(name)
            except Exception:
                log.exception("project_setup.note_project_changed failed")

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
        )
        self._lane_a = lane_a
        self._lane_b = lane_b
        self._lane_c = lane_c
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
            self._root_state = str(state)
            self._root_absent = True
            if not self._root_absent_announced:
                self._root_absent_announced = True
                log.warning(
                    "sync paused: local_root %s is not available (%s)",
                    self.config.get("local_root"), state,
                )
                self._notify_tray(
                    "Sync paused — your Creators Club drive is disconnected.",
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
            self._root_state = root_guard_mod.ROOT_PRESENT
            self._root_absent_announced = False
            self._root_misplaced_announced = False
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
            self._notify_tray("Drive reconnected — sync resumed.", "ccsync-companion")
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
            "Your Creators Club drive is mounted at the wrong path. Sync is paused "
            "until it is fixed — see the CCSync window.", "ccsync-companion")
        body = (
            f"Your Creators Club drive is plugged in, but macOS mounted it "
            f"somewhere other than {mount_point}.\n\n"
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
        if self.config_problems or self._login_gate_blocks_sync():
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
                    lane._status.detail = _LANE_ROOT_ABSENT_DETAIL
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
        self._notify_tray(
            f"Resolve is looking for media on {self.config.get('canonical_prefix')} but that "
            "path doesn't land in your sync folder. Your P: drive (Windows) or Mapped Mount "
            "(Mac) is wrong. See EDITOR_SETUP step 6. Nothing will sync until this is fixed.",
            "ccsync-companion: mapping warning",
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
        recently dismissed). Still respects ignore_tracker. Safe to call
        from the tray thread; blocks until any resulting popup is closed.
        """
        if self._root_absent:
            log.warning("scan whole project refused: the sync drive is disconnected")
            self._notify_tray(
                "Your Creators Club drive is disconnected, so CCSync can't tell where "
                "your media is. Plug it back in and try again.", "ccsync-companion")
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

        if not out_of_tree:
            log.info("whole-project scan: all media is in the tree")
            self._notify_tray("Whole-project scan: all media is in the tree", "ccsync-companion")
            return

        log.info("whole-project scan: %d clip(s) outside %s", len(out_of_tree), local_root)
        self._show_out_of_tree_popup(out_of_tree)

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

    def _refresh_media_tree_once(self) -> None:
        """Rescan the media pool and update the cache. Fault-isolated: never
        raises, and any failure just leaves the previous cache in place
        (except an explicit not-ok result, which clears it -- Resolve
        closing/switching projects should not keep reporting stale data)."""
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

        clips: list[dict[str, Any]] = []
        for item in result.get("items", []):
            file_path = item.get("file_path", "") or ""
            try:
                present = bool(self._exists_fn(file_path)) if file_path else False
            except Exception:
                present = False
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
            proxy_relink.apply_relinks(ops, resolve_bridge.link_proxy_media)
        except Exception:
            log.exception("proxy relink pass failed")

    def _media_tree_loop(self) -> None:
        while not self._media_tree_stop_event.is_set():
            try:
                self._refresh_media_tree_once()
            except Exception:
                log.exception("media tree refresh loop failed")
            if self._media_tree_stop_event.wait(self.media_tree_refresh_interval):
                break

    # -- identity / login gating (see identity.py) -----------------------------------------------
    def _apply_identity_role(self) -> None:
        """Dynamic role from the verified sign-in (identity.py's `role`,
        sourced from the dashboard's DASH_ADMIN_USERS list) decides
        sync_enabled when available -- "base" (direct NAS access, e.g. the
        admin's own rig) means no sync lanes, anything else means normal
        editor sync. Falls back to config.toml's static sync_enabled/mode
        when not signed in, require_login is off, or the dashboard didn't
        send a role (older server).

        Only touches self._sync_enabled -- popup_enabled deliberately stays
        whatever config.toml says either way (see config.py's MODE_PROFILES
        comment: a careless base-rig editor can still cut in media from
        outside the tree, so the popup should still catch it).

        MONOTONIC: the role may only ever DISABLE sync, never enable it.
        This used to be a flat `self._sync_enabled = (role != "base")`, which
        let a dashboard-supplied role="editor" override the machine's own
        `mode="base"` / `sync_enabled=false` -- so any sign-in by an account
        outside DASH_ADMIN_USERS started full sync lanes on the base rig,
        where local_root IS the live NAS share (P:\\, historically
        T:\\Creators_Club). Lane B is
        a deleting `rclone sync` DOWNWARD from that user's empty SFTP home,
        i.e. it would delete the NAS's real Proxy/ files under every selected
        project (AUDIT_2 CORE-C1). A machine that says it does not sync must
        stay that way whatever the server says.

        Idempotent and cheap to call whenever identity state changes
        (constructor, sign_in(), sign_out()) rather than threading role
        through every call site that currently reads self._sync_enabled.
        """
        role = self.identity.role
        if role is None:
            self._sync_enabled = self._configured_sync_enabled
        else:
            self._sync_enabled = self._configured_sync_enabled and (role != "base")

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

    def effective_mode(self) -> str:
        """"base" or "editor" -- the identity-derived role when signed in
        and the dashboard sent one, else config.toml's static `mode`. Same
        precedence as _apply_identity_role(); used for dashboard reporting
        (get_mode) so admins see the role actually in effect, not just
        whatever's written in this machine's local file."""
        role = self.identity.role
        if role is not None:
            return role
        return str(self.config.get("mode", "editor")).strip().lower() or "editor"

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
        from . import drive_swap

        try:
            mode = drive_swap.classify_p_target(
                drive_swap.current_p_target(),
                str(self.config.get("local_root", "")),
                self._server_p_unc(),
            )
        except Exception:
            mode = "none"
        self._p_mode_cache = (now, mode)
        return mode

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
            ok, message = drive_swap.swap_to_server(unc, username=username,
                                                    password=password)
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
        out: list[dict[str, str]] = []
        for entry in entries or []:
            slug = str(entry.get("slug") or "").strip()
            rel = str(entry.get("rel_path") or entry.get("label") or "").strip()
            if slug and rel:
                out.append({"slug": slug, "rel": rel})
        return out

    def remove_project_from_machine(self, slug: str) -> tuple[bool, str]:
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
        rel = next((p["rel"] for p in self.removable_projects() if p["slug"] == slug), None)
        if rel is None:
            return False, "that project is not selected on this machine"
        safe_rel = normalized_safe_rel(rel)
        if not safe_rel:
            return False, f"unsafe project path {rel!r} -- nothing was deleted"

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

    def _start_lanes(self) -> None:
        """Actually start the sync lanes/sequencer, per sync_enabled/managed
        mode. Extracted from start() so on_signed_in() can (re)run it once a
        require_login gate clears, without repeating the reporter/manifest/
        watcher startup that only ever needs to happen once."""
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

    def apply_upgrade(self) -> None:
        """Download, verify, swap the exe and restart. Blocking (a ~20 MB
        download) -- the tray calls this on a daemon thread. On failure the
        current build keeps running and the tray says so."""
        info = self.upgrade.available
        if info is None:
            return
        # Never swap the exe and exit out from under work in progress: the
        # spawned copy would be killed mid-shutil.copy2, leaving a partial
        # .ccsync-tmp and a project where some clips are relinked and some
        # are not (AUDIT_2 CORE-H8/H5).
        if self._popup_active_lock.locked():
            self._notify_tray(
                "Can't update while a CCSync window is open. Close it and try again.",
                "ccsync-companion")
            return
        if self._consolidate_active:
            self._notify_tray(
                "Can't update while media is being copied in. Let it finish, then try again.",
                "ccsync-companion")
            return
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

    def _diagnostic_log_tail(self, lines: int = 40) -> list[str]:
        try:
            with open(self.log_path, "r", encoding="utf-8", errors="replace") as fh:
                return [line.rstrip("\n") for line in fh.readlines()[-lines:]]
        except Exception as exc:
            return [f"(could not read {self.log_path}: {exc})"]

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
        out.append("-- lanes --")
        try:
            for status in self.lane_statuses():
                out.append(f"  {vars(status)}")
        except Exception as exc:
            out.append(f"  <failed: {exc}>")

        out.append("")
        out.append("-- syncthing --")
        try:
            reachable = self._lane_c.check_once()
            out.append(f"  reachable: {reachable.state != 'error'} ({reachable.state})")
            out.append(f"  detail: {reachable.detail or reachable.last_error or ''}")
        except Exception as exc:
            out.append(f"  <failed: {exc}>")

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
        from .identity import parse_token

        # Deliberately NOT identity.token (which returns None once expired --
        # and "when did it expire" is exactly what diagnostics need).
        raw = getattr(self.identity, "_identity", None) or {}
        _user, expires = parse_token(raw.get("token"))
        if expires is None:
            return "(no token)"
        remaining = expires - time.time()
        stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(expires))
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
            self._notify_tray(
                "Another CCSync window is open, so the diagnostics went to the log "
                "instead (tray → Open log). Close it and try again to get them on the "
                "clipboard.", "ccsync-companion")
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
                    root.destroy()

            ui_dispatch.dispatch(_copy_via_tk)
            log.info("diagnostics copied to clipboard (%d chars)", len(text))
            self._notify_tray(
                "Diagnostics copied. Paste them to your admin in a message.", "ccsync-companion")
            return True
        except Exception:
            log.exception("could not copy diagnostics to the clipboard")
            log.info("DIAGNOSTICS:\n%s", text)
            self._notify_tray(
                "Couldn't reach the clipboard. The diagnostics were written to the log "
                "instead (tray → Open log).", "ccsync-companion")
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
        rel_to_slug = self.sequencer.rel_to_slug
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
            self._media_tree_stop_event.clear()
            self._media_tree_thread = threading.Thread(
                target=self._media_tree_loop, name="ccsync-media-tree", daemon=True
            )
            self._media_tree_thread.start()
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
        self._stop_event.clear()
        self._watcher_thread = threading.Thread(
            target=self.watcher.run, args=(self._stop_event,), name="ccsync-watcher", daemon=True
        )
        self._watcher_thread.start()
        self._start_shutdown_guard()
        self._start_keep_awake()
        self._start_lut_link()
        self._start_root_guard()
        self._start_broll_server()

    def _start_broll_server(self) -> None:
        """Serve the b-roll web UI's "Send to Resolve" button.

        LAST in start(), and behind its own try: it is a convenience endpoint
        for one button in a web page, and everything above it is what moves
        the footage. broll_server.start() already swallows a failed bind
        (a stale standalone broll-companion holding 8899 is the expected
        cause and it says so in the log) -- this catch is for the rest.
        """
        try:
            self._broll_server = broll_server_mod.start(self.config)
        except Exception:
            log.exception("failed to start the b-roll Send-to-Resolve server")
            self._broll_server = None

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
        return self._pending_tracker.describe(statuses, self._lane_peer_states())

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

        try:
            leftovers = fixer_mod.sweep_stale_tmp_files(str(self.config.get("local_root", "")))
        except Exception:
            log.exception("stale-tmp sweep failed")
            return
        if leftovers:
            self._notify_tray(
                f"Found {len(leftovers)} half-copied file(s) from an interrupted copy. "
                "Nothing was deleted. Tray → Copy diagnostics for your admin.",
                "ccsync-companion")

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
                    self._notify_tray(
                        "Your CCSync sign-in has expired, so syncing has stopped. "
                        "Right-click the tray icon → Sign in…", "ccsync-companion")
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
        self._stop_event.set()
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
        for power_guard, label in ((guard, "shutdown"), (awake, "keep-awake"),
                                   (root, "sync-drive")):
            if power_guard is None:
                continue
            try:
                power_guard.stop()
            except Exception:
                log.exception("failed to stop the %s guard", label)
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
        # CORE-H6).
        just_upgraded = upgrade_mod.note_version_start(self._state_dir)

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
            # a broken exe and no way back (AUDIT_2 CORE-H6). Deferred again
            # by 60 s so an AV hold on the freshly-renamed file has time to
            # clear, and retried on every subsequent start regardless.
            cleanup_timer = threading.Timer(60.0, upgrade_mod.cleanup_old_exe)
            cleanup_timer.daemon = True
            cleanup_timer.start()

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
    try:
        app = CompanionApp(cfg)
        app.run()
    except Exception:
        log.exception("ccsync-companion crashed during startup/run")
        raise


if __name__ == "__main__":
    run()
