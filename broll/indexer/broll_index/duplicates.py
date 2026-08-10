"""`broll-index duplicates` — find clips that already exist elsewhere in the index and
mark them `duplicate_of` the canonical copy.

THE CENTRAL CORRECTNESS REQUIREMENT (not an edge case): a video marked `duplicate_of` is
skipped when the archive is copied to the NAS (see broll_index/manifest.py). A false
positive here does not just waste a little disk space — it LOSES FOOTAGE, permanently,
the moment the "real" copy is deleted from wherever it currently sits and only the
(now-unmarked-but-actually-unique) file was ever indexed.

Two-stage by design, matching the reasoning in migrations/005_duplicates.sql:

  1. `find_candidates` groups videos by the fast partial `hash` (first + last 8 MiB +
     size, computed by `scan` — see hashing.hash_file_partial). This is cheap enough to
     run over an entire archive, but it can in principle collide for two files that are
     NOT the same content: same size, same first 8 MiB, same last 8 MiB, different
     middle. That is a CANDIDATE, never a conclusion.

  2. `confirm_group` computes (or reuses a cached) whole-file hash — hashing.hash_file_full
     — for every candidate and re-groups by true equality. A partial-hash group can
     legitimately split into several distinct-content subgroups; this is handled, not
     assumed away. Only a confirmed subgroup of 2+ is ever eligible to be marked
     `duplicate_of`.

`--no-verify` skips step 2 entirely and marks straight off the partial-hash grouping —
faster, but exactly as risky as the paragraph above describes. The CLI prints a loud
warning when it's used (see cli.py's cmd_duplicates).

Canonical pick (`pick_canonical`) mirrors rebase.py's `_rank`: highest status rank, then
most segments, then lowest id — so existing index work (proxies, contact sheets, the
Claude pass) is never the one thrown away. The two modules deliberately agree on what
"most-indexed" means.

Duplicate rows are never deleted (unlike rebase's `--prune-duplicates`): they keep their
row so the index still knows every location a given clip exists at, but are excluded
from `run_pipeline` (pipeline.py), from the copy manifest (manifest.py), and — per
SPEC.md, on the web/ side — from search results.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .hashing import hash_file_full

# Same preference order as rebase.py's _STATUS_RANK — kept in sync deliberately so
# "most-indexed" means the same thing whichever command is looking at it.
_STATUS_RANK = {"sorted": 5, "indexed": 4, "proxied": 3, "probed": 2, "discovered": 1, "error": 0}

ResolvePathFn = Callable[[dict[str, Any]], "Path | None"]


def _rank(video: dict[str, Any], segment_counts: dict[int, int]) -> tuple[int, int, int]:
    # Third element breaks ties by lowest id (negated so sorting descending picks it).
    return (
        _STATUS_RANK.get(video.get("status") or "", 0),
        segment_counts.get(video["id"], 0),
        -video["id"],
    )


def find_candidates(videos: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Group videos sharing a partial `hash` into candidate duplicate sets (size >= 2).

    Videos with no recorded hash, or already marked as someone else's duplicate, are
    excluded from candidacy — a row that is already a duplicate never gets reconsidered
    as (or grouped as) a fresh candidate, which is what makes `--apply` idempotent: the
    canonical row's `duplicate_of` stays NULL, so on the next run any new copy of the
    same content still finds it and groups with it, while already-settled duplicates
    just drop out of the pool.
    """
    by_hash: dict[str, list[dict[str, Any]]] = {}
    for v in videos:
        digest = v.get("hash")
        if not digest:
            continue
        if v.get("duplicate_of"):
            continue
        by_hash.setdefault(digest, []).append(v)
    return [group for group in by_hash.values() if len(group) >= 2]


def pick_canonical(
    group: list[dict[str, Any]], segment_counts: dict[int, int] | None = None
) -> dict[str, Any]:
    """The most-indexed row in a group: highest status rank, then most segments, then
    lowest id. Mirrors rebase.py's ranking so the two commands never disagree about
    which copy is "the" canonical one."""
    segment_counts = segment_counts or {}
    return sorted(group, key=lambda v: _rank(v, segment_counts), reverse=True)[0]


