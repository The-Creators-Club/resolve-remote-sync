"""The three Timeline Cards media recipes, run as fleet jobs.

docs/TIMELINE-CARDS-INTO-CCSYNC.md phase 1 (2026-08-30). Timeline Cards makes
three derived files for every clip a lane touches, on ONE worker thread in
whichever process happens to be serving the page:

    audio-extract   `<clip>.m4a` (aac copy) or `<clip>.ogg` (mono Opus) --
                    what the lane's <audio> element plays.
    proxy-480p      `<clip>.480p.mp4` -- what the video window plays, from the
                    SAME element, so picture and sound cannot drift.
    peaks           `<clip>.peaks` -- the waveform under the lane.

All three land in the vault, under `<episode>\\Script Docs\\remote_audio\\`,
which every machine in the fleet shares. This module is those recipes, moved
onto a machine that is not the one serving the page.

THE RECIPES ARE REPRODUCED EXACTLY, and that is the whole point of the file.
The page reads these files; a proxy with a two-second GOP seeks like treacle,
an extraction whose duration shifted breaks the lane's one premise (source
seconds == clip seconds), and a `.peaks` written at the wrong rate or with the
wrong header byte draws a blank waveform. The argv builders below are
therefore pinned VERBATIM by tests against
`multicam_pipeline/cards/library_engine.py`'s `_src_make` (:1490), `_vid_make`
(:1637) and `_peaks_make` (:1190), and the one deliberate difference is
explained where it is made (`-f`, below).

Four rules, each of them somebody else's scar:

  * **NEVER TWO WRITERS ON ONE OUTPUT** -- proxy_gen's rule 2, adopted
    wholesale (`proxy_gen.py:18` and `_claim_partial:725`). Every recipe
    writes `<final>.partial` and moves it with `os.replace` only after
    RE-CHECKING that no finished file has appeared meanwhile. The fleet lease
    already stops two machines claiming one job; what it cannot stop is a
    Timeline Cards server making the same file locally at the same time,
    which is exactly the shape lane B + BPG had. FIRST WRITER WINS, ALWAYS,
    AND WE ARE HAPPY TO LOSE.
  * **`.partial`, NOT `.tmp.m4a`.** Timeline Cards writes `out + ".tmp.m4a"`;
    this writes `out + ".partial"`, because `.partial` is the suffix every
    sync lane in this repo already excludes in both directions and a half
    written proxy must never reach another machine. It costs one `-f` flag
    (below) and buys the file being invisible to the fleet until it is done.
  * **`-f` IS LOAD-BEARING NOW.** ffmpeg picks its muxer from the output's
    extension, and `<name>.m4a.partial` has none it knows. `-f ipod` is
    exactly what `.m4a` resolves to and `-f mp4` exactly what `.mp4` does --
    measured byte-identical against the Timeline Cards command on 2026-08-30
    for the m4a and the mp4; the ogg differs only in its random stream serial,
    which the Ogg muxer re-rolls on every run of any argv at all.
  * **NOTHING HERE DECIDES WHAT TO MAKE.** The job says which clip and where
    the output goes; this module makes it. Deciding is the page's job, and
    the page is in the other repo.

Every collaborator that touches the world -- ffmpeg, the clock, the progress
sink, the stop check -- arrives as a parameter, exactly as proxy_gen's do, so
the whole thing is testable with a fake ffmpeg and no media at all.
"""
from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

from . import ffmpeg_tools, proxy_gen, proxy_scan

log = logging.getLogger("ccsync.jobs.media")

KIND_PROXY_480P = "proxy-480p"
KIND_AUDIO_EXTRACT = "audio-extract"
KIND_PEAKS = "peaks"
MEDIA_KINDS = (KIND_PROXY_480P, KIND_AUDIO_EXTRACT, KIND_PEAKS)

# proxy_gen's suffix, deliberately the same string: it is what every lane
# filter in this repo already excludes, and a second spelling would be a
# half-written file that syncs.
PARTIAL_SUFFIX = proxy_scan.PARTIAL_SUFFIX

# library_engine.py:1653 -- the proxy's name is `<stem>.480p.mp4`, and the
# page looks for exactly that.
VID_EXT = ".480p.mp4"
# SRC_TYPES, in the order src_ready() looks for them (cards/config.py:87).
AUDIO_EXTS = (".m4a", ".ogg")
PEAKS_EXT = ".peaks"

# library_engine.PEAK_RATE (:1153). 200 a second since 2026-08-28: at the
# lane's working zoom a pixel is ~20 ms, and the old 50/s binning made the
# waveform blocky. THE VALUE IS IN THE FILE'S HEADER -- the page remakes a
# file whose third byte says something else -- so changing it here without
# changing it there is a cache that is rebuilt on every single view.
PEAK_RATE = 200
PEAK_SAMPLE_RATE = 8000

