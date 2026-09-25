"""The phone contract, pinned (2026-08-30, docs/MOBILE_PLAN.md M1; moved onto
the terminal look 2026-09-25 when the classic look was deleted).

Every page's phone behaviour hangs off ONE set of names: the tokens in the
terminal `:root`, a small set of media queries and a class vocabulary
(`.scroll-x`, `.tbl.stack-sm` with `data-label`, `.phone-only`, the 44px
`--tap` target). A rename here is a rename in every page template at once,
and nothing else in the suite would notice: no page 500s when `stack-sm`
quietly becomes `stacked`, it just stops working on a phone.

The same goes for the lines `shell.html` carries on behalf of the PWA (the
manifest, the theme colour, the two Apple metas, the touch icon, `pwa.js`
BEFORE htmx, `viewport-fit=cover`) and for the install slot in the HUD's
"more" sheet: pwa.js and the shell never touch the same file, and the only
place the contract can be enforced is here.

What this file does NOT pin is how anything looks. It is deliberately a set
of "the name still exists and it is still declared in the right query" tests,
because the whole point of the layer is that a restyle changes the numbers
and keeps the vocabulary.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CC = ROOT / "static" / "cc"
TERMINAL = (CC / "terminal.css").read_text(encoding="utf-8")
COMPONENTS = (CC / "components.css").read_text(encoding="utf-8")
PHONE = (CC / "phone.css").read_text(encoding="utf-8")
HUD = (CC / "hud.css").read_text(encoding="utf-8")
SHEETS = {p.name: p.read_text(encoding="utf-8") for p in sorted(CC.glob("*.css"))}
ALL_CSS = "\n".join(SHEETS.values())
SHELL = (ROOT / "templates" / "shell.html").read_text(encoding="utf-8")
TOPBAR = (ROOT / "templates" / "partials" / "topbar.html").read_text(encoding="utf-8")
SETTINGS_NAV = (ROOT / "templates" / "partials" / "settings_nav.html").read_text(
    encoding="utf-8")
LOGIN = (ROOT / "templates" / "login.html").read_text(encoding="utf-8")

# The terminal's two widths: the page body stacks at 760 (the bench's number),
# the HUD dock appears at 600 (hud-common's, shared byte for byte with the
# three SPAs). The 1100 query is the desktop-narrow one and is not a phone.
PAGE_QUERY = "@media (max-width: 760px)"
DOCK_QUERY = "@media (max-width: 600px)"
TOUCH_QUERY = "@media (pointer: coarse)"
APP_QUERY = "@media (display-mode: standalone)"


def _strip_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _blocks(css: str, opening: str) -> list[str]:
    """The text of every {...} that follows `opening`, brace-balanced.

    Written for media queries, whose bodies hold nested rules that a
    non-greedy regex cannot survive.
    """
    css = _strip_comments(css)
    out: list[str] = []
    pos = 0
    while True:
        at = css.find(opening, pos)
        if at < 0:
            return out
        start = css.index("{", at + len(opening))
        depth = 0
        for i in range(start, len(css)):
            if css[i] == "{":
                depth += 1
            elif css[i] == "}":
                depth -= 1
                if depth == 0:
                    out.append(css[start + 1:i])
                    pos = i
                    break
        else:
            raise AssertionError(f"unterminated block after {opening!r}")


PHONE_BLOCK = "\n".join(_blocks(PHONE, PAGE_QUERY))
TOUCH_BLOCK = "\n".join(_blocks(PHONE, TOUCH_QUERY))
HUD_DOCK_BLOCK = "\n".join(_blocks(HUD, DOCK_QUERY))
HUD_TOUCH_BLOCK = "\n".join(_blocks(HUD, TOUCH_QUERY))
APP_BLOCK = "\n".join(_blocks(HUD, APP_QUERY))


# ------------------------------------------------------------- 1. the tokens

TOKENS = {
    "--tap": "44px",
    "--safe-t": "env(safe-area-inset-top, 0px)",
    "--safe-b": "env(safe-area-inset-bottom, 0px)",
    "--safe-l": "env(safe-area-inset-left, 0px)",
    "--safe-r": "env(safe-area-inset-right, 0px)",
}


@pytest.mark.parametrize("name,value", sorted(TOKENS.items()))
def test_the_mobile_tokens_are_declared_with_their_contract_values(name, value):
    """MOBILE_PLAN.md 3.1. Page rules write var(--tap) into their own
    declarations; if the token is not declared the rule is simply ignored and
    the control is 12px tall with nothing to show for it."""
    root = TERMINAL[TERMINAL.index(":root"):]
    root = root[:root.index("}")]
    assert f"{name}: {value};" in root


# ------------------------------------------------------------ 2. the queries


def test_every_phone_rule_for_the_pages_lives_in_phone_css():
    """One sheet to read for what a phone does differently to the page body:
    phone.css. It carries the page query (the second copy is the 16px field
    rule, which must be LAST and is pinned in test_cc_css_facts) and the one
    coarse-pointer block for the page controls."""
    assert _strip_comments(PHONE).count(PAGE_QUERY) == 2
    assert _strip_comments(PHONE).count(TOUCH_QUERY) == 1


def test_the_dock_query_is_hud_commons_600():
    """The dock appears at 600px and below, and everything that makes room
    for it (the --cc-dock-h lift) uses the same number."""
    assert ".hud-dock" in HUD_DOCK_BLOCK
    assert "--cc-dock-h" in "\n".join(
        b for b in _blocks(HUD, DOCK_QUERY) if "html:has(.hud-dock)" in b)


def test_no_hover_query_decides_behaviour():
    """MOBILE_PLAN.md 3.1: (hover: none) may REVEAL a hover-only affordance
    and nothing else. A touch laptop reports both, so anything gated on it is
    wrong on the machine an editor actually uses."""
    for name, css in SHEETS.items():
        for block in _blocks(css, "@media (hover: none)"):
            for decl in re.findall(r"\{([^}]*)\}", block):
                props = {d.split(":")[0].strip() for d in decl.split(";") if ":" in d}
                assert props <= {"display"}, (name, decl)


# --------------------------------------------------------- 3. the vocabulary


def test_scroll_x_scrolls_inside_itself():
    """Never the page: a phone that scrolls sideways has lost the layout."""
    body = _strip_comments(COMPONENTS)
    rule = body[body.index(".scroll-x {"):]
    rule = rule[:rule.index("}")]
    assert "overflow-x: auto" in rule


def test_stack_turns_a_table_into_labelled_rows_below_the_phone_breakpoint():
    """MOBILE_PLAN.md 3.2, and the shape every page writes its data-labels
    for: the header gone, every cell a labelled line. A cell with no
    data-label renders bare, which is how a row of actions stays readable."""
    assert ".tbl.stack-sm thead { display: none; }" in PHONE_BLOCK
    assert ".tbl.stack-sm td[data-label]::before" in PHONE_BLOCK
    assert "content: attr(data-label)" in PHONE_BLOCK
    # 12px, not 11: a heading that has become the only name a value carries
    # cannot be the smallest text on the page.
    labels = re.findall(r"\.tbl\.stack-sm td\[data-label\]::before\s*\{([^}]*)\}",
                        PHONE_BLOCK)
    assert labels
    for decl in labels:
        if "font-size" in decl:
            assert "font-size: 12px" in decl, decl


def test_an_empty_data_label_asks_for_no_heading_at_all():
    """The action cell (M2, 2026-08-30): a td that carries data-label="" opts
    out of the heading instead of getting an empty line above its button."""
    assert '.tbl.stack-sm td[data-label=""]::before { display: none; }' in PHONE_BLOCK


def test_a_stacked_cell_wraps_and_its_actions_sit_left():
    """The other half of a readable stacked row: nothing nowrap survives the
    stack, and the action cell's buttons do not float at the far edge."""
    assert ".tbl.stack-sm td { white-space: normal; }" in PHONE_BLOCK
    assert ".tbl.stack-sm td.acts-cell" in PHONE_BLOCK


