"""The field page over HTTP: what it serves, who may talk to it, and the buttons' routes."""
from __future__ import annotations

import http.client
import json
import re
import threading
import time
from pathlib import Path

import pytest

from ccsync_companion import field_server, loopback_guard, tray
from test_field_service import SERIAL, World, card_of


@pytest.fixture()
def served(tmp_path):
    w = World(tmp_path)
    server = field_server.make_server(w.cfg, w.svc, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    w.server, w.port = server, server.server_address[1]
    yield w
    server.shutdown()
    server.server_close()


def call(w, method, path, body=None, headers=None, host=None, raw=None):
    conn = http.client.HTTPConnection("127.0.0.1", w.port, timeout=10)
    h = dict(headers or {})
    if host is not None:
        h["Host"] = host
    data = raw
    if body is not None:
        data = json.dumps(body).encode()
        h.setdefault("Content-Type", "application/json")
    conn.request(method, path, body=data, headers=h)
    r = conn.getresponse()
    payload = r.read()
    conn.close()
    try:
        parsed = json.loads(payload)
    except ValueError:
        parsed = payload
    return r.status, parsed, dict(r.getheaders())


def own(w):
    return {"Origin": f"http://127.0.0.1:{w.port}"}


# -------------------------------------------------------------------------------- the page
def test_the_server_binds_loopback_only(served):
    assert served.server.server_address[0] == "127.0.0.1"


def test_the_page_and_its_two_files_are_served_from_disk(served):
    for path, ctype in (("/field", "text/html"), ("/field/", "text/html"),
                        ("/field/field.css", "text/css"), ("/field/field.js", "text/javascript")):
        status, body, headers = call(served, "GET", path)
        assert status == 200 and headers["Content-Type"].startswith(ctype), path
        assert headers["Cache-Control"] == "no-store" and headers["X-Content-Type-Options"] == "nosniff"
    status, body, headers = call(served, "GET", "/field")
    assert "default-src 'none'" in headers["Content-Security-Policy"] and headers["X-Frame-Options"] == "DENY"
    assert b"Field backup" in body and b"/field/field.js" in body


def test_the_page_reaches_for_nothing_outside_this_computer():
    """Offline means offline: no CDN, no web font, no analytics, not even an absolute URL."""
    root = Path(field_server.ASSET_DIR)
    for name in ("index.html", "field.css", "field.js"):
        text = (root / name).read_text(encoding="utf-8")
        for url in re.findall(r"https?://[^\s\"')]+", text):
            assert re.match(r"https?://(127\.0\.0\.1|localhost)", url), f"{name} reaches for {url}"
        assert "@import" not in text and "url(" not in text.replace("url()", "")
        assert not re.search(r"\bsrc=\"(?!/field/)", text)


def test_the_page_script_never_writes_server_text_as_html():
    js = (Path(field_server.ASSET_DIR) / "field.js").read_text(encoding="utf-8")
    assert "innerHTML" not in js and "document.write" not in js and "eval(" not in js


def test_an_unknown_path_is_a_404_in_json(served):
    status, body, _ = call(served, "GET", "/field/nope")
    assert status == 404 and body["ok"] is False
    assert call(served, "GET", "/")[0] == 404


# ---------------------------------------------------------------------------------- the guard
def test_a_request_that_dials_loopback_by_another_name_is_refused(served):
    status, body, headers = call(served, "GET", "/field/api/state", host="evil.example.com")
    assert status == 403 and "Access-Control-Allow-Origin" not in headers
    assert call(served, "GET", "/field/api/state", host=f"localhost:{served.port}")[0] == 200


def test_another_pages_origin_is_refused_and_gets_no_cors_headers(served):
    status, body, headers = call(served, "GET", "/field/api/state", headers={"Origin": "https://evil.example.com"})
    assert status == 403 and "Access-Control-Allow-Origin" not in headers
    status, _, _ = call(served, "POST", "/field/api/sync", {}, headers={"Origin": "http://127.0.0.1:9999"})
    assert status == 403                                                  # another local page, another port


def test_the_page_may_talk_to_itself_and_the_dashboards_origin_may_too(served):
    assert call(served, "POST", "/field/api/remember", {"dests": ["x"]}, headers=own(served))[0] == 200
    assert call(served, "POST", "/field/api/remember", {"dests": ["x"]}, headers={"Origin": "http://dash.test"})[0] == 200


def test_a_post_without_an_origin_needs_the_loopback_token(served):
    assert call(served, "POST", "/field/api/remember", {"dests": []})[0] == 403
    token = loopback_guard.read_token()
    assert token
    assert call(served, "POST", "/field/api/remember", {"dests": []}, headers={loopback_guard.TOKEN_HEADER: token})[0] == 200
    assert call(served, "POST", "/field/api/remember", {"dests": []}, headers={loopback_guard.TOKEN_HEADER: "wrong"})[0] == 403


def test_a_post_must_be_json(served):
    status, _, _ = call(served, "POST", "/field/api/sync", raw=b"x=1", headers={**own(served), "Content-Type": "text/plain"})
    assert status == 415


def test_a_bad_or_oversized_body_is_a_400_or_413_not_a_crash(served):
    h = {**own(served), "Content-Type": "application/json"}
    assert call(served, "POST", "/field/api/copy", raw=b"{nope", headers=h)[0] == 400
    assert call(served, "POST", "/field/api/copy", raw=b"[1,2]", headers=h)[0] == 400
    assert call(served, "POST", "/field/api/copy", raw=b"{" + b" " * 70_000 + b"}", headers=h)[0] == 413


# ---------------------------------------------------------------------------------- the routes
def test_state_lists_the_card_the_drives_and_the_copier(served):
    status, st, _ = call(served, "GET", "/field/api/state?refresh=1")
    assert status == 200 and st["ok"]
    assert [c["serial"] for c in st["cards"]] == [SERIAL]
    assert {d["id"] for d in st["destinations"]} == {"vol:AAAA0001", "vol:BBBB0001", "vol:LLLL0001"}
    assert st["copier"]["name"] and "sync" in st and st["machine"] == "razer"


def test_copy_runs_to_the_end_and_the_state_follows_it(served):
    call(served, "POST", "/field/api/kind", {"volumeId": "vol:LLLL0001", "kind": "ours"}, headers=own(served))
    status, got, _ = call(served, "POST", "/field/api/copy", {"serial": SERIAL, "dests": ["vol:AAAA0001", "vol:LLLL0001"]},
                          headers=own(served))
    assert status == 200 and got["ok"] and len(got["run"]["lanes"]) == 2
    for _ in range(300):
        st = call(served, "GET", "/field/api/state")[1]
        if st["runs"] and not st["runs"][0]["running"]:
            break
        time.sleep(0.05)
    lanes = st["runs"][0]["lanes"]
    assert {l["state"] for l in lanes} == {"done"} and all(l["percent"] == 100 for l in lanes)
    assert card_of(st)["verdict"]["safeToFormat"]
    assert set(st["lastDests"]) == {"vol:AAAA0001", "vol:LLLL0001"}


def test_a_refusal_comes_back_as_a_409_with_the_sentence(served):
    status, got, _ = call(served, "POST", "/field/api/copy", {"serial": SERIAL, "dests": []}, headers=own(served))
    assert status == 409 and "at least one" in got["error"]
    status, got, _ = call(served, "POST", "/field/api/copy", {"serial": "NOPE", "dests": ["vol:AAAA0001"]}, headers=own(served))
    assert status == 409 and "not in a reader" in got["error"]


def test_folders_and_kinds_are_set_from_the_page(served):
    folder = str(served.drives["L"] / "FieldBackup")
    assert call(served, "POST", "/field/api/folder", {"path": folder}, headers=own(served))[1]["folders"]
    assert call(served, "POST", "/field/api/folder", {"path": "relative"}, headers=own(served))[0] == 409
    assert call(served, "POST", "/field/api/kind", {"volumeId": "vol:BBBB0001", "kind": "ours"}, headers=own(served))[0] == 200
    assert call(served, "POST", "/field/api/kind", {"volumeId": "vol:BBBB0001", "kind": "bogus"}, headers=own(served))[0] == 409
    st = call(served, "GET", "/field/api/state?refresh=1")[1]
    assert {d["kind"] for d in st["destinations"] if d["id"] == "vol:BBBB0001"} == {"ours"}
    assert any(d["type"] == "folder" for d in st["destinations"])
    assert call(served, "POST", "/field/api/folder/remove", {"path": folder}, headers=own(served))[1]["folders"] == []


def test_cancel_and_sync_answer(served):
    assert call(served, "POST", "/field/api/cancel", {"runId": "nope"}, headers=own(served))[1] == {"ok": False}
    status, got, _ = call(served, "POST", "/field/api/sync", {}, headers=own(served))
    assert status == 200 and got["ok"]
    assert call(served, "POST", "/field/api/unknown", {}, headers=own(served))[0] == 404


# ----------------------------------------------------------------------- start, stop, the tray
def test_the_port_and_url_follow_the_config():
    assert field_server.configured_port({}) == 8898
    assert field_server.configured_port({"field_server_port": "9001"}) == 9001
    assert field_server.configured_port({"field_server_port": "banana"}) == 8898
    assert field_server.configured_port({"field_server_port": 0}) == 8898
    assert field_server.page_url({"field_server_port": 9001}) == "http://127.0.0.1:9001/field"
    assert not field_server.is_enabled({"field_server_enabled": False})


def test_start_does_nothing_when_off_and_survives_a_taken_port(tmp_path, monkeypatch):
    w = World(tmp_path)
    assert field_server.start_server({"field_server_enabled": False}, w.svc) is None
    blocker = field_server.make_server(w.cfg, w.svc, port=0)
    try:
        port = blocker.server_address[1]
        assert field_server.start_server({**w.cfg, "field_server_port": port}, w.svc) is None
        assert field_server.last_bind_error()
    finally:
        blocker.server_close()
    free = field_server.make_server(w.cfg, w.svc, port=0)             # a port that is free is taken, and logged
    port = free.server_address[1]
    free.server_close()
    server = field_server.start_server({**w.cfg, "field_server_port": port}, w.svc)
    try:
        assert server is not None and field_server.last_bind_error() == ""
        assert field_server.page_url(w.cfg, server) == f"http://127.0.0.1:{port}/field"
    finally:
        field_server.stop(server)


def test_stop_cancels_a_running_copy_and_releases_the_port(tmp_path):
    w = World(tmp_path)
    server = field_server.make_server(w.cfg, w.svc, port=0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    field_server.stop(server)
    field_server.stop(None)                                  # never raises
    with pytest.raises(OSError):
        http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=1).request("GET", "/field")


class FakeApp:
    def __init__(self, url):
        self.url = url
        self.field_service = object()

    def field_page_url(self):
        return self.url


def test_the_tray_item_opens_the_page_or_says_why_not(monkeypatch):
    opened, said = [], []
    monkeypatch.setattr(tray, "_spawn", lambda app, label, fn: fn())
    monkeypatch.setattr(tray, "_open_dashboard", lambda url, app=None: opened.append(url) or True)
    monkeypatch.setattr(tray, "_notify", lambda app, msg: said.append(msg))
    tray.action_open_field(FakeApp("http://127.0.0.1:8898/field"))
    assert opened == ["http://127.0.0.1:8898/field"] and not said
    tray.action_open_field(FakeApp(""))
    assert len(opened) == 1 and "not running" in said[0]
