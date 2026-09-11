"""Bug hunt 2026-09-11b, territory comp-ytdl-jobs (CR-254).

Every test here fails at f1eeb42 and passes after the fix beside it. This
hunt was OF the CR-237 fix pass, so most of these pin the state that pass
created rather than the state it found.

  * comp-ytdl-jobs-1: a standing refusal must retire when the fleet stops
    being offered anything, or a rollback the admin abandons alarms every
    machine for the life of its process.
  * comp-ytdl-jobs-2: `ensure()`'s own failure returns must carry the cause
    and the counter, not just `ensure_ffmpeg_pair()`'s.
  * comp-ytdl-jobs-4: a stalled STDERR drain carries no audio, and a recorded
    read error must keep its own message.
  * comp-ytdl-jobs-5: the SAME-vs-OLDER refusal compare, which changed
    fleet-visible behaviour with no test at all.
  * comp-ytdl-jobs-6: the local stops must be bounded, and an admin's cancel
    must never be the entry that is truncated away.
  * wire-5 / dash-api-4: a 403 on the heartbeat or the result is an account
    bar, not a blip: stop, and say so.
  * res-companion-4 (companion half): "this machine cannot keep its
    crash-loop counter" must leave the machine.
"""
from __future__ import annotations

import logging
import threading

import pytest

from ccsync_companion import config as config_mod
from ccsync_companion import jobs_media
from ccsync_companion import jobs_runner as runner_mod
from ccsync_companion import sidecar_tools
from ccsync_companion import upgrade as upgrade_mod
from ccsync_companion import ytdl_executor
from ccsync_companion import ytdlp_manager

from test_jobs_runner import FakeDashboard, FakeIdle, cfg


# --------------------------------------------------------------------------
# comp-ytdl-jobs-1 / comp-ytdl-jobs-5 -- the standing refusal
# --------------------------------------------------------------------------

def _manager(tmp_path):
    return upgrade_mod.UpgradeManager({"dashboard_url": "http://dash.example"},
                                      floor_file=tmp_path / "upgrade_floor.json")


def _older_version() -> str:
    parts = [int(p) for p in config_mod.VERSION.split(".")[:3]]
    while len(parts) < 3:
        parts.append(0)
    for index in range(len(parts) - 1, -1, -1):
        if parts[index] > 0:
            parts[index] -= 1
            return ".".join(str(p) for p in parts)
    raise AssertionError("VERSION has no older neighbour")


def test_a_refusal_of_an_older_build_survives_and_the_running_one_does_not(tmp_path):
    """comp-ytdl-jobs-5: the SAME-vs-OLDER rule the CR-237 fix introduced was
    unasserted in all 827 tests, so a revert to the tolerant compare would
    have stayed green."""
    manager = _manager(tmp_path)
    manager._note_refusal(_older_version(), "below the downgrade floor")
    record = manager.refusal()
    assert record is not None and record["version"] == _older_version()
    manager._note_refusal(config_mod.VERSION, "below the downgrade floor")
    assert manager.refusal() is None


def test_a_reply_with_no_offer_retires_the_standing_refusal(tmp_path):
    """comp-ytdl-jobs-1: the admin gives up on the rollback and makes the
    current build current again. No offer is ever made to a machine already
    running it, so `_accept_offer` never runs again and the refusal had no
    remaining way out - the whole fleet stayed `[ REFUSING 0.9.65 ]`."""
    manager = _manager(tmp_path)
    manager._note_refusal(_older_version(), "below the downgrade floor")
    assert manager.refusal() is not None
    for _ in range(3):
        manager.note_report_response({"ok": True})
    assert manager.refusal() is None
    assert upgrade_mod.upgrade_report({}, 1, manager.refusal())[
        "refused_version"] is None


def test_a_reply_that_still_carries_the_refused_offer_keeps_the_refusal(tmp_path):
    """The other direction: while the rollback IS still current the offer
    keeps arriving, is refused again, and the chip must stay lit."""
    manager = _manager(tmp_path)
    offer = {"version": _older_version(), "url": "http://dash.example/x.exe",
             "sha256": "a" * 64}
    manager.note_report_response({"ok": True, "upgrade": offer})
    assert manager.refusal() is not None
    assert manager.refusal()["version"] == _older_version()


