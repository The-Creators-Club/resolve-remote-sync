"""The music search UI mounted at /music.

Modelled on test_broll_mount.py, and for the same reason: editors get one URL
and one login instead of a third service to reach and sign in to, and the mount
is in-process because /api/audio serves Range/206 and a reverse proxy in front
of it reintroduces the header-passthrough problem.

These tests do NOT need music/web importable. They must not: the dashboard venv
has no numpy, and musicweb imports it at module scope, so on this machine (and
on the container, and on CI) a real import is an ImportError -- which is exactly
one of the states under test. Everything else runs against a small fake
`musicweb` package installed into sys.modules, mirroring the real one's
contract: `musicweb.main.app` is a FastAPI, `musicweb.config.DATA_ROOT` is a
Path read from the environment at import time, and `musicweb.db` connects to
DATA_ROOT/music.db and applies a schema.

The tri-state is the point of most of this file. absent = the code is not
there; degraded = the code is there and its data root cannot be opened, so
every request 500s with "unable to open database file". Both hide the nav link,
and neither may stop the dashboard booting -- it is what tells the whole fleet
whether their footage is syncing.
"""
from __future__ import annotations

import os
import sqlite3
import sys
import types
from pathlib import Path

import pytest
from fastapi import APIRouter, FastAPI, Header
from fastapi.responses import HTMLResponse
from fastapi.testclient import TestClient

from ccsync_dashboard import auth, music
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "s" * 32


# --- a stand-in for the music app --------------------------------------------

def _build_fake_musicweb() -> dict[str, types.ModuleType]:
    """The three modules ccsync_dashboard.music imports from music/web.

    The package is `musicweb`, deliberately NOT `app`: broll/web is imported as
    the top-level package `app`, and a second package of that name on the same
    PYTHONPATH would collide in sys.modules and one of the two would silently
    win. The fake keeps the same name for the same reason -- and so this file
    and test_broll_mount.py can install their fakes side by side.

    config resolves DATA_ROOT from the environment AT IMPORT TIME, as the real
    musicweb.config does (it is module-level, not a function), so the fixture
    sets the env var before building this.
    """
    pkg = types.ModuleType("musicweb")
    pkg.__path__ = []  # a package, so `from musicweb.x import y` resolves

    config = types.ModuleType("musicweb.config")
    config.DATA_ROOT = Path(os.environ.get("DATA_ROOT", "./data")).resolve()
    config.DB_PATH = config.DATA_ROOT / "music.db"
    config.MUSIC_ROOT = Path(os.environ.get("MUSIC_ROOT", "./library")).resolve()

    # musicweb's ingest is fail-closed standalone since 2026-08-17
    # (COMMERCIAL_READINESS.md item 15); the mount is what declares that a
    # login gate is wrapped around it. Faithful to upstream, and the flag the
    # test below reads.
    config.login_gated_calls = []

    def set_login_gated(value=True):
        config.login_gated_calls.append(bool(value))

    config.set_login_gated = set_login_gated

    db = types.ModuleType("musicweb.db")

    def connect(path=None):
        p = Path(path or config.DB_PATH)
        p.parent.mkdir(parents=True, exist_ok=True)
        return sqlite3.connect(p, timeout=30)

    def init(con) -> None:
        con.executescript(
            "CREATE TABLE IF NOT EXISTS tracks (id INTEGER PRIMARY KEY, rel_path TEXT);"
        )
        con.commit()

    db.connect = connect
    db.init = init
    db._schema_ready = False   # mounting must not flip this; see test below

    main = types.ModuleType("musicweb.main")
    music_app = FastAPI(title="Music Tagger (fake)")

    api = APIRouter()

    @api.get("/api/stats")
    def stats() -> dict:
        return {"tracks": 0}

    @api.get("/api/audio/{track_id}")
    def audio(track_id: int) -> dict:
        return {"track_id": track_id}

    @api.post("/api/ingest")
    def ingest() -> dict:
        # musicweb's write route carries no token WHEN MOUNTED: it is called by
        # the SPA from a logged-in browser and nothing about /music/* is
        # exempted from the dashboard's login_gate. Upstream only demands a
        # token when it is running standalone, with nothing in front of it --
        # see music/web/DEPLOY.md and music/web/tests/test_ingest_gate.py.
        return {"ok": True}

    music_app.include_router(api)

    @music_app.get("/", response_class=HTMLResponse)
    def home() -> str:
        return "<html><body>MUSIC SEARCH</body></html>"

    # The ingest PANEL (docs/MUSIC_INGEST_PLAN.md step 2): session-authorised
    # on a header the real musicweb reads and MusicGate mints. Echoed rather
    # than implemented -- what these tests are about is WHICH name (and whether
    # "admin") reaches the sub-app, which is the gate's job, not the panel's.
    @music_app.get("/api/ingest-batches")
    def list_batches(x_ccsync_user: str | None = Header(default=None),
                     x_ccsync_admin: str | None = Header(default=None)) -> dict:
        return {"user": x_ccsync_user, "admin": x_ccsync_admin}

    @music_app.post("/api/ingest-batches")
    def create_batch(x_ccsync_user: str | None = Header(default=None)) -> dict:
        return {"created_by": x_ccsync_user}

    @music_app.post("/api/ingest-batches/{uid}/cancel")
    def cancel_batch(uid: str, x_ccsync_user: str | None = Header(default=None),
                     x_ccsync_admin: str | None = Header(default=None)) -> dict:
        return {"uid": uid, "user": x_ccsync_user, "admin": x_ccsync_admin}

    # The companion's half: fleet-token authed, no session anywhere. Only the
    # carve-out in app.py decides whether these are reachable at all.
    @music_app.post("/api/fleet/ingest/batches/{uid}/claim")
    def fleet_claim(uid: str) -> dict:
        return {"claimed": uid}

    @music_app.post("/api/fleet/ingest/batches/{uid}/items/{iuid}/result")
    def fleet_result(uid: str, iuid: str) -> dict:
        return {"batch": uid, "item": iuid}

    @music_app.post("/api/fleet/ingest/batches/{uid}/items/{iuid}/uploaded")
    def fleet_uploaded(uid: str, iuid: str) -> dict:
        return {"batch": uid, "item": iuid}

    main.app = music_app
    pkg.config, pkg.db, pkg.main = config, db, main
    return {"musicweb": pkg, "musicweb.config": config,
            "musicweb.db": db, "musicweb.main": main}


