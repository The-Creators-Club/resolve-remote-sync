"""Which originals in this machine's projects have no proxy beside them?

Lane B is the only path that carries video DOWN to editors, and its include
is `**/Proxy/**` (sync/rclone_lane.build_filter_rules_down). An original with
no sibling `<dir>/Proxy/<stem>.mov|.mp4` therefore never reaches anybody else
in the fleet -- it is invisible to every machine but the one it sits on, and
until this module nothing anywhere said so. `docs/SERVER.md:193-196` has
carried an "ffmpeg fallback generator" to-do since the start; this is the
half that ANSWERS THE QUESTION. Generating the missing files is proxy_gen's
job, and it consumes what is returned here.

Pure scan logic on purpose: no threads, no ffmpeg, no imports from app/tray,
and it never raises. A directory or file that vanishes mid-walk is skipped,
exactly like manifest.scan_local_manifest -- a companion whose scan blew up
would go quiet about the one thing it exists to report.

The proxy CONVENTION (an adjacent `Proxy/` dir, same stem, .mov or .mp4)
lives in proxy_relink.py and is imported, never redeclared: two copies of it
drifting apart would mean this module counting a clip as missing while the
relinker happily attaches the proxy that is right there.

Path handling: every path here comes off an os.walk of the local tree, so it
is a real local path in this host's own spelling and plain os.path is
correct. proxy_relink's ntpath/posixpath dance exists for the canonically
spelled `P:\\...` strings Resolve stores, which never reach this module.

Added 2026-08-10 with the companion proxy generator.
"""

from __future__ import annotations

import logging
import os
import re
import time
from typing import Any, Callable, Optional

from . import fixer, manifest, proxy_relink
from .proxy_relink import PROXY_DIR_NAME, PROXY_EXTENSIONS  # noqa: F401 -- re-exported
from .sync import rclone_lane

# "ccsync.proxy_scan", NOT __name__ -- setup_logging() only attaches handlers
# to the "ccsync" logger (see shutdown_guard.py's note on the same trap).
log = logging.getLogger("ccsync.proxy_scan")

# What the generator writes. .mp4 rather than BPG's .mov because these are
# HEVC/H.264 in an mp4 container; both extensions are proxies as far as
# PROXY_EXTENSIONS and Resolve's adjacent-Proxy auto-link are concerned.
GENERATED_EXT = ".mp4"

# In-progress name for a proxy being encoded. Already excluded by every lane
# filter in both directions (rclone_lane.IN_PROGRESS_EXCLUDE_RULES, and
# server/common.py's PARTIAL_IGNORE_LINES for the .stignore builders), which
# is why the generator writes here first and os.replace()s into place.
PARTIAL_SUFFIX = ".partial"

# ffmpeg cannot decode these at all (no BRAW/REDCODE/Canon RAW decoder in any
# build we ship against), so a gap in one of them is COUNTED and reported --
# "run the Blackmagic Proxy Generator" is the only answer -- but never queued.
NEEDS_RESOLVE_EXTS = frozenset({".braw", ".r3d", ".crm"})

# 360/action-cam originals. ffmpeg can read them, but a flat 1080p proxy of a
# dual-fisheye .insv is not a usable preview of anything, and Resolve won't
# treat it as a proxy for the stitched clip either. Not counted, not queued.
SKIP_GENERATION_EXTS = frozenset({".insv", ".360"})

# Anything shot on a camera is OUR footage whatever folder it landed in --
# this beats the path tokens below, so `Downloads/A001.mxf` is own-footage
# quality (a camera original that happens to sit in a folder called
# Downloads is still a camera original).
CAMERA_EXTS = frozenset({".braw", ".mxf", ".r3d", ".crm", ".mts", ".m2ts"})

# Path tokens that mean "this is a downloaded reference clip, not our
# footage" -- those get the b-roll platform's 540p preview spec instead of
# the full own-footage quality.
YOUTUBE_MARKERS = frozenset({"youtube", "yt", "downloads"})

KIND_OWN = "own"
KIND_PREVIEW = "preview"

# generation_state() answers.
GEN_GENERATE = "generate"
GEN_NEEDS_RESOLVE = "needs_resolve"
GEN_SKIP = "skip"

# The one extension the tray names by name ("4 BRAW clips need the Blackmagic
# Proxy Generator"): it is the fleet's dominant camera format and the only
# one an editor can act on themselves.
BRAW_EXT = ".braw"

