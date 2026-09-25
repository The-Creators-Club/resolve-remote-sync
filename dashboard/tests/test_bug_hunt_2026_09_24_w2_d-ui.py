"""Wave 2 of the 2026-09-24 hunt's fix pass, group d-ui (chunks 1 to 4).

  ui-dash-main-1   the sidebar tick folded the tree shut and duplicated the
                   sheet handle (details keeper read a detached target).
  ui-dash-main-2   the DUI-6 refusal mover searched the detached old panel.
  ui-dash-main-3   the project page's 10 s poll wiped MOVE / SHARE A FOLDER.
  ui-dash-main-7   [ UNDO ] on a TICKED row unticked with no question.
  ui-dash-main-8   the sidebar poll shut the phone's projects sheet.
  ui-dash-admin-2  "releases itself 0s ago" (logic-admin-2 is the same).
  ui-dash-admin-3  the Users / Packages polls wiped forms and orphaned writes.
  ui-dash-admin-5  alerts / recovery / protection results landed off-screen.

The browser half runs the REAL htmx 1.9.12 in headless Chrome against a fake
XMLHttpRequest: the tests these findings regressed (DUI-6) passed against a
hand-built event detail that htmx never sends, which is how the mover shipped
without ever working. Skipped where Chrome is not installed.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth, ui
from ccsync_dashboard import db as dbmod
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

DASH = Path(__file__).resolve().parents[1]
STATIC = DASH / "static"
TEMPLATES = DASH / "templates"
SECRET = "test-secret-value-w2-d-ui-1234567890"
TOKEN = "companion-token-w2-d-ui-1234567890"


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


# ------------------------------------------------------------ the harness

FAKE_XHR = r"""
window.__log = [];
window.__routes = [];   // [{verb, path, status, text, hold}]
function FakeXHR() {
  this.upload = {addEventListener: function () {}};
  this.readyState = 0; this.status = 0; this.responseText = ""; this.headers = {};
  this._listeners = {};
}
FakeXHR.prototype.open = function (verb, path) { this.verb = verb; this.path = path; };
FakeXHR.prototype.overrideMimeType = function () {};
FakeXHR.prototype.setRequestHeader = function (k, v) { this.headers[k] = v; };
FakeXHR.prototype.addEventListener = function (n, fn) { (this._listeners[n] = this._listeners[n] || []).push(fn); };
FakeXHR.prototype.getAllResponseHeaders = function () { return ""; };
FakeXHR.prototype.getResponseHeader = function () { return null; };
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
  if (!route || route.hold) return;           // a request still in flight
  setTimeout(function () {
    self.readyState = 4; self.status = route.status || 200;
    self.responseText = typeof route.text === "function" ? route.text() : route.text;
    self.response = self.responseText;   // htmx 1.9.12 swaps xhr.response
    self.responseURL = self.path;
    self.onload();
  }, 5);
};
window.XMLHttpRequest = FakeXHR;
window.addEventListener("error", function (e) {
  window.__done({error: String(e.message) + " @" + e.lineno + ":" + e.colno + " " + (e.error && e.error.stack)});
});
window.__done = function (result) {
  var pre = document.createElement("pre");
  pre.id = "out";
  pre.textContent = JSON.stringify(result);
  document.body.appendChild(pre);
};
"""


def _inline_base_script() -> str:
    """base.html's own inline <script> (the details keeper and the fragment
    scroll), taken from the template so the test runs what ships."""
    text = (TEMPLATES / "base.html").read_text(encoding="utf-8")
    blocks = re.findall(r"<script>(.*?)</script>", text, flags=re.S)
    assert blocks, "base.html has no inline script"
    return "\n".join(blocks)


def _run_page(tmp_path: Path, body: str, scenario: str) -> dict:
    page = tmp_path / "page.html"
    page.write_text(f"""<!doctype html><html><head><meta charset="utf-8">
<script>{FAKE_XHR}</script>
<script>{_inline_base_script()}</script>
<script src="{(STATIC / 'htmx.min.js').as_uri()}"></script>
<script src="{(STATIC / 'htmx_errors.js').as_uri()}"></script>
<style>.spacer {{ height: 3000px; }}</style>
</head><body>{body}
<script>
document.addEventListener("DOMContentLoaded", function () {{
  setTimeout(function () {{
    try {{ {scenario} }} catch (e) {{ window.__done({{error: String(e && e.stack || e)}}); }}
  }}, 50);
}});
</script>
</body></html>""", encoding="utf-8")
    out = subprocess.run(
        [CHROME, "--headless=new", "--disable-gpu", "--no-first-run",
         "--allow-file-access-from-files", f"--user-data-dir={tmp_path / 'profile'}",
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


# ------------------------------------------------ ui-dash-main-1 (browser)

@needs_chrome
def test_an_outerhtml_swap_keeps_the_groups_the_reader_opened(tmp_path):
    """htmx leaves the removed element in detail.target after an outerHTML
    swap; the keeper restored into it, so the new tree came back shut."""
    body = """
<div id="tree-host"><nav class="projects" id="tree">
  <details class="proj-group" data-key="grp:2026"><summary>2026</summary>
    <input type="checkbox" hx-post="/tick" hx-target="closest .projects" hx-swap="outerHTML">
  </details>
</nav></div>"""
    scenario = """
window.__routes.push({verb: "POST", path: "/tick", text:
  '<nav class="projects" id="tree" data-new="1"><details class="proj-group" data-key="grp:2026">'
  + '<summary>2026</summary><input type="checkbox" checked></details></nav>'});
document.querySelector("details").setAttribute("open", "");
document.querySelector("input").click();
setTimeout(function () {
  var d = document.querySelector('details[data-key="grp:2026"]');
  window.__done({open: d.hasAttribute("open"), swapped: !!document.querySelector("[data-new]")});
}, 500);
"""
    result = _run_page(tmp_path, body, scenario)
    assert result["swapped"] is True, "the swap did not happen"
    assert result["open"] is True, "the group the reader opened was folded shut"


@needs_chrome
def test_a_swap_that_replaces_the_open_sheet_opens_the_new_one(tmp_path):
    """On a phone the tick's answer replaced the open <nav popover> with a
    new, closed one: the sheet shut under the editor after every tick."""
    body = """
<aside class="sidebar">
  <button popovertarget="projects-sheet">[ PROJECTS ]</button>
  <nav class="projects sheet" id="projects-sheet" popover>
    <input type="checkbox" hx-post="/tick" hx-target="closest .sidebar" hx-swap="innerHTML">
  </nav>
</aside>"""
    scenario = """
window.__routes.push({verb: "POST", path: "/tick", text:
  '<button popovertarget="projects-sheet">[ PROJECTS ]</button>'
  + '<nav class="projects sheet" id="projects-sheet" popover data-new="1"><input type="checkbox" checked></nav>'});
document.getElementById("projects-sheet").showPopover();
document.querySelector("input").click();
setTimeout(function () {
  var nav = document.getElementById("projects-sheet");
  window.__done({open: nav.matches(":popover-open"),
                 handles: document.querySelectorAll("button[popovertarget]").length,
                 swapped: nav.hasAttribute("data-new")});
}, 500);
"""
    result = _run_page(tmp_path, body, scenario)
    assert result["swapped"] is True, "the swap did not happen"
    assert result["handles"] == 1
    assert result["open"] is True, "the projects sheet shut after the tick"


# ------------------------------------------------ ui-dash-main-1 (markup)

def test_the_sidebar_tick_swaps_the_aside_not_the_nav():
    """The answer is the whole partial (handle + nav); swapping it over the
    nav alone added a second [ PROJECTS ] handle on every tick."""
    text = (TEMPLATES / "partials" / "sidebar.html").read_text(encoding="utf-8")
    assert 'hx-target="closest .projects" hx-swap="outerHTML"' not in text
    assert 'hx-target="closest .sidebar" hx-swap="innerHTML"' in text
    # Every page that includes the partial puts it inside an aside.sidebar,
    # which is what `closest .sidebar` resolves to.
    for page in TEMPLATES.glob("*.html"):
        body = page.read_text(encoding="utf-8")
        if '{% include "partials/sidebar.html" %}' in body:
            before = body.split('{% include "partials/sidebar.html" %}', 1)[0]
            assert before.rfind('<aside class="sidebar"') > before.rfind("</"), page.name


# -------------------------------------- ui-dash-main-2 / admin-5 (browser)

def _panel(banner_html: str, extra_form: str = "") -> str:
    return f"""
<div id="panel">
  <div class="spacer"></div>
  {extra_form}
  <form hx-post="/do" hx-target="#panel" hx-swap="outerHTML">
    <input type="hidden" name="key" value="b"><button type="submit">[ GO ]</button>
  </form>
</div>""", f"""
'<div id="panel">{banner_html}<div class="spacer"></div>{extra_form.replace(chr(10), "")}'
  + '<form hx-post="/do" hx-target="#panel" hx-swap="outerHTML">'
  + '<input type="hidden" name="key" value="b"><button type="submit">[ GO ]</button></form></div>'"""


def _mover_scenario(response_js: str) -> str:
    return """
window.__routes.push({verb: "POST", path: "/do", text: %s});
window.scrollTo(0, 99999);
var buttons = document.querySelectorAll("button");
buttons[buttons.length - 1].click();
setTimeout(function () {
  var b = document.querySelector(".error-banner, .result-banner");
  var next = b && b.nextElementSibling;
  var r = b.getBoundingClientRect();
  window.__done({
    beside: !!(next && next.tagName === "FORM" && next.querySelector("input[value=b]")),
    marked: b.className,
    visible: r.top >= 0 && r.bottom <= window.innerHeight
  });
}, 800);
""" % response_js


@needs_chrome
def test_a_refusal_on_an_outerhtml_panel_lands_beside_its_button(tmp_path):
    body, response = _panel('<div class="banner error-banner">refused: no</div>')
    result = _run_page(tmp_path, body, _mover_scenario(response))
    assert result["beside"] is True, "the refusal stayed at the top of the panel"
    assert "form-error" in result["marked"]
    assert result["visible"] is True


@needs_chrome
def test_a_result_banner_lands_beside_the_form_that_was_pressed(tmp_path):
    """ui-dash-admin-5: two forms post to one path (Protection's two date
    acks); the answer goes beside the one whose hidden key was sent."""
    other = ('<form hx-post="/do" hx-target="#panel" hx-swap="outerHTML">'
             '<input type="hidden" name="key" value="a"><button type="submit">[ A ]</button></form>')
    body, response = _panel('<div class="muted result-banner">the test could not be sent</div>',
                            extra_form=other)
    result = _run_page(tmp_path, body, _mover_scenario(response))
    assert result["beside"] is True
    assert "form-result" in result["marked"]
    assert result["visible"] is True


def test_the_three_admin_panels_mark_their_banners_for_the_mover():
    for name, err, notice in (("admin_alerts", "error", "notice"),
                              ("recovery", "recovery_error", "recovery_notice"),
                              ("protection", "protection_error", "protection_notice")):
        text = (TEMPLATES / "partials" / f"{name}.html").read_text(encoding="utf-8")
        assert f'{{% if {err} %}}<div class="banner error-banner">' in text, name
        assert re.search(r"\{% if " + notice + r" %\}<div class=\"muted result-banner\"", text), name


# ------------------------------- ui-dash-main-3 / admin-3 / main-8 (browser)

POLLED = """
<div id="polled" hx-get="/poll" hx-trigger="every 1s" hx-swap="innerHTML">
  <form hx-post="/write" hx-target="#polled" hx-swap="innerHTML">
    <input type="text" name="path" value="">
    <select name="to"><option value="a" selected>a</option><option value="b">b</option></select>
    <button type="submit">[ GO ]</button>
  </form>
  <nav id="sheet" popover>sheet</nav>
</div>"""
POLL_ANSWER = ("'<form hx-post=\"/write\" hx-target=\"#polled\" hx-swap=\"innerHTML\">"
               "<input type=\"text\" name=\"path\" value=\"\"><select name=\"to\">"
               "<option value=\"a\" selected>a</option><option value=\"b\">b</option></select>"
               "<button type=\"submit\">[ GO ]</button></form><nav id=\"sheet\" popover>sheet</nav>"
               "<i data-new=\"1\"></i>'")


def _polls(log):
    return sum(1 for line in log if line == "GET /poll")


@needs_chrome
def test_a_poll_does_not_wipe_a_field_being_typed_in(tmp_path):
    scenario = """
