"""The theme rules two visual fixes depend on (2026-08-18).

Neither is the kind of thing a functional test would ever notice, and both
were reported from a screenshot rather than a traceback, so they are pinned
here as CSS facts:

  1. The header wraps by WHOLE ITEMS. It used to be a nowrap flex row whose
     items could shrink, so an admin nav wider than the window broke inside
     the labels: "[ TRANSFERS" on one line and "]" on the next, with the "//"
     separators floating loose. The classic fix was flex-wrap + `flex: 0 0
     auto` + `white-space: nowrap` on every child, and the staleness stamp
     and session chip joined into one `.topbar-right` item.

  2. Text fields, textareas and selects are painted by the theme. Until then
     only three places asked, so most of /admin/settings rendered as UA
     chrome: a white box with black text in the middle of a black terminal.

Converted 2026-09-25, when the CC Terminal look replaced the classic one and
style.css went with it. The same two facts are pinned on the sheets every page
now loads: the HUD (static/cc/hud.css, whose hud-common block the three SPA
sheets carry byte for byte) for the header, and static/cc/terminal.css +
components.css for the fields. The HUD does not wrap at all: it keeps every
label whole with nowrap, lets only the brand name and the stamp give way, and
narrows by MOVING entries into the "more" sheet and the phone dock. Deleted
with the classic sheet (nothing in the terminal carries them): the `.nav-sep`
"//" pseudo-element, the "no module links in the bar" rule (the HUD's bar has
a nav again, on purpose), and `.side-head` (the classic section header; a
terminal window's bar is its header).

A restyle is allowed to change these numbers; what it must not do is drop the
properties, which is what these tests check.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CC = ROOT / "static" / "cc"
# terminal.css holds the tokens, the base and theme-common; components.css
# the field paint. Read together, as a page loads them.
TERMINAL_CSS = (CC / "terminal.css").read_text(encoding="utf-8")
CSS = TERMINAL_CSS + "\n" + (CC / "components.css").read_text(encoding="utf-8")
HUD_CSS = (CC / "hud.css").read_text(encoding="utf-8")
TOPBAR = (ROOT / "templates" / "partials" / "topbar.html").read_text(encoding="utf-8")

# The families the base form-control rules must cover. Anything a settings
# page or a wizard step is likely to use.
TEXTUAL_INPUTS = ("text", "password", "url", "email", "search", "number")

# The terminal's one base field rule: every input that is not a drawn control.
FIELD = 'input:not([type="checkbox"]):not([type="radio"]):not([type="range"])'


def _strip_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def rule(css: str, selector: str) -> str:
    """Every declaration this stylesheet makes for `selector`, concatenated.

    Selector lists are split, so `.inp:focus` is found inside a three-selector
    focus rule as readily as in a rule of its own; and all matching rules are
    joined because a control is often given its paint in one rule and its
    geometry in another. These are regression pins, not a cascade model: the
    question is whether the property is still declared. Only top-level rules
    (and rules one @media deep) are seen, which is all these tests ask about.
    """
    found = []
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", _strip_comments(css)):
        parts = [p.strip() for p in m.group(1).split(",")]
        if selector in parts:
            found.append(m.group(2))
    if not found:
        raise AssertionError(f"no rule for selector {selector!r}")
    return " ".join(found)


def _media_block(css: str, query: str) -> str:
    """The body of the first `@media <query>` block, braces balanced."""
    css = _strip_comments(css)
    start = css.index("{", css.index(f"@media {query}")) + 1
    depth, i = 1, start
    while depth:
        depth += {"{": 1, "}": -1}.get(css[i], 0)
        i += 1
    return css[start:i - 1]


# ------------------------------------------------------------ 1. the header


def test_topbar_row_wraps_by_whole_items():
    """The HUD is one flex row that never breaks a label: the nav and the meta
    row are nowrap, and the nav never shrinks."""
    body = rule(HUD_CSS, ".hud")
    assert "display: flex" in body
    assert "flex: none" in rule(HUD_CSS, ".hud-nav")
    assert "white-space: nowrap" in rule(HUD_CSS, ".hud-meta")


def test_every_topbar_child_is_an_unbreakable_unit():
    """The actual fix for "[ TRANSFERS" / "]", in HUD terms: a nav entry is
    nowrap, and every item of the meta row is `flex: none` (the stamp alone
    may shrink, with an ellipsis, never break)."""
    assert "white-space: nowrap" in rule(HUD_CSS, ".hud-nav a")
    assert "flex: none" in rule(HUD_CSS, ".hud-meta > *")
    stamp = rule(HUD_CSS, ".hud-meta > .hud-stamp")
    assert "overflow: hidden" in stamp


def test_the_stamp_and_the_session_chip_are_one_item():
    """"updated 4s ago" and the user + menu keys must not be split across a
    wrap, so they are one flex child (.hud-meta), pushed right as a unit by
    the spacer (the classic .topbar-right's margin-left: auto)."""
    meta = TOPBAR[TOPBAR.index('<div class="hud-meta">'):TOPBAR.index('<div class="hud-menu"')]
    assert 'id="topbar-stamp"' in meta and 'class="hud-user' in meta
    assert "flex: 1 1 0" in rule(HUD_CSS, ".hud-spacer")
    assert "justify-content: flex-end" in rule(HUD_CSS, ".hud-meta")


def test_the_phone_layer_does_not_undo_the_wrap_safe_topbar():
    """Extended 2026-08-30 with the phone layer (MOBILE_PLAN.md M1). The tests
    above read every rule for a selector wherever it is, so a `white-space:
    normal` added inside the phone query would leave them passing and put a
    broken label back at 390px -- the exact bug they exist for, on the screen
    it is most likely to happen on. The phone layout narrows the bar by
    MOVING items into the dock and the "more" sheet, never by letting a label
    break."""
    for query in ("(max-width: 600px)", "(min-width: 601px) and (max-width: 900px)"):
        layer = _media_block(HUD_CSS, query)
        for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", layer):
            if re.search(r"\.hud(-nav|-meta|-brand)?\b(?![-\w])", m.group(1)):
                assert "flex-wrap: wrap" not in m.group(2), (query, m.group(1))
                assert "white-space: normal" not in m.group(2), (query, m.group(1))
                assert "flex-shrink" not in m.group(2), (query, m.group(1))
    phone = _media_block(HUD_CSS, "(max-width: 600px)")
    assert ".hud-nav" in phone and "display: none" in phone
    assert ".hud-dock" in phone


def test_the_brand_stays_on_one_line():
    """The brand is site data of any length: it stays one line and gives way
    by ellipsis, never by wrapping."""
    assert 'class="hud-brand"' in TOPBAR
    assert "white-space: nowrap" in rule(HUD_CSS, ".hud-brand")
    assert "text-overflow: ellipsis" in rule(HUD_CSS, ".hud-name")


# ----------------------------------------------------- 2. the form controls


def test_every_text_field_family_is_themed():
    """The terminal paints EVERY input that is not a drawn control in one
    rule, so no textual type can be missed (the classic sheet listed six).
    The native spinner / picker / drop-down list is the half a page cannot
    paint; without color-scheme it renders white against our text colour."""
    body = rule(CSS, FIELD)
    assert "background-color: var(--win-solid)" in body
    assert "color: var(--text)" in body
    assert "color-scheme: dark" in body
    # ...and the one rule excludes exactly the three drawn controls, so every
    # textual family in TEXTUAL_INPUTS falls under it.
    for kind in TEXTUAL_INPUTS:
        assert f'[type="{kind}"]' not in FIELD
    # The field class adds the border every textual field carries.
    assert "border: 1px solid var(--line)" in rule(CSS, ".inp")


def test_textareas_and_selects_share_the_same_paint():
    for selector in ("textarea", "select"):
        body = rule(CSS, selector)
        assert "background-color: var(--win-solid)" in body
        assert "color-scheme: dark" in body
    for selector in (".area", ".sel"):
        assert "border: 1px solid var(--line)" in rule(CSS, selector)


def test_focus_is_a_slim_ring_that_moves_nothing():
    """Border colour and a glow only: no outline and no border width change,
    so focusing a field moves nothing (the terminal's ring is the cyan hi)."""
    body = rule(CSS, ".inp:focus")
    assert "outline: none" in body
    assert "border-color: var(--hi)" in body
    assert "box-shadow:" in body
    assert "border-width" not in body and "padding" not in body


def test_placeholder_disabled_and_option_states_exist():
    assert "var(--muted)" in rule(CSS, ".inp::placeholder")
    assert "opacity" in rule(CSS, ".inp:disabled")
    assert "background: var(--win-solid)" in rule(CSS, "select option")


def test_checkboxes_and_radios_keep_their_own_treatment():
    """The base block must never swallow the drawn controls: they are drawn,
    not merely coloured (2026-08-17). The field rule excludes them, and the
    terminal draws its own glyph over a hidden native input."""
    assert ':not([type="checkbox"])' in FIELD and ':not([type="radio"])' in FIELD
    assert "opacity: 0" in rule(CSS, ".check input")
    assert "opacity: 0" in rule(CSS, ".radio input")


# Adapters, so the fleet-wide section below reads the same in all four suites
# (this one's rule() takes the stylesheet as its first argument; the three SPA
# copies close over theirs).
_CSS_TEXT = TERMINAL_CSS
_REPO_ROOT = ROOT.parent


def _rule(selector: str) -> str:
    return rule(TERMINAL_CSS, selector)


# ---------------------------------------------- 3. scrollbars and sliders
#
# Added 2026-08-18 with the theme-common block. The owner's screenshot of the
# music filter rail showed a stock light-grey Chromium scrollbar running down
# the middle of a black terminal, and the four FEEL sliders wearing a stock
# grey track: two surfaces the theme had simply never claimed. Both are pinned
# here because neither has any functional signal at all -- nothing 500s when a
# scrollbar goes grey again.

SCROLL_PIECES = (
    "::-webkit-scrollbar",
    "::-webkit-scrollbar-track",
    "::-webkit-scrollbar-thumb",
    "::-webkit-scrollbar-thumb:hover",
    "::-webkit-scrollbar-corner",
)


def test_the_scroll_tokens_are_defined_with_the_fleet_values():
    """One token per stylesheet, the same value in all four. --scroll-track is
    the near-black red the bar runs in; the thumb is the phosphor red the rest
    of the theme is drawn in, brightening on hover."""
    body = _rule(":root")
    assert "--scroll-track: #1a0508" in body
    assert "--scroll-thumb: var(--red)" in body
    assert "--scroll-thumb-hover: var(--red-hot)" in body


def test_html_and_body_state_the_standard_scrollbar_pair():
    """scrollbar-color/-width is what Firefox and Chromium 121+ read; the
    -webkit- pseudo-elements below are what every Edge in the field reads.
    Both, because the fleet is not on one browser."""
    for selector in ("html", "body"):
        body = _rule(selector)
        assert "scrollbar-color: var(--scroll-thumb) var(--scroll-track)" in body
        assert "scrollbar-width: thin" in body


def test_every_scrolling_container_inherits_the_pair():
    """The rails, panels and grids that scroll are not enumerated anywhere:
    the universal rule is what stops a container added later from shipping a
    grey bar (the music rail is exactly how this was found)."""
    body = _rule("*")
    assert "scrollbar-color: var(--scroll-thumb) var(--scroll-track)" in body
    assert "scrollbar-width: thin" in body


@pytest.mark.parametrize("piece", SCROLL_PIECES)
def test_each_webkit_scrollbar_piece_is_painted(piece):
    body = _rule(piece)
    assert "var(--scroll-track)" in body or "var(--scroll-thumb" in body, piece


def test_the_bar_is_thin_square_and_has_no_arrow_buttons():
    bar = _rule("::-webkit-scrollbar")
    assert "width: 10px" in bar and "height: 10px" in bar
    # Square corners are a house rule, and a scrollbar is not exempt.
    assert "border-radius: 0" in _rule("::-webkit-scrollbar-thumb")
    assert "border-radius: 0" in _rule("::-webkit-scrollbar-track")
    assert "display: none" in _rule("::-webkit-scrollbar-button")


def test_the_thumb_is_the_phosphor_red_and_brightens_on_hover():
    assert "background: var(--scroll-thumb)" in _rule("::-webkit-scrollbar-thumb")
    assert "background: var(--scroll-thumb-hover)" in _rule(
        "::-webkit-scrollbar-thumb:hover")


def test_range_inputs_get_a_dark_track_and_a_red_thumb():
    """accent-color alone leaves the TRACK stock grey in Chromium, which is
    what the FEEL sliders looked like. The vendor pseudo-elements are the only
    way to paint track and thumb separately."""
    base = _rule('input[type="range"]')
    assert "accent-color: var(--red)" in base
    assert "appearance: none" in base
    for track in ('input[type="range"]::-webkit-slider-runnable-track',
                  'input[type="range"]::-moz-range-track'):
        body = _rule(track)
        assert "background: var(--scroll-track)" in body
        assert "border: 1px solid var(--red-dim)" in body
    for thumb in ('input[type="range"]::-webkit-slider-thumb',
                  'input[type="range"]::-moz-range-thumb'):
        body = _rule(thumb)
        assert "background: var(--red)" in body
        assert "border-radius: 0" in body


def test_the_two_vendor_slider_families_are_never_in_one_selector_list():
    """An unknown pseudo-element invalidates the WHOLE selector list it appears
    in, so `::-webkit-slider-thumb, ::-moz-range-thumb { ... }` styles nothing
    in either browser. This is the mistake that looks correct in a diff."""
    for m in re.finditer(r"([^{}]+)\{[^{}]*\}", _strip_comments(_CSS_TEXT)):
        sel = m.group(1)
        assert not ("-webkit-slider" in sel and "-moz-range" in sel), sel


def test_selection_and_the_focus_ring_are_not_left_to_the_browser():
    """The stock selection is a blue slab and the stock focus ring is a
    white/black double line: both are the UA picking a colour on a page that
    has one."""
    sel = _rule("::selection")
    assert "background: var(--red)" in sel
    assert "outline: 1px solid var(--red)" in _rule(":focus-visible")


def test_the_root_declares_the_uas_dark_mode():
    """color-scheme on :root is what darkens the parts no rule can reach -- an
    overlay scrollbar mid-fade, a native drop-down list."""
    assert "color-scheme: dark" in _rule(":root")


# ------------------------------------- 4. the theme-common block cannot drift

THEME_COMMON_BEGIN = "/* ==== theme-common BEGIN"
THEME_COMMON_END = "theme-common END"

FLEET_STYLESHEETS = {
    # The dashboard's copy lives in the terminal sheet since style.css was
    # retired with the classic look (2026-09-25).
    "dashboard": _REPO_ROOT / "dashboard" / "static" / "cc" / "terminal.css",
    "broll": _REPO_ROOT / "broll" / "web" / "static" / "style.css",
    "music": _REPO_ROOT / "music" / "web" / "static" / "style.css",
    "ytdl": _REPO_ROOT / "ytdl" / "web" / "static" / "style.css",
}


def _theme_common(path):
    """The block between the two markers, newline-normalised.

    Newlines are normalised rather than compared raw because .css is not in
    .gitattributes' eol=lf list, so whether a checkout is LF or CRLF is a
    property of the machine (core.autocrlf=true on the base rig), not of the
    content. The contract is about the content: all four apps must paint the
    same scrollbar.
    """
    raw = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    assert raw.count(THEME_COMMON_BEGIN) == 1, (
        f"{path} must carry the theme-common block exactly once")
    body = raw.split(THEME_COMMON_BEGIN, 1)[1]
    assert THEME_COMMON_END in body, f"{path} has an unterminated theme-common block"
    return body.split(THEME_COMMON_END, 1)[0]


def test_all_four_stylesheets_carry_the_theme_common_block():
    for name, path in FLEET_STYLESHEETS.items():
        assert path.exists(), f"{name}: {path} is missing"
        assert _theme_common(path).strip(), f"{name}: theme-common block is empty"


def test_the_theme_common_block_is_identical_in_all_four_stylesheets():
    """Four static trees, one login, one origin, no build step and no shared
    import: the only thing keeping the scrollbar in /music the same as the one
    in /transfers is that these bytes are the same bytes. Fix a failure by
    copying the block, not by editing one side to agree.
    """
    blocks = {name: _theme_common(path)
              for name, path in FLEET_STYLESHEETS.items()}
    reference = blocks["dashboard"]
    drifted = [name for name, body in blocks.items() if body != reference]
    assert not drifted, (
        "theme-common has drifted from dashboard/static/cc/terminal.css in: "
        + ", ".join(sorted(drifted)))
