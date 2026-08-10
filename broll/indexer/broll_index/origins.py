"""Resolve where each clip's TRUE original lives, and record it.

Everything an editor ever touches is a proxy: the shared archive holds ~27 MB
H.264 copies and the sources stay on the archive drives. At final export the
real file has to be found again, so its location is recorded while we still
know it.

Two shares resolve differently, which is the whole reason this exists:

    source=originals   rel_path IS the original. root + rel_path, done.

    source=proxies     rel_path is the PROXY (`Day 1/A74/Proxy/x.mov`). The
                       camera original is a SEPARATE videos row, status
                       'excluded', sitting one directory up with a different
                       extension (`Day 1/A74/x.MP4`). Nothing linked the two,
                       so it was findable only by guessing at filenames.

Matching for the second case is by (directory, stem) against the excluded rows
of the same share -- never by scanning the filesystem. The rows were written by
the same scan that saw both files, so they are the authoritative record of what
sat beside what, and they keep working when the drive is unplugged.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

logger = logging.getLogger(__name__)

# Set by the scanner for the non-archived side of a source="proxies" share:
# the camera original, deliberately neither indexed nor copied to the NAS.
EXCLUDED = "excluded"


def _key(rel_path: str) -> tuple[str, str]:
    """(directory without any Proxy component, lowercased stem).

    Directory-aware on purpose: two cameras on the same shoot produce
    `Day 1/A74/x.mov` and `Day 1/Fx3/x.mov`, and matching on stem alone would
    pair a proxy with the wrong camera's original.
    """
    p = PurePosixPath(rel_path)
    parts = [x for x in p.parent.parts if x.lower() != "proxy"]
    return ("/".join(parts), p.stem.lower())


def resolve_originals(rows: list[dict], roots: dict[str, str]) -> dict[int, dict]:
    """video_id -> {path, size_bytes} for every clip whose original we can place.

    `rows` is every videos row (all statuses -- the excluded ones ARE the
    answer for proxies-shares). `roots` maps share -> filesystem root.
    """
    # Index the camera originals by (share, dir, stem).
    excluded: dict[tuple[str, str, str], dict] = {}
    for r in rows:
        if r["status"] == EXCLUDED:
            d, stem = _key(r["rel_path"])
            excluded[(r["share"], d, stem)] = r

    out: dict[int, dict] = {}
    for r in rows:
        if r["status"] == EXCLUDED:
            continue
        root = roots.get(r["share"])
        if not root:
            continue

        d, stem = _key(r["rel_path"])
        twin = excluded.get((r["share"], d, stem))
        if twin is not None:
            # A proxies-share clip: its original is the excluded row's file.
            rel, size = twin["rel_path"], twin["size_bytes"]
        else:
            # An originals-share clip: rel_path already IS the original.
            rel, size = r["rel_path"], r["size_bytes"]

        out[r["id"]] = {
            "path": str(Path(root) / rel),
            "size_bytes": size,
        }
    return out


def record_originals(storage, roots: dict[str, str], *, verify: bool = False,
                     dry_run: bool = False) -> dict:
    """Write the resolved original path onto every clip. Returns a summary.

    `verify=True` stats each path and only stamps `original_verified_at` for
    the ones that exist right now. Off by default because the archive drives
    are frequently unplugged, and "not mounted today" must never be recorded as
    "this original is gone".
    """
    rows = storage.all_videos()
    resolved = resolve_originals(rows, roots)
    now = datetime.now(timezone.utc).isoformat()

    written = verified = missing = 0
    for vid, info in resolved.items():
        fields = {"original_path": info["path"],
                  "original_size_bytes": info["size_bytes"]}
        if verify:
            if Path(info["path"]).is_file():
                fields["original_verified_at"] = now
                verified += 1
            else:
                missing += 1
        if not dry_run:
            storage.update_video(vid, **fields)
        written += 1

    return {
        "rows": len(rows),
        "resolved": written,
        "unresolved": sum(1 for r in rows if r["status"] != EXCLUDED
                          and r["id"] not in resolved),
        "verified": verified,
        "missing_on_disk": missing,
    }
