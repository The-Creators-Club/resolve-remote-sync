from __future__ import annotations

from ccsync_companion import consolidate


# ---------------------------------------------------------------- plan

def _item(path, mpi=None):
    return {"file_path": path, "media_pool_item": mpi if mpi is not None else object(),
            "clip_name": path.split("\\")[-1], "resolve_project_name": "CCT Creator Profiles"}


def test_plan_dedupes_and_sizes():
    a = object()
    b = object()
    items = [
        {"file_path": "G:\\raw\\A001.braw", "media_pool_item": a, "resolve_project_name": ""},
        {"file_path": "g:\\raw\\a001.braw", "media_pool_item": b, "resolve_project_name": ""},  # dup (case)
        {"file_path": "G:\\raw\\B002.wav", "media_pool_item": object(), "resolve_project_name": ""},
    ]
    sizes = {"G:\\raw\\A001.braw": 1000, "G:\\raw\\B002.wav": 50}
    plan = consolidate.plan_local_consolidation(
        items, local_root="", editor_name="ruskin", project_prefix="Projects/2026/Creator Profiles/Season 1",
        size_fn=lambda p: sizes.get(p, sizes.get(p.replace("g:", "G:"), 0)),
    )
    assert plan["count"] == 2  # deduped to unique paths
    braw = next(o for o in plan["ops"] if o["file_path"].lower().endswith("a001.braw"))
    assert len(braw["media_pool_items"]) == 2  # both timeline/pool refs kept
    assert braw["dest_rel"].startswith("Projects/2026/Creator Profiles/Season 1/")
    assert plan["bytes"] == 1050


def test_plan_uses_server_root_over_prefix():
    items = [_item("G:\\x\\clip.mov")]
    plan = consolidate.plan_local_consolidation(
        items, local_root="", editor_name="ruskin", project_prefix="Projects/wrong",
        server_roots={"cct creator profiles": "Projects/2026/Creator Profiles/Season 1"},
        size_fn=lambda p: 10,
    )
    assert plan["ops"][0]["dest_rel"].startswith("Projects/2026/Creator Profiles/Season 1/")


# ---------------------------------------------------------------- dry-run parse

DRYRUN_STDERR = "\n".join([
    '{"level":"notice","msg":"No host key validation","object":"remote"}',
    '{"level":"notice","msg":"Skipped copy as --dry-run is set (size 2Mi)","object":"A001.braw"}',
    '{"level":"notice","msg":"Skipped copy as --dry-run is set (size 50)","object":"B002.wav"}',
    '{"level":"info","stats":{"totalTransfers":2,"totalBytes":2097202,"transfers":2,"bytes":2097202}}',
    "not json at all",
])


def test_parse_dry_run_stats():
    parsed = consolidate.parse_dry_run_stats(DRYRUN_STDERR)
    assert parsed["count"] == 2
    assert parsed["bytes"] == 2097202
    assert parsed["objects"] == ["A001.braw", "B002.wav"]  # host-key line excluded (no dry-run msg)


def test_parse_dry_run_empty():
    # A real "rclone measured zero" run: a stats record IS present, so
    # saw_stats is True and reconcile_with_nas may trust the zeros (DEL-0).
    parsed = consolidate.parse_dry_run_stats(
        '{"level":"info","stats":{"totalTransfers":0,"totalBytes":0}}')
    assert parsed == {
        "count": 0, "bytes": 0, "objects": [], "objects_total": 0,
        "deletes": 0, "deleted_dirs": 0, "delete_objects": [], "delete_objects_total": 0,
        "saw_stats": True,
    }


DRYRUN_STDERR_WITH_DELETES = "\n".join([
    '{"level":"notice","msg":"Skipped delete as --dry-run is set","object":"Proxy/old.mov"}',
    '{"level":"info","stats":{"totalTransfers":0,"totalBytes":0,"deletes":1,"deletedDirs":0}}',
])


