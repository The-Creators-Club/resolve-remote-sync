"""The Timeline Cards page, mounted in the dashboard at /cards.

docs/TIMELINE-CARDS-INTO-CCSYNC.md phase 3 (2026-08-30). Everything here runs
against a FAKE `multicam_pipeline.cards` package built in a tmp dir -- a real
`BaseHTTPRequestHandler` with the same idioms the real one uses (send_response
/ send_header / end_headers / wfile.write, and a byte-range branch), and a
stub engine that records what it was constructed with. So this suite needs no
checkout, no vault, no PostgreSQL and no Resolve, and it still exercises the
shim end to end.

The properties defended, each of them a way this goes wrong live:

  * TRI-STATE, AND NEVER FATAL. No checkout, no vault, a checkout that does
    not import, an engine that will not start: four different sentences, four
    dashboards that still boot and still serve the fleet page.
  * THE LOGIN GATE COVERS THE WHOLE PREFIX. `/cards/` is a whole cut of a
    documentary and the page can drive Resolve; the three `/cards/agent/*`
    fleet routes are the only carve-out, and they were pinned in phase 2.
  * THE ROUTES ANSWER BYTE FOR BYTE. A JSON GET through the shim is the
    engine's own JSON; a Range GET is a 206 with the right slice, the right
    Content-Range and the right ETag.
  * `/api/restart` NEVER REACHES THE HANDLER. In the standalone server it
    re-execs the process. Here that process is the dashboard.
  * THE TUNNEL GOES IN-PROCESS. With the page mounted, `/cards/agent/*` calls
    the engine directly -- no HTTP hop, no upstream token, and the same
    verified-identity name rule as phase 2.
  * THE ENGINE STOPS WITH THE APP. Starlette runs no lifespan for a mounted
    app; the dashboard's own shutdown hook is the only thing that will ever
    stop those threads.
"""
from __future__ import annotations

import json
import sys
import textwrap
import time

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth, cards, cards_pool
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "test-secret-not-a-real-one"
TOKEN = "companion-token-not-a-real-one"

# What the fake handler serves at /audio, so the Range test has real bytes.
AUDIO_BYTES = bytes(range(256)) * 8          # 2048 bytes, every value distinct


FAKE_HANDLER = '''
"""A minimal stand-in for multicam_pipeline.cards.handler."""
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse
import gzip
import json
import os


def make_handler(engine):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype="application/json; charset=utf-8"):
            data = body if isinstance(body, bytes) else body.encode("utf-8")
            # The real handler's own condition, verbatim: a full state is
            # ~660 KB of JSON and ~90 KB gzipped, and the page fetches it on
            # every version.
            enc = None
            if (len(data) >= 2048 and "json" in ctype
                    and "gzip" in (self.headers.get("Accept-Encoding") or "")):
                data = gzip.compress(data, 5)
                enc = "gzip"
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            if enc:
                self.send_header("Content-Encoding", enc)
                self.send_header("Vary", "Accept-Encoding")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            u = urlparse(self.path)
            if u.path == "/api/state":
                self._send(200, json.dumps(engine.state(u.query)))
            elif u.path == "/audio":
                self._serve_range(engine.audio_path)
            elif u.path == "/agent/pending":
                self._send(200, json.dumps({"reached": "the handler"}))
            elif u.path == "/":
                self._send(200, "<!doctype html><title>Timeline Cards</title>",
                           "text/html; charset=utf-8")
            elif u.path == "/big":
                self._send(200, json.dumps({"pad": "x" * 8000}))
            elif u.path == "/boom":
                raise RuntimeError("a route that blew up")
            elif u.path == "/silent":
                return
            else:
                self._send(404, "not found", "text/plain")

        def _serve_range(self, path):
            """The real handler's shared byte-range code, condensed: the shim
            has to carry a 206 with its validators, not just a 200."""
            st = os.stat(path)
            size = st.st_size
            etag = '"%d-%d"' % (size, int(st.st_mtime))
            rng = self.headers.get("Range") or ""
            if_range = (self.headers.get("If-Range") or "").strip()
            if if_range and if_range != etag:
                rng = ""
            start, end = 0, size - 1
            if rng.startswith("bytes="):
                parts = rng[6:].split("-")
                if parts[0]:
                    start = min(int(parts[0]), size - 1)
                if len(parts) > 1 and parts[1]:
                    end = min(int(parts[1]), size - 1)
            length = end - start + 1
            self.send_response(206 if rng else 200)
            self.send_header("Content-Type", "audio/ogg")
            self.send_header("ETag", etag)
            self.send_header("Accept-Ranges", "bytes")
            if rng:
                self.send_header("Content-Range",
                                 "bytes %d-%d/%d" % (start, end, size))
            self.send_header("Content-Length", str(length))
            self.end_headers()
            with open(path, "rb") as fh:
                fh.seek(start)
                left = length
                while left > 0:
                    buf = fh.read(min(1 << 16, left))
                    if not buf:
                        break
                    self.wfile.write(buf)
                    left -= len(buf)

        def do_POST(self):
            u = urlparse(self.path)
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)) or 0)
            if u.path == "/api/restart":
                engine.restarted = True
                self._send(200, json.dumps({"ok": True}))
                return
            engine.posts.append((u.path, body.decode("utf-8")))
            self._send(200, json.dumps({"ok": True, "path": u.path}))

    return Handler
'''

