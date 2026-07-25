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

# Cap on how many "would transfer"/"would delete" object names we hold in
# memory -- a whole-tree dry run (D-2) can log hundreds of thousands of
# per-file lines; the totals below still come from rclone's own summary
# stats record, so capping the sample lists loses nothing but the (already
# unusable) full listing. See AUDIT §6 "dry run buffers the entire verbose
# rclone log in memory".
_OBJECTS_CAP = 200


def parse_dry_run_stats(stderr_text: str) -> dict[str, Any]:
    """Parse rclone --use-json-log --dry-run stderr. Returns
    {"count": int, "bytes": int, "objects": [names], "objects_total": int,
    "deletes": int, "deleted_dirs": int, "delete_objects": [names],
    "delete_objects_total": int}. Verified against rclone 1.71
    (2026-07-24): the final `stats` record carries totalTransfers/
    totalBytes/deletes/deletedDirs for what WOULD happen under --dry-run;
    each skipped transfer logs 'Skipped copy as --dry-run is set' and each
    skipped removal logs 'Skipped delete as --dry-run is set', both with an
    "object" field -- kept in SEPARATE lists so a deletion is never
    mistaken for (or hidden among) a harmless upload/download (AUDIT D-1)."""
    count = 0
    total_bytes = 0
    deletes = 0
    deleted_dirs = 0
    objects: list[str] = []
    objects_total = 0
    delete_objects: list[str] = []
    delete_objects_total = 0
    for line in stderr_text.splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        stats = rec.get("stats")
        if isinstance(stats, dict):
            count = int(stats.get("totalTransfers", count) or 0)
            total_bytes = int(stats.get("totalBytes", total_bytes) or 0)
            deletes = int(stats.get("deletes", deletes) or 0)
            deleted_dirs = int(stats.get("deletedDirs", deleted_dirs) or 0)
        obj = rec.get("object")
        msg = rec.get("msg", "")
        low = msg.lower()
        if not obj or "dry-run" not in low:
            continue
        if "delete" in low:
            delete_objects_total += 1
            if len(delete_objects) < _OBJECTS_CAP:
                delete_objects.append(obj)
        else:
            objects_total += 1
            if len(objects) < _OBJECTS_CAP:
                objects.append(obj)
    return {
        "count": count,
        "bytes": total_bytes,
        "objects": objects,
        "objects_total": objects_total,
        "deletes": deletes,
        "deleted_dirs": deleted_dirs,
        "delete_objects": delete_objects,
        "delete_objects_total": delete_objects_total,
    }


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
    # build_up/down_command always add --verbose so the REAL runs get
    # per-file INFO log lines for parse_json_log() -- but a dry run only
    # needs the NOTICE-level "Skipped ... as --dry-run is set" lines and the
    # --stats summary record (added above via stats_interval), both of which
    # rclone emits at the default log level. --verbose on a whole-tree dry
    # run instead floods capture_output with one JSON line per file, which
    # parse_dry_run_stats then has to hold entirely in memory (AUDIT §6).
    cmd = [arg for arg in cmd if arg != "--verbose"]
    return cmd + ["--dry-run"]


def reconcile_with_nas(
    cfg: dict[str, Any],
    subpath: Optional[str],
    state_dir: Path,
    run_fn: Callable[[list[str], float], str] = _default_run,
    timeout: float = 120.0,
) -> dict[str, Any]:
    """Dry-run both lanes for `subpath` (a project subtree). Returns
    {"uploads": {...}, "downloads": {...}, "ok": bool, "error": str|None,
    "skip_lane_b": bool}. Never raises.

    A blank/None `subpath` is a HARD ABORT, not a whole-tree fallback: it
    means the caller couldn't pin down which project is being consolidated
    (e.g. a blank active_project with no server-root mapping for the open
    Resolve project), and running either lane against the whole tree would
    upload every local file and -- worse -- let lane B's `rclone sync`
    delete every local Proxy/ file the NAS doesn't have, across every
    project, not just the one being onboarded (AUDIT D-2).

    `skip_lane_b` is True whenever the down-direction dry run reports it
    would delete anything: lane B is a destructive `rclone sync`, and a
    dry-run delete count here means the consent dialog's promised "proxies
    download" is really "local proxy files get deleted" (AUDIT D-1). The
    caller is responsible for actually honouring skip_lane_b before running
    lane B; this function only computes and surfaces it.
    """
    result: dict[str, Any] = {
        "uploads": None, "downloads": None, "ok": True, "error": None,
        "skip_lane_b": False,
    }
    if subpath is None or not str(subpath).strip():
        result["ok"] = False
        result["error"] = "no active project resolved — refusing whole-tree consolidate"
        log.error("reconcile_with_nas: %s", result["error"])
        return result
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

    downloads = result["downloads"] or {}
    deletes = int(downloads.get("deletes", 0) or 0)
    deleted_dirs = int(downloads.get("deleted_dirs", 0) or 0)
    if deletes or deleted_dirs:
        result["skip_lane_b"] = True
        log.warning(
            "reconcile_with_nas: dry-run reports the proxy sync would DELETE "
            "%d local file(s) and %d local dir(s) under %s -- lane B (proxy "
            "download) must be SKIPPED to avoid data loss",
            deletes, deleted_dirs, subpath,
        )
    return result


def lane_b_allowed(reconcile: dict[str, Any]) -> bool:
    """Whether the actual lane-B (proxy download) run is safe to execute
    after this reconcile: the dry run must have succeeded AND reported zero
    deletions. Callers (e.g. app.py's consolidate flow) must check this
    before invoking the real `rclone sync` -- see reconcile_with_nas's
    docstring (AUDIT D-1)."""
    if not reconcile.get("ok", False):
        return False
    return not reconcile.get("skip_lane_b", False)


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
        deletes = int(down.get("deletes", 0) or 0)
        deleted_dirs = int(down.get("deleted_dirs", 0) or 0)
        if deletes or deleted_dirs:
            dirs_part = f" and {deleted_dirs} folder(s)" if deleted_dirs else ""
            lines.append(
                f"  !!! WARNING: the NAS proxy sync would DELETE {deletes} local file(s)"
                f"{dirs_part} !!!"
            )
            lines.append(
                "  Proxy download will be SKIPPED for this consolidate -- fix the mismatch "
                "on the NAS first, then re-run."
            )
        else:
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
