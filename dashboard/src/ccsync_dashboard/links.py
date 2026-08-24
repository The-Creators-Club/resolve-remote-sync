"""Cross-project folder links (docs/SHARED_FOLDERS_PLAN.md, 2026-08-23).

A project's `.ccsync-project` marker may carry an `includes` list declaring
that this project BORROWS a folder that lives inside ANOTHER project. The
borrowed folder is synced to any machine that ticked the borrower, at its one
true path under the lender -- no second copy, no symlink, no relink in
Resolve (decision D2).

The marker is a plain JSON file on a share every editor can write, so
nothing in it is trusted: this module re-derives everything and refuses
anything it cannot prove, exactly the posture read_marker takes with the
slug. Only `ok` rows ever reach a companion (D5).

These are pure functions over the mounted tree (filesystem reads via
provision, no DB, no HTTP) so test_links.py can drive every refusal against
tmp_path. The lender's ACTIVITY (projects row, active flag) is DB state and
is judged by the collector's _run_links, which also owns the stale-path
fallback for a lender that moved on the NAS.

Deliberately not importing api._validate_tree_part despite the shared rules:
api.py will import this module for the authoring endpoint (WP5), so the
segment validator lives here and api's stays where its 422 mapping is.
"""
from __future__ import annotations

import logging
import os
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from . import provision

log = logging.getLogger("ccsync.links")

# TREE_LAYOUT_PLAN WP2 will replace this literal with layout().projects_dir;
# until then the tree's projects dir is the one name every marker, label and
# lane already assumes.
PROJECTS_SEGMENT = "Projects"

# Hard cap per marker: the selection response and the companion's per-include
# lane runs are both O(includes), and a tampered marker must not be able to
# make either unbounded.
MAX_INCLUDES = 32

STATUS_OK = "ok"
STATUS_MISSING = "missing"
STATUS_INVALID = "invalid"
STATUS_LENDER_INACTIVE = "lender-inactive"


@dataclass(frozen=True)
class LinkResult:
    """One resolved `includes` entry.

    `declared` is the normalised path as written in the marker (leading
    `Projects/` kept -- it is the row key and what the UI echoes back).
    `lender_rel` / `sub_rel` are tree-relative WITHOUT the projects segment,
    matching the `rel_path` spelling of the selection API. They are set for
    `ok` and `missing` (a missing folder still names who would lend it);
    `lender_slug` comes from the lender's own marker.
    """
    declared: str
    status: str
    lender_rel: str | None = None
    sub_rel: str | None = None
    lender_slug: str | None = None
    detail: str = ""


def normalise_declared(value: str) -> str:
    """The one spelling a declared path is compared and stored in: posix
    separators, NFC (the NAS, Windows and macOS all serve these names in
    NFC; an NFD spelling from a Mac zip would otherwise never match),
    no surrounding whitespace, no trailing slash."""
    text = unicodedata.normalize("NFC", str(value or ""))
    return text.replace("\\", "/").strip().rstrip("/")


def _segment_error(seg: str) -> str | None:
    if not seg or seg in (".", ".."):
        return "empty or dot path segment"
    if seg.startswith("."):
        return f"segment {seg!r} starts with '.'"
    if any(ord(ch) < 32 for ch in seg):
        return "control character in path"
    if ":" in seg:
        return f"segment {seg!r} contains ':' (declare a tree-relative path, not a drive path)"
    if len(seg.encode("utf-8")) > 255:
        return "path segment over 255 bytes"
    return None


def parse_includes(raw: object) -> tuple[list[str], int]:
    """Path strings out of a marker's raw `includes` value, in order.

    Entries may be bare strings or objects with a str `path` (§2.1). The
    second element counts entries that carried no usable path at all --
    they cannot become rows (the declared path IS the row key), so the
    caller logs them and moves on. A non-list `includes` counts as one bad.
    """
    if raw is None:
        return [], 0
    if not isinstance(raw, list):
        return [], 1
    paths: list[str] = []
    bad = 0
    for entry in raw:
        if isinstance(entry, str):
            paths.append(entry)
        elif isinstance(entry, dict) and isinstance(entry.get("path"), str):
            paths.append(entry["path"])
        else:
            bad += 1
    return paths, bad


