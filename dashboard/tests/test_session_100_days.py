"""A sign-in lasts 100 days and says when it ends (Alex, 2026-10-14: "you only
need to be online once every 100 days to log in once and it should warn you
while online if the login is about to expire. Everything should be able to run
on device in offline mode."), for the whole dashboard.

- every lifetime default is 100 days, idle equal to absolute;
- a signed-in response carries X-CCSync-Session-Expires, /api/ and a page
  alike; a companion identity token does not;
- GET /api/v1/session reports it (and is the gate's 401 with no session);
- /login?renew=1 shows the form while signed in and a sign-in revokes the old
  session and mints a new one;
- a real sign-out lands on the page that forgets the Cards front door's
  saved list, and the worker itself never deletes on a login redirect.
"""
from __future__ import annotations

import hashlib
import hmac
import time

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth, cards_landing, sessions
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "test-secret"
HUNDRED_DAYS = 100 * 24 * 3600
HEADER = "X-CCSync-Session-Expires"


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


def _sign_in(c, user="jsmith", pw="pw1"):
    r = c.post("/login", data={"username": user, "password": pw},
               follow_redirects=False)
    assert r.status_code == 303
    return r


# ------------------------------------------------------------------ defaults

def test_every_default_is_a_hundred_days():
    assert auth.SESSION_TTL_SECONDS == HUNDRED_DAYS
    assert sessions.DEFAULT_IDLE_SECONDS == HUNDRED_DAYS
    assert sessions.DEFAULT_ABSOLUTE_SECONDS == HUNDRED_DAYS
    s = Settings()
    assert s.session_idle_seconds == HUNDRED_DAYS
    assert s.session_absolute_seconds == HUNDRED_DAYS


def test_env_defaults_and_overrides():
    s = Settings.from_env({})
    assert s.session_idle_seconds == HUNDRED_DAYS
    assert s.session_absolute_seconds == HUNDRED_DAYS
    s = Settings.from_env({"DASH_SESSION_IDLE_SECONDS": "3600",
                           "DASH_SESSION_ABSOLUTE_SECONDS": "7200"})
    assert (s.session_idle_seconds, s.session_absolute_seconds) == (3600, 7200)


def test_non_positive_lifetime_falls_back_to_a_hundred_days():
    s = Settings(session_idle_seconds=0, session_absolute_seconds=-5)
    assert s.session_idle_seconds == HUNDRED_DAYS
    assert s.session_absolute_seconds == HUNDRED_DAYS


def test_the_cookie_lives_a_hundred_days(client):
    r = _sign_in(client)
    assert f"Max-Age={HUNDRED_DAYS}" in r.headers["set-cookie"]


# -------------------------------------------------------------------- header

def test_signed_in_page_and_api_carry_the_expiry(client):
    _sign_in(client)
    now = time.time()
    for url in ("/api/v1/me", "/api/v1/session", "/transfers"):
        r = client.get(url)
        assert r.status_code == 200, url
        end = int(r.headers[HEADER])
        assert abs(end - (now + HUNDRED_DAYS)) < 120, url


def test_anonymous_and_gated_responses_carry_no_header(client):
    assert HEADER not in client.get("/api/v1/me").headers
    gated = client.get("/api/v1/session")
    assert gated.status_code == 401 and HEADER not in gated.headers
    assert HEADER not in client.get("/login").headers


def test_a_companion_identity_token_gets_no_header(client):
    token = auth.make_identity_token(SECRET, "jsmith")
    r = client.get("/api/v1/me", headers={"X-CCSync-Identity": token})
    assert HEADER not in r.headers


def test_a_shorter_idle_clock_wins(tmp_path):
    settings = Settings(db_path=str(tmp_path / "a.db"), session_secret=SECRET,
                        session_idle_seconds=3600)
    app = create_app(settings)
    app.state.credential_verifier = lambda s, u, p: True
    with TestClient(app) as c:
        _sign_in(c)
        end = int(c.get("/api/v1/me").headers[HEADER])
        assert abs(end - (time.time() + 3600)) < 120


# ----------------------------------------------------------------- /session

def test_session_endpoint(client):
    gated = client.get("/api/v1/session")
    assert gated.status_code == 401
    assert gated.json()["detail"] == "Your sign-in has expired. Sign in again."
    _sign_in(client)
    body = client.get("/api/v1/session").json()
    assert body["user"] == "jsmith"
    assert abs(body["expires_epoch"] - (time.time() + HUNDRED_DAYS)) < 120
    assert 99.9 < body["days_left"] <= 100
    assert body["expires_at"].startswith("20") and body["expires_at"].endswith("+00:00")


# -------------------------------------------------------------------- renew

def test_login_with_a_live_session_bounces_unless_renewing(client):
    _sign_in(client)
    bounced = client.get("/login?next=/transfers", follow_redirects=False)
    assert bounced.status_code == 303 and bounced.headers["location"] == "/transfers"
    form = client.get("/login?renew=1&next=/transfers", follow_redirects=False)
    assert form.status_code == 200
    assert 'name="renew" value="1"' in form.text
    assert 'name="next" value="/transfers"' in form.text
    assert "another 100 days" in form.text


def test_renewing_revokes_the_old_session_and_mints_a_new_one(client):
    _sign_in(client)
    old_cookie = client.cookies.get(auth.COOKIE_NAME)
    store = client.app.state.session_store
    old_sid = auth.session_id_for(SECRET, old_cookie)
    assert store.validate(old_sid) == "jsmith"
    r = client.post("/login", data={"username": "jsmith", "password": "pw1",
                                    "next": "/transfers", "renew": "1"},
                    follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/transfers"
    new_cookie = client.cookies.get(auth.COOKIE_NAME)
    assert new_cookie and new_cookie != old_cookie
    assert store.validate(old_sid) is None
    assert store.validate(auth.session_id_for(SECRET, new_cookie)) == "jsmith"
    # an off-site next is still refused on the way out
    r = client.post("/login", data={"username": "jsmith", "password": "pw1",
                                    "next": "//evil.example", "renew": "1"},
                    follow_redirects=False)
    assert r.headers["location"] == "/"


def test_a_failed_renewal_leaves_the_session_alone(client):
    _sign_in(client)
    r = client.post("/login", data={"username": "jsmith", "password": "nope",
                                    "renew": "1"})
    assert "sign-in refused" in r.text
    assert client.get("/api/v1/me").json()["user"] == "jsmith"


# ------------------------------------------------------------------ sign-out

@pytest.mark.parametrize("path", ["/logout", "/logout-everywhere"])
def test_a_real_sign_out_lands_on_the_page_that_forgets_the_saved_list(client, path):
    _sign_in(client)
    # a tracked session's POST needs its CSRF token (auth.csrf_token)
    sid = auth.session_id_for(SECRET, client.cookies.get(auth.COOKIE_NAME))
    token = hmac.new(SECRET.encode(), b"csrf|" + sid.encode(), hashlib.sha256).hexdigest()
    r = client.post(path, headers={auth.CSRF_HEADER: token}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login?signed_out=1"
    page = client.get("/login?signed_out=1")
    assert "caches.delete('cards-landing')" in page.text
    # ...and only that page: a plain /login (an expired sign-in) does not
    assert "caches.delete" not in client.get("/login").text


def test_the_worker_never_deletes_the_saved_list_on_a_login_redirect():
    js = cards_landing.CARDS_SW
    assert "forgetPage" not in js
    assert ".delete(" not in js
    # the redirect arm exists and saves nothing
    assert "r.redirected && /\\/login/.test(r.url)" in js
    assert "nothing to save, nothing to forget" in js
