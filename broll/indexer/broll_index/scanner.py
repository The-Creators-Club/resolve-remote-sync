"""Directory walk for `broll-index scan`.

Walks a share root, yielding video files while skipping hidden/system directories and
anything under DATA_ROOT (so the indexer never tries to index its own generated data).
"""

from __future__ import annotations

import fnmatch
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Sequence, TYPE_CHECKING

from .hashing import hash_file_partial

if TYPE_CHECKING:
    from .storage.base import Storage

VIDEO_EXTENSIONS = {".mov", ".mp4", ".mxf", ".braw", ".avi", ".mkv", ".m4v"}

# Windows file attribute bits (kernel32 FILE_ATTRIBUTE_*).
_FILE_ATTRIBUTE_HIDDEN = 0x2
_FILE_ATTRIBUTE_SYSTEM = 0x4


@dataclass(frozen=True)
class ScannedFile:
    path: Path       # absolute filesystem path
    rel_path: str    # forward-slash path relative to the share root


def is_hidden_or_system(path: Path) -> bool:
    """True for dot-prefixed names, or (on Windows) files/dirs flagged hidden/system."""
    if path.name.startswith("."):
        return True
    if os.name == "nt":
        try:
            attrs = path.stat().st_file_attributes  # type: ignore[attr-defined]
        except (AttributeError, OSError):
            return False
        if attrs & (_FILE_ATTRIBUTE_HIDDEN | _FILE_ATTRIBUTE_SYSTEM):
            return True
    return False


def _is_under(path: Path, ancestor: Path | None) -> bool:
    if ancestor is None:
        return False
    return path == ancestor or ancestor in path.parents


def is_excluded_dir(rel_dir: str, patterns: Sequence[str]) -> bool:
    """True if `rel_dir` (forward-slash, relative to the share root) is excluded.

    fnmatch semantics, so `*` crosses separators: "*/AE" matches both
    "Nuclear/AE" and "Nuclear/B-roll/AE". That is deliberate — the patterns name
    folder *kinds* ("the AE comps", "the download folders") that recur at
    varying depths, and enumerating every depth would be a list that silently
    goes stale as the project tree grows.

    Case-INSENSITIVE (BROLL-16, 2026-08-11): the shares live on NTFS and SMB,
    where `Erosion/YouTube` and `Erosion/Youtube` are the same folder. Matched
    case-sensitively, renaming one letter silently un-excluded a whole subtree
    and re-indexed it as a second copy of itself. Both sides are lowercased
    rather than using fnmatch.fnmatch, whose case-folding depends on the
    platform running the scan and not on the filesystem being scanned.
    """
    lowered = rel_dir.lower()
    return any(fnmatch.fnmatchcase(lowered, p.lower()) for p in patterns)


def scan_share(root: str | Path, data_root: str | Path | None = None,
               exclude: Sequence[str] | None = None) -> Iterator[ScannedFile]:
    """Walk `root`, yielding every video file not hidden/system and not under `data_root`.

    `exclude` prunes directories by pattern (see is_excluded_dir). Pruning happens
    during the walk rather than filtering the yielded files, so an excluded
    subtree is never descended into at all — on a share rooted at a whole project
    over the NAS that is the difference between statting a few thousand files and
    a few tens of thousands.
    """
    root = Path(root).resolve()
    data_root_resolved = Path(data_root).resolve() if data_root else None
    patterns = list(exclude or ())

    for dirpath, dirnames, filenames in os.walk(root):
        current = Path(dirpath)

        if _is_under(current, data_root_resolved):
            dirnames[:] = []
            continue

        keep = []
        for d in dirnames:
            child = current / d
            if is_hidden_or_system(child):
                continue
            if data_root_resolved is not None and child.resolve() == data_root_resolved:
                continue
            if patterns and is_excluded_dir(child.relative_to(root).as_posix(), patterns):
                continue
            keep.append(d)
        dirnames[:] = keep

        for fname in filenames:
            fpath = current / fname
            if is_hidden_or_system(fpath):
                continue
            if fpath.suffix.lower() not in VIDEO_EXTENSIONS:
                continue
            yield ScannedFile(path=fpath, rel_path=fpath.relative_to(root).as_posix())


def _path_is_in_inbox(path: Path, inbox_root: Path | None) -> bool:
    if inbox_root is None:
        return False
    resolved = path.resolve()
    return resolved == inbox_root or inbox_root in resolved.parents


