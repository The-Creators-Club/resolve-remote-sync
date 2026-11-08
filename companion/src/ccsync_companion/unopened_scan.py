"""Clips only on this computer, in Resolve projects nobody here has open.

CR-383 (2026-11-08). The Resolve project "Animals - Pangolins and Bears" in
the shared postgres library FF5 had 45 music clips in its Master/Music bin
linked to `C:\\Users\\user\\Desktop\\Music Docs\\...` on ruskin's PC: outside
the sync tree, so never uploaded and offline on every other machine. The
out-of-tree popup only ever looks at the project OPEN in Resolve on the
editor's own computer, and nobody had opened that one there since at least
2026-10-30, so nothing warned anybody. The same 45 files had been fixed in
three other projects on 2026-10-31 -- the day he opened those. The owner's
ask: "check projects nobody is looking at", and keep bothering the editor
until it is fixed.

So, every `unopened_scan_minutes` (default 30, 0 = off), on its own thread:

  * Find this machine's project libraries: Resolve's GetDatabaseList() only
    when the bridge is ALREADY connected (CR-68: nothing here may be the
    reason a scriptapp() happens), every postgres library Resolve's log says
    it attached, and every disk library's Project.db files on disk.
  * Read every project's media pool out of the library DIRECTLY
    (library.read_all_pools: one connection, all SELECTs). No Resolve call.
  * A project is FLAGGED when at least one of its clips is OUT_OF_TREE by
    the watcher's own classification (paths.classify_path, which already
    means "exists on this disk") and at least one other clip lives in the
    tree under a project root. The first half keeps editor A from being
    told about editor B's Desktop (only the machine holding the file can fix
    it); the second is CR-232's rule from the dashboard side -- a personal
    project entirely off the tree is the editor's own business and stays
    silent.
  * Skipped: the project open on this machine (the watcher and its popup own
    it), the scratch names in `ignored_resolve_projects`, and any name a
    library holds twice (library.read_all_pools leaves those out, and nothing
    in a row says which one is which).
  * While anything is flagged, a tray balloon on the first finding and every
    NAG_SECONDS after it until a sweep finds it clean. Opening the project is
    the fix: the media-tree pass classifies its WHOLE pool within one
    media_tree_refresh_interval and the existing FIX ALL popup offers the
    clips (app._classify_pool_once).
  * `report()` feeds `sync_guard.resolve_health.unopened_out_of_tree`:
    names and counts only, never a path. None until a sweep has completed,
    because "we have not looked" must never read as "nothing is wrong".

Same discipline as drive_reminder.py: injectable clock, notifier and
readers; no public method raises; an unreachable library is logged once,
not every pass, and skipped.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Mapping, Optional

from . import canon, library, ui_copy
from . import config as config_mod
from . import site as site_mod
from .paths import FOREIGN, OUT_OF_TREE, classify_path

log = logging.getLogger("ccsync.unopened_scan")

# How often the balloon repeats while a flagged project stays flagged. The
# owner's word was "keep bothering"; half an hour is drive_reminder's cadence
# (CR-92) and the one editors already know.
NAG_SECONDS = 30 * 60.0
# The thread's own heartbeat. A sweep is due every unopened_scan_minutes and a
# nag every NAG_SECONDS; waking once a minute is fine-grained enough for both
# and costs nothing.
TICK_SECONDS = 60.0
# Not on the start path: Resolve's log may not have its library lines yet,
# and startup already has every lane, the reporter and the watcher to bring up.
INITIAL_DELAY_SECONDS = 120.0
# The wire's cap (dashboard ResolveHealthIn.unopened_out_of_tree). A machine
# with more than twenty such projects has a bigger conversation coming.
MAX_REPORTED = 20
# Balloon text is 250 WCHARs on Windows (drive_reminder's note); a project
# name is free text and can be long.
_NAME_CAP = 60


@dataclass(frozen=True)
class Finding:
    """One project with clips only on this computer. `where` is the folder
    they sit in, shortened for the balloon -- shown here, NEVER reported."""
    library: str
    project: str
    count: int
    where: str = ""


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def interval_seconds(cfg: Mapping[str, Any]) -> float:
    """`unopened_scan_minutes` in seconds; 0 = off. A garbage or negative
    value is the default (config.validate_config warns about it), never an
    exception and never "off" by accident."""
    default = float(config_mod.DEFAULTS.get("unopened_scan_minutes", 30.0))
    try:
        minutes = float(cfg.get("unopened_scan_minutes", default))
        if minutes < 0:
            raise ValueError
    except (TypeError, ValueError, AttributeError):
        minutes = default
    return minutes * 60.0


# ---------------------------------------------------------------- libraries

def discover_libraries(api_infos: Optional[Iterable[library.LibraryInfo]],
                       overrides: Optional[Mapping[str, Any]] = None
                       ) -> list[library.LibraryInfo]:
    """Every library this machine can be told about. Never raises.

    PostgreSQL: the API's list first (already fetched by the caller, under
    the bridge lock, and only on a bridge that was connected), then
    Resolve's log; one entry per library NAME, first source wins. The
    `library_db_*` overrides are the editor saying the other two are wrong
    (library.locate's rule): a host + name adds that library, and the
    credentials apply to every postgres library, since the fleet's are all
    Resolve's default anyway. Disk: every Project.db on disk.
    """
    overrides = overrides or {}
    out: list[library.LibraryInfo] = []
    try:
        seen: set[str] = set()
        candidates = list(api_infos or []) + library.postgres_libraries_from_log()
        host = str(overrides.get("library_db_host") or "").strip()
        name = str(overrides.get("library_db_name") or "").strip()
        if host and name:
            candidates.insert(0, library.LibraryInfo(kind="PostgreSQL", name=name, host=host))
        user = str(overrides.get("library_db_user") or "").strip()
        password = str(overrides.get("library_db_password") or "")
        try:
            port = int(overrides.get("library_db_port") or 0)
        except (TypeError, ValueError):
            port = 0
        for info in candidates:
            key = info.name.casefold()
            if not info.name or key in seen:
                continue
            seen.add(key)
            out.append(library.LibraryInfo(
                kind="PostgreSQL", name=info.name, host=info.host or "127.0.0.1",
                port=port or info.port, user=user or info.user,
                password=password or info.password))
    except Exception:
        log.debug("unopened scan: postgres library discovery failed", exc_info=True)
    try:
        for library_name, db_path in library.disk_project_dbs():
            out.append(library.LibraryInfo(kind="Disk", name=library_name,
                                           sqlite_path=db_path))
    except Exception:
        log.debug("unopened scan: disk library discovery failed", exc_info=True)
    return out


def _library_key(info: library.LibraryInfo) -> str:
    return info.sqlite_path if info.kind == "Disk" else f"{info.name}@{info.host}"


# ----------------------------------------------------------- classification

def _under_project_root(path: str, local_root: str, prefix: str,
                        known_rels: Optional[list[str]]) -> bool:
    """Does this clip live in the tree under a project root?

    The question rclone_lane._project_rel_for_path already answers for the
    express lane, asked of the clip's LOCAL spelling (a canonical `P:\\...`
    is translated first, as classify_path does). Known project rels win; the
    year/series/project heuristic is the fallback, because the project being
    asked about is often not ticked on this machine at all -- which is
    exactly why nobody here had it open.

    A cheap "is it under Projects at all" test comes first: that helper logs
    a DEBUG line for every path it turns down, and a pool of b-roll archive
    clips would otherwise write one per clip per sweep.
    """
    from .sync.rclone_lane import _project_rel_for_path

    local = path
    if prefix and canon.is_canonical(path, prefix):
        local = canon.canonical_to_local(path, local_root, prefix) or ""
    if not local or not local_root:
        return False
    try:
        rel = os.path.relpath(local, local_root)
    except ValueError:
        return False                      # another drive entirely
    parts = [p for p in re.split(r"[\\/]", rel) if p]
    if not parts or parts[0] == ".." or parts[0].lower() != "projects":
        return False
    if known_rels and _project_rel_for_path(local_root, local, known_rels):
        return True
    return _project_rel_for_path(local_root, local, None) is not None


def _where(paths: list[str]) -> str:
    """The folder the clips sit in, as its last two names: "Desktop\\Music
    Docs". Shown to the editor on their own screen only."""
    if not paths:
        return ""
    plat = canon.plat_for(paths[0])
    dirs = [plat.dirname(p) for p in paths]
    try:
        common = plat.commonpath(dirs)
    except ValueError:
        common = ""
    parts = [p for p in re.split(r"[\\/]", common) if p and not p.endswith(":")]
    if len(parts) < 2:
        # Different drives, or everything under one drive root: the folder
        # holding most of them says more than "C:".
        common = Counter(dirs).most_common(1)[0][0]
        parts = [p for p in re.split(r"[\\/]", common) if p and not p.endswith(":")]
    return plat.sep.join(parts[-2:])


