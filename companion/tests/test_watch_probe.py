"""Lane A's file watcher must not be able to freeze the companion (MAC-12).

On the first editor Mac the companion stopped dead one line after
`lane_a_video_up: managed mode`: watchdog's FSEvents backend was inside
`watch_path -> open()` on the external SSD, blocked in the kernel WHILE
HOLDING THE GIL, so tray, sign-in and the main thread all sat in take_gil and
the process was alive and did nothing until it was killed.

There is no in-process fix -- a C call that takes the GIL and then blocks in
the kernel freezes every thread wherever it is started. So the root is
pre-flighted by a SUBPROCESS, which is the only place that open() may hang
without taking us with it. What is tested here:

  * the decision (fake probes: answers / blocked / no probe available),
  * that a blocked drive costs the watcher and nothing else -- one ERROR, one
    toast, a re-check on a bounded backoff, and recovery without a restart,
  * that the real probe command works against a real directory on this host,
    which is the one part a fake cannot prove.
"""

from __future__ import annotations

import logging
import subprocess
import threading
import time
from pathlib import Path

import pytest

from ccsync_companion.sync import rclone_lane as lane_mod
from ccsync_companion.sync.rclone_lane import (
    DIRECTION_UP,
    WATCH_PROBE_BLOCKED,
    WATCH_PROBE_MAX_RETRY_SECONDS,
    WATCH_PROBE_OK,
    WATCH_PROBE_RETRY_SECONDS,
    WATCH_PROBE_UNAVAILABLE,
    RcloneLane,
    probe_watch_root,
    watch_probe_command,
)


def _make_lane(tmp_path, probe=None, on_watch_blocked=None, direction=DIRECTION_UP):
    (tmp_path / "local").mkdir(parents=True, exist_ok=True)
    return RcloneLane(
        direction=direction,
        local_root=str(tmp_path / "local"),
        remote="nas",
        remote_root="Creators_Club",
        state_dir=tmp_path / "state",
        watch_probe_fn=probe,
        on_watch_blocked=on_watch_blocked,
    )


class _FakeObserver:
    """Stands in for watchdog's Observer -- and records that the one call
    that froze the Mac (schedule -> watch_path -> open) was ever made."""

    instances: list = []

    def __init__(self) -> None:
        self.scheduled: list = []
        self.started = False
        type(self).instances.append(self)

    def schedule(self, handler, path, recursive=False):
        self.scheduled.append((path, recursive))

    def start(self):
        self.started = True

    def stop(self):
        pass

    def join(self, timeout=None):
        pass


@pytest.fixture
def observer(monkeypatch):
    """Make `from watchdog.observers import Observer` hand back the fake."""
    import watchdog.observers

    _FakeObserver.instances = []
    monkeypatch.setattr(watchdog.observers, "Observer", _FakeObserver)
    return _FakeObserver


class _RecordedTimer:
    """threading.Timer that never actually waits -- the test fires it."""

    def __init__(self, delay, fn):
        self.delay = delay
        self.fn = fn
        self.daemon = False
        self.cancelled = False

    def start(self):
        pass

    def cancel(self):
        self.cancelled = True


@pytest.fixture
def timers(monkeypatch):
    armed: list[_RecordedTimer] = []

    def _timer(delay, fn):
        timer = _RecordedTimer(delay, fn)
        armed.append(timer)
        return timer

    monkeypatch.setattr(lane_mod.threading, "Timer", _timer)
    return armed


# ===========================================================================
# The decision: start the observer, or refuse to
# ===========================================================================


def test_a_drive_that_answers_gets_its_watcher(tmp_path, observer):
    lane = _make_lane(tmp_path, probe=lambda root: (WATCH_PROBE_OK, "exit 0"))

    lane._start_watchdog()

    assert lane._observer is not None
    assert observer.instances[0].scheduled == [(lane.local_root, True)]
    assert observer.instances[0].started is True


def test_the_probe_is_given_the_root_the_observer_would_open(tmp_path, observer):
    seen: list[str] = []

    def _probe(root):
        seen.append(root)
        return WATCH_PROBE_OK, "exit 0"

    lane = _make_lane(tmp_path, probe=_probe)
    lane._start_watchdog()

    assert seen == [lane.local_root]


