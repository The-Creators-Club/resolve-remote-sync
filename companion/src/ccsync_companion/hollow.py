"""Hollow copies: a camera original's index and a few of its frames, at the original's own path.

docs/GRADING_FRAMES.md (2026-11-22, RSV-147). A remote editor grades a BRAW clip from ONE real
frame: the companion fetches the clip's head, its index (`moov`) and the frames asked for, and
writes them at their own offsets into a SPARSE file of the original's length, so the rest of it
takes no room on the disk. Resolve opens it as the real clip (same path, same length and
timecode), shows the fetched frames pixel for pixel and every other frame Media Offline.

This module is phase 1 of that plan (section 7): the index parser, the sparse writer, the marker,
the ledger and the predicate. Companion release A ships it with NOTHING in the running app able
to create a hollow copy: every reader in section 4 asks the predicate first, so a build that can
make one is never older than a build that knows what one is (D5, section 8). Until phase 3 the
writer is exercised by tests only.

A HOLLOW COPY MUST NEVER COUNT AS THE FOOTAGE (section 4). It has the original's name, sits at
the original's path, is almost exactly the original's length and holds a few frames. Three
independent signs mark it, so that no single lost file or missed code path turns it into "a copy":

  1. THE LEDGER, `<state>/grading_frames.json`, keyed by the normalised local path (CR-90), and
     FALSIFIABLE against the file: a row stands only while the file at that path is the size the
     row recorded (the b-roll stand-in ledger's lesson, broll_standins.py). The real original
     arriving by any route makes the row describe nothing.
  2. THE MARKER, a trailing `free` atom holding `{"ccsync": "hollow", ...}`, readable from the
     last few KB by any tool. It also makes the length differ from the original's, so no
     name-and-size comparison anywhere matches a hollow copy to the real file.
  3. THE FILESYSTEM: allocated size far below the length. Needs no ledger and no read.

and two questions, deliberately different:

  * `is_hollow(path, st)`: MUST THIS FILE NOT BE TREATED AS FOOTAGE? Yes on ANY sign. Cheap
    enough for walks that stat every file: the ledger is a dict lookup, the filesystem sign comes
    from the stat the walk already holds (plus one GetCompressedFileSizeW on Windows, only for a
    file whose attributes say it might be sparse). The marker is read only when asked to be
    (`deep=True`, for readers that touch few files) or, in a walk's `Pass`, when the filesystem
    sign fired alone and the log line has to say whether the file is ours.
  * `may_delete(path)`: MAY THIS FILE BE DELETED AS A HOLLOW COPY? Only when ALL THREE agree (doc
    section 3.5, last bullet). Any doubt keeps the file and says so in the log. `remove_hollow`
    asks it again at the moment of the unlink: it is the one delete in the feature.

PATHS (CR-90, docs/GOTCHAS.md section 17): the ledger key is only ever compared, so it goes through
broll_standins.normalise_key (NFC, then canon.norm). The path a row STORES, and every path this
module opens, renames or deletes, keeps its bytes.

Nothing here calls Resolve.
"""

from __future__ import annotations

import io
import json
import logging
import os
import secrets
import stat as stat_mod
import struct
import sys
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from . import config as config_mod
from .broll_standins import normalise_key as _standins_normalise_key

log = logging.getLogger("ccsync.hollow")

STATE_FILENAME = "grading_frames.json"
LEDGER_VERSION = 1

# -- the BRAW layout (docs/GRADING_FRAMES.md section 2.1) ---------------------------------------
# Every frame of the 157 clips swept starts with these eight bytes. The cheap "this really is a
# frame" check after a fetch: a range read from the wrong offset, or a NAS file that changed
# under its index, fails it.
FRAME_MAGIC = b"\x00\x00\x04\x00bmdf"
# Section 3.4 step 2 reads the first 64 KB: the headers, the timecode sample and the first
# frame's header. A clip whose first frame starts later than that is a layout this build has
# not seen (every clip swept had it at byte 4,100) and is refused, not guessed at.
HEAD_BYTES = 64 * 1024
# The BRAW codec variants seen in the sweep were brlt, brst and brxq. Blackmagic's four-character
# codes all start "br"; anything else in a .braw's picture track is not a layout we know.
BRAW_CODEC_PREFIX = b"br"
# The top-level boxes that may sit before `mdat`. A BRAW has `wide` alone; `ftyp`, `free` and
# `skip` are harmless QuickTime fillers. `moov` before `mdat` is the "index not last" refusal.
_PRE_MDAT_BOXES = frozenset({"wide", "ftyp", "free", "skip"})

# -- the marker (section 4, sign 2) -------------------------------------------------------------
MARKER_TYPE = b"free"
MARKER_KIND = "hollow"
MARKER_VERSION = 1
# The marker atom is small (a line of JSON). Bounding it is what keeps "read the tail" cheap and
# what lets a reader find the atom's start without walking the file.
MARKER_MAX_BYTES = 4096

# -- the filesystem sign (section 4, sign 3) ----------------------------------------------------
# THE SPARSE ATTRIBUTE ALONE IS NOT A SIGN (2026-11-22). rclone's multi-thread downloads create
# local files sparse on Windows (`--local-no-sparse`: "On Windows platforms rclone will make sparse
# files when doing multi-thread downloads"), so a WHOLE original brought down by Bring originals
# can carry FILE_ATTRIBUTE_SPARSE_FILE while every byte is allocated. Verified on creator-1 with
# the bundled rclone v1.74.4: a 40 MiB multi-thread copy came out attributes 0x220 (sparse) with
# GetCompressedFileSizeW = 41,943,040, exactly its length. Calling that file hollow would stop
# lane A uploading it and the manifest counting it: a footage-safety failure in the other
# direction. The sign is ALLOCATED SIZE FAR BELOW LENGTH; the attribute is only the pre-filter
# that decides whether the allocation is worth asking for.
#
# THE THRESHOLD: less than HALF the length allocated. A complete real file is fully allocated
# whatever its attribute says: NTFS allocates every byte written, zeros included, and rclone
# writes every byte. A rename into place is the only way rclone's file reaches its final name, so
# a half-downloaded one is never under the original's name either. Half leaves a wide margin
# above cluster and sparse-granule rounding (64 KiB on NTFS) and above an in-place partial, and a
# file less than half there is not a usable copy of anything by any measure. A hollow copy whose
# kept frames are MORE than half its clip (a one-second clip of 15 MB frames) does not show this
# sign; the ledger and the marker still mark it, and it can never be deleted automatically, which
# is the safe way to be wrong.
SPARSE_ALLOCATED_FRACTION = 0.5
# Below a megabyte the rounding is noise next to the length, and no camera original is that
# small (field_mode.UNKNOWN_ORIGINAL_BYTES draws the same line for the same reason).
SPARSE_MIN_BYTES = 1 << 20

# Windows file attributes (winnt.h).
_FILE_ATTRIBUTE_SPARSE_FILE = 0x200
_FILE_ATTRIBUTE_COMPRESSED = 0x800
_FILE_ATTRIBUTE_OFFLINE = 0x1000
_FILE_ATTRIBUTE_RECALL_ON_OPEN = 0x40000
_FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x400000
# Placeholders (OneDrive "online only", any Cloud Files provider) whose data is not on the disk.
_PLACEHOLDER_ATTRIBUTES = (_FILE_ATTRIBUTE_OFFLINE | _FILE_ATTRIBUTE_RECALL_ON_OPEN
                           | _FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS)
# macOS st_flags (sys/stat.h): transparently compressed (decmpfs) and dataless (an iCloud
# placeholder). A compressed file is allocated below its length for a reason that is not ours.
_UF_COMPRESSED = 0x20
_SF_DATALESS = 0x40000000

# Temporary names: lane A's video filter does not carry them (not a video extension), the
# carry-all filter and lane C both ignore `*.ccsync-tmp` (rclone_lane.CARRY_ALL_NAME_EXCLUDE_RULES,
# syncthing_admin), and originals_lane refuses the ending. A hollow copy is never visible to any
# reader half built.
TEMP_SUFFIX = ".ccsync-tmp"
_BUILD_TAG = "hollow"
_ASIDE_TAG = "hollow-aside"

ASIDE_ADDED_FRAMES = "added_frames"
ASIDE_ORIGINALS = "originals"

_COPY_CHUNK = 4 << 20


class LayoutRefused(ValueError):
    """A layout the parser does not recognise, or a range that does not check out. `str()` is a
    sentence naming the cause, fit for the editor (no em dashes)."""


class HollowRefused(RuntimeError):
    """The writer will not build (or add to) this hollow copy. `str()` is a sentence naming the
    cause, fit for the editor (no em dashes)."""


# =============================================================================================
# The index
# =============================================================================================

@dataclass(frozen=True)
class BrawIndex:
    """Where every frame of a .braw is. `frames[i] = (offset, length)`, in file order."""
    file_size: int
    moov_offset: int
    moov_length: int
    mdat_body_offset: int
    codec: str
    frames: tuple = ()

    @property
    def frame_count(self) -> int:
        return len(self.frames)

    @property
    def head_length(self) -> int:
        """The bytes before the first frame: the headers and the timecode sample."""
        return int(self.frames[0][0])


