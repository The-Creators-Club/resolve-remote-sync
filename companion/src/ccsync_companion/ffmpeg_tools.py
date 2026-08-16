"""ffmpeg/ffprobe wrappers for the companion's proxy generator.

REHOMED from `broll/indexer/broll_index/ffmpeg_tools.py` (2026-08-10), copied
rather than imported -- same call as `music_worker.py:1-16`. The indexer is a
base-rig pipeline with its own venv and a system ffmpeg on PATH; the companion
is a frozen, windowed app on every editor machine, so the two modules cannot
share a file without dragging the indexer's assumptions onto the fleet. What
changed in the move:

  * every entry point takes `ffmpeg_path` (the `ffmpeg_path` config key). The
    indexer hardcodes the bare name "ffmpeg" because PATH is guaranteed there;
    on an editor machine the binary is wherever the installer put it, and a
    LaunchAgent's PATH is /usr/bin:/bin:/usr/sbin:/sbin (see the INST-7 note in
    the generated config.toml -- the same reason `rclone_path` exists).
  * every subprocess carries `creationflags=_win_creationflags()`. The indexer
    runs in a console; the companion does not (build.spec, console=False), so
    an unflagged spawn flashes a black window on the editor's desktop for each
    probe.
  * `ffmpeg_available()` is new, modeled on `rclone_lane.rclone_available` --
    ffmpeg is optional here (absent = notifier-only), so "is it there?" is a
    question this module has to answer without raising, and cheaply enough to
    ask on every tick.
  * the encoding functions became PURE ARGV BUILDERS. The indexer's
    `build_proxy` runs, verifies and retries in one call; the companion's
    proxy_gen needs Popen with a drained stderr pipe, a 2 s poll for "the user
    came back", and a kill path -- none of which fits inside a subprocess.run.
    Splitting argv from execution also makes the flag set testable without an
    ffmpeg anywhere near the suite.
  * `probe_video()` gained timecode extraction (ship-blocker: Resolve's
    LinkProxyMedia refuses a proxy whose timecode does not match the original,
    proxy_relink.py:35-37) plus audio facts, and lost `shot_date`, which only
    the search index cares about.

The 540p preview spec below is deliberately IDENTICAL to the b-roll one, so a
proxy generated for a YouTube download doubles as its b-roll preview. If the
b-roll side ever changes, this file has to change with it -- test_ffmpeg_tools
asserts the whole preview flag subsequence literally so that drift is loud.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional

log = logging.getLogger("ccsync.ffmpeg")

# Decode subprocess output as UTF-8 rather than the system codepage. Windows
# defaults to the locale codec (cp1252 here, cp950 on a zh-TW box), which
# raises UnicodeDecodeError on ffprobe/ffmpeg output carrying CJK titles or
# metadata -- real archive filenames hit this immediately. errors="replace"
# keeps a stray undecodable byte from killing a whole encode.
TEXT_UTF8 = {"text": True, "encoding": "utf-8", "errors": "replace"}


class UnreadableMediaError(RuntimeError):
    """This file cannot be read as media -- not a transient failure.

    Seen on the real archive: a 108 MB .mp4 with a valid `ftyp` header but no
    `moov` atom, i.e. an incomplete download. Re-running will never fix it, so
    the message needs to say WHY rather than just echoing the command line.

    The companion raises this for subprocess plumbing failures too (ffprobe
    missing, timing out, emitting non-JSON). The caller -- proxy_gen -- has
    exactly one response to any of them: count the attempt and move on to the
    next clip. Two exception types would buy it nothing and give it a way to
    crash its own worker thread.
    """


def _win_creationflags() -> int:
    """CREATE_NO_WINDOW: a duplicate of `rclone_lane._win_creationflags`
    (:326-334), which itself mirrors `upgrade._default_spawn`. Copied a third
    time rather than imported because this module must not pull the sync
    package in (proxy generation runs on the base rig with `sync_enabled=false`
    and no lane objects at all), and one `if sys.platform` is a smaller debt
    than that import edge. Every ffmpeg/ffprobe spawn needs it: the companion
    is a windowed build (build.spec, console=False), so an unflagged spawn
    flashes a console window on the editor's desktop -- and the generator
    spawns one per clip, unattended, which would be a strobe light.
    A no-op (0) off Windows."""
    if sys.platform == "win32":
        return subprocess.CREATE_NO_WINDOW
    return 0


# ---------------------------------------------------------------------------
# locating the binaries
# ---------------------------------------------------------------------------

def _managed_binary(name: str) -> Optional[str]:
    """The companion-installed copy of a bare `ffmpeg`/`ffprobe`, or None.

    sidecar_tools (2026-08-16) puts a pinned static ffmpeg + ffprobe into the
    same tools dir yt-dlp lives in, because no editor machine had one and the
    local YouTube downloader cannot merge without it. It is a FALLBACK behind
    PATH on purpose: an editor's own install (`winget install Gyan.FFmpeg`,
    brew) keeps winning, exactly as before, and this only answers when the
    bare name resolves to nothing. Only the bare default names are mapped --
    an explicit `ffmpeg_path` that does not exist stays not-found rather than
    silently running a different binary. Deferred import: sidecar_tools
    imports this module for the own-install check."""
    stem = os.path.basename(name).lower()
    for suffix in (".exe", ""):
        if stem.endswith(suffix):
            stem = stem[: len(stem) - len(suffix)] if suffix else stem
            break
    if stem not in ("ffmpeg", "ffprobe") or os.path.dirname(name):
        return None
    try:
        from . import sidecar_tools
        candidate = sidecar_tools.managed_path(stem)
        return str(candidate) if candidate.is_file() else None
    except Exception:
        return None


def _resolve_binary(path: str, managed_fallback: bool = True) -> Optional[str]:
    """Absolute path to `path`, or None if it isn't there. Never raises.

    A bare name goes through PATH first and then, unless `managed_fallback`
    is off, the companion's own tools dir (_managed_binary)."""
    try:
        if not os.path.isabs(path):
            found = shutil.which(path)
            if found is None and managed_fallback:
                found = _managed_binary(path)
            return found
        return path if os.path.exists(path) else None
    except OSError:
        return None


