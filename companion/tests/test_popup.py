"""Popup logic tests (pure functions only — no real tkinter window is ever
created in tests; PopupDialog itself needs a live display and is exercised
manually per README.md's "known limitations")."""

from __future__ import annotations

import pytest

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
    rows = build_popup_rows(items, r"C:\Creators_Club", "owen")
    assert rows[0]["suggested_dest"] == "Audio/Music"
    assert rows[1]["suggested_dest"] == "B-roll/Editor Added/owen"


def test_build_popup_rows_falls_back_to_basename_for_clip_name():
    items = [_item(r"C:\Desktop\track.wav", clip_name=None)]
    rows = build_popup_rows(items, r"C:\Creators_Club", "owen")
    assert rows[0]["clip_name"] == "track.wav"


def test_perform_fix_all_uses_selection_over_suggestion(tmp_path):
    items = [_item(str(tmp_path / "track.wav"))]
    (tmp_path / "track.wav").write_text("audio")
    rows = build_popup_rows(items, str(tmp_path / "root"), "owen")

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
    rows = build_popup_rows(items, r"C:\Creators_Club", "owen")

    calls = []

    def fake_fix_clip(file_path, dest_rel, local_root, media_pool_item):
        calls.append(dest_rel)
        return {"ok": True, "message": "ok", "copied_to": "x"}

    perform_fix_all(rows, {}, r"C:\Creators_Club", fix_clip_fn=fake_fix_clip)
    assert calls == ["Audio/Music"]


def test_perform_ignore_all_marks_every_row():
    items = [_item(r"C:\Desktop\a.mov"), _item(r"C:\Desktop\b.mov")]
    rows = build_popup_rows(items, r"C:\Creators_Club", "owen")
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
    rows = build_popup_rows(items, r"C:\Creators_Club", "owen")
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
        items, str(tmp_path), "owen", project_prefix="Projects/2025/FF4/Nuclear",
    )

    assert rows[0]["suggested_dest"] == (
        "Projects/2026/Creator Profiles/Season 1/B-roll/Editor Added/owen"
    )


def test_build_popup_rows_falls_back_to_configured_project_prefix_when_unmatched(tmp_path):
    (tmp_path / "Projects" / "2026" / "Creator Profiles" / "Season 1").mkdir(parents=True)
    write_project_marker(tmp_path / "Projects" / "2026" / "Creator Profiles" / "Season 1")
    items = [_item(r"C:\Desktop\clip.mov", resolve_project_name="Some Unrelated Show")]

    rows = build_popup_rows(
        items, str(tmp_path), "owen", project_prefix="Projects/2025/FF4/Nuclear",
    )

    assert rows[0]["suggested_dest"] == "Projects/2025/FF4/Nuclear/B-roll/Editor Added/owen"


def test_build_popup_rows_falls_back_to_tree_root_when_nothing_matches(tmp_path):
    items = [_item(r"C:\Desktop\clip.mov", resolve_project_name="Some Unrelated Show")]

    rows = build_popup_rows(items, str(tmp_path), "owen", project_prefix="")

    assert rows[0]["suggested_dest"] == "B-roll/Editor Added/owen"


# -- server_roots (dashboard's sticky per-Resolve-project mapping) -----------


def test_build_popup_rows_server_roots_wins_over_local_matching(tmp_path):
    # A tree dir exists that WOULD locally match by token overlap, but the
    # server mapping must take priority over fixer.pick_project_prefix.
    (tmp_path / "Projects" / "2026" / "Creator Profiles" / "Season 1").mkdir(parents=True)
    write_project_marker(tmp_path / "Projects" / "2026" / "Creator Profiles" / "Season 1")
    items = [_item(r"C:\Desktop\clip.mov", resolve_project_name="CCT Creator Profiles")]

    server_roots = {"cct creator profiles": "Projects/2099/Server/Override"}
    rows = build_popup_rows(
        items, str(tmp_path), "owen", project_prefix="Projects/2025/FF4/Nuclear",
        server_roots=server_roots,
    )

    assert rows[0]["suggested_dest"] == "Projects/2099/Server/Override/B-roll/Editor Added/owen"


def test_build_popup_rows_server_roots_lookup_is_case_insensitive(tmp_path):
    items = [_item(r"C:\Desktop\clip.mov", resolve_project_name="CCT Creator Profiles")]

    server_roots = {"cct creator profiles": "Projects/2026/Creator Profiles/Season 1"}
    rows = build_popup_rows(items, str(tmp_path), "owen", server_roots=server_roots)

    assert rows[0]["suggested_dest"] == (
        "Projects/2026/Creator Profiles/Season 1/B-roll/Editor Added/owen"
    )


def test_build_popup_rows_server_roots_absent_entry_falls_through_to_existing_chain(tmp_path):
    (tmp_path / "Projects" / "2026" / "Creator Profiles" / "Season 1").mkdir(parents=True)
    write_project_marker(tmp_path / "Projects" / "2026" / "Creator Profiles" / "Season 1")
    items = [_item(r"C:\Desktop\clip.mov", resolve_project_name="CCT Creator Profiles")]

    # server_roots is provided but has no entry for this project -- must
    # fall through to the local pick_project_prefix chain, not the tree root.
    server_roots = {"some other project": "Projects/2099/Whatever"}
    rows = build_popup_rows(
        items, str(tmp_path), "owen", project_prefix="Projects/2025/FF4/Nuclear",
        server_roots=server_roots,
    )

    assert rows[0]["suggested_dest"] == (
        "Projects/2026/Creator Profiles/Season 1/B-roll/Editor Added/owen"
    )


