"""The phone contract, pinned (2026-08-30, docs/MOBILE_PLAN.md M1).

Six packages build the mobile port in parallel against ONE set of names: the
tokens in `:root`, three media queries and a class vocabulary (`.scroll-x`,
`.stack`, `.tap`, `.sheet`, `.phone-hide`, `.phone-only`, `.rule`). This
package defines all of them, so a rename here is a rename in five other
branches at once, and nothing else in the suite would notice: no page 500s
when `.stack` quietly becomes `.stacked`, it just stops working on a phone.

The same goes for the lines `base.html` carries on behalf of the PWA package
(the manifest, the theme colour, the two Apple metas, the touch icon,
`pwa.js` BEFORE htmx, `mobile.css` after `style.css`, `viewport-fit=cover`)
and for the install slot in the drawer foot: they are a contract between two
branches that never touch the same file, and the only place the contract can
be enforced is here.

What this file does NOT pin is how anything looks. It is deliberately a set
of "the name still exists and it is still declared in the right query" tests,
because the whole point of the layer is that a later restyle changes the
numbers and keeps the vocabulary.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / "static" / "style.css").read_text(encoding="utf-8")
BASE = (ROOT / "templates" / "base.html").read_text(encoding="utf-8")
TOPBAR = (ROOT / "templates" / "partials" / "topbar.html").read_text(encoding="utf-8")
SIDEBAR = (ROOT / "templates" / "partials" / "sidebar.html").read_text(encoding="utf-8")
SETTINGS_NAV = (ROOT / "templates" / "partials" / "settings_nav.html").read_text(
    encoding="utf-8")
LOGIN = (ROOT / "templates" / "login.html").read_text(encoding="utf-8")

# The three queries, exactly as MOBILE_PLAN.md 3.1 spells them. The phone one
# is a literal because @media cannot read a custom property; --bp-phone exists
# for the rules, and the two must not drift apart (pinned below).
PHONE_QUERY = "@media (max-width: 600px)"
TOUCH_QUERY = "@media (pointer: coarse)"
APP_QUERY = "@media (display-mode: standalone)"

PHONE_LAYER_BEGIN = "/* ==== the phone layer"
THEME_COMMON_BEGIN = "/* ==== theme-common BEGIN"


def _strip_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _block(css: str, opening: str) -> str:
    """The text of the {...} that follows `opening`, brace-balanced.

    Written for media queries, whose bodies hold nested rules that a
    non-greedy regex cannot survive.
    """
    css = _strip_comments(css)
    start = css.index(opening) + len(opening)
    start = css.index("{", start)
    depth = 0
    for i in range(start, len(css)):
        if css[i] == "{":
            depth += 1
        elif css[i] == "}":
            depth -= 1
            if depth == 0:
                return css[start + 1:i]
    raise AssertionError(f"unterminated block after {opening!r}")


PHONE_BLOCK = _block(CSS, PHONE_QUERY)
TOUCH_BLOCK = _block(CSS, TOUCH_QUERY)
APP_BLOCK = _block(CSS, APP_QUERY)


# ------------------------------------------------------------- 1. the tokens

TOKENS = {
    "--bp-phone": "600px",
    "--bp-tablet": "900px",
    "--tap": "44px",
    "--safe-t": "env(safe-area-inset-top, 0px)",
    "--safe-b": "env(safe-area-inset-bottom, 0px)",
    "--safe-l": "env(safe-area-inset-left, 0px)",
    "--safe-r": "env(safe-area-inset-right, 0px)",
}


@pytest.mark.parametrize("name,value", sorted(TOKENS.items()))
def test_the_mobile_tokens_are_declared_with_their_contract_values(name, value):
    """MOBILE_PLAN.md 3.1. Five other packages write var(--tap) into their own
    rules; if the token is not declared the rule is simply ignored and the
    control is 12px tall with nothing to show for it."""
    assert f"{name}: {value};" in CSS


def test_the_breakpoint_token_and_the_query_agree():
    """A media query cannot read a custom property, so the number is written
    out in the query AND declared as a token for the rules. They are two
    copies of one decision: this is the test that they are the same copy."""
    assert "--bp-phone: 600px" in CSS
    assert PHONE_QUERY in CSS


# ------------------------------------------------------------ 2. the queries


@pytest.mark.parametrize("query", [PHONE_QUERY, TOUCH_QUERY, APP_QUERY])
def test_each_of_the_three_queries_exists_exactly_once(query):
    """One block per query, so there is one place to read what a phone, a
    touch screen or the installed app does differently. The 900px query the
    stylesheet always had is not one of them and is untouched."""
    assert _strip_comments(CSS).count(query) == 1, query


def test_the_old_narrow_window_query_survives():
    assert "@media (max-width: 900px)" in CSS


def test_no_hover_query_decides_behaviour():
    """MOBILE_PLAN.md 3.1: (hover: none) may hide a hover-only affordance and
    nothing else. A touch laptop reports both, so anything gated on it is
    wrong on the machine an editor actually uses."""
    assert "(hover: none)" not in _strip_comments(CSS)


def test_the_phone_layer_sits_before_the_theme_common_block():
    """theme-common is compared byte for byte against the b-roll, music and
    ytdl stylesheets (test_theme_css.py). A phone rule inside it would have to
    be copied into all three, and fails four suites until it is."""
    assert CSS.index(PHONE_LAYER_BEGIN) < CSS.index(THEME_COMMON_BEGIN)
    assert THEME_COMMON_BEGIN not in CSS[:CSS.index(PHONE_LAYER_BEGIN)]


def test_the_theme_common_block_carries_no_phone_rules():
    common = CSS[CSS.index(THEME_COMMON_BEGIN):]
    for query in (PHONE_QUERY, TOUCH_QUERY, APP_QUERY):
        assert query not in common


# --------------------------------------------------------- 3. the vocabulary


def test_scroll_x_scrolls_inside_itself_and_hints_that_it_does():
    """Never the page: a phone that scrolls sideways has lost the layout, and
    the hint edge is there because a phone paints no scrollbar until you drag
    one."""
    body = _strip_comments(CSS)
    rule = body[body.index(".scroll-x {"):]
    rule = rule[:rule.index("}")]
    assert "overflow-x: auto" in rule
    assert "-webkit-overflow-scrolling: touch" in rule
    assert "border-right: 1px solid var(--red-dim)" in rule


def test_stack_turns_a_table_into_labelled_rows_below_the_phone_breakpoint():
    """MOBILE_PLAN.md 3.2, and the shape M2 and M3 write their data-labels
    for: every tr a block, every td a labelled line, the header gone. A cell
    with no data-label renders bare, which is how a row of actions stays
    readable."""
    assert "table.stack thead { display: none; }" in PHONE_BLOCK
    assert "table.stack td { display: block" in PHONE_BLOCK
    assert "table.stack td[data-label]" in PHONE_BLOCK
    assert "content: attr(data-label)" in PHONE_BLOCK
    assert "font-size: 11px" in PHONE_BLOCK


def test_an_empty_data_label_asks_for_no_heading_at_all():
    """The action cell (M2, 2026-08-30): a td that carries data-label="" opts
    out of the heading, instead of getting an empty 11px line above its
    button. A cell with no attribute renders bare too; the empty value is for
    a table whose cells are generated and cannot simply omit it."""
    assert 'table.stack td[data-label]:not([data-label=""])::before' in PHONE_BLOCK


def test_a_control_in_a_stacked_cell_is_a_full_width_row():
    """The other half of a real target inside a stacked table: min-height
    comes from the coarse-pointer block, the width from here."""
    assert "table.stack td > .tap" in PHONE_BLOCK
    assert "table.stack td > .btn" in PHONE_BLOCK


def test_phone_only_and_phone_hide_are_a_pair():
    assert ".phone-only { display: none; }" in CSS
    assert ".phone-hide { display: none !important; }" in PHONE_BLOCK
    assert ".phone-only { display: revert; }" in PHONE_BLOCK


def test_the_tap_class_and_the_two_controls_grow_on_a_coarse_pointer_only():
    """The 44px hit box is decided by POINTER, not by width: that is what
    leaves a 1280px mouse window pixel-identical, and what gives a touch
    laptop the big targets a narrow desktop window must not get."""
    assert "min-height: var(--tap)" in TOUCH_BLOCK
    assert "min-width: var(--tap)" in TOUCH_BLOCK
    for selector in (".btn", "a.chip", ".tap"):
        assert selector in TOUCH_BLOCK, selector
    # ...and nowhere in the phone query, which would make the size a function
    # of the window instead of the pointer.
    assert "min-width: var(--tap)" not in PHONE_BLOCK


def test_the_project_tick_is_a_44px_target_on_a_coarse_pointer():
    """The M0 sweep's worst target in the product, 13.3 x 13.3px on every
    signed-in page, and it starts a real sync on someone's computer. The input
    itself is 44px (a label around a 16px box measures 16px, which is what a
    finger gets too); the painted box stays 1em, drawn by a ::before centred
    in the hit box."""
    assert "input[type=\"checkbox\"].proj-check" in TOUCH_BLOCK
    assert "width: var(--tap)" in TOUCH_BLOCK
    assert ".proj-check::before" in TOUCH_BLOCK
    # The row has to grow with it or two 44px boxes 30px apart overlap and the
    # tap lands on the wrong project.
    assert ".project-link { min-height: var(--tap)" in TOUCH_BLOCK


def test_no_text_under_12px_on_a_phone():
    """MOBILE_PLAN.md goal 1. The chips were the only thing in the product
    below the floor (11px); the desktop keeps 11."""
    assert ".chip { font-size: 12px; }" in PHONE_BLOCK
    assert ".chip { font-size: 12px; }" not in _strip_comments(
        CSS[:CSS.index(PHONE_LAYER_BEGIN)])


def test_the_sheet_is_the_popover_api_and_no_script():
    """The projects rail on a phone. Script-free is not a preference: the
    partial is the innerHTML of an <aside> htmx replaces every 30s."""
    assert 'id="projects-sheet" popover' in SIDEBAR
    assert 'popovertarget="projects-sheet"' in SIDEBAR
    assert "<script" not in SIDEBAR
    assert ".projects.sheet:popover-open" in PHONE_BLOCK
    assert "max-height: 60vh" in PHONE_BLOCK
    # The desktop escape hatch: an author display beats the UA's
    # [popover]:not(:popover-open) rule, so the rail stays a block above the
    # breakpoint -- and it has to be declared BEFORE the phone query, because
    # the query hands the state back with `display: revert` at the same
    # specificity and the later declaration would win.
    body = _strip_comments(CSS)
    hatch = body[body.index(".projects.sheet {"):]
    hatch = hatch[:hatch.index("}")]
    assert "display: block" in hatch
    # The UA also makes a popover a fixed, bordered, canvas-coloured card;
    # every part of that is undone here or the rail paints as a white box over
    # the corner of the desktop.
    for undone in ("position: static", "border: none", "background: none"):
        assert undone in hatch, undone
    assert body.index(".projects.sheet {") < body.index(PHONE_QUERY)


def test_the_sheet_handle_is_a_tap_target_above_the_gesture_bar():
    assert "sheet-handle" in SIDEBAR
    assert "height: calc(var(--tap) + var(--safe-b))" in PHONE_BLOCK


def test_the_rule_is_a_border_with_no_text_in_it():
    """It used to be 120 box-drawing characters: a thousand pixels of text
    laid out on every page of the product to paint one line."""
    assert '<div class="rule"></div>' in BASE
    assert '"─"' not in BASE
    body = _strip_comments(CSS)
    rule = body[body.index(".rule {"):]
    rule = rule[:rule.index("}")]
    assert "height: 0" in rule
    assert "border-top: 1px solid var(--red-dim)" in rule


# --------------------------------------- 4. the lines base.html owes the PWA

CONTRACT_LINES = (
    '<link rel="manifest" href="/manifest.webmanifest">',
    '<meta name="theme-color" content="#0a0a0d">',
    '<meta name="apple-mobile-web-app-capable" content="yes">',
    '<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">',
    '<link rel="apple-touch-icon" href="/static/icons/icon-180.png">',
    '<script src="/static/pwa.js" defer></script>',
    '<link rel="stylesheet" href="/static/mobile.css">',
)


@pytest.mark.parametrize("line", CONTRACT_LINES)
def test_base_html_carries_the_pwa_contract_line(line):
    """MOBILE_PLAN.md 3.3, exact text. The PWA package makes the targets
    exist; these lines are how a browser finds them, and neither branch can
    test the pair on its own."""
    assert line in BASE


def test_the_viewport_covers_the_display_cutout():
    assert ('<meta name="viewport" content="width=device-width, initial-scale=1, '
            'viewport-fit=cover">') in BASE


def test_pwa_js_is_ordered_before_htmx():
    """Both are deferred, and deferred scripts run in document order: pwa.js
    has to rewrite the poll intervals on a coarse pointer while htmx has not
    yet processed the nodes."""
    assert BASE.index("/static/pwa.js") < BASE.index("/static/htmx.min.js")


def test_mobile_css_is_linked_after_style_css():
    assert BASE.index("/static/style.css") < BASE.index("/static/mobile.css")


def test_the_install_slot_is_empty_and_in_the_drawer_foot():
    """pwa.js fills it with an [ INSTALL ] chip when Chrome offers one. Empty
    here, and phone-only, so a desktop never shows a control that cannot do
    anything."""
    assert '<span id="install-slot" class="phone-only"></span>' in TOPBAR
    foot = TOPBAR[TOPBAR.index('class="drawer-foot"'):]
    assert 'id="install-slot"' in foot


# ------------------------------------------------------- 5. polling on a phone


def test_every_poll_in_this_packages_templates_is_filtered_by_visibility():
    """MOBILE_PLAN.md 3.4: a phone in a pocket must not hold a connection
    against --workers 1. Only base.html polls among the files this package
    owns; the sidebar's 30s poll lives on the <aside> in fourteen PAGE
    templates, which belong to M2 and M3 (recorded in the handover)."""
    for path in (ROOT / "templates" / "base.html",
                 ROOT / "templates" / "partials" / "topbar.html",
                 ROOT / "templates" / "partials" / "sidebar.html",
                 ROOT / "templates" / "partials" / "settings_nav.html",
                 ROOT / "templates" / "login.html"):
        text = re.sub(r"\{#.*?#\}", "", path.read_text(encoding="utf-8"), flags=re.S)
        for trigger in re.findall(r'hx-trigger="([^"]*)"', text):
            if "every" not in trigger:
                continue
            assert "[document.visibilityState === 'visible']" in trigger, (
                f"{path.name}: unfiltered poll {trigger!r}")


def test_the_fleet_halt_banner_still_loads_immediately():
    """The filter must not cost the load trigger: the banner says the whole
    company has stopped syncing, and waiting 60s for it is not an option."""
    assert ("hx-trigger=\"load, every 60s [document.visibilityState === 'visible']\""
            in BASE)


# ------------------------------------------------ 6. the rest of the chrome


def test_the_settings_strip_is_a_scroll_x_row_that_snaps_to_the_current_page():
    """Twelve entries wrapped onto four rows is half a phone screen of
    navigation. One row, and the entry you are standing on is the ONLY snap
    target in the container, which is what scrolls it into view with no JS."""
    # The class is given by selector, not by markup: test_settings_hub.py
    # (another package's file) pins class="settings-nav" exactly.
    assert 'class="settings-nav"' in SETTINGS_NAV
    assert "scroll-snap-type: x mandatory" in PHONE_BLOCK
    assert "overflow-x: auto" in PHONE_BLOCK
    assert (".settings-nav-item.settings-nav-current { scroll-snap-align: center; }"
            in PHONE_BLOCK)
    # Exactly one snap target, or the container has a choice and makes the
    # wrong one.
    assert PHONE_BLOCK.count("scroll-snap-align") == 1


def test_the_topbar_chips_have_a_phone_copy_in_the_drawer():
    """At 390px the bar is one 44px row. The chips are duplicated rather than
    moved because the partial is injected into three SPAs with innerHTML and
    must stay script-free: only CSS can choose which copy a screen sees."""
    assert 'class="chip red phone-hide"' in TOPBAR
    assert 'class="drawer-chips phone-only"' in TOPBAR
    drawer = TOPBAR[TOPBAR.index('id="nav-drawer"'):]
    assert "drawer-chips" in drawer


def test_the_login_fields_do_not_zoom_or_capitalise_on_a_phone():
    """16px is the threshold below which Android and iOS zoom the page into a
    focused field and do not come back out; autocapitalize is why "jsmith"
    used to arrive as "Jsmith"."""
    assert 'autocapitalize="none"' in LOGIN
    assert ".login-box input { font-size: 16px; }" in PHONE_BLOCK
    assert "width: min(380px, 100% - 2rem)" in PHONE_BLOCK


def test_the_installed_app_pays_the_status_bar_inset():
    assert "var(--safe-t)" in APP_BLOCK
