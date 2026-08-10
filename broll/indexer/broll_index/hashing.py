"""Fast partial-file hashing used by `scan` to fingerprint videos without reading them whole,
plus the whole-file hash used by `duplicates` to CONFIRM a partial-hash match.

Per schema.sql: hash = xxh64(first 8MiB + last 8MiB + size).

`hash_file_partial` is cheap enough to run over an entire archive but can, in principle,
collide for two distinct files sharing head, tail and size — see broll_index/duplicates.py's
module docstring for why that is treated as a correctness issue, not a curiosity, and why
`hash_file_full` (this module's whole-file digest) exists to confirm it before anything is
ever marked a duplicate.
"""

from __future__ import annotations

from pathlib import Path

import xxhash

CHUNK_SIZE = 8 * 1024 * 1024  # 8 MiB


def hash_file_partial(path: str | Path) -> str:
    path = Path(path)
    size = path.stat().st_size
    h = xxhash.xxh64()
    with open(path, "rb") as f:
        head = f.read(min(CHUNK_SIZE, size))
        h.update(head)
        if size > CHUNK_SIZE:
            f.seek(max(size - CHUNK_SIZE, 0))
            tail = f.read(CHUNK_SIZE)
            h.update(tail)
    h.update(str(size).encode("utf-8"))
    return h.hexdigest()


def hash_file_full(path: str | Path) -> str:
    """Whole-file xxh64, streamed in CHUNK_SIZE reads so a 40 GB master is never loaded
    into memory at once. This is the only thing that actually CONFIRMS two files are
    byte-identical — see the module docstring and broll_index/duplicates.py."""
    path = Path(path)
    h = xxhash.xxh64()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(CHUNK_SIZE)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()
