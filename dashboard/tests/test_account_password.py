"""Account page 2026-09-25, group B: change your own password
(docs/ACCOUNT_PAGE_FEATURES.md 3.3, feature F2, owner decisions D-1..D-3).

The JSON route is group C's (`POST /api/v1/me/password`, in account_api.py).
So that this file tests the real request path (cookies, the session store,
CSRF, the threadpool) without waiting on that module, each app here carries a
harness route that is the pinned route shape of 3.3 verbatim: session user
(401), `change_own_password`, then on ok `rotate_after_password_change`,
commit, answer; a refusal maps `status`/`detail`, and a 429 carries
`auth.throttle_headers(retry_after)`.
"""
from __future__ import annotations

import json
import logging
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import Body, Depends, HTTPException, Request, Response
from fastapi.testclient import TestClient

from ccsync_dashboard import account_password, api, auth, local_users
from ccsync_dashboard import db as dbmod
from ccsync_dashboard.app import create_app
from ccsync_dashboard.nas.base import NasError
from ccsync_dashboard.settings import Settings

SECRET = "a-test-session-secret-of-length"
OLD = "the-old-password-1"
NEW = "a-brand-new-password-2"
PATH = "/api/v1/_harness/me/password"


def _add_harness(app) -> None:
    @app.post(PATH)
    def harness(request: Request, response: Response,
                payload: dict[str, Any] = Body(...),
                conn=Depends(api.get_conn)) -> dict[str, Any]:
        user = auth.get_session_user(request)
        if not user:
            raise HTTPException(status_code=401, detail="Sign in first.")
        res = account_password.change_own_password(
            request, conn, user, payload.get("current_password", ""),
            payload.get("new_password", ""), payload.get("new_password_again", ""))
        if not res.ok:
            headers = auth.throttle_headers(res.retry_after) if res.status == 429 else None
            raise HTTPException(status_code=res.status, detail=res.detail, headers=headers)
        n = account_password.rotate_after_password_change(request, response, user)
        conn.commit()
        return {"ok": True, "method": res.method, "other_sessions_signed_out": n,
                "csrf": auth.csrf_token(request)}


def _body(current=OLD, new=NEW, again=None):
    return {"current_password": current, "new_password": new,
            "new_password_again": new if again is None else again}


class Env(SimpleNamespace):
    def login(self, user="tchen", password=None) -> str:
        """Sign in for real (a TRACKED session), returning the csrf token."""
        self.client.cookies.clear()
        resp = self.client.post("/api/v1/login", json={
            "username": user, "password": password or self.passwords[user]})
        assert resp.status_code == 200, resp.text
        return resp.json()["csrf"]

    def change(self, csrf, **kw):
        return self.client.post(PATH, json=_body(**kw), headers={"X-CSRF-Token": csrf})

    def sid(self, cookie=None) -> str:
        return auth.session_id_for(SECRET, cookie or self.client.cookies.get(auth.COOKIE_NAME))

    def audit_rows(self):
        conn = dbmod.connect(self.db_path)
        try:
            return [dict(r) for r in conn.execute(
                "SELECT * FROM fleet_audit WHERE action = 'account.password_change'")]
        finally:
            conn.close()


def _make_env(tmp_path, **settings_kw):
    db_path = str(tmp_path / "dash.db")
    app = create_app(Settings(db_path=db_path, session_secret=SECRET,
                              admin_users=frozenset({"owen"}), **settings_kw))
    _add_harness(app)
    return app, db_path


@pytest.fixture
def smb_env(tmp_path, nas_case):
    """smb sign-in against each NAS fake; the SMB probe itself is replaced by
    the app's credential_verifier seam (the one /api/v1/login also reads)."""
    app, db_path = _make_env(tmp_path, **nas_case.kwargs)
    passwords = {"tchen": OLD, "owen": OLD}
    calls: list[str] = []

    def verifier(settings, user, password):
        calls.append(user)
        return passwords.get(user) == password

    app.state.credential_verifier = verifier
    nas_case.seed_editor("tchen")
    with TestClient(app) as client:
        client.app.state.collector.stop()
        yield Env(client=client, app=app, db_path=db_path, passwords=passwords,
                  nas_case=nas_case, verifier_calls=calls)