@dataclass
class ConfirmedGroup:
    """A subset of a partial-hash candidate group confirmed byte-identical by whole-file
    hash. `videos` carries each row with `full_hash` filled in (freshly computed or
    reused from a cached `videos.full_hash`)."""

    videos: list[dict[str, Any]]
    full_hash: str


def confirm_group(
    group: list[dict[str, Any]],
    resolve_path: ResolvePathFn,
    hasher: Callable[[Path], str] = hash_file_full,
) -> tuple[list[ConfirmedGroup], list[dict[str, Any]], list[dict[str, Any]]]:
    """Confirm a partial-hash candidate group via whole-file hash.

    Returns (confirmed, singletons, missing):

    - `confirmed`: subsets of 2+ videos whose whole-file hash actually matches — true
      duplicates. A single partial-hash group CAN split into several of these (or none)
      — that's the whole point of verification, so it is not assumed away.
    - `singletons`: videos whose whole-file hash matched nobody else in the group — the
      partial hash collided but the content differs. THIS IS THE CASE THAT MUST NEVER BE
      MARKED DUPLICATE.
    - `missing`: videos whose source file no longer exists (unknown share, or the file
      is gone). Never marked duplicate either — reported separately so a human can look
      into it, rather than silently trusting a stale hash.

    `hash_file_full` is only actually invoked for rows that don't already have a cached
    `full_hash` — this is what makes `--apply` cheap to re-run.
    """
    by_full_hash: dict[str, list[dict[str, Any]]] = {}
    missing: list[dict[str, Any]] = []

    for v in group:
        path = resolve_path(v)
        if path is None or not Path(path).is_file():
            missing.append(v)
            continue
        full_hash = v.get("full_hash") or hasher(path)
        by_full_hash.setdefault(full_hash, []).append({**v, "full_hash": full_hash})

    confirmed: list[ConfirmedGroup] = []
    singletons: list[dict[str, Any]] = []
    for full_hash, rows in by_full_hash.items():
        if len(rows) >= 2:
            confirmed.append(ConfirmedGroup(videos=rows, full_hash=full_hash))
        else:
            singletons.append(rows[0])

    return confirmed, singletons, missing


@dataclass
class DuplicatePlan:
    """What `duplicates` would do. Rendered as a report before anything is written."""

    marked: list[dict[str, Any]] = field(default_factory=list)  # {video, duplicate_of, full_hash}
    canonicals: list[dict[str, Any]] = field(default_factory=list)  # {video, full_hash}
    false_positives: list[dict[str, Any]] = field(default_factory=list)  # {video, reason}
    missing: list[dict[str, Any]] = field(default_factory=list)  # {video, reason}
    verified: bool = True

    def summary(self) -> str:
        return (
            f"{len(self.marked)} duplicate(s) to mark, "
            f"{len(self.canonicals)} canonical copy/copies kept, "
            f"{len(self.false_positives)} partial-hash collision(s) confirmed distinct (NOT marked), "
            f"{len(self.missing)} file(s) missing (not marked) — "
            f"verification {'ON' if self.verified else 'OFF (--no-verify: unconfirmed, risk of data loss)'}"
        )


def _plan_group(
    plan: DuplicatePlan,
    rows: list[dict[str, Any]],
    segment_counts: dict[int, int],
    *,
    full_hash: str | None,
) -> None:
    canonical = pick_canonical(rows, segment_counts)
    plan.canonicals.append({"video": canonical, "full_hash": full_hash})
    for v in rows:
        if v["id"] == canonical["id"]:
            continue
        plan.marked.append({"video": v, "duplicate_of": canonical["id"], "full_hash": full_hash})