def _walk(fh: Any, size: int) -> dict[str, Any]:
    """field_mode.walk_boxes, the one ISO-BMFF box walker in the companion (its quick verify reads
    the same `moov`). Imported late: field_mode imports ledger_scan, which imports this module."""
    from .field_mode import walk_boxes  # noqa: PLC0415

    return walk_boxes(fh, size)


def _children(body: bytes) -> list[tuple[str, bytes]]:
    """The child boxes of a container's body, as (type, body). Through the same walker as the top
    level, over the bytes in hand; a child list that does not run to the container's end is
    refused, because a half-read index is the one thing that must never be trusted."""
    walked = _walk(io.BytesIO(body), len(body))
    # QuickTime lets a container end in a 32-bit zero terminator (fewer than 8 bytes, which the
    # walker reports as "short"); the spike's walker stepped over it, so this does too. Anything
    # else that does not run to the end is refused.
    padded = walked["stop"] == "short" and not any(body[walked["at"]:])
    if walked["stop"] != "eof" and not padded:
        raise LayoutRefused("the clip's index is damaged or in a shape this computer does not "
                            "read (a box inside it does not end where it should)")
    out = []
    for box in walked["boxes"]:
        start = box["off"]
        header = 16 if int.from_bytes(body[start:start + 4], "big") == 1 else 8
        out.append((box["type"], body[start + header:start + box["len"]]))
    return out


def _child(body: bytes, kind: str) -> Optional[bytes]:
    for name, inner in _children(body):
        if name == kind:
            return inner
    return None


def locate_index(head: bytes, file_size: int) -> tuple[int, int, int]:
    """From the head of a .braw (its first HEAD_BYTES) and its length on the server: (moov offset,
    moov length, offset of the mdat's first byte). The index must be LAST: the box after `mdat`
    is the index and nothing follows it. Raises LayoutRefused naming what is wrong."""
    try:
        size = int(file_size)
    except (TypeError, ValueError):
        raise LayoutRefused("the clip's size on the server is not a number") from None
    if size <= 16 or len(head) < 16:
        raise LayoutRefused("the clip is too small to be a camera original")
    walked = _walk(io.BytesIO(bytes(head)), size)
    mdat = None
    for box in walked["boxes"]:
        if box["type"] == "mdat":
            mdat = box
            break
        if box["type"] == "moov":
            raise LayoutRefused("the clip's index is at the start of the file, not the end, which "
                                "is a layout this build does not fetch frames from")
        if box["type"] not in _PRE_MDAT_BOXES:
            raise LayoutRefused(f"the clip starts with a {box['type']!r} box, which is not a "
                                "Blackmagic RAW layout this build knows")
    if mdat is None:
        if walked["stop"] == "overrun":
            raise LayoutRefused("the clip's boxes run past its end (a damaged or still-recording file)")
        raise LayoutRefused("the clip has no picture data box (mdat) where a Blackmagic RAW file has it")
    after = mdat["off"] + mdat["len"]
    if after >= size:
        raise LayoutRefused("the clip has no index after its picture data, so the index is not last "
                            "(or the recording was interrupted)")
    header = 16 if int.from_bytes(head[mdat["off"]:mdat["off"] + 4], "big") == 1 else 8
    return after, size - after, mdat["off"] + header


def parse_index(head: bytes, moov: bytes, file_size: int) -> BrawIndex:
    """The frame table of a .braw: `head` its first bytes (HEAD_BYTES is what the fetch reads),
    `moov` every byte from the index's offset to the end of the file, `file_size` the original's
    length. Refuses, with a sentence naming the cause, every layout section 3.4 says to refuse:
    the index not last, more than one frame per chunk, chunk offsets it does not understand, a
    sync-sample table (frames that depend on each other), frames out of their data box, a first
    frame past the head."""
    moov_offset, moov_length, mdat_body = locate_index(head, file_size)
    moov = bytes(moov)
    if len(moov) != moov_length:
        raise LayoutRefused(f"the index read was {len(moov)} bytes where the clip says {moov_length}")
    if len(moov) < 8 or moov[4:8] != b"moov":
        raise LayoutRefused("the box after the picture data is not the clip's index (moov)")
    declared = int.from_bytes(moov[0:4], "big")
    header = 8
    if declared == 1:
        declared = int.from_bytes(moov[8:16], "big")
        header = 16
    elif declared == 0:
        declared = len(moov)
    if declared != len(moov):
        raise LayoutRefused("something follows the clip's index, so the index is not the last "
                            "thing in the file")
    traks = [inner for name, inner in _children(moov[header:]) if name == "trak"]
    videos = []
    for trak in traks:
        mdia = _child(trak, "mdia")
        hdlr = _child(mdia, "hdlr") if mdia is not None else None
        if hdlr is not None and len(hdlr) >= 12 and hdlr[8:12] == b"vide":
            videos.append(mdia)
    if not videos:
        raise LayoutRefused("the clip's index has no picture track")
    if len(videos) > 1:
        raise LayoutRefused("the clip has more than one picture track, which is not a Blackmagic "
                            "RAW layout this build knows")
    minf = _child(videos[0], "minf")
    stbl = _child(minf, "stbl") if minf is not None else None
    if stbl is None:
        raise LayoutRefused("the clip's picture track has no sample table")
    tables = dict(_children(stbl))
    stsd = tables.get("stsd") or b""
    codec_raw = stsd[12:16] if len(stsd) >= 16 else b""
    codec = codec_raw.decode("latin1") if codec_raw else "?"
    if not codec_raw.startswith(BRAW_CODEC_PREFIX):
        raise LayoutRefused(f"the clip's pictures are {codec!r}, not Blackmagic RAW")
    if "stss" in tables:
        raise LayoutRefused("the clip has a sync-sample table, so its frames depend on each other "
                            "and one cannot be fetched alone")
    if "ctts" in tables:
        raise LayoutRefused("the clip stores its frames out of display order, which this build "
                            "does not fetch from")
    stsz = tables.get("stsz")
    if stsz is None or len(stsz) < 12:
        raise LayoutRefused("the clip's index has no frame sizes")
    uniform, count = struct.unpack(">II", stsz[4:12])
    if count <= 0:
        raise LayoutRefused("the clip's index lists no frames")
    if uniform:
        sizes = (uniform,) * count
    else:
        if len(stsz) < 12 + 4 * count:
            raise LayoutRefused("the clip's frame size table is shorter than its frame count")
        sizes = struct.unpack(f">{count}I", stsz[12:12 + 4 * count])
    stsc = tables.get("stsc")
    if stsc is None or len(stsc) < 8:
        raise LayoutRefused("the clip's index does not say how frames are grouped")
    entries = struct.unpack(">I", stsc[4:8])[0]
    if entries <= 0 or len(stsc) < 8 + 12 * entries:
        raise LayoutRefused("the clip's frame grouping table is damaged")
    for j in range(entries):
        _first, per_chunk, _desc = struct.unpack(">III", stsc[8 + 12 * j:20 + 12 * j])
        if per_chunk != 1:
            raise LayoutRefused("the clip keeps more than one frame per chunk, which is a layout "
                                "this build does not fetch frames from")
    if "co64" in tables:
        table, width, fmt = tables["co64"], 8, "Q"
    elif "stco" in tables:
        table, width, fmt = tables["stco"], 4, "I"
    else:
        raise LayoutRefused("the clip's index has no frame offsets this build understands (neither "
                            "64-bit nor 32-bit chunk offsets)")
    if len(table) < 8:
        raise LayoutRefused("the clip's frame offset table is damaged")
    chunks = struct.unpack(">I", table[4:8])[0]
    if chunks != count:
        raise LayoutRefused(f"the clip's index lists {chunks} chunks for {count} frames, so a frame "
                            "is not its own chunk")
    if len(table) < 8 + width * count:
        raise LayoutRefused("the clip's frame offset table is shorter than its frame count")
    offsets = struct.unpack(f">{count}{fmt}", table[8:8 + width * count])
    frames = []
    for i, (off, length) in enumerate(zip(offsets, sizes)):
        if length < len(FRAME_MAGIC) or off < mdat_body or off + length > moov_offset:
            raise LayoutRefused(f"frame {i} of the clip lies outside its picture data")
        frames.append((int(off), int(length)))
    if frames[0][0] + len(FRAME_MAGIC) > HEAD_BYTES:
        raise LayoutRefused(f"the clip's first frame starts at byte {frames[0][0]}, past the "
                            f"{HEAD_BYTES // 1024} KB head this build reads")
    if min(off for off, _ in frames) != frames[0][0]:
        raise LayoutRefused("the clip's first frame is not the first thing in its picture data")
    return BrawIndex(file_size=int(file_size), moov_offset=moov_offset, moov_length=moov_length,
                     mdat_body_offset=mdat_body, codec=codec, frames=tuple(frames))


def check_frame(data: bytes, number: int, length: int) -> None:
    """A fetched frame is the right length and starts the way every BRAW frame does
    (`00 00 04 00 'bmdf'`). Raises LayoutRefused naming the frame."""
    if len(data) != length:
        raise LayoutRefused(f"frame {number} came back {len(data)} bytes long where the clip's index "
                            f"says {length}")
    if not bytes(data[:len(FRAME_MAGIC)]) == FRAME_MAGIC:
        raise LayoutRefused(f"frame {number} does not start the way a Blackmagic RAW frame does, "
                            "so the clip on the server may have changed")