# Per-project cap on the QUEUE (the per-clip list), not on the counts --
# `missing`/`braw`/`own`/`preview` are always exact, the same split
# manifest.MAX_PER_FILE_ENTRIES makes. A first-ever scan of a base rig
# project with 4000 unproxied clips would otherwise build a list the tray and
# the reporter both have to carry, for a queue that will take days to drain.
MAX_QUEUE_PER_PROJECT = 500

# How settled a file must be before it counts. A clip still being copied in
# (or still being written by BPG) is not a gap, it is a file in flight --
# same idea as lane B's lane_b_min_age_seconds. Callers pass the configured
# proxy_gen_min_age_seconds; this is the fallback.
DEFAULT_MIN_AGE_SECONDS = 120.0

# Split on runs of non-alphanumerics: `yt-dlp`, `YouTube_Downloads`,
# `2026.08.10 youtube` all tokenize the way a human reads them.
_TOKEN_SPLIT_RE = re.compile(r"[^0-9a-z]+")


def classify_footage(path: Any) -> str:
    """KIND_OWN or KIND_PREVIEW -- which quality this clip deserves.

    Camera extension wins outright (see CAMERA_EXTS). Otherwise the path is
    split into components and each component into TOKENS, and an exact token
    match against YOUTUBE_MARKERS means preview.

    Tokenizing rather than substring-matching, because "yt" is a substring of
    `Nayth` (a real project folder in this tree) and of `Kyoto`, and every one
    of those clips would silently get 540p reference quality. Tokenizing
    rather than comparing whole components, because the folder is really
    called "YouTube Downloads" -- component equality matches neither marker.

    Ambiguous paths default to own footage: over-spending on a reference clip
    costs disk, under-spending on a shoot costs a re-encode nobody notices
    until they are cutting with it.
    """
    try:
        text = str(path or "")
        if not text:
            return KIND_OWN
        if os.path.splitext(text)[1].lower() in CAMERA_EXTS:
            return KIND_OWN
        for component in re.split(r"[\\/]+", text):
            for token in _TOKEN_SPLIT_RE.split(component.lower()):
                if token and token in YOUTUBE_MARKERS:
                    return KIND_PREVIEW
    except Exception:
        log.debug("proxy scan: could not classify %r", path, exc_info=True)
    return KIND_OWN


def generation_state(ext: Any) -> str:
    """GEN_GENERATE / GEN_NEEDS_RESOLVE / GEN_SKIP for a file extension.

    Accepts ".braw" or "braw"; anything unrecognised is generatable, because
    ffmpeg reads far more than this list enumerates and the caller has
    already filtered to rclone_lane.VIDEO_EXTS.
    """
    try:
        text = str(ext or "").strip().lower()
    except Exception:
        return GEN_GENERATE
    if not text:
        return GEN_GENERATE
    if not text.startswith("."):
        text = "." + text
    if text in SKIP_GENERATION_EXTS:
        return GEN_SKIP
    if text in NEEDS_RESOLVE_EXTS:
        return GEN_NEEDS_RESOLVE
    return GEN_GENERATE


def expected_proxies(original_path: Any, is_windows: Optional[bool] = None) -> list[str]:
    """The proxy paths that would COVER this original -- proxy_relink's list.

    A thin wrapper on purpose: one definition of the convention, so "is it
    covered?" here and "what do I attach?" there can never disagree.
    """
    return proxy_relink.expected_proxy_paths(str(original_path or ""), is_windows)


def _proxy_dir_and_stem(original_path: Any) -> tuple[str, str]:
    text = str(original_path or "")
    parent = os.path.dirname(text)
    stem = os.path.splitext(os.path.basename(text))[0]
    return os.path.join(parent, PROXY_DIR_NAME), stem


def partial_path(original_path: Any) -> str:
    """Where the generator writes while encoding: `Proxy/<stem>.mp4.partial`.

    Never the final name: lane A/B and Syncthing all exclude `*.partial`, so
    a half-written file cannot escape this machine, and a crash mid-encode
    leaves something obviously unfinished rather than a truncated proxy that
    Resolve would happily attach.
    """
    proxy_dir, stem = _proxy_dir_and_stem(original_path)
    if not stem:
        return ""
    return os.path.join(proxy_dir, stem + GENERATED_EXT + PARTIAL_SUFFIX)


