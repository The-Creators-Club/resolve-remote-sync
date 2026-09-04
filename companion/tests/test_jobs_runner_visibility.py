"""What this machine can SAY about the fleet work it does (or does not) do.

Usability + resilience sweep 2026-09-04, CMEDIA-2 / CMEDIA-12 / CMEDIA-13.
Until this wave the runner's verdict lived in a diagnostics bundle somebody
had to be asked to copy, a forced job was an unexplained slowdown, and there
was no way at all for the person at the machine to stop one.

The properties defended:

  * THE GATE IS A SENTENCE, and it is the verdict the last tick actually
    reached, not a fresh evaluation (status() may do no I/O -- it is called
    on the tray's refresh thread).
  * A JOB THAT STARTED WITH SOMEBODY AT THE KEYBOARD SAYS WHO ASKED. The
    admin's `--now` and the editor's own volunteer window are different
    sentences, because they are different answers to "why is my machine
    busy".
  * STOPPING IT IS THE ADMIN'S CANCEL PATH, REUSED. One place terminates a
    job, the result comes back as cancelled and NOT retryable, and the media
    recipes' `.partial` discipline is untouched.
  * WHAT THIS MACHINE HAS RUN SURVIVES A RESTART, and a state dir that
    cannot be written is never why a job fails.
"""
from __future__ import annotations

import json
import subprocess
import threading

from ccsync_companion import jobs_runner as runner_mod

from test_jobs_runner import FakeDashboard, FakeIdle, a_job, a_pipeline, a_vault, cfg


class SlowChild:
    """A child that runs until something stops it, with no OS process behind
    it: the macOS CI runner should not be sleeping for a minute to prove that
    a button cancels a job."""

    def __init__(self, *args, **kwargs):
        self.stdout = None
        self.returncode = None
        self.killed = False
        self._done = threading.Event()

    def wait(self, timeout=None):
        if self._done.wait(timeout if timeout is not None else 60):
            return self.returncode
        raise subprocess.TimeoutExpired("pipeline.py", timeout)

    def terminate(self):
        self.killed = True
        self.returncode = -15
        self._done.set()

    def kill(self):
        self.terminate()


def make(tmp_path, dashboard, caps=None, idle=900, resolve=False, halted=False,
         recent_path=None, runner_fn=None, blocked=None, **cfg_over):
    return runner_mod.JobRunner(
        cfg(tmp_path, **cfg_over),
        request_fn=dashboard.request,
        identity_token_fn=lambda: "identity",
        capabilities_fn=lambda: (caps if caps is not None else {"whisper": True}),
        idle_probe=FakeIdle(idle),
        resolve_running_fn=lambda: resolve,
        halted_fn=lambda: halted,
        blocked_fn=blocked,
        machine_name="EDIT-PC",
        recent_path=recent_path,
        runner_fn=runner_fn,
    )


# ------------------------------------------------------- the gate in words

def test_the_gate_is_a_sentence_an_editor_can_read(tmp_path):
    dash = FakeDashboard(a_job(tmp_path))
    r = make(tmp_path, dash, idle=12)
    r.note_report_reply({"commands": {"jobs": {"offered": [7]}}})
    r.tick()
    gate = r.status()["gate"]
    assert gate["taking_work"] is False
    assert "Somebody is at this computer" in gate["reason"]
    # The floor this machine is waiting for, not a bare number of seconds.
    assert "5 minutes" in gate["reason"]


def test_a_halted_fleet_says_so_on_the_machine_itself(tmp_path):
    dash = FakeDashboard(a_job(tmp_path))
    r = make(tmp_path, dash, halted=True)
    r.note_report_reply({"commands": {"jobs": {"offered": [7]}}})
    r.tick()
    assert r.status()["gate"] == {
        "taking_work": False,
        "reason": runner_mod.GATE_SENTENCES[runner_mod.STATE_HALTED][1]}


def test_a_machine_with_nothing_offered_is_still_taking_work(tmp_path):
    """"Nothing queued" is not a refusal, and rendering it as one is how a
    fleet with no work looks like a fleet that is broken."""
    r = make(tmp_path, FakeDashboard())
    r.tick()
    gate = r.status()["gate"]
    assert gate["taking_work"] is True
    assert "ready for fleet work" in gate["reason"]