window.__routes.push({verb: "GET", path: "/poll", text: %s});
var input = document.querySelector("input[name=path]");
input.focus();
input.value = "B-roll/A001_0512.braw";
input.dispatchEvent(new Event("input", {bubbles: true}));
setTimeout(function () {
  var focused = document.activeElement === document.querySelector("input[name=path]");
  var value = document.querySelector("input[name=path]").value;
  // Blurred but still typed: the panel keeps it too.
  document.querySelector("input[name=path]").blur();
  setTimeout(function () {
    window.__done({focused: focused, value: value,
                   after_blur: document.querySelector("input[name=path]").value,
                   log: window.__log});
  }, 2500);
}, 3500);
""" % POLL_ANSWER
    result = _run_page(tmp_path, POLLED, scenario)
    assert result["value"] == "B-roll/A001_0512.braw", result
    assert result["focused"] is True
    assert result["after_blur"] == "B-roll/A001_0512.braw"
    assert _polls(result["log"]) == 0, result


@needs_chrome
def test_a_poll_resumes_once_nothing_is_being_done(tmp_path):
    """The pause is a skip, not a stop: an untouched panel still refreshes."""
    scenario = """
window.__routes.push({verb: "GET", path: "/poll", text: %s});
setTimeout(function () {
  window.__done({log: window.__log, swapped: !!document.querySelector("[data-new]")});
}, 3500);
""" % POLL_ANSWER
    result = _run_page(tmp_path, POLLED, scenario)
    assert _polls(result["log"]) >= 2, result
    assert result["swapped"] is True


@needs_chrome
def test_a_poll_does_not_orphan_a_write_in_flight(tmp_path):
    """ui-dash-admin-3: a NAS create takes up to two minutes. The poll used to
    replace the busy form and detach the box the answer was headed for."""
    scenario = """
window.__routes.push({verb: "GET", path: "/poll", text: %s});
window.__routes.push({verb: "POST", path: "/write", hold: true});
document.querySelector("button").click();
setTimeout(function () {
  window.__done({log: window.__log,
                 busy: document.querySelector("form").classList.contains("htmx-request")});
}, 3500);
""" % POLL_ANSWER
    result = _run_page(tmp_path, POLLED, scenario)
    assert "POST /write" in result["log"]
    assert _polls(result["log"]) == 0, result
    assert result["busy"] is True, "the busy form was replaced by a fresh one"


@needs_chrome
def test_a_poll_does_not_shut_an_open_sheet(tmp_path):
    """ui-dash-main-8: the sidebar's 30 s beat closed the phone's sheet."""
    scenario = """
window.__routes.push({verb: "GET", path: "/poll", text: %s});
document.getElementById("sheet").showPopover();
setTimeout(function () {
  window.__done({log: window.__log,
                 open: document.getElementById("sheet").matches(":popover-open")});
}, 3500);
""" % POLL_ANSWER
    result = _run_page(tmp_path, POLLED, scenario)
    assert result["open"] is True
    assert _polls(result["log"]) == 0, result


# ------------------------------------------------ ui-dash-main-7 (server)

@pytest.fixture
def env(tmp_path):
    db_path = tmp_path / "w2dui.db"
    settings = Settings(db_path=str(db_path), session_secret=SECRET,
                        report_token=TOKEN, admin_users=frozenset({"owen"}))
    app = create_app(settings)
    with TestClient(app) as client:
        conn = dbmod.connect(db_path)
        now = dbmod.utcnow_iso()
        dbmod.upsert_project(conn, "2026-ff5-elections", "2026/FF5/Elections", "/data/e", now)
        conn.commit()
        client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "owen"))
        yield client, conn
        conn.close()


def _report(client, editor, machine):
    resp = client.post("/api/v1/report", json={
        "editor_name": editor, "machine": machine, "machine_id": f"mid-{machine}",
        "reported_at": "2026-09-25T10:00:00+00:00", "lanes": []}, headers={
        "X-CCSync-Token": TOKEN,
        "X-CCSync-Identity": auth.make_identity_token(SECRET, editor)})
    assert resp.status_code == 200, resp.text


def test_undoing_a_person_tick_asks_first_and_names_the_computers(env):
    client, conn = env
    _report(client, "leso", "EDIT-PC")
    _report(client, "leso", "LAPTOP")
    assert client.put("/api/v1/selection/leso/2026-ff5-elections").status_code == 200
    html = client.get("/partials/plan-changes").text
    m = re.search(r'hx-post="/partials/plan-changes/\d+/undo"[^>]*>', html, flags=re.S)
    assert m, html
    form = m.group(0)
    assert "hx-confirm=" in form, "a person-wide untick with no question"
    assert "2026/FF5/Elections" in form
    assert "EDIT-PC" in form and "LAPTOP" in form
    assert "2 computers" in form
    assert "\u2014" not in form


def test_undoing_an_untick_puts_back_without_a_question(env):
    """Putting a project BACK removes nothing, so it needs no confirm."""
    client, conn = env
    _report(client, "leso", "EDIT-PC")
    client.put("/api/v1/selection/leso/2026-ff5-elections")
    client.delete("/api/v1/selection/leso/2026-ff5-elections")
    rows = dbmod.recent_plan_changes(conn, dbmod.utcnow_iso())
    untick_id = next(r["id"] for r in rows if r["action"] == dbmod.AUDIT_UNTICK)
    html = client.get("/partials/plan-changes").text
    form = re.search(rf'hx-post="/partials/plan-changes/{untick_id}/undo"[^>]*>', html).group(0)
    assert "hx-confirm" not in form


def test_the_undo_notice_and_the_row_name_the_folder_not_the_slug(env):
    client, conn = env
    _report(client, "leso", "EDIT-PC")
    client.put("/api/v1/selection/leso/2026-ff5-elections")
    tick_id = dbmod.fetch_audit(conn)[0]["id"]
    html = client.post(f"/partials/plan-changes/{tick_id}/undo").text
    assert "removed 2026/FF5/Elections again for leso" in html
    assert '<td class="mono-sm" title="2026-ff5-elections">2026/FF5/Elections</td>' in html


# ------------------------------- ui-dash-admin-2 / logic-admin-2 (server)

def test_until_says_how_far_away_a_future_stamp_is():
    now = dt.datetime.now(dt.timezone.utc)
    assert ui.until((now + dt.timedelta(hours=23, minutes=30, seconds=30)).isoformat()) == "in 23h 30m"
    assert ui.until((now + dt.timedelta(minutes=5, seconds=30)).isoformat()) == "in 5m"
    assert ui.until((now + dt.timedelta(days=2, hours=1, minutes=1)).isoformat()) == "in 2d 1h"
    assert ui.until((now - dt.timedelta(minutes=1)).isoformat()) == "any moment now"
    assert ui.until(None) == "never"
    assert ui.until("not a stamp") == "not a stamp"
    # Offset-less stamps are UTC, as `ago` reads them (CR-89's lesson).
    naive = (now + dt.timedelta(hours=3, minutes=10)).replace(tzinfo=None).isoformat()
    assert ui.until(naive).startswith("in 3h")


def test_an_active_halt_says_when_it_releases_itself(env):
    client, conn = env
    dbmod.set_fleet_halt(conn, True, "restoring the pool", "owen")
    conn.commit()
    for path in ("/partials/fleet-halt-banner", "/partials/admin/fleet-halt"):
        html = client.get(path).text
        assert "releases itself" in html, (path, html)
        assert "releases itself 0s ago" not in html, path
        assert re.search(r"releases itself in \d+h", html), (path, html)


@needs_chrome
def test_an_answer_to_a_tall_form_lands_at_its_foot(tmp_path):
    """ui-dash-admin-5: the alert settings are one [ SAVE ] under twenty
    fields; above the form's first field is a screen away from the button."""
    form = ('<form hx-post="/do" hx-target="#panel" hx-swap="outerHTML">'
            '<div class="spacer"></div><div><button type="submit">[ SAVE ]</button></div></form>')
    body = f'<div id="panel"><div class="spacer"></div>{form}</div>'
    scenario = """
window.__routes.push({verb: "POST", path: "/do", text:
  '<div id="panel"><div class="banner error-banner">refused: bad port</div>'
  + '<div class="spacer"></div>%s</div>'});
window.scrollTo(0, 99999);
document.querySelector("button").click();
setTimeout(function () {
  var b = document.querySelector(".error-banner");
  var r = b.getBoundingClientRect();
  var next = b.nextElementSibling;
  window.__done({before_button: !!(next && next.tagName === "BUTTON"),
                 visible: r.top >= 0 && r.bottom <= window.innerHeight});
}, 800);
""" % form
    result = _run_page(tmp_path, body, scenario)
    assert result["before_button"] is True, result
    assert result["visible"] is True



# ===========================================================================
# Chunk 2 (builder d-ui, 2026-09-25):
#   ui-dash-static-1  chips swapped in by an outerHTML panel are keyboard
#                     reachable (the mover half is chunk 1's test above).
#   ui-dash-static-2  a 4xx refusal is the server's reason beside the control,
#                     not "THIS PAGE HAS STOPPED UPDATING".
#   ui-dash-admin-6   Site Settings answers beside [ SAVE ], and a refused
#                     save replaces an old "saved".
#   ui-dash-static-3  after an in-page save, [ UNDO ] names the save just made.
#   ui-dash-admin-7   HEALTH counts a source that raised as NOT CHECKED.
#   logic-plans-2     the mode buttons ask before ticking everywhere, and the
#                     poll keeps the tick's UX-1 capacity confirm.
#   logic-admin-3     an expired halt can be taken down without a new halt.
#   logic-admin-6     Packages names the vendor feed, not ship.cmd, on a feed
#                     site.
#   logic-admin-7     cancelling a PINNED job names this server, not a computer.
# ===========================================================================

# -------------------------------------------------- ui-dash-static-1 (chips)

@needs_chrome
def test_a_chip_swapped_in_by_an_outerhtml_panel_is_keyboard_reachable(tmp_path):
    body = """
<div id="panel"><form hx-post="/do" hx-target="#panel" hx-swap="outerHTML">
  <button type="submit">[ GO ]</button></form></div>"""
    scenario = """
window.__routes.push({verb: "POST", path: "/do", text:
  '<div id="panel"><span class="chip" title="why this chip is red">[ RED ]</span></div>'});
document.querySelector("button").click();
setTimeout(function () {
  var c = document.querySelector(".chip");
  window.__done({tabindex: c && c.getAttribute("tabindex")});
}, 500);
"""
    assert _run_page(tmp_path, body, scenario)["tabindex"] == "0"


# ---------------------------------------------- ui-dash-static-2 (browser)

REFUSAL_PAGE = """
<aside class="sidebar"><nav class="projects">
  <label><input type="checkbox" id="tick" hx-post="/tick" hx-target="closest .sidebar"
         hx-swap="innerHTML"> 2026/FF5/Elections</label>
</nav></aside>
<div id="polled" hx-get="/poll" hx-trigger="load" hx-swap="innerHTML">poll</div>"""


def _refusal_scenario(status: int, body_text: str) -> str:
    return """
window.__routes.push({verb: "POST", path: "/tick", status: %d, text: %s});
setTimeout(function () {
  var box = document.getElementById("tick");
  box.click();
  setTimeout(function () {
    var stale = document.getElementById("htmx-stale-banner");
    var note = document.querySelector(".htmx-refusal");
    window.__done({
      stale: stale ? stale.textContent : null,
      note: note ? note.textContent : null,
      beside: !!(note && note.nextElementSibling && note.nextElementSibling.contains(box)),
      checked: box.checked
    });
  }, 600);
}, 300);
""" % (status, json.dumps(body_text))


def _no_poll(page: str) -> str:
    return page.replace('hx-trigger="load"', 'hx-trigger="never"')


@needs_chrome
def test_a_409_says_the_servers_reason_beside_the_box_and_unticks_it(tmp_path):
    reason = ("every computer on this account is wired to the server: they work "
              "directly off the NAS and sync nothing, so projects cannot be ticked for them")
    result = _run_page(tmp_path, _no_poll(REFUSAL_PAGE),
                       _refusal_scenario(409, json.dumps({"detail": reason})))
    # HEAD: a red "THIS PAGE HAS STOPPED UPDATING ... answered 409" bar, no
    # reason anywhere, and the box left ticked.
    assert result["stale"] is None, result
    assert result["note"] == "▲ Refused: " + reason
    assert result["beside"] is True
    assert result["checked"] is False


@needs_chrome
def test_a_signed_in_403_is_not_called_an_ended_session(tmp_path):
    result = _run_page(tmp_path, _no_poll(REFUSAL_PAGE),
                       _refusal_scenario(403, json.dumps({"detail": "not allowed"})))
    assert result["stale"] is None, result
    assert result["note"].startswith("▲ Not allowed: not allowed")
    assert "session" not in result["note"]


