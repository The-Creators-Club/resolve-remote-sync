"""The UI port review's settings-* findings (docs/UI_PORT_REVIEW_2026-09-25.md,
fix builder F-settings, 2026-09-25).

  settings-1  Alerts Save sent 17 fields to a route capped at 16: every Save
              was a 400 "malformed form body". Server AND form.
  settings-2  a rollback refusal landed on the chosen OLDER row (inside the
              folded "other versions held" list) or nowhere at all.
  settings-3  on a phone, Sync plans / Packages / Setup scrolled sideways: the
              page stacks were grids with an auto track a nowrap bar could
              widen.
  settings-4  Alerts sent.log scrolled sideways inside a .scroll-y.
  settings-5  an in-page link to a tab ("AI providers") worked once.
  settings-6  dismissing a Health notice left it counted under open findings.

The browser halves run the shipped CSS / JS in headless Chrome (without
mobile emulation, which grows the layout viewport to the content and so hid
settings-3 from tools/mobile_sweep.js). Skipped where Chrome is absent.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import alerts, auth, ui
from ccsync_dashboard import db as dbmod
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings
from conftest import HX

DASH = Path(__file__).resolve().parents[1]
STATIC = DASH / "static"
SECRET = "test-secret-value-cc-settings-fix-1234567890"


def _chrome() -> str | None:
    for cand in (os.environ.get("CHROME"),
                 r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                 r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                 shutil.which("google-chrome"), shutil.which("chromium"),
                 shutil.which("chrome")):
        if cand and Path(cand).exists():
            return cand
    return None


CHROME = _chrome()
needs_chrome = pytest.mark.skipif(CHROME is None, reason="no Chrome on this machine")


@pytest.fixture
def env(tmp_path):
    settings = Settings(db_path=str(tmp_path / "d.db"), session_secret=SECRET,
                        admin_users=frozenset({"owen"}))
    with TestClient(create_app(settings)) as c:
        c.app.state.collector.stop()
        conn = dbmod.connect(settings.db_path)
        c.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "owen"))
        try:
            yield c, conn
        finally:
            conn.close()


def _csrf(client, page):
    m = re.search(r'name="csrf" content="([^"]+)"', client.get(page).text)
    return m.group(1) if m else ""


def _hx(client, page):
    headers = {**HX, "HX-Current-URL": "http://testserver" + page}
    headers["Origin"] = "http://testserver"
    headers["X-CSRF-Token"] = _csrf(client, page)
    return headers


class _FormValues(HTMLParser):
    """What a browser would submit for one form id: every named control
    inside it or pointing at it with form=, checked radios only."""

    def __init__(self, form_id):
        super().__init__()
        self.form_id = form_id
        self.stack: list[str | None] = []
        self.pairs: list[tuple[str, str]] = []
        self._select: str | None = None
        self._select_val: str | None = None
        self._first_opt: str | None = None

    def _owner(self, a):
        return a.get("form") or (self.stack[-1] if self.stack else None)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "form":
            self.stack.append(a.get("id"))
        elif tag == "input" and a.get("name") and self._owner(a) == self.form_id:
            typ = (a.get("type") or "text").lower()
            if typ in ("submit", "button"):
                return
            if typ in ("radio", "checkbox") and "checked" not in a:
                return
            self.pairs.append((a["name"], a.get("value") or ""))
        elif tag == "select" and a.get("name") and self._owner(a) == self.form_id:
            self._select, self._select_val, self._first_opt = a["name"], None, None
        elif tag == "option" and self._select:
            if self._first_opt is None:
                self._first_opt = a.get("value", "")
            if "selected" in a:
                self._select_val = a.get("value", "")

    def handle_endtag(self, tag):
        if tag == "form" and self.stack:
            self.stack.pop()
        elif tag == "select" and self._select:
            val = self._select_val if self._select_val is not None else (self._first_opt or "")
            self.pairs.append((self._select, val))
            self._select = None


def _form_values(html, form_id):
    p = _FormValues(form_id)
    p.feed(html)
    return p.pairs


# ------------------------------------------------------------ settings-1

def test_alerts_save_takes_every_setting_key_at_once(env):
    """17 keys (one per SETTING_KEYS entry) is what the form sends; the cap
    was 16 and parse_qs refused the whole body."""
    client, _conn = env
    assert len(alerts.SETTING_KEYS) > ui.MAX_FORM_FIELDS, \
        "the scenario needs more keys than the default cap"
    body = {k: "" for k in alerts.SETTING_KEYS}
    body.update({"alerts_sink": "none", "alerts_smtp_port": "587",
                 "alerts_smtp_tls": "1", "alerts_smtp_verify_tls": "1",
                 "alerts_weekly": "1", "alerts_heartbeat": "0",
                 "alerts_triage": "0", "alerts_triage_hours": "6,18"})
    r = client.post("/partials/admin/alerts/save", data=body,
                    headers={**HX, "Origin": "http://testserver",
                             "X-CSRF-Token": _csrf(client, "/admin/alerts")})
    assert r.status_code == 200, r.text[:300]
    assert "saved." in r.text


def test_alerts_save_still_refuses_a_flood_of_fields(env):
    client, _conn = env
    body = "&".join(f"a{i}=1" for i in range(ui.alerts_form_max_fields() + 1))
    r = client.post("/partials/admin/alerts/save", content=body,
                    headers={**HX, "Origin": "http://testserver",
                             "Content-Type": "application/x-www-form-urlencoded",
                             "X-CSRF-Token": _csrf(client, "/admin/alerts")})
    assert r.status_code == 400


def test_every_other_form_route_keeps_the_default_cap():
    src = (DASH / "src" / "ccsync_dashboard" / "ui.py").read_text(encoding="utf-8")
    widened = re.findall(r"await _form\(request, max_fields=(\w+)", src)
    assert widened == ["alerts_form_max_fields"], widened


def test_the_rendered_alerts_form_saves_as_the_browser_sends_it(env):
    """The whole rendered #alerts-form, posted as a browser would: 200 and
    "saved.", and its field count sits inside the route's own cap."""
    client, _conn = env
    html = client.get("/admin/alerts").text
    pairs = _form_values(html, "alerts-form")
    names = {k for k, _v in pairs}
    assert names == set(alerts.SETTING_KEYS), names ^ set(alerts.SETTING_KEYS)
    assert len(pairs) <= ui.alerts_form_max_fields()
    r = client.post("/partials/admin/alerts/save", data=dict(pairs),
                    headers=_hx(client, "/admin/alerts"))
    assert r.status_code == 200, r.text[:300]
    assert "saved." in r.text
    assert "malformed" not in r.text


