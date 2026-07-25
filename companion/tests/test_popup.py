"""Popup logic tests (pure functions only — no real tkinter window is ever
created in tests; PopupDialog itself needs a live display and is exercised
manually per README.md's "known limitations")."""

from __future__ import annotations

from ccsync_companion import fixer
from ccsync_companion.popup import (
    build_popup_rows,
    dedupe_out_of_tree_items,
    perform_fix_all,
    perform_ignore_all,
)


def _item(file_path, clip_name=None, media_pool_item=None, resolve_project_name=""):
    return {
        "file_path": file_path,
        "media_pool_item": media_pool_item if media_pool_item is not None else object(),
        "clip_name": clip_name,
        "resolve_project_name": resolve_project_name,
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


# -- dedupe_out_of_tree_items ------------------------------------------------


def test_dedupe_collapses_same_path_different_case_and_slashes():
    mpi_a, mpi_b = object(), object()
    items = [
        _item(r"C:\Creators_Club\Clip.mov", media_pool_item=mpi_a),
        _item(r"c:\creators_club\CLIP.mov", media_pool_item=mpi_b),
    ]
    merged = dedupe_out_of_tree_items(items)
    assert len(merged) == 1
    assert merged[0]["media_pool_items"] == [mpi_a, mpi_b]


def test_dedupe_preserves_distinct_paths_as_separate_rows():
    items = [_item(r"C:\Desktop\a.mov"), _item(r"C:\Desktop\b.mov")]
    merged = dedupe_out_of_tree_items(items)
    assert len(merged) == 2
    assert {m["file_path"] for m in merged} == {r"C:\Desktop\a.mov", r"C:\Desktop\b.mov"}


def test_dedupe_preserves_first_seen_order():
    items = [_item(r"C:\Desktop\z.mov"), _item(r"C:\Desktop\a.mov"), _item(r"C:\Desktop\z.mov")]
    merged = dedupe_out_of_tree_items(items)
    assert [m["file_path"] for m in merged] == [r"C:\Desktop\z.mov", r"C:\Desktop\a.mov"]


def test_dedupe_three_timeline_items_one_path_keeps_all_three_media_pool_items():
    mpis = [object(), object(), object()]
    items = [_item(r"C:\Desktop\clip.mov", media_pool_item=m) for m in mpis]
    merged = dedupe_out_of_tree_items(items)
    assert len(merged) == 1
    assert merged[0]["media_pool_items"] == mpis


def test_build_popup_rows_always_dedupes_before_building():
    items = [_item(r"C:\Desktop\track.wav"), _item(r"C:\desktop\TRACK.WAV")]
    rows = build_popup_rows(items, r"C:\Creators_Club", "alex")
    assert len(rows) == 1
    assert len(rows[0]["media_pool_items"]) == 2


# -- project-aware destination suggestion (fallback order) -------------------


def test_build_popup_rows_prefers_matched_resolve_project(tmp_path):
    (tmp_path / "Projects" / "2026" / "Creator Profiles" / "Season 1").mkdir(parents=True)
    (tmp_path / "Projects" / "2025" / "FF4" / "Nuclear").mkdir(parents=True)
    items = [_item(r"C:\Desktop\clip.mov", resolve_project_name="CCT Creator Profiles")]

    rows = build_popup_rows(
        items, str(tmp_path), "alex", project_prefix="Projects/2025/FF4/Nuclear",
    )

    assert rows[0]["suggested_dest"] == (
        "Projects/2026/Creator Profiles/Season 1/B-roll/Editor Added/alex"
    )


def test_build_popup_rows_falls_back_to_configured_project_prefix_when_unmatched(tmp_path):
    (tmp_path / "Projects" / "2026" / "Creator Profiles" / "Season 1").mkdir(parents=True)
    items = [_item(r"C:\Desktop\clip.mov", resolve_project_name="Some Unrelated Show")]

    rows = build_popup_rows(
        items, str(tmp_path), "alex", project_prefix="Projects/2025/FF4/Nuclear",
    )

    assert rows[0]["suggested_dest"] == "Projects/2025/FF4/Nuclear/B-roll/Editor Added/alex"


def test_build_popup_rows_falls_back_to_tree_root_when_nothing_matches(tmp_path):
    items = [_item(r"C:\Desktop\clip.mov", resolve_project_name="Some Unrelated Show")]

    rows = build_popup_rows(items, str(tmp_path), "alex", project_prefix="")

    assert rows[0]["suggested_dest"] == "B-roll/Editor Added/alex"


# -- server_roots (dashboard's sticky per-Resolve-project mapping) -----------


def test_build_popup_rows_server_roots_wins_over_local_matching(tmp_path):
    # A tree dir exists that WOULD locally match by token overlap, but the
    # server mapping must take priority over fixer.pick_project_prefix.
    (tmp_path / "Projects" / "2026" / "Creator Profiles" / "Season 1").mkdir(parents=True)
    items = [_item(r"C:\Desktop\clip.mov", resolve_project_name="CCT Creator Profiles")]

    server_roots = {"cct creator profiles": "Projects/2099/Server/Override"}
    rows = build_popup_rows(
        items, str(tmp_path), "alex", project_prefix="Projects/2025/FF4/Nuclear",
        server_roots=server_roots,
    )

    assert rows[0]["suggested_dest"] == "Projects/2099/Server/Override/B-roll/Editor Added/alex"


def test_build_popup_rows_server_roots_lookup_is_case_insensitive(tmp_path):
    items = [_item(r"C:\Desktop\clip.mov", resolve_project_name="CCT Creator Profiles")]

    server_roots = {"cct creator profiles": "Projects/2026/Creator Profiles/Season 1"}
    rows = build_popup_rows(items, str(tmp_path), "alex", server_roots=server_roots)

    assert rows[0]["suggested_dest"] == (
        "Projects/2026/Creator Profiles/Season 1/B-roll/Editor Added/alex"
    )


def test_build_popup_rows_server_roots_absent_entry_falls_through_to_existing_chain(tmp_path):
    (tmp_path / "Projects" / "2026" / "Creator Profiles" / "Season 1").mkdir(parents=True)
    items = [_item(r"C:\Desktop\clip.mov", resolve_project_name="CCT Creator Profiles")]

    # server_roots is provided but has no entry for this project -- must
    # fall through to the local pick_project_prefix chain, not the tree root.
    server_roots = {"some other project": "Projects/2099/Whatever"}
    rows = build_popup_rows(
        items, str(tmp_path), "alex", project_prefix="Projects/2025/FF4/Nuclear",
        server_roots=server_roots,
    )

    assert rows[0]["suggested_dest"] == (
        "Projects/2026/Creator Profiles/Season 1/B-roll/Editor Added/alex"
    )


def test_build_popup_rows_server_roots_none_falls_through_to_existing_chain(tmp_path):
    (tmp_path / "Projects" / "2026" / "Creator Profiles" / "Season 1").mkdir(parents=True)
    items = [_item(r"C:\Desktop\clip.mov", resolve_project_name="CCT Creator Profiles")]

    rows = build_popup_rows(items, str(tmp_path), "alex", server_roots=None)

    assert rows[0]["suggested_dest"] == (
        "Projects/2026/Creator Profiles/Season 1/B-roll/Editor Added/alex"
    )


def test_build_popup_rows_server_roots_empty_dict_falls_through_to_existing_chain(tmp_path):
    items = [_item(r"C:\Desktop\clip.mov", resolve_project_name="Some Unrelated Show")]

    rows = build_popup_rows(
        items, str(tmp_path), "alex", project_prefix="Projects/2025/FF4/Nuclear",
        server_roots={},
    )

    assert rows[0]["suggested_dest"] == "Projects/2025/FF4/Nuclear/B-roll/Editor Added/alex"


# -- perform_fix_all with grouped media_pool_items ----------------------------


def test_perform_fix_all_passes_all_grouped_media_pool_items_to_fix_clip():
    mpi_a, mpi_b = object(), object()
    items = [
        _item(r"C:\Desktop\clip.mov", media_pool_item=mpi_a),
        _item(r"c:\desktop\CLIP.mov", media_pool_item=mpi_b),
    ]
    rows = build_popup_rows(items, r"C:\Creators_Club", "alex")

    calls = []

    def fake_fix_clip(file_path, dest_rel, local_root, media_pool_items):
        calls.append(media_pool_items)
        return {"ok": True, "message": "ok", "copied_to": "x"}

    perform_fix_all(rows, {}, r"C:\Creators_Club", fix_clip_fn=fake_fix_clip)
    assert calls == [[mpi_a, mpi_b]]


def test_perform_fix_all_falls_back_to_suggestion_when_selection_is_blank():
    items = [_item(r"C:\Desktop\track.wav")]
    rows = build_popup_rows(items, r"C:\Creators_Club", "alex")

    calls = []

    def fake_fix_clip(file_path, dest_rel, local_root, media_pool_items):
        calls.append(dest_rel)
        return {"ok": True, "message": "ok", "copied_to": "x"}

    # a row whose combobox got cleared to "" must still fall back to a
    # valid default, never fix with an empty destination.
    perform_fix_all(
        rows, {r"C:\Desktop\track.wav": ""}, r"C:\Creators_Club", fix_clip_fn=fake_fix_clip,
    )
    assert calls == ["Audio/Music"]


# -- fix-all progress callback (worker-thread UI-hang fix) --------------------


def test_perform_fix_all_reports_progress_per_row():
    rows = [
        {"file_path": f"C:\\x\\f{i}.wav", "media_pool_items": [object()],
         "suggested_dest": "Audio/Music"}
        for i in range(3)
    ]

    def fake_fix_clip(path, dest, root, mpis):
        return {"ok": True, "message": "ok", "copied_to": dest}

    seen = []
    perform_fix_all(rows, {}, r"C:\root", fix_clip_fn=fake_fix_clip,
                    progress_fn=lambda done, total, res: seen.append((done, total, res["ok"])))
    assert seen == [(1, 3, True), (2, 3, True), (3, 3, True)]


def test_perform_fix_all_progress_survives_callback_error():
    rows = [{"file_path": "C:\\x\\f.wav", "media_pool_items": [object()],
             "suggested_dest": "Audio/Music"}]

    def fake_fix_clip(path, dest, root, mpis):
        return {"ok": True, "message": "ok", "copied_to": dest}

    def boom(done, total, res):
        raise RuntimeError("ui gone")

    # a throwing progress callback must not abort the batch
    results = perform_fix_all(rows, {}, r"C:\root", fix_clip_fn=fake_fix_clip, progress_fn=boom)
    assert len(results) == 1 and results[0]["ok"] is True


def test_perform_fix_all_continues_past_failures():
    rows = [
        {"file_path": "C:\\x\\a.wav", "media_pool_items": [object()], "suggested_dest": "Audio/Music"},
        {"file_path": "C:\\x\\b.wav", "media_pool_items": [object()], "suggested_dest": "Audio/Music"},
        {"file_path": "C:\\x\\c.wav", "media_pool_items": [object()], "suggested_dest": "Audio/Music"},
    ]

    def fake_fix_clip(path, dest, root, mpis):
        ok = not path.endswith("b.wav")
        return {"ok": ok, "message": "boom" if not ok else "ok", "copied_to": dest}

    results = perform_fix_all(rows, {}, r"C:\root", fix_clip_fn=fake_fix_clip)
    assert [r["ok"] for r in results] == [True, False, True]  # one failure doesn't stop the rest
