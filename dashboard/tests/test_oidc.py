"""DASH_AUTH_METHOD=oidc, end to end against a real (fake) IdP.

COMMERCIAL_READINESS.md item 12, 2026-08-17. Everything runs with
DASH_DEV_INSECURE deleted -- see test_sessions.py for why the rest of the
suite does not.
"""
from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth, oidc
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

from fake_idp import FakeIdP

STRONG = "kX9-quiet-harbour-42-zephyr"


@pytest.fixture(autouse=True)
def _strict(monkeypatch):
    monkeypatch.delenv("DASH_DEV_INSECURE", raising=False)
    yield


@pytest.fixture
def idp():
    fake = FakeIdP().start()
    fake.claims = {"preferred_username": "jsmith", "groups": ["editors"]}
    try:
        yield fake
    finally:
        fake.stop()


def _settings(tmp_path, idp, name="oidc.db", **kwargs) -> Settings:
    base = dict(
        db_path=str(tmp_path / name), session_secret=STRONG,
        admin_users=frozenset({"owen"}), auth_method="oidc",
        oidc_issuer=idp.base_url, oidc_client_id="ccsync-dashboard",
        oidc_client_secret="s" * 32,
    )
    base.update(kwargs)
    return Settings(**base)


def _app(settings):
    app = create_app(settings)
    app.state.credential_verifier = lambda s, u, p: p == "correct-horse"
    # A fresh discovery cache per app, so one test's IdP cannot answer another's.
    app.state.oidc_discovery = oidc.Discovery()
    return app


def _sign_in(client, idp):
    """Walk both legs: /auth/oidc/login -> (the IdP) -> /auth/oidc/callback.

    The `aud` and `nonce` the IdP mints are filled in here from the authorize
    URL, because a real provider echoes the nonce it was given and stamps the
    client it issued for. A test that wants either of them WRONG walks the two
    legs by hand instead."""
    start = client.get("/auth/oidc/login?next=/transfers", follow_redirects=False)
    assert start.status_code == 303, start.text
    query = parse_qs(urlsplit(start.headers["location"]).query)
    idp.claims["aud"] = "ccsync-dashboard"
    idp.claims["nonce"] = query["nonce"][0]
    return client.get(f"/auth/oidc/callback?code=abc&state={query['state'][0]}",
                      follow_redirects=False), query


# --------------------------------------------------------------- happy path

def test_sign_in_end_to_end(tmp_path, idp):
    app = _app(_settings(tmp_path, idp))
    with TestClient(app) as client:
        resp, query = _sign_in(client, idp)
        assert resp.status_code == 303 and resp.headers["location"] == "/transfers"
        assert client.get("/api/v1/me").json()["user"] == "jsmith"
        # ...and it is a normal, revocable dashboard session like any other
        assert len(app.state.session_store.list_for_user("jsmith")) == 1

        # PKCE S256, state and nonce are all on the authorize URL
        assert query["code_challenge_method"] == ["S256"]
        assert query["code_challenge"] and query["state"] and query["nonce"]
        assert query["redirect_uri"] == ["http://testserver/auth/oidc/callback"]
        # ...and the verifier (never the challenge) went to the token endpoint
        form = idp.issued_forms[-1]
        assert form["grant_type"] == "authorization_code"
        assert form["code_verifier"] and form["code_verifier"] not in query["code_challenge"]
        assert form["_authorization"].startswith("Basic ")   # client_secret_basic


def test_the_username_claim_is_configurable(tmp_path, idp):
    idp.claims = {"preferred_username": "ignored", "nas_login": "editor2"}
    with TestClient(_app(_settings(tmp_path, idp, oidc_username_claim="nas_login"))) as c:
        resp, _ = _sign_in(c, idp)
        assert resp.status_code == 303
        assert c.get("/api/v1/me").json()["user"] == "editor2"


def test_admin_comes_from_dash_admin_users_not_the_idp(tmp_path, idp):
    """A claim mapping that silently grants fleet-wide rights is exactly what
    an operator must be able to read off one list."""
    idp.claims = {"preferred_username": "jsmith", "groups": ["ccsync-admins"]}
    settings = _settings(tmp_path, idp, oidc_admin_claim="groups",
                         oidc_admin_values=frozenset({"ccsync-admins"}))
    with TestClient(_app(settings)) as c:
        _sign_in(c, idp)
        assert c.get("/api/v1/me").json()["is_admin"] is False
    assert oidc.is_admin_by_claims(settings, {"groups": ["ccsync-admins"]}) is True
    assert oidc.is_admin_by_claims(settings, {"groups": ["everyone"]}) is False


# -------------------------------------------------------------- refusals

def test_a_mismatched_state_is_refused(tmp_path, idp):
    with TestClient(_app(_settings(tmp_path, idp))) as c:
        c.get("/auth/oidc/login", follow_redirects=False)
        resp = c.get("/auth/oidc/callback?code=abc&state=not-the-one",
                     follow_redirects=False)
        assert resp.status_code == 400
        assert c.get("/api/v1/me").json()["user"] is None


