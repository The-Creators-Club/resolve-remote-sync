"""The 2026-09-18b hunt, the b-roll indexer's half (webapps-tools, CR-290).

Same substitution discipline as the 2026-09-18 file: no ffmpeg runs, the
encoder, the probes and the packet counts are the module's own seams, which is
what lets these tests pin WHICH reads are paid for as well as the verdict.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from broll_index import ffmpeg_tools


@pytest.fixture(autouse=True)
def _clean_frame_cache():
    """The source-count memo is process-wide; a test must not inherit one."""
    ffmpeg_tools.clear_frame_count_cache()
    yield
    ffmpeg_tools.clear_frame_count_cache()


# ------------------------------------------------------- broll-indexer-1

class _Probe:
    """One ffprobe answer for a 60 s / 30 fps file (1800 frames)."""

    INFO = {
        "format": {"duration": "60.0"},
        "streams": [{"codec_type": "video", "codec_name": "h264",
                     "width": 1920, "height": 1080,
                     "avg_frame_rate": "30/1"}],
    }


def _build(monkeypatch, tmp_path, counts, use_nvenc=False, encoder_fails=False):
    """Run build_proxy with every external read substituted.

    Returns the paths `count_frames` was asked about: the whole of
    broll-indexer-1 is that the SOURCE stopped being one of them.
    """
    asked = []

    def fake_count(path):
        asked.append(str(path))
        return counts.get("src" if str(path).endswith("src.mov") else "dest")

    class _Done:
        returncode = 0
        stderr = ""

    class _Failed:
        returncode = 1
        stderr = "nvenc session limit"

    def fake_run(cmd, *a, **k):
        if encoder_fails and "h264_nvenc" in cmd:
            return _Failed()
        return _Done()

    monkeypatch.setattr(ffmpeg_tools, "run_ffprobe", lambda p: _Probe.INFO)
    monkeypatch.setattr(ffmpeg_tools.subprocess, "run", fake_run)
    monkeypatch.setattr(ffmpeg_tools, "verify_decodes", lambda p: 0)
    monkeypatch.setattr(ffmpeg_tools, "count_frames", fake_count)
    monkeypatch.setattr(ffmpeg_tools, "probe_video",
                        lambda p: {"duration_s": 60.0})
    src = tmp_path / "src.mov"
    src.write_bytes(b"source")
    ffmpeg_tools.build_proxy(src, tmp_path / "out.mp4", use_nvenc=use_nvenc)
    return asked


@pytest.mark.parametrize("dst", [1799, 1798])
def test_a_proxy_one_or_two_frames_short_is_refused(monkeypatch, tmp_path, dst):
    """The low end of the Reproductive Rights class (1-18 frames short).

    A CFR original's real count IS its duration * fps, so a proxy 1 or 2
    frames short of it sat inside the cheap estimate's window and the source
    was never counted - the exact comparison never ran.
    """
    with pytest.raises(RuntimeError) as exc:
        _build(monkeypatch, tmp_path, {"dest": dst, "src": 1800})
    assert f"{dst} frames of the source's 1800" in str(exc.value)


def test_a_proxy_longer_than_its_source_is_refused_too(monkeypatch, tmp_path):
    """frames_match is EXACT in both directions, and the indexer must not be
    the one producer with a private tolerance."""
    with pytest.raises(RuntimeError) as exc:
        _build(monkeypatch, tmp_path, {"dest": 1802, "src": 1800})
    assert "1802 frames of the source's 1800" in str(exc.value)


def test_a_good_proxy_costs_one_source_read_across_the_encoder_fallback(
        monkeypatch, tmp_path):
    """CR-286B's saving that survives an exact comparison: the source is
    demuxed once per original, not once per verification pass."""
    asked = _build(monkeypatch, tmp_path, {"dest": 1800, "src": 1800},
                   use_nvenc=True, encoder_fails=True)
    assert [a for a in asked if a.endswith("src.mov")].__len__() == 1, asked


def test_a_count_the_destination_cannot_produce_costs_no_source_read(
        monkeypatch, tmp_path):
    """"Both known or skip" is unchanged, and an unknowable comparison must
    not pay for the expensive half of itself."""
    asked = _build(monkeypatch, tmp_path, {"dest": None, "src": 1800})
    assert not any(a.endswith("src.mov") for a in asked), asked


def test_the_source_count_memo_is_keyed_on_the_bytes(monkeypatch, tmp_path):
    """A re-encoded file at the same path is a different file."""
    calls = []
    monkeypatch.setattr(ffmpeg_tools, "count_frames",
                        lambda p: calls.append(str(p)) or len(calls))
    f = tmp_path / "a.mov"
    f.write_bytes(b"one")
    assert ffmpeg_tools.count_frames_cached(f) == 1
    assert ffmpeg_tools.count_frames_cached(f) == 1  # memo hit
    f.write_bytes(b"one-longer")
    assert ffmpeg_tools.count_frames_cached(f) == 2
    assert len(calls) == 2


def test_a_count_that_failed_once_is_not_remembered(monkeypatch, tmp_path):
    """CR-290A: `count_frames` answers None for an SMB blip as well as for an
    unreadable file, and a memoised None would leave that original unchecked
    for the life of the process - every later proxy of it taking the "both
    known or skip" branch."""
    answers = [None, 1800]
    calls = []

    def fake_count(path):
        if str(path).endswith("src.mov"):
            calls.append(str(path))
            return answers.pop(0)
        return 1799

    class _Done:
        returncode = 0
        stderr = ""

    monkeypatch.setattr(ffmpeg_tools, "run_ffprobe", lambda p: _Probe.INFO)
    monkeypatch.setattr(ffmpeg_tools.subprocess, "run", lambda *a, **k: _Done())
    monkeypatch.setattr(ffmpeg_tools, "verify_decodes", lambda p: 0)
    monkeypatch.setattr(ffmpeg_tools, "count_frames", fake_count)
    monkeypatch.setattr(ffmpeg_tools, "probe_video",
                        lambda p: {"duration_s": 60.0})
    src = tmp_path / "src.mov"
    src.write_bytes(b"source")

    # The blip: nothing can be compared, so nothing is condemned.
    ffmpeg_tools.build_proxy(src, tmp_path / "out.mp4", use_nvenc=False)

    # The next proxy of the same original must be counted for real.
    with pytest.raises(RuntimeError) as exc:
        ffmpeg_tools.build_proxy(src, tmp_path / "out2.mp4", use_nvenc=False)
    assert "1799 frames of the source's 1800" in str(exc.value)
    assert len(calls) == 2, calls


