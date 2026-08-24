"""Express lane A (AUDIT_2 C-2 / P9): the watchdog-triggered, short-lived
`rclone copy --files-from-raw` that uploads the exact clip an editor just
dropped in, instead of waiting for the sequencer's rotation to reach that
project.

The safety-critical properties proven here, all of which the audit calls out
by name:

  * the express argv is `copy` + `--ignore-existing` -- never `sync`, never
    `move`, so no speed change widens a deletion window;
  * `--no-traverse` is paired with `--no-update-dir-modtime` and appears ONLY
    on express runs (unpaired on a full pass it is a measured pessimisation);
  * express takes its OWN lock, so it cannot queue behind an in-flight 40 GB
    periodic upload -- which is the entire point of the feature;
  * events are coalesced into one list file per window, the batch is capped,
    the list file is written atomically with a unique name, and a non-ASCII
    filename survives the round trip.

No real rclone binary is needed -- see test_rclone_filters.py for the
integration tests that run the express argv against the bundled 1.74.4.
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import pytest

from ccsync_companion.sync.rclone_lane import (
    EXPRESS_DEFAULT_MAX_BATCH,
    EXPRESS_PARTIAL_SUFFIX,
    LANE_A_MIN_AGE_SECONDS,
    PARTIAL_SUFFIX,
    ExpressListError,
    DIRECTION_DOWN,
    DIRECTION_UP,
    RcloneLane,
    build_express_command,
    build_filter_rules_down,
    build_filter_rules_up,
    build_up_command,
    build_down_command,
    path_matches_lane_a_filter,
    write_files_from_list,
)

NON_ASCII_NAME = "caf\u00e9 \u65e5\u672c\u8a9e.braw"


@pytest.fixture(autouse=True)
def _stub_rclone_available(monkeypatch):
    monkeypatch.setattr(
        "ccsync_companion.sync.rclone_lane.rclone_available",
        lambda rclone_path, *a, **kw: (True, rclone_path),
    )


class _FakeExpressProc:
    """Stand-in for the express rclone child: a single stderr stream read to
    EOF, plus a fixed exit code."""

    def __init__(self, stderr_text: str, returncode: int = 0) -> None:
        self.stderr = _FakeStderr(stderr_text)
        self._returncode = returncode
        self.terminated = False

    def wait(self, timeout=None) -> int:
        return self._returncode

    def poll(self):
        return None

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.terminated = True


class _FakeStderr:
    def __init__(self, text: str) -> None:
        self._text = text

    def read(self) -> str:
        return self._text


DEFAULT_STDERR = '{"level":"info","msg":"clip.mov: Copied (new)"}\n'


def _recording_popen(calls: list, stderr_text: str = DEFAULT_STDERR, returncode: int = 0,
                     lists: list | None = None, hold: threading.Event | None = None):
    def factory(cmd, **kwargs):
        calls.append(list(cmd))
        if lists is not None and "--files-from-raw" in cmd:
            list_path = Path(cmd[cmd.index("--files-from-raw") + 1])
            # Snapshot the list file WHILE rclone would be reading it: after
            # the run it is deleted.
            lists.append(list_path.read_text(encoding="utf-8"))
        if hold is not None:
            hold.wait(5)
        return _FakeExpressProc(stderr_text, returncode)

    return factory


def _make_lane(tmp_path, cfg=None, popen_factory=None, direction=DIRECTION_UP, debounce=0.05):
    # local_root must EXIST: the lane (periodic AND express) refuses to run
    # against a local_root that is not a directory -- see test_rclone_lane's
    # _make_lane for why that gate is there.
    (tmp_path / "local").mkdir(parents=True, exist_ok=True)
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
    """A file that is already past --min-age and size-stable."""
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    old = time.time() - (LANE_A_MIN_AGE_SECONDS + 60)
    os.utime(path, (old, old))
    return path


def _flush_now(lane: RcloneLane) -> None:
    """Run the debounce window's work synchronously (no timer sleep)."""
    timer = lane._express_timer
    if timer is not None:
        timer.cancel()
        lane._express_timer = None
    lane._express_flush()


# -- argv shape --------------------------------------------------------------


def test_express_argv_is_upload_only_copy_with_the_paired_traverse_flags(tmp_path):
    cmd = build_express_command(
        "rclone", str(tmp_path / "local"), "nas", "Creators_Club", tmp_path / "list.txt"
    )
    assert cmd[1] == "copy", "express must never be `sync` or `move` -- it may not delete"
    assert "sync" not in cmd and "move" not in cmd and "delete" not in cmd
    assert "--ignore-existing" in cmd, "express must never overwrite an existing NAS file"
    assert "--files-from-raw" in cmd
    assert cmd[cmd.index("--files-from-raw") + 1] == str(tmp_path / "list.txt")
    # --no-traverse is ONLY ever valid paired with --no-update-dir-modtime.
    assert "--no-traverse" in cmd
    assert "--no-update-dir-modtime" in cmd
    # No delete-capable or destructive flag may appear.
    for flag in ("--delete-before", "--delete-during", "--delete-after", "--delete-excluded"):
        assert flag not in cmd


