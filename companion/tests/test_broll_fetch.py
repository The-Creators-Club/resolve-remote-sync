"""On-demand archive clip download (broll_fetch) -- the piece that makes
"Send to Resolve" work on machines that don't sync the b-roll archive.

Layers, in request order: the command builder and prereq checks (pure),
the job registry poll_fetch serves broll_server from, the real _run_job
against a python child standing in for rclone, and shutdown.
"""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

import pytest

from ccsync_companion import broll_fetch, broll_server
from ccsync_companion.sync import rclone_lane


CFG = {
    "remote": "creators_club_sftp",
    "remote_root": "/mnt/tank/creators_club",
    "rclone_path": "rclone",
    "local_root": "C:/Creators_Club",
}


@pytest.fixture(autouse=True)
def clean_registry():
    """No test may inherit another's jobs, or leak its own."""
    with broll_fetch._JOBS_LOCK:
        broll_fetch._JOBS.clear()
    yield
    broll_fetch.stop_all()
    with broll_fetch._JOBS_LOCK:
        broll_fetch._JOBS.clear()


@pytest.fixture
def rclone_present(monkeypatch):
    monkeypatch.setattr(
        broll_fetch.rclone_lane, "rclone_available", lambda path, use_cache=True: (True, path)
    )


# ---------------------------------------------------------------------------
# The command
# ---------------------------------------------------------------------------


def test_the_remote_rel_matches_the_local_archive_rel():
    """The two halves of one layout: broll_server derives the LOCAL archive
    path from BROLL_ARCHIVE_REL, this module derives the NAS path from
    ARCHIVE_REMOTE_REL. If they drift, downloads land beside the archive the
    inserts read from."""
    assert "/".join(broll_server.BROLL_ARCHIVE_REL) == broll_fetch.ARCHIVE_REMOTE_REL


def test_fetch_command_is_a_single_file_copyto(tmp_path):
    dest = tmp_path / "clip.mov"
    cmd = broll_fetch.build_fetch_command(CFG, "military/naval/clip.mov", str(dest))
    assert cmd[0] == "rclone"
    assert cmd[1] == "copyto"
    assert cmd[2] == (
        "creators_club_sftp:/mnt/tank/creators_club/Assets/B-roll Archive/"
        "military/naval/clip.mov"
    )
    assert cmd[3] == str(dest)


def test_fetch_command_strips_a_trailing_slash_off_remote_root(tmp_path):
    cfg = dict(CFG, remote_root="/mnt/tank/creators_club/")
    cmd = broll_fetch.build_fetch_command(cfg, "clip.mov", str(tmp_path / "clip.mov"))
    assert "//Assets" not in cmd[2]
    assert cmd[2].endswith("/Assets/B-roll Archive/clip.mov")


def test_fetch_command_carries_stats_and_json_log(tmp_path):
    """--use-json-log + --stats is what the progress parse reads; losing
    either turns the web UI's percentage into a permanent spinner."""
    cmd = broll_fetch.build_fetch_command(CFG, "clip.mov", str(tmp_path / "clip.mov"))
    assert "--use-json-log" in cmd
    assert "--stats" in cmd


def test_fetch_command_respects_the_operators_tuning(tmp_path):
    cfg = dict(CFG, sftp_chunk_size="128Ki", rclone_path="C:/tools/rclone.exe")
    cmd = broll_fetch.build_fetch_command(cfg, "clip.mov", str(tmp_path / "clip.mov"))
    assert cmd[0] == "C:/tools/rclone.exe"
    assert "--sftp-chunk-size" in cmd
    assert cmd[cmd.index("--sftp-chunk-size") + 1] == "128Ki"


# ---------------------------------------------------------------------------
# Prereqs
# ---------------------------------------------------------------------------


def test_a_blank_remote_is_an_editor_facing_refusal(rclone_present):
    err = broll_fetch.prereq_error(dict(CFG, remote=""))
    assert err is not None and "remote" in err


def test_a_blank_remote_root_is_too(rclone_present):
    err = broll_fetch.prereq_error(dict(CFG, remote_root=" "))
    assert err is not None and "remote_root" in err


def test_a_missing_rclone_is_reported_with_its_own_detail(monkeypatch):
    monkeypatch.setattr(
        broll_fetch.rclone_lane, "rclone_available",
        lambda path, use_cache=True: (False, "rclone not found on PATH ('rclone')"),
    )
    err = broll_fetch.prereq_error(CFG)
    assert err is not None and "rclone not found on PATH" in err