def test_parse_dry_run_stats_reads_deletes_separately_from_transfers():
    parsed = consolidate.parse_dry_run_stats(DRYRUN_STDERR_WITH_DELETES)
    assert parsed["deletes"] == 1
    assert parsed["delete_objects"] == ["Proxy/old.mov"]
    assert parsed["objects"] == []  # a delete must never land in the transfer list


def test_parse_dry_run_stats_caps_object_lists():
    lines = [
        f'{{"level":"notice","msg":"Skipped copy as --dry-run is set","object":"f{i}.mov"}}'
        for i in range(250)
    ]
    lines.append('{"level":"info","stats":{"totalTransfers":250,"totalBytes":0}}')
    parsed = consolidate.parse_dry_run_stats("\n".join(lines))
    assert len(parsed["objects"]) == 200
    assert parsed["objects_total"] == 250
    assert parsed["count"] == 250  # the summary total is unaffected by the cap


def test_reconcile_runs_both_lanes(tmp_path):
    calls = []

    def fake_run(cmd, timeout):
        calls.append(cmd)
        # up = has "copy", down uses "sync" -- return different stats
        if "copy" in cmd:
            return '{"stats":{"totalTransfers":3,"totalBytes":300}}'
        return '{"stats":{"totalTransfers":1,"totalBytes":100}}'

    cfg = {"rclone_path": "rclone", "local_root": "L", "remote": "r",
           "remote_root": "/nas", "transfers": 4}
    out = consolidate.reconcile_with_nas(cfg, "Projects/2026/X", tmp_path, run_fn=fake_run)
    assert out["ok"] is True
    assert out["uploads"]["count"] == 3 and out["downloads"]["count"] == 1
    assert out["skip_lane_b"] is False
    assert len(calls) == 2
    assert all("--dry-run" in c for c in calls)
    assert all("--verbose" not in c for c in calls)  # AUDIT §6: dropped from dry runs


def test_reconcile_survives_rclone_error(tmp_path):
    def boom(cmd, timeout):
        raise RuntimeError("rclone missing")

    out = consolidate.reconcile_with_nas({"local_root": "L", "remote": "r", "remote_root": "/n"},
                                         "Projects/2026/X", tmp_path, run_fn=boom)
    assert out["ok"] is False and "rclone missing" in out["error"]


def test_reconcile_hard_aborts_on_none_subpath(tmp_path):
    """AUDIT D-2: a None subpath must hard-abort rather than fall back to a
    whole-tree dry run/consolidate. run_fn must never even be called."""
    calls = []

    def spy(cmd, timeout):
        calls.append(cmd)
        return ""

    out = consolidate.reconcile_with_nas(
        {"local_root": "L", "remote": "r", "remote_root": "/n"}, None, tmp_path, run_fn=spy,
    )
    assert out["ok"] is False
    assert "refusing whole-tree consolidate" in out["error"]
    assert calls == []


def test_reconcile_hard_aborts_on_blank_subpath(tmp_path):
    calls = []

    def spy(cmd, timeout):
        calls.append(cmd)
        return ""

    out = consolidate.reconcile_with_nas(
        {"local_root": "L", "remote": "r", "remote_root": "/n"}, "   ", tmp_path, run_fn=spy,
    )
    assert out["ok"] is False
    assert calls == []


def test_reconcile_flags_skip_lane_b_when_downloads_would_delete(tmp_path):
    def fake_run(cmd, timeout):
        if "copy" in cmd:
            return '{"stats":{"totalTransfers":3,"totalBytes":300}}'
        return DRYRUN_STDERR_WITH_DELETES

    cfg = {"rclone_path": "rclone", "local_root": "L", "remote": "r",
           "remote_root": "/nas", "transfers": 4}
    out = consolidate.reconcile_with_nas(cfg, "Projects/2026/X", tmp_path, run_fn=fake_run)
    assert out["ok"] is True
    assert out["skip_lane_b"] is True
    assert consolidate.lane_b_allowed(out) is False