def ffprobe_for(ffmpeg_path: str) -> str:
    """The ffprobe that belongs to `ffmpeg_path`.

    Every ffmpeg distribution ships ffprobe beside ffmpeg, and the installer
    drops both in one directory, so the sibling is the right answer AND the
    only one that works when the binaries are deliberately kept off PATH (the
    rclone_path precedent again). Falling back to the bare name keeps a
    PATH-installed ffmpeg (`winget install Gyan.FFmpeg`) working when
    `ffmpeg_path` is itself just "ffmpeg" and shutil.which comes up empty
    because PATH changed since the probe.
    """
    resolved = _resolve_binary(ffmpeg_path)
    if resolved:
        directory = os.path.dirname(resolved)
        stem = os.path.basename(resolved)
        # Preserve the ".exe" (or any other suffix the platform uses) rather
        # than assuming: a frozen ffmpeg.exe next to a bare "ffprobe" is not a
        # combination that exists in the wild.
        candidate = os.path.join(directory, stem.replace("ffmpeg", "ffprobe", 1))
        if candidate != resolved and os.path.exists(candidate):
            return candidate
    return "ffprobe"


# Successful `ffmpeg -version` probes are cached for this long, per path.
# Same reasoning as RCLONE_PROBE_TTL_SECONDS (rclone_lane.py:468-475): the
# generator's tick asks "is ffmpeg there?" every 15 s and the tray asks again
# for its menu, and each miss is a window-suppressed CreateProcess plus a
# binary load purely to re-learn what was true 200 ms ago. Only SUCCESSES are
# cached -- a missing or broken ffmpeg must be re-probed every time so the
# generator starts working the instant it is installed, with no restart.
FFMPEG_PROBE_TTL_SECONDS = 300.0
_ffmpeg_probe_cache: dict[str, tuple[float, str]] = {}
_ffmpeg_probe_lock = threading.Lock()


