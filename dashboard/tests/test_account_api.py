"""Account page 2026-09-25, group C: the /account page's JSON routes and the
services its partials call (docs/ACCOUNT_PAGE_FEATURES.md sections 3 and 7).

Every test signs in through /api/v1/login, so the session is TRACKED and the
CSRF gate is live exactly as in a deployment (hand-minted cookies skip it).
The apps run with DASH_DEV_INSECURE removed (test_sessions.py's `strict`
shape): under the dev flag a REVOKED cookie still signs in, which would make
every "that browser is signed out now" assertion here vacuous.
"""
from __future__ import annotations

import base64
import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import account_api, auth, db, local_users
from ccsync_dashboard.app import create_app
from ccsync_dashboard.nas import NasError
from ccsync_dashboard.settings import Settings

PASSWORD = "correct-horse-battery"
STRONG = "kX9-quiet-harbour-42-zephyr"   # passes the boot secret floor
EM_DASH = chr(0x2014)


def _key(seed: str, comment: str = "") -> str:
    body = base64.b64encode(("key-" + seed).encode() * 3).decode()
    return f"ssh-ed25519 {body} {comment}".strip()


def _settings(tmp_path, **kwargs) -> Settings:
    base = dict(db_path=str(tmp_path / "acct.db"), session_secret=STRONG,
                admin_users=frozenset({"owen"}))
    base.update(kwargs)
    return Settings(**base)


def _migrated(settings: Settings) -> Settings:
    conn = db.connect(settings.db_path)
    try:
        db.migrate(conn)
    finally:
        conn.close()
    return settings


@pytest.fixture
def strict(monkeypatch):
    monkeypatch.delenv("DASH_DEV_INSECURE", raising=False)
    yield


@pytest.fixture
def app(tmp_path, strict):
    application = create_app(_migrated(_settings(tmp_path)))
    application.state.credential_verifier = lambda s, u, p: p == PASSWORD
    return application


def _login(client: TestClient, user: str) -> str:
    resp = client.post("/api/v1/login", json={"username": user, "password": PASSWORD})
    assert resp.status_code == 200, resp.text
    return resp.json()["csrf"]


class Signed:
    """A signed-in browser: the client plus its CSRF header."""

    def __init__(self, app, user: str):
        self.client = TestClient(app)
        self.client.__enter__()
        self.user = user
        self.csrf = _login(self.client, user)

    @property
    def h(self) -> dict[str, str]:
        return {"X-CSRF-Token": self.csrf}

    def close(self):
        self.client.__exit__(None, None, None)


@pytest.fixture
def browsers(app):
    made: list[Signed] = []

    def make(user: str) -> Signed:
        s = Signed(app, user)
        made.append(s)
        return s

    yield make
    for s in made:
        s.close()


def _conn(app):
    return db.connect(app.state.settings.db_path)


def _seed_machine(app, editor: str, machine: str, *, state: bool = True,
                  caps: dict | None = None, cfg: dict | None = "default",
                  mode: str | None = None) -> None:
    now = db.utcnow_iso()
    conn = _conn(app)
    try:
        db.record_known_editor(conn, editor, "admin")
        db.upsert_machine(conn, editor, machine, now, platform="windows")
        if state:
            db.upsert_machine_state(conn, editor, machine, None, now, platform="windows",
                                    companion_version="0.9.80", mode=mode)
            db.store_machine_capabilities(conn, editor, machine, caps if caps is not None else {
                "jobs_enabled": True, "job_kinds": [], "gpu_present": True,
                "gpu_name": "RTX 4080", "gpu_vram_gb": 16, "idle_seconds": 300}, now)
            if cfg == "default":
                cfg = {"accepts": ["jobs_enabled", "jobs_kinds"],
                       "jobs_volunteer_minutes": 30, "drive_reminder_minutes": 30.0,
                       "pending_restart": {}}
            db.store_machine_settings(conn, editor, machine, cfg, now)
        conn.commit()
    finally:
        conn.close()


def _audit(app, action: str) -> list[dict[str, Any]]:
    conn = _conn(app)
    try:
        return db.fetch_audit(conn, actions=(action,))
    finally:
        conn.close()


# ------------------------------------------------------------ gate: 401, CSRF

WRITES = [
    ("put", "/api/v1/me/display-name", {"display_name": "X"}),
    ("put", "/api/v1/admin/users/jsmith/display-name", {"display_name": "X"}),
    ("post", "/api/v1/me/password", {"current_password": "a", "new_password": "b",
                                     "new_password_again": "b"}),
    ("post", "/api/v1/me/sessions/0123456789ab/revoke", None),
    ("post", "/api/v1/me/sessions/revoke-others", None),
    ("post", "/api/v1/machines/jsmith/JS-RIG/settings", {"jobs_enabled": False}),
    ("delete", "/api/v1/machines/jsmith/JS-RIG/settings", None),
]
READS = ["/api/v1/me/account", "/api/v1/me/sessions", "/api/v1/me/sync-keys"]


def test_every_route_needs_a_session(app):
    with TestClient(app) as client:
        for path in READS:
            assert client.get(path).status_code == 401, path
        for method, path, body in WRITES:
            kwargs = {"json": body} if body is not None else {}
            assert getattr(client, method)(path, **kwargs).status_code == 401, path


