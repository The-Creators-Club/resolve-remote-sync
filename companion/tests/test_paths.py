"""Path classification tests — Windows + posix paths, case-insensitivity."""

from __future__ import annotations

import os

import pytest

from ccsync_companion.paths import (
    BAD_PREFIX,
    MISSING,
    OK,
    OUT_OF_TREE,
    classify_path,
    clear_prefix_cache,
)


@pytest.fixture(autouse=True)
def _fresh_prefix_cache():
    """classify_path memoises the prefix probe for a couple of seconds (one
    realpath per poll, not per clip) -- tests must not inherit each other's."""
    clear_prefix_cache()
    yield
    clear_prefix_cache()


def _always_true(_path: str) -> bool:
    return True


def _always_false(_path: str) -> bool:
    return False


def _subst_p_to_creators_club(path: str) -> str:
    """What realpath() returns on a machine where `subst P: C:\\Creators_Club`
    actually ran."""
    return path.replace("P:\\", "C:\\Creators_Club\\")


def _mapped_mount_to_home(path: str) -> str:
    return path.replace("/Volumes/CreatorsClub", "/Users/jane/Creators_Club")


# -- Windows-style paths -----------------------------------------------


def test_windows_ok_under_local_root():
    result = classify_path(
        r"C:\Creators_Club\B-roll\clip.mov",
        local_root=r"C:\Creators_Club",
        canonical_prefix="P:\\",
        is_windows=True,
    )
    assert result == OK


def test_windows_ok_case_insensitive():
    result = classify_path(
        r"c:\CREATORS_CLUB\b-roll\CLIP.MOV",
        local_root=r"C:\Creators_Club",
        canonical_prefix="P:\\",
        is_windows=True,
    )
    assert result == OK


def test_windows_ok_forward_slash_variant():
    # A stray forward-slash path should still normalize the same as native
    # backslashes on Windows (ntpath treats both as separators).
    result = classify_path(
        "C:/Creators_Club/B-roll/clip.mov",
        local_root=r"C:\Creators_Club",
        canonical_prefix="P:\\",
        is_windows=True,
    )
    assert result == OK


def test_windows_out_of_tree_when_exists():
    result = classify_path(
        r"C:\Users\alex\Desktop\clip.mov",
        local_root=r"C:\Creators_Club",
        canonical_prefix="P:\\",
        exists_fn=_always_true,
        is_windows=True,
    )
    assert result == OUT_OF_TREE


def test_windows_canonical_prefix_missing_locally_is_missing_when_the_prefix_resolves():
    # THE designed steady state on a remote editor rig: lane A is
    # upload-only, so Resolve's "P:\Projects\..." video original
    # legitimately lives only on the NAS and was never downloaded here.
    # This must NOT warn -- see AUDIT.md §5's BAD_PREFIX-storm finding
    # (a 400-clip project would otherwise fire 400 tray notifications on a
    # perfectly healthy install). What makes it healthy is that `subst P:`
    # DID run: the prefix resolves under local_root.
    result = classify_path(
        r"P:\Projects\2025\FF4\Nuclear\B-roll\clip.mov",
        local_root=r"C:\Creators_Club",
        canonical_prefix="P:\\",
        exists_fn=_always_false,
        is_windows=True,
        realpath_fn=_subst_p_to_creators_club,
    )
    assert result == MISSING


def test_windows_unmapped_prefix_warns_even_though_the_file_is_absent():
    """AUDIT_2 L-15 [REGRESSION]: round 1 made this return MISSING whenever
    the FILE was absent, regardless of whether the PREFIX resolved -- which
    silently deleted SPEC component 2's mapping-health warning for its
    primary failure mode (`subst P:` never ran at login / the Mac Mapped
    Mount is unset). Every clip then classified MISSING: zero warnings, zero
    tray notifications, every clip offline, nothing above debug in the log."""
    result = classify_path(
        r"P:\Projects\2025\FF4\Nuclear\B-roll\clip.mov",
        local_root=r"C:\Creators_Club",
        canonical_prefix="P:\\",
        exists_fn=_always_false,
        is_windows=True,
        realpath_fn=lambda p: p,  # no subst in place: P:\ resolves to itself
    )
    assert result == BAD_PREFIX