def test_build_popup_rows_server_roots_none_falls_through_to_existing_chain(tmp_path):
    (tmp_path / "Projects" / "2026" / "Creator Profiles" / "Season 1").mkdir(parents=True)
    write_project_marker(tmp_path / "Projects" / "2026" / "Creator Profiles" / "Season 1")
    items = [_item(r"C:\Desktop\clip.mov", resolve_project_name="CCT Creator Profiles")]

    rows = build_popup_rows(items, str(tmp_path), "owen", server_roots=None)

    assert rows[0]["suggested_dest"] == (
        "Projects/2026/Creator Profiles/Season 1/B-roll/Editor Added/owen"
    )


def test_build_popup_rows_server_roots_empty_dict_falls_through_to_existing_chain(tmp_path):
    items = [_item(r"C:\Desktop\clip.mov", resolve_project_name="Some Unrelated Show")]

    rows = build_popup_rows(
        items, str(tmp_path), "owen", project_prefix="Projects/2025/FF4/Nuclear",
        server_roots={},
    )

    assert rows[0]["suggested_dest"] == "Projects/2025/FF4/Nuclear/B-roll/Editor Added/owen"


# -- perform_fix_all with grouped media_pool_items ----------------------------


def test_perform_fix_all_passes_all_grouped_media_pool_items_to_fix_clip():
    mpi_a, mpi_b = object(), object()
    items = [
        _item(r"C:\Desktop\clip.mov", media_pool_item=mpi_a),
        _item(r"c:\desktop\CLIP.mov", media_pool_item=mpi_b),
    ]
    rows = build_popup_rows(items, r"C:\Creators_Club", "owen")

    calls = []

    def fake_fix_clip(file_path, dest_rel, local_root, media_pool_items):
        calls.append(media_pool_items)
        return {"ok": True, "message": "ok", "copied_to": "x"}

    perform_fix_all(rows, {}, r"C:\Creators_Club", fix_clip_fn=fake_fix_clip)
    assert calls == [[mpi_a, mpi_b]]


def test_perform_fix_all_falls_back_to_suggestion_when_selection_is_blank():
    items = [_item(r"C:\Desktop\track.wav")]
    rows = build_popup_rows(items, r"C:\Creators_Club", "owen")

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
    popup.show_popup(items, "C:\\Creators_Club", "owen", tracker)

    assert tracker.is_ignored(r"G:\raw\A001.braw")
    assert tracker.is_ignored(r"G:\raw\B002.wav")


