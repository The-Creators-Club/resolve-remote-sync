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
  * **THE IDLE GATE CAN BE OPENED, BY A PERSON, TWO WAYS** (§10, 2026-08-30)
    -- and by nobody else. The one AT the machine can `volunteer()` it for
    half an hour from the tray, and an admin can mark a JOB forced, which this
    loop will claim by id with the editor present. Neither opens anything
    above them: a halt, an update, a tripped breaker, `jobs_enabled = false`
    and this machine's own kind list all still refuse. "Force" means "do not
    wait for anybody to leave", never "run on a machine that cannot".
  * **NOTHING HERE TOUCHES RESOLVE'S SCRIPTING API** (CR-68). The only
    Resolve question asked is whether the process is running, through
    resolve_prefs, which fails closed.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from . import config as config_mod
from . import job_paths, jobs_media

log = logging.getLogger("ccsync.jobs")

# Gate states, in the order _gate() asks them. The diagnostics bundle, the log
# and -- since the 2026-09-04 sweep (CMEDIA-12) -- `status()["gate"]` render
# these, which is what "why is this machine not taking any work" is answered
# with on the machine itself.
STATE_DISABLED = "disabled"
STATE_NO_DASHBOARD = "no_dashboard"
STATE_HALTED = "halted"
STATE_NO_CAPABILITY = "no_capability"
# THE THIRD GPU CONSUMER (CMEDIA-1, sweep 2026-09-03). The b-roll and music
# ingestors and the proxy generator already negotiate over this machine's GPU
# through `blocked_fn` ("indexing beats proxy generation"); the job runner was
# outside that agreement, and its gate opens on the same event theirs do
# (`_user_is_away`). So the common case was a whisper job claimed onto a
# machine already holding 8-12 GB of VLM weights: an OOM or a crawl, reported
# as a job failure, which then earned the machine the dashboard's per-machine
# cooldown for a fault it did not have.
STATE_LOCAL_WORK = "local_work"
STATE_RUNNING = "running"
STATE_USER_ACTIVE = "user_active"
STATE_RESOLVE_OPEN = "resolve_open"
STATE_NOTHING_OFFERED = "nothing_offered"
STATE_READY = "ready"
# A job that ran THROUGH a closed gate (§10, 2026-08-30): the admin marked it
# forced, or the person here volunteered. Reported by status() while it runs so
# the tray and the diagnostics can say why work started with somebody at the
# keyboard, instead of looking like the idle gate had failed.
STATE_FORCED = "forced"

# THE GATE IN WORDS (CMEDIA-12, sweep 2026-09-04). One sentence per state, in
# the second person, because the reader is the editor whose machine is quietly
# doing nothing (or quietly doing something). `taking_work` is "is anything
# here stopping this computer", NOT "is a job running": a machine nobody has
# offered work to is taking work, it just has none.
#
# The dashboard's own reasons (a per-machine cooldown after a failure, the
# per-kind fleet cap) never reach this side -- they show up here as an empty
# offer list, which is why the nothing-offered sentence says who is quiet
# rather than claiming the queue is empty.
GATE_SENTENCES: dict[str, tuple[bool, str]] = {
    STATE_DISABLED: (
        False, "Fleet jobs are switched off on this computer."),
    STATE_NO_DASHBOARD: (
        False, "This computer is not signed in to the dashboard, so the fleet "
               "has no way to give it work."),
    STATE_HALTED: (
        False, "Your admin has stopped syncing for the whole fleet, so this "
               "computer is not taking work of any kind."),
    STATE_NO_CAPABILITY: (
        False, "This computer is not set up for any of the kinds of work the "
               "fleet queues."),
    STATE_LOCAL_WORK: (
        False, "This computer is busy with your own work, so it is not taking "
               "fleet work."),
    STATE_USER_ACTIVE: (
        False, "Somebody is at this computer, so it is not taking fleet work."),
    STATE_RESOLVE_OPEN: (
        False, "Resolve is open here, so this computer is not taking fleet "
               "work."),
    STATE_RUNNING: (True, "This computer is running a fleet job."),
    STATE_FORCED: (
        True, "Your admin asked this computer to run a fleet job now."),
    STATE_READY: (True, "This computer is ready for fleet work."),
    STATE_NOTHING_OFFERED: (
        True, "This computer is ready for fleet work. The dashboard has not "
              "offered it any."),
}
# What `current["forced_reason"]` says (CMEDIA-13). The state existed from
# phase 1 precisely so somebody could be told why work started with them at
# the keyboard, and until this sweep nothing read it.
FORCED_BY_ADMIN = ("Your admin asked this computer to run this job now, "
                   "without waiting for you to step away.")