def test_a_callback_with_no_flow_cookie_is_refused(tmp_path, idp):
    with TestClient(_app(_settings(tmp_path, idp))) as c:
        resp = c.get("/auth/oidc/callback?code=abc&state=whatever",
                     follow_redirects=False)
        assert resp.status_code == 400


def test_a_wrongly_signed_id_token_is_refused(tmp_path, idp):
    idp.sign_with_wrong_key = True
    with TestClient(_app(_settings(tmp_path, idp))) as c:
        resp, _ = _sign_in(c, idp)
        assert resp.status_code == 403
        assert c.get("/api/v1/me").json()["user"] is None


def test_a_replayed_nonce_from_another_login_is_refused(tmp_path, idp):
    """The nonce binds the id_token to THIS browser's login attempt."""
    with TestClient(_app(_settings(tmp_path, idp))) as first:
        first.get("/auth/oidc/login", follow_redirects=False)
        # freeze the id_token the IdP will hand back, minted for a nonce that
        # belongs to nobody
        idp.claims = {**idp.claims, "aud": "ccsync-dashboard",
                      "nonce": "some-other-logins-nonce"}
        start = first.get("/auth/oidc/login", follow_redirects=False)
        state = parse_qs(urlsplit(start.headers["location"]).query)["state"][0]
        resp = first.get(f"/auth/oidc/callback?code=abc&state={state}",
                         follow_redirects=False)
        assert resp.status_code == 403


def test_an_id_token_for_the_wrong_audience_is_refused(tmp_path, idp):
    with TestClient(_app(_settings(tmp_path, idp))) as c:
        start = c.get("/auth/oidc/login", follow_redirects=False)
        query = parse_qs(urlsplit(start.headers["location"]).query)
        idp.claims = {"preferred_username": "jsmith", "aud": "some-other-client",
                      "nonce": query["nonce"][0]}
        resp = c.get(f"/auth/oidc/callback?code=abc&state={query['state'][0]}",
                     follow_redirects=False)
        assert resp.status_code == 403


def test_a_missing_username_claim_is_refused_not_guessed(tmp_path, idp):
    idp.claims = {"sub": "0d1f", "email": "jsmith@example.com"}
    with TestClient(_app(_settings(tmp_path, idp))) as c:
        resp, _ = _sign_in(c, idp)
        assert resp.status_code == 403
        assert "DASH_OIDC_USERNAME_CLAIM" in resp.json()["detail"]


def test_an_email_shaped_username_is_refused(tmp_path, idp):
    """Every join in this dashboard is a NAS username. Truncating
    'jsmith@example.com' to 'jsmith' is how an editor gets matched to somebody
    else's selections."""
    idp.claims = {"preferred_username": "jsmith@example.com"}
    with TestClient(_app(_settings(tmp_path, idp))) as c:
        resp, _ = _sign_in(c, idp)
        assert resp.status_code == 403


def test_a_token_endpoint_failure_is_a_refusal_not_a_traceback(tmp_path, idp):
    idp.token_status = 400
    with TestClient(_app(_settings(tmp_path, idp))) as c:
        resp, _ = _sign_in(c, idp)
        assert resp.status_code == 403


def test_a_discovery_document_naming_another_issuer_is_refused(tmp_path, idp):
    """The IdP mix-up attack: a document served by one provider claiming to
    speak for another."""
    idp.discovery_document = lambda: {
        "issuer": "https://someone-else.example",
        "authorization_endpoint": f"{idp.base_url}/authorize",
        "token_endpoint": f"{idp.base_url}/token", "jwks_uri": f"{idp.base_url}/jwks",
    }
    with TestClient(_app(_settings(tmp_path, idp))) as c:
        assert c.get("/auth/oidc/login", follow_redirects=False).status_code == 503


# ------------------------------------------------------- the seam and config

def test_the_routes_are_inert_without_oidc_configured(tmp_path):
    """Always mounted, never active: a 503 naming the missing variable beats a
    404 that looks like an old build."""
    settings = Settings(db_path=str(tmp_path / "off.db"), session_secret=STRONG)
    with TestClient(create_app(settings)) as c:
        resp = c.get("/auth/oidc/login", follow_redirects=False)
        assert resp.status_code == 503 and "DASH_OIDC_ISSUER" in resp.json()["detail"]


def test_oidc_without_an_issuer_refuses_to_boot(tmp_path):
    settings = Settings(db_path=str(tmp_path / "bad.db"), session_secret=STRONG,
                        auth_method="oidc")
    with pytest.raises(RuntimeError) as excinfo:
        create_app(settings)
    assert "DASH_OIDC_ISSUER" in str(excinfo.value)