def test_phone_only_is_hidden_on_a_desktop_and_shown_on_a_phone():
    assert ".phone-only { display: none; }" in _strip_comments(COMPONENTS)
    assert ".phone-only { display: flex; }" in PHONE_BLOCK


def test_the_page_controls_grow_on_a_coarse_pointer_only():
    """The 44px hit box is decided by POINTER, not by width: that is what
    leaves a 1280px mouse window pixel-identical, and what gives a touch
    laptop the big targets a narrow desktop window must not get."""
    assert "min-height: var(--tap)" in TOUCH_BLOCK
    for selector in (".key", ".check", ".radio", ".switch", ".inp", ".sel",
                     ".tree .row", ".fold"):
        assert selector in TOUCH_BLOCK, selector
    # ...and nowhere in the phone query, which would make the size a function
    # of the window instead of the pointer.
    assert "var(--tap)" not in PHONE_BLOCK


def test_every_hud_control_is_a_44px_target_on_a_coarse_pointer():
    for selector in (".hud-nav a", ".hud-key", ".hud-mi", ".hud-dock a",
                     ".hud-dock button", ".snav a"):
        assert selector in HUD_TOUCH_BLOCK, selector
    assert "min-height: var(--cc-tap)" in HUD_TOUCH_BLOCK


def test_no_text_under_12px_on_a_phone():
    """MOBILE_PLAN.md goal 1. The desktop keeps its 10-11px labels; the phone
    layer lifts the ones the sweep found (the key hints, table heads, stamps)
    and never states anything smaller again."""
    for selector in (".tbl th", ".key.sm", ".hint", ".kv dt", ".sec-h"):
        assert selector in PHONE_BLOCK, selector
    for small in re.findall(r"font-size:\s*([0-9.]+)px", PHONE_BLOCK):
        assert float(small) >= 12, small


