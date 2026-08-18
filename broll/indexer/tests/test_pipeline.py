from __future__ import annotations

from pathlib import Path

import pytest

from broll_index import pipeline
from broll_index.config import Config, DbConfig, SamplingConfig, ShareConfig


def _cfg(tmp_path) -> Config:
    return Config(
        shares={"broll": ShareConfig(root=str(tmp_path))},
        data_root=tmp_path / "_data",
        db=DbConfig(mode="sqlite", path=str(tmp_path / "broll.db")),
        model="sonnet",
        sampling=SamplingConfig(),
    )


def test_process_video_runs_stages_in_order_and_advances_status(tmp_path, sqlite_storage, monkeypatch):
    calls = []

    def fake_probe(cfg, storage, video, src_path):
        calls.append("probe")
        storage.update_video(video["id"], status="probed", duration_s=2.0, fps=25.0, width=320, height=240)

    def fake_proxy(cfg, storage, video, src_path):
        calls.append("proxy")
        storage.update_video(video["id"], status="proxied")

    def fake_frames(cfg, storage, video, src_path):
        calls.append("frames")

    def fake_claude(cfg, storage, video, model, invoke=None):
        calls.append("claude")
        storage.write_index_result(
            video["id"], themes=[], quality_flags=[], category_hint=None, segments=[], model=model
        )

    def fake_transcribe(cfg, storage, video, src_path, ingest_only=False):
        # Never let a real subprocess boundary get exercised here — see
        # test_pipeline_transcribe.py for dedicated stage_transcribe coverage.
        calls.append("transcribe")

    monkeypatch.setattr(pipeline, "stage_probe", fake_probe)
    monkeypatch.setattr(pipeline, "stage_proxy", fake_proxy)
    monkeypatch.setattr(pipeline, "stage_frames", fake_frames)
    monkeypatch.setattr(pipeline, "stage_describe", fake_claude)
    monkeypatch.setattr(pipeline, "stage_transcribe", fake_transcribe)

    (tmp_path / "clip.mov").write_bytes(b"x")
    vid = sqlite_storage.upsert_video("broll", "clip.mov", status="discovered")
    cfg = _cfg(tmp_path)

    video = sqlite_storage.get_video(vid)
    pipeline._process_video(cfg, sqlite_storage, video, model="sonnet", requested_stages=set(pipeline.DEFAULT_STAGES))

    assert calls == ["probe", "proxy", "frames", "transcribe", "claude"]
    assert sqlite_storage.get_video(vid)["status"] == "indexed"


def test_process_video_resumes_from_current_status(tmp_path, sqlite_storage, monkeypatch):
    calls = []
    monkeypatch.setattr(pipeline, "stage_probe", lambda *a, **k: calls.append("probe"))
    monkeypatch.setattr(pipeline, "stage_proxy", lambda *a, **k: (calls.append("proxy"), a[1].update_video(a[2]["id"], status="proxied")))
    monkeypatch.setattr(pipeline, "stage_frames", lambda *a, **k: calls.append("frames"))
    monkeypatch.setattr(pipeline, "stage_describe", lambda *a, **k: calls.append("claude"))
    monkeypatch.setattr(pipeline, "stage_transcribe", lambda *a, **k: calls.append("transcribe"))

    (tmp_path / "clip.mov").write_bytes(b"x")
    vid = sqlite_storage.upsert_video("broll", "clip.mov", status="probed")
    cfg = _cfg(tmp_path)
    video = sqlite_storage.get_video(vid)

    pipeline._process_video(cfg, sqlite_storage, video, model="sonnet", requested_stages=set(pipeline.DEFAULT_STAGES))

    assert "probe" not in calls  # already past discovered, must not re-probe
    assert calls == ["proxy", "frames", "transcribe", "claude"]


def test_process_video_stages_filter_restricts_execution(tmp_path, sqlite_storage, monkeypatch):
    calls = []
    monkeypatch.setattr(pipeline, "stage_probe", lambda *a, **k: calls.append("probe"))
    monkeypatch.setattr(pipeline, "stage_proxy", lambda *a, **k: calls.append("proxy"))
    monkeypatch.setattr(pipeline, "stage_frames", lambda *a, **k: calls.append("frames"))
    monkeypatch.setattr(pipeline, "stage_describe", lambda *a, **k: calls.append("claude"))

    (tmp_path / "clip.mov").write_bytes(b"x")
    vid = sqlite_storage.upsert_video("broll", "clip.mov", status="discovered")
    cfg = _cfg(tmp_path)
    video = sqlite_storage.get_video(vid)

    pipeline._process_video(cfg, sqlite_storage, video, model="sonnet", requested_stages={"probe"})

    assert calls == ["probe"]  # proxy/frames/claude filtered out even though status wasn't advanced