@pytest.fixture
def music_env(tmp_path, monkeypatch):
    """Install the fake music package and point its data root at tmp_path.

    monkeypatch.setitem cleans sys.modules up afterwards, so the fake never
    leaks into another test module.
    """
    monkeypatch.setenv("DATA_ROOT", str(tmp_path / "musicdata"))
    monkeypatch.setenv("MUSIC_ROOT", str(tmp_path / "library"))
    for name, module in _build_fake_musicweb().items():
        monkeypatch.setitem(sys.modules, name, module)
    return tmp_path


@pytest.fixture
def no_musicweb(monkeypatch):
    """Make `import musicweb` fail, whatever is on this machine's disk.

    Without this the in-repo dev fallback (_add_in_repo_music_web) finds
    music/web in the checkout, and whether the import then succeeds depends on
    whether numpy happens to be in the venv -- a test that passes for a
    different reason on different machines is the failure mode the b-roll
    tests were rewritten to remove.
    """
    import builtins

    real_import = builtins.__import__

    def fail_on_musicweb(name, *a, **kw):
        if name == "musicweb" or name.startswith("musicweb."):
            raise ImportError("simulated: the music tree is not deployed here")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", fail_on_musicweb)
    for name in [n for n in sys.modules if n == "musicweb" or n.startswith("musicweb.")]:
        monkeypatch.delitem(sys.modules, name, raising=False)
    return real_import


def _app(tmp_path, **kw):
    return create_app(Settings(db_path=str(tmp_path / "d.db"), session_secret=SECRET, **kw))