def test_a_plain_http_issuer_is_refused_unless_it_is_loopback():
    assert auth._issuer_transport_ok("https://idp.example") is True
    assert auth._issuer_transport_ok("http://idp.example") is False
    assert auth._issuer_transport_ok("http://127.0.0.1:8080") is True
    assert auth._issuer_transport_ok("http://localhost:8080") is True
    assert auth._issuer_transport_ok("ftp://idp.example") is False


def test_local_password_login_is_break_glass_for_admins_only(tmp_path, idp):
    """The IdP being down must not lock the operator out; it must not reopen
    password login for the whole fleet either."""
    with TestClient(_app(_settings(tmp_path, idp, "bg.db"))) as c:
        page = c.get("/login")
        assert "[ SIGN IN WITH SSO ]" in page.text
        assert "name=\"password\"" not in page.text          # hidden by default
        assert "?local=1" in page.text

        local = c.get("/login?local=1")
        assert "name=\"password\"" in local.text

        # a non-admin cannot use it
        refused = c.post("/login?local=1", data={"username": "jsmith",
                                                 "password": "correct-horse"})
        assert "sign-in refused" in refused.text
        assert c.get("/api/v1/me").json()["user"] is None

        # ...the operator can
        ok = c.post("/login?local=1", data={"username": "owen", "password": "correct-horse"},
                    follow_redirects=False)
        assert ok.status_code == 303
        assert c.get("/api/v1/me").json()["user"] == "owen"


def test_the_flow_cookie_is_signed_and_short_lived():
    packed = oidc.pack_flow(STRONG, {"state": "s", "exp": 10_000_000_000})
    assert oidc.unpack_flow(STRONG, packed)["state"] == "s"
    assert oidc.unpack_flow("another-secret-entirely", packed) is None
    assert oidc.unpack_flow(STRONG, packed[:-4] + "0000") is None
    assert oidc.unpack_flow(STRONG, None) is None
    assert oidc.unpack_flow(STRONG, "not-a-cookie") is None
    expired = oidc.pack_flow(STRONG, {"state": "s", "exp": 1_000})
    assert oidc.unpack_flow(STRONG, expired) is None


# ------------------------------------------- who may sign in (trust-model-5)


def _known_editor(settings, username):
    """A username this fleet has a positive record of, the same predicate
    api._require_fleet_member enforces on the password path."""
    from ccsync_dashboard import db as dbmod

    conn = dbmod.connect(settings.db_path)
    dbmod.migrate(conn)
    dbmod.record_known_editor(conn, username, "admin", dbmod.utcnow_iso())
    conn.commit()
    conn.close()


def test_an_account_this_fleet_does_not_know_is_refused(tmp_path, idp):
    """Pointing DASH_OIDC_ISSUER at a company directory used to let every
    account in it sign in as an editor, and one whose preferred_username
    equalled a real editor's name inherited that editor's plans, ticks and
    device approvals (trust-model-5, 2026-08-21)."""
    settings = _settings(tmp_path, idp, "member.db")
    _known_editor(settings, "someone-else")
    idp.claims = {"preferred_username": "accounts.payable"}
    with TestClient(_app(settings)) as c:
        resp, _ = _sign_in(c, idp)
        assert resp.status_code == 403
        assert "not part of this fleet" in resp.text
        assert c.get("/api/v1/me").json()["user"] is None


def test_an_editor_this_fleet_knows_signs_in(tmp_path, idp):
    settings = _settings(tmp_path, idp, "member2.db")
    _known_editor(settings, "jsmith")
    with TestClient(_app(settings)) as c:
        resp, _ = _sign_in(c, idp)
        assert resp.status_code == 303
        assert c.get("/api/v1/me").json()["user"] == "jsmith"


def test_a_group_claim_can_be_the_authority_instead(tmp_path, idp):
    """The customer whose IdP owns the answer: DASH_OIDC_ALLOWED_GROUPS makes
    membership of a directory group the check, and nothing else passes."""
    settings = _settings(tmp_path, idp, "group.db",
                         oidc_allowed_groups=frozenset({"editors"}))
    _known_editor(settings, "someone-else")
    with TestClient(_app(settings)) as c:              # idp publishes groups=["editors"]
        resp, _ = _sign_in(c, idp)
        assert resp.status_code == 303
        assert c.get("/api/v1/me").json()["user"] == "jsmith"

    idp.claims = {"preferred_username": "intern", "groups": ["everyone"]}
    with TestClient(_app(settings)) as c:
        resp, _ = _sign_in(c, idp)
        assert resp.status_code == 403
        assert "not a member of the group" in resp.text


def test_the_operator_is_never_locked_out_of_a_fleet_with_no_editors_yet(tmp_path, idp):
    """Degrades the way api._require_fleet_member does: with nothing to check
    against, the check is skipped and logged rather than refusing day one."""
    with TestClient(_app(_settings(tmp_path, idp, "empty.db"))) as c:
        resp, _ = _sign_in(c, idp)
        assert resp.status_code == 303
