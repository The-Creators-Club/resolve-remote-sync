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
    parsed = consolidate.parse_dry_run_stats(
        '{"level":"info","stats":{"totalTransfers":0,"totalBytes":0}}')
    assert parsed == {"count": 0, "bytes": 0, "objects": []}


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
    assert len(calls) == 2
    assert all("--dry-run" in c for c in calls)


def test_reconcile_survives_rclone_error(tmp_path):
    def boom(cmd, timeout):
        raise RuntimeError("rclone missing")

    out = consolidate.reconcile_with_nas({"local_root": "L", "remote": "r", "remote_root": "/n"},
                                         None, tmp_path, run_fn=boom)
    assert out["ok"] is False and "rclone missing" in out["error"]


# ---------------------------------------------------------------- report + run

def test_build_report_mentions_all_three_numbers():
    plan = {"count": 5, "bytes": 5_000_000}
    reconcile = {"ok": True, "uploads": {"count": 3, "bytes": 300},
                 "downloads": {"count": 7, "bytes": 700}}
    report = consolidate.build_report(plan, reconcile)
    assert "5 scattered clip" in report
    assert "3 original" in report and "7 proxy" in report
    assert "COPIED, never moved" in report


def test_build_report_nas_error():
    report = consolidate.build_report({"count": 1, "bytes": 1},
                                      {"ok": False, "error": "no remote"})
    assert "could not check the NAS" in report


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
