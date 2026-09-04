"""Is this machine really serving the Timeline Cards page, and if not, why?

Usability + resilience sweep 2026-09-04, RES-6 and RES-7. Before this wave
`report_block()["connected"]` was `bool(self._threads)` and nothing ever
cleared that list, so a dead loop, a fleet credential that had been refused
for hours and a dashboard that could not be reached all rendered on the fleet
grid exactly like a healthy machine. And the refusal was decided ONCE, at
start: signing in from the tray, or closing the standalone agent the sentence
told you to close, changed nothing until the companion was restarted.

The properties defended:

  * GREEN MEANS TALKING. The loops are alive AND the dashboard answered one
    of them within two long polls; a start buys GRACE_SECONDS and no more.
  * THE FIVE WORDS ARE DIFFERENT PROBLEMS. stopped / credential_refused /
    unreachable / refused are four different people's jobs.
  * THE REFUSAL IS RE-ASKED, and the role starts on its own when it clears.
  * THE ADVICE NAMES THE PROCESS. Image name and pid, and what to close.
"""
from __future__ import annotations

import importlib
import json
import sys
import time

import pytest

from ccsync_companion import timeline_cards_role as role_mod

from test_timeline_cards_role import (DASH, FakeDashboard, TOKEN, a_cfg,
                                      a_checkout, _wait_for)


@pytest.fixture(autouse=True)
def _forget_the_fake_package():
    """The sibling suite's fixture, repeated: each test writes its own
    multicam_pipeline and none may see the last."""
    before = list(sys.path)
    yield
    agent = sys.modules.get("multicam_pipeline.cards.agent")
    if agent is not None and hasattr(agent, "STOP"):
        agent.STOP.set()
    for name in [n for n in sys.modules if n.startswith("multicam_pipeline")]:
        sys.modules.pop(name, None)
    sys.path[:] = before
    importlib.invalidate_caches()


class FakeClock:
    """Minutes pass when the test says so, never when it is slow."""

    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now

    def tick(self, seconds):
        self.now += seconds


def a_role(tmp_path, dashboard=None, processes=None, clock=None, **over):
    return role_mod.TimelineCardsRole(
        a_cfg(tmp_path, **over),
        request_fn=(dashboard or FakeDashboard()).request,
        identity_token_fn=lambda: "signed-identity",
        processes_fn=(processes if processes is not None else (lambda: [])),
        clock=clock or time.monotonic,
    )


# ------------------------------------------------------------- green means talking

def test_a_talking_role_is_running_and_carries_its_last_poll(tmp_path):
    a_checkout(tmp_path)
    role = a_role(tmp_path)
    role.start()
    _wait_for(lambda: role.report_block()["last_poll_at"])
    block = role.report_block()
    assert block["state"] == role_mod.HEALTH_RUNNING
    assert block["connected"] is True
    assert block["last_http_status"] == 200
    assert block["last_poll_at"].endswith("+00:00")
    assert block["gate_state"] == role_mod.STATE_RUNNING
    role.stop()


def test_a_role_that_has_not_talked_for_two_long_polls_is_unreachable(tmp_path):
    a_checkout(tmp_path)
    role = a_role(tmp_path)
    role.start()
    _wait_for(lambda: role.report_block()["last_poll_at"])
    with role._lock:
        role._last_poll_at = time.time() - (role_mod.STALE_AFTER_SECONDS + 5)
    block = role.report_block()
    assert block["state"] == role_mod.HEALTH_UNREACHABLE
    assert block["connected"] is False
    assert block["detail"]
    role.stop()


def test_a_start_that_has_not_polled_yet_is_green_only_briefly(tmp_path):
    """A chip that goes amber for the first three seconds of every companion
    restart is a chip nobody believes -- and one that stays green for ever on
    a role that never made a call is the bug."""
    a_checkout(tmp_path)
    role = a_role(tmp_path)
    role.start()
    with role._lock:
        role._last_poll_at = None
        role._since = time.time()
    assert role.report_block()["state"] == role_mod.HEALTH_RUNNING
    with role._lock:
        role._since = time.time() - (role_mod.GRACE_SECONDS + 5)
    assert role.report_block()["state"] == role_mod.HEALTH_UNREACHABLE
    role.stop()


# --------------------------------------------------- the four kinds of not green

