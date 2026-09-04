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
    list_remote_files,
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

    def wait(self, timeout=None):
        # SYNC-1/SYS-17: proc.wait() is polled with a timeout now.
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
    # ...and what follows the prefix is the EDITOR's sentence, not the trip
    # reason (SYNC-106, wave 5 of the 2026-09-03 sweep): this string is what
    # the tray line, the balloon, the Settings window and the dashboard chip
    # all render. The technical reason stays on the breaker, for the log, the
    # report and copy_diagnostics.
    assert status.detail.endswith(
        lane_guard.BREAKER_EDITOR_REASONS[lane_guard.BREAKER_CAUSE_EMPTY])
    assert "listed the tree as empty" not in status.detail
    assert breaker.reason == "the NAS listed the tree as empty"
    assert breaker.report()["reason"] == "the NAS listed the tree as empty"


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
    assert "your admin stopped syncing" in message
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


# -- moved, not deleted (KNOWN_BUGS CR-44, 2026-08-20) ----------------------
#
# The breaker's blind spot until now: an editor drags a folder somewhere else
# in the project and every proxy under it leaves the path lane B is syncing
# at once. Nothing was deleted, everything is still on the NAS, and the
# breaker read it as the tree being emptied -- ruskin's PC, 2026-08-19.


def test_a_pass_that_only_relocated_files_does_not_trip(tmp_path):
    breaker = _breaker(tmp_path, lane_b_max_deletes_per_pass=10)
    # 100 files left the folder; all 100 are still on the NAS elsewhere.
    assert breaker.note_pass("Projects/X", 100, 0,
                             relocation_probe=lambda: 100) is None
    assert not breaker.tripped
    # ...and they are off the cumulative counter too, or the NEXT ordinary
    # pass trips on a leak that never happened.
    assert breaker.report()["deletes"] == 0
    assert breaker.report()["last_pass_deletes"] == 0


def test_real_deletions_hiding_behind_a_move_still_trip(tmp_path):
    breaker = _breaker(tmp_path, lane_b_max_deletes_per_pass=10)
    # 100 trashed, 80 of them relocations -- 20 real deletions is still over
    # the cap of 10, and the reason says so without hiding the moves.
    reason = breaker.note_pass("Projects/X", 100, 0, relocation_probe=lambda: 80)
    assert reason is not None
    assert "20 file(s)" in reason
    assert "80 were moved to a new folder" in reason
    assert breaker.tripped


def test_the_probe_is_not_run_on_a_pass_that_was_never_going_to_trip(tmp_path):
    # It costs a recursive listing of the whole scope. On the ~99% of passes
    # that are nowhere near a limit it must not be spent at all.
    calls: list[int] = []

    def probe():
        calls.append(1)
        return 0

    breaker = _breaker(tmp_path, lane_b_max_deletes_per_pass=10)
    assert breaker.note_pass("Projects/X", 3, 0, relocation_probe=probe) is None
    assert calls == []


def test_a_probe_that_throws_leaves_the_breaker_as_strict_as_before(tmp_path):
    def probe():
        raise OSError("the NAS went away mid-listing")

    breaker = _breaker(tmp_path, lane_b_max_deletes_per_pass=10)
    assert breaker.note_pass("Projects/X", 50, 0, relocation_probe=probe) is not None
    assert breaker.tripped


def test_a_probe_cannot_claim_more_moves_than_the_pass_had_deletions(tmp_path):
    # A bug in the probe must not be able to talk the breaker out of a trip.
    breaker = _breaker(tmp_path, lane_b_max_deletes_per_pass=10)
    assert breaker.note_pass("Projects/X", 50, 0,
                             relocation_probe=lambda: 5000) is None
    assert breaker.report()["deletes"] == 0


def test_relocations_do_not_dodge_the_cumulative_rule_for_real_deletions(tmp_path):
    breaker = _breaker(tmp_path, lane_b_max_deletes_per_pass=100,
                       lane_b_max_deletes_cumulative=30)
    # Three passes of 20, half of each a genuine deletion: the moves come off
    # the counter, the deletions stay on it, and the leak still trips.
    assert breaker.note_pass("Projects/X", 20, 0, relocation_probe=lambda: 10) is None
    assert breaker.note_pass("Projects/X", 20, 0, relocation_probe=lambda: 10) is None
    reason = breaker.note_pass("Projects/X", 20, 0, relocation_probe=lambda: 10)
    assert reason is not None and "slow leak" in reason


