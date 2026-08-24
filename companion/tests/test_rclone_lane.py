"""RcloneLane tests: the Popen-based runner's live --stats JSON parsing,
per-project (subpath) run_once behavior, and the legacy subprocess_run seam.

No real rclone binary is needed here — a scripted fake `popen_factory`
stands in for rclone's stderr stream (see test_rclone_filters.py for the
real-rclone integration tests, including the --stats JSON-shape gate test
this module's fake is modeled on).
"""

from __future__ import annotations

import json
import subprocess
import threading
import time
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
    # local_root must EXIST. Since the external-SSD work, _run_once_locked
    # refuses to spawn anything against a local_root that is not a directory
    # -- lane B is `rclone sync` DOWN, and against an absent /Volumes/<SSD>
    # it would create the directory on the boot disk and fill it. A lane
    # pointed at a directory nobody created is a disconnected drive, not a
    # working install (same reasoning as test_app._make_local_root).
    (tmp_path / "local").mkdir(parents=True, exist_ok=True)
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
    # current_project is cleared at the end of a run: leaving it set is what
    # kept the last-synced project wearing "[ SYNCING NOW ]" on the
    # dashboard for the rest of the process's life (AUDIT_2 UX-14).
    assert status.current_project is None
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


# -- S-6: UTF-8 decoding + CREATE_NO_WINDOW + reader-thread crash safety -----


def test_run_popen_passes_utf8_replace_decoding(tmp_path):
    """rclone logs UTF-8; the default cp1252 text=True decoding raises
    UnicodeDecodeError on a non-ASCII filename, which (pre-fix) killed the
    reader thread with no try/except and deadlocked proc.wait() forever."""
    captured: dict = {}

    def factory(cmd, **kwargs):
        captured.update(kwargs)
        return _FakeProc([], 0)

    lane = _make_lane(tmp_path, popen_factory=factory)
    lane._run_popen(["rclone"])

    assert captured["encoding"] == "utf-8"
    assert captured["errors"] == "replace"
    assert "text" not in captured


def test_run_popen_sets_create_no_window_flag_matching_platform(tmp_path):
    import sys

    captured: dict = {}

    def factory(cmd, **kwargs):
        captured.update(kwargs)
        return _FakeProc([], 0)

    lane = _make_lane(tmp_path, popen_factory=factory)
    lane._run_popen(["rclone"])

    if sys.platform == "win32":
        assert captured["creationflags"] == subprocess.CREATE_NO_WINDOW
    else:
        assert captured["creationflags"] == 0


class _FakeProcRaisesMidStream:
    """Simulates a decode/IO error surfacing partway through iterating
    proc.stderr -- the exact shape a UnicodeDecodeError from a rogue byte
    sequence would take even with errors="replace" (e.g. a genuine pipe
    read failure)."""

    def __init__(self, returncode: int = 0) -> None:
        self._returncode = returncode
        self.killed = False

    @property
    def stderr(self):
        def _gen():
            yield '{"level":"info","msg":"rclone starting"}\n'
            raise OSError("simulated pipe read failure")

        return _gen()

    def wait(self) -> int:
        return self._returncode

    def kill(self) -> None:
        self.killed = True


def test_run_popen_reader_crash_kills_proc_instead_of_deadlocking(tmp_path):
    fake_proc = _FakeProcRaisesMidStream()

    def factory(cmd, **kwargs):
        return fake_proc

    lane = _make_lane(tmp_path, popen_factory=factory)
    # Must return promptly (not hang) and must have killed the process so
    # proc.wait() -- which already returned via the fixed returncode here,
    # but in the real deadlock scenario would otherwise never return --
    # cannot stall forever with nobody draining the pipe.
    # (returncode, bounded stderr tail, incremental parse result) since the
    # whole-stream buffer was replaced by a tail + running tally.
    returncode, _text, result = lane._run_popen(["rclone"])

    assert fake_proc.killed is True
    assert returncode == 0
    assert result.transferred == 0


# -- thread-leak fix: sign-out/sign-in must not leak the periodic thread ----


def test_start_is_noop_when_a_live_generation_is_still_running(tmp_path):
    """start() on a lane that is genuinely running (no stop() pending) is
    idempotent per LaneAdapter's contract -- no second thread."""
    lane = _make_lane(tmp_path, popen_factory=_make_popen_factory([], 0, []))
    lane.scan_interval = 60

    lane.start()
    try:
        first = lane._periodic_thread
        first_event = lane._stop_event
        lane.start()
        assert lane._periodic_thread is first
        assert lane._stop_event is first_event
        assert not lane._stop_event.is_set()
    finally:
        lane.stop()


