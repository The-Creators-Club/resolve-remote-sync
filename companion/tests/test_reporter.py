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


def test_payload_carries_completions_when_provided():
    from ccsync_companion.reporter import DashboardReporter
    from ccsync_companion.sync.base import LaneStatus

    events = [{"name": "Projects/X/a.mov", "direction": "up",
               "lane": "lane_a_video_up", "at": "2026-07-26T08:00:00+00:00"}]
    reporter = DashboardReporter(
        lambda: [LaneStatus(name="lane_a_video_up", state="idle")],
        {"dashboard_url": "http://x", "editor_name": "e"},
        get_completions=lambda: list(events),
    )
    payload = reporter._build_payload()
    assert payload["completed"] == events

    reporter_none = DashboardReporter(
        lambda: [LaneStatus(name="lane_a_video_up", state="idle")],
        {"dashboard_url": "http://x", "editor_name": "e"},
    )
    assert "completed" not in reporter_none._build_payload()


# -- B6: the payload never grows past what the dashboard will accept --------


def _big_manifest(n_projects, n_files):
    """The shape KNOWN_BUGS B6 names: N projects x 2 file lists x N entries.
    manifest.MAX_PER_FILE_ENTRIES is 2000 and MAX_PROJECTS is 64, so
    (64, 2000) is the real worst case a base rig produces."""
    return {
        f"2026/FF5/P{i:03d}": {
            "n_originals": n_files, "bytes_originals": n_files * 10**9,
            "n_proxies": n_files, "bytes_proxies": n_files * 10**8,
            "truncated": False,
            "originals": [[f"Footage/Day 1/CAM A/A{j:06d}_C001_0101AB.braw", 12345678]
                          for j in range(n_files)],
            "proxies": [[f"Proxy/Footage/Day 1/CAM A/A{j:06d}_C001_0101AB.mov", 123456]
                        for j in range(n_files)],
        }
        for i in range(n_projects)
    }


def _reporter_with(manifest=None, tree=None, queue=None, calls=None):
    from ccsync_companion.sync.base import LaneStatus

    def fake_post(url, data, headers, timeout):
        if calls is not None:
            calls.append(data)
        return {}

    return DashboardReporter(
        lambda: [LaneStatus(name="lane_a_video_up", state="idle")],
        _cfg(),
        http_post=fake_post,
        get_local_manifest=(lambda: manifest) if manifest is not None else None,
        get_media_tree=(lambda: tree) if tree is not None else None,
        get_queue_info=(lambda: (queue, None)) if queue is not None else None,
    )


def test_an_oversized_heavy_payload_sheds_sections_instead_of_413ing(caplog):
    """B6's lower-trigger variant: the dashboard refuses a body over 8 MiB,
    and that refusal costs the WHOLE report -- lane status, transfers,
    machine_state, presence and the upgrade advertisement with it. 64
    projects x 2000 file entries blows past 8 MB and nothing here measured
    the payload at all."""
    calls = []
    reporter = _reporter_with(manifest=_big_manifest(64, 2000), calls=calls)
    with caplog.at_level(logging.WARNING, logger="ccsync.reporter"):
        reporter.post_once(light=False)

    assert len(calls) == 1
    sent = calls[0]
    assert reporter_mod.payload_size(sent) <= reporter_mod.PAYLOAD_BUDGET_BYTES
    # the LANE CORE always survives -- that is the whole point
    assert sent["lanes"][0]["name"] == "lane_a_video_up"
    assert sent["editor_name"] and sent["machine"]
    # rollups survive; only the per-file lists were shed, and it was logged
    assert sent["local_manifest"]["2026/FF5/P000"]["n_originals"] == 2000
    assert sent["local_manifest"]["2026/FF5/P000"]["originals"] is None
    assert sent["local_manifest"]["2026/FF5/P000"]["truncated"] is True
    assert "per-file lists" in " ".join(r.getMessage() for r in caplog.records)


def test_a_payload_that_fits_is_left_completely_alone():
    calls = []
    manifest = _big_manifest(3, 5)
    _reporter_with(manifest=manifest, calls=calls).post_once(light=False)
    assert calls[0]["local_manifest"] == manifest
    assert calls[0]["local_manifest"]["2026/FF5/P000"]["originals"] is not None


