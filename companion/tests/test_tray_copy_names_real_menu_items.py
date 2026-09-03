"""No copy that sends an editor to a tray menu item that no longer exists.

bug-hunt-2026-09-03 comp-ui-2. The 2026-08-27 menu reduction cut the tray's
right-click menu to ten rows and moved COPY DIAGNOSTICS FOR YOUR ADMIN, OPEN
LOG, SCAN WHOLE PROJECT and the whole Advanced submenu into the Settings
window (settings_window.py). The error copy did not move with them: for a
week the balloon an editor saw when a lane failed said "Tray -> Copy
diagnostics for your admin", and there was no such item anywhere in the menu -
on precisely the machine whose diagnostics the admin needed.

So the strings say where the button IS now: "Tray > Settings > COPY
DIAGNOSTICS FOR YOUR ADMIN", "Tray > Settings > OPEN LOG", "Tray > Settings >
SCAN WHOLE PROJECT", "Tray > Settings > REMOVE '<project>'". This test does
not know what the menu contains; it knows the two spellings that named the OLD
shape, so the next menu move cannot leave the copy behind quietly.

Same shape as test_no_em_dash.py: an AST walk over string literals in the
whole package, docstrings and log arguments subtracted (a comment or a log
line describing the old menu is history, not copy).
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from test_no_em_dash import _docstring_nodes, _log_argument_nodes, _py_files

SRC = Path(__file__).resolve().parents[1] / "src" / "ccsync_companion"

# The arrow is how every one of these strings was written; "Tray > Advanced"
# is the same claim in the new punctuation, and there is no Advanced submenu
# to reach either way.
DEAD_ROUTES = ("Tray →", "tray →", "Advanced →", "Tray > Advanced")


def _offenders(source: str, filename: str) -> list[str]:
    tree = ast.parse(source, filename=filename)
    skip = _docstring_nodes(tree) | _log_argument_nodes(tree)
    return [
        node.value for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
        and id(node) not in skip
        and any(route in node.value for route in DEAD_ROUTES)
    ]


@pytest.mark.parametrize("path", _py_files(), ids=lambda p: p.name)
def test_no_copy_points_at_a_menu_item_that_is_gone(path: Path) -> None:
    bad = _offenders(path.read_text(encoding="utf-8"), str(path))
    assert not bad, (
        f"{path.relative_to(SRC).as_posix()} sends an editor to a tray menu item the "
        f"2026-08-27 reduction deleted: {bad}. Those buttons are in the Settings "
        f"window now - say 'Tray > Settings > COPY DIAGNOSTICS FOR YOUR ADMIN' (or "
        f"OPEN LOG / SCAN WHOLE PROJECT / REMOVE '<project>').")


def test_the_scan_would_catch_a_regression() -> None:
    """The detector itself, and the exemptions it inherits."""
    assert _offenders('x = "Something went wrong. Tray → Copy diagnostics."', "<x>")
    assert _offenders('x = "use Advanced → Remove a project"', "<x>")
    assert _offenders('x = "Tray > Advanced > Open log"', "<x>")
    assert not _offenders(
        'x = "Tray > Settings > COPY DIAGNOSTICS FOR YOUR ADMIN"', "<x>")
    # History in a comment, a docstring or the log is not copy.
    assert not _offenders('"""was Tray → Copy diagnostics"""', "<x>")
    assert not _offenders('x = 1  # was Tray → Copy diagnostics', "<x>")
    assert not _offenders('log.info("was Tray → Copy diagnostics")', "<x>")


# -- and the other half of the same promise (UX-1, sweep 2026-09-04) ---------
#
# The scan above knows the two spellings that named the OLD shape. It cannot
# know whether a route written today still ends somewhere. So the routes live
# in ui_copy.py (tests/test_sweep_2026_09_04_copy.py pins that they live
# nowhere else), and each carries the label of the row it ends at: deleting
# or renaming that row without touching the copy is what this test fails on.

MENU_SOURCES = ("tray.py", "settings_window.py")


def _menu_source() -> str:
    return "\n".join((SRC / name).read_text(encoding="utf-8")
                     for name in MENU_SOURCES)


def test_every_route_ends_at_a_row_that_exists() -> None:
    from ccsync_companion import ui_copy

    source = _menu_source()
    missing = {route: row for route, row in ui_copy.ROUTE_ROWS.items()
               if row not in source}
    assert not missing, (
        f"these routes name a menu row that no longer appears in "
        f"{' or '.join(MENU_SOURCES)}: {missing}. Either the row moved (fix "
        f"the route in ui_copy.py) or the copy is pointing at nothing again, "
        f"which is exactly what the 2026-08-27 menu reduction did.")


def test_every_route_is_spelled_one_way() -> None:
    """One arrow, one prefix. Half the copy said "Tray >" and half "Tray →"."""
    from ccsync_companion import ui_copy

    for route in ui_copy.ROUTES:
        assert route.startswith("Tray > "), route
        assert "→" not in route and "->" not in route, route
        assert "…" not in route, (
            f"{route!r}: the ellipsis is on the button, not in the sentence "
            f"pointing at it - it reads as a truncation mid-line.")