@needs_chrome
def test_a_401_and_a_failing_poll_still_say_the_page_is_stale(tmp_path):
    """Controls: the outage and the ended session keep the DUI-2 banner."""
    result = _run_page(tmp_path, _no_poll(REFUSAL_PAGE),
                       _refusal_scenario(401, json.dumps({"detail": "login required"})))
    assert "session has ended" in (result["stale"] or ""), result
    scenario = """
window.__routes.push({verb: "GET", path: "/poll", status: 404, text: "{}"});
htmx.trigger(document.getElementById("polled"), "poke");
setTimeout(function () {
  var s = document.getElementById("htmx-stale-banner");
  window.__done({stale: s ? s.textContent : null});
}, 600);
"""
    (tmp_path / "poll").mkdir()
    result = _run_page(tmp_path / "poll",
                       REFUSAL_PAGE.replace('hx-trigger="load"', 'hx-trigger="poke"'), scenario)
    assert "STOPPED UPDATING" in (result["stale"] or ""), result


# ---------------------------------- ui-dash-admin-6 / ui-dash-static-3 (page)

@pytest.fixture
def settings_page(env):
    """The REAL /admin/settings render, its own scripts stripped, with a fake
    fetch and static/site_settings.js: the template and the script together,
    the way a browser gets them."""
    client, _conn = env
    html = client.get("/admin/settings").text
    html = re.sub(r"<script\b[^>]*>.*?</script>", "", html, flags=re.S)
    html = re.sub(r"<link\b[^>]*>", "", html)
    return html


FAKE_FETCH = r"""
window.__log = [];
window.__puts = 0;
window.__put_status = [200, 422];
window.__history = [{at: "2026-09-20T10:00:00+00:00", actor: "alex", action: "save", count: 1}];
window.__confirms = [];
window.confirm = function (m) { window.__confirms.push(m); return true; };
window.alert = function () {};
function answer(status, body) {
  return Promise.resolve({ok: status < 400, status: status, statusText: "x",
    json: function () { return Promise.resolve(body); }});
}
window.fetch = function (path, opts) {
  opts = opts || {};
  var verb = (opts.method || "GET").toUpperCase();
  window.__log.push(verb + " " + path + (opts.body && path.indexOf("undo") >= 0 ? " " + opts.body : ""));
  if (path === "/api/v1/admin/site" && verb === "PUT") {
    var s = window.__put_status[window.__puts++] || 200;
    if (s === 200) {
      window.__history.unshift({at: "2026-09-25T09:00:0" + window.__puts + "+00:00",
                                actor: "owen", action: "save", count: 1});
      return answer(200, {ok: true});
    }
    return answer(s, {detail: "canonical_prefix must be a drive letter"});
  }
  if (path === "/api/v1/admin/site/history") {
    return answer(200, {entries: window.__history.slice()});
  }
  if (path.indexOf("/api/v1/admin/site/undo-last-change") === 0) {
    return answer(409, {detail: "stop here"});
  }
  return answer(200, {});
};
window.__done = function (result) {
  var pre = document.createElement("pre");
  pre.id = "out";
  pre.textContent = JSON.stringify(result);
  document.body.appendChild(pre);
};
window.addEventListener("error", function (e) {
  window.__done({error: String(e.message) + " @" + e.lineno});
});
"""