def test_start_after_a_timed_out_stop_starts_a_fresh_generation(tmp_path):
    """AUDIT_2 L-2: stop()'s 5 s join times out routinely (an rclone run
    takes minutes), and the old code then hit start()'s liveness guard and
    returned WITHOUT clearing the latched stop event -- so the winding-down
    thread exited and nothing ever replaced it. The lane was dead for the
    process's life while the tray still showed `idle`."""
    lane = _make_lane(tmp_path, popen_factory=_make_popen_factory([], 0, []))

    class _StubAliveThread:
        def is_alive(self) -> bool:
            return True

    stale = _StubAliveThread()
    stale_event = lane._stop_event
    lane._periodic_thread = stale
    stale_event.set()  # stop() ran; the old thread hasn't observed it yet
    lane.scan_interval = 60

    lane.start()
    try:
        # A NEW thread, on a NEW (cleared) event...
        assert lane._periodic_thread is not stale
        assert lane._periodic_thread.is_alive()
        assert lane._stop_event is not stale_event
        assert not lane._stop_event.is_set()
        # ...and the stale generation's own event is untouched, so that
        # thread still exits rather than being re-armed.
        assert stale_event.is_set()
    finally:
        lane.stop()


def test_slow_run_then_stop_then_start_resumes_syncing(tmp_path):
    """The real L-2 scenario end to end: a slow run makes stop()'s join time
    out, and the immediate start() (Pause->Resume, sign-out->sign-in, self-
    upgrade) must leave a LIVE periodic thread that actually syncs again."""
    started = threading.Event()
    release = threading.Event()
    runs = []

    class _SlowLane(RcloneLane):
        def run_once(self, subpath=None, max_duration_seconds=None):
            runs.append(subpath)
            started.set()
            release.wait(10)
            return self.status()

    lane = _SlowLane(
        direction=DIRECTION_UP,
        local_root=str(tmp_path / "local"),
        remote="nas",
        remote_root="Creators_Club",
        state_dir=tmp_path / "state",
        popen_factory=_make_popen_factory([], 0, []),
    )
    lane.scan_interval = 0.01
    lane._start_watchdog = lambda: None  # no observer needed here

    lane.start()
    assert started.wait(5)
    first = lane._periodic_thread

    # stop() sets the event and then blocks in its bounded join, which the
    # still-running rclone run outlasts -- exactly the state the audit
    # reproduced. Driving stop() from another thread reproduces it without
    # spending the full 5 s join in the test.
    stopper = threading.Thread(target=lane.stop, daemon=True)
    stopper.start()
    time.sleep(0.1)
    assert first.is_alive(), "precondition: the old thread outlives stop()'s join"

    lane.start()
    try:
        second = lane._periodic_thread
        assert second is not first
        assert second.is_alive(), "a stop() whose join timed out must not kill the lane"
        assert not lane._stop_event.is_set()
        # And syncs genuinely resume on the new generation.
        assert len(runs) >= 1
    finally:
        release.set()
        stopper.join(timeout=10)
        lane.stop()


def test_start_spawns_fresh_thread_when_no_thread_alive(tmp_path):
    lane = _make_lane(tmp_path, popen_factory=_make_popen_factory([], 0, []))
    lane.scan_interval = 60  # avoid a second real rclone run firing mid-test

    lane.start()
    try:
        assert lane._periodic_thread is not None
        assert lane._periodic_thread.is_alive()
        assert not lane._stop_event.is_set()
    finally:
        lane.stop()


def test_stop_joins_periodic_thread_with_timeout(tmp_path):
    lane = _make_lane(tmp_path, popen_factory=_make_popen_factory([], 0, []))
    finished = threading.Event()

    def worker():
        time.sleep(0.05)
        finished.set()

    thread = threading.Thread(target=worker, daemon=True)
    lane._periodic_thread = thread
    thread.start()

    lane.stop()

    assert finished.is_set()
    assert not thread.is_alive()