def is_bpg_busy(
    original_path: Any, exists_fn: Optional[Callable[[str], bool]] = None
) -> bool:
    """Is the Blackmagic Proxy Generator writing this clip's proxy RIGHT NOW?

    While Resolve/BPG generates a proxy it writes `.<stem>.tmp` (the growing
    output) plus a 0-byte `.<stem>.lock` inside the `Proxy/` dir, and renames
    the .tmp into place on completion -- observed live 2026-08-04 on a 2.3 GB
    `.Z6B_4317-004.tmp` (rclone_lane.py:73-85, which excludes both from every
    lane for the same reason).

    A clip in that state is covered-PENDING: not missing (a proxy is minutes
    away) and never queued (two encoders writing the same stem is the
    two-writers race this whole design avoids). Never raises.
    """
    check = exists_fn if exists_fn is not None else os.path.exists
    proxy_dir, stem = _proxy_dir_and_stem(original_path)
    if not stem:
        return False
    for suffix in (".tmp", ".lock"):
        try:
            if check(os.path.join(proxy_dir, "." + stem + suffix)):
                return True
        except Exception:
            continue
    return False


def empty_gap() -> dict[str, Any]:
    """A zeroed per-project gap dict.

    `missing` is every original with no proxy, INCLUDING the needs_resolve
    ones -- they are just as invisible to the rest of the fleet, and the
    notifier's whole point is to say so. The identity that holds is
    `own + preview + needs_resolve == missing`, with `clips` (the queue) a
    capped subset of the own+preview part and `braw` a subset of
    needs_resolve. Clips BPG is mid-way through, and .insv/.360, are counted
    nowhere: neither is a gap anyone can act on.
    """
    return {
        "missing": 0,
        "braw": 0,
        "needs_resolve": 0,
        KIND_OWN: 0,
        KIND_PREVIEW: 0,
        "clips": [],
        "truncated": False,
    }


def _is_pruned_dir(name: str) -> bool:
    """Directories the walk must not descend into.

    `Proxy` at any case, or the proxies themselves would be scanned as
    originals and queue a proxy for every proxy (an .mp4 in a Proxy dir has
    no `Proxy/Proxy/<stem>.mp4` beside it, so it would look "missing"
    forever). `.ccsync-trash` is lane B's backup-dir (rclone_lane.py:66) --
    files there are already deleted as far as the tree is concerned. Dot-dirs
    cover .ccsync-trash too today, and are excluded for the same reason
    fixer.list_project_dirs:170 excludes them.
    """
    lowered = name.lower()
    return (
        lowered == PROXY_DIR_NAME.lower()
        or name == rclone_lane.TRASH_DIR_NAME
        or name.startswith(".")
    )


def _stat_exists(path: str, stat_fn: Callable[[str], Any]) -> bool:
    try:
        stat_fn(path)
        return True
    except Exception:
        return False


