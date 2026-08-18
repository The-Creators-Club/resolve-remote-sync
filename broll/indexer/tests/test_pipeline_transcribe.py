from __future__ import annotations

from pathlib import Path

import pytest

from broll_index import pipeline
from broll_index.config import Config, DbConfig, SamplingConfig, ShareConfig, WhisperConfig

# Same shape as tests/test_transcribe.py's fixture SRT.
SRT = """1
00:00:00,000 --> 00:00:02,480
清晨九點半

2
00:00:02,480 --> 00:00:05,120
警方展開了第一波攻堅行動
"""


def _cfg(tmp_path, **whisper_overrides) -> Config:
    whisper = WhisperConfig(**whisper_overrides)
    return Config(
        shares={"broll": ShareConfig(root=str(tmp_path))},
        data_root=tmp_path / "_data",
        db=DbConfig(mode="sqlite", path=str(tmp_path / "broll.db")),
        model="sonnet",
        sampling=SamplingConfig(),
        whisper=whisper,
    )


def _never_called_runner(*args, **kwargs):
    raise AssertionError("the whisper runner must not be invoked when an .srt already exists")


# ---------------------------------------------------------------------------
# reuse an existing .srt — must never call the runner (no redone GPU work)
# ---------------------------------------------------------------------------

def test_stage_transcribe_reuses_existing_srt_without_calling_runner(tmp_path, sqlite_storage):
    (tmp_path / "clip.mov").write_bytes(b"x")
    vid = sqlite_storage.upsert_video("broll", "clip.mov", status="proxied")
    cfg = _cfg(tmp_path)

    out_dir = cfg.data_root / "transcripts" / str(vid)
    out_dir.mkdir(parents=True)
    (out_dir / "clip.srt").write_text(SRT, encoding="utf-8")

    video = sqlite_storage.get_video(vid)
    pipeline.stage_transcribe(cfg, sqlite_storage, video, tmp_path / "clip.mov", runner=_never_called_runner)

    row = sqlite_storage.get_video(vid)
    assert row["transcribed_at"] is not None
    assert row["status"] == "proxied"  # transcription never touches videos.status

    cues = sqlite_storage.get_transcript(vid)
    assert len(cues) == 1  # gap 0 between the two cues -> merged (default max_gap_s=1.0)
    assert "清晨九點半" in cues[0].text
    assert "警方展開了第一波攻堅行動" in cues[0].text


def test_stage_transcribe_is_idempotent_when_transcribed_at_already_set(tmp_path, sqlite_storage):
    (tmp_path / "clip.mov").write_bytes(b"x")
    vid = sqlite_storage.upsert_video(
        "broll", "clip.mov", status="proxied", transcribed_at="2026-01-01T00:00:00+00:00"
    )
    cfg = _cfg(tmp_path)
    video = sqlite_storage.get_video(vid)

    # No .srt on disk at all, and a runner that would blow up if called — if the
    # already-set transcribed_at guard were broken, this would raise.
    pipeline.stage_transcribe(cfg, sqlite_storage, video, tmp_path / "clip.mov", runner=_never_called_runner)

    assert sqlite_storage.get_transcript(vid) == []  # untouched — never even attempted


# ---------------------------------------------------------------------------
# runs whisper (mocked runner boundary) when no .srt exists yet
# ---------------------------------------------------------------------------