def reset_ffmpeg_available_cache() -> None:
    """Drop every cached probe result (config change repointing ffmpeg_path,
    a Phase-2 installer step that just put ffmpeg there, or tests)."""
    with _ffmpeg_probe_lock:
        _ffmpeg_probe_cache.clear()


def ffmpeg_available(ffmpeg_path: str, use_cache: bool = True) -> tuple[bool, str]:
    """Check whether `ffmpeg_path` resolves to a runnable ffmpeg binary.

    Returns (available, message). Never raises -- ffmpeg is an OPTIONAL
    dependency (absent means the companion still notifies about proxy gaps,
    it just can't fill them), so no caller of this is prepared for a throw.
    """
    if use_cache:
        with _ffmpeg_probe_lock:
            entry = _ffmpeg_probe_cache.get(ffmpeg_path)
        if entry is not None and (time.monotonic() - entry[0]) < FFMPEG_PROBE_TTL_SECONDS:
            return True, entry[1]

    resolved = ffmpeg_path
    if not os.path.isabs(ffmpeg_path):
        found = shutil.which(ffmpeg_path) or _managed_binary(ffmpeg_path)
        if found is None:
            return False, f"ffmpeg not found on PATH ('{ffmpeg_path}')"
        resolved = found
    elif not os.path.exists(resolved):
        return False, f"ffmpeg not found at '{resolved}'"

    try:
        proc = subprocess.run(
            [resolved, "-version"],
            capture_output=True,
            timeout=10,
            encoding="utf-8",
            errors="replace",
            creationflags=_win_creationflags(),
        )
    except Exception as exc:
        return False, f"ffmpeg at '{resolved}' failed to run: {exc}"
    if proc.returncode != 0:
        return False, f"ffmpeg at '{resolved}' exited {proc.returncode}"
    with _ffmpeg_probe_lock:
        _ffmpeg_probe_cache[ffmpeg_path] = (time.monotonic(), resolved)
    return True, resolved


# ---------------------------------------------------------------------------
# encoder detection
# ---------------------------------------------------------------------------

# The only encoders this module ever names. Reporting the full `-encoders`
# output (several hundred lines) to the dashboard would be absurd, and the
# generator only ever chooses between a GPU and a CPU path per quality tier.
INTERESTING_ENCODERS = ("hevc_nvenc", "h264_nvenc", "libx265", "libx264")

_encoder_cache: dict[str, frozenset[str]] = {}
_encoder_lock = threading.Lock()


def reset_encoder_cache() -> None:
    """Forget which encoders each ffmpeg reported (tests, or a config change
    repointing ffmpeg_path at a differently-built binary)."""
    with _encoder_lock:
        _encoder_cache.clear()