FAKE_ENGINE = '''
"""A minimal stand-in for multicam_pipeline.cards.project_agent."""


class ProjectAgentEngine:
    def __init__(self, path, root, token, db_host=None, db_name=None,
                 readonly=False, write_allow=None, backup_dir=None,
                 data_dir=None):
        self.built = dict(path=path, root=root, token=token, db_host=db_host,
                          db_name=db_name, write_allow=list(write_allow or ()),
                          backup_dir=backup_dir, data_dir=data_dir)
        self.root = root
        self.agent_name = None
        self.access_key = "a key that must be cleared"
        self.media_map = []
        self.claude_runner = None
        self.started = False
        self.stopped = False
        self.ticks = 0
        self.restarted = False
        self.posts = []
        self.audio_path = ""
        self.handed_back = []
        self.agent_pushes = []

    # -- lifecycle
    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def tick(self):
        self.ticks += 1

    # -- what the page reads
    def state(self, query):
        return {"version": 7, "query": query, "root": self.root}

    # -- the agent protocol
    def agent_state(self, body):
        self.agent_pushes.append(body.get("name"))
        return {"ok": True, "saw": body}

    def agent_pending(self, wait):
        return {"wait": wait, "req": None}

    def agent_result(self, body):
        return {"ok": True, "result": body}

    def unhand(self, out):
        self.handed_back.append(out)
'''


@pytest.fixture(scope="module")
def fake_src(tmp_path_factory):
    """A checkout with just enough `multicam_pipeline.cards` in it.

    Module-scoped and torn down by name: `multicam_pipeline` is a top-level
    package, so a second one on sys.path in the same process would be the
    first one again (broll.py's `app` problem, one package name over).
    """
    src = tmp_path_factory.mktemp("cards-checkout")
    pkg = src / "multicam_pipeline" / "cards"
    pkg.mkdir(parents=True)
    (src / "multicam_pipeline" / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "handler.py").write_text(textwrap.dedent(FAKE_HANDLER), encoding="utf-8")
    (pkg / "project_agent.py").write_text(textwrap.dedent(FAKE_ENGINE), encoding="utf-8")
    yield str(src)
    for name in [n for n in sys.modules if n.split(".")[0] == "multicam_pipeline"]:
        del sys.modules[name]
    while str(src) in sys.path:
        sys.path.remove(str(src))


def make_settings(tmp_path, **kw):
    projects = tmp_path / "tree" / "Projects"
    projects.mkdir(parents=True, exist_ok=True)
    return Settings(
        db_path=str(tmp_path / "dash.db"), session_secret=SECRET,
        admin_users=frozenset({"owen"}), projects_dir=str(projects),
        report_token=TOKEN, **kw)


def make_vault(tmp_path, *names):
    """A vault with one episode folder per name, and a clip in the first.

    An episode is a folder with `Interviewees` or `Clips` in it -- the rule
    `cards_pool.has_transcripts` applies, and the one the other repo's
    roots.py has always applied. The shape is the real one:
    `<vault>/<show>/<episode>`.
    """
    vault = tmp_path / "vault"
    made = []
    for name in names or ("Civil Defence",):
        root = vault / "FF5" / name
        (root / "Interviewees").mkdir(parents=True)
        (root / "Script Docs").mkdir(parents=True, exist_ok=True)
        made.append(root)
    audio = made[0] / "Script Docs" / "clip.opus"
    audio.write_bytes(AUDIO_BYTES)
    return vault, made, audio


def open_episode(app, root, timeout=5.0):
    """Open one episode and WAIT for it. -> the entry.

    The pool builds in a thread on purpose (a real engine reads an episode
    off a network share as it comes up, and no request may wait on that), so
    a test that wants a page behind a URL waits here.
    """
    entry, refusal = app.state.cards_pool.open(str(root))
    assert entry is not None, refusal
    end = time.monotonic() + timeout
    while entry.state == cards_pool.LOADING and time.monotonic() < end:
        time.sleep(0.01)
    assert entry.state == cards_pool.READY, entry.detail
    return entry


