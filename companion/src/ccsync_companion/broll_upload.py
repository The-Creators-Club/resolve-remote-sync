"""Upload of ONE indexed b-roll clip's artifacts to the NAS -- the mirror
image of `broll_fetch.py`, which pulls one clip DOWN.

Why a sibling and not a mode of that module: the two answer different
questions. A fetch is a click an editor is waiting on -- two at a time, no
queue, terminal states popped on read, because the browser's own 1.5 s poll IS
the retry. An ingest upload is unattended background work with an ORDER that
matters and a pause an editor (or a fleet halt) can hold for hours. Sharing
one registry would mean either a queue nobody clicking wanted or no queue for
the work that needs one. What they DO share is the rclone command shape, the
`--stats` JSON progress parsing and the prerequisite check -- imported here,
not re-derived, so a knob an operator sets in config.toml (sftp_chunk_size and
the rest) applies to both.

Ordering is the whole design (docs/BROLL_INGEST_PLAN.md §1 step 7): the
poster and the sprite go first because they are ~100 KB each and the clip
becomes VISIBLE in the search UI the moment the server can stat them; the
540p proxy next, so it is playable; the camera ORIGINAL last, because it is
tens of gigabytes and nothing downstream is blocked on it -- an editor whose
drive is unplugged before it goes up still gets a searchable, playable clip
(the item's `original_uploaded` stays 0 and the page offers a retry).

The server verifies every upload by stat'ing the file under BROLL_DATA_ROOT
before it flips a row live. This module's own `rclone lsjson` check is the
cheaper half of that: it catches "rclone exited 0 and the file is not there"
(a moved mount, a full disk on the far side) without a round trip to the
dashboard, and it is the difference between retrying one file and marking a
whole clip failed.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
from pathlib import Path
from typing import Any, Callable, Optional

from . import broll_fetch
from .sync import rclone_lane

log = logging.getLogger("ccsync.brollup")

# The NAS-side folder, shared with the download half (broll_fetch pins the
# local/remote pair together; this is the same string on purpose).
ARCHIVE_REMOTE_REL = broll_fetch.ARCHIVE_REMOTE_REL

STATE_QUEUED = "queued"
STATE_UPLOADING = "uploading"
STATE_DONE = "done"
STATE_FAILED = "failed"

# What an artifact IS, which is also the order it goes up in. Stills first
# (the clip becomes visible), proxy next (it becomes playable), the original
# last (tens of GB, and nothing is blocked on it) -- see the module docstring.
KIND_POSTER = "poster"
KIND_SPRITE = "sprite"
KIND_PROXY = "proxy"
KIND_ORIGINAL = "original"
UPLOAD_ORDER = {KIND_POSTER: 0, KIND_SPRITE: 1, KIND_PROXY: 2, KIND_ORIGINAL: 3}

# rclone's closing "fatal error received" notice repeats the fact of failure
# without the cause -- broll_fetch skips it for the same reason.
_FATAL_NOTICE = broll_fetch._FATAL_NOTICE
_ERROR_LEVELS = broll_fetch._ERROR_LEVELS


class UploadJob:
    """One artifact on its way to the NAS. Deliberately FetchJob's shape --
    same fields, same `progress()` dict, same `cancel()` -- so the loopback's
    progress route and the tray can format either without knowing which
    direction the bytes are going."""

    def __init__(self, local_path: str, remote_rel: str, kind: str,
                 item_uid: str = "", size_bytes: Optional[int] = None):
        self.local_path = local_path
        self.remote_rel = remote_rel
        self.kind = kind
        self.item_uid = item_uid
        self.size_bytes = size_bytes
        self.state = STATE_QUEUED
        self.error: Optional[str] = None
        self.bytes_done: Optional[int] = None
        self.bytes_total: Optional[int] = None
        self.speed_bps: Optional[float] = None
        self.eta_seconds: Optional[int] = None
        self.proc: Optional[subprocess.Popen] = None
        self.cancelled = False
        self.attempts = 0
        self.lock = threading.Lock()

    @property
    def order(self) -> tuple[int, str]:
        """Stills, then proxy, then original; ties broken by the remote path so
        a queue is deterministic (and therefore testable)."""
        return (UPLOAD_ORDER.get(self.kind, len(UPLOAD_ORDER)), self.remote_rel)

    def progress(self) -> dict[str, Any]:
        with self.lock:
            done, total = self.bytes_done, self.bytes_total
            snapshot = {
                "kind": self.kind,
                "rel": self.remote_rel,
                "bytes": done,
                "total_bytes": total,
                "speed_bps": self.speed_bps,
                "eta_seconds": self.eta_seconds,
            }
        if isinstance(done, (int, float)) and isinstance(total, (int, float)) and total > 0:
            snapshot["percent"] = max(0, min(100, int(done * 100 / total)))
        return snapshot

    def feed_stats(self, stats: dict) -> None:
        with self.lock:
            self.bytes_done = stats.get("bytes")
            self.bytes_total = stats.get("totalBytes")
            self.speed_bps = stats.get("speed")
            self.eta_seconds = stats.get("eta")

    def cancel(self) -> None:
        """Best-effort kill: shutdown, a cancelled batch, or the editor coming
        back. Never raises."""
        with self.lock:
            self.cancelled = True
            proc = self.proc
        if proc is not None:
            try:
                proc.kill()
            except Exception:
                log.debug("broll upload: kill failed for %s", self.remote_rel, exc_info=True)


# ---------------------------------------------------------------------------
# argv
# ---------------------------------------------------------------------------

def _remote_spec(ccsync_cfg: dict[str, Any], remote_rel: str,
                 archive_rel: str = ARCHIVE_REMOTE_REL) -> str:
    remote = str(ccsync_cfg.get("remote") or "").strip()
    remote_root = str(ccsync_cfg.get("remote_root") or "").strip()
    return f"{remote}:{remote_root.rstrip('/')}/{archive_rel.strip('/')}/{remote_rel.lstrip('/')}"


def build_upload_command(ccsync_cfg: dict[str, Any], local_path: str | Path,
                         remote_rel: str,
                         archive_rel: str = ARCHIVE_REMOTE_REL) -> list[str]:
    """The `rclone copyto` argv for one artifact.

    `copyto`, not `copy`: one source file, one destination path, nothing to
    traverse -- and it is what lets the SERVER decide the name (the batch
    claim allocates `<stem>_2` against claimed names, never against disk), so
    this side never guesses. rclone writes to `<name>.partial` on the far side
    and renames on completion, so a killed upload cannot leave a
    plausible-looking truncated clip where the server's stat() would find it.

    The tuning and transport flags come from `rclone_lane` so an operator's
    config.toml knobs (sftp_chunk_size, connections, checkers) apply here too;
    DIRECTION_UP because this is the same direction lane A moves in and its
    `--order-by` is the one meant for uploads.

    `--verbose` is NOT carried over from broll_fetch's command: the default
    log level already emits `--stats` lines at NOTICE, and an unattended
    background upload of a 40 GB original does not need per-file INFO chatter
    on the stderr pipe this process has to drain.
    """
    rclone_path = str(ccsync_cfg.get("rclone_path") or "rclone")
    tuning = rclone_lane.RcloneTuning.from_cfg(ccsync_cfg)
    return [
        rclone_path,
        "copyto",
        str(local_path),
        _remote_spec(ccsync_cfg, remote_rel, archive_rel),
        *tuning.flags(rclone_lane.DIRECTION_UP),
        *rclone_lane._transport_flags(),
        "--use-json-log",
        "--stats", "1s",
        "--stats-log-level", "NOTICE",
    ]


def build_verify_command(ccsync_cfg: dict[str, Any], remote_rel: str,
                         archive_rel: str = ARCHIVE_REMOTE_REL) -> list[str]:
    """`rclone lsjson` for one uploaded file -- the size check.

    Size, not checksum: the SFTP remote exposes no hashes for these files
    (docs/BROLL_INGEST_PLAN.md §9 Q4), so `--checksum` would either be a lie
    or a full re-read of a 40 GB original over the link. The server's own
    stat() under BROLL_DATA_ROOT is the authority; this is the cheap local
    half that catches "rclone exited 0 and nothing is there".
    """
    rclone_path = str(ccsync_cfg.get("rclone_path") or "rclone")
    return [
        rclone_path,
        "lsjson",
        _remote_spec(ccsync_cfg, remote_rel, archive_rel),
        *rclone_lane._transport_flags(),
    ]


def parse_verify_size(stdout: Optional[str], name: str = "") -> Optional[int]:
    """The uploaded file's size out of `rclone lsjson` output, or None.

    None means "could not tell", never "zero": an unparseable answer must not
    read as a failed upload -- the server is about to stat the file anyway,
    and failing a clip on our own JSON parsing would be the worst kind of
    false negative.
    """
    try:
        rows = json.loads(stdout or "")
    except (TypeError, ValueError):
        return None
    if not isinstance(rows, list) or not rows:
        return None
    wanted = os.path.basename(name) if name else ""
    for row in rows:
        if not isinstance(row, dict):
            continue
        if wanted and str(row.get("Name") or row.get("Path") or "") != wanted:
            continue
        size = row.get("Size")
        if isinstance(size, (int, float)) and size >= 0:
            return int(size)
    return None


# ---------------------------------------------------------------------------
# the queue
# ---------------------------------------------------------------------------

class UploadQueue:
    """One rclone at a time, in artifact order, pausable.

    ONE at a time is not a tuning choice: lanes A and B are already competing
    for the same SFTP link and the same NAS, and the sequencer exists because
    two rclones on one link are slower than one. Background ingest uploads get
    the leftovers, politely.

    `progress()` does NO I/O -- it rides the reporter's tick and every tray
    menu build. `pause()` stops STARTING work and kills nothing: a 40 GB
    original killed at 39 GB restarts from byte 0 (SFTP uploads do not
    resume), so a pause waits for the file in flight. `stop_all()` is the
    shutdown path and does kill.
    """

    def __init__(self, cfg_fn: Callable[[], dict[str, Any]],
                 runner: Optional[Callable[["UploadQueue", UploadJob, list[str]], None]] = None):
        """`cfg_fn` is read per job, not once: an operator can repoint the
        remote (or fix a blank remote_root) without restarting the tray, and
        a batch can outlive several config reloads.

        `runner(queue, job, cmd)` replaces the rclone spawn AND owns the
        job's outcome -- it must call `queue._finish(job, ok, error)`. That is
        the tests' seam and the one place they are allowed to reach past the
        public surface; nothing in the app passes one.
        """
        self._cfg_fn = cfg_fn
        self._runner = runner
        self._lock = threading.RLock()
        self._queue: list[UploadJob] = []
        self._active: Optional[UploadJob] = None
        self._done: list[UploadJob] = []
        self._failed: list[UploadJob] = []
        self._paused = False
        self._stopped = False
        self._wake = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # -- submission ---------------------------------------------------------

    def enqueue(self, local_path: str | Path, remote_rel: str, kind: str,
                item_uid: str = "", size_bytes: Optional[int] = None) -> UploadJob:
        """Queue one artifact. Idempotent per remote path: a re-queue of
        something already in flight (a retried item, a duplicated tick) joins
        the existing job rather than racing a second rclone at the same
        destination."""
        with self._lock:
            for existing in ([self._active] if self._active else []) + self._queue:
                if existing.remote_rel == remote_rel:
                    return existing
            job = UploadJob(str(local_path), remote_rel, kind, item_uid, size_bytes)
            self._queue.append(job)
            self._queue.sort(key=lambda j: j.order)
        self._ensure_thread()
        self._wake.set()
        return job

    # -- control ------------------------------------------------------------

    def pause(self) -> None:
        with self._lock:
            self._paused = True

    def resume(self) -> None:
        with self._lock:
            self._paused = False
        self._wake.set()

    @property
    def paused(self) -> bool:
        with self._lock:
            return self._paused

    def stop_all(self) -> None:
        """Kill what is in flight and stop the worker. For shutdown and for a
        cancelled batch; never raises."""
        with self._lock:
            self._stopped = True
            active = self._active
            queued = list(self._queue)
            self._queue.clear()
        for job in queued:
            job.state = STATE_FAILED
            job.error = "cancelled"
        if active is not None:
            active.cancel()
        self._wake.set()

    # -- reporting ----------------------------------------------------------

    def progress(self) -> dict[str, Any]:
        """Zero I/O. {queued, active, done, failed, paused}."""
        with self._lock:
            active = self._active
            snapshot = {
                "queued": len(self._queue),
                "done": len(self._done),
                "failed": len(self._failed),
                "paused": self._paused,
            }
        snapshot["active"] = active.progress() if active is not None else None
        return snapshot

    def failures(self) -> list[dict[str, Any]]:
        """What failed and why -- for the item's `error` and the retry button."""
        with self._lock:
            return [{"rel": j.remote_rel, "kind": j.kind, "item_uid": j.item_uid,
                     "error": j.error or "the upload failed"} for j in self._failed]

    def uploaded(self) -> list[dict[str, Any]]:
        """What landed, as the fleet route's `files:[{rel,size}]` wants it."""
        with self._lock:
            return [{"rel": j.remote_rel, "kind": j.kind, "item_uid": j.item_uid,
                     "size": j.bytes_total or j.size_bytes} for j in self._done]

    # -- the worker ---------------------------------------------------------

    def _ensure_thread(self) -> None:
        with self._lock:
            if self._stopped or (self._thread is not None and self._thread.is_alive()):
                return
            self._thread = threading.Thread(target=self._loop, name="ccsync-broll-upload",
                                            daemon=True)
            self._thread.start()

    def _next_job(self) -> Optional[UploadJob]:
        with self._lock:
            if self._stopped or self._paused or self._active is not None or not self._queue:
                return None
            job = self._queue.pop(0)
            self._active = job
            job.state = STATE_UPLOADING
            job.attempts += 1
            return job

    def _finish(self, job: UploadJob, ok: bool, error: str = "") -> None:
        with self._lock:
            self._active = None
            if ok:
                job.state = STATE_DONE
                self._done.append(job)
            else:
                job.state = STATE_FAILED
                job.error = error or "the upload failed"
                self._failed.append(job)
        self._wake.set()

    def _loop(self) -> None:
        while True:
            with self._lock:
                if self._stopped:
                    return
                idle = self._active is None and (self._paused or not self._queue)
            if idle:
                self._wake.wait(timeout=1.0)
                self._wake.clear()
                continue
            job = self._next_job()
            if job is None:
                self._wake.wait(timeout=1.0)
                self._wake.clear()
                continue
            cfg = {}
            try:
                cfg = self._cfg_fn() or {}
            except Exception:  # noqa: BLE001 - a config read must not kill the queue
                log.debug("broll upload: config read failed", exc_info=True)
            refusal = broll_fetch.prereq_error(cfg)
            if refusal:
                # Not a per-file failure: this machine cannot reach the NAS at
                # all right now. The job goes back to the front of the queue
                # and the next tick tries again -- "NAS unreachable" must not
                # burn an item's attempts (plan §6).
                with self._lock:
                    self._active = None
                    job.state = STATE_QUEUED
                    job.error = refusal
                    self._queue.insert(0, job)
                log.info("broll upload: waiting -- %s", refusal)
                self._wake.wait(timeout=5.0)
                self._wake.clear()
                continue
            cmd = build_upload_command(cfg, job.local_path, job.remote_rel)
            if self._runner is not None:
                self._runner(self, job, cmd)
                continue
            ok, error = run_upload(job, cmd)
            if ok:
                ok, error = verify_upload(cfg, job)
            self._finish(job, ok, error)