def test_stop_then_start_does_not_leak_the_old_thread(tmp_path):
    """The exact sequence from the audit: sign_out() (stop) followed
    quickly by sign_in() (start) must not end up with two live periodic
    threads, one of them orphaned forever."""
    lane = _make_lane(tmp_path, popen_factory=_make_popen_factory([], 0, []))
    lane.scan_interval = 0.01

    lane.start()
    first_thread = lane._periodic_thread
    lane.stop()
    assert not first_thread.is_alive()

    lane.start()
    try:
        second_thread = lane._periodic_thread
        assert second_thread is not first_thread
        assert second_thread.is_alive()
    finally:
        lane.stop()


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
        assert (
            "creators_club_sftp:/mnt/tank/Creators_Club/Projects/2026/FF5/Alpha" in calls[0]
        )
        assert "--dirs-only" in calls[0]
        # .stversions on the NAS is a deep mirror of every deleted file's
        # directory structure -- pruned at the listing, not just at the
        # mkdir loop (AUDIT_2 DEL-1 / C-3).
        assert ".stversions/**" in calls[0]
        assert ".stfolder/**" in calls[0]

    def test_dot_directories_are_never_recreated(self, tmp_path):
        """AUDIT_2 DEL-1, the top-severity finding in this module.

        `.stfolder` is Syncthing's folder marker. Its ABSENCE is the only
        thing that turns "the local project dir is missing or empty" into a
        stopped folder with an error rather than "the editor deleted 5,000
        files -- propagate that to the NAS and every other editor". If the
        structure clone recreates it (and it did: the loop guarded only
        `..` and absolute paths), moving or renaming a project folder --
        an ordinary thing an editor does -- becomes a mass delete.
        """
        listing = (
            ".stfolder/\n"
            ".stversions/\n"
            ".stversions/Audio/Music/\n"
            ".stignore/\n"
            "Audio/\n"
            "Audio/.hidden_scratch/\n"
            "B-roll/Proxy/\n"
        )
        created, _calls, base = self._run(tmp_path, listing)

        assert not (base / ".stfolder").exists()
        assert not (base / ".stversions").exists()
        assert not (base / ".stignore").exists()
        # A dot segment anywhere in the path disqualifies the whole entry,
        # not just a dot-named leaf.
        assert not (base / "Audio" / ".hidden_scratch").exists()
        # ...and the real project scaffolding is still created.
        assert (base / "Audio").is_dir()
        assert (base / "B-roll" / "Proxy").is_dir()
        # base + Audio + B-roll/Proxy (B-roll itself arrives via parents=True)
        assert created == 3

    def test_backslash_dot_segments_are_skipped_too(self, tmp_path):
        created, _calls, base = self._run(tmp_path, "sub\\.stfolder/\ngood/\n")
        assert not (base / "sub" / ".stfolder").exists()
        assert (base / "good").is_dir()
        assert created == 2  # base + good

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

    def test_projects_component_is_matched_case_insensitively(self, tmp_path):
        """Every other comparison in this function lowercases (and both lanes
        run rclone --ignore-case), but the first component used to be compared
        against the literal "Projects" -- so a mapped `P:\\projects\\...`, or
        an editor whose local_root is spelled in lower case, returned None and
        the clip silently waited for the next full rotation."""
        knowns = ["2026/CCT/Show"]
        assert (
            self._f(tmp_path, Path("projects/2026/CCT/Show/a.mov"), knowns)
            == "Projects/2026/CCT/Show"
        )
        assert (
            self._f(tmp_path, Path("PROJECTS/2026/CCT/Show/a.mov"), knowns)
            == "Projects/2026/CCT/Show"
        )

    def test_legacy_fallback_canonicalizes_the_projects_component(self, tmp_path):
        """The returned rel becomes an rclone subpath on the NAS, which IS
        case sensitive -- so the first component must be the canonical
        "Projects" no matter how it is cased on the local disk."""
        assert (
            self._f(tmp_path, Path("projects/2026/Series/Show/a.mov"), None)
            == "Projects/2026/Series/Show"
        )

    def test_a_rejected_path_says_why_at_debug_level(self, tmp_path, caplog):
        """"No log line" was half the bug: a path the express lane declined to
        attribute left no trace at all to diagnose."""
        with caplog.at_level("DEBUG", logger="ccsync.sync.rclone"):
            assert self._f(tmp_path, Path("Elsewhere/a.mov"), ["2026/CCT/Show"]) is None
            assert self._f(tmp_path, Path("Projects/2026/X/Y/a.mov"), ["2026/CCT/Show"]) is None
        messages = [r.getMessage() for r in caplog.records]
        assert any("not under a 'Projects' directory" in m for m in messages)
        assert any("matches none of the" in m for m in messages)


# ===========================================================================
# AUDIT_3 M-8: stderr is parsed incrementally and only a tail is retained
# ===========================================================================


def test_run_popen_keeps_only_a_bounded_stderr_tail(tmp_path, monkeypatch):
    """rclone --use-json-log --verbose emits a record PER FILE. Buffering the
    whole stream just to re-parse it at the end held hundreds of MB in the
    companion's RSS during a card ingest -- on the editor's machine, while it
    was uploading."""
    from ccsync_companion.sync import rclone_lane as rclone_mod

    monkeypatch.setattr(rclone_mod, "STDERR_TAIL_LINES", 5)
    lines = [
        '{"level":"info","msg":"clip%03d.mov: Copied (new)"}\n' % i for i in range(500)
    ]
    lane = _make_lane(tmp_path, popen_factory=_make_popen_factory(lines, 0, []))

    returncode, tail, result = lane._run_popen(["rclone"])

    assert returncode == 0
    assert tail.count("\n") == 5, "only the tail is retained"
    assert "clip499.mov" in tail and "clip000.mov" not in tail
    # ...and the COUNT is still complete, because it was tallied per line.
    assert result.transferred == 500
    assert result.ok is True


def test_run_popen_tally_counts_errors_and_bounds_the_kept_ones(tmp_path):
    lines = (
        ['{"level":"error","msg":"failure %d"}\n' % i for i in range(250)]
        + ['{"level":"info","msg":"clip.mov: Copied (new)"}\n']
    )
    lane = _make_lane(tmp_path, popen_factory=_make_popen_factory(lines, 1, []))

    _rc, _tail, result = lane._run_popen(["rclone"])

    assert result.error_count == 250
    assert len(result.errors) == 200  # RcloneRunTally.MAX_ERRORS
    assert result.errors[-1] == "failure 249"  # the last one still reaches last_error
    assert result.transferred == 1
    assert result.ok is False


