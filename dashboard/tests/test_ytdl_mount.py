"""The YouTube downloader UI mounted at /ytdl.

Modelled on test_music_mount.py, and for the same reasons: editors get one URL
and one login instead of a fourth service to reach and sign in to, the mount is
in-process, and the tri-state (absent / degraded / mounted) is most of what
there is to get wrong.

These tests do NOT need ytdl/web importable, and they must not import it: the
dashboard venv has no yt-dlp, the real ytdlweb starts a pipeline THREAD from
worker.ensure_started(), and its tree is being written while this file runs.
Everything here runs against a small fake `ytdlweb` package installed into
sys.modules, mirroring the real one's contract -- `ytdlweb.main.app` is a
FastAPI, `ytdlweb.config.DATA_ROOT` is a Path read from the environment at
import time, `ytdlweb.db` connects and applies a schema, and
`ytdlweb.worker.ensure_started()` is idempotent.

WHAT IS EXTRA HERE, over music: identity. Unlike music, this sub-app makes
per-user decisions -- which projects a job may download into, whose manifest
may be read -- from an X-CCSync-User header that ccsync_dashboard.ytdl mints
from the session cookie. So the fake app echoes that header back, and two tests
pin the whole contract: the value equals the session's username, and a FORGED
inbound header never reaches the sub-app. Without the second one, any
logged-in editor could download into another editor's projects by adding a
header to a fetch().
"""
from __future__ import annotations

import os
import sqlite3
import sys
import types
from pathlib import Path

import pytest
from fastapi import APIRouter, FastAPI, Header, Request
from fastapi.responses import HTMLResponse
from fastapi.testclient import TestClient

from ccsync_dashboard import auth, ytdl
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "s" * 32


# --- a stand-in for the ytdl app ----------------------------------------------

def _build_fake_ytdlweb() -> dict[str, types.ModuleType]:
    """The four modules ccsync_dashboard.ytdl imports from ytdl/web.

    The package is `ytdlweb`, deliberately NOT `app` (broll/web owns that
    top-level name and two packages of one name on a PYTHONPATH collide in
    sys.modules, one silently winning) and NOT `ytdl` (which is the dashboard
    module doing the mounting). The fake keeps the name for the same reasons --
    and so this file, test_music_mount.py and test_broll_mount.py can install
    their fakes side by side.

    config resolves DATA_ROOT from the environment AT IMPORT TIME, as the real
    ytdlweb.config does, so the fixture sets the env var before building this.
    """
    pkg = types.ModuleType("ytdlweb")
    pkg.__path__ = []  # a package, so `from ytdlweb.x import y` resolves

    config = types.ModuleType("ytdlweb.config")
    config.DATA_ROOT = Path(os.environ.get("YTDL_DATA_ROOT", "./data")).resolve()
    config.DB_PATH = config.DATA_ROOT / "ytdl.db"
    config.PROJECTS_ROOT = Path(os.environ.get("YTDL_PROJECTS_ROOT", "./projects"))

    db = types.ModuleType("ytdlweb.db")

    def connect(path=None):
        p = Path(path or config.DB_PATH)
        p.parent.mkdir(parents=True, exist_ok=True)
        return sqlite3.connect(p, timeout=30)

    def init(con) -> None:
        con.executescript(
            "CREATE TABLE IF NOT EXISTS jobs (id INTEGER PRIMARY KEY, term TEXT);"
        )
        con.commit()

    db.connect = connect
    db.init = init
    db._schema_ready = False   # mounting must not flip this; see test below

    worker = types.ModuleType("ytdlweb.worker")
    # A recorder, not a thread. The real ensure_started() spawns the pipeline
    # daemon; a test suite that started one per create_app would be racing a
    # subprocess-spawning worker against its own tmp dirs.
    worker.started = 0

    def ensure_started() -> None:
        worker.started += 1

    worker.ensure_started = ensure_started

    main = types.ModuleType("ytdlweb.main")
    ytdl_app = FastAPI(title="YouTube Downloader (fake)")

    api = APIRouter()

    @api.get("/api/me")
    def me(request: Request) -> dict:
        # Faithful to ytdlweb.session.current_user: the ONLY thing it trusts is
        # the gate-injected header. Echoed raw (including the absent case) so
        # the gate's behaviour is what these tests observe.
        return {"user": request.headers.get("x-ccsync-user")}

    @api.get("/api/jobs/{job_id}")
    def job(job_id: int, x_ccsync_user: str | None = Header(default=None)) -> dict:
        return {"id": job_id, "user": x_ccsync_user}

    @api.post("/api/jobs")
    def create_job(request: Request) -> dict:
        return {"created_by": request.headers.get("x-ccsync-user")}

    ytdl_app.include_router(api)

    @ytdl_app.get("/", response_class=HTMLResponse)
    def home() -> str:
        return "<html><body>YOUTUBE DOWNLOADER</body></html>"

    main.app = ytdl_app
    pkg.config, pkg.db, pkg.main, pkg.worker = config, db, main, worker
    return {"ytdlweb": pkg, "ytdlweb.config": config, "ytdlweb.db": db,
            "ytdlweb.main": main, "ytdlweb.worker": worker}


