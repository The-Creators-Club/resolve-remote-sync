"""The /ytdl mount's two credentials-and-switches problems, 2026-08-21.

test_ytdl_mount.py owns the mount's tri-state and the identity header. This
file owns the two things the bug hunt found around them:

  - **dash-release-ai-1**: the site switch has TWO homes -- the container's
    DASH_SITE_YOUTUBE_DOWNLOAD and a `site_settings` row -- and the mount read
    only the environment. `GET /api/v1/site` resolves the row FIRST, so on a
    vendor build (env unset) an admin ticking "YouTube downloader" on Settings
    turned the feature on for every companion in the fleet while the dashboard
    itself went on 404ing /ytdl, restart or no restart. The reverse was as
    wrong: env=1 with the box unticked left the dashboard serving downloads the
    site says it does not do.
  - **ytdl-web-1**: the sub-app can only check the shared DASH_REPORT_TOKEN,
    because a per-editor `cce1.` token's hash lives in this database. The gate
    resolves the credential and stamps its verdict; the stamp is stripped
    inbound first, exactly as the identity header is.

The fake `ytdlweb` is built here rather than imported from test_ytdl_mount so
this file keeps working whatever that one's fake grows: what it must model is
`ytdlweb.routes_fleet.trust_gate_stamp` and a route that echoes the stamped
headers, neither of which the mount tests care about.
"""
from __future__ import annotations

import os
import sqlite3
import sys
import types
from pathlib import Path

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.testclient import TestClient

from ccsync_dashboard import auth, db, site_store, ytdl
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "s" * 32
SHARED = "t" * 32
ROW_KEY = "features.youtube_download"


def _build_fake_ytdlweb() -> dict[str, types.ModuleType]:
    pkg = types.ModuleType("ytdlweb")
    pkg.__path__ = []

    config = types.ModuleType("ytdlweb.config")
    config.DATA_ROOT = Path(os.environ.get("YTDL_DATA_ROOT", "./data")).resolve()
    config.DB_PATH = config.DATA_ROOT / "ytdl.db"

    dbm = types.ModuleType("ytdlweb.db")

    def connect(path=None):
        p = Path(path or config.DB_PATH)
        p.parent.mkdir(parents=True, exist_ok=True)
        return sqlite3.connect(p, timeout=30)

    def init(con) -> None:
        con.executescript("CREATE TABLE IF NOT EXISTS jobs (id INTEGER PRIMARY KEY);")
        con.commit()

    dbm.connect, dbm.init = connect, init

    worker = types.ModuleType("ytdlweb.worker")
    worker.started = 0

    def ensure_started() -> None:
        worker.started += 1

    worker.ensure_started = ensure_started

    ai_backend = types.ModuleType("ytdlweb.ai_backend")
    ai_backend.set_provider_lookup = lambda fn: None

    # The real one is a module global read by a request handler with no app
    # object in hand (ytdl-web-1); the fake records that the mount set it.
    routes_fleet = types.ModuleType("ytdlweb.routes_fleet")
    routes_fleet.trusted = []
    routes_fleet.trust_gate_stamp = lambda on=True: routes_fleet.trusted.append(on)

    main = types.ModuleType("ytdlweb.main")
    sub = FastAPI(title="YouTube Downloader (fake)")

    @sub.get("/", response_class=HTMLResponse)
    def home() -> str:
        return "<html><body>YOUTUBE DOWNLOADER</body></html>"

    @sub.post("/api/jobs/{job_id}/claim")
    def claim(job_id: int, request: Request) -> dict:
        # Echoed raw, including the absent case: what the gate did to the
        # headers is what these tests observe.
        return {"job_id": job_id,
                "stamp": request.headers.get("x-ccsync-fleet-auth"),
                "user": request.headers.get("x-ccsync-user")}

    main.app = sub
    pkg.config, pkg.db, pkg.main, pkg.worker = config, dbm, main, worker
    pkg.ai_backend, pkg.routes_fleet = ai_backend, routes_fleet
    return {"ytdlweb": pkg, "ytdlweb.config": config, "ytdlweb.db": dbm,
            "ytdlweb.main": main, "ytdlweb.worker": worker,
            "ytdlweb.ai_backend": ai_backend,
            "ytdlweb.routes_fleet": routes_fleet}