@pytest.fixture
def local_env(tmp_path):
    app, db_path = _make_env(tmp_path, auth_method="local")
    with TestClient(app) as client:
        client.app.state.collector.stop()
        conn = dbmod.connect(db_path)
        local_users.create_user(conn, "tchen", OLD, "editor")
        local_users.create_user(conn, "mira", OLD, "admin")
        conn.commit()
        conn.close()
        yield Env(client=client, app=app, db_path=db_path,
                  passwords={"tchen": OLD, "mira": OLD})


def _nas_password(nas_case, user):
    for row in nas_case.fake.state["users"]:
        if row.get("username", row.get("name")) == user:
            return row.get("password")
    return None


# ---------------------------------------------------------------- success

def test_smb_success_changes_the_nas_password_and_rotates(smb_env, caplog):
    env = smb_env
    caplog.set_level(logging.DEBUG)
    # Another browser of the same person, and one of somebody else's.
    env.login("owen")
    owen_sid = env.sid()
    env.login("tchen")
    other_sid = env.sid()
    csrf = env.login("tchen")
    old_cookie = env.client.cookies.get(auth.COOKIE_NAME)
    old_sid = env.sid()
    store = env.app.state.session_store

    resp = env.change(csrf)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True and body["method"] == "smb"
    assert body["other_sessions_signed_out"] == 1
    assert _nas_password(env.nas_case, "tchen") == NEW

    # D-1: the other browser is signed out; D-2: this one has a NEW cookie
    # and the old one no longer validates server-side.
    new_cookie = env.client.cookies.get(auth.COOKIE_NAME)
    assert new_cookie and new_cookie != old_cookie
    assert store.validate(old_sid) is None
    assert store.validate(other_sid) is None
    assert store.validate(env.sid(new_cookie)) == "tchen"
    # Somebody else's session is untouched.
    assert store.validate(owen_sid) == "owen"
    # The csrf returned belongs to the NEW session, so the next write works.
    assert body["csrf"] and body["csrf"] != csrf
    env.passwords["tchen"] = NEW            # what the NAS now holds, for the verifier
    again = env.client.post(PATH, json=_body(current=NEW, new="yet-another-password-3"),
                            headers={"X-CSRF-Token": body["csrf"]})
    assert again.status_code == 200, again.text

    rows = env.audit_rows()
    assert rows and rows[0]["actor"] == "tchen" and rows[0]["subject"] == "tchen"
    detail = json.loads(rows[0]["detail_json"])
    assert detail == {"method": "smb", "other_sessions_signed_out": 1}
    for row in rows:
        for secret in (OLD, NEW, "yet-another-password-3"):
            assert secret not in row["detail_json"]
    for rec in caplog.records:
        text = rec.getMessage()
        for secret in (OLD, NEW, "yet-another-password-3"):
            assert secret not in text


def test_local_success_changes_the_hash_and_keeps_report_tokens(local_env):
    env = local_env
    conn = dbmod.connect(env.db_path)
    token, _row = dbmod.create_editor_report_token(conn, "tchen", "owen")
    conn.commit()
    conn.close()
    identity = auth.make_identity_token(SECRET, "tchen")

    csrf = env.login("tchen")
    resp = env.change(csrf)
    assert resp.status_code == 200, resp.text
    assert resp.json()["method"] == "local"
    assert resp.json()["other_sessions_signed_out"] == 0

    conn = dbmod.connect(env.db_path)
    try:
        assert local_users.verify_password(conn, "tchen", NEW)
        assert not local_users.verify_password(conn, "tchen", OLD)
        # A report token and a companion identity authenticate a MACHINE.
        assert dbmod.verify_editor_report_token(conn, token) == "tchen"
    finally:
        conn.close()
    assert auth.read_identity_token(SECRET, identity) == "tchen"
    # The new password signs in through the real sign-in route.
    env.passwords["tchen"] = NEW
    env.login("tchen")