def test_build_popup_rows_carries_the_effective_prefix(tmp_path):
    """AUDIT_2 CORE-H3: the dialog needs the SAME prefix the suggestion used,
    or its dropdown offers destinations that never sync."""
    from ccsync_companion import popup

    rows = popup.build_popup_rows(
        [{"file_path": r"G:\x\clip.mov", "media_pool_item": object(),
          "clip_name": "clip", "resolve_project_name": "CCT S1"}],
        local_root=str(tmp_path), editor_name="editor2",
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


def test_the_fixer_dialog_gets_the_app_icon_like_every_other_root():
    """PopupDialog._build was the one root that never called
    theme.apply_window_icon, so the dialog an editor sees most often -- the
    one asking about their media -- showed the default Tk feather and read as
    "some random program". Source-level because the real window cannot be
    built in a test (see conftest._no_real_tk_windows)."""
    import inspect

    from ccsync_companion import popup

    for builder in (popup.PopupDialog._build, popup.ProgressWindow._show):
        source = inspect.getsource(builder)
        assert "apply_window_icon" in source, f"{builder.__qualname__} has no app icon"


def test_the_batch_bar_never_counts_bytes_that_were_not_copied(tmp_path):
    """`batch_done += file_total` ran for EVERY row, including aborted and
    failed ones -- and fixer.fix_clip deletes both artifacts of a failed or
    abandoned attempt before returning, so the bar, the "X of Y done" text and
    RateEstimator's speed/ETA were all credited with bytes that are not on
    disk. Worst exactly where the editor is watching hardest: a run where
    things went wrong."""
    from ccsync_companion import popup

    good = tmp_path / "good.mov"
    good.write_bytes(b"x" * 1000)
    bad = tmp_path / "bad.mov"
    bad.write_bytes(b"y" * 3000)
    skipped = tmp_path / "skipped.mov"
    skipped.write_bytes(b"z" * 6000)
    rows = [
        {"file_path": str(p), "suggested_dest": "D", "clip_name": p.name,
         "media_pool_items": []}
        for p in (good, bad, skipped)
    ]

    def fake_fix(path, dest, root, mpis, on_bytes=None):
        if path.endswith("good.mov"):
            return {"ok": True, "message": "ok", "copied_to": dest}
        if path.endswith("bad.mov"):
            return {"ok": False, "message": "disk full"}
        return {"ok": False, "aborted": True, "message": "skipped by you"}

    seen = []
    popup.perform_fix_all(rows, {}, str(tmp_path), fix_clip_fn=fake_fix,
                          state_fn=seen.append)

    assert seen[-1]["batch_bytes_total"] == 10000
    assert seen[-1]["batch_bytes_done"] == 1000
    assert seen[-1]["fixed"] == 1
    assert seen[-1]["failed"] == 1
    assert seen[-1]["skipped"] == 1


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


# ===========================================================================
# [ SKIP THIS FILE ] and [ CANCEL ALL ] (mid-file), alongside the older
# [ STOP AFTER THIS FILE ] (between files)
# ===========================================================================


def _rows(tmp_path, count=4, size=10):
    rows = []
    for i in range(count):
        p = tmp_path / f"f{i}.mov"
        p.write_bytes(b"x" * size)
        rows.append({"file_path": str(p), "suggested_dest": "D",
                     "clip_name": p.name, "media_pool_items": []})
    return rows


def test_skip_this_file_abandons_one_file_and_continues_the_batch(tmp_path):
    """The whole point of SKIP: the rest of the list still gets copied."""
    from ccsync_companion import popup

    rows = _rows(tmp_path, 4)
    control = popup.BatchControl()
    attempted, relinked = [], []

    def fake_fix(path, dest, root, mpis, on_bytes=None, should_abort=None):
        attempted.append(path)
        if path.endswith("f1.mov"):
            control.request_skip_current()          # the user clicks, mid-copy
            if should_abort():
                return {"ok": False, "aborted": True, "copied_to": None,
                        "leftover_paths": [], "message": "Skipped by you"}
        relinked.append(path)
        return {"ok": True, "message": "ok", "copied_to": dest}

    results = popup.perform_fix_all(rows, {}, str(tmp_path), fix_clip_fn=fake_fix,
                                    control=control)

    assert len(attempted) == 4, "every file is still attempted after a skip"
    assert len(results) == 4
    assert [r.get("aborted", False) for r in results] == [False, True, False, False]
    assert not any(p.endswith("f1.mov") for p in relinked), (
        "the skipped file must not be relinked in Resolve"
    )


def test_cancel_all_stops_the_batch_immediately(tmp_path):
    """CANCEL ALL abandons the file in flight AND everything after it."""
    from ccsync_companion import popup

    rows = _rows(tmp_path, 5)
    control = popup.BatchControl()
    attempted = []

    def fake_fix(path, dest, root, mpis, on_bytes=None, should_abort=None):
        attempted.append(path)
        if path.endswith("f1.mov"):
            control.request_cancel_all()
            if should_abort():
                return {"ok": False, "aborted": True, "copied_to": None,
                        "leftover_paths": [], "message": "Skipped by you"}
        return {"ok": True, "message": "ok", "copied_to": dest}

    results = popup.perform_fix_all(rows, {}, str(tmp_path), fix_clip_fn=fake_fix,
                                    control=control)

    assert len(attempted) == 2, f"the batch kept going after CANCEL ALL: {attempted}"
    assert len(results) == 2
    assert results[-1]["aborted"] is True
    assert all(not r.get("aborted") for r in results[:-1])


def test_cancel_all_between_files_never_starts_the_next_one(tmp_path):
    from ccsync_companion import popup

    rows = _rows(tmp_path, 5)
    control = popup.BatchControl()
    attempted = []

    def fake_fix(path, dest, root, mpis, on_bytes=None, should_abort=None):
        attempted.append(path)
        if len(attempted) == 2:
            control.request_cancel_all()            # lands after the copy ends
        return {"ok": True, "message": "ok", "copied_to": dest}

    results = popup.perform_fix_all(rows, {}, str(tmp_path), fix_clip_fn=fake_fix,
                                    control=control)
    assert len(attempted) == 2
    assert len(results) == 2 and all(r["ok"] for r in results)


def test_stop_after_this_file_still_finishes_the_file_it_is_on(tmp_path):
    """The graceful control must stay lossless -- that is why SKIP is a
    separate button and not a change of meaning."""
    from ccsync_companion import popup

    rows = _rows(tmp_path, 4)
    control = popup.BatchControl()
    finished = []

    def fake_fix(path, dest, root, mpis, on_bytes=None, should_abort=None):
        if path.endswith("f0.mov"):
            control.request_stop_after_file()       # clicked mid-copy
        assert should_abort is None or not should_abort(), (
            "STOP AFTER THIS FILE must never abort the copy in flight"
        )
        finished.append(path)
        return {"ok": True, "message": "ok", "copied_to": dest}

    results = popup.perform_fix_all(rows, {}, str(tmp_path), fix_clip_fn=fake_fix,
                                    control=control, should_stop=control.should_stop)

    assert len(finished) == 1, "the file in flight is COMPLETED, then the batch stops"
    assert results[0]["ok"] is True


def test_a_skip_click_between_files_does_not_abandon_the_next_file(tmp_path):
    """The skip flag is per-file and re-armed by the loop: a click that lands
    in the gap between two files must not abandon a file the user never saw
    start copying."""
    from ccsync_companion import popup

    rows = _rows(tmp_path, 3)
    control = popup.BatchControl()
    control.request_skip_current()                  # set BEFORE the run starts
    aborts = []

    def fake_fix(path, dest, root, mpis, on_bytes=None, should_abort=None):
        aborts.append(bool(should_abort()))
        return {"ok": True, "message": "ok", "copied_to": dest}

    popup.perform_fix_all(rows, {}, str(tmp_path), fix_clip_fn=fake_fix, control=control)
    assert aborts == [False, False, False]


def test_perform_fix_all_publishes_the_new_counts_without_touching_the_old_keys(tmp_path):
    from ccsync_companion import popup

    rows = _rows(tmp_path, 3)
    control = popup.BatchControl()
    control.request_skip_current()

    def fake_fix(path, dest, root, mpis, on_bytes=None, should_abort=None):
        if path.endswith("f1.mov"):
            control.request_skip_current()
            return {"ok": False, "aborted": True, "copied_to": None,
                    "leftover_paths": [], "message": "Skipped by you"}
        return {"ok": True, "message": "ok", "copied_to": dest}

    seen = []
    popup.perform_fix_all(rows, {}, str(tmp_path), fix_clip_fn=fake_fix,
                          state_fn=seen.append, control=control)

    final = seen[-1]
    assert final["fixed"] == 2 and final["skipped"] == 1 and final["failed"] == 0
    assert final["cancelled"] is False
    # the pre-existing keys are still all there, unchanged in meaning
    for key in ("index", "total", "name", "file_bytes_done", "file_bytes_total",
                "batch_bytes_done", "batch_bytes_total", "stopped"):
        assert key in final


def test_perform_fix_all_marks_cancelled_in_the_final_state(tmp_path):
    from ccsync_companion import popup

    rows = _rows(tmp_path, 3)
    control = popup.BatchControl()

    def fake_fix(path, dest, root, mpis, on_bytes=None, should_abort=None):
        control.request_cancel_all()
        return {"ok": False, "aborted": True, "copied_to": None,
                "leftover_paths": [], "message": "Skipped by you"}

    seen = []
    popup.perform_fix_all(rows, {}, str(tmp_path), fix_clip_fn=fake_fix,
                          state_fn=seen.append, control=control)
    assert seen[-1]["cancelled"] is True
    assert seen[-1]["stopped"] is True
    assert seen[-1]["skipped"] == 1


def test_perform_fix_all_passes_the_abort_poll_into_fix_clip(tmp_path):
    """End to end: the Tk button sets a BatchControl flag, and the copy sees
    it through fix_clip's should_abort -- that poll is what
    fixer.copy_with_progress checks once per 8 MB chunk."""
    from ccsync_companion import popup

    rows = _rows(tmp_path, 1)
    control = popup.BatchControl()
    polls = []

    def fake_fix(path, dest, root, mpis, on_bytes=None, should_abort=None):
        polls.append(should_abort())
        control.request_skip_current()              # "the user clicks"
        polls.append(should_abort())
        return {"ok": True, "message": "ok", "copied_to": dest}

    popup.perform_fix_all(rows, {}, str(tmp_path), fix_clip_fn=fake_fix, control=control)
    assert polls == [False, True]


def test_perform_fix_all_without_a_control_is_exactly_the_old_behaviour(tmp_path):
    """Every existing caller passes no control and must keep working, right
    down to the fix_clip doubles written against the older signatures."""
    from ccsync_companion import popup

    rows = _rows(tmp_path, 2)
    results = popup.perform_fix_all(
        rows, {}, str(tmp_path),
        fix_clip_fn=lambda a, b, c, d: {"ok": True, "message": "", "copied_to": b},
    )
    assert [r["ok"] for r in results] == [True, True]


def test_call_fix_clip_drops_kwargs_the_double_does_not_accept(tmp_path):
    from ccsync_companion import popup

    def oldest(path, dest, root, mpis):
        return {"ok": True, "message": "oldest", "copied_to": dest}

    def with_on_bytes(path, dest, root, mpis, on_bytes=None):
        return {"ok": True, "message": "on_bytes", "copied_to": dest}

    def newest(path, dest, root, mpis, on_bytes=None, should_abort=None):
        return {"ok": True, "message": "newest", "copied_to": dest}

    args = ("p", "d", "r", [])
    poll = (lambda: False)
    assert popup.call_fix_clip(oldest, args, on_bytes=None,
                               should_abort=poll)["message"] == "oldest"
    assert popup.call_fix_clip(with_on_bytes, args, on_bytes=None,
                               should_abort=poll)["message"] == "on_bytes"
    assert popup.call_fix_clip(newest, args, on_bytes=None,
                               should_abort=poll)["message"] == "newest"


def test_call_fix_clip_lets_a_genuine_type_error_surface():
    """The retry loop must not swallow a real bug inside fix_clip -- the
    final call is made outside it."""
    from ccsync_companion import popup

    def broken(path, dest, root, mpis, on_bytes=None, should_abort=None):
        raise TypeError("unsupported operand type(s) for +: 'int' and 'str'")

    with pytest.raises(TypeError):
        popup.call_fix_clip(broken, ("p", "d", "r", []), on_bytes=None, should_abort=None)


def test_summarize_fix_results_counts_skipped_separately_from_failed():
    """"3 fixed, 1 skipped by you" -- a file the user abandoned is neither a
    success nor a malfunction, and calling it either lies to them."""
    from ccsync_companion import popup

    results = [
        {"ok": True}, {"ok": True}, {"ok": True},
        {"ok": False, "aborted": True},
    ]
    assert popup.summarize_fix_results(results, 4) == "3 of 4 copied in, 1 skipped by you"

    mixed = results + [{"ok": False, "message": "disk full"}]
    assert popup.summarize_fix_results(mixed, 5) == (
        "3 of 5 copied in, 1 skipped by you, 1 failed")

    assert popup.summarize_fix_results([{"ok": True}], 1) == "1 of 1 copied in"


def test_summarize_fix_results_says_what_was_left_alone_when_stopped():
    from ccsync_companion import popup

    results = [{"ok": True}, {"ok": False, "aborted": True}]
    assert popup.summarize_fix_results(results, 6, stopped_early=True) == (
        "Stopped: 1 of 6 copied in, 1 skipped by you, 4 left alone")


def test_batch_control_flags_are_independent():
    from ccsync_companion import popup

    control = popup.BatchControl()
    assert not control.should_abort_current() and not control.should_stop()

    control.request_stop_after_file()
    assert control.should_stop()
    assert not control.should_abort_current(), (
        "STOP AFTER THIS FILE must never abort the copy in flight")

    control.reset()
    control.request_skip_current()
    assert control.should_abort_current()
    assert not control.should_stop(), "a skip must not end the batch"

    control.reset()
    control.request_cancel_all()
    assert control.should_abort_current() and control.should_stop()
    assert control.cancel_all_requested()

    control.begin_file()
    assert control.should_abort_current(), "begin_file only re-arms the SKIP flag"


def _real_rows(tmp_path, count=3, size=60_000):
    rows = []
    for i in range(count):
        p = tmp_path / "src" / f"clip{i}.braw"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"A" * size)
        rows.append({"file_path": str(p), "suggested_dest": "B-roll",
                     "clip_name": p.name, "media_pool_items": []})
    return rows


