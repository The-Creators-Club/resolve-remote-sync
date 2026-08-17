"""build_archive --apply must not undo an in-place repair, and must not
destroy anything it replaces.

COMMERCIAL_READINESS.md item 9 (2026-08-17). The copy set was
`d.stat().st_size != s.stat().st_size` -- so every preview
`fix_10bit_proxies.py --apply` had re-encoded (a different size by
definition) looked un-copied, and the next build put the 10-bit source back
over the fix. Silently, on every clip, every run. Size is not identity.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import build_archive  # noqa: E402
from broll_index import inplace_fixes  # noqa: E402


def _write(path: Path, data: bytes, mtime: float | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


class TestNeedsCopy:
    def test_an_absent_destination_needs_copying(self, tmp_path):
        src = _write(tmp_path / "src.mp4", b"abc")
        assert build_archive.needs_copy(src, tmp_path / "dst.mp4") is True

    def test_a_faithful_copy_does_not(self, tmp_path):
        src = _write(tmp_path / "src.mp4", b"abc" * 100, mtime=1_700_000_000)
        dst = _write(tmp_path / "dst.mp4", b"abc" * 100, mtime=1_700_000_000)
        assert build_archive.needs_copy(src, dst) is False

    def test_a_different_size_needs_copying(self, tmp_path):
        src = _write(tmp_path / "src.mp4", b"abc" * 100, mtime=1_700_000_000)
        dst = _write(tmp_path / "dst.mp4", b"abc", mtime=1_700_000_000)
        assert build_archive.needs_copy(src, dst) is True

    def test_same_size_different_content_is_caught_by_the_hash(self, tmp_path):
        # The gap size alone leaves: a truncated or wrong file of the right
        # length used to read as "already present".
        src = _write(tmp_path / "src.mp4", b"a" * 4096, mtime=1_700_000_000)
        dst = _write(tmp_path / "dst.mp4", b"b" * 4096, mtime=1_700_000_500)
        assert build_archive.needs_copy(src, dst) is True

    def test_a_second_of_filesystem_rounding_is_not_a_difference(self, tmp_path):
        src = _write(tmp_path / "src.mp4", b"a" * 4096, mtime=1_700_000_000)
        dst = _write(tmp_path / "dst.mp4", b"a" * 4096, mtime=1_700_000_001)
        assert build_archive.needs_copy(src, dst) is False


class TestInPlaceFixesAreProtected:
    def test_a_recorded_repair_is_not_re_copied(self, tmp_path):
        root = tmp_path / "archive"
        src = _write(tmp_path / "sources" / "A001.mp4", b"10-bit source" * 100)
        dst = _write(root / "Creators_Club" / "Proxy" / "A001.mp4", b"8-bit repair")
        inplace_fixes.record(root, dst, note="R9")

        # Size differs, so the old rule would have re-copied it.
        assert build_archive.needs_copy(src, dst) is True
        assert inplace_fixes.is_fixed(root, dst) is True

    def test_protection_lapses_once_the_file_is_something_else(self, tmp_path):
        root = tmp_path / "archive"
        dst = _write(root / "Creators_Club" / "Proxy" / "A001.mp4", b"8-bit repair")
        inplace_fixes.record(root, dst)
        dst.write_bytes(b"a completely different file")
        assert inplace_fixes.is_fixed(root, dst) is False

    def test_the_manifest_survives_a_second_entry(self, tmp_path):
        root = tmp_path / "archive"
        a = _write(root / "x" / "Proxy" / "a.mp4", b"a")
        b = _write(root / "x" / "Proxy" / "b.mp4", b"b")
        inplace_fixes.record(root, a)
        inplace_fixes.record(root, b)
        assert len(inplace_fixes.load(root)) == 2
        assert inplace_fixes.is_fixed(root, a) and inplace_fixes.is_fixed(root, b)

    def test_a_missing_or_corrupt_manifest_protects_nothing(self, tmp_path):
        root = tmp_path / "archive"
        dst = _write(root / "x" / "Proxy" / "a.mp4", b"a")
        assert inplace_fixes.load(root) == {}
        inplace_fixes.manifest_path(root).write_text("{not json", encoding="utf-8")
        assert inplace_fixes.load(root) == {}
        assert inplace_fixes.is_fixed(root, dst) is False


class TestTrash:
    def test_a_replaced_file_is_kept_not_destroyed(self, tmp_path):
        root = tmp_path / "archive"
        victim = _write(root / "Creators_Club" / "Proxy" / "A001.mp4", b"the old one")

        kept = inplace_fixes.stash(root, victim)

        assert kept is not None and kept.read_bytes() == b"the old one"
        assert not victim.exists()
        assert inplace_fixes.TRASH_DIRNAME in str(kept)

    def test_stashing_nothing_is_not_an_error(self, tmp_path):
        assert inplace_fixes.stash(tmp_path, tmp_path / "nope.mp4") is None


class TestQuickHash:
    def test_it_distinguishes_a_re_encode_from_its_source(self, tmp_path):
        a = _write(tmp_path / "a.mp4", b"x" * 5000)
        b = _write(tmp_path / "b.mp4", b"y" * 5000)
        assert inplace_fixes.quick_hash(a) != inplace_fixes.quick_hash(b)

    def test_it_is_stable_for_the_same_bytes(self, tmp_path):
        a = _write(tmp_path / "a.mp4", b"x" * 5_000_000)
        b = _write(tmp_path / "b.mp4", b"x" * 5_000_000)
        assert inplace_fixes.quick_hash(a) == inplace_fixes.quick_hash(b)

    def test_an_unreadable_file_hashes_to_nothing_rather_than_raising(self, tmp_path):
        assert inplace_fixes.quick_hash(tmp_path / "missing.mp4") == ""
