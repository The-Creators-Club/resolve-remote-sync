"""CR-367 (prelaunch review 2026-10-07, wave A3a): GL-15 and GL-16, and the
token half of COM-H15.

  * GL-16  the JSON login obeys the same SSO rule as the browser form,
  * GL-15  removing a person cuts off their computers: identity tokens are
           revocable per person (generation + valid_after), a delete leaves a
           durable tombstone every auth method reads, a sign-in mints a
           per-computer report token when the shared one is off, the mounted
           fleet doors withhold a barred identity,
  * COM-H15 token half: a NEW site (variable unset) ships with the shared
           fleet token off, a site that sets it keeps it.
"""
from __future__ import annotations

import sqlite3
import time

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import api, auth
from ccsync_dashboard import db as dbmod
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "test-secret-key-for-cr367"
SHARED = "fleet-report-token-cr367"


def make(tmp_path, name="d.db", **kw):
    kw.setdefault("report_token", SHARED)
    kw.setdefault("admin_users", frozenset({"owen"}))
    return Settings(db_path=str(tmp_path / name), session_secret=SECRET, **kw)


def as_user(client, user):
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, user))
    return client


def report_body(editor="jsmith", machine="PC"):
    return {"editor_name": editor, "machine": machine,
            "reported_at": "2026-10-07T10:00:00+00:00", "lanes": []}


def hdr(token, editor="jsmith", floor=0):
    return {"X-CCSync-Token": token,
            "X-CCSync-Identity": auth.make_identity_token(SECRET, editor, floor=floor)}


# ------------------------------------------------------------------ GL-16

def test_json_login_refuses_a_non_admin_on_an_oidc_site(tmp_path):
    settings = make(tmp_path, auth_method="oidc", oidc_issuer="https://idp.example",
                    oidc_client_id="x")
    app = create_app(settings)
    calls = []

    def verifier(s, u, p):
        calls.append(u)
        return True          # the NAS accepts every password: the bug's premise

    app.state.credential_verifier = verifier
    with TestClient(app) as client:
        refused = client.post("/api/v1/login", json={"username": "leaver", "password": "pw"})
        assert refused.status_code == 401
        assert refused.json()["detail"] == "bad username or password"
        assert "ccsync_session" not in client.cookies
        assert calls == []                      # SMB was never even asked
        # the operator's break-glass still works
        ok = client.post("/api/v1/login", json={"username": "owen", "password": "pw"})
        assert ok.status_code == 200 and ok.json()["is_admin"] is True


def test_json_login_is_unchanged_on_an_smb_site(tmp_path):
    app = create_app(make(tmp_path))
    app.state.credential_verifier = lambda s, u, p: True
    with TestClient(app) as client:
        assert client.post("/api/v1/login",
                           json={"username": "jsmith", "password": "pw"}).status_code == 200


def test_both_login_routes_share_one_rule(tmp_path):
    settings = make(tmp_path, auth_method="oidc")
    assert auth.oidc_password_refused(settings, "jsmith") is True
    assert auth.oidc_password_refused(settings, "owen") is False
    assert auth.oidc_password_refused(make(tmp_path), "jsmith") is False


def test_json_login_refuses_plaintext_when_the_cookie_is_pinned_secure(tmp_path):
    settings = make(tmp_path, cookie_secure="1", site_dashboard_url="https://d.example")
    app = create_app(settings)
    app.state.credential_verifier = lambda s, u, p: True
    with TestClient(app) as client:                      # http://testserver
        resp = client.post("/api/v1/login", json={"username": "owen", "password": "pw"})
        assert resp.status_code == 403
        assert "https" in resp.json()["detail"]


# ------------------------------------------------- identity revocation (db)

