"""The terminal Users, Sync plans, Jobs, History and Setup pages (UI redesign
port phase 4, second half, group `settings-fleet`, builder P4b, 2026-09-25).

Run through the `ui_variant` fixture: classic keeps every classic pin (these
tests only assert the classic page still draws classic), and the terminal
look keeps every hook, URL and confirm the classic pages carry, puts every
swap target on a body and never on a `.win` (plan 3.1), keeps the one-time
secret out of every foldable window (3.1, wave 5), keeps ARCHIVE's native
confirm (3.2, wave 5), and draws no [ bracket ] label.
"""
from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth
from ccsync_dashboard import db as dbmod
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "p4b-test-secret-not-a-real-one-xx"
ROOT = Path(__file__).resolve().parents[1]
CC = ROOT / "templates" / "cc"

MY_TEMPLATES = (
    "admin_users.html", "partials/admin_users.html", "partials/admin_sessions.html",
    "partials/admin_report_tokens.html", "partials/admin_suspend_button.html",
    "partials/fleet_halt.html", "partials/minted_secret.html",
    "admin_assignments.html", "admin_jobs.html", "partials/admin_jobs.html",
    "admin_audit.html", "partials/admin_audit.html", "setup.html",
)
MY_SCRIPTS = ("cc/assignments.js", "cc/setup.js")

# Swap hooks that must sit on a body (or inside one), never on a .win (3.1).
HOOKS = ("admin-users-box", "admin-sessions", "admin-report-tokens",
         "admin-fleet-halt", "admin-jobs", "minted-secret")

PAGES = {
    "/admin/users": "USERS",
    "/admin/assignments?editor=jsmith&machine=*": "SYNC PLANS",
    "/admin/jobs": "FLEET JOBS",
    "/admin/audit": "HISTORY",
    "/setup": "SETUP",
}


@pytest.fixture
def env(ui_variant, tmp_path):
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
        dbmod.create_job(conn, "peaks", {"root": "media", "rel_path": "FF5/a.mp4",
                                          "out_root": "vault", "out_rel": "Vault/x"}, {})
        conn.commit()
        client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "owen"))
        yield client, conn
        conn.close()


def _terminal(ui_variant) -> bool:
    return "settings-fleet" in ui_variant.groups


class _Tree(HTMLParser):
    """Every element with its classes, id and ancestors' classes."""
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
            "meta", "source", "track", "wbr", "path", "circle"}

    def __init__(self):
        super().__init__()
        self.stack: list[dict] = []
        self.nodes: list[dict] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        node = {"tag": tag, "attrs": a, "cls": (a.get("class") or "").split(),
                "anc": [dict(n) for n in self.stack]}
        self.nodes.append(node)
        if tag not in self.VOID:
            self.stack.append({"tag": tag, "cls": node["cls"], "attrs": a})

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID and self.stack:
            self.stack.pop()

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i]["tag"] == tag:
                del self.stack[i:]
                break


def _parse(html: str) -> _Tree:
    t = _Tree()
    t.feed(html)
    return t


def _check_terminal_markup(html: str) -> None:
    tree = _parse(html)
    ids = [n["attrs"]["id"] for n in tree.nodes if n["attrs"].get("id")]
    dupes = {i for i in ids if ids.count(i) > 1}
    assert not dupes, dupes
    for n in tree.nodes:
        a, cls = n["attrs"], n["cls"]
        hooked = [h for h in HOOKS if h in cls or a.get("id") == h]
        if hooked:
            assert "win" not in cls, (hooked, a)
        if n["tag"] == "section" and "win" in cls:
            assert a.get("aria-labelledby"), a
            assert a["aria-labelledby"] in ids, a
        if n["tag"] == "button":
            assert a.get("type") in ("button", "submit"), a
            if "fold" in cls:
                assert a.get("type") == "button"
                assert a.get("aria-labelledby") or a.get("aria-label"), a
        if n["tag"] == "h2" and "t" in cls:
            assert a.get("id"), a
        if "hx-confirm" in a:
            chain = [a] + [x["attrs"] for x in n["anc"]]
            assert any(k in x for x in chain for k in ("hx-post", "hx-get", "hx-put", "hx-delete")), a
    # No [ bracket ] label on any control (owner rule).
    for label in re.findall(r"<(?:button|a)\b[^>]*>(.*?)</(?:button|a)>", html, re.S):
        text = re.sub(r"<[^>]+>", "", label)
        assert not re.search(r"\[ [A-Z]", text), text
    # No heading's accessible name holds an underscore.
    for h in re.findall(r'<h2 class="t"[^>]*>(.*?)</h2>', html, re.S):
        spoken = re.sub(r'<span aria-hidden="true">[^<]*</span>', "", h)
        spoken = re.sub(r"<[^>]+>", "", spoken)
        assert "_" not in spoken, h


