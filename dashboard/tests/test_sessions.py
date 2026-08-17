"""Server-side revocable sessions, the SQLite login throttle, CSRF and the
boot-time secret floor (COMMERCIAL_READINESS.md items 6/H1 and 15, 2026-08-17).

Everything here runs with DASH_DEV_INSECURE **off**, unlike the rest of the
suite: conftest sets it at import time so the other fifteen test modules can go
on hand-minting cookies and using `session_secret="test-secret"`, and these
tests are the ones that pin what a real deployment does instead. Every fixture
therefore deletes the variable BEFORE constructing Settings -- the flag is read
in Settings.__post_init__, not at create_app.
"""
from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth, db, sessions
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

# >= 24 chars, plenty of distinct characters: what broll.check_ingest_token
# demands, which is now the same rule DASH_SESSION_SECRET and
# DASH_REPORT_TOKEN are held to.
STRONG = "kX9-quiet-harbour-42-zephyr"
STRONG_TOKEN = "7mV-lantern-basalt-91-drift"


@pytest.fixture
def strict(monkeypatch):
    """A production-shaped environment: no dev flag anywhere."""
    monkeypatch.delenv("DASH_DEV_INSECURE", raising=False)
    yield


def _settings(tmp_path, name="s.db", **kwargs) -> Settings:
    return Settings(db_path=str(tmp_path / name), session_secret=STRONG,
                    admin_users=frozenset({"owen"}), **kwargs)


def _app(settings, verifier=None):
    app = create_app(settings)
    app.state.credential_verifier = verifier or (lambda s, u, p: p == "correct-horse")
    return app


def _login(client, user="jsmith", password="correct-horse"):
    resp = client.post("/login", data={"username": user, "password": password},
                       follow_redirects=False)
    assert resp.status_code == 303, resp.text
    return resp


def _csrf(client) -> str:
    page = client.get("/")
    assert page.status_code == 200
    match = re.search(r'<meta name="csrf" content="([0-9a-f]*)"', page.text)
    assert match, "base.html must publish the CSRF token"
    return match.group(1)


# ------------------------------------------------------------ the store

def test_store_round_trip_and_revocation(tmp_path):
    store = sessions.SessionStore(tmp_path / "st.db")
    store.ensure_schema()
    store.create("sid1", "JSmith", client="10.0.0.9 Firefox")
    assert store.validate("sid1") == "jsmith"
    assert store.list_for_user("jsmith")[0]["client"] == "10.0.0.9 Firefox"
    assert store.revoke("sid1", by="logout") == 1
    assert store.validate("sid1") is None
    # revoking twice is not an error and does not double-count
    assert store.revoke("sid1") == 0


def test_idle_and_absolute_lifetimes(tmp_path):
    store = sessions.SessionStore(tmp_path / "life.db", idle_seconds=100,
                                  absolute_seconds=1000)
    store.ensure_schema()
    store.create("sid", "jsmith", now="2026-08-17T00:00:00+00:00")
    # inside the idle window: valid, and last_seen slides
    assert store.validate("sid", now="2026-08-17T00:01:00+00:00") == "jsmith"
    # ...which is what makes an ACTIVE session outlive the idle window
    assert store.validate("sid", now="2026-08-17T00:02:30+00:00") == "jsmith"
    # a gap longer than the idle window ends it
    assert store.validate("sid", now="2026-08-17T00:10:00+00:00") is None

    store.create("sid2", "jsmith", now="2026-08-17T00:00:00+00:00")
    # ...and no amount of activity beats the absolute lifetime
    for minute in range(1, 17):
        store.validate("sid2", now=f"2026-08-17T00:{minute:02d}:00+00:00")
    assert store.validate("sid2", now="2026-08-17T00:17:00+00:00") is None


def test_revoke_user_and_log_out_everywhere_else(tmp_path):
    store = sessions.SessionStore(tmp_path / "many.db")
    store.ensure_schema()
    for sid in ("a", "b", "c"):
        store.create(sid, "jsmith")
    store.create("other", "editor2")
    assert store.revoke_user("jsmith", by="admin:owen", except_sid="b") == 2
    assert store.validate("a") is None and store.validate("c") is None
    assert store.validate("b") == "jsmith"          # the tab they are looking at
    assert store.validate("other") == "editor2"      # nobody else is touched


