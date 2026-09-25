"""The CC Terminal look is the dashboard's ONLY look (owner, 2026-09-25: "this
is completely replacing the old one"). This file replaces the ui_variant
fixture's coverage meta-test and the overlay mechanism tests with the plain
facts that remain:

* every template under templates/ compiles, and every page and every polled
  partial renders (200) for a signed-in admin on a fresh site;
* between them the renders load every template file (a file nothing renders
  is dead markup, or a route that lost its page);
* the classic look is gone: no templates/cc/, no base.html, no style.css, no
  look switch (/ui/preview), no look menu;
* an htmx request from a page an older build drew (no `X-CC-UI: terminal`)
  is answered with HX-Refresh BEFORE the route runs, so a write from it is
  never committed (UI port review mechanism-1);
* a `ui_terminal_groups` row a 0.7.62 site stored is removed at boot and a
  Settings save that still names it is not refused;
* the service worker precaches no classic sheet and names a new cache.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth, ui
from ccsync_dashboard import db as dbmod
from ccsync_dashboard import site_store
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "every-template-test-secret-xxxxxxxx"
ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "templates"
STATIC = ROOT / "static"
HX = {"HX-Request": "true", "X-CC-UI": "terminal"}

PAGES = (
    "/", "/project/2026-ff5-elections", "/transfers",
    "/project-setup?resolve_project=Elections",
    "/installer", "/help", "/account",
    "/admin/settings", "/admin/users", "/admin/assignments", "/admin/packages",
    "/admin/jobs", "/admin/audit", "/setup",
    "/admin/health", "/admin/invariants", "/admin/protection", "/admin/alerts",
    "/admin/recovery", "/offline",
)

PARTIALS = (
    "/partials/topbar", "/partials/stamp", "/partials/halt-line",
    "/partials/fleet", "/partials/projects-tree", "/partials/home-problems",
    "/partials/home-transfers", "/partials/home-queue", "/partials/computer-answer",
    "/partials/project/2026-ff5-elections", "/partials/project/2026-ff5-elections/bins",
    "/partials/project-roots", "/partials/project-roots/browse",
    "/partials/transfers", "/partials/plan-changes",
    "/partials/person-queue", "/partials/account/computer",
    "/partials/account/sync-keys", "/partials/account/sessions",
    "/partials/admin/users", "/partials/admin/sessions",
    "/partials/admin/report-tokens", "/partials/admin/fleet-halt",
    "/partials/admin/jobs", "/partials/admin/audit",
    "/partials/admin/packages", "/partials/admin/dashboard-update",
    "/partials/health-notices", "/partials/health-collector",
    "/partials/health-diagnostics",
)


@pytest.fixture
def loaded(monkeypatch):
    """Every template name the one environment loads during the test."""
    seen: set[str] = set()
    env = ui.templates.env
    original = env._load_template

    def load(name, globals):  # noqa: A002 - Jinja's own parameter name
        seen.add(str(name).replace("\\", "/"))
        return original(name, globals)

    monkeypatch.setattr(env, "_load_template", load)
    # Jinja's cache would hide a second load; start each test cold.
    env.cache.clear() if env.cache is not None else None
    return seen


@pytest.fixture
def site(tmp_path):
    projects = tmp_path / "tree" / "Projects"
    projects.mkdir(parents=True)
    settings = Settings(db_path=str(tmp_path / "d.db"), session_secret=SECRET,
                        admin_users=frozenset({"owen"}), projects_dir=str(projects),
                        auth_method="local")
    app = create_app(settings)
    with TestClient(app) as client:
        conn = dbmod.connect(settings.db_path)
        now = dbmod.utcnow_iso()
        dbmod.upsert_project(conn, "2026-ff5-elections", "2026/FF5/Elections",
                             "/data/2026-ff5-elections", now)
        dbmod.record_known_editor(conn, "jsmith", source="admin", now=now)
        conn.commit()
        client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "owen"))
        yield client, conn, settings
        conn.close()


# Drawn only when the site holds the data they are about; each still has to
# compile (test_every_template_compiles) and is rendered by its own area's
# tests.
DATA_CONDITIONAL = frozenset({
    "cards_landing.html",                   # only with Timeline Cards mounted
    "partials/account_computer.html",       # one per computer that reported
    "partials/account_jobs.html",           # inside a computer's window
    "partials/account_result.html",         # the answer to an account write
    "partials/admin_suspend_button.html",   # one per local account
    "partials/missing_files.html",          # a project's per-device drill-down
    "partials/person_fix_root.html",        # one per remote computer
})


def _all_templates() -> list[str]:
    return sorted(p.relative_to(TEMPLATES).as_posix()
                  for p in TEMPLATES.rglob("*.html"))


def test_the_classic_look_is_gone():
    assert not (TEMPLATES / "cc").exists()
    assert not (TEMPLATES / "base.html").exists()
    for name in ("style.css", "mobile.css", "ui_groups.js"):
        assert not (STATIC / name).exists(), name
    for name in _all_templates():
        text = (TEMPLATES / name).read_text(encoding="utf-8")
        assert "/ui/preview" not in text, name


def test_every_template_compiles():
    # The routers' own modules register the filters and globals the
    # templates use (create_app imports them the same way).
    from ccsync_dashboard import ui_chrome, ui_everyday, ui_health, ui_home  # noqa: F401
    for name in _all_templates():
        ui.templates.env.get_template(name)


def test_every_page_and_partial_renders_and_every_template_is_used(site, loaded):
    client, _conn, _settings = site
    for path in PAGES:
        r = client.get(path)
        assert r.status_code == 200, (path, r.status_code, r.text[:300])
        assert 'data-ui="cc"' in r.text, path
        assert '"X-CC-UI": "terminal"' in r.text, path
        assert "/static/style.css" not in r.text, path
        assert "/ui/preview" not in r.text, path
        # /help lists the shipped docs tree by title, and for an admin on a
        # dev checkout that includes docs/UI_PORT_LEDGER/, whose titles say
        # "after the classic look was retired". A doc title is data, not
        # product copy, so the phrase check reads the page with the index cut.
        text = r.text
        if path == "/help":
            text = re.sub(r'<a href="/help/[^"]*">.*?</a>', "", text, flags=re.DOTALL)
        assert "classic look" not in text, path
    for path in PARTIALS:
        r = client.get(path, headers=HX)
        assert r.status_code == 200, (path, r.status_code, r.text[:300])
        assert "HX-Refresh" not in r.headers, path
    client.cookies.clear()
    r = client.get("/login")
    assert r.status_code == 200 and 'data-ui="cc"' in r.text
    never = sorted(set(_all_templates()) - loaded - DATA_CONDITIONAL)
    assert not never, f"templates no page or partial renders: {never}"


def test_the_hud_has_no_look_menu(site):
    client, _conn, _settings = site
    body = client.get("/partials/topbar?current=broll", headers={}).text
    assert "data-dash-topbar" in body
    assert "look on this" not in body and "/ui/preview" not in body


def test_the_look_switch_routes_are_gone_and_go_answers_one_place(site):
    client, _conn, _settings = site
    assert client.get("/ui/preview?variant=classic", follow_redirects=False).status_code == 404
    r = client.get("/go/notices", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/admin/health#server-notices"


def test_a_stale_page_is_told_to_reload_and_its_write_never_lands(site):
    """mechanism-1: the old 409 came AFTER partial_toggle had committed."""
    client, conn, _settings = site
    for headers in ({"HX-Request": "true"},
                    {"HX-Request": "true", "X-CC-UI": "chrome,home"}):
        r = client.get("/partials/fleet", headers=headers)
        assert r.status_code == 200 and r.headers.get("HX-Refresh") == "true"
        assert r.text == ""
        r = client.post("/partials/selection/jsmith/2026-ff5-elections/toggle?view=tree",
                        headers=headers)
        assert r.headers.get("HX-Refresh") == "true" and r.text == ""
        assert dbmod.fetch_selections(conn, "jsmith") == []
    # The same write from a current page lands.
    r = client.post("/partials/selection/jsmith/2026-ff5-elections/toggle?view=tree",
                    headers=HX)
    assert r.status_code == 200 and "HX-Refresh" not in r.headers
    assert [s["slug"] for s in dbmod.fetch_selections(conn, "jsmith")] == ["2026-ff5-elections"]


def test_a_stored_look_setting_is_harmless(tmp_path):
    db_path = str(tmp_path / "d.db")
    conn = dbmod.connect(db_path)
    dbmod.migrate(conn)
    conn.execute(f"INSERT INTO {site_store.TABLE} (key, value, updated_at, updated_by) "
                 "VALUES ('ui_terminal_groups', 'chrome,home', '2026-09-25T00:00:00Z', 'owen')")
    conn.commit()
    conn.close()
    settings = Settings(db_path=db_path, session_secret=SECRET,
                        admin_users=frozenset({"owen"}), auth_method="local")
    with TestClient(create_app(settings)) as client:
        conn = dbmod.connect(db_path)
        try:
            assert "ui_terminal_groups" not in site_store.get_all(conn)
        finally:
            conn.close()
        client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "owen"))
        manifest = client.get("/api/v1/admin/site").json()
        assert "ui_terminal_groups" not in manifest
        r = client.put("/api/v1/admin/site",
                       json={"values": {"ui_terminal_groups": "none", "ui_preview": "off"}})
        assert r.status_code == 200, r.text


def test_the_service_worker_names_a_new_cache_and_no_classic_sheet(site):
    client, _conn, _settings = site
    body = client.get("/sw.js").text
    assert "style.css" not in body.split("const PASS_THROUGH")[0].split("const PRECACHE")[1]
    assert "mobile.css" not in body
    assert "const LOOK = '" in body
    assert "/static/cc/hud.css?h=" in body


def test_undo_last_change_survives_a_history_entry_that_recorded_the_look_switch(tmp_path):
    """A site that ran 0.7.62 may have the look switch as its newest recorded
    site change. Undo used to hand that key to validate_many and answer 422
    "not a recognised site setting"; now the retired key is dropped from the
    values to restore (as the PUT drops it), so the switch alone is "nothing
    to restore" and a mixed entry restores its other keys."""
    from ccsync_dashboard import site_store
    db_path = tmp_path / "undo-retired.db"
    settings = Settings(db_path=str(db_path), session_secret=SECRET,
                        admin_users=frozenset({"owen"}), auth_method="local")
    app = create_app(settings)
    with TestClient(app) as client:
        conn = dbmod.connect(db_path)
        client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "owen"))
        dbmod.record_site_change(conn, "owen", "save", {"ui_terminal_groups": "none"},
                                 {"ui_terminal_groups": "chrome,home"})
        conn.commit()
        r = client.post("/api/v1/admin/site/undo-last-change")
        assert r.status_code == 409, r.text
        assert "not a recognised" not in r.text
        dbmod.record_site_change(conn, "owen", "save",
                                 {"ui_terminal_groups": "chrome,home", "tree_name": "Projects"},
                                 {"ui_terminal_groups": "all", "tree_name": "Vault"})
        site_store.set_many(conn, {"tree_name": "Vault"}, updated_by="owen")
        conn.commit()
        r = client.post("/api/v1/admin/site/undo-last-change")
        assert r.status_code == 200, r.text
        assert site_store.get_all(conn).get("tree_name") == "Projects"
        assert "ui_terminal_groups" not in site_store.get_all(conn)
        conn.close()