def test_stage_transcribe_runs_whisper_when_no_srt_exists(tmp_path, sqlite_storage):
    (tmp_path / "clip.mov").write_bytes(b"x")
    vid = sqlite_storage.upsert_video("broll", "clip.mov", status="proxied")

    python_exe = tmp_path / "python.exe"
    script = tmp_path / "transcribe.py"
    python_exe.write_bytes(b"")
    script.write_bytes(b"")

    cfg = _cfg(tmp_path, python=str(python_exe), script=str(script), language="zh")

    produced_srt = tmp_path / "produced.srt"
    produced_srt.write_text(SRT, encoding="utf-8")

    calls = []

    def fake_runner(src, out_dir, python_exe_arg, script_arg, model, language):
        calls.append(
            {"src": src, "python": python_exe_arg, "script": script_arg, "model": model, "language": language}
        )
        return produced_srt

    video = sqlite_storage.get_video(vid)
    pipeline.stage_transcribe(cfg, sqlite_storage, video, tmp_path / "clip.mov", runner=fake_runner)

    assert len(calls) == 1
    assert calls[0]["language"] == "zh"
    assert calls[0]["model"] == "large-v3-turbo"

    row = sqlite_storage.get_video(vid)
    assert row["transcribed_at"] is not None
    assert row["transcript_lang"] == "zh"
    cues = sqlite_storage.get_transcript(vid)
    assert len(cues) == 1


def test_ingest_only_never_runs_whisper_when_no_srt_exists(tmp_path, sqlite_storage):
    """The local parallel runner's contract: ingest an .srt or do nothing.

    Without this, a share that has never been through batch_transcribe.py turns
    what the caller believes is a cheap parse into a full Whisper run — and it
    happens ahead of stage_probe, so ahead of the max_duration_s cap that would
    have discarded the long takes it is transcribing.
    """
    (tmp_path / "clip.mov").write_bytes(b"x")
    vid = sqlite_storage.upsert_video("broll", "clip.mov", status="discovered")

    python_exe = tmp_path / "python.exe"
    script = tmp_path / "transcribe.py"
    python_exe.write_bytes(b"")
    script.write_bytes(b"")
    cfg = _cfg(tmp_path, python=str(python_exe), script=str(script))

    video = sqlite_storage.get_video(vid)
    pipeline.stage_transcribe(cfg, sqlite_storage, video, tmp_path / "clip.mov",
                              runner=_never_called_runner, ingest_only=True)

    row = sqlite_storage.get_video(vid)
    assert row["transcribed_at"] is None
    assert row["status"] == "discovered"
    assert sqlite_storage.get_transcript(vid) == []


def test_ingest_only_still_ingests_an_existing_srt(tmp_path, sqlite_storage):
    (tmp_path / "clip.mov").write_bytes(b"x")
    vid = sqlite_storage.upsert_video("broll", "clip.mov", status="discovered")

    out_dir = tmp_path / "_data" / "transcripts" / str(vid)
    out_dir.mkdir(parents=True)
    (out_dir / "clip.srt").write_text(SRT, encoding="utf-8")

    cfg = _cfg(tmp_path)
    video = sqlite_storage.get_video(vid)
    pipeline.stage_transcribe(cfg, sqlite_storage, video, tmp_path / "clip.mov",
                              runner=_never_called_runner, ingest_only=True)

    assert sqlite_storage.get_video(vid)["transcribed_at"] is not None
    assert len(sqlite_storage.get_transcript(vid)) == 1


def test_parallel_local_calls_transcribe_with_ingest_only():
    """Pin the call site — the flag is only useful if the runner actually passes it."""
    import inspect

    import parallel_local

    assert "ingest_only=True" in inspect.getsource(parallel_local._process_one)


# ---------------------------------------------------------------------------
# failure handling — additive enrichment only, must never touch status or block claude
# ---------------------------------------------------------------------------

def test_stage_transcribe_swallows_runner_failure(tmp_path, sqlite_storage, caplog):
    (tmp_path / "clip.mov").write_bytes(b"x")
    vid = sqlite_storage.upsert_video("broll", "clip.mov", status="proxied")

    python_exe = tmp_path / "python.exe"
    script = tmp_path / "transcribe.py"
    python_exe.write_bytes(b"")
    script.write_bytes(b"")
    cfg = _cfg(tmp_path, python=str(python_exe), script=str(script))

    def failing_runner(*args, **kwargs):
        raise RuntimeError("whisper exited 1: CUDA out of memory")

    video = sqlite_storage.get_video(vid)
    # Must not raise.
    pipeline.stage_transcribe(cfg, sqlite_storage, video, tmp_path / "clip.mov", runner=failing_runner)

    row = sqlite_storage.get_video(vid)
    assert row["status"] == "proxied"  # not 'error'
    assert row["transcribed_at"] is None
    assert sqlite_storage.get_transcript(vid) == []


