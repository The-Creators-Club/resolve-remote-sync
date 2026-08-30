"""Regenerate the fixture icons beside this file (MOBILE_PLAN.md §4 M5, 2026-08-30).

The CI workflow serves `tools/android/fixture/` with `python -m http.server`
and points Bubblewrap at the manifest in it. Bubblewrap DOWNLOADS the icons
the manifest names and refuses a build without a 512x512 one, so the fixture
has to carry real PNG bytes -- it cannot borrow `static/icons/*` (M4's, and
not on this branch) and there is no PIL in any venv here.

So: stdlib only, `zlib` plus the PNG chunk format. Flat panel black, the same
`#0a0a0d` the manifest declares. Nobody ever looks at these; they exist so the
BUILD is proven end to end on CI, which is the one step nobody here has run.

    python tools/android/fixture/make_fixture_icons.py
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
RGB = (0x0A, 0x0A, 0x0D)


def _chunk(kind: bytes, data: bytes) -> bytes:
    return (struct.pack(">I", len(data)) + kind + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))


def png(size: int, rgb: tuple[int, int, int] = RGB) -> bytes:
    row = b"\x00" + bytes(rgb) * size          # filter byte 0, then the pixels
    raw = row * size
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
        + _chunk(b"IDAT", zlib.compress(raw, 9))
        + _chunk(b"IEND", b"")
    )


def main() -> int:
    for name, size in (("icon-192.png", 192), ("icon-512.png", 512),
                       ("icon-512-maskable.png", 512)):
        path = HERE / name
        path.write_bytes(png(size))
        print(f"wrote {path} ({path.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
