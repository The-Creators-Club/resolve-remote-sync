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
