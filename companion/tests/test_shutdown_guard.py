"""Tests for the shutdown warning (companion/src/ccsync_companion/shutdown_guard.py).

The window/message-pump half needs Windows and a real HWND; the half that
decides whether to interrupt someone's shutdown does not, and that is the
half that can ruin an evening either way. Both failure directions are
covered: a false block (traps the editor) and a missed block (loses hours of
upload).
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import threading
import time

import pytest

from ccsync_companion.shutdown_guard import (
    ES_CONTINUOUS,
    ES_SYSTEM_REQUIRED,
    MAX_REASON_CHARS,
    NS_TERMINATE_CANCEL,
    NS_TERMINATE_NOW,
    TERMINATE_EPISODE_SECONDS,
    KeepAwakeGuard,
    PendingTracker,
    ShutdownGuard,
    _DarwinKeepAwake,
    _DarwinShutdownGuard,
    _WindowsKeepAwake,
    _WindowsShutdownGuard,
    caffeinate_command,
    describe_pending,
    make_keep_awake_guard,
    make_shutdown_guard,
    should_cancel_terminate,
)
from ccsync_companion.sync.base import (
    STATE_ERROR,
    STATE_IDLE,
    STATE_PAUSED,
    STATE_SYNCING,
    LaneStatus,
)


# --- describe_pending ------------------------------------------------------

def test_idle_lanes_do_not_interrupt_the_shutdown():
    statuses = [LaneStatus(name="lane_a"), LaneStatus(name="lane_b")]
    assert describe_pending(statuses) is None


def test_no_lanes_at_all_does_not_interrupt():
    assert describe_pending([]) is None
    assert describe_pending(None) is None


def test_a_syncing_lane_produces_a_warning():
    statuses = [LaneStatus(name="lane_a", state=STATE_SYNCING)]
    reason = describe_pending(statuses)
    assert reason and "still syncing" in reason


def test_the_warning_names_what_is_left_and_how_long():
    statuses = [
        LaneStatus(
            name="lane_a",
            state=STATE_SYNCING,
            bytes_done=10 * 1024**3,
            bytes_total=33 * 1024**3,
            eta_seconds=4800,
        )
    ]
    reason = describe_pending(statuses)
    assert "23.0 GB left" in reason
    assert "about 1h 20m" in reason


def test_remaining_bytes_add_up_but_eta_takes_the_slowest_lane():
    """Lanes run concurrently. Summing their ETAs would overstate the wait,
    which pushes people towards switching off -- the opposite of the point."""
    statuses = [
        LaneStatus(name="lane_a", state=STATE_SYNCING,
                   bytes_done=0, bytes_total=1024**3, eta_seconds=600),
        LaneStatus(name="lane_c", state=STATE_SYNCING,
                   bytes_done=0, bytes_total=1024**3, eta_seconds=1800),
    ]
    reason = describe_pending(statuses)
    assert "2.0 GB left" in reason
    assert "about 30 min" in reason


def test_a_queued_backlog_counts_even_when_no_transfer_is_running():
    """Between rclone runs the lane is idle with items still to go. Switching
    off there is exactly as bad as switching off mid-file."""
    statuses = [LaneStatus(name="lane_a", state=STATE_IDLE, queued=3)]
    assert describe_pending(statuses) is not None


def test_a_paused_lane_never_blocks_the_shutdown():
    """Pause is the editor saying "not now". Nothing is in flight to lose."""
    statuses = [LaneStatus(name="lane_a", state=STATE_PAUSED, queued=9)]
    assert describe_pending(statuses) is None


def test_an_errored_lane_never_blocks_the_shutdown():
    """A lane that cannot sync will not sync any better for staying on."""
    statuses = [LaneStatus(name="lane_a", state=STATE_ERROR, queued=9,
                           last_error="ssh: connect failed")]
    assert describe_pending(statuses) is None


def test_one_busy_lane_is_enough_among_idle_ones():
    statuses = [
        LaneStatus(name="lane_a"),
        LaneStatus(name="lane_b", state=STATE_SYNCING),
        LaneStatus(name="lane_c", state=STATE_PAUSED),
    ]
    assert describe_pending(statuses) is not None


def test_a_finished_transfer_contributes_no_remaining_bytes():
    """bytes_done == bytes_total must not render as "0 B left"."""
    statuses = [LaneStatus(name="lane_a", state=STATE_SYNCING,
                           bytes_done=1024**3, bytes_total=1024**3)]
    reason = describe_pending(statuses)
    assert reason is not None
    assert "left" not in reason.split(".")[0]


def test_a_sub_minute_eta_is_left_out_rather_than_shown_as_zero():
    statuses = [LaneStatus(name="lane_a", state=STATE_SYNCING,
                           bytes_done=0, bytes_total=1024, eta_seconds=12)]
    reason = describe_pending(statuses)
    assert "about" not in reason


def test_the_reason_fits_what_windows_will_display():
    """ShutdownBlockReasonCreate fails past MAX_STR_BLOCKREASON, and failing
    to set a reason while still blocking gives a refusal with no explanation."""
    statuses = [LaneStatus(name="x" * 500, state=STATE_SYNCING,
                           bytes_done=1, bytes_total=10**15, eta_seconds=10**6)]
    reason = describe_pending(statuses)
    assert 0 < len(reason) <= MAX_REASON_CHARS


def test_a_malformed_status_does_not_decide_the_whole_question():
    class Broken:
        @property
        def state(self):
            raise RuntimeError("boom")

    statuses = [Broken(), LaneStatus(name="lane_a", state=STATE_SYNCING)]
    assert describe_pending(statuses) is not None


def test_only_malformed_statuses_allow_the_shutdown():
    class Broken:
        @property
        def state(self):
            raise RuntimeError("boom")

    assert describe_pending([Broken()]) is None


# --- B8: the logs have to go somewhere an admin can read ------------------

def test_this_modules_log_records_reach_the_ccsync_log():
    """B8 [verified]. This was the only module using
    logging.getLogger(__name__) -- "ccsync_companion.shutdown_guard", which
    setup_logging() attaches no handler to. Records propagated to the
    unconfigured root logger, and in the windowed (console=False) build
    stderr is None, so WARNING+ hit logging.lastResort and vanished while
    INFO/DEBUG never appeared at all. Both of this module's features became
    undiagnosable from companion.log or tray -> Copy diagnostics."""
    from ccsync_companion import shutdown_guard

    assert shutdown_guard.log.name == "ccsync.shutdown_guard"


def test_every_module_logs_under_the_ccsync_logger():
    """The general form of B8: setup_logging() only ever adds handlers to
    "ccsync", so a logger named anything else is a silently-discarded
    module."""
    import importlib
    import pkgutil

    import ccsync_companion

    offenders = []
    for info in pkgutil.walk_packages(ccsync_companion.__path__,
                                      ccsync_companion.__name__ + "."):
        try:
            module = importlib.import_module(info.name)
        except Exception:  # optional dependency (pystray/PIL) -- not our concern
            continue
        logger = getattr(module, "log", None)
        name = getattr(logger, "name", None)
        if name is None:
            continue
        if name != "ccsync" and not name.startswith("ccsync."):
            offenders.append(f"{info.name} -> {name}")
    assert offenders == [], f"these modules log where nothing is listening: {offenders}"


# --- B9: "busy" needs a liveness bound ------------------------------------

class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def _tracker(clock=None, **kw):
    clock = clock or _Clock()
    return PendingTracker(clock=clock, **kw), clock


def test_a_lane_that_has_just_gone_busy_always_counts():
    """The first sample starts the liveness clock -- a transfer must never be
    suppressed at the moment it starts."""
    tracker, _clock = _tracker()
    statuses = [LaneStatus(name="lane_c", state=STATE_SYNCING, queued=4)]
    assert tracker.describe(statuses) is not None


def test_a_lane_that_never_moves_stops_blocking_the_shutdown():
    """B9. Tailscale drops / the NAS goes off overnight with four unreceived
    files: lane C reports `syncing` from a NEED COUNT forever, so every
    shutdown was interrupted with zero bytes in flight and the machine was
    held awake until the companion restarted."""
    tracker, clock = _tracker(stale_seconds=180.0)
    statuses = [LaneStatus(name="lane_c", state=STATE_SYNCING, queued=4)]

    assert tracker.describe(statuses) is not None
    clock.advance(170)
    assert tracker.describe(statuses) is not None, "gave up while still inside the window"
    clock.advance(20)
    assert tracker.describe(statuses) is None


def test_a_lane_that_keeps_moving_keeps_blocking():
    """The other direction: a genuine slow overnight upload must keep the
    machine awake for as long as bytes keep arriving."""
    tracker, clock = _tracker(stale_seconds=180.0)
    done = [0]

    def statuses():
        return [LaneStatus(name="lane_a", state=STATE_SYNCING,
                           bytes_done=done[0], bytes_total=40 * 1024**3)]

    for _ in range(20):
        assert tracker.describe(statuses()) is not None
        clock.advance(170)
        done[0] += 1024**3


def test_a_dropping_queue_counts_as_movement_for_a_lane_with_no_byte_counts():
    """Lane C reports no byte totals at all, so the need count falling is the
    only progress it can ever show."""
    tracker, clock = _tracker(stale_seconds=100.0)
    for queued in (9, 8, 7, 6):
        assert tracker.describe(
            [LaneStatus(name="lane_c", state=STATE_SYNCING, queued=queued)]
        ) is not None
        clock.advance(90)


def test_a_stalled_lane_starts_counting_again_once_it_moves():
    tracker, clock = _tracker(stale_seconds=100.0)
    stuck = [LaneStatus(name="lane_c", state=STATE_SYNCING, queued=4)]
    tracker.describe(stuck)
    clock.advance(200)
    assert tracker.describe(stuck) is None
    assert tracker.describe(
        [LaneStatus(name="lane_c", state=STATE_SYNCING, queued=3)]
    ) is not None


def test_going_idle_re_arms_the_grace_period():
    """A lane that finishes and later starts a fresh transfer must not
    inherit the stale timestamp of the last one."""
    tracker, clock = _tracker(stale_seconds=100.0)
    busy = [LaneStatus(name="lane_a", state=STATE_SYNCING, queued=1)]
    tracker.describe(busy)
    clock.advance(200)
    assert tracker.describe(busy) is None

    tracker.describe([LaneStatus(name="lane_a")])  # idle -- forget it
    clock.advance(10)
    assert tracker.describe(busy) is not None


def test_a_lane_with_no_connected_peer_is_a_backlog_not_a_transfer():
    """Lane C sets STATE_SYNCING purely from need counts, independent of
    whether any device is actually connected."""
    tracker, _clock = _tracker()
    statuses = [LaneStatus(name="lane_c", state=STATE_SYNCING, queued=4)]
    assert tracker.describe(statuses, {"lane_c": False}) is None
    assert tracker.describe(statuses, {"lane_c": True}) is not None


def test_an_unknown_peer_state_never_silences_the_warning():
    """"Can't tell" must behave exactly like the old code -- lanes A and B
    have no connectivity signal at all."""
    tracker, _clock = _tracker()
    statuses = [LaneStatus(name="lane_a", state=STATE_SYNCING, queued=1)]
    assert tracker.describe(statuses, {}) is not None
    assert tracker.describe(statuses, {"lane_a": None}) is not None
    assert tracker.describe(statuses, None) is not None


def test_peer_state_can_come_from_the_status_itself():
    """Forward compatibility: a LaneStatus that grows a peer_connected field
    needs no change in here."""
    class _Status:
        name = "lane_c"
        state = STATE_SYNCING
        queued = 4
        peer_connected = False

    tracker, _clock = _tracker()
    assert tracker.describe([_Status()]) is None


def test_one_disconnected_lane_does_not_silence_a_live_one():
    tracker, _clock = _tracker()
    statuses = [
        LaneStatus(name="lane_c", state=STATE_SYNCING, queued=4),
        LaneStatus(name="lane_a", state=STATE_SYNCING, queued=1),
    ]
    assert tracker.describe(statuses, {"lane_c": False}) is not None


def test_the_hold_ceiling_eventually_stands_down():
    """The backstop staleness cannot see: a lane whose numbers churn but
    never finish (rclone wedged in SFTP retries) would otherwise hold the
    idle timer for days."""
    tracker, clock = _tracker(stale_seconds=100.0, max_hold_seconds=3600.0)
    done = [0]
    blocked_for = 0.0
    while True:
        done[0] += 1
        reason = tracker.describe(
            [LaneStatus(name="lane_a", state=STATE_SYNCING, bytes_done=done[0],
                        bytes_total=10**12)]
        )
        if reason is None:
            break
        clock.advance(60)
        blocked_for += 60
        assert blocked_for <= 3660, "the ceiling never fired"
    assert blocked_for >= 3600


def test_the_ceiling_resets_once_everything_is_idle():
    tracker, clock = _tracker(stale_seconds=100.0, max_hold_seconds=600.0)
    busy = [LaneStatus(name="lane_a", state=STATE_SYNCING, queued=1)]
    tracker.describe(busy)
    clock.advance(700)
    tracker.describe([LaneStatus(name="lane_a")])  # settled
    clock.advance(10)
    assert tracker.describe(busy) is not None


def test_the_tracker_agrees_with_describe_pending_on_a_live_snapshot():
    tracker, _clock = _tracker()
    statuses = [LaneStatus(name="lane_a", state=STATE_SYNCING,
                           bytes_done=10 * 1024**3, bytes_total=33 * 1024**3,
                           eta_seconds=4800)]
    assert tracker.describe(statuses) == describe_pending(statuses)


def test_paused_and_errored_lanes_are_still_never_blocking():
    tracker, _clock = _tracker()
    assert tracker.describe([LaneStatus(name="a", state=STATE_PAUSED, queued=9)]) is None
    assert tracker.describe([LaneStatus(name="b", state=STATE_ERROR, queued=9)]) is None


def test_a_tracker_that_blows_up_allows_the_shutdown():
    """Every failure path in the liveness check means "not blocking": a bug
    in here must be able to cost a warning, never to trap someone."""
    def boom():
        raise RuntimeError("clock exploded")

    tracker = PendingTracker(clock=boom)
    assert tracker.describe([LaneStatus(name="a", state=STATE_SYNCING)]) is None


@pytest.mark.parametrize("bad", [0, -1, "soon", None, [180]])
def test_a_bad_threshold_falls_back_to_the_shipped_default(bad):
    """Both thresholds are hand-editable config keys. This is the layer that
    would MISBEHAVE rather than crash on a bad one: a stale window of 0 marks
    every lane stalled on its second sample, i.e. it silently switches both
    guards off."""
    from ccsync_companion import shutdown_guard

    tracker = PendingTracker(stale_seconds=bad, max_hold_seconds=bad)
    assert tracker._stale_seconds == shutdown_guard.PROGRESS_STALE_SECONDS
    assert tracker._max_hold_seconds == shutdown_guard.MAX_HOLD_SECONDS


def test_a_zero_stale_window_does_not_silently_disable_the_guards():
    clock = _Clock()
    tracker = PendingTracker(stale_seconds=0, clock=clock)
    statuses = [LaneStatus(name="lane_c", state=STATE_SYNCING, queued=4)]
    tracker.describe(statuses)
    clock.advance(30)
    assert tracker.describe(statuses) is not None, "a 0 config value switched the guard off"


def test_tuned_thresholds_are_honoured():
    tracker, clock = _tracker(stale_seconds=30.0)
    statuses = [LaneStatus(name="lane_c", state=STATE_SYNCING, queued=4)]
    assert tracker.describe(statuses) is not None
    clock.advance(31)
    assert tracker.describe(statuses) is None


def test_the_tracker_does_not_grow_without_bound():
    tracker, clock = _tracker()
    for n in range(50):
        tracker.describe([LaneStatus(name=f"lane_{n}", state=STATE_SYNCING, queued=1)])
        clock.advance(1)
    assert len(tracker._seen) == 1


# --- the WM_QUERYENDSESSION policy ----------------------------------------

def _guard(reason_fn, calls=None):
    calls = calls if calls is not None else []
    return _WindowsShutdownGuard(
        reason_fn,
        block_fn=lambda hwnd, reason: calls.append(("block", hwnd, reason)),
        unblock_fn=lambda hwnd: calls.append(("unblock", hwnd)),
    ), calls


def test_nothing_pending_allows_the_shutdown_and_sets_no_reason():
    guard, calls = _guard(lambda: None)
    assert guard.handle_query_end_session(42) == 1
    assert calls == []


def test_something_pending_blocks_and_sets_the_reason():
    guard, calls = _guard(lambda: "still syncing")
    assert guard.handle_query_end_session(42) == 0
    assert calls == [("block", 42, "still syncing")]


def test_a_crashing_reason_callback_allows_the_shutdown():
    """The one thing this feature must never do is trap someone at a machine
    that will not turn off because of a bug in the guard itself."""
    def boom():
        raise RuntimeError("kaboom")

    guard, calls = _guard(boom)
    assert guard.handle_query_end_session(42) == 1


def test_a_reason_that_cannot_be_set_allows_the_shutdown():
    """Blocking with no text = "this app is preventing shutdown" and no
    explanation. Better to let it through."""
    def explode(hwnd, reason):
        raise OSError("ShutdownBlockReasonCreate failed")

    guard = _WindowsShutdownGuard(lambda: "still syncing", block_fn=explode)
    assert guard.handle_query_end_session(42) == 1


def test_the_reason_is_truncated_before_it_reaches_windows():
    guard, calls = _guard(lambda: "z" * 4000)
    assert guard.handle_query_end_session(42) == 0
    assert len(calls[0][2]) == MAX_REASON_CHARS


def test_a_block_is_withdrawn_once_the_sync_finishes():
    """First shutdown attempt blocks; the sync completes; the second attempt
    must both allow it AND clear the reason, or the block screen keeps
    quoting a sync that is long done."""
    pending = ["still syncing"]
    guard, calls = _guard(lambda: pending[0])
    assert guard.handle_query_end_session(7) == 0
    pending[0] = None
    assert guard.handle_query_end_session(7) == 1
    assert calls == [("block", 7, "still syncing"), ("unblock", 7)]


def test_nothing_is_unblocked_that_was_never_blocked():
    guard, calls = _guard(lambda: None)
    guard.handle_query_end_session(7)
    guard.handle_query_end_session(7)
    assert calls == []


def test_a_crash_after_a_block_still_withdraws_the_reason():
    state = {"raise": False}

    def reason():
        if state["raise"]:
            raise RuntimeError("boom")
        return "still syncing"

    guard, calls = _guard(reason)
    assert guard.handle_query_end_session(7) == 0
    state["raise"] = True
    assert guard.handle_query_end_session(7) == 1
    assert ("unblock", 7) in calls


# --- construction ----------------------------------------------------------

def test_the_guard_is_a_no_op_when_switched_off():
    guard = make_shutdown_guard(lambda: "syncing", enabled=False)
    assert type(guard) is ShutdownGuard
    guard.start()
    guard.stop()
    assert guard.active is False


def test_macos_gets_the_darwin_guard(monkeypatch):
    """Macs used to get nothing at all: no warning on Quit, and a logout that
    killed the companion where it stood."""
    monkeypatch.setattr(sys, "platform", "darwin")
    guard = make_shutdown_guard(lambda: "syncing", enabled=True)
    assert isinstance(guard, _DarwinShutdownGuard)


def test_the_darwin_guard_is_a_no_op_when_switched_off(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    guard = make_shutdown_guard(lambda: "syncing", enabled=False)
    assert type(guard) is ShutdownGuard


def test_no_op_on_platforms_with_no_guard(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    assert type(make_shutdown_guard(lambda: "syncing", enabled=True)) is ShutdownGuard


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only guard")
def test_the_real_guard_is_built_on_windows():
    guard = make_shutdown_guard(lambda: None, enabled=True)
    assert isinstance(guard, _WindowsShutdownGuard)


@pytest.mark.skipif(sys.platform != "win32", reason="needs a real HWND")
def test_the_window_really_comes_up_and_goes_away():
    """The ctypes half: RegisterClassW/CreateWindowExW/GetMessageW actually
    working, which no amount of injected fakes can tell us."""
    guard = make_shutdown_guard(lambda: None, enabled=True)
    guard.start()
    try:
        assert guard.active, "no window -- editors would get no warning at all"
    finally:
        guard.stop()
    assert guard.active is False


@pytest.mark.skipif(sys.platform != "win32", reason="needs a real HWND")
def test_a_real_window_answers_query_end_session_without_crashing():
    """Exercises the genuine ShutdownBlockReasonCreate/Destroy pair against a
    live HWND, then clears it -- if this leaked, the machine would refuse to
    shut down for a process that has exited."""
    guard = make_shutdown_guard(lambda: "CCSync test -- ignore", enabled=True)
    guard.start()
    try:
        assert guard.active
        assert guard.handle_query_end_session(guard._hwnd) == 0
        guard._clear_block(guard._hwnd)
    finally:
        guard.stop()


def test_stopping_a_guard_that_never_started_is_harmless():
    guard = _WindowsShutdownGuard(lambda: None)
    guard.stop()
    assert guard.active is False


def test_a_guard_whose_pump_died_can_be_started_again(monkeypatch):
    """The pump thread ends on ANY failure inside it (ctypes unavailable,
    RegisterClassW/CreateWindowExW failing, the message loop raising) and
    used to leave a dead Thread object in _thread -- so start() early-returned
    forever, `active` quietly reported False, and (before the logger fix) the
    exception explaining it went nowhere."""
    guard = _WindowsShutdownGuard(lambda: None)
    attempts = []

    def dead_pump():
        attempts.append(1)
        guard._ready.set()  # exactly what the real failure paths do

    monkeypatch.setattr(guard, "_pump", dead_pump)

    guard.start()
    deadline = time.monotonic() + 5.0
    while guard._thread is not None and guard._thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.01)
    guard.start()

    assert len(attempts) == 2, "a guard with a dead pump was never restartable"


def test_a_live_guard_is_not_started_twice(monkeypatch):
    guard = _WindowsShutdownGuard(lambda: None)
    started = []
    running = threading.Event()

    def slow_pump():
        started.append(1)
        guard._ready.set()
        running.wait(5.0)

    monkeypatch.setattr(guard, "_pump", slow_pump)
    guard.start()
    try:
        guard.start()
        assert len(started) == 1
    finally:
        running.set()


def test_a_keep_awake_whose_loop_died_can_be_started_again(monkeypatch):
    guard, _fake = _keep_awake(lambda: False)
    attempts = []
    monkeypatch.setattr(guard, "_loop", lambda: attempts.append(1))

    guard.start()
    deadline = time.monotonic() + 5.0
    while guard._thread is not None and guard._thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.01)
    guard.start()

    assert len(attempts) == 2


@pytest.mark.skipif(sys.platform != "win32", reason="needs a real window class")
def test_the_window_class_and_its_wndproc_are_given_back_on_stop():
    """RegisterClassW registers CLASS NAME -> our ctypes callback for the
    whole PROCESS. stop() used to leave both in place, so a second guard took
    the ERROR_CLASS_ALREADY_EXISTS branch and its CreateWindowExW dispatched
    WM_NCCREATE into the first guard's callback -- which may by then have been
    garbage-collected. Non-deterministic, and exactly what a
    build/start/stop/drop sequence sets up."""
    guard = make_shutdown_guard(lambda: None, enabled=True)
    guard.start()
    assert guard.active
    assert guard._class_registered is True
    guard.stop()
    assert guard._class_registered is False
    assert guard._wndproc_ref is None


@pytest.mark.skipif(sys.platform != "win32", reason="needs a real window class")
def test_a_second_guard_registers_its_own_class_after_the_first_stops():
    first = make_shutdown_guard(lambda: None, enabled=True)
    first.start()
    first.stop()
    second = make_shutdown_guard(lambda: None, enabled=True)
    second.start()
    try:
        assert second.active, "the second guard got no window -- no warning at all"
        assert second._class_registered is True, "it reused a callback nobody holds"
    finally:
        second.stop()


# --- keep-awake ------------------------------------------------------------

class _FakeExecutionState:
    """Stand-in for SetThreadExecutionState: records flags, returns the
    previous state like the real one (0 means failure)."""

    def __init__(self, fail=False):
        self.calls: list[int] = []
        self.fail = fail

    def __call__(self, flags: int) -> int:
        self.calls.append(flags)
        return 0 if self.fail else ES_CONTINUOUS


def _keep_awake(busy_fn, fake=None):
    fake = fake or _FakeExecutionState()
    return _WindowsKeepAwake(busy_fn, set_state_fn=fake, poll_seconds=0.01), fake


def test_a_busy_lane_holds_off_the_idle_timer():
    guard, fake = _keep_awake(lambda: True)
    assert guard.apply_once() is True
    assert fake.calls == [ES_CONTINUOUS | ES_SYSTEM_REQUIRED]


def test_the_display_is_never_held_awake():
    """ES_DISPLAY_REQUIRED would leave editors with a screen that refuses to
    blank all night. We are keeping the upload alive, not the monitor."""
    guard, fake = _keep_awake(lambda: True)
    guard.apply_once()
    assert all(not (flags & 0x00000002) for flags in fake.calls)


def test_es_continuous_is_always_set():
    """Without ES_CONTINUOUS the call nudges the idle timer once instead of
    holding it -- the subtly-broken version that looks like it works."""
    guard, fake = _keep_awake(lambda: True)
    guard.apply_once()
    assert all(flags & ES_CONTINUOUS for flags in fake.calls)


def test_an_idle_machine_is_left_alone_entirely():
    guard, fake = _keep_awake(lambda: False)
    assert guard.apply_once() is False
    assert fake.calls == []


def test_the_idle_timer_is_released_when_the_sync_finishes():
    busy = [True]
    guard, fake = _keep_awake(lambda: busy[0])
    guard.apply_once()
    busy[0] = False
    assert guard.apply_once() is False
    assert fake.calls == [ES_CONTINUOUS | ES_SYSTEM_REQUIRED, ES_CONTINUOUS]


def test_windows_is_only_called_when_the_answer_changes():
    """Re-asserting every poll works but churns powercfg's requests list,
    burying any real diagnosis in noise."""
    guard, fake = _keep_awake(lambda: True)
    for _ in range(5):
        guard.apply_once()
    assert len(fake.calls) == 1


def test_a_crashing_busy_check_lets_the_machine_sleep():
    """Failing the other way would keep an editor's PC awake all night."""
    def boom():
        raise RuntimeError("kaboom")

    guard, fake = _keep_awake(boom)
    assert guard.apply_once() is False
    assert fake.calls == []


