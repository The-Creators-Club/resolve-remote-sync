"""Bug hunt 2026-09-11, territory comp-ytdl-jobs (CR-237).

Every test here fails at 40f931a and passes after the fix beside it.

  * comp-ytdl-jobs-2: a report reply must not wipe a stop the person at this
    machine asked for. The dashboard is never told about a local stop, and the
    common reply carries no `jobs` block at all.
  * comp-ytdl-jobs-3: a sidecar install that keeps failing must carry its
    CAUSE, be logged at WARNING whatever the YouTube flag says, and reach the
    report through the block that already exists.
  * comp-ytdl-jobs-4: `_read_pcm` must not build peaks out of a buffer its
    drain thread is still writing to.
  * comp-ytdl-jobs-5: the gate sentence must not carry the previous tick's
    note into a state that never set one.
  * ytdl-web-3 (companion half): the heartbeat, manifest and clip-status calls
    must name THIS COMPUTER, so a woken-up laptop cannot keep renewing a lease
    that now belongs to the editor's other machine.
  * res-companion-4 (upgrade half): a swallowed state write is a WARNING and a
    counter, not a DEBUG line.
"""
from __future__ import annotations

import logging
import threading
import time
from urllib.parse import urlparse

import pytest

from ccsync_companion import jobs_media
from ccsync_companion import jobs_runner as runner_mod
from ccsync_companion import sidecar_tools
from ccsync_companion import upgrade as upgrade_mod
from ccsync_companion import ytdl_executor
from ccsync_companion import ytdlp_manager

from test_jobs_runner import FakeDashboard, FakeIdle, cfg


# --------------------------------------------------------------------------
# comp-ytdl-jobs-2 -- a local stop survives a report reply
# --------------------------------------------------------------------------

def _runner(tmp_path, **over):
    return runner_mod.JobRunner(
        cfg(tmp_path, **over),
        request_fn=FakeDashboard().request,
        identity_token_fn=lambda: "identity",
        capabilities_fn=lambda: {"whisper": True},
        idle_probe=FakeIdle(900),
        resolve_running_fn=lambda: False,
        halted_fn=lambda: False,
        machine_name="EDIT-PC",
    )


def test_a_report_reply_with_no_jobs_block_does_not_wipe_a_local_stop(tmp_path):
    """The commonest reply of all -- an idle fleet's -- used to erase the
    tray's [ STOP ] before the job thread's next 5 s poll ever read it."""
    r = _runner(tmp_path)
    r._job = {"id": 11, "kind": "whisper"}
    assert r.stop_current() is True

    r.note_report_reply({"commands": {}})

    assert r._cancel_requested(11) is True


def test_a_report_reply_carrying_other_cancels_keeps_the_local_one(tmp_path):
    r = _runner(tmp_path)
    r._job = {"id": 11, "kind": "whisper"}
    r.stop_current()

    r.note_report_reply({"commands": {"jobs": {"cancel": [12, 13]}}})

    assert r._cancel_requested(11) is True
    assert r._cancel_requested(12) is True


def test_the_local_stop_retires_once_the_result_is_posted(tmp_path):
    """Or a number the dashboard reuses after a rebuild is cancelled by a
    stop somebody asked for last week."""
    r = _runner(tmp_path)
    r._job = {"id": 11, "kind": "whisper"}
    r.stop_current()
    r._post_result(11, False, runner_mod.CANCELLED_ERROR, retryable=False)

    r.note_report_reply({"commands": {}})

    assert r._cancel_requested(11) is False


# --------------------------------------------------------------------------
# comp-ytdl-jobs-5 -- the gate note belongs to the tick that set it
# --------------------------------------------------------------------------

def test_a_halt_does_not_inherit_the_previous_ticks_gate_note(tmp_path):
    halted = {"now": False}
    r = runner_mod.JobRunner(
        cfg(tmp_path),
        request_fn=FakeDashboard().request,
        identity_token_fn=lambda: "identity",
        capabilities_fn=lambda: {"whisper": True},
        idle_probe=FakeIdle(900),
        resolve_running_fn=lambda: False,
        halted_fn=lambda: halted["now"],
        blocked_fn=lambda: "Indexing b-roll",
        machine_name="EDIT-PC",
    )
    assert r._gate() == runner_mod.STATE_LOCAL_WORK
    assert "Indexing b-roll" in r.status()["gate"]["reason"]

    halted["now"] = True
    assert r._gate() == runner_mod.STATE_HALTED
    reason = r.status()["gate"]["reason"]
    assert "Indexing b-roll" not in reason


# --------------------------------------------------------------------------
# comp-ytdl-jobs-4 -- a drain that has not reached EOF is not an answer
# --------------------------------------------------------------------------

