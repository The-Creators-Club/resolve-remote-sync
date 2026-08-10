"""The sprite sheet is written by the indexer and read by the browser, and the
two live in different languages in different packages on different machines.

Nothing connected them. `build_sprite` caps a sheet at SPRITE_MAX_CELLS cells
and stretches the interval to fit; `positionSprite` read the interval as a flat
2 s. Every clip longer than 8 minutes (240 cells x 2 s) therefore had its cell
index computed against a grid it did not have: the 46:20 hit in a 50:41
documentary was called cell 1390 of a sheet holding 240, the overlay landed
below the image and painted nothing, and the poster underneath -- taken at 10%
in, i.e. an interview at 5:04 -- showed through as "the thumbnail". It looked
like a thumbnail picking a bad frame rather than a grid mismatch, which is why
it survived a round of thumbnail work (2026-08-10).

These read both files as TEXT. The web container has no indexer package to
import (deliberately -- it needs a GPU and ffmpeg), so a regex over the source
is the only honest way to compare them from here.
"""
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
APP_JS = REPO / "broll" / "web" / "static" / "app.js"
FFMPEG_TOOLS = REPO / "broll" / "indexer" / "broll_index" / "ffmpeg_tools.py"

pytestmark = pytest.mark.skipif(
    not FFMPEG_TOOLS.is_file(),
    reason="the indexer tree is not present in this checkout",
)


def _js_const(name: str) -> float:
    m = re.search(rf"^const {name} = ([0-9.]+);", APP_JS.read_text(encoding="utf-8"),
                  re.M)
    assert m, f"{name} is not defined in app.js"
    return float(m.group(1))


def _py_value(pattern: str) -> float:
    m = re.search(pattern, FFMPEG_TOOLS.read_text(encoding="utf-8"), re.M)
    assert m, f"{pattern} not found in ffmpeg_tools.py"
    return float(m.group(1))


def test_the_browser_and_the_generator_agree_on_the_grid():
    assert _js_const("SPRITE_MAX_CELLS") == _py_value(r"^SPRITE_MAX_CELLS = (\d+)")
    assert _js_const("SPRITE_COLUMNS") == _py_value(r"columns: int = (\d+)")
    assert _js_const("SPRITE_CELL_WIDTH") == _py_value(r"cell_width: int = (\d+)")
    assert _js_const("SPRITE_SECONDS_PER_FRAME") == _py_value(
        r"interval_s: float = ([0-9.]+)")


def test_the_browser_widens_the_interval_like_the_generator_does():
    """Not just "the constants match" -- the browser has to APPLY the cap. It
    held the right SPRITE_COLUMNS and SPRITE_CELL_WIDTH all along and still
    read the wrong cell, because it never divided by SPRITE_MAX_CELLS."""
    js = APP_JS.read_text(encoding="utf-8")
    assert re.search(r"duration / SPRITE_MAX_CELLS", js), (
        "positionSprite must stretch the interval for long clips the way "
        "build_sprite does, or every clip over 8 minutes reads the wrong cell"
    )
    # And the flat interval must not survive anywhere that maps seconds -> cell.
    body = js[js.index("function positionSprite"):]
    body = body[:body.index("\n}")]
    assert "SPRITE_SECONDS_PER_FRAME" not in body, (
        "positionSprite should take its interval from spriteInterval(), not "
        "the flat constant"
    )


@pytest.mark.parametrize("duration_s,expected_interval", [
    (60.0, 2.0),        # a minute: under the cap, unchanged
    (480.0, 2.0),       # exactly 240 cells: still the shipped interval
    (481.0, 481 / 240), # one second over: the interval starts stretching
    (3041.0, 3041 / 240),  # the 50:41 documentary that showed the wrong frame
])
def test_the_documented_interval_rule(duration_s, expected_interval):
    """Pins the rule itself, so a change to either side has to change this
    table and say what it means."""
    max_cells = _py_value(r"^SPRITE_MAX_CELLS = (\d+)")
    base = _js_const("SPRITE_SECONDS_PER_FRAME")
    interval = duration_s / max_cells if duration_s / base > max_cells else base
    assert interval == pytest.approx(expected_interval)
