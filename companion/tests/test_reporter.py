"""Dashboard reporter tests: payload contract, header/URL handling,
disabled-when-blank behavior, and fault isolation -- in the style of
test_syncthing_lane.py (injected fake HTTP, plus one in-process
http.server fixture exercising the real default_http_post)."""

from __future__ import annotations

import json
import logging
import platform
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from ccsync_companion import config as config_mod
from ccsync_companion import reporter as reporter_mod
from ccsync_companion.reporter import DashboardReporter, default_http_post
from ccsync_companion.sync.base import STATE_ERROR, STATE_SYNCING, LaneStatus


def _cfg(**overrides):
    cfg = {
        "editor_name": "alex",
        "dashboard_url": "http://dash.example.com",
        "dashboard_token": "tok123",
        "dashboard_report_interval": 60,
    }
    cfg.update(overrides)
    return cfg


# -- payload contract -----------------------------------------------


def test_post_once_payload_shape_matches_contract():
    calls = []

    def fake_post(url, data, headers, timeout):
        calls.append((url, data, headers, timeout))
        return {}

    now = datetime(2026, 7, 24, 12, 0, 0, tzinfo=timezone.utc)
    statuses = [
        LaneStatus(
            name="lane_a_video_up", state=STATE_SYNCING, queued=2, transferring=1,
            last_error=None, last_sync=now, detail="transferred 3 file(s)",
            current_project="Projects/2026/FF5/Nuclear", bytes_done=100, bytes_total=200,
            speed_bps=1234.5, eta_seconds=10.0,
        ),
        LaneStatus(
            name="lane_b_proxy_down", state=STATE_ERROR, queued=0, transferring=0,
            last_error="boom", last_sync=None, detail="",
        ),
    ]
    reporter = DashboardReporter(lambda: statuses, _cfg(), http_post=fake_post)
    reporter.post_once()

    assert len(calls) == 1
    url, data, headers, timeout = calls[0]
    assert url == "http://dash.example.com/api/v1/report"
    assert headers["Content-Type"] == "application/json"
    assert headers["X-CCSync-Token"] == "tok123"
    # CORE-M12: a FULL report carries local_manifest + media_tree, which
    # cannot cross a real WAN link in the 5 s light-tick timeout -- so those
    # two sections never reached the dashboard at all.
    assert timeout == reporter.full_report_timeout
    assert reporter.full_report_timeout > reporter.timeout

    assert data["editor_name"] == "alex"
    assert data["machine"] == platform.node()
    assert data["companion_version"] == config_mod.VERSION
    # reported_at must be a parseable ISO 8601 UTC timestamp.
    parsed = datetime.fromisoformat(data["reported_at"])
    assert parsed.tzinfo is not None

    assert data["lanes"] == [
        {
            "name": "lane_a_video_up", "state": STATE_SYNCING, "queued": 2,
            "transferring": 1, "last_error": None, "last_sync": now.isoformat(),
            "detail": "transferred 3 file(s)",
            "current_project": "Projects/2026/FF5/Nuclear", "bytes_done": 100,
            "bytes_total": 200, "speed_bps": 1234.5, "eta_seconds": 10.0,
            "transfers": [],
        },
        {
            "name": "lane_b_proxy_down", "state": STATE_ERROR, "queued": 0,
            "transferring": 0, "last_error": "boom", "last_sync": None,
            "detail": None,
            "current_project": None, "bytes_done": None, "bytes_total": None,
            "speed_bps": None, "eta_seconds": None, "transfers": [],
        },
    ]
    # queue/current_project keys are absent entirely when no get_queue_info
    # callback was supplied (non-managed mode).
    assert "queue" not in data
    assert "current_project" not in data
    assert "resolve_project" not in data
    # mode/local_manifest/media_tree keys are absent entirely when no
    # getter was supplied.
    assert "mode" not in data
    assert "local_manifest" not in data
    assert "media_tree" not in data

    # The payload must also be JSON-serializable as-is (no datetimes etc).
    json.dumps(data)