def test_no_capability_says_which_kind_of_missing(tmp_path):
    """A machine with no ffmpeg needs a set-up; a machine narrowed to a kind
    it cannot run needs a config line. One state, two sentences."""
    bare = make(tmp_path, FakeDashboard(), caps={})
    bare.tick()
    assert "no whisper set-up" in bare.status()["gate"]["reason"]

    narrowed = make(tmp_path, FakeDashboard(),
                    caps={"whisper": True, "job_kinds": ["peaks"]})
    narrowed.tick()
    reason = narrowed.status()["gate"]["reason"]
    assert "take only: peaks" in reason and narrowed.status()["gate"][
        "taking_work"] is False


def test_jobs_switched_off_is_its_own_sentence(tmp_path):
    r = make(tmp_path, FakeDashboard(), jobs_enabled=False)
    r.tick()
    assert r.status()["gate"] == {
        "taking_work": False,
        "reason": "Fleet jobs are switched off on this computer."}


def test_the_gate_reason_never_carries_an_em_dash(tmp_path):
    """Owner's rule 2026-08-18: not in anything an editor reads."""
    for taking, sentence in runner_mod.GATE_SENTENCES.values():
        assert "—" not in sentence
    assert "—" not in runner_mod.FORCED_BY_ADMIN
    assert "—" not in runner_mod.FORCED_BY_VOLUNTEER


# ------------------------------------------------------- the job it is on

def test_a_running_job_names_itself_in_the_editors_own_terms(tmp_path):
    a_pipeline(tmp_path)
    a_vault(tmp_path)
    dash = FakeDashboard(a_job(tmp_path))
    seen: list = []
    r = make(tmp_path, dash)

    original = r._execute

    def watch(job):
        seen.append(r.status()["current"])
        return original(job)

    r._execute = watch
    r.note_report_reply({"commands": {"jobs": {"offered": [7]}}})
    r.tick()
    current = seen[0]
    assert current["id"] == 7 and current["kind"] == "whisper"
    # The RELATIVE path: the vault is a drive letter here and a mount there.
    assert current["rel_path"].endswith("Interview 3")
    assert current["started_at"].endswith("+00:00")
    assert current["forced_reason"] is None
    # ...and it is gone the moment the job is.
    assert r.status()["current"] is None


def test_a_forced_job_tells_the_person_at_the_keyboard_who_asked(tmp_path):
    """CMEDIA-13: the state existed from phase 1 so somebody could be told,
    and nothing read it."""
    a_pipeline(tmp_path)
    a_vault(tmp_path)
    dash = FakeDashboard(a_job(tmp_path))
    seen: list = []
    r = make(tmp_path, dash, idle=5)          # somebody is here
    original = r._execute
    r._execute = lambda job: (seen.append(r.status()), original(job))
    r.note_report_reply(
        {"commands": {"jobs": {"offered": [7], "forced": [7]}}})
    r.tick()
    assert seen[0]["state"] == runner_mod.STATE_FORCED
    assert seen[0]["current"]["forced_reason"] == runner_mod.FORCED_BY_ADMIN
    assert seen[0]["gate"]["taking_work"] is True


def test_a_volunteered_job_says_that_instead(tmp_path):
    a_pipeline(tmp_path)
    a_vault(tmp_path)
    dash = FakeDashboard(a_job(tmp_path))
    seen: list = []
    r = make(tmp_path, dash, idle=5)
    r.volunteer(30)
    original = r._execute
    r._execute = lambda job: (seen.append(r.status()["current"]), original(job))
    r.note_report_reply({"commands": {"jobs": {"offered": [7]}}})
    r.tick()
    assert seen[0]["forced_reason"] == runner_mod.FORCED_BY_VOLUNTEER


# ------------------------------------------------------- stopping this one

def test_stop_current_with_nothing_running_is_a_no(tmp_path):
    r = make(tmp_path, FakeDashboard())
    assert r.stop_current() is False


