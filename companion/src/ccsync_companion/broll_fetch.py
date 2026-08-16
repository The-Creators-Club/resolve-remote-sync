"""On-demand download of ONE b-roll archive clip -- or one music track -- from the NAS.

Why this exists (2026-08-11): remote editors sync their ticked projects plus
the shared asset folders (Luts, Stills) -- the b-roll archive is neither, so
"Send to Resolve" dead-ended at "file not found -- is the share mounted?" on
every machine except the base rig, whose local_root IS the NAS share. Syncing
the whole archive down would cost every editor hundreds of GB for a library
they browse remotely; instead the companion pulls exactly the clip the editor
just asked to insert, into the same place a full sync would have put it
(<local_root>/Assets/B-roll Archive/<rel_path>), over the same rclone remote
lanes A and B already use. broll_server.build_insert_response was the only
caller; since 2026-08-16 music_server.build_send_response is the second, for
the identical reason -- the music library (Assets/Music) is not a synced
folder either, so every "+ Resolve" on a remote editor's machine dead-ended
at the same "is the share mounted?" (ruskin, 2026-08-16). Both answer
{"state": "downloading"} responses the web UI polls, and perform the
insert on the first poll that finds the file in place. The NAS-side folder
is a parameter (`remote_rel`) so the two callers share one job registry,
one rclone command shape and one shutdown kill.

Jobs are keyed by destination path, so a re-click (or the UI's own 1.5 s
poll) joins the running download instead of spawning a second rclone racing
the first for the same .partial. Terminal states are popped on read: after
"failed" the next poll retries from scratch, and after "done" the caller
re-checks the filesystem, which is the only authority worth trusting there.

Deliberately NOT a lane: no filter files, no LaneStatus, no dashboard
reporting, no sequencer turn. One file, one `rclone copyto`, one daemon
thread parsing --stats JSON for the progress bar. The transport flags and
tuning come from rclone_lane so a knob an operator sets in config.toml
(sftp_chunk_size etc.) applies to this download too.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
from typing import Any, Optional

from .sync import rclone_lane

log = logging.getLogger("ccsync.broll")

# Where the archive lives under remote_root on the NAS. Must stay in step
# with broll_server.BROLL_ARCHIVE_REL (the local half of the same layout);
# test_broll_fetch.py pins the pair together. A string, not a tuple: this
# side is only ever joined into an rclone remote spec with forward slashes.
ARCHIVE_REMOTE_REL = "Assets/B-roll Archive"
# The music library's NAS-side folder; the local half is
# music_server.MUSIC_LIBRARY_REL. Same pinning rule as the archive pair.
MUSIC_REMOTE_REL = "Assets/Music"

STATE_DOWNLOADING = "downloading"
STATE_DONE = "done"
STATE_FAILED = "failed"

# rclone's closing "fatal error received" notice repeats the fact of failure
# without the cause -- same reason rclone_lane._most_informative_error skips
# it when picking a line for the tray.
_FATAL_NOTICE = "fatal error received"
_ERROR_LEVELS = ("error", "critical", "fatal")


class FetchJob:
    """One running (or just-finished) archive download."""

    def __init__(self, dest: str, rel_path: str):
        self.dest = dest
        self.rel_path = rel_path
        self.state = STATE_DOWNLOADING
        self.error: Optional[str] = None
        self.bytes_done: Optional[int] = None
        self.bytes_total: Optional[int] = None
        self.speed_bps: Optional[float] = None
        self.eta_seconds: Optional[int] = None
        self.proc: Optional[subprocess.Popen] = None
        self.cancelled = False
        self.lock = threading.Lock()

    def progress(self) -> dict[str, Any]:
        with self.lock:
            done, total = self.bytes_done, self.bytes_total
            snapshot = {
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
        """Best-effort kill for shutdown. Never raises."""
        with self.lock:
            self.cancelled = True
            proc = self.proc
        if proc is not None:
            try:
                proc.kill()
            except Exception:
                log.debug("broll fetch: kill failed for %s", self.dest, exc_info=True)


_JOBS: dict[str, FetchJob] = {}
_JOBS_LOCK = threading.Lock()


def _job_key(dest: str) -> str:
    return os.path.normcase(os.path.normpath(os.path.abspath(dest)))


def prereq_error(ccsync_cfg: dict[str, Any]) -> Optional[str]:
    """Why this machine cannot fetch from the NAS at all, or None if it can.

    Editor-facing text -- it lands in the web UI's toast verbatim. These are
    the same conditions config.validate_config flags for the lanes, but a
    machine can run with config_problems (sync stands down, the 8899 server
    does not), so they are re-checked here rather than assumed away.
    """
    remote = str(ccsync_cfg.get("remote") or "").strip()
    if not remote:
        return ("this machine's sync config names no rclone remote, so the "
                "clip can't be fetched from the NAS (remote= in ~/.ccsync/config.toml)")
    remote_root = str(ccsync_cfg.get("remote_root") or "").strip()
    if not remote_root:
        return ("this machine's sync config has no remote_root, so the "
                "clip can't be fetched from the NAS (remote_root= in ~/.ccsync/config.toml)")
    rclone_path = str(ccsync_cfg.get("rclone_path") or "rclone")
    ok, detail = rclone_lane.rclone_available(rclone_path)
    if not ok:
        return f"can't fetch the clip from the NAS -- {detail}"
    return None


def build_fetch_command(ccsync_cfg: dict[str, Any], rel_path: str, dest: str,
                        remote_rel: str = ARCHIVE_REMOTE_REL) -> list[str]:
    """The `rclone copyto` argv for one file under `remote_rel` on the NAS.

    `copyto`, not `copy` with a filter: one source file, one destination
    path, nothing to traverse. rclone writes dest as `<name>.partial` and
    renames on completion, so a killed download can never leave a
    plausible-looking truncated clip where is_file() would find it.
    """
    rclone_path = str(ccsync_cfg.get("rclone_path") or "rclone")
    remote = str(ccsync_cfg.get("remote") or "").strip()
    remote_root = str(ccsync_cfg.get("remote_root") or "").strip()
    tuning = rclone_lane.RcloneTuning.from_cfg(ccsync_cfg)
    src = f"{remote}:{remote_root.rstrip('/')}/{remote_rel.strip('/')}/{rel_path}"
    return [
        rclone_path,
        "copyto",
        src,
        str(dest),
        *tuning.flags(rclone_lane.DIRECTION_DOWN),
        *rclone_lane._transport_flags(),
        "--use-json-log",
        "--verbose",
        "--stats", "1s",
        "--stats-log-level", "NOTICE",
    ]


def _feed_line(job: FetchJob, line: str, errors: list[str]) -> None:
    """One stderr line: --stats progress into the job, error text aside."""
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


def _run_job(job: FetchJob, cmd: list[str]) -> None:
    """The download thread. Sets the job's terminal state; never raises."""
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
        with job.lock:
            job.state = STATE_FAILED
            job.error = f"could not start rclone: {exc}"
        return

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
        # Same never-let-the-reader-die rule as the lanes: an exception here
        # would leave rclone blocked on a full stderr pipe forever.
        try:
            for line in proc.stderr:
                _feed_line(job, line, errors)
        except Exception:
            log.exception("broll fetch: stderr reader failed -- killing rclone")
            try:
                proc.kill()
            except Exception:
                pass
        returncode = proc.wait()
    finally:
        with job.lock:
            job.proc = None

    if returncode == 0 and os.path.isfile(job.dest):
        with job.lock:
            job.state = STATE_DONE
        log.info("broll fetch: synced %s", job.dest)
        return

    if returncode == 0:
        # rclone reported success but the file is not there -- a moved mount,
        # a dest on a share that vanished mid-run. Say so rather than "error".
        message = f"the download finished but {job.dest} is still missing"
    else:
        message = errors[-1] if errors else f"rclone exited with code {returncode}"
    with job.lock:
        job.state = STATE_FAILED
        job.error = "cancelled -- the companion shut down" if job.cancelled else message
    log.warning("broll fetch: %s failed: %s", job.rel_path, job.error)


