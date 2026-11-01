"""Originals on request: bring chosen camera originals DOWN to this computer.

docs/SELECTIVE_ORIGINALS.md sections 4.2-4.3 and 12 (2026-10-31). The owner's
case: a remote editor needed the 80 originals of one footage folder for a
grade, and the only way to get them was an `rclone copy` typed over SSH.

WHAT comes down is the dashboard's decision, never this module's: each
selection item may carry `originals`, the expanded list of posix rels inside
that project that this computer asked for (dashboard 0.7.77, section 12.3).
Absent means nothing. A shape this build does not understand also means
nothing (fail closed: a misread list is a download nobody asked for).

HOW is deliberately not lane B:

  * Lane B is `rclone sync`, the one verb that deletes locally. An original
    inside its filter would be trashed the moment the NAS lost it and counted
    by the breaker as a 40 GB mass delete. So originals stay OUTSIDE lane B's
    Proxy-only filter (unchanged), where `sync` never touches them, and come
    down here through `rclone copy --files-from-raw --ignore-existing`, which
    can neither delete nor overwrite.
  * `--files-from-raw` refuses every filter flag (measured against the bundled
    1.74.4, rclone_lane.build_express_command), so every rule a filter would
    have applied is applied in Python before a name enters the list
    (list_rule_reason).
  * The NAS is re-listed before each run and every wanted rel is matched by
    NFC key (CR-90): the list rclone reads carries the NAS's OWN spelling,
    because a path something opens must be the bytes on disk.
  * One slot, `--transfers 2`, its own thread (D5: originals coming down never
    slow footage going up). NOT inside the sequencer's joined per-project turn:
    a 40 GB file in that join holds every other project's proxies back, which
    is the CR-347 lesson (sequencer._run_lanes_a_and_b).
  * It has a LaneStatus, so the power guards keep the PC awake while it runs
    (D6), the drive reminder names it, the tray shows it and the report's
    lane block carries its counts. Un-picking never deletes (D7).

Nothing here calls Resolve. A file lands where its clip already points.
"""

from __future__ import annotations

import json
import logging
import os
import stat
import subprocess
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from . import lane_guard
from . import rclone_lane
from .base import (
    STATE_ERROR,
    STATE_IDLE,
    STATE_PAUSED,
    STATE_SYNCING,
    LaneAdapter,
    LaneStatus,
)

log = logging.getLogger("ccsync.sync.originals")

LANE_NAME = "lane_b_originals_down"
PROJECTS_PREFIX = "Projects/"

# D5 (owner, 2026-10-31): two transfers, one run at a time, whatever the
# machine's `transfers` says for lane B.
ORIGINALS_TRANSFERS = 2

# Its own partial name, disjoint from lane B's and express's (rclone derives
# the temp token from the file, so two runs writing one name would share a
# temp path; see rclone_lane.EXPRESS_PARTIAL_SUFFIX). Must stay <= 16 chars
# and end in `.partial`: lane A's IN_PROGRESS_EXCLUDE_RULES and
# scan_orphan_partials both key on that ending.
ORIGINALS_PARTIAL_SUFFIX = ".orig.partial"

# --max-duration for one run, SOFT, so the file in flight still lands (a 40 GB
# original killed at 39 GB restarts from byte 0). An hour, not the rotation
# budget express uses: this run is off the rotation by design, and a cut-off
# run simply starts again.
ORIGINALS_MAX_DURATION_SECONDS = 3600

# How often the lane looks at the plan with nothing to wake it. The sequencer
# hook and a Resolve request wake it sooner.
POLL_SECONDS = 120.0
# A plan that needed a NAS listing and found nothing to bring (every wanted
# file missing on the NAS, say) is not re-listed every poll.
RELIST_SECONDS = 900.0
# Just-landed files stay out of lane A this long. Lane A would only run an
# `--ignore-existing` no-op for them (the NAS has every one), but the express
# watchdog sees each arrival, and the hand-off is what keeps it quiet.
LANDED_EXCLUDE_SECONDS = 3600.0
# The project listing is a recursive walk, the shape list_remote_files caps at
# ten minutes for the same reason.
LIST_TIMEOUT_SECONDS = 600.0
# A selection item asking for more than this is truncated, with a warning. A
# list file is read once by rclone; this bounds what one plan can make it read.
MAX_WANTED_PER_PROJECT = 20000

LEDGER_FILENAME = "originals.json"
LEDGER_VERSION = 1

# Names that are never an original to bring, whatever the dashboard says.
_PARTIAL_ENDINGS = (".partial", ".tmp", ".part", ".ytdl", ".lock", ".ccsync-tmp")
_VIDEO_EXTS = frozenset(ext.lower() for ext in rclone_lane.VIDEO_EXTS)


