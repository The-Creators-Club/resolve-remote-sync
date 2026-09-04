"""The Timeline Cards role: what starts it, what refuses it, what it says.

docs/TIMELINE-CARDS-INTO-CCSYNC.md phase 2 (2026-08-30). The Timeline Cards
checkout is a fake package written into tmp_path and the dashboard is a dict,
so this suite runs on a machine with neither.

The properties defended, each of them a way an editor's Resolve gets hurt:

  * ONE RESOLVE CLIENT PER MACHINE. A standalone `reorder_web.py --agent`
    already running here is a refusal, named, and it is NOT killed: a human
    started it and a human stops it. "Cannot tell" counts as running.
  * AN ENGINE THAT STILL OWNS A CONNECTION IS REFUSED. The contract check is
    a version AND a signature, and the message names §7c rather than raising
    a TypeError somewhere inside a conform.
  * OFF IS THE DEFAULT, EVERYWHERE. `cards_agent` unset is a refusal with a
    sentence, not silence -- the diagnostics bundle has to be able to say
    why this machine is not serving the page.
  * THE COMPANION'S CREDENTIAL, AND ONLY IT. The role talks to the DASHBOARD
    with the fleet token plus a signed identity; the cards server's own token
    appears nowhere on this side, including in the query string the engine's
    own client builds.
"""
from __future__ import annotations

import importlib
import json
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

from ccsync_companion import timeline_cards_bridge as bridge_mod
from ccsync_companion import timeline_cards_role as role_mod

DASH = "https://dash.invalid"
TOKEN = "companion-token-not-a-real-one"


def a_cfg(tmp_path, **over):
    cfg = {
        "cards_agent": True,
        "dashboard_url": DASH,
        "dashboard_token": TOKEN,
        "jobs_mulcam_pipeline": str(tmp_path / "MulticamPipeline"),
        "jobs_vault_root": str(tmp_path / "vault"),
    }
    cfg.update(over)
    return cfg


class FakeDashboard:
    """The three tunnel routes, in a dict."""

    def __init__(self):
        self.calls: list[tuple[str, str, dict | None, dict]] = []
        self.answer: dict = {"ok": True}
        self.status = 200

    def request(self, method, url, body, headers, timeout):
        self.calls.append((method, url, body, headers))
        return self.status, dict(self.answer)


def a_checkout(tmp_path, *, contract=1, takes_bridge=True, importable=True,
               class_name="SyncEngine", loops_raise=False):
    """A fake MulticamPipeline whose cards package is two tiny modules.

    Deliberately NOT the real one: what is under test is the shim's judgement
    about an engine, and the real engine needs a vault, a database and a
    Resolve to construct.
    """
    root = tmp_path / "MulticamPipeline"
    cards = root / "multicam_pipeline" / "cards"
    cards.mkdir(parents=True, exist_ok=True)
    (root / "multicam_pipeline" / "__init__.py").write_text("", encoding="utf-8")
    (cards / "__init__.py").write_text("", encoding="utf-8")
    if not importable:
        (cards / "resolve_engine.py").write_text("import nosuchmodule\n",
                                                 encoding="utf-8")
        (cards / "agent.py").write_text("", encoding="utf-8")
        return root
    signature = "def __init__(self, root, bridge=None):" if takes_bridge \
        else "def __init__(self, root):"
    version = "" if contract is None else f"BRIDGE_CONTRACT_VERSION = {contract}\n"
    (cards / "resolve_engine.py").write_text(textwrap.dedent(f"""
        {version}
        class {class_name}(object):
            {signature}
                self.root = root
                self.bridge = getattr(self, 'bridge', None) or locals().get('bridge')
                self.started = False
                self.version = 5

            def start(self):
                self.started = True
        """), encoding="utf-8")
    # THE LOOPS DO NOT RETURN, because the real AgentClient's do not: since
    # RES-6 (sweep 2026-09-04) a loop that returns is a REPORTABLE FAULT
    # (health "stopped"), so a fake that ran once and exited would make every
    # healthy-role test in this file assert a dead one. `loops_raise` is the
    # other half, for the tests that want the fault.
    body = ('raise RuntimeError("resolve went away")' if loops_raise
            else 'STOP.wait(30)')
    (cards / "agent.py").write_text(textwrap.dedent("""
        import threading

        STOP = threading.Event()

        class AgentClient(object):
            def __init__(self, server, token, engine, name=None):
                self.url, self.token, self.eng, self.name = server, token, engine, name
                self.pushed = []

            def _req(self, path, doc=None, timeout=30):
                raise NotImplementedError

            def push_loop(self):
                # The real AgentClient treats every exception as "the network
                # is down" and backs off; a fake that died on one would make
                # every tunnel fault in this suite look like a dead thread.
                try:
                    self.pushed.append(self._req("/agent/state", {
                        "token": self.token, "name": self.name,
                        "state": {"timeline": "E1", "project": "FF5"}}, 90))
                except Exception:
                    pass
                __AFTER__

            def pull_loop(self):
                try:
                    self._req("/agent/pending?wait=25&token=" + str(self.token),
                              None, 45)
                except Exception:
                    pass
                __AFTER__
        """).replace("__AFTER__", body), encoding="utf-8")
    return root