def test_lane_b_allowed_true_only_when_ok_and_no_deletions():
    assert consolidate.lane_b_allowed({"ok": True, "skip_lane_b": False}) is True
    assert consolidate.lane_b_allowed({"ok": True, "skip_lane_b": True}) is False
    assert consolidate.lane_b_allowed({"ok": False, "skip_lane_b": False}) is False


# ---------------------------------------------------------------- report + run

def test_build_report_mentions_all_three_numbers():
    plan = {"count": 5, "bytes": 5_000_000}
    reconcile = {"ok": True, "uploads": {"count": 3, "bytes": 300},
                 "downloads": {"count": 7, "bytes": 700}}
    report = consolidate.build_report(plan, reconcile)
    assert "5 scattered clip" in report
    assert "3 original" in report and "7 proxy" in report
    assert "COPIED, never moved" in report


def test_build_report_surfaces_deletions_prominently_and_skips_download_line():
    plan = {"count": 5, "bytes": 5_000_000}
    reconcile = {
        "ok": True, "uploads": {"count": 3, "bytes": 300},
        "downloads": {"count": 0, "bytes": 0, "deletes": 12, "deleted_dirs": 2},
    }
    report = consolidate.build_report(plan, reconcile)
    assert "DELETE 12 local file(s)" in report
    assert "2 folder(s)" in report
    assert "SKIPPED" in report
    assert "will download from the NAS" not in report  # replaced by the warning


def test_build_report_nas_error():
    report = consolidate.build_report({"count": 1, "bytes": 1},
                                      {"ok": False, "error": "no remote"})
    assert "could not check the NAS" in report


# ------------------------------------------------- DEL-0: the delete guard

def test_default_run_survives_non_ascii_rclone_output(tmp_path):
    """AUDIT_2 DEL-0 [reproduced live], the flagship data-loss regression.

    _default_run was the ONE rclone call in companion code still using bare
    `text=True`, which decodes with the console codepage (cp1252 here) under
    errors="strict". rclone logs UTF-8, so a single CJK filename --
    near-guaranteed in Traditional-Taiwanese-Mandarin documentary work --
    raised UnicodeDecodeError inside subprocess's own reader thread. That
    does NOT propagate: communicate() returned stderr=None, exit code 0, no
    exception. parse_dry_run_stats("") then reported deletes=0, the consent
    dialog said "0 proxy file(s) will download / 0 deletions", and lane B
    deleted the editor's local proxies anyway.

    Uses a real subprocess, so it exercises the actual decode path.
    """
    import sys

    script = tmp_path / "emit.py"
    script.write_text(
        "import sys\n"
        "sys.stderr.buffer.write("
        "'{\"level\":\"notice\",\"msg\":\"Skipped delete as --dry-run is set\","
        "\"object\":\"Proxy/\\u53f0\\u5317_\\u4ee3\\u7406.mov\"}\\n'"
        ".encode('utf-8'))\n"
        "sys.stderr.buffer.write("
        "'{\"level\":\"info\",\"stats\":{\"totalTransfers\":0,\"totalBytes\":0,"
        "\"deletes\":2,\"deletedDirs\":0}}\\n'.encode('utf-8'))\n",
        encoding="utf-8",
    )
    stderr = consolidate._default_run([sys.executable, str(script)], timeout=30)

    assert stderr, "stderr came back empty -- the decode swallowed it again"
    parsed = consolidate.parse_dry_run_stats(stderr)
    assert parsed["deletes"] == 2, "a CJK filename must not blind the delete counter"
    assert parsed["saw_stats"] is True
    assert consolidate.lane_b_allowed(
        {"ok": True, "skip_lane_b": bool(parsed["deletes"])}
    ) is False


