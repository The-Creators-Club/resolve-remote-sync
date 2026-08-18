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

    # The provider layer (2026-08-18). The real ai_backend asks this callback
    # on EVERY AI call, which is what lets a key typed on Settings work with
    # no container restart; the fake records what was installed.
    ai_backend = types.ModuleType("ytdlweb.ai_backend")
    ai_backend.installed = []

    def set_provider_lookup(fn) -> None:
        ai_backend.installed.append(fn)

    ai_backend.set_provider_lookup = set_provider_lookup

    main.app = ytdl_app
    pkg.config, pkg.db, pkg.main, pkg.worker = config, db, main, worker
    pkg.ai_backend = ai_backend
    return {"ytdlweb": pkg, "ytdlweb.config": config, "ytdlweb.db": db,
            "ytdlweb.main": main, "ytdlweb.worker": worker,
            "ytdlweb.ai_backend": ai_backend}


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
    """A dashboard whose SITE has enabled the YouTube downloader.

    2026-08-17 (COMMERCIAL_READINESS.md item 2): the feature is off unless the
    customer turned it on, so every test below that is about the MOUNT has to
    say so, or it would be measuring the feature switch instead. The tests that
    are about the switch pass site_feature_youtube_download=False explicitly.
    """
    kw.setdefault("site_feature_youtube_download", True)
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
    """ytdlweb has no session of its own, so login_gate IS the credential for
    POST api/jobs (which spends the NAS's bandwidth and disk). The ONLY
    exemptions from it are the four fleet-token route shapes and the open
    client-config read (2026-08-14, docs/YTDL_LOCAL_DOWNLOAD.md §4) -- the
    browser-facing routes, this one included, are never among them."""
    app = _app(tmp_path)
    with TestClient(app) as c:
        assert c.post("/ytdl/api/jobs", follow_redirects=False).status_code == 401
        as_user(c)
        assert c.post("/ytdl/api/jobs").json() == {"created_by": "jsmith"}


# --- the fleet-token bypass: four route shapes, nothing else ------------------
# docs/YTDL_LOCAL_DOWNLOAD.md §4: claim/heartbeat/manifest/clip-status happen
# when no browser is open, so they authenticate with X-CCSync-Token exactly the
# way the companion's selection fetch does. The gate only steps aside; the
# sub-app's own require_fleet_token still validates, so these tests assert
# "not the gate's 401", never a specific sub-app answer.

FLEET_PATHS = (
    ("post", "/ytdl/api/jobs/1/claim"),
    ("post", "/ytdl/api/jobs/1/heartbeat"),
    ("get", "/ytdl/api/jobs/1/download-manifest"),
    ("post", "/ytdl/api/jobs/1/clips/abc-12_345/status"),
)


def test_the_fleet_routes_pass_the_gate_with_the_token(tmp_path, ytdl_env):
    app = _app(tmp_path, report_token="fleet-tok")
    with TestClient(app) as c:
        for method, path in FLEET_PATHS:
            r = getattr(c, method)(path, follow_redirects=False)
            assert r.status_code == 401, f"{path} without a token"
            r = getattr(c, method)(path, follow_redirects=False,
                                   headers={"X-CCSync-Token": "fleet-tok"})
            assert r.status_code != 401, f"{path} with the token"
            assert r.status_code != 303, f"{path} must never redirect to login"


def test_a_wrong_token_never_passes_the_fleet_gate(tmp_path, ytdl_env):
    app = _app(tmp_path, report_token="fleet-tok")
    with TestClient(app) as c:
        for method, path in FLEET_PATHS:
            r = getattr(c, method)(path, follow_redirects=False,
                                   headers={"X-CCSync-Token": "wrong"})
            assert r.status_code == 401, path


def test_the_client_config_is_open_by_design(tmp_path, ytdl_env):
    """The yt-dlp sidecar manager reads the version floor BEFORE it holds
    anything to claim, and sends no token doing it (companion
    ytdlp_manager). Nothing in the payload is secret."""
    app = _app(tmp_path)
    with TestClient(app) as c:
        r = c.get("/ytdl/api/config/ytdl-client", follow_redirects=False)
        assert r.status_code not in (303, 401)


def test_the_browser_job_routes_stay_session_gated_even_with_the_token(tmp_path, ytdl_env):
    """The bypass is per-suffix, not per-prefix: a leaked fleet token must not
    read a browser's job view or lock its mode."""
    app = _app(tmp_path, report_token="fleet-tok")
    with TestClient(app) as c:
        for method, path in (("get", "/ytdl/api/jobs/1"),
                             ("post", "/ytdl/api/jobs/1/mode-lock"),
                             ("post", "/ytdl/api/jobs/1/cancel"),
                             ("post", "/ytdl/api/jobs")):
            r = getattr(c, method)(path, follow_redirects=False,
                                   headers={"X-CCSync-Token": "fleet-tok"})
            assert r.status_code == 401, path


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