def test_end_to_end_skip_leaves_no_partial_in_the_tree_and_copies_the_rest(tmp_path):
    """THE CORE-H5 GUARANTEE through the whole stack -- real perform_fix_all,
    real fixer.fix_clip, real chunked copy. After a mid-file skip the sync
    folder holds the files that finished and NOTHING of the one abandoned:
    no partial under the final name, no `.ccsync-tmp`. That orphan is what
    lane A would upload and lane C would fan out to the fleet."""
    from ccsync_companion import popup

    root = tmp_path / "root"
    root.mkdir()
    rows = _real_rows(tmp_path, 3)
    control = popup.BatchControl()

    def on_state(info):
        # "the user clicks SKIP" as soon as the middle file starts moving.
        if info.get("name") == "clip1.braw" and info.get("file_bytes_done"):
            control.request_skip_current()

    results = popup.perform_fix_all(
        rows, {}, str(root), state_fn=on_state, control=control,
        fix_clip_fn=lambda *a, **kw: fixer.fix_clip(
            *a, replace_clip_fn=lambda m, p: {"ok": True, "message": ""}, **kw),
    )

    assert [r.get("aborted", False) for r in results] == [False, True, False]
    dest = root / "B-roll"
    assert sorted(p.name for p in dest.iterdir()) == ["clip0.braw", "clip2.braw"], (
        f"the abandoned copy left something behind: {sorted(p.name for p in dest.iterdir())}"
    )
    assert not any(p.name.endswith(fixer.TMP_SUFFIX) for p in dest.iterdir())
    # every original is untouched, as always
    assert all((tmp_path / "src" / f"clip{i}.braw").stat().st_size == 60_000
               for i in range(3))


