"""The dashboard's OWN executor for jobs the fleet gave up on.

docs/TIMELINE-CARDS-INTO-CCSYNC.md §4.4 rule 5 and §6 phase 4 (2026-08-30).
Rule 5 has always read "N attempts, then mode_lock-style pinning to the NAS
worker so a job that no machine can do does not ping-pong for ever". Phase 1
shipped the first half and wrote down exactly why it could not ship the
second: an abandoned job was VISIBLE, and there was no NAS-side executor to
hand it to, "because there is none".

There is one now. Phase 3 mounted the Timeline Cards engine in this
container, with the vault rw, the footage share ro and its own single ffmpeg
worker -- the very worker the fleet job kinds were carved out of. So a media
job the fleet cannot finish is not abandoned any more: it is PINNED, and this
thread hands it to that worker.

Four rules, each with its reason:

  * **ONLY THE MEDIA KINDS.** `whisper` never pins: this container has ffmpeg
    and no GPU, and a pin would be a job that fails for ever in a new place.
    It is abandoned, visibly, which is the honest answer (db.JOB_PINNABLE_KINDS).
  * **THE PIN IS ONE-WAY.** Nothing here ever re-queues. The fleet has
    already spent the whole retry budget; putting it back is the ping-pong
    rule 5 exists to end. A failure here is `abandoned`.
  * **THE ENGINE OWNS THE FFMPEG, NOT THIS MODULE.** The work goes through
    ONE seam -- `engine.fleet_execute(kind, source, out_dir, stem, ...)`,
    §7f -- which enqueues onto the engine's own `_src_q`/`_vid_q`. That is
    what keeps "the NAS must never run dozens of ffmpegs because a lane
    opened" true with a queue feeding it, and what keeps the recipe (the
    argv, the `.partial`, first-writer-wins) in the one place a page reads.
    An engine without that method is NO EXECUTOR AT ALL: nothing pins, and
    jobs are abandoned exactly as they were in phase 1.
  * **PATHS ARE RESOLVED THROUGH THIS CONTAINER'S ROOTS** (§4.1). A job's
    inputs are (root name, relative path) pairs; `container_roots` is what
    this container calls `vault`, `media` and `tree`. A root that is not
    configured here is a job that fails with a sentence naming the setting,
    never a path guessed from a mount table.

The result is `done` with `result.files` relative to the output root, exactly
as a companion's would be -- because the Timeline Cards client polling that
row may be on another server entirely, and it must not be able to tell who
made the file (§7b.4: read the answer off the DISK).
"""
from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Any, Callable

from . import db

log = logging.getLogger("ccsync.dashboard.cards_exec")

# How often the executor looks for pinned work. Slow on purpose: a pinned job
# has already waited through a whole retry budget, and this thread shares a
# container with the fleet dashboard, whose job is to tell everyone whether
# their footage is syncing.
POLL_SECONDS = 10.0

# The seam the Timeline Cards engine provides (§7f). Named here as a constant
# because "is there an executor" is asked in three places and must be one
# question.
ENGINE_METHOD = "fleet_execute"


class ExecutorError(Exception):
    """A job this container cannot do. Never retried anywhere: by the time a
    job is pinned there is nowhere left to try."""


def container_roots(settings: Any) -> dict[str, str]:
    """What THIS container calls the fleet's root names.

    `DASH_JOBS_ROOTS` wins ("vault=/vault,media=/media"); otherwise the
    values this deployment already has -- the Timeline Cards vault root and
    the projects mount. `media` has no fallback on purpose: the footage share
    is a separate bind mount and guessing it from the media map would be
    guessing which side of a pair is which.
    """
    roots: dict[str, str] = {}
    vault = (str(getattr(settings, "cards_root", "") or "").strip()
             or str(getattr(settings, "cards_vault_root", "") or "").strip())
    if vault:
        roots["vault"] = vault
    tree = str(getattr(settings, "projects_dir", "") or "").strip()
    if tree:
        roots["tree"] = tree
    for name, path in dict(getattr(settings, "jobs_roots", None) or {}).items():
        roots[str(name)] = str(path)
    return roots


def resolve(roots: dict[str, str], root: str, rel: str) -> Path:
    """(root name, relative path) -> a path in this container, or a refusal.

    The same rule `companion/job_paths.py` enforces on the other side, for
    the same reason: an absolute path on the wire is right on exactly one
    machine, and `..` is how a cache write leaves the vault.
    """
    name = str(root or "").strip().lower()
    base = roots.get(name)
    if not base:
        raise ExecutorError(
            f"this container has no {name!r} root configured, so it cannot "
            f"place this job's paths (DASH_JOBS_ROOTS)")
    parts = [p for p in str(rel or "").replace("\\", "/").split("/") if p]
    if any(p == ".." for p in parts):
        raise ExecutorError(f"{rel!r} leaves its root")
    return Path(base).joinpath(*parts)