def classify_project(items: Iterable[Mapping[str, Any]], local_root: str, prefix: str,
                     known_rels: Optional[list[str]] = None,
                     exists_fn: Optional[Callable[[str], bool]] = None
                     ) -> Optional[tuple[int, list[str]]]:
    """(count, paths) of a TREE project's clips that are only on this
    computer, or None when there is nothing to say.

    `count` is unique files, which is what the FIX ALL popup lists
    (popup.dedupe_out_of_tree_items): one file cut in three times is one
    copy to make.
    """
    from .watcher import _norm_key

    outside: dict[str, str] = {}
    tree = False
    for item in items:
        path = str(item.get("file_path") or "")
        if not path:
            continue
        cls = classify_path(path, local_root, prefix, exists_fn=exists_fn)
        if cls == OUT_OF_TREE:
            outside.setdefault(_norm_key(path), path)
        elif not tree and cls != FOREIGN and _under_project_root(
                path, local_root, prefix, known_rels):
            tree = True
    if not outside or not tree:
        return None
    paths = sorted(outside.values())
    return len(paths), paths


def nag_message(findings: list[Finding]) -> str:
    """The balloon. No em dashes (owner's rule, 2026-08-18)."""
    top = findings[0]
    name = top.project if len(top.project) <= _NAME_CAP else top.project[:_NAME_CAP - 3] + "..."
    where = f" ({top.where})" if top.where else ""
    clips = ui_copy.count(top.count, "clip")
    verb = "is" if top.count == 1 else "are"
    if len(findings) == 1:
        return (f"{clips} in '{name}' {verb} only on this computer{where}. "
                "Open that project in Resolve and press FIX ALL.")
    others = ui_copy.count(len(findings) - 1, "other project")
    return (f"{clips} in '{name}'{where} and more in {others} are only on this "
            "computer. Open each project in Resolve and press FIX ALL.")