@pytest.fixture(autouse=True)
def _forget_the_fake_package():
    """Each test writes its own multicam_pipeline; none may see the last.

    The module cache AND the sys.path entry AND importlib's directory cache:
    leave any one of the three and the second test in a run imports the first
    test's engine out of a temp directory that no longer exists.
    """
    before = list(sys.path)
    yield
    agent = sys.modules.get("multicam_pipeline.cards.agent")
    if agent is not None and hasattr(agent, "STOP"):
        # Let the fake loops end with the test that started them.
        agent.STOP.set()
    for name in [n for n in sys.modules if n.startswith("multicam_pipeline")]:
        sys.modules.pop(name, None)
    sys.path[:] = before
    importlib.invalidate_caches()


def a_role(tmp_path, dashboard=None, **over):
    return role_mod.TimelineCardsRole(
        a_cfg(tmp_path, **over),
        request_fn=(dashboard or FakeDashboard()).request,
        identity_token_fn=lambda: "signed-identity",
        processes_fn=lambda: ["notepad.exe"],
    )


# --------------------------------------------------------------- the refusals

def test_off_is_the_default_and_it_says_so(tmp_path):
    role = a_role(tmp_path, cards_agent=False)
    state, detail = role.refusal()
    assert state == role_mod.STATE_DISABLED
    assert "cards_agent" in detail
    assert role.start() is False
    assert role.status()["state"] == role_mod.STATE_DISABLED


def test_no_dashboard_is_a_refusal(tmp_path):
    role = a_role(tmp_path, dashboard_token="")
    assert role.refusal()[0] == role_mod.STATE_NO_DASHBOARD


def test_no_checkout_is_a_refusal_that_names_the_key(tmp_path):
    role = a_role(tmp_path, jobs_mulcam_pipeline="")
    state, detail = role.refusal()
    assert state == role_mod.STATE_NO_CHECKOUT
    assert "jobs_mulcam_pipeline" in detail


def test_no_vault_is_a_refusal(tmp_path):
    role = a_role(tmp_path, jobs_vault_root="")
    assert role.refusal()[0] == role_mod.STATE_NO_VAULT


def test_a_fleet_halt_refuses_a_start(tmp_path):
    role = role_mod.TimelineCardsRole(
        a_cfg(tmp_path), processes_fn=lambda: [], halted_fn=lambda: True)
    assert role.refusal()[0] == role_mod.STATE_HALTED


def test_a_halt_check_that_cannot_answer_fails_closed(tmp_path):
    role = role_mod.TimelineCardsRole(
        a_cfg(tmp_path), processes_fn=lambda: [],
        halted_fn=lambda: 1 / 0)
    assert role.refusal()[0] == role_mod.STATE_HALTED


# ------------------------------------------------------- one Resolve client

