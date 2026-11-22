"""Grading frames: fetch a few real frames of a camera original into a hollow copy.

docs/GRADING_FRAMES.md phases 3 and 4 (2026-11-22, RSV-147). A remote editor parks the playhead
on a frame and picks Workspace > Scripts > CC Sync > Bring grading frame; the Lua menu script
writes a request file into `~/.ccsync/requests/frames/` (it cannot make an HTTP call and must not
hold the loopback token, the same reason as SELECTIVE_ORIGINALS.md 12.2), and this module does the
rest: validate the request, work out the frames, read them from the server through the editor's
own download route, and hand them to `hollow.build_hollow` / `hollow.add_frames`, which put a
hollow copy at the original's own path. One balloon answers the request.

What this is NOT (doc section 3.4, "Not a lane"): seconds long and megabytes big, so no LaneStatus,
no power guard and nothing on the sequencer's rotation (the CR-347 lesson). One worker thread,
two clips at a time, and one tray line while a batch runs.

The dashboard is never in the byte path: every byte comes from `rclone cat --offset --count`
through `rclone_lane.down_route`, with the tuning, route and transport flags Bring originals uses
(`originals_lane.build_originals_command`). The ranged read is ONE function (`Transport.read_range`)
so a batch transport (`rclone serve http` on loopback, doc 3.4 "Cost") can replace it later.

macOS: section 6 item 1 has not been run, and section 5 puts the Mac in only once it passes, so on
a Mac the fetch refuses with one sentence behind FETCH_ENABLED_ON_MACOS. The predicate and every
reader of section 4 stay live there.

CR-68: nothing here calls Resolve. No em dashes in any sentence an editor reads (2026-08-18).
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from . import hollow
from . import originals_requests
from . import ui_copy
from .sync import originals_lane, rclone_lane

log = logging.getLogger("ccsync.grading_frames")

# THE MAC SWITCH (doc section 5 and 6 item 1, 2026-11-22). A sparse file on APFS, the Mapped
# Mount path and rows a, b, c and g of section 2.4 have not been checked on a Mac. Flip this when
# they have; nothing else in the module knows about the platform.
FETCH_ENABLED_ON_MACOS = False
MACOS_REFUSAL = ("grading frames are not available on a Mac yet, because they have not been "
                 "tested there. Bring originals still works")

SCHEMA_VERSION = 1
SOURCES = ("playhead", "timeline_range", "timeline_all", "media_pool")
MAX_REQUEST_BYTES = 1024 * 1024
MAX_CLIPS = 2000
MAX_FRAMES_PER_CLIP = 64
MAX_USES_PER_CLIP = 64
MAX_PATH_CHARS = 4096
MAX_TEXT_CHARS = 1024
# Same rule as the originals inbox (12.2): a request nobody has heard about for an hour is one the
# editor has stopped expecting.
MAX_AGE_SECONDS = 3600.0
POLL_SECONDS = 2.0
CLIPS_AT_A_TIME = 2

# Doc 3.4: a file under 64 MB is fetched whole (that covers the `_S00n` stills the parser cannot
# read, and costs no more than a hollow copy's own reads).
WHOLE_FILE_BELOW = 64 * 1024 * 1024
# A HOLLOW COPY MUST SHOW THE FILESYSTEM SIGN WHEN IT IS MADE (2026-11-22). hollow.filesystem_sign
# is "less than half allocated"; a copy holding more than that never shows it, so may_delete can
# never remove it and "Remove grading frames" keeps it for ever. A third leaves room for the
# frames a later request adds. Over it, the whole original comes down instead: a real file, no
# marker, no ledger row.
WHOLE_FILE_FRACTION = 1.0 / 3.0
# Ranges closer than this are read in one `rclone cat`: a frame and its neighbours sit a few MB
# apart with a second of sound between them, and every read is a connection.
COALESCE_GAP = 1 << 20
READ_TIMEOUT_SECONDS = 300.0
STAT_TIMEOUT_SECONDS = 120.0
WHOLE_TIMEOUT_SECONDS = 1800.0

BRAW_EXT = ".braw"
PRUNE_MIN_AGE_SECONDS = 600.0


def request_dir() -> Path:
    """Read at call time, so a test's HOME redirection is honoured."""
    return Path.home() / ".ccsync" / "requests" / "frames"


class RequestError(ValueError):
    """The request file is malformed; the message is for the log."""


class Refused(Exception):
    """This clip gets no grading frame. `str()` is the clause the editor reads after "No grading
    frame for <clip>: "."""


def _clause(text: str) -> str:
    """A refusal as a clause: no trailing full stop (the balloon adds one), and a leading capital
    lowered when the sentence came from elsewhere ("The sync drive is formatted exFAT..."), so
    "No grading frame for A001: the sync drive..." reads as one sentence."""
    text = str(text or "").strip().rstrip(".").strip()
    if len(text) > 1 and text[0].isupper() and text[1].islower():
        text = text[0].lower() + text[1:]
    return text or "something went wrong (see the log)"


