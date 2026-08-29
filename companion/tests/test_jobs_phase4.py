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
