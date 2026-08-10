from __future__ import annotations

import pytest

from broll_index.transcribe import TranscriptCue


def test_get_segments_includes_id_and_search_norm(sqlite_storage_v4):
    vid = sqlite_storage_v4.upsert_video("broll", "clip.mov", status="proxied")
    sqlite_storage_v4.write_index_result(
        vid, themes=[], quality_flags=[], category_hint=None,
        segments=[{"t_start": 0.0, "t_end": 1.0, "description": "d", "objects": [], "setting": "", "motion": ""}],
        model="m",
    )
    segs = sqlite_storage_v4.get_segments(vid)
    assert len(segs) == 1
    assert segs[0]["description"] == "d"
    assert segs[0]["search_norm"] == ""
    assert "id" in segs[0]


def test_get_transcript_segments_includes_id_and_search_norm(sqlite_storage_v4):
    vid = sqlite_storage_v4.upsert_video("broll", "clip.mov", status="proxied")
    sqlite_storage_v4.write_transcript(vid, [TranscriptCue(0.0, 1.0, "hello")], "en")
    rows = sqlite_storage_v4.get_transcript_segments(vid)
    assert len(rows) == 1
    assert rows[0]["text"] == "hello"
    assert rows[0]["search_norm"] == ""
    assert "id" in rows[0]


def test_update_search_norm_segment(sqlite_storage_v4):
    vid = sqlite_storage_v4.upsert_video("broll", "clip.mov", status="proxied")
    sqlite_storage_v4.write_index_result(
        vid, themes=[], quality_flags=[], category_hint=None,
        segments=[{"t_start": 0.0, "t_end": 1.0, "description": "d", "objects": [], "setting": "", "motion": ""}],
        model="m",
    )
    seg_id = sqlite_storage_v4.get_segments(vid)[0]["id"]
    sqlite_storage_v4.update_search_norm("segment", seg_id, "d normalized")
    assert sqlite_storage_v4.get_segments(vid)[0]["search_norm"] == "d normalized"


def test_update_search_norm_transcript(sqlite_storage_v4):
    vid = sqlite_storage_v4.upsert_video("broll", "clip.mov", status="proxied")
    sqlite_storage_v4.write_transcript(vid, [TranscriptCue(0.0, 1.0, "hello")], "en")
    cue_id = sqlite_storage_v4.get_transcript_segments(vid)[0]["id"]
    sqlite_storage_v4.update_search_norm("transcript", cue_id, "hello normalized")
    assert sqlite_storage_v4.get_transcript_segments(vid)[0]["search_norm"] == "hello normalized"


def test_update_search_norm_unknown_source_raises(sqlite_storage_v4):
    with pytest.raises(ValueError, match="unknown search_norm source"):
        sqlite_storage_v4.update_search_norm("bogus", 1, "x")


def test_upsert_embedding_insert_and_replace(sqlite_storage_v4):
    vid = sqlite_storage_v4.upsert_video("broll", "clip.mov", status="proxied")
    sqlite_storage_v4.upsert_embedding("segment", 1, vid, "model-a", 3, b"\x00\x01\x02")
    models = sqlite_storage_v4.get_embedding_models(vid)
    assert models == {("segment", 1): "model-a"}

    row = sqlite_storage_v4.conn.execute(
        "SELECT model, dim, vec FROM embeddings WHERE source = 'segment' AND source_id = 1"
    ).fetchone()
    assert row["model"] == "model-a"
    assert row["dim"] == 3
    assert row["vec"] == b"\x00\x01\x02"

    # Replace with a new model (simulating a model change / re-embed).
    sqlite_storage_v4.upsert_embedding("segment", 1, vid, "model-b", 4, b"\x03\x04\x05\x06")
    models_after = sqlite_storage_v4.get_embedding_models(vid)
    assert models_after == {("segment", 1): "model-b"}

    count = sqlite_storage_v4.conn.execute(
        "SELECT COUNT(*) FROM embeddings WHERE source = 'segment' AND source_id = 1"
    ).fetchone()[0]
    assert count == 1  # replaced, not duplicated


def test_get_embedding_models_scoped_to_video(sqlite_storage_v4):
    vid1 = sqlite_storage_v4.upsert_video("broll", "a.mov", status="proxied")
    vid2 = sqlite_storage_v4.upsert_video("broll", "b.mov", status="proxied")
    sqlite_storage_v4.upsert_embedding("segment", 1, vid1, "m", 3, b"\x00\x00\x00")
    sqlite_storage_v4.upsert_embedding("segment", 2, vid2, "m", 3, b"\x00\x00\x00")

    assert sqlite_storage_v4.get_embedding_models(vid1) == {("segment", 1): "m"}
    assert sqlite_storage_v4.get_embedding_models(vid2) == {("segment", 2): "m"}