# ---------------------------------------------------------------- refusals

def test_wrong_current_password_records_a_failure(smb_env):
    env = smb_env
    csrf = env.login("tchen")
    store = env.app.state.session_store
    resp = env.change(csrf, current="not-my-password")
    assert resp.status_code == 422
    assert resp.json()["detail"] == account_password.MSG_WRONG_CURRENT
    conn = dbmod.connect(env.db_path)
    try:
        row = conn.execute("SELECT failures FROM login_attempts WHERE scope='user' "
                           "AND key='tchen'").fetchone()
    finally:
        conn.close()
    assert row is not None and row["failures"] == 1
    assert _nas_password(env.nas_case, "tchen") is None
    # Nothing rotated on a refusal.
    assert store.validate(env.sid()) == "tchen"
    assert env.audit_rows() == []


def test_throttled_after_the_sign_in_budget(smb_env):
    env = smb_env
    csrf = env.login("tchen")
    statuses = []
    for _ in range(8):
        resp = env.change(csrf, current="wrong-guess-password")
        statuses.append(resp.status_code)
        if resp.status_code == 429:
            break
    assert statuses[0] == 422 and statuses[-1] == 429, statuses
    assert int(resp.headers["Retry-After"]) >= 1
    assert resp.json()["detail"].startswith("Too many sign-in attempts. Try again in ")
    # A throttled attempt never reaches the verifier, even with the right one.
    before = len(env.verifier_calls)
    resp = env.change(csrf)
    assert resp.status_code == 429
    assert len(env.verifier_calls) == before
    # D-3: the SAME budget as the sign-in page.
    resp = env.client.post("/api/v1/login", json={"username": "tchen", "password": OLD})
    assert resp.status_code == 429


def test_probe_busy_is_a_503(smb_env):
    env = smb_env
    csrf = env.login("tchen")

    def busy(settings, user, password):
        raise auth.CredentialProbeBusy("full")

    env.app.state.credential_verifier = busy
    resp = env.change(csrf)
    assert resp.status_code == 503
    assert resp.json()["detail"] == account_password.MSG_BUSY


@pytest.mark.parametrize("kw,detail", [
    ({"new": "short", "again": "short"},
     "The new password needs at least 12 characters. Nothing changed."),
    ({"current": OLD, "new": OLD}, account_password.MSG_SAME),
    ({"again": "something-else-entirely"}, account_password.MSG_MISMATCH),
])
def test_form_mistakes_are_refused_before_anything_is_asked(smb_env, kw, detail):
    env = smb_env
    csrf = env.login("tchen")
    calls_before = len(env.verifier_calls)
    resp = env.change(csrf, **kw)
    assert resp.status_code == 422
    assert resp.json()["detail"] == detail
    # No budget spent, no NAS asked.
    assert len(env.verifier_calls) == calls_before
    assert _nas_password(env.nas_case, "tchen") is None


def test_min_chars_sentence_follows_the_constant(smb_env, monkeypatch):
    env = smb_env
    csrf = env.login("tchen")
    monkeypatch.setattr(auth, "MIN_PASSWORD_CHARS", 30)
    resp = env.change(csrf)
    assert resp.status_code == 422
    assert "at least 30 characters" in resp.json()["detail"]


def test_smb_not_an_editor_never_calls_set_known_password(smb_env, monkeypatch):
    env = smb_env
    # owen is on DASH_ADMIN_USERS but is not an account in the NAS's editors group.
    set_calls: list[str] = []
    real = account_password.make_nas_client

    def spy(settings):
        nas = real(settings)
        original = nas.set_known_password

        def recording(user, password):
            set_calls.append(user)
            return original(user, password)

        nas.set_known_password = recording
        return nas

    monkeypatch.setattr(account_password, "make_nas_client", spy)
    csrf = env.login("owen")
    resp = env.change(csrf)
    assert resp.status_code == 409
    assert resp.json()["detail"] == account_password.MSG_NOT_EDITOR.format(user="owen")
    assert set_calls == []