def test_a_standalone_agent_is_a_refusal_and_is_not_killed(tmp_path, caplog):
    a_checkout(tmp_path)
    line = (r'"C:\python.exe" E:\Projects\Editing\Resolve\MulticamPipeline'
            r'\reorder_web.py --agent http://truenas:8800/')
    role = role_mod.TimelineCardsRole(a_cfg(tmp_path),
                                      processes_fn=lambda: [line])
    with caplog.at_level("WARNING", logger="ccsync.cards"):
        assert role.start() is False
    state, detail = role.refusal()
    assert state == role_mod.STATE_STANDALONE_AGENT
    assert "reorder_web.py" in detail and "CR-68" in detail
    # Nothing in this module may terminate somebody else's process.
    source = Path(role_mod.__file__).read_text(encoding="utf-8")
    assert "terminate(" not in source and "taskkill" not in source


def test_the_pcs_own_server_counts_too(tmp_path):
    """README: do not run this PC's own reorder_web.py 8800 and the agent at
    the same time. The companion is now the agent, so the server counts."""
    role = role_mod.TimelineCardsRole(
        a_cfg(tmp_path),
        processes_fn=lambda: ["python reorder_web.py 8800"])
    assert role.refusal()[0] == role_mod.STATE_STANDALONE_AGENT


def test_a_process_probe_that_cannot_answer_counts_as_running(tmp_path):
    """FAILS CLOSED. A false refusal costs the page until somebody looks; a
    false clearance costs scripting for the whole Resolve session, for every
    client on the machine."""
    role = role_mod.TimelineCardsRole(a_cfg(tmp_path), processes_fn=lambda: None)
    state, detail = role.refusal()
    assert state == role_mod.STATE_STANDALONE_AGENT
    assert "could not be listed" in detail


def test_an_unrelated_python_is_not_an_agent(tmp_path):
    assert role_mod.standalone_agent(
        ["python -m pip install ccsync", "C:\\Windows\\explorer.exe"]) is None


def test_a_process_listing_that_failed_part_way_is_not_an_answer(monkeypatch):
    """bug-hunt-2026-09-03 comp-resolve-6. A CIM query that emits lines and
    then fails is a TRUNCATED list, and reading it as authoritative is how a
    running standalone agent goes unseen: two Resolve clients on one machine,
    the CR-68 outcome this gate exists to prevent."""
    class _Out:
        returncode = 1
        stdout = "explorer.exe\npython.exe -m pip\n"

    monkeypatch.setattr(role_mod.platform, "system", lambda: "Windows")
    monkeypatch.setattr(role_mod.subprocess, "run", lambda *a, **k: _Out())
    assert role_mod.running_command_lines() is None
    # ...and "cannot tell" is a refusal, not a clearance.
    assert role_mod.standalone_agent(role_mod.running_command_lines()) is not None


def test_a_process_listing_that_succeeded_is_used(monkeypatch):
    class _Out:
        returncode = 0
        stdout = "python reorder_web.py --agent http://truenas:8800/\n"

    monkeypatch.setattr(role_mod.platform, "system", lambda: "Windows")
    monkeypatch.setattr(role_mod.subprocess, "run", lambda *a, **k: _Out())
    lines = role_mod.running_command_lines()
    assert lines and "reorder_web.py" in lines[0]


def test_the_probe_is_cached_rather_than_run_per_tick(tmp_path):
    calls = []

    def probe():
        calls.append(1)
        return []

    role = role_mod.TimelineCardsRole(a_cfg(tmp_path), processes_fn=probe)
    role.refusal()
    role.refusal()
    role.refusal()
    assert len(calls) == 1


# --------------------------------------------------------------- the contract

def test_an_engine_with_no_bridge_contract_is_refused(tmp_path):
    """Today's Timeline Cards. It owns a Resolve connection, so it cannot run
    beside the companion's -- and the message says which document to read."""
    a_checkout(tmp_path, contract=None)
    role = a_role(tmp_path)
    assert role.start() is False
    status = role.status()
    assert status["state"] == role_mod.STATE_NO_ENGINE
    assert "7c" in status["detail"] and "BRIDGE_CONTRACT_VERSION" in status["detail"]