def _run_settings(tmp_path: Path, html: str, scenario: str) -> dict:
    page = tmp_path / "settings.html"
    head = (f"<script>{FAKE_FETCH}</script>"
            f"<script src=\"{(STATIC / 'site_settings.js').as_uri()}\"></script>")
    tail = ("<script>document.addEventListener('DOMContentLoaded', function () {"
            "setTimeout(function () { try {" + scenario + "} catch (e) {"
            "window.__done({error: String(e && e.stack || e)}); } }, 300); });</script>")
    html = re.sub(r"<head>", lambda _m: "<head>" + head, html, count=1)
    html = html.replace("</body>", tail + "</body>", 1)
    page.write_text(html, encoding="utf-8")
    out = subprocess.run(
        [CHROME, "--headless=new", "--disable-gpu", "--no-first-run",
         "--allow-file-access-from-files", f"--user-data-dir={tmp_path / 'profile'}",
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


@needs_chrome
def test_a_save_answers_beside_its_button_and_a_refusal_replaces_saved(tmp_path, settings_page):
    scenario = """
var form = document.getElementById("settings-form");
function submit() { form.dispatchEvent(new Event("submit", {cancelable: true})); }
submit();
setTimeout(function () {
  var line = document.getElementById("settings-save-result");
  var first = line ? line.textContent : null;
  var button = form.querySelector("button[type=submit]");
  var besideButton = !!(line && button && line.parentNode === button.parentNode);
  submit();
  setTimeout(function () {
    window.__done({first: first, second: line ? line.textContent : null,
                   besideButton: besideButton, bad: line ? line.className : "",
                   page: document.querySelector("main").textContent});
  }, 400);
}, 400);
"""
    result = _run_settings(tmp_path, settings_page, scenario)
    # HEAD: no line beside the button (the answer was written above the first
    # field), and the second, refused save left "saved" standing.
    assert result["besideButton"] is True
    assert result["first"].startswith("saved at "), result
    assert result["second"] == "▲ could not save: canonical_prefix must be a drive letter"
    assert "bad" in result["bad"]
    assert "saved at" not in result["page"], "an old 'saved' stands beside the refusal"


@needs_chrome
def test_undo_after_an_in_page_save_names_the_save_just_made(tmp_path, settings_page):
    scenario = """
window.__put_status = [200];
var form = document.getElementById("settings-form");
form.dispatchEvent(new Event("submit", {cancelable: true}));
setTimeout(function () {
  document.getElementById("site-undo-btn").click();
  setTimeout(function () {
    window.__done({confirms: window.__confirms, log: window.__log,
                   list: document.getElementById("site-history-list").textContent});
  }, 400);
}, 500);
"""
    result = _run_settings(tmp_path, settings_page, scenario)
    # HEAD: the confirm quoted the 09-20 entry loaded at page load while the
    # server's undo reverts entries[0], the save just made.
    assert result["confirms"], result
    assert "2026-09-25T09:00:01" in result["confirms"][-1], result["confirms"]
    assert "2026-09-20" not in result["confirms"][-1]
    # The list shows "0s ago" since ui-dash-admin-12 (chunk 3; the exact
    # stamp is the row's title): the save just made is the first row.
    assert result["list"].startswith("save by owen"), result["list"]
    undo = [line for line in result["log"] if "undo-last-change" in line]
    assert undo and '"expected_at":"2026-09-25T09:00:01+00:00"' in undo[-1], result["log"]


def test_the_settings_page_has_no_answer_slot_above_the_fields(env):
    client, _conn = env
    html = client.get("/admin/settings").text
    assert 'id="settings-saved"' not in html
    assert 'id="settings-error"' not in html
    for slot in ("settings-save-result", "settings-import-result", "site-undo-result"):
        assert f'id="{slot}"' in html, slot


# ------------------------------------------------------- ui-dash-admin-7

class _Req:
    def __init__(self, app):
        self.app = app


def test_a_source_that_raises_is_not_checked_not_ok(env, monkeypatch):
    client, conn = env
    from ccsync_dashboard import alerts, invariants, protection

    def boom(*_a, **_k):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(protection, "page_view", boom)
    html = client.get("/admin/health").text
    assert "Could not read the protection lines" in html
    assert "RuntimeError: database is locked" in html

    monkeypatch.setattr(alerts, "scan", boom)
    monkeypatch.setattr(invariants, "page_view", boom)
    monkeypatch.setattr(dbmod, "open_notices", boom)
    html = client.get("/admin/health").text
    # HEAD: every source gone, and the page said all was well.
    assert "Every check this server runs answered" not in html
    for what in ("the open notices", "the alert checks", "the invariants",
                 "the protection lines"):
        assert f"Could not read {what}" in html, what
    rows = ui._health_rows(_Req(client.app), conn)
    assert [r["band"] for r in rows] == ["unknown"] * 4
    assert "—" not in html.split("<main", 1)[-1]


# --------------------------------------------------------- logic-plans-2

def test_the_mode_buttons_ask_before_ticking_every_computer(env, monkeypatch):
    client, conn = env
    _report(client, "owen", "LAP")
    _report(client, "owen", "DESK")
    monkeypatch.setattr(ui, "tick_capacity_warning",
                        lambda *_a, **_k: "2026/FF5/Elections is 620 GB of proxies. "
                                          "LAP has 180 GB free.")
    resp = client.put("/api/v1/selection/owen/2026-ff5-elections?machine=LAP&mode=upload_only")
    assert resp.status_code == 200, resp.text
    for path in ("/project/2026-ff5-elections", "/partials/project/2026-ff5-elections"):
        html = client.get(path).text
        m = re.search(r"<button[^>]*mode=full[^>]*>", html, flags=re.S)
        assert m, (path, html)
        button = m.group(0)
        # HEAD: no confirm at all on a button that ticks DESK in full.
        assert "hx-confirm=" in button, path
        assert "DESK" in button and "LAP" in button, button
        assert "620 GB" in button, button
        assert "—" not in button


def test_the_poll_keeps_the_ticks_capacity_confirm(env, monkeypatch):
    client, conn = env
    _report(client, "owen", "LAP")
    monkeypatch.setattr(ui, "tick_capacity_warning",
                        lambda *_a, **_k: "2026/FF5/Elections is 620 GB of proxies.")
    html = client.get("/partials/project/2026-ff5-elections").text
    tick = re.search(r"<button[^>]*/toggle\?view=project&(?:amp;)?slug_page[^>]*>", html, flags=re.S)
    assert tick, html
    # HEAD: the 10 s poll re-rendered [ TICK ] without its UX-1 confirm.
    assert "620 GB" in tick.group(0)


# --------------------------------------------------------- logic-admin-3

def test_an_expired_halt_can_be_taken_down_without_a_new_halt(env):
    client, conn = env
    dbmod.set_fleet_halt(conn, True, "restoring the pool", "owen",
                         now="2026-09-01T00:00:00+00:00")
    conn.commit()
    assert dbmod.get_fleet_halt(conn)["expired"] is True
    panel = client.get("/partials/admin/fleet-halt").text
    # HEAD: the expired branch offered only [ STOP ALL SYNCING ].
    assert "[ OK, IT CAN STAY OFF ]" in panel
    assert "Take this notice down" in client.get("/partials/fleet-halt-banner").text
    resp = client.post("/partials/admin/fleet-halt",
                       data={"active": "0", "ack_expired": "1",
                             "reason": "the expired stop was acknowledged"})
    assert resp.status_code == 200
    halt = dbmod.get_fleet_halt(conn)
    assert halt["expired"] is False and halt["active"] is False
    assert "HAS EXPIRED" not in client.get("/partials/fleet-halt-banner").text


def test_the_ok_button_never_releases_a_live_halt(env):
    """A tab drawn while the stop was expired, pressed after a NEW stop."""
    client, conn = env
    dbmod.set_fleet_halt(conn, True, "a new reason", "owen")
    conn.commit()
    html = client.post("/partials/admin/fleet-halt",
                       data={"active": "0", "ack_expired": "1"}).text
    assert dbmod.get_fleet_halt(conn)["active"] is True
    assert "a new stop was set since this page loaded" in html


# --------------------------------------------------------- logic-admin-6

def test_a_feed_site_is_pointed_at_the_feed_not_ship_cmd(env, monkeypatch):
    client, _conn = env
    from ccsync_dashboard import release_feed

    real = release_feed.build_feed_view

    def configured(*a, **k):
        view = dict(real(*a, **k))
        view.update(configured=True, feed_url="https://feed.invalid/channel.json")
        return view

    html = client.get("/partials/admin/packages").text
    assert "tools\\ship.cmd" in html, "control: a site with no feed keeps ship.cmd"
    monkeypatch.setattr(release_feed, "build_feed_view", configured)
    html = client.get("/partials/admin/packages").text
    # HEAD: "publish a build below, or from your wired computer with
    # tools\ship.cmd", on an appliance that has neither.
    assert "Press [ CHECK NOW ] there to fetch them" in html
    assert "or from your wired" not in html
    assert "Publish new builds from your wired computer" not in html


# --------------------------------------------------------- logic-admin-7

def _job(conn, state, name):
    job_id = dbmod.create_job(conn, "peaks", {"root": "media", "rel_path": name})
    conn.execute("UPDATE jobs SET state=? WHERE id=?", (state, job_id))
    conn.commit()
    return job_id


def test_cancelling_a_pinned_job_names_this_server(env):
    client, conn = env
    job_id = _job(conn, dbmod.JOB_PINNED, "a.mp4")
    html = client.post(f"/partials/admin/jobs/{job_id}/cancel").text
    # HEAD: "the computer running it is the only thing that can end it".
    assert "this server&#39;s own worker" in html or "this server's own worker" in html
    assert "the computer running it" not in html
    assert dbmod.get_job(conn, job_id)["cancel_requested_at"]


def test_cancelling_a_held_job_still_names_the_computer(env):
    client, conn = env
    job_id = _job(conn, dbmod.JOB_RUNNING, "b.mp4")
    html = client.post(f"/partials/admin/jobs/{job_id}/cancel").text
    assert "the computer running it" in html



# ===========================================================================
# Chunk 3 (builder d-ui, 2026-09-25):
#   ui-dash-main-4   the fix-root computer chips keep the admin's ?as=.
#   ui-dash-main-5   those chips wrap on a phone instead of running off it.
#   ui-dash-main-6   the PROJECT ROOTS poll leaves an open [ BROWSE ] alone.
#   ui-dash-main-9   the queue's own untick keeps the computer and the
#                    "safe to close" line.
#   ui-dash-main-10  "(s)" plurals on the fleet / transfers / bins panels.
#   ui-dash-admin-4  OTHER VERSIONS / PREVIOUS STOPS keep their open state.
#   ui-dash-admin-9  SMTP password controls with the environment in charge.
#   ui-dash-admin-11 a minted token wraps inside its box on a phone.
#   ui-dash-admin-12 raw ISO stamps beside humanised ones.
# ===========================================================================

MAC = "Leso-MacBook-Pro-2024.local"


def _two_computers(client, editor="leso"):
    _report(client, editor, "EDIT-PC")
    _report(client, editor, MAC)


def _fix_root_row(html: str) -> str:
    start = html.index('<div class="fix-root-box">')
    end = html.index('<div class="mono-sm root-line">', start)
    return html[start:end]


def _fix_root_hrefs(html: str) -> list[str]:
    return [h.replace("&amp;", "&")
            for h in re.findall(r'href="([^"]*)"', _fix_root_row(html))]


# ------------------------------------------------------------ ui-dash-main-4

def test_the_fix_root_chips_keep_the_editor_the_admin_is_viewing(env):
    client, _conn = env
    _two_computers(client)
    hrefs = _fix_root_hrefs(client.get("/?as=leso").text)
    # HEAD: "/" and "/?machine=EDIT-PC", which land on the ADMIN's queue.
    assert "/?as=leso" in hrefs, hrefs
    assert "/?machine=EDIT-PC&as=leso" in hrefs, hrefs
    assert f"/?machine={MAC}&as=leso" in hrefs, hrefs
    # Following one is the editor's view of that computer, not the admin's.
    page = client.get("/?machine=EDIT-PC&as=leso").text
    assert "[ SYNC QUEUE: LESO ]" in page
    row = _fix_root_row(page)
    assert re.search(r'class="chip amber"\s+href="/\?machine=EDIT-PC&amp;as=leso"', row), row


def test_the_fix_root_chips_of_your_own_computers_carry_no_as(env):
    client, _conn = env
    _two_computers(client, editor="owen")
    hrefs = _fix_root_hrefs(client.get("/").text)
    assert "/" in hrefs and "/?machine=EDIT-PC" in hrefs
    assert not any("as=" in h for h in hrefs), hrefs


# ------------------------------------------------------------ ui-dash-main-5

@needs_chrome
def test_the_fix_root_chips_wrap_on_a_phone(tmp_path, env):
    client, _conn = env
    _two_computers(client, editor="owen")
    row = _fix_root_row(client.get("/").text) + "</div>"
    body = (f'<link rel="stylesheet" href="{(STATIC / "style.css").as_uri()}">'
            f'<div id="phone" style="width:390px;overflow:hidden">{row}</div>')
    scenario = """
setTimeout(function () {
  var limit = document.getElementById("phone").getBoundingClientRect().right;
  var worst = 0;
  document.querySelectorAll("#phone a.chip").forEach(function (a) {
    worst = Math.max(worst, a.getBoundingClientRect().right);
  });
  window.__done({limit: limit, worst: worst,
                 chips: document.querySelectorAll("#phone a.chip").length});
}, 300);
"""
    result = _run_page(tmp_path, body, scenario)
    assert result["chips"] == 3
    # HEAD: the MacBook chip ended past the 390 px edge.
    assert result["worst"] <= result["limit"] + 0.5, result


# ------------------------------------------------------------ ui-dash-main-6

ROOTS_POLLED = """
<div id="roots" hx-get="/poll" hx-trigger="every 1s" hx-swap="innerHTML">
  <div class="roots-box"><div id="roots-browse-m1">%s</div></div>
</div>"""
BROWSE = ('<div class="roots-browse" data-poll-hold>Projects / FF5 / Elections'
          '<i id="deep"></i></div>')


@needs_chrome
def test_the_roots_poll_leaves_an_open_folder_picker_alone(tmp_path):
    scenario = """
window.__routes.push({verb: "GET", path: "/poll", text: '<div class="roots-box" data-new="1"></div>'});
setTimeout(function () {
  window.__done({log: window.__log, still: !!document.getElementById("deep")});
}, 3500);
"""
    result = _run_page(tmp_path, ROOTS_POLLED % BROWSE, scenario)
    # HEAD: the beat emptied the picker three folders deep.
    assert result["still"] is True
    assert _polls(result["log"]) == 0, result


@needs_chrome
def test_a_picker_left_open_stops_holding_the_poll(tmp_path):
    scenario = """
window.__routes.push({verb: "GET", path: "/poll", text: '<div class="roots-box" data-new="1"></div>'});
document.querySelector("[data-poll-hold]").__pollHoldAt = Date.now() - 6 * 60 * 1000;
setTimeout(function () {
  window.__done({log: window.__log, swapped: !!document.querySelector("[data-new]")});
}, 2500);
"""
    result = _run_page(tmp_path, ROOTS_POLLED % BROWSE, scenario)
    assert result["swapped"] is True, result


def test_the_folder_picker_is_marked_to_hold_the_poll():
    text = (TEMPLATES / "partials" / "project_roots_browse.html").read_text(encoding="utf-8")
    assert '<div class="roots-browse" data-poll-hold>' in text


# ------------------------------------------------------------ ui-dash-main-9

def test_the_queue_untick_keeps_the_computer_and_the_safe_to_close_line(env):
    client, conn = env
    dbmod.upsert_project(conn, "2026-ff5-voters", "2026/FF5/Voters", "/data/v",
                         dbmod.utcnow_iso())
    conn.commit()
    _two_computers(client)
    for slug in ("2026-ff5-elections", "2026-ff5-voters"):
        assert client.put(f"/api/v1/selection/leso/{slug}").status_code == 200
    page = client.get("/?machine=EDIT-PC&as=leso").text
    assert "/toggle?queue_machine=EDIT-PC" in page, "the untick does not say which computer"
    html = client.post("/partials/selection/leso/2026-ff5-elections/toggle"
                       "?queue_machine=EDIT-PC").text
    # The write stays the PERSON's, as the confirm says: off both computers.
    for machine in ("EDIT-PC", MAC):
        assert all(s["slug"] != "2026-ff5-elections"
                   for s in dbmod.fetch_selections(conn, "leso", machine=machine)), machine
    assert any(s["slug"] == "2026-ff5-voters"
               for s in dbmod.fetch_selections(conn, "leso", machine=MAC))
    # HEAD: no sentence, and a button that forgot the computer.
    assert "Safe to close" in html or "Not yet" in html, html
    assert "/partials/selection/leso/2026-ff5-voters/toggle?queue_machine=EDIT-PC" in html


def test_a_queue_machine_that_is_not_theirs_is_the_persons_view(env):
    client, _conn = env
    _two_computers(client)
    dbmod_ok = client.put("/api/v1/selection/leso/2026-ff5-elections").status_code
    assert dbmod_ok == 200
    html = client.post("/partials/selection/leso/2026-ff5-elections/toggle"
                       "?queue_machine=SOMEONE-ELSES").text
    assert "SOMEONE-ELSES" not in html


# ----------------------------------------------------------- ui-dash-main-10

def test_the_cited_panels_carry_no_brackets_s():
    for name in ("fleet_grid", "transfers", "bins"):
        text = (TEMPLATES / "partials" / f"{name}.html").read_text(encoding="utf-8")
        code = re.sub(r"\{#.*?#\}", "", text, flags=re.S)
        # HEAD: SHARE REMOVAL(S) REFUSED, folder(s), file(s), original(s).
        assert "(s)" not in code and "(S)" not in code, name


def test_safe_to_close_counts_in_words():
    one = ui.safe_to_close({"transfers": [], "queues": [
        {"editor": "leso", "direction": "down", "n_files": 1}]}, "leso")
    assert "1 file is still coming down and carries on" in one["sentence"]
    three = ui.safe_to_close({"transfers": [], "queues": [
        {"editor": "leso", "direction": "down", "n_files": 3}]}, "leso")
    assert "3 files are still coming down and carry on" in three["sentence"]
    up = ui.safe_to_close({"transfers": [], "queues": [
        {"editor": "leso", "direction": "up", "n_files": 1, "bytes": 10}]}, "leso")
    assert up["sentence"].startswith("Not yet: 1 file still uploading"), up


# ----------------------------------------------------------- ui-dash-admin-4

def test_the_rollback_list_and_the_halt_history_are_keyed():
    pk = (TEMPLATES / "partials" / "admin_packages.html").read_text(encoding="utf-8")
    fh = (TEMPLATES / "partials" / "fleet_halt.html").read_text(encoding="utf-8")
    # HEAD: neither had a data-key or an id, so no keeper could remember them.
    assert '<details class="pkg-other" data-key="pkg-other"' in pk
    assert '<details class="proj-group" data-key="halt-history"' in fh


@needs_chrome
def test_a_keyed_section_stays_open_across_a_poll(tmp_path):
    """The keeper knows a <details> only by its data-key: with one, the
    30 s Packages beat no longer folds OTHER VERSIONS shut (control: the
    same markup without the key comes back closed)."""
    def run(section: str, sub: str) -> dict:
        body = (f'<div id="pk" hx-get="/poll" hx-trigger="every 1s" '
                f'hx-swap="innerHTML">{section}</div>')
        scenario = """
window.__routes.push({verb: "GET", path: "/poll", text: '%s<i data-new="1"></i>'});
document.querySelector("details").setAttribute("open", "");
setTimeout(function () {
  window.__done({swapped: !!document.querySelector("[data-new]"),
                 open: document.querySelector("details.pkg-other").hasAttribute("open")});
}, 2500);
""" % section
        return _run_page(sub, body, scenario)

    keyed = ('<details class="pkg-other" data-key="pkg-other"><summary>[ OTHER VERSIONS ]'
             '</summary>0.9.77</details>')
    bare = keyed.replace(' data-key="pkg-other"', "")
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    result = run(keyed, tmp_path / "a")
    assert result["swapped"] is True and result["open"] is True
    control = run(bare, tmp_path / "b")
    assert control["swapped"] is True and control["open"] is False


# ----------------------------------------------------------- ui-dash-admin-9

def test_the_env_password_offers_no_set_or_clear(env, monkeypatch):
    client, _conn = env
    from ccsync_dashboard import alerts

    monkeypatch.setenv(alerts.SMTP_PASSWORD_ENV, "env-app-password-abcd1234")
    html = client.get("/admin/alerts").text
    # HEAD: both buttons beside "it cannot be changed here".
    assert "[ SET PASSWORD ]" not in html and "[ CLEAR ]" not in html
    assert "comes from the deployment" in html
    assert "env-app-password-abcd1234" not in html


def test_a_stale_tab_setting_the_password_is_told_the_env_still_wins(env, monkeypatch):
    client, _conn = env
    from ccsync_dashboard import alerts

    monkeypatch.setenv(alerts.SMTP_PASSWORD_ENV, "env-app-password-abcd1234")
    html = client.post("/partials/admin/alerts/password",
                       data={"password": "a-new-app-password-5678"}).text
    assert "password stored." in html
    # HEAD: "password stored." and nothing else, while mail used the env one.
    assert "environment password is still the one" in html
    monkeypatch.delenv(alerts.SMTP_PASSWORD_ENV)
    html = client.post("/partials/admin/alerts/password", data={"clear": "1"}).text
    assert "password cleared." in html and "environment password" not in html
    assert "[ SET PASSWORD ]" in html, "control: the file-backed form is offered again"


# ---------------------------------------------------------- ui-dash-admin-11

@needs_chrome
def test_a_minted_token_wraps_inside_its_box(tmp_path):
    token = "cce1." + "0123456789abcdef" + "." + "a" * 48
    body = (f'<link rel="stylesheet" href="{(STATIC / "style.css").as_uri()}">'
            f'<div id="phone" style="width:390px"><div id="minted-secret"><div class="minted-box">'
            f'<div class="minted-value mono-sm" id="minted-value">{token}</div></div></div></div>')
    scenario = """
setTimeout(function () {
  var v = document.getElementById("minted-value");
  var box = document.querySelector(".minted-box").getBoundingClientRect();
  window.__done({value_scroll: v.scrollWidth, value_client: v.clientWidth,
                 box_right: box.right});
}, 300);
"""
    result = _run_page(tmp_path, body, scenario)
    # HEAD: nowrap from .mono-sm, the value ~500 px wide in a 390 px box.
    assert result["value_scroll"] <= result["value_client"] + 1, result
    assert result["box_right"] <= 400, result


# ---------------------------------------------------------- ui-dash-admin-12

def test_the_halt_says_ago_not_iso(env):
    client, conn = env
    dbmod.set_fleet_halt(conn, True, "restoring the pool", "owen")
    conn.commit()
    panel = client.get("/partials/admin/fleet-halt").text
    # HEAD: "set by owen at 2026-09-25T03:16:18.123456+00:00".
    assert re.search(r'set by owen <span title="[^"]+">\d+[smhd] ago</span>', panel), panel


def test_report_tokens_say_ago_not_iso(env):
    client, _conn = env
    _report(client, "leso", "EDIT-PC")
    resp = client.post("/partials/admin/report-tokens/create",
                       data={"username": "leso", "label": "laptop"})
    assert resp.status_code == 200, resp.text
    html = client.get("/partials/admin/report-tokens").text
    assert re.search(r'data-label="CREATED" title="[^"]+">\d+[smhd] ago<', html), html
    assert 'data-label="LAST USED" title="">never<' in html


def test_the_jobs_head_says_how_long_in_words():
    src = (TEMPLATES / "partials" / "admin_jobs.html").read_text(encoding="utf-8")
    # HEAD: "the oldest has waited 172800s".
    assert "depth.oldest_age_s | eta" in src
    assert ui.eta(172800) == "2d 0h"


def test_the_alert_log_recovery_and_history_humanise_their_stamps():
    al = (TEMPLATES / "partials" / "admin_alerts.html").read_text(encoding="utf-8")
    rc = (TEMPLATES / "partials" / "recovery.html").read_text(encoding="utf-8")
    assert "{{ row.at | ago }}" in al and "{{ group.at | ago }}" in al
    assert "{{ triage.last_poll.at | ago }}" in al
    assert "{{ drill.at | ago }}" in rc and "{{ row.at | ago }}" in rc
    js = (STATIC / "site_settings.js").read_text(encoding="utf-8")
    assert '" at " + e.at' not in js and '" at " + latest.at' not in js
    # The undo still names the entry it confirmed by its exact stamp.
    assert "agoText(e.at)" in js and "expected_at: latest.at" in js


# ===========================================================================
# Chunk 4 (builder d-ui, 2026-09-25):
#   ui-dash-admin-14  [ UNDO LAST IMPORT ] undoes any change; a rollback asked
#                     "Update this dashboard to X?".
#   ui-dash-static-4  a refused dashboard update flashed its reason and lost it.
#   ui-dash-static-5  --muted and the drawer's close were under AA contrast.
#   ui-dash-static-6  the offline page's [ RETRY ] went to "/".
#   ui-dash-static-7  the stale banner hid the toasts and the page's foot.
#   ui-dash-static-8  [ COPY ] stuck on COPIED, and was mute over http.
#   ui-dash-static-9  the AI pin / CLI flag kept a choice the server refused.
#   ui-copy-6         " -- " in ui.py copy that reaches a page.
#   ui-copy-7         LOGIN / LOGOUT beside "sign in" everywhere else.
# ===========================================================================

import ast as _ast


def _run_static(tmp_path: Path, name: str, head: str, body: str, scenario: str,
                width: int = 1280) -> dict:
    """A page with only what the test names on it: a fake fetch or XHR in
    `head`, the markup, and the scenario once the DOM is ready."""
    page = tmp_path / name
    page.write_text(f"""<!doctype html><html><head><meta charset="utf-8">
{head}
</head><body>{body}
<script>
window.__done = window.__done || function (result) {{
  var pre = document.createElement("pre");
  pre.id = "out";
  pre.textContent = JSON.stringify(result);
  document.body.appendChild(pre);
}};
window.addEventListener("error", function (e) {{
  window.__done({{error: String(e.message) + " @" + e.lineno}});
}});
document.addEventListener("DOMContentLoaded", function () {{
  setTimeout(function () {{
    try {{ {scenario} }} catch (e) {{ window.__done({{error: String(e && e.stack || e)}}); }}
  }}, 100);
}});
</script>
</body></html>""", encoding="utf-8")
    out = subprocess.run(
        [CHROME, "--headless=new", "--disable-gpu", "--no-first-run",
         "--allow-file-access-from-files", f"--user-data-dir={tmp_path / 'profile'}",
         f"--window-size={width},900", "--virtual-time-budget=15000", "--dump-dom",
         page.as_uri()],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    m = re.search(r'<pre id="out">(.*?)</pre>', out.stdout, flags=re.S)
    assert m, f"the page never reported: {out.stdout[-2000:]} {out.stderr[-2000:]}"
    raw = (m.group(1).replace("&quot;", '"').replace("&lt;", "<")
           .replace("&gt;", ">").replace("&amp;", "&"))
    result = json.loads(raw)
    assert "error" not in result, result["error"]
    return result


# ----------------------------------------------------------- ui-dash-admin-14

def test_the_settings_undo_is_named_for_any_change(env):
    client, _conn = env
    html = client.get("/admin/settings").text
    # HEAD: "[ UNDO LAST IMPORT ]" on a button that undoes a save too.
    assert "[ UNDO LAST CHANGE ]" in html
    assert "UNDO LAST IMPORT" not in html


def test_the_older_bundle_buttons_are_marked_as_rollbacks():
    src = (TEMPLATES / "partials" / "admin_dashboard_update.html").read_text(encoding="utf-8")
    m = re.search(r"<button[^>]*>\[ ROLL BACK TO \{\{ u\.version \}\} \]", src, flags=re.S)
    assert m, "the rollback-candidate button moved"
    # HEAD: the button carried only data-dashupd-apply, the UPDATE marker.
    assert 'data-dashupd-older="1"' in m.group(0)


DASHUPD_FETCH = r"""
<script>
window.__posts = 0; window.__status = 0; window.__confirms = [];
window.__partial_in_progress = false;
window.confirm = function (m) { window.__confirms.push(m); return true; };
function answer(status, body, text) {
  return Promise.resolve({ok: status < 400, status: status, statusText: "x",
    headers: {get: function () { return null; }},
    json: function () { return Promise.resolve(body); },
    text: function () { return Promise.resolve(text || ""); }});
}
function panelHtml() {
  return '<div class="admin-packages-box" id="dashboard-update" data-running="0.7.58">'
    + '<div id="dashupd-progress" class="muted" data-in-progress="'
    + (window.__partial_in_progress ? "1" : "0") + '">'
    + (window.__partial_in_progress ? "working: download - fetching" : "") + '</div>'
    + '<button type="button" id="up" data-dashupd-apply="0.7.60">[ UPDATE NOW ]</button>'
    + '<button type="button" id="back" data-dashupd-apply="0.7.55" data-dashupd-older="1">'
    + '[ ROLL BACK TO 0.7.55 ]</button></div>';
}
window.fetch = function (path, opts) {
  opts = opts || {};
  var verb = (opts.method || "GET").toUpperCase();
  if (path === "/api/v1/admin/dashboard-update/apply" && verb === "POST") {
    window.__posts++;
    // Held long enough for a double click to land while it is out.
    return new Promise(function (resolve) {
      setTimeout(function () {
        resolve(answer(409, {detail: "that bundle was built for another runtime"}));
      }, 200);
    });
  }
  if (path === "/partials/admin/dashboard-update") return answer(200, {}, panelHtml());
  if (path === "/api/v1/admin/dashboard-update/status") {
    window.__status++;
    return answer(200, {in_progress: false, step: "idle", message: ""});
  }
  return answer(200, {});
};
</script>
"""


@needs_chrome
def test_a_refused_update_keeps_its_reason_and_posts_once(tmp_path):
    head = DASHUPD_FETCH + f'<script src="{(STATIC / "dashboard_update.js").as_uri()}"></script>'
    body = ('<div id="host"><div class="admin-packages-box" id="dashboard-update" data-running="0.7.58">'
            '<div id="dashupd-progress" class="muted" data-in-progress="0"></div>'
            '<button type="button" id="up" data-dashupd-apply="0.7.60">[ UPDATE NOW ]</button>'
            '</div></div>')
    scenario = """
var b = document.getElementById("up");
b.click(); b.click();
setTimeout(function () {
  var r = document.getElementById("dashupd-refusal");
  window.__done({posts: window.__posts, refusal: r ? r.textContent : null,
                 panel: !!document.getElementById("dashboard-update")});
}, 1500);
"""
    result = _run_static(tmp_path, "dashupd.html", head, body, scenario)
    # HEAD: two POSTs, and the repaint erased the reason (no refusal line).
    assert result["posts"] == 1, result
    assert result["refusal"] and "another runtime" in result["refusal"], result
    assert "—" not in result["refusal"]


@needs_chrome
def test_a_refusal_while_another_update_runs_resumes_the_watch(tmp_path):
    head = (DASHUPD_FETCH + "<script>window.__partial_in_progress = true;</script>"
            + f'<script src="{(STATIC / "dashboard_update.js").as_uri()}"></script>')
    body = ('<div class="admin-packages-box" id="dashboard-update" data-running="0.7.58">'
            '<div id="dashupd-progress" class="muted" data-in-progress="0"></div>'
            '<button type="button" id="up" data-dashupd-apply="0.7.60">[ UPDATE NOW ]</button>'
            '</div>')
    scenario = """
document.getElementById("up").click();
setTimeout(function () { window.__done({status: window.__status}); }, 2500);
"""
    result = _run_static(tmp_path, "dashupd2.html", head, body, scenario)
    # HEAD: the fetch() repaint fires no htmx:afterSwap, so nothing polled.
    assert result["status"] >= 1, result


@needs_chrome
def test_an_older_bundle_asks_to_roll_back_not_to_update(tmp_path):
    head = DASHUPD_FETCH + f'<script src="{(STATIC / "dashboard_update.js").as_uri()}"></script>'
    body = ('<div class="admin-packages-box" id="dashboard-update" data-running="0.7.58">'
            '<div id="dashupd-progress" class="muted" data-in-progress="0"></div>'
            '<button type="button" id="up" data-dashupd-apply="0.7.60">[ UPDATE NOW ]</button>'
            '<button type="button" id="back" data-dashupd-apply="0.7.55" data-dashupd-older="1">'
            '[ ROLL BACK TO 0.7.55 ]</button></div>')
    scenario = """
document.getElementById("back").click();
setTimeout(function () {
  document.getElementById("up").click();
  setTimeout(function () { window.__done({confirms: window.__confirms}); }, 800);
}, 800);
"""
    result = _run_static(tmp_path, "dashupd3.html", head, body, scenario)
    confirms = result["confirms"]
    assert len(confirms) == 2, confirms
    # HEAD: both said "Update this dashboard to ...".
    assert confirms[0].startswith("Roll this dashboard back to 0.7.55?"), confirms
    assert confirms[1].startswith("Update this dashboard to 0.7.60?"), confirms


# ----------------------------------------------------------- ui-dash-static-5

def _contrast(fg: str, bg: str) -> float:
    def lum(h: str) -> float:
        c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
        return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
    a, b = lum(fg), lum(bg)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


def _css_token(css: str, name: str) -> str:
    m = re.search(r"--" + name + r":\s*(#[0-9a-fA-F]{6})", css)
    assert m, name
    return m.group(1)


def test_muted_text_meets_aa_on_every_surface():
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    muted = _css_token(css, "muted")
    for surface in ("bg", "panel", "field"):
        # HEAD: #6f6f7a is 3.98 / 3.82 / 3.63.
        assert _contrast(muted, _css_token(css, surface)) >= 4.5, (muted, surface)


def test_the_drawer_close_and_help_notes_are_not_border_red():
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    for sel in (r"\.drawer-close", r"\.help-file-note"):
        m = re.search(r"^" + sel + r"\s*\{([^}]*)\}", css, flags=re.M)
        assert m, sel
        # HEAD: color: var(--red-dim), 1.8:1 on the page.
        assert "var(--red-dim)" not in m.group(1), (sel, m.group(1))
    red = _css_token(css, "red")
    assert _contrast(red, _css_token(css, "panel")) >= 4.5


# ----------------------------------------------------------- ui-dash-static-6

def test_the_offline_retry_reloads_the_page_that_failed(env):
    client, _conn = env
    html = client.get("/offline").text
    m = re.search(r"<a\b([^>]*)>\[ RETRY \]</a>", html, flags=re.S)
    assert m, html
    attrs = m.group(1)
    # HEAD: href="/", which threw the reader's own URL away.
    assert 'href=""' in attrs, attrs
    # ...and at /offline itself, where a reload would only paint this again.
    assert "location.pathname === '/offline'" in attrs


# ----------------------------------------------------------- ui-dash-static-7

@needs_chrome
def test_the_stale_banner_leaves_the_toasts_and_the_foot_readable(tmp_path):
    head = f'<link rel="stylesheet" href="{(STATIC / "style.css").as_uri()}">'
    body = ('<div id="assign-toast" class="toast-host"><div class="toast err" id="t">'
            'could not tick leso</div></div>'
            '<div class="spacer" style="height:1500px"></div><p id="last">the last line</p>'
            f'<script src="{(STATIC / "htmx_errors.js").as_uri()}"></script>')
    scenario = """
document.dispatchEvent(new CustomEvent("htmx:sendError", {detail: {}}));
setTimeout(function () {
  window.scrollTo(0, document.documentElement.scrollHeight);
  setTimeout(function () {
    var banner = document.getElementById("htmx-stale-banner").getBoundingClientRect();
    var toast = document.getElementById("t").getBoundingClientRect();
    var last = document.getElementById("last").getBoundingClientRect();
    window.__done({bannerTop: banner.top, toastBottom: toast.bottom, lastBottom: last.bottom,
                   bar: window.innerHeight - document.documentElement.clientHeight});
  }, 200);
}, 200);
"""
    result = _run_static(tmp_path, "stale.html", head, body, scenario, width=390 + 600)
    # HEAD: the toast sat at bottom:1rem under the banner, and the page's
    # last line scrolled no further than the viewport's foot, behind it.
    assert result["toastBottom"] <= result["bannerTop"] + 0.5, result
    # `bar` is a horizontal scrollbar headless may draw: the fixed banner
    # sits above it, the scrolled content ends under it.
    assert result["lastBottom"] <= result["bannerTop"] + result["bar"] + 0.5, json.dumps(result)


def test_the_stale_banner_clears_the_home_indicator():
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    m = re.search(r"^([^{}\n]*\.stale-banner)\s*\{([^}]*)\}", css, flags=re.M)
    assert m
    # HEAD: padding 0.5rem 0.9rem, no --safe-b, under viewport-fit=cover.
    assert "var(--safe-b" in m.group(2)
    # ...and the rule has to outrank .banner.alarm's own padding and margin,
    # which it lost to on HEAD (one class against two).
    assert m.group(1).count(".") >= 3, m.group(1)


# ----------------------------------------------------------- ui-dash-static-8

COPY_BODY = ('<span id="pw">hunter2-one-time</span>'
             '<button type="button" class="copy-btn" id="c" data-copy-from="pw">[ COPY ]</button>')


@needs_chrome
def test_a_double_click_on_copy_goes_back_to_copy(tmp_path):
    head = ("<script>Object.defineProperty(navigator, 'clipboard', {configurable: true,"
            " value: {writeText: function () { return Promise.resolve(); }}});</script>"
            f'<script src="{(STATIC / "copy_value.js").as_uri()}"></script>')
    # The label during the 2 s window, then after it: the second matters.
    page = _run_static(tmp_path, "copy.html", head, COPY_BODY, """
var b = document.getElementById("c");
var seen = [];
b.click();
setTimeout(function () {
  b.click();
  setTimeout(function () { seen.push(b.textContent); }, 50);
  setTimeout(function () { seen.push(b.textContent); window.__done({seen: seen}); }, 2600);
}, 300);
""")
    during, after = page["seen"]
    assert during == "[ COPIED ]"
    # HEAD: the second click saved "[ COPIED ]" as the label to go back to.
    assert after == "[ COPY ]", page


@needs_chrome
def test_copy_without_a_clipboard_api_says_what_happened(tmp_path):
    head = ("<script>Object.defineProperty(navigator, 'clipboard', {configurable: true,"
            " value: undefined});"
            "document.execCommand = function () { return false; };</script>"
            f'<script src="{(STATIC / "copy_value.js").as_uri()}"></script>')
    result = _run_static(tmp_path, "copy2.html", head, COPY_BODY, """
var b = document.getElementById("c");
b.click();
setTimeout(function () {
  window.__done({label: b.textContent, selected: String(window.getSelection())});
}, 100);
""")
    # HEAD: the value was selected and the button said nothing at all.
    assert result["label"] == "[ SELECTED - PRESS CTRL+C ]", result
    assert result["selected"] == "hunter2-one-time"


# ----------------------------------------------------------- ui-dash-static-9

AI_FETCH = r"""
window.__confirms = [];
window.confirm = function () { return true; };
function answer(status, body) {
  return Promise.resolve({ok: status < 400, status: status, statusText: "x",
    json: function () { return Promise.resolve(body); }});
}
window.fetch = function (path, opts) {
  opts = opts || {};
  var verb = (opts.method || "GET").toUpperCase();
  if (path === "/api/v1/admin/ai-providers") {
    return answer(200, {providers: [], preference: "auto", cli_enabled: false,
                        resolved: {name: "claude_code", label: "Claude Code", reason: "first available"}});
  }
  if (path === "/api/v1/admin/ai-providers/preference" && verb === "PUT") {
    return answer(422, {detail: "no key saved for OpenAI API"});
  }
  if (path === "/api/v1/admin/site" && verb === "PUT") {
    return answer(422, {detail: "the notice has not been accepted"});
  }
  if (path === "/api/v1/admin/site/history") return answer(200, {entries: []});
  return answer(200, {});
};
window.__done = function (result) {
  var pre = document.createElement("pre");
  pre.id = "out";
  pre.textContent = JSON.stringify(result);
  document.body.appendChild(pre);
};
window.addEventListener("error", function (e) {
  window.__done({error: String(e.message) + " @" + e.lineno});
});
"""


@needs_chrome
def test_a_refused_ai_pin_or_cli_flag_goes_back_to_what_is_in_force(tmp_path, settings_page):
    html = settings_page
    page = tmp_path / "ai.html"
    head = (f"<script>{AI_FETCH}</script>"
            f"<script src=\"{(STATIC / 'site_settings.js').as_uri()}\"></script>")
    scenario = """
var pref = document.getElementById("ai-preference");
var opt = document.createElement("option");
opt.value = "openai_api"; opt.textContent = "4. OpenAI API";
pref.appendChild(opt);
pref.value = "openai_api";
pref.dispatchEvent(new Event("change"));
var flag = document.getElementById("ai-cli-enabled");
setTimeout(function () {
  var prefAfter = pref.value;
  var err1 = document.getElementById("ai-error").textContent;
  flag.click();
  setTimeout(function () {
    window.__done({pref: prefAfter, err1: err1, flag: flag.checked,
                   err2: document.getElementById("ai-error").textContent});
  }, 600);
}, 600);
"""
    tail = ("<script>document.addEventListener('DOMContentLoaded', function () {"
            "setTimeout(function () { try {" + scenario + "} catch (e) {"
            "window.__done({error: String(e && e.stack || e)}); } }, 300); });</script>")
    html = re.sub(r"<head>", lambda _m: "<head>" + head, html, count=1)
    html = html.replace("</body>", tail + "</body>", 1)
    page.write_text(html, encoding="utf-8")
    out = subprocess.run(
        [CHROME, "--headless=new", "--disable-gpu", "--no-first-run",
         "--allow-file-access-from-files", f"--user-data-dir={tmp_path / 'profile'}",
         "--window-size=1280,900", "--virtual-time-budget=15000", "--dump-dom",
         page.as_uri()],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    m = re.search(r'<pre id="out">(.*?)</pre>', out.stdout, flags=re.S)
    assert m, out.stdout[-2000:]
    result = json.loads(m.group(1).replace("&quot;", '"').replace("&lt;", "<")
                        .replace("&gt;", ">").replace("&amp;", "&"))
    assert "error" not in result, result
    # HEAD: the select kept "openai_api" and the box stayed ticked.
    assert result["pref"] == "auto", result
    assert "no key saved" in result["err1"], result
    assert result["flag"] is False, result
    assert "not been accepted" in result["err2"], result


# ------------------------------------------------------------------ ui-copy-6

def _typewriter_dashes(path: Path) -> list[tuple[int, str]]:
    tree = _ast.parse(path.read_text(encoding="utf-8"))
    skip: set[int] = set()
    for node in _ast.walk(tree):
        if isinstance(node, (_ast.Module, _ast.ClassDef, _ast.FunctionDef,
                             _ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if (isinstance(first, _ast.Expr) and isinstance(first.value, _ast.Constant)
                    and isinstance(first.value.value, str)):
                skip.add(id(first.value))
        # Log lines are not copy (the house rule exempts them).
        if (isinstance(node, _ast.Call) and isinstance(node.func, _ast.Attribute)
                and node.func.attr in ("debug", "info", "warning", "error",
                                       "exception", "critical")):
            skip.update(id(n) for n in _ast.walk(node))
    return [(n.lineno, n.value) for n in _ast.walk(tree)
            if isinstance(n, _ast.Constant) and isinstance(n.value, str)
            and id(n) not in skip and " -- " in n.value]


def test_ui_py_copy_has_no_typewriter_em_dash():
    hits = _typewriter_dashes(DASH / "src" / "ccsync_dashboard" / "ui.py")
    # HEAD: seven, among them the login page's "busy checking sign-ins --".
    assert not hits, hits


def test_the_busy_login_says_it_without_the_banned_dash():
    src = (DASH / "src" / "ccsync_dashboard" / "ui.py").read_text(encoding="utf-8")
    assert "the server is busy checking sign-ins. Try again in a moment." in src


# ------------------------------------------------------------------ ui-copy-7

def test_the_topbar_says_sign_in_and_sign_out(env):
    client, _conn = env
    body = client.get("/partials/topbar").text
    assert "[ SIGN OUT ]" in body and "[ SIGN OUT EVERYWHERE ]" in body
    # HEAD: [ LOGOUT ] and [ LOGOUT ALL ].
    assert "LOGOUT" not in body.upper().replace("/LOGOUT", "")
    assert "log in again" not in body
    anon = TestClient(client.app)
    page = anon.get("/login").text
    assert "[ SIGN IN ]" in page and "[ LOGIN ]" not in page


def test_the_sessions_confirms_say_sign_in_again():
    # The confirms render only beside a live session row, so read the source.
    html = (TEMPLATES / "partials" / "admin_sessions.html").read_text(encoding="utf-8")
    assert html.count("need to sign in again") == 2
    # HEAD: "You will need to log in again" beside "Sign yourself out".
    assert "log in again" not in html


# ====================================================================
# OWED round (2026-09-25): items other groups left for d-ui's files.
# ====================================================================

from ccsync_dashboard import health as _health  # noqa: E402
from ccsync_dashboard import local_users as _local_users  # noqa: E402


def _up_uncertain(machine="EDIT-PC", n_files=0, label="Elections"):
    return {"editor": "leso", "machine": machine, "slug": "2026-ff5-elections",
            "label": label, "lane": "a", "direction": "up", "kind": "original",
            "n_files": n_files, "bytes": 1000 * n_files, "files": [],
            "truncated": bool(n_files), "manifest_truncated": True,
            "uncertain": True}


# ------------------------------------------- logic-sync-truth-2 (safe_to_close)

def test_an_originals_capped_machine_is_never_safe_to_close():
    view = {"transfers": [], "queues": [_up_uncertain()]}
    out = ui.safe_to_close(view, "leso")
    # HEAD: {"safe": True, "sentence": "Safe to close: nothing is transferring."}
    assert out["safe"] is False, out
    assert "Safe to close" not in out["sentence"]
    assert "EDIT-PC" in out["sentence"] and "Elections" in out["sentence"]
    assert " -- " not in out["sentence"] and "—" not in out["sentence"]


def test_a_counted_upload_on_a_capped_machine_says_there_may_be_more():
    view = {"transfers": [], "queues": [_up_uncertain(n_files=3)]}
    out = ui.safe_to_close(view, "leso")
    assert out["safe"] is False
    assert out["sentence"].startswith("Not yet: 3 files still uploading from EDIT-PC")
    assert "There may be more: EDIT-PC (Elections)" in out["sentence"], out


def test_a_view_without_the_uncertain_key_reads_as_before():
    q = _up_uncertain(n_files=2)
    del q["uncertain"]
    out = ui.safe_to_close({"transfers": [], "queues": [q]}, "leso")
    assert "There may be more" not in out["sentence"]
    assert ui.safe_to_close({"transfers": [], "queues": []}, "leso")["safe"] is True


# ------------------------- logic-sync-truth-2 / bug-dash-db-2 (transfers.html)

def _render_transfers(queues):
    tpl = ui.templates.env.get_template("partials/transfers.html")
    return tpl.render(transfers={"transfers": [], "fleet_speed_bps": 0,
                                 "queues": queues, "queued_files": 0,
                                 "queued_bytes": 0, "history": []},
                      safe_to_close=None, scope_admin=True)


def test_the_capped_manifest_line_is_worded_by_direction():
    down_capped = {"editor": "leso", "machine": "EDIT-PC", "slug": "s", "label": "L",
                   "lane": "b", "direction": "down", "kind": "proxy", "n_files": 500,
                   "bytes": 5, "files": [], "truncated": True,
                   "manifest_truncated": True}
    down_exact = dict(down_capped, n_files=1, files=[{"name": "a.mp4", "size": 5}],
                      truncated=False)
    html = _render_transfers([_up_uncertain(n_files=3), down_capped, down_exact])
    # HEAD: one "manifest was capped; totals may undercount" line for all three.
    assert "totals may undercount" not in html
    # Owed round 2: the zero-file capped row has its own sentence (below), so
    # the "count may be low" caveat belongs to a capped row that counted some.
    assert html.count("so the upload count may be low") == 1
    assert html.count("proxy list was capped, so the count is worked out from its totals") == 1
    # A capped proxy row has no names to list, so no "... and 500 more" either.
    assert "and 500 more" not in html
    assert "—" not in html


# ----------------------------------------------- logic-sync-truth-4 (disk chip)

def test_the_disk_chip_no_longer_says_the_trash_cannot_prune():
    text = ui.chip_help("disk", free="1 GB", total="1 TB", system="", at="1m ago")
    # HEAD: ".ccsync-trash cannot prune while proxy download is stopped."
    assert "cannot prune" not in text
    assert "safety breaker" in text
    assert "—" not in text and " -- " not in text
    # Review round: the prune-to-twice-the-floor behaviour is bug-comp-rclone-3,
    # new AFTER 0.9.78; every companion in the field stops at the floor. The
    # chip names both, and tells the old-machine reader what restarts it.
    assert "On CC Sync newer than 0.9.78 it is emptied until the drive has twice the floor free" in text
    assert "On 0.9.78 or older it stops emptying at the floor" in text
    assert "presses [ RESUME ] in that computer's tray" in text
    # The first cut claimed the self-restart for every machine.
    assert "is emptied oldest first until the drive has twice the floor free" not in text


# ------------------------------------------------------- ui-copy-5 (fleet grid)

def test_the_empty_fleet_names_the_one_diagnostics_route(env):
    client, _conn = env
    html = client.get("/").text
    assert "No computer has reported yet" in html
    # HEAD: a hand-written third route, "Settings, then Help, then Copy diagnostics".
    assert "Settings, then Help, then Copy diagnostics" not in html
    import html as _html
    assert f"ask that editor to open {_html.escape(_health.COMPANION_DIAGNOSTICS_PATH, quote=False)}" in html


# ------------------------------------------ bug-dash-api-4 (the [ SET ] button)

@pytest.fixture
def local_env(tmp_path):
    db_path = tmp_path / "w2dui-local.db"
    app = create_app(Settings(db_path=str(db_path), session_secret=SECRET,
                              admin_users=frozenset({"owen"}), auth_method="local"))
    with TestClient(app) as client:
        client.app.state.collector.stop()
        conn = dbmod.connect(db_path)
        _local_users.create_user(conn, "jsmith", "leaked-password-123", "editor")
        conn.commit()
        conn.close()
        yield client


def test_the_users_page_set_button_signs_the_account_out(local_env):
    client = local_env
    resp = client.post("/api/v1/login", json={"username": "jsmith",
                                              "password": "leaked-password-123"})
    assert resp.status_code == 200, resp.text
    sid = auth.session_id_for(SECRET, client.cookies.get(auth.COOKIE_NAME))
    store = client.app.state.session_store
    assert store.validate(sid) == "jsmith"
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "owen"))
    html = client.post("/partials/admin/users/password",
                       data={"username": "jsmith", "password": "a-new-password-456"}).text
    # HEAD: the hash changed and the leaked password's session still validated.
    assert store.validate(sid) is None
    assert "Password set for jsmith, and signed out 1 session of theirs." in html


def test_a_set_with_no_sessions_keeps_the_plain_notice(local_env):
    client = local_env
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "owen"))
    html = client.post("/partials/admin/users/password",
                       data={"username": "jsmith", "password": "a-new-password-456"}).text
    assert "Password set for jsmith. Tell them the new password" in html
    assert "signed out" not in html


# ------------------- bug-dash-diag-3, logic-admin-4/5, ui-dash-admin-13 (recovery)

def _render_recovery(preview=None, result=None, problem="", resolve_undo=None):
    recovery = {
        "protection": {"counts": {"ok": 1, "broken": 0, "not_checked": 0,
                                  "check_failed": 0}, "lines": []},
        "facts": [], "problems": [], "plan": None,
        "snapshots": [{"name": "auto-2026-09-24"}],
        "projects": [{"slug": "s", "label": "2026/FF5/Elections"}],
        "drills": [], "restores": [],
    }
    tpl = ui.templates.env.get_template("partials/recovery.html")
    return tpl.render(recovery=recovery, recovery_problem=problem,
                      recovery_preview=preview, recovery_result=result,
                      resolve_undo=resolve_undo or [])


def _preview(missing, changed):
    return {"slug": "s", "snapshot": "auto-2026-09-24", "label": "Elections",
            "missing_count": missing, "changed_count": changed, "unchanged_count": 4,
            "missing": [], "note": "", "truncated": False,
            "counts_unavailable": False}


def _restore_form(html):
    m = re.search(r'<form hx-post="/partials/admin/recovery/restore".*?</form>', html, re.S)
    assert m, html
    return m.group(0)


def test_the_restore_paragraph_says_where_the_copy_goes():
    html = " ".join(_render_recovery().split())
    # HEAD: "copied into a NEW folder inside that project".
    assert "inside that project" not in html
    assert "at the top of the Projects folder on the server" in html
    assert "It is not sent to any editor's computer." in html
    intro = " ".join((TEMPLATES / "admin_recovery.html").read_text(encoding="utf-8").split())
    assert "new folder inside the project" not in intro
    assert "new folder at the top of the Projects folder on the server" in intro


def test_a_changed_only_restore_starts_ticked_and_counts_what_it_copies():
    form = _restore_form(_render_recovery(_preview(0, 3)))
    # HEAD: an unticked box and "Copy 0 file(s) into a new folder?".
    assert re.search(r'name="include_changed" value="1" checked', form)
    assert "Copy 0 file(s)" not in form
    assert "Copy the 3 file(s) that are there but different into a new folder?" in form


def test_a_mixed_restore_confirm_names_both_counts_and_stays_unticked():
    form = _restore_form(_render_recovery(_preview(2, 5)))
    assert "checked" not in form
    assert ("Copy 2 missing file(s), and the 5 different one(s) if the box is "
            "ticked, into a new folder?") in form
    plain = _restore_form(_render_recovery(_preview(2, 0)))
    assert "Copy 2 missing file(s) into a new folder?" in plain
    assert "different" not in plain.split('hx-confirm="')[1].split('"')[0]
    for f in (form, plain):
        assert "—" not in f and " -- " not in f


def test_the_restore_result_says_where_and_that_a_dot_name_may_hide():
    html = " ".join(_render_recovery(result={
        "files": 2, "where": ".restored-20260925/Elections",
        "failed_count": 0, "failed": []}).split())
    # HEAD: "Restored 2 file(s) into .restored-20260925/Elections." and no more.
    assert ("into .restored-20260925/Elections, at the top of the Projects "
            "folder on the server.") in html
    assert "hidden in Explorer or Finder" in html


def test_the_restore_route_docstring_names_the_tree_not_the_project():
    doc = ui.partial_admin_recovery_restore.__doc__ or ""
    assert "<tree>/.restored-<ts>/<project>/" in doc
    assert "<project>/.restored-<ts>/`" not in doc


# ------------------------------------------ ui-copy-2 (the collector anchor)

def test_the_collector_panel_is_the_anchor_the_notices_link_to():
    html = (TEMPLATES / "partials" / "collector_health.html").read_text(encoding="utf-8")
    # HEAD: no id, so /#fleet-collector landed at the top of the page.
    assert re.search(r'<div class="side-head" id="fleet-collector"[^>]*>\[ COLLECTOR \]', html)


def test_the_fleet_page_renders_the_collector_anchor_once(env):
    client, _conn = env
    _report(client, "leso", "EDIT-PC")
    html = client.get("/").text
    assert html.count('id="fleet-collector"') == 1


# ------------------------------------------ ui-copy-2 (the Resolve undo button)

def _seed_journals(client, conn, journals):
    _report(client, "leso", "EDIT-PC")
    dbmod.store_resolve_journals(conn, "leso", "EDIT-PC", journals)
    conn.commit()


def test_the_resolve_answer_lists_each_computers_changes_with_an_undo(env):
    client, conn = env
    _seed_journals(client, conn, [
        {"id": "ff5-elections/2026-09-24T10-00-00.json", "project": "FF5 Elections",
         "started": "2026-09-24T10:00:00+00:00", "entries": 12, "sources": "fixer"}])
    html = client.get("/admin/recovery?problem=resolve").text
    # HEAD: no page drew the journals; the API routes had no caller.
    assert 'id="resolve-undo"' in html
    assert "[ UNDO THIS CHANGE ]" in html
    assert 'hx-post="/partials/admin/recovery/resolve-undo"' in html
    assert 'value="ff5-elections/2026-09-24T10-00-00.json"' in html
    assert "Put back the 12 clip path(s) CC Sync changed in FF5 Elections on EDIT-PC?" in html
    # Only the Resolve answer draws it.
    assert 'id="resolve-undo"' not in client.get("/admin/recovery?problem=project").text


def test_undo_this_change_asks_that_computer_and_shows_it_asked(env):
    client, conn = env
    jid = "ff5-elections/2026-09-24T10-00-00.json"
    _seed_journals(client, conn, [{"id": jid, "project": "FF5 Elections",
                                   "started": "", "entries": 3, "sources": ""}])
    html = client.post("/partials/admin/recovery/resolve-undo",
                       data={"editor": "leso", "machine": "EDIT-PC", "journal": jid}).text
    assert "Asked EDIT-PC to put those clip paths back." in html
    rows = dbmod.resolve_undos_for_machine(conn, "leso", "EDIT-PC")
    assert [r["journal_id"] for r in rows] == [jid]
    assert rows[0]["requested_by"] == "owen"
    # The row now says it was asked instead of offering a second button.
    # The button, not the words: d-diag's recovery step now names the button
    # in its prose, on the same page.
    assert "[ UNDO ASKED ]" in html and ">[ UNDO THIS CHANGE ]</button>" not in html
    assert "asked to undo FF5 Elections: waiting for that computer to report" in html


def test_undoing_a_change_the_computer_never_reported_is_refused(env):
    client, conn = env
    _seed_journals(client, conn, [])
    html = client.post("/partials/admin/recovery/resolve-undo",
                       data={"editor": "leso", "machine": "EDIT-PC",
                             "journal": "nope/x.json"}).text
    assert "has not reported a change called" in html
    assert dbmod.resolve_undos_for_machine(conn, "leso", "EDIT-PC") == []


def test_an_editor_cannot_press_undo_this_change(env):
    client, conn = env
    jid = "p/j.json"
    _seed_journals(client, conn, [{"id": jid, "project": "P", "entries": 1}])
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "leso"))
    resp = client.post("/partials/admin/recovery/resolve-undo",
                       data={"editor": "leso", "machine": "EDIT-PC", "journal": jid})
    assert resp.status_code in (401, 403)
    assert dbmod.resolve_undos_for_machine(conn, "leso", "EDIT-PC") == []