# --------------------------------------- 4. the lines shell.html owes the PWA

CONTRACT_LINES = (
    '<link rel="manifest" href="/manifest.webmanifest">',
    '<meta name="theme-color" content="#070403">',
    '<meta name="apple-mobile-web-app-capable" content="yes">',
    '<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">',
    "<link rel=\"apple-touch-icon\" href=\"{{ asset_url('icons/icon-180.png') }}\">",
    "<script src=\"{{ asset_url('pwa.js') }}\" defer></script>",
    "<link rel=\"stylesheet\" href=\"{{ asset_url('cc/phone.css') }}\">",
)


@pytest.mark.parametrize("line", CONTRACT_LINES)
def test_shell_html_carries_the_pwa_contract_line(line):
    """MOBILE_PLAN.md 3.3, exact text. pwa.js makes the targets exist; these
    lines are how a browser finds them."""
    assert line in SHELL


def test_the_theme_colour_is_the_terminal_background():
    """The phone's status bar is painted with it; a different value draws a
    band of another colour above every page."""
    assert "--bg: #070403" in TERMINAL


def test_the_viewport_covers_the_display_cutout():
    assert ('<meta name="viewport" content="width=device-width, initial-scale=1, '
            'viewport-fit=cover">') in SHELL


def test_pwa_js_is_ordered_before_htmx():
    """Both are deferred, and deferred scripts run in document order: pwa.js
    has to rewrite the poll intervals on a coarse pointer while htmx has not
    yet processed the nodes."""
    assert SHELL.index("asset_url('pwa.js')") < SHELL.index("asset_url('htmx.min.js')")


def test_phone_css_is_linked_after_the_sheets_it_overrides():
    """phone.css wins by order at equal specificity; linked first it loses
    every rule it states."""
    at = SHELL.index("asset_url('cc/phone.css')")
    for sheet in ("cc/hud.css", "cc/terminal.css", "cc/components.css"):
        assert SHELL.index(f"asset_url('{sheet}')") < at, sheet


