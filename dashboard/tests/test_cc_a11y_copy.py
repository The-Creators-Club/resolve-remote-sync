"""Accessibility and copy in the terminal look (UI port review 2026-09-25,
findings a11y-copy-1 .. a11y-copy-11, fix builder F-a11y).

Each test here fails on the tree the review was run against:

- a decorative glyph drawn by CSS `content:` carries an empty alternative, so
  a control is not named "black right-pointing small triangle dismiss" (1);
- both confirm dialogs, and the SPA one, say the question they ask (2);
- the SPA tips keep a title as the accessible description and follow
  keyboard focus (3); the dashboard's tips reach keys, tabs and fields on
  focus, and a touch screen gets a "?" that opens the hint sheet (4);
- headings carry no prompt glyph and no underscore in their name (5);
- a fold names its window, and a repeated key names what it acts on (6);
- a page sheet cannot undercut the 12 px phone floor (7);
- a confirm names a key in sentence case in double quotes (8);
- the Site field hints say "server", not "machine" (9);
- the alerts never say "since never" (10);
- no customer's show name is an example path (11).

Static facts over the files where a render would need the whole app, and the
alert text through the real functions.
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from ccsync_dashboard import alerts

from test_sweep_2026_09_04_copy import _retired_words_in  # noqa: E402  (tests/ on sys.path)

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
CC_CSS = ROOT / "static" / "cc"
# The terminal look is the only look since 2026-09-25 (C-collapse): its
# templates moved up out of templates/cc/.
CC_T = ROOT / "templates"
CC_JS = CC_CSS / "cc.js"
SPA_APPS = ("broll", "music", "ytdl")
HUD_BEGIN = "/* ==== hud-common BEGIN"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def _strip_css_comments(text: str) -> str:
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


def _cc_templates() -> list[Path]:
    return sorted(CC_T.rglob("*.html"))


# ------------------------------------------------------------ a11y-copy-1

_STR = r'"(?:[^"\\\n]|\\.)*"'
_CONTENT = re.compile(r"content:\s*((?:" + _STR + r"\s*)+?)\s*(?=;|\})")


def _glyphs_without_alt(css: str) -> list[str]:
    """Every `content:` made only of strings, with something in them, that is
    neither the alt form nor followed straight away by its alt twin."""
    css = _strip_css_comments(css)
    bad = []
    for m in _CONTENT.finditer(css):
        val = m.group(1).strip()
        if all(s == '""' for s in re.findall(_STR, val)):
            continue
        after = css[m.end():m.end() + 200]
        if re.match(r"\s*/", after):
            continue
        if re.match(r";\s*content:\s*" + re.escape(val) + r"\s*/\s*" + _STR, after):
            continue
        line = css.count("\n", 0, m.start()) + 1
        bad.append(f"{line}: content: {val}")
    return bad


def _terminal_sheets() -> list[tuple[str, str]]:
    out = [(p.name, _read(p)) for p in sorted(CC_CSS.glob("*.css"))]
    for app in SPA_APPS:
        sheet = REPO / app / "web" / "static" / "style.css"
        if sheet.exists():
            text = _read(sheet)
            # hud-common and every html.cc block after it are the terminal look
            out.append((f"{app}/style.css", text[text.index(HUD_BEGIN):]))
    return out


@pytest.mark.parametrize("name,text", _terminal_sheets(), ids=[n for n, _ in _terminal_sheets()])
def test_every_generated_glyph_has_an_empty_alternative(name, text):
    bad = _glyphs_without_alt(text)
    assert not bad, f"{name}: decorative content with no alt text: {bad}"


def test_the_alt_scan_would_catch_a_bare_glyph():
    assert _glyphs_without_alt('.a::before { content: "\\25B8"; }')
    assert not _glyphs_without_alt('.a::before { content: "\\25B8"; content: "\\25B8" / ""; }')
    assert not _glyphs_without_alt('.a::before { content: ""; }')
    assert not _glyphs_without_alt('td::before { content: attr(data-label) ": "; }')


def test_what_to_do_keeps_its_words_for_a_screen_reader():
    css = _read(CC_CSS / "components.css")
    assert 'content: "> what to do: " / "what to do: "' in css


def test_the_transfer_direction_is_a_word_behind_an_arrow():
    text = _read(CC_T / "partials" / "transfers.html")
    arrows = [ln for ln in text.splitlines() if "⇡" in ln or "⇣" in ln]
    # the one place the arrows are drawn is the macro, hidden, beside a word
    assert len(arrows) == 1 and "macro dirmark" in arrows[0], arrows
    assert 'aria-hidden="true"' in arrows[0] and 'class="vh"' in arrows[0]
    assert text.count("dirmark(") >= 5


def test_the_decorative_checkbox_glyph_is_not_part_of_the_name():
    css = _read(CC_CSS / "components.css")
    for sel in (".check .g::before", ".radio .g::before",
                ".radio input:checked + .g::before"):
        rule = css[css.index(sel):].split("}", 1)[0]
        assert '/ ""' in rule, sel


# ------------------------------------------------------------ a11y-copy-2

def test_the_confirm_dialog_is_described_by_its_question():
    shell = _read(CC_T / "shell.html")
    dlg = re.search(r'<dialog id="cc-confirm"[^>]*>', shell).group(0)
    described = re.search(r'aria-describedby="([^"]+)"', dlg)
    assert described, dlg
    q = re.search(r'<p[^>]*\bid="%s"[^>]*>' % re.escape(described.group(1)), shell)
    assert q and "data-cc-confirm-q" in q.group(0)


def test_the_site_settings_ask_is_described_by_its_question():
    html = _read(CC_T / "admin_settings.html")
    dlg = re.search(r'<dialog id="site-ask"[^>]*>', html).group(0)
    assert 'aria-describedby="site-ask-q"' in dlg
    assert '<p id="site-ask-q">' in html


@pytest.mark.parametrize("app", SPA_APPS)
def test_the_spa_confirm_has_a_name_and_says_its_question(app):
    js = _read(REPO / app / "web" / "static" / "cc_spa.js")
    box = js[js.index("function confirmBox("):]
    box = box[:box.index("\n  }\n")]
    assert "dialog.setAttribute('aria-label'" in box
    assert "dialog.setAttribute('aria-describedby', 'cc-spa-confirm-q')" in box
    assert "q.id = 'cc-spa-confirm-q'" in box


# ------------------------------------------------------------ a11y-copy-3

@pytest.mark.parametrize("app", SPA_APPS)
def test_spa_tips_keep_the_description_and_follow_focus(app):
    js = _read(REPO / app / "web" / "static" / "cc_spa.js")
    show = js[js.index("function showTip(el)"):]
    show = show[:show.index("\n  }\n")]
    moved = show.index("removeAttribute('title')")
    assert "setAttribute('aria-description'" in show[:moved], \
        "the title must become the accessible description before it is removed"
    assert re.search(r"addEventListener\('focusin', function \(e\) \{[^}]*showTip\(el\)", js, re.S)
    assert "addEventListener('focusout'" in js


# ------------------------------------------------------------ a11y-copy-4

def test_dashboard_tips_reach_keys_tabs_and_fields():
    js = _read(CC_JS)
    sel = re.search(r"var TIP_SELECTOR = ((?:\"[^\"]*\"\s*\+?\s*)+);", js).group(1)
    sel = "".join(re.findall(r'"([^"]*)"', sel))
    for piece in ("button[title]", "a[title]", "[role=tab][title]", "label[title]",
                  "select[title]", "input[title]"):
        assert piece in sel, piece


def test_a_touch_screen_gets_a_question_mark_that_opens_the_hint_sheet():
    js = _read(CC_JS)
    adopt = js[js.index("function adoptTips(root)"):]
    adopt = adopt[:adopt.index("\n  }\n")]
    assert "tipButton(el)" in adopt
    tb = js[js.index("function tipButton(el)"):]
    tb = tb[:tb.index("\n  }\n")]
    assert "finePointer()" in tb, "only a coarse pointer gets one"
    assert '"tip-btn"' in tb and '"data-tip-for"' in tb and "aria-label" in tb
    assert "window.ccsyncOpenHint = function" in js
    hint = js[js.index("window.ccsyncOpenHint = function"):]
    hint = hint[:hint.index("\n  };\n")]
    for hook in ('"chip-sheet"', '".chip-sheet-label"', '".chip-sheet-text"', "hidden = false"):
        assert hook in hint, hook
    # the sheet the "?" opens exists in the terminal shell
    assert 'id="chip-sheet"' in _read(CC_T / "partials" / "hint_sheet.html")
    # no regular-expression literal after a bracket: the mounted-prefix scan
    assert "(/" not in tb


# ------------------------------------------------------------ a11y-copy-5

def test_no_page_title_prompt_reaches_a_screen_reader():
    bad = []
    for path in _cc_templates():
        for m in re.finditer(r'<span class="prompt"[^>]*>', _read(path)):
            if 'aria-hidden="true"' not in m.group(0):
                bad.append(path.name)
    assert not bad, bad


_H2_T = re.compile(r'<h2 class="t"[^>]*>(.*?)</h2>', re.S)


def test_no_window_title_is_named_with_underscores():
    bad = []
    for path in _cc_templates():
        for m in _H2_T.finditer(_read(path)):
            inner = m.group(1)
            # an underscore drawn aria-hidden (with a hidden space) is fine
            spoken = re.sub(r'<span aria-hidden="true">[^<]*</span>', "", inner)
            literal = re.sub(r"\{\{.*?\}\}|\{%.*?%\}|<[^>]+>", "", spoken)
            if "_" in literal:
                bad.append(f"{path.name}: {inner}")
            for expr in re.findall(r"\{\{(.*?)\}\}", inner):
                e = expr.strip()
                # a bare `title` / `name` is a snake_case window id; a data
                # value (a computer's own name) is shown as it is
                if e in ("title", "name") or re.fullmatch(r'"[a-z_]+"', e):
                    bad.append(f"{path.name}: {{{{ {e} }}}} with no cc_title")
    assert not bad, bad


def test_cc_title_draws_a_space_for_a_screen_reader():
    from ccsync_dashboard.ui_home import tree_label
    out = str(tree_label("this_dashboard"))
    assert out == 'this<span aria-hidden="true">_</span><span class="vh"> </span>dashboard'


def test_help_headings_lose_their_hashes_for_a_screen_reader():
    css = _read(CC_CSS / "components.css")
    assert 'content: "## " / ""' in css and 'content: "### " / ""' in css


# ------------------------------------------------------------ a11y-copy-6

_FOLD = re.compile(r'<button class="fold"[^>]*>.*?</button>', re.S)


def test_every_fold_names_its_window():
    bad = []
    for path in _cc_templates():
        for m in _FOLD.finditer(_read(path)):
            btn = m.group(0)
            if "aria-labelledby=" in btn or "aria-label=" in btn:
                continue
            vh = re.search(r'<span class="vh">([^<]*)</span>', btn)
            if not vh or vh.group(1).strip() == "fold":
                bad.append(f"{path.name}: {btn[:120]}")
    assert not bad, bad


_REPEATED = {
    "partials/admin_users.html": ("export data", "erase history", "revoke", "set", "delete",
                                  "approve", "dismiss", "remove", "save"),
    "partials/admin_suspend_button.html": (),
    "partials/home_problems.html": ("dismiss",),
    "partials/health_notices.html": ("dismiss",),
}


@pytest.mark.parametrize("rel", sorted(_REPEATED))
def test_a_repeated_key_names_what_it_acts_on(rel):
    text = _read(CC_T / rel)
    bad = []
    for label in _REPEATED[rel]:
        for m in re.finditer(r'<span class="t">%s</span>' % re.escape(label), text):
            if not text[m.end():].startswith('<span class="vh">'):
                bad.append(f"{label} at {text.count(chr(10), 0, m.start()) + 1}")
    # the computed labels too: enable/disable, suspend/resume, add/update key,
    # and a problem's link
    for m in re.finditer(r'<span class="t">\{%[^<]*%\}</span>|<span class="t">\{\{[^<]*href_label[^<]*\}\}</span>', text):
        if not text[m.end():].startswith('<span class="vh">'):
            bad.append(f"{m.group(0)[:60]} at {text.count(chr(10), 0, m.start()) + 1}")
    assert not bad, bad


# ------------------------------------------------------------ a11y-copy-7

def _rules(text: str):
    """(media or None, selectors, last font-size px or None, index)."""
    text = _strip_css_comments(text)
    out, stack, buf, i = [], [], "", 0
    while i < len(text):
        ch = text[i]
        if ch == "{":
            head, buf = buf.strip(), ""
            if head.startswith("@"):
                stack.append(head)
                i += 1
                continue
            j = text.index("}", i)
            sizes = re.findall(r"font-size:\s*([0-9.]+)px", text[i + 1:j])
            out.append((stack[-1] if stack else None,
                        [s.strip() for s in head.split(",") if s.strip()],
                        float(sizes[-1]) if sizes else None, len(out)))
            i = j + 1
            continue
        if ch == "}":
            if stack:
                stack.pop()
            buf = ""
        else:
            buf += ch
        i += 1
    return out


def _phone(media) -> bool:
    m = media and re.search(r"max-width:\s*(\d+)px", media)
    return bool(m) and int(m.group(1)) >= 390 and "min-width" not in media


# The sheets the shell links BEFORE phone.css; every other sheet is a page
# sheet linked after it, so phone.css's floor list cannot reach its rules.
_BEFORE_PHONE = {"hud.css", "terminal.css", "components.css"}


def test_no_sheet_undercuts_the_12px_phone_floor():
    floor = {s for m, sels, size, _ in _rules(_read(CC_CSS / "phone.css"))
             if _phone(m) and size is not None and size >= 12 for s in sels}
    bad = []
    for path in sorted(CC_CSS.glob("*.css")):
        if path.name == "phone.css":
            continue
        rs = _rules(_read(path))
        for media, sels, size, idx in rs:
            if media is not None or size is None or size >= 12:
                continue
            for sel in sels:
                own = any(_phone(m2) and s2 is not None and s2 >= 12 and sel in sl2 and i2 > idx
                          for m2, sl2, s2, i2 in rs)
                if not own and not (path.name in _BEFORE_PHONE and sel in floor):
                    bad.append(f"{path.name}: {sel} at {size}px")
    assert not bad, bad


# ------------------------------------------------------------ a11y-copy-8

def test_a_confirm_names_a_key_in_sentence_case_not_capitals():
    labels = set()
    for path in _cc_templates():
        labels |= {m.strip().lower() for m in re.findall(r'<span class="t">([^<{]+)</span>', _read(path))}
    bad = []
    for path in _cc_templates():
        for q in re.findall(r'hx-confirm="([^"]*)"', _read(path)):
            for word in re.findall(r"\b[A-Z]{2,}(?: [A-Z]{2,})*\b", q):
                if word.lower() in labels:
                    bad.append(f"{path.name}: {word} in {q[:80]!r}")
    assert not bad, bad


def test_packages_quotes_check_now_and_names_the_window_in_words():
    text = _read(CC_T / "partials" / "admin_packages.html")
    visible = re.sub(r"\{#.*?#\}", "", text, flags=re.S)
    visible = re.sub(r"<[^>]+>", " ", visible)
    assert "Press check now" not in visible
    assert "from_the_vendor window" not in visible
    assert 'Press "Check now"' in visible


# ------------------------------------------------------------ a11y-copy-9

def _set_block_strings(text: str) -> list[str]:
    out = []
    for block in re.findall(r"\{%-?\s*set\b.*?%\}", text, re.S):
        out += [s for s in re.findall(r'"((?:[^"\\]|\\.)*)"', block) if " " in s]
    return out


def test_no_retired_word_in_the_json_help_maps():
    bad = []
    for path in _cc_templates():
        for s in _set_block_strings(_read(path)):
            words = _retired_words_in(s)
            if words:
                bad.append(f"{path.name}: {words} in {s[:70]!r}")
    assert not bad, bad


def test_the_help_map_scan_sees_a_set_block():
    assert _set_block_strings('{% set H = {"k": "the same machine as this"} %}') == \
        ["the same machine as this"]


# ------------------------------------------------------------ a11y-copy-10

NOW = "2026-09-25T12:00:00+00:00"


def test_for_words_never_says_since_never():
    assert alerts._for_words(None, NOW) is None
    assert alerts._for_words("", NOW) is None
    assert alerts._for_words("2026-09-25T11:52:00+00:00", NOW) == "for 8 minutes"
    assert alerts._for_words("2026-09-25T11:59:30+00:00", NOW) == "for 1 minute"
    assert alerts._for_words("2026-09-25T09:00:00+00:00", NOW) == "for 3 hours"
    assert alerts._for_words("2026-09-20T12:00:00+00:00", NOW) == "for 5 days"


def _feed_text(feed):
    ctx = SimpleNamespace(feed=feed, now=NOW)
    found = alerts._check_feed_stale(ctx)
    assert len(found) == 1
    f = found[0]
    return " ".join(str(v) for v in (f.values() if isinstance(f, dict) else vars(f).values()))


def test_the_feed_alert_on_a_fresh_site_says_never_checked():
    text = _feed_text({})
    assert "since never" not in text
    assert "has never been able to check for new CC Sync builds" in text


def test_the_feed_alert_with_a_stamp_says_for_how_long():
    text = _feed_text({"last_checked_at": "2026-09-10T12:00:00+00:00"})
    assert "has not been able to check for new CC Sync builds for 15 days" in text
    assert "since 15 days ago" not in text


def test_the_weekly_builds_line_never_says_since_never(tmp_path, monkeypatch):
    from ccsync_dashboard import api
    from ccsync_dashboard import db as dbmod
    editors = [
        {"editor_username": "ed", "machine": "PC-A", "platform": "windows",
         "companion_version": "0.9.53", "companion_outdated": True,
         "current_companion_version": "0.9.80"},
        {"editor_username": "ed", "machine": "PC-B", "platform": "windows",
         "companion_version": "0.9.49", "companion_outdated": True,
         "companion_version_since": "2026-09-22T12:00:00+00:00",
         "current_companion_version": "0.9.80"},
    ]
    monkeypatch.setattr(api, "build_editors_view", lambda conn, now: {"editors": editors})
    monkeypatch.setattr(alerts, "scan", lambda *a, **k: [])
    conn = dbmod.connect(str(tmp_path / "w.db"))
    dbmod.migrate(conn)
    try:
        _subject, text = alerts.compose_weekly(conn, NOW)
    finally:
        conn.close()
    assert "since never" not in text
    assert "ed/PC-A is on 0.9.53 (since when is not known); current" in text
    assert "ed/PC-B has been on 0.9.49 for 3 days; current" in text


# ------------------------------------------------------------ a11y-copy-11

def test_no_studio_show_name_is_an_example_path():
    bad = [p.name for p in _cc_templates() if re.search(r"\bFF\d\b|Elections|Pangolin", _read(p))]
    assert not bad, bad
