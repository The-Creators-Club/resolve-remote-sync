"""Fixer tests: destination suggestion by type, existing-dir listing (Proxy
excluded), collision-safe renaming, and the copy+relink flow (mocked
resolve_bridge / copy_fn — never touches a real Resolve instance)."""

from __future__ import annotations

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