def test_every_write_needs_the_csrf_token(app, browsers):
    _seed_machine(app, "jsmith", "JS-RIG")
    admin = browsers("owen")
    second = browsers("owen")          # another of owen's browsers: must stay signed in
    before = admin.client.get("/api/v1/me/sessions").json()["sessions"]
    assert len(before) == 2
    for method, path, body in WRITES:
        kwargs = {"json": body} if body is not None else {}
        resp = getattr(admin.client, method)(path, **kwargs)
        assert resp.status_code == 403, (path, resp.status_code, resp.text)
        assert "CSRF" in resp.text
    # ...and nothing was written behind the refusal
    conn = _conn(app)
    try:
        assert db.get_display_name(conn, "jsmith") is None
        assert db.get_display_name(conn, "owen") is None      # the refused self PUT
        assert db.machine_settings_request(conn, "jsmith", "JS-RIG") is None
    finally:
        conn.close()
    # the refused sign-out calls signed nobody out
    assert second.client.get("/api/v1/me/account").status_code == 200
    after = admin.client.get("/api/v1/me/sessions").json()["sessions"]
    assert sorted(s["handle"] for s in after) == sorted(s["handle"] for s in before)
    assert _audit(app, db.AUDIT_ACCOUNT_SIGNOUT_OTHERS) == []
    assert _audit(app, db.AUDIT_ACCOUNT_SIGNOUT_ONE) == []


def test_no_new_path_is_open_or_csrf_exempt():
    from ccsync_dashboard import app as app_mod

    for _m, path, _b in WRITES:
        assert not app_mod._open_path(path, "POST")
        assert path not in app_mod._CSRF_EXEMPT_EXACT
        assert not path.startswith(app_mod._CSRF_EXEMPT_PREFIXES)
        assert app_mod._CSRF_EXEMPT_RE.match(path) is None
    for path in READS:
        assert not app_mod._open_path(path, "GET")


# ------------------------------------------------------------ the view (3.1)

def test_account_view_shape_and_as_is_ignored(app, browsers):
    _seed_machine(app, "jsmith", "JS-RIG")
    _seed_machine(app, "owen", "OWEN-RIG", mode="base")
    admin = browsers("owen")
    view = admin.client.get("/api/v1/me/account?as=jsmith").json()
    assert view["user"] == "owen"                # ?as= never changes whose page it is
    assert view["is_admin"] is True and view["admin_source"] == "admin_list"
    assert view["display_name"] is None and view["shown_as"] == "owen"
    assert view["auth_method"] == "smb"
    assert view["password"] == {"changeable": True, "where": "server",
                                "min_chars": auth.MIN_PASSWORD_CHARS, "oidc_host": None}
    assert view["csrf"] is None
    assert set(view["site"]) == {"canonical_prefix", "auto_update", "youtube_download",
                                 "fleet_halt"}
    assert [c["machine"] for c in view["computers"]] == ["OWEN-RIG"]
    assert view["computers"][0]["mode"] == "base"

    editor = browsers("jsmith")
    view = editor.client.get("/api/v1/me/account").json()
    assert view["is_admin"] is False and view["admin_source"] == ""
    assert view["account"] == {"suspended": False}
    (pc,) = view["computers"]
    assert pc["machine"] == "JS-RIG" and pc["platform"] == "windows"
    assert pc["companion_version"] == "0.9.80" and pc["live"] is True
    assert pc["jobs"]["enabled"] is True and pc["jobs"]["gpu"] == "RTX 4080, 16 GB"
    assert pc["settings"]["accepts"] == ["jobs_enabled", "jobs_kinds"]
    assert pc["settings"]["jobs_volunteer_minutes"] == 30
    assert pc["settings_request"] is None
    assert pc["can_request"] is True and pc["request_blocked"] == ""
    # sessions and sync keys have their own routes (a slow NAS never holds the page)
    assert "sessions" not in view and "keys" not in view


def test_account_view_suspended_and_older_companion(app, browsers):
    _seed_machine(app, "jsmith", "OLD-PC", cfg=None)       # no machine_settings section
    _seed_machine(app, "jsmith", "NEW-PC", state=False)    # registered, never reported
    conn = _conn(app)
    try:
        db.suspend_editor(conn, "jsmith", by="owen", reason="test")
        conn.commit()
    finally:
        conn.close()
    editor = browsers("jsmith")
    # Suspension turns a person's COMPUTERS away, not their browser: the page
    # must say it happened.
    view = editor.client.get("/api/v1/me/account").json()
    assert view["account"] == {"suspended": True}
    by_name = {c["machine"]: c for c in view["computers"]}
    old = by_name["OLD-PC"]
    assert old["settings"] is None                   # NULL = not reported, never a default
    assert old["can_request"] is False
    assert old["request_blocked"] == (
        "OLD-PC's CCSync is too old to change this from here. Update it, or change it "
        "in its tray: Settings, FLEET JOBS.")


def test_account_view_lists_a_lost_computer(app, browsers):
    """A registry row past LOST_MACHINE_DAYS with no machine_state row is the
    grid's LOST row; the page must list it too, never live, and never offer an
    ask (it has not reported)."""
    long_ago = "2020-01-01T00:00:00+00:00"
    conn = _conn(app)
    try:
        db.record_known_editor(conn, "jsmith", "admin")
        db.upsert_machine(conn, "jsmith", "OLD-LAPTOP", long_ago, platform="darwin")
        db.upsert_machine(conn, "rkim", "THEIR-LOST", long_ago, platform="windows")
        conn.commit()
    finally:
        conn.close()
    editor = browsers("jsmith")
    view = editor.client.get("/api/v1/me/account").json()
    (pc,) = view["computers"]                 # never another person's lost row
    assert pc["machine"] == "OLD-LAPTOP" and pc["lost"] is True
    assert pc["live"] is False and pc["can_request"] is False
    assert pc["request_blocked"] == "OLD-LAPTOP has not reported yet."
    assert pc["settings"] is None and pc["jobs"]["enabled"] is None


