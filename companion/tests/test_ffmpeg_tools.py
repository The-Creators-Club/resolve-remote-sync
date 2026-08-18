"""ffmpeg_tools tests — the flag spec, in writing.

No test here runs a real ffmpeg or ffprobe. Everything that would spawn is
monkeypatched at `ffmpeg_tools.subprocess`, for the same reason conftest
blocks real Tk windows: the developer's box HAS an ffmpeg on PATH, so a test
that "accidentally works" locally would be the one that encodes a 4 GB clip on
somebody else's machine.

The argv assertions are the point of the module. `preview_proxy_cmd` in
particular is compared against a LITERAL flag subsequence copied from
broll/indexer/broll_index/ffmpeg_tools.py's build_proxy — the two pipelines
have to emit interchangeable files, so drift needs to fail here rather than be
discovered as a b-roll preview that doesn't match its neighbours.
"""

from __future__ import annotations

import json

import pytest

from ccsync_companion import ffmpeg_tools as ft


@pytest.fixture(autouse=True)
def _clean_module_caches():
    """Both caches are process-global (a dict behind a lock), so without this
    a probe result from one test answers another test's question — the same
    class of hazard as conftest's resolve_bridge session reset."""
    ft.reset_ffmpeg_available_cache()
    ft.reset_encoder_cache()
    yield
    ft.reset_ffmpeg_available_cache()
    ft.reset_encoder_cache()


class _FakeCompletedProcess:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _sub(argv: list[str], needle: list[str]) -> bool:
    """Is `needle` a contiguous subsequence of `argv`?"""
    n = len(needle)
    return any(argv[i:i + n] == needle for i in range(len(argv) - n + 1))


def _after(argv: list[str], flag: str) -> str:
    return argv[argv.index(flag) + 1]


# ---------------------------------------------------------------------------
# own_proxy_cmd — the own-footage tier
# ---------------------------------------------------------------------------

def test_own_proxy_nvenc_is_hevc_main10_ten_bit():
    cmd = ft.own_proxy_cmd("ffmpeg", "in.mov", "out.mp4", nvenc=True)

    assert _sub(cmd, ["-c:v", "hevc_nvenc"])
    assert _sub(cmd, ["-profile:v", "main10"])
    assert _sub(cmd, ["-pix_fmt", "p010le"])
    assert _sub(cmd, ["-preset", "p5"])
    assert _sub(cmd, ["-rc", "vbr"])
    assert "libx265" not in cmd


def test_own_proxy_cpu_path_is_libx265_ten_bit():
    cmd = ft.own_proxy_cmd("ffmpeg", "in.mov", "out.mp4", nvenc=False)

    assert _sub(cmd, ["-c:v", "libx265"])
    assert _sub(cmd, ["-pix_fmt", "yuv420p10le"])
    assert _sub(cmd, ["-preset", "medium"])
    assert _sub(cmd, ["-x265-params", "log-level=error"])
    assert "hevc_nvenc" not in cmd
    # NVENC-only rate-control flag: passing -rc to libx265 is an error.
    assert "-rc" not in cmd


@pytest.mark.parametrize("nvenc", [True, False])
def test_own_proxy_always_tags_hvc1(nvenc):
    """QuickTime and Resolve refuse HEVC-in-mp4 tagged `hev1`; the file still
    plays in VLC, which is how a missing tag survives to an editor's timeline
    as Media Offline."""
    cmd = ft.own_proxy_cmd("ffmpeg", "in.mov", "out.mp4", nvenc=nvenc)

    assert _sub(cmd, ["-tag:v", "hvc1"])


@pytest.mark.parametrize("nvenc", [True, False])
def test_own_proxy_never_upscales(nvenc):
    cmd = ft.own_proxy_cmd("ffmpeg", "in.mov", "out.mp4", nvenc=nvenc)

    assert _after(cmd, "-vf") == "scale=-2:'trunc(min(1080,ih)/2)*2'"


def test_own_proxy_honours_a_custom_height():
    cmd = ft.own_proxy_cmd("ffmpeg", "in.mov", "out.mp4", nvenc=True, max_height=720)

    assert _after(cmd, "-vf") == "scale=-2:'trunc(min(720,ih)/2)*2'"


@pytest.mark.parametrize("height", [1080, 720, 540])
def test_the_scale_filter_rounds_the_height_down_to_even(height):
    """MED-12: `-2` guards the WIDTH only. An odd-height source (RGB/4:4:4
    screen capture, ffv1/utvideo) passed its height straight through and died
    at encoder init with EINVAL -- before a single frame -- which three passes
    later turned into a permanent cap on the clip. Verified against real
    ffmpeg 2026-08-11: 640x481 ffv1 fails with the old filter, encodes to
    638x480 with this one."""
    own = ft.own_proxy_cmd("ffmpeg", "in.mov", "out.mp4", nvenc=False,
                           max_height=height)
    preview = ft.preview_proxy_cmd("ffmpeg", "in.mp4", "out.mp4", nvenc=False,
                                   height=height)

    for cmd in (own, preview):
        assert _after(cmd, "-vf") == f"scale=-2:'trunc(min({height},ih)/2)*2'"


