"""ffprobe/ffmpeg wrappers: probing, proxy/sprite/poster generation, scene-detect frame
extraction, and contact-sheet building. All ffmpeg specifics per SPEC.md's "ffmpeg
specifics" section.
"""

from __future__ import annotations

import json
import math
import re
import subprocess
from functools import lru_cache
from pathlib import Path

# Decode subprocess output as UTF-8 rather than the system codepage. Windows
# defaults to the locale codec (cp950 on a zh-TW box), which raises
# UnicodeDecodeError on ffprobe/ffmpeg output carrying CJK titles or metadata —
# real archive filenames hit this immediately. errors="replace" keeps a stray
# undecodable byte from killing a whole indexing run.
TEXT_UTF8 = {"text": True, "encoding": "utf-8", "errors": "replace"}


# ---------------------------------------------------------------------------
# probe
# ---------------------------------------------------------------------------

class UnreadableMediaError(RuntimeError):
    """The file cannot be read as media at all — not a transient failure.

    Seen on the real archive: a 108 MB .mp4 with a valid `ftyp` header but no
    `moov` atom, i.e. an incomplete download. Re-running will never fix it, so
    the message needs to say WHY rather than just echoing the command line —
    the operator's action is to re-download the source.
    """


def run_ffprobe(path: str | Path) -> dict:
    cmd = [
        "ffprobe", "-v", "error",
        "-print_format", "json",
        "-show_format", "-show_streams",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, **TEXT_UTF8)
    if result.returncode != 0:
        err = (result.stderr or "").strip()
        hint = ""
        if "moov atom not found" in err:
            hint = " — file is truncated or incompletely downloaded"
        elif "Invalid data found" in err:
            hint = " — file is not valid media"
        raise UnreadableMediaError(f"ffprobe failed on {Path(path).name}: {err[:200]}{hint}")
    return json.loads(result.stdout)


def _parse_fps(rate: str) -> float | None:
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


def _tags(obj) -> dict:
    """`tags` off a format/stream dict, tolerating both a missing key and an
    explicit JSON null (ffprobe emits both, depending on version)."""
    if not isinstance(obj, dict):
        return {}
    tags = obj.get("tags")
    return tags if isinstance(tags, dict) else {}


def timecode_from_probe(info: dict) -> tuple[str | None, bool]:
    """(start timecode, did a tmcd stream produce it) out of ffprobe output.

    The flag is what dropframe_normalized needs and nothing else can recover
    afterwards (audit F6, 2026-09-17). A `tmcd` track carries its own
    drop-frame BIT and ffprobe prints that bit AS THE SEPARATOR, so a colon
    from a tmcd file is a real non-drop timecode; a Sony body's `rtmd` data
    stream prints colons whatever the camera counted. Presence of a tmcd
    stream ANYWHERE decides it, not which tag the string came from: the mov
    demuxer copies the tmcd track's value up into `format.tags.timecode`, so
    the container tag on such a file is the tmcd track's own printing.
    Verified 2026-09-17 on both real cases: Johnny_Harris cam-1-050.mov
    (stream 2 data/tmcd, `13:53:30:02` at 30000/1001, genuinely non-drop) and
    an FX3 original (stream 2 data/rtmd, colon form, no tmcd stream).

    Order: container tag, then a tmcd stream, then any other stream tag.
    Container-level is what QuickTime/MP4 recordings carry and what ffmpeg's
    own `-timecode` writes back, so a round trip through us is stable; the
    tmcd/rtmd data stream is where MXF and most camera formats put it.
    Companion parity: ccsync_companion/ffmpeg_tools.timecode_from_probe.
    """
    streams = [s for s in (info.get("streams") or []) if isinstance(s, dict)]
    has_tmcd = any(s.get("codec_tag_string") == "tmcd" for s in streams)

    container = _tags(info.get("format")).get("timecode")
    if container:
        return str(container), has_tmcd
    for stream in streams:
        if stream.get("codec_tag_string") == "tmcd":
            value = _tags(stream).get("timecode")
            if value:
                return str(value), True
    for stream in streams:
        value = _tags(stream).get("timecode")
        if value:
            return str(value), has_tmcd
    return None, False