def test_a_blocked_drive_never_reaches_the_observer(tmp_path, observer, timers, caplog):
    """The whole point. `Observer().schedule(...)` is the call that blocked in
    the kernel holding the GIL; on a drive that is not answering it must not
    be made at all."""
    lane = _make_lane(tmp_path, probe=lambda root: (WATCH_PROBE_BLOCKED, "no answer within 5s"))

    with caplog.at_level(logging.ERROR, logger="ccsync.sync.rclone"):
        lane._start_watchdog()

    assert observer.instances == [], "the observer was started on a wedged volume"
    assert lane._observer is None
    message = " ".join(r.getMessage() for r in caplog.records)
    # It must name the condition and the action, not just "failed".
    assert "not answering" in message
    assert "Disconnect and reconnect the drive" in message
    assert "GIL" in message and "MAC-12" in message


def test_a_blocked_drive_toasts_once_no_matter_how_often_it_is_re_checked(
        tmp_path, observer, timers):
    said: list[str] = []
    lane = _make_lane(
        tmp_path,
        probe=lambda root: (WATCH_PROBE_BLOCKED, "no answer within 5s"),
        on_watch_blocked=said.append,
    )

    lane._start_watchdog()
    timers[-1].fn()  # the re-check fires, and finds it still wedged
    timers[-1].fn()

    assert len(said) == 1, "a wedged drive must not toast on every re-check"
    assert "isn't responding" in said[0]
    assert "Disconnect and reconnect the drive" in said[0]
    assert "Everything else is still running" in said[0]


def test_the_re_check_backs_off_and_stops_at_the_cap(tmp_path, observer, timers):
    lane = _make_lane(tmp_path, probe=lambda root: (WATCH_PROBE_BLOCKED, "no answer"))

    lane._start_watchdog()
    assert timers[0].delay == WATCH_PROBE_RETRY_SECONDS
    assert timers[0].daemon is True, "a live timer would hold the process open"

    for _ in range(20):
        timers[-1].fn()
    delays = [t.delay for t in timers]
    assert delays[1] == WATCH_PROBE_RETRY_SECONDS * 2
    assert max(delays) == WATCH_PROBE_MAX_RETRY_SECONDS
    assert delays == sorted(delays), "the backoff must never shrink"


def test_a_remount_brings_the_watcher_back_without_a_restart(
        tmp_path, observer, timers, caplog):
    answers = [
        (WATCH_PROBE_BLOCKED, "no answer within 5s"),
        (WATCH_PROBE_OK, "exit 0"),
    ]
    said: list[str] = []
    lane = _make_lane(tmp_path, probe=lambda root: answers.pop(0), on_watch_blocked=said.append)

    lane._start_watchdog()
    assert lane._observer is None

    with caplog.at_level(logging.INFO, logger="ccsync.sync.rclone"):
        timers[-1].fn()  # the editor replugged the drive

    assert lane._observer is not None
    assert observer.instances[0].scheduled == [(lane.local_root, True)]
    assert len(said) == 2 and "responding again" in said[1]
    assert any("answering again" in r.getMessage() for r in caplog.records)
    # ...and the backoff is reset, so the NEXT wedge is re-checked in a minute
    # rather than in a quarter of an hour.
    assert lane._watch_retry_delay == WATCH_PROBE_RETRY_SECONDS


def test_a_probe_we_could_not_run_fails_OPEN(tmp_path, observer):
    """No interpreter, no /bin/ls, no COMSPEC. Refusing to watch the tree
    because our own probe is missing would be a self-inflicted outage."""
    lane = _make_lane(tmp_path, probe=lambda root: (WATCH_PROBE_UNAVAILABLE, "no such file"))

    lane._start_watchdog()

    assert lane._observer is not None


def test_a_probe_that_raises_fails_OPEN(tmp_path, observer):
    def _boom(root):
        raise RuntimeError("the probe itself is broken")

    lane = _make_lane(tmp_path, probe=_boom)
    lane._start_watchdog()

    assert lane._observer is not None