def test_the_bare_prefix_redirects_into_the_mount(tmp_path, ytdl_env):
    """`/ytdl` (no trailing slash) -> `/ytdl/` is LOAD-BEARING, the same way
    `/music`'s is: Starlette only serves the mount from the slashed form, and
    the bare form is what anyone types by hand. Pinned on ytdl/web's side only
    under a plain mount with neither gate (docs/youtube_dlp_bugs.md YTDL-43,
    2026-08-11); this is the authenticated, both-gates-in-place pin."""
    app = _app(tmp_path)
    with TestClient(app) as c:
        as_user(c)
        r = c.get("/ytdl", follow_redirects=False)
        assert r.status_code in (307, 308), r.status_code
        assert r.headers["location"].endswith("/ytdl/")
        # ...and following it really lands in the sub-app
        assert "YOUTUBE DOWNLOADER" in c.get("/ytdl").text


def test_ytdlwebs_project_query_runs_against_the_real_dashboard_schema(tmp_path):
    """ytdl/web/tests/conftest.py hand-copies the projects/selections DDL
    ("copied rather than imported"), so a dashboard column rename would keep
    every ytdl test green while production degraded to "no project list"
    (docs/youtube_dlp_bugs.md YTDL-44, 2026-08-11). This side owns the schema,
    so this side proves the ytdl query still runs against it -- no ytdlweb
    import needed beyond the query module, which is dependency-free.
    """
    src = Path(__file__).resolve().parents[2] / "ytdl" / "web"
    if not (src / "ytdlweb" / "projects.py").is_file():
        pytest.skip(f"no ytdl checkout beside this one at {src}")
    sys.path.insert(0, str(src))
    for name in [n for n in sys.modules if n == "ytdlweb" or n.startswith("ytdlweb.")]:
        del sys.modules[name]
    try:
        from ytdlweb import projects as ytdl_projects
    finally:
        sys.path.remove(str(src))

    from ccsync_dashboard import db

    conn = db.connect(tmp_path / "dashboard.db")
    try:
        db.migrate(conn)
        db.upsert_project(conn, "s-alpha", "2026/FF5/Alpha", "/data/Projects/Alpha", "t0")
        db.upsert_project(conn, "s-old", "2025/Retired", "/data/Projects/Retired", "t0")
        conn.execute("UPDATE projects SET active=0 WHERE slug='s-old'")
        db.add_selection(conn, "jsmith", "s-alpha", "jsmith", "t0")
        db.add_selection(conn, "jsmith", "s-old", "jsmith", "t0")
        conn.commit()
        rows = conn.execute(ytdl_projects._SQL, ("jsmith",)).fetchall()
        # the retired project is dropped by the query's active=1 join
        assert [(r[0], r[1]) for r in rows] == [("s-alpha", "2026/FF5/Alpha")]
    finally:
        conn.close()


def test_the_identity_header_round_trips_a_latin1_name_and_withholds_a_cjk_one(
        tmp_path, ytdl_env):
    """The gate encodes the identity header latin-1 BECAUSE Starlette decodes
    headers latin-1: UTF-8 turned `josé` into `josÃ©` on arrival, so that
    editor's ticked projects matched nothing (docs/youtube_dlp_bugs.md
    YTDL-29, 2026-08-11). A name beyond U+00FF has no lossless encoding and a
    lossy one could collide two editors, so the gate withholds the header
    entirely and the sub-app sees an anonymous request (the real ytdlweb
    answers 401 to that; this suite's fake just echoes what arrived, so "no
    header" is the assertable contract here) -- broken loudly for one person,
    never quietly wrong."""
    app = _app(tmp_path)
    with TestClient(app) as c:
        as_user(c, "josé")
        assert c.get("/ytdl/api/me").json() == {"user": "josé"}
        as_user(c, "小明")
        assert c.get("/ytdl/api/me").json() == {"user": None}


# --------------------------------------------------------------------------
# The site switch (COMMERCIAL_READINESS.md item 2, 2026-08-17)
# --------------------------------------------------------------------------
# The YouTube downloader is OFF unless the customer's site.toml says
# `[features] youtube_download`. Off is what the vendor build ships: the
# customer, not the vendor, decides whether downloading third-party YouTube
# material is lawful for them (docs/legal/YOUTUBE_FEATURE_NOTICE.md).


