"""The three Timeline Cards media recipes, reproduced exactly.

docs/TIMELINE-CARDS-INTO-CCSYNC.md phase 1 (2026-08-30). Two halves:

  * THE ARGV IS PINNED VERBATIM against
    `MulticamPipeline/multicam_pipeline/cards/library_engine.py` -- `_src_make`
    (:1518, :1537), `_vid_make` (:1671) and `_peaks_make` (:1196). These
    files are read by a page in another repo on another release cadence; a
    proxy with a two-second GOP seeks like treacle, an extraction whose
    duration shifted breaks the lane's one premise, and a `.peaks` with the
    wrong header byte draws nothing. If one of these lists changes, the
    change is to every cached file in the vault and it wants saying out loud.
  * THE OUTPUT IS CHECKED AGAINST REAL ffmpeg, on clips made by ffmpeg here:
    an AAC mp4, a PCM mov in portrait, and an audio-only file. Dimensions,
    GOP, duration equality, and `.peaks` byte-for-byte against a reference
    computed the Timeline Cards way. Skipped, never failed, where there is no
    ffmpeg -- it is an optional dependency of this companion and CI has none.

Plus the properties that are not about ffmpeg at all: rule 2 (never two
writers on one output, and a finished file appearing mid-run means ours is
dropped), the progress stream, and nvenc standing aside cleanly where the
encoder is absent.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

import pytest

from ccsync_companion import jobs_media

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")
needs_ffmpeg = pytest.mark.skipif(
    not (FFMPEG and FFPROBE),
    reason="no ffmpeg/ffprobe here -- an OPTIONAL dependency of this companion")


def _encoders() -> set[str]:
    if not FFMPEG:
        return set()
    out = subprocess.run([FFMPEG, "-hide_banner", "-encoders"],
                         capture_output=True, text=True, timeout=30).stdout
    return {line.split()[1] for line in out.splitlines()
            if line.startswith(" ") and len(line.split()) > 1}


HAS_NVENC = "h264_nvenc" in _encoders()


# ------------------------------------------------------------- test media
@pytest.fixture(scope="module")
def clips(tmp_path_factory):
    """One of each shape the recipes have to survive.

    `testsrc`/`sine`, so nothing here needs a rush on a share: a landscape
    AAC mp4 (the stream-copy path), a PORTRAIT PCM mov (the Opus path, and
    the one where `min(480,ih)` caps the LONG side), and an audio-only file
    (a legitimate audio-extract input and an illegitimate proxy one).
    """
    if not (FFMPEG and FFPROBE):
        pytest.skip("no ffmpeg here")
    out = tmp_path_factory.mktemp("clips")

    def run(*args):
        subprocess.run([FFMPEG, "-y", "-loglevel", "error", *args],
                       check=True, timeout=180)

    run("-f", "lavfi", "-i", "testsrc=size=1920x1080:rate=30:duration=3",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
        str(out / "landscape_aac.mp4"))
    run("-f", "lavfi", "-i", "testsrc=size=1080x1920:rate=25:duration=2",
        "-f", "lavfi", "-i", "sine=frequency=300:duration=2",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "pcm_s16le",
        str(out / "portrait_pcm.mov"))
    run("-f", "lavfi", "-i", "sine=frequency=200:duration=2",
        "-c:a", "aac", str(out / "audio_only.m4a"))
    run("-f", "lavfi", "-i", "testsrc=size=320x240:rate=24:duration=1",
        "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        str(out / "silent_small.mp4"))
    return out


def probe(path, *entries, stream="a:0"):
    result = subprocess.run(
        [FFPROBE, "-v", "error", "-select_streams", stream, "-show_entries",
         "stream=" + ",".join(entries), "-of", "default=nw=1", str(path)],
        capture_output=True, text=True, timeout=60)
    got = {}
    for line in result.stdout.splitlines():
        key, _sep, value = line.partition("=")
        got[key] = value.strip()
    return got


def a_job(**kw):
    return jobs_media.MediaJob(ffmpeg_path=FFMPEG or "ffmpeg", **kw)


# =====================================================================
# THE RECIPES, VERBATIM. Each list below is the one in library_engine.py,
# with `-f` added because the output is named `.partial` (module docstring).
# =====================================================================

def test_the_aac_copy_is_library_engines_line_for_line():
    assert jobs_media.audio_copy_cmd("FF", "in.mp4", "out.m4a.partial") == [
        "FF", "-y", "-loglevel", "error", "-i", "in.mp4", "-vn", "-sn",
        "-dn", "-c:a", "copy", "-movflags", "+faststart",
        "-f", "ipod", "out.m4a.partial"]


def test_the_opus_fallback_is_library_engines_line_for_line():
    assert jobs_media.audio_opus_cmd("FF", "in.mov", "out.ogg.partial") == [
        "FF", "-y", "-loglevel", "error", "-i", "in.mov", "-vn", "-sn",
        "-dn", "-ac", "1", "-c:a", "libopus", "-b:a", "64k", "-vbr", "on",
        "-f", "ogg", "out.ogg.partial"]


def test_the_480p_proxy_is_library_engines_line_for_line():
    assert jobs_media.proxy_cmd("FF", "in.mp4", "out.mp4.partial", 30) == [
        "FF", "-y", "-loglevel", "error", "-i", "in.mp4",
        "-map", "0:v:0", "-map", "0:a:0?",
        "-vf", "scale=-2:'min(480,ih)'",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "26",
        "-g", "30", "-keyint_min", "30", "-sc_threshold", "0",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k", "-ac", "2",
        "-movflags", "+faststart", "-f", "mp4", "out.mp4.partial"]


def test_the_nvenc_proxy_changes_the_encoder_and_nothing_else():
    """The GOP, the scale, the pixel format, the audio and the faststart are
    IDENTICAL: the page must not be able to tell which machine made a file."""
    cpu = jobs_media.proxy_cmd("FF", "in.mp4", "o.partial", 25, nvenc=False)
    gpu = jobs_media.proxy_cmd("FF", "in.mp4", "o.partial", 25, nvenc=True)
    assert gpu[gpu.index("-c:v"):gpu.index("-g")] == [
        "-c:v", "h264_nvenc", "-preset", "p4", "-cq", "26"]
    assert cpu[:cpu.index("-c:v")] == gpu[:gpu.index("-c:v")]
    assert cpu[cpu.index("-g"):] == gpu[gpu.index("-g"):]


def test_the_peaks_decode_is_library_engines_line_for_line():
    """No `-y` and no output file: `-` is stdout, and the binning happens in
    this process."""
    assert jobs_media.peaks_cmd("FF", "in.wav") == [
        "FF", "-loglevel", "error", "-i", "in.wav", "-vn", "-ac", "1",
        "-ar", "8000", "-f", "s16le", "-"]


def test_progress_is_a_global_option_and_goes_at_position_one():
    """Everything after the input is an OUTPUT option; `-progress` is not one
    (proxy_gen._progress_argv's rule)."""
    argv = jobs_media.progress_argv(["ffmpeg", "-y", "-i", "a.mp4", "b.mp4"])
    assert argv[:3] == ["ffmpeg", "-progress", "pipe:1"]
    assert argv[3:] == ["-y", "-i", "a.mp4", "b.mp4"]


# =====================================================================
# The peaks format, which is the one file that must be BYTE-identical.
# =====================================================================

def reference_peaks(raw: bytes) -> bytes:
    """`_peaks_make`'s pure-Python branch, transcribed here so the reference
    is independent of the implementation under test."""
    import array
    sr, rate = 8000, 200
    per = sr // rate
    count = len(raw) // 2 // per
    block = array.array("h")
    block.frombytes(raw[:count * per * 2])
    peaks = bytes(
        min(255, max(map(abs, block[i * per:(i + 1) * per])) * 255 // 32767)
        for i in range(count))
    return b"PK" + bytes([rate, 0]) + peaks


def test_the_peaks_header_is_pk_the_rate_and_a_zero():
    """The third byte is the rate the file was made at, and the PAGE remakes
    any file whose byte disagrees with the rate it wants. That is what made
    the 50/s -> 200/s change survivable, and it is why this is pinned."""
    made = jobs_media.peaks_bytes(b"\x00\x00" * 8000)
    assert made[:2] == b"PK"
    assert made[2] == 200 == jobs_media.PEAK_RATE
    assert made[3] == 0
    # One second of 8 kHz audio at 200 bins a second.
    assert len(made) - 4 == 200


def test_the_peaks_bytes_match_a_reference_computed_the_timeline_cards_way():
    import random
    rnd = random.Random(7)
    raw = b"".join(
        int(rnd.uniform(-32768, 32767)).to_bytes(2, "little", signed=True)
        for _ in range(8000 * 2))
    assert jobs_media.peaks_bytes(raw) == reference_peaks(raw)


def test_the_loudest_possible_sample_does_not_overflow_the_byte():
    """-32768 is the one value where `|s| * 255 // 32767` exceeds 255, and
    the two branches of `_peaks_make` agree there only because one clamps and
    the other's uint8 cast happens to. Both must still be 255."""
    raw = (-32768).to_bytes(2, "little", signed=True) * 8000
    made = jobs_media.peaks_bytes(raw)
    assert set(made[4:]) == {255}
    assert made == reference_peaks(raw)


def test_a_decode_that_produced_nothing_is_a_header_and_no_bins():
    assert jobs_media.peaks_bytes(b"") == b"PK" + bytes([200, 0])


# =====================================================================
# Against real ffmpeg.
# =====================================================================

@needs_ffmpeg
def test_the_proxy_of_a_landscape_clip_is_480_lines_with_a_gop_of_one_second(
        clips, tmp_path):
    src = clips / "landscape_aac.mp4"
    out = a_job().run("proxy-480p", src, tmp_path, "Interview 3")
    assert out["files"] == ["Interview 3.480p.mp4"]
    made = tmp_path / "Interview 3.480p.mp4"
    video = probe(made, "width", "height", "codec_name", stream="v:0")
    # 1920x1080 -> the SHORT side is capped, and -2 keeps the width even.
    assert (video["width"], video["height"]) == ("854", "480")
    assert gop_seconds(made) <= 1.001


@needs_ffmpeg
def test_the_proxy_of_a_portrait_clip_caps_its_long_side(clips, tmp_path):
    """`min(480,ih)` on a 1080x1920 rush is 270x480, not 480x854: the page
    shows phone footage in the same window as everything else."""
    out = a_job().run("proxy-480p", clips / "portrait_pcm.mov", tmp_path, "Phone")
    video = probe(tmp_path / out["files"][0], "width", "height", stream="v:0")
    assert (video["width"], video["height"]) == ("270", "480")


@needs_ffmpeg
def test_a_small_source_is_never_blown_up(clips, tmp_path):
    """`min(480,ih)`, not a flat 480: a 240-line clip stays 240 lines rather
    than being upscaled into a bigger file that shows no more."""
    out = a_job().run("proxy-480p", clips / "silent_small.mp4", tmp_path, "Small")
    video = probe(tmp_path / out["files"][0], "width", "height", stream="v:0")
    assert (video["width"], video["height"]) == ("320", "240")


@needs_ffmpeg
def test_the_gop_follows_the_sources_frame_rate_and_is_not_a_flat_thirty(
        clips, tmp_path):
    """A keyframe a SECOND is what makes a seek land at once. A flat `-g 30`
    would be 1.2 s on this 25p clip and two seconds on 60p footage."""
    out = a_job().run("proxy-480p", clips / "portrait_pcm.mov", tmp_path, "P25")
    assert gop_seconds(tmp_path / out["files"][0]) <= 1.001


def gop_seconds(path) -> float:
    """The longest gap between key frames, in seconds. What "a keyframe a
    second" actually means to a browser asked to seek."""
    result = subprocess.run(
        [FFPROBE, "-v", "error", "-select_streams", "v:0", "-show_entries",
         "frame=key_frame,pts_time", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, timeout=120)
    keys = [float(line.split(",")[1]) for line in result.stdout.splitlines()
            if line.startswith("1,") and "," in line]
    if len(keys) < 2:
        return 0.0
    return max(b - a for a, b in zip(keys, keys[1:]))


@needs_ffmpeg
def test_the_proxys_audio_is_the_same_length_as_the_sources(clips, tmp_path):
    """The lane plays picture and sound off ONE element, so a proxy whose
    audio drifted is a window that slides out of sync with itself."""
    src = clips / "landscape_aac.mp4"
    out = a_job().run("proxy-480p", src, tmp_path, "Sync")
    source = float(probe(src, "duration")["duration"])
    made = float(probe(tmp_path / out["files"][0], "duration")["duration"])
    assert abs(source - made) <= jobs_media.DURATION_TOLERANCE_SECONDS


@needs_ffmpeg
def test_an_aac_source_is_copied_not_re_encoded(clips, tmp_path):
    """A track a browser already plays is the best possible answer, and
    re-encoding it would cost quality for nothing."""
    src = clips / "landscape_aac.mp4"
    out = a_job().run("audio-extract", src, tmp_path, "Interview 3")
    assert out["files"] == ["Interview 3.m4a"]
    made = tmp_path / "Interview 3.m4a"
    assert probe(made, "codec_name")["codec_name"] == "aac"
    assert probe(made, "codec_name", stream="v:0") == {}
    assert abs(float(probe(made, "duration")["duration"])
               - float(probe(src, "duration")["duration"])) <= 0.05


@needs_ffmpeg
def test_a_pcm_source_becomes_mono_opus(clips, tmp_path):
    """Everything that is not a clean AAC copy decodes to Opus, which is
    resampled from the decoded stream and cannot drift the way a stream copy
    across an edit list can."""
    out = a_job().run("audio-extract", clips / "portrait_pcm.mov",
                      tmp_path, "Phone")
    assert out["files"] == ["Phone.ogg"]
    made = probe(tmp_path / "Phone.ogg", "codec_name", "channels")
    assert made["codec_name"] == "opus"
    assert made["channels"] == "1"


@needs_ffmpeg
def test_an_audio_only_file_extracts_and_is_not_a_proxy(clips, tmp_path):
    """Two different answers about the same file, and both are right: it has
    audio to lift out, and there is nothing to make a picture of. The proxy
    refusal is NOT retryable -- no machine in the fleet will find a video
    stream that is not there."""
    src = clips / "audio_only.m4a"
    assert a_job().run("audio-extract", src, tmp_path, "VO")["files"] == ["VO.m4a"]
    with pytest.raises(jobs_media.MediaJobError) as caught:
        a_job().run("proxy-480p", src, tmp_path, "VO")
    assert caught.value.retryable is False
    assert "no video track" in str(caught.value)


@needs_ffmpeg
def test_a_silent_clip_cannot_be_extracted_and_says_so_permanently(clips, tmp_path):
    with pytest.raises(jobs_media.MediaJobError) as caught:
        a_job().run("audio-extract", clips / "silent_small.mp4", tmp_path, "Mute")
    assert caught.value.retryable is False
    assert "no audio track" in str(caught.value)


@needs_ffmpeg
def test_peaks_over_real_audio_match_the_reference_byte_for_byte(clips, tmp_path):
    """The whole file, header included, against the same decode binned the
    Timeline Cards way. This is the one output that has to be identical
    rather than equivalent: the page reads it as raw bytes."""
    src = clips / "landscape_aac.mp4"
    out = a_job().run("peaks", src, tmp_path, "Interview 3")
    assert out["files"] == ["Interview 3.peaks"]
    decoded = subprocess.run(jobs_media.peaks_cmd(FFMPEG, src),
                             capture_output=True, timeout=180).stdout
    assert (tmp_path / "Interview 3.peaks").read_bytes() == reference_peaks(decoded)


@needs_ffmpeg
def test_peaks_made_at_another_rate_are_remade(tmp_path):
    """`peaks_state`'s own rule, on this side too: the two must agree about
    what "already made" means, or the cache is rebuilt on every view.

    And the RE-CHECK before publishing has to know the same rule: the stale
    file is newer than its source, so a bare mtime test would let a 50/s
    `.peaks` refuse every remake for ever. (It did, on the first run of this
    test.)"""
    src = tmp_path / "in.m4a"
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-f", "lavfi",
                    "-i", "sine=frequency=200:duration=1", "-c:a", "aac",
                    str(src)], check=True, timeout=120)
    final = tmp_path / "old.peaks"
    final.write_bytes(b"PK" + bytes([50, 0]) + b"\x10" * 50)
    os.utime(final, (time.time() + 60, time.time() + 60))
    out = a_job().run("peaks", src, tmp_path, "old")
    assert out["skipped"] is False
    assert final.read_bytes()[2] == jobs_media.PEAK_RATE


@needs_ffmpeg
def test_a_file_that_is_already_there_and_current_is_not_made_again(clips, tmp_path):
    """The same `mtime >= source mtime` test the page uses. A fleet that
    re-encodes what it already has is a fleet doing nothing useful loudly."""
    src = clips / "portrait_pcm.mov"
    first = a_job().run("proxy-480p", src, tmp_path, "Once")
    assert first["skipped"] is False
    again = a_job().run("proxy-480p", src, tmp_path, "Once")
    assert again["skipped"] is True
    assert again["files"] == first["files"]
    # A skipped job reports no realtime figure: there is nothing honest to
    # divide, and a zero would average into a lie.
    assert "realtime" not in again


@needs_ffmpeg
@pytest.mark.skipif(not HAS_NVENC, reason="no NVIDIA encoder on this machine")
def test_the_nvenc_proxy_comes_out_the_same_shape_as_the_cpu_one(clips, tmp_path):
    """Where the hardware exists, the phase-1 win has to produce a file the
    page cannot tell apart: same dimensions, same codec, same GOP."""
    src = clips / "portrait_pcm.mov"
    cpu = tmp_path / "cpu"
    gpu = tmp_path / "gpu"
    a_job(nvenc=False).run("proxy-480p", src, cpu, "P")
    a_job(nvenc=True).run("proxy-480p", src, gpu, "P")
    keys = ("codec_name", "width", "height")
    assert probe(cpu / "P.480p.mp4", *keys, stream="v:0") == \
        probe(gpu / "P.480p.mp4", *keys, stream="v:0")
    assert gop_seconds(gpu / "P.480p.mp4") <= 1.001


@needs_ffmpeg
def test_a_machine_without_the_encoder_simply_does_not_ask_for_it(clips, tmp_path):
    """nvenc is a CAPABILITY, not a wish: the runner passes what
    capabilities.py reported, so a build without the encoder never assembles
    an argv it cannot run. Here: the default is off, and the file is made."""
    job = a_job()
    assert job.nvenc is False
    assert "h264_nvenc" not in jobs_media.proxy_cmd(FFMPEG, "a", "b", 30,
                                                    nvenc=job.nvenc)
    assert job.run("proxy-480p", clips / "portrait_pcm.mov", tmp_path, "P")["files"]


# =====================================================================
# Rule 2: NEVER TWO WRITERS ON ONE OUTPUT.
# =====================================================================

def test_a_second_claimant_of_one_output_backs_off():
    """proxy_gen._claim_partial's property. Keyed on the OUTPUT, not the
    source, because two sources that differ only by container resolve to one
    output name."""
    try:
        assert jobs_media.claim_partial("/tmp/X/A.480p.mp4.partial") is True
        assert jobs_media.claim_partial("/tmp/X/A.480p.mp4.partial") is False
        # ...and normcase/normpath, so two spellings of one path are one
        # claim on Windows.
        assert jobs_media.claim_partial("/tmp/X/./A.480p.mp4.partial") is False
    finally:
        jobs_media.release_partial("/tmp/X/A.480p.mp4.partial")
    assert jobs_media.claim_partial("/tmp/X/A.480p.mp4.partial") is True
    jobs_media.release_partial("/tmp/X/A.480p.mp4.partial")


@needs_ffmpeg
def test_a_finished_file_appearing_mid_run_means_ours_is_dropped(clips, tmp_path):
    """FIRST WRITER WINS, AND WE ARE HAPPY TO LOSE (proxy_gen rule 2).

    A Timeline Cards server making the same file locally is the shape the
    fleet lease cannot prevent -- it only stops two MACHINES claiming one
    JOB. So the existence check is repeated AFTER the work: overwriting a
    file the page is reading with one we happen to have just made is the
    thing rule 2 exists to stop.
    """
    src = clips / "portrait_pcm.mov"
    final = tmp_path / "Race.480p.mp4"
    theirs = b"the file somebody else finished while we were encoding"

    class Interloper(jobs_media.MediaJob):
        def _publish_after_writing(self, partial):
            pass

    job = a_job()
    real_run = jobs_media._run_ffmpeg

    def run_and_race(cmd, **kwargs):
        outcome = real_run(cmd, **kwargs)
        final.write_bytes(theirs)
        os.utime(final, (time.time() + 60, time.time() + 60))
        return outcome

    jobs_media._run_ffmpeg = run_and_race
    try:
        out = job.run("proxy-480p", src, tmp_path, "Race")
    finally:
        jobs_media._run_ffmpeg = real_run
    # Theirs is untouched, ours is gone, and the job still SUCCEEDS: the file
    # the caller asked for is there, which is what it wanted.
    assert final.read_bytes() == theirs
    assert out["files"] == ["Race.480p.mp4"]
    assert not (tmp_path / ("Race.480p.mp4" + jobs_media.PARTIAL_SUFFIX)).exists()


@needs_ffmpeg
def test_a_failed_recipe_leaves_no_partial_behind(clips, tmp_path):
    """A `.partial` is invisible to every sync lane, so one left behind costs
    disk rather than a broken file -- but it also has to be cleaned up, or a
    retry finds its own output already claimed."""
    src = clips / "portrait_pcm.mov"
    real_run = jobs_media._run_ffmpeg
    jobs_media._run_ffmpeg = lambda cmd, **kw: (1, "ffmpeg said no")
    try:
        with pytest.raises(jobs_media.MediaJobError):
            a_job().run("proxy-480p", src, tmp_path, "Doomed")
    finally:
        jobs_media._run_ffmpeg = real_run
    assert list(tmp_path.glob("*.partial")) == []
    # ...and the claim was released, so the retry is not refused by us.
    partial = tmp_path / ("Doomed.480p.mp4" + jobs_media.PARTIAL_SUFFIX)
    assert jobs_media.claim_partial(partial) is True
    jobs_media.release_partial(partial)


def test_is_fresh_uses_the_same_test_the_page_does(tmp_path):
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"x")
    final = tmp_path / "clip.480p.mp4"
    assert jobs_media.is_fresh(final, source) is False
    final.write_bytes(b"y")
    os.utime(final, (time.time() - 600, time.time() - 600))
    # Older than the media it came from: a re-export invalidates the cache on
    # both sides at the same instant.
    assert jobs_media.is_fresh(final, source) is False
    os.utime(final, (time.time() + 600, time.time() + 600))
    assert jobs_media.is_fresh(final, source) is True


