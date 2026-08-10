"""sources="all"|"visual"|"transcript" on /api/search and search_videos --
restricts a search to what's SEEN (segments -- segments_fts/segments_cjk_fts
+ embeddings.source='segment') vs. what's SAID (transcript_segments --
transcript_fts/transcript_cjk_fts + embeddings.source='transcript').

The encoder is always mocked via monkeypatching
app.semantic._load_fastembed_encoder -- never download a real model here,
same pattern as test_semantic_booster.py.
"""
from __future__ import annotations

import math

import numpy as np

from app import semantic
from tests.factories import (
    insert_embedding,
    insert_segment,
    insert_transcript_segment,
    insert_video,
)

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
    `score`."""
    return [score, math.sqrt(max(0.0, 1.0 - score * score))]


QUERY_VEC = [1.0, 0.0]


def _seed_visual_only_and_transcript_only(conn):
    """video A matches only via a segment (visual index); video B matches
    only via a transcript cue (spoken-word index) -- same query term in
    both, so mode="all" finds both and the source-restricted modes each find
    exactly one."""
    video_a = insert_video(conn, share="broll", rel_path="visual_only.mov")
    seg_id = insert_segment(
        conn, video_a, description="a bioluminescent jellyfish drifts near the reef"
    )
    video_b = insert_video(conn, share="broll", rel_path="transcript_only.mov")
    tr_id = insert_transcript_segment(
        conn, video_b, text="a bioluminescent jellyfish was mentioned by the diver"
    )
    return video_a, video_b, seg_id, tr_id


# ---------------------------------------------------------------------------
# Basic filtering: all / visual / transcript.
# ---------------------------------------------------------------------------


def test_sources_all_returns_both_videos(client, conn):
    video_a, video_b, _, _ = _seed_visual_only_and_transcript_only(conn)
    r = client.get("/api/search", params={"q": "bioluminescent jellyfish"})
    assert r.status_code == 200
    body = r.json()
    ids = {row["video"]["id"] for row in body["results"]}
    assert ids == {video_a, video_b}
    assert body["total"] == 2


def test_sources_visual_returns_only_video_a(client, conn):
    video_a, video_b, _, _ = _seed_visual_only_and_transcript_only(conn)
    r = client.get(
        "/api/search", params={"q": "bioluminescent jellyfish", "sources": "visual"}
    )
    assert r.status_code == 200
    body = r.json()
    ids = {row["video"]["id"] for row in body["results"]}
    assert ids == {video_a}
    assert body["total"] == 1


def test_sources_transcript_returns_only_video_b(client, conn):
    video_a, video_b, _, _ = _seed_visual_only_and_transcript_only(conn)
    r = client.get(
        "/api/search", params={"q": "bioluminescent jellyfish", "sources": "transcript"}
    )
    assert r.status_code == 200
    body = r.json()
    ids = {row["video"]["id"] for row in body["results"]}
    assert ids == {video_b}
    assert body["total"] == 1


# ---------------------------------------------------------------------------
# Every hit under a source-restricted search must actually carry that source.
# ---------------------------------------------------------------------------


def test_sources_visual_hits_all_have_source_visual(client, conn):
    _seed_visual_only_and_transcript_only(conn)
    r = client.get(
        "/api/search", params={"q": "bioluminescent jellyfish", "sources": "visual"}
    )
    body = r.json()
    assert body["results"], "expected at least one result"
    for row in body["results"]:
        assert row["hits"], "a returned video must not have an empty hits list"
        for hit in row["hits"]:
            assert hit["source"] == "visual"


def test_sources_transcript_hits_all_have_source_transcript(client, conn):
    _seed_visual_only_and_transcript_only(conn)
    r = client.get(
        "/api/search", params={"q": "bioluminescent jellyfish", "sources": "transcript"}
    )
    body = r.json()
    assert body["results"], "expected at least one result"
    for row in body["results"]:
        assert row["hits"], "a returned video must not have an empty hits list"
        for hit in row["hits"]:
            assert hit["source"] == "transcript"


# ---------------------------------------------------------------------------
# A video whose only matching hit is filtered out must be ABSENT, not
# present with an empty hits array.
# ---------------------------------------------------------------------------


def test_video_with_only_filtered_hit_is_absent_not_empty(client, conn):
    video_a, video_b, _, _ = _seed_visual_only_and_transcript_only(conn)
    r = client.get(
        "/api/search", params={"q": "bioluminescent jellyfish", "sources": "visual"}
    )
    body = r.json()
    result_ids = [row["video"]["id"] for row in body["results"]]
    assert video_b not in result_ids
    # Doubly sure: no row in the payload at all references video_b, whether
    # with hits or not.
    assert all(row["video"]["id"] != video_b for row in body["results"])


# ---------------------------------------------------------------------------
# Composition with `mode`.
# ---------------------------------------------------------------------------


def test_sources_transcript_composes_with_mode_keyword(client, conn):
    video_a = insert_video(conn, share="broll", rel_path="a.mov")
    insert_segment(conn, video_a, description="a rare falcon soars over the canyon")
    video_b = insert_video(conn, share="broll", rel_path="b.mov")
    insert_transcript_segment(
        conn, video_b, text="a rare falcon soars over the canyon, said the guide"
    )

    r = client.get(
        "/api/search",
        params={"q": "rare falcon", "sources": "transcript", "mode": "keyword"},
    )
    assert r.status_code == 200
    ids = {row["video"]["id"] for row in r.json()["results"]}
    assert ids == {video_b}


def test_sources_visual_with_mode_semantic_only_considers_segment_embeddings(
    client, conn, monkeypatch
):
    """A transcript embedding that would otherwise score highest must NOT be
    returned when sources="visual" restricts mode="semantic" to
    embeddings.source = 'segment'."""
    seg_video = insert_video(conn, share="broll", rel_path="seg.mov")
    seg_id = insert_segment(conn, seg_video, description="unrelated visual description")
    insert_embedding(
        conn,
        source="segment",
        source_id=seg_id,
        video_id=seg_video,
        vec=_unit_2d_with_cosine(0.60),
        model=MODEL,
    )

    tr_video = insert_video(conn, share="broll", rel_path="tr.mov")
    tr_id = insert_transcript_segment(conn, tr_video, text="unrelated spoken description")
    # Deliberately the highest-scoring embedding in the DB, so a bug that
    # forgets to filter by embeddings.source would surface it anyway.
    insert_embedding(
        conn,
        source="transcript",
        source_id=tr_id,
        video_id=tr_video,
        vec=_unit_2d_with_cosine(0.95),
        model=MODEL,
    )

    query = "wholly absent footage description with no keyword overlap"
    _patch_encoder(monkeypatch, {query: QUERY_VEC})

    r = client.get(
        "/api/search", params={"q": query, "sources": "visual", "mode": "semantic"}
    )
    assert r.status_code == 200
    ids = {row["video"]["id"] for row in r.json()["results"]}
    assert ids == {seg_video}
    assert tr_video not in ids


# ---------------------------------------------------------------------------
# Invalid `sources` value falls back to "all" rather than erroring.
# ---------------------------------------------------------------------------


def test_invalid_sources_value_falls_back_to_all(client, conn):
    video_a, video_b, _, _ = _seed_visual_only_and_transcript_only(conn)
    r = client.get(
        "/api/search",
        params={"q": "bioluminescent jellyfish", "sources": "not-a-real-value"},
    )
    assert r.status_code == 200
    ids = {row["video"]["id"] for row in r.json()["results"]}
    assert ids == {video_a, video_b}
