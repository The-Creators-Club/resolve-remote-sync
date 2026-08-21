"""Resolve timeline watcher — Component 1 of SPEC.md's companion app.

Polls the current Resolve project/timeline every `poll_interval` seconds
(default 3s). For every video+audio timeline item, pulls the media pool
item's "File Path" clip property and classifies it (see paths.py):

  OK          -> ignored
  OUT_OF_TREE -> queued for the popup fixer (debounced per session)
  BAD_PREFIX  -> mapping-health tray notification (once per broken episode)
  MISSING     -> logged at debug level ONCE per path, plus a per-poll
                 count; no user-facing action

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
from .paths import (
    BAD_PREFIX, FOREIGN, MISSING, NON_CANONICAL, OK, OUT_OF_TREE, classify_path,
)

log = logging.getLogger("ccsync.watcher")


def _norm_key(path: str) -> str:
    return resolve_bridge._norm_path(path)


class TimelineWatcher:
    """Supervised polling loop over the current Resolve timeline.

    `on_out_of_tree(items)` is called with the *newly seen* (not-yet-ignored)
    OUT_OF_TREE items whenever there's at least one — the fixer/popup layer
    decides how to batch/present them.

    `on_mapping_warning(item)` is called ONCE per broken-mapping episode,
    with the first BAD_PREFIX item of it — the tray layer turns this into a
    notification, and the notification names the mapping, not the clip
    (comp-resolve-5, 2026-08-21). Every further BAD_PREFIX path in the same
    episode gets a log line here instead. Re-armed when the mapping recovers.

    `on_non_canonical(items)` is called with newly seen NON_CANONICAL items —
    in-tree clips stored under the local spelling. Offered ONCE per path per
    process: the fix (an auto-ReplaceClip to the canonical spelling) changes
    the clip's File Path, so a fixed clip simply never reappears, and a
    refused one must not be retried every 3 s.

    `on_foreign(item)` is called once per newly seen FOREIGN path — another
    machine's private spelling, unfixable from here — for a tray warning.

    `on_bridge_state(connected, reason)` is called on EVERY poll with the
    state of the Resolve scripting link — the one callback here that is not
    edge-triggered, because its consumer measures how long a bad state has
    lasted (app._handle_bridge_state).
    """

    def __init__(
        self,
        local_root: str,
        canonical_prefix: str,
        poll_interval: float = 3.0,
        on_out_of_tree: Optional[Callable[[list[dict[str, Any]]], None]] = None,
        on_mapping_warning: Optional[Callable[[dict[str, Any]], None]] = None,
        on_non_canonical: Optional[Callable[[list[dict[str, Any]]], None]] = None,
        on_foreign: Optional[Callable[[dict[str, Any]], None]] = None,
        ignore_tracker: Optional[IgnoreTracker] = None,
        get_timeline_items: Optional[Callable[[], dict[str, Any]]] = None,
        on_project_changed: Optional[Callable[[str], None]] = None,
        ignored_projects: Optional[list[str]] = None,
        root_present_fn: Optional[Callable[[], bool]] = None,
        on_bridge_state: Optional[Callable[[bool, str], None]] = None,
    ) -> None:
        self.local_root = local_root
        self.canonical_prefix = canonical_prefix
        self.poll_interval = poll_interval
        self._on_out_of_tree = on_out_of_tree
        self._on_mapping_warning = on_mapping_warning
        self._on_non_canonical = on_non_canonical
        self._on_foreign = on_foreign
        self._on_project_changed = on_project_changed
        # EVERY poll's bridge state, not just the transitions _note_bridge_state
        # logs: app._handle_bridge_state times a recurring warning off it, and
        # "how long has this been broken" cannot be measured from an edge.
        self._on_bridge_state = on_bridge_state
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
        # poll_timeline_items, NOT get_timeline_items: the poll cache (skip
        # the per-clip walk while the timeline's shape is unchanged, full walk
        # every 10th poll regardless) is armed for this loop alone. tray →
        # Scan whole project and the fixer act on what they are shown and go
        # through the uncached entry points.
        self._get_timeline_items = get_timeline_items or resolve_bridge.poll_timeline_items
        self._warned_mapping: set[str] = set()
        # ONE mapping-health warning per broken EPISODE, not per clip path
        # (comp-resolve-5, 2026-08-21). _warned_mapping dedupes per path, so a
        # 300-clip timeline opened before P: was mapped fired 300 identical
        # toasts on the first full poll -- and on macOS tray_native.notify is
        # a synchronous `osascript` spawn on THIS thread, so the watcher (and
        # with it the project name the dashboard reports) parked for the
        # duration while Notification Center filled with 300 copies of one
        # message. The toast never named the clip anyway: the thing an editor
        # can act on is the mapping. Cleared with _warned_mapping on recovery,
        # so a break -> fix -> break cycle still warns again.
        self._mapping_warning_sent = False
        # Once-per-process latches for the two 2026-08-12 classes. Offered
        # (not warned) is the right word for _offered_non_canonical: a
        # successful auto-relink changes the clip's File Path so the key
        # never comes back; the latch only stops a REFUSED relink being
        # retried every poll. _warned_foreign mirrors _warned_mapping, but
        # has no recovery reset -- a foreign path never heals on this
        # machine (fixing it elsewhere changes its spelling, i.e. its key).
        self._offered_non_canonical: set[str] = set()
        self._warned_foreign: set[str] = set()
        # MISSING paths already logged individually. Seen live 2026-08-13 on
        # an editor's machine (0.7.4, log_level=DEBUG): "Energy Transition" has
        # thousands of clips whose media has not synced down yet, and every
        # one of them logged its own DEBUG line every poll -- 5 MB of
        # companion.log rotated every ~25 minutes, which drowned (and then
        # rotated away) the upgrade-history lines we were trying to read
        # hours later. The per-path line is diagnostic ONCE; after that only
        # the per-poll count below is. Rebuilt from THIS poll's missing set at
        # the end of every full pass, so it cannot grow past the number of
        # clips on the open timeline and a path that recovers -- or a project
        # switch that takes it away -- re-arms its line.
        self._missing_logged: set[str] = set()
        # Most recently seen Resolve project name (see resolve_bridge's
        # "project_name" key), tracked across polls so other components
        # (the dashboard reporter) can report which project is open without
        # owning any Resolve-bridge concerns themselves. None when Resolve
        # is closed/unreachable or the bridge result didn't carry a name.
        self.last_resolve_project: Optional[str] = None
        # Bridge connection state as of the last poll, for _note_bridge_state
        # below. None = startup, i.e. the first poll always announces itself.
        self._bridge_connected: Optional[bool] = None
        self._bridge_reason: str = ""

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
            # No answer at all is a disconnection like any other -- and the
            # one whose reason is least likely to be guessable from the log.
            self._note_bridge_state(False, f"the Resolve bridge failed: {exc}")
            self.last_resolve_project = None
            return {"ok": False, "message": str(exc), "out_of_tree": 0, "mapping_warnings": 0}

        # BEFORE the ignored-project early return below: whether Resolve is
        # reachable has nothing to do with which project happens to be open.
        message = str(result.get("message") or "")
        self._note_bridge_state(
            not resolve_bridge.is_disconnection_message(message), message
        )

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
        new_non_canonical: list[dict[str, Any]] = []
        new_mapping_warnings = 0
        new_foreign_warnings = 0
        # Every MISSING key seen this poll (not just the newly logged ones):
        # it is both the pass summary's N and the next value of
        # _missing_logged -- see the log-flood note in __init__.
        missing_now: set[str] = set()
        new_missing = 0
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
            elif cls == NON_CANONICAL:
                if key in self._offered_non_canonical:
                    continue
                self._offered_non_canonical.add(key)
                item = dict(item)
                item["resolve_project_name"] = resolve_project_name
                new_non_canonical.append(item)
            elif cls == BAD_PREFIX:
                if key in self._warned_mapping:
                    continue
                self._warned_mapping.add(key)
                new_mapping_warnings += 1
                if self._mapping_warning_sent:
                    # The episode has already been reported. The PATH is still
                    # worth a log line -- it is the diagnostic half of the old
                    # per-clip warning (comp-resolve-5, 2026-08-21).
                    log.warning(
                        "clip on the canonical prefix does not resolve under "
                        "local_root either: %s", path,
                    )
                    continue
                self._mapping_warning_sent = True
                if self._on_mapping_warning is not None:
                    try:
                        self._on_mapping_warning(item)
                    except Exception:
                        log.exception("on_mapping_warning callback failed")
            elif cls == FOREIGN:
                if key in self._warned_foreign:
                    continue
                self._warned_foreign.add(key)
                new_foreign_warnings += 1
                if self._on_foreign is not None:
                    try:
                        self._on_foreign(item)
                    except Exception:
                        log.exception("on_foreign callback failed")
            elif cls == MISSING:
                missing_now.add(key)
                if key not in self._missing_logged:
                    new_missing += 1
                    log.debug("clip path missing on disk, not under local_root/prefix: %s", path)
            # OK -> nothing to do

        if missing_now:
            # The count is the signal worth having every poll ("is the sync
            # catching up?"); the paths are not. Silent when nothing is
            # missing, so a healthy rig writes nothing here at all.
            log.debug("%d clip paths missing on disk (%d new)", len(missing_now), new_missing)
        # Assignment, not update(): dropping the keys that did NOT come back
        # missing this pass is what re-arms a recovered (or switched-away)
        # path and what bounds the set. Only reached on a full poll -- an
        # early return above leaves the previous pass's set alone, so a
        # disconnected bridge does not replay every path on reconnect.
        self._missing_logged = missing_now

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
            # Re-arms the once-per-episode toast as well as the per-path keys
            # (comp-resolve-5, 2026-08-21).
            self._mapping_warning_sent = False

        if new_out_of_tree and self._on_out_of_tree is not None:
            try:
                self._on_out_of_tree(new_out_of_tree)
            except Exception:
                log.exception("on_out_of_tree callback failed")

        if new_non_canonical and self._on_non_canonical is not None:
            try:
                self._on_non_canonical(new_non_canonical)
            except Exception:
                log.exception("on_non_canonical callback failed")

        return {
            "ok": True,
            "message": "",
            "out_of_tree": len(new_out_of_tree),
            "mapping_warnings": new_mapping_warnings,
            "non_canonical": len(new_non_canonical),
            "foreign_warnings": new_foreign_warnings,
            "missing": len(missing_now),
            "missing_new": new_missing,
        }

    def _note_bridge_state(self, connected: bool, reason: str = "") -> None:
        """Say at INFO, ONCE, when the Resolve bridge comes or goes.

        This line used to be `log.debug("timeline poll: %s", ...)` on every
        failed poll, i.e. every 3 s, i.e. nothing at all at the shipped
        `log_level = "INFO"`. It hid two separate multi-hour incidents: MAC-10
        (the macOS modules path was wrong, so EVERY Resolve feature was dead
        for a whole session while the log looked perfectly healthy) and item
        19 (Resolve's own script server died at launch and never retried). A
        user-visible capability going away is not a debug detail.

        Once per TRANSITION, not once per poll: repeats stay at DEBUG (the
        callers' own lines) so a machine with Resolve shut all week does not
        write 28 000 identical INFO records. A change of REASON counts as a
        transition of its own -- "not running" and "running but not accepting
        scripting connections" ask the reader for different actions.
        """
        reason = "" if connected else str(reason or "")
        if self._on_bridge_state is not None:
            # Before the transition filter, and fault-isolated like every
            # other callback here: a consumer that raises must not cost this
            # poll its logging, let alone the rest of the cycle.
            try:
                self._on_bridge_state(connected, reason)
            except Exception:
                log.exception("on_bridge_state callback failed")
        if connected == self._bridge_connected and reason == self._bridge_reason:
            return
        self._bridge_connected, self._bridge_reason = connected, reason
        if connected:
            log.info("Resolve bridge: connected to DaVinci Resolve")
        else:
            log.info("Resolve bridge: %s", reason or "no connection")

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