# =====================================================================
# Progress, and stopping.
# =====================================================================

@needs_ffmpeg
def test_an_encode_reports_a_fraction_of_the_source_duration(clips, tmp_path):
    """ffmpeg's `-progress` stream against the source's own duration. It is
    what the fleet chip reads, and a machine with no percentage looks
    identical to a machine that is wedged."""
    seen: list = []
    job = a_job(on_progress=seen.append)
    job.run("proxy-480p", clips / "landscape_aac.mp4", tmp_path, "Bar")
    assert seen, "no progress was published at all"
    assert all(f is None or 0.0 <= f <= 1.0 for f in seen)
    assert seen[-1] is not None and seen[-1] > 0.5


def test_a_fraction_of_an_unknown_whole_is_not_a_fraction():
    """None, never 0: a source whose duration ffprobe could not answer has no
    honest percentage, and 0% is a machine that looks stuck."""
    published: list = []
    tracker = jobs_media._Progress(None, published.append, time.monotonic)
    tracker.feed("out_time_us", "1500000")
    tracker.publish()
    assert published and set(published) == {None}


def test_progress_is_published_at_most_once_a_second():
    """ffmpeg emits a block per output packet -- hundreds a second on a short
    clip -- and every one of them would be a lock and a report."""
    published: list = []
    now = [1000.0]
    tracker = jobs_media._Progress(10.0, published.append, lambda: now[0])
    for micros in range(100000, 2100000, 100000):
        tracker.feed("out_time_us", str(micros))
    assert len(published) == 1
    now[0] += 2.0
    tracker.feed("out_time_us", "5000000")
    assert len(published) == 2
    assert published[-1] == pytest.approx(0.5)