# =============================================================================================
# The request file (doc 3.4; the selective-originals contract, SELECTIVE_ORIGINALS.md 12.2)
# =============================================================================================

def _text(value: Any, name: str, limit: int, required: bool = True) -> str:
    if value is None and not required:
        return ""
    if not isinstance(value, str):
        raise RequestError(f"{name} is not a string")
    if len(value) > limit:
        raise RequestError(f"{name} is longer than {limit} characters")
    if "\x00" in value:
        raise RequestError(f"{name} holds a NUL")
    return value


def _frame_no(value: Any, name: str) -> int:
    # bool is an int in Python; a `true` where a frame number belongs is a malformed file.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RequestError(f"{name} is not a number")
    if isinstance(value, float) and (value != value or value != int(value)):
        raise RequestError(f"{name} is not a whole frame number")
    return int(value)


def _fps(value: Any, name: str) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 < value <= 1000:
        raise RequestError(f"{name} is not a frame rate")
    return float(value)


def parse_request(raw: bytes) -> dict:
    """Validate one frames request STRICTLY. Raises RequestError.

    {"v": 1, "source", "project", "timeline", "created_at",
     "clips": [{"file_path", "unique_id", "name", "frames": [int], "uses": [[first, last]],
                "clip_fps", "timeline_fps", "exact", "timecode", "angle_timeline",
                "angle_timecode"}],
     "refused": [sentence]}

    `frames` are the frames ASKED FOR (the playhead's). `uses` are the source frames of the clip's
    uses on the timeline, first and last. `refused` carries what the script itself could not
    resolve (a multicam it would not guess at), so the balloon can say it."""
    if len(raw) > MAX_REQUEST_BYTES:
        raise RequestError(f"larger than {MAX_REQUEST_BYTES} bytes")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise RequestError(f"not UTF-8 JSON ({exc})") from None
    if not isinstance(data, dict):
        raise RequestError("not a JSON object")
    version = data.get("v")
    if type(version) is not int or version != SCHEMA_VERSION:
        raise RequestError(f"v is {version!r}, this build reads v {SCHEMA_VERSION}")
    source = data.get("source")
    if source not in SOURCES:
        raise RequestError(f"source {source!r} is not one of {SOURCES}")
    clips = data.get("clips")
    refused_raw = data.get("refused", [])
    if not isinstance(clips, list) or not isinstance(refused_raw, list):
        raise RequestError("clips or refused is not a list")
    if not clips and not refused_raw:
        raise RequestError("no clips and nothing refused")
    if len(clips) > MAX_CLIPS or len(refused_raw) > MAX_CLIPS:
        raise RequestError(f"more than {MAX_CLIPS} clips")
    out = []
    for i, clip in enumerate(clips):
        if not isinstance(clip, dict):
            raise RequestError(f"clips[{i}] is not an object")
        frames = clip.get("frames", [])
        uses = clip.get("uses", [])
        if not isinstance(frames, list) or len(frames) > MAX_FRAMES_PER_CLIP:
            raise RequestError(f"clips[{i}].frames is not a short list")
        if not isinstance(uses, list) or len(uses) > MAX_USES_PER_CLIP:
            raise RequestError(f"clips[{i}].uses is not a short list")
        parsed_uses = []
        for j, use in enumerate(uses):
            if not isinstance(use, list) or len(use) != 2:
                raise RequestError(f"clips[{i}].uses[{j}] is not [first, last]")
            first, last = (_frame_no(v, f"clips[{i}].uses[{j}]") for v in use)
            parsed_uses.append((min(first, last), max(first, last)))
        exact = clip.get("exact", True)
        if not isinstance(exact, bool):
            raise RequestError(f"clips[{i}].exact is not true or false")
        out.append({
            "file_path": _text(clip.get("file_path"), f"clips[{i}].file_path", MAX_PATH_CHARS),
            "unique_id": _text(clip.get("unique_id"), f"clips[{i}].unique_id", MAX_TEXT_CHARS,
                               required=False),
            "name": _text(clip.get("name"), f"clips[{i}].name", MAX_TEXT_CHARS, required=False),
            "frames": [_frame_no(f, f"clips[{i}].frames") for f in frames],
            "uses": parsed_uses,
            "clip_fps": _fps(clip.get("clip_fps"), f"clips[{i}].clip_fps"),
            "timeline_fps": _fps(clip.get("timeline_fps"), f"clips[{i}].timeline_fps"),
            "exact": exact,
            "timecode": _text(clip.get("timecode"), f"clips[{i}].timecode", 64, required=False),
            "angle_timeline": _text(clip.get("angle_timeline"), f"clips[{i}].angle_timeline",
                                    MAX_TEXT_CHARS, required=False),
            "angle_timecode": _text(clip.get("angle_timecode"), f"clips[{i}].angle_timecode",
                                    64, required=False),
        })
    refused = [_text(r, f"refused[{i}]", MAX_TEXT_CHARS) for i, r in enumerate(refused_raw)]
    return {
        "source": source,
        "project": _text(data.get("project"), "project", MAX_TEXT_CHARS, required=False),
        "timeline": _text(data.get("timeline"), "timeline", MAX_TEXT_CHARS, required=False),
        "created_at": _text(data.get("created_at"), "created_at", 64),
        "clips": out,
        "refused": refused,
    }


