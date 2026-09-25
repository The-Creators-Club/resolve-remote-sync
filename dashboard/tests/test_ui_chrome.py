"""The terminal chrome (UI redesign port, phase 1 "chrome", 2026-09-25).

docs/UI_REDESIGN_PORT_PLAN.md 2.2, 2.5, 3.4, 4.1, 7.0, R6, R9, R15, R16.
Since the owner retired the look switch the same day, the terminal chrome is
the ONLY chrome: these tests used to switch the `chrome` group on through
ui_variant and pin the classic bar beside it. The classic half is gone with
the classic look; what is left pins the one chrome every page and every SPA
gets.
"""
from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin

import pytest
from fastapi.testclient import TestClient
from jinja2 import ChoiceLoader, DictLoader

from ccsync_dashboard import auth, ui
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "s" * 32
DASH = Path(__file__).resolve().parents[1]
REPO = DASH.parent
HUD_CSS = DASH / "static" / "cc" / "hud.css"
TEMPLATES = DASH / "templates"
SPA_SHEETS = {
    "broll": (REPO / "broll" / "web" / "static" / "style.css", "/broll/static/style.css"),
    "music": (REPO / "music" / "web" / "static" / "style.css", "/music/style.css"),
    "ytdl": (REPO / "ytdl" / "web" / "static" / "style.css", "/ytdl/style.css"),
}
BEGIN, END = "hud-common BEGIN", "hud-common END"
# ytdl's deny-by-default root-relative scan (its test_mounted_prefix.py).
ABSOLUTE = re.compile(r"""["'`(](/[^"'`)\s>]*)""")


def _block(path: Path) -> str:
    raw = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    assert raw.count(BEGIN) == 1, f"{path} must carry hud-common exactly once"
    return raw.split(BEGIN, 1)[1].split(END, 1)[0]