def test_run_once_still_reports_the_last_error_from_the_tail(tmp_path):
    lines = ['{"level":"error","msg":"quota exceeded"}\n']
    lane = _make_lane(tmp_path, popen_factory=_make_popen_factory(lines, 1, []))
    subpath = "Projects/2026/FF5/Alpha"
    (Path(lane.local_root) / subpath).mkdir(parents=True)

    status = lane.run_once(subpath=subpath)

    assert status.state == STATE_ERROR
    assert status.last_error == "quota exceeded"


def test_handle_stderr_line_still_works_without_a_tally(tmp_path):
    """The live --stats side must stay callable on its own."""
    lane = _make_lane(tmp_path)
    lane._handle_stderr_line(TRANSFERRING_STATS_LINES[1])
    assert lane.status().transfers and lane.status().bytes_done == 1000


# ===========================================================================
# AUDIT_3 L-12: lane B says WHERE it moved local files
# ===========================================================================


def test_lane_b_reports_the_trash_dir_when_the_backup_dir_was_used(tmp_path):
    """Lane B is `sync` with --backup-dir, so a proxy the editor generated
    locally and hasn't uploaded is MOVED out of the project folder. Nothing
    said so -- the files just vanished from the folder they were working
    in, and .ccsync-trash is undiscoverable unless you know it exists."""
    notices: list[str] = []
    lines = ['{"level":"info","msg":"old.mov: Deleted"}\n']
    calls: list[list[str]] = []
    # local_root must EXIST -- see _make_lane above (this lane is built
    # inline because it needs an on_trash callback).
    (tmp_path / "local").mkdir(parents=True, exist_ok=True)
    lane = RcloneLane(
        direction=DIRECTION_DOWN,
        local_root=str(tmp_path / "local"),
        remote="nas",
        remote_root="Creators_Club",
        state_dir=tmp_path / "state",
        popen_factory=_make_popen_factory(lines, 0, calls),
        on_trash=notices.append,
    )
    subpath = "Projects/2026/FF5/Alpha"

    # rclone creates the backup dir only when it actually moves something
    # there; stand in for that here.
    real_backup_dir = lane._backup_dir
    made: list[str] = []

    def _spy_backup_dir(sub=None):
        path = real_backup_dir(sub)
        made.append(path)
        target = Path(path) / "Proxy" / "old.mov"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("recovered copy")
        return path

    lane._backup_dir = _spy_backup_dir
    lane.run_once(subpath=subpath)

    assert notices == [made[0]]
    assert ".ccsync-trash" in notices[0]
    assert subpath.replace("/", "\\") in notices[0] or subpath in notices[0]


def test_lane_b_stays_quiet_when_nothing_was_moved(tmp_path):
    notices: list[str] = []
    lane = RcloneLane(
        direction=DIRECTION_DOWN,
        local_root=str(tmp_path / "local"),
        remote="nas",
        remote_root="Creators_Club",
        state_dir=tmp_path / "state",
        popen_factory=_make_popen_factory(STATS_LINES, 0, []),
        on_trash=notices.append,
    )
    lane.run_once(subpath="Projects/2026/FF5/Alpha")
    assert notices == []


def test_lane_a_never_reports_a_trash_dir(tmp_path):
    """Lane A is copy-only: it has no --backup-dir and deletes nothing."""
    notices: list[str] = []
    lane = RcloneLane(
        direction=DIRECTION_UP,
        local_root=str(tmp_path / "local"),
        remote="nas",
        remote_root="Creators_Club",
        state_dir=tmp_path / "state",
        popen_factory=_make_popen_factory(STATS_LINES, 0, []),
        on_trash=notices.append,
    )
    subpath = "Projects/2026/FF5/Alpha"
    (Path(lane.local_root) / subpath).mkdir(parents=True)
    lane.run_once(subpath=subpath)
    assert notices == []


def test_a_raising_on_trash_callback_never_fails_the_run(tmp_path):
    def _boom(path):
        raise RuntimeError("tray is gone")

    lane = RcloneLane(
        direction=DIRECTION_DOWN,
        local_root=str(tmp_path / "local"),
        remote="nas",
        remote_root="Creators_Club",
        state_dir=tmp_path / "state",
        popen_factory=_make_popen_factory([], 0, []),
        on_trash=_boom,
    )
    real_backup_dir = lane._backup_dir

    def _spy_backup_dir(sub=None):
        path = real_backup_dir(sub)
        (Path(path) / "x").mkdir(parents=True, exist_ok=True)
        return path

    lane._backup_dir = _spy_backup_dir
    assert lane.run_once(subpath="Projects/2026/FF5/Alpha").state == STATE_IDLE


