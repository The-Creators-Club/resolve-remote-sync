"""broll_upload.py: the rclone command, the artifact ORDER, the pause, and
the size verification.

No rclone is spawned: the queue takes a `runner` seam, `run_upload` is
exercised against a fake Popen, and the verification against a fake
CompletedProcess. The ordering assertions are the load-bearing ones -- stills
first is what makes a clip visible in the search UI before its 40 GB original
has moved a byte.
"""

from __future__ import annotations

import json
import subprocess
import threading
import time

import pytest

from ccsync_companion import broll_upload as up
from ccsync_companion import broll_fetch
from ccsync_companion.sync import rclone_lane

CFG = {
    "remote": "nas",
    "remote_root": "/mnt/tank/Creators_Club",
    "rclone_path": "rclone",
    "local_root": "P:\\",
}


def _cfg(**over):
    out = dict(CFG)
    out.update(over)
    return out


@pytest.fixture(autouse=True)
def _no_real_rclone_probe(monkeypatch):
    """`prereq_error` ends in `rclone_available()`, which SPAWNS rclone -- fine
    on a base rig, a hang-until-timeout on any machine without one (and this
    suite must pass on a bare CI runner). Stubbed with the pure-config half of
    the same check, so "this machine names no remote" is still exercised."""
    def fake_prereq(cfg):
        if not str((cfg or {}).get("remote") or "").strip():
            return ("this machine's sync config names no rclone remote, so the "
                    "clip can't be fetched from the NAS (remote= in ~/.ccsync/config.toml)")
        if not str((cfg or {}).get("remote_root") or "").strip():
            return "this machine's sync config has no remote_root"
        return None

    monkeypatch.setattr(up.broll_fetch, "prereq_error", fake_prereq)


def _sub(cmd, sequence):
    n = len(sequence)
    return any(cmd[i:i + n] == sequence for i in range(len(cmd) - n + 1))


# ---------------------------------------------------------------------------
# the command
# ---------------------------------------------------------------------------

def test_the_upload_command_is_a_copyto_into_the_archive():
    cmd = up.build_upload_command(_cfg(), r"C:\staging\77.mp4",
                                  "Creators_Club/E2E/Proxy/A001.mp4")
    assert cmd[:3] == ["rclone", "copyto", r"C:\staging\77.mp4"]
    assert cmd[3] == "nas:/mnt/tank/Creators_Club/Assets/B-roll Archive/Creators_Club/E2E/Proxy/A001.mp4"


def test_the_upload_command_carries_the_operators_tuning_for_the_UP_direction():
    """The same knobs lane A honours: an operator who set sftp_chunk_size in
    config.toml did not mean "except for b-roll uploads"."""
    cfg = _cfg(sftp_chunk_size="256k", sftp_connections=8, checkers=16)
    cmd = up.build_upload_command(cfg, "a.jpg", "x/posters/1.jpg")

    tuning = rclone_lane.RcloneTuning.from_cfg(cfg)
    for flag in tuning.flags(rclone_lane.DIRECTION_UP):
        assert flag in cmd
    assert _sub(cmd, ["--sftp-chunk-size", "256k"])
    for flag in rclone_lane._transport_flags():
        assert flag in cmd


def test_the_upload_command_asks_for_json_stats_once_a_second():
    cmd = up.build_upload_command(_cfg(), "a.mp4", "x.mp4")
    assert "--use-json-log" in cmd
    assert _sub(cmd, ["--stats", "1s"])
    assert _sub(cmd, ["--stats-log-level", "NOTICE"])


def test_the_remote_path_never_grows_a_double_slash():
    cmd = up.build_upload_command(_cfg(remote_root="/mnt/tank/CC/"), "a", "/x/y.mp4")
    assert "//" not in cmd[3].split(":", 1)[1]


def test_the_archive_folder_is_the_one_the_download_half_uses():
    """One layout, two directions. broll_fetch pins the local/remote pair; a
    second spelling here would upload into a folder nothing serves."""
    assert up.ARCHIVE_REMOTE_REL == broll_fetch.ARCHIVE_REMOTE_REL == "Assets/B-roll Archive"