def test_the_probe_runs_once_per_observer_start_not_per_event(tmp_path, observer):
    """Startup latency and per-event cost are both bounded by this: the whole
    mechanism is one process at sign-in, not one per file the editor drops."""
    calls: list[str] = []
    lane = _make_lane(tmp_path, probe=lambda root: calls.append(root) or (WATCH_PROBE_OK, "exit 0"))

    lane._start_watchdog()
    for _ in range(50):
        lane.notify_path_changed(str(Path(lane.local_root) / "Projects" / "a.mov"))

    assert len(calls) == 1


def test_lane_b_never_probes_anything(tmp_path, observer):
    """Lane B has no watchdog at all -- it must not pay for this."""
    calls: list = []
    lane = _make_lane(
        tmp_path, probe=lambda root: calls.append(root) or (WATCH_PROBE_OK, "exit 0"),
        direction="down",
    )

    lane.start_watchdog_only()

    assert calls == []
    assert lane._observer is None


# ===========================================================================
# ...and the rest of the companion keeps running
# ===========================================================================


def test_the_managed_start_path_returns_instead_of_hanging(tmp_path, observer, timers):
    """`start_watchdog_only()` is the call the Mac never came back from. The
    property is simply that it RETURNS -- everything downstream (the tray,
    the sign-in window, the sequencer) exists only because it does."""
    lane = _make_lane(tmp_path, probe=lambda root: (WATCH_PROBE_BLOCKED, "no answer"))
    done = threading.Event()

    def _start():
        lane.start_watchdog_only()
        done.set()

    threading.Thread(target=_start, daemon=True).start()

    assert done.wait(5.0), "start_watchdog_only() did not return -- this is MAC-12"
    assert lane._observer is None


def test_stop_cancels_a_pending_re_check(tmp_path, observer, timers):
    """A lane that was never allowed to start its watcher must not wake up a
    minute after shutdown and start one."""
    lane = _make_lane(tmp_path, probe=lambda root: (WATCH_PROBE_BLOCKED, "no answer"))
    lane._start_watchdog()
    retry = timers[-1]

    lane.stop()

    assert retry.cancelled is True
    assert lane._watch_retry_timer is None
    assert lane._watch_retry_delay == WATCH_PROBE_RETRY_SECONDS


def test_a_re_check_that_fires_after_stop_starts_nothing(tmp_path, observer, timers):
    """cancel() only helps before the deadline -- the same reason
    _debounced_fire re-checks the stop event."""
    lane = _make_lane(tmp_path, probe=lambda root: (WATCH_PROBE_BLOCKED, "no answer"))
    lane._start_watchdog()
    retry = timers[-1]

    lane.stop()
    retry.fn()

    assert observer.instances == []
    assert lane._observer is None


def test_a_toast_callback_that_raises_never_reaches_the_lane(tmp_path, observer, timers):
    def _boom(_message):
        raise RuntimeError("no tray")

    lane = _make_lane(
        tmp_path, probe=lambda root: (WATCH_PROBE_BLOCKED, "no answer"),
        on_watch_blocked=_boom,
    )

    lane._start_watchdog()  # must not raise

    assert lane._observer is None


# ===========================================================================
# The real probe: the one part a fake cannot prove
# ===========================================================================


def test_the_real_probe_answers_ok_for_a_real_directory(tmp_path):
    """Runs an actual subprocess against an actual directory on this host --
    if the snippet does not parse, or the argv is wrong, everything above is
    testing a fantasy."""
    (tmp_path / "Projects").mkdir()

    status, detail = probe_watch_root(str(tmp_path))

    assert status == WATCH_PROBE_OK, detail
    # The exit code, not just the status: OK is returned for ANY prompt
    # answer, so without this a snippet with a syntax error would pass.
    assert detail == "exit 0"


