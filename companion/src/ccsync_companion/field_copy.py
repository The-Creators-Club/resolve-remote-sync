"""Field backup: copy one card to every ticked destination at once, one lane per physical drive.

Companion half of footage-sorter docs/LEDGER-BROWSER-DESIGN.md, "The companion" item 4. The page
(field_server.py) picks a card and ticks destinations; this module is the engine behind
"Copy to all".

HOW IT COPIES. Not a second copier: every destination's files go through `card_copy.CardJob`,
the copier behind the `card-ingest` job, so TeraCopy on Windows (history-database truth,
TestAlways verify, /SkipAll) and the Python copier elsewhere behave exactly as they do for the
sorter, and the rules that protect footage are the same ones:

  * NEVER OVERWRITE. A different file already at the destination is a `conflict`, left alone and
    shown. A partial of THIS file (an interrupted copy) is resumed, never replaced blind.
  * A FILE THAT IS ALREADY THERE is not copied: same size and mtime (2.5 s, exFAT keeps 2) at its
    place, or already on that drive under another name per the ledger mirror and confirmed on disk.
    Each is QUICK-VERIFIED against the card (size, first and last MiB, the moov) and recorded
    `quick`, so running a card again is also the way to check it.
  * A COPY IS RECORDED ONLY WHEN VERIFIED: `full` when the copier verified it (TeraCopy's hash
    check, or the Python copier's read-back), `quick` when only the quick compare did.

ONE LANE PER PHYSICAL DRIVE, at the same time. Destinations that share a physical disk (two folders
on D:, or two partitions of one disk) go through ONE lane, one after the other; destinations on
different disks run together. The card is read by every lane at once, which is what makes copying
to three drives take as long as the slowest.

THE DESTINATION LAYOUT is the October field one: `<destination>/<day> <card label or serial>/<the
card's own tree>` (field_mode.card_folder_name), under a `FieldBackup` folder on a drive or the NAS
pool, and straight into a configured laptop folder.

FAILURES, each in words:
  * a destination without room is REFUSED before a byte moves (its lane says how much it has and
    needs); the others carry on;
  * a drive that fills up mid-copy, or is pulled, stops its lane (checked every two seconds and by
    the copier's own errors); what had landed whole is kept, recorded, and shown.
"""
from __future__ import annotations

import logging
import os
import shutil
import threading
import time
from contextlib import ExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from . import card_copy, field_mode, sorter_cards
from . import teracopy as teracopy_mod

log = logging.getLogger("ccsync.fieldcopy")

MARGIN_BYTES = 256 * 1024 * 1024          # kept spare on a destination (October: freeSpaceMarginMB 256)
FULL_BYTES = 48 * 1024 * 1024             # free space below this mid-copy = the drive is full
ALIVE_SECONDS = 2.0
RATE_WINDOW_SECONDS = 6.0
MAX_PROBLEMS = 40
POOL_ROOT = "pool"                         # the job_paths root every lane writes under

STATES = ("queued", "planning", "checking", "copying", "done", "attention", "failed", "stopped", "refused")
TERMINAL = ("done", "attention", "failed", "stopped", "refused")


def fmt_bytes(n: Any) -> str:
    try:
        v = float(n)
    except (TypeError, ValueError):
        return "?"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(v) < 1000 or unit == "TB":
            return f"{v:.0f} {unit}" if unit == "B" else (f"{v:.1f} {unit}" if v < 100 else f"{v:.0f} {unit}")
        v /= 1000.0
    return "?"


def rel_of_current(text: Any) -> str:
    """CardJob's Progress.current is str() of the source reference, `{'root': 'card:X', 'rel': 'a/b.MP4'}`;
    the page wants the card-relative path."""
    s = str(text or "")
    if s.startswith("{") and "'rel'" in s:
        head, _, tail = s.partition("'rel':")
        return tail.strip().strip("}").strip().strip("'\"") or s
    return s


def looks_full(text: str) -> bool:
    t = str(text or "").lower()
    return ("no space left" in t or "not enough space" in t or "disk is full" in t
            or "errno 28" in t or "winerror 112" in t or "winerror 39" in t)