def test_account_view_oidc_password_facts(tmp_path):
    settings = _settings(tmp_path, auth_method="oidc",
                         oidc_issuer="https://login.example.com/tenant/abc")
    facts = account_api._password_facts(settings)
    assert facts == {"changeable": False, "where": "organisation",
                     "min_chars": auth.MIN_PASSWORD_CHARS, "oidc_host": "login.example.com"}
    facts = account_api._password_facts(_settings(tmp_path, auth_method="local"))
    assert facts["changeable"] is True and facts["where"] == "dashboard"


# ------------------------------------------------------- display names (3.2)

def test_set_and_clear_own_display_name(app, browsers):
    editor = browsers("jsmith")
    resp = editor.client.put("/api/v1/me/display-name", headers=editor.h,
                             json={"display_name": "  T.   Chen "})
    assert resp.status_code == 200, resp.text
    stored = resp.json()["display_name"]
    assert stored == "T. Chen"
    assert account_api.display_names_for(app)["jsmith"] == stored     # cache dropped
    view = editor.client.get("/api/v1/me/account").json()
    assert view["display_name"] == stored and view["shown_as"] == stored
    rows = _audit(app, db.AUDIT_ACCOUNT_DISPLAY_NAME)
    assert rows[0]["actor"] == "jsmith" and rows[0]["subject"] == "jsmith"
    assert rows[0]["detail"] == {"before": None, "after": stored}

    resp = editor.client.put("/api/v1/me/display-name", headers=editor.h,
                             json={"display_name": ""})
    assert resp.json() == {"ok": True, "display_name": None}
    assert "jsmith" not in account_api.display_names_for(app)
    assert _audit(app, db.AUDIT_ACCOUNT_DISPLAY_NAME)[0]["detail"] == {
        "before": stored, "after": None}


def test_display_name_nfc_on_the_way_in(app, browsers):
    editor = browsers("jsmith")
    decomposed = "Šimon"
    resp = editor.client.put("/api/v1/me/display-name", headers=editor.h,
                             json={"display_name": decomposed})
    assert resp.json()["display_name"] == "Šimon"


@pytest.mark.parametrize("text,status,detail", [
    ("   ", 422, "A name cannot be empty. To go back to your sign-in name, clear the box "
                "and save."),
    ("x" * 65, 422, "A name can be at most 64 characters."),
    ("Evil‮Name", 422, "A name cannot contain invisible or control characters."),
    ("Zero‍Width", 422, "A name cannot contain invisible or control characters."),
    ("Bell\x07", 422, "A name cannot contain invisible or control characters."),
    ("OWEN", 409, "Someone else already goes by that name. Pick another."),
])
def test_display_name_refusals(app, browsers, text, status, detail):
    editor = browsers("jsmith")
    resp = editor.client.put("/api/v1/me/display-name", headers=editor.h,
                             json={"display_name": text})
    assert resp.status_code == status, resp.text
    assert resp.json()["detail"] == detail
    assert EM_DASH not in resp.json()["detail"]


def test_display_name_cannot_copy_anothers_name_but_may_use_own_sign_in_name(app, browsers):
    other = browsers("rkim")
    assert other.client.put("/api/v1/me/display-name", headers=other.h,
                            json={"display_name": "Ruskin"}).status_code == 200
    editor = browsers("jsmith")
    resp = editor.client.put("/api/v1/me/display-name", headers=editor.h,
                             json={"display_name": "ruskin"})
    assert resp.status_code == 409
    resp = editor.client.put("/api/v1/me/display-name", headers=editor.h,
                             json={"display_name": "rkim"})      # another's sign-in name
    assert resp.status_code == 409
    resp = editor.client.put("/api/v1/me/display-name", headers=editor.h,
                             json={"display_name": "JSmith"})    # your own is fine
    assert resp.status_code == 200 and resp.json()["display_name"] == "JSmith"


def test_display_name_over_256_is_refused_before_normalising(app, browsers):
    editor = browsers("jsmith")
    resp = editor.client.put("/api/v1/me/display-name", headers=editor.h,
                             json={"display_name": "x" * 257})
    assert resp.status_code == 422


def test_admin_sets_and_clears_someone_elses_name(app, browsers):
    _seed_machine(app, "jsmith", "JS-RIG")
    admin = browsers("owen")
    resp = admin.client.put("/api/v1/admin/users/JSmith/display-name", headers=admin.h,
                            json={"display_name": "J. Smith"})
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"ok": True, "display_name": "J. Smith"}
    row = _audit(app, db.AUDIT_USER_DISPLAY_NAME)[0]
    assert row["actor"] == "owen" and row["subject"] == "jsmith"
    assert admin.client.put("/api/v1/admin/users/jsmith/display-name", headers=admin.h,
                            json={"display_name": ""}).json()["display_name"] is None
    resp = admin.client.put("/api/v1/admin/users/nobody/display-name", headers=admin.h,
                            json={"display_name": "Ghost"})
    assert resp.status_code == 404
    assert resp.json()["detail"] == "There is no account called nobody."


def test_an_editor_cannot_name_someone_else(app, browsers):
    _seed_machine(app, "rkim", "RK-PC")
    editor = browsers("jsmith")
    resp = editor.client.put("/api/v1/admin/users/rkim/display-name", headers=editor.h,
                             json={"display_name": "Mallory"})
    assert resp.status_code == 403
    # the self route is always the session user, whatever else is sent
    resp = editor.client.put("/api/v1/me/display-name?as=rkim", headers=editor.h,
                             json={"display_name": "Mallory", "username": "rkim"})
    assert resp.status_code == 200
    conn = _conn(app)
    try:
        assert db.get_display_name(conn, "rkim") is None
        assert db.get_display_name(conn, "jsmith") == "Mallory"
    finally:
        conn.close()