def test_process_video_stage_failure_sets_error_and_stops(tmp_path, sqlite_storage, monkeypatch):
    def failing_probe(cfg, storage, video, src_path):
        raise RuntimeError("ffprobe exploded")

    monkeypatch.setattr(pipeline, "stage_probe", failing_probe)

    (tmp_path / "clip.mov").write_bytes(b"x")
    vid = sqlite_storage.upsert_video("broll", "clip.mov", status="discovered")
    cfg = _cfg(tmp_path)
    video = sqlite_storage.get_video(vid)

    pipeline._process_video(cfg, sqlite_storage, video, model="sonnet", requested_stages=set(pipeline.DEFAULT_STAGES))

    row = sqlite_storage.get_video(vid)
    assert row["status"] == "error"
    assert "ffprobe exploded" in row["error"]


def test_process_video_unknown_share_sets_error(tmp_path, sqlite_storage):
    vid = sqlite_storage.upsert_video("nonexistent_share", "clip.mov", status="discovered")
    cfg = _cfg(tmp_path)  # only knows about "broll"
    video = sqlite_storage.get_video(vid)

    pipeline._process_video(cfg, sqlite_storage, video, model="sonnet", requested_stages=set(pipeline.DEFAULT_STAGES))

    row = sqlite_storage.get_video(vid)
    assert row["status"] == "error"
    assert "unknown share" in row["error"]


def test_run_pipeline_skips_duplicate_of_rows_never_invokes_claude(tmp_path, sqlite_storage, monkeypatch):
    """A video already marked duplicate_of must never reach any stage — above all never
    spend a Claude call describing footage already described under its canonical row."""
    processed_ids = []
    monkeypatch.setattr(
        pipeline, "stage_describe",
        lambda cfg, storage, video, model, invoke=None: processed_ids.append(video["id"]),
    )

    (tmp_path / "canonical.mov").write_bytes(b"x")
    (tmp_path / "dup.mov").write_bytes(b"x")
    canonical = sqlite_storage.upsert_video("broll", "canonical.mov", status="proxied")
    dup = sqlite_storage.upsert_video("broll", "dup.mov", status="proxied")
    sqlite_storage.update_video(dup, duplicate_of=canonical)

    cfg = _cfg(tmp_path)
    count = pipeline.run_pipeline(cfg, sqlite_storage, model="sonnet", stages=["claude"])

    assert count == 1  # only the canonical was attempted
    assert processed_ids == [canonical]
    assert dup not in processed_ids

    # The duplicate's row is untouched by the run — never even entered the queue.
    dup_row = sqlite_storage.get_video(dup)
    assert dup_row["status"] == "proxied"
    assert dup_row.get("error") is None


def test_videos_by_status_excludes_confirmed_duplicates(sqlite_storage):
    keep = sqlite_storage.upsert_video("broll", "a.mov", status="proxied")
    dup = sqlite_storage.upsert_video("broll", "b.mov", status="proxied")
    sqlite_storage.update_video(dup, duplicate_of=keep)

    eligible = sqlite_storage.videos_by_status(["proxied"])
    assert {v["id"] for v in eligible} == {keep}


def test_run_pipeline_respects_limit_and_continues_past_errors(tmp_path, sqlite_storage, monkeypatch):
    monkeypatch.setattr(pipeline, "stage_probe", lambda cfg, storage, video, src_path: (_ for _ in ()).throw(RuntimeError("boom")))

    for i in range(3):
        (tmp_path / f"clip{i}.mov").write_bytes(b"x")
        sqlite_storage.upsert_video("broll", f"clip{i}.mov", status="discovered")

    cfg = _cfg(tmp_path)
    count = pipeline.run_pipeline(cfg, sqlite_storage, model="sonnet", limit=2, stages=["probe"])

    assert count == 2
    errored = sqlite_storage.videos_by_status(["error"])
    assert len(errored) == 2  # both attempted videos errored, but the queue kept going
    still_discovered = sqlite_storage.videos_by_status(["discovered"])
    assert len(still_discovered) == 1  # third video untouched due to limit


