"""The ffmpeg half of b-roll ingest: the proxy, sprite, poster, thumb, scene
detection and frame extraction an editor's machine has to produce before the
local model ever sees a clip -- and the xxh64 fingerprint the archive dedupes
on.

Everything here is a PURE ARGV BUILDER plus one spawn helper, the split
`ffmpeg_tools` already made and for the same reasons: the orchestrator needs
Popen with a drained stderr, a poll for "the editor came back" and a kill
path, none of which fits inside a subprocess.run, and keeping the flags here
means the whole encoding spec is assertable on a machine with no ffmpeg.

**Every number and filter string in this file is the b-roll INDEXER's**
(`broll/indexer/broll_index/ffmpeg_tools.py`). That is not a coincidence to be
tidied away later: a clip indexed on an editor's machine and a clip indexed on
the base rig land in ONE search database and are served to everyone by one web
UI. If the sprite geometry differs, hover-scrubbing lands on the wrong frame
for half the archive; if the frame timestamps differ, the segments the model
describes are labelled with times that do not match the video. So
`test_broll_ingest_media.py` loads the indexer's module BY PATH and compares
the argv, flag for flag, wherever the tree is present -- the same standing
comparison `ffmpeg_tools`' preview-proxy tests make by hand, mechanised.

What legitimately differs, and only this:
  * the binary: `ffmpeg_path` from config, never the bare name -- an editor's
    ffmpeg is wherever the installer put it and a LaunchAgent's PATH is
    /usr/bin:/bin (ffmpeg_tools' header);
  * `creationflags=CREATE_NO_WINDOW` on every spawn -- the companion is a
    windowed build and this runs unattended, hundreds of times per batch;
  * argv building is separated from running (see above).
"""

from __future__ import annotations

import json
import logging
import math
import re
import subprocess
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

from . import ffmpeg_tools
from .ffmpeg_tools import UnreadableMediaError, _win_creationflags, TEXT_UTF8

log = logging.getLogger("ccsync.brollmedia")

# --- the fingerprint -------------------------------------------------------
#
# `videos.hash` is xxh64(first 8 MiB + last 8 MiB + size) -- broll/schema.sql
# and broll_index/hashing.py. The server dedupes an ingest batch against the
# live archive on exactly this digest, so a different chunk size, a different
# order, or a size fed in as anything but its decimal string would make every
# clip look new and re-ingest an archive that is already there.
HASH_CHUNK_SIZE = 8 * 1024 * 1024

# --- sprite geometry -------------------------------------------------------
#
# Lifted from broll_index.ffmpeg_tools.build_sprite. The cap exists because at
# the 2 s interval a 16-minute clip wants ~490 cells (2400 x 6615 px), which
# failed outright on the real archive; past a point more cells add no usable
# scrubbing precision anyway, so a long clip gets a wider interval rather than
# no sprite.
SPRITE_MAX_CELLS = 240
SPRITE_COLUMNS = 10
SPRITE_CELL_WIDTH = 240
SPRITE_INTERVAL_S = 2.0

POSTER_WIDTH = 640
# The drop-zone thumbnail: the browser makes its own for files it can decode,
# and asks us for the rest (10-bit XAVC, MXF, anything <video> refuses).
# 160 px wide is the grid cell; anything bigger is bytes over the loopback for
# pixels nobody sees.
THUMB_WIDTH = 160

# Scene detection + gap filling, the indexer's defaults (SamplingConfig).
SCENE_THRESHOLD = 0.3
MAX_GAP_S = 4.0
# Seeking to (or past) the exact end of a clip returns zero frames and ffmpeg
# errors out; the indexer clamps by this margin.
FRAME_SAFETY_MARGIN = 0.05

_SHOWINFO_PTS_RE = re.compile(r"pts_time:(?P<t>[0-9.]+)")


# ---------------------------------------------------------------------------
# probe + hash
# ---------------------------------------------------------------------------

def probe(ffmpeg_path: str, path: str | Path) -> dict:
    """Facts about a source clip, or UnreadableMediaError.

    `ffmpeg_tools.probe_video` unchanged -- one ffprobe, the drop-frame
    normalisation Resolve needs, and `shot_date` for the index row.
    """
    return ffmpeg_tools.probe_video(ffmpeg_path, path)