def as_user(client, user="jsmith"):
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, user))
    return client


# --- the dashboard must survive the feature being absent or broken ------------

def test_an_absent_music_tree_never_takes_the_dashboard_down(tmp_path, no_musicweb,
                                                             monkeypatch):
    """The dashboard is what tells the whole fleet whether their footage is
    syncing. An optional feature must not be able to stop it booting, so the
    import is guarded and a failure is logged rather than raised."""
    import builtins

    app = _app(tmp_path)
    monkeypatch.setattr(builtins, "__import__", no_musicweb)

    assert app.state.music_status == music.ABSENT
    assert app.state.music_mounted is False
    with TestClient(app) as c:
        assert c.get("/api/v1/health").status_code == 200
        assert c.get("/login").status_code == 200


def test_an_absent_music_tree_is_not_advertised_in_the_nav(tmp_path, no_musicweb,
                                                           monkeypatch):
    import builtins

    app = _app(tmp_path)
    monkeypatch.setattr(builtins, "__import__", no_musicweb)

    with TestClient(app) as c:
        page = as_user(c).get("/")
        assert page.status_code == 200
        assert 'href="/music/"' not in page.text


def test_a_data_root_it_cannot_open_is_mounted_but_never_advertised(tmp_path, music_env,
                                                                    monkeypatch):
    """Degraded, the state that is easy to get wrong: musicweb imports fine but
    DATA_ROOT is a read-only bind mount or belongs to another uid, so sqlite
    answers "unable to open database file" on every request. Reporting that as
    a success is how the nav ends up offering a link to a page that 500s."""
    def boom(path=None):
        raise sqlite3.OperationalError("unable to open database file")

    monkeypatch.setattr(sys.modules["musicweb.db"], "connect", boom)
    app = _app(tmp_path)

    assert app.state.music_status == music.DEGRADED
    assert app.state.music_mounted is False, "a broken mount is never advertised"
    with TestClient(app) as c:
        assert c.get("/api/v1/health").status_code == 200
        page = as_user(c).get("/")
        assert page.status_code == 200
        assert 'href="/music/"' not in page.text


def test_degraded_is_still_reachable_for_whoever_types_the_url(tmp_path, music_env,
                                                               monkeypatch):
    """Mounted but unadvertised, exactly like b-roll: an operator who goes
    looking gets the sub-app (and its real error) rather than a 404 that says
    nothing about what is wrong."""
    def boom(path=None):
        raise sqlite3.OperationalError("unable to open database file")

    monkeypatch.setattr(sys.modules["musicweb.db"], "connect", boom)
    app = _app(tmp_path)
    with TestClient(app) as c:
        as_user(c)
        assert c.get("/music/").status_code == 200


# --- the mount itself ---------------------------------------------------------

def test_the_ui_is_served_under_the_prefix(tmp_path, music_env):
    app = _app(tmp_path)
    assert app.state.music_status == music.MOUNTED
    assert app.state.music_mounted is True
    with TestClient(app) as c:
        # Unauthenticated: the gate bounces a page request to login, which
        # proves the mount sits behind the dashboard's auth without musicweb
        # having any auth code of its own.
        r = c.get("/music/", follow_redirects=False)
        assert r.status_code == 303
        assert "/login" in r.headers["location"]


def test_the_bare_prefix_redirects_into_the_mount(tmp_path, music_env):
    """`/music` (no trailing slash) -> `/music/` is LOAD-BEARING, not
    incidental: it is the URL the topbar link and everything anyone types by
    hand use, and Starlette only serves the mount from the slashed form. It was
    pinned by music/web's own suite and by nothing on this side (KNOWN_BUGS
    DASH-9, 2026-08-11)."""
    app = _app(tmp_path)
    with TestClient(app) as c:
        as_user(c)
        r = c.get("/music", follow_redirects=False)
        assert r.status_code in (307, 308), r.status_code
        assert r.headers["location"].endswith("/music/")
        # ...and following it really lands in the sub-app
        assert "MUSIC SEARCH" in c.get("/music").text