def test_fit_payload_drops_the_heavy_sections_last_and_keeps_the_report():
    """Worst case: even with everything else shed the body is still too big.
    A LIGHT report that arrives beats a HEAVY one that 413s."""
    reporter = _reporter_with()
    payload = {
        "editor_name": "alex", "machine": "PC", "lanes": [{"name": "lane_a_video_up"}],
        "media_tree": {"Big": [{"clip_name": "x" * 400} for _ in range(40000)]},
        "local_manifest": {"only": {"n_originals": 1, "originals": None, "proxies": None}},
    }
    fitted = reporter._fit_payload(dict(payload), budget=4096)
    assert reporter_mod.payload_size(fitted) <= 4096
    assert "media_tree" not in fitted          # the biggest section goes first
    assert fitted["lanes"] == [{"name": "lane_a_video_up"}]
    assert fitted["editor_name"] == "alex" and fitted["machine"] == "PC"

    # ...and when even that is not enough, local_manifest goes too
    payload["local_manifest"] = {f"p{i}": {"n_originals": i} for i in range(400)}
    fitted = reporter._fit_payload(dict(payload), budget=1024)
    assert reporter_mod.payload_size(fitted) <= 1024
    assert "media_tree" not in fitted and "local_manifest" not in fitted


# -- COMP-CORE-5: measure once, send those same bytes -------------------------


def test_a_fitted_payload_carries_the_bytes_it_was_measured_as():
    """_fit_payload serialised the whole body to size it and threw that away,
    and default_http_post then dumped the identical structure again -- 2x CPU
    and 2x transient peak memory per heavy report on the machine with the
    64-project manifest."""
    reporter = _reporter_with()
    payload = {"editor_name": "alex", "machine": "PC", "lanes": []}
    fitted = reporter._fit_payload(dict(payload), budget=reporter_mod.PAYLOAD_BUDGET_BYTES)

    body = getattr(fitted, "encoded", None)
    assert isinstance(body, bytes)
    assert json.loads(body.decode("utf-8")) == payload
    # ...and it is still a plain dict to every injected HttpPostFn.
    assert isinstance(fitted, dict) and fitted == payload


def test_a_shed_payload_carries_the_bytes_of_its_FINAL_shape():
    """The reused bytes must be the LAST measurement, never a pre-shedding
    one -- sending those would put the dropped sections back on the wire."""
    reporter = _reporter_with()
    payload = {
        "editor_name": "alex", "machine": "PC", "lanes": [],
        "media_tree": {"Big": [{"clip_name": "x" * 400} for _ in range(4000)]},
    }
    fitted = reporter._fit_payload(dict(payload), budget=4096)

    body = getattr(fitted, "encoded", None)
    assert isinstance(body, bytes)
    assert json.loads(body.decode("utf-8")) == fitted
    assert "media_tree" not in json.loads(body.decode("utf-8"))


def test_default_http_post_sends_the_pre_encoded_body_when_there_is_one(
    fake_dashboard_server,
):
    """...and a bare dict still serialises itself: identity.py's verify POST
    and every injected double hand this one of those."""
    port = fake_dashboard_server.server_address[1]
    url = f"http://127.0.0.1:{port}/api/v1/report"
    headers = {"Content-Type": "application/json"}

    measured = reporter_mod._measured({"editor_name": "alex"}, b'{"editor_name": "alex"}')
    default_http_post(url, measured, headers, 5.0)
    default_http_post(url, {"editor_name": "ruskin"}, headers, 5.0)

    bodies = [r["body"] for r in fake_dashboard_server.captured]
    assert bodies == [{"editor_name": "alex"}, {"editor_name": "ruskin"}]


def test_the_queue_is_capped_at_the_dashboards_ceiling(caplog):
    calls = []
    reporter = _reporter_with(queue=[f"slug-{i}" for i in range(120)], calls=calls)
    with caplog.at_level(logging.WARNING, logger="ccsync.reporter"):
        reporter.post_once(light=True)
    assert len(calls[0]["queue"]) == reporter_mod.MAX_REPORT_PROJECTS
    assert "queued project(s)" in " ".join(r.getMessage() for r in caplog.records)


def test_server_side_truncation_is_logged_by_the_companion(caplog):
    """The dashboard now truncates rather than rejecting, and says so in the
    reply. "the dashboard is not showing everything this machine has" has to
    be discoverable from THIS log too."""
    from ccsync_companion.sync.base import LaneStatus

    reporter = DashboardReporter(
        lambda: [LaneStatus(name="lane_a_video_up", state="idle")],
        _cfg(),
        http_post=lambda *a: {"ok": True, "truncated": {"local_manifest": 12}},
    )
    with caplog.at_level(logging.WARNING, logger="ccsync.reporter"):
        reporter.post_once()
    assert "truncated this report" in " ".join(r.getMessage() for r in caplog.records)