def resolve_include(projects_dir: Path, borrower_rel: str, include_path: str) -> LinkResult:
    """Validate ONE declared path against the mounted tree (§2.2 steps 2-7).

    `borrower_rel` is the borrowing project's rel (no Projects/ prefix).
    Never raises; every refusal is a LinkResult the UI can show verbatim.
    """
    declared = normalise_declared(include_path)

    def bad(detail: str) -> LinkResult:
        return LinkResult(declared=declared, status=STATUS_INVALID, detail=detail)

    if not declared:
        return bad("empty path")
    if declared.startswith("/"):
        return bad("absolute paths cannot be shared; declare a tree-relative Projects/ path")
    parts = declared.split("/")
    for seg in parts:
        err = _segment_error(seg)
        if err:
            return bad(err)
    if parts[0] != PROJECTS_SEGMENT:
        return bad(f"only folders inside a project can be shared "
                   f"(the path must start with {PROJECTS_SEGMENT}/)")
    if len(parts) < 3:
        return bad("that is a whole project; tick both projects instead")
    # Lane A's '- **/Proxy/**' exclusion is relative to each run's root, so a
    # run rooted inside Proxy/ would upload proxies as originals (§2.2 step 5).
    if any(seg.lower() == "proxy" for seg in parts):
        return bad("cannot share a Proxy folder; share its parent instead")

    rel = "/".join(parts[1:])
    anc = provision.marked_ancestor(projects_dir, rel, include_self=True)
    if anc is None:
        return bad("not inside a project")
    if anc == rel:
        return bad("that is a whole project; tick both projects instead")
    lender_rel = anc
    sub_rel = rel[len(lender_rel) + 1:]
    if lender_rel == normalise_declared(borrower_rel):
        return bad("that folder is inside this project already")
    lender_slug = provision.read_marker(Path(projects_dir) / lender_rel)
    if lender_slug is None:
        # marked_ancestor saw a valid marker moments ago; a race with a
        # marker rewrite lands here. Next cycle settles it.
        return bad("the lending project's marker is unreadable")

    target = Path(projects_dir) / rel
    below = provision.marked_descendants(target)
    if below:
        return bad(f"contains a project ({below[0]})")

    common = LinkResult(declared=declared, status=STATUS_OK, lender_rel=lender_rel,
                        sub_rel=sub_rel, lender_slug=lender_slug)
    if not target.is_dir():
        return LinkResult(declared=declared, status=STATUS_MISSING, lender_rel=lender_rel,
                          sub_rel=sub_rel, lender_slug=lender_slug,
                          detail="folder not found on the server")
    try:
        real = Path(os.path.realpath(target))
        root = Path(os.path.realpath(projects_dir))
        if not real.is_relative_to(root):
            return bad("path escapes the Projects tree")
    except OSError:
        return LinkResult(declared=declared, status=STATUS_MISSING, lender_rel=lender_rel,
                          sub_rel=sub_rel, lender_slug=lender_slug,
                          detail="folder could not be read on the server")
    return common


def resolve_marker_includes(projects_dir: Path, borrower_rel: str,
                            raw: object) -> list[LinkResult]:
    """Every row the collector should hold for one borrower's marker: parse,
    cap, dedupe (equal or nested declared paths within one marker collapse
    to the outermost/first, §2.2 step 9), then resolve each survivor."""
    paths, unusable = parse_includes(raw)
    if unusable:
        log.warning("marker of %s: %d includes entr%s carried no usable path and were "
                    "skipped", borrower_rel, unusable, "y" if unusable == 1 else "ies")

    # Normalise + dedupe first, order-independently: an include equal to or
    # BELOW another of the same marker is a duplicate whichever was written
    # first -- the outermost declaration covers it (§2.2 step 9).
    ordered: list[str] = []
    for path in paths:
        declared = normalise_declared(path)
        if declared in ordered:
            log.info("marker of %s: duplicate include %s dropped", borrower_rel, declared)
            continue
        ordered.append(declared)
    kept: list[str] = []
    for declared in ordered:
        outer = next((o for o in ordered if o != declared and declared.startswith(o + "/")),
                     None)
        if outer is not None:
            log.info("marker of %s: include %s is inside %s -- dropped as duplicate",
                     borrower_rel, declared, outer)
            continue
        kept.append(declared)

    results: list[LinkResult] = []
    for i, declared in enumerate(kept):
        if i >= MAX_INCLUDES:
            results.append(LinkResult(declared=declared, status=STATUS_INVALID,
                                      detail=f"too many includes (limit {MAX_INCLUDES})"))
            continue
        results.append(resolve_include(projects_dir, borrower_rel, declared))
    return results