def test_a_dead_loop_is_stopped_and_says_what_killed_it(tmp_path):
    a_checkout(tmp_path, loops_raise=True)
    role = a_role(tmp_path)
    role.start()
    _wait_for(lambda: role.report_block()["state"] == role_mod.HEALTH_STOPPED)
    block = role.report_block()
    assert block["connected"] is False
    assert "resolve went away" in block["detail"]
    # The gate still says the role was meant to be up: the two answers are
    # different questions.
    assert block["gate_state"] == role_mod.STATE_RUNNING
    role.stop()


def test_a_refused_credential_says_sign_in_again(tmp_path):
    a_checkout(tmp_path)
    dashboard = FakeDashboard()
    dashboard.status = 401
    role = a_role(tmp_path, dashboard=dashboard)
    role.start()
    _wait_for(lambda: role.report_block()["last_http_status"] == 401)
    block = role.report_block()
    assert block["state"] == role_mod.HEALTH_CREDENTIAL_REFUSED
    assert block["detail"] == role_mod.CREDENTIAL_ADVICE
    assert "sign in again from the tray" in block["detail"]
    role.stop()


def test_a_403_is_the_same_answer(tmp_path):
    a_checkout(tmp_path)
    dashboard = FakeDashboard()
    dashboard.status = 403
    role = a_role(tmp_path, dashboard=dashboard)
    role.start()
    _wait_for(lambda: role.report_block()["last_http_status"] == 403)
    assert role.report_block()["state"] == role_mod.HEALTH_CREDENTIAL_REFUSED
    role.stop()


def test_a_transport_failure_is_remembered_and_named(tmp_path):
    """The engine's loops swallow it and back off, which is right for them
    and is exactly why this side has to keep the last one."""
    a_checkout(tmp_path)

    class Dead:
        def request(self, *args, **kwargs):
            raise OSError("connection refused")

    role = a_role(tmp_path, dashboard=Dead())
    role.start()
    _wait_for(lambda: role.report_block()["detail"].find("connection refused") >= 0)
    block = role.report_block()
    assert block["state"] == role_mod.HEALTH_UNREACHABLE
    assert block["last_http_status"] is None
    role.stop()


def test_a_machine_that_never_started_is_refused_not_stopped(tmp_path):
    role = a_role(tmp_path, cards_agent=False)
    role.start()
    block = role.report_block()
    assert block["state"] == role_mod.HEALTH_REFUSED
    assert block["gate_state"] == role_mod.STATE_DISABLED
    assert block["detail"] == "cards_agent is not set in ~/.ccsync/config.toml"


def test_the_block_is_json_for_the_report(tmp_path):
    a_checkout(tmp_path)
    role = a_role(tmp_path)
    role.start()
    json.dumps(role.report_block())
    role.stop()


# ------------------------------------------------- the refusal is re-asked (RES-7)

def test_the_role_starts_on_its_own_when_the_rival_goes_away(tmp_path):
    a_checkout(tmp_path)
    clock = FakeClock()
    running = ["4312\tpython.exe\tC:\\py.exe reorder_web.py --agent"]
    role = a_role(tmp_path, processes=lambda: list(running), clock=clock)
    assert role.start() is False
    assert role.report_block()["gate_state"] == role_mod.STATE_STANDALONE_AGENT
    running.clear()
    # Still inside the probe cache: nothing has changed yet.
    assert role.supervise_now() is False
    clock.tick(role_mod.PROBE_CACHE_SECONDS + 1)
    assert role.supervise_now() is True
    assert role.status()["state"] == role_mod.STATE_RUNNING
    role.stop()


def test_a_halt_at_boot_no_longer_latches_the_role_off_for_the_process(tmp_path):
    """A fleet halt expires at 24 h by design; the role used to stay off
    until the companion was restarted."""
    a_checkout(tmp_path)
    halted = {"yes": True}
    role = role_mod.TimelineCardsRole(a_cfg(tmp_path),
                                      request_fn=FakeDashboard().request,
                                      processes_fn=lambda: [],
                                      halted_fn=lambda: halted["yes"])
    assert role.start() is False
    assert role.status()["state"] == role_mod.STATE_HALTED
    halted["yes"] = False
    assert role.supervise_now() is True
    role.stop()