def test_a_signed_in_editor_renders_a_page_through_the_mount(tmp_path, music_env):
    """That the request really reaches the sub-app, not just login_gate: a
    303 or 401 on an unmounted path looks identical from outside."""
    app = _app(tmp_path)
    with TestClient(app) as c:
        as_user(c)
        page = c.get("/music/")
        assert page.status_code == 200, page.text
        assert "MUSIC SEARCH" in page.text
        assert c.get("/music/api/stats").json() == {"tracks": 0}
        assert c.get("/music/api/audio/7").json() == {"track_id": 7}
        # ...and the nav offers the link, which it must only ever do when the
        # mount is fully working.
        assert 'href="/music/"' in c.get("/").text
        # The topbar partial the SPA injects marks the page it was fetched
        # for -- and only that page (see test_topbar_partial.py).
        marked = c.get("/partials/topbar?current=music").text
        assert 'nav-current" href="/music/"' in marked
        assert marked.count("nav-current") == 1


def test_the_storage_probe_creates_the_database(tmp_path, music_env):
    """Starlette does NOT run a mounted sub-app's lifespan. musicweb applies its
    schema lazily so nothing strictly has to be replicated, but running it here
    is what distinguishes MOUNTED from DEGRADED."""
    app = _app(tmp_path)
    assert app.state.music_mounted is True
    assert (music_env / "musicdata" / "music.db").is_file()


def test_mounting_does_not_mutate_musicwebs_own_globals(tmp_path, music_env):
    """The probe opens its own connection and closes it. Flipping
    db._schema_ready from out here would mean a later real request skips the
    schema apply on the strength of work done by a different connection."""
    app = _app(tmp_path)
    assert app.state.music_mounted is True
    assert sys.modules["musicweb.db"]._schema_ready is False


def test_mounting_declares_the_login_gate_to_musicweb(tmp_path, music_env):
    """musicweb's /api/ingest is fail-closed when it is not authenticated by
    anything (COMMERCIAL_READINESS.md item 15, 2026-08-17): standalone it
    demands MUSIC_INGEST_TOKEN. Mounted here the browser is already past
    login_gate and the SPA has no token to send, so the mount says so.

    A CALL rather than an env var on purpose -- a host that merely has a
    variable set is not a process with the middleware wrapped around it.
    """
    _app(tmp_path)
    assert sys.modules["musicweb.config"].login_gated_calls == [True]


def test_an_older_music_checkout_without_the_declaration_still_mounts(
        tmp_path, music_env, caplog):
    """Best-effort like everything else about this mount: a checkout that
    predates set_login_gated must not stop the dashboard booting."""
    del sys.modules["musicweb.config"].set_login_gated
    app = _app(tmp_path)
    assert app.state.music_mounted is True
    assert "login-gated" in caplog.text


def test_dashboard_routes_are_unchanged_by_the_mount(tmp_path, music_env):
    """A music route must never shadow a dashboard one."""
    app = _app(tmp_path)
    with TestClient(app) as c:
        assert c.get("/api/v1/health").status_code == 200
        assert c.get("/login").status_code == 200


def test_broll_and_music_can_be_mounted_side_by_side(tmp_path, music_env):
    """The whole reason the package is `musicweb` and not `app`. Both fakes are
    in sys.modules at once here; if the names collided one mount would silently
    serve the other's routes."""
    from test_broll_mount import TOKEN, _build_fake_broll

    for name, module in _build_fake_broll("BROLL_DATA_ROOT").items():
        sys.modules[name] = module
    os.environ["BROLL_DATA_ROOT"] = str(tmp_path / "brolldata")
    os.environ["BROLL_INGEST_TOKEN"] = TOKEN
    try:
        app = _app(tmp_path, broll_enabled=True, broll_ingest_token=TOKEN)
        assert app.state.broll_status == "mounted"
        assert app.state.music_status == music.MOUNTED
        with TestClient(app) as c:
            as_user(c)
            assert "B-ROLL SEARCH" in c.get("/broll/").text
            assert "MUSIC SEARCH" in c.get("/music/").text
    finally:
        for name in ("app", "app.config", "app.db", "app.main"):
            sys.modules.pop(name, None)
        os.environ.pop("BROLL_DATA_ROOT", None)
        os.environ.pop("BROLL_INGEST_TOKEN", None)