@pytest.fixture
def ytdl_env(tmp_path, monkeypatch):
    monkeypatch.setenv("YTDL_DATA_ROOT", str(tmp_path / "ytdldata"))
    monkeypatch.setenv("YTDL_PROJECTS_ROOT", str(tmp_path / "projects"))
    # The feature flag is re-read per request; at 5 s a test that ticks the box
    # would be a sleep. The TTL is about poll cost, not about correctness.
    monkeypatch.setattr(ytdl, "FEATURE_TTL_SECONDS", 0.0)
    for name, module in _build_fake_ytdlweb().items():
        monkeypatch.setitem(sys.modules, name, module)
    return tmp_path


def _settings(tmp_path, **kw) -> Settings:
    """The VENDOR BUILD's shape: DASH_SITE_YOUTUBE_DOWNLOAD is not set."""
    kw.setdefault("site_feature_youtube_download", False)
    return Settings(db_path=str(tmp_path / "d.db"), session_secret=SECRET, **kw)


def _set_row(settings: Settings, value: str) -> None:
    """Tick (or untick) the box on Settings, as the admin route does."""
    conn = db.connect(settings.db_path)
    try:
        db.migrate(conn)
        site_store.set_many(conn, {ROW_KEY: value}, "alex")
        conn.commit()
    finally:
        conn.close()


def as_user(client, user="jsmith"):
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, user))
    return client


# --- the site switch has two homes (dash-release-ai-1) ------------------------

def test_a_settings_tick_mounts_the_downloader_with_no_env_var(tmp_path, ytdl_env):
    """The customer-admin path in the shipped vendor build: no env var anywhere,
    one tick on Settings, and /ytdl has to answer -- because that same tick is
    what /api/v1/site publishes to every companion in the fleet."""
    settings = _settings(tmp_path)
    _set_row(settings, "1")

    app = create_app(settings)
    assert app.state.ytdl_status == ytdl.MOUNTED
    assert app.state.ytdl_mounted is True
    with TestClient(app) as c:
        assert "YOUTUBE DOWNLOADER" in as_user(c).get("/ytdl/").text


def test_an_untouched_site_is_still_off(tmp_path, ytdl_env):
    """Off is the vendor build's shape and it must stay off: the customer, not
    the vendor, decides whether downloading third-party YouTube material is
    lawful for them."""
    app = create_app(_settings(tmp_path))
    assert app.state.ytdl_status == ytdl.DISABLED
    assert app.state.ytdl_mounted is False
    with TestClient(app) as c:
        assert as_user(c).get("/ytdl/").status_code == 404
    assert sys.modules["ytdlweb.worker"].started == 0, (
        "an off site must not import or start anything")


def test_the_tick_takes_effect_without_a_restart(tmp_path, ytdl_env):
    """WP D's promise, and the reason the gate re-reads the flag per request:
    the companions learn about the feature the moment the row is written, and
    they start calling the fleet routes at once."""
    settings = _settings(tmp_path)
    app = create_app(settings)
    assert app.state.ytdl_status == ytdl.DISABLED
    with TestClient(app) as c:
        as_user(c)
        assert c.get("/ytdl/").status_code == 404
        _set_row(settings, "1")
        assert "YOUTUBE DOWNLOADER" in c.get("/ytdl/").text
        # ...and the nav catches up with it, rather than advertising nothing
        # until somebody restarts the container.
        assert app.state.ytdl_mounted is True
        assert 'href="/ytdl/"' in c.get("/").text


def test_unticking_the_box_stops_serving_it(tmp_path, ytdl_env):
    """The reverse was as wrong: env=1 and the box unticked left the dashboard
    downloading for a site whose manifest says it does not."""
    settings = _settings(tmp_path, site_feature_youtube_download=True)
    app = create_app(settings)
    assert app.state.ytdl_status == ytdl.MOUNTED
    with TestClient(app) as c:
        as_user(c)
        assert c.get("/ytdl/").status_code == 200
        _set_row(settings, "0")
        assert c.get("/ytdl/").status_code == 404
        assert app.state.ytdl_mounted is False


def test_an_off_site_serves_no_fleet_route_either(tmp_path, ytdl_env):
    """The companion's half is under the same prefix, so it goes with it: a
    machine-to-machine route answering while the site says no would be the one
    way a download could still happen."""
    settings = _settings(tmp_path, report_token=SHARED)
    app = create_app(settings)
    with TestClient(app) as c:
        r = c.post("/ytdl/api/jobs/1/claim", json={},
                   headers={"X-CCSync-Token": SHARED})
        assert r.status_code == 404


