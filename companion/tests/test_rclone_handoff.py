"""Lane A's hand-off (2026-09-26, KNOWN_BUGS CR-347).

A lane A turn that reaches its per-project budget with files still in flight
lets them finish in the background and returns, so the next upload run (and
the rest of the rotation) is not held by one big original on a thin uplink.
leso's Mac, 2026-09-26: a 22 GB drone original uploading ALONE for 13+ hours
at a quarter of the line, three of four transfer slots empty, 52 originals
and a proxy download queued behind it.

No real rclone: a scripted child whose stderr the test feeds and which exits
when told, and a manual clock the test moves, so nothing here sleeps for the
ten minutes a real budget takes.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
from pathlib import Path

import pytest

from ccsync_companion import shutdown_guard
from ccsync_companion.sync import rclone_lane
from ccsync_companion.sync.base import STATE_IDLE, STATE_SYNCING
from ccsync_companion.sync.rclone_lane import DIRECTION_UP, RcloneLane

SUB = "Projects/2026/Base Drone"
BIG = "Interviewees/fx3_20260920_1881.MP4"


@pytest.fixture(autouse=True)
def _stub_rclone_available(monkeypatch):
    monkeypatch.setattr(
        "ccsync_companion.sync.rclone_lane.rclone_available",
        lambda rclone_path: (True, rclone_path),
    )


class _Child:
    """A stand-in for the rclone Popen that runs until the test ends it."""

    def __init__(self, cmd):
        self.cmd = cmd
        self._lines: queue.Queue = queue.Queue()
        self._exited = threading.Event()
        self.returncode = None
        self.terminated = False
        self.stderr = self._stream()

    def _stream(self):
        while True:
            line = self._lines.get()
            if line is None:
                return
            yield line

    def feed(self, *records: dict) -> None:
        for record in records:
            self._lines.put(json.dumps(record) + "\n")

    def exit(self, code: int) -> None:
        if self._exited.is_set():
            return
        self.returncode = code
        self._exited.set()
        self._lines.put(None)

    def wait(self, timeout=None):
        if self._exited.wait(0.01 if timeout is not None else None):
            return self.returncode
        raise subprocess.TimeoutExpired(cmd="rclone", timeout=timeout)

    def poll(self):
        return self.returncode if self._exited.is_set() else None

    def terminate(self):
        self.terminated = True
        self.exit(143)

    def kill(self):
        self.exit(-9)


class _Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def _stats(names: list[str], done: int = 1000, size: int = 22_000_000_000) -> dict:
    return {
        "level": "notice", "msg": "",
        "stats": {
            "bytes": done, "totalBytes": size * max(1, len(names)), "speed": 450000.0,
            "eta": 3600, "transferring": [
                {"name": n, "bytes": done, "size": size, "percentage": 44,
                 "speed": 450000.0, "eta": 3600} for n in names
            ],
        },
    }


def _copied(name: str) -> dict:
    return {"level": "info", "msg": "Copied (new)", "object": name}


def _wait_until(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return bool(predicate())


def _lane(tmp_path, transfers=4, cfg=None):
    children: list[_Child] = []

    def factory(cmd, **kwargs):
        child = _Child(cmd)
        children.append(child)
        return child

    local = tmp_path / "local"
    (local / SUB / "Interviewees").mkdir(parents=True)
    lane = RcloneLane(
        direction=DIRECTION_UP, local_root=str(local), remote="nas",
        remote_root="Creators_Club", state_dir=tmp_path / "state",
        popen_factory=factory, transfers=transfers, cfg=cfg,
    )
    lane._wait_poll_seconds = 0.01
    clock = _Clock()
    lane._monotonic = clock
    return lane, children, clock


def _in_thread(fn):
    out: dict = {}

    def body():
        out["status"] = fn()

    thread = threading.Thread(target=body, daemon=True)
    thread.start()
    return thread, out


def _hand_off(lane, children, clock, names=(BIG,)):
    """Run one rotation pass to its hand-off; return (status, child)."""
    thread, out = _in_thread(lambda: lane.run_once(
        SUB, max_duration_seconds=600, may_hand_off=True))
    assert _wait_until(lambda: len(children) == 1)
    child = children[0]
    child.feed(_stats(list(names)))
    assert _wait_until(lambda: lane._fg_run is not None and lane._fg_run.claims())
    clock.now = 600 + rclone_lane.HANDOFF_GRACE_SECONDS + 1
    thread.join(timeout=5)
    assert not thread.is_alive(), "the pass must return once it is past its budget"
    return out["status"], child


# -- the hand-off itself ------------------------------------------------------


def test_a_pass_past_its_budget_with_a_file_in_flight_returns_and_leaves_it_running(tmp_path):
    lane, children, clock = _lane(tmp_path)
    status, child = _hand_off(lane, children, clock)

    assert not child.terminated and child.poll() is None, (
        "the child is NOT ended: SFTP does not resume, and it had sent 9.8 GB")
    assert lane.handoff_inflight_paths() == [f"{SUB}/{BIG}"]
    assert lane.last_run_outcome(SUB) == rclone_lane.RUN_OUTCOME_WORK_REMAINED
    # The lane still reads as uploading, so no reader thinks it is idle.
    assert status.state == STATE_SYNCING
    assert [row["name"] for row in status.transfers] == [BIG]
    child.exit(10)


def test_the_lane_stays_busy_for_the_keep_awake_guard_while_the_child_runs(tmp_path):
    """busy_lanes wants `syncing`: a Mac allowed to sleep mid-file restarts
    that file from byte 0, which is the whole cost this change is about."""
    lane, children, clock = _lane(tmp_path)
    _status, child = _hand_off(lane, children, clock)

    assert shutdown_guard.busy_lanes([lane.status()]), (
        "a handed-off upload must keep the machine awake")
    child.exit(10)
    assert _wait_until(lambda: not lane._live_handoffs())
    assert lane.status().state == STATE_IDLE
    assert not shutdown_guard.busy_lanes([lane.status()])


def test_the_progress_token_moves_while_only_the_handed_off_child_moves(tmp_path):
    """The dashboard reds a non-terminal state whose token stops (SYS-1)."""
    lane, children, clock = _lane(tmp_path)
    _status, child = _hand_off(lane, children, clock)
    before = lane.status().progress_token
    child.feed(_stats([BIG], done=5_000_000))
    assert _wait_until(lambda: lane.status().progress_token != before)
    child.exit(10)


def test_the_next_pass_gets_the_free_slots_and_leaves_the_file_alone(tmp_path):
    lane, children, clock = _lane(tmp_path)
    _status, first = _hand_off(lane, children, clock)

    clock.now = 0.0
    thread, _out = _in_thread(lambda: lane.run_once(
        SUB, max_duration_seconds=600, may_hand_off=True))
    assert _wait_until(lambda: len(children) == 2)
    second = children[1]
    cmd = second.cmd
    assert cmd[cmd.index("--transfers") + 1] == "3", "four slots, one busy"
    suffix = cmd[cmd.index("--partial-suffix") + 1]
    # Its own temp name: rclone derives the token from the file, so two runs
    # of one file would otherwise interleave into one corrupt .partial.
    assert suffix.endswith(".partial") and suffix != rclone_lane.PARTIAL_SUFFIX
    assert len(suffix) <= 16, "rclone refuses a longer partial suffix"
    rules = Path(cmd[cmd.index("--filter-from") + 1]).read_text(encoding="utf-8")
    assert f"- /{BIG}" in rules.splitlines(), "the handed-off file is kept out"
    second.exit(0)
    thread.join(timeout=5)
    first.exit(10)


def test_a_pass_with_no_handed_off_child_has_the_argv_it_always_had(tmp_path):
    lane, children, _clock = _lane(tmp_path)
    thread, _out = _in_thread(lambda: lane.run_once(
        SUB, max_duration_seconds=600, may_hand_off=True))
    assert _wait_until(lambda: len(children) == 1)
    children[0].exit(0)
    thread.join(timeout=5)
    cmd = children[0].cmd
    assert "--partial-suffix" not in cmd
    assert cmd[cmd.index("--transfers") + 1] == "4"


def test_when_background_uploads_fill_every_slot_no_pass_is_started(tmp_path):
    lane, children, clock = _lane(tmp_path, transfers=1)
    _status, child = _hand_off(lane, children, clock)

    status = lane.run_once(SUB, max_duration_seconds=600, may_hand_off=True)

    assert len(children) == 1, "no second rclone while every slot is moving a file"
    assert status.state == STATE_SYNCING, "the background upload is still the lane's"
    # "Has not looked", never "found nothing": the skip-ahead must not treat
    # this project as done.
    assert lane.last_run_outcome(SUB) is None
    child.exit(10)


# -- what must NOT hand off --------------------------------------------------


def test_consolidate_and_fix_all_still_wait_for_their_upload(tmp_path):
    """They call run_once to WAIT for the file; returning early would tell
    them it had landed."""
    lane, children, clock = _lane(tmp_path)
    thread, _out = _in_thread(lambda: lane.run_once(SUB, max_duration_seconds=600))
    assert _wait_until(lambda: len(children) == 1)
    child = children[0]
    child.feed(_stats([BIG]))
    assert _wait_until(lambda: lane._fg_run is not None and lane._fg_run.claims())
    clock.now = 900
    time.sleep(0.1)
    assert thread.is_alive(), "without may_hand_off the pass waits, as before"
    assert not lane._live_handoffs()
    child.feed(_copied(BIG))
    child.exit(10)
    thread.join(timeout=5)
    assert not thread.is_alive()


def test_a_pass_past_its_budget_with_nothing_in_flight_is_waited_for(tmp_path):
    """No claim = between files or about to exit: nothing to hand off."""
    lane, children, clock = _lane(tmp_path)
    thread, _out = _in_thread(lambda: lane.run_once(
        SUB, max_duration_seconds=600, may_hand_off=True))
    assert _wait_until(lambda: len(children) == 1)
    child = children[0]
    child.feed(_stats([]))
    clock.now = 900
    time.sleep(0.1)
    assert thread.is_alive()
    assert not lane._live_handoffs()
    child.exit(10)
    thread.join(timeout=5)


def test_the_switch_turns_it_off(tmp_path):
    lane, children, clock = _lane(tmp_path, cfg={"lane_a_handoff_enabled": False})
    thread, _out = _in_thread(lambda: lane.run_once(
        SUB, max_duration_seconds=600, may_hand_off=True))
    assert _wait_until(lambda: len(children) == 1)
    children[0].feed(_stats([BIG]))
    assert _wait_until(lambda: lane._fg_run is not None and lane._fg_run.claims())
    clock.now = 900
    time.sleep(0.1)
    assert thread.is_alive()
    children[0].exit(10)
    thread.join(timeout=5)


def test_lane_b_never_hands_off(tmp_path):
    lane, _children, _clock = _lane(tmp_path)
    down = RcloneLane(direction=rclone_lane.DIRECTION_DOWN, local_root=lane.local_root,
                      remote="nas", remote_root="Creators_Club",
                      state_dir=tmp_path / "state-b")
    assert down._handoff_enabled is False


# -- the end of a handed-off child ---------------------------------------------


def test_when_the_child_lands_its_file_the_history_and_the_sequencer_hear_of_it(tmp_path):
    lane, children, clock = _lane(tmp_path)
    woken: list[str] = []
    lane.handoff_done_fn = woken.append
    _status, child = _hand_off(lane, children, clock)
    lane.pop_completions()

    child.feed(_copied(BIG))
    assert _wait_until(lambda: not lane._fg_run and lane.handoff_inflight_paths() == [])
    child.exit(10)

    assert _wait_until(lambda: not lane._live_handoffs())
    assert woken and set(woken) == {SUB}, "its slots are free: wake the rotation"
    names = [row["name"] for row in lane.pop_completions()]
    assert names == [f"{SUB}/{BIG}"], "the file reaches the transfer history once"


def test_each_file_a_background_child_finishes_wakes_the_rotation_at_once(tmp_path):
    """The child starts nothing new after its cutoff, so a slot one of its
    files frees stays empty until the next lane A pass. Asked for when the
    file lands, not when the child's LAST file does: leso's 22 GB original
    would otherwise keep a finished clip's slot idle for hours."""
    small = "Interviewees/small3.MP4"
    lane, children, clock = _lane(tmp_path)
    woken: list[str] = []
    lane.handoff_done_fn = woken.append
    _status, child = _hand_off(lane, children, clock, names=(BIG, small))
    assert woken == []

    child.feed(_copied(small))

    assert _wait_until(lambda: woken == [SUB]), "a freed slot is asked for straight away"
    assert lane.handoff_inflight_paths() == [f"{SUB}/{BIG}"]
    assert child.poll() is None, "the big file goes on"
    child.exit(10)