def test_signing_in_later_is_enough(tmp_path):
    a_checkout(tmp_path)
    cfg = a_cfg(tmp_path)
    cfg["dashboard_token"] = ""
    role = role_mod.TimelineCardsRole(cfg, request_fn=FakeDashboard().request,
                                      processes_fn=lambda: [])
    assert role.start() is False
    detail = role.status()["detail"]
    assert "Sign in from the tray" in detail and "restart" not in detail
    cfg["dashboard_token"] = TOKEN
    assert role.supervise_now() is True
    role.stop()


def test_a_running_role_is_not_started_twice_by_the_watchdog(tmp_path):
    a_checkout(tmp_path)
    role = a_role(tmp_path)
    assert role.start() is True
    engine = role._engine
    assert role.supervise_now() is True
    assert role._engine is engine
    role.stop()


def test_the_watchdog_runs_on_a_timer_and_only_where_the_role_is_on(tmp_path,
                                                                   monkeypatch):
    monkeypatch.setattr(role_mod, "PROBE_CACHE_SECONDS", 0.02)
    a_checkout(tmp_path)
    running = ["4312\tpython.exe\tpython reorder_web.py --agent"]
    role = a_role(tmp_path, processes=lambda: list(running))
    assert role.start() is False
    running.clear()
    _wait_for(lambda: role.status()["state"] == role_mod.STATE_RUNNING)
    role.stop()
    # ...and a machine with the role switched off keeps no thread at all: it
    # must not shell out for a process listing every minute for ever.
    off = a_role(tmp_path, cards_agent=False)
    off.start()
    assert off._supervisor is None


def test_stopping_the_role_stops_the_watchdog(tmp_path, monkeypatch):
    monkeypatch.setattr(role_mod, "PROBE_CACHE_SECONDS", 0.02)
    a_checkout(tmp_path)
    role = a_role(tmp_path)
    role.start()
    watchdog = role._supervisor
    role.stop()
    watchdog.join(timeout=5)
    assert watchdog.is_alive() is False


def test_a_refusal_that_never_changes_is_logged_once(tmp_path, caplog):
    """The watchdog re-asks every minute; companion.log must not grow a line
    a minute for weeks."""
    role = a_role(tmp_path, cards_agent=False)
    with caplog.at_level("INFO", logger="ccsync.cards"):
        role.start()
        for _ in range(5):
            role.supervise_now()
    lines = [r for r in caplog.records if "not serving the page here" in r.message]
    assert len(lines) == 1


# ------------------------------------------------- the advice names the process

def test_the_refusal_names_the_process_and_what_to_close(tmp_path):
    role = a_role(tmp_path, processes=lambda: [
        "4312\tpython.exe\tC:\\Python\\python.exe reorder_web.py --agent"])
    state, detail = role.refusal()
    assert state == role_mod.STATE_STANDALONE_AGENT
    assert "python.exe (pid 4312)" in detail
    assert "Close the standalone Timeline Cards agent window" in detail
    assert "CR-68" in detail


def test_cannot_tell_is_not_rendered_as_a_sighting(tmp_path):
    """"Found: this machine's processes could not be listed" sent people
    looking for a process nobody had seen."""
    role = a_role(tmp_path, processes=lambda: None)
    state, detail = role.refusal()
    assert state == role_mod.STATE_STANDALONE_AGENT
    assert "Found:" not in detail
    assert "may be running here" in detail and "could not be listed" in detail


def test_describe_process_reads_both_probe_shapes():
    assert role_mod.describe_process(
        "4312\tpython.exe\tpython reorder_web.py --agent"
    ) == "python.exe (pid 4312): python reorder_web.py --agent"
    # macOS `ps -Ao pid=,comm=,command=`.
    assert role_mod.describe_process(
        " 812 /usr/bin/python3 python3 reorder_web.py --agent"
    ) == "python3 (pid 812): python3 reorder_web.py --agent"
    # A bare command line from a probe this module does not own.
    assert role_mod.describe_process(
        "python reorder_web.py --agent") == "python reorder_web.py --agent"
    assert role_mod.describe_process("") == ""


def test_no_sentence_an_editor_reads_carries_an_em_dash(tmp_path):
    role = a_role(tmp_path, processes=lambda: None)
    assert "—" not in role.refusal()[1]
    assert "—" not in role_mod.CREDENTIAL_ADVICE
    assert "—" not in a_role(tmp_path, cards_agent=False).refusal()[1]
