"""CR-319 (2026-09-24): the sequencer's skip-ahead.

ruskin (DESKTOP-LQQ41TC) had one project with 97.5 GB of proxies still to
come down and several with nothing, and every ~12-minute round spent ~2 of
them re-checking the quiet ones. A project whose lane B turn ends at the
budget with files left now goes again at once -- but only while every other
project's last turn found nothing up or down, recently enough, and nothing
else (a watcher event, an unconfirmed .stignore, a pending folder, a halt, a
missing drive, the rotate scheme) says it needs its turn.

Shares the fakes in test_sequencer.py, as test_sequencer_perf.py does. The
clock is injected so "checked too long ago" is a number, not a sleep.
"""

from __future__ import annotations

import threading

import pytest

from ccsync_companion.sync.rclone_lane import (
    RUN_OUTCOME_MOVED,
    RUN_OUTCOME_NOTHING,
    RUN_OUTCOME_WORK_REMAINED,
)
from ccsync_companion.sync.sequencer import Sequencer
from test_sequencer import (  # noqa: E402  (sibling test module, not a package)
    FakeAdmin,
    FakeLane,
    FakeSelectionClient,
    _cfg,
    _item,
    _stop_all_sequencers,  # noqa: F401  -- autouse fixture, imported for reuse
    _wait_until,
)

X = "2026/Film/Film 1 + 2"
Y = "2026/Film/Quiet One"
Z = "2026/Film/Quiet Two"
XS, YS, ZS = (f"Projects/{rel}" for rel in (X, Y, Z))


class _Clock:
    def __init__(self) -> None:
        self.t = 1000.0
        self.lock = threading.Lock()

    def __call__(self) -> float:
        with self.lock:
            return self.t

    def advance(self, seconds: float) -> None:
        with self.lock:
            self.t += seconds


class _OutcomeLane(FakeLane):
    """FakeLane plus the CR-319 accessor. `outcomes[subpath]` is the answer
    (default: found nothing); `on_run(subpath)` runs inside run_once."""

    def __init__(self, name, events, outcomes=None, on_run=None):
        super().__init__(name, events)
        self.outcomes = dict(outcomes or {})
        self.on_run = on_run
        self.clock_at = []

    def run_once(self, subpath=None, max_duration_seconds=None, rotation_pass=False):
        super().run_once(subpath)
        if self.on_run is not None:
            self.on_run(subpath)

    def last_run_outcome(self, subpath):
        return self.outcomes.get(subpath, RUN_OUTCOME_NOTHING)


def _items(*, y_upload_only=False):
    y = _item("s-y", Y, 1)
    if y_upload_only:
        y["sync_mode"] = "upload_only"
    return [_item("s-x", X, 0, label="Film 1 + 2"), y, _item("s-z", Z, 2)]


def _build(items=None, *, admin=None, clock=None, x_step=0.0, b_outcomes=None,
           a_outcomes=None, halted=None, on_b=None, **cfg):
    admin = admin or FakeAdmin()
    clock = clock or _Clock()
    b_out = {XS: RUN_OUTCOME_WORK_REMAINED}
    b_out.update(b_outcomes or {})

    def _b_run(subpath):
        if subpath == XS:
            clock.advance(x_step)
        lane_b.clock_at.append((subpath, clock()))
        if on_b is not None:
            on_b(subpath)

    lane_a = _OutcomeLane("lane_a", admin.events, outcomes=a_outcomes)
    lane_b = _OutcomeLane("lane_b", admin.events, outcomes=b_out, on_run=_b_run)
    seq = Sequencer(
        lane_a, lane_b, admin, FakeSelectionClient(selection=items or _items()),
        _cfg(**cfg), folder_status_poll_seconds=0.02, now=clock, halted=halted,
    )
    return seq, lane_a, lane_b, admin, clock