def detect_encoders(ffmpeg_path: str) -> frozenset[str]:
    """Which of INTERESTING_ENCODERS this ffmpeg build offers. Never raises.

    Cached without a TTL, unlike the availability probe: a binary's encoder
    list cannot change while it sits on disk, and `-encoders` is the expensive
    end of ffmpeg's startup. An empty set is NOT cached -- it means the probe
    itself failed (missing binary, timeout), and the generator would otherwise
    be stuck on the CPU path for the life of the process because ffmpeg was
    briefly unreachable on a network drive.

    NB an encoder being LISTED is not proof it will run: NVENC on a machine
    with no NVIDIA GPU (or with every session already taken) is compiled in and
    fails at encode time. That is why the generator keeps its one-shot CPU
    retry rather than trusting this.
    """
    with _encoder_lock:
        cached = _encoder_cache.get(ffmpeg_path)
    if cached is not None:
        return cached

    try:
        proc = subprocess.run(
            [ffmpeg_path, "-hide_banner", "-encoders"],
            capture_output=True,
            timeout=20,
            encoding="utf-8",
            errors="replace",
            creationflags=_win_creationflags(),
        )
    except Exception as exc:
        log.debug("ffmpeg -encoders failed for %s: %s", ffmpeg_path, exc)
        return frozenset()
    if proc.returncode != 0:
        log.debug("ffmpeg -encoders exited %s for %s", proc.returncode, ffmpeg_path)
        return frozenset()

    text = proc.stdout or ""
    # Substring match on the whole listing, exactly as the indexer did: the
    # line format (" V....D hevc_nvenc  NVIDIA NVENC hevc encoder") has moved
    # between ffmpeg releases, and the names are distinctive enough that a
    # false positive would need an encoder description to quote one.
    found = frozenset(name for name in INTERESTING_ENCODERS if name in text)
    if found:
        with _encoder_lock:
            _encoder_cache[ffmpeg_path] = found
    return found


# ---------------------------------------------------------------------------
# probe
# ---------------------------------------------------------------------------

# A probe of a file on a sleeping USB drive or a stalled SMB mount can sit
# there indefinitely; the generator's worker thread is the one that would be
# stuck, and it is also the thread that has to notice "the user came back".
PROBE_TIMEOUT_SECONDS = 60


def _parse_fps(rate: str) -> Optional[float]:
    if not rate or rate in ("0/0",):
        return None
    if "/" in rate:
        num, _, den = rate.partition("/")
        try:
            num_f, den_f = float(num), float(den)
        except ValueError:
            return None
        return num_f / den_f if den_f else None
    try:
        return float(rate)
    except ValueError:
        return None


def _float_or_none(value) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _tags(obj) -> dict:
    """`tags` off a format/stream dict, tolerating both a missing key and an
    explicit JSON null (ffprobe emits both, depending on version)."""
    if not isinstance(obj, dict):
        return {}
    tags = obj.get("tags")
    return tags if isinstance(tags, dict) else {}


def _timecode_from(info: dict) -> Optional[str]:
    """The source timecode, or None.

    Order matters and is not arbitrary. Container-level (`format.tags.timecode`)
    is what QuickTime/MP4 recordings carry and what ffmpeg's own `-timecode`
    writes back, so a round trip through us is stable. MXF and many camera
    formats instead carry a dedicated `tmcd` timecode TRACK, which surfaces as
    a data stream with the same tag; that is the fallback.

    None is a legitimate answer (screen recordings, YouTube downloads have no
    timecode at all) and must not be confused with failure -- the generator
    simply omits `-timecode`, and Resolve's LinkProxyMedia is happy as long as
    neither side claims one.
    """
    container = _tags(info.get("format")).get("timecode")
    if container:
        return str(container)
    for stream in info.get("streams", []) or []:
        if not isinstance(stream, dict):
            continue
        is_tmcd = (
            stream.get("codec_tag_string") == "tmcd"
            or stream.get("codec_type") == "data"
        )
        if not is_tmcd:
            continue
        value = _tags(stream).get("timecode")
        if value:
            return str(value)
    return None


# The only rates drop-frame timecode exists at. 23.976 is fractional too but
# has no DF variant; integer rates never drop. Copied from
# broll/indexer/broll_index/ffmpeg_tools.py:97-99 with dropframe_normalized
# below -- the two modules already keep the 540p preview spec identical by
# hand, and this is the same kind of shared fact.
NTSC_DF_RATES = (29.97, 59.94)