def test_trash_toast_is_rate_limited_but_logging_is_not(tmp_path, monkeypatch):
    """One continuing cleanup (spread over runs by --max-delete-size) must
    not toast on every pass -- 30 minutes between toasts, log every time."""
    from ccsync_companion.sync import rclone_lane as rl

    calls = []
    lane = rl.RcloneLane(
        direction=rl.DIRECTION_DOWN, local_root=str(tmp_path), remote="nas",
        remote_root="CC", state_dir=tmp_path, on_trash=lambda d: calls.append(d),
    )
    backup = tmp_path / ".ccsync-trash" / "20260726-1"
    backup.mkdir(parents=True)
    (backup / "x.mov").write_text("x")

    fake_result = rl.RcloneRunResult(ok=True, transferred=0, errors=[],
                                     raw_returncode=0, deleted=1)

    t = {"now": 1000.0}
    monkeypatch.setattr(rl.time, "monotonic", lambda: t["now"])

    lane._last_backup_dir = str(backup)
    lane._notify_trash(fake_result)
    assert len(calls) == 1

    # next run, 60s later: moved again -> logged, NOT toasted
    t["now"] += 60
    lane._last_backup_dir = str(backup)
    lane._notify_trash(fake_result)
    assert len(calls) == 1

    # after the cooldown: toast again
    t["now"] += rl.TRASH_NOTIFY_COOLDOWN_SECONDS + 1
    lane._last_backup_dir = str(backup)
    lane._notify_trash(fake_result)
    assert len(calls) == 2


def test_tally_captures_completed_file_names():
    from ccsync_companion.sync.rclone_lane import RcloneRunTally

    tally = RcloneRunTally()
    tally.feed_record({"level": "info", "msg": "Copied (new)", "object": "B-roll/a.mov"})
    tally.feed_record({"level": "info", "msg": "Deleted", "object": "B-roll/old.mov"})
    tally.feed_record({"level": "error", "msg": "boom"})
    result = tally.result()
    assert result.completed_files == ["B-roll/a.mov"]
    # A delete still counts as a per-file record ("transferred" is rclone's
    # own per-file line count, not a byte claim); the completion list is what
    # the dashboard's history reads, and that must hold arrivals only.
    assert result.transferred == 2 and result.deleted == 1


def test_a_backup_dir_move_is_one_deletion_and_no_completion():
    """comp-lanes-ab-4 (2026-08-21): --backup-dir emits BOTH records for the
    same object, and "Moved (server-side)" used to be read as a finished
    download -- so every trashed proxy was counted twice in `transferred`
    and shown in the dashboard's transfer history as a file that had just
    arrived on the editor's machine."""
    from ccsync_companion.sync.rclone_lane import RcloneRunTally

    tally = RcloneRunTally()
    tally.feed_record({"level": "info", "msg": "Moved (server-side)",
                       "object": "Proxy/a.mov"})
    tally.feed_record({"level": "info", "msg": "Moved into backup dir",
                       "object": "Proxy/a.mov"})
    result = tally.result()
    assert result.completed_files == []
    assert result.deleted == 1
    assert result.transferred == 1


def test_lane_records_and_drains_completions(tmp_path):
    from ccsync_companion.sync import rclone_lane as rl

    lane = rl.RcloneLane(direction=rl.DIRECTION_UP, local_root=str(tmp_path),
                         remote="nas", remote_root="CC", state_dir=tmp_path)
    result = rl.RcloneRunResult(ok=True, transferred=2, errors=[], raw_returncode=0,
                                completed_files=["B-roll/a.mov", "B-roll/b.mov"])
    lane._record_completions(result, "Projects/2026/CCT/X")
    drained = lane.pop_completions()
    assert [d["name"] for d in drained] == [
        "Projects/2026/CCT/X/B-roll/a.mov", "Projects/2026/CCT/X/B-roll/b.mov"]
    assert all(d["direction"] == "up" and d["lane"] == lane.name for d in drained)
    assert lane.pop_completions() == []      # drained means drained


def test_max_delete_abort_is_a_bounded_stop_not_an_error(tmp_path):
    """The --max-delete-size safety valve tripping is the cap WORKING -- an
    oversized cleanup continues next pass. It painted the lane red with the
    useless closing notice for hours (2026-07-26)."""
    lines = [
        '{"level":"info","msg":"a.mov: Copied (new)","object":"a.mov"}\n',
        '{"level":"error","msg":"Delete exceeded --max-delete-size threshold, aborting"}\n',
        '{"level":"error","msg":"Fatal error received - not attempting retries"}\n',
    ]
    calls = []
    lane = _make_lane(tmp_path, direction=DIRECTION_DOWN,
                      popen_factory=_make_popen_factory(lines, returncode=7, calls=calls))
    status = lane.run_once()
    assert status.state == STATE_IDLE
    assert status.last_error is None
    assert "continues next pass" in status.detail


