"""Regression tests for non-ASCII handling.

A real archive scan (FF2 E1, Chinese-language news clips) died with
UnicodeDecodeError: 'charmap' codec can't decode byte 0x8d — subprocess
defaults to the Windows locale codepage (cp950 here), which cannot decode
ffprobe's UTF-8 output when a file carries CJK metadata or a CJK name.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from broll_index.ffmpeg_tools import TEXT_UTF8, probe_video, run_ffprobe

CJK_TITLE = "【歷史上的今天】警匪激烈槍戰"
CJK_NAME = "測試片段_ceshi.mp4"


@pytest.fixture
def cjk_clip(tmp_path: Path, require_ffmpeg) -> Path:
    """A tiny real clip with a CJK filename AND a CJK title tag in its metadata.

    require_ffmpeg (conftest.py) turns "no ffmpeg on PATH" into a clean skip
    (or, with CCSYNC_REQUIRE_FFMPEG=1, a failure) instead of the raw
    FileNotFoundError subprocess.run() below would otherwise raise
    (2026-08-17, same fix as test_ffmpeg_tools.py / test_proxy_integrity.py)."""
    out = tmp_path / CJK_NAME
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=320x240:duration=1:rate=10",
            "-metadata", f"title={CJK_TITLE}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out),
        ],
        capture_output=True, check=True, **TEXT_UTF8,
    )
    return out


def test_text_utf8_does_not_rely_on_locale_codec() -> None:
    assert TEXT_UTF8["encoding"] == "utf-8"
    # A stray undecodable byte must never abort a long indexing run.
    assert TEXT_UTF8["errors"] == "replace"


def test_ffprobe_reads_file_with_cjk_name_and_metadata(cjk_clip: Path) -> None:
    info = run_ffprobe(cjk_clip)
    assert info["format"]["tags"]["title"] == CJK_TITLE


def test_probe_video_handles_cjk(cjk_clip: Path) -> None:
    meta = probe_video(cjk_clip)
    assert meta["width"] == 320 and meta["height"] == 240
    assert meta["duration_s"] == pytest.approx(1.0, abs=0.2)


def test_scan_and_store_roundtrip_cjk_path(tmp_path: Path, schema_path: Path, cjk_clip: Path) -> None:
    from broll_index.scanner import do_scan
    from broll_index.storage.sqlite_backend import SqliteBackend

    db = SqliteBackend(tmp_path / "broll.db", schema_path=schema_path)
    count = do_scan(db, "ff2", cjk_clip.parent)

    assert count == 1
    row = db.get_video_by_path("ff2", CJK_NAME)
    assert row is not None and row["rel_path"] == CJK_NAME