# =============================================================================================
# The marker
# =============================================================================================

def marker_bytes(real_size: int, frames: Iterable[int], nas_mtime: str = "") -> bytes:
    """The trailing `free` atom: `<u32 length>free{"ccsync": "hollow", ...}`. Appended at the
    original's length, so a hollow copy is always longer than the original by exactly this."""
    body = json.dumps({"ccsync": MARKER_KIND, "v": MARKER_VERSION, "real_size": int(real_size),
                       "frames": sorted({int(f) for f in frames}), "nas_mtime": str(nas_mtime or ""),
                       "made": time.strftime("%Y-%m-%dT%H:%M:%S")},
                      separators=(",", ":")).encode("utf-8")
    atom = struct.pack(">I4s", 8 + len(body), MARKER_TYPE) + body
    if len(atom) > MARKER_MAX_BYTES:
        raise HollowRefused(f"too many frames for one grading-frame copy ({len(atom)} bytes of "
                            f"marker, {MARKER_MAX_BYTES} allowed)")
    return atom


def parse_marker_tail(tail: bytes, file_size: int) -> Optional[dict[str, Any]]:
    """The marker in the last bytes of a file of `file_size`, or None. FALSIFIABLE: the atom must
    end exactly at the end of the file AND start exactly at the `real_size` it names, so a `free`
    atom that merely happens to sit at the end of some real file is not taken for ours."""
    data = bytes(tail)
    for start in range(len(data) - 8, -1, -1):
        if data[start + 4:start + 8] != MARKER_TYPE:
            continue
        if int.from_bytes(data[start:start + 4], "big") != len(data) - start:
            continue
        try:
            doc = json.loads(data[start + 8:].decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return None
        if not isinstance(doc, dict) or doc.get("ccsync") != MARKER_KIND:
            return None
        try:
            real = int(doc.get("real_size"))
        except (TypeError, ValueError):
            return None
        if real + (len(data) - start) != int(file_size):
            return None
        frames = doc.get("frames")
        if not isinstance(frames, list) or not all(isinstance(f, int) and f >= 0 for f in frames):
            return None
        return doc
    return None


def read_marker(path: Any, st: Optional[os.stat_result] = None) -> Optional[dict[str, Any]]:
    """The marker of the file at `path`, or None (no marker, not a file, cannot read it). One
    open, one read of at most MARKER_MAX_BYTES from the end. Never raises."""
    try:
        with open(path, "rb") as fh:
            size = os.fstat(fh.fileno()).st_size
            want = min(size, MARKER_MAX_BYTES)
            if want < 8:
                return None
            fh.seek(size - want)
            tail = fh.read(want)
        return parse_marker_tail(tail, size)
    except OSError:
        return None
    except Exception:                                             # noqa: BLE001
        log.debug("hollow: could not read the marker of %r", path, exc_info=True)
        return None


# THE MARKER VERDICT, REMEMBERED (review, 2026-11-22). Lane A's periodic walk has to read the
# marker of every original it is about to let rclone upload: a hollow copy that was COPIED (a
# sync tree moved to a new drive in Explorer or Finder, a project folder duplicated) loses its
# ledger row, because the path changed, AND its holes, because the copy filled them in. The
# marker is then the only sign left, and the file is a clip-sized run of zeros under the
# original's name that `copy --ignore-existing` would make the NAS's permanent copy the day the
# real one is not at that path. One open and one 4 KB read per file is too much every two
# minutes for ever, and nothing once: a file's verdict cannot change while its size and
# modification time do not. In memory only; a restart reads each file once more.
_MARKER_CACHE_MAX = 200_000
_marker_cache: dict[tuple[str, int, int], bool] = {}
_marker_cache_lock = threading.Lock()


def has_marker(path: Any, st: Optional[os.stat_result] = None) -> bool:
    """Does this file carry the hollow marker? `read_marker`, remembered by (path, size, mtime).
    For a walk that must ask about every file; `may_delete` never uses it (a delete reads the
    file itself, at that moment). Never raises."""
    st = _stat(path, st)
    if st is None:
        return False
    try:
        stamp = int(getattr(st, "st_mtime_ns", 0) or int(float(st.st_mtime) * 1e9))
        key = (str(path), int(st.st_size), stamp)
    except Exception:                                             # noqa: BLE001
        return read_marker(path) is not None
    with _marker_cache_lock:
        held = _marker_cache.get(key)
    if held is not None:
        return held
    verdict = read_marker(path) is not None
    with _marker_cache_lock:
        if len(_marker_cache) >= _MARKER_CACHE_MAX:
            _marker_cache.clear()
        _marker_cache[key] = verdict
    return verdict


# =============================================================================================
# The filesystem
# =============================================================================================

_win_api: Optional[Any] = None
_win_api_lock = threading.Lock()


def _win() -> Any:
    """kernel32 with the five calls this module uses, argtypes set once. Windows only."""
    global _win_api
    with _win_api_lock:
        if _win_api is None:
            import ctypes  # noqa: PLC0415
            from ctypes import wintypes  # noqa: PLC0415

            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            k32.GetCompressedFileSizeW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
            k32.GetCompressedFileSizeW.restype = wintypes.DWORD
            k32.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPVOID,
                                            wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD,
                                            ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
            k32.DeviceIoControl.restype = wintypes.BOOL
            k32.GetVolumePathNameW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
            k32.GetVolumePathNameW.restype = wintypes.BOOL
            k32.GetVolumeInformationW.argtypes = [
                wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
                ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD), wintypes.LPWSTR,
                wintypes.DWORD]
            k32.GetVolumeInformationW.restype = wintypes.BOOL
            _win_api = (ctypes, wintypes, k32)
        return _win_api


_FSCTL_SET_SPARSE = 0x000900C4
_FILE_SUPPORTS_SPARSE_FILES = 0x00000040
_INVALID_FILE_SIZE = 0xFFFFFFFF


def _plain_win_path(path: str) -> str:
    """`\\\\?\\C:\\x` -> `C:\\x` and `\\\\?\\UNC\\s\\x` -> `\\\\s\\x`: the extended-length prefix
    ledger_scan.long_path adds, removed for a key that has to compare equal to the plain spelling."""
    text = str(path)
    if text.startswith("\\\\?\\UNC\\"):
        return "\\\\" + text[8:]
    if text.startswith("\\\\?\\"):
        return text[4:]
    return text


def _regular(st: Any) -> bool:
    """A plain file, by a stat the caller holds. A stat-like object with no mode (a test's
    stand-in, a caller's own record) cannot say, and the caller has already listed it as a file."""
    mode = getattr(st, "st_mode", None)
    return True if mode is None else stat_mod.S_ISREG(mode)


def allocated_bytes(path: Any, st: Optional[os.stat_result] = None) -> Optional[int]:
    """How many bytes of this file are on the disk, or None when it cannot be told.
    Windows: GetCompressedFileSizeW (for a sparse file, the allocated size). Elsewhere:
    st_blocks * 512. Never raises."""
    try:
        if os.name == "nt":
            ctypes, wintypes, k32 = _win()
            high = wintypes.DWORD(0)
            ctypes.set_last_error(0)
            low = k32.GetCompressedFileSizeW(str(path), ctypes.byref(high))
            if low == _INVALID_FILE_SIZE and ctypes.get_last_error() != 0:
                return None
            return (int(high.value) << 32) | int(low)
        if st is None:
            st = os.stat(path)
        blocks = getattr(st, "st_blocks", None)
        return None if blocks is None else int(blocks) * 512
    except Exception:                                             # noqa: BLE001
        return None


def filesystem_sign(path: Any, st: Optional[os.stat_result] = None) -> bool:
    """Sign 3: is this file's allocated size far below its length (SPARSE_ALLOCATED_FRACTION)?

    Needs no ledger and no read. On Windows the attributes in the stat a walk already holds are
    the pre-filter: only a file marked sparse, or a cloud placeholder (offline / recall on
    access), costs a GetCompressedFileSizeW. The attribute ALONE is never the answer (see
    SPARSE_ALLOCATED_FRACTION: rclone's multi-thread downloads are sparse and whole). An NTFS
    compressed file that is not sparse is allocated below its length for a reason that is not
    ours and is never this sign; likewise a macOS decmpfs-compressed file. Never raises; a stat
    that cannot be read is no sign."""
    try:
        if st is None:
            st = os.stat(path)
        if not _regular(st):
            return False
        size = int(st.st_size)
        if size < SPARSE_MIN_BYTES:
            return False
        if os.name == "nt":
            attrs = int(getattr(st, "st_file_attributes", 0) or 0)
            placeholder = bool(attrs & _PLACEHOLDER_ATTRIBUTES)
            if not (attrs & _FILE_ATTRIBUTE_SPARSE_FILE) and not placeholder:
                return False
            allocated = allocated_bytes(path, st)
            if allocated is None:
                # A placeholder's data is elsewhere whatever the size call says; a file that is
                # only marked sparse and cannot be measured is NOT called hollow on the mark.
                return placeholder
        else:
            flags = int(getattr(st, "st_flags", 0) or 0)
            if flags & _SF_DATALESS:
                return True
            if flags & _UF_COMPRESSED:
                return False
            blocks = getattr(st, "st_blocks", None)
            if blocks is None:
                return False
            allocated = int(blocks) * 512
            if allocated <= 0:
                # NOTHING AT ALL ON THE DISK IS "CANNOT TELL", NOT "HOLLOW" (review, 2026-11-22).
                # Some network and FUSE mounts answer st_blocks = 0 for every file. Believed,
                # that would call every original on such a drive hollow: lane A would upload
                # none of them and the manifest would count none. A hollow copy this feature
                # made always has its head and index on the disk, so zero is never ours; a
                # real iCloud placeholder is caught by SF_DATALESS above. Not verified on a Mac
                # (doc section 6 item 1).
                return False
        return allocated < size * SPARSE_ALLOCATED_FRACTION
    except Exception:                                             # noqa: BLE001
        log.debug("hollow: could not read the filesystem sign of %r", path, exc_info=True)
        return False


