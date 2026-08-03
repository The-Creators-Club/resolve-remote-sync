"""Tests for the shutdown warning (companion/src/ccsync_companion/shutdown_guard.py).

The window/message-pump half needs Windows and a real HWND; the half that
decides whether to interrupt someone's shutdown does not, and that is the
half that can ruin an evening either way. Both failure directions are
covered: a false block (traps the editor) and a missed block (loses hours of
upload).
"""

from __future__ import annotations

import sys
import threading
import time

import pytest

from ccsync_companion.shutdown_guard import (
    ES_CONTINUOUS,
    ES_SYSTEM_REQUIRED,
    MAX_REASON_CHARS,
    KeepAwakeGuard,
    PendingTracker,
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