def hash_partial(path: str | Path) -> str:
    """xxh64(first 8 MiB + last 8 MiB + size) -- `videos.hash`.

    Byte-for-byte broll_index/hashing.py's algorithm, including the details
    that look incidental and are not: the head read is `min(CHUNK, size)` (so
    a file smaller than 8 MiB is hashed once, not twice), the tail is read only
    when the file is BIGGER than one chunk, and the size is mixed in as its
    DECIMAL STRING in UTF-8 -- not as 8 bytes of anything. Change any of those
    and every clip on this machine looks new to a server holding 12,000 rows
    of the old digest.
    """
    path = Path(path)
    import xxhash  # deferred: only an ingest ever needs it

    size = path.stat().st_size
    h = xxhash.xxh64()
    with open(path, "rb") as f:
        head = f.read(min(HASH_CHUNK_SIZE, size))
        h.update(head)
        if size > HASH_CHUNK_SIZE:
            f.seek(max(size - HASH_CHUNK_SIZE, 0))
            tail = f.read(HASH_CHUNK_SIZE)
            h.update(tail)
    h.update(str(size).encode("utf-8"))
    return h.hexdigest()


# ---------------------------------------------------------------------------
# argv builders -- PURE. No I/O, no probing, no filesystem.
# ---------------------------------------------------------------------------

def preview_proxy_cmd(ffmpeg_path: str, src: str | Path, dest: str | Path, *,
                      nvenc: bool, timecode: Optional[str] = None) -> list[str]:
    """The 540p browsing proxy. `ffmpeg_tools.preview_proxy_cmd` verbatim --
    NOT a second copy of the spec: that function is already the b-roll one
    (its own tests pin the argv against the indexer's), and the ingest's only
    addition is passing the source timecode, which camera originals have and
    YouTube downloads do not.
    """
    return ffmpeg_tools.preview_proxy_cmd(ffmpeg_path, src, dest, nvenc=nvenc,
                                          timecode=timecode)


