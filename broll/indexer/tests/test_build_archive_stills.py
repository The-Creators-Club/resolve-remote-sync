"""Posters and sprites ship with the archive, or the site shows "no preview".

The deployed site's DATA_ROOT is the archive root itself: it serves
`media/poster/{id}.jpg` out of `<DATA_ROOT>/posters` and `media/sprite/{id}.jpg`
out of `<DATA_ROOT>/sprites`. Until 2026-08-10 build_archive copied media only
and those two folders were populated by hand, so a clip could be indexed,
searchable and playable while still rendering as a grey placeholder.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from build_archive import POSTER_DIR, SPRITE_DIR, still_pairs  # noqa: E402


def _data_root(tmp_path: Path, *, poster=True, sprite=True, vid=48) -> Path:
    root = tmp_path / "data"
    for kind, want in ((POSTER_DIR, poster), (SPRITE_DIR, sprite)):
        (root / kind).mkdir(parents=True, exist_ok=True)
        if want:
            (root / kind / f"{vid}.jpg").write_bytes(b"\xff\xd8fake\xff\xd9")
    return root


def test_stills_are_named_by_id_in_flat_top_level_folders(tmp_path):
    """The web app looks these up by id under <DATA_ROOT>/posters|sprites. Any
    other layout -- beside the clip, under its category -- is invisible to it."""
    data_root = _data_root(tmp_path)
    dest = tmp_path / "archive"

    found, missing = still_pairs({"id": 48}, data_root, dest)

    assert missing == []
    assert [d.relative_to(dest).as_posix() for _s, d in found] == [
        "posters/48.jpg", "sprites/48.jpg"]
    assert [s.relative_to(data_root).as_posix() for s, _d in found] == [
        "posters/48.jpg", "sprites/48.jpg"]


def test_a_missing_poster_is_a_reported_skip_not_an_abort(tmp_path):
    """stage_proxy can fail on a broken stream, and clips indexed before that
    stage existed have no pair at all. Their media is still worth shipping."""
    data_root = _data_root(tmp_path, poster=False)
    dest = tmp_path / "archive"

    found, missing = still_pairs({"id": 48}, data_root, dest)

    assert missing == [POSTER_DIR]
    assert [d.name for _s, d in found] == ["48.jpg"]
    assert found[0][1].parent.name == SPRITE_DIR


def test_a_clip_with_neither_still_plans_nothing_and_reports_both(tmp_path):
    data_root = _data_root(tmp_path, poster=False, sprite=False)

    found, missing = still_pairs({"id": 48}, data_root, tmp_path / "archive")

    assert found == []
    assert missing == [POSTER_DIR, SPRITE_DIR]


def test_an_absent_data_root_does_not_raise(tmp_path):
    """A dest built against a config whose data_root was never populated must
    still produce a plan -- the media copy is the part that matters."""
    found, missing = still_pairs({"id": 1}, tmp_path / "nope", tmp_path / "archive")

    assert found == []
    assert missing == [POSTER_DIR, SPRITE_DIR]