def test_a_token_minted_before_a_revocation_is_dead_and_a_new_one_lives(tmp_path):
    settings = make(tmp_path)
    app = create_app(settings)
    with TestClient(app):
        conn = dbmod.connect(settings.db_path)
        old = auth.make_identity_token(SECRET, "jsmith")
        assert auth.read_identity_token_ex(settings, old, conn=conn)[0] == "jsmith"
        rec = dbmod.revoke_identity(conn, "jsmith", by="admin:owen", reason="laptop taken")
        conn.commit()
        assert rec["gen"] == 1
        assert auth.read_identity_token_ex(settings, old, conn=conn) == (None, False)
        status = auth.identity_status(settings, old, conn=conn)
        assert status == ("jsmith", False, True)         # ours, and withdrawn
        # signing in again in the SAME second still yields a token that passes
        new = auth.make_identity_token(SECRET, "jsmith",
                                       floor=dbmod.identity_floor(conn, "jsmith"))
        assert auth.read_identity_token_ex(settings, new, conn=conn)[0] == "jsmith"
        # another person is untouched
        other = auth.make_identity_token(SECRET, "ruskin")
        assert auth.read_identity_token_ex(settings, other, conn=conn)[0] == "ruskin"
        conn.close()


def test_the_generation_counts_and_never_moves_backwards(tmp_path):
    conn = dbmod.connect(str(tmp_path / "g.db"))
    dbmod.migrate(conn)
    a = dbmod.revoke_identity(conn, "x", by="a", now=2_000_000_000)
    b = dbmod.revoke_identity(conn, "x", by="a", now=1_000)   # a clock step back
    assert (a["gen"], b["gen"]) == (1, 2)
    assert b["valid_after"] == a["valid_after"]
    conn.close()


def test_the_token_wire_shape_is_still_five_fields():
    token = auth.make_identity_token(SECRET, "jsmith", floor=int(time.time()) + 50)
    assert len(token.split(".")) == 5
    assert auth.identity_issued_at(token) >= int(time.time()) + 50


def test_a_revocation_check_that_cannot_read_the_db_fails_open(tmp_path):
    settings = make(tmp_path, name="missing.db")        # no file at all
    token = auth.make_identity_token(SECRET, "jsmith")
    assert auth.read_identity_token_ex(settings, token)[0] == "jsmith"
    assert not (tmp_path / "missing.db").exists()       # and it made no file


# ---------------------------------------------------------------- /report

def test_report_with_a_revoked_identity_is_401_and_says_why(tmp_path):
    settings = make(tmp_path)
    app = create_app(settings)
    with TestClient(app) as client:
        stale = hdr(SHARED)
        assert client.post("/api/v1/report", json=report_body(), headers=stale).status_code == 200
        conn = dbmod.connect(settings.db_path)
        dbmod.revoke_identity(conn, "jsmith", by="admin:owen")
        conn.commit()
        conn.close()
        resp = client.post("/api/v1/report", json=report_body(), headers=stale)
        assert resp.status_code == 401
        assert "revoked" in resp.json()["detail"]
        # signed in again (a new floor-stamped token) it is accepted at once
        conn = dbmod.connect(settings.db_path)
        floor = dbmod.identity_floor(conn, "jsmith")
        conn.close()
        assert client.post("/api/v1/report", json=report_body(),
                           headers=hdr(SHARED, floor=floor)).status_code == 200


def test_the_admin_revoke_route(tmp_path):
    settings = make(tmp_path)
    app = create_app(settings)
    with TestClient(app) as client:
        stale = hdr(SHARED)
        as_user(client, "jsmith")
        assert client.post("/api/v1/admin/users/jsmith/identity/revoke").status_code in (401, 403)
        as_user(client, "owen")
        resp = client.post("/api/v1/admin/users/jsmith/identity/revoke")
        assert resp.status_code == 200, resp.text
        assert resp.json()["generation"] == 1
        client.cookies.clear()
        assert client.post("/api/v1/report", json=report_body(),
                           headers=stale).status_code == 401


# ------------------------------------------- delete leaves a tombstone

def _delete_smb_editor(client, conn, name="jsmith"):
    """Delete through the real route on an smb site with no NAS backend."""
    as_user(client, "owen")
    return client.delete(f"/api/v1/admin/users/{name}")