def dropframe_normalized(tc: Optional[str], fps: Optional[float]) -> Optional[str]:
    """The timecode string as Resolve will count it against an NTSC source.

    Sony bodies store the start TC in an rtmd data stream whose tag prints
    with COLONS even when the camera counts drop-frame -- and at 59.94 the
    non-drop reading of "03:40:27:12" is a different absolute frame than the
    drop reading, so a proxy carrying the tag verbatim fails the
    LinkProxyMedia validation R10 exists for (proven live 2026-08-12: colon
    form refused, semicolon form accepted, byte-identical otherwise; the
    matching clip property in Resolve reads "Drop frame: 1"). A genuinely
    non-drop NTSC source would get a wrong (semicolon) form here and its link
    would be refused -- which is the status quo for it, never a wrong pairing:
    Resolve validates every attach.

    Ported verbatim from the indexer (COMP-MEDIA-1, 2026-08-14): R10's second
    half landed only on the b-roll preview pipeline, so the companion -- which
    makes the fleet's EDITING proxies -- kept writing the colon form.
    test_ffmpeg_tools carries the indexer's own regression test so the two
    copies cannot drift again.
    """
    if not tc or ";" in tc or fps is None:
        return tc
    if not any(abs(fps - rate) < 0.01 for rate in NTSC_DF_RATES):
        return tc
    head, sep, frames = tc.rpartition(":")
    return f"{head};{frames}" if sep else tc


def probe_video(ffmpeg_path: str, path: str | Path) -> dict:
    """Facts about a source clip, or UnreadableMediaError.

    Returns {duration_s, fps, width, height, codec, has_audio,
    audio_channels, timecode}. `timecode` is DROP-FRAME NORMALIZED against
    `fps` before it is returned, so every caller -- own_proxy_cmd today, any
    other tomorrow -- writes the form Resolve counts in (COMP-MEDIA-1,
    2026-08-14; see dropframe_normalized). `has_audio` decides nothing here -- the argv
    builders always ask for AAC, and ffmpeg ignores an audio codec for a
    silent input -- but the generator reports it, and a clip with no audio
    stream at all is worth being able to see when a proxy comes back silent.
    """
    cmd = [
        ffprobe_for(ffmpeg_path), "-v", "error",
        "-print_format", "json",
        "-show_format", "-show_streams",
        str(path),
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=PROBE_TIMEOUT_SECONDS,
            creationflags=_win_creationflags(),
            **TEXT_UTF8,
        )
    except subprocess.TimeoutExpired:
        raise UnreadableMediaError(
            f"ffprobe timed out after {PROBE_TIMEOUT_SECONDS}s on "
            f"{Path(path).name} -- unreachable drive, or a file still being written"
        )
    except OSError as exc:
        # Missing/unrunnable ffprobe. Deliberately the same exception type as
        # bad media: proxy_gen treats "can't probe this clip" as one outcome.
        raise UnreadableMediaError(f"ffprobe could not be run ({cmd[0]}): {exc}")

    if result.returncode != 0:
        err = (result.stderr or "").strip()
        hint = ""
        if "moov atom not found" in err:
            hint = " -- file is truncated or incompletely downloaded"
        elif "Invalid data found" in err:
            hint = " -- file is not valid media"
        raise UnreadableMediaError(
            f"ffprobe failed on {Path(path).name}: {err[:200]}{hint}"
        )

    try:
        info = json.loads(result.stdout or "")
    except ValueError as exc:
        raise UnreadableMediaError(f"ffprobe output on {Path(path).name} was not JSON: {exc}")
    if not isinstance(info, dict):
        raise UnreadableMediaError(f"ffprobe output on {Path(path).name} was not an object")

    fmt = info.get("format") or {}
    streams = [s for s in (info.get("streams") or []) if isinstance(s, dict)]
    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video_stream is None:
        # An audio-only or metadata-only file that landed in a video directory.
        # There is nothing to make a proxy of, and it is never going to change.
        raise UnreadableMediaError(f"{Path(path).name} has no video stream")
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)

    duration_s = _float_or_none(fmt.get("duration"))
    if duration_s is None:
        duration_s = _float_or_none(video_stream.get("duration"))

    fps = _parse_fps(video_stream.get("avg_frame_rate", "") or "") or _parse_fps(
        video_stream.get("r_frame_rate", "") or ""
    )

    return {
        "duration_s": duration_s,
        "fps": fps,
        "width": video_stream.get("width"),
        "height": video_stream.get("height"),
        "codec": video_stream.get("codec_name"),
        "has_audio": audio_stream is not None,
        "audio_channels": (audio_stream or {}).get("channels"),
        # Normalized HERE rather than in the argv builder: the tag is only
        # wrong relative to the source's frame rate, and this is the one place
        # that holds both (COMP-MEDIA-1, 2026-08-14).
        "timecode": dropframe_normalized(_timecode_from(info), fps),
    }


