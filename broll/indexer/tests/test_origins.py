"""Resolving where each clip's TRUE original lives.

Everything an editor touches is a proxy; the sources stay on the archive
drives. At final export the real file has to be found again, so its location is
recorded while we still know it.
"""
from __future__ import annotations

from broll_index.origins import resolve_originals

ROOTS = {"dl": "I:/Downloads", "own": "Z:/Shoot"}


def _row(vid, share, rel_path, status="indexed", size=None):
    return {"id": vid, "share": share, "rel_path": rel_path,
            "status": status, "size_bytes": size}


def test_a_downloads_clip_resolves_to_its_own_path():
    rows = [_row(1, "dl", "news/clip.mp4", size=100)]
    out = resolve_originals(rows, ROOTS)
    assert out[1]["path"].replace("\\", "/") == "I:/Downloads/news/clip.mp4"
    assert out[1]["size_bytes"] == 100


def test_a_proxies_clip_resolves_to_the_camera_original():
    """rel_path is the PROXY; the original is a separate 'excluded' row one
    directory up with a different extension, and nothing linked the two."""
    rows = [
        _row(1, "own", "Day 1/A74/Proxy/shot_001.mov", size=27_000_000),
        _row(2, "own", "Day 1/A74/shot_001.MP4", status="excluded", size=1_024_000_000),
    ]
    out = resolve_originals(rows, ROOTS)
    assert out[1]["path"].replace("\\", "/") == "Z:/Shoot/Day 1/A74/shot_001.MP4"
    assert out[1]["size_bytes"] == 1_024_000_000, "the ORIGINAL's size, not the proxy's"


def test_the_excluded_row_itself_is_not_given_an_original():
    rows = [
        _row(1, "own", "Day 1/A74/Proxy/shot_001.mov"),
        _row(2, "own", "Day 1/A74/shot_001.MP4", status="excluded"),
    ]
    assert 2 not in resolve_originals(rows, ROOTS)


def test_two_cameras_with_the_same_filename_do_not_cross_pair():
    """The real shoot has `Day 1/A74/x.mov` and `Day 1/Fx3/x.mov`. Matching on
    stem alone would pair a proxy with the wrong camera's original."""
    rows = [
        _row(1, "own", "Day 1/A74/Proxy/clip.mov"),
        _row(2, "own", "Day 1/A74/clip.MP4", status="excluded", size=11),
        _row(3, "own", "Day 1/Fx3/Proxy/clip.mov"),
        _row(4, "own", "Day 1/Fx3/clip.MP4", status="excluded", size=22),
    ]
    out = resolve_originals(rows, ROOTS)
    assert out[1]["size_bytes"] == 11
    assert "A74" in out[1]["path"]
    assert out[3]["size_bytes"] == 22
    assert "Fx3" in out[3]["path"]


def test_days_are_kept_apart_too():
    rows = [
        _row(1, "own", "Day 1/A74/Proxy/clip.mov"),
        _row(2, "own", "Day 1/A74/clip.MP4", status="excluded", size=11),
        _row(3, "own", "Day 2/A74/Proxy/clip.mov"),
        _row(4, "own", "Day 2/A74/clip.MP4", status="excluded", size=22),
    ]
    out = resolve_originals(rows, ROOTS)
    assert out[1]["size_bytes"] == 11 and "Day 1" in out[1]["path"]
    assert out[3]["size_bytes"] == 22 and "Day 2" in out[3]["path"]


def test_extension_differences_do_not_prevent_a_match():
    """Proxy is .mov, camera original is .MP4 — matching is on the stem."""
    rows = [
        _row(1, "own", "Day 1/A74/Proxy/shot.mov"),
        _row(2, "own", "Day 1/A74/SHOT.MP4", status="excluded", size=5),
    ]
    assert resolve_originals(rows, ROOTS)[1]["size_bytes"] == 5


def test_a_share_with_no_configured_root_is_skipped_not_guessed():
    rows = [_row(1, "unknown-share", "a.mov")]
    assert resolve_originals(rows, ROOTS) == {}


def test_a_proxy_with_no_original_beside_it_falls_back_to_itself():
    """A proxies-share clip whose camera file was never scanned still needs a
    path — its own is the best available answer, not None."""
    rows = [_row(1, "own", "Day 1/A74/Proxy/orphan.mov", size=7)]
    out = resolve_originals(rows, ROOTS)
    assert out[1]["path"].replace("\\", "/") == "Z:/Shoot/Day 1/A74/Proxy/orphan.mov"