def test_stop_current_ends_the_child_and_answers_cancelled(tmp_path):
    """CMEDIA-2. The admin's cancel path, reused whole: the same `_cancel`
    list, the same child kill, the same not-retryable answer."""
    a_pipeline(tmp_path)
    a_vault(tmp_path)
    dash = FakeDashboard(a_job(tmp_path))
    children: list = []

    def spawn(*args, **kwargs):
        children.append(SlowChild())
        return children[-1]

    r = make(tmp_path, dash, runner_fn=spawn)
    r.note_report_reply({"commands": {"jobs": {"offered": [7]}}})

    stopped = threading.Event()

    def press_the_button():
        # Wait until the job is really running, then do what the tray does.
        for _ in range(500):
            if r.status()["current"] is not None:
                break
            stopped.wait(0.02)
        assert r.stop_current() is True
        stopped.set()

    presser = threading.Thread(target=press_the_button, daemon=True)
    presser.start()
    r.tick()
    presser.join(timeout=30)
    assert stopped.is_set()
    assert children[0].killed is True
    result = dash.results[-1]
    assert result["ok"] is False
    assert result["error"] == runner_mod.CANCELLED_ERROR
    # NOT RETRYABLE: another machine picking up work a person just stopped is
    # the one outcome nobody asked for.
    assert result["retryable"] is False


def test_stop_current_uses_the_dashboards_own_cancel_list(tmp_path):
    """Not a second mechanism: the id goes where `commands.jobs.cancel` puts
    it, so exactly one place terminates a job."""
    r = make(tmp_path, FakeDashboard())
    r._job = {"id": 11, "kind": "peaks"}
    assert r.stop_current() is True
    assert r._cancel_requested(11) is True
    # Pressing it twice does not double the list.
    r.stop_current()
    assert r._cancel.count(11) == 1


# ------------------------------------------------- what this machine has run

def test_a_finished_job_lands_in_the_recent_list(tmp_path):
    a_pipeline(tmp_path)
    a_vault(tmp_path)
    dash = FakeDashboard(a_job(tmp_path))
    ledger = tmp_path / "state" / "jobs_recent.json"
    r = make(tmp_path, dash, recent_path=ledger)
    r.note_report_reply({"commands": {"jobs": {"offered": [7]}}})
    r.tick()
    recent = r.status()["recent"]
    assert len(recent) == 1
    assert recent[0]["id"] == 7 and recent[0]["kind"] == "whisper"
    assert recent[0]["outcome"] == "done" and recent[0]["error"] == ""
    assert recent[0]["rel_path"].endswith("Interview 3")
    assert recent[0]["finished_at"].endswith("+00:00")


def test_a_failure_keeps_its_sentence(tmp_path):
    a_pipeline(tmp_path, body="import sys; sys.exit(3)")
    a_vault(tmp_path)
    dash = FakeDashboard(a_job(tmp_path))
    r = make(tmp_path, dash, recent_path=tmp_path / "state" / "jobs_recent.json")
    r.note_report_reply({"commands": {"jobs": {"offered": [7]}}})
    r.tick()
    entry = r.status()["recent"][0]
    assert entry["outcome"] == "failed" and "exited 3" in entry["error"]


def test_a_cancelled_job_is_its_own_outcome(tmp_path):
    """Somebody chose it, so it is not a failure in the list they read."""
    r = make(tmp_path, FakeDashboard(),
             recent_path=tmp_path / "state" / "jobs_recent.json")
    r._current = {"id": 4, "kind": "peaks", "rel_path": "A/B.mov"}
    r._note_finished(4, False, runner_mod.CANCELLED_ERROR)
    assert r.status()["recent"][0]["outcome"] == "cancelled"


def test_the_list_survives_a_restart_and_stays_ten_long(tmp_path):
    ledger = tmp_path / "state" / "jobs_recent.json"
    first = make(tmp_path, FakeDashboard(), recent_path=ledger)
    for i in range(14):
        first._current = {"id": i, "kind": "peaks", "rel_path": f"{i}.mov"}
        first._note_finished(i, True, "")
    again = make(tmp_path, FakeDashboard(), recent_path=ledger)
    recent = again.status()["recent"]
    assert len(recent) == runner_mod.RECENT_MAX
    # Newest first.
    assert [item["id"] for item in recent] == list(range(13, 3, -1))
    assert json.loads(ledger.read_text(encoding="utf-8"))["jobs"][0]["id"] == 13


def test_a_ledger_that_cannot_be_written_never_fails_a_job(tmp_path):
    """proxy_history's posture: bookkeeping bolted onto the work."""
    blocked = tmp_path / "nope"
    blocked.write_text("not a directory", encoding="utf-8")
    r = make(tmp_path, FakeDashboard(), recent_path=blocked / "jobs_recent.json")
    r._current = {"id": 1, "kind": "peaks", "rel_path": "A.mov"}
    r._note_finished(1, True, "")
    # In memory it is still the answer; on disk it simply is not there.
    assert r.status()["recent"][0]["id"] == 1


