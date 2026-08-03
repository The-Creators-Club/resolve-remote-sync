"""canon tests — the canonical-vs-local spelling matrix, from either host.

The host seam is canon's own `os` reference: `posix_host` swaps it for a
namespace whose `.path` is posixpath, which is exactly what a macOS editor
sees (os.path IS ntpath on Windows, so the default fixture-free tests are the
Windows host). Nothing here touches the filesystem.
"""

from __future__ import annotations

import ntpath
import os
import posixpath
import types

import pytest

from ccsync_companion import canon

WIN_HOST = os.name == "nt"

# A macOS editor: no P: drive, the tree at local_root, the prefix still "P:\".
MAC_ROOT = "/Volumes/T7/Creators_Club"
CANON = "P:\\"
CLIP = r"P:\Projects\2026\CCT\Panel\A001_C061.braw"


@pytest.fixture
def posix_host(monkeypatch):
    """Make canon believe the host is posix (macOS editor)."""
    monkeypatch.setattr(canon, "os", types.SimpleNamespace(path=posixpath))


# -- is_drive_style -----------------------------------------------------------


@pytest.mark.parametrize("prefix", ["P:", "P:\\", "P:/", "p:\\", " P:\\ ", "T:/"])
def test_bare_drive_roots_are_drive_style(prefix):
    assert canon.is_drive_style(prefix) is True


@pytest.mark.parametrize(
    "prefix",
    ["", None, "P:\\Projects", "T:\\Creators_Club", "/Volumes/CreatorsClub", "\\\\nas\\share"],
)
def test_everything_else_is_not_drive_style(prefix):
    assert canon.is_drive_style(prefix) is False


# -- plat_for -----------------------------------------------------------------


@pytest.mark.parametrize("text", ["P:\\", "P:", r"P:\Projects\x", "p:/projects/x", r"a\b"])
def test_windows_spellings_get_ntpath_on_any_host(text, posix_host):
    # THE point of the module: on a posix host posixpath.normcase is a no-op,
    # so "P:\X" and "p:/x" would not compare equal and dirname would answer
    # the whole string.
    assert canon.plat_for(text) is ntpath


def test_posix_spellings_get_the_host_module(posix_host):
    assert canon.plat_for("/Volumes/CreatorsClub/x") is posixpath


def test_posix_spellings_get_ntpath_on_windows():
    # os.path IS ntpath here -- Windows behavior is untouched.
    assert canon.plat_for("/Volumes/CreatorsClub/x") is os.path


# -- is_canonical -------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        r"P:\Projects\2026\x.braw",
        "p:/projects/2026/x.braw",
        "P:/Projects/2026/x.braw",
        r"p:\PROJECTS\x.braw",
        "P:\\",
    ],
)
def test_every_spelling_of_the_canonical_prefix_is_canonical(path, posix_host):
    assert canon.is_canonical(path, CANON) is True
    assert canon.is_canonical(path, "P:") is True


@pytest.mark.parametrize(
    "path",
    [r"Q:\Projects\x.braw", "/Volumes/T7/Creators_Club/Projects/x.braw", "", "PP:\\x",
     "P:"],  # drive-RELATIVE: "P:" names the CWD on P:, not its root
)
def test_other_paths_are_not_canonical(path, posix_host):
    assert canon.is_canonical(path, CANON) is False


def test_no_prefix_is_never_canonical():
    assert canon.is_canonical(CLIP, "") is False
    assert canon.is_canonical(CLIP, None) is False


def test_a_sibling_directory_is_not_under_a_deep_prefix(posix_host):
    # Naive startswith would call "T:\Creators_ClubExtra" a member of
    # "T:\Creators_Club".
    assert canon.is_canonical(r"T:\Creators_Club\a.mov", r"T:\Creators_Club") is True
    assert canon.is_canonical(r"T:\Creators_ClubExtra\a.mov", r"T:\Creators_Club") is False


def test_posix_canonical_prefix_still_works(posix_host):
    assert canon.is_canonical("/Volumes/CC/Projects/a.mov", "/Volumes/CC") is True
    assert canon.is_canonical("/Volumes/CCExtra/a.mov", "/Volumes/CC") is False


# -- canonical_to_local -------------------------------------------------------


def test_canonical_translates_to_the_local_tree_on_a_mac(posix_host):
    assert canon.canonical_to_local(CLIP, MAC_ROOT, CANON) == \
        MAC_ROOT + "/Projects/2026/CCT/Panel/A001_C061.braw"


def test_case_and_separator_variants_translate_too(posix_host):
    # Case is folded for the MEMBERSHIP test but preserved in the result --
    # the probe may land on a case-sensitive volume.
    assert canon.canonical_to_local("p:/projects/2026/a.braw", MAC_ROOT, CANON) == \
        MAC_ROOT + "/projects/2026/a.braw"


@pytest.mark.parametrize("prefix", ["P:", "P:\\", "P:/"])
def test_trailing_separator_variants_of_the_prefix_agree(prefix, posix_host):
    assert canon.canonical_to_local(CLIP, MAC_ROOT, prefix) == \
        MAC_ROOT + "/Projects/2026/CCT/Panel/A001_C061.braw"


