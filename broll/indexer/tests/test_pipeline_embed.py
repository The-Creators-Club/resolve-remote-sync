from __future__ import annotations

import numpy as np
import pytest

from broll_index import embed, pipeline
from broll_index.config import Config, DbConfig, EmbeddingConfig, SamplingConfig, ShareConfig
from broll_index.transcribe import TranscriptCue


def _cfg(tmp_path, **embedding_overrides) -> Config:
    embedding = EmbeddingConfig(**embedding_overrides)
    return Config(
        shares={"broll": ShareConfig(root=str(tmp_path))},
        data_root=tmp_path / "_data",
        db=DbConfig(mode="sqlite", path=str(tmp_path / "broll.db")),
        model="sonnet",
        sampling=SamplingConfig(),
        embedding=embedding,
    )


def _fake_embed_texts(texts, model_name="m", batch_size=64):
    """Deterministic, cheap stand-in for embed.embed_texts — no model, no network.

    Encodes each text as a short vector derived from its content so equality checks
    (same text -> same vector) are meaningful without downloading anything.
    """
    dim = 8
    vectors = np.zeros((len(texts), dim), dtype=np.float32)
    for i, t in enumerate(texts):
        for j, ch in enumerate(t[:dim]):
            vectors[i, j % dim] += ord(ch)
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (vectors / norms).astype(np.float32)


@pytest.fixture(autouse=True)
def _fake_fastembed(monkeypatch):
    monkeypatch.setattr(embed, "_FASTEMBED_AVAILABLE", True)
    monkeypatch.setattr(embed, "embed_texts", _fake_embed_texts)


def _make_indexed_video(storage, tmp_path, rel="clip.mov", onscreen="厦门堵车现场"):
    (tmp_path / rel).write_bytes(b"x")
    vid = storage.upsert_video("broll", rel, status="proxied")
    storage.write_index_result(
        vid,
        themes=["traffic"],
        quality_flags=[],
        category_hint=None,
        segments=[
            {
                "t_start": 0.0, "t_end": 5.0,
                "description": "dashcam traffic", "objects": ["car"], "setting": "street",
                "motion": "static", "onscreen_text": onscreen, "onscreen_text_en": "traffic jam",
            }
        ],
        model="claude-sonnet-5",
    )
    return vid


# ---------------------------------------------------------------------------
# core behaviour
# ---------------------------------------------------------------------------

def test_stage_embed_populates_search_norm_and_embeddings(tmp_path, sqlite_storage_v4):
    vid = _make_indexed_video(sqlite_storage_v4, tmp_path)
    cfg = _cfg(tmp_path, model="fake-model")
    video = sqlite_storage_v4.get_video(vid)

    pipeline.stage_embed(cfg, sqlite_storage_v4, video)

    seg = sqlite_storage_v4.get_segments(vid)[0]
    assert seg["search_norm"] != ""
    assert "堵車" in seg["search_norm"].split()  # traditional variant reachable

    models = sqlite_storage_v4.get_embedding_models(vid)
    assert models == {("segment", seg["id"]): "fake-model"}

    row = sqlite_storage_v4.conn.execute(
        "SELECT dim, vec FROM embeddings WHERE source = 'segment' AND source_id = ?", (seg["id"],)
    ).fetchone()
    assert row["dim"] == 8
    vec = embed.from_blob(row["vec"], dim=8)
    assert vec.shape == (8,)


def test_stage_embed_covers_transcript_segments_too(tmp_path, sqlite_storage_v4):
    (tmp_path / "clip.mov").write_bytes(b"x")
    vid = sqlite_storage_v4.upsert_video("broll", "clip.mov", status="proxied")
    sqlite_storage_v4.write_transcript(vid, [TranscriptCue(0.0, 2.0, "厦门堵车情况严重")], "zh")
    cfg = _cfg(tmp_path, model="fake-model")
    video = sqlite_storage_v4.get_video(vid)

    pipeline.stage_embed(cfg, sqlite_storage_v4, video)

    cue = sqlite_storage_v4.get_transcript_segments(vid)[0]
    assert cue["search_norm"] != ""
    assert sqlite_storage_v4.get_embedding_models(vid) == {("transcript", cue["id"]): "fake-model"}


def test_stage_embed_never_touches_video_status(tmp_path, sqlite_storage_v4):
    vid = _make_indexed_video(sqlite_storage_v4, tmp_path)
    cfg = _cfg(tmp_path)
    video = sqlite_storage_v4.get_video(vid)

    pipeline.stage_embed(cfg, sqlite_storage_v4, video)

    assert sqlite_storage_v4.get_video(vid)["status"] == "indexed"