def test_a_configured_machine_passes(rclone_present):
    assert broll_fetch.prereq_error(CFG) is None


# ---------------------------------------------------------------------------
# poll_fetch: the registry
# ---------------------------------------------------------------------------


def _capturing_runner(started: list):
    def runner(job, cmd):
        started.append((job, cmd))
    return runner


def test_first_poll_starts_the_job_and_reports_downloading(tmp_path, rclone_present):
    started: list = []
    result = broll_fetch.poll_fetch(
        CFG, "a/clip.mov", str(tmp_path / "clip.mov"), runner=_capturing_runner(started)
    )
    assert result["state"] == "downloading"
    assert "progress" in result
    assert len(started) == 1


def test_a_second_poll_joins_the_running_job(tmp_path, rclone_present):
    """The web UI re-POSTs every 1.5s and editors double-click: one rclone
    per destination, never two racing for the same .partial."""
    started: list = []
    dest = str(tmp_path / "clip.mov")
    runner = _capturing_runner(started)
    broll_fetch.poll_fetch(CFG, "a/clip.mov", dest, runner=runner)
    result = broll_fetch.poll_fetch(CFG, "a/clip.mov", dest, runner=runner)
    assert result["state"] == "downloading"
    assert len(started) == 1


def test_progress_flows_from_stats_to_the_poll(tmp_path, rclone_present):
    started: list = []
    dest = str(tmp_path / "clip.mov")
    broll_fetch.poll_fetch(CFG, "a/clip.mov", dest, runner=_capturing_runner(started))
    job, _cmd = started[0]
    job.feed_stats({"bytes": 25, "totalBytes": 100, "speed": 10.0, "eta": 8})

    result = broll_fetch.poll_fetch(CFG, "a/clip.mov", dest, runner=_capturing_runner([]))

    assert result["progress"]["percent"] == 25
    assert result["progress"]["speed_bps"] == 10.0


def test_done_is_reported_once_then_popped(tmp_path, rclone_present):
    started: list = []
    dest = str(tmp_path / "clip.mov")
    runner = _capturing_runner(started)
    broll_fetch.poll_fetch(CFG, "a/clip.mov", dest, runner=runner)
    job, _cmd = started[0]
    with job.lock:
        job.state = broll_fetch.STATE_DONE

    assert broll_fetch.poll_fetch(CFG, "a/clip.mov", dest, runner=runner)["state"] == "done"
    # Popped: the next poll starts fresh (the caller only polls again if the
    # file is somehow still missing).
    assert broll_fetch.poll_fetch(CFG, "a/clip.mov", dest, runner=runner)["state"] == "downloading"
    assert len(started) == 2


def test_a_failure_is_reported_once_then_retried(tmp_path, rclone_present):
    started: list = []
    dest = str(tmp_path / "clip.mov")
    runner = _capturing_runner(started)
    broll_fetch.poll_fetch(CFG, "a/clip.mov", dest, runner=runner)
    job, _cmd = started[0]
    with job.lock:
        job.state = broll_fetch.STATE_FAILED
        job.error = "sftp: no such file"

    result = broll_fetch.poll_fetch(CFG, "a/clip.mov", dest, runner=runner)
    assert result == {"state": "failed", "message": "sftp: no such file"}
    # The failed job is gone; a re-click starts a new download.
    assert broll_fetch.poll_fetch(CFG, "a/clip.mov", dest, runner=runner)["state"] == "downloading"
    assert len(started) == 2


def test_a_prereq_failure_registers_no_job(tmp_path, rclone_present):
    started: list = []
    result = broll_fetch.poll_fetch(
        dict(CFG, remote=""), "a/clip.mov", str(tmp_path / "clip.mov"),
        runner=_capturing_runner(started),
    )
    assert result["state"] == "failed"
    assert started == []
    with broll_fetch._JOBS_LOCK:
        assert broll_fetch._JOBS == {}


# ---------------------------------------------------------------------------
# The cap, the tree and the destination (COMMERCIAL_READINESS.md item 5)
# ---------------------------------------------------------------------------


