"""`broll-index rebase` — re-point an existing index at a new storage location.

Use case: the archive is indexed while it's still scattered across many drives
(each scanned as its own share), then everything is consolidated onto the NAS.
Rebase matches indexed videos to their new home **by content hash**, so all the
expensive work — proxies, contact sheets, and above all the Claude index passes —
is preserved. Nothing is re-encoded and nothing is re-indexed.

This works because `hashing.hash_file_partial` fingerprints file *content*
(first 8 MiB + last 8 MiB + size), which a copy or move does not change.

Duplicates are expected: a scattered archive usually holds the same clip on more
than one drive, which shows up as several DB rows sharing one hash. Rebase never
silently discards those — it points the best-indexed row at the NAS file and
reports the rest as superseded, for review.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TYPE_CHECKING

from .hashing import hash_file_partial
from .scanner import scan_share

if TYPE_CHECKING:
    from .storage.base import Storage

# Preference order when several indexed rows share one hash: keep the one that
# got furthest through the pipeline (and, tie-broken, the one with more segments).
_STATUS_RANK = {"sorted": 5, "indexed": 4, "proxied": 3, "probed": 2, "discovered": 1, "error": 0}


@dataclass
class RebasePlan:
    """What `rebase` would do. Rendered as a report before anything is written."""

    rematched: list[dict[str, Any]] = field(default_factory=list)
    already_correct: list[dict[str, Any]] = field(default_factory=list)
    superseded: list[dict[str, Any]] = field(default_factory=list)
    missing: list[dict[str, Any]] = field(default_factory=list)
    unindexed_files: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"{len(self.rematched)} rematched, "
            f"{len(self.already_correct)} already correct, "
            f"{len(self.superseded)} duplicate row(s) superseded, "
            f"{len(self.missing)} indexed video(s) not found on the new root, "
            f"{len(self.unindexed_files)} file(s) on the new root not in the index"
        )


def hash_tree(root: str | Path, data_root: str | Path | None = None) -> dict[str, list[str]]:
    """Hash every video under `root`. Returns hash -> [rel_path, ...]."""
    by_hash: dict[str, list[str]] = {}
    for sf in scan_share(root, data_root):
        digest = hash_file_partial(sf.path)
        by_hash.setdefault(digest, []).append(sf.rel_path)
    return by_hash


def _rank(video: dict[str, Any], segment_counts: dict[int, int]) -> tuple[int, int]:
    return (_STATUS_RANK.get(video.get("status") or "", 0), segment_counts.get(video["id"], 0))


def plan_rebase(
    videos: list[dict[str, Any]],
    files_by_hash: dict[str, list[str]],
    *,
    to_share: str,
    segment_counts: dict[int, int] | None = None,
) -> RebasePlan:
    """Pure planning step — no I/O, no writes. Decides what rebase should change."""
    segment_counts = segment_counts or {}
    plan = RebasePlan()

    videos_by_hash: dict[str, list[dict[str, Any]]] = {}
    for v in videos:
        digest = v.get("hash")
        if not digest:
            plan.missing.append({"video": v, "reason": "no hash recorded — re-run scan on its original root"})
            continue
        videos_by_hash.setdefault(digest, []).append(v)

    for digest, rows in videos_by_hash.items():
        new_paths = files_by_hash.get(digest)
        if not new_paths:
            for v in rows:
                plan.missing.append({"video": v, "reason": "no file with this content hash under the new root"})
            continue

        # Best-indexed row wins the (single) canonical NAS path.
        rows_ranked = sorted(rows, key=lambda v: _rank(v, segment_counts), reverse=True)
        winner, losers = rows_ranked[0], rows_ranked[1:]
        new_rel_path = sorted(new_paths)[0]

        if winner.get("share") == to_share and winner.get("rel_path") == new_rel_path:
            plan.already_correct.append({"video": winner, "rel_path": new_rel_path})
        else:
            plan.rematched.append(
                {
                    "video": winner,
                    "from": f"{winner.get('share')}:{winner.get('rel_path')}",
                    "to": f"{to_share}:{new_rel_path}",
                }
            )

        for dup in losers:
            plan.superseded.append(
                {
                    "video": dup,
                    "duplicate_of": winner["id"],
                    "note": f"same content as video {winner['id']} ({new_rel_path})",
                }
            )

        # More than one copy of this content on the new root is worth flagging too.
        for extra in sorted(new_paths)[1:]:
            plan.unindexed_files.append(f"{extra}  (duplicate copy of {new_rel_path})")

    indexed_hashes = set(videos_by_hash)
    for digest, paths in files_by_hash.items():
        if digest not in indexed_hashes:
            plan.unindexed_files.extend(sorted(paths))

    return plan


def render_report(plan: RebasePlan, to_share: str) -> str:
    lines = [f"# Rebase report — target share: {to_share}", "", plan.summary(), ""]

    if plan.rematched:
        lines += ["## Rematched (index preserved, path updated)", ""]
        lines += [f"- [{r['video']['id']}] {r['from']}  ->  {r['to']}" for r in plan.rematched]
        lines.append("")
    if plan.already_correct:
        lines += [f"## Already correct ({len(plan.already_correct)})", ""]
    if plan.superseded:
        lines += [
            "## Superseded duplicates (NOT deleted — review these)",
            "",
            "These rows indexed a copy of content that now lives at a single path on the",
            "new root. Their index data is redundant. Delete them with --prune-duplicates",
            "once you have read this list.",
            "",
        ]
        lines += [
            f"- [{s['video']['id']}] {s['video'].get('share')}:{s['video'].get('rel_path')} — {s['note']}"
            for s in plan.superseded
        ]
        lines.append("")
    if plan.missing:
        lines += ["## Not found on the new root (left untouched)", ""]
        lines += [
            f"- [{m['video']['id']}] {m['video'].get('share')}:{m['video'].get('rel_path')} — {m['reason']}"
            for m in plan.missing
        ]
        lines.append("")
    if plan.unindexed_files:
        lines += [
            "## On the new root but not in the index",
            "",
            "Run `scan` + `run` on the new root to index these.",
            "",
        ]
        lines += [f"- {p}" for p in plan.unindexed_files]
        lines.append("")

    return "\n".join(lines)


def do_rebase(
    storage: "Storage",
    *,
    to_share: str,
    root: str | Path,
    data_root: str | Path | None = None,
    dry_run: bool = True,
    prune_duplicates: bool = False,
) -> tuple[RebasePlan, str]:
    """Plan and (unless dry_run) apply a rebase. Returns (plan, report_text)."""
    videos = storage.all_videos()
    segment_counts = storage.segment_counts()
    files_by_hash = hash_tree(root, data_root)

    plan = plan_rebase(videos, files_by_hash, to_share=to_share, segment_counts=segment_counts)
    report = render_report(plan, to_share)

    if dry_run:
        return plan, report

    for r in plan.rematched:
        new_share, new_rel = r["to"].split(":", 1)
        storage.update_video(r["video"]["id"], share=new_share, rel_path=new_rel)

    if prune_duplicates:
        for s in plan.superseded:
            storage.delete_video(s["video"]["id"])

    return plan, report