def test_the_row_wins_over_the_environment_in_both_directions(tmp_path, ytdl_env):
    """Same precedence ai_providers.cli_enabled reads, and the same one
    site_store.resolved_manifest publishes."""
    settings = _settings(tmp_path, site_feature_youtube_download=True)
    _set_row(settings, "0")
    assert ytdl.feature_enabled(settings) is False
    _set_row(settings, "1")
    assert ytdl.feature_enabled(settings) is True


def test_an_unreadable_database_falls_back_to_the_environment(tmp_path, ytdl_env,
                                                              monkeypatch):
    """A legal switch is never flipped on a customer's behalf by an error."""
    def boom(*_a, **_k):
        raise sqlite3.OperationalError("unable to open database file")

    monkeypatch.setattr(ytdl.db, "connect", boom)
    assert ytdl.feature_enabled(_settings(tmp_path)) is False
    assert ytdl.feature_enabled(
        _settings(tmp_path, site_feature_youtube_download=True)) is True


# --- the machine credential the sub-app cannot check itself (ytdl-web-1) ------

def _mint(settings: Settings, editor: str) -> str:
    conn = db.connect(settings.db_path)
    try:
        db.migrate(conn)
        token, _row = db.create_editor_report_token(conn, editor, "alex")
        conn.commit()
        return token
    finally:
        conn.close()


def test_the_mount_tells_the_sub_app_it_may_believe_the_stamp(tmp_path, ytdl_env):
    """Installed the way the AI-provider lookup is, and best-effort in the same
    way: an older ytdl tree with no routes_fleet must still mount."""
    create_app(_settings(tmp_path, site_feature_youtube_download=True))
    assert sys.modules["ytdlweb.routes_fleet"].trusted == [True]


def test_a_per_editor_token_reaches_the_sub_app_as_its_editor(tmp_path, ytdl_env):
    """THE DEFECT. The dashboard's own gate already accepts a cce1 token; the
    sub-app cannot check one, so before this it answered 403 to every
    claim/heartbeat/status POST from an editor whose admin had minted one --
    and requester-first downloads are the only way YouTube originals have
    reached editors since 2026-08-16."""
    settings = _settings(tmp_path, site_feature_youtube_download=True,
                         report_token=SHARED)
    token = _mint(settings, "kchen")
    app = create_app(settings)
    with TestClient(app) as c:
        r = c.post("/ytdl/api/jobs/7/claim", json={},
                   headers={"X-CCSync-Token": token})
        assert r.status_code == 200, r.text
        assert r.json()["stamp"] == "editor:kchen"


def test_the_shared_token_is_stamped_as_the_shared_one(tmp_path, ytdl_env):
    """It identifies nobody, and the stamp says exactly that -- which is why
    X-CCSync-Identity exists beside it."""
    settings = _settings(tmp_path, site_feature_youtube_download=True,
                         report_token=SHARED)
    app = create_app(settings)
    with TestClient(app) as c:
        r = c.post("/ytdl/api/jobs/7/claim", json={},
                   headers={"X-CCSync-Token": SHARED})
        assert r.json()["stamp"] == "shared"


def test_a_forged_stamp_never_reaches_the_sub_app(tmp_path, ytdl_env):
    """The whole reason the sub-app may believe it: the gate strips before it
    appends. A stamp the caller wrote would otherwise be the entire
    authorisation story for "may this machine download for the fleet"."""
    settings = _settings(tmp_path, site_feature_youtube_download=True,
                         report_token=SHARED)
    app = create_app(settings)
    with TestClient(app) as c:
        forged = {"X-CCSync-Fleet-Auth": "editor:admin"}
        as_user(c, "jsmith")
        assert c.post("/ytdl/api/jobs/7/claim", json={},
                      headers=forged).json()["stamp"] is None
        # ...including alongside a credential that is real but not that one
        r = c.post("/ytdl/api/jobs/7/claim", json={},
                   headers={"X-CCSync-Token": SHARED, **forged})
        assert r.json()["stamp"] == "shared"


def test_a_revoked_or_unknown_token_is_stamped_with_nothing(tmp_path, ytdl_env):
    """The stamp is our verdict, not a transcription: a token we do not
    recognise leaves the sub-app to its own fail-closed 403."""
    settings = _settings(tmp_path, site_feature_youtube_download=True,
                         report_token=SHARED)
    app = create_app(settings)
    with TestClient(app) as c:
        as_user(c, "jsmith")
        for token in ("cce1.deadbeefdeadbeef." + "0" * 48, "not-the-shared-one"):
            r = c.post("/ytdl/api/jobs/7/claim", json={},
                       headers={"X-CCSync-Token": token})
            assert r.json()["stamp"] is None, token