def poll_fetch(
    ccsync_cfg: dict[str, Any],
    rel_path: str,
    dest: str,
    runner: Optional[Any] = None,
    remote_rel: str = ARCHIVE_REMOTE_REL,
) -> dict[str, Any]:
    """Start (or join) the download that puts `dest` in place; report state.

    `remote_rel` is the NAS-side folder `rel_path` hangs off (the archive by
    default, MUSIC_REMOTE_REL for the music route). Jobs are keyed by `dest`,
    so the two callers can never race each other for one file.

    Returns one of:
      {"state": "downloading", "progress": {...}}
      {"state": "done"}                       -- popped; caller re-checks disk
      {"state": "failed", "message": str}     -- popped; next poll retries

    `runner` is the thread-spawn seam for tests: it receives (job, cmd) and
    defaults to a daemon thread running _run_job.
    """
    key = _job_key(dest)
    with _JOBS_LOCK:
        job = _JOBS.get(key)
        if job is None:
            err = prereq_error(ccsync_cfg)
            if err:
                return {"state": STATE_FAILED, "message": err}
            job = FetchJob(dest, rel_path)
            cmd = build_fetch_command(ccsync_cfg, rel_path, dest, remote_rel)
            _JOBS[key] = job
            if runner is not None:
                runner(job, cmd)
            else:
                threading.Thread(
                    target=_run_job, args=(job, cmd),
                    name="ccsync-broll-fetch", daemon=True,
                ).start()
            return {"state": STATE_DOWNLOADING, "progress": job.progress()}

    with job.lock:
        state, error = job.state, job.error
    if state == STATE_DOWNLOADING:
        return {"state": STATE_DOWNLOADING, "progress": job.progress()}
    with _JOBS_LOCK:
        _JOBS.pop(key, None)
    if state == STATE_DONE:
        return {"state": STATE_DONE}
    return {"state": STATE_FAILED, "message": error or "the download failed"}


def stop_all() -> None:
    """Kill every in-flight download. For companion shutdown; never raises.

    The registry is left alone: a poll after shutdown (there won't be one,
    the HTTP server stops in the same breath) would read the jobs' failed
    state and pop them normally.
    """
    with _JOBS_LOCK:
        jobs = list(_JOBS.values())
    for job in jobs:
        job.cancel()
