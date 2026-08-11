"""build_sprite records the sheet it actually built, and stage_proxy stores it.

The browser used to re-derive the grid from videos.width/height (the SOURCE)
and from a model of build_sprite's own rules. Both were wrong across most of
the live archive: the sheet is tiled from the 540p proxy through
`scale=240:-2`, and each scale step rounds to an even number, so 6,783 of 7,117
sheets had a cell a pixel taller than the source aspect ratio predicts
(BROLL-1) -- and the SPRITE_MAX_CELLS cap postdates 95 sheets that were built
without it, with nothing on the row to say which is which (BROLL-2).

Nothing recovers either fact from the JPEG afterwards, so these pin that the
generator hands it over and that the pipeline persists it.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from broll_index import ffmpeg_tools, pipeline
from broll_index.config import Config, DbConfig, SamplingConfig, ShareConfig


@pytest.fixture
def landscape_clip(tmp_path: Path, ffmpeg_available: bool) -> Path:
    """A 1920x1080 clip -- the ratio that produced the measured 135-vs-136 gap."""
    if not ffmpeg_available:
        pytest.skip("ffmpeg/ffprobe not available on PATH")
    out = tmp_path / "hd.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", "testsrc=duration=4:size=1920x1080:rate=25",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)],
        check=True,
    )
    return out


def test_build_sprite_returns_the_grid_it_tiled(landscape_clip, tmp_path):
    dest = tmp_path / "sprite.jpg"
    geometry = ffmpeg_tools.build_sprite(landscape_clip, dest, duration_s=4.0)

    assert geometry["sprite_cols"] == 10
    assert geometry["sprite_interval_s"] == 2.0
    assert geometry["sprite_cells"] == 3  # floor(4/2) + 1
    assert geometry["sprite_cell_w"] == 240


def test_the_measured_cell_height_is_the_even_one_not_the_arithmetic_one(
    landscape_clip, tmp_path
):
    """The whole of BROLL-1 in one assertion: 240 * 1080/1920 is 135, and the
    sheet's cells are 136 px tall because `scale=240:-2` rounds to even. A
    browser that trusts the arithmetic is one row-fraction off per row."""
    dest = tmp_path / "sprite.jpg"
    geometry = ffmpeg_tools.build_sprite(landscape_clip, dest, duration_s=4.0)

    assert round(240 * 1080 / 1920) == 135
    assert geometry["sprite_cell_h"] == 136


def test_the_recorded_grid_actually_divides_the_sheet(landscape_clip, tmp_path):
    """Measured off the file, so it must tile it exactly -- that is the property
    the overlay's backgroundPosition depends on."""
    dest = tmp_path / "sprite.jpg"
    geometry = ffmpeg_tools.build_sprite(landscape_clip, dest, duration_s=4.0)
    width, height = ffmpeg_tools.probe_image_size(dest)

    rows = -(-geometry["sprite_cells"] // geometry["sprite_cols"])
    assert width == geometry["sprite_cell_w"] * geometry["sprite_cols"]
    assert height == geometry["sprite_cell_h"] * rows


def test_a_widened_interval_is_recorded_as_widened(tmp_path, monkeypatch):
    """BROLL-2's half: the interval is only 2 s below the cap, and the row has
    to say which it got -- a sheet built before the cap existed carries no
    marker, which is why the browser was guessing.

    ffmpeg is spied rather than run, as in test_proxy_integrity's twin: a short
    fixture clip at a widened interval yields no frames, which would fail for
    reasons unrelated to the arithmetic under test."""
    captured = {}

    def spy(cmd, *a, **kw):
        if isinstance(cmd, list) and "-vf" in cmd:
            captured["vf"] = cmd[cmd.index("-vf") + 1]
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(ffmpeg_tools.subprocess, "run", spy)
    geometry = ffmpeg_tools.build_sprite(
        tmp_path / "src.mp4", tmp_path / "long.jpg", duration_s=3600.0, max_cells=60
    )

    assert geometry["sprite_interval_s"] == 60.0
    assert geometry["sprite_cells"] == 60
    # The recorded interval is the one that was actually tiled, not the request.
    assert "fps=1/60.0" in captured["vf"]


def test_an_unmeasurable_sheet_records_no_cell_size_rather_than_a_guess(
    tmp_path, monkeypatch
):
    """"Unknown" is a usable answer -- the browser falls back to its legacy
    heuristics. A guessed cell size stored as if measured is not."""
    monkeypatch.setattr(ffmpeg_tools.subprocess, "run",
                        lambda *a, **kw: subprocess.CompletedProcess(a[0], 0, "", ""))
    geometry = ffmpeg_tools.build_sprite(tmp_path / "src.mp4", tmp_path / "s.jpg",
                                         duration_s=10.0)

    assert geometry["sprite_cell_w"] is None
    assert geometry["sprite_cell_h"] is None
    assert geometry["sprite_cells"] == 6  # the arithmetic half is still known


def test_stage_proxy_stores_the_geometry_on_the_row(tmp_path, sqlite_storage, monkeypatch):
    monkeypatch.setattr(ffmpeg_tools, "detect_nvenc_available", lambda: False)
    monkeypatch.setattr(ffmpeg_tools, "build_proxy", lambda *a, **kw: None)
    monkeypatch.setattr(ffmpeg_tools, "build_poster", lambda *a, **kw: None)
    monkeypatch.setattr(ffmpeg_tools, "build_sprite", lambda *a, **kw: {
        "sprite_cols": 10, "sprite_cells": 24, "sprite_interval_s": 12.5,
        "sprite_cell_w": 240, "sprite_cell_h": 136,
    })

    vid = sqlite_storage.upsert_video("s", "clip.mov", status="probed", duration_s=300.0)
    cfg = Config(
        shares={"s": ShareConfig(root=str(tmp_path))},
        data_root=tmp_path / "_data",
        db=DbConfig(mode="sqlite", path=str(tmp_path / "broll.db")),
        model="sonnet",
        sampling=SamplingConfig(),
    )
    pipeline.stage_proxy(cfg, sqlite_storage, sqlite_storage.get_video(vid),
                         tmp_path / "clip.mov")

    row = sqlite_storage.get_video(vid)
    assert row["status"] == "proxied"
    assert (row["sprite_cell_w"], row["sprite_cell_h"]) == (240, 136)
    assert (row["sprite_cols"], row["sprite_cells"]) == (10, 24)
    assert row["sprite_interval_s"] == 12.5