def test_express_gets_its_own_partial_suffix(tmp_path):
    """Express is the only place two rclones touch one tree at once, and
    rclone's partial token is derived from the file rather than random per
    run (measured: `clip1.mov.42048420.partial` from two separate runs). A
    distinct suffix is what keeps a simultaneous express + periodic upload of
    the same new file from interleaving into one temp path."""
    cmd = build_express_command(
        "rclone", "C:\\root", "nas", "Creators_Club", tmp_path / "l.txt"
    )
    suffix = cmd[cmd.index("--partial-suffix") + 1]
    assert suffix == EXPRESS_PARTIAL_SUFFIX
    assert suffix != PARTIAL_SUFFIX
    assert len(suffix) <= 16, "rclone rejects a partial suffix longer than 16 chars"
    assert suffix.endswith(PARTIAL_SUFFIX), "orphan .partial reporting must still find it"


def test_express_argv_carries_no_filter_flags_because_rclone_refuses_them(tmp_path):
    """Measured against the bundled rclone 1.74.4:

        CRITICAL: Failed to initialise global options: failed to reload
        "filter" options: the usage of --files-from-raw overrides all other
        filters, it should be used alone or with --files-from

    for BOTH --min-age and --filter-from. So the express argv must carry
    neither -- both gates move into Python (path_matches_lane_a_filter and
    RcloneLane._express_partition). A regression here would make every
    express run die at startup.
    """
    cmd = build_express_command(
        "rclone", str(tmp_path / "local"), "nas", "Creators_Club", tmp_path / "list.txt"
    )
    assert "--min-age" not in cmd
    assert "--filter-from" not in cmd
    assert "--filter" not in cmd
    assert "--include" not in cmd
    assert "--exclude" not in cmd


def test_express_argv_maps_local_root_onto_remote_root(tmp_path):
    cmd = build_express_command(
        "rclone", "C:\\Creators_Club", "nas", "Creators_Club", tmp_path / "l.txt"
    )
    assert cmd[2] == "C:\\Creators_Club"
    assert cmd[3] == "nas:Creators_Club"


def test_express_argv_keeps_the_transport_tuning_of_the_normal_lane_a(tmp_path):
    cmd = build_express_command(
        "rclone", "C:\\root", "nas", "Creators_Club", tmp_path / "l.txt", transfers=7
    )
    assert cmd[cmd.index("--transfers") + 1] == "7"
    assert "--sftp-chunk-size" in cmd
    assert "--use-json-log" in cmd


def test_the_full_pass_still_has_no_no_traverse(tmp_path):
    """AUDIT_2 P10, measured: --no-traverse on a FULL pass touched all 61
    destination dir modtimes vs 2 with traverse. It is a pessimisation
    there and must stay express-only."""
    filter_file = tmp_path / "f.txt"
    filter_file.write_text("- **\n")
    for build in (build_up_command, build_down_command):
        cmd = build("rclone", "C:\\root", "nas", "Creators_Club", filter_file)
        assert "--no-traverse" not in cmd
        assert "--no-update-dir-modtime" not in cmd
        assert "--files-from-raw" not in cmd
    # ...and the full lane A pass keeps the --min-age gate it CAN use.
    up = build_up_command("rclone", "C:\\root", "nas", "Creators_Club", filter_file)
    assert up[up.index("--min-age") + 1] == f"{LANE_A_MIN_AGE_SECONDS}s"


# -- locking -----------------------------------------------------------------


def test_express_uses_a_different_lock_than_the_periodic_run(tmp_path):
    lane = _make_lane(tmp_path)
    assert lane._express_run_lock is not lane._run_lock


def test_express_runs_while_the_periodic_run_lock_is_held(tmp_path):
    """C-2's stated risk: reusing _run_lock serializes the express upload
    behind an in-flight 40 GB periodic upload, defeating the feature."""
    calls: list = []
    lane = _make_lane(tmp_path, popen_factory=_recording_popen(calls))
    local = Path(lane.local_root)
    _old_file(local, "Projects/2026/FF5/Alpha/clip.mov")

    lane._run_lock.acquire()  # pretend a 40 GB periodic upload is in flight
    try:
        lane.notify_path_changed(str(local / "Projects/2026/FF5/Alpha/clip.mov"))
        _flush_now(lane)
    finally:
        lane._run_lock.release()

    assert len(calls) == 1, "express must not wait on the periodic lane lock"
    assert "--files-from-raw" in calls[0]


def test_a_second_express_flush_does_not_stack_a_second_rclone(tmp_path):
    calls: list = []
    lane = _make_lane(tmp_path, popen_factory=_recording_popen(calls))
    local = Path(lane.local_root)
    _old_file(local, "Projects/2026/FF5/Alpha/clip.mov")
    lane.notify_path_changed(str(local / "Projects/2026/FF5/Alpha/clip.mov"))

    lane._express_run_lock.acquire()  # an express run is already uploading
    try:
        _flush_now(lane)
    finally:
        lane._express_run_lock.release()

    pending = dict(lane._express_pending)
    # This flush RE-ARMS the debounce timer (that is the "kept for the next
    # window" behaviour being asserted below), so the lane must be stopped
    # here: an unstopped one fires ~50 ms later, inside whatever test is
    # running by then, and writes an express list file + spawns a fake rclone
    # under ANOTHER test's tmp_path. That leak made
    # test_list_file_is_written_atomically_via_os_replace fail at random
    # under pytest-randomly's shuffling.
    lane.stop()

    assert calls == [], "a second express rclone must not stack on the first"
    # ...and the path is kept for the next window rather than dropped.
    assert pending


# -- batching / coalescing ---------------------------------------------------


