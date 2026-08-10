"""Reciprocal Rank Fusion -- pure function, no DB needed. See
app.search.reciprocal_rank_fusion's docstring for why RRF (rather than
combining raw bm25/cosine scores) is the load-bearing design choice here.
"""
from __future__ import annotations

import pytest

from app.search import RRF_K, reciprocal_rank_fusion


def test_empty_rank_lists_returns_empty():
    assert reciprocal_rank_fusion({}) == {}


def test_source_with_no_hits_is_safe():
    scores = reciprocal_rank_fusion({"a": [], "b": ["x"]})
    assert scores == {"x": 1.0 / (RRF_K + 1)}


def test_single_source_ranks_are_monotonically_decreasing():
    scores = reciprocal_rank_fusion({"a": ["first", "second", "third"]})
    assert scores["first"] > scores["second"] > scores["third"]


def test_item_present_in_multiple_sources_sums_contributions():
    # "shared" is ranked #2 in both sources; a lone appearance at #2 would
    # only get one source's contribution.
    scores = reciprocal_rank_fusion(
        {
            "a": ["other_a", "shared"],
            "b": ["other_b", "shared"],
        }
    )
    lone_rank2_contribution = 1.0 / (RRF_K + 2)
    assert scores["shared"] == pytest.approx(2 * lone_rank2_contribution)


def test_several_modest_rankings_can_outrank_one_top_ranking():
    """The whole point of RRF over "just trust the single best-ranked
    source": a segment ranked #3-#5 by several independent sources
    accumulates enough partial votes to beat one ranked #1 by only a single
    source."""
    rank_lists = {
        "segments_fts": ["solo_winner", "modest", "x", "y", "z"],
        "segments_cjk_fts": ["a", "b", "modest", "c", "d"],
        "transcript_fts": ["e", "modest", "f", "g", "h"],
        "transcript_cjk_fts": ["i", "j", "k", "modest", "l"],
    }
    scores = reciprocal_rank_fusion(rank_lists)
    assert scores["modest"] > scores["solo_winner"]


def test_deterministic_for_identical_input():
    rank_lists = {"a": ["x", "y", "z"], "b": ["z", "x"]}
    first = reciprocal_rank_fusion(rank_lists)
    second = reciprocal_rank_fusion(rank_lists)
    assert first == second


def test_custom_k_changes_relative_weighting_but_not_ordering():
    rank_lists = {"a": ["first", "second"]}
    default_scores = reciprocal_rank_fusion(rank_lists)
    tight_scores = reciprocal_rank_fusion(rank_lists, k=1)
    assert default_scores["first"] > default_scores["second"]
    assert tight_scores["first"] > tight_scores["second"]
    assert tight_scores["first"] != default_scores["first"]
