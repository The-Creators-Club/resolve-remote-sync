"""cap_sheets evenly subsamples a clip's contact sheets to a ceiling.

The long tail of the real archive (9% of videos, 36% of all model calls) is
long clips sliced into many windows. Capping the sheets fed per video is the
lever that reclaims that cost. The property that makes it acceptable rather than
lossy-at-the-end is that it subsamples ACROSS the clip — first and last sheet
always kept — so a capped long clip still spans its whole duration.
"""
from __future__ import annotations

from pathlib import Path

from broll_index.claude_client import cap_sheets

SHEETS = [Path(f"s{i:03d}.jpg") for i in range(100)]


def test_no_cap_when_disabled():
    assert cap_sheets(SHEETS, 0) is SHEETS
    assert cap_sheets(SHEETS, -1) is SHEETS


def test_under_cap_is_unchanged():
    few = SHEETS[:10]
    assert cap_sheets(few, 24) == few


def test_caps_to_at_most_max():
    assert len(cap_sheets(SHEETS, 24)) <= 24
    assert len(cap_sheets(SHEETS, 1)) == 1


def test_keeps_first_and_last_so_full_span_is_covered():
    out = cap_sheets(SHEETS, 24)
    assert out[0] == SHEETS[0]
    assert out[-1] == SHEETS[-1]


def test_preserves_timecode_order():
    out = cap_sheets(SHEETS, 24)
    assert out == sorted(out, key=lambda p: p.name)


def test_even_stride_not_front_truncation():
    """The bug this guards against: taking the first N sheets, which would index
    only the opening of a long clip. The sample must reach the back half."""
    out = cap_sheets(SHEETS, 10)
    # at least one sheet from the final quarter of the clip
    assert any(int(p.name[1:4]) >= 75 for p in out)
    # and the spread should be wide, not clustered at the start
    idxs = [int(p.name[1:4]) for p in out]
    assert max(idxs) - min(idxs) == 99


def test_no_duplicate_sheets_under_aggressive_cap():
    """Rounding to nearest index can collide; the result must not repeat a sheet
    (a repeat would waste a cell and misrepresent coverage)."""
    for cap in (2, 3, 7, 13, 24, 37):
        out = cap_sheets(SHEETS, cap)
        assert len(out) == len(set(out)), f"cap={cap} produced duplicates"
