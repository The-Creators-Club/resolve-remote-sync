"""Path translation for the b-roll insert endpoint: both OS styles, traversal
rejection, macOS /Volumes probing.

Ported verbatim (module path aside) from the retired standalone
broll-companion's tests/test_paths.py — this is contract, not implementation
detail: the traversal rejection is the only reason a loopback server with
`Access-Control-Allow-Origin: *` can be handed a client-supplied path at all.
"""

from __future__ import annotations

import os

import pytest

from ccsync_companion.broll_server import (
    MountNotConfiguredError,
    PathTraversalError,
    probe_darwin_mount,
    translate_path,
)


def test_windows_style_join():
    mounts = {"broll": "Y:/broll"}
    result = translate_path(
        "broll", "military/naval/clip_0021.mov", mounts, platform="win32"
    )
    assert result == "Y:\\broll\\military\\naval\\clip_0021.mov"


def test_windows_style_join_with_backslash_root():
    mounts = {"broll": "B:\\"}
    result = translate_path("broll", "clip.mov", mounts, platform="win32")
    assert result == "B:\\clip.mov"


def test_mac_style_join_configured_mount():
    mounts = {"broll": "/Volumes/broll"}
    result = translate_path(
        "broll", "military/naval/clip_0021.mov", mounts, platform="darwin"
    )
    assert result == "/Volumes/broll/military/naval/clip_0021.mov"


def test_mac_style_join_trailing_slash_root():
    mounts = {"broll": "/Volumes/broll/"}
    result = translate_path("broll", "clip.mov", mounts, platform="darwin")
    assert result == "/Volumes/broll/clip.mov"


@pytest.mark.parametrize(
    "rel_path",
    [
        "../etc/passwd",
        "military/../../etc/passwd",
        "military/../../../etc/passwd",
        "..",
        "a/b/..",
    ],
)
def test_traversal_rejected(rel_path):
    mounts = {"broll": "Y:/broll"}
    with pytest.raises(PathTraversalError):
        translate_path("broll", rel_path, mounts, platform="win32")


def test_traversal_rejected_even_with_dotdot_in_middle_of_valid_looking_path():
    mounts = {"broll": "/Volumes/broll"}
    with pytest.raises(PathTraversalError):
        translate_path("broll", "military/naval/../../../../etc/passwd", mounts, platform="darwin")


def test_a_drive_letter_smuggled_in_as_a_segment_is_rejected():
    mounts = {"broll": "Y:/broll"}
    with pytest.raises(PathTraversalError):
        translate_path("broll", "C:/Windows/System32/config/SAM", mounts, platform="win32")


def test_empty_rel_path_rejected():
    mounts = {"broll": "Y:/broll"}
    with pytest.raises(PathTraversalError):
        translate_path("broll", "", mounts, platform="win32")


def test_no_mount_configured_windows():
    with pytest.raises(MountNotConfiguredError) as exc_info:
        translate_path("broll", "clip.mov", {}, platform="win32")
    assert "broll" in str(exc_info.value)


def test_no_mount_configured_darwin_when_probe_fails():
    with pytest.raises(MountNotConfiguredError):
        translate_path("broll", "clip.mov", {}, platform="darwin", isdir=lambda p: False)


def test_mac_probe_finds_base_candidate():
    def fake_isdir(path):
        return path == "/Volumes/broll"

    result = translate_path("broll", "clip.mov", {}, platform="darwin", isdir=fake_isdir)
    assert result == "/Volumes/broll/clip.mov"


def test_mac_probe_finds_collision_suffix_candidate():
    def fake_isdir(path):
        return path == "/Volumes/broll-2"

    result = translate_path("broll", "clip.mov", {}, platform="darwin", isdir=fake_isdir)
    assert result == "/Volumes/broll-2/clip.mov"


def test_mac_configured_mount_takes_precedence_over_probe():
    # A configured mount should win even if a probe candidate also exists.
    mounts = {"broll": "/Volumes/other-name"}
    result = translate_path(
        "broll", "clip.mov", mounts, platform="darwin", isdir=lambda p: True
    )
    assert result == "/Volumes/other-name/clip.mov"


def test_mac_probe_with_monkeypatched_os_path_isdir(monkeypatch, tmp_path):
    # Simulate Finder's "-1" collision suffix using monkeypatch on the real
    # os.path.isdir (rather than the explicit isdir= injection), backed by a
    # real tmp dir so the check reflects genuine filesystem semantics.
    real_dir = tmp_path / "broll-1"
    real_dir.mkdir()

    def fake_isdir(path):
        if path == "/Volumes/broll-1":
            return real_dir.is_dir()
        return False

    monkeypatch.setattr(os.path, "isdir", fake_isdir)

    result = translate_path("broll", "clip.mov", {}, platform="darwin")
    assert result == "/Volumes/broll-1/clip.mov"


def test_probe_darwin_mount_directly_no_match():
    assert probe_darwin_mount("broll", isdir=lambda p: False) is None


def test_probe_darwin_mount_directly_match_order():
    # base candidate should be preferred over suffixed ones if both exist
    def fake_isdir(path):
        return path in ("/Volumes/broll", "/Volumes/broll-1")

    assert probe_darwin_mount("broll", isdir=fake_isdir) == "/Volumes/broll"


# ---------------------------------------------------------------------------
# `share` is a path segment too (COMMERCIAL_READINESS.md item 5 / C1)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("share", ["../..", "..", "a/b", "a\\b", ".hidden",
                                   ".", "C:", "bro\x00ll", "bro\nll", "",
                                   " broll", "broll "])
def test_an_unsafe_share_is_never_interpolated_into_a_path(share):
    """`share` is BOTH a mounts key and, on macOS, the tail of
    f"/Volumes/{share}" -- so share="../.." resolved to "/" and served the
    whole filesystem under a route whose contract is one share. It is one safe
    segment or it is refused."""
    assert probe_darwin_mount(share, isdir=lambda p: True) is None
    with pytest.raises(PathTraversalError):
        translate_path(share, "clip.mov", {"broll": "Y:/broll"}, platform="win32")


def test_the_share_rule_applies_on_windows_too():
    """Not a darwin-only guard: the same string is the key of a mounts table
    an editor can hand-edit."""
    with pytest.raises(PathTraversalError):
        translate_path("../secrets", "clip.mov", {"../secrets": "Y:/x"},
                       platform="win32")


def test_a_probed_volume_must_resolve_inside_volumes():
    """A symlink at /Volumes/<share> pointing out of /Volumes passes every
    segment rule there is; only realpath sees it."""
    def escaping_realpath(path):
        return "/private/etc" if path.endswith("/broll") else path

    assert probe_darwin_mount(
        "broll", isdir=lambda p: p == "/Volumes/broll",
        realpath=escaping_realpath,
    ) is None


def test_a_probed_volume_that_stays_inside_volumes_is_served():
    def honest_realpath(path):
        return path

    assert probe_darwin_mount(
        "broll", isdir=lambda p: p == "/Volumes/broll-2",
        realpath=honest_realpath,
    ) == "/Volumes/broll-2"
