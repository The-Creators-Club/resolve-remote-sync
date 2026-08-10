"""app.semantic: brute-force cosine search over the embeddings table.

The encoder is always mocked here via monkeypatching
app.semantic._load_fastembed_encoder -- these tests must never download a
real model.
"""
from __future__ import annotations

import numpy as np
import pytest

from app import semantic
from tests.factories import insert_embedding, insert_video

DIM = 4


class FakeEncoder:
    """Returns a preset vector per exact query string; unknown queries get
    an all-zero vector (cosine similarity 0 against anything)."""

    def __init__(self, vectors: dict[str, list[float]]):
        self._vectors = vectors

    def embed(self, docs):
        for d in docs:
            vec = self._vectors.get(d, [0.0] * DIM)
            yield np.array(vec, dtype=np.float32)


def _unit(vec: list[float]) -> list[float]:
    arr = np.array(vec, dtype=np.float32)
    norm = float(np.linalg.norm(arr))
    return (arr / norm).tolist() if norm else arr.tolist()


def test_no_embeddings_means_unavailable_and_empty_search(conn):
    s = semantic.SemanticSearch(model="test-model")
    assert s.available(conn) is False
    assert s.search(conn, "anything") == []


def test_model_mismatch_is_skipped_not_compared(conn, monkeypatch):
    """Embeddings exist, but under a different model than this instance is
    configured for -- must be treated the same as "no embeddings", never
    compared as if the vector spaces matched."""
    v = insert_video(conn, share="broll", rel_path="a.mov")
    insert_embedding(
        conn, source="segment", source_id=1, video_id=v, vec=_unit([1, 0, 0, 0]),
        model="some-other-model",
    )

    s = semantic.SemanticSearch(model="test-model")
    monkeypatch.setattr(
        semantic, "_load_fastembed_encoder", lambda name: FakeEncoder({"query": _unit([1, 0, 0, 0])})
    )
    assert s.available(conn) is False
    assert s.search(conn, "query") == []


def test_fastembed_unavailable_degrades_to_empty(conn, monkeypatch):
    v = insert_video(conn, share="broll", rel_path="a.mov")
    insert_embedding(
        conn, source="segment", source_id=1, video_id=v, vec=_unit([1, 0, 0, 0]),
        model="test-model",
    )
    s = semantic.SemanticSearch(model="test-model")
    monkeypatch.setattr(semantic, "_load_fastembed_encoder", lambda name: None)
    assert s.search(conn, "query") == []


def test_top_match_is_the_closest_vector(conn, monkeypatch):
    v1 = insert_video(conn, share="broll", rel_path="ambulance.mov")
    v2 = insert_video(conn, share="broll", rel_path="ocean.mov")
    insert_embedding(
        conn, source="segment", source_id=1, video_id=v1, vec=_unit([1, 0, 0, 0]),
        model="test-model",
    )
    insert_embedding(
        conn, source="segment", source_id=2, video_id=v2, vec=_unit([0, 1, 0, 0]),
        model="test-model",
    )

    s = semantic.SemanticSearch(model="test-model")
    monkeypatch.setattr(
        semantic,
        "_load_fastembed_encoder",
        lambda name: FakeEncoder({"emergency vehicle": _unit([0.9, 0.1, 0, 0])}),
    )

    hits = s.search(conn, "emergency vehicle")
    assert hits[0]["source"] == "segment"
    assert hits[0]["source_id"] == 1
    assert hits[0]["video_id"] == v1
    assert hits[0]["score"] > hits[1]["score"]


def test_allowed_video_ids_filters_before_top_k(conn, monkeypatch):
    v1 = insert_video(conn, share="broll", rel_path="a.mov")
    v2 = insert_video(conn, share="broll", rel_path="b.mov")
    insert_embedding(
        conn, source="segment", source_id=1, video_id=v1, vec=_unit([1, 0, 0, 0]),
        model="test-model",
    )
    insert_embedding(
        conn, source="segment", source_id=2, video_id=v2, vec=_unit([0.99, 0.01, 0, 0]),
        model="test-model",
    )

    s = semantic.SemanticSearch(model="test-model")
    monkeypatch.setattr(
        semantic, "_load_fastembed_encoder", lambda name: FakeEncoder({"q": _unit([1, 0, 0, 0])})
    )

    # v1 is the closer match, but restrict the pool to v2 only.
    hits = s.search(conn, "q", allowed_video_ids={v2})
    assert [h["video_id"] for h in hits] == [v2]


def test_reload_triggered_by_row_count_change_not_per_request(conn, monkeypatch):
    v = insert_video(conn, share="broll", rel_path="a.mov")
    insert_embedding(
        conn, source="segment", source_id=1, video_id=v, vec=_unit([1, 0, 0, 0]),
        model="test-model",
    )
    s = semantic.SemanticSearch(model="test-model")
    monkeypatch.setattr(
        semantic, "_load_fastembed_encoder", lambda name: FakeEncoder({"q": _unit([1, 0, 0, 0])})
    )
    first = s.search(conn, "q")
    assert len(first) == 1

    v2 = insert_video(conn, share="broll", rel_path="b.mov")
    insert_embedding(
        conn, source="segment", source_id=2, video_id=v2, vec=_unit([0, 1, 0, 0]),
        model="test-model",
    )
    second = s.search(conn, "q")
    assert len(second) == 2  # cache correctly reloaded, not stuck at 1 row


def test_empty_query_is_safe(conn):
    s = semantic.SemanticSearch(model="test-model")
    assert s.search(conn, "") == []
    assert s.search(conn, "   ") == []
