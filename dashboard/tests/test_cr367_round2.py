"""CR-367 round 2 (2026-10-07, package A3a): a deleted person cannot sign in
to the BROWSER either (GL-15 / bug-dash-auth-2). Suspension stays out of
browser sign-in (DCORE-4)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth, oidc
from ccsync_dashboard import db as dbmod
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

from fake_idp import FakeIdP
from test_oidc import STRONG, _app, _sign_in

SECRET = "test-secret-key-for-cr367-r2"


def _settings(tmp_path, **kw):
    return Settings(db_path=str(tmp_path / "r2.db"), session_secret=SECRET,
                    report_token="fleet-report-token-r2",
                    admin_users=frozenset({"owen"}), **kw)


def _tombstone(settings, name="jsmith", **kw):
    conn = dbmod.connect(settings.db_path)
    dbmod.migrate(conn)
    dbmod.revoke_identity(conn, name, by="admin:owen", removed=True, **kw)
    conn.commit()
    conn.close()


def test_removal_check_exempts_config_admins_and_fails_open(tmp_path):
    settings = _settings(tmp_path)
    _tombstone(settings, "jsmith")
    _tombstone(settings, "owen")
    assert auth.removed_signin_refused(settings, "jsmith") is True
    assert auth.removed_signin_refused(settings, "owen") is False   # operator config
    assert auth.removed_signin_refused(settings, "ruskin") is False
    broken = Settings(db_path=str(tmp_path / "no" / "such" / "dir" / "x.db"),
                      session_secret=SECRET)
    assert auth.removed_signin_refused(broken, "jsmith") is False


def test_a_removed_person_cannot_sign_in_on_the_json_route(tmp_path):
    settings = _settings(tmp_path)
    app = create_app(settings)
    app.state.credential_verifier = lambda s, u, p: True
    with TestClient(app) as client:
        _tombstone(settings, "jsmith")
        refused = client.post("/api/v1/login", json={"username": "jsmith", "password": "pw"})
        assert refused.status_code == 401
        assert refused.json()["detail"] == "bad username or password"
        assert auth.COOKIE_NAME not in client.cookies
        ok = client.post("/api/v1/login", json={"username": "ruskin", "password": "pw"})
        assert ok.status_code == 200


def test_a_removed_person_cannot_sign_in_on_the_browser_form(tmp_path):
    settings = _settings(tmp_path)
    app = create_app(settings)
    app.state.credential_verifier = lambda s, u, p: True
    with TestClient(app) as client:
        _tombstone(settings, "jsmith")
        resp = client.post("/login", data={"username": "jsmith", "password": "pw"},
                           follow_redirects=False)
        assert resp.status_code != 303
        assert auth.COOKIE_NAME not in client.cookies
        ok = client.post("/login", data={"username": "ruskin", "password": "pw"},
                         follow_redirects=False)
        assert ok.status_code == 303 and auth.COOKIE_NAME in client.cookies


def test_a_suspended_person_can_still_sign_in(tmp_path):
    """DCORE-4: suspension is independent of sign-in."""
    settings = _settings(tmp_path)
    app = create_app(settings)
    app.state.credential_verifier = lambda s, u, p: True
    with TestClient(app) as client:
        conn = dbmod.connect(settings.db_path)
        dbmod.record_known_editor(conn, "jsmith", "admin")
        dbmod.suspend_editor(conn, "jsmith", by="owen")
        conn.commit()
        conn.close()
        assert client.post("/api/v1/login", json={
            "username": "jsmith", "password": "pw"}).status_code == 200


@pytest.fixture
def idp(monkeypatch):
    monkeypatch.delenv("DASH_DEV_INSECURE", raising=False)
    fake = FakeIdP().start()
    fake.claims = {"preferred_username": "jsmith", "groups": ["editors"]}
    try:
        yield fake
    finally:
        fake.stop()


def test_a_removed_person_in_the_allowed_group_cannot_sign_in_through_oidc(tmp_path, idp):
    settings = Settings(
        db_path=str(tmp_path / "oidc.db"), session_secret=STRONG,
        admin_users=frozenset({"owen"}), auth_method="oidc",
        oidc_issuer=idp.base_url, oidc_client_id="ccsync-dashboard",
        oidc_client_secret="s" * 32, oidc_allowed_groups=frozenset({"editors"}))
    app = _app(settings)
    with TestClient(app) as client:
        resp, _ = _sign_in(client, idp)
        assert resp.status_code == 303                      # a member signs in
        client.cookies.clear()
        _tombstone(settings, "jsmith")
        resp, _ = _sign_in(client, idp)
        assert resp.status_code == 403
        assert "removed" in resp.json()["detail"]
        assert auth.COOKIE_NAME not in client.cookies