# ---------------------------------------------------------------------------
# argv builders -- PURE. No I/O, no probing, no filesystem.
# ---------------------------------------------------------------------------
#
# Everything below returns a list[str] and touches nothing. proxy_gen owns the
# spawning (Popen, drained stderr, BELOW_NORMAL priority, 2 s kill poll), and
# keeping the flags here means the whole encoding spec is assertable in a unit
# test on a machine with no ffmpeg -- which is every CI-shaped machine and most
# of the fleet.

# -- own footage: HEVC Main-10, 1080p, ~7 Mbps ----------------------------
#
# Chosen to match the FF4-era Resolve proxies already in the tree, so a
# generated proxy and a hand-made one look and cut the same. 10-bit is not
# vanity: the source is 10-bit log, and an 8-bit proxy bands visibly in the
# sky the moment anyone puts a LUT on the viewer.
OWN_MAX_HEIGHT = 1080
OWN_BITRATE = "7M"
OWN_AUDIO_BITRATE = "192k"

# VBR headroom, as multiples of the target bitrate: 7M -> 10M peak, 14M buffer.
# The peak exists so a hard pan or a grain-heavy shot doesn't smear; the buffer
# is the usual 2 s at peak. Derived rather than hardcoded so that overriding
# `proxy_gen_bitrate` moves all three numbers together -- a config with a 20M
# target and a 10M ceiling would clamp every busy frame and nobody would know.
OWN_MAXRATE_FACTOR = 1.43
OWN_BUFSIZE_FACTOR = 2.0

_RATE_RE = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*([kKmMgG]?)\s*$")


def _scaled_rate(bitrate: str, factor: float) -> str:
    """`bitrate` times `factor`, in the unit it was written in ("7M" -> "10M").

    An unparseable bitrate returns the input unchanged, which yields
    maxrate == bufsize == bitrate: a valid, merely conservative, encode. The
    alternative -- raising -- would turn a typo in config.toml into a
    generator that never runs, and config validation already warns about it.
    """
    match = _RATE_RE.match(bitrate or "")
    if not match:
        return bitrate
    value, unit = float(match.group(1)), match.group(2)
    scaled = value * factor
    # Integers stay integers ("10M", not "10.01M"): ffmpeg accepts both, but
    # the log line and the dashboard field are read by people.
    return f"{round(scaled)}{unit}" if scaled >= 1 else f"{scaled:g}{unit}"