def test_end_to_end_cancel_all_deletes_the_partial_and_stops(tmp_path):
    from ccsync_companion import popup

    root = tmp_path / "root"
    root.mkdir()
    rows = _real_rows(tmp_path, 4)
    control = popup.BatchControl()

    def on_state(info):
        if info.get("name") == "clip1.braw" and info.get("file_bytes_done"):
            control.request_cancel_all()

    results = popup.perform_fix_all(
        rows, {}, str(root), state_fn=on_state, control=control,
        fix_clip_fn=lambda *a, **kw: fixer.fix_clip(
            *a, replace_clip_fn=lambda m, p: {"ok": True, "message": ""}, **kw),
    )

    assert len(results) == 2, "CANCEL ALL must not start clip2/clip3"
    assert results[-1]["aborted"] is True
    assert sorted(p.name for p in (root / "B-roll").iterdir()) == ["clip0.braw"]


def test_end_to_end_skipped_file_is_never_relinked_in_resolve(tmp_path):
    """ReplaceClip must not be called for a file that was abandoned -- the
    copy it would point at does not exist."""
    from ccsync_companion import popup

    root = tmp_path / "root"
    root.mkdir()
    rows = _real_rows(tmp_path, 2)
    rows[0]["media_pool_items"] = [object()]
    rows[1]["media_pool_items"] = [object()]
    control = popup.BatchControl()
    replaced = []

    def on_state(info):
        if info.get("name") == "clip0.braw" and info.get("file_bytes_done"):
            control.request_skip_current()

    popup.perform_fix_all(
        rows, {}, str(root), state_fn=on_state, control=control,
        fix_clip_fn=lambda *a, **kw: fixer.fix_clip(
            *a,
            replace_clip_fn=lambda m, p: (replaced.append(p), {"ok": True, "message": ""})[1],
            **kw),
    )

    assert len(replaced) == 1, "only the file that actually copied is relinked"
    assert replaced[0].endswith("clip1.braw")


def test_a_skipped_file_is_not_added_to_the_ignore_tracker(tmp_path):
    """CHOSEN SEMANTICS: skipping ONE copy attempt is not "never offer me
    this clip again". Only the popup's [ SKIP FOR NOW (this session) ] button
    (perform_ignore_all) touches the IgnoreTracker; an abandoned copy leaves
    it alone, so the clip is offered again on the next scan."""
    from ccsync_companion import popup

    root = tmp_path / "root"
    root.mkdir()
    rows = _real_rows(tmp_path, 1)
    tracker = fixer.IgnoreTracker()
    control = popup.BatchControl()

    def on_state(info):
        if info.get("file_bytes_done"):
            control.request_skip_current()

    results = popup.perform_fix_all(
        rows, {}, str(root), state_fn=on_state, control=control,
        fix_clip_fn=lambda *a, **kw: fixer.fix_clip(
            *a, replace_clip_fn=lambda m, p: {"ok": True, "message": ""}, **kw),
    )

    assert results[0]["aborted"] is True
    assert not tracker.is_ignored(rows[0]["file_path"]), (
        "an abandoned copy must not silently hide the clip forever"
    )


def test_progress_window_skip_and_cancel_reach_the_worker(monkeypatch):
    """The consolidate window gets the same three controls. The worker sees
    them through `window.control` (mid-file) and `should_stop` (between
    files) -- its 2-arg signature is unchanged, so existing callers and
    their doubles keep working."""
    from ccsync_companion import popup

    window = popup.ProgressWindow("COPYING")
    monkeypatch.setattr(window, "_show", lambda: None)

    window._on_skip_current_file()
    assert window.control.should_abort_current(), "SKIP must abort the file in flight"
    assert not window.should_stop(), "SKIP must NOT end the batch"
    assert not window.cancelled()

    window.control.reset()
    window._on_cancel_all()
    assert window.control.should_abort_current()
    assert window.cancelled()

    seen = []
    window.run(lambda publish, should_stop: seen.append(should_stop()))
    assert seen == [True], "CANCEL ALL must also stop the batch between files"