def _strip_comments(css: str) -> str:
    # A block starts inside its BEGIN marker's comment: close it first.
    if not css.lstrip().startswith("/*") and "*/" in css.split("{", 1)[0]:
        css = "/*" + css
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _rules(css: str):
    """(selector, body) for every innermost rule, media queries flattened."""
    return [(m.group(1).strip(), m.group(2))
            for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", _strip_comments(css))]


# ----------------------------------------------------------- hud-common

def test_hud_common_is_byte_identical_in_all_four_sheets():
    ref = _block(HUD_CSS)
    assert ref.strip()
    drifted = [name for name, (path, _url) in SPA_SHEETS.items() if _block(path) != ref]
    assert not drifted, "hud-common drifted from static/cc/hud.css in: " + ", ".join(drifted)


def test_hud_common_selectors_are_hud_owned():
    for sel, _body in _rules(_block(HUD_CSS)):
        if sel.startswith("@") or re.fullmatch(r"\d+%|from|to", sel):
            continue
        for part in (p.strip() for p in sel.split(",")):
            assert re.match(r"(\.hud|\.snav|header\.hud-host|#dash-topbar:has\(> \.hud\))", part), part
            assert not re.match(r"(html|body|:root)\b", part), part


def test_popover_base_rules_declare_no_display():
    positioned = []
    for sel, body in _rules(_block(HUD_CSS)):
        parts = [p.strip() for p in sel.split(",")]
        if all(d.strip().startswith("--") for d in body.split(";") if d.strip()):
            continue  # the token declarations
        if any(p in (".hud-menu", ".hud-more", "#hud-more", "#hud-user") for p in parts):
            assert "display" not in body, sel
            positioned.append(body)
    assert any("position: fixed" in b for b in positioned)
    assert sum("inset:" in b for b in positioned) >= 2  # the menu and the sheet
    css = _strip_comments(_block(HUD_CSS))
    assert ".hud-menu:popover-open, .hud-more:popover-open { display: flex" in css


def test_every_hud_token_is_namespaced_and_declared_or_defaulted():
    block = _strip_comments(_block(HUD_CSS))
    declared = set(re.findall(r"(--cc-[\w-]+)\s*:", block))
    for name, fallback in re.findall(r"var\((--[\w-]+)\s*(,)?", block):
        assert name.startswith("--cc-"), name
        assert name in declared or fallback, name


def test_hud_common_passes_the_shared_scans():
    block = _block(HUD_CSS)
    assert not [m for m in ABSOLUTE.findall(block) if m != "/"]
    assert "—" not in block and "–" not in block
    assert "backdrop-filter" not in block
    assert "infinite" not in block
    assert "thecreatorsclub" not in block.lower()
    assert "@font-face" not in block and "font-family: var(--cc-mono)" in block


def test_the_dock_query_is_600_and_nothing_under_12px_inside_it():
    css = _strip_comments(_block(HUD_CSS))
    phone = css.split("@media (max-width: 600px) {", 1)[1]
    phone = phone.split("\n}\n", 1)[0]
    assert ".hud-dock {" in phone and "position: fixed" in phone
    for size in re.findall(r"font-size:\s*(\d+)px", phone):
        assert int(size) >= 12, phone
    # the one dock query: --cc-dock-h is declared on the root inside the same
    # query, outside hud-common, in every sheet
    for path in [HUD_CSS] + [p for p, _ in SPA_SHEETS.values()]:
        text = _strip_comments(path.read_text(encoding="utf-8").replace("\r\n", "\n"))
        m = re.search(r"@media \(max-width: (\d+)px\) \{\s*html:has\(\.hud-dock\) \{ --cc-dock-h:", text)
        assert m and m.group(1) == "600", path
        assert len(re.findall(r"--cc-dock-h\s*:", text)) == 1, path


def test_hud_common_carries_the_a11y_and_standalone_blocks():
    css = _strip_comments(_block(HUD_CSS))
    assert "@media (forced-colors: active)" in css
    assert "@media (prefers-reduced-motion: reduce)" in css
    assert "@media (display-mode: standalone)" in css and "env(safe-area-inset-top, 0px)" in css
    assert "@media (pointer: coarse)" in css and "min-height: var(--cc-tap)" in css
    assert "outline: 2px solid var(--cc-hi)" in css
    assert "animation: hud-blink 1.2s steps(1) 4" in css
    assert "header.hud-host { display: contents; }" in css
    assert "#dash-topbar:has(> .hud) { display: contents;" in css
    assert "@media (min-width: 601px) and (max-width: 900px)" in css
    assert ".hud-more-btn { display: inline-flex; }" in css


def test_hud_css_outside_the_block_styles_no_hud_element():
    text = HUD_CSS.read_text(encoding="utf-8")
    outside = text.split(BEGIN)[0] + text.split(END, 1)[1]
    for sel, _ in _rules(outside):
        cleaned = re.sub(r":has\([^)]*\)", "", sel)
        assert not re.search(r"\.hud|#hud-|\.dock|\.snav", cleaned), sel
    assert not [m for m in ABSOLUTE.findall(outside) if m != "/"]
    assert "backdrop-filter" not in outside and "—" not in outside


def test_the_spa_font_urls_resolve_to_the_dashboards_fonts(tmp_path):
    with TestClient(create_app(Settings(db_path=str(tmp_path / "d.db"),
                                        session_secret=SECRET))) as c:
        for name, (path, served) in list(SPA_SHEETS.items()) + [("dash", (HUD_CSS, "/static/cc/hud.css"))]:
            urls = re.findall(r"src:\s*url\(([^)]+)\)", path.read_text(encoding="utf-8"))
            assert urls, name
            for u in urls:
                resolved = urljoin(served, u)
                assert resolved.startswith("/static/fonts/"), (name, resolved)
                r = c.get(resolved)
                assert r.status_code == 200, (name, resolved)
                assert r.headers["content-type"].startswith("font/woff2")


# ------------------------------------------------------------ rendering

def _client(tmp_path, admins=frozenset({"owen"})) -> TestClient:
    return TestClient(create_app(Settings(db_path=str(tmp_path / "d.db"),
                                          session_secret=SECRET, admin_users=admins)))


def _as(client, user):
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, user))
    return client