def read_timecode_source(path: str | Path) -> tuple[str | None, bool]:
    """read_timecode, plus whether a tmcd stream is what printed it.

    Never raises: a proxy without timecode is degraded, not a pipeline
    failure.
    """
    try:
        info = run_ffprobe(path)
    except Exception:
        return None, False
    return timecode_from_probe(info)


def read_timecode(path: str | Path) -> str | None:
    """The file's embedded start timecode (e.g. "03:40:27;12"), or None.

    Cameras write it as a tmcd track (QuickTime) or a format/stream tag.
    It matters because Resolve's LinkProxyMedia VALIDATES the pairing: a
    proxy with no embedded timecode is refused against a source that has one
    (KNOWN_BUGS R10, proven live 2026-08-12 -- remuxing the same bytes with
    -timecode flipped the identical link from refused to accepted).
    """
    return read_timecode_source(path)[0]


# The only rates drop-frame timecode exists at. 23.976 is fractional too but
# has no DF variant; integer rates never drop.
NTSC_DF_RATES = (29.97, 59.94)


def dropframe_normalized(tc: str | None, fps: float | None,
                        from_tmcd: bool = False) -> str | None:
    """The timecode string as Resolve will count it against an NTSC source.

    Sony bodies store the start TC in an rtmd data stream whose tag prints
    with COLONS even when the camera counts drop-frame -- and at 59.94 the
    non-drop reading of "03:40:27:12" is a different absolute frame than the
    drop reading, so a proxy carrying the tag verbatim fails the same
    LinkProxyMedia validation R10 exists for (proven live 2026-08-12: colon
    form refused, semicolon form accepted, byte-identical otherwise; the
    matching clip property in Resolve reads "Drop frame: 1").

    `from_tmcd` is the 2026-09-17 half of the rule (audit F6, plan
    BROLL_PROXY_TIERS_PLAN.md section 4): a tmcd track carries the drop-frame
    bit itself and ffprobe prints it as the separator, so THAT colon is a
    genuine non-drop timecode and rewriting it is what makes Resolve refuse
    the proxy. R17's tenth case is exactly this -- 231 of the Johnny Harris
    shoot's 377 proxies are 29.97 NDF with a tmcd track, and every one of
    their previews carried a semicolon the source never had. Normalise only
    what came from a file with no tmcd stream, i.e. the rtmd/format-tag case
    the 2026-08-12 fix was measured on.
    """
    if not tc or ";" in tc or fps is None or from_tmcd:
        return tc
    if not any(abs(fps - rate) < 0.01 for rate in NTSC_DF_RATES):
        return tc
    head, sep, frames = tc.rpartition(":")
    return f"{head};{frames}" if sep else tc


def _int_or_none(value) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def video_fps(info: dict) -> float | None:
    """The video stream's frame rate out of ffprobe output.

    Factored out of probe_video because build_proxy needs the rate from the
    SAME probe it reads the timecode from (2026-09-17): the preview's
    keyframe interval is one second of frames, and a second ffprobe of a
    multi-GB original on a network share costs more than the encode does.
    """
    streams = info.get("streams") or []
    video_stream = next((s for s in streams if s.get("codec_type") == "video"), {})
    return _parse_fps(video_stream.get("avg_frame_rate", "")) or _parse_fps(
        video_stream.get("r_frame_rate", "")
    )


