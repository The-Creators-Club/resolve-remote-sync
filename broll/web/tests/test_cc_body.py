"""B-roll's body in the terminal look (UI redesign port, phase 6, 2026-09-25).

docs/UI_REDESIGN_PORT_PLAN.md 1.4, 4.1, 7.0, 7.1 row 6. The music and
youtube suites carry their own test_cc_body.py; this is b-roll's.

What it pins: html.cc is in the markup (the terminal look is the only look
since 2026-09-25, so nothing switches it and the retired look cookie is
cleared, never read), and the loader only toggles cc-chrome on whether a HUD
arrived; the helper cc_spa.js loads before app.js, is
served under the mount and is byte-identical with the other apps' copies;
the cc-spa-common block is byte-identical with music's; every phase 6 rule
is scoped to html.cc, so the classic app and the client share page (R22)
are untouched; the clip detail goes beside the grid only in the terminal
look; every confirm keeps the browser's confirm when the look is off.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve()
_APP_DIR = _HERE.parents[1]
_REPO = _HERE.parents[3]
STATIC = _APP_DIR / "static"
SHEET = STATIC / "style.css"
HELPER = STATIC / "cc_spa.js"
INDEX = STATIC / "index.html"
NODE = shutil.which("node")

OTHER_HELPERS = [p for p in (_REPO / "music" / "web" / "static" / "cc_spa.js",
                             _REPO / "ytdl" / "web" / "static" / "cc_spa.js")
                 if p.exists()]
MUSIC_SHEET = _REPO / "music" / "web" / "static" / "style.css"
BEGIN, END = "cc-spa-common BEGIN", "cc-spa-common END"
APP_MARK = "B-roll in the terminal look (UI port phase 6"
WINDOWS = {"search": "header-controls", "browse": "folder-tree",
           "results": "grid-view", "clip": "detail-view"}
_ABSOLUTE = re.compile(r"""["'`(](/[^"'`)\s>]*)""")
ASK = "((window.ccSpa && window.ccSpa.active()) ? await window.ccSpa.confirm(q) : window.confirm(q))"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def _strip_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _phase6_css() -> str:
    raw = _text(SHEET)
    assert raw.count(BEGIN) == 1 and raw.count(END) == 1
    tail = raw[raw.index("/* ==== " + BEGIN):]
    assert APP_MARK in tail, "b-roll's own terminal block follows cc-spa-common"
    return tail


def _selectors(css: str):
    css = _strip_comments(css)
    out, buf, depth = [], "", 0
    for ch in css:
        if ch == "{":
            head = buf.strip()
            if not head.startswith("@"):
                out.append(head)
            buf = ""
            depth += 1
        elif ch == "}":
            buf = ""
            depth -= 1
        elif ch == ";" and depth:
            buf = ""
        else:
            buf += ch
    return out


# ------------------------------------------------------------- first paint

def test_html_cc_is_in_the_markup_and_the_head_script_reads_no_cookie():
    html = _text(INDEX)
    assert '<html lang="en" class="cc">' in html
    head = html.split("</head>", 1)[0]
    script = head.split("<script>", 1)[1].split("</script>", 1)[0]
    # the retired look cookie is cleared, never read or switched on
    assert "document.cookie.split" not in script and "indexOf('apps')" not in script
    assert "cl.add('cc')" not in script
    assert "document.cookie = 'ccsync_ui_effective=; path=/; max-age=0'" in script
    assert "document.body" not in script
    assert not _ABSOLUTE.findall(script)


@pytest.mark.skipif(not NODE, reason="node is not on PATH")
@pytest.mark.parametrize("cookie", [
    "ccsync_ui_effective=chrome.apps", "x=1; ccsync_ui_effective=apps", "",
])
def test_the_head_script_runs(cookie, tmp_path):
    # Whatever an old cookie said, the hold starts and the cookie is cleared.
    head = _text(INDEX).split("</head>", 1)[0]
    script = head.split("<script>", 1)[1].split("</script>", 1)[0]
    harness = (
        "const cls = new Set();\n"
        "global.document = {cookie: %s, documentElement: {classList: {add: c => cls.add(c), remove: c => cls.delete(c)}}};\n"
        "global.setTimeout = () => 0;\n%s\n"
        "process.stdout.write(JSON.stringify([[...cls].sort(), document.cookie]));\n"
    ) % (json.dumps(cookie), script)
    f = tmp_path / "head.js"
    f.write_text(harness, encoding="utf-8")
    out = subprocess.run([NODE, str(f)], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    classes, written = json.loads(out.stdout)
    assert classes == ["cc-chrome", "cc-chrome-pending"]
    assert written == "ccsync_ui_effective=; path=/; max-age=0"


def test_the_loader_toggles_only_cc_chrome_on_the_hud():
    js = _text(STATIC / "app.js")
    body = js[js.index("function syncDashboardLook("):]
    body = body[:body.index("\n}\n")]
    assert 'host.querySelector(".hud")' in body
    assert 'classList.toggle("cc-chrome", hud)' in body
    # html.cc is markup: nothing switches it, and the marker is gone
    assert 'toggle("cc",' not in body and "data-ui-apps" not in body
    # the chrome can arrive under an open clip: the detail follows it
    assert "relayoutDetail();" in body


# -------------------------------------------------------------- the helper

def test_the_helper_loads_before_app_js():
    html = _text(INDEX)
    assert html.count('<script src="static/cc_spa.js"></script>') == 1
    assert html.index('src="static/cc_spa.js"') < html.index('src="static/app.js"')


def test_the_helper_is_byte_identical_with_the_other_apps():
    assert OTHER_HELPERS, "music and youtube ship the same helper"
    mine = HELPER.read_bytes().replace(b"\r\n", b"\n")
    for p in OTHER_HELPERS:
        assert p.read_bytes().replace(b"\r\n", b"\n") == mine, f"{p} drifted"


def test_the_helper_passes_the_mount_and_dash_rules():
    raw = _text(HELPER)
    assert not _ABSOLUTE.findall(raw)
    assert "—" not in raw and "–" not in raw
    assert "root.classList.contains('cc')" in raw


def test_the_helper_is_served_under_the_mount():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.main import app as broll_app
    parent = FastAPI()
    parent.mount("/broll", broll_app)
    with TestClient(parent) as c:
        r = c.get("/broll/static/cc_spa.js")
    assert r.status_code == 200
    assert "window.ccSpa" in r.text


def test_the_share_page_never_takes_the_terminal_look():
    """R22: the public client page loads this app's style.css, never the
    helper, and nothing on it sets html.cc."""
    for name in ("share.html", "share.js"):
        text = _text(STATIC / name)
        assert "cc_spa" not in text and "html.cc" not in text, name
        assert "classList.add('cc')" not in text and 'classList.add("cc")' not in text


# ----------------------------------------------------------------- windows

def test_the_windows_are_marked():
    html = _text(INDEX)
    for title, ident in WINDOWS.items():
        tag = re.search(r'<[a-z]+ [^>]*(?:id|class)="%s"[^>]*>' % ident, html).group(0)
        assert f'data-cc-win="{title}"' in tag, title


def test_the_detail_goes_beside_the_grid_only_in_the_terminal_look():
    js = _text(STATIC / "app.js")
    body = js[js.index("function relayoutDetail("):]
    body = body[:body.index("\n}\n")]
    assert 'document.documentElement.classList.contains("cc")' in body
    assert 'layout.classList.toggle("hidden", open)' in body   # classic: replaces
    css = _phase6_css()
    assert "html.cc #browse-layout.cc-with-detail > #detail-view" in css


# ------------------------------------------------------------------- sheet

def test_cc_spa_common_is_identical_with_musics():
    if not MUSIC_SHEET.exists():
        pytest.skip("no music checkout beside this one")
    mine = _text(SHEET).split(BEGIN, 1)[1].split(END, 1)[0]
    theirs = _text(MUSIC_SHEET).split(BEGIN, 1)[1].split(END, 1)[0]
    assert mine == theirs


def test_every_phase6_rule_is_scoped_to_the_terminal_look():
    for sel in _selectors(_phase6_css()):
        for part in sel.split(","):
            part = part.strip()
            assert (part.startswith("html.cc") or part.startswith("html:not(.cc)")
                    or part.startswith(".cc-spa-")), f"unscoped rule: {part!r}"


def test_phase6_css_has_no_bracket_content_dash_or_root_url():
    css = _phase6_css()
    for m in re.finditer(r"content:\s*([^;]+);", _strip_comments(css)):
        assert "[" not in m.group(1) and "]" not in m.group(1), m.group(0)
    assert "—" not in css and "–" not in css
    assert not _ABSOLUTE.findall(css)


def test_the_grid_and_detail_keep_room_for_the_dock():
    css = _phase6_css()
    assert "html.cc #grid-view[data-cc-win] { padding: 0 var(--ccs-pad) calc(16px + var(--cc-dock-h, 0px)); }" in css
    assert "html.cc #detail-view[data-cc-win] { padding: 0 var(--ccs-pad) calc(16px + var(--cc-dock-h, 0px));" in css


# ---------------------------------------------------------------- confirms

def test_every_confirm_keeps_the_browser_confirm_when_the_look_is_off():
    ingest = _text(STATIC / "ingest.js")
    folders = _text(STATIC / "clientfolders.js")
    assert ingest.count(ASK) == 3
    assert folders.count(ASK) == 3
    for js in (ingest, folders):
        bare = js.replace(ASK, "")
        assert "window.confirm(" not in bare, "a confirm that skips the terminal dialog"