@pytest.mark.parametrize("nvenc", [True, False])
def test_own_proxy_keeps_every_audio_track(nvenc):
    """MED-1: with no -map, ffmpeg's default selection takes exactly ONE audio
    stream, and camera originals here routinely carry two or more (Sony/Canon
    MXF dual pairs, dual-system, .mts). The editor then cuts on a proxy whose
    scratch/lav track does not exist and only reappears on the original."""
    cmd = ft.own_proxy_cmd("ffmpeg", "in.mov", "out.mp4", nvenc=nvenc)

    assert _sub(cmd, ["-map", "0:v:0"])
    # '?' -- optional: a silent original must still encode.
    assert _sub(cmd, ["-map", "0:a?"])
    # As INPUT-ordered output options: after -i, before the destination.
    assert cmd.index("-i") < cmd.index("-map") < len(cmd) - 1


def test_the_preview_tier_keeps_the_indexers_default_stream_selection():
    """Deliberately NOT given MED-1's -map flags: this tier's output is meant
    to be interchangeable with one the b-roll indexer produced, and its inputs
    are YouTube downloads with one audio track."""
    cmd = ft.preview_proxy_cmd("ffmpeg", "in.mp4", "out.mp4", nvenc=True)

    assert "-map" not in cmd


def test_own_proxy_carries_the_source_timecode_when_there_is_one():
    """The ship-blocker: LinkProxyMedia refuses on a timecode mismatch."""
    cmd = ft.own_proxy_cmd(
        "ffmpeg", "in.mov", "out.mp4", nvenc=True, timecode="01:00:00:00"
    )

    assert _sub(cmd, ["-timecode", "01:00:00:00"])
    # ...as an OUTPUT option: after the input, before the destination.
    assert cmd.index("-i") < cmd.index("-timecode") < len(cmd) - 1
    assert _sub(cmd, ["-map_metadata", "0"])


@pytest.mark.parametrize("timecode", [None, ""])
def test_own_proxy_omits_timecode_when_the_source_has_none(timecode):
    """Writing 00:00:00:00 onto a source that claims no timecode is a
    mismatch of its own, not a safe default."""
    cmd = ft.own_proxy_cmd("ffmpeg", "in.mov", "out.mp4", nvenc=True, timecode=timecode)

    assert "-timecode" not in cmd


@pytest.mark.parametrize("nvenc", [True, False])
def test_own_proxy_default_bitrate_and_derived_headroom(nvenc):
    cmd = ft.own_proxy_cmd("ffmpeg", "in.mov", "out.mp4", nvenc=nvenc)

    assert _sub(cmd, ["-b:v", "7M"])
    assert _sub(cmd, ["-maxrate", "10M"])
    assert _sub(cmd, ["-bufsize", "14M"])


def test_own_proxy_headroom_follows_a_custom_bitrate():
    """A 20M target with a 10M ceiling would clamp every busy frame silently,
    so the three numbers move together."""
    cmd = ft.own_proxy_cmd("ffmpeg", "in.mov", "out.mp4", nvenc=True, bitrate="20M")

    assert _sub(cmd, ["-b:v", "20M"])
    assert _sub(cmd, ["-maxrate", "29M"])
    assert _sub(cmd, ["-bufsize", "40M"])


def test_own_proxy_unparseable_bitrate_degrades_to_a_conservative_encode():
    """A typo in config.toml must not produce an argv ffmpeg rejects — the
    generator would then fail every clip forever."""
    cmd = ft.own_proxy_cmd("ffmpeg", "in.mov", "out.mp4", nvenc=True, bitrate="seven")

    assert _sub(cmd, ["-b:v", "seven"])
    assert _sub(cmd, ["-maxrate", "seven"])
    assert _sub(cmd, ["-bufsize", "seven"])


def test_own_proxy_audio_container_and_paths():
    cmd = ft.own_proxy_cmd("C:/tools/ffmpeg.exe", "in.mov", "out.mp4", nvenc=True)

    assert cmd[0] == "C:/tools/ffmpeg.exe"
    assert cmd[1:6] == ["-y", "-hide_banner", "-loglevel", "error", "-nostats"]
    assert _sub(cmd, ["-i", "in.mov"])
    assert _sub(cmd, ["-c:a", "aac", "-b:a", "192k"])
    assert _sub(cmd, ["-movflags", "+faststart"])
    assert cmd[-1] == "out.mp4"


