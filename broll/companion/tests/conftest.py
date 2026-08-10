"""Shared fixtures: a live CompanionServer bound to an ephemeral port."""

from __future__ import annotations

import http.client
import json
import threading

import pytest

from broll_companion import server as server_mod


class CompanionClient:
    """Tiny http.client-based helper for hitting the test server."""

    def __init__(self, port: int):
        self.port = port

    def _connect(self) -> http.client.HTTPConnection:
        return http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)

    def get(self, path: str):
        conn = self._connect()
        conn.request("GET", path)
        resp = conn.getresponse()
        body = resp.read()
        headers = dict(resp.getheaders())
        conn.close()
        return resp.status, headers, body

    def post_json(self, path: str, obj: dict):
        conn = self._connect()
        payload = json.dumps(obj).encode("utf-8")
        conn.request(
            "POST",
            path,
            body=payload,
            headers={"Content-Type": "application/json", "Content-Length": str(len(payload))},
        )
        resp = conn.getresponse()
        body = resp.read()
        headers = dict(resp.getheaders())
        conn.close()
        return resp.status, headers, body

    def options(self, path: str):
        conn = self._connect()
        conn.request("OPTIONS", path)
        resp = conn.getresponse()
        body = resp.read()
        headers = dict(resp.getheaders())
        conn.close()
        return resp.status, headers, body


@pytest.fixture
def companion_config():
    return {"server_url": "http://127.0.0.1:8000", "mounts": {}}


@pytest.fixture
def live_server(companion_config, monkeypatch):
    """Start a real CompanionServer on an ephemeral loopback port."""
    # Never actually try to talk to Resolve during HTTP-layer tests.
    monkeypatch.setattr(server_mod.resolve_bridge, "try_connect", lambda: False)

    srv = server_mod.make_server(companion_config, host="127.0.0.1", port=0)
    port = srv.server_address[1]
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield srv, CompanionClient(port)
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5)