# ------------------------------------------------------------------- sweep

class UnopenedScan:
    """The sweep, its findings and the reminder. Thread-safe readers."""

    def __init__(
        self,
        *,
        interval_fn: Callable[[], float],
        local_root_fn: Callable[[], str],
        canonical_prefix_fn: Callable[[], str],
        open_project_fn: Callable[[], Optional[str]],
        ignored_projects_fn: Callable[[], Any],
        libraries_fn: Callable[[], list[library.LibraryInfo]],
        notify_fn: Callable[[str, str], None],
        known_rels_fn: Callable[[], Optional[list[str]]] = lambda: None,
        ready_fn: Callable[[], bool] = lambda: True,
        nag_allowed_fn: Callable[[], bool] = lambda: True,
        reader: Optional[Callable[[library.LibraryInfo], library.LibraryPools]] = None,
        exists_fn: Optional[Callable[[str], bool]] = None,
        nag_seconds: float = NAG_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        wall_now: Callable[[], str] = _now_iso,
    ) -> None:
        self._interval_fn = interval_fn
        self._local_root_fn = local_root_fn
        self._prefix_fn = canonical_prefix_fn
        self._open_project_fn = open_project_fn
        self._ignored_fn = ignored_projects_fn
        self._libraries_fn = libraries_fn
        self._notify_fn = notify_fn
        self._known_rels_fn = known_rels_fn
        self._ready_fn = ready_fn
        self._nag_allowed_fn = nag_allowed_fn
        self._reader = reader
        self._exists_fn = exists_fn
        self.nag_seconds = float(nag_seconds)
        self._clock = clock
        self._wall_now = wall_now
        self._lock = threading.Lock()
        # None = no sweep has completed: report() says None, not [].
        self._findings: Optional[list[Finding]] = None
        self._scan_at: Optional[str] = None
        self._next_sweep_at: Optional[float] = None
        self._last_nag_at: Optional[float] = None
        # Log-once latches: an unreachable library is a state, not an event,
        # and a sweep every 30 minutes would otherwise log it 48 times a day.
        self._unreachable: set[str] = set()
        self._duplicates_logged: set[tuple[str, str]] = set()
        self._no_libraries_logged = False
        self._tick_error_logged = ""

    # -- readers -----------------------------------------------------------

    def report(self) -> tuple[Optional[list[dict[str, Any]]], Optional[str]]:
        """(entries, scan time) for resolve_health. (None, None) until a
        sweep has completed. Names and counts only, never a path."""
        with self._lock:
            if self._findings is None:
                return None, None
            entries = [{"project": f.project, "count": int(f.count)}
                       for f in self._findings[:MAX_REPORTED]]
            return entries, self._scan_at

    def findings(self) -> Optional[list[Finding]]:
        with self._lock:
            return None if self._findings is None else list(self._findings)

    def visible(self) -> list[Finding]:
        """The findings minus the project open right now (the watcher's
        popup owns that one). What the tray and the balloon talk about."""
        found = self.findings() or []
        try:
            open_project = self._open_project_fn() or ""
        except Exception:
            open_project = ""
        return [f for f in found if not open_project or f.project != open_project]

    # -- the sweep ---------------------------------------------------------

    def sweep_once(self) -> Optional[list[Finding]]:
        """Read every library once and replace the findings. None (and the
        previous findings kept) when nothing could be read. Never raises."""
        try:
            return self._sweep()
        except Exception:
            log.exception("unopened scan: the sweep failed")
            return None

    def _sweep(self) -> Optional[list[Finding]]:
        if not self._ready_fn():
            log.debug("unopened scan: skipped, the sync folder is not usable right now")
            return None
        local_root = str(self._local_root_fn() or "")
        prefix = str(self._prefix_fn() or "")
        if not local_root:
            return None
        infos = list(self._libraries_fn() or [])
        if not infos:
            if not self._no_libraries_logged:
                self._no_libraries_logged = True
                log.info("unopened scan: no Resolve project library found on this "
                         "computer (Resolve's log names none and no disk library "
                         "exists); nothing to check")
            return None
        self._no_libraries_logged = False
        try:
            open_project = self._open_project_fn() or ""
        except Exception:
            open_project = ""
        ignored = config_mod.normalize_ignored_projects(self._ignored_fn())
        try:
            known = self._known_rels_fn()
        except Exception:
            known = None

        findings: list[Finding] = []
        read_any = False
        projects_read = 0
        for info in infos:
            key = _library_key(info)
            try:
                # Looked up per call when not injected, so a patched
                # library.read_all_pools (the test suite's guard) is the one used.
                reader = self._reader or library.read_all_pools
                pools = reader(info)
            except library.LibraryUnavailable as exc:
                self._note_unreachable(key, info, str(exc))
                continue
            except Exception as exc:
                self._note_unreachable(key, info, f"{type(exc).__name__}: {exc}")
                continue
            if key in self._unreachable:
                self._unreachable.discard(key)
                log.info("unopened scan: %s answers again", info.describe())
            read_any = True
            for name in pools.duplicates:
                if (key, name) not in self._duplicates_logged:
                    self._duplicates_logged.add((key, name))
                    log.warning("unopened scan: %s holds more than one project named "
                                "%r; neither is checked (nothing in the library says "
                                "which is which)", info.describe(), name)
            for name, items in pools.pools.items():
                if open_project and name == open_project:
                    continue
                if config_mod.is_ignored_project(name, ignored):
                    continue
                projects_read += 1
                verdict = classify_project(items, local_root, prefix, known,
                                           self._exists_fn)
                if verdict is None:
                    continue
                count, paths = verdict
                findings.append(Finding(library=info.name, project=name,
                                        count=count, where=_where(paths)))
        if not read_any:
            return None
        findings.sort(key=lambda f: (-f.count, f.project.casefold()))
        with self._lock:
            previous = self._findings
            self._findings = findings
            self._scan_at = self._wall_now()
        if findings:
            log.info("unopened scan: %d project(s) not open here have clips only on "
                     "this computer: %s", len(findings),
                     "; ".join(f"{f.project!r} ({f.count})" for f in findings[:MAX_REPORTED]))
        elif previous:
            log.info("unopened scan: clean again (%d project(s) checked)", projects_read)
        else:
            log.debug("unopened scan: %d project(s) checked, nothing outside the tree",
                      projects_read)
        return findings

    def _note_unreachable(self, key: str, info: library.LibraryInfo, why: str) -> None:
        if key in self._unreachable:
            log.debug("unopened scan: %s still unreachable: %s", info.describe(), why)
            return
        self._unreachable.add(key)
        log.warning("unopened scan: cannot read %s (%s); skipping it until it "
                    "answers", info.describe(), why)

    # -- the reminder ------------------------------------------------------

    def maybe_nag(self) -> bool:
        """Show the balloon if one is due. True when it was shown."""
        try:
            if not self._nag_allowed_fn():
                return False
            visible = self.visible()
            if not visible:
                # Re-armed: the next finding is a FIRST finding again.
                self._last_nag_at = None
                return False
            now = self._clock()
            if self._last_nag_at is not None and now - self._last_nag_at < self.nag_seconds:
                return False
            self._last_nag_at = now
            self._notify_fn(nag_message(visible),
                            site_mod.notify_title("footage only on this computer"))
            return True
        except Exception:
            log.debug("unopened scan: reminder failed", exc_info=True)
            return False

    # -- the loop ----------------------------------------------------------

    def tick(self) -> None:
        """One heartbeat: a sweep if one is due, then a reminder if one is.
        Never raises."""
        try:
            interval = float(self._interval_fn() or 0.0)
            if interval <= 0:
                # Switched off: forget what we knew, so the report goes back to
                # "not checked" rather than carrying a stale verdict for ever.
                with self._lock:
                    self._findings = None
                    self._scan_at = None
                self._next_sweep_at = None
                self._last_nag_at = None
                return
            now = self._clock()
            if self._next_sweep_at is None or now >= self._next_sweep_at:
                self._next_sweep_at = now + interval
                self.sweep_once()
            self.maybe_nag()
            self._tick_error_logged = ""
        except Exception as exc:
            text = f"{type(exc).__name__}: {exc}"
            if text != self._tick_error_logged:
                self._tick_error_logged = text
                log.exception("unopened scan: tick failed")

    def run(self, stop_event: threading.Event,
            initial_delay: float = INITIAL_DELAY_SECONDS,
            tick_seconds: float = TICK_SECONDS) -> None:
        """The thread body. Returns when `stop_event` is set."""
        if stop_event.wait(initial_delay):
            return
        while True:
            self.tick()
            if stop_event.wait(tick_seconds):
                return