class PinnedExecutor:
    """The thread that drains `pinned`. Never raises out of tick()."""

    def __init__(self, settings: Any, engine: Any,
                 connect: Callable[[], Any] | None = None,
                 poll_seconds: float = POLL_SECONDS) -> None:
        self.settings = settings
        self.engine = engine
        self.poll_seconds = float(poll_seconds)
        self._connect = connect or (lambda: db.connect(settings.db_path))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.roots = container_roots(settings)

    # -- is there an executor at all ------------------------------------
    def available(self) -> bool:
        """What `jobs.can_pin` asks. An engine that is not mounted, or one
        from a checkout that does not implement the seam yet, is NO executor:
        the answer must be false so jobs are abandoned visibly rather than
        pinned into a queue nothing drains."""
        return callable(getattr(self.engine, ENGINE_METHOD, None))

    def why_not(self) -> str:
        if self.engine is None:
            return "Timeline Cards is not mounted in this dashboard"
        if not self.available():
            return (f"the mounted Timeline Cards checkout has no "
                    f"{ENGINE_METHOD}() (plan section 7f)")
        return ""

    # -- the loop --------------------------------------------------------
    def start(self) -> None:
        if self._thread is not None or not self.available():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="ccsync-pinned",
                                        daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=5.0)

    def _loop(self) -> None:
        """ONE CONNECTION FOR THE LIFE OF THE THREAD, the collector's shape
        (and its DASH-8 lesson): an open that fails is retried on the next
        pass rather than killing the only thread that drains this queue."""
        conn = None
        try:
            while not self._stop.is_set():
                if conn is None:
                    try:
                        conn = self._connect()
                    except Exception:  # noqa: BLE001
                        log.exception("the pinned job executor could not open "
                                      "the database; retrying")
                        self._stop.wait(max(2.0, self.poll_seconds))
                        continue
                try:
                    self.tick(conn)
                except Exception:  # noqa: BLE001 - a worker thread never dies
                    log.exception("the pinned job executor's tick failed")
                self._stop.wait(max(2.0, self.poll_seconds))
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:  # noqa: BLE001
                    pass

    def tick(self, conn: Any) -> list[int]:
        """One pass. -> the ids that ended (done or abandoned)."""
        if not self.available():
            return []
        ended: list[int] = []
        for job in db.pinned_jobs(conn):
            if self._stop.is_set():
                break
            if not db.take_pinned_job(conn, int(job["id"])):
                continue
            conn.commit()
            ended.append(self._run(conn, job))
        return [i for i in ended if i]

    # -- one job ---------------------------------------------------------
    def _run(self, conn: Any, job: dict) -> int:
        job_id = int(job["id"])
        kind = str(job["kind"])
        try:
            source, out_dir, stem, out_root, out_rel = self._paths(job)
        except ExecutorError as exc:
            log.warning("pinned job #%s cannot be placed here: %s", job_id, exc)
            db.fail_pinned_job(conn, job_id, str(exc))
            conn.commit()
            return job_id

        def on_progress(fraction: Any) -> None:
            # Its own connection would be tidier and a second writer on the
            # same row would be worse. This runs on the thread that called
            # fleet_execute, which is this one.
            try:
                db.pin_progress(conn, job_id, fraction)
                conn.commit()
            except Exception:  # noqa: BLE001
                log.debug("pinned job #%s: could not record progress", job_id,
                          exc_info=True)

        def should_stop() -> str:
            if self._stop.is_set():
                return "this dashboard is shutting down"
            try:
                if db.job_cancel_requested(conn, job_id):
                    return db.JOB_CANCELLED_ERROR
            except Exception:  # noqa: BLE001
                log.debug("pinned job #%s: could not read the cancel flag",
                          job_id, exc_info=True)
            return ""

        log.info("pinned job #%s: %s of %s -> %s (nothing in the fleet would "
                 "finish it)", job_id, kind, source, out_dir)
        try:
            outcome = dict(getattr(self.engine, ENGINE_METHOD)(
                kind, str(source), str(out_dir), stem,
                on_progress=on_progress, should_stop=should_stop) or {})
        except Exception as exc:  # noqa: BLE001 - the engine is another repo
            log.warning("pinned job #%s (%s) failed here too: %s", job_id, kind, exc)
            db.fail_pinned_job(conn, job_id, f"{type(exc).__name__}: {exc}")
            conn.commit()
            return job_id
        if outcome.get("error"):
            db.fail_pinned_job(conn, job_id, str(outcome["error"]))
            conn.commit()
            return job_id
        result = dict(outcome)
        result["executor"] = db.PIN_HOLDER
        # PATHS RELATIVE TO THE OUTPUT ROOT, with the root named beside them,
        # exactly as a companion answers (§4.1 applied to the answer): the
        # client reading this row may be on another server, where /vault
        # means nothing.
        result["out_root"] = out_root
        result["files"] = [f"{out_rel}/{name}" if out_rel else str(name)
                           for name in (outcome.get("files") or [])]
        db.finish_pinned_job(conn, job_id, result)
        conn.commit()
        log.info("pinned job #%s: done, %d file(s)", job_id, len(result["files"]))
        return job_id

    def _paths(self, job: dict) -> tuple[Path, Path, str, str, str]:
        """A media job's inputs -> (source, out dir, stem, out root, out rel).

        `jobs_runner._media_paths`'s answer, computed against this
        container's roots instead of a machine's config. Same fields, same
        refusals, on purpose: a job that lands here has already been read by
        the other implementation, and two spellings of "where does the file
        go" is how a cache ends up in two places."""
        inputs = dict(job.get("inputs") or {})
        root = str(inputs.get("root") or "media")
        source = resolve(self.roots, root, str(inputs.get("rel_path") or ""))
        out_root = str(inputs.get("out_root") or root)
        out_rel = str(inputs.get("out_rel") or "").strip().replace("\\", "/").strip("/")
        if not out_rel:
            raise ExecutorError(
                "a media job must name the directory its output goes in "
                "(out_root + out_rel)")
        out_dir = resolve(self.roots, out_root, out_rel)
        stem = str(inputs.get("out_stem") or "").strip() or _stem(source)
        return source, out_dir, stem, out_root, out_rel


def _stem(path: Path) -> str:
    return os.path.splitext(path.name)[0]