def nfc(text: str) -> str:
    """COMPARISON ONLY (CR-90): NFC + case fold. Never a path to open."""
    return unicodedata.normalize("NFC", str(text or "")).casefold()


def list_rule_reason(rel: str) -> Optional[str]:
    """Why `rel` (posix, inside the project) may not enter the list, or None.

    These are the rules lane B's and lane A's filter files would apply, and
    which `--files-from-raw` will not let us pass as flags: inside the project,
    a video extension, not under Proxy/ (lane B's), not a partial, not trash,
    not hidden (`.ccsync-trash`, `.stversions`, AppleDouble `._x`), not a
    file-move staging name."""
    text = str(rel or "")
    if not text or "\n" in text or "\r" in text or "\x00" in text:
        return "not a usable name"
    if "\\" in text or text.startswith("/") or ":" in text.split("/", 1)[0]:
        return "not a relative posix path"
    segments = text.split("/")
    if any(seg in ("", ".", "..") for seg in segments):
        return "escapes the project"
    for seg in segments:
        if seg.startswith("."):
            return "hidden or trash"
        if seg.startswith(rclone_lane.MOVE_STAGING_PREFIX):
            return "a file move in progress"
    if any(seg.casefold() == "proxy" for seg in segments[:-1]):
        return "a proxy"
    name = segments[-1].casefold()
    if name.endswith(_PARTIAL_ENDINGS) or ".partial" in name:
        return "a partial download"
    if os.path.splitext(name)[1] not in _VIDEO_EXTS:
        return "not a video original"
    return None


@dataclass
class Want:
    """One project's wanted originals, as the dashboard spelled them."""
    slug: str
    project_rel: str
    rels: list = field(default_factory=list)


def wanted_by_project(selection: Optional[Iterable[Any]]) -> list[Want]:
    """The `originals` of every FULL tick in `selection`, per project.

    Reuses the sequencer's own validation so a project the rotation would not
    sync is not one this lane writes into. An upload-only tick brings nothing
    down (docs/UPLOAD_ONLY_TICK.md section 1): its originals are ignored even
    if a dashboard ever sent them. Fails closed per item on an unknown shape:
    `originals` must be a list of strings, or the item contributes nothing."""
    from .sequencer import _item_is_valid, _item_rel, _item_upload_only

    out: list[Want] = []
    for item in selection or []:
        if not isinstance(item, dict) or "originals" not in item:
            continue
        raw = item.get("originals")
        if raw is None:
            continue
        try:
            if not _item_is_valid(item) or _item_upload_only(item):
                continue
        except Exception:
            continue
        slug = str(item.get("slug"))
        if not isinstance(raw, list) or not all(isinstance(r, str) for r in raw):
            log.warning("originals: the dashboard sent an `originals` this build does "
                        "not understand for %s (%s) -- bringing nothing for it",
                        slug, type(raw).__name__)
            continue
        project_rel = _item_rel(item)
        if not project_rel:
            continue
        rels: list[str] = []
        seen: set[str] = set()
        for rel in raw:
            cleaned = rel.strip("/")
            key = nfc(cleaned)
            if not cleaned or key in seen:
                continue
            seen.add(key)
            rels.append(cleaned)
        if len(rels) > MAX_WANTED_PER_PROJECT:
            log.warning("originals: %s asks for %d files -- taking the first %d this run",
                        slug, len(rels), MAX_WANTED_PER_PROJECT)
            rels = rels[:MAX_WANTED_PER_PROJECT]
        if rels:
            out.append(Want(slug=slug, project_rel=project_rel.replace("\\", "/"), rels=rels))
    return out


def parse_listing(output: str) -> dict[str, tuple[int, str]]:
    """`rclone lsf -R --files-only --format spt --separator ;` -> {rel: (size, mtime)}.

    Size and time first because neither can hold the separator, so the
    remainder after the second one is the whole filename, `;` and all."""
    found: dict[str, tuple[int, str]] = {}
    for line in str(output or "").splitlines():
        size_text, sep, rest = line.partition(";")
        if not sep:
            continue
        mtime, sep2, path = rest.partition(";")
        if not sep2:
            continue
        try:
            size = int(size_text.strip())
        except ValueError:
            continue
        rel = path.rstrip("\r").strip("/")
        if rel:
            found[rel] = (size, mtime.strip())
    return found