def test_the_report_token_is_read_per_post_not_cached_at_construction():
    """/api/v1/verify hands back the current fleet report token and
    identity.IdentityManager republishes it into this same cfg dict at
    sign-in. Cached at construction, a stale config.toml `dashboard_token`
    (rotated on the server, or mistyped at install) 401'd every report
    forever with a successful tray sign-in sitting right next to it."""
    from ccsync_companion.sync.base import LaneStatus

    seen = []

    def fake_post(url, data, headers, timeout):
        seen.append(headers.get("X-CCSync-Token"))
        return {}

    cfg = _cfg(dashboard_token="STALE")
    reporter = DashboardReporter(
        lambda: [LaneStatus(name="lane_a_video_up", state="idle")], cfg,
        http_post=fake_post)
    reporter.post_once()
    cfg["dashboard_token"] = "fresh-from-verify"      # what sign-in does
    reporter.post_once()
    assert seen == ["STALE", "fresh-from-verify"]


def test_a_blanked_cfg_token_falls_back_to_the_constructed_value():
    from ccsync_companion.sync.base import LaneStatus

    seen = []

    def fake_post(url, data, headers, timeout):
        seen.append(headers.get("X-CCSync-Token"))
        return {}

    cfg = _cfg(dashboard_token="tok123")
    reporter = DashboardReporter(
        lambda: [LaneStatus(name="lane_a_video_up", state="idle")], cfg,
        http_post=fake_post)
    cfg["dashboard_token"] = ""
    reporter.post_once()
    assert seen == ["tok123"]


def test_shedding_never_mutates_the_manifest_cache():
    """ManifestCache.get() returns a SHALLOW copy, so its per-project dicts
    are shared with the live cache. Stripping the file lists in place would
    blank them until the next full rescan (manifest_refresh_interval later),
    silently degrading every subsequent report too."""
    from ccsync_companion import manifest as manifest_mod
    from ccsync_companion.sync.base import LaneStatus

    cache = manifest_mod.ManifestCache({"local_root": ""})
    cache._cache = _big_manifest(64, 2000)
    before = {rel: len(e["originals"]) for rel, e in cache._cache.items()}

    reporter = DashboardReporter(
        lambda: [LaneStatus(name="lane_a_video_up", state="idle")], _cfg(),
        http_post=lambda *a: {}, get_local_manifest=cache.get)
    reporter.post_once(light=False)

    after = {rel: len(e["originals"]) for rel, e in cache._cache.items()}
    assert after == before
    assert all(e["truncated"] is False for e in cache._cache.values())


# -- proxy coverage: which of this machine's originals nobody else can see --


def _coverage(**overrides):
    coverage = {
        "state": "user-active", "enabled": True, "missing": 12, "braw": 4,
        "needs_resolve": 4, "own": 6, "preview": 2, "left": 8, "generated": 3,
        "failed": 1, "ffmpeg": True, "nvenc": True,
        "scanned_at": "2026-08-10T12:00:00+00:00",
        "projects": {"2026/FF5/Nuclear": {"missing": 12, "braw": 4}},
    }
    coverage.update(overrides)
    return coverage


def _reporter_with_coverage(coverage, calls):
    from ccsync_companion.sync.base import LaneStatus

    def fake_post(url, data, headers, timeout):
        calls.append(data)
        return {}

    return DashboardReporter(
        lambda: [LaneStatus(name="lane_a_video_up", state="idle")],
        _cfg(), http_post=fake_post,
        get_proxy_coverage=(coverage if callable(coverage) else (lambda: coverage)),
    )


def test_the_proxy_section_rides_every_tick_including_light_ones():
    """Unlike local_manifest/media_tree this is a handful of integers off a
    cached read -- and "nobody else can see this editor's footage" is not
    something an admin should wait a heavy cycle to learn."""
    calls = []
    reporter = _reporter_with_coverage(_coverage(), calls)
    reporter.post_once(light=True)
    reporter.post_once(light=False)

    assert len(calls) == 2
    for sent in calls:
        section = sent["proxy_coverage"]
        assert section["missing"] == 12 and section["braw"] == 4
        assert section["state"] == "user-active"
        assert section["ffmpeg"] is True and section["nvenc"] is True
        assert section["scanned_at"] == "2026-08-10T12:00:00+00:00"
        assert section["projects"]["2026/FF5/Nuclear"]["missing"] == 12


def test_no_getter_means_no_section_at_all():
    """The dashboard ignores unknown keys (extra="ignore"), so shipping this
    ahead of any server-side UI is safe -- but a companion whose generator
    failed to construct must send nothing rather than a section of zeroes."""
    calls = []
    _reporter_with(calls=calls).post_once(light=True)
    assert "proxy_coverage" not in calls[0]

    calls.clear()
    _reporter_with_coverage({}, calls).post_once(light=True)
    assert "proxy_coverage" not in calls[0]