# `_src_make`'s tolerance: an mp4 with an edit list or priming samples can
# come out of a stream copy shifted, and the lane's whole premise is that
# source seconds are clip seconds.
DURATION_TOLERANCE_SECONDS = 0.05

# The ceilings Timeline Cards uses, kept: 30 minutes for a copy or a peaks
# decode, an hour for an encode.
COPY_TIMEOUT_SECONDS = 1800.0
ENCODE_TIMEOUT_SECONDS = 3600.0
PROBE_TIMEOUT_SECONDS = 120.0

# How often a running recipe's progress is published. proxy_gen's number and
# its reason: ffmpeg emits a -progress block per output packet, hundreds a
# second, and the consumer here turns them into a 30 s heartbeat.
PROGRESS_PUBLISH_SECONDS = 1.0

# How often the loop wakes to ask whether it should stop.
POLL_SECONDS = 0.5


class MediaJobError(Exception):
    """A recipe that cannot be finished. `retryable=False` means the fault is
    in the INPUT -- a file with no audio track, a rush with no video stream --
    which no other machine in the fleet is going to fix, and the runner hands
    it back as a failure rather than letting it tour the fleet."""

    def __init__(self, message: str, retryable: bool = True):
        super().__init__(message)
        self.retryable = bool(retryable)


# ======================================================================
# The probes. Timeline Cards' `cards/media.py` (:42, :72), reproduced --
# NOT ffmpeg_tools.probe_video, which raises on a file with no video stream
# and returns a container duration. Both distinctions matter here: an
# audio-only file is a legitimate `audio-extract` input, and the check that
# decides whether a stream copy is usable is the AUDIO STREAM's duration,
# because a container's own counts the video too.
#
# ffprobe comes from `ffmpeg_tools.ffprobe_for(ffmpeg_path)`, which is the
# companion's own tool discovery: the sibling of whatever ffmpeg this machine
# resolved, including the pinned static pair `sidecar_tools` installs for
# machines that have neither on PATH.
# ======================================================================


def _ffprobe(ffmpeg_path: str) -> str:
    return ffmpeg_tools.ffprobe_for(ffmpeg_path)


def _run_probe(cmd: list[str]) -> Optional[str]:
    try:
        result = subprocess.run(  # noqa: S603 -- argv built here
            cmd, capture_output=True, timeout=PROBE_TIMEOUT_SECONDS,
            creationflags=ffmpeg_tools._win_creationflags(),
            **ffmpeg_tools.TEXT_UTF8)
    except (OSError, subprocess.SubprocessError):
        log.debug("media jobs: probe failed: %s", cmd[0], exc_info=True)
        return None
    return result.stdout or ""


def probe_audio(ffmpeg_path: str, path: str | Path) -> tuple[Optional[str], Optional[float]]:
    """(codec, duration) of the first AUDIO stream; (None, None) if there is
    none or ffprobe cannot be run. The STREAM's duration, never the
    container's (cards/media.py:42's whole reason)."""
    out = _run_probe([
        _ffprobe(ffmpeg_path), "-v", "error", "-select_streams", "a:0",
        "-show_entries", "stream=codec_name,duration", "-of", "default=nw=1",
        str(path)])
    if out is None:
        return None, None
    codec: Optional[str] = None
    duration: Optional[float] = None
    for line in out.splitlines():
        key, _sep, value = line.partition("=")
        if key == "codec_name" and value.strip():
            codec = value.strip()
        elif key == "duration":
            try:
                duration = float(value)
            except ValueError:
                duration = None
    return codec, duration


def probe_video(
    ffmpeg_path: str, path: str | Path,
) -> tuple[Optional[str], Optional[int], Optional[int], Optional[float]]:
    """(codec, width, height, fps) of the first VIDEO stream.

    The rate is resolved from its fraction HERE ("30000/1001" -> 29.97) rather
    than rounded twice: it is what the proxy's GOP is set from, and a GOP of
    30 on 29.97 footage is a keyframe every 1.001 s, which is right, while
    rounding the fraction to 30000 is not.
    """
    out = _run_probe([
        _ffprobe(ffmpeg_path), "-v", "error", "-select_streams", "v:0",
        "-show_entries",
        "stream=codec_name,width,height,avg_frame_rate,r_frame_rate",
        "-of", "default=nw=1", str(path)])
    if out is None:
        return None, None, None, None
    got: dict[str, str] = {}
    for line in out.splitlines():
        key, _sep, value = line.partition("=")
        got[key] = value.strip()
    codec = got.get("codec_name") or None
    if not codec:
        return None, None, None, None

    def rate(text: str) -> Optional[float]:
        try:
            num, _sep, den = (text or "").partition("/")
            value = float(num) / float(den or 1)
            return value if value > 0 else None
        except (ValueError, ZeroDivisionError):
            return None

    def number(text: str) -> Optional[int]:
        try:
            return int(text)
        except (TypeError, ValueError):
            return None

    return (codec, number(got.get("width", "")), number(got.get("height", "")),
            rate(got.get("avg_frame_rate", "")) or rate(got.get("r_frame_rate", "")))


