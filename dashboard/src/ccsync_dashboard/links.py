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

# ...and a cap on the ENTRIES considered, not just the rows produced
# (dash-db-3 / regression-22, 2026-09-11). The row cap bounded the table and
# left the WORK unbounded: both dedupe passes below ran over every declared
# entry first, `declared in ordered` being a list scan and the nesting check a
# scan inside a scan, so a 20,000-entry marker (about 700 KB, and every editor
# can write the share) cost 23 s of CPU inside the collector's guarded loop on
# EVERY provision cycle, holding its connection. Four times the row cap is
# deliberately generous: nothing legitimate comes near it, and the entries past
# it are dropped unread: at most MAX_INCLUDES rows can survive anyway, and a
# marker that needs more than four times the cap to name its first 32 distinct
# folders is not one an editor wrote by hand.
MAX_INCLUDE_ENTRIES = MAX_INCLUDES * 4

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

    # dash-db-3 (2026-09-11): bound the WORK before the two dedupe passes, not
    # only the rows after them. `declared_total` is kept so the refusal below
    # still names how many the marker really declared.
    declared_total = len(paths)
    if declared_total > MAX_INCLUDE_ENTRIES:
        log.warning("marker of %s: %d includes entries is past the %d this reads at all; "
                    "the rest were dropped unread",
                    borrower_rel, declared_total, MAX_INCLUDE_ENTRIES)
        paths = paths[:MAX_INCLUDE_ENTRIES]

    # Normalise + dedupe first, order-independently: an include equal to or
    # BELOW another of the same marker is a duplicate whichever was written
    # first -- the outermost declaration covers it (§2.2 step 9).
    #
    # Both passes are sets and one sorted scan (dash-db-3): the list-membership
    # test and the nested `next(...)` they replace were each O(n^2), which the
    # entry cap above bounds but does not make cheap.
    ordered: list[str] = []
    seen: set[str] = set()
    for path in paths:
        declared = normalise_declared(path)
        if declared in seen:
            log.info("marker of %s: duplicate include %s dropped", borrower_rel, declared)
            continue
        seen.add(declared)
        ordered.append(declared)
    # An include is a duplicate when ANY other declaration of the same marker
    # is a proper prefix of it; in sorted order that ancestor is the last one
    # still open, so one scan answers every row. The sort key is the path plus
    # its separator, NOT the bare path: `a!` sorts between `a` and `a/b`, so on
    # bare keys the block of descendants is not contiguous and `a/b` would
    # escape its ancestor.
    inside: dict[str, str] = {}
    stack: list[str] = []
    for declared in sorted(ordered, key=lambda d: d + "/"):
        while stack and not declared.startswith(stack[-1] + "/"):
            stack.pop()
        if stack:
            inside[declared] = stack[-1]
        else:
            stack.append(declared)
    kept: list[str] = []
    for declared in ordered:
        outer = inside.get(declared)
        if outer is not None:
            log.info("marker of %s: include %s is inside %s -- dropped as duplicate",
                     borrower_rel, declared, outer)
            continue
        kept.append(declared)

    results: list[LinkResult] = []
    for i, declared in enumerate(kept):
        if i >= MAX_INCLUDES:
            # dash-db-3 (2026-09-11): STOP here, do not keep appending one
            # refusal per remaining entry. The cap's comment promises a
            # tampered marker cannot make this unbounded, but the loop used to
            # `continue`, so a marker with 10,000 includes produced 10,000
            # LinkResults and therefore up to 10,000 project_links rows (the
            # key is (borrower_slug, declared_path), and the declared path is
            # written by anyone who can write the share) - rewritten every
            # provision cycle and rendered on the admin page. One row says the
            # same thing and bounds the table by the constant.
            # The count is the marker's OWN total, not what survived the entry
            # cap above (dash-db-3): an admin reading this row is being told
            # how big the file on the share is, and a number that shrank to
            # the cap would hide exactly the tampering worth seeing.
            ignored = max(len(kept) - MAX_INCLUDES,
                          declared_total - MAX_INCLUDES)
            log.warning("marker of %s: %d includes over the limit of %d were ignored",
                        borrower_rel, ignored, MAX_INCLUDES)
            results.append(LinkResult(
                declared=declared, status=STATUS_INVALID,
                detail=f"too many includes (limit {MAX_INCLUDES}); "
                       f"{ignored} ignored"))
            break
        results.append(resolve_include(projects_dir, borrower_rel, declared))
    return results