class _BrokenNas:
    def __init__(self, on: str, text: str = "boom"):
        self.on, self.text, self.set_calls = on, text, []

    def is_editor(self, user):
        if self.on == "is_editor":
            raise NasError(self.text)
        return True

    def set_known_password(self, user, password):
        self.set_calls.append(user)
        if self.on == "set":
            raise NasError(self.text)


def test_smb_nas_unreachable_is_a_502(smb_env, monkeypatch):
    env = smb_env
    nas = _BrokenNas("is_editor")
    monkeypatch.setattr(account_password, "make_nas_client", lambda s: nas)
    csrf = env.login("tchen")
    resp = env.change(csrf)
    assert resp.status_code == 502
    assert resp.json()["detail"] == account_password.MSG_NAS_UNREACHABLE
    assert nas.set_calls == []


def test_smb_nas_setup_error_of_any_kind_is_a_502_not_a_500(smb_env, monkeypatch, caplog):
    # Account page 2026-09-25 review round: a non-NasError from the client
    # factory must not become a 500 carrying backend detail.
    env = smb_env

    def broken(settings):
        raise ValueError(f"bad nas_host 'nas.internal:9999' with secret {NEW}")

    monkeypatch.setattr(account_password, "make_nas_client", broken)
    caplog.set_level(logging.WARNING, logger="ccsync.dashboard.account_password")
    csrf = env.login("tchen")
    resp = env.change(csrf)
    assert resp.status_code == 502
    assert resp.json()["detail"] == account_password.MSG_NAS_UNREACHABLE
    assert "nas.internal" not in resp.text
    assert NEW not in caplog.text and OLD not in caplog.text
    assert _nas_password(env.nas_case, "tchen") != NEW  # never set


def test_smb_nas_refusal_is_a_502_and_its_text_is_logged_masked(smb_env, monkeypatch,
                                                                 caplog):
    env = smb_env
    nas = _BrokenNas("set", text=f"validation failed for password {NEW} (errno 22)")
    monkeypatch.setattr(account_password, "make_nas_client", lambda s: nas)
    caplog.set_level(logging.WARNING, logger="ccsync.dashboard.account_password")
    csrf = env.login("tchen")
    resp = env.change(csrf)
    assert resp.status_code == 502
    assert resp.json()["detail"] == account_password.MSG_NAS_REFUSED
    assert "errno 22" not in resp.text and NEW not in resp.text
    logged = " ".join(r.getMessage() for r in caplog.records)
    assert "errno 22" in logged and NEW not in logged
    assert env.audit_rows() == []


def test_smb_without_a_nas_credential_is_a_503(tmp_path):
    app, _db = _make_env(tmp_path)          # smb, no NAS settings at all
    app.state.credential_verifier = lambda s, u, p: p == OLD
    with TestClient(app) as client:
        client.app.state.collector.stop()
        csrf = client.post("/api/v1/login",
                           json={"username": "tchen", "password": OLD}).json()["csrf"]
        resp = client.post(PATH, json=_body(), headers={"X-CSRF-Token": csrf})
    assert resp.status_code == 503
    assert resp.json()["detail"] == account_password.MSG_NO_NAS