def test_post_once_lane_transfers_included_from_status():
    calls = []

    def fake_post(url, data, headers, timeout):
        calls.append(data)

    statuses = [
        LaneStatus(
            name="lane_a_video_up",
            transfers=[
                {
                    "name": "clip.mov", "direction": "up", "bytes_done": 1000,
                    "bytes_total": 5000, "percentage": 20.0, "speed_bps": 500.0,
                    "eta_seconds": 8.0,
                }
            ],
        )
    ]
    reporter = DashboardReporter(lambda: statuses, _cfg(), http_post=fake_post)
    reporter.post_once()

    assert calls[0]["lanes"][0]["transfers"] == [
        {
            "name": "clip.mov", "direction": "up", "bytes_done": 1000,
            "bytes_total": 5000, "percentage": 20.0, "speed_bps": 500.0,
            "eta_seconds": 8.0,
        }
    ]


def test_post_once_includes_queue_and_current_project_when_get_queue_info_set():
    calls = []

    def fake_post(url, data, headers, timeout):
        calls.append(data)

    def get_queue_info():
        return (["slug-b", "slug-c"], "slug-a")

    reporter = DashboardReporter(
        lambda: [], _cfg(), http_post=fake_post, get_queue_info=get_queue_info
    )
    reporter.post_once()

    assert calls[0]["queue"] == ["slug-b", "slug-c"]
    assert calls[0]["current_project"] == "slug-a"


def test_post_once_queue_info_none_current_project():
    calls = []

    def fake_post(url, data, headers, timeout):
        calls.append(data)

    def get_queue_info():
        return ([], None)

    reporter = DashboardReporter(
        lambda: [], _cfg(), http_post=fake_post, get_queue_info=get_queue_info
    )
    reporter.post_once()

    assert calls[0]["queue"] == []
    assert calls[0]["current_project"] is None


def test_post_once_get_queue_info_failure_does_not_raise_and_omits_gracefully():
    calls = []

    def fake_post(url, data, headers, timeout):
        calls.append(data)

    def failing_get_queue_info():
        raise RuntimeError("boom")

    reporter = DashboardReporter(
        lambda: [], _cfg(), http_post=fake_post, get_queue_info=failing_get_queue_info
    )
    reporter.post_once()  # must not raise

    assert calls[0]["queue"] == []
    assert calls[0]["current_project"] is None


def test_post_once_includes_resolve_project_when_getter_set():
    calls = []

    def fake_post(url, data, headers, timeout):
        calls.append(data)

    reporter = DashboardReporter(
        lambda: [], _cfg(), http_post=fake_post, get_resolve_project=lambda: "CCT Creator Profiles"
    )
    reporter.post_once()
    assert calls[0]["resolve_project"] == "CCT Creator Profiles"


def test_post_once_resolve_project_none_when_getter_returns_none():
    calls = []

    def fake_post(url, data, headers, timeout):
        calls.append(data)

    reporter = DashboardReporter(
        lambda: [], _cfg(), http_post=fake_post, get_resolve_project=lambda: None
    )
    reporter.post_once()
    assert calls[0]["resolve_project"] is None


def test_post_once_resolve_project_none_when_getter_raises():
    calls = []

    def fake_post(url, data, headers, timeout):
        calls.append(data)

    def failing_get_resolve_project():
        raise RuntimeError("boom")

    reporter = DashboardReporter(
        lambda: [], _cfg(), http_post=fake_post, get_resolve_project=failing_get_resolve_project
    )
    reporter.post_once()  # must not raise
    assert calls[0]["resolve_project"] is None


def test_post_once_omits_resolve_project_when_no_getter_supplied():
    calls = []

    def fake_post(url, data, headers, timeout):
        calls.append(data)

    reporter = DashboardReporter(lambda: [], _cfg(), http_post=fake_post)
    reporter.post_once()
    assert "resolve_project" not in calls[0]