def test_a_third_concurrent_download_is_refused_not_queued(tmp_path, rclone_present):
    """The web UI re-POSTs every 1.5 s, so without a cap a page holding the
    button down is a spawn button: one rclone per click, all of them competing
    with lanes A and B for the same SFTP link."""
    started: list = []
    runner = _capturing_runner(started)
    for n in range(broll_fetch.MAX_CONCURRENT_FETCHES):
        assert broll_fetch.poll_fetch(
            CFG, f"a/clip{n}.mov", str(tmp_path / f"clip{n}.mov"), runner=runner
        )["state"] == "downloading"

    result = broll_fetch.poll_fetch(
        CFG, "a/one_too_many.mov", str(tmp_path / "one_too_many.mov"), runner=runner)

    # "busy", not "failed" (CMEDIA-7, 2026-09-04): the cap was always designed
    # around the page's own 1.5 s re-POST being the retry, and the page loops
    # only while the state is downloading -- so as a failure it was a red toast
    # and the end of the attempt, with the editor told to come back later.
    assert result == {"state": "busy", "message": broll_fetch.BUSY_MESSAGE,
                      "retry_after": broll_fetch.BUSY_RETRY_AFTER_SECONDS}
    assert len(started) == broll_fetch.MAX_CONCURRENT_FETCHES
    # ...and the refused one registered nothing, so the next poll is a fresh
    # start rather than a job stuck in "failed".
    with broll_fetch._JOBS_LOCK:
        assert str(tmp_path / "one_too_many.mov").lower() not in \
            [k.lower() for k in broll_fetch._JOBS]


def test_a_poll_of_a_running_job_is_never_capped(tmp_path, rclone_present):
    """The cap must not break the poll loop of the downloads already running:
    joining an existing job is not a new child."""
    started: list = []
    runner = _capturing_runner(started)
    dests = [str(tmp_path / f"clip{n}.mov")
             for n in range(broll_fetch.MAX_CONCURRENT_FETCHES)]
    for n, dest in enumerate(dests):
        broll_fetch.poll_fetch(CFG, f"a/clip{n}.mov", dest, runner=runner)

    for n, dest in enumerate(dests):
        assert broll_fetch.poll_fetch(
            CFG, f"a/clip{n}.mov", dest, runner=runner)["state"] == "downloading"
    assert len(started) == broll_fetch.MAX_CONCURRENT_FETCHES


def test_a_destination_outside_the_tree_is_refused(tmp_path):
    """Defence in depth behind the (share, rel_path) validation: an
    `rclone copyto` writes wherever it is pointed, and the mounts table it is
    pointed through is a file an editor can hand-edit."""
    cfg = dict(CFG, local_root=str(tmp_path / "tree"))
    (tmp_path / "tree").mkdir()
    refusal = broll_fetch.fetch_refusal(cfg, str(tmp_path / "elsewhere" / "clip.mov"))
    assert refusal and "outside this machine's tree" in refusal


def test_a_destination_inside_the_tree_is_allowed(tmp_path):
    cfg = dict(CFG, local_root=str(tmp_path))
    assert broll_fetch.fetch_refusal(
        cfg, str(tmp_path / "Assets" / "B-roll Archive" / "clip.mov")) is None


def test_no_local_root_means_nowhere_to_put_it(tmp_path):
    assert broll_fetch.fetch_refusal(dict(CFG, local_root=""),
                                     str(tmp_path / "clip.mov"))


def test_an_absent_tree_stops_the_download_before_rclone_runs(tmp_path):
    """THE macOS failure this guard exists for: `rclone` into an unmounted
    /Volumes/<Name> does not fail -- it creates the directory on the boot
    volume and fills the internal disk (root_guard.py). Every lane asks the
    guard first; this download never did."""
    cfg = dict(CFG, local_root=str(tmp_path))
    refusal = broll_fetch.fetch_refusal(
        cfg, str(tmp_path / "clip.mov"),
        probe=lambda root: broll_fetch.root_guard.ROOT_ABSENT,
    )
    assert refusal and "isn't mounted" in refusal


def test_a_misplaced_volume_is_refused_too(tmp_path):
    cfg = dict(CFG, local_root=str(tmp_path))
    assert broll_fetch.fetch_refusal(
        cfg, str(tmp_path / "clip.mov"),
        probe=lambda root: broll_fetch.root_guard.ROOT_MISPLACED,
    )


def test_a_broken_probe_never_blocks_the_download(tmp_path):
    """root_guard's contract: ROOT_UNKNOWN is "no new information", never a
    reason to stop an editor working."""
    cfg = dict(CFG, local_root=str(tmp_path))
    assert broll_fetch.fetch_refusal(
        cfg, str(tmp_path / "clip.mov"),
        probe=lambda root: broll_fetch.root_guard.ROOT_UNKNOWN,
    ) is None


