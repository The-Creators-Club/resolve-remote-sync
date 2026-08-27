"""Sequencer -- drives Lane A/B/C to sync the dashboard-selected projects ONE
AT A TIME, in the server-supplied order (selection.py fetches that order;
this module executes it). Managed-mode only: app.py does not construct/start
this when the dashboard integration is disabled (selection_client.enabled is
False), though start() also guards against it directly.

The server decides WHICH projects are shared to this editor (server-side
unshare is the authority for unselected Syncthing folders) -- this module's
only job is ordering and pacing: run lanes A and B for one project's
subtree, then give Lane C (Syncthing) a turn with every other selected
folder paused, wait for it to settle (or time out), and move on.

Fault-isolated throughout, matching every other background loop in this
package (reporter.py, sync/*_lane.py): a failing step logs and the loop
moves on, it never dies. All waiting goes through small interruptible-wait
helpers built on threading.Event.wait() (the stop_event.wait() idiom used
by RcloneLane/SyncthingLane's periodic loops), so tests can drive the loop
with tiny real intervals instead of mocking time.
"""

from __future__ import annotations

import inspect
import logging
import threading
import time
import urllib.error
from collections import deque
from pathlib import Path
from typing import Any, Optional

from .. import config as config_mod
from ..selection import SelectionClient
# A LANE's error state, not one of this module's own STATE_* (which describe
# the sequencer itself) -- hence the alias.
from .base import STATE_ERROR as STATE_ERROR_LANE
from .rclone_lane import clone_directory_tree
from .borrowed_folders import BorrowedFolderManager
from .repath import ProjectRepather, _default_move, normalized_safe_rel
from .shared_folders import SharedFolderManager
from .syncthing_admin import (
    STIGNORE_LINES,
    SyncthingAdmin,
    is_restricted,
    missing_ignore_lines,
)

log = logging.getLogger("ccsync.sync.sequencer")

STATE_STARTUP = "startup"
STATE_NO_SELECTION = "no_selection"
STATE_RUNNING = "running"
STATE_BETWEEN_PASSES = "between_passes"
STATE_PAUSED = "paused"
STATE_STOPPED = "stopped"

# How often folder_status() is polled while waiting for a project's Lane C
# sync to settle (needTotalItems == 0). A constructor override exists so
# tests aren't stuck waiting on real 5-second ticks.
DEFAULT_FOLDER_STATUS_POLL_SECONDS = 5.0

# Granularity of the (rare) waits that still have to poll a predicate rather
# than block on an event.
_POLL_CHUNK_SECONDS = 0.05

PROJECTS_PREFIX = "Projects/"

# Lane C pacing schemes (AUDIT_2 P4/C-1).
#   "none"   -- never pause a folder; Syncthing's own maxFolderConcurrency
#               paces the I/O. THE DEFAULT.
#   "rotate" -- the historical scheme: pause every other selected folder for
#               the duration of the current project's turn.
PAUSE_SCHEME_NONE = "none"
PAUSE_SCHEME_ROTATE = "rotate"

# How long a project's turn waits on lane C when nothing is being paused
# (ops-efficiency-3, 2026-08-21). Long enough that a project with a couple
# of small files finishes inside its own turn and the dashboard's
# current_project reads sensibly, short enough that a folder with a big
# backlog does not hold every other project's proxies for ten minutes.
DEFAULT_LANE_C_SETTLE_SECONDS = 30

# Idle backoff after a pass that moved nothing (ops-efficiency-2,
# 2026-08-21). A steady-state pass costs 3 rclone processes, 2 recursive
# SFTP listings and 3 local walks PER PROJECT -- ~300 SSH handshakes a pass
# for ten editors with ten projects each -- purely to discover that nothing
# changed. Multipliers on `sequencer_idle_seconds`, applied only while
# consecutive passes keep finding nothing, and reset to 1x by any evidence
# that something DID (a transfer, a selection change, a watcher event, a
# tray action). Capped rather than open-ended: lane B has no NAS-side change
# signal, so the backoff is also the worst-case latency of a proxy arriving.
IDLE_BACKOFF_STEPS = (1, 2, 5)

# What a per-turn read of a folder's .stignore found (SYNC-6, 2026-08-14).
# "missing" deliberately covers a read that failed as well as one that came
# back short: the re-assert is a fail-closed retry path, so not knowing means
# writing.
IGNORES_OK = "ok"
IGNORES_MISSING = "missing"
IGNORES_ABSENT = "absent"  # 404 -- this folder is not configured here at all


def _sort_by_position(selection: list[dict]) -> list[dict]:
    return sorted(selection, key=lambda item: item.get("position", 0))


def _item_is_valid(item: dict) -> bool:
    """A selection item usable for sync: rel_path must be a non-blank str,
    contained under local_root (repath.normalized_safe_rel -- a `..`, `\\` or
    drive-letter segment reaches lane A's SOURCE path, where
    `rclone copy C:\\ nas:...` would upload every video on the editor's C:
    drive; AUDIT_2 L-7), slug must be a non-blank str, and active (when
    present) must not be explicitly False. A dashboard row whose project
    record is gone (LEFT JOIN -> rel_path NULL) must never reach a path join
    -- str(None) == "None" would move the project directory to
    "...\\Projects\\None" (AUDIT D-4).

    slug is validated for the same reason rel_path is, one layer along: it
    becomes the SYNCTHING FOLDER ID, and _process_project's
    `str(item.get("slug"))` turned a NULL slug into the literal folder id
    "None" -- every pause/unpause/set_ignores/status call of that project's
    turn then addressed a folder called "None", and "None" stuck around
    forever as a key in the bookkeeping dicts.

    Goes through the SHARED normalize-then-validate helper: this used to
    validate the raw string while repath.py stripped a leading "/" first, so
    "/2026/CCT/Show" was repathed (directory moved, Syncthing re-pointed) and
    then never synced by lanes A/B (AUDIT_3 L-11)."""
    rel = item.get("rel_path")
    if not isinstance(rel, str) or not rel.strip():
        return False
    if normalized_safe_rel(rel) is None:
        return False
    slug = item.get("slug")
    if not isinstance(slug, str) or not slug.strip():
        return False
    if item.get("active") is False:
        return False
    if _item_sync_mode(item) is None:
        return False
    return True


def _item_rel(item: dict) -> Optional[str]:
    """The normalized, validated rel_path of a selection item (None when
    unusable). Every path built from a selection item goes through this so
    the string that reaches lane A's `Projects/<rel>` is the same one
    _rel_to_slug and repath.py agreed was safe."""
    return normalized_safe_rel(item.get("rel_path"))


# A tick's MODE (docs/UPLOAD_ONLY_TICK.md, dashboard 0.7.14 / companion
# 0.9.54). `full` is every lane; `upload_only` is lane A alone -- the editor
# has the footage backed up locally and wants the originals on the server
# without the project's proxies (lane B) or shared files (lane C) coming
# down. The server never shares the Syncthing folder with an upload-only
# machine, so lane C could not run for it even if this side tried.
SYNC_MODE_FULL = "full"
SYNC_MODE_UPLOAD_ONLY = "upload_only"


def _item_sync_mode(item: dict) -> Optional[str]:
    """The selection item's mode, or None when the value is not one this
    build knows. A missing or blank key is `full`: that is what every item
    meant before the key existed, and what a cached selection.json written
    by an older companion still carries. An UNKNOWN value fails closed --
    the item is not synced at all (see _item_is_valid) rather than guessed
    at: reading a mode this build has never heard of as `full` would start
    the very download the tick was meant to prevent, and reading it as
    upload-only would silently stop a project syncing."""
    raw = item.get("sync_mode")
    if raw is None:
        return SYNC_MODE_FULL
    if not isinstance(raw, str):
        return None
    value = raw.strip().lower()
    if not value:
        return SYNC_MODE_FULL
    if value in (SYNC_MODE_FULL, SYNC_MODE_UPLOAD_ONLY):
        return value
    return None


def _item_upload_only(item: dict) -> bool:
    return _item_sync_mode(item) == SYNC_MODE_UPLOAD_ONLY


def _include_is_valid(entry: object) -> Optional[dict]:
    """A selection item's `includes` entry (SHARED_FOLDERS_PLAN.md §4.2),
    validated to the same standard as the item itself -- the cached
    selection.json is a file on the editor's own disk, so nothing in it is
    trusted with a path. Returns {"subpath", "sub_rel", "lender_rel",
    "lender_slug"} or None. Fail closed, never widen: an entry that fails
    here is dropped, and a dropped entry syncs NOTHING extra (the borrowed
    dir simply is not run), which is the safe direction.

    Checks: subpath survives normalized_safe_rel (traversal, drive letters,
    leading slash), is at least lender + one sub segment deep, has no
    `proxy` segment (lane A's `- **/Proxy/**` is relative to the run root,
    so a run rooted inside Proxy/ would upload proxies as originals),
    lender_slug is a non-blank str, and sub_rel is the subpath's own tail
    (which is what makes lender_rel derivable)."""
    if not isinstance(entry, dict):
        return None
    sub = normalized_safe_rel(entry.get("subpath"))
    if sub is None:
        return None
    parts = sub.split("/")
    if len(parts) < 2:
        return None
    if any(seg.lower() == "proxy" for seg in parts):
        return None
    lender_slug = entry.get("lender_slug")
    if not isinstance(lender_slug, str) or not lender_slug.strip():
        return None
    sub_rel = normalized_safe_rel(entry.get("sub_rel"))
    if sub_rel is None or not sub.endswith("/" + sub_rel) or sub == sub_rel:
        return None
    lender_rel = sub[: -(len(sub_rel) + 1)]
    return {"subpath": sub, "sub_rel": sub_rel, "lender_rel": lender_rel,
            "lender_slug": lender_slug.strip()}


def _accepts_max_duration(fn: Any) -> bool:
    try:
        return "max_duration_seconds" in inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False


def _is_not_found(exc: BaseException) -> bool:
    """A Syncthing 404 -- "this folder isn't configured locally", i.e. the
    editor hasn't accepted it yet. Routine, not an error worth a traceback
    per project per pass (AUDIT_2 L-11)."""
    return isinstance(exc, urllib.error.HTTPError) and exc.code == 404