# ---------------------------------------------------------------------------
# idempotency + model-change re-embed
# ---------------------------------------------------------------------------

def test_stage_embed_is_idempotent_second_run_does_no_work(tmp_path, sqlite_storage_v4, monkeypatch):
    vid = _make_indexed_video(sqlite_storage_v4, tmp_path)
    cfg = _cfg(tmp_path, model="fake-model")
    video = sqlite_storage_v4.get_video(vid)

    pipeline.stage_embed(cfg, sqlite_storage_v4, video)

    calls = []
    original = embed.embed_texts

    def spy(texts, *a, **k):
        calls.append(list(texts))
        return original(texts, *a, **k)

    monkeypatch.setattr(embed, "embed_texts", spy)

    video2 = sqlite_storage_v4.get_video(vid)
    pipeline.stage_embed(cfg, sqlite_storage_v4, video2)

    assert calls == []  # nothing needed embedding the second time


def test_stage_embed_model_change_triggers_re_embed(tmp_path, sqlite_storage_v4):
    vid = _make_indexed_video(sqlite_storage_v4, tmp_path)
    cfg_a = _cfg(tmp_path, model="model-a")
    video = sqlite_storage_v4.get_video(vid)
    pipeline.stage_embed(cfg_a, sqlite_storage_v4, video)

    seg_id = sqlite_storage_v4.get_segments(vid)[0]["id"]
    assert sqlite_storage_v4.get_embedding_models(vid) == {("segment", seg_id): "model-a"}

    cfg_b = _cfg(tmp_path, model="model-b")
    video2 = sqlite_storage_v4.get_video(vid)
    pipeline.stage_embed(cfg_b, sqlite_storage_v4, video2)

    assert sqlite_storage_v4.get_embedding_models(vid) == {("segment", seg_id): "model-b"}
    # still exactly one embeddings row for this segment (replaced, not duplicated)
    count = sqlite_storage_v4.conn.execute(
        "SELECT COUNT(*) FROM embeddings WHERE source = 'segment' AND source_id = ?", (seg_id,)
    ).fetchone()[0]
    assert count == 1


def test_stage_embed_does_not_recompute_existing_search_norm(tmp_path, sqlite_storage_v4):
    vid = _make_indexed_video(sqlite_storage_v4, tmp_path)
    seg_id = sqlite_storage_v4.get_segments(vid)[0]["id"]
    sqlite_storage_v4.update_search_norm("segment", seg_id, "hand-written-norm")

    cfg = _cfg(tmp_path, model="fake-model")
    video = sqlite_storage_v4.get_video(vid)
    pipeline.stage_embed(cfg, sqlite_storage_v4, video)

    assert sqlite_storage_v4.get_segments(vid)[0]["search_norm"] == "hand-written-norm"


# ---------------------------------------------------------------------------
# failure handling — additive enrichment only, must never error the video
# ---------------------------------------------------------------------------

def test_stage_embed_swallows_storage_failure(tmp_path, sqlite_storage_v4, monkeypatch):
    vid = _make_indexed_video(sqlite_storage_v4, tmp_path)
    cfg = _cfg(tmp_path)
    video = sqlite_storage_v4.get_video(vid)

    def failing_get_segments(video_id):
        raise RuntimeError("db exploded")

    monkeypatch.setattr(sqlite_storage_v4, "get_segments", failing_get_segments)

    pipeline.stage_embed(cfg, sqlite_storage_v4, video)  # must not raise

    row = sqlite_storage_v4.get_video(vid)
    assert row["status"] == "indexed"  # untouched
    assert row["error"] is None


def test_stage_embed_skips_embedding_when_fastembed_unavailable_but_still_normalizes(
    tmp_path, sqlite_storage_v4, monkeypatch
):
    monkeypatch.setattr(embed, "_FASTEMBED_AVAILABLE", False)
    vid = _make_indexed_video(sqlite_storage_v4, tmp_path)
    cfg = _cfg(tmp_path)
    video = sqlite_storage_v4.get_video(vid)

    pipeline.stage_embed(cfg, sqlite_storage_v4, video)

    seg = sqlite_storage_v4.get_segments(vid)[0]
    assert seg["search_norm"] != ""  # normalization still happened
    assert sqlite_storage_v4.get_embedding_models(vid) == {}  # but no embedding written


