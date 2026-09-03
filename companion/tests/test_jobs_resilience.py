"""What a fleet job survives: a dashboard blip, and a child that stops
answering.

bug-hunt-2026-09-03, findings comp-ytdl-jobs-1/2/4/5/6. Every one of these is
about work that is ALREADY BEING DONE - minutes of GPU or encode - and the
question is whether something outside the machine can throw it away, park it
for ever, or leave litter behind:

  * a heartbeat POST that cannot be delivered is a blip, not a verdict (one
    dashboard deploy used to kill every running job in the fleet);
  * the beater thread cannot be killed by anything it calls;
  * a peaks decode that stops producing output still hears a cancel;
  * a stopped AAC copy takes its `.partial` with it, and a finished file that
    could not be published is KEPT, because the message says it is there.
"""
from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from ccsync_companion import jobs_media
from ccsync_companion import jobs_runner as runner_mod


class FakeIdle:
    def __init__(self, value=900):
        self.value = value

    def seconds_idle(self):
        return self.value


class BlippingDashboard:
    """A dashboard whose /heartbeat is unreachable - a container restart, a
    tailnet wobble - while /claim and /result still work. `default_request`
    RAISES on a transport failure by design, which is the whole point."""

    def __init__(self, job=None):
        self.job = job
        self.beats = 0
        self.results: list[dict] = []

    def request(self, method, url, body, headers, timeout):
        suffix = url.split("/api/v1/jobs", 1)[1]
        if suffix == "/claim":
            job, self.job = self.job, None
            return 200, {"job": job}
        if suffix.endswith("/heartbeat"):
            self.beats += 1
            raise OSError("[Errno 111] Connection refused")
        if suffix.endswith("/result"):
            self.results.append(body)
            return 200, {"ok": True}
        return 404, None


# ------------------------------------------------- comp-ytdl-jobs-1

def _runner(tmp_path, dash, **over):
    vault = tmp_path / "vault"
    (vault / "Ep/Youtube/Interview 3").mkdir(parents=True, exist_ok=True)
    cfg = {"dashboard_url": "http://dash.example", "dashboard_token": "tok",
           "jobs_vault_root": str(vault),
           "jobs_whisper_python": sys.executable,
           "jobs_mulcam_pipeline": str(tmp_path / "MulticamPipeline")}
    cfg.update(over)
    return runner_mod.JobRunner(
        cfg, request_fn=dash.request,
        capabilities_fn=lambda: {"whisper": True},
        idle_probe=FakeIdle(), machine_name="EDIT-PC")


def test_a_heartbeat_that_cannot_be_delivered_is_not_a_verdict(tmp_path):
    """A beat that never arrived says nothing about whether the lease is
    still ours. Only a 410 does."""
    dash = BlippingDashboard()
    assert _runner(tmp_path, dash)._heartbeat(7, 0.5) is True
    assert dash.beats == 1


class FinishingProc:
    """A child that runs for a couple of polls and then exits cleanly."""

    stdout = None

    def __init__(self, waits=3):
        self.left = waits
        self.returncode = None
        self.terminated = False

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        if self.terminated:
            return self.returncode
        # Long enough that the (shortened) heartbeat interval really elapses
        # while the child is still running.
        time.sleep(0.02)
        self.left -= 1
        if self.left <= 0:
            self.returncode = 0
            return 0
        raise subprocess.TimeoutExpired("pipeline.py", timeout or 1)

    def terminate(self):
        self.terminated = True
        self.returncode = -15

    def kill(self):
        self.terminated = True
        self.returncode = -9


def test_a_dashboard_blip_does_not_destroy_a_running_whisper_job(
        tmp_path, monkeypatch):
    """CR-31's shape in the jobs runner: the container restarts for three
    seconds and eighteen minutes of GPU work is terminated, handed back as a
    retryable failure, and the machine that did it is cooled down."""
    monkeypatch.setattr(runner_mod, "HEARTBEAT_SECONDS", 0.01)
    job = {"id": 7, "kind": "whisper",
           "inputs": {"root": "vault", "rel_path": "Ep/Youtube/Interview 3",
                      "episode_rel": "Ep"}}
    dash = BlippingDashboard(job)
    proc = FinishingProc()
    runner = _runner(tmp_path, dash)
    runner._runner = lambda *a, **k: proc
    runner.note_report_reply({"commands": {"jobs": {"offered": [7]}}})
    assert runner.tick() is not None
    assert dash.beats >= 1, "no heartbeat was even attempted"
    assert proc.terminated is False
    assert dash.results[-1]["ok"] is True


# ------------------------------------------------- comp-ytdl-jobs-2

