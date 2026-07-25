"""In-process fake Syncthing REST server for collector tests.

Same approach as companion/tests/test_syncthing_lane.py's _FakeSyncthingHandler,
extended with the endpoints the dashboard collector uses. Mutate
`server.state` between requests to simulate changes; set state["down"] = True
to make every request fail with a 500.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

SERVER_ID = "SRVSRVS-SRVSRVS-SRVSRVS-SRVSRVS-SRVSRVS-SRVSRVS-SRVSRVS-SRVSRVS"
EDITOR_ID = "EDITORA-EDITORA-EDITORA-EDITORA-EDITORA-EDITORA-EDITORA-EDITORA"
EDITOR2_ID = "EDITORB-EDITORB-EDITORB-EDITORB-EDITORB-EDITORB-EDITORB-EDITORB"


def default_state() -> dict:
    return {
        "down": False,
        "my_id": SERVER_ID,
        "devices": [
            {"deviceID": SERVER_ID, "name": "server"},
            {"deviceID": EDITOR_ID, "name": "jsmith"},
            {"deviceID": EDITOR2_ID, "name": EDITOR2_ID},  # unmapped: never renamed
        ],
        "folders": [
            {
                "id": "2025-ff4-nuclear",
                "label": "2025/FF4/Nuclear",
                "path": "/data/Projects/2025/FF4/Nuclear",
                "devices": [{"deviceID": SERVER_ID}, {"deviceID": EDITOR_ID},
                            {"deviceID": EDITOR2_ID}],
            },
        ],
        "pending_devices": {},  # deviceID -> {"name": ..., "address": ...}
        "connections": {EDITOR_ID: {"connected": True, "address": "100.1.2.3:22000"}},
        "db_status": {"2025-ff4-nuclear": {"globalFiles": 120, "globalBytes": 5_000_000}},
        # (folder, device) -> completion payload
        "completion": {
            ("2025-ff4-nuclear", EDITOR_ID): {
                "completion": 62.5, "needItems": 45, "needBytes": 1_000_000, "needDeletes": 0},
            ("2025-ff4-nuclear", EDITOR2_ID): {
                "completion": 100.0, "needItems": 0, "needBytes": 0, "needDeletes": 0},
        },
        # (folder, device) -> list of file dicts served through pagination
        "remoteneed": {
            ("2025-ff4-nuclear", EDITOR_ID): [
                {"name": f"Audio/Music/track{i:03}.wav", "size": 1000 + i} for i in range(45)
            ],
        },
    }


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        state = self.server.state  # type: ignore[attr-defined]
        if state["down"]:
            self._json({"error": "down"}, status=500)
            return
        url = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}
        if url.path == "/rest/config/folders":
            state["folders"].append(body)
            self._json({})
        elif url.path == "/rest/config/devices":
            state["devices"].append(body)
            state["pending_devices"].pop(body.get("deviceID"), None)
            self._json({})
        elif url.path == "/rest/db/ignores":
            state.setdefault("ignores", {})[q.get("folder")] = body.get("ignore", [])
            self._json({})
        else:
            self._json({"error": "not found"}, status=404)

    def _json(self, payload, status=200):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_PUT(self):
        state = self.server.state  # type: ignore[attr-defined]
        if state["down"]:
            self._json({"error": "down"}, status=500)
            return
        url = urlparse(self.path)
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}
        if url.path.startswith("/rest/config/folders/"):
            folder_id = url.path.rsplit("/", 1)[1]
            for i, f in enumerate(state["folders"]):
                if f["id"] == folder_id:
                    state["folders"][i] = body
                    state.setdefault("put_folder_calls", []).append(body)
                    self._json({})
                    return
            self._json({"error": "no such folder"}, status=404)
        elif url.path.startswith("/rest/config/devices/"):
            device_id = url.path.rsplit("/", 1)[1]
            for i, d in enumerate(state["devices"]):
                if d["deviceID"] == device_id:
                    state["devices"][i] = body
                    self._json({})
                    return
            self._json({"error": "no such device"}, status=404)
        else:
            self._json({"error": "not found"}, status=404)

    def do_GET(self):
        state = self.server.state  # type: ignore[attr-defined]
        if state["down"]:
            self._json({"error": "down"}, status=500)
            return
        url = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        if url.path.startswith("/rest/config/folders/"):
            folder_id = url.path.rsplit("/", 1)[1]
            match = next((f for f in state["folders"] if f["id"] == folder_id), None)
            if match is None:
                self._json({"error": "no such folder"}, status=404)
            else:
                self._json(match)
        elif url.path == "/rest/system/ping":
            self._json({"ping": "pong"})
        elif url.path == "/rest/system/status":
            self._json({"myID": state["my_id"]})
        elif url.path == "/rest/config":
            self._json({"folders": state["folders"], "devices": state["devices"]})
        elif url.path == "/rest/cluster/pending/devices":
            self._json(state["pending_devices"])
        elif url.path == "/rest/system/connections":
            self._json({"connections": state["connections"]})
        elif url.path == "/rest/db/status":
            self._json(state["db_status"].get(q.get("folder"), {}))
        elif url.path == "/rest/db/completion":
            key = (q.get("folder"), q.get("device"))
            self._json(state["completion"].get(key, {"completion": 0, "needItems": 0,
                                                     "needBytes": 0, "needDeletes": 0}))
        elif url.path == "/rest/db/remoteneed":
            key = (q.get("folder"), q.get("device"))
            page, perpage = int(q.get("page", 1)), int(q.get("perpage", 100))
            all_files = state["remoteneed"].get(key, [])
            start = (page - 1) * perpage
            self._json({"files": all_files[start:start + perpage],
                        "page": page, "perpage": perpage})
        else:
            self._json({"error": "not found"}, status=404)


class FakeSyncthing:
    def __init__(self):
        self.httpd = HTTPServer(("127.0.0.1", 0), _Handler)
        self.httpd.state = default_state()  # type: ignore[attr-defined]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def state(self) -> dict:
        return self.httpd.state  # type: ignore[attr-defined]

    @property
    def url(self) -> str:
        host, port = self.httpd.server_address
        return f"http://{host}:{port}"

    def start(self):
        self.thread.start()
        return self

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()