def test_local_break_glass_admin_without_a_row_is_a_409(local_env):
    """owen is on DASH_ADMIN_USERS with no local account. He cannot sign in
    with a password here, so his session is a hand-minted one (dev mode)."""
    env = local_env
    env.client.cookies.clear()
    env.client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "owen"))
    resp = env.client.post(PATH, json=_body())
    assert resp.status_code == 409
    assert resp.json()["detail"] == account_password.MSG_NOT_LOCAL.format(user="owen")
    # Refused before verifying, so no sign-in failure was charged to him.
    conn = dbmod.connect(env.db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM login_attempts").fetchone()[0] == 0
    finally:
        conn.close()


def test_local_wrong_current_password(local_env):
    env = local_env
    csrf = env.login("tchen")
    resp = env.change(csrf, current="definitely-not-it")
    assert resp.status_code == 422
    assert resp.json()["detail"] == account_password.MSG_WRONG_CURRENT


def test_oidc_is_refused_with_directions():
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        settings=SimpleNamespace(auth_method="oidc"))))
    res = account_password.change_own_password(request, None, "tchen", OLD, NEW, NEW)
    assert (res.ok, res.status, res.method) == (False, 409, "oidc")
    assert res.detail == account_password.MSG_OIDC


def test_signed_out_is_refused_by_the_route_shape(local_env):
    env = local_env
    env.client.cookies.clear()
    resp = env.client.post(PATH, json=_body())
    assert resp.status_code == 401


def test_a_tracked_session_without_csrf_is_refused(local_env):
    env = local_env
    env.login("tchen")
    resp = env.client.post(PATH, json=_body())
    assert resp.status_code == 403
    conn = dbmod.connect(env.db_path)
    try:
        assert local_users.verify_password(conn, "tchen", OLD)
    finally:
        conn.close()


# ---------------------------------------------------------------- rotation edges

def test_rotation_with_no_session_store_still_mints_a_cookie():
    minted = []
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()),
                              state=SimpleNamespace(ccsync_session=(None, None, False)))

    def fake_start(req, resp, user):
        minted.append(user)
        return "new-sid"

    orig_store, orig_start = auth.session_store, auth.start_session
    auth.session_store = lambda req: None
    auth.start_session = fake_start
    try:
        n = account_password.rotate_after_password_change(request, SimpleNamespace(), "TChen")
    finally:
        auth.session_store, auth.start_session = orig_store, orig_start
    assert n is None and minted == ["tchen"]


def test_rotation_failure_to_mint_still_signs_the_others_out(local_env, monkeypatch):
    # Account page 2026-09-25 review round: D-1 "always". A failed mint must
    # not leave a stolen cookie alive; this browser keeps its OLD session.
    env = local_env
    env.login("tchen")
    other_sid = env.sid()
    csrf = env.login("tchen")
    sid = env.sid()
    assert other_sid != sid
    store = env.app.state.session_store

    def broken(*a, **k):
        raise RuntimeError("disk full")

    monkeypatch.setattr(auth, "start_session", broken)
    resp = env.change(csrf)
    assert resp.status_code == 200, resp.text
    assert resp.json()["other_sessions_signed_out"] == 1
    assert store.validate(other_sid) is None
    assert store.validate(sid) == "tchen"


def test_rotation_failure_to_mint_and_to_revoke_is_not_raised(local_env, monkeypatch):
    env = local_env
    csrf = env.login("tchen")
    store = env.app.state.session_store

    def broken(*a, **k):
        raise RuntimeError("disk full")

    monkeypatch.setattr(auth, "start_session", broken)
    monkeypatch.setattr(store, "revoke_user", broken)
    resp = env.change(csrf)
    assert resp.status_code == 200, resp.text
    assert resp.json()["other_sessions_signed_out"] is None


def test_rotation_failure_to_revoke_is_logged_not_raised(local_env, monkeypatch):
    env = local_env
    csrf = env.login("tchen")
    store = env.app.state.session_store

    def broken(*a, **k):
        raise RuntimeError("locked")

    monkeypatch.setattr(store, "revoke_user", broken)
    resp = env.change(csrf)
    assert resp.status_code == 200, resp.text
    assert resp.json()["other_sessions_signed_out"] is None


def test_every_sentence_has_no_em_dash():
    for name in dir(account_password):
        if name.startswith("MSG_"):
            assert "—" not in getattr(account_password, name), name
