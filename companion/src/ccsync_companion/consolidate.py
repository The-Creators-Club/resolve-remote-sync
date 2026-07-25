"""Pre-existing-project consolidate & upload — the logic half.

Onboarding a project that predates the sync system: a remote editor already
has originals scattered around their own disk. This module plans the tidy-up:

  1. Consolidate: copy every out-of-tree media-pool clip into the canonical
     project folder and relink Resolve to the copy (never move -- a failed
     relink must never strand a file; the scattered original is left for the
     editor to delete).
  2. Reconcile against the NAS: `rclone --dry-run` reports how many originals
     would upload (lane A) and how many proxies would download (lane B), so
     the editor sees the plan before anything transfers.

Everything here is pure or subprocess-injectable so it is testable without a
display, Resolve, or a live NAS. app.consolidate_project() wires it to the
tray action, the report dialog, and the real lane runs.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any, Callable, Optional

from . import fixer, popup
from .sync import rclone_lane

log = logging.getLogger("ccsync.consolidate")


# ------------------------------------------------------------ local plan

def _safe_size(path: str, size_fn: Callable[[str], int]) -> int:
    try:
        return int(size_fn(path))
    except Exception:
        return 0


def plan_local_consolidation(
    out_of_tree_items: list[dict[str, Any]],
    local_root: str,
    editor_name: str,
    project_prefix: str,
    server_roots: Optional[dict[str, str]] = None,
    size_fn: Callable[[str], int] = os.path.getsize,
) -> dict[str, Any]:
    """Turn out-of-tree media-pool items into copy operations, deduped by
    source path (popup.build_popup_rows already dedupes and resolves the
    destination, honoring the sticky server root). Returns:
        {"ops": [{file_path, media_pool_items, dest_rel, size}], "count", "bytes"}
    """
    rows = popup.build_popup_rows(
        out_of_tree_items,
        local_root=local_root,
        editor_name=editor_name,
        project_prefix=project_prefix,
        server_roots=server_roots,
    )
    ops = []
    total = 0
    for row in rows:
        size = _safe_size(row["file_path"], size_fn)
        total += size
        ops.append({
            "file_path": row["file_path"],
            "media_pool_items": row.get("media_pool_items", []),
            "dest_rel": row["suggested_dest"],
            "size": size,
        })
    return {"ops": ops, "count": len(ops), "bytes": total}


# ------------------------------------------------------------ rclone diff

def parse_dry_run_stats(stderr_text: str) -> dict[str, Any]:
    """Parse rclone --use-json-log --dry-run stderr. Returns
    {"count": int, "bytes": int, "objects": [names]}. Verified against
    rclone 1.71 (2026-07-24): the final `stats` record carries
    totalTransfers/totalBytes for what WOULD transfer under --dry-run, and
    each skipped object logs 'Skipped copy as --dry-run is set' with an
    "object" field."""
    count = 0
    total_bytes = 0
    objects: list[str] = []
    for line in stderr_text.splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        stats = rec.get("stats")
        if isinstance(stats, dict):
            count = int(stats.get("totalTransfers", count) or 0)
            total_bytes = int(stats.get("totalBytes", total_bytes) or 0)
        obj = rec.get("object")
        msg = rec.get("msg", "")
        if obj and "dry-run" in msg.lower():
            objects.append(obj)
    return {"count": count, "bytes": total_bytes, "objects": objects}


def _default_run(cmd: list[str], timeout: float) -> str:
    """Run rclone, return stderr text (rclone's JSON log goes to stderr)."""
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return proc.stderr or ""


def _dry_run_command(
    direction: str, cfg: dict[str, Any], subpath: Optional[str], filter_file: Path
) -> list[str]:
    rclone_path = cfg.get("rclone_path", "rclone")
    common = dict(
        rclone_path=rclone_path,
        local_root=cfg["local_root"],
        remote=cfg["remote"],
        remote_root=cfg["remote_root"],
        filter_file=filter_file,
        transfers=int(cfg.get("transfers", 4)),
        subpath=subpath,
        stats_interval="1s",
    )
    if direction == rclone_lane.DIRECTION_UP:
        cmd = rclone_lane.build_up_command(**common)
    else:
        cmd = rclone_lane.build_down_command(**common)
    return cmd + ["--dry-run"]


def reconcile_with_nas(
    cfg: dict[str, Any],
    subpath: Optional[str],
    state_dir: Path,
    run_fn: Callable[[list[str], float], str] = _default_run,
    timeout: float = 120.0,
) -> dict[str, Any]:
    """Dry-run both lanes for `subpath` (a project subtree, or None = whole
    tree). Returns {"uploads": {count,bytes,objects}, "downloads": {...},
    "ok": bool, "error": str|None}. Never raises."""
    result: dict[str, Any] = {"uploads": None, "downloads": None, "ok": True, "error": None}
    try:
        up_filter = rclone_lane.write_filter_file(
            rclone_lane.build_filter_rules_up(), state_dir / "consolidate_filter_up.txt"
        )
        down_filter = rclone_lane.write_filter_file(
            rclone_lane.build_filter_rules_down(), state_dir / "consolidate_filter_down.txt"
        )
        up_cmd = _dry_run_command(rclone_lane.DIRECTION_UP, cfg, subpath, up_filter)
        result["uploads"] = parse_dry_run_stats(run_fn(up_cmd, timeout))
        down_cmd = _dry_run_command(rclone_lane.DIRECTION_DOWN, cfg, subpath, down_filter)
        result["downloads"] = parse_dry_run_stats(run_fn(down_cmd, timeout))
    except Exception as exc:
        log.exception("reconcile dry-run failed")
        result["ok"] = False
        result["error"] = str(exc)
    return result


# ------------------------------------------------------------ report text

def human_bytes(n: int) -> str:
    size = float(n or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return "?"


def build_report(plan: dict[str, Any], reconcile: dict[str, Any]) -> str:
    """One human-readable summary of what consolidate-and-upload will do."""
    lines = ["PRE-EXISTING PROJECT — CONSOLIDATE & UPLOAD", ""]
    lines.append(
        f"  {plan['count']} scattered clip(s) to copy into the project "
        f"folder ({human_bytes(plan['bytes'])})"
    )
    if reconcile.get("ok"):
        up = reconcile.get("uploads") or {"count": 0, "bytes": 0}
        down = reconcile.get("downloads") or {"count": 0, "bytes": 0}
        lines.append(
            f"  {up['count']} original(s) will upload to the NAS "
            f"({human_bytes(up['bytes'])}) — plus the consolidated clips above once copied in"
        )
        lines.append(
            f"  {down['count']} proxy file(s) will download from the NAS "
            f"({human_bytes(down['bytes'])})"
        )
    else:
        lines.append(f"  (could not check the NAS: {reconcile.get('error')})")
    lines.append("")
    lines.append("Originals are COPIED, never moved — your scattered files stay put.")
    return "\n".join(lines)


# ------------------------------------------------------------ execution

def run_consolidation(
    ops: list[dict[str, Any]],
    local_root: str,
    fix_clip_fn: Callable[..., dict[str, Any]] = fixer.fix_clip,
    progress_fn: Optional[Callable[[int, int, dict[str, Any]], None]] = None,
) -> list[dict[str, Any]]:
    """Copy+relink every op (fixer.fix_clip never raises). Returns per-op
    results with file_path attached. Same shape/semantics as
    popup.perform_fix_all, but driven from the ops list."""
    results = []
    total = len(ops)
    for op in ops:
        outcome = dict(fix_clip_fn(
            op["file_path"], op["dest_rel"], local_root, op.get("media_pool_items", [])
        ))
        outcome["file_path"] = op["file_path"]
        results.append(outcome)
        if progress_fn is not None:
            try:
                progress_fn(len(results), total, outcome)
            except Exception:
                log.exception("consolidation progress callback failed")
    return results