@dataclass
class Destination:
    """Where one lane writes. `root` is an existing directory; `subdir` is the folder under it that
    holds the card folders ("FieldBackup" on a drive, "" for a configured laptop folder)."""
    id: str
    kind: str                          # drive | folder | pool
    label: str
    root: str
    subdir: str = ""
    volume_id: str = ""                # vol:<SERIAL> | nas:<share> | "" (not recordable)
    volume_label: str = ""
    volume_root: str = ""              # the volume's own root, for the ledger's relative paths
    volume_kind: str = "unknown"
    serial: str = ""
    lane: str = ""                     # the physical drive key
    recordable: bool = True            # the outbox can carry it (a local volume with a serial)

    def base(self, folder: str) -> Path:
        parts = [p for p in (self.subdir, folder) if p]
        return Path(self.root).joinpath(*parts)

    def rel_of(self, absolute: "str | Path") -> str:
        """Path relative to the volume root, '/'-separated: what the ledger stores."""
        try:
            return Path(absolute).relative_to(Path(self.volume_root or self.root)).as_posix()
        except ValueError:
            return Path(absolute).name


def group_by_lane(dests: list[Destination]) -> dict[str, list[Destination]]:
    """Destinations that share a physical drive are one lane, in the order given."""
    out: dict[str, list[Destination]] = {}
    for d in dests:
        out.setdefault(d.lane or d.id, []).append(d)
    return out


# ------------------------------------------------------------------------------------------ planning
@dataclass
class PlanItem:
    rel: str                           # the card-relative path, '/'-separated
    size: int
    mtime: Any
    action: str                        # copy | resume | there | elsewhere
    dst: Path                          # where it goes / is
    found: Optional[Path] = None       # for `elsewhere`: where the drive already has it


@dataclass
class Plan:
    items: list[PlanItem] = field(default_factory=list)

    def of(self, *actions: str) -> list[PlanItem]:
        return [i for i in self.items if i.action in actions]

    @property
    def copy_bytes(self) -> int:
        return sum(i.size for i in self.of("copy", "resume"))


def plan_destination(card_files: list[list[Any]], dest: Destination, folder: str,
                     view: Optional[field_mode.LedgerView] = None) -> Plan:
    """What each file needs at this destination. Read-only: stats, nothing else."""
    base = dest.base(folder)
    plan = Plan()
    for row in card_files:
        rel, size, mtime = str(row[0]), int(row[1]), row[2]
        dst = base.joinpath(*rel.split("/"))
        try:
            st = os.stat(dst)
        except OSError:
            st = None
        if st is not None:
            if not dst.is_file():
                plan.items.append(PlanItem(rel, size, mtime, "copy", dst))      # CardJob: a conflict
            elif st.st_size == size and field_mode.same_mtime(st.st_mtime * 1000.0, mtime):
                plan.items.append(PlanItem(rel, size, mtime, "there", dst))
            elif st.st_size < size:
                plan.items.append(PlanItem(rel, size, mtime, "resume", dst))
            else:
                plan.items.append(PlanItem(rel, size, mtime, "copy", dst))      # CardJob: skip or conflict
            continue
        found = _already_on_volume(view, dest, rel, size, mtime) if view is not None else None
        if found is not None:
            plan.items.append(PlanItem(rel, size, mtime, "elsewhere", dst, found))
        else:
            plan.items.append(PlanItem(rel, size, mtime, "copy", dst))
    return plan


def _already_on_volume(view: field_mode.LedgerView, dest: Destination, rel: str, size: int,
                       mtime: Any) -> Optional[Path]:
    """The ledger says this drive holds the file under another name or folder; believe it only if
    the file is really there now, at the right size and time."""
    if not dest.volume_id or not dest.volume_root or not field_mode.is_recordable(rel):
        return None
    name = rel.rsplit("/", 1)[-1]
    for row in view.copies(name, size, mtime):
        if row.get("volume_id") != dest.volume_id or not row.get("path"):
            continue
        cand = Path(dest.volume_root).joinpath(*str(row["path"]).split("/"))
        try:
            st = os.stat(cand)
        except OSError:
            continue
        if st.st_size == size and field_mode.same_mtime(st.st_mtime * 1000.0, mtime):
            return cand
    return None