# -- mode / local_manifest / media_tree -----------------------------------------------


def test_post_once_includes_mode_when_getter_set():
    calls = []

    def fake_post(url, data, headers, timeout):
        calls.append(data)

    reporter = DashboardReporter(lambda: [], _cfg(), http_post=fake_post, get_mode=lambda: "editor")
    reporter.post_once()
    assert calls[0]["mode"] == "editor"


def test_post_once_omits_mode_when_no_getter_supplied():
    calls = []

    def fake_post(url, data, headers, timeout):
        calls.append(data)

    reporter = DashboardReporter(lambda: [], _cfg(), http_post=fake_post)
    reporter.post_once()
    assert "mode" not in calls[0]


def test_post_once_mode_getter_failure_omits_key():
    calls = []

    def fake_post(url, data, headers, timeout):
        calls.append(data)

    def failing_get_mode():
        raise RuntimeError("boom")

    reporter = DashboardReporter(
        lambda: [], _cfg(), http_post=fake_post, get_mode=failing_get_mode
    )
    reporter.post_once()  # must not raise
    assert "mode" not in calls[0]


def test_post_once_heavy_includes_local_manifest_and_media_tree():
    calls = []

    def fake_post(url, data, headers, timeout):
        calls.append(data)

    local_manifest = {"2026/FF5/Nuclear": {"n_originals": 3}}
    media_tree = {"MyProject": [{"bin_path": "", "clip_name": "a.mov"}]}

    reporter = DashboardReporter(
        lambda: [], _cfg(), http_post=fake_post,
        get_local_manifest=lambda: local_manifest,
        get_media_tree=lambda: media_tree,
    )
    reporter.post_once(light=False)

    assert calls[0]["local_manifest"] == local_manifest
    assert calls[0]["media_tree"] == media_tree


def test_post_once_light_omits_local_manifest_and_media_tree():
    calls = []

    def fake_post(url, data, headers, timeout):
        calls.append(data)

    reporter = DashboardReporter(
        lambda: [], _cfg(), http_post=fake_post,
        get_local_manifest=lambda: {"x": 1},
        get_media_tree=lambda: {"y": 2},
    )
    reporter.post_once(light=True)

    assert "local_manifest" not in calls[0]
    assert "media_tree" not in calls[0]
    # mode/lanes/etc still present on a light tick.
    assert "lanes" in calls[0]


def test_post_once_light_still_includes_mode_and_resolve_project():
    calls = []

    def fake_post(url, data, headers, timeout):
        calls.append(data)

    reporter = DashboardReporter(
        lambda: [], _cfg(), http_post=fake_post,
        get_mode=lambda: "base", get_resolve_project=lambda: "Proj",
    )
    reporter.post_once(light=True)

    assert calls[0]["mode"] == "base"
    assert calls[0]["resolve_project"] == "Proj"


def test_post_once_local_manifest_getter_failure_omits_key():
    calls = []

    def fake_post(url, data, headers, timeout):
        calls.append(data)

    def failing():
        raise RuntimeError("boom")

    reporter = DashboardReporter(
        lambda: [], _cfg(), http_post=fake_post, get_local_manifest=failing
    )
    reporter.post_once()  # must not raise
    assert "local_manifest" not in calls[0]


def test_post_once_media_tree_getter_failure_omits_key():
    calls = []

    def fake_post(url, data, headers, timeout):
        calls.append(data)

    def failing():
        raise RuntimeError("boom")

    reporter = DashboardReporter(
        lambda: [], _cfg(), http_post=fake_post, get_media_tree=failing
    )
    reporter.post_once()  # must not raise
    assert "media_tree" not in calls[0]


# -- adaptive interval selection -----------------------------------------------


def test_select_interval_returns_normal_when_no_lane_syncing():
    statuses = [LaneStatus(name="lane_a_video_up", state="idle")]
    reporter = DashboardReporter(
        lambda: statuses, _cfg(dashboard_report_interval=60, dashboard_report_interval_active=5),
        http_post=lambda *a: None,
    )
    assert reporter._select_interval() == 60