def test_with_no_journals_the_resolve_answer_points_at_the_tray():
    html = " ".join(_render_recovery(problem="resolve").split())
    assert "No computer has told this server about a clip-path change it could undo." in html
    assert "[ UNDO LAST FIX ]" in html


# ====================================================================
# Review round (2026-09-25): the adversarial reviewer's four problems.
# ====================================================================

# ------------------------------- logic-sync-truth-2, end to end (real view)

def _seed_capped_originals(conn, *, held=2500, listed=2000):
    """The hunter's scenario (b): a laptop with more originals than the
    companion lists, every listed one already on the NAS, zero owed."""
    now = dbmod.utcnow_iso()
    pid = conn.execute("SELECT id FROM projects WHERE slug=?",
                       ("2026-ff5-elections",)).fetchone()[0]
    dbmod.record_known_editor(conn, "leso", source="admin", now=now)
    dbmod.upsert_machine(conn, "leso", "EDIT-PC", now)
    dbmod.add_selection(conn, "leso", "2026-ff5-elections", created_by="owen",
                        now=now, machine="EDIT-PC")
    dbmod.replace_nas_media(conn, pid, [(f"o{i:05d}.mov", "original", "mov", 100, 1)
                                        for i in range(listed)], "sig", 2, now, force=True)
    dbmod.replace_editor_media(conn, "leso", "EDIT-PC", "2026-ff5-elections",
                               [(f"o{i:05d}.mov", "original", 100) for i in range(listed)],
                               now)
    dbmod.upsert_editor_media_project(
        conn, editor="leso", machine="EDIT-PC", slug="2026-ff5-elections",
        mode="editor", n_originals=held, bytes_originals=100 * held,
        n_proxies=0, bytes_proxies=0, truncated=listed < held, now=now)
    conn.commit()


