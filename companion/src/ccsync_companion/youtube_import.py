"""File the YouTube clips the dashboard downloaded into the open project.

The last hop of the YouTube page: an editor types a topic on the dashboard,
the server searches/filters/downloads into `<project>/Youtube/<term>/`, sync
delivers those files to this machine like any other media -- and then, until
this module existed, somebody had to go and find the folder and drag it into
Resolve. This watches for them and files them into `Master/Youtube/<term>`.

A clip pasted in as a URL has no search term to sort it under, so it lands in
`<project>/Youtube/` itself and is filed into `Master/Youtube` (0.7.1).

Modelled on proxy_gen.ProxyGenerator (proxy_gen.py:263) down to the shape:
one daemon thread, a 15 s tick with a slower scan cadence on top of it, a
priority-ordered gate publishing plain-string states, and a `status()` that is
a lock-guarded read of cached values and does NO I/O -- the tray/reporter
call it off their own threads, and a getter that touched the filesystem there
is how the right-click freeze of 2026-07-26 happened.

Three decisions carry most of the design:

  1. ONLY THE PROJECT THAT IS OPEN. Importing needs the project open anyway
     (the media pool belongs to it), and the rescan is idempotent, so opening
     a project is what picks up everything that arrived while it was closed.
     That is why there is no queue, no per-project state and no database.
  2. NO DATABASE, DELIBERATELY. `to_import = settled files on disk MINUS the
     paths already in the media pool`, recomputed every cycle. A restart, a
     re-sync, a renamed bin and a project copied to another machine all
     self-heal, because nothing was remembered that could be wrong. The
     documented consequence: a clip DELETED from the pool while its file
     stays on disk comes back after a companion restart. The escape hatches
     are deleting the file or `youtube_import_enabled = false`.
  3. NEVER STOP THE COMPANION, and never under the editor's hands. Every
     tick is caught, every collaborator is a constructor seam, the import is
     batched so the Resolve lock is never held long, and a state ("Resolve is
     closed", "this project isn't mapped") is published rather than retried
     silently or counted against a file.

Added 2026-08-11 with the dashboard's YouTube downloader page.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from . import canon
from . import config as config_mod
from . import fixer, resolve_bridge

# "ccsync.youtube_import", NOT __name__ -- setup_logging() only attaches
# handlers to the "ccsync" logger, and in the windowed build sys.stderr is
# None, so a record emitted under "ccsync_companion.youtube_import" goes
# nowhere at all.
log = logging.getLogger("ccsync.youtube_import")

# Same tick as the proxy generator, and for the same reason: short enough
# that "the editor opened a project" and "the drive came back" are noticed
# promptly, long enough that an idle machine does arithmetic four times a
# minute and nothing else.
TICK_SECONDS = 15.0

# The folder the dashboard downloads into, under the project root, and the
# bin the clips are filed into under Master. The same word on purpose: an
# editor looking at `P:\Projects\...\Youtube\algal reef` and at
# `Master/Youtube/algal reef` must not have to learn a mapping.
YOUTUBE_DIR_NAME = "Youtube"

# The _collect key for clips sitting loose in `<project>/Youtube/` ITSELF.
# The downloader's paste-a-URL box writes one-off clips there because a URL
# carries no search term to sort them under, and until 0.7.1 the scan skipped
# every non-directory in that folder, so those clips were invisible forever.
#
# The empty string cannot collide with a real term folder: os.listdir never
# yields "", and no filesystem this ships on can name a directory that. It is
# also never handed to Resolve as a bin segment -- ("Youtube", "") would come
# back as Master/Youtube/Untitled (resolve_bridge.FALLBACK_BIN_NAME), a bin
# nobody asked for -- see _import_batch.
ROOT_TERM = ""

# What counts as a downloaded clip. A whitelist rather than a blacklist
# because the download writes SIDECARS next to every video -- `.credits.json`
# (which the Resolve credits script reads) and `manifest.json` -- and
# importing those as media is nonsense Resolve would either refuse or, worse,
# accept as a still.
VIDEO_EXTS = frozenset({".mp4", ".mov", ".mkv", ".webm", ".m4v"})

# Half-delivered files, by name. The extension whitelist already excludes
# most of them (`clip.mp4.partial` has extension `.partial`), but naming them
# is what makes the rule readable: rclone writes `<name>.<hash>.partial`,
# Syncthing writes `.syncthing.<name>.tmp`, and both are files that will
# become real media in a moment and must not be imported halfway there.
SKIP_SUFFIXES = (".partial", ".tmp", ".lock")

# Gate answers, published verbatim as status()["state"]. Plain strings rather
# than an enum because they cross into the report payload, and a dashboard
# reading them must not need to import this module.
STATE_DISABLED = "disabled"
STATE_DRIVE_ABSENT = "drive-absent"
STATE_PAUSED = "paused"
STATE_RESOLVE_CLOSED = "resolve-closed"
STATE_NO_PROJECT_MATCH = "no-project-match"
STATE_NOTHING_TO_DO = "nothing-to-do"
STATE_WAITING_SETTLE = "waiting-settle"
STATE_IMPORTING = "importing"
# The gate's "nothing is stopping me" answer, and the state between a clean
# scan and the next one.
STATE_IDLE = "idle"


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class YoutubeImporter:
    """The worker. start()/stop()/join() plus a zero-I/O status() reader."""

    def __init__(
        self,
        cfg: dict[str, Any],
        *,
        root_present_fn: Optional[Callable[[], bool]] = None,
        paused_fn: Optional[Callable[[], bool]] = None,
        get_resolve_project: Optional[Callable[[], Optional[str]]] = None,
        get_project_roots: Optional[Callable[[], tuple]] = None,
        import_fn: Optional[Callable[..., dict]] = None,
        session_state_fn: Optional[Callable[[], dict]] = None,
        listdir_fn: Optional[Callable[[str], list]] = None,
        stat_fn: Optional[Callable[[str], Any]] = None,
        isdir_fn: Optional[Callable[[str], bool]] = None,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        self.cfg = cfg
        self.local_root = str(cfg.get("local_root", "") or "")
        # For the pool-dedupe alias fold ONLY (never for a filesystem probe):
        # clips an editor hand-imported through the P: drive sit in the pool
        # under the canonical spelling, and without translating those back to
        # this machine's local_root spelling the first scan of a pre-existing
        # Youtube folder would re-import every one of them as a duplicate.
        self.canonical_prefix = str(cfg.get("canonical_prefix", "") or "")

        # -- injected seams. Everything that touches the world is here, which
        # is what lets the whole state machine be tested with no Resolve, no
        # threads and (for the gate) no tree.
        self._root_present_fn = root_present_fn
        self._paused_fn = paused_fn
        self._get_resolve_project = get_resolve_project
        self._get_project_roots = get_project_roots
        self._import_fn = import_fn or resolve_bridge.import_files_to_bin_path
        self._session_state_fn = session_state_fn or resolve_bridge.session_state
        self._listdir = listdir_fn or os.listdir
        self._stat = stat_fn or os.stat
        self._isdir = isdir_fn or os.path.isdir
        # monotonic for the scan cadence (a clock the user drags backwards
        # must not stall the importer for hours), wall clock only for the
        # mtime settle comparison, which is against a real st_mtime.
        self._clock = clock
        self._wall_clock = wall_clock

        # -- config. coerce_numeric everywhere, never int()/float(): this
        # object is constructed inside CompanionApp.__init__, where a
        # hand-edited `youtube_import_scan_interval = "1m"` would take the
        # windowed exe down with no tray and no log line (AUDIT_2 CORE-M4).
        self.enabled = bool(cfg.get("youtube_import_enabled", True))
        self.scan_interval = config_mod.coerce_numeric(cfg, "youtube_import_scan_interval", 60)
        self.min_age_seconds = config_mod.coerce_numeric(
            cfg, "youtube_import_min_age_seconds", 120
        )
        self.batch_limit = int(
            config_mod.coerce_numeric(cfg, "youtube_import_batch_limit", 20)
        )
        self.max_failures = int(
            config_mod.coerce_numeric(cfg, "youtube_import_max_failures", 3)
        )

        # -- state read by status(), ALL of it guarded by _lock.
        self._lock = threading.Lock()
        # A disabled importer never starts its thread, so no tick will ever
        # publish a state -- seed the truthful one here or the tray/report
        # would say "idle" about a feature that is off.
        self._state = STATE_IDLE if self.enabled else STATE_DISABLED
        self._pending = 0
        self._imported_session = 0
        self._failed_session = 0
        self._last_import_at: Optional[str] = None
        self._last_bin = ""
        self._last_error = ""

        # -- worker-thread-only state.
        # {path: (size, mtime)} from the PREVIOUS scan. A file is settled
        # only when this scan agrees with that one -- an mtime old enough on
        # its own is not proof, because a slow copy of a file whose mtime is
        # stamped from the source looks settled the whole way through.
        self._seen: dict[str, tuple] = {}
        # Paths this session has already handed to Resolve (imported, or
        # found already in the pool). Not a dedupe mechanism -- the pool walk
        # is that -- just a way to not ask again about the same 400 files
        # every minute for the rest of the day.
        self._done: set[str] = set()
        # {path: attempts} -- in-process ONLY, exactly like proxy_gen's
        # _failures (proxy_gen.py:346-349). A refusal persisted to disk turns
        # one evening of a wedged Resolve into a file that never imports
        # again, and nothing here is worth that.
        self._failures: dict[str, int] = {}
        self._last_scan_at: Optional[float] = None
        # The project name the last tick saw. A CHANGE is a scan trigger: the
        # editor who just opened a project is the one waiting for its clips.
        self._last_project: Optional[str] = None
        # (project name, local dir or None, resolved at) -- the mapping chain
        # walks the tree in its fallback branch, so it is memoised for a scan
        # interval rather than re-run every 15 s tick.
        self._map_cache: tuple[str, Optional[str], float] = ("", None, 0.0)
        # Set when a cycle imported its batch cap and left files behind, so
        # the next TICK picks the remainder up rather than the next scan.
        self._more_to_do = False
        # What the last completed scan concluded, republished between scans so
        # the tray does not flip to "idle" for 45 s while an import is queued.
        self._scan_state = STATE_IDLE

        self._stop_event = threading.Event()
        self._wake = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # -- collaborators, each fault-isolated --------------------------------
    def _root_present(self) -> bool:
        try:
            if self._root_present_fn is not None:
                return bool(self._root_present_fn())
            return os.path.isdir(self.local_root)
        except Exception:
            # "Can't tell" is present, matching proxy_gen._root_present: an
            # unanswerable probe must not switch a feature off.
            log.debug("youtube import: could not check local_root", exc_info=True)
            return True

    def _is_paused(self) -> bool:
        try:
            return bool(self._paused_fn()) if self._paused_fn is not None else False
        except Exception:
            log.debug("youtube import: paused_fn failed", exc_info=True)
            return False

    def _current_project(self) -> Optional[str]:
        """The open Resolve project's name, or None for "not right now".

        None covers closed, unreachable AND ignored (the watcher blanks it for
        `ignored_resolve_projects`) -- all three mean the same thing here:
        there is no project to import into.
        """
        if self._get_resolve_project is None:
            return None
        try:
            name = self._get_resolve_project()
        except Exception:
            log.debug("youtube import: get_resolve_project() failed", exc_info=True)
            return None
        name = str(name or "").strip()
        return name or None

    def _bridge_is_down(self) -> bool:
        """Has the Resolve bridge told us it has NO connection?

        `connected` is None until something has actually asked Resolve, and
        "not checked yet" must not read as "closed" -- that would make the
        first tick after start() always publish resolve-closed. Only an
        explicit False stands the importer down; the watcher's own poll is
        what rediscovers Resolve.
        """
        try:
            state = self._session_state_fn() or {}
        except Exception:
            log.debug("youtube import: session_state() failed", exc_info=True)
            return False
        return state.get("connected") is False

    # -- which folder on disk is this project? ------------------------------
    def _project_roots(self) -> dict[str, str]:
        if self._get_project_roots is None:
            return {}
        try:
            result = self._get_project_roots()
        except Exception:
            log.debug("youtube import: project_roots_result() failed", exc_info=True)
            return {}
        # (mapping, source) -- the source matters to callers that WRITE files
        # (AUDIT_2 CORE-H9); this one only reads a directory, and its fallback
        # is separately gated on that directory existing.
        mapping = result[0] if isinstance(result, tuple) else result
        return mapping if isinstance(mapping, dict) else {}

    def _local_dir(self, prefix: str) -> str:
        """`Projects/2026/FF5/Nuclear` -> `<local_root>/Projects/2026/...`.

        os.path.join on split components, never a `P:\\...` string and never
        ntpath: the tree is at local_root on this machine, which on a Mac is
        `/Volumes/<SSD>/Creators_Club` and has no drive namespace at all.
        """
        parts = [part for part in str(prefix or "").replace("\\", "/").split("/") if part]
        return os.path.join(self.local_root, *parts) if parts else self.local_root

    def _resolve_project_dir(self, project_name: str) -> Optional[str]:
        """The project's directory on THIS machine, or None if we can't say.

        Order, and why: the dashboard's project_roots mapping is authoritative
        (an admin set it, and it is the same mapping the popup fixer files
        media with), so it wins outright. Only when it has nothing for this
        name do we fall back to fixer.match_project_dir's token-overlap guess
        -- and that guess is then gated on `<guess>/Youtube` actually
        existing, which is a fact rather than a hunch. A wrong guess here
        would file one project's YouTube clips into another project's bins,
        so "no idea" (None -> no-project-match) is a perfectly good answer.

        Memoised for a scan interval: the fallback walks the Projects tree.
        """
        cached_name, cached_dir, cached_at = self._map_cache
        interval = self.scan_interval if self.scan_interval > 0 else 60
        if cached_name == project_name and (self._clock() - cached_at) < interval:
            return cached_dir

        resolved: Optional[str] = None
        prefix = self._project_roots().get(project_name.strip().lower())
        if prefix:
            resolved = self._local_dir(prefix)
        else:
            try:
                rels = fixer.list_project_dirs(self.local_root)
                matched = fixer.match_project_dir(project_name, rels)
            except Exception:
                log.debug("youtube import: the project-dir guess failed", exc_info=True)
                matched = None
            if matched:
                guess = self._local_dir(f"Projects/{matched}")
                if self._safe_isdir(os.path.join(guess, YOUTUBE_DIR_NAME)):
                    resolved = guess
                else:
                    log.debug(
                        "youtube import: %r looks like %s, but it has no %s folder "
                        "-- not guessing", project_name, matched, YOUTUBE_DIR_NAME,
                    )
        self._map_cache = (project_name, resolved, self._clock())
        return resolved

    # -- the gate ----------------------------------------------------------
    def _gate(self, project_name: Optional[str]) -> str:
        """Why the importer is or isn't filing clips right now, in priority
        order. The FIRST true answer wins, and the order is the order an
        editor would ask the questions in: is it on, is the disk here, did I
        pause it, is Resolve there, and does this project mean anything to me.

        STATE_IDLE means nothing is in the way -- the scan decides the rest.
        """
        if not self.enabled:
            return STATE_DISABLED
        if not self._root_present():
            return STATE_DRIVE_ABSENT
        if self._is_paused():
            return STATE_PAUSED
        if project_name is None or self._bridge_is_down():
            return STATE_RESOLVE_CLOSED
        if self._resolve_project_dir(project_name) is None:
            return STATE_NO_PROJECT_MATCH
        return STATE_IDLE

    def _publish_state(self, state: str) -> None:
        with self._lock:
            self._state = state

    # -- public, zero-I/O reader -------------------------------------------
    def status(self) -> dict[str, Any]:
        """What the tray and the reporter render. Cached, lock-guarded, and
        it touches NO filesystem and no Resolve.

        The rule this obeys is proxy_gen.gap()'s (proxy_gen.py:510-516): these
        getters are called from the tray's refresh thread, which on the win32
        backend can stall the message loop, so nothing in here may block,
        probe or walk anything.
        """
        with self._lock:
            return {
                "state": self._state,
                "pending": self._pending,
                "imported_session": self._imported_session,
                "failed_session": self._failed_session,
                "last_import_at": self._last_import_at,
                "last_bin": self._last_bin,
                "last_error": self._last_error,
            }

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        if self._thread is not None:
            return
        if not self.enabled:
            log.info("youtube auto-import is disabled by config")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop, name="ccsync-youtube-import", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """Never blocks -- join() is the caller's separate decision."""
        self._stop_event.set()
        self._wake.set()

    def join(self, timeout: float = 5.0) -> None:
        thread = self._thread
        if thread is None or not thread.is_alive():
            return
        try:
            thread.join(timeout=timeout)
            if thread.is_alive():
                log.warning("youtube import: the worker did not stop within %.0fs", timeout)
        except Exception:
            log.exception("youtube import: failed to join the worker thread")

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.tick()
            except Exception:
                # One bad tick must not end the thread: the next one is a
                # complete recomputation from the disk and the pool, so
                # whatever went wrong here costs one cycle and nothing else.
                log.exception("youtube import: tick failed")
            self._wake.wait(TICK_SECONDS)
            self._wake.clear()

    # -- the tick ----------------------------------------------------------
    def tick(self) -> str:
        """One pass: gate, maybe scan, maybe import. Returns the published
        state (what the tests and the reporter read)."""
        project_name = self._current_project()
        if project_name != self._last_project:
            # A project change is a scan trigger AND a mapping-cache reset:
            # the editor who just opened a project is the one waiting for its
            # clips, and a 60 s wait to find that out is 60 s of them
            # wondering whether the feature works.
            self._last_project = project_name
            self._last_scan_at = None
            self._map_cache = ("", None, 0.0)
            self._more_to_do = False

        state = self._gate(project_name)
        if state != STATE_IDLE:
            self._publish_state(state)
            return state

        if not self._scan_due():
            self._publish_state(self._scan_state)
            return self._scan_state

        # Both re-reads are cache hits (the gate above just resolved them);
        # they are here rather than passed down so this function reads as one
        # decision and not as a chain of promises about what the gate proved.
        project_dir = self._resolve_project_dir(project_name or "")
        if project_name is None or project_dir is None:  # pragma: no cover
            self._publish_state(STATE_NO_PROJECT_MATCH)
            return STATE_NO_PROJECT_MATCH
        state = self.scan_once(project_name, project_dir)
        self._scan_state = state
        self._publish_state(state)
        return state

    def _scan_due(self) -> bool:
        if self._more_to_do:
            # A cycle that hit the batch cap: the remainder goes on the NEXT
            # tick, not the next scan interval, so a big drop lands in a few
            # minutes rather than a few hours.
            return True
        if self._last_scan_at is None:
            return True  # first tick after start(), or a project change
        interval = self.scan_interval if self.scan_interval > 0 else 60
        return (self._clock() - self._last_scan_at) >= interval

    # -- detection ---------------------------------------------------------
    def _safe_isdir(self, path: str) -> bool:
        try:
            return bool(self._isdir(path))
        except Exception:
            return False

    def _safe_listdir(self, path: str) -> list[str]:
        try:
            return sorted(self._listdir(path))
        except OSError:
            # A term folder deleted between the two listdirs, or a share that
            # went away mid-scan. Neither is worth a log line at INFO: the
            # next cycle recomputes everything from scratch anyway.
            log.debug("youtube import: could not list %s", path, exc_info=True)
            return []
        except Exception:
            log.debug("youtube import: could not list %s", path, exc_info=True)
            return []

    @staticmethod
    def _is_clip_name(name: str) -> bool:
        """Is this a downloaded video, rather than one of its neighbours?

        Excluded, and each for a reason seen in a real term folder: dotfiles
        (Syncthing's `.syncthing.<name>.tmp`, macOS's `._name`), the
        half-delivered suffixes above, and anything outside the video
        whitelist -- which is what keeps `<name>.credits.json` (the sidecar
        the Resolve credits script reads) and `manifest.json` out of the pool.
        """
        if not name or name.startswith("."):
            return False
        lowered = name.lower()
        if lowered.endswith(SKIP_SUFFIXES):
            return False
        return os.path.splitext(lowered)[1] in VIDEO_EXTS

    def _is_capped(self, path: str) -> bool:
        return self._failures.get(path, 0) >= max(1, self.max_failures)

    def _collect(self, project_dir: str) -> tuple[dict[str, list[str]], int]:
        """({term: [settled paths]}, how many are still arriving).

        TWO places, and no deeper: the term folders the downloader writes
        (`Youtube/<term>/<video>.mp4`) and `Youtube/` ITSELF, which is where a
        clip pasted in by URL lands because there is no search term to sort it
        under (0.7.1). Still not a recursive walk -- these two levels are
        exactly the two the downloader writes, and a deeper one would drag in
        whatever else an editor has filed there.

        Loose clips come back under ROOT_TERM and are filed into the
        `Master/Youtube` bin itself; everything else about them -- the clip
        whitelist, the settle rules, the failure cap, the per-path
        bookkeeping -- is the term folders' behaviour unchanged.
        """
        root = os.path.join(project_dir, YOUTUBE_DIR_NAME)
        if not self._safe_isdir(root):
            return {}, 0

        now = self._wall_clock()
        seen: dict[str, tuple] = {}
        pending: dict[str, list[str]] = {}
        waiting = 0

        def take(directory: str, term: str, skip_dirs: bool = False) -> None:
            nonlocal waiting
            for name in self._safe_listdir(directory):
                if not self._is_clip_name(name):
                    continue
                path = os.path.join(directory, name)
                if skip_dirs and self._safe_isdir(path):
                    # Only in the root, and only because BOTH loops read it
                    # now: a term folder someone named "reef.mp4" passes the
                    # clip whitelist on its name alone, and handing a
                    # directory to ImportMedia is not a thing to find out
                    # about in Resolve.
                    continue
                try:
                    stat = self._stat(path)
                    fingerprint = (int(stat.st_size), float(stat.st_mtime))
                except OSError:
                    continue
                except Exception:
                    log.debug("youtube import: could not stat %s", path, exc_info=True)
                    continue
                previous = self._seen.get(path)
                # Seeded even for files we then skip, so the dict is a true
                # picture of the folder and vanished files fall out of it.
                seen[path] = fingerprint
                if path in self._done or self._is_capped(path):
                    continue
                if (now - fingerprint[1]) < self.min_age_seconds:
                    waiting += 1
                    continue
                if previous != fingerprint:
                    # First sighting, or it grew since the last one. Either
                    # way it is still arriving -- the mtime alone is not
                    # enough, because a copy that preserves the source's
                    # timestamp is born looking old.
                    waiting += 1
                    continue
                pending.setdefault(term, []).append(path)

        # The root's own loose clips first: a one-off URL download is the one
        # an editor is watching for, and it should not queue behind every
        # term folder's batch.
        take(root, ROOT_TERM, skip_dirs=True)
        for term in self._safe_listdir(root):
            if term.startswith("."):
                continue
            term_dir = os.path.join(root, term)
            if not self._safe_isdir(term_dir):
                continue
            take(term_dir, term)
        self._seen = seen
        return pending, waiting

    # -- importing ---------------------------------------------------------
    def scan_once(self, project_name: str, project_dir: str) -> str:
        """Look, then file whatever is ready. Returns the state to publish."""
        pending, waiting = self._collect(project_dir)
        self._last_scan_at = self._clock()
        total = sum(len(paths) for paths in pending.values())
        with self._lock:
            self._pending = total + waiting

        if not total:
            self._more_to_do = False
            return STATE_WAITING_SETTLE if waiting else STATE_NOTHING_TO_DO

        self._publish_state(STATE_IMPORTING)
        loose = len(pending.get(ROOT_TERM, []))
        log.info(
            "youtube import: %d clip(s) in %d term folder(s)%s ready for %r",
            total, len(pending) - (1 if ROOT_TERM in pending else 0),
            f" plus {loose} loose in {YOUTUBE_DIR_NAME}/" if loose else "",
            project_name,
        )
        deferred = 0
        for term, paths in pending.items():
            batch = paths[: max(1, self.batch_limit)]
            deferred += len(paths) - len(batch)
            if not self._import_batch(project_name, term, batch):
                # An environment refusal (Resolve went away, the editor
                # switched project): the remaining terms would only get the
                # same answer, and doing them anyway would file clips into
                # whatever is open now.
                self._more_to_do = True
                return STATE_IMPORTING
        self._more_to_do = deferred > 0
        if deferred:
            return STATE_IMPORTING
        return STATE_WAITING_SETTLE if waiting else STATE_NOTHING_TO_DO

    def _import_batch(self, project_name: str, term: str, paths: list[str]) -> bool:
        """Hand one term folder's batch to Resolve. False = stop this cycle.

        `term` is ROOT_TERM for the clips found loose in `Youtube/` itself,
        and those go into `Master/Youtube` -- passing ("Youtube", "") would
        have resolve_bridge._safe_bin_name turn the empty segment into
        "Untitled" and file a URL download into a bin nobody named.

        Never raises: import_files_to_bin_path is a never-raise function, and
        this adds the same guarantee around a seam a test (or a future
        caller) might supply.
        """
        segments = (YOUTUBE_DIR_NAME,) if term == ROOT_TERM else (YOUTUBE_DIR_NAME, term)
        bin_path = "/".join(segments)
        try:
            result = self._import_fn(
                list(paths), segments,
                expected_project_name=project_name,
                path_alias_fn=self._pool_path_alias,
            )
        except Exception:
            log.exception("youtube import: the import call raised for %s", bin_path)
            self._note_error("the import failed -- see the log")
            return False
        if not isinstance(result, dict):
            self._note_error("the import returned nothing usable")
            return False

        imported = [str(p) for p in (result.get("imported") or [])]
        skipped = [str(p) for p in (result.get("skipped_existing") or [])]
        failed = [str(p) for p in (result.get("failed") or [])]
        self._done.update(imported)
        self._done.update(skipped)
        for path in failed:
            self._failures[path] = self._failures.get(path, 0) + 1
            attempts, cap = self._failures[path], max(1, self.max_failures)
            if attempts >= cap:
                log.warning(
                    "youtube import: giving up on %s after %d attempt(s). It will be "
                    "tried again on the next companion restart", path, attempts,
                )

        with self._lock:
            self._imported_session += len(imported)
            self._failed_session += len(failed)
            if imported:
                self._last_import_at = _iso_now()
                self._last_bin = bin_path
            if result.get("ok"):
                self._last_error = ""
        if imported:
            log.info(
                "youtube import: filed %d clip(s) into %s/%s%s",
                len(imported), resolve_bridge.MASTER_BIN_NAME, bin_path,
                f" ({len(skipped)} already there)" if skipped else "",
            )
        if result.get("ok"):
            return True

        message = str(result.get("message") or "the import was refused")
        self._note_error(message)
        # A per-file refusal is progress of a kind -- the counters above have
        # it, and the next cycle retries what is left. Only a refusal that
        # touched NOTHING means "stop asking this cycle".
        return bool(imported or skipped or failed)

    def _pool_path_alias(self, pool_path: str) -> Optional[str]:
        """A media-pool path's spelling on THIS machine's tree, or None.

        Handed to import_files_to_bin_path so its dedupe set holds both
        spellings of every pool clip. Clips imported by hand through the P:
        drive are stored canonically (`P:\\Projects\\...`); the paths this
        module hands Resolve are local_root ones (ImportMedia cannot resolve
        "P:\\" on a Mac -- broll_server.default_broll_mount's reason). Without
        this fold `_norm_path` never matches the two, and the first scan of a
        Youtube folder that predates this feature would duplicate every clip
        the editor had already filed. canonical_to_local answers None for a
        path that is not on the canonical prefix, which is exactly "no second
        spelling"; a TRANSLATION is all this is, never a filesystem probe.
        """
        try:
            return canon.canonical_to_local(
                pool_path, self.local_root, self.canonical_prefix
            )
        except Exception:
            log.debug("youtube import: alias translation failed for %r",
                      pool_path, exc_info=True)
            return None

    def _note_error(self, message: str) -> None:
        with self._lock:
            self._last_error = str(message or "")
        log.info("youtube import: %s", message)