def test_select_interval_returns_active_when_a_lane_is_syncing():
    statuses = [
        LaneStatus(name="lane_a_video_up", state="idle"),
        LaneStatus(name="lane_b_proxy_down", state=STATE_SYNCING),
    ]
    reporter = DashboardReporter(
        lambda: statuses, _cfg(dashboard_report_interval=60, dashboard_report_interval_active=5),
        http_post=lambda *a: None,
    )
    assert reporter._select_interval() == 5


def test_select_interval_get_statuses_failure_falls_back_to_normal():
    def failing_get_statuses():
        raise RuntimeError("boom")

    reporter = DashboardReporter(
        failing_get_statuses, _cfg(dashboard_report_interval=60, dashboard_report_interval_active=5),
        http_post=lambda *a: None,
    )
    assert reporter._select_interval() == 60


def test_report_loop_throttles_heavy_payload_during_active_ticks(monkeypatch):
    """First tick is always heavy; subsequent fast (active-interval) ticks
    stay light until a full report_interval has elapsed since the last
    heavy post, at which point a heavy tick recurs."""
    monkeypatch.setattr(reporter_mod, "INITIAL_DELAY_SECONDS", 0.0)
    statuses = [LaneStatus(name="lane_a_video_up", state=STATE_SYNCING)]
    reporter = DashboardReporter(
        lambda: statuses,
        _cfg(dashboard_report_interval=0.15, dashboard_report_interval_active=0.03),
        http_post=lambda *a: None,
    )
    light_calls = []
    real_post_once = reporter.post_once

    def spy_post_once(light=False):
        light_calls.append(light)
        return real_post_once(light=light)

    reporter.post_once = spy_post_once

    reporter.start()
    try:
        deadline = time.monotonic() + 3.0
        while len(light_calls) < 6 and time.monotonic() < deadline:
            time.sleep(0.01)
    finally:
        reporter.stop()

    assert len(light_calls) >= 6
    assert light_calls[0] is False  # first tick always heavy
    assert any(v is True for v in light_calls), "fast ticks should mostly be light"
    assert any(v is False for v in light_calls[1:]), "a heavy tick should recur at report_interval cadence"


def test_post_once_empty_lanes_list():
    calls = []
    reporter = DashboardReporter(lambda: [], _cfg(), http_post=lambda *a: calls.append(a))
    reporter.post_once()
    assert calls[0][1]["lanes"] == []


# -- identity (require_login) -----------------------------------------------


def test_post_once_uses_get_editor_name_and_sends_identity_header():
    calls = []

    def fake_post(url, data, headers, timeout):
        calls.append((data, headers))

    reporter = DashboardReporter(
        lambda: [], _cfg(editor_name="stale-config-name"), http_post=fake_post,
        get_editor_name=lambda: "verified-user",
        get_identity_token=lambda: "v1.verified-user.9999999999.deadbeef",
    )
    reporter.post_once()

    data, headers = calls[0]
    assert data["editor_name"] == "verified-user"
    assert headers["X-CCSync-Identity"] == "v1.verified-user.9999999999.deadbeef"


def test_post_once_skipped_when_get_editor_name_returns_none():
    calls = []

    def fake_post(url, data, headers, timeout):
        calls.append((data, headers))

    reporter = DashboardReporter(
        lambda: [], _cfg(), http_post=fake_post,
        get_editor_name=lambda: None,
        get_identity_token=lambda: "should-not-be-sent",
    )
    reporter.post_once()

    assert calls == []


def test_post_once_omits_identity_header_when_get_identity_token_returns_none():
    calls = []

    def fake_post(url, data, headers, timeout):
        calls.append(headers)

    reporter = DashboardReporter(
        lambda: [], _cfg(), http_post=fake_post,
        get_editor_name=lambda: "alex",
        get_identity_token=lambda: None,
    )
    reporter.post_once()

    assert "X-CCSync-Identity" not in calls[0]


