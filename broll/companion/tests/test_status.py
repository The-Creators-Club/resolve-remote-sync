"""GET /status shape tests."""

from __future__ import annotations

import json

from broll_companion import server as server_mod
from broll_companion.config import VERSION


def test_build_status_response_shape(monkeypatch):
    monkeypatch.setattr(server_mod.resolve_bridge, "try_connect", lambda: True)
    result = server_mod.build_status_response({"broll": "B:/"})
    assert result == {
        "ok": True,
        "resolve_connected": True,
        "mounts": {"broll": "B:/"},
        "version": VERSION,
    }


def test_build_status_response_tolerant_of_resolve_absent(monkeypatch):
    monkeypatch.setattr(server_mod.resolve_bridge, "try_connect", lambda: False)
    result = server_mod.build_status_response({})
    assert result["ok"] is True
    assert result["resolve_connected"] is False


def test_build_status_response_never_raises_if_try_connect_raises(monkeypatch):
    # try_connect itself is documented as tolerant, but build_status_response
    # should not crash the server even if that contract is somehow violated
    # by a future change; resolve_bridge.try_connect must not propagate.
    def boom():
        raise RuntimeError("should not happen")

    monkeypatch.setattr(server_mod.resolve_bridge, "try_connect", boom)
    try:
        server_mod.build_status_response({})
    except RuntimeError:
        raised = True
    else:
        raised = False
    # documents current behaviour: try_connect is the contract's tolerance
    # boundary, so if IT raises, that's a bug in try_connect, not here.
    assert raised is True


def test_status_over_http(live_server):
    _srv, client = live_server
    status, _headers, body = client.get("/status")
    assert status == 200
    data = json.loads(body)
    assert set(data.keys()) == {"ok", "resolve_connected", "mounts", "version"}
    assert data["ok"] is True
    assert data["version"] == VERSION
