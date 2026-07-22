from __future__ import annotations

from ccbench.report import best_per_combo, classify_lane, render_report
from ccbench.result import RunResult


def _r(engine, dataset, direction, params, MB_s, verified=True, ok=True, repeat_index=0, skipped=False, reason=""):
    return RunResult(
        engine=engine, dataset=dataset, direction=direction, params=params,
        seconds=100.0, num_bytes=int(MB_s * 1024 * 1024 * 100), MB_s=MB_s,
        verified=verified, ok=ok, skipped=skipped, reason=reason,
        lane=classify_lane(dataset, direction), repeat_index=repeat_index,
    )


def test_classify_lane():
    assert classify_lane("large", "up") == "A"
    assert classify_lane("large", "down") == "B"
    assert classify_lane("small", "up") == "C"
    assert classify_lane("small", "down") == "C"
    assert classify_lane("network", "up") == "net"
    assert classify_lane("weird", "up") == "?"


def test_best_per_combo_picks_max_and_prefers_verified():
    rows = [
        _r("rclone_sftp", "large", "up", {"transfers": 4}, 50.0, repeat_index=0),
        _r("rclone_sftp", "large", "up", {"transfers": 4}, 80.0, repeat_index=1),
        _r("rclone_sftp", "large", "up", {"transfers": 8}, 60.0, repeat_index=0),
    ]
    best = best_per_combo(rows)
    by_params = {tuple(sorted(r.params.items())): r for r in best}
    assert by_params[(("transfers", 4),)].MB_s == 80.0
    assert by_params[(("transfers", 8),)].MB_s == 60.0


def test_best_per_combo_keeps_failed_representative():
    rows = [_r("syncthing", "small", "up", {}, 0.0, ok=False, verified=False, reason="boom")]
    best = best_per_combo(rows)
    assert len(best) == 1
    assert best[0].ok is False


def test_render_report_contains_lane_sections_and_winner():
    rows = [
        _r("rclone_sftp", "large", "up", {"transfers": 8, "multi_thread_streams": 0}, 90.0),
        _r("robocopy_smb", "large", "up", {"mt": 16}, 40.0),
        _r("rclone_sftp", "large", "down", {"transfers": 8, "multi_thread_streams": 4}, 120.0),
        _r("syncthing", "small", "up", {}, 30.0),
        _r("syncthing", "small", "down", {}, 28.0),
    ]
    md = render_report(rows, baseline_mbps=60.0)

    assert "Lane A" in md
    assert "Lane B" in md
    assert "Lane C" in md
    assert "Recommended per-lane config" in md
    assert "rclone_sftp" in md
    assert "Did we beat Resolve Cloud" in md
    # Lane A winner is rclone_sftp @ 90 MB/s -- flags should be present
    assert "--transfers 8" in md


def test_render_report_baseline_math():
    rows = [_r("rclone_sftp", "large", "up", {"transfers": 8}, 100.0)]
    md = render_report(rows, baseline_mbps=60.0)
    # 60 Mbps -> 7.5 MB/s; 60 MB/s literal -> 60.0 MB/s
    assert "7.5 MB/s" in md
    assert "60.0 MB/s" in md


def test_render_report_handles_no_successful_runs():
    rows = [_r("rclone_sftp", "large", "up", {"transfers": 4}, 0.0, ok=False, verified=False, reason="exit 1")]
    md = render_report(rows)
    assert "no successful runs" in md.lower() or "No successful runs" in md
