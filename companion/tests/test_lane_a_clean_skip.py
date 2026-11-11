"""Lane A's clean-project skip and its narrow re-check pool (2026-11-05).

ruskin's companion ran `rclone copy --ignore-existing` up for each of his 14
ticked projects on every pass, ~6 minutes apart, each with its own pool of up
to 16 SSH connections. The NAS logged ~1,900 logins an hour from his machine,
in bursts of ~150, on passes that uploaded nothing at all.

Now a project whose last lane A run checked everything and found nothing, and
that the file watcher has seen no write in since, is skipped; it is re-checked
with a narrow pool (sftp_connections_verify / checkers_verify) at least every
lane_a_verify_seconds. Every doubt -- no watcher, a different watcher, a
change, a deferred file, a run that moved or failed, "Sync now", a resume --
is a full run.

These drive Sequencer._run_lanes_a_and_b directly with an injected clock, so
"two hours later" is a number, not a sleep.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ccsync_companion.sync.rclone_lane import (
    DIRECTION_UP,
    RUN_OUTCOME_MOVED,
    RUN_OUTCOME_NOTHING,
    RcloneLane,
    RcloneTuning,
)
from ccsync_companion.sync.sequencer import (
    LANE_A_CHANGE_SETTLE_SECONDS,
    Sequencer,
)
from test_sequencer import (  # noqa: E402  (sibling test module, not a package)
    FakeAdmin,
    FakeLane,
    FakeSelectionClient,
    _cfg,
    _item,
    _stop_all_sequencers,  # noqa: F401  -- autouse fixture, imported for reuse
)

REL = "2026/FF5/Civil Defence"
SUB = f"Projects/{REL}"
SLUG = "s-civil"


class _Clock:
    def __init__(self) -> None:
        self.t = 10_000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


class _WatchedLane:
    """Lane A with a watcher. `outcome`, `deferred` and `epoch` are what the
    NEXT run reports; `calls` records (subpath, verify_only)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, bool]] = []
        self.outcome = RUN_OUTCOME_NOTHING
        self.deferred = False
        self.epoch: int | None = 1

    def run_once(self, subpath=None, max_duration_seconds=None, rotation_pass=False,
                 may_hand_off=False, verify_only=False):
        self.calls.append((subpath, verify_only))

    def last_run_outcome(self, subpath):
        return self.outcome

    def last_run_deferred(self):
        return self.deferred

    def watch_epoch(self):
        return self.epoch


def _build(lane_a=None, clock=None, **cfg):
    admin = FakeAdmin()
    lane_a = lane_a or _WatchedLane()
    lane_b = FakeLane("lane_b", admin.events)
    clock = clock or _Clock()
    seq = Sequencer(
        lane_a, lane_b, admin,
        FakeSelectionClient(selection=[_item(SLUG, REL, 0)]),
        _cfg(lane_b_enabled=False, **cfg), folder_status_poll_seconds=0.02, now=clock,
    )
    # notify_change maps a rel to a slug through the known selection.
    seq._update_known_selection([_item(SLUG, REL, 0)])
    return seq, lane_a, clock


def _turn(seq):
    return seq._run_lanes_a_and_b(SUB, 600.0, slug=SLUG)


def _runs(lane):
    return [verify for _sub, verify in lane.calls]


# -- the rule ----------------------------------------------------------------


def test_a_clean_project_is_skipped_until_the_recheck_is_due():
    seq, lane, clock = _build()
    assert _turn(seq)["a"] == RUN_OUTCOME_NOTHING      # first: nothing known, full
    clock.advance(360)
    out = _turn(seq)                                    # clean, no change: skipped
    assert out["a"] == RUN_OUTCOME_NOTHING, "a skip reads as 'found nothing' for CR-319"
    assert _runs(lane) == [False]

    clock.advance(seq.lane_a_verify_seconds)            # past the window: re-check, narrow
    _turn(seq)
    assert _runs(lane) == [False, True]
    clock.advance(360)                                  # that re-check was clean too
    _turn(seq)
    assert _runs(lane) == [False, True]


def test_a_watcher_event_after_the_clean_run_means_a_full_run():
    seq, lane, clock = _build()
    _turn(seq)
    clock.advance(400)
    seq.notify_change(SUB)
    clock.advance(200)
    _turn(seq)
    assert _runs(lane) == [False, False]


