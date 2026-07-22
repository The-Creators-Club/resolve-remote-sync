"""Syncthing lane tests: config.xml API-key parsing, and REST behavior
against a tiny in-process http.server fixture (never a real Syncthing)."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from ccsync_companion.sync.base import STATE_ERROR, STATE_IDLE, STATE_SYNCING
from ccsync_companion.sync.syncthing_lane import (
    SyncthingLane,
    read_api_key_from_config,
)

# -- config.xml parsing -----------------------------------------------


def test_read_api_key_from_config(tmp_path):
    path = tmp_path / "config.xml"
    path.write_text(
        "<configuration><gui><apikey>abc123</apikey></gui></configuration>",
        encoding="utf-8",
    )
    assert read_api_key_from_config(path) == "abc123"


def test_read_api_key_missing_file(tmp_path):
    assert read_api_key_from_config(tmp_path / "nope.xml") is None


def test_read_api_key_malformed_xml(tmp_path):
    path = tmp_path / "config.xml"
    path.write_text("<not><valid", encoding="utf-8")
    assert read_api_key_from_config(path) is None


def test_read_api_key_no_gui_element(tmp_path):
    path = tmp_path / "config.xml"
    path.write_text("<configuration></configuration>", encoding="utf-8")
    assert read_api_key_from_config(path) is None


# -- REST behaviour against a tiny fixture server ------------------------


class _FakeSyncthingHandler(BaseHTTPRequestHandler):
    server_version = "FakeSyncthing/0"

    def do_GET(self):
        state = self.server.fake_state
        if self.path == "/rest/system/ping":
            self._json(200, {"ping": "pong"})
        elif self.path == "/rest/config":
            self._json(200, {"folders": state["folders"]})
        elif self.path.startswith("/rest/db/status"):
            folder_id = self.path.split("folder=")[-1]
            self._json(200, state["db_status"].get(folder_id, {"needTotalItems": 0}))
        else:
            self._json(404, {"error": "not found"})

    def _json(self, status, obj):
        payload = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt, *args):  # quiet
        pass


@pytest.fixture
def fake_syncthing_server():
    server = HTTPServer(("127.0.0.1", 0), _FakeSyncthingHandler)
    server.fake_state = {
        "folders": [{"id": "proj-1", "devices": [{"deviceID": "AAAA"}, {"deviceID": "BBBB"}]}],
        "db_status": {"proj-1": {"needTotalItems": 0}},
    }
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _lane_for(server, **kwargs):
    port = server.server_address[1]
    return SyncthingLane(
        base_url=f"http://127.0.0.1:{port}", api_key="testkey", **kwargs
    )


def test_check_once_idle_when_folder_configured_and_shared(fake_syncthing_server):
    lane = _lane_for(fake_syncthing_server, expected_folder_ids=["proj-1"])
    status = lane.check_once()
    assert status.state == STATE_IDLE
    assert status.last_error is None


def test_check_once_syncing_when_items_needed(fake_syncthing_server):
    fake_syncthing_server.fake_state["db_status"]["proj-1"] = {"needTotalItems": 4}
    lane = _lane_for(fake_syncthing_server, expected_folder_ids=["proj-1"])
    status = lane.check_once()
    assert status.state == STATE_SYNCING
    assert status.queued == 4


def test_check_once_error_when_folder_missing(fake_syncthing_server):
    lane = _lane_for(fake_syncthing_server, expected_folder_ids=["not-configured"])
    status = lane.check_once()
    assert status.state == STATE_ERROR
    assert "not configured" in status.last_error


def test_check_once_error_when_folder_not_shared(fake_syncthing_server):
    fake_syncthing_server.fake_state["folders"] = [{"id": "proj-1", "devices": [{"deviceID": "AAAA"}]}]
    lane = _lane_for(fake_syncthing_server, expected_folder_ids=["proj-1"])
    status = lane.check_once()
    assert status.state == STATE_ERROR
    assert "not shared" in status.last_error


def test_check_once_no_expected_folders_is_idle(fake_syncthing_server):
    lane = _lane_for(fake_syncthing_server, expected_folder_ids=[])
    status = lane.check_once()
    assert status.state == STATE_IDLE


def test_check_once_unreachable_server_reports_not_running():
    # Nothing listening on this port.
    lane = SyncthingLane(base_url="http://127.0.0.1:1", api_key="testkey", expected_folder_ids=["x"])
    status = lane.check_once()
    assert status.state == STATE_ERROR
    assert status.last_error == "Syncthing not running"


def test_check_once_no_api_key_anywhere(tmp_path):
    lane = SyncthingLane(
        base_url="http://127.0.0.1:1",
        api_key="",
        config_xml_path=tmp_path / "nonexistent.xml",
        expected_folder_ids=["x"],
    )
    status = lane.check_once()
    assert status.state == STATE_ERROR
    assert "API key" in status.last_error