def test_a_deleted_smb_editor_stays_out_and_is_not_re_registered(tmp_path):
    settings = make(tmp_path)
    app = create_app(settings)
    with TestClient(app) as client:
        h = hdr(SHARED)
        assert client.post("/api/v1/report", json=report_body(), headers=h).status_code == 200
        conn = dbmod.connect(settings.db_path)
        assert "jsmith" in dbmod.known_editor_usernames(conn)
        resp = _delete_smb_editor(client, conn)
        assert resp.status_code == 200, resp.text
        assert "jsmith" not in dbmod.known_editor_usernames(conn)
        assert dbmod.identity_removed(conn, "jsmith")
        client.cookies.clear()
        # the SAME credentials the person held before: shared token + the
        # never-expiring identity token. Both used to pass.
        again = client.post("/api/v1/report", json=report_body(), headers=h)
        assert again.status_code == 401
        # the generation bump must not word a REMOVED person as "revoked: sign
        # in again" (a sign-in that is then refused with 403).
        assert "removed" in again.json()["detail"]
        assert "sign in again" not in again.json()["detail"]
        # and even a token minted AFTER the delete (the NAS account still
        # exists, so /verify's password check passes) is refused at the report
        fresh = hdr(SHARED, floor=dbmod.identity_floor(conn, "jsmith"))
        refused = client.post("/api/v1/report", json=report_body(), headers=fresh)
        assert refused.status_code == 401
        assert "removed" in refused.json()["detail"]
        assert "jsmith" not in dbmod.known_editor_usernames(conn)
        conn.close()


def test_verify_refuses_a_removed_person(tmp_path):
    settings = make(tmp_path)
    app = create_app(settings)
    app.state.credential_verifier = lambda s, u, p: True
    with TestClient(app) as client:
        conn = dbmod.connect(settings.db_path)
        dbmod.revoke_identity(conn, "jsmith", by="admin:owen", removed=True)
        conn.commit()
        resp = client.post("/api/v1/verify", json={"username": "jsmith", "password": "x"})
        assert resp.status_code == 403
        assert "removed" in resp.json()["detail"]
        conn.close()


def test_only_an_admin_action_lifts_the_tombstone(tmp_path):
    conn = dbmod.connect(str(tmp_path / "t.db"))
    dbmod.migrate(conn)
    dbmod.revoke_identity(conn, "jsmith", by="admin:owen", removed=True)
    for source in ("report", "seed", "selection"):
        dbmod.record_known_editor(conn, "jsmith", source)
        assert dbmod.identity_removed(conn, "jsmith"), source
    dbmod.record_known_editor(conn, "jsmith", "admin")
    assert not dbmod.identity_removed(conn, "jsmith")
    # old tokens stay dead even though the name is back
    assert dbmod.identity_floor(conn, "jsmith") > 0
    conn.close()


def test_account_refusal_reads_the_tombstone_on_every_auth_method(tmp_path):
    for method in ("smb", "oidc", "local"):
        settings = make(tmp_path, name=f"{method}.db", auth_method=method,
                        oidc_issuer="https://idp.example", oidc_client_id="x")
        conn = dbmod.connect(settings.db_path)
        dbmod.migrate(conn)
        dbmod.revoke_identity(conn, "jsmith", by="a", removed=True)
        assert api._account_refusal(settings, conn, "jsmith") == api.REFUSED_ACCOUNT_REMOVED
        conn.close()


# ------------------------------------------ /verify mints a computer token

def test_verify_mints_a_per_computer_token_when_the_shared_one_is_off(tmp_path):
    settings = make(tmp_path, shared_report_token_enabled=False)
    app = create_app(settings)
    app.state.credential_verifier = lambda s, u, p: True
    with TestClient(app) as client:
        body = client.post("/api/v1/verify", json={
            "username": "jsmith", "password": "x", "machine": "EDIT-1"}).json()
        tok = body["report_token"]
        assert tok.startswith("cce1.") and body["editor_report_token"] == tok
        assert body["report_token_kind"] == "editor"
        # it is a real, working credential: a report under it is accepted
        resp = client.post("/api/v1/report", json=report_body(), headers={
            "X-CCSync-Token": tok,
            "X-CCSync-Identity": body["token"]})
        assert resp.status_code == 200, resp.text
        # the same computer signing in again REPLACES its token
        again = client.post("/api/v1/verify", json={
            "username": "jsmith", "password": "x", "machine": "EDIT-1"}).json()
        assert again["report_token"] != tok
        conn = dbmod.connect(settings.db_path)
        live = dbmod.fetch_editor_report_tokens(conn, editor="jsmith")
        assert len(live) == 1 and live[0]["label"].endswith("EDIT-1")
        assert dbmod.verify_editor_report_token(conn, tok) is None
        # a second computer keeps its own
        client.post("/api/v1/verify", json={
            "username": "jsmith", "password": "x", "machine": "EDIT-2"})
        assert len(dbmod.fetch_editor_report_tokens(conn, editor="jsmith")) == 2
        conn.close()