def own_proxy_cmd(
    ffmpeg_path: str,
    src: str | Path,
    dest: str | Path,
    *,
    nvenc: bool,
    max_height: int = OWN_MAX_HEIGHT,
    bitrate: str = OWN_BITRATE,
    timecode: Optional[str] = None,
) -> list[str]:
    """argv for an own-footage proxy: HEVC Main-10, `max_height`p, ~`bitrate`.

    `timecode` (from probe_video) is the ship-blocker: Resolve's
    LinkProxyMedia refuses a proxy whose timecode doesn't match the original
    (proxy_relink.py:35-37), and an mp4 written without one starts at
    00:00:00:00. It is omitted entirely when the source has none -- writing a
    zero timecode onto a source that claims none is a mismatch of its own.
    """
    maxrate = _scaled_rate(bitrate, OWN_MAXRATE_FACTOR)
    bufsize = _scaled_rate(bitrate, OWN_BUFSIZE_FACTOR)

    if nvenc:
        # p5 is the slow-ish end of the NVENC presets: this runs while the user
        # is away, so encode speed is worth trading for bitrate efficiency.
        video_codec = [
            "-c:v", "hevc_nvenc",
            "-profile:v", "main10",
            "-pix_fmt", "p010le",
            "-preset", "p5",
            "-rc", "vbr",
            "-b:v", bitrate,
            "-maxrate", maxrate,
            "-bufsize", bufsize,
        ]
    else:
        video_codec = [
            "-c:v", "libx265",
            "-pix_fmt", "yuv420p10le",
            "-preset", "medium",
            "-b:v", bitrate,
            "-maxrate", maxrate,
            "-bufsize", bufsize,
            # x265 prints its encoder banner and a per-run summary on stderr
            # unconditionally, which the generator's bounded stderr deque would
            # otherwise store instead of the actual error when one comes.
            "-x265-params", "log-level=error",
        ]

    cmd = [
        ffmpeg_path, "-y", "-hide_banner", "-loglevel", "error", "-nostats",
        "-i", str(src),
        # ffmpeg's DEFAULT stream selection takes exactly one video and one
        # audio stream, and camera originals in this tree routinely carry two
        # or more (Sony/Canon MXF dual pairs, dual-system, .mts): without this
        # the editor cuts on a proxy whose scratch/lav track simply is not
        # there, and it reappears only on the original (MED-1, 2026-08-11).
        # `0:a?` rather than `0:a` because a silent original must still encode.
        "-map", "0:v:0", "-map", "0:a?",
        # Carry the source's metadata (creation time, camera tags, reel name)
        # into the proxy: Resolve reads several of them when matching a proxy
        # to its original, and losing them costs nothing to avoid.
        "-map_metadata", "0",
    ]
    if timecode:
        cmd += ["-timecode", str(timecode)]
    cmd += [
        # Never upscale: a 720p source should stay 720p rather than being
        # inflated to the proxy height, which costs bytes and adds nothing.
        # trunc(.../2)*2 because -2 only guarantees the WIDTH is even: an
        # odd-height source (RGB/4:4:4 screen capture, ffv1/utvideo) passed its
        # height straight through and died at encoder init, which the failure
        # cap then made permanent (MED-12, 2026-08-11).
        "-vf", f"scale=-2:'trunc(min({max_height},ih)/2)*2'",
        *video_codec,
        # QuickTime and Resolve refuse HEVC-in-mp4 tagged with the default
        # `hev1`; `hvc1` is the tag both accept. Without it the file plays in
        # VLC, which is exactly how this gets missed until an editor's timeline
        # shows Media Offline.
        "-tag:v", "hvc1",
        "-c:a", "aac", "-b:a", OWN_AUDIO_BITRATE,
        "-movflags", "+faststart",
        # The generator encodes to `<name>.mp4.partial` and ffmpeg chooses the
        # muxer by extension: ".partial" names none, so without an explicit
        # format EVERY encode dies at muxer init (EINVAL) before a single
        # frame -- the whole 1040-clip base-rig queue, overnight 2026-08-11.
        "-f", "mp4",
        str(dest),
    ]
    return cmd