def test_thousands_of_events_coalesce_into_one_list_and_one_rclone(tmp_path):
    """The watchdog fires per write chunk -- the audit measured thousands of
    on_modified events a minute during a card ingest."""
    calls: list = []
    lists: list = []
    lane = _make_lane(tmp_path, popen_factory=_recording_popen(calls, lists=lists))
    local = Path(lane.local_root)
    paths = [_old_file(local, f"Projects/2026/FF5/Alpha/clip{i}.mov") for i in range(3)]

    for _ in range(500):
        for p in paths:
            lane.notify_path_changed(str(p))
    _flush_now(lane)

    assert len(calls) == 1, "one window -> one rclone"
    assert len(lists) == 1
    entries = [line for line in lists[0].splitlines() if line]
    assert sorted(entries) == sorted(
        f"Projects/2026/FF5/Alpha/clip{i}.mov" for i in range(3)
    )


def test_batch_over_the_cap_is_left_to_the_periodic_pass(tmp_path):
    calls: list = []
    lists: list = []
    lane = _make_lane(
        tmp_path, cfg={"express_max_batch": 5}, popen_factory=_recording_popen(calls, lists=lists)
    )
    local = Path(lane.local_root)
    for i in range(12):
        p = _old_file(local, f"Projects/2026/FF5/Alpha/clip{i}.mov")
        lane.notify_path_changed(str(p))
    _flush_now(lane)

    entries = [line for line in lists[0].splitlines() if line]
    assert len(entries) == 5
    assert lane.express_report()["dropped_over_cap"] == 7


def test_default_batch_cap_is_bounded(tmp_path):
    lane = _make_lane(tmp_path)
    assert lane._express_max_batch == EXPRESS_DEFAULT_MAX_BATCH
    assert 0 < EXPRESS_DEFAULT_MAX_BATCH <= 1000


def test_debounce_window_comes_from_watch_debounce_seconds(tmp_path):
    """P9: watch_debounce_seconds was a dead knob in managed mode; it now
    drives the express window."""
    lane = _make_lane(tmp_path, debounce=7.5)
    assert lane._express_debounce == pytest.approx(7.5)
    # ...and an explicit express_debounce_seconds still wins.
    lane2 = _make_lane(tmp_path, cfg={"express_debounce_seconds": 2}, debounce=7.5)
    assert lane2._express_debounce == pytest.approx(2.0)


def test_managed_mode_says_the_scan_interval_knobs_are_dead(tmp_path, caplog):
    """P9's other half: scan_interval_up/scan_interval_down start no loop in
    managed mode. They are wired to nothing, so the lane says so out loud
    rather than leaving two knobs that silently do nothing."""
    pytest.importorskip("watchdog")
    lane = _make_lane(tmp_path)
    with caplog.at_level("WARNING", logger="ccsync.sync.rclone"):
        lane.start_watchdog_only()
    lane.stop()
    messages = [r.getMessage() for r in caplog.records]
    assert any("scan_interval_up/scan_interval_down are IGNORED" in m for m in messages)
    assert any("watch_debounce_seconds" in m for m in messages)


def test_a_junk_debounce_value_falls_back_instead_of_crashing_the_lane(tmp_path):
    lane = _make_lane(tmp_path, cfg={"express_debounce_seconds": "soon"}, debounce=9)
    assert lane._express_debounce == pytest.approx(9.0)


def test_notify_arms_a_timer_so_a_real_watchdog_event_fires_on_its_own(tmp_path):
    calls: list = []
    lane = _make_lane(tmp_path, popen_factory=_recording_popen(calls), debounce=0.05)
    local = Path(lane.local_root)
    p = _old_file(local, "Projects/2026/FF5/Alpha/clip.mov")
    lane.notify_path_changed(str(p))
    assert lane._express_timer is not None
    deadline = time.time() + 5
    while time.time() < deadline and not calls:
        time.sleep(0.02)
    assert len(calls) == 1
    lane.stop()


# -- the stability gate (--min-age can't be passed, so it lives in Python) ---


def test_a_file_still_being_written_is_never_uploaded(tmp_path):
    calls: list = []
    lane = _make_lane(tmp_path, popen_factory=_recording_popen(calls))
    local = Path(lane.local_root)
    p = _old_file(local, "Projects/2026/FF5/Alpha/growing.mov", b"a" * 10)

    lane.notify_path_changed(str(p))
    # The ingest keeps writing after the event was recorded.
    p.write_bytes(b"a" * 5000)
    old = time.time() - (LANE_A_MIN_AGE_SECONDS + 60)
    os.utime(p, (old, old))  # mtime-preserving ingest: --min-age alone is blind (L-14)
    _flush_now(lane)

    assert calls == [], "a growing file must not be uploaded truncated"
    assert "Projects/2026/FF5/Alpha/growing.mov" in lane._express_pending

    # Second consecutive size-stable observation -> now it goes.
    _flush_now(lane)
    assert len(calls) == 1


def test_a_file_younger_than_min_age_is_deferred_not_uploaded(tmp_path):
    calls: list = []
    lane = _make_lane(tmp_path, popen_factory=_recording_popen(calls))
    local = Path(lane.local_root)
    p = local / "Projects/2026/FF5/Alpha/fresh.mov"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"f" * 64)  # mtime = now

    lane.notify_path_changed(str(p))
    _flush_now(lane)
    assert calls == []
    assert "Projects/2026/FF5/Alpha/fresh.mov" in lane._express_pending

    old = time.time() - (LANE_A_MIN_AGE_SECONDS + 60)
    os.utime(p, (old, old))
    _flush_now(lane)
    assert len(calls) == 1