def test_progress_window_stop_after_this_file_never_aborts_the_copy(monkeypatch):
    from ccsync_companion import popup

    window = popup.ProgressWindow("COPYING")
    monkeypatch.setattr(window, "_show", lambda: None)
    window._on_stop()
    assert window.should_stop()
    assert not window.control.should_abort_current(), (
        "the graceful stop must let the file in flight finish")
    assert not window.cancelled()


def test_progress_window_controls_never_raise_without_a_window(monkeypatch):
    """The buttons only exist once _show() has built them; a headless run (or
    a click racing the window teardown) must not raise out of the Tk
    callback."""
    from ccsync_companion import popup

    window = popup.ProgressWindow("COPYING")
    window._on_stop()
    window._on_skip_current_file()
    window._on_cancel_all()
    assert window.should_stop() and window.cancelled()


class _TickRoot:
    """The three calls ProgressWindow._tick can make on its root."""

    def __init__(self):
        self.destroyed = False
        self.quits = 0
        self.after_calls = 0

    def destroy(self):
        self.destroyed = True

    def quit(self):
        self.quits += 1

    def after(self, ms, fn):
        self.after_calls += 1


def test_the_progress_window_ends_itself_with_destroy_not_quit():
    """UI-2: this window is shown under ui_dispatch.run_dialog, which on
    darwin parks in `tkwait window`. _tkinter's quit flag is process-global
    and Tk_WaitWindow never consults it, so quit() left the finished window
    on screen with the dispatcher's pump parked in the tkwait: every later
    dialog queued forever, serve()'s mainloop could not return, SIGTERM could
    not finish (MAC-11 took kill -9). _show's `finally: root.destroy()` is
    only reached AFTER run_dialog returns, so it never ran."""
    from ccsync_companion import popup

    window = popup.ProgressWindow("COPYING")
    window.root = _TickRoot()
    window._done.set()

    window._tick()

    assert window.root.destroyed is True
    assert window.root.quits == 0, (
        "root.quit() does not end run_dialog's tkwait on macOS")
    assert window.root.after_calls == 0, "a finished tick must not re-arm"


def test_the_progress_window_keeps_ticking_until_the_worker_is_done():
    from ccsync_companion import popup

    window = popup.ProgressWindow("COPYING")
    window.root = _TickRoot()

    window._tick()

    assert window.root.destroyed is False
    assert window.root.after_calls == 1


# ===========================================================================
# PopupDialog's Tk-side wiring, with fake widgets (conftest forbids a real
# Tk window, and this logic is exactly what a live-only test never covers)
# ===========================================================================


class _FakeWidget:
    """Records config()/pack()/grid() calls instead of drawing anything."""

    def __init__(self):
        self.text = ""
        self.state = "normal"
        self.packed = False
        self.gridded = True

    def config(self, **kw):
        if "text" in kw:
            self.text = kw["text"]
        if "state" in kw:
            self.state = kw["state"]

    def pack(self, **kw):
        self.packed = True

    def pack_forget(self):
        self.packed = False

    def grid(self, **kw):
        self.gridded = True

    def grid_remove(self):
        self.gridded = False


class _FakeRoot(_FakeWidget):
    def __init__(self):
        super().__init__()
        self.destroyed = False

    def destroy(self):
        self.destroyed = True

    def bell(self):
        pass


def _bare_dialog(rows):
    """A PopupDialog with every widget faked -- no tkinter involved."""
    from ccsync_companion import popup

    dialog = object.__new__(popup.PopupDialog)
    dialog.rows = rows
    dialog.local_root = "L"
    dialog.ignore_tracker = fixer.IgnoreTracker()
    dialog.on_done = None
    dialog.editor_name = "owen"
    dialog._fixing = False
    dialog._progress_lock = __import__("threading").Lock()
    dialog._progress = {}
    dialog._stop_requested = False
    dialog._control = popup.BatchControl()
    dialog._rate = popup.RateEstimator()
    dialog._tick_job = None
    dialog._batch_rows = rows
    dialog._failed_rows = []
    dialog.root = _FakeRoot()
    for name in ("status_label", "_progress_frame", "_fix_btn", "_ignore_btn",
                 "_retry_btn", "_stop_btn", "_skip_btn", "_cancel_btn"):
        setattr(dialog, name, _FakeWidget())
    return dialog


def _row(path):
    return {"file_path": path, "suggested_dest": "D", "clip_name": path,
            "media_pool_items": []}


def test_the_x_button_during_a_copy_means_cancel_all_and_does_not_close():
    """The X must not orphan a partial, and must not destroy the root either:
    destroying it ends mainloop(), so show_popup() returns and
    app._show_out_of_tree_popup() RELEASES the popup lock while the worker is
    still copying multi-GB files and calling ReplaceClip (CORE-M1). It
    cancels (partial cleaned up by fix_clip) and the window closes itself."""
    dialog = _bare_dialog([_row("a.mov")])
    dialog._fixing = True

    dialog._on_close_request()

    assert dialog._control.cancel_all_requested()
    assert dialog._control.should_abort_current()
    assert dialog.root.destroyed is False
    assert "Cancelling" in dialog.status_label.text


def test_the_x_button_still_closes_a_dialog_that_is_not_copying():
    dialog = _bare_dialog([_row("a.mov")])
    dialog._on_close_request()
    assert dialog.root.destroyed is True
    assert not dialog._control.cancel_all_requested()


def test_the_timer_tick_finishes_a_batch_whose_marshal_to_the_tk_thread_failed():
    """MAC-11: the worker's `root.after(0, ...)` is the one cross-thread Tk
    call in this dialog, and on macOS it can fail (and used to fail SILENTLY).
    The tick runs on the Tk thread and needs no such call, so the window still
    closes itself once the worker has published its result."""
    dialog = _bare_dialog([_row("a.mov")])
    dialog._fixing = True
    dialog._pending_results = [{"file_path": "a.mov", "ok": True}]

    dialog._tick()

    assert dialog._fixing is False
    assert dialog.root.destroyed is True, (
        "a completed FIX ALL whose after() never ran left an unclosable window: "
        "every button is disabled by _run_fix and the X means cancel-all while "
        "_fixing is True"
    )


