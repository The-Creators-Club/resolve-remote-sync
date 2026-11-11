"""The new Timeline Cards editor, supervised and proxied at /cards/edit.

2026-11-05, `cards_edit.py` (MulticamPipeline editor/docs/NAS-CUTOVER.md phase
2). The stand-in for the editor is a real child process: a small Python script
at the path the real bundle would have (`editor/dist-server/host.mjs`), run by
`sys.executable` standing in for `node`, that serves HTTP and a WebSocket on
`TC_PORT` and refuses any request without the right `X-TC-Proxy-Secret`, which
is what `createProxyAuth` does. So the supervisor, the environment it builds,
the proxy and the socket relay are all exercised end to end, and no Node, no
vault, no NAS and no editor checkout is needed.

The properties defended, each a way this goes wrong live:

  * OFF MEANS OFF. Disabled: no route, no process. A missing Node or bundle or
    vault: the dashboard boots, the route answers a page that says WHAT is
    missing, health reports it, and nothing is spawned.
  * THE TRUST RULES. A client cannot send `X-TC-*` (the editor believes
    `X-TC-User` only with the secret, but the client must not get to try); the
    dashboard's cookie never reaches the editor; the secret and the signed-in
    user are added by the proxy alone; the editor's environment holds none of
    the dashboard's secrets.
  * SEEK. Range requests come back 206 with the right slice, untouched.
  * THE SOCKET IS AUTHENTICATED HERE. `login_gate` never sees a websocket.
  * A CRASH LOOP RESTARTS WITH A BACKOFF, and says so.
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import textwrap
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from ccsync_dashboard import auth, cards_edit, cards_landing
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "test-secret-not-a-real-one"
AUDIO = bytes(range(256)) * 8                      # 2048 bytes, every value distinct

# The stand-in for editor/dist-server/host.mjs. Python, run by sys.executable.
FAKE_EDITOR = '''
import gzip, json, os, sys
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket

PORT = int(os.environ["TC_PORT"])
SECRET = os.environ["TC_PROXY_SECRET"]
AUDIO = bytes(range(256)) * 8
print("fake editor up on", PORT, flush=True)


def seen(headers):
    return {k.lower(): v for k, v in headers.items()}


async def home(request):
    return HTMLResponse("<html><body>the editor</body></html>")


async def echo(request: Request):
    body = await request.body()
    return JSONResponse({
        "method": request.method, "raw_path": request.scope["raw_path"].decode(),
        "query": request.scope["query_string"].decode(), "headers": seen(request.headers),
        "body_len": len(body), "argv": sys.argv[1:],
        "env": {k: v for k, v in os.environ.items() if k.startswith("TC_")},
        "leaked": [k for k in ("DASH_SESSION_SECRET", "TRUENAS_PW", "DASH_REPORT_TOKEN")
                   if k in os.environ]})


async def audio(request: Request):
    rng = request.headers.get("range")
    if not rng:
        return Response(AUDIO, media_type="audio/ogg", headers={"Accept-Ranges": "bytes"})
    a, _, b = rng.split("=", 1)[1].partition("-")
    a, b = int(a), int(b) if b else len(AUDIO) - 1
    return Response(AUDIO[a:b + 1], status_code=206, media_type="audio/ogg", headers={
        "Content-Range": f"bytes {a}-{b}/{len(AUDIO)}", "Accept-Ranges": "bytes"})


async def gz(request: Request):
    return Response(gzip.compress(b"x" * 5000), media_type="text/plain",
                    headers={"Content-Encoding": "gzip"})


async def sync(ws: WebSocket):
    await ws.accept()
    await ws.send_text(json.dumps({"headers": seen(ws.headers)}))
    while True:
        m = await ws.receive()
        if m["type"] == "websocket.disconnect":
            return
        if m.get("text") is not None:
            await ws.send_text("echo:" + m["text"])
        else:
            await ws.send_bytes(b"echo:" + m["bytes"])


inner = Starlette(routes=[
    Route("/cards/edit/", home),
    Route("/cards/edit/api/echo", echo, methods=["GET", "POST", "PUT"]),
    Route("/cards/edit/api/echo/{rest:path}", echo),
    Route("/cards/edit/media/audio", audio),
    Route("/cards/edit/gz", gz),
    WebSocketRoute("/cards/edit/sync", sync),
])


async def app(scope, receive, send):
    """createProxyAuth: no secret, no answer (403), the socket included."""
    if scope["type"] in ("http", "websocket"):
        got = dict(scope["headers"]).get(b"x-tc-proxy-secret", b"").decode()
        if got != SECRET:
            if scope["type"] == "http":
                await JSONResponse({"code": "proxy-required"}, status_code=403)(scope, receive, send)
            else:
                await send({"type": "websocket.close", "code": 1008})
            return
    await inner(scope, receive, send)


# Bind like node does, not like uvicorn does: uvicorn sets SO_REUSEADDR, which on Windows lets a
# second process bind a port that is already taken, so two stand-ins under parallel test workers
# could share one port and answer each other's dashboards (2026-11-10). Exclusive bind: a lost
# race is an exit, as it is for the real editor.
import socket
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
sock.bind(("127.0.0.1", PORT))
config = uvicorn.Config(app, log_level="warning", ws="websockets")
uvicorn.Server(config).run(sockets=[sock])
'''


def checkout(tmp_path, script=FAKE_EDITOR, name="checkout"):
    src = tmp_path / name
    bundle = src / "editor" / "dist-server"
    bundle.mkdir(parents=True)
    (bundle / "host.mjs").write_text(textwrap.dedent(script), encoding="utf-8")
    return src


def vault(tmp_path):
    root = tmp_path / "vault" / "FF5" / "Civil Defence"
    (root / "Interviewees").mkdir(parents=True)
    cuts = root / "Script Docs" / "Cuts"
    cuts.mkdir(parents=True)
    (cuts / "Part 1 - Ordered.cut.md").write_text("# Part 1\n", encoding="utf-8")
    return tmp_path / "vault", root


def settings_for(tmp_path, src, vault_dir, **kw):
    projects = tmp_path / "tree" / "Projects"
    projects.mkdir(parents=True, exist_ok=True)
    opts = {"cards_editor": True, "cards_node": sys.executable,
            "cards_src": str(src), "cards_vault_root": str(vault_dir)}
    opts.update(kw)
    return Settings(
        db_path=str(tmp_path / "dash.db"), session_secret=SECRET,
        admin_users=frozenset({"owen"}), projects_dir=str(projects), **opts)


def sign_in(client, user="owen"):
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, user))


def wait_ready(app, seconds=40):
    editor = app.state.cards_edit
    end = time.time() + seconds
    while time.time() < end:
        if editor.ready():
            return editor
        time.sleep(0.1)
    raise AssertionError(f"the stand-in editor never answered: {editor.as_dict()}\n"
                         + "\n".join(editor.tail))


@pytest.fixture(scope="module")
def live(tmp_path_factory):
    """One dashboard with the stand-in editor really running behind it."""
    tmp_path = tmp_path_factory.mktemp("edit-live")
    src = checkout(tmp_path)
    vdir, _root = vault(tmp_path)
    app = create_app(settings_for(tmp_path, src, vdir))
    assert app.state.cards_edit_status == cards_edit.MOUNTED, app.state.cards_edit_detail
    with TestClient(app) as client:
        wait_ready(app)
        sign_in(client)
        yield client, app


# ------------------------------------------------------------ off means off

class _NoSpawn:
    """Stands in for the `subprocess` name inside cards_edit: any Popen fails."""
    TimeoutExpired = subprocess.TimeoutExpired
    DEVNULL, PIPE, STDOUT = subprocess.DEVNULL, subprocess.PIPE, subprocess.STDOUT

    spawned = 0

    @classmethod
    def Popen(cls, *a, **k):  # noqa: N802
        cls.spawned += 1
        raise AssertionError("the editor must not be spawned")


def test_disabled_registers_nothing_and_spawns_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(cards_edit, "subprocess", _NoSpawn)
    src = checkout(tmp_path)
    vdir, _ = vault(tmp_path)
    app = create_app(settings_for(tmp_path, src, vdir, cards_editor=False))
    assert app.state.cards_edit is None
    assert app.state.cards_edit_status == cards_edit.DISABLED
    assert "DASH_CARDS_EDITOR" in app.state.cards_edit_detail
    assert not any(getattr(r, "path", "").startswith("/cards/edit") for r in app.routes)
    with TestClient(app) as client:
        sign_in(client)
        assert client.get("/cards/edit/api/echo").status_code == 404
        assert client.get("/cards/edit").status_code in (303, 404)
        health = client.get("/api/v1/health").json()
    assert health["cards"]["editor"]["status"] == cards_edit.DISABLED
    assert _NoSpawn.spawned == 0


@pytest.mark.parametrize("what", ["node", "bundle", "vault", "src"])
def test_a_missing_prerequisite_is_a_page_that_says_which(tmp_path, monkeypatch, what):
    monkeypatch.setattr(cards_edit, "subprocess", _NoSpawn)
    monkeypatch.setattr(cards_edit, "DEFAULT_NODE", str(tmp_path / "no" / "node"))
    monkeypatch.delenv("CARDS_SRC", raising=False)
    src = checkout(tmp_path)
    vdir, _ = vault(tmp_path)
    kw = {}
    if what == "node":
        kw["cards_node"] = str(tmp_path / "nowhere" / "node")
        expect = "DASH_NODE"
    elif what == "bundle":
        (src / "editor" / "dist-server" / "host.mjs").unlink()
        expect = "editor bundle"
    elif what == "vault":
        kw["cards_vault_root"] = str(tmp_path / "gone")
        expect = "vault root is not mounted"
    else:
        kw["cards_src"] = ""
        expect = "DASH_CARDS_SRC"
    app = create_app(settings_for(tmp_path, src, vdir, **kw))
    assert app.state.cards_edit_status == cards_edit.ABSENT
    assert expect in app.state.cards_edit_detail
    with TestClient(app) as client:     # the dashboard boots; the lifespan ran
        sign_in(client)
        page = client.get("/cards/edit/", headers={"accept": "text/html"})
        assert page.status_code == 503
        assert expect in page.text and "/cards/" in page.text
        assert "—" not in page.text
        api = client.get("/cards/edit/api/echo", headers={"accept": "application/json"})
        assert api.status_code == 503 and expect in api.json()["detail"]
        health = client.get("/api/v1/health").json()
        assert client.get("/api/v1/health").status_code == 200
    assert health["cards"]["editor"]["status"] == cards_edit.ABSENT
    assert expect in health["cards"]["editor"]["detail"]
    assert _NoSpawn.spawned == 0


# ---------------------------------------------------------------- the proxy

def test_the_bare_url_redirects_with_its_query(live):
    client, _ = live
    r = client.get("/cards/edit?key=a%2Fb", follow_redirects=False)
    assert r.status_code == 308
    assert r.headers["location"] == "/cards/edit/?key=a%2Fb"


def test_login_is_required(live):
    client, _ = live
    anon = TestClient(client.app)
    page = anon.get("/cards/edit/", headers={"accept": "text/html"}, follow_redirects=False)
    assert page.status_code == 303 and page.headers["location"].startswith("/login")
    for path in ("/cards/edit/api/echo", "/cards/edit/media/audio"):
        r = anon.get(path, follow_redirects=False)
        assert r.status_code == 401, path          # JSON, never a login DOCUMENT
    assert anon.post("/cards/edit/api/echo", content=b"x", follow_redirects=False).status_code in (303, 401, 403)


def test_the_page_comes_through(live):
    client, _ = live
    r = client.get("/cards/edit/")
    assert r.status_code == 200 and "the editor" in r.text


def test_the_proxy_adds_the_secret_and_user_and_strips_what_a_client_sent(live):
    client, app = live
    secret = app.state.cards_edit.secret
    assert len(secret) >= 32
    r = client.get("/cards/edit/api/echo", headers={
        "X-TC-User": "mallory", "x-tc-proxy-secret": "guess", "X-TC-Anything": "1",
        "Authorization": "Bearer dashboard-token", "X-Forwarded-For": "6.6.6.6",
        "Cookie": f"{auth.COOKIE_NAME}={client.cookies.get(auth.COOKIE_NAME)}; theme=dark"})
    assert r.status_code == 200
    seen = r.json()["headers"]
    assert seen["x-tc-user"] == "owen"
    assert seen["x-tc-proxy-secret"] == secret
    assert "x-tc-anything" not in seen
    assert "authorization" not in seen
    assert seen["x-forwarded-for"] != "6.6.6.6"
    assert seen["cookie"] == "theme=dark"          # the dashboard's session stays here
    assert seen["host"].startswith("127.0.0.1:")


def test_a_non_ascii_user_survives_as_a_percent_encoded_header(live):
    client, _ = live
    sign_in(client, "zoë")
    try:
        r = client.get("/cards/edit/api/echo")
    finally:
        sign_in(client)
    assert r.json()["headers"]["x-tc-user"] == "zo%C3%AB"


def test_the_editor_is_started_as_the_live_editor_with_an_allow_listed_env(live):
    client, app = live
    body = client.get("/cards/edit/api/echo").json()
    assert body["argv"] == ["--write"]                 # this IS the live editor
    env = body["env"]
    assert env["TC_MOUNT_BASE"] == "/cards/edit"
    assert env["TC_MOUNT_HOME"] == "/cards/"
    assert env["TC_HOST"] == "127.0.0.1"
    assert env["TC_VAULT"] == app.state.settings.cards_vault_root
    assert env["TC_PORT"] == str(app.state.cards_edit.port)
    assert env["TC_MEDIA_CACHE"].endswith("media")
    assert "cards-edit" in env["TC_WORK"]
    assert body["leaked"] == []


def test_the_path_and_query_arrive_as_sent(live):
    client, _ = live
    r = client.get("/cards/edit/api/echo/%E4%B8%AD%20x%2Fy?key=Civil%20Defence%2FScript%20Docs&n=1")
    assert r.status_code == 200
    body = r.json()
    assert body["raw_path"] == "/cards/edit/api/echo/%E4%B8%AD%20x%2Fy"
    assert body["query"] == "key=Civil%20Defence%2FScript%20Docs&n=1"


def test_range_requests_pass_through_untouched(live):
    client, _ = live
    r = client.get("/cards/edit/media/audio", headers={"Range": "bytes=10-19"})
    assert r.status_code == 206
    assert r.headers["content-range"] == "bytes 10-19/2048"
    assert r.content == AUDIO[10:20]
    tail = client.get("/cards/edit/media/audio", headers={"Range": "bytes=2000-"})
    assert tail.status_code == 206 and tail.content == AUDIO[2000:]
    full = client.get("/cards/edit/media/audio")
    assert full.status_code == 200 and full.content == AUDIO
    assert full.headers["accept-ranges"] == "bytes"
    head = client.head("/cards/edit/media/audio")
    assert head.status_code == 200 and head.headers["content-length"] == "2048"


def test_a_compressed_body_stays_a_matching_pair(live):
    client, _ = live
    r = client.get("/cards/edit/gz")
    assert r.headers["content-encoding"] == "gzip"
    assert r.content == b"x" * 5000                 # decoded once, by the client


def test_a_request_body_is_streamed_through(live):
    client, _ = live
    payload = b"0123456789abcdef" * 65536           # 1 MiB
    r = client.post("/cards/edit/api/echo", content=payload,
                    headers={"content-type": "application/octet-stream",
                             "origin": "http://testserver"})
    assert r.status_code == 200
    body = r.json()
    assert body["method"] == "POST" and body["body_len"] == len(payload)
    # a same-origin Origin is handed on as a loopback one: the editor compares
    # it with the Host it is sent, which is the loopback one too
    assert body["headers"]["origin"] == f"http://127.0.0.1:{body['env']['TC_PORT']}"


def test_a_foreign_origin_is_left_for_the_editor_to_refuse(live):
    client, _ = live
    r = client.get("/cards/edit/api/echo", headers={"origin": "https://evil.example"})
    assert r.json()["headers"]["origin"] == "https://evil.example"


# ----------------------------------------------------------- the websocket

def test_the_socket_is_relayed_both_ways_with_the_trust_headers(live):
    client, app = live
    with client.websocket_connect("/cards/edit/sync", headers={
            "X-TC-User": "mallory", "origin": "http://testserver"}) as ws:
        hello = json.loads(ws.receive_text())["headers"]
        assert hello["x-tc-user"] == "owen"
        assert hello["x-tc-proxy-secret"] == app.state.cards_edit.secret
        assert hello["origin"].startswith("http://127.0.0.1:")
        assert "cookie" not in hello or auth.COOKIE_NAME not in hello["cookie"]
        ws.send_text("hello")
        assert ws.receive_text() == "echo:hello"
        ws.send_bytes(b"\x00\x01\x02")
        assert ws.receive_bytes() == b"echo:\x00\x01\x02"


def test_the_socket_needs_a_login_the_gate_never_sees(live):
    client, _ = live
    anon = TestClient(client.app)
    with pytest.raises(WebSocketDisconnect):
        with anon.websocket_connect("/cards/edit/sync"):
            pass


def test_a_cross_site_socket_is_refused(live):
    client, _ = live
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/cards/edit/sync",
                                      headers={"origin": "https://evil.example"}):
            pass


# ------------------------------------------------------ the supervisor

def test_a_crash_loop_restarts_with_a_backoff_and_says_so(tmp_path):
    src = checkout(tmp_path, "import sys; print('boom', flush=True); sys.exit(3)")
    vdir, _ = vault(tmp_path)
    editor = cards_edit.Editor(settings_for(tmp_path, src, vdir))
    editor.backoff_first = 0.05
    editor.backoff_cap = 0.2
    editor.start()
    try:
        end = time.time() + 30
        while time.time() < end and editor.restarts < cards_edit.CRASHLOOP_AFTER + 1:
            time.sleep(0.05)
        d = editor.as_dict()
        assert d["restarts"] >= cards_edit.CRASHLOOP_AFTER
        assert d["state"] == cards_edit.S_FAILED
        assert "exit 3" in d["last_exit"] and "starting it again" in d["detail"]
        assert "boom" in d["detail"]                 # its last words are in the answer
        assert editor.target() is None               # so the proxy answers the page
    finally:
        editor.stop(grace=5)
    assert editor.state == cards_edit.S_IDLE


def test_stop_ends_the_child(tmp_path):
    src = checkout(tmp_path)
    vdir, _ = vault(tmp_path)
    app = create_app(settings_for(tmp_path, src, vdir))
    with TestClient(app):
        editor = wait_ready(app)
        pid = editor._proc.pid
        proc = editor._proc
    assert proc.poll() is not None, f"the child {pid} outlived the lifespan"
    assert editor.state == cards_edit.S_IDLE


def test_health_reports_the_running_editor(live):
    client, _ = live
    block = client.get("/api/v1/health").json()["cards"]["editor"]
    assert block["status"] == cards_edit.MOUNTED
    assert block["state"] == cards_edit.S_RUNNING and block["port"]


# ------------------------------------------------------ the landing's link

def test_editor_href_names_the_newest_cut_list(tmp_path):
    vdir, root = vault(tmp_path)
    (root / "Script Docs" / "Cuts" / "Newer cut.cut.md").write_text("# n\n", encoding="utf-8")
    import os

    old = time.time() - 1000
    os.utime(root / "Script Docs" / "Cuts" / "Part 1 - Ordered.cut.md", (old, old))
    cards_edit._CUT_CACHE.clear()
    href = cards_edit.editor_href(str(vdir), str(root))
    assert href == "/cards/edit/?key=FF5/Civil%20Defence/Script%20Docs/Cuts/Newer%20cut.cut.md"
    # an episode with no cut list, or outside the vault, goes to the sheet
    (root.parent / "Empty" / "Interviewees").mkdir(parents=True)
    assert cards_edit.editor_href(str(vdir), str(root.parent / "Empty")) == "/cards/edit/"
    assert cards_edit.editor_href(str(vdir), str(tmp_path)) == "/cards/edit/"


def _request(editor):
    state = SimpleNamespace(cards_edit=editor, settings=SimpleNamespace(
        cards_vault_root=""))
    return SimpleNamespace(app=SimpleNamespace(state=state))


def test_the_link_is_drawn_only_while_the_editor_answers(tmp_path):
    vdir, root = vault(tmp_path)
    cards_edit._CUT_CACHE.clear()
    s = settings_for(tmp_path, checkout(tmp_path), vdir)
    editor = cards_edit.Editor(s)
    rows = [{"root": str(root), "slug": "x"}]
    req = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        cards_edit=editor, settings=s)))
    cards_landing._editor_links(req, rows)
    assert rows[0]["editor_href"] == ""               # not running: no link
    editor.adopt(12345)
    cards_landing._editor_links(req, rows)
    assert rows[0]["editor_href"].startswith("/cards/edit/?key=FF5/Civil%20Defence/")
    cards_landing._editor_links(_request(None), rows)  # disabled: blank again
    assert rows[0]["editor_href"] == ""


def test_the_landing_page_draws_the_link(tmp_path, monkeypatch):
    """Through the real template: a Jinja slip here would break /cards/."""
    from test_cards_mount import FAKE_ENGINE, FAKE_HANDLER

    monkeypatch.delenv("CARDS_SRC", raising=False)
    src = checkout(tmp_path)
    pkg = src / "multicam_pipeline" / "cards"
    pkg.mkdir(parents=True)
    (src / "multicam_pipeline" / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "handler.py").write_text(textwrap.dedent(FAKE_HANDLER), encoding="utf-8")
    (pkg / "project_agent.py").write_text(textwrap.dedent(FAKE_ENGINE), encoding="utf-8")
    vdir, _root = vault(tmp_path)
    cards_edit._CUT_CACHE.clear()
    try:
        app = create_app(settings_for(tmp_path, src, vdir, cards_enabled=True))
        client = TestClient(app)            # no lifespan: nothing is spawned
        sign_in(client)
        before = client.get("/cards/")
        assert before.status_code == 200 and "Open in the new editor" not in before.text
        app.state.cards_edit.adopt(12345)
        after = client.get("/cards/")
        assert after.status_code == 200
        assert "Open in the new editor" in after.text
        assert "/cards/edit/?key=FF5/Civil%20Defence/Script%20Docs/Cuts/" in after.text
        # beside the old mount, not over it: the kill-switch worker, the flat
        # PWA files and the landing still belong to /cards
        anon = TestClient(app)
        sw = anon.get("/cards/sw.js")
        assert sw.status_code == 200 and "cards-landing" in sw.text
        assert anon.get("/cards/manifest.webmanifest").status_code == 200
        assert client.get("/cards/edit/", headers={"accept": "text/html"}).status_code == 503
    finally:
        for name in [n for n in sys.modules if n.split(".")[0] == "multicam_pipeline"]:
            del sys.modules[name]
        while str(src) in sys.path:
            sys.path.remove(str(src))


def test_no_em_dash_in_what_an_editor_reads():
    import inspect

    page = cards_edit.unavailable(
        SimpleNamespace(method="GET", headers={"accept": "text/html"}),
        None)
    assert "—" not in page.body.decode()
    assert "—" not in inspect.getsource(cards_landing._editor_links).split('"""')[0]


