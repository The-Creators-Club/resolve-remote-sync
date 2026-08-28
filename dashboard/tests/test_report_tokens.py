"""Per-editor fleet report tokens (COMMERCIAL_READINESS.md item 15, 2026-08-17).

The fleet authenticated with ONE shared DASH_REPORT_TOKEN: not revocable for a
single editor, held by everyone including anyone who has left, and one leak
away from every machine. These pin the replacement:

  * the token is stored HASHED and shown once,
  * it BINDS -- a token minted for one editor cannot report or read selections
    as another,
  * the shared token still works (nothing in the field has been migrated) and
    DASH_SHARED_REPORT_TOKEN_ENABLED=0 retires it,
  * the boot log says how much of the fleet is still on the shared one, which
    is the only way an operator knows when it is safe to flip that switch.
"""
from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import app as appmod
from ccsync_dashboard import auth
from ccsync_dashboard import db as dbmod
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "s"
SHARED = "sekrit"


def payload(editor="JSmith", machine="EDIT-PC"):
    return {
        "editor_name": editor,
        "machine": machine,
        "companion_version": "0.1.0",
        "reported_at": "2026-07-24T10:00:00+00:00",
        "lanes": [
            {"name": "lane_a_video_up", "state": "idle", "queued": 0, "transferring": 0,
             "last_error": None, "last_sync": None, "detail": None},
        ],
    }


def headers(token, editor="jsmith"):
    return {"X-CCSync-Token": token,
            "X-CCSync-Identity": auth.make_identity_token(SECRET, editor)}


def make_settings(tmp_path, name="dash.db", **kw):
    kw.setdefault("report_token", SHARED)
    return Settings(db_path=str(tmp_path / name), session_secret=SECRET,
                    admin_users=frozenset({"admin"}), **kw)


@pytest.fixture
def env(tmp_path):
    settings = make_settings(tmp_path)
    app = create_app(settings)
    with TestClient(app) as client:
        conn = dbmod.connect(settings.db_path)
        yield client, conn
        conn.close()


def mint(conn, editor="jsmith", label=""):
    token, row = dbmod.create_editor_report_token(conn, editor, created_by="admin",
                                                  label=label)
    conn.commit()
    return token, row


# ------------------------------------------------------------------ storage

def test_the_secret_is_never_stored(env):
    _client, conn = env
    token, row = mint(conn)
    stored = conn.execute("SELECT * FROM editor_report_tokens WHERE token_id = ?",
                          (row["token_id"],)).fetchone()
    secret = token.rsplit(".", 1)[1]
    assert secret not in dict(stored).values()
    assert stored["token_hash"] != secret
    # ...and nothing can hand it back: the listing is metadata only.
    listed = dbmod.fetch_editor_report_tokens(conn)
    assert secret not in repr(listed)


def test_verify_round_trip_and_revocation(env):
    _client, conn = env
    token, row = mint(conn, "jsmith")
    assert dbmod.verify_editor_report_token(conn, token) == "jsmith"
    assert dbmod.revoke_editor_report_token(conn, row["token_id"], revoked_by="admin")
    conn.commit()
    assert dbmod.verify_editor_report_token(conn, token) is None
    # Revoking twice is not an error the caller can distinguish a token by.
    assert not dbmod.revoke_editor_report_token(conn, row["token_id"], revoked_by="admin")


@pytest.mark.parametrize("bad", [
    "", "sekrit", "cce1.short.deadbeef", "cce1.0123456789abcdef.nothex",
    "cce1.0123456789abcdef." + "a" * 47, "CCE1.0123456789ABCDEF." + "a" * 48,
])
def test_garbage_is_never_a_valid_token(env, bad):
    _client, conn = env
    assert dbmod.verify_editor_report_token(conn, bad) is None


def test_a_tampered_secret_does_not_verify(env):
    _client, conn = env
    token, _row = mint(conn)
    head, secret = token.rsplit(".", 1)
    forged = f"{head}.{'0' * len(secret)}"
    assert dbmod.verify_editor_report_token(conn, forged) is None


# ------------------------------------------------------------------- /report

def test_report_accepts_a_per_editor_token(env):
    client, conn = env
    token, _row = mint(conn, "jsmith")
    r = client.post("/api/v1/report", json=payload(), headers=headers(token))
    assert r.status_code == 200
    assert conn.execute(
        "SELECT auth_kind FROM report_auth WHERE editor_username='jsmith'"
    ).fetchone()["auth_kind"] == "editor"


def test_a_per_editor_token_cannot_report_as_somebody_else(env):
    """The whole point: the shared token proves only "somebody in this fleet"."""
    client, conn = env
    token, _row = mint(conn, "jsmith")
    r = client.post("/api/v1/report", json=payload(editor="editor2"),
                    headers=headers(token, editor="editor2"))
    assert r.status_code == 401
    assert "different editor" in r.json()["detail"]


def test_a_revoked_token_stops_working_immediately(env):
    client, conn = env
    token, row = mint(conn, "jsmith")
    assert client.post("/api/v1/report", json=payload(),
                       headers=headers(token)).status_code == 200
    dbmod.revoke_editor_report_token(conn, row["token_id"], revoked_by="admin")
    conn.commit()
    assert client.post("/api/v1/report", json=payload(),
                       headers=headers(token)).status_code == 401