def test_a_0_byte_file_is_never_uploaded(tmp_path):
    """COMP-GUARD-1 (2026-08-14): the express twin of lane A's --min-size
    floor. rclone refuses --min-size next to --files-from-raw (same CRITICAL
    as --min-age), and express is `copy --ignore-existing` too -- so an empty
    upload would be the NAS's permanent copy of that clip. A hard kill in the
    middle of the fixer's copy strands exactly such a file, under its real
    name, and the watchdog fires on it."""
    calls: list = []
    lane = _make_lane(tmp_path, popen_factory=_recording_popen(calls))
    local = Path(lane.local_root)
    p = _old_file(local, "Projects/2026/FF5/Alpha/stranded.mov", b"")
    assert p.stat().st_size == 0

    lane.notify_path_changed(str(p))
    _flush_now(lane)
    _flush_now(lane)  # a second size-stable observation would satisfy L-14

    assert calls == [], "an empty file must never travel a copy --ignore-existing lane"
    # Deferred, not dropped: a file that was only just created is 0 bytes for
    # an instant, and the next window sees the real ones.
    assert "Projects/2026/FF5/Alpha/stranded.mov" in lane._express_pending

    p.write_bytes(b"x" * 64)
    old = time.time() - (LANE_A_MIN_AGE_SECONDS + 60)
    os.utime(p, (old, old))
    _flush_now(lane)   # first non-zero observation: size changed -> defer
    _flush_now(lane)   # stable at 64 bytes -> away it goes
    assert len(calls) == 1


def test_a_path_deleted_before_the_window_closes_is_dropped_silently(tmp_path):
    calls: list = []
    lane = _make_lane(tmp_path, popen_factory=_recording_popen(calls))
    local = Path(lane.local_root)
    p = _old_file(local, "Projects/2026/FF5/Alpha/gone.mov")
    lane.notify_path_changed(str(p))
    p.unlink()
    _flush_now(lane)
    assert calls == []
    assert lane._express_pending == {}


def test_a_pending_path_is_handed_back_to_the_periodic_pass_eventually(tmp_path, monkeypatch):
    calls: list = []
    lane = _make_lane(tmp_path, popen_factory=_recording_popen(calls))
    local = Path(lane.local_root)
    p = local / "Projects/2026/FF5/Alpha/forever.mov"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"f" * 64)
    lane.notify_path_changed(str(p))
    monkeypatch.setattr("ccsync_companion.sync.rclone_lane.EXPRESS_PENDING_MAX_SECONDS", -1.0)
    _flush_now(lane)
    assert calls == []
    assert lane._express_pending == {}


# -- what may enter the list at all -----------------------------------------


def test_non_video_proxy_and_outside_root_paths_never_enter_the_batch(tmp_path):
    lane = _make_lane(tmp_path)
    local = Path(lane.local_root)
    for rel in (
        "Projects/2026/FF5/Alpha/notes.txt",
        "Projects/2026/FF5/Alpha/Proxy/clip.mov",
        "Projects/2026/FF5/Alpha/sub/proxy/clip.mov",
    ):
        lane.notify_path_changed(str(_old_file(local, rel)))
    outside = _old_file(tmp_path / "elsewhere", "clip.mov")
    lane.notify_path_changed(str(outside))
    assert lane._express_pending == {}


def test_path_filter_predicate_matches_the_lane_a_rule_list():
    assert path_matches_lane_a_filter("Projects/A/clip.mov")
    assert path_matches_lane_a_filter("Projects/A/CLIP.MOV")  # --ignore-case parity
    assert path_matches_lane_a_filter("Projects/A/" + NON_ASCII_NAME)
    assert not path_matches_lane_a_filter("Projects/A/notes.txt")
    assert not path_matches_lane_a_filter("Projects/A/Proxy/clip.mov")
    assert not path_matches_lane_a_filter("Projects/A/proxy/clip.mov")
    assert not path_matches_lane_a_filter("Projects\\A\\Proxy\\clip.mov")
    assert not path_matches_lane_a_filter("")
    # A name that merely resembles Proxy is still a real original.
    assert path_matches_lane_a_filter("Projects/Proxynotreal.mov")


def test_path_filter_predicate_refuses_macos_appledouble_sidecars():
    """Express is lane A's OTHER door, and this predicate is the whole filter
    on it (build_express_command can pass no --filter-from at all). A `._`
    sidecar has a video extension and no Proxy component, so without an
    explicit check a Mac's watchdog event uploads the exact file the periodic
    pass now refuses -- KNOWN_BUGS 12, which is about both, not just the
    rule list."""
    assert not path_matches_lane_a_filter("Projects/A/._clip.mov")
    assert not path_matches_lane_a_filter("Projects\\A\\._clip.mov")
    assert not path_matches_lane_a_filter("._clip.mov")
    # Only the BASENAME decides -- a directory that happens to start with `._`
    # is somebody's real folder, and the file inside it is a real original.
    assert path_matches_lane_a_filter("Projects/._weird_dir/clip.mov")
    # ...and a leading dot alone is not an AppleDouble sidecar.
    assert path_matches_lane_a_filter("Projects/A/.hidden.mov")


def test_express_is_lane_a_only(tmp_path):
    lane_b = _make_lane(tmp_path, direction=DIRECTION_DOWN)
    assert lane_b._express_enabled is False
    local = Path(lane_b.local_root)
    lane_b.notify_path_changed(str(_old_file(local, "Projects/2026/FF5/Alpha/clip.mov")))
    assert lane_b._express_pending == {}


