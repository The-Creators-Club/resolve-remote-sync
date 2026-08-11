from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from broll_index import ffmpeg_tools


# ---------------------------------------------------------------------------
# pure functions — no ffmpeg needed
# ---------------------------------------------------------------------------

def test_seconds_to_timecode():
    assert ffmpeg_tools.seconds_to_timecode(0) == "00:00:00"
    assert ffmpeg_tools.seconds_to_timecode(65) == "00:01:05"
    assert ffmpeg_tools.seconds_to_timecode(3725) == "01:02:05"


def test_compute_cell_size_preserves_aspect_ratio():
    w, h = ffmpeg_tools.compute_cell_size(1920, 1080, 384)
    assert w == 384
    assert h % 2 == 0
    assert abs(h - 216) <= 2  # 384 * 1080/1920 = 216


def test_fill_gaps_no_fill_needed():
    timestamps = [0.0, 2.0, 4.0]
    result = ffmpeg_tools.fill_gaps(timestamps, duration_s=4.0, max_gap_s=4.0)
    assert result == [0.0, 2.0, 4.0]


def test_fill_gaps_inserts_points_for_large_gap():
    timestamps = [0.0, 20.0]
    result = ffmpeg_tools.fill_gaps(timestamps, duration_s=20.0, max_gap_s=4.0)
    assert result[0] == 0.0
    assert result[-1] == 20.0
    for a, b in zip(result, result[1:]):
        assert b - a <= 4.0 + 1e-6


def test_fill_gaps_adds_leading_zero_if_first_timestamp_too_late():
    timestamps = [10.0]
    result = ffmpeg_tools.fill_gaps(timestamps, duration_s=10.0, max_gap_s=4.0)
    assert result[0] == 0.0


def test_fill_gaps_fills_trailing_gap_to_duration():
    timestamps = [0.0]
    result = ffmpeg_tools.fill_gaps(timestamps, duration_s=12.0, max_gap_s=4.0)
    assert result[-1] == 12.0
    for a, b in zip(result, result[1:]):
        assert b - a <= 4.0 + 1e-6


def test_fill_gaps_empty_timestamps():
    result = ffmpeg_tools.fill_gaps([], duration_s=9.0, max_gap_s=4.0)
    assert result[0] == 0.0
    assert result[-1] == 9.0


# ---------------------------------------------------------------------------
# real ffmpeg/ffprobe on a tiny generated clip (NVENC and claude are never invoked)
# ---------------------------------------------------------------------------

def test_probe_video_reads_duration_fps_resolution(tiny_clip):
    info = ffmpeg_tools.probe_video(tiny_clip)
    assert info["width"] == 320
    assert info["height"] == 240
    assert info["duration_s"] == pytest.approx(2.0, abs=0.2)
    assert info["fps"] == pytest.approx(25.0, abs=0.5)
    assert info["codec"] == "h264"


def test_build_proxy_libx264_fallback(tiny_clip, tmp_path):
    dest = tmp_path / "proxy.mp4"
    ffmpeg_tools.build_proxy(tiny_clip, dest, use_nvenc=False)
    assert dest.exists()
    assert dest.stat().st_size > 0
    info = ffmpeg_tools.probe_video(dest)
    # tiny_clip is 320x240 — below PROXY_HEIGHT, so it must NOT be upscaled.
    assert info["height"] == 240


def test_build_proxy_does_not_upscale_a_small_source(tiny_clip, tmp_path):
    """Upscaling a low-res source to the proxy height costs bytes and adds no
    detail. At archive scale that waste is the difference between fitting on
    disk and not."""
    dest = tmp_path / "proxy_noupscale.mp4"
    ffmpeg_tools.build_proxy(tiny_clip, dest, use_nvenc=False, height=1080)
    assert ffmpeg_tools.probe_video(dest)["height"] == 240


def test_build_proxy_downscales_a_large_source(tmp_path):
    big = tmp_path / "big.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", "testsrc=size=1920x1080:duration=1:rate=10",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(big)],
        check=True,
    )
    dest = tmp_path / "proxy_big.mp4"
    ffmpeg_tools.build_proxy(big, dest, use_nvenc=False, height=540)
    assert ffmpeg_tools.probe_video(dest)["height"] == 540
    # And the point of the exercise: the proxy is materially smaller.
    assert dest.stat().st_size < big.stat().st_size


