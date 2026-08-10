"""Integration tests for hybrid/keyword/semantic mode dispatch, transcript
hits, fuzzy end-to-end behaviour, and /api/videos/{id} transcript cues.
Exercised through the real /api/search + /api/videos endpoints (client
fixture), same as the pre-existing v2 search tests.
"""
from __future__ import annotations

import numpy as np
import pytest

from app import semantic
from tests.factories import (
    insert_embedding,
    insert_segment,
    insert_transcript_segment,
    insert_video,
)

MODEL = semantic.DEFAULT_MODEL


def _unit(vec: list[float]) -> list[float]:
    arr = np.array(vec, dtype=np.float32)
    norm = float(np.linalg.norm(arr))
    return (arr / norm).tolist() if norm else arr.tolist()


class FakeEncoder:
    def __init__(self, vectors: dict[str, list[float]]):
        self._vectors = vectors

    def embed(self, docs):
        for d in docs:
            vec = self._vectors.get(d, [0.0] * 4)
            yield np.array(vec, dtype=np.float32)


def _patch_encoder(monkeypatch, vectors: dict[str, list[float]]) -> None:
    monkeypatch.setattr(
        semantic, "_load_fastembed_encoder", lambda name: FakeEncoder(vectors)
    )


# ---------------------------------------------------------------------------
# Transcript hits: source="transcript", correct timestamps, distinct from
# "visual" (segment) hits.
# ---------------------------------------------------------------------------


def test_transcript_hit_has_transcript_source_and_own_timestamps(client, conn):
    video_id = insert_video(conn, share="broll", rel_path="news/raid.mov")
    insert_segment(
        conn,
        video_id,
        t_start=0.0,
        t_end=10.0,
        description="Officers gather outside a building",
        objects="officers, building, courtyard",
    )
    insert_transcript_segment(
        conn,
        video_id,
        t_start=42.0,
        t_end=47.5,
        text="the suspect named Chang was arrested this morning",
    )

    r = client.get("/api/search", params={"q": "Chang", "mode": "keyword"})
    assert r.status_code == 200
    body = r.json()
    row = next(row for row in body["results"] if row["video"]["id"] == video_id)
    hit = next(h for h in row["hits"] if h["source"] == "transcript")
    assert hit["t_start"] == 42.0
    assert hit["t_end"] == 47.5
    assert hit["transcript_id"] is not None
    assert hit["segment_id"] is None


def test_visual_hit_is_marked_source_visual(client, conn):
    video_id = insert_video(conn, share="broll", rel_path="clip.mov")
    insert_segment(
        conn, video_id, description="A grey frigate moored at the pier", objects="frigate, pier"
    )
    r = client.get("/api/search", params={"q": "frigate"})
    body = r.json()
    row = next(row for row in body["results"] if row["video"]["id"] == video_id)
    hit = row["hits"][0]
    assert hit["source"] == "visual"
    assert hit["segment_id"] is not None
    assert hit["transcript_id"] is None


# ---------------------------------------------------------------------------
# /api/videos/{id} includes transcript cues alongside segments.
# ---------------------------------------------------------------------------


def test_video_detail_includes_transcript_cues(client, conn):
    video_id = insert_video(conn, share="broll", rel_path="clip.mov")
    insert_segment(conn, video_id, description="A police briefing")
    insert_transcript_segment(conn, video_id, t_start=1.0, t_end=3.0, text="hello there")

    r = client.get(f"/api/videos/{video_id}")
    assert r.status_code == 200
    body = r.json()
    assert "transcript" in body
    assert len(body["transcript"]) == 1
    assert body["transcript"][0]["text"] == "hello there"
    assert body["transcript"][0]["t_start"] == 1.0


def test_video_detail_transcript_empty_list_when_none(client, conn):
    video_id = insert_video(conn, share="broll", rel_path="clip.mov")
    insert_segment(conn, video_id, description="A police briefing")
    r = client.get(f"/api/videos/{video_id}")
    assert r.json()["transcript"] == []


# ---------------------------------------------------------------------------
# mode dispatch
# ---------------------------------------------------------------------------


def test_mode_keyword_excludes_semantic_only_hits(client, conn, monkeypatch):
    keyword_video = insert_video(conn, share="broll", rel_path="keyword.mov")
    insert_segment(conn, keyword_video, description="a submarine surfaces near the coast")

    semantic_only_video = insert_video(conn, share="broll", rel_path="semantic.mov")
    seg_id = insert_segment(
        conn, semantic_only_video, description="totally unrelated words with no overlap"
    )
    insert_embedding(
        conn, source="segment", source_id=seg_id, video_id=semantic_only_video,
        vec=_unit([1, 0, 0, 0]), model=MODEL,
    )
    _patch_encoder(monkeypatch, {"submarine": _unit([1, 0, 0, 0])})

    r = client.get("/api/search", params={"q": "submarine", "mode": "keyword"})
    ids = {row["video"]["id"] for row in r.json()["results"]}
    assert keyword_video in ids
    assert semantic_only_video not in ids