class Sequencer:
    """Fault-isolated daemon thread: syncs the dashboard's selected projects
    one at a time, in order, re-checking the selection between projects and
    between passes so server-side changes (add/remove/reorder) take effect
    without a companion restart."""

    def __init__(
        self,
        lane_a: Any,
        lane_b: Any,
        admin: SyncthingAdmin,
        selection: SelectionClient,
        cfg: dict[str, Any],
        folder_status_poll_seconds: float = DEFAULT_FOLDER_STATUS_POLL_SECONDS,
        now: Any = time.monotonic,
        clone_tree_fn: Any = clone_directory_tree,
        repather: Optional[ProjectRepather] = None,
        shared_folders: Optional[Any] = None,
        borrowed_folders: Optional[Any] = None,
        halted: Optional[Any] = None,
    ) -> None:
        self.lane_a = lane_a
        self.lane_b = lane_b
        self.admin = admin
        self.selection = selection
        self.cfg = cfg
        self.local_root = cfg.get("local_root", "")
        # The fleet-wide asset libraries (the LUT library). Not part of the
        # selection and not part of the rotation -- see sync/shared_folders.py
        # -- so the sequencer's only job here is to call reconcile() often
        # enough, INCLUDING on the no-selection path where nothing else runs.
        # `halted` is app.py's "is syncing stopped on this machine" predicate
        # (lane_guard.HaltState.active). Optional: a sequencer built without
        # one behaves as before, which is what every existing test assumes.
        self._halted = halted
        self.shared_folders = (
            shared_folders
            if shared_folders is not None
            else SharedFolderManager(admin, self.local_root, halted=halted)
        )
        # Lender folders this machine borrows from without ticking them
        # (SHARED_FOLDERS_PLAN.md §3.3) -- same lifecycle as the asset
        # libraries: not in the rotation, reconciled once per pass, paused
        # by a halt. Built lazily around borrowed_lenders() so the manager
        # always sees the freshest selection-derived set.
        self.borrowed_folders = (
            borrowed_folders
            if borrowed_folders is not None
            else BorrowedFolderManager(
                admin, self.local_root, lenders_fn=self.borrowed_lenders,
                selected_slugs_fn=self.expected_folder_slugs,
                halted=halted, move_dir=_default_move)
        )
        # EVERY numeric here goes through config.coerce_numeric/coerce_count.
        # A bare float(cfg.get(...)) raises on a hand-edited
        # `selection_poll_interval = "fast"`, and the Sequencer is built
        # inside CompanionApp.__init__ -- on the windowed exe that is a
        # process that vanishes with no tray and no log line (AUDIT_2
        # CORE-M4's family; validate_config() reports the bad value).
        self.selection_poll_interval = config_mod.coerce_numeric(
            cfg, "selection_poll_interval", 60
        )
        self.project_rotation_seconds = config_mod.coerce_numeric(
            cfg, "project_rotation_seconds", 600
        )
        self.sequencer_idle_seconds = config_mod.coerce_numeric(
            cfg, "sequencer_idle_seconds", 60
        )
        # Base rig with direct NAS access reads proxies off the share; no
        # point mirroring them locally (and it fills the system drive).
        self.lane_b_enabled = bool(cfg.get("lane_b_enabled", True))
        # AUDIT_2 C-1/P7: lanes A and B are opposite directions over disjoint
        # file sets (**/Proxy/** vs everything else) in separate processes,
        # and WireGuard/Tailscale is full duplex -- so running them serially
        # left one direction idle for the whole of the other's transfer.
        # Toggleable because upstream and downstream now compete for the
        # editor's CPU and disk.
        self.concurrent_lanes = bool(cfg.get("concurrent_lanes", True))
        # AUDIT_2 C-3/P10: the directory-structure clone is a full remote
        # listing per project per pass and is entirely redundant in steady
        # state. Run it on the first pass, after a repath, and every N passes
        # thereafter. 1 => every pass; 0 => NEVER (only the forced,
        # post-repath clone still runs).
        #
        # `int(cfg.get(..., 10) or 1)` turned a configured 0 into 1, i.e. the
        # exact OPPOSITE of what config.py's comment and config.example.toml
        # both document ("0 = never re-clone") -- an operator disabling the
        # per-project remote listing got it on every single pass instead
        # (AUDIT_3 M-6). 0 now means disabled, the same way
        # orphan_scan_every_n_passes has always treated it.
        self.structure_clone_every_n_passes = config_mod.coerce_count(
            cfg, "structure_clone_every_n_passes", 10
        )
        # AUDIT_2 P4: see PAUSE_SCHEME_*. Anything unrecognised falls back to
        # the new default rather than silently reviving the rescan storm.
        scheme = str(cfg.get("lane_c_pause_scheme", PAUSE_SCHEME_NONE) or "").strip().lower()
        if scheme not in (PAUSE_SCHEME_NONE, PAUSE_SCHEME_ROTATE):
            log.warning(
                "sequencer: unknown lane_c_pause_scheme %r -- using %r",
                scheme, PAUSE_SCHEME_NONE,
            )
            scheme = PAUSE_SCHEME_NONE
        self.lane_c_pause_scheme = scheme
        # What replaces the pause scheme's pacing. 0 disables the write.
        self.lane_c_max_folder_concurrency = config_mod.coerce_count(
            cfg, "lane_c_max_folder_concurrency", 2
        )
        # The lane C settle with the pause scheme OFF -- see
        # _lane_c_wait_budget (ops-efficiency-3). coerce_count, not
        # coerce_numeric: 0 is a legal value here and means "restore the old
        # behaviour" (wait the whole project_rotation_seconds either way),
        # which coerce_numeric's positive-only gate would reject.
        self.lane_c_settle_seconds = config_mod.coerce_count(
            cfg, "lane_c_settle_seconds", DEFAULT_LANE_C_SETTLE_SECONDS
        )
        # AUDIT_2 P8/P15/C-7: count orphan .partial files on the NAS every N
        # passes and REPORT them. Never deletes. 0 disables the scan.
        self.orphan_scan_every_n_passes = config_mod.coerce_count(
            cfg, "orphan_scan_every_n_passes", 20
        )
        self.folder_status_poll_seconds = folder_status_poll_seconds
        self._now = now
        self._clone_tree_fn = clone_tree_fn
        # Editor-side half of server-side project moves (sync/repath.py).
        self.repather = repather if repather is not None else ProjectRepather(
            admin, self.local_root
        )

        self._stop_event = threading.Event()
        self._resume_event = threading.Event()
        self._resume_event.set()  # not paused by default
        self._wake_event = threading.Event()
        # "Something changed -- re-evaluate now." Set by stop(), pause(),
        # resume(), notify_change() and trigger_pass_now(); every wait below
        # blocks on THIS for its whole remaining timeout instead of waking
        # 20x/s forever (AUDIT_2 L-18). Distinct from _wake_event, which is a
        # latched "run a pass now" signal that only _wait_or_wake consumes.
        self._interrupt = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        self._state = STATE_STARTUP
        self._current_slug: Optional[str] = None
        self._current_position = 0
        self._current_total = 0
        self._queue_slugs: list[str] = []
        self._rel_to_slug: dict[str, str] = {}
        self._slug_to_item: dict[str, dict] = {}
        # Slugs ticked upload-only (docs/UPLOAD_ONLY_TICK.md): in
        # _slug_to_item and rel_to_slug like any other project (lane A, the
        # express watchdog and the manifest all need them), but never a
        # Syncthing folder of this machine's.
        self._upload_only_slugs: set[str] = set()
        # Borrowed folders (SHARED_FOLDERS_PLAN.md §3.1). Kept OUT of
        # _rel_to_slug: rel_to_slug feeds _selected_project_rels (the
        # manifest and proxy-scan scope), which must stay the selection's
        # own rels. known_rels()/notify_change read both maps.
        self._borrowed_by_slug: dict[str, list[dict]] = {}
        self._borrowed_rel_to_slug: dict[str, str] = {}
        # Lenders NOT in the selection whose folder this machine borrows
        # from: lender_slug -> {"rel", "subs", "borrowers"} -- the WP3
        # borrowed-folder manager's input, and what a halt must also pause.
        self._borrowed_lenders: dict[str, dict] = {}
        self._queue: Optional[deque] = None  # live remaining-items during a pass; None otherwise
        self._last_selection: list[dict] = []
        self._no_selection_reason = ""
        # True only while _lane_c_turn is actively pausing/unpausing folders
        # -- stop()/pause() wait for this to clear before their own
        # unpause-everything sweep, so an in-flight sweep can't re-pause a
        # folder AFTER that sweep already ran (AUDIT §4).
        self._in_lane_c_turn = False
        # Set whenever _in_lane_c_turn is False, so the wait below can block
        # on an event instead of polling.
        self._lane_c_idle = threading.Event()
        self._lane_c_idle.set()
        # Slugs already processed in the current pass -- notify_change must
        # not re-prepend them (AUDIT_2 L-10).
        self._processed_slugs: set[str] = set()
        # Slugs whose .stignore is NOT known to be in place -- either
        # accept_folder() failed part-way (the folder exists in Syncthing but
        # its ignores never landed) or this turn's re-assertion failed. Such
        # a folder must stay paused, including through the leak-recovery
        # sweeps, which would otherwise undo the protection a few seconds
        # later (AUDIT_2 L-3). Cleared ONLY by a set_ignores that actually
        # returned, and pruned when a slug leaves the selection: a stale
        # entry excluded a slug from every _unpause_all sweep forever.
        self._ignores_unconfirmed: set[str] = set()
        # How many times each project has been processed since its last
        # structure clone (AUDIT_2 C-3). Missing == never cloned.
        self._clone_ages: dict[str, int] = {}
        # Same, for the orphan .partial scan.
        self._orphan_ages: dict[str, int] = {}
        # Throttle for selection.get(): it does a live HTTP fetch AND
        # rewrites selection.json on EVERY call, and the lane C wait loop
        # called it every 5 s -- ~120 requests + 120 disk writes per project
        # per pass per editor (AUDIT_2 P11/L-5).
        self._selection_cache: Optional[tuple[float, Any, str]] = None
        # Files the pass in flight has moved, and how far the between-passes
        # wait has backed off (ops-efficiency-2). Plain attributes: both are
        # touched from the sequencer thread, and a torn read would cost one
        # wait of the wrong length.
        self._pass_moved = 0
        self._idle_step = 0
        # Set when a project's lanes A and B BOTH failed -- "the NAS is not
        # reachable from here" (ops-efficiency-4). Cleared at the head of
        # each pass.
        self._offline_pass = False
        # Folders THIS sequencer paused and has not released yet -- lets the
        # pre-lane release below issue only the PATCHes that are actually
        # needed instead of a blind sweep over the whole selection (each one
        # makes Syncthing commit its config and restart the folder).
        self._paused_by_us: set[str] = set()

    # -- lifecycle -----------------------------------------------------
    def start(self) -> None:
        if not self.selection.enabled:
            return
        if self._thread is not None and self._thread.is_alive():
            # RcloneLane.start() and SyncthingLane.start() both got this
            # guard in round 1; the sequencer did not. stop() joins with
            # timeout=10, which an in-flight 40 GB lane A run always
            # outlasts -- and start() then cleared _stop_event and spawned
            # thread #2 while #1 was still looping. Two sequencers race:
            # both drive _lane_c_turn, so Syncthing folders flip
            # paused/unpaused several times a second and rotation collapses
            # entirely. Every subsequent sign-out/sign-in added another
            # permanent thread (AUDIT_2 L-1, reproduced live).
            log.warning(
                "sequencer: start() while a sequencer thread is still alive -- "
                "ignoring rather than spawning a second one"
            )
            return
        self._stop_event.clear()
        self._interrupt.clear()
        self._resume_event.set()
        self._arm_lanes()
        self._thread = threading.Thread(target=self._run, name="ccsync-sequencer", daemon=True)
        self._thread.start()

    def _arm_lanes(self) -> None:
        """Clear the stop latch on the lanes this sequencer drives.

        SYNC-1 (2026-08-14): in managed mode both rclone lanes are STOPPED on
        sign-out (app._stop_lanes), but only lane A is re-armed on the way
        back in -- start_watchdog_only() installs a fresh stop event, while
        lane B has no equivalent entry point at all, because run_once() from
        here IS its whole drive. A latched lane B returned its stale
        LaneStatus from every subsequent run_once() for the life of the
        process: no proxy was ever downloaded again after one
        sign-out/sign-in or token expiry, and the fleet grid kept showing the
        lane idle-and-green. Arming from HERE rather than from app.py keeps
        "the sequencer drives these lanes" and "the sequencer un-latches
        them" in the same place.

        Best-effort per lane: `arm` is not part of the LaneAdapter contract
        (a test double, or a future adapter with no stop latch, need not have
        it), and a lane that cannot be armed must not stop the sequencer from
        starting -- the pass would still run every other lane.
        """
        for lane in (self.lane_a, self.lane_b):
            arm = getattr(lane, "arm", None)
            if arm is None:
                continue
            try:
                arm()
            except Exception:
                log.exception(
                    "sequencer: could not re-arm lane %s", getattr(lane, "name", lane)
                )

    def stop(self) -> None:
        self._stop_event.set()
        self._wake_event.set()
        self._interrupt.set()
        # JOIN first, THEN unpause: unpausing before the worker has actually
        # stopped let an in-flight _lane_c_turn re-pause every non-current
        # project right after this sweep ran, leaving them stuck paused
        # until the next launch's _startup_unpause (AUDIT §4).
        self._wait_for_lane_c_turn_idle(timeout=5.0)
        if self._thread is not None:
            self._thread.join(timeout=10)
        self._unpause_all(self._last_selection)
        with self._lock:
            self._state = STATE_STOPPED
            self._current_slug = None
            self._queue_slugs = []

    def pause(self) -> None:
        self._resume_event.clear()
        self._interrupt.set()
        # Same ordering concern as stop(): give an in-flight lane-C pause
        # sweep a bounded window to notice and bail (or finish) before the
        # unpause-everything sweep below runs.
        self._wait_for_lane_c_turn_idle(timeout=5.0)
        self._unpause_all(self._last_selection)

    def resume(self) -> None:
        self._resume_event.set()
        self._wake_event.set()
        self._interrupt.set()
        self._wake_up_now()

    def _wait_for_lane_c_turn_idle(self, timeout: float) -> None:
        """Bounded, non-blocking-past-timeout wait for _lane_c_turn's
        folder-pause sweep to finish. Never waits for the whole pass (e.g.
        _wait_for_folder_sync) -- only for the part that actually mutates
        other folders' paused state, which is what could otherwise race
        _unpause_all() below.

        Blocks on an event rather than the bare time.sleep() poll it used to
        run (AUDIT_2 L-18)."""
        if self._thread is None or not self._thread.is_alive():
            return
        self._lane_c_idle.wait(timeout)

    def trigger_pass_now(self) -> None:
        self._wake_event.set()
        self._interrupt.set()
        # An explicit "sync now" is the clearest possible evidence that the
        # idle backoff has to go back to the normal cadence
        # (ops-efficiency-2).
        self._wake_up_now()

    # -- introspection -----------------------------------------------------
    @property
    def current_slug(self) -> Optional[str]:
        with self._lock:
            return self._current_slug

    @property
    def queue_slugs(self) -> list[str]:
        with self._lock:
            return list(self._queue_slugs)

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    @property
    def rel_to_slug(self) -> dict[str, str]:
        with self._lock:
            return dict(self._rel_to_slug)

    def status_detail(self) -> str:
        with self._lock:
            state = self._state
            current_slug = self._current_slug
            position = self._current_position
            total = self._current_total
            slug_to_item = dict(self._slug_to_item)
            no_selection_reason = self._no_selection_reason

        if state == STATE_STARTUP:
            return "starting up"
        if state == STATE_NO_SELECTION:
            return f"no selection ({no_selection_reason})" if no_selection_reason else "no selection"
        if state == STATE_RUNNING:
            item = slug_to_item.get(current_slug or "", {})
            label = item.get("label") or item.get("rel_path") or current_slug or "?"
            verb = "uploading" if _item_upload_only(item) else "syncing"
            return f"{verb} {label} ({position}/{total})"
        if state == STATE_BETWEEN_PASSES:
            return "idle between passes"
        if state == STATE_PAUSED:
            return "paused"
        return "stopped"

    def known_rels(self) -> list[str]:
        """Selected-project rel paths (any depth), PLUS borrowed-folder rels
        -- feeds lane A's watchdog project attribution
        (rclone_lane.known_rels_fn, longest known rel wins), so a file
        dropped into a borrowed dir is express-uploaded under the LENDER's
        NAS path rather than misattributed or ignored."""
        with self._lock:
            return list(self._rel_to_slug) + list(self._borrowed_rel_to_slug)

    def rel_to_slug_with_borrowed(self) -> dict[str, str]:
        """rel -> slug over selection AND borrowed rels (a borrowed rel maps
        to its BORROWER: that is whose turn ran it). For status reporting;
        _selected_project_rels keeps reading rel_to_slug, which deliberately
        stays selection-only (manifest and proxy-scan scope, §3.1)."""
        with self._lock:
            merged = dict(self._borrowed_rel_to_slug)
            merged.update(self._rel_to_slug)
            return merged

    def expected_folder_slugs(self) -> list[str]:
        """The Syncthing folder IDs (== project slugs) of the current
        selection, in selection order. Thread-safe.

        Wired into SyncthingLane as `expected_folder_ids_fn`: lane C had no
        way to learn which folders it was supposed to be syncing, so it
        reported idle/queued=0/last_sync=now unconditionally for every
        managed editor (AUDIT_2 L-6/UX-3).

        Upload-only projects are NOT folders of this machine's, so they are
        left out: lane C would otherwise report itself behind on a folder
        the server never shares with it."""
        with self._lock:
            return [s for s in self._slug_to_item if s not in self._upload_only_slugs]

    def upload_only_slugs(self) -> set[str]:
        """The slugs ticked upload-only in the current selection."""
        with self._lock:
            return set(self._upload_only_slugs)

    def halt_folder_ids(self) -> list[str]:
        """EVERY lane C folder a halt has to pause: the selected projects
        plus the fleet-wide asset libraries.

        The halt walked expected_folder_slugs() alone, which is the project
        selection -- so a fleet halt pressed because a bad ingest or a mass
        rename in `Assets/B-roll Archive` was spreading left the B-roll,
        music and LUT folders syncing on every machine in the fleet while
        every tray said nothing was (sync-safety-2, 2026-08-21). Deliberately
        NOT folded into expected_folder_slugs: that list is also lane C's
        "which folders am I behind on" input, and the asset libraries are not
        part of the rotation it describes."""
        ids = self.expected_folder_slugs()
        seen = set(ids)
        try:
            extra = list(self.shared_folders.folder_ids()) if self.shared_folders else []
        except Exception:
            log.debug("sequencer: could not list the shared asset folders", exc_info=True)
            extra = []
        # ...plus the lender folders this machine borrows from without
        # having them ticked (SHARED_FOLDERS_PLAN.md §5): they are never in
        # ordered_selected, so nothing else would pause them on a halt. A
        # lender folder not (yet) configured locally 404s on the pause,
        # which the halt already tolerates.
        with self._lock:
            extra += list(self._borrowed_lenders)
        for folder_id in extra:
            if folder_id and folder_id not in seen:
                seen.add(folder_id)
                ids.append(folder_id)
        return ids

    def release_for_halt(self) -> None:
        """Release lane C folders after a halt is lifted, through the SAME
        filter the leak-recovery sweep uses.

        The halt's own release PATCHed `paused: false` onto every folder it
        had paused, which includes a folder deliberately left paused because
        its .stignore never landed -- putting an unfiltered `sendreceive`
        folder online, offering every original and every Proxy/ file
        (sync-safety-4, 2026-08-21). _unpause_all already knows not to do
        that, and it also skips the invalid/de-selected items SYNC-2 is
        about. The shared asset folders come back through their own
        reconcile, which checks their ignores the same way."""
        self._unpause_all(self._last_selection)
        self._reconcile_shared_folders()
        # Borrowed lender folders come back the same way the asset libraries
        # do: through their own reconcile, which re-checks the restricted
        # ignores before any unpause.
        self._reconcile_borrowed_folders()

    # -- watcher hand-off -----------------------------------------------------
    def notify_change(self, rel: str) -> None:
        """rel is "Projects/<year>/<series>/<project>" (from RcloneLane's
        on_change callback). Promotes the matching selected project to be
        next-after-current if it isn't already current -- no preemption of
        whatever is running right now."""
        rel_path = rel[len(PROJECTS_PREFIX):] if rel.startswith(PROJECTS_PREFIX) else rel
        with self._lock:
            # A write in a borrowed dir promotes the BORROWER: it is the
            # borrower's turn that runs the borrowed subpath's lanes.
            slug = (self._rel_to_slug.get(rel_path)
                    or self._borrowed_rel_to_slug.get(rel_path))
            if not slug or slug == self._current_slug:
                return
            if slug in self._processed_slugs:
                # Already done this pass. Lane A's watchdog fires per write
                # chunk, so a card ingest into project 1 of 5 produced
                # thousands of events a minute, each re-prepending project 1
                # -- projects 3-5 then never reached their lane C turn for
                # the whole ingest (AUDIT_2 L-10). It will be picked up at
                # the head of the NEXT pass; _wake_event below still shortens
                # the wait between passes.
                self._wake_event.set()
                self._interrupt.set()
                self._wake_up_now()
                return
            item = self._slug_to_item.get(slug)
            if item is None:
                return
            if self._queue is not None:
                self._queue = deque(i for i in self._queue if i.get("slug") != slug)
                self._queue.appendleft(item)
                self._queue_slugs = [i.get("slug") for i in self._queue]
        self._wake_event.set()
        self._interrupt.set()
        # The editor just wrote a file in a selected project: whatever the
        # idle backoff had decided, the next pass is worth running at the
        # normal cadence (ops-efficiency-2).
        self._wake_up_now()

    # -- main loop -----------------------------------------------------
    def _run(self) -> None:
        with self._lock:
            self._state = STATE_STARTUP
        self._startup_unpause()
        while not self._stop_event.is_set():
            if not self._resume_event.is_set():
                self._park_paused()
                continue

            # BEFORE the selection check, deliberately: an editor with zero
            # projects ticked still gets the shared libraries, and that is
            # exactly the branch below that continues without doing anything
            # else. Fault-isolated -- reconcile() never raises, but a broken
            # library must not be able to stop project syncing either way.
            self._reconcile_shared_folders()

            selection, source = self._selection_get()
            if not selection:
                with self._lock:
                    self._state = STATE_NO_SELECTION
                    self._current_slug = None
                    self._queue_slugs = []
                    self._no_selection_reason = self._describe_no_selection(selection, source)
                if self._wait_or_wake(self.selection_poll_interval):
                    break
                continue

            self._update_known_selection(selection)
            # AFTER the selection update, deliberately: the borrowed-lender
            # set is derived from it, and reconciling on the stale set would
            # accept or drop a lender one pass late.
            self._reconcile_borrowed_folders()
            self._reconcile_paths(selection)
            self._check_remote_root()
            self._run_pass(selection)

            if self._stop_event.is_set() or not self._resume_event.is_set():
                continue

            with self._lock:
                self._state = STATE_BETWEEN_PASSES
                self._current_slug = None
                self._queue_slugs = []
            self._unpause_all(self._last_selection)
            self._note_pass_finished()
            if self._wait_or_wake(self._idle_seconds()):
                break

        with self._lock:
            self._state = STATE_STOPPED
            self._current_slug = None
            self._queue_slugs = []

    def _check_remote_root(self) -> None:
        """Ask lane B to probe `remote_root` itself, once per process.

        sync-safety-5 (2026-08-21): the breaker's marker-directory rule only
        applies to the whole-tree scope, and in managed mode every pass names
        a project subpath -- so the "is remote_root actually the tree" check
        SYNC_SAFETY.md credits the fleet with has never run on it. A
        remote_root pointing at a stale copy of the tree (a backup dataset, a
        snapshot clone mounted for a restore drill) passes every per-project
        probe and then trashes every proxy newer than the copy. Never raises,
        and never blocks the pass: the lane parks itself if the breaker
        trips."""
        probe = getattr(self.lane_b, "check_remote_root", None)
        if probe is None or not self.lane_b_enabled:
            return
        try:
            probe()
        except Exception:
            log.debug("sequencer: the remote_root probe failed", exc_info=True)

    def _reconcile_shared_folders(self) -> None:
        """Keep the fleet-wide asset libraries online. Never raises."""
        if self.shared_folders is None:
            return
        try:
            self.shared_folders.reconcile()
        except Exception:
            log.debug("sequencer: shared folder reconcile failed", exc_info=True)

    def _reconcile_borrowed_folders(self) -> None:
        """Keep the borrowed lender folders accepted, restricted and online
        (and drop the ones no borrower needs). Never raises."""
        if self.borrowed_folders is None:
            return
        try:
            self.borrowed_folders.reconcile()
        except Exception:
            log.debug("sequencer: borrowed folder reconcile failed", exc_info=True)

    @staticmethod
    def _describe_no_selection(selection: Optional[list[dict]], source: str) -> str:
        if selection is None:
            if source == "none":
                return "dashboard unreachable, no cache"
            return "dashboard unreachable"
        return "zero projects selected"

    # -- selection access -----------------------------------------------------
    def _selection_get(self) -> tuple[Any, str]:
        """selection.get(), remembering the result for later throttled reads.

        The unthrottled path -- used where a fresh answer is worth a request
        (once per pass, once per project)."""
        result = self.selection.get()
        self._selection_cache = (self._now(), result[0], result[1])
        return result

    def _selection_get_throttled(self) -> tuple[Any, str]:
        """A selection read that costs nothing more than once per
        `selection_poll_interval`.

        selection.get() is not a cheap accessor: it does a live HTTP fetch to
        the dashboard AND rewrites selection.json on every success. Called
        from the lane C poll loop that runs every 5 s for up to a 600 s turn,
        that was ~120 requests + 120 disk writes per project per pass per
        editor -- roughly 1 req/s against the dashboard ON THE NAS precisely
        while transfers are running, and a truncate-then-write window in
        which a killed companion leaves a zero-byte selection.json
        (AUDIT_2 P11/L-5).

        The proper fix is a TTL inside selection.py (that module's owner);
        this is the caller-side half, and it is what makes the poll loop
        stop hammering it in the meantime."""
        cached = self._selection_cache
        if cached is not None and (self._now() - cached[0]) < self.selection_poll_interval:
            return cached[1], cached[2]
        return self._selection_get()

    # -- startup / pause -----------------------------------------------------
    def _apply_lane_c_pacing(self) -> None:
        """With the pause scheme off, Syncthing itself has to pace lane C --
        that is what maxFolderConcurrency 1-2 does, and it buys the pacing
        WITHOUT ~1000 config commits and ~180 folder rescans an hour
        (AUDIT_2 P4/C-1/§4.2). Fault-isolated: an older Syncthing without
        the endpoint must not stop the sequencer."""
        if self.lane_c_pause_scheme != PAUSE_SCHEME_NONE:
            return
        if self.lane_c_max_folder_concurrency <= 0:
            return
        try:
            self.admin.ensure_max_folder_concurrency(self.lane_c_max_folder_concurrency)
        except Exception:
            log.debug(
                "sequencer: could not set maxFolderConcurrency -- leaving Syncthing's default",
                exc_info=True,
            )

    def _startup_unpause(self) -> None:
        """Leak recovery: best-effort unpause every folder in the cached
        selection, in case a previous run crashed mid-pass with some
        folders left paused.

        Runs REGARDLESS of the pause scheme -- with the scheme off this is
        the only thing that releases a folder an older companion (or a
        crashed rotate-scheme pass) left paused, and a folder left paused
        means lane C silently carries nothing for that project.

        Every folder is VERIFIED against the live .stignore before it is
        released -- see _verify_startup_ignores."""
        self._apply_lane_c_pacing()
        cached: Optional[list[dict]] = None
        try:
            cached = self.selection.load_cached()
        except Exception:
            log.exception("sequencer: failed to load cached selection for startup unpause")
        if cached:
            self._update_known_selection(cached)
            self._verify_startup_ignores(cached)
            self._unpause_all(cached)

    def _verify_startup_ignores(self, selection: list[dict]) -> None:
        """One GET /rest/db/ignores per selected folder, at startup, BEFORE
        the leak-recovery sweep releases anything.

        Neither latch that protects a half-filtered folder survives the
        process: _ignores_unconfirmed here and
        SyncthingAdmin._ignores_unconfirmed are both in-memory. So a
        companion killed between accept_folder's folder-config write and its
        set_ignores -- or one whose last run ended with the B5 re-assert
        still failing -- came back up knowing nothing, and _unpause_all
        released a `sendreceive` folder with no .stignore. Lane C then
        indexes and offers every .braw/.mov original and the whole Proxy/
        tree bidirectionally, until that project's first turn re-asserts the
        ignores: up to a full rotation x N projects.

        Verify-and-latch only; it deliberately does NOT re-assert here.
        _reassert_folder_policy at the head of each project's lane C turn is
        already the retry path, it runs under the same fault isolation as
        everything else in a turn, and re-asserting N folders inline would
        put N config commits (each of which restarts and rescans a folder)
        between launch and the first byte of sync.

        A fetch failure counts as unconfirmed, matching _maybe_auto_accept's
        fail-closed posture: waiting one rotation for a folder whose
        filtering we could not read is cheap, putting an unfiltered
        sendreceive folder online is not. A 404 is the exception -- that
        folder is not configured locally at all, so there is nothing to run
        unfiltered and the unpause that follows 404s just as harmlessly."""
        getter = getattr(self.admin, "get_ignores", None)
        if getter is None:  # an admin double that predates the getter
            return
        for index, item in enumerate(selection):
            if self._stop_event.is_set():
                # SYNC-8 (2026-08-11): verification costs one GET per folder
                # at up to the read timeout each, so a quit/sign-out/config
                # reload lands inside it routinely -- and BOTH sweeps that
                # follow (_startup_unpause's and stop()'s) run over the WHOLE
                # selection, releasing folders this loop never reached. Not
                # yet verified IS unconfirmed; the next turn's re-assert
                # clears it.
                self._latch_unverified(selection[index:])
                return
            if not _item_is_valid(item) or _item_upload_only(item):
                continue
            slug = str(item.get("slug"))
            try:
                fetched = getter(slug)
            except Exception as exc:
                if _is_not_found(exc):
                    log.debug("sequencer: folder %s not configured locally yet", slug)
                    continue
                log.warning(
                    "sequencer: could not read folder %s's ignores at startup (%s) -- "
                    "treating it as unfiltered and leaving it paused until a re-assert "
                    "lands", slug, exc,
                )
                with self._lock:
                    self._ignores_unconfirmed.add(slug)
                continue
            missing = missing_ignore_lines(fetched)
            if not missing and not is_restricted(fetched):
                continue
            if not missing:
                # A SELECTED folder still carrying a borrowed-folder
                # restriction: the editor just ticked a lender they were
                # borrowing from (SHARED_FOLDERS_PLAN.md §3.3). The
                # missing-lines check is a superset test, which the
                # restricted list passes -- but online it would sync only
                # the borrowed subtree while the tick promises the project.
                log.warning(
                    "sequencer: folder %s carries a restricted (borrowed-folder) "
                    ".stignore but is now selected -- leaving it paused until the full "
                    "ignore list lands", slug)
                with self._lock:
                    self._ignores_unconfirmed.add(slug)
                continue
            # One line per unconfirmed folder, with the reason: a folder that
            # verifies clean must cost nothing and say nothing.
            log.warning(
                "sequencer: folder %s is missing %d of its %d ignore patterns (e.g. %s) "
                "-- leaving it paused until a re-assert lands rather than releasing an "
                "unfiltered sendreceive folder",
                slug, len(missing), len(STIGNORE_LINES), ", ".join(missing[:3]),
            )
            with self._lock:
                self._ignores_unconfirmed.add(slug)

    def _latch_unverified(self, items: list[dict]) -> None:
        """Latch every still-unverified folder as unconfirmed (SYNC-8).

        Only the items _item_is_valid accepts: _unpause_all skips the rest
        outright (SYNC-2), so latching them would be bookkeeping nothing
        reads. A folder that is not configured locally at all latches too --
        its unpause 404s just as harmlessly as its GET would have."""
        slugs = {str(item.get("slug")) for item in items
                 if _item_is_valid(item) and not _item_upload_only(item)}
        if not slugs:
            return
        log.warning(
            "sequencer: stopped during the startup ignores verification -- %d folder(s) "
            "stay paused until a re-assert confirms their ignores", len(slugs),
        )
        with self._lock:
            self._ignores_unconfirmed |= slugs

    def _park_paused(self) -> None:
        with self._lock:
            self._state = STATE_PAUSED
            self._current_slug = None
            self._queue_slugs = []
        while not self._stop_event.is_set() and not self._resume_event.is_set():
            # Blocks on the interrupt (resume()/stop() both set it); the
            # bounded wait is only a safety net, not a poll.
            self._interrupt.clear()
            if self._stop_event.is_set() or self._resume_event.is_set():
                break
            self._interrupt.wait(1.0)
        if self._stop_event.is_set():
            return
        with self._lock:
            self._state = STATE_STARTUP
        self._startup_unpause()

    # -- selection bookkeeping -----------------------------------------------------
    def _update_known_selection(self, selection: list[dict]) -> None:
        rel_to_slug: dict[str, str] = {}
        slug_to_item: dict[str, dict] = {}
        upload_only: set[str] = set()
        for item in selection:
            if not _item_is_valid(item):
                continue
            rel = _item_rel(item)
            slug = item.get("slug")
            if rel and slug:
                rel_to_slug[rel] = slug
            if slug:
                slug_to_item[slug] = item
                if _item_upload_only(item):
                    upload_only.add(slug)
        borrowed_by_slug, borrowed_rel_to_slug, borrowed_lenders = \
            self._build_borrowed(selection, rel_to_slug, slug_to_item)
        # SYNC-2 (2026-08-11): the ignores latch is pruned against every slug
        # the selection MENTIONS, not just the usable ones. A project that
        # goes invalid without leaving the selection (archived -> rel_path
        # NULL) used to have its latch erased while the folder itself stayed
        # in Syncthing, unfiltered.
        slugged = {
            str(item.get("slug"))
            for item in selection
            if isinstance(item.get("slug"), str) and item.get("slug").strip()
        }
        with self._lock:
            # A mode flip is a change too: full -> upload-only must stop
            # lane B and the lane C turn on the next pass, and the reverse
            # must start them, without waiting out the idle backoff.
            changed = (set(slug_to_item) != set(self._slug_to_item)
                       or upload_only != self._upload_only_slugs
                       or borrowed_by_slug != self._borrowed_by_slug)
            self._rel_to_slug = rel_to_slug
            self._slug_to_item = slug_to_item
            self._upload_only_slugs = upload_only
            self._borrowed_by_slug = borrowed_by_slug
            self._borrowed_rel_to_slug = borrowed_rel_to_slug
            self._borrowed_lenders = borrowed_lenders
            self._last_selection = list(selection)
        if changed:
            # A tick or an untick is exactly the moment a backed-off
            # sequencer has to be prompt again (ops-efficiency-2).
            self._wake_up_now()
        self._prune_bookkeeping(set(slug_to_item), slugged)

    def _build_borrowed(
        self, selection: list[dict], rel_to_slug: dict[str, str],
        slug_to_item: dict[str, dict],
    ) -> tuple[dict[str, list[dict]], dict[str, str], dict[str, dict]]:
        """Validated, deduped borrowed-folder maps from the selection's
        `includes` (SHARED_FOLDERS_PLAN.md §3.1). The server already applies
        this policy (§4.2); re-applying it here is what stops a STALE CACHED
        selection.json -- or a tampered one -- from double-running a subtree
        or running one outside the declared scope. Fail closed: an invalid
        entry is dropped with one warning, never widened."""
        selected_rels = list(rel_to_slug)
        by_slug: dict[str, list[dict]] = {}
        borrowed_rel_to_slug: dict[str, str] = {}
        lenders: dict[str, dict] = {}
        claimed: list[str] = []
        for item in _sort_by_position(selection):
            if not _item_is_valid(item):
                continue
            slug = str(item.get("slug"))
            raw = item.get("includes")
            if not isinstance(raw, list):
                continue
            for entry in raw:
                if isinstance(entry, dict) and entry.get("covered"):
                    # The lender is selected on this machine: its own runs
                    # cover the subtree. The entry exists so the removal
                    # gate can see the relationship (app.removal_blockers).
                    continue
                inc = _include_is_valid(entry)
                if inc is None:
                    log.warning(
                        "sequencer: dropping an invalid includes entry on %s (%r) -- "
                        "refusing to build a path from it", slug, entry)
                    continue
                sub = inc["subpath"]
                # Equal to or under a selected project: the project's own
                # runs cover it. Under (or equal to) an include already
                # granted this pass: longest prefix wins.
                if any(sub == r or sub.startswith(r + "/") for r in selected_rels):
                    continue
                if any(sub == c or sub.startswith(c + "/") for c in claimed):
                    continue
                claimed.append(sub)
                by_slug.setdefault(slug, []).append(inc)
                borrowed_rel_to_slug[sub] = slug
                lender = inc["lender_slug"]
                if lender not in slug_to_item:
                    rec = lenders.setdefault(
                        lender, {"rel": inc["lender_rel"], "subs": [], "borrowers": []})
                    rec["subs"].append(inc["sub_rel"])
                    if slug not in rec["borrowers"]:
                        rec["borrowers"].append(slug)
        return by_slug, borrowed_rel_to_slug, lenders

    def _borrowed_includes(self, slug: str) -> list[dict]:
        with self._lock:
            return list(self._borrowed_by_slug.get(slug, []))

    def borrowed_lenders(self) -> dict[str, dict]:
        """lender_slug -> {"rel", "subs", "borrowers"} for lenders NOT in
        the selection -- the borrowed-folder manager's one input (WP3), and
        the extra folders a halt pauses."""
        with self._lock:
            return {k: dict(v) for k, v in self._borrowed_lenders.items()}

    def _prune_bookkeeping(
        self, live_slugs: set[str], selection_slugs: Optional[set[str]] = None
    ) -> None:
        """Drop per-slug bookkeeping for projects that are no longer
        selected. These dicts/sets are keyed by slug and were append-only, so
        every project an editor ever ticked stayed in memory for the life of
        the process -- and, worse, a stale _ignores_unconfirmed entry
        PERMANENTLY excluded that slug from every leak-recovery unpause sweep
        (_unpause_all), so re-ticking the project left its folder stuck
        paused with nothing to release it.

        _paused_by_us is deliberately NOT pruned here: it is the only record
        of a folder this sequencer actually paused, and _release_paused_folders
        is scoped to it rather than to the selection, so dropping an
        unselected slug would strand that folder paused forever. It drains
        itself instead -- on a successful unpause, and on a 404 (see
        _set_paused).

        `selection_slugs` is every slug the selection MENTIONS, valid or not
        (SYNC-2): the ignores latch is pruned against that wider set, because
        a project that goes invalid in place -- archived, so the dashboard's
        LEFT JOIN ships it with rel_path NULL -- still has a real, possibly
        unfiltered folder in Syncthing. It leaves the latch only when it
        leaves the selection entirely, which is the case the pruning was
        written for."""
        with self._lock:
            self._ignores_unconfirmed &= (
                live_slugs if selection_slugs is None else selection_slugs
            )
            for ages in (self._clone_ages, self._orphan_ages):
                # Borrowed-dir runs key these as "<slug>::<subpath>"
                # (SHARED_FOLDERS_PLAN.md §3.1): the part before "::" is the
                # borrower, and the key lives exactly as long as it does.
                for key in [k for k in ages
                            if k.split("::", 1)[0] not in live_slugs]:
                    ages.pop(key, None)

    def _ignores_unconfirmed_for(self, slug: str) -> bool:
        """Whether this folder's .stignore is NOT known to be in place, so no
        sweep may unpause it. Two sources: this sequencer's own latch, and
        the admin's half-accepted-folder record (SyncthingAdmin.accept_folder
        writes the folder config BEFORE it can set ignores, so a failure
        there leaves a real, existing, unfiltered folder -- B14)."""
        with self._lock:
            if str(slug) in self._ignores_unconfirmed:
                return True
        confirmed = getattr(self.admin, "ignores_confirmed", None)
        if confirmed is None:
            return False
        try:
            return not confirmed(slug)
        except Exception:
            log.debug("sequencer: ignores_confirmed(%s) failed", slug, exc_info=True)
            return False

    def _paused_folder_ids(self) -> Optional[set[str]]:
        """Which folders the local Syncthing has PAUSED right now, or None
        when that could not be read.

        SYNC-7 (2026-08-14): _unpause_all issued _set_paused(slug, False) --
        a config-mutating PATCH on the 30 s config_write_timeout, one per
        selected project -- after every pass, on every tray Resume, at every
        startup and on stop(), unconditionally. Under the default
        lane_c_pause_scheme ("none") this sequencer never pauses anything, so
        essentially all of those writes were no-ops that still took
        Syncthing's config lock, in a module whose own comments cite config
        churn as the reason the rotate scheme was retired. ONE read of the
        folder list answers "which of these is actually paused?" for the whole
        sweep, so steady state costs one GET and no config writes -- the same
        shape ensure_max_folder_concurrency and SharedFolderManager already
        use.

        Scoping the sweep to _paused_by_us (what _release_paused_folders does)
        was the other candidate and is wrong here: this sweep is also the only
        in-run release for a folder THIS process never paused -- accept_folder
        creates folders paused, an older companion or a crashed pass leaves
        them paused, and a hand-pause in the GUI is real. A state check keeps
        that coverage.

        None means "could not tell", and the caller then falls back to the
        unconditional sweep: a folder left paused is a project that silently
        syncs nothing at all, so this fails towards the write.
        """
        getter = getattr(self.admin, "get_folders", None)
        if getter is None:  # an admin double that predates the getter
            return None
        try:
            folders = getter()
        except Exception:
            log.debug(
                "sequencer: could not read the folder list for the unpause sweep",
                exc_info=True,
            )
            return None
        if not isinstance(folders, (list, tuple)):
            return None
        return {
            str(folder.get("id"))
            for folder in folders
            if isinstance(folder, dict) and folder.get("id") and folder.get("paused")
        }

    def _unpause_all(self, selection: list[dict]) -> None:
        releasable: list[str] = []
        for item in selection:
            # SYNC-2 (2026-08-11): this swept by RAW slug while
            # _verify_startup_ignores skips invalid items -- so the one folder
            # class nothing ever verified was also the one class released
            # unconditionally. The dashboard ships such rows routinely
            # (fetch_selections is a LEFT JOIN, so an archived project arrives
            # as {"slug": ..., "rel_path": None, "active": False}). Skip means
            # stay paused: an unverified `sendreceive` folder going online is
            # the L-3 outcome, and a de-selected project has nothing to sync.
            if not _item_is_valid(item):
                log.debug(
                    "sequencer: not releasing %r -- it is not a usable selection item",
                    item.get("slug"),
                )
                continue
            if _item_upload_only(item):
                # No folder of ours to release: the server does not share it
                # with this machine. If one is configured locally from an
                # earlier full tick, it stays exactly as it is.
                continue
            slug = item.get("slug")
            if self._ignores_unconfirmed_for(slug):
                # Deliberately excluded from every leak-recovery sweep: this
                # folder has no .stignore, so unpausing it means lane C
                # indexes and offers every .braw/.mov original and every
                # Proxy/ file. The next turn re-asserts the ignores and
                # releases it (AUDIT_2 L-3).
                log.debug(
                    "sequencer: folder %s stays paused -- its ignores never landed", slug
                )
                continue
            releasable.append(slug)

        if not releasable:
            return
        # One read for the whole sweep, and only for a sweep that has
        # something to release (SYNC-7).
        paused_ids = self._paused_folder_ids()
        for slug in releasable:
            if paused_ids is not None and str(slug) not in paused_ids:
                # Already running: no PATCH needed. The bookkeeping still has
                # to be kept honest, or a folder someone else released would
                # sit in _paused_by_us and be retried at every project
                # boundary by _release_paused_folders for the life of the
                # process.
                with self._lock:
                    self._paused_by_us.discard(slug)
                continue
            self._set_paused(slug, False)

    def _release_paused_folders(self) -> None:
        """Unpause every folder this sequencer paused and hasn't released.

        Called BEFORE each project's lane A/B runs. The previous project's
        lane C turn left all the other folders paused, and the only sweep
        that undid that ran between passes -- so a 200 GB ingest blocking in
        lane A for 18 h left lane C stopped for every other selected project
        that whole time (AUDIT_2 L-4). Scoped to what we actually paused, so
        in steady state it costs zero config writes rather than one per
        project per project."""
        with self._lock:
            slugs = sorted(self._paused_by_us)
        for slug in slugs:
            if self._ignores_unconfirmed_for(slug):
                continue
            self._set_paused(slug, False)

    def _set_paused(self, slug: str, paused: bool) -> bool:
        """Pause/unpause one folder. Returns False on failure. A 404 just
        means the editor hasn't accepted that folder yet -- routine, and it
        used to write a full traceback per project per pass, burying real
        errors in companion.log (AUDIT_2 L-11)."""
        try:
            self.admin.set_folder_paused(slug, paused)
            with self._lock:
                if paused:
                    self._paused_by_us.add(slug)
                else:
                    self._paused_by_us.discard(slug)
            return True
        except Exception as exc:
            if _is_not_found(exc):
                log.debug("sequencer: folder %s not configured locally yet", slug)
                # There is no folder to be left paused, so stop tracking it:
                # a folder removed from Syncthing while we had it paused
                # otherwise stayed in _paused_by_us for the life of the
                # process, retried on every single project boundary.
                with self._lock:
                    self._paused_by_us.discard(slug)
            else:
                log.exception(
                    "sequencer: failed to %s folder %s", "pause" if paused else "unpause", slug
                )
            return False

    # -- one pass over the selected projects -----------------------------------------------------
    def _run_pass(self, selection: list[dict]) -> None:
        # Survives a mid-pass selection change: a project already synced this
        # pass must not be re-run from scratch just because the tail of the
        # list changed (AUDIT_2 L-10).
        with self._lock:
            self._processed_slugs = set()
        self._pass_moved = 0
        self._offline_pass = False
        processed_entries: dict[str, dict] = {}
        try:
            while True:
                ordered = _sort_by_position(selection)
                base_slugs = [item.get("slug") for item in ordered]
                total = len(ordered)
                # Anything already done this pass whose entry is UNCHANGED is
                # skipped on the restart; a changed entry (new rel_path, say)
                # genuinely needs re-running.
                queue_items = [
                    item for item in ordered
                    if processed_entries.get(str(item.get("slug"))) != item
                ]
                with self._lock:
                    self._queue = deque(queue_items)

                restart_selection: Optional[list[dict]] = None
                processed = total - len(queue_items)
                while True:
                    if self._stop_event.is_set() or not self._resume_event.is_set():
                        with self._lock:
                            self._queue = None
                        return

                    with self._lock:
                        if self._queue:
                            item = self._queue.popleft()
                            self._current_slug = item.get("slug")
                            self._current_position = processed + 1
                            self._current_total = total
                            self._queue_slugs = [i.get("slug") for i in self._queue]
                            self._state = STATE_RUNNING
                        else:
                            item = None

                    if item is None:
                        with self._lock:
                            self._queue = None
                        break

                    processed += 1
                    self._process_project(item, ordered)
                    slug = str(item.get("slug"))
                    processed_entries[slug] = item
                    with self._lock:
                        self._processed_slugs.add(slug)
                        self._current_slug = None
                        self._queue_slugs = [i.get("slug") for i in (self._queue or [])]

                    if self._stop_event.is_set() or not self._resume_event.is_set():
                        with self._lock:
                            self._queue = None
                        return

                    if self._offline_pass:
                        # Both rclone lanes failed on that project, i.e. the
                        # NAS is not reachable from here (ops-efficiency-4,
                        # 2026-08-21). Every remaining project would spend
                        # the same contimeout x retries per lane -- roughly
                        # 45 minutes of doomed subprocesses for ten projects
                        # -- to learn the same thing. Abandon the pass; the
                        # idle backoff makes the retry cadence sane, and any
                        # watcher/tray/selection event still cuts it short.
                        log.warning(
                            "sequencer: lanes A and B both failed on %s -- treating the "
                            "server as unreachable and ending this pass early; the next "
                            "one runs in %.0fs", item.get("slug"), self._idle_seconds(),
                        )
                        with self._lock:
                            self._queue = None
                        return

                    # Once per project, not per poll tick -- worth a live
                    # request, unlike the lane C wait loop (AUDIT_2 P11).
                    new_selection, _source = self._selection_get()
                    if new_selection:
                        new_slugs = [i.get("slug") for i in _sort_by_position(new_selection)]
                        if new_slugs != base_slugs:
                            restart_selection = new_selection
                            break

                if restart_selection is None:
                    return
                selection = restart_selection
                self._update_known_selection(selection)
        finally:
            with self._lock:
                self._processed_slugs = set()

    def _reconcile_paths(self, selection: list[dict]) -> list[str]:
        """Repath any project moved server-side BEFORE lanes touch it --
        otherwise lane A re-uploads the old local tree to the NAS's dead
        old path. Fault-isolated like every other step. Returns the slugs
        that were actually repathed (a repath invalidates the cached
        directory structure -- see _maybe_clone_structure)."""
        try:
            return list(self.repather.reconcile(selection) or [])
        except Exception:
            log.exception("sequencer: repath reconcile failed")
            return []

    def _process_project(self, item: dict, ordered_selected: list[dict]) -> None:
        if not _item_is_valid(item):
            log.warning(
                "sequencer: skipping selection item with an invalid/inactive rel_path or "
                "slug (slug=%r, rel_path=%r) -- refusing to build a local path or a "
                "Syncthing folder id from it",
                item.get("slug"), item.get("rel_path"),
            )
            return
        rel_path = _item_rel(item)
        if rel_path is None:  # unreachable via _item_is_valid; belt and braces
            return
        slug = str(item.get("slug"))
        subpath = f"{PROJECTS_PREFIX}{rel_path}"
        upload_only = _item_upload_only(item)

        # A mid-pass selection refresh may have re-ordered/changed rels --
        # re-check this project's local path right before its lanes run.
        # STRICTLY BEFORE lane A, and never concurrent with it: repath moves
        # the project directory, and a lane A that started first would
        # re-upload the stale tree to the NAS's dead old path (AUDIT_2 C-1).
        repathed = self._reconcile_paths([item])

        # Then mirror the project's full directory skeleton -- including
        # empty folders, which neither lane would otherwise create (lane B
        # copies proxy files only; lane C's .stignore drops video/Proxy).
        # Editors get the same bin layout the NAS has from the moment they
        # tick, not only once files exist. Now CONDITIONAL: it is a full
        # remote listing and it is redundant in steady state (AUDIT_2 C-3).
        self._maybe_clone_structure(subpath, slug, forced=bool(repathed))
        if self._stop_event.is_set() or not self._resume_event.is_set():
            return

        # Release every folder the previous turn paused BEFORE the
        # (potentially very long) lane A/B runs -- see _release_paused_folders.
        self._release_paused_folders()

        budget = self.project_rotation_seconds if self.project_rotation_seconds > 0 else None
        self._run_lanes_a_and_b(subpath, budget, upload_only=upload_only)
        if self._stop_event.is_set() or not self._resume_event.is_set():
            return

        if upload_only:
            # Lane A was the whole turn (docs/UPLOAD_ONLY_TICK.md). No
            # borrowed-folder runs -- a borrowed subtree is something this
            # machine would DOWNLOAD -- and no lane C turn: the server never
            # shares the folder with an upload-only machine, so there is
            # nothing to accept, unpause or wait for.
            self._maybe_scan_orphans(subpath, slug)
            return

        # Borrowed folders (SHARED_FOLDERS_PLAN.md D3/§3.1): each ok include
        # is an EXTRA subpath run inside this borrower's turn -- same
        # filters, breaker scope, trash layout; nothing in rclone_lane.py
        # changes, the subpath is just deeper. Each include gets its own
        # budget (a borrower with N includes gets N+1), and its bookkeeping
        # is keyed "<slug>::<subpath>" so it is pruned with the borrower.
        for inc in self._borrowed_includes(slug):
            sub = f"{PROJECTS_PREFIX}{inc['subpath']}"
            key = f"{slug}::{inc['subpath']}"
            self._maybe_clone_structure(sub, key, forced=False)
            if self._stop_event.is_set() or not self._resume_event.is_set():
                return
            self._run_lanes_a_and_b(sub, budget)
            if self._stop_event.is_set() or not self._resume_event.is_set():
                return
            self._maybe_scan_orphans(sub, key)

        self._maybe_scan_orphans(subpath, slug)
        self._lane_c_turn(item, ordered_selected)

    def _run_lanes_a_and_b(
        self, subpath: str, budget: Optional[float], upload_only: bool = False,
    ) -> None:
        """Lane A (up) and lane B (down) for one project.

        Concurrent by default: they are opposite directions over disjoint
        file sets in separate rclone processes, and the link is full duplex,
        so serializing them left one direction idle for the whole of the
        other's transfer -- up to 50% of pass wall clock (AUDIT_2 C-1/P7).
        Both are joined before the caller moves to the next project, so
        "one project at a time" is unchanged, as is the ordering guarantee
        that repath runs first. Two lane A runs on the same project are
        still impossible: RcloneLane._run_lock covers that.

        `upload_only` (docs/UPLOAD_ONLY_TICK.md) is the per-PROJECT switch
        for lane B, beside the per-machine `lane_b_enabled`: an upload-only
        tick downloads no proxies. A lone lane A failure is then not
        offline evidence either (_note_transport)."""
        run_b = self.lane_b_enabled and not upload_only
        outcomes: dict[str, Any] = {}

        def _a() -> None:
            try:
                outcomes["a"] = self._run_lane(self.lane_a, subpath, budget)
            except Exception:
                log.exception("sequencer: lane A run_once failed for %s", subpath)
            finally:
                self._note_lane_moved(self.lane_a)

        def _b() -> None:
            try:
                outcomes["b"] = self._run_lane(self.lane_b, subpath, budget)
            except Exception:
                log.exception("sequencer: lane B run_once failed for %s", subpath)
            finally:
                self._note_lane_moved(self.lane_b)

        if not (self.concurrent_lanes and run_b):
            _a()
            if run_b and not (self._stop_event.is_set() or not self._resume_event.is_set()):
                _b()
            self._note_transport(outcomes, run_b)
            return

        thread = threading.Thread(
            target=_b, name="ccsync-sequencer-lane-b", daemon=True
        )
        thread.start()
        try:
            _a()
        finally:
            # Always join: an un-joined lane B would still be writing into
            # the project directory while the next project's repath moves it.
            thread.join()
        self._note_transport(outcomes, run_b)

    # -- pass economics (ops-efficiency-2 / -4, 2026-08-21) ---------------
    def _note_lane_moved(self, lane: Any) -> None:
        """Add what a lane run just moved to this pass's total. Never
        raises: `last_run_moved` is not part of the LaneAdapter contract, so
        a test double or a future adapter without one simply contributes
        nothing (and the pass then looks idle, which only costs a longer
        wait)."""
        try:
            getter = getattr(lane, "last_run_moved", None)
            if getter is None:
                return
            self._pass_moved += max(0, int(getter() or 0))
        except Exception:
            log.debug("sequencer: could not read a lane's moved count", exc_info=True)

    def _note_transport(self, outcomes: dict[str, Any], run_b: bool) -> None:
        """Did BOTH rclone lanes fail on this project?

        The cheapest honest test for "this machine cannot reach the NAS"
        that costs no extra probe (ops-efficiency-4, 2026-08-21). A laptop
        off the tailnet spends ~60 s x 3 attempts per lane per project
        blackholed in contimeout, so ten ticked projects burn roughly
        45 minutes of doomed subprocesses per pass, and 60 s later start
        again. One lane failing is ordinary (a missing remote dir, a
        filename rclone refuses); both failing on the same project, in
        opposite directions, is the link. Only consulted when lane B is
        enabled -- on a base rig lane A is alone and its failures are not
        evidence of anything.
        """
        if not run_b:
            return
        states = [getattr(outcomes.get(key), "state", None) for key in ("a", "b")]
        if all(state == STATE_ERROR_LANE for state in states):
            self._offline_pass = True

    def _note_pass_finished(self) -> None:
        """Advance or reset the idle backoff at the end of a pass."""
        moved = self._pass_moved
        step = self._idle_step
        if moved > 0:
            self._idle_step = 0
        elif step < len(IDLE_BACKOFF_STEPS) - 1:
            self._idle_step = step + 1
        if self._idle_step != step:
            log.debug(
                "sequencer: pass moved %d file(s) -- next idle wait is %.0fs",
                moved, self._idle_seconds())

    def _wake_up_now(self) -> None:
        """Something happened that a backed-off sequencer must react to at
        the normal cadence: a watcher event, a tray trigger, a resume, a
        selection change."""
        self._idle_step = 0

    def _idle_seconds(self) -> float:
        """The between-passes wait, with the backoff applied."""
        step = min(max(0, self._idle_step), len(IDLE_BACKOFF_STEPS) - 1)
        return self.sequencer_idle_seconds * IDLE_BACKOFF_STEPS[step]

    @staticmethod
    def _run_lane(lane: Any, subpath: str, budget: Optional[float]) -> Any:
        """run_once with a per-project time budget where the lane supports
        one. Adapters that predate the budget (and test doubles) take
        (subpath) only -- checked by signature rather than by catching
        TypeError, which would silently re-run a lane whose body raised."""
        if budget is None or not _accepts_max_duration(lane.run_once):
            return lane.run_once(subpath)
        return lane.run_once(subpath, max_duration_seconds=budget)

    def _maybe_clone_structure(self, subpath: str, slug: str, forced: bool = False) -> bool:
        """Structure clone, but not on every pass.

        `clone_directory_tree` is an `rclone lsf --dirs-only -R` over SFTP
        plus a local mkdir loop -- ~1.5 s and one SSH handshake per project,
        three times per project per pass alongside the lane traversals, and
        after the first pass it creates nothing at all in steady state
        (AUDIT_2 C-3/P10). Kept unconditional in exactly the cases where the
        tree really can have changed under us: the first pass after startup,
        and immediately after a repath moved the project.

        Returns True when the clone ran."""
        every = self.structure_clone_every_n_passes
        if every <= 0 and not forced:
            # 0 = disabled, as config.py and config.example.toml have always
            # said (AUDIT_3 M-6). `forced` still wins: a repath moved the
            # project, so whatever structure exists locally is at the wrong
            # path and re-creating it is not optional.
            return False
        age = self._clone_ages.get(slug)
        due = forced or age is None or every <= 1 or age >= every
        if not due:
            self._clone_ages[slug] = (age or 0) + 1
            return False
        self._clone_structure(subpath)
        self._clone_ages[slug] = 1
        return True

    def _maybe_scan_orphans(self, subpath: str, slug: str) -> bool:
        """Every N passes, count the `*.partial` files lane A's killed runs
        left on the NAS and log them. REPORTS ONLY -- adding a delete path on
        the NAS is exactly what AUDIT_2 C-7 rules out, so this never removes
        anything. Costs one remote listing when it runs."""
        every = self.orphan_scan_every_n_passes
        if every <= 0:
            return False
        scan = getattr(self.lane_a, "refresh_orphan_report", None)
        if scan is None:
            return False
        age = self._orphan_ages.get(slug)
        if age is not None and age < every:
            self._orphan_ages[slug] = age + 1
            return False
        self._orphan_ages[slug] = 1
        try:
            scan(subpath)
        except Exception:
            log.debug("sequencer: orphan .partial scan failed for %s", subpath, exc_info=True)
            return False
        return True

    def _local_root_is_present(self) -> bool:
        """Is the tree actually mounted right now?

        Defence in depth behind app.py's root guard: the structure clone ends
        in a local `mkdir -p` loop, so against an absent local_root -- a macOS
        editor's external SSD unplugged -- it would BUILD the whole project
        scaffolding on the machine's internal disk, at exactly the path lane B
        then syncs into. Fails open on an unreadable probe, same as the lane's
        own check."""
        try:
            root = str(self.local_root or "").strip()
            # Path("") is Path(".") -- the PROCESS CWD, which is always a
            # directory and is C:\Windows\system32 for a Run-key autostart.
            # A blank local_root must never read as "the tree is here".
            return bool(root) and Path(root).is_dir()
        except Exception:
            log.debug("sequencer: could not check local_root", exc_info=True)
            return True

    def _clone_structure(self, subpath: str) -> None:
        if not self._local_root_is_present():
            log.warning(
                "sequencer: not cloning the structure for %s -- local_root %s is not "
                "a directory (drive disconnected?)", subpath, self.local_root,
            )
            return
        try:
            created = self._clone_tree_fn(
                rclone_path=str(self.cfg.get("rclone_path", "rclone")),
                remote=str(self.cfg.get("remote", "")),
                remote_root=str(self.cfg.get("remote_root", "")),
                local_root=self.local_root,
                subpath=subpath,
            )
        except Exception:
            log.exception("sequencer: structure clone failed for %s", subpath)
            return
        if created:
            log.info(
                "sequencer: created %d missing project folder(s) for %s", created, subpath
            )

    # -- Lane C (Syncthing) turn -----------------------------------------------------
    def _lane_c_turn(self, item: dict, ordered_selected: list[dict]) -> None:
        # A stopping/pausing sequencer must not start a fresh pause sweep --
        # re-checked below inside the sweep loop too (AUDIT §4).
        if self._stop_event.is_set() or not self._resume_event.is_set():
            return
        slug = item.get("slug")
        # _maybe_auto_accept builds `local_root/Projects/<rel_path>` from
        # this, so it uses the same normalized+validated rel every other
        # path-building consumer does.
        rel_path = _item_rel(item) or ""
        if not slug or not rel_path:
            return
        if _item_upload_only(item):
            # Belt and braces: _process_project never gets here for an
            # upload-only project, and accepting the folder would be the one
            # thing the tick promises not to do.
            return

        with self._lock:
            self._in_lane_c_turn = True
            self._lane_c_idle.clear()
        try:
            if not self._maybe_auto_accept(slug, rel_path):
                # accept_folder creates the folder PAUSED, sets ignores, then
                # unpauses -- so that a failed set_ignores leaves it paused
                # rather than syncing unfiltered. Unpausing it here anyway
                # (which the old code did unconditionally, ~1 ms later) threw
                # that guarantee away: the folder leaves pending_folders(), so
                # NOTHING ever retries the ignores, and lane C then indexes
                # and offers every .braw/.mov original and every Proxy/ file
                # for the life of the install -- a straight lane-direction
                # violation (AUDIT_2 L-3).
                with self._lock:
                    self._ignores_unconfirmed.add(slug)
                log.warning(
                    "sequencer: folder %s could not be accepted cleanly -- leaving it "
                    "paused rather than syncing without ignores", slug,
                )
                return

            # Re-assert ignores + versioning for THIS folder once per turn.
            # Nothing else in the codebase ever sets ignores on a folder it
            # did not itself accept, so a folder accepted by an older
            # companion, by hand in the Syncthing GUI, or before DEL-6 was
            # fixed stayed un-ignored and unversioned forever (AUDIT_2 L-3/
            # P6/DEL-6).
            #
            # It is also the ONLY retry of a half-accepted folder's ignores
            # (the folder has left pending_folders(), so nothing offers it
            # again) -- which is why the latch below is cleared HERE, on a
            # set_ignores that actually returned, and not merely because the
            # slug was absent from pending_folders() (B14).
            if not self._reassert_folder_policy(slug):
                # B5: this used to be swallowed by a bare log.exception and
                # the unpause below ran anyway, putting a sendreceive folder
                # with no known .stignore online -- lane C then offers every
                # original video and the whole Proxy/ tree bidirectionally,
                # duplicating lanes A/B and propagating any local video
                # delete to the NAS and every other editor.
                with self._lock:
                    self._ignores_unconfirmed.add(slug)
                log.warning(
                    "sequencer: could not confirm ignores for folder %s -- leaving it "
                    "paused rather than syncing without them", slug,
                )
                return
            with self._lock:
                self._ignores_unconfirmed.discard(slug)

            # AUDIT_2 P4/C-1: pausing every OTHER selected folder for the
            # duration of this turn costs N(N-1) config commits per pass
            # (~1000/hour at N=6), restarts and fully rescans a folder on
            # every unpause (~180 tree walks/hour, competing for the same
            # IOPS as lanes A and B), silently rewrites unrelated folder
            # fields on each PATCH, and leaves every non-current project
            # unable to send its small latency-sensitive files for up to
            # N x rotation seconds (~50 min at N=6). maxFolderConcurrency
            # (set in _apply_lane_c_pacing) buys the same "one project at a
            # time" pacing for zero config writes. "rotate" restores the old
            # scheme if this ever turns out to be wrong in the field.
            if self.lane_c_pause_scheme == PAUSE_SCHEME_ROTATE:
                for other in ordered_selected:
                    if self._stop_event.is_set() or not self._resume_event.is_set():
                        return
                    other_slug = other.get("slug")
                    if not other_slug or other_slug == slug or _item_upload_only(other):
                        continue
                    self._set_paused(other_slug, True)

            if self._stop_event.is_set() or not self._resume_event.is_set():
                return

            # Unpause unconditionally, in BOTH schemes: with the scheme off
            # this is what releases a folder that an older companion, a
            # crashed rotate-scheme pass, or a hand-pause left stuck -- and a
            # stuck-paused folder means lane C carries nothing at all for
            # that project. _set_paused is a no-op write only when the folder
            # is already running, which Syncthing handles cheaply.
            if not self._set_paused(slug, False):
                return
        finally:
            with self._lock:
                self._in_lane_c_turn = False
                self._lane_c_idle.set()

        base_slugs = [i.get("slug") for i in ordered_selected if not _item_upload_only(i)]
        self._wait_for_folder_sync(slug, base_slugs)
        self._verify_current_folder_unpaused(slug)

    def _reassert_folder_policy(self, slug: str) -> bool:
        """Ignores + versioning, per turn, for the current folder only.

        Returns False when the ignores are NOT known to have landed, so the
        caller can leave the folder paused -- the same guarantee
        SyncthingAdmin.accept_folder makes, which this used to throw away by
        catching every non-404 with a bare log.exception and returning
        normally (B5). A config write that merely exceeds
        config_write_timeout is the expected trigger: the codebase documents
        those routinely outlast the read timeout, which is why
        config_write_timeout exists at all.

        A 404 is NOT a failure here: it means the folder is not configured
        locally at all, so there is nothing to run unfiltered -- and the
        unpause that follows 404s just as harmlessly. Reporting it as a
        failure would put a WARNING per project per pass in the log for every
        folder the editor has not been offered yet (AUDIT_2 L-11).

        Versioning and ignoreDelete are reported separately: a folder without
        either is a delete-safety risk, not a lane-direction violation, and
        blocking the unpause on one would stop lane C entirely for a folder
        whose ignores are fine.
        """
        state = self._ignores_state(slug)
        if state == IGNORES_ABSENT:
            log.debug("sequencer: folder %s not configured locally yet", slug)
            return True
        if state == IGNORES_MISSING:
            try:
                self.admin.set_ignores(slug, STIGNORE_LINES)
            except Exception as exc:
                if _is_not_found(exc):
                    log.debug("sequencer: folder %s not configured locally yet", slug)
                    return True
                log.exception("sequencer: could not re-assert ignores for %s", slug)
                return False
        else:
            # The .stignore was READ and carries every line, which is stronger
            # evidence than a POST that returned -- so the admin's
            # half-accepted latch can be cleared from here too (SYNC-6),
            # otherwise a folder whose set_ignores timed out AFTER Syncthing
            # applied it would stay latched forever and be excluded from every
            # leak-recovery unpause sweep.
            note = getattr(self.admin, "note_ignores_confirmed", None)
            if note is not None:
                try:
                    note(slug)
                except Exception:
                    log.debug("sequencer: note_ignores_confirmed(%s) failed", slug, exc_info=True)

        # ONE folder fetch for both checks below (SYNC-6): each ensure_* does
        # its own GET /rest/config/folders/<id> when it isn't handed a config,
        # which made a steady-state turn cost two identical reads. Same shape
        # as SharedFolderManager._reconcile_one. A read we could not make is
        # passed on as None, which just restores the old per-call fetch.
        folder: Optional[dict] = None
        get_folder = getattr(self.admin, "get_folder", None)
        if get_folder is not None:
            try:
                fetched_folder = get_folder(slug)
                folder = fetched_folder if isinstance(fetched_folder, dict) else None
            except Exception as exc:
                if _is_not_found(exc):
                    return True
                log.debug("sequencer: could not read folder %s's config", slug, exc_info=True)
        try:
            self.admin.ensure_versioning(slug, folder)
        except Exception as exc:
            if _is_not_found(exc):
                return True
            log.exception("sequencer: could not ensure versioning for %s", slug)
        # delete-protection (2026-08-11, docs/delete-protection-ignoredelete.md):
        # the retrofit path for folders accepted by an older companion or by
        # hand. One PATCH on the first turn after the upgrade, silence after.
        try:
            self.admin.ensure_ignore_delete(slug, folder)
        except Exception as exc:
            if _is_not_found(exc):
                return True
            log.exception("sequencer: could not ensure ignoreDelete for %s", slug)
        return True

    def _ignores_state(self, slug: str) -> str:
        """IGNORES_OK | IGNORES_MISSING | IGNORES_ABSENT for one folder.

        SYNC-6 (2026-08-14): _reassert_folder_policy POSTed the full
        STIGNORE_LINES on every project's turn, forever -- one .stignore
        rewrite, plus the ignore-matcher re-evaluation that follows it, per
        project per pass, in a steady state where nothing is ever missing.
        Reading first is the shape SharedFolderManager._ensure_ignores already
        proved ("steady state costs one GET and no config write").

        It keeps the B5 posture that made the unconditional write a
        deliberate retry path: a read that FAILS counts as missing, so the
        write still happens and the folder still stays paused if that write
        fails. Only a read that actually returned a complete .stignore skips
        it. IGNORES_ABSENT (404) is the one benign case -- the folder is not
        configured on this machine, so there is nothing to run unfiltered.
        """
        getter = getattr(self.admin, "get_ignores", None)
        if getter is None:  # an admin double that predates the getter
            return IGNORES_MISSING
        try:
            fetched = getter(slug)
        except Exception as exc:
            if _is_not_found(exc):
                return IGNORES_ABSENT
            log.debug(
                "sequencer: could not read folder %s's ignores (%s) -- re-asserting them",
                slug, exc,
            )
            return IGNORES_MISSING
        missing = missing_ignore_lines(fetched)
        if not missing and is_restricted(fetched):
            # The editor ticked a lender they were borrowing from: its
            # .stignore is still the borrowed-folder restriction, which
            # passes the superset test above but would sync only the
            # borrowed subtree. Re-assert the FULL list (set_ignores
            # replaces the whole file, restriction gone).
            log.info(
                "sequencer: folder %s carries a restricted (borrowed-folder) .stignore "
                "but is selected here -- rewriting the full ignore list", slug)
            return IGNORES_MISSING
        if not missing:
            return IGNORES_OK
        log.info(
            "sequencer: folder %s is missing %d of its %d ignore patterns (e.g. %s) "
            "-- re-asserting", slug, len(missing), len(STIGNORE_LINES), ", ".join(missing[:3]),
        )
        return IGNORES_MISSING

    def _verify_current_folder_unpaused(self, slug: str) -> None:
        """Confirm the turn actually left this folder running.

        A config PATCH that times out (Syncthing commits and restarts the
        folder on one) could otherwise leave EVERY selected folder paused
        and lane C fully stopped until the between-passes sweep -- hours
        away, or never, if the pass is long (AUDIT_2 L-11)."""
        try:
            config = self.admin.get_config() or {}
        except Exception:
            log.debug("sequencer: could not verify paused state for %s", slug, exc_info=True)
            return
        for folder in (config.get("folders") or []):
            if folder.get("id") != slug:
                continue
            if folder.get("paused"):
                log.warning(
                    "sequencer: folder %s is still paused after its lane C turn -- "
                    "retrying the unpause", slug,
                )
                self._set_paused(slug, False)
            return

    def _maybe_auto_accept(self, slug: str, rel_path: str) -> bool:
        """Returns True when the folder is (or already was) usable, False
        when an accept was needed and failed -- or when we could not find out
        whether one was needed.

        Fail-CLOSED on a pending_folders() failure: "can't tell" used to
        return True, which released a folder the previous turn had
        deliberately latched paused (its ignores never landed) on the
        strength of one failed GET. Waiting one rotation for a folder whose
        filtering is uncertain is cheap; putting an unfiltered sendreceive
        folder online is not (B14)."""
        try:
            pending = self.admin.pending_folders() or {}
        except Exception as exc:
            if _is_not_found(exc):
                # No pending-folders endpoint at all (a Syncthing predating
                # /rest/cluster/pending/folders). That is a definite "nothing
                # is pending", not a "can't tell".
                log.debug("sequencer: no pending-folders endpoint -- nothing to accept")
                return True
            log.exception(
                "sequencer: pending_folders() failed -- treating %s as unusable this turn",
                slug,
            )
            return False
        if not isinstance(pending, dict) or slug not in pending:
            return True
        try:
            offered_by = (pending.get(slug) or {}).get("offeredBy") or {}
            device_id = next(iter(offered_by.keys())) if offered_by else ""
            local_path = str(Path(self.local_root) / "Projects" / rel_path)
            self.admin.accept_folder(
                slug, label=rel_path, local_path=local_path, offered_by_device_id=device_id
            )
        except Exception:
            log.exception("sequencer: accept_folder(%s) failed", slug)
            return False
        return True

    def _remote_device_ids(self, slug: str) -> list[str]:
        """Every device this folder is shared with except ourselves."""
        try:
            config = self.admin.get_config() or {}
            my_id = str((self.admin.system_status() or {}).get("myID", "") or "")
        except Exception:
            log.debug("sequencer: could not resolve devices for %s", slug, exc_info=True)
            return []
        for folder in (config.get("folders") or []):
            if folder.get("id") != slug:
                continue
            return [
                str(d.get("deviceID"))
                for d in (folder.get("devices") or [])
                if d.get("deviceID") and str(d.get("deviceID")) != my_id
            ]
        return []

    def _uploads_drained(self, slug: str, device_ids: list[str]) -> bool:
        """Whether every remote device has everything we hold for this
        folder. needTotalItems (below) is the DOWNLOAD side only, so a turn
        could end -- and the folder then be paused by the next project's
        turn -- with the editor's own outgoing files half-sent, stalling
        them for up to N x rotation seconds (AUDIT_2 P5). Degrades to
        "drained" whenever the endpoint can't answer."""
        for device_id in device_ids:
            try:
                completion = self.admin.completion(slug, device_id) or {}
            except Exception:
                log.debug(
                    "sequencer: completion(%s, %s) failed", slug, device_id, exc_info=True
                )
                continue
            try:
                if float(completion.get("needBytes", 0) or 0) > 0:
                    return False
            except (TypeError, ValueError):
                continue
        return True

    def _lane_c_wait_budget(self) -> float:
        """How long a project's turn may wait on lane C before moving on.

        The full `project_rotation_seconds` (600) is load-bearing ONLY under
        PAUSE_SCHEME_ROTATE, where the next project's turn will pause this
        folder and the wait is what stops that happening mid-transfer. With
        the default scheme ("none") nothing is paused and Syncthing paces
        every folder itself via maxFolderConcurrency, so the wait gates
        nothing at all -- it just parks the whole sequencer for up to ten
        minutes per project on any folder with a large backlog or a
        permanently non-zero need (a conflict, a deleted-but-still-ticked
        remote), delaying lane B proxies for every project behind it by up to
        N x 600 s (ops-efficiency-3, 2026-08-21). A short settle is kept so
        `current_project` still reads sensibly on the dashboard rather than
        flickering through the queue.
        """
        rotation = self.project_rotation_seconds
        if self.lane_c_pause_scheme == PAUSE_SCHEME_ROTATE:
            return rotation
        settle = self.lane_c_settle_seconds
        if settle <= 0:
            return rotation
        return min(rotation, settle) if rotation > 0 else settle

    def _wait_for_folder_sync(self, slug: str, base_slugs: list[str]) -> None:
        start = self._now()
        budget = self._lane_c_wait_budget()
        device_ids = self._remote_device_ids(slug)
        while True:
            if self._stop_event.is_set() or not self._resume_event.is_set():
                return
            try:
                status = self.admin.folder_status(slug) or {}
                need = int((status or {}).get("needTotalItems", 0) or 0)
            except Exception:
                log.exception("sequencer: folder_status(%s) failed", slug)
                return  # can't tell -- don't block the whole rotation on it
            if need == 0 and self._uploads_drained(slug, device_ids):
                return
            if self._now() - start >= budget:
                return

            # Throttled, NOT per 5-second tick: see _selection_get_throttled
            # (AUDIT_2 P11). Cost of the throttle: a selection change made
            # mid-turn is noticed up to selection_poll_interval later, which
            # is the cadence the knob already promises.
            new_selection, _source = self._selection_get_throttled()
            if new_selection:
                new_slugs = [i.get("slug") for i in _sort_by_position(new_selection)]
                if new_slugs != base_slugs:
                    return

            if self._interruptible_wait(self.folder_status_poll_seconds):
                return

    # -- interruptible waits -----------------------------------------------------
    #
    # Both wait on the single _interrupt event for the WHOLE remaining
    # timeout. They used to wake every 50 ms forever, and the sequencer is
    # always in one of them, so the process woke 20x/s indefinitely on a
    # laptop for no reason (AUDIT_2 L-18). _interrupt is cleared BEFORE the
    # predicates are re-checked, so a setter racing the clear can only ever
    # cost one extra wakeup, never a missed signal.
    def _interruptible_wait(self, seconds: float) -> bool:
        """Sleep up to `seconds`, breaking early on stop() or pause().
        Returns True if the caller should stop what it's doing. Deliberately
        does NOT consume _wake_event -- a notify_change() during a lane C
        wait must still shorten the between-passes wait later."""
        deadline = self._now() + seconds
        while True:
            self._interrupt.clear()
            if self._stop_event.is_set() or not self._resume_event.is_set():
                return True
            remaining = deadline - self._now()
            if remaining <= 0:
                return False
            if not self._interrupt.wait(remaining):
                return False

    def _wait_or_wake(self, seconds: float) -> bool:
        """Sleep up to `seconds`, breaking early on stop(), pause(), or a
        wake trigger (notify_change()/trigger_pass_now()/resume()). Returns
        True only if the caller should stop the whole loop (stop() called)."""
        deadline = self._now() + seconds
        while True:
            self._interrupt.clear()
            if self._stop_event.is_set():
                return True
            if not self._resume_event.is_set():
                return False
            if self._wake_event.is_set():
                self._wake_event.clear()
                return False
            remaining = deadline - self._now()
            if remaining <= 0:
                return False
            if not self._interrupt.wait(remaining):
                return False
