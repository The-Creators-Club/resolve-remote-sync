"""The b-roll search UI mounted at /broll.

Editors get one URL and one login instead of a second service to reach and sign
in to. Both apps are FastAPI, so this is a real in-process mount: the b-roll
media routes serve video with Range requests, and a reverse proxy in front of
them would reintroduce the header-passthrough problem broll's own DEPLOY.md
warns about.

These tests do NOT need the b-roll repo checked out. They used to: six of eight
were gated on a hardcoded E:/Projects/broll-platform/web, so on CI, on the NAS,
and on every machine but one developer's they skipped in silence and pytest
exited 0 -- including every auth test. Instead we install a small fake `app`
package into sys.modules that mirrors the real one's contract, INCLUDING its
dev-mode "no token configured means ingest is open" hole, so the tests prove
that our own gate closes it rather than trusting upstream not to open it.
"""
from __future__ import annotations

import os
import sqlite3
import sys
import types
from pathlib import Path

import pytest
from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.testclient import TestClient

from ccsync_dashboard import auth, broll
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "s" * 32
# 48 hex chars, the shape `openssl rand -hex 24` produces -- what the deploy
# docs tell the operator to use, and what check_ingest_token demands.
TOKEN = "9f3c1ab27d4e5608bc19af730d25e8641c07b9a3f2de5061"


# --- a stand-in for the b-roll app -------------------------------------------

def _build_fake_broll(data_root_env: str) -> dict[str, types.ModuleType]:
    """The three modules ccsync_dashboard.broll imports from the b-roll repo.

    Faithful to the parts of the contract the mount depends on: `app.main.app`
    is a FastAPI, `app.config` resolves its directories from BROLL_DATA_ROOT at
    call time, `app.db.ensure_schema` creates the SQLite file. The ingest route
    deliberately reproduces upstream's verify_ingest_token, dev-mode branch and
    all.
    """
    import os
    from pathlib import Path

    pkg = types.ModuleType("app")
    pkg.__path__ = []  # a package, so `from app.x import y` resolves

    config = types.ModuleType("app.config")

    def get_data_root() -> Path:
        return Path(os.environ.get(data_root_env, "./data")).resolve()

    config.get_data_root = get_data_root
    config.get_db_path = lambda: get_data_root() / "broll.db"
    config.get_proxies_dir = lambda: get_data_root() / "proxies"
    config.get_sprites_dir = lambda: get_data_root() / "sprites"
    config.get_posters_dir = lambda: get_data_root() / "posters"
    config.get_sheets_dir = lambda: get_data_root() / "sheets"
    config.get_ingest_token = lambda: os.environ.get("BROLL_INGEST_TOKEN") or None

    db = types.ModuleType("app.db")

    def ensure_schema(path) -> None:
        conn = sqlite3.connect(str(path))
        conn.execute("CREATE TABLE IF NOT EXISTS videos (share TEXT, rel_path TEXT)")
        conn.commit()
        conn.close()

    db.ensure_schema = ensure_schema

    main = types.ModuleType("app.main")
    broll_app = FastAPI(title="B-Roll Platform (fake)")

    def verify_ingest_token(x_ingest_token: str | None = Header(default=None)) -> None:
        # Upstream, verbatim in spirit: unset token == dev mode == wide open.
        expected = config.get_ingest_token()
        if expected is None:
            return
        if x_ingest_token != expected:
            raise HTTPException(status_code=401, detail="missing or invalid X-Ingest-Token")

    ingest = APIRouter(prefix="/api/ingest",
                       dependencies=[Depends(verify_ingest_token)])

    @ingest.post("/shares")
    def ingest_shares(body: list[dict]) -> dict:
        return {"ok": True, "shares": len(body)}

    broll_app.include_router(ingest)

    @broll_app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return "<html><body>B-ROLL SEARCH</body></html>"

    @broll_app.get("/api/search")
    def search() -> dict:
        return {"results": []}

    @broll_app.get("/media/proxy/{name}")
    def media(name: str) -> dict:
        return {"name": name}

    main.app = broll_app
    pkg.config, pkg.db, pkg.main = config, db, main
    return {"app": pkg, "app.config": config, "app.db": db, "app.main": main}