@pytest.mark.parametrize("builder", ["own", "preview"])
@pytest.mark.parametrize("nvenc", [True, False])
def test_proxy_cmds_force_the_mp4_muxer(builder, nvenc):
    """The real destination is `<name>.mp4.partial`, and ffmpeg picks the
    muxer from the extension: without an explicit `-f mp4` every encode fails
    at muxer init (EINVAL) before one frame — which is how the base rig made
    zero of 1040 queued proxies overnight, 2026-08-11."""
    if builder == "own":
        cmd = ft.own_proxy_cmd("ffmpeg", "in.mov", "out.mp4.partial", nvenc=nvenc)
    else:
        cmd = ft.preview_proxy_cmd("ffmpeg", "in.mp4", "out.mp4.partial", nvenc=nvenc)

    # As an OUTPUT option: after the input, immediately before the destination.
    assert cmd[-3:] == ["-f", "mp4", "out.mp4.partial"]
    assert cmd.index("-f") > cmd.index("-i")


def test_own_proxy_stringifies_path_objects():
    from pathlib import Path

    cmd = ft.own_proxy_cmd("ffmpeg", Path("in.mov"), Path("out.mp4"), nvenc=True)

    assert all(isinstance(part, str) for part in cmd)


# ---------------------------------------------------------------------------
# preview_proxy_cmd — the b-roll spec, verbatim
# ---------------------------------------------------------------------------

# Copied by hand from broll/indexer/broll_index/ffmpeg_tools.py build_proxy
# (:180-194). If a change here is intentional, the b-roll indexer has to make
# the same change — otherwise the two pipelines produce different files for
# the same YouTube download, which is exactly what this tier exists to avoid.
# `-f mp4` is the one deliberate divergence (no output byte differs): the
# indexer writes to `<name>.mp4`, the generator to `<name>.mp4.partial`, and
# ffmpeg cannot choose a muxer from ".partial" (2026-08-11).
BROLL_NVENC_TAIL = [
    "-vf", "scale=-2:'trunc(min(540,ih)/2)*2'",
    "-c:v", "h264_nvenc", "-preset", "p4", "-cq", "34",
    "-pix_fmt", "yuv420p",
    "-c:a", "aac", "-b:a", "96k",
    "-movflags", "+faststart",
    "-f", "mp4",
]
BROLL_CPU_TAIL = [
    "-vf", "scale=-2:'trunc(min(540,ih)/2)*2'",
    "-c:v", "libx264", "-preset", "veryfast", "-crf", "30",
    "-pix_fmt", "yuv420p",
    "-c:a", "aac", "-b:a", "96k",
    "-movflags", "+faststart",
    "-f", "mp4",
]


def test_preview_proxy_nvenc_argv_matches_the_broll_spec_literally():
    cmd = ft.preview_proxy_cmd("ffmpeg", "in.mp4", "out.mp4", nvenc=True)

    assert cmd == [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", "in.mp4",
        *BROLL_NVENC_TAIL,
        "out.mp4",
    ]


def test_preview_proxy_cpu_argv_matches_the_broll_spec_literally():
    cmd = ft.preview_proxy_cmd("ffmpeg", "in.mp4", "out.mp4", nvenc=False)

    assert cmd == [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", "in.mp4",
        *BROLL_CPU_TAIL,
        "out.mp4",
    ]


def test_preview_proxy_constants_are_the_measured_ones():
    """540p/cq34 was measured ~3.7x smaller than 720p/cq26 on real archive
    footage; the comment above these constants is the justification."""
    assert (ft.PROXY_HEIGHT, ft.PROXY_CQ, ft.PROXY_CRF) == (540, 34, 30)
    assert ft.PROXY_AUDIO_BITRATE == "96k"


def test_preview_proxy_carries_no_metadata_flags_and_no_timecode_by_default():
    """The YouTube tier passes no timecode (a download has none) and must not
    invent one -- a proxy claiming 00:00:00:00 against a source that claims
    nothing is a mismatch of its own."""
    cmd = ft.preview_proxy_cmd("ffmpeg", "in.mp4", "out.mp4", nvenc=True)

    assert "-timecode" not in cmd
    assert "-map_metadata" not in cmd
    assert "-tag:v" not in cmd


def test_preview_proxy_carries_the_timecode_when_the_ingest_path_passes_one():
    """b-roll INGEST encodes camera originals, which DO carry a start
    timecode, and Resolve's LinkProxyMedia refuses a proxy that lost it (R10).
    Same flag, same place, as the indexer's build_proxy puts it: after
    -pix_fmt, before the audio codec."""
    cmd = ft.preview_proxy_cmd("ffmpeg", "in.mov", "out.mp4", nvenc=False,
                               timecode="03:40:27;12")

    assert _sub(cmd, ["-timecode", "03:40:27;12"])
    assert cmd.index("-pix_fmt") < cmd.index("-timecode") < cmd.index("-c:a")


@pytest.mark.parametrize("nvenc", [True, False])
def test_preview_proxy_pins_8bit_420_like_the_indexer_does(nvenc):
    """Without it libx264 inherits the source's pixel format, and our own
    shoots are 10-bit (FX3/FX30 XAVC): every preview from a 10-bit source came
    back a black rectangle in the editors' browsers (indexer, 2026-08-11).
    The companion's copy of this argv shipped without the flag until
    2026-08-18, so the two pipelines produced different files for the same
    10-bit input."""
    cmd = ft.preview_proxy_cmd("ffmpeg", "in.mp4", "out.mp4", nvenc=nvenc)

    assert _sub(cmd, ["-pix_fmt", "yuv420p"])
    # An OUTPUT option: after the encoder is chosen, before the audio codec.
    assert cmd.index("-c:v") < cmd.index("-pix_fmt") < cmd.index("-c:a")