def test_the_shared_token_still_works_and_is_recorded_as_shared(env):
    client, conn = env
    assert client.post("/api/v1/report", json=payload(),
                       headers=headers(SHARED)).status_code == 200
    assert conn.execute(
        "SELECT auth_kind FROM report_auth WHERE editor_username='jsmith'"
    ).fetchone()["auth_kind"] == "shared"


def test_disabling_the_shared_token_leaves_per_editor_tokens_working(tmp_path):
    settings = make_settings(tmp_path, shared_report_token_enabled=False)
    app = create_app(settings)
    with TestClient(app) as client:
        conn = dbmod.connect(settings.db_path)
        token, _row = mint(conn, "jsmith")
        assert client.post("/api/v1/report", json=payload(),
                           headers=headers(SHARED)).status_code == 401
        assert client.post("/api/v1/report", json=payload(),
                           headers=headers(token)).status_code == 200
        conn.close()


def test_the_pre_body_gate_refuses_a_bogus_per_editor_token(env):
    """app.py's gate checks credentials BEFORE reading the body (B15), and a
    per-editor-SHAPED token must not be a way past it."""
    client, _conn = env
    bogus = "cce1." + "0" * 16 + "." + "0" * 48
    r = client.post("/api/v1/report", json=payload(), headers=headers(bogus))
    assert r.status_code == 401


# --------------------------------------------------------------- selections

def test_selection_read_binds_to_the_token_s_editor(env):
    client, conn = env
    token, _row = mint(conn, "jsmith")
    ok = client.get("/api/v1/selection/jsmith",
                    headers={"X-CCSync-Token": token})
    assert ok.status_code == 200
    # No identity header needed -- the token IS the identity -- but it cannot
    # be pointed at another editor.
    other = client.get("/api/v1/selection/editor2",
                       headers={"X-CCSync-Token": token})
    assert other.status_code == 401


# ------------------------------------------------------------- admin routes

def admin_client(client):
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "admin"))
    return client


def test_admin_mints_lists_and_revokes(env):
    client, conn = env
    admin_client(client)

    created = client.post("/api/v1/admin/report-tokens",
                          json={"username": "jsmith", "label": "laptop"})
    assert created.status_code == 200
    token = created.json()["token"]
    assert dbmod.verify_editor_report_token(conn, token) == "jsmith"

    listed = client.get("/api/v1/admin/report-tokens").json()
    assert [t["editor_username"] for t in listed["tokens"]] == ["jsmith"]
    # The secret is shown ONCE. It is not in the listing.
    assert token.rsplit(".", 1)[1] not in repr(listed)

    token_id = created.json()["token_row"]["token_id"]
    assert client.delete(f"/api/v1/admin/report-tokens/{token_id}").status_code == 200
    assert client.get("/api/v1/admin/report-tokens").json()["tokens"] == []
    assert client.delete(f"/api/v1/admin/report-tokens/{token_id}").status_code == 404


def test_minting_is_admins_only(env):
    client, _conn = env
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "jsmith"))
    r = client.post("/api/v1/admin/report-tokens", json={"username": "jsmith"})
    assert r.status_code == 403


def test_the_users_page_panel_renders_and_mints(env):
    client, conn = env
    admin_client(client)
    assert "REPORT TOKENS" in client.get("/partials/admin/report-tokens").text

    r = client.post("/partials/admin/report-tokens/create",
                    data={"username": "jsmith", "label": "laptop"})
    assert r.status_code == 200
    assert "cce1." in r.text                       # shown once, here
    assert dbmod.fetch_editor_report_tokens(conn)[0]["editor_username"] == "jsmith"

    token_id = dbmod.fetch_editor_report_tokens(conn)[0]["token_id"]
    revoked = client.post("/partials/admin/report-tokens/revoke",
                          data={"token_id": token_id})
    assert revoked.status_code == 200
    assert dbmod.fetch_editor_report_tokens(conn) == []


def test_c8_revoke_confirm_names_the_editor_and_the_consequence(env):
    """C-8 (UX.md, resilience sweep 2026-08-28): one click used to take an
    editor's companion off the fleet with no confirm at all, and the token
    it revokes cannot be shown again."""
    client, conn = env
    admin_client(client)
    client.post("/partials/admin/report-tokens/create",
               data={"username": "jsmith", "label": "laptop"})
    panel = client.get("/partials/admin/report-tokens").text
    assert ("Revoke jsmith's report token? Their companion stops reporting "
            "and stops syncing until you issue a new token and they enter "
            "it. The old token cannot be shown again.") in panel


# ------------------------------------------------------------ migration log

def test_boot_log_names_the_machines_still_on_the_shared_token(env, caplog):
    client, conn = env
    client.post("/api/v1/report", json=payload(), headers=headers(SHARED))
    with caplog.at_level(logging.WARNING, logger="ccsync.dashboard.app"):
        appmod._log_shared_token_migration(conn, client.app.state.settings)
    assert "jsmith/EDIT-PC" in caplog.text
    assert "DASH_SHARED_REPORT_TOKEN_ENABLED=0" in caplog.text


def test_boot_log_is_quiet_once_everyone_has_moved(env, caplog):
    client, conn = env
    token, _row = mint(conn, "jsmith")
    client.post("/api/v1/report", json=payload(), headers=headers(token))
    with caplog.at_level(logging.INFO, logger="ccsync.dashboard.app"):
        appmod._log_shared_token_migration(conn, client.app.state.settings)
    assert "still authenticate" not in caplog.text
    assert "safe" in caplog.text or "retire it" in caplog.text