def test_verify_is_unchanged_while_the_shared_token_is_on(tmp_path):
    settings = make(tmp_path, shared_report_token_enabled=True)
    app = create_app(settings)
    app.state.credential_verifier = lambda s, u, p: True
    with TestClient(app) as client:
        body = client.post("/api/v1/verify",
                           json={"username": "jsmith", "password": "x"}).json()
        assert body["report_token"] == SHARED
        assert "editor_report_token" not in body
        conn = dbmod.connect(settings.db_path)
        assert dbmod.fetch_editor_report_tokens(conn) == []     # nothing minted
        conn.close()


def test_the_per_computer_cap_retires_the_oldest(tmp_path):
    settings = make(tmp_path, shared_report_token_enabled=False)
    app = create_app(settings)
    app.state.credential_verifier = lambda s, u, p: True
    with TestClient(app) as client:
        for _ in range(api.VERIFY_TOKENS_PER_EDITOR + 4):
            client.post("/api/v1/verify", json={"username": "jsmith", "password": "x"})
        conn = dbmod.connect(settings.db_path)
        assert len(dbmod.fetch_editor_report_tokens(conn, editor="jsmith")) \
            == api.VERIFY_TOKENS_PER_EDITOR
        conn.close()


# ----------------------------------------------- the mounted fleet doors

def test_identity_bar_names_revoked_and_barred_identities(tmp_path):
    settings = make(tmp_path)
    app = create_app(settings)
    with TestClient(app):
        conn = dbmod.connect(settings.db_path)
        token = auth.make_identity_token(SECRET, "jsmith")
        assert api.identity_bar(settings, token) is None
        assert api.identity_bar(settings, "") is None
        assert api.identity_bar(settings, "garbage") is None     # the sub-app refuses it
        dbmod.record_known_editor(conn, "jsmith", "admin")
        dbmod.suspend_editor(conn, "jsmith", by="owen")
        conn.commit()
        assert "suspended" in api.identity_bar(settings, token)
        dbmod.unsuspend_editor(conn, "jsmith")
        dbmod.revoke_identity(conn, "jsmith", by="owen")
        conn.commit()
        assert "revoked" in api.identity_bar(settings, token)
        conn.close()


def test_strip_barred_identity_removes_only_the_barred_header(tmp_path):
    settings = make(tmp_path)
    app = create_app(settings)
    with TestClient(app):
        conn = dbmod.connect(settings.db_path)
        good = auth.make_identity_token(SECRET, "ruskin").encode("latin-1")
        bad = auth.make_identity_token(SECRET, "jsmith").encode("latin-1")
        dbmod.revoke_identity(conn, "jsmith", by="owen", removed=True)
        conn.commit()
        conn.close()
        kept = api.strip_barred_identity(
            settings, [(b"x-ccsync-token", b"t"), (b"x-ccsync-identity", bad)], "test")
        assert kept == [(b"x-ccsync-token", b"t")]
        kept = api.strip_barred_identity(
            settings, [(b"x-ccsync-identity", good)], "test")
        assert kept == [(b"x-ccsync-identity", good)]


