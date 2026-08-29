"""Fault injection: the companion half of SYS-18's nine chaos tests.

SYS-18 (resilience sweep 2026-08-28, `docs/RESILIENCE_SWEEP_2026-08-28.md`
item 43): thirteen suites, strong on LOGIC and near-silent on CONDITIONS.
The systems agent read the whole ledger as data and found that about 2 % of
entries were discovered by a test; every failure class in the sweep is a
fault a test could have induced in seconds and never did.

The seams were already there -- `popen_factory`, the reporter's `_http_post`,
the selection client's opener, `subprocess.run`, `_monotonic` -- so what this
module adds is not a harness, it is the INJECTIONS, one per class rather than
one per bug.

Two rules, and they are what makes these different from the unit tests next
door:

1. **Every test asserts an OBSERVABLE**, never an internal call: the state
   the lane reports, the sentence the tray shows, the file on disk the next
   boot reads, the notice a person is handed. A test that asserted "the
   guard function was called" would pass against a guard whose answer nobody
   surfaces, which is exactly the "green while dead" shape the sweep is
   about.
2. **Nothing here sleeps, spawns or reaches the network.** Clocks are
   injected, children are scripted, and every ceiling is crossed in
   milliseconds. A chaos suite that took a minute per fault would be run
   once.

Nine injections, seven of which land on the companion (7 and 8 are
server-side; see `dashboard/tests/chaos/test_fault_injection.py`).
"""

from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.error
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

import pytest

from ccsync_companion import config as config_mod
from ccsync_companion import reporter as reporter_mod
from ccsync_companion.app import CompanionApp, LaneWatchdog, WATCHDOG_STATE_FILENAME
from ccsync_companion.reporter import DashboardReporter
from ccsync_companion.selection import SelectionClient
from ccsync_companion.sync import lane_guard, rclone_lane
from ccsync_companion.sync.base import STATE_ERROR, STATE_PAUSED
from ccsync_companion.sync.rclone_lane import DIRECTION_DOWN, DIRECTION_UP, RcloneLane
from ccsync_companion.sync.sequencer import STATE_STOPPED, Sequencer


# -- the fault list --------------------------------------------------------
#
# Data, not prose: SYS-18 names nine injections and ties each to a ledger
# entry it closes, and the registry below is what lets the last test in this
# file fail when one of them is quietly dropped. `where` is the component
# that owns the assertion -- two of the nine are only observable on the
# server, and a chaos suite that silently covered seven would be the same
# kind of silence the sweep is about.


@dataclass(frozen=True)
class Fault:
    id: str
    injection: str
    closes: str
    where: str


FAULTS = (
    Fault("never_exits", "a popen_factory whose child never exits",
          "SYS-17 / CR-91b", "companion"),
    Fault("slow_clock", "a clock 20 minutes behind the server's",
          "SYS-4 / APP-13", "companion"),
    Fault("disk_full", "disk_usage answering 1 GB free", "SYS-5 / SYNC-7", "companion"),
    Fault("rejected_credential", "a report POST that 401s, then recovers",
          "APP-1 / DASH-2", "companion"),
    Fault("pass_raises", "the loop raising on its third pass", "SYS-2", "companion"),
    Fault("killed_mid_latch", "the process killed between an atomic latch's "
          "tmp-write and its replace", "class G (APP-3 / APP-4 / APP-11)", "companion"),
    Fault("undeclared_section", "a report carrying a section this dashboard "
          "does not declare", "SYS-3", "dashboard"),
    Fault("cloned_machine_id", "a second hostname reporting an existing machine_id",
          "SYS-9 / DASH-11", "dashboard"),
    Fault("empty_folder_list", "a listing that answers 200 with no folders at all",
          "CR-44 / CR-47 / DASH-4", "both"),
)

COMPANION_FAULTS = tuple(f for f in FAULTS if f.where in ("companion", "both"))


# -- shared doubles --------------------------------------------------------


class _ScriptedChild:
    """A stand-in for subprocess.Popen with a scripted exit.

    `never_exits=True` is injection 1: `wait()` raises TimeoutExpired for
    ever, which is what a child blocked in an uninterruptible kernel read
    looks like to the parent -- CR-91's Mac, whose external SSD stopped
    answering while rclone held `_run_lock`.
    """

    def __init__(self, lines=(), returncode: int = 0, never_exits: bool = False) -> None:
        self.stderr = iter(list(lines))
        self._returncode = returncode
        self._never_exits = never_exits
        self.terminated = False
        self.killed = False

    def wait(self, timeout=None) -> int:
        if self._never_exits:
            raise subprocess.TimeoutExpired(cmd="rclone", timeout=timeout)
        return self._returncode

    def poll(self):
        return None if self._never_exits else self._returncode

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True


