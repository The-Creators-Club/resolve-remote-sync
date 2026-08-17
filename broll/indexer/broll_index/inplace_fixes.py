"""Remember which archive files were repaired IN PLACE, so nothing undoes them.

WHY (COMMERCIAL_READINESS.md item 9, 2026-08-17). Two scripts write into the
same archive tree with opposite beliefs about what a file should be:

  - `fix_10bit_proxies.py --apply` re-encodes a browser-hostile preview and
    `os.replace`s the 8-bit result over it (KNOWN_BUGS R9). The fixed file is
    a DIFFERENT SIZE from the one build_archive placed.
  - `build_archive.py --apply` decided what still needed copying by comparing
    `dst.stat().st_size != src.stat().st_size`. Every repaired preview
    therefore looked "not yet copied", and the next build silently copied the
    10-bit original back over it -- undoing the repair on every clip, with no
    output saying so.

Size is not identity. This module is the shared record of "this file is
deliberately not a byte-copy of its source", plus the trash that makes any
overwrite reversible.

The manifest lives at the archive root (`.ccsync-inplace-fixes.json`) so it
travels with the tree, and is keyed by POSIX relative path so a manifest
written on Windows is readable on the NAS.

Nothing here raises on I/O: a missing or corrupt manifest degrades to "no
file is known-fixed", which is the pre-2026-08-17 behaviour.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from pathlib import Path
from typing import Any, Optional

MANIFEST_NAME = ".ccsync-inplace-fixes.json"

# Where a replaced file goes instead of being destroyed. A sibling of the
# archive root's contents, and never swept automatically: the operator
# deletes it once they are satisfied, which is the only person who can know.
TRASH_DIRNAME = ".ccsync-replaced"

# Head and tail bytes fed to the digest alongside the size. A full hash of a
# 60 GB archive is hours of I/O for a check that runs before every copy; head
# + tail + size distinguishes a re-encode from its source with certainty (a
# transcode changes the first frame's bytes and the container's trailer) and
# is two seeks per file.
HASH_WINDOW = 1024 * 1024


def quick_hash(path: Any, window: int = HASH_WINDOW) -> str:
    """sha256 of (size, first `window` bytes, last `window` bytes). "" on error.

    NOT a content hash and deliberately not called one -- it answers "is this
    the same file I looked at before?", which is the only question the two
    callers ask.
    """
    try:
        p = Path(path)
        size = p.stat().st_size
        digest = hashlib.sha256(str(size).encode("ascii"))
        with open(p, "rb") as fh:
            digest.update(fh.read(window))
            if size > window * 2:
                fh.seek(-window, os.SEEK_END)
                digest.update(fh.read(window))
        return digest.hexdigest()
    except Exception:
        return ""


def manifest_path(root: Any) -> Path:
    return Path(root) / MANIFEST_NAME


def load(root: Any) -> dict[str, Any]:
    """The manifest as {rel posix path: entry}. `{}` when there is none."""
    try:
        with open(manifest_path(root), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        files = data.get("files") if isinstance(data, dict) else None
        return files if isinstance(files, dict) else {}
    except Exception:
        return {}


def _rel(root: Any, path: Any) -> str:
    try:
        return Path(path).resolve().relative_to(Path(root).resolve()).as_posix()
    except Exception:
        return Path(path).name


def record(root: Any, path: Any, *, note: str = "", by: str = "") -> None:
    """Note that `path` under `root` is a deliberate in-place repair.

    Written through tmp+replace: two `--apply` workers finish at the same
    moment and a half-written manifest is one that reads as empty, which
    would let the next build_archive undo everything in it.
    """
    try:
        target = manifest_path(root)
        files = load(root)
        files[_rel(root, path)] = {
            "hash": quick_hash(path),
            "size": Path(path).stat().st_size,
            "fixed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "by": by or "fix_10bit_proxies.py",
            "note": note,
        }
        tmp = target.with_name(target.name + ".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"files": files}, fh, indent=1, sort_keys=True)
        os.replace(tmp, target)
    except Exception:
        # A repair that cannot be recorded is still a repair. The caller
        # prints its own failures; losing the note costs a future re-copy,
        # not the file.
        pass


def is_fixed(root: Any, path: Any, files: Optional[dict[str, Any]] = None) -> bool:
    """Is `path` a recorded repair that is STILL the file we recorded?

    The hash re-check is the point: a stale manifest entry for a file that
    has since been replaced by something else must not protect it forever.
    """
    entry = (files if files is not None else load(root)).get(_rel(root, path))
    if not isinstance(entry, dict):
        return False
    recorded = str(entry.get("hash") or "")
    if not recorded:
        return False
    return recorded == quick_hash(path)


def stash(root: Any, path: Any) -> Optional[Path]:
    """Move `path` into the archive's trash before it is overwritten.

    Returns where it went, or None when there was nothing there. Raises
    nothing the caller cannot see: an OSError here means the overwrite must
    NOT proceed, so it is deliberately allowed to propagate.
    """
    source = Path(path)
    if not source.exists():
        return None
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    target = Path(root) / TRASH_DIRNAME / stamp / _rel(root, path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target = target.with_name(f"{target.stem}-{int(time.time())}{target.suffix}")
    shutil.move(str(source), str(target))
    return target