def filesystem_name(path: Any) -> str:
    """The name of the filesystem `path` is on ("NTFS", "exFAT", "apfs", ...), or "" when it
    cannot be told. For the D3 refusal sentence. Never raises.

    macOS: statfs(2)'s f_fstypename through ctypes, NOT VERIFIED ON A MAC as of 2026-11-22 (doc
    section 6 item 1): the 64-bit-inode struct, via the `statfs$INODE64` symbol on Intel and
    plain `statfs` on Apple silicon, where it is the only one."""
    try:
        if os.name == "nt":
            ctypes, wintypes, k32 = _win()
            target = str(path)
            buf = ctypes.create_unicode_buffer(1024)
            if not k32.GetVolumePathNameW(target, buf, len(buf)):
                return ""
            name = ctypes.create_unicode_buffer(64)
            flags = wintypes.DWORD(0)
            if not k32.GetVolumeInformationW(buf.value, None, 0, None, None,
                                             ctypes.byref(flags), name, len(name)):
                return ""
            return name.value
        if sys.platform == "darwin":
            return _darwin_fstypename(str(path))
        return _proc_mounts_type(str(path))
    except Exception:                                             # noqa: BLE001
        log.debug("hollow: could not name the filesystem of %r", path, exc_info=True)
        return ""


def _darwin_fstypename(path: str) -> str:
    import ctypes  # noqa: PLC0415
    import ctypes.util  # noqa: PLC0415

    class _StatFS(ctypes.Structure):
        _fields_ = [("f_bsize", ctypes.c_uint32), ("f_iosize", ctypes.c_int32),
                    ("f_blocks", ctypes.c_uint64), ("f_bfree", ctypes.c_uint64),
                    ("f_bavail", ctypes.c_uint64), ("f_files", ctypes.c_uint64),
                    ("f_ffree", ctypes.c_uint64), ("f_fsid", ctypes.c_int32 * 2),
                    ("f_owner", ctypes.c_uint32), ("f_type", ctypes.c_uint32),
                    ("f_flags", ctypes.c_uint32), ("f_fssubtype", ctypes.c_uint32),
                    ("f_fstypename", ctypes.c_char * 16), ("f_mntonname", ctypes.c_char * 1024),
                    ("f_mntfromname", ctypes.c_char * 1024), ("f_flags_ext", ctypes.c_uint32),
                    ("f_reserved", ctypes.c_uint32 * 7)]

    libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
    try:
        fn = getattr(libc, "statfs$INODE64")
    except AttributeError:
        fn = libc.statfs
    fn.argtypes = [ctypes.c_char_p, ctypes.POINTER(_StatFS)]
    fn.restype = ctypes.c_int
    out = _StatFS()
    if fn(os.fsencode(path), ctypes.byref(out)) != 0:
        return ""
    return out.f_fstypename.decode("utf-8", "replace")


def _proc_mounts_type(path: str) -> str:
    best, kind = "", ""
    full = os.path.realpath(path)
    with open("/proc/self/mounts", encoding="utf-8") as fh:
        for line in fh:
            parts = line.split()
            if len(parts) < 3:
                continue
            mount = parts[1].replace("\\040", " ")
            if (full == mount or full.startswith(mount.rstrip("/") + "/")) and len(mount) > len(best):
                best, kind = mount, parts[2]
    return kind


# Filesystems known to keep a sparse file's holes empty, and known not to. Lower case.
_SPARSE_YES = frozenset({"ntfs", "refs", "apfs", "ext4", "ext3", "xfs", "btrfs", "zfs", "tmpfs", "f2fs"})
_SPARSE_NO = frozenset({"exfat", "fat", "fat32", "vfat", "msdos", "hfs", "udf"})


def can_hold_sparse(folder: Any) -> tuple[Optional[bool], str]:
    """D3: can this folder's drive hold a sparse file? -> (answer, filesystem name). None means it
    could not be told; the writer treats that as no. Windows asks the volume's own flag
    (FILE_SUPPORTS_SPARSE_FILES); elsewhere the name decides, and a name on neither list is
    PROBED: one temporary file, one byte written 8 MiB in, its allocation measured, removed."""
    name = filesystem_name(folder)
    try:
        if os.name == "nt":
            ctypes, wintypes, k32 = _win()
            buf = ctypes.create_unicode_buffer(1024)
            if not k32.GetVolumePathNameW(str(folder), buf, len(buf)):
                return None, name
            flags = wintypes.DWORD(0)
            if not k32.GetVolumeInformationW(buf.value, None, 0, None, None, ctypes.byref(flags),
                                             None, 0):
                return None, name
            return bool(flags.value & _FILE_SUPPORTS_SPARSE_FILES), name
        lowered = name.lower()
        if lowered in _SPARSE_YES:
            return True, name
        if lowered in _SPARSE_NO:
            return False, name
        return _probe_sparse(folder), name
    except Exception:                                             # noqa: BLE001
        log.debug("hollow: could not tell whether %r holds sparse files", folder, exc_info=True)
        return None, name


def _probe_sparse(folder: Any) -> Optional[bool]:
    probe = Path(folder) / f".ccsync-sparse-probe-{os.getpid()}-{secrets.token_hex(4)}{TEMP_SUFFIX}"
    try:
        with open(probe, "xb") as fh:
            fh.seek(8 << 20)
            fh.write(b"\0")
            fh.flush()
            os.fsync(fh.fileno())
        allocated = allocated_bytes(probe)
        return None if allocated is None else allocated < (1 << 20)
    except OSError:
        return None
    finally:
        try:
            os.unlink(probe)
        except OSError:
            pass


def sparse_refusal(folder: Any) -> Optional[str]:
    """D3's refusal sentence for a drive that cannot hold grading frames, or None when it can."""
    able, name = can_hold_sparse(folder)
    if able:
        return None
    if able is None:
        return ("This computer could not tell whether the sync drive can hold grading frames"
                + (f" (it is formatted {name})" if name else "")
                + ", so none were fetched. Nothing large is written by surprise.")
    return (f"The sync drive is formatted {name or 'in a format'} that cannot keep the empty "
            "parts of a file empty, so a grading frame would take up the whole clip's size. "
            "None were fetched.")


def _set_sparse(fh: Any) -> None:
    """Mark an open, still empty file sparse BEFORE anything is written to it. Windows only, and
    through DeviceIoControl, never `fsutil`: no child process for every clip, and no console
    window flashing on the editor's screen. On APFS and the Linux filesystems every file can be
    sparse and there is nothing to set."""
    if os.name != "nt":
        return
    import msvcrt  # noqa: PLC0415

    ctypes, wintypes, k32 = _win()
    handle = msvcrt.get_osfhandle(fh.fileno())
    returned = wintypes.DWORD(0)
    if not k32.DeviceIoControl(handle, _FSCTL_SET_SPARSE, None, 0, None, 0,
                               ctypes.byref(returned), None):
        err = ctypes.get_last_error()
        raise HollowRefused(f"the sync drive would not mark the file sparse (Windows error {err}), "
                            "so no grading frame was written")


# =============================================================================================
# The ledger
# =============================================================================================

def normalise_key(path: Any) -> str:
    """The ledger's comparison key: broll_standins.normalise_key (CR-90: NFC first, then
    canon.norm for case and separators), after dropping the extended-length prefix a walk may
    have put on a Windows path. NEVER a path to open."""
    text = str(path or "")
    if not text:
        return ""
    return _standins_normalise_key(_plain_win_path(text))


def default_state_path(ccsync_cfg: Optional[dict] = None) -> Path:
    """`<log dir>/state/grading_frames.json`, beside every other companion ledger (app.py derives
    the state dir the same way; broll_standins.default_state_path is the pattern, including its
    rule that a lazy read must never create config.toml)."""
    cfg = ccsync_cfg
    try:
        if cfg is None:
            cfg = (config_mod.load_config() if config_mod.CONFIG_PATH.exists()
                   else dict(config_mod.DEFAULTS))
        return config_mod.resolved_log_path(cfg).parent / "state" / STATE_FILENAME
    except Exception:                                             # noqa: BLE001
        return config_mod.CONFIG_DIR / "state" / STATE_FILENAME


def _size_of(path: Any) -> Optional[int]:
    try:
        return int(os.stat(path).st_size)
    except Exception:                                             # noqa: BLE001
        return None