def test_completions_before_the_hand_off_are_reported_once(tmp_path):
    lane, children, clock = _lane(tmp_path)
    thread, _out = _in_thread(lambda: lane.run_once(
        SUB, max_duration_seconds=600, may_hand_off=True))
    assert _wait_until(lambda: len(children) == 1)
    child = children[0]
    child.feed(_copied("Interviewees/small.MP4"), _stats([BIG]))
    assert _wait_until(lambda: lane._fg_run is not None and lane._fg_run.claims())
    clock.now = 700
    thread.join(timeout=5)
    child.feed(_copied(BIG))
    child.exit(10)
    assert _wait_until(lambda: not lane._live_handoffs())
    time.sleep(0.05)
    names = [row["name"] for row in lane.pop_completions()]
    assert sorted(names) == sorted([f"{SUB}/Interviewees/small.MP4", f"{SUB}/{BIG}"])


def test_stop_ends_a_handed_off_child(tmp_path):
    """Sign-out, a fleet halt, Quit and a self-upgrade all come through
    stop(); a child that outlived it would upload beside the next process."""
    lane, children, clock = _lane(tmp_path)
    woken: list[str] = []
    lane.handoff_done_fn = woken.append
    _status, child = _hand_off(lane, children, clock)

    lane.stop()

    assert child.terminated
    assert _wait_until(lambda: not lane._live_handoffs())
    time.sleep(0.05)
    assert woken == [], "a stopped lane is not asked to run again"


