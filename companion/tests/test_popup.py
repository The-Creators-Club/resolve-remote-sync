"""Popup logic tests (pure functions only — no real tkinter window is ever
created in tests; PopupDialog itself needs a live display and is exercised
manually per README.md's "known limitations")."""

from __future__ import annotations

from conftest import write_project_marker

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
    write_project_marker(tmp_path / "Projects" / "2026" / "Creator Profiles" / "Season 1")
    (tmp_path / "Projects" / "2025" / "FF4" / "Nuclear").mkdir(parents=True)
    write_project_marker(tmp_path / "Projects" / "2025" / "FF4" / "Nuclear")
    items = [_item(r"C:\Desktop\clip.mov", resolve_project_name="CCT Creator Profiles")]

    rows = build_popup_rows(
        items, str(tmp_path), "alex", project_prefix="Projects/2025/FF4/Nuclear",
    )

    assert rows[0]["suggested_dest"] == (
        "Projects/2026/Creator Profiles/Season 1/B-roll/Editor Added/alex"
    )


def test_build_popup_rows_falls_back_to_configured_project_prefix_when_unmatched(tmp_path):
    (tmp_path / "Projects" / "2026" / "Creator Profiles" / "Season 1").mkdir(parents=True)
    write_project_marker(tmp_path / "Projects" / "2026" / "Creator Profiles" / "Season 1")
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
    write_project_marker(tmp_path / "Projects" / "2026" / "Creator Profiles" / "Season 1")
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
    write_project_marker(tmp_path / "Projects" / "2026" / "Creator Profiles" / "Season 1")
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
    write_project_marker(tmp_path / "Projects" / "2026" / "Creator Profiles" / "Season 1")
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


# ===========================================================================
# AUDIT_2 round-2 regressions
# ===========================================================================


def test_no_display_fallback_actually_ignores_the_items(monkeypatch):
    """AUDIT_2 CORE-M3. show_popup's docstring promises the items are
    "auto-ignored so we don't spin forever re-popping the same clips" -- but
    the except branch only print()ed them (a NO-OP in the windowed build,
    where sys.stdout is None) and never touched ignore_tracker. The same
    batch re-popped, and re-failed, every 300 s forever."""
    from ccsync_companion import fixer, popup

    tracker = fixer.IgnoreTracker()

    def no_display(*a, **k):
        raise RuntimeError("no display name and no $DISPLAY environment variable")

    monkeypatch.setattr(popup, "PopupDialog", no_display)

    items = [
        {"file_path": r"G:\raw\A001.braw", "media_pool_item": object(),
         "clip_name": "A001", "resolve_project_name": ""},
        {"file_path": r"G:\raw\B002.wav", "media_pool_item": object(),
         "clip_name": "B002", "resolve_project_name": ""},
    ]
    popup.show_popup(items, "C:\\Creators_Club", "alex", tracker)

    assert tracker.is_ignored(r"G:\raw\A001.braw")
    assert tracker.is_ignored(r"G:\raw\B002.wav")


def test_build_popup_rows_carries_the_effective_prefix(tmp_path):
    """AUDIT_2 CORE-H3: the dialog needs the SAME prefix the suggestion used,
    or its dropdown offers destinations that never sync."""
    from ccsync_companion import popup

    rows = popup.build_popup_rows(
        [{"file_path": r"G:\x\clip.mov", "media_pool_item": object(),
          "clip_name": "clip", "resolve_project_name": "CCT S1"}],
        local_root=str(tmp_path), editor_name="ruskin",
        project_prefix="Projects/2026/CCT/Season 1",
    )
    assert rows[0]["effective_prefix"] == "Projects/2026/CCT/Season 1"
    assert rows[0]["suggested_dest"].startswith("Projects/2026/CCT/Season 1/")


# ===========================================================================
# AUDIT_2 UX-9 / UX-10: batch progress, rate estimation, stop-after-this-file
# ===========================================================================


