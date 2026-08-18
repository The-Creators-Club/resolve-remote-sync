"""The theme rules two visual fixes depend on (2026-08-18).

Neither is the kind of thing a functional test would ever notice, and both
were reported from a screenshot rather than a traceback, so they are pinned
here as CSS facts:

  1. The topbar wraps by WHOLE ITEMS. It used to be a nowrap flex row whose
     items could shrink, so an admin nav wider than the window broke inside
     the labels: "[ TRANSFERS" on one line and "]" on the next, with the "//"
     separators floating loose. The fix is flex-wrap + `flex: 0 0 auto` +
     `white-space: nowrap` on every child, the separators moved out of the
     markup into `.nav-sep::before`, and the staleness stamp and session chip
     joined into one `.topbar-right` item.

  2. Text fields, textareas and selects are painted by the theme. Until now
     only three places asked, so most of /admin/settings rendered as UA
     chrome: a white box with black text in the middle of a black terminal.

A restyle is allowed to change these numbers; what it must not do is drop the
properties, which is what these tests check. The topbar half is duplicated in
the b-roll, music and ytdl suites, because the header those pages inject from
/partials/topbar is painted by THEIR stylesheet, not this one.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / "static" / "style.css").read_text(encoding="utf-8")
TOPBAR = (ROOT / "templates" / "partials" / "topbar.html").read_text(encoding="utf-8")

# The families the base form-control rules must cover. Anything a settings
# page or a wizard step is likely to use.
TEXTUAL_INPUTS = ("text", "password", "url", "email", "search", "number")


def _strip_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def rule(css: str, selector: str) -> str:
    """Every declaration this stylesheet makes for `selector`, concatenated.

    Selector lists are split, so `input[type="text"]:focus` is found inside
    the thirteen-selector focus rule as readily as in a rule of its own; and
    all matching rules are joined because a control is often given its paint
    in one rule and its geometry in another. These are regression pins, not a
    cascade model: the question is whether the property is still declared.
    """
    found = []
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", _strip_comments(css)):
        parts = [p.strip() for p in m.group(1).split(",")]
        if selector in parts:
            found.append(m.group(2))
    if not found:
        raise AssertionError(f"no rule for selector {selector!r} in style.css")
    return " ".join(found)


# ------------------------------------------------------------ 1. the topbar


def test_topbar_row_wraps_by_whole_items():
    body = rule(CSS, ".topbar")
    assert "flex-wrap: wrap" in body
    assert "display: flex" in body


def test_every_topbar_child_is_an_unbreakable_unit():
    """The actual fix for "[ TRANSFERS" / "]". nowrap stops the label
    breaking; `flex: 0 0 auto` stops the item being squeezed narrower than
    its label in the first place."""
    body = rule(CSS, ".topbar > *")
    assert "white-space: nowrap" in body
    assert "flex: 0 0 auto" in body


def test_nav_separators_are_pseudo_elements_not_text_nodes():
    """A `<span class="dim">//</span>` between two links is a flex item of its
    own and a wrap can strand it at the end or the start of a row. As a
    ::before of the item it precedes it travels with that item.

    The bar itself has carried no separated nav entries since the 2026-08-18
    redesign moved the modules into the drawer, so the markup half of this
    test is now "the bar has no bracketed links to separate" (below). The
    rule stays: it is the vocabulary an inline nav entry gets if one ever
    comes back, and the three SPA stylesheets pin it too.
    """
    # The escape, not the two characters: a quote followed by a slash is what
    # a root-relative URL looks like, and every shipped asset is scanned for
    # one (YTDL-42).
    assert 'content: "\\2f\\2f"' in rule(CSS, ".nav-link.nav-sep::before")


def test_the_bar_itself_carries_no_module_links():
    """The redesign in one assertion: between the brand and the right-hand
    chip the bar holds nothing that could wrap at all. Everything that used to
    live there -- Transfers, Users, Assignments, Setup, Settings, the three
    modules, the installer -- is in the drawer or under Settings."""
    # Comments first: this template explains the redesign in prose and names
    # the very labels the assertions below say are gone from the bar.
    markup = re.sub(r"\{#.*?#\}", "", TOPBAR, flags=re.S)
    # Then the drawer element itself, whole: what is left is the bar.
    bar = re.sub(r'<div class="nav-drawer".*?\n</div>\n', "", markup, flags=re.S)
    bar = bar[bar.index('class="brand"'):bar.index('class="topbar-right"')]
    assert "nav-drawer" not in bar, "the drawer element was not stripped"
    assert "nav-link" not in bar
    for gone in ("[ TRANSFERS ]", "[ USERS ]", "[ SETTINGS ]", "[ B-ROLL ]",
                 "[ MUSIC ]", "[ YOUTUBE ]", "[ INSTALLER ]"):
        assert gone not in bar


def test_the_stamp_and_the_session_chip_are_one_item():
    """"updated 4s ago" and the user + logout buttons must not be split
    across a wrap, so they are one flex child carrying the margin-left:auto
    that used to sit on .stamp."""
    assert 'class="topbar-right"' in TOPBAR
    body = rule(CSS, ".topbar-right")
    assert "margin-left: auto" in body
    assert "margin-left: auto" not in rule(CSS, ".stamp")


def test_the_brand_stays_on_one_line():
    """.brand is a direct child of .topbar, so the nowrap above binds it."""
    assert 'class="brand"' in TOPBAR
    assert "white-space: nowrap" in rule(CSS, ".topbar > *")


# ----------------------------------------------------- 2. the form controls


@pytest.mark.parametrize("kind", TEXTUAL_INPUTS)
def test_every_text_field_family_is_themed(kind):
    body = rule(CSS, f'input[type="{kind}"]')
    assert "background: var(--field)" in body
    assert "border: 1px solid var(--red-dim)" in body
    assert "color: var(--text)" in body
    # The native spinner / picker / drop-down list is the half a page cannot
    # paint; without this it renders white against our text colour.
    assert "color-scheme: dark" in body


def test_textareas_and_selects_share_the_same_paint():
    for selector in ("textarea", "select"):
        body = rule(CSS, selector)
        assert "background: var(--field)" in body
        assert "border: 1px solid var(--red-dim)" in body
        assert "color-scheme: dark" in body


def test_focus_is_a_slim_red_ring_that_moves_nothing():
    body = rule(CSS, 'input[type="text"]:focus')
    assert "outline: none" in body
    assert "border-color: var(--red)" in body
    assert "box-shadow: 0 0 0 1px var(--red)" in body


def test_placeholder_disabled_and_option_states_exist():
    assert "var(--red)" in rule(CSS, "::placeholder")
    assert "opacity" in rule(CSS, "input:disabled")
    assert "background: var(--panel)" in rule(CSS, "select option")


def test_checkboxes_and_radios_keep_their_own_treatment():
    """The base block must never swallow the appearance:none controls: they
    are drawn, not merely coloured (2026-08-17)."""
    for selector in ('input[type="checkbox"]', 'input[type="radio"]'):
        assert "appearance: none" in rule(CSS, selector)


# Adapters, so the fleet-wide section below reads the same in all four suites
# (this one's rule() takes the stylesheet as its first argument; the three SPA
# copies close over theirs).
_CSS_TEXT = CSS
_REPO_ROOT = ROOT.parent


def _rule(selector: str) -> str:
    return rule(CSS, selector)


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
    "dashboard": _REPO_ROOT / "dashboard" / "static" / "style.css",
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
        "theme-common has drifted from dashboard/static/style.css in: "
        + ", ".join(sorted(drifted)))


# --------------------------------------------- 5. this app's nav surfaces


def test_the_section_header_carries_the_hairline_rule():
    """`.side-head` is THE section header of the fleet UI: 41 uses, from the
    sidebar's [ PROJECTS ] to every block of /admin/settings and every step of
    the setup wizard. It had the red and the [ ... ] brackets but no rule under
    it, so the same heading read as a heading in b-roll and as a loose red line
    here (owner, 2026-08-18)."""
    body = _rule(".side-head")
    assert "color: var(--red)" in body
    assert "border-bottom: 1px dotted var(--red-dim)" in body


def test_a_section_header_that_is_a_link_still_reads_as_one():
    assert "color: var(--red)" in _rule(".side-head a")
    assert "color: var(--red-hot)" in _rule(".side-head a:hover")
