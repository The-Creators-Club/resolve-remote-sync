"""broll-indexer-3 (2026-09-18b mediums): the audio-only clip's speech is the
only index it will ever have, so both halves of the transcript path must be
able to see it - the batch queue that writes the .srt (covered in
test_batch_transcribe_queue.py) and the pipeline pass that ingests it.
"""
from __future__ import annotations

from broll_index import pipeline
from broll_index.config import Config, DbConfig, SamplingConfig, ShareConfig
from broll_index.storage.sqlite_backend import SqliteBackend


def _cfg(tmp_path) -> Config:
    return Config(
        shares={"s": ShareConfig(root=str(tmp_path))},
        data_root=tmp_path / "_data",
        db=DbConfig(mode="sqlite", path=str(tmp_path / "broll.db")),
        model="haiku",
        sampling=SamplingConfig(),
    )


def _run(tmp_path, schema_path, monkeypatch, *, stages, **row):
    db = SqliteBackend(tmp_path / "b.db", schema_path=schema_path)
    vid = db.upsert_video("s", "a.mp4", **row)
    (tmp_path / "a.mp4").write_bytes(b"x")
    seen: list[int] = []
    monkeypatch.setattr(pipeline, "stage_transcribe",
                        lambda *a, **k: seen.append(a[2]["id"]))
    monkeypatch.setattr(pipeline, "stage_embed", lambda *a, **k: None)
    try:
        pipeline.run_pipeline(_cfg(tmp_path), db, model="haiku", stages=stages)
    finally:
        db.close()
    return vid, seen


def test_an_audio_only_clip_reaches_the_transcribe_stage(
    tmp_path, schema_path, monkeypatch
):
    """stage_probe parks it at 'skipped' (no video stream, a real duration).
    The transcribe stage runs ingest_only, so if run_pipeline never selects the
    row, the .srt written for it is never ingested and the clip is indexed as
    nothing at all."""
    vid, seen = _run(tmp_path, schema_path, monkeypatch, stages=["transcribe"],
                     status="skipped", duration_s=1800.0)
    assert seen == [vid]


def test_a_skipped_clip_is_not_selected_for_the_visual_stages(
    tmp_path, schema_path, monkeypatch
):
    """Widening the queue must not undo the park: 'skipped' is not a
    prerequisite status for probe, proxy, frames or claude."""
    db = SqliteBackend(tmp_path / "c.db", schema_path=schema_path)
    db.upsert_video("s", "a.mp4", status="skipped", duration_s=1800.0)
    (tmp_path / "a.mp4").write_bytes(b"x")
    called: list[str] = []
    for stage in ("stage_probe", "stage_proxy", "stage_frames", "stage_describe"):
        monkeypatch.setattr(pipeline, stage,
                            lambda *a, _s=stage, **k: called.append(_s))
    try:
        pipeline.run_pipeline(_cfg(tmp_path), db, model="haiku",
                              stages=["probe", "proxy", "frames", "claude"])
    finally:
        db.close()
    assert called == []
