"""The theme rules two visual fixes depend on (2026-08-18).

Both were reported from a screenshot rather than a traceback, and neither is
the kind of thing a functional test would notice, so they are pinned as CSS
facts. This is the b-roll copy of dashboard/tests/test_theme_css.py --
duplicated rather than shared because these are separate suites with separate
interpreters and no common package (the same reason the no-em-dash scan is
duplicated).

  1. The topbar wraps by WHOLE ITEMS. The header this page shows is fetched
     from the dashboard's /partials/topbar and injected into #dash-topbar, so
     it is painted by THIS stylesheet: the dashboard's fix alone would leave
     this page still breaking "[ TRANSFERS ]" into "[ TRANSFERS" and "]".

  2. Text fields, textareas and selects are painted by the theme from the
     ELEMENT, not from a per-control class, so a search box or a settings
     field looks the same in every app of the fleet.

A restyle may change these numbers; what it must not do is drop the
properties.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

CSS = (Path(__file__).resolve().parents[1] / "static" / "style.css").read_text(
    encoding="utf-8")

TEXTUAL_INPUTS = ("text", "password", "url", "email", "search", "number")


def _strip_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def rule(selector: str) -> str:
    """Every declaration this stylesheet makes for `selector`, concatenated.

    Selector lists are split, so `input[type="text"]:focus` is found inside
    the thirteen-selector focus rule as readily as in a rule of its own; and
    all matching rules are joined because a control is often given its paint
    in one rule and its geometry in another. These are regression pins, not a
    cascade model: the question is whether the property is still declared.
    """
    found = []
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", _strip_comments(CSS)):
        parts = [p.strip() for p in m.group(1).split(",")]
        if selector in parts:
            found.append(m.group(2))
    if not found:
        raise AssertionError(f"no rule for selector {selector!r} in style.css")
    return " ".join(found)


# ------------------------------------------------------------ 1. the topbar


def test_topbar_row_wraps_by_whole_items():
    body = rule(".topbar")
    assert "flex-wrap: wrap" in body
    assert "display: flex" in body


def test_every_topbar_child_is_an_unbreakable_unit():
    body = rule(".topbar > *")
    assert "white-space: nowrap" in body
    assert "flex: 0 0 auto" in body


def test_nav_separators_are_pseudo_elements_not_text_nodes():
    # The escape, not the two characters: a quote followed by a slash is what
    # a root-relative URL looks like, and every shipped asset is scanned for
    # one (YTDL-42).
    assert 'content: "\\2f\\2f"' in rule(".nav-link.nav-sep::before")


def test_the_stamp_and_the_session_chip_are_one_item():
    body = rule(".topbar-right")
    assert "margin-left: auto" in body
    assert "margin-left: auto" not in rule(".stamp")


# ----------------------------------------------------- 2. the form controls


@pytest.mark.parametrize("kind", TEXTUAL_INPUTS)
def test_every_text_field_family_is_themed(kind):
    body = rule(f'input[type="{kind}"]')
    assert "background: var(--field)" in body
    assert "border: 1px solid var(--red-dim)" in body
    assert "color: var(--text)" in body
    # The native spinner / picker / drop-down list is the half a page cannot
    # paint; without this it renders white against our text colour.
    assert "color-scheme: dark" in body


def test_textareas_and_selects_share_the_same_paint():
    for selector in ("textarea", "select"):
        body = rule(selector)
        assert "background: var(--field)" in body
        assert "border: 1px solid var(--red-dim)" in body
        assert "color-scheme: dark" in body


def test_focus_is_a_slim_red_ring_that_moves_nothing():
    body = rule('input[type="text"]:focus')
    assert "outline: none" in body
    assert "border-color: var(--red)" in body
    assert "box-shadow: 0 0 0 1px var(--red)" in body


def test_placeholder_disabled_and_option_states_exist():
    assert "var(--red)" in rule("::placeholder")
    assert "opacity" in rule("input:disabled")
    assert "background: var(--panel)" in rule("select option")


# Adapters, so the fleet-wide section below reads the same in all four suites
# (the dashboard's rule() takes the stylesheet as its first argument).
_CSS_TEXT = CSS
_REPO_ROOT = Path(__file__).resolve().parents[3]
_rule = rule


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

# Every navigation surface in the b-roll UI, and the rule each one must state
# to belong to the same theme as the dashboard's .side-head (2026-08-18).
NAV_SURFACES = (
    ".folder-tree-head",        # the browse rail's heading
    ".segments-col-heading",    # the detail view's column headings
    "#settings-panel h3",
    "#ingest-panel h3",         # the ingest panel's steps
)


@pytest.mark.parametrize("selector", NAV_SURFACES)
def test_every_section_heading_uses_the_red_dim_hairline(selector):
    """red-dim, not the grey --border used for row separators: a section
    heading is structure. The rail's own heading had no rule at all."""
    assert "border-bottom: 1px dotted var(--red-dim)" in _rule(selector)