def _b_sequence(seq, lane_b, n):
    seq.start()
    assert _wait_until(lambda: len(lane_b.calls) >= n, timeout=10.0)
    seq.stop()
    return [c.split("/")[-1] for c in lane_b.calls[:n]]


F, Q1, Q2 = "Film 1 + 2", "Quiet One", "Quiet Two"
PLAIN = [F, Q1, Q2, F, Q1, Q2, F, Q1, Q2]


# -- the rule, in ruskin's shape --------------------------------------------


def test_the_busy_project_keeps_going_while_the_others_found_nothing(caplog):
    """Round 1 is the plain rotation (nothing is known yet); from round 2
    on, Film 1 + 2 goes again as long as the quiet two's checks are fresh."""
    seq, _a, lane_b, _admin, _clock = _build()
    with caplog.at_level("INFO", logger="ccsync.sync.sequencer"):
        got = _b_sequence(seq, lane_b, 7)
    assert got == [F, Q1, Q2, F, F, F, F]
    lines = [r.getMessage() for r in caplog.records if "another turn" in r.getMessage()]
    assert lines, "the skip-ahead must say so in the log"
    assert "Film 1 + 2 still has files to fetch and the other 2 projects found nothing" \
        in lines[0]


def test_a_quiet_project_checked_too_long_ago_gets_its_turn():
    """Each Film turn takes 700 s against a 600 s window: the turn that
    started inside the window earns one more, the next does not."""
    seq, _a, lane_b, _admin, _clock = _build(x_step=700.0)
    got = _b_sequence(seq, lane_b, 11)
    assert got == [F, Q1, Q2, F, F, Q1, Q2, F, F, Q1, Q2]


def test_lane_c_turns_for_the_other_projects_keep_coming_within_the_bound():
    """400 s Film turns, 600 s window: three Film turns, then the quiet
    ones -- and each quiet project's lane C turn (its unpause) recurs no
    later than the window plus two Film turns after its last."""
    seq, _a, lane_b, admin, _clock = _build(x_step=400.0)
    got = _b_sequence(seq, lane_b, 13)
    assert got == [F, Q1, Q2, F, F, F, Q1, Q2, F, F, F, Q1, Q2]
    q1_at = [t for sub, t in lane_b.clock_at if sub == YS]
    assert len(q1_at) >= 3
    for earlier, later in zip(q1_at, q1_at[1:]):
        assert later - earlier <= 600 + 2 * 400
    # Every quiet turn ran its lane C turn: one unpause of its folder each.
    unpauses = [e for e in admin.events if e[:2] == ("pause", "s-y") and e[2] is False]
    assert len(unpauses) >= len(q1_at) - 1


def test_the_feature_off_is_the_plain_rotation():
    seq, _a, lane_b, _admin, _clock = _build(lane_b_idle_recheck_seconds=0)
    assert _b_sequence(seq, lane_b, 9) == PLAIN


def test_a_project_with_no_work_left_never_repeats():
    seq, _a, lane_b, _admin, _clock = _build(b_outcomes={XS: RUN_OUTCOME_MOVED})
    assert _b_sequence(seq, lane_b, 9) == PLAIN


@pytest.mark.parametrize("outcome", [RUN_OUTCOME_MOVED, None, RUN_OUTCOME_WORK_REMAINED])
def test_another_project_that_did_not_find_nothing_gets_its_turn(outcome):
    """Transferred files, failed/unknown (None), or itself cut off by the
    budget: none of those is "found nothing"."""
    seq, _a, lane_b, _admin, _clock = _build(b_outcomes={YS: outcome})
    got = _b_sequence(seq, lane_b, 9)
    assert got == PLAIN


@pytest.mark.parametrize("outcome", [RUN_OUTCOME_MOVED, None, RUN_OUTCOME_WORK_REMAINED])
def test_another_project_whose_upload_did_not_find_nothing_gets_its_turn(outcome):
    seq, _a, lane_b, _admin, _clock = _build(a_outcomes={YS: outcome})
    assert _b_sequence(seq, lane_b, 9) == PLAIN