class _Tree(HTMLParser):
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
            "meta", "source", "track", "wbr", "path", "circle"}

    def __init__(self):
        super().__init__()
        self.stack: list[tuple[str, dict]] = []
        self.elems: list[tuple[str, dict, tuple[str, ...]]] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        chain = tuple(c for _, d in self.stack for c in (d.get("class") or "").split())
        self.elems.append((tag, a, chain))
        if tag not in self.VOID:
            self.stack.append((tag, a))

    def handle_startendtag(self, tag, attrs):
        a = dict(attrs)
        chain = tuple(c for _, d in self.stack for c in (d.get("class") or "").split())
        self.elems.append((tag, a, chain))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break


def _parse(html: str) -> _Tree:
    t = _Tree()
    t.feed(html)
    return t


def test_topbar_is_the_hud(tmp_path):
    with _client(tmp_path) as c:
        r = _as(c, "jsmith").get("/partials/topbar?current=transfers")
        assert r.status_code == 200
        html = r.text
        mounted = c.app.state
    assert 'class="hud"' in html and "data-dash-topbar" in html
    # the SPAs' classic-bar marker went with the switch (2026-09-25)
    assert "data-ui-apps" not in html
    assert "<script" not in html and "[ " not in html
    assert "nav-drawer" not in html and "menu-btn" not in html
    # only mounted modules (music may mount from the dev tree in this venv)
    for mod, flag in (("/broll/", "broll_mounted"), ("/music/", "music_mounted"),
                      ("/ytdl/", "ytdl_mounted"), ("/cards/", "cards_mounted")):
        assert (f'href="{mod}"' in html) == bool(getattr(mounted, flag, False)), mod
    assert re.search(r'<a href="/transfers" aria-current="page">', html)
    # sign out, everywhere (with its confirm), installer, help, account survive
    for needle in ('action="/logout"', 'action="/logout-everywhere"', "window.confirm(",
                   'href="/download"', 'href="/help"', 'href="/account"', 'id="install-slot"'):
        assert needle in html, needle
    # counts absent at zero, and an editor gets none
    assert "hud-count" not in html
    tree = _parse(html)
    for tag, attrs, chain in tree.elems:
        if "popovertarget" in attrs:
            assert tag == "button", attrs
            assert attrs.get("type") == "button", attrs
        if "hud-dock" in (attrs.get("class") or "").split():
            assert "hud" not in chain, "the dock must be a sibling of .hud (R7)"
    # the SPAs' first-paint look cookie is retired: the SPAs are terminal
    # in markup now, so the bar never sets it again
    assert not any(k.lower() == "set-cookie" and "ccsync_ui_effective" in v
                   for k, v in r.headers.multi_items())


def test_topbar_counts_show_in_the_spas_when_nonzero(tmp_path, monkeypatch):
    monkeypatch.setattr(ui, "_notice_counts_safe", lambda s: {"error": 3})
    monkeypatch.setattr(ui, "_alert_counts_safe", lambda s: {"warn": 1})
    with _client(tmp_path) as c:
        html = _as(c, "owen").get("/partials/topbar?current=broll").text
    assert "<b>3</b> problems" in html and "<b>1</b> alert<" in html
    assert 'href="/go/notices"' in html
    # no "look" menu section: there is one look (2026-09-25)
    assert "ui/preview" not in html and "classic" not in html


_ALLOWED_UNPREFIXED = {"scroll-x"}


def _classes(html: str) -> set[str]:
    out = set()
    for m in re.finditer(r'class="([^"]*)"', html):
        out.update(m.group(1).split())
    return out