def test_the_sub_apps_interactive_docs_are_not_published(tmp_path, music_env):
    """Mounting a second FastAPI() brings /docs, /redoc and /openapi.json with
    it. The dashboard publishes no API explorer; neither does its mount."""
    app = _app(tmp_path)
    with TestClient(app) as c:
        as_user(c)
        for path in ("/music/docs", "/music/redoc", "/music/openapi.json"):
            assert c.get(path).status_code == 404, path


# --- auth --------------------------------------------------------------------

def test_the_api_answers_401_json_not_a_login_redirect(tmp_path, music_env):
    """The SPA fetches /music/api/... and <audio> loads /music/api/audio/{id};
    neither can follow a 303 to an HTML page. The SPA would parse the login
    page as JSON and the player would fail opaquely."""
    app = _app(tmp_path)
    with TestClient(app) as c:
        for path in ("/music/api/stats", "/music/api/audio/1"):
            r = c.get(path, follow_redirects=False)
            assert r.status_code == 401, path
            assert r.json()["detail"] == "login required"


def test_the_write_routes_are_behind_the_login_gate(tmp_path, music_env):
    """musicweb has no token of its own, so login_gate IS the credential for
    /api/ingest and /api/resolve* (reveal moved to the companion loopback,
    MUSIC-6 2026-08-14). Nothing about /music/* may be
    exempted from it -- that exemption is what b-roll needs a token to make
    safe, and the day music grows a machine-to-machine ingest it needs one
    too."""
    app = _app(tmp_path)
    with TestClient(app) as c:
        r = c.post("/music/api/ingest", follow_redirects=False)
        assert r.status_code == 401, r.text
        # and with a session it goes through -- i.e. it really is the gate
        as_user(c)
        assert c.post("/music/api/ingest").json() == {"ok": True}


# --- optional: the same thing against a real checkout ------------------------

def test_a_real_checkout_still_satisfies_the_contract_the_fake_models(tmp_path, monkeypatch):
    """Proves the fake has not drifted from music/web -- same module names, same
    `musicweb.main.app`, same config.DATA_ROOT and db.connect/init.

    Skips wherever musicweb's own dependencies are not installed, which is
    everywhere the dashboard runs today: numpy is imported at musicweb.db
    module scope and the dashboard venv does not have it. That skip is itself
    the ABSENT path in production, and it is covered above with a fake so it
    cannot skip silently."""
    raw = os.environ.get("MUSIC_WEB_SRC", "").strip()
    src = (Path(raw) if raw else Path(__file__).resolve().parents[2] / "music" / "web").resolve()
    if not (src / "musicweb" / "main.py").is_file():
        pytest.skip(f"no musicweb/main.py under {src}")
    monkeypatch.setenv("DATA_ROOT", str(tmp_path / "musicdata"))
    monkeypatch.setenv("MUSIC_ROOT", str(tmp_path / "library"))
    monkeypatch.syspath_prepend(str(src))       # undone at teardown
    for name in [n for n in sys.modules if n == "musicweb" or n.startswith("musicweb.")]:
        monkeypatch.delitem(sys.modules, name, raising=False)
    try:
        import musicweb.main  # noqa: F401
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"the checkout's own dependencies are not installed here: {e}")

    dash = _app(tmp_path)
    assert dash.state.music_status == music.MOUNTED
    with TestClient(dash) as c:
        as_user(c)
        assert c.get("/music/").status_code == 200
        assert c.get("/music/docs").status_code == 404