# ---------------------------------------------------------------------------
# running one upload
# ---------------------------------------------------------------------------

def _feed_line(job: UploadJob, line: str, errors: list[str]) -> None:
    """One stderr line: `--stats` progress into the job, error text aside.
    broll_fetch._feed_line's logic, on an UploadJob."""
    line = line.strip()
    if not line or not line.startswith("{"):
        return
    try:
        record = json.loads(line)
    except json.JSONDecodeError:
        return
    stats = record.get("stats")
    if isinstance(stats, dict):
        job.feed_stats(stats)
    if str(record.get("level", "")).lower() in _ERROR_LEVELS:
        msg = str(record.get("msg") or "").strip()
        if msg and _FATAL_NOTICE not in msg.lower():
            errors.append(msg)


def run_upload(job: UploadJob, cmd: list[str]) -> tuple[bool, str]:
    """Run one rclone to completion -> (ok, error). Never raises.

    Same never-let-the-reader-die rule as the lanes: an exception in the
    stderr loop would leave rclone blocked on a full pipe for ever, holding
    the queue.
    """
    errors: list[str] = []
    try:
        proc = subprocess.Popen(
            cmd,
            stderr=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            encoding="utf-8",
            errors="replace",
            creationflags=rclone_lane._win_creationflags(),
        )
    except OSError as exc:
        return False, f"could not start rclone: {exc}"

    with job.lock:
        already_cancelled = job.cancelled
        if not already_cancelled:
            job.proc = proc
    if already_cancelled:
        # stop_all() ran between the spawn and this publication; its kill
        # found proc still None, so it falls to us.
        try:
            proc.kill()
        except Exception:
            pass

    try:
        try:
            for line in proc.stderr:
                _feed_line(job, line, errors)
        except Exception:
            log.exception("broll upload: stderr reader failed -- killing rclone")
            try:
                proc.kill()
            except Exception:
                pass
        returncode = proc.wait()
    finally:
        with job.lock:
            job.proc = None

    if job.cancelled:
        return False, "cancelled"
    if returncode == 0:
        return True, ""
    return False, (errors[-1] if errors else f"rclone exited with code {returncode}")