def probe_video(path: str | Path) -> dict:
    """Return {duration_s, fps, width, height, codec, shot_date, frames,
    start_tc, bitrate} for a source file.

    Every key here is a `videos` COLUMN: stage_probe splats this dict straight
    into storage.update_video, so a key added without its migration is a SQL
    error on the next probe. The last three arrived with migration 012
    (2026-09-17, BROLL_PROXY_TIERS_PLAN.md section 5 / audit F3) -- the detail
    API decides `original_is_edit_weight` on the bitrate and phase 3 writes
    `frames`/`start_tc` into the interchange file that creates an offline
    clip, and neither can be re-derived inside the dashboard container without
    ffprobing a multi-GB original on the NAS on every detail view.

    `start_tc` is the timecode AS THE FILE PRINTS IT, deliberately not
    dropframe_normalized: this column describes the SOURCE, and the
    normalisation is a property of a proxy written against it.
    """
    info = run_ffprobe(path)
    fmt = info.get("format", {})
    streams = info.get("streams", [])
    video_stream = next((s for s in streams if s.get("codec_type") == "video"), {})

    duration_s = None
    if fmt.get("duration") is not None:
        duration_s = float(fmt["duration"])
    elif video_stream.get("duration") is not None:
        duration_s = float(video_stream["duration"])

    fps = video_fps(info)

    shot_date = None
    tags = fmt.get("tags", {}) or {}
    creation_time = tags.get("creation_time") or (video_stream.get("tags", {}) or {}).get("creation_time")
    if creation_time:
        shot_date = creation_time[:10]

    # The stream's own rate first: `format.bit_rate` is the whole container,
    # so a 1080p H.264 original with a PCM audio track reads 1.5 Mbps heavier
    # than its picture and would be called "not edit-weight" on the strength
    # of its sound.
    bitrate = _int_or_none(video_stream.get("bit_rate"))
    if bitrate is None:
        bitrate = _int_or_none(fmt.get("bit_rate"))

    return {
        "duration_s": duration_s,
        "fps": fps,
        "width": video_stream.get("width"),
        "height": video_stream.get("height"),
        "codec": video_stream.get("codec_name"),
        "shot_date": shot_date,
        "frames": _int_or_none(video_stream.get("nb_frames")),
        "start_tc": timecode_from_probe(info)[0],
        "bitrate": bitrate,
    }


# ---------------------------------------------------------------------------
# encoder detection
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def detect_nvenc_available() -> bool:
    try:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            capture_output=True, check=True, **TEXT_UTF8,
        )
    except (OSError, subprocess.CalledProcessError):
        return False
    return "h264_nvenc" in result.stdout


# ---------------------------------------------------------------------------
# proxy / sprite / poster
# ---------------------------------------------------------------------------

# Browser-preview encoding defaults.
#
# The history, because it is the argument for the numbers rather than against
# them. Measured 2026-08-11 on real archive footage: at 720p/cq26 the proxy
# came out at ~95% of source size, because that archive was YouTube downloads
# that were ALREADY compressed -- re-encoding 1080p->720p at high quality
# saved almost nothing, and on the 1 TB queue of the day that was ~991 GB of
# proxies, more than the free disk. 540p/cq34 measured ~3.7x smaller
# (~4.5 MB/min vs ~17 MB/min) across three sample files, and the quality cost
# was acceptable because the preview was ONLY ever browsed: "Send to Resolve"
# inserted the original media, so nothing downstream saw it.
#
# Both halves of that justification stopped holding on 2026-09-17
# (BROLL_PROXY_TIERS_PLAN.md section 4, owner's complaint 3): the editors
# cannot judge a clip at 540p, and in phase 3 this file becomes the FIRST
# PROXY RESOLVE LINKS on a remote machine, so it is cut on, not just browsed.
# 1080p at cq25/crf23 is roughly 3-5 Mbps, about 10x today's files (a 40 s
# clip goes from ~2 MB to ~20 MB); the archive's own originals are 6.5-8.3
# Mbps, so it is still a saving, and NEW CLIPS ONLY -- existing previews are
# not re-encoded (owner, 2026-09-17).
PROXY_HEIGHT = 1080
PROXY_CQ = 25          # h264_nvenc constant-quality
PROXY_CRF = 23         # libx264 equivalent, used when NVENC is unavailable
PROXY_AUDIO_BITRATE = "128k"


def count_frames_cmd(ffprobe_path: str, path: str | Path) -> list[str]:
    """argv that COUNTS the video packets in a file.

    `nb_frames` is a container field and is absent or a lie in exactly the
    cases that matter (an mp4 written by a killed encoder still carries the
    count it intended), so the check that decides whether a proxy is short
    counts packets instead. Parity: ccsync_companion/ffmpeg_tools.py, same
    name, same flags -- one of the two pipelines passing a proxy the other
    would reject is the whole reason both exist as one spec.
    """
    return [
        ffprobe_path, "-v", "error",
        "-count_packets",
        "-select_streams", "v:0",
        "-show_entries", "stream=nb_read_packets",
        "-print_format", "json",
        str(path),
    ]