@pytest.fixture
def broll_env(tmp_path, monkeypatch):
    """Install the fake b-roll package and point its data root at tmp_path.

    monkeypatch.setitem cleans sys.modules up afterwards, so the fake never
    leaks into another test module the way the old sys.path.insert(0, ...) did.
    """
    monkeypatch.setenv("BROLL_DATA_ROOT", str(tmp_path / "brolldata"))
    monkeypatch.setenv("BROLL_INGEST_TOKEN", TOKEN)
    for name, module in _build_fake_broll("BROLL_DATA_ROOT").items():
        monkeypatch.setitem(sys.modules, name, module)
    return tmp_path


def _app(tmp_path, **kw):
    return create_app(Settings(db_path=str(tmp_path / "d.db"), session_secret=SECRET, **kw))


def _broll_app(tmp_path, **kw):
    kw.setdefault("broll_ingest_token", TOKEN)
    return _app(tmp_path, broll_enabled=True, **kw)


def as_user(client, user="jsmith"):
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, user))
    return client


# --- the dashboard must survive the feature being absent or broken ------------

def test_dashboard_starts_with_the_feature_off(tmp_path):
    app = _app(tmp_path)
    with TestClient(app) as c:
        assert c.get("/api/v1/health").status_code == 200
    assert app.state.broll_mounted is False, "off by default, nothing mounted"
    assert app.state.broll_status == broll.ABSENT


def test_an_unimportable_broll_checkout_never_takes_the_dashboard_down(tmp_path, monkeypatch):
    """The dashboard is what tells the whole fleet whether their footage is
    syncing. An optional feature must not be able to stop it booting, so the
    import is guarded and a failure is logged rather than raised."""
    import builtins

    real_import = builtins.__import__

    def fail_on_broll(name, *a, **kw):
        if name == "app.main" or name.startswith("app."):
            raise ImportError("simulated: /broll-app volume missing")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", fail_on_broll)
    app = _broll_app(tmp_path)
    monkeypatch.setattr(builtins, "__import__", real_import)

    assert app.state.broll_mounted is False
    assert app.state.broll_status == broll.ABSENT
    with TestClient(app) as c:
        assert c.get("/api/v1/health").status_code == 200


def test_a_data_root_it_cannot_prepare_is_mounted_but_never_advertised(tmp_path, broll_env,
                                                                       monkeypatch):
    """The failure mode this used to have: _init_broll_storage raises (the
    archive bind mount is owned by someone else, so mkdir/ensure_schema hit
    PermissionError), the exception is logged, the mount is reported as a
    success anyway, and the nav offers a link to an app that 500s on every
    request. Degraded is not mounted."""
    def boom(path):
        raise PermissionError(f"[Errno 13] Permission denied: {path}")

    monkeypatch.setattr(sys.modules["app.db"], "ensure_schema", boom)
    app = _broll_app(tmp_path)

    assert app.state.broll_status == broll.DEGRADED
    assert app.state.broll_mounted is False, "a broken mount is never advertised"
    with TestClient(app) as c:
        assert c.get("/api/v1/health").status_code == 200
        page = as_user(c).get("/")
        assert page.status_code == 200
        assert "[ B-ROLL ]" not in page.text


# --- the mount itself ---------------------------------------------------------

def test_the_ui_is_served_under_the_prefix(tmp_path, broll_env):
    app = _broll_app(tmp_path)
    with TestClient(app) as c:
        assert app.state.broll_mounted is True
        assert app.state.broll_status == broll.MOUNTED
        # Unauthenticated: the gate should bounce a page request to login,
        # which proves the mount is behind the dashboard's auth.
        r = c.get("/broll/", follow_redirects=False)
        assert r.status_code == 303
        assert "/login" in r.headers["location"]