FORCED_BY_VOLUNTEER = ("You lent this computer to the fleet, so it took this "
                       "job while you are here.")

# The last few jobs this machine ran, so the answer to "what did my computer
# do for the team" survives a restart (CMEDIA-2). proxy_history.py's posture
# in one small file: bookkeeping bolted onto the work, never able to fail it.
RECENT_FILENAME = "jobs_recent.json"
RECENT_MAX = 10

HTTP_TIMEOUT_SECONDS = 20.0
# The dashboard's lease is 300 s (db.JOB_LEASE_SECONDS). Beat every 30, so a
# beat that cannot be DELIVERED costs a tenth of the lease and nothing else:
# `_heartbeat` treats a transport failure as a blip and keeps working, and the
# lease running out at the dashboard is the backstop (bug-hunt-2026-09-03
# comp-ytdl-jobs-1). Only a 410 -- the dashboard saying the job is not ours
# any more -- stops the work.
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
# THE EARLY HEARTBEAT (§10, 2026-08-30). A whisper pass is minutes long and
# the 30 s beat is sized against the lease, not against a progress bar -- so a
# beat also goes out as soon as the fraction has really moved (1 %) and the
# last one is at least 5 s old. Both halves matter: without the step a file
# that finishes in 4 s would send a beat per line, and without the floor a long
# file would leave the chip frozen for half a minute.
PROGRESS_STEP = 0.01
PROGRESS_MIN_SECONDS = 5.0
# How many of the child's lines are kept while it runs. The tail that rides the
# result is measured in CHARACTERS (OUTPUT_TAIL_CHARS); this is only the bound
# on the list the drain thread appends to, so a pipeline that prints a line a
# millisecond cannot grow the companion's heap.
OUTPUT_TAIL_LINES = 2000
# "(12 written, 0 failed, 3 skipped) (41.2 min audio in 3.6 min, 11.4x
# realtime overall)" -- whisper_corpus's own summary line.
_REALTIME_RE = re.compile(r"([0-9.]+)x realtime")
# THE THREE LINES whisper_corpus.py actually prints, and nothing else (§10.4).
# Copied from its own format strings ("%d media file(s), %d already
# transcribed, %d to do", "[%d/%d] %s", "        %.0fs / %.0fs", "done: ...")
# so a line that merely looks similar -- the per-file "lang=zh 41s audio in
# 3.6s" summary sits at the same indent as the progress line -- cannot be read
# as progress.
_WHISPER_TOTAL_RE = re.compile(
    r"^(\d+) media file\(s\), (\d+) already transcribed, (\d+) to do\s*$")
