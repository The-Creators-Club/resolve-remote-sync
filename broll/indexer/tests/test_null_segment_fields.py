"""A present-but-null segment field must not discard a paid-for clip.

Validation checked that required segment keys were PRESENT, not that they held
a value. `{"t_end": null}` passed, then died at the INSERT on a NOT NULL column
— after every contact-sheet call for that clip had already been spent. Three
clips on the real archive failed exactly this way (segments.t_end x2,
segments.setting x1) and would have failed identically on every rerun.
"""
from __future__ import annotations

import pytest

from broll_index.claude_client import validate_contract

BASE_SEG = {
    "t_start": 0.0,
    "t_end": 5.0,
    "description": "a pier",
    "objects": ["pier", "boat"],
    "setting": "harbor",
    "motion": "static",
}


def _payload(*segments):
    return {
        "themes": ["harbor"],
        "category_hint": None,
        "quality_flags": [],
        "segments": list(segments),
    }


def test_a_null_text_field_becomes_empty_string():
    """setting/description/objects/motion are DEFAULT '' in the schema and mean
    'nothing found' — exactly what a null is trying to say."""
    out = validate_contract(_payload({**BASE_SEG, "setting": None}))
    assert out["segments"][0]["setting"] == ""
    assert out["segments"][0]["description"] == "a pier", "other fields untouched"


@pytest.mark.parametrize("field", ["description", "setting", "motion"])
def test_every_required_text_field_tolerates_null(field):
    out = validate_contract(_payload({**BASE_SEG, field: None}))
    assert out["segments"][0][field] == ""


def test_a_null_objects_list_becomes_an_empty_list_not_a_string():
    """`objects` is a LIST in the contract and the writer ", "-joins it.
    Coercing it to "" would silently drop every object keyword on the clip,
    which is most of what makes the clip findable."""
    out = validate_contract(_payload({**BASE_SEG, "objects": None}))
    assert out["segments"][0]["objects"] == []


def test_a_healthy_objects_list_survives():
    out = validate_contract(_payload(BASE_SEG))
    assert out["segments"][0]["objects"] == ["pier", "boat"]


def test_a_non_string_text_field_is_also_coerced():
    out = validate_contract(_payload({**BASE_SEG, "setting": 42}))
    assert out["segments"][0]["setting"] == ""


@pytest.mark.parametrize("field", ["t_start", "t_end"])
def test_a_segment_with_no_usable_time_is_dropped_not_fatal(field):
    """A time cannot be invented, but losing one segment beats losing the clip."""
    out = validate_contract(_payload({**BASE_SEG, field: None},
                                        {**BASE_SEG, "t_start": 5.0, "t_end": 9.0}))
    assert len(out["segments"]) == 1
    assert out["segments"][0]["t_start"] == 5.0


def test_a_non_numeric_time_is_dropped_too():
    out = validate_contract(_payload({**BASE_SEG, "t_end": "5 seconds"},
                                        {**BASE_SEG, "t_start": 5.0, "t_end": 9.0}))
    assert len(out["segments"]) == 1


def test_all_segments_untimed_still_raises():
    """Nothing to write. Marking the clip indexed with zero segments would hide
    the failure instead of surfacing it."""
    with pytest.raises(ValueError, match="t_start/t_end"):
        validate_contract(_payload({**BASE_SEG, "t_end": None}))


def test_a_genuinely_missing_key_still_raises():
    """The present-but-null fix must not weaken the missing-key check."""
    seg = {k: v for k, v in BASE_SEG.items() if k != "setting"}
    with pytest.raises(ValueError, match="missing keys"):
        validate_contract(_payload(seg))


def test_a_healthy_response_is_unchanged():
    out = validate_contract(_payload(BASE_SEG))
    assert len(out["segments"]) == 1
    for k, v in BASE_SEG.items():
        assert out["segments"][0][k] == v


def test_integer_times_are_accepted():
    """A model returning 0 rather than 0.0 is not an error."""
    out = validate_contract(_payload({**BASE_SEG, "t_start": 0, "t_end": 5}))
    assert len(out["segments"]) == 1
