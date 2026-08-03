"""RcloneLane shutdown/spawn races and the timer/reader bounds around them
(KNOWN_BUGS B13 plus the three sync-engine minors next to it).

The property under test throughout is the one the audit named: **stop() must
never leave an rclone running.** On Windows a child outlives its parent, so a
self-upgrade that spawns rclone one instruction after stop() looked for a
child to kill leaves the OLD process's upload racing the NEW process's lanes
over the same tree (AUDIT_2 C-7).

Everything here is deterministic -- no sleeps. The two mechanisms used are:

  * an injected hook that calls stop() from inside the work the lane does
    between "should I run?" and "spawn" (that whole span used to be
    uncancellable), and
  * an instrumented spawn lock that lets a test observe the exact moment the
    stopping thread reaches it, so the spawn/publish window can be pinned
    open on purpose.
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import pytest

from ccsync_companion.sync.base import STATE_IDLE
from ccsync_companion.sync.rclone_lane import (
    DIRECTION_UP,
    LANE_A_MIN_AGE_SECONDS,
    RcloneLane,
)


@pytest.fixture(autouse=True)
def _stub_rclone_available(monkeypatch):
    monkeypatch.setattr(
        "ccsync_companion.sync.rclone_lane.rclone_available",
        lambda rclone_path, *a, **kw: (True, rclone_path),
    )


class _FakeProc:
    """Stand-in for an rclone child that stop() can terminate.

    With wait_for_terminate=True the runner's own `proc.wait()` blocks until
    the child is terminated, exactly as a real one does. That is what keeps
    the publish-before-release tests deterministic: without it the runner can
    finish and clear its published handle before the stopping thread -- which
    is parked on the spawn lock -- ever gets a look at it.
    """

    def __init__(
        self, stderr_text: str = "", returncode: int = 0, wait_for_terminate: bool = False
    ) -> None:
        self.stderr = _FakeStderr(stderr_text)
        self._returncode = returncode
        self.terminated = False
        self.killed = False
        self._wait_for_terminate = wait_for_terminate
        self._ended = threading.Event()

    def wait(self, timeout=None) -> int:
        if timeout is None and self._wait_for_terminate:
            assert self._ended.wait(10), "stop() never terminated the child"
        return self._returncode

    def poll(self):
        return None if not self.terminated else self._returncode

    def terminate(self) -> None:
        self.terminated = True
        self._ended.set()

    def kill(self) -> None:
        self.killed = True
        self._ended.set()


class _FakeStderr:
    def __init__(self, text: str) -> None:
        self._text = text
        self._lines = [ln + "\n" for ln in text.splitlines()]

    def read(self) -> str:
        return self._text

    def __iter__(self):
        return iter(self._lines)


class _InstrumentedLock:
    """A Lock that announces WHICH thread is trying to take it.

    Lets a test pin the spawn window open until the stopping thread has
    provably reached the lock -- the alternative being a sleep and a prayer.
    """

    def __init__(self) -> None:
        self._inner = threading.Lock()
        self._attempts: dict[str, threading.Event] = {}
        self._meta = threading.Lock()

    def attempt_event(self, thread_name: str) -> threading.Event:
        with self._meta:
            return self._attempts.setdefault(thread_name, threading.Event())

    def acquire(self, *args, **kwargs):
        self.attempt_event(threading.current_thread().name).set()
        return self._inner.acquire(*args, **kwargs)

    def release(self):
        return self._inner.release()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *exc):
        self.release()
        return False


def _make_lane(tmp_path, popen_factory=None, direction=DIRECTION_UP, debounce=30.0, cfg=None):
    return RcloneLane(
        direction=direction,
        local_root=str(tmp_path / "local"),
        remote="nas",
        remote_root="Creators_Club",
        state_dir=tmp_path / "state",
        watch_debounce_seconds=debounce,
        popen_factory=popen_factory,
        cfg=cfg,
    )


def _old_file(root: Path, rel: str, data: bytes = b"x" * 64) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    old = time.time() - (LANE_A_MIN_AGE_SECONDS + 60)
    os.utime(path, (old, old))
    return path


def _flush_now(lane: RcloneLane) -> None:
    timer = lane._express_timer
    if timer is not None:
        timer.cancel()
        lane._express_timer = None
    lane._express_flush()


# ===========================================================================
# B13a: stop() during the work BETWEEN the shutdown check and the spawn
# ===========================================================================


def test_express_stop_landing_before_the_spawn_starts_no_rclone(tmp_path, monkeypatch):
    """_express_flush_inner checked _express_shutdown once, at the top, and
    then partitioned the batch, took the run lock, shelled out to
    `rclone version` and wrote a list file before spawning -- all of it
    uncancellable. A stop() anywhere in that span spawned an rclone that the
    already-completed _express_stop() could not know about."""
    calls: list = []
    lane = _make_lane(tmp_path)
    root = Path(lane.local_root)
    _old_file(root, "Projects/2026/FF5/Alpha/clip.mov")

    def factory(cmd, **kwargs):
        calls.append(list(cmd))
        return _FakeProc()

    lane.popen_factory = factory

    # The hook stands in for "stop() happened while we were getting ready":
    # rclone_available() is a real subprocess on the real path and is called
    # AFTER the old code's only shutdown check.
    def _available_then_stop(rclone_path, *a, **kw):
        lane.stop()
        return True, rclone_path

    monkeypatch.setattr(
        "ccsync_companion.sync.rclone_lane.rclone_available", _available_then_stop
    )

    lane.notify_path_changed(str(root / "Projects/2026/FF5/Alpha/clip.mov"))
    _flush_now(lane)

    assert calls == [], "stop() must be seen before the express child is created"
    # A stand-down is not a failure: no error counter, no red lane.
    assert lane.express_report()["last_error"] is None
    assert lane.express_report()["runs"] == 0
    assert lane.status().state != "error"


def test_express_stand_down_leaves_no_list_file_and_no_inflight_claim(tmp_path, monkeypatch):
    """A cancelled run must not strand its bookkeeping: a leaked in-flight
    claim excludes those paths from EVERY future periodic pass."""
    calls: list = []
    lane = _make_lane(tmp_path, popen_factory=lambda cmd, **kw: calls.append(cmd) or _FakeProc())
    root = Path(lane.local_root)
    _old_file(root, "Projects/2026/FF5/Alpha/clip.mov")

    def _available_then_stop(rclone_path, *a, **kw):
        lane.stop()
        return True, rclone_path

    monkeypatch.setattr(
        "ccsync_companion.sync.rclone_lane.rclone_available", _available_then_stop
    )
    lane.notify_path_changed(str(root / "Projects/2026/FF5/Alpha/clip.mov"))
    _flush_now(lane)

    assert calls == []
    assert lane.express_inflight_paths() == []
    assert list((tmp_path / "state").glob("express_*")) == []


def test_stop_during_the_partition_is_seen_before_any_work_is_committed(tmp_path, monkeypatch):
    """The re-check under the express run lock: a stop() that lands while the
    batch is being stat'd must be seen BEFORE a list file is written and
    before the in-flight claim is taken, not just before the spawn."""
    written: list = []
    monkeypatch.setattr(
        "ccsync_companion.sync.rclone_lane.write_files_from_list",
        lambda rels, path: written.append(list(rels)),
    )

    class _StoppingLane(RcloneLane):
        def _express_partition(self, batch):
            out = super()._express_partition(batch)
            self.stop()
            return out

    lane = _StoppingLane(
        direction=DIRECTION_UP,
        local_root=str(tmp_path / "local"),
        remote="nas",
        remote_root="Creators_Club",
        state_dir=tmp_path / "state",
        watch_debounce_seconds=30.0,
        popen_factory=lambda cmd, **kw: _FakeProc(),
    )
    root = Path(lane.local_root)
    clip = _old_file(root, "Projects/2026/FF5/Alpha/clip.mov")
    lane.notify_path_changed(str(clip))
    _flush_now(lane)

    assert written == [], "no express list file may be written for a cancelled window"
    assert lane.express_inflight_paths() == []


def test_periodic_stop_landing_after_the_command_is_built_starts_no_rclone(tmp_path):
    """The periodic lane-B/lane-A path had the same shape and, worse,
    _run_once_locked never consulted _stop_event at all: a run queued behind
    _run_lock could start rclone long after the lane had been stopped."""
    calls: list = []

    class _StoppingLane(RcloneLane):
        def _build_command(self, *args, **kwargs):
            cmd = super()._build_command(*args, **kwargs)
            # Building the filter file is the last thing before the spawn --
            # stop() landing here used to be invisible to the runner.
            self._stop_event.set()
            return cmd

    lane = _StoppingLane(
        direction=DIRECTION_UP,
        local_root=str(tmp_path / "local"),
        remote="nas",
        remote_root="Creators_Club",
        state_dir=tmp_path / "state",
        popen_factory=lambda cmd, **kw: calls.append(cmd) or _FakeProc(),
    )
    subpath = "Projects/2026/FF5/Alpha"
    (Path(lane.local_root) / subpath).mkdir(parents=True)

    status = lane.run_once(subpath=subpath)

    assert calls == [], "a stopped lane must not spawn rclone"
    # Stood down, not failed -- a self-upgrade must not paint the grid red.
    assert status.state == STATE_IDLE
    assert status.last_error is None
    assert status.current_project is None
    assert status.detail == "stopped before this pass started"


def test_run_once_on_an_already_stopped_lane_is_a_noop(tmp_path):
    calls: list = []
    lane = _make_lane(tmp_path, popen_factory=lambda cmd, **kw: calls.append(cmd) or _FakeProc())
    subpath = "Projects/2026/FF5/Alpha"
    (Path(lane.local_root) / subpath).mkdir(parents=True)

    lane.stop()
    lane.run_once(subpath=subpath)

    assert calls == []


def test_a_fresh_generation_runs_again_after_stop_then_start(tmp_path):
    """The stop check must key on the CURRENT generation's event, or the
    lane would be permanently dead after the first stop() -- exactly the
    regression AUDIT_2 L-2 warned about."""
    calls: list = []
    lane = _make_lane(tmp_path, popen_factory=lambda cmd, **kw: calls.append(cmd) or _FakeProc())
    subpath = "Projects/2026/FF5/Alpha"
    (Path(lane.local_root) / subpath).mkdir(parents=True)

    lane.stop()
    lane.run_once(subpath=subpath)
    assert calls == []

    lane._start_watchdog = lambda: None  # managed mode re-arms without an observer
    lane.start_watchdog_only()
    lane.run_once(subpath=subpath)
    lane.stop()

    assert len(calls) == 1, "a restarted lane must sync again"


# ===========================================================================
# B13b: the handle is published BEFORE the spawn stops being cancellable
# ===========================================================================


def test_express_child_spawned_under_the_lock_is_still_terminated_by_stop(tmp_path):
    """The other half of B13: _express_spawn published self._express_proc only
    AFTER the child started, so a concurrent _express_stop() read None and
    returned having killed nothing -- while the child it was looking for
    started a moment later and outlived the process.

    Pinned open deliberately: the spawning thread holds the spawn lock across
    the whole check/spawn/publish, and the factory below does not return until
    the stopping thread has provably reached that lock."""
    lane = _make_lane(tmp_path)
    lane._express_proc_lock = _InstrumentedLock()
    stopper_at_lock = lane._express_proc_lock.attempt_event("express-stopper")
    stopper_returned = threading.Event()
    procs: list = []

    def stopper() -> None:
        lane._express_stop()
        stopper_returned.set()

    thread = threading.Thread(target=stopper, name="express-stopper")

    def factory(cmd, **kwargs):
        proc = _FakeProc(wait_for_terminate=True)
        procs.append(proc)
        thread.start()
        # The stopper has set _express_shutdown and reached the spawn lock we
        # are holding. Under the old code it would have read _express_proc
        # (None) and returned right here.
        assert stopper_at_lock.wait(10)
        assert not stopper_returned.is_set(), (
            "stop() must not be able to complete while a spawn is in flight"
        )
        return proc

    lane.popen_factory = factory
    root = Path(lane.local_root)
    _old_file(root, "Projects/2026/FF5/Alpha/clip.mov")
    lane.notify_path_changed(str(root / "Projects/2026/FF5/Alpha/clip.mov"))
    _flush_now(lane)
    thread.join(timeout=10)

    assert len(procs) == 1
    assert procs[0].terminated is True, "stop() must find and end the express child"


def test_periodic_child_spawned_under_the_lock_is_still_terminated_by_stop(tmp_path):
    """Same publish-after-spawn gap on the periodic path (_run_popen set
    self._proc only after Popen returned)."""
    lane = _make_lane(tmp_path)
    lane._proc_lock = _InstrumentedLock()
    stopper_at_lock = lane._proc_lock.attempt_event("periodic-stopper")
    stopper_returned = threading.Event()
    procs: list = []

    def stopper() -> None:
        lane._kill_running_process()
        stopper_returned.set()

    thread = threading.Thread(target=stopper, name="periodic-stopper")

    def factory(cmd, **kwargs):
        proc = _FakeProc(wait_for_terminate=True)
        procs.append(proc)
        thread.start()
        assert stopper_at_lock.wait(10)
        assert not stopper_returned.is_set()
        return proc

    lane.popen_factory = factory
    lane._run_popen(["rclone", "copy"])
    thread.join(timeout=10)

    assert procs[0].terminated is True, "stop() must find and end the periodic child"


def test_the_express_and_periodic_spawn_locks_are_separate(tmp_path):
    """stop()ing one must never be able to block on the other's spawn: the
    two children are killed independently by design."""
    lane = _make_lane(tmp_path)
    assert lane._proc_lock is not lane._express_proc_lock
    assert lane._proc_lock is not lane._run_lock
    assert lane._express_proc_lock is not lane._express_run_lock


# ===========================================================================
# Minor: the stderr reader join is bounded
# ===========================================================================


class _NeverEndingStderr:
    """A pipe whose write handle a grandchild inherited: rclone is gone, but
    EOF never arrives, so `for line in proc.stderr` blocks forever."""

    def __init__(self, released: threading.Event, extra: list[str]) -> None:
        self._released = released
        self._extra = extra
        self.blocked = threading.Event()

    def __iter__(self):
        return self

    def __next__(self) -> str:
        if self._extra:
            return self._extra.pop(0)
        self.blocked.set()
        self._released.wait(30)
        if self._extra:
            return self._extra.pop(0)
        raise StopIteration


def test_run_popen_does_not_block_forever_on_a_reader_that_never_sees_eof(
    tmp_path, monkeypatch, caplog
):
    """rclone_lane.py:1889's unbounded join(): the reader never returns, so
    _run_once_locked blocked forever WHILE HOLDING _run_lock and the
    sequencer's whole project rotation stopped."""
    monkeypatch.setattr("ccsync_companion.sync.rclone_lane.STDERR_READER_JOIN_SECONDS", 0.2)
    released = threading.Event()
    stderr = _NeverEndingStderr(released, ['{"level":"info","msg":"clip.mov: Copied (new)"}\n'])

    class _WedgedProc:
        def __init__(self) -> None:
            self.stderr = stderr

        def wait(self, timeout=None) -> int:
            return 0

        def poll(self):
            return None

        def kill(self) -> None:
            pass

    lane = _make_lane(tmp_path, popen_factory=lambda cmd, **kw: _WedgedProc())
    try:
        with caplog.at_level("WARNING", logger="ccsync.sync.rclone"):
            returncode, tail, result = lane._run_popen(["rclone", "copy"])
    finally:
        released.set()

    assert returncode == 0
    # Everything that DID arrive before the block is still counted.
    assert result.transferred == 1
    assert "Copied" in tail
    assert any(
        "still open" in r.getMessage() for r in caplog.records
    ), "an abandoned reader must be reported, not silently tolerated"