def test_stage_embed_skips_when_disabled(tmp_path, sqlite_storage_v4):
    vid = _make_indexed_video(sqlite_storage_v4, tmp_path)
    cfg = _cfg(tmp_path, enabled=False)
    video = sqlite_storage_v4.get_video(vid)

    pipeline.stage_embed(cfg, sqlite_storage_v4, video)

    seg = sqlite_storage_v4.get_segments(vid)[0]
    assert seg["search_norm"] == ""
    assert sqlite_storage_v4.get_embedding_models(vid) == {}


# ---------------------------------------------------------------------------
# _process_video / run_pipeline wiring
# ---------------------------------------------------------------------------

def test_process_video_runs_embed_after_claude(tmp_path, sqlite_storage_v4, monkeypatch):
    calls = []

    def fake_claude(cfg, storage, video, model, invoke=None):
        calls.append("claude")
        storage.write_index_result(
            video["id"], themes=[], quality_flags=[], category_hint=None,
            segments=[{"t_start": 0.0, "t_end": 1.0, "description": "d", "objects": [], "setting": "", "motion": ""}],
            model=model,
        )

    def fake_embed(cfg, storage, video):
        calls.append("embed")

    monkeypatch.setattr(pipeline, "stage_probe", lambda cfg, storage, video, src_path: (
        calls.append("probe"), storage.update_video(video["id"], status="probed", duration_s=2.0, fps=25.0, width=320, height=240)
    ))
    monkeypatch.setattr(pipeline, "stage_proxy", lambda cfg, storage, video, src_path: (
        calls.append("proxy"), storage.update_video(video["id"], status="proxied")
    ))
    monkeypatch.setattr(pipeline, "stage_frames", lambda cfg, storage, video, src_path: calls.append("frames"))
    monkeypatch.setattr(pipeline, "stage_transcribe", lambda cfg, storage, video, src_path: calls.append("transcribe"))
    monkeypatch.setattr(pipeline, "stage_claude", fake_claude)
    monkeypatch.setattr(pipeline, "stage_embed", fake_embed)

    (tmp_path / "clip.mov").write_bytes(b"x")
    vid = sqlite_storage_v4.upsert_video("broll", "clip.mov", status="discovered")
    cfg = _cfg(tmp_path)
    video = sqlite_storage_v4.get_video(vid)

    pipeline._process_video(cfg, sqlite_storage_v4, video, model="sonnet", requested_stages=set(pipeline.DEFAULT_STAGES))

    assert calls == ["probe", "proxy", "frames", "transcribe", "claude", "embed"]


def test_process_video_embed_failure_does_not_error_video(tmp_path, sqlite_storage_v4, monkeypatch):
    def failing_embed(cfg, storage, video):
        raise RuntimeError("embed blew up")

    monkeypatch.setattr(pipeline, "stage_embed", failing_embed)

    vid = _make_indexed_video(sqlite_storage_v4, tmp_path)
    cfg = _cfg(tmp_path)
    video = sqlite_storage_v4.get_video(vid)

    pipeline._process_video(cfg, sqlite_storage_v4, video, model="sonnet", requested_stages={"embed"})

    row = sqlite_storage_v4.get_video(vid)
    assert row["status"] == "indexed"  # untouched, not 'error'
    assert row["error"] is None


def test_process_video_embed_unaffected_by_unknown_share(tmp_path, sqlite_storage_v4, monkeypatch):
    # embed doesn't need src_path/share config at all — an unrelated unknown-share
    # video must still be eligible for status-independent enrichment.
    calls = []
    monkeypatch.setattr(pipeline, "stage_embed", lambda cfg, storage, video: calls.append("embed"))

    vid = sqlite_storage_v4.upsert_video("nonexistent_share", "clip.mov", status="indexed")
    cfg = _cfg(tmp_path)  # only knows about "broll"
    video = sqlite_storage_v4.get_video(vid)

    pipeline._process_video(cfg, sqlite_storage_v4, video, model="sonnet", requested_stages={"embed"})

    assert calls == ["embed"]
    assert sqlite_storage_v4.get_video(vid)["status"] == "indexed"  # not 'error'


def test_run_pipeline_widens_status_for_embed_stage(tmp_path, sqlite_storage_v4, monkeypatch):
    calls = []
    monkeypatch.setattr(pipeline, "stage_embed", lambda cfg, storage, video: calls.append(video["id"]))

    (tmp_path / "clip.mov").write_bytes(b"x")
    vid = sqlite_storage_v4.upsert_video("broll", "clip.mov", status="indexed")
    cfg = _cfg(tmp_path)

    count = pipeline.run_pipeline(cfg, sqlite_storage_v4, model="sonnet", stages=["embed"])

    assert count == 1
    assert calls == [vid]
