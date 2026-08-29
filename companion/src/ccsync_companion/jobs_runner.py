"""This machine doing work the fleet queued: claim, run, heartbeat, report.

docs/TIMELINE-CARDS-INTO-CCSYNC.md phase 0 (2026-08-29) and phase 1
(2026-08-30). Four kinds:

    whisper                             MulticamPipeline's corpus stage over a
                                        folder in the vault, as a subprocess.
    proxy-480p / audio-extract / peaks  the three Timeline Cards media
                                        recipes, in-process (`jobs_media.py`).

Either way the work writes into the vault, which every machine shares -- so
nothing streams through the dashboard and the job row records PATHS, never
bytes (§4.4 rule 6).

The shape is proxy_gen's, deliberately, because the thing being protected is
the same thing: an editor's machine. Every seam arrives as a constructor
parameter (the idle probe, the Resolve check, the HTTP call, the clock, the
subprocess runner) so the whole loop is testable with no dashboard, no venv,
no GPU and no keyboard.

Six rules, each with its reason:

  * **OFFERS ARE AN INVITATION, THE CLAIM IS THE DECISION.** The report reply
    names ids this machine MAY claim; the claim is a compare-and-set on the
    dashboard. Two machines offered the same job cannot both run it, and this
    side needs no co-ordination to be safe.
  * **ONE JOB AT A TIME.** Enforced here as well as by the scheduler: this
    loop refuses to claim while it is holding one, so a stale offer or a
    duplicated reply cannot start a second transcode on a machine already
    saturated by the first.
  * **THE IDLE GATE IS THE SAME ONE proxy_gen USES**, from the same probe
    object the capabilities section reports (app.py wires one), and None
    means cannot tell means NOT IDLE.
  * **A RUNNING JOB IS NOT KILLED WHEN THE EDITOR COMES BACK.** proxy_gen
    kills ffmpeg within ~2 s because a proxy costs seconds and is trivially
    resumable; a whisper pass is minutes of GPU work that resumes from
    nothing, so killing it turns "the machine was briefly slow" into "the
    work was wasted and the job is re-queued to fail the same way". No new
    job is claimed while somebody is here, which is the part that matters.
  * **A FLEET HALT STOPS IT** -- the child is terminated and the job handed
    back as a retryable failure. "Stop everything" outranks a transcript.
    A media recipe stops the same way, and its `.partial` is discarded rather
    than published: a half-written proxy that reached the vault would be a
    file the page plays.
  * **THE MEDIA RECIPES ARE NOT KILLED WHEN THE EDITOR RETURNS EITHER**, for
    the same reason as whisper and with less at stake: a 480p encode is
    seconds to minutes, it runs BELOW NORMAL priority (jobs_media._popen), and
    the half that protects the editor is that no new job is claimed while
    somebody is here.
  * **NOTHING HERE TOUCHES RESOLVE'S SCRIPTING API** (CR-68). The only
    Resolve question asked is whether the process is running, through
    resolve_prefs, which fails closed.
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

from . import config as config_mod
from . import job_paths, jobs_media

log = logging.getLogger("ccsync.jobs")

# Gate states, in the order _gate() asks them. The tray does not render these
# yet; the diagnostics bundle and the log do, and they are what "why is this
# machine not taking any work" is answered with.
STATE_DISABLED = "disabled"
STATE_NO_DASHBOARD = "no_dashboard"
STATE_HALTED = "halted"
STATE_NO_CAPABILITY = "no_capability"
STATE_RUNNING = "running"
STATE_USER_ACTIVE = "user_active"
STATE_RESOLVE_OPEN = "resolve_open"
STATE_NOTHING_OFFERED = "nothing_offered"
STATE_READY = "ready"

HTTP_TIMEOUT_SECONDS = 20.0
# The dashboard's lease is 300 s (db.JOB_LEASE_SECONDS). Beat every 30 so a
# machine has to miss ten in a row before it is treated as gone.
HEARTBEAT_SECONDS = 30.0
# How much of the pipeline's own output rides back with the result. Enough to
# carry its summary line and a traceback; nowhere near enough to be a log
# shipping channel.
OUTPUT_TAIL_CHARS = 4000
# How much longer this loop waits when the dashboard says the queue is empty
# (phase 4's backpressure, and it is the companion's half of it). Capped, so
# a machine that has backed off still notices work within two minutes -- the
# offers ride the report anyway, and the report interval is 5-60 s.
IDLE_BACKOFF = 4.0
IDLE_BACKOFF_MAX_SECONDS = 120.0
# What a job that an admin stopped is handed back as. NOT RETRYABLE, always:
# another machine picking up work a person just stopped is the one outcome
# nobody asked for, and the dashboard's own word for it is the same string
# (db.JOB_CANCELLED_ERROR).
CANCELLED_ERROR = "cancelled"
# "(12 written, 0 failed, 3 skipped) (41.2 min audio in 3.6 min, 11.4x
# realtime overall)" -- whisper_corpus's own summary line.
_REALTIME_RE = re.compile(r"([0-9.]+)x realtime")


class JobRunner:
    """The loop. Never raises out of tick()/start()/stop()."""

    def __init__(
        self,
        cfg: dict[str, Any],
        request_fn: Optional[Callable[..., tuple[int, Any]]] = None,
        editor_fn: Optional[Callable[[], Optional[str]]] = None,
        identity_token_fn: Optional[Callable[[], Optional[str]]] = None,
        capabilities_fn: Optional[Callable[[], dict[str, Any]]] = None,
        idle_probe: Any = None,
        resolve_running_fn: Optional[Callable[[], bool]] = None,
        halted_fn: Optional[Callable[[], bool]] = None,
        machine_name: str = "",
        runner_fn: Optional[Callable[..., Any]] = None,
        clock: Callable[[], float] = time.monotonic,
        notify: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.cfg = cfg or {}
        self._request = request_fn
        self._editor_fn = editor_fn
        self._identity_token_fn = identity_token_fn
        self._capabilities_fn = capabilities_fn
        self._idle_probe = idle_probe
        self._resolve_running_fn = resolve_running_fn
        self._halted_fn = halted_fn
        self._machine_name = machine_name
        self._runner = runner_fn or subprocess.Popen
        self._clock = clock
        self._notify = notify

        self.enabled = bool(self.cfg.get("jobs_enabled", True))
        self.idle_seconds = config_mod.coerce_numeric(self.cfg, "jobs_idle_seconds", 300)
        self.skip_while_resolve = bool(
            self.cfg.get("jobs_skip_while_resolve_running", True))
        self.poll_seconds = config_mod.coerce_numeric(self.cfg, "jobs_poll_seconds", 20)

        self._lock = threading.Lock()
        self._offered: list[int] = []
        # THE QUEUE DEPTH THE DASHBOARD LAST REPORTED (phase 4): {queued,
        # running, pinned, oldest_age_s}, or {} from a dashboard too old to
        # send one. It is not an instruction -- the offers are -- it is what
        # lets this loop stop asking a fleet that has nothing to give.
        self._queue: dict[str, Any] = {}
        self._cancel: list[int] = []
        self._job: Optional[dict[str, Any]] = None
        self._state = STATE_NOTHING_OFFERED
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # -- what the app hands us ------------------------------------------
    def note_report_reply(self, resp: Any) -> None:
        """Read `commands.jobs` off a report reply: what this machine may
        claim, what an admin has asked it to stop, and how deep the queue is.

        Never raises: this runs on the reporter thread, beside the halt and
        the file moves."""
        try:
            commands = resp.get("commands") if isinstance(resp, dict) else None
            block = commands.get("jobs") if isinstance(commands, dict) else None
            if not isinstance(block, dict):
                block = {}
            offered = block.get("offered")
            ids = [int(i) for i in offered] if isinstance(offered, list) else []
            cancel = block.get("cancel")
            stops = [int(i) for i in cancel] if isinstance(cancel, list) else []
            queue = block.get("queue")
            depth = dict(queue) if isinstance(queue, dict) else {}
        except (TypeError, ValueError):
            log.debug("jobs: unreadable offer block", exc_info=True)
            return
        with self._lock:
            self._offered = ids[:16]
            self._queue = depth
            self._cancel = stops[:16]

    def status(self) -> dict[str, Any]:
        """Zero-I/O snapshot for the log, the diagnostics bundle and (later)
        the tray."""
        with self._lock:
            job = dict(self._job) if self._job else None
            return {"state": self._state, "offered": list(self._offered),
                    "queue": dict(self._queue),
                    "job": {"id": job["id"], "kind": job["kind"]} if job else None}

    def wait_seconds(self) -> float:
        """How long to sleep before the next tick -- THE BACKOFF (phase 4).

        The offers ride the report reply, so a tick with nothing offered
        makes no HTTP call at all and costs nothing. What this exists for is
        the other half: a dashboard that says the queue is EMPTY is a
        dashboard that will have nothing for a while, and a fleet of eight
        machines waking up every 20 s to discover that is eight pointless
        wakeups a minute on eight editors' laptops.

        A DEEP queue never lengthens the wait. Backpressure here means "stop
        asking", never "stop working": the machines are what empties it.
        """
        base = max(2.0, float(self.poll_seconds))
        with self._lock:
            offered, depth = list(self._offered), dict(self._queue)
        if offered or not depth:
            return base
        if int(depth.get("queued") or 0) > 0 or int(depth.get("running") or 0) > 0:
            return base
        return min(base * IDLE_BACKOFF, IDLE_BACKOFF_MAX_SECONDS)

    # -- the gate --------------------------------------------------------
    def _seconds_idle(self) -> Optional[float]:
        if self._idle_probe is None:
            return None
        try:
            value = self._idle_probe.seconds_idle()
            return None if value is None else float(value)
        except Exception:
            log.debug("jobs: idle probe failed", exc_info=True)
            return None

    def _user_is_away(self) -> bool:
        """None (cannot tell) is NOT away. idle.py's contract."""
        idle = self._seconds_idle()
        return idle is not None and idle >= self.idle_seconds

    def _resolve_running(self) -> bool:
        """Fails CLOSED, like proxy_gen's: a check that cannot answer must not
        read as "the GPU is free"."""
        if self._resolve_running_fn is None:
            return False
        try:
            return bool(self._resolve_running_fn())
        except Exception:
            log.debug("jobs: resolve_running_fn failed", exc_info=True)
            return True

    def _cancel_requested(self, job_id: int) -> bool:
        """Has an admin asked this machine to stop this job? (Phase 4.)

        The id rides `commands.jobs.cancel` on the report reply and keeps
        riding it until this machine answers with a result -- so a click that
        lands while a laptop is asleep is a click that still happens.
        """
        with self._lock:
            return int(job_id) in self._cancel

    def _halted(self) -> bool:
        if self._halted_fn is None:
            return False
        try:
            return bool(self._halted_fn())
        except Exception:
            # Fails CLOSED too: "I could not tell whether everything is
            # stopped" must not start a GPU job.
            log.debug("jobs: halt check failed", exc_info=True)
            return True

    def _capabilities(self) -> dict[str, Any]:
        if self._capabilities_fn is None:
            return {}
        try:
            return dict(self._capabilities_fn() or {})
        except Exception:
            log.debug("jobs: capabilities failed", exc_info=True)
            return {}

    def runnable_kinds(self) -> list[str]:
        """The kinds THIS machine can actually execute right now.

        Sent with every claim, so a machine that has ffmpeg but no whisper
        venv is never handed a transcription it would have to give straight
        back -- and so a dashboard that grows a fifth kind cannot hand this
        build work it has no runner for. Capability-derived, not configured:
        the answer must not be able to disagree with the capabilities section
        the scheduler filtered on.
        """
        caps = self._capabilities()
        kinds: list[str] = []
        if caps.get("whisper"):
            kinds.append("whisper")
        # BOTH, never one: every media recipe probes before it encodes.
        if caps.get("ffmpeg") and caps.get("ffprobe"):
            kinds.extend(jobs_media.MEDIA_KINDS)
        return kinds

    def _gate(self) -> str:
        """Why this machine is or is not taking work, in priority order --
        proxy_gen._gate's shape, and the order an editor would ask the
        questions in."""
        if not self.enabled:
            return STATE_DISABLED
        if not self._dashboard_url or not self._token:
            return STATE_NO_DASHBOARD
        if self._halted():
            return STATE_HALTED
        with self._lock:
            holding = self._job is not None
            offered = list(self._offered)
        if holding:
            return STATE_RUNNING
        if not self.runnable_kinds():
            return STATE_NO_CAPABILITY
        if not self._user_is_away():
            return STATE_USER_ACTIVE
        if self.skip_while_resolve and self._resolve_running():
            return STATE_RESOLVE_OPEN
        if not offered:
            return STATE_NOTHING_OFFERED
        return STATE_READY

    # -- the fleet calls -------------------------------------------------
    @property
    def _dashboard_url(self) -> str:
        return str(self.cfg.get("dashboard_url", "") or "").strip().rstrip("/")

    @property
    def _token(self) -> str:
        """Read from cfg PER CALL: IdentityManager republishes a rotated token
        into this same dict at sign-in."""
        return str(self.cfg.get("dashboard_token", "") or "").strip()

    @property
    def machine(self) -> str:
        if self._machine_name:
            return self._machine_name
        import platform
        return platform.node()

    def _headers(self) -> dict[str, str]:
        identity = ""
        if self._identity_token_fn is not None:
            try:
                identity = str(self._identity_token_fn() or "")
            except Exception:
                log.debug("jobs: identity_token_fn failed", exc_info=True)
        return {"Content-Type": "application/json",
                "X-CCSync-Token": self._token,
                "X-CCSync-Identity": identity}

    def _call(self, suffix: str, body: dict) -> tuple[int, Any]:
        request = self._request
        if request is None:
            from .broll_ingest import default_request
            request = default_request
        return request("POST", f"{self._dashboard_url}/api/v1/jobs{suffix}",
                       body, self._headers(), HTTP_TIMEOUT_SECONDS)

    def _claim(self) -> Optional[dict[str, Any]]:
        status, parsed = self._call("/claim", {
            "machine": self.machine,
            "capabilities": self._capabilities(),
            "kinds": self.runnable_kinds()})
        if status != 200 or not isinstance(parsed, dict):
            log.debug("jobs: claim answered HTTP %s", status)
            return None
        return parsed.get("job") or None

    def _heartbeat(self, job_id: int, progress: Optional[float] = None) -> bool:
        """-> keep going. A 410 is the dashboard saying the job is no longer
        ours (the lease expired and somebody else has it, or an admin ended
        it); the answer to all of those is the same one, and it is to stop.

        `progress` is 0..1 or None, and NONE IS NOT ZERO: a recipe with no
        honest fraction to report (a peaks pass reads its input in one gulp)
        sends none, and the fleet chip shows the job id rather than a machine
        that looks stuck at 0%.
        """
        body: dict[str, Any] = {"machine": self.machine}
        if progress is not None:
            body["progress"] = max(0.0, min(1.0, float(progress)))
        status, _parsed = self._call(f"/{int(job_id)}/heartbeat", body)
        if status == 410:
            log.warning("jobs: job #%s is no longer ours -- stopping", job_id)
            return False
        return True

    def _post_result(self, job_id: int, ok: bool, error: str = "",
                     result: Optional[dict] = None, retryable: bool = True) -> None:
        try:
            self._call(f"/{int(job_id)}/result",
                       {"machine": self.machine, "ok": bool(ok),
                        "retryable": bool(retryable), "error": str(error or "")[:2000],
                        "result": result or {}})
        except Exception:
            # The lease expires on its own, so a lost result costs one retry
            # rather than a stuck job. Never fatal to the loop.
            log.exception("jobs: could not post the result of job #%s", job_id)

    # -- the loop --------------------------------------------------------
    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="ccsync-jobs",
                                        daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=5.0)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:
                log.exception("jobs: the runner tick failed")
            self._stop.wait(self.wait_seconds())

    def tick(self) -> Optional[dict[str, Any]]:
        """One pass: claim if allowed, run it, report it. -> the job it ran.

        Synchronous by design. The thread that claims is the thread that runs
        and the thread that answers, so "one job at a time" is a property of
        the code rather than of a flag somebody has to remember to clear.
        """
        state = self._gate()
        with self._lock:
            self._state = state
        if state != STATE_READY:
            return None
        job = self._claim()
        if job is None:
            with self._lock:
                self._state = STATE_NOTHING_OFFERED
                self._offered = []
            return None
        with self._lock:
            self._job = job
            self._state = STATE_RUNNING
        try:
            self._execute(job)
        finally:
            with self._lock:
                self._job = None
                self._state = STATE_NOTHING_OFFERED
        return job

    def _execute(self, job: dict[str, Any]) -> None:
        """Dispatch by kind. ONE place that knows which runner does what, so
        adding a kind is adding a branch here and a capability above, never a
        second loop with its own gate."""
        job_id = int(job["id"])
        kind = str(job.get("kind") or "")
        if kind in jobs_media.MEDIA_KINDS:
            self._execute_media(job)
            return
        if kind != "whisper":
            # Claimed something this build cannot run: hand it straight back,
            # NOT retryable on this machine's account -- the dashboard's own
            # kind filter is what should have stopped it, and a silent retry
            # loop between the two would be invisible.
            self._post_result(job_id, False,
                              f"this companion has no runner for {kind!r} jobs",
                              retryable=False)
            return
        self._execute_whisper(job)

    def _execute_whisper(self, job: dict[str, Any]) -> None:
        job_id = int(job["id"])
        try:
            argv, folder, episode = self._whisper_command(job)
        except job_paths.JobPathError as exc:
            # A path this machine cannot place is not a transient failure, but
            # it IS retryable elsewhere: another machine may have the root.
            log.warning("jobs: job #%s cannot be placed here: %s", job_id, exc)
            self._post_result(job_id, False, str(exc), retryable=True)
            return
        log.info("jobs: job #%s transcribing %s (episode root %s)",
                 job_id, folder, episode)
        started = self._clock()
        ok, output, error = self._run_child(job_id, argv)
        elapsed = round(self._clock() - started, 1)
        if not ok:
            self._post_result(job_id, False, error or "the transcription failed",
                              result={"seconds": elapsed, "output": output},
                              # A CANCELLED JOB IS NOT RETRIED (phase 4): an
                              # admin stopped it, and handing it to the next
                              # idle machine would be the fleet arguing with
                              # a person.
                              retryable=error != CANCELLED_ERROR)
            return
        result = {
            "seconds": elapsed,
            "realtime": _parse_realtime(output),
            # PATHS, not bytes: the files are in the vault, which every
            # machine shares.
            "files": _words_files(episode),
            "output": output,
        }
        self._post_result(job_id, True, result=result)
        if self._notify is not None:
            try:
                self._notify(f"Finished a transcription job for the fleet "
                             f"({elapsed:.0f}s).")
            except Exception:
                log.debug("jobs: notify failed", exc_info=True)

    # -- the media recipes (phase 1) -------------------------------------
    def _execute_media(self, job: dict[str, Any]) -> None:
        """One Timeline Cards recipe, in this process.

        In-process and not a subprocess, unlike whisper: the recipe is ffmpeg
        plus about forty lines of binning, the companion already owns an
        ffmpeg discovery and a `.partial` discipline, and shelling out to a
        second Python would mean a second copy of both.
        """
        job_id = int(job["id"])
        kind = str(job["kind"])
        try:
            source, out_dir, stem, out_root, out_rel = self._media_paths(job)
        except job_paths.JobPathError as exc:
            # A path this machine cannot place is retryable ELSEWHERE: another
            # machine may have the root this one is missing.
            log.warning("jobs: job #%s cannot be placed here: %s", job_id, exc)
            self._post_result(job_id, False, str(exc), retryable=True)
            return
        log.info("jobs: job #%s %s of %s -> %s", job_id, kind, source, out_dir)

        # The heartbeat and the progress it carries. The recipe publishes a
        # fraction about once a second (ffmpeg's -progress stream); the beater
        # sends one every 30, which is what the 300 s lease is sized against.
        latest: dict[str, Any] = {"fraction": None}
        lease_lost = threading.Event()
        finished = threading.Event()

        def on_progress(fraction: Optional[float]) -> None:
            latest["fraction"] = fraction

        cancelled: dict[str, bool] = {"yes": False}

        def should_stop() -> str:
            if self._cancel_requested(job_id):
                cancelled["yes"] = True
                return CANCELLED_ERROR
            if lease_lost.is_set():
                return "the lease was lost"
            if self._halted():
                return "a fleet halt stopped this job"
            if self._stop.is_set():
                return "this computer is shutting down"
            return ""

        def beat() -> None:
            while not finished.wait(HEARTBEAT_SECONDS):
                if not self._heartbeat(job_id, latest["fraction"]):
                    # Sets the flag rather than killing anything itself: the
                    # thread doing the work is the thread that owns the child
                    # and the .partial, and two threads ending one encode is
                    # how a half-written file gets published.
                    lease_lost.set()
                    return

        beater = threading.Thread(target=beat, name="ccsync-jobs-heartbeat",
                                  daemon=True)
        beater.start()
        started = self._clock()
        try:
            recipe = jobs_media.MediaJob(
                ffmpeg_path=str(self.cfg.get("ffmpeg_path", "ffmpeg")),
                # WHAT THIS MACHINE REPORTED, not what it wishes: the
                # capabilities section is `detect_encoders` on this binary, so
                # the argv can never name an encoder this ffmpeg lacks.
                nvenc=bool(self._capabilities().get("nvenc")),
                on_progress=on_progress, should_stop=should_stop,
                clock=self._clock)
            outcome = recipe.run(kind, source, out_dir, stem)
        except jobs_media.MediaJobError as exc:
            finished.set()
            log.warning("jobs: job #%s (%s) failed: %s", job_id, kind, exc)
            self._post_result(job_id, False, str(exc),
                              result={"seconds": round(self._clock() - started, 1)},
                              retryable=(bool(getattr(exc, "retryable", True))
                                         and not cancelled["yes"]))
            return
        except Exception as exc:                                # noqa: BLE001
            finished.set()
            log.exception("jobs: job #%s (%s) raised", job_id, kind)
            self._post_result(job_id, False, str(exc), retryable=True)
            return
        finally:
            finished.set()
        result = dict(outcome)
        # PATHS RELATIVE TO THE OUTPUT ROOT, and the root named beside them
        # (§4.1 applied to the answer): "Script Docs/remote_audio/source/A.m4a"
        # under `vault` means the same thing on every machine, and
        # `X:\...\A.m4a` means it on exactly one.
        result["out_root"] = out_root
        result["files"] = [f"{out_rel}/{name}" if out_rel else name
                           for name in outcome.get("files", [])]
        self._post_result(job_id, True, result=result)

    def _media_paths(
        self, job: dict[str, Any],
    ) -> tuple[Path, Path, str, str, str]:
        """A media job's inputs -> (source, out dir, stem, out root, out rel).

        `out_root`/`out_rel` name the directory the recipe writes into -- for
        Timeline Cards that is `<episode>/Script Docs/remote_audio/source` for
        the extractions and the proxies, and `.../remote_audio` for the peaks.
        The SUBMITTER decides which, because it is the page that knows where
        it will look.

        `out_stem` is the name the page uses for this clip (its multicam
        name), which is NOT always the media file's own stem -- and defaulting
        to the file's stem is right for everything else.
        """
        inputs = job.get("inputs") or {}
        root = str(inputs.get("root") or "media")
        source = job_paths.resolve(self.cfg, root, str(inputs.get("rel_path") or ""))
        out_root = str(inputs.get("out_root") or root)
        out_rel = str(inputs.get("out_rel") or "").strip().replace("\\", "/").strip("/")
        if not out_rel:
            raise job_paths.JobPathError(
                "a media job must name the directory its output goes in "
                "(out_root + out_rel) -- nothing here guesses where a cache "
                "belongs in somebody's vault")
        out_dir = job_paths.resolve(self.cfg, out_root, out_rel)
        stem = str(inputs.get("out_stem") or "").strip() or source.stem
        return source, out_dir, stem, out_root, out_rel

    def _whisper_command(self, job: dict[str, Any]) -> tuple[list[str], Path, Path]:
        """The exact command the corpus stage documents:

            <whisper venv python> <checkout>/pipeline.py transcribe
                --folder <dir> --root <episode root> [--speakers]

        Both paths are resolved from (root, rel_path) pairs HERE, on the
        machine that will open them (§4.1). `episode_rel` defaults to the
        folder's own root when a submitter omits it, because the corpus stage
        requires one and refusing the job would be the less useful answer.
        """
        inputs = job.get("inputs") or {}
        root = str(inputs.get("root") or "vault")
        folder = job_paths.resolve(self.cfg, root, str(inputs.get("rel_path") or ""))
        episode_rel = str(inputs.get("episode_rel") or "").strip()
        episode = (job_paths.resolve(self.cfg, root, episode_rel) if episode_rel
                   else folder.parent)
        python = str(self.cfg.get("jobs_whisper_python", "") or "").strip()
        checkout = Path(str(self.cfg.get("jobs_mulcam_pipeline", "") or "").strip())
        if not python or not checkout.name:
            raise job_paths.JobPathError(
                "this machine has no whisper venv or MulticamPipeline checkout "
                "configured (jobs_whisper_python / jobs_mulcam_pipeline)")
        argv = [python, str(checkout / "pipeline.py"), "transcribe",
                "--folder", str(folder), "--root", str(episode)]
        if inputs.get("speakers"):
            argv.append("--speakers")
        return argv, folder, episode

    def _run_child(self, job_id: int, argv: list[str]) -> tuple[bool, str, str]:
        """Run the pipeline, heartbeating while it works.

        -> (ok, output tail, error). The child is terminated when the lease is
        lost, when a fleet halt arrives, or when the companion is shutting
        down -- and NOT when the editor comes back (see the module docstring).
        """
        try:
            proc = self._runner(
                argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
                creationflags=_win_creationflags())
        except Exception as exc:                                    # noqa: BLE001
            log.exception("jobs: could not start the transcription")
            return False, "", f"could not start the transcription: {exc}"
        last_beat = self._clock()
        chunks: list[str] = []
        try:
            while True:
                try:
                    out, _err = proc.communicate(timeout=HEARTBEAT_SECONDS)
                    if out:
                        chunks.append(out)
                    break
                except subprocess.TimeoutExpired:
                    pass
                now = self._clock()
                if now - last_beat >= HEARTBEAT_SECONDS:
                    last_beat = now
                    if not self._heartbeat(job_id):
                        _terminate(proc)
                        return False, _tail(chunks), "the lease was lost"
                if self._cancel_requested(job_id):
                    log.warning("jobs: job #%s was cancelled -- stopping the child",
                                job_id)
                    _terminate(proc)
                    return False, _tail(chunks), CANCELLED_ERROR
                if self._halted():
                    log.warning("jobs: a fleet halt arrived -- stopping job #%s",
                                job_id)
                    _terminate(proc)
                    return False, _tail(chunks), "a fleet halt stopped this job"
                if self._stop.is_set():
                    _terminate(proc)
                    return False, _tail(chunks), "this computer is shutting down"
        except Exception as exc:                                    # noqa: BLE001
            log.exception("jobs: the transcription child failed")
            _terminate(proc)
            return False, _tail(chunks), str(exc)
        code = proc.returncode
        output = _tail(chunks)
        if code == 0:
            return True, output, ""
        return False, output, f"pipeline.py transcribe exited {code}"


