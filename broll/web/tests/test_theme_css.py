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