def test_an_unreadable_reply_does_not_retire_the_refusal(tmp_path):
    """"the reply was not a dict" is not "nothing is being refused"."""
    manager = _manager(tmp_path)
    manager._note_refusal(_older_version(), "below the downgrade floor")
    manager.note_report_response("not a dict")
    manager.note_report_response({"ok": True, "upgrade": {"version": "9.9.9"}})
    assert manager.refusal() is not None


# --------------------------------------------------------------------------
# res-companion-4 (companion half) -- the swallowed state write leaves the box
# --------------------------------------------------------------------------

def test_the_swallowed_state_writes_ride_the_upgrade_report(monkeypatch):
    monkeypatch.setattr(upgrade_mod, "_WRITE_FAILURES", 3, raising=False)
    block = upgrade_mod.upgrade_report({}, 1, None)
    assert block["state_write_failures"] == 3
    monkeypatch.setattr(upgrade_mod, "_WRITE_FAILURES", 0, raising=False)
    assert upgrade_mod.upgrade_report({}, 1, None)["state_write_failures"] == 0


# --------------------------------------------------------------------------
# comp-ytdl-jobs-2 -- ensure()'s own failure returns
# --------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clean_sidecar_counters():
    sidecar_tools.reset_failures()
    yield
    sidecar_tools.reset_failures()


def _downloader_on(monkeypatch, tmp_path, *, tools_dir=None, unblock=False):
    monkeypatch.setattr(ytdlp_manager, "youtube_enabled", lambda _cfg=None: True)
    monkeypatch.setattr(ytdlp_manager, "tools_dir", lambda: tmp_path / "tools")
    monkeypatch.setattr(ytdlp_manager, "ensure_tools_dir", lambda: tools_dir)
    monkeypatch.setattr(sidecar_tools, "_free_space_ok", lambda _d: True)
    monkeypatch.setattr(sidecar_tools, "is_installed", lambda _t: False)
    monkeypatch.setattr(sidecar_tools, "_editor_has_own_ffmpeg", lambda *a, **k: False)
    monkeypatch.setattr(sidecar_tools, "_editor_has_own_deno", lambda: False)
    monkeypatch.setattr(sidecar_tools, "_unblock_enabled", lambda: unblock)
    monkeypatch.setattr(sidecar_tools, "pinned_assets", lambda: {
        "ffmpeg": ("https://example.invalid/ffmpeg.gz", "0" * 64, "gz"),
        "ffprobe": ("https://example.invalid/ffprobe.gz", "0" * 64, "gz"),
        "deno": ("https://example.invalid/deno.zip", "0" * 64, "zip"),
    })


def test_a_full_disk_on_a_youtube_machine_reaches_the_editor(tmp_path, monkeypatch):
    """The two commonest failures on a machine with the downloader ON went
    through `ensure()`, whose returns CR-237 never updated: the tray line
    could not appear and the report said nothing."""
    _downloader_on(monkeypatch, tmp_path, tools_dir=None)
    first = sidecar_tools.ensure({})
    second = sidecar_tools.ensure({})
    assert second["action"] == sidecar_tools.ACTION_FAILED
    assert second["failed"]
    assert second["cause"]
    assert second["consecutive_failures"] >= 2
    assert first["consecutive_failures"] == 1
    line = ytdlp_manager.sidecar_warning_line(
        {"sidecar": ytdlp_manager.sidecar_report(second)})
    assert "ffmpeg" in line
    assert "—" not in line


def test_one_pass_is_counted_once_whichever_entry_point_ran(tmp_path, monkeypatch):
    """`ensure()` calls `ensure_ffmpeg_pair()`, which counts the pass. A
    second count there would make the two-pass warning fire on pass one."""
    _downloader_on(monkeypatch, tmp_path, tools_dir=None)
    sidecar_tools.ensure({})
    assert sidecar_tools.consecutive_failures() == 1