def test_list_remote_files_keys_by_basename_and_size(tmp_path):
    # Sizes first, then the path -- and a filename containing the separator
    # and fullwidth punctuation, which is what yt-dlp names actually look
    # like in this tree.
    output = (
        "12;Projects/2026/X/Proxy/a.mov\n"
        "34;Projects/2026/X/B-roll/a.mov\n"
        "56;Projects/2026/X/Proxy/News ; clip [abc].mov\n"
        "not-a-size;Projects/2026/X/junk\n"
        "\n"
    )
    found = list_remote_files("rclone", "nas", "root", "Projects/2026/X",
                              run_fn=lambda cmd, timeout: output)
    assert found["a.mov"] == {12, 34}
    assert found["News ; clip [abc].mov"] == {56}
    assert "junk" not in found


def test_list_remote_files_tells_a_failed_listing_from_an_empty_one(tmp_path):
    # None and {} must not be confused: an empty remote is exactly the case
    # the breaker exists for, and it must stay free to trip there.
    assert list_remote_files("rclone", "nas", "root", None,
                             run_fn=lambda cmd, timeout: None) is None
    assert list_remote_files("rclone", "nas", "root", None,
                             run_fn=lambda cmd, timeout: "") == {}


def _lane_b_with_trash(tmp_path, breaker, remote_recursive, trashed=("a.mov", "b.mov", "c.mov")):
    """A lane B whose last pass moved `trashed` into its backup dir, with the
    recursive remote listing the relocation probe will see."""
    trash = tmp_path / "local" / ".ccsync-trash" / "20260820-120000" / "Proxy"
    trash.mkdir(parents=True)
    for name in trashed:
        (trash / name).write_bytes(b"x" * 7)

    def remote_list(cmd, timeout):
        if "-R" in cmd:
            return remote_recursive
        return "Projects"

    lines = [
        '{"level":"info","msg":"%s: Moved into backup dir"}\n' % name
        for name in trashed
    ]
    lane = RcloneLane(
        direction=DIRECTION_DOWN,
        local_root=str(tmp_path / "local"),
        remote="nas",
        remote_root="Creators_Club",
        state_dir=tmp_path / "state",
        breaker=breaker,
        remote_list_fn=remote_list,
        popen_factory=_factory(lines, 0, []),
    )
    # run_once() computes its own --backup-dir (a fresh timestamp), so pin
    # it to the one this fixture actually populated.
    lane._backup_dir = lambda subpath=None: str(trash.parent)
    return lane


def test_a_lane_pass_that_moved_a_folder_does_not_trip(tmp_path):
    # End to end through the lane: rclone reports three files moved into the
    # backup dir, and all three are still on the NAS under a new path.
    breaker = _breaker(tmp_path, lane_b_max_deletes_per_pass=2)
    lane = _lane_b_with_trash(tmp_path, breaker, "".join(
        f"7;Projects/2026/X/B-roll/{name}\n" for name in ("a.mov", "b.mov", "c.mov")
    ))
    status = lane.run_once()
    assert not breaker.tripped, "a folder move is not an emptied tree"
    assert status.state == STATE_IDLE


def test_a_lane_pass_whose_files_really_are_gone_still_trips(tmp_path):
    breaker = _breaker(tmp_path, lane_b_max_deletes_per_pass=2)
    lane = _lane_b_with_trash(tmp_path, breaker, "")     # the NAS has none of them
    lane.run_once()
    assert breaker.tripped


def test_a_same_named_file_at_a_different_size_is_not_a_move(tmp_path):
    # A re-encode (the base rig superseding .mp4 proxies with .mov ones)
    # really is a deletion of the old bytes, and must keep counting as one.
    breaker = _breaker(tmp_path, lane_b_max_deletes_per_pass=2)
    lane = _lane_b_with_trash(tmp_path, breaker, "".join(
        f"999;Projects/2026/X/Proxy/{name}\n" for name in ("a.mov", "b.mov", "c.mov")
    ))
    lane.run_once()
    assert breaker.tripped


# -- the 2026-08-21 hunt ----------------------------------------------------


