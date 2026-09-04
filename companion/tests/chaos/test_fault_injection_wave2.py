"""Fault injection, wave 2: the shapes the last thirty ledger entries paid for.

SYS-10 (usability + resilience sweep 2026-09-03,
`docs/usability-resilience-sweep-2026-09-03/SYS.md`): against ~10,600 test
functions, 28 were fault injections, and every one of them was parameterised
over the shapes of the sweep BEFORE last. Everything in CR-125..CR-154 was
found by the owner using the product. So this module is the sibling of
`test_fault_injection.py` written against the newer ledger, on the same two
rules as its parent:

1. **Every assertion is an OBSERVABLE** - a refusal, a safe state, or a
   notice a person is handed. Never "the guard was called", and never a log
   line: a diagnosis that reaches only `companion.log` reaches nobody (UX-10).
2. **Nothing here sleeps, spawns, opens a window or reaches the network.**
   Every Tk root is a fake (conftest `_no_real_tk_windows` makes a real one a
   test failure), every listener is a stub, and no assertion here depends on
   the platform - both suites run on the macOS CI runner as well as this box
   (the lesson of the three red macOS builds around CR-138..CR-144).

Five injections, each named for the defect class it closes:

  1. two doors onto one loopback bind (CR-149 follow-up, companion 0.9.66)
  2. a bind retry that arrives during shutdown (CR-149)
  3. sync blocked while the tray is green (CR-149 APP-1, CR-27's licence park)
  4. an update pushed into work that is in flight (CR-149 RES-8 / COMP-CORE-2)
  5. a worker thread collecting another thread's Tk closure cycle (CR-93)
"""

from __future__ import annotations

import gc
import threading
import weakref
from typing import Any, Optional

import pytest

from ccsync_companion import broll_server as broll_server_mod
from ccsync_companion import ui_dispatch
from ccsync_companion.app import CompanionApp
from ccsync_companion.sync.base import STATE_IDLE, LaneStatus
from ccsync_companion.tray import compute_overall_color


# -- the app under test ----------------------------------------------------


def _chaos_app(tmp_path, **overrides) -> CompanionApp:
    """The same inert CompanionApp `test_fault_injection._chaos_app` builds:
    lanes off, and both gates open so an assertion measures the injected
    fault rather than "nobody has onboarded this machine"."""
    root = tmp_path / "root"
    root.mkdir(parents=True, exist_ok=True)
    cfg = {
        "editor_name": "owen",
        "local_root": str(root),
        "remote": "nas",
        "remote_root": "/mnt/tank/Creators_Club",
        "canonical_prefix": "P:\\",
        "active_project": "",
        "poll_interval": 3,
        "popup_enabled": False,
        "log_path": str(tmp_path / "companion.log"),
        "dashboard_url": "",
        "sync_enabled": False,
        "lane_b_enabled": False,
    }
    cfg.update(overrides)
    app = CompanionApp(cfg)
    app._require_login = False
    app.eula_problem = lambda: None
    return app


# -- 1: two doors onto one loopback bind (CR-149 follow-up) ----------------
#
# CMEDIA-3 gave the 8899 loopback a RETRY (it used to be tried once, at start,
# so quitting whatever held the port left the companion believing it was
# serving). The retry runs on the media-tree thread and start() binds on the
# main one, so for one release there were two callers and no lock: when the
# retry won the race, the second bind hit EADDRINUSE against OUR OWN listener,
# wrote None over the live handle, and left a listener nothing holds with
# `loopback.bound = false` for ever - and the tray advice naming the retired
# BRoll Companion as the squatter, which was us. Found by the CI build, not by
# the local gate (run 33788381735).


class _FakeListener:
    def __init__(self, port: int) -> None:
        self.port = port
        self.stopped = False

    def shutdown(self) -> None:
        self.stopped = True


class _OnePortOnly:
    """A `broll_server.start` that behaves like the operating system: the
    first bind takes the port, every later one fails with EADDRINUSE - which
    is what our own second door looked like from the inside."""

    def __init__(self) -> None:
        self.calls = 0
        self.listener: Optional[_FakeListener] = None

    def __call__(self, cfg, **kwargs):
        self.calls += 1
        if self.listener is not None:
            raise OSError(48, "address already in use")
        self.listener = _FakeListener(int(cfg.get("broll_server_port", 8899)))
        return self.listener