def plan_duplicates(
    videos: list[dict[str, Any]],
    *,
    resolve_path: ResolvePathFn,
    segment_counts: dict[int, int] | None = None,
    verify: bool = True,
    hasher: Callable[[Path], str] = hash_file_full,
) -> DuplicatePlan:
    """Pure planning step (only reads files, to hash them, when verify=True — never
    writes to storage). Decides what `duplicates` should change."""
    segment_counts = segment_counts or {}
    plan = DuplicatePlan(verified=verify)

    for group in find_candidates(videos):
        if verify:
            confirmed, singletons, missing = confirm_group(group, resolve_path, hasher=hasher)
            plan.missing.extend(
                {"video": v, "reason": "source file no longer exists — not marked duplicate"}
                for v in missing
            )
            plan.false_positives.extend(
                {
                    "video": v,
                    "reason": (
                        "partial hash matched other candidate(s) in this group but the "
                        "whole-file hash differs — genuinely different content"
                    ),
                }
                for v in singletons
            )
            for cg in confirmed:
                _plan_group(plan, cg.videos, segment_counts, full_hash=cg.full_hash)
        else:
            _plan_group(plan, group, segment_counts, full_hash=None)

    return plan


def render_report(plan: DuplicatePlan) -> str:
    lines = ["# Duplicate detection report", "", plan.summary(), ""]

    if not plan.verified:
        lines += [
            "**WARNING: run with --no-verify.**",
            "",
            "These duplicate marks come from the fast partial hash ONLY (first + last "
            "8 MiB + size) and have NOT been confirmed by a whole-file hash. A false "
            "positive here is skipped during the NAS copy, which LOSES footage. Re-run "
            "with verification on (the default, i.e. without --no-verify) before trusting "
            "this report.",
            "",
        ]

    if plan.marked:
        lines += ["## Marked duplicate", ""]
        lines += [
            f"- [{m['video']['id']}] {m['video'].get('share')}:{m['video'].get('rel_path')}"
            f"  ->  duplicate of video {m['duplicate_of']}"
            for m in plan.marked
        ]
        lines.append("")

    if plan.canonicals:
        lines += ["## Canonical copies kept", ""]
        lines += [
            f"- [{c['video']['id']}] {c['video'].get('share')}:{c['video'].get('rel_path')}"
            for c in plan.canonicals
        ]
        lines.append("")

    if plan.false_positives:
        lines += [
            "## Partial-hash collisions confirmed DISTINCT (NOT marked duplicate)",
            "",
            "These shared a partial hash with another row but their whole-file hash "
            "differs — genuinely different content. This is exactly the case "
            "verification exists to catch; do not mark these duplicate.",
            "",
        ]
        lines += [
            f"- [{f['video']['id']}] {f['video'].get('share')}:{f['video'].get('rel_path')} — {f['reason']}"
            for f in plan.false_positives
        ]
        lines.append("")

    if plan.missing:
        lines += ["## Missing source files (NOT marked duplicate)", ""]
        lines += [
            f"- [{m['video']['id']}] {m['video'].get('share')}:{m['video'].get('rel_path')} — {m['reason']}"
            for m in plan.missing
        ]
        lines.append("")

    return "\n".join(lines)


def do_duplicates(
    storage: Any,
    *,
    resolve_path: ResolvePathFn,
    verify: bool = True,
    apply: bool = False,
) -> tuple[DuplicatePlan, str]:
    """Plan and (unless dry-run) apply duplicate detection. Returns (plan, report_text).

    Applying is idempotent and re-runnable: `find_candidates` excludes rows that already
    have `duplicate_of` set, so a second run with nothing new on disk produces an empty
    plan and writes nothing.
    """
    videos = storage.all_videos()
    segment_counts = storage.segment_counts()

    plan = plan_duplicates(
        videos, resolve_path=resolve_path, segment_counts=segment_counts, verify=verify
    )
    report = render_report(plan)

    if apply:
        for m in plan.marked:
            fields: dict[str, Any] = {"duplicate_of": m["duplicate_of"]}
            if m.get("full_hash"):
                fields["full_hash"] = m["full_hash"]
            storage.update_video(m["video"]["id"], **fields)

        # Cache the canonical's own whole-file hash too (confirm_group already computed
        # it), so a later re-run of `duplicates` never has to hash it again. Writing the
        # same value again when it's already cached is harmless (idempotent).
        for c in plan.canonicals:
            full_hash = c.get("full_hash")
            if full_hash:
                storage.update_video(c["video"]["id"], full_hash=full_hash)

    return plan, report