def test_post_once_no_getters_falls_back_to_cfg_editor_name_back_compat():
    calls = []

    def fake_post(url, data, headers, timeout):
        calls.append((data, headers))

    reporter = DashboardReporter(lambda: [], _cfg(editor_name="alex"), http_post=fake_post)
    reporter.post_once()

    data, headers = calls[0]
    assert data["editor_name"] == "alex"
    assert "X-CCSync-Identity" not in headers


def test_post_once_get_editor_name_failure_skips_cycle():
    calls = []

    def fake_post(url, data, headers, timeout):
        calls.append(1)

    def failing_get_editor_name():
        raise RuntimeError("boom")

    reporter = DashboardReporter(
        lambda: [], _cfg(), http_post=fake_post, get_editor_name=failing_get_editor_name
    )
    reporter.post_once()  # must not raise

    assert calls == []


def test_post_once_get_identity_token_failure_omits_header_but_still_posts():
    calls = []

    def fake_post(url, data, headers, timeout):
        calls.append(headers)

    def failing_get_identity_token():
        raise RuntimeError("boom")

    reporter = DashboardReporter(
        lambda: [], _cfg(), http_post=fake_post,
        get_editor_name=lambda: "alex", get_identity_token=failing_get_identity_token,
    )
    reporter.post_once()  # must not raise

    assert "X-CCSync-Identity" not in calls[0]


# -- headers / URL handling -----------------------------------------------


def test_post_once_omits_token_header_when_blank():
    calls = []

    def fake_post(url, data, headers, timeout):
        calls.append(headers)

    reporter = DashboardReporter(lambda: [], _cfg(dashboard_token=""), http_post=fake_post)
    reporter.post_once()
    assert "X-CCSync-Token" not in calls[0]
    assert calls[0]["Content-Type"] == "application/json"


def test_post_once_includes_token_header_when_set():
    calls = []

    def fake_post(url, data, headers, timeout):
        calls.append(headers)

    reporter = DashboardReporter(lambda: [], _cfg(dashboard_token="secret"), http_post=fake_post)
    reporter.post_once()
    assert calls[0]["X-CCSync-Token"] == "secret"


def test_post_once_url_join_handles_trailing_slash():
    calls = []

    def fake_post(url, data, headers, timeout):
        calls.append(url)

    reporter = DashboardReporter(
        lambda: [], _cfg(dashboard_url="http://dash.example.com/"), http_post=fake_post
    )
    reporter.post_once()
    assert calls[0] == "http://dash.example.com/api/v1/report"


def test_post_once_url_join_no_trailing_slash():
    calls = []

    def fake_post(url, data, headers, timeout):
        calls.append(url)

    reporter = DashboardReporter(
        lambda: [], _cfg(dashboard_url="http://dash.example.com"), http_post=fake_post
    )
    reporter.post_once()
    assert calls[0] == "http://dash.example.com/api/v1/report"


# -- disabled when dashboard_url blank -----------------------------------------------


def test_reporter_disabled_when_dashboard_url_blank():
    reporter = DashboardReporter(lambda: [], _cfg(dashboard_url=""), http_post=lambda *a: None)
    assert reporter.enabled is False


def test_start_does_not_spawn_thread_when_disabled():
    calls = []
    reporter = DashboardReporter(
        lambda: [], _cfg(dashboard_url=""), http_post=lambda *a: calls.append(a)
    )
    reporter.start()
    assert reporter._thread is None
    time.sleep(0.1)
    assert calls == []
    reporter.stop()  # must not raise


def test_post_once_is_a_noop_when_disabled():
    calls = []
    reporter = DashboardReporter(
        lambda: [], _cfg(dashboard_url=""), http_post=lambda *a: calls.append(a)
    )
    reporter.post_once()
    assert calls == []


# -- fault isolation -----------------------------------------------


