from __future__ import annotations

from ccbench.report import classify_lane, lane_of, render_report, summarize_repeats
from ccbench.result import RunResult


def _r(
    engine, dataset, direction, params, MB_s, verified=True, ok=True, repeat_index=0,
    skipped=False, reason="", lane=None, loopback=False, verify_method="spot-check-sha256",
):
    return RunResult(
        engine=engine, dataset=dataset, direction=direction, params=params,
        seconds=100.0, num_bytes=int(MB_s * 1_000_000 * 100), MB_s=MB_s,
        verified=verified, ok=ok, skipped=skipped, reason=reason,
        lane=classify_lane(dataset, direction) if lane is None else lane,
        repeat_index=repeat_index, loopback=loopback,
        bytes_source="rclone-stats", verify_method=verify_method,
    )


def test_classify_lane_is_legacy_fallback_only():
    assert classify_lane("large", "up") == "A"
    assert classify_lane("large", "down") == "B"
    assert classify_lane("small", "up") == "C"
    assert classify_lane("small", "down") == "C"
    assert classify_lane("network", "up") == "net"
    assert classify_lane("weird", "up") == "?"


def test_lane_of_uses_the_recorded_lane_not_the_dataset_name():
    """A dataset dir named 'large_smallish' or 'data/large' must not be able to
    move a run into another lane: the lane comes from bench.toml via matrix.py."""
    row = _r("rclone_sftp", "large_and_small_mixed", "up", {"transfers": 4}, 50.0, lane="C")
    assert lane_of(row) == "C"

    legacy = _r("rclone_sftp", "large", "up", {"transfers": 4}, 50.0, lane="")
    assert lane_of(legacy) == "A"  # falls back to substring classification


def test_lane_is_carried_into_the_report_sections():
    rows = [_r("rclone_sftp", "weirdly_named_dataset", "up", {"transfers": 8}, 90.0, lane="A")]
    md = render_report(rows)
    assert "Lane A" in md
    assert "Lane ?" not in md


def test_summarize_repeats_reports_median_with_min_and_max():
    rows = [
        _r("rclone_sftp", "large", "up", {"transfers": 4}, 50.0, repeat_index=0),
        _r("rclone_sftp", "large", "up", {"transfers": 4}, 60.0, repeat_index=1),
        _r("rclone_sftp", "large", "up", {"transfers": 4}, 200.0, repeat_index=2),
    ]
    summaries = summarize_repeats(rows)
    assert len(summaries) == 1
    s = summaries[0]
    assert s.median_mb_s == 60.0  # not the lucky 200.0 max
    assert s.min_mb_s == 50.0
    assert s.max_mb_s == 200.0
    assert s.n_ok == 3


def test_summarize_repeats_ignores_failed_repeats_in_the_median():
    rows = [
        _r("rclone_sftp", "large", "up", {"transfers": 4}, 80.0, repeat_index=0),
        _r("rclone_sftp", "large", "up", {"transfers": 4}, 0.0, ok=False, verified=False, repeat_index=1),
        _r("rclone_sftp", "large", "up", {"transfers": 4}, 100.0, repeat_index=2),
    ]
    s = summarize_repeats(rows)[0]
    assert s.median_mb_s == 90.0
    assert (s.n_ok, s.n_total) == (2, 3)


def test_summarize_repeats_verified_only_when_every_repeat_verified():
    rows = [
        _r("rclone_sftp", "large", "up", {"transfers": 4}, 80.0, verified=True, repeat_index=0),
        _r("rclone_sftp", "large", "up", {"transfers": 4}, 90.0, verified=False, repeat_index=1),
    ]
    assert summarize_repeats(rows)[0].verified is False


def test_summarize_repeats_keeps_failed_representative():
    rows = [_r("syncthing", "small", "up", {}, 0.0, ok=False, verified=False, reason="boom")]
    summaries = summarize_repeats(rows)
    assert len(summaries) == 1
    assert summaries[0].ok is False