def test_throttle_counts_username_and_ip_separately_and_backs_off(tmp_path):
    store = sessions.SessionStore(tmp_path / "thr.db")
    store.ensure_schema()
    now = "2026-08-17T12:00:00+00:00"
    for _ in range(sessions.LOGIN_FAILURE_LIMIT):
        store.record_failure("jsmith", "10.0.0.9", now=now)
    assert store.throttled("jsmith", "10.0.0.9", now=now) > 0
    # the IP budget bites even for a username that has never failed -- which is
    # the whole point: spraying one password across every username used to be
    # unbounded (item 15).
    assert store.throttled("someone-else", "10.0.0.9", now=now) > 0
    # ...and a different host is unaffected
    assert store.throttled("someone-else", "10.0.0.10", now=now) == 0

    first = store.throttled("jsmith", "10.0.0.9", now=now)
    store.record_failure("jsmith", "10.0.0.9", now=now)
    assert store.throttled("jsmith", "10.0.0.9", now=now) > first   # exponential

    # a success clears both budgets
    store.clear_failures("jsmith", "10.0.0.9")
    assert store.throttled("jsmith", "10.0.0.9", now=now) == 0


def test_throttle_survives_a_restart(tmp_path):
    """The dict it replaced was in-process, so every deploy handed an attacker
    a fresh budget -- and the dashboard restarts on every deploy."""
    path = tmp_path / "restart.db"
    now = "2026-08-17T12:00:00+00:00"
    first = sessions.SessionStore(path)
    first.ensure_schema()
    for _ in range(sessions.LOGIN_FAILURE_LIMIT):
        first.record_failure("jsmith", "10.0.0.9", now=now)
    assert sessions.SessionStore(path).throttled("jsmith", "10.0.0.9", now=now) > 0


def test_failures_age_out_of_the_window(tmp_path):
    store = sessions.SessionStore(tmp_path / "age.db")
    store.ensure_schema()
    for _ in range(sessions.LOGIN_FAILURE_LIMIT):
        store.record_failure("jsmith", None, now="2026-08-17T00:00:00+00:00")
    # an editor who fat-fingers a password an hour apart is never throttled
    assert store.throttled("jsmith", None, now="2026-08-17T09:00:00+00:00") == 0


def test_prune_drops_only_what_can_never_be_used(tmp_path):
    store = sessions.SessionStore(tmp_path / "prune.db", absolute_seconds=60)
    store.ensure_schema()
    store.create("old", "jsmith", now="2026-08-01T00:00:00+00:00")
    store.create("new", "jsmith")
    store.prune()
    assert {r["sid"] for r in store.list_for_user("jsmith")} == {"new"}


# ------------------------------------------------------- end to end (strict)

def test_login_creates_a_revocable_session(strict, tmp_path):
    settings = _settings(tmp_path)
    app = _app(settings)
    with TestClient(app) as client:
        _login(client)
        assert client.get("/api/v1/me").json()["user"] == "jsmith"
        rows = app.state.session_store.list_for_user("jsmith")
        assert len(rows) == 1 and rows[0]["client"]
        # revoked out from under the browser -> the very next request is anonymous
        app.state.session_store.revoke_user("jsmith", by="admin:owen")
        assert client.get("/api/v1/me").json()["user"] is None
        assert client.get("/", follow_redirects=False).status_code == 303


def test_an_unknown_session_id_is_not_a_session(strict, tmp_path):
    """The whole point of the server-side row: a cookie this server signed but
    has no record of (revoked, expired, or minted before the deploy) is not a
    login. Without this, "log out everywhere" cannot mean anything."""
    settings = _settings(tmp_path, "unknown.db")
    with TestClient(_app(settings)) as client:
        client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(STRONG, "jsmith"))
        assert client.get("/api/v1/me").json()["user"] is None