# ------------------------------------------------------------ the browser

def _static_page(html: str) -> str:
    """A rendered page made loadable from disk: /static/ URLs point at the
    tree, scripts are dropped (layout is what is measured)."""
    html = re.sub(r"<script\b.*?</script>", "", html, flags=re.S)
    base = STATIC.as_uri() + "/"
    return re.sub(r'(href|src)="/static/([^"?]*)(\?[^"]*)?"',
                  lambda m: f'{m.group(1)}="{base}{m.group(2)}"', html)


def _chrome_dump(tmp_path: Path, page_html: str, width: int, name="page") -> str:
    """Load the page in an iframe `width` px wide: headless Chrome will not
    make a WINDOW narrower than 500 px, but a frame is its own viewport. The
    page posts its answer to the host, which prints it."""
    page = tmp_path / f"{name}.html"
    page.write_text(page_html, encoding="utf-8")
    host = tmp_path / f"{name}-host.html"
    host.write_text(f"""<!doctype html><html><body style="margin:0">
<iframe src="{page.as_uri()}" style="width:{width}px;height:900px;border:0"></iframe>
<script>window.addEventListener("message", function (e) {{
  var pre = document.createElement("pre"); pre.id = "out";
  pre.textContent = e.data; document.body.appendChild(pre);
}});</script></body></html>""", encoding="utf-8")
    out = subprocess.run(
        [CHROME, "--headless=new", "--disable-gpu", "--no-first-run",
         "--allow-file-access-from-files", f"--user-data-dir={tmp_path / ('profile-' + name)}",
         f"--window-size={max(width, 500) + 40},1000", "--virtual-time-budget=8000", "--dump-dom",
         host.as_uri()],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    return out.stdout + out.stderr


def _measure(tmp_path, html, width, name):
    probe = """<script>
window.addEventListener("load", function () { setTimeout(function () {
  var de = document.documentElement, worst = null;
  document.querySelectorAll("body *").forEach(function (el) {
    var cs = getComputedStyle(el);
    if (cs.overflowX !== "auto" && cs.overflowX !== "scroll") return;
    if (el.closest(".scroll-x") || /^(INPUT|SELECT|TEXTAREA)$/.test(el.tagName)) return;
    if (el.offsetParent === null) return;
    var by = el.scrollWidth - el.clientWidth;
    if (by > 1 && (!worst || by > worst.by)) worst = {by: by, cls: String(el.className)};
  });
  parent.postMessage(JSON.stringify({sw: de.scrollWidth, iw: window.innerWidth, inner: worst}), "*");
}, 300); });
</script>"""
    page = _static_page(html).replace("</body>", probe + "</body>")
    dump = _chrome_dump(tmp_path, page, width, name)
    m = re.search(r'<pre id="out">(.*?)</pre>', dump, flags=re.S)
    assert m, dump[-2000:]
    return json.loads(m.group(1).replace("&quot;", '"').replace("&amp;", "&"))


# ------------------------------------------------------------ settings-3

@needs_chrome
@pytest.mark.parametrize("path", ["/admin/assignments", "/admin/packages", "/setup"])
def test_settings_pages_do_not_scroll_sideways_on_a_phone(env, tmp_path, path):
    client, _conn = env
    r = client.get(path)
    assert r.status_code == 200, r.text[:300]
    assert 'data-ui="cc"' in r.text
    m = _measure(tmp_path, r.text, 390, "p" + re.sub(r"\W", "", path))
    assert m["iw"] == 390, m      # no mobile layout-viewport growth here
    assert m["sw"] <= m["iw"], f"{path} scrolls sideways at 390: {m}"


# ------------------------------------------------------------ settings-4

@needs_chrome
def test_alerts_sent_log_does_not_scroll_sideways_at_tablet_width(env, tmp_path):
    client, conn = env
    for i in range(3):
        conn.execute(
            "INSERT INTO alert_log (at, kind, subject, sent_to, ok, detail) "
            "VALUES (?, ?, ?, ?, 0, ?)",
            (f"2026-09-2{i}T08:00:00Z", "weekly",
             "a subject long enough to push the table well past a tablet column " * 2,
             "someone.with.a.long.address@example.com, another.long.address@example.com",
             "the channel refused it with a reason long enough to need the room"))
    conn.commit()
    r = client.get("/admin/alerts")
    assert r.status_code == 200
    m = _measure(tmp_path, r.text, 768, "alerts768")
    assert m["sw"] <= m["iw"], m
    assert m["inner"] is None, f"something outside a .scroll-x scrolls sideways: {m}"



# ------------------------------------------------ the htmx + cc.js harness
# The REAL htmx 1.9.12, cc.js and shell.html's inline keeper, against a
# fake XMLHttpRequest (the pattern of test_bug_hunt_2026_09_24_w2_d-ui.py,
# plus response headers, which HX-Trigger needs).

FAKE_XHR = r"""
window.__log = [];
window.__routes = [];   // [{verb, path, status, text, headers}]
function FakeXHR() {
  this.upload = {addEventListener: function () {}};
  this.readyState = 0; this.status = 0; this.responseText = ""; this.headers = {};
  this._listeners = {}; this._resp = {};
}
FakeXHR.prototype.open = function (verb, path) { this.verb = verb; this.path = path; };
FakeXHR.prototype.overrideMimeType = function () {};
FakeXHR.prototype.setRequestHeader = function (k, v) { this.headers[k] = v; };
FakeXHR.prototype.addEventListener = function (n, fn) { (this._listeners[n] = this._listeners[n] || []).push(fn); };
FakeXHR.prototype.getAllResponseHeaders = function () {
  var self = this;
  return Object.keys(this._resp).map(function (k) { return k + ": " + self._resp[k]; }).join("\r\n");
};
FakeXHR.prototype.getResponseHeader = function (name) {
  var want = String(name).toLowerCase();
  for (var k in this._resp) { if (k.toLowerCase() === want) return this._resp[k]; }
  return null;
};
FakeXHR.prototype.abort = function () {};
FakeXHR.prototype.send = function (body) {
  var self = this;
  var path = String(this.path).split("?")[0];
  window.__log.push(this.verb + " " + path);
  var route = null;
  for (var i = 0; i < window.__routes.length; i++) {
    var r = window.__routes[i];
    if (r.verb === this.verb && r.path === path) { route = r; break; }
  }
  if (!route) return;
  setTimeout(function () {
    self.readyState = 4; self.status = route.status || 200;
    self._resp = route.headers || {};
    self.responseText = typeof route.text === "function" ? route.text() : route.text;
    self.response = self.responseText;
    self.responseURL = self.path;
    self.onload();
  }, 5);
};
window.XMLHttpRequest = FakeXHR;
window.addEventListener("error", function (e) {
  window.__done({error: String(e.message) + " @" + e.lineno + ":" + e.colno});
});
window.__done = function (result) {
  var pre = document.createElement("pre");
  pre.id = "out";
  pre.textContent = JSON.stringify(result);
  document.body.appendChild(pre);
};
"""


def _shell_inline() -> str:
    text = (DASH / "templates" / "shell.html").read_text(encoding="utf-8")
    return "\n".join(b for b in re.findall(r"<script>(.*?)</script>", text, flags=re.S)
                     if "{{" not in b and "{%" not in b)


def _run_cc(tmp_path: Path, body: str, scenario: str, pre: str = "") -> dict:
    page = tmp_path / "cc.html"
    page.write_text(f"""<!doctype html><html><head><meta charset="utf-8">
<script>{FAKE_XHR}</script>
<script>{pre}</script>
<script src="{(STATIC / 'htmx.min.js').as_uri()}"></script>
<script src="{(STATIC / 'cc' / 'cc.js').as_uri()}"></script>
<script>{_shell_inline()}</script>
<style>.win.collapsed > :not(.bar) {{ display: none; }} [hidden] {{ display: none; }}</style>
</head><body>{body}
<script>
window.addEventListener("load", function () {{
  setTimeout(function () {{
    try {{ {scenario} }} catch (e) {{ window.__done({{error: String(e && e.stack || e)}}); }}
  }}, 100);
}});
</script>
</body></html>""", encoding="utf-8")
    out = subprocess.run(
        [CHROME, "--headless=new", "--disable-gpu", "--no-first-run",
         "--allow-file-access-from-files", f"--user-data-dir={tmp_path / 'profile-cc'}",
         "--window-size=1280,900", "--virtual-time-budget=15000", "--dump-dom",
         page.as_uri()],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    m = re.search(r'<pre id="out">(.*?)</pre>', out.stdout, flags=re.S)
    assert m, f"the page never reported: {out.stdout[-2000:]} {out.stderr[-2000:]}"
    raw = (m.group(1).replace("&quot;", '"').replace("&lt;", "<")
           .replace("&gt;", ">").replace("&amp;", "&"))
    result = json.loads(raw)
    assert "error" not in result, result["error"]
    return result


def _js(s: str) -> str:
    return json.dumps(s)


# ------------------------------------------------------------ settings-2

from test_packages import TEST_PUBKEY, insert_unsigned_package, publish  # noqa: E402
from test_packages import SECRET as PKG_SECRET  # noqa: E402


@pytest.fixture
def pkg_env(tmp_path):
    settings = Settings(
        db_path=str(tmp_path / "p.db"), report_token="sekrit", session_secret=PKG_SECRET,
        admin_users=frozenset({"owen"}), packages_dir=str(tmp_path / "pkgs"),
        release_pubkeys=(TEST_PUBKEY,), release_soak_minutes=0, auth_method="local",
    )
    with TestClient(create_app(settings)) as client:
        conn = dbmod.connect(settings.db_path)
        client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(PKG_SECRET, "owen"))
        # 0.2.0 was current, 0.3.0 is current: 0.2.0 is the rollback choice.
        assert publish(client, "0.2.0", body=b"v2", make_current=1).status_code == 200
        assert publish(client, "0.3.0", body=b"v3", make_current=1).status_code == 200
        insert_unsigned_package(conn, settings, "windows", "0.1.5")
        yield client, conn, settings
        conn.close()


def _pkg_post(client, data):
    return client.post("/partials/admin/packages/current", data=data,
                       headers={**HX, "HX-Current-URL": "http://testserver/admin/packages"})


def _refusal_rows(html):
    """The version of every row carrying a row refusal."""
    out = []
    for chunk in re.split(r'<tr class="[^"]*pkg-row[^"]*">', html)[1:]:
        chunk = chunk.split("</tr>", 1)[0]
        if "row-refusal" in chunk:
            m = re.search(r'<b class="num">([^<]+)</b>', chunk)
            out.append(m.group(1) if m else "?")
    return out


def test_the_rollback_select_names_the_row_it_sits_on(pkg_env):
    client, _conn, _settings = pkg_env
    html = client.get("/admin/packages").text
    form = re.search(r'<form class="cell-form rb".*?</form>', html, flags=re.S)
    assert form, "no rollback form"
    assert 'name="row_version" value="0.3.0"' in form.group(0)


def test_a_refused_rollback_is_drawn_on_the_served_row(pkg_env):
    """The chosen build vanished between render and click: the refusal used
    to be keyed to 0.2.0's row, which was gone, and drew nowhere."""
    client, conn, _settings = pkg_env
    conn.execute("DELETE FROM companion_packages WHERE version = '0.2.0'")
    conn.commit()
    r = _pkg_post(client, {"kind": "companion", "platform": "windows",
                           "row_version": "0.3.0", "version": "0.2.0"})
    assert r.status_code == 200, r.text[:300]
    assert _refusal_rows(r.text) == ["0.3.0"], _refusal_rows(r.text)
    assert dbmod.get_current_package(conn, "windows")["version"] == "0.3.0"


def test_a_refusal_for_no_row_on_the_page_falls_back_to_the_banner(pkg_env):
    client, _conn, _settings = pkg_env
    r = _pkg_post(client, {"kind": "companion", "platform": "windows",
                           "version": "7.7.7"})
    assert r.status_code == 200
    assert _refusal_rows(r.text) == []
    assert "error-banner" in r.text and "7.7.7" in r.text


def test_a_refusal_on_a_held_row_still_lands_on_that_row(pkg_env):
    client, _conn, _settings = pkg_env
    r = _pkg_post(client, {"kind": "companion", "platform": "windows",
                           "version": "0.1.5"})
    assert _refusal_rows(r.text) == ["0.1.5"]
    assert "error-banner" not in r.text


@needs_chrome
def test_a_row_refusal_inside_folded_held_builds_is_opened_up_to(tmp_path):
    """The real cc.js: after an outerHTML swap whose refusal sits inside a
    folded window AND a closed <details data-key>, both open."""
    box = """<div class="admin-packages-box">
  <section class="win" data-win="other_versions_held"><div class="bar"><button class="fold" type="button" aria-expanded="true"></button><h2 class="t">held</h2></div>
    <details class="fold pkg-other" data-key="pkg-other"><summary>show</summary><div class="body">
      <table><tr class="pkg-row"><td><form hx-post="/partials/admin/packages/current" hx-target="closest .admin-packages-box" hx-swap="outerHTML">
        <button type="submit" id="go">make current</button></form>%s</td></tr></table>
    </div></details>
  </section></div>"""
    answer = box % '<div class="note err row-refusal" role="alert"><span class="grow">refused</span></div>'
    pre = ("try { localStorage.setItem('ccsync.fold:' + location.pathname, "
           "JSON.stringify({other_versions_held: 1})); } catch (e) {}")
    scenario = """
window.__routes.push({verb: "POST", path: "/partials/admin/packages/current", text: %s});
var before = document.querySelector(".win").classList.contains("collapsed");
htmx.trigger(document.querySelector("form"), "submit");
setTimeout(function () {
  var ref = document.querySelector(".row-refusal");
  var d = document.querySelector("details.pkg-other");
  var win = document.querySelector(".win");
  window.__done({before: before, found: !!ref, open: d && d.hasAttribute("open"),
                 folded: win.classList.contains("collapsed"),
                 visible: !!(ref && ref.offsetParent)});
}, 600);
""" % _js(answer)
    result = _run_cc(tmp_path, box % "", scenario, pre=pre)
    assert result["before"] is True, "the harness did not fold the window first"
    assert result["found"] is True
    assert result["open"] is True, "the held-builds list stayed shut over the refusal"
    assert result["folded"] is False, "the window stayed folded over the refusal"
    assert result["visible"] is True


# ------------------------------------------------------------ settings-5

@needs_chrome
def test_an_in_page_link_to_a_tab_works_every_time(tmp_path):
    body = """
<div class="tabs" role="tablist" id="site-tabs">
  <button type="button" role="tab" id="tab-features" aria-controls="panel-features" aria-selected="true">features</button>
  <button type="button" role="tab" id="tab-ai" aria-controls="panel-ai" aria-selected="false">ai</button>
</div>
<div id="panel-features"><a class="hi" id="link" href="#ai-providers">AI providers</a></div>
<div id="panel-ai" hidden><section class="win" data-win="your_ai_providers" id="ai-providers">providers</section></div>"""
    scenario = """
function state() {
  return {hash: location.hash, ai: !document.getElementById("panel-ai").hidden,
          feat: !document.getElementById("panel-features").hidden};
}
document.getElementById("link").click();
setTimeout(function () {
  var first = state();
  document.getElementById("tab-features").click();
  setTimeout(function () {
    var back = state();
    document.getElementById("link").click();
    setTimeout(function () { window.__done({first: first, back: back, second: state()}); }, 200);
  }, 200);
}, 200);
"""
    result = _run_cc(tmp_path, body, scenario)
    assert result["first"]["ai"] is True, result
    assert result["back"]["feat"] is True, result
    assert result["second"] == {"hash": "#ai-providers", "ai": True, "feat": False}, result


# ------------------------------------------------------------ settings-6

def test_a_dismiss_tells_the_page_to_reread_open_findings(env):
    client, conn = env
    dbmod.notice(conn, kind="project_nested_marker", subject="nas", severity="error",
                 body="something broke", fix="do the thing")
    conn.commit()
    page = client.get("/admin/health").text
    count = re.search(r'<span id="htab-open-count">\s*\((\d+)\)</span>', page)
    assert count, "the open findings tab count has no id to be replaced by"
    before = int(count.group(1))
    lst = re.search(r'<div[^>]*id="health-open-list"[^>]*>', page, flags=re.S)
    assert lst and 'hx-trigger="cc-health-changed from:body"' in lst.group(0)
    assert 'hx-select="#health-open-list"' in lst.group(0)
    assert "#htab-open-count" in lst.group(0)
    assert "something broke" in page.split('id="health-open-list"', 1)[1]
    nid = conn.execute("SELECT id FROM notices WHERE body = 'something broke'").fetchone()[0]
    r = client.post(f"/partials/health-notices/{nid}/dismiss",
                    headers=_hx(client, "/admin/health"))
    assert r.status_code == 200
    assert r.headers.get("HX-Trigger") == "cc-health-changed"
    after = client.get("/admin/health").text
    m = re.search(r'<span id="htab-open-count">\s*(?:\((\d+)\))?</span>', after)
    assert m and int(m.group(1) or 0) < before
    listed = after.split('id="health-open-list"', 1)[1].split('id="hpanel-notices"', 1)[0]
    assert "something broke" not in listed


def test_a_dismiss_of_a_gone_notice_triggers_nothing(env):
    client, _conn = env
    r = client.post("/partials/health-notices/999999/dismiss",
                    headers=_hx(client, "/admin/health"))
    assert r.status_code == 200
    assert "HX-Trigger" not in r.headers


@needs_chrome
def test_the_open_findings_tab_rereads_when_a_notice_is_dismissed(tmp_path):
    """Real htmx: the dismiss answer's HX-Trigger makes #health-open-list
    fetch the page and take its list and the tab count."""
    def page(n):
        rows = "".join(f'<div class="prob">finding {i}</div>' for i in range(n))
        return f"""<div class="tabs" role="tablist"><button type="button" role="tab" id="htab-open" aria-controls="hpanel-open" aria-selected="true">open findings<span id="htab-open-count"> ({n})</span></button>
<button type="button" role="tab" id="htab-notices" aria-controls="hpanel-notices" aria-selected="false">notices</button></div>
<div id="hpanel-open"><span class="meta" id="health-open-meta"><b>{n}</b> open</span>
<div class="scroll-y hl-list" id="health-open-list" hx-get="/admin/health" hx-trigger="cc-health-changed from:body"
 hx-select="#health-open-list" hx-swap="outerHTML" hx-select-oob="#htab-open-count,#health-open-meta">{rows}</div></div>
<div id="hpanel-notices" hidden><div id="health-notices-body"><form hx-post="/partials/health-notices/1/dismiss" hx-target="#health-notices-body"><button id="dismiss">dismiss</button></form></div></div>"""
    scenario = """
window.__routes.push({verb: "POST", path: "/partials/health-notices/1/dismiss",
                      headers: {"HX-Trigger": "cc-health-changed"}, text: "<div>gone</div>"});
window.__routes.push({verb: "GET", path: "/admin/health", text: %s});
htmx.trigger(document.querySelector("#health-notices-body form"), "submit");
setTimeout(function () {
  window.__done({count: document.getElementById("htab-open-count").textContent,
                 rows: document.querySelectorAll("#health-open-list .prob").length,
                 meta: document.getElementById("health-open-meta").textContent,
                 log: window.__log});
}, 800);
""" % _js("<html><body>" + page(1) + "</body></html>")
    result = _run_cc(tmp_path, page(2), scenario)
    assert "GET /admin/health" in result["log"], result
    assert result["count"].strip() == "(1)", result
    assert result["rows"] == 1, result
    assert result["meta"].startswith("1"), result