def test_the_browse_rail_is_a_panel_with_its_own_scroller():
    body = _rule(".folder-tree")
    assert "background: var(--panel)" in body
    assert "border-right: 1px solid var(--red-dim)" in body
    assert "overflow-y: auto" in body


def test_the_batch_scope_tabs_are_a_bracketed_strip_not_browser_buttons():
    """"Mine" / "All machines" on the ingest panel share .mode-toggles with the
    header's search-mode strip: one border round the group, red labels, and the
    fleet's current-selection idiom (field fill + a 2px red inset) on the
    active tab."""
    strip = _rule(".mode-toggles")
    assert "border: 1px solid var(--red-dim)" in strip
    tab = _rule(".mode-btn")
    assert "color: var(--red)" in tab
    assert "background: none" in tab
    assert "box-shadow: inset 2px 0 0 var(--red)" in _rule(".mode-btn.active")

# ---------------------------------------------------- 3. the left nav drawer
# The 2026-08-18 nav redesign: the module links left the bar for a drawer the
# HTML popover API opens with no JavaScript at all. This page injects that
# markup from /partials/topbar with innerHTML, so THIS stylesheet paints it --
# the same duplication rule as the topbar half above.


def test_the_menu_bars_are_drawn_not_typed():
    """Three vertical bars from a gradient, not a "|||" glyph: a glyph is at
    the mercy of whichever monospace face the machine happens to have."""
    assert "repeating-linear-gradient" in rule(".menu-bars")
    assert 'content: "["' in rule(".menu-btn::before")
    assert 'content: "]"' in rule(".menu-btn::after")


def test_the_drawer_base_rule_declares_no_display():
    """The one thing a restyle must not break. An author `display` in the base
    rule beats the UA's `[popover]:not(:popover-open) { display: none }`, and
    the drawer would then be stuck open with no way to dismiss it."""
    assert "display:" not in rule(".nav-drawer")
    assert "display: flex" in rule(".nav-drawer:popover-open")


def test_the_drawer_is_a_left_panel_over_a_dimmed_backdrop():
    body = rule(".nav-drawer")
    assert "position: fixed" in body
    assert "background: var(--panel)" in body
    # ::backdrop is the dim. Without it the drawer floats over a page that
    # still looks live and clickable.
    assert "background" in rule(".nav-drawer::backdrop")


def test_the_drawers_current_entry_uses_the_house_idiom():
    """Field fill plus a 2px red accent, the same "you are here" the sidebar
    and the settings strip use."""
    body = rule(".drawer-item.drawer-current")
    assert "background: var(--field)" in body
    assert "var(--red)" in body


def test_the_settings_gear_is_red():
    """The SVG paints with currentColor, so the link's colour is the icon's."""
    assert "color: var(--red)" in rule(".gear-link")