@pytest.fixture
def ytdl_env(tmp_path, monkeypatch):
    """Install the fake ytdl package and point its data root at tmp_path.

    monkeypatch.setitem cleans sys.modules up afterwards, so the fake never
    leaks into another test module.
    """
    monkeypatch.setenv("YTDL_DATA_ROOT", str(tmp_path / "ytdldata"))
    monkeypatch.setenv("YTDL_PROJECTS_ROOT", str(tmp_path / "projects"))
    for name, module in _build_fake_ytdlweb().items():
        monkeypatch.setitem(sys.modules, name, module)
    return tmp_path


@pytest.fixture
def no_ytdlweb(monkeypatch):
    """Make `import ytdlweb` fail, whatever is on this machine's disk.

    Without this the in-repo dev fallback (_add_in_repo_ytdl_web) finds
    ytdl/web in the checkout, and whether the import then succeeds depends on
    whether yt-dlp happens to be in the venv -- a test that passes for a
    different reason on different machines is the failure mode the b-roll tests
    were rewritten to remove. It would also start the real pipeline thread.
    """
    import builtins

    real_import = builtins.__import__

    def fail_on_ytdlweb(name, *a, **kw):
        if name == "ytdlweb" or name.startswith("ytdlweb."):
            raise ImportError("simulated: the ytdl tree is not deployed here")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", fail_on_ytdlweb)
    for name in [n for n in sys.modules if n == "ytdlweb" or n.startswith("ytdlweb.")]:
        monkeypatch.delitem(sys.modules, name, raising=False)
    return real_import


def _app(tmp_path, **kw):
    return create_app(Settings(db_path=str(tmp_path / "d.db"), session_secret=SECRET, **kw))


def as_user(client, user="jsmith"):
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, user))
    return client


# --- the dashboard must survive the feature being absent or broken ------------

def test_an_absent_ytdl_tree_never_takes_the_dashboard_down(tmp_path, no_ytdlweb,
                                                            monkeypatch):
    """The dashboard is what tells the whole fleet whether their footage is
    syncing. An optional feature must not be able to stop it booting, so the
    import is guarded and a failure is logged rather than raised."""
    import builtins

    app = _app(tmp_path)
    monkeypatch.setattr(builtins, "__import__", no_ytdlweb)

    assert app.state.ytdl_status == ytdl.ABSENT
    assert app.state.ytdl_mounted is False
    with TestClient(app) as c:
        assert c.get("/api/v1/health").status_code == 200
        assert c.get("/login").status_code == 200


def test_an_absent_ytdl_tree_is_not_advertised_in_the_nav(tmp_path, no_ytdlweb,
                                                          monkeypatch):
    import builtins

    app = _app(tmp_path)
    monkeypatch.setattr(builtins, "__import__", no_ytdlweb)

    with TestClient(app) as c:
        page = as_user(c).get("/")
        assert page.status_code == 200
        assert 'href="/ytdl/"' not in page.text


def test_a_data_root_it_cannot_open_is_mounted_but_never_advertised(tmp_path, ytdl_env,
                                                                    monkeypatch):
    """Degraded, the state that is easy to get wrong: ytdlweb imports fine but
    YTDL_DATA_ROOT is a read-only bind mount or belongs to another uid, so
    sqlite answers "unable to open database file" on every request. Reporting
    that as a success is how the nav ends up offering a link to a page that
    500s."""
    def boom(path=None):
        raise sqlite3.OperationalError("unable to open database file")

    monkeypatch.setattr(sys.modules["ytdlweb.db"], "connect", boom)
    app = _app(tmp_path)

    assert app.state.ytdl_status == ytdl.DEGRADED
    assert app.state.ytdl_mounted is False, "a broken mount is never advertised"
    with TestClient(app) as c:
        assert c.get("/api/v1/health").status_code == 200
        page = as_user(c).get("/")
        assert page.status_code == 200
        assert 'href="/ytdl/"' not in page.text