# Folders holding an editor's own conform/offline proxies of footage that is also
# present as originals. Measured on the real archive: 2,100 of 4,482 scanned files
# (660 GB) sat under these, and 1,958 had the original beside them — indexing both
# means paying twice to describe one clip and returning two hits for it. Content
# hashing cannot catch them: same footage, different encode, different bytes.
#
# They are recorded with status='skipped' rather than not scanned at all, because
# they still belong in the copy manifest (they are usually still linked inside
# existing Resolve projects, and dropping them would break those on relink).
PROXY_DIR_RE = re.compile(
    r"(^|/)(proxy|proxies|optimized|optimised|transcode|transcodes|transcoded|lowres|low_res)(/|$)",
    re.IGNORECASE,
)


def is_editor_proxy_path(rel_path: str) -> bool:
    return bool(PROXY_DIR_RE.search(rel_path))


def initial_status(rel_path: str, source: str = "originals") -> str:
    """The status a newly-seen file gets, per its share's `source` mode.

    source="originals" — the archive copy is the file itself; a Proxy/ folder
    beside it is the editor's redundant second encode. Proxy -> 'skipped':
    not worth indexing, but still copied (existing Resolve projects link to it,
    so dropping it would break them on relink).

    source="proxies" — our own shot footage. Now the Proxy/ .mov is the archive
    copy and the camera original is the redundant one: 20x the bytes, staying on
    the shoot drive, never going to the server. So the verdicts swap, and the
    original gets 'excluded' rather than 'skipped' — 'skipped' would still put
    all 403 GB of them in the copy manifest, which is the exact opposite of the
    point. 'excluded' means: not indexed AND not copied, but still recorded, so
    there is a durable record of which original each proxy came from if a finish
    ever needs to relink to camera media.
    """
    if source == "proxies":
        return "discovered" if is_editor_proxy_path(rel_path) else "excluded"
    return "skipped" if is_editor_proxy_path(rel_path) else "discovered"


def do_scan(
    storage: "Storage",
    share: str,
    root: str | Path,
    data_root: str | Path | None = None,
    inbox: str | None = None,
    skip_editor_proxies: bool = True,
    source: str = "originals",
    exclude: Sequence[str] | None = None,
    rehash: bool = False,
) -> int:
    """Walk `root`, upserting a `videos` row (status=discovered on first sight) per file.

    Rescanning an already-processed video only refreshes hash/size_bytes/in_inbox — it
    never resets `status` back to discovered, since SPEC.md doesn't call for re-indexing
    unchanged files and doing so would silently undo completed work on every rescan.

    A file already on the index whose size is unchanged keeps its stored hash rather
    than being read again (BROLL-IDX-6, 2026-08-14). hash_file_partial reads 8 MiB of
    head and 8 MiB of tail, and the shares are 25 NETWORK roots — so a rescan to pick
    up a handful of new downloads was pulling ~16 MiB per already-known file over the
    wire (~70 GB, ~25 min at the measured 46 MB/s, on one 4,482-file share) to
    recompute a digest that cannot have changed unless the file did. `rehash=True`
    restores the unconditional read for the one case size cannot see: an in-place edit
    that kept the byte count.

    `source` selects which side of a proxy/original pair is the archive copy — see
    initial_status(). `skip_editor_proxies=False` overrides it to take everything
    as-is (status='discovered'), for callers that want the raw tree with no
    proxy/original judgement applied.

    `exclude` prunes directories before they are walked (see is_excluded_dir).
    Note it only governs what a scan ADDS: rows written by an earlier scan of the
    same share stay exactly as they are, since do_scan never revisits a path it
    did not just see. Widening the exclude list therefore needs the now-excluded
    rows deleted by hand.
    """
    root = Path(root)
    inbox_root = (root / inbox).resolve() if inbox else None

    count = 0
    for sf in scan_share(root, data_root, exclude=exclude):
        size = sf.path.stat().st_size
        in_inbox = 1 if _path_is_in_inbox(sf.path, inbox_root) else 0

        # Looked up BEFORE hashing, which is the whole point: the row already
        # carries the digest, and the stat() above is the cheap discriminator.
        existing = storage.get_video_by_path(share, sf.rel_path)
        reusable = bool(
            not rehash
            and existing is not None
            and existing.get("hash")
            and existing.get("size_bytes") == size
        )
        digest = existing["hash"] if reusable else hash_file_partial(sf.path)

        fields: dict = {"hash": digest, "size_bytes": size, "in_inbox": in_inbox}
        if existing is None:
            fields["status"] = (
                initial_status(sf.rel_path, source) if skip_editor_proxies else "discovered"
            )

        storage.upsert_video(share, sf.rel_path, **fields)
        count += 1

    return count