def test_reconcile_fails_closed_when_rclone_returned_no_stats(tmp_path):
    """AUDIT_2 DEL-0, second hardening. "We received no data" and "rclone
    measured zero deletions" are indistinguishable in the counters, and
    treating the first as the second is the exact shape of defect that
    produced DEL-0. A timeout, a killed process or an rclone crash must
    never read as "nothing will be deleted"."""
    out = consolidate.reconcile_with_nas(
        {"rclone_path": "rclone", "local_root": "L", "remote": "r", "remote_root": "/nas"},
        "Projects/2026/X", tmp_path, run_fn=lambda cmd, timeout: "",
    )
    assert out["ok"] is False
    assert "no data" in out["error"]
    assert consolidate.lane_b_allowed(out) is False


def test_reconcile_fails_closed_when_only_the_download_side_is_blank(tmp_path):
    def half(cmd, timeout):
        return '{"stats":{"totalTransfers":3,"totalBytes":300}}' if "copy" in cmd else ""

    out = consolidate.reconcile_with_nas(
        {"rclone_path": "rclone", "local_root": "L", "remote": "r", "remote_root": "/nas"},
        "Projects/2026/X", tmp_path, run_fn=half,
    )
    assert out["ok"] is False
    assert consolidate.lane_b_allowed(out) is False


def test_parse_dry_run_stats_counts_directory_removals_as_deletions():
    """AUDIT_2 §7 new-defect 2: rclone emits "Skipped remove directory as
    --dry-run is set" for directories, which landed in the harmless
    "would upload/download" sample list shown to the human."""
    text = "\n".join([
        '{"level":"notice","msg":"Skipped remove directory as --dry-run is set",'
        '"object":"B-roll/day03/Proxy"}',
        '{"level":"info","stats":{"totalTransfers":0,"totalBytes":0,"deletedDirs":1}}',
    ])
    parsed = consolidate.parse_dry_run_stats(text)
    assert parsed["delete_objects"] == ["B-roll/day03/Proxy"]
    assert parsed["objects"] == []


def test_build_report_leads_with_the_reassurance():
    """UX-13: "Originals are COPIED, never moved" was the LAST line, below a
    "!!! WARNING ... DELETE !!!" block, so nobody read it."""
    report = consolidate.build_report(
        {"count": 2, "bytes": 20},
        {"ok": True, "uploads": {"count": 1, "bytes": 1},
         "downloads": {"count": 0, "bytes": 0, "deletes": 3, "deleted_dirs": 0}},
    )
    lines = report.splitlines()
    assert lines[0] == "COPY THIS PROJECT'S MEDIA IN"
    assert "COPIED, never moved" in lines[1]
    assert "Consolidate" not in report


def test_run_consolidation_reports_progress():
    ops = [{"file_path": f"G:\\x\\f{i}.wav", "media_pool_items": [object()],
            "dest_rel": "Audio/Music", "size": 1} for i in range(3)]
    seen = []
    results = consolidate.run_consolidation(
        ops, "L",
        fix_clip_fn=lambda p, d, r, m: {"ok": True, "message": "ok", "copied_to": d},
        progress_fn=lambda done, total, res: seen.append(done),
    )
    assert [r["ok"] for r in results] == [True, True, True]
    assert seen == [1, 2, 3]
    assert all(r["file_path"] for r in results)


def test_run_consolidation_publishes_rich_progress_and_can_stop(tmp_path):
    """UX-10: Consolidate's whole user-visible surface was four toasts, with
    a potentially MULTI-HOUR silence between the third and the fourth -- even
    though run_consolidation already ACCEPTED a progress_fn and app.py passed
    none."""
    ops = [
        {"file_path": f"G:\\x\\f{i}.mov", "media_pool_items": [], "dest_rel": "D",
         "size": 1000}
        for i in range(4)
    ]

    def fake_fix(path, dest, root, mpis, on_bytes=None):
        on_bytes(0, 1000)
        on_bytes(1000, 1000)
        return {"ok": True, "message": "ok", "copied_to": dest}

    seen = []
    results = consolidate.run_consolidation(
        ops, "L", fix_clip_fn=fake_fix, state_fn=seen.append,
    )
    assert len(results) == 4
    assert all(s["batch_bytes_total"] == 4000 for s in seen)
    assert seen[-1]["batch_bytes_done"] == 4000
    assert any(s["name"] == "f2.mov" for s in seen)

    # ...and it stops BETWEEN files (never mid-file: CORE-H5).
    done = []
    results = consolidate.run_consolidation(
        ops, "L",
        fix_clip_fn=lambda *a, **k: done.append(1) or {"ok": True, "message": "", "copied_to": "D"},
        should_stop=lambda: len(done) >= 1,
    )
    assert len(results) == 1