def test_a_stall_in_a_handed_off_child_is_recorded_but_not_blamed_on_the_next_pass(tmp_path):
    lane, children, clock = _lane(tmp_path)
    _status, child = _hand_off(lane, children, clock)

    # Nothing moves for longer than the zero-progress limit.
    clock.now += rclone_lane.zero_progress_limit_seconds(600) + 60
    assert _wait_until(lambda: child.terminated)
    assert _wait_until(lambda: not lane._live_handoffs())

    record = lane.stall_record()
    assert record is not None and record["lane"] == "A"
    assert lane._pending_stall_detail is None, (
        "the next foreground pass is a different child and must not wear this error")


# -- the neighbours: express, the orphan report, a repath ---------------------


def test_express_defers_a_file_a_handed_off_child_is_writing(tmp_path):
    lane, children, clock = _lane(tmp_path)
    _status, child = _hand_off(lane, children, clock)
    path = Path(lane.local_root) / SUB / BIG
    path.write_bytes(b"x" * 10)
    old = time.time() - 3600
    os.utime(path, (old, old))

    rel = f"{SUB}/{BIG}"
    ready, deferred = lane._express_partition({rel: (10, time.monotonic())})

    assert ready == [] and rel in deferred
    child.exit(10)


def test_the_orphan_report_does_not_count_a_temp_file_still_being_written(tmp_path):
    lane, children, clock = _lane(tmp_path)
    _status, child = _hand_off(lane, children, clock)
    test = lane._inflight_partial_test(SUB)

    assert test is not None
    assert test(f"{BIG}.268a72de.partial")
    assert test(f"{BIG}.268a72de.h3.partial")
    assert not test("Interviewees/fx3_20260920_1843.MP4.1234abcd.partial"), (
        "a real orphan is still reported")
    child.exit(10)
    assert _wait_until(lambda: not lane._live_handoffs())
    assert lane._inflight_partial_test(SUB) is None