_WHISPER_FILE_RE = re.compile(r"^\[(\d+)/(\d+)\] ")
_WHISPER_AT_RE = re.compile(r"^\s+([0-9.]+)s / ([0-9.]+)s\s*$")
_WHISPER_DONE_RE = re.compile(r"^done: \d+ transcribed")


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
        blocked_fn: Optional[Callable[[], Any]] = None,
        machine_name: str = "",
        runner_fn: Optional[Callable[..., Any]] = None,
        clock: Callable[[], float] = time.monotonic,
        notify: Optional[Callable[[str], None]] = None,
        recent_path: Optional[Path] = None,
    ) -> None:
        self.cfg = cfg or {}
        self._request = request_fn
        self._editor_fn = editor_fn
        self._identity_token_fn = identity_token_fn
        self._capabilities_fn = capabilities_fn
        self._idle_probe = idle_probe
        self._resolve_running_fn = resolve_running_fn
        self._halted_fn = halted_fn
        # CMEDIA-1: the same seam ProxyGenerator and the ingestors carry.
        # False/None = nothing local in the way; a STRING = the sentence for
        # what is (and True with no words, for a caller that has none).
        self._blocked_fn = blocked_fn
        self._machine_name = machine_name
        self._runner = runner_fn or subprocess.Popen
        self._clock = clock
        self._notify = notify

        self.enabled = bool(self.cfg.get("jobs_enabled", True))
        self.idle_seconds = config_mod.coerce_numeric(self.cfg, "jobs_idle_seconds", 300)
        self.skip_while_resolve = bool(
            self.cfg.get("jobs_skip_while_resolve_running", True))
        self.poll_seconds = config_mod.coerce_numeric(self.cfg, "jobs_poll_seconds", 20)
        # How long one click of the tray's "take fleet jobs now" lasts (§10).
        self.volunteer_minutes = config_mod.coerce_numeric(
            self.cfg, "jobs_volunteer_minutes", 30)

        self._lock = threading.Lock()
        self._offered: list[int] = []
        # THE QUEUE DEPTH THE DASHBOARD LAST REPORTED (phase 4): {queued,
        # running, pinned, oldest_age_s}, or {} from a dashboard too old to
        # send one. It is not an instruction -- the offers are -- it is what
        # lets this loop stop asking a fleet that has nothing to give.
        self._queue: dict[str, Any] = {}
        self._cancel: list[int] = []
        # THE IDS AN ADMIN SUBMITTED WITH `--now` (§10). An offer this machine
        # may claim even with somebody at the keyboard -- and only those ids,
        # which is why `_claim_ids` exists: a forced claim must not be able to
        # pick up the ordinary job that happened to be offered beside it.
        self._forced: list[int] = []
        self._claim_ids: Optional[list[int]] = None
        # The person AT this machine saying "use it now" -- a monotonic
        # deadline for the gate, and a wall-clock copy for the report (the
        # dashboard cannot read another machine's monotonic clock).
        self._volunteer_until: Optional[float] = None
        self._volunteer_until_iso: Optional[str] = None
        self._job: Optional[dict[str, Any]] = None
        # What the tray and Settings show while a job runs (CMEDIA-2/13): the
        # id, the kind, the file in this editor's own words, when it started
        # and -- when it started with them present -- who asked for that.
        self._current: Optional[dict[str, Any]] = None
        self._state = STATE_NOTHING_OFFERED
        # The extra clause the no-capability sentence needs. Recorded where the
        # capabilities are already in hand, because status() must stay zero-I/O
        # (it is called from the tray's refresh thread).
        self._gate_note = ""
        # Written at every result and read at construction, so "what has this
        # machine run" outlives a restart (CMEDIA-2). Derived from the log path
        # rather than passed in: app.py builds this runner and nothing else
        # knows where its state dir is.
        self._recent_path = (Path(recent_path) if recent_path is not None
                             else _default_recent_path(self.cfg))
        self._recent: list[dict[str, Any]] = _load_recent(self._recent_path)
        # THE WAKE (bug-hunt-2026-09-03 comp-ytdl-jobs-3). The backoff can put
        # this loop to sleep for IDLE_BACKOFF_MAX_SECONDS, so an offer landing
        # on the report reply -- including an admin's forced [ RUN NOW ] --
        # would otherwise wait up to two minutes for a machine that is doing
        # nothing. `note_report_reply` sets it, `_loop` waits on it beside the
        # timeout, and `stop()` sets it too so a shutdown is not held up by a
        # backed-off sleep.
        self._wake = threading.Event()
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
            forced = block.get("forced")
            urgent = [int(i) for i in forced] if isinstance(forced, list) else []
            queue = block.get("queue")
            depth = dict(queue) if isinstance(queue, dict) else {}
        except (TypeError, ValueError):
            log.debug("jobs: unreadable offer block", exc_info=True)
            return
        with self._lock:
            self._offered = ids[:16]
            self._queue = depth
            self._cancel = stops[:16]
            self._forced = urgent[:16]
        if ids or urgent:
            # Work to claim: wake the loop now rather than at the end of a
            # backoff sleep (comp-ytdl-jobs-3). A cancel needs no wake -- the
            # thread that would act on it is already inside the job.
            self._wake.set()

    # -- volunteering (§10, 2026-08-30) -----------------------------------
    def volunteer(self, minutes: Optional[float] = None) -> Optional[str]:
        """The person AT this machine lending it to the fleet for a while.

        -> the ISO deadline, or None when it was switched off. `None` minutes
        means the configured default (`jobs_volunteer_minutes`, 30); `0`
        clears it. A TIMER and not a toggle deliberately: somebody who lends
        their machine and then walks away should get it back without having to
        remember they lent it.
        """
        try:
            value = self.volunteer_minutes if minutes is None else float(minutes)
        except (TypeError, ValueError):
            value = self.volunteer_minutes
        with self._lock:
            if value <= 0:
                self._volunteer_until = None
                self._volunteer_until_iso = None
                log.info("jobs: no longer volunteering -- back to the idle gate")
                return None
            self._volunteer_until = self._clock() + value * 60.0
            self._volunteer_until_iso = (
                datetime.now(timezone.utc) + timedelta(minutes=value)
            ).replace(microsecond=0).isoformat()
            log.info("jobs: volunteering for the next %.0f minutes (until %s)",
                     value, self._volunteer_until_iso)
            return self._volunteer_until_iso

    @property
    def volunteering(self) -> bool:
        with self._lock:
            return self._volunteering_locked()

    @property
    def volunteer_until_iso(self) -> Optional[str]:
        """The wall-clock deadline the capabilities section carries, or None.

        Reads through the same expiry check as the gate, so a report can never
        tell the dashboard this machine is volunteering after the timer here
        has run out."""
        with self._lock:
            return self._volunteer_until_iso if self._volunteering_locked() else None

    def _volunteering_locked(self) -> bool:
        """Caller holds `_lock`. Expiring CLEARS both copies, so the answer and
        what the report says cannot drift apart."""
        deadline = self._volunteer_until
        if deadline is None:
            return False
        if self._clock() >= deadline:
            self._volunteer_until = None
            self._volunteer_until_iso = None
            log.info("jobs: the volunteer window has run out -- back to the idle gate")
            return False
        return True

    def status(self) -> dict[str, Any]:
        """Zero-I/O snapshot for the log, the diagnostics bundle and the
        tray.

        ZERO-I/O IS A REQUIREMENT, not a description: the tray's refresh thread
        calls this, and on the win32 backend any I/O here stalls the message
        loop (the right-click freeze of 2026-07-26). So `gate` is the verdict
        the LAST tick reached, never a fresh evaluation -- which is also the
        honest thing to report, because it is the verdict the claim was made
        under (CMEDIA-12).
        """
        with self._lock:
            job = dict(self._job) if self._job else None
            current = dict(self._current) if self._current else None
            volunteer = (self._volunteer_until_iso
                         if self._volunteering_locked() else None)
            state, note = self._state, self._gate_note
            recent = [dict(item) for item in self._recent]
        taking, sentence = GATE_SENTENCES.get(
            state, (False, "This computer is not taking fleet work."))
        if note:
            sentence = f"{sentence} {note}"
        if state == STATE_USER_ACTIVE:
            sentence = (f"{sentence} It waits for "
                        f"{_minutes(self.idle_seconds)} of quiet.")
        return {"state": state, "offered": list(self._offered),
                "queue": dict(self._queue),
                "volunteer_until": volunteer, "forced": list(self._forced),
                "gate": {"taking_work": bool(taking), "reason": sentence},
                "current": current,
                "recent": recent,
                "job": {"id": job["id"], "kind": job["kind"]} if job else None}

    def stop_current(self) -> bool:
        """The person at this machine stopping the job it is running for the
        fleet (CMEDIA-2). -> was there a job to stop.

        THE ADMIN'S CANCEL PATH, REUSED WHOLE. The id goes on the same
        `_cancel` list `commands.jobs.cancel` fills, so the thread that owns
        the child and the `.partial` is the thread that ends them -- exactly
        one place terminates a job, and it is the one that has been tested
        against a half-written proxy reaching the vault. The result goes back
        as cancelled and NOT retryable (CANCELLED_ERROR), because another
        machine picking up work a person just stopped is the one outcome
        nobody asked for.

        Returns as soon as the stop is REQUESTED: the child gets up to a
        heartbeat slice to die, and a button that blocks the tray for five
        seconds is a button that looks broken.
        """
        with self._lock:
            job = dict(self._job) if self._job else None
            if job is None:
                return False
            job_id = int(job["id"])
            if job_id not in self._cancel:
                self._cancel.append(job_id)
                del self._cancel[:-16]
        log.warning("jobs: the person at this machine stopped job #%s", job_id)
        return True

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

        AN ABSENT DEPTH IS THE BASE CADENCE, deliberately: it means a
        dashboard too old to send one, and a dashboard deployed behind the
        companions must not read as "nothing to do for two minutes". Until
        2026-09-03 that was also the shape a dashboard with an EMPTY queue
        sent (it omitted the block entirely), so the backoff below was
        unreachable in the fleet -- the dashboard now always sends the full
        depth, zeros included, to a companion that can run jobs
        (bug-hunt-2026-09-03 comp-ytdl-jobs-3). The sleep is interruptible
        (`_wake`), so backing off never delays a new offer.
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

    def _local_work_reason(self) -> str:
        """What work of the editor's own is using this computer, or "".

        Fails CLOSED like `_halted` and `_resolve_running` above: a seam that
        cannot answer must not read as "the GPU is free"."""
        if self._blocked_fn is None:
            return ""
        try:
            answer = self._blocked_fn()
        except Exception:
            log.debug("jobs: blocked_fn failed", exc_info=True)
            return "Something here could not be asked whether it is busy."
        if not answer:
            return ""
        text = str(answer).strip() if not isinstance(answer, bool) else ""
        return text or "Work of your own is running here."

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
        # ...AND THIS MACHINE'S OWN ALLOW-LIST (phase 4), from the same
        # capabilities section the scheduler filtered on, so the two answers
        # cannot disagree. Empty is every kind. Honoured on BOTH sides
        # deliberately: the dashboard's filter is what stops the offer, and
        # this is what stops a stale offer being acted on by a machine whose
        # owner has since changed their mind.
        allowed = [str(k) for k in (caps.get("job_kinds") or [])]
        if allowed:
            kinds = [k for k in kinds if k in allowed]
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
            # WHICH of the two no-capability shapes this is (CMEDIA-12): a
            # machine with no ffmpeg and no whisper venv needs a set-up, a
            # machine whose owner narrowed `[jobs] kinds` to something it
            # cannot do needs a config line changed, and the states are one.
            # Recorded here because the capabilities are already in hand and
            # status() may do no I/O.
            allowed = [str(k) for k in (self._capabilities().get("job_kinds") or [])]
            self._gate_note = (
                f"It is set to take only: {', '.join(allowed)}."
                if allowed else
                "There is no whisper set-up here, and no ffmpeg for the "
                "media jobs.")
            return STATE_NO_CAPABILITY
        # CMEDIA-1: ABOVE the two gates a person can open, deliberately.
        # Indexing beats proxy generation for the reason it beats fleet work:
        # it is the thing the person here is waiting on, and it needs the same
        # GPU. A volunteer click is not consent to run two GPU jobs at once.
        local = self._local_work_reason()
        if local:
            self._gate_note = local
            return STATE_LOCAL_WORK
        self._gate_note = ""
        # THE TWO GATES A PERSON CAN OPEN (§10, 2026-08-30), and only these
        # two: what comes above is capability and safety, and neither a
        # volunteer nor an admin's `--now` is allowed past those.
        blocked = ""
        if not self.volunteering:
            if not self._user_is_away():
                blocked = STATE_USER_ACTIVE
            elif self.skip_while_resolve and self._resolve_running():
                blocked = STATE_RESOLVE_OPEN
        if blocked:
            with self._lock:
                forced = [i for i in self._forced if i in self._offered]
            if not forced:
                return blocked
            # ONLY THESE IDS. The claim carries them, so a machine whose gate
            # is shut cannot pick up the ordinary job that happened to be
            # offered in the same reply.
            log.info("jobs: claiming forced job #%s with somebody at the keyboard",
                     forced[0])
            with self._lock:
                self._claim_ids = forced
            return STATE_READY
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
        body: dict[str, Any] = {
            "machine": self.machine,
            "capabilities": self._capabilities(),
            "kinds": self.runnable_kinds()}
        with self._lock:
            ids, self._claim_ids = self._claim_ids, None
        if ids:
            # A CLOSED GATE CLAIMING ANYWAY (§10): the dashboard intersects
            # this list with what it would have offered, so naming ids can
            # only ever narrow what comes back, never widen it.
            body["ids"] = list(ids)
        status, parsed = self._call("/claim", body)
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

        A TRANSPORT FAILURE IS A BLIP, NOT A VERDICT (bug-hunt-2026-09-03
        comp-ytdl-jobs-1, and it is CR-31's shape): `default_request` RAISES
        on a refused connection or a DNS wobble, and this used to let that
        raise out into `_run_child`'s catch-all, which terminated the child and
        handed the job back as a retryable failure. One dashboard deploy
        (stage-verify-swap, ~3 s) therefore threw away every whisper pass in
        the fleet at once and cooled down the machines that had done the work.
        A beat that could not be delivered is no evidence the lease is gone,
        and the lease expiring is already the backstop, so the answer is to
        keep going. `ytdl_executor.DownloadJob._heartbeat_loop` learned this
        first.
        """
        body: dict[str, Any] = {"machine": self.machine}
        if progress is not None:
            body["progress"] = max(0.0, min(1.0, float(progress)))
        try:
            status, _parsed = self._call(f"/{int(job_id)}/heartbeat", body)
        except Exception:                                       # noqa: BLE001
            log.info("jobs: a heartbeat for job #%s did not get through -- "
                     "carrying on", job_id)
            log.debug("jobs: heartbeat transport failure", exc_info=True)
            return True
        if status == 410:
            log.warning("jobs: job #%s is no longer ours -- stopping", job_id)
            return False
        return True

    def _post_result(self, job_id: int, ok: bool, error: str = "",
                     result: Optional[dict] = None, retryable: bool = True) -> None:
        # RECORDED BEFORE IT IS SENT (CMEDIA-2): a result the dashboard never
        # received is exactly the case where the editor's own machine is the
        # only place that can say what happened.
        self._note_finished(job_id, ok, error)
        try:
            self._call(f"/{int(job_id)}/result",
                       {"machine": self.machine, "ok": bool(ok),
                        "retryable": bool(retryable), "error": str(error or "")[:2000],
                        "result": result or {}})
        except Exception:
            # The lease expires on its own, so a lost result costs one retry
            # rather than a stuck job. Never fatal to the loop.
            log.exception("jobs: could not post the result of job #%s", job_id)

    def _note_finished(self, job_id: int, ok: bool, error: str) -> None:
        """One line in the ledger the editor reads (CMEDIA-2). Never raises:
        this is bookkeeping bolted onto the work, and a state dir that cannot
        be written must not fail a transcode that succeeded."""
        try:
            with self._lock:
                current = dict(self._current) if self._current else {}
                if int(current.get("id") or 0) != int(job_id):
                    current = {}
                entry = {
                    "id": int(job_id),
                    "kind": str(current.get("kind") or ""),
                    "rel_path": str(current.get("rel_path") or ""),
                    # The three words the panel renders. `cancelled` is its own
                    # outcome and not a failure: somebody chose it.
                    "outcome": ("cancelled" if str(error) == CANCELLED_ERROR
                                else "done" if ok else "failed"),
                    "error": "" if ok else str(error or "")[:300],
                    "finished_at": _now_iso(),
                }
                self._recent.insert(0, entry)
                del self._recent[RECENT_MAX:]
                snapshot = [dict(item) for item in self._recent]
            _save_recent(self._recent_path, snapshot)
        except Exception:
            log.debug("jobs: could not record the finished job", exc_info=True)

    # -- the loop --------------------------------------------------------
    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._wake.clear()
        self._thread = threading.Thread(target=self._loop, name="ccsync-jobs",
                                        daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=5.0)

    def _loop(self) -> None:
        while not self._stop.is_set():
            # Cleared BEFORE the tick, so an offer that lands while this tick
            # is running is still a wake and not a lost one (comp-ytdl-jobs-3).
            self._wake.clear()
            try:
                self.tick()
            except Exception:
                log.exception("jobs: the runner tick failed")
            if self._stop.is_set():
                break
            self._wake.wait(self.wait_seconds())

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
        with self._lock:
            # Read before the claim clears it: what the state says while this
            # job runs is how the tray explains a job that started with the
            # editor present.
            forced_claim = bool(self._claim_ids)
        job = self._claim()
        if job is None:
            with self._lock:
                self._state = STATE_NOTHING_OFFERED
                self._offered = []
            return None
        volunteering = self.volunteering
        with self._lock:
            self._job = job
            self._state = STATE_FORCED if forced_claim else STATE_RUNNING
            # THE JOB IN THE EDITOR'S OWN TERMS (CMEDIA-2/13). `rel_path` and
            # not the resolved path: the vault is a drive letter here and a
            # mount there, and the relative half is the half that reads the
            # same everywhere (§4.1).
            self._current = {
                "id": int(job["id"]),
                "kind": str(job.get("kind") or ""),
                "rel_path": str((job.get("inputs") or {}).get("rel_path") or ""),
                "started_at": _now_iso(),
                "forced_reason": (FORCED_BY_ADMIN if forced_claim
                                  else FORCED_BY_VOLUNTEER if volunteering
                                  else None),
            }
        try:
            self._execute(job)
        finally:
            with self._lock:
                self._job = None
                self._current = None
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
            # A THREAD WHOSE ONLY JOB IS LIVENESS MUST NOT BE KILLABLE BY
            # ANYTHING IT CALLS (bug-hunt-2026-09-03 comp-ytdl-jobs-2).
            # `_heartbeat` swallows transport failures itself now, but this
            # belt stays: a raise here ends the thread permanently, nothing
            # sets `lease_lost`, `should_stop()` never learns, the encode runs
            # on with an expired lease, and in a frozen windowed build the
            # excepthook's traceback goes to a stderr that does not exist. The
            # loop keeps beating rather than returning, because one bad beat
            # is not a reason to stop reporting for the rest of the job.
            while not finished.wait(HEARTBEAT_SECONDS):
                try:
                    alive = self._heartbeat(job_id, latest["fraction"])
                except Exception:                               # noqa: BLE001
                    log.debug("jobs: the heartbeat for job #%s raised",
                              job_id, exc_info=True)
                    continue
                if not alive:
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
                "this computer has no whisper venv or MulticamPipeline checkout "
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

        The stdout is read on a DRAIN THREAD (§10, 2026-08-30), the shape
        jobs_media._drain_progress already uses. It used to ride
        `communicate(timeout=...)`, which buffers the whole run and hands it
        over at exit -- so the pipeline's own "[3/12] ..." lines existed and
        nobody could see them until the transcription was over, and the fleet
        chip had nothing to show for twenty minutes.
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
        progress: dict[str, Any] = {}
        latest: dict[str, Optional[float]] = {"fraction": None}
        sent: Optional[float] = None

        def feed(line: str) -> None:
            chunks.append(line + "\n")
            del chunks[:-OUTPUT_TAIL_LINES]
            fraction = whisper_progress(line, progress)
            if fraction is not None:
                latest["fraction"] = fraction

        reader: Optional[threading.Thread] = None
        if getattr(proc, "stdout", None) is not None:
            reader = threading.Thread(target=_drain_lines, args=(proc.stdout, feed),
                                      name="ccsync-jobs-stdout", daemon=True)
            reader.start()
        try:
            while True:
                try:
                    # In slices, so a cancel, a halt and a shutdown are all
                    # noticed while the child runs -- and short enough that the
                    # early progress beat below can actually be early.
                    proc.wait(timeout=max(0.1, min(HEARTBEAT_SECONDS,
                                                   PROGRESS_MIN_SECONDS)))
                    break
                except subprocess.TimeoutExpired:
                    pass
                now = self._clock()
                fraction = latest["fraction"]
                moved = (fraction is not None
                         and (sent is None or abs(fraction - sent) >= PROGRESS_STEP)
                         and (now - last_beat) >= PROGRESS_MIN_SECONDS)
                if now - last_beat >= HEARTBEAT_SECONDS or moved:
                    last_beat = now
                    sent = fraction
                    if not self._heartbeat(job_id, fraction):
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
        if reader is not None:
            # The last lines the child wrote as it exited, including its own
            # summary -- _parse_realtime reads them off the tail below.
            reader.join(timeout=5.0)
        code = proc.returncode
        output = _tail(chunks)
        if code == 0:
            # A RUN WITH NOTHING TO DO ends at 1.0 (§10.4): the pipeline prints
            # its "0 to do" line and exits without ever naming a file, and a
            # chip left at "unknown" for a job that succeeded reads as wedged.
            if progress.get("total") == 0 and latest["fraction"] is None:
                self._heartbeat(job_id, 1.0)
            return True, output, ""
        return False, output, f"pipeline.py transcribe exited {code}"


def _now_iso() -> str:
    """UTC, to the second. The tray renders it as "4 min ago"; the file has to
    stay readable a week later on another machine's clock."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _minutes(seconds: Any) -> str:
    """"5 minutes" / "30 seconds" -- the idle floor as a person says it."""
    try:
        value = float(seconds or 0)
    except (TypeError, ValueError):
        return "a few minutes"
    if value >= 120:
        return f"{value / 60:.0f} minutes"
    if value >= 60:
        return "a minute"
    return f"{value:.0f} seconds"


def _default_recent_path(cfg: dict[str, Any]) -> Optional[Path]:
    """`~/.ccsync/state/jobs_recent.json`, beside every other latch the
    companion keeps across restarts. None when even that cannot be worked out,
    which leaves the ledger in memory rather than failing the runner.

    A cfg with NO `log_path` gets None rather than the packaged default: a
    loaded config always carries one (config.DEFAULTS fills it), so the only
    callers without one are harnesses, and a suite must not write into the
    state dir of whoever is running it."""
    if not str((cfg or {}).get("log_path") or "").strip():
        return None
    try:
        return config_mod.resolved_log_path(cfg or {}).parent / "state" / RECENT_FILENAME
    except Exception:
        log.debug("jobs: no state dir for the recent-jobs ledger", exc_info=True)
        return None


def _load_recent(path: Optional[Path]) -> list[dict[str, Any]]:
    """Never raises, and never lets a corrupt file be why the runner will not
    build: an unreadable ledger is an empty one."""
    if path is None:
        return []
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except Exception:
        log.debug("jobs: the recent-jobs ledger could not be read", exc_info=True)
        return []
    items = data.get("jobs") if isinstance(data, dict) else data
    if not isinstance(items, list):
        return []
    return [dict(item) for item in items if isinstance(item, dict)][:RECENT_MAX]


def _save_recent(path: Optional[Path], items: list[dict[str, Any]]) -> None:
    """Whole-file rewrite through a temp name, proxy_totals.json's shape: the
    file is tiny and a half-written one would be read at the next start."""
    if path is None:
        return
    try:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".tmp")
        tmp.write_text(json.dumps({"jobs": items}, indent=2), encoding="utf-8")
        os.replace(tmp, target)
    except Exception:
        log.debug("jobs: could not write %s", path, exc_info=True)