def test_generic_fatal_surfaces_the_cause_not_the_closing_notice(tmp_path):
    lines = [
        '{"level":"error","msg":"sftp: connection lost"}\n',
        '{"level":"error","msg":"Fatal error received - not attempting retries"}\n',
    ]
    calls = []
    lane = _make_lane(tmp_path, direction=DIRECTION_DOWN,
                      popen_factory=_make_popen_factory(lines, returncode=7, calls=calls))
    status = lane.run_once()
    assert status.state == STATE_ERROR
    assert "connection lost" in status.last_error
    assert "not attempting retries" not in status.last_error


# ===========================================================================
# transfers[].project_slug -- the dashboard accepts and persists it
# (api.TransferIn / db.replace_active_transfers) and the companion never sent
# it, so the column was always NULL and a live transfer could only be
# identified by file path.
# ===========================================================================


SUBPATH = "Projects/2026/FF5/Energy Transition"


def _project_with_marker(lane, subpath=SUBPATH, slug="energy-transition"):
    project_dir = Path(lane.local_root) / subpath
    project_dir.mkdir(parents=True, exist_ok=True)
    if slug is not None:
        (project_dir / ".ccsync-project").write_text(
            json.dumps({"slug": slug}), encoding="utf-8"
        )
    return project_dir


class _SnapshottingProc:
    """A fake rclone whose stderr yields lazily, so the test can read the
    lane's LIVE status between lines -- transfers[] is cleared when a run
    finishes, so mid-run is the only place to see it."""

    def __init__(self, lane, lines: list[str], snapshots: list) -> None:
        self._lane = lane
        self._lines = lines
        self._snapshots = snapshots

    @property
    def stderr(self):
        def gen():
            for line in self._lines:
                yield line
                self._snapshots.append(list(self._lane.status().transfers))
        return gen()

    def wait(self) -> int:
        return 0


def _live_transfer_rows(lane, subpath):
    """Run a pass and return the transfer rows as the dashboard would see
    them mid-run."""
    snapshots: list = []
    lane.popen_factory = lambda cmd, **kwargs: _SnapshottingProc(
        lane, TRANSFERRING_STATS_LINES, snapshots
    )
    lane.run_once(subpath=subpath)
    live = [rows for rows in snapshots if rows]
    assert live, "precondition: the fake stream has a live transferring entry"
    return live[0]


def test_transfer_rows_carry_the_project_slug_of_the_running_project(tmp_path):
    """The slug, not the rel path: it is the project's immutable identity and
    survives the rename/move that makes a rel path a bad join key."""
    lane = _make_lane(tmp_path, popen_factory=_make_popen_factory([], 0, []))
    _project_with_marker(lane, slug="energy-transition")

    rows = _live_transfer_rows(lane, SUBPATH)

    assert rows[0]["name"] == "clip.mov"
    assert rows[0]["project_slug"] == "energy-transition"
    # ...and nothing else about the row shape changed.
    assert rows[0]["direction"] == DIRECTION_UP
    assert rows[0]["bytes_total"] == 5000


def test_transfer_rows_omit_the_slug_when_the_marker_has_not_arrived(tmp_path):
    """Lane C delivers the marker; until it does, the field must be ABSENT
    rather than a rel path masquerading as a slug -- the dashboard leaves the
    column NULL, which is exactly the honest answer."""
    lane = _make_lane(tmp_path, popen_factory=_make_popen_factory([], 0, []))
    _project_with_marker(lane, slug=None)  # dir exists, no marker

    rows = _live_transfer_rows(lane, SUBPATH)

    assert "project_slug" not in rows[0]


def test_a_whole_tree_run_sends_no_project_slug(tmp_path):
    lane = _make_lane(tmp_path, popen_factory=_make_popen_factory([], 0, []))
    Path(lane.local_root).mkdir(parents=True, exist_ok=True)

    rows = _live_transfer_rows(lane, None)

    assert "project_slug" not in rows[0]


def test_an_invalid_marker_slug_is_not_forwarded(tmp_path):
    """A marker is a plain JSON file on a share every editor can write, and
    this value becomes a dashboard URL segment / Syncthing folder id."""
    lane = _make_lane(tmp_path, popen_factory=_make_popen_factory([], 0, []))
    _project_with_marker(lane, slug="../../etc")

    rows = _live_transfer_rows(lane, SUBPATH)

    assert "project_slug" not in rows[0]


def test_an_over_long_slug_is_dropped_rather_than_422ing_the_report(tmp_path):
    """TransferIn.project_slug is Field(max_length=128) and pydantic rejects
    the WHOLE body on a violation -- lane status, presence and the upgrade
    advertisement would all be lost with it. Nothing upstream bounds a marker
    slug's length, so the sender does."""
    from ccsync_companion.sync.rclone_lane import MAX_PROJECT_SLUG_CHARS

    lane = _make_lane(tmp_path, popen_factory=_make_popen_factory([], 0, []))
    _project_with_marker(lane, slug="a" * (MAX_PROJECT_SLUG_CHARS + 1))

    rows = _live_transfer_rows(lane, SUBPATH)

    assert "project_slug" not in rows[0]
    # ...and one exactly at the cap still goes.
    lane._project_slug_cache.clear()
    _project_with_marker(lane, slug="b" * MAX_PROJECT_SLUG_CHARS)
    rows = _live_transfer_rows(lane, SUBPATH)
    assert rows[0]["project_slug"] == "b" * MAX_PROJECT_SLUG_CHARS