def test_an_off_site_does_not_mount_the_downloader_at_all(tmp_path, ytdl_env):
    """Not "mounted but hidden": nothing is imported, nothing is served."""
    app = _app(tmp_path, site_feature_youtube_download=False)
    assert app.state.ytdl_status == ytdl.DISABLED
    assert app.state.ytdl_mounted is False
    with TestClient(app) as c:
        as_user(c)
        assert c.get("/ytdl/").status_code == 404
        assert c.get("/ytdl/api/me").status_code == 404


def test_an_off_site_serves_no_fleet_download_route(tmp_path, ytdl_env):
    """The companion's half is under the same mount, so it goes with it -- a
    machine-to-machine route that answered while the feature was off would be
    the one way a download could still happen."""
    token = "t" * 32
    app = _app(tmp_path, site_feature_youtube_download=False, report_token=token)
    headers = {"X-CCSync-Token": token}
    with TestClient(app) as c:
        for path in ("/ytdl/api/jobs/1/claim", "/ytdl/api/jobs/1/heartbeat",
                     "/ytdl/api/jobs/1/clips/abc/status"):
            # The fleet token is presented, so login_gate lets these through --
            # and there is nothing mounted behind it.
            assert c.post(path, json={}, headers=headers).status_code == 404, path
        assert c.get("/ytdl/api/jobs/1/download-manifest",
                     headers=headers).status_code == 404
        assert c.get("/ytdl/api/config/ytdl-client",
                     headers=headers).status_code == 404


def test_the_switch_is_the_only_difference(tmp_path, ytdl_env):
    """Same checkout, same fake package, same everything else."""
    off = _app(tmp_path, site_feature_youtube_download=False)
    on = _app(tmp_path, site_feature_youtube_download=True)
    assert off.state.ytdl_status == ytdl.DISABLED
    assert on.state.ytdl_status == ytdl.MOUNTED


def test_an_off_site_does_not_even_import_the_sub_app(tmp_path, no_ytdlweb):
    """DISABLED is decided BEFORE the import, so a site with the feature off
    never pays the yt-dlp import cost and never reports ABSENT for a tree that
    is simply not wanted -- two different operator problems."""
    app = _app(tmp_path, site_feature_youtube_download=False)
    assert app.state.ytdl_status == ytdl.DISABLED


def test_the_default_settings_have_both_flags_off():
    """The vendor build's shape. `youtube_unblock` is published only when the
    downloader itself is on -- an unblock-without-downloader answer would tell
    companions to install a challenge solver for a feature they cannot use."""
    s = Settings()
    assert s.site_feature_youtube_download is False
    assert s.site_feature_youtube_unblock is False
    # ...and CLI AI providers, for the same "the vendor decides nothing for
    # the customer" reason (2026-08-18, ai_providers.py).
    assert s.site_feature_ai_cli_providers is False


# --- how the sub-app learns which AI to use (2026-08-18) ----------------------

def test_mounting_installs_the_ai_provider_lookup(tmp_path, ytdl_env):
    """Env at mount time is not enough: keys are typed on Settings and change
    while the container runs, so what the sub-app gets is a CALLBACK it asks
    per call -- installed in two places (the module global the WORKER THREAD
    reads, and app.state where it can be seen)."""
    import sys as _sys

    app = _app(tmp_path)
    assert app.state.ytdl_status == ytdl.MOUNTED
    fake_backend = _sys.modules["ytdlweb.ai_backend"]
    assert len(fake_backend.installed) == 1
    assert _sys.modules["ytdlweb.main"].app.state.ai_provider_lookup is \
        fake_backend.installed[0]


def test_the_installed_lookup_answers_from_the_live_database(tmp_path, ytdl_env):
    """End to end: a key stored through the admin route is what the ytdl app's
    next call resolves to -- no restart, no env var."""
    import sys as _sys

    from ccsync_dashboard import ai_providers

    app = _app(tmp_path)
    lookup = _sys.modules["ytdlweb.ai_backend"].installed[0]
    assert lookup()["provider"] == ""          # nothing configured yet
    ai_providers.set_key(app.state.settings, "deepseek_api", "sk-live-value-abcd")
    payload = lookup()
    assert payload["provider"] == "deepseek_api"
    assert payload["api_key"] == "sk-live-value-abcd"
    assert payload["cli_enabled"] is False


def test_an_older_ytdl_tree_with_no_ai_backend_still_mounts(tmp_path, ytdl_env,
                                                            monkeypatch):
    """Best-effort in both directions: a tree that predates the provider layer
    keeps working off its own environment, and a failure to install the hook
    must never cost the mount."""
    import sys as _sys

    monkeypatch.delitem(_sys.modules, "ytdlweb.ai_backend")
    monkeypatch.delattr(_sys.modules["ytdlweb"], "ai_backend")
    app = _app(tmp_path)
    assert app.state.ytdl_status == ytdl.MOUNTED