def test_every_class_in_the_rendered_chrome_is_hud_owned(tmp_path, monkeypatch):
    monkeypatch.setattr(ui, "_notice_counts_safe", lambda s: {"error": 2})
    monkeypatch.setattr(ui, "_alert_counts_safe", lambda s: {"error": 1, "warn": 2})
    monkeypatch.setattr(ui, "_stamp_context",
                        lambda conn: {"stamp_at": "2026-09-25T00:00:00Z",
                                      "stamp_syncthing_reachable": False})
    seen = set()
    with _client(tmp_path) as c:
        _as(c, "owen")
        seen |= _classes(c.get("/partials/topbar").text)
        page = c.get("/admin/users").text
        seen |= _classes(page.split('<nav class="snav', 1)[1].split("</nav>", 1)[0])
        seen.add("snav")
        headers = _page_headers(page)
        stale = c.get("/partials/stamp", headers=headers).text
        seen |= _classes(stale)
        _as(c, "jsmith")
        seen |= _classes(c.get("/partials/topbar").text)
    assert "hud-stale" in seen
    bad = sorted(x for x in seen if not x.startswith(("hud", "snav")) and x not in _ALLOWED_UNPREFIXED)
    assert not bad, bad
    block = _block(HUD_CSS)
    for cls in _ALLOWED_UNPREFIXED:
        assert f".{cls}" in block


def _page_headers(page: str) -> dict:
    m = re.search(r"<body hx-headers='([^']*)'", page)
    assert m, "no hx-headers on <body>"
    hdrs = json.loads(m.group(1).replace("&#34;", '"').replace("&quot;", '"'))
    hdrs["HX-Request"] = "true"
    return hdrs


def test_a_page_gets_the_bare_host_and_hud_sheet(tmp_path):
    with _client(tmp_path) as c:
        page = _as(c, "owen").get("/admin/users").text
    assert '<header class="hud-host">' in page and '<header class="topbar">' not in page
    assert re.search(r'href="/static/cc/hud\.css\?h=[0-9a-f]{10}"', page)
    assert "/static/style.css" not in page and "/static/mobile.css" not in page
    assert '<nav class="snav scroll-x"' in page and "settings-nav-item" not in page
    # the halt line on its own route, never the classic banner (R15)
    assert 'hx-get="/partials/halt-line"' in page and "fleet-halt-banner" not in page


def test_the_stamp_poll_from_a_page_gets_the_hud_stamp(tmp_path):
    with _client(tmp_path) as c:
        _as(c, "owen")
        page = c.get("/admin/users").text
        headers = _page_headers(page)
        assert headers.get(ui.LOOK_HEADER) == ui.LOOK_VALUE == "terminal"
        r = c.get("/partials/stamp", headers=headers)
    assert r.status_code == 200 and "hud-stamp-at" in r.text and "stamp-at" not in r.text.replace("hud-stamp-at", "")


def test_the_halt_line_route_follows_the_page(tmp_path, monkeypatch):
    halted = {"halt": {"active": True, "reason": "NAS swap", "set_by": "owen",
                       "set_at": "2026-09-25T00:00:00Z", "expires_at": None},
              "halt_hours": 2, "halt_machines": 4}
    with _client(tmp_path) as c:
        _as(c, "owen")
        headers = _page_headers(c.get("/admin/users").text)
        quiet = c.get("/partials/halt-line", headers=headers)
        assert quiet.status_code == 200 and quiet.text.strip() == ""
        monkeypatch.setattr(ui, "_halt_banner_context", lambda conn: halted)
        r = c.get("/partials/halt-line", headers=headers)
        assert r.status_code == 200
        assert "Syncing is stopped on every computer" in r.text and "NAS swap" in r.text
        assert "[ " not in r.text and 'class="v">NAS swap' in r.text
        assert 'href="/admin/users#admin-fleet-halt"' in r.text
        # a page drawn by an older build (htmx without X-CC-UI: terminal)
        # never gets it: the stale-page gate tells it to reload instead
        stale = c.get("/partials/halt-line", headers={"HX-Request": "true"})
        assert stale.status_code == 200 and stale.text == ""
        assert stale.headers.get("HX-Refresh") == "true"
    (tmp_path / "x").mkdir()
    with _client(tmp_path / "x") as c2:
        anon = c2.get("/partials/halt-line", follow_redirects=False)
        assert anon.status_code in (401, 302, 303, 307)


