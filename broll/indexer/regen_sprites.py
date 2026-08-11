"""Regenerate legacy sprite sheets so their real geometry gets recorded.

Migration 009 added the five sprite_* columns that let the browser stop
re-deriving sheet geometry from source dimensions (BROLL-1) and stop applying
the cell cap to sheets that predate it (BROLL-2). But the columns are only
filled in when build_sprite runs — the ~7,117 sheets already in the archive
carry NULL and stay on the browser's legacy heuristics, which the 2026-08-11
hunt measured wrong for 95.3% of them (and badly wrong for the 95 uncapped
long-clip sheets). This sweep closes that tail: re-run build_sprite for every
clip whose geometry is unrecorded, from the local proxy, and record what was
actually built.

Idempotent and resumable by construction: the work list is
`sprite_cell_h IS NULL`, and each clip's UPDATE lands with its sheet — an
interrupted run just has less left to do. Clips whose proxy is missing are
reported and skipped, never fetched from the originals: this sweep is a
local-disk pass (proxies decode at hundreds of times realtime; the originals
live on a network share and would dominate the whole run — the same economics
as stage_proxy's derived_src comment).

After a run, the regenerated sheets and the DB still need to reach the NAS the
usual way (build_archive / the dashboard deploy's stills push); this script
deliberately touches nothing outside --data-root.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from broll_index import ffmpeg_tools  # noqa: E402
from broll_index.migrate import migrate_sqlite_db  # noqa: E402

GEOMETRY_COLUMNS = (
    "sprite_cell_w", "sprite_cell_h", "sprite_cols", "sprite_cells",
    "sprite_interval_s",
)


def work_list(con: sqlite3.Connection, data_root: Path, force: bool) -> list[dict]:
    """Clips whose sheet should be (re)built: geometry unrecorded, duration
    known, proxy on local disk. `force` widens to every clip with a proxy —
    for a sheet someone hand-deleted or a future format change."""
    predicate = "1=1" if force else "sprite_cell_h IS NULL"
    rows = con.execute(
        f"SELECT id, duration_s FROM videos "
        f"WHERE {predicate} AND duration_s IS NOT NULL ORDER BY id"
    ).fetchall()
    out = []
    for vid, duration_s in rows:
        proxy = data_root / "proxies" / f"{vid}.mp4"
        if proxy.is_file() and proxy.stat().st_size:
            out.append({"id": vid, "duration_s": duration_s, "proxy": proxy})
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data-root", required=True, type=Path,
                    help="index root holding broll.db, proxies/, sprites/")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--limit", type=int, default=0, help="stop after N clips (0 = all)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="rebuild even clips whose geometry is already recorded")
    args = ap.parse_args()

    db_path = args.data_root / "broll.db"
    if not db_path.is_file():
        print(f"regen_sprites: no broll.db under {args.data_root}", file=sys.stderr)
        return 1

    # 009 is idempotent; the web side applies it on its next boot, but this
    # sweep cannot write columns that are not there yet.
    print(migrate_sqlite_db(db_path))

    con = sqlite3.connect(db_path)
    try:
        todo = work_list(con, args.data_root, args.force)
        no_proxy = con.execute(
            "SELECT count(*) FROM videos WHERE sprite_cell_h IS NULL "
            "AND duration_s IS NOT NULL"
        ).fetchone()[0] - len(todo)
        if args.limit:
            todo = todo[: args.limit]
        print(f"regen_sprites: {len(todo)} clip(s) to build"
              + (f" ({no_proxy} unrecorded but no local proxy -- skipped; the "
                 f"closing count includes them)"
                 if no_proxy > 0 else ""))
        if args.dry_run or not todo:
            return 0

        sprites_dir = args.data_root / "sprites"
        started = time.monotonic()
        done = failed = 0

        def build(item: dict):
            return item["id"], ffmpeg_tools.build_sprite(
                item["proxy"], sprites_dir / f"{item['id']}.jpg",
                duration_s=item["duration_s"],
            )

        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = [pool.submit(build, item) for item in todo]
            for future in as_completed(futures):
                try:
                    vid, geometry = future.result()
                except Exception as exc:  # noqa: BLE001 - one bad clip must not stop the sweep
                    failed += 1
                    print(f"regen_sprites: FAILED: {exc}", file=sys.stderr)
                    continue
                # Written per clip so an interrupt loses nothing already built.
                con.execute(
                    "UPDATE videos SET " + ", ".join(f"{c}=?" for c in GEOMETRY_COLUMNS)
                    + " WHERE id=?",
                    [geometry[c] for c in GEOMETRY_COLUMNS] + [vid],
                )
                con.commit()
                done += 1
                if done % 250 == 0:
                    rate = done / (time.monotonic() - started)
                    print(f"regen_sprites: {done}/{len(todo)} "
                          f"({rate:.1f}/s, ~{(len(todo) - done) / rate:.0f}s left)")

        elapsed = time.monotonic() - started
        print(f"regen_sprites: {done} rebuilt, {failed} failed in {elapsed:.0f}s")
        remaining = con.execute(
            "SELECT count(*) FROM videos WHERE sprite_cell_h IS NULL "
            "AND duration_s IS NOT NULL"
        ).fetchone()[0]
        print(f"regen_sprites: {remaining} row(s) still unrecorded "
              f"(no local proxy, or failed above)")
        return 1 if failed else 0
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())
