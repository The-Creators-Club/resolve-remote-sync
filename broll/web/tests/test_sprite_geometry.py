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
# sprite.js since 2026-08-18: the geometry moved out of app.js so the client
# folder viewer (share.js) reads the SAME copy. Both pages load it first.
APP_JS = REPO / "broll" / "web" / "static" / "sprite.js"
FFMPEG_TOOLS = REPO / "broll" / "indexer" / "broll_index" / "ffmpeg_tools.py"

pytestmark = pytest.mark.skipif(
    not FFMPEG_TOOLS.is_file(),
    reason="the indexer tree is not present in this checkout",
)


def _js_const(name: str) -> float:
    m = re.search(rf"^const {name} = ([0-9.]+);", APP_JS.read_text(encoding="utf-8"),
                  re.M)
    assert m, f"{name} is not defined in sprite.js"
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


def test_the_browser_prefers_the_geometry_the_generator_recorded():
    """The constants above are a MODEL of the generator; the row is the
    generator's own answer (BROLL-1/BROLL-2, 2026-08-11). Where the two
    disagree -- which was 95.3% of live sheets, because `scale=240:-2` rounds to
    even and the source aspect ratio does not -- the row wins.

    These are text assertions because the frontend has no test runner here (the
    same posture as tests/test_mounted_prefix.py); the arithmetic they guard is
    pinned on the generator's side, in the indexer's
    test_sprite_geometry_recorded.py."""
    js = APP_JS.read_text(encoding="utf-8")
    body = js[js.index("function spriteGeometry"):]
    body = body[:body.index("\n}\n")]
    for column in ("sprite_cell_w", "sprite_cell_h", "sprite_cells",
                   "sprite_cols", "sprite_interval_s"):
        assert column in body, f"spriteGeometry ignores videos.{column}"
    # The recorded branch must come FIRST -- a fallback that runs anyway is not
    # a fallback.
    assert body.index("video.sprite_cell_w") < body.index("video.height")


def test_the_source_derived_cell_height_survives_only_as_the_fallback():
    """Legacy rows carry no geometry and must keep behaving exactly as they did
    -- nothing gets worse for a sheet nobody has regenerated. So the old
    arithmetic stays, reachable only when the row is silent."""
    js = APP_JS.read_text(encoding="utf-8")
    body = js[js.index("function spriteGeometry"):]
    body = body[:body.index("\n}\n")]
    assert "SPRITE_CELL_WIDTH * (video.height / video.width)" in body
    assert "135" in body  # the no-dimensions-at-all default, unchanged


def test_positionsprite_reads_the_grid_rather_than_rebuilding_it():
    """Every constant it used to apply by hand now comes from spriteGeometry, so
    there is one place a legacy row is distinguished from a recorded one."""
    js = APP_JS.read_text(encoding="utf-8")
    body = js[js.index("function positionSprite"):]
    body = body[:body.index("\n}")]
    for constant in ("SPRITE_MAX_CELLS", "SPRITE_COLUMNS", "SPRITE_CELL_WIDTH",
                     "video.height", "video.width"):
        assert constant not in body, (
            f"positionSprite re-derives {constant} instead of taking the sheet's "
            "own geometry"
        )


def test_the_card_is_sized_by_the_same_geometry_as_the_overlay():
    """A card sized off the source aspect ratio while the overlay is offset by
    the sheet's real cell height shows a sliver of the next row."""
    # Both card builders: the SPA's (app.js) and the client viewer's
    # (share.js). Each sizes its thumb off the shared geometry.
    for name, fn in (("app.js", "function buildCard"), ("share.js", "function shareCard")):
        js = (APP_JS.parent / name).read_text(encoding="utf-8")
        body = js[js.index(fn):]
        body = body[:body.index("\n}")]
        assert "spriteGeometry(video).cellHeight" in body, name


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