def parse_frame_count(stdout_text: str | None) -> int | None:
    """The packet count out of a count_frames_cmd run, or None.

    None means "could not tell", never zero: the caller's response to an
    unreadable count is to SKIP the comparison, and a 0 would fail every
    proxy on a machine whose ffprobe printed something unexpected.
    """
    try:
        payload = json.loads(stdout_text or "")
        streams = payload.get("streams") or []
        return _int_or_none((streams[0] or {}).get("nb_read_packets"))
    except (ValueError, AttributeError, IndexError, TypeError):
        return None


def count_frames(path: str | Path) -> int | None:
    """How many video frames a file actually contains, or None.

    The Reproductive Rights lesson (2026-09-17): seven proxies were 1-18
    frames short of their originals, Resolve refused every one of them as a
    proxy, and nothing anywhere said so -- the editor saw "sync stuck". A
    preview is the first proxy Resolve links in phase 3, so a short one is a
    failed item, not a warning nobody reads.
    """
    try:
        result = subprocess.run(
            count_frames_cmd("ffprobe", path), capture_output=True, **TEXT_UTF8)
    except OSError:
        return None
    if result.returncode != 0:
        return None
    return parse_frame_count(result.stdout)


def verify_decodes(path: str | Path, max_errors: int = 0) -> int:
    """Decode a file end to end and return the count of libav errors.

    Container metadata (duration, dimensions) can look perfectly correct while
    the H.264 bitstream is damaged, so checking ffprobe output is NOT enough —
    only a real decode catches it. Measured: 17% of proxies produced under
    6-way concurrent NVENC had corrupt bitstreams ("Invalid NAL unit size")
    while reporting the right duration and resolution.
    """
    r = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-f", "null", "-"],
        capture_output=True, **TEXT_UTF8,
    )
    return len([ln for ln in (r.stderr or "").splitlines() if ln.strip()])


