"""What the serial pipeline does after a stage has already ruled a clip out.

Two stages sit AFTER the ones that make those rulings and neither is gated on
status, so both used to run anyway:

  * `transcribe` on a clip `probe` had just discarded for length -- a full
    Whisper pass on a three-hour take on its way to the bin (BROLL-4). It also
    ran Whisper rather than ingesting an existing .srt, which is the same waste
    by another route (parallel_local.py was fixed for this; the serial path was
    not);
  * nothing at all after `frames` on an `index: false` share, because that
    branch `return`ed -- abandoning the loop before `transcribe` and `embed`,
    so `index: false` silently implied `transcribe: false` (BROLL-5).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from broll_index import pipeline
from broll_index.config import Config, DbConfig, SamplingConfig, ShareConfig, WhisperConfig


def _cfg(tmp_path: Path, share: ShareConfig) -> Config:
    return Config(
        shares={"s": share},
        data_root=tmp_path / "_data",
        db=DbConfig(mode="sqlite", path=str(tmp_path / "broll.db")),
        model="sonnet",
        sampling=SamplingConfig(),
        whisper=WhisperConfig(),
    )


def _stub_stages(monkeypatch, calls: list[str], *, probe_result: dict):
    def fake_probe(cfg, storage, video, src_path):
        calls.append("probe")
        storage.update_video(video["id"], **probe_result)

    monkeypatch.setattr(pipeline, "stage_probe", fake_probe)
    monkeypatch.setattr(pipeline, "stage_proxy", lambda cfg, storage, video, src: (
        calls.append("proxy"), storage.update_video(video["id"], status="proxied")))
    monkeypatch.setattr(pipeline, "stage_frames",
                        lambda cfg, storage, video, src: calls.append("frames"))
    monkeypatch.setattr(pipeline, "stage_describe",
                        lambda cfg, storage, video, model, invoke=None: calls.append("claude"))
    monkeypatch.setattr(pipeline, "stage_embed",
                        lambda cfg, storage, video: calls.append("embed"))

    def fake_transcribe(cfg, storage, video, src_path, ingest_only=False):
        calls.append(f"transcribe(ingest_only={ingest_only})")

    monkeypatch.setattr(pipeline, "stage_transcribe", fake_transcribe)


def _run(tmp_path, storage, share: ShareConfig, monkeypatch, calls, probe_result):
    _stub_stages(monkeypatch, calls, probe_result=probe_result)
    (tmp_path / "clip.mov").write_bytes(b"x")
    vid = storage.upsert_video("s", "clip.mov", status="discovered")
    pipeline._process_video(
        _cfg(tmp_path, share), storage, storage.get_video(vid),
        model="sonnet", requested_stages=set(pipeline.DEFAULT_STAGES),
    )
    return vid


# ---------------------------------------------------------------------------
# BROLL-4 — the duration cap has to mean something to the stages after probe
# ---------------------------------------------------------------------------

def test_an_over_length_clip_is_not_transcribed(tmp_path, sqlite_storage, monkeypatch):
    calls: list[str] = []
    _run(tmp_path, sqlite_storage,
         ShareConfig(root=str(tmp_path), max_duration_s=300), monkeypatch, calls,
         probe_result={"status": "skipped", "codec": "h264", "duration_s": 10800.0,
                       "error": "longer than 300s cap (10800s) — not indexed"})

    assert not any(c.startswith("transcribe") for c in calls)
    # `embed` still runs, as it always has: it reads already-stored rows, finds
    # none, and costs nothing. The expensive stage is the one that must not.
    assert calls == ["probe", "embed"]


def test_an_audio_only_clip_is_still_transcribed(tmp_path, sqlite_storage, monkeypatch):
    """The other reason probe says 'skipped'. There is nothing to see, and the
    speech is the only index the clip will ever have -- see stage_probe."""
    calls: list[str] = []
    _run(tmp_path, sqlite_storage,
         ShareConfig(root=str(tmp_path)), monkeypatch, calls,
         probe_result={"status": "skipped", "codec": None, "duration_s": 640.0,
                       "error": "audio-only (no video stream) — transcript indexed, no visuals"})

    assert "transcribe(ingest_only=True)" in calls


def test_the_serial_path_ingests_an_srt_rather_than_running_whisper(
    tmp_path, sqlite_storage, monkeypatch
):
    """ingest_only, like parallel_local.py: without it a share that has never
    been through batch_transcribe.py gets a real Whisper run per clip, inside
    the local pass, ahead of everything else."""
    calls: list[str] = []
    _run(tmp_path, sqlite_storage, ShareConfig(root=str(tmp_path)), monkeypatch, calls,
         probe_result={"status": "probed", "duration_s": 4.0, "codec": "h264",
                       "width": 320, "height": 240})

    assert "transcribe(ingest_only=True)" in calls
    assert "transcribe(ingest_only=False)" not in calls


@pytest.mark.parametrize("row,expected", [
    ({"status": "skipped", "codec": "h264", "duration_s": 900.0}, True),
    ({"status": "skipped", "codec": None, "duration_s": 900.0}, False),   # audio-only
    ({"status": "skipped", "codec": None, "duration_s": None}, False),    # never probed
    ({"status": "proxied", "codec": "h264", "duration_s": 900.0}, False),
])
def test_skipped_for_length_reads_the_row_not_the_error_prose(row, expected):
    assert pipeline.skipped_for_length(row) is expected


# ---------------------------------------------------------------------------
# BROLL-5 — `index: false` must not imply `transcribe: false`
# ---------------------------------------------------------------------------

def test_an_index_false_share_still_transcribes_and_embeds(
    tmp_path, sqlite_storage, monkeypatch
):
    calls: list[str] = []
    vid = _run(tmp_path, sqlite_storage,
               ShareConfig(root=str(tmp_path), index=False), monkeypatch, calls,
               probe_result={"status": "probed", "duration_s": 4.0, "codec": "h264",
                             "width": 320, "height": 240})

    assert "transcribe(ingest_only=True)" in calls
    assert "embed" in calls
    # The stages that opting out is ABOUT are still skipped, and the clip rests
    # where it did before.
    assert "frames" not in calls and "claude" not in calls
    assert sqlite_storage.get_video(vid)["status"] == pipeline.ORGANISED_STATUS


def test_an_index_false_share_that_also_opts_out_of_transcribe_gets_neither(
    tmp_path, sqlite_storage, monkeypatch
):
    calls: list[str] = []
    _run(tmp_path, sqlite_storage,
         ShareConfig(root=str(tmp_path), index=False, transcribe=False),
         monkeypatch, calls,
         probe_result={"status": "probed", "duration_s": 4.0, "codec": "h264",
                       "width": 320, "height": 240})

    assert not any(c.startswith("transcribe") for c in calls)
    assert "frames" not in calls and "claude" not in calls