def test_admin_display_name_service_without_a_session_says_sign_in_first(app):
    """The middleware answers 401 before the route; account_ui calls the
    SERVICE, so the service's own wording is what a partial would show."""
    from fastapi import HTTPException
    from starlette.requests import Request

    request = Request({"type": "http", "app": app, "method": "PUT", "path": "/",
                       "headers": [], "query_string": b""})
    conn = _conn(app)
    try:
        with pytest.raises(HTTPException) as caught:
            account_api.set_user_display_name(request, conn, "jsmith", "X")
    finally:
        conn.close()
    assert caught.value.status_code == 401 and caught.value.detail == "Sign in first."


def test_display_name_cache_does_not_store_a_map_read_before_an_invalidate(app, monkeypatch):
    """A reader loads the OLD map, a write lands and invalidates, then the
    reader stores: it must not, or the new name is hidden for 30 s."""
    real = db.display_names

    def racing(conn):
        names = dict(real(conn))
        account_api.invalidate_display_names(app)      # the write, mid-read
        return names

    monkeypatch.setattr(account_api.db, "display_names", racing)
    account_api.invalidate_display_names(app)
    account_api.display_names_for(app)
    assert getattr(app.state, "display_names_cache", None) is None
    monkeypatch.setattr(account_api.db, "display_names", real)
    account_api.display_names_for(app)                # an undisturbed read is cached
    assert getattr(app.state, "display_names_cache", None) is not None


def test_display_name_cache_fails_open_and_shown_as(tmp_path):
    class _State:
        settings = _settings(tmp_path, db_path=str(tmp_path / "no" / "such" / "dir.db"))

    class _App:
        state = _State()

    assert account_api.display_names_for(_App()) == {}
    assert account_api.shown_as({"tchen": "T. Chen"}, "tchen") == "T. Chen"
    assert account_api.shown_as({"tchen": "T. Chen"}, "owen") == "owen"
    assert account_api.shown_as({}, None) == ""


# ---------------------------------------------------- signed-in browsers (3.4)

def test_list_and_revoke_own_sessions(app, browsers):
    here = browsers("jsmith")
    laptop = browsers("jsmith")
    stranger = browsers("rkim")
    listed = here.client.get("/api/v1/me/sessions").json()["sessions"]
    assert len(listed) == 2
    assert sum(1 for s in listed if s["current"]) == 1
    for s in listed:
        assert len(s["handle"]) == 12 and set(s) == {
            "handle", "ip", "browser", "created_at", "last_seen", "current"}
    mine = next(s for s in listed if s["current"])["handle"]
    other = next(s for s in listed if not s["current"])["handle"]

    resp = here.client.post(f"/api/v1/me/sessions/{mine}/revoke", headers=here.h)
    assert resp.status_code == 409
    assert resp.json()["detail"] == "That is this browser. Use Sign out instead."

    # another person's handle is invisible, never revoked
    theirs = stranger.client.get("/api/v1/me/sessions").json()["sessions"][0]["handle"]
    resp = here.client.post(f"/api/v1/me/sessions/{theirs}/revoke", headers=here.h)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "That browser is already signed out."
    assert stranger.client.get("/api/v1/me/account").status_code == 200

    resp = here.client.post(f"/api/v1/me/sessions/{other}/revoke", headers=here.h)
    assert resp.json() == {"ok": True, "revoked": 1}
    assert laptop.client.get("/api/v1/me/account").status_code == 401
    assert _audit(app, db.AUDIT_ACCOUNT_SIGNOUT_ONE)[0]["detail"] == {"handle": other}

    resp = here.client.post(f"/api/v1/me/sessions/{other}/revoke", headers=here.h)
    assert resp.status_code == 404

    resp = here.client.post("/api/v1/me/sessions/NOT-A-HANDLE/revoke", headers=here.h)
    assert resp.status_code == 422
    assert resp.json()["detail"] == "That is not a browser on this list."


def test_revoke_others_keeps_this_browser(app, browsers):
    here = browsers("jsmith")
    a = browsers("jsmith")
    b = browsers("jsmith")
    stranger = browsers("rkim")
    resp = here.client.post("/api/v1/me/sessions/revoke-others", headers=here.h)
    assert resp.json() == {"ok": True, "revoked": 2}
    assert here.client.get("/api/v1/me/account").status_code == 200
    assert a.client.get("/api/v1/me/account").status_code == 401
    assert b.client.get("/api/v1/me/account").status_code == 401
    assert stranger.client.get("/api/v1/me/account").status_code == 200
    row = _audit(app, db.AUDIT_ACCOUNT_SIGNOUT_OTHERS)[0]
    assert row["actor"] == "jsmith" and row["detail"] == {"revoked": 2}


def test_revoke_others_counts_only_live_browsers(app, browsers):
    here = browsers("jsmith")
    live = browsers("jsmith")
    stale = browsers("jsmith")
    listed = here.client.get("/api/v1/me/sessions").json()["sessions"]
    stale_handle = next(s["handle"] for s in listed
                        if not s["current"])
    conn = _conn(app)
    try:
        # past its idle lifetime, not yet swept (no request from it since)
        conn.execute("UPDATE auth_sessions SET last_seen=?, created_at=? WHERE sid LIKE ?",
                     ("2020-01-01T00:00:00+00:00", "2020-01-01T00:00:00+00:00",
                      stale_handle + "%"))
        conn.commit()
    finally:
        conn.close()
    shown = here.client.get("/api/v1/me/sessions").json()["sessions"]
    assert len(shown) == 2                             # this one + one live other
    resp = here.client.post("/api/v1/me/sessions/revoke-others", headers=here.h)
    assert resp.json() == {"ok": True, "revoked": 1}
    assert _audit(app, db.AUDIT_ACCOUNT_SIGNOUT_OTHERS)[0]["detail"] == {"revoked": 1}
    assert here.client.get("/api/v1/me/account").status_code == 200
    assert live.client.get("/api/v1/me/account").status_code == 401
    assert stale.client.get("/api/v1/me/account").status_code == 401