def test_results_are_delivered_exactly_once_whichever_path_gets_there_first():
    """Both routes fire in the normal case -- after() then the tick 250 ms
    later. on_done must not run twice: it releases the popup lock and does the
    app's bookkeeping."""
    dialog = _bare_dialog([_row("a.mov")])
    calls = []
    dialog.on_done = calls.append
    dialog._fixing = True
    dialog._pending_results = [{"file_path": "a.mov", "ok": True}]

    dialog._deliver_results()
    dialog._deliver_results()
    dialog._tick()

    assert len(calls) == 1


def test_retry_failed_gets_its_own_batch_delivered(monkeypatch):
    """UI-1: the exactly-once latch is per BATCH, not per dialog.

    Every other case in this file drives ONE batch, which is exactly how this
    shipped. `_finished`, latched by the first delivery (MAC-11), was never
    reset, so RETRY FAILED's worker published a result both delivery routes
    then refused to read: _fix_done never ran, `_fixing` stayed True, FIX ALL
    and IGNORE stayed disabled, STOP/SKIP/CANCEL only set flags a finished
    worker never reads, and the X routed back into _on_cancel_all -- an
    unclosable window holding app._popup_active_lock (taken across
    show_popup) for the rest of the session.
    """
    import threading
    import types

    from ccsync_companion import popup

    rows = [_row("a.mov"), _row("b.mov")]
    dialog = _bare_dialog(rows)
    dialog._vars = []
    dialog.canonical_prefix = ""

    # The worker runs inline so both batches are deterministic. The fake root
    # has no after(), so _safe_after and the 250 ms tick are both no-ops here
    # and delivery is driven by hand -- the same call the tick would make.
    class _InlineThread:
        def __init__(self, target, name=None, daemon=None):
            self._target = target

        def start(self):
            self._target()

    monkeypatch.setattr(popup, "threading",
                        types.SimpleNamespace(Thread=_InlineThread,
                                              Lock=threading.Lock))

    batches = []
    outcomes = {"a.mov": {"ok": True, "message": "ok"},
                "b.mov": {"ok": False, "message": "still downloading from the cloud"}}

    def fake_perform(batch_rows, selections, local_root, **kw):
        batches.append([r["file_path"] for r in batch_rows])
        return [dict(outcomes[r["file_path"]], file_path=r["file_path"])
                for r in batch_rows]

    monkeypatch.setattr(popup, "perform_fix_all", fake_perform)

    dialog._on_fix_all()
    dialog._deliver_results()

    assert dialog._fixing is False
    assert dialog._failed_rows == [rows[1]]
    assert dialog.root.destroyed is False, "a batch with a failure stays open to retry"

    # ...the cloud file finished downloading, which is the documented reason
    # RETRY FAILED exists.
    outcomes["b.mov"] = {"ok": True, "message": "ok"}
    dialog._on_retry_failed()
    dialog._deliver_results()

    assert batches == [["a.mov", "b.mov"], ["b.mov"]]
    assert dialog._fixing is False, (
        "the second batch was never delivered: no button and no X can close "
        "this window, and app._popup_active_lock is held for the session")
    assert dialog._failed_rows == []
    assert dialog.root.destroyed is True


def test_the_x_button_closes_a_window_whose_worker_has_already_finished():
    """There is nothing left to cancel: the batch ended. Bouncing the click
    off _on_cancel_all is what made the window feel dead (MAC-11)."""
    dialog = _bare_dialog([_row("a.mov")])
    dialog._fixing = True
    dialog._pending_results = [{"file_path": "a.mov", "ok": True}]

    dialog._on_close_request()

    assert dialog.root.destroyed is True
    assert not dialog._control.cancel_all_requested()


def test_a_raising_on_done_still_closes_the_window():
    """The copy and the relink have already happened by then; an exception in
    the app's callback must not cost the editor a modal it cannot dismiss."""
    dialog = _bare_dialog([_row("a.mov")])

    def boom(_results):
        raise RuntimeError("bookkeeping blew up")

    dialog.on_done = boom
    dialog._fixing = True
    dialog._pending_results = [{"file_path": "a.mov", "ok": True}]

    dialog._deliver_results()

    assert dialog.root.destroyed is True
    assert dialog._fixing is False


def test_the_three_buttons_set_exactly_one_meaning_each():
    dialog = _bare_dialog([_row("a.mov")])

    dialog._on_stop_after_file()
    assert dialog._stop_requested is True
    assert not dialog._control.should_abort_current(), (
        "STOP AFTER THIS FILE must never abandon the file in flight")

    dialog = _bare_dialog([_row("a.mov")])
    dialog._on_skip_current_file()
    assert dialog._control.should_abort_current()
    assert dialog._stop_requested is False, "SKIP must not end the batch"
    assert not dialog._control.should_stop()

    dialog = _bare_dialog([_row("a.mov")])
    dialog._on_cancel_all()
    assert dialog._control.should_abort_current()
    assert dialog._control.cancel_all_requested()
    assert dialog._stop_requested is True
    assert dialog._cancel_btn.state == "disabled"


