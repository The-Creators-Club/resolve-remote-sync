"""The terminal Site and Packages pages (UI redesign port phase 4, first half,
group `settings-fleet`, builder P4a, 2026-09-25).

Run through the `ui_variant` fixture: classic keeps drawing classic, and the
terminal look keeps every control the classic pages carry (a small control
census over the Packages partial), keeps the Site page's tabs DISPLAY ONLY
(no nested form, only site_store.KEYS names inside #settings-form, the other
forms siblings), lists in "roll back to" only builds a plain MAKE CURRENT
accepts, keeps the unsigned build's signature confirm, says the delete goes
to the trash for 30 days, puts no swap hook on a .win, and draws no
[ bracket ] label and no long dash.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth, site_store
from ccsync_dashboard import db as dbmod
from ccsync_dashboard import dashboard_update as dashupd_mod
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

from test_packages import (  # noqa: E402  (tests/ is on sys.path via conftest)
    SECRET, TEST_PUBKEY, insert_unsigned_package, publish,
)

ROOT = Path(__file__).resolve().parents[1]
CC = ROOT / "templates" / "cc"
MY_TEMPLATES = ("admin_settings.html", "partials/android_settings.html",
                "admin_packages.html", "partials/admin_packages.html",
                "partials/admin_dashboard_update.html")
MY_STATIC = ("cc/site_settings.js", "cc/dashboard_update.js", "cc/settings_fleet.css")
LONG_DASHES = ("—", "–")


@pytest.fixture
def env(ui_variant, tmp_path):
    settings = Settings(
        db_path=str(tmp_path / "p.db"), report_token="sekrit", session_secret=SECRET,
        admin_users=frozenset({"owen"}), packages_dir=str(tmp_path / "pkgs"),
        release_pubkeys=(TEST_PUBKEY,), release_soak_minutes=0, auth_method="local",
    )
    app = create_app(settings)
    with TestClient(app) as client:
        conn = dbmod.connect(settings.db_path)
        client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "owen"))
        # 0.2.0 was current (ever_current), 0.3.0 is current, 0.4.0 is staged
        # (newer), 0.1.5 is an unsigned build from before signing existed.
        assert publish(client, "0.2.0", body=b"v2", make_current=1).status_code == 200
        assert publish(client, "0.3.0", body=b"v3", make_current=1).status_code == 200
        assert publish(client, "0.4.0", body=b"v4").status_code == 200
        insert_unsigned_package(conn, settings, "windows", "0.1.5")
        yield client, conn, settings
        conn.close()


def _terminal(ui_variant) -> bool:
    return "settings-fleet" in ui_variant.groups


class _Tree(HTMLParser):
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
            "meta", "source", "track", "wbr", "path", "circle"}

    def __init__(self):
        super().__init__()
        self.stack: list[dict] = []
        self.nodes: list[dict] = []

    def handle_starttag(self, tag, attrs):
        a = {k: (v if v is not None else "") for k, v in attrs}
        node = {"tag": tag, "attrs": a, "cls": (a.get("class") or "").split(),
                "anc": list(self.stack), "kids": []}
        for anc in self.stack:
            anc["kids"].append(node)
        self.nodes.append(node)
        if tag not in self.VOID:
            self.stack.append(node)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i]["tag"] == tag:
                del self.stack[i:]
                break


def _parse(html: str) -> _Tree:
    t = _Tree()
    t.feed(html)
    return t


def _controls(html: str) -> set[tuple]:
    """(method, path, sorted field names) of every htmx form, the census key."""
    out = set()
    for n in _parse(html).nodes:
        for verb in ("hx-post", "hx-get", "hx-put", "hx-delete"):
            if verb in n["attrs"]:
                names = sorted({k["attrs"].get("name") for k in n["kids"]
                                if k["tag"] in ("input", "select", "textarea")
                                and k["attrs"].get("name")})
                path = n["attrs"][verb].split("?")[0]
                out.add((verb, path, tuple(names)))
    return out


def _visible_text(html: str) -> str:
    html = re.sub(r"(?s)<script.*?</script>|<style.*?</style>|\{#.*?#\}", "", html)
    return re.sub(r"<[^>]+>", " ", html)


# ------------------------------------------------------------- packages

def test_packages_page_renders_in_its_look(ui_variant, env):
    client, _conn, _settings = env
    page = client.get("/admin/packages")
    assert page.status_code == 200
    ui_variant.check_page(page.text)
    if _terminal(ui_variant):
        assert "cc/settings_fleet.css" in page.text
        assert "cc/dashboard_update.js" in page.text
        assert 'data-win="this_dashboard"' in page.text
        assert 'hx-get="/partials/admin/dashboard-update"' in page.text
    else:
        assert "cc/dashboard_update.js" not in page.text
        assert "[ OTHER VERSIONS HELD ON THIS SERVER ]" in page.text


def test_terminal_packages_rollback_select_and_held_rows(ui_variant, env):
    if not _terminal(ui_variant):
        pytest.skip("terminal only")
    client, conn, _settings = env
    html = client.get("/admin/packages").text
    tree = _parse(html)
    # The select lists only builds a plain MAKE CURRENT accepts: 0.2.0 (signed,
    # was current). Not the unsigned 0.1.5, not the newer staged 0.4.0.
    selects = [n for n in tree.nodes if n["tag"] == "select" and n["attrs"].get("name") == "version"]
    assert len(selects) == 1
    opts = [k["attrs"].get("value") for k in selects[0]["kids"] if k["tag"] == "option"]
    assert opts == ["", "0.2.0"]
    form = next(a for a in reversed(selects[0]["anc"]) if a["tag"] == "form")
    assert form["attrs"]["hx-post"] == "/partials/admin/packages/current"
    assert "hx-confirm" in form["attrs"] and form["attrs"].get("data-confirm-key")

    # Every held build keeps its own row, with delete, inside the pkg-other fold.
    assert 'data-key="pkg-other"' in html
    deletes = [n for n in tree.nodes if n["attrs"].get("hx-post") == "/partials/admin/packages/delete"]
    versions = sorted(k["attrs"]["value"] for n in deletes for k in n["kids"]
                      if k["attrs"].get("name") == "version")
    assert versions == ["0.1.5", "0.2.0", "0.4.0"]
    for d in deletes:
        q = d["attrs"]["hx-confirm"]
        assert "trash" in q and "30 days" in q
        assert d["attrs"].get("data-confirm-key", "").startswith("pkg-delete:")

    # The unsigned build cannot post force=1 without the signature confirm.
    forced = [n for n in tree.nodes if n["tag"] == "form" and any(
        k["attrs"].get("name") == "force" for k in n["kids"])]
    unsigned = [n for n in forced if any(k["attrs"].get("name") == "version"
                                         and k["attrs"].get("value") == "0.1.5" for k in n["kids"])]
    assert unsigned, "the unsigned build lost its typed override"
    for n in unsigned:
        assert "no release signature" in n["attrs"].get("hx-confirm", "")

    # The shortcut really does roll back.
    r = client.post("/partials/admin/packages/current",
                    data={"kind": "companion", "platform": "windows", "version": "0.2.0"},
                    headers=ui_variant.htmx_headers(client, "http://testserver/admin/packages"))
    assert r.status_code == 200
    assert dbmod.get_current_package(conn, "windows")["version"] == "0.2.0"
    assert "admin-packages-box" in r.text and "win" in r.text


def test_terminal_packages_keeps_every_classic_control(ui_variant, env):
    """The census, for this page: every (verb, path, fields) the classic panel
    offers is offered by the terminal one (it may add the rollback select)."""
    if ui_variant.name != "all":
        pytest.skip("needs both looks in one app")
    client, _conn, _settings = env
    classic = client.get("/partials/admin/packages",
                         headers={"HX-Request": "true", "X-CC-UI": ""})
    terminal = client.get("/partials/admin/packages",
                          headers=ui_variant.htmx_headers(client, "http://testserver/admin/packages"))
    assert classic.status_code == terminal.status_code == 200
    assert "[ MAKE CURRENT ]" in classic.text
    assert "sf-pkg" in terminal.text
    missing = _controls(classic.text) - _controls(terminal.text)
    assert not missing, missing


def test_terminal_packages_hooks_never_on_a_window(ui_variant, env):
    if not _terminal(ui_variant):
        pytest.skip("terminal only")
    client, _conn, _settings = env
    html = client.get("/admin/packages").text
    for n in _parse(html).nodes:
        if "win" in n["cls"]:
            assert "admin-packages-box" not in n["cls"]
            assert n["attrs"].get("id") not in ("dashboard-update", "admin-packages")
    ids = re.findall(r'\sid="([^"]+)"', html)
    assert len(ids) == len(set(ids)), [i for i in ids if ids.count(i) > 1]


def test_terminal_dashboard_update_partial(ui_variant, env, monkeypatch):
    if not _terminal(ui_variant):
        pytest.skip("terminal only")
    client, _conn, _settings = env
    view = {"image_mode": True, "running": "0.7.60", "image": "0.7.60", "source": "image",
            "runtime_id": "abcdef0123456789", "code_updates": [
                {"version": "0.7.61", "size_bytes": 1000, "published_at": "", "notes": "fixes"}],
            "runtime_updates": [], "rollback_candidates": [{"version": "0.7.58"}],
            "current": {"version": "0.7.59", "previous": "0.7.58", "applied_at": ""},
            "schema": {"safe": True, "backup": "pre-0.7.59.tar", "live": 57, "target": 57},
            "nas_hint": "Apps > ccsync > Update", "in_progress": False, "step": "idle",
            "message": "", "last_error": "", "backups": [], "boot_attempts": 0}
    monkeypatch.setattr(dashupd_mod, "status", lambda settings, state: view)
    r = client.get("/partials/admin/dashboard-update",
                   headers=ui_variant.htmx_headers(client, "http://testserver/admin/packages"))
    assert r.status_code == 200
    html = r.text
    assert 'id="dashboard-update"' in html
    assert "hx-swap-oob" not in html          # fetched by hand: no oob (3.1)
    assert 'data-dashupd-apply="0.7.61"' in html
    # Two select-plus-key pairs, one per flow, never one merged list.
    assert 'data-dashupd-for="dashupd-older-key"' in html
    assert re.search(r'id="dashupd-older-key"[^>]*data-dashupd-older="1"', html)
    assert 'data-dashupd-for="dashupd-rollback-key"' in html
    assert 'data-dashupd-rollback="0.7.58"' in html
    assert 'id="dashupd-restore-db"' in html
    _no_brackets_or_dashes(html)


# ------------------------------------------------------------------ site

def test_site_page_renders_in_its_look(ui_variant, env):
    client, _conn, _settings = env
    page = client.get("/admin/settings")
    assert page.status_code == 200
    ui_variant.check_page(page.text)
    if not _terminal(ui_variant):
        assert "cc/site_settings.js" not in page.text
        return
    html = page.text
    assert "cc/site_settings.js" in html
    assert re.search(r'src="/static/site_settings\.js', html) is None
    tree = _parse(html)
    tabs = [n for n in tree.nodes if n["attrs"].get("role") == "tab"]
    assert len(tabs) == 5
    ids = {n["attrs"].get("id") for n in tree.nodes}
    for t in tabs:
        assert t["attrs"]["aria-controls"] in ids
        assert t["attrs"].get("type") == "button"
    # No nested form, and the other forms are siblings of #settings-form.
    for n in tree.nodes:
        if n["tag"] == "form":
            assert not any(a["tag"] == "form" for a in n["anc"]), n["attrs"]
    settings_form = next(n for n in tree.nodes if n["attrs"].get("id") == "settings-form")
    kid_ids = {k["attrs"].get("id") for k in settings_form["kids"]}
    for other in ("settings-import-form", "android-form", "ui-groups-form", "ai-providers",
                  "ai-preference", "ai-cli-enabled"):
        assert other in ids, other
        assert other not in kid_ids, other
    # Serialised as site_settings.js does: only site_store.KEYS names.
    names = {k["attrs"]["name"] for k in settings_form["kids"]
             if k["tag"] in ("input", "select", "textarea") and k["attrs"].get("name")}
    allowed = set(site_store.KEYS)
    assert names <= allowed, names - allowed
    assert "indexer_model_tier" in names and "tier" not in names
    # Every non-submit button in the form is type=button (a fold never PUTs).
    for k in settings_form["kids"]:
        if k["tag"] == "button":
            assert k["attrs"].get("type") in ("button", "submit"), k["attrs"]
    _no_brackets_or_dashes(html)


# ---------------------------------------------------------- static facts

def _no_brackets_or_dashes(html: str) -> None:
    text = _visible_text(html)
    assert not re.search(r"\[ [A-Za-z]", text), re.findall(r"\[ [^\]]{0,30}\]", text)[:5]
    for ch in LONG_DASHES:
        assert ch not in text


def test_my_files_have_no_long_dash_and_no_bracket_label():
    for rel in MY_TEMPLATES:
        text = (CC / rel).read_text(encoding="utf-8")
        assert "creators" not in text.lower(), rel   # no customer names
        for ch in LONG_DASHES:
            assert ch not in text, rel
        assert not re.search(r"\[ [A-Z][A-Z ]+ \]", _visible_text(text)), rel
    for rel in MY_STATIC:
        text = (ROOT / "static" / rel).read_text(encoding="utf-8")
        for ch in LONG_DASHES:
            assert ch not in text, rel
        assert '"[ "' not in text and "'[ '" not in text, rel


def test_every_non_submit_button_in_my_templates_is_typed():
    for rel in MY_TEMPLATES:
        text = (CC / rel).read_text(encoding="utf-8")
        for tag in re.findall(r"<button\b[^>]*>", text):
            assert re.search(r'\btype="(button|submit)"', tag), (rel, tag)


def _node():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not on PATH")
    return node


_HARNESS = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[2], 'utf8');
function el(id) { return { id, attrs: {}, isConnected: true, parentNode: {}, classList: {toggle(){}},
  getAttribute(k) { return this.attrs[k] === undefined ? null : this.attrs[k]; },
  setAttribute(k, v) { this.attrs[k] = String(v); }, hasAttribute(k) { return k in this.attrs; } }; }
const nodes = { 'dashboard-update': el('dashboard-update'), 'dashupd-progress': el('dashupd-progress') };
let outer = null, reloaded = 0, appended = [];
Object.defineProperty(nodes['dashboard-update'], 'outerHTML', { set(v) { outer = v; } });
global.window = { location: { reload() { reloaded++; } }, confirm() { return true; } };
global.document = {
  body: { getAttribute(k) { return k === 'hx-headers' ? '{"X-CSRF-Token":"t","X-CC-UI":"chrome,settings-fleet"}' : null; },
          appendChild(n) { appended.push(n); } },
  getElementById(id) { return nodes[id] || null; },
  querySelector(s) { return s === '.cc-reload' ? (appended[0] || null) : null; },
  createElement() { return { setAttribute() {}, appendChild() {} }; },
  addEventListener() {},
};
let sent = null;
function answer(status, headers, body) {
  global.fetch = (url, opts) => { sent = opts; return Promise.resolve({ status, ok: status < 400,
    headers: { get: (k) => headers[k] || null }, text: () => Promise.resolve(body) }); };
}
eval(src);
(async () => {
  const out = {};
  answer(200, { 'HX-Refresh': 'true' }, '');
  await window.ccsyncDashUpdate.reloadPanel();
  out.refresh = { reloaded, outer, ui: sent.headers['X-CC-UI'], hx: sent.headers['HX-Request'] };
  reloaded = 0;
  answer(409, { 'X-CC-UI-Want': 'chrome' }, 'x');
  await window.ccsyncDashUpdate.reloadPanel();
  out.want = { reloaded, outer, line: appended.length };
  answer(200, {}, '<div id="dashboard-update">new</div>');
  await window.ccsyncDashUpdate.reloadPanel();
  out.ok = { outer };
  const key = el('k'); key.attrs['data-dashupd-apply'] = ''; key.attrs['data-dashupd-older'] = '1';
  nodes['k'] = key;
  const sel = { value: '0.7.58', matches: () => true, getAttribute: () => 'k' };
  window.ccsyncDashUpdate.onChange({ target: sel });
  out.sel = { apply: key.attrs['data-dashupd-apply'], disabled: key.disabled };
  console.log(JSON.stringify(out));
})();
"""