def build_proxy(
    src: str | Path,
    dest: str | Path,
    use_nvenc: bool | None = None,
    height: int = PROXY_HEIGHT,
    cq: int = PROXY_CQ,
    crf: int = PROXY_CRF,
    verify: bool = True,
) -> None:
    """Encode a browsing proxy, and prove it actually decodes.

    `verify` re-decodes the output and, on corruption, retries once with
    libx264. Concurrent NVENC sessions on a consumer GPU can silently emit a
    damaged bitstream rather than failing, and a corrupt proxy is worse than a
    missing one: the frames that reach the model are wrong and the editor's
    preview is broken, with nothing in the logs to say so.
    """
    if use_nvenc is None:
        use_nvenc = detect_nvenc_available()
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)

    # ONE probe for both facts. The timecode is carried into the proxy so
    # Resolve will accept it as the clip's proxy: LinkProxyMedia validates the
    # pairing, and a timecode-less proxy is refused against a source that has
    # one (R10). ffmpeg drops timecode on encode unless told otherwise.
    # DF-normalized only when no tmcd stream printed it -- see
    # dropframe_normalized (audit F6, 2026-09-17).
    try:
        info = run_ffprobe(src)
    except Exception:
        info = {}
    timecode, tc_from_tmcd = timecode_from_probe(info)
    fps = video_fps(info)
    if timecode:
        timecode = dropframe_normalized(timecode, fps, tc_from_tmcd)
    timecode_flags = ["-timecode", timecode] if timecode else []

    # One second of frames, so scrubbing the page lands close to the pointer
    # instead of at the previous keyframe (2026-09-17, plan section 4). Omitted
    # when the rate is unknown rather than guessed: ffmpeg's own default is a
    # better guess than ours.
    gop_flags = ["-g", str(round(fps))] if fps and round(fps) >= 1 else []

    def _encode(nvenc: bool) -> None:
        # p5 and `-rc vbr` for the same reason own_proxy_cmd uses them: this
        # runs unattended, so encode speed is worth trading for efficiency.
        video_codec = [
            "-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", str(cq),
        ] if nvenc else [
            "-c:v", "libx264", "-preset", "medium", "-crf", str(crf),
        ]
        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(src),
            # Never upscale: a 360p source should stay 360p rather than being
            # inflated to the proxy height, which costs bytes and adds nothing.
            # The trunc(...)/2)*2 guards height to even, matching the width's
            # `-2`: an odd-height non-4:2:0 source (RGB screen capture, ffv1)
            # fails at encoder init otherwise. Parity with the companion's
            # preview_proxy_cmd, whose argv-literal tests pin this exact
            # filter (MED-12, 2026-08-11).
            "-vf", f"scale=-2:'trunc(min({height},ih)/2)*2'",
            *video_codec,
            *gop_flags,
            # 8-bit 4:2:0, ALWAYS: these proxies exist to play in a browser,
            # and without the pin libx264 inherits the source's pixel format.
            # Our own shoots are 10-bit (FX3/FX30 XAVC), which came out as
            # H.264 High 10 / yuv420p10le -- posters fine, playback a black
            # rectangle on the editors' machines (found 2026-08-11: every
            # Creators_Club preview from a 10-bit source was unwatchable).
            "-pix_fmt", "yuv420p",
            *timecode_flags,
            "-c:a", "aac", "-b:a", PROXY_AUDIO_BITRATE,
            "-movflags", "+faststart",
            str(dest),
        ]
        # Capture stderr: without it a CalledProcessError carries only the
        # command line, which says nothing about WHY ffmpeg refused. That cost
        # a diagnosis cycle on the real archive.
        r = subprocess.run(cmd, capture_output=True, **TEXT_UTF8)
        if r.returncode != 0:
            raise RuntimeError(
                f"ffmpeg {'nvenc' if nvenc else 'libx264'} exited {r.returncode}: "
                f"{(r.stderr or '').strip()[:300]}"
            )

    def _bad(reason_only: bool = False) -> str | None:
        """Why this proxy is unusable, or None if it is fine.

        Three independent failure modes, all seen on real footage: a damaged
        bitstream (decodes with errors), a TRUNCATED proxy that decodes
        perfectly but stops early — the latter passes an error check and then
        breaks anything that seeks past the cut, so duration has to be
        compared against the source as well — and a proxy a FEW FRAMES short,
        which passes both of those and is refused by Resolve as a proxy
        (2026-09-17, the Reproductive Rights incident: seven files 1-18 frames
        short, diagnosed as "sync is stuck"). A count neither side can produce
        is not a mismatch: both must be known before this fails anything.
        """
        errs = verify_decodes(dest)
        if errs > 0:
            return f"{errs} decode errors"
        src_frames, dst_frames = count_frames(src), count_frames(dest)
        if src_frames and dst_frames and src_frames != dst_frames:
            return f"{dst_frames} frames of the source's {src_frames}"
        try:
            src_d = probe_video(src).get("duration_s")
            dst_d = probe_video(dest).get("duration_s")
        except Exception:
            return None  # can't compare; don't fail on the check itself
        if src_d and dst_d and dst_d < src_d * 0.97:
            return f"truncated: {dst_d:.0f}s of {src_d:.0f}s"
        return None

    # The GPU encoder can fail OUTRIGHT under concurrency (session limits) as
    # well as producing bad output, so both paths fall back to the CPU encoder.
    # Only a failure of libx264 itself is fatal.
    try:
        _encode(use_nvenc)
        encode_failed = None
    except RuntimeError as e:
        if not use_nvenc:
            raise
        encode_failed = str(e)

    if encode_failed:
        _encode(False)  # raises on its own if the CPU path also fails

    if not verify:
        return

    reason = _bad()
    if reason:
        # Fall back to the CPU encoder: no GPU session contention, and it
        # decodes codecs (AV1) that the hardware path can mishandle.
        if encode_failed is None:
            _encode(False)
            reason = _bad()
        if reason:
            raise RuntimeError(f"proxy unusable after libx264 fallback ({reason})")