def test_run_cycle_swallows_exceptions():
    def failing_post(url, data, headers, timeout):
        raise RuntimeError("dashboard unreachable")

    reporter = DashboardReporter(lambda: [], _cfg(), http_post=failing_post)
    reporter._run_cycle()  # must not raise


def test_run_cycle_marks_heavy_attempt_even_on_failure():
    # A failing heavy post must still update _last_heavy_at -- otherwise
    # _report_loop's `light = active_tick and (now - self._last_heavy_at) <
    # report_interval` is always False, and every subsequent active tick
    # resends the full (possibly oversized) heavy payload forever instead
    # of degrading to the normal report_interval cadence.
    def failing_post(url, data, headers, timeout):
        raise RuntimeError("timed out")

    reporter = DashboardReporter(lambda: [], _cfg(), http_post=failing_post)
    assert reporter._last_heavy_at == 0.0
    reporter._run_cycle(light=False)
    assert reporter._last_heavy_at > 0.0


def test_run_cycle_light_tick_does_not_touch_last_heavy_at():
    reporter = DashboardReporter(lambda: [], _cfg(), http_post=lambda *a: {})
    reporter._last_heavy_at = 123.0
    reporter._run_cycle(light=True)
    assert reporter._last_heavy_at == 123.0


def test_run_cycle_heavy_success_still_updates_last_heavy_at():
    reporter = DashboardReporter(lambda: [], _cfg(), http_post=lambda *a: {})
    before = time.monotonic()
    reporter._run_cycle(light=False)
    assert reporter._last_heavy_at >= before


def test_report_loop_survives_post_failures_and_keeps_running(monkeypatch):
    monkeypatch.setattr(reporter_mod, "INITIAL_DELAY_SECONDS", 0.01)
    call_count = {"n": 0}

    def flaky_post(url, data, headers, timeout):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("boom")

    reporter = DashboardReporter(
        lambda: [], _cfg(dashboard_report_interval=0.03), http_post=flaky_post
    )
    reporter.start()
    try:
        deadline = time.monotonic() + 3.0
        while call_count["n"] < 3 and time.monotonic() < deadline:
            time.sleep(0.01)
    finally:
        reporter.stop()
    assert call_count["n"] >= 3


def test_error_logging_warns_once_then_debug(caplog):
    def failing_post(url, data, headers, timeout):
        raise RuntimeError("boom")

    reporter = DashboardReporter(lambda: [], _cfg(), http_post=failing_post)
    with caplog.at_level(logging.DEBUG, logger="ccsync.reporter"):
        reporter._run_cycle()
        reporter._run_cycle()

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    debugs = [r for r in caplog.records if r.levelno == logging.DEBUG]
    assert len(warnings) == 1
    assert len(debugs) == 1


def test_error_logging_resets_to_warning_after_a_success(caplog):
    results = iter([RuntimeError("boom"), None, RuntimeError("boom again")])

    def flaky_post(url, data, headers, timeout):
        result = next(results)
        if isinstance(result, Exception):
            raise result

    reporter = DashboardReporter(lambda: [], _cfg(), http_post=flaky_post)
    with caplog.at_level(logging.DEBUG, logger="ccsync.reporter"):
        reporter._run_cycle()  # fails -> WARNING
        reporter._run_cycle()  # succeeds -> resets
        reporter._run_cycle()  # fails again -> WARNING (not DEBUG)

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 2


# -- default_http_post against a real socket -----------------------------------------------


class _CapturingHandler(BaseHTTPRequestHandler):
    server_version = "FakeDashboard/0"

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        self.server.captured.append(
            {
                "path": self.path,
                # HTTP header names are case-insensitive (RFC 7230 3.2), and
                # urllib.request's do_open() title-cases every outgoing
                # header regardless of what default_http_post sets -- so
                # capture case-insensitively rather than asserting on the
                # exact wire casing.
                "headers": {k.lower(): v for k, v in self.headers.items()},
                "body": json.loads(body.decode("utf-8")) if body else None,
            }
        )
        payload = b"{}"
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt, *args):  # quiet
        pass


