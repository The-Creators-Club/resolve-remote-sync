"""merge_similar_segments: the eval's remaining known gap
(broll/eval/local_vlm/results/report.md: ~10.3 predicted segments/clip vs
Haiku's 4.3), and the over-segmented shapes actually seen there."""
from __future__ import annotations

from broll_index.local_vlm import merge_similar_segments


def _seg(t_start, t_end, desc, objects, text="", text_en=""):
    return {"t_start": t_start, "t_end": t_end, "description": desc, "objects": objects,
            "setting": "", "motion": "", "onscreen_text": text, "onscreen_text_en": text_en}


def test_merge_adjacent_near_duplicate_segments():
    segments = [
        _seg(0, 4, "man in white hat and shirt walking away from camera, overcast sky", ["man", "hat"]),
        _seg(4, 4, "man in white hat and shirt walking away from camera, overcast sky, cameraman", ["man", "hat", "cameraman"]),
        _seg(8, 8, "man in white hat and shirt standing still facing away, overcast sky", ["man", "hat"]),
        _seg(12, 16, "wind turbine, muddy field, overcast sky", ["wind turbine", "field"]),
    ]
    merged, n_merges = merge_similar_segments(segments)
    # The first three (same man, same setting, near-identical wording) collapse
    # into one; the wind-turbine shot is different enough to stay separate.
    assert len(merged) == 2
    assert n_merges == 2
    assert merged[0]["t_start"] == 0 and merged[0]["t_end"] == 8
    assert set(merged[0]["objects"]) == {"man", "hat", "cameraman"}


def test_merge_keeps_dissimilar_adjacent_segments_apart():
    segments = [
        _seg(0, 4, "crowd interior, dim lighting, people in white shirts", ["crowd", "people"]),
        _seg(6, 6, "newsreader", ["newsreader", "presenter"]),
        _seg(10, 13, "crowded public transport interior, passengers seated", ["passengers", "transport"]),
    ]
    merged, n_merges = merge_similar_segments(segments)
    assert n_merges == 0
    assert len(merged) == 3


def test_merge_is_not_transitive_across_a_dissimilar_middle_segment():
    """A -> B similar, B -> C similar, but A and C alone would not merge if
    adjacent: the chain must go through B, and a non-adjacent pair is never
    compared directly."""
    segments = [
        _seg(0, 4, "man in white hat and shirt walking, overcast sky", ["man", "hat"]),
        _seg(4, 8, "man in white hat and shirt walking, overcast sky, close-up", ["man", "hat"]),
        _seg(8, 12, "wind turbine, muddy field", ["wind turbine", "field"]),
    ]
    merged, n_merges = merge_similar_segments(segments)
    assert n_merges == 1
    assert len(merged) == 2
    assert merged[0]["t_end"] == 8
    assert merged[1]["description"] == "wind turbine, muddy field"


def test_merge_union_of_objects_case_insensitive_order_preserving():
    segments = [
        _seg(0, 0, "x", ["Crowd", "People"]),
        _seg(0, 0, "x", ["crowd", "people", "banner"]),
    ]
    merged, n = merge_similar_segments(segments)
    assert n == 1
    assert merged[0]["objects"] == ["Crowd", "People", "banner"]


def test_merge_concatenates_onscreen_text_when_different():
    segments = [
        _seg(0, 4, "logo shot", ["logo"], text="CTBC", text_en="CTBC"),
        _seg(4, 8, "logo shot", ["logo"], text="FLYING OYSTER", text_en="Flying Oyster"),
    ]
    merged, n = merge_similar_segments(segments)
    assert n == 1
    assert merged[0]["onscreen_text"] == "CTBC | FLYING OYSTER"
    assert merged[0]["onscreen_text_en"] == "CTBC | Flying Oyster"


def test_merge_empty_and_single_segment_are_no_ops():
    assert merge_similar_segments([]) == ([], 0)
    one = [_seg(0, 1, "x", [])]
    merged, n = merge_similar_segments(one)
    assert n == 0 and merged == one


def test_merge_ten_over_segmented_shots_down_to_about_four():
    """Reproduces the eval's over-segmentation shape (report.md's 20-largest-
    disagreements list, e.g. clip 7272/8264): a handful of DISTINCT shots each
    sampled multiple times in a row by the per-frame windowing."""
    segments = []
    shots = [
        ("man with glasses erasing whiteboard, room interior, window, ceiling fan", ["man", "whiteboard", "window"], 3),
        ("man standing in front of whiteboard holding marker, classroom setting", ["man", "whiteboard", "marker"], 3),
        ("room interior, folding chairs and tables, chevron-patterned floor", ["chairs", "tables", "floor"], 2),
        ("man writing on whiteboard, glasses, checkered shirt, indoor setting", ["man", "whiteboard"], 2),
    ]
    t = 0.0
    for desc, objs, repeats in shots:
        for _ in range(repeats):
            segments.append(_seg(t, t, desc, list(objs)))
            t += 4.0
    assert len(segments) == 10
    merged, n_merges = merge_similar_segments(segments)
    assert len(merged) == 4
    assert n_merges == 6