def test_a_lane_without_the_outcome_accessor_rotates_as_before():
    """Every adapter that predates CR-319 answers "don't know"."""
    admin = FakeAdmin()
    lane_a = FakeLane("lane_a", admin.events)
    lane_b = FakeLane("lane_b", admin.events)
    seq = Sequencer(lane_a, lane_b, admin, FakeSelectionClient(selection=_items()),
                    _cfg(), folder_status_poll_seconds=0.02)
    assert _b_sequence(seq, lane_b, 9) == PLAIN


# -- lane A is never delayed -------------------------------------------------


def test_a_file_changed_in_a_quiet_project_stops_the_skip():
    """A watcher event lands in Quiet One while Film 1 + 2 is downloading
    in round 2 -- Quiet One is ALREADY done this pass, which is the case
    notify_change reorders nothing for. The skip must still give way."""
    holder = {}
    film_turns = []

    def on_b(subpath):
        if subpath == XS:
            film_turns.append(subpath)
            if len(film_turns) == 2:
                holder["seq"].notify_change(YS)

    seq, _a, lane_b, _admin, _clock = _build(on_b=on_b)
    holder["seq"] = seq
    got = _b_sequence(seq, lane_b, 5)
    assert got == [F, Q1, Q2, F, Q1]


def test_a_change_during_its_own_turn_keeps_that_project_unskippable():
    holder = {}
    quiet_turns = []

    def on_b(subpath):
        if subpath == YS:
            quiet_turns.append(subpath)
            if len(quiet_turns) == 1:
                # Current project: notify_change returns early for it, but
                # the change is still an upload owed.
                holder["seq"].notify_change(YS)

    seq, _a, lane_b, _admin, _clock = _build(on_b=on_b)
    holder["seq"] = seq
    got = _b_sequence(seq, lane_b, 5)
    assert got == [F, Q1, Q2, F, Q1]


def test_an_upload_only_quiet_project_counts_by_its_uploads():
    seq, _a, lane_b, _admin, _clock = _build(items=_items(y_upload_only=True))
    # Lane B never runs for the upload-only project.
    assert _b_sequence(seq, lane_b, 5) == [F, Q2, F, F, F]


def test_an_upload_only_quiet_project_with_uploads_left_gets_its_turn():
    seq, lane_a, lane_b, _admin, _clock = _build(
        items=_items(y_upload_only=True), a_outcomes={YS: RUN_OUTCOME_WORK_REMAINED})
    assert _b_sequence(seq, lane_b, 6) == [F, Q2, F, Q2, F, Q2]


# -- lane C: what a quiet project's own turn does is never skipped -----------


def test_a_quiet_project_with_unconfirmed_ignores_gets_its_turn():
    admin = FakeAdmin()
    admin._ignores_unconfirmed.add("s-y")
    admin.ignore_raises.add("s-y")
    admin.folder_ignores["s-y"] = None  # missing .stignore: re-assert fails
    seq, _a, lane_b, _admin, _clock = _build(admin=admin)
    assert _b_sequence(seq, lane_b, 9) == PLAIN


def test_a_quiet_project_with_a_folder_waiting_to_be_accepted_gets_its_turn():
    admin = FakeAdmin()
    offered = {"offeredBy": {"DEV": {}}}
    original = admin.pending_folders
    admin.pending_folders = lambda: {"s-z": offered, **original()}
    seq, _a, lane_b, _admin, _clock = _build(admin=admin)
    assert _b_sequence(seq, lane_b, 9) == PLAIN


def test_pending_folders_that_cannot_be_read_mean_no_skip():
    admin = FakeAdmin()
    admin.pending_folders = lambda: (_ for _ in ()).throw(RuntimeError("down"))
    seq, _a, lane_b, _admin, _clock = _build(admin=admin)
    # _maybe_auto_accept fails closed too, so the quiet folders latch
    # unconfirmed -- either way, nobody is skipped.
    assert _b_sequence(seq, lane_b, 9) == PLAIN