def test_preview_proxy_quality_overrides_reach_the_argv():
    nv = ft.preview_proxy_cmd("ffmpeg", "a", "b", nvenc=True, height=360, cq=28)
    cpu = ft.preview_proxy_cmd("ffmpeg", "a", "b", nvenc=False, height=360, crf=22)

    assert _after(nv, "-vf") == "scale=-2:'trunc(min(360,ih)/2)*2'"
    assert _sub(nv, ["-cq", "28"])
    assert _sub(cpu, ["-crf", "22"])


# ---------------------------------------------------------------------------
# verify_decodes_cmd / count_decode_errors
# ---------------------------------------------------------------------------

def test_verify_decodes_cmd_is_a_null_decode():
    cmd = ft.verify_decodes_cmd("C:/tools/ffmpeg.exe", "out.mp4")

    assert cmd == [
        "C:/tools/ffmpeg.exe", "-v", "error", "-i", "out.mp4", "-f", "null", "-",
    ]


def test_count_decode_errors_counts_real_lines():
    stderr = (
        "[h264 @ 000] Invalid NAL unit size (1234 > 56).\n"
        "[h264 @ 000] Error splitting the input into NAL units.\n"
    )

    assert ft.count_decode_errors(stderr) == 2


@pytest.mark.parametrize("text", [None, "", "\n", "  \n\t\n", "\r\n"])
def test_count_decode_errors_is_blank_line_tolerant(text):
    """A clean decode prints nothing; a trailing newline read as one error
    would condemn every good proxy the generator makes."""
    assert ft.count_decode_errors(text) == 0


# ---------------------------------------------------------------------------
# ffmpeg_available
# ---------------------------------------------------------------------------

def test_ffmpeg_available_missing_on_path(monkeypatch):
    monkeypatch.setattr(ft.shutil, "which", lambda name: None)

    ok, msg = ft.ffmpeg_available("ffmpeg")

    assert ok is False
    assert "not found on PATH" in msg