@pytest.mark.parametrize("doors", [
    # start() first, then the media-tree thread's retry a minute later.
    ("start", "retry"),
    # ...and the order the CI runner actually hit, where the retry got there
    # first: the fix has to hold whichever door reaches the lock first.
    ("retry", "start"),
])
def test_two_bind_doors_never_take_the_port_from_each_other(tmp_path, monkeypatch, doors):
    """CR-149 follow-up. The observable is the SAFE STATE, not the lock: one
    listener, still ours, and `sync_guard.loopback.bound` true - which is the
    only thing that tells an admin "Send to Resolve works on this machine"
    from "this machine believes it works".
    """
    factory = _OnePortOnly()
    monkeypatch.setattr(broll_server_mod, "start", factory)
    app = _chaos_app(tmp_path)

    for door in doors:
        if door == "start":
            app._start_broll_server()
        else:
            assert app.retry_loopback_bind() is True

    assert factory.calls == 1, "the second door bound against our own listener"
    assert app._broll_server is factory.listener, (
        "a failed second bind wrote None over the live handle (CR-149)")
    report = app.loopback_report()
    assert report["bound"] is True and report["error"] == ""


def test_two_threads_racing_the_bind_leave_one_listener(tmp_path, monkeypatch):
    """The same fault as a real race rather than a sequence. Whatever the
    interleaving, the answer must be identical: one bind, one listener, and a
    report that says the port is held."""
    factory = _OnePortOnly()
    monkeypatch.setattr(broll_server_mod, "start", factory)
    app = _chaos_app(tmp_path)
    ready = threading.Barrier(2, timeout=5)

    def _door(fn):
        def run():
            ready.wait()
            fn()
        return run

    threads = [threading.Thread(target=_door(app._start_broll_server)),
               threading.Thread(target=_door(app.retry_loopback_bind))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5)
        assert not thread.is_alive()

    assert factory.calls == 1
    assert app._broll_server is factory.listener
    assert app.loopback_report()["bound"] is True


# -- 2: a bind retry that arrives during shutdown (CR-149) ----------------


def test_a_retry_during_shutdown_leaves_the_port_alone(tmp_path, monkeypatch):
    """The other half of the same lock. A self-upgrade shuts this process
    down and the replacement is up within seconds; a retry that re-took 8899
    on the way out would leave the new build reading its own predecessor as a
    squatter and reporting `bound = false` for ever.

    Under-acting is the safe direction: no bind at all.
    """
    factory = _OnePortOnly()
    monkeypatch.setattr(broll_server_mod, "start", factory)
    app = _chaos_app(tmp_path)
    app._shutdown_started = True

    assert app.retry_loopback_bind() is False
    assert factory.calls == 0, "a teardown must not re-take the port it just released"
    assert app._broll_server is None


# -- 3: sync blocked while the tray is green (CR-149 APP-1) ---------------
#
# APP-1: `compute_overall_color` and the tooltip read five things and none of
# them was the one place that already knows why nothing is syncing. An EULA
# park (CR-27, which parked ruskin's three lanes twice), a rejected token or a
# tripped breaker left the icon its normal colour above a tooltip saying "up
# to date" - a claim made without ever asking whether syncing was ALLOWED.


@pytest.mark.parametrize("reason,inject", [
    # The licence park, which is CR-27's shape: an editor whose companion
    # self-upgraded into the EULA gate syncs nothing until they click, and
    # only the tray can tell them.
    ("licence_pending", "eula"),
    # ...and a machine nobody is signed in on, the other gate that stops
    # every lane before a lane can report anything at all.
    ("not_signed_in", "login"),
])
def test_a_blocked_machine_is_named_and_never_shows_green(tmp_path, reason, inject):
    """CR-149 APP-1. Two observables, and the icon is the one that matters:
    an editor does not read `sync_guard`, they read a colour."""
    app = _chaos_app(tmp_path)
    if inject == "eula":
        app.eula_problem = lambda: (
            "The licence agreement has not been accepted on this computer yet, "
            "so nothing is syncing")
    else:
        app._require_login = True
        app._login_gate_blocks_sync = lambda: True

    blocked = app.blocked_report(app.sync_guard())

    assert blocked is not None, "a machine that syncs nothing must say so"
    assert blocked["reason"] == reason
    assert blocked["detail"], "a reason with no sentence is a log line"

    # Every lane idle and no error anywhere: this is exactly the state that
    # used to paint green.
    idle = [LaneStatus(name=name, state=STATE_IDLE)
            for name in ("lane_a_rclone_up", "lane_b_rclone_down", "lane_c_syncthing")]
    assert compute_overall_color(idle, app, {"blocked": blocked}) != "green"