def test_a_different_contract_version_is_refused(tmp_path):
    a_checkout(tmp_path, contract=99)
    role = a_role(tmp_path)
    assert role.start() is False
    assert role.status()["state"] == role_mod.STATE_OLD_ENGINE
    assert "99" in role.status()["detail"]


def test_a_declared_contract_without_the_argument_is_refused(tmp_path):
    """The constant is a CLAIM; the signature is whether it is true."""
    a_checkout(tmp_path, takes_bridge=False)
    role = a_role(tmp_path)
    assert role.start() is False
    assert "bridge" in role.status()["detail"]


def test_the_engine_may_be_called_resolveengine(tmp_path):
    """bug-hunt-2026-09-03 comp-resolve-3: check_contract accepts either
    spelling and _start used to hard-require SyncEngine, so the checkout that
    exists today (ResolveEngine, the name §7c's own prose uses) passed the
    contract test and then died as an AttributeError inside start()'s
    catch-all, under a sentence that named nothing."""
    a_checkout(tmp_path, class_name="ResolveEngine")
    role = a_role(tmp_path)
    assert role.start() is True
    assert type(role._engine).__name__ == "ResolveEngine"
    assert role._engine.bridge is not None
    role.stop()


def test_check_contract_hands_back_the_class_it_validated(tmp_path):
    a_checkout(tmp_path, class_name="ResolveEngine")
    engine_mod, _agent = role_mod.load_engine(tmp_path / "MulticamPipeline")
    assert role_mod.check_contract(engine_mod) is engine_mod.ResolveEngine


def test_a_checkout_that_does_not_import_is_a_sentence(tmp_path):
    a_checkout(tmp_path, importable=False)
    role = a_role(tmp_path)
    assert role.start() is False
    assert role.status()["state"] == role_mod.STATE_NO_ENGINE
    assert "could not be imported" in role.status()["detail"]


def test_a_missing_checkout_names_the_path(tmp_path):
    role = a_role(tmp_path, jobs_mulcam_pipeline=str(tmp_path / "nowhere"))
    assert role.start() is False
    assert "nowhere" in role.status()["detail"]


def test_a_directory_that_is_not_a_checkout_is_refused(tmp_path):
    (tmp_path / "MulticamPipeline").mkdir()
    role = a_role(tmp_path)
    assert role.start() is False
    assert "not a MulticamPipeline checkout" in role.status()["detail"]


# ------------------------------------------------------------- it does start

def test_it_starts_with_the_config_the_checkout_and_no_rival(tmp_path):
    a_checkout(tmp_path)
    dashboard = FakeDashboard()
    role = a_role(tmp_path, dashboard=dashboard)
    assert role.start() is True
    status = role.status()
    assert status["state"] == role_mod.STATE_RUNNING and status["running"]
    role.stop()
    assert role.status()["running"] is False


def test_the_engine_is_handed_the_bridge_and_the_vault(tmp_path):
    a_checkout(tmp_path)
    bridge = bridge_mod.CardsBridge({}, connect_fn=lambda: None)
    role = role_mod.TimelineCardsRole(a_cfg(tmp_path), bridge=bridge,
                                      processes_fn=lambda: [],
                                      request_fn=FakeDashboard().request)
    assert role.start() is True
    engine = role._engine
    assert engine.root == str(tmp_path / "vault")
    assert engine.bridge is bridge
    assert engine.started is True
    role.stop()


def test_starting_twice_starts_one_engine(tmp_path):
    a_checkout(tmp_path)
    role = a_role(tmp_path)
    assert role.start() is True
    first = role._engine
    assert role.start() is True
    assert role._engine is first
    role.stop()


# ------------------------------------------------------------- the tunnel

def test_the_push_goes_to_the_dashboard_with_the_fleet_credential(tmp_path):
    a_checkout(tmp_path)
    dashboard = FakeDashboard()
    role = a_role(tmp_path, dashboard=dashboard)
    role.start()
    _wait_for(lambda: dashboard.calls)
    method, url, body, headers = dashboard.calls[0]
    assert method == "POST"
    assert url == f"{DASH}/cards/agent/state"
    assert headers["X-CCSync-Token"] == TOKEN
    assert headers["X-CCSync-Identity"] == "signed-identity"
    role.stop()


