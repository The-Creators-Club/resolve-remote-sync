from __future__ import annotations

import time

import pytest

from ccbench.report import (
    BLEND_WARN_SECONDS,
    classify_lane,
    filter_since,
    lane_of,
    parse_since,
    render_report,
    summarize_repeats,
)
from ccbench.result import RunResult


def _r(
    engine, dataset, direction, params, MB_s, verified=True, ok=True, repeat_index=0,
    skipped=False, reason="", lane=None, loopback=False, verify_method="spot-check-sha256",
    timestamp=None, seconds=100.0, timing_resolution_s=0.0,
):
    return RunResult(
        engine=engine, dataset=dataset, direction=direction, params=params,
        seconds=seconds, num_bytes=int(MB_s * 1_000_000 * seconds), MB_s=MB_s,
        verified=verified, ok=ok, skipped=skipped, reason=reason,
        lane=classify_lane(dataset, direction) if lane is None else lane,
        repeat_index=repeat_index, loopback=loopback,
        bytes_source="rclone-stats", verify_method=verify_method,
        timestamp=time.time() if timestamp is None else timestamp,
        timing_resolution_s=timing_resolution_s,
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


def test_zero_multi_thread_streams_is_printed_not_dropped():
    """`--multi-thread-streams 0` is falsy but load-bearing: rclone's default
    is 4, so omitting the flag recommends a config that was never measured --
    quite possibly the one that lost."""
    rows = [_r("rclone_sftp", "large", "up", {"transfers": 8, "multi_thread_streams": 0}, 90.0)]
    md = render_report(rows)
    assert "--multi-thread-streams 0" in md


def test_a_nonzero_multi_thread_streams_winner_still_prints_its_value():
    rows = [_r("rclone_smb", "large", "up", {"transfers": 4, "multi_thread_streams": 8}, 90.0)]
    md = render_report(rows)
    assert "--multi-thread-streams 8" in md


def test_the_printed_flags_match_the_winning_params_exactly():
    """0 beating 4 must not be reported as 4."""
    rows = [
        _r("rclone_smb", "large", "up", {"transfers": 4, "multi_thread_streams": 0}, 120.0),
        _r("rclone_smb", "large", "up", {"transfers": 4, "multi_thread_streams": 4}, 60.0),
    ]
    md = render_report(rows)
    recommendation = md.split("Recommended per-lane config")[1]
    assert "Exact flags: `rclone copy ... --transfers 4 --multi-thread-streams 0`" in recommendation


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


# ---------------------------------------------------------------------------
# SHIP-7: a median that blends two sittings must say so
# ---------------------------------------------------------------------------


def test_repeats_measured_back_to_back_are_not_flagged_as_blended():
    now = time.time()
    rows = [
        _r("rclone_sftp", "large", "up", {"transfers": 8}, 380.0, repeat_index=0, timestamp=now),
        _r("rclone_sftp", "large", "up", {"transfers": 8}, 390.0, repeat_index=1, timestamp=now + 120),
    ]
    s = summarize_repeats(rows)[0]
    assert s.blended is False
    assert "BLENDED" not in render_report(rows)


def test_a_rerun_after_a_tuning_change_is_flagged_not_silently_medianed():
    """The NAS is retuned between two matrix runs and --rerun appends: 380/380
    and 760/760 median to 570 MB/s, a number nobody measured, with n 4/4."""
    now = time.time()
    old = now - 3 * 86400
    rows = [
        _r("rclone_sftp", "large", "up", {"transfers": 8}, 380.0, repeat_index=0, timestamp=old),
        _r("rclone_sftp", "large", "up", {"transfers": 8}, 380.0, repeat_index=1, timestamp=old + 60),
        _r("rclone_sftp", "large", "up", {"transfers": 8}, 760.0, repeat_index=0, timestamp=now),
        _r("rclone_sftp", "large", "up", {"transfers": 8}, 760.0, repeat_index=1, timestamp=now + 60),
    ]
    s = summarize_repeats(rows)[0]
    assert s.median_mb_s == 570.0  # the fabricated middle is still computed...
    assert s.span_seconds > BLEND_WARN_SECONDS
    assert s.blended is True

    md = render_report(rows)
    assert "BLENDED" in md            # ...but it is no longer presented silently
    assert "3.0 d" in md
    assert "--since" in md
    # and the caveat follows the winner into the recommendation somebody copies
    assert "BLENDED" in md.split("Recommended per-lane config")[1]


def test_a_failed_attempt_from_last_week_does_not_make_todays_repeats_a_blend():
    now = time.time()
    rows = [
        _r("rclone_sftp", "large", "up", {"transfers": 8}, 0.0, ok=False, verified=False,
           reason="exit 1", repeat_index=0, timestamp=now - 7 * 86400),
        _r("rclone_sftp", "large", "up", {"transfers": 8}, 380.0, repeat_index=0, timestamp=now),
        _r("rclone_sftp", "large", "up", {"transfers": 8}, 390.0, repeat_index=1, timestamp=now + 60),
    ]
    assert summarize_repeats(rows)[0].blended is False


def test_since_filters_rows_by_their_recorded_timestamp():
    now = time.time()
    rows = [
        _r("rclone_sftp", "large", "up", {"transfers": 8}, 380.0, timestamp=now - 5 * 86400),
        _r("rclone_sftp", "large", "up", {"transfers": 8}, 760.0, timestamp=now),
    ]
    kept = filter_since(rows, now - 86400)
    assert [r.MB_s for r in kept] == [760.0]

    md = render_report(kept, since_label="2026-08-14")
    assert "**760.0 MB/s median**" in md
    assert "2026-08-14" in md  # the slice is stated in the artifact itself


@pytest.mark.parametrize("text, hours", [("24h", 24), ("7d", 168), ("1.5h", 1.5), ("2 D", 48)])
def test_parse_since_relative_shorthand(text, hours):
    now = 1_000_000.0
    assert parse_since(text, now=now) == pytest.approx(now - hours * 3600)


def test_parse_since_iso8601_and_refusal_to_guess():
    assert parse_since("2026-08-14") == pytest.approx(
        __import__("datetime").datetime(2026, 8, 14).timestamp()
    )
    for bad in ("", "last tuesday", "24x", "2026-13-01"):
        with pytest.raises(ValueError):
            parse_since(bad)


# ---------------------------------------------------------------------------
# SHIP-10: a polled clock's resolution is printed, not swallowed
# ---------------------------------------------------------------------------


def test_a_coarse_clock_on_a_short_run_is_called_out():
    rows = [
        _r("syncthing", "small", "up", {}, 30.0, lane="C", loopback=True,
           seconds=2.0, timing_resolution_s=0.1),
    ]
    md = render_report(rows)
    assert "clock +/-0.10s on a 2.0s run" in md
    assert "5% instrument error" in md


def test_the_same_resolution_on_a_long_run_is_not_worth_saying():
    rows = [
        _r("syncthing", "large", "up", {}, 30.0, lane="A", loopback=True,
           seconds=600.0, timing_resolution_s=0.1),
    ]
    assert "instrument error" not in render_report(rows)


def test_rows_from_bracketed_runners_carry_no_clock_note():
    rows = [_r("rclone_sftp", "large", "up", {"transfers": 8}, 90.0, seconds=2.0)]
    assert "instrument error" not in render_report(rows)