# -- YouTube downloads: the b-roll preview spec, verbatim ------------------
#
# Proxy encoding defaults, copied unchanged from
# broll/indexer/broll_index/ffmpeg_tools.py:125-139 -- the justification is the
# reason to keep them identical:
#
# Measured on real archive footage: at 720p/cq26 the proxy came out at ~95% of
# source size, because these archives are YouTube downloads that are ALREADY
# compressed -- re-encoding 1080p->720p at high quality saves almost nothing.
# On a 1 TB queue that is ~991 GB of proxies, more than the free disk.
#
# 540p/cq34 measured ~3.7x smaller (~4.5 MB/min vs ~17 MB/min) across three
# sample files. The quality cost is acceptable because proxies exist only for
# browsing and choosing shots in the web player: "Send to Resolve" inserts the
# ORIGINAL media, so nothing downstream is degraded by a small proxy.
PROXY_HEIGHT = 540
PROXY_CQ = 34          # h264_nvenc constant-quality
PROXY_CRF = 30         # libx264 equivalent, used when NVENC is unavailable
PROXY_AUDIO_BITRATE = "96k"


def preview_proxy_cmd(
    ffmpeg_path: str,
    src: str | Path,
    dest: str | Path,
    *,
    nvenc: bool,
    height: int = PROXY_HEIGHT,
    cq: int = PROXY_CQ,
    crf: int = PROXY_CRF,
) -> list[str]:
    """argv for a 540p browsing proxy -- byte-for-byte the b-roll spec.

    No `-timecode`/`-map_metadata` here, unlike own_proxy_cmd: this tier exists
    for downloaded footage, which has no timecode to preserve, and the output
    is meant to be interchangeable with one the b-roll indexer produced. Any
    extra flag here would make the two pipelines produce different files for
    the same input, which is the whole thing this tier is trying to avoid.
    """
    video_codec = ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", str(cq)] if nvenc else [
        "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
    ]
    return [
        ffmpeg_path, "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(src),
        # Never upscale: a 360p source should stay 360p rather than being
        # inflated to the proxy height, which costs bytes and adds nothing.
        # The even-height trunc is the ONE thing in this argv that is not
        # byte-identical to the b-roll indexer's build_proxy: -2 guards the
        # width only, and an odd-height source fails at encoder init (MED-12,
        # 2026-08-11). The indexer needs the same edit for parity; until it
        # gets one the two differ on odd-height sources ONLY, where the
        # indexer's version does not encode at all.
        "-vf", f"scale=-2:'trunc(min({height},ih)/2)*2'",
        *video_codec,
        "-c:a", "aac", "-b:a", PROXY_AUDIO_BITRATE,
        "-movflags", "+faststart",
        # The one deliberate divergence from the b-roll indexer's argv, and it
        # changes no output byte: the indexer writes straight to `<name>.mp4`,
        # this pipeline writes to `<name>.mp4.partial`, and ffmpeg cannot pick
        # a muxer from ".partial" (EINVAL at init, overnight 2026-08-11).
        "-f", "mp4",
        str(dest),
    ]


# -- verification ---------------------------------------------------------

def verify_decodes_cmd(ffmpeg_path: str, path: str | Path) -> list[str]:
    """argv that decodes a file end to end into nothing, printing only errors.

    Container metadata (duration, dimensions) can look perfectly correct while
    the bitstream is damaged, so checking ffprobe output is NOT enough -- only
    a real decode catches it. Measured on the b-roll archive: 17% of proxies
    produced under 6-way concurrent NVENC had corrupt bitstreams ("Invalid NAL
    unit size") while reporting the right duration and resolution.
    """
    return [ffmpeg_path, "-v", "error", "-i", str(path), "-f", "null", "-"]


def count_decode_errors(stderr_text: Optional[str]) -> int:
    """How many libav errors a verify_decodes_cmd run reported.

    `-v error` prints one line per problem and nothing at all for a clean
    decode, so the count is just the non-blank lines. Blank-line tolerant on
    purpose: the stream arrives having been through a bounded deque and a
    line-ending translation, and a trailing "\\n" must not read as one error --
    that would condemn every good proxy the generator makes.
    """
    return len([ln for ln in (stderr_text or "").splitlines() if ln.strip()])