def test_no_cards_token_is_ever_sent(tmp_path):
    """The whole point of the tunnel: the cards server's secret lives in the
    dashboard container, and this machine never holds one."""
    a_checkout(tmp_path)
    dashboard = FakeDashboard()
    role = a_role(tmp_path, dashboard=dashboard)
    role.start()
    _wait_for(lambda: len(dashboard.calls) >= 2)
    role.stop()
    for _method, url, body, headers in dashboard.calls:
        assert "token" not in url.lower()
        assert "X-Cards-Token" not in headers
        assert not (body or {}).get("token")


def test_the_long_poll_keeps_its_wait(tmp_path):
    a_checkout(tmp_path)
    dashboard = FakeDashboard()
    role = a_role(tmp_path, dashboard=dashboard)
    role.start()
    _wait_for(lambda: any("pending" in c[1] for c in dashboard.calls))
    poll = [c for c in dashboard.calls if "pending" in c[1]][0]
    assert poll[0] == "GET"
    assert poll[1] == f"{DASH}/cards/agent/pending?wait=25"
    role.stop()


def test_a_greedy_wait_is_clamped_on_this_side_too(tmp_path):
    role = a_role(tmp_path)
    dashboard = FakeDashboard()
    role._request = dashboard.request
    role.call("/agent/pending?wait=600&token=abc")
    assert dashboard.calls[0][1].endswith("?wait=25")


def test_a_route_the_protocol_does_not_have_is_refused(tmp_path):
    role = a_role(tmp_path)
    with pytest.raises(role_mod.CardsTunnelError):
        role.call("/agent/everything")


def test_a_non_200_is_an_exception_the_loops_back_off_from(tmp_path):
    dashboard = FakeDashboard()
    dashboard.status = 502
    dashboard.answer = {"detail": "could not reach the Timeline Cards server"}
    role = a_role(tmp_path, dashboard=dashboard)
    with pytest.raises(role_mod.CardsTunnelError) as caught:
        role.call("/agent/state", {"state": None})
    assert "502" in str(caught.value)
    assert "could not reach" in str(caught.value)


# --------------------------------------------------------------- the report

def test_the_report_block_says_which_timeline(tmp_path):
    a_checkout(tmp_path)
    dashboard = FakeDashboard()
    role = a_role(tmp_path, dashboard=dashboard)
    role.start()
    _wait_for(lambda: role.report_block()["timeline"])
    block = role.report_block()
    assert block["connected"] is True
    assert block["timeline"] == "E1"
    assert block["version"] == 5
    assert block["state"] == role_mod.STATE_RUNNING
    role.stop()


def test_the_report_block_of_a_refusing_machine_names_the_refusal(tmp_path):
    role = a_role(tmp_path, cards_agent=False)
    role.start()
    block = role.report_block()
    assert block == {"connected": False, "state": role_mod.HEALTH_REFUSED,
                     "detail": "cards_agent is not set in ~/.ccsync/config.toml",
                     "gate_state": role_mod.STATE_DISABLED,
                     "last_poll_at": None, "last_http_status": None,
                     "timeline": "", "version": 0, "since": None}


def test_the_status_carries_the_lock_numbers(tmp_path):
    a_checkout(tmp_path)
    bridge = bridge_mod.CardsBridge({}, connect_fn=lambda: None)
    role = role_mod.TimelineCardsRole(a_cfg(tmp_path), bridge=bridge,
                                      processes_fn=lambda: [],
                                      request_fn=FakeDashboard().request)
    role.start()
    with bridge.lock("cards.sweep"):
        pass
    assert role.status()["lock"]["takes"] == 1
    role.stop()


def test_the_role_is_json_serialisable_for_the_report(tmp_path):
    """It rides the report body, which is JSON."""
    role = a_role(tmp_path, cards_agent=False)
    json.dumps(role.report_block())


def _wait_for(predicate, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.02)
    raise AssertionError("the loops never got there")