# ---------------------------------------------------------------------------
# verification
# ---------------------------------------------------------------------------

def test_the_verify_command_is_an_lsjson_of_the_uploaded_file():
    cmd = up.build_verify_command(_cfg(), "x/Proxy/A001.mp4")
    assert cmd[:2] == ["rclone", "lsjson"]
    assert cmd[2].endswith("Assets/B-roll Archive/x/Proxy/A001.mp4")


def test_parse_verify_size_reads_the_matching_row():
    out = json.dumps([{"Path": "A001.mp4", "Name": "A001.mp4", "Size": 12345, "IsDir": False}])
    assert up.parse_verify_size(out, "A001.mp4") == 12345


def test_parse_verify_size_ignores_a_row_for_another_file():
    out = json.dumps([{"Name": "B002.mp4", "Size": 1}])
    assert up.parse_verify_size(out, "A001.mp4") is None


@pytest.mark.parametrize("stdout", ["", "not json", "[]", "{}", None])
def test_parse_verify_size_of_an_unreadable_answer_is_none_not_zero(stdout):
    """None means "could not tell", never "the upload failed" -- the server
    stats the file itself before flipping the row live, and failing a clip on
    our own JSON parsing would be the worst kind of false negative."""
    assert up.parse_verify_size(stdout, "x.mp4") is None


class _FakeCompleted:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_verify_accepts_a_matching_size(tmp_path):
    local = tmp_path / "a.mp4"
    local.write_bytes(b"x" * 500)
    job = up.UploadJob(str(local), "x/a.mp4", up.KIND_PROXY)
    out = json.dumps([{"Name": "a.mp4", "Size": 500}])

    ok, error = up.verify_upload(_cfg(), job, runner=lambda cmd: _FakeCompleted(stdout=out))
    assert (ok, error) == (True, "")


def test_verify_rejects_a_truncated_upload(tmp_path):
    local = tmp_path / "a.mp4"
    local.write_bytes(b"x" * 500)
    job = up.UploadJob(str(local), "x/a.mp4", up.KIND_PROXY)
    out = json.dumps([{"Name": "a.mp4", "Size": 120}])

    ok, error = up.verify_upload(_cfg(), job, runner=lambda cmd: _FakeCompleted(stdout=out))
    assert ok is False
    assert "120 bytes, not 500" in error


def test_verify_reports_a_file_that_is_not_there_at_all(tmp_path):
    local = tmp_path / "a.mp4"
    local.write_bytes(b"x")
    job = up.UploadJob(str(local), "x/a.mp4", up.KIND_PROXY)

    ok, error = up.verify_upload(
        _cfg(), job, runner=lambda cmd: _FakeCompleted(returncode=3, stderr="directory not found"))
    assert ok is False
    assert "is not on the NAS" in error


def test_verify_that_cannot_run_at_all_does_not_fail_the_clip(tmp_path):
    """The server's own stat() is the authority; a broken lsjson here must not
    be what marks an indexed clip failed."""
    local = tmp_path / "a.mp4"
    local.write_bytes(b"x")
    job = up.UploadJob(str(local), "x/a.mp4", up.KIND_PROXY)

    def boom(cmd):
        raise OSError("rclone vanished")

    assert up.verify_upload(_cfg(), job, runner=boom) == (True, "")


# ---------------------------------------------------------------------------
# the queue
# ---------------------------------------------------------------------------

def _queue(runner=None, cfg=None):
    return up.UploadQueue(lambda: cfg if cfg is not None else _cfg(), runner=runner)


