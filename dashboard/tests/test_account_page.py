"""Account page 2026-09-25, group F: the /account page, its htmx partials, and
the display name on the surfaces of docs/ACCOUNT_PAGE_FEATURES.md 6.2.

Every browser signs in through /api/v1/login so its session is TRACKED and
the CSRF gate is live, exactly as in a deployment, with DASH_DEV_INSECURE
removed (test_sessions.py's `strict` shape): under the dev flag a revoked
cookie still signs in, which would make "the other browser is out" vacuous.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import account_api, account_ui, auth, cards_landing, db, local_users
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

from conftest import HX

PASSWORD = "correct-horse-battery"
STRONG = "kX9-quiet-harbour-42-zephyr"   # passes the boot secret floor
EM_DASH = chr(0x2014)
# The page's own heading: "> YOUR ACCOUNT" (terminal look, no brackets).
YOUR_ACCOUNT_H1 = '<span class="prompt" aria-hidden="true">&gt;</span> YOUR ACCOUNT</span>'


def _settings(tmp_path, **kwargs) -> Settings:
    base = dict(db_path=str(tmp_path / "page.db"), session_secret=STRONG,
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


class Signed:
    def __init__(self, app, user: str, password: str = PASSWORD):
        self.client = TestClient(app)
        self.client.__enter__()
        self.user = user
        resp = self.client.post("/api/v1/login", json={"username": user, "password": password})
        assert resp.status_code == 200, resp.text
        self.csrf = resp.json()["csrf"]

    @property
    def h(self) -> dict[str, str]:
        # X-CC-UI rides every htmx call a page makes (shell.html's
        # hx-headers); without it app.stale_page_gate answers HX-Refresh.
        return {"X-CSRF-Token": self.csrf, **HX}

    def close(self):
        self.client.__exit__(None, None, None)


@pytest.fixture
def browsers(app):
    made: list[Signed] = []

    def make(user: str, application=None, password: str = PASSWORD) -> Signed:
        s = Signed(application or app, user, password)
        made.append(s)
        return s

    yield make
    for s in made:
        s.close()


def _conn(app):
    return db.connect(app.state.settings.db_path)


def _seed_machine(app, editor: str, machine: str, *, caps: dict | None = None,
                  cfg: Any = "default", mode: str | None = None) -> None:
    now = db.utcnow_iso()
    conn = _conn(app)
    try:
        db.record_known_editor(conn, editor, "admin")
        db.upsert_machine(conn, editor, machine, now, platform="windows")
        db.upsert_machine_state(conn, editor, machine, None, now, platform="windows",
                                companion_version="0.9.80", mode=mode)
        db.store_machine_capabilities(conn, editor, machine, caps if caps is not None else {
            "jobs_enabled": True, "job_kinds": [], "gpu_present": True,
            "gpu_name": "RTX 4080", "gpu_vram_gb": 16, "idle_seconds": 300}, now)
        if cfg == "default":
            cfg = {"accepts": ["jobs_enabled", "jobs_kinds"],
                   "jobs_volunteer_minutes": 30, "drive_reminder_minutes": 30.0,
                   "pending_restart": {}}
        if cfg is not None:
            db.store_machine_settings(conn, editor, machine, cfg, now)
        conn.commit()
    finally:
        conn.close()


def _project(app, slug: str, label: str) -> None:
    now = db.utcnow_iso()
    conn = _conn(app)
    try:
        conn.execute("INSERT OR IGNORE INTO projects (slug, label, path, first_seen, last_seen, active)"
                     " VALUES (?, ?, ?, ?, ?, 1)", (slug, label, "/mnt/" + label, now, now))
        conn.commit()
    finally:
        conn.close()


def _set_name(app, user: str, name: str) -> None:
    conn = _conn(app)
    try:
        db.set_display_name(conn, user, name, by=user, now=db.utcnow_iso())
        conn.commit()
    finally:
        conn.close()
    account_api.invalidate_display_names(app)


class _Tree(HTMLParser):
    """Records, for every element with an id, whether an ancestor polls."""

    VOID = {"input", "br", "img", "meta", "link", "hr", "col", "source", "wbr"}

    def __init__(self):
        super().__init__()
        self.stack: list[bool] = []
        self.polled_ids: dict[str, bool] = {}

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        inside = any(self.stack)
        if a.get("id"):
            self.polled_ids[a["id"]] = inside
        if tag in self.VOID:
            return
        self.stack.append("every " in (a.get("hx-trigger") or ""))

    def handle_endtag(self, tag):
        if tag in self.VOID:
            return
        if self.stack:
            self.stack.pop()


def _polled(html: str) -> dict[str, bool]:
    tree = _Tree()
    tree.feed(html)
    return tree.polled_ids


# ------------------------------------------------------------------ the page

def test_account_needs_a_session(app):
    with TestClient(app) as client:
        resp = client.get("/account", follow_redirects=False)
        assert resp.status_code in (303, 307, 401), resp.status_code
        for path in ("/partials/account/sessions", "/partials/account/sync-keys",
                     "/partials/account/computer?machine=X"):
            assert client.get(path, follow_redirects=False).status_code in (303, 307, 401), path


def test_page_renders_for_an_editor_with_every_panel(app, browsers):
    _seed_machine(app, "jsmith", "JS-RIG")
    ed = browsers("jsmith")
    resp = ed.client.get("/account")
    assert resp.status_code == 200, resp.text
    html = resp.text
    for marker in (YOUR_ACCOUNT_H1, 'id="account-you"', 'id="account-password"',
                   '<h2 class="sec">your computers', '<h2 class="sec">your wired computers',
                   'id="account-settings"',
                   'id="account-sessions-wrap"', "JS-RIG", "fleet jobs",
                   'hx-get="/partials/account/sync-keys"', 'autocomplete="current-password"',
                   'autocomplete="new-password"'):
        assert marker in html, marker
    assert "This page is about <b>you</b> only" not in html
    assert "/admin/users" not in html.split('id="account-you"')[0].split(YOUR_ACCOUNT_H1)[1]
    assert "/partials/admin/machines/update" not in html
    assert "/partials/admin/machines/ask-why" not in html
    assert '<span class="t">Update now</span>' not in html
    assert '<span class="t">Ask this computer why</span>' not in html
    # the computer's F5 controls are there (owner, accepts reported)
    assert 'name="jobs_enabled"' in html and 'name="jobs_kinds"' in html
    assert 'name="mode"' not in html                       # CR-88: never requestable


def test_page_renders_for_an_admin_with_the_note_and_admin_buttons(app, browsers):
    _seed_machine(app, "owen", "OWEN-RIG", mode="base")
    admin = browsers("owen")
    html = admin.client.get("/account").text
    assert "This page is about <b>you</b> only" in html
    assert 'href="/admin/users"><span class="t">Settings, Users</span>' in html
    assert '<span class="t">Ask this computer why</span>' in html
    assert 'hx-post="/partials/admin/machines/ask-why?view=none"' in html
    assert "OWEN-RIG" in html and "wired to the server" in html


def test_as_is_ignored_on_the_page(app, browsers):
    _seed_machine(app, "jsmith", "JS-RIG")
    admin = browsers("owen")
    html = admin.client.get("/account?as=jsmith").text
    assert "signed in as <b>owen</b>" in html
    assert "JS-RIG" not in html


def test_the_password_and_you_panels_are_never_polled(app, browsers):
    _seed_machine(app, "jsmith", "JS-RIG")
    ed = browsers("jsmith")
    ids = _polled(ed.client.get("/account").text)
    for key in ("account-password", "account-pw-form", "account-pw0", "account-pw1",
                "account-pw2", "account-pw-result", "account-you", "account-name-in"):
        assert key in ids, key
        assert ids[key] is False, f"{key} sits inside a polling element"
    # ...while the computers and the browsers list DO refresh themselves
    html = ed.client.get("/account").text
    # Each computer window's frame stays put; a hidden poll inside it asks
    # its own route and takes only that window's body (hx-select-oob).
    m = re.search(r'id="(pc-[0-9a-f]{12})".*?<div class="ev-poll"[^>]*?'
                  r'hx-get="/partials/account/computer\?machine=JS-RIG"[^>]*?'
                  r'hx-trigger="every 30s[^"]*"[^>]*?hx-select-oob="#(pc-[0-9a-f]{12})-body',
                  html, re.S)
    assert m and m.group(1) == m.group(2)
    assert 'hx-get="/partials/account/sessions"' in html


def test_oidc_shows_no_password_form(app, browsers):
    ed = browsers("jsmith")
    object.__setattr__(app.state.settings, "auth_method", "oidc")
    object.__setattr__(app.state.settings, "oidc_issuer", "https://login.example.org/t/1")
    html = ed.client.get("/account").text
    assert "No password here" in html
    assert 'id="account-pw-form"' not in html and 'name="current_password"' not in html
    assert "login.example.org" in html and "/t/1" not in html
    assert "emergency sign-in" not in html                  # admins only
    admin = browsers("owen")
    assert "emergency sign-in" in admin.client.get("/account").text


@pytest.mark.parametrize("query,expect", [
    ("changed=password&others=2", "Signed out 2 other browsers"),
    ("changed=password&others=1", "Signed out 1 other browser;"),
    ("changed=password&others=0", "No other browser was signed in"),
    ("changed=password&others=99999999", "Signed out 999 other browsers"),
])
def test_changed_line(app, browsers, query, expect):
    ed = browsers("jsmith")
    assert expect in ed.client.get(f"/account?{query}").text


@pytest.mark.parametrize("query", [
    "changed=%3Cb%3Ex&others=2",
    "changed=Password&others=2",
])
def test_changed_line_renders_nothing_for_another_word(app, browsers, query):
    ed = browsers("jsmith")
    html = ed.client.get(f"/account?{query}").text
    assert "Password changed." not in html
    assert "<b>x" not in html


# Review round (account page 2026-09-25): a change with no count (B answers
# None when the server keeps no session store or the sign-out failed) must
# still confirm the change, and say the other browsers may still be in.
@pytest.mark.parametrize("query", [
    "changed=password",
    "changed=password&others=",
    "changed=password&others=abc",
    "changed=password&others=%3Cscript%3Ealert(1)%3C%2Fscript%3E",
])
def test_changed_line_without_a_count_still_confirms(app, browsers, query):
    ed = browsers("jsmith")
    html = ed.client.get(f"/account?{query}").text
    assert "Password changed." in html
    assert "Your other browsers may still be signed in" in html
    assert "No other browser was signed in" not in html
    note = html.split("Password changed.")[1].split("</div>")[0]
    assert "Signed out" not in note
    assert "<script>alert" not in html


def test_changed_line_negative_is_clamped(app, browsers):
    ed = browsers("jsmith")
    assert "No other browser was signed in" in ed.client.get(
        "/account?changed=password&others=-5").text


def test_empty_states(app, browsers):
    ed = browsers("jsmith")
    html = ed.client.get("/account").text
    assert "No remote computers have reported in as jsmith" in html
    assert 'href="/download"' in html
    assert "No computers wired to the server." in html


# --------------------------------------------------------- display name (F1)

def test_display_name_partial_saves_and_refuses_in_the_panel(app, browsers):
    ed = browsers("jsmith")
    resp = ed.client.post("/partials/account/display-name", data={"display_name": "J. Smith"},
                          headers=ed.h)
    assert resp.status_code == 200
    assert "Other people now see J. Smith" in resp.text
    assert 'id="account-you"' in resp.text
    # taken: another person's sign-in name is a 200 with the sentence
    _seed_machine(app, "owen", "OWEN-RIG")
    resp = ed.client.post("/partials/account/display-name", data={"display_name": "OWEN"},
                          headers=ed.h)
    assert resp.status_code == 200
    assert "Someone else already goes by that name. Pick another." in resp.text
    assert 'value="OWEN"' in resp.text                      # what was typed is kept
    resp = ed.client.post("/partials/account/display-name",
                          data={"display_name": "a" + chr(0x202E) + "b"}, headers=ed.h)
    assert "A name cannot contain invisible or control characters." in resp.text
    resp = ed.client.post("/partials/account/display-name", data={"display_name": "x" * 65},
                          headers=ed.h)
    assert "A name can be at most 64 characters." in resp.text
    # clear
    resp = ed.client.post("/partials/account/display-name", data={"display_name": ""},
                          headers=ed.h)
    assert "Cleared." in resp.text
    for text in (resp.text,):
        assert EM_DASH not in text


def test_display_name_partial_needs_csrf_and_session(app, browsers):
    with TestClient(app) as anon:
        resp = anon.post("/partials/account/display-name", data={"display_name": "X"},
                         follow_redirects=False)
        assert resp.status_code in (303, 307, 401, 403)
    ed = browsers("jsmith")
    resp = ed.client.post("/partials/account/display-name", data={"display_name": "X"})
    assert resp.status_code == 403
    conn = _conn(app)
    try:
        assert db.get_display_name(conn, "jsmith") is None
    finally:
        conn.close()


def test_admin_display_name_partial_asks_the_nas_off_the_event_loop(app, browsers,
                                                                    monkeypatch):
    """Review round (account page 2026-09-25): build_admin_users_view asks
    the NAS, so the route must run it in the threadpool, never inline on the
    event loop (section 0)."""
    import asyncio

    from ccsync_dashboard import api as api_mod
    seen: list[bool] = []
    real = api_mod.build_admin_users_view

    def spy(*a, **kw):
        try:
            asyncio.get_running_loop()
            seen.append(True)       # called on the event loop's thread
        except RuntimeError:
            seen.append(False)      # a worker thread: what we want
        return real(*a, **kw)

    monkeypatch.setattr(api_mod, "build_admin_users_view", spy)
    admin = browsers("owen")
    resp = admin.client.post("/partials/admin/users/display-name",
                             data={"username": "jsmith", "display_name": "J. Smith"},
                             headers=admin.h)
    assert resp.status_code == 200, resp.text
    assert seen == [False]


def test_add_options_capacity_sentence_matches_the_tick_helper(app):
    """Review round (account page 2026-09-25): _add_options batches the
    figures (one proxy map, one free-space read) instead of two queries per
    project, and must still print the SAME sentence the tick helper does."""
    from ccsync_dashboard.api import tick_capacity_warning
    _seed_machine(app, "jsmith", "JS-RIG")
    _project(app, "big", "2026/FF5/Big")
    _project(app, "small", "2026/FF5/Small")
    _project(app, "unwalked", "2026/FF5/Unwalked")
    now = db.utcnow_iso()
    conn = _conn(app)
    try:
        for slug, size in (("big", 900 * 10**9), ("small", 1 * 10**9)):
            pid = conn.execute("SELECT id FROM projects WHERE slug=?", (slug,)).fetchone()["id"]
            conn.execute("INSERT OR REPLACE INTO nas_inventory_state (project_id, bytes_proxies,"
                         " walked_at) VALUES (?, ?, ?)", (pid, size, now))
        conn.execute("UPDATE machine_state SET disk_root_free_bytes=?, disk_at=?"
                     " WHERE editor_username=? AND machine=?",
                     (100 * 10**9, now, "jsmith", "JS-RIG"))
        conn.commit()
        opts = {o["slug"]: o["warning"] for o in account_ui._add_options(
            conn, "jsmith", {"machine": "JS-RIG", "plan": []})}
        for slug in ("big", "small", "unwalked"):
            assert opts[slug] == (tick_capacity_warning(conn, "jsmith", slug, "JS-RIG") or "")
        assert opts["big"]                  # the tight one does get a sentence
        assert opts["unwalked"] == ""       # never read as 0 GB
    finally:
        conn.close()


def test_admin_display_name_partial(app, browsers):
    _seed_machine(app, "jsmith", "JS-RIG")
    ed = browsers("jsmith")
    resp = ed.client.post("/partials/admin/users/display-name",
                          data={"username": "owen", "display_name": "Boss"}, headers=ed.h)
    assert resp.status_code == 403
    admin = browsers("owen")
    resp = admin.client.post("/partials/admin/users/display-name",
                             data={"username": "jsmith", "display_name": "J. Smith"},
                             headers=admin.h)
    assert resp.status_code == 200
    assert "jsmith is now shown as J. Smith" in resp.text
    resp = admin.client.post("/partials/admin/users/display-name",
                             data={"username": "nobody-here", "display_name": "X"},
                             headers=admin.h)
    assert resp.status_code == 200
    assert "There is no account called nobody-here." in resp.text
    conn = _conn(app)
    try:
        assert db.get_display_name(conn, "jsmith") == "J. Smith"
        rows = db.fetch_audit(conn, actions=(db.AUDIT_USER_DISPLAY_NAME,))
        assert rows and rows[0]["actor"] == "owen" and rows[0]["subject"] == "jsmith"
    finally:
        conn.close()


# ------------------------------------------- where the display name shows (6.2)

def test_topbar_shows_the_name_and_links_to_account(app, browsers):
    _set_name(app, "jsmith", "J. Smith")
    ed = browsers("jsmith")
    html = ed.client.get("/account").text
    assert 'href="/account" title="signed in as jsmith">J. Smith' in html
    assert YOUR_ACCOUNT_H1 in html
    # the topbar the SPAs fetch renders through the same context
    top = ed.client.get("/partials/topbar").text
    assert 'title="signed in as jsmith">J. Smith' in top


def test_topbar_without_a_name_shows_the_sign_in_name(app, browsers):
    ed = browsers("jsmith")
    top = ed.client.get("/partials/topbar").text
    assert 'title="signed in as jsmith">jsmith' in top


def test_fleet_grid_shows_name_with_sign_in_name_muted(app, browsers):
    _seed_machine(app, "jsmith", "JS-RIG")
    _set_name(app, "jsmith", "J. Smith")
    admin = browsers("owen")
    html = admin.client.get("/partials/fleet").text
    assert 'title="signed in as jsmith">J. Smith' in html
    # the sign-in name rides muted (the <small>) beside the shown name
    assert '<small title="signed in as jsmith">J. Smith (jsmith)</small>' in html


def test_audit_and_plan_changes_show_the_name(app, browsers):
    _seed_machine(app, "jsmith", "JS-RIG")
    _project(app, "p1", "2026/P1")
    _set_name(app, "jsmith", "J. Smith")
    ed = browsers("jsmith")
    conn = _conn(app)
    try:
        db.audit(conn, "jsmith", "plan.tick", "jsmith",
                 {"slug": "p1", "editor": "jsmith", "machine": "JS-RIG", "scope": "machine",
                  "before": [], "after": []})
        conn.commit()
    finally:
        conn.close()
    admin = browsers("owen")
    audit = admin.client.get("/partials/admin/audit").text
    assert 'data-label="who" title="jsmith"><b>J. Smith</b></td>' in audit
    plan = admin.client.get("/partials/plan-changes").text
    assert 'id="plan-changes"' in plan
    assert 'data-label="who" title="jsmith"><b>J. Smith</b></td>' in plan          # WHO
    assert ('data-label="editor" title="jsmith">J. Smith</td>'
            in plan.split('<span class="w">ticked</span>')[1])                      # EDITOR


def test_users_page_has_the_shown_as_column(tmp_path, strict, browsers):
    application = create_app(_migrated(_settings(tmp_path, auth_method="local")))
    conn = _conn(application)
    try:
        local_users.create_user(conn, "owen", "owen-password-long", "admin")
        local_users.create_user(conn, "jsmith", "js-password-long", "editor")
        conn.commit()
    finally:
        conn.close()
    _set_name(application, "jsmith", "J. Smith")
    admin = browsers("owen", application, "owen-password-long")
    html = admin.client.get("/admin/users").text
    assert ">shown as</th>" in html
    assert 'hx-post="/partials/admin/users/display-name"' in html
    assert 'value="J. Smith"' in html


def test_shown_as_filter_falls_back_to_the_value():
    from ccsync_dashboard import ui

    env = ui.templates.env
    tpl = env.from_string("{{ who | shown_as }}")
    assert tpl.render(who="jsmith", display_names={"jsmith": "J. Smith"}) == "J. Smith"
    assert tpl.render(who="owen", display_names={"jsmith": "J. Smith"}) == "owen"
    assert tpl.render(who="companion") == "companion"      # no map at all
    assert tpl.render(who=None, display_names={}) == ""


def test_cards_landing_phrases_use_display_names(monkeypatch):
    monkeypatch.setattr(account_api, "display_names_for",
                        lambda app: {"jsmith": "J. Smith", "tricky": "You"})
    now = 1_000_000.0
    row: dict[str, Any] = {"slug": "s1", "mtime": None}
    cards_landing._catalogue_row(row, [], 0, {}, {"s1": {"by": "jsmith", "at": now - 120}},
                                 {}, now, "owen", {"jsmith": "J. Smith"})
    assert row["opened_phrase"].startswith("J. Smith opened it")
    assert row["opened_by"] == "jsmith"
    row = {"slug": "s1", "mtime": None}
    cards_landing._catalogue_row(row, [], 0, {}, {"s1": {"by": "tricky", "at": now - 120}},
                                 {}, now, "owen", {"tricky": "You"})
    # a name spelt like the phrase's own word cannot pass as the reader
    assert row["opened_phrase"].startswith("tricky opened it")

    class Entry:
        slug = "s1"

        def as_dict(self):
            return {"slug": "s1", "state": "ready", "occupants": ["jsmith"],
                    "last_in": "jsmith", "last_in_seconds": 30.0}

        def last_in_other_than(self, me):
            return ("jsmith", 30.0)

    class Pool:
        cap = 2

        def entries(self):
            return [Entry()]

        def get(self, slug):
            return Entry()

        def may_close(self, slug, me, admin):
            return None

    monkeypatch.setattr(cards_landing, "_episodes", lambda request: [
        {"slug": "s1", "name": "Ep", "root": ""}])
    monkeypatch.setattr(cards_landing, "_catalogue", lambda *a, **k: None)
    monkeypatch.setattr(auth, "get_session_user", lambda request: "owen")
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        cards_pool=Pool(), settings=SimpleNamespace(admin_users=frozenset({"owen"})))))
    monkeypatch.setattr(auth, "is_admin", lambda *a, **k: True)
    state = cards_landing._state(request)
    ep = state["episodes"][0]
    assert ep["occupants"] == ["jsmith"]                   # the key stays a key
    assert ep["occupants_shown"] == ["J. Smith"]
    assert ep["last_in_phrase"] == "J. Smith is in it now"
    assert "J. Smith is in it now" in ep["close_prompt"]


# ------------------------------------------------------ signed-in browsers (F3)

def test_sessions_panel_and_sign_out_others(app, browsers):
    here = browsers("jsmith")
    browsers("jsmith")
    browsers("owen")
    html = here.client.get("/partials/account/sessions").text
    assert html.count(">this browser</span>") == 1
    assert html.count('<span class="t">Sign out</span>') == 1   # the other one, never this one
    assert '<span class="t">Sign out the others</span>' in html
    assert '<span class="t">Sign out everywhere</span>' in html
    assert 'action="/logout-everywhere"' in html
    # no full session id anywhere
    handles = re.findall(r'name="handle" value="([^"]+)"', html)
    assert handles and all(re.fullmatch(r"[0-9a-f]{12}", h) for h in handles)
    resp = here.client.post("/partials/account/sessions/revoke-others", headers=here.h)
    assert resp.status_code == 200
    assert "Signed out 1 other browser." in resp.text
    assert "Only this browser is signed in." in resp.text


def test_sessions_revoke_one_and_the_refusals(app, browsers):
    here = browsers("jsmith")
    other = browsers("jsmith")
    html = here.client.get("/partials/account/sessions").text
    handle = re.findall(r'name="handle" value="([^"]+)"', html)[0]
    resp = here.client.post("/partials/account/sessions/revoke", data={"handle": "nothex"},
                            headers=here.h)
    assert resp.status_code == 200 and "That is not a browser on this list." in resp.text
    resp = here.client.post("/partials/account/sessions/revoke", data={"handle": handle},
                            headers=here.h)
    assert resp.status_code == 200 and "Signed that browser out." in resp.text
    assert other.client.get("/api/v1/me/account").status_code == 401
    resp = here.client.post("/partials/account/sessions/revoke", data={"handle": handle},
                            headers=here.h)
    assert "That browser is already signed out." in resp.text
    rows = here.client.post("/partials/account/sessions/revoke", data={"handle": handle})
    assert rows.status_code == 403                         # CSRF


# ------------------------------------------------------------ sync keys (F4)

def test_sync_keys_partial(app, browsers):
    ed = browsers("jsmith")
    html = ed.client.get("/partials/account/sync-keys").text
    assert "none yet" in html
    assert "not with your password" in html


# ------------------------------------------------------------- password (F2)

@pytest.fixture
def local_app(tmp_path, strict):
    application = create_app(_migrated(_settings(tmp_path, auth_method="local")))
    conn = _conn(application)
    try:
        local_users.create_user(conn, "jsmith", "old-password-long", "editor")
        conn.commit()
    finally:
        conn.close()
    return application


def test_password_partial_refusal_is_a_result_line(local_app, browsers, caplog):
    here = browsers("jsmith", local_app, "old-password-long")
    body = {"current_password": "wrong-password-x", "new_password": "new-password-long",
            "new_password_again": "new-password-long"}
    resp = here.client.post("/partials/account/password", data=body, headers=here.h)
    assert resp.status_code == 200
    assert "That is not your current password, so nothing changed." in resp.text
    assert "HX-Redirect" not in resp.headers
    resp = here.client.post("/partials/account/password", headers=here.h, data={
        "current_password": "old-password-long", "new_password": "short",
        "new_password_again": "short"})
    assert "needs at least" in resp.text
    assert not any("new-password-long" in r.getMessage() for r in caplog.records)
    assert EM_DASH not in resp.text


def test_password_partial_success_redirects_with_a_new_cookie(local_app, browsers):
    here = browsers("jsmith", local_app, "old-password-long")
    other = browsers("jsmith", local_app, "old-password-long")
    old_cookie = here.client.cookies.get(auth.COOKIE_NAME)
    resp = here.client.post("/partials/account/password", headers=here.h, data={
        "current_password": "old-password-long", "new_password": "new-password-long",
        "new_password_again": "new-password-long"})
    assert resp.status_code == 200, resp.text
    assert resp.headers.get("HX-Redirect") == "/account?changed=password&others=1"
    assert here.client.cookies.get(auth.COOKIE_NAME) != old_cookie
    page = here.client.get("/account?changed=password&others=1")
    assert page.status_code == 200 and "Signed out 1 other browser;" in page.text
    assert other.client.get("/api/v1/me/account").status_code == 401


@pytest.mark.parametrize("count", [None, "not-a-count", True])
def test_password_partial_success_without_a_count_still_confirms(local_app, browsers,
                                                                 monkeypatch, count):
    """B's rotate_after_password_change answers None when there is no session
    store or signing the others out failed; the password HAS changed, so the
    redirect still carries changed=password and the page says so."""
    real = account_api.change_password

    def no_count(*a, **kw):
        out = dict(real(*a, **kw))
        out["other_sessions_signed_out"] = count
        return out

    monkeypatch.setattr(account_api, "change_password", no_count)
    here = browsers("jsmith", local_app, "old-password-long")
    resp = here.client.post("/partials/account/password", headers=here.h, data={
        "current_password": "old-password-long", "new_password": "new-password-long",
        "new_password_again": "new-password-long"})
    assert resp.status_code == 200, resp.text
    assert resp.headers.get("HX-Redirect") == "/account?changed=password"
    page = here.client.get(resp.headers["HX-Redirect"])
    assert "Password changed." in page.text
    assert "Your other browsers may still be signed in" in page.text
    assert EM_DASH not in page.text


def test_admin_password_reset_partial_is_audited(tmp_path, strict, browsers):
    """D-15: the Users page's [ SET ] writes user.password_reset, with nothing
    about the password in it."""
    application = create_app(_migrated(_settings(tmp_path, auth_method="local")))
    conn = _conn(application)
    try:
        local_users.create_user(conn, "owen", "owen-password-long", "admin")
        local_users.create_user(conn, "jsmith", "js-password-long", "editor")
        conn.commit()
    finally:
        conn.close()
    admin = browsers("owen", application, "owen-password-long")
    resp = admin.client.post("/partials/admin/users/password", headers=admin.h,
                             data={"username": "jsmith", "password": "brand-new-password"})
    assert resp.status_code == 200 and "Password set for jsmith" in resp.text
    conn = _conn(application)
    try:
        rows = db.fetch_audit(conn, actions=("user.password_reset",))
    finally:
        conn.close()
    assert rows and rows[0]["actor"] == "owen" and rows[0]["subject"] == "jsmith"
    assert "brand-new" not in rows[0]["detail_json"]


# --------------------------------------------------- a computer's fleet jobs (F5)

def test_ask_from_the_page_stores_a_pending_request(app, browsers):
    _seed_machine(app, "jsmith", "JS-RIG")
    ed = browsers("jsmith")
    resp = ed.client.post("/partials/account/machines/settings", headers=ed.h,
                          data={"editor": "jsmith", "machine": "JS-RIG", "jobs_enabled": "0"})
    assert resp.status_code == 200, resp.text
    assert "JS-RIG gets it the next time it reports in." in resp.text
    assert '<span class="t">Withdraw</span>' in resp.text
    assert 'hx-post="/partials/account/machines/settings/withdraw"' in resp.text
    conn = _conn(app)
    try:
        req = db.machine_settings_request(conn, "jsmith", "JS-RIG")
    finally:
        conn.close()
    assert req["state"] == "pending" and req["settings"] == {"jobs_enabled": False}
    # the box now shows what was asked
    assert re.search(r'name="jobs_enabled" value="1"(?! checked)>', resp.text)
    resp = ed.client.post("/partials/account/machines/settings/withdraw", headers=ed.h,
                          data={"editor": "jsmith", "machine": "JS-RIG"})
    assert resp.status_code == 200 and "Withdrawn." in resp.text
    assert '<span class="t">Withdraw</span>' not in resp.text
    assert 'hx-post="/partials/account/machines/settings/withdraw"' not in resp.text


def test_ask_kinds_every_kind_is_stored_as_empty_and_last_kind_refused(app, browsers):
    _seed_machine(app, "jsmith", "JS-RIG", caps={"jobs_enabled": True,
                                                 "job_kinds": ["peaks"], "idle_seconds": 60})
    ed = browsers("jsmith")
    resp = ed.client.post("/partials/account/machines/settings", headers=ed.h,
                          data={"editor": "jsmith", "machine": "JS-RIG", "jobs_kinds_sent": "1"})
    assert resp.status_code == 200
    assert account_ui.LAST_KIND in resp.text
    conn = _conn(app)
    try:
        assert db.machine_settings_request(conn, "jsmith", "JS-RIG") is None
    finally:
        conn.close()
    resp = ed.client.post("/partials/account/machines/settings", headers=ed.h, data={
        "editor": "jsmith", "machine": "JS-RIG", "jobs_kinds_sent": "1",
        "jobs_kinds": list(db.JOB_KINDS)})
    assert resp.status_code == 200
    conn = _conn(app)
    try:
        assert db.machine_settings_request(conn, "jsmith", "JS-RIG")["settings"] == {"jobs_kinds": []}
    finally:
        conn.close()


def test_ask_naming_mode_is_refused(app, browsers):
    _seed_machine(app, "jsmith", "JS-RIG")
    ed = browsers("jsmith")
    resp = ed.client.post("/partials/account/machines/settings", headers=ed.h,
                          data={"editor": "jsmith", "machine": "JS-RIG", "jobs_enabled": "0",
                                "mode": "base"})
    assert resp.status_code == 200
    assert "Only these can be changed from here" in resp.text
    conn = _conn(app)
    try:
        assert db.machine_settings_request(conn, "jsmith", "JS-RIG") is None
    finally:
        conn.close()


def test_ask_for_someone_elses_computer_is_403(app, browsers):
    _seed_machine(app, "owen", "OWEN-RIG")
    ed = browsers("jsmith")
    resp = ed.client.post("/partials/account/machines/settings", headers=ed.h,
                          data={"editor": "owen", "machine": "OWEN-RIG", "jobs_enabled": "0"})
    assert resp.status_code == 403


def test_old_companion_gets_the_too_old_sentence_and_no_controls(app, browsers):
    _seed_machine(app, "jsmith", "JS-OLD", cfg=None)       # no section: cfg_* NULL
    ed = browsers("jsmith")
    html = ed.client.get("/account").text
    assert "JS-OLD&#39;s CCSync is too old to change this from here." in html
    assert 'hx-post="/partials/account/machines/settings"' not in html
    assert "not reported" in html
    resp = ed.client.post("/partials/account/machines/settings", headers=ed.h,
                          data={"editor": "jsmith", "machine": "JS-OLD", "jobs_enabled": "0"})
    assert resp.status_code == 200 and "too old to change this from here" in resp.text


def test_readonly_rows_and_youtube_hidden_when_site_has_it_off(app, browsers):
    _seed_machine(app, "jsmith", "JS-RIG", cfg={
        "accepts": ["jobs_enabled", "jobs_kinds"], "jobs_volunteer_minutes": 45,
        "drive_reminder_minutes": 0, "pending_restart": {},
        "youtube": {"downloads": True, "signin_enabled": True, "terms_accepted": True,
                    "signin": "ok"}})
    ed = browsers("jsmith")
    html = ed.client.get("/account").text
    assert "45 min" in html and "the first warning only" in html
    pc = {"settings": {"jobs_volunteer_minutes": 45, "drive_reminder_minutes": 30.0,
                       "youtube": {"downloads": False, "signin_enabled": True,
                                   "terms_accepted": True, "signin": "expired"}}}
    off = account_ui._readonly_rows(pc, {"youtube_download": False}, False)
    assert [r["name"] for r in off] == ["lend it to the fleet for", "drive reminder"]
    on = {r["name"]: r["value"] for r in account_ui._readonly_rows(
        pc, {"youtube_download": True}, False)}
    assert on["YouTube sign-in"] == "expired: sign in again"
    assert "downloads off on this computer" in on["YouTube terms"]
    # a wired rig has no drive reminder row; NULL settings read "not reported" ("")
    rig = account_ui._readonly_rows({"settings": None}, {"youtube_download": True}, True)
    assert [r["name"] for r in rig] == ["lend it to the fleet for", "YouTube terms",
                                         "YouTube sign-in"]
    assert all(r["value"] == "" for r in rig)


def test_computer_partial(app, browsers):
    _seed_machine(app, "jsmith", "JS-RIG")
    ed = browsers("jsmith")
    resp = ed.client.get("/partials/account/computer?machine=JS-RIG")
    assert resp.status_code == 200 and "JS-RIG" in resp.text
    assert ed.client.get("/partials/account/computer?machine=NOPE").text == ""
    _seed_machine(app, "owen", "OWEN-RIG")
    assert ed.client.get("/partials/account/computer?machine=OWEN-RIG").text == ""


# ------------------------------------------------------------ the 4.5 lines

def _pc(**req) -> dict:
    running = req.pop("running", None)
    return {"machine": "M1", "settings": {"pending_restart": req.pop("pending_restart", {})},
            "jobs": running or {}, "settings_request": req or None}


SAVED = "M1 saved it. It takes effect the next time CCSync starts there."


def _status(settings, running=None, **extra):
    now = db.utcnow_iso()
    extra.setdefault("answered_at", now)
    line = account_ui.request_status(_pc(state="applied", settings=settings,
                                         running=running, **extra))
    return line and line["text"]


def test_in_effect_needs_the_running_value_to_match():
    """Review round (account page 2026-09-25), spec 4.4/4.5: `applied` with no
    pending_restart entry is NOT "In effect." until the running value
    (jobs.enabled / jobs.kinds from capabilities) matches the ask."""
    off = {"jobs_enabled": False}
    # running value not changed yet (an old companion sends no pending_restart)
    assert _status(off, {"enabled": True}) == SAVED
    # running value not reported (NULL capabilities): cannot tell
    assert _status(off, {"enabled": None}) == SAVED
    assert _status(off) == SAVED
    assert _status(off, {"enabled": False}) == "In effect."
    # kinds: a different running set is not a match; [] and every kind are one answer
    kinds = {"jobs_kinds": ["whisper"]}
    assert _status(kinds, {"kinds": ["whisper", "peaks"]}) == SAVED
    assert _status(kinds, {"kinds": []}) == SAVED
    assert _status(kinds, {"kinds": ["whisper"]}) == "In effect."
    every = {"jobs_kinds": []}
    assert _status(every, {"kinds": list(db.JOB_KINDS)}) == "In effect."
    assert _status(every, {"kinds": []}) == "In effect."
    assert _status(every, {"kinds": ["whisper"]}) == SAVED
    # both keys asked: both must match
    both = {"jobs_enabled": True, "jobs_kinds": ["peaks"]}
    assert _status(both, {"enabled": True, "kinds": ["whisper"]}) == SAVED
    assert _status(both, {"enabled": True, "kinds": ["peaks"]}) == "In effect."
    # a key this page cannot read back is never claimed as in effect
    assert _status({"future_key": 1}, {"enabled": True}) == SAVED


def test_in_effect_goes_quiet():
    """"In effect. (and the row is quiet)": the green line shows for a while
    after the answer, then the row says nothing."""
    import datetime as dt
    old = (dt.datetime.now(dt.timezone.utc)
           - dt.timedelta(seconds=account_ui.IN_EFFECT_SHOWS_FOR + 60)).replace(
        microsecond=0).isoformat()
    off = {"jobs_enabled": False}
    running = {"enabled": False}
    assert _status(off, running, answered_at=old) is None
    assert _status(off, running, answered_at=None) is None
    assert _status(off, running, answered_at="garbage") is None
    # still waiting for a restart is NOT quiet, however old
    assert _status(off, running, answered_at=old, pending_restart=off) == SAVED


def test_request_status_lines():
    now = db.utcnow_iso()
    assert account_ui.request_status(_pc()) is None
    line = account_ui.request_status(_pc(state="pending", requested_at=now, delivered_at=None,
                                         detail="", settings={"jobs_enabled": False}))
    assert line["text"].endswith("M1 gets it the next time it reports in.")
    line = account_ui.request_status(_pc(state="pending", requested_at=now, delivered_at=now,
                                         detail="", settings={}))
    assert line["text"].startswith("Sent to M1") and line["text"].endswith("Waiting for its answer.")
    line = account_ui.request_status(_pc(state="pending", delivered_at=now,
                                         detail="could not save config.toml", settings={}))
    assert line["text"] == ("M1 could not save it yet and will try again: "
                            "could not save config.toml")
    line = account_ui.request_status(_pc(state="applied", settings={"jobs_enabled": False},
                                         pending_restart={"jobs_enabled": False}))
    assert line["text"] == "M1 saved it. It takes effect the next time CCSync starts there."
    # applied, nothing on disk waiting, running value matches, answered just now
    line = account_ui.request_status(_pc(state="applied", settings={"jobs_enabled": False},
                                         answered_at=now, running={"enabled": False}))
    assert line == {"tone": "green", "text": "In effect."}
    line = account_ui.request_status(_pc(state="refused", detail="nope", settings={}))
    assert line["text"] == "M1 refused: nope"
    line = account_ui.request_status(_pc(state="expired", settings={}))
    assert line["text"] == "M1 did not report in for 14 days, so the request was dropped."
    assert account_ui.request_status(_pc(state="withdrawn", settings={})) is None
    assert account_ui.request_status(_pc(state="something-new", settings={})) is None


def test_dom_id_is_stable_and_safe():
    assert account_ui.dom_id("A B/C") == account_ui.dom_id("A B/C")
    assert account_ui.dom_id("A B/C") != account_ui.dom_id("A B C")
    assert re.fullmatch(r"pc-[0-9a-f]{12}", account_ui.dom_id("我的 電腦"))


def test_module_sentences_have_no_em_dash():
    for value in vars(account_ui).values():
        if isinstance(value, str):
            assert EM_DASH not in value
    for d in (account_ui.KIND_WORDS,):
        assert all(EM_DASH not in v for v in d.values())


# ------------------------------------------------ projects on one computer

def test_plan_rows_drive_the_existing_toggle_route(app, browsers):
    _seed_machine(app, "jsmith", "JS RIG")                # a space: matched exactly
    _project(app, "p1", "2026/FF5/Elections")
    _project(app, "p2", "2026/Shorts/Night Market")
    conn = _conn(app)
    try:
        db.add_selection(conn, "jsmith", "p1", created_by="jsmith", now=db.utcnow_iso(),
                         machine="JS RIG", sync_mode=db.SYNC_MODE_UPLOAD_ONLY)
        conn.commit()
    finally:
        conn.close()
    ed = browsers("jsmith")
    html = ed.client.get("/account").text
    # view=none: the account page takes an empty 200 back (R15). The
    # attribute's ampersands may be autoescaped (&amp;); htmx decodes them.
    base = "/partials/selection/jsmith/p1/toggle?view=none&machine=JS%20RIG"

    def posts(body: str, mode: str) -> bool:
        pat = "&(amp;)?".join(re.escape(part) for part in f"{base}&mode={mode}".split("&"))
        return re.search(f'hx-post="{pat}"', body) is not None

    assert posts(html, "full")                                  # Sync fully
    # Untick names the state it means (everyday-apps-1): an explicit off.
    assert posts(html, "off")                                   # Untick
    assert "This removes 2026/FF5/Elections from JS RIG." in html
    assert '<option value="p2"' in html and '<option value="p1"' not in html
    # the route the button posts to is the existing one, and it flips the mode
    resp = ed.client.post(f"{base}&mode=full", headers=ed.h)
    assert resp.status_code == 200, resp.text
    conn = _conn(app)
    try:
        modes = {r["slug"]: r["sync_mode"] for r in db.selections_for_machine(conn, "jsmith", "JS RIG")}
    finally:
        conn.close()
    assert modes == {"p1": db.SYNC_MODE_FULL}
    frag = ed.client.get("/partials/account/computer?machine=JS%20RIG").text
    assert re.search(r'<span class="tag ok"[^>]*>full</span>', frag)
    assert posts(frag, "upload_only")


def test_wired_computer_has_no_plan_controls(app, browsers):
    _seed_machine(app, "jsmith", "JS-WIRED", mode="base")
    _project(app, "p1", "2026/FF5/Elections")
    ed = browsers("jsmith")
    html = ed.client.get("/account").text
    assert "JS-WIRED" in html and "wired to the server" in html
    assert "projects on this computer" not in html
    assert "no wait (a computer wired to the server is exempt)" in html


F_WRITES = ["/partials/account/display-name", "/partials/admin/users/display-name",
            "/partials/account/password", "/partials/account/sessions/revoke",
            "/partials/account/sessions/revoke-others", "/partials/account/machines/settings",
            "/partials/account/machines/settings/withdraw"]


def test_every_page_write_needs_csrf_and_is_not_exempt(app, browsers):
    from ccsync_dashboard import app as app_mod

    _seed_machine(app, "owen", "OWEN-RIG")
    admin = browsers("owen")
    for path in F_WRITES:
        assert not app_mod._open_path(path, "POST"), path
        assert path not in app_mod._CSRF_EXEMPT_EXACT
        assert not path.startswith(app_mod._CSRF_EXEMPT_PREFIXES)
        assert app_mod._CSRF_EXEMPT_RE.match(path) is None
        resp = admin.client.post(path, data={"editor": "owen", "machine": "OWEN-RIG",
                                             "jobs_enabled": "0", "display_name": "X",
                                             "username": "owen", "handle": "0123456789ab"})
        assert resp.status_code == 403, (path, resp.status_code)
    for path in ("/account", "/partials/account/sessions", "/partials/account/sync-keys",
                 "/partials/account/computer"):
        assert not app_mod._open_path(path, "GET"), path
    conn = _conn(app)
    try:
        assert db.get_display_name(conn, "owen") is None
        assert db.machine_settings_request(conn, "owen", "OWEN-RIG") is None
    finally:
        conn.close()