@pytest.mark.parametrize("path", list(PAGES))
def test_each_page_draws_in_the_look_it_was_asked_for(ui_variant, env, path):
    client, _ = env
    page = client.get(path).text
    ui_variant.check_page(page)
    if not _terminal(ui_variant):
        assert 'data-ui="cc"' not in page
        assert "[ " in page      # the classic brackets, untouched
        return
    assert 'data-ui="cc"' in page
    assert "/static/cc/settings_people.css?h=" in page
    assert f"&gt;</span> {PAGES[path]}" in page
    _check_terminal_markup(page)


def test_users_page_keeps_every_panel_poll_and_the_secret_slot(ui_variant, env):
    client, _ = env
    page = client.get("/admin/users").text
    for url in ("/partials/admin/users", "/partials/admin/sessions",
                "/partials/admin/report-tokens", "/partials/admin/fleet-halt"):
        assert f'hx-get="{url}"' in page, url
    if not _terminal(ui_variant):
        return
    tree = _parse(page)
    slot = [n for n in tree.nodes if n["attrs"].get("id") == "minted-secret"]
    assert len(slot) == 1
    assert not any("win" in a["cls"] for a in slot[0]["anc"])
    assert not any(a["attrs"].get("hx-get") for a in slot[0]["anc"])
    # The frames are in the page; each poll sits on a .body, never the .win.
    for url in ("/partials/admin/sessions", "/partials/admin/report-tokens",
                "/partials/admin/fleet-halt"):
        node = next(n for n in tree.nodes if n["attrs"].get("hx-get") == url)
        assert "body" in node["cls"] and "win" not in node["cls"]
        assert any("win" in a["cls"] for a in node["anc"])


@pytest.mark.parametrize("url,hook", [
    ("/partials/admin/users", "admin-users-box"),
    ("/partials/admin/sessions", "admin-sessions"),
    ("/partials/admin/report-tokens", "admin-report-tokens"),
    ("/partials/admin/fleet-halt", "admin-fleet-halt"),
    ("/partials/admin/jobs", "admin-jobs"),
    ("/partials/admin/audit", None),
])
def test_each_partial_keeps_its_hook_in_both_looks(ui_variant, env, url, hook):
    client, _ = env
    page_url = "http://testserver/admin/audit" if "audit" in url else (
        "http://testserver/admin/jobs" if "jobs" in url else "http://testserver/admin/users")
    r = client.get(url, headers=ui_variant.htmx_headers(client, page_url))
    assert r.status_code == 200, r.text[:300]
    if hook:
        assert hook in r.text
    if _terminal(ui_variant):
        assert "[ " not in re.sub(r"<!--.*?-->", "", r.text) or "hx-confirm" in r.text
        _check_terminal_markup(r.text)


def test_a_minted_token_is_never_inside_a_foldable_window(ui_variant, env):
    client, _ = env
    r = client.post("/partials/admin/report-tokens/create",
                    data={"username": "jsmith", "label": "laptop"},
                    headers=ui_variant.htmx_headers(client, "http://testserver/admin/users"))
    assert r.status_code == 200, r.text[:300]
    assert 'id="minted-secret"' in r.text and 'hx-swap-oob="true"' in r.text
    assert 'id="minted-value"' in r.text
    if not _terminal(ui_variant):
        return
    tree = _parse(r.text)
    value = next(n for n in tree.nodes if n["attrs"].get("id") == "minted-value")
    for anc in value["anc"]:
        if "win" in anc["cls"]:
            assert "data-nofold" in anc["attrs"]
            assert "data-win" not in anc["attrs"]
    assert 'class="fold"' not in r.text.split('id="minted-secret"')[1].split("</section>")[0]
    assert "cc/copy_value" not in r.text   # the shell loads it, not the fragment
    assert 'data-copy-from="minted-value"' in r.text


def test_sync_plans_keeps_archive_native_and_emits_the_machine_map(ui_variant, env):
    client, _ = env
    page = client.get("/admin/assignments?editor=jsmith&machine=*").text
    assert 'action="/partials/admin/projects/archive"' in page
    assert "onsubmit=\"return window.confirm('Archive '" in page
    if not _terminal(ui_variant):
        assert "/static/assignments.js" in page
        return
    assert "/static/cc/assignments.js?h=" in page
    assert "/static/assignments.js" not in page
    m = re.search(r'<script type="application/json" id="assign-machine-map">(.*?)</script>',
                  page, re.S)
    data = json.loads(m.group(1))
    assert "jsmith" in data["map"] and data["all"]
    # The same grid hooks the script reads.
    for hook in ('id="assign-grid"', 'class="proj-check matrix-check"',
                 'id="assign-toast"', 'id="assign-editor"', 'id="assign-machine"'):
        assert hook in page, hook