def test_a_machine_with_nothing_blocking_still_reaches_green(tmp_path):
    """The converse, and the reason the colour stays worth reading: a guard
    that answered "blocked" on a healthy machine would make amber permanent,
    which is how CR-139's findings-about-nothing stop a panel being read."""
    app = _chaos_app(tmp_path, sync_enabled=True)
    idle = [LaneStatus(name=name, state=STATE_IDLE)
            for name in ("lane_a_rclone_up", "lane_b_rclone_down", "lane_c_syncthing")]
    assert compute_overall_color(idle, app, {"blocked": None}) == "green"


# -- 4: an update pushed into work that is in flight ----------------------


class _CountingUpgrader:
    """Stands in for the upgrade manager. `apply` counts, because the whole
    property is that it is never reached."""

    def __init__(self) -> None:
        self.applies = 0
        self.available = {"version": "9.9.9", "url": "https://example.invalid/x"}

    def apply(self) -> bool:
        self.applies += 1
        return True

    def refusal(self):
        return None


@pytest.mark.parametrize("blocker,setup", [
    ("popup", "popup"),
    ("consolidate", "consolidate"),
])
def test_an_update_pushed_into_work_in_flight_is_refused(tmp_path, blocker, setup):
    """COMP-CORE-2 / AUDIT_2 CORE-H8: standing this process down mid-copy
    kills the spawned replacement inside `shutil.copy2`, leaving a partial
    `.ccsync-tmp` and a project where some clips are relinked and some are
    not. `commands.upgrade` and `auto_update` (MULTI_MACHINE_PLAN §9) both
    reach `apply_upgrade` without an editor present, so the stand-down test is
    the only thing between a fleet-wide push and that outcome.

    The observable is the REFUSAL plus the untouched exe: a swap that happened
    and then reported "popup" would be the bug wearing the fix's answer.
    """
    app = _chaos_app(tmp_path)
    upgrader = _CountingUpgrader()
    app.upgrade = upgrader
    if setup == "popup":
        app._popup_active_lock.acquire()
    else:
        app._consolidate_active = True

    try:
        # quiet_refusals=True is the pushed-update path: the toast belongs to
        # the click, not to a retry every minute while the window stays open.
        assert app.apply_upgrade(quiet_refusals=True) == blocker
        assert upgrader.applies == 0, "the exe was swapped under work in flight"
    finally:
        if setup == "popup":
            app._popup_active_lock.release()
        else:
            app._consolidate_active = False

    # ...and it is a STAND-DOWN, not a refusal that sticks: the same push a
    # minute later, with the window closed, installs.
    assert app.apply_upgrade(quiet_refusals=True) == ""
    assert upgrader.applies == 1


# -- 5: a worker thread collecting another thread's Tk cycle (CR-93) ------
#
# `_tkinter` frees the interpreter in `Tkapp_Dealloc`, inline, on whatever
# thread drops the last reference; from any other thread Tcl answers
# `Tcl_Panic` - abort(), no traceback, nothing in companion.log, the whole
# tray gone. The 2026-08-30 recurrence was exactly this shape: a dialog's
# nested functions in a REFERENCE CYCLE reaching `root`, collected by the
# cyclic GC on whichever thread tripped it (the watcher thread's library read,
# twice). So the fault injected here is the collection ITSELF, on a thread
# that built nothing.
#
# No real Tk: conftest `_no_real_tk_windows` fails any test that opens one,
# and the native proof (the real Tcl_AsyncDelete) lives in
# `test_tk_release_native.py`, which needs a display and a subprocess because
# the failure it demonstrates kills the interpreter. What is asserted here is
# the REGISTRY CONTRACT with the same fakes `test_ui_dispatch.py` uses, which
# is what makes it identical on Windows and on the macOS runner.


class _FakeInterp:
    """`root.tk` - the object whose deallocation is the abort."""


class _FakeTkRoot:
    def __init__(self) -> None:
        self.tk = _FakeInterp()
        self.destroyed = 0

    def title(self) -> str:
        return "CCSYNC.EXE"

    def winfo_exists(self) -> bool:
        return self.destroyed == 0

    def destroy(self) -> None:
        self.destroyed += 1


