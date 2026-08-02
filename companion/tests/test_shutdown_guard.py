"""Tests for the shutdown warning (companion/src/ccsync_companion/shutdown_guard.py).

The window/message-pump half needs Windows and a real HWND; the half that
decides whether to interrupt someone's shutdown does not, and that is the
half that can ruin an evening either way. Both failure directions are
covered: a false block (traps the editor) and a missed block (loses hours of
upload).
"""

from __future__ import annotations

import sys
import time

import pytest

from ccsync_companion.shutdown_guard import (
    ES_CONTINUOUS,
    ES_SYSTEM_REQUIRED,
    MAX_REASON_CHARS,
    KeepAwakeGuard,
    ShutdownGuard,
    _WindowsKeepAwake,
    _WindowsShutdownGuard,
    describe_pending,
    make_keep_awake_guard,
    make_shutdown_guard,
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


def test_no_op_off_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    guard = make_shutdown_guard(lambda: "syncing", enabled=True)
    assert type(guard) is ShutdownGuard


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


def test_keep_awake_is_a_no_op_off_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
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