def test_sessions_not_recorded_is_503(app, browsers):
    here = browsers("jsmith")
    app.state.session_store = None   # dev: the hand-checked cookie still signs in
    resp = here.client.get("/api/v1/me/sessions")
    assert resp.status_code == 503
    assert resp.json()["detail"] == "Signed-in browsers are not being recorded on this server."


# ----------------------------------------------------------- sync keys (3.5)

class _StubNas:
    def __init__(self, sshpubkey: Any = None, error: bool = False):
        self.sshpubkey = sshpubkey
        self.error = error

    def find_user(self, username):
        if self.error:
            raise NasError("HTTP 500 secret backend detail")
        return {"username": username, "sshpubkey": self.sshpubkey}


def _use_nas(monkeypatch, nas):
    monkeypatch.setattr(account_api.nas_factory, "nas_configured", lambda s: True)
    monkeypatch.setattr(account_api.nas_factory, "make_nas_client", lambda s: nas)


def _pending(app, user, seed, machine):
    conn = _conn(app)
    try:
        text = _key(seed, f"{user}@{machine}")
        db.add_pending_ssh_key(conn, user, local_users.pubkey_fingerprint(text), text,
                               machine=machine)
        conn.commit()
        return text
    finally:
        conn.close()


def test_sync_keys_pending_and_truenas_approved(app, browsers, monkeypatch):
    approved = _key("rig", "jsmith@JS-RIG")
    fp = local_users.pubkey_fingerprint(approved)
    conn = _conn(app)
    try:
        db.audit(conn, "owen", "ssh_key.approve", "jsmith", {"fingerprint": fp,
                                                             "machine": "JS-RIG"})
        # a substring-matching subject (jsmith2) must not lend its machine
        db.audit(conn, "owen", "ssh_key.approve", "jsmith2", {"fingerprint": fp,
                                                              "machine": "WRONG"})
        conn.commit()
    finally:
        conn.close()
    waiting = _pending(app, "jsmith", "laptop", "JS-LAPTOP")
    _use_nas(monkeypatch, _StubNas(sshpubkey=f"# a comment\n{approved}\nnot-a-key\n"))
    editor = browsers("jsmith")
    body = editor.client.get("/api/v1/me/sync-keys").json()
    assert body["unreadable"] == "" and body["installed_unknown"] is False
    states = {k["state"]: k for k in body["keys"]}
    assert states["waiting"]["machine"] == "JS-LAPTOP"
    assert states["approved"]["fingerprint"] == fp
    assert states["approved"]["machine"] == "JS-RIG"
    assert states["approved"]["comment"] == "jsmith@JS-RIG"
    raw = json.dumps(body)
    assert waiting.split()[1] not in raw and approved.split()[1] not in raw
    assert "key_text" not in raw


def test_sync_keys_dsm_installed_marker(app, browsers, monkeypatch):
    _use_nas(monkeypatch, _StubNas(sshpubkey="(installed)"))
    editor = browsers("jsmith")
    body = editor.client.get("/api/v1/me/sync-keys").json()
    assert body["installed_unknown"] is True and body["keys"] == []


def test_sync_keys_nas_error_still_lists_the_waiting_half(app, browsers, monkeypatch, caplog):
    _pending(app, "jsmith", "laptop", "JS-LAPTOP")
    _use_nas(monkeypatch, _StubNas(error=True))
    editor = browsers("jsmith")
    body = editor.client.get("/api/v1/me/sync-keys").json()
    assert body["unreadable"] == ("The server could not be asked which keys are approved "
                                  "just now.")
    assert [k["state"] for k in body["keys"]] == ["waiting"]
    assert "secret backend detail" not in json.dumps(body)


def test_sync_keys_any_nas_failure_is_unreadable_not_500(app, browsers, monkeypatch):
    class _Broken:
        def find_user(self, username):
            raise TypeError("backend exploded with token=abc123")

    _pending(app, "jsmith", "laptop", "JS-LAPTOP")
    _use_nas(monkeypatch, _Broken())
    editor = browsers("jsmith")
    resp = editor.client.get("/api/v1/me/sync-keys")
    assert resp.status_code == 200
    body = resp.json()
    assert body["unreadable"] == account_api.KEYS_UNREADABLE
    assert [k["state"] for k in body["keys"]] == ["waiting"]
    assert "abc123" not in resp.text

    def cannot_build(settings):
        raise RuntimeError("no client")

    monkeypatch.setattr(account_api.nas_factory, "make_nas_client", cannot_build)
    assert editor.client.get("/api/v1/me/sync-keys").json()["unreadable"] == (
        account_api.KEYS_UNREADABLE)


def test_sync_keys_are_not_read_from_the_nas_on_oidc(tmp_path, monkeypatch):
    """Spec 3.5: the approved half comes from the NAS on `smb` only."""
    asked: list[str] = []

    class _Nas:
        def find_user(self, username):
            asked.append(username)
            return {"sshpubkey": _key("x", "someone")}

    monkeypatch.setattr(account_api.nas_factory, "nas_configured", lambda s: True)
    monkeypatch.setattr(account_api.nas_factory, "make_nas_client", lambda s: _Nas())
    settings = _settings(tmp_path, auth_method="oidc")
    conn = db.connect(settings.db_path)
    db.migrate(conn)
    try:
        view = account_api.build_sync_keys_view(settings, conn, "jsmith")
    finally:
        conn.close()
    assert asked == [] and view["keys"] == [] and view["unreadable"] == ""