def test_audio_only_file_skips_visual_stages(tmp_path, schema_path, monkeypatch):
    """yt-dlp sometimes fetches an audio-only stream into an .mp4: a real
    duration but no video stream. Proxy, sprite and frame extraction all fail
    on those, yet the speech is perfectly indexable. Found on the real archive
    in an FF4 LoL subfolder. Mark them skipped for visual work instead of
    erroring on every run.
    """
    from broll_index import ffmpeg_tools
    from broll_index.pipeline import stage_probe
    from broll_index.storage.sqlite_backend import SqliteBackend

    db = SqliteBackend(tmp_path / "b.db", schema_path=schema_path)
    vid = db.upsert_video("s", "audio_only.mp4", status="discovered")

    monkeypatch.setattr(
        ffmpeg_tools, "probe_video",
        lambda p: {"duration_s": 1153.6, "fps": None, "width": None,
                   "height": None, "codec": None, "shot_date": None},
    )
    stage_probe(_cfg(tmp_path), db, db.get_video(vid), tmp_path / "audio_only.mp4")

    row = db.get_video(vid)
    assert row["status"] == "skipped"
    assert "audio-only" in (row["error"] or "")
    assert row["duration_s"] == 1153.6  # probe data still recorded

    # and it must not be picked up for visual work
    assert vid not in {v["id"] for v in db.videos_by_status(["discovered", "probed", "proxied"])}


def test_normal_video_still_probes_to_probed(tmp_path, schema_path, monkeypatch):
    from broll_index import ffmpeg_tools
    from broll_index.pipeline import stage_probe
    from broll_index.storage.sqlite_backend import SqliteBackend

    db = SqliteBackend(tmp_path / "b2.db", schema_path=schema_path)
    vid = db.upsert_video("s", "normal.mp4", status="discovered")
    monkeypatch.setattr(
        ffmpeg_tools, "probe_video",
        lambda p: {"duration_s": 30.0, "fps": 25.0, "width": 1920,
                   "height": 1080, "codec": "h264", "shot_date": None},
    )
    stage_probe(_cfg(tmp_path), db, db.get_video(vid), tmp_path / "normal.mp4")
    assert db.get_video(vid)["status"] == "probed"


def test_clip_over_the_share_duration_cap_is_skipped_before_any_cost(
    tmp_path, schema_path, monkeypatch
):
    """The cap has to bite at probe, the cheapest stage. Everything after it —
    proxy encode, scene detection, frame extraction, model calls — is what a long
    take actually costs. On the MOFA event 4 of 558 clips are 0.7% of the files
    but 16% of the total runtime."""
    from broll_index import ffmpeg_tools
    from broll_index.pipeline import stage_probe
    from broll_index.storage.sqlite_backend import SqliteBackend

    db = SqliteBackend(tmp_path / "cap.db", schema_path=schema_path)
    vid = db.upsert_video("broll", "Proxy/long_take.mov", status="discovered")
    monkeypatch.setattr(
        ffmpeg_tools, "probe_video",
        lambda p: {"duration_s": 1704.0, "fps": 25.0, "width": 1920,
                   "height": 1080, "codec": "h264", "shot_date": None},
    )

    cfg = _cfg(tmp_path)
    cfg.shares["broll"].max_duration_s = 300.0
    stage_probe(cfg, db, db.get_video(vid), tmp_path / "long_take.mov")

    row = db.get_video(vid)
    assert row["status"] == "skipped"
    assert "cap" in (row["error"] or "")
    assert row["duration_s"] == 1704.0, "probe data is still recorded"
    assert vid not in {v["id"] for v in db.videos_by_status(["discovered", "probed", "proxied"])}


def test_a_clip_under_the_cap_is_unaffected(tmp_path, schema_path, monkeypatch):
    from broll_index import ffmpeg_tools
    from broll_index.pipeline import stage_probe
    from broll_index.storage.sqlite_backend import SqliteBackend

    db = SqliteBackend(tmp_path / "cap2.db", schema_path=schema_path)
    vid = db.upsert_video("broll", "Proxy/short.mov", status="discovered")
    monkeypatch.setattr(
        ffmpeg_tools, "probe_video",
        lambda p: {"duration_s": 299.0, "fps": 25.0, "width": 1920,
                   "height": 1080, "codec": "h264", "shot_date": None},
    )
    cfg = _cfg(tmp_path)
    cfg.shares["broll"].max_duration_s = 300.0
    stage_probe(cfg, db, db.get_video(vid), tmp_path / "short.mov")
    assert db.get_video(vid)["status"] == "probed"


def test_no_cap_configured_leaves_long_clips_alone(tmp_path, schema_path, monkeypatch):
    """Existing shares set no cap and must behave exactly as before."""
    from broll_index import ffmpeg_tools
    from broll_index.pipeline import stage_probe
    from broll_index.storage.sqlite_backend import SqliteBackend

    db = SqliteBackend(tmp_path / "cap3.db", schema_path=schema_path)
    vid = db.upsert_video("broll", "long.mov", status="discovered")
    monkeypatch.setattr(
        ffmpeg_tools, "probe_video",
        lambda p: {"duration_s": 9999.0, "fps": 25.0, "width": 1920,
                   "height": 1080, "codec": "h264", "shot_date": None},
    )
    stage_probe(_cfg(tmp_path), db, db.get_video(vid), tmp_path / "long.mov")
    assert db.get_video(vid)["status"] == "probed"