def test_a_change_just_before_the_clean_run_started_is_not_covered_by_it():
    """--min-age kept a fresh file out of that run, so its "nothing" says
    nothing about the file. Only a run that started a settle period after
    the write covers it."""
    seq, lane, clock = _build()
    seq.notify_change(SUB)
    clock.advance(LANE_A_CHANGE_SETTLE_SECONDS - 10)
    _turn(seq)                      # clean, but too soon after the write
    clock.advance(300)
    _turn(seq)                      # so this one runs
    clock.advance(300)
    _turn(seq)                      # and that one did cover it: skipped
    assert _runs(lane) == [False, False]


@pytest.mark.parametrize("change", ["moved", "deferred", "new_watcher", "no_watcher"])
def test_anything_short_of_a_clean_watched_check_means_a_full_run(change):
    seq, lane, clock = _build()
    if change == "moved":
        lane.outcome = RUN_OUTCOME_MOVED
    elif change == "deferred":
        lane.deferred = True      # express had a file in flight: not looked at
    _turn(seq)
    if change == "new_watcher":
        lane.epoch = 2
    elif change == "no_watcher":
        lane.epoch = None
    lane.outcome = RUN_OUTCOME_NOTHING
    lane.deferred = False
    clock.advance(300)
    _turn(seq)
    assert _runs(lane) == [False, False]


def test_a_watcher_that_restarted_during_the_run_makes_it_not_clean():
    """Writes made while the old observer was down were never seen, so a run
    whose start and end saw different observers proves nothing."""

    class _Restarting(_WatchedLane):
        def run_once(self, *args, **kwargs):
            super().run_once(*args, **kwargs)
            if len(self.calls) == 1:
                self.epoch = 2

    seq, lane, clock = _build(lane_a=_Restarting())
    _turn(seq)
    clock.advance(300)
    _turn(seq)            # not covered: full
    clock.advance(300)
    _turn(seq)            # the second run was watched throughout: skipped
    assert _runs(lane) == [False, False]


def test_a_lane_with_no_watcher_api_always_runs():
    """Older lane objects and test doubles: never skipped."""
    admin = FakeAdmin()
    lane_a = FakeLane("lane_a", admin.events)
    seq = Sequencer(lane_a, FakeLane("lane_b", admin.events), admin,
                    FakeSelectionClient(selection=[_item(SLUG, REL, 0)]),
                    _cfg(lane_b_enabled=False), folder_status_poll_seconds=0.02)
    for _ in range(3):
        seq._run_lanes_a_and_b(SUB, 600.0, slug=SLUG)
    assert lane_a.calls == [SUB, SUB, SUB]


@pytest.mark.parametrize("how", ["trigger_pass_now", "resume"])
def test_sync_now_and_resume_forget_every_clean_check(how):
    seq, lane, clock = _build()
    _turn(seq)
    getattr(seq, how)()
    clock.advance(60)
    _turn(seq)
    assert _runs(lane) == [False, False]


def test_zero_turns_the_skip_off():
    seq, lane, clock = _build(lane_a_verify_seconds=0)
    for _ in range(3):
        _turn(seq)
        clock.advance(300)
    assert _runs(lane) == [False, False, False]


def test_a_failed_lane_b_this_pass_turns_skips_into_narrow_rechecks():
    """The offline test needs lane A to have RUN on the project where lane B
    failed; a skipped lane A cannot fail, and a laptop off the tailnet would
    then grind through every project's lane B timeout."""
    seq, lane, clock = _build()
    _turn(seq)
    seq._pass_b_failed = True
    clock.advance(300)
    _turn(seq)
    assert _runs(lane) == [False, True]


def test_a_skip_is_per_subpath_and_a_change_in_the_project_covers_its_borrowed_ones():
    seq, lane, clock = _build()
    borrowed = "Projects/2026/FF5/Shared/B-roll"
    seq._run_lanes_a_and_b(SUB, 600.0, slug=SLUG)
    seq._run_lanes_a_and_b(borrowed, 600.0, slug=SLUG)
    clock.advance(300)
    seq.notify_change(SUB)
    clock.advance(10)
    seq._run_lanes_a_and_b(SUB, 600.0, slug=SLUG)
    seq._run_lanes_a_and_b(borrowed, 600.0, slug=SLUG)
    assert [s for s, _v in lane.calls] == [SUB, borrowed, SUB, borrowed]


# -- the lane half -----------------------------------------------------------


