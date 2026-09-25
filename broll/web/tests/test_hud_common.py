"""The terminal HUD in this app (UI redesign port, phase 1, 2026-09-25).

docs/UI_REDESIGN_PORT_PLAN.md 4.1, 7.0, R6, R16, R22. The dashboard's
/partials/topbar serves the HUD (its only header since the look switch was
retired, 2026-09-25), this app injects it with innerHTML, and THIS
stylesheet paints it: so the hud-common block here must be the same bytes as
the dashboard's static/cc/hud.css (fix a drift by copying the block). The
first-paint hold no longer reads a look cookie: it always holds, and the
loader ends the hold on whatever arrived.
"""
from __future__ import annotations

import re
from pathlib import Path

_HERE = Path(__file__).resolve()
_REPO_ROOT = _HERE.parents[3]
STATIC = _HERE.parent.parent / "static"
SHEET = STATIC / "style.css"
DASH_HUD = _REPO_ROOT / "dashboard" / "static" / "cc" / "hud.css"
BEGIN, END = "hud-common BEGIN", "hud-common END"
FONT_PREFIX = "../../static/fonts/"
MARK = "the terminal HUD (UI port phase 1"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def _block(path: Path) -> str:
    raw = _text(path)
    assert raw.count(BEGIN) == 1, f"{path} must carry hud-common exactly once"
    return raw.split(BEGIN, 1)[1].split(END, 1)[0]


def _strip_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def test_hud_common_matches_the_dashboards_copy():
    assert _block(SHEET) == _block(DASH_HUD), (
        "hud-common drifted from dashboard/static/cc/hud.css: copy the block")


def test_hud_common_sits_after_every_existing_block():
    css = _text(SHEET)
    # first-occurrence slicing tests (the phone blocks, theme-common) must
    # never see the HUD's queries first
    assert css.index(BEGIN) > css.index("theme-common END")
    assert css.index(BEGIN) > css.index("END nav drawer, menu button, settings gear")


def test_the_classic_drawer_block_is_still_here():
    assert "BEGIN nav drawer, menu button, settings gear" in _text(SHEET)


def test_the_phase_one_rules_are_all_scoped():
    """R22 and the HUD's own rule: everything this phase added outside
    hud-common is keyed on the HUD's presence, the first-paint class or
    #dash-topbar, or is an @font-face, so a page without the HUD is
    untouched."""
    # both pieces start inside a marker comment: reopen it before stripping
    tail = (_strip_comments("/*" + _text(SHEET).split(MARK, 1)[1].split(BEGIN, 1)[0])
            + _strip_comments("/*" + _text(SHEET).split(END, 1)[1]
                              .split("/* ==== cc-spa-common BEGIN", 1)[0]))
    # phase 6's body rules follow and are pinned by test_cc_body.py
    # (every one under html.cc)
    allowed = ("html:has(.hud", "body:has(.hud-dock)", "html.cc-chrome-pending",
               "#dash-topbar:has(> .hud) + .rule", "html:has(#dash-topbar > .hud) body")
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", tail):
        sel = m.group(1).strip()
        if sel.startswith("@") or not sel:
            continue
        for part in (p.strip() for p in sel.split(",")):
            assert part.startswith(allowed), part
    assert "@font-face" in tail


def test_the_dock_lift_and_the_rule_hide_exist():
    css = _strip_comments(_text(SHEET))
    assert re.search(r"@media \(max-width: 600px\) \{\s*html:has\(\.hud-dock\) \{ --cc-dock-h:", css)
    assert len(re.findall(r"--cc-dock-h\s*:", css)) == 1
    assert "#dash-topbar:has(> .hud) + .rule { display: none; }" in css
    assert "html.cc-chrome-pending #dash-topbar:not(:has(> .hud)) { min-height: 58px;" in css
    assert "html.cc-chrome-pending #dash-topbar:not(:has(> .hud)) > * { visibility: hidden; }" in css
    assert "html.cc-chrome-pending #dash-topbar + .rule { display: none; }" in css


def test_the_font_urls_point_at_the_dashboards_fonts():
    urls = re.findall(r"src:\s*url\(([^)]+)\)", _text(SHEET))
    assert urls and all(u == FONT_PREFIX + u.rsplit("/", 1)[1] for u in urls), urls
    for u in urls:
        assert (_REPO_ROOT / "dashboard" / "static" / "fonts" / u.rsplit("/", 1)[1]).exists(), u


def test_the_first_paint_script_holds_the_hud_height():
    html = _text(STATIC / "index.html")
    head = html.split("</head>", 1)[0]
    script = head.split("<script>", 1)[1].split("</script>", 1)[0]
    assert head.index("<script>") < head.index('rel="stylesheet"')
    # the hold is unconditional now: no look cookie is read to decide it
    assert "document.cookie.split" not in script and "slice(20)" not in script
    assert "cl.add('cc-chrome');" in script and "cl.add('cc-chrome-pending');" in script
    assert "cc-chrome-pending" in script and "setTimeout" in script
    assert "match(/" not in script and "\u2014" not in script


def test_the_loader_trusts_what_arrived():
    js = _text(STATIC / "app.js")
    fn = js.split("function syncDashboardLook(host)", 1)[1].split("\n}\n", 1)[0]
    # the look cookie is retired: the loader writes none, reads no marker
    assert "document.cookie" not in fn and "data-ui-apps" not in fn
    assert "cc-chrome" in fn and '.querySelector(".hud")' in fn
    loader = js.split("async function loadDashboardTopbar()", 1)[1].split("\n}\n", 1)[0]
    assert "finally {" in loader
    assert "cc-chrome-pending" in loader.split("finally {", 1)[1]
    assert "syncDashboardLook(host)" in loader


def test_the_body_grows_so_the_hud_sticks():
    assert "html:has(#dash-topbar > .hud) body { height: auto; min-height: 100%; }" in _text(SHEET)


def test_the_pager_and_panels_clear_the_dock():
    css = _text(SHEET)
    assert "body:has(.hud-dock) #grid-view { padding-bottom: calc(40px + var(--cc-dock-h, 0px)); }" in css
    assert "body:has(.hud-dock) #toast-container" in css
    for panel in ("#settings-panel", "#ingest-panel", "#cf-panel"):
        assert f"body:has(.hud-dock) {panel}" in css


def test_index_and_static_are_revalidated(tmp_path):
    """R16: an always-fresh topbar must never meet a heuristically cached
    old sheet that cannot paint it."""
    from fastapi.testclient import TestClient
    from app.main import app as broll_app
    with TestClient(broll_app) as c:
        for path in ("/", "/static/style.css", "/static/app.js"):
            r = c.get(path)
            assert r.status_code == 200, path
            assert r.headers.get("cache-control") == "no-cache", path
        # the client share page's asset mount is not changed
        assert c.get("/share/assets/style.css").headers.get("cache-control") != "no-cache"