def test_a_corrupt_ledger_reads_as_an_empty_one(tmp_path):
    ledger = tmp_path / "state" / "jobs_recent.json"
    ledger.parent.mkdir(parents=True)
    ledger.write_text("{not json", encoding="utf-8")
    assert make(tmp_path, FakeDashboard(), recent_path=ledger).status()["recent"] == []


def test_the_default_path_is_the_state_dir_beside_every_other_latch(tmp_path):
    path = runner_mod._default_recent_path(
        {"log_path": str(tmp_path / ".ccsync" / "companion.log")})
    assert path == tmp_path / ".ccsync" / "state" / "jobs_recent.json"


def test_a_cfg_with_no_log_path_keeps_the_ledger_in_memory(tmp_path):
    """A harness must not write into the state dir of whoever runs it."""
    assert runner_mod._default_recent_path({}) is None


def test_the_status_block_is_json_for_the_report_and_the_tray(tmp_path):
    r = make(tmp_path, FakeDashboard())
    r.tick()
    json.dumps(r.status())


# ---------------------------------- the third GPU consumer (CMEDIA-1)
#
# The ingestors and the proxy generator have negotiated over this machine's
# GPU since 2026-08-18 ("indexing beats proxy generation"); the job runner was
# outside that agreement, and both gates open on the same event. So a whisper
# job was claimed onto a machine already holding 8-12 GB of VLM weights, and
# the OOM came back as a job failure that earned the machine a cooldown.

def test_local_work_closes_the_gate_and_says_which(tmp_path):
    dash = FakeDashboard(a_job(tmp_path))
    r = make(tmp_path, dash, blocked=lambda: "indexing b-roll first")
    r.note_report_reply({"commands": {"jobs": {"offered": [7]}}})
    r.tick()
    status = r.status()
    assert status["state"] == runner_mod.STATE_LOCAL_WORK
    assert status["gate"]["taking_work"] is False
    assert "busy with your own work" in status["gate"]["reason"]
    assert "indexing b-roll first" in status["gate"]["reason"]
    assert dash.claims == 0


def test_a_volunteer_click_is_not_consent_to_run_two_gpu_jobs(tmp_path):
    """The local-work gate sits ABOVE the two gates a person can open: a
    volunteer window is "you may use my machine while I am here", not "run a
    transcription on top of the batch I am waiting for"."""
    dash = FakeDashboard(a_job(tmp_path))
    r = make(tmp_path, dash, idle=1, blocked=lambda: "indexing b-roll first")
    r.volunteer(30)
    r.note_report_reply({"commands": {"jobs": {"offered": [7]}}})
    r.tick()
    assert r.status()["state"] == runner_mod.STATE_LOCAL_WORK
    assert dash.claims == 0


def test_a_seam_that_cannot_answer_is_not_a_free_gpu(tmp_path):
    """Fails CLOSED, like the halt and the Resolve probe beside it."""
    def boom():
        raise RuntimeError("the ingestor is wedged")

    dash = FakeDashboard(a_job(tmp_path))
    r = make(tmp_path, dash, blocked=boom)
    r.note_report_reply({"commands": {"jobs": {"offered": [7]}}})
    r.tick()
    assert r.status()["state"] == runner_mod.STATE_LOCAL_WORK
    assert dash.claims == 0


def test_nothing_local_leaves_the_gate_exactly_as_it_was(tmp_path):
    dash = FakeDashboard(a_job(tmp_path))
    r = make(tmp_path, dash, blocked=lambda: False)
    r.note_report_reply({"commands": {"jobs": {"offered": [7]}}})
    r.tick()
    assert r.status()["state"] != runner_mod.STATE_LOCAL_WORK
    # ...and a runner built without the seam at all (an older caller) is
    # unchanged: absent is not blocked.
    r2 = make(tmp_path, FakeDashboard(a_job(tmp_path)))
    r2.note_report_reply({"commands": {"jobs": {"offered": [7]}}})
    r2.tick()
    assert r2.status()["state"] != runner_mod.STATE_LOCAL_WORK