def test_sync_keys_only_your_own(app, browsers, monkeypatch):
    _pending(app, "rkim", "theirs", "RK-PC")
    monkeypatch.setattr(account_api.nas_factory, "nas_configured", lambda s: False)
    editor = browsers("jsmith")
    body = editor.client.get("/api/v1/me/sync-keys?as=rkim").json()
    assert body["keys"] == [] and body["unreadable"] == ""


def test_sync_keys_local_and_needed(tmp_path):
    settings = _settings(tmp_path, auth_method="local")
    conn = db.connect(settings.db_path)
    db.migrate(conn)
    try:
        local_users.create_user(conn, "jsmith", "a-long-enough-pw", "editor")
        text = _key("local", "jsmith@JS-RIG")
        local_users.add_ssh_key(conn, "jsmith", text, label="JS-RIG")
        view = account_api.build_sync_keys_view(settings, conn, "jsmith")
        (key,) = view["keys"]
        assert key["state"] == "approved" and key["machine"] == "JS-RIG"
        assert key["fingerprint"] == local_users.pubkey_fingerprint(text)
        assert view["needed"] is True                 # no computers yet: the first one needs one
        now = db.utcnow_iso()
        db.upsert_machine(conn, "jsmith", "JS-RIG", now)
        db.upsert_machine_state(conn, "jsmith", "JS-RIG", None, now, mode="base")
        assert account_api.build_sync_keys_view(settings, conn, "jsmith")["needed"] is False
    finally:
        conn.close()


# ------------------------------------------- machine settings requests (3.6)

def _ask(s: Signed, body: Any, editor="jsmith", machine="JS-RIG"):
    return s.client.post(f"/api/v1/machines/{editor}/{machine}/settings",
                         headers=s.h, json=body)


def test_owner_asks_and_withdraws(app, browsers):
    _seed_machine(app, "jsmith", "JS-RIG")
    editor = browsers("jsmith")
    resp = _ask(editor, {"jobs_enabled": False})
    assert resp.status_code == 200, resp.text
    req = resp.json()["request"]
    assert req["settings"] == {"jobs_enabled": False} and req["state"] == "pending"
    assert req["requested_by"] == "jsmith"
    # a second ask MERGES under a new id
    resp = _ask(editor, {"jobs_kinds": ["peaks"]})
    merged = resp.json()["request"]
    assert merged["settings"] == {"jobs_enabled": False, "jobs_kinds": ["peaks"]}
    assert merged["request_id"] != req["request_id"]
    view = editor.client.get("/api/v1/me/account").json()
    assert view["computers"][0]["settings_request"]["state"] == "pending"

    resp = editor.client.delete("/api/v1/machines/jsmith/JS-RIG/settings", headers=editor.h)
    assert resp.status_code == 200 and resp.json()["ok"] is True
    conn = _conn(app)
    try:
        assert db.machine_settings_request(conn, "jsmith", "JS-RIG")["state"] == "withdrawn"
    finally:
        conn.close()


def test_an_editor_cannot_ask_someone_elses_computer_and_an_admin_can(app, browsers):
    _seed_machine(app, "rkim", "RK-PC")
    editor = browsers("jsmith")
    resp = _ask(editor, {"jobs_enabled": False}, editor="rkim", machine="RK-PC")
    assert resp.status_code == 403
    assert resp.json()["detail"] == ("Only the person this computer belongs to, or an "
                                     "admin, can change it.")
    resp = editor.client.delete("/api/v1/machines/rkim/RK-PC/settings", headers=editor.h)
    assert resp.status_code == 403
    admin = browsers("owen")
    resp = _ask(admin, {"jobs_enabled": False}, editor="rkim", machine="RK-PC")
    assert resp.status_code == 200
    assert resp.json()["request"]["requested_by"] == "owen"
    rows = _audit(app, db.AUDIT_MACHINE_SETTINGS_REQUEST)
    assert rows and rows[0]["actor"] == "owen"


@pytest.mark.parametrize("body,status,detail", [
    ({"mode": "base"}, 422, account_api.MACHINE_ONLY_THESE),
    ({"jobs_enabled": False, "mode": "editor"}, 422, account_api.MACHINE_ONLY_THESE),
    ({"jobs_volunteer_minutes": 10}, 422, account_api.MACHINE_ONLY_THESE),
    ({}, 422, account_api.MACHINE_ONLY_THESE),
    (["jobs_enabled"], 422, account_api.MACHINE_ONLY_THESE),
    ({"jobs_kinds": ["peaks", "mine-bitcoin"]}, 422, "mine-bitcoin is not a kind of fleet work."),
    ({"jobs_enabled": "no"}, 422, account_api.MACHINE_BAD_ENABLED),
    ({"jobs_kinds": "peaks"}, 422, account_api.MACHINE_BAD_KINDS),
    # [] is EVERY kind on the wire (4.8): a client meaning "none" must be told
    ({"jobs_kinds": []}, 422, ("That is the last kind of work this computer takes. "
                               "Untick Let the fleet use this computer instead.")),
    ({"jobs_enabled": True, "jobs_kinds": []}, 422, account_api.MACHINE_KINDS_EMPTY),
])
def test_machine_settings_whitelist(app, browsers, body, status, detail):
    _seed_machine(app, "jsmith", "JS-RIG")
    editor = browsers("jsmith")
    resp = _ask(editor, body)
    assert resp.status_code == status, resp.text
    assert resp.json()["detail"] == detail
    conn = _conn(app)
    try:
        assert db.machine_settings_request(conn, "jsmith", "JS-RIG") is None
    finally:
        conn.close()


