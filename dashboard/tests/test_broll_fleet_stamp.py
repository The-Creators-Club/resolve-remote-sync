"""What the b-roll mount tells broll/web about `X-CCSync-Token` (CR-55).

2026-08-21, CR-67 item 2. `broll/web/app/fleet_auth.py` compared that header
against the shared DASH_REPORT_TOKEN and nothing else, so an editor whose
companion had adopted the per-editor `cce1.<id>.<secret>` token an admin minted
for them (preferred since 2026-08-17) got past login_gate's fleet carve-out and
was then answered 403 by the b-roll app itself: their dropped clips never left
`queued`. Only this side can verify such a token -- it means reading the
dashboard's database, which the separately deployed b-roll tree cannot see -- so
BrollGate resolves it and stamps `X-CCSync-Fleet-Auth: shared|editor:<name>`.

Music got this on the same day (test_music_fleet_stamp.py); this is its mirror,
and the sub-app's half is broll/web/tests/test_fleet_credentials.py.

The fake sub-app here echoes the headers it was handed, because what is under
test is which of them arrive, not what broll/web does with them.
"""
from __future__ import annotations

import sqlite3
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
INGEST = "9f3c1ab27d4e5608bc19af730d25e8641c07b9a3f2de5061"
FLEET_UID = "0123456789abcdef0123456789abcdef"


def _build_fake_broll(tmp_path) -> dict[str, types.ModuleType]:
    """The modules ccsync_dashboard.broll imports, plus `app.fleet_auth`.

    That last one is new here: the mount now calls its `trust_gate_stamp` so
    the sub-app knows a gate is stripping forged copies of the header. A tree
    WITHOUT it must still mount (an older deployed checkout), which
    test_broll_mount.py's fake covers by not having one.
    """
    pkg = types.ModuleType("app")
    pkg.__path__ = []

    config = types.ModuleType("app.config")
    root = tmp_path / "brolldata"
    config.get_data_root = lambda: root
    config.get_db_path = lambda: root / "broll.db"
    config.get_proxies_dir = lambda: root / "proxies"
    config.get_sprites_dir = lambda: root / "sprites"
    config.get_posters_dir = lambda: root / "posters"
    config.get_sheets_dir = lambda: root / "sheets"

    db = types.ModuleType("app.db")

    def ensure_schema(path) -> None:
        conn = sqlite3.connect(str(path))
        conn.execute("CREATE TABLE IF NOT EXISTS videos (share TEXT, rel_path TEXT)")
        conn.commit()
        conn.close()

    db.ensure_schema = ensure_schema

    fleet_auth = types.ModuleType("app.fleet_auth")
    fleet_auth.trusted = []
    fleet_auth.trust_gate_stamp = lambda on=True: fleet_auth.trusted.append(on)

    main = types.ModuleType("app.main")
    broll_app = FastAPI(title="B-Roll Platform (fake)")

    @broll_app.post("/api/fleet/ingest/batches/{uid}/claim")
    def fleet_claim(uid: str,
                    x_ccsync_fleet_auth: str | None = Header(default=None),
                    x_ccsync_token: str | None = Header(default=None)) -> dict:
        return {"claimed": uid, "fleet_auth": x_ccsync_fleet_auth,
                "token_seen": bool(x_ccsync_token)}

    @broll_app.get("/api/search")
    def search(x_ccsync_fleet_auth: str | None = Header(default=None)) -> dict:
        return {"fleet_auth": x_ccsync_fleet_auth}

    main.app = broll_app
    pkg.config, pkg.db, pkg.main, pkg.fleet_auth = config, db, main, fleet_auth
    return {"app": pkg, "app.config": config, "app.db": db, "app.main": main,
            "app.fleet_auth": fleet_auth}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("BROLL_DATA_ROOT", str(tmp_path / "brolldata"))
    monkeypatch.setenv("BROLL_INGEST_TOKEN", INGEST)
    modules = _build_fake_broll(tmp_path)
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    settings = Settings(db_path=str(tmp_path / "d.db"), session_secret=SECRET,
                        report_token=SHARED, broll_enabled=True,
                        broll_ingest_token=INGEST,
                        admin_users=frozenset({"admin"}))
    app = create_app(settings)
    with TestClient(app) as client:
        conn = dbmod.connect(settings.db_path)
        yield client, conn, modules["app.fleet_auth"]
        conn.close()


def claim(client, token):
    return client.post(f"/broll/api/fleet/ingest/batches/{FLEET_UID}/claim",
                       json={}, headers={"X-CCSync-Token": token},
                       follow_redirects=False)


def test_the_mount_installs_the_stamp_trust(env):
    """The sub-app believes the header only because a mount said so, and only a
    mount strips a forged inbound copy."""
    _client, _conn, fleet_auth = env
    assert fleet_auth.trusted == [True]


def test_a_per_editor_token_is_stamped_with_the_editor_it_is_bound_to(env):
    """THE bug: a cce1 token got past login_gate's fleet carve-out and was then
    403'd by the b-roll app, which has no way to check it."""
    client, conn, _fa = env
    token, _row = dbmod.create_editor_report_token(conn, "editor2",
                                                   created_by="admin")
    conn.commit()
    r = claim(client, token)
    assert r.status_code == 200, r.text
    assert r.json()["fleet_auth"] == "editor:editor2"


def test_the_shared_token_is_stamped_shared(env):
    client, _conn, _fa = env
    r = claim(client, SHARED)
    assert r.status_code == 200, r.text
    assert r.json()["fleet_auth"] == "shared"
    # The token itself still travels: an older b-roll checkout that knows
    # nothing about the stamp keeps working off its own comparison.
    assert r.json()["token_seen"] is True


def test_a_revoked_per_editor_token_is_not_stamped(env):
    """Revocation must reach the mount, not just the dashboard's own routes.
    login_gate refuses this one anyway; the stamp must not be the thing that
    would have let it through."""
    client, conn, _fa = env
    token, row = dbmod.create_editor_report_token(conn, "editor2",
                                                  created_by="admin")
    dbmod.revoke_editor_report_token(conn, row["token_id"], revoked_by="admin")
    conn.commit()
    assert claim(client, token).status_code == 401


def test_an_unverifiable_token_gets_no_stamp(env):
    """A cce1-SHAPED token that is in no database is not a credential, and the
    absence of a stamp is what makes broll/web fall back to its own compare."""
    client, _conn, _fa = env
    assert claim(client, "cce1." + "0" * 16 + "." + "9" * 48).status_code == 401


def test_an_inbound_stamp_is_stripped_from_a_browser_request(env):
    """Strip-then-append, never "append if absent": without the strip, an
    editor's own fetch() could hand the fleet routes a credential."""
    client, _conn, _fa = env
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "jsmith"))
    r = client.get("/broll/api/search",
                   headers={"X-CCSync-Fleet-Auth": "editor:someone-else"},
                   follow_redirects=False)
    assert r.status_code == 200, r.text
    assert r.json()["fleet_auth"] is None
