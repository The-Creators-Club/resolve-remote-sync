"""What phase 4 added to this side of the fleet job wire.

docs/TIMELINE-CARDS-INTO-CCSYNC.md phase 4 (2026-08-30). Three things arrive
on the report reply that this machine has to do something about:

  * `commands.jobs.queue` -- how deep the queue is, so this loop can stop
    asking a fleet that has nothing to give. BACKPRESSURE HERE MEANS "STOP
    ASKING", NEVER "STOP WORKING": a deep queue must never lengthen the wait,
    because the machines are what empties it.
  * `commands.jobs.cancel` -- an admin ended a job this machine is holding.
    The child is killed and the job handed back as `cancelled`, NOT
    retryable: another machine re-running work a person just stopped is the
    one outcome nobody wants.
  * the `[jobs] kinds` allow-list, reported in capabilities so an editor's
    laptop can be kept out of one kind without being taken out of the fleet.
"""
from __future__ import annotations

import subprocess
import sys

import pytest

from ccsync_companion import capabilities as caps_mod
from ccsync_companion import jobs_runner as runner_mod


class FakeIdle:
    def __init__(self, value=900):
        self.value = value

    def seconds_idle(self):
        return self.value


def make(**over):
    cfg = {"dashboard_url": "http://dash.example", "dashboard_token": "tok"}
    cfg.update(over)
    return runner_mod.JobRunner(cfg, request_fn=lambda *a, **k: (200, {}),
                                capabilities_fn=lambda: {"whisper": True},
                                idle_probe=FakeIdle(), machine_name="EDIT-PC")


# ------------------------------------------------------------- the backoff

def test_an_empty_queue_makes_this_machine_ask_less_often():
    r = make(jobs_poll_seconds=20)
    r.note_report_reply({"commands": {"jobs": {
        "queue": {"queued": 0, "running": 0, "pinned": 0, "oldest_age_s": None}}}})
    assert r.wait_seconds() == 80.0


def test_the_backoff_is_capped_so_work_is_still_noticed():
    r = make(jobs_poll_seconds=90)
    r.note_report_reply({"commands": {"jobs": {"queue": {"queued": 0}}}})
    assert r.wait_seconds() == runner_mod.IDLE_BACKOFF_MAX_SECONDS


def test_a_deep_queue_never_lengthens_the_wait():
    """Backpressure is not this machine going quiet while there is work."""
    r = make(jobs_poll_seconds=20)
    r.note_report_reply({"commands": {"jobs": {
        "queue": {"queued": 40, "running": 4, "oldest_age_s": 900.0}}}})
    assert r.wait_seconds() == 20.0


def test_an_offer_always_wins_over_the_depth_signal():
    r = make(jobs_poll_seconds=20)
    r.note_report_reply({"commands": {"jobs": {
        "offered": [7], "queue": {"queued": 0}}}})
    assert r.wait_seconds() == 20.0


def test_a_dashboard_too_old_to_send_a_depth_keeps_the_old_cadence():
    r = make(jobs_poll_seconds=20)
    r.note_report_reply({"commands": {"halt": {"active": False}}})
    assert r.wait_seconds() == 20.0
    assert r.status()["queue"] == {}


def test_an_unreadable_block_changes_nothing():
    r = make(jobs_poll_seconds=20)
    r.note_report_reply({"commands": {"jobs": {"queue": "soon", "offered": "no"}}})
    assert r.status()["queue"] == {}
    assert r.status()["offered"] == []


# -------------------------------------------------------------- the cancel

class FakeDashboard:
    def __init__(self, job=None):
        self.job = job
        self.results: list[dict] = []

    def request(self, method, url, body, headers, timeout):
        suffix = url.split("/api/v1/jobs", 1)[1]
        if suffix == "/claim":
            job, self.job = self.job, None
            return 200, {"job": job}
        if suffix.endswith("/result"):
            self.results.append(body)
        return 200, {"ok": True}


class FakeProc:
    """A child that never finishes on its own. `on_wait` is the reporter
    thread arriving with the admin's cancel while it runs.

    `stdout` is None: since section 10 the runner drains the child's output on
    its own thread, and a child with nothing to drain is exactly the case this
    suite is about -- what happens when it is STOPPED, not what it printed."""

    stdout = None

    def __init__(self, on_wait):
        self.on_wait = on_wait
        self.terminated = False
        self.returncode = None

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        if self.terminated:
            return self.returncode
        self.on_wait()
        raise subprocess.TimeoutExpired("pipeline.py", timeout or 1)

    def terminate(self):
        self.terminated = True
        self.returncode = -1

    def kill(self):
        self.terminated = True
        self.returncode = -1


def a_whisper_runner(tmp_path, dash, on_wait):
    vault = tmp_path / "vault"
    (vault / "Ep/Youtube/Interview 3").mkdir(parents=True)
    proc = FakeProc(on_wait)
    runner = runner_mod.JobRunner(
        {"dashboard_url": "http://dash.example", "dashboard_token": "tok",
         "jobs_vault_root": str(vault),
         "jobs_whisper_python": sys.executable,
         "jobs_mulcam_pipeline": str(tmp_path / "MulticamPipeline")},
        request_fn=dash.request,
        capabilities_fn=lambda: {"whisper": True},
        idle_probe=FakeIdle(900),
        machine_name="EDIT-PC",
        runner_fn=lambda *a, **k: proc)
    return runner, proc


