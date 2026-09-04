"""Fixer tests: destination suggestion by type, existing-dir listing (Proxy
excluded), collision-safe renaming, and the copy+relink flow (mocked
resolve_bridge / copy_fn — never touches a real Resolve instance)."""

from __future__ import annotations

import logging

import os
import shutil
from pathlib import Path

import pytest

from conftest import write_project_marker

from ccsync_companion import fixer


# -- destination suggestion -----------------------------------------------


@pytest.mark.parametrize(
    "filename,expected",
    [
        ("track.wav", "Audio/Music"),
        ("song.mp3", "Audio/Music"),
        ("voice.aif", "Audio/Music"),
        ("voice.aiff", "Audio/Music"),
        ("loop.flac", "Audio/Music"),
        ("voiceover.m4a", "Audio/Music"),
        ("sfx.ogg", "Audio/Music"),
        ("still.png", "B-roll/Stills"),
        ("still.JPG", "B-roll/Stills"),
        ("still.jpeg", "B-roll/Stills"),
        ("scan.tif", "B-roll/Stills"),
        ("scan.tiff", "B-roll/Stills"),
        ("layered.psd", "B-roll/Stills"),
        ("render.exr", "B-roll/Stills"),
    ],
)
def test_suggest_destination_audio_and_stills(filename, expected):
    assert fixer.suggest_destination(f"C:\\Desktop\\{filename}", "owen") == expected


@pytest.mark.parametrize("filename", ["clip.mov", "clip.mp4", "notes.docx", "weird.xyz"])
def test_suggest_destination_video_and_other_falls_back_to_editor_added(filename):
    assert (
        fixer.suggest_destination(f"C:\\Desktop\\{filename}", "owen")
        == "B-roll/Editor Added/owen"
    )


def test_suggest_destination_unknown_editor_name():
    assert fixer.suggest_destination("clip.mov", "") == "B-roll/Editor Added/Unknown"


# -- destination directory listing -----------------------------------------


def test_list_destination_dirs_includes_defaults_even_if_missing(tmp_path):
    dirs = fixer.list_destination_dirs(str(tmp_path), "owen")
    assert "Audio/Music" in dirs
    assert "B-roll/Stills" in dirs
    assert "B-roll/Editor Added/owen" in dirs


def test_list_destination_dirs_excludes_proxy(tmp_path):
    (tmp_path / "B-roll" / "Proxy").mkdir(parents=True)
    (tmp_path / "B-roll" / "Proxy" / "Nested").mkdir(parents=True)
    (tmp_path / "Interviewees" / "Jane").mkdir(parents=True)
    dirs = fixer.list_destination_dirs(str(tmp_path), "owen")
    assert "Interviewees/Jane" in dirs
    assert not any("proxy" in d.lower() for d in dirs)


def test_list_destination_dirs_uses_forward_slashes(tmp_path):
    (tmp_path / "AE" / "Renders").mkdir(parents=True)
    dirs = fixer.list_destination_dirs(str(tmp_path), "owen")
    assert "AE/Renders" in dirs
    assert not any("\\" in d for d in dirs)


# -- collision-safe destination path ---------------------------------------


def test_unique_destination_path_no_collision(tmp_path):
    result = fixer.unique_destination_path(tmp_path, "clip.mov")
    assert result == tmp_path / "clip.mov"


def test_unique_destination_path_appends_number_on_collision(tmp_path):
    (tmp_path / "clip.mov").write_text("existing")
    result = fixer.unique_destination_path(tmp_path, "clip.mov")
    assert result == tmp_path / "clip (2).mov"


def test_unique_destination_path_increments_past_multiple_collisions(tmp_path):
    (tmp_path / "clip.mov").write_text("a")
    (tmp_path / "clip (2).mov").write_text("b")
    (tmp_path / "clip (3).mov").write_text("c")
    result = fixer.unique_destination_path(tmp_path, "clip.mov")
    assert result == tmp_path / "clip (4).mov"


# -- fix_clip (copy + relink) ----------------------------------------------


class FakeClip:
    """A stand-in MediaPoolItem: an opaque object, deliberately NOT a dict.

    A real MediaPoolItem is a fusionscript object and can never be a dict,
    and since the wave-1 review (2026-08-26) resolve_bridge treats EVERY
    dict as one of its item dicts -- so a `{}` here would be a row with no
    clip in it rather than a clip (resolve_bridge._is_item_dict).
    """

    def __init__(self):
        self.relinked_to = None


def _fake_replace_clip_ok(media_pool_item, new_path):
    media_pool_item.relinked_to = new_path
    return {"ok": True, "message": f"Relinked to {new_path}"}


def _fake_replace_clip_fail(media_pool_item, new_path):
    return {"ok": False, "message": "ReplaceClip returned False"}


def test_fix_clip_copies_and_relinks(tmp_path):
    src = tmp_path / "src" / "clip.mov"
    src.parent.mkdir(parents=True)
    src.write_text("video bytes")
    local_root = tmp_path / "root"
    media_pool_item = FakeClip()

    result = fixer.fix_clip(
        str(src), "B-roll/Editor Added/owen", str(local_root), media_pool_item,
        replace_clip_fn=_fake_replace_clip_ok,
    )

    assert result["ok"] is True
    dest = local_root / "B-roll" / "Editor Added" / "owen" / "clip.mov"
    assert dest.is_file()
    assert dest.read_text() == "video bytes"
    assert src.is_file(), "original must never be deleted/moved"
    assert media_pool_item.relinked_to == str(dest)


def test_fix_clip_collision_renames_copy(tmp_path):
    src = tmp_path / "src" / "clip.mov"
    src.parent.mkdir(parents=True)
    src.write_text("new bytes")
    local_root = tmp_path / "root"
    dest_dir = local_root / "Audio" / "Music"
    dest_dir.mkdir(parents=True)
    (dest_dir / "clip.mov").write_text("pre-existing bytes")

    result = fixer.fix_clip(
        str(src), "Audio/Music", str(local_root), FakeClip(), replace_clip_fn=_fake_replace_clip_ok,
    )

    assert result["ok"] is True
    assert result["copied_to"].endswith("clip (2).mov")
    assert (dest_dir / "clip.mov").read_text() == "pre-existing bytes"
    assert (dest_dir / "clip (2).mov").read_text() == "new bytes"


def test_fix_clip_missing_source_reports_failure_no_crash(tmp_path):
    result = fixer.fix_clip(
        str(tmp_path / "does_not_exist.mov"), "Audio/Music", str(tmp_path), FakeClip(),
    )
    assert result["ok"] is False
    assert "not found" in result["message"]


def test_fix_clip_relink_failure_keeps_copy_and_reports_error(tmp_path):
    src = tmp_path / "src" / "clip.mov"
    src.parent.mkdir(parents=True)
    src.write_text("bytes")
    local_root = tmp_path / "root"

    result = fixer.fix_clip(
        str(src), "Audio/Music", str(local_root), FakeClip(), replace_clip_fn=_fake_replace_clip_fail,
    )

    assert result["ok"] is False
    assert "relink failed" in result["message"]
    dest = local_root / "Audio" / "Music" / "clip.mov"
    assert dest.is_file(), "copy must survive even when ReplaceClip fails"
    assert src.is_file(), "original must never be deleted, even on relink failure"


# -- IgnoreTracker ----------------------------------------------------------


def test_ignore_tracker_is_ignored_and_normalizes_case_on_windows():
    tracker = fixer.IgnoreTracker()
    tracker.ignore(r"C:\Users\owen\Desktop\clip.mov")
    assert tracker.is_ignored(r"c:\USERS\owen\DESKTOP\clip.MOV") is True
    assert tracker.is_ignored(r"C:\Users\owen\Desktop\other.mov") is False


def test_ignore_tracker_clear():
    tracker = fixer.IgnoreTracker()
    tracker.ignore("clip.mov")
    tracker.clear()
    assert tracker.is_ignored("clip.mov") is False


# -- persisted folder ignores + the skip ledger (RES-12 / UX-4) ------------


def test_a_folder_ignore_is_honoured_and_survives_a_restart(tmp_path):
    """RES-12: an editor who keeps a personal stock-footage folder outside
    the tree was offered the same clips at every start for ever, because the
    ignore set died with the process."""
    state = tmp_path / "state"
    tracker = fixer.IgnoreTracker(state)
    assert tracker.ignore_folder(str(tmp_path / "stock"), reason="my own library")
    assert tracker.is_ignored(str(tmp_path / "stock" / "sunset.mov")) is True

    # A "restart": a brand new tracker over the same state dir.
    restarted = fixer.IgnoreTracker(state)
    assert restarted.is_ignored(str(tmp_path / "stock" / "sunset.mov")) is True
    assert restarted.folder_count() == 1
    assert restarted.folders()[0]["reason"] == "my own library"
    assert restarted.folders()[0]["when"]


def test_a_folder_ignore_does_not_catch_a_sibling_with_the_same_prefix(tmp_path):
    """canon._is_under's separator rule: "stock_extra" is not inside
    "stock"."""
    tracker = fixer.IgnoreTracker(tmp_path / "state")
    tracker.ignore_folder(str(tmp_path / "stock"))
    assert tracker.is_ignored(str(tmp_path / "stock_extra" / "clip.mov")) is False