def test_process_video_transcribe_failure_does_not_error_video_or_block_claude(tmp_path, sqlite_storage, monkeypatch):
    calls = []
    monkeypatch.setattr(pipeline, "stage_probe", lambda *a, **k: (calls.append("probe"), a[1].update_video(a[2]["id"], status="probed", duration_s=2.0, fps=25.0, width=320, height=240)))
    monkeypatch.setattr(pipeline, "stage_proxy", lambda *a, **k: (calls.append("proxy"), a[1].update_video(a[2]["id"], status="proxied")))
    monkeypatch.setattr(pipeline, "stage_frames", lambda *a, **k: calls.append("frames"))

    def failing_transcribe(cfg, storage, video, src_path, ingest_only=False):
        calls.append("transcribe")
        raise RuntimeError("whisper blew up")

    def fake_claude(cfg, storage, video, model, invoke=None):
        calls.append("claude")
        storage.write_index_result(
            video["id"], themes=[], quality_flags=[], category_hint=None, segments=[], model=model
        )

    monkeypatch.setattr(pipeline, "stage_transcribe", failing_transcribe)
    monkeypatch.setattr(pipeline, "stage_describe", fake_claude)

    (tmp_path / "clip.mov").write_bytes(b"x")
    vid = sqlite_storage.upsert_video("broll", "clip.mov", status="discovered")
    cfg = Config(
        shares={"broll": ShareConfig(root=str(tmp_path))},
        data_root=tmp_path / "_data",
        db=DbConfig(mode="sqlite", path=str(tmp_path / "broll.db")),
        model="sonnet",
        sampling=SamplingConfig(),
    )
    video = sqlite_storage.get_video(vid)

    pipeline._process_video(cfg, sqlite_storage, video, model="sonnet", requested_stages=set(pipeline.DEFAULT_STAGES))

    assert calls == ["probe", "proxy", "frames", "transcribe", "claude"]  # claude still ran
    row = sqlite_storage.get_video(vid)
    assert row["status"] == "indexed"  # not 'error' — transcribe failure didn't stop the queue
    assert row["error"] is None


# ---------------------------------------------------------------------------
# disabled / missing-whisper paths skip cleanly
# ---------------------------------------------------------------------------

def test_stage_transcribe_skips_when_disabled(tmp_path, sqlite_storage):
    (tmp_path / "clip.mov").write_bytes(b"x")
    vid = sqlite_storage.upsert_video("broll", "clip.mov", status="proxied")
    cfg = _cfg(tmp_path, enabled=False)

    video = sqlite_storage.get_video(vid)
    pipeline.stage_transcribe(cfg, sqlite_storage, video, tmp_path / "clip.mov", runner=_never_called_runner)

    row = sqlite_storage.get_video(vid)
    assert row["transcribed_at"] is None
    assert row["status"] == "proxied"


def test_stage_transcribe_skips_when_whisper_paths_missing(tmp_path, sqlite_storage):
    (tmp_path / "clip.mov").write_bytes(b"x")
    vid = sqlite_storage.upsert_video("broll", "clip.mov", status="proxied")
    cfg = _cfg(
        tmp_path,
        python=str(tmp_path / "nope" / "python.exe"),
        script=str(tmp_path / "nope" / "transcribe.py"),
    )

    video = sqlite_storage.get_video(vid)
    pipeline.stage_transcribe(cfg, sqlite_storage, video, tmp_path / "clip.mov", runner=_never_called_runner)

    row = sqlite_storage.get_video(vid)
    assert row["transcribed_at"] is None
    assert row["status"] == "proxied"
