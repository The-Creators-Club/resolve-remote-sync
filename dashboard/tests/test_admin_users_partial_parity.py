"""The Users page's htmx buttons must not be a softer door than the JSON
routes (dash-admin-5, 2026-08-21).

`POST /partials/admin/users/disable` called `local_users.disable_user` bare:
no last-enabled-admin guard, no self-disable guard, and no credential purge --
while `POST /api/v1/admin/users/{u}/disable` has all three. A disabled row
cannot sign in and is not an admin (`is_local_admin`), so the button could
take admin away from an appliance that has no shell to put it back with, and
left the disabled account's sessions and report token working either way.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth, db as dbmod
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "test-secret"


def as_user(client, user):
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, user))
    return client


@pytest.fixture
def env(tmp_path):
    settings = Settings(
        db_path=str(tmp_path / "parity.db"),
        session_secret=SECRET,
        admin_users=frozenset({"owen"}),
        auth_method="local",
    )
    app = create_app(settings)
    with TestClient(app) as client:
        yield client


def _make(client, username, role="editor", password="correct-horse-battery-new"):
    resp = client.post("/api/v1/admin/users",
                       json={"username": username, "role": role, "password": password})
    assert resp.status_code == 200, resp.text


def test_the_button_refuses_to_disable_the_last_enabled_admin(env):
    as_user(env, "owen")
    _make(env, "boss", role="admin")
    resp = env.post("/partials/admin/users/disable",
                    data={"username": "boss", "disabled": "1"})
    # htmx swaps the response either way, so a refusal is a BANNER, not a 4xx.
    assert resp.status_code == 200
    assert "last enabled admin" in resp.text
    assert auth.verify_credentials(env.app.state.settings, "boss",
                                   "correct-horse-battery-new") is True


def test_the_button_refuses_to_disable_your_own_account(env):
    as_user(env, "owen")
    _make(env, "boss", role="admin")
    _make(env, "boss2", role="admin")
    as_user(env, "boss")
    resp = env.post("/partials/admin/users/disable",
                    data={"username": "boss", "disabled": "1"})
    assert resp.status_code == 200
    assert "signed in as" in resp.text


def test_the_button_revokes_what_can_still_act_as_the_account(env):
    as_user(env, "owen")
    _make(env, "newbie")
    settings = env.app.state.settings
    conn = dbmod.connect(settings.db_path)
    token, _row = dbmod.create_editor_report_token(conn, "newbie", created_by="admin")
    conn.commit()
    assert dbmod.verify_editor_report_token(conn, token) == "newbie"
    conn.close()

    resp = env.post("/partials/admin/users/disable",
                    data={"username": "newbie", "disabled": "1"})
    assert resp.status_code == 200
    conn = dbmod.connect(settings.db_path)
    assert dbmod.verify_editor_report_token(conn, token) is None
    conn.close()
