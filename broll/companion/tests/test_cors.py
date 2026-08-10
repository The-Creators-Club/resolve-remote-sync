"""CORS / preflight handling against a real live server."""

from __future__ import annotations

import json


def test_options_preflight_returns_204_with_cors_headers(live_server):
    _srv, client = live_server
    status, headers, body = client.options("/insert")
    assert status == 204
    assert headers.get("Access-Control-Allow-Origin") == "*"
    assert headers.get("Access-Control-Allow-Headers") == "Content-Type"
    assert body == b""


def test_get_status_has_cors_headers(live_server):
    _srv, client = live_server
    status, headers, body = client.get("/status")
    assert status == 200
    assert headers.get("Access-Control-Allow-Origin") == "*"
    assert headers.get("Access-Control-Allow-Headers") == "Content-Type"
    data = json.loads(body)
    assert data["ok"] is True


def test_post_insert_has_cors_headers_even_on_error(live_server):
    _srv, client = live_server
    status, headers, body = client.post_json(
        "/insert",
        {
            "share": "broll",
            "rel_path": "clip.mov",
            "in_frame": 0,
            "out_frame": 10,
            "fps": 25,
            "mode": "append",
        },
    )
    assert status == 200
    assert headers.get("Access-Control-Allow-Origin") == "*"
    data = json.loads(body)
    assert data["ok"] is False


def test_unknown_route_still_has_cors_headers(live_server):
    _srv, client = live_server
    status, headers, _body = client.get("/nope")
    assert status == 404
    assert headers.get("Access-Control-Allow-Origin") == "*"


def test_preflight_allows_private_network_access(live_server):
    """The b-roll UI is moving from :8420 to the cc_sync dashboard's origin, so
    the page will sit on a tailnet address and call 127.0.0.1. Chromium treats
    public -> private as a Private Network Access request and blocks it AT THE
    PREFLIGHT unless the target opts in — the insert would fail before any of
    our handler code ran."""
    _srv, client = live_server
    status, headers, _body = client.options("/insert")
    assert status == 204
    assert headers.get("Access-Control-Allow-Private-Network") == "true"


def test_the_header_is_present_on_real_responses_too(live_server):
    _srv, client = live_server
    _status, headers, _body = client.get("/status")
    assert headers.get("Access-Control-Allow-Private-Network") == "true"