def _drain(queue, expected, timeout=5.0):
    """Wait until `expected` jobs have finished, or fail loudly."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        snap = queue.progress()
        if snap["done"] + snap["failed"] >= expected:
            return snap
        time.sleep(0.01)
    pytest.fail(f"queue did not drain: {queue.progress()}")


def test_stills_go_first_the_proxy_next_and_the_original_last():
    """The clip becomes VISIBLE the moment the server can stat the poster and
    the sprite, playable when the proxy lands, and the 40 GB original blocks
    nothing (docs/BROLL_INGEST_PLAN.md §1 step 7)."""
    order = []
    queue = _queue(runner=lambda q, job, cmd: (order.append(job.kind), q._finish(job, True)))
    # Paused while the clip's four artifacts are offered, because the queue
    # starts working the instant it has one -- which is what it should do in
    # production, where they are offered as each stage finishes.
    queue.pause()

    # Enqueued in the WRONG order on purpose.
    queue.enqueue("o.mov", "x/A001.mov", up.KIND_ORIGINAL)
    queue.enqueue("p.mp4", "x/Proxy/A001.mp4", up.KIND_PROXY)
    queue.enqueue("s.jpg", "sprites/1.jpg", up.KIND_SPRITE)
    queue.enqueue("po.jpg", "posters/1.jpg", up.KIND_POSTER)
    queue.resume()

    _drain(queue, 4)
    assert order == [up.KIND_POSTER, up.KIND_SPRITE, up.KIND_PROXY, up.KIND_ORIGINAL]
    queue.stop_all()


def test_only_one_rclone_runs_at_a_time():
    """Lanes A and B are already competing for the one SFTP link; the
    sequencer exists because two rclones on one link are slower than one."""
    concurrent = []
    running = threading.Lock()

    def runner(q, job, cmd):
        got = running.acquire(blocking=False)
        concurrent.append(got)
        time.sleep(0.02)
        if got:
            running.release()
        q._finish(job, True)

    queue = _queue(runner=runner)
    for i in range(5):
        queue.enqueue(f"{i}.jpg", f"posters/{i}.jpg", up.KIND_POSTER)

    _drain(queue, 5)
    assert all(concurrent), "two uploads overlapped"
    queue.stop_all()


def test_pause_stops_starting_new_uploads_and_resume_continues():
    started = []
    queue = _queue(runner=lambda q, job, cmd: (started.append(job.remote_rel),
                                               q._finish(job, True)))
    queue.pause()
    queue.enqueue("a.jpg", "posters/1.jpg", up.KIND_POSTER)
    time.sleep(0.1)
    assert started == []
    assert queue.progress()["paused"] is True
    assert queue.progress()["queued"] == 1

    queue.resume()
    _drain(queue, 1)
    assert started == ["posters/1.jpg"]
    queue.stop_all()


def test_progress_is_zero_io_and_names_the_file_in_flight(monkeypatch):
    held = threading.Event()

    def runner(q, job, cmd):
        job.feed_stats({"bytes": 50, "totalBytes": 100, "speed": 10.0, "eta": 5})
        held.wait(timeout=2)
        q._finish(job, True)

    queue = _queue(runner=runner)
    queue.enqueue("a.mp4", "x/Proxy/a.mp4", up.KIND_PROXY)
    deadline = time.time() + 2
    while time.time() < deadline and queue.progress()["active"] is None:
        time.sleep(0.01)

    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: pytest.fail("progress() spawned"))
    snap = queue.progress()
    assert snap["active"]["rel"] == "x/Proxy/a.mp4"
    assert snap["active"]["percent"] == 50
    assert snap["active"]["kind"] == up.KIND_PROXY

    held.set()
    _drain(queue, 1)
    queue.stop_all()


def test_a_re_queued_file_joins_the_job_already_in_the_queue():
    """The orchestrator's tick can re-offer the same artifact (a retried item,
    a duplicated tick). Two rclones writing the same destination would race
    for one .partial."""
    queue = _queue(runner=lambda q, job, cmd: q._finish(job, True))
    queue.pause()
    a = queue.enqueue("a.jpg", "posters/1.jpg", up.KIND_POSTER)
    b = queue.enqueue("a.jpg", "posters/1.jpg", up.KIND_POSTER)
    assert a is b
    assert queue.progress()["queued"] == 1
    queue.stop_all()


def test_a_failed_upload_is_recorded_with_its_reason():
    queue = _queue(runner=lambda q, job, cmd: q._finish(job, False, "connection refused"))
    queue.enqueue("a.jpg", "posters/1.jpg", up.KIND_POSTER)
    _drain(queue, 1)

    assert queue.progress()["failed"] == 1
    assert queue.failures()[0]["error"] == "connection refused"
    assert queue.failures()[0]["rel"] == "posters/1.jpg"
    queue.stop_all()


def test_uploaded_reports_the_shape_the_fleet_route_wants():
    def runner(q, job, cmd):
        job.feed_stats({"bytes": 10, "totalBytes": 10})
        q._finish(job, True)

    queue = _queue(runner=runner)
    queue.enqueue("a.jpg", "posters/1.jpg", up.KIND_POSTER, item_uid="abc")
    _drain(queue, 1)

    assert queue.uploaded() == [{"rel": "posters/1.jpg", "kind": up.KIND_POSTER,
                                 "item_uid": "abc", "size": 10}]
    queue.stop_all()


def test_a_machine_that_cannot_reach_the_nas_waits_instead_of_failing_the_item():
    """"NAS unreachable" must not burn an item's attempts: the job goes back
    to the front of the queue and the next tick tries again (plan §6)."""
    tried = []
    queue = up.UploadQueue(lambda: {"remote": "", "local_root": "P:\\"},
                           runner=lambda q, job, cmd: tried.append(job) or q._finish(job, True))
    job = queue.enqueue("a.jpg", "posters/1.jpg", up.KIND_POSTER)
    time.sleep(0.2)

    assert tried == []
    snap = queue.progress()
    assert snap["queued"] == 1 and snap["failed"] == 0
    assert "names no rclone remote" in (job.error or "")
    queue.stop_all()


def test_stop_all_kills_the_active_job_and_empties_the_queue():
    started = threading.Event()

    def runner(q, job, cmd):
        started.set()
        time.sleep(0.5)
        q._finish(job, True)

    queue = _queue(runner=runner)
    queue.enqueue("a.mp4", "x/a.mp4", up.KIND_PROXY)
    queue.enqueue("b.mp4", "x/b.mp4", up.KIND_PROXY)
    started.wait(timeout=2)
    queue.stop_all()

    assert queue.progress()["queued"] == 0


# ---------------------------------------------------------------------------
# run_upload against a fake rclone
# ---------------------------------------------------------------------------

class _FakePopen:
    def __init__(self, lines, returncode=0):
        self.stderr = iter(lines)
        self._returncode = returncode
        self.killed = False

    def wait(self):
        return self._returncode

    def kill(self):
        self.killed = True


def test_run_upload_feeds_stats_into_the_job(monkeypatch):
    lines = [
        json.dumps({"level": "info", "stats": {"bytes": 60, "totalBytes": 120,
                                               "speed": 3.0, "eta": 20}}) + "\n",
        "not json at all\n",
    ]
    monkeypatch.setattr(up.subprocess, "Popen", lambda *a, **kw: _FakePopen(lines))
    job = up.UploadJob("a.mp4", "x/a.mp4", up.KIND_PROXY)

    ok, error = up.run_upload(job, ["rclone"])

    assert (ok, error) == (True, "")
    assert job.progress()["percent"] == 50


def test_run_upload_reports_rclones_own_error_line(monkeypatch):
    lines = [
        json.dumps({"level": "error", "msg": "Failed to copy: permission denied"}) + "\n",
        json.dumps({"level": "error", "msg": "fatal error received"}) + "\n",
    ]
    monkeypatch.setattr(up.subprocess, "Popen",
                        lambda *a, **kw: _FakePopen(lines, returncode=1))
    job = up.UploadJob("a.mp4", "x/a.mp4", up.KIND_PROXY)

    ok, error = up.run_upload(job, ["rclone"])

    assert ok is False
    # The closing "fatal error received" notice repeats the fact without the
    # cause -- the useful line is the one before it.
    assert error == "Failed to copy: permission denied"


def test_run_upload_survives_rclone_not_being_startable(monkeypatch):
    def boom(*a, **kw):
        raise OSError("no rclone here")

    monkeypatch.setattr(up.subprocess, "Popen", boom)
    ok, error = up.run_upload(up.UploadJob("a", "b", up.KIND_PROXY), ["rclone"])
    assert ok is False and "could not start rclone" in error


def test_run_upload_spawns_with_the_window_suppressed(monkeypatch):
    captured = {}

    def fake_popen(cmd, **kwargs):
        captured.update(kwargs)
        return _FakePopen([])

    monkeypatch.setattr(up.subprocess, "Popen", fake_popen)
    up.run_upload(up.UploadJob("a", "b", up.KIND_PROXY), ["rclone"])
    assert "creationflags" in captured
    assert captured["stdout"] is subprocess.DEVNULL


def test_a_cancelled_job_reports_cancelled_not_a_failure(monkeypatch):
    monkeypatch.setattr(up.subprocess, "Popen",
                        lambda *a, **kw: _FakePopen([], returncode=-9))
    job = up.UploadJob("a", "b", up.KIND_PROXY)
    job.cancel()

    ok, error = up.run_upload(job, ["rclone"])
    assert ok is False and error == "cancelled"


# ---------------------------------------------------------------------------
# the stop latch and the retry (comp-loopback-1 / comp-loopback-3, 2026-08-21)
# ---------------------------------------------------------------------------

def test_a_stopped_queue_never_takes_another_job():
    """comp-loopback-1: `stop_all` is a ONE-WAY latch. `_ensure_thread`
    refuses to start a worker while `_stopped` is set, so anything enqueued
    afterwards sits in a list nothing will ever drain -- which is why the
    orchestrator drops a stopped queue instead of reusing it."""
    ran: list = []
    queue = _queue(runner=lambda q, job, cmd: ran.append(job) or q._finish(job, True))
    queue.stop_all()

    queue.enqueue("a.jpg", "posters/1.jpg", up.KIND_POSTER)
    time.sleep(0.1)

    assert ran == [], "a stopped queue must not start a worker"
    assert queue.progress()["queued"] == 1
    assert queue.uploaded() == []


def test_stop_all_says_what_it_cancelled():
    """What was killed did NOT go up: a reader that only ever saw `done` would
    report a batch whose uploads were cancelled as one with nothing
    outstanding (comp-loopback-1, 2026-08-21)."""
    started = threading.Event()

    def runner(q, job, cmd):
        started.set()
        time.sleep(0.3)
        q._finish(job, True)

    queue = _queue(runner=runner)
    queue.enqueue("a.mp4", "x/a.mp4", up.KIND_PROXY)
    queue.enqueue("b.mp4", "x/b.mp4", up.KIND_PROXY)
    started.wait(timeout=2)
    queue.stop_all()

    rels = [entry["rel"] for entry in queue.failures()]
    assert "x/b.mp4" in rels
    assert queue.failures()[-1]["error"] == "cancelled"


def test_retry_forgets_a_failure_so_the_file_can_be_sent_again():
    """comp-loopback-3: `failures()` is a ledger, not a queue. A rel left in
    it reads as still broken on every later tick, so the caller re-sending a
    failed upload has to clear the verdict first."""
    attempts: list = []

    def runner(q, job, cmd):
        attempts.append(job.remote_rel)
        ok = len(attempts) > 1
        q._finish(job, ok, "" if ok else "rclone exited with code 1")

    queue = _queue(runner=runner)
    queue.enqueue("a.jpg", "posters/1.jpg", up.KIND_POSTER)
    _drain(queue, 1)
    assert [entry["rel"] for entry in queue.failures()] == ["posters/1.jpg"]

    dropped = queue.retry(["posters/1.jpg"])
    queue.enqueue("a.jpg", "posters/1.jpg", up.KIND_POSTER)
    _drain(queue, 1)

    assert dropped == 1
    assert queue.failures() == []
    assert [entry["rel"] for entry in queue.uploaded()] == ["posters/1.jpg"]
    queue.stop_all()


def test_retry_leaves_the_failures_it_was_not_asked_about():
    queue = _queue(runner=lambda q, job, cmd: q._finish(job, False, "no"))
    queue.enqueue("a.jpg", "posters/1.jpg", up.KIND_POSTER)
    queue.enqueue("b.jpg", "posters/2.jpg", up.KIND_POSTER)
    _drain(queue, 2)

    queue.retry(["posters/1.jpg"])

    assert [entry["rel"] for entry in queue.failures()] == ["posters/2.jpg"]
    assert queue.retry([]) == 0
    queue.stop_all()