def test_a_blip_does_not_kill_the_media_beater(tmp_path, monkeypatch):
    """A daemon thread whose only job is liveness must survive anything it
    calls. When it died, the encode ran on with an expired lease, the fleet
    handed the same job to a second machine, and nothing anywhere said so -
    in a frozen windowed build the excepthook writes to a stderr that is not
    there."""
    monkeypatch.setattr(runner_mod, "HEARTBEAT_SECONDS", 0.02)

    class Slow:
        def __init__(self, **kw):
            self.kw = kw

        def run(self, kind, source, out_dir, stem):
            time.sleep(0.3)
            return {"files": [f"{stem}.480p.mp4"], "seconds": 1.0,
                    "skipped": False}

    monkeypatch.setattr(runner_mod.jobs_media, "MediaJob", Slow)
    media = tmp_path / "media"
    (media / "FF5").mkdir(parents=True)
    (media / "FF5" / "Interview.mp4").write_bytes(b"x")
    (tmp_path / "vault" / "V/Ep").mkdir(parents=True)
    job = {"id": 9, "kind": "proxy-480p",
           "inputs": {"root": "media", "rel_path": "FF5/Interview.mp4",
                      "out_root": "vault", "out_rel": "V/Ep"}}
    dash = BlippingDashboard(job)
    runner = _runner(tmp_path, dash, jobs_media_root=str(media))
    runner._capabilities_fn = lambda: {"ffmpeg": True, "ffprobe": True}
    runner.note_report_reply({"commands": {"jobs": {"offered": [9]}}})
    runner.tick()
    # More than one: the first raise used to end the thread for the rest of
    # the job, so exactly one beat was ever attempted.
    assert dash.beats > 1
    assert dash.results[-1]["ok"] is True


# ------------------------------------------------- comp-ytdl-jobs-4

class StalledStream:
    """An ffmpeg pipe that produces nothing more and never reaches EOF - a
    share that went away mid-decode. `read` returns only when the process is
    killed."""

    def __init__(self, released: threading.Event):
        self.released = released

    def read(self, size=-1):
        self.released.wait(20)
        return b""

    def close(self):
        pass


class ClosedStream:
    def readline(self):
        return ""

    def close(self):
        pass


class StalledProc:
    def __init__(self, released: threading.Event):
        self.released = released
        self.stdout = StalledStream(released)
        self.stderr = ClosedStream()
        self.returncode = None
        self.killed = False

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -9
        self.released.set()


def test_a_child_that_stops_producing_output_still_hears_a_cancel(monkeypatch):
    """`BufferedReader.read(1 MiB)` returns short only at EOF, so the old
    loop was parked INSIDE the read: a cancel, a fleet halt, a shutdown and
    the 1800 s ceiling were all unreachable, while the beater kept renewing
    the lease and the dashboard saw a healthy job for ever."""
    monkeypatch.setattr(jobs_media, "POLL_SECONDS", 0.02)
    released = threading.Event()
    proc = StalledProc(released)
    asked = {"n": 0}

    def should_stop():
        asked["n"] += 1
        return "cancelled" if asked["n"] > 2 else ""

    outcome: dict = {}

    def call():
        try:
            jobs_media._read_pcm(["ffmpeg"], should_stop=should_stop,
                                 popen=lambda *a, **k: proc)
        except BaseException as exc:                            # noqa: BLE001
            outcome["error"] = exc

    worker = threading.Thread(target=call, daemon=True)
    worker.start()
    try:
        worker.join(timeout=10)
        assert not worker.is_alive(), "the decode ignored should_stop"
        assert isinstance(outcome.get("error"), jobs_media.MediaJobError)
        assert str(outcome["error"]) == "cancelled"
        assert proc.killed is True
    finally:
        released.set()


# ------------------------------------------------- comp-ytdl-jobs-5

def _clip(tmp_path) -> tuple[Path, Path]:
    source = tmp_path / "Interview.mov"
    source.write_bytes(b"x")
    return source, tmp_path / "Interview.m4a"


def test_a_stopped_aac_copy_takes_its_partial_with_it(tmp_path, monkeypatch):
    """Rule 2: nothing that will not be finished stays on disk. A cancelled
    batch used to leave a full-length .m4a.partial per clip in the vault,
    and no sweep anywhere removes those."""
    source, final = _clip(tmp_path)
    partial = Path(str(final) + jobs_media.PARTIAL_SUFFIX)

    def stopped(cmd, **kw):
        partial.write_bytes(b"half an interview")
        raise jobs_media.MediaJobError("a fleet halt stopped this job")

    monkeypatch.setattr(jobs_media, "_run_ffmpeg", stopped)
    job = jobs_media.MediaJob(ffmpeg_path="ffmpeg")
    with pytest.raises(jobs_media.MediaJobError):
        job._attempt_copy(source, final, 12.0)
    assert not partial.exists()


# ------------------------------------------------- comp-ytdl-jobs-6

def test_a_finished_file_that_could_not_be_published_is_kept(tmp_path,
                                                             monkeypatch):
    """The message an admin reads off the job row says the file "is still
    there as <name>.partial". It has to BE there - and finished work is worth
    keeping anyway: an os.replace that lost to a share holding the target open
    is a transient the next attempt can win."""
    source, final = _clip(tmp_path)
    partial = Path(str(final) + jobs_media.PARTIAL_SUFFIX)

    def refuse(src, dst):
        raise OSError("the file is in use by another process")

    monkeypatch.setattr(jobs_media.os, "replace", refuse)
    job = jobs_media.MediaJob(ffmpeg_path="ffmpeg")
    with pytest.raises(jobs_media.MediaJobError) as caught:
        job._with_partial(final, source,
                          lambda p: p.write_bytes(b"a finished proxy"))
    assert partial.name in str(caught.value)
    assert partial.exists(), "the message names a file the next line deleted"
    # And the in-process claim was still let go, so the retry can take it.
    assert jobs_media.claim_partial(partial) is True
    jobs_media.release_partial(partial)
