"""Path classification tests — Windows + posix paths, case-insensitivity."""

from __future__ import annotations

from ccsync_companion.paths import BAD_PREFIX, MISSING, OK, OUT_OF_TREE, classify_path


def _always_true(_path: str) -> bool:
    return True


def _always_false(_path: str) -> bool:
    return False


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


def test_windows_canonical_prefix_missing_locally_is_missing_not_bad_prefix():
    # THE designed steady state on a remote editor rig: lane A is
    # upload-only, so Resolve's "P:\Projects\..." video original
    # legitimately lives only on the NAS and was never downloaded here.
    # This must NOT warn -- see AUDIT.md §5's BAD_PREFIX-storm finding
    # (a 400-clip project would otherwise fire 400 tray notifications on a
    # perfectly healthy install).
    result = classify_path(
        r"P:\Projects\2025\FF4\Nuclear\B-roll\clip.mov",
        local_root=r"C:\Creators_Club",
        canonical_prefix="P:\\",
        exists_fn=_always_false,
        is_windows=True,
    )
    assert result == MISSING


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


def test_posix_canonical_prefix_missing_locally_is_missing_not_bad_prefix():
    # Same steady-state case as the Windows equivalent above: a Mapped
    # Mount path that simply isn't downloaded yet must not warn.
    result = classify_path(
        "/Volumes/CreatorsClub/Projects/clip.mov",
        local_root="/Users/jane/Creators_Club",
        canonical_prefix="/Volumes/CreatorsClub",
        exists_fn=_always_false,
        is_windows=False,
    )
    assert result == MISSING


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