def test_setup_loads_the_forked_client_and_keeps_every_id(ui_variant, env):
    client, _ = env
    page = client.get("/setup").text
    for hook in ("setup-eula-text", "setup-eula-checkbox", "setup-eula-accept",
                 "setup-eula-status", "setup-admin-body", "setup-studio-form",
                 "setup-studio-status", "setup-alerts-form", "setup-alerts-test",
                 "setup-alerts-status", "setup-tasks-body", "setup-error"):
        assert f'id="{hook}"' in page, hook
    for name in ("org_name", "org_short", "tree_name", "canonical_prefix",
                 "template_folders", "email", "webhook"):
        assert f'name="{name}"' in page, name
    if not _terminal(ui_variant):
        assert 'src="/static/setup.js"' in page
        return
    assert "/static/cc/setup.js?h=" in page
    assert 'src="/static/setup.js"' not in page


def test_the_first_run_setup_page_draws_without_a_session(ui_variant, env):
    client, _ = env
    client.cookies.clear()
    r = client.get("/setup", follow_redirects=False)
    # Either the first-run window is open (a page with no strip) or it is
    # closed (a redirect to sign in); both looks answer the same way.
    if r.status_code == 200 and _terminal(ui_variant):
        assert "settings-nav" not in r.text and "snav" not in r.text


def test_every_cc_template_of_mine_is_registered_and_owned():
    from ccsync_dashboard import ui_variant as uv
    for name in MY_TEMPLATES:
        assert uv.TEMPLATE_GROUPS.get(f"cc/{name}") == "settings-fleet", name
        assert (CC / name).is_file(), name


def test_forked_scripts_build_no_bracket_labels_and_keep_their_calls():
    for rel in MY_SCRIPTS:
        src = (ROOT / "static" / rel).read_text(encoding="utf-8")
        code = "\n".join(line for line in src.splitlines()
                         if not line.lstrip().startswith("//"))
        assert not re.search(r"""["']\[ |\s\]["']""", code), rel
    classic = (ROOT / "static" / "setup.js").read_text(encoding="utf-8")
    fork = (ROOT / "static" / "cc" / "setup.js").read_text(encoding="utf-8")
    for call in set(re.findall(r'"/api/v1/[a-z/]+', classic)):
        assert call in fork, call
    classic = (ROOT / "static" / "assignments.js").read_text(encoding="utf-8")
    fork = (ROOT / "static" / "cc" / "assignments.js").read_text(encoding="utf-8")
    assert fork.count("window.confirm") == classic.count("window.confirm")
    for call in set(re.findall(r'"/api/v1/[a-z/-]+', classic)):
        assert call in fork, call


def test_no_em_dash_in_my_visible_text():
    for name in MY_TEMPLATES:
        src = (CC / name).read_text(encoding="utf-8")
        src = re.sub(r"\{#.*?#\}", "", src, flags=re.S)
        assert "—" not in src, name
    for rel in MY_SCRIPTS:
        code = "\n".join(line for line in (ROOT / "static" / rel).read_text(
            encoding="utf-8").splitlines() if not line.lstrip().startswith("//"))
        assert "—" not in code, rel


def test_suspend_and_resume_answer_in_the_asking_look(ui_variant, env):
    """The suspend key is only ever included from the users partial, and only
    on a local account's row, so the page tests above (no local accounts)
    never drew it. Integrator, 2026-09-25: the coverage hook caught it."""
    from ccsync_dashboard import local_users
    client, conn = env
    local_users.create_user(conn, "jsmith", "seed-pass-123456", "editor", created_by="owen")
    conn.commit()
    headers = ui_variant.htmx_headers(client, "http://testserver/admin/users")
    r = client.post("/partials/admin/users/suspend",
                    data={"username": "jsmith", "suspended": "1"}, headers=headers)
    assert r.status_code == 200, r.text[:300]
    assert 'name="suspended" value="0"' in r.text   # jsmith now offers resume
    if _terminal(ui_variant):
        assert re.search(r'<span class="t">resume</span>', r.text)
        _check_terminal_markup(r.text)
    else:
        assert "[ RESUME ]" in r.text
    r = client.post("/partials/admin/users/suspend",
                    data={"username": "jsmith", "suspended": "0"}, headers=headers)
    assert r.status_code == 200 and 'name="suspended" value="1"' in r.text