def _terminate(proc: Any) -> None:
    """Stop the child, and do not hang waiting for it to agree."""
    try:
        proc.terminate()
        proc.wait(timeout=10)
    except Exception:
        try:
            proc.kill()
        except Exception:
            log.debug("jobs: could not kill the child", exc_info=True)


def _tail(chunks: list[str]) -> str:
    return "".join(chunks)[-OUTPUT_TAIL_CHARS:]


def _parse_realtime(output: str) -> Optional[float]:
    """The corpus stage's own "11.4x realtime overall" figure, or None.

    Reported because it is the one number that says whether handing this work
    to another machine was worth it -- and None when the line is not there,
    rather than a zero that would average into a lie.
    """
    matches = _REALTIME_RE.findall(output or "")
    if not matches:
        return None
    try:
        return float(matches[-1])
    except (TypeError, ValueError):
        return None


def _words_files(episode: Path, limit: int = 200) -> list[str]:
    """The `<stem>_words.json` sidecars under this episode's Clips folder,
    relative to the episode root.

    Paths RELATIVE to the root, for the same reason a job's inputs are: an
    absolute path in a result row is one that means something different on
    every machine that reads it later.
    """
    try:
        clips = episode / "Clips"
        if not clips.is_dir():
            return []
        found = sorted(str(p.relative_to(episode)).replace("\\", "/")
                       for p in clips.glob("*/*_words.json"))
        return found[:limit]
    except Exception:
        log.debug("jobs: could not list the sidecars", exc_info=True)
        return []


def _win_creationflags() -> int:
    """CREATE_NO_WINDOW on Windows: an unflagged child flashes a console on
    the editor's desktop, which is what broll_vlm_sidecar._runner exists to
    avoid too."""
    try:
        return int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception:
        return 0
