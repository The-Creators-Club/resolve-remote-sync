"""Admin management of local accounts (WP C, docs/ZERO_TOUCH_PLAN.md §3.3
item 4, 2026-08-17): the local branch of /api/v1/admin/users and its
htmx twins, plus "no NAS credential must not 503 the Users page any more".
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth, db as dbmod, local_users
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "test-secret"
KEY = "ssh-ed25519 QUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUE= jsmith@laptop"


def as_user(client, user):
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, user))
    return client


@pytest.fixture
def env(tmp_path):
    settings = Settings(
        db_path=str(tmp_path / "local_admin.db"),
        session_secret=SECRET,
        admin_users=frozenset({"owen"}),
        auth_method="local",
        # Deliberately NO nas_pw/nas_host: the appliance's default shape.
    )
    app = create_app(settings)
    with TestClient(app) as client:
        yield client


def test_users_page_does_not_503_without_a_nas_credential(env):
    as_user(env, "owen")
    resp = env.get("/api/v1/admin/users")
    assert resp.status_code == 200
    body = resp.json()
    assert body["truenas_configured"] is False
    assert body["auth_method"] == "local"
    assert body["local_users"] == []


def test_non_admin_cannot_manage_local_users(env):
    assert env.post("/api/v1/admin/users", json={"username": "newbie"}).status_code == 401
    as_user(env, "jsmith")
    resp = env.post("/api/v1/admin/users", json={"username": "newbie"})
    assert resp.status_code == 403


def test_create_local_editor_with_explicit_password(env):
    as_user(env, "owen")
    resp = env.post("/api/v1/admin/users", json={
        "username": "newbie", "password": "correct-horse-battery-new",
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert "generated_password" not in body
    assert body["result"]["role"] == "editor"
    assert auth.verify_credentials(env.app.state.settings, "newbie", "correct-horse-battery-new")


def test_create_local_admin_with_generated_password(env):
    as_user(env, "owen")
    resp = env.post("/api/v1/admin/users", json={"username": "newadmin", "role": "admin"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    generated = body["generated_password"]
    assert generated
    assert auth.verify_credentials(env.app.state.settings, "newadmin", generated) is True
    assert auth.is_admin(env.app.state.settings, "newadmin") is True


def test_create_local_user_with_ssh_key(env):
    as_user(env, "owen")
    resp = env.post("/api/v1/admin/users", json={
        "username": "newbie", "password": "correct-horse-battery-new", "ssh_pubkey": KEY,
    })
    assert resp.status_code == 200
    view = resp.json()["view"]
    row = next(u for u in view["local_users"] if u["username"] == "newbie")
    assert len(row["ssh_keys"]) == 1


def test_duplicate_local_user_422(env):
    as_user(env, "owen")
    env.post("/api/v1/admin/users", json={"username": "newbie", "password": "correct-horse-battery-new"})
    resp = env.post("/api/v1/admin/users", json={"username": "newbie", "password": "correct-horse-battery-new"})
    assert resp.status_code == 422


def test_set_password_local_mode(env):
    as_user(env, "owen")
    env.post("/api/v1/admin/users", json={"username": "newbie", "password": "correct-horse-battery-new"})
    resp = env.post("/api/v1/admin/users/newbie/password", json={"password": "correct-horse-battery-2"})
    assert resp.status_code == 200
    assert auth.verify_credentials(env.app.state.settings, "newbie", "correct-horse-battery-2")


def test_set_password_unknown_user_422(env):
    as_user(env, "owen")
    resp = env.post("/api/v1/admin/users/ghost/password", json={"password": "correct-horse-battery-2"})
    assert resp.status_code == 422


def test_disable_and_enable_local_user(env):
    as_user(env, "owen")
    env.post("/api/v1/admin/users", json={"username": "newbie", "password": "correct-horse-battery-new"})
    resp = env.post("/api/v1/admin/users/newbie/disable", json={"disabled": True})
    assert resp.status_code == 200
    assert auth.verify_credentials(env.app.state.settings, "newbie", "correct-horse-battery-new") is False
    resp = env.post("/api/v1/admin/users/newbie/disable", json={"disabled": False})
    assert resp.status_code == 200
    assert auth.verify_credentials(env.app.state.settings, "newbie", "correct-horse-battery-new") is True


def test_add_and_remove_ssh_key(env):
    as_user(env, "owen")
    env.post("/api/v1/admin/users", json={"username": "newbie", "password": "correct-horse-battery-new"})
    resp = env.post("/api/v1/admin/users/newbie/keys", json={"key_text": KEY, "label": "laptop"})
    assert resp.status_code == 200
    fingerprint = resp.json()["key"]["fingerprint"]
    resp = env.delete(f"/api/v1/admin/users/newbie/keys/{fingerprint}")
    assert resp.status_code == 200
    assert resp.json()["removed"] is True


def test_disable_and_keys_are_400_outside_local_mode(tmp_path):
    settings = Settings(
        db_path=str(tmp_path / "smb.db"), session_secret=SECRET,
        admin_users=frozenset({"owen"}), auth_method="smb",
    )
    with TestClient(create_app(settings)) as client:
        as_user(client, "owen")
        assert client.post("/api/v1/admin/users/jsmith/disable",
                           json={"disabled": True}).status_code == 400
        assert client.post("/api/v1/admin/users/jsmith/keys",
                           json={"key_text": KEY}).status_code == 400
        assert client.delete("/api/v1/admin/users/jsmith/keys/SHA256:x").status_code == 400


# ------------------------------------------------------------- htmx partials

def test_users_partial_page_renders_without_500(env):
    as_user(env, "owen")
    resp = env.get("/admin/users")
    assert resp.status_code == 200
    assert b"LOCAL ACCOUNTS" in resp.content


def test_partial_create_local_user_via_htmx(env):
    as_user(env, "owen")
    resp = env.post("/partials/admin/users/create", data={
        "username": "newbie", "role": "editor", "password": "correct-horse-battery-new",
    })
    assert resp.status_code == 200
    assert b"newbie" in resp.content
    assert auth.verify_credentials(env.app.state.settings, "newbie", "correct-horse-battery-new")


def test_partial_disable_and_keys_via_htmx(env):
    as_user(env, "owen")
    env.post("/partials/admin/users/create", data={
        "username": "newbie", "password": "correct-horse-battery-new",
    })
    resp = env.post("/partials/admin/users/disable", data={"username": "newbie", "disabled": "1"})
    assert resp.status_code == 200
    assert auth.verify_credentials(env.app.state.settings, "newbie", "correct-horse-battery-new") is False

    resp = env.post("/partials/admin/users/keys/add", data={"username": "newbie", "key_text": KEY})
    assert resp.status_code == 200
    conn = dbmod.connect(env.app.state.settings.db_path)
    fingerprint = local_users.keys_for(conn, "newbie")[0]["fingerprint"]
    conn.close()
    resp = env.post("/partials/admin/users/keys/remove",
                    data={"username": "newbie", "fingerprint": fingerprint})
    assert resp.status_code == 200
