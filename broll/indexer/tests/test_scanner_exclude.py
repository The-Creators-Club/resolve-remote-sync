"""Share-level directory exclusion.

The case this exists for: a share rooted at a whole project (so the archive keeps
the project's folder structure) must still skip the subtrees that belong to a
different share, or to no share at all. Getting it wrong indexes the editor proxy
of a clip already indexed from its original — a duplicate that content hashing
cannot see, because it is the same footage in a different encode.
"""
from __future__ import annotations

import pytest

from broll_index.config import _build_shares
from broll_index.scanner import do_scan, is_excluded_dir, scan_share
from broll_index.storage.sqlite_backend import SqliteBackend


def _touch(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"fake video bytes")


def _project(root):
    """A miniature of the FF4 shape: own footage, downloads, and AE comps."""
    _touch(root / "Nuclear" / "B-roll" / "Hengchun" / "Proxy" / "own.mov")
    _touch(root / "Nuclear" / "B-roll" / "Youtube" / "Proxy" / "download.mov")
    _touch(root / "Nuclear" / "Youtube" / "Proxy" / "download2.mov")
    _touch(root / "Nuclear" / "AE" / "Renders" / "comp.mov")
    _touch(root / "Spies" / "Interviewees" / "X" / "Proxy" / "own2.mov")


def test_no_patterns_walks_everything(tmp_path):
    root = tmp_path / "FF4"
    _project(root)
    assert len(list(scan_share(root))) == 5


def test_excludes_prune_named_subtrees(tmp_path):
    root = tmp_path / "FF4"
    _project(root)

    found = sorted(sf.rel_path for sf in scan_share(
        root, exclude=["Nuclear/Youtube", "Nuclear/B-roll/Youtube", "*/AE"]))

    assert found == [
        "Nuclear/B-roll/Hengchun/Proxy/own.mov",
        "Spies/Interviewees/X/Proxy/own2.mov",
    ]


def test_star_crosses_separators_so_one_pattern_catches_every_depth(tmp_path):
    root = tmp_path / "FF4"
    _touch(root / "A" / "AE" / "x.mov")
    _touch(root / "A" / "B" / "C" / "AE" / "y.mov")
    _touch(root / "A" / "keep.mov")

    found = sorted(sf.rel_path for sf in scan_share(root, exclude=["*/AE"]))
    assert found == ["A/keep.mov"]


def test_exclude_matches_the_directory_not_the_file(tmp_path):
    """A file whose own name matches a pattern is kept — patterns name folders."""
    root = tmp_path / "FF4"
    _touch(root / "Renders" / "a.mov")
    _touch(root / "Keep" / "Renders.mov")

    found = sorted(sf.rel_path for sf in scan_share(root, exclude=["Renders"]))
    assert found == ["Keep/Renders.mov"]


def test_do_scan_honours_exclude(tmp_path, schema_path):
    root = tmp_path / "FF4"
    _project(root)

    db = SqliteBackend(tmp_path / "t.db", schema_path=schema_path)
    count = do_scan(db, "ff4", root, source="proxies",
                    exclude=["Nuclear/Youtube", "Nuclear/B-roll/Youtube", "*/AE"])
    assert count == 2

    paths = {
        p for p in (
            "Nuclear/B-roll/Hengchun/Proxy/own.mov",
            "Nuclear/B-roll/Youtube/Proxy/download.mov",
            "Nuclear/Youtube/Proxy/download2.mov",
            "Nuclear/AE/Renders/comp.mov",
            "Spies/Interviewees/X/Proxy/own2.mov",
        ) if db.get_video_by_path("ff4", p) is not None
    }
    assert paths == {
        "Nuclear/B-roll/Hengchun/Proxy/own.mov",
        "Spies/Interviewees/X/Proxy/own2.mov",
    }


def test_is_excluded_dir_is_case_sensitive():
    """Deliberate: the NAS holds `youtube` and `Youtube` as distinct folders, and
    a case-insensitive pattern for one would silently swallow the other."""
    assert is_excluded_dir("Nuclear/Youtube", ["Nuclear/Youtube"]) is True
    assert is_excluded_dir("Nuclear/youtube", ["Nuclear/Youtube"]) is False
    assert is_excluded_dir("Nuclear/B-roll", ["Nuclear/Youtube"]) is False


def test_config_parses_exclude_and_strips_slashes():
    shares = _build_shares({"ff4": {"root": "Z:/FF4", "source": "proxies",
                                    "exclude": ["/Nuclear/Youtube/", "*/AE"]}})
    assert shares["ff4"].exclude == ["Nuclear/Youtube", "*/AE"]


def test_config_defaults_exclude_to_empty():
    shares = _build_shares({"a": {"root": "Z:/a"}, "b": "Z:/b"})
    assert shares["a"].exclude == []
    assert shares["b"].exclude == []


def test_config_rejects_a_bare_string_exclude():
    """A string is iterable, so it would 'work' and exclude nothing."""
    with pytest.raises(ValueError, match="must be a list"):
        _build_shares({"ff4": {"root": "Z:/FF4", "exclude": "Nuclear/Youtube"}})