def test_resume_drops_the_remembered_remote_listing(tmp_path):
    """comp-lanes-ab-1: a trigger-1 trip re-tripped on the identical listing
    the moment the lane ran again, because resume() cleared the deletion
    counters and left the remote baseline on disk. The [ RESUME ] button was
    dead for any deliberate consolidation on the NAS."""
    breaker = _breaker(tmp_path)
    assert breaker.check_remote("Projects/X", [f"f{i}" for i in range(10)]) is None
    assert breaker.check_remote("Projects/X", ["f0", "f1"]) is not None
    assert breaker.tripped

    assert breaker.resume("tray") is True
    # The same listing the operator has just approved must now be the
    # baseline, not the evidence for another trip.
    assert breaker.check_remote("Projects/X", ["f0", "f1"]) is None
    assert not breaker.tripped
    assert breaker.check_remote("Projects/X", ["f0", "f1"]) is None


def test_resume_drops_the_baseline_for_the_empty_listing_trigger_too(tmp_path):
    breaker = _breaker(tmp_path)
    breaker.check_remote("Projects/X", ["a", "b", "c"])
    assert breaker.check_remote("Projects/X", []) is not None
    breaker.resume("tray")
    assert breaker.check_remote("Projects/X", []) is None
    assert not breaker.tripped


def test_a_resume_request_is_applied_exactly_once(tmp_path):
    """comp-lanes-ab-2: the dashboard's [ RESUME ] rides every report reply
    until an admin clears it, so the same request must not clear a LATER
    trip."""
    breaker = _breaker(tmp_path, lane_b_max_deletes_per_pass=1)
    breaker.note_pass("Projects/X", 9, 0)
    assert breaker.resume("dashboard", request_id="2026-08-21T10:00:00Z") is True
    assert not breaker.tripped
    # Same standing request, next report: no-op.
    assert breaker.resume("dashboard", request_id="2026-08-21T10:00:00Z") is False
    breaker.note_pass("Projects/X", 9, 0)
    assert breaker.tripped
    assert breaker.resume("dashboard", request_id="2026-08-21T10:00:00Z") is False
    assert breaker.tripped, "an old request must not clear a new trip"
    assert breaker.resume("dashboard", request_id="2026-08-21T11:00:00Z") is True


def test_an_applied_resume_request_survives_a_restart(tmp_path):
    breaker = _breaker(tmp_path, lane_b_max_deletes_per_pass=1)
    breaker.note_pass("Projects/X", 9, 0)
    assert breaker.resume("dashboard", request_id="req-1") is True
    revived = _breaker(tmp_path, lane_b_max_deletes_per_pass=1)
    revived.note_pass("Projects/X", 9, 0)
    assert revived.tripped
    assert revived.resume("dashboard", request_id="req-1") is False


def test_moves_are_discounted_before_they_fill_the_cumulative_counter(tmp_path):
    """comp-lanes-ab-5: five passes of 40 moved files never trip the per-pass
    rule, so the probe never ran and all 200 stayed on the cumulative
    counter -- and the next handful of REAL deletions tripped a 'slow leak'
    made almost entirely of files still on the NAS."""
    breaker = _breaker(tmp_path, lane_b_max_deletes_per_pass=50,
                       lane_b_max_deletes_cumulative=200)
    for _ in range(5):
        assert breaker.note_pass("Projects/X", 40, 0,
                                 relocation_probe=lambda: 40) is None
    assert breaker.report()["deletes"] == 0
    assert breaker.note_pass("Projects/X", 8, 0, relocation_probe=lambda: 0) is None
    assert not breaker.tripped


def test_a_small_tidy_pass_still_costs_no_probe(tmp_path):
    # The probe is a recursive remote listing; it must not be spent on the
    # handful of proxies an ordinary re-render supersedes.
    calls = []
    breaker = _breaker(tmp_path, lane_b_max_deletes_per_pass=50)
    breaker.note_pass("Projects/X", 3, 0,
                      relocation_probe=lambda: calls.append(1) or 0)
    assert calls == []


