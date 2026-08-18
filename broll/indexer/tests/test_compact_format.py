"""compact_format.py: grammar shape, tolerant parsing, category assignment
(TF-IDF path, so no fastembed download in CI), and pixel exposure flags."""
from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from broll_index import compact_format
from broll_index.compact_format import (
    CategoryAssigner, build_compact_prompt, build_grammar, clip_text_for_category,
    frame_table, parse_compact, parse_compact_lines, pixel_quality_flags, seconds_to_tc,
)


def _frames(n: int, start_t: float = 0.0, step: float = 4.0) -> list[dict]:
    return [{"i": i, "t": start_t + i * step, "tc": seconds_to_tc(start_t + i * step)}
            for i in range(n)]


# ---------------------------------------------------------------------------
# prompt / frame table
# ---------------------------------------------------------------------------

def test_frame_table_lists_every_frame_with_its_timecode():
    frames = _frames(3)
    table = frame_table(frames)
    assert table == "F1=00:00:00 F2=00:00:04 F3=00:00:08"


def test_build_compact_prompt_substitutes_the_frame_table():
    prompt = build_compact_prompt(_frames(2))
    assert "F1=00:00:00 F2=00:00:04" in prompt
    assert "__FRAME_TABLE__" not in prompt


def test_seconds_to_tc_rounds_and_floors_at_zero():
    assert seconds_to_tc(0) == "00:00:00"
    assert seconds_to_tc(-3) == "00:00:00"
    assert seconds_to_tc(3661.6) == "01:01:02"


# ---------------------------------------------------------------------------
# grammar
# ---------------------------------------------------------------------------

def test_grammar_bounds_frame_ids_to_the_window():
    g = build_grammar(3)
    assert '"F1"' in g and '"F3"' in g and '"F4"' not in g
    assert "root ::= sline{1,3} tline" in g


def test_grammar_at_least_one_frame():
    g = build_grammar(0)
    assert "sline{1,1}" in g  # max(1, n)


# ---------------------------------------------------------------------------
# parser
# ---------------------------------------------------------------------------

def test_parse_compact_lines_basic_shot_and_theme():
    text = (
        "S F1-F2 | crowd interior, dim lighting | crowd;people;interior | - // -\n"
        "T police operation;press conference\n"
    )
    shots, themes, problems = parse_compact_lines(text, 4)
    assert len(shots) == 1
    assert shots[0]["f_start"] == 0 and shots[0]["f_end"] == 1
    assert shots[0]["objects"] == ["crowd", "people", "interior"]
    assert shots[0]["onscreen_text"] == "" and shots[0]["onscreen_text_en"] == ""
    assert themes == ["police operation", "press conference"]
    assert not problems


def test_parse_compact_lines_tolerates_markdown_bullets_and_prefixes():
    text = "- S1: F1 | newsreader | newsreader | - // -\n* T: news\n"
    shots, themes, problems = parse_compact_lines(text, 2)
    assert len(shots) == 1
    assert themes == ["news"]


def test_parse_compact_lines_onscreen_text_with_embedded_pipe_and_double_slash():
    text = "S F1 | title card | logo | CTBC | FLYING OYSTER // CTBC flying oyster\n" "T brand\n"
    shots, _themes, _problems = parse_compact_lines(text, 1)
    assert shots[0]["onscreen_text"] == "CTBC | FLYING OYSTER"
    assert shots[0]["onscreen_text_en"] == "CTBC flying oyster"


def test_parse_compact_lines_records_unparsed_lines_as_problems_not_fatal():
    text = "some stray commentary\nS F1 | ok | - | - // -\nT x\n"
    shots, _themes, problems = parse_compact_lines(text, 1)
    assert len(shots) == 1
    assert any("unparsed" in p for p in problems)


def test_parse_compact_lines_clamps_out_of_range_frame_ids():
    shots, _themes, _problems = parse_compact_lines("S F1-F9 | wide | - | - // -\nT x\n", 3)
    assert shots[0]["f_start"] == 0 and shots[0]["f_end"] == 2  # clamped to n=3


def test_parse_compact_lines_no_s_lines_raises_via_parse_compact():
    frames = _frames(2)
    with pytest.raises(ValueError, match="no S lines parsed"):
        parse_compact("T only themes, no shots\n", frames)


