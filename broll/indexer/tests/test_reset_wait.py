"""Sleep until the reset the 429 actually names, instead of polling blindly.

run_queue.py polled every 15 minutes on a rate limit. Each poll relaunches the
API stage with --api-workers concurrent calls, so ~26 requests go out and all
429 before the parent cancels the rest. On 2026-08-02 that ran 21 times against
limits that printed their own reset time ("resets 4:30am (Asia/Taipei)") —
about 546 calls spent learning nothing.
"""
from __future__ import annotations

from datetime import datetime

import pytest

from broll_index.claude_client import (
    MAX_RESET_WAIT_S,
    RESET_MARGIN_S,
    extract_reset_hint,
    seconds_until_reset,
)

REAL_429 = ("claude exited 1: API error 429: You've hit your session limit "
            "· resets 4:30am (Asia/Taipei)")


def test_the_hint_is_extracted_from_a_real_error_line():
    assert extract_reset_hint(REAL_429).startswith("4:30am")


def test_a_later_time_today_waits_until_then():
    now = datetime(2026, 8, 2, 2, 18, 0)          # the real 02:18 limit hit
    wait = seconds_until_reset("4:30am (Asia/Taipei)", now=now)
    assert wait == pytest.approx((2 * 3600 + 12 * 60) + RESET_MARGIN_S)


def test_a_time_already_past_rolls_to_tomorrow():
    """A limit hit at 11pm that resets '1am' is two hours away, not twenty-two
    hours ago."""
    now = datetime(2026, 8, 2, 23, 0, 0)
    wait = seconds_until_reset("1am", now=now)
    assert wait == pytest.approx(2 * 3600 + RESET_MARGIN_S)


def test_pm_and_bare_hours_parse():
    now = datetime(2026, 8, 2, 13, 0, 0)
    assert seconds_until_reset("5pm (Asia/Taipei)", now=now) == pytest.approx(
        4 * 3600 + RESET_MARGIN_S)


@pytest.mark.parametrize("hint,at,expected_hour", [
    ("12am", datetime(2026, 8, 2, 20, 0), 0),    # midnight, not noon
    ("12pm", datetime(2026, 8, 2, 6, 0), 12),    # noon, not midnight
])
def test_the_twelve_oclock_edge_cases(hint, at, expected_hour):
    wait = seconds_until_reset(hint, now=at)
    landed = at.timestamp() + wait - RESET_MARGIN_S
    assert datetime.fromtimestamp(landed).hour == expected_hour


def test_the_margin_clears_the_boundary():
    """Retrying on the dot races the reset and spends a whole worker set on a
    429 that would have succeeded a moment later."""
    now = datetime(2026, 8, 2, 4, 0, 0)
    assert seconds_until_reset("4:30am", now=now) > 30 * 60


@pytest.mark.parametrize("hint", [None, "", "soon", "whenever", "next Tuesday"])
def test_an_unusable_hint_falls_back(hint):
    assert seconds_until_reset(hint) is None


def test_an_absurd_wait_falls_back_rather_than_parking_the_run():
    """A misparsed or wrong-zone hint must not sleep the run for half a day."""
    now = datetime(2026, 8, 2, 5, 0, 0)
    assert seconds_until_reset("4am", now=now) is None  # ~23h away -> reject
    assert MAX_RESET_WAIT_S == 6 * 3600


def test_a_nonsense_clock_time_is_rejected():
    assert seconds_until_reset("99:99") is None


def test_the_whole_path_from_a_real_error_string():
    """End to end: the exact text the run logged all night must produce a wait."""
    now = datetime(2026, 8, 2, 2, 18, 0)
    wait = seconds_until_reset(extract_reset_hint(REAL_429), now=now)
    assert wait is not None and 0 < wait < MAX_RESET_WAIT_S
