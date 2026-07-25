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

import logging
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Optional

from ..selection import SelectionClient
from .rclone_lane import clone_directory_tree
from .repath import ProjectRepather
from .syncthing_admin import SyncthingAdmin

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

# Granularity of the interruptible waits below -- small enough that stop()/
# pause()/notify_change()/trigger_pass_now() feel immediate, large enough
# not to busy-loop.
_POLL_CHUNK_SECONDS = 0.05

PROJECTS_PREFIX = "Projects/"


def _sort_by_position(selection: list[dict]) -> list[dict]:
    return sorted(selection, key=lambda item: item.get("position", 0))


def _item_is_valid(item: dict) -> bool:
    """A selection item usable for sync: rel_path must be a non-blank str
    and active (when present) must not be explicitly False. A dashboard row
    whose project record is gone (LEFT JOIN -> rel_path NULL) must never
    reach a path join -- str(None) == "None" would move the project
    directory to "...\\Projects\\None" (AUDIT D-4)."""
    rel = item.get("rel_path")
    if not isinstance(rel, str) or not rel.strip():
        return False
    if item.get("active") is False:
        return False
    return True


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
    ) -> None:
        self.lane_a = lane_a
        self.lane_b = lane_b
        self.admin = admin
        self.selection = selection
        self.cfg = cfg
        self.local_root = cfg.get("local_root", "")
        self.selection_poll_interval = float(cfg.get("selection_poll_interval", 60))
        self.project_rotation_seconds = float(cfg.get("project_rotation_seconds", 600))
        self.sequencer_idle_seconds = float(cfg.get("sequencer_idle_seconds", 60))
        # Base rig with direct NAS access reads proxies off the share; no
        # point mirroring them locally (and it fills the system drive).
        self.lane_b_enabled = bool(cfg.get("lane_b_enabled", True))
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
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        self._state = STATE_STARTUP
        self._current_slug: Optional[str] = None
        self._current_position = 0
        self._current_total = 0
        self._queue_slugs: list[str] = []
        self._rel_to_slug: dict[str, str] = {}
        self._slug_to_item: dict[str, dict] = {}
        self._queue: Optional[deque] = None  # live remaining-items during a pass; None otherwise
        self._last_selection: list[dict] = []
        self._no_selection_reason = ""
        # True only while _lane_c_turn is actively pausing/unpausing folders
        # -- stop()/pause() wait for this to clear before their own
        # unpause-everything sweep, so an in-flight sweep can't re-pause a
        # folder AFTER that sweep already ran (AUDIT §4).
        self._in_lane_c_turn = False

    # -- lifecycle -----------------------------------------------------
    def start(self) -> None:
        if not self.selection.enabled:
            return
        self._stop_event.clear()
        self._resume_event.set()
        self._thread = threading.Thread(target=self._run, name="ccsync-sequencer", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._wake_event.set()
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
        # Same ordering concern as stop(): give an in-flight lane-C pause
        # sweep a bounded window to notice and bail (or finish) before the
        # unpause-everything sweep below runs.
        self._wait_for_lane_c_turn_idle(timeout=5.0)
        self._unpause_all(self._last_selection)

    def resume(self) -> None:
        self._resume_event.set()
        self._wake_event.set()

    def _wait_for_lane_c_turn_idle(self, timeout: float) -> None:
        """Bounded, non-blocking-past-timeout wait for _lane_c_turn's
        folder-pause sweep to finish. Never waits for the whole pass (e.g.
        _wait_for_folder_sync) -- only for the part that actually mutates
        other folders' paused state, which is what could otherwise race
        _unpause_all() below."""
        if self._thread is None or not self._thread.is_alive():
            return
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                busy = self._in_lane_c_turn
            if not busy:
                return
            if not self._thread.is_alive():
                return
            time.sleep(_POLL_CHUNK_SECONDS)

    def trigger_pass_now(self) -> None:
        self._wake_event.set()

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
            return f"syncing {label} ({position}/{total})"
        if state == STATE_BETWEEN_PASSES:
            return "idle between passes"
        if state == STATE_PAUSED:
            return "paused"
        return "stopped"

    def known_rels(self) -> list[str]:
        """Selected-project rel paths (any depth) -- feeds lane A's watchdog
        project attribution (rclone_lane.known_rels_fn)."""
        with self._lock:
            return list(self._rel_to_slug)

    # -- watcher hand-off -----------------------------------------------------
    def notify_change(self, rel: str) -> None:
        """rel is "Projects/<year>/<series>/<project>" (from RcloneLane's
        on_change callback). Promotes the matching selected project to be
        next-after-current if it isn't already current -- no preemption of
        whatever is running right now."""
        rel_path = rel[len(PROJECTS_PREFIX):] if rel.startswith(PROJECTS_PREFIX) else rel
        with self._lock:
            slug = self._rel_to_slug.get(rel_path)
            if not slug or slug == self._current_slug:
                return
            item = self._slug_to_item.get(slug)
            if item is None:
                return
            if self._queue is not None:
                self._queue = deque(i for i in self._queue if i.get("slug") != slug)
                self._queue.appendleft(item)
                self._queue_slugs = [i.get("slug") for i in self._queue]
        self._wake_event.set()

    # -- main loop -----------------------------------------------------
    def _run(self) -> None:
        with self._lock:
            self._state = STATE_STARTUP
        self._startup_unpause()
        while not self._stop_event.is_set():
            if not self._resume_event.is_set():
                self._park_paused()
                continue

            selection, source = self.selection.get()
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
            self._reconcile_paths(selection)
            self._run_pass(selection)

            if self._stop_event.is_set() or not self._resume_event.is_set():
                continue

            with self._lock:
                self._state = STATE_BETWEEN_PASSES
                self._current_slug = None
                self._queue_slugs = []
            self._unpause_all(self._last_selection)
            if self._wait_or_wake(self.sequencer_idle_seconds):
                break

        with self._lock:
            self._state = STATE_STOPPED
            self._current_slug = None
            self._queue_slugs = []

    @staticmethod
    def _describe_no_selection(selection: Optional[list[dict]], source: str) -> str:
        if selection is None:
            if source == "none":
                return "dashboard unreachable, no cache"
            return "dashboard unreachable"
        return "zero projects selected"

    # -- startup / pause -----------------------------------------------------
    def _startup_unpause(self) -> None:
        """Leak recovery: best-effort unpause every folder in the cached
        selection, in case a previous run crashed mid-pass with some
        folders left paused."""
        cached: Optional[list[dict]] = None
        try:
            cached = self.selection.load_cached()
        except Exception:
            log.exception("sequencer: failed to load cached selection for startup unpause")
        if cached:
            self._update_known_selection(cached)
            self._unpause_all(cached)

    def _park_paused(self) -> None:
        with self._lock:
            self._state = STATE_PAUSED
            self._current_slug = None
            self._queue_slugs = []
        while not self._stop_event.is_set() and not self._resume_event.is_set():
            self._stop_event.wait(_POLL_CHUNK_SECONDS)
        if self._stop_event.is_set():
            return
        with self._lock:
            self._state = STATE_STARTUP
        self._startup_unpause()

    # -- selection bookkeeping -----------------------------------------------------
    def _update_known_selection(self, selection: list[dict]) -> None:
        rel_to_slug: dict[str, str] = {}
        slug_to_item: dict[str, dict] = {}
        for item in selection:
            if not _item_is_valid(item):
                continue
            rel = item.get("rel_path")
            slug = item.get("slug")
            if rel and slug:
                rel_to_slug[rel] = slug
            if slug:
                slug_to_item[slug] = item
        with self._lock:
            self._rel_to_slug = rel_to_slug
            self._slug_to_item = slug_to_item
            self._last_selection = list(selection)

    def _unpause_all(self, selection: list[dict]) -> None:
        for item in selection:
            slug = item.get("slug")
            if not slug:
                continue
            try:
                self.admin.set_folder_paused(slug, False)
            except Exception:
                log.exception("sequencer: failed to unpause folder %s", slug)

    # -- one pass over the selected projects -----------------------------------------------------
    def _run_pass(self, selection: list[dict]) -> None:
        while True:
            ordered = _sort_by_position(selection)
            base_slugs = [item.get("slug") for item in ordered]
            total = len(ordered)
            with self._lock:
                self._queue = deque(ordered)

            restart_selection: Optional[list[dict]] = None
            processed = 0
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

                with self._lock:
                    self._current_slug = None
                    self._queue_slugs = [i.get("slug") for i in (self._queue or [])]

                if self._stop_event.is_set() or not self._resume_event.is_set():
                    with self._lock:
                        self._queue = None
                    return

                new_selection, _source = self.selection.get()
                if new_selection:
                    new_slugs = [i.get("slug") for i in _sort_by_position(new_selection)]
                    if new_slugs != base_slugs:
                        restart_selection = new_selection
                        break

            if restart_selection is None:
                return
            selection = restart_selection
            self._update_known_selection(selection)

    def _reconcile_paths(self, selection: list[dict]) -> None:
        """Repath any project moved server-side BEFORE lanes touch it --
        otherwise lane A re-uploads the old local tree to the NAS's dead
        old path. Fault-isolated like every other step."""
        try:
            self.repather.reconcile(selection)
        except Exception:
            log.exception("sequencer: repath reconcile failed")

    def _process_project(self, item: dict, ordered_selected: list[dict]) -> None:
        if not _item_is_valid(item):
            log.warning(
                "sequencer: skipping selection item with invalid/inactive rel_path "
                "(slug=%s) -- refusing to build a path from it",
                item.get("slug"),
            )
            return
        rel_path = item.get("rel_path")
        subpath = f"{PROJECTS_PREFIX}{rel_path}"

        # A mid-pass selection refresh may have re-ordered/changed rels --
        # re-check this project's local path right before its lanes run.
        self._reconcile_paths([item])

        # First, mirror the project's full directory skeleton -- including
        # empty folders, which neither lane would otherwise create (lane B
        # copies proxy files only; lane C's .stignore drops video/Proxy).
        # Editors get the same bin layout the NAS has from the moment they
        # tick, not only once files exist. Idempotent, so it also picks up
        # folders added server-side later. Fault-isolated like the lanes.
        self._clone_structure(subpath)
        if self._stop_event.is_set() or not self._resume_event.is_set():
            return

        try:
            self.lane_a.run_once(subpath)
        except Exception:
            log.exception("sequencer: lane A run_once failed for %s", subpath)
        if self._stop_event.is_set() or not self._resume_event.is_set():
            return

        if self.lane_b_enabled:
            try:
                self.lane_b.run_once(subpath)
            except Exception:
                log.exception("sequencer: lane B run_once failed for %s", subpath)
            if self._stop_event.is_set() or not self._resume_event.is_set():
                return

        self._lane_c_turn(item, ordered_selected)

    def _clone_structure(self, subpath: str) -> None:
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
        rel_path = str(item.get("rel_path", ""))
        if not slug:
            return

        with self._lock:
            self._in_lane_c_turn = True
        try:
            self._maybe_auto_accept(slug, rel_path)

            for other in ordered_selected:
                if self._stop_event.is_set() or not self._resume_event.is_set():
                    return
                other_slug = other.get("slug")
                if not other_slug or other_slug == slug:
                    continue
                try:
                    self.admin.set_folder_paused(other_slug, True)
                except Exception:
                    log.exception("sequencer: failed to pause folder %s", other_slug)

            if self._stop_event.is_set() or not self._resume_event.is_set():
                return

            try:
                self.admin.set_folder_paused(slug, False)
            except Exception:
                log.exception("sequencer: failed to unpause folder %s", slug)
        finally:
            with self._lock:
                self._in_lane_c_turn = False

        base_slugs = [i.get("slug") for i in ordered_selected]
        self._wait_for_folder_sync(slug, base_slugs)

    def _maybe_auto_accept(self, slug: str, rel_path: str) -> None:
        try:
            pending = self.admin.pending_folders() or {}
        except Exception:
            log.exception("sequencer: pending_folders() failed")
            return
        if not isinstance(pending, dict) or slug not in pending:
            return
        try:
            offered_by = (pending.get(slug) or {}).get("offeredBy") or {}
            device_id = next(iter(offered_by.keys())) if offered_by else ""
            local_path = str(Path(self.local_root) / "Projects" / rel_path)
            self.admin.accept_folder(
                slug, label=rel_path, local_path=local_path, offered_by_device_id=device_id
            )
        except Exception:
            log.exception("sequencer: accept_folder(%s) failed", slug)

    def _wait_for_folder_sync(self, slug: str, base_slugs: list[str]) -> None:
        start = self._now()
        while True:
            if self._stop_event.is_set() or not self._resume_event.is_set():
                return
            try:
                status = self.admin.folder_status(slug) or {}
                need = int((status or {}).get("needTotalItems", 0) or 0)
            except Exception:
                log.exception("sequencer: folder_status(%s) failed", slug)
                return  # can't tell -- don't block the whole rotation on it
            if need == 0:
                return
            if self._now() - start >= self.project_rotation_seconds:
                return

            new_selection, _source = self.selection.get()
            if new_selection:
                new_slugs = [i.get("slug") for i in _sort_by_position(new_selection)]
                if new_slugs != base_slugs:
                    return

            if self._interruptible_wait(self.folder_status_poll_seconds):
                return

    # -- interruptible waits -----------------------------------------------------
    def _interruptible_wait(self, seconds: float) -> bool:
        """Sleep up to `seconds`, breaking early on stop() or pause().
        Returns True if the caller should stop what it's doing."""
        deadline = self._now() + seconds
        while True:
            if self._stop_event.is_set() or not self._resume_event.is_set():
                return True
            remaining = deadline - self._now()
            if remaining <= 0:
                return False
            chunk = min(remaining, _POLL_CHUNK_SECONDS)
            if self._stop_event.wait(chunk):
                return True

    def _wait_or_wake(self, seconds: float) -> bool:
        """Sleep up to `seconds`, breaking early on stop(), pause(), or a
        wake trigger (notify_change()/trigger_pass_now()/resume()). Returns
        True only if the caller should stop the whole loop (stop() called)."""
        deadline = self._now() + seconds
        while True:
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
            chunk = min(remaining, _POLL_CHUNK_SECONDS)
            if self._stop_event.wait(chunk):
                return True