def test_mode_is_never_requestable_whitelist():
    assert "mode" not in db.MACHINE_SETTING_KEYS


def test_every_kind_is_stored_as_empty(app, browsers):
    _seed_machine(app, "jsmith", "JS-RIG", caps={"jobs_enabled": True,
                                                  "job_kinds": ["peaks"]})
    editor = browsers("jsmith")
    resp = _ask(editor, {"jobs_kinds": list(db.JOB_KINDS) + ["peaks"]})
    assert resp.status_code == 200, resp.text
    assert resp.json()["request"]["settings"] == {"jobs_kinds": []}


def test_unknown_machine_is_404(app, browsers):
    _seed_machine(app, "jsmith", "JS-RIG")
    editor = browsers("jsmith")
    resp = _ask(editor, {"jobs_enabled": False}, machine="NOPE")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "jsmith has no computer called NOPE."


def test_too_old_and_not_reported_are_409(app, browsers):
    _seed_machine(app, "jsmith", "OLD-PC", cfg=None)
    _seed_machine(app, "jsmith", "SILENT", state=False)
    _seed_machine(app, "jsmith", "HALF", cfg={"accepts": ["jobs_enabled"]})
    editor = browsers("jsmith")
    resp = _ask(editor, {"jobs_enabled": False}, machine="OLD-PC")
    assert resp.status_code == 409
    assert resp.json()["detail"] == (
        "OLD-PC's CCSync is too old to change this from here. Update it, or change it "
        "in its tray: Settings, FLEET JOBS.")
    resp = _ask(editor, {"jobs_enabled": False}, machine="SILENT")
    assert resp.status_code == 409
    assert resp.json()["detail"] == "SILENT has not reported yet."
    # a companion that accepts only one key is refused the other (future/new skew)
    resp = _ask(editor, {"jobs_kinds": ["peaks"]}, machine="HALF")
    assert resp.status_code == 409
    assert _ask(editor, {"jobs_enabled": False}, machine="HALF").status_code == 200
    conn = _conn(app)
    try:
        assert db.machine_settings_request(conn, "jsmith", "OLD-PC") is None
        assert db.machine_settings_request(conn, "jsmith", "SILENT") is None
    finally:
        conn.close()


def test_unchanged_stores_nothing_unless_the_disk_differs(app, browsers):
    _seed_machine(app, "jsmith", "JS-RIG")          # running: enabled, every kind
    editor = browsers("jsmith")
    resp = _ask(editor, {"jobs_enabled": True, "jobs_kinds": list(db.JOB_KINDS)})
    assert resp.json() == {"ok": True, "unchanged": True}
    conn = _conn(app)
    try:
        assert db.machine_settings_request(conn, "jsmith", "JS-RIG") is None
    finally:
        conn.close()
    # config.toml already says something else (waiting on a restart): asking
    # for the running value IS a change
    _seed_machine(app, "jsmith", "JS-RIG", cfg={
        "accepts": ["jobs_enabled", "jobs_kinds"], "pending_restart": {"jobs_enabled": False}})
    resp = _ask(editor, {"jobs_enabled": True})
    assert resp.status_code == 200 and "request" in resp.json()


@pytest.mark.parametrize("caps,body", [
    # a newer companion running a kind this dashboard does not know: asking for
    # just the known one WOULD change it (skew: companion ahead)
    ({"jobs_enabled": True, "job_kinds": ["whisper", "some-future-kind"]},
     {"jobs_kinds": ["whisper"]}),
    ({"jobs_enabled": True, "job_kinds": ["some-future-kind"]},
     {"jobs_kinds": list(db.JOB_KINDS)}),
])
def test_unchanged_needs_a_running_value_it_can_read(app, browsers, caps, body):
    _seed_machine(app, "jsmith", "JS-RIG", caps=caps)
    editor = browsers("jsmith")
    resp = _ask(editor, body)
    assert resp.status_code == 200, resp.text
    assert "request" in resp.json(), resp.json()


def test_running_kinds_reads_cannot_tell_as_none():
    # A companion that never sent job_kinds is stored NULL and read back as []
    # (db._job_kinds_json: absent = every kind, the scheduler's own contract),
    # so [] is "every kind" here too; only an unknown or malformed list is None.
    assert account_api._running_kinds({"job_kinds": []}) == []
    assert account_api._running_kinds({"job_kinds": list(db.JOB_KINDS)}) == []
    assert account_api._running_kinds({"job_kinds": ["whisper", "peaks", "peaks"]}) == [
        "peaks", "whisper"]
    assert account_api._running_kinds({"job_kinds": ["whisper", "future"]}) is None
    assert account_api._running_kinds({"job_kinds": "whisper"}) is None
    assert account_api._running_kinds({}) is None


def test_unchanged_still_answered_for_a_known_subset(app, browsers):
    _seed_machine(app, "jsmith", "JS-RIG", caps={"jobs_enabled": True,
                                                  "job_kinds": ["peaks", "whisper"]})
    editor = browsers("jsmith")
    resp = _ask(editor, {"jobs_enabled": True, "jobs_kinds": ["whisper", "peaks"]})
    assert resp.json() == {"ok": True, "unchanged": True}


# --------------------------------------------------------- password (3.3)

@pytest.fixture
def local_app(tmp_path, strict):
    application = create_app(_migrated(_settings(tmp_path, auth_method="local")))
    return application