def test_an_abandoned_reader_cannot_write_into_the_next_run(tmp_path, monkeypatch):
    """The bounded join leaves a daemon thread parked on the pipe. It must
    not still be feeding this lane's live status when it finally wakes."""
    monkeypatch.setattr("ccsync_companion.sync.rclone_lane.STDERR_READER_JOIN_SECONDS", 0.2)
    released = threading.Event()
    late_line = (
        '{"level":"notice","msg":"","stats":{"bytes":999,"totalBytes":999,'
        '"speed":1.0,"eta":0}}\n'
    )
    stderr = _NeverEndingStderr(released, [])

    class _WedgedProc:
        def __init__(self) -> None:
            self.stderr = stderr

        def wait(self, timeout=None) -> int:
            return 0

        def poll(self):
            return None

        def kill(self) -> None:
            pass

    lane = _make_lane(tmp_path, popen_factory=lambda cmd, **kw: _WedgedProc())
    lane._run_popen(["rclone", "copy"])
    assert stderr.blocked.is_set()

    # The parked reader finally gets a line, long after the run it belonged
    # to reported its result.
    stderr._extra.append(late_line)
    released.set()
    deadline = time.time() + 5
    while time.time() < deadline and stderr._extra:
        time.sleep(0.01)

    assert lane.status().bytes_done is None, (
        "a run that has already finished must not have its status rewritten"
    )