class HollowLedger:
    """`grading_frames.json`: every hollow copy this machine has placed. One entry per path:

        {local_path, size, nas_size, nas_mtime, frames, placed_at, placed_at_iso,
         aside_of?, aside_reason?}

    `size` is the hollow copy's OWN length, and it is what makes the entry falsifiable: a file at
    that path of any other size is not the copy we placed, so the entry is no sign at all
    (`stands`). An `aside_of` entry is an old hollow copy renamed out of the way (a fuller one
    replaced it, or the real original is coming down), kept until it can be removed.

    Re-read whenever the file's (mtime, size) changes, written tmp + os.replace with a pid-unique
    temporary name (comp-sync-1's lesson in broll_standins). A corrupt file is an empty ledger
    plus one warning; nothing here raises."""

    def __init__(self, path: Any) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()
        self._entries: dict[str, dict[str, Any]] = {}
        self._stamp: Optional[tuple[float, int]] = None
        self._loaded = False
        self._warned_corrupt = False

    def _file_stamp(self) -> Optional[tuple[float, int]]:
        try:
            st = self.path.stat()
            return (float(st.st_mtime), int(st.st_size))
        except Exception:                                         # noqa: BLE001
            return None

    def _load_locked(self) -> None:
        stamp = self._file_stamp()
        if self._loaded and stamp == self._stamp:
            return
        self._stamp, self._loaded = stamp, True
        if stamp is None:
            self._entries = {}
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            if not self._warned_corrupt:
                self._warned_corrupt = True
                log.warning("grading frames: %s is not readable JSON, treating it as empty. A "
                            "grading-frame copy made before now is still recognised by its marker "
                            "and by the filesystem, but cannot be removed automatically", self.path)
            self._entries = {}
            return
        rows = data.get("hollow") if isinstance(data, dict) else None
        self._entries = ({str(k): dict(v) for k, v in rows.items() if isinstance(v, dict)}
                         if isinstance(rows, dict) else {})
        self._warned_corrupt = False

    def _persist_locked(self) -> bool:
        tmp = self.path.with_name(f"{self.path.name}.{os.getpid()}.tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps({"version": LEDGER_VERSION, "hollow": self._entries},
                                      indent=1, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self.path)
        except (OSError, TypeError, ValueError) as exc:
            log.warning("grading frames: could not write %s: %s", self.path, exc)
            try:
                tmp.unlink()
            except OSError:
                pass
            return False
        self._stamp = self._file_stamp()
        return True

    # -- writes -----------------------------------------------------------------------------
    def record(self, local_path: Any, size: int, nas_size: int, nas_mtime: str = "",
               frames: Iterable[int] = (), aside_of: Optional[str] = None,
               aside_reason: Optional[str] = None) -> bool:
        """Remember a hollow copy at `local_path`. True when it was written down. Called BEFORE
        the rename into place, so a crash leaves a row (falsifiable by size) rather than a hollow
        copy nobody wrote down."""
        key = normalise_key(local_path)
        if not key:
            return False
        entry = {"local_path": str(local_path), "size": int(size), "nas_size": int(nas_size),
                 "nas_mtime": str(nas_mtime or ""), "frames": sorted({int(f) for f in frames}),
                 "placed_at": time.time(), "placed_at_iso": time.strftime("%Y-%m-%dT%H:%M:%S")}
        if aside_of:
            entry["aside_of"] = str(aside_of)
            entry["aside_reason"] = str(aside_reason or "")
        with self._lock:
            self._load_locked()
            previous = self._entries.get(key)
            self._entries[key] = entry
            if self._persist_locked():
                return True
            if previous is None:
                self._entries.pop(key, None)
            else:
                self._entries[key] = previous
            return False

    def forget(self, local_path: Any) -> bool:
        key = normalise_key(local_path)
        with self._lock:
            self._load_locked()
            if key not in self._entries:
                return False
            self._entries.pop(key, None)
            self._persist_locked()
            return True

    def restore(self, local_path: Any, entry: Optional[dict[str, Any]]) -> None:
        """Put back exactly what was there before (a write that has to be undone)."""
        key = normalise_key(local_path)
        with self._lock:
            self._load_locked()
            if entry is None:
                self._entries.pop(key, None)
            else:
                self._entries[key] = dict(entry)
            self._persist_locked()

    def relocated(self, old_dir: Any, new_dir: Any) -> int:
        """A folder holding hollow copies was moved (commands.file_moves, a folder): re-key every
        row under it, so the ledger sign follows the files. -> how many rows moved."""
        old_key = normalise_key(old_dir).rstrip("\\/")
        if not old_key:
            return 0
        moved = 0
        with self._lock:
            self._load_locked()
            for key, entry in list(self._entries.items()):
                if not (key.startswith(old_key + "\\") or key.startswith(old_key + "/")):
                    continue
                raw = str(entry.get("local_path") or "")
                tail = _plain_win_path(raw)[len(_plain_win_path(str(old_dir)).rstrip("\\/")):]
                new_path = str(new_dir).rstrip("\\/") + tail
                self._entries.pop(key, None)
                entry = dict(entry, local_path=new_path)
                self._entries[normalise_key(new_path)] = entry
                moved += 1
            if moved:
                self._persist_locked()
        return moved

    # -- reads ------------------------------------------------------------------------------
    def get(self, local_path: Any) -> Optional[dict[str, Any]]:
        key = normalise_key(local_path)
        if not key:
            return None
        with self._lock:
            self._load_locked()
            entry = self._entries.get(key)
            return dict(entry) if entry is not None else None

    def snapshot(self) -> dict[str, dict[str, Any]]:
        """Every row by key, copied: what a walk reads once instead of once per file."""
        with self._lock:
            self._load_locked()
            return {k: dict(v) for k, v in self._entries.items()}

    def entries(self) -> list[dict[str, Any]]:
        with self._lock:
            self._load_locked()
            return [dict(v) for v in self._entries.values()]

    @staticmethod
    def stands(entry: Optional[dict[str, Any]], actual_size: Optional[int]) -> bool:
        """Is this row still a sign for a file of `actual_size`? Only when the file is the very
        size the row recorded: anything else (the real original arriving, a file replaced) has
        falsified it. An absent file is no sign either: there is nothing to keep from anyone."""
        if not entry or actual_size is None:
            return False
        try:
            return int(entry.get("size")) == int(actual_size)
        except (TypeError, ValueError):
            return False


_LEDGER_LOCK = threading.Lock()
_LEDGER: Optional[HollowLedger] = None
_LEDGER_ENV: Optional[tuple] = None
_CONFIGURED: Optional[tuple[HollowLedger, tuple]] = None


def _env_key() -> tuple:
    """What the default path depends on. Re-resolved only when this changes, so a per-file ask
    does not read config.toml, and a test (whose HOME and CONFIG_PATH conftest redirects) never
    reads or writes another test's ledger."""
    return (str(config_mod.CONFIG_PATH), os.environ.get("HOME"), os.environ.get("USERPROFILE"))


def ledger() -> HollowLedger:
    """The process's ledger. `configure()` wins while the environment it was configured under is
    unchanged (app startup); otherwise the default path."""
    global _LEDGER, _LEDGER_ENV
    env = _env_key()
    with _LEDGER_LOCK:
        if _CONFIGURED is not None and _CONFIGURED[1] == env:
            return _CONFIGURED[0]
        if _LEDGER is None or _LEDGER_ENV != env:
            _LEDGER, _LEDGER_ENV = HollowLedger(default_state_path()), env
        return _LEDGER


def configure(path: Any) -> HollowLedger:
    """Point the process's ledger at `path` (app startup, beside broll_standins.configure)."""
    global _CONFIGURED
    with _LEDGER_LOCK:
        led = HollowLedger(path)
        _CONFIGURED = (led, _env_key())
        return led


# =============================================================================================
# The predicate
# =============================================================================================

@dataclass
class Signs:
    """The three signs for one file. `marker` is None when it was not read."""
    ledger: bool = False
    marker: Optional[bool] = None
    filesystem: bool = False
    entry: Optional[dict[str, Any]] = None
    marker_doc: Optional[dict[str, Any]] = None

    def any(self) -> bool:
        return bool(self.ledger or self.marker or self.filesystem)

    def all(self) -> bool:
        return bool(self.ledger and self.marker and self.filesystem)

    def ours(self) -> bool:
        """The ledger or the marker: a hollow copy THIS feature made, as opposed to a file the
        filesystem merely says is mostly holes (a cloud placeholder, something we did not make)."""
        return bool(self.ledger or self.marker)

    def describe(self) -> str:
        return ", ".join(f"{name} {'yes' if value else ('not read' if value is None else 'no')}"
                         for name, value in (("ledger", self.ledger), ("marker", self.marker),
                                             ("filesystem", self.filesystem)))


def _stat(path: Any, st: Optional[os.stat_result]) -> Optional[os.stat_result]:
    if st is not None:
        return st
    try:
        return os.stat(path)
    except OSError:
        return None