@needs_ffmpeg
def test_a_halt_stops_the_encode_and_publishes_nothing(clips, tmp_path):
    """"Stop everything" outranks a proxy, and a half-written file that
    reached the vault would be one the page plays."""
    job = a_job(should_stop=lambda: "a fleet halt stopped this job")
    with pytest.raises(jobs_media.MediaJobError) as caught:
        job.run("proxy-480p", clips / "landscape_aac.mp4", tmp_path, "Halted")
    assert "fleet halt" in str(caught.value)
    # No file, and no `.partial` either: the encode was killed and its output
    # removed, so a retry elsewhere starts from nothing rather than from
    # somebody's abandoned half. (`.ccsync` is the suite's redirected HOME.)
    assert [p.name for p in tmp_path.iterdir() if p.name != ".ccsync"] == []


def test_an_unknown_kind_is_refused_permanently(tmp_path):
    """The dashboard's kind filter is what should have stopped it; a silent
    retry loop between the two would be invisible."""
    with pytest.raises(jobs_media.MediaJobError) as caught:
        a_job().run("conform", tmp_path / "x.mp4", tmp_path, "x")
    assert caught.value.retryable is False


def test_a_source_this_machine_cannot_see_is_retryable_elsewhere(tmp_path):
    """Another machine may have the share mounted where this one does not --
    which is the entire reason a job's paths are (root, rel_path) pairs."""
    with pytest.raises(jobs_media.MediaJobError) as caught:
        a_job().run("peaks", tmp_path / "gone.mp4", tmp_path, "gone")
    assert caught.value.retryable is True