@pytest.mark.parametrize("root", [MAC_ROOT, MAC_ROOT + "/"])
def test_trailing_separator_on_local_root_is_absorbed(root, posix_host):
    assert canon.canonical_to_local(CLIP, root, CANON) == \
        MAC_ROOT + "/Projects/2026/CCT/Panel/A001_C061.braw"


def test_canonical_translates_on_windows_too():
    assert canon.canonical_to_local(CLIP, r"F:\Creators_Club", CANON) == \
        r"F:\Creators_Club\Projects\2026\CCT\Panel\A001_C061.braw"


def test_a_path_that_is_not_canonical_translates_to_none(posix_host):
    assert canon.canonical_to_local("/Volumes/T7/Creators_Club/x.braw", MAC_ROOT, CANON) is None
    assert canon.canonical_to_local(r"Q:\x.braw", MAC_ROOT, CANON) is None


def test_missing_roots_translate_to_none(posix_host):
    assert canon.canonical_to_local(CLIP, "", CANON) is None
    assert canon.canonical_to_local(CLIP, MAC_ROOT, "") is None
    assert canon.canonical_to_local("", MAC_ROOT, CANON) is None


def test_the_prefix_itself_translates_to_the_root(posix_host):
    assert canon.canonical_to_local("P:\\", MAC_ROOT, CANON) == MAC_ROOT


@pytest.mark.skipif(not WIN_HOST, reason="drive-rooted local_root is a Windows shape")
def test_base_rig_identity_never_produces_a_drive_relative_path():
    # rstripping "P:\" to "P:" would make os.path.join answer the
    # DRIVE-RELATIVE "P:Projects\x" -- a different directory entirely.
    assert canon.canonical_to_local(CLIP, "P:\\", "P:\\") == CLIP


# -- local_to_canonical -------------------------------------------------------


def test_local_file_is_emitted_in_all_backslash_canonical_spelling(posix_host):
    got = canon.local_to_canonical(
        MAC_ROOT + "/Projects/2026/CCT/Panel/A001_C061.braw", MAC_ROOT, CANON
    )
    assert got == CLIP
    assert "/" not in got  # a mixed P:\Projects/2026 travels to the whole fleet


@pytest.mark.parametrize("prefix", ["P:", "P:\\", "P:/"])
def test_prefix_trailing_separator_variants_emit_the_same_canonical_path(prefix, posix_host):
    got = canon.local_to_canonical(MAC_ROOT + "/Projects/a.braw", MAC_ROOT, prefix)
    assert got == r"P:\Projects\a.braw"


def test_local_to_canonical_on_windows_matches_the_old_join():
    got = canon.local_to_canonical(r"F:\Creators_Club\B-roll\clip.mov", r"F:\Creators_Club", CANON)
    assert got == r"P:\B-roll\clip.mov"


def test_a_file_outside_local_root_keeps_its_physical_path(posix_host):
    outside = "/Users/jane/Desktop/clip.mov"
    assert canon.local_to_canonical(outside, MAC_ROOT, CANON) == outside


def test_local_root_itself_keeps_its_physical_path(posix_host):
    assert canon.local_to_canonical(MAC_ROOT, MAC_ROOT, CANON) == MAC_ROOT


def test_no_prefix_configured_keeps_the_physical_path(posix_host):
    physical = MAC_ROOT + "/Projects/a.braw"
    assert canon.local_to_canonical(physical, MAC_ROOT, "") == physical
    assert canon.local_to_canonical(physical, MAC_ROOT, None) == physical


def test_base_rig_identity_is_the_identity(posix_host):
    physical = MAC_ROOT + "/Projects/a.braw"
    assert canon.local_to_canonical(physical, MAC_ROOT, MAC_ROOT) == physical


@pytest.mark.skipif(not WIN_HOST, reason="P:\\ as local_root is the Windows base rig")
def test_windows_base_rig_identity_is_the_identity():
    assert canon.local_to_canonical(r"P:\Projects\a.braw", "P:\\", "P:\\") == r"P:\Projects\a.braw"


def test_a_posix_canonical_prefix_stays_posix_spelled(posix_host):
    got = canon.local_to_canonical(
        "/Users/jane/Creators_Club/Projects/a.braw", "/Users/jane/Creators_Club", "/Volumes/CC"
    )
    assert got == "/Volumes/CC/Projects/a.braw"


def test_round_trip_through_both_directions_is_stable(posix_host):
    physical = MAC_ROOT + "/Projects/2026/CCT/Panel/A001_C061.braw"
    canonical = canon.local_to_canonical(physical, MAC_ROOT, CANON)
    assert canonical == CLIP
    assert canon.canonical_to_local(canonical, MAC_ROOT, CANON) == physical


def test_a_different_drive_is_not_under_local_root():
    # os.path.relpath raises ValueError across drives on Windows.
    assert canon.local_to_canonical(r"G:\Temp\x.braw", r"F:\Creators_Club", CANON) == \
        r"G:\Temp\x.braw"