def test_a_degraded_mount_never_starts_the_pipeline_worker(tmp_path, ytdl_env,
                                                           monkeypatch):
    """Order matters inside _init_ytdl_storage: the worker's first act is to
    recover jobs left mid-pipeline, and it cannot query a database that could
    not be opened."""
    def boom(path=None):
        raise sqlite3.OperationalError("unable to open database file")

    monkeypatch.setattr(sys.modules["ytdlweb.db"], "connect", boom)
    app = _app(tmp_path)

    assert app.state.ytdl_status == ytdl.DEGRADED
    assert sys.modules["ytdlweb.worker"].started == 0


def test_degraded_is_still_reachable_for_whoever_types_the_url(tmp_path, ytdl_env,
                                                               monkeypatch):
    """Mounted but unadvertised, exactly like b-roll and music: an operator who
    goes looking gets the sub-app (and its real error) rather than a 404 that
    says nothing about what is wrong."""
    def boom(path=None):
        raise sqlite3.OperationalError("unable to open database file")

    monkeypatch.setattr(sys.modules["ytdlweb.db"], "connect", boom)
    app = _app(tmp_path)
    with TestClient(app) as c:
        as_user(c)
        assert c.get("/ytdl/").status_code == 200


# --- the mount itself ---------------------------------------------------------

def test_the_ui_is_served_under_the_prefix(tmp_path, ytdl_env):
    app = _app(tmp_path)
    assert app.state.ytdl_status == ytdl.MOUNTED
    assert app.state.ytdl_mounted is True
    with TestClient(app) as c:
        # Unauthenticated: the gate bounces a page request to login, which
        # proves the mount sits behind the dashboard's auth without ytdlweb
        # having any auth code of its own.
        r = c.get("/ytdl/", follow_redirects=False)
        assert r.status_code == 303
        assert "/login" in r.headers["location"]


def test_a_signed_in_editor_renders_a_page_through_the_mount(tmp_path, ytdl_env):
    """That the request really reaches the sub-app, not just login_gate: a
    303 or 401 on an unmounted path looks identical from outside."""
    app = _app(tmp_path)
    with TestClient(app) as c:
        as_user(c)
        page = c.get("/ytdl/")
        assert page.status_code == 200, page.text
        assert "YOUTUBE DOWNLOADER" in page.text
        assert c.get("/ytdl/api/jobs/7").json()["id"] == 7
        # ...and the nav offers the link, which it must only ever do when the
        # mount is fully working. The trailing slash is mandatory: the SPA
        # resolves every URL against the document.
        assert 'href="/ytdl/"' in c.get("/").text
        # The topbar partial the SPA injects marks the page it was fetched
        # for -- and only that page (see test_topbar_partial.py).
        marked = c.get("/partials/topbar?current=ytdl").text
        assert 'nav-current" href="/ytdl/"' in marked
        assert marked.count("nav-current") == 1


def test_the_storage_probe_creates_the_database_and_starts_the_worker(tmp_path,
                                                                      ytdl_env):
    """Starlette does NOT run a mounted sub-app's lifespan. For music that only
    cost the MOUNTED/DEGRADED distinction; here it would also mean no pipeline
    thread at all, so every job would sit in `queued` forever while the UI
    happily polled it."""
    app = _app(tmp_path)
    assert app.state.ytdl_mounted is True
    assert (ytdl_env / "ytdldata" / "ytdl.db").is_file()
    assert sys.modules["ytdlweb.worker"].started == 1


def test_mounting_does_not_mutate_ytdlwebs_own_globals(tmp_path, ytdl_env):
    """The probe opens its own connection and closes it. Flipping
    db._schema_ready from out here would mean a later real request skips the
    schema apply on the strength of work done by a different connection."""
    app = _app(tmp_path)
    assert app.state.ytdl_mounted is True
    assert sys.modules["ytdlweb.db"]._schema_ready is False


def test_dashboard_routes_are_unchanged_by_the_mount(tmp_path, ytdl_env):
    """A ytdl route must never shadow a dashboard one."""
    app = _app(tmp_path)
    with TestClient(app) as c:
        assert c.get("/api/v1/health").status_code == 200
        assert c.get("/login").status_code == 200


