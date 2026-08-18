"""What a dropped clip is CALLED in the archive, and why it is never guessed.

`app/archive_names.py` is `build_archive.py`'s naming rules, lifted rather than
vendored (the indexer script imports PyYAML and its own config module, neither
of which the dashboard container has). Lifted code needs a test that says what
it must keep doing, and this is it -- plus a direct comparison against the
indexer's own functions where a checkout is present, so a rule fixed there and
not here is loud.

The rule that matters most is the one that reads like an implementation
detail: collisions are settled against CLAIMED names, never against what is on
disk. Treating a file already at the target path as a collision renamed all
2,093 clips to `_2` on the indexer's second archive build, and the newcomer
variant of the same bug (BROLL-IDX-5, 2026-08-14) wrote one clip's bytes over a
file already recorded on another row, already served by the web app and already
cut into editors' timelines.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from app.archive_names import MAX_STEM, claim_key, claim_name, safe_name, split_stem

REPO_ROOT = Path(__file__).resolve().parents[3]
BUILD_ARCHIVE = REPO_ROOT / "broll" / "indexer" / "build_archive.py"


def test_windows_forbidden_characters_are_replaced_and_nothing_else():
    assert safe_name('a<b>c:d"e/f\\g|h?i*j') == "a_b_c_d_e_f_g_h_i_j"
    assert safe_name("plain name 01") == "plain name 01"


def test_cjk_survives_intact():
    """The archive is full of Chinese titles and an editor has to recognise
    their own folder. Sanitising more than Windows forbids is how a shoot
    becomes unfindable to the person who named it."""
    assert safe_name("廈門堵車現場") == "廈門堵車現場"


def test_a_long_name_is_truncated_not_dropped():
    """Windows MAX_PATH is 260 and three clips failed the indexer's first build
    outright (WinError 123) once the archive root was prepended. A shortened
    title still identifies the clip; the DB holds the full one."""
    long_name = "x" * (MAX_STEM + 40)
    assert len(safe_name(long_name)) == MAX_STEM
    assert safe_name("y" * 200, cap=10) == "y" * 10


def test_trailing_dots_and_spaces_go_and_an_empty_name_still_gets_one():
    # Windows cannot store either; a name is not optional.
    assert safe_name("clip. ") == "clip"
    assert safe_name("...") == "untitled"
    assert safe_name("") == "untitled"


def test_the_claim_key_folds_a_clip_and_its_proxy_onto_one_name():
    """Per stem, not per full path (BROLL-IDX-5): keying on the whole path let
    `<folder>/name.mov` (free) and `<folder>/Proxy/name_2.mp4` (taken) diverge,
    which is how a newcomer landed on top of a published clip's original."""
    assert claim_key("Creators_Club/shoot", "A001") == "creators_club/shoot/a001"
    assert claim_key("F", "Name") == claim_key("f", "name")


def test_the_first_claim_keeps_the_plain_name():
    taken: set[str] = set()
    assert claim_name("dir", "A001", taken) == "A001"


def test_a_collision_becomes_underscore_two_then_three():
    taken: set[str] = set()
    assert claim_name("dir", "A001", taken) == "A001"
    assert claim_name("dir", "A001", taken) == "A001_2"
    assert claim_name("dir", "A001", taken) == "A001_3"


def test_the_same_name_in_another_folder_is_not_a_collision():
    taken: set[str] = set()
    assert claim_name("dir/one", "A001", taken) == "A001"
    assert claim_name("dir/two", "A001", taken) == "A001"


def test_claim_name_mutates_the_set_so_one_batch_cannot_double_claim():
    """The allocator's whole job inside one claim transaction: item 2 must see
    what item 1 took, or two clips of one drop would upload to one path."""
    taken: set[str] = set()
    claim_name("dir", "A001", taken)
    assert claim_key("dir", "A001") in taken


def test_split_stem_never_eats_a_leading_dot():
    """os.path.splitext calls `.hidden` an extension, which would hand
    claim_name an empty stem and produce a file called `_2.hidden`. A camera
    never writes such a name; a drop is whatever the editor's disk holds."""
    assert split_stem("A001_C003.MP4") == ("A001_C003", ".MP4")
    assert split_stem("no_extension") == ("no_extension", "")
    assert split_stem(".hidden") == (".hidden", "")
    assert split_stem("two.dots.mov") == ("two.dots", ".mov")


# --- parity with the indexer -------------------------------------------------

def _load_build_archive():
    """Load build_archive.py by path, or skip.

    It imports broll_index.config (PyYAML) and broll_index.inplace_fixes, so it
    only loads where the indexer's dependencies are installed -- which is the
    base rig, not the container and not necessarily CI. Skipping is honest
    here: the tests above re-state every rule, and server/tests has its own
    cross-component half.
    """
    if not BUILD_ARCHIVE.exists():
        pytest.skip("the indexer is not in this checkout")
    # APPENDED, never inserted: broll/web's own tree has to keep winning the
    # name `app`, and broll/indexer has a `tests` package of its own that must
    # not shadow this one.
    indexer_dir = str(BUILD_ARCHIVE.parent)
    if indexer_dir not in sys.path:
        sys.path.append(indexer_dir)
    spec = importlib.util.spec_from_file_location("_build_archive_parity", BUILD_ARCHIVE)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001 - a missing indexer dep, not a failure
        pytest.skip(f"build_archive.py is not importable here ({exc})")
    return module


@pytest.mark.parametrize("name", [
    "A001_C003_0812AB", "廈門堵車現場處理事故", 'bad<>:"/\\|?*name', "trailing. ",
    "", "x" * 300, "two.dots",
])
def test_safe_name_matches_the_indexers(name):
    indexer = _load_build_archive()
    assert safe_name(name) == indexer.safe_name(name)
    assert MAX_STEM == indexer.MAX_STEM


def test_claim_name_matches_the_indexers_for_a_run_of_collisions():
    indexer = _load_build_archive()
    mine: set[str] = set()
    theirs: set[str] = set()
    for _ in range(5):
        assert (claim_name("Creators_Club/shoot", "A001", mine)
                == indexer.claim_name("Creators_Club/shoot", "A001", theirs))
    assert mine == theirs


def test_claim_key_matches_the_indexers():
    indexer = _load_build_archive()
    assert claim_key("Dir/Sub", "Stem") == indexer.claim_key("Dir/Sub", "Stem")