def sprite_geometry(duration_s: float, *, columns: int = SPRITE_COLUMNS,
                    cell_width: int = SPRITE_CELL_WIDTH,
                    interval_s: float = SPRITE_INTERVAL_S,
                    max_cells: int = SPRITE_MAX_CELLS) -> dict[str, Any]:
    """The sheet's shape BEFORE it is built -- interval, cell count, rows.

    The arithmetic is build_sprite's, in the same order (the widening happens
    first, then the cell count is derived from the widened interval and capped
    again), because both numbers are STORED on the row and read back by the
    browser to place the hover overlay. `sprite_cell_w`/`sprite_cell_h` are
    deliberately absent here: they are MEASURED off the finished sheet, never
    computed, because `scale={w}:-2` rounds to an even number and on the live
    archive 6,783 of 7,117 sheets came out a pixel taller than the source
    aspect ratio predicted (BROLL-1/BROLL-2).
    """
    duration_s = float(duration_s or 0)
    interval = float(interval_s)
    if duration_s and duration_s / interval > max_cells:
        interval = duration_s / max_cells
    n_frames = max(int(duration_s // interval) + 1, 1)
    n_frames = min(n_frames, max_cells)
    rows = max((n_frames + columns - 1) // columns, 1)
    return {
        "sprite_cols": columns,
        "sprite_rows": rows,
        "sprite_cells": n_frames,
        "sprite_interval_s": interval,
        "cell_width": cell_width,
    }


def sprite_cmd(ffmpeg_path: str, src: str | Path, dest: str | Path,
               geometry: dict[str, Any]) -> list[str]:
    """argv for the hover-scrub sheet described by `geometry`."""
    return [
        ffmpeg_path, "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(src),
        "-vf", (f"fps=1/{geometry['sprite_interval_s']},"
                f"scale={geometry['cell_width']}:-2,"
                f"tile={geometry['sprite_cols']}x{geometry['sprite_rows']}"),
        "-frames:v", "1",
        "-q:v", "4",
        str(dest),
    ]


def poster_cmd(ffmpeg_path: str, src: str | Path, dest: str | Path,
               duration_s: float, width: int = POSTER_WIDTH) -> list[str]:
    """One poster frame, taken ~10% in -- far enough past a fade or a black
    slate to be a picture of the shot."""
    ts = max(float(duration_s or 0) * 0.1, 0.0)
    return [
        ffmpeg_path, "-y", "-hide_banner", "-loglevel", "error",
        "-ss", f"{ts:.3f}", "-i", str(src),
        "-vf", f"scale={width}:-2",
        "-frames:v", "1",
        "-q:v", "3", "-pix_fmt", "yuvj420p",
        str(dest),
    ]


def thumb_cmd(ffmpeg_path: str, src: str | Path, dest: str | Path,
              duration_s: float, width: int = THUMB_WIDTH) -> list[str]:
    """The drop-zone preview: a poster at 160 px. Same recipe, smaller -- so
    a page showing 300 dropped clips is not fetching 300 640px JPEGs."""
    return poster_cmd(ffmpeg_path, src, dest, duration_s, width=width)


def scene_detect_cmd(ffmpeg_path: str, src: str | Path,
                     threshold: float = SCENE_THRESHOLD) -> list[str]:
    """argv that decodes the clip and prints one `showinfo` line per
    scene-change frame to STDERR (which is where ffmpeg's filter logging
    goes -- the caller reads it from there, never from stdout)."""
    return [
        ffmpeg_path, "-hide_banner",
        "-i", str(src),
        "-vf", f"select='gt(scene,{threshold})',showinfo",
        "-f", "null", "-",
    ]


def parse_scene_timestamps(stderr_text: Optional[str]) -> list[float]:
    """Scene-change timestamps out of a scene_detect_cmd run's stderr.

    `detect_scene_timestamps`' semantics exactly: every `pts_time:` in the
    output, de-duplicated and sorted. Tolerant of an empty or truncated
    stream -- a clip with no cuts at all is a single-shot clip, not a failure,
    and `fill_gaps` will still produce sampling points for it.
    """
    return sorted({float(m.group("t")) for m in _SHOWINFO_PTS_RE.finditer(stderr_text or "")})


def fill_gaps(timestamps: Sequence[float], duration_s: float,
              max_gap_s: float = MAX_GAP_S) -> list[float]:
    """Ensure timestamps start near 0 and no gap between consecutive timestamps exceeds
    max_gap_s, inserting evenly-spaced fill points where needed (including after the last
    scene-detected timestamp, up to duration_s). Pure function, no I/O.

    A COPY of broll_index.ffmpeg_tools.fill_gaps (the docstring above is its
    own): it decides which frames the model is shown, and a copy that drifted
    would mean a clip sampled differently depending on which machine ingested
    it. test_broll_ingest_media.py runs both implementations over the same
    inputs and compares.
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


def frame_path(frames_dir: str | Path, index: int) -> Path:
    """`frames/frame_0004.jpg` -- the name the vendored `load_frame_list`
    reconstructs from `frames.json`'s timestamps array BY POSITION. The index
    is the position in the REQUESTED timestamp list, not a running count of
    files written, so a frame ffmpeg failed to produce leaves a hole rather
    than shifting every later frame's timecode."""
    return Path(frames_dir) / f"frame_{index:04d}.jpg"


def extract_frame_cmd(ffmpeg_path: str, src: str | Path, timestamp: float,
                      dest: str | Path, duration_s: Optional[float] = None,
                      safety_margin: float = FRAME_SAFETY_MARGIN) -> list[str]:
    """argv for one still at `timestamp` (accurate seek, -ss before -i).

    Clamped to `duration_s - safety_margin` when the duration is known:
    container duration routinely overstates the decodable stream, and a seek
    past the last real frame writes nothing while still exiting 0.
    """
    effective = float(timestamp)
    if duration_s is not None:
        effective = min(effective, max(float(duration_s) - safety_margin, 0.0))
    return [
        ffmpeg_path, "-y", "-hide_banner", "-loglevel", "error",
        "-ss", f"{effective:.3f}", "-i", str(src),
        "-frames:v", "1", "-q:v", "3", "-pix_fmt", "yuvj420p",
        str(dest),
    ]


def write_frames_json(sheets_dir: str | Path, timestamps: Iterable[float],
                      sheets: Iterable[str | Path] = ()) -> Path:
    """Write `<sheets_dir>/frames.json` in the shape the vendored
    `local_vlm.load_frame_list` reads.

    `{"timestamps": [...], "sheets": [...]}` and nothing else: load_frame_list
    walks `timestamps` and pairs index i with `frames/frame_{i:04d}.jpg`, so
    this must record the timestamps ACTUALLY SAMPLED, in request order, with
    the holes left in place. `sheets` is empty for ingest -- contact sheets are
    the Anthropic backend's input and the local backend never reads them --
    but the key is written anyway, because that is the file the indexer writes
    and the same reader parses both.
    """
    sheets_dir = Path(sheets_dir)
    sheets_dir.mkdir(parents=True, exist_ok=True)
    path = sheets_dir / "frames.json"
    path.write_text(
        json.dumps({"timestamps": [float(t) for t in timestamps],
                    "sheets": [str(p) for p in sheets]}),
        encoding="utf-8",
    )
    return path


# ---------------------------------------------------------------------------
# running one of the above
# ---------------------------------------------------------------------------

# A still or a sprite is seconds of work; the ceiling is for a file on a
# sleeping USB drive or a stalled SMB mount, where the worker thread would
# otherwise sit there for ever -- and it is the thread that also has to notice
# "the editor came back".
RUN_TIMEOUT_SECONDS = 900


def run_ffmpeg(cmd: Sequence[str], timeout: int = RUN_TIMEOUT_SECONDS,
               child_sink: Optional[Any] = None) -> tuple[int, str]:
    """Run one built argv to completion -> (returncode, stderr text).

    stderr is DRAINED, never discarded: it is where ffmpeg puts both the
    reason it refused and (for scene detection) the entire result. Left
    unread on a pipe, a chatty filter fills the OS buffer and ffmpeg blocks
    for ever holding the batch. `communicate` reads both streams for us.

    Never raises for a media reason: a non-zero exit is returned, because the
    caller counts an attempt and moves to the next clip. A binary that cannot
    be RUN at all, or a timeout, is UnreadableMediaError -- the same single
    exception type ffmpeg_tools chose, for the same reason (the caller has one
    response to all of them).

    `child_sink` is MEDIA-2 (resilience sweep 2026-08-28): the orchestrator's
    `stop()`/`cancel()` promised for months to kill the ffmpeg child and could
    not, because nothing ever handed it one -- this ran under
    `subprocess.run` on a daemon thread, `join(timeout=5)` abandoned that
    thread, and an orphaned ffmpeg.exe kept running past tray exit holding a
    handle on the staged file (which then blocked staging cleanup on Windows).
    Popen, published, and cleared again on the way out; the sink itself is
    never allowed to fail the run.
    """
    if child_sink is None:
        # No sink wired (a test double, a caller with nothing to kill): the
        # simple, blocking form, which is also what every existing test of
        # this function patches.
        try:
            done = subprocess.run(
                list(cmd),
                capture_output=True,
                timeout=timeout,
                creationflags=_win_creationflags(),
                **TEXT_UTF8,
            )
        except subprocess.TimeoutExpired:
            raise UnreadableMediaError(
                f"ffmpeg timed out after {timeout}s -- unreachable drive, or a file "
                "still being written")
        except OSError as exc:
            raise UnreadableMediaError(f"ffmpeg could not be run ({cmd[0]}): {exc}")
        return done.returncode, (done.stderr or "")

    try:
        proc = subprocess.Popen(
            list(cmd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=_win_creationflags(),
            **TEXT_UTF8,
        )
    except OSError as exc:
        raise UnreadableMediaError(f"ffmpeg could not be run ({cmd[0]}): {exc}")
    _publish_child(child_sink, proc)
    try:
        try:
            _out, err = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            # Kill it, then drain: a killed child whose pipes are never read
            # is the same wedged thread the timeout exists to end.
            proc.kill()
            try:
                proc.communicate(timeout=10)
            except Exception:  # noqa: BLE001 - already failing; do not mask it
                pass
            raise UnreadableMediaError(
                f"ffmpeg timed out after {timeout}s -- unreachable drive, or a file "
                "still being written")
    finally:
        _publish_child(child_sink, None)
    return proc.returncode, (err or "")


def _publish_child(child_sink: Optional[Any], proc: Optional[Any]) -> None:
    """Hand the live child to the orchestrator (or take it back).

    Swallows everything: a sink that raises must not turn a finished encode
    into a failed clip."""
    if child_sink is None:
        return
    try:
        child_sink(proc)
    except Exception:  # noqa: BLE001
        log.debug("could not publish the ffmpeg child", exc_info=True)
