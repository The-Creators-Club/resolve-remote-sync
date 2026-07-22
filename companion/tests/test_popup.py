"""Popup logic tests (pure functions only — no real tkinter window is ever
created in tests; PopupDialog itself needs a live display and is exercised
manually per README.md's "known limitations")."""

from __future__ import annotations

from ccsync_companion import fixer
from ccsync_companion.popup import build_popup_rows, perform_fix_all, perform_ignore_all


def _item(file_path, clip_name=None, media_pool_item=None):
    return {
        "file_path": file_path,
        "media_pool_item": media_pool_item if media_pool_item is not None else object(),
        "clip_name": clip_name,
    }


def test_build_popup_rows_uses_suggested_destination():
    items = [_item(r"C:\Desktop\track.wav"), _item(r"C:\Desktop\clip.mov")]
    rows = build_popup_rows(items, r"C:\Creators_Club", "alex")
    assert rows[0]["suggested_dest"] == "Audio/Music"
    assert rows[1]["suggested_dest"] == "B-roll/Editor Added/alex"


def test_build_popup_rows_falls_back_to_basename_for_clip_name():
    items = [_item(r"C:\Desktop\track.wav", clip_name=None)]
    rows = build_popup_rows(items, r"C:\Creators_Club", "alex")
    assert rows[0]["clip_name"] == "track.wav"


def test_perform_fix_all_uses_selection_over_suggestion(tmp_path):
    items = [_item(str(tmp_path / "track.wav"))]
    (tmp_path / "track.wav").write_text("audio")
    rows = build_popup_rows(items, str(tmp_path / "root"), "alex")

    calls = []

    def fake_fix_clip(file_path, dest_rel, local_root, media_pool_item):
        calls.append((file_path, dest_rel))
        return {"ok": True, "message": "ok", "copied_to": "somewhere"}

    selections = {str(tmp_path / "track.wav"): "Audio/Custom"}
    results = perform_fix_all(rows, selections, str(tmp_path / "root"), fix_clip_fn=fake_fix_clip)

    assert calls == [(str(tmp_path / "track.wav"), "Audio/Custom")]
    assert results[0]["file_path"] == str(tmp_path / "track.wav")
    assert results[0]["ok"] is True


def test_perform_fix_all_falls_back_to_suggested_dest_when_no_selection():
    items = [_item(r"C:\Desktop\track.wav")]
    rows = build_popup_rows(items, r"C:\Creators_Club", "alex")

    calls = []

    def fake_fix_clip(file_path, dest_rel, local_root, media_pool_item):
        calls.append(dest_rel)
        return {"ok": True, "message": "ok", "copied_to": "x"}

    perform_fix_all(rows, {}, r"C:\Creators_Club", fix_clip_fn=fake_fix_clip)
    assert calls == ["Audio/Music"]


def test_perform_ignore_all_marks_every_row():
    items = [_item(r"C:\Desktop\a.mov"), _item(r"C:\Desktop\b.mov")]
    rows = build_popup_rows(items, r"C:\Creators_Club", "alex")
    tracker = fixer.IgnoreTracker()

    perform_ignore_all(rows, tracker)

    assert tracker.is_ignored(r"C:\Desktop\a.mov")
    assert tracker.is_ignored(r"C:\Desktop\b.mov")
    assert not tracker.is_ignored(r"C:\Desktop\c.mov")
