"""A proxy must be proven to decode, not just to exist.

Real failure on the archive run: 10 of 244 proxies had correct duration,
resolution and container metadata while their H.264 bitstreams were damaged
("Invalid NAL unit size"). The source files decoded perfectly, so the pipeline
introduced it — concurrent encoding on the GPU silently emitting bad output
rather than failing. A corrupt proxy is worse than a missing one: the frames
that reach the model are wrong and the editor's preview is broken, with nothing
in the logs to say so.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from broll_index import ffmpeg_tools


@pytest.fixture
def clip(tmp_path: Path) -> Path:
    out = tmp_path / "src.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", "testsrc2=size=640x480:duration=2:rate=15",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)],
        check=True,
    )
    return out


def test_verify_decodes_reports_zero_for_a_good_file(clip: Path):
    assert ffmpeg_tools.verify_decodes(clip) == 0


def test_verify_decodes_detects_a_damaged_bitstream(clip: Path, tmp_path: Path):
    """Corrupt the middle of the file, leaving the container header intact —
    exactly the shape of the real failure (metadata fine, video data damaged)."""
    damaged = tmp_path / "damaged.mp4"
    data = bytearray(clip.read_bytes())
    start = len(data) // 3
    for i in range(start, min(start + 6000, len(data))):
        data[i] ^= 0xFF
    damaged.write_bytes(bytes(data))

    assert ffmpeg_tools.verify_decodes(damaged) > 0


def test_build_proxy_verifies_by_default(clip: Path, tmp_path: Path, monkeypatch):
    """The happy path must actually run a verification pass."""
    calls = []
    real = ffmpeg_tools.verify_decodes

    def spy(path, *a, **kw):
        calls.append(Path(path).name)
        return real(path, *a, **kw)

    monkeypatch.setattr(ffmpeg_tools, "verify_decodes", spy)
    dest = tmp_path / "proxy.mp4"
    ffmpeg_tools.build_proxy(clip, dest, use_nvenc=False)

    assert dest.is_file()
    assert calls, "build_proxy did not verify its output"


def test_corrupt_encode_falls_back_and_raises_if_still_bad(clip: Path, tmp_path: Path, monkeypatch):
    """If both the primary encode and the CPU fallback produce corruption, fail
    loudly rather than leaving a broken proxy in place."""
    monkeypatch.setattr(ffmpeg_tools, "verify_decodes", lambda *a, **kw: 42)
    with pytest.raises(RuntimeError, match="unusable"):
        ffmpeg_tools.build_proxy(clip, tmp_path / "p.mp4", use_nvenc=False)


def test_verify_can_be_disabled_for_speed(clip: Path, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(ffmpeg_tools, "verify_decodes",
                        lambda *a, **kw: pytest.fail("should not verify"))
    ffmpeg_tools.build_proxy(clip, tmp_path / "p.mp4", use_nvenc=False, verify=False)


def test_truncated_proxy_is_rejected(clip: Path, tmp_path: Path, monkeypatch):
    """A proxy can decode with ZERO errors and still be unusable because it
    stops early. Seen on the archive: an AV1 source produced a short proxy that
    passed the error check, then frame extraction failed seeking past the cut.
    Duration must be compared against the source, not just error count.
    """
    real_probe = ffmpeg_tools.probe_video

    def fake_probe(path, *a, **kw):
        info = dict(real_probe(path, *a, **kw))
        # Report the proxy as half the length of the source.
        if Path(path).name == "proxy.mp4":
            info["duration_s"] = (info.get("duration_s") or 2.0) / 2
        return info

    monkeypatch.setattr(ffmpeg_tools, "verify_decodes", lambda *a, **kw: 0)
    monkeypatch.setattr(ffmpeg_tools, "probe_video", fake_probe)

    with pytest.raises(RuntimeError, match="truncated"):
        ffmpeg_tools.build_proxy(clip, tmp_path / "proxy.mp4", use_nvenc=False)


def test_sprite_widens_interval_for_a_long_clip(clip: Path, tmp_path: Path, monkeypatch):
    """A 16-minute clip at the shipped 2s interval wants ~490 cells
    (2400x6615 px) and failed outright on the real archive. The interval
    widens so a long clip gets a coarser sprite rather than none."""
    captured = {}

    def spy(cmd, *a, **kw):
        # Capture only — a 2s fixture clip at a widened interval yields no
        # frames, so actually running this would fail for reasons unrelated
        # to what is under test (the interval/tile arithmetic).
        if isinstance(cmd, list) and "-vf" in cmd:
            captured["vf"] = cmd[cmd.index("-vf") + 1]
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(ffmpeg_tools.subprocess, "run", spy)
    ffmpeg_tools.build_sprite(clip, tmp_path / "s.jpg", duration_s=3600.0, max_cells=60)

    vf = captured.get("vf", "")
    # 3600s over at most 60 cells -> one frame per 60s, tiled 10 wide x 6
    assert "fps=1/60" in vf, vf
    assert "tile=10x6" in vf, vf


def test_sprite_keeps_the_default_interval_when_it_fits(clip: Path, tmp_path: Path, monkeypatch):
    captured = {}
    def spy(cmd, *a, **kw):
        if isinstance(cmd, list) and "-vf" in cmd:
            captured["vf"] = cmd[cmd.index("-vf") + 1]
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(ffmpeg_tools.subprocess, "run", spy)
    ffmpeg_tools.build_sprite(clip, tmp_path / "s2.jpg", duration_s=60.0)

    assert "fps=1/2.0" in captured.get("vf", ""), captured


def test_sprite_still_fine_for_a_short_clip(clip: Path, tmp_path: Path):
    dest = tmp_path / "sprite_short.jpg"
    ffmpeg_tools.build_sprite(clip, dest, duration_s=2.0)
    assert dest.is_file() and dest.stat().st_size > 0


def test_nvenc_encode_failure_falls_back_to_cpu(clip: Path, tmp_path: Path, monkeypatch):
    """The GPU encoder can fail OUTRIGHT under concurrency, not just produce
    bad output. On the real archive several large files errored this way while
    encoding fine in isolation. A hardware-encoder failure must fall back to
    libx264, not fail the video.
    """
    calls = []
    real_run = ffmpeg_tools.subprocess.run

    def fake_run(cmd, *a, **kw):
        if isinstance(cmd, list) and "h264_nvenc" in cmd:
            calls.append("nvenc")
            return subprocess.CompletedProcess(cmd, 1, "", "OpenEncodeSessionEx failed")
        if isinstance(cmd, list) and "libx264" in cmd:
            calls.append("libx264")
        return real_run(cmd, *a, **kw)

    monkeypatch.setattr(ffmpeg_tools.subprocess, "run", fake_run)
    dest = tmp_path / "p.mp4"
    ffmpeg_tools.build_proxy(clip, dest, use_nvenc=True)

    assert calls[:2] == ["nvenc", "libx264"], calls
    assert dest.is_file() and dest.stat().st_size > 0


def test_cpu_encode_failure_is_fatal(clip: Path, tmp_path: Path, monkeypatch):
    """If libx264 itself fails there is nothing left to try — surface it."""
    def fake_run(cmd, *a, **kw):
        return subprocess.CompletedProcess(cmd, 1, "", "disk full")

    monkeypatch.setattr(ffmpeg_tools.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="libx264"):
        ffmpeg_tools.build_proxy(clip, tmp_path / "p.mp4", use_nvenc=False)


def test_encode_error_includes_ffmpeg_stderr(clip: Path, tmp_path: Path, monkeypatch):
    """A CalledProcessError carries only the command line, which says nothing
    about WHY ffmpeg refused — that cost a diagnosis cycle on the archive."""
    def fake_run(cmd, *a, **kw):
        return subprocess.CompletedProcess(cmd, 1, "", "No space left on device")

    monkeypatch.setattr(ffmpeg_tools.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="No space left on device"):
        ffmpeg_tools.build_proxy(clip, tmp_path / "p.mp4", use_nvenc=False)