# ======================================================================
# The argv builders. These are the recipes, and the tests pin them line for
# line against library_engine.py. Read a change to one of them as a change to
# every cached file in the vault.
# ======================================================================


def audio_copy_cmd(ffmpeg_path: str, src: str | Path, out: str | Path) -> list[str]:
    """`_src_make`'s AAC branch (:1518): the track lifted out untouched.

    A copy, not a transcode, because an AAC track a browser already plays is
    the best possible answer and re-encoding it would cost quality for
    nothing. `-vn -sn -dn` drops video, subtitles and data; `+faststart` puts
    the index at the front so the lane can start playing before the file has
    arrived.
    """
    return [str(ffmpeg_path), "-y", "-loglevel", "error", "-i", str(src),
            "-vn", "-sn", "-dn", "-c:a", "copy", "-movflags", "+faststart",
            # `.m4a` resolves to the `ipod` muxer; the output here is named
            # `.partial`, so it has to be said out loud (module docstring).
            "-f", "ipod", str(out)]


def audio_opus_cmd(ffmpeg_path: str, src: str | Path, out: str | Path) -> list[str]:
    """`_src_make`'s fallback (:1537): everything that is not a clean AAC copy.

    Mono 64k Opus, RESAMPLED FROM THE DECODED STREAM, which is why it is the
    fallback: it cannot drift the way a stream copy across an edit list can,
    and every browser plays it.
    """
    return [str(ffmpeg_path), "-y", "-loglevel", "error", "-i", str(src),
            "-vn", "-sn", "-dn", "-ac", "1", "-c:a", "libopus", "-b:a", "64k",
            "-vbr", "on", "-f", "ogg", str(out)]


def proxy_cmd(
    ffmpeg_path: str, src: str | Path, out: str | Path, gop: int,
    nvenc: bool = False,
) -> list[str]:
    """`_vid_make`'s encode (:1671), with the nvenc variant phase 1 adds.

    `scale=-2:'min(480,ih)'` caps the picture at 480 LINES: on a landscape
    rush that is its short side (1920x1080 -> 854x480), on a portrait one the
    long side (1080x1920 -> 270x480), and `min` means a small source is never
    blown up. `-2` keeps the width even, which yuv420p requires.

    THE GOP IS THE SOURCE'S OWN FRAME RATE, ROUNDED -- a keyframe a SECOND, so
    a seek to any frame is one GOP away. A flat `-g 30` would be two seconds
    on 60p footage, which is the difference between a lane that scrubs and a
    lane that lurches.

    nvenc where the machine has it is the phase-1 win. `p4` is NVIDIA's
    "medium" preset and `-cq 26` its constant-quality control, chosen to sit
    where `-crf 26` does on x264; the GOP, the pixel format, the audio and the
    faststart are IDENTICAL, because the page must not be able to tell which
    machine made a file.
    """
    video = (["-c:v", "h264_nvenc", "-preset", "p4", "-cq", "26"] if nvenc
             else ["-c:v", "libx264", "-preset", "veryfast", "-crf", "26"])
    return [str(ffmpeg_path), "-y", "-loglevel", "error", "-i", str(src),
            "-map", "0:v:0", "-map", "0:a:0?",
            "-vf", "scale=-2:'min(480,ih)'",
            *video,
            "-g", str(int(gop)), "-keyint_min", str(int(gop)),
            "-sc_threshold", "0", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "96k", "-ac", "2",
            "-movflags", "+faststart", "-f", "mp4", str(out)]


def peaks_cmd(ffmpeg_path: str, src: str | Path) -> list[str]:
    """`_peaks_make`'s decode (:1196): mono 8 kHz signed 16-bit, to STDOUT.

    No `-y` and no output file: the samples are binned in this process. 8 kHz
    because the waveform only needs an envelope, and it makes an hour of audio
    28 MB of pipe instead of 600.
    """
    return [str(ffmpeg_path), "-loglevel", "error", "-i", str(src),
            "-vn", "-ac", "1", "-ar", str(PEAK_SAMPLE_RATE), "-f", "s16le", "-"]