def test_prefix_probe_is_cached_so_it_costs_one_realpath_per_poll():
    """A 400-clip timeline must not mean 400 realpath() syscalls."""
    calls = []

    def counting_realpath(p):
        calls.append(p)
        return r"C:\Creators_Club"

    for i in range(50):
        classify_path(
            rf"P:\Projects\clip{i}.mov",
            local_root=r"C:\Creators_Club",
            canonical_prefix="P:\\",
            exists_fn=_always_false,
            is_windows=True,
            realpath_fn=counting_realpath,
        )
    assert len(calls) == 1
    assert calls == ["P:\\"]  # the PREFIX is probed, never the per-clip path


def test_windows_bad_prefix_takes_priority_even_if_file_exists():
    # If P: happens to be mapped to something else entirely (not local_root)
    # and a file really does exist there, it's still a mapping-health
    # warning, not a plain OUT_OF_TREE popup candidate.
    result = classify_path(
        r"P:\Projects\clip.mov",
        local_root=r"C:\Creators_Club",
        canonical_prefix="P:\\",
        exists_fn=_always_true,
        is_windows=True,
    )
    assert result == BAD_PREFIX


def test_windows_canonical_prefix_ok_when_subst_resolves_under_root():
    # subst P: C:\Creators_Club -> realpath(P:\Projects\clip.mov) lands under
    # local_root: this is the healthy editor state, NOT a mapping warning.
    result = classify_path(
        r"P:\Projects\clip.mov",
        local_root=r"C:\Creators_Club",
        canonical_prefix="P:\\",
        exists_fn=_always_true,
        is_windows=True,
        realpath_fn=lambda p: p.replace("P:\\", "C:\\Creators_Club\\"),
    )
    assert result == OK


def test_windows_missing_when_nowhere_and_nonexistent():
    result = classify_path(
        r"D:\Old Footage\clip.mov",
        local_root=r"C:\Creators_Club",
        canonical_prefix="P:\\",
        exists_fn=_always_false,
        is_windows=True,
    )
    assert result == MISSING


def test_windows_root_itself_is_ok():
    result = classify_path(
        r"C:\Creators_Club",
        local_root=r"C:\Creators_Club",
        canonical_prefix="P:\\",
        is_windows=True,
    )
    assert result == OK


def test_windows_similar_prefix_sibling_dir_is_not_ok():
    # "C:\Creators_ClubExtra\..." must NOT be treated as under
    # "C:\Creators_Club" just because of a naive startswith on the raw
    # string (this is why classify_path appends the separator before
    # comparing).
    result = classify_path(
        r"C:\Creators_ClubExtra\clip.mov",
        local_root=r"C:\Creators_Club",
        canonical_prefix="P:\\",
        exists_fn=_always_true,
        is_windows=True,
    )
    assert result == OUT_OF_TREE


# -- posix-style paths (macOS editors) -----------------------------------


def test_posix_ok_under_local_root():
    result = classify_path(
        "/Users/jane/Creators_Club/B-roll/clip.mov",
        local_root="/Users/jane/Creators_Club",
        canonical_prefix="/Volumes/CreatorsClub",
        is_windows=False,
    )
    assert result == OK


def test_posix_out_of_tree_when_exists():
    result = classify_path(
        "/Users/jane/Desktop/clip.mov",
        local_root="/Users/jane/Creators_Club",
        canonical_prefix="/Volumes/CreatorsClub",
        exists_fn=_always_true,
        is_windows=False,
    )
    assert result == OUT_OF_TREE


def test_posix_canonical_prefix_missing_locally_is_missing_when_the_mount_resolves():
    # Same steady-state case as the Windows equivalent above: a Mapped
    # Mount path that simply isn't downloaded yet must not warn -- provided
    # the mount itself resolves under local_root.
    result = classify_path(
        "/Volumes/CreatorsClub/Projects/clip.mov",
        local_root="/Users/jane/Creators_Club",
        canonical_prefix="/Volumes/CreatorsClub",
        exists_fn=_always_false,
        is_windows=False,
        realpath_fn=_mapped_mount_to_home,
    )
    assert result == MISSING


def test_posix_unset_mapped_mount_warns_even_though_the_file_is_absent():
    # SPEC.md flaw #7: Mapped Mount on Mac is a manual Resolve preference,
    # so "nobody set it" is the expected failure -- and it must warn.
    result = classify_path(
        "/Volumes/CreatorsClub/Projects/clip.mov",
        local_root="/Users/jane/Creators_Club",
        canonical_prefix="/Volumes/CreatorsClub",
        exists_fn=_always_false,
        is_windows=False,
        realpath_fn=lambda p: p,
    )
    assert result == BAD_PREFIX