def test_the_db_keeps_the_capped_row_the_page_needs(env):
    # The premise the end-to-end tests below rest on: d-db's half has landed.
    _client, conn = env
    _seed_capped_originals(conn)
    up = [q for q in dbmod.fetch_sync_backlog(conn, "leso") if q["direction"] == "up"]
    assert len(up) == 1 and up[0]["uncertain"] is True and up[0]["n_files"] == 0


def test_an_originals_capped_machine_is_not_safe_to_close_through_the_real_view(env):
    from ccsync_dashboard.api import build_transfers_view
    _client, conn = env
    _seed_capped_originals(conn)
    v = build_transfers_view(conn, editor="leso")
    out = ui.safe_to_close(v, "leso")
    assert out["safe"] is False, out
    assert out["sentence"].startswith("Cannot tell yet: EDIT-PC")


def test_the_editors_queue_panel_does_not_say_safe_to_close_over_a_capped_list(env):
    client, conn = env
    _seed_capped_originals(conn)
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "leso"))
    html = " ".join(client.get("/partials/queue").text.split())
    assert "Safe to close" not in html
    assert "Cannot tell yet" in html
    page = " ".join(client.get("/partials/transfers").text.split())
    assert "so the dashboard cannot tell whether it still owes uploads" in page


# ------------------------------- bug-dash-api-4, the SMB create-or-update door