# -- audit dash-mounts-1 (2026-11-11): the proxy stops pulling when the browser has gone --------

def _run_passthrough(chunks, method, receive):
    sent = []

    async def send(message):
        sent.append(message)

    async def go():
        await asyncio.wait_for(
            cards_edit.Passthrough(chunks, 206, [])({"type": "http", "method": method}, receive, send), 10)

    asyncio.run(go())
    return sent


def test_a_get_whose_browser_leaves_closes_the_upstream_at_once():
    state = {"closed": False, "made": 0}

    async def media():
        try:
            while True:
                state["made"] += 1
                yield b"x" * 65536
                await asyncio.sleep(0)
        finally:
            state["closed"] = True

    calls = {"n": 0}

    async def receive():
        calls["n"] += 1
        if calls["n"] == 1:
            return {"type": "http.request", "body": b"", "more_body": False}
        await asyncio.sleep(0.05)
        return {"type": "http.disconnect"}

    sent = _run_passthrough(media(), "GET", receive)
    assert state["closed"] and state["made"] < 100000
    assert sent[0]["type"] == "http.response.start"
    assert sent[-1].get("more_body") is True          # cut short: no clean end was claimed


def test_a_long_poll_nobody_is_waiting_for_is_let_go():
    """The read timeout to the editor is None; an answer that never came held its upstream
    connection for ever once the browser had left."""
    state = {"closed": False}

    async def never():
        try:
            await asyncio.Event().wait()
            yield b""
        finally:
            state["closed"] = True

    async def receive():
        await asyncio.sleep(0.05)
        return {"type": "http.disconnect"}

    sent = _run_passthrough(never(), "GET", receive)
    assert state["closed"] and [m["type"] for m in sent] == ["http.response.start"]