def test_broll_music_and_ytdl_can_be_mounted_side_by_side(tmp_path, ytdl_env):
    """The whole reason the package is `ytdlweb` and not `app`. All three fakes
    are in sys.modules at once here; if the names collided one mount would
    silently serve another's routes."""
    from test_broll_mount import TOKEN, _build_fake_broll
    from test_music_mount import _build_fake_musicweb

    os.environ["DATA_ROOT"] = str(tmp_path / "musicdata")
    os.environ["MUSIC_ROOT"] = str(tmp_path / "library")
    os.environ["BROLL_DATA_ROOT"] = str(tmp_path / "brolldata")
    os.environ["BROLL_INGEST_TOKEN"] = TOKEN
    for name, module in _build_fake_broll("BROLL_DATA_ROOT").items():
        sys.modules[name] = module
    for name, module in _build_fake_musicweb().items():
        sys.modules[name] = module
    try:
        app = _app(tmp_path, broll_enabled=True, broll_ingest_token=TOKEN)
        assert app.state.broll_status == "mounted"
        assert app.state.music_status == "mounted"
        assert app.state.ytdl_status == ytdl.MOUNTED
        with TestClient(app) as c:
            as_user(c)
            assert "B-ROLL SEARCH" in c.get("/broll/").text
            assert "MUSIC SEARCH" in c.get("/music/").text
            assert "YOUTUBE DOWNLOADER" in c.get("/ytdl/").text
            nav = c.get("/").text
            for href in ('href="/broll/"', 'href="/music/"', 'href="/ytdl/"'):
                assert href in nav
    finally:
        for name in ("app", "app.config", "app.db", "app.main",
                     "musicweb", "musicweb.config", "musicweb.db", "musicweb.main"):
            sys.modules.pop(name, None)
        for var in ("BROLL_DATA_ROOT", "BROLL_INGEST_TOKEN", "MUSIC_ROOT"):
            os.environ.pop(var, None)


def test_the_sub_apps_interactive_docs_are_not_published(tmp_path, ytdl_env):
    """Mounting a third FastAPI() brings /docs, /redoc and /openapi.json with
    it. The dashboard publishes no API explorer; neither does any of its
    mounts."""
    app = _app(tmp_path)
    with TestClient(app) as c:
        as_user(c)
        for path in ("/ytdl/docs", "/ytdl/redoc", "/ytdl/openapi.json"):
            assert c.get(path).status_code == 404, path


# --- auth --------------------------------------------------------------------

def test_the_api_answers_401_json_not_a_login_redirect(tmp_path, ytdl_env):
    """The SPA polls api/jobs/{id} every 1.5s while a pipeline runs; it cannot
    follow a 303 to an HTML page. A session that expires mid-job would
    otherwise hand it a login page to JSON.parse once per tick."""
    app = _app(tmp_path)
    with TestClient(app) as c:
        for path in ("/ytdl/api/me", "/ytdl/api/jobs/1"):
            r = c.get(path, follow_redirects=False)
            assert r.status_code == 401, path
            assert r.json()["detail"] == "login required"
        r = c.post("/ytdl/api/jobs", follow_redirects=False)
        assert r.status_code == 401, r.text


def test_the_write_routes_are_behind_the_login_gate(tmp_path, ytdl_env):
    """ytdlweb has no token of its own, so login_gate IS the credential for
    POST api/jobs (which spends the NAS's bandwidth and disk) -- and nothing
    about /ytdl/* may ever be exempted from it, which is exactly the exemption
    b-roll needs a token to make safe."""
    app = _app(tmp_path)
    with TestClient(app) as c:
        assert c.post("/ytdl/api/jobs", follow_redirects=False).status_code == 401
        as_user(c)
        assert c.post("/ytdl/api/jobs").json() == {"created_by": "jsmith"}


# --- identity: the header is minted here, never accepted from outside ---------

def test_the_sub_app_is_told_who_the_session_belongs_to(tmp_path, ytdl_env):
    """The whole point of YtdlGate. ytdlweb has no session code: it authorises
    every per-user decision (which projects a job may write into, whose
    manifest may be read) on this header, and the header exists because the
    gate decoded the ccsync_session cookie with the dashboard's own secret."""
    app = _app(tmp_path)
    with TestClient(app) as c:
        as_user(c, "kchen")
        assert c.get("/ytdl/api/me").json() == {"user": "kchen"}
        assert c.get("/ytdl/api/jobs/3").json() == {"id": 3, "user": "kchen"}
        # a different editor on the same server gets their own answer
        as_user(c, "jsmith")
        assert c.get("/ytdl/api/me").json() == {"user": "jsmith"}


