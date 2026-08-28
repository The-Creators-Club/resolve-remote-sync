from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "test-secret"


@pytest.fixture(autouse=True)
def _reset_throttle():
    """No-op kept as a marker: the failure budget moved out of a module-level
    dict and into SQLite on 2026-08-17 (sessions.SessionStore), so it is
    per-database and every test's tmp_path already isolates it. The strict,
    production-shaped behaviour lives in test_sessions.py."""
    yield


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
    settings = Settings(admin_users=frozenset({"owen"}))
    assert auth.can_manage(settings, "jsmith", "jsmith") is True
    assert auth.can_manage(settings, "jsmith", "other") is False
    assert auth.can_manage(settings, "owen", "other") is True
    assert auth.can_manage(settings, None, "jsmith") is False


@pytest.fixture
def client(tmp_path):
    settings = Settings(db_path=str(tmp_path / "a.db"), session_secret=SECRET,
                        admin_users=frozenset({"owen"}))
    app = create_app(settings)
    app.state.credential_verifier = (
        lambda s, u, p: (u, p) in {("jsmith", "pw1"), ("owen", "pw2")}
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


def test_expired_session_answers_htmx_pollers_with_hx_redirect(client):
    """DASH-4: /partials/* is not in the JSON-401 prefix list, so an expired
    session used to hand every self-refreshing fragment a 303 -- which XHR
    follows transparently -- and htmx swapped the WHOLE login document into
    <main>/<aside>. The page then kept polling a login page every 2s and
    never navigated anywhere. HX-Redirect is what htmx turns into a real
    browser navigation."""
    resp = client.get(
        "/partials/transfers",
        headers={"HX-Request": "true", "HX-Current-URL": "http://dash/transfers"},
        follow_redirects=False,
    )
    assert resp.status_code == 401
    # the PAGE, not the fragment -- ?next=/partials/transfers would log the
    # editor back in onto a bare fragment
    assert resp.headers["HX-Redirect"] == "/login?next=%2Ftransfers"
    # and nothing swappable came back
    assert "<!doctype html" not in resp.text.lower()
    assert "password" not in resp.text.lower()


def test_htmx_redirect_keeps_the_pages_query_and_survives_a_missing_current_url(client):
    resp = client.get(
        "/partials/sidebar?current=x",
        headers={"HX-Request": "true",
                 "HX-Current-URL": "http://dash/project/2026-cct?as=editor2"},
        follow_redirects=False,
    )
    assert resp.headers["HX-Redirect"] == "/login?next=%2Fproject%2F2026-cct%3Fas%3Deditor2"
    # no HX-Current-URL (htmx always sends it, but a hand-rolled caller may
    # not): fall back to the request's own path rather than dropping the header
    resp = client.get("/partials/sidebar", headers={"HX-Request": "true"},
                      follow_redirects=False)
    assert resp.headers["HX-Redirect"] == "/login?next=%2Fpartials%2Fsidebar"


def test_plain_document_gets_still_get_the_303(client):
    """The companion's /project-setup deep link is a document GET and must
    keep landing on the login page with its destination preserved."""
    resp = client.get("/project-setup?resolve_project=Doc", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/login?next=%2Fproject-setup")
    assert "HX-Redirect" not in resp.headers


def test_selection_open_with_token_but_gated_without(tmp_path):
    settings = Settings(db_path=str(tmp_path / "t.db"), session_secret=SECRET, report_token="tok")
    app = create_app(settings)
    identity = auth.make_identity_token(SECRET, "jsmith")
    with TestClient(app) as c:
        # companion token + matching identity bypasses the gate
        assert c.get("/api/v1/selection/jsmith",
                     headers={"X-CCSync-Token": "tok",
                              "X-CCSync-Identity": identity}).status_code == 200
        # without token and without session -> gated
        assert c.get("/api/v1/selection/jsmith").status_code == 401
        # wrong token -> gated
        assert c.get("/api/v1/selection/jsmith", headers={"X-CCSync-Token": "no"}).status_code == 401


def test_selection_read_with_the_shared_token_needs_a_matching_identity(tmp_path):
    """The report token is a SHARED secret /api/v1/verify hands to every
    editor, so on its own it said nothing about WHOSE selection was being
    read: any editor could enumerate the whole fleet's queues and sticky
    project-root mappings. Same identity rule as /api/v1/report."""
    settings = Settings(db_path=str(tmp_path / "si.db"), session_secret=SECRET,
                        report_token="tok")
    with TestClient(create_app(settings)) as c:
        token_only = {"X-CCSync-Token": "tok"}
        assert c.get("/api/v1/selection/jsmith", headers=token_only).status_code == 401
        # a valid identity for SOMEONE ELSE is not enough either
        wrong = dict(token_only, **{"X-CCSync-Identity": auth.make_identity_token(SECRET, "editor2")})
        assert c.get("/api/v1/selection/jsmith", headers=wrong).status_code == 401
        # a session cookie is not an identity token
        stale = dict(token_only, **{"X-CCSync-Identity": auth.make_session_cookie(SECRET, "jsmith")})
        assert c.get("/api/v1/selection/jsmith", headers=stale).status_code == 401
        right = dict(token_only, **{"X-CCSync-Identity": auth.make_identity_token(SECRET, "jsmith")})
        assert c.get("/api/v1/selection/jsmith", headers=right).status_code == 200


def test_selection_read_falls_back_to_token_only_without_a_session_secret(tmp_path):
    """A server with no DASH_SESSION_SECRET can neither mint nor verify
    identity tokens (dashboard login is off too), so demanding one there
    would simply break lab deployments -- same carve-out /api/v1/report has."""
    settings = Settings(db_path=str(tmp_path / "nosec.db"), report_token="tok")
    with TestClient(create_app(settings)) as c:
        assert c.get("/api/v1/selection/jsmith",
                     headers={"X-CCSync-Token": "tok"}).status_code == 200


def test_verify_endpoint_returns_identity_token(client):
    # bad creds -> 401
    assert client.post("/api/v1/verify", json={"username": "jsmith", "password": "bad"}).status_code == 401
    resp = client.post("/api/v1/verify", json={"username": "JSmith", "password": "pw1"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True and body["username"] == "jsmith"
    # the token validates as an IDENTITY token for that user...
    assert auth.read_identity_token(SECRET, body["token"]) == "jsmith"
    # ...but NOT as a session cookie (see SEC-1: purpose claims are distinct).
    assert auth.read_session_cookie(SECRET, body["token"]) is None
    # onboarding smoothness: the report token comes back so the installer
    # needs no extra secret from the editor
    assert "report_token" in body


def test_verify_only_mints_identities_for_fleet_members(tmp_path):
    """The credential check is an SMB session setup, so ANY account the NAS's
    SMB service accepts -- a bookkeeper, a share user -- came back with a
    valid identity token AND the shared report_token, i.e. the ability to
    write reports and read selections. Membership of `editors` (or
    DASH_ADMIN_USERS) is the fleet definition create_or_update_editor already
    enforces."""
    from fake_truenas import FakeTrueNAS

    truenas = FakeTrueNAS().start()
    try:
        truenas.state["groups"].append({"id": 111, "group": "editors", "gid": 3001})
        truenas.state["users"].extend([
            {"id": 5, "uid": 3010, "username": "jsmith", "full_name": "jsmith",
             "home": "/h/jsmith", "group": {"id": 111}, "groups": [111],
             "sshpubkey": None, "smb": True, "locked": False, "password_disabled": False},
            {"id": 6, "uid": 4000, "username": "bookkeeper", "full_name": "bookkeeper",
             "home": "/h/book", "group": {"id": 60}, "groups": [60], "sshpubkey": None,
             "smb": True, "locked": False, "password_disabled": False},
            {"id": 7, "uid": 0, "username": "root", "full_name": "root", "home": "/root",
             "group": {"id": 5}, "groups": [5], "sshpubkey": None, "smb": True,
             "locked": False, "password_disabled": False},
        ])
        settings = Settings(db_path=str(tmp_path / "v.db"), session_secret=SECRET,
                            report_token="tok", admin_users=frozenset({"owen"}),
                            truenas_pw="fake-pw", truenas_base_url=truenas.base_url)
        app = create_app(settings)
        app.state.credential_verifier = lambda s, u, p: p == "pw"   # SMB says yes to all
        with TestClient(app) as c:
            def verify(username):
                return c.post("/api/v1/verify", json={"username": username, "password": "pw"})

            assert verify("jsmith").status_code == 200                    # editor
            assert verify("owen").status_code == 200                      # DASH_ADMIN_USERS
            for outsider in ("bookkeeper", "root", "ghost"):
                resp = verify(outsider)
                assert resp.status_code == 403, outsider
                assert "editors" in resp.json()["detail"]
                assert "report_token" not in resp.text
    finally:
        truenas.stop()


def test_verify_is_retryable_not_open_when_truenas_is_unreachable(tmp_path):
    """Fail closed but retryable: a NAS blip must never quietly hand out
    identities, nor permanently brick sign-in."""
    settings = Settings(db_path=str(tmp_path / "vu.db"), session_secret=SECRET,
                        truenas_pw="fake-pw",
                        truenas_base_url="http://127.0.0.1:9/api/v2.0")   # discard port
    app = create_app(settings)
    app.state.credential_verifier = lambda s, u, p: True
    with TestClient(app) as c:
        resp = c.post("/api/v1/verify", json={"username": "jsmith", "password": "pw"})
        assert resp.status_code == 503
        assert "try again" in resp.json()["detail"]


def test_verify_skips_the_group_check_without_truenas_credentials(tmp_path):
    """Same degrade-don't-crash convention as the admin Users section: with
    no TRUENAS_PW there is nothing to check against, and locking every
    companion out of a TrueNAS-less deployment is not the answer."""
    settings = Settings(db_path=str(tmp_path / "vn.db"), session_secret=SECRET)
    app = create_app(settings)
    app.state.credential_verifier = lambda s, u, p: True
    with TestClient(app) as c:
        assert c.post("/api/v1/verify",
                      json={"username": "jsmith", "password": "pw"}).status_code == 200


def test_session_cookie_secure_flag_follows_the_scheme(tmp_path):
    """secure=True on today's plain-http LAN deployment makes the browser
    silently drop the cookie -- an unloggable total outage. auto = on for
    https only; DASH_COOKIE_SECURE forces either way."""
    from ccsync_dashboard import auth as authmod

    def cookie_header(settings, headers=None, peer=("testclient", 50000)):
        app = create_app(settings)
        app.state.credential_verifier = lambda s, u, p: True
        with TestClient(app, client=peer) as c:
            resp = c.post("/api/v1/login", json={"username": "jsmith", "password": "pw"},
                          headers=headers or {})
            assert resp.status_code == 200
            return resp.headers["set-cookie"].lower()

    auto = Settings(db_path=str(tmp_path / "c1.db"), session_secret=SECRET)
    assert "secure" not in cookie_header(auto)                       # http today
    assert "httponly" in cookie_header(auto) and "samesite=lax" in cookie_header(auto)
    # A TLS terminator in front is the only way this deployment sees https --
    # and since 2026-08-17 (H1) its X-Forwarded-Proto counts only when it
    # arrives from a peer in DASH_TRUSTED_PROXIES. Tailscale Serve and a
    # sidecar both arrive over loopback, which is the default.
    assert "secure" not in cookie_header(auto, {"X-Forwarded-Proto": "https"})
    assert "secure" in cookie_header(
        Settings(db_path=str(tmp_path / "c1b.db"), session_secret=SECRET),
        {"X-Forwarded-Proto": "https"}, peer=("127.0.0.1", 50000))

    forced = Settings(db_path=str(tmp_path / "c2.db"), session_secret=SECRET,
                      cookie_secure="1")
    assert "secure" in cookie_header(forced, {"X-Forwarded-Proto": "https"})
    off = Settings(db_path=str(tmp_path / "c3.db"), session_secret=SECRET,
                   cookie_secure="0")
    assert "secure" not in cookie_header(off, {"X-Forwarded-Proto": "https"},
                                         peer=("127.0.0.1", 50000))

    assert Settings.from_env({}).cookie_secure == "auto"
    assert Settings.from_env({"DASH_COOKIE_SECURE": "1"}).cookie_secure == "1"
    assert authmod.cookie_secure is not None


def test_session_cookie_secure_flag_on_the_html_login_form(tmp_path):
    settings = Settings(db_path=str(tmp_path / "c4.db"), session_secret=SECRET,
                        cookie_secure="1")
    app = create_app(settings)
    app.state.credential_verifier = lambda s, u, p: True
    with TestClient(app) as c:
        # X-Forwarded-Proto: the form is REFUSED on a connection that is
        # provably plain http while DASH_COOKIE_SECURE=1, because the browser
        # would drop the Secure cookie and loop forever (auth.
        # refuse_plaintext_login, 2026-08-17).
        resp = c.post("/login", data={"username": "jsmith", "password": "pw"},
                      headers={"X-Forwarded-Proto": "https"}, follow_redirects=False)
        assert resp.status_code == 303
        assert "secure" in resp.headers["set-cookie"].lower()


def test_session_cookie_not_accepted_as_identity_token():
    cookie = auth.make_session_cookie(SECRET, "jsmith")
    assert auth.read_session_cookie(SECRET, cookie) == "jsmith"
    assert auth.read_identity_token(SECRET, cookie) is None


def test_identity_token_not_accepted_as_session_cookie():
    token = auth.make_identity_token(SECRET, "jsmith")
    assert auth.read_identity_token(SECRET, token) == "jsmith"
    assert auth.read_session_cookie(SECRET, token) is None


def test_dotted_username_round_trips_through_both_token_kinds():
    # A dot is a valid TrueNAS-style username character (db.py's
    # _USERNAME_RE) -- it must never break the token's field parsing (S-9).
    cookie = auth.make_session_cookie(SECRET, "john.doe")
    assert auth.read_session_cookie(SECRET, cookie) == "john.doe"
    token = auth.make_identity_token(SECRET, "john.doe")
    assert auth.read_identity_token(SECRET, token) == "john.doe"


def test_v1_token_format_rejected_everywhere():
    # Hard cutover (see SEC-1/S-9 module docstring): a pre-2026-07-25 v1
    # token is never valid, either as a session cookie or an identity token.
    v1 = "v1.jsmith.9999999999.deadbeef"
    assert auth.read_session_cookie(SECRET, v1) is None
    assert auth.read_identity_token(SECRET, v1) is None


def test_identity_token_longer_ttl_than_session():
    import time as _t
    now = _t.time()
    sess = auth.make_session_cookie(SECRET, "jsmith", now=now)
    ident = auth.make_identity_token(SECRET, "jsmith", now=now)
    # The expiry is the second-to-last field of both -- identity keeps the
    # five-field shape (v2.<purpose>.<user_b64>.<exp>.<sig>) that the companion
    # parses, while a session cookie carries a per-login nonce as well
    # (2026-08-17, see make_session_cookie).
    assert int(ident.split(".")[-2]) > int(sess.split(".")[-2])
    assert len(ident.split(".")) == 5 and len(sess.split(".")) == 6


def test_identity_token_does_not_expire():
    """CR-86: a companion sign-in must not lapse. It used to hold 30 days, and
    the day it lapsed the editor's lanes stopped behind one tray balloon --
    two days of an editor's syncing went missing that way (2026-08-25). The
    expiry FIELD stays (the five-field shape is what deployed builds parse),
    stamped far enough out that no fleet outlives it."""
    import time as _t
    now = _t.time()
    ident = auth.make_identity_token(SECRET, "jsmith", now=now)
    expires = int(ident.split(".")[-2])
    assert expires - now > 50 * 365 * 24 * 3600
    # Still a token this server reads back, decades later.
    assert auth.read_identity_token(SECRET, ident,
                                    now=now + 40 * 365 * 24 * 3600) == "jsmith"
    # Unchanged wire shape: five fields, which is what every companion in the
    # field parses (companion identity.parse_token).
    assert len(ident.split(".")) == 5


def test_login_throttle_does_not_grow_without_bound(tmp_path):
    """SEC-12, restated for the SQLite budget (2026-08-17): a spray of failed
    logins against throwaway usernames must not accumulate forever. The
    in-process dict swept on every attempt; the table is pruned at boot, and
    an entry outside the window stops counting immediately either way."""
    from ccsync_dashboard import sessions

    store = sessions.SessionStore(tmp_path / "spray.db")
    store.ensure_schema()
    for i in range(50):
        store.record_failure(f"spray{i}", None, now="2026-08-17T00:00:00+00:00")
    assert store.throttled("jsmith", None, now="2026-08-17T04:00:00+00:00") == 0
    # the next FAILURE sweeps them, so the table cannot grow across a
    # months-long container uptime; boot-time prune_attempts is the backstop
    store.record_failure("jsmith", None, now="2026-08-17T04:00:00+00:00")
    assert store.prune_attempts(now="2026-08-17T09:00:00+00:00") == 1


def test_report_requires_a_matching_identity_header(tmp_path):
    """The report token is a SHARED secret handed to every editor by
    /api/v1/verify, so it cannot prove WHO is reporting. A valid
    X-CCSync-Identity naming the same editor is therefore required: without
    it, bob could post as alice and overwrite her lane state, machine_state,
    live transfers and presence rows (proved live in the round-2 audit).

    BEHAVIOUR CHANGE: pre-upgrade companions that send no identity header are
    rejected with 401 rather than written as unverified."""
    from ccsync_dashboard import db as dbmod
    settings = Settings(db_path=str(tmp_path / "v.db"), session_secret=SECRET, report_token="tok")
    app = create_app(settings)
    with TestClient(app) as c:
        conn = dbmod.connect(tmp_path / "v.db")
        payload = {"editor_name": "jsmith", "machine": "PC", "reported_at": "2026-07-25T10:00:00+00:00",
                   "lanes": [{"name": "lane_a_video_up", "state": "idle"}]}
        # no identity header -> REJECTED, and nothing written
        resp = c.post("/api/v1/report", json=payload, headers={"X-CCSync-Token": "tok"})
        assert resp.status_code == 401
        assert "X-CCSync-Identity" in resp.json()["detail"]
        assert dbmod.fetch_verified_map(conn) == {}
        assert conn.execute("SELECT COUNT(*) FROM lane_report_current").fetchone()[0] == 0

        # valid identity token matching editor -> accepted and verified
        token = auth.make_identity_token(SECRET, "jsmith")
        resp = c.post("/api/v1/report", json=payload,
                      headers={"X-CCSync-Token": "tok", "X-CCSync-Identity": token})
        assert resp.status_code == 200
        assert dbmod.fetch_verified_map(conn) == {("jsmith", "PC"): True}

        # a token for a DIFFERENT user is an outright spoofing attempt,
        # rejected before any write, so jsmith's rows are unchanged.
        other = auth.make_identity_token(SECRET, "someoneelse")
        resp = c.post("/api/v1/report", json=payload,
                      headers={"X-CCSync-Token": "tok", "X-CCSync-Identity": other})
        assert resp.status_code == 401
        assert dbmod.fetch_verified_map(conn) == {("jsmith", "PC"): True}

        # a session cookie is not an identity token: invalid, so rejected too
        # (it can no longer sneak through as an unverified write).
        session_cookie = auth.make_session_cookie(SECRET, "someoneelse")
        resp = c.post("/api/v1/report", json=payload,
                      headers={"X-CCSync-Token": "tok", "X-CCSync-Identity": session_cookie})
        assert resp.status_code == 401
        assert dbmod.fetch_verified_map(conn) == {("jsmith", "PC"): True}

        # An expired identity token is rejected with a "sign in again" message
        # rather than silently downgrading to an unverified write. Minted the
        # long way round because make_identity_token no longer expires (CR-86)
        # -- the tokens this arm defends against are the pre-CR-86 ones still
        # sitting in editors' identity.json files.
        expired = auth._make_token(SECRET, auth.PURPOSE_IDENTITY, "jsmith",
                                   now=1000.0, ttl=30 * 24 * 3600)
        resp = c.post("/api/v1/report", json=payload,
                      headers={"X-CCSync-Token": "tok", "X-CCSync-Identity": expired})
        assert resp.status_code == 401 and "expired" in resp.json()["detail"]
        conn.close()


def test_report_without_session_secret_cannot_require_identity(tmp_path):
    """A server with no DASH_SESSION_SECRET cannot mint OR verify identity
    tokens at all (dashboard login is disabled too), so requiring the header
    there would make reports impossible. Lab/token-optional deployments keep
    working -- unverified."""
    from ccsync_dashboard import db as dbmod
    settings = Settings(db_path=str(tmp_path / "n.db"), report_token_optional=True)
    app = create_app(settings)
    with TestClient(app) as c:
        payload = {"editor_name": "jsmith", "machine": "PC",
                   "reported_at": "2026-07-25T10:00:00+00:00",
                   "lanes": [{"name": "lane_a_video_up", "state": "idle"}]}
        assert c.post("/api/v1/report", json=payload).status_code == 200
        conn = dbmod.connect(tmp_path / "n.db")
        assert dbmod.fetch_verified_map(conn) == {("jsmith", "PC"): False}
        conn.close()


def test_report_body_size_is_capped(tmp_path):
    """Any holder of the shared report token could otherwise POST a
    multi-GB body at the single-worker container. Rejected from
    Content-Length, before anything is parsed."""
    from ccsync_dashboard.app import MAX_REPORT_BODY_BYTES
    settings = Settings(db_path=str(tmp_path / "big.db"), session_secret=SECRET, report_token="tok")
    app = create_app(settings)
    with TestClient(app) as c:
        resp = c.post(
            "/api/v1/report",
            content=b"x" * 16,
            headers={"X-CCSync-Token": "tok", "Content-Type": "application/json",
                     "Content-Length": str(MAX_REPORT_BODY_BYTES + 1)},
        )
        assert resp.status_code == 413


def test_scope_helper():
    from ccsync_dashboard.auth import Scope
    editor = Scope(user="jsmith", admin=False)
    assert editor.editor == "jsmith" and editor.allows("jsmith") and not editor.allows("other")
    admin = Scope(user="owen", admin=True, focus="editor2")
    assert admin.editor == "editor2" and admin.allows("anyone")
    admin_all = Scope(user="owen", admin=True)
    assert admin_all.editor is None and admin_all.allows("whoever")


def test_login_page_renders(client):
    page = client.get("/login")
    assert page.status_code == 200 and "[ SIGN IN ]" in page.text
    resp = client.post("/login", data={"username": "jsmith", "password": "pw1"},
                       follow_redirects=False)
    assert resp.status_code == 303 and auth.COOKIE_NAME in resp.cookies
    bad = client.post("/login", data={"username": "jsmith", "password": "nope"})
    # ONE generic message for every refusal since 2026-08-17 -- "bad password"
    # vs "too many attempts" vs "not an admin" was a username/role oracle.
    assert "sign-in refused" in bad.text


def test_login_rejects_oversized_body(client):
    # /login is unauthenticated -- an unbounded body read here would be a
    # single-worker OOM open to anyone on the tailnet (see the unbounded
    # /login body finding). Declared-too-big (Content-Length) is rejected
    # before the body is even read.
    from ccsync_dashboard.ui import MAX_LOGIN_BODY_BYTES

    huge = "username=" + ("a" * (MAX_LOGIN_BODY_BYTES + 1))
    resp = client.post(
        "/login", content=huge.encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 413


def test_login_rejects_too_many_form_fields(client):
    # max_num_fields caps a field-count DoS via parse_qs.
    from ccsync_dashboard.ui import MAX_FORM_FIELDS

    body = "&".join(f"f{i}=x" for i in range(MAX_FORM_FIELDS + 5))
    resp = client.post(
        "/login", content=body.encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 400


def test_login_accepts_normal_sized_body(client):
    # Sanity: the size/field guards must not break a normal login.
    resp = client.post("/login", data={"username": "jsmith", "password": "pw1", "next": "/"},
                       follow_redirects=False)
    assert resp.status_code == 303


def test_a_non_ascii_cookie_byte_is_a_no_session_not_a_500():
    """Starlette hands cookies over latin-1-decoded, so a byte >= 0x80 in the
    signature segment reached hmac.compare_digest as non-ASCII text and raised
    TypeError -- a 500 with a traceback, pre-auth, on every gated path
    (docs/youtube_dlp_bugs.md YTDL-32, the DASH-5 twin; 2026-08-11)."""
    cookie = auth.make_session_cookie(SECRET, "jsmith", now=1000.0)
    head, _, _sig = cookie.rpartition(".")
    assert auth.read_session_cookie(SECRET, head + ".sïg", now=1000.0) is None
    # and a good cookie still reads
    assert auth.read_session_cookie(SECRET, cookie, now=1000.0) == "jsmith"


# ---------------------------------------------- DASH-2 (2026-08-28)
#
# Rotating DASH_SESSION_SECRET 401s every companion in the fleet at once: the
# identity token is an HMAC over it and never expires (CR-86).


def test_a_previous_secret_still_verifies_an_identity_token():
    old = auth.make_identity_token("old-secret", "leso")
    assert auth.read_identity_token("new-secret", old) is None
    assert auth.read_identity_token("new-secret", old, previous=("old-secret",)) == "leso"


def test_a_previous_secret_is_accept_only_and_reported_as_retired():
    from ccsync_dashboard.settings import Settings

    settings = Settings(session_secret="new-secret",
                        session_secrets_previous=("old-secret",))
    user, retired = auth.read_identity_token_ex(
        settings, auth.make_identity_token("old-secret", "leso"))
    assert (user, retired) == ("leso", True)
    user, retired = auth.read_identity_token_ex(
        settings, auth.make_identity_token("new-secret", "leso"))
    assert (user, retired) == ("leso", False)
    # A key that was never trusted is still nothing.
    assert auth.read_identity_token_ex(
        settings, auth.make_identity_token("other", "leso")) == (None, False)


def test_a_session_cookie_from_a_previous_secret_is_still_a_session():
    cookie = auth.make_session_cookie("old-secret", "owen")
    assert auth.read_session_cookie("new-secret", cookie) is None
    assert auth.read_session_cookie("new-secret", cookie,
                                    previous=("old-secret",)) == "owen"


def test_the_previous_key_list_is_named_at_boot_and_still_held_to_the_floor():
    from ccsync_dashboard.settings import Settings

    problems = auth.check_boot_secrets(Settings(
        session_secret="x" * 40, session_secrets_previous=("changeme",)))
    assert any("DASH_SESSION_SECRET_PREVIOUS" in p for p in problems)