def test_a_get_that_is_read_to_the_end_is_whole_and_other_methods_never_listen():
    async def three():
        for part in (b"a", b"b", b"c"):
            yield part

    async def quiet():
        await asyncio.Event().wait()

    sent = _run_passthrough(three(), "GET", quiet)
    assert [m.get("body") for m in sent[1:]] == [b"a", b"b", b"c", b""] and sent[-1]["more_body"] is False

    async def must_not_be_read():
        raise AssertionError("a POST's receive belongs to the body gate's replay")

    sent = _run_passthrough(three(), "POST", must_not_be_read)
    assert [m.get("body") for m in sent[1:]] == [b"a", b"b", b"c", b""]


def test_the_editor_is_the_first_thing_the_dashboard_stops(tmp_path, monkeypatch):
    """Audit lens-longrun-dashboard-1 (2026-11-11): the child's SIGTERM is what flushes every open
    cut list, and it was stopped LAST, behind about twenty seconds of joins, in a container that
    `docker stop` kills after ten."""
    from ccsync_dashboard import cards, sorter

    order = []

    async def editor_shutdown(app):
        order.append("editor")

    monkeypatch.setattr(cards_edit, "shutdown", editor_shutdown)
    real_engine, real_sorter = cards.stop_engine, sorter.stop_sorter
    monkeypatch.setattr(cards, "stop_engine", lambda app: (order.append("engine"), real_engine(app))[1])
    monkeypatch.setattr(sorter, "stop_sorter", lambda app: (order.append("sorter"), real_sorter(app))[1])
    app = create_app(Settings(db_path=str(tmp_path / "d.db"), session_secret="s", report_token="t",
                              admin_users=frozenset({"owen"})))
    with TestClient(app):
        assert order == []
    assert order[0] == "editor" and set(order) == {"editor", "engine", "sorter"}, order