def test_the_real_probe_answers_promptly_for_a_path_that_is_not_there(tmp_path):
    """A missing root is NOT this check's business: observer.schedule() fails
    cleanly on it and the root guard owns that story. What matters is that the
    filesystem ANSWERED.

    Doubles as proof that the snippet really touches the path it is given: a
    probe that did nothing would exit 0 here.
    """
    status, detail = probe_watch_root(str(tmp_path / "unplugged"))

    assert status == WATCH_PROBE_OK
    assert detail == "exit 1"


def test_the_real_probe_never_takes_longer_than_its_timeout(tmp_path):
    """The bound that makes this safe to call on the startup path. Uses a
    child that sleeps forever, standing in for one blocked in the kernel."""
    import sys

    def _sleeper(cmd, **kwargs):
        kwargs.pop("creationflags", None)
        return subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"], **kwargs)

    started = time.monotonic()
    status, detail = probe_watch_root(str(tmp_path), timeout=0.5, popen_factory=_sleeper)
    elapsed = time.monotonic() - started

    assert status == WATCH_PROBE_BLOCKED, detail
    assert elapsed < 10.0, "the probe outlived its own timeout"


def test_the_real_probe_kills_the_child_it_gave_up_on(tmp_path):
    import sys

    spawned: list = []

    def _sleeper(cmd, **kwargs):
        kwargs.pop("creationflags", None)
        proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"], **kwargs)
        spawned.append(proc)
        return proc

    probe_watch_root(str(tmp_path), timeout=0.5, popen_factory=_sleeper)

    assert spawned and spawned[0].poll() is not None, "a probe process was orphaned"


def test_the_frozen_fallback_command_really_runs_on_this_host(tmp_path):
    """A frozen build cannot use `-c` -- sys.executable is the companion --
    so it shells out to a base-system tool instead. Proven here for THIS
    host's platform (the other one's shape is pinned above), against a path
    with a SPACE in it, which is where a mis-quoted command line would fail
    instantly having touched no filesystem at all.
    """
    root = tmp_path / "Creators Club"
    (root / "Projects").mkdir(parents=True)

    status, detail = probe_watch_root(
        str(root), command_fn=lambda p: watch_probe_command(p, frozen=True))

    assert status == WATCH_PROBE_OK
    assert detail == "exit 0", "the fallback probe did not list the directory"


def test_a_probe_that_cannot_be_started_is_unavailable_not_blocked(tmp_path):
    def _missing(cmd, **kwargs):
        raise FileNotFoundError(2, "No such file or directory")

    status, detail = probe_watch_root(str(tmp_path), popen_factory=_missing)

    assert status == WATCH_PROBE_UNAVAILABLE
    assert "could not start a probe" in detail


def test_the_probe_command_never_re_launches_the_companion():
    """In a frozen build sys.executable IS the companion, so `-c` there would
    start a second companion instead of a probe -- and the probe must not
    import this package in any case (slow, and every import side effect would
    run twice)."""
    frozen_posix = watch_probe_command("/Volumes/SAMDISK/Creators_Club",
                                       executable="/opt/ccsync/ccsync-companion",
                                       frozen=True, is_windows=False)
    assert frozen_posix[0] == "/bin/ls"
    assert "ccsync-companion" not in " ".join(frozen_posix)

    frozen_windows = watch_probe_command(r"P:\Creators_Club",
                                         executable=r"C:\ccsync\ccsync-companion.exe",
                                         frozen=True, is_windows=True)
    assert frozen_windows[1] == "/c"
    assert "ccsync-companion" not in " ".join(frozen_windows)
    # The path is its own argv element: `cmd /c "one long string"` is the
    # classic subprocess trap on Windows -- list2cmdline escapes an embedded
    # quote as \" and cmd.exe does not read it that way, so a root with a
    # space in it would fail instantly having touched no filesystem at all.
    assert frozen_windows[-1] == r"P:\Creators_Club"

    source_run = watch_probe_command("/tmp/root", executable="/usr/bin/python3",
                                     frozen=False, is_windows=False)
    assert source_run[:2] == ["/usr/bin/python3", "-c"]
    assert "ccsync" not in source_run[2], "the probe must not import the package"
    assert source_run[-1] == "/tmp/root"
