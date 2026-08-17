"""Syncthing lane tests: config.xml API-key parsing, and REST behavior
against a tiny in-process http.server fixture (never a real Syncthing)."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from ccsync_companion.sync.base import (
    STATE_ERROR,
    STATE_IDLE,
    STATE_PAUSED,
    STATE_SYNCING,
)
from ccsync_companion.sync import syncthing_lane
from ccsync_companion.sync.syncthing_lane import (
    SyncthingLane,
    default_config_xml_path,
    read_api_key_from_config,
)

# -- default config.xml location --------------------------------------


@pytest.fixture
def _windows_paths(tmp_path, monkeypatch):
    """Pin platform to Windows and LOCALAPPDATA to tmp so the resolution
    order is testable on any OS. Returns (managed, stock) config.xml paths."""
    monkeypatch.setattr(syncthing_lane.platform, "system", lambda: "Windows")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    managed = tmp_path / "ccsync" / "syncthing-config" / "config.xml"
    stock = tmp_path / "Syncthing" / "config.xml"
    return managed, stock


def test_default_config_prefers_ccsync_managed_home(_windows_paths):
    managed, stock = _windows_paths
    managed.parent.mkdir(parents=True)
    managed.write_text("<configuration/>", encoding="utf-8")
    stock.parent.mkdir(parents=True)
    stock.write_text("<configuration/>", encoding="utf-8")
    assert default_config_xml_path() == managed


def test_default_config_falls_back_to_stock_when_no_managed(_windows_paths):
    managed, stock = _windows_paths
    stock.parent.mkdir(parents=True)
    stock.write_text("<configuration/>", encoding="utf-8")
    assert default_config_xml_path() == stock


def test_default_config_neither_exists_points_at_managed(_windows_paths):
    managed, _stock = _windows_paths
    assert default_config_xml_path() == managed


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
        elif self.path == "/rest/system/status":
            if "my_id" not in state:
                self._json(404, {"error": "not found"})
            else:
                self._json(200, {"myID": state["my_id"]})
        elif self.path.startswith("/rest/db/completion"):
            from urllib.parse import parse_qs, urlparse
            q = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
            key = (q.get("folder"), q.get("device"))
            self._json(200, state.get("remote_completion", {}).get(
                key, {"completion": 100, "needItems": 0, "needBytes": 0}))
        elif self.path == "/rest/cluster/pending/folders":
            self._json(200, state.get("pending_folders", {}))
        elif self.path == "/rest/system/connections":
            # Absent from fake_state -> 404, i.e. exactly what an older
            # Syncthing (or one mid-restart) does. The lane must treat that
            # as "no path information", never as a lane error.
            if "connections" not in state:
                self._json(404, {"error": "not found"})
            else:
                self._json(200, state["connections"])
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


def test_check_once_no_expected_folders_never_claims_a_sync(fake_syncthing_server):
    """AUDIT_2 L-6/UX-3: `syncthing_folder_ids` defaults to [] and nothing in
    managed mode ever populates it, so this branch was EVERY editor's steady
    state -- and it reported `last_sync=now` on every 15 s poll, which is
    what kept the tray's lane C dot green while lane C did nothing. Checking
    nothing must not look like a successful sync."""
    lane = _lane_for(fake_syncthing_server, expected_folder_ids=[])
    status = lane.check_once()
    assert status.state == STATE_IDLE
    assert status.last_sync is None
    assert status.detail == "no project folders to check yet"


def test_expected_folder_ids_fn_is_evaluated_per_poll(fake_syncthing_server):
    """The sequencer owns the live folder set; the lane must read it fresh
    each poll rather than from a config key nothing writes."""
    live: list[str] = []
    lane = _lane_for(fake_syncthing_server, expected_folder_ids_fn=lambda: list(live))

    assert lane.check_once().last_sync is None  # nothing selected yet

    live.append("proj-1")
    fake_syncthing_server.fake_state["db_status"]["proj-1"] = {"needTotalItems": 7}
    status = lane.check_once()
    assert status.state == STATE_SYNCING
    assert status.queued == 7


def test_expected_folder_ids_fn_failure_falls_back_to_the_static_list(fake_syncthing_server):
    def boom():
        raise RuntimeError("sequencer not started")

    lane = _lane_for(
        fake_syncthing_server, expected_folder_ids=["proj-1"], expected_folder_ids_fn=boom
    )
    assert lane.check_once().state == STATE_IDLE


def test_check_once_reports_paused_when_every_folder_is_paused(fake_syncthing_server):
    fake_syncthing_server.fake_state["folders"] = [
        {"id": "proj-1", "paused": True,
         "devices": [{"deviceID": "AAAA"}, {"deviceID": "BBBB"}]},
    ]
    lane = _lane_for(fake_syncthing_server, expected_folder_ids=["proj-1"])
    status = lane.check_once()
    assert status.state == STATE_PAUSED
    assert status.last_sync is None


def test_check_once_reports_error_on_folder_error_state(fake_syncthing_server):
    """"folder marker missing" (the aftermath of a failed repath) syncs
    nothing at all, and needTotalItems reports that as a serene 0."""
    fake_syncthing_server.fake_state["db_status"]["proj-1"] = {
        "needTotalItems": 0, "state": "error", "stateChanged": "folder marker missing",
    }
    lane = _lane_for(fake_syncthing_server, expected_folder_ids=["proj-1"])
    status = lane.check_once()
    assert status.state == STATE_ERROR
    assert "folder marker missing" in status.last_error


def test_check_once_reports_error_on_nonzero_error_count(fake_syncthing_server):
    fake_syncthing_server.fake_state["db_status"]["proj-1"] = {
        "needTotalItems": 0, "state": "idle", "errors": 3,
    }
    lane = _lane_for(fake_syncthing_server, expected_folder_ids=["proj-1"])
    assert lane.check_once().state == STATE_ERROR


def test_start_after_a_timed_out_stop_starts_a_fresh_generation(fake_syncthing_server):
    """AUDIT_2 L-2, lane C half."""
    lane = _lane_for(fake_syncthing_server, expected_folder_ids=["proj-1"])
    lane.poll_interval = 60

    class _StubAliveThread:
        def is_alive(self) -> bool:
            return True

    stale = _StubAliveThread()
    stale_event = lane._stop_event
    lane._thread = stale
    stale_event.set()

    lane.start()
    try:
        assert lane._thread is not stale
        assert lane._thread.is_alive()
        assert not lane._stop_event.is_set()
        assert stale_event.is_set()
    finally:
        lane.stop()


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


# -- per-home API-key fallback (owen_laptop, 2026-07-26) --------------------


def _write_config_xml(path, key):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"<configuration><gui><apikey>{key}</apikey></gui></configuration>",
        encoding="utf-8",
    )


def _http_get_requiring(accepted_key, seen_keys):
    """Fake http_get: 403 unless called with `accepted_key`."""
    import urllib.error

    def http_get(url, api_key, timeout):
        seen_keys.append(api_key)
        if api_key != accepted_key:
            raise urllib.error.HTTPError(url, 403, "Forbidden", None, None)
        return {"ping": "pong"} if url.endswith("/ping") else {"folders": []}

    return http_get


def test_get_falls_back_to_the_stock_key_when_the_managed_key_is_rejected(_windows_paths):
    """A preserved-but-stale managed home must not lock the lane out of a
    veteran instance running from the stock home."""
    managed, stock = _windows_paths
    _write_config_xml(managed, "managed-key")
    _write_config_xml(stock, "stock-key")
    seen: list = []
    lane = SyncthingLane(api_key="", http_get=_http_get_requiring("stock-key", seen))
    status = lane.check_once()
    assert status.state == STATE_IDLE
    assert seen[:2] == ["managed-key", "stock-key"]
    # The accepted key is remembered and tried first on the next poll.
    seen.clear()
    lane.check_once()
    assert seen[0] == "stock-key"


def test_check_once_all_keys_rejected_is_not_reported_as_not_running(_windows_paths):
    managed, _stock = _windows_paths
    _write_config_xml(managed, "managed-key")
    lane = SyncthingLane(api_key="", http_get=_http_get_requiring("other-key", []))
    status = lane.check_once()
    assert status.state == STATE_ERROR
    assert "rejected" in status.last_error
    assert status.last_error != "Syncthing not running"


def test_explicit_config_xml_path_scopes_key_discovery(_windows_paths, tmp_path):
    """An explicit config_xml_path is authoritative: the stock home's key
    must NOT be tried (tests and power users rely on that isolation)."""
    _managed, stock = _windows_paths
    _write_config_xml(stock, "stock-key")
    explicit = tmp_path / "explicit" / "config.xml"
    _write_config_xml(explicit, "explicit-key")
    seen: list = []
    lane = SyncthingLane(
        api_key="",
        config_xml_path=explicit,
        http_get=_http_get_requiring("stock-key", seen),
    )
    status = lane.check_once()
    assert status.state == STATE_ERROR
    assert seen == ["explicit-key"]


def test_a_settled_key_costs_no_config_xml_parse_per_request(_windows_paths, monkeypatch):
    """SYNC-8 (2026-08-14): _poll_loop makes roughly 3 + 2N requests every
    15 s, and each one rebuilt the candidate list by ET.parse-ing up to two
    whole config.xml files to re-learn a key that has not changed since boot.
    The key the instance already accepted is now tried alone."""
    managed, stock = _windows_paths
    _write_config_xml(managed, "managed-key")
    _write_config_xml(stock, "stock-key")
    parses: list = []
    real_read = syncthing_lane.read_api_key_from_config
    monkeypatch.setattr(
        syncthing_lane,
        "read_api_key_from_config",
        lambda path: (parses.append(str(path)), real_read(path))[1],
    )
    lane = SyncthingLane(
        api_key="", expected_folder_ids=["x"],
        http_get=_http_get_requiring("managed-key", []),
    )

    lane.check_once()
    assert parses, "sanity: the first poll has to learn the key from disk"

    parses.clear()
    for _ in range(5):
        lane.check_once()
    assert parses == [], "a settled key must not re-parse config.xml per request"


def test_the_stock_home_is_still_reached_when_the_settled_key_starts_failing(_windows_paths):
    """The lazy candidate list must not cost the multi-home fallback its only
    trigger -- a 401/403 still fans out over every known home."""
    managed, stock = _windows_paths
    _write_config_xml(managed, "managed-key")
    _write_config_xml(stock, "stock-key")
    seen: list = []
    lane = SyncthingLane(
        api_key="", expected_folder_ids=["x"],
        http_get=_http_get_requiring("stock-key", seen),
    )
    lane.check_once()
    assert seen[:2] == ["managed-key", "stock-key"]

    # Syncthing is restarted from the managed home: the remembered stock key
    # now 403s, and the fan-out has to happen again.
    seen.clear()
    lane._http_get = _http_get_requiring("managed-key", seen)
    lane.check_once()
    assert seen[:2] == ["stock-key", "managed-key"]


# -- relay detection (AUDIT_2 P3/C-6) ---------------------------------------


def _connections(**by_device):
    return {"connections": dict(by_device)}


def test_summarize_connections_splits_relayed_from_direct():
    """Devices are added with addresses ["dynamic"] and relaysEnabled
    defaults to true, so Syncthing silently falls back to the PUBLIC relay
    pool -- typically 1-5 MB/s, shared and rate-limited. The `type` field is
    the only thing that says so."""
    summary = syncthing_lane.summarize_connections(_connections(
        NASDEV={"connected": True, "type": "relay-client"},
        EDITOR={"connected": True, "type": "tcp-client"},
        QUICDEV={"connected": True, "type": "quic-client"},
    ))
    assert summary["relayed"] == ["NASDEV"]
    assert sorted(summary["direct"]) == ["EDITOR", "QUICDEV"]
    assert summary["devices"]["NASDEV"] == "relay-client"


def test_summarize_connections_ignores_disconnected_devices():
    """"Offline" and "relayed" are different problems with different fixes;
    a disconnected entry keeps a stale type and must not be counted."""
    summary = syncthing_lane.summarize_connections(_connections(
        GONE={"connected": False, "type": "relay-client"},
    ))
    assert summary["relayed"] == []
    assert summary["devices"] == {}


def test_summarize_connections_tolerates_junk():
    for payload in (None, {}, {"connections": None}, {"connections": {"X": "nope"}}):
        summary = syncthing_lane.summarize_connections(payload)
        assert summary["relayed"] == []


def test_relayed_device_shows_up_in_the_lane_detail(fake_syncthing_server):
    """Without this, a slow editor and a relayed editor are indistinguishable
    -- which is precisely the state the fleet is in today."""
    fake_syncthing_server.fake_state["connections"] = _connections(
        NASDEV={"connected": True, "type": "relay-client"},
    )
    lane = _lane_for(fake_syncthing_server, expected_folder_ids=["proj-1"])
    status = lane.check_once()

    assert status.state == STATE_IDLE
    assert "relayed" in status.detail
    assert lane.connection_path_summary()["relayed"] == ["NASDEV"]


def test_direct_connection_adds_no_relay_warning(fake_syncthing_server):
    fake_syncthing_server.fake_state["connections"] = _connections(
        NASDEV={"connected": True, "type": "tcp-client"},
    )
    lane = _lane_for(fake_syncthing_server, expected_folder_ids=["proj-1"])
    status = lane.check_once()

    assert "relayed" not in status.detail
    assert lane.connection_path_summary()["direct"] == ["NASDEV"]


def test_relay_detail_is_appended_not_substituted(fake_syncthing_server):
    """The existing detail still has to answer "what is lane C doing"; the
    path warning is extra information, not a replacement for it."""
    fake_syncthing_server.fake_state["connections"] = _connections(
        NASDEV={"connected": True, "type": "relay-client"},
    )
    lane = _lane_for(fake_syncthing_server, expected_folder_ids=[])
    status = lane.check_once()

    assert "no project folders to check yet" in status.detail
    assert "relayed" in status.detail


def test_missing_connections_endpoint_is_not_a_lane_error(fake_syncthing_server):
    """An older Syncthing 404s here; lane C must keep working and simply
    report no path information."""
    lane = _lane_for(fake_syncthing_server, expected_folder_ids=["proj-1"])
    status = lane.check_once()

    assert status.state == STATE_IDLE
    assert status.last_error is None
    assert lane.connection_path_summary() == {}


# -- URL encoding of folder ids (AUDIT_3 L-10) ------------------------------


def test_db_status_query_encodes_the_folder_id(fake_syncthing_server, monkeypatch):
    """Folder IDs are dashboard project slugs: an "&" or "?" in one used to
    be interpolated raw into the query string, so the request asked about
    something else entirely."""
    lane = _lane_for(fake_syncthing_server, expected_folder_ids=["a b&folder=other"])
    seen: list[str] = []
    real_get = lane._get

    def _spy(path):
        seen.append(path)
        return real_get(path)

    monkeypatch.setattr(lane, "_get", _spy)
    fake_syncthing_server.fake_state["folders"] = [
        {"id": "a b&folder=other", "devices": [{"deviceID": "AAAA"}, {"deviceID": "BBBB"}]}
    ]
    lane.check_once()

    assert "/rest/db/status?folder=a+b%26folder%3Dother" in seen


def test_check_once_reports_outgoing_uploads_as_syncing(fake_syncthing_server):
    """A lane C UPLOAD (this machine -> server) showed 'up to date'
    everywhere for its whole duration (the 400 MB mp3, 2026-07-26):
    needTotalItems only counts downloads. The remote device's own need IS
    the upload in progress."""
    fake_syncthing_server.fake_state["my_id"] = "AAAA"
    fake_syncthing_server.fake_state["remote_completion"] = {
        ("proj-1", "BBBB"): {"completion": 40.0, "needItems": 3, "needBytes": 420_000_000},
    }
    lane = _lane_for(fake_syncthing_server, expected_folder_ids=["proj-1"])
    status = lane.check_once()
    assert status.state == STATE_SYNCING
    assert status.queued == 3
    assert "sending 3 file(s)" in status.detail
    assert "to the server" in status.detail

    # drained -> back to idle
    fake_syncthing_server.fake_state["remote_completion"] = {}
    status = lane.check_once()
    assert status.state == STATE_IDLE


def test_check_once_downloads_take_precedence_over_uploads(fake_syncthing_server):
    fake_syncthing_server.fake_state["my_id"] = "AAAA"
    fake_syncthing_server.fake_state["db_status"]["proj-1"] = {"needTotalItems": 4}
    fake_syncthing_server.fake_state["remote_completion"] = {
        ("proj-1", "BBBB"): {"needItems": 2, "needBytes": 100},
    }
    lane = _lane_for(fake_syncthing_server, expected_folder_ids=["proj-1"])
    status = lane.check_once()
    assert status.state == STATE_SYNCING
    assert status.queued == 4          # the download count, as before


def test_pending_offered_folder_is_setup_not_error(fake_syncthing_server):
    """A freshly ticked project: the server has offered the folder but the
    sequencer hasn't accepted it yet. That flashed C:error on every tick."""
    fake_syncthing_server.fake_state["pending_folders"] = {
        "new-proj": {"offeredBy": {"SERVER": {"label": "2026/X/New"}}}}
    lane = _lane_for(fake_syncthing_server, expected_folder_ids=["new-proj"])
    status = lane.check_once()
    assert status.state == STATE_SYNCING
    assert "setting up" in status.detail

    # a missing folder that is NOT pending stays a real error
    fake_syncthing_server.fake_state["pending_folders"] = {}
    lane2 = _lane_for(fake_syncthing_server, expected_folder_ids=["new-proj"])
    status = lane2.check_once()
    assert status.state == STATE_ERROR
