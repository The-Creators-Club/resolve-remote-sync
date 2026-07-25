from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "test-secret"


@pytest.fixture(autouse=True)
def _reset_throttle():
    auth._failures.clear()
    yield
    auth._failures.clear()


def test_cookie_round_trip_and_expiry():
    cookie = auth.make_session_cookie(SECRET, "jsmith", now=1000.0)
    assert auth.read_session_cookie(SECRET, cookie, now=1000.0) == "jsmith"
    assert auth.read_session_cookie(SECRET, cookie, now=1000.0 + auth.SESSION_TTL_SECONDS + 1) is None
    assert auth.read_session_cookie("other-secret", cookie) is None
    tampered = cookie.replace("jsmith", "admin")
    assert auth.read_session_cookie(SECRET, tampered) is None
    assert auth.read_session_cookie(SECRET, None) is None
    assert auth.read_session_cookie(SECRET, "v1.garbage") is None
    assert auth.read_session_cookie("", cookie) is None  # no secret configured


def test_can_manage_matrix():
    settings = Settings(admin_users=frozenset({"alex"}))
    assert auth.can_manage(settings, "jsmith", "jsmith") is True
    assert auth.can_manage(settings, "jsmith", "other") is False
    assert auth.can_manage(settings, "alex", "other") is True
    assert auth.can_manage(settings, None, "jsmith") is False


@pytest.fixture
def client(tmp_path):
    settings = Settings(db_path=str(tmp_path / "a.db"), session_secret=SECRET,
                        admin_users=frozenset({"alex"}))
    app = create_app(settings)
    app.state.credential_verifier = (
        lambda s, u, p: (u, p) in {("jsmith", "pw1"), ("alex", "pw2")}
    )
    with TestClient(app) as c:
        yield c


def test_login_logout_flow(client):
    assert client.post("/api/v1/login", json={"username": "jsmith", "password": "wrong"}).status_code == 401
    resp = client.post("/api/v1/login", json={"username": "JSmith", "password": "pw1"})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "user": "jsmith", "is_admin": False}
    assert auth.COOKIE_NAME in resp.cookies
    me = client.get("/api/v1/me").json()
    assert me["user"] == "jsmith" and me["is_admin"] is False

    client.post("/api/v1/logout")
    assert client.get("/api/v1/me").json()["user"] is None


def test_login_throttling(client):
    for _ in range(auth.LOGIN_FAILURE_LIMIT):
        client.post("/api/v1/login", json={"username": "jsmith", "password": "bad"})
    resp = client.post("/api/v1/login", json={"username": "jsmith", "password": "pw1"})
    assert resp.status_code == 429  # even the right password waits out the window


def test_login_unconfigured(tmp_path):
    app = create_app(Settings(db_path=str(tmp_path / "b.db")))  # no session_secret
    with TestClient(app) as client:
        resp = client.post("/api/v1/login", json={"username": "x", "password": "y"})
        assert resp.status_code == 503


def test_login_gate_blocks_anonymous(client):
    # pages redirect to /login; JSON returns 401; open paths pass through
    r = client.get("/", follow_redirects=False)
    # the redirect preserves the destination (deep-link support)
    assert r.status_code == 303 and r.headers["location"].startswith("/login")
    assert client.get("/api/v1/projects").status_code == 401
    assert client.get("/api/v1/transfers").status_code in (401, 404)  # 404 until route exists
    assert client.get("/login").status_code == 200
    assert client.get("/api/v1/health").status_code == 200            # open for monitoring
    # report endpoint stays open (token-guarded by its own route)
    assert client.post("/api/v1/report", json={"bad": 1}).status_code in (401, 422)


def test_login_gate_allows_authenticated(client):
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "jsmith"))
    assert client.get("/", follow_redirects=False).status_code == 200
    assert client.get("/api/v1/projects").status_code == 200