def test_logout_revokes_rather_than_just_dropping_the_cookie(strict, tmp_path):
    settings = _settings(tmp_path, "lo.db")
    app = _app(settings)
    with TestClient(app) as client:
        _login(client)
        cookie = client.cookies[auth.COOKIE_NAME]
        token = _csrf(client)
        assert client.post("/logout", data={"csrf": token},
                           follow_redirects=False).status_code == 303
        # the stolen copy of the same cookie is dead too
        client.cookies.set(auth.COOKIE_NAME, cookie)
        assert client.get("/api/v1/me").json()["user"] is None


def test_logout_everywhere(strict, tmp_path):
    settings = _settings(tmp_path, "loa.db")
    app = _app(settings)
    with TestClient(app) as first, TestClient(app) as second:
        _login(first)
        _login(second)
        assert len(app.state.session_store.list_for_user("jsmith")) == 2
        token = _csrf(first)
        assert first.post("/logout-everywhere", data={"csrf": token},
                          follow_redirects=False).status_code == 303
        assert app.state.session_store.list_for_user("jsmith") == []
        assert second.get("/api/v1/me").json()["user"] is None


def test_admin_can_revoke_another_editors_sessions_from_the_users_page(strict, tmp_path):
    settings = _settings(tmp_path, "adm.db")
    app = _app(settings)
    with TestClient(app) as admin, TestClient(app) as editor:
        _login(admin, "owen")
        _login(editor, "jsmith")
        panel = admin.get("/partials/admin/sessions")
        assert panel.status_code == 200
        assert "jsmith" in panel.text and "[ REVOKE ALL ]" in panel.text
        resp = admin.post("/partials/admin/sessions/revoke",
                          data={"username": "jsmith"},
                          headers={"X-CSRF-Token": _csrf(admin)})
        assert resp.status_code == 200 and "revoked 1 session" in resp.text
        assert editor.get("/api/v1/me").json()["user"] is None
        # ...and the admin's own session is untouched
        assert admin.get("/api/v1/me").json()["user"] == "owen"


def test_the_json_twin_of_the_sessions_panel(strict, tmp_path):
    """Scriptable, and deliberately not a NAS call: revocation has to work
    while the NAS is unreachable, which is when an admin reaches for it."""
    settings = _settings(tmp_path, "jsonadm.db")
    app = _app(settings)
    with TestClient(app) as admin, TestClient(app) as editor:
        _login(admin, "owen")
        _login(editor, "jsmith")
        listed = admin.get("/api/v1/admin/sessions").json()["sessions"]
        assert {s["username"] for s in listed} == {"owen", "jsmith"}
        assert all(len(s["sid"]) == 12 for s in listed)      # prefix only
        resp = admin.post("/api/v1/admin/users/jsmith/sessions/revoke",
                          headers={"X-CSRF-Token": _csrf(admin)})
        assert resp.status_code == 200 and resp.json()["revoked"] == 1
        assert editor.get("/api/v1/me").json()["user"] is None
        # ...and it is CSRF-gated like every other cookie-authenticated write
        assert admin.post("/api/v1/admin/users/owen/sessions/revoke").status_code == 403


def test_a_non_admin_cannot_reach_the_revoke_route(strict, tmp_path):
    settings = _settings(tmp_path, "notadm.db")
    app = _app(settings)
    with TestClient(app) as client:
        _login(client, "jsmith")
        assert client.get("/partials/admin/sessions").status_code == 403
        assert client.post("/partials/admin/sessions/revoke",
                           data={"username": "owen"},
                           headers={"X-CSRF-Token": _csrf(client)}).status_code == 403


def test_login_throttle_is_generic_and_applies_to_the_html_form(strict, tmp_path):
    settings = _settings(tmp_path, "thr2.db")
    app = _app(settings)
    with TestClient(app) as client:
        for _ in range(sessions.LOGIN_FAILURE_LIMIT):
            page = client.post("/login", data={"username": "jsmith", "password": "no"})
            assert "sign-in refused" in page.text
        # even the RIGHT password now waits, and says the same thing -- a
        # throttle that answers differently is a username oracle
        page = client.post("/login", data={"username": "jsmith",
                                           "password": "correct-horse"})
        assert "sign-in refused" in page.text
        assert "too many" not in page.text.lower()


# ------------------------------------------------------------------- CSRF