class _FakeNas:
    """A create-or-update that succeeds, and a password write that is recorded."""

    def __init__(self):
        self.passwords: list[tuple[str, str]] = []

    def create_or_update_editor(self, username, ssh_pubkey, full_name=None):
        return {"created": False, "username": username, "home_ok": True, "warnings": []}

    def set_known_password(self, username, password):
        self.passwords.append((username, password))

    def __getattr__(self, name):  # anything the Users view asks the NAS
        raise ui.NasError(f"fake NAS: {name} not modelled")


_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIGq7cQ2bFz0c1S6h8d9F0mXrJkVtYw3pLnB4sE5uR7aZ jsmith@laptop"


def test_the_create_form_resetting_an_existing_password_signs_the_account_out(env, monkeypatch):
    client, _conn = env
    nas = _FakeNas()
    monkeypatch.setattr(ui.nas_factory, "nas_configured", lambda s: True)
    monkeypatch.setattr(ui.nas_factory, "make_nas_client", lambda s: nas)
    store = client.app.state.session_store
    store.create("sid-leaked", "jsmith")
    assert store.validate("sid-leaked") == "jsmith"
    html = client.post("/partials/admin/users/create", data={
        "username": "jsmith", "ssh_pubkey": _KEY,
        "password": "a-new-password-456"}).text
    assert nas.passwords == [("jsmith", "a-new-password-456")]
    # HEAD (and the first cut of this round): the password changed and the
    # session signed in with the old one still validated.
    assert store.validate("sid-leaked") is None
    assert "signed out 1 session of theirs" in html