def _factory(child, calls: Optional[list] = None):
    def make(cmd, **kwargs):
        if calls is not None:
            calls.append(cmd)
        return child
    return make


def _ticking_clock(step: float = 60.0) -> Callable[[], float]:
    """A monotonic clock that jumps `step` seconds every time it is read, so
    an hours-long ceiling is crossed inside one millisecond."""
    state = {"now": 0.0}

    def clock() -> float:
        state["now"] += step
        return state["now"]

    return clock


def _lane(tmp_path, direction=DIRECTION_UP, **kwargs) -> RcloneLane:
    # local_root must EXIST: an absent one is a disconnected drive to
    # _run_once_locked and every lane below would stand down for the wrong
    # reason (test_rclone_lane._make_lane's rule).
    (tmp_path / "local").mkdir(parents=True, exist_ok=True)
    return RcloneLane(
        direction=direction,
        local_root=str(tmp_path / "local"),
        remote="nas",
        remote_root="Creators_Club",
        state_dir=tmp_path / "state",
        **kwargs,
    )


@pytest.fixture(autouse=True)
def _rclone_is_installed(monkeypatch):
    """Every fault here is about a CONDITION, never about whether the
    developer's machine has an rclone on PATH."""
    monkeypatch.setattr(
        "ccsync_companion.sync.rclone_lane.rclone_available",
        lambda rclone_path: (True, rclone_path),
    )


# -- 1: a child that never exits (SYS-17 / CR-91b) -------------------------


@pytest.mark.parametrize("direction", [DIRECTION_UP, DIRECTION_DOWN])
def test_a_child_that_never_exits_ends_the_pass_red_rather_than_syncing_for_ever(
        tmp_path, direction):
    """CR-91b: lane A sat in `state=syncing, transferring=1, last_error=NULL`
    for 2 h 20 m holding `_run_lock`, so lane B never got a turn and the
    editor downloaded nothing all afternoon -- with the fleet grid green.

    The observable is the LANE REPORT, not the kill: a companion that killed
    the child and still reported `syncing` would have fixed nothing that the
    dashboard, the tray or the editor can see.
    """
    child = _ScriptedChild(never_exits=True)
    lane = _lane(tmp_path, direction=direction, popen_factory=_factory(child))
    lane._wait_poll_seconds = 0.01          # poll at once; the fake never exits
    lane._monotonic = _ticking_clock(60.0)  # ...and cover hours in milliseconds
    subpath = "Projects/2026/FF5/Animals"
    (Path(lane.local_root) / subpath).mkdir(parents=True)

    status = lane.run_once(subpath=subpath, max_duration_seconds=600)

    assert status.state == STATE_ERROR, "a wedged pass must not report as syncing"
    assert "killed" in (status.last_error or "")
    assert status.transferring == 0 and status.current_project is None

    # NEVER IN MEMORY ONLY: the editor's first move is to restart the tray,
    # and that must not erase the only evidence the machine has.
    record = json.loads(
        (tmp_path / "state" / rclone_lane.LANE_STALL_FILENAME).read_text(encoding="utf-8"))
    assert record["killed"] is True and record["seconds"] > 0
    # ...and it reaches the dashboard through the one guard section app.py
    # asks a lane for, whichever lane stalled.
    reader = _lane(tmp_path, direction=DIRECTION_DOWN, popen_factory=_factory(_ScriptedChild()))
    assert reader.sync_guard_report()["stalled"]["killed"] is True


