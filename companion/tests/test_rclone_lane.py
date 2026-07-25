"""RcloneLane tests: the Popen-based runner's live --stats JSON parsing,
per-project (subpath) run_once behavior, and the legacy subprocess_run seam.

No real rclone binary is needed here — a scripted fake `popen_factory`
stands in for rclone's stderr stream (see test_rclone_filters.py for the
real-rclone integration tests, including the --stats JSON-shape gate test
this module's fake is modeled on).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ccsync_companion.sync.base import STATE_ERROR, STATE_IDLE, STATE_SYNCING
from ccsync_companion.sync.rclone_lane import DIRECTION_DOWN, DIRECTION_UP, RcloneLane


@pytest.fixture(autouse=True)
def _stub_rclone_available(monkeypatch):
    """These tests exercise the Popen/subprocess_run seam and run_once's
    own logic — not rclone_available()'s "is a real binary on PATH" check,
    which would otherwise make every test here depend on rclone being
    installed. See test_rclone_filters.py for the real-rclone tests."""
    monkeypatch.setattr(
        "ccsync_companion.sync.rclone_lane.rclone_available",
        lambda rclone_path: (True, rclone_path),
    )

STATS_LINES = [
    '{"level":"info","msg":"rclone starting"}\n',
    '{"level":"info","msg":"scanning source"}\n',
    '{"level":"notice","msg":"",'
    '"stats":{"bytes":1000,"totalBytes":5000,"speed":500.0,"eta":8,'
    '"transfers":0,"totalTransfers":1,"errors":0,"fatalError":false}}\n',
    '{"level":"notice","msg":"",'
    '"stats":{"bytes":5000,"totalBytes":5000,"speed":600.0,"eta":0,'
    '"transfers":1,"totalTransfers":1,"errors":0,"fatalError":false}}\n',
    '{"level":"info","msg":"clip.mov: Copied (new)"}\n',
]

# A run that has a live "transferring" entry mid-flight (rclone --stats JSON
# includes this array only while at least one file transfer is in flight),
# followed by a stats tick with it gone (file finished) -- see
# _handle_stderr_line / LaneStatus.transfers.
TRANSFERRING_STATS_LINES = [
    '{"level":"info","msg":"rclone starting"}\n',
    '{"level":"notice","msg":"",'
    '"stats":{"bytes":1000,"totalBytes":5000,"speed":500.0,"eta":8,'
    '"transfers":0,"totalTransfers":1,"errors":0,"fatalError":false,'
    '"transferring":[{"name":"clip.mov","bytes":1000,"size":5000,'
    '"percentage":20,"speed":500.0,"eta":8}]}}\n',
    '{"level":"notice","msg":"",'
    '"stats":{"bytes":5000,"totalBytes":5000,"speed":600.0,"eta":0,'
    '"transfers":1,"totalTransfers":1,"errors":0,"fatalError":false}}\n',
    '{"level":"info","msg":"clip.mov: Copied (new)"}\n',
]


class _FakeProc:
    """Scripted stand-in for subprocess.Popen: a stderr line iterator plus
    a .wait() that returns a fixed exit code, per the task brief."""

    def __init__(self, lines: list[str], returncode: int) -> None:
        self.stderr = iter(lines)
        self._returncode = returncode

    def wait(self) -> int:
        return self._returncode


def _make_popen_factory(lines: list[str], returncode: int, calls: list[list[str]]):
    def factory(cmd, **kwargs):
        calls.append(cmd)
        return _FakeProc(lines, returncode)

    return factory


def _make_lane(tmp_path, direction=DIRECTION_UP, popen_factory=None, subprocess_run=None):
    kwargs = dict(
        direction=direction,
        local_root=str(tmp_path / "local"),
        remote="nas",
        remote_root="Creators_Club",
        state_dir=tmp_path / "state",
    )
    if popen_factory is not None:
        kwargs["popen_factory"] = popen_factory
    if subprocess_run is not None:
        kwargs["subprocess_run"] = subprocess_run
    return RcloneLane(**kwargs)


# -- Popen path: live stats + final persisted values -------------------------


def test_run_once_persists_final_bytes_and_clears_speed_eta_after_completion(tmp_path):
    calls: list[list[str]] = []
    factory = _make_popen_factory(STATS_LINES, returncode=0, calls=calls)
    lane = _make_lane(tmp_path, popen_factory=factory)

    subpath = "Projects/2026/FF5/Energy Transition"
    project_dir = Path(lane.local_root) / subpath
    project_dir.mkdir(parents=True)

    status = lane.run_once(subpath=subpath)

    assert len(calls) == 1, "popen_factory should be invoked exactly once"
    assert status.state == STATE_IDLE
    assert status.current_project == subpath
    # Final stats record's values persist after the run completes...
    assert status.bytes_done == 5000
    assert status.bytes_total == 5000
    # ...but speed/eta are cleared since the lane is no longer transferring.
    assert status.speed_bps is None
    assert status.eta_seconds is None
    assert status.transferring == 0
    assert status.detail == "transferred 1 file(s)"
    assert status.last_error is None


def test_handle_stderr_line_populates_transfers_with_direction_up(tmp_path):
    lane = _make_lane(tmp_path, direction=DIRECTION_UP)
    lane._handle_stderr_line(TRANSFERRING_STATS_LINES[1])

    transfers = lane.status().transfers
    assert transfers == [
        {
            "name": "clip.mov",
            "direction": "up",
            "bytes_done": 1000,
            "bytes_total": 5000,
            "percentage": 20,
            "speed_bps": 500.0,
            "eta_seconds": 8,
        }
    ]


def test_handle_stderr_line_populates_transfers_with_direction_down(tmp_path):
    lane = _make_lane(tmp_path, direction=DIRECTION_DOWN)
    lane._handle_stderr_line(TRANSFERRING_STATS_LINES[1])

    transfers = lane.status().transfers
    assert transfers[0]["direction"] == "down"


def test_handle_stderr_line_clears_transfers_when_transferring_absent(tmp_path):
    lane = _make_lane(tmp_path)
    lane._handle_stderr_line(TRANSFERRING_STATS_LINES[1])  # populate
    assert lane.status().transfers  # sanity: populated first

    lane._handle_stderr_line(TRANSFERRING_STATS_LINES[2])  # no "transferring" key
    assert lane.status().transfers == []


def test_run_once_clears_transfers_on_completion(tmp_path):
    calls: list[list[str]] = []
    factory = _make_popen_factory(TRANSFERRING_STATS_LINES, returncode=0, calls=calls)
    lane = _make_lane(tmp_path, popen_factory=factory)

    status = lane.run_once()

    assert len(calls) == 1
    assert status.state == STATE_IDLE
    # A run that had a live per-file transfer mid-flight must not leave
    # stale entries once the run has finished.
    assert status.transfers == []


def test_run_once_popen_failure_sets_error_state_authoritatively(tmp_path):
    calls: list[list[str]] = []
    # Exit code is authoritative even though none of these lines are
    # error-level — mirrors the existing subprocess_run-path contract.
    factory = _make_popen_factory(STATS_LINES, returncode=1, calls=calls)
    lane = _make_lane(tmp_path, popen_factory=factory)

    status = lane.run_once()

    assert len(calls) == 1
    assert status.state == STATE_ERROR
    assert status.last_error
    assert status.transferring == 0


def test_run_once_missing_subpath_dir_skips_without_invoking_popen(tmp_path):
    calls: list[list[str]] = []
    factory = _make_popen_factory(STATS_LINES, returncode=0, calls=calls)
    lane = _make_lane(tmp_path, popen_factory=factory)

    status = lane.run_once(subpath="Projects/2026/FF5/Not There Yet")

    assert calls == [], "rclone must not be spawned when the project dir isn't local yet"
    assert status.state == STATE_IDLE
    assert status.detail == "project dir not yet local: Projects/2026/FF5/Not There Yet"
    assert status.bytes_done is None
    assert status.bytes_total is None


def test_run_once_missing_subpath_dir_only_applies_to_upload_direction(tmp_path):
    # Lane B (down) creates the local dir itself via rclone sync, so a
    # missing local subpath must NOT be special-cased there.
    calls: list[list[str]] = []
    factory = _make_popen_factory(STATS_LINES, returncode=0, calls=calls)
    lane = _make_lane(tmp_path, direction=DIRECTION_DOWN, popen_factory=factory)

    status = lane.run_once(subpath="Projects/2026/FF5/Brand New")

    assert len(calls) == 1
    assert status.state == STATE_IDLE
    assert status.detail != "project dir not yet local: Projects/2026/FF5/Brand New"


def test_run_once_whole_tree_run_leaves_current_project_none(tmp_path):
    calls: list[list[str]] = []
    factory = _make_popen_factory(STATS_LINES, returncode=0, calls=calls)
    lane = _make_lane(tmp_path, popen_factory=factory)

    status = lane.run_once()

    assert len(calls) == 1
    assert status.current_project is None


# -- legacy subprocess_run seam (explicit injection keeps the old path) -----


class _FakeCompletedProcess:
    def __init__(self, returncode: int, stderr: str) -> None:
        self.returncode = returncode
        self.stderr = stderr


def test_run_once_uses_legacy_subprocess_run_when_explicitly_injected(tmp_path):
    calls: list[list[str]] = []
    popen_calls: list[list[str]] = []

    def fake_subprocess_run(cmd, **kwargs):
        calls.append(cmd)
        return _FakeCompletedProcess(0, '{"level":"info","msg":"clip.mov: Copied (new)"}\n')

    popen_factory = _make_popen_factory(STATS_LINES, returncode=0, calls=popen_calls)
    lane = _make_lane(tmp_path, subprocess_run=fake_subprocess_run)
    # A directly-constructed lane with no popen_factory and an explicit
    # subprocess_run must use the legacy path — sanity check the seam
    # picked the right one before asserting behavior.
    assert lane._legacy_run is True

    status = lane.run_once()

    assert len(calls) == 1
    assert popen_calls == []
    assert status.state == STATE_IDLE
    # Legacy path never parses live --stats records.
    assert status.bytes_done is None
    assert status.speed_bps is None
    # Command-shape stays stats-flag-free on the legacy path (keeps the
    # pre-existing build_up_command/build_down_command shape tests green).
    assert "--stats" not in calls[0]


def test_default_construction_prefers_popen_path_over_legacy(tmp_path):
    lane = _make_lane(tmp_path)
    assert lane._legacy_run is False


def test_popen_factory_alone_is_not_legacy_even_with_default_subprocess_run(tmp_path):
    calls: list[list[str]] = []
    factory = _make_popen_factory(STATS_LINES, returncode=0, calls=calls)
    lane = _make_lane(tmp_path, popen_factory=factory)
    assert lane._legacy_run is False
    assert lane.subprocess_run is subprocess.run


# -- clone_directory_tree (empty-dir structure cloning) ----------------------


class TestCloneDirectoryTree:
    def _run(self, tmp_path, listing, **kwargs):
        from ccsync_companion.sync.rclone_lane import clone_directory_tree

        calls = []

        def fake_run(cmd, timeout):
            calls.append(cmd)
            return listing

        result = clone_directory_tree(
            rclone_path="rclone",
            remote=kwargs.pop("remote", "creators_club_sftp"),
            remote_root=kwargs.pop("remote_root", "/mnt/tank/Creators_Club"),
            local_root=str(tmp_path),
            subpath="Projects/2026/FF5/Alpha",
            run_fn=fake_run,
            **kwargs,
        )
        return result, calls, tmp_path / "Projects" / "2026" / "FF5" / "Alpha"

    def test_creates_all_dirs_including_empty_and_nested(self, tmp_path):
        listing = "Footage/\nFootage/Interviews/\nGraphics/\nAudio/SFX/\n"
        created, calls, base = self._run(tmp_path, listing)
        # project root + 4 listed dirs (Audio/ implied via parents=True but
        # only counted once as part of Audio/SFX)
        assert (base / "Footage" / "Interviews").is_dir()
        assert (base / "Graphics").is_dir()
        assert (base / "Audio" / "SFX").is_dir()
        assert created == 5
        # remote side assembled with exactly one slash at the join
        assert calls[0][-1] == "creators_club_sftp:/mnt/tank/Creators_Club/Projects/2026/FF5/Alpha"
        assert "--dirs-only" in calls[0]

    def test_idempotent_second_run_creates_nothing(self, tmp_path):
        listing = "Footage/\n"
        self._run(tmp_path, listing)
        created, _calls, _base = self._run(tmp_path, listing)
        assert created == 0

    def test_listing_failure_returns_none_and_creates_nothing(self, tmp_path):
        from ccsync_companion.sync.rclone_lane import clone_directory_tree

        result = clone_directory_tree(
            rclone_path="rclone", remote="r", remote_root="/root",
            local_root=str(tmp_path), subpath="Projects/X",
            run_fn=lambda cmd, timeout: None,
        )
        assert result is None
        assert not (tmp_path / "Projects").exists()

    def test_run_fn_exception_swallowed(self, tmp_path):
        from ccsync_companion.sync.rclone_lane import clone_directory_tree

        def boom(cmd, timeout):
            raise OSError("rclone missing")

        result = clone_directory_tree(
            rclone_path="rclone", remote="r", remote_root="/root",
            local_root=str(tmp_path), subpath="Projects/X", run_fn=boom,
        )
        assert result is None

    def test_blank_remote_is_a_noop(self, tmp_path):
        from ccsync_companion.sync.rclone_lane import clone_directory_tree

        result = clone_directory_tree(
            rclone_path="rclone", remote="", remote_root="",
            local_root=str(tmp_path), subpath="Projects/X",
            run_fn=lambda cmd, timeout: "Footage/\n",
        )
        assert result is None
        assert not (tmp_path / "Projects").exists()

    def test_parent_relative_entries_are_skipped(self, tmp_path):
        listing = "../escape/\ngood/\n"
        created, _calls, base = self._run(tmp_path, listing)
        assert (base / "good").is_dir()
        assert not (tmp_path / "escape").exists()
        assert not (base.parent / "escape").exists()


# -- _project_rel_for_path (any-depth attribution) ---------------------------


class TestProjectRelForPath:
    def _f(self, tmp_path, sub, knowns=None):
        from ccsync_companion.sync.rclone_lane import _project_rel_for_path

        return _project_rel_for_path(str(tmp_path), str(tmp_path / sub), knowns)

    def test_longest_known_prefix_wins(self, tmp_path):
        knowns = ["2026/CCT", "2026/CCT/Creator Profiles/Season 1"]
        rel = self._f(tmp_path, Path("Projects/2026/CCT/Creator Profiles/Season 1/B-roll/a.mov"),
                      knowns)
        assert rel == "Projects/2026/CCT/Creator Profiles/Season 1"

    def test_no_known_match_returns_none(self, tmp_path):
        rel = self._f(tmp_path, Path("Projects/2026/Other/Show/a.mov"), ["2025/FF4/Nuclear"])
        assert rel is None

    def test_legacy_fallback_without_knowns(self, tmp_path):
        rel = self._f(tmp_path, Path("Projects/2026/Series/Show/a.mov"), None)
        assert rel == "Projects/2026/Series/Show"
        assert self._f(tmp_path, Path("Projects/2026/a.mov"), None) is None

    def test_file_directly_in_project_dir(self, tmp_path):
        rel = self._f(tmp_path, Path("Projects/2026/CCT/Show/a.mov"), ["2026/CCT/Show"])
        assert rel == "Projects/2026/CCT/Show"

    def test_outside_projects_tree(self, tmp_path):
        assert self._f(tmp_path, Path("Elsewhere/a.mov"), ["2026/CCT/Show"]) is None