def test_state_changing_posts_need_the_token(strict, tmp_path):
    settings = _settings(tmp_path, "csrf.db")
    with TestClient(_app(settings)) as client:
        _login(client)
        assert client.post("/logout", follow_redirects=False).status_code == 403
        assert client.post(
            "/logout", headers={"X-CSRF-Token": "0" * 64},
            follow_redirects=False).status_code == 403
        assert client.post(
            "/logout", headers={"X-CSRF-Token": _csrf(client)},
            follow_redirects=False).status_code == 303


def test_a_cross_site_origin_is_refused_even_with_a_token(strict, tmp_path):
    settings = _settings(tmp_path, "origin.db")
    with TestClient(_app(settings)) as client:
        _login(client)
        token = _csrf(client)
        resp = client.post("/logout", headers={"X-CSRF-Token": token,
                                               "Origin": "https://evil.example"},
                           follow_redirects=False)
        assert resp.status_code == 403


def test_the_token_travels_on_every_htmx_request_and_in_plain_forms(strict, tmp_path):
    settings = _settings(tmp_path, "tpl.db")
    with TestClient(_app(settings)) as client:
        _login(client)
        page = client.get("/")
        # <body hx-headers=...> is what puts it on every htmx call, including
        # partials swapped in later
        assert 'hx-headers=\'{"X-CSRF-Token": "' in page.text
        # ...and the logout form, which is NOT htmx, carries the hidden field
        assert '<input type="hidden" name="csrf"' in page.text
        # the mounted SPAs read it off the topbar they already inject
        topbar = client.get("/partials/topbar")
        assert "data-csrf=" in topbar.text and "data-dash-topbar" in topbar.text


def test_token_authed_routes_are_exempt(strict, tmp_path):
    """A companion has no session cookie and no page to read a token from."""
    settings = _settings(tmp_path, "exempt.db", report_token=STRONG_TOKEN)
    with TestClient(_app(settings)) as client:
        payload = {"editor_name": "jsmith", "machine": "PC",
                   "reported_at": "2026-08-17T10:00:00+00:00",
                   "lanes": [{"name": "lane_a_video_up", "state": "idle"}]}
        resp = client.post("/api/v1/report", json=payload, headers={
            "X-CCSync-Token": STRONG_TOKEN,
            "X-CCSync-Identity": auth.make_identity_token(STRONG, "jsmith")})
        assert resp.status_code == 200


# ------------------------------------------------------------ boot checks

@pytest.mark.parametrize("kwargs, fragment", [
    ({"session_secret": "REPLACE_ME"}, "DASH_SESSION_SECRET"),
    ({"session_secret": "short"}, "DASH_SESSION_SECRET"),
    ({"session_secret": STRONG, "report_token": "REPLACE_ME"}, "DASH_REPORT_TOKEN"),
    ({"session_secret": STRONG, "report_token": "aaaaaaaaaaaaaaaaaaaaaaaaaaaa"},
     "DASH_REPORT_TOKEN"),
])
def test_weak_secrets_refuse_to_boot(strict, tmp_path, kwargs, fragment):
    """The shipped compose sets both to REPLACE_ME and nothing checked
    (COMMERCIAL_READINESS.md item 15). Same rule as the ingest token, same
    refusal."""
    settings = Settings(db_path=str(tmp_path / "boot.db"), **kwargs)
    with pytest.raises(RuntimeError) as excinfo:
        create_app(settings)
    assert fragment in str(excinfo.value)


def test_no_secret_at_all_is_still_allowed(strict, tmp_path):
    """Login off entirely is a documented lab shape; what is refused is a
    secret that is PRESENT and weak."""
    create_app(Settings(db_path=str(tmp_path / "none.db")))