def signs(path: Any, st: Optional[os.stat_result] = None, *, marker: bool = True,
          snapshot: Optional[dict[str, dict[str, Any]]] = None) -> Signs:
    """Every sign for the file at `path`. `snapshot` is a `HollowLedger.snapshot()` a walk took
    once; without one the process ledger is asked. Never raises."""
    out = Signs()
    st = _stat(path, st)
    if st is None or not _regular(st):
        return out
    try:
        if snapshot is None:
            entry = ledger().get(path)
        elif snapshot:
            entry = snapshot.get(normalise_key(path))
        else:
            entry = None
        out.entry = dict(entry) if entry else None
        out.ledger = HollowLedger.stands(entry, int(st.st_size))
    except Exception:                                             # noqa: BLE001
        log.debug("hollow: ledger lookup failed for %r", path, exc_info=True)
    out.filesystem = filesystem_sign(path, st)
    if marker:
        doc = read_marker(path)
        out.marker = doc is not None
        out.marker_doc = doc
    return out


def is_hollow(path: Any, st: Optional[os.stat_result] = None, *, deep: bool = False,
              snapshot: Optional[dict[str, dict[str, Any]]] = None) -> bool:
    """MUST THIS FILE NOT BE TREATED AS FOOTAGE? True on ANY of the three signs (module docstring).

    Cheap by default: the ledger (a lookup) and the filesystem (from `st` when the caller holds
    one). `deep=True` also reads the marker when neither of those fired, for a reader that touches
    a handful of files and can afford one small read each (Bring originals' plan, a file move,
    the field quick verify): that is what catches a hollow copy that was copied somewhere that
    filled its holes and whose ledger row is on another computer. Never raises; a file that
    cannot be stat'ed is not hollow (there is nothing there to mistake)."""
    st = _stat(path, st)
    if st is None or not _regular(st):
        return False
    got = signs(path, st, marker=False, snapshot=snapshot)
    if got.ledger or got.filesystem:
        return True
    if deep:
        return read_marker(path) is not None
    return False


def may_delete(path: Any) -> tuple[bool, str]:
    """MAY THIS FILE BE DELETED AS A HOLLOW COPY? Only when all three signs agree AND agree with
    each other: the ledger row stands (same size), the marker is there and names the size the
    ledger was told the original had, and the filesystem says the file is mostly holes. Anything
    else is doubt, and doubt keeps the file. -> (yes, the reason in words). Never raises."""
    try:
        st = os.lstat(path)
    except OSError:
        return False, "it is not there"
    if not stat_mod.S_ISREG(st.st_mode):
        return False, "it is not a plain file"
    got = signs(path, st, marker=True)
    if not got.all():
        return False, f"not every sign agrees that it is a grading-frame copy ({got.describe()})"
    try:
        if int((got.marker_doc or {}).get("real_size")) != int((got.entry or {}).get("nas_size")):
            return False, ("its marker and the ledger disagree about the original's size "
                           f"({(got.marker_doc or {}).get('real_size')} and "
                           f"{(got.entry or {}).get('nas_size')})")
    except (TypeError, ValueError):
        return False, "its marker or its ledger row does not name the original's size"
    return True, "the ledger, the marker and the filesystem all say it is a grading-frame copy"


def remove_hollow(path: Any, led: Optional[HollowLedger] = None) -> tuple[bool, str]:
    """THE ONE DELETE IN THIS FEATURE (doc section 3.5). Asks `may_delete` at the moment of the
    unlink; any doubt keeps the file and is logged. A file Resolve still holds is kept too and
    can be tried again later. -> (removed, the reason in words). Never raises."""
    ok, why = may_delete(path)
    if not ok:
        log.warning("grading frames: kept %s rather than delete it: %s", path, why)
        return False, why
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
    except OSError as exc:
        log.info("grading frames: %s could not be removed yet (%s); it stays and is tried again",
                 path, exc)
        return False, f"it could not be removed yet ({exc})"
    (led or ledger()).forget(path)
    log.info("grading frames: removed the grading-frame copy %s", path)
    return True, why


class Pass:
    """One walk's view of the predicate: the ledger read ONCE, and the log line trap 2 asks for.

    A real file excluded on the filesystem sign alone (no ledger row, and no marker when the walk
    may read one) is a cloud-drive placeholder or something this feature did not make, and it is
    NAMED in the log, once per walk: being kept out of the upload and the manifest in silence is
    how a real problem hides. `read_marker=False` is for a walk that must not open files
    (ledger_scan's read-only rule); its line then says the marker was not looked for.

    `deep=True` (lane A's walk) also asks the MARKER of a file neither cheap sign names, through
    `has_marker`'s memory: see _marker_cache for the copy that has only its marker left."""

    def __init__(self, reader: str, *, read_marker: bool = True, deep: bool = False,
                 snapshot: Optional[dict[str, dict[str, Any]]] = None) -> None:
        self.reader = reader
        self.read_marker = read_marker
        self.deep = bool(deep and read_marker)
        self.marker_only: list[str] = []
        try:
            self._snapshot = ledger().snapshot() if snapshot is None else snapshot
        except Exception:                                         # noqa: BLE001
            log.debug("hollow: could not read the ledger for %s", reader, exc_info=True)
            self._snapshot = {}
        self.excluded_count = 0
        self.unexplained: list[str] = []
        self._named: set[str] = set()

    def excluded(self, path: Any, st: Optional[os.stat_result] = None) -> bool:
        """Is this file to be skipped as not-footage? Never raises."""
        try:
            st = _stat(path, st)
            if st is None or not _regular(st):
                return False
            got = signs(path, st, marker=False, snapshot=self._snapshot)
            if not (got.ledger or got.filesystem):
                if not (self.deep and has_marker(path, st)):
                    return False
                text = str(path)
                if text not in self._named:
                    self._named.add(text)
                    self.marker_only.append(text)
                    log.warning(
                        "%s: not treating %s as footage: it carries the grading-frame marker, "
                        "though it has no ledger row on this computer and its empty parts are "
                        "filled in (a grading-frame copy that was copied from somewhere else). "
                        "It holds a few frames of the clip and can be deleted by hand "
                        "(docs/GRADING_FRAMES.md section 4)", self.reader, text)
                self.excluded_count += 1
                return True
            self.excluded_count += 1
            if got.filesystem and not got.ledger:
                self._explain(path, st, got)
            return True
        except Exception:                                         # noqa: BLE001
            log.debug("hollow: %s could not judge %r", self.reader, path, exc_info=True)
            return False

    def _explain(self, path: Any, st: os.stat_result, got: Signs) -> None:
        marker = read_marker(path) if self.read_marker else None
        if marker is not None:
            return          # ours, written down nowhere on this computer: the marker says so
        text = str(path)
        if text in self._named:
            return
        self._named.add(text)
        self.unexplained.append(text)
        allocated = allocated_bytes(path, st)
        log.warning(
            "%s: not treating %s as footage: only %s of its %d bytes are on the disk, and it %s "
            "and no grading-frames ledger row. It is a cloud-drive placeholder or a file CC Sync "
            "did not make (docs/GRADING_FRAMES.md section 4)", self.reader, text,
            "?" if allocated is None else f"{allocated}", int(st.st_size),
            "carries no grading-frame marker" if self.read_marker else "was not opened to look for a marker")


# =============================================================================================
# Lane A's exclusions (section 4, first row)
# =============================================================================================

PROJECTS_PREFIX = "Projects/"
# The whole-tree walk behind a `subpath=None` ask (express, an unmanaged whole-tree pass) is
# reused this long: express asks on every flush and its own partition already checks each file
# it is about to send (rclone_lane._express_partition), so this list is the second door, not the
# first.
TREE_WALK_TTL_SECONDS = 300.0
_tree_cache: dict[str, tuple[float, list[str]]] = {}
_tree_cache_lock = threading.Lock()


def _rel_under(path: str, root: str) -> Optional[str]:
    """`path` relative to `root`, `/`-separated, in the bytes it was given; None when outside.
    Compared through the ledger key (NFC, case, separators); the tail keeps its own spelling."""
    p_key, r_key = normalise_key(path), normalise_key(root).rstrip("\\/")
    if not r_key or not (p_key.startswith(r_key + "\\") or p_key.startswith(r_key + "/")):
        return None
    plain = _plain_win_path(str(path))
    tail = plain[len(_plain_win_path(str(root)).rstrip("\\/")):]
    return tail.replace("\\", "/").strip("/") or None


def _walk_video_files(base: str) -> Iterable[tuple[str, os.stat_result]]:
    """Every video file under `base` (rclone_lane.VIDEO_EXTS), skipping what lane A never carries
    anyway: Proxy folders, the lane B trash, hidden and Syncthing folders. os.scandir, so on
    Windows the attributes come with the directory listing and cost no extra call."""
    from .sync import rclone_lane  # noqa: PLC0415  (rclone_lane imports this module)

    exts = {e.lower() for e in rclone_lane.VIDEO_EXTS}
    stack = [base]
    while stack:
        directory = stack.pop()
        try:
            with os.scandir(directory) as it:
                entries = list(it)
        except OSError:
            continue
        for entry in entries:
            name = entry.name
            try:
                if entry.is_dir(follow_symlinks=False):
                    lowered = name.lower()
                    if lowered == "proxy" or name.startswith(".") or entry.is_symlink():
                        continue
                    stack.append(entry.path)
                    continue
                if os.path.splitext(name)[1].lower() not in exts or name.startswith("._"):
                    continue
                if not entry.is_file(follow_symlinks=False):
                    continue
                yield entry.path, entry.stat(follow_symlinks=False)
            except OSError:
                continue