@pytest.fixture(autouse=True)
def _empty_tk_registry():
    ui_dispatch._reset_registry_for_tests()
    yield
    ui_dispatch._reset_registry_for_tests()


def _build_a_dialog_that_leaves_a_cycle(label: str) -> weakref.ReferenceType:
    """A dialog in its own frame, closed, leaving its closures pointing at
    each other and at `root` - the Settings-window shape, which relied on the
    frame ending to free them and does not."""
    root = _FakeTkRoot()
    ui_dispatch.adopt(root, label)
    interp = weakref.ref(root.tk)
    state: dict[str, Any] = {"closed": False}

    def _refresh():
        if not state["closed"]:
            return _refresh          # a self-cycle reaching root through _close
        return root

    def _close():
        state["closed"] = True
        state["refresh"] = _refresh
        root.destroy()

    _close()
    return interp


def test_a_worker_threads_collection_never_frees_another_threads_interpreter():
    """CR-93, the 2026-08-30 recurrence. A `gc.collect()` on a thread that
    built nothing must leave every interpreter it did not build ALIVE, however
    much garbage the collection finds: the pin (1.8 MB, deliberate) is the
    safe state and the abort is the alternative."""
    built: dict[str, Any] = {}
    ready = threading.Event()
    finish = threading.Event()

    def _builder():
        built["interp"] = _build_a_dialog_that_leaves_a_cycle("the settings window")
        # Deliberately no reclaim here: the dialog has ended and the cycle is
        # still garbage, which is the window the watcher thread collected in.
        ready.set()
        finish.wait(5)
        # The building thread, and only it, may free it.
        built["freed"] = ui_dispatch.reclaim_mine("the dialog ended")

    thread = threading.Thread(target=_builder, name="the tray's dialog thread")
    thread.start()
    assert ready.wait(5)

    # THE INJECTION: another thread trips the cyclic collector, exactly as the
    # watcher thread's library read did, twice.
    for _ in range(3):
        gc.collect()
    assert built["interp"]() is not None, (
        "another thread's collection freed a Tcl interpreter - that is the abort")
    assert len(ui_dispatch.pinned_records()) == 1
    assert ui_dispatch.reclaim_mine("a thread that built nothing") == 0

    finish.set()
    thread.join(5)
    assert not thread.is_alive()
    assert built["freed"] == 1, "the building thread must be able to free it"
    assert built["interp"]() is None
    assert ui_dispatch.pinned_records() == []


def test_a_release_asked_for_from_the_wrong_thread_frees_nothing():
    """The explicit half of the same rule. `release_root` from another thread
    destroys nothing and frees nothing - and says so, because a window that
    silently stayed open is how the first fix's blind spot survived."""
    built: dict[str, Any] = {}
    ready = threading.Event()
    finish = threading.Event()

    def _builder():
        root = _FakeTkRoot()
        ui_dispatch.adopt(root, "the fixer popup")
        built["root"] = root
        built["interp"] = weakref.ref(root.tk)
        ready.set()
        finish.wait(5)

    thread = threading.Thread(target=_builder, name="the fixer's thread")
    thread.start()
    assert ready.wait(5)

    assert ui_dispatch.release_root(built["root"], "the fixer popup") is False
    assert built["root"].destroyed == 0
    assert built["interp"]() is not None
    assert built["root"] in ui_dispatch.parked_roots()

    finish.set()
    thread.join(5)


# -- the registry ----------------------------------------------------------


WAVE2_FAULTS = {
    "two_bind_doors": "CR-149 (companion 0.9.66, CI run 33788381735)",
    "retry_during_shutdown": "CR-149",
    "blocked_but_green": "CR-149 APP-1 / CR-27",
    "update_into_work_in_flight": "COMP-CORE-2 / AUDIT_2 CORE-H8",
    "foreign_thread_collection": "CR-93",
}


def test_every_wave_two_injection_has_a_section():
    """The parent module's pin, on this file: SYS-10 asks for injections over
    the shapes of CR-125..CR-154, and a suite that quietly lost one of them
    would leave the count true in the report and false in the tree."""
    from pathlib import Path

    body = Path(__file__).read_text(encoding="utf-8")
    for number in range(1, 6):
        assert f"# -- {number}:" in body, f"no injection section for fault {number}"
    assert len(WAVE2_FAULTS) == 5
    for fault, closes in WAVE2_FAULTS.items():
        assert closes, f"{fault} closes no ledger entry"