def test_a_forged_identity_header_never_reaches_the_sub_app(tmp_path, ytdl_env):
    """SPOOF-PROOFING, and the reason the gate strips before it appends. A
    logged-in editor sails past login_gate with a valid session of their own;
    if their `fetch(url, {headers: {'X-CCSync-User': 'admin'}})` survived the
    trip, that header would be the entire authorisation story for "which
    projects may I download into"."""
    app = _app(tmp_path)
    with TestClient(app) as c:
        as_user(c, "jsmith")
        forged = {"X-CCSync-User": "admin"}
        assert c.get("/ytdl/api/me", headers=forged).json() == {"user": "jsmith"}
        assert c.get("/ytdl/api/jobs/1", headers=forged).json()["user"] == "jsmith"
        assert c.post("/ytdl/api/jobs", headers=forged).json() == {"created_by": "jsmith"}


def test_a_forged_header_survives_nothing_even_with_no_session(tmp_path, ytdl_env):
    """login_gate answers this request 401 long before the sub-app sees it, so
    this is the belt to that brace: even reached directly, the gate hands the
    sub-app NO identity rather than the caller's own claim, and ytdlweb's own
    401 does the rest."""
    import asyncio

    seen: dict = {}

    async def spy(scope, receive, send):
        seen["headers"] = [(k.decode(), v.decode()) for k, v in scope["headers"]]
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(_message):
        return None

    gate = ytdl.YtdlGate(spy, SECRET)
    # An expired/garbage cookie is the same case as no cookie: read_session_cookie
    # returns None and nothing is appended.
    scope = {"type": "http", "method": "GET", "path": "/ytdl/api/me",
             "root_path": "/ytdl",
             "headers": [(b"x-ccsync-user", b"admin"),
                         (b"cookie", b"ccsync_session=nonsense; other=1")]}
    asyncio.run(gate(scope, receive, send))

    assert not [k for k, _v in seen["headers"] if k == "x-ccsync-user"], (
        "a forged identity header reached the sub-app with no session at all"
    )
    # ...and the gate did not mutate the caller's own scope on the way past:
    # it belongs to the server, and a mounted app is not the only reader.
    assert (b"x-ccsync-user", b"admin") in scope["headers"]


# --- optional: the same thing against a real checkout ------------------------

def test_a_real_checkout_still_satisfies_the_contract_the_fake_models(tmp_path,
                                                                      monkeypatch):
    """Proves the fake has not drifted from ytdl/web -- same module names, same
    `ytdlweb.main.app`, same config.DATA_ROOT, db.connect/init and
    worker.ensure_started.

    Skips wherever ytdlweb's own dependencies are not installed, which is
    everywhere the dashboard runs today (yt-dlp is not in this venv). That skip
    is itself the ABSENT path in production, and it is covered above with a
    fake so it cannot skip silently. YTDL_WORKER=0 keeps the real pipeline
    thread out of the test process.
    """
    raw = os.environ.get("YTDL_WEB_SRC", "").strip()
    src = (Path(raw) if raw else Path(__file__).resolve().parents[2] / "ytdl" / "web").resolve()
    if not (src / "ytdlweb" / "main.py").is_file():
        pytest.skip(f"no ytdlweb/main.py under {src}")
    monkeypatch.setenv("YTDL_DATA_ROOT", str(tmp_path / "ytdldata"))
    monkeypatch.setenv("YTDL_PROJECTS_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("YTDL_WORKER", "0")
    monkeypatch.syspath_prepend(str(src))       # undone at teardown
    for name in [n for n in sys.modules if n == "ytdlweb" or n.startswith("ytdlweb.")]:
        monkeypatch.delitem(sys.modules, name, raising=False)
    try:
        import ytdlweb.main  # noqa: F401
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"the checkout's own dependencies are not installed here: {e}")

    dash = _app(tmp_path)
    assert dash.state.ytdl_status == ytdl.MOUNTED
    with TestClient(dash) as c:
        as_user(c)
        assert c.get("/ytdl/").status_code == 200
        assert c.get("/ytdl/docs").status_code == 404
