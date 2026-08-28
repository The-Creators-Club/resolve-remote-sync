"""SYS-7 (resilience sweep 2026-08-28): the diagnostics bundle gets a route.

`build_diagnostics()` was clipboard-only, so the one artefact that answers "why
is my footage not syncing" existed only if a non-technical editor performed a
manual step at the right moment, on the machine that was broken -- and went
silently to the log instead if any CCSync window happened to be open.

Three triggers are pinned here (the button, a lane falling into `error`, an
admin's ask), plus the three properties that keep the channel from becoming its
own problem: never without a verified identity, at most one upload per lane per
hour PERSISTED ACROSS RESTARTS, and one admin ask applied exactly once however
many replies carry it.

Nothing here touches a real dashboard, rclone, Syncthing or Tk.
"""
from __future__ import annotations

import json
import platform
import threading
from typing import Any

from ccsync_companion import reporter as reporter_mod
from ccsync_companion.app import (
    DIAGNOSTICS_LANE_ERROR_INTERVAL_SECONDS, DIAGNOSTICS_STATE_FILENAME,
    CompanionApp,
)
from ccsync_companion.reporter import DashboardReporter
from ccsync_companion.sync.base import STATE_ERROR, STATE_IDLE, LaneStatus


# ------------------------------------------------- reporter.post_diagnostics

def _reporter(posts: list, **cfg_overrides) -> DashboardReporter:
    cfg = {
        "editor_name": "owen",
        "dashboard_url": "http://dash.example.com",
        "dashboard_token": "tok123",
    }
    cfg.update(cfg_overrides)

    def fake_post(url, data, headers, timeout):
        posts.append((url, data, headers, timeout))
        return {}

    return DashboardReporter(lambda: [], cfg, http_post=fake_post,
                             get_machine_id=lambda: "mid-7")


def test_post_diagnostics_uses_the_report_channels_url_and_headers():
    posts: list = []
    rep = _reporter(posts)
    assert rep.post_diagnostics("=== CCSYNC DIAGNOSTICS ===", "button") is True
    url, body, headers, _timeout = posts[0]
    assert url == "http://dash.example.com/api/v1/diagnostics"
    assert headers["X-CCSync-Token"] == "tok123"
    assert body["editor_name"] == "owen"
    assert body["machine"] == platform.node()
    assert body["machine_id"] == "mid-7"
    assert body["trigger"] == "button"
    assert body["at"]
    assert body["text"] == "=== CCSYNC DIAGNOSTICS ==="


def test_post_diagnostics_sends_the_identity_token_like_post_once_does():
    posts: list = []
    rep = _reporter(posts)
    rep._get_identity_token = lambda: "signed-identity"
    rep.post_diagnostics("x", "button")
    assert posts[0][2]["X-CCSync-Identity"] == "signed-identity"


def test_post_diagnostics_refuses_without_a_verified_identity():
    """A bundle names this machine's paths, its Resolve project and its
    editor's tree: posting one while signed out would file it under whatever
    name happened to be left in config.toml."""
    posts: list = []
    rep = _reporter(posts)
    rep._get_editor_name = lambda: None
    assert rep.post_diagnostics("x", "button") is False
    assert posts == []


def test_post_diagnostics_is_inert_with_no_dashboard_configured():
    posts: list = []
    rep = _reporter(posts, dashboard_url="")
    assert rep.post_diagnostics("x", "button") is False
    assert posts == []


def test_post_diagnostics_cuts_an_enormous_bundle():
    """The wire is sometimes an editor's home uplink, and the dashboard's body
    gate is a 413: a bundle that cannot be posted is a bundle nobody reads."""
    posts: list = []
    rep = _reporter(posts)
    rep.post_diagnostics("z" * (reporter_mod.DIAGNOSTICS_MAX_CHARS + 4096), "button")
    assert len(posts[0][1]["text"]) == reporter_mod.DIAGNOSTICS_MAX_CHARS


# --------------------------------------------------------- the app triggers

def _cfg(tmp_path, **overrides) -> dict[str, Any]:
    root = tmp_path / "root"
    root.mkdir(parents=True, exist_ok=True)
    cfg = {
        "editor_name": "owen",
        "local_root": str(root),
        "canonical_prefix": "P:\\",
        "remote": "creators_club_sftp",
        "remote_root": "/mnt/tank/Creators_Club",
        "active_project": "",
        "log_path": str(tmp_path / "companion.log"),
        "dashboard_url": "",
        "popup_enabled": False,
        "sync_enabled": False,
        "lane_b_enabled": False,
    }
    cfg.update(overrides)
    return cfg