def test_a_failed_call_is_not_recorded_as_held():
    """SetThreadExecutionState returns 0 on failure. Believing it worked
    would mean never issuing the release, and never retrying."""
    guard, fake = _keep_awake(lambda: True, _FakeExecutionState(fail=True))
    assert guard.apply_once() is False
    assert guard.held is False


def test_a_failed_call_is_retried_on_the_next_poll():
    fake = _FakeExecutionState(fail=True)
    guard, _ = _keep_awake(lambda: True, fake)
    guard.apply_once()
    guard.apply_once()
    assert len(fake.calls) == 2


def test_a_raising_call_leaves_the_state_unheld():
    def explode(flags):
        raise OSError("SetThreadExecutionState blew up")

    guard = _WindowsKeepAwake(lambda: True, set_state_fn=explode)
    assert guard.apply_once() is False


def test_the_loop_releases_the_idle_timer_when_it_stops():
    """A thread that dies still holding ES_SYSTEM_REQUIRED is the failure
    that leaves a machine unable to sleep with nothing left to sync."""
    guard, fake = _keep_awake(lambda: True)
    guard.start()
    deadline = time.monotonic() + 5.0
    while not guard.held and time.monotonic() < deadline:
        time.sleep(0.01)
    assert guard.held, "never took the idle timer"
    guard.stop()
    assert guard.held is False
    assert fake.calls[0] == ES_CONTINUOUS | ES_SYSTEM_REQUIRED
    assert fake.calls[-1] == ES_CONTINUOUS