def test_the_dev_flag_is_the_only_bypass(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DEV_INSECURE", "1")
    settings = Settings(db_path=str(tmp_path / "dev.db"), session_secret="weak")
    assert settings.dev_insecure is True
    create_app(settings)


def test_report_token_optional_does_nothing_without_the_dev_flag(strict):
    """DASH_REPORT_TOKEN_OPTIONAL was one env var from unauthenticated writes
    to the fleet's status; it is no longer a shipped code path (item 15)."""
    assert Settings(report_token_optional=True).report_token_optional is False
    assert Settings(report_token_optional=True, dev_insecure=True).report_token_optional is True


def test_cookie_secure_1_without_a_tls_path_refuses_to_boot(strict, tmp_path):
    settings = Settings(db_path=str(tmp_path / "tls.db"), session_secret=STRONG,
                        cookie_secure="1", trusted_proxies="")
    with pytest.raises(RuntimeError) as excinfo:
        create_app(settings)
    assert "DASH_COOKIE_SECURE=1" in str(excinfo.value)
    # a site that publishes an https URL (Tailscale Serve) is a TLS path
    create_app(Settings(db_path=str(tmp_path / "tls2.db"), session_secret=STRONG,
                        cookie_secure="1", trusted_proxies="",
                        site_dashboard_url="https://nas.example.ts.net"))


def test_login_over_http_is_refused_when_secure_is_forced(strict, tmp_path):
    settings = Settings(db_path=str(tmp_path / "http.db"), session_secret=STRONG,
                        cookie_secure="1")
    with TestClient(_app(settings)) as client:
        # TestClient speaks http and is not a trusted proxy, so this IS the
        # "editor loops on the login page forever" case -- answered, not looped.
        assert client.get("/login").status_code == 400
        page = client.post("/login", data={"username": "jsmith",
                                           "password": "correct-horse"})
        assert "https only" in page.text


# -------------------------------------------------------- trusted proxies

def test_x_forwarded_proto_is_only_believed_from_a_trusted_peer(strict, tmp_path):
    """H1: X-Forwarded-Proto was trusted from anyone, so any host on the
    tailnet decided whether the Secure flag went on the session cookie."""
    settings = Settings(db_path=str(tmp_path / "prox.db"), session_secret=STRONG)
    with TestClient(_app(settings)) as client:
        # TestClient's peer is 'testclient', which parses as no IP at all
        resp = _login(client)
        assert "secure" not in resp.headers["set-cookie"].lower()
        resp = client.post("/login", data={"username": "jsmith", "password": "correct-horse"},
                           headers={"X-Forwarded-Proto": "https"}, follow_redirects=False)
        assert "secure" not in resp.headers["set-cookie"].lower()

    loopback = Settings(db_path=str(tmp_path / "prox2.db"), session_secret=STRONG)
    with TestClient(_app(loopback), client=("127.0.0.1", 5000)) as client:
        resp = client.post("/login", data={"username": "jsmith", "password": "correct-horse"},
                           headers={"X-Forwarded-Proto": "https"}, follow_redirects=False)
        assert "secure" in resp.headers["set-cookie"].lower()


def test_trusted_proxy_accepts_cidrs_and_ignores_junk():
    settings = Settings(trusted_proxies="172.17.0.0/16, not-an-ip, ::1")
    assert auth.trusted_proxy(settings, "172.17.0.1") is True
    assert auth.trusted_proxy(settings, "172.18.0.1") is False
    assert auth.trusted_proxy(settings, "::1") is True
    assert auth.trusted_proxy(settings, "testclient") is False
    assert auth.trusted_proxy(settings, None) is False
    # the default is loopback only
    assert auth.trusted_proxy(Settings(), "127.0.0.1") is True
    assert auth.trusted_proxy(Settings(), "10.0.0.9") is False


# --------------------------------------------------------- password floor

def test_password_floor_applies_to_new_passwords_only():
    assert auth.check_password("x" * auth.MIN_PASSWORD_CHARS) is None
    assert "at least" in auth.check_password("short")
    assert auth.MIN_PASSWORD_CHARS >= 12


def test_the_session_schema_is_additive(tmp_path):
    """It is created with CREATE TABLE IF NOT EXISTS beside db.py's numbered
    migrations, not as one of them, so it never collides with a schema change
    in flight -- and it must not disturb user_version."""
    conn = db.connect(tmp_path / "add.db")
    db.migrate(conn)
    before = conn.execute("PRAGMA user_version").fetchone()[0]
    sessions.SessionStore(tmp_path / "add.db").ensure_schema(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == before
    conn.close()