@pytest.fixture
def fake_dashboard_server():
    server = HTTPServer(("127.0.0.1", 0), _CapturingHandler)
    server.captured = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_default_http_post_sends_json_body_and_headers(fake_dashboard_server):
    port = fake_dashboard_server.server_address[1]
    url = f"http://127.0.0.1:{port}/api/v1/report"
    default_http_post(
        url,
        {"editor_name": "alex", "lanes": []},
        {"Content-Type": "application/json", "X-CCSync-Token": "tok123"},
        5.0,
    )
    assert len(fake_dashboard_server.captured) == 1
    request = fake_dashboard_server.captured[0]
    assert request["path"] == "/api/v1/report"
    assert request["headers"]["x-ccsync-token"] == "tok123"
    assert request["headers"]["content-type"] == "application/json"
    assert request["body"] == {"editor_name": "alex", "lanes": []}


def test_reporter_end_to_end_against_fake_server(fake_dashboard_server):
    port = fake_dashboard_server.server_address[1]
    cfg = _cfg(dashboard_url=f"http://127.0.0.1:{port}")
    statuses = [LaneStatus(name="lane_c_syncthing")]
    reporter = DashboardReporter(lambda: statuses, cfg)  # real default_http_post
    reporter.post_once()
    assert len(fake_dashboard_server.captured) == 1
    body = fake_dashboard_server.captured[0]["body"]
    assert body["lanes"][0]["name"] == "lane_c_syncthing"


# -- upgrade-channel response callback --------------------------------


def test_post_once_hands_parsed_response_to_callback():
    responses = []
    reporter = DashboardReporter(
        lambda: [], _cfg(),
        http_post=lambda u, d, h, t: {"ok": True, "upgrade": {"version": "9.9.9"}},
        on_report_response=responses.append,
    )
    reporter.post_once()
    assert responses == [{"ok": True, "upgrade": {"version": "9.9.9"}}]


def test_post_once_survives_broken_response_callback():
    def boom(resp):
        raise RuntimeError("boom")

    reporter = DashboardReporter(
        lambda: [], _cfg(), http_post=lambda u, d, h, t: {}, on_report_response=boom,
    )
    reporter.post_once()  # must not raise


def test_payload_includes_platform_key():
    calls = []
    reporter = DashboardReporter(
        lambda: [], _cfg(), http_post=lambda u, d, h, t: calls.append(d) or {},
    )
    reporter.post_once()
    assert calls[0]["platform"] in {"windows", "macos", "linux"}


# -- per-machine version + never-raise numeric config (AUDIT_3 M-5 / #14) ----


def test_companion_version_is_on_every_report_including_light_ticks():
    """The dashboard displays a per-machine companion version, and most ticks
    are LIGHT ones (the fast active cadence) -- the field must not be part of
    the heavy payload sections."""
    calls = []

    def fake_post(url, data, headers, timeout):
        calls.append(data)
        return {}

    reporter = DashboardReporter(lambda: [], _cfg(), http_post=fake_post)
    reporter.post_once(light=True)
    reporter.post_once(light=False)

    assert [d["companion_version"] for d in calls] == [config_mod.VERSION] * 2
    assert "local_manifest" not in calls[0]  # sanity: it really was light


def test_hand_edited_report_intervals_never_raise_in_the_constructor(caplog):
    """The reporter is constructed inside CompanionApp.__init__, so a bare
    float() on a hand-edited value took the windowed exe down with no tray
    and no log line."""
    cfg = _cfg(dashboard_report_interval="1m", dashboard_report_interval_active=None)
    with caplog.at_level("ERROR", logger="ccsync.config"):
        reporter = DashboardReporter(lambda: [], cfg, http_post=lambda *a: {})

    assert reporter.report_interval == 60.0
    assert reporter.report_interval_active == 5.0