def test_a_child_that_never_exits_but_keeps_moving_bytes_is_left_alone(tmp_path):
    """The other half of CR-91, and the reason this is not a timeout: SFTP
    uploads do not resume, so killing a 40 GB original at the ceiling would
    restart it from byte 0 every pass, for ever, leaving a `.partial` on the
    NAS each time."""
    tally = rclone_lane.RcloneRunTally()
    moved = {"n": 0}

    class _MovingChild(_ScriptedChild):
        def wait(self, timeout=None):
            moved["n"] += 1_000_000
            lane._handle_stderr_line(
                '{"level":"notice","msg":"","stats":{"bytes":%d,"totalBytes":9e12,'
                '"speed":1.0,"eta":99}}' % moved["n"], tally)
            return super().wait(timeout)

    child = _MovingChild(never_exits=True)
    lane = _lane(tmp_path, popen_factory=_factory(child))
    lane._wait_poll_seconds = 0.01

    # A bounded clock: 200 reads x 60 s is 3 h 20 m, far past both ceilings.
    reads = {"n": 0}

    def clock() -> float:
        reads["n"] += 1
        if reads["n"] > 200:
            raise _EnoughPolling()
        return reads["n"] * 60.0

    lane._monotonic = clock
    with pytest.raises(_EnoughPolling):
        lane._wait_with_watchdog(["rclone"], child, tally, 600)

    assert not (child.killed or child.terminated)
    assert lane.stall_record() is None, "a moving transfer is not a stall"


class _EnoughPolling(BaseException):
    """Ends the watchdog loop from inside the injected clock. A BaseException
    so the loop's own `except Exception` cannot swallow it."""


# -- 2: a clock 20 minutes slow (SYS-4 / APP-13) ---------------------------


SLOW_BY_SECONDS = 20 * 60


def test_a_clock_twenty_minutes_slow_is_measured_warned_and_named(tmp_path, caplog):
    """SYS-4: a slow clock makes lane B's `--min-age` exclude every file on
    the NAS. rclone exits 0, transfers nothing and the lane goes green, so
    the editor downloads NOTHING, indefinitely, with no error anywhere. The
    server's own `received_at` was already in every report reply and the
    companion threw it away.

    Injected at the wire, not at `time.time`: the reply is what the fix
    reads, and a fault injected into the stdlib would prove less.
    """
    served = time.time() + SLOW_BY_SECONDS   # the server is ahead => we are behind

    def slow_clock_post(url, payload, headers, timeout):
        return {"received_at": reporter_mod._iso_utc(served)}

    reporter = DashboardReporter(
        lambda: [], {"editor_name": "owen", "dashboard_url": "http://dash.example",
                     "dashboard_token": "tok"},
        http_post=slow_clock_post, state_dir=tmp_path / "state")

    with caplog.at_level("WARNING"):
        reporter.post_once(light=True)

    skew = reporter.clock_skew_seconds
    assert skew is not None and -SLOW_BY_SECONDS - 30 < skew < -SLOW_BY_SECONDS + 30
    assert any("clock" in m and "min-age" in m for m in caplog.messages), (
        "the log must name the consequence, not just the number")

    # The observable an ADMIN gets: one sentence at the top of the machine's
    # row, ahead of every lane state, saying lane B is not merely quiet.
    app = _chaos_app(tmp_path)
    app.reporter.clock_skew_seconds = skew
    blocked = app.blocked_report(app.sync_guard())
    assert blocked["reason"] == "clock_skew"
    assert "proxy download will not transfer" in blocked["detail"]

    # ...and the same sentence in the tray, which is where the editor is.
    from ccsync_companion.tray import _clock_skew_line

    line = _clock_skew_line(app.sync_guard())
    assert line and "clock" in line.lower()


# -- 3: 1 GB free (SYS-5 / SYNC-7) -----------------------------------------


ONE_GB = 1024 ** 3


def test_a_drive_with_one_gigabyte_free_parks_lane_b_instead_of_thrashing(tmp_path):
    """SYS-5 / SYNC-7 / UX-1: below the floor rclone failed ENOSPC per FILE,
    the lane went red with a raw rclone string, and `.ccsync-trash` (up to
    50 GB of recovery copies on the SAME volume) was never reclaimed, because
    the prune only ran at the tail of a HEALTHY pass. One `[ ALL ]` click
    filled a laptop.

    `paused`, deliberately not `error`: the machine is not broken, lanes A
    and C must keep running, and the fleet grid must not paint a red dot on
    an editor who simply needs to empty their Downloads folder.
    """
    floor = lane_guard.DiskFloorLatch(tmp_path / "floor.json", {})
    calls: list[list[str]] = []
    lane = _lane(tmp_path, direction=DIRECTION_DOWN, disk_floor=floor,
                 popen_factory=_factory(_ScriptedChild(), calls))
    lane._free_bytes_fn = lambda path: ONE_GB

    status = lane.run_once()

    assert calls == [], "no rclone may be spawned against a full drive"
    assert status.state == STATE_PAUSED
    assert floor.parked and "GB free" in floor.report()["reason"]

    # Persisted, so the restart an editor tries first cannot clear it, and
    # carried to the dashboard in the guard section.
    assert lane_guard.DiskFloorLatch(tmp_path / "floor.json", {}).parked
    assert lane.sync_guard_report()["disk_floor"]["parked"] is True