def lane_a_excludes(local_root: Any, subpath: Optional[str], *,
                    clock: Callable[[], float] = time.monotonic) -> list[str]:
    """The paths lane A must leave out of a run rooted at `subpath` (`Projects/<rel>`, or None
    for local_root itself), relative to that root, `/`-separated: every ledger row under it, and
    every file a walk of it finds hollow by the filesystem sign OR by its marker (a deep Pass:
    lane A is where a hollow copy taken for footage does permanent damage, so it is the one walk
    that asks all three signs of every file). Both Unicode spellings, as
    file_moves.recent_excludes emits them (SYNC-11: rclone matches the bytes it reads off the
    disk, and a Mac's are NFD). Never raises: a source of excludes that cannot answer must not
    stop the upload (rclone_lane._build_command's rule), and the express door checks each file
    itself."""
    out: list[str] = []
    try:
        root_text = str(local_root or "")
        if not root_text:
            return []
        sub = str(subpath or "").replace("\\", "/").strip("/")
        base = os.path.join(root_text, *sub.split("/")) if sub else root_text
        rels: list[str] = []
        for entry in ledger().entries():
            rel = _rel_under(str(entry.get("local_path") or ""), base)
            if rel and HollowLedger.stands(entry, _size_of(entry.get("local_path"))):
                rels.append(rel)
        if sub:
            check = Pass("lane A", deep=True)
            for path, st in _walk_video_files(base):
                if check.excluded(path, st):
                    rel = _rel_under(path, base)
                    if rel:
                        rels.append(rel)
        else:
            rels += _tree_walk(root_text, clock)
        for rel in rels:
            for spelling in (unicodedata.normalize("NFC", rel), unicodedata.normalize("NFD", rel)):
                if spelling not in out:
                    out.append(spelling)
        if out:
            log.info("lane A: leaving %d grading-frame cop%s out of this run (%s)",
                     len(rels), "y" if len(rels) == 1 else "ies", sub or "the whole tree")
    except Exception:                                             # noqa: BLE001
        log.exception("grading frames: lane A exclusions failed; the express door still checks")
    return out


def _tree_walk(root_text: str, clock: Callable[[], float]) -> list[str]:
    key = normalise_key(root_text)
    now = clock()
    with _tree_cache_lock:
        held = _tree_cache.get(key)
        if held is not None and now - held[0] < TREE_WALK_TTL_SECONDS:
            return list(held[1])
    base = os.path.join(root_text, "Projects")
    check = Pass("lane A", deep=True)
    rels = []
    for path, st in _walk_video_files(base):
        if check.excluded(path, st):
            rel = _rel_under(path, root_text)
            if rel:
                rels.append(rel)
    with _tree_cache_lock:
        _tree_cache[key] = (now, list(rels))
    return rels


# =============================================================================================
# The writer (phase 1; nothing in the running app calls it until phase 3)
# =============================================================================================

ReadRange = Callable[[int, int], bytes]


@dataclass
class _Range:
    offset: int
    length: int
    read: ReadRange
    frame: Optional[int] = None
    what: str = ""


def _temp_name(dest: Path, tag: str) -> Path:
    return dest.with_name(f"{dest.name}.{tag}-{os.getpid()}-{secrets.token_hex(4)}{TEMP_SUFFIX}")


def _rename_no_clobber(src: Path, dst: Path) -> None:
    """Rename `src` to `dst` only if nothing is at `dst`. A REAL ORIGINAL can land at that path
    while a hollow copy is being built (Bring originals, the editor's own copy), and `os.replace`
    would silently put the hollow copy over it. Windows' rename refuses an existing target by
    itself; on POSIX a hard link refuses it (and is atomic), with a checked rename as the
    fallback for a filesystem that will not link."""
    if os.name == "nt":
        os.rename(src, dst)
        return
    try:
        os.link(src, dst)
    except FileExistsError:
        raise
    except OSError:
        if os.path.lexists(dst):
            raise FileExistsError(f"{dst} already exists") from None
        os.rename(src, dst)
        return
    os.unlink(src)


def _read_exact(read: ReadRange, offset: int, length: int, what: str) -> bytes:
    data = read(int(offset), int(length))
    if data is None or len(data) != length:
        raise HollowRefused(f"the {what} came back {0 if data is None else len(data)} bytes long "
                            f"where {length} were asked for, so nothing was written")
    return bytes(data)


def _write_ranges(temp: Path, ranges: list[_Range], real_size: int, marker: bytes) -> int:
    """Create `temp` sparse, write each range at its offset, the marker last at `real_size`.
    -> the bytes written. NEVER truncate() to extend the file (doc section 2.2): the C runtime
    zero-fills, which fills the holes (measured: 1.9 GB allocated for a 3 GB "hollow" clip). On a
    sparse file, seeking past the end and writing leaves a hole; the index, written at the end,
    sets the length and the marker after it adds its own few bytes."""
    written = 0
    with open(temp, "xb") as fh:
        _set_sparse(fh)
        for rng in sorted(ranges, key=lambda r: r.offset):
            left, pos = rng.length, rng.offset
            while left:
                step = min(left, _COPY_CHUNK)
                chunk = _read_exact(rng.read, pos, step, rng.what)
                if rng.frame is not None and pos == rng.offset:
                    # The whole frame's length was asked for and every chunk is checked for its
                    # length above; its start is what says it IS a frame.
                    check_frame(chunk[:len(FRAME_MAGIC)], rng.frame, len(FRAME_MAGIC))
                fh.seek(pos)
                fh.write(chunk)
                pos += step
                left -= step
                written += step
        fh.seek(real_size)
        fh.write(marker)
        fh.flush()
        os.fsync(fh.fileno())
    return written


def _check_allocation(temp: Path, written: int, n_ranges: int) -> None:
    """Nothing large is ever written by surprise (D3): the file on the disk must hold about what
    was written, not the clip's length. A drive that said it could hold sparse files and then
    filled the holes in (an SMB share that claims support, a filesystem that zero-fills) is
    caught here, before the file is renamed into place."""
    allocated = allocated_bytes(temp)
    if allocated is None:
        raise HollowRefused("this computer could not measure how much of the grading-frame copy "
                            "is on the disk, so it was not kept")
    # NTFS allocates a sparse file in compression units (64 KiB with 4 KiB clusters, more on a
    # volume formatted with large clusters), so each range can round up at both ends. 2 MiB a
    # range is far above that and far below "the holes were filled in", which is the clip's size.
    slack = (2 << 20) * (n_ranges + 1)
    # ...AND IT MUST SHOW THE FILESYSTEM SIGN (2026-11-22, from the first CI run on a Mac). The
    # slack above is megabytes, so on a small clip a drive that filled every hole in still
    # passed: GitHub's macOS runner (APFS) left a 10 MB test clip fully allocated and the copy
    # was placed. A copy that is not mostly holes is a clip-sized file the predicate's third
    # sign cannot see and `may_delete` can never remove, so it is never placed, whatever the
    # reason it came out that way.
    try:
        length = int(os.stat(temp).st_size)
    except OSError:
        length = 0
    not_hollow = length > 0 and allocated >= length * SPARSE_ALLOCATED_FRACTION
    if not_hollow or allocated > written + MARKER_MAX_BYTES + slack:
        name = filesystem_name(temp.parent)
        raise HollowRefused(f"the sync drive{f' ({name})' if name else ''} filled in the empty parts "
                            f"of the grading-frame copy ({allocated} bytes on the disk for {written} "
                            "written), so it was not kept")


def _frame_set(index: BrawIndex, frames: Iterable[int]) -> list[int]:
    wanted = set()
    for f in frames:
        try:
            n = int(f)
        except (TypeError, ValueError):
            raise HollowRefused(f"{f!r} is not a frame number") from None
        if n < 0 or n >= index.frame_count:
            raise HollowRefused(f"frame {n} is outside the clip (it has {index.frame_count} frames)")
        wanted.add(n)
    # Frame 0 always: Blackmagic's decoder reads the first frame's header to open the clip at all
    # (doc section 2.2), and fetching it whole gives the clip a picture at its start too.
    wanted.add(0)
    return sorted(wanted)


def _build(dest: Path, index: BrawIndex, ranges: list[_Range], frames: list[int],
           nas_mtime: str) -> tuple[Path, int]:
    """Write a complete hollow copy under a temporary name beside `dest`. -> (temp, its length).
    The temporary file is removed on any failure."""
    refusal = sparse_refusal(dest.parent)
    if refusal:
        raise HollowRefused(refusal)
    marker = marker_bytes(index.file_size, frames, nas_mtime)
    temp = _temp_name(dest, _BUILD_TAG)
    try:
        written = _write_ranges(temp, ranges, index.file_size, marker)
        _check_allocation(temp, written, len(ranges))
        length = int(os.stat(temp).st_size)
        if length != index.file_size + len(marker):
            raise HollowRefused(f"the grading-frame copy came out {length} bytes long where "
                                f"{index.file_size + len(marker)} were meant")
        return temp, length
    except BaseException:
        try:
            os.unlink(temp)
        except OSError:
            pass
        raise