def test_build_proxy_forces_8bit_from_a_10bit_source(tmp_path):
    """A 10-bit source (every FX3/FX30 shoot) must not produce a 10-bit
    proxy: without the -pix_fmt pin libx264 inherited the source format and
    emitted H.264 High 10, which browsers render as a black rectangle --
    every Creators_Club preview was unwatchable while its poster looked
    fine (found 2026-08-11)."""
    ten_bit = tmp_path / "tenbit.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", "testsrc=size=640x360:duration=1:rate=10",
         "-c:v", "libx264", "-pix_fmt", "yuv420p10le", str(ten_bit)],
        check=True,
    )
    dest = tmp_path / "proxy_8bit.mp4"
    ffmpeg_tools.build_proxy(ten_bit, dest, use_nvenc=False)

    info = ffmpeg_tools.run_ffprobe(dest)
    video = next(s for s in info["streams"] if s["codec_type"] == "video")
    assert video["pix_fmt"] == "yuv420p"
    assert video.get("profile") != "High 10"


def test_build_proxy_carries_the_sources_timecode(tmp_path):
    """Resolve's LinkProxyMedia validates the pairing and REFUSES a proxy
    with no embedded timecode against a source that has one (R10, proven
    live 2026-08-12) -- so the preview must inherit the camera's timecode
    or no archived clip can ever attach it."""
    src = tmp_path / "shot.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", "testsrc=size=640x360:duration=1:rate=10",
         "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-timecode", "01:02:03:04", str(src)],
        check=True,
    )
    # ffprobe renders the frame field unpadded at low rates ("01:02:03:4"),
    # so pin the round trip, not the literal string: the proxy must carry
    # exactly what the source carries.
    src_tc = ffmpeg_tools.read_timecode(src)
    assert src_tc is not None and src_tc.startswith("01:02:03")

    dest = tmp_path / "proxy_tc.mp4"
    ffmpeg_tools.build_proxy(src, dest, use_nvenc=False)
    assert ffmpeg_tools.read_timecode(dest) == src_tc


def test_dropframe_normalization():
    """Sony rtmd tags print colon (non-drop) forms for drop-frame material;
    at NTSC rates the colon reading is a different absolute frame and Resolve
    refuses the pairing (measured live 2026-08-12: colon refused, semicolon
    accepted, same bytes otherwise)."""
    f = ffmpeg_tools.dropframe_normalized
    assert f("03:40:27:12", 59.94) == "03:40:27;12"
    assert f("03:40:27:12", 29.97) == "03:40:27;12"
    # Already drop-form, integer rates, 23.976 (no DF variant), and unknown
    # fps all pass through untouched.
    assert f("03:40:27;12", 59.94) == "03:40:27;12"
    assert f("03:40:27:12", 25.0) == "03:40:27:12"
    assert f("03:40:27:12", 23.976) == "03:40:27:12"
    assert f("03:40:27:12", None) == "03:40:27:12"
    assert f(None, 59.94) is None


def test_a_source_without_timecode_still_proxies(tiny_clip, tmp_path):
    assert ffmpeg_tools.read_timecode(tiny_clip) is None
    dest = tmp_path / "proxy_notc.mp4"
    ffmpeg_tools.build_proxy(tiny_clip, dest, use_nvenc=False)
    assert dest.exists() and dest.stat().st_size > 0


def test_build_sprite_and_poster(tiny_clip, tmp_path):
    sprite = tmp_path / "sprite.jpg"
    poster = tmp_path / "poster.jpg"
    ffmpeg_tools.build_sprite(tiny_clip, sprite, duration_s=2.0)
    ffmpeg_tools.build_poster(tiny_clip, poster, duration_s=2.0)
    assert sprite.exists() and sprite.stat().st_size > 0
    assert poster.exists() and poster.stat().st_size > 0


def test_detect_scene_timestamps_and_extract_frames(tiny_clip, tmp_path):
    # testsrc is a constant animated pattern; scene threshold may or may not fire, but the
    # function must not crash and must return a sorted list of floats within range.
    timestamps = ffmpeg_tools.detect_scene_timestamps(tiny_clip, threshold=0.3)
    assert isinstance(timestamps, list)
    assert all(isinstance(t, float) for t in timestamps)

    filled = ffmpeg_tools.fill_gaps(timestamps, duration_s=2.0, max_gap_s=1.0)
    frames = ffmpeg_tools.extract_frames(tiny_clip, filled, tmp_path / "frames", duration_s=2.0)
    assert len(frames) == len(filled)
    for ts, f in frames:
        assert isinstance(ts, float)
        assert f.exists() and f.stat().st_size > 0


def test_build_contact_sheet_from_extracted_frames(tiny_clip, tmp_path):
    timestamps = [0.0, 0.5, 1.0]
    frames = ffmpeg_tools.extract_frames(tiny_clip, timestamps, tmp_path / "frames")
    timecodes = [ffmpeg_tools.seconds_to_timecode(ts) for ts, _ in frames]
    out = tmp_path / "sheet_0001.jpg"
    result = ffmpeg_tools.build_contact_sheet(
        [p for _, p in frames], timecodes, out, cell_width=160, cell_height=90
    )
    assert result == out
    assert out.exists() and out.stat().st_size > 0