def test_median_is_reported_not_max_in_the_rendered_table():
    rows = [
        _r("rclone_sftp", "large", "up", {"transfers": 8}, 40.0, repeat_index=0),
        _r("rclone_sftp", "large", "up", {"transfers": 8}, 45.0, repeat_index=1),
        _r("rclone_sftp", "large", "up", {"transfers": 8}, 300.0, repeat_index=2),
    ]
    md = render_report(rows)
    assert "median MB/s" in md
    assert "**45.0 MB/s median**" in md
    assert "300.0" in md  # kept, but as the max column


def test_render_report_contains_lane_sections_and_winner():
    rows = [
        _r("rclone_sftp", "large", "up", {"transfers": 8, "multi_thread_streams": 0}, 90.0),
        _r("robocopy_smb", "large", "up", {"mt": 16}, 40.0),
        _r("rclone_sftp", "large", "down", {"transfers": 8, "multi_thread_streams": 4}, 120.0),
        _r("syncthing", "small", "up", {}, 30.0, loopback=True),
        _r("syncthing", "small", "down", {}, 28.0, loopback=True),
    ]
    md = render_report(rows, baseline_mbps=60.0)

    assert "Lane A" in md
    assert "Lane B" in md
    assert "Lane C" in md
    assert "Recommended per-lane config" in md
    assert "rclone_sftp" in md
    assert "Did we beat Resolve Cloud" in md
    assert "--transfers 8" in md


def test_chunk_size_flag_is_rendered_in_kib():
    rows = [_r("rclone_sftp", "large", "up", {"transfers": 8, "sftp_chunk_size_kib": 255}, 90.0)]
    md = render_report(rows)
    assert "--sftp-chunk-size 255Ki" in md
    assert "255M" not in md


def test_legacy_megabyte_chunk_rows_are_flagged_not_silently_rendered():
    rows = [_r("rclone_sftp", "large", "up", {"transfers": 8, "sftp_chunk_size_mb": 32}, 90.0)]
    md = render_report(rows)
    assert "LEGACY MB unit" in md


def test_loopback_rows_are_labelled_and_never_beat_a_network_row():
    rows = [
        _r("syncthing", "small", "up", {}, 900.0, loopback=True),
        _r("rclone_sftp", "small", "up", {"transfers": 8}, 30.0),
    ]
    md = render_report(rows)
    assert "Loopback" in md
    assert "YES -- not comparable" in md
    # lane C winner must be the real-network rclone row, not the loopback pair
    assert "**Winner: `rclone_sftp`**" in md
    assert "**Winner: `syncthing`**" not in md


def test_loopback_only_lane_names_the_winner_but_marks_it_non_comparable():
    rows = [_r("syncthing", "small", "up", {}, 900.0, loopback=True)]
    md = render_report(rows)
    assert "**Winner: `syncthing`**" in md
    assert "LOOPBACK measurement" in md


def test_render_report_baseline_math():
    rows = [_r("rclone_sftp", "large", "up", {"transfers": 8}, 100.0)]
    md = render_report(rows, baseline_mbps=60.0)
    # 60 Mbps -> 7.5 MB/s; 60 MB/s literal -> 60.0 MB/s (both decimal MB)
    assert "7.5 MB/s" in md
    assert "60.0 MB/s" in md


def test_render_report_handles_no_successful_runs():
    rows = [_r("rclone_sftp", "large", "up", {"transfers": 4}, 0.0, ok=False, verified=False, reason="exit 1")]
    md = render_report(rows)
    assert "no successful runs" in md.lower()


def test_verification_method_is_visible_in_the_table():
    rows = [
        _r("rclone_sftp", "large", "up", {"transfers": 4}, 50.0, verified=False,
           verify_method="exit-code-only"),
    ]
    md = render_report(rows)
    assert "exit-code-only" in md
