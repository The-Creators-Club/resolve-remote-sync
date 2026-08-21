"""What the music mount tells musicweb about `X-CCSync-Token` (music-1).

2026-08-21. musicweb compared that header against the shared DASH_REPORT_TOKEN
and nothing else, so an editor whose companion had adopted the per-editor
`cce1.<id>.<secret>` token an admin minted for them (preferred since
2026-08-17) got past the dashboard's login_gate carve-out and was then answered
403 by the music app itself: their dropped albums never left `queued`. Only
this side can verify such a token -- it means reading the dashboard's database,
which the separately deployed music tree cannot see -- so MusicGate resolves it
and stamps `X-CCSync-Fleet-Auth: shared|editor:<name>`.

The fake sub-app here echoes the headers it was handed, because what is under
test is which of them arrive, not what musicweb does with them (that half is
music/web/tests/test_fleet_ingest.py).
"""
from __future__ import annotations

import sys
import types

import pytest
from fastapi import FastAPI, Header
from fastapi.testclient import TestClient

from ccsync_dashboard import auth
from ccsync_dashboard import db as dbmod
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "s" * 32
SHARED = "f" * 40
FLEET_UID = "0123456789abcdef0123456789abcdef"


def _build_fake_musicweb(tmp_path) -> dict[str, types.ModuleType]:
    """The three modules ccsync_dashboard.music imports, minus the numpy.

    Same shape as test_music_mount.py's fake and for the same reason: the
    dashboard venv has no numpy, so a real `import musicweb` is an ImportError
    on this machine, on the container and on CI.
    """
    pkg = types.ModuleType("musicweb")
    pkg.__path__ = []

    config = types.ModuleType("musicweb.config")
    config.DATA_ROOT = tmp_path / "musicdata"
    config.DB_PATH = config.DATA_ROOT / "music.db"
    config.set_login_gated = lambda value=True: None

    db = types.ModuleType("musicweb.db")

    def connect(path=None):
        import sqlite3
        p = path or config.DB_PATH
        p.parent.mkdir(parents=True, exist_ok=True)
        return sqlite3.connect(p, timeout=30)

    db.connect = connect
    db.init = lambda con: None

    main = types.ModuleType("musicweb.main")
    music_app = FastAPI(title="Music Tagger (fake)")

    @music_app.post("/api/fleet/ingest/batches/{uid}/claim")
    def fleet_claim(uid: str,
                    x_ccsync_fleet_auth: str | None = Header(default=None),
                    x_ccsync_token: str | None = Header(default=None)) -> dict:
        return {"claimed": uid, "fleet_auth": x_ccsync_fleet_auth,
                "token_seen": bool(x_ccsync_token)}

    @music_app.get("/api/stats")
    def stats(x_ccsync_fleet_auth: str | None = Header(default=None)) -> dict:
        return {"fleet_auth": x_ccsync_fleet_auth}

    main.app = music_app
    pkg.config, pkg.db, pkg.main = config, db, main
    return {"musicweb": pkg, "musicweb.config": config,
            "musicweb.db": db, "musicweb.main": main}


@pytest.fixture
def env(tmp_path, monkeypatch):
    for name, module in _build_fake_musicweb(tmp_path).items():
        monkeypatch.setitem(sys.modules, name, module)
    settings = Settings(db_path=str(tmp_path / "d.db"), session_secret=SECRET,
                        report_token=SHARED, admin_users=frozenset({"admin"}))
    app = create_app(settings)
    with TestClient(app) as client:
        conn = dbmod.connect(settings.db_path)
        yield client, conn
        conn.close()


def claim(client, token):
    return client.post(f"/music/api/fleet/ingest/batches/{FLEET_UID}/claim",
                       json={}, headers={"X-CCSync-Token": token},
                       follow_redirects=False)


def test_a_per_editor_token_is_stamped_with_the_editor_it_is_bound_to(env):
    """THE bug: a cce1 token got past login_gate and was then 403'd by the
    music app, which has no way to check it."""
    client, conn = env
    token, _row = dbmod.create_editor_report_token(conn, "editor2",
                                                   created_by="admin")
    conn.commit()
    r = claim(client, token)
    assert r.status_code == 200, r.text
    assert r.json()["fleet_auth"] == "editor:editor2"


def test_the_shared_token_is_stamped_shared(env):
    client, _conn = env
    r = claim(client, SHARED)
    assert r.status_code == 200, r.text
    assert r.json()["fleet_auth"] == "shared"
    # The token itself still travels: an older music checkout that knows
    # nothing about the stamp keeps working off its own comparison.
    assert r.json()["token_seen"] is True


def test_a_revoked_per_editor_token_is_not_stamped(env):
    """Revocation must reach the mount, not just the dashboard's own routes.
    login_gate refuses this one anyway; the stamp must not be the thing that
    would have let it through."""
    client, conn = env
    token, row = dbmod.create_editor_report_token(conn, "editor2",
                                                  created_by="admin")
    dbmod.revoke_editor_report_token(conn, row["token_id"], revoked_by="admin")
    conn.commit()
    r = claim(client, token)
    assert r.status_code == 401


def test_an_inbound_stamp_is_stripped_from_a_browser_request(env):
    """Strip-then-append, never "append if absent": without the strip, an
    editor's own fetch() could hand the fleet routes a credential."""
    client, _conn = env
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "jsmith"))
    r = client.get("/music/api/stats",
                   headers={"X-CCSync-Fleet-Auth": "shared"},
                   follow_redirects=False)
    assert r.status_code == 200, r.text
    assert r.json()["fleet_auth"] is None


def test_an_unverifiable_token_gets_no_stamp(env):
    """A cce1-SHAPED token that is in no database is not a credential, and the
    absence of a stamp is what makes musicweb fall back to its own compare."""
    client, _conn = env
    r = claim(client, "cce1." + "0" * 16 + "." + "9" * 48)
    assert r.status_code == 401