def test_forget_folder_brings_the_clips_back(tmp_path):
    state = tmp_path / "state"
    tracker = fixer.IgnoreTracker(state)
    tracker.ignore_folder(str(tmp_path / "stock"))
    assert tracker.forget_folder(str(tmp_path / "stock")) is True
    assert tracker.is_ignored(str(tmp_path / "stock" / "sunset.mov")) is False
    assert fixer.IgnoreTracker(state).folder_count() == 0
    # A second [ FORGET ] on the same entry says so rather than reporting a
    # success it did not have.
    assert tracker.forget_folder(str(tmp_path / "stock")) is False


def test_a_folder_ignore_that_cannot_be_persisted_is_refused(tmp_path, monkeypatch):
    """"Always" that lasts until the next restart is worse than no button:
    the caller is told, so the editor can be."""
    tracker = fixer.IgnoreTracker(tmp_path / "state")
    monkeypatch.setattr(fixer, "_write_json_atomic", lambda *a, **k: False)
    assert tracker.ignore_folder(str(tmp_path / "stock")) is False
    assert tracker.folder_count() == 0


def test_a_tracker_with_no_state_dir_is_the_old_session_only_behaviour():
    tracker = fixer.IgnoreTracker()
    tracker.ignore("clip.mov")
    assert tracker.is_ignored("clip.mov") is True
    assert tracker.skipped_count() == 0
    assert tracker.ignore_folder("anywhere") is False


def test_skipped_clips_are_recorded_across_a_restart(tmp_path):
    """UX-4: the ledger is a RECORD, not a suppression list. A restart offers
    the clip again (the button says "this session" and means it) -- what
    survives is the COUNT nobody could see before."""
    state = tmp_path / "state"
    tracker = fixer.IgnoreTracker(state)
    tracker.ignore(r"C:\Users\owen\Desktop\clip.mov")
    tracker.ignore(r"C:\Users\owen\Desktop\other.mov", how="headless")
    assert tracker.skipped_count() == 2

    restarted = fixer.IgnoreTracker(state)
    assert restarted.skipped_count() == 2
    assert restarted.session_count() == 0
    assert restarted.is_ignored(r"C:\Users\owen\Desktop\clip.mov") is False


def test_the_skip_ledger_records_how_the_clip_was_skipped(tmp_path):
    state = tmp_path / "state"
    tracker = fixer.IgnoreTracker(state)
    tracker.ignore("/raw/a.mov", how="headless")
    written = fixer._read_json(state / fixer.SKIPPED_CLIPS_FILENAME)["clips"]
    assert [v["how"] for v in written.values()] == ["headless"]


def test_clear_forgets_the_session_but_not_the_folders(tmp_path):
    """APP-2 clears dismissals; RES-12's standing decisions stay."""
    tracker = fixer.IgnoreTracker(tmp_path / "state")
    tracker.ignore("/raw/a.mov")
    tracker.ignore_folder("/stock")
    tracker.clear()
    assert tracker.is_ignored("/raw/a.mov") is False
    assert tracker.is_ignored("/stock/b.mov") is True
    assert tracker.session_count() == 0
    # Cleared from the SESSION, still counted in the ledger: the clip is
    # still not syncing, whatever the tray now offers.
    assert tracker.skipped_count() == 1