def test_selection_open_with_token_but_gated_without(tmp_path):
    settings = Settings(db_path=str(tmp_path / "t.db"), session_secret=SECRET, report_token="tok")
    app = create_app(settings)
    with TestClient(app) as c:
        # companion token path bypasses the gate
        assert c.get("/api/v1/selection/jsmith", headers={"X-CCSync-Token": "tok"}).status_code == 200
        # without token and without session -> gated
        assert c.get("/api/v1/selection/jsmith").status_code == 401
        # wrong token -> gated
        assert c.get("/api/v1/selection/jsmith", headers={"X-CCSync-Token": "no"}).status_code == 401


def test_verify_endpoint_returns_identity_token(client):
    # bad creds -> 401
    assert client.post("/api/v1/verify", json={"username": "jsmith", "password": "bad"}).status_code == 401
    resp = client.post("/api/v1/verify", json={"username": "JSmith", "password": "pw1"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True and body["username"] == "jsmith"
    # the token validates as a session/identity token for that user
    assert auth.read_session_cookie(SECRET, body["token"]) == "jsmith"
    # onboarding smoothness: the report token comes back so the installer
    # needs no extra secret from the editor
    assert "report_token" in body


def test_identity_token_longer_ttl_than_session():
    import time as _t
    now = _t.time()
    sess = auth.make_session_cookie(SECRET, "jsmith", now=now)
    ident = auth.make_identity_token(SECRET, "jsmith", now=now)
    # identity expiry field is further out
    assert int(ident.split(".")[2]) > int(sess.split(".")[2])


def test_report_marks_machine_verified_with_identity(tmp_path):
    from ccsync_dashboard import db as dbmod
    settings = Settings(db_path=str(tmp_path / "v.db"), session_secret=SECRET, report_token="tok")
    app = create_app(settings)
    with TestClient(app) as c:
        conn = dbmod.connect(tmp_path / "v.db")
        payload = {"editor_name": "jsmith", "machine": "PC", "reported_at": "2026-07-25T10:00:00+00:00",
                   "lanes": [{"name": "lane_a_video_up", "state": "idle"}]}
        # no identity header -> unverified
        c.post("/api/v1/report", json=payload, headers={"X-CCSync-Token": "tok"})
        assert dbmod.fetch_verified_map(conn) == {("jsmith", "PC"): False}
        # valid identity token matching editor -> verified
        token = auth.make_identity_token(SECRET, "jsmith")
        c.post("/api/v1/report", json=payload,
               headers={"X-CCSync-Token": "tok", "X-CCSync-Identity": token})
        assert dbmod.fetch_verified_map(conn) == {("jsmith", "PC"): True}
        # a token for a DIFFERENT user does not verify jsmith's report
        other = auth.make_identity_token(SECRET, "someoneelse")
        c.post("/api/v1/report", json=payload,
               headers={"X-CCSync-Token": "tok", "X-CCSync-Identity": other})
        assert dbmod.fetch_verified_map(conn) == {("jsmith", "PC"): False}
        conn.close()


def test_scope_helper():
    from ccsync_dashboard.auth import Scope
    editor = Scope(user="jsmith", admin=False)
    assert editor.editor == "jsmith" and editor.allows("jsmith") and not editor.allows("other")
    admin = Scope(user="alex", admin=True, focus="ruskin")
    assert admin.editor == "ruskin" and admin.allows("anyone")
    admin_all = Scope(user="alex", admin=True)
    assert admin_all.editor is None and admin_all.allows("whoever")


def test_login_page_renders(client):
    page = client.get("/login")
    assert page.status_code == 200 and "[ SIGN IN ]" in page.text
    resp = client.post("/login", data={"username": "jsmith", "password": "pw1"},
                       follow_redirects=False)
    assert resp.status_code == 303 and auth.COOKIE_NAME in resp.cookies
    bad = client.post("/login", data={"username": "jsmith", "password": "nope"})
    assert "bad username or password" in bad.text
