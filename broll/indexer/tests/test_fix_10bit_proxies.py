"""fix_10bit_proxies must never transcode an ORIGINAL.

COMMERCIAL_READINESS.md item 9 (2026-08-17). `candidate_files` resolves
`videos.archive_path` straight out of the database and `reencode` overwrites
whatever it is handed. A row whose archive_path points at the top-slot
original -- an older row, a hand-edited path, a clip published before the
layout rule -- had its best copy re-encoded to 540p over itself, and the
script printed `fixed` next to it. Nothing about that was recoverable: the
sources live on archive drives that are not in the tree, and the archive copy
IS the copy editors link against.

No ffmpeg here: build_proxy is stubbed, because what is under test is which
files the script is willing to point it at.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fix_10bit_proxies as fix  # noqa: E402
from broll_index import inplace_fixes  # noqa: E402


@pytest.fixture
def archive(tmp_path):
    root = tmp_path / "archive"
    clip_dir = root / "Creators_Club" / "ff3" / "day1"
    (clip_dir / "Proxy").mkdir(parents=True)
    (clip_dir / "A001.mov").write_bytes(b"the original, 40 GB of it" * 10)
    (clip_dir / "Proxy" / "A001.mp4").write_bytes(b"the 10-bit preview")
    return root


class TestIsAProxy:
    @pytest.mark.parametrize("rel,expected", [
        ("Creators_Club/ff3/day1/Proxy/A001.mp4", True),
        ("Creators_Club/ff3/day1/proxy/A001.mp4", True),
        ("proxies/4127.mp4", True),
        ("Creators_Club/ff3/day1/A001.mov", False),
        ("Downloads/news/clip.mp4", False),
    ])
    def test_structural_classification(self, tmp_path, rel, expected):
        assert fix.is_a_proxy(tmp_path / rel) is expected


class TestReencodeRefusal:
    def test_it_refuses_a_file_outside_a_proxy_folder(self, archive, monkeypatch):
        called = []
        monkeypatch.setattr(fix.ffmpeg_tools, "build_proxy",
                            lambda s, d: called.append((s, d)))
        original = archive / "Creators_Club" / "ff3" / "day1" / "A001.mov"
        before = original.read_bytes()

        err = fix.reencode(original, archive)

        assert err is not None and "REFUSED" in err
        assert called == []
        assert original.read_bytes() == before

    def test_it_re_encodes_a_real_preview(self, archive, monkeypatch):
        preview = archive / "Creators_Club" / "ff3" / "day1" / "Proxy" / "A001.mp4"
        monkeypatch.setattr(fix.ffmpeg_tools, "build_proxy",
                            lambda s, d: Path(d).write_bytes(b"8-bit"))

        assert fix.reencode(preview, archive) is None
        assert preview.read_bytes() == b"8-bit"

    def test_the_source_is_the_adjacent_original_when_there_is_exactly_one(
            self, archive, monkeypatch):
        preview = archive / "Creators_Club" / "ff3" / "day1" / "Proxy" / "A001.mp4"
        seen = {}
        monkeypatch.setattr(
            fix.ffmpeg_tools, "build_proxy",
            lambda s, d: seen.update(src=Path(s)) or Path(d).write_bytes(b"8"))

        fix.reencode(preview, archive)
        assert seen["src"].name == "A001.mov"

    def test_a_stem_diverged_preview_falls_back_to_itself(self, archive, monkeypatch):
        # Safe only because the target is inside Proxy/ -- a second generation
        # of a 540p browsing proxy costs nothing anyone can see.
        (archive / "Creators_Club" / "ff3" / "day1" / "A001.mov").unlink()
        preview = archive / "Creators_Club" / "ff3" / "day1" / "Proxy" / "A001.mp4"
        seen = {}
        monkeypatch.setattr(
            fix.ffmpeg_tools, "build_proxy",
            lambda s, d: seen.update(src=Path(s)) or Path(d).write_bytes(b"8"))

        fix.reencode(preview, archive)
        assert seen["src"] == preview

    def test_a_failed_encode_leaves_the_preview_and_no_temp(self, archive, monkeypatch):
        preview = archive / "Creators_Club" / "ff3" / "day1" / "Proxy" / "A001.mp4"
        before = preview.read_bytes()

        def boom(s, d):
            raise RuntimeError("ffmpeg died")

        monkeypatch.setattr(fix.ffmpeg_tools, "build_proxy", boom)

        assert "ffmpeg died" in (fix.reencode(preview, archive) or "")
        assert preview.read_bytes() == before
        assert list(preview.parent.glob(".fix~*")) == []


class TestManifest:
    def test_a_repair_is_recorded_so_build_archive_cannot_undo_it(
            self, archive, monkeypatch):
        preview = archive / "Creators_Club" / "ff3" / "day1" / "Proxy" / "A001.mp4"
        monkeypatch.setattr(fix.ffmpeg_tools, "build_proxy",
                            lambda s, d: Path(d).write_bytes(b"8-bit and different"))

        fix.reencode(preview, archive)

        assert inplace_fixes.is_fixed(archive, preview) is True

    def test_a_manifest_entry_stops_protecting_a_file_that_changed_since(
            self, archive, monkeypatch):
        preview = archive / "Creators_Club" / "ff3" / "day1" / "Proxy" / "A001.mp4"
        monkeypatch.setattr(fix.ffmpeg_tools, "build_proxy",
                            lambda s, d: Path(d).write_bytes(b"8-bit"))
        fix.reencode(preview, archive)

        preview.write_bytes(b"something else entirely")
        assert inplace_fixes.is_fixed(archive, preview) is False

    def test_a_refusal_records_nothing(self, archive, monkeypatch):
        monkeypatch.setattr(fix.ffmpeg_tools, "build_proxy",
                            lambda s, d: pytest.fail("transcoded an original"))
        original = archive / "Creators_Club" / "ff3" / "day1" / "A001.mov"
        fix.reencode(original, archive)
        assert inplace_fixes.load(archive) == {}