def test_posix_bad_prefix_mapped_mount_resolves_elsewhere():
    # SPEC.md flaw #7: Mapped Mount on Mac is a manual Resolve preference.
    # Here the mount DOES exist but resolves to somewhere other than
    # local_root -- that is still a genuine, detectable mapping break.
    result = classify_path(
        "/Volumes/CreatorsClub/Projects/clip.mov",
        local_root="/Users/jane/Creators_Club",
        canonical_prefix="/Volumes/CreatorsClub",
        exists_fn=_always_true,
        is_windows=False,
        realpath_fn=lambda p: p,  # no subst-equivalent resolution on this mount
    )
    assert result == BAD_PREFIX


# -- misc -----------------------------------------------------------


def test_empty_path_is_missing():
    assert classify_path("", local_root=r"C:\Creators_Club", canonical_prefix="P:\\") == MISSING


def test_local_root_missing_from_config_never_false_positive_ok():
    # If local_root is unset/empty, nothing should classify as OK.
    result = classify_path(
        r"C:\Creators_Club\clip.mov",
        local_root="",
        canonical_prefix="P:\\",
        exists_fn=_always_true,
        is_windows=True,
    )
    assert result == OUT_OF_TREE


def test_base_rig_stray_nas_media_is_out_of_tree():
    """Base rig: local_root and canonical_prefix are BOTH the tree root on
    the NAS drive, so media elsewhere on the same drive (Temp Transfer,
    homes) must classify as OUT_OF_TREE (popup), not BAD_PREFIX (warning)."""
    kwargs = dict(
        local_root="T:\\Creators_Club",
        canonical_prefix="T:\\Creators_Club",
        exists_fn=lambda p: True,
        is_windows=True,
    )
    assert classify_path("T:\\Creators_Club\\Projects\\2025\\FF4\\Nuclear\\a.wav", **kwargs) == OK
    assert classify_path("T:\\Temp Transfer\\Creators Club\\x.braw", **kwargs) == OUT_OF_TREE
    assert classify_path("G:\\Temp Transfer\\y.braw", **kwargs) == OUT_OF_TREE
    assert classify_path("C:\\Users\\alex\\Downloads\\z.mp4", **kwargs) == OUT_OF_TREE


# -- macOS editors: a canonical P:\ prefix on a posix host ------------------
#
# There is no P: drive on a Mac: Resolve reaches the canonical path through
# its Mapped Mount preference while the tree physically sits at local_root.
# So os.path.exists("P:\\Projects\\x") is False on every Mac, healthy or
# broken, and realpath("P:\\") resolves RELATIVE TO THE CWD -- the probe has
# to go through the local twin and the prefix health has to come from the
# tree being present. is_windows=False is the seam (the same one the posix
# tests above use); the local twin is built with the HOST separator, so the
# exists_fn below is spelling-tolerant.

MAC_ROOT = "/Volumes/T7/Creators_Club"
MAC_CLIP = r"P:\Projects\2026\CCT\Panel\A001_C061.braw"
MAC_TWIN = MAC_ROOT + "/Projects/2026/CCT/Panel/A001_C061.braw"


def _exists_only(*present):
    wanted = {p.lower().replace("\\", "/") for p in present}

    def _exists(path):
        return str(path).lower().replace("\\", "/") in wanted

    return _exists


def _mac(path, **kwargs):
    kwargs.setdefault("exists_fn", _exists_only())
    kwargs.setdefault("root_present_fn", lambda _root: True)
    return classify_path(
        path, local_root=MAC_ROOT, canonical_prefix="P:\\", is_windows=False, **kwargs
    )


def test_mac_canonical_clip_present_in_the_local_tree_is_ok():
    """Without the local-twin probe every clip on a healthy Mac misclassifies:
    nothing can stat "P:\\Projects\\..." there."""
    assert _mac(MAC_CLIP, exists_fn=_exists_only(MAC_TWIN)) == OK


def test_mac_case_and_separator_variants_are_ok_too():
    assert _mac("p:/projects/2026/cct/panel/a001_c061.braw",
                exists_fn=_exists_only(MAC_TWIN)) == OK


def test_mac_canonical_clip_not_downloaded_yet_is_missing_when_the_tree_is_there():
    # The designed steady state: lane A is upload-only, so the original lives
    # on the NAS only. Must not warn.
    assert _mac(MAC_CLIP) == MISSING


def test_mac_canonical_clip_with_the_tree_absent_is_a_mapping_warning():
    # The drive that holds the tree isn't mounted (the T7 is unplugged) --
    # THE macOS equivalent of `subst P:` never running at login.
    assert _mac(MAC_CLIP, root_present_fn=lambda _root: False) == BAD_PREFIX