def engine_of(app, slug=""):
    """The engine behind one open episode -- the only one, unless named."""
    entries = [e for e in app.state.cards_pool.entries()
               if not slug or e.slug == slug]
    assert entries, "no episode is open"
    return entries[0].engine


def U(app, path="/", slug=""):
    """The URL of a path inside an open episode's page."""
    entries = [e for e in app.state.cards_pool.entries()
               if not slug or e.slug == slug]
    assert entries, "no episode is open"
    return f"/cards/p/{entries[0].slug}{path}"


@pytest.fixture
def mounted(tmp_path, fake_src, monkeypatch):
    """A dashboard with ONE episode open, plus a real file at /audio.

    Since 2026-09-14 the mount carries a POOL rather than an engine: `/cards/`
    is a landing page that needs no engine at all, and the page itself lives
    under `/cards/p/<slug>/`. A suite that wants the page opens an episode
    first, exactly as a person does.
    """
    monkeypatch.delenv("CARDS_SRC", raising=False)
    vault, roots, audio = make_vault(tmp_path, "Civil Defence", "Framing Formosa")
    settings = make_settings(
        tmp_path, cards_enabled=True, cards_src=fake_src,
        cards_vault_root=str(vault), cards_db_host="192.168.0.102",
        cards_db_name="FF5", cards_db_write_allow="FF5lab, FF5",
        cards_media_map="P:\\=/media/;X:\\=/vault/",
        cards_token="cards-token-not-a-real-one")
    app = create_app(settings)
    assert app.state.cards_status == cards.MOUNTED, app.state.cards_detail
    entry = open_episode(app, roots[0])
    entry.engine.audio_path = str(audio)
    with TestClient(app) as client:
        client.cookies.set(auth.COOKIE_NAME,
                           auth.make_session_cookie(SECRET, "owen"))
        yield client, app


def fleet_headers(editor="jsmith"):
    return {"X-CCSync-Token": TOKEN,
            "X-CCSync-Identity": auth.make_identity_token(SECRET, editor)}


# --------------------------------------------------------------- the tri-state

def test_no_checkout_is_disabled_and_the_dashboard_still_boots(tmp_path, monkeypatch):
    monkeypatch.delenv("CARDS_SRC", raising=False)
    app = create_app(make_settings(tmp_path))
    assert app.state.cards_status == cards.DISABLED
    assert app.state.cards_mounted is False
    assert "DASH_CARDS_ENABLED" in app.state.cards_detail
    with TestClient(app) as client:
        assert client.get("/api/v1/health").status_code == 200


def test_enabled_with_no_source_says_which_variable(tmp_path, monkeypatch):
    monkeypatch.delenv("CARDS_SRC", raising=False)
    app = create_app(make_settings(tmp_path, cards_enabled=True))
    assert app.state.cards_status == cards.DISABLED
    assert "DASH_CARDS_SRC" in app.state.cards_detail


def test_a_source_that_is_not_there_is_absent(tmp_path, monkeypatch):
    monkeypatch.delenv("CARDS_SRC", raising=False)
    app = create_app(make_settings(
        tmp_path, cards_enabled=True, cards_src=str(tmp_path / "nope"),
        cards_vault_root=str(tmp_path)))
    assert app.state.cards_status == cards.ABSENT
    assert "not there" in app.state.cards_detail


def test_no_vault_is_disabled_with_the_reason(tmp_path, fake_src, monkeypatch):
    """"Blank = /cards says no vault mounted" -- the mount is optional and so
    are its two bind mounts."""
    monkeypatch.delenv("CARDS_SRC", raising=False)
    app = create_app(make_settings(tmp_path, cards_enabled=True, cards_src=fake_src))
    assert app.state.cards_status == cards.DISABLED
    assert "vault" in app.state.cards_detail


def test_a_vault_that_is_not_mounted_is_absent(tmp_path, fake_src, monkeypatch):
    """Configured and not there is an OPERATOR problem, not a choice: the bind
    mount is missing, and every page write would fail."""
    monkeypatch.delenv("CARDS_SRC", raising=False)
    app = create_app(make_settings(
        tmp_path, cards_enabled=True, cards_src=fake_src,
        cards_vault_root=str(tmp_path / "not-mounted")))
    assert app.state.cards_status == cards.ABSENT
    assert "vault" in app.state.cards_detail


