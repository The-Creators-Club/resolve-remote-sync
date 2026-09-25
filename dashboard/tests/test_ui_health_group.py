"""The terminal Health group (UI redesign port, phase 5 "settings-health",
2026-09-25): Health, Invariants, Protection, Alerts, Recovery.

docs/UI_REDESIGN_PORT_PLAN.md 1.3, 1.5, 5.3, 7.1 row 5, R13, R15. Classic
pins (test_health_page.py, test_invariants.py, test_protection.py,
test_alerts.py, the recovery tests) are untouched: this file only ADDS the
terminal assertions, with the group switched on through the one seam every
reader of the setting uses (ui_variant.site_groups), and checks classic is
unchanged beside it.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import alerts, auth, db as dbmod, protection
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "test-secret-value-uihealth-1234567890"
HEALTH = "chrome,settings-health"
BOTH = pytest.mark.parametrize("ui_variant", ["classic", HEALTH], indirect=True)
TERMINAL = pytest.mark.parametrize("ui_variant", [HEALTH, "all"], indirect=True)
PAGES = ("/admin/health", "/admin/invariants", "/admin/protection",
         "/admin/alerts", "/admin/recovery")


@pytest.fixture
def env(tmp_path):
    settings = Settings(db_path=str(tmp_path / "d.db"), session_secret=SECRET,
                        admin_users=frozenset({"owen"}))
    with TestClient(create_app(settings)) as c:
        # The collector's own first pass races the fixture (see
        # test_health_page.py's env): stop it before anything is read.
        c.app.state.collector.stop()
        conn = dbmod.connect(settings.db_path)
        c.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "owen"))
        try:
            yield c, conn
        finally:
            conn.close()


def _hx(ui_variant, client, page="/admin/health"):
    headers = ui_variant.htmx_headers(client, "http://testserver" + page)
    headers["Origin"] = "http://testserver"
    headers["X-CSRF-Token"] = _csrf(client, page)
    return headers


def _csrf(client, page):
    m = re.search(r'name="csrf" content="([^"]+)"', client.get(page).text)
    return m.group(1) if m else ""


class _Forms(HTMLParser):
    """Every <form>, the depth it opened at, and the named controls inside."""

    def __init__(self):
        super().__init__()
        self.stack: list[dict] = []
        self.forms: list[dict] = []
        self.nested = 0
        self.controls: list[dict] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "form":
            if self.stack:
                self.nested += 1
            f = {"attrs": a, "names": []}
            self.stack.append(f)
            self.forms.append(f)
        elif tag in ("input", "select", "textarea", "button") and a.get("name"):
            owner = a.get("form") or (self.stack[-1]["attrs"].get("id") if self.stack else None)
            self.controls.append({"name": a["name"], "owner": owner,
                                  "in": self.stack[-1] if self.stack else None, "attrs": a})
            if self.stack and not a.get("form"):
                self.stack[-1]["names"].append(a["name"])

    def handle_endtag(self, tag):
        if tag == "form" and self.stack:
            self.stack.pop()


def _forms(html):
    p = _Forms()
    p.feed(html)
    return p


# ------------------------------------------------------------- every page

@BOTH
@pytest.mark.parametrize("path", PAGES)
def test_each_page_renders_in_its_look(env, ui_variant, path):
    client, _conn = env
    r = client.get(path)
    assert r.status_code == 200, r.text[:400]
    ui_variant.check_page(r.text)
    if ui_variant.is_classic:
        assert 'data-ui="cc"' not in r.text
        assert "[ " in r.text  # classic keeps its bracket keys (D8, classic unchanged)
    else:
        assert 'data-ui="cc"' in r.text
        assert "cc/health.css" in r.text
        assert 'class="sidebar"' not in r.text  # D17: no sidebar on Settings pages


@TERMINAL
@pytest.mark.parametrize("path", PAGES)
def test_terminal_pages_draw_no_bracket_control_and_no_em_dash(env, ui_variant, path):
    client, _conn = env
    html = client.get(path + ("?problem=resolve" if path.endswith("recovery") else "")).text
    body = html.split("<body", 1)[1]
    assert "—" not in body
    for m in re.finditer(r"<(button|a)\b[^>]*>(.*?)</\1>", body, flags=re.S):
        text = re.sub(r"<[^>]+>", "", m.group(2))
        assert not re.search(r"\[\s*[A-Z]", text), f"bracketed control on {path}: {text!r}"


@TERMINAL
@pytest.mark.parametrize("path", PAGES)
def test_every_window_folds_and_has_a_named_heading(env, ui_variant, path):
    client, _conn = env
    html = client.get(path).text
    wins = re.findall(r'<section class="win"[^>]*>\s*<div class="bar"><button type="button" class="fold"[^>]*aria-label="Fold [^"]+"', html)
    assert wins, path
    assert html.count('<section class="win"') == len(wins), path


# ------------------------------------------------------------- health

@TERMINAL
def test_health_panels_are_tabs_whose_frames_carry_the_go_anchors(env, ui_variant):
    client, _conn = env
    html = client.get("/admin/health").text
    for panel_id, anchor, route in (("hpanel-notices", "server-notices", "/partials/health-notices"),
                                    ("hpanel-collector", "fleet-collector", "/partials/health-collector"),
                                    ("hpanel-diag", "fleet-diagnostics", "/partials/health-diagnostics")):
        assert f'aria-controls="{panel_id}"' in html
        start = html.index(f'id="{panel_id}"')
        chunk = html[start:start + 1500]
        assert f'id="{anchor}"' in chunk and f'hx-get="{route}"' in chunk
        # the FRAME is static; only the body is fetched (3.1)
        assert f'id="{anchor}" hx-get' not in chunk


@TERMINAL
@pytest.mark.parametrize("route,marker", [
    ("/partials/health-notices", "what the server checks"),
    ("/partials/health-collector", "cycle"),
    ("/partials/health-diagnostics", "diagnostics"),
])
def test_health_partials_serve_terminal_markup(env, ui_variant, route, marker):
    client, _conn = env
    r = client.get(route, headers=_hx(ui_variant, client))
    assert r.status_code == 200, r.text[:300]
    assert marker in r.text
    assert "[ " not in re.sub(r"<[^>]+>", "", r.text).replace("[ TAKE", "")  # no bracket label


@pytest.mark.parametrize("ui_variant", ["classic"], indirect=True)
@pytest.mark.parametrize("route", ["/partials/health-notices", "/partials/health-collector",
                                   "/partials/health-diagnostics"])
def test_health_partials_are_404_when_the_group_is_off(env, ui_variant, route):
    client, _conn = env
    r = client.get(route, headers=_hx(ui_variant, client, "/admin/health"))
    assert r.status_code in (404, 409) or r.headers.get("HX-Refresh") == "true"
    assert "health-notices-body" not in r.text


@TERMINAL
def test_a_dismiss_from_health_returns_health_markup(env, ui_variant):
    client, conn = env
    dbmod.notice(conn, kind="project_nested_marker", subject="nas", severity="error",
                 body="something broke", fix="do the thing")
    conn.commit()
    listed = client.get("/partials/health-notices", headers=_hx(ui_variant, client)).text
    m = re.search(r'hx-post="/partials/health-notices/(\d+)/dismiss"', listed)
    assert m, listed[:600]
    assert 'hx-target="#health-notices-body"' in listed
    r = client.post(f"/partials/health-notices/{m.group(1)}/dismiss", headers=_hx(ui_variant, client))
    assert r.status_code == 200, r.text[:300]
    assert "what the server checks" in r.text          # the health panel,
    assert "admin-users-box" not in r.text and 'id="server-notices"' not in r.text


@pytest.mark.parametrize("ui_variant", ["classic"], indirect=True)
def test_a_health_dismiss_changes_nothing_when_the_group_is_off(env, ui_variant):
    client, conn = env
    dbmod.notice(conn, kind="project_nested_marker", subject="nas", severity="error",
                 body="b", fix="f")
    conn.commit()
    nid = conn.execute("SELECT id FROM notices").fetchone()[0]
    r = client.post(f"/partials/health-notices/{nid}/dismiss", headers=_hx(ui_variant, client))
    assert r.status_code != 200 or r.headers.get("HX-Refresh")
    row = conn.execute("SELECT cleared_at FROM notices WHERE id=?", (nid,)).fetchone()
    assert row[0] in (None, "")


@pytest.mark.parametrize("ui_variant,where", [
    (HEALTH, {"notices": "/admin/health#server-notices", "collector": "/admin/health#fleet-collector",
              "diagnostics": "/admin/health#fleet-diagnostics", "restore": "/admin/recovery#restore"}),
    ("classic", {"notices": "/#server-notices", "collector": "/#fleet-collector",
                 "diagnostics": "/#fleet-diagnostics", "restore": "/admin/recovery#restore"}),
], indirect=["ui_variant"])
def test_go_resolves_per_variant_and_lands_on_a_rendered_anchor(env, ui_variant, where):
    client, _conn = env
    for panel, href in where.items():
        r = client.get(f"/go/{panel}", follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == href, (panel, r.headers.get("location"))
        if not ui_variant.is_classic:
            page, anchor = href.split("#")
            assert f'id="{anchor}"' in client.get(page).text, href


# ------------------------------------------------------------- invariants / protection

@TERMINAL
def test_invariants_keep_three_states_and_protection_acks_swap_terminal(env, ui_variant):
    client, _conn = env
    inv = client.get("/admin/invariants").text
    assert 'id="invariant-table"' in inv and "not checked" in inv
    prot = client.get("/admin/protection").text
    assert prot.count('hx-post="/partials/admin/protection/ack"') == 2
    assert 'hx-target="#protection"' in prot
    r = client.post("/partials/admin/protection/ack",
                    data={"key": "restore_drill", "date": "2026-09-01"},
                    headers=_hx(ui_variant, client, "/admin/protection"))
    assert r.status_code == 200, r.text[:300]
    assert '<div id="protection" class="vstack">' in r.text
    assert "2026-09-01" in r.text


# ------------------------------------------------------------- alerts

@TERMINAL
def test_alerts_keeps_four_sibling_forms_and_the_save_carries_only_setting_keys(env, ui_variant):
    client, _conn = env
    html = client.get("/admin/alerts").text
    p = _forms(html)
    assert p.nested == 0, "a nested <form> is dropped by the parser"
    posts = {f["attrs"].get("hx-post") for f in p.forms}
    assert {"/partials/admin/alerts/save", "/partials/admin/alerts/password",
            "/partials/admin/alerts/triage/run", "/partials/admin/alerts/test"} <= posts
    save = next(f for f in p.forms if f["attrs"].get("hx-post") == "/partials/admin/alerts/save")
    assert set(save["names"]) <= set(alerts.SETTING_KEYS), set(save["names"]) - set(alerts.SETTING_KEYS)
    pw_id = next(f["attrs"]["id"] for f in p.forms if f["attrs"].get("hx-post") == "/partials/admin/alerts/password")
    run_id = next(f["attrs"]["id"] for f in p.forms if f["attrs"].get("hx-post") == "/partials/admin/alerts/triage/run")
    owners = {c["name"]: c["owner"] for c in p.controls}
    if "password" in owners:   # absent when the password comes from the environment
        assert owners["password"] == pw_id and owners["clear"] == pw_id
    assert any(c["attrs"].get("form") == run_id for c in p.controls if c["attrs"].get("type") == "submit") \
        or 'form="%s"' % run_id in html


@TERMINAL
def test_alerts_save_answers_with_the_terminal_panel(env, ui_variant):
    client, _conn = env
    r = client.post("/partials/admin/alerts/save", data={"alerts_sink": "none"},
                    headers=_hx(ui_variant, client, "/admin/alerts"))
    assert r.status_code == 200, r.text[:300]
    assert 'id="alerts-pw-form"' in r.text and '<div id="admin-alerts"' in r.text


# ------------------------------------------------------------- recovery

@TERMINAL
def test_recovery_keeps_its_forms_ids_and_targets(env, ui_variant):
    client, _conn = env
    html = client.get("/admin/recovery?problem=resolve").text
    for anchor in ('id="recovery"', 'id="restore"', 'id="resolve-undo"', 'id="wizard"'):
        assert anchor in html
    assert 'hx-post="/partials/admin/recovery/drill"' in html
    assert html.count('hx-target="#recovery"') >= 1
    assert _forms(html).nested == 0
    # the picker stays a link per problem, the chosen one marked
    assert 'href="/admin/recovery?problem=resolve#wizard" aria-current="true"' in html
    assert "what to do" in html


@TERMINAL
def test_recovery_posts_answer_with_the_terminal_panel(env, ui_variant):
    client, _conn = env
    r = client.post("/partials/admin/recovery/drill", data={"problem": ""},
                    headers=_hx(ui_variant, client, "/admin/recovery"))
    assert r.status_code == 200, r.text[:300]
    assert '<div id="recovery" class="vstack">' in r.text
    r = client.post("/partials/admin/recovery/preview",
                    data={"problem": "", "slug": "nope", "snapshot": "nope"},
                    headers=_hx(ui_variant, client, "/admin/recovery"))
    assert r.status_code == 200 and '<div id="recovery" class="vstack">' in r.text