def test_a_deno_only_failure_reports_the_streak_it_is_on(tmp_path, monkeypatch):
    """The deno-only arm read the counter AFTER ensure_ffmpeg_pair had reset
    it to 0, so it published `action: failed` with `consecutive_failures: 0`
    and no cause - a failed pass that reads as a clean one. The streak itself
    stays the PAIR's: an ffmpeg that installs fine resets it every pass, which
    is what keeps the "cannot make proxies" line off a machine whose only
    missing tool is the JS runtime."""
    tools = tmp_path / "tools"
    tools.mkdir(parents=True, exist_ok=True)
    _downloader_on(monkeypatch, tmp_path, tools_dir=tools, unblock=True)
    monkeypatch.setattr(sidecar_tools, "is_installed",
                        lambda tool: tool != "deno")
    def _fails(tool, *_a, **_k):
        sidecar_tools._note_cause(tool, "certificate verify failed")
        return False

    monkeypatch.setattr(sidecar_tools, "install_tool", _fails)
    first = sidecar_tools.ensure({})
    second = sidecar_tools.ensure({})
    assert second["action"] == sidecar_tools.ACTION_FAILED
    assert first["consecutive_failures"] == 1
    assert second["consecutive_failures"] == 1
    assert second["failed"] == ["deno"]
    assert second["cause"]


# --------------------------------------------------------------------------
# comp-ytdl-jobs-4 -- the drain liveness check
# --------------------------------------------------------------------------

class _StuckStream:
    def __init__(self, release):
        self.release = release

    def read(self, _size=None):
        self.release.wait(30)
        return b""

    def readline(self):
        self.release.wait(30)
        return b""

    def close(self):
        pass


class _ClosedStream:
    def __init__(self, chunks=(b"pcm",)):
        self.chunks = list(chunks)

    def read(self, _size=None):
        return self.chunks.pop(0) if self.chunks else b""

    def readline(self):
        return self.chunks.pop(0) if self.chunks else b""

    def close(self):
        pass


class _FailingStream:
    def read(self, _size=None):
        raise OSError("the share went away")

    def close(self):
        pass


class _ExitedChild:
    returncode = 0

    def __init__(self, stdout, stderr):
        self.stdout = stdout
        self.stderr = stderr
        self.killed = False

    def poll(self):
        return 0

    def wait(self, timeout=None):
        return 0

    def terminate(self):
        self.killed = True

    def kill(self):
        self.killed = True


def test_a_stalled_stderr_drain_does_not_fail_a_complete_decode(monkeypatch):
    """stderr carries no audio: a pipe held open by an inherited handle used
    to fail a job whose PCM buffer was complete, and the fleet then retried
    it on another machine for ever."""
    release = threading.Event()
    monkeypatch.setattr(jobs_media, "DRAIN_JOIN_SECONDS", 0.2)
    monkeypatch.setattr(jobs_media, "STDERR_JOIN_SECONDS", 0.2)
    child = _ExitedChild(_ClosedStream(), _StuckStream(release))
    try:
        code, pcm, _err = jobs_media._read_pcm(
            ["ffmpeg"], popen=lambda *a, **k: child)
    finally:
        release.set()
    assert code == 0
    assert pcm == b"pcm"
    assert child.killed is False


def test_a_real_read_error_keeps_its_own_message(monkeypatch):
    """The liveness raise sat ahead of `if failure:`, so a genuine decode
    error on a stalled share was reported as the generic sentence."""
    release = threading.Event()
    monkeypatch.setattr(jobs_media, "DRAIN_JOIN_SECONDS", 0.2)
    monkeypatch.setattr(jobs_media, "STDERR_JOIN_SECONDS", 0.2)
    child = _ExitedChild(_FailingStream(), _StuckStream(release))
    try:
        with pytest.raises(jobs_media.MediaJobError) as caught:
            jobs_media._read_pcm(["ffmpeg"], popen=lambda *a, **k: child)
    finally:
        release.set()
    assert "the share went away" in str(caught.value)
    assert child.killed is True


def test_a_stalled_pcm_drain_still_fails_the_job(monkeypatch):
    """CR-237's own property, kept: truncated peaks published under the final
    name are worse than no peaks."""
    release = threading.Event()
    monkeypatch.setattr(jobs_media, "DRAIN_JOIN_SECONDS", 0.2)
    monkeypatch.setattr(jobs_media, "STDERR_JOIN_SECONDS", 0.2)
    child = _ExitedChild(_StuckStream(release), _ClosedStream((b"",)))
    try:
        with pytest.raises(jobs_media.MediaJobError) as caught:
            jobs_media._read_pcm(["ffmpeg"], popen=lambda *a, **k: child)
    finally:
        release.set()
    assert "read to the end" in str(caught.value)
    assert child.killed is True