class _StuckStream:
    """A pipe that never reaches EOF: the share that went away with the read
    end still open."""

    def __init__(self, release: threading.Event) -> None:
        self._release = release
        self._first = True

    def read(self, _size=None):
        if self._first:
            self._first = False
            return b"\x00\x01" * 16
        # Blocks past the join's timeout, exactly as the real one does.
        self._release.wait()
        return b""

    def readline(self, *_a):
        self._release.wait()
        return ""

    def close(self):
        pass


class _ExitedChild:
    def __init__(self, release: threading.Event) -> None:
        self.stdout = _StuckStream(release)
        self.stderr = _StuckStream(release)
        self.returncode = 0
        self.killed = False

    def poll(self):
        return 0

    def wait(self, timeout=None):
        return 0

    def terminate(self):
        self.killed = True

    def kill(self):
        self.killed = True


def test_a_pcm_drain_that_never_reaches_eof_fails_the_job(tmp_path, monkeypatch):
    """Truncated peaks published under the final name are cached by Timeline
    Cards for ever: a short answer that reports success is the worst one."""
    release = threading.Event()
    child = _ExitedChild(release)
    # The join must not take 30 real seconds to prove the point.
    monkeypatch.setattr(jobs_media, "DRAIN_JOIN_SECONDS", 0.2)
    try:
        with pytest.raises(jobs_media.MediaJobError) as caught:
            jobs_media._read_pcm(["ffmpeg"], popen=lambda *a, **k: child)
    finally:
        release.set()
    assert "read to the end" in str(caught.value)
    assert child.killed is True


# --------------------------------------------------------------------------
# comp-ytdl-jobs-3 -- a sidecar that cannot install says WHY, to a human
# --------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clean_sidecar_counters():
    sidecar_tools.reset_failures()
    yield
    sidecar_tools.reset_failures()


def _no_network_opener(*_args, **_kwargs):
    raise OSError("certificate verify failed: unable to get local issuer certificate")


def _pair_with_no_network(tmp_path, monkeypatch):
    monkeypatch.setattr(ytdlp_manager, "tools_dir", lambda: tmp_path / "tools")
    monkeypatch.setattr(ytdlp_manager, "ensure_tools_dir",
                        lambda: _mk(tmp_path / "tools"))
    monkeypatch.setattr(sidecar_tools, "_free_space_ok", lambda _d: True)
    monkeypatch.setattr(sidecar_tools, "is_installed", lambda _t: False)
    monkeypatch.setattr(sidecar_tools, "_editor_has_own_ffmpeg",
                        lambda *a, **k: False)
    monkeypatch.setattr(sidecar_tools, "pinned_assets", lambda: {
        "ffmpeg": ("https://example.invalid/ffmpeg.gz", "0" * 64, "gz"),
        "ffprobe": ("https://example.invalid/ffprobe.gz", "0" * 64, "gz"),
        "deno": ("https://example.invalid/deno.zip", "0" * 64, "zip"),
    })
    return sidecar_tools.ensure_ffmpeg_pair({}, github_open=_no_network_opener)


def _mk(path):
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_a_failed_sidecar_install_carries_its_cause(tmp_path, monkeypatch):
    """"could not install ffmpeg" is the line that reached an admin and told
    them nothing: the Mac in the field cannot verify GitHub's certificate."""
    status = _pair_with_no_network(tmp_path, monkeypatch)
    assert status["action"] == sidecar_tools.ACTION_FAILED
    assert "certificate verify failed" in status["cause"]
    assert "certificate verify failed" in status["message"]


def test_a_repeated_sidecar_failure_is_a_warning_whatever_the_flag_says(
        tmp_path, monkeypatch, caplog):
    _pair_with_no_network(tmp_path, monkeypatch)
    with caplog.at_level(logging.WARNING, logger="ccsync.sidecar"):
        status = _pair_with_no_network(tmp_path, monkeypatch)
    assert status["consecutive_failures"] >= 2
    assert any("consecutive passes" in rec.getMessage()
               for rec in caplog.records)


def test_the_sidecar_verdict_rides_the_report_block_that_already_exists():
    """`sync_guard.ytdlp.sidecar` (comp-ytdl-jobs-3): CYT-7's pattern, as an
    OPTIONAL key, so no new report section and no dashboard change is needed
    for the fact to leave the machine."""
    block = ytdlp_manager.status_report({
        "ok": True, "version": "2026.08.11", "action": ytdlp_manager.ACTION_NONE,
        "message": "fine", "checked_at": time.time(),
        "sidecar": {"ok": False, "action": sidecar_tools.ACTION_FAILED,
                    "failed": ["ffmpeg", "ffprobe"],
                    "cause": "certificate verify failed",
                    "consecutive_failures": 4,
                    "message": "could not install ffmpeg, ffprobe",
                    "checked_at": time.time()},
    })
    assert block["sidecar"]["cause"] == "certificate verify failed"
    assert block["sidecar"]["failed"] == ["ffmpeg", "ffprobe"]
    assert block["sidecar"]["consecutive_failures"] == 4
    # A check that never ran is not a check that passed.
    assert "sidecar" not in ytdlp_manager.status_report(
        {"ok": True, "action": ytdlp_manager.ACTION_NONE})