def test_express_does_nothing_without_a_configured_remote(tmp_path):
    calls: list = []
    lane = RcloneLane(
        direction=DIRECTION_UP,
        local_root=str(tmp_path / "local"),
        remote="",
        remote_root="",
        state_dir=tmp_path / "state",
        watch_debounce_seconds=0.05,
        popen_factory=_recording_popen(calls),
    )
    local = Path(lane.local_root)
    lane.notify_path_changed(str(_old_file(local, "Projects/2026/FF5/Alpha/clip.mov")))
    _flush_now(lane)
    assert calls == []


def test_express_can_be_disabled_from_config(tmp_path):
    lane = _make_lane(tmp_path, cfg={"express_upload_enabled": False})
    assert lane._express_enabled is False
    local = Path(lane.local_root)
    lane.notify_path_changed(str(_old_file(local, "Projects/2026/FF5/Alpha/clip.mov")))
    assert lane._express_pending == {}


# -- the list file ----------------------------------------------------------


def test_list_file_is_written_atomically_via_os_replace(tmp_path, monkeypatch):
    """DEL-2's lesson: a truncated filter/list file read by rclone is exactly
    how the audit's worst finding happened. The target must only ever appear
    complete."""
    seen: list = []
    real_replace = os.replace

    def spy(src, dst):
        # Before the swap the destination must not exist half-written.
        assert not Path(dst).exists()
        seen.append((str(src), str(dst)))
        real_replace(src, dst)

    monkeypatch.setattr("ccsync_companion.sync.rclone_lane.os.replace", spy)
    target = tmp_path / "state" / "express.txt"
    write_files_from_list(["Projects/a/clip.mov"], target)
    assert len(seen) == 1
    assert seen[0][0] != str(target)  # written to a tmp name first
    assert target.read_text(encoding="utf-8") == "Projects/a/clip.mov\n"
    assert list(target.parent.glob("*.tmp")) == []


