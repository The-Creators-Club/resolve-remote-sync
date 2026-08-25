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


# ------------------------------------------------------------------- delete
#
# Deleting an account is the one Users-page action that cannot be undone, so
# the guards are tested as hard as the happy path: the two lockouts it must
# refuse, and the credentials that would otherwise outlive the row.

def _make(client, username, role="editor", password="correct-horse-battery-new"):
    resp = client.post("/api/v1/admin/users",
                       json={"username": username, "role": role, "password": password})
    assert resp.status_code == 200, resp.text


def test_delete_local_user_removes_account_and_keys(env):
    as_user(env, "owen")
    _make(env, "newbie")
    env.post("/api/v1/admin/users/newbie/keys", json={"key_text": KEY, "label": "laptop"})

    resp = env.delete("/api/v1/admin/users/newbie")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["deleted"]["ssh_keys_removed"] == 1
    assert body["view"]["local_users"] == []
    assert auth.verify_credentials(env.app.state.settings, "newbie",
                                   "correct-horse-battery-new") is False

    conn = dbmod.connect(env.app.state.settings.db_path)
    assert local_users.get_user(conn, "newbie") is None
    # The sftp sidecar serves keys straight out of this table (internal_sftp.py):
    # an orphan row would keep authenticating an account that no longer exists.
    assert local_users.keys_for(conn, "newbie") == []
    conn.close()


def test_delete_revokes_sessions_and_report_tokens(env):
    as_user(env, "owen")
    _make(env, "newbie")
    conn = dbmod.connect(env.app.state.settings.db_path)
    dbmod.create_editor_report_token(conn, "newbie", created_by="owen")
    conn.commit()
    conn.close()
    env.app.state.session_store.create("sid-for-newbie", "newbie", client="laptop")

    resp = env.delete("/api/v1/admin/users/newbie")
    assert resp.status_code == 200, resp.text
    assert resp.json()["deleted"]["sessions_revoked"] == 1
    assert resp.json()["deleted"]["report_tokens_revoked"] == 1
    assert env.app.state.session_store.list_for_user("newbie") == []
    conn = dbmod.connect(env.app.state.settings.db_path)
    assert dbmod.fetch_editor_report_tokens(conn, editor="newbie") == []
    conn.close()


def test_delete_takes_the_fleet_records_with_it(env):
    """Until CR-76 (2026-08-24) delete kept the fleet rows, on the theory
    that a grid row vanishing turns a known editor into an unmapped stranger
    (B16). It now removes the person everywhere: the stranger problem is
    solved by taking their Syncthing device out first (test_admin_delete.py),
    so a known_editors row left behind would only keep a deleted person on
    the fleet page. DISABLE is the button that keeps everything."""
    as_user(env, "owen")
    _make(env, "newbie")
    conn = dbmod.connect(env.app.state.settings.db_path)
    assert "newbie" in dbmod.known_editor_usernames(conn)
    conn.close()

    assert env.delete("/api/v1/admin/users/newbie").status_code == 200

    conn = dbmod.connect(env.app.state.settings.db_path)
    assert "newbie" not in dbmod.known_editor_usernames(conn)
    conn.close()


def test_cannot_delete_the_account_you_are_signed_in_as(env):
    as_user(env, "owen")
    _make(env, "owen2", role="admin")
    as_user(env, "owen2")
    resp = env.delete("/api/v1/admin/users/owen2")
    assert resp.status_code == 409
    assert "signed in as" in resp.json()["detail"]
    assert auth.is_admin(env.app.state.settings, "owen2") is True


def test_cannot_delete_the_last_enabled_admin(env):
    as_user(env, "owen")  # break-glass DASH_ADMIN_USERS admin, not a local row
    _make(env, "boss", role="admin")
    resp = env.delete("/api/v1/admin/users/boss")
    assert resp.status_code == 409
    assert "last enabled admin" in resp.json()["detail"]

    # A second admin makes the first deletable again.
    _make(env, "boss2", role="admin")
    assert env.delete("/api/v1/admin/users/boss").status_code == 200


def test_a_disabled_admin_is_not_the_last_enabled_admin(env):
    as_user(env, "owen")
    _make(env, "boss", role="admin")
    # A second admin first: since dash-admin-5 (2026-08-21) DISABLE refuses
    # the last enabled admin exactly as DELETE does, so making `boss` the
    # only one would test the guard rather than the rule below it.
    _make(env, "boss2", role="admin")
    assert env.post("/api/v1/admin/users/boss/disable", json={"disabled": True}).status_code == 200
    assert env.delete("/api/v1/admin/users/boss").status_code == 200


def test_delete_unknown_user_is_404(env):
    as_user(env, "owen")
    assert env.delete("/api/v1/admin/users/nobody").status_code == 404


def test_delete_requires_admin(env):
    as_user(env, "owen")
    _make(env, "newbie")
    env.cookies.clear()
    assert env.delete("/api/v1/admin/users/newbie").status_code == 401
    as_user(env, "jsmith")
    assert env.delete("/api/v1/admin/users/newbie").status_code == 403


def test_delete_outside_local_mode_is_404_for_a_stranger_and_works_for_a_known_editor(tmp_path):
    """Delete is no longer a local-mode carve-out (CR-76): with no NAS
    configured there is no account to remove, but a name the fleet knows
    (a report, a tick, a device) is still deletable -- that is the only way
    its records get cleaned up. A name nobody has heard of is a 404."""
    settings = Settings(
        db_path=str(tmp_path / "smb2.db"), session_secret=SECRET,
        admin_users=frozenset({"owen"}), auth_method="smb",
    )
    with TestClient(create_app(settings)) as client:
        as_user(client, "owen")
        assert client.delete("/api/v1/admin/users/jsmith").status_code == 404
        conn = dbmod.connect(settings.db_path)
        dbmod.record_known_editor(conn, "jsmith", "admin")
        conn.commit()
        conn.close()
        resp = client.delete("/api/v1/admin/users/jsmith")
        assert resp.status_code == 200, resp.text
        assert resp.json()["deleted"]["machines"] == []


def test_partial_delete_via_htmx(env):
    as_user(env, "owen")
    env.post("/partials/admin/users/create", data={
        "username": "newbie", "password": "correct-horse-battery-new",
    })
    resp = env.post("/partials/admin/users/delete", data={"username": "newbie"})
    assert resp.status_code == 200
    assert b"newbie" not in resp.content
    assert auth.verify_credentials(env.app.state.settings, "newbie",
                                   "correct-horse-battery-new") is False


def test_partial_delete_refusal_renders_a_banner_not_an_error(env):
    as_user(env, "owen")
    env.post("/partials/admin/users/create", data={
        "username": "boss", "role": "admin", "password": "correct-horse-battery-new",
    })
    resp = env.post("/partials/admin/users/delete", data={"username": "boss"})
    assert resp.status_code == 200
    assert b"last enabled admin" in resp.content
    assert auth.is_admin(env.app.state.settings, "boss") is True