def test_mac_prefix_health_never_calls_realpath():
    """realpath("P:\\") on posix answers something CWD-relative: either a
    BAD_PREFIX storm or, if it raises, a permanently masked breakage."""
    calls = []

    assert _mac(MAC_CLIP, realpath_fn=lambda p: calls.append(p) or p) == MISSING
    assert calls == []


def test_mac_prefix_health_probe_is_cached_like_the_windows_one():
    calls = []

    def counting_isdir(root):
        calls.append(root)
        return True

    for i in range(50):
        classify_path(
            rf"P:\Projects\clip{i}.braw",
            local_root=MAC_ROOT,
            canonical_prefix="P:\\",
            exists_fn=_exists_only(),
            is_windows=False,
            root_present_fn=counting_isdir,
        )
    assert len(calls) == 1


def test_mac_local_root_spelling_is_still_ok():
    assert _mac(MAC_TWIN) == OK


def test_mac_media_outside_the_tree_is_still_a_popup_candidate():
    assert _mac("/Users/jane/Desktop/clip.mov", exists_fn=lambda _p: True) == OUT_OF_TREE


def test_mac_base_rig_identity_prefix_is_untouched():
    """A posix canonical prefix (prefix == local_root, or a real mount point)
    keeps the realpath-based probe -- only the drive-style P:\\ case changes."""
    calls = []
    got = classify_path(
        "/Volumes/CreatorsClub/Projects/clip.mov",
        local_root="/Users/jane/Creators_Club",
        canonical_prefix="/Volumes/CreatorsClub",
        exists_fn=_always_false,
        is_windows=False,
        realpath_fn=lambda p: calls.append(p) or _mapped_mount_to_home(p),
    )
    assert got == MISSING
    assert calls == ["/Volumes/CreatorsClub"]


# -- loopback-share P: (the 0.4.10 canonical relinks, 2026-07-26) ----------


@pytest.mark.skipif(
    os.name != "nt",
    reason="a loopback SMB share mapped to a drive letter is a Windows-only "
           "mechanism -- _delooped returns early on any other host by design",
)
def test_delooped_translates_localhost_share(monkeypatch):
    from ccsync_companion import paths

    monkeypatch.setattr(paths, "_local_share_target",
                        lambda share: r"D:\Creators_Club" if share == "CCSync_P" else None)
    assert paths._delooped("\\\\localhost\\CCSync_P\\Projects\\x.mp4") == \
        r"D:\Creators_Club\Projects\x.mp4"
    # remote hosts and non-UNC paths come back unchanged
    assert paths._delooped("\\\\NAS\\Share\\x.mp4") == "\\\\NAS\\Share\\x.mp4"
    assert paths._delooped(r"D:\x.mp4") == r"D:\x.mp4"


def test_canonical_clip_on_loopback_share_is_ok_not_bad_prefix(monkeypatch):
    r"""An editor's P: is a loopback SHARE (\\localhost\CCSync_P ->
    local_root), so realpath answers UNC -- which is local_root in disguise.
    Every canonically-relinked clip read as BAD_PREFIX until translated."""
    from ccsync_companion import paths

    paths.clear_prefix_cache()
    monkeypatch.setattr(paths, "_local_share_target",
                        lambda share: r"D:\Creators_Club")
    monkeypatch.setattr(paths.os, "name", "nt")

    got = paths.classify_path(
        r"P:\Projects\2026\CCT\X\clip.mp4",
        local_root=r"D:\Creators_Club",
        canonical_prefix="P:\\",
        exists_fn=lambda p: True,
        is_windows=True,
        realpath_fn=lambda p: p.replace("P:\\", "\\\\localhost\\CCSync_P\\", 1),
    )
    paths.clear_prefix_cache()
    assert got == paths.OK


def test_missing_canonical_clip_on_healthy_loopback_share_is_missing(monkeypatch):
    from ccsync_companion import paths

    paths.clear_prefix_cache()
    monkeypatch.setattr(paths, "_local_share_target",
                        lambda share: r"D:\Creators_Club")
    monkeypatch.setattr(paths.os, "name", "nt")

    got = paths.classify_path(
        r"P:\Projects\2026\CCT\X\not-downloaded.braw",
        local_root=r"D:\Creators_Club",
        canonical_prefix="P:\\",
        exists_fn=lambda p: False,
        is_windows=True,
        realpath_fn=lambda p: p.replace("P:\\", "\\\\localhost\\CCSync_P\\", 1),
    )
    paths.clear_prefix_cache()
    assert got == paths.MISSING          # healthy mapping, file just not local
