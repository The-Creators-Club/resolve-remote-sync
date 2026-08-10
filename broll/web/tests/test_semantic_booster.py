"""mode="hybrid" precision regression tests -- see
docs/indexing-findings.md's "Semantic search cannot prove absence" and
app/search.py's module docstring.

Before this change, semantic ran as an equal-weight RRF source and every
query returned results, because nearest-neighbour retrieval always has
neighbours. These tests pin down the fix: keyword determines the result
set, semantic only ADDS videos keyword missed (floored, capped), and an
empty result set is the correct, expected outcome for a query that matches
nothing.

The encoder is always mocked via monkeypatching
app.semantic._load_fastembed_encoder -- never download a real model here.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from app import semantic
from app.search import SEMANTIC_COSINE_FLOOR, SEMANTIC_ONLY_MAX_VIDEOS
from tests.factories import insert_embedding, insert_segment, insert_video

MODEL = semantic.DEFAULT_MODEL


class FakeEncoder:
    """Returns a preset vector per exact query string; unknown queries get
    an all-zero vector (cosine similarity 0 against anything)."""

    def __init__(self, vectors: dict[str, list[float]]):
        self._vectors = vectors

    def embed(self, docs):
        for d in docs:
            vec = self._vectors.get(d, [0.0, 0.0])
            yield np.array(vec, dtype=np.float32)


def _patch_encoder(monkeypatch, vectors: dict[str, list[float]]) -> None:
    monkeypatch.setattr(
        semantic, "_load_fastembed_encoder", lambda name: FakeEncoder(vectors)
    )


def _unit_2d_with_cosine(score: float) -> list[float]:
    """A 2D unit vector whose dot product with (1.0, 0.0) is exactly
    `score` -- lets a test pin an embedding's similarity to a query encoded
    as (1.0, 0.0) precisely, rather than approximately."""
    return [score, math.sqrt(max(0.0, 1.0 - score * score))]


QUERY_VEC = [1.0, 0.0]

# A query guaranteed to hit nothing in any of the four FTS sources or the
# fuzzy retry (no indexed word anywhere close to these), so every result in
# these tests comes only from the semantic pass.
ABSENT_QUERY = "wedding ceremony wholly absent footage"


# ---------------------------------------------------------------------------
# The regression this task exists to fix: mediocre semantic similarity
# everywhere must not manufacture a result.
# ---------------------------------------------------------------------------


def test_uniformly_mediocre_semantic_similarity_returns_zero_videos(
    client, conn, monkeypatch
):
    for score in (0.40, 0.42, 0.45, 0.48):
        video_id = insert_video(conn, share="broll", rel_path=f"noise_{score}.mov")
        seg_id = insert_segment(
            conn, video_id, description="completely unrelated stock footage content"
        )
        insert_embedding(
            conn,
            source="segment",
            source_id=seg_id,
            video_id=video_id,
            vec=_unit_2d_with_cosine(score),
            model=MODEL,
        )
    _patch_encoder(monkeypatch, {ABSENT_QUERY: QUERY_VEC})

    r = client.get("/api/search", params={"q": ABSENT_QUERY, "mode": "hybrid"})
    assert r.status_code == 200
    body = r.json()
    assert body["results"] == []
    assert body["total"] == 0


# ---------------------------------------------------------------------------
# One strong match among low scores IS returned, and marked "semantic".
# ---------------------------------------------------------------------------


def test_one_strong_semantic_match_is_returned_and_marked_semantic(
    client, conn, monkeypatch
):
    strong_video = insert_video(conn, share="broll", rel_path="strong.mov")
    strong_seg = insert_segment(
        conn, strong_video, description="completely unrelated stock footage content"
    )
    insert_embedding(
        conn,
        source="segment",
        source_id=strong_seg,
        video_id=strong_video,
        vec=_unit_2d_with_cosine(0.75),
        model=MODEL,
    )

    for i, score in enumerate((0.30, 0.35, 0.41)):
        weak_video = insert_video(conn, share="broll", rel_path=f"weak_{i}.mov")
        weak_seg = insert_segment(
            conn, weak_video, description="also unrelated filler footage content"
        )
        insert_embedding(
            conn,
            source="segment",
            source_id=weak_seg,
            video_id=weak_video,
            vec=_unit_2d_with_cosine(score),
            model=MODEL,
        )

    _patch_encoder(monkeypatch, {ABSENT_QUERY: QUERY_VEC})

    r = client.get("/api/search", params={"q": ABSENT_QUERY, "mode": "hybrid"})
    assert r.status_code == 200
    body = r.json()
    ids = {row["video"]["id"] for row in body["results"]}
    assert ids == {strong_video}
    row = body["results"][0]
    assert row["match"] == "semantic"


# ---------------------------------------------------------------------------
# Semantic-only contribution is capped, even when far more than the cap
# scores above the floor.
# ---------------------------------------------------------------------------


def test_semantic_only_contribution_never_exceeds_the_cap(client, conn, monkeypatch):
    assert SEMANTIC_ONLY_MAX_VIDEOS == 5, (
        "this test's assertions assume the documented cap of 5 -- update the "
        "test alongside the constant if it's ever retuned"
    )
    for i in range(50):
        video_id = insert_video(conn, share="broll", rel_path=f"floor_pass_{i}.mov")
        seg_id = insert_segment(
            conn, video_id, description="unrelated generic archive footage content"
        )
        score = 0.50 + (i % 40) / 100.0  # spread of distinct scores, all >= floor
        insert_embedding(
            conn,
            source="segment",
            source_id=seg_id,
            video_id=video_id,
            vec=_unit_2d_with_cosine(min(score, 0.999)),
            model=MODEL,
        )
    _patch_encoder(monkeypatch, {ABSENT_QUERY: QUERY_VEC})

    r = client.get("/api/search", params={"q": ABSENT_QUERY, "mode": "hybrid", "limit": 100})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == SEMANTIC_ONLY_MAX_VIDEOS
    assert len(body["results"]) == SEMANTIC_ONLY_MAX_VIDEOS
    assert all(row["match"] == "semantic" for row in body["results"])


# ---------------------------------------------------------------------------
# Semantic must not reorder (or otherwise alter) confident keyword results.
# ---------------------------------------------------------------------------


def test_semantic_booster_does_not_reorder_confident_keyword_results(
    client, conn, monkeypatch
):
    v1 = insert_video(conn, share="broll", rel_path="v1.mov")
    seg1 = insert_segment(
        conn,
        v1,
        description="sailors sailors sailors gather on the pier",
        objects="sailors, pier, sailors, pier",
    )
    v2 = insert_video(conn, share="broll", rel_path="v2.mov")
    seg2 = insert_segment(
        conn, v2, description="a lone sailor walks near the pier", objects="sailor, pier"
    )

    r_before = client.get("/api/search", params={"q": "sailors pier"})
    assert r_before.status_code == 200
    body_before = r_before.json()
    order_before = [row["video"]["id"] for row in body_before["results"]]
    assert set(order_before) == {v1, v2}

    # Give both keyword-matched videos strong (above-floor) embeddings and a
    # working mocked encoder. If the booster fused semantic into keyword
    # ranking at all, this would be exactly the case that could reorder it.
    insert_embedding(
        conn, source="segment", source_id=seg1, video_id=v1,
        vec=_unit_2d_with_cosine(0.60), model=MODEL,
    )
    insert_embedding(
        conn, source="segment", source_id=seg2, video_id=v2,
        vec=_unit_2d_with_cosine(0.95), model=MODEL,
    )
    _patch_encoder(monkeypatch, {"sailors pier": QUERY_VEC})

    r_after = client.get("/api/search", params={"q": "sailors pier"})
    assert r_after.status_code == 200
    body_after = r_after.json()

    order_after = [row["video"]["id"] for row in body_after["results"]]
    assert order_after == order_before
    assert body_after == body_before, (
        "semantic being available must not change a query's output at all "
        "when every semantically-similar video was already found by keyword"
    )


# ---------------------------------------------------------------------------
# Labelling.
# ---------------------------------------------------------------------------


def test_keyword_result_is_labelled_keyword(client, conn):
    video_id = insert_video(conn, share="broll", rel_path="clip.mov")
    insert_segment(conn, video_id, description="a submarine surfaces near the coast")
    r = client.get("/api/search", params={"q": "submarine"})
    assert r.status_code == 200
    row = next(row for row in r.json()["results"] if row["video"]["id"] == video_id)
    assert row["match"] == "keyword"


def test_mode_keyword_results_are_always_labelled_keyword(client, conn, monkeypatch):
    keyword_video = insert_video(conn, share="broll", rel_path="keyword.mov")
    insert_segment(conn, keyword_video, description="a submarine surfaces near the coast")

    semantic_only_video = insert_video(conn, share="broll", rel_path="semantic.mov")
    seg_id = insert_segment(
        conn, semantic_only_video, description="totally unrelated words with no overlap"
    )
    insert_embedding(
        conn, source="segment", source_id=seg_id, video_id=semantic_only_video,
        vec=_unit_2d_with_cosine(0.90), model=MODEL,
    )
    _patch_encoder(monkeypatch, {"submarine": QUERY_VEC})

    r = client.get("/api/search", params={"q": "submarine", "mode": "keyword"})
    assert r.status_code == 200
    results = r.json()["results"]
    assert {row["video"]["id"] for row in results} == {keyword_video}
    assert all(row["match"] == "keyword" for row in results)


# ---------------------------------------------------------------------------
# mode="semantic" still applies the floor (the one place semantic is an
# explicit, uncapped user choice).
# ---------------------------------------------------------------------------


def test_mode_semantic_still_applies_the_cosine_floor(client, conn, monkeypatch):
    above_video = insert_video(conn, share="broll", rel_path="above.mov")
    above_seg = insert_segment(conn, above_video, description="a body armor vest on display")
    insert_embedding(
        conn, source="segment", source_id=above_seg, video_id=above_video,
        vec=_unit_2d_with_cosine(0.60), model=MODEL,
    )

    below_video = insert_video(conn, share="broll", rel_path="below.mov")
    below_seg = insert_segment(conn, below_video, description="an unrelated hallucinated result")
    insert_embedding(
        conn, source="segment", source_id=below_seg, video_id=below_video,
        vec=_unit_2d_with_cosine(0.35), model=MODEL,
    )

    _patch_encoder(monkeypatch, {"body armor": QUERY_VEC})

    r = client.get("/api/search", params={"q": "body armor", "mode": "semantic"})
    assert r.status_code == 200
    ids = {row["video"]["id"] for row in r.json()["results"]}
    assert ids == {above_video}
    assert SEMANTIC_COSINE_FLOOR == pytest.approx(0.50)
