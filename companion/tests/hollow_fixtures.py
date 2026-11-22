"""Synthetic Blackmagic RAW files and planted hollow copies, for the grading-frames tests.

docs/GRADING_FRAMES.md section 7: phase 1 is "fully unit-tested against fixture files built in the
test (no camera footage in the repo)". A file here has the shape the 2026-11-22 sweep found on all
157 clips: `wide`, `mdat` (a timecode sample, then one frame per chunk, each starting
`00 00 04 00 'bmdf'`, with sound chunks between them), then `moov` LAST, with `co64` offsets,
`stsz` sizes, `stsc` one sample per chunk and no `stss`. Knobs bend it into every shape the parser
must refuse. Not a test module: the reader tests in test_manifest.py, test_rclone_lane.py and the
others import it to plant a hollow copy.
"""

from __future__ import annotations

import os
import struct
from pathlib import Path
from typing import Optional

import pytest

from ccsync_companion import hollow

FRAME_LEN = 256 * 1024
N_FRAMES = 40


def box(kind: bytes, body: bytes) -> bytes:
    return struct.pack(">I4s", 8 + len(body), kind) + body


def full(kind: bytes, body: bytes) -> bytes:
    """A FullBox: version 0, flags 0."""
    return box(kind, b"\0\0\0\0" + body)


def _trak(handler: bytes, codec: bytes, sizes: list[int], offsets: list[int], *, per_chunk: int = 1,
          co64: bool = True, stss: bool = False, ctts: bool = False, offsets_table: bool = True,
          terminator: bool = False) -> bytes:
    hdlr = full(b"hdlr", b"\0\0\0\0" + handler + b"\0" * 12 + b"\0")
    stsd = full(b"stsd", struct.pack(">I", 1) + struct.pack(">I4s", 16, codec) + b"\0" * 8)
    stts = full(b"stts", struct.pack(">III", 1, len(sizes), 1))
    stsc = full(b"stsc", struct.pack(">I", 1) + struct.pack(">III", 1, per_chunk, 1))
    stsz = full(b"stsz", struct.pack(">II", 0, len(sizes)) + b"".join(struct.pack(">I", s) for s in sizes))
    tables = stsd + stts + stsc + stsz
    if offsets_table:
        if co64:
            tables += full(b"co64", struct.pack(">I", len(offsets))
                           + b"".join(struct.pack(">Q", o) for o in offsets))
        else:
            tables += full(b"stco", struct.pack(">I", len(offsets))
                           + b"".join(struct.pack(">I", o) for o in offsets))
    if stss:
        tables += full(b"stss", struct.pack(">II", 1, 1))
    if ctts:
        tables += full(b"ctts", struct.pack(">III", 1, len(sizes), 0))
    # QuickTime allows a container to end in a 32-bit zero terminator.
    minf = box(b"minf", box(b"stbl", tables + (b"\0" * 4 if terminator else b"")))
    mdia = box(b"mdia", full(b"mdhd", b"\0" * 20) + hdlr + minf)
    return box(b"trak", full(b"tkhd", b"\0" * 80) + mdia)