def test_the_offline_page_names_nobody(tmp_path, monkeypatch):
    monkeypatch.setattr(ui, "_notice_counts_safe", lambda s: {"error": 3})
    with _client(tmp_path) as c:
        _as(c, "owen")
        html = c.get("/offline").text
    # a bare gate page since it moved onto shell.html: no HUD at all, so
    # nothing on it can go stale in the service worker's cache
    assert "hud-host" not in html and 'class="hud"' not in html
    assert "cc/hud.css" in html and "Try again" in html
    assert "hud-count" not in html and 'href="/account"' not in html
    assert "owen" not in html


# ------------------------------------------------ the shell (test-only child)

_PROBE = ('{% extends "shell.html" %}{% block layout %}'
          '<main class="page"><p>probe</p></main>{% endblock %}')


def test_the_terminal_shell(tmp_path):
    env = ui.templates.env
    orig = env.loader
    env.loader = ChoiceLoader([DictLoader({"cc_probe.html": _PROBE}), orig])
    try:
        html = env.get_template("cc_probe.html").render(
            csrf_token="tok123", brand_org="Studio", session_user="jsmith",
            session_is_admin=False, nav_current="", request=None)
    finally:
        env.loader = orig
    # one look: no group set, no generation, no signature on the root
    assert '<html lang="en" data-ui="cc">' in html
    assert "data-ui-groups" not in html and "data-ui-sig" not in html
    hdrs = json.loads(re.search(r"<body hx-headers='([^']*)'", html).group(1))
    # the look header every page sends, which app.stale_page_gate checks
    assert hdrs == {"X-CSRF-Token": "tok123", "X-CC-UI": "terminal"}
    srcs = re.findall(r'<script src="([^"]+)"', html)
    names = [s.split("?")[0] for s in srcs]
    assert names == ["/static/pwa.js", "/static/htmx.min.js", "/static/htmx_errors.js",
                     "/static/cc/copy_value.js", "/static/tab_memory.js", "/static/cc/cc.js"]
    sheets = [s.split("?")[0] for s in re.findall(r'<link rel="stylesheet" href="([^"]+)"', html)]
    assert sheets == ["/static/cc/hud.css", "/static/cc/terminal.css",
                      "/static/cc/components.css", "/static/cc/phone.css"]
    assert "/static/style.css" not in html and "/static/mobile.css" not in html
    assert '<header class="hud-host">' in html and 'class="hud"' in html
    # hint sheet: block 2's three hooks, hidden, and NOT the classic chip sheet
    assert re.search(r'<div id="chip-sheet" class="hint-sheet"[^>]*hidden>', html)
    assert 'class="chip-sheet-label"' in html and 'class="chip-sheet-text"' in html
    assert 'class="chip-sheet"' not in html
    assert '<dialog id="cc-confirm"' in html and "autofocus" in html
    assert 'hx-get="/partials/halt-line"' in html and "fleet-halt-banner" not in html
    assert "[ " not in html.split("<body", 1)[1]
    assert "—" not in html


# ------------------------------------------------------------- scripts

def test_block_two_has_one_explicit_selector_with_summary_exempt():
    js = (DASH / "static" / "htmx_errors.js").read_text(encoding="utf-8")
    assert '".hud-led[title], .chip[title], .dot[title]"' in js
    assert '"[data-tip], [data-chip-detail], .tag[title], .led[title], "' in js
    assert 'var CONTROLS = "a, button, input, select, textarea, label, summary";' in js
    assert 'chip.getAttribute("data-tip") || chip.getAttribute("data-chip-detail")' in js


def test_pwa_install_button_is_the_hud_key():
    # the slot only exists in the HUD's "more" sheet since the classic
    # drawer went (2026-09-25), so the bracketed classic chip went with it
    js = (DASH / "static" / "pwa.js").read_text(encoding="utf-8")
    assert "btn.className = 'hud-key install-btn';" in js
    assert "'install this app'" in js
    assert "btn chip tap install-btn" not in js and "[ INSTALL ]" not in js