# ---------------------------------------------------------------------------
# The stderr feed
# ---------------------------------------------------------------------------


def test_feed_line_ignores_non_json_noise():
    job = broll_fetch.FetchJob("dest", "rel")
    errors: list = []
    broll_fetch._feed_line(job, "Transferred: 12345\n", errors)
    broll_fetch._feed_line(job, "{not json", errors)
    assert job.progress()["bytes"] is None
    assert errors == []


def test_feed_line_reads_stats_records():
    job = broll_fetch.FetchJob("dest", "rel")
    line = json.dumps({"level": "notice", "stats": {"bytes": 5, "totalBytes": 10}})
    broll_fetch._feed_line(job, line, [])
    assert job.progress()["percent"] == 50


def test_feed_line_keeps_the_informative_error_not_the_fatal_notice():
    """Same rule as the lanes' _most_informative_error: rclone's closing
    "Fatal error received..." line repeats the fact of failure without the
    cause, and it is the LAST line, so keeping every error and reading the
    tail would surface it instead of the reason."""
    job = broll_fetch.FetchJob("dest", "rel")
    errors: list = []
    broll_fetch._feed_line(
        job, json.dumps({"level": "error", "msg": "sftp: permission denied"}), errors)
    broll_fetch._feed_line(
        job, json.dumps({"level": "fatal", "msg": "Fatal error received - not attempting retries"}),
        errors)
    assert errors == ["sftp: permission denied"]


# ---------------------------------------------------------------------------
# _run_job against a real child process (python standing in for rclone)
# ---------------------------------------------------------------------------


def _fake_rclone_cmd(script: str) -> list[str]:
    return [sys.executable, "-c", script]


def test_run_job_success_lands_the_file_and_reports_done(tmp_path):
    dest = tmp_path / "clip.mov"
    job = broll_fetch.FetchJob(str(dest), "clip.mov")
    stats = json.dumps({"level": "notice", "stats": {"bytes": 4, "totalBytes": 4}})
    script = (
        "import sys, pathlib\n"
        f"pathlib.Path({str(dest)!r}).write_bytes(b'fake')\n"
        f"sys.stderr.write({stats!r} + '\\n')\n"
    )
    broll_fetch._run_job(job, _fake_rclone_cmd(script))
    assert job.state == broll_fetch.STATE_DONE
    assert job.progress()["percent"] == 100


def test_run_job_failure_surfaces_the_childs_error(tmp_path):
    dest = tmp_path / "clip.mov"
    job = broll_fetch.FetchJob(str(dest), "clip.mov")
    err = json.dumps({"level": "error", "msg": "directory not found"})
    script = (
        "import sys\n"
        f"sys.stderr.write({err!r} + '\\n')\n"
        "sys.exit(3)\n"
    )
    broll_fetch._run_job(job, _fake_rclone_cmd(script))
    assert job.state == broll_fetch.STATE_FAILED
    assert job.error == "directory not found"


def test_run_job_exit_zero_without_the_file_is_still_a_failure(tmp_path):
    """rclone reporting success for a file that is not there (a dest share
    yanked mid-run) must not fall through to "done" -- the insert would then
    hand Resolve a path that does not exist."""
    dest = tmp_path / "clip.mov"
    job = broll_fetch.FetchJob(str(dest), "clip.mov")
    broll_fetch._run_job(job, _fake_rclone_cmd("pass"))
    assert job.state == broll_fetch.STATE_FAILED
    assert str(dest) in job.error


def test_run_job_unrunnable_binary_fails_cleanly(tmp_path):
    job = broll_fetch.FetchJob(str(tmp_path / "clip.mov"), "clip.mov")
    broll_fetch._run_job(job, [str(tmp_path / "no-such-rclone.exe"), "copyto"])
    assert job.state == broll_fetch.STATE_FAILED
    assert "could not start rclone" in job.error


# ---------------------------------------------------------------------------
# Shutdown
# ---------------------------------------------------------------------------


class _FakeProc:
    def __init__(self):
        self.killed = False

    def kill(self):
        self.killed = True


def test_stop_all_kills_running_children(tmp_path, rclone_present):
    started: list = []
    broll_fetch.poll_fetch(
        CFG, "a/clip.mov", str(tmp_path / "clip.mov"), runner=_capturing_runner(started))
    job, _cmd = started[0]
    proc = _FakeProc()
    with job.lock:
        job.proc = proc

    broll_fetch.stop_all()

    assert proc.killed is True
    assert job.cancelled is True