def test_a_checkout_that_does_not_import_is_absent(tmp_path, monkeypatch):
    monkeypatch.delenv("CARDS_SRC", raising=False)
    src = tmp_path / "broken"
    (src / "multicam_pipeline" / "cards").mkdir(parents=True)
    app = create_app(make_settings(
        tmp_path, cards_enabled=True, cards_src=str(src),
        cards_vault_root=str(tmp_path)))
    assert app.state.cards_status == cards.ABSENT
    assert "did not import" in app.state.cards_detail
    for name in [n for n in sys.modules if n.split(".")[0] == "multicam_pipeline"]:
        del sys.modules[name]
    while str(src) in sys.path:
        sys.path.remove(str(src))


def test_cards_src_in_the_environment_is_taken_as_consent(tmp_path, fake_src, monkeypatch):
    """The dev/test hook: a checkout named by hand needs no enable flag."""
    monkeypatch.setenv("CARDS_SRC", fake_src)
    monkeypatch.setenv("CARDS_VAULT_ROOT", str(tmp_path))
    app = create_app(make_settings(tmp_path))
    assert app.state.cards_status == cards.MOUNTED


def test_an_engine_that_will_not_build_is_a_failed_episode(tmp_path, fake_src,
                                                           monkeypatch):
    """Anything the engine's constructor throws is a state, not a boot
    failure: the fleet dashboard is what tells everyone whether their footage
    is syncing.

    It is now a state of ONE EPISODE rather than of the mount: nothing is
    built until somebody opens one, so the dashboard boots MOUNTED with a
    landing page, and the episode that will not open says why on it. The
    other episode still opens.
    """
    monkeypatch.delenv("CARDS_SRC", raising=False)
    monkeypatch.setattr(cards, "build_engine",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no postgres")))
    vault, roots, _ = make_vault(tmp_path)
    app = create_app(make_settings(
        tmp_path, cards_enabled=True, cards_src=fake_src,
        cards_vault_root=str(vault)))
    assert app.state.cards_status == cards.MOUNTED
    entry, refusal = app.state.cards_pool.open(str(roots[0]))
    assert refusal == ""
    end = time.monotonic() + 5.0
    while entry.state == cards_pool.LOADING and time.monotonic() < end:
        time.sleep(0.01)
    assert entry.state == cards_pool.FAILED
    # dash-cards-7 (2026-09-18): the page gets the exception's TYPE and a
    # pointer to the log, never its text -- a psycopg OperationalError carries
    # the DSN. The full text is in the warning above.
    assert "RuntimeError" in entry.detail
    assert "no postgres" not in entry.detail
    with TestClient(app) as client:
        client.cookies.set(auth.COOKIE_NAME,
                           auth.make_session_cookie(SECRET, "owen"))
        # The landing page still draws, which is the whole point of it not
        # needing an engine.
        page = client.get("/cards/")
        assert page.status_code == 200
        assert "cl-badge-failed" in page.text
        assert "RuntimeError" in page.text


def test_a_wrap_that_fails_stops_the_engine_it_already_started(
        tmp_path, fake_src, monkeypatch):
    """bug-hunt-2026-09-03 dash-release-jobs-1.

    The engine is started before the a2wsgi wrap. When the wrap raised, the
    recovery (`stop_engine`) read an `app.state.cards_engine` that was still
    None, so the sweep and the ffmpeg worker ran for the life of the container
    with nothing holding a reference to them.
    """
    monkeypatch.delenv("CARDS_SRC", raising=False)
    from ccsync_dashboard import cards_wsgi

    built = []
    real_build = cards.build_engine

    def spy(*a, **kw):
        engine = real_build(*a, **kw)
        built.append(engine)
        return engine

    monkeypatch.setattr(cards, "build_engine", spy)
    monkeypatch.setattr(cards_wsgi, "handler_wsgi",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    vault, roots, _ = make_vault(tmp_path)
    app = create_app(make_settings(
        tmp_path, cards_enabled=True, cards_src=fake_src,
        cards_vault_root=str(vault)))
    entry, _refusal = app.state.cards_pool.open(str(roots[0]))
    end = time.monotonic() + 5.0
    while entry.state == cards_pool.LOADING and time.monotonic() < end:
        time.sleep(0.01)
    assert entry.state == cards_pool.FAILED
    assert "RuntimeError" in entry.detail and "boom" not in entry.detail
    assert len(built) == 1
    assert built[0].started is True
    assert built[0].stopped is True
    assert entry.engine is None


# ------------------------------------------------------------ what it is built with

def test_the_engine_is_built_the_way_server_main_builds_it(mounted):
    _, app = mounted
    engine = engine_of(app)
    assert engine.started is True
    assert engine.built["path"] is None                # no --project
    assert engine.built["db_host"] == "192.168.0.102"
    assert engine.built["db_name"] == "FF5"
    assert engine.built["write_allow"] == ["FF5lab", "FF5"]
    assert engine.built["token"] == "cards-token-not-a-real-one"
    # THE BROWSER KEY IS RETIRED (§7.4): the session cookie is the auth here.
    assert engine.access_key is None
    assert engine.media_map == [("P:\\", "/media"), ("X:\\", "/vault")]
    # The Claude seam (§7d) is injected at mount time.
    assert engine.claude_runner is not None
    assert hasattr(engine.claude_runner, "run")


def test_the_media_map_parses_the_way_the_other_side_does():
    assert cards.parse_media_map("P:\\=/media/;X:\\=/vault/") == [
        ("P:\\", "/media"), ("X:\\", "/vault")]
    # A value may contain a colon; the FIRST '=' splits.
    assert cards.parse_media_map("P:=//host/share") == [("P:", "//host/share")]
    assert cards.parse_media_map("") == []
    assert cards.parse_media_map("nonsense") == []


# ------------------------------------------------------------------ the gate

def test_login_is_required_for_the_whole_prefix(tmp_path, fake_src, monkeypatch):
    """The landing page AND one episode's page, under the deeper prefix.

    The episode prefix is where this is easy to get wrong: the JSON-401 list
    in app.py was four literal prefixes with no slug in them, so an expired
    session would have handed an `<audio>` element a login DOCUMENT, which on
    that page reads as "this clip has no audio".
    """
    monkeypatch.delenv("CARDS_SRC", raising=False)
    vault, roots, _ = make_vault(tmp_path)
    app = create_app(make_settings(
        tmp_path, cards_enabled=True, cards_src=fake_src,
        cards_vault_root=str(vault)))
    open_episode(app, roots[0])
    with TestClient(app) as client:
        landing = client.get("/cards/", follow_redirects=False)
        assert landing.status_code == 303 and "/login" in landing.headers["location"]
        page = client.get(U(app, "/"), follow_redirects=False)
        assert page.status_code == 303 and "/login" in page.headers["location"]
        # ...and the page's own fetches get JSON, not a login document to
        # JSON.parse.
        api = client.get(U(app, "/api/state?v=-1"), follow_redirects=False)
        assert api.status_code == 401
        assert api.json()["detail"] == "login required"
        for media in ("/audio?mp=x", "/video?mp=x", "/peaks?mp=x"):
            answer = client.get(U(app, media), follow_redirects=False)
            assert answer.status_code == 401, media


def test_a_fleet_token_does_not_open_the_page(mounted):
    """Phase 2's rule, now that there is something behind the prefix."""
    client, app = mounted
    client.cookies.clear()
    resp = client.get(U(app, "/api/state?v=-1"), headers=fleet_headers(),
                      follow_redirects=False)
    assert resp.status_code == 401


def test_restart_never_reaches_the_handler(mounted):
    client, app = mounted
    resp = client.post(U(app, "/api/restart"), json={})
    assert resp.status_code == 200
    assert "cannot restart itself" in resp.json()["error"]
    assert engine_of(app).restarted is False


def test_restart_with_a_trailing_slash_is_refused_too(mounted):
    """bug-hunt-2026-09-03 dash-release-jobs-4: the gate matched the path
    exactly, so `/api/restart/` walked past it into a handler that may
    normalise the slash itself."""
    client, app = mounted
    resp = client.post(U(app, "/api/restart/"), json={}, follow_redirects=False)
    assert resp.status_code == 200
    assert "cannot restart itself" in resp.json()["error"]
    assert engine_of(app).restarted is False


def test_the_agent_protocol_is_not_served_by_the_mount(mounted):
    """The three routes belong to cards_tunnel, which is registered first. A
    fourth one added upstream must not appear on the session-gated prefix."""
    client, app = mounted
    resp = client.get("/cards/agent/anything-else")
    assert resp.status_code == 404
    assert "the agent protocol" in resp.json()["error"]


def test_a_cross_site_post_is_refused(mounted):
    """The page sends no CSRF token (like /broll and /ytdl), so the ORIGIN
    check is what stands between a logged-in editor and somebody else's page
    deleting clips out of their timeline."""
    client, app = mounted
    resp = client.post(U(app, "/api/delete"), json={"uids": ["x"]},
                       headers={"Origin": "http://evil.example"})
    assert resp.status_code == 403
    same = client.post(U(app, "/api/delete"), json={"uids": ["x"]},
                       headers={"Origin": "http://testserver"})
    assert same.status_code == 200


# ------------------------------------------------------------------- the shim

def test_a_json_get_is_the_engines_own_json(mounted):
    client, app = mounted
    resp = client.get(U(app, "/api/state?v=-1"))
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    assert resp.json() == {"version": 7, "query": "v=-1",
                           "root": engine_of(app).root}
    # ONE Date and ONE Server header, whatever the handler emitted.
    assert len(resp.headers.get_list("date")) <= 1
    assert len(resp.headers.get_list("server")) <= 1


def test_the_path_under_the_mount_is_what_the_handler_dispatches_on(mounted):
    """a2wsgi strips the prefix into SCRIPT_NAME, which is the whole reason
    the handler keeps its absolute `/api/...` dispatch."""
    client, app = mounted
    assert client.get(U(app, "/api/state")).status_code == 200
    assert client.get(U(app, "/does-not-exist")).status_code == 404


def test_a_post_body_reaches_the_handler(mounted):
    client, app = mounted
    resp = client.post(U(app, "/api/plan"), json={"rev": 3})
    assert resp.json() == {"ok": True, "path": "/api/plan"}
    path, raw = engine_of(app).posts[0]
    assert (path, json.loads(raw)) == ("/api/plan", {"rev": 3})


def test_a_range_request_passes_through_as_a_206(mounted):
    client, app = mounted
    resp = client.get(U(app, "/audio?mp=x"), headers={"Range": "bytes=10-19"})
    assert resp.status_code == 206
    assert resp.headers["Content-Range"] == f"bytes 10-19/{len(AUDIO_BYTES)}"
    assert resp.headers["Content-Length"] == "10"
    assert resp.content == AUDIO_BYTES[10:20]
    assert resp.headers["Accept-Ranges"] == "bytes"


def test_the_whole_file_is_a_200_with_the_same_validators(mounted):
    client, app = mounted
    resp = client.get(U(app, "/audio?mp=x"))
    assert resp.status_code == 200
    assert resp.content == AUDIO_BYTES
    etag = resp.headers["ETag"]
    again = client.get(U(app, "/audio?mp=x"), headers={"Range": "bytes=0-3",
                                                     "If-Range": etag})
    assert again.status_code == 206
    assert again.content == AUDIO_BYTES[:4]


def test_the_handlers_own_gzip_survives_the_shim(mounted):
    """The handler compresses its own bodies and sets Content-Encoding; the
    shim must pass both through untouched. uvicorn does not re-encode, so a
    header dropped here would be 660 KB of gzip served as text/plain -- which
    the browser renders as binary and nobody reads as a header bug."""
    client, app = mounted
    resp = client.get(U(app, "/big"), headers={"Accept-Encoding": "gzip"})
    assert resp.status_code == 200
    # httpx decodes it, so the proof it WAS compressed is the raw length
    # against the decoded one.
    assert resp.json()["pad"] == "x" * 8000
    assert int(resp.headers["content-length"]) < 8000
    assert resp.headers["Vary"] == "Accept-Encoding"
    plain = client.get(U(app, "/big"), headers={"Accept-Encoding": "identity"})
    assert "content-encoding" not in plain.headers
    assert int(plain.headers["content-length"]) > 8000


def test_a_route_that_raises_is_a_500_and_not_a_dead_mount(mounted):
    client, app = mounted
    assert client.get(U(app, "/boom")).status_code == 500
    assert client.get(U(app, "/api/state")).status_code == 200


def test_a_route_that_answers_nothing_is_a_502(mounted):
    """It cannot happen, and "cannot happen" still needs an answer -- the
    alternative is a browser waiting for a response nobody will write."""
    client, app = mounted
    resp = client.get(U(app, "/silent"))
    assert resp.status_code == 502
    assert "answered nothing" in resp.json()["error"]


def test_the_bare_prefix_redirects_to_the_slash(mounted):
    """EVERY fetch in the page is document-relative (`api/state?v=-1`), so at
    /cards with no slash they would resolve against the dashboard root."""
    client, app = mounted
    resp = client.get("/cards", follow_redirects=False)
    assert resp.status_code in (303, 307, 308)
    assert resp.headers["location"].endswith("/cards/")


def test_the_bare_project_url_redirects_to_the_slash_too(mounted):
    """The same rule one level deeper, and it bites harder: document-relative
    from `/cards/p/<slug>` resolves against `/cards/p/`, so every asset and
    every fetch would be one directory too high."""
    client, app = mounted
    bare = U(app, "")
    resp = client.get(bare, follow_redirects=False)
    assert resp.status_code in (303, 307, 308)
    assert resp.headers["location"].endswith(bare + "/")


# ------------------------------------------------------------------ the tunnel

def in_episode(app, editor, slug=""):
    """That editor has the episode's page open. -> phase 1a.

    What the dispatcher records off a real request, done directly here: the
    agent tunnel routes a push to the engine ITS OWN EDITOR is in, and the
    fleet identity in these tests (`jsmith`) is not the browser session's.
    """
    entries = [e for e in app.state.cards_pool.entries()
               if not slug or e.slug == slug]
    app.state.cards_pool.note_visit(entries[0].slug, editor)


def test_the_tunnel_calls_the_engine_in_process(mounted, monkeypatch):
    client, app = mounted
    client.cookies.clear()
    in_episode(app, "jsmith")
    from ccsync_dashboard import cards_tunnel

    def no_http(*a, **k):  # pragma: no cover - the point is that it is not called
        raise AssertionError("the tunnel made an HTTP hop with the page mounted")

    monkeypatch.setattr(cards_tunnel, "_forward", no_http)
    state = client.post("/cards/agent/state",
                        json={"name": "CREATOR-1", "machine": "CREATOR-1",
                              "token": "a token of my choosing"},
                        headers=fleet_headers())
    assert state.status_code == 200
    saw = state.json()["saw"]
    # The VERIFIED identity, and the caller's own token dropped -- phase 2's
    # two rules, unchanged by the engine being in this process.
    assert saw["name"] == "jsmith/CREATOR-1"
    assert "token" not in saw
    pending = client.get("/cards/agent/pending?wait=3", headers=fleet_headers())
    assert pending.json() == {"wait": "3", "req": None}
    result = client.post("/cards/agent/result", json={"id": 1, "ok": True},
                         headers=fleet_headers())
    assert result.json()["result"]["id"] == 1
    assert engine_of(app).ticks >= 3


def test_an_engine_that_raises_answers_the_agent_a_sentence(mounted):
    """handler.py's own contract: a 200 with `{"error": ...}`, because the
    agent's five-retry loop must not repeat a request that cannot succeed."""
    client, app = mounted
    client.cookies.clear()
    in_episode(app, "jsmith")

    def boom(body):
        raise RuntimeError("the mirror file is unreadable")

    engine_of(app).agent_state = boom
    resp = client.post("/cards/agent/state", json={}, headers=fleet_headers())
    assert resp.status_code == 200
    assert resp.json()["error"] == "the mirror file is unreadable"


def test_a_push_goes_to_the_engine_that_editor_is_in(mounted, monkeypatch):
    """Phase 1a: Resolve belongs to the ACCOUNT, not to the server.

    Two episodes open, two editors, one in each. A state push carries a
    verified identity and nothing else that could decide where it lands -- so
    the identity is what decides, or Alex's sweep arrives in Ruskin's episode
    and the cards on his screen become somebody else's.
    """
    client, app = mounted
    client.cookies.clear()
    from ccsync_dashboard import cards_tunnel

    monkeypatch.setattr(cards_tunnel, "_forward", _no_http)
    second = open_episode(app, _second_episode(app))
    first = engine_of(app)
    in_episode(app, "jsmith", slug=_slug_of(app, first))
    in_episode(app, "ruskin", slug=second.slug)

    client.post("/cards/agent/state",
                json={"name": "CREATOR-1", "machine": "CREATOR-1"},
                headers=fleet_headers("jsmith"))
    client.post("/cards/agent/state",
                json={"name": "RUSKIN-PC", "machine": "RUSKIN-PC"},
                headers=fleet_headers("ruskin"))
    assert first.agent_pushes == ["jsmith/CREATOR-1"]
    assert second.engine.agent_pushes == ["ruskin/RUSKIN-PC"]


def test_an_editor_in_no_episode_is_told_so_and_lands_nowhere(mounted, monkeypatch):
    """The other half of the same rule, and the one that must not guess.

    An agent whose owner has no page open used to be attached to "the"
    engine, because there was only one. With a pool that would be whichever
    episode happened to be first -- somebody else's timeline, driven by a
    machine its owner cannot see.
    """
    client, app = mounted
    client.cookies.clear()
    from ccsync_dashboard import cards_tunnel

    monkeypatch.setattr(cards_tunnel, "_forward", _no_http)
    resp = client.post("/cards/agent/state", json={"name": "CREATOR-1"},
                       headers=fleet_headers("nobody"))
    assert resp.status_code == 200
    assert "not in a Timeline Cards episode" in resp.json()["error"]
    assert engine_of(app).agent_pushes == []
    # The long poll is not an action: an empty answer, not an error a
    # companion would log once a second for an owner who is simply not there.
    poll = client.get("/cards/agent/pending?wait=0",
                      headers=fleet_headers("nobody"))
    assert poll.status_code == 200
    assert "req" not in poll.json()


def _no_http(*a, **k):  # pragma: no cover - the point is that it is not called
    raise AssertionError("the tunnel made an HTTP hop with the page mounted")


def _second_episode(app):
    """The root of an episode in the vault that is not open yet."""
    from ccsync_dashboard import cards, cards_pool as pool_mod

    vault = cards.vault_root(app.state.settings)
    open_slugs = {e.slug for e in app.state.cards_pool.entries()}
    for row in pool_mod.episodes(vault):
        if row["slug"] not in open_slugs:
            return row["root"]
    raise AssertionError("the vault has only one episode in it")


def _slug_of(app, engine):
    for entry in app.state.cards_pool.entries():
        if entry.engine is engine:
            return entry.slug
    raise AssertionError("that engine is not in the pool")


def test_with_no_mount_the_tunnel_is_exactly_phase_two(tmp_path, monkeypatch):
    """Both origins during the transition (§7.4): a dashboard with no page
    mounted still forwards to the separate container."""
    monkeypatch.delenv("CARDS_SRC", raising=False)
    from ccsync_dashboard import cards_tunnel

    settings = make_settings(tmp_path, cards_server_url="http://cards.invalid:8800",
                             cards_token="upstream")
    app = create_app(settings)
    assert app.state.cards_engine is None
    calls = []

    def fake_forward(request, method, suffix, body=None, query="", timeout=0):
        calls.append((method, suffix))
        return {"ok": True}

    monkeypatch.setattr(cards_tunnel, "_forward", fake_forward)
    with TestClient(app) as client:
        assert client.post("/cards/agent/state", json={},
                           headers=fleet_headers()).status_code == 200
    assert calls == [("POST", "/agent/state")]


# ------------------------------------------------------------------ shutdown

def test_every_open_episode_stops_with_the_app(tmp_path, fake_src, monkeypatch):
    """One shutdown hook, and it drains the WHOLE pool.

    Starlette runs no lifespan for a mounted app, so this is the only thing
    that will ever stop those threads -- and with a pool "the engine" is a
    list. An engine left running here is a sweep against a database the next
    process is opening.
    """
    monkeypatch.delenv("CARDS_SRC", raising=False)
    vault, roots, _ = make_vault(tmp_path, "Civil Defence", "Framing Formosa")
    app = create_app(make_settings(
        tmp_path, cards_enabled=True, cards_src=fake_src,
        cards_vault_root=str(vault)))
    engines = [open_episode(app, root).engine for root in roots]
    assert len(engines) == 2
    with TestClient(app):
        assert [e.stopped for e in engines] == [False, False]
    assert [e.stopped for e in engines] == [True, True]
    assert app.state.cards_pool.entries() == []


def test_stop_engine_survives_an_engine_that_will_not_stop(mounted):
    client, app = mounted

    def boom():
        raise RuntimeError("a thread that is not listening")

    engine_of(app).stop = boom
    cards.stop_engine(app)                      # must not raise
    assert app.state.cards_engine is None
    assert app.state.cards_pool.entries() == []


# -------------------------------------------------------------- the health line

def test_the_health_line_says_which_state_and_why(mounted):
    client, app = mounted
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "owen"))
    block = client.get("/api/v1/health").json()["cards"]
    assert block["status"] == cards.MOUNTED
    assert block["root"] == engine_of(app).root
    # ONE LINE PER EPISODE: "the" root used to be whichever engine answered.
    assert [(e["state"], e["root"]) for e in block["open"]] == [
        ("ready", engine_of(app).root)]
    assert block["cap"] == 2
    # No credential is configured in this suite, so the honest answer is no.
    assert block["claude"]["ok"] is False
    assert block["claude"]["why"]


def test_an_absent_mount_does_not_make_the_dashboard_unhealthy(tmp_path, monkeypatch):
    monkeypatch.delenv("CARDS_SRC", raising=False)
    app = create_app(make_settings(tmp_path))
    with TestClient(app) as client:
        client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "owen"))
        body = client.get("/api/v1/health").json()
    assert body["cards"]["status"] == cards.DISABLED
    assert body["ok"] is True


def test_the_health_line_is_not_served_to_a_stranger(tmp_path, monkeypatch):
    """The unauthenticated body is {ok, version} and nothing else: the vault's
    path on the NAS is not something a probe gets to read."""
    monkeypatch.delenv("CARDS_SRC", raising=False)
    app = create_app(make_settings(tmp_path))
    with TestClient(app) as client:
        assert "cards" not in client.get("/api/v1/health").json()