def test_cc_dashboard_update_js_reload_paths(tmp_path):
    node = _node()
    harness = tmp_path / "h.js"
    harness.write_text(_HARNESS, encoding="utf-8")
    proc = subprocess.run([node, str(harness), str(ROOT / "static" / "cc" / "dashboard_update.js")],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    # HX-Refresh: reload, never swap the empty body over the panel.
    assert out["refresh"] == {"reloaded": 1, "outer": None,
                              "ui": "chrome,settings-fleet", "hx": "true"}
    # 409 + Want: the reload line, the panel kept.
    assert out["want"]["reloaded"] == 0 and out["want"]["outer"] is None
    assert out["want"]["line"] == 1
    assert out["ok"]["outer"] == '<div id="dashboard-update">new</div>'
    # The select copies its value onto its key (the older-bundle flow).
    assert out["sel"] == {"apply": "0.7.58", "disabled": False}


def test_cc_site_settings_js_writes_only_the_classic_routes():
    src = (ROOT / "static" / "cc" / "site_settings.js").read_text(encoding="utf-8")
    classic = (ROOT / "static" / "site_settings.js").read_text(encoding="utf-8")
    cc_routes = set(re.findall(r'"(/api/v1/[a-z0-9_/-]+)', src))
    classic_routes = set(re.findall(r'"(/api/v1/[a-z0-9_/-]+)', classic))
    assert cc_routes, "no routes found"
    assert cc_routes <= classic_routes | {"/api/v1/admin/site"}, cc_routes - classic_routes
    assert "site-ask" in src          # import and undo ask through the dialog