def whisper_progress(line: str, state: dict[str, Any]) -> Optional[float]:
    """One line of `pipeline.py transcribe` output -> how far through it is.

    A PURE FUNCTION over a caller-owned `state` dict, so the whole thing is
    testable with a list of strings and no subprocess. -> the new fraction, or
    None when this line says nothing about progress -- and None is NOT zero
    (db.clamp_progress's rule, the same one jobs_media._Progress obeys): a
    machine reported at 0 % looks stuck, a machine reported as unknown shows
    its job id and looks busy, which is the truth until the first file starts.

    Per FILE with a linear guess inside it, which is all the pipeline offers:
    the diarize pass after the last file shows as 100 % for its duration
    (§10.5). Good enough to tell working from wedged.
    """
    if not line:
        return None
    match = _WHISPER_TOTAL_RE.match(line)
    if match:
        # "12 media file(s), 3 already transcribed, 9 to do" -- the denominator
        # is what is TO DO, because the ones already transcribed are skipped in
        # milliseconds and counting them would make the bar jump.
        state["total"] = int(match.group(3))
        return None
    match = _WHISPER_FILE_RE.match(line)
    if match:
        index, total = int(match.group(1)), int(match.group(2))
        state["total"] = total
        state["base"] = (index - 1) / total if total > 0 else 0.0
        return _clamped(state["base"])
    match = _WHISPER_AT_RE.match(line)
    if match and state.get("base") is not None:
        total = int(state.get("total") or 0)
        at, duration = float(match.group(1)), float(match.group(2))
        base = float(state["base"])
        if duration <= 0 or total <= 0:
            # A file whose duration ffprobe would not give: hold at the file
            # boundary rather than divide by nothing.
            return _clamped(base)
        return _clamped(base + (at / duration) / total)
    if _WHISPER_DONE_RE.match(line):
        return 1.0
    return None


def _clamped(fraction: float) -> Optional[float]:
    """0..1, and None for 0 -- see whisper_progress's rule about zero."""
    value = max(0.0, min(1.0, float(fraction)))
    return value if value > 0 else None


def _drain_lines(stream: Any, feed: Callable[[str], None]) -> None:
    """Read the child's stdout line by line until it closes.

    jobs_media._drain_progress's shape, and its posture too: a reader that
    raises must not be able to take down the run it is only watching."""
    try:
        for line in iter(stream.readline, ""):
            if not line:
                break
            if isinstance(line, bytes):
                line = line.decode("utf-8", "replace")
            try:
                feed(line.rstrip("\r\n"))
            except Exception:
                log.debug("jobs: the progress parser stumbled", exc_info=True)
    except Exception:
        log.debug("jobs: the child's output reader stopped early", exc_info=True)
    finally:
        try:
            stream.close()
        except Exception:
            pass


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
