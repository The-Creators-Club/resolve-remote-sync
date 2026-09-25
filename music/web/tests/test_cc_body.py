"""The terminal body look in this app (UI redesign port, phase 6, 2026-09-25).

docs/UI_REDESIGN_PORT_PLAN.md 7.1 row 6, 4.1, 7.0. The same file sits in
music/web/tests and ytdl/web/tests: it finds its app from its own path.

What it pins: the head script turns on html.cc before first paint when the
dashboard's readable cookie lists `apps`; the helper cc_spa.js is loaded
before app.js, served under the mount, and byte-identical in every app that
ships it; the cc-spa-common CSS block is byte-identical between the music and
youtube sheets; every phase 6 rule is scoped to html.cc (so the classic page
is untouched); the terminal labels carry no brackets (the helper's label
transform, run in node); the confirm paths keep the classic browser confirm.
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
APP = _APP_DIR.parent.name  # 'music' or 'ytdl'
STATIC = _APP_DIR / "static"
SHEET = STATIC / "style.css"
HELPER = STATIC / "cc_spa.js"
INDEX = STATIC / "index.html"
NODE = shutil.which("node")

# Every app that ships the helper; b-roll joins when its phase 6 lands.
HELPER_COPIES = [
    p for p in (
        _REPO / "music" / "web" / "static" / "cc_spa.js",
        _REPO / "ytdl" / "web" / "static" / "cc_spa.js",
        _REPO / "broll" / "web" / "static" / "cc_spa.js",
    ) if p.exists()
]
SHEETS_WITH_COMMON = [
    _REPO / "music" / "web" / "static" / "style.css",
    _REPO / "ytdl" / "web" / "static" / "style.css",
]
BEGIN, END = "cc-spa-common BEGIN", "cc-spa-common END"
APP_MARK = "in the terminal look (UI port phase 6"

WINDOWS = {
    "music": {"feel": None, "tempo_and_length": None, "tracks": "results"},
    "ytdl": {
        "before_you_download": "attest", "progress": "progress",
        "search_terms": "terms", "waiting_for_you": "waiting", "queue": "queue",
    },
}
OWN_FOLD = {"music": (), "ytdl": ("review", "downloads", "recent", "history")}

_ABSOLUTE = re.compile(r"""["'`(](/[^"'`)\s>]*)""")


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def _strip_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _phase6_css() -> str:
    raw = _text(SHEET)
    assert raw.count(BEGIN) == 1, "the sheet must carry cc-spa-common once"
    tail = raw[raw.index("/* ==== " + BEGIN):]
    assert APP_MARK in tail, "the app's own terminal block follows cc-spa-common"
    return tail


def _selectors(css: str):
    """Every selector list of a style rule, @media wrappers unwrapped."""
    css = _strip_comments(css)
    out = []
    depth = 0
    buf = ""
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


# ---------------------------------------------------------------- first paint

def test_the_head_script_sets_html_cc_from_the_cookie():
    head = _text(INDEX).split("</head>", 1)[0]
    script = head.split("<script>", 1)[1].split("</script>", 1)[0]
    assert "document.cookie.split('; ')" in script
    assert "indexOf('apps')" in script
    assert "cl.add('cc')" in script
    # documentElement, never document.body (there is none in <head>)
    assert "document.body" not in script
    assert not _ABSOLUTE.findall(script)


@pytest.mark.skipif(not NODE, reason="node is not on PATH")
@pytest.mark.parametrize("cookie,expect", [
    ("ccsync_ui_effective=chrome.apps", ["cc", "cc-chrome", "cc-chrome-pending"]),
    ("x=1; ccsync_ui_effective=apps", ["cc"]),
    ("ccsync_ui_effective=chrome", ["cc-chrome", "cc-chrome-pending"]),
    ("", []),
])
def test_the_head_script_runs(cookie, expect, tmp_path):
    head = _text(INDEX).split("</head>", 1)[0]
    script = head.split("<script>", 1)[1].split("</script>", 1)[0]
    harness = (
        "const cls = new Set();\n"
        "global.document = {cookie: %s, documentElement: {classList: {add: c => cls.add(c), remove: c => cls.delete(c)}}};\n"
        "global.setTimeout = () => 0;\n"
        "%s\n"
        "process.stdout.write(JSON.stringify([...cls].sort()));\n"
    ) % (json.dumps(cookie), script)
    f = tmp_path / "head.js"
    f.write_text(harness, encoding="utf-8")
    out = subprocess.run([NODE, str(f)], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout) == sorted(expect)


def test_the_topbar_marker_is_authoritative_for_html_cc():
    js = _text(STATIC / "app.js")
    body = js[js.index("function syncDashboardLook("):]
    body = body[:body.index("\n}\n")]
    assert "root.classList.toggle('cc', apps)" in body
    assert "data-ui-apps" in body


# ---------------------------------------------------------------- the helper

def test_the_helper_loads_before_app_js():
    html = _text(INDEX)
    assert html.count('<script src="cc_spa.js"></script>') == 1
    assert html.index('src="cc_spa.js"') < html.index('src="app.js"')


def test_the_helper_is_byte_identical_in_every_app():
    assert len(HELPER_COPIES) >= 2
    first = HELPER_COPIES[0].read_bytes().replace(b"\r\n", b"\n")
    for p in HELPER_COPIES[1:]:
        assert p.read_bytes().replace(b"\r\n", b"\n") == first, f"{p} drifted from {HELPER_COPIES[0]}"


def test_the_helper_passes_the_mount_and_dash_rules():
    raw = _text(HELPER)
    assert not _ABSOLUTE.findall(raw), "a leading-slash URL escapes the mount"
    assert "—" not in raw and "–" not in raw
    # every behaviour is gated on html.cc
    assert "root.classList.contains('cc')" in raw


def test_the_helper_is_served_under_the_mount():
    if APP == "music":
        from musicweb.main import app as sub
    else:
        from ytdlweb.main import app as sub
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    parent = FastAPI()
    parent.mount(f"/{APP}", sub)
    with TestClient(parent) as c:
        r = c.get(f"/{APP}/cc_spa.js")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/javascript")
    assert "window.ccSpa" in r.text


@pytest.mark.skipif(not NODE, reason="node is not on PATH")
def test_terminal_labels_carry_no_brackets(tmp_path):
    cases = {
        "[ ADD MUSIC ]": "Add music",
        "[ GET IT FROM THE NAS ]": "Get it from the NAS",
        "[ RETRY 3 FAILED ]": "Retry 3 failed",
        "[ include them ]": "include them",
        "[ EN + ZH ]": "EN + ZH",
        "[-] REVIEW": "Review",
        "[+] DOWNLOAD HISTORY": "Download history",
        "[ DASHBOARD ]": "Dashboard",
        "SEARCH": None,
        "5 [ clips ] here": None,
    }
    inline = {
        "all 4 filtered out: [ SHOW FILTERED OUT ] to see them":
            'all 4 filtered out: "Show filtered out" to see them',
        "Use [ CANCEL ] to end the job, or [ DOWNLOAD ON THE SERVER INSTEAD ].":
            'Use "Cancel" to end the job, or "Download on the server instead".',
        "nothing here": None,
    }
    harness = (
        "const noop = () => {};\n"
        "global.window = {addEventListener: noop};\n"
        "global.location = {pathname: '/x/'};\n"
        "global.document = {documentElement: {classList: {contains: () => false}}, readyState: 'loading',"
        " addEventListener: noop};\n"
        "global.MutationObserver = function () { this.observe = noop; };\n"
        "global.WeakMap = WeakMap;\n"
        "%s\n"
        "const s = window.ccSpa;\n"
        "process.stdout.write(JSON.stringify({labels: %s.map(t => s.label(t)), inline: %s.map(t => s.inline(t))}));\n"
    ) % (_text(HELPER), json.dumps(list(cases)), json.dumps(list(inline)))
    f = tmp_path / "labels.js"
    f.write_text(harness, encoding="utf-8")
    out = subprocess.run([NODE, str(f)], capture_output=True, text=True, timeout=30, encoding="utf-8")
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout)
    assert got["labels"] == list(cases.values())
    assert got["inline"] == list(inline.values())
    for v in list(cases.values()) + list(inline.values()):
        assert v is None or ("[" not in v and "]" not in v)