def test_a_cancel_kills_the_child_and_reports_cancelled(tmp_path):
    """The whole path: the id rides the reply, the runner kills its
    subprocess, and the job goes back NOT retryable -- another machine
    re-running work a person just stopped is the one outcome nobody wants."""
    job = {"id": 7, "kind": "whisper",
           "inputs": {"root": "vault", "rel_path": "Ep/Youtube/Interview 3",
                      "episode_rel": "Ep"}}
    dash = FakeDashboard(job)
    holder: dict = {}

    def on_wait():
        # the reporter thread, arriving mid-run with the admin's click
        holder["runner"].note_report_reply(
            {"commands": {"jobs": {"cancel": [7]}}})

    runner, proc = a_whisper_runner(tmp_path, dash, on_wait)
    holder["runner"] = runner
    runner.note_report_reply({"commands": {"jobs": {"offered": [7]}}})
    assert runner.tick() is not None
    assert proc.terminated is True
    assert dash.results[-1]["ok"] is False
    assert dash.results[-1]["error"] == runner_mod.CANCELLED_ERROR
    assert dash.results[-1]["retryable"] is False


def test_a_halt_still_hands_the_job_back_retryably(tmp_path):
    """The contrast that makes the cancel meaningful: "stop everything" is
    not "never do this"."""
    job = {"id": 8, "kind": "whisper",
           "inputs": {"root": "vault", "rel_path": "Ep/Youtube/Interview 3",
                      "episode_rel": "Ep"}}
    dash = FakeDashboard(job)
    halted = {"yes": False}

    def on_wait():
        halted["yes"] = True

    runner, proc = a_whisper_runner(tmp_path, dash, on_wait)
    runner._halted_fn = lambda: halted["yes"]
    runner.note_report_reply({"commands": {"jobs": {"offered": [8]}}})
    runner.tick()
    assert proc.terminated is True
    assert dash.results[-1]["retryable"] is True
    assert dash.results[-1]["error"] != runner_mod.CANCELLED_ERROR


def test_a_cancel_for_a_job_this_machine_is_not_holding_is_harmless(tmp_path):
    r = make()
    r.note_report_reply({"commands": {"jobs": {"cancel": [1, 2, 3]}}})
    assert r._cancel_requested(2) is True
    assert r._cancel_requested(9) is False


# ----------------------------------------------------------- the allow-list

def test_no_allow_list_is_every_kind():
    """The default, and it has to be: naming the kinds you DO want is the
    only way to be excluded from one."""
    assert caps_mod.job_kinds({}) == []
    assert caps_mod.job_kinds({"jobs_kinds": []}) == []


def test_an_allow_list_reaches_the_capabilities_section(tmp_path):
    caps_mod.reset_cache()
    section = caps_mod.build({"jobs_kinds": ["whisper", "peaks"]},
                             use_cache=False)
    assert section["job_kinds"] == ["whisper", "peaks"]


def test_a_hand_written_comma_string_is_read_as_a_list():
    """config.toml is edited by hand, and `jobs_kinds = "whisper, peaks"` is
    what a person writes when the example line is out of sight."""
    assert caps_mod.job_kinds({"jobs_kinds": "whisper, peaks"}) ==         ["whisper", "peaks"]


def test_a_typo_in_the_allow_list_is_dropped_not_obeyed():
    """A machine allow-listing a kind that does not exist would silently take
    no work at all, which looks exactly like a machine that is offline."""
    assert caps_mod.job_kinds({"jobs_kinds": ["whisper", "proxy480"]}) ==         ["whisper"]


def test_the_runner_will_not_claim_a_kind_this_machine_is_not_allowed():
    """Honoured on BOTH sides: the dashboard's filter stops the offer, and
    this stops a stale offer being acted on."""
    r = runner_mod.JobRunner(
        {"dashboard_url": "http://d", "dashboard_token": "t"},
        capabilities_fn=lambda: {"whisper": True, "ffmpeg": True,
                                 "ffprobe": True,
                                 "job_kinds": ["proxy-480p"]},
        idle_probe=FakeIdle(), machine_name="EDIT-PC")
    assert r.runnable_kinds() == ["proxy-480p"]


def test_an_editors_laptop_can_be_kept_out_of_one_kind_not_the_fleet():
    """The point of the setting: `jobs_enabled = false` was the only tool,
    and it takes the machine out of everything."""
    r = runner_mod.JobRunner(
        {"dashboard_url": "http://d", "dashboard_token": "t"},
        capabilities_fn=lambda: {"whisper": True, "ffmpeg": True,
                                 "ffprobe": True,
                                 "job_kinds": ["peaks", "audio-extract"]},
        idle_probe=FakeIdle(), machine_name="EDIT-PC")
    assert "whisper" not in r.runnable_kinds()
    assert sorted(r.runnable_kinds()) == ["audio-extract", "peaks"]