def test_mode_semantic_works_with_keyword_sources_disabled(client, conn, monkeypatch):
    keyword_video = insert_video(conn, share="broll", rel_path="keyword.mov")
    insert_segment(conn, keyword_video, description="a submarine surfaces near the coast")

    semantic_video = insert_video(conn, share="broll", rel_path="semantic.mov")
    seg_id = insert_segment(
        conn, semantic_video, description="totally unrelated words with no overlap"
    )
    insert_embedding(
        conn, source="segment", source_id=seg_id, video_id=semantic_video,
        vec=_unit([1, 0, 0, 0]), model=MODEL,
    )
    _patch_encoder(monkeypatch, {"submarine": _unit([1, 0, 0, 0])})

    r = client.get("/api/search", params={"q": "submarine", "mode": "semantic"})
    assert r.status_code == 200
    ids = {row["video"]["id"] for row in r.json()["results"]}
    assert semantic_video in ids
    assert keyword_video not in ids


def test_hybrid_mode_fuses_both(client, conn, monkeypatch):
    keyword_video = insert_video(conn, share="broll", rel_path="keyword.mov")
    insert_segment(conn, keyword_video, description="a submarine surfaces near the coast")

    semantic_video = insert_video(conn, share="broll", rel_path="semantic.mov")
    seg_id = insert_segment(
        conn, semantic_video, description="totally unrelated words with no overlap"
    )
    insert_embedding(
        conn, source="segment", source_id=seg_id, video_id=semantic_video,
        vec=_unit([1, 0, 0, 0]), model=MODEL,
    )
    _patch_encoder(monkeypatch, {"submarine": _unit([1, 0, 0, 0])})

    r = client.get("/api/search", params={"q": "submarine", "mode": "hybrid"})
    ids = {row["video"]["id"] for row in r.json()["results"]}
    assert {keyword_video, semantic_video} <= ids


def test_invalid_mode_falls_back_to_hybrid(client, conn):
    video_id = insert_video(conn, share="broll", rel_path="clip.mov")
    insert_segment(conn, video_id, description="a submarine surfaces near the coast")
    r = client.get("/api/search", params={"q": "submarine", "mode": "bogus"})
    assert r.status_code == 200
    ids = {row["video"]["id"] for row in r.json()["results"]}
    assert video_id in ids


# ---------------------------------------------------------------------------
# Semantic degrades cleanly.
# ---------------------------------------------------------------------------


def test_no_embeddings_still_returns_200_keyword_only(client, conn):
    video_id = insert_video(conn, share="broll", rel_path="clip.mov")
    insert_segment(conn, video_id, description="a submarine surfaces near the coast")
    r = client.get("/api/search", params={"q": "submarine"})
    assert r.status_code == 200
    ids = {row["video"]["id"] for row in r.json()["results"]}
    assert video_id in ids


def test_embedding_model_mismatch_does_not_crash_search(client, conn, monkeypatch):
    video_id = insert_video(conn, share="broll", rel_path="clip.mov")
    seg_id = insert_segment(conn, video_id, description="a submarine surfaces near the coast")
    insert_embedding(
        conn, source="segment", source_id=seg_id, video_id=video_id,
        vec=_unit([1, 0, 0, 0]), model="some-legacy-model",
    )
    _patch_encoder(monkeypatch, {"submarine": _unit([1, 0, 0, 0])})

    r = client.get("/api/search", params={"q": "submarine"})
    assert r.status_code == 200
    ids = {row["video"]["id"] for row in r.json()["results"]}
    # Keyword match still finds it; semantic path silently contributed
    # nothing rather than comparing across model spaces or crashing.
    assert video_id in ids


# ---------------------------------------------------------------------------
# Fuzzy matching.
# ---------------------------------------------------------------------------


def test_misspelled_query_finds_the_clip_via_fuzzy(client, conn):
    video_id = insert_video(conn, share="broll", rel_path="ambulance.mov")
    insert_segment(
        conn,
        video_id,
        description="An ambulance rushes past a crowd",
        objects="ambulance, emergency vehicle, siren",
    )
    r = client.get("/api/search", params={"q": "ambluance"})
    assert r.status_code == 200
    ids = {row["video"]["id"] for row in r.json()["results"]}
    assert video_id in ids


def test_fuzzy_false_disables_typo_correction_for_a_query_with_no_exact_hits(client, conn):
    video_id = insert_video(conn, share="broll", rel_path="ambulance.mov")
    insert_segment(
        conn,
        video_id,
        description="An ambulance rushes past a crowd",
        objects="ambulance, emergency vehicle, siren",
    )
    r = client.get("/api/search", params={"q": "ambluance", "fuzzy": False})
    assert r.status_code == 200
    ids = {row["video"]["id"] for row in r.json()["results"]}
    assert video_id not in ids


def test_fuzzy_does_not_alter_a_query_with_plenty_of_results(client, conn):
    for i in range(6):
        v = insert_video(conn, share="broll", rel_path=f"pagetest/clip_{i}.mov")
        insert_segment(conn, v, description="generic stock footage of a harbor exercise drill")

    r_on = client.get("/api/search", params={"q": "harbor", "fuzzy": True, "limit": 100})
    r_off = client.get("/api/search", params={"q": "harbor", "fuzzy": False, "limit": 100})
    assert r_on.status_code == 200 and r_off.status_code == 200
    assert r_on.json() == r_off.json()
