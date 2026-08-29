"""DASH_AUTH_METHOD=local end to end (WP C, docs/ZERO_TOUCH_PLAN.md §3.3,
2026-08-17): the /login and /api/v1/verify paths dispatching to
local_users.py instead of the SMB probe, and auth.is_admin reading the local
`users` table's role column.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth, db as dbmod, local_users
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

STRONG = "kX9-quiet-harbour-42-zephyr"


@pytest.fixture(autouse=True)
def _strict(monkeypatch):
    """Every other test file in this suite runs with DASH_DEV_INSECURE=1
    (conftest.py); this one runs strict, same posture as test_oidc.py, so the
    real verify_credentials/is_admin dispatch is exercised end to end rather
    than through app.state.credential_verifier."""
    monkeypatch.delenv("DASH_DEV_INSECURE", raising=False)
    yield


def _settings(tmp_path, **kwargs) -> Settings:
    base = dict(db_path=str(tmp_path / "local.db"), session_secret=STRONG,
               auth_method="local")
    base.update(kwargs)
    return Settings(**base)


def _seed_users(settings) -> None:
    conn = dbmod.connect(settings.db_path)
    dbmod.migrate(conn)
    local_users.create_user(conn, "owen", "correct-horse-battery-owen", "admin")
    local_users.create_user(conn, "jsmith", "correct-horse-battery-jsmi", "editor")
    conn.commit()
    conn.close()


def test_verify_credentials_dispatches_to_local(tmp_path):
    settings = _settings(tmp_path)
    _seed_users(settings)
    assert auth.verify_credentials(settings, "jsmith", "correct-horse-battery-jsmi") is True
    assert auth.verify_credentials(settings, "JSmith", "correct-horse-battery-jsmi") is True
    assert auth.verify_credentials(settings, "jsmith", "wrong-password-here") is False
    assert auth.verify_credentials(settings, "ghost", "whatever-password") is False


def test_is_admin_reads_local_role(tmp_path):
    settings = _settings(tmp_path)
    _seed_users(settings)
    assert auth.is_admin(settings, "owen") is True
    assert auth.is_admin(settings, "jsmith") is False
    assert auth.is_admin(settings, "ghost") is False


def test_is_admin_break_glass_via_dash_admin_users(tmp_path):
    """DASH_ADMIN_USERS is honoured ADDITIVELY in local mode -- even for a
    name with no local account at all, which is exactly the break-glass
    shape (ZERO_TOUCH_PLAN.md §3.3)."""
    settings = _settings(tmp_path, admin_users=frozenset({"breakglass"}))
    _seed_users(settings)
    assert auth.is_admin(settings, "breakglass") is True


def test_login_flow_local_mode(tmp_path):
    settings = _settings(tmp_path)
    _seed_users(settings)
    with TestClient(create_app(settings)) as c:
        bad = c.post("/api/v1/login", json={"username": "jsmith", "password": "nope"})
        assert bad.status_code == 401
        good = c.post("/api/v1/login",
                      json={"username": "jsmith", "password": "correct-horse-battery-jsmi"})
        assert good.status_code == 200
        body = good.json()
        assert body.pop("csrf")          # see test_auth's login flow
        assert body == {"ok": True, "user": "jsmith", "is_admin": False}
        assert auth.COOKIE_NAME in good.cookies
        me = c.get("/api/v1/me").json()
        assert me == {"user": "jsmith", "is_admin": False}


def test_login_flow_admin_role(tmp_path):
    settings = _settings(tmp_path)
    _seed_users(settings)
    with TestClient(create_app(settings)) as c:
        resp = c.post("/api/v1/login",
                      json={"username": "owen", "password": "correct-horse-battery-owen"})
        assert resp.status_code == 200
        assert resp.json()["is_admin"] is True


def test_disabled_local_account_cannot_log_in(tmp_path):
    settings = _settings(tmp_path)
    _seed_users(settings)
    conn = dbmod.connect(settings.db_path)
    local_users.disable_user(conn, "jsmith", True)
    conn.commit()
    conn.close()
    with TestClient(create_app(settings)) as c:
        resp = c.post("/api/v1/login",
                      json={"username": "jsmith", "password": "correct-horse-battery-jsmi"})
        assert resp.status_code == 401


def test_verify_endpoint_local_mode_role(tmp_path):
    settings = _settings(tmp_path)
    _seed_users(settings)
    with TestClient(create_app(settings)) as c:
        resp = c.post("/api/v1/verify", json={
            "username": "owen", "password": "correct-horse-battery-owen",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["role"] == "base"   # admin -> "base", same mapping as smb/oidc
        assert "token" in body

        resp2 = c.post("/api/v1/verify", json={
            "username": "jsmith", "password": "correct-horse-battery-jsmi",
        })
        assert resp2.json()["role"] == "editor"


def test_check_boot_secrets_local_mode_needs_session_secret(tmp_path):
    settings = Settings(db_path=str(tmp_path / "boot.db"), auth_method="local", session_secret="")
    problems = auth.check_boot_secrets(settings)
    assert any("DASH_SESSION_SECRET" in p for p in problems)


def test_check_boot_secrets_local_mode_ok_with_strong_secret(tmp_path):
    settings = _settings(tmp_path)
    assert auth.check_boot_secrets(settings) == []