def test_a_measurement_that_fails_parks_nothing(tmp_path):
    """"Could not tell" is not "the disk is full" -- the direction this latch
    must never fail in, and the reason `check(None)` exists."""
    floor = lane_guard.DiskFloorLatch(tmp_path / "floor.json", {})
    calls: list[list[str]] = []
    lane = _lane(tmp_path, direction=DIRECTION_DOWN, disk_floor=floor,
                 popen_factory=_factory(_ScriptedChild(), calls))

    def raising(path):
        raise OSError("the volume stopped answering")

    lane._free_bytes_fn = raising
    lane.run_once()

    assert not floor.parked
    assert calls, "an unmeasurable disk must not stop the lane"


# -- 4: a report POST that 401s, then recovers -----------------------------


def _http_401(url, payload, headers, timeout):
    raise urllib.error.HTTPError(url, 401, "Unauthorized", {}, None)


def test_a_rejected_credential_is_counted_toasted_once_and_then_forgiven(tmp_path):
    """APP-1: a revoked token gave ONE warning and then DEBUG for ever, with
    three green lanes above it. The machine looked healthy and reported
    nothing for days.

    The observable is the health record the report itself carries -- the only
    channel through which an admin can tell a machine whose reports are being
    REJECTED from one that has nothing to say -- plus exactly one toast. Not
    per streak: a 401 does not clear by itself, and re-toasting it every
    interval trains the editor to dismiss it.
    """
    toasts: list[str] = []
    reporter = DashboardReporter(
        lambda: [], {"editor_name": "owen", "dashboard_url": "http://dash.example",
                     "dashboard_token": "tok"},
        http_post=_http_401, notify=toasts.append, state_dir=tmp_path / "state")

    for _ in range(3):
        with pytest.raises(urllib.error.HTTPError):
            reporter.post_once(light=True)

    health = reporter.health()
    assert health["last_status"] == "HTTP 401"
    assert health["consecutive_failures"] == 3
    assert health["last_success_at"] is None
    assert len(toasts) == 1 and "rejected" in toasts[0]

    # RECOVERY. The streak clears, the health record says so, and the toast
    # is re-armed so a SECOND revocation is announced too.
    reporter._http_post = lambda *a: {"received_at": reporter_mod._iso_utc(time.time())}
    reporter.post_once(light=True)
    assert reporter.health()["last_status"] == "ok"
    assert reporter.health()["consecutive_failures"] == 0
    assert reporter._auth_notified is False

    # ...and it survived the restart the editor performs while chasing it.
    revived = DashboardReporter(
        lambda: [], {"editor_name": "owen", "dashboard_url": "http://dash.example"},
        http_post=_http_401, state_dir=tmp_path / "state")
    assert revived.health()["last_status"] == "ok"


def test_a_rejected_selection_fetch_falls_back_to_the_cache_and_says_so(tmp_path):
    """The same 401, one endpoint over. GOTCHAS.md §12: the companion "falls
    back silently to its cached selection" -- so the sync plan an editor is
    running can be days old with nothing anywhere saying which. The source
    label is the whole point of the assertion: a fallback that cannot be told
    from a live answer is how a restored-from-backup dashboard silently
    reverts everyone's plan (SYS-19).
    """
    state = tmp_path / "state"
    state.mkdir(parents=True)
    plan = [{"slug": "ff5-animals", "rel_path": "2026/FF5/Animals", "position": 0}]
    answers = {"live": True}

    def flaky_get(url, headers, timeout):
        if not answers["live"]:
            raise urllib.error.HTTPError(url, 401, "Unauthorized", {}, None)
        return {"selection": plan}

    client = SelectionClient(
        {"editor_name": "owen", "dashboard_url": "http://dash.example",
         "dashboard_token": "tok"},
        state, http_get=flaky_get)
    # Set on the object, not through cfg: config.coerce_numeric REFUSES a
    # non-positive `selection_fetch_ttl` and substitutes 30 (correctly -- a
    # zero there would put the sequencer's 5 s poll back on the network).
    # Zero here is what makes the fault deterministic without a sleep.
    client.fetch_ttl = 0

    assert client.get() == (plan, "live")

    answers["live"] = False
    got, source = client.get()
    assert got == plan, "the last known plan must keep the lanes running"
    assert source == "cache", "a cached plan must never be reported as live"

    answers["live"] = True
    assert client.get()[1] == "live"


