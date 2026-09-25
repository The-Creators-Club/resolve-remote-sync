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
    """LIVE and HISTORY are both fixed-layout `.xft` tables, so the column
    widths come from the colgroup and never from a cell's text."""
    html = (ROOT / "templates/partials/transfers.html").read_text(encoding="utf-8")
    tables = re.findall(r'<table class="([^"]*)"', html)
    xft = [t.split() for t in tables if "xft" in t.split()]
    assert len(xft) == 2, tables
    for classes in xft:
        assert {"tbl", "fixed"} <= set(classes), classes


def test_the_numbers_have_fixed_columns_and_the_file_column_takes_the_rest():
    html = (ROOT / "templates/partials/transfers.html").read_text(encoding="utf-8")
    live = html.split('id="xf-live"', 1)[1].split("</table>", 1)[0]
    cols = re.search(r"<colgroup>(.*?)</colgroup>", live, re.S).group(1)
    # progress, speed, eta: each a fixed width; the file column is the one
    # bare <col>, so a long name can only take the space that is left.
    assert re.search(r'<col>(<col style="width:\d+ch">){3}$', cols.strip()), cols


def test_the_file_cell_wraps_and_the_numbers_do_not():
    comps = (ROOT / "static/cc/components.css").read_text(encoding="utf-8")
    assert re.search(r"\.tbl\.fixed \{\s*table-layout: fixed", comps)
    everyday = (ROOT / "static/cc/everyday.css").read_text(encoding="utf-8")
    rule = re.search(r"\.xft td\.file \{([^}]*)\}", everyday)
    # `anywhere`, not `break-word`: only `anywhere` shrinks min-content.
    assert rule and "overflow-wrap: anywhere" in rule.group(1)
    # nothing turns the file cell back into a single unbreakable line
    assert not re.search(r"\.xft td\.file \{[^}]*white-space: nowrap", everyday)
    html = (ROOT / "templates/partials/transfers.html").read_text(encoding="utf-8")
    assert 'class="file c-file"' in html