def scan_project(
    project_dir: Any,
    *,
    min_age_seconds: float = DEFAULT_MIN_AGE_SECONDS,
    now: Optional[float] = None,
    stat_fn: Callable[[str], Any] = os.stat,
) -> dict[str, Any]:
    """The proxy gap for ONE project dir. Never raises.

    `stat_fn` is the single injectable seam for the filesystem: it answers
    size/mtime for originals AND doubles as the existence probe for candidate
    proxies (a stat that raises is "not there"), so a test can drive the
    whole walk without a real tree.
    """
    gap = empty_gap()
    candidates: list[dict[str, Any]] = []
    try:
        try:
            stamp = time.time() if now is None else float(now)
            settle = max(0.0, float(min_age_seconds))
        except (TypeError, ValueError):
            # A hand-edited "2m" in the config must not stop the scan; the
            # default settle window is the safe answer (coerce_numeric's
            # ethos, applied where the value finally gets used).
            log.debug("proxy scan: bad min_age_seconds=%r -- using %s",
                      min_age_seconds, DEFAULT_MIN_AGE_SECONDS)
            stamp, settle = time.time(), DEFAULT_MIN_AGE_SECONDS
        cutoff = stamp - settle

        # os.walk's default onerror is None: an unreadable or vanished
        # directory ends that branch silently, which is exactly the
        # never-raise behaviour manifest.scan_local_manifest relies on.
        for dirpath, dirnames, filenames in os.walk(str(project_dir)):
            dirnames[:] = [d for d in dirnames if not _is_pruned_dir(d)]
            for filename in filenames:
                # macOS AppleDouble sidecars keep the original's extension, so
                # `._A001.mov` is a video file by every test below and would
                # queue a proxy for a 4 KB resource fork (rclone_lane.py:89-96,
                # KNOWN_BUGS 12).
                if filename.startswith("._"):
                    continue
                ext = os.path.splitext(filename)[1].lower()
                # Same definition of "a video file" as the sync lanes, for the
                # same reason manifest.py uses it: if a lane wouldn't carry it,
                # its absence downstream is not a proxy gap.
                if ext not in rclone_lane.VIDEO_EXTS:
                    continue
                state = generation_state(ext)
                if state == GEN_SKIP:
                    continue
                path = os.path.join(dirpath, filename)
                try:
                    stat = stat_fn(path)
                    size = int(stat.st_size)
                    mtime = float(stat.st_mtime)
                except Exception:
                    # Vanished between the listing and the stat, or on a share
                    # that just went away. One file, skipped.
                    continue
                if size <= 0:
                    # A 0-byte file is a placeholder or a failed copy. Nothing
                    # to encode, and reporting it would send an editor hunting
                    # for a clip that has no bytes.
                    continue
                if mtime > cutoff:
                    continue  # still settling -- a file in flight is not a gap
                if any(_stat_exists(p, stat_fn) for p in expected_proxies(path)):
                    continue
                if is_bpg_busy(path, exists_fn=lambda p: _stat_exists(p, stat_fn)):
                    continue

                gap["missing"] += 1
                if state == GEN_NEEDS_RESOLVE:
                    gap["needs_resolve"] += 1
                    if ext == BRAW_EXT:
                        gap["braw"] += 1
                    continue
                kind = classify_footage(path)
                gap[kind] += 1
                candidates.append(
                    {"path": path, "kind": kind, "size": size, "mtime": mtime}
                )

        # Newest first: the clip someone shot this morning is the one their
        # collaborators are waiting on. `path` breaks mtime ties so the queue
        # is deterministic between scans.
        candidates.sort(key=lambda clip: (-clip["mtime"], clip["path"]))
        if len(candidates) > MAX_QUEUE_PER_PROJECT:
            gap["truncated"] = True
            candidates = candidates[:MAX_QUEUE_PER_PROJECT]
        gap["clips"] = candidates
    except Exception:
        log.exception("proxy scan: %s could not be scanned", project_dir)
    return gap


def _empty_totals() -> dict[str, Any]:
    return {
        "missing": 0,
        "braw": 0,
        "needs_resolve": 0,
        KIND_OWN: 0,
        KIND_PREVIEW: 0,
        "queued": 0,
        "projects": 0,
        "dropped": 0,
        "truncated": False,
    }


def scan_missing_proxies(
    local_root: Any,
    selected_rels: Optional[set] = None,
    min_age_seconds: float = DEFAULT_MIN_AGE_SECONDS,
    max_projects: int = manifest.MAX_PROJECTS,
    now: Optional[float] = None,
    stat_fn: Callable[[str], Any] = os.stat,
) -> dict[str, Any]:
    """{"projects": {project_rel: gap}, "totals": {...}} for the whole tree.

    Project discovery is fixer.list_project_dirs (marker-based, the same set
    every other part of the companion works on) narrowed by
    manifest.prioritize_project_rels, so the selected projects and the
    most-recently-touched survive the cap -- a base rig whose local_root is
    the entire NAS tree has hundreds, and this is a SECOND full walk on top
    of the manifest's.

    Every scanned project appears in "projects", gap or no gap: "this project
    is fully covered" is an answer callers need, and telling it apart from
    "this project was capped out of the scan" matters for what the tray says.

    Never raises. A blank or missing local_root is an empty result, not an
    error -- an editor whose SSD is unplugged must not see a scan failure.
    """
    result: dict[str, Any] = {"projects": {}, "totals": _empty_totals()}
    try:
        root = str(local_root or "").strip()
        if not root:
            return result
        project_rels = fixer.list_project_dirs(root, extra_rels=selected_rels or ())
        project_rels, dropped = manifest.prioritize_project_rels(
            root, project_rels, selected_rels, max_projects
        )
        totals = result["totals"]
        totals["dropped"] = dropped
        for project_rel in project_rels:
            project_dir = os.path.join(
                root, "Projects", project_rel.replace("/", os.sep)
            )
            gap = scan_project(
                project_dir, min_age_seconds=min_age_seconds, now=now, stat_fn=stat_fn
            )
            result["projects"][project_rel] = gap
            for key in ("missing", "braw", "needs_resolve", KIND_OWN, KIND_PREVIEW):
                totals[key] += gap[key]
            totals["queued"] += len(gap["clips"])
            totals["truncated"] = totals["truncated"] or bool(gap["truncated"])
        totals["projects"] = len(result["projects"])
    except Exception:
        log.exception("proxy scan: the sweep of %r failed", local_root)
    return result