def test_a_coverage_getter_that_raises_costs_only_its_own_section():
    calls = []

    def _boom():
        raise RuntimeError("the generator is on fire")

    _reporter_with_coverage(_boom, calls).post_once(light=True)
    assert "proxy_coverage" not in calls[0]
    assert calls[0]["lanes"], "the rest of the report still went"


def test_the_per_project_map_is_capped_at_the_dashboards_ceiling():
    calls = []
    projects = {f"2026/FF5/P{i:03d}": {"missing": 1} for i in range(200)}
    _reporter_with_coverage(_coverage(projects=projects), calls).post_once(light=True)
    sent = calls[0]["proxy_coverage"]
    assert len(sent["projects"]) == reporter_mod.MAX_REPORT_PROJECTS
    assert sent["missing"] == 12, "the totals are never capped"


def test_fit_payload_sheds_the_proxy_project_map_and_keeps_the_scalars(caplog):
    """The part that answers "can anyone else see this editor's footage" is
    the totals; WHICH project the gap is in is a detail worth losing to make
    the report fit."""
    reporter = _reporter_with()
    payload = {
        "editor_name": "alex", "lanes": [{"name": "lane_a_video_up"}],
        "proxy_coverage": _coverage(projects={
            f"2026/FF5/P{i:03d}": {"missing": i} for i in range(64)}),
        "local_manifest": {"only": {"n_originals": 1, "originals": None, "proxies": None}},
    }
    with caplog.at_level(logging.WARNING, logger="ccsync.reporter"):
        fitted = reporter._fit_payload(dict(payload), budget=900)

    assert fitted["proxy_coverage"]["projects"] == {}
    assert fitted["proxy_coverage"]["missing"] == 12
    assert fitted["proxy_coverage"]["truncated"] is True
    assert fitted["lanes"] == [{"name": "lane_a_video_up"}]
    assert "per-project proxy gap map" in " ".join(r.getMessage() for r in caplog.records)


def test_a_payload_that_fits_keeps_the_whole_proxy_map():
    reporter = _reporter_with()
    payload = {"lanes": [], "proxy_coverage": _coverage()}
    fitted = reporter._fit_payload(dict(payload), budget=1_000_000)
    assert fitted["proxy_coverage"]["projects"]["2026/FF5/Nuclear"]["missing"] == 12


# -- the YouTube auto-import section (youtube_import.py) ---------------------


def _reporter_with_youtube(status, calls):
    from ccsync_companion.sync.base import LaneStatus

    def fake_post(url, data, headers, timeout):
        calls.append(data)
        return {}

    return DashboardReporter(
        lambda: [LaneStatus(name="lane_a_video_up", state="idle")],
        _cfg(), http_post=fake_post,
        get_youtube_import=(status if callable(status) else (lambda: status)),
    )


def test_the_youtube_section_rides_every_tick_including_light_ones():
    """A handful of counters off a cached, zero-I/O read -- and the dashboard
    page that started the download is watching for exactly this, so waiting
    for a heavy cycle would make a working import look like a stuck one."""
    calls = []
    status = {"state": "importing", "pending": 4, "imported_session": 9,
              "failed_session": 0, "last_import_at": "2026-08-11T12:00:00+00:00",
              "last_bin": "Youtube/algal reef", "last_error": ""}
    reporter = _reporter_with_youtube(status, calls)

    reporter.post_once(light=True)
    reporter.post_once(light=False)

    assert len(calls) == 2
    for sent in calls:
        assert sent["youtube_import"]["state"] == "importing"
        assert sent["youtube_import"]["imported_session"] == 9
        assert sent["youtube_import"]["last_bin"] == "Youtube/algal reef"


def test_no_youtube_getter_means_no_youtube_section():
    """Same contract as proxy_coverage: a companion whose importer failed to
    construct sends nothing rather than a section of zeroes, and the dashboard
    cannot miss a key it never knew about."""
    calls = []
    _reporter_with(calls=calls).post_once(light=True)
    assert "youtube_import" not in calls[0]

    calls.clear()
    _reporter_with_youtube({}, calls).post_once(light=True)
    assert "youtube_import" not in calls[0]


def test_a_youtube_getter_that_raises_costs_only_its_own_section():
    calls = []

    def _boom():
        raise RuntimeError("the importer is on fire")

    _reporter_with_youtube(_boom, calls).post_once(light=True)
    assert "youtube_import" not in calls[0]
    assert calls[0]["lanes"], "the rest of the report still went"