def test_password_change_rotates_this_browser_and_signs_out_others(local_app, browsers, caplog):
    conn = _conn(local_app)
    try:
        local_users.create_user(conn, "jsmith", "old-password-long", "editor")
        conn.commit()
    finally:
        conn.close()
    local_app.state.credential_verifier = None
    del local_app.state.credential_verifier

    def login(user, pw):
        s = TestClient(local_app)
        s.__enter__()
        r = s.post("/api/v1/login", json={"username": user, "password": pw})
        assert r.status_code == 200, r.text
        return s, r.json()["csrf"]

    here, token = login("jsmith", "old-password-long")
    other, _ = login("jsmith", "old-password-long")
    try:
        old_cookie = here.cookies.get(auth.COOKIE_NAME)
        body = {"current_password": "old-password-long", "new_password": "new-password-long",
                "new_password_again": "new-password-long"}
        resp = here.post("/api/v1/me/password", json=body, headers={"X-CSRF-Token": token})
        assert resp.status_code == 200, resp.text
        answer = resp.json()
        assert answer["ok"] is True and answer["method"] == "local"
        assert answer["other_sessions_signed_out"] == 1
        assert answer["csrf"] and answer["csrf"] != token
        assert here.cookies.get(auth.COOKIE_NAME) != old_cookie
        assert here.get("/api/v1/me/account").status_code == 200       # still signed in
        assert other.get("/api/v1/me/account").status_code == 401      # the other is out
        # the old page's token belonged to the rotated session
        assert here.put("/api/v1/me/display-name", json={"display_name": "J"},
                        headers={"X-CSRF-Token": token}).status_code == 403
        assert here.put("/api/v1/me/display-name", json={"display_name": "J"},
                        headers={"X-CSRF-Token": answer["csrf"]}).status_code == 200
        conn = _conn(local_app)
        try:
            assert local_users.verify_password(conn, "jsmith", "new-password-long")
        finally:
            conn.close()
        rows = _audit(local_app, db.AUDIT_ACCOUNT_PASSWORD)
        assert rows and "password-long" not in rows[0]["detail_json"]
        assert not any("password-long" in r.getMessage() for r in caplog.records)
    finally:
        here.__exit__(None, None, None)
        other.__exit__(None, None, None)


def test_password_change_refusals_are_http_codes(local_app):
    conn = _conn(local_app)
    try:
        local_users.create_user(conn, "jsmith", "old-password-long", "editor")
        conn.commit()
    finally:
        conn.close()
    with TestClient(local_app) as client:
        token = client.post("/api/v1/login", json={
            "username": "jsmith", "password": "old-password-long"}).json()["csrf"]
        h = {"X-CSRF-Token": token}
        resp = client.post("/api/v1/me/password", headers=h, json={
            "current_password": "old-password-long", "new_password": "a-new-password",
            "new_password_again": "a-different-one"})
        assert resp.status_code == 422
        assert resp.json()["detail"] == "The two new passwords are not the same. Nothing changed."
        resp = client.post("/api/v1/me/password", headers=h, json={
            "current_password": "wrong-wrong-wrong", "new_password": "a-new-password",
            "new_password_again": "a-new-password"})
        assert resp.status_code == 422
        assert "not your current password" in resp.json()["detail"]
        for detail in (resp.json()["detail"],):
            assert EM_DASH not in detail
        # keep guessing: the sign-in throttle takes over, with Retry-After
        last = None
        for _ in range(12):
            last = client.post("/api/v1/me/password", headers=h, json={
                "current_password": "wrong-wrong-wrong", "new_password": "a-new-password",
                "new_password_again": "a-new-password"})
            if last.status_code == 429:
                break
        assert last is not None and last.status_code == 429
        assert "retry-after" in {k.lower() for k in last.headers}


@pytest.mark.parametrize("field,value", [
    ("current_password", "S3cretTyped" * 100),        # 1100 characters
    ("new_password", "N3wTyped" * 200),
    ("new_password_again", ["L1stTyped"]),
    ("current_password", 12345678987654321),
])
def test_password_field_refusal_never_echoes_what_was_typed(app, browsers, field, value):
    editor = browsers("jsmith")
    body = {"current_password": "x", "new_password": "y", "new_password_again": "y"}
    body[field] = value
    resp = editor.client.post("/api/v1/me/password", headers=editor.h, json=body)
    assert resp.status_code == 422
    assert resp.json() == {"detail": account_api.PASSWORD_BAD_FIELD}
    typed = value[0] if isinstance(value, list) else str(value)
    assert typed[:9] not in resp.text
    assert "input" not in resp.json()


def test_password_body_that_is_not_an_object_is_one_sentence(app, browsers):
    editor = browsers("jsmith")
    resp = editor.client.post("/api/v1/me/password", headers=editor.h,
                              json=["S3cretTyped"])
    assert resp.status_code == 422
    assert resp.json() == {"detail": account_api.PASSWORD_BAD_FIELD}


def test_password_change_oidc_is_refused(app, browsers):
    editor = browsers("jsmith")
    object.__setattr__(app.state.settings, "auth_method", "oidc")
    resp = editor.client.post("/api/v1/me/password", headers=editor.h, json={
        "current_password": PASSWORD, "new_password": "new-password-long",
        "new_password_again": "new-password-long"})
    assert resp.status_code == 409
    assert "organisation" in resp.json()["detail"]


# ------------------------------------------------------------ the sentences

def test_no_em_dash_in_any_sentence():
    for name in dir(account_api):
        value = getattr(account_api, name)
        if name.isupper() and isinstance(value, str):
            assert EM_DASH not in value, name