# ---------------------------------------------------------------- windows

def test_the_windows_are_marked():
    html = _text(INDEX)
    for title, ident in WINDOWS[APP].items():
        assert f'data-cc-win="{title}"' in html, title
        if ident:
            tag = re.search(r'<[a-z]+ id="%s"[^>]*>' % ident, html).group(0)
            assert f'data-cc-win="{title}"' in tag
    for ident in OWN_FOLD[APP]:
        tag = re.search(r'<section id="%s"[^>]*>' % ident, html).group(0)
        assert "data-cc-own-fold" in tag, ident
    if APP == "music":
        assert "sec.dataset.ccWin = cat;" in _text(STATIC / "app.js")


# ---------------------------------------------------------------- the sheet

def test_cc_spa_common_is_identical_in_both_sheets():
    blocks = []
    for p in SHEETS_WITH_COMMON:
        raw = _text(p)
        assert raw.count(BEGIN) == 1 and raw.count(END) == 1, p
        blocks.append(raw.split(BEGIN, 1)[1].split(END, 1)[0])
    assert blocks[0] == blocks[1]


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


def test_phase6_css_keeps_the_12px_floor_on_phones():
    css = _strip_comments(_phase6_css())
    for m in re.finditer(r"@media \(max-width: 600px\) \{(.*?)\n\}", css, flags=re.S):
        for size in re.findall(r"font-size:\s*(\d+)px", m.group(1)):
            assert int(size) >= 12


# ---------------------------------------------------------------- confirms

def test_confirms_keep_the_browser_confirm_when_the_look_is_off():
    if APP == "music":
        js = _text(STATIC / "ingest.js")
        assert js.count("window.ccSpa.active()) ? await window.ccSpa.confirm(q) : window.confirm(q)") == 2
    else:
        js = _text(STATIC / "app.js")
        assert "const confirmDiscard = msg => typeof confirm === 'function' && confirm(msg);" in js
        assert "window.ccSpa.active()) ? window.ccSpa.confirm(msg) : confirmDiscard(msg)" in js
        assert "!(await askDiscardParked())" in js