def verify_upload(ccsync_cfg: dict[str, Any], job: UploadJob,
                  runner: Optional[Callable[..., Any]] = None) -> tuple[bool, str]:
    """Confirm the far side has the file, at the size we sent -> (ok, error).

    A size we cannot READ is not a failure (parse_verify_size's rule): the
    server stats the file itself before flipping the row live, and refusing a
    clip on our own lsjson parsing would be a false negative. A size we CAN
    read and that disagrees is a real failure -- a truncated upload that the
    server would otherwise reject one round trip later.
    """
    run = runner or (lambda cmd: subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=120, creationflags=rclone_lane._win_creationflags()))
    try:
        local_size = os.path.getsize(job.local_path)
    except OSError:
        local_size = None

    try:
        proc = run(build_verify_command(ccsync_cfg, job.remote_rel))
    except Exception as exc:  # noqa: BLE001 - see the docstring
        log.debug("broll upload: lsjson verification failed (%s)", exc, exc_info=True)
        return True, ""
    if getattr(proc, "returncode", 1) != 0:
        return False, (f"the upload finished but {job.remote_rel} is not on the NAS "
                       f"({(getattr(proc, 'stderr', '') or '').strip()[:120]})")

    remote_size = parse_verify_size(getattr(proc, "stdout", ""),
                                    os.path.basename(job.remote_rel))
    if remote_size is None or local_size is None:
        return True, ""
    with job.lock:
        job.bytes_total = job.bytes_total or remote_size
    if remote_size != local_size:
        return False, (f"{job.remote_rel} arrived at {remote_size} bytes, not "
                       f"{local_size} -- it will be sent again")
    return True, ""