def listing_command(rclone_path: str, remote: str, remote_root: str,
                    project_rel: str) -> list[str]:
    side = rclone_lane._join_remote_path(remote_root, PROJECTS_PREFIX + project_rel)
    return [rclone_path, "lsf", "-R", "--files-only", "--format", "spt",
            "--separator", ";", f"{remote}:{side}"]


@dataclass
class Entry:
    slug: str
    project_rel: str
    rel: str          # the NAS's own spelling, relative to the project
    size: int
    nas_mtime: str


@dataclass
class Plan:
    entries: list = field(default_factory=list)
    not_on_server: int = 0
    refused: int = 0
    already_here: int = 0
    differs_here: int = 0


def plan_project(want: Want, nas_files: dict[str, tuple[int, str]],
                 local_project_dir: Path,
                 stat_fn: Callable[[Path], Optional[int]]) -> Plan:
    """What to put in the list for one project.

    Every wanted rel is matched against THIS run's NAS listing by NFC key and
    the NAS's spelling is what goes forward; a name the listing does not hold
    never reaches the list. A file already here at the same size is skipped;
    one here at a DIFFERENT size is the editor's own and is left alone
    (`--ignore-existing` would skip it anyway; leaving it out keeps the counts
    honest)."""
    by_key: dict[str, tuple[str, int, str]] = {}
    for nas_rel, (size, mtime) in nas_files.items():
        by_key.setdefault(nfc(nas_rel), (nas_rel, size, mtime))
    plan = Plan()
    for rel in want.rels:
        hit = by_key.get(nfc(rel))
        if hit is None:
            plan.not_on_server += 1
            continue
        nas_rel, size, mtime = hit
        if list_rule_reason(nas_rel) is not None:
            plan.refused += 1
            continue
        local_size = stat_fn(local_project_dir.joinpath(*nas_rel.split("/")))
        if local_size is None and nas_rel != rel:
            local_size = stat_fn(local_project_dir.joinpath(*rel.split("/")))
        if local_size is not None:
            if local_size == size:
                plan.already_here += 1
            else:
                plan.differs_here += 1
            continue
        plan.entries.append(Entry(want.slug, want.project_rel, nas_rel, size, mtime))
    return plan


def _stat_size(path: Path) -> Optional[int]:
    try:
        st = os.stat(path)
    except OSError:
        return None
    return None if stat.S_ISDIR(st.st_mode) else int(st.st_size)


def build_originals_command(cfg: dict[str, Any], project_rel: str, local_root: str,
                            list_file: Path,
                            max_duration_seconds: Optional[float] = ORIGINALS_MAX_DURATION_SECONDS,
                            ) -> list[str]:
    """The argv for one project's run (SELECTIVE_ORIGINALS.md 4.2).

    `copy`, never `sync`: it cannot delete. `--ignore-existing`: it cannot
    overwrite. The source reads the tree through the download route exactly
    as broll_fetch.build_fetch_command does (it writes nothing on the server),
    so a tunnel route or an operator's tuning knob applies here too. NO filter
    flag of any kind: `--files-from-raw` refuses them, and the run would die
    at startup (rclone_lane.build_express_command's measurement)."""
    rclone_path = str(cfg.get("rclone_path") or "rclone")
    route = rclone_lane.down_route(cfg)
    tuning = rclone_lane.RcloneTuning.from_cfg(cfg)
    rel = str(project_rel).replace("\\", "/").strip("/")
    src = f"{route.remote}:{rclone_lane._join_remote_path(route.remote_root, PROJECTS_PREFIX + rel)}"
    dest = str(Path(local_root) / "Projects" / Path(*rel.split("/")))
    return [
        rclone_path,
        "copy",
        src,
        dest,
        "--files-from-raw", str(list_file),
        "--ignore-existing",
        "--no-traverse",
        "--partial-suffix", ORIGINALS_PARTIAL_SUFFIX,
        "--transfers", str(ORIGINALS_TRANSFERS),
        *rclone_lane._max_duration_flags(max_duration_seconds),
        *tuning.flags(rclone_lane.DIRECTION_DOWN),
        *rclone_lane.route_flags(route.via),
        *rclone_lane._transport_flags(),
        "--use-json-log",
        "--verbose",
        "--stats", "2s",
        "--stats-log-level", "NOTICE",
    ]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _iso_epoch(stamp: Any) -> Optional[float]:
    try:
        when = datetime.fromisoformat(str(stamp))
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when.timestamp()


def _human_bytes(n: Any) -> str:
    try:
        size = float(n or 0)
    except (TypeError, ValueError):
        return "?"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return "?"


def progress_sentence(done: int, total: int, bytes_left: int) -> str:
    """The tray line (12.1 copy, no em dashes)."""
    return f"Bringing originals: {done} of {total}, {_human_bytes(bytes_left)} to go"