# --- identity: the ingest panel's headers are minted here, never accepted -----
#
# docs/MUSIC_INGEST_PLAN.md step 2, 2026-08-18. `/music/api/ingest-batches`
# makes per-user decisions with real consequences -- whose batches these are,
# and who may stop another machine's work -- and musicweb has no session code
# of its own. MusicGate is where the ccsync_session cookie becomes a name, on
# exactly the contract BrollGate and YtdlGate already run.

def test_the_sub_app_is_told_who_the_session_belongs_to(tmp_path, music_env):
    app = _app(tmp_path)
    with TestClient(app) as c:
        as_user(c, "kchen")
        assert c.get("/music/api/ingest-batches").json()["user"] == "kchen"
        assert c.post("/music/api/ingest-batches").json() == {"created_by": "kchen"}
        as_user(c, "jsmith")
        assert c.get("/music/api/ingest-batches").json()["user"] == "jsmith"


def test_a_forged_identity_header_never_reaches_the_sub_app(tmp_path, music_env):
    """SPOOF-PROOFING, and the reason the gate strips before it appends. A
    logged-in editor sails past login_gate with a valid session of their own;
    if their `fetch(url, {headers: {'X-CCSync-User': 'admin'}})` survived the
    trip, that header would be the whole authorisation story for "whose batch
    may I cancel"."""
    app = _app(tmp_path)
    with TestClient(app) as c:
        as_user(c, "jsmith")
        forged = {"X-CCSync-User": "kchen", "X-CCSync-Admin": "1"}
        body = c.get("/music/api/ingest-batches", headers=forged).json()
        assert body["user"] == "jsmith"
        assert body["admin"] is None, "a forged admin claim reached the sub-app"
        assert c.post("/music/api/ingest-batches/abc/cancel",
                      headers=forged).json()["user"] == "jsmith"


def test_a_real_admin_is_stamped_as_one(tmp_path, music_env):
    """`scope=all` (every machine's batches) and cancelling somebody else's
    work are gated on this header inside the sub-app, so it has to arrive for
    the people who really are admins -- and only them."""
    app = _app(tmp_path, admin_users="root, kchen")
    with TestClient(app) as c:
        as_user(c, "kchen")
        assert c.get("/music/api/ingest-batches").json()["admin"] == "1"
        as_user(c, "jsmith")
        assert c.get("/music/api/ingest-batches").json()["admin"] is None


def test_a_forged_header_survives_nothing_even_with_no_session(tmp_path, music_env):
    """login_gate answers this 401 long before the sub-app sees it, so this is
    the belt to that brace: even reached directly, the gate hands the sub-app
    NO identity rather than the caller's own claim."""
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

    gate = music.MusicGate(spy, Settings(db_path=":memory:", session_secret=SECRET))
    scope = {"type": "http", "method": "GET", "path": "/music/api/ingest-batches",
             "root_path": "/music",
             "headers": [(b"x-ccsync-user", b"admin"), (b"x-ccsync-admin", b"1"),
                         (b"cookie", b"ccsync_session=nonsense; other=1")]}
    asyncio.run(gate(scope, receive, send))

    assert not [k for k, _v in seen["headers"]
                if k in ("x-ccsync-user", "x-ccsync-admin")], (
        "a forged identity header reached the sub-app with no session at all")
    # ...and the gate did not mutate the caller's own scope on the way past:
    # it belongs to the server, and a mounted app is not the only reader.
    assert (b"x-ccsync-user", b"admin") in scope["headers"]


def test_the_identity_header_round_trips_a_latin1_name_and_withholds_a_cjk_one(
        tmp_path, music_env):
    """LATIN-1, because Starlette decodes headers latin-1: UTF-8 turned `josé`
    into `josÃ©` on arrival and that editor's own rows matched nothing
    (YTDL-29, 2026-08-11). A name beyond U+00FF has no lossless encoding and a
    lossy one could collide two editors, so the header is withheld entirely and
    the sub-app 401s -- broken loudly for one person, never quietly wrong."""
    app = _app(tmp_path)
    with TestClient(app) as c:
        as_user(c, "josé")
        assert c.get("/music/api/ingest-batches").json()["user"] == "josé"
        as_user(c, "小明")
        assert c.get("/music/api/ingest-batches").json()["user"] is None