def peaks_bytes(raw: bytes) -> bytes:
    """s16le samples -> the `.peaks` file, header and all.

    THE FORMAT IS FOUR BYTES OF HEADER AND ONE BYTE A BIN:

        b"PK" | PEAK_RATE | 0 | max(|sample|) * 255 // 32767 per bin

    The third byte is the rate the file was made at, and the page remakes any
    file whose byte disagrees with the rate it wants -- which is what made
    the 50/s -> 200/s change survivable and is why this must stay exact.

    numpy when it is importable and `array` when it is not, exactly as
    `_peaks_make` does, and the two produce THE SAME BYTES: the pure-Python
    branch's `min(255, ...)` and the numpy branch's uint8 cast agree even at
    -32768, the one sample value where the arithmetic exceeds 255.
    """
    per = PEAK_SAMPLE_RATE // PEAK_RATE
    count = len(raw) // 2 // per
    if count <= 0:
        return b"PK" + bytes([PEAK_RATE, 0])
    try:
        import numpy as np
        samples = np.frombuffer(raw, dtype="<i2", count=count * per)
        peaks = (np.abs(samples.astype("int32")).reshape(-1, per).max(axis=1)
                 * 255 // 32767).astype("uint8").tobytes()
    except ImportError:
        import array
        block = array.array("h")
        block.frombytes(raw[:count * per * 2])
        peaks = bytes(
            min(255, max(map(abs, block[i * per:(i + 1) * per])) * 255 // 32767)
            for i in range(count))
    return b"PK" + bytes([PEAK_RATE, 0]) + peaks


# ======================================================================
# Rule 2, adopted wholesale: NEVER TWO WRITERS ON ONE OUTPUT.
# ======================================================================

_partial_lock = threading.Lock()
_partials: set[str] = set()


def _partial_key(path: str | Path) -> str:
    return os.path.normcase(os.path.normpath(str(path)))


def claim_partial(path: str | Path) -> bool:
    """Take this output path, or say it is already taken.

    proxy_gen._claim_partial (:725), same reasoning and the same key: the
    OUTPUT, not the source, because two sources that differ only by container
    resolve to one output name. The fleet lease means one job is claimed once,
    so this covers what the lease cannot -- two recipes in this process
    racing for one file, and a re-queued job arriving while its predecessor
    is still finishing.
    """
    key = _partial_key(path)
    with _partial_lock:
        if key in _partials:
            return False
        _partials.add(key)
        return True


def release_partial(path: str | Path) -> None:
    with _partial_lock:
        _partials.discard(_partial_key(path))


def is_fresh(final: str | Path, source: str | Path) -> bool:
    """Is there already a finished file here, newer than the clip it comes
    from? Timeline Cards' `src_ready`/`vid_ready`/`peaks_state` test exactly
    (`os.path.getmtime(out) >= os.path.getmtime(src)`), so the two agree about
    what "already made" means -- and a media file replaced by a re-export
    invalidates its cache on both sides at the same instant."""
    try:
        return os.path.getmtime(str(final)) >= os.path.getmtime(str(source))
    except OSError:
        return False


def _publish(partial: str | Path, final: str | Path, source: str | Path,
             already_made: Optional[Callable[[], bool]] = None) -> bool:
    """Move the finished `.partial` onto its name. -> did ours land.

    THE RE-CHECK IS HERE, AFTER THE WORK, NOT ONLY BEFORE IT (proxy_gen
    `_publish`:1705, and the reason is unchanged): a Timeline Cards server can
    make the same file locally while this machine encodes, and overwriting it
    would be replacing a file a page is reading with one we happen to have
    just made. First writer wins; ours is discarded, and the job still reports
    the file, because the file is there and that is what the caller asked for.
    """
    settled = already_made or (lambda: is_fresh(final, source))
    if settled():
        log.info("media jobs: %s already exists and is current -- discarding "
                 "the one just made rather than overwriting it",
                 os.path.basename(str(final)))
        discard(partial)
        return False
    try:
        os.replace(str(partial), str(final))
    except OSError as exc:
        raise MediaJobError(
            f"could not put the finished file in place ({exc}) -- it is still "
            f"there as {os.path.basename(str(partial))}") from exc
    return True


def discard(partial: str | Path) -> None:
    """Remove something we are not going to finish. Never raises: a `.partial`
    is excluded from every sync lane, so a failure here costs disk and
    nothing else."""
    try:
        os.remove(str(partial))
    except OSError:
        log.debug("media jobs: could not remove %s", partial, exc_info=True)


# ======================================================================
# Running ffmpeg with a progress stream.
# ======================================================================


def _popen(cmd: list[str], binary_stdout: bool = False,
           want_stdout: bool = True) -> Any:
    """Spawn ffmpeg: no console window, below-normal priority, pipes drained.

    proxy_gen._default_popen's shape and its reasons -- the priority covers
    the moment before a stop check fires, `stdin=DEVNULL` stops ffmpeg eating
    the parent's (there is none in a frozen windowed build, which makes it an
    error rather than a theft), and every pipe opened here is READ TO EOF on
    its own thread, because an undrained 64 KB OS buffer blocks the encoder
    for ever.
    """
    kwargs: dict[str, Any] = {
        # PIPE only when something is going to READ it -- an undrained pipe
        # fills its ~64 KB OS buffer and blocks the encoder for ever, which is
        # the classic deadlock, and it is not worth relying on "ffmpeg happens
        # to write nothing to stdout without -progress".
        "stdout": subprocess.PIPE if want_stdout else subprocess.DEVNULL,
        "stdin": subprocess.DEVNULL,
        "stderr": subprocess.PIPE,
    }
    if not binary_stdout:
        kwargs.update(ffmpeg_tools.TEXT_UTF8)
    else:
        # stdout is PCM; stderr still has to be text, and Popen has one
        # setting for both, so the stderr drain decodes by hand below.
        pass
    flags = ffmpeg_tools._win_creationflags()
    if os.name == "nt":
        flags |= getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0x00004000)
    kwargs["creationflags"] = flags
    return subprocess.Popen(cmd, **kwargs)  # noqa: S603 -- argv built above


def progress_argv(cmd: list[str]) -> list[str]:
    """`-progress pipe:1` at position 1. proxy_gen._progress_argv's rule: it
    is a GLOBAL option, and everything after the input is an output option."""
    return [cmd[0], "-progress", "pipe:1", *cmd[1:]]


def _drain_text(stream: Any, sink: list[str], limit: int = 40) -> None:
    """Read a pipe to EOF into a bounded list. Never raises -- this runs on its
    own thread, where an exception would go to a stderr a windowed build does
    not have."""
    try:
        for line in iter(stream.readline, ""):
            if not line:
                break
            if isinstance(line, bytes):
                line = line.decode("utf-8", "replace")
            sink.append(line.rstrip("\r\n"))
            del sink[:-limit]
    except Exception:
        log.debug("media jobs: stderr reader stopped early", exc_info=True)
    finally:
        try:
            stream.close()
        except Exception:
            pass


class _Progress:
    """ffmpeg's `-progress` stream turned into a fraction, published at most
    once a second."""

    def __init__(self, total_seconds: Optional[float],
                 sink: Optional[Callable[[Optional[float]], None]],
                 clock: Callable[[], float]):
        self.total = float(total_seconds or 0.0)
        self.sink = sink
        self.clock = clock
        self.last = 0.0
        self.seconds = 0.0

    def feed(self, key: str, value: str) -> None:
        parsed = proxy_gen.parse_progress(key, value)
        if parsed is None or parsed[0] != "seconds":
            return
        self.seconds = parsed[1]
        now = self.clock()
        if now - self.last < PROGRESS_PUBLISH_SECONDS:
            return
        self.last = now
        self.publish()

    def publish(self) -> None:
        if self.sink is None:
            return
        # None when the source duration is unknown: a fraction of an unknown
        # whole is not a fraction, and the chip shows the job id instead of an
        # invented number (db.clamp_progress's rule, on this side too).
        fraction = (max(0.0, min(1.0, self.seconds / self.total))
                    if self.total > 0 else None)
        try:
            self.sink(fraction)
        except Exception:
            log.debug("media jobs: progress sink raised", exc_info=True)


def _run_ffmpeg(
    cmd: list[str], *, total_seconds: Optional[float] = None,
    on_progress: Optional[Callable[[Optional[float]], None]] = None,
    should_stop: Optional[Callable[[], str]] = None,
    ceiling: float = ENCODE_TIMEOUT_SECONDS,
    clock: Callable[[], float] = time.monotonic,
    popen: Optional[Callable[..., Any]] = None,
) -> tuple[int, str]:
    """Run one ffmpeg, reporting progress and stopping when told to.

    -> (returncode, stderr tail). Raises MediaJobError when it was stopped or
    ran past the ceiling, because those are not results a caller should be
    able to mistake for a finished file.
    """
    spawn = popen or _popen
    wants = on_progress is not None
    argv = progress_argv(cmd) if wants else cmd
    try:
        proc = spawn(argv) if popen is not None else spawn(argv, want_stdout=wants)
    except Exception as exc:                                    # noqa: BLE001
        raise MediaJobError(f"could not start ffmpeg: {exc}") from exc
    errors: list[str] = []
    threads = [threading.Thread(target=_drain_text, args=(proc.stderr, errors),
                               name="ccsync-media-stderr", daemon=True)]
    tracker = _Progress(total_seconds, on_progress, clock)
    if on_progress is not None and getattr(proc, "stdout", None) is not None:
        threads.append(threading.Thread(
            target=_drain_progress, args=(proc.stdout, tracker.feed),
            name="ccsync-media-progress", daemon=True))
    for thread in threads:
        thread.start()
    started = clock()
    stopped = ""
    timed_out = False
    while True:
        if proc.poll() is not None:
            break
        stopped = (should_stop() if should_stop is not None else "") or ""
        if stopped:
            break
        if (clock() - started) > ceiling:
            timed_out = True
            break
        time.sleep(POLL_SECONDS)
    if stopped or timed_out:
        _kill(proc)
        for thread in threads:
            thread.join(timeout=5.0)
        raise MediaJobError(
            stopped or f"ffmpeg did not finish within {int(ceiling)}s")
    for thread in threads:
        thread.join(timeout=5.0)
    tracker.publish()
    return int(proc.poll() or 0), "\n".join(errors).strip()[-200:]


def _drain_progress(stream: Any, feed: Callable[[str, str], None]) -> None:
    try:
        for line in iter(stream.readline, ""):
            if not line:
                break
            if isinstance(line, bytes):
                line = line.decode("utf-8", "replace")
            key, sep, value = line.strip().partition("=")
            if sep:
                feed(key, value)
    except Exception:
        log.debug("media jobs: progress reader stopped early", exc_info=True)
    finally:
        try:
            stream.close()
        except Exception:
            pass


def _kill(proc: Any) -> None:
    """End a child that must stop NOW, with a BOUNDED wait: a process in an
    uninterruptible kernel wait cannot be killed at all, and an unbounded
    wait() here would hang the thread whose job is to be responsive
    (proxy_gen._kill, rclone_lane._end_probe before it)."""
    try:
        proc.kill()
    except Exception:
        log.debug("media jobs: could not kill ffmpeg", exc_info=True)
    try:
        proc.wait(timeout=5)
    except Exception:
        log.warning("media jobs: ffmpeg did not die when killed -- leaving it "
                    "to the OS. Its output stays a .partial and is never "
                    "published.")


def _read_pcm(
    cmd: list[str], *, should_stop: Optional[Callable[[], str]] = None,
    ceiling: float = COPY_TIMEOUT_SECONDS,
    clock: Callable[[], float] = time.monotonic,
    popen: Optional[Callable[..., Any]] = None,
) -> tuple[int, bytes, str]:
    """Run an ffmpeg that writes PCM to stdout, reading it as it comes.

    Chunked rather than `subprocess.run(capture_output=True)` -- which is what
    `_peaks_make` uses -- so a stop (a fleet halt, a shutdown) is honoured
    within a chunk instead of within half an hour, and so the caller can
    heartbeat while an hour of audio decodes.
    """
    spawn = popen or _popen
    try:
        proc = spawn(cmd, binary_stdout=True)
    except Exception as exc:                                    # noqa: BLE001
        raise MediaJobError(f"could not start ffmpeg: {exc}") from exc
    errors: list[str] = []
    reader = threading.Thread(target=_drain_text, args=(proc.stderr, errors),
                              name="ccsync-media-stderr", daemon=True)
    reader.start()
    chunks: list[bytes] = []
    started = clock()
    stopped = ""
    timed_out = False
    try:
        while True:
            block = proc.stdout.read(1 << 20)
            if not block:
                break
            chunks.append(block if isinstance(block, bytes)
                          else block.encode("latin-1"))
            stopped = (should_stop() if should_stop is not None else "") or ""
            if stopped:
                break
            if (clock() - started) > ceiling:
                timed_out = True
                break
    except Exception as exc:                                    # noqa: BLE001
        _kill(proc)
        reader.join(timeout=5.0)
        raise MediaJobError(f"the decode failed: {exc}") from exc
    if stopped or timed_out:
        _kill(proc)
        reader.join(timeout=5.0)
        raise MediaJobError(
            stopped or f"ffmpeg did not finish within {int(ceiling)}s")
    try:
        proc.wait(timeout=30)
    except Exception:
        _kill(proc)
    reader.join(timeout=5.0)
    return int(proc.returncode or 0), b"".join(chunks), \
        "\n".join(errors).strip()[-200:]


# ======================================================================
# The three recipes, end to end.
# ======================================================================


class MediaJob:
    """One recipe, on this machine. Not a queue and not a scheduler: the
    fleet is the queue now, and this is the piece that does the work.

    `nvenc` is the CAPABILITY, not a wish: jobs_runner passes what
    capabilities.py reported, which is `ffmpeg_tools.detect_encoders` on this
    machine's own binary, so a build without the encoder never assembles an
    argv it cannot run.
    """

    def __init__(
        self,
        ffmpeg_path: str = "ffmpeg",
        nvenc: bool = False,
        on_progress: Optional[Callable[[Optional[float]], None]] = None,
        should_stop: Optional[Callable[[], str]] = None,
        clock: Callable[[], float] = time.monotonic,
        popen: Optional[Callable[..., Any]] = None,
    ) -> None:
        self.ffmpeg_path = str(ffmpeg_path or "ffmpeg")
        self.nvenc = bool(nvenc)
        self.on_progress = on_progress
        self.should_stop = should_stop
        self.clock = clock
        self.popen = popen

    # -- the dispatch ----------------------------------------------------
    def run(self, kind: str, source: Path, out_dir: Path, stem: str) -> dict[str, Any]:
        """-> {"files": [names in out_dir], "seconds", "realtime", "skipped"}.

        `files` are NAMES, not paths: the caller knows which root and which
        relative directory it asked for, and an absolute path in a result row
        is one that means something different on every machine that reads it
        later (§4.1, applied to the answer as well as the question).
        """
        kind = str(kind)
        if kind not in MEDIA_KINDS:
            raise MediaJobError(f"no recipe for {kind!r} jobs", retryable=False)
        if not source.exists():
            # RETRYABLE: this machine may simply not have the share mounted
            # where it thinks it does, and another one might.
            raise MediaJobError(f"the source media is not here: {source}")
        started = self.clock()
        if kind == KIND_AUDIO_EXTRACT:
            files, skipped, media_seconds = self._audio(source, out_dir, stem)
        elif kind == KIND_PROXY_480P:
            files, skipped, media_seconds = self._proxy(source, out_dir, stem)
        else:
            files, skipped, media_seconds = self._peaks(source, out_dir, stem)
        elapsed = round(self.clock() - started, 1)
        result: dict[str, Any] = {"files": files, "seconds": elapsed,
                                  "skipped": skipped}
        # The one number that says whether moving this work to another machine
        # was worth it -- and absent, rather than zero, when there is nothing
        # honest to divide (a skipped job, an unprobeable source).
        if media_seconds and elapsed > 0 and not skipped:
            result["realtime"] = round(float(media_seconds) / elapsed, 1)
        return result

    # -- audio-extract ---------------------------------------------------
    def _audio(self, source: Path, out_dir: Path,
               stem: str) -> tuple[list[str], bool, Optional[float]]:
        """`_src_make` (:1490).

        AAC IS COPIED AND THEN CHECKED, and the check is the interesting half:
        an mp4 with an edit list or priming samples can come out of a stream
        copy SHIFTED, and the lane's whole premise is that source seconds are
        clip seconds. A shift, a copy ffmpeg refuses, or a codec no browser
        plays all fall through to Opus, which is resampled from the decoded
        stream and cannot drift.
        """
        for ext in AUDIO_EXTS:
            existing = out_dir / f"{stem}{ext}"
            if is_fresh(existing, source):
                return [existing.name], True, None
        codec, duration = probe_audio(self.ffmpeg_path, source)
        if not codec:
            # NOT RETRYABLE: a file with no audio track has none on every
            # machine in the fleet.
            raise MediaJobError("no audio track", retryable=False)
        out_dir.mkdir(parents=True, exist_ok=True)
        if codec == "aac":
            final = out_dir / f"{stem}.m4a"
            made = self._attempt_copy(source, final, duration)
            if made is not None:
                return [made], False, duration
        final = out_dir / f"{stem}.ogg"
        self._with_partial(
            final, source,
            lambda partial: self._require(
                _run_ffmpeg(audio_opus_cmd(self.ffmpeg_path, source, partial),
                            total_seconds=duration, on_progress=self.on_progress,
                            should_stop=self.should_stop,
                            ceiling=COPY_TIMEOUT_SECONDS, clock=self.clock,
                            popen=self.popen)))
        return [final.name], False, duration

    def _attempt_copy(self, source: Path, final: Path,
                      duration: Optional[float]) -> Optional[str]:
        """The AAC copy, or None if it came out unusable. Never raises for a
        refused copy: falling back to Opus is the DESIGNED answer, not a
        failure, and a job that ended there is a job that worked."""
        partial = Path(str(final) + PARTIAL_SUFFIX)
        if not claim_partial(partial):
            raise MediaJobError(
                f"another writer on this machine already has "
                f"{partial.name} -- leaving it to them")
        try:
            code, err = _run_ffmpeg(
                audio_copy_cmd(self.ffmpeg_path, source, partial),
                total_seconds=duration, on_progress=self.on_progress,
                should_stop=self.should_stop, ceiling=COPY_TIMEOUT_SECONDS,
                clock=self.clock, popen=self.popen)
            got: Optional[float] = None
            if code == 0:
                _codec, got = probe_audio(self.ffmpeg_path, partial)
            if code == 0 and (duration is None or got is None
                              or abs(got - duration) <= DURATION_TOLERANCE_SECONDS):
                _publish(partial, final, source)
                return final.name
            log.info("media jobs: %s: the aac copy is not usable (rc=%s, %s "
                     "against %s s) -- decoding to opus instead",
                     source.name, code, got, duration)
            discard(partial)
            return None
        finally:
            release_partial(partial)

    # -- proxy-480p ------------------------------------------------------
    def _proxy(self, source: Path, out_dir: Path,
               stem: str) -> tuple[list[str], bool, Optional[float]]:
        """`_vid_make` (:1637)."""
        final = out_dir / f"{stem}{VID_EXT}"
        if is_fresh(final, source):
            return [final.name], True, None
        codec, _width, _height, fps = probe_video(self.ffmpeg_path, source)
        if not codec:
            raise MediaJobError("no video track", retryable=False)
        _acodec, source_audio = probe_audio(self.ffmpeg_path, source)
        gop = max(1, int(round(fps or 30)))
        out_dir.mkdir(parents=True, exist_ok=True)

        def encode(partial: Path) -> None:
            self._require(_run_ffmpeg(
                proxy_cmd(self.ffmpeg_path, source, partial, gop, self.nvenc),
                total_seconds=source_audio, on_progress=self.on_progress,
                should_stop=self.should_stop, ceiling=ENCODE_TIMEOUT_SECONDS,
                clock=self.clock, popen=self.popen))
            # The proxy's audio is a re-encode, and the lane plays picture and
            # sound off this ONE element: if it came out a different length,
            # say so, rather than let the window drift quietly (_vid_make's
            # own check, kept, and it is a WARNING and not a failure -- a
            # proxy that is 40 ms out is still far better than no picture).
            _codec, made = probe_audio(self.ffmpeg_path, partial)
            if source_audio and made and \
                    abs(source_audio - made) > DURATION_TOLERANCE_SECONDS:
                log.warning("media jobs: %s: the proxy's audio is %.3f s "
                            "against the source's %.3f s",
                            source.name, made, source_audio)

        self._with_partial(final, source, encode)
        return [final.name], False, source_audio

    # -- peaks -----------------------------------------------------------
    def _peaks(self, source: Path, out_dir: Path,
               stem: str) -> tuple[list[str], bool, Optional[float]]:
        """`_peaks_make` (:1190), including the header-byte rule.

        A file made at another rate is REMADE, not kept: the page's own
        `peaks_state` does exactly this, and the two must agree or the cache
        is rebuilt on every view.
        """
        final = out_dir / f"{stem}{PEAKS_EXT}"

        def current() -> bool:
            return is_fresh(final, source) and _peaks_rate(final) == PEAK_RATE

        if current():
            return [final.name], True, None
        out_dir.mkdir(parents=True, exist_ok=True)
        _codec, duration = probe_audio(self.ffmpeg_path, source)
        code, raw, err = _read_pcm(
            peaks_cmd(self.ffmpeg_path, source), should_stop=self.should_stop,
            ceiling=COPY_TIMEOUT_SECONDS, clock=self.clock, popen=self.popen)
        if code != 0:
            raise MediaJobError(err or f"ffmpeg exited {code}")
        if not raw:
            raise MediaJobError("there is no audio to draw", retryable=False)
        payload = peaks_bytes(raw)

        def write(partial: Path) -> None:
            partial.write_bytes(payload)

        self._with_partial(final, source, write, already_made=current)
        return [final.name], False, duration

    # -- the shared discipline -------------------------------------------
    def _with_partial(self, final: Path, source: Path,
                      work: Callable[[Path], None],
                      already_made: Optional[Callable[[], bool]] = None) -> None:
        """Rule 2, in one place: claim the output, do the work into
        `<final>.partial`, publish only if nothing else got there first, and
        always let go of the claim.

        `already_made` is what "got there first" MEANS, and peaks needs its
        own: a `.peaks` written at another rate is newer than its source and
        still has to be replaced, so the mtime test alone would let a stale
        50/s file refuse every remake for ever.
        """
        partial = Path(str(final) + PARTIAL_SUFFIX)
        if not claim_partial(partial):
            raise MediaJobError(
                f"another writer on this machine already has {partial.name} "
                f"-- leaving it to them")
        try:
            work(partial)
            _publish(partial, final, source, already_made)
        except MediaJobError:
            discard(partial)
            raise
        except Exception as exc:                                # noqa: BLE001
            discard(partial)
            raise MediaJobError(str(exc)) from exc
        finally:
            release_partial(partial)

    @staticmethod
    def _require(outcome: tuple[int, str]) -> None:
        code, err = outcome
        if code != 0:
            raise MediaJobError(err or f"ffmpeg exited {code}")


def _peaks_rate(path: Path) -> Optional[int]:
    """The rate byte out of a `.peaks` header, or None if it is not one."""
    try:
        with open(path, "rb") as handle:
            head = handle.read(3)
    except OSError:
        return None
    return head[2] if len(head) == 3 and head[:2] == b"PK" else None