def test_the_rotate_scheme_never_skips():
    seq, _a, lane_b, _admin, _clock = _build(lane_c_pause_scheme="rotate")
    assert _b_sequence(seq, lane_b, 9) == PLAIN


# -- the gates that already short-circuit are never bypassed -----------------


def test_a_halt_means_no_skip():
    seq, _a, lane_b, _admin, _clock = _build(halted=lambda: True)
    assert _b_sequence(seq, lane_b, 9) == PLAIN


def test_a_halt_predicate_that_raises_means_no_skip():
    def boom():
        raise RuntimeError("cannot tell")

    seq, _a, lane_b, _admin, _clock = _build(halted=boom)
    assert _b_sequence(seq, lane_b, 9) == PLAIN


def test_a_missing_drive_means_no_skip(tmp_path):
    seq, _a, lane_b, _admin, _clock = _build(local_root=str(tmp_path / "unplugged"))
    assert _b_sequence(seq, lane_b, 9) == PLAIN


def test_an_upload_only_busy_project_is_never_repeated():
    items = _items()
    items[0]["sync_mode"] = "upload_only"
    seq, lane_a, lane_b, _admin, _clock = _build(
        items=items, a_outcomes={XS: RUN_OUTCOME_WORK_REMAINED})
    seq.start()
    assert _wait_until(lambda: len(lane_a.calls) >= 9, timeout=10.0)
    seq.stop()
    assert [c.split("/")[-1] for c in lane_a.calls[:9]] == PLAIN
    assert XS not in lane_b.calls


def test_lane_b_disabled_means_no_skip():
    seq, lane_a, _b, _admin, _clock = _build(lane_b_enabled=False)
    seq.start()
    assert _wait_until(lambda: len(lane_a.calls) >= 9, timeout=10.0)
    seq.stop()
    assert [c.split("/")[-1] for c in lane_a.calls[:9]] == PLAIN


def test_a_single_project_is_never_repeated_inside_one_pass():
    """Pass-level work (shared folders, trash prune, the unpause sweep) runs
    between passes; a pass that never ended would starve it."""
    seq, _a, lane_b, _admin, _clock = _build(items=[_item("s-x", X, 0)])
    passes = []
    original = seq._note_pass_finished
    seq._note_pass_finished = lambda: (passes.append(1), original())[1]
    seq.start()
    assert _wait_until(lambda: len(lane_b.calls) >= 3, timeout=10.0)
    seq.stop()
    assert len(passes) >= 2


def test_state_is_in_memory_so_a_fresh_sequencer_starts_with_a_plain_round():
    seq, _a, lane_b, _admin, clock = _build()
    assert _b_sequence(seq, lane_b, 7)[3:] == [F, F, F, F]
    seq2, _a2, lane_b2, _admin2, _clock2 = _build(clock=clock)
    assert _b_sequence(seq2, lane_b2, 3) == [F, Q1, Q2]


def test_the_bad_config_value_is_a_warning_never_an_error():
    from ccsync_companion import config as config_mod

    cfg = dict(config_mod.DEFAULTS)
    cfg["lane_b_idle_recheck_seconds"] = "soon"
    errors, warnings = config_mod.validate_config(cfg)
    assert not any("lane_b_idle_recheck_seconds" in e for e in errors)
    assert any("lane_b_idle_recheck_seconds" in w for w in warnings)
    seq, *_ = _build(lane_b_idle_recheck_seconds="soon")
    assert seq.lane_b_idle_recheck_seconds == 600


# -- the lane side: what run_once reports ------------------------------------

from pathlib import Path  # noqa: E402

