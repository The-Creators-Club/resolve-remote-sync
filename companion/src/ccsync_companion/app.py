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
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

from . import config as config_mod
from . import popup
from . import resolve_bridge
from . import upgrade as upgrade_mod
from .fixer import IgnoreTracker
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
        self._popup_snooze: dict[str, float] = {}
        self.popup_snooze_seconds = float(cfg.get("popup_snooze_seconds", 300))
        # popup.show_popup blocks (it runs a Tk mainloop) and Tk is not
        # thread-safe -- this guards against the passive watcher-driven
        # popup and the user-initiated "Scan whole project" tray action
        # both trying to open a Tk root at once.
        self._popup_active_lock = threading.Lock()
        self._paused = False
        self._stop_event = threading.Event()
        self._watcher_thread: Optional[threading.Thread] = None
        self._tray_icon = None
        # Populated by run(); surfaced in the tray tooltip so a misconfigured
        # install is visible without opening the log.
        self.config_problems: list[str] = []

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
            self.selection_client = SelectionClient(cfg, self._state_dir)
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
        )

        # Resolve media-pool BIN tree cache (get_media_tree()) -- refreshed
        # on its own slow background thread; see _refresh_media_tree_once().
        self.media_tree_refresh_interval = float(cfg.get("media_tree_refresh_interval", 120))
        self._media_tree_cache: dict[str, list[dict[str, Any]]] = {}
        self._media_tree_lock = threading.Lock()
        self._media_tree_stop_event = threading.Event()
        self._media_tree_thread: Optional[threading.Thread] = None

        # Self-upgrade channel (upgrade.py): availability is fed by the
        # reporter's response callback below and by sign_in()'s verify
        # response; the tray surfaces it ("Update now") and apply() swaps
        # the exe + restarts via shutdown().
        self.upgrade = upgrade_mod.UpgradeManager(
            cfg,
            request_shutdown=self.shutdown,
            on_available=lambda info: self._notify_tray(
                f"Update available → v{info['version']} — use the tray menu to install",
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
        )
        self.watcher = TimelineWatcher(
            local_root=cfg["local_root"],
            canonical_prefix=cfg["canonical_prefix"],
            poll_interval=float(cfg.get("poll_interval", 3)),
            on_out_of_tree=self._handle_out_of_tree,
            on_mapping_warning=self._handle_mapping_warning,
            ignore_tracker=self.ignore_tracker,
            on_project_changed=self._on_resolve_project_changed,
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
        state_dir = Path(cfg.get("log_path", "~/.ccsync/companion.log")).expanduser().parent / "state"
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
            transfers=int(cfg.get("transfers", 4)),
            scan_interval=float(cfg.get("scan_interval_up", 300)),
            watch_debounce_seconds=float(cfg.get("watch_debounce_seconds", 10)),
            state_dir=state_dir,
            on_change=on_change,
        )
        lane_b = RcloneLane(
            direction=DIRECTION_DOWN,
            local_root=cfg["local_root"],
            remote=cfg["remote"],
            remote_root=cfg["remote_root"],
            rclone_path=cfg.get("rclone_path", "rclone"),
            transfers=int(cfg.get("transfers", 4)),
            scan_interval=float(cfg.get("scan_interval_down", 120)),
            state_dir=state_dir,
        )
        lane_c = SyncthingLane(
            base_url=cfg.get("syncthing_url", "http://127.0.0.1:8384"),
            api_key=cfg.get("syncthing_api_key", ""),
            expected_folder_ids=cfg.get("syncthing_folder_ids", []),
        )
        self._lane_a = lane_a
        self._lane_b = lane_b
        self._lane_c = lane_c
        return [lane_a, lane_b, lane_c]

    # -- watcher callbacks -----------------------------------------------
    def _handle_out_of_tree(self, items: list[dict[str, Any]]) -> None:
        from .watcher import _norm_key

        now = time.monotonic()
        fresh = []
        for item in items:
            key = _norm_key(item.get("file_path", ""))
            shown_at = self._popup_snooze.get(key)
            if shown_at is not None and (now - shown_at) < self.popup_snooze_seconds:
                continue
            fresh.append(item)
        if not fresh:
            return

        if not bool(self.config.get("popup_enabled", True)):
            log.debug("popup suppressed (popup_enabled=false): %d clip(s) outside %s",
                      len(fresh), self.config.get("local_root"))
            return

        log.info("popup: %d clip(s) outside %s", len(fresh), self.config.get("local_root"))
        for item in fresh:
            self._popup_snooze[_norm_key(item.get("file_path", ""))] = now

        self._show_out_of_tree_popup(fresh)

    def _handle_mapping_warning(self, item: dict[str, Any]) -> None:
        path = item.get("file_path", "")
        msg = (
            f"clip on canonical prefix ({self.config.get('canonical_prefix')}) doesn't "
            f"resolve under local_root ({self.config.get('local_root')}): {path}"
        )
        log.warning(msg)
        self._notify_tray(msg, "ccsync-companion: mapping warning")

    # -- popup plumbing (shared by the passive watcher and the manual
    # "Scan whole project" tray action) -------------------------------
    def _notify_tray(self, msg: str, title: str = "ccsync-companion") -> None:
        if self._tray_icon is not None:
            try:
                self._tray_icon.notify(msg, title)
            except Exception:
                log.debug("tray notify failed (backend may not support it)")

    def _show_out_of_tree_popup(self, items: list[dict[str, Any]]) -> None:
        """Build server_roots and show the popup for `items`. Blocks until
        the dialog closes (popup.show_popup runs a Tk mainloop), so this is
        guarded by `_popup_active_lock`: only one popup -- whether raised by
        the passive watcher or a user-initiated "Scan whole project" -- may
        be open at a time, since Tk is not safe to touch from two threads
        at once. Safe to call from any thread."""
        if not self._popup_active_lock.acquire(blocking=False):
            log.info("popup already open -- skipping (%d clip(s) not shown)", len(items))
            self._notify_tray("A popup is already open — close it first.", "ccsync-companion")
            return
        try:
            server_roots: Optional[dict[str, str]] = None
            if self.selection_client is not None and hasattr(self.selection_client, "get_project_roots"):
                try:
                    server_roots = self.selection_client.get_project_roots()
                except Exception:
                    log.exception("get_project_roots() failed")
                    server_roots = None

            popup.show_popup(
                items, self.config["local_root"], self.editor_identity() or "", self.ignore_tracker,
                project_prefix=self.config.get("active_project", ""),
                server_roots=server_roots,
            )
        finally:
            self._popup_active_lock.release()

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

    def _server_roots(self) -> Optional[dict[str, str]]:
        if self.selection_client is not None and hasattr(self.selection_client, "get_project_roots"):
            try:
                return self.selection_client.get_project_roots()
            except Exception:
                log.exception("get_project_roots() failed")
        return None

    def consolidate_project(self) -> None:
        """User-initiated (tray): onboard a pre-existing project. Scans the
        whole media pool, plans copying every out-of-tree clip into the
        canonical project folder, dry-runs both rclone lanes against the NAS
        for a reconciliation report, and -- on confirm -- consolidates
        (copy+relink) then uploads originals and downloads proxies for the
        open project. Runs on the tray thread; guarded by the popup lock so
        it can't collide with an open fixer dialog."""
        from . import consolidate

        result = resolve_bridge.get_media_pool_items()
        if not result.get("ok"):
            message = result.get("message", "unknown error")
            log.warning("consolidate: %s", message)
            self._notify_tray(f"Consolidate failed: {message}", "ccsync-companion")
            return

        local_root = self.config.get("local_root", "")
        canonical_prefix = self.config.get("canonical_prefix", "")
        resolve_project = result.get("project_name", "") or ""
        server_roots = self._server_roots()

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

        if not self._popup_active_lock.acquire(blocking=False):
            self._notify_tray("A popup is already open — close it first.", "ccsync-companion")
            return
        try:
            plan = consolidate.plan_local_consolidation(
                out_of_tree, local_root, self.editor_identity() or "",
                project_prefix, server_roots,
            )
            self._notify_tray("Checking the NAS…", "ccsync-companion: consolidate")
            reconcile = consolidate.reconcile_with_nas(self.config, subpath, self._state_dir)
            report = consolidate.build_report(plan, reconcile)
            if plan["count"] == 0 and reconcile.get("ok") and \
                    (reconcile["uploads"] or {}).get("count", 0) == 0:
                self._notify_tray("Nothing to consolidate — this project is already tidy.",
                                  "ccsync-companion")
                return
            if not popup.confirm_dialog("CONSOLIDATE PROJECT", report, ok_label="CONSOLIDATE & UPLOAD"):
                log.info("consolidate: cancelled by user")
                return

            log.info("consolidate: copying %d clip(s) into %s", plan["count"], project_prefix or "tree")
            results = consolidate.run_consolidation(plan["ops"], local_root)
            failures = [r for r in results if not r.get("ok")]
            if failures:
                log.warning("consolidate: %d/%d copies failed", len(failures), len(results))
                self._notify_tray(
                    f"{len(results) - len(failures)}/{len(results)} consolidated, "
                    f"{len(failures)} failed — see log.", "ccsync-companion")
        finally:
            self._popup_active_lock.release()

        # Upload originals + pull proxies for this project (outside the popup
        # lock -- these are long rclone runs, not UI). One-shot, regardless of
        # managed/sequencer state.
        self._notify_tray("Uploading originals to the NAS…", "ccsync-companion: consolidate")
        try:
            self._lane_a.run_once(subpath)
        except Exception:
            log.exception("consolidate: lane A upload failed")
        if self._lane_b_enabled:
            try:
                self._lane_b.run_once(subpath)
            except Exception:
                log.exception("consolidate: lane B proxy pull failed")
        self._notify_tray("Consolidate & upload finished.", "ccsync-companion: consolidate")

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

        Idempotent and cheap to call whenever identity state changes
        (constructor, sign_in(), sign_out()) rather than threading role
        through every call site that currently reads self._sync_enabled.
        """
        role = self.identity.role
        if role is None:
            self._sync_enabled = self._configured_sync_enabled
        else:
            self._sync_enabled = (role != "base")

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
        return self.config.get("editor_name", "")

    def _lane_pending_login_detail(self) -> str:
        return 'sign in required -- use the tray\'s "Sign in..." to authenticate before syncing'

    def _mark_lanes_pending_login(self) -> None:
        for lane in self.lanes:
            try:
                with lane._lock:
                    lane._status.detail = self._lane_pending_login_detail()
            except Exception:
                pass

    def _start_lanes(self) -> None:
        """Actually start the sync lanes/sequencer, per sync_enabled/managed
        mode. Extracted from start() so on_signed_in() can (re)run it once a
        require_login gate clears, without repeating the reporter/manifest/
        watcher startup that only ever needs to happen once."""
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
        if self._require_login and not self.identity.valid():
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
        self._notify_tray(f"Updating to v{info['version']}…", "ccsync-companion")
        if not self.upgrade.apply():
            self._notify_tray(
                "Update failed — still running the current version. See companion.log.",
                "ccsync-companion",
            )

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

    def toggle_pause(self) -> None:
        self._paused = not self._paused
        if not self._sync_enabled:
            log.info("pause toggled but sync_enabled=false -- nothing to pause")
            return
        if self._managed and self.sequencer is not None:
            try:
                self.sequencer.pause() if self._paused else self.sequencer.resume()
            except Exception:
                log.exception("toggle_pause: sequencer failed")
            # Lane C's poll loop is read-only status reporting -- it keeps
            # running regardless of pause state.
        else:
            for lane in self.lanes:
                try:
                    lane.stop() if self._paused else lane.start()
                except Exception:
                    log.exception("toggle_pause: lane %s failed", getattr(lane, "name", lane))
        log.info("sync %s", "paused" if self._paused else "resumed")

    # -- lifecycle ---------------------------------------------------
    def start(self) -> None:
        if self._require_login and not self.identity.valid():
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
        self._stop_event.clear()
        self._watcher_thread = threading.Thread(
            target=self.watcher.run, args=(self._stop_event,), name="ccsync-watcher", daemon=True
        )
        self._watcher_thread.start()

    def shutdown(self) -> None:
        self._stop_event.set()
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

    def run(self) -> None:
        setup_logging(self.config)
        log.info("ccsync-companion v%s starting", config_mod.VERSION)
        log.info("config: %s", config_mod.CONFIG_PATH)
        # Remove the .old a previous self-upgrade left behind (see upgrade.py).
        # Its presence means THIS start is the first on a freshly-upgraded
        # build -- surface that as a toast once the tray exists below.
        just_upgraded = upgrade_mod.cleanup_old_exe()

        # A half-configured install is the single most common failure mode and
        # is otherwise completely silent — nothing syncs and no lane says why.
        errors, warnings = config_mod.validate_config(self.config)
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
        self.config_problems = errors

        self.start()

        try:
            from . import tray as tray_mod

            self._tray_icon = tray_mod.start_tray(self)
            log.info("tray icon started")
        except ImportError:
            self._tray_icon = None
            log.warning("pystray/Pillow not installed — running headless (Ctrl+C to stop)")

        if just_upgraded:
            log.info("self-upgrade to v%s completed", config_mod.VERSION)
            # Slight delay: the tray icon thread has only just started and
            # Windows drops notify() calls for icons not yet registered.
            timer = threading.Timer(3.0, lambda: self._notify_tray(
                f"Update complete — now running v{config_mod.VERSION}.",
                "ccsync-companion",
            ))
            timer.daemon = True
            timer.start()

        try:
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


def run() -> None:
    cfg = config_mod.load_config()
    app = CompanionApp(cfg)
    app.run()


if __name__ == "__main__":
    run()
