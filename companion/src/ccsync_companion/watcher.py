"""Resolve timeline watcher — Component 1 of SPEC.md's companion app.

Polls the current Resolve project/timeline every `poll_interval` seconds
(default 3s). For every video+audio timeline item, pulls the media pool
item's "File Path" clip property and classifies it (see paths.py):

  OK          -> ignored
  OUT_OF_TREE -> queued for the popup fixer (debounced per session)
  BAD_PREFIX  -> mapping-health tray notification (debounced per session)
  MISSING     -> logged at debug level, no user-facing action

The watcher never raises: resolve_bridge already returns friendly dicts on
every Resolve-side failure, and this module wraps its own loop body in
try/except so one bad poll never kills the supervised thread.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Optional

from . import canon
from . import config as config_mod
from . import resolve_bridge
from .fixer import IgnoreTracker
from .paths import BAD_PREFIX, MISSING, OK, OUT_OF_TREE, classify_path

log = logging.getLogger("ccsync.watcher")


def _norm_key(path: str) -> str:
    return resolve_bridge._norm_path(path)


class TimelineWatcher:
    """Supervised polling loop over the current Resolve timeline.

    `on_out_of_tree(items)` is called with the *newly seen* (not-yet-ignored)
    OUT_OF_TREE items whenever there's at least one — the fixer/popup layer
    decides how to batch/present them.

    `on_mapping_warning(item)` is called once per newly seen BAD_PREFIX path
    (i.e. debounced the same way OUT_OF_TREE items are) — the tray layer
    turns this into a notification.
    """

    def __init__(
        self,
        local_root: str,
        canonical_prefix: str,
        poll_interval: float = 3.0,
        on_out_of_tree: Optional[Callable[[list[dict[str, Any]]], None]] = None,
        on_mapping_warning: Optional[Callable[[dict[str, Any]], None]] = None,
        ignore_tracker: Optional[IgnoreTracker] = None,
        get_timeline_items: Optional[Callable[[], dict[str, Any]]] = None,
        on_project_changed: Optional[Callable[[str], None]] = None,
        ignored_projects: Optional[list[str]] = None,
        root_present_fn: Optional[Callable[[], bool]] = None,
    ) -> None:
        self.local_root = local_root
        self.canonical_prefix = canonical_prefix
        self.poll_interval = poll_interval
        self._on_out_of_tree = on_out_of_tree
        self._on_mapping_warning = on_mapping_warning
        self._on_project_changed = on_project_changed
        # Last NON-None project name seen -- deliberately NOT cleared when
        # the bridge flaps to None (Resolve restarting, transient failure),
        # so name -> None -> same name never refires on_project_changed.
        self._last_seen_project: Optional[str] = None
        # Scratch/utility project names (config `ignored_resolve_projects`,
        # normalized): the whole poll pretends these aren't open -- nothing
        # is reported, prompted, or popped for them. Kills the Blackmagic
        # Proxy Generator's helper project nagging the base rig. Matching is
        # config_mod.is_ignored_project(), i.e. numbered duplicates ("New
        # Doc 1", "New Doc 2") count as the same scratch project -- the BPG
        # counts them up, and an exact-match list let every new number
        # through (seen live 2026-07-25).
        self._ignored_projects = config_mod.normalize_ignored_projects(ignored_projects)
        # "Is local_root actually here?" (app.root_is_present -> root_guard.py).
        # A macOS editor's tree lives on an external SSD that gets unplugged,
        # and while it is out EVERY clip on the timeline misclassifies: the
        # ones on the canonical prefix as BAD_PREFIX (a mapping-health warning
        # per clip, none of which names the real problem) and the rest as
        # OUT_OF_TREE (a popup offering to copy media into a directory that
        # does not exist). None = no gate, i.e. the behaviour before this.
        self._root_present_fn = root_present_fn
        self.ignore_tracker = ignore_tracker if ignore_tracker is not None else IgnoreTracker()
        self._get_timeline_items = get_timeline_items or resolve_bridge.get_timeline_items
        self._warned_mapping: set[str] = set()
        # Most recently seen Resolve project name (see resolve_bridge's
        # "project_name" key), tracked across polls so other components
        # (the dashboard reporter) can report which project is open without
        # owning any Resolve-bridge concerns themselves. None when Resolve
        # is closed/unreachable or the bridge result didn't carry a name.
        self.last_resolve_project: Optional[str] = None

    def poll_once(self) -> dict[str, Any]:
        """Run one poll cycle. Returns a small summary dict; never raises."""
        if not self._root_is_present():
            # Deliberately BEFORE the Resolve call: last_resolve_project is
            # left alone (Resolve is still open with the project the editor is
            # working on -- it is the media that is unreachable, not the app),
            # so the dashboard keeps showing the truth while the drive is out.
            return {"ok": False, "message": "local root is not available (drive "
                    "disconnected?)", "out_of_tree": 0, "mapping_warnings": 0}
        try:
            result = self._get_timeline_items()
        except Exception as exc:  # belt and braces on top of resolve_bridge's own catch-all
            log.debug("get_timeline_items raised: %s", exc)
            self.last_resolve_project = None
            return {"ok": False, "message": str(exc), "out_of_tree": 0, "mapping_warnings": 0}

        project_name = result.get("project_name") or None
        if project_name is not None and config_mod.is_ignored_project(
            project_name, self._ignored_projects
        ):
            log.debug("ignoring Resolve project %r (ignored_resolve_projects)", project_name)
            self.last_resolve_project = None
            return {"ok": True, "message": "ignored project", "out_of_tree": 0,
                    "mapping_warnings": 0}
        self.last_resolve_project = project_name
        if (
            self.last_resolve_project is not None
            and self.last_resolve_project != self._last_seen_project
        ):
            self._last_seen_project = self.last_resolve_project
            if self._on_project_changed is not None:
                try:
                    self._on_project_changed(self.last_resolve_project)
                except Exception:
                    log.exception("on_project_changed callback failed")

        if not result.get("ok"):
            log.debug("timeline poll: %s", result.get("message"))
            return {"ok": False, "message": result.get("message", ""), "out_of_tree": 0, "mapping_warnings": 0}

        new_out_of_tree: list[dict[str, Any]] = []
        new_mapping_warnings = 0
        resolve_project_name = result.get("project_name", "")
        # Did anything under the canonical prefix classify as healthy this
        # poll? See the _warned_mapping reset below.
        prefix_healthy = False
        prefix_broken = False

        for item in result.get("items", []):
            path = item.get("file_path", "")
            if not path:
                continue
            cls = classify_path(path, self.local_root, self.canonical_prefix)
            # _norm_key normalizes in the spelling the path is WRITTEN in
            # (canon.norm -> ntpath for a canonical "P:\..." string, the
            # host's os.path for a real local one), so the warn-once key
            # folds case and separators on a Mac too. It used to be the raw
            # host normalization, which on posix folded neither -- so one
            # broken mapping could warn once per spelling Resolve happened to
            # return. Membership is still canon.is_canonical's job, not this
            # key's.
            key = _norm_key(path)
            under_prefix = canon.is_canonical(path, self.canonical_prefix)
            if under_prefix:
                # OK and MISSING both mean the prefix RESOLVES (paths.py
                # probes the prefix, not the file) -- i.e. the mapping is
                # healthy and the clip is simply not downloaded.
                if cls in (OK, MISSING):
                    prefix_healthy = True
                elif cls == BAD_PREFIX:
                    prefix_broken = True

            if cls == OUT_OF_TREE:
                if self.ignore_tracker.is_ignored(path):
                    continue
                # Copy rather than mutate: `item` may be a shared/reused
                # object from the caller's test double or a real Resolve
                # wrapper -- popup.py needs to know which project was open
                # in Resolve when this clip was seen (fixer.match_project_dir)
                # without the watcher owning any popup-layer concerns.
                item = dict(item)
                item["resolve_project_name"] = resolve_project_name
                new_out_of_tree.append(item)
            elif cls == BAD_PREFIX:
                if key in self._warned_mapping:
                    continue
                self._warned_mapping.add(key)
                new_mapping_warnings += 1
                if self._on_mapping_warning is not None:
                    try:
                        self._on_mapping_warning(item)
                    except Exception:
                        log.exception("on_mapping_warning callback failed")
            elif cls == MISSING:
                log.debug("clip path missing on disk, not under local_root/prefix: %s", path)
            # OK -> nothing to do

        if prefix_healthy and not prefix_broken and self._warned_mapping:
            # The mapping is working again. Warning once per PROCESS lifetime
            # meant a break -> fix -> break cycle (the editor reboots without
            # the login subst, fixes it, then it fails again next week) was
            # never reported a second time -- and the set grew without bound
            # (AUDIT_2 L-17). Clearing on recovery re-arms the warning and
            # bounds the set at the same time.
            log.info(
                "mapping to %s is healthy again -- re-arming mapping-health warnings",
                self.canonical_prefix,
            )
            self._warned_mapping.clear()

        if new_out_of_tree and self._on_out_of_tree is not None:
            try:
                self._on_out_of_tree(new_out_of_tree)
            except Exception:
                log.exception("on_out_of_tree callback failed")

        return {
            "ok": True,
            "message": "",
            "out_of_tree": len(new_out_of_tree),
            "mapping_warnings": new_mapping_warnings,
        }

    def _root_is_present(self) -> bool:
        """False only when the gate POSITIVELY says the tree is gone. A
        missing or raising callable is "carry on": a broken gate must cost a
        few misclassified clips, never the whole watcher."""
        if self._root_present_fn is None:
            return True
        try:
            return bool(self._root_present_fn())
        except Exception:
            log.debug("root-present check failed -- polling anyway", exc_info=True)
            return True

    def run(self, stop_event: threading.Event) -> None:
        """Blocking supervised loop — run this in its own thread."""
        log.info("timeline watcher started (poll_interval=%ss)", self.poll_interval)
        while not stop_event.is_set():
            try:
                self.poll_once()
            except Exception:
                log.exception("timeline watcher poll cycle failed")
            stop_event.wait(self.poll_interval)
        log.info("timeline watcher stopped")