def test_verify_tuning_only_narrows():
    t = RcloneTuning()
    v = t.for_verify()
    assert (v.sftp_connections, v.checkers) == (4, 4)
    assert v.sftp_chunk_size == t.sftp_chunk_size and v.sftp_concurrency == t.sftp_concurrency
    # Never wider than the normal pool...
    assert RcloneTuning(sftp_connections=2, checkers=2).for_verify().sftp_connections == 2
    # ...0 (unlimited) is wider than anything...
    assert RcloneTuning(sftp_connections=0).for_verify().sftp_connections == 4
    # ...and a verify knob of 0 leaves the normal value alone.
    off = RcloneTuning(sftp_connections_verify=0, checkers_verify=0).for_verify()
    assert (off.sftp_connections, off.checkers) == (16, 16)


def test_verify_tuning_comes_from_config():
    t = RcloneTuning.from_cfg({"sftp_connections_verify": 2, "checkers_verify": 3})
    assert (t.for_verify().sftp_connections, t.for_verify().checkers) == (2, 3)


def _lane(tmp_path):
    (tmp_path / "local").mkdir(parents=True, exist_ok=True)
    return RcloneLane(
        direction=DIRECTION_UP, local_root=str(tmp_path / "local"), remote="nas",
        remote_root="Creators_Club", state_dir=tmp_path / "state",
        watch_debounce_seconds=30.0,
    )


def _flag(cmd, name):
    return cmd[cmd.index(name) + 1]


def test_a_verify_run_carries_the_narrow_pool(tmp_path):
    lane = _lane(tmp_path)
    full = lane._build_command(subpath="Projects/2026/P")
    verify = lane._build_command(subpath="Projects/2026/P", verify_only=True)
    assert (_flag(full, "--sftp-connections"), _flag(full, "--checkers")) == ("16", "16")
    assert (_flag(verify, "--sftp-connections"), _flag(verify, "--checkers")) == ("4", "4")
    assert _flag(verify, "--transfers") == _flag(full, "--transfers")


def test_a_command_that_left_files_to_express_is_marked_deferred(tmp_path):
    lane = _lane(tmp_path)
    lane._build_command(subpath="Projects/2026/P")
    assert lane.last_run_deferred() is False
    with lane._express_inflight_lock:
        lane._express_inflight |= {"Projects/2026/P/B-roll/a.mov"}
    lane._build_command(subpath="Projects/2026/P")
    assert lane.last_run_deferred() is True


def test_server_moved_excludes_do_not_count_as_deferred(tmp_path):
    lane = _lane(tmp_path)
    lane.extra_excludes_fn = lambda subpath: ["B-roll/old.mov"]
    lane._build_command(subpath="Projects/2026/P")
    assert lane.last_run_deferred() is False


def test_watch_epoch_is_none_without_a_live_observer(tmp_path):
    lane = _lane(tmp_path)
    assert lane.watch_epoch() is None

    class _Obs:
        def __init__(self, alive):
            self.alive = alive

        def is_alive(self):
            return self.alive

    lane._watch_epoch = 3
    lane._observer = _Obs(True)
    assert lane.watch_epoch() == 3
    lane._observer = _Obs(False)
    assert lane.watch_epoch() is None
    lane._observer = None


# -- audit comp-sync-2 (2026-11-11): what makes a clean check stale ---------------


def test_a_flip_to_upload_only_runs_lane_a_in_full_again():
    """Full -> upload-only widens lane A's filter from video to every file, so the earlier
    "found nothing" says nothing about what is now in scope. It used to SKIP for up to two hours."""
    seq, lane, clock = _build()
    _turn(seq)
    clock.advance(360)
    _turn(seq)
    assert _runs(lane) == [False]                       # clean, skipped
    flipped = dict(_item(SLUG, REL, 0), sync_mode="upload_only")
    seq._update_known_selection([flipped])
    clock.advance(360)
    _turn(seq)
    assert _runs(lane) == [False, False]                # looked at again, in full


def test_an_untick_and_a_retick_forget_the_clean_check():
    """While unticked the watcher cannot map a write to the project, so nothing records it."""
    seq, lane, clock = _build()
    _turn(seq)
    seq._update_known_selection([])                     # unticked
    seq.notify_change(SUB)                              # written to meanwhile: no slug, no change time
    seq._update_known_selection([_item(SLUG, REL, 0)])  # ticked again
    clock.advance(360)
    _turn(seq)
    assert _runs(lane) == [False, False]
    assert SLUG not in seq._lane_a_changed_at or seq._lane_a_changed_at[SLUG] <= clock()


def test_an_unchanged_selection_keeps_the_skip():
    seq, lane, clock = _build()
    _turn(seq)
    for _ in range(3):                                  # the 30 s selection refresh, nothing different
        seq._update_known_selection([_item(SLUG, REL, 0)])
        clock.advance(360)
        _turn(seq)
    assert _runs(lane) == [False]
