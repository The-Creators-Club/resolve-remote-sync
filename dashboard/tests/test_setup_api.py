"""First-admin bootstrap (WP C, docs/ZERO_TOUCH_PLAN.md §3.3 step 2 / §3.5
step 2, 2026-08-17): setup_api.py's two open routes, and the "no users yet"
gate that closes the window the instant one exists.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth, db as dbmod, local_users
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

STRONG = "kX9-quiet-harbour-42-zephyr"


def _app(tmp_path, **kwargs):
    base = dict(db_path=str(tmp_path / "setup.db"), session_secret=STRONG,
               auth_method="local")
    base.update(kwargs)
    return create_app(Settings(**base))


def test_status_reports_no_users_yet(tmp_path):
    with TestClient(_app(tmp_path)) as c:
        resp = c.get("/api/v1/setup/status")
        assert resp.status_code == 200
        assert resp.json() == {"auth_method": "local", "users_exist": False}


def test_status_open_without_a_session(tmp_path):
    """Same terms as /api/v1/health -- app.py's _OPEN_EXACT, no cookie needed."""
    with TestClient(_app(tmp_path)) as c:
        resp = c.get("/api/v1/setup/status")
        assert resp.status_code == 200


def test_status_non_local_reports_users_exist_true(tmp_path):
    """smb/oidc sites never show the "create your admin" wizard step --
    DASH_ADMIN_USERS is the answer there, not this table."""
    with TestClient(_app(tmp_path, auth_method="smb")) as c:
        resp = c.get("/api/v1/setup/status")
        assert resp.json() == {"auth_method": "smb", "users_exist": True}


def test_create_first_admin_and_it_is_logged_in(tmp_path):
    with TestClient(_app(tmp_path)) as c:
        resp = c.post("/api/v1/setup/admin",
                      json={"username": "Owen", "password": "correct-horse-battery"})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body == {"ok": True, "user": "owen", "is_admin": True}
        # Same cookie path as /login: the wizard continues logged in.
        assert auth.COOKIE_NAME in resp.cookies
        me = c.get("/api/v1/me").json()
        assert me == {"user": "owen", "is_admin": True}

        status = c.get("/api/v1/setup/status").json()
        assert status["users_exist"] is True


def test_second_admin_creation_refused_409(tmp_path):
    with TestClient(_app(tmp_path)) as c:
        first = c.post("/api/v1/setup/admin",
                       json={"username": "owen", "password": "correct-horse-battery"})
        assert first.status_code == 200
        second = c.post("/api/v1/setup/admin",
                        json={"username": "someoneelse", "password": "correct-horse-battery"})
        assert second.status_code == 409


def test_refused_when_a_local_account_already_exists_outside_the_wizard(tmp_path):
    settings = Settings(db_path=str(tmp_path / "pre.db"), session_secret=STRONG,
                        auth_method="local")
    conn = dbmod.connect(settings.db_path)
    dbmod.migrate(conn)
    local_users.create_user(conn, "owen", "correct-horse-battery", "admin")
    conn.commit()
    conn.close()
    with TestClient(create_app(settings)) as c:
        resp = c.post("/api/v1/setup/admin",
                      json={"username": "second", "password": "correct-horse-battery"})
        assert resp.status_code == 409


def test_refused_when_not_local_auth_method(tmp_path):
    with TestClient(_app(tmp_path, auth_method="smb")) as c:
        resp = c.post("/api/v1/setup/admin",
                      json={"username": "owen", "password": "correct-horse-battery"})
        assert resp.status_code == 403


def test_weak_password_refused(tmp_path):
    with TestClient(_app(tmp_path)) as c:
        resp = c.post("/api/v1/setup/admin", json={"username": "owen", "password": "short"})
        assert resp.status_code == 422
        assert local_users_missing(tmp_path)


def local_users_missing(tmp_path) -> bool:
    conn = dbmod.connect(tmp_path / "setup.db")
    try:
        return local_users.any_users_exist(conn) is False
    finally:
        conn.close()


def test_bad_username_refused(tmp_path):
    with TestClient(_app(tmp_path)) as c:
        resp = c.post("/api/v1/setup/admin",
                      json={"username": "Not A Username", "password": "correct-horse-battery"})
        assert resp.status_code == 422