def _ranges_for(index: BrawIndex, frames: list[int], read: ReadRange) -> list[_Range]:
    out = [_Range(0, index.head_length, read, None, "head of the clip")]
    for n in frames:
        off, length = index.frames[n]
        out.append(_Range(off, length, read, n, f"frame {n}"))
    out.append(_Range(index.moov_offset, index.moov_length, read, None, "clip's index"))
    return out


def build_hollow(dest: Any, index: BrawIndex, frames: Iterable[int], read_range: ReadRange, *,
                 nas_mtime: str = "", led: Optional[HollowLedger] = None) -> dict[str, Any]:
    """Place a NEW hollow copy at `dest`: the head, the whole first frame, each frame asked for
    and the index, from `read_range(offset, length)` (rclone in phase 3, a local file in tests).
    Written under a temporary name in the same folder, every frame checked, the marker appended,
    the ledger row written, then ONE rename into place that refuses to overwrite anything.
    -> the ledger entry. Raises HollowRefused / LayoutRefused with a sentence naming the cause."""
    dest = Path(dest)
    if os.path.lexists(dest):
        raise HollowRefused(f"something is already at {dest.name} on this computer, so no grading "
                            "frame was written over it")
    wanted = _frame_set(index, frames)
    led = led or ledger()
    temp, length = _build(dest, index, _ranges_for(index, wanted, read_range), wanted, nas_mtime)
    try:
        if not led.record(dest, length, index.file_size, nas_mtime, wanted):
            raise HollowRefused("the grading-frames ledger could not be written, so the copy was "
                                "not put in place")
        try:
            _rename_no_clobber(temp, dest)
        except OSError as exc:
            led.forget(dest)
            raise HollowRefused(f"the grading-frame copy could not be put in place ({exc}); "
                                "nothing was overwritten") from None
    except BaseException:
        try:
            os.unlink(temp)
        except OSError:
            pass
        raise
    log.info("grading frames: placed %s (%d frames, %d bytes long)", dest, len(wanted), length)
    return led.get(dest) or {}


def _local_reader(path: Path) -> tuple[ReadRange, Callable[[], None]]:
    fh = open(path, "rb")

    def read(offset: int, length: int) -> bytes:
        fh.seek(offset)
        return fh.read(length)

    return read, fh.close


def read_local_index(path: Any, real_size: int) -> BrawIndex:
    """Parse the index of a hollow copy (or any local .braw) whose original is `real_size` long."""
    read, close = _local_reader(Path(path))
    try:
        head = read(0, HEAD_BYTES)
        moov_offset, moov_length, _ = locate_index(head, real_size)
        return parse_index(head, read(moov_offset, moov_length), real_size)
    finally:
        close()


def add_frames(dest: Any, frames: Iterable[int], read_range: ReadRange, *, nas_size: int,
               nas_mtime: str = "", led: Optional[HollowLedger] = None) -> dict[str, Any]:
    """Add frames to the hollow copy at `dest` by building a NEW file and swapping it in, never
    by writing into the old one: Resolve holds the file open without write sharing, but lets it
    be renamed (doc section 2.4 rows i and j, section 3.4). The new file is the old one's filled
    ranges (head, index, the frames it holds, read locally and checked again) plus the new
    frames from `read_range`; the old one is renamed aside, the new one renamed into place, and
    the old one removed when Resolve lets go of it (here if it already has, else later through
    `sweep_asides`). -> the new ledger entry. Raises HollowRefused / LayoutRefused."""
    dest = Path(dest)
    led = led or ledger()
    doc = read_marker(dest)
    if doc is None:
        raise HollowRefused(f"{dest.name} on this computer is not a grading-frame copy that frames "
                            "can be added to")
    real_size = int(doc["real_size"])
    if int(nas_size) != real_size:
        raise HollowRefused(f"the clip on the server has changed since its grading frames were "
                            f"fetched ({nas_size} bytes now, {real_size} then)")
    index = read_local_index(dest, real_size)
    held = _frame_set(index, doc.get("frames") or [])
    wanted = _frame_set(index, list(held) + list(frames))
    old_read, close = _local_reader(dest)
    try:
        ranges = [_Range(0, index.head_length, old_read, None, "head of the clip")]
        for n in wanted:
            off, length = index.frames[n]
            source = old_read if n in held else read_range
            ranges.append(_Range(off, length, source, n, f"frame {n}"))
        ranges.append(_Range(index.moov_offset, index.moov_length, old_read, None, "clip's index"))
        temp, length = _build(dest, index, ranges, wanted, nas_mtime or str(doc.get("nas_mtime") or ""))
    finally:
        close()
    before = led.get(dest)
    old_size = int(os.stat(dest).st_size)
    aside = _temp_name(dest, _ASIDE_TAG)
    try:
        # Written down BEFORE the rename: an aside with no ledger row could never be removed
        # (one sign missing is doubt), so a ledger that will not take the row stops the swap.
        if not led.record(aside, old_size, real_size, str(doc.get("nas_mtime") or ""), held,
                          aside_of=str(dest), aside_reason=ASIDE_ADDED_FRAMES):
            raise OSError("the grading-frames ledger could not be written")
        os.rename(dest, aside)
    except OSError as exc:
        led.forget(aside)
        os.unlink(temp)
        raise HollowRefused(f"the old grading-frame copy could not be moved aside ({exc})") from None
    try:
        if not led.record(dest, length, real_size, nas_mtime or str(doc.get("nas_mtime") or ""), wanted):
            raise OSError("the grading-frames ledger could not be written")
        _rename_no_clobber(temp, dest)
    except OSError as exc:
        # Put the old copy back exactly as it was; the new one goes.
        try:
            os.unlink(temp)
        except OSError:
            pass
        try:
            _rename_no_clobber(aside, dest)
            led.forget(aside)
            led.restore(dest, before)
        except OSError:
            log.warning("grading frames: %s could not be put back at %s; it stays aside and is "
                        "still recognised by every sign", aside, dest)
        raise HollowRefused(f"the fuller grading-frame copy could not be put in place ({exc})") from None
    remove_hollow(aside, led)
    log.info("grading frames: %s now holds %d frames (was %d)", dest, len(wanted), len(held))
    return led.get(dest) or {}


def move_aside(path: Any, reason: str, led: Optional[HollowLedger] = None) -> Optional[str]:
    """Rename a hollow copy THIS FEATURE MADE (ledger or marker) out of the way of the real
    original, and carry its ledger row to the new name. -> the new path, or None when it is not
    ours or could not be moved (the reason is logged). A file only the filesystem calls hollow
    is never renamed: it is something we did not make."""
    path = Path(path)
    led = led or ledger()
    got = signs(path, marker=True)
    if not got.ours():
        log.warning("grading frames: left %s where it is: it is not a grading-frame copy this "
                    "computer can recognise as its own (%s)", path, got.describe())
        return None
    aside = _temp_name(path, _ASIDE_TAG)
    entry = got.entry if got.ledger else None
    try:
        if entry is not None:
            led.record(aside, int(entry["size"]), int(entry.get("nas_size") or 0),
                       str(entry.get("nas_mtime") or ""), entry.get("frames") or [],
                       aside_of=str(path), aside_reason=reason)
        os.rename(path, aside)
    except OSError as exc:
        led.forget(aside)
        log.warning("grading frames: could not move %s aside (%s)", path, exc)
        return None
    if entry is not None:
        led.forget(path)
    log.info("grading frames: moved the grading-frame copy %s aside to %s (%s)", path, aside.name, reason)
    return str(aside)


def restore_aside(aside: Any, home: Any = None, led: Optional[HollowLedger] = None) -> bool:
    """Put an aside copy back at the path it came from (`home`, else the row's `aside_of`), if
    that path is still empty: the real original did not arrive. True when it went back. Never
    overwrites anything. A copy with no ledger row (marker only) goes back without one."""
    led = led or ledger()
    entry = led.get(aside)
    target = home if home is not None else (entry or {}).get("aside_of")
    if not target:
        return False
    target = Path(str(target))
    try:
        _rename_no_clobber(Path(aside), target)
    except OSError:
        return False
    if entry:
        led.forget(aside)
        led.record(target, int(entry["size"]), int(entry.get("nas_size") or 0),
                   str(entry.get("nas_mtime") or ""), entry.get("frames") or [])
    log.info("grading frames: put %s back at %s", Path(aside).name, target)
    return True


def asides(reason: Optional[str] = None, led: Optional[HollowLedger] = None) -> list[dict[str, Any]]:
    """Every aside row (optionally of one reason)."""
    return [e for e in (led or ledger()).entries()
            if e.get("aside_of") and (reason is None or e.get("aside_reason") == reason)]


def sweep_asides(led: Optional[HollowLedger] = None) -> int:
    """Remove the old copies `add_frames` renamed aside once Resolve has let go of them. A row
    whose file is gone is forgotten. -> how many were removed. Never raises."""
    led = led or ledger()
    removed = 0
    try:
        for entry in asides(ASIDE_ADDED_FRAMES, led):
            path = str(entry.get("local_path") or "")
            if not os.path.lexists(path):
                led.forget(path)
                continue
            if remove_hollow(path, led)[0]:
                removed += 1
    except Exception:                                             # noqa: BLE001
        log.exception("grading frames: the aside sweep failed")
    return removed