def test_moving_the_project_folder_ends_the_children_reading_from_it(tmp_path):
    lane, children, clock = _lane(tmp_path)
    _status, child = _hand_off(lane, children, clock)

    other = str(Path(lane.local_root) / "Projects/2026/Elections")
    assert lane.end_handoffs_under(other, "test") == 0
    assert not child.terminated

    ended = lane.end_handoffs_under(str(Path(lane.local_root) / SUB), "moved")
    assert ended == 1 and child.terminated
    assert _wait_until(lambda: not lane._live_handoffs())


# -- the sequencer's half -----------------------------------------------------


class _KwLane:
    """Records the keywords each run_once was given."""

    def __init__(self, name):
        self.name = name
        self.calls: list[dict] = []
        self.ended: list[str] = []

    def run_once(self, subpath=None, max_duration_seconds=None, rotation_pass=False,
                 may_hand_off=False):
        self.calls.append({"subpath": subpath, "may_hand_off": may_hand_off,
                           "rotation_pass": rotation_pass})

    def end_handoffs_under(self, local_dir, why):
        self.ended.append(local_dir)
        return 0


def _sequencer(tmp_path):
    from ccsync_companion.sync.sequencer import Sequencer

    class _Admin:
        def __getattr__(self, name):
            return lambda *a, **kw: {}

    class _Selection:
        enabled = True

        def get(self):
            return None, "live"

        def load_cached(self):
            return None

    lane_a, lane_b = _KwLane("a"), _KwLane("b")
    root = tmp_path / "root"
    root.mkdir()
    seq = Sequencer(lane_a, lane_b, _Admin(), _Selection(),
                    {"local_root": str(root), "project_rotation_seconds": 600},
                    folder_status_poll_seconds=0.01)
    return seq, lane_a, lane_b, root