def test_run_consolidation_tolerates_a_fix_clip_double_without_on_bytes():
    ops = [{"file_path": "G:\\x\\f.wav", "media_pool_items": [], "dest_rel": "D", "size": 1}]
    results = consolidate.run_consolidation(
        ops, "L", fix_clip_fn=lambda p, d, r, m: {"ok": True, "message": "ok", "copied_to": d},
    )
    assert results[0]["ok"] is True


# ===========================================================================
# Consolidate gets the same mid-file controls as FIX ALL
# ===========================================================================


def _ops(count=4, size=1000):
    return [
        {"file_path": f"G:\\x\\f{i}.mov", "media_pool_items": [], "dest_rel": "D",
         "size": size}
        for i in range(count)
    ]


def test_run_consolidation_skip_abandons_one_op_and_continues():
    from ccsync_companion import popup

    control = popup.BatchControl()
    attempted = []

    def fake_fix(path, dest, root, mpis, on_bytes=None, should_abort=None):
        attempted.append(path)
        if path.endswith("f1.mov"):
            control.request_skip_current()
            if should_abort():
                return {"ok": False, "aborted": True, "copied_to": None,
                        "leftover_paths": [], "message": "Skipped by you"}
        return {"ok": True, "message": "ok", "copied_to": dest}

    results = consolidate.run_consolidation(_ops(4), "L", fix_clip_fn=fake_fix,
                                            control=control)
    assert len(attempted) == 4
    assert [r.get("aborted", False) for r in results] == [False, True, False, False]


def test_run_consolidation_cancel_all_stops_the_batch():
    from ccsync_companion import popup

    control = popup.BatchControl()
    attempted = []

    def fake_fix(path, dest, root, mpis, on_bytes=None, should_abort=None):
        attempted.append(path)
        control.request_cancel_all()
        if should_abort():
            return {"ok": False, "aborted": True, "copied_to": None,
                    "leftover_paths": [], "message": "Skipped by you"}
        return {"ok": True, "message": "ok", "copied_to": dest}

    results = consolidate.run_consolidation(_ops(5), "L", fix_clip_fn=fake_fix,
                                            control=control)
    assert len(attempted) == 1
    assert results[0]["aborted"] is True


def test_run_consolidation_publishes_the_new_counts():
    from ccsync_companion import popup

    control = popup.BatchControl()

    def fake_fix(path, dest, root, mpis, on_bytes=None, should_abort=None):
        if path.endswith("f0.mov"):
            control.request_skip_current()
            return {"ok": False, "aborted": True, "copied_to": None,
                    "leftover_paths": [], "message": "Skipped by you"}
        return {"ok": True, "message": "ok", "copied_to": dest}

    seen = []
    consolidate.run_consolidation(_ops(3), "L", fix_clip_fn=fake_fix,
                                  state_fn=seen.append, control=control)
    final = seen[-1]
    assert final["skipped"] == 1 and final["fixed"] == 2 and final["failed"] == 0
    assert final["cancelled"] is False
    assert final["batch_bytes_total"] == 3000  # existing keys untouched


def test_run_consolidation_without_a_control_is_unchanged():
    """The existing app.py/test callers pass no control and must be
    byte-for-byte unaffected -- including doubles that predate on_bytes."""
    results = consolidate.run_consolidation(
        _ops(2), "L",
        fix_clip_fn=lambda p, d, r, m: {"ok": True, "message": "ok", "copied_to": d},
    )
    assert [r["ok"] for r in results] == [True, True]