def test_a_mount_with_no_settings_serves_search_but_stamps_nothing(tmp_path, music_env):
    """The music mount fails ABSENT, never fatal. A caller that has not been
    updated must get a working search UI with the ingest panel 401ing, not a
    dashboard that will not boot."""
    host = FastAPI()
    assert music.mount_music(host) == music.MOUNTED
    with TestClient(host) as c:
        c.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "jsmith"))
        assert c.get("/music/api/ingest-batches").json()["user"] is None


# --- the fleet carve-out (docs/MUSIC_INGEST_PLAN.md step 2) -------------------

FLEET_UID = "0123456789abcdef0123456789abcdef"
ITEM_UID = "fedcba9876543210fedcba9876543210"


def test_a_companion_reaches_the_fleet_routes_with_the_fleet_token(tmp_path, music_env):
    """These calls happen with no browser open, so there is no session to gate
    on. Without the carve-out every one of them gets a 303 to an HTML login
    page that no companion can follow, and music ingest stops fleet-wide."""
    token = "f" * 40
    app = _app(tmp_path, report_token=token)
    headers = {"X-CCSync-Token": token}
    with TestClient(app) as c:
        r = c.post(f"/music/api/fleet/ingest/batches/{FLEET_UID}/claim", json={},
                   headers=headers, follow_redirects=False)
        assert r.status_code == 200, r.text
        r = c.post(
            f"/music/api/fleet/ingest/batches/{FLEET_UID}/items/{ITEM_UID}/result",
            json={}, headers=headers, follow_redirects=False)
        assert r.status_code == 200, r.text


def test_the_carve_out_is_per_suffix_not_per_prefix(tmp_path, music_env):
    """A leaked fleet token must not read or stop a browser's batch: the SPA's
    own panel stays fully session-gated."""
    token = "f" * 40
    app = _app(tmp_path, report_token=token)
    with TestClient(app) as c:
        r = c.get("/music/api/ingest-batches", headers={"X-CCSync-Token": token},
                  follow_redirects=False)
        assert r.status_code == 401


def test_no_fleet_token_is_still_a_login_bounce(tmp_path, music_env):
    token = "f" * 40
    app = _app(tmp_path, report_token=token)
    with TestClient(app) as c:
        r = c.post(f"/music/api/fleet/ingest/batches/{FLEET_UID}/claim", json={},
                   follow_redirects=False)
        assert r.status_code == 401


@pytest.mark.parametrize("path", [
    # an id of the wrong shape -- the 32-hex uid is what the server mints
    "/music/api/fleet/ingest/batches/1/claim",
    f"/music/api/fleet/ingest/batches/{FLEET_UID}/items/1/result",
    # a suffix nobody defined
    f"/music/api/fleet/ingest/batches/{FLEET_UID}/delete",
    # ... and the b-roll pattern must not cover music, nor the other way round
    f"/music/api/fleet/ingest/batches/{FLEET_UID}/items/{ITEM_UID}/frames",
])
def test_only_the_six_fleet_shapes_skip_the_login_gate(tmp_path, music_env, path):
    token = "f" * 40
    app = _app(tmp_path, report_token=token)
    with TestClient(app) as c:
        r = c.post(path, json={}, headers={"X-CCSync-Token": token},
                   follow_redirects=False)
        assert r.status_code == 401, path


def test_the_music_and_broll_carve_outs_are_separate_patterns():
    """Two mounts, two prefixes. A widened pattern covering both would be one
    nobody can read a carve-out out of -- and one that a rename of either mount
    silently unguards."""
    from ccsync_dashboard import app as app_module
    source = Path(app_module.__file__).read_text(encoding="utf-8")
    assert "_music_fleet_re" in source
    assert r"^/music/api/fleet/ingest/batches/[0-9a-f]{32}/" in source
    assert r"^/broll/api/fleet/ingest/batches/[0-9a-f]{32}/" in source