def merge_clips(clips: Iterable[dict]) -> list[dict]:
    """One entry per file: a clip cut into a timeline three times is one fetch with three uses.
    The file path is the key as Resolve wrote it; compared in NFC and case-folded (CR-90), the
    first spelling seen is the one that is used."""
    merged: dict[str, dict] = {}
    for clip in clips:
        key = unicodedata.normalize("NFC", clip["file_path"]).casefold()
        held = merged.get(key)
        if held is None:
            merged[key] = {**clip, "frames": list(clip["frames"]), "uses": list(clip["uses"])}
            continue
        held["frames"] += [f for f in clip["frames"] if f not in held["frames"]]
        held["uses"] += [u for u in clip["uses"] if u not in held["uses"]]
        held["exact"] = held["exact"] and clip["exact"]
        for k in ("timecode", "angle_timeline", "angle_timecode"):
            held[k] = held[k] or clip[k]
    return list(merged.values())


# =============================================================================================
# Which frames (D1, D2)
# =============================================================================================

# D2 is one neighbour either side, always. An INEXACT frame (the script could not map the playhead
# to one file frame: the clip's rate differs from the timeline's, or it is retimed) gets two.
# Measured on a live timeline, 2026-11-22: a 119.88 fps clip on a 29.97 timeline worked out to
# frame 19036 where Resolve's own source start said 19038, and a retimed item is placed from a
# start that can be a frame low. Doc section 6 item 6 names widening as the answer if one frame
# proves too few; two more frames are 6 MB, a wrong frame is a Media Offline card.
MARGIN_EXACT = 1
MARGIN_INEXACT = 2