def test_the_loop_notices_a_sync_finishing_without_being_stopped():
    busy = [True]
    guard, fake = _keep_awake(lambda: busy[0])
    guard.start()
    try:
        deadline = time.monotonic() + 5.0
        while not guard.held and time.monotonic() < deadline:
            time.sleep(0.01)
        assert guard.held
        busy[0] = False
        deadline = time.monotonic() + 5.0
        while guard.held and time.monotonic() < deadline:
            time.sleep(0.01)
        assert guard.held is False, "held the idle timer after the sync finished"
    finally:
        guard.stop()


def test_stopping_a_keep_awake_that_never_started_is_harmless():
    guard, fake = _keep_awake(lambda: True)
    guard.stop()
    assert guard.held is False
    assert fake.calls == []


def test_starting_twice_runs_one_loop():
    guard, fake = _keep_awake(lambda: False)
    guard.start()
    first = guard._thread
    guard.start()
    try:
        assert guard._thread is first
    finally:
        guard.stop()


def test_keep_awake_is_a_no_op_when_switched_off():
    guard = make_keep_awake_guard(lambda: True, enabled=False)
    assert type(guard) is KeepAwakeGuard
    guard.start()
    guard.stop()
    assert guard.held is False


def test_macos_gets_the_darwin_keep_awake(monkeypatch):
    """A Mac that idles into sleep mid-upload loses the same hours a Windows
    box does, and caffeinate -i is the same request ES_SYSTEM_REQUIRED is."""
    monkeypatch.setattr(sys, "platform", "darwin")
    assert isinstance(make_keep_awake_guard(lambda: True), _DarwinKeepAwake)


