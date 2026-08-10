"""`broll-index sort` — move indexed inbox clips into their category folder."""

from __future__ import annotations

import os
import shutil
from pathlib import Path, PurePosixPath
from typing import Any

from .config import Config
from .storage.base import Storage


def _dedupe_rel_path(share_root: Path, rel_path: str) -> str:
    candidate = rel_path
    n = 1
    while (share_root / candidate).exists():
        n += 1
        p = PurePosixPath(rel_path)
        parent = str(p.parent)
        new_name = f"{p.stem}_{n}{p.suffix}"
        candidate = new_name if parent == "." else f"{parent}/{new_name}"
    return candidate


def plan_move(share_root: Path, video: dict[str, Any]) -> tuple[Path, str]:
    """Compute the destination absolute path and new rel_path for a sortable video."""
    category = video["category"]
    filename = PurePosixPath(video["rel_path"]).name
    dest_rel = _dedupe_rel_path(share_root, f"{category}/{filename}")
    return share_root / dest_rel, dest_rel


def move_file(src: Path, dest: Path, same_volume: bool | None = None) -> None:
    """Move src -> dest. os.replace when same volume, else copy+verify-size+delete.

    `same_volume` can be forced (used by tests) — by default it's auto-detected by
    comparing drive letters (Windows) / st_dev (POSIX).
    """
    dest.parent.mkdir(parents=True, exist_ok=True)

    if same_volume is None:
        if os.name == "nt":
            same_volume = os.path.splitdrive(str(src.resolve()))[0].lower() == os.path.splitdrive(
                str(dest.resolve())
            )[0].lower()
        else:
            same_volume = src.stat().st_dev == dest.parent.stat().st_dev

    if same_volume:
        os.replace(src, dest)
        return

    shutil.copy2(src, dest)
    if dest.stat().st_size != src.stat().st_size:
        dest.unlink(missing_ok=True)
        raise IOError(f"size mismatch copying {src} -> {dest}, aborting move")
    src.unlink()


def do_sort(cfg: Config, storage: Storage, dry_run: bool = False) -> list[dict[str, Any]]:
    plan: list[dict[str, Any]] = []
    for video in storage.sortable_videos():
        share_cfg = cfg.shares.get(video["share"])
        if share_cfg is None:
            storage.set_error(video["id"], f"sort failed: unknown share '{video['share']}'")
            continue

        share_root = Path(share_cfg.root)
        src_path = share_root / video["rel_path"]
        dest_path, dest_rel = plan_move(share_root, video)
        entry = {"video_id": video["id"], "from": video["rel_path"], "to": dest_rel}
        plan.append(entry)

        if dry_run:
            continue

        try:
            move_file(src_path, dest_path)
            storage.record_moved(video["id"], dest_rel)
        except Exception as e:  # noqa: BLE001 - never crash the sort loop over one bad file
            storage.set_error(video["id"], f"sort failed: {e}")

    return plan