def test_a_torn_write_cannot_lose_a_tripped_breaker(tmp_path, monkeypatch):
    """sync-safety-8: the state file was written in place, so a power loss
    or a self-upgrade kill mid-write left an empty/partial file -- which
    reads as NOT TRIPPED and takes the remote baseline with it."""
    breaker = _breaker(tmp_path, lane_b_max_deletes_per_pass=1)
    breaker.check_remote("Projects/X", ["a", "b", "c", "d"])
    breaker.note_pass("Projects/X", 9, 0)
    assert breaker.tripped

    real_write = Path.write_text

    def torn(self, data, *args, **kwargs):
        real_write(self, data[: max(1, len(data) // 2)], *args, **kwargs)
        raise OSError("the power went out")

    monkeypatch.setattr(Path, "write_text", torn)
    breaker.note_pass("Projects/X", 1, 0)
    monkeypatch.undo()

    revived = _breaker(tmp_path)
    assert revived.tripped
    assert revived.check_remote("Projects/X", []) is not None, (
        "the remote baseline must survive too -- trigger 1 has nothing to "
        "compare against without it"
    )


def test_a_successful_write_leaves_no_temp_file_behind(tmp_path):
    breaker = _breaker(tmp_path)
    breaker.trip("because")
    assert (tmp_path / "breaker.json").is_file()
    assert not (tmp_path / "breaker.json.tmp").exists()


def test_a_proxy_rewritten_on_the_nas_at_the_same_path_is_not_a_deletion(tmp_path):
    """comp-lanes-ab-3: lane B's --min-age hides a proxy the NAS rewrote in
    the last 120 s from the SOURCE listing while the editor's older local
    copy stays on the destination side, so rclone moves it into the trash
    without replacing it. A bulk re-render then trips the breaker on files
    that are all on the server, and the basename+size probe cannot excuse
    them because a re-encode changes the size."""
    breaker = _breaker(tmp_path, lane_b_max_deletes_per_pass=2)
    lane = _lane_b_with_trash(tmp_path, breaker, "".join(
        # Same relative path as the trashed copies, brand new sizes.
        f"999;Proxy/{name}\n" for name in ("a.mov", "b.mov", "c.mov")
    ))
    status = lane.run_once()
    assert not breaker.tripped, "the files are all still on the NAS, at that path"
    assert status.state == STATE_IDLE


def test_the_remote_root_marker_probe_runs_in_managed_mode(tmp_path):
    """sync-safety-5: every managed pass names a project subpath, so the
    breaker's marker rule (`if not key`) never ran -- the one pre-flight that
    catches a remote_root pointing at the wrong dataset was dark on the whole
    fleet."""
    calls = []

    def remote_list(cmd, timeout):
        calls.append(cmd)
        return "Documents\nDownloads\n"

    breaker = _breaker(tmp_path)
    (tmp_path / "local").mkdir(parents=True, exist_ok=True)
    lane = RcloneLane(
        direction=DIRECTION_DOWN,
        local_root=str(tmp_path / "local"),
        remote="nas",
        remote_root="home",
        state_dir=tmp_path / "state",
        breaker=breaker,
        remote_list_fn=remote_list,
    )
    assert lane.check_remote_root() is False
    assert breaker.tripped
    assert "remote_root" in breaker.reason
    assert len(calls) == 1


def test_the_remote_root_probe_is_paid_for_once(tmp_path):
    calls = []

    def remote_list(cmd, timeout):
        calls.append(cmd)
        return "Projects\nAssets\n"

    breaker = _breaker(tmp_path)
    (tmp_path / "local").mkdir(parents=True, exist_ok=True)
    lane = RcloneLane(
        direction=DIRECTION_DOWN,
        local_root=str(tmp_path / "local"),
        remote="nas",
        remote_root="Creators_Club",
        state_dir=tmp_path / "state",
        breaker=breaker,
        remote_list_fn=remote_list,
    )
    assert lane.check_remote_root() is True
    assert lane.check_remote_root() is True
    assert len(calls) == 1
    assert not breaker.tripped


# -- APP-3: the latches live where a support session will not delete them ---


def test_adopting_a_legacy_latch_moves_it(tmp_path):
    legacy = tmp_path / "state" / lane_guard.BREAKER_STATE_FILENAME
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text(json.dumps({"tripped": True, "reason": "shrank"}),
                      encoding="utf-8")
    new = tmp_path / lane_guard.BREAKER_STATE_FILENAME

    assert lane_guard.adopt_legacy_latch(new, legacy) == new
    assert json.loads(new.read_text(encoding="utf-8"))["tripped"] is True
    # Moved, not copied: a downgrade must not re-latch on a stale file.
    assert not legacy.exists()

    breaker = lane_guard.LaneBBreaker(new, {})
    assert breaker.tripped is True


def test_adoption_never_overwrites_a_latch_already_in_the_new_place(tmp_path):
    legacy = tmp_path / "state" / lane_guard.HALT_STATE_FILENAME
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text(json.dumps({"active": False}), encoding="utf-8")
    new = tmp_path / lane_guard.HALT_STATE_FILENAME
    new.write_text(json.dumps({"active": True, "scope": "fleet"}), encoding="utf-8")

    lane_guard.adopt_legacy_latch(new, legacy)
    assert lane_guard.HaltState(new).active is True


def test_adoption_is_a_no_op_and_never_raises_without_a_legacy_file(tmp_path):
    new = tmp_path / lane_guard.BREAKER_STATE_FILENAME
    assert lane_guard.adopt_legacy_latch(new, tmp_path / "state" / "nope.json") == new
    assert not new.exists()
    assert lane_guard.LaneBBreaker(new, {}).tripped is False


def test_a_fresh_trip_writes_to_the_new_location(tmp_path):
    """The whole point: the file the breaker latches into is beside
    config.toml, not under the state/ directory support sessions delete."""
    new = tmp_path / lane_guard.BREAKER_STATE_FILENAME
    breaker = lane_guard.LaneBBreaker(new, {})
    breaker.trip("a test trip")
    assert new.exists()
    assert not (tmp_path / "state").exists()
    assert lane_guard.LaneBBreaker(new, {}).tripped is True


# -- lane B's free-space floor (SYS-5 / SYNC-7, sweep 2026-08-28) -----------


def _floor(tmp_path, **cfg):
    return lane_guard.DiskFloorLatch(tmp_path / "disk.json", cfg)


def test_a_drive_under_the_floor_parks_lane_b(tmp_path):
    latch = _floor(tmp_path, lane_b_min_free_bytes=20 * 1024**3)
    reason = latch.check(8 * 1024**3)
    assert reason is not None and "8 GB free" in reason
    assert latch.parked


def test_a_drive_above_the_floor_parks_nothing(tmp_path):
    latch = _floor(tmp_path, lane_b_min_free_bytes=20 * 1024**3)
    assert latch.check(500 * 1024**3) is None
    assert not latch.parked


def test_the_park_clears_itself_only_at_twice_the_floor(tmp_path):
    latch = _floor(tmp_path, lane_b_min_free_bytes=20 * 1024**3)
    latch.check(1 * 1024**3)
    # Back over the floor but inside the hysteresis band: still parked, or the
    # sentence would flicker on and off after one deleted clip.
    assert latch.check(25 * 1024**3) is not None
    assert latch.parked
    assert latch.check(41 * 1024**3) is None
    assert not latch.parked


def test_a_measurement_that_failed_changes_nothing_either_way(tmp_path):
    latch = _floor(tmp_path, lane_b_min_free_bytes=20 * 1024**3)
    assert latch.check(None) is None
    assert not latch.parked, "'could not measure' must never park a lane"
    latch.check(1 * 1024**3)
    assert latch.check(None) is not None, "...nor release one that is full"
    assert latch.parked


def test_a_park_survives_a_restart(tmp_path):
    _floor(tmp_path, lane_b_min_free_bytes=20 * 1024**3).check(2 * 1024**3)
    again = _floor(tmp_path, lane_b_min_free_bytes=20 * 1024**3)
    assert again.parked and again.reason


def test_the_tray_can_clear_the_park(tmp_path):
    latch = _floor(tmp_path, lane_b_min_free_bytes=20 * 1024**3)
    latch.check(2 * 1024**3)
    assert latch.resume("tray") is True
    assert not latch.parked
    # Idempotent, like the breaker's resume: a second click is not an error.
    assert latch.resume("tray") is False


def test_a_floor_of_zero_turns_the_whole_device_off(tmp_path):
    latch = _floor(tmp_path, lane_b_min_free_bytes=0)
    assert not latch.enabled
    assert latch.check(0) is None
    assert not latch.parked


def test_lane_b_stands_down_paused_under_the_floor_and_spawns_nothing(tmp_path):
    calls: list[list[str]] = []
    lane = _lane_b(tmp_path, remote_entries=["Projects"],
                   popen_factory=_factory([], 0, calls))
    lane.disk_floor = _floor(tmp_path, lane_b_min_free_bytes=20 * 1024**3)
    lane._free_bytes_fn = lambda path: 3 * 1024**3
    status = lane.run_once()
    assert calls == [], "no rclone may run against a drive with no room on it"
    # PAUSED, never ERROR: the lane is not broken, and lanes A and C keep
    # running exactly as they do for a breaker trip.
    assert status.state == STATE_PAUSED
    assert status.last_error is None
    assert "3 GB free" in (status.detail or "")
    assert lane.disk_floor.parked
    assert lane.sync_guard_report()["disk_floor"]["parked"] is True


def test_lane_b_runs_again_by_itself_once_there_is_room(tmp_path):
    calls: list[list[str]] = []
    lane = _lane_b(tmp_path, remote_entries=["Projects"],
                   popen_factory=_factory([], 0, calls))
    lane.disk_floor = _floor(tmp_path, lane_b_min_free_bytes=20 * 1024**3)
    lane._free_bytes_fn = lambda path: 3 * 1024**3
    lane.run_once()
    assert calls == []
    lane._free_bytes_fn = lambda path: 500 * 1024**3
    lane.run_once()
    assert calls, "the park has to clear on its own -- nobody clicks anything"
    assert not lane.disk_floor.parked


def test_a_free_space_probe_that_raises_never_parks_the_lane(tmp_path):
    calls: list[list[str]] = []
    lane = _lane_b(tmp_path, remote_entries=["Projects"],
                   popen_factory=_factory([], 0, calls))
    lane.disk_floor = _floor(tmp_path, lane_b_min_free_bytes=20 * 1024**3)

    def boom(path):
        raise OSError("no such device")

    lane._free_bytes_fn = boom
    lane.run_once()
    assert calls, "our own broken probe must not stop an editor syncing"
    assert not lane.disk_floor.parked


def test_the_disk_report_names_both_volumes_and_never_raises(tmp_path):
    class _Usage:
        def __init__(self, free, total):
            self.free, self.total = free, total

    report = lane_guard.disk_report(
        str(tmp_path), system_path=str(tmp_path),
        usage_fn=lambda path: _Usage(7, 100),
    )
    assert report["root_free_bytes"] == 7
    assert report["root_total_bytes"] == 100
    assert report["system_free_bytes"] == 7
    assert report["at"]

    def boom(path):
        raise OSError("gone")

    unknown = lane_guard.disk_report(str(tmp_path), usage_fn=boom)
    # None, NOT 0: a drive we could not measure must never render as a drive
    # with no space left (nor as one that is fine).
    assert unknown["root_free_bytes"] is None
    assert unknown["root_total_bytes"] is None
    assert unknown["system_free_bytes"] is None


# -- the trash prune's third trigger and its ordering fallback (SYNC-16) ----


def test_disk_pressure_prunes_what_age_and_size_would_have_kept(tmp_path):
    old = _trash_batch(tmp_path, "20260820-000000", age_days=2, size=1000)
    newest = _trash_batch(tmp_path, "20260827-000000", age_days=1, size=1000)
    summary = lane_guard.prune_trash(
        str(tmp_path), max_age_days=14, max_bytes=0,
        min_free_bytes=50 * 1024**3, free_bytes_fn=lambda root: 1 * 1024**3,
    )
    assert summary["removed"] == 1
    assert not old.exists()
    assert newest.exists(), "the newest batch is never the one that goes"


def test_disk_pressure_prunes_nothing_when_the_drive_has_room(tmp_path):
    keep = _trash_batch(tmp_path, "20260820-000000", age_days=2)
    summary = lane_guard.prune_trash(
        str(tmp_path), max_age_days=14, max_bytes=0,
        min_free_bytes=20 * 1024**3, free_bytes_fn=lambda root: 500 * 1024**3,
    )
    assert summary["removed"] == 0 and keep.exists()


def test_disk_pressure_that_cannot_be_measured_prunes_nothing(tmp_path):
    keep = _trash_batch(tmp_path, "20260820-000000", age_days=2)
    _trash_batch(tmp_path, "20260821-000000", age_days=2)
    summary = lane_guard.prune_trash(
        str(tmp_path), max_age_days=14, max_bytes=0,
        min_free_bytes=20 * 1024**3, free_bytes_fn=lambda root: None,
    )
    assert summary["removed"] == 0 and keep.exists()


def test_the_breaker_still_gates_the_disk_pressure_prune(tmp_path):
    old = _trash_batch(tmp_path, "20260101-000000", age_days=400)
    _trash_batch(tmp_path, "20260102-000000", age_days=399)
    breaker = _breaker(tmp_path)
    breaker.trip("a bad pass")
    summary = lane_guard.prune_trash(
        str(tmp_path), max_age_days=14, breaker=breaker,
        min_free_bytes=50 * 1024**3, free_bytes_fn=lambda root: 0,
    )
    assert summary["removed"] == 0 and old.exists()


def test_a_batch_with_no_usable_timestamp_sorts_by_its_name(tmp_path):
    """SYNC-16: `trash_entries` yielded 0.0 for such a batch, which made a
    batch created seconds ago the OLDEST thing in the trash -- so the size
    rule deleted it before one created a fortnight back."""
    import os

    old = _trash_batch(tmp_path, "20260101-000000", age_days=400, size=1000)
    # The newest batch, with no usable timestamp anywhere in it: an empty
    # directory whose own mtime is the epoch is exactly what a batch whose
    # every stat failed looks like to trash_entries.
    fresh = tmp_path / lane_guard.TRASH_DIR_NAME / "20260827-120000"
    fresh.mkdir(parents=True)
    os.utime(fresh, (0, 0))

    entries = {p.name: m for p, m, _s in lane_guard.trash_entries(str(tmp_path))}
    assert entries["20260827-120000"] > entries["20260101-000000"]

    summary = lane_guard.prune_trash(str(tmp_path), max_age_days=0, max_bytes=1)
    assert summary["removed"] == 1
    assert fresh.exists(), "the newest batch must never be the first one dropped"
    assert not old.exists()


def test_batch_stamp_reads_the_directory_name_and_refuses_anything_else():
    assert lane_guard.batch_stamp("20260827-120000") is not None
    assert lane_guard.batch_stamp("not-a-batch") is None
    assert lane_guard.batch_stamp("") is None
    assert lane_guard.batch_stamp(None) is None


def test_the_sequencer_prunes_the_trash_on_a_lane_that_keeps_failing():
    """SYNC-16: the prune was the LAST statement of a fully successful lane B
    pass, so the machine that needed it most -- one erroring every pass with
    50 GB of recovery copies on a full disk -- never reached it."""
    from ccsync_companion.sync import sequencer as sequencer_mod

    class _SickLaneB:
        def __init__(self):
            self.pruned = 0

        def _maybe_prune_trash(self):
            self.pruned += 1

    seq = sequencer_mod.Sequencer.__new__(sequencer_mod.Sequencer)
    seq.lane_b = _SickLaneB()
    seq.lane_b_enabled = True
    seq._prune_trash()
    assert seq.lane_b.pruned == 1

    def boom():
        raise OSError("the volume went away mid-walk")

    seq.lane_b._maybe_prune_trash = boom
    seq._prune_trash()  # fault-isolated, exactly like _check_remote_root


# -- SYNC-112: the recovery folder can be named, opened and explained --------

def test_trash_summary_counts_the_folder_in_one_walk(tmp_path):
    """SYNC-112 (sweep 2026-09-03): `.ccsync-trash` is the whole "nothing was
    deleted" story and the editor had no way to open it, no idea how much was
    in it and no warning that the copies expire."""
    _trash_batch(tmp_path, "20260701-000000", age_days=30, size=500)
    _trash_batch(tmp_path, "20260817-000000", age_days=1, size=1500)
    summary = lane_guard.trash_summary(str(tmp_path), max_age_days=14, now=1.0)
    assert summary["path"].endswith(lane_guard.TRASH_DIR_NAME)
    assert summary["count"] == 2 and summary["bytes"] == 2000
    assert summary["retention_days"] == 14
    # The OLDEST batch, from the directory name _backup_dir wrote.
    assert summary["oldest"] == lane_guard.batch_stamp("20260701-000000")


def test_trash_summary_is_cached_then_refreshed(tmp_path):
    _trash_batch(tmp_path, "20260701-000000", age_days=30, size=500)
    first = lane_guard.trash_summary(str(tmp_path), now=1000.0)
    _trash_batch(tmp_path, "20260817-000000", age_days=1, size=1500)
    assert lane_guard.trash_summary(str(tmp_path), now=1010.0) == first
    later = lane_guard.trash_summary(
        str(tmp_path), now=1000.0 + lane_guard.TRASH_SUMMARY_CACHE_SECONDS + 1)
    assert later["count"] == 2


def test_trash_summary_of_a_machine_with_no_trash_is_zero_not_none(tmp_path):
    """"Nothing has ever been trashed" and "the walk failed" are different
    answers: only the second is None."""
    summary = lane_guard.trash_summary(str(tmp_path), now=2000.0)
    assert summary["count"] == 0 and summary["bytes"] == 0
    assert summary["oldest"] is None


def test_a_prune_drops_the_cached_summary(tmp_path):
    _trash_batch(tmp_path, "20260701-000000", age_days=30, size=500)
    _trash_batch(tmp_path, "20260817-000000", age_days=1, size=1500)
    assert lane_guard.trash_summary(str(tmp_path), now=3000.0)["count"] == 2
    lane_guard.prune_trash(str(tmp_path), max_age_days=14)
    assert lane_guard.trash_summary(str(tmp_path), now=3001.0)["count"] == 1


# -- SYNC-106: two sentences, one trip --------------------------------------
#
# The trip reason was one string doing two jobs, and as copy it was wrong in
# four places at once: "the NAS root does not look like the tree: none of
# Projects, Assets is under remote_root (saw 0 entries). Check remote_root in
# config.toml." An editor cannot open config.toml (it is under ~/.ccsync, the
# build is frozen) and it is not their job if they could.

def test_the_trip_carries_the_admins_sentence_and_the_editors(tmp_path):
    breaker = _breaker(tmp_path)
    reason = breaker.check_remote("", ["Documents", "Downloads"])
    # The technical half is unchanged: it is what the log, the report and
    # copy_diagnostics carry, and an admin can act on every word of it.
    assert "remote_root" in reason and "config.toml" in reason

    block = breaker.report()
    assert block["cause"] == lane_guard.BREAKER_CAUSE_ROOT
    editor = block["editor_reason"]
    assert editor == (
        "The server does not look like your project tree right now, so CCSync "
        "stopped downloading proxies before anything could be removed. Nothing "
        "was deleted and your uploads are still running. Ask your admin to "
        "check the server.")
    assert "config.toml" not in editor and "remote_root" not in editor


def test_every_reason_ends_on_what_was_not_lost(tmp_path):
    """The EMPTY and SHRANK reasons ended on the alarm. Both facts that stop
    the support call ride every sentence now."""
    tail = ("Nothing was deleted and your uploads are still running. "
            "Ask your admin to check the server.")
    for sentence in lane_guard.BREAKER_EDITOR_REASONS.values():
        assert sentence.endswith(tail), sentence
        assert "—" not in sentence


def test_an_empty_listing_and_a_shrunk_one_have_their_own_words(tmp_path):
    empty = _breaker(tmp_path / "a")
    (tmp_path / "a").mkdir()
    empty.check_remote("Projects/2026/X", ["a", "b", "c", "d"])
    empty.check_remote("Projects/2026/X", [])
    assert empty.report()["cause"] == lane_guard.BREAKER_CAUSE_EMPTY
    assert "listed nothing" in empty.report()["editor_reason"]

    (tmp_path / "b").mkdir()
    shrank = _breaker(tmp_path / "b")
    shrank.check_remote("Projects/2026/X", [f"d{i}" for i in range(10)])
    shrank.check_remote("Projects/2026/X", ["d0", "d1", "d2"])
    assert shrank.report()["cause"] == lane_guard.BREAKER_CAUSE_SHRANK
    assert "Far fewer files" in shrank.report()["editor_reason"]


def test_a_breaker_tripped_by_an_older_build_still_gets_the_sentence():
    """The latch is read from disk on the next start, and a state file
    written before 0.9.69 has a reason and no cause."""
    said = lane_guard.breaker_editor_reason(
        "the NAS root does not look like the tree: none of Projects is under "
        "remote_root (saw 0 entries). Check remote_root in config.toml.")
    assert said == lane_guard.BREAKER_EDITOR_REASONS[lane_guard.BREAKER_CAUSE_ROOT]
    # ...and a reason nothing recognises falls back to itself, never to
    # silence: a trip nobody can name is still a trip the editor is owed.
    assert lane_guard.breaker_editor_reason("something new") == "something new"


def test_the_editor_sentence_clears_with_the_latch(tmp_path):
    breaker = _breaker(tmp_path)
    breaker.check_remote("", ["Documents"])
    assert breaker.report()["editor_reason"]
    breaker.resume(by="tray")
    assert breaker.report()["editor_reason"] is None
    assert breaker.report()["cause"] is None
