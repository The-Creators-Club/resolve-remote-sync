"""Lane A (video originals, editor -> NAS) and Lane B (proxies, NAS -> editor).

Both lanes wrap the same rclone-subprocess machinery (SPEC.md: "sync/rclone_
lane.py — wraps an rclone subprocess"); only the filter rules, rclone
subcommand (copy vs sync), direction, and trigger (watchdog+periodic vs
periodic-only) differ, so one module + one class parameterized by
`direction` covers both.

Filter-rule correctness (especially Lane B's nested-Proxy-dir selection) was
verified against a real rclone binary with --dry-run against local fixture
dirs before writing this — see tests/test_rclone_filters.py, which re-proves
it in CI. rclone's directory-filter semantics are subtle: a bare "- **" at
the end of a filter list does NOT, by itself, stop rclone from *listing*
directories to look for matches inside them, but an explicit "+ **/Proxy/"
directory-allow rule is still included below for clarity and for parity
with `rclone check`/`ncdu`-style tools that do prune eagerly.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from .base import (
    STATE_ERROR,
    STATE_IDLE,
    STATE_SYNCING,
    LaneAdapter,
    LaneStatus,
)

log = logging.getLogger("ccsync.sync.rclone")

VIDEO_EXTS = [
    ".braw", ".mov", ".mp4", ".mxf", ".avi", ".mts", ".m2ts", ".mkv",
    ".r3d", ".crm", ".mpg", ".mpeg", ".wmv", ".webm", ".insv", ".360",
]

DIRECTION_UP = "up"
DIRECTION_DOWN = "down"


def build_filter_rules_up() -> list[str]:
    """Lane A: video files anywhere EXCEPT under a Proxy/ dir, nothing else.

    Both the nested (`**/Proxy/**`) and root-level (`/Proxy/**`) forms are
    needed: rclone's `**/` requires at least one leading path component, so
    a Proxy/ dir at the tree root would slip past the nested rule alone.
    """
    rules = ["- **/Proxy/**", "- /Proxy/**"]
    rules += [f"+ *{ext}" for ext in VIDEO_EXTS]
    rules.append("- **")
    return rules


def build_filter_rules_down() -> list[str]:
    """Lane B: only the contents of Proxy/ dirs, at any depth (root included)."""
    return [
        "+ /Proxy/",
        "+ /Proxy/**",
        "+ **/Proxy/",
        "+ **/Proxy/**",
        "- **",
    ]


def write_filter_file(rules: list[str], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(rules) + "\n", encoding="utf-8")
    return path


def rclone_available(rclone_path: str) -> tuple[bool, str]:
    """Check whether `rclone_path` resolves to a runnable rclone binary.

    Returns (available, message). Never raises.
    """
    resolved = rclone_path
    if not os.path.isabs(rclone_path):
        found = shutil.which(rclone_path)
        if found is None:
            return False, f"rclone not found on PATH ('{rclone_path}')"
        resolved = found
    elif not os.path.exists(resolved):
        return False, f"rclone not found at '{resolved}'"

    try:
        proc = subprocess.run(
            [resolved, "version"], capture_output=True, timeout=10, text=True
        )
    except Exception as exc:
        return False, f"rclone at '{resolved}' failed to run: {exc}"
    if proc.returncode != 0:
        return False, f"rclone at '{resolved}' exited {proc.returncode}"
    return True, resolved


def _join_remote_path(remote_root: str, subpath: str) -> str:
    """Join a remote root and a posix-style subpath with exactly one '/'
    between them, regardless of leading/trailing slashes on either side."""
    root = remote_root.rstrip("/")
    sub = subpath.strip("/")
    if not root:
        return sub
    if not sub:
        return root
    return f"{root}/{sub}"


def _run_lsf(cmd: list[str], timeout: float) -> Optional[str]:
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        log.warning(
            "rclone lsf exited %d: %s", proc.returncode, (proc.stderr or "").strip()[:300]
        )
        return None
    return proc.stdout


def clone_directory_tree(
    rclone_path: str,
    remote: str,
    remote_root: str,
    local_root: str,
    subpath: str,
    run_fn: Optional[Callable[[list[str], float], Optional[str]]] = None,
    timeout: float = 300.0,
) -> Optional[int]:
    """Replicate the NAS-side DIRECTORY STRUCTURE of `subpath` under
    local_root -- every directory, including empty ones.

    Exists because nothing else carries empty dirs to an editor: lane B's
    filters copy proxy FILES only (rclone never creates a directory no
    matching file lives in), and lane C's editor-side .stignore drops video
    files and Proxy dirs -- so a project's empty scaffolding (folders the
    team laid out but hasn't filled yet) never appears on an editor's
    machine. One `rclone lsf --dirs-only -R` listing + local mkdirs;
    deliberately NOT an rclone sync with --create-empty-src-dirs, whose
    interaction with filter rules is subtle (see module docstring).

    Returns the number of directories newly created, or None when the
    listing failed (misconfigured remote, network down). Never raises.
    """
    if not remote or not remote_root:
        return None
    remote_side = f"{remote}:{_join_remote_path(remote_root, subpath)}"
    cmd = [rclone_path, "lsf", "--dirs-only", "-R", remote_side]
    runner = run_fn or _run_lsf
    try:
        output = runner(cmd, timeout)
    except Exception as exc:
        log.warning("structure clone: rclone lsf failed for %s: %s", remote_side, exc)
        return None
    if output is None:
        return None

    base = Path(local_root) / subpath
    created = 0
    try:
        if not base.is_dir():
            base.mkdir(parents=True, exist_ok=True)
            created += 1
    except OSError as exc:
        log.warning("structure clone: could not create %s: %s", base, exc)
        return None
    for line in output.splitlines():
        rel = line.strip().strip("/")
        # lsf never emits absolute or parent-relative entries, but a mkdir
        # escaping local_root would be bad enough to guard anyway.
        if not rel or ".." in Path(rel).parts or Path(rel).is_absolute():
            continue
        target = base / rel
        try:
            if not target.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                created += 1
        except OSError as exc:
            log.warning("structure clone: could not create %s: %s", target, exc)
    return created


def _append_stats_flags(cmd: list[str], stats_interval: Optional[str]) -> list[str]:
    if stats_interval:
        cmd += ["--stats", stats_interval, "--stats-log-level", "NOTICE"]
    return cmd


def build_up_command(
    rclone_path: str,
    local_root: str,
    remote: str,
    remote_root: str,
    filter_file: Path,
    transfers: int = 4,
    subpath: str | None = None,
    stats_interval: str | None = None,
) -> list[str]:
    local_side = str(Path(local_root) / subpath) if subpath else str(local_root)
    remote_side = (
        f"{remote}:{_join_remote_path(remote_root, subpath)}" if subpath else f"{remote}:{remote_root}"
    )
    cmd = [
        rclone_path,
        "copy",
        local_side,
        remote_side,
        "--filter-from", str(filter_file),
        "--ignore-existing",
        "--min-age", "30s",
        "--transfers", str(transfers),
        "--use-json-log",
        "--verbose",  # INFO-level per-file log lines — parse_json_log() needs these
    ]
    return _append_stats_flags(cmd, stats_interval)


def build_down_command(
    rclone_path: str,
    local_root: str,
    remote: str,
    remote_root: str,
    filter_file: Path,
    transfers: int = 4,
    subpath: str | None = None,
    stats_interval: str | None = None,
) -> list[str]:
    local_side = str(Path(local_root) / subpath) if subpath else str(local_root)
    remote_side = (
        f"{remote}:{_join_remote_path(remote_root, subpath)}" if subpath else f"{remote}:{remote_root}"
    )
    cmd = [
        rclone_path,
        "sync",
        remote_side,
        local_side,
        "--filter-from", str(filter_file),
        "--transfers", str(transfers),
        "--use-json-log",
        "--verbose",  # INFO-level per-file log lines — parse_json_log() needs these
    ]
    return _append_stats_flags(cmd, stats_interval)


@dataclass
class RcloneRunResult:
    ok: bool
    transferred: int
    errors: list[str]
    raw_returncode: int


def parse_json_log(text: str) -> RcloneRunResult:
    """Parse rclone --use-json-log stderr output into a summary.

    Tolerant of non-JSON lines (rclone occasionally emits plain text for
    config-file notices etc.) — those are skipped rather than raising.
    """
    transferred = 0
    errors: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        level = record.get("level", "")
        msg = record.get("msg", "")
        if level == "error":
            errors.append(msg)
        elif "Copied" in msg or "Moved" in msg or "Deleted" in msg:
            # Per-file records ("clip.mov: Copied (new)") only — the run-
            # summary stats line ("Transferred: 0 B / ...") must not count
            # as a file, which is why "Transferred" is NOT matched here.
            transferred += 1
    return RcloneRunResult(ok=not errors, transferred=transferred, errors=errors, raw_returncode=0)


def _project_rel_for_path(
    local_root: str, path: str, known_rels: Optional[list[str]] = None
) -> Optional[str]:
    """Given an absolute file path under local_root, return the
    "Projects/<rel>" subtree it belongs to.

    With `known_rels` (posix rels like "2026/CCT/Creator Profiles/Season 1",
    from the sequencer's selection), the LONGEST rel whose segments prefix
    the path wins -- projects live at any depth since 2026-07-25, so fixed
    slicing can't work. Without knowns (legacy whole-tree mode) the original
    year/series/project heuristic (first 3 components) is kept."""
    try:
        rel = Path(path).relative_to(Path(local_root))
    except ValueError:
        return None
    parts = rel.parts
    if len(parts) < 2 or parts[0] != "Projects":
        return None
    inner = [p.lower() for p in parts[1:]]

    if known_rels:
        best: Optional[str] = None
        best_len = 0
        for known in known_rels:
            segs = [s.lower() for s in known.strip("/").split("/") if s]
            if len(segs) < len(inner) and inner[: len(segs)] == segs and len(segs) > best_len:
                best, best_len = known, len(segs)
        return f"Projects/{best}" if best else None

    if len(parts) < 4:
        return None
    return "/".join(parts[:4])


class RcloneLane(LaneAdapter):
    """One rclone-backed lane. direction="up" -> Lane A, direction="down" -> Lane B."""

    def __init__(
        self,
        direction: str,
        local_root: str,
        remote: str,
        remote_root: str,
        rclone_path: str = "rclone",
        transfers: int = 4,
        scan_interval: float = 300.0,
        watch_debounce_seconds: float = 10.0,
        state_dir: Optional[Path] = None,
        subprocess_run=subprocess.run,
        popen_factory=None,
        on_change: Optional[Callable[[str], None]] = None,
        known_rels_fn: Optional[Callable[[], list[str]]] = None,
    ) -> None:
        assert direction in (DIRECTION_UP, DIRECTION_DOWN)
        self.direction = direction
        self.name = "lane_a_video_up" if direction == DIRECTION_UP else "lane_b_proxy_down"
        self.local_root = local_root
        self.remote = remote
        self.remote_root = remote_root
        self.rclone_path = rclone_path
        self.transfers = transfers
        self.scan_interval = scan_interval
        self.watch_debounce_seconds = watch_debounce_seconds
        self.subprocess_run = subprocess_run
        self.popen_factory = popen_factory
        self.on_change = on_change
        # Selected-project rels (any depth) for the watchdog's project
        # attribution -- see _project_rel_for_path. None = legacy heuristic.
        self.known_rels_fn = known_rels_fn

        # Backward-compat seam: a caller that injects a custom subprocess_run
        # (and no popen_factory) keeps the old subprocess.run() code path —
        # this is only true when subprocess_run was actually overridden, not
        # left at its subprocess.run default, which always uses the newer
        # Popen-based runner (needed for live --stats parsing).
        self._legacy_run = popen_factory is None and subprocess_run is not subprocess.run

        self._state_dir = state_dir or (Path.home() / ".ccsync" / "state")
        self._filter_file = self._state_dir / f"filter_{direction}.txt"

        self._stop_event = threading.Event()
        self._periodic_thread: Optional[threading.Thread] = None
        self._observer = None  # watchdog Observer, lane A only
        self._debounce_timer: Optional[threading.Timer] = None
        self._lock = threading.Lock()
        # Serializes rclone runs: the periodic loop and a debounced watchdog
        # fire must never run two rclone processes on the same lane at once.
        self._run_lock = threading.Lock()
        self._status = LaneStatus(name=self.name)

    # -- filter file -------------------------------------------------
    def _ensure_filter_file(self) -> Path:
        rules = build_filter_rules_up() if self.direction == DIRECTION_UP else build_filter_rules_down()
        return write_filter_file(rules, self._filter_file)

    def _build_command(
        self, subpath: Optional[str] = None, stats_interval: Optional[str] = None
    ) -> list[str]:
        filter_file = self._ensure_filter_file()
        if self.direction == DIRECTION_UP:
            return build_up_command(
                self.rclone_path, self.local_root, self.remote, self.remote_root,
                filter_file, self.transfers, subpath=subpath, stats_interval=stats_interval,
            )
        return build_down_command(
            self.rclone_path, self.local_root, self.remote, self.remote_root,
            filter_file, self.transfers, subpath=subpath, stats_interval=stats_interval,
        )

    # -- LaneAdapter ---------------------------------------------------
    def start(self) -> None:
        available, msg = rclone_available(self.rclone_path)
        if not available:
            with self._lock:
                self._status.state = STATE_ERROR
                self._status.last_error = msg
            log.error("%s: %s", self.name, msg)
            return

        self._stop_event.clear()
        self._periodic_thread = threading.Thread(
            target=self._periodic_loop, name=f"ccsync-{self.name}-periodic", daemon=True
        )
        self._periodic_thread.start()

        if self.direction == DIRECTION_UP:
            self._start_watchdog()

    def start_watchdog_only(self) -> None:
        """Start just the filesystem watcher, no periodic loop. Managed mode
        (sequencer-driven) uses this so file events still reach on_change
        while run_once() stays externally driven."""
        if self.direction != DIRECTION_UP or self._observer is not None:
            return
        self._stop_event.clear()
        self._start_watchdog()

    def stop(self) -> None:
        self._stop_event.set()
        if self._debounce_timer is not None:
            self._debounce_timer.cancel()
        if self._observer is not None:
            try:
                self._observer.stop()
                self._observer.join(timeout=5)
            except Exception:
                pass
            self._observer = None

    def status(self) -> LaneStatus:
        with self._lock:
            return LaneStatus(**vars(self._status))

    def run_once(self, subpath: Optional[str] = None) -> LaneStatus:
        with self._run_lock:
            return self._run_once_locked(subpath)

    def _run_once_locked(self, subpath: Optional[str] = None) -> LaneStatus:
        available, msg = rclone_available(self.rclone_path)
        if not available:
            with self._lock:
                self._status.state = STATE_ERROR
                self._status.last_error = msg
            return self.status()

        if self.direction == DIRECTION_UP and subpath:
            # Lane A pushes local -> NAS; if the project folder hasn't been
            # created locally yet (e.g. not accepted/mapped yet), there is
            # nothing to run — and rclone would just error on a missing
            # source dir, which we don't want treated as a real failure.
            project_dir = Path(self.local_root) / subpath
            if not project_dir.exists():
                with self._lock:
                    self._status.state = STATE_IDLE
                    self._status.detail = f"project dir not yet local: {subpath}"
                return self.status()

        with self._lock:
            self._status.state = STATE_SYNCING
            self._status.transferring = 1
            self._status.current_project = subpath
            self._status.bytes_done = None
            self._status.bytes_total = None
            self._status.speed_bps = None
            self._status.eta_seconds = None
            self._status.transfers = []

        if self._legacy_run:
            cmd = self._build_command(subpath=subpath, stats_interval=None)
            try:
                proc = self.subprocess_run(cmd, capture_output=True, text=True, timeout=None)
            except Exception as exc:
                with self._lock:
                    self._status.state = STATE_ERROR
                    self._status.last_error = str(exc)
                    self._status.transferring = 0
                return self.status()
            returncode = proc.returncode
            stderr_text = proc.stderr or ""
        else:
            cmd = self._build_command(subpath=subpath, stats_interval="10s")
            try:
                returncode, stderr_text = self._run_popen(cmd)
            except Exception as exc:
                with self._lock:
                    self._status.state = STATE_ERROR
                    self._status.last_error = str(exc)
                    self._status.transferring = 0
                    self._status.speed_bps = None
                    self._status.eta_seconds = None
                    self._status.transfers = []
                return self.status()

        result = parse_json_log(stderr_text)
        with self._lock:
            self._status.transferring = 0
            self._status.queued = 0
            # No longer transferring — bytes_done/bytes_total keep their
            # final values, but speed/eta/per-file transfers stop making
            # sense once idle.
            self._status.speed_bps = None
            self._status.eta_seconds = None
            self._status.transfers = []
            # Exit code is authoritative: rclone logs transient per-attempt
            # failures at error level ("Attempt 1/3 failed ...") even when a
            # retry succeeds and the run as a whole is fine.
            if returncode != 0:
                self._status.state = STATE_ERROR
                tail = result.errors[-1] if result.errors else stderr_text.strip()[-300:]
                self._status.last_error = tail or f"rclone exited {returncode}"
            else:
                if result.errors:
                    log.info("%s: %d transient error line(s), run succeeded (last: %s)",
                             self.name, len(result.errors), result.errors[-1])
                self._status.state = STATE_IDLE
                self._status.last_error = None
                self._status.last_sync = datetime.now(timezone.utc)
                self._status.detail = f"transferred {result.transferred} file(s)"
        return self.status()

    # -- Popen-based runner with live --stats JSON parsing ---------------
    def _run_popen(self, cmd: list[str]) -> tuple[int, str]:
        factory = self.popen_factory or subprocess.Popen
        proc = factory(cmd, stderr=subprocess.PIPE, text=True)
        lines: list[str] = []

        def _reader() -> None:
            for line in proc.stderr:
                lines.append(line)
                self._handle_stderr_line(line)

        reader_thread = threading.Thread(
            target=_reader, name=f"ccsync-{self.name}-stderr-reader", daemon=True
        )
        reader_thread.start()
        returncode = proc.wait()
        reader_thread.join()
        return returncode, "".join(lines)

    def _handle_stderr_line(self, line: str) -> None:
        line = line.strip()
        if not line or not line.startswith("{"):
            return
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            return
        stats = record.get("stats")
        if not isinstance(stats, dict):
            return
        with self._lock:
            self._status.bytes_done = stats.get("bytes")
            self._status.bytes_total = stats.get("totalBytes")
            self._status.speed_bps = stats.get("speed")
            self._status.eta_seconds = stats.get("eta")
            self._status.transfers = self._normalize_transferring(stats.get("transferring"))

    def _normalize_transferring(self, transferring: Optional[list]) -> list[dict]:
        """Normalize rclone --stats JSON's "transferring" array (per-file, live
        mid-transfer only -- absent/empty between files or once idle) into the
        dashboard's "transfers" shape. Direction is fixed per-lane."""
        direction = DIRECTION_UP if self.direction == DIRECTION_UP else DIRECTION_DOWN
        if not transferring:
            return []
        result: list[dict] = []
        for entry in transferring:
            if not isinstance(entry, dict):
                continue
            result.append(
                {
                    "name": entry.get("name"),
                    "direction": direction,
                    "bytes_done": entry.get("bytes"),
                    "bytes_total": entry.get("size"),
                    "percentage": entry.get("percentage"),
                    "speed_bps": entry.get("speed"),
                    "eta_seconds": entry.get("eta"),
                }
            )
        return result

    # -- periodic pass ---------------------------------------------------
    def _periodic_loop(self) -> None:
        # Run once immediately on start, then every scan_interval.
        while not self._stop_event.is_set():
            try:
                self.run_once()
            except Exception:
                log.exception("%s: periodic pass failed", self.name)
            if self._stop_event.wait(self.scan_interval):
                break

    # -- watchdog (lane A only) -------------------------------------------
    def _start_watchdog(self) -> None:
        try:
            from watchdog.events import FileSystemEventHandler
            from watchdog.observers import Observer
        except ImportError:
            log.warning(
                "%s: 'watchdog' not installed — falling back to periodic-only "
                "uploads every %ss", self.name, self.scan_interval,
            )
            return

        lane = self

        class _Handler(FileSystemEventHandler):
            def on_created(self, event):
                self._maybe_trigger(event)

            def on_modified(self, event):
                self._maybe_trigger(event)

            def on_moved(self, event):
                self._maybe_trigger(event)

            def _maybe_trigger(self, event) -> None:
                if event.is_directory:
                    return
                path = getattr(event, "dest_path", None) or event.src_path
                ext = os.path.splitext(path)[1].lower()
                if ext not in VIDEO_EXTS:
                    return
                if "proxy" in [p.lower() for p in Path(path).parts]:
                    return
                if lane.on_change is not None:
                    # Per-project mode: hand off to the (separately built)
                    # sequencer instead of running a debounced whole-tree
                    # pass. Known project rels (any depth) come from the
                    # sequencer's selection via known_rels_fn; a file not
                    # under any known project is ignored rather than falling
                    # back to the old whole-tree trigger.
                    knowns = None
                    if lane.known_rels_fn is not None:
                        try:
                            knowns = list(lane.known_rels_fn())
                        except Exception:
                            knowns = None
                    rel = _project_rel_for_path(lane.local_root, path, knowns)
                    if rel is not None:
                        lane.on_change(rel)
                    return
                lane._schedule_debounced_run()

        try:
            observer = Observer()
            observer.schedule(_Handler(), self.local_root, recursive=True)
            observer.start()
            self._observer = observer
        except Exception as exc:
            log.warning("%s: failed to start watchdog observer: %s", self.name, exc)

    def _schedule_debounced_run(self) -> None:
        with self._lock:
            if self._debounce_timer is not None:
                self._debounce_timer.cancel()
            self._debounce_timer = threading.Timer(self.watch_debounce_seconds, self._debounced_fire)
            self._debounce_timer.daemon = True
            self._debounce_timer.start()

    def _debounced_fire(self) -> None:
        try:
            self.run_once()
        except Exception:
            log.exception("%s: debounced run failed", self.name)