# --------------------------------------------------------------------------
# comp-ytdl-jobs-6 / wire-5 -- the runner
# --------------------------------------------------------------------------

def _runner(tmp_path, dash=None, **over):
    return runner_mod.JobRunner(
        cfg(tmp_path, **over),
        request_fn=(dash or FakeDashboard()).request,
        identity_token_fn=lambda: "identity",
        capabilities_fn=lambda: {"whisper": True},
        idle_probe=FakeIdle(900),
        resolve_running_fn=lambda: False,
        halted_fn=lambda: False,
        machine_name="EDIT-PC",
    )


def test_an_admin_cancel_is_never_the_entry_that_is_truncated(tmp_path):
    """comp-ytdl-jobs-6: 16 local stops that never got a result used to fill
    every slot, and the fleet's [ CANCEL ] then did nothing, silently."""
    r = _runner(tmp_path)
    for stale in range(1000, 1030):
        r._note_local_cancel(stale)
    r.note_report_reply({"commands": {"jobs": {"cancel": [4242]}}})
    assert r._cancel_requested(4242) is True
    assert len(r._cancel) <= 16
    assert len(r._local_cancel) <= 16


def test_the_newest_local_stop_is_the_one_that_is_kept(tmp_path):
    """A stop the editor pressed a second ago outranks one from last week."""
    r = _runner(tmp_path)
    for stale in range(1, 40):
        r._note_local_cancel(stale)
    assert 39 in r._local_cancel
    assert 1 not in r._local_cancel


def test_a_403_on_the_heartbeat_stops_the_job(tmp_path):
    """wire-5 / dash-api-4: dash-api-6's account bar gates the heartbeat as
    well as the claim. Only 410 used to stop the work, so a suspended
    editor's machine ran the job to the end and wrote into the shared
    vault."""
    dash = FakeDashboard()
    dash.heartbeat_status = 403
    r = _runner(tmp_path, dash=dash)
    assert r._heartbeat(7, 0.5) is False
    assert r.status()["gate"]["reason"]
    assert "not being accepted" in r.status()["gate"]["reason"]
    assert "—" not in r.status()["gate"]["reason"]


def test_a_410_on_the_heartbeat_is_still_not_a_credential_problem(tmp_path):
    dash = FakeDashboard()
    dash.heartbeat_status = 410
    r = _runner(tmp_path, dash=dash)
    assert r._heartbeat(7, None) is False
    assert "not being accepted" not in r.status()["gate"]["reason"]


def test_a_500_on_the_heartbeat_is_still_a_blip(tmp_path):
    dash = FakeDashboard()
    dash.heartbeat_status = 503
    r = _runner(tmp_path, dash=dash)
    assert r._heartbeat(7, None) is True


def test_a_refused_result_is_recorded_rather_than_swallowed(tmp_path, caplog):
    class Refusing(FakeDashboard):
        def request(self, method, url, body, headers, timeout):
            if url.endswith("/result"):
                return 403, {"detail": "this account is suspended"}
            return super().request(method, url, body, headers, timeout)

    r = _runner(tmp_path, dash=Refusing())
    with caplog.at_level(logging.WARNING, logger="ccsync.jobs"):
        r._post_result(7, True, result={})
    assert any("403" in rec.getMessage() for rec in caplog.records)
    assert "not being accepted" in r.status()["gate"]["reason"]


# --------------------------------------------------------------------------
# Hand-off wave (2026-09-11b)
#   * ytdl-web-3's third door: the `X-CCSync-Machine` header routes_fleet
#     already accepts, so the id survives a body or a query string that does
#     not reach the route.
#   * wire-5's surfacing half: a refused fleet credential has to close the
#     gate it contradicts, or Settings prints "Taking fleet work" and drops
#     the sentence that says the work is not being accepted.
# --------------------------------------------------------------------------