def test_parse_compact_returns_the_validate_contract_shape():
    frames = _frames(3)
    text = "S F1-F2 | crowd | people;crowd | - // -\nS F3 | newsreader | newsreader | 華視新聞 // CTS News\nT news\n"
    contract, problems = parse_compact(text, frames)
    assert set(contract.keys()) == {"themes", "category_hint", "quality_flags", "segments"}
    assert contract["themes"] == ["news"]
    assert len(contract["segments"]) == 2
    seg0 = contract["segments"][0]
    assert seg0["t_start"] == frames[0]["t"] and seg0["t_end"] == frames[1]["t"]
    assert seg0["setting"] == "" and seg0["motion"] == ""
    seg1 = contract["segments"][1]
    # canonicalize_no_visual_label runs inside validate_contract
    assert seg1["description"] == "newsreader"
    assert seg1["onscreen_text"] == "華視新聞"
    assert seg1["onscreen_text_en"] == "CTS News"
    assert not problems


def test_parse_compact_lines_dedupes_and_splits_object_lists_on_semicolon_or_comma():
    shots, _t, _p = parse_compact_lines("S F1 | x | crowd;People;crowd | - // -\nT x\n", 1)
    assert shots[0]["objects"] == ["crowd", "People"]  # case-insensitive dedupe, order preserved


# ---------------------------------------------------------------------------
# category assignment (TF-IDF path — no network / fastembed dependency in CI)
# ---------------------------------------------------------------------------

_TAXONOMY = [
    {"slug": "society/policing-crime", "label": "Policing & crime", "description": "police officers, arrests, courts"},
    {"slug": "environment/waste-recycling", "label": "Waste & recycling", "description": "recycling facility, sorting, landfill"},
    {"slug": "general/unsorted", "label": "Unsorted", "description": ""},
]


def test_category_assigner_tfidf_picks_the_closest_slug():
    assigner = CategoryAssigner(_TAXONOMY, prefer="tfidf")
    assert assigner.method == "tfidf"
    slug, score = assigner.assign("police officers arresting suspects, handcuffs, patrol car")
    assert slug == "society/policing-crime"
    assert score > 0


def test_category_assigner_below_min_score_returns_none():
    assigner = CategoryAssigner(_TAXONOMY, prefer="tfidf", min_score=2.0)  # unreachable score
    slug, score = assigner.assign("police officers arresting suspects")
    assert slug is None


def test_category_assigner_empty_taxonomy_or_text_returns_none():
    assigner = CategoryAssigner([], prefer="tfidf")
    assert assigner.assign("anything") == (None, 0.0)
    assigner2 = CategoryAssigner(_TAXONOMY, prefer="tfidf")
    assert assigner2.assign("   ") == (None, 0.0)


def test_clip_text_for_category_concatenates_themes_descriptions_objects():
    result = {
        "themes": ["police"],
        "segments": [{"description": "arrest", "objects": ["handcuffs", "patrol car"]}],
    }
    text = clip_text_for_category(result)
    assert "police" in text and "arrest" in text and "handcuffs" in text


# ---------------------------------------------------------------------------
# pixel exposure flags
# ---------------------------------------------------------------------------

def _write_solid_jpg(path: Path, level: int) -> Path:
    Image.new("L", (64, 36), color=level).convert("RGB").save(path, "JPEG")
    return path


def test_pixel_quality_flags_overexposed(tmp_path):
    paths = [_write_solid_jpg(tmp_path / f"f{i}.jpg", 250) for i in range(3)]
    flags, stats = pixel_quality_flags(paths)
    assert "overexposed" in flags
    assert len(stats) == 3


def test_pixel_quality_flags_underexposed_excludes_true_black_frames(tmp_path):
    # A near-black frame is content (v6 labels it 'black frame'), not a fault —
    # only DIM-but-not-black frames should trip underexposed.
    paths = [_write_solid_jpg(tmp_path / f"f{i}.jpg", 30) for i in range(3)]
    flags, _stats = pixel_quality_flags(paths)
    assert "underexposed" in flags


def test_pixel_quality_flags_true_black_frames_are_not_flagged(tmp_path):
    paths = [_write_solid_jpg(tmp_path / f"f{i}.jpg", 2) for i in range(3)]
    flags, _stats = pixel_quality_flags(paths)
    assert "underexposed" not in flags


def test_pixel_quality_flags_normal_exposure_no_flags(tmp_path):
    paths = [_write_solid_jpg(tmp_path / f"f{i}.jpg", 120) for i in range(3)]
    flags, _stats = pixel_quality_flags(paths)
    # A flat solid-colour test frame has zero Laplacian variance, which is a
    # legitimate soft_focus trigger on its own — only exposure is asserted here.
    assert "overexposed" not in flags and "underexposed" not in flags


def test_pixel_quality_flags_unreadable_file_recorded_as_error_not_raised(tmp_path):
    bad = tmp_path / "not_an_image.jpg"
    bad.write_bytes(b"not a jpeg")
    flags, stats = pixel_quality_flags([bad])
    assert flags == []
    assert "error" in stats[0]