def test_a_corrupt_ignore_file_fails_towards_showing_the_clips(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    (state / fixer.FIXER_IGNORES_FILENAME).write_text("{not json", encoding="utf-8")
    tracker = fixer.IgnoreTracker(state)
    assert tracker.folder_count() == 0
    assert tracker.is_ignored("/anything/clip.mov") is False


def test_the_skip_ledger_is_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(fixer, "_MAX_SKIPPED_RECORDED", 3)
    tracker = fixer.IgnoreTracker(tmp_path / "state")
    for n in range(6):
        tracker.ignore(f"/raw/{n}.mov")
    assert tracker.skipped_count() == 3


# -- fix_clip with multiple timeline items sharing one source file ---------


def test_fix_clip_relinks_every_media_pool_item_from_one_copy(tmp_path):
    calls = []

    def fake_replace(mpi, new_path):
        calls.append((mpi, new_path))
        return {"ok": True, "message": "ok"}

    src = tmp_path / "src.mov"
    src.write_text("bytes")
    local_root = tmp_path / "root"

    result = fixer.fix_clip(
        str(src), "Audio/Music", str(local_root), ["mpi-a", "mpi-b", "mpi-c"],
        copy_fn=shutil.copy2, replace_clip_fn=fake_replace,
    )

    assert result["ok"] is True
    assert "3 item(s)" in result["message"]
    assert [c[0] for c in calls] == ["mpi-a", "mpi-b", "mpi-c"]
    # every relink targets the SAME single copy, not three separate copies
    assert len({c[1] for c in calls}) == 1


def test_fix_clip_accepts_single_media_pool_item_back_compat(tmp_path):
    src = tmp_path / "src" / "clip.mov"
    src.parent.mkdir(parents=True)
    src.write_text("video bytes")
    local_root = tmp_path / "root"
    media_pool_item = FakeClip()

    result = fixer.fix_clip(
        str(src), "B-roll/Editor Added/owen", str(local_root), media_pool_item,
        replace_clip_fn=_fake_replace_clip_ok,
    )

    assert result["ok"] is True
    assert media_pool_item.relinked_to is not None


def test_fix_clip_relinks_duplicate_media_pool_items_only_once(tmp_path):
    """AUDIT §6: popup.dedupe_out_of_tree_items collapses timeline
    occurrences by path, so the same underlying MediaPoolItem object can
    appear many times in the list -- ReplaceClip must fire once per
    DISTINCT item, not once per occurrence."""
    calls = []

    def fake_replace(mpi, new_path):
        calls.append(mpi)
        return {"ok": True, "message": "ok"}

    shared = FakeClip()
    other = FakeClip()

    src = tmp_path / "src.mov"
    src.write_text("bytes")
    local_root = tmp_path / "root"

    result = fixer.fix_clip(
        str(src), "Audio/Music", str(local_root),
        [shared, shared, shared, other],
        copy_fn=shutil.copy2, replace_clip_fn=fake_replace,
    )

    assert result["ok"] is True
    assert "2 item(s)" in result["message"]
    assert len(calls) == 2
    assert calls[0] is shared and calls[1] is other


def test_fix_clip_copy_failure_mid_copy_leaves_no_dest_file(tmp_path):
    """AUDIT D-5: a copy that dies partway through (disk full, SMB drop)
    must not leave a truncated file under the final name -- or any stray
    temp file -- in the destination dir."""
    src = tmp_path / "src" / "big.braw"
    src.parent.mkdir(parents=True)
    src.write_text("original bytes")
    local_root = tmp_path / "root"

    def flaky_copy(_src, dst):
        # Simulate a partial write before the failure -- exactly the
        # truncated-file scenario the fix must prevent under the final name.
        Path(dst).write_text("PARTIAL")
        raise OSError("disk full")

    result = fixer.fix_clip(
        str(src), "B-roll/Editor Added/owen", str(local_root), FakeClip(),
        copy_fn=flaky_copy,
    )

    assert result["ok"] is False
    assert result["copied_to"] is None
    dest_dir = local_root / "B-roll" / "Editor Added" / "owen"
    assert not dest_dir.exists() or list(dest_dir.iterdir()) == []
    assert src.is_file(), "original must never be touched"


def test_fix_clip_rejects_absolute_destination(tmp_path):
    local_root = tmp_path / "root"
    local_root.mkdir()
    src = tmp_path / "clip.mov"
    src.write_text("bytes")

    other_drive = "C:\\Windows\\Temp" if os.name == "nt" else "/etc/elsewhere"
    result = fixer.fix_clip(str(src), other_drive, str(local_root), {})

    assert result["ok"] is False
    assert "outside local_root" in result["message"]
    assert result["copied_to"] is None


def test_fix_clip_rejects_drive_relative_leading_slash_destination(tmp_path):
    local_root = tmp_path / "root"
    local_root.mkdir()
    src = tmp_path / "clip.mov"
    src.write_text("bytes")

    result = fixer.fix_clip(str(src), "/Escaped/Dir", str(local_root), {})

    assert result["ok"] is False
    assert "outside local_root" in result["message"]


def test_fix_clip_rejects_parent_traversal_destination(tmp_path):
    local_root = tmp_path / "root"
    local_root.mkdir()
    src = tmp_path / "clip.mov"
    src.write_text("bytes")

    result = fixer.fix_clip(str(src), "../../Elsewhere", str(local_root), {})

    assert result["ok"] is False
    assert "outside local_root" in result["message"]


def test_fix_clip_accepts_normal_relative_destination(tmp_path):
    local_root = tmp_path / "root"
    src = tmp_path / "clip.mov"
    src.write_text("bytes")

    result = fixer.fix_clip(
        str(src), "Audio/Music", str(local_root), FakeClip(), replace_clip_fn=_fake_replace_clip_ok,
    )

    assert result["ok"] is True
    assert (local_root / "Audio" / "Music" / "clip.mov").is_file()


def test_fix_clip_reports_partial_relink_failure(tmp_path):
    def fake_replace(mpi, new_path):
        return {"ok": mpi != "bad", "message": "boom" if mpi == "bad" else "ok"}

    src = tmp_path / "src.mov"
    src.write_text("bytes")
    local_root = tmp_path / "root"

    result = fixer.fix_clip(
        str(src), "Audio/Music", str(local_root), ["good", "bad"],
        copy_fn=shutil.copy2, replace_clip_fn=fake_replace,
    )

    assert result["ok"] is False
    assert "1/2" in result["message"]
    assert result["copied_to"] is not None  # copy survives a partial relink failure


# -- match_project_dir -------------------------------------------------------


def test_match_project_dir_matches_on_token_overlap():
    candidates = ["2026/Creator Profiles/Season 1", "2025/FF4/Nuclear"]
    assert fixer.match_project_dir("CCT Creator Profiles", candidates) == "2026/Creator Profiles/Season 1"


def test_match_project_dir_no_match_returns_none():
    candidates = ["2025/FF4/Nuclear", "2026/Creator Profiles/Season 1"]
    assert fixer.match_project_dir("Totally Unrelated Show", candidates) is None


def test_match_project_dir_tie_returns_none():
    candidates = ["2025/FF4/Nuclear Sunrise", "2026/Other/Nuclear Sunset"]
    # both candidates share exactly one non-year token ("nuclear") with the
    # project name -- equal score, ambiguous, must not guess.
    assert fixer.match_project_dir("Nuclear Project", candidates) is None


def test_match_project_dir_year_only_overlap_does_not_count():
    candidates = ["2025/FF4/Nuclear"]
    # "2025" overlaps, but it's a year token -- not enough to qualify alone.
    assert fixer.match_project_dir("2025 Highlights", candidates) is None


def test_match_project_dir_empty_project_name_returns_none():
    assert fixer.match_project_dir("", ["2026/Creator Profiles/Season 1"]) is None


def test_match_project_dir_empty_candidates_returns_none():
    assert fixer.match_project_dir("CCT Creator Profiles", []) is None


def test_match_project_dir_picks_higher_overlap_over_lower():
    candidates = ["2026/Creator Profiles/Season 1", "2026/Creator/Misc"]
    # "creator profiles season" -> 2 overlapping tokens with the first dir,
    # only 1 ("creator") with the second -- first dir must win outright.
    assert (
        fixer.match_project_dir("Creator Profiles Season 1", candidates)
        == "2026/Creator Profiles/Season 1"
    )


# -- list_project_dirs -------------------------------------------------------


def test_list_project_dirs_scans_year_series_project_layout(tmp_path):
    (tmp_path / "Projects" / "2026" / "Creator Profiles" / "Season 1").mkdir(parents=True)
    write_project_marker(tmp_path / "Projects" / "2026" / "Creator Profiles" / "Season 1")
    (tmp_path / "Projects" / "2025" / "FF4" / "Nuclear").mkdir(parents=True)
    write_project_marker(tmp_path / "Projects" / "2025" / "FF4" / "Nuclear")
    dirs = fixer.list_project_dirs(str(tmp_path))
    assert "2026/Creator Profiles/Season 1" in dirs
    assert "2025/FF4/Nuclear" in dirs


def test_list_project_dirs_tolerates_missing_tree(tmp_path):
    assert fixer.list_project_dirs(str(tmp_path / "does_not_exist")) == []


def test_list_project_dirs_tolerates_blank_local_root():
    assert fixer.list_project_dirs("") == []


# -- pick_project_prefix (fallback order) ------------------------------------


def test_pick_project_prefix_prefers_matched_resolve_project():
    candidates = ["2026/Creator Profiles/Season 1", "2025/FF4/Nuclear"]
    result = fixer.pick_project_prefix(
        "CCT Creator Profiles", candidates, project_prefix="Projects/2025/FF4/Nuclear",
    )
    assert result == "Projects/2026/Creator Profiles/Season 1"


def test_pick_project_prefix_falls_back_to_configured_project_prefix():
    candidates = ["2026/Creator Profiles/Season 1"]
    result = fixer.pick_project_prefix(
        "Unrelated Show", candidates, project_prefix="Projects/2025/FF4/Nuclear",
    )
    assert result == "Projects/2025/FF4/Nuclear"


def test_pick_project_prefix_falls_back_to_tree_root_when_nothing_matches():
    result = fixer.pick_project_prefix("Unrelated Show", [], project_prefix="")
    assert result == ""


def test_match_project_dir_ignores_trivial_numeric_tokens():
    """Regression (2026-07-25, dashboard twin): 'Event 1 Videos' must not
    match '.../Season 1' on the shared bare '1' -- short all-digit tokens
    carry no identity."""
    candidates = ["2025/FF4/Nuclear", "2026/Creator Profiles/Season 1"]
    assert fixer.match_project_dir("Event 1.EXE Videos for Event", candidates) is None
    assert fixer.match_project_dir("Part 2 Cut 1", candidates) is None
    assert fixer.match_project_dir("Season 1 Recap", candidates) == "2026/Creator Profiles/Season 1"


def test_list_project_dirs_marker_at_any_depth(tmp_path):
    deep = tmp_path / "Projects" / "2026" / "CCT" / "Creator Profiles" / "Season 1"
    deep.mkdir(parents=True)
    write_project_marker(deep)
    shallow = tmp_path / "Projects" / "OneOffs"
    shallow.mkdir(parents=True)
    write_project_marker(shallow)
    # bare dir (no marker) is invisible
    (tmp_path / "Projects" / "2026" / "CCT" / "Bare").mkdir(parents=True)

    dirs = fixer.list_project_dirs(str(tmp_path))
    assert dirs == ["2026/CCT/Creator Profiles/Season 1", "OneOffs"]


def test_list_project_dirs_prunes_nested_markers(tmp_path):
    outer = tmp_path / "Projects" / "2026" / "Show"
    inner = outer / "Nested"
    inner.mkdir(parents=True)
    write_project_marker(outer)
    write_project_marker(inner)
    assert fixer.list_project_dirs(str(tmp_path)) == ["2026/Show"]


def test_list_project_dirs_extra_rels_union(tmp_path):
    # selected project whose marker hasn't synced down yet
    d = tmp_path / "Projects" / "2026" / "CCT" / "New Thing"
    d.mkdir(parents=True)
    dirs = fixer.list_project_dirs(str(tmp_path), extra_rels=["2026/CCT/New Thing", "2026/Absent"])
    assert dirs == ["2026/CCT/New Thing"]  # absent extra dropped, existing bare dir adopted


# ===========================================================================
# AUDIT_2 round-2 regressions
# ===========================================================================


def test_fix_clip_refuses_a_blank_local_root(tmp_path, monkeypatch):
    """AUDIT_2 CORE-H1 [measured]. D-6's containment check is a NO-OP when
    local_root is blank: Path("").resolve() is the process CWD, so
    _dest_dir_is_contained happily approved "<CWD>/Audio/Music". Measured in
    the audit as:

        fix_clip(src, "Audio/Music", "", [mpi]) -> copied_to 'Audio\\Music\\take1.mp4'

    With local_root="" every clip also classifies OUT_OF_TREE, so one FIX ALL
    scattered the whole project's media into the autostart exe's working
    directory -- C:\\Windows\\system32 for a Run-key launch -- and relinked
    Resolve to paths nothing will ever sync.
    """
    src = tmp_path / "take1.mp4"
    src.write_bytes(b"x" * 16)
    monkeypatch.chdir(tmp_path)

    for blank in ("", "   "):
        result = fixer.fix_clip(str(src), "Audio/Music", blank, [],
                               replace_clip_fn=lambda mpi, p: {"ok": True, "message": ""})
        assert result["ok"] is False
        assert result["copied_to"] is None
        assert "sync folder" in result["message"]

    assert not (tmp_path / "Audio").exists(), "nothing may be created under the CWD"


def test_fix_clip_claims_the_destination_name_before_copying(tmp_path):
    """AUDIT_2 DEL-7. unique_destination_path() chose a free name, then a
    multi-GB copy ran for minutes, and only THEN did os.replace() land --
    silently clobbering whatever had arrived at that path meanwhile. The
    concrete case is lane C syncing down a DIFFERENT track.wav from another
    editor into Audio/Music during the copy; Syncthing then propagates the
    overwrite fleet-wide.

    The destination name is now created O_CREAT|O_EXCL up front, so a
    concurrent writer picking a name cannot collide with ours.
    """
    root = tmp_path / "root"
    root.mkdir()
    src = tmp_path / "track.wav"
    src.write_bytes(b"original" * 8)

    seen_during_copy = {}

    def slow_copy(s, d):
        # Whatever the final name is, it must ALREADY exist by now.
        seen_during_copy["dest_exists"] = (root / "Audio" / "Music" / "track.wav").exists()
        import shutil as _sh
        _sh.copy2(s, d)

    result = fixer.fix_clip(str(src), "Audio/Music", str(root), [],
                           copy_fn=slow_copy,
                           replace_clip_fn=lambda mpi, p: {"ok": True, "message": ""})
    assert result["ok"] is True
    assert seen_during_copy["dest_exists"] is True


def test_fix_clip_never_overwrites_a_file_that_appeared_during_the_copy(tmp_path):
    """The DEL-7 outcome that matters: an arriving file is not clobbered."""
    root = tmp_path / "root"
    root.mkdir()
    dest_dir = root / "Audio" / "Music"
    dest_dir.mkdir(parents=True)
    src = tmp_path / "track.wav"
    src.write_bytes(b"mine")

    def racing_copy(s, d):
        # Another writer lands its own track.wav while we copy.
        import shutil as _sh
        _sh.copy2(s, d)

    (dest_dir / "track.wav").write_bytes(b"someone-elses")
    result = fixer.fix_clip(str(src), "Audio/Music", str(root), [],
                           copy_fn=racing_copy,
                           replace_clip_fn=lambda mpi, p: {"ok": True, "message": ""})
    assert result["ok"] is True
    assert (dest_dir / "track.wav").read_bytes() == b"someone-elses"
    assert result["copied_to"].endswith("track (2).wav")


def test_fix_clip_tmp_name_is_unique_per_process_and_call(tmp_path):
    """AUDIT_2 CORE-M1: two overlapping FIX ALLs for the same source name both
    wrote "<name>.ccsync-tmp", interleaved their writes, and both replaced
    into the same final name -- a corrupted mixed file under a name Resolve
    was then relinked to."""
    root = tmp_path / "root"
    root.mkdir()
    src = tmp_path / "a.mov"
    src.write_bytes(b"x")

    tmp_names = []

    def record(s, d):
        tmp_names.append(str(d))
        import shutil as _sh
        _sh.copy2(s, d)

    for _ in range(2):
        fixer.fix_clip(str(src), "B-roll", str(root), [], copy_fn=record,
                       replace_clip_fn=lambda mpi, p: {"ok": True, "message": ""})
    assert len(set(tmp_names)) == 2
    assert all(n.endswith(fixer.TMP_SUFFIX) for n in tmp_names)


def test_sweep_stale_tmp_files_reports_and_does_not_delete(tmp_path):
    """AUDIT_2 CORE-H5. A FIX ALL killed mid-copy leaves a partial multi-GB
    file and nothing ever cleaned it up.

    DELIBERATE CHOICE: this REPORTS, it does not unlink. The .stignore and
    rclone-filter half of the fix (in sync/) already stops these syncing
    anywhere, which leaves only wasted disk -- not worth weighing against the
    hard "never delete user data" rule, since a partial BRAW is still the
    editor's data and the filesystem alone cannot prove no process is
    writing it.
    """
    import os
    import time

    root = tmp_path / "root"
    (root / "Projects" / "X").mkdir(parents=True)
    stale = root / "Projects" / "X" / ("A001.braw" + fixer.TMP_SUFFIX)
    stale.write_bytes(b"partial")
    fresh = root / "Projects" / "X" / ("B002.braw" + fixer.TMP_SUFFIX)
    fresh.write_bytes(b"in flight")
    old = time.time() - 7200
    os.utime(stale, (old, old))

    found = fixer.sweep_stale_tmp_files(str(root))
    assert found == [str(stale)], "only files older than the age floor are reported"
    assert stale.exists(), "the sweep must NEVER delete -- hard requirement"
    assert fresh.exists()


def test_sweep_stale_tmp_files_tolerates_a_blank_or_missing_root(tmp_path):
    assert fixer.sweep_stale_tmp_files("") == []
    assert fixer.sweep_stale_tmp_files(str(tmp_path / "nope")) == []


# -- COMP-GUARD-1: the OTHER half of an interrupted FIX ALL -------------------


def _interrupted_fix(root, name="A001_C012.braw", pid=424242, reservation=b"",
                     age_seconds=600.0):
    """The residue of a fix_clip killed mid-copy: the O_EXCL reservation under
    the FINAL name plus the partial it was copying into."""
    import os
    import time

    folder = root / "B-roll" / "Editor Added" / "editor2"
    folder.mkdir(parents=True, exist_ok=True)
    final = folder / name
    final.write_bytes(reservation)
    tmp = folder / f"{name}.{pid}-abcd1234{fixer.TMP_SUFFIX}"
    tmp.write_bytes(b"partially copied bytes")
    old = time.time() - age_seconds
    os.utime(tmp, (old, old))
    os.utime(final, (old, old))
    return final, tmp


def test_orphan_reservation_sweep_removes_the_0_byte_final_name(tmp_path):
    """A hard kill (self-upgrade, reboot, power loss) runs neither of
    fix_clip's cleanup exits, so the 0-byte name it reserved stays. Lane A
    uploads it 120 s later and --ignore-existing then guarantees the real
    footage can never replace it -- from where lane C fans the empty clip out
    to the fleet, immortal since the ignoreDelete retrofit."""
    root = tmp_path / "root"
    final, tmp = _interrupted_fix(root)

    removed = fixer.sweep_orphan_reservations(str(root))

    assert removed == [str(final)]
    assert not final.exists()
    # The PARTIAL is still the editor's data and is never deleted -- that
    # half of the bargain does not change.
    assert tmp.exists()


def test_orphan_reservation_sweep_leaves_a_non_empty_file_alone(tmp_path):
    """DEL-7's case: something else (lane C carrying another editor's
    same-named file down) landed on that exact path. Non-empty is not ours."""
    root = tmp_path / "root"
    final, _tmp = _interrupted_fix(root, reservation=b"real footage")

    assert fixer.sweep_orphan_reservations(str(root)) == []
    assert final.read_bytes() == b"real footage"


def test_orphan_reservation_sweep_leaves_an_in_flight_copy_alone(tmp_path):
    """A live copy rewrites its tmp continuously, so a FRESH tmp means the
    reservation is still doing its job."""
    root = tmp_path / "root"
    final, _tmp = _interrupted_fix(root, age_seconds=0.0)

    assert fixer.sweep_orphan_reservations(str(root)) == []
    assert final.exists()


def test_orphan_reservation_sweep_never_touches_this_processes_own(tmp_path):
    import os

    root = tmp_path / "root"
    final, _tmp = _interrupted_fix(root, pid=os.getpid())

    assert fixer.sweep_orphan_reservations(str(root)) == []
    assert final.exists()


def test_orphan_reservation_sweep_ignores_a_tmp_with_no_writer(tmp_path):
    """Pre-CORE-M1 tmps carry no pid segment, so nothing ties them to a
    writer -- and the adjacent name may be an ordinary file."""
    root = tmp_path / "root"
    import os
    import time

    folder = root / "B-roll"
    folder.mkdir(parents=True)
    final = folder / "C003.braw"
    final.write_bytes(b"")
    tmp = folder / ("C003.braw" + fixer.TMP_SUFFIX)
    tmp.write_bytes(b"partial")
    old = time.time() - 600
    os.utime(tmp, (old, old))

    assert fixer.sweep_orphan_reservations(str(root)) == []
    assert final.exists()


def test_orphan_reservation_sweep_tolerates_a_blank_or_missing_root(tmp_path):
    assert fixer.sweep_orphan_reservations("") == []
    assert fixer.sweep_orphan_reservations(str(tmp_path / "nope")) == []


def test_both_sweeps_can_share_one_walk_of_the_tree(tmp_path):
    """The startup sweep walks local_root once and feeds both."""
    root = tmp_path / "root"
    final, tmp = _interrupted_fix(root, age_seconds=7200)

    walked = fixer.walk_ccsync_tmp_files(str(root))
    assert [path for _mtime, path in walked] == [str(tmp)]
    assert fixer.sweep_stale_tmp_files(str(root), tmp_files=walked) == [str(tmp)]
    assert fixer.sweep_orphan_reservations(str(root), tmp_files=walked) == [str(final)]


def test_reserved_name_for_tmp_reads_back_what_fix_clip_writes(tmp_path):
    """Pins the pairing against a name fix_clip actually produced, so the two
    halves cannot drift apart."""
    import os

    root = tmp_path / "root"
    root.mkdir()
    src = tmp_path / "outside" / "A001.braw"
    src.parent.mkdir()
    src.write_bytes(b"x" * 16)

    seen = {}

    def record(s, d):
        seen["tmp"] = str(d)
        import shutil as _sh
        _sh.copy2(s, d)

    result = fixer.fix_clip(str(src), "B-roll", str(root), [], copy_fn=record,
                            replace_clip_fn=lambda mpi, p: {"ok": True, "message": ""})
    assert result["ok"]
    final, pid = fixer.reserved_name_for_tmp(seen["tmp"])
    assert final == result["copied_to"]
    assert pid == os.getpid()


def test_list_destination_dirs_scopes_to_the_project_prefix(tmp_path):
    """AUDIT_2 CORE-H3. popup.py called this with no project_prefix and a
    hardcoded EMPTY editor_name, so the dropdown offered bare "Audio/Music",
    "B-roll/Stills" and "B-roll/Editor Added/Unknown" beside the correctly
    prefixed suggestion. Picking one filed the media OUTSIDE Projects/, where
    _project_rel_for_path yields None and no run_once(subpath) ever covers
    it -- and the dialog still said "Fixed"."""
    prefix = "Projects/2026/CCT/Season 1"
    (tmp_path / "Projects" / "2026" / "CCT" / "Season 1" / "Audio" / "Music").mkdir(parents=True)
    (tmp_path / "Audio" / "Music").mkdir(parents=True)  # a stray root-level dir

    dirs = fixer.list_destination_dirs(str(tmp_path), "editor2", prefix)
    assert f"{prefix}/Audio/Music" in dirs
    assert f"{prefix}/B-roll/Editor Added/editor2" in dirs
    assert "Audio/Music" not in dirs, "an un-prefixed destination never syncs"
    assert "B-roll/Editor Added/Unknown" not in dirs
    assert all(d.startswith(prefix) for d in dirs)


# ===========================================================================
# AUDIT_2 UX-9: per-file copy progress
# ===========================================================================


def test_copy_with_progress_reports_bytes_as_it_goes(tmp_path):
    """shutil.copy2 reports NOTHING, so a 40 GB BRAW over SMB parked the
    fixer dialog's counter for twenty-plus minutes and looked exactly like a
    hang. Hit live 2026-07-25 at "35/69" while the process was demonstrably
    copying at ~33 MB/s."""
    src = tmp_path / "big.braw"
    src.write_bytes(b"A" * (5 * 1024 * 1024))
    dst = tmp_path / "copy.braw"

    seen = []
    fixer.copy_with_progress(src, dst, on_bytes=lambda d, t: seen.append((d, t)),
                             chunk_size=1024 * 1024)

    assert dst.read_bytes() == src.read_bytes()
    assert seen[0] == (0, 5 * 1024 * 1024), "must report 0 BEFORE the first read"
    assert seen[-1] == (5 * 1024 * 1024, 5 * 1024 * 1024)
    assert len(seen) >= 5, "one report per chunk, not just start and end"
    assert [d for d, _t in seen] == sorted(d for d, _t in seen)


def test_copy_with_progress_preserves_copy2_semantics(tmp_path):
    """It replaces shutil.copy2, so it must still copy metadata and must
    still never touch the source."""
    import os
    import time

    src = tmp_path / "a.mov"
    src.write_bytes(b"payload")
    old = time.time() - 100_000
    os.utime(src, (old, old))
    dst = tmp_path / "b.mov"

    fixer.copy_with_progress(src, dst)
    assert dst.read_bytes() == b"payload"
    assert abs(os.stat(dst).st_mtime - os.stat(src).st_mtime) < 2
    assert src.exists() and src.read_bytes() == b"payload"


def test_copy_with_progress_survives_a_broken_callback(tmp_path):
    """A progress callback that raises must not fail a copy that is fine."""
    src = tmp_path / "a.mov"
    src.write_bytes(b"x" * 4096)
    dst = tmp_path / "b.mov"

    def boom(done, total):
        raise RuntimeError("UI is gone")

    fixer.copy_with_progress(src, dst, on_bytes=boom, chunk_size=1024)
    assert dst.read_bytes() == src.read_bytes()


def test_fix_clip_streams_progress_and_still_uses_tmp_plus_replace(tmp_path):
    """The chunked copy must COMPOSE with DEL-7/CORE-H5: still copy to a
    unique <dest>.ccsync-tmp, still os.replace into an O_EXCL-claimed final
    name, still never touch the source."""
    root = tmp_path / "root"
    root.mkdir()
    src = tmp_path / "take.wav"
    src.write_bytes(b"z" * (3 * 1024 * 1024))

    seen = []
    result = fixer.fix_clip(
        str(src), "Audio/Music", str(root), [],
        replace_clip_fn=lambda mpi, p: {"ok": True, "message": ""},
        on_bytes=lambda d, t: seen.append(d),
    )
    assert result["ok"] is True
    assert seen and seen[-1] == 3 * 1024 * 1024
    dest = root / "Audio" / "Music" / "take.wav"
    assert dest.read_bytes() == src.read_bytes()
    assert src.exists()
    assert not any(p.name.endswith(fixer.TMP_SUFFIX)
                   for p in (root / "Audio" / "Music").iterdir())


# ===========================================================================
# Cloud placeholders -- the measured root cause of the 2026-07-25 incident
# ===========================================================================


def test_is_placeholder_reads_the_windows_cloud_attributes(tmp_path, monkeypatch):
    """MEASURED on the user's machine: ccsync-companion read 222.0 MB/10 s
    while GoogleDriveFS read 222.1 MB/10 s -- byte for byte. FIX ALL was
    blocked inside open()/read() waiting for Google Drive to hydrate an
    online-only source clip. Nothing anywhere said so, so a working copy was
    indistinguishable from a hang."""
    import os

    path = tmp_path / "clip.mp4"
    path.write_bytes(b"x")
    real_stat = os.stat

    class _Stat:
        def __init__(self, attrs):
            self.st_file_attributes = attrs

    for attr in (fixer.FILE_ATTRIBUTE_OFFLINE,
                 fixer.FILE_ATTRIBUTE_RECALL_ON_OPEN,
                 fixer.FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS):
        monkeypatch.setattr(os, "stat", lambda p, _a=attr: _Stat(_a))
        assert fixer.is_placeholder(str(path)) is True, hex(attr)

    monkeypatch.setattr(os, "stat", lambda p: _Stat(0x20))  # FILE_ATTRIBUTE_ARCHIVE
    assert fixer.is_placeholder(str(path)) is False

    monkeypatch.setattr(os, "stat", real_stat)


def test_is_placeholder_is_never_a_gate(tmp_path, monkeypatch):
    """A false positive must never block a copy and a missing attribute must
    never raise -- this is a diagnostic, not a permission check."""
    import os

    assert fixer.is_placeholder(str(tmp_path / "nope.mov")) is False

    class _NoAttrStat:
        pass  # no st_file_attributes at all (Linux/macOS)

    monkeypatch.setattr(os, "stat", lambda p: _NoAttrStat())
    assert fixer.is_placeholder("anything") is False


def test_classify_copy_failure_names_the_cloud_case_and_the_action():
    """`(last: FAILED)` told the user nothing. The most common real cause is
    a placeholder that never hydrated, and the fix is a specific right-click
    in Google Drive."""
    msg = fixer.classify_copy_failure(OSError("The cloud operation was unsuccessful"),
                                      placeholder=True)
    assert "Available offline" in msg
    # The agreed tray wording since the comp-ui-2 sweep (2026-09-03): the
    # button lives in the Settings window, not on an Advanced submenu.
    assert "Tray > Settings > SCAN WHOLE PROJECT" in msg


def test_classify_copy_failure_gives_the_os_reason_for_genuine_errors():
    assert "disk is full" in fixer.classify_copy_failure(
        OSError(28, "No space left on device"), placeholder=False)
    assert "open in another program" in fixer.classify_copy_failure(
        PermissionError("Access is denied"), placeholder=False)
    assert "moved or renamed" in fixer.classify_copy_failure(
        FileNotFoundError("nope"), placeholder=False)
    generic = fixer.classify_copy_failure(OSError("weird thing happened"), placeholder=False)
    assert "weird thing happened" in generic


def test_fix_clip_reports_the_placeholder_reason_on_a_copy_failure(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    src = tmp_path / "The Billion Dollar Buddhists.mp4"
    src.write_bytes(b"x" * 16)

    monkeypatch.setattr(fixer, "is_placeholder", lambda p: True)

    def hydration_fails(s, d):
        raise OSError("The cloud file provider is not running")

    result = fixer.fix_clip(str(src), "B-roll", str(root), [], copy_fn=hydration_fails,
                            replace_clip_fn=lambda m, p: {"ok": True, "message": ""})
    assert result["ok"] is False
    assert result["placeholder"] is True
    assert "Available offline" in result["message"]
    assert "cloud file provider" not in result["message"], "raw OS text is for the log"
    # ...and nothing was left behind at the destination.
    assert list((root / "B-roll").iterdir()) == []


# ===========================================================================
# [ SKIP THIS FILE ] / [ CANCEL ALL ]: mid-file abort, and the cleanup that
# is the only reason it is allowed to exist (CORE-H5)
# ===========================================================================


def test_copy_with_progress_aborts_promptly_mid_file(tmp_path):
    """The flag flips while a multi-GB file is copying: the copy must stop at
    the next 8 MB chunk boundary, not at the end of the file."""
    src = tmp_path / "big.braw"
    src.write_bytes(b"A" * 10_000)
    dst = tmp_path / "partial.braw"

    seen = []

    def should_abort():
        return len(seen) >= 3

    with pytest.raises(fixer.CopyAborted):
        fixer.copy_with_progress(src, dst, on_bytes=lambda d, t: seen.append(d),
                                 chunk_size=1000, should_abort=should_abort)

    assert dst.exists(), "the partial is left for the CALLER to delete"
    assert dst.stat().st_size < src.stat().st_size, "it must not have finished the file"
    assert len(seen) < 12, "it must not have read the whole file before noticing"


def test_copy_with_progress_closes_its_handles_before_raising(tmp_path):
    """CopyAborted is raised AFTER the `with` block. Raising inside it leaves
    a Windows handle open on the destination, so the caller's unlink fails
    with "in use by another process" -- stranding exactly the partial the
    abort exists to remove."""
    src = tmp_path / "a.mov"
    src.write_bytes(b"x" * 4096)
    dst = tmp_path / "b.mov"

    with pytest.raises(fixer.CopyAborted):
        fixer.copy_with_progress(src, dst, chunk_size=512, should_abort=lambda: True)

    # If a handle were still open this unlink would raise on Windows.
    dst.unlink()
    assert not dst.exists()


def test_copy_with_progress_ignores_an_abort_callback_that_raises(tmp_path):
    """A misbehaving UI predicate must never abandon a copy that is fine."""
    src = tmp_path / "a.mov"
    src.write_bytes(b"x" * 4096)
    dst = tmp_path / "b.mov"

    def boom():
        raise RuntimeError("the window went away")

    fixer.copy_with_progress(src, dst, chunk_size=512, should_abort=boom)
    assert dst.read_bytes() == src.read_bytes()


def test_copy_with_progress_with_the_flag_never_set_is_unchanged(tmp_path):
    src = tmp_path / "a.mov"
    src.write_bytes(b"x" * 4096)
    dst = tmp_path / "b.mov"
    fixer.copy_with_progress(src, dst, chunk_size=512, should_abort=lambda: False)
    assert dst.read_bytes() == src.read_bytes()


def test_fix_clip_abort_deletes_the_partial_destination(tmp_path):
    """THE CORE-H5 GUARANTEE, and the only reason mid-file abort is allowed
    at all: after a skip/cancel nothing of the attempt survives under
    local_root. A stranded multi-GB partial is what lane A would upload and
    lane C would fan out to the whole fleet."""
    root = tmp_path / "root"
    root.mkdir()
    src = tmp_path / "huge.braw"
    src.write_bytes(b"A" * 100_000)

    relinked = []

    def _relink(mpi, path):
        relinked.append(path)
        return {"ok": True, "message": ""}

    result = fixer.fix_clip(
        str(src), "B-roll/Stills", str(root), [object()],
        replace_clip_fn=_relink,
        on_bytes=lambda d, t: None,
        should_abort=lambda: True,
    )

    assert result["ok"] is False
    assert result["aborted"] is True
    assert result["copied_to"] is None
    assert result["leftover_paths"] == []
    assert relinked == [], "an abandoned file must NEVER be relinked in Resolve"
    dest_dir = root / "B-roll" / "Stills"
    assert list(dest_dir.iterdir()) == [], (
        f"the abort left files behind: {[p.name for p in dest_dir.iterdir()]}"
    )
    assert src.read_bytes() == b"A" * 100_000, "the original is never touched"


def test_fix_clip_abort_removes_both_the_tmp_and_the_reserved_final_name(tmp_path):
    """Two artifacts exist by the time a copy is running: the partial
    <dest>.<pid>-<uuid>.ccsync-tmp, and the 0-byte final name
    _claim_destination_path reserved up front (O_CREAT|O_EXCL). The tmp is
    filtered out of every lane; the reservation is NOT -- a 0-byte .braw
    under the final name would upload on lane A and could then never be
    replaced (lane A uses --ignore-existing)."""
    root = tmp_path / "root"
    root.mkdir()
    src = tmp_path / "take.wav"
    src.write_bytes(b"z" * 50_000)

    seen_during_copy = {}

    def copy_then_abort(s, d):
        # Write a partial (as the real copier would), snapshot what is on
        # disk at the moment of the abort, then raise like it does.
        Path(d).write_bytes(b"z" * 10_000)
        seen_during_copy["paths"] = sorted(p.name for p in Path(d).parent.iterdir())
        raise fixer.CopyAborted("user skipped")

    result = fixer.fix_clip(str(src), "Audio/Music", str(root), [],
                            copy_fn=copy_then_abort,
                            replace_clip_fn=lambda m, p: {"ok": True, "message": ""})

    names = seen_during_copy["paths"]
    assert "take.wav" in names, "the final name is reserved before the copy starts"
    assert any(n.endswith(fixer.TMP_SUFFIX) for n in names)
    assert result["aborted"] is True
    assert list((root / "Audio" / "Music").iterdir()) == [], (
        "BOTH the partial and the reserved name must be gone"
    )


def test_fix_clip_abort_reports_a_partial_it_could_not_delete(tmp_path, monkeypatch, caplog):
    """Best-effort-but-LOUD: a delete that fails must never raise, must log a
    warning naming the path, and must surface in the result so the dialog can
    tell the user there is an orphan on their disk."""
    import logging

    root = tmp_path / "root"
    root.mkdir()
    src = tmp_path / "clip.mov"
    src.write_bytes(b"q" * 1000)

    def copy_then_abort(s, d):
        Path(d).write_bytes(b"q" * 100)
        raise fixer.CopyAborted("user cancelled")

    real_unlink = Path.unlink

    def stubborn_unlink(self, *a, **k):
        if self.name.endswith(fixer.TMP_SUFFIX):
            raise PermissionError("used by another process")
        return real_unlink(self, *a, **k)

    monkeypatch.setattr(Path, "unlink", stubborn_unlink)

    with caplog.at_level(logging.WARNING, logger="ccsync.fixer"):
        result = fixer.fix_clip(str(src), "B-roll", str(root), [],
                                copy_fn=copy_then_abort,
                                replace_clip_fn=lambda m, p: {"ok": True, "message": ""})

    assert result["aborted"] is True
    assert len(result["leftover_paths"]) == 1
    assert result["leftover_paths"][0].endswith(fixer.TMP_SUFFIX)
    assert "Delete it by hand" in result["message"]
    assert any("COULD NOT REMOVE" in r.message for r in caplog.records)


def test_remove_partial_never_raises_and_is_a_no_op_on_a_missing_file(tmp_path):
    assert fixer.remove_partial(tmp_path / "not-there.braw") is None
    doomed = tmp_path / "there.braw"
    doomed.write_bytes(b"x")
    assert fixer.remove_partial(doomed) is None
    assert not doomed.exists()
    # a directory can't be unlinked -- reported, never raised
    a_dir = tmp_path / "a-dir"
    a_dir.mkdir()
    assert fixer.remove_partial(a_dir) == str(a_dir)


def test_abort_cleanup_never_deletes_a_file_another_writer_put_there(tmp_path):
    """DEL-7 still holds during an abort. Lane C can sync down a same-named
    file from another editor onto the name we reserved while our copy runs --
    deleting THAT would destroy data this module did not write, which is the
    one thing it may never do."""
    root = tmp_path / "root"
    root.mkdir()
    src = tmp_path / "track.wav"
    src.write_bytes(b"m" * 5000)

    def copy_then_abort(s, d):
        Path(d).write_bytes(b"m" * 500)
        # somebody else's content lands on our reserved final name
        dest = Path(d).parent / "track.wav"
        dest.write_bytes(b"SOMEONE ELSE'S TRACK")
        raise fixer.CopyAborted("user skipped")

    result = fixer.fix_clip(str(src), "Audio/Music", str(root), [],
                            copy_fn=copy_then_abort,
                            replace_clip_fn=lambda m, p: {"ok": True, "message": ""})

    assert result["aborted"] is True
    survivor = root / "Audio" / "Music" / "track.wav"
    assert survivor.read_bytes() == b"SOMEONE ELSE'S TRACK"
    # ...but OUR partial is still gone
    assert not any(p.name.endswith(fixer.TMP_SUFFIX)
                   for p in (root / "Audio" / "Music").iterdir())


def test_remove_reserved_name_only_removes_an_empty_reservation(tmp_path):
    empty = tmp_path / "claimed.braw"
    empty.touch()
    assert fixer.remove_reserved_name(empty) is None
    assert not empty.exists()

    theirs = tmp_path / "theirs.braw"
    theirs.write_bytes(b"data")
    assert fixer.remove_reserved_name(theirs) is None
    assert theirs.read_bytes() == b"data", "a non-empty file is never deleted here"

    assert fixer.remove_reserved_name(tmp_path / "gone.braw") is None


def test_fix_clip_without_should_abort_behaves_exactly_as_before(tmp_path):
    """The new parameter is optional; every existing caller is unaffected."""
    root = tmp_path / "root"
    root.mkdir()
    src = tmp_path / "a.wav"
    src.write_bytes(b"payload")
    result = fixer.fix_clip(str(src), "Audio/Music", str(root), [],
                            replace_clip_fn=lambda m, p: {"ok": True, "message": ""})
    assert result["ok"] is True
    assert "aborted" not in result
    assert (root / "Audio" / "Music" / "a.wav").read_bytes() == b"payload"


# -- canonical relink path (the D:-vs-P: offline-clip bug, 2026-07-26) -----


def test_canonical_clip_path_translates_local_root_to_prefix(tmp_path):
    import os

    dest = os.path.join(str(tmp_path), "root", "B-roll", "clip.mov")
    got = fixer.canonical_clip_path(dest, os.path.join(str(tmp_path), "root"), "P:\\")
    # Hardcoded backslashes, NOT "P:\\" + os.path.join(...): the canonical
    # spelling is a fleet-wide constant, not a property of the host running
    # the test. Deriving it from os.path.join demanded "P:\B-roll/clip.mov"
    # on macOS -- i.e. it asserted the exact mixed spelling that
    # test_canonical_clip_path_is_all_backslashes_from_a_posix_tree below
    # exists to forbid. The two contradicted each other on a Mac (MAC-2b).
    assert got == r"P:\B-roll\clip.mov"

    # no prefix configured -> physical path unchanged
    assert fixer.canonical_clip_path(dest, os.path.join(str(tmp_path), "root"), "") == dest
    # not under local_root -> physical path unchanged
    outside = os.path.join(str(tmp_path), "elsewhere", "clip.mov")
    assert fixer.canonical_clip_path(outside, os.path.join(str(tmp_path), "root"), "P:\\") == outside
    # base rig identity: prefix IS local_root
    root = os.path.join(str(tmp_path), "root")
    assert fixer.canonical_clip_path(dest, root, root) == dest


def test_canonical_clip_path_is_all_backslashes_from_a_posix_tree():
    """A macOS editor's tree is at /Volumes/T7/Creators_Club, but what goes
    into the project database via ReplaceClip must be the fleet's canonical
    Windows spelling. Joining the prefix to the relative part with the HOST
    separator emits `P:\\Projects/2026/...`, and that mixed path travels to
    every other machine in the fleet."""
    got = fixer.canonical_clip_path(
        "/Volumes/T7/Creators_Club/Projects/2026/CCT/Panel/A001_C061.braw",
        "/Volumes/T7/Creators_Club",
        "P:\\",
    )
    assert got == r"P:\Projects\2026\CCT\Panel\A001_C061.braw"
    assert "/" not in got


def test_fix_clip_relinks_to_canonical_path_not_physical(tmp_path):
    r"""The Resolve project travels between machines; this machine's
    local_root does not. Relinking to D:\...\clip.mov made the clip
    offline everywhere but the machine that fixed it."""
    src = tmp_path / "src" / "clip.mov"
    src.parent.mkdir(parents=True)
    src.write_text("video bytes")
    local_root = tmp_path / "root"
    media_pool_item = FakeClip()

    result = fixer.fix_clip(
        str(src), "B-roll/Editor Added/owen", str(local_root), media_pool_item,
        replace_clip_fn=_fake_replace_clip_ok,
        canonical_prefix="P:\\",
    )

    assert result["ok"] is True
    # the file physically lands under local_root...
    dest = local_root / "B-roll" / "Editor Added" / "owen" / "clip.mov"
    assert dest.is_file()
    # ...but Resolve is pointed at the canonical P:\ path, spelled with
    # backslashes on every host (see the note in
    # test_canonical_clip_path_translates_local_root_to_prefix).
    assert media_pool_item.relinked_to == r"P:\B-roll\Editor Added\owen\clip.mov"


# -- item 9 (COMMERCIAL_READINESS.md, 2026-08-17): the two gates around the
# copy, and the rehearsal switch -------------------------------------------


class TestReservationRecheck:
    """`_claim_destination_path` claims the final name with O_EXCL before the
    copy; nothing stopped a second writer overwriting the 0-byte claim during
    a multi-GB copy, and os.replace then destroyed what arrived."""

    def test_a_file_that_lands_on_our_reservation_is_not_overwritten(self, tmp_path):
        root = tmp_path / "root"
        (root / "B-roll").mkdir(parents=True)
        src = tmp_path / "clip.mov"
        src.write_bytes(b"ours" * 10)
        dest = root / "B-roll" / "clip.mov"

        def copy_that_loses_the_race(s, d):
            # Lane C syncs somebody else's clip.mov onto our reservation
            # WHILE we copy -- the DEL-7 case, one step later.
            dest.write_bytes(b"someone-elses")
            shutil.copy2(s, d)

        result = fixer.fix_clip(
            str(src), "B-roll", str(root), [],
            copy_fn=copy_that_loses_the_race,
            replace_clip_fn=lambda mpi, p: {"ok": True, "message": ""},
        )

        assert result["ok"] is True
        assert dest.read_bytes() == b"someone-elses"
        assert result["copied_to"].endswith("clip (2).mov")
        assert Path(result["copied_to"]).read_bytes() == src.read_bytes()

    def test_a_reservation_that_vanished_still_lands_under_its_own_name(self, tmp_path):
        root = tmp_path / "root"
        (root / "B-roll").mkdir(parents=True)
        src = tmp_path / "clip.mov"
        src.write_bytes(b"ours")

        def copy_that_loses_the_reservation(s, d):
            (root / "B-roll" / "clip.mov").unlink()
            shutil.copy2(s, d)

        result = fixer.fix_clip(
            str(src), "B-roll", str(root), [],
            copy_fn=copy_that_loses_the_reservation,
            replace_clip_fn=lambda mpi, p: {"ok": True, "message": ""},
        )
        assert result["ok"] is True
        assert result["copied_to"].endswith("clip.mov")


class TestVerifyBeforeRelink:
    def test_a_short_copy_is_never_relinked(self, tmp_path):
        root = tmp_path / "root"
        root.mkdir()
        src = tmp_path / "clip.mov"
        src.write_bytes(b"x" * 5000)
        relinks = []

        def truncating_copy(s, d):
            Path(d).write_bytes(b"x" * 10)

        result = fixer.fix_clip(
            str(src), "B-roll", str(root), [object()],
            copy_fn=truncating_copy,
            replace_clip_fn=lambda mpi, p: relinks.append(p) or {"ok": True},
        )

        assert result["ok"] is False
        assert relinks == []
        assert "cut short" in result["verify_error"]
        # And the bad copy is gone, so lane A cannot upload it under a name
        # --ignore-existing would never let it replace.
        assert not (root / "B-roll" / "clip.mov").exists()

    def test_a_source_that_changed_during_the_copy_is_never_relinked(self, tmp_path):
        root = tmp_path / "root"
        root.mkdir()
        src = tmp_path / "clip.mov"
        src.write_bytes(b"x" * 100)
        relinks = []

        def copy_then_grow_the_source(s, d):
            shutil.copy2(s, d)
            # The card is still being ingested: same size, new mtime.
            os.utime(src, (1000000.0, 1000000.0))

        result = fixer.fix_clip(
            str(src), "B-roll", str(root), [object()],
            copy_fn=copy_then_grow_the_source,
            replace_clip_fn=lambda mpi, p: relinks.append(p) or {"ok": True},
        )

        assert result["ok"] is False
        assert relinks == []
        assert "still being written" in result["verify_error"]

    def test_a_faithful_copy_is_relinked(self, tmp_path):
        root = tmp_path / "root"
        root.mkdir()
        src = tmp_path / "clip.mov"
        src.write_bytes(b"x" * 100)
        relinks = []

        result = fixer.fix_clip(
            str(src), "B-roll", str(root), [object()],
            copy_fn=shutil.copy2,
            replace_clip_fn=lambda mpi, p: relinks.append(p) or {"ok": True},
        )
        assert result["ok"] is True and len(relinks) == 1

    def test_verify_copy_is_pure(self, tmp_path):
        a = tmp_path / "a"
        b = tmp_path / "b"
        a.write_bytes(b"12345")
        b.write_bytes(b"12345")
        before = fixer.sample_source(a)
        assert fixer.verify_copy(a, b, before) is None
        b.write_bytes(b"12")
        assert "cut short" in fixer.verify_copy(a, b, before)


class TestDryRun:
    def test_it_copies_nothing_and_relinks_nothing(self, tmp_path):
        root = tmp_path / "root"
        root.mkdir()
        src = tmp_path / "clip.mov"
        src.write_bytes(b"x" * 100)
        relinks = []

        result = fixer.fix_clip(
            str(src), "B-roll", str(root), [object()],
            copy_fn=lambda s, d: pytest.fail("dry run copied a file"),
            replace_clip_fn=lambda mpi, p: relinks.append(p) or {"ok": True},
            canonical_prefix="P:\\",
            dry_run=True,
        )

        assert result["ok"] is False and result["dry_run"] is True
        assert relinks == []
        assert not (root / "B-roll").exists()
        assert result["would_copy_to"].endswith(os.path.join("B-roll", "clip.mov"))
        assert result["would_relink_to"] == r"P:\B-roll\clip.mov"

    def test_it_still_refuses_a_destination_outside_local_root(self, tmp_path):
        root = tmp_path / "root"
        root.mkdir()
        src = tmp_path / "clip.mov"
        src.write_bytes(b"x")
        result = fixer.fix_clip(str(src), "../escape", str(root), [], dry_run=True)
        assert result["ok"] is False
        assert "outside local_root" in result["message"]

    def test_the_config_default_is_read_once(self, tmp_path, monkeypatch):
        from ccsync_companion import config as config_mod
        fixer.reset_dry_run_cache()
        reads = []

        def fake_load():
            reads.append(1)
            return {"fixer_dry_run": True}

        monkeypatch.setattr(config_mod, "load_config", fake_load)
        try:
            assert fixer.dry_run_default() is True
            assert fixer.dry_run_default() is True
            assert len(reads) == 1
        finally:
            fixer.reset_dry_run_cache()


# -- library walk, 2026-08-26 ------------------------------------------------


def test_fix_clip_resolves_a_uid_only_entry_at_the_relink(tmp_path, monkeypatch):
    from ccsync_companion import resolve_bridge

    src = tmp_path / "src" / "clip.mov"
    src.parent.mkdir(parents=True)
    src.write_text("video bytes")
    live = object()
    monkeypatch.setattr(resolve_bridge, "media_pool_item_by_uid",
                        lambda uid: live if uid == "uid-a" else None)
    seen = []

    def _replace(mpi, path):
        seen.append((mpi, path))
        return {"ok": True}

    result = fixer.fix_clip(
        str(src), "B-roll/Editor Added/owen", str(tmp_path / "root"),
        [{"media_pool_item": None, "media_pool_uid": "uid-a", "clip_name": "clip.mov"}],
        replace_clip_fn=_replace, canonical_prefix="P:\\",
    )

    assert result["ok"] is True
    assert seen == [(live, r"P:\B-roll\Editor Added\owen\clip.mov")]


def test_fix_clip_dedupes_uid_only_entries_by_uid_not_by_dict_identity(
        tmp_path, monkeypatch):
    """Two timeline items of one clip are two DIFFERENT dicts carrying the
    SAME uid: keying by id() would put a clip cut in 50 times back to 50
    ReplaceClips, which is the re-conform storm the dedupe exists to stop."""
    from ccsync_companion import resolve_bridge

    src = tmp_path / "src" / "clip.mov"
    src.parent.mkdir(parents=True)
    src.write_text("video bytes")
    live = object()
    monkeypatch.setattr(resolve_bridge, "media_pool_item_by_uid", lambda uid: live)
    calls = []

    result = fixer.fix_clip(
        str(src), "B-roll", str(tmp_path / "root"),
        [{"media_pool_item": None, "media_pool_uid": "uid-a"},
         {"media_pool_item": None, "media_pool_uid": "uid-a"}],
        replace_clip_fn=lambda mpi, path: (calls.append(path), {"ok": True})[1],
        canonical_prefix="P:\\",
    )

    assert result["ok"] is True
    assert len(calls) == 1


def test_fix_clip_reports_a_clip_it_could_not_find_as_a_failure(
        tmp_path, monkeypatch, caplog):
    """The copy landed. Saying "Fixed" while nothing was repointed at it is
    the one outcome worse than failing."""
    from ccsync_companion import resolve_bridge

    src = tmp_path / "src" / "clip.mov"
    src.parent.mkdir(parents=True)
    src.write_text("video bytes")
    monkeypatch.setattr(resolve_bridge, "media_pool_item_by_uid", lambda uid: None)

    with caplog.at_level(logging.WARNING):
        result = fixer.fix_clip(
            str(src), "B-roll", str(tmp_path / "root"),
            [{"media_pool_item": None, "media_pool_uid": "uid-gone",
              "clip_name": "clip.mov"}],
            replace_clip_fn=lambda mpi, path: {"ok": True},
            canonical_prefix="P:\\",
        )

    assert result["ok"] is False
    assert "clip.mov" in result["message"]
    assert result["copied_to"]


def test_list_project_dirs_folds_the_two_spellings_of_one_project(tmp_path):
    """bug-hunt-2026-09-03 comp-core-3: the walked source is NFD on a Mac and
    `extra_rels` (the dashboard's selection) is NFC, and the extras' only
    membership test is is_dir(), which succeeds on APFS/HFS+ for either
    spelling -- so one project entered the set twice. The spelling RETURNED is
    the walked one: callers walk these paths, and there the bytes on disk are
    the truth."""
    import unicodedata

    from conftest import write_project_marker

    walked = unicodedata.normalize("NFD", "2026/Français/Été")
    selected = unicodedata.normalize("NFC", "2026/Français/Été")
    project_dir = tmp_path / "Projects" / walked.replace("/", os.sep)
    project_dir.mkdir(parents=True)
    write_project_marker(project_dir, slug="ete")
    # NTFS is normalisation-PRESERVING and case-folds nothing else, so the
    # second spelling has to be materialised here to reproduce what APFS does
    # for free: one directory that answers is_dir() to either spelling. On
    # APFS itself that mkdir finds the directory already there (FileExistsError
    # on the macOS CI runner, 2026-09-03), which is exactly the shape wanted.
    (tmp_path / "Projects" / selected.replace("/", os.sep)).mkdir(parents=True, exist_ok=True)

    rels = fixer.list_project_dirs(str(tmp_path), extra_rels=[selected])
    assert rels == [walked]


# ===========================================================================
# RES-14 (2026-09-04): a CANCEL that is honoured while the source is a cloud
# placeholder. `fsrc.read()` cannot be interrupted, so the chunk IS the
# cancellation latency -- and during it the dialog has already disabled
# STOP/SKIP/CANCEL and cannot even be closed.
# ===========================================================================


class _SlowSource:
    """A file-like whose reads cost TIME on a fake clock.

    22.2 MB/s is the live incident's rate (222 MB per 10 s hydrating a Google
    Drive placeholder). No sleeps: the wall clock is not part of this
    measurement and a test that waits for one is a test that flakes on CI.
    """

    BYTES_PER_SECOND = 22.2 * 1024 * 1024

    def __init__(self, size, clock):
        self._left = size
        self._clock = clock

    def read(self, count):
        chunk = min(count, self._left)
        self._left -= chunk
        self._clock.advance(chunk / self.BYTES_PER_SECOND)
        return b"A" * chunk

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def test_a_cancel_is_honoured_within_two_seconds_of_a_slow_source(tmp_path,
                                                                  monkeypatch):
    clock = _FakeClock()
    src = tmp_path / "placeholder.braw"
    src.write_bytes(b"")
    dst = tmp_path / "copy.braw"
    slow = _SlowSource(4 * 1024 * 1024 * 1024, clock)
    real_open = open

    def fake_open(path, mode="r", *args, **kwargs):
        if "r" in mode and str(path) == str(src):
            return slow
        return real_open(path, mode, *args, **kwargs)

    monkeypatch.setattr("builtins.open", fake_open)
    monkeypatch.setattr(fixer.os.path, "getsize", lambda p: 4 * 1024 * 1024 * 1024)

    pressed_at = 3.0
    with pytest.raises(fixer.CopyAborted):
        fixer.copy_with_progress(
            src, dst, should_abort=lambda: clock.now >= pressed_at, clock=clock)

    assert clock.now - pressed_at < 2.0, (
        "the button the editor pressed must be answered inside two seconds")


def test_a_read_slower_than_the_poll_budget_makes_the_next_one_smaller(tmp_path,
                                                                       monkeypatch):
    """A cold placeholder blocks for the whole hydration whatever it is
    asked for, so the answer is to ask for less."""
    clock = _FakeClock()
    sizes = []
    src = tmp_path / "cold.braw"
    src.write_bytes(b"")
    dst = tmp_path / "copy.braw"

    class _Glacial(_SlowSource):
        BYTES_PER_SECOND = 64 * 1024      # 1 MB would be 16 s

        def read(self, count):
            sizes.append(count)
            return super().read(count)

    glacial = _Glacial(64 * 1024 * 1024, clock)
    real_open = open

    def fake_open(path, mode="r", *args, **kwargs):
        if "r" in mode and str(path) == str(src):
            return glacial
        return real_open(path, mode, *args, **kwargs)

    monkeypatch.setattr("builtins.open", fake_open)
    monkeypatch.setattr(fixer.os.path, "getsize", lambda p: 64 * 1024 * 1024)

    with pytest.raises(fixer.CopyAborted):
        fixer.copy_with_progress(
            src, dst, should_abort=lambda: clock.now >= 300.0, clock=clock)

    assert sizes[0] == fixer.POLL_CHUNK_BYTES
    assert sizes[-1] == fixer.MIN_CHUNK_BYTES
    assert sizes[-1] < sizes[0], "the reads must shrink, not the copy stall"


def test_a_cancel_between_clips_stops_the_replaceclip_loop(tmp_path,
                                                           monkeypatch):
    """The other half of the wedge: a clip cut in 50 places is 50
    uninterruptible ReplaceClip calls and the loop consulted should_abort not
    at all, so the dialog sat disabled for the whole batch."""
    src = tmp_path / "A001.braw"
    src.write_bytes(b"x" * 64)
    local_root = tmp_path / "tree"
    (local_root / "Media").mkdir(parents=True)

    relinked = []
    items = [{"clip_name": "a"}, {"clip_name": "b"}, {"clip_name": "c"}]
    monkeypatch.setattr(fixer.resolve_bridge, "resolve_media_pool_item",
                        lambda entry: entry)

    def replace_clip(mpi, path):
        relinked.append(mpi["clip_name"])
        return {"ok": True}

    result = fixer.fix_clip(
        str(src), "Media", str(local_root), items,
        replace_clip_fn=replace_clip,
        # Pressed after the copy landed, while the relinks are running.
        should_abort=lambda: len(relinked) >= 2,
        dry_run=False,
    )

    assert relinked == ["a", "b"], "it must stop between clips, never mid-call"
    assert result["aborted"] is True and result["partial_relink"] is True
    assert result["relinked"] == 2
    # The copy landed and the clips already repointed are correct: nothing
    # here deletes, and the message says exactly how far it got.
    assert result["copied_to"] and Path(result["copied_to"]).exists()
    assert "2 of 3" in result["message"]
    assert "—" not in result["message"]


def test_an_abandoned_copy_never_appears_under_the_final_name(tmp_path):
    """RES-14's other guarantee, pinned: the partial is a `.ccsync-tmp` and
    the 0-byte O_EXCL reservation goes with it, so lane A can never upload a
    truncated file under a name it could then never replace."""
    src = tmp_path / "A002.braw"
    src.write_bytes(b"y" * 4096)
    local_root = tmp_path / "tree"
    (local_root / "Media").mkdir(parents=True)

    result = fixer.fix_clip(
        str(src), "Media", str(local_root), [{"clip_name": "a"}],
        should_abort=lambda: True,
        replace_clip_fn=lambda mpi, path: {"ok": True},
        dry_run=False,
    )

    assert result["aborted"] is True
    assert list((local_root / "Media").iterdir()) == []