# ---------------------------------------------------------------------------------------------- lanes
class Lane:
    """One destination's progress. Written by its lane thread, read by the page's polls: plain
    values, so a torn read is a number one beat stale."""

    def __init__(self, run_id: str, dest: Destination) -> None:
        self.run_id = run_id
        self.dest = dest
        self.state = "queued"
        self.message = ""
        self.phase = "copy"                # copy | verify
        self.stage = ""                    # what it is doing, in words
        self.copier = ""
        self.current = ""
        self.files_total = 0
        self.files_done = 0
        self.bytes_total = 0
        self.bytes_done = 0
        self.counts = {"copied": 0, "skipped": 0, "there": 0, "conflicts": 0, "failed": 0, "unverified": 0}
        self.problems: list[dict[str, str]] = []
        self.recorded = 0
        self.started: Optional[float] = None
        self.finished: Optional[float] = None
        self._samples: list[tuple[float, int]] = []
        self.progress: Optional[card_copy.Progress] = None
        self._vf_bytes_total = 0
        self._vf_bytes_done = 0
        self._copy_bytes_total = 0
        self._copy_done_final = 0
        self._lock = threading.Lock()

    # -- numbers ---------------------------------------------------------------------------------
    def _done_total(self) -> tuple[int, int]:
        copy_done = int(self.progress.bytes) if self.progress is not None else self._copy_done_final
        copy_done = min(copy_done, self._copy_bytes_total) if self._copy_bytes_total else copy_done
        return self._vf_bytes_done + copy_done, self._vf_bytes_total + self._copy_bytes_total

    def problem(self, path: str, why: str) -> None:
        if len(self.problems) < MAX_PROBLEMS:
            self.problems.append({"path": path, "why": why})

    def snapshot(self, now: Optional[float] = None) -> dict[str, Any]:
        now = time.monotonic() if now is None else now
        done, total = self._done_total()
        with self._lock:
            if not self._samples or now - self._samples[-1][0] >= 0.5:
                self._samples.append((now, done))
            while len(self._samples) > 2 and now - self._samples[1][0] >= RATE_WINDOW_SECONDS:
                self._samples.pop(0)
            t0, b0 = self._samples[0]
        running = self.state in ("planning", "checking", "copying")
        prog = self.progress
        phase = prog.phase if (prog is not None and self.state == "copying") else self.phase
        bps = int((done - b0) / (now - t0)) if (running and now - t0 > 0 and done >= b0) else 0
        if phase == "verify" and self.state == "copying":
            bps = 0
        remaining = max(0, total - done)
        eta = int(remaining / bps) if bps > 0 and running else None
        pct = (100.0 * done / total) if total > 0 else (100.0 if self.state in TERMINAL and self.state != "refused" else 0.0)
        if running:
            pct = min(pct, 99.0)
        elif self.state in ("done", "attention"):
            pct = 100.0
        current = (rel_of_current(prog.current) if (prog is not None and self.state == "copying" and prog.current)
                   else self.current)
        files_done = self.files_done
        if prog is not None and self.state == "copying":
            files_done = self.files_done + int(prog.done)
        return {
            "runId": self.run_id, "dest": self.dest.id, "label": self.dest.label,
            "volumeKind": self.dest.volume_kind, "lane": self.dest.lane,
            "state": self.state, "message": self.message, "stage": self.stage,
            "phase": phase, "copier": (prog.copier if prog is not None and self.state == "copying"
                                       else self.copier),
            "current": current, "percent": round(pct, 1),
            "bytesDone": int(done), "bytesTotal": int(total),
            "filesDone": int(files_done), "filesTotal": int(self.files_total),
            "bps": max(0, bps), "etaS": eta, "counts": dict(self.counts), "problems": list(self.problems),
            "recorded": self.recorded,
            "elapsedS": int((self.finished or time.monotonic()) - self.started) if self.started else 0,
        }