def test_build_contact_sheets_groups_by_nine(tiny_clip, tmp_path):
    timestamps = [i * 0.1 for i in range(11)]  # 11 frames -> 2 sheets (9 + 2)
    frames = ffmpeg_tools.extract_frames(tiny_clip, timestamps, tmp_path / "frames")
    sheets = ffmpeg_tools.build_contact_sheets(frames, tmp_path / "sheets", width=320, height=240)
    assert len(sheets) == 2
    for s in sheets:
        assert s.exists() and s.stat().st_size > 0


# ---------------------------------------------------------------------------
# regressions from the first real-archive run (FF2 E1)
# ---------------------------------------------------------------------------

def test_extract_frames_skips_frames_ffmpeg_did_not_write(tiny_clip, tmp_path):
    """Seeking past the real end of a stream writes nothing but still exits 0.

    Container duration routinely overstates the decodable stream (dashcam
    recordings especially), so the returned list must contain only real files —
    a phantom path aborts the whole contact sheet later.
    """
    timestamps = [0.0, 0.5, 900.0]  # last one is far beyond the 2s clip
    frames = ffmpeg_tools.extract_frames(tiny_clip, timestamps, tmp_path / "frames")

    assert all(p.is_file() and p.stat().st_size > 0 for _, p in frames)
    assert [ts for ts, _ in frames] == [0.0, 0.5]


def test_build_contact_sheets_tolerates_a_vanished_frame(tiny_clip, tmp_path):
    frames = ffmpeg_tools.extract_frames(tiny_clip, [0.0, 0.5, 1.0], tmp_path / "frames")
    frames[1][1].unlink()  # simulate a frame disappearing after extraction

    sheets = ffmpeg_tools.build_contact_sheets(frames, tmp_path / "sheets", width=320, height=240)

    assert len(sheets) == 1
    assert sheets[0].exists() and sheets[0].stat().st_size > 0


def test_contact_sheet_timecodes_stay_bound_to_their_frame(tiny_clip, tmp_path, monkeypatch):
    """A dropped frame must not shift later timecodes.

    Pairing frames and timestamps by list position (the original bug) silently
    mislabels every cell after a gap, which would put wrong times into search
    results — the worst possible failure, since nothing looks broken.
    """
    captured: list[list[str]] = []
    real_build = ffmpeg_tools.build_contact_sheet

    def spy(frame_paths, timecodes, out_path, **kwargs):
        captured.append(list(timecodes))
        return real_build(frame_paths, timecodes, out_path, **kwargs)

    monkeypatch.setattr(ffmpeg_tools, "build_contact_sheet", spy)

    # 10s and 20s frames exist; the 900s one cannot be extracted.
    frames = ffmpeg_tools.extract_frames(
        tiny_clip, [0.0, 1.0], tmp_path / "frames"
    )
    frames = [(0.0, frames[0][1]), (10.0, frames[1][1])]

    ffmpeg_tools.build_contact_sheets(frames, tmp_path / "sheets", width=320, height=240)

    assert captured == [["00:00:00", "00:00:10"]]


def test_detect_nvenc_available_returns_bool():
    # We never assert True/False (depends on the machine's GPU/driver) — just that the
    # detection call itself doesn't crash and returns a bool, and is cached.
    result = ffmpeg_tools.detect_nvenc_available()
    assert isinstance(result, bool)

def test_build_proxy_survives_an_odd_height_non_420_source(tmp_path):
    """An odd-height RGB/4:4:4 source (screen captures, ffv1) fails at encoder
    init unless the scale filter guards HEIGHT to even as well as width — the
    width's `-2` already does, the height's bare `min(H,ih)` did not
    (MED-12, 2026-08-11; measured: 640x481 + `min(1080,ih)` → ffmpeg exit -22,
    nothing written). The same trunc(...)/2)*2 filter is hand-copied into the
    companion's preview_proxy_cmd argv-literal tests — change one, change both."""
    odd = tmp_path / "odd.mkv"
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", "testsrc=size=640x481:duration=1:rate=10",
         "-c:v", "ffv1", "-pix_fmt", "yuv444p", str(odd)],
        check=True,
    )
    dest = tmp_path / "proxy_odd.mp4"
    ffmpeg_tools.build_proxy(odd, dest, use_nvenc=False, height=1080)
    assert ffmpeg_tools.probe_video(dest)["height"] == 480