class _HeaderRecordingDeps:
    dashboard_url = "http://dash.example:8480"
    token = "t"

    def __init__(self) -> None:
        self.calls: list = []

    def identity_token(self):
        return "identity"

    def request(self, method, url, body, headers, timeout):
        self.calls.append((method, url, body, dict(headers or {})))
        return 200, {"ok": True, "clips": []}


def _ytdl_client(monkeypatch, machine_id="mach-abc"):
    monkeypatch.setattr(ytdl_executor, "_this_machine_id", lambda: machine_id)
    deps = _HeaderRecordingDeps()
    return ytdl_executor.FleetClient(deps, "ruskin"), deps


def test_every_ytdl_fleet_call_carries_the_machine_header(monkeypatch):
    """routes_fleet._machine_of reads three doors and the header is the
    shape-independent one. The body field alone is lost the moment a call
    goes out without a body."""
    client, deps = _ytdl_client(monkeypatch)
    client.heartbeat(88)
    client.manifest(88)
    client.clip_status(88, "abcdefghijk", "done", filepath_rel="a.mp4")
    assert deps.calls, "no fleet call was made"
    for _method, _url, _body, headers in deps.calls:
        assert headers.get("X-CCSync-Machine") == "mach-abc"


def test_a_machine_with_no_id_sends_no_machine_header(monkeypatch):
    """OPTIONAL both ways: absent must keep meaning today's per-editor
    answer, and an empty header value is not the same as no header."""
    client, deps = _ytdl_client(monkeypatch, machine_id="")
    client.heartbeat(88)
    assert "X-CCSync-Machine" not in deps.calls[0][3]


def test_a_machine_id_that_is_not_header_safe_is_left_out(monkeypatch):
    """An id an editor replaced by hand can hold a newline or a non-ASCII
    character; http.client raises on both, and a claim that dies in the
    transport is worse than a claim the server answers per editor."""
    client, deps = _ytdl_client(monkeypatch, machine_id="mach\r\nabc")
    client.heartbeat(88)
    assert "X-CCSync-Machine" not in deps.calls[0][3]
    client2, deps2 = _ytdl_client(monkeypatch, machine_id="mach-\u00e9")
    client2.heartbeat(88)
    assert "X-CCSync-Machine" not in deps2.calls[0][3]


def test_a_refused_credential_closes_the_gate_it_contradicts(tmp_path):
    """wire-5's surfacing half: the runner starts at STATE_NOTHING_OFFERED,
    whose verdict is "taking work" - so Settings rendered "Taking fleet work"
    and threw the reason away, which is where the credential sentence lived.
    A door that answers 403 to claim, heartbeat and result alike is not a
    machine that is taking work."""
    dash = FakeDashboard()
    dash.heartbeat_status = 403
    r = _runner(tmp_path, dash=dash)
    assert r.status()["gate"]["taking_work"] is True
    r._heartbeat(7, 0.5)
    gate = r.status()["gate"]
    assert gate["taking_work"] is False
    assert "not being accepted" in gate["reason"]
    assert "ready for fleet work" not in gate["reason"]
    assert "\u2014" not in gate["reason"]


def test_a_call_that_gets_through_reopens_the_gate(tmp_path):
    """Sticky within the process, cleared by the next call that lands: an
    account un-suspended must not need a tray restart to say so."""
    dash = FakeDashboard()
    dash.heartbeat_status = 403
    r = _runner(tmp_path, dash=dash)
    r._heartbeat(7, 0.5)
    assert r.status()["gate"]["taking_work"] is False
    dash.heartbeat_status = 200
    r._heartbeat(7, 0.5)
    gate = r.status()["gate"]
    assert gate["taking_work"] is True
    assert "not being accepted" not in gate["reason"]


def test_a_closed_gate_keeps_its_own_reason_and_gains_the_note(tmp_path):
    """The refusal never replaces a reason the editor can act on: somebody at
    the keyboard is still why this machine is not transcoding."""
    dash = FakeDashboard()
    dash.heartbeat_status = 403
    r = _runner(tmp_path, dash=dash)
    r._state = runner_mod.STATE_USER_ACTIVE
    r._heartbeat(7, 0.5)
    reason = r.status()["gate"]["reason"]
    assert "Somebody is at this computer" in reason
    assert "not being accepted" in reason
    assert r.status()["gate"]["taking_work"] is False