from ccsync_companion.sync.rclone_lane import DIRECTION_DOWN, DIRECTION_UP  # noqa: E402
from test_rclone_lane import (  # noqa: E402
    STATS_LINES,
    _make_lane,
    _make_popen_factory,
    _stub_rclone_available,  # noqa: F401  -- autouse fixture, imported for reuse
)

_QUIET_LINES = ['{"level":"info","msg":"rclone starting"}\n']
_SUB = "Projects/2026/Film/Film 1 + 2"


def _lane(tmp_path, lines, returncode, direction=DIRECTION_UP):
    lane = _make_lane(tmp_path, direction=direction,
                      popen_factory=_make_popen_factory(lines, returncode, []))
    (Path(lane.local_root) / _SUB).mkdir(parents=True, exist_ok=True)
    return lane


def test_a_run_cut_off_by_the_budget_is_work_remained(tmp_path):
    lane = _lane(tmp_path, STATS_LINES, returncode=10)
    lane.run_once(subpath=_SUB, max_duration_seconds=600)
    assert lane.last_run_outcome(_SUB) == RUN_OUTCOME_WORK_REMAINED


def test_a_completed_run_that_moved_nothing_is_nothing(tmp_path):
    lane = _lane(tmp_path, _QUIET_LINES, returncode=0)
    lane.run_once(subpath=_SUB, max_duration_seconds=600)
    assert lane.last_run_moved() == 0
    assert lane.last_run_outcome(_SUB) == RUN_OUTCOME_NOTHING


def test_a_completed_run_that_moved_files_is_moved(tmp_path):
    lane = _lane(tmp_path, STATS_LINES, returncode=0)
    lane.run_once(subpath=_SUB, max_duration_seconds=600)
    assert lane.last_run_moved() > 0
    assert lane.last_run_outcome(_SUB) == RUN_OUTCOME_MOVED


def test_a_failed_run_is_dont_know(tmp_path):
    lane = _lane(tmp_path, _QUIET_LINES, returncode=1)
    lane.run_once(subpath=_SUB, max_duration_seconds=600)
    assert lane.last_run_outcome(_SUB) is None


def test_exit_10_without_a_budget_is_not_work_remained(tmp_path):
    lane = _lane(tmp_path, _QUIET_LINES, returncode=10)
    lane.run_once(subpath=_SUB)
    assert lane.last_run_outcome(_SUB) is None


def test_the_outcome_belongs_to_its_subpath_only(tmp_path):
    lane = _lane(tmp_path, _QUIET_LINES, returncode=0)
    lane.run_once(subpath=_SUB, max_duration_seconds=600)
    assert lane.last_run_outcome("Projects/2026/Film/Other") is None
    assert lane.last_run_outcome(_SUB + "/") == RUN_OUTCOME_NOTHING


def test_an_early_return_forgets_the_previous_outcome(tmp_path):
    lane = _lane(tmp_path, _QUIET_LINES, returncode=0)
    lane.run_once(subpath=_SUB, max_duration_seconds=600)
    assert lane.last_run_outcome(_SUB) == RUN_OUTCOME_NOTHING
    lane._stop_event.set()  # a stopped lane starts nothing
    lane.run_once(subpath=_SUB, max_duration_seconds=600)
    assert lane.last_run_outcome(_SUB) is None


def test_a_project_folder_that_was_never_here_has_nothing_to_upload(tmp_path):
    lane = _make_lane(tmp_path, direction=DIRECTION_UP,
                      popen_factory=_make_popen_factory(_QUIET_LINES, 0, []))
    lane.run_once(subpath=_SUB, max_duration_seconds=600)
    assert lane.last_run_outcome(_SUB) == RUN_OUTCOME_NOTHING


def test_lane_b_down_reports_the_same_way(tmp_path):
    lane = _lane(tmp_path, STATS_LINES, returncode=10, direction=DIRECTION_DOWN)
    lane.run_once(subpath=_SUB, max_duration_seconds=600)
    assert lane.last_run_outcome(_SUB) == RUN_OUTCOME_WORK_REMAINED