def test_ffmpeg_available_missing_absolute_path(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("must not spawn anything for a path that isn't there")

    monkeypatch.setattr(ft.subprocess, "run", boom)

    ok, msg = ft.ffmpeg_available(str(tmp_path / "nope" / "ffmpeg.exe"))

    assert ok is False
    assert "not found at" in msg


def test_ffmpeg_available_probes_with_utf8_and_no_console_window(monkeypatch, tmp_path):
    """ffmpeg's banner is UTF-8 (build strings carry non-ASCII names) and the
    default cp1252 decode raises on it — the S-6 shape. CREATE_NO_WINDOW keeps
    the windowed build from flashing a console per probe."""
    exe = tmp_path / "ffmpeg.exe"
    exe.write_text("stub")
    captured: dict = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured.update(kwargs)
        return _FakeCompletedProcess(0)

    monkeypatch.setattr(ft.subprocess, "run", fake_run)

    ok, resolved = ft.ffmpeg_available(str(exe))

    assert ok is True
    assert resolved == str(exe)
    assert captured["cmd"] == [str(exe), "-version"]
    assert captured["timeout"] == 10
    assert captured["encoding"] == "utf-8"
    assert captured["errors"] == "replace"
    if ft.sys.platform == "win32":
        assert captured["creationflags"] == ft.subprocess.CREATE_NO_WINDOW
    else:
        assert captured["creationflags"] == 0


def test_ffmpeg_available_nonzero_exit_is_unavailable(monkeypatch, tmp_path):
    exe = tmp_path / "ffmpeg.exe"
    exe.write_text("stub")
    monkeypatch.setattr(
        ft.subprocess, "run", lambda cmd, **k: _FakeCompletedProcess(9)
    )

    ok, msg = ft.ffmpeg_available(str(exe))

    assert ok is False
    assert "exited 9" in msg


def test_ffmpeg_available_never_raises(monkeypatch, tmp_path):
    """Callers include the tray snapshot and the reporter tick; neither has a
    handler for a throw from a availability question."""
    exe = tmp_path / "ffmpeg.exe"
    exe.write_text("stub")

    def boom(cmd, **kwargs):
        raise OSError("[WinError 1455] the paging file is too small")

    monkeypatch.setattr(ft.subprocess, "run", boom)

    ok, msg = ft.ffmpeg_available(str(exe))

    assert ok is False
    assert "failed to run" in msg
    assert "paging file" in msg


def test_ffmpeg_available_caches_successes_for_the_ttl(monkeypatch, tmp_path):
    exe = tmp_path / "ffmpeg.exe"
    exe.write_text("stub")
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return _FakeCompletedProcess(0)

    monkeypatch.setattr(ft.subprocess, "run", fake_run)
    clock = [1000.0]
    monkeypatch.setattr(ft.time, "monotonic", lambda: clock[0])

    assert ft.ffmpeg_available(str(exe))[0] is True
    clock[0] += ft.FFMPEG_PROBE_TTL_SECONDS - 1
    assert ft.ffmpeg_available(str(exe))[0] is True
    assert len(calls) == 1, "a cached success re-spawned ffmpeg"

    clock[0] += 2  # now past the TTL
    assert ft.ffmpeg_available(str(exe))[0] is True
    assert len(calls) == 2


def test_ffmpeg_available_does_not_cache_failures(monkeypatch, tmp_path):
    """A missing or broken ffmpeg must be re-probed every time, so the
    generator starts working the instant it is installed — no restart."""
    exe = tmp_path / "ffmpeg.exe"
    exe.write_text("stub")
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return _FakeCompletedProcess(1)

    monkeypatch.setattr(ft.subprocess, "run", fake_run)

    assert ft.ffmpeg_available(str(exe))[0] is False
    assert ft.ffmpeg_available(str(exe))[0] is False
    assert len(calls) == 2


def test_reset_ffmpeg_available_cache_forces_a_reprobe(monkeypatch, tmp_path):
    exe = tmp_path / "ffmpeg.exe"
    exe.write_text("stub")
    calls: list[list[str]] = []
    monkeypatch.setattr(
        ft.subprocess, "run",
        lambda cmd, **k: (calls.append(cmd), _FakeCompletedProcess(0))[1],
    )

    ft.ffmpeg_available(str(exe))
    ft.reset_ffmpeg_available_cache()
    ft.ffmpeg_available(str(exe))

    assert len(calls) == 2


def test_ffmpeg_available_use_cache_false_bypasses_the_cache(monkeypatch, tmp_path):
    exe = tmp_path / "ffmpeg.exe"
    exe.write_text("stub")
    calls: list[list[str]] = []
    monkeypatch.setattr(
        ft.subprocess, "run",
        lambda cmd, **k: (calls.append(cmd), _FakeCompletedProcess(0))[1],
    )

    ft.ffmpeg_available(str(exe))
    ft.ffmpeg_available(str(exe), use_cache=False)

    assert len(calls) == 2


# ---------------------------------------------------------------------------
# ffprobe_for
# ---------------------------------------------------------------------------

def test_ffprobe_for_picks_the_sibling_keeping_the_suffix(tmp_path):
    (tmp_path / "ffmpeg.exe").write_text("stub")
    (tmp_path / "ffprobe.exe").write_text("stub")

    assert ft.ffprobe_for(str(tmp_path / "ffmpeg.exe")) == str(tmp_path / "ffprobe.exe")


def test_ffprobe_for_falls_back_to_the_bare_name(tmp_path, monkeypatch):
    """An ffmpeg with no sibling ffprobe (or none we can find) still gets a
    usable argv — PATH is the last resort, not an error."""
    monkeypatch.setattr(ft.shutil, "which", lambda name: None)
    exe = tmp_path / "ffmpeg.exe"
    exe.write_text("stub")

    assert ft.ffprobe_for("ffmpeg") == "ffprobe"
    assert ft.ffprobe_for(str(exe)) == "ffprobe"


def test_ffprobe_for_resolves_a_bare_name_through_path(tmp_path, monkeypatch):
    (tmp_path / "ffmpeg").write_text("stub")
    (tmp_path / "ffprobe").write_text("stub")
    monkeypatch.setattr(ft.shutil, "which", lambda name: str(tmp_path / "ffmpeg"))

    assert ft.ffprobe_for("ffmpeg") == str(tmp_path / "ffprobe")


# ---------------------------------------------------------------------------
# detect_encoders
# ---------------------------------------------------------------------------

# Trimmed from a real `ffmpeg -hide_banner -encoders` listing.
ENCODERS_OUTPUT = """Encoders:
 V..... = Video
 ------
 V....D h264_nvenc           NVIDIA NVENC H.264 encoder (codec h264)
 V....D hevc_nvenc           NVIDIA NVENC hevc encoder (codec hevc)
 V....D libx264              libx264 H.264 / AVC / MPEG-4 AVC (codec h264)
 V....D libx265              libx265 H.265 / HEVC (codec hevc)
 A....D aac                  AAC (Advanced Audio Coding)
"""

ENCODERS_OUTPUT_NO_GPU = """Encoders:
 V....D libx264              libx264 H.264 / AVC / MPEG-4 AVC (codec h264)
 V....D libx265              libx265 H.265 / HEVC (codec hevc)
"""


def test_detect_encoders_parses_the_listing(monkeypatch):
    captured: dict = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured.update(kwargs)
        return _FakeCompletedProcess(0, stdout=ENCODERS_OUTPUT)

    monkeypatch.setattr(ft.subprocess, "run", fake_run)

    found = ft.detect_encoders("ffmpeg")

    assert found == frozenset({"h264_nvenc", "hevc_nvenc", "libx264", "libx265"})
    assert captured["cmd"] == ["ffmpeg", "-hide_banner", "-encoders"]
    assert captured["encoding"] == "utf-8"


def test_detect_encoders_on_a_gpu_less_build(monkeypatch):
    monkeypatch.setattr(
        ft.subprocess, "run",
        lambda cmd, **k: _FakeCompletedProcess(0, stdout=ENCODERS_OUTPUT_NO_GPU),
    )

    found = ft.detect_encoders("ffmpeg")

    assert "hevc_nvenc" not in found
    assert "h264_nvenc" not in found
    assert {"libx264", "libx265"} <= found


def test_detect_encoders_caches_per_path(monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.setattr(
        ft.subprocess, "run",
        lambda cmd, **k: (
            calls.append(cmd), _FakeCompletedProcess(0, stdout=ENCODERS_OUTPUT)
        )[1],
    )

    ft.detect_encoders("ffmpeg")
    ft.detect_encoders("ffmpeg")
    ft.detect_encoders("C:/tools/ffmpeg.exe")

    assert len(calls) == 2, "the encoder list was re-probed for a path already seen"


@pytest.mark.parametrize(
    "outcome",
    [
        lambda cmd, **k: _FakeCompletedProcess(1, stderr="Unrecognized option"),
        lambda cmd, **k: (_ for _ in ()).throw(FileNotFoundError("no ffmpeg")),
        lambda cmd, **k: (_ for _ in ()).throw(
            ft.subprocess.TimeoutExpired("ffmpeg", 20)
        ),
    ],
)
def test_detect_encoders_returns_empty_on_any_failure(monkeypatch, outcome):
    monkeypatch.setattr(ft.subprocess, "run", outcome)

    assert ft.detect_encoders("ffmpeg") == frozenset()


def test_detect_encoders_does_not_cache_a_failure(monkeypatch):
    """A network-drive blip must not pin the generator to the CPU path for the
    life of the process."""
    calls: list[list[str]] = []

    def flaky(cmd, **kwargs):
        calls.append(cmd)
        if len(calls) == 1:
            raise OSError("drive not ready")
        return _FakeCompletedProcess(0, stdout=ENCODERS_OUTPUT)

    monkeypatch.setattr(ft.subprocess, "run", flaky)

    assert ft.detect_encoders("ffmpeg") == frozenset()
    assert "hevc_nvenc" in ft.detect_encoders("ffmpeg")


def test_reset_encoder_cache_forces_a_reprobe(monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.setattr(
        ft.subprocess, "run",
        lambda cmd, **k: (
            calls.append(cmd), _FakeCompletedProcess(0, stdout=ENCODERS_OUTPUT)
        )[1],
    )

    ft.detect_encoders("ffmpeg")
    ft.reset_encoder_cache()
    ft.detect_encoders("ffmpeg")

    assert len(calls) == 2


# ---------------------------------------------------------------------------
# probe_video
# ---------------------------------------------------------------------------

def _probe_json(*, fmt_tags=None, streams=None, duration="12.5"):
    fmt: dict = {"duration": duration}
    if fmt_tags is not None:
        fmt["tags"] = fmt_tags
    return json.dumps({
        "format": fmt,
        "streams": streams if streams is not None else [_video_stream(), _audio_stream()],
    })


def _video_stream(**over):
    stream = {
        "codec_type": "video",
        "codec_name": "hevc",
        "width": 3840,
        "height": 2160,
        "avg_frame_rate": "24000/1001",
        "r_frame_rate": "24000/1001",
    }
    stream.update(over)
    return stream


def _audio_stream(**over):
    stream = {"codec_type": "audio", "codec_name": "pcm_s24le", "channels": 2}
    stream.update(over)
    return stream


def _patch_probe(monkeypatch, *, stdout="", returncode=0, stderr="", capture=None):
    def fake_run(cmd, **kwargs):
        if capture is not None:
            capture["cmd"] = cmd
            capture.update(kwargs)
        return _FakeCompletedProcess(returncode, stdout=stdout, stderr=stderr)

    monkeypatch.setattr(ft.subprocess, "run", fake_run)


def test_probe_video_reads_the_facts(monkeypatch):
    captured: dict = {}
    _patch_probe(monkeypatch, stdout=_probe_json(), capture=captured)

    info = ft.probe_video("ffmpeg", "A001.mov")

    assert info["duration_s"] == pytest.approx(12.5)
    assert info["fps"] == pytest.approx(23.976, abs=0.001)
    assert (info["width"], info["height"]) == (3840, 2160)
    assert info["codec"] == "hevc"
    assert info["has_audio"] is True
    assert info["audio_channels"] == 2
    assert info["timecode"] is None
    assert captured["cmd"][1:] == [
        "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", "A001.mov",
    ]
    assert captured["timeout"] == ft.PROBE_TIMEOUT_SECONDS


def test_probe_video_takes_the_container_timecode(monkeypatch):
    _patch_probe(
        monkeypatch,
        stdout=_probe_json(fmt_tags={"timecode": "10:00:00:00", "encoder": "x"}),
    )

    assert ft.probe_video("ffmpeg", "A001.mov")["timecode"] == "10:00:00:00"


def test_probe_video_falls_back_to_a_tmcd_stream_timecode(monkeypatch):
    """MXF and most camera formats carry a timecode TRACK rather than a
    container tag; without this fallback those clips would get a proxy with no
    timecode and LinkProxyMedia would refuse it."""
    _patch_probe(monkeypatch, stdout=_probe_json(
        fmt_tags={"encoder": "x"},
        streams=[
            _video_stream(),
            _audio_stream(),
            {
                "codec_type": "data",
                "codec_tag_string": "tmcd",
                "tags": {"timecode": "01:23:45:12"},
            },
        ],
    ))

    assert ft.probe_video("ffmpeg", "A001.mxf")["timecode"] == "01:23:45:12"


def test_probe_video_prefers_the_container_timecode_over_the_stream(monkeypatch):
    _patch_probe(monkeypatch, stdout=_probe_json(
        fmt_tags={"timecode": "10:00:00:00"},
        streams=[
            _video_stream(),
            {"codec_type": "data", "codec_tag_string": "tmcd",
             "tags": {"timecode": "01:23:45:12"}},
        ],
    ))

    assert ft.probe_video("ffmpeg", "A001.mov")["timecode"] == "10:00:00:00"


def test_probe_video_no_timecode_anywhere_is_none_not_zero(monkeypatch):
    """A YouTube download legitimately has none; None is the answer that makes
    own_proxy_cmd omit -timecode."""
    _patch_probe(monkeypatch, stdout=_probe_json(
        fmt_tags={"encoder": "Lavf"},
        streams=[_video_stream(codec_name="h264"), _audio_stream(codec_name="aac")],
    ))

    assert ft.probe_video("ffmpeg", "download.mp4")["timecode"] is None


def test_dropframe_normalization():
    """Sony rtmd tags print colon (non-drop) forms for drop-frame material;
    at NTSC rates the colon reading is a different absolute frame and Resolve
    refuses the pairing (measured live 2026-08-12: colon refused, semicolon
    accepted, same bytes otherwise).

    Copied from broll/indexer/tests/test_ffmpeg_tools.py:156 on purpose
    (COMP-MEDIA-1, 2026-08-14): R10's fix landed only on the indexer's copy of
    this module for two days, and the two must not drift again."""
    f = ft.dropframe_normalized
    assert f("03:40:27:12", 59.94) == "03:40:27;12"
    assert f("03:40:27:12", 29.97) == "03:40:27;12"
    # Already drop-form, integer rates, 23.976 (no DF variant), and unknown
    # fps all pass through untouched.
    assert f("03:40:27;12", 59.94) == "03:40:27;12"
    assert f("03:40:27:12", 25.0) == "03:40:27:12"
    assert f("03:40:27:12", 23.976) == "03:40:27:12"
    assert f("03:40:27:12", None) == "03:40:27:12"
    assert f(None, 59.94) is None


@pytest.mark.parametrize("rate", ["60000/1001", "30000/1001"])
def test_probe_video_normalizes_a_drop_frame_timecode(monkeypatch, rate):
    """The COMP-MEDIA-1 failure, end to end: an FX3/FX6 clip at 59.94 DF whose
    tag prints with colons. own_proxy_cmd writes probe_video's answer straight
    into `-timecode`, so a verbatim tag is a proxy that claims non-drop against
    a drop-frame original -- and Resolve refuses every attach of it."""
    _patch_probe(monkeypatch, stdout=_probe_json(
        fmt_tags={"timecode": "03:40:27:12"},
        streams=[_video_stream(avg_frame_rate=rate, r_frame_rate=rate),
                 _audio_stream()],
    ))

    info = ft.probe_video("ffmpeg", "C0001.MP4")

    assert info["timecode"] == "03:40:27;12"
    assert _sub(
        ft.own_proxy_cmd("ffmpeg", "C0001.MP4", "out.mp4.partial", nvenc=True,
                         timecode=info["timecode"]),
        ["-timecode", "03:40:27;12"],
    )


def test_probe_video_leaves_a_non_ntsc_timecode_alone(monkeypatch):
    """25p is never drop-frame: normalizing there would break the pairing this
    exists to keep."""
    _patch_probe(monkeypatch, stdout=_probe_json(
        fmt_tags={"timecode": "03:40:27:12"},
        streams=[_video_stream(avg_frame_rate="25/1", r_frame_rate="25/1")],
    ))

    assert ft.probe_video("ffmpeg", "A001.mxf")["timecode"] == "03:40:27:12"


def test_probe_video_normalizes_a_tmcd_stream_timecode_too(monkeypatch):
    """The rtmd/tmcd TRACK is where Sony actually writes it -- the fallback
    path has to be normalized or the fix misses the cameras it is for."""
    _patch_probe(monkeypatch, stdout=_probe_json(
        fmt_tags={"encoder": "x"},
        streams=[
            _video_stream(avg_frame_rate="30000/1001", r_frame_rate="30000/1001"),
            {"codec_type": "data", "codec_tag_string": "tmcd",
             "tags": {"timecode": "01:23:45:12"}},
        ],
    ))

    assert ft.probe_video("ffmpeg", "A001.mxf")["timecode"] == "01:23:45;12"


def test_probe_video_tolerates_a_null_tags_object(monkeypatch):
    _patch_probe(monkeypatch, stdout=json.dumps({
        "format": {"duration": "3.0", "tags": None},
        "streams": [_video_stream(tags=None)],
    }))

    info = ft.probe_video("ffmpeg", "a.mov")

    assert info["timecode"] is None
    assert info["has_audio"] is False
    assert info["audio_channels"] is None


def test_probe_video_falls_back_to_the_stream_duration(monkeypatch):
    _patch_probe(monkeypatch, stdout=json.dumps({
        "format": {},
        "streams": [_video_stream(duration="7.25")],
    }))

    assert ft.probe_video("ffmpeg", "a.mov")["duration_s"] == pytest.approx(7.25)


def test_probe_video_survives_a_missing_duration(monkeypatch):
    """Growing files and some dashcam recordings report none; the generator
    just loses its stuck-encode ceiling estimate for that clip."""
    _patch_probe(monkeypatch, stdout=json.dumps({
        "format": {}, "streams": [_video_stream(avg_frame_rate="0/0")],
    }))

    info = ft.probe_video("ffmpeg", "a.mov")

    assert info["duration_s"] is None
    assert info["fps"] == pytest.approx(23.976, abs=0.001)  # from r_frame_rate


def test_probe_video_raises_on_a_truncated_download(monkeypatch):
    _patch_probe(
        monkeypatch, returncode=1,
        stderr="a.mp4: moov atom not found\n",
    )

    with pytest.raises(ft.UnreadableMediaError) as excinfo:
        ft.probe_video("ffmpeg", "a.mp4")

    assert "truncated or incompletely downloaded" in str(excinfo.value)


def test_probe_video_raises_on_invalid_data(monkeypatch):
    _patch_probe(monkeypatch, returncode=1, stderr="Invalid data found when processing input")

    with pytest.raises(ft.UnreadableMediaError) as excinfo:
        ft.probe_video("ffmpeg", "a.mp4")

    assert "not valid media" in str(excinfo.value)


def test_probe_video_raises_when_there_is_no_video_stream(monkeypatch):
    _patch_probe(monkeypatch, stdout=json.dumps({
        "format": {"duration": "60.0"}, "streams": [_audio_stream()],
    }))

    with pytest.raises(ft.UnreadableMediaError) as excinfo:
        ft.probe_video("ffmpeg", "voiceover.wav")

    assert "no video stream" in str(excinfo.value)


def test_probe_video_raises_on_non_json_output(monkeypatch):
    _patch_probe(monkeypatch, stdout="not json at all")

    with pytest.raises(ft.UnreadableMediaError):
        ft.probe_video("ffmpeg", "a.mov")


def test_probe_video_wraps_a_missing_ffprobe(monkeypatch):
    """Subprocess plumbing failures arrive as UnreadableMediaError too —
    proxy_gen has one response to "this clip can't be probed"."""
    def boom(cmd, **kwargs):
        raise FileNotFoundError(2, "The system cannot find the file specified")

    monkeypatch.setattr(ft.subprocess, "run", boom)

    with pytest.raises(ft.UnreadableMediaError) as excinfo:
        ft.probe_video("ffmpeg", "a.mov")

    assert "could not be run" in str(excinfo.value)


def test_probe_video_wraps_a_timeout(monkeypatch):
    """A stalled SMB mount must not wedge the generator's worker thread — the
    same thread has to notice the user coming back."""
    def boom(cmd, **kwargs):
        raise ft.subprocess.TimeoutExpired("ffprobe", ft.PROBE_TIMEOUT_SECONDS)

    monkeypatch.setattr(ft.subprocess, "run", boom)

    with pytest.raises(ft.UnreadableMediaError) as excinfo:
        ft.probe_video("ffmpeg", "a.mov")

    assert "timed out" in str(excinfo.value)


def test_probe_video_passes_utf8_and_no_console_window(monkeypatch):
    captured: dict = {}
    _patch_probe(monkeypatch, stdout=_probe_json(), capture=captured)

    ft.probe_video("ffmpeg", "A001.mov")

    assert captured["encoding"] == "utf-8"
    assert captured["errors"] == "replace"
    if ft.sys.platform == "win32":
        assert captured["creationflags"] == ft.subprocess.CREATE_NO_WINDOW
    else:
        assert captured["creationflags"] == 0