def frame_bytes(n: int, length: int = FRAME_LEN) -> bytes:
    """Frame n: the BRAW magic, then a pattern that differs per frame (so a frame read from the
    wrong offset is caught) and is never all zeros (so a hole is never mistaken for a frame)."""
    seed = bytes((n * 7 + i) % 251 + 1 for i in range(251))
    body = (seed * (length // len(seed) + 1))[:length - len(hollow.FRAME_MAGIC)]
    return hollow.FRAME_MAGIC + body


def make_braw(*, n_frames: int = N_FRAMES, frame_len: int = FRAME_LEN, large_mdat: bool = True,
              co64: bool = True, per_chunk: int = 1, stss: bool = False, ctts: bool = False,
              codec: bytes = b"brlt", moov_first: bool = False, trailing: bytes = b"",
              first_frame_at: int = 4100, offsets_table: bool = True, two_video: bool = False,
              audio_every: int = 10, terminator: bool = False) -> tuple[bytes, list[tuple[int, int]]]:
    """-> (the file's bytes, [(offset, length)] per frame)."""
    head = box(b"wide", b"")
    mdat_header = 16 if large_mdat else 8
    body_start = len(head) + mdat_header
    pad = first_frame_at - body_start
    assert pad >= 4, "the timecode sample needs room before the first frame"
    body = bytearray(b"\0\0\0\x01" + b"\x11" * (pad - 4))       # timecode sample + metadata
    frames: list[tuple[int, int]] = []
    audio_sizes: list[int] = []
    audio_offsets: list[int] = []
    for n in range(n_frames):
        frames.append((body_start + len(body), frame_len))
        body += frame_bytes(n, frame_len)
        if audio_every and n % audio_every == audio_every - 1:
            audio_offsets.append(body_start + len(body))
            audio_sizes.append(4096)
            body += b"\x22" * 4096
    if large_mdat:
        mdat = struct.pack(">I4sQ", 1, b"mdat", 16 + len(body)) + bytes(body)
    else:
        mdat = box(b"mdat", bytes(body))

    def build_moov(shift: int) -> bytes:
        offs = [o + shift for o, _ in frames]
        traks = _trak(b"vide", codec, [ln for _, ln in frames], offs, per_chunk=per_chunk,
                      co64=co64, stss=stss, ctts=ctts, offsets_table=offsets_table,
                      terminator=terminator)
        if two_video:
            traks += _trak(b"vide", codec, [ln for _, ln in frames], offs)
        if audio_sizes:
            traks += _trak(b"soun", b"lpcm", audio_sizes, [o + shift for o in audio_offsets],
                           co64=co64)
        return box(b"moov", full(b"mvhd", b"\0" * 96) + traks)

    if moov_first:
        moov = build_moov(0)
        moov = build_moov(len(moov))
        data = head + moov + mdat
        frames = [(o + len(moov), ln) for o, ln in frames]
    else:
        data = head + mdat + build_moov(0) + trailing
    return data, frames


def write_braw(path: Path, **kwargs) -> tuple[Path, list[tuple[int, int]]]:
    data, frames = make_braw(**kwargs)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path, frames


def reader_of(path: Path):
    """A `read_range` over a local file, as phase 3's rclone reader will be over the NAS."""
    def read(offset: int, length: int) -> bytes:
        with open(path, "rb") as fh:
            fh.seek(offset)
            return fh.read(length)
    return read


def index_of(path: Path) -> hollow.BrawIndex:
    data = path.read_bytes()
    head = data[:hollow.HEAD_BYTES]
    off, length, _ = hollow.locate_index(head, len(data))
    return hollow.parse_index(head, data[off:off + length], len(data))


# The fixtures are ~10 MB clips whose holes are a few MB each, and plant_holes_only's is 8 MiB.
HOLE_PROBE_BYTES = 4 << 20
_hole_probe: dict[str, tuple[int, int]] = {}


def measure_hole(folder: Path, hole: int = HOLE_PROBE_BYTES) -> tuple[int, int]:
    """Write 4 KB, leave `hole` bytes unwritten, write one more byte, exactly as the writer does
    (sparse flag first on Windows, seek, write). -> (length, bytes on the disk)."""
    probe = Path(folder) / f".hole-probe-{os.getpid()}-{hole}{hollow.TEMP_SUFFIX}"
    try:
        with open(probe, "xb") as fh:
            hollow._set_sparse(fh)
            fh.write(b"\x01" * 4096)
            fh.seek(4096 + hole)
            fh.write(b"\x01")
            fh.flush()
            os.fsync(fh.fileno())
        st = os.stat(probe)
        allocated = hollow.allocated_bytes(probe, st)
        return int(st.st_size), int(st.st_size if allocated is None else allocated)
    finally:
        try:
            os.unlink(probe)
        except OSError:
            pass


def need_sparse(folder: Path) -> None:
    """Skip LOUDLY where this folder cannot hold the fixtures' sparse files: the reason names
    the filesystem, so a run that skipped the writer's tests says so in its summary (`-rs`).

    MEASURED, not read off the filesystem's name (2026-11-22). The first CI run on a Mac had
    `can_hold_sparse` answer yes for APFS by name, and the runner then left every fixture fully
    allocated: nine tests failed on a property of the runner's disk. A 4 MiB hole is written here
    the way the writer writes one, and the tests run only where it stays empty."""
    # The nearest folder that exists: a test names where its hollow copy WILL go.
    folder = Path(folder)
    while not folder.exists() and folder.parent != folder:
        folder = folder.parent
    able, name = hollow.can_hold_sparse(folder)
    label = name or "a filesystem this machine could not name"
    if not able:
        pytest.skip(f"SPARSE FILES UNAVAILABLE HERE: {folder} is on {label}, which "
                    f"{'cannot' if able is False else 'could not be shown to'} hold sparse files, "
                    "so the hollow-copy writer is NOT TESTED on this machine")
    key = hollow.filesystem_name(folder) + "|" + str(Path(folder).anchor)
    if key not in _hole_probe:
        try:
            _hole_probe[key] = measure_hole(Path(folder))
        except OSError as exc:
            pytest.skip(f"SPARSE FILES UNAVAILABLE HERE: {folder} ({label}) could not be probed "
                        f"({exc}), so the hollow-copy writer is NOT TESTED on this machine")
    length, allocated = _hole_probe[key]
    if allocated >= length * hollow.SPARSE_ALLOCATED_FRACTION:
        pytest.skip(f"SPARSE FILES UNAVAILABLE HERE: {folder} is on {label}, which did NOT keep a "
                    f"{HOLE_PROBE_BYTES >> 20} MiB hole empty ({allocated} bytes on the disk for a "
                    f"file of {length}), so the hollow-copy writer is NOT TESTED on this machine")


def plant_hollow(dest: Path, *, source_dir: Optional[Path] = None, frames=(20,), led=None,
                 **kwargs) -> tuple[Path, Path]:
    """A real hollow copy at `dest`, built by the module's own writer from a synthetic original
    kept OUTSIDE the tree (the NAS's copy, as it were). -> (dest, the original). Skips loudly where
    the folder cannot hold sparse files."""
    need_sparse(dest.parent if dest.parent.exists() else dest.parent.parent)
    dest.parent.mkdir(parents=True, exist_ok=True)
    src_dir = source_dir or (dest.parent.parent / "_nas_side")
    original, _ = write_braw(src_dir / dest.name, **kwargs)
    hollow.build_hollow(dest, index_of(original), frames, reader_of(original), led=led)
    return dest, original


def plant_holes_only(path: Path, size: int = 8 << 20) -> Path:
    """A file the filesystem calls mostly holes, with NO marker and NO ledger row: the shape of a
    cloud-drive placeholder, or of something CC Sync did not make (trap 2)."""
    need_sparse(path.parent)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "xb") as fh:
        hollow._set_sparse(fh)
        fh.write(b"\x01" * 4096)
        fh.seek(size - 1)
        fh.write(b"\x01")
    return path


def plant_sparse_but_whole(path: Path, size: int = 8 << 20) -> Path:
    """Trap 1: a file marked sparse with EVERY byte written, as rclone's multi-thread downloads
    leave a whole original on Windows."""
    path.parent.mkdir(parents=True, exist_ok=True)
    need_sparse(path.parent)
    with open(path, "xb") as fh:
        hollow._set_sparse(fh)
        chunk = os.urandom(1 << 20)
        left = size
        while left:
            step = min(left, len(chunk))
            fh.write(chunk[:step])
            left -= step
    return path