# -- 5: the loop raising on its third pass (SYS-2) -------------------------


class _NullLane:
    """The smallest thing the sequencer will drive: it is not what is under
    test here, the loop's own survival is."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.calls = 0

    def run_once(self, subpath=None, max_duration_seconds=None):
        self.calls += 1
        return None

    def arm(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def status(self):
        return None


class _NullReconciler:
    def reconcile(self, *a, **kw):
        return {}


class _NullAdmin:
    """Duck-typed: the Sequencer stores it, and no path this test reaches
    calls it."""

    def get_config(self):
        return {"folders": []}

    def system_status(self):
        return {"myID": ""}


def _chaos_sequencer(tmp_path) -> Sequencer:
    root = tmp_path / "root"
    root.mkdir(parents=True, exist_ok=True)
    # An ENABLED client, because `start()` returns without spawning a thread
    # for a companion with no dashboard_url -- and the fault under test is
    # about the thread. It answers an empty plan, so every iteration takes
    # the no-selection path: the cheapest loop that is still the real one.
    selection = SelectionClient(
        {"editor_name": "owen", "dashboard_url": "http://dash.example"},
        tmp_path / "state", http_get=lambda url, headers, timeout: {"selection": []})
    return Sequencer(
        _NullLane("lane_a"), _NullLane("lane_b"), _NullAdmin(), selection,
        {"local_root": str(root), "selection_poll_interval": 0.01,
         "project_rotation_seconds": 5.0, "sequencer_idle_seconds": 0.01},
        folder_status_poll_seconds=0.01,
        shared_folders=_NullReconciler(), borrowed_folders=_NullReconciler(),
    )


def _until(predicate, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return bool(predicate())


def test_a_pass_that_raises_costs_one_pass_and_is_reported(tmp_path):
    """SYS-2, first half. `_run` had no try/except around its loop body, so
    one OSError (a mapped P: dropping mid-pass is the observed one) killed
    the thread with `_state` frozen at its last value: the reporter kept
    posting that state every 30 s and the grid showed a healthy machine that
    had not moved a byte since. Self-healing is only half the fix -- a
    machine that needs restarting three times an hour has to be VISIBLE."""
    seq = _chaos_sequencer(tmp_path)
    passes = {"n": 0}
    real = seq._reconcile_shared_folders

    def flaky():
        passes["n"] += 1
        if passes["n"] == 3:
            raise OSError("[WinError 53] P:\\ is gone")
        return real()

    seq._reconcile_shared_folders = flaky
    try:
        seq.start()
        assert _until(lambda: passes["n"] >= 5)
    finally:
        seq.stop()

    assert seq.loop_failures() == 1
    assert seq.last_error() == "OSError: [WinError 53] P:\\ is gone"
    assert passes["n"] >= 5, "the loop must go on to the passes after the bad one"


# The thread really does die here, and `_run` RE-RAISES on purpose so
# threading.excepthook -- and through it crash_report -- still sees it. That
# is the contract, so the resulting PytestUnhandledThreadExceptionWarning is
# the test working, not a leak.
@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_a_thread_that_dies_anyway_is_restarted_recorded_and_reported(tmp_path):
    """SYS-2, second half: the scaffolding around the loop body can still
    fail, and when it does the thread really is gone. `LaneWatchdog` is the
    mirror of the dashboard's own `CollectorWatchdog`, which has supervised
    the collector for a year while nothing supervised this.

    The observable is threefold: `_state` reaches STOPPED (it is in a
    `finally` now, not after the `while`, which is the half that made a dead
    sequencer look busy), the restart is on DISK, and it rides the report as
    `sync_guard.restarts` with the exception that caused it.
    """
    seq = _chaos_sequencer(tmp_path)

    def boom():
        raise RuntimeError("the loop scaffolding exploded")

    seq._startup_unpause = boom
    seq.start()
    # No stop() here on purpose: `thread_died()` answers False for a
    # sequencer somebody STOPPED (a sign-out must never read as the fault the
    # watchdog exists to recover from), so stopping it would hide the very
    # condition under test.
    assert _until(lambda: not seq._thread.is_alive())

    assert seq.state == STATE_STOPPED, "a dead sequencer must not look busy"
    assert seq.thread_died() is True

    app = _chaos_app(tmp_path)
    app.sequencer = seq
    watchdog = LaneWatchdog(
        app, interval=0.0, state_path=tmp_path / "state" / WATCHDOG_STATE_FILENAME)
    try:
        assert watchdog.check() == ["sequencer"]
    finally:
        seq.stop()

    report = watchdog.report()["sequencer"]
    assert report["count_24h"] == 1
    assert report["last_error"] == "RuntimeError: the loop scaffolding exploded"
    # On disk, because a crash loop that restarts the whole companion must
    # not reset the counter that is the evidence of the crash loop.
    saved = json.loads(
        (tmp_path / "state" / WATCHDOG_STATE_FILENAME).read_text(encoding="utf-8"))
    assert saved["threads"]["sequencer"]["events"]


# -- 6: killed between an atomic latch's tmp-write and its replace ---------
#
# Class G, and this system has paid for it twice: `config.set_value`'s old
# in-place `write_text` left config.toml truncated-and-empty (ALL DEFAULTS on
# the next start: no local_root, no dashboard_url, no token, reinstall the
# only cure -- APP-4), and `secrets_boot.write_secret_file` truncated before
# writing so an ENOSPC left a key that `key_present` still called present.
#
# The kill is injected at `os.replace`, which is the instant the fault
# describes: the tmp file is fully written and the rename has not happened.
# What must be true afterwards is that the PREVIOUS committed value is what
# the next reader gets -- never a blank, never a truncation, never a partial.


class _ProcessKilled(BaseException):
    """Stands in for the process ending inside the write. A BaseException so
    a latch's own `except Exception:` cannot mistake it for an I/O error it
    is allowed to log and swallow."""


def _kill_at_replace(monkeypatch) -> None:
    """Every latch here commits through `os.replace`, so one patch is the
    kill for all three -- and patching the stdlib rather than each module's
    reference is what makes this a fault in the SYSTEM rather than a stub."""

    def killed(src, dst, *a, **kw):
        raise _ProcessKilled(f"killed before {dst} was replaced")

    monkeypatch.setattr(os, "replace", killed)


def _config_latch(tmp_path):
    path = tmp_path / "config.toml"
    config_mod.set_value(path, "mode", "editor")

    def write():
        config_mod.set_value(path, "mode", "base")

    return path, write, lambda: config_mod.load_config(path).get("mode")


def _stall_latch(tmp_path):
    path = tmp_path / "state" / rclone_lane.LANE_STALL_FILENAME
    rclone_lane.write_stall_record(path, {"lane": "A", "killed": True, "seconds": 11})

    def write():
        rclone_lane.write_stall_record(path, {"lane": "B", "killed": True, "seconds": 99})

    return path, write, lambda: (rclone_lane.read_stall_record(path) or {}).get("lane")


def _breaker_latch(tmp_path):
    path = tmp_path / "breaker.json"
    breaker = lane_guard.LaneBBreaker(path, {})
    breaker.trip("the NAS listed the tree as EMPTY")

    def write():
        lane_guard.LaneBBreaker(path, {}).resume("tray")

    return path, write, lambda: lane_guard.LaneBBreaker(path, {}).tripped


# Three latches, three subsystems, ONE idiom (tmp -> harden -> os.replace).
# The parameterisation is the point: class G is not a bug in one file, it is
# a property every latch in this system has to have.
LATCHES = {
    "config.toml": (_config_latch, "editor"),
    "lane_stall.json": (_stall_latch, "A"),
    "lane_b_breaker.json": (_breaker_latch, True),
}


@pytest.mark.parametrize("name", sorted(LATCHES))
def test_a_kill_between_tmp_write_and_replace_leaves_the_last_good_value(
        tmp_path, monkeypatch, name):
    """Class G. The rule CLAUDE.md states as "never make a safety latch
    in-memory-only" has a second half nobody wrote down: a latch that is
    durable but not ATOMIC is worse than one that is neither, because the
    torn value reads as data.

    Losing a live `sync_halt.json` mid-write releases a fleet halt on one
    machine; losing config.toml takes the machine's credentials with it.
    """
    build, previous = LATCHES[name]
    path, write, read = build(tmp_path)
    assert read() == previous

    _kill_at_replace(monkeypatch)
    with pytest.raises(_ProcessKilled):
        write()

    monkeypatch.undo()
    assert read() == previous, (
        f"{name} lost its committed value to a kill inside the write")
    assert path.exists(), f"{name} was left absent by an interrupted write"


@pytest.mark.parametrize("name", sorted(LATCHES))
def test_a_stray_tmp_file_left_by_the_kill_is_not_what_the_next_boot_reads(
        tmp_path, monkeypatch, name):
    """The debris half: a real kill leaves the fully-written `.tmp` behind,
    and it is still there on the next boot. Nothing may adopt it."""
    build, previous = LATCHES[name]
    path, write, read = build(tmp_path)

    _kill_at_replace(monkeypatch)
    with pytest.raises(_ProcessKilled):
        write()
    monkeypatch.undo()

    strays = [p for p in path.parent.glob(path.name + "*") if p != path]
    assert strays, "the injection did not actually leave a tmp file behind"
    assert read() == previous


# -- 9 (companion half): a listing that answers with no folders at all -----


def test_an_empty_remote_listing_parks_lane_b_before_a_byte_is_deleted(tmp_path):
    """CR-44 / CR-47: lane B is `rclone sync` DOWN, so a remote that lists
    EMPTY is an instruction to move every local proxy into the trash. On
    ruskin's machine (2026-08-19) a routine reorganisation cost 100 local
    copies before the breaker stopped it.

    `paused` and not `error` for the reason the disk floor is: lanes A and C
    keep running, and only a human clears it.
    """
    scope = "Projects/2026/FF5/Animals"
    breaker = lane_guard.LaneBBreaker(tmp_path / "breaker.json", {})
    breaker.check_remote(scope, ["A001.mov", "A002.mov", "Proxy"])  # the healthy pass
    calls: list[list[str]] = []
    lane = _lane(tmp_path, direction=DIRECTION_DOWN, breaker=breaker,
                 remote_list_fn=lambda cmd, timeout: "",
                 popen_factory=_factory(_ScriptedChild(), calls))

    status = lane.run_once(subpath=scope)

    assert calls == [], "no rclone may run against a remote that lists empty"
    assert status.state == STATE_PAUSED
    assert breaker.tripped and "EMPTY" in breaker.reason
    assert lane_guard.LaneBBreaker(tmp_path / "breaker.json", {}).tripped


def test_a_listing_that_FAILED_is_not_an_empty_one(tmp_path):
    """The distinction the whole probe turns on: a flapping tailnet must not
    need an operator to clear a breaker. rclone fails the run on its own."""
    scope = "Projects/2026/FF5/Animals"
    breaker = lane_guard.LaneBBreaker(tmp_path / "breaker.json", {})
    breaker.check_remote(scope, ["A001.mov", "A002.mov", "Proxy"])
    lane = _lane(tmp_path, direction=DIRECTION_DOWN, breaker=breaker,
                 remote_list_fn=lambda cmd, timeout: None,
                 popen_factory=_factory(_ScriptedChild()))

    lane.run_once(subpath=scope)

    assert not breaker.tripped


# -- the app under test ----------------------------------------------------


def _chaos_app(tmp_path, **overrides) -> CompanionApp:
    """A CompanionApp with the lanes inert and the two gates open.

    `require_login` and the licence gate are both about a machine nobody has
    onboarded; leaving them on would make every `blocked_report` assertion
    here measure the gate instead of the fault (test_app._unblocked_app's
    rule).
    """
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


# -- the registry itself ---------------------------------------------------


def test_every_companion_side_injection_has_a_test(request):
    """SYS-18 names NINE injections, each closing a class rather than a bug.
    A suite that quietly covered seven of them would be the same silence the
    sweep is about, so the list is data and this is the pin.

    The two dashboard-only faults are asserted in
    `dashboard/tests/chaos/test_fault_injection.py`, which carries the mirror
    of this test.
    """
    assert len(FAULTS) == 9, "SYS-18 names nine injections"
    assert {f.where for f in FAULTS} <= {"companion", "dashboard", "both"}
    body = Path(__file__).read_text(encoding="utf-8")
    # Each injection owns a numbered section header in this file, so the
    # registry cannot drift from what is actually exercised.
    missing = [f.id for f in COMPANION_FAULTS
               if f"# -- {FAULTS.index(f) + 1}" not in body]
    assert not missing, f"no injection section for {missing}"
    for fault in FAULTS:
        assert fault.closes, f"{fault.id} closes no ledger entry"