def test_a_signed_in_editor_renders_a_page_through_the_mount(tmp_path, broll_env):
    """The test that was missing: nothing ever proved a page came out of the
    b-roll app rather than out of login_gate. A 401/303 on an unmounted path
    looks identical."""
    app = _broll_app(tmp_path)
    with TestClient(app) as c:
        as_user(c)
        page = c.get("/broll/")
        assert page.status_code == 200, page.text
        assert "B-ROLL SEARCH" in page.text
        assert c.get("/broll/api/search").json() == {"results": []}
        # ...and the nav offers the link, which it must only ever do when the
        # mount is fully working.
        assert "[ B-ROLL ]" in c.get("/").text


def test_the_lifespan_shim_creates_the_database(tmp_path, broll_env):
    """Starlette does NOT run a mounted sub-app's lifespan. Without the shim the
    data dirs are never made and the schema never applied, so the first request
    hits a database that does not exist."""
    app = _broll_app(tmp_path)
    with TestClient(app):
        assert app.state.broll_mounted is True
        assert (broll_env / "brolldata" / "broll.db").is_file()
        assert (broll_env / "brolldata" / "proxies").is_dir()


def test_dashboard_routes_are_unchanged_by_the_mount(tmp_path, broll_env):
    """A b-roll route must never shadow a dashboard one."""
    app = _broll_app(tmp_path)
    with TestClient(app) as c:
        assert app.state.broll_mounted is True
        assert c.get("/api/v1/health").status_code == 200
        assert c.get("/login").status_code == 200


def test_the_sub_apps_interactive_docs_are_not_published(tmp_path, broll_env):
    """Mounting a second FastAPI() brings /docs, /redoc and /openapi.json with
    it. The dashboard publishes no API explorer; neither does its mount."""
    app = _broll_app(tmp_path)
    with TestClient(app) as c:
        as_user(c)
        for path in ("/broll/docs", "/broll/redoc", "/broll/openapi.json"):
            assert c.get(path).status_code == 404, path


# --- auth --------------------------------------------------------------------

def test_api_and_media_answer_401_json_not_a_login_redirect(tmp_path, broll_env):
    """These are fetched by JS and by <video>, neither of which can follow a 303
    to an HTML page: the SPA would parse the login page as JSON and the player
    would fail opaquely."""
    app = _broll_app(tmp_path)
    with TestClient(app) as c:
        assert app.state.broll_mounted is True
        for path in ("/broll/api/search", "/broll/media/proxy/1.mp4"):
            r = c.get(path, follow_redirects=False)
            assert r.status_code == 401, path
            assert r.json()["detail"] == "login required"


def test_the_indexer_can_ingest_with_the_right_token(tmp_path, broll_env):
    app = _broll_app(tmp_path)
    with TestClient(app) as c:
        r = c.post("/broll/api/ingest/shares",
                   json=[{"share": "s", "root": "Z:/x"}],
                   headers={"X-Ingest-Token": TOKEN})
        assert r.status_code == 200, r.text
        assert r.json() == {"ok": True, "shares": 1}

        bad = c.post("/broll/api/ingest/shares",
                     json=[{"share": "s", "root": "Z:/x"}],
                     headers={"X-Ingest-Token": "wrong"}, follow_redirects=False)
        assert bad.status_code in (401, 303)


def test_a_session_alone_can_never_reach_ingest(tmp_path, broll_env, monkeypatch):
    """The verified hole: with no BROLL_INGEST_TOKEN in the environment the
    b-roll app's own guard flips to dev mode, so every logged-in editor -- or
    anyone with a stolen session cookie -- could POST /broll/api/ingest/shares
    and repoint every clip's archive path. The dashboard's own gate re-checks
    the token on every ingest request and does not consult the environment, so
    the sub-app's dev mode is unreachable here."""
    monkeypatch.delenv("BROLL_INGEST_TOKEN", raising=False)
    app = _broll_app(tmp_path)          # token still supplied via Settings
    assert app.state.broll_mounted is True
    with TestClient(app) as c:
        as_user(c)
        r = c.post("/broll/api/ingest/shares", json=[{"share": "s", "root": "Z:/x"}],
                   follow_redirects=False)
        assert r.status_code == 401, r.text
        assert "X-Ingest-Token" in r.json()["detail"]
        # and the fake sub-app really is in dev mode -- i.e. it is OUR gate
        # doing the refusing, not upstream's
        assert sys.modules["app.config"].get_ingest_token() is None


