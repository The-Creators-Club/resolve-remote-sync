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
    ) -> None:
        self.local_root = local_root
        self.canonical_prefix = canonical_prefix
        self.poll_interval = poll_interval
        self._on_out_of_tree = on_out_of_tree
        self._on_mapping_warning = on_mapping_warning
        self.ignore_tracker = ignore_tracker if ignore_tracker is not None else IgnoreTracker()
        self._get_timeline_items = get_timeline_items or resolve_bridge.get_timeline_items
        self._warned_mapping: set[str] = set()

    def poll_once(self) -> dict[str, Any]:
        """Run one poll cycle. Returns a small summary dict; never raises."""
        try:
            result = self._get_timeline_items()
        except Exception as exc:  # belt and braces on top of resolve_bridge's own catch-all
            log.debug("get_timeline_items raised: %s", exc)
            return {"ok": False, "message": str(exc), "out_of_tree": 0, "mapping_warnings": 0}

        if not result.get("ok"):
            log.debug("timeline poll: %s", result.get("message"))
            return {"ok": False, "message": result.get("message", ""), "out_of_tree": 0, "mapping_warnings": 0}

        new_out_of_tree: list[dict[str, Any]] = []
        new_mapping_warnings = 0

        for item in result.get("items", []):
            path = item.get("file_path", "")
            if not path:
                continue
            cls = classify_path(path, self.local_root, self.canonical_prefix)
            key = _norm_key(path)

            if cls == OUT_OF_TREE:
                if self.ignore_tracker.is_ignored(path):
                    continue
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