def test_the_sidecar_warning_line_waits_for_a_second_failed_pass():
    """One GitHub blip is not a sentence an editor needs; a machine that has
    silently stopped taking media work is."""
    quiet = ytdlp_manager.sidecar_warning_line(
        {"sidecar": {"action": sidecar_tools.ACTION_FAILED,
                     "consecutive_failures": 1, "cause": "boom"}})
    assert quiet == ""
    line = ytdlp_manager.sidecar_warning_line(
        {"sidecar": {"action": sidecar_tools.ACTION_FAILED,
                     "consecutive_failures": 3,
                     "cause": "certificate verify failed"}})
    assert "ffmpeg" in line and "certificate verify failed" in line
    assert "—" not in line


# --------------------------------------------------------------------------
# ytdl-web-3 (companion half) -- every fleet call names THIS COMPUTER
# --------------------------------------------------------------------------

class _RecordingDeps:
    dashboard_url = "http://dash.example:8480"
    token = "t"

    def __init__(self) -> None:
        self.calls: list = []

    def identity_token(self):
        return "identity"

    def request(self, method, url, body, headers, timeout):
        self.calls.append((method, url, body))
        if urlparse(url).path.endswith("/download-manifest"):
            return 200, {"clips": []}
        return 200, {"ok": True}


def _client(monkeypatch, machine_id="mach-abc"):
    monkeypatch.setattr(ytdl_executor, "_this_machine_id", lambda: machine_id)
    deps = _RecordingDeps()
    return ytdl_executor.FleetClient(deps, "ruskin"), deps


def test_the_heartbeat_names_the_machine(monkeypatch):
    client, deps = _client(monkeypatch)
    client.heartbeat(88)
    assert deps.calls[0][2]["machine_id"] == "mach-abc"
    assert deps.calls[0][2]["editor"] == "ruskin"


def test_the_manifest_fetch_names_the_machine(monkeypatch):
    client, deps = _client(monkeypatch)
    client.manifest(88)
    assert "machine_id=mach-abc" in deps.calls[0][1]


def test_a_clip_status_names_the_machine(monkeypatch):
    client, deps = _client(monkeypatch)
    client.clip_status(88, "abcdefghijk", "done", filepath_rel="a.mp4")
    assert deps.calls[0][2]["machine_id"] == "mach-abc"


def test_a_machine_with_no_id_sends_no_field(monkeypatch):
    """OPTIONAL on the wire: absent must keep meaning today's per-editor
    answer, or a companion that cannot read machine.json starts getting 410s
    mid-download."""
    client, deps = _client(monkeypatch, machine_id="")
    client.heartbeat(88)
    client.clip_status(88, "abcdefghijk", "done")
    client.manifest(88)
    assert "machine_id" not in deps.calls[0][2]
    assert "machine_id" not in deps.calls[1][2]
    assert "?" not in deps.calls[2][1]


# --------------------------------------------------------------------------
# res-companion-4 (upgrade half) -- a state write that fails is news
# --------------------------------------------------------------------------

def test_a_swallowed_state_write_is_a_warning_and_a_count(tmp_path, caplog,
                                                          monkeypatch):
    before = upgrade_mod.write_failures()
    monkeypatch.setattr(upgrade_mod.os, "replace",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("no space left")))
    with caplog.at_level(logging.WARNING, logger="ccsync.upgrade"):
        assert upgrade_mod._write_json(tmp_path / "state.json", {"a": 1}) is False
    assert upgrade_mod.write_failures() == before + 1
    assert any(rec.levelno >= logging.WARNING for rec in caplog.records)


def test_note_version_start_says_so_when_it_could_not_record_the_start(
        tmp_path, caplog, monkeypatch):
    """A crash-loop counter that cannot be written means every start looks
    like the first one: APP-5's revert can never fire."""
    monkeypatch.setattr(upgrade_mod, "_write_json", lambda *a, **k: False)
    with caplog.at_level(logging.WARNING, logger="ccsync.upgrade"):
        upgrade_mod.note_version_start(tmp_path / "state")
    assert any("crash-loop guard" in rec.getMessage() for rec in caplog.records)