def test_perform_fix_all_publishes_rich_per_chunk_state(tmp_path):
    """The overall bar needs a byte denominator, and the per-file bar needs
    updates DURING a file -- "35/69" alone is what made a working copy
    indistinguishable from a hang."""
    from ccsync_companion import popup

    a = tmp_path / "a.mov"
    a.write_bytes(b"x" * 1000)
    b = tmp_path / "b.mov"
    b.write_bytes(b"y" * 3000)
    rows = [
        {"file_path": str(a), "suggested_dest": "D", "clip_name": "a.mov", "media_pool_items": []},
        {"file_path": str(b), "suggested_dest": "D", "clip_name": "b.mov", "media_pool_items": []},
    ]

    def fake_fix(path, dest, root, mpis, on_bytes=None):
        total = 1000 if path.endswith("a.mov") else 3000
        for done in (0, total // 2, total):
            on_bytes(done, total)
        return {"ok": True, "message": "ok", "copied_to": dest}

    seen = []
    popup.perform_fix_all(rows, {}, str(tmp_path), fix_clip_fn=fake_fix,
                          state_fn=seen.append)

    assert popup.batch_total_bytes(rows) == 4000
    assert all(s["batch_bytes_total"] == 4000 for s in seen)
    mid_b = [s for s in seen if s["name"] == "b.mov" and s["file_bytes_done"] == 1500]
    assert mid_b, "per-file progress must be reported mid-file"
    # The batch counter must account for already-finished files.
    assert mid_b[0]["batch_bytes_done"] == 1000 + 1500
    assert seen[-1]["batch_bytes_done"] == 4000


def test_perform_fix_all_stops_between_files_never_mid_file(tmp_path):
    """UX-9's cancel. Between files ONLY: aborting a copy in flight is
    exactly what strands an orphaned multi-GB .ccsync-tmp for lane C to fan
    out to the fleet (CORE-H5)."""
    from ccsync_companion import popup

    rows = []
    for i in range(5):
        p = tmp_path / f"f{i}.mov"
        p.write_bytes(b"x" * 10)
        rows.append({"file_path": str(p), "suggested_dest": "D",
                     "clip_name": p.name, "media_pool_items": []})

    copied = []

    def fake_fix(path, dest, root, mpis, on_bytes=None):
        copied.append(path)
        return {"ok": True, "message": "ok", "copied_to": dest}

    results = popup.perform_fix_all(
        rows, {}, str(tmp_path), fix_clip_fn=fake_fix,
        should_stop=lambda: len(copied) >= 2,
    )
    assert len(copied) == 2
    assert len(results) == 2, "the remaining files are LEFT ALONE, not half-done"


def test_perform_fix_all_still_supports_the_old_three_arg_progress_fn(tmp_path):
    """Deliberate compatibility choice: progress_fn keeps its (done, total,
    result) signature and the rich channel is a SEPARATE state_fn, so every
    existing caller and test keeps working."""
    from ccsync_companion import popup

    p = tmp_path / "a.mov"
    p.write_bytes(b"x")
    rows = [{"file_path": str(p), "suggested_dest": "D", "clip_name": "a",
             "media_pool_items": []}]
    seen = []
    popup.perform_fix_all(
        rows, {}, str(tmp_path),
        fix_clip_fn=lambda a, b, c, d, on_bytes=None: {"ok": True, "message": "", "copied_to": b},
        progress_fn=lambda done, total, result: seen.append((done, total)),
    )
    assert seen == [(1, 1)]


def test_perform_fix_all_tolerates_a_fix_clip_double_without_on_bytes(tmp_path):
    from ccsync_companion import popup

    p = tmp_path / "a.mov"
    p.write_bytes(b"x")
    rows = [{"file_path": str(p), "suggested_dest": "D", "clip_name": "a",
             "media_pool_items": []}]
    results = popup.perform_fix_all(
        rows, {}, str(tmp_path),
        fix_clip_fn=lambda a, b, c, d: {"ok": True, "message": "", "copied_to": b},
    )
    assert results[0]["ok"] is True


# -- rate estimation --------------------------------------------------------


def test_rate_estimator_uses_a_rolling_window_not_a_cumulative_average():
    """A cumulative average takes minutes to react when SMB throughput
    changes -- the opposite of what someone staring at a stalled-looking
    dialog needs."""
    from ccsync_companion.popup import RateEstimator

    clock = {"t": 0.0}
    est = RateEstimator(window_seconds=5.0, clock=lambda: clock["t"])

    # 10 s of 1 MB/s...
    for i in range(11):
        clock["t"] = float(i)
        est.observe(i * 1_000_000)
    # ...then it jumps to 10 MB/s.
    for i in range(1, 6):
        clock["t"] = 10.0 + i
        est.observe(10_000_000 + i * 10_000_000)

    speed = est.speed_bps()
    assert speed > 5_000_000, (
        f"a rolling window must track the new rate, got {speed}; a cumulative "
        f"average would still read ~2.6 MB/s"
    )


def test_rate_estimator_is_undefined_until_it_has_two_samples():
    from ccsync_companion.popup import RateEstimator

    est = RateEstimator()
    assert est.speed_bps() is None
    assert est.eta_seconds(0, 100) is None


def test_rate_estimator_eta():
    from ccsync_companion.popup import RateEstimator

    clock = {"t": 0.0}
    est = RateEstimator(window_seconds=10.0, clock=lambda: clock["t"])
    est.observe(0)
    clock["t"] = 2.0
    est.observe(2_000_000)  # 1 MB/s
    assert abs(est.eta_seconds(2_000_000, 12_000_000) - 10.0) < 0.5
    assert est.eta_seconds(100, 100) is None  # already done


# -- the strings an editor actually reads ----------------------------------


def test_format_file_progress_matches_the_audits_example():
    from ccsync_companion.popup import format_file_progress

    line = format_file_progress("A001_C012.braw", 4_402_341_478, 13_636_916_838,
                                34_603_008, 260)
    assert 'Copying "A001_C012.braw"' in line
    assert "GB of" in line
    assert "MB/s" in line
    assert "~4 min left" in line


def test_format_batch_progress_matches_the_audits_example():
    from ccsync_companion.popup import format_batch_progress

    line = format_batch_progress(35, 69, 137_438_953_472, 431_620_000_000)
    assert line.startswith("File 35 of 69")
    assert "GB of" in line and "done" in line


def test_human_eta_wording():
    from ccsync_companion.popup import human_eta

    assert human_eta(0) == "almost done"
    assert human_eta(45) == "~45 sec left"
    assert human_eta(600) == "~10 min left"
    assert human_eta(7500) == "~2h 5m left"
    assert human_eta(None) == ""


# -- ProgressWindow (headless path) ----------------------------------------


def test_progress_window_runs_the_worker_even_with_no_display(monkeypatch):
    """The window is decoration; the copy must complete regardless. A
    progress UI that can prevent the work from happening is worse than none."""
    from ccsync_companion import popup

    window = popup.ProgressWindow("COPYING", "originals are copied, never moved")
    monkeypatch.setattr(
        window, "_show",
        lambda: (_ for _ in ()).throw(RuntimeError("no display name and no $DISPLAY")),
    )

    ran = []

    def worker(publish, should_stop):
        publish({"name": "a.mov", "file_bytes_done": 1, "file_bytes_total": 2,
                 "batch_bytes_done": 1, "batch_bytes_total": 2, "index": 1, "total": 1})
        ran.append(should_stop())

    window.run(worker)
    assert ran == [False]


def test_progress_window_stop_flag_is_visible_to_the_worker(monkeypatch):
    from ccsync_companion import popup

    window = popup.ProgressWindow("COPYING")
    monkeypatch.setattr(window, "_show", lambda: None)
    window._on_stop()

    seen = []
    window.run(lambda publish, should_stop: seen.append(should_stop()))
    assert seen == [True]


# -- cloud placeholders in the UI -----------------------------------------


def test_preflight_summary_warns_about_online_only_files(tmp_path, monkeypatch):
    """This single line would have prevented the whole 2026-07-25
    confusion."""
    from ccsync_companion import fixer, popup

    rows = []
    for i in range(69):
        p = tmp_path / f"f{i}.mp4"
        p.write_bytes(b"x")
        rows.append({"file_path": str(p), "suggested_dest": "D", "clip_name": p.name,
                     "media_pool_items": []})

    online = {str(tmp_path / f"f{i}.mp4") for i in range(12)}
    monkeypatch.setattr(fixer, "is_placeholder", lambda p: p in online)

    text = popup.preflight_summary(rows)
    assert "12 of 69" in text
    assert "online-only" in text
    assert "0%" in text, "must explain WHY the bar will sit still"

    monkeypatch.setattr(fixer, "is_placeholder", lambda p: False)
    assert popup.preflight_summary(rows) == ""


def test_progress_line_says_waiting_for_download_not_copying():
    """The per-file byte bar legitimately reads 0% for the whole hydration.
    "Copying ... 0 B of 1.2 GB" for ten minutes is exactly the display that
    destroys trust and gets the window force-quit."""
    from ccsync_companion.popup import format_file_progress

    waiting = format_file_progress("The Billion Dollar Buddhists.mp4", 0, 1_288_490_188,
                                   None, None, placeholder=True)
    assert waiting.startswith("Waiting for your cloud drive to download")
    assert "1.2 GB" in waiting
    assert "Copying" not in waiting

    # Once bytes actually move it switches to the normal copy line.
    moving = format_file_progress("The Billion Dollar Buddhists.mp4", 100_000_000,
                                  1_288_490_188, 33_000_000, 40, placeholder=True)
    assert moving.startswith('Copying "')
    assert "Waiting" not in moving


def test_perform_fix_all_publishes_the_placeholder_flag(tmp_path, monkeypatch):
    from ccsync_companion import fixer, popup

    p = tmp_path / "online.mp4"
    p.write_bytes(b"x" * 100)
    rows = [{"file_path": str(p), "suggested_dest": "D", "clip_name": "online.mp4",
             "media_pool_items": []}]
    monkeypatch.setattr(fixer, "is_placeholder", lambda path: True)

    seen = []
    popup.perform_fix_all(
        rows, {}, str(tmp_path), state_fn=seen.append,
        fix_clip_fn=lambda a, b, c, d, on_bytes=None: {"ok": True, "message": "", "copied_to": b},
    )
    assert seen[0]["placeholder"] is True


def test_a_failure_does_not_stop_the_batch(tmp_path):
    """Existing behaviour, now pinned: one bad file must not abandon the
    other 68."""
    from ccsync_companion import popup

    rows = []
    for i in range(4):
        p = tmp_path / f"f{i}.mov"
        p.write_bytes(b"x")
        rows.append({"file_path": str(p), "suggested_dest": "D", "clip_name": p.name,
                     "media_pool_items": []})

    def flaky(path, dest, root, mpis, on_bytes=None):
        ok = not path.endswith("f1.mov")
        return {"ok": ok, "message": "" if ok else "cloud download failed",
                "copied_to": dest if ok else None}

    results = popup.perform_fix_all(rows, {}, str(tmp_path), fix_clip_fn=flaky)
    assert len(results) == 4
    assert [r["ok"] for r in results] == [True, False, True, True]