@needs_ffmpeg
def test_the_probes_answer_about_the_stream_and_not_the_container(clips):
    """cards/media.py's distinction, and it is the one the copy check rests
    on: a container's duration counts the video too, and the question is
    whether the AUDIO came out the length it went in."""
    codec, duration = jobs_media.probe_audio(FFMPEG, clips / "landscape_aac.mp4")
    assert codec == "aac"
    assert 2.9 < duration < 3.1
    vcodec, width, height, fps = jobs_media.probe_video(
        FFMPEG, clips / "portrait_pcm.mov")
    assert (vcodec, width, height) == ("h264", 1080, 1920)
    assert fps == pytest.approx(25.0)
    # An audio-only file is not a video probe failure to raise about: it is
    # (None, None, None, None), which the proxy recipe reads as "no video
    # track" and refuses permanently.
    assert jobs_media.probe_video(FFMPEG, clips / "audio_only.m4a") == \
        (None, None, None, None)


def test_a_fractional_frame_rate_is_resolved_once_not_rounded_twice():
    """"30000/1001" is 29.97, whose GOP is 30 -- a keyframe every 1.001 s.
    Rounding the fraction's numerator would be a GOP of 30000."""
    assert jobs_media.MediaJob  # the module imports without ffmpeg present
    assert round(30000 / 1001) == 30