# A sprite sheet exists for hover-scrubbing, so past a point more cells add no
# usable precision — they just make an enormous image. At the shipped 2s
# interval a 16-minute clip wants ~490 cells (2400 x 6615 px), which failed
# outright on the real archive. Cap the cell count and stretch the interval to
# fit: a long clip gets coarser scrubbing rather than no sprite at all.
SPRITE_MAX_CELLS = 240


def probe_image_size(path: str | Path) -> tuple[int, int] | None:
    """(width, height) of an image file, or None if it cannot be read.

    Never raises: it exists to MEASURE an output that has already been written,
    and a failed measurement must degrade to "geometry unknown" rather than
    fail the clip that was otherwise sprited fine.
    """
    try:
        info = run_ffprobe(path)
        stream = next(
            (s for s in info.get("streams", []) if s.get("codec_type") == "video"), {}
        )
        width, height = stream.get("width"), stream.get("height")
    except Exception:  # noqa: BLE001 - see docstring
        return None
    if not width or not height:
        return None
    return int(width), int(height)


def build_sprite(src: str | Path, dest: str | Path, duration_s: float, columns: int = 10,
                  cell_width: int = 240, interval_s: float = 2.0,
                  max_cells: int = SPRITE_MAX_CELLS) -> dict[str, float | int | None]:
    """Sprite sheet: 1 frame every `interval_s` seconds, tiled `columns` wide, cell_width px.

    `interval_s` is widened automatically when the clip is long enough that the
    requested interval would exceed `max_cells`.

    Returns the sheet's geometry for the caller to STORE (BROLL-1/BROLL-2,
    2026-08-11): the browser cannot re-derive it. The cell height is measured
    off the sheet just written rather than computed, because `scale={w}:-2`
    rounds to an even number and so does the 540p proxy step before it — on the
    live archive 6,783 of 7,117 sheets were a pixel taller than the source
    aspect ratio predicted, which is a ~17% overlay offset on a 24-row sheet.
    The interval and cell count go with it because `max_cells` postdates part of
    the archive, and a sheet built before it carries no marker saying so.

    `sprite_cell_w`/`sprite_cell_h` are None when the sheet could not be
    measured — an honest "unknown" the reader falls back on, never a guess
    dressed up as a measurement.
    """
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)

    if duration_s and duration_s / interval_s > max_cells:
        interval_s = duration_s / max_cells

    n_frames = max(int(duration_s // interval_s) + 1, 1)
    n_frames = min(n_frames, max_cells)
    rows = max((n_frames + columns - 1) // columns, 1)
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(src),
        "-vf", f"fps=1/{interval_s},scale={cell_width}:-2,tile={columns}x{rows}",
        "-frames:v", "1",
        "-q:v", "4",
        str(dest),
    ]
    subprocess.run(cmd, check=True)

    geometry: dict[str, float | int | None] = {
        "sprite_cols": columns,
        "sprite_cells": n_frames,
        "sprite_interval_s": interval_s,
        "sprite_cell_w": None,
        "sprite_cell_h": None,
    }
    # `tile` always emits the full columns x rows canvas (a short clip's unused
    # cells are padded, not cropped), so dividing the sheet by the grid we asked
    # for is exact and needs no model of ffmpeg's rounding.
    size = probe_image_size(dest)
    if size:
        sheet_w, sheet_h = size
        geometry["sprite_cell_w"] = sheet_w // columns
        geometry["sprite_cell_h"] = sheet_h // rows
    return geometry


def build_poster(src: str | Path, dest: str | Path, duration_s: float, width: int = 640) -> None:
    """Single poster frame, taken ~10% into the clip (avoids black-frame opens/fades)."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    ts = max(duration_s * 0.1, 0.0)
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-ss", f"{ts:.3f}", "-i", str(src),
        "-vf", f"scale={width}:-2",
        "-frames:v", "1",
        "-q:v", "3", "-pix_fmt", "yuvj420p",
        str(dest),
    ]
    subprocess.run(cmd, check=True)


# ---------------------------------------------------------------------------
# scene-detect frame extraction
# ---------------------------------------------------------------------------

_SHOWINFO_PTS_RE = re.compile(r"pts_time:(?P<t>[0-9.]+)")


def detect_scene_timestamps(src: str | Path, threshold: float = 0.3) -> list[float]:
    """Timestamps (seconds) of scene-change frames via ffmpeg's `select`+`showinfo`."""
    cmd = [
        "ffmpeg", "-hide_banner",
        "-i", str(src),
        "-vf", f"select='gt(scene,{threshold})',showinfo",
        "-f", "null", "-",
    ]
    result = subprocess.run(cmd, capture_output=True, **TEXT_UTF8)
    timestamps = [float(m.group("t")) for m in _SHOWINFO_PTS_RE.finditer(result.stderr)]
    return sorted(set(timestamps))


def fill_gaps(timestamps: list[float], duration_s: float, max_gap_s: float = 4.0) -> list[float]:
    """Ensure timestamps start near 0 and no gap between consecutive timestamps exceeds
    max_gap_s, inserting evenly-spaced fill points where needed (including after the last
    scene-detected timestamp, up to duration_s). Pure function, no I/O.
    """
    if duration_s <= 0:
        return [0.0]

    points = sorted(t for t in timestamps if 0 <= t <= duration_s)
    if not points or points[0] > max_gap_s:
        points = [0.0, *points]

    filled: list[float] = [points[0]]
    for t in points[1:]:
        prev = filled[-1]
        gap = t - prev
        if gap > max_gap_s:
            n_steps = math.ceil(gap / max_gap_s)
            step = gap / n_steps
            for i in range(1, n_steps):
                filled.append(prev + step * i)
        filled.append(t)

    trailing_gap = duration_s - filled[-1]
    if trailing_gap > max_gap_s:
        n_steps = math.ceil(trailing_gap / max_gap_s)
        step = trailing_gap / n_steps
        prev = filled[-1]
        for i in range(1, n_steps + 1):
            filled.append(prev + step * i)

    return sorted(set(round(t, 3) for t in filled))


def extract_frames(
    src: str | Path,
    timestamps: list[float],
    out_dir: str | Path,
    duration_s: float | None = None,
    safety_margin: float = 0.05,
) -> list[tuple[float, Path]]:
    """Extract one still per timestamp (accurate seek).

    Returns (timestamp, path) pairs in timestamp order, for frames that were
    actually produced. Pairs rather than two parallel lists on purpose: a frame
    can be skipped (see below), and pairing by list position would then shift
    every later timecode — silently mislabelling contact sheets, which is how
    wrong timestamps would reach search results.

    If `duration_s` is given, timestamps are clamped to `duration_s - safety_margin` —
    seeking to (or past) the exact end of a clip returns zero frames and ffmpeg errors out.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    frames: list[tuple[float, Path]] = []
    for i, ts in enumerate(timestamps):
        effective_ts = ts
        if duration_s is not None:
            effective_ts = min(ts, max(duration_s - safety_margin, 0.0))
        out_path = out_dir / f"frame_{i:04d}.jpg"
        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-ss", f"{effective_ts:.3f}", "-i", str(src),
            "-frames:v", "1", "-q:v", "3", "-pix_fmt", "yuvj420p",
            str(out_path),
        ]
        subprocess.run(cmd, check=True)
        # A seek past the real last frame writes nothing yet still exits 0 —
        # container duration routinely overstates the decodable stream (dashcam
        # and other growing-file recordings especially). Returning a path that
        # doesn't exist breaks contact-sheet tiling downstream, so only keep
        # frames ffmpeg actually produced.
        if out_path.is_file() and out_path.stat().st_size > 0:
            frames.append((ts, out_path))
    return frames


# ---------------------------------------------------------------------------
# contact sheets
# ---------------------------------------------------------------------------

_FONT_CANDIDATES = [
    "C:/Windows/Fonts/arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
]


@lru_cache(maxsize=1)
def find_font() -> str | None:
    for candidate in _FONT_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    return None


def seconds_to_timecode(t: float) -> str:
    total = int(round(t))
    hh, rem = divmod(total, 3600)
    mm, ss = divmod(rem, 60)
    return f"{hh:02d}:{mm:02d}:{ss:02d}"


def _even(n: int) -> int:
    return n if n % 2 == 0 else n + 1


def compute_cell_size(width: int, height: int, cell_width: int) -> tuple[int, int]:
    if not width or not height:
        return cell_width, _even(round(cell_width * 9 / 16))
    cell_height = _even(round(cell_width * height / width))
    return cell_width, cell_height


def _escape_drawtext(text: str) -> str:
    return text.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def build_contact_sheet(
    frame_paths: list[Path],
    timecodes: list[str],
    out_path: str | Path,
    cell_width: int = 384,
    cell_height: int | None = None,
) -> Path:
    """Tile up to 9 frames into a 3x3 contact sheet with a burned-in HH:MM:SS per cell."""
    if not frame_paths:
        raise ValueError("build_contact_sheet requires at least one frame")
    if len(frame_paths) > 9:
        raise ValueError("build_contact_sheet takes at most 9 frames (3x3)")
    if cell_height is None:
        cell_height = _even(round(cell_width * 9 / 16))

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    font = find_font()
    # fontfile is itself a drawtext option value, so its ':'s (e.g. Windows drive letters)
    # need the same escaping as any other option value.
    fontfile_arg = f"fontfile='{_escape_drawtext(font)}':" if font else ""

    inputs: list[str] = []
    filters: list[str] = []
    for i, (frame, tc) in enumerate(zip(frame_paths, timecodes)):
        inputs += ["-i", str(frame)]
        label = f"v{i}"
        drawtext = (
            f"drawtext={fontfile_arg}text='{_escape_drawtext(tc)}':x=8:y=h-28:"
            "fontsize=18:fontcolor=white:box=1:boxcolor=black@0.5:boxborderw=4"
        )
        filters.append(f"[{i}:v]scale={cell_width}:{cell_height},{drawtext}[{label}]")

    n = len(frame_paths)
    if n == 1:
        # xstack requires >= 2 inputs; a single-frame "sheet" is just the scaled/labeled frame.
        filters[-1] = filters[-1].replace("[v0]", "[out]")
    else:
        layout_positions = []
        for i in range(n):
            row, col = divmod(i, 3)
            layout_positions.append(f"{col * cell_width}_{row * cell_height}")
        xstack_inputs = "".join(f"[v{i}]" for i in range(n))
        filters.append(f"{xstack_inputs}xstack=inputs={n}:layout={'|'.join(layout_positions)}[out]")

    filter_complex = ";".join(filters)
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        *inputs,
        "-filter_complex", filter_complex,
        "-map", "[out]",
        "-q:v", "4",
        str(out_path),
    ]
    subprocess.run(cmd, check=True)
    return out_path


def build_contact_sheets(
    frames: list[tuple[float, Path]],
    out_dir: str | Path,
    width: int | None = None,
    height: int | None = None,
    cell_width: int = 384,
) -> list[Path]:
    """Group extracted frames into 3x3 contact sheets (sheet_0001.jpg, sheet_0002.jpg, ...).

    Takes (timestamp, path) pairs from `extract_frames` so each cell's burned-in
    timecode is guaranteed to belong to the frame it is drawn on.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cell_w, cell_h = compute_cell_size(width or 0, height or 0, cell_width)

    # Defence in depth: never hand a vanished frame to ffmpeg — one missing
    # input aborts the whole xstack and fails the video.
    frames = [(ts, p) for ts, p in frames if Path(p).is_file()]

    sheets: list[Path] = []
    for sheet_index, start in enumerate(range(0, len(frames), 9)):
        chunk = frames[start:start + 9]
        chunk_frames = [p for _, p in chunk]
        chunk_tcs = [seconds_to_timecode(ts) for ts, _ in chunk]
        out_path = out_dir / f"sheet_{sheet_index + 1:04d}.jpg"
        build_contact_sheet(chunk_frames, chunk_tcs, out_path, cell_width=cell_w, cell_height=cell_h)
        sheets.append(out_path)
    return sheets