def test_list_file_write_failure_leaves_no_temp_behind(tmp_path, monkeypatch):
    def boom(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr("ccsync_companion.sync.rclone_lane.os.replace", boom)
    target = tmp_path / "state" / "express.txt"
    with pytest.raises(OSError):
        write_files_from_list(["Projects/a/clip.mov"], target)
    assert list(target.parent.glob("*.tmp")) == []
    assert not target.exists()


def test_non_ascii_path_survives_the_list_round_trip(tmp_path):
    """The audit's worst finding was a non-ASCII decode bug. rclone reads
    --files-from-raw as raw UTF-8 bytes, so the list has to be written as
    UTF-8 and must come back byte-identical."""
    rel = f"Projects/2026/FF5/Alpha/{NON_ASCII_NAME}"
    target = tmp_path / "state" / "express.txt"
    write_files_from_list([rel], target)
    assert target.read_bytes() == (rel + "\n").encode("utf-8")
    assert target.read_text(encoding="utf-8").splitlines() == [rel]


def test_non_ascii_path_survives_enqueue_to_list_file(tmp_path):
    calls: list = []
    lists: list = []
    lane = _make_lane(tmp_path, popen_factory=_recording_popen(calls, lists=lists))
    local = Path(lane.local_root)
    p = _old_file(local, f"Projects/2026/FF5/Alpha/{NON_ASCII_NAME}")
    lane.notify_path_changed(str(p))
    _flush_now(lane)
    assert lists[0].splitlines() == [f"Projects/2026/FF5/Alpha/{NON_ASCII_NAME}"]


def test_list_file_never_contains_a_blank_line(tmp_path):
    """Measured: a blank line in a --files-from-raw list is read as the ROOT
    directory -- rclone fails the run with "Failed to copy: is a directory
    not a file" (exit 1)."""
    target = tmp_path / "state" / "express.txt"
    write_files_from_list(["Projects/a/clip.mov", "Projects/b/clip.mov"], target)
    text = target.read_text(encoding="utf-8")
    assert text.endswith("\n") and not text.endswith("\n\n")
    assert "" not in text.split("\n")[:-1]
    with pytest.raises(ExpressListError):
        write_files_from_list([], target)
    with pytest.raises(ExpressListError):
        write_files_from_list(["  "], target)


def test_list_entries_are_posix_because_backslashes_silently_match_nothing(tmp_path):
    """Measured: a backslash-separated entry transfers 0 bytes and still
    exits 0 -- a silent no-op, the worst possible failure mode."""
    target = tmp_path / "state" / "express.txt"
    write_files_from_list(["Projects\\2026\\FF5\\Alpha\\clip.mov"], target)
    assert target.read_text(encoding="utf-8") == "Projects/2026/FF5/Alpha/clip.mov\n"


def test_list_entries_may_not_escape_the_local_root(tmp_path):
    target = tmp_path / "state" / "express.txt"
    for bad in ("../outside.mov", "Projects/../../outside.mov", "C:/Windows/x.mov"):
        with pytest.raises(ExpressListError):
            write_files_from_list([bad], target)


def test_each_express_run_gets_a_unique_list_file_name(tmp_path):
    names: list = []

    def factory(cmd, **kwargs):
        names.append(cmd[cmd.index("--files-from-raw") + 1])
        return _FakeExpressProc(DEFAULT_STDERR)

    lane = _make_lane(tmp_path, popen_factory=factory)
    local = Path(lane.local_root)
    for i in range(3):
        p = _old_file(local, f"Projects/2026/FF5/Alpha/clip{i}.mov")
        lane.notify_path_changed(str(p))
        _flush_now(lane)
    assert len(names) == 3
    assert len(set(names)) == 3, "two express runs must never share a list file"


def test_list_file_is_removed_after_the_run(tmp_path):
    calls: list = []
    lane = _make_lane(tmp_path, popen_factory=_recording_popen(calls))
    local = Path(lane.local_root)
    lane.notify_path_changed(str(_old_file(local, "Projects/2026/FF5/Alpha/clip.mov")))
    _flush_now(lane)
    leftovers = list((tmp_path / "state").glob("express_*"))
    assert leftovers == []


# -- run bookkeeping / failure isolation ------------------------------------


def test_start_sweeps_only_old_express_lists_and_nothing_else(tmp_path):
    """Debris from a hard kill, cleaned up -- but a fresh list (another live
    companion's rclone may be reading it) and anything that is not our own
    scratch artifact must be left strictly alone."""
    pytest.importorskip("watchdog")
    state = tmp_path / "state"
    state.mkdir(parents=True)
    stale = state / "express_999_1_deadbeef.txt"
    fresh = state / "express_999_2_cafebabe.txt"
    other = state / "filter_up.txt"
    for path in (stale, fresh, other):
        path.write_text("Projects/a/clip.mov\n", encoding="utf-8")
    old = time.time() - (86400 * 3)
    os.utime(stale, (old, old))

    lane = _make_lane(tmp_path)
    lane.start_watchdog_only()
    lane.stop()

    assert not stale.exists()
    assert fresh.exists()
    assert other.exists()


def test_express_success_is_recorded_without_touching_lane_state(tmp_path):
    lane = _make_lane(tmp_path, popen_factory=_recording_popen([]))
    local = Path(lane.local_root)
    before = lane.status().state
    lane.notify_path_changed(str(_old_file(local, "Projects/2026/FF5/Alpha/clip.mov")))
    _flush_now(lane)
    report = lane.express_report()
    assert report["runs"] == 1
    assert report["files_uploaded"] == 1
    assert report["last_error"] is None
    assert lane.status().state == before


def test_a_failed_express_run_does_not_paint_the_lane_red(tmp_path):
    """The periodic pass is the authority on lane health; a transient
    express failure is a logged warning plus a counter, and the full pass
    still covers the file."""
    lane = _make_lane(
        tmp_path,
        popen_factory=_recording_popen(
            [], stderr_text='{"level":"error","msg":"connection lost"}\n', returncode=1
        ),
    )
    local = Path(lane.local_root)
    lane.notify_path_changed(str(_old_file(local, "Projects/2026/FF5/Alpha/clip.mov")))
    _flush_now(lane)
    assert lane.express_report()["last_error"] == "connection lost"
    assert lane.status().state != "error"


def test_stop_disarms_express_and_drops_pending_paths(tmp_path):
    calls: list = []
    lane = _make_lane(tmp_path, popen_factory=_recording_popen(calls))
    local = Path(lane.local_root)
    lane.notify_path_changed(str(_old_file(local, "Projects/2026/FF5/Alpha/clip.mov")))
    lane.stop()
    assert lane._express_pending == {}
    assert lane._express_timer is None
    # A late watchdog event after stop() must not spawn an rclone.
    lane.notify_path_changed(str(local / "Projects/2026/FF5/Alpha/clip.mov"))
    _flush_now(lane)
    assert calls == []


def _watchdog_handler(lane):
    lane._start_watchdog()
    handlers = lane._observer._handlers
    return list(handlers[list(handlers)[0]])[0]


def _event(path):
    class _Event:
        is_directory = False
        src_path = str(path)

    return _Event()


def test_watchdog_handler_feeds_the_express_path(tmp_path):
    """The wiring itself: a watchdog event on a video file outside Proxy
    reaches notify_path_changed (and still reaches on_change)."""
    pytest.importorskip("watchdog")
    seen: list = []
    lane = _make_lane(tmp_path)
    local = Path(lane.local_root)
    (local / "Projects/2026/FF5/Alpha").mkdir(parents=True)
    lane.on_change = lambda rel: seen.append(rel)
    lane.known_rels_fn = lambda: ["2026/FF5/Alpha"]
    enqueued: list = []
    lane.notify_path_changed = lambda p: enqueued.append(p)

    handler = _watchdog_handler(lane)
    handler.on_created(_event(local / "Projects/2026/FF5/Alpha/clip.mov"))
    lane.stop()
    assert enqueued == [str(local / "Projects/2026/FF5/Alpha/clip.mov")]
    assert seen == ["Projects/2026/FF5/Alpha"]


def test_express_scope_never_exceeds_the_periodic_lane_a_scope(tmp_path):
    """A file under a project the server has NOT selected (or under a stale
    pre-repath name) is skipped by the sequencer's lane A, so express must
    skip it too -- otherwise the express path would push data to the NAS
    that the ordinary pass would never touch."""
    pytest.importorskip("watchdog")
    seen: list = []
    enqueued: list = []
    lane = _make_lane(tmp_path)
    local = Path(lane.local_root)
    (local / "Projects/2026/FF5/Unselected").mkdir(parents=True)
    lane.on_change = lambda rel: seen.append(rel)
    lane.known_rels_fn = lambda: ["2026/FF5/Alpha"]
    lane.notify_path_changed = lambda p: enqueued.append(p)

    handler = _watchdog_handler(lane)
    handler.on_created(_event(local / "Projects/2026/FF5/Unselected/clip.mov"))
    lane.stop()
    assert enqueued == []
    assert seen == []


def test_legacy_mode_still_expresses_and_still_runs_the_debounced_pass(tmp_path):
    pytest.importorskip("watchdog")
    enqueued: list = []
    scheduled: list = []
    lane = _make_lane(tmp_path)  # no on_change -> legacy whole-tree mode
    local = Path(lane.local_root)
    (local / "Projects/2026/FF5/Alpha").mkdir(parents=True)
    lane.notify_path_changed = lambda p: enqueued.append(p)
    lane._schedule_debounced_run = lambda: scheduled.append(1)

    handler = _watchdog_handler(lane)
    handler.on_created(_event(local / "Projects/2026/FF5/Alpha/clip.mov"))
    lane.stop()
    assert len(enqueued) == 1 and scheduled == [1]


# ===========================================================================
# AUDIT_3 M-3: "Pause syncing" must stop the express lane too
# ===========================================================================


def test_paused_express_ignores_notify_path_changed(tmp_path):
    """The tray's Pause only called sequencer.pause(), which halts the
    ROTATION -- lane A's watchdog kept feeding notify_path_changed and
    express kept spawning its own rclone, so a "paused" editor went on
    pushing every new clip to the NAS."""
    calls: list = []
    lane = _make_lane(tmp_path, popen_factory=_recording_popen(calls))
    local = Path(lane.local_root)
    clip = _old_file(local, "Projects/2026/FF5/Alpha/clip.mov")

    lane.pause_express()
    assert lane.express_paused() is True

    lane.notify_path_changed(str(clip))
    assert lane._express_pending == {}
    _flush_now(lane)
    assert calls == [], "a paused lane must not run an express upload"


def test_pause_express_drops_a_batch_already_armed(tmp_path):
    """Pause has to beat a window that is already counting down -- otherwise
    the clip queued one second before Pause is uploaded one second after
    it."""
    calls: list = []
    lane = _make_lane(tmp_path, popen_factory=_recording_popen(calls))
    local = Path(lane.local_root)
    clip = _old_file(local, "Projects/2026/FF5/Alpha/clip.mov")

    lane.notify_path_changed(str(clip))
    assert lane._express_pending, "sanity: queued before the pause"

    lane.pause_express()
    assert lane._express_pending == {}
    assert lane._express_timer is None
    _flush_now(lane)
    assert calls == []


def test_resume_express_re_arms_the_lane(tmp_path):
    calls: list = []
    lists: list = []
    lane = _make_lane(tmp_path, popen_factory=_recording_popen(calls, lists=lists))
    local = Path(lane.local_root)
    clip = _old_file(local, "Projects/2026/FF5/Alpha/clip.mov")

    lane.pause_express()
    lane.notify_path_changed(str(clip))
    lane.resume_express()
    assert lane.express_paused() is False

    lane.notify_path_changed(str(clip))
    _flush_now(lane)

    assert len(calls) == 1
    assert lists == ["Projects/2026/FF5/Alpha/clip.mov\n"]


# ===========================================================================
# AUDIT_3 M-4: an EMPTY known_rels is not "no known_rels"
# ===========================================================================


def test_empty_known_rels_uploads_nothing_instead_of_guessing(tmp_path):
    """sequencer.known_rels() returns [] before the first fetch and whenever
    the dashboard is down. `if known_rels:` treated that like "no selection
    source wired" and fell back to the legacy first-3-components heuristic --
    so a watchdog event in that window express-uploaded a file from a project
    the server never selected."""
    pytest.importorskip("watchdog")
    seen: list = []
    enqueued: list = []
    lane = _make_lane(tmp_path)
    local = Path(lane.local_root)
    (local / "Projects/2026/FF5/Alpha").mkdir(parents=True)
    lane.on_change = lambda rel: seen.append(rel)
    lane.known_rels_fn = lambda: []           # wired, but nothing known yet
    lane.notify_path_changed = lambda p: enqueued.append(p)

    handler = _watchdog_handler(lane)
    handler.on_created(_event(local / "Projects/2026/FF5/Alpha/clip.mov"))
    lane.stop()

    assert enqueued == []
    assert seen == []


def test_a_failing_known_rels_fn_also_uploads_nothing(tmp_path):
    """Same reasoning: a selection source that cannot answer means nothing is
    known to be in scope -- not "fall back to the guess"."""
    pytest.importorskip("watchdog")
    seen: list = []
    enqueued: list = []
    lane = _make_lane(tmp_path)
    local = Path(lane.local_root)
    (local / "Projects/2026/FF5/Alpha").mkdir(parents=True)
    lane.on_change = lambda rel: seen.append(rel)

    def _boom():
        raise RuntimeError("sequencer is gone")

    lane.known_rels_fn = _boom
    lane.notify_path_changed = lambda p: enqueued.append(p)

    handler = _watchdog_handler(lane)
    handler.on_created(_event(local / "Projects/2026/FF5/Alpha/clip.mov"))
    lane.stop()

    assert enqueued == []
    assert seen == []


def test_no_known_rels_fn_at_all_still_uses_the_legacy_heuristic(tmp_path):
    """Legacy whole-tree mode (no dashboard) must be untouched: there the
    periodic pass covers the whole local_root, so any match is in scope."""
    from ccsync_companion.sync.rclone_lane import _project_rel_for_path

    root = str(tmp_path)
    path = str(tmp_path / "Projects/2026/Series/Show/clip.mov")
    assert _project_rel_for_path(root, path, None) == "Projects/2026/Series/Show"
    assert _project_rel_for_path(root, path, []) is None


# ===========================================================================
# The periodic pass must stand down on paths express already has in flight
# (2026-08-02): both use --ignore-existing, but while express is still
# uploading, the destination doesn't exist yet for the periodic pass to skip,
# so the same file went up twice at once over an already-saturated uplink.
# ===========================================================================


def _filter_rules(lane, subpath=None):
    """Build a periodic lane A command and read back the filter file it wrote."""
    lane._build_command(subpath=subpath)
    return [
        line.strip()
        for line in lane._filter_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_periodic_filter_excludes_paths_express_is_uploading(tmp_path):
    lane = _make_lane(tmp_path)
    with lane._express_inflight_lock:
        lane._express_inflight |= {"Projects/2026/P/B-roll/a.mov"}

    rules = _filter_rules(lane, subpath="Projects/2026/P")
    # rules[0] is the AppleDouble exclude (KNOWN_BUGS 12); what matters here
    # is that the in-flight exclude still beats every `+ *<ext>` include.
    assert rules[1] == "- /B-roll/a.mov"
    assert rules.index("- /B-roll/a.mov") < min(
        i for i, rule in enumerate(rules) if rule.startswith("+ ")
    )
    assert rules[-1] == "- **"


def test_periodic_filter_is_unchanged_when_express_is_idle(tmp_path):
    lane = _make_lane(tmp_path)
    assert _filter_rules(lane, subpath="Projects/2026/P") == build_filter_rules_up()


def test_another_projects_inflight_path_does_not_touch_this_run(tmp_path):
    lane = _make_lane(tmp_path)
    with lane._express_inflight_lock:
        lane._express_inflight |= {"Projects/2026/OTHER/a.mov"}
    assert _filter_rules(lane, subpath="Projects/2026/P") == build_filter_rules_up()


def test_lane_b_filter_never_gets_express_excludes(tmp_path):
    """Express is lane A only; lane B's rules must stay exactly as they were
    (an exclude leaking in here would skip a proxy download)."""
    lane = _make_lane(tmp_path, direction=DIRECTION_DOWN)
    with lane._express_inflight_lock:
        lane._express_inflight |= {"Projects/2026/P/B-roll/a.mov"}
    lane._build_command(subpath="Projects/2026/P")
    rules = [l.strip() for l in lane._filter_file.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert rules == build_filter_rules_down()


def test_inflight_claim_is_registered_during_the_run_and_released_after(tmp_path):
    """The claim must be visible WHILE rclone runs and gone afterwards."""
    seen: list[list[str]] = []
    root = tmp_path / "local"
    _old_file(root, "Projects/2026/P/B-roll/a.mov")

    def popen_factory(cmd, **kwargs):
        seen.append(sorted(lane._express_inflight))
        return _FakeExpressProc("", 0)

    lane = _make_lane(tmp_path, popen_factory=popen_factory)
    lane.notify_path_changed(str(root / "Projects/2026/P/B-roll/a.mov"))
    _flush_now(lane)

    assert seen == [["Projects/2026/P/B-roll/a.mov"]]   # held during the run
    assert lane.express_inflight_paths() == []           # released after


def test_a_crashing_express_run_still_releases_its_claim(tmp_path):
    """A leaked claim would exclude those paths from EVERY future periodic
    pass -- stranding the file permanently, which is worse than duplicating."""
    root = tmp_path / "local"
    _old_file(root, "Projects/2026/P/B-roll/a.mov")

    def popen_factory(cmd, **kwargs):
        raise OSError("rclone vanished")

    lane = _make_lane(tmp_path, popen_factory=popen_factory)
    lane.notify_path_changed(str(root / "Projects/2026/P/B-roll/a.mov"))
    _flush_now(lane)

    assert lane.express_inflight_paths() == []


def test_express_stands_down_when_the_local_root_is_gone(tmp_path):
    """Same gate as the periodic pass: the express run builds a
    --files-from list of paths RELATIVE TO local_root, so against a tree that
    has been unplugged every entry names a file that is not there. Nothing is
    lost -- the paths are still on the drive, and the periodic pass owns them
    when it returns."""
    import shutil

    calls: list = []
    lane = _make_lane(tmp_path, popen_factory=_recording_popen(calls))
    _old_file(Path(lane.local_root), "Projects/2026/FF5/Alpha/clip.mov")

    lane._express_run(["Projects/2026/FF5/Alpha/clip.mov"])
    assert len(calls) == 1, "sanity: express normally runs"

    shutil.rmtree(lane.local_root)
    lane._express_run(["Projects/2026/FF5/Alpha/clip.mov"])
    assert len(calls) == 1, "express spawned rclone against an unmounted tree"


def test_write_in_a_borrowed_dir_attributes_to_the_borrowed_rel(tmp_path):
    """SHARED_FOLDERS_PLAN.md §3.2: the sequencer's known_rels() carries
    borrowed rels alongside the selection's own, and the longest known rel
    wins -- so a clip dropped into a borrowed dir is express-uploaded under
    the LENDER's NAS path (the subtree the borrower actually runs), never
    the lender's root (not selected here) and never dropped."""
    from ccsync_companion.sync.rclone_lane import _project_rel_for_path

    root = str(tmp_path)
    borrowed = "2026/FF5/Civil Defence/Interviewees/Aha Chu"
    known = ["2026/FF5/Elections", borrowed]      # what known_rels() returns
    path = str(tmp_path / "Projects/2026/FF5/Civil Defence/Interviewees/Aha Chu/clip.mov")
    assert _project_rel_for_path(root, path, known) == f"Projects/{borrowed}"
    # a write elsewhere in the lender is NOT in scope on this machine
    other = str(tmp_path / "Projects/2026/FF5/Civil Defence/B-roll/clip.mov")
    assert _project_rel_for_path(root, other, known) is None