class FieldRun:
    def __init__(self, run_id: str, card: dict[str, Any], folder: str, lanes: list[Lane]) -> None:
        self.id = run_id
        self.card = card
        self.folder = folder
        self.lanes = lanes
        self.cancelled = threading.Event()
        self.started = time.time()
        self.finished: Optional[float] = None
        self.threads: list[threading.Thread] = []

    @property
    def running(self) -> bool:
        return any(l.state not in TERMINAL for l in self.lanes)

    def snapshot(self) -> dict[str, Any]:
        now = time.monotonic()
        return {"id": self.id, "card": {k: self.card.get(k) for k in ("serial", "label", "kind")},
                "folder": self.folder, "running": self.running, "cancelled": self.cancelled.is_set(),
                "startedAt": self.started, "finishedAt": self.finished,
                "lanes": [l.snapshot(now) for l in self.lanes]}


@dataclass
class Services:
    """Everything a lane needs from outside, so the suite supplies fakes."""
    cfg: dict[str, Any]
    view: field_mode.LedgerView
    volumes_fn: Callable[..., list[dict[str, Any]]] = sorter_cards.list_volumes
    teracopy_fn: Optional[Callable[[], tuple[Optional[teracopy_mod.TeraCopy], str]]] = None
    record_fn: Callable[[Destination, list[dict[str, Any]]], int] = lambda d, c: 0
    on_lane_done: Callable[[Lane], None] = lambda lane: None
    on_run_done: Callable[[FieldRun], None] = lambda run: None
    free_fn: Callable[[str], int] = lambda p: int(shutil.disk_usage(p).free)
    alive_fn: Callable[[str], bool] = lambda p: os.path.isdir(p)
    clock: Callable[[], float] = time.monotonic