class _Recorder:
    """Stands in for the reporter's upload half."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def __call__(self, text: str, trigger: str = "button") -> bool:
        self.calls.append((text, trigger))
        return True


def _app(tmp_path, identity="owen", **overrides) -> tuple[CompanionApp, _Recorder]:
    app = CompanionApp(_cfg(tmp_path, **overrides))
    app._notify_tray = lambda *a, **kw: None
    app.editor_identity = lambda: identity
    app.build_diagnostics = lambda: "=== CCSYNC DIAGNOSTICS ===\nroot: missing"
    recorder = _Recorder()
    app.reporter.post_diagnostics = recorder
    # Synchronous, so the assertions do not race a daemon thread. The async
    # wrapper is exercised on its own below.
    app._upload_diagnostics_async = lambda trigger: app._upload_diagnostics(trigger)
    return app, recorder


def _state(app) -> dict:
    path = app._diagnostics_state_path()
    if path is None or not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def test_copy_diagnostics_uploads_as_well_as_copying(tmp_path, monkeypatch):
    """The clipboard STAYS: an editor already pasting into a message must not
    have that taken away. The upload is the half that works when they never
    do."""
    app, recorder = _app(tmp_path)
    monkeypatch.setattr("ccsync_companion.ui_dispatch.dispatch", lambda fn: None)
    assert app.copy_diagnostics() is True
    assert [t for _text, t in recorder.calls] == ["button"]


def test_a_window_being_open_no_longer_loses_the_bundle(tmp_path):
    """The worst of the three ways this artefact used to reach nobody: the
    clipboard path needs a Tk root, and the upload does not."""
    app, recorder = _app(tmp_path)
    app._popup_active_lock.acquire()
    try:
        assert app.copy_diagnostics() is False
    finally:
        app._popup_active_lock.release()
    assert [t for _text, t in recorder.calls] == ["button"]


def test_no_upload_at_all_when_nobody_is_signed_in(tmp_path):
    app, recorder = _app(tmp_path, identity=None)
    assert app._upload_diagnostics("button") is False
    assert recorder.calls == []


def test_a_lane_falling_into_error_uploads_once(tmp_path):
    """The TRANSITION, not the state: a machine in error since Tuesday would
    otherwise upload one bundle per report interval for ever."""
    app, recorder = _app(tmp_path)
    states = [LaneStatus(name="lane_a_video_up", state=STATE_IDLE)]
    app.lane_statuses = lambda: states

    app._note_lane_error_diagnostics()
    assert recorder.calls == []

    states[0] = LaneStatus(name="lane_a_video_up", state=STATE_ERROR,
                           last_error="ssh: connect failed")
    app._note_lane_error_diagnostics()
    assert [t for _text, t in recorder.calls] == ["lane_error"]

    # Still in error on the next report cycle: no second bundle.
    app._note_lane_error_diagnostics()
    assert len(recorder.calls) == 1


def test_a_flapping_lane_is_rate_limited_to_one_bundle_an_hour(tmp_path):
    app, recorder = _app(tmp_path)
    state = {"state": STATE_IDLE}
    app.lane_statuses = lambda: [
        LaneStatus(name="lane_b_proxy_down", state=state["state"])]

    state["state"] = STATE_ERROR
    app._note_lane_error_diagnostics()
    state["state"] = STATE_IDLE
    app._note_lane_error_diagnostics()
    state["state"] = STATE_ERROR
    app._note_lane_error_diagnostics()
    assert len(recorder.calls) == 1

    # ...and the limit is a real hour, not a flag: age the stamp and it fires.
    stored = _state(app)
    stored["lanes"]["lane_b_proxy_down"]["sent_at"] -= (
        DIAGNOSTICS_LANE_ERROR_INTERVAL_SECONDS + 60)
    stored["lanes"]["lane_b_proxy_down"]["state"] = STATE_IDLE
    app._write_diagnostics_state(stored)
    app._note_lane_error_diagnostics()
    assert len(recorder.calls) == 2


def test_the_rate_limit_survives_a_restart(tmp_path):
    """Never a memory-only latch (the sweep's rule): the machine this protects
    the dashboard from is a machine that keeps restarting."""
    app, recorder = _app(tmp_path)
    app.lane_statuses = lambda: [
        LaneStatus(name="lane_c_syncthing", state=STATE_ERROR)]
    app._note_lane_error_diagnostics()
    assert len(recorder.calls) == 1

    fresh, fresh_recorder = _app(tmp_path)
    fresh.lane_statuses = lambda: [
        LaneStatus(name="lane_c_syncthing", state=STATE_IDLE)]
    fresh._note_lane_error_diagnostics()
    fresh.lane_statuses = lambda: [
        LaneStatus(name="lane_c_syncthing", state=STATE_ERROR)]
    fresh._note_lane_error_diagnostics()
    assert fresh_recorder.calls == []


def test_a_lane_state_read_that_raises_costs_no_bundle_and_no_traceback(tmp_path):
    app, recorder = _app(tmp_path)

    def boom():
        raise OSError("the lane is gone")

    app.lane_statuses = boom
    app._note_lane_error_diagnostics()
    assert recorder.calls == []


# ------------------------------------------------------- the admin's ask

def _reply(requested_at: str, by: str = "alex") -> dict:
    return {"ok": True, "commands": {"diagnostics": {
        "requested_by": by, "requested_at": requested_at}}}


def test_an_admins_ask_uploads_a_bundle(tmp_path):
    app, recorder = _app(tmp_path)
    app._apply_diagnostics_request(_reply("2026-08-28T10:00:00+00:00"))
    assert [t for _text, t in recorder.calls] == ["admin_request"]


def test_one_ask_is_applied_exactly_once_however_often_it_is_delivered(tmp_path):
    """The dashboard keeps this command standing until the BUNDLE ARRIVES, so
    the `requested_at` comparison is the only thing between one admin click
    and an upload every 30 seconds."""
    app, recorder = _app(tmp_path)
    stamp = "2026-08-28T10:00:00+00:00"
    for _ in range(4):
        app._apply_diagnostics_request(_reply(stamp))
    assert len(recorder.calls) == 1

    # A LATER ask is a later question and is answered.
    app._apply_diagnostics_request(_reply("2026-08-28T11:00:00+00:00"))
    assert len(recorder.calls) == 2


def test_the_applied_ask_survives_a_restart(tmp_path):
    app, _recorder = _app(tmp_path)
    stamp = "2026-08-28T10:00:00+00:00"
    app._apply_diagnostics_request(_reply(stamp))

    fresh, fresh_recorder = _app(tmp_path)
    fresh._apply_diagnostics_request(_reply(stamp))
    assert fresh_recorder.calls == []


def test_a_reply_with_no_diagnostics_command_does_nothing(tmp_path):
    app, recorder = _app(tmp_path)
    for reply in ({}, {"ok": True}, {"commands": {}}, {"commands": {"halt": {}}},
                  "not a dict", None):
        app._apply_diagnostics_request(reply)
    assert recorder.calls == []
    assert _state(app).get("applied_request") is None


def test_the_state_file_lives_beside_the_other_latches(tmp_path):
    app, _recorder = _app(tmp_path)
    app._apply_diagnostics_request(_reply("2026-08-28T10:00:00+00:00"))
    path = app._diagnostics_state_path()
    assert path.name == DIAGNOSTICS_STATE_FILENAME
    assert path.parent.name == "state"
    assert path.exists()
    # ...and no .tmp left behind (tmp + os.replace, like identity.py).
    assert list(path.parent.glob("*.tmp")) == []


def test_an_upload_that_raises_never_reaches_the_reporter_thread(tmp_path):
    """A diagnostics upload must never be the reason anything else stops: the
    dashboard being unreachable is one of the states this bundle describes."""
    app, _recorder = _app(tmp_path)

    def boom(text, trigger="button"):
        raise OSError("dashboard unreachable")

    app.reporter.post_diagnostics = boom
    assert app._upload_diagnostics("button") is False
    app._apply_diagnostics_request(_reply("2026-08-28T10:00:00+00:00"))


def test_the_async_wrapper_really_uploads(tmp_path):
    app = CompanionApp(_cfg(tmp_path))
    app._notify_tray = lambda *a, **kw: None
    app.editor_identity = lambda: "owen"
    app.build_diagnostics = lambda: "bundle"
    recorder = _Recorder()
    app.reporter.post_diagnostics = recorder
    app._upload_diagnostics_async("admin_request")
    for thread in list(threading.enumerate()):
        if thread.name == "ccsync-diagnostics-upload":
            thread.join(timeout=5)
    assert [t for _text, t in recorder.calls] == ["admin_request"]


def test_a_reporter_too_old_to_upload_is_a_log_line_not_a_crash(tmp_path):
    """A lane double or a stub reporter in a test: discoverable from the log
    rather than as a traceback on the reporter thread."""
    app, _recorder = _app(tmp_path)
    app.reporter.post_diagnostics = None
    assert app._upload_diagnostics("button") is False