# ===========================================================================
# Minor: stop() vs the legacy debounce timer
# ===========================================================================


class _StubObserver:
    """Watchdog observer stand-in whose stop() delivers one last file event --
    the exact window the old ordering left open."""

    def __init__(self, on_stop=None) -> None:
        self._on_stop = on_stop
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True
        if self._on_stop is not None:
            self._on_stop()

    def join(self, timeout=None) -> None:
        pass


def test_a_file_event_delivered_during_stop_cannot_arm_a_new_timer(tmp_path):
    """stop() cancelled the debounce timer FIRST and stopped the observer
    second, without holding _lock -- so an event still being delivered armed
    a fresh timer that fired run_once() on a stopped lane seconds later."""
    calls: list = []
    lane = _make_lane(tmp_path, popen_factory=lambda cmd, **kw: calls.append(cmd) or _FakeProc(),
                      debounce=0.05)
    lane._observer = _StubObserver(on_stop=lane._schedule_debounced_run)
    lane._schedule_debounced_run()
    assert lane._debounce_timer is not None, "precondition: a window is open"

    lane.stop()

    assert lane._observer is None
    assert lane._debounce_timer is None, "no timer may survive stop()"
    # And nothing fires afterwards.
    time.sleep(0.15)
    assert calls == []


def test_schedule_debounced_run_refuses_to_arm_on_a_stopped_lane(tmp_path):
    lane = _make_lane(tmp_path, popen_factory=lambda cmd, **kw: _FakeProc(), debounce=0.05)
    lane.stop()
    lane._schedule_debounced_run()
    assert lane._debounce_timer is None