@pytest.mark.parametrize("mount", ["broll", "music", "ytdl"])
def test_every_mount_gate_strips_a_barred_identity(tmp_path, mount):
    """The shared-token path on b-roll, music and ytdl: the stamp says
    "somebody in this fleet", and the identity header was the only thing naming
    who. A removed person's header must not reach the sub-app."""
    import importlib
    settings = make(tmp_path)
    app = create_app(settings)
    with TestClient(app):
        conn = dbmod.connect(settings.db_path)
        dbmod.revoke_identity(conn, "jsmith", by="owen", removed=True)
        conn.commit()
        conn.close()
        mod = importlib.import_module(f"ccsync_dashboard.{mount}")
        gate_cls = next(getattr(mod, n) for n in ("BrollGate", "MusicGate", "YtdlGate")
                        if hasattr(mod, n))
        seen = {}

        async def inner(scope, receive, send):
            seen["headers"] = dict(scope["headers"])

        gate = _build_gate(gate_cls, inner, settings)
        tok = auth.make_identity_token(SECRET, "jsmith").encode("latin-1")
        scope = {"type": "http", "path": "/x", "headers": [
            (b"x-ccsync-token", SHARED.encode()), (b"x-ccsync-identity", tok)]}
        scope2 = gate._identified_scope(scope)
        names = {k for k, _ in scope2["headers"]}
        assert b"x-ccsync-identity" not in names


def _build_gate(gate_cls, inner, settings):
    """The three gates take (app, ...) with differing extras; try the shapes."""
    import inspect
    params = list(inspect.signature(gate_cls.__init__).parameters)[1:]
    kwargs = {}
    for p in params:
        if p == "app":
            kwargs[p] = inner
        elif p in ("session_secret", "secret"):
            kwargs[p] = SECRET
        elif p == "settings":
            kwargs[p] = settings
        elif p in ("ingest_token", "token"):
            kwargs[p] = "t" * 30
    return gate_cls(**kwargs)


# ------------------------------------------- COM-H15 token default (settings)

@pytest.mark.parametrize("raw,expected", [
    ("", False),             # a NEW site: unset is off
    ("0", False), ("false", False), ("off", False), ("no", False),
    ("1", True), ("true", True), ("yes", True),
    ("garbage", True),       # a typo in a deliberately-set variable keeps the fleet connected
])
def test_from_env_default_is_off_and_explicit_values_are_honoured(raw, expected):
    env = {"DASH_REPORT_TOKEN": SHARED}
    if raw != "":
        env["DASH_SHARED_REPORT_TOKEN_ENABLED"] = raw
    assert Settings.from_env(env).shared_report_token_enabled is expected


def test_a_hand_built_settings_keeps_the_legacy_default():
    assert Settings().shared_report_token_enabled is True


def test_new_site_resolves_shared_token_as_none(tmp_path):
    settings = make(tmp_path, shared_report_token_enabled=False)
    assert api.resolve_companion_credential(settings, None, SHARED)[0] == api.AUTH_NONE
    legacy = make(tmp_path, shared_report_token_enabled=True)
    assert api.resolve_companion_credential(legacy, None, SHARED)[0] == api.AUTH_SHARED


def test_the_sign_in_token_cap_retires_the_least_recently_used(tmp_path):
    """A computer still reporting on the OLDEST token must not lose it to a
    newer sign-in's cap (overseer note 4, 2026-10-07)."""
    conn = dbmod.connect(str(tmp_path / "c.db"))
    dbmod.migrate(conn)
    ids = []
    for i in range(api.VERIFY_TOKENS_PER_EDITOR):
        _tok, row = dbmod.create_editor_report_token(
            conn, "jsmith", created_by="verify", label=f"{api.VERIFY_TOKEN_LABEL}: PC{i}")
        ids.append(row["token_id"])
    conn.commit()
    conn.execute("UPDATE editor_report_tokens SET last_used_at = '2999-01-01T00:00:00+00:00' "
                 "WHERE token_id = ?", (ids[0],))
    conn.commit()
    api._mint_verify_report_token(conn, "jsmith", "NEWPC")
    live = {r["token_id"] for r in dbmod.fetch_editor_report_tokens(conn, editor="jsmith")}
    assert ids[0] in live
    assert len(live) == api.VERIFY_TOKENS_PER_EDITOR
    conn.close()