def test_fix_done_reports_skipped_separately_and_keeps_the_window_open():
    """"3 fixed, 1 skipped by you" -- and the dialog stays open so the user
    can retry the file they abandoned."""
    rows = [_row("a.mov"), _row("b.mov")]
    dialog = _bare_dialog(rows)
    dialog._fixing = True

    dialog._fix_done([
        {"ok": True, "message": "", "file_path": "a.mov"},
        {"ok": False, "aborted": True, "leftover_paths": [], "file_path": "b.mov",
         "message": "Skipped by you"},
    ])

    text = dialog.status_label.text
    assert "1 of 2 copied in" in text and "1 skipped by you" in text
    assert "failed" not in text, "a deliberate skip is not a failure"
    assert dialog.root.destroyed is False
    # the skipped row is retryable -- skipping ONE copy attempt is not
    # "never offer me this clip again"
    assert dialog._failed_rows == [rows[1]]
    assert dialog._retry_btn.packed is True
    assert not dialog.ignore_tracker.is_ignored("b.mov")


def test_fix_done_surfaces_a_partial_it_could_not_delete():
    """The one case where a skip is not clean: the orphan is inside the sync
    folder and only this process ever knew about it (CORE-H5)."""
    dialog = _bare_dialog([_row("a.mov")])
    dialog._fixing = True

    dialog._fix_done([
        {"ok": False, "aborted": True, "file_path": "a.mov",
         "leftover_paths": [r"T:\Creators_Club\B-roll\a.mov.1234-ab.ccsync-tmp"],
         "message": "Skipped by you, but CCSync couldn't delete..."},
    ])

    assert "could NOT delete" in dialog.status_label.text
    assert "a.mov.1234-ab.ccsync-tmp" in dialog.status_label.text


def test_fix_done_closes_the_window_when_everything_worked():
    dialog = _bare_dialog([_row("a.mov")])
    dialog._fixing = True
    done = []
    dialog.on_done = done.append

    dialog._fix_done([{"ok": True, "message": "", "file_path": "a.mov"}])

    assert dialog.root.destroyed is True
    assert len(done) == 1


def test_perform_fix_all_passes_canonical_prefix_and_degrades():
    """canonical_prefix reaches a modern fix_clip; a legacy double without
    the kwarg still works via call_fix_clip's degradation."""
    from ccsync_companion.popup import perform_fix_all

    seen = {}

    def modern(path, dest_rel, local_root, items, on_bytes=None,
               should_abort=None, canonical_prefix=""):
        seen["canonical_prefix"] = canonical_prefix
        return {"ok": True, "message": "", "copied_to": "x"}

    rows = [{"file_path": "C:/x/a.mov", "suggested_dest": "B-roll", "media_pool_items": []}]
    perform_fix_all(rows, {"C:/x/a.mov": "B-roll"}, "C:/root",
                    fix_clip_fn=modern, canonical_prefix="P:\\")
    assert seen["canonical_prefix"] == "P:\\"

    def legacy(path, dest_rel, local_root, items, on_bytes=None):
        seen["legacy_called"] = True
        return {"ok": True, "message": "", "copied_to": "x"}

    perform_fix_all(rows, {"C:/x/a.mov": "B-roll"}, "C:/root",
                    fix_clip_fn=legacy, canonical_prefix="P:\\")
    assert seen["legacy_called"] is True


# ===========================================================================
# macOS port: every root goes through ui_dispatch (inline on Windows)
# ===========================================================================


def _record_dispatch(monkeypatch, run: bool = False):
    """Replace ui_dispatch.dispatch with a recorder. `run=False` means the
    dialog body is never executed, which is how these tests stay honest about
    conftest._no_real_tk_windows."""
    from ccsync_companion import ui_dispatch

    calls: list = []

    def _dispatch(fn):
        calls.append(fn)
        return fn() if run else None

    monkeypatch.setattr(ui_dispatch, "dispatch", _dispatch)
    return calls


def test_confirm_dialog_builds_its_root_through_ui_dispatch(monkeypatch):
    """On macOS the root and its mainloop must land on the main thread; on
    Windows dispatch is inline, so this changes nothing there."""
    from ccsync_companion import popup

    calls = _record_dispatch(monkeypatch)
    assert popup.confirm_dialog("T", "body") is False  # nothing ran -> safe default
    assert len(calls) == 1 and callable(calls[0])


def test_confirm_dialog_treats_a_stopped_dispatcher_as_no_display(monkeypatch):
    """Shutdown races: dispatch raises rather than blocking, and the answer
    an unanswerable confirm gives is still "do nothing"."""
    from ccsync_companion import popup, ui_dispatch

    def _stopped(fn):
        raise ui_dispatch.UIDispatchStopped("stopped")

    monkeypatch.setattr(ui_dispatch, "dispatch", _stopped)
    assert popup.confirm_dialog("T", "body", ok_label="PROCEED") is False


def test_show_popup_dispatches_construction_AND_mainloop_together(monkeypatch):
    """PopupDialog.__init__ builds the Tk root and show() runs its mainloop --
    split across the dispatch boundary they would land on two threads."""
    from ccsync_companion import fixer as fixer_mod
    from ccsync_companion import popup

    calls = _record_dispatch(monkeypatch)
    built: list = []

    class _FakeDialog:
        def __init__(self, *a, **k):
            built.append("init")

        def show(self):
            built.append("show")

    monkeypatch.setattr(popup, "PopupDialog", _FakeDialog)
    items = [{"file_path": r"G:\raw\A001.braw", "media_pool_item": object(),
              "clip_name": "A001", "resolve_project_name": ""}]
    popup.show_popup(items, r"C:\Creators_Club", "owen", fixer_mod.IgnoreTracker())

    assert len(calls) == 1
    assert built == [], "the dialog must be built INSIDE the dispatched call"
    calls[0]()
    assert built == ["init", "show"]


def test_progress_window_show_goes_through_ui_dispatch(monkeypatch):
    from ccsync_companion import popup

    calls = _record_dispatch(monkeypatch)
    window = popup.ProgressWindow("COPYING")
    window._show()
    assert len(calls) == 1 and callable(calls[0])