class TestReadProjectSlug:
    def _dir(self, tmp_path, text=None):
        project = tmp_path / "p"
        project.mkdir(parents=True, exist_ok=True)
        if text is not None:
            (project / ".ccsync-project").write_text(text, encoding="utf-8")
        return project

    def test_reads_the_slug(self, tmp_path):
        from ccsync_companion.sync.rclone_lane import read_project_slug

        assert read_project_slug(self._dir(tmp_path, '{"slug": "creator-pool"}')) == "creator-pool"

    def test_missing_malformed_and_blank_are_all_none(self, tmp_path):
        from ccsync_companion.sync.rclone_lane import read_project_slug

        assert read_project_slug(self._dir(tmp_path)) is None
        assert read_project_slug(self._dir(tmp_path, "not json")) is None
        assert read_project_slug(self._dir(tmp_path, '{"slug": "  "}')) is None
        assert read_project_slug(self._dir(tmp_path, '{}')) is None

    def test_a_slug_that_is_not_an_identity_is_refused(self, tmp_path):
        from ccsync_companion.sync.rclone_lane import read_project_slug

        for bad in ("../../etc", "a/b", "Season 1", "UPPER"):
            assert read_project_slug(self._dir(tmp_path, json.dumps({"slug": bad}))) is None

    def test_a_bom_prefixed_marker_still_parses(self, tmp_path):
        """Markers are hand-editable on an SMB share; Notepad writes a BOM."""
        from ccsync_companion.sync.rclone_lane import read_project_slug

        project = tmp_path / "p"
        project.mkdir()
        (project / ".ccsync-project").write_bytes(
            b"\xef\xbb\xbf" + json.dumps({"slug": "bom-project"}).encode("utf-8")
        )
        assert read_project_slug(project) == "bom-project"


def test_the_slug_lookup_caches_hits_but_retries_misses(tmp_path, monkeypatch):
    """The stats tick is every 2s for the length of a run, so the marker read
    is cached -- but caching a MISS would pin "no slug" for the life of the
    process on a project whose marker is still on its way down lane C."""
    from ccsync_companion.sync import rclone_lane as rclone_mod

    lane = _make_lane(tmp_path, popen_factory=_make_popen_factory([], 0, []))
    reads: list = []
    real = rclone_mod.read_project_slug

    def counting(directory):
        reads.append(str(directory))
        return real(directory)

    monkeypatch.setattr(rclone_mod, "read_project_slug", counting)

    _project_with_marker(lane, slug=None)
    assert lane._project_slug_for_subpath(SUBPATH) is None
    assert lane._project_slug_for_subpath(SUBPATH) is None
    assert len(reads) == 2, "a miss must be retried -- the marker may arrive later"

    _project_with_marker(lane, slug="energy-transition")
    assert lane._project_slug_for_subpath(SUBPATH) == "energy-transition"
    assert lane._project_slug_for_subpath(SUBPATH) == "energy-transition"
    assert len(reads) == 3, "a hit is cached: the slug is immutable"


def test_normalize_transferring_defaults_to_no_slug(tmp_path):
    """The helper stays callable on its own (it is exercised directly by the
    tests above and by any future caller that only wants the row shape)."""
    lane = _make_lane(tmp_path, popen_factory=_make_popen_factory([], 0, []))
    rows = lane._normalize_transferring([{"name": "a.mov", "bytes": 1, "size": 2}])
    assert rows[0]["name"] == "a.mov"
    assert "project_slug" not in rows[0]


# -- the drive has to actually be there (root_guard.py's defence in depth) ---


def test_a_missing_local_root_parks_the_lane_and_spawns_nothing(tmp_path):
    """THE safety line. Lane B is `rclone sync <NAS> <local_root>`: against a
    local_root that is not there -- a macOS editor's external SSD unplugged --
    rclone does not fail, it CREATES the destination and fills the machine's
    internal disk with the project that belongs on the SSD.

    app.py's root guard normally pauses the lanes long before this. This
    check is what holds if that guard's thread ever dies."""
    calls: list[list[str]] = []
    factory = _make_popen_factory(STATS_LINES, returncode=0, calls=calls)
    lane = _make_lane(tmp_path, direction=DIRECTION_DOWN, popen_factory=factory)
    Path(lane.local_root).rmdir()  # the drive goes away

    status = lane.run_once("Projects/2026/FF5/Alpha")

    assert calls == [], "rclone was spawned against a tree that is not mounted"
    assert status.state == STATE_IDLE
    assert status.detail == "local root missing (drive disconnected?)"


def test_the_lane_runs_again_the_moment_the_root_comes_back(tmp_path):
    calls: list[list[str]] = []
    factory = _make_popen_factory(STATS_LINES, returncode=0, calls=calls)
    lane = _make_lane(tmp_path, direction=DIRECTION_DOWN, popen_factory=factory)
    root = Path(lane.local_root)
    root.rmdir()
    lane.run_once()
    assert calls == []

    root.mkdir(parents=True)
    lane.run_once()
    assert len(calls) == 1