def frame_set(asked: Iterable[int], uses: Iterable[tuple[int, int]], frame_count: int,
              margin: int = MARGIN_EXACT) -> list[int]:
    """The frames to fetch for one clip of `frame_count` frames.

    D1: the frame asked for (the playhead's, when there is one), plus the first and middle frames
    of each USE of the clip on the timeline. D2: one neighbour either side of every one of them.

      * An ASKED frame outside the clip is refused (Refused, with a sentence), never clamped: a
        silent clamp would fetch a frame nobody looked at and say it was the one they asked for.
      * A use is clipped to the clip (a rate-converted mapping can land a frame past the end) and
        dropped when nothing of it is inside.
      * A NEIGHBOUR outside the clip is quietly left out.
      * No asked frame and no use (a media pool clip, chosen in the pool): the first and middle
        frames of the WHOLE clip, the nearest thing to "its use" a clip that is not on a timeline
        has.
      * Frame 0 is always added by the writer (the decoder needs its header, doc 2.2)."""
    if frame_count <= 0:
        raise Refused("the clip's index lists no frames")
    anchors: set[int] = set()
    for f in asked:
        if f < 0 or f >= frame_count:
            raise Refused(f"frame {f} is outside the clip (it has {frame_count} frames), so "
                          "nothing was fetched for it")
        anchors.add(f)
    for first, last in uses:
        lo, hi = max(0, first), min(frame_count - 1, last)
        if lo > hi:
            continue
        anchors.update((lo, (lo + hi) // 2))
    if not anchors:
        anchors.update((0, (frame_count - 1) // 2))
    out: set[int] = set()
    for a in anchors:
        for f in range(a - margin, a + margin + 1):
            if 0 <= f < frame_count:
                out.add(f)
    return sorted(out)


# =============================================================================================
# The transport (doc 3.4: the editor's own rclone remote, through the down route)
# =============================================================================================

class TransportError(RuntimeError):
    """rclone could not read the server. The message is for the log."""


class Transport:
    """The editor's rclone remote through `rclone_lane.down_route`, with Bring originals' tuning,
    route and transport flags. `run` is subprocess.run's shape (the test seam)."""

    def __init__(self, cfg: dict[str, Any], run: Callable[..., Any] = subprocess.run) -> None:
        self.cfg = cfg
        self._run = run

    def _route(self) -> tuple[str, str, list[str]]:
        route = rclone_lane.down_route(self.cfg)
        tuning = rclone_lane.RcloneTuning.from_cfg(self.cfg)
        flags = [*tuning.flags(rclone_lane.DIRECTION_DOWN), *rclone_lane.route_flags(route.via),
                 *rclone_lane._transport_flags()]
        return route.remote, route.remote_root, flags

    def _source(self, tree_rel: str) -> tuple[str, list[str]]:
        remote, remote_root, flags = self._route()
        return f"{remote}:{rclone_lane._join_remote_path(remote_root, tree_rel)}", flags

    def _rclone(self) -> str:
        return str(self.cfg.get("rclone_path") or "rclone")

    def _call(self, argv: list[str], timeout: float, binary: bool) -> Any:
        try:
            proc = self._run(argv, capture_output=True, timeout=timeout,
                             creationflags=rclone_lane._win_creationflags())
        except subprocess.TimeoutExpired:
            raise TransportError(f"rclone took longer than {timeout:.0f} s") from None
        except OSError as exc:
            raise TransportError(f"could not start rclone ({exc})") from None
        if proc.returncode != 0:
            err = proc.stderr.decode("utf-8", "replace") if isinstance(proc.stderr, bytes) else str(proc.stderr or "")
            last = [line for line in err.splitlines() if line.strip()][-1:] or [""]
            raise TransportError(f"rclone exited {proc.returncode}: {last[0][:300]}")
        return proc.stdout

    def stat_argv(self, tree_rel: str) -> list[str]:
        src, flags = self._source(tree_rel)
        return [self._rclone(), "lsjson", src, *flags]

    def read_argv(self, tree_rel: str, offset: int, count: int) -> list[str]:
        src, flags = self._source(tree_rel)
        return [self._rclone(), "cat", src, "--offset", str(int(offset)), "--count", str(int(count)),
                *flags]

    def whole_argv(self, tree_rel: str, dest: Path) -> list[str]:
        src, flags = self._source(tree_rel)
        # copyto writes `<name>.partial` and renames on completion (broll_fetch's reason): a killed
        # download never leaves a plausible-looking truncated clip at the original's path.
        return [self._rclone(), "copyto", src, str(dest), "--ignore-existing", *flags]

    def stat(self, tree_rel: str) -> Optional[tuple[int, str]]:
        """(size, modification time as the server says it) of one file, None when it is not
        there. Step 1 of doc 3.4."""
        try:
            out = self._call(self.stat_argv(tree_rel), STAT_TIMEOUT_SECONDS, binary=False)
        except TransportError as exc:
            if "exited 3" in str(exc):     # rclone's "directory not found"
                return None
            raise
        try:
            rows = json.loads(out.decode("utf-8") if isinstance(out, bytes) else out)
        except (UnicodeDecodeError, ValueError):
            raise TransportError("rclone lsjson did not answer JSON") from None
        rows = [r for r in rows if isinstance(r, dict) and not r.get("IsDir")]
        if len(rows) != 1:
            return None
        return int(rows[0].get("Size") or 0), str(rows[0].get("ModTime") or "")

    def read_range(self, tree_rel: str, offset: int, count: int) -> bytes:
        """THE byte path: `count` bytes of the server's file from `offset`. The one function a
        batch transport replaces (doc 3.4, "Cost"). A short answer is the writer's to refuse."""
        data = self._call(self.read_argv(tree_rel, offset, count), READ_TIMEOUT_SECONDS, binary=True)
        return bytes(data or b"")

    def fetch_whole(self, tree_rel: str, dest: Path) -> None:
        self._call(self.whole_argv(tree_rel, dest), WHOLE_TIMEOUT_SECONDS, binary=False)


class RangeCache:
    """A `read_range` for the writer that answers from spans already read. The head and the index
    are read before the build (to parse them), and the build asks for them again; the frames are
    planned up front and read in COALESCED spans, so a frame and its two neighbours are one read,
    not three. Every answer is a slice of what the server sent, never padded."""

    def __init__(self, read: Callable[[int, int], bytes]) -> None:
        self._read = read
        self._spans: list[tuple[int, bytes]] = []
        self.reads = 0

    def _fetch(self, offset: int, count: int) -> bytes:
        self.reads += 1
        data = self._read(offset, count)
        self._spans.append((offset, data))
        return data

    def prefetch(self, ranges: Iterable[tuple[int, int]]) -> None:
        merged: list[list[int]] = []
        for off, length in sorted(ranges):
            if self._held(off, length) is not None:
                continue
            if merged and off - (merged[-1][0] + merged[-1][1]) <= COALESCE_GAP:
                merged[-1][1] = max(merged[-1][1], off + length - merged[-1][0])
            else:
                merged.append([off, length])
        for off, length in merged:
            self._fetch(off, length)

    def _held(self, offset: int, count: int) -> Optional[bytes]:
        for start, data in self._spans:
            if start <= offset and offset + count <= start + len(data):
                return data[offset - start:offset - start + count]
        return None

    def __call__(self, offset: int, count: int) -> bytes:
        held = self._held(offset, count)
        return held if held is not None else self._fetch(offset, count)


# =============================================================================================
# One clip
# =============================================================================================

@dataclass
class Outcome:
    """What happened to one clip. `kind`: "made" (a new hollow copy), "added" (frames added to an
    existing one), "whole" (the whole original came down), "refused"."""
    name: str
    kind: str
    sentence: str = ""
    timecode: str = ""
    angle_timeline: str = ""
    angle_timecode: str = ""
    frames: list = field(default_factory=list)


def _display_name(clip: dict) -> str:
    name = os.path.splitext(os.path.basename(clip["file_path"].replace("\\", "/")))[0]
    return name or clip.get("name") or "this clip"


def _times_differ(then: Any, now: Any) -> bool:
    """Has the server's file a different modification time than when its frames were fetched?
    Compared as TIMES, two seconds apart or more (review, 2026-11-22): the same file read through
    the plain route and through a tunnel route can come back in another time zone or to another
    precision, and comparing the two strings would call every hollow copy stale the day the
    route changed, deleting frames the editor asked for (and refusing outright while Resolve
    holds the file open). A time that cannot be read is no evidence either way: the size, which
    is compared first, is what a changed clip nearly always shows."""
    def epoch(value: Any) -> Optional[float]:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        return stamp.timestamp()

    a, b = epoch(then), epoch(now)
    if a is None or b is None:
        return False
    return abs(a - b) >= 2.0


class ClipFetch:
    """The five steps of doc 3.4 for one clip, and every refusal of its list."""

    def __init__(self, cfg: dict[str, Any], transport: Transport, selection: Optional[list],
                 halted: bool, platform: str = sys.platform,
                 fetch_refusal: Optional[Callable[[dict, str], Optional[str]]] = None,
                 led: Optional[hollow.HollowLedger] = None) -> None:
        self.cfg = cfg
        self.transport = transport
        self.selection = selection
        self.halted = halted
        self.platform = platform
        self._fetch_refusal = fetch_refusal
        self.led = led

    # -- where the clip is ---------------------------------------------------------------------
    def _place(self, clip: dict) -> tuple[str, Path]:
        """(tree rel on the server, local path) for a clip's File Path, or Refused. Never trusts
        the path it was handed: it must be under this computer's tree (by the canonical prefix or
        local_root, originals_requests.tree_rel_for), inside a project TICKED here on a full tick,
        and pass the originals list rules (a video original, not a proxy, not hidden, not a
        partial, no `..`)."""
        local_root = str(self.cfg.get("local_root") or "")
        prefix = str(self.cfg.get("canonical_prefix") or "")
        tree_rel = originals_requests.tree_rel_for(clip["file_path"], local_root, prefix)
        if not tree_rel:
            raise Refused("it is not in this computer's tree")
        if os.path.splitext(tree_rel)[1].lower() != BRAW_EXT:
            raise Refused("it is not a Blackmagic RAW (.braw) clip, and grading frames are only "
                          "fetched for those for now")
        parts = [p for p in tree_rel.split("/") if p]
        folded = [originals_lane.nfc(p) for p in parts]
        for comps, _slug, upload_only in originals_requests._project_map(self.selection):
            if len(folded) > len(comps) and folded[:len(comps)] == comps:
                if upload_only:
                    raise Refused("its project is ticked upload-only on this computer, so nothing "
                                  "comes down for it. Tick it in full on the dashboard first")
                inner = "/".join(parts[len(comps):])
                why = originals_lane.list_rule_reason(inner)
                if why is not None:
                    raise Refused(f"it is not a camera original ({why})")
                return tree_rel, Path(local_root).joinpath(*parts)
        raise Refused("its project is not ticked on this computer")

    def _gate(self, local: Path) -> None:
        if self.platform == "darwin" and not FETCH_ENABLED_ON_MACOS:
            raise Refused(MACOS_REFUSAL)
        if self.halted:
            raise Refused("syncing is stopped on this computer (a sync halt), so nothing is "
                          "brought down")
        refuse = self._fetch_refusal
        if refuse is None:
            from . import broll_fetch  # noqa: PLC0415  (broll_fetch imports the sync package)

            refuse = broll_fetch.fetch_refusal
        why = refuse(self.cfg, str(local.parent))
        if why:
            raise Refused(str(why).replace(" -- ", ", "))

    @staticmethod
    def _existing_folder(path: Path) -> Path:
        probe = path
        while not probe.exists() and probe.parent != probe:
            probe = probe.parent
        return probe

    # -- the work ---------------------------------------------------------------------------------
    def run(self, clip: dict) -> Outcome:
        name = _display_name(clip)
        out = Outcome(name=name, kind="refused", timecode=clip.get("timecode", ""),
                      angle_timeline=clip.get("angle_timeline", ""),
                      angle_timecode=clip.get("angle_timecode", ""))
        try:
            self._run(clip, out)
        except (Refused, hollow.LayoutRefused, hollow.HollowRefused) as exc:
            out.kind, out.sentence = "refused", _clause(str(exc))
        except TransportError as exc:
            log.warning("grading frames: %s: %s", name, exc)
            out.kind = "refused"
            out.sentence = ("the server could not be read just now, so nothing was fetched. "
                            "Try again in a minute")
        except Exception:
            log.exception("grading frames: %s failed", name)
            out.kind, out.sentence = "refused", "something went wrong (see the log)"
        return out

    def _run(self, clip: dict, out: Outcome) -> None:
        tree_rel, local = self._place(clip)
        self._gate(local)
        led = self.led or hollow.ledger()
        existing: Optional[dict] = None
        if os.path.lexists(local):
            got = hollow.signs(local, marker=True)
            if not got.any():
                raise Refused("its real original is already on this computer, so there is "
                              "nothing to fetch")
            if not got.ours():
                raise Refused("something CC Sync did not make is already at its path (a cloud "
                              "placeholder?), so nothing was written over it")
            existing = got.entry or {"nas_size": (got.marker_doc or {}).get("real_size"),
                                     "nas_mtime": (got.marker_doc or {}).get("nas_mtime")}
        sparse_why = hollow.sparse_refusal(self._existing_folder(local.parent))
        if sparse_why:
            raise Refused(sparse_why)
        stat = self.transport.stat(tree_rel)
        if stat is None:
            raise Refused("it is not on the server at that path")
        size, mtime = stat
        if existing is not None and (str(existing.get("nas_size")) != str(size)
                                     or _times_differ(existing.get("nas_mtime"), mtime)):
            # Doc 3.5: the server's file changed since the frames were fetched, so they describe
            # a file that is no longer there. Dropped under the all-three-signs rule, then made
            # afresh; a copy that cannot be dropped is kept and the request refused.
            removed, why = hollow.remove_hollow(local, led)
            if not removed:
                raise Refused(f"its grading frames are out of date and the old copy was kept ({why})")
            existing = None
        local.parent.mkdir(parents=True, exist_ok=True)
        if size < WHOLE_FILE_BELOW and existing is None:
            self._whole(tree_rel, local, out)
            return
        reader = RangeCache(lambda off, n: self.transport.read_range(tree_rel, off, n))
        head = reader(0, min(hollow.HEAD_BYTES, size))
        moov_offset, moov_length, _ = hollow.locate_index(head, size)
        index = hollow.parse_index(head, reader(moov_offset, moov_length), size)
        wanted = frame_set(clip["frames"], clip["uses"], index.frame_count,
                           margin=MARGIN_EXACT if clip.get("exact", True) else MARGIN_INEXACT)
        held = []
        if existing is not None:
            held = list((hollow.read_marker(local) or {}).get("frames") or [])
        every = sorted(set(wanted) | set(held) | {0})
        written = (index.head_length + index.moov_length + 512
                   + sum(index.frames[f][1] for f in every))
        if written > size * WHOLE_FILE_FRACTION:
            if existing is not None:
                removed, why = hollow.remove_hollow(local, led)
                if not removed:
                    raise Refused(f"these frames are most of the clip, and its old grading-frame "
                                  f"copy could not be removed to bring the whole original ({why})")
            self._whole(tree_rel, local, out)
            return
        reader.prefetch(index.frames[f] for f in every if f not in held)
        if existing is not None:
            hollow.add_frames(local, wanted, reader, nas_size=size, nas_mtime=mtime, led=led)
            out.kind = "added"
        else:
            hollow.build_hollow(local, index, wanted, reader, nas_mtime=mtime, led=led)
            out.kind = "made"
        out.frames = wanted
        log.info("grading frames: %s %s (%d frames, %d reads)", out.kind, local, len(wanted),
                 reader.reads)

    def _whole(self, tree_rel: str, local: Path, out: Outcome) -> None:
        if os.path.lexists(local):
            raise Refused("its real original is already on this computer, so there is nothing "
                          "to fetch")
        self.transport.fetch_whole(tree_rel, local)
        if not local.is_file():
            raise Refused("the whole original did not arrive")
        out.kind = "whole"
        log.info("grading frames: brought the whole original %s", local)


# =============================================================================================
# The balloons (doc 3.2)
# =============================================================================================

LOAD_SENTENCE = ("Switch to another timeline and back to load {it}, and set Playback > Proxy "
                 "Handling to Prefer Camera Originals to see {it}.")
REOPEN_SENTENCE = "Close and reopen the project to see the new frames."


def _at(outcome: Outcome) -> str:
    return f" at {outcome.timecode}" if outcome.timecode else ""


def _angle(outcome: Outcome) -> str:
    if not outcome.angle_timeline:
        return ""
    where = f" at {outcome.angle_timecode}" if outcome.angle_timecode else ""
    return (f" Its raw settings are in the angle timeline {outcome.angle_timeline}{where} "
            "(Scripts > CC Sync > Go to grading frame).")


def balloon(outcomes: list[Outcome], script_refusals: Iterable[str] = ()) -> str:
    """One balloon per request. A single clip gets doc 3.2's own sentences; a batch is counted."""
    script_refusals = [s for s in script_refusals if s]
    made = [o for o in outcomes if o.kind == "made"]
    added = [o for o in outcomes if o.kind == "added"]
    whole = [o for o in outcomes if o.kind == "whole"]
    refused = [o for o in outcomes if o.kind == "refused"]
    if len(outcomes) == 1 and not script_refusals:
        o = outcomes[0]
        if o.kind == "made":
            return (f"Grading frame ready: {o.name}{_at(o)}. "
                    + LOAD_SENTENCE.format(it="it") + _angle(o))
        if o.kind == "added":
            return f"Added to {o.name}. {REOPEN_SENTENCE}" + _angle(o)
        if o.kind == "whole":
            return (f"{o.name} is small, so its whole original came down instead of a grading "
                    f"frame. " + LOAD_SENTENCE.format(it="it"))
        return f"No grading frame for {o.name}: {o.sentence}."
    parts: list[str] = []
    ready = len(made) + len(whole)
    if ready:
        parts.append(f"Grading frames ready for {ui_copy.count(ready, 'clip')}. "
                     + LOAD_SENTENCE.format(it="them" if ready > 1 else "it"))
    if added:
        parts.append(f"Added to {ui_copy.count(len(added), 'clip')} that already had grading "
                     f"frames. {REOPEN_SENTENCE}")
    failures = [f"{o.name}: {o.sentence}" for o in refused] + list(script_refusals)
    if failures:
        lead = "No grading frame for " if not (ready or added) else "Not fetched, "
        parts.append(f"{lead}{ui_copy.count(len(failures), 'clip')}. {failures[0].rstrip('. ')}."
                     + (f" ({len(failures) - 1} more in the log.)" if len(failures) > 1 else ""))
    return " ".join(parts) or "Nothing was asked for."


# =============================================================================================
# The service: inbox, worker, housekeeping, Settings
# =============================================================================================

class GradingFrames:
    """The request inbox and its one worker thread. Not a lane."""

    def __init__(self, cfg: dict[str, Any], selection_fn: Callable[[], Optional[list]],
                 notify_fn: Callable[[str], None], halted_fn: Callable[[], bool] = lambda: False,
                 transport: Optional[Transport] = None, inbox: Optional[Path] = None,
                 clock: Callable[[], float] = time.time, platform: str = sys.platform,
                 fetch_refusal: Optional[Callable[[dict, str], Optional[str]]] = None) -> None:
        self.cfg = cfg
        self._selection_fn = selection_fn
        self._notify = notify_fn
        self._halted_fn = halted_fn
        self.transport = transport or Transport(cfg)
        self._inbox = inbox
        self._clock = clock
        self.platform = platform
        self._fetch_refusal = fetch_refusal
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._progress: Optional[tuple[int, int]] = None

    @property
    def inbox(self) -> Path:
        return self._inbox or request_dir()

    # -- the thread ----------------------------------------------------------------------------
    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="ccsync-grading-frames", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        self.housekeeping()
        while not self._stop.is_set():
            try:
                if self.poll_once():
                    self.housekeeping()
            except Exception:
                log.exception("grading frames: inbox poll failed")
            self._stop.wait(POLL_SECONDS)

    # -- the tray line -------------------------------------------------------------------------
    def tray_line(self) -> Optional[str]:
        """One line while a batch runs, else None. A read of two ints, no I/O."""
        with self._lock:
            progress = self._progress
        if progress is None:
            return None
        done, total = progress
        if total <= 1:
            return "Fetching a grading frame"
        return f"Fetching grading frames: {done} of {total} clips"

    def _set_progress(self, value: Optional[tuple[int, int]]) -> None:
        with self._lock:
            self._progress = value

    # -- the inbox -----------------------------------------------------------------------------
    def poll_once(self) -> int:
        try:
            names = sorted(p for p in self.inbox.iterdir() if p.is_file())
        except FileNotFoundError:
            return 0
        except OSError:
            log.debug("grading frames: cannot read %s", self.inbox, exc_info=True)
            return 0
        finished = 0
        for path in names:
            if path.suffix.lower() == ".json":
                finished += 1 if self._handle(path) else 0
            elif path.name.endswith(".tmp") and self._age(path) > MAX_AGE_SECONDS:
                self._delete(path, "a half-written request older than an hour")
        return finished

    def _age(self, path: Path) -> float:
        try:
            return self._clock() - path.stat().st_mtime
        except OSError:
            return 0.0

    def _delete(self, path: Path, why: str) -> None:
        try:
            path.unlink()
            log.info("grading frames: removed request %s (%s)", path.name, why)
        except FileNotFoundError:
            pass
        except OSError:
            log.warning("grading frames: could not remove request %s", path, exc_info=True)

    def _handle(self, path: Path) -> bool:
        try:
            raw = path.read_bytes()
        except OSError:
            return False
        try:
            request = parse_request(raw)
        except RequestError as exc:
            log.warning("grading frames: request %s is malformed (%s), deleting it", path.name, exc)
            self._delete(path, "malformed")
            return True
        created = originals_requests._created_epoch(request["created_at"])
        age = max(self._age(path), (self._clock() - created) if created is not None else 0.0)
        if age > MAX_AGE_SECONDS:
            log.warning("grading frames: request %s is %.0f minutes old, deleting it unanswered",
                        path.name, age / 60.0)
            self._delete(path, "older than an hour")
            return True
        # Deleted BEFORE the work: a request that takes minutes must not be picked up twice by a
        # restart, and one that failed is answered with a balloon, not retried behind the
        # editor's back.
        self._delete(path, "taken")
        message = self.answer(request)
        try:
            self._notify(message)
        except Exception:
            log.debug("grading frames: balloon failed", exc_info=True)
        return True

    def answer(self, request: dict) -> str:
        """Fetch every clip of one request, two at a time. -> the balloon."""
        clips = merge_clips(request["clips"])
        try:
            selection = self._selection_fn()
        except Exception:
            log.debug("grading frames: selection read failed", exc_info=True)
            selection = None
        try:
            halted = bool(self._halted_fn())
        except Exception:
            halted = False
        worker = ClipFetch(self.cfg, self.transport, selection, halted, platform=self.platform,
                           fetch_refusal=self._fetch_refusal)
        outcomes: list[Outcome] = []
        if clips:
            self._set_progress((0, len(clips)))
            try:
                with ThreadPoolExecutor(max_workers=CLIPS_AT_A_TIME,
                                        thread_name_prefix="ccsync-grading-clip") as pool:
                    for outcome in pool.map(worker.run, clips):
                        outcomes.append(outcome)
                        self._set_progress((len(outcomes), len(clips)))
            finally:
                self._set_progress(None)
        for o in outcomes:
            if o.kind == "refused":
                log.info("grading frames: %s refused: %s", o.name, o.sentence)
        return balloon(outcomes, request["refused"])

    # -- housekeeping (the worker owns it) -------------------------------------------------------
    def housekeeping(self) -> None:
        """Old copies `add_frames` set aside, removed once Resolve lets go; ledger rows whose file
        is gone, forgotten. Never raises."""
        try:
            hollow.sweep_asides()
        except Exception:
            log.exception("grading frames: aside sweep failed")
        try:
            prune_ledger()
        except Exception:
            log.exception("grading frames: ledger prune failed")

    # -- Settings --------------------------------------------------------------------------------
    @staticmethod
    def count() -> int:
        return len(held_copies())

    def remove_all(self) -> str:
        return remove_all()


def held_copies(led: Optional[hollow.HollowLedger] = None) -> list[dict]:
    """Every grading-frame copy this computer holds now: ledger rows (not asides) whose file is
    there at the size the row recorded."""
    led = led or hollow.ledger()
    return [e for e in led.entries()
            if not e.get("aside_of")
            and hollow.HollowLedger.stands(e, hollow._size_of(e.get("local_path")))]


def prune_ledger(led: Optional[hollow.HollowLedger] = None) -> int:
    """Forget rows whose file is gone. ONLY while the folder it lived in is there: an unplugged
    drive makes every file unstattable at once, and forgetting then would cost every copy its
    ledger sign (the b-roll stand-ins' comp-broll-tiers-1 lesson). -> rows forgotten."""
    led = led or hollow.ledger()
    gone = 0
    now = time.time()
    for entry in led.entries():
        path = str(entry.get("local_path") or "")
        if not path or os.path.lexists(path):
            continue
        # A row is written BEFORE its file is renamed into place (hollow.build_hollow,
        # move_aside), and Bring originals does that on another thread. Pruned in that instant
        # the copy would land with no ledger row, and could then never be removed by the button
        # (review, 2026-11-22). Ten minutes is far longer than any rename.
        try:
            if now - float(entry.get("placed_at") or 0) < PRUNE_MIN_AGE_SECONDS:
                continue
        except (TypeError, ValueError):
            pass
        if not os.path.isdir(os.path.dirname(path)):
            continue
        if led.forget(path):
            gone += 1
    if gone:
        log.info("grading frames: forgot %d ledger row(s) whose file is gone", gone)
    return gone


def remove_all(led: Optional[hollow.HollowLedger] = None) -> str:
    """[ REMOVE GRADING FRAMES ]: every hollow copy, through hollow.remove_hollow (all three signs,
    any doubt keeps the file). -> the sentence for the balloon."""
    led = led or hollow.ledger()
    copies = held_copies(led)
    if not copies:
        return "There are no grading frames on this computer."
    removed, kept = 0, []
    for entry in copies:
        ok, why = hollow.remove_hollow(entry["local_path"], led)
        if ok:
            removed += 1
        else:
            kept.append((_display_name({"file_path": entry["local_path"]}), why))
    parts = []
    if removed:
        parts.append(f"Removed the grading frames of {ui_copy.count(removed, 'clip')}. Reopen the "
                     "project in Resolve to see the proxies again.")
    if kept:
        first_name, first_why = kept[0]
        parts.append(f"Kept {ui_copy.count(len(kept), 'clip')}: {first_name}, because {first_why}."
                     + (" If Resolve has the project open, close it and try again."
                        if any("could not be removed yet" in why for _, why in kept) else ""))
    return " ".join(parts)


SETTINGS_RENDER_SENTENCE = ("This computer cannot render the final picture from these clips: a "
                            "render stops at the first frame that was not fetched.")


def settings_lines(count: int) -> list[str]:
    """The Settings > THIS COMPUTER text, pure (the window adds the button)."""
    return [f"Grading frames: {ui_copy.count(count, 'clip')}", SETTINGS_RENDER_SENTENCE]