def test_the_install_slot_is_empty_and_in_the_more_sheet():
    """pwa.js fills it with an INSTALL key when Chrome offers one. Empty
    here, and inside the "more" sheet that only the phone dock and the
    tablet bar open, so a desktop never shows a control that cannot do
    anything."""
    assert '<span id="install-slot"></span>' in TOPBAR
    sheet = TOPBAR[TOPBAR.index('id="hud-more"'):]
    assert 'id="install-slot"' in sheet


# ------------------------------------------------------- 5. polling on a phone


def test_every_poll_in_the_chrome_is_filtered_by_visibility():
    """MOBILE_PLAN.md 3.4: a phone in a pocket must not hold a connection
    against --workers 1. The page templates are pinned by
    test_mobile_fleet.py; these are the files on every page."""
    for path in (ROOT / "templates" / "shell.html",
                 ROOT / "templates" / "partials" / "topbar.html",
                 ROOT / "templates" / "partials" / "settings_nav.html",
                 ROOT / "templates" / "login.html"):
        text = re.sub(r"\{#.*?#\}", "", path.read_text(encoding="utf-8"), flags=re.S)
        for trigger in re.findall(r'hx-trigger="([^"]*)"', text):
            if "every" not in trigger:
                continue
            assert "[document.visibilityState === 'visible']" in trigger, (
                f"{path.name}: unfiltered poll {trigger!r}")


def test_the_fleet_halt_line_still_loads_immediately():
    """The filter must not cost the load trigger: the line says the whole
    company has stopped syncing, and waiting 60s for it is not an option."""
    assert ("hx-trigger=\"load, every 60s [document.visibilityState === 'visible']\""
            in SHELL)
    assert 'hx-get="/partials/halt-line"' in SHELL


# ------------------------------------------------ 6. the rest of the chrome


def test_the_settings_strip_is_a_scroll_x_row_that_snaps_to_the_current_page():
    """Twelve entries wrapped onto four rows is half a phone screen of
    navigation. One row, and the entry you are standing on is the ONLY snap
    target in the strip, which is what scrolls it into view with no JS."""
    assert 'class="snav scroll-x"' in SETTINGS_NAV
    assert ".snav.scroll-x { flex-wrap: nowrap; overflow-x: auto;" in HUD_DOCK_BLOCK
    assert "scroll-snap-type: x" in HUD_DOCK_BLOCK
    assert ('.snav.scroll-x a[aria-current="page"] { scroll-snap-align: center; }'
            in HUD_DOCK_BLOCK)
    assert HUD_DOCK_BLOCK.count("scroll-snap-align") == 1


def test_the_phone_bar_hides_the_desktop_nav_and_shows_the_dock():
    """At 390px the bar is one row: the nav and the desktop-only keys go, the
    dock carries the destinations, and the "more" sheet the rest."""
    assert ".hud-nav, .hud .hud-hide-sm { display: none; }" in HUD_DOCK_BLOCK
    assert '<nav class="hud-dock"' in TOPBAR
    dock = TOPBAR[TOPBAR.index('<nav class="hud-dock"'):]
    dock = dock[:dock.index("</nav>")]
    assert 'popovertarget="hud-more"' in dock


def test_the_login_fields_do_not_zoom_or_capitalise_on_a_phone():
    """16px is the threshold below which Android and iOS zoom the page into a
    focused field and do not come back out; autocapitalize is why "jsmith"
    used to arrive as "Jsmith"."""
    assert 'autocapitalize="none"' in LOGIN
    last = _blocks(PHONE, PAGE_QUERY)[-1]
    assert "input:not([type=checkbox], [type=radio], [type=range])" in last
    assert "font-size: 16px" in last
    # ...and the selector's root hook is on the shell, or it matches nothing.
    assert '<html lang="en" data-ui="cc">' in SHELL


def test_the_installed_app_pays_the_status_bar_inset():
    assert "env(safe-area-inset-top, 0px)" in APP_BLOCK