# ===========================================================================
# 2026-08-11 hunt: what the run tally counts (SYNC-10 / SYNC-11)
# ===========================================================================


# rclone's periodic --stats record: the msg is the WHOLE run summary, and it
# grows a "Deleted:" line from the first deletion onwards.
_STATS_TICK = {
    "level": "info",
    "msg": ("\nTransferred:   \t  100 MiB / 200 MiB, 50%, 10 MiB/s, ETA 10s\n"
            "Checks:              120 / 120, 100%\n"
            "Deleted:              12 (files), 0 (dirs)\n"
            "Transferred:           5 / 10, 50%\n"
            "Elapsed time:      10m0s\n"),
    "stats": {"bytes": 104857600, "totalBytes": 209715200, "deletes": 12},
}


def test_stats_ticks_are_not_counted_as_transferred_or_deleted_files():
    """SYNC-10: `"Deleted" in msg` is true on EVERY stats tick once anything
    has been deleted, so a lane B pass that trashed 12 proxies over ten
    minutes reported ~300 deletions to the dashboard -- one per tick, each
    also counted as a transfer."""
    from ccsync_companion.sync.rclone_lane import RcloneRunTally

    tally = RcloneRunTally()
    for _ in range(30):
        tally.feed_record(dict(_STATS_TICK))
    tally.feed_record({"level": "info", "msg": "old.mov: Deleted", "object": "old.mov"})

    result = tally.result()
    assert (result.transferred, result.deleted) == (1, 1)
    assert result.completed_files == []


def test_a_backup_dir_move_is_a_deletion_not_a_completion():
    """--backup-dir does not delete, it moves aside -- but from the
    destination's point of view the file is gone, and "Moved" put it in the
    dashboard's transfer HISTORY as if it had just arrived (SYNC-10)."""
    from ccsync_companion.sync.rclone_lane import RcloneRunTally

    tally = RcloneRunTally()
    tally.feed_record({"level": "info", "msg": "Proxy/old.mov: Moved into backup dir",
                       "object": "Proxy/old.mov"})
    tally.feed_record({"level": "info", "msg": "Copied (new)", "object": "Proxy/new.mov"})

    result = tally.result()
    assert result.deleted == 1
    assert result.completed_files == ["Proxy/new.mov"]


def test_critical_records_reach_the_error_list():
    """SYNC-11: only level == "error" was recorded, so the `Failed to create
    file system for ...` shape -- logged at CRITICAL before rclone exits --
    left `errors` empty. _most_informative_error([]) then returned "" and
    _is_max_delete_abort went blind."""
    from ccsync_companion.sync.rclone_lane import (
        RcloneRunTally, _is_max_delete_abort, _most_informative_error,
    )

    tally = RcloneRunTally()
    tally.feed_record({"level": "critical",
                       "msg": "Failed to create file system for \"nas:CC\": "
                              "couldn't connect SSH: dial tcp: i/o timeout"})
    tally.feed_record({"level": "fatal",
                       "msg": "--max-delete threshold reached, aborting"})

    result = tally.result()
    assert result.error_count == 2
    assert result.ok is False
    assert "Failed to create file system" in _most_informative_error(result.errors)
    assert _is_max_delete_abort(result.errors) is True


def test_a_critical_line_survives_the_whole_text_parser_too():
    """parse_json_log is the same rules by another door (the express run and
    the legacy injected-subprocess_run path both use it)."""
    from ccsync_companion.sync.rclone_lane import parse_json_log

    text = (
        '{"level":"info","msg":"rclone starting"}\n'
        '{"level":"critical","msg":"Failed to create file system for \\"nas:CC\\""}\n'
    )
    result = parse_json_log(text)
    assert result.errors and "Failed to create file system" in result.errors[0]


def test_backup_dir_and_breaker_scope_take_a_deep_borrowed_subpath(tmp_path):
    """SHARED_FOLDERS_PLAN.md §3.2: a borrowed dir's lane B run uses a
    subpath deeper than year/series/project (5+ segments). Nothing in the
    lane may assume the old depth: the trash lands under the full subpath
    (so a recovery is unambiguous) and the breaker scope is the sub
    subpath (so a trip in the borrowed dir cannot park the lender's or the
    borrower's own runs)."""
    lane = _make_lane(tmp_path, DIRECTION_DOWN)
    sub = "Projects/2026/FF5/Civil Defence/Interviewees/Aha Chu"
    backup = lane._backup_dir(sub)
    assert backup.replace("\\", "/").endswith(
        "/2026/FF5/Civil Defence/Interviewees/Aha Chu")
    assert ".ccsync-trash" in backup

    # a remote-shrank memory recorded for the deep scope stays keyed to
    # exactly that scope string
    assert lane.breaker.check_remote(sub, ["a.mp4", "b.mp4"]) is None