def test_a_debounce_timer_that_already_fired_still_stands_down(tmp_path):
    """Timer.cancel() only helps before the deadline: a timer whose callback
    was already dispatched runs regardless, so the fire path re-checks."""
    calls: list = []
    lane = _make_lane(tmp_path, popen_factory=lambda cmd, **kw: calls.append(cmd) or _FakeProc())
    lane.stop()
    lane._debounced_fire()
    assert calls == []


# ===========================================================================
# Minor: the express busy-requeue kept resetting the give-up clock
# ===========================================================================


def test_busy_requeue_preserves_the_original_first_seen(tmp_path):
    """`setdefault(rel, (-1, time.monotonic()))` re-stamped first_seen every
    window, so EXPRESS_PENDING_MAX_SECONDS could never fire for a path that
    kept losing the run lock: it was re-stat'd forever instead of being
    handed back to the periodic pass."""
    lane = _make_lane(tmp_path, popen_factory=lambda cmd, **kw: _FakeProc())
    root = Path(lane.local_root)
    clip = _old_file(root, "Projects/2026/FF5/Alpha/clip.mov")
    rel = "Projects/2026/FF5/Alpha/clip.mov"

    lane.notify_path_changed(str(clip))
    # Old, but not yet past EXPRESS_PENDING_MAX_SECONDS -- i.e. still a path
    # express is willing to upload, which is the case the requeue handles.
    ancient = time.monotonic() - 600
    size = lane._express_pending[rel][0]
    lane._express_pending[rel] = (size, ancient)

    lane._express_run_lock.acquire()  # an express run is already uploading
    try:
        _flush_now(lane)
    finally:
        lane._express_run_lock.release()

    assert lane._express_pending[rel][1] == pytest.approx(ancient), (
        "the requeue must not restart the give-up clock"
    )
    lane.stop()