class OriginalsLedger:
    """`~/.ccsync/state/originals.json`: what this lane brought down.

    It is what phase 3's "free the space" will check against, and what lane
    A's exclude hand-off reads for just-landed names. It is NEVER the source
    of what to download; the dashboard is. Written atomically (tmp +
    os.replace), because a torn ledger is a lost record of which files are
    copies the server already holds."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self._files: dict[str, dict] = {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            files = data.get("files") if isinstance(data, dict) else None
            if isinstance(files, dict):
                self._files = {str(k): dict(v) for k, v in files.items() if isinstance(v, dict)}
        except FileNotFoundError:
            pass
        except Exception:
            log.warning("originals: could not read %s -- starting a new ledger", self.path,
                        exc_info=True)

    @staticmethod
    def key(slug: str, rel: str) -> str:
        return f"{slug}/{nfc(rel)}"

    def record(self, entry: Entry, arrived_at: Optional[str] = None) -> None:
        with self._lock:
            self._files[self.key(entry.slug, entry.rel)] = {
                "slug": entry.slug,
                "project_rel": entry.project_rel,
                "rel": entry.rel,
                "size": int(entry.size),
                "nas_mtime": entry.nas_mtime,
                "arrived_at": arrived_at or _now_iso(),
            }
            snapshot = dict(self._files)
        self._write(snapshot)

    def has(self, slug: str, rel: str) -> bool:
        with self._lock:
            return self.key(slug, rel) in self._files

    def entries(self) -> list[dict]:
        with self._lock:
            return [dict(v) for v in self._files.values()]

    def _write(self, files: dict) -> None:
        tmp = self.path.with_name(f"{self.path.name}.{os.getpid()}.tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump({"version": LEDGER_VERSION, "files": files}, fh,
                          ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)
        except OSError:
            log.warning("originals: could not write %s", self.path, exc_info=True)
            try:
                os.unlink(tmp)
            except OSError:
                pass


def _under(full: str, root: str) -> str:
    """`full` relative to the run root `root`, "" when outside it. Component-
    wise and NFC/case folded (file_moves._under's rule, bug-hunt-2026-09-03
    comp-sync-3); an empty root is the whole tree."""
    if not root:
        return full
    parts = [p for p in full.split("/") if p]
    root_parts = [p for p in root.split("/") if p]
    if len(parts) <= len(root_parts):
        return ""
    if [nfc(p) for p in parts[:len(root_parts)]] != [nfc(p) for p in root_parts]:
        return ""
    return "/".join(parts[len(root_parts):])


class OriginalsDownLane(LaneAdapter):
    """`lane_b_originals_down`: one slot, its own thread, down only."""

    name = LANE_NAME

    def __init__(
        self,
        cfg: dict[str, Any],
        state_dir: Path,
        selection_fn: Callable[[], Optional[list]],
        disk_floor: Optional["lane_guard.DiskFloorLatch"] = None,
        halted_fn: Optional[Callable[[], bool]] = None,
        root_present_fn: Optional[Callable[[], bool]] = None,
        paused_fn: Optional[Callable[[], bool]] = None,
        remote_list_fn: Optional[Callable[[list[str], float], Optional[str]]] = None,
        popen_factory: Optional[Callable[..., Any]] = None,
        free_bytes_fn: Optional[Callable[[Any], Optional[int]]] = None,
        refusal_fn: Optional[Callable[[dict, str], Optional[str]]] = None,
        clock: Callable[[], float] = time.time,
        poll_seconds: float = POLL_SECONDS,
    ) -> None:
        self.cfg = cfg
        self.local_root = str(cfg.get("local_root") or "")
        self._state_dir = Path(state_dir)
        self._selection_fn = selection_fn
        self.disk_floor = disk_floor
        self._halted_fn = halted_fn or (lambda: False)
        self._root_present_fn = root_present_fn or (lambda: True)
        # The tray's Pause. In managed mode it pauses only the sequencer and
        # express (app.toggle_pause), so this lane, which is neither, asks.
        self._paused_fn = paused_fn or (lambda: False)
        self._remote_list_fn = remote_list_fn or rclone_lane._run_lsf
        self._popen = popen_factory or subprocess.Popen
        self._free_bytes_fn = free_bytes_fn or lane_guard.free_bytes_at
        self._refusal_fn = refusal_fn
        self._clock = clock
        self.poll_seconds = float(poll_seconds)
        self.ledger = OriginalsLedger(self._state_dir / LEDGER_FILENAME)
        # `_lock` and `_status` by those names: app.py stamps every lane's
        # detail through them (halt, sign-in, misconfiguration, drive out).
        self._lock = threading.Lock()
        self._status = LaneStatus(name=LANE_NAME)
        self._wake = threading.Event()
        self._stop_event: Optional[threading.Event] = None
        self._thread: Optional[threading.Thread] = None
        self._proc: Any = None
        self._abort_reason: Optional[str] = None
        # In flight right now: Entry list of the run in progress.
        self._inflight: list[Entry] = []
        # The signature of the last plan that needed a listing and found
        # nothing to bring, and when (RELIST_SECONDS).
        self._idle_signature: Optional[tuple] = None
        self._idle_at = 0.0
        # What note_selection last saw, so only a CHANGE wakes the lane.
        self._seen_signature: Optional[tuple] = None
        self._run_seq = 0
        # Arrivals of this process, (full tree rel, epoch), for lane A's hook.
        self._landed: list[tuple[str, float]] = []

    # -- LaneAdapter ---------------------------------------------------------
    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        # A fresh event per generation (rclone_lane's L-2 rule): a stop()
        # whose join timed out mid-run must not be re-armed by the next start.
        stop_event = threading.Event()
        self._stop_event = stop_event
        self._thread = threading.Thread(target=self._loop, args=(stop_event,),
                                        name="ccsync-originals-down", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        stop_event = self._stop_event
        if stop_event is not None:
            stop_event.set()
        self._wake.set()
        self._kill("the companion is stopping sync")
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=5.0)

    def status(self) -> LaneStatus:
        with self._lock:
            return LaneStatus(**vars(self._status))

    def run_once(self) -> LaneStatus:
        self.wake()
        return self.status()

    # -- wiring --------------------------------------------------------------
    def wake(self) -> None:
        """Look at the plan now (a pick changed, a request was answered)."""
        self._idle_signature = None
        self._wake.set()

    def note_selection(self, selection: Optional[list]) -> None:
        """The sequencer's hook: called with every selection it reads.

        Wakes the lane when the wanted set changed, and stops a run whose
        files are no longer wanted (5.1: un-picking stops a download that has
        not finished; the files already down stay). Never raises."""
        try:
            wants = wanted_by_project(selection)
            signature = self._signature(wants)
            if signature != self._seen_signature:
                self._seen_signature = signature
                self.wake()
            with self._lock:
                inflight = list(self._inflight)
            if inflight:
                wanted = {(w.slug, nfc(r)) for w in wants for r in w.rels}
                if any((e.slug, nfc(e.rel)) not in wanted for e in inflight):
                    self._kill("some of these originals are no longer asked for")
        except Exception:
            log.exception("originals: note_selection failed")

    def lane_a_excludes(self, subpath: Optional[str]) -> list[str]:
        """Lane A's exclude hook (the one file_moves feeds): every name this
        lane is writing now or landed in the last hour, relative to `subpath`
        (a lane A run root like `Projects/2026/X`, or None for local_root,
        which is what express asks with). Both Unicode spellings, as
        FileMoveLedger.recent_excludes emits them (SYNC-11). Never raises."""
        try:
            wanted = str(subpath or "").replace("\\", "/").strip("/")
            if wanted and not wanted.lower().startswith(PROJECTS_PREFIX.lower()):
                wanted = PROJECTS_PREFIX + wanted
            cutoff = self._clock() - LANDED_EXCLUDE_SECONDS
            with self._lock:
                fulls = [f"{PROJECTS_PREFIX}{e.project_rel}/{e.rel}" for e in self._inflight]
                self._landed = [(p, at) for p, at in self._landed if at >= cutoff]
                fulls += [p for p, _at in self._landed]
            out: list[str] = []
            for full in fulls:
                rel = _under(full, wanted)
                if not rel:
                    continue
                for spelling in (unicodedata.normalize("NFC", rel),
                                 unicodedata.normalize("NFD", rel)):
                    if spelling not in out:
                        out.append(spelling)
            return out
        except Exception:
            log.exception("originals: lane A exclude hand-off failed -- excluding nothing")
            return []

    # -- the loop ------------------------------------------------------------
    def _loop(self, stop_event: threading.Event) -> None:
        while not stop_event.is_set():
            self._wake.clear()
            try:
                self.cycle(stop_event)
            except Exception as exc:
                log.exception("originals: a run failed")
                self._set(state=STATE_ERROR, last_error=f"could not bring originals: {exc}",
                          detail="", transferring=0, queued=0)
            if stop_event.is_set():
                break
            self._wake.wait(self.poll_seconds)

    @staticmethod
    def _signature(wants: list[Want]) -> tuple:
        return tuple(sorted((w.slug, nfc(r)) for w in wants for r in w.rels))

    def _set(self, **fields: Any) -> None:
        with self._lock:
            for key, value in fields.items():
                setattr(self._status, key, value)

    def _stand_down(self, detail: str) -> None:
        self._set(state=STATE_PAUSED, detail=detail, transferring=0, queued=0,
                  speed_bps=None, eta_seconds=None, transfers=[],
                  progress_token=None, last_error=None)

    def _idle(self, detail: str = "") -> None:
        self._set(state=STATE_IDLE, detail=detail, transferring=0, queued=0,
                  speed_bps=None, eta_seconds=None, transfers=[],
                  bytes_done=None, bytes_total=None, progress_token=None)

    def _gate(self) -> Optional[str]:
        try:
            if self._halted_fn():
                return "NOT DOWNLOADING ORIGINALS: syncing is stopped on this computer"
        except Exception:
            log.debug("originals: halt check failed", exc_info=True)
        try:
            if self._paused_fn():
                return "NOT DOWNLOADING ORIGINALS: syncing is paused"
        except Exception:
            log.debug("originals: pause check failed", exc_info=True)
        try:
            if not self._root_present_fn():
                return "NOT DOWNLOADING ORIGINALS: the sync drive is not connected"
        except Exception:
            log.debug("originals: root check failed", exc_info=True)
        return None

    def _local_project_dir(self, project_rel: str) -> Path:
        return Path(self.local_root) / "Projects" / Path(*project_rel.split("/"))

    def _refusal(self, dest: str) -> Optional[str]:
        if self._refusal_fn is not None:
            return self._refusal_fn(self.cfg, dest)
        from .. import broll_fetch  # lazy: broll_fetch imports this package
        return broll_fetch.fetch_refusal(self.cfg, dest)

    def _list_nas(self, project_rel: str) -> Optional[dict[str, tuple[int, str]]]:
        route = rclone_lane.down_route(self.cfg)
        cmd = listing_command(str(self.cfg.get("rclone_path") or "rclone"),
                              route.remote, route.remote_root, project_rel)
        output = self._remote_list_fn(cmd, LIST_TIMEOUT_SECONDS)
        if output is None:
            return None
        return parse_listing(output)

    def cycle(self, stop_event: Optional[threading.Event] = None) -> None:
        """One look at the plan and, if there is work, one run per project.
        Public for the tests; the thread calls it."""
        stop_event = stop_event or threading.Event()
        gate = self._gate()
        if gate:
            self._stand_down(gate)
            return
        try:
            selection = self._selection_fn()
        except Exception:
            log.debug("originals: selection read failed", exc_info=True)
            selection = None
        wants = wanted_by_project(selection)
        if not wants:
            self._idle()
            return
        # Cheap first: a wanted file already at its own spelling here costs a
        # stat, not a NAS listing.
        outstanding: list[Want] = []
        for want in wants:
            base = self._local_project_dir(want.project_rel)
            rels = [r for r in want.rels if _stat_size(base.joinpath(*r.split("/"))) is None]
            if rels:
                outstanding.append(Want(want.slug, want.project_rel, rels))
        if not outstanding:
            self._idle(f"all {sum(len(w.rels) for w in wants)} asked-for originals are here")
            return
        signature = self._signature(outstanding)
        if (signature == self._idle_signature
                and (self._clock() - self._idle_at) < RELIST_SECONDS):
            return

        entries: list[Entry] = []
        not_on_server = 0
        for want in outstanding:
            dest = str(self._local_project_dir(want.project_rel))
            refusal = self._refusal(dest)
            if refusal:
                self._stand_down(f"NOT DOWNLOADING ORIGINALS: {refusal}")
                return
            listing = self._list_nas(want.project_rel)
            if listing is None:
                self._set(state=STATE_ERROR, transferring=0, queued=0, detail="",
                          last_error="could not list the server to find the originals")
                return
            plan = plan_project(want, listing, self._local_project_dir(want.project_rel),
                                _stat_size)
            not_on_server += plan.not_on_server
            if plan.not_on_server or plan.refused or plan.differs_here:
                log.info("originals: %s: %d not on the server, %d not originals, %d "
                         "already here at another size (left alone)", want.slug,
                         plan.not_on_server, plan.refused, plan.differs_here)
            entries.extend(plan.entries)
        if not entries:
            self._idle_signature, self._idle_at = signature, self._clock()
            self._idle(f"{not_on_server} asked-for originals are not on the server"
                       if not_on_server else "")
            return

        total_bytes = sum(e.size for e in entries)
        disk = self._disk_refusal(total_bytes)
        if disk:
            self._stand_down(f"NOT DOWNLOADING ORIGINALS (disk): {disk}")
            return

        self._run_all(entries, total_bytes, stop_event)

    def _disk_refusal(self, total_bytes: int) -> Optional[str]:
        """The shared floor first (a nearly-full drive parks originals with lane
        B), then section 4.2's refusal of a run that would not fit above it."""
        try:
            free = self._free_bytes_fn(self.local_root)
        except Exception:
            free = None
        floor = 0
        if self.disk_floor is not None and getattr(self.disk_floor, "enabled", True):
            try:
                reason = self.disk_floor.check(free)
            except Exception:
                log.exception("originals: the free-space floor check failed")
                reason = None
            if reason:
                return reason
            floor = int(getattr(self.disk_floor, "min_free_bytes", 0) or 0)
        if free is None:
            return None
        room = int(free) - floor
        if total_bytes > room:
            kept = f", keeping {_human_bytes(floor)} free" if floor else ""
            return (f"these originals need {_human_bytes(total_bytes)} and this drive has "
                    f"{_human_bytes(max(0, room))} to give{kept}")
        return None

    # -- a run ---------------------------------------------------------------
    def _run_all(self, entries: list[Entry], total_bytes: int,
                 stop_event: threading.Event) -> None:
        total = len(entries)
        state = {"done_files": 0, "done_bytes": 0, "failed": 0}
        by_project: dict[str, list[Entry]] = {}
        for entry in entries:
            by_project.setdefault(entry.project_rel, []).append(entry)
        self._abort_reason = None
        self._set(state=STATE_SYNCING, last_error=None, queued=total, transferring=0,
                  bytes_total=total_bytes, bytes_done=0, transfers=[],
                  current_project=None,
                  detail=progress_sentence(0, total, total_bytes),
                  progress_token=rclone_lane.progress_token(0, 0, None))
        error: Optional[str] = None
        work_remained = False
        for project_rel, batch in by_project.items():
            if stop_event.is_set() or self._abort_reason:
                break
            gate = self._gate()
            if gate:
                self._abort_reason = gate
                break
            code, run_error = self._run_project(project_rel, batch, total, total_bytes,
                                                state, stop_event)
            if code == rclone_lane.RCLONE_EXIT_MAX_DURATION:
                work_remained = True
            elif code not in (0, None) and not self._abort_reason:
                error = run_error or f"rclone exited with code {code}"
        with self._lock:
            self._inflight = []
        done = state["done_files"]
        if self._abort_reason:
            log.info("originals: run stopped (%s) after %d of %d", self._abort_reason,
                     done, total)
            gate = self._gate()
            if gate:
                self._stand_down(gate)
            else:
                self._idle()
                self._wake.set()
            return
        if error:
            self._set(state=STATE_ERROR, last_error=error, transferring=0, queued=0,
                      speed_bps=None, eta_seconds=None, transfers=[],
                      detail=f"brought {done} of {total} originals down")
            return
        self._set(last_sync=datetime.now(timezone.utc))
        self._idle(f"brought {done} of {total} originals down" if done else "")
        if work_remained:
            self._wake.set()

    def _next_list_file(self, slug: str) -> Path:
        self._run_seq += 1
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in slug)[:64]
        return self._state_dir / f"originals_{safe}_{os.getpid()}_{self._run_seq}.txt"

    def _run_project(self, project_rel: str, batch: list[Entry], total: int,
                     total_bytes: int, state: dict,
                     stop_event: threading.Event) -> tuple[Optional[int], Optional[str]]:
        list_file = self._next_list_file(batch[0].slug)
        try:
            rclone_lane.write_files_from_list([e.rel for e in batch], list_file)
        except (rclone_lane.ExpressListError, OSError) as exc:
            return 1, f"could not write the list of originals: {exc}"
        by_name = {e.rel: e for e in batch}
        by_key = {nfc(e.rel): e for e in batch}
        with self._lock:
            self._inflight = list(batch)
        cmd = build_originals_command(self.cfg, project_rel, self.local_root, list_file)
        errors: list[str] = []
        base_bytes = state["done_bytes"]
        try:
            try:
                proc = self._popen(
                    cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE, encoding="utf-8", errors="replace",
                    creationflags=rclone_lane._win_creationflags())
            except OSError as exc:
                return 1, f"could not start rclone: {exc}"
            with self._lock:
                self._proc = proc
            if self._abort_reason or stop_event.is_set():
                self._kill(self._abort_reason or "stopping")

            def _landed(entry: Entry) -> None:
                if entry.rel in done_names:
                    return
                done_names.add(entry.rel)
                self.ledger.record(entry)
                with self._lock:
                    self._landed.append((f"{PROJECTS_PREFIX}{entry.project_rel}/{entry.rel}",
                                         self._clock()))
                state["done_files"] += 1
                state["done_bytes"] += int(entry.size)

            done_names: set[str] = set()
            stats_bytes = [0]

            def _reader() -> None:
                try:
                    for line in proc.stderr:
                        self._feed(line, by_name, by_key, _landed, errors, stats_bytes,
                                   total, total_bytes, base_bytes, state)
                except Exception:
                    log.exception("originals: stderr reader failed -- killing rclone")
                    self._kill("the progress reader failed")

            reader = threading.Thread(target=_reader, name="ccsync-originals-stderr",
                                      daemon=True)
            reader.start()
            code = self._wait(proc, stop_event)
            reader.join(timeout=rclone_lane.STDERR_READER_JOIN_SECONDS)
            # The log line is not the only witness: anything that is now here
            # at the size the NAS listed is in, whatever rclone printed.
            base = self._local_project_dir(project_rel)
            for entry in batch:
                if entry.rel in done_names:
                    continue
                if _stat_size(base.joinpath(*entry.rel.split("/"))) == entry.size:
                    _landed(entry)
            failed = len(batch) - len(done_names)
            if code == 0 and failed:
                state["failed"] += failed
                return 1, (errors[-1] if errors else
                           f"{failed} originals did not arrive")
            return code, (errors[-1] if errors else None)
        finally:
            with self._lock:
                self._proc = None
            try:
                os.unlink(list_file)
            except OSError:
                pass

    def _feed(self, line: str, by_name: dict, by_key: dict, landed: Callable[[Entry], None],
              errors: list, stats_bytes: list, total: int, total_bytes: int,
              base_bytes: int, state: dict) -> None:
        line = str(line or "").strip()
        if not line.startswith("{"):
            return
        try:
            record = json.loads(line)
        except ValueError:
            return
        stats = record.get("stats")
        if isinstance(stats, dict):
            try:
                stats_bytes[0] = int(stats.get("bytes") or 0)
            except (TypeError, ValueError):
                pass
            inflight = [t for t in (stats.get("transferring") or []) if isinstance(t, dict)]
            done_bytes = min(total_bytes, base_bytes + stats_bytes[0])
            done_bytes = max(done_bytes, state["done_bytes"])
            left = max(0, total_bytes - done_bytes)
            remaining = total - state["done_files"]
            self._set(transferring=len(inflight), queued=max(0, remaining - len(inflight)),
                      bytes_done=done_bytes, speed_bps=stats.get("speed"),
                      eta_seconds=stats.get("eta"),
                      detail=progress_sentence(state["done_files"], total, left),
                      progress_token=rclone_lane.progress_token(
                          done_bytes, state["done_files"], None))
            return
        name = str(record.get("object") or "")
        msg = str(record.get("msg") or "")
        if name and "Copied" in msg:
            entry = by_name.get(name) or by_key.get(nfc(name))
            if entry is not None:
                landed(entry)
                left = max(0, total_bytes - state["done_bytes"])
                self._set(detail=progress_sentence(state["done_files"], total, left))
            return
        if str(record.get("level", "")).lower() in ("error", "critical", "fatal"):
            if msg and "fatal error received" not in msg.lower():
                errors.append(msg[:300])

    def _wait(self, proc: Any, stop_event: threading.Event) -> Optional[int]:
        """Wait for rclone, ending it on a stop, an un-pick, a halt, a lost
        drive, or a run that has outlived even the soft cutoff's grace."""
        ceiling = rclone_lane.hard_ceiling_seconds(ORIGINALS_MAX_DURATION_SECONDS)
        started = time.monotonic()
        while True:
            try:
                return proc.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                pass
            if stop_event.is_set():
                self._kill("the companion is stopping sync")
            gate = self._gate()
            if gate:
                self._abort_reason = gate
                self._kill(gate)
            if time.monotonic() - started > ceiling:
                log.warning("originals: rclone ran past %.0fs -- ending it", ceiling)
                self._kill("the run outlived its time limit")

    def _kill(self, why: str) -> None:
        # The reason is recorded even with no child running: an un-pick that
        # lands between two projects' runs must stop the next one too.
        if self._abort_reason is None:
            self._abort_reason = why
        with self._lock:
            proc = self._proc
        if proc is None:
            return
        try:
            proc.kill()
        except Exception:
            log.debug("originals: kill failed", exc_info=True)
