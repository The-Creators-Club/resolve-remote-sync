"""Fixer tests: destination suggestion by type, existing-dir listing (Proxy
excluded), collision-safe renaming, and the copy+relink flow (mocked
resolve_bridge / copy_fn — never touches a real Resolve instance)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

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
    assert fixer.suggest_destination(f"C:\\Desktop\\{filename}", "alex") == expected


@pytest.mark.parametrize("filename", ["clip.mov", "clip.mp4", "notes.docx", "weird.xyz"])
def test_suggest_destination_video_and_other_falls_back_to_editor_added(filename):
    assert (
        fixer.suggest_destination(f"C:\\Desktop\\{filename}", "alex")
        == "B-roll/Editor Added/alex"
    )


def test_suggest_destination_unknown_editor_name():
    assert fixer.suggest_destination("clip.mov", "") == "B-roll/Editor Added/Unknown"


# -- destination directory listing -----------------------------------------


def test_list_destination_dirs_includes_defaults_even_if_missing(tmp_path):
    dirs = fixer.list_destination_dirs(str(tmp_path), "alex")
    assert "Audio/Music" in dirs
    assert "B-roll/Stills" in dirs
    assert "B-roll/Editor Added/alex" in dirs


def test_list_destination_dirs_excludes_proxy(tmp_path):
    (tmp_path / "B-roll" / "Proxy").mkdir(parents=True)
    (tmp_path / "B-roll" / "Proxy" / "Nested").mkdir(parents=True)
    (tmp_path / "Interviewees" / "Jane").mkdir(parents=True)
    dirs = fixer.list_destination_dirs(str(tmp_path), "alex")
    assert "Interviewees/Jane" in dirs
    assert not any("proxy" in d.lower() for d in dirs)


def test_list_destination_dirs_uses_forward_slashes(tmp_path):
    (tmp_path / "AE" / "Renders").mkdir(parents=True)
    dirs = fixer.list_destination_dirs(str(tmp_path), "alex")
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


def _fake_replace_clip_ok(media_pool_item, new_path):
    media_pool_item["relinked_to"] = new_path
    return {"ok": True, "message": f"Relinked to {new_path}"}


def _fake_replace_clip_fail(media_pool_item, new_path):
    return {"ok": False, "message": "ReplaceClip returned False"}


def test_fix_clip_copies_and_relinks(tmp_path):
    src = tmp_path / "src" / "clip.mov"
    src.parent.mkdir(parents=True)
    src.write_text("video bytes")
    local_root = tmp_path / "root"
    media_pool_item = {}

    result = fixer.fix_clip(
        str(src), "B-roll/Editor Added/alex", str(local_root), media_pool_item,
        replace_clip_fn=_fake_replace_clip_ok,
    )

    assert result["ok"] is True
    dest = local_root / "B-roll" / "Editor Added" / "alex" / "clip.mov"
    assert dest.is_file()
    assert dest.read_text() == "video bytes"
    assert src.is_file(), "original must never be deleted/moved"
    assert media_pool_item["relinked_to"] == str(dest)


def test_fix_clip_collision_renames_copy(tmp_path):
    src = tmp_path / "src" / "clip.mov"
    src.parent.mkdir(parents=True)
    src.write_text("new bytes")
    local_root = tmp_path / "root"
    dest_dir = local_root / "Audio" / "Music"
    dest_dir.mkdir(parents=True)
    (dest_dir / "clip.mov").write_text("pre-existing bytes")

    result = fixer.fix_clip(
        str(src), "Audio/Music", str(local_root), {}, replace_clip_fn=_fake_replace_clip_ok,
    )

    assert result["ok"] is True
    assert result["copied_to"].endswith("clip (2).mov")
    assert (dest_dir / "clip.mov").read_text() == "pre-existing bytes"
    assert (dest_dir / "clip (2).mov").read_text() == "new bytes"


def test_fix_clip_missing_source_reports_failure_no_crash(tmp_path):
    result = fixer.fix_clip(
        str(tmp_path / "does_not_exist.mov"), "Audio/Music", str(tmp_path), {},
    )
    assert result["ok"] is False
    assert "not found" in result["message"]


def test_fix_clip_relink_failure_keeps_copy_and_reports_error(tmp_path):
    src = tmp_path / "src" / "clip.mov"
    src.parent.mkdir(parents=True)
    src.write_text("bytes")
    local_root = tmp_path / "root"

    result = fixer.fix_clip(
        str(src), "Audio/Music", str(local_root), {}, replace_clip_fn=_fake_replace_clip_fail,
    )

    assert result["ok"] is False
    assert "relink failed" in result["message"]
    dest = local_root / "Audio" / "Music" / "clip.mov"
    assert dest.is_file(), "copy must survive even when ReplaceClip fails"
    assert src.is_file(), "original must never be deleted, even on relink failure"


# -- IgnoreTracker ----------------------------------------------------------


def test_ignore_tracker_is_ignored_and_normalizes_case_on_windows():
    tracker = fixer.IgnoreTracker()
    tracker.ignore(r"C:\Users\alex\Desktop\clip.mov")
    assert tracker.is_ignored(r"c:\USERS\alex\DESKTOP\clip.MOV") is True
    assert tracker.is_ignored(r"C:\Users\alex\Desktop\other.mov") is False


def test_ignore_tracker_clear():
    tracker = fixer.IgnoreTracker()
    tracker.ignore("clip.mov")
    tracker.clear()
    assert tracker.is_ignored("clip.mov") is False


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
    media_pool_item = {}

    result = fixer.fix_clip(
        str(src), "B-roll/Editor Added/alex", str(local_root), media_pool_item,
        replace_clip_fn=_fake_replace_clip_ok,
    )

    assert result["ok"] is True
    assert media_pool_item["relinked_to"] is not None


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
    (tmp_path / "Projects" / "2025" / "FF4" / "Nuclear").mkdir(parents=True)
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