def test_a_path_that_keeps_losing_the_lock_is_eventually_given_up(tmp_path, monkeypatch):
    """The behaviour that clock exists for, end to end."""
    calls: list = []
    lane = _make_lane(tmp_path, popen_factory=lambda cmd, **kw: calls.append(cmd) or _FakeProc())
    root = Path(lane.local_root)
    clip = _old_file(root, "Projects/2026/FF5/Alpha/clip.mov")
    rel = "Projects/2026/FF5/Alpha/clip.mov"

    lane.notify_path_changed(str(clip))
    size = lane._express_pending[rel][0]
    lane._express_pending[rel] = (size, time.monotonic() - 600)

    lane._express_run_lock.acquire()
    try:
        _flush_now(lane)          # window 1: busy, requeued
    finally:
        lane._express_run_lock.release()
    assert rel in lane._express_pending

    # Now the path IS past its deadline -- which it can only be if the
    # requeue kept the original first_seen.
    monkeypatch.setattr(
        "ccsync_companion.sync.rclone_lane.EXPRESS_PENDING_MAX_SECONDS", 300.0
    )
    _flush_now(lane)              # window 2: too old -> the periodic pass owns it
    # Snapshot BEFORE stop(), which drops the pending map wholesale and would
    # make the assertion below true no matter what the requeue did.
    pending_after = dict(lane._express_pending)
    lane.stop()

    assert calls == []
    assert pending_after == {}