@pytest.mark.parametrize("partial", [1799, 1798])
def test_make_own_proxies_refuses_a_one_frame_short_proxy(
        monkeypatch, tmp_path, partial):
    """The editor-grade producer: its output is renamed into Proxy/<stem>.mp4
    and linked by Resolve directly."""
    import tools.make_own_proxies as mop

    class _Done:
        returncode = 0
        stderr = ""

    src = tmp_path / "A003.mov"
    src.write_bytes(b"source")
    monkeypatch.setattr(mop.ffmpeg_tools, "probe_video",
                        lambda p: {"duration_s": 60.0, "fps": 30.0,
                                   "width": 1920, "height": 1080})
    monkeypatch.setattr(mop.ffmpeg_tools, "read_timecode_source",
                        lambda p: (None, False))
    monkeypatch.setattr(mop.ffmpeg_tools, "verify_decodes", lambda p: 0)
    monkeypatch.setattr(mop.subprocess, "run", lambda *a, **k: _Done())
    monkeypatch.setattr(
        mop.ffmpeg_tools, "count_frames",
        lambda p: partial if str(p).endswith(".partial") else 1800)

    rec = mop.encode_one(src, cap_s=0, nvenc=False, dry=False)

    assert rec["status"] == "bad-output", rec
    assert f"{partial} frames of the source's 1800" in rec["detail"]
    assert not (src.parent / "Proxy" / "A003.mp4").exists()