def test_the_create_form_without_a_password_signs_nobody_out(env, monkeypatch):
    client, _conn = env
    nas = _FakeNas()
    monkeypatch.setattr(ui.nas_factory, "nas_configured", lambda s: True)
    monkeypatch.setattr(ui.nas_factory, "make_nas_client", lambda s: nas)
    store = client.app.state.session_store
    store.create("sid-keep", "jsmith")
    html = client.post("/partials/admin/users/create", data={
        "username": "jsmith", "ssh_pubkey": _KEY}).text
    # A key-only update is not a password reset: nothing to revoke.
    assert nas.passwords == []
    assert store.validate("sid-keep") == "jsmith"
    assert "signed out" not in html


# ------------------------------- ui-copy-2, an old open ask under newer rows

def test_an_old_unanswered_undo_stays_asked_under_five_newer_requests(env):
    client, conn = env
    old = "p/old.json"
    _seed_journals(client, conn, [{"id": old, "project": "P", "entries": 2}])
    now = dbmod.utcnow_iso()
    assert dbmod.request_resolve_undo(conn, "leso", "EDIT-PC", old, "P", "owen", now)
    for i in range(6):
        dbmod.request_resolve_undo(conn, "leso", "EDIT-PC", f"p/n{i}.json", "P", "owen", now)
    conn.commit()
    view = ui._resolve_undo_view(conn)
    (row,) = [r for r in view if r["machine"] == "EDIT-PC"]
    assert len(row["requests"]) == 5 and old not in [r["journal_id"] for r in row["requests"]]
    # HEAD of this round: `asked` came from the five drawn rows, so the old
    # open ask fell out and [ UNDO THIS CHANGE ] came back for a duplicate.
    (j,) = row["journals"]
    assert j["asked"] is True
    html = client.get("/admin/recovery?problem=resolve").text
    # The button, not the words: d-diag's recovery step now names the button
    # in its prose, on the same page.
    assert "[ UNDO ASKED ]" in html and ">[ UNDO THIS CHANGE ]</button>" not in html


# ====================================================================
# Owed round 2 (2026-09-25)
# ====================================================================

# ------------------- bug-dash-db-2 (owed by d-db): the zero-file capped row

def test_a_zero_file_capped_upload_row_is_a_sentence_not_zero_files():
    html = " ".join(_render_transfers([_up_uncertain()]).split())
    # HEAD: "0 files · 0 B" beside an "upload" chip, which reads as done.
    assert "0 files · 0 B" not in html and ">0 files" not in html
    assert '<span class="chip">upload</span>' not in html
    assert "[ CANNOT TELL ]" in html
    assert ("this computer's file list was capped: it holds more video originals "
            "than it can list to the dashboard, so the dashboard cannot tell "
            "whether it still owes uploads") in html
    # The header over such a panel does not say "0 files · 0 B waiting" either.
    assert "waiting behind the transfers above" not in html
    assert "nothing counted yet, but the rows below are not finished" in html
    assert "—" not in html and " -- " not in html


def test_a_capped_row_that_counted_files_still_shows_its_count():
    html = " ".join(_render_transfers([_up_uncertain(n_files=3)]).split())
    assert "3 files" in html and "[ CANNOT TELL ]" not in html
    assert "so the upload count may be low" in html


def test_a_zero_file_row_that_is_not_capped_keeps_its_old_shape():
    # A GETTING READY row is also zero files; it must stay as it was.
    q = dict(_up_uncertain(), uncertain=False, pending=True)
    html = " ".join(_render_transfers([q]).split())
    assert "[ GETTING READY ]" in html and "[ CANNOT TELL ]" not in html


# ---------------- ui-copy-6 (owed to d-ui for this round): the package-wide scan
#
# DUI-14 kept " -- " out of templates; ui-copy-6 found 93 of them in the
# package's Python copy instead (HTTP detail, toasts, alert mail). Every
# owning group has now changed its own, so this widens the check to every
# module and keeps them from coming back. Not copy, and so exempt: SQL (a
# `--` there is a schema comment), and the three named strings below, none
# of which a person reads on a page.

_SQL_CALLS = ("execute", "executescript", "executemany")
# d-ui owed round 3 (2026-09-25): the first cut matched case-insensitively on
# a bare prefix, so English copy that happened to start "Update the
# dashboard -- ..." or "Delete ..." or "With ..." was exempt. SQL here is
# always written in upper case, and a keyword is followed by whitespace.
_SQL_HEAD_RE = re.compile(r"\s*(CREATE|ALTER|INSERT|UPDATE|DELETE|SELECT|WITH)\s")

# (module, how the string starts): why it is not visible copy.
_TYPEWRITER_DASH_ALLOWED = {
    # The body of a probe file written and deleted in the same breath.
    ("setup_engine.py", "ccsync setup probe -- safe to delete"),
    # Python source run by the image's interpreter at stage-verify.
    ("dashboard_update.py", "\nimport json, sqlite3, sys, traceback"),
    # An instruction to the model, never shown to a person.
    ("cards_ai.py", "\n\nOUTPUT: reply with the JSON object alone --"),
}


def _sql_statement_constants(path: Path) -> set[tuple[int, str]]:
    """(line, value) of every string constant inside the FIRST positional
    argument of an execute/executescript/executemany call: the statement.

    d-ui owed round 3 (2026-09-25): the first cut exempted every constant
    anywhere in the call, so a parameter tuple, and any string elsewhere in
    the module that happened to equal one, went unscanned."""
    tree = _ast.parse(path.read_text(encoding="utf-8"))
    out: set[tuple[int, str]] = set()
    for node in _ast.walk(tree):
        if (isinstance(node, _ast.Call) and isinstance(node.func, _ast.Attribute)
                and node.func.attr in _SQL_CALLS and node.args):
            out.update((n.lineno, n.value) for n in _ast.walk(node.args[0])
                       if isinstance(n, _ast.Constant) and isinstance(n.value, str))
    return out


def _package_typewriter_dashes() -> list[str]:
    hits = []
    for path in sorted((DASH / "src" / "ccsync_dashboard").rglob("*.py")):
        sql = _sql_statement_constants(path)
        for line, value in _typewriter_dashes(path):
            if (line, value) in sql or _SQL_HEAD_RE.match(value):
                continue
            if any(path.name == mod and value.startswith(head)
                   for mod, head in _TYPEWRITER_DASH_ALLOWED):
                continue
            hits.append(f"{path.relative_to(DASH)}:{line}: {value[:80]!r}")
    return hits


def test_no_typewriter_em_dash_in_any_dashboard_python_copy():
    hits = _package_typewriter_dashes()
    # HEAD: 93 across api.py, the ops modules, auth, cards and diag.
    assert not hits, "\n".join(hits)


def test_the_package_scan_still_catches_a_dash_in_copy(tmp_path, monkeypatch):
    # The exemptions must not swallow real copy: an HTTP detail with " -- "
    # beside a SQL comment is still found, and only the detail.
    pkg = tmp_path / "src" / "ccsync_dashboard"
    pkg.mkdir(parents=True)
    (pkg / "fake.py").write_text(
        'SCHEMA = """\nCREATE TABLE t (a TEXT -- a comment\n);"""\n'
        'def f(conn):\n'
        '    conn.execute("SELECT 1 -- why")\n'
        '    raise HTTPException(409, detail="refused -- try again")\n',
        encoding="utf-8")
    monkeypatch.setitem(globals(), "DASH", tmp_path)
    hits = _package_typewriter_dashes()
    assert len(hits) == 1 and "refused -- try again" in hits[0], hits


def test_the_sql_exemption_does_not_swallow_english_copy(tmp_path, monkeypatch):
    # d-ui owed round 3 (2026-09-25): copy that starts with an English word
    # spelled like a SQL keyword, a parameter of an execute call, and a copy
    # string equal to such a parameter were all exempt under the first cut.
    pkg = tmp_path / "src" / "ccsync_dashboard"
    pkg.mkdir(parents=True)
    (pkg / "fake.py").write_text(
        'def f(conn):\n'
        '    conn.execute("UPDATE t SET a=? -- why", ("note -- param",))\n'
        '    conn.executemany("""\n  INSERT INTO t VALUES (?) -- x""", [])\n'
        '    a = HTTPException(409, detail="Update the dashboard -- now")\n'
        '    b = HTTPException(409, detail="Delete it -- first")\n'
        '    c = HTTPException(409, detail="With care -- please")\n'
        '    d = HTTPException(409, detail="select one -- here")\n'
        '    e = HTTPException(409, detail="SELECTED -- nothing")\n',
        encoding="utf-8")
    monkeypatch.setitem(globals(), "DASH", tmp_path)
    hits = "\n".join(_package_typewriter_dashes())
    for copy in ("note -- param", "Update the dashboard -- now", "Delete it -- first",
                 "With care -- please", "select one -- here", "SELECTED -- nothing"):
        assert copy in hits, (copy, hits)
    assert "UPDATE t SET" not in hits and "INSERT INTO" not in hits, hits


# ====================================================================
# Owed round 3 (2026-09-25)
# ====================================================================

# -------- the zero-file capped row keeps its CR-311 hold (api.py sets `held`)

def test_a_held_zero_file_capped_row_shows_the_hold_not_leave_it_running():
    held = {"reason": "drive_missing",
            "sentence": "Its sync drive is unplugged, so nothing can upload.",
            "since": None}
    html = " ".join(_render_transfers([dict(_up_uncertain(), held=held)]).split())
    # HEAD of round 2: the CANNOT TELL branch never rendered `held`, and told
    # the admin to leave a machine running that is not uploading at all.
    assert "[ CANNOT TELL ]" in html
    assert "[ ON HOLD ]" in html
    assert "Its sync drive is unplugged, so nothing can upload." in html
    assert "Leave it running and check its tray." not in html
    assert "—" not in html and " -- " not in html


def test_an_unheld_zero_file_capped_row_still_says_check_its_tray():
    html = " ".join(_render_transfers([dict(_up_uncertain(), held=None)]).split())
    assert "Leave it running and check its tray." in html
    assert "[ ON HOLD ]" not in html
