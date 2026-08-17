"""Lane B's circuit breaker, the .ccsync-trash retention policy, and the
sync halt (COMMERCIAL_READINESS.md item 9, 2026-08-17).

No real rclone binary: the remote listing, the dry-run probe and the check
run all go through injected runners, exactly as test_rclone_lane.py does for
the transfer itself.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from ccsync_companion.sync import lane_guard
from ccsync_companion.sync.base import STATE_IDLE, STATE_PAUSED
from ccsync_companion.sync.rclone_lane import (
    DIRECTION_DOWN,
    DIRECTION_UP,
    RcloneLane,
    list_remote_top,
    scan_pending_uploads,
    scan_size_mismatches,
)


@pytest.fixture(autouse=True)
def _stub_rclone_available(monkeypatch):
    monkeypatch.setattr(
        "ccsync_companion.sync.rclone_lane.rclone_available",
        lambda rclone_path: (True, rclone_path),
    )


def _breaker(tmp_path, **cfg):
    return lane_guard.LaneBBreaker(tmp_path / "breaker.json", cfg)


# -- trigger 1: the remote does not look like the tree ----------------------


def test_a_root_with_no_marker_directory_trips_before_anything_runs(tmp_path):
    breaker = _breaker(tmp_path)
    reason = breaker.check_remote("", ["Documents", "Downloads"])
    assert reason is not None
    assert "remote_root" in reason
    assert breaker.tripped


def test_a_root_that_holds_projects_is_fine(tmp_path):
    breaker = _breaker(tmp_path)
    assert breaker.check_remote("", ["Projects", "Assets"]) is None
    assert not breaker.tripped


def test_an_empty_listing_where_there_used_to_be_one_trips(tmp_path):
    breaker = _breaker(tmp_path)
    assert breaker.check_remote("Projects/2026/X", ["a", "b", "c", "d"]) is None
    reason = breaker.check_remote("Projects/2026/X", [])
    assert reason is not None and "EMPTY" in reason
    assert breaker.tripped


def test_an_empty_listing_at_a_scope_never_seen_before_does_not_trip(tmp_path):
    # A project that has not been created on the NAS yet is empty, and that
    # is not evidence of anything.
    breaker = _breaker(tmp_path)
    assert breaker.check_remote("Projects/2026/New", []) is None
    assert not breaker.tripped


def test_a_listing_that_halves_trips(tmp_path):
    breaker = _breaker(tmp_path)
    breaker.check_remote("Projects/2026/X", [f"d{i}" for i in range(10)])
    reason = breaker.check_remote("Projects/2026/X", ["d0", "d1", "d2"])
    assert reason is not None and "shrank" in reason
    assert breaker.tripped


def test_a_listing_that_shrinks_from_a_tiny_sample_does_not_trip(tmp_path):
    breaker = _breaker(tmp_path)
    breaker.check_remote("Projects/2026/X", ["a", "b"])
    assert breaker.check_remote("Projects/2026/X", ["a"]) is None
    assert not breaker.tripped


def test_a_failed_listing_is_not_a_trip(tmp_path):
    # rclone will fail the run on its own; needing an operator to clear a
    # flapping tailnet would make the breaker the bigger problem.
    breaker = _breaker(tmp_path)
    breaker.check_remote("Projects/2026/X", ["a", "b", "c", "d"])
    assert breaker.check_remote("Projects/2026/X", None) is None
    assert not breaker.tripped


def test_dot_entries_do_not_count_as_a_populated_remote(tmp_path):
    breaker = _breaker(tmp_path)
    breaker.check_remote("Projects/2026/X", ["a", "b", "c", "d"])
    # .stfolder/.stversions exist whether or not a single project does --
    # list_remote_top drops them, so this arrives already empty.
    assert breaker.check_remote("Projects/2026/X", []) is not None


# -- triggers 2 and 3: what the pass did ------------------------------------


def test_a_pass_over_the_absolute_cap_trips(tmp_path):
    breaker = _breaker(tmp_path, lane_b_max_deletes_per_pass=10)
    assert breaker.note_pass("Projects/X", 11, 1000) is not None
    assert breaker.tripped


def test_a_pass_under_the_caps_does_not_trip(tmp_path):
    breaker = _breaker(tmp_path, lane_b_max_deletes_per_pass=10)
    assert breaker.note_pass("Projects/X", 3, 1000, local_proxies=100) is None
    assert not breaker.tripped


def test_the_fraction_rule_catches_a_small_project(tmp_path):
    # 12 of 40 is under the absolute cap of 50 but 30% of everything there.
    breaker = _breaker(tmp_path, lane_b_max_delete_fraction=0.25)
    reason = breaker.note_pass("Projects/X", 12, 0, local_proxies=40)
    assert reason is not None and "40 local proxies" in reason


def test_the_fraction_rule_is_off_below_the_minimum_sample(tmp_path):
    breaker = _breaker(tmp_path, lane_b_max_delete_fraction=0.25)
    assert breaker.note_pass("Projects/X", 2, 0, local_proxies=4) is None
    assert not breaker.tripped


def test_a_slow_leak_trips_on_the_cumulative_rule(tmp_path):
    breaker = _breaker(tmp_path, lane_b_max_deletes_per_pass=20,
                       lane_b_max_deletes_cumulative=45)
    assert breaker.note_pass("Projects/X", 20, 0) is None
    assert breaker.note_pass("Projects/X", 20, 0) is None
    reason = breaker.note_pass("Projects/X", 20, 0)
    assert reason is not None and "slow leak" in reason


def test_trip_fires_the_callback_exactly_once(tmp_path):
    seen: list[str] = []
    breaker = lane_guard.LaneBBreaker(
        tmp_path / "b.json", {"lane_b_max_deletes_per_pass": 1},
        on_trip=seen.append,
    )
    breaker.note_pass("X", 5, 0)
    breaker.note_pass("X", 5, 0)
    assert len(seen) == 1


# -- persistence and resume -------------------------------------------------


def test_a_trip_survives_a_restart(tmp_path):
    breaker = _breaker(tmp_path, lane_b_max_deletes_per_pass=1)
    breaker.note_pass("Projects/X", 9, 0)
    revived = _breaker(tmp_path)
    assert revived.tripped
    assert revived.reason == breaker.reason


def test_resume_clears_the_latch_and_the_counters(tmp_path):
    breaker = _breaker(tmp_path, lane_b_max_deletes_per_pass=1,
                       lane_b_max_deletes_cumulative=5)
    breaker.note_pass("Projects/X", 9, 0)
    assert breaker.resume("tray") is True
    assert not breaker.tripped
    # Without clearing the counters the very next pass re-trips on the
    # cumulative rule and the button reads as broken.
    assert breaker.report()["deletes"] == 0
    assert breaker.resume("tray") is False
    assert _breaker(tmp_path).tripped is False


def test_a_corrupt_state_file_reads_as_not_tripped(tmp_path):
    (tmp_path / "breaker.json").write_text("{not json", encoding="utf-8")
    assert _breaker(tmp_path).tripped is False


# -- the lane itself --------------------------------------------------------


def _lane_b(tmp_path, breaker=None, remote_entries=None, popen_factory=None):
    (tmp_path / "local").mkdir(parents=True, exist_ok=True)

    def remote_list(cmd, timeout):
        if remote_entries is None:
            return None
        return "\n".join(remote_entries)

    return RcloneLane(
        direction=DIRECTION_DOWN,
        local_root=str(tmp_path / "local"),
        remote="nas",
        remote_root="Creators_Club",
        state_dir=tmp_path / "state",
        breaker=breaker,
        remote_list_fn=remote_list,
        popen_factory=popen_factory,
    )


class _FakeProc:
    def __init__(self, lines, returncode):
        self.stderr = iter(lines)
        self._rc = returncode

    def wait(self):
        return self._rc


def _factory(lines, rc, calls):
    def make(cmd, **kwargs):
        calls.append(cmd)
        return _FakeProc(lines, rc)
    return make


def test_a_tripped_breaker_stops_lane_b_before_rclone_is_spawned(tmp_path):
    breaker = _breaker(tmp_path)
    breaker.trip("the NAS listed the tree as empty")
    calls: list[list[str]] = []
    lane = _lane_b(tmp_path, breaker=breaker, remote_entries=["Projects"],
                   popen_factory=_factory([], 0, calls))
    status = lane.run_once()
    assert calls == []
    assert status.state == STATE_PAUSED
    assert "STOPPED (safety)" in status.detail
    assert "empty" in status.detail


def test_an_empty_remote_trips_the_lane_without_deleting_anything(tmp_path):
    breaker = _breaker(tmp_path)
    breaker.check_remote("", ["Projects"])          # the healthy pass before
    calls: list[list[str]] = []
    lane = _lane_b(tmp_path, breaker=breaker, remote_entries=[],
                   popen_factory=_factory([], 0, calls))
    status = lane.run_once()
    assert calls == [], "no rclone may run against a remote that lists empty"
    assert status.state == STATE_PAUSED
    assert breaker.tripped


def test_a_healthy_pass_leaves_the_lane_running(tmp_path):
    breaker = _breaker(tmp_path)
    calls: list[list[str]] = []
    lines = ['{"level":"info","msg":"p.mov: Copied (new)"}\n']
    lane = _lane_b(tmp_path, breaker=breaker, remote_entries=["Projects"],
                   popen_factory=_factory(lines, 0, calls))
    status = lane.run_once()
    assert calls, "the pass should have run"
    assert status.state == STATE_IDLE
    assert not breaker.tripped


def test_a_pass_that_trashes_too_much_trips_the_lane(tmp_path):
    breaker = _breaker(tmp_path, lane_b_max_deletes_per_pass=2)
    calls: list[list[str]] = []
    lines = [
        '{"level":"info","msg":"a.mov: Moved into backup dir"}\n',
        '{"level":"info","msg":"b.mov: Moved into backup dir"}\n',
        '{"level":"info","msg":"c.mov: Moved into backup dir"}\n',
    ]
    lane = _lane_b(tmp_path, breaker=breaker, remote_entries=["Projects"],
                   popen_factory=_factory(lines, 0, calls))
    status = lane.run_once()
    assert breaker.tripped
    assert status.state == STATE_PAUSED
    # ...and the NEXT pass does not run at all.
    calls.clear()
    lane.run_once()
    assert calls == []


def test_resume_after_trip_puts_the_lane_back(tmp_path):
    breaker = _breaker(tmp_path)
    breaker.trip("something")
    lane = _lane_b(tmp_path, breaker=breaker, remote_entries=["Projects"])
    assert lane.resume_after_trip("tray") is True
    assert lane.status().state == STATE_IDLE
    assert lane.resume_after_trip("tray") is False


def test_lane_a_has_no_breaker(tmp_path):
    # Lane A is `copy` and deletes nothing; a breaker there would be a
    # safety device guarding an operation that is already additive.
    (tmp_path / "local").mkdir(parents=True, exist_ok=True)
    lane = RcloneLane(direction=DIRECTION_UP, local_root=str(tmp_path / "local"),
                      remote="nas", remote_root="CC", state_dir=tmp_path / "state")
    assert lane.breaker is None


def test_a_lane_b_built_without_one_still_gets_a_breaker(tmp_path):
    lane = _lane_b(tmp_path)
    assert lane.breaker is not None


# -- .ccsync-trash retention ------------------------------------------------


def _trash_batch(root: Path, name: str, age_days: float, size: int = 1000) -> Path:
    batch = root / lane_guard.TRASH_DIR_NAME / name / "Projects"
    batch.mkdir(parents=True)
    f = batch / "clip.mov"
    f.write_bytes(b"x" * size)
    when = time.time() - age_days * 86400.0
    import os

    os.utime(f, (when, when))
    os.utime(batch.parent, (when, when))
    return batch.parent


def test_a_batch_older_than_the_window_is_pruned(tmp_path):
    _trash_batch(tmp_path, "20260701-000000", age_days=30)
    keep = _trash_batch(tmp_path, "20260817-000000", age_days=1)
    summary = lane_guard.prune_trash(str(tmp_path), max_age_days=14)
    assert summary["removed"] == 1
    assert keep.exists()


def test_the_size_cap_prunes_oldest_first_and_never_the_last_one(tmp_path):
    _trash_batch(tmp_path, "20260810-000000", age_days=3, size=1000)
    newest = _trash_batch(tmp_path, "20260816-000000", age_days=1, size=1000)
    summary = lane_guard.prune_trash(str(tmp_path), max_age_days=0, max_bytes=1)
    # Over the cap by miles, and still exactly one batch survives: the newest
    # is the one somebody is most likely to be about to ask for.
    assert summary["removed"] == 1
    assert newest.exists()


def test_nothing_is_pruned_while_the_breaker_is_tripped(tmp_path):
    old = _trash_batch(tmp_path, "20260101-000000", age_days=400)
    breaker = _breaker(tmp_path)
    breaker.trip("a bad pass")
    summary = lane_guard.prune_trash(str(tmp_path), max_age_days=14, breaker=breaker)
    assert summary["removed"] == 0
    assert old.exists(), "a trip is exactly when the recovery copies matter"


def test_prune_on_an_empty_tree_is_a_no_op(tmp_path):
    assert lane_guard.prune_trash(str(tmp_path))["removed"] == 0


def test_count_local_proxies_counts_only_proxy_dirs_and_skips_the_trash(tmp_path):
    root = tmp_path / "local"
    (root / "Projects" / "X" / "Proxy").mkdir(parents=True)
    (root / "Projects" / "X" / "Proxy" / "a.mov").write_bytes(b"x")
    (root / "Projects" / "X" / "Proxy" / "b.mov").write_bytes(b"x")
    (root / "Projects" / "X" / "orig.braw").write_bytes(b"x")
    trash = root / lane_guard.TRASH_DIR_NAME / "20260101-000000" / "Proxy"
    trash.mkdir(parents=True)
    (trash / "gone.mov").write_bytes(b"x")
    assert lane_guard.count_local_proxies(str(root)) == 2
    assert lane_guard.count_local_proxies(str(root), "Projects/X") == 2


# -- the halt ---------------------------------------------------------------


def test_a_halt_survives_a_restart(tmp_path):
    halt = lane_guard.HaltState(tmp_path / "halt.json")
    assert halt.engage("the NAS is being rebuilt") is True
    revived = lane_guard.HaltState(tmp_path / "halt.json")
    assert revived.active
    assert revived.reason == "the NAS is being rebuilt"


def test_an_editor_cannot_release_a_fleet_halt(tmp_path):
    halt = lane_guard.HaltState(tmp_path / "halt.json")
    halt.engage("admin stopped everything", lane_guard.HALT_SCOPE_FLEET)
    ok, message = halt.release(by="tray")
    assert ok is False
    assert "administrator" in message
    assert halt.active
    ok, _ = halt.release(by="dashboard", force=True)
    assert ok and not halt.active


def test_the_dashboards_flag_engages_and_releases(tmp_path):
    halt = lane_guard.HaltState(tmp_path / "halt.json")
    assert halt.note_fleet_flag({"active": True, "reason": "stop"}) is True
    assert halt.note_fleet_flag({"active": True, "reason": "stop"}) is None
    assert halt.active
    assert halt.note_fleet_flag({"active": False}) is False
    assert not halt.active


def test_a_reply_with_no_halt_key_leaves_a_fleet_halt_alone(tmp_path):
    # An older dashboard says nothing about the halt; absence of the field is
    # absence of information, not a release.
    halt = lane_guard.HaltState(tmp_path / "halt.json")
    halt.note_fleet_flag({"active": True, "reason": "stop"})
    assert halt.note_fleet_flag(None) is None
    assert halt.active


def test_a_local_halt_is_not_cleared_by_the_dashboard_saying_nothing(tmp_path):
    halt = lane_guard.HaltState(tmp_path / "halt.json")
    halt.engage("I stopped it", lane_guard.HALT_SCOPE_LOCAL)
    assert halt.note_fleet_flag({"active": False}) is None
    assert halt.active, "the fleet flag must not clear an editor's own halt"


# -- the probes -------------------------------------------------------------


def test_list_remote_top_drops_dot_entries(tmp_path):
    out = list_remote_top(
        "rclone", "nas", "CC", None,
        run_fn=lambda cmd, t: "Projects/\n.stfolder/\n.stversions/\nAssets/\n",
    )
    assert out == ["Projects", "Assets"]


def test_list_remote_top_returns_none_when_the_listing_fails(tmp_path):
    assert list_remote_top("rclone", "nas", "CC", None,
                           run_fn=lambda cmd, t: None) is None


def test_pending_uploads_counts_the_dry_runs_skipped_copies(tmp_path):
    (tmp_path / "local").mkdir()
    filter_file = tmp_path / "f.txt"
    filter_file.write_text("+ *.mov\n- **\n", encoding="utf-8")
    stderr = (
        '{"level":"notice","msg":"A001.mov: Skipped copy as --dry-run is set",'
        '"object":"A001.mov"}\n'
        '{"level":"notice","msg":"A002.mov: Skipped copy as --dry-run is set",'
        '"object":"A002.mov"}\n'
        '{"level":"info","msg":"there was nothing else"}\n'
    )
    seen: list[list[str]] = []

    def run(cmd, timeout):
        seen.append(cmd)
        return 0, stderr

    out = scan_pending_uploads("rclone", str(tmp_path / "local"), "nas", "CC",
                               filter_file, "Projects/X", run_fn=run)
    assert out == {"count": 2, "samples": ["A001.mov", "A002.mov"]}
    assert "--dry-run" in seen[0]


def test_pending_uploads_returns_none_when_the_probe_fails(tmp_path):
    # None is load-bearing: the removal gate must refuse on it.
    (tmp_path / "local").mkdir()
    filter_file = tmp_path / "f.txt"
    filter_file.write_text("+ *.mov\n- **\n", encoding="utf-8")
    assert scan_pending_uploads(
        "rclone", str(tmp_path / "local"), "nas", "CC", filter_file, "Projects/X",
        run_fn=lambda cmd, t: (1, "boom"),
    ) is None


def test_size_mismatches_reads_the_differ_list(tmp_path):
    (tmp_path / "local").mkdir()
    filter_file = tmp_path / "f.txt"
    filter_file.write_text("+ *.mov\n- **\n", encoding="utf-8")
    seen: list[list[str]] = []

    def run(cmd, timeout):
        seen.append(cmd)
        return "A001.mov\nB/B002.mov\n"

    out = scan_size_mismatches("rclone", str(tmp_path / "local"), "nas", "CC",
                               filter_file, "Projects/X", run_fn=run)
    assert out["count"] == 2
    assert out["samples"] == ["A001.mov", "B/B002.mov"]
    assert "--one-way" in seen[0] and "--size-only" in seen[0]
    assert "--differ" in seen[0]


def test_the_lane_reports_its_guard_state(tmp_path):
    breaker = _breaker(tmp_path)
    breaker.trip("bad remote")
    lane = _lane_b(tmp_path, breaker=breaker)
    report = lane.sync_guard_report()
    assert report["lane_b_breaker"]["tripped"] is True
    assert report["lane_b_breaker"]["reason"] == "bad remote"


def test_the_breaker_state_file_is_json_a_human_can_read(tmp_path):
    breaker = _breaker(tmp_path)
    breaker.trip("because")
    data = json.loads((tmp_path / "breaker.json").read_text(encoding="utf-8"))
    assert data["tripped"] is True and data["reason"] == "because"
