"""Resolve timeline watcher — Component 1 of SPEC.md's companion app.

Polls the current Resolve project/timeline every `poll_interval` seconds
(default 3s). For every video+audio timeline item, pulls the media pool
item's "File Path" clip property and classifies it (see paths.py):

  OK          -> ignored
  OUT_OF_TREE -> queued for the popup fixer (debounced per session)
  BAD_PREFIX  -> mapping-health tray notification (once per broken episode)
  MISSING     -> logged at debug level ONCE per path, plus a per-poll
                 count; no user-facing action. One exception since
                 2026-09-17 (audit F4): an offline b-roll ARCHIVE original
                 that has a proxy on disk, or is a ledgered stand-in, is
                 still classified MISSING and is counted and listed
                 NOWHERE -- it is the designed steady state of a
                 proxy-only b-roll insert, and the count rides every
                 report and the tray's diagnostics line. CR-317
                 (2026-09-24) widened that to every in-tree clip: an
                 original that is not on this computer but whose proxy is
                 (and Resolve has not refused that proxy) is the designed
                 steady state on a remote rig, and is counted and listed
                 nowhere either. MISSING in the count now means "neither
                 the original nor a usable proxy is here".

The watcher never raises: resolve_bridge already returns friendly dicts on
every Resolve-side failure, and this module wraps its own loop body in
try/except so one bad poll never kills the supervised thread.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from . import broll_standins
from . import canon
from . import config as config_mod
from . import proxy_relink
from . import resolve_bridge
from .fixer import IgnoreTracker
from .paths import (
    BAD_PREFIX, FOREIGN, MISSING, NON_CANONICAL, OK, OUT_OF_TREE, classify_path,
)

log = logging.getLogger("ccsync.watcher")

# How many MISSING clips a surface is handed (RES-19). The COUNT is
# last_counts["missing"] and is exact; this list is evidence, and a project
# whose media has not arrived yet has thousands of them.
MAX_MISSING_REPORTED = 50
# comp-sync-13 (2026-09-11): the shortest gap between two offers of the SAME
# non-canonical path after a failed relink. Matched to
# resolve_journal.allow_automatic's 900 s window, which is what refuses the
# burst: an offer the limiter cannot act on is an entry on a pending list
# nobody drains.
REARM_COOLDOWN_SECONDS = 900.0
# ...and the re-arm book itself is bounded, like every other set in here.
MAX_REARM_TRACKED = 2000
# comp-app-4 (2026-09-11): how many refused relinks are remembered. Deliberately
# above the report's own cap of 50 (a surface may want more than it sends) and
# far below a media pool, which is what this dict could reach on the one
# machine that produces refusals in bulk.
MAX_NON_CANONICAL_REFUSED = 200

# comp-resolve-7 (2026-09-18): how long the archive exemption's verdict about
# one path stands. Long enough that a 3 s poll asks the filesystem about a
# clip once a minute instead of twenty times, short enough that a proxy
# landing (or being deleted) shows up in the missing count while the editor
# still remembers doing it.
EXEMPT_TTL_SECONDS = 60.0
EXEMPT_MEMO_MAX = 4000


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
        moved_lookup: Optional[Callable[[str], Optional[dict[str, Any]]]] = None,
        on_moved_clip: Optional[Callable[[dict[str, Any], dict[str, Any]], None]] = None,
        archive_exempt_fn: Optional[Callable[[str], bool]] = None,
        proxy_held_fn: Optional[Callable[[str], bool]] = None,
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
        # RES-10 (resilience sweep 2026-08-28): a MISSING clip whose path this
        # machine moved on the server's instruction is not a mystery. The
        # lookup is file_moves.FileMoveLedger.moved_to; None means the whole
        # question is off (an app built without a ledger, and every test that
        # does not care), and a MISSING clip is the DEBUG line it always was.
        self._moved_lookup = moved_lookup
        self._on_moved_clip = on_moved_clip
        # Audit F4 (docs/BROLL_PROXY_TIERS_PLAN.md section 6, 2026-09-17): an
        # offline b-roll ORIGINAL that has a proxy is the designed steady
        # state on a remote rig, not a problem. classify_path still answers
        # MISSING for it -- the stored path is `P:\...`, which is not under
        # local_root -- but since RES-12/RES-19 that count and up to 50 paths
        # ride every report as sync_guard.resolve_health and the tray prints
        # "N missing on disk". Every proxy-only b-roll insert would add one.
        # The test is per path and cached per poll; see _archive_exempt.
        self._archive_exempt_fn = archive_exempt_fn
        # comp-resolve-7 (2026-09-18): the archive exemption's answer, kept
        # ACROSS polls with a short TTL.
        #
        # The verdict was cached per poll only, and the poll is every 3 s. A
        # remote rig with a proxy-only b-roll timeline is the designed steady
        # state in which every archive clip is MISSING on every poll, so a
        # 200-clip timeline cost the ledger's stat plus the media file's stat
        # plus up to four find_proxy_on_disk probes each -- roughly a
        # thousand filesystem probes every three seconds, on the thread the
        # popup and fixer latency depend on, for a diagnostic count. The TTL
        # is deliberately short: the answer flips when a proxy lands or is
        # deleted, and a long memory would keep a genuinely missing clip out
        # of the count.
        self._exempt_memo: dict[str, tuple[float, bool]] = {}
        # CR-317 (2026-09-24): the same question for PROJECT footage. Seen
        # live on ruskin's DESKTOP-LQQ41TC ("Reproductive Rights Fight",
        # timeline "Ordered V7"): the fleet grid said "57 clips Resolve cannot
        # find", and every one was a camera or YouTube original that a remote
        # editor by design never holds (lane B brings proxies only, lane C
        # excludes video), each with its proxy attached, playing, and on his
        # disk at the NAS size. Audit F4 exempted the ARCHIVE only, so the
        # count every remote rig reported was simply "the timeline", and the
        # one clip with nothing to play was hidden among fifty that were
        # fine. Asked of the FILESYSTEM for the reason _archive_exempt gives
        # (a timeline item carries no proxy state; the media pool walk that
        # reads it runs every 120 s, not every 3 s), plus the relink pass's
        # refusal memory, so a proxy Resolve would not attach does not count
        # as one. Remembered with the same TTL and cap as the archive answer.
        # None = the default rule below; tests inject.
        self._proxy_held_fn = proxy_held_fn
        self._proxy_memo: dict[str, tuple[float, bool]] = {}
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
        # The last FULL poll's totals and when it finished (UX-4). None until
        # one has completed: "we have not looked yet" is not "nothing is
        # wrong", and app.resolve_health() renders the two differently.
        self.last_counts: Optional[dict[str, int]] = None
        self.last_scan_at: Optional[str] = None
        # Bridge connection state as of the last poll, for _note_bridge_state
        # below. None = startup, i.e. the first poll always announces itself.
        self._bridge_connected: Optional[bool] = None
        self._bridge_reason: str = ""
        # RES-19 (usability sweep 2026-09-03). Two holes, one cause: the
        # watcher knew and nobody could ask.
        #
        #  * MISSING was a DEBUG line and a count. "Media Offline" is the
        #    thing an editor actually notices, so the PATHS are kept here
        #    (bounded, rebuilt from each full pass like _missing_logged) for
        #    app.resolve_health() to render.
        #  * _offered_non_canonical is add-only, so a relink refused for a
        #    transient reason (Resolve busy, the file locked for a second)
        #    was never offered again for the life of the process. The relink
        #    caller now calls rearm_non_canonical() on a failure -- only a
        #    SUCCESS may latch -- and the refusal is kept here so a surface
        #    can name it.
        self._missing_items: list[dict[str, str]] = []
        self._non_canonical_refused: dict[str, dict[str, str]] = {}
        # comp-sync-13 (2026-09-11): when a re-armed path may be offered
        # again. RES-19's rearm is unconditional, so on a machine whose
        # canonical_prefix is wrong every 3 s poll re-offered all of them and
        # app._handle_non_canonical's unprompted branch appended them to its
        # pending list again, while resolve_journal.allow_automatic (900 s)
        # refused the burst that would have drained it. The cooldown is that
        # window: re-offering sooner cannot be acted on anyway.
        self._rearm_due: dict[str, float] = {}
        self._rearm_clock = time.monotonic

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

        # UX-4 / RES-12 (resilience sweep 2026-08-28). These three ride
        # `sync_guard.resolve_health` and are deliberately TOTALS for this
        # poll, where the four counters beside them are per-poll deltas
        # (warn-once, offer-once). An out-of-tree clip the editor skipped is
        # still an out-of-tree clip, and the whole point of reporting it is
        # that nobody was going to hear about it otherwise.
        total_out_of_tree = 0
        total_bad_prefix = 0
        new_out_of_tree: list[dict[str, Any]] = []
        new_non_canonical: list[dict[str, Any]] = []
        new_mapping_warnings = 0
        new_foreign_warnings = 0
        # Every MISSING key seen this poll (not just the newly logged ones):
        # it is both the pass summary's N and the next value of
        # _missing_logged -- see the log-flood note in __init__.
        missing_now: set[str] = set()
        # The same clips as `missing_now`, in the spelling a person reads, and
        # capped: a project whose media has not synced down yet has thousands
        # (see the log-flood note in __init__), and this rides a tray render.
        missing_items: list[dict[str, str]] = []
        new_missing = 0
        # One answer per path per poll: a timeline item appears twice (video
        # and audio) and the test stats a file.
        exempt_cache: dict[str, bool] = {}
        # CR-317: the proxy question's own per-poll answers. NOT exempt_cache:
        # both are keyed by path, and the archive's False for a project clip
        # would be read back as "no proxy here".
        held_cache: dict[str, bool] = {}
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
                total_out_of_tree += 1
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
                # comp-sync-13: offered once, then only when a re-arm has
                # come due.
                if key in self._offered_non_canonical and not self._rearm_is_due(key):
                    continue
                # comp-resolve-b-2 (2026-09-11b): the OFFER arms the next one.
                # Only a FAILED relink used to lift the latch, so when
                # resolve_journal.allow_automatic refused the whole burst
                # nothing was attempted, nothing was re-armed, and the clips
                # sat on app's pending queue that no timer drains -- until the
                # editor happened to click SCAN WHOLE PROJECT, which only a
                # log line they never read tells them to do. Re-offering on
                # the same 900 s cooldown is what drains it: the caller
                # de-dupes against its pending list (comp-sync-13), so the
                # cost of a re-offer the limiter refuses again is one
                # dictionary lookup.
                self._arm_rearm(key)
                self._offered_non_canonical.add(key)
                item = dict(item)
                item["resolve_project_name"] = resolve_project_name
                new_non_canonical.append(item)
            elif cls == BAD_PREFIX:
                total_bad_prefix += 1
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
                if self._archive_exempt(path, exempt_cache):
                    # Counted nowhere and listed nowhere: an archive clip
                    # playing its proxy is working, and a number that goes up
                    # every time an editor inserts b-roll is a number nobody
                    # can read (audit F4). The CLASSIFICATION is untouched --
                    # the file really is not on this disk.
                    continue
                if self._proxy_held(path, held_cache):
                    # CR-317 (2026-09-24): the same rule for project footage.
                    # The original is not here and is not meant to be (a
                    # remote rig syncs proxies down, never originals); its
                    # proxy is, and Resolve plays it. Nothing to report and,
                    # like the archive case, nothing to log every poll.
                    continue
                missing_now.add(key)
                if len(missing_items) < MAX_MISSING_REPORTED:
                    missing_items.append({
                        "name": str(item.get("clip_name") or os.path.basename(path) or path),
                        "path": path,
                    })
                if key not in self._missing_logged:
                    new_missing += 1
                    # CR-317 (2026-09-24): this line used to say "not under
                    # local_root/prefix", the opposite of the class -- MISSING
                    # means the prefix DOES resolve under local_root and the
                    # file is simply absent. It also never said whether the
                    # proxy was here, which is the question that decides
                    # whether the editor can cut. Reaching this line means it
                    # is not (the exemption above would have taken the clip).
                    log.debug("clip's original is not on this computer and "
                              "no usable proxy for it is either: %s", path)
                # RES-10: FIXABLE, not merely missing -- we know exactly where
                # the file went, because this machine is the one that moved
                # it. Asked on every poll while the clip is missing; the
                # consumer offers the repoint once per move.
                if self._moved_lookup is not None and self._on_moved_clip is not None:
                    try:
                        local = canon.canonical_to_local(
                            path, self.local_root, self.canonical_prefix) or path
                        entry = self._moved_lookup(local)
                        if entry is not None:
                            self._on_moved_clip(dict(item), entry)
                    except Exception:
                        log.exception("moved-clip lookup failed")
            # OK -> nothing to do

        if missing_now:
            # The count is the signal worth having every poll ("is the sync
            # catching up?"); the paths are not. Silent when nothing is
            # missing, so a healthy rig writes nothing here at all.
            log.debug("%d clip(s) with neither the original nor a usable proxy "
                      "on this computer (%d new)", len(missing_now), new_missing)
        # Assignment, not update(): dropping the keys that did NOT come back
        # missing this pass is what re-arms a recovered (or switched-away)
        # path and what bounds the set. Only reached on a full poll -- an
        # early return above leaves the previous pass's set alone, so a
        # disconnected bridge does not replay every path on reconnect.
        self._missing_logged = missing_now
        # Same rebuild-per-pass rule, for the same reason: a clip whose media
        # has arrived must leave the list on the pass that sees it (RES-19).
        self._missing_items = missing_items

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

        self._note_scan(total_out_of_tree, total_bad_prefix, len(missing_now))
        return {
            "ok": True,
            "message": "",
            "out_of_tree": len(new_out_of_tree),
            "mapping_warnings": new_mapping_warnings,
            "non_canonical": len(new_non_canonical),
            "foreign_warnings": new_foreign_warnings,
            "missing": len(missing_now),
            "missing_new": new_missing,
            # ADDED keys, never replacing the ones above: the totals this
            # poll saw, whatever anybody has dismissed (UX-4).
            "out_of_tree_total": total_out_of_tree,
            "bad_prefix": total_bad_prefix,
        }

    def _archive_exempt(self, path: str, cache: dict[str, bool]) -> bool:
        """Is this MISSING clip an offline b-roll original that is fine?

        True for a clip in the b-roll archive that either IS a ledgered
        stand-in on this machine or has a proxy file on disk beside it. The
        second half is the "whose proxy is working" of plan section 6, asked
        of the FILESYSTEM rather than of Resolve: a timeline item carries no
        `proxy_state` (only a media-pool walk does), and one property read per
        missing clip per 3 s poll is not a trade worth making for a diagnostic
        count.

        Never raises: a question that cannot be answered counts the clip, the
        way it has always been counted.
        """
        try:
            key = _norm_key(path)
            if key in cache:
                return cache[key]
            now = time.monotonic()
            remembered = self._exempt_memo.get(key)
            if remembered is not None and now - remembered[0] < EXEMPT_TTL_SECONDS:
                cache[key] = remembered[1]
                return remembered[1]
            if self._archive_exempt_fn is not None:
                answer = bool(self._archive_exempt_fn(path))
            else:
                answer = (
                    broll_standins.is_under_archive(
                        path, self.local_root, self.canonical_prefix)
                    and (broll_standins.is_standin(path)
                         or bool(proxy_relink.find_proxy_on_disk(
                             path, self.local_root, self.canonical_prefix)))
                )
            cache[key] = answer
            self._exempt_memo[key] = (now, answer)
            if len(self._exempt_memo) > EXEMPT_MEMO_MAX:
                # A timeline can hold thousands; this is a cache, not a
                # ledger. Dropping it whole is cheaper than an LRU and the
                # next poll refills what it actually asks about.
                self._exempt_memo.clear()
            return answer
        except Exception:
            log.debug("watcher: could not judge %s against the archive", path,
                      exc_info=True)
            return False

    def _proxy_held(self, path: str, cache: dict[str, bool]) -> bool:
        """Is this MISSING project clip playing a proxy that IS on this disk?

        CR-317 (2026-09-24). True when the clip's proxy is at the tree's
        convention (`Proxy/<stem>.mov|.mp4` beside the original, by either
        spelling -- proxy_relink.find_proxy_on_disk, the same probe the
        archive rule and the relink pass use) AND Resolve has not already
        refused that exact file for this clip (proxy_relink.is_refused, the
        relink pass's in-memory ledger keyed on the proxy's mtime and size).
        That is the relink pass's own contract: a conventional proxy on disk
        is attached by it or by Resolve's adjacent auto-link, and one it
        could not attach is remembered -- the case ruskin's short A004
        proxies were in on 2026-09-17, which must stay in the count.

        The b-roll archive is NOT judged here: its `Proxy/<stem>.mp4` is the
        browser preview, and _archive_exempt already carries the archive's
        own rule (stand-ins included). A clip that rule counted stays counted.

        Deliberately not a Resolve read: see _archive_exempt, and CR-68 --
        nothing on this thread gets a scripting call it did not already
        make. A proxy attached somewhere OTHER than the convention is not
        seen, so such a clip is still counted: the safe direction for
        evidence.

        Never raises: a question that cannot be answered counts the clip.
        """
        try:
            key = _norm_key(path)
            if key in cache:
                return cache[key]
            now = time.monotonic()
            remembered = self._proxy_memo.get(key)
            if remembered is not None and now - remembered[0] < EXEMPT_TTL_SECONDS:
                cache[key] = remembered[1]
                return remembered[1]
            if self._proxy_held_fn is not None:
                answer = bool(self._proxy_held_fn(path))
            elif broll_standins.is_under_archive(
                    path, self.local_root, self.canonical_prefix):
                answer = False
            else:
                proxy = proxy_relink.find_proxy_on_disk(
                    path, self.local_root, self.canonical_prefix)
                answer = bool(proxy) and not proxy_relink.is_refused(path, proxy)
            cache[key] = answer
            self._proxy_memo[key] = (now, answer)
            if len(self._proxy_memo) > EXEMPT_MEMO_MAX:
                self._proxy_memo.clear()
            return answer
        except Exception:
            log.debug("watcher: could not tell whether %s has its proxy here",
                      path, exc_info=True)
            return False

    def bridge_is_connected(self) -> Optional[bool]:
        """Whether the last poll reached Resolve. None until the first poll
        has run, and that is load-bearing: "we have not looked" must not
        render as "Resolve is closed" (the same rule last_scan_at obeys)."""
        return self._bridge_connected

    # -- what the last pass saw, for a surface to render (RES-19) ----------
    def missing_clips(self) -> list[dict[str, str]]:
        """[{"name", "path"}] for the clips whose media is not on this
        computer, as of the last FULL pass. Since CR-317 (2026-09-24) that
        means neither the original nor a usable proxy: a clip playing its
        proxy is not listed, and this list rides the report as
        `resolve_health.missing_clips` with its shape unchanged. Capped at MAX_MISSING_REPORTED;
        `last_counts["missing"]` is the true count. A copy, because the
        caller is the tray/report thread and this list is replaced wholesale
        by the poll thread."""
        return [dict(entry) for entry in self._missing_items]

    def non_canonical_refused(self) -> list[dict[str, str]]:
        """[{"name", "path"}] for the in-tree clips whose relink to the
        canonical spelling Resolve refused. Copies, same reason as above."""
        return [dict(entry) for entry in self._non_canonical_refused.values()]

    def rearm_non_canonical(self, path: str, name: str = "") -> None:
        """This path's relink FAILED: offer it again (RES-19).

        `_offered_non_canonical` was add-only, so a relink refused for a
        transient reason -- Resolve busy, the file locked for a second -- was
        never retried for the life of the process, and the only way back was
        a restart nobody knew to do. Only a SUCCESS may latch a path now: a
        success rewrites the clip's File Path, so the key never comes back
        anyway. The unprompted burst is still rate-limited by
        resolve_journal.allow_automatic in app._handle_non_canonical, which
        is what stops this becoming a retry every 3 s.
        """
        text = str(path or "")
        if not text:
            return
        key = _norm_key(text)
        # comp-sync-13: RE-ARMED, not re-offered. Discarding the key outright
        # put the path back in the next 3 s poll, and the caller appends every
        # offer to a pending list a 15-minute limiter was refusing to drain:
        # ~300 appends of the same 158 clips per window, every failure
        # re-arming the cycle. The key stays latched and the cooldown is what
        # lifts it.
        self._arm_rearm(key)
        # comp-app-4 (2026-09-11): capped AT THE SOURCE. The report truncates
        # this list to 50 on its way out, but the dict itself was unbounded,
        # and the one machine that produces refusals in bulk is the machine
        # with a wrong canonical_prefix and a media pool full of them - so the
        # memory the cap was meant to save was already held here. Oldest out
        # first (insertion order): the newest refusals are the ones a surface
        # is about to name.
        self._non_canonical_refused.pop(key, None)
        self._non_canonical_refused[key] = {
            "name": str(name or os.path.basename(text) or text),
            "path": text,
        }
        while len(self._non_canonical_refused) > MAX_NON_CANONICAL_REFUSED:
            self._non_canonical_refused.pop(
                next(iter(self._non_canonical_refused)), None)

    def _arm_rearm(self, key: str) -> None:
        """This path may be offered again once the cooldown elapses.

        Written on both paths that latch a key (the offer and a failed
        relink), and bounded here rather than at either caller: the machine
        that produces these in bulk is the machine with a wrong
        canonical_prefix, whose every poll walks a media pool full of them.
        Oldest out first, and an evicted key is offered again by the next
        poll (see _rearm_is_due), which is the same answer the queue ceiling
        in app._handle_non_canonical gives.
        """
        self._rearm_due.pop(key, None)
        self._rearm_due[key] = self._rearm_clock() + REARM_COOLDOWN_SECONDS
        while len(self._rearm_due) > MAX_REARM_TRACKED:
            self._rearm_due.pop(next(iter(self._rearm_due)), None)

    def _rearm_is_due(self, key: str) -> bool:
        """Has this path's re-arm cooldown elapsed (comp-sync-13)?

        A key with NO record is due (comp-resolve-b-2, 2026-09-11b): the only
        way a latched path loses its record is the eviction above, and
        answering "not due" there would strand exactly the clips the book
        overflowed on, for the life of the process. The re-offer re-arms, so
        an evicted key costs one extra offer, not one per poll.
        """
        due = self._rearm_due.get(key)
        if due is None:
            return True
        try:
            return self._rearm_clock() >= float(due)
        except (TypeError, ValueError):
            return True

    def clear_non_canonical_refusal(self, path: str) -> None:
        """This path relinked. Drop any refusal recorded against it."""
        text = str(path or "")
        if text:
            self._non_canonical_refused.pop(_norm_key(text), None)

    def _note_scan(self, out_of_tree: int, bad_prefix: int, missing: int) -> None:
        """Publish the poll's totals for `app.resolve_health()` (UX-4).

        poll_once has computed exactly these numbers since the watcher
        existed and returned them into a caller that only ever looked at
        `ok` -- so the one editor mistake that guarantees unsynced footage
        was invisible to everyone but the editor making it. Written only at
        the END of a FULL pass: an early return (drive out, Resolve closed,
        ignored project) must leave the last real answer standing rather than
        report a reassuring zero.
        """
        self.last_counts = {
            "out_of_tree": int(out_of_tree),
            "bad_prefix": int(bad_prefix),
            "missing": int(missing),
        }
        self.last_scan_at = datetime.now(timezone.utc).isoformat()

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
            # Loop liveness for app.LaneWatchdog (SYS-2, resilience sweep
            # 2026-08-28), on the contract collector.py has carried since
            # ops-efficiency-6. poll_once() talks to Resolve through the
            # fusionscript C extension, which is exactly the kind of call a
            # thread can be alive and permanently stuck inside; that is a
            # different fault from a thread that died, and the watchdog can
            # only tell them apart if this is stamped.
            self._heartbeat = time.monotonic()
            try:
                self.poll_once()
            except Exception:
                log.exception("timeline watcher poll cycle failed")
            stop_event.wait(self.poll_interval)
        log.info("timeline watcher stopped")