# --- the token is a credential, and is treated like one ----------------------

@pytest.mark.parametrize("token", ["", "   ", "REPLACE_ME", "replace_me", "tok-123",
                                   "changeme", "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"])
def test_the_dashboard_refuses_to_start_with_a_weak_ingest_token(tmp_path, broll_env,
                                                                 monkeypatch, token):
    """`BROLL_INGEST_TOKEN: "REPLACE_ME"` shipped in compose.yaml and, unlike
    every other REPLACE_ME, it WORKED -- a live credential published in the
    repo. Blank was worse: it opened ingest to any session. Both must stop the
    app from starting rather than quietly serve a write path."""
    monkeypatch.delenv("BROLL_INGEST_TOKEN", raising=False)
    with pytest.raises(RuntimeError) as e:
        _app(tmp_path, broll_enabled=True, broll_ingest_token=token)
    assert "BROLL_INGEST_TOKEN" in str(e.value)


def test_a_weak_token_does_not_stop_a_dashboard_that_is_not_serving_broll(tmp_path):
    app = _app(tmp_path, broll_ingest_token="REPLACE_ME")
    with TestClient(app) as c:
        assert c.get("/api/v1/health").status_code == 200


# --- optional: the same thing against a real checkout ------------------------

def test_a_real_checkout_still_satisfies_the_contract_the_fake_models(tmp_path, monkeypatch):
    """Proves the fake has not drifted from the real app -- same module names,
    same `app.main.app`, same lifespan work.

    No longer opt-in: the b-roll platform was folded into this repo as broll/
    on 2026-08-10, so the real web app is present wherever the repo is and this
    check runs on every machine rather than on whoever remembered to set
    BROLL_WEB_SRC (which still overrides, for a checkout kept elsewhere). The
    fake stays the primary coverage all the same: the web app's own
    dependencies need not be installed in the dashboard venv, and when they are
    not this skips while everything above still runs."""
    raw = os.environ.get("BROLL_WEB_SRC", "").strip()
    src = (Path(raw) if raw else Path(__file__).resolve().parents[2] / "broll" / "web").resolve()
    if not (src / "app" / "main.py").is_file():
        pytest.skip(f"no app/main.py under {src}")
    monkeypatch.setenv("BROLL_DATA_ROOT", str(tmp_path / "brolldata"))
    monkeypatch.setenv("BROLL_INGEST_TOKEN", TOKEN)
    monkeypatch.syspath_prepend(str(src))       # undone at teardown
    for name in [n for n in sys.modules if n == "app" or n.startswith("app.")]:
        monkeypatch.delitem(sys.modules, name, raising=False)
    try:
        import app.main  # noqa: F401
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"the checkout's own dependencies are not installed here: {e}")

    dash = _broll_app(tmp_path)
    assert dash.state.broll_status == broll.MOUNTED
    with TestClient(dash) as c:
        as_user(c)
        assert c.get("/broll/").status_code == 200
        assert c.get("/broll/docs").status_code == 404
        assert c.post("/broll/api/ingest/shares",
                      json=[{"share": "s", "root": "Z:/x"}]).status_code == 401


def test_check_ingest_token_accepts_what_the_docs_tell_operators_to_generate():
    assert broll.check_ingest_token(TOKEN) is None
    # `openssl rand -hex 24` -- the exact recipe in compose.yaml
    assert broll.check_ingest_token("a" * 24 + "b" * 24) is not None, "still too uniform"
    assert broll.check_ingest_token("0123456789abcdef01234567") is None