def test_only_lane_a_is_allowed_to_hand_off(tmp_path):
    seq, lane_a, lane_b, _root = _sequencer(tmp_path)
    seq._run_lanes_a_and_b(SUB, 600)
    assert [c["may_hand_off"] for c in lane_a.calls] == [True]
    assert [c["may_hand_off"] for c in lane_b.calls] == [False]


def test_a_lane_that_predates_the_keyword_is_still_called(tmp_path):
    from ccsync_companion.sync.sequencer import Sequencer

    class _Old:
        def __init__(self):
            self.calls = []

        def run_once(self, subpath=None, max_duration_seconds=None):
            self.calls.append(subpath)

    old = _Old()
    Sequencer._run_lane(old, SUB, 600, may_hand_off=True)
    assert old.calls == [SUB]


def test_the_sequencer_is_woken_when_a_handed_off_upload_ends(tmp_path):
    seq, lane_a, _lane_b, _root = _sequencer(tmp_path)
    assert lane_a.handoff_done_fn == seq.notify_change


def test_a_repath_move_ends_the_background_uploads_in_that_folder_first(tmp_path):
    seq, lane_a, _lane_b, root = _sequencer(tmp_path)
    src = root / "Projects/2026/Old Name"
    src.mkdir(parents=True)
    (src / "clip.mov").write_bytes(b"x")
    dst = root / "Projects/2026/New Name"

    seq._guarded_move(str(src), str(dst))

    assert lane_a.ended == [str(src)]
    assert (dst / "clip.mov").exists() and not src.exists()
    assert seq.repather._move == seq._guarded_move
    assert seq.borrowed_folders._move_dir == seq._guarded_move