def test_the_darwin_keep_awake_is_a_no_op_when_switched_off(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    assert type(make_keep_awake_guard(lambda: True, enabled=False)) is KeepAwakeGuard


def test_keep_awake_is_a_no_op_on_platforms_with_no_guard(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    assert type(make_keep_awake_guard(lambda: True)) is KeepAwakeGuard


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only guard")
def test_the_real_keep_awake_talks_to_windows():
    """The genuine SetThreadExecutionState, taken and released -- no fakes.
    Verified by powercfg elsewhere; here we only assert it does not fail."""
    guard = make_keep_awake_guard(lambda: True)
    guard.start()
    try:
        deadline = time.monotonic() + 5.0
        while not guard.held and time.monotonic() < deadline:
            time.sleep(0.01)
        assert guard.held, "Windows refused ES_SYSTEM_REQUIRED"
    finally:
        guard.stop()
    assert guard.held is False


# --- macOS: caffeinate instead of SetThreadExecutionState -------------------
#
# Every one of these runs on Windows with no pyobjc and no /usr/bin: the
# child process is injected, so what is under test is the policy, which is
# the half that decides whether a Mac sleeps on top of a live upload.

class _FakeCaffeinate:
    """Stand-in for the caffeinate child: Popen's four-method surface."""

    def __init__(self, ignore_terminate: bool = False):
        self.returncode = None
        self.terminated = 0
        self.killed = 0
        self.waits: list = []
        self.ignore_terminate = ignore_terminate

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated += 1
        if not self.ignore_terminate:
            self.returncode = -signal.SIGTERM

    def kill(self):
        self.killed += 1
        self.returncode = -9

    def wait(self, timeout=None):
        self.waits.append(timeout)
        if self.returncode is None:
            raise subprocess.TimeoutExpired("caffeinate", timeout)
        return self.returncode

    def die(self, returncode: int = 0):
        """The child going away on its own, with us none the wiser."""
        self.returncode = returncode


class _FakeSpawner:
    def __init__(self, error: Exception = None, returns=_FakeCaffeinate):
        self.argvs: list = []
        self.children: list = []
        self.error = error
        self.returns = returns

    def __call__(self, argv):
        self.argvs.append(list(argv))
        if self.error is not None:
            raise self.error
        if self.returns is None:
            return None
        child = self.returns()
        self.children.append(child)
        return child


def _darwin_keep_awake(busy_fn, spawner=None, **kw):
    spawner = spawner if spawner is not None else _FakeSpawner()
    kw.setdefault("poll_seconds", 0.01)
    kw.setdefault("stop_grace_seconds", 0.05)
    return _DarwinKeepAwake(busy_fn, spawn_fn=spawner, **kw), spawner


def test_the_caffeinate_command_asks_for_idle_sleep_only():
    """-d is ES_DISPLAY_REQUIRED's twin: it would leave editors with a screen
    that refuses to blank all night. We are keeping the upload alive."""
    argv = caffeinate_command()
    assert argv[0].endswith("caffeinate")
    assert "-i" in argv
    assert "-d" not in argv


def test_caffeinate_is_told_to_die_with_the_companion():
    """-w <our pid>: a companion that is SIGKILLed never gets to terminate
    the child, and a forgotten caffeinate keeps a Mac awake until reboot."""
    argv = caffeinate_command()
    assert argv[argv.index("-w") + 1] == str(os.getpid())
    assert caffeinate_command(1234)[-1] == "1234"


def test_a_busy_lane_starts_caffeinate():
    guard, spawner = _darwin_keep_awake(lambda: True)
    assert guard.apply_once() is True
    assert spawner.argvs == [caffeinate_command()]


def test_an_idle_mac_is_left_alone_entirely():
    guard, spawner = _darwin_keep_awake(lambda: False)
    assert guard.apply_once() is False
    assert spawner.argvs == []


def test_caffeinate_is_started_once_not_every_poll():
    guard, spawner = _darwin_keep_awake(lambda: True)
    for _ in range(5):
        guard.apply_once()
    assert len(spawner.argvs) == 1


def test_caffeinate_is_stopped_when_the_sync_finishes():
    busy = [True]
    guard, spawner = _darwin_keep_awake(lambda: busy[0])
    guard.apply_once()
    child = spawner.children[0]
    busy[0] = False
    assert guard.apply_once() is False
    assert child.terminated == 1
    assert child.killed == 0
    assert guard.held is False


def test_a_caffeinate_that_ignores_sigterm_is_killed():
    """It holds the idle timer for as long as it lives, so "it did not stop"
    cannot be where we give up -- that is a Mac that never sleeps again."""
    busy = [True]
    spawner = _FakeSpawner(returns=lambda: _FakeCaffeinate(ignore_terminate=True))
    guard, _ = _darwin_keep_awake(lambda: busy[0], spawner)
    guard.apply_once()
    child = spawner.children[0]
    busy[0] = False
    guard.apply_once()
    assert child.terminated == 1
    assert child.killed == 1


def test_a_caffeinate_that_died_on_its_own_is_replaced():
    """The child can go away without us (killed, missing binary on a
    stripped image). Believing we still hold the idle timer would let the
    Mac sleep on top of a live transfer."""
    guard, spawner = _darwin_keep_awake(lambda: True)
    guard.apply_once()
    spawner.children[0].die(0)
    assert guard.apply_once() is True
    assert len(spawner.argvs) == 2


def test_an_unpollable_child_is_treated_as_gone():
    class _Unpollable(_FakeCaffeinate):
        def poll(self):
            raise OSError("no such process")

    spawner = _FakeSpawner(returns=_Unpollable)
    guard, _ = _darwin_keep_awake(lambda: True, spawner)
    guard.apply_once()
    guard.apply_once()
    assert len(spawner.argvs) == 2, "a phantom hold costs a night's upload"


def test_a_failed_spawn_lets_the_mac_sleep_rather_than_raising(caplog):
    """No caffeinate on this image, or fork failed. Fail-open: the machine
    may sleep, the companion carries on."""
    guard, spawner = _darwin_keep_awake(
        lambda: True, _FakeSpawner(error=FileNotFoundError("/usr/bin/caffeinate"))
    )
    with caplog.at_level(logging.DEBUG, logger="ccsync.shutdown_guard"):
        assert guard.apply_once() is False
        assert guard.apply_once() is False
    assert guard.held is False
    complaints = [r for r in caplog.records if "may sleep" in r.getMessage()]
    assert len(complaints) == 1, "a broken spawn must not spam the log every poll"


def test_a_failed_spawn_is_retried_on_the_next_poll():
    guard, spawner = _darwin_keep_awake(
        lambda: True, _FakeSpawner(error=OSError("EAGAIN"))
    )
    guard.apply_once()
    guard.apply_once()
    assert len(spawner.argvs) == 2


def test_a_spawner_that_returns_nothing_is_not_recorded_as_held():
    guard, _ = _darwin_keep_awake(lambda: True, _FakeSpawner(returns=None))
    assert guard.apply_once() is False
    assert guard.held is False


def test_a_crashing_busy_check_lets_the_mac_sleep():
    def boom():
        raise RuntimeError("kaboom")

    guard, spawner = _darwin_keep_awake(boom)
    assert guard.apply_once() is False
    assert spawner.argvs == []


def test_the_darwin_loop_stops_caffeinate_when_the_guard_stops():
    """stop() while a lane is mid-transfer: the child must not outlive the
    companion's own keep-awake decision."""
    guard, spawner = _darwin_keep_awake(lambda: True)
    guard.start()
    deadline = time.monotonic() + 5.0
    while not guard.held and time.monotonic() < deadline:
        time.sleep(0.01)
    assert guard.held, "never took the idle timer"
    guard.stop()
    assert guard.held is False
    assert spawner.children[0].terminated >= 1


def test_the_darwin_loop_notices_a_sync_finishing_without_being_stopped():
    busy = [True]
    guard, spawner = _darwin_keep_awake(lambda: busy[0])
    guard.start()
    try:
        deadline = time.monotonic() + 5.0
        while not guard.held and time.monotonic() < deadline:
            time.sleep(0.01)
        assert guard.held
        busy[0] = False
        deadline = time.monotonic() + 5.0
        while guard.held and time.monotonic() < deadline:
            time.sleep(0.01)
        assert guard.held is False, "held the idle timer after the sync finished"
        assert spawner.children[0].terminated == 1
    finally:
        guard.stop()


def test_stopping_a_darwin_keep_awake_that_never_started_is_harmless():
    guard, spawner = _darwin_keep_awake(lambda: True)
    guard.stop()
    assert guard.held is False
    assert spawner.argvs == []


def test_stop_reaps_a_child_no_loop_ever_owned():
    """A child process can be ended from any thread (unlike the Windows
    execution state), so stop() is the backstop for a loop that never ran."""
    guard, spawner = _darwin_keep_awake(lambda: True)
    guard.apply_once()
    guard.stop()
    assert spawner.children[0].terminated == 1
    assert guard.held is False


def test_a_darwin_keep_awake_whose_loop_died_can_be_started_again(monkeypatch):
    guard, _spawner = _darwin_keep_awake(lambda: False)
    attempts = []
    monkeypatch.setattr(guard, "_loop", lambda: attempts.append(1))

    guard.start()
    deadline = time.monotonic() + 5.0
    while guard._thread is not None and guard._thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.01)
    guard.start()

    assert len(attempts) == 2


def test_starting_the_darwin_loop_twice_runs_one_loop():
    guard, _spawner = _darwin_keep_awake(lambda: False)
    guard.start()
    first = guard._thread
    try:
        guard.start()
        assert guard._thread is first
    finally:
        guard.stop()


# --- macOS: the Quit policy -------------------------------------------------
#
# There is no macOS equivalent of ShutdownBlockReasonCreate, so this is a
# warning rather than a block -- and the one property it must never lose is
# that a second attempt always goes through.

def test_an_idle_mac_never_cancels_a_quit():
    assert should_cancel_terminate(1000.0, None, busy=False) is False
    assert should_cancel_terminate(1000.0, 999.0, busy=False) is False


def test_the_first_quit_mid_upload_is_cancelled_once():
    assert should_cancel_terminate(1000.0, None, busy=True) is True


def test_a_second_quit_in_the_same_episode_always_goes_through():
    """The hard requirement. Someone who has read the notification and quit
    again has answered the question; a guard that argues twice is one people
    force-quit past -- and then never trust on the night it is right."""
    assert should_cancel_terminate(1000.0, 999.0, busy=True) is False
    assert should_cancel_terminate(1000.0 + TERMINATE_EPISODE_SECONDS - 1, 1000.0,
                                   busy=True) is False


def test_a_genuinely_later_attempt_is_worth_warning_about_again():
    assert should_cancel_terminate(1000.0 + TERMINATE_EPISODE_SECONDS, 1000.0,
                                   busy=True) is True


def test_a_clock_that_went_backwards_allows_the_quit():
    assert should_cancel_terminate(900.0, 1000.0, busy=True) is False


def test_an_unusable_clock_allows_the_quit():
    assert should_cancel_terminate("now", None, busy=True) is True
    assert should_cancel_terminate("now", 1000.0, busy=True) is False


def test_a_bad_episode_length_falls_back_to_the_shipped_default():
    assert should_cancel_terminate(1000.0, 995.0, busy=True, episode_seconds=0) is False
    assert should_cancel_terminate(2000.0, 995.0, busy=True, episode_seconds="soon") is True


class _FakeSignals:
    """Stand-in for signal.signal: records installs, returns the previous
    handler like the real one. No real signals are ever sent in these tests."""

    def __init__(self, previous=signal.SIG_DFL):
        self.installed: list = []
        self.current = previous

    def __call__(self, signum, handler):
        self.installed.append((signum, handler))
        previous, self.current = self.current, handler
        return previous


def _darwin_guard(reason_fn, on_shutdown=None, notify=None, signals=None,
                  clock=None, install=None):
    notes = [] if notify is None else notify
    signals = signals if signals is not None else _FakeSignals()
    guard = _DarwinShutdownGuard(
        reason_fn,
        on_shutdown=on_shutdown,
        notify_fn=notes.append if isinstance(notes, list) else notes,
        signal_fn=signals,
        install_delegate_fn=install if install is not None else (lambda: None),
        clock=clock or _Clock(),
    )
    return guard, notes, signals


def test_nothing_pending_allows_the_quit_and_says_nothing():
    guard, notes, _ = _darwin_guard(lambda: None)
    assert guard.handle_should_terminate() == NS_TERMINATE_NOW
    assert notes == []


def test_a_quit_mid_upload_is_delayed_once_with_an_explanation():
    guard, notes, _ = _darwin_guard(lambda: "CCSync is still syncing -- 19.3 GB left")
    assert guard.handle_should_terminate() == NS_TERMINATE_CANCEL
    assert notes == ["CCSync is still syncing -- 19.3 GB left"]


def test_quitting_again_straight_after_is_never_refused():
    guard, notes, _ = _darwin_guard(lambda: "still syncing")
    assert guard.handle_should_terminate() == NS_TERMINATE_CANCEL
    assert guard.handle_should_terminate() == NS_TERMINATE_NOW
    assert guard.handle_should_terminate() == NS_TERMINATE_NOW
    assert len(notes) == 1, "warned twice about the same quit"


def test_a_much_later_quit_is_warned_about_again():
    clock = _Clock()
    guard, notes, _ = _darwin_guard(lambda: "still syncing", clock=clock)
    assert guard.handle_should_terminate() == NS_TERMINATE_CANCEL
    clock.advance(TERMINATE_EPISODE_SECONDS + 1)
    assert guard.handle_should_terminate() == NS_TERMINATE_CANCEL
    assert len(notes) == 2


def test_a_crashing_reason_callback_allows_the_quit():
    def boom():
        raise RuntimeError("kaboom")

    guard, notes, _ = _darwin_guard(boom)
    assert guard.handle_should_terminate() == NS_TERMINATE_NOW
    assert notes == []


def test_a_crashing_clock_allows_the_quit():
    def boom():
        raise RuntimeError("clock exploded")

    guard, _notes, _ = _darwin_guard(lambda: "still syncing", clock=boom)
    assert guard.handle_should_terminate() == NS_TERMINATE_NOW


def test_a_notification_that_cannot_be_shown_does_not_change_the_answer():
    def explode(text):
        raise OSError("osascript missing")

    guard, _notes, _ = _darwin_guard(lambda: "still syncing", notify=explode)
    assert guard.handle_should_terminate() == NS_TERMINATE_CANCEL


def test_the_quit_warning_is_truncated_like_the_windows_one():
    guard, notes, _ = _darwin_guard(lambda: "z" * 4000)
    assert guard.handle_should_terminate() == NS_TERMINATE_CANCEL
    assert len(notes[0]) == MAX_REASON_CHARS


# --- macOS: SIGTERM (logout / launchctl bootout) ---------------------------

def test_a_sigterm_handler_is_installed_for_logout():
    """launchd sends SIGTERM at logout and on `launchctl bootout`. The
    default disposition kills the interpreter where it stands -- part-way
    through a state write, with no lane shutdown."""
    stopped = []
    guard, _notes, signals = _darwin_guard(lambda: None, on_shutdown=lambda: stopped.append(1))
    guard.start()
    try:
        assert [signum for signum, _h in signals.installed] == [signal.SIGTERM]
        handler = signals.installed[0][1]
        handler(signal.SIGTERM, None)
        assert stopped == [1], "SIGTERM did not reach the companion's shutdown"
    finally:
        guard.stop()


def test_the_previous_sigterm_handler_is_chained():
    """Additive, never in the way: whatever had SIGTERM before us may well be
    what actually ends the process."""
    seen = []
    signals = _FakeSignals(previous=lambda signum, frame: seen.append("previous"))
    guard, _notes, _ = _darwin_guard(lambda: None, on_shutdown=lambda: seen.append("ours"),
                                     signals=signals)
    guard.start()
    try:
        signals.installed[0][1](signal.SIGTERM, None)
    finally:
        guard.stop()
    assert seen == ["ours", "previous"]


def test_a_crashing_shutdown_callback_does_not_escape_the_signal_handler():
    """A signal handler that throws lands the exception in whatever unrelated
    line of code happened to be running."""
    def boom():
        raise RuntimeError("shutdown exploded")

    guard, _notes, signals = _darwin_guard(lambda: None, on_shutdown=boom)
    guard.start()
    try:
        signals.installed[0][1](signal.SIGTERM, None)  # must not raise
    finally:
        guard.stop()


def test_sigterm_is_left_alone_with_no_shutdown_callback():
    """A handler that does nothing would SWALLOW SIGTERM and leave
    `launchctl bootout` hanging until launchd's SIGKILL -- strictly worse
    than the default disposition."""
    guard, _notes, signals = _darwin_guard(lambda: None, on_shutdown=None)
    guard.start()
    try:
        assert signals.installed == []
    finally:
        guard.stop()


def test_the_previous_sigterm_handler_is_put_back_on_stop():
    original = lambda signum, frame: None  # noqa: E731
    signals = _FakeSignals(previous=original)
    guard, _notes, _ = _darwin_guard(lambda: None, on_shutdown=lambda: None, signals=signals)
    guard.start()
    guard.stop()
    assert signals.current is original
    assert guard.active is False


def test_a_registrar_that_refuses_is_not_fatal():
    """signal.signal() raises ValueError off the main thread. That costs a
    tidy logout, never the companion's startup."""
    def refuse(signum, handler):
        raise ValueError("signal only works in main thread")

    guard, _notes, _ = _darwin_guard(lambda: None, on_shutdown=lambda: None, signals=refuse)
    guard.start()
    assert guard.active is False
    guard.stop()


def test_the_sigterm_handler_is_installed_once():
    guard, _notes, signals = _darwin_guard(lambda: None, on_shutdown=lambda: None)
    guard.start()
    guard.start()
    try:
        assert len(signals.installed) == 1
    finally:
        guard.stop()


# --- macOS: the AppKit half is optional ------------------------------------

def test_a_delegate_install_failure_is_not_fatal():
    def explode():
        raise RuntimeError("AppKit said no")

    guard, _notes, _ = _darwin_guard(lambda: None, install=explode)
    guard.start()  # must not raise
    assert guard.active is False
    guard.stop()


def test_the_delegate_is_given_back_on_stop():
    undone = []
    guard, _notes, _ = _darwin_guard(lambda: None, install=lambda: lambda: undone.append(1))
    guard.start()
    assert guard.active is True
    guard.stop()
    assert undone == [1]
    assert guard.active is False


def test_the_delegate_half_no_ops_without_pyobjc():
    """This is the real code path on any machine without AppKit -- including
    every machine that runs this test suite. It must return None, not raise:
    the SIGTERM half is worth having on its own."""
    guard = _DarwinShutdownGuard(lambda: None)
    if sys.platform == "darwin":
        pytest.skip("AppKit may genuinely be importable here")
    assert guard._install_app_delegate() is None


@pytest.fixture
def fake_foundation(monkeypatch):
    """Just enough of pyobjc's Foundation to build the delegate class.

    The ObjC bridge is not what needs testing; the three lines of dispatch
    inside applicationShouldTerminate_ are, and they are unreachable on a
    machine with no AppKit -- which is every machine that runs this suite."""
    import types

    from ccsync_companion import shutdown_guard as mod

    module = types.ModuleType("Foundation")

    class NSObject:
        @classmethod
        def alloc(cls):
            return cls()

        def init(self):
            return self

    module.NSObject = NSObject
    monkeypatch.setitem(sys.modules, "Foundation", module)
    # monkeypatch restores the real cache afterwards, so a Mac that has
    # already built the genuine class does not end up holding this one.
    monkeypatch.setattr(mod, "_APP_DELEGATE_CLASS", None)
    return mod


def test_the_delegate_class_is_built_once_per_process(fake_foundation):
    """Defining an ObjC class registers its NAME with the runtime, and doing
    that twice raises -- so a guard that is stopped and started again would
    get an exception where a warning should be."""
    first = fake_foundation._app_delegate_class()
    second = fake_foundation._app_delegate_class()
    assert first is second


def test_the_delegate_asks_the_guard(fake_foundation):
    guard, notes, _ = _darwin_guard(lambda: "still syncing")
    delegate = fake_foundation._app_delegate_class().alloc().init()
    delegate.guard = guard
    assert delegate.applicationShouldTerminate_(None) == NS_TERMINATE_CANCEL
    assert delegate.applicationShouldTerminate_(None) == NS_TERMINATE_NOW
    assert len(notes) == 1


def test_a_delegate_with_no_guard_allows_the_quit(fake_foundation):
    delegate = fake_foundation._app_delegate_class().alloc().init()
    assert delegate.applicationShouldTerminate_(None) == NS_TERMINATE_NOW


def test_a_delegate_whose_guard_explodes_allows_the_quit(fake_foundation):
    class _Exploding:
        def handle_should_terminate(self):
            raise RuntimeError("boom")

    delegate = fake_foundation._app_delegate_class().alloc().init()
    delegate.guard = _Exploding()
    assert delegate.applicationShouldTerminate_(None) == NS_TERMINATE_NOW


def test_the_darwin_guard_survives_a_start_stop_with_no_appkit():
    """No callback (so no SIGTERM handler), no AppKit (so no delegate): the
    guard still starts and stops cleanly and reports itself inactive.

    "No AppKit" is now INJECTED rather than assumed. The test used to default
    every seam and rely on pyobjc being unimportable -- true on Windows CI,
    false on any real Mac, where the tray extra installs
    pyobjc-framework-Cocoa. There the default install_delegate_fn genuinely
    installed a delegate and `active` was True, so the test failed while the
    product was doing exactly the right thing (first real macOS run,
    2026-08-04). The AppKit-present path is covered by the fake_foundation
    tests above.
    """
    guard = _DarwinShutdownGuard(lambda: None, install_delegate_fn=lambda: None)
    guard.start()
    try:
        assert guard.active is False
    finally:
        guard.stop()


# --- 2026-08-11 hunt: SYNC-7 / SYNC-15 / SYNC-16 ---------------------------


def test_sigterm_never_chains_into_our_own_handler():
    """SYNC-7. _restore_signal_handler deliberately leaves our handler
    installed when it cannot restore (previous is None, or the restore raised
    off the main thread), so the next start() captures OUR handler as
    _previous_sigterm. The guard against chaining compared a bound method
    with `is` -- and attribute access builds a new bound-method object every
    time, so it never fired: SIGTERM then recursed handle_sigterm -> chain ->
    handle_sigterm to the recursion limit, logging a traceback per frame."""
    calls: list[str] = []
    signals = _FakeSignals(previous=None)
    guard, _notes, _ = _darwin_guard(
        lambda: None, on_shutdown=lambda: calls.append("shutdown"), signals=signals)

    guard.start()
    # signal.signal() returned None for the previous handler, so putting it
    # back would raise -- _restore_signal_handler leaves ours installed, and
    # the next start() reads it back as "whoever had SIGTERM before us".
    guard.stop()
    guard.start()
    assert guard._previous_sigterm is not None

    signals.installed[-1][1](signal.SIGTERM, None)

    assert calls == ["shutdown"], "the handler chained into itself"
    guard.stop()


def test_a_pump_that_will_not_die_is_not_replaced_by_a_second_one(monkeypatch):
    """SYNC-15. stop() cleared _hwnd/_thread unconditionally but posted
    WM_CLOSE only `if hwnd` -- so a stop() before the window came up (the 5 s
    _ready.wait in start() is a bound, not a guarantee) left a permanent
    ccsync-shutdown-guard thread and a live window, and the next start() built
    a SECOND pump on top of them."""
    from ccsync_companion import shutdown_guard

    monkeypatch.setattr(shutdown_guard, "STOP_READY_WAIT_SECONDS", 0.05)
    monkeypatch.setattr(shutdown_guard, "STOP_JOIN_SECONDS", 0.05)
    guard = _WindowsShutdownGuard(lambda: None)
    release = threading.Event()
    thread = threading.Thread(target=lambda: release.wait(30.0), daemon=True)
    guard._thread = thread
    thread.start()
    try:
        guard.stop()
        assert guard._thread is thread, "the live pump was forgotten"

        built: list[str] = []
        guard._pump = lambda: built.append("pump")
        guard.start()
        assert built == [], "a second pump was started over a live one"
    finally:
        release.set()
        thread.join(timeout=5.0)


def test_a_pump_that_exits_is_let_go_of(monkeypatch):
    """...and the references must NOT be kept when the join succeeds, or a
    guard could never be restarted after a clean stop."""
    from ccsync_companion import shutdown_guard

    monkeypatch.setattr(shutdown_guard, "STOP_READY_WAIT_SECONDS", 0.05)
    guard = _WindowsShutdownGuard(lambda: None)
    thread = threading.Thread(target=lambda: None, daemon=True)
    guard._thread = thread
    thread.start()
    thread.join(timeout=5.0)

    guard.stop()

    assert guard._thread is None
    assert guard.active is False


def test_the_hold_ceiling_is_per_lane():
    """SYNC-16. One clock for the whole tracker meant a lane that churns for
    hours without settling (lane C's need count ticking over a huge library,
    rclone wedged in retries) stood the guard down for every OTHER lane -- so
    a genuine 200 GB lane A ingest starting later got no keep-awake and the
    machine idle-slept mid-upload."""
    tracker, clock = _tracker(stale_seconds=100.0, max_hold_seconds=600.0)
    for tick in range(1, 15):
        tracker.describe([LaneStatus(name="lane_c", state=STATE_SYNCING, queued=tick)])
        clock.advance(60)
    # lane C is past its own ceiling and no longer speaks for itself...
    assert tracker.describe(
        [LaneStatus(name="lane_c", state=STATE_SYNCING, queued=99)]) is None

    # ...but lane A has only just started moving.
    reason = tracker.describe([
        LaneStatus(name="lane_c", state=STATE_SYNCING, queued=100),
        LaneStatus(name="lane_a", state=STATE_SYNCING, bytes_done=1,
                   bytes_total=200 * 1024**3),
    ])
    assert reason is not None
    assert "left" in reason


def test_a_lane_past_the_ceiling_does_not_re_arm_while_it_churns():
    """The ceiling still has to bite: a per-lane clock must not restart just
    because that lane's own numbers keep moving."""
    tracker, clock = _tracker(stale_seconds=100.0, max_hold_seconds=600.0)
    reason = "not run"
    for tick in range(1, 15):
        reason = tracker.describe(
            [LaneStatus(name="lane_a", state=STATE_SYNCING, queued=tick)])
        clock.advance(60)
    assert reason is None
