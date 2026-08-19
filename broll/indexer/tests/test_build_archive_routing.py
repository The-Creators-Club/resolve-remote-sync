"""Which collection a clip files under, and why it is not the `index` flag.

The archive has two trees with different organising principles: Downloads/ is
organised by category (an editor searches for "nuclear"), Creators_Club/ keeps
the shoot's own shape (an editor looks for "day 2, the A74"). Picking the wrong
one puts a clip somewhere nobody will look, and because the path is recorded in
the index and pointed at by timelines, it is expensive to move afterwards.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from build_archive import (  # noqa: E402
    archive_folders, creator_shares, dest_dir, dest_rel,
)


class _Share:
    def __init__(self, source="originals", index=True, archive_name=""):
        self.source = source
        self.index = index
        self.archive_name = archive_name


class _Cfg:
    def __init__(self, shares):
        self.shares = shares


def test_own_shoot_is_chosen_by_source_not_by_index():
    """The regression that put 99 MOFA clips in Downloads/_uncategorised/.

    MOFA was flipped from index:false to indexed once measurement showed
    describing it was cheap. If the collection rule keys off `index`, that flip
    silently re-routes the whole share into the wrong tree — with no error, and
    visible only as clips filed under a category they never had.
    """
    cfg = _Cfg({
        "mofa-disaster": _Share(source="proxies", index=True),   # own shoot, now indexed
        "ff4-nuclear": _Share(source="originals", index=True),   # a download
    })
    assert creator_shares(cfg) == {"mofa-disaster"}


def test_own_shoot_still_routes_when_not_indexed():
    """Flipping `index` either way must not move a share between collections."""
    on = _Cfg({"mofa": _Share(source="proxies", index=True)})
    off = _Cfg({"mofa": _Share(source="proxies", index=False)})
    assert creator_shares(on) == creator_shares(off) == {"mofa"}


def test_download_is_never_a_creator_share_even_when_unindexed():
    cfg = _Cfg({"ff4-lol": _Share(source="originals", index=False)})
    assert creator_shares(cfg) == set()


def test_own_shoot_keeps_shoot_structure_and_drops_source_proxy_level():
    """`Proxy/` in the SOURCE means "the editor proxy"; in the archive it means
    "the preview". Carrying the source's level through would nest one inside the
    other and break Resolve's `<parent>/Proxy/<stem>` lookup."""
    video = {"share": "mofa-disaster",
             "rel_path": "Day 1/A74/Proxy/fx30_computex0282.mov",
             "category": None}
    creators = {"mofa-disaster"}
    assert dest_dir(video, creators) == "Creators_Club/mofa-disaster/Day 1/A74"
    assert dest_rel(video, creators, ".mov", as_preview=False) == \
        "Creators_Club/mofa-disaster/Day 1/A74/fx30_computex0282.mov"
    assert dest_rel(video, creators, ".mp4", as_preview=True) == \
        "Creators_Club/mofa-disaster/Day 1/A74/Proxy/fx30_computex0282.mp4"


def test_download_files_under_its_category():
    video = {"share": "ff4-nuclear", "rel_path": "clip.mp4",
             "category": "energy/nuclear"}
    assert dest_dir(video, set()) == "Downloads/energy/nuclear"


def test_uncategorised_download_falls_back_to_the_bucket():
    """A download with no category legitimately lands here. An OWN SHOOT landing
    here is the bug above, since own shoots never get a category at all."""
    video = {"share": "ff4-nuclear", "rel_path": "clip.mp4", "category": None}
    assert dest_dir(video, set()) == "Downloads/_uncategorised"


@pytest.mark.parametrize("source", ["proxies", "originals"])
def test_every_share_lands_in_exactly_one_collection(source):
    cfg = _Cfg({"s": _Share(source=source)})
    video = {"share": "s", "rel_path": "a/b.mov", "category": "x/y"}
    folder = dest_dir(video, creator_shares(cfg))
    assert folder.startswith("Creators_Club/") ^ folder.startswith("Downloads/")


def test_archive_name_renames_the_folder_but_not_the_share():
    """`disinfo` on disk, "Disinformation" on the NAS (owner's call, 2026-08-19).

    The two must stay separable: the key is what every videos row is stored
    under, so a rename that reached it would orphan the lot. Only the top level
    of the archive path moves, and the shoot's own subfolders are untouched --
    they are how an editor looks for the clip.
    """
    cfg = _Cfg({
        "disinfo": _Share(source="proxies", archive_name="Disinformation"),
        "ff2": _Share(source="proxies"),
    })
    folders = archive_folders(cfg)
    assert folders == {"disinfo": "Disinformation"}

    video = {"share": "disinfo", "rel_path": "Footage/Bento/Proxy/A001.mov",
             "category": None}
    creators = creator_shares(cfg)
    assert dest_dir(video, creators, folders) == "Creators_Club/Disinformation/Footage/Bento"
    assert dest_rel(video, creators, ".mov", as_preview=False, folders=folders) ==         "Creators_Club/Disinformation/Footage/Bento/A001.mov"

    # A share without one keeps its key, and so does a caller with no config.
    plain = {"share": "ff2", "rel_path": "E1/Day 1/Proxy/B002.mov", "category": None}
    assert dest_dir(plain, creators, folders) == "Creators_Club/ff2/E1/Day 1"
    assert dest_dir(video, creators) == "Creators_Club/disinfo/Footage/Bento"