class FieldCopier:
    """Starts runs and keeps them. One run per card at a time."""

    def __init__(self, services: Services) -> None:
        self.s = services
        self._lock = threading.RLock()
        self.runs: dict[str, FieldRun] = {}
        self._seq = 0

    # -- starting ---------------------------------------------------------------------------------
    def active_for(self, serial: str) -> Optional[FieldRun]:
        with self._lock:
            for r in self.runs.values():
                if r.running and str(r.card.get("serial", "")).upper() == str(serial).upper():
                    return r
        return None

    def busy_dest_ids(self) -> set[str]:
        with self._lock:
            return {l.dest.id for r in self.runs.values() if r.running for l in r.lanes
                    if l.state not in TERMINAL}

    def start(self, card: dict[str, Any], dests: list[Destination], folder: str) -> FieldRun:
        """Start one lane per physical drive. `card` = {serial, label, kind, root, files}. Raises
        ValueError (a sentence) for what cannot start at all."""
        if not dests:
            raise ValueError("tick at least one destination")
        with self._lock:
            if self.active_for(card["serial"]):
                raise ValueError("this card is already being copied: wait for it to finish, or stop it")
            taken = self.busy_dest_ids()
            clash = [d.label for d in dests if d.id in taken]
            if clash:
                raise ValueError(f"{', '.join(clash)} is busy with another copy")
            self._seq += 1
            run_id = f"{int(time.time())}-{self._seq}"
            lanes = [Lane(run_id, d) for d in dests]
            run = FieldRun(run_id, {k: card.get(k) for k in ("serial", "label", "kind", "root")}, folder, lanes)
            self.runs[run_id] = run
            for old in sorted(self.runs)[:-12]:
                if not self.runs[old].running:
                    self.runs.pop(old, None)
        thread = threading.Thread(target=self._drive, args=(run, card, dests), daemon=True,
                                  name=f"ccsync-field-{run_id}")
        run.threads.append(thread)
        thread.start()
        return run

    def cancel(self, run_id: str) -> bool:
        with self._lock:
            run = self.runs.get(run_id)
        if run is None:
            return False
        run.cancelled.set()
        return True

    def get(self, run_id: str) -> Optional[FieldRun]:
        with self._lock:
            return self.runs.get(run_id)

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            runs = sorted(self.runs.values(), key=lambda r: r.started, reverse=True)
        return [r.snapshot() for r in runs]

    def wait(self, run: FieldRun, timeout: float = 30.0) -> bool:
        """Test seam: block until the run's lanes are all finished."""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if not run.running and run.finished is not None:
                return True
            time.sleep(0.02)
        return False

    # -- the run ----------------------------------------------------------------------------------
    def _drive(self, run: FieldRun, card: dict[str, Any], dests: list[Destination]) -> None:
        by_lane = group_by_lane(dests)
        lane_of = {l.dest.id: l for l in run.lanes}
        try:
            with ExitStack() as stack:
                stack.enter_context(sorter_cards.ingest_busy(card["serial"], card.get("root") or ""))
                workers = []
                for key, members in by_lane.items():
                    t = threading.Thread(target=self._lane_group,
                                         args=(run, card, [lane_of[m.id] for m in members]),
                                         daemon=True, name=f"ccsync-field-lane-{key}")
                    workers.append(t)
                    t.start()
                for t in workers:
                    t.join()
        except Exception:                                         # noqa: BLE001
            log.exception("field: the run %s failed", run.id)
            for l in run.lanes:
                if l.state not in TERMINAL:
                    l.state, l.message = "failed", "The copy could not run (see the companion log)."
        finally:
            run.finished = time.time()
            try:
                self.s.on_run_done(run)
            except Exception:                                     # noqa: BLE001
                log.exception("field: the run-done hook failed")

    def _lane_group(self, run: FieldRun, card: dict[str, Any], lanes: list[Lane]) -> None:
        for i, lane in enumerate(lanes):
            if i:
                lane.stage = "waiting for the other copy on this physical drive"
            try:
                self._run_lane(run, card, lane)
            except Exception as exc:                              # noqa: BLE001
                log.exception("field: lane %s failed", lane.dest.id)
                lane.state, lane.message = "failed", f"The copy could not run: {exc}"
            finally:
                lane.finished = time.monotonic()
                try:
                    self.s.on_lane_done(lane)
                except Exception:                                 # noqa: BLE001
                    log.exception("field: the lane-done hook failed")

    # -- one lane -------------------------------------------------------------------------------
    def _stopper(self, run: FieldRun, dest: Destination) -> Callable[[], str]:
        """The copier's should_stop: cancelled, the drive gone, or the drive full. The drive checks
        run every ALIVE_SECONDS, not per buffer."""
        state = {"at": 0.0, "reason": ""}

        def stop() -> str:
            if state["reason"]:
                return state["reason"]
            if run.cancelled.is_set():
                state["reason"] = "stopped by you"
                return state["reason"]
            now = self.s.clock()
            if now - state["at"] < ALIVE_SECONDS:
                return ""
            state["at"] = now
            try:
                if not self.s.alive_fn(dest.root):
                    state["reason"] = f"{dest.label} was taken out (or went away) during the copy"
                elif self.s.free_fn(dest.root) < FULL_BYTES:
                    state["reason"] = f"{dest.label} is full"
            except OSError:
                state["reason"] = f"{dest.label} was taken out (or went away) during the copy"
            return state["reason"]

        return stop

    def _run_lane(self, run: FieldRun, card: dict[str, Any], lane: Lane) -> None:
        dest = lane.dest
        lane.started = time.monotonic()
        if run.cancelled.is_set():
            lane.state, lane.message = "stopped", "Stopped before it started."
            return
        lane.state, lane.stage = "planning", "looking at what is already there"
        if not self.s.alive_fn(dest.root):
            lane.state, lane.message = "refused", f"{dest.label} is not there. Plug it in and try again."
            return
        card_root = Path(card["root"])
        files = [list(f) for f in card.get("files") or []]
        plan = plan_destination(files, dest, run.folder, self.s.view)
        lane.files_total = len(plan.items)
        need = plan.copy_bytes
        try:
            free = int(self.s.free_fn(dest.root))
        except OSError:
            lane.state, lane.message = "refused", f"{dest.label} cannot be read. Is it still plugged in?"
            return
        if need + MARGIN_BYTES > free:
            lane.state = "refused"
            lane.message = (f"Not enough room on {dest.label}: {fmt_bytes(free)} free, and this card needs "
                            f"{fmt_bytes(need)} more (plus {fmt_bytes(MARGIN_BYTES)} kept spare). "
                            f"Nothing was copied there.")
            return
        stopper = self._stopper(run, dest)
        recorded: list[dict[str, Any]] = []

        # 1. what is already there: a quick verify against the card
        present = plan.of("there", "elsewhere")
        lane._vf_bytes_total = sum(min(i.size, 2 * field_mode.MIB) for i in present)
        lane._copy_bytes_total = need
        if present:
            lane.state, lane.phase, lane.stage = "checking", "verify", f"checking {len(present)} files already there"
            for item in present:
                reason = stopper()
                if reason:
                    self._finish_stopped(lane, reason, recorded, dest)
                    return
                lane.current = item.rel
                target = item.found or item.dst
                res = field_mode.quick_compare(card_root.joinpath(*item.rel.split("/")), target)
                lane._vf_bytes_done += min(item.size, 2 * field_mode.MIB)
                lane.files_done += 1
                if res.get("ok"):
                    lane.counts["there"] += 1
                    recorded.append(self._entry(dest, target, item, "quick"))
                    if res.get("warning"):
                        lane.problem(item.rel, res["warning"])
                else:
                    if res.get("unreadable") and not os.path.isdir(card_root):
                        self._finish_stopped(lane, "the card was taken out of its reader", recorded, dest)
                        return
                    lane.counts["conflicts"] += 1
                    lane.problem(item.rel, f"it is already at the destination but does not match the "
                                           f"card: {res.get('error')}. It was left alone.")

        # 2. the rest: the sorter's copier
        todo = plan.of("copy", "resume")
        if todo:
            lane.state, lane.phase, lane.stage = "copying", "copy", f"copying {len(todo)} files"
            self._copy_stage(run, card, lane, todo, stopper, recorded)

        # 3. record what is proven, then say how it went
        self._record(lane, recorded)
        if lane.state in ("stopped", "failed"):
            return
        c = lane.counts
        bad = c["conflicts"] + c["failed"] + c["unverified"]
        lane.state = "attention" if bad else "done"
        bits = []
        if c["copied"]:
            bits.append(f"{c['copied']} copied and verified")
        if c["skipped"]:
            bits.append(f"{c['skipped']} already identical")
        if c["there"]:
            bits.append(f"{c['there']} already there, quick-checked")
        if c["conflicts"]:
            bits.append(f"{c['conflicts']} left alone (something different is there)")
        if c["failed"]:
            bits.append(f"{c['failed']} failed")
        if c["unverified"]:
            bits.append(f"{c['unverified']} copied but not verified")
        lane.message = ", ".join(bits) + "." if bits else "Nothing to copy."
        lane.stage = ""

    def _copy_stage(self, run: FieldRun, card: dict[str, Any], lane: Lane, todo: list[PlanItem],
                    stopper: Callable[[], str], recorded: list[dict[str, Any]]) -> None:
        dest = lane.dest
        lane_cfg = {**self.s.cfg, "jobs_pool_root": dest.root}
        by_rel = {i.rel: i for i in todo}
        root_prefix = "/".join(p for p in (dest.subdir.replace("\\", "/"), run.folder) if p)
        copies = []
        for item in todo:
            copies.append({"src": {"root": f"card:{card['serial']}", "rel": item.rel},
                           "dst": {"root": POOL_ROOT, "rel": f"{root_prefix}/{item.rel}"},
                           "size": item.size, "mode": item.action})
        # the folders first (the copier makes them; a drive that will not take a folder says so now)
        parents = dict.fromkeys(c["dst"]["rel"].rsplit("/", 1)[0] for c in copies)
        folders = [{"root": POOL_ROOT, "rel": p} for p in parents]
        job = card_copy.CardJob(lane_cfg, should_stop=stopper, volumes_fn=self.s.volumes_fn,
                                teracopy_fn=self.s.teracopy_fn)
        job._ingest_serial = str(card["serial"])        # a pulled card stops the lane, not every file
        job.progress.of, job.progress.total_bytes = len(copies), sum(c["size"] for c in copies)
        lane.progress = job.progress
        try:
            result = job.run(card_copy.KIND_DRIVE_COPY, {"copies": copies, "folders": folders,
                                                         "src_root": f"card:{card['serial']}"})
        except card_copy.CardJobError as exc:
            lane.state = "failed"
            lane.message = str(exc)
            return
        lane.copier = str(result.get("copier") or "python")
        lane.files_done += int(job.progress.done)
        lane._copy_done_final = int(job.progress.bytes)
        lane.progress = None

        def rel_of(wire: dict[str, Any]) -> str:
            src = (wire or {}).get("src")
            return str(src.get("rel") if isinstance(src, dict) else src or "")

        full_markers = False
        for item in result.get("copied") or []:
            rel = rel_of(item)
            planned = by_rel.get(rel)
            if planned is None:
                continue
            target = planned.dst.with_name(str(item.get("filename") or planned.dst.name))
            if item.get("verified"):
                lane.counts["copied"] += 1
                recorded.append(self._entry(dest, target, planned, "full"))
                continue
            res = field_mode.quick_compare(Path(card["root"]).joinpath(*rel.split("/")), target)
            if res.get("ok"):
                lane.counts["copied"] += 1
                recorded.append(self._entry(dest, target, planned, "quick"))
            else:
                lane.counts["unverified"] += 1
                lane.problem(rel, f"copied but not verified: {res.get('error')}")
        for item in result.get("skipped") or []:
            planned = by_rel.get(rel_of(item))
            if planned is None:
                continue
            lane.counts["skipped"] += 1
            target = planned.dst.with_name(str(item.get("filename") or planned.dst.name))
            recorded.append(self._entry(dest, target, planned, "full"))
        for item in result.get("conflicts") or []:
            lane.counts["conflicts"] += 1
            lane.problem(rel_of(item), str(item.get("why") or "something different is already there")
                         + " It was not overwritten.")
        for item in result.get("failed") or []:
            lane.counts["failed"] += 1
            why = str(item.get("why") or "the copy failed")
            full_markers = full_markers or looks_full(why)
            lane.problem(rel_of(item), why)
        if job.stopped:
            lane.state = "stopped" if run.cancelled.is_set() else "failed"
            lane.message = self._stopped_message(lane, job.stopped)
        elif full_markers:
            lane.state = "failed"
            lane.message = (f"{dest.label} ran out of room. {lane.counts['copied']} files are on it whole and "
                            f"verified; the rest were not copied. Free some space or pick another drive.")

    @staticmethod
    def _stopped_message(lane: Lane, reason: str) -> str:
        landed = lane.counts["copied"] + lane.counts["skipped"] + lane.counts["there"]
        return (f"Stopped: {reason}. {landed} files are on {lane.dest.label} whole and verified "
                f"(they are kept and recorded); the rest were not copied. A half-written file is never "
                f"left under its real name by the built-in copier; TeraCopy may leave a short one, which "
                f"the next run finishes.")

    def _finish_stopped(self, lane: Lane, reason: str, recorded: list[dict[str, Any]], dest: Destination) -> None:
        lane.state = "failed" if not reason.startswith("stopped by you") else "stopped"
        lane.message = self._stopped_message(lane, reason)
        self._record(lane, recorded)

    # -- recording --------------------------------------------------------------------------------
    def _entry(self, dest: Destination, target: Path, item: PlanItem, level: str) -> dict[str, Any]:
        try:
            mtime = int(round(os.stat(target).st_mtime * 1000))
        except OSError:
            mtime = None if item.mtime is None else int(round(float(item.mtime)))
        return {"path": dest.rel_of(target), "name": target.name, "size": item.size, "mtime": mtime,
                "verified": level, "rel": item.rel}

    def _record(self, lane: Lane, entries: list[dict[str, Any]]) -> None:
        keep = [e for e in entries if field_mode.is_recordable(e["rel"])]
        if not keep or not lane.dest.volume_id:
            return
        try:
            lane.recorded += int(self.s.record_fn(lane.dest, keep) or 0)
        except Exception:                                         # noqa: BLE001
            log.exception("field: could not record the copies of %s", lane.dest.label)
