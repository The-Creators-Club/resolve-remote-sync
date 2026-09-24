"""CR-312 (2026-09-24): a long clip name on LIVE TRANSFERS pushed PROGRESS,
SPEED and ETA off the panel behind a sideways scroll. `.mono-sm` is nowrap,
so the FILE cell's text set the table width. Measured in Chrome at 1600, 1100
and 390 px after the fix: no .scroll-x overflows and every SPEED cell is
inside the box. This pins the two pieces that make it so.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_both_transfers_tables_carry_the_class():
    html = (ROOT / "templates/partials/transfers.html").read_text(encoding="utf-8")
    assert html.count('class="editors stack transfers"') == 2


def test_the_file_cell_wraps_and_the_numbers_do_not():
    css = (ROOT / "static/style.css").read_text(encoding="utf-8")
    rule = re.search(r"table\.editors\.transfers td\.path \{([^}]*)\}", css)
    assert rule and "white-space: normal" in rule.group(1)
    # `anywhere`, not `break-word`: only `anywhere` shrinks min-content.
    assert "overflow-wrap: anywhere" in rule.group(1)
    assert re.search(r"table\.editors\.transfers td:not\(\.path\) \{\s*white-space: nowrap",
                     css)
