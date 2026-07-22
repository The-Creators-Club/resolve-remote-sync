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
from typing import Optional

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


def build_up_command(
    rclone_path: str,
    local_root: str,
    remote: str,
    remote_root: str,
    filter_file: Path,
    transfers: int = 4,
) -> list[str]:
    return [
        rclone_path,
        "copy",
        str(local_root),
        f"{remote}:{remote_root}",
        "--filter-from", str(filter_file),
        "--ignore-existing",
        "--min-age", "30s",
        "--transfers", str(transfers),
        "--use-json-log",
        "--verbose",  # INFO-level per-file log lines — parse_json_log() needs these
    ]


def build_down_command(
    rclone_path: str,
    local_root: str,
    remote: str,
    remote_root: str,
    filter_file: Path,
    transfers: int = 4,
) -> list[str]:
    return [
        rclone_path,
        "sync",
        f"{remote}:{remote_root}",
        str(local_root),
        "--filter-from", str(filter_file),
        "--transfers", str(transfers),
        "--use-json-log",
        "--verbose",  # INFO-level per-file log lines — parse_json_log() needs these
    ]


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
        elif "Copied" in msg or "Transferred" in msg:
            transferred += 1
    return RcloneRunResult(ok=not errors, transferred=transferred, errors=errors, raw_returncode=0)


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

    def _build_command(self) -> list[str]:
        filter_file = self._ensure_filter_file()
        if self.direction == DIRECTION_UP:
            return build_up_command(
                self.rclone_path, self.local_root, self.remote, self.remote_root,
                filter_file, self.transfers,
            )
        return build_down_command(
            self.rclone_path, self.local_root, self.remote, self.remote_root,
            filter_file, self.transfers,
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

    def run_once(self) -> LaneStatus:
        with self._run_lock:
            return self._run_once_locked()

    def _run_once_locked(self) -> LaneStatus:
        available, msg = rclone_available(self.rclone_path)
        if not available:
            with self._lock:
                self._status.state = STATE_ERROR
                self._status.last_error = msg
            return self.status()

        with self._lock:
            self._status.state = STATE_SYNCING
            self._status.transferring = 1

        cmd = self._build_command()
        try:
            proc = self.subprocess_run(cmd, capture_output=True, text=True, timeout=None)
        except Exception as exc:
            with self._lock:
                self._status.state = STATE_ERROR
                self._status.last_error = str(exc)
                self._status.transferring = 0
            return self.status()

        result = parse_json_log(proc.stderr or "")
        with self._lock:
            self._status.transferring = 0
            self._status.queued = 0
            if proc.returncode != 0 or result.errors:
                self._status.state = STATE_ERROR
                tail = result.errors[-1] if result.errors else (proc.stderr or "").strip()[-300:]
                self._status.last_error = tail or f"rclone exited {proc.returncode}"
            else:
                self._status.state = STATE_IDLE
                self._status.last_error = None
                self._status.last_sync = datetime.now(timezone.utc)
                self._status.detail = f"transferred {result.transferred} file(s)"
        return self.status()

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