def test_busy_requeue_respects_the_batch_cap(tmp_path):
    """The requeue was the one insertion point that ignored
    _express_max_batch, so a busy lane could grow the pending map past the cap
    notify_path_changed() enforces."""
    lane = _make_lane(tmp_path, cfg={"express_max_batch": 2},
                      popen_factory=lambda cmd, **kw: _FakeProc())
    root = Path(lane.local_root)
    pending = {}
    for i in range(5):
        path = _old_file(root, f"Projects/2026/FF5/Alpha/clip{i}.mov")
        pending[f"Projects/2026/FF5/Alpha/clip{i}.mov"] = (path.stat().st_size, time.monotonic())
    lane._express_pending = dict(pending)

    lane._express_run_lock.acquire()
    try:
        _flush_now(lane)
    finally:
        lane._express_run_lock.release()

    assert len(lane._express_pending) <= 2
    lane.stop()


def test_a_busy_requeue_on_a_stopping_lane_arms_nothing(tmp_path):
    lane = _make_lane(tmp_path, popen_factory=lambda cmd, **kw: _FakeProc())
    root = Path(lane.local_root)
    clip = _old_file(root, "Projects/2026/FF5/Alpha/clip.mov")
    lane.notify_path_changed(str(clip))
    batch = dict(lane._express_pending)

    lane.stop()
    lane._express_requeue(list(batch), batch)

    assert lane._express_timer is None
