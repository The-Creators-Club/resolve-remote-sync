"""Embed each archive preview's source timecode so Resolve accepts it as a proxy.

KNOWN_BUGS R10 (2026-08-12): Resolve's LinkProxyMedia VALIDATES the pairing
and refuses a proxy with no embedded timecode against a source that has one
-- proven live: remuxing the same preview bytes with -timecode flipped the
identical link from refused to accepted. build_proxy never carried timecode
(ffmpeg drops it on encode unless asked), so no archived clip could ever
attach its preview, in Resolve's own adjacent-Proxy auto-attach or the
companion's explicit link alike. The encoder now embeds it; this script
repairs the previews already in the archive.

A REMUX, NOT A RE-ENCODE: `-c copy -timecode <tc>` rewrites the container
only -- seconds per file, no GPU, no quality change (and no bearing on the
declined R9 sweep; a 10-bit preview stays 10-bit). Previews whose source has
no timecode, or that already carry one, are skipped. Writes `.fix~<name>`
beside the target and os.replace()s it into place; DB untouched; the archive
is under no sync lane, so nothing fans out (editors' local copies arrive via
the companion's per-clip fetch, which reads whatever the NAS has).

Run on the base rig with P: mapped:

    python fix_proxy_timecode.py            # dry-run: count and report only
    python fix_proxy_timecode.py --apply
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from broll_index import ffmpeg_tools

DEFAULT_ROOT = r"P:\Assets\B-roll Archive"
WORKERS = 4


def candidate_previews(root: Path) -> list[Path]:
    conn = sqlite3.connect(f"file:{root / 'broll.db'}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    out = []
    for row in conn.execute("SELECT id, archive_path FROM videos"):
        rel = row["archive_path"]
        path = (root / rel) if rel else (root / "proxies" / f"{row['id']}.mp4")
        if path.is_file():
            out.append(path)
    conn.close()
    return out


def source_for(preview: Path) -> Path | None:
    """The top-slot file this preview pairs with (unique stem sibling above
    Proxy/), or None. Same rule as fix_10bit_proxies.source_for, minus the
    fall-back-to-self: remuxing the preview's own (absent) timecode into
    itself would be a no-op."""
    if preview.parent.name != "Proxy":
        return None
    parent = preview.parent.parent
    try:
        entries = os.listdir(parent)
    except OSError:
        return None
    matches = [parent / e for e in entries
               if os.path.splitext(e)[0] == preview.stem and (parent / e).is_file()]
    return matches[0] if len(matches) == 1 else None


def plan(preview: Path) -> tuple[str, str | None]:
    """(verdict, source_tc): verdict in {fix, has-tc, no-source, source-no-tc}."""
    if ffmpeg_tools.read_timecode(preview):
        return "has-tc", None
    src = source_for(preview)
    if src is None:
        return "no-source", None
    tc = ffmpeg_tools.read_timecode(src)
    if not tc:
        return "source-no-tc", None
    return "fix", tc


def remux(preview: Path, tc: str) -> str | None:
    """Rewrite `preview` in place with `tc` embedded. Error string or None."""
    tmp = preview.with_name(f".fix~{preview.name}")
    r = subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-i", str(preview), "-c", "copy", "-timecode", tc,
         "-movflags", "+faststart", str(tmp)],
        capture_output=True, encoding="utf-8", errors="replace", timeout=600,
    )
    if r.returncode != 0:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return f"{preview}: ffmpeg exited {r.returncode}: {(r.stderr or '').strip()[:160]}"
    # The remux must round-trip the timecode, or the replace buys nothing.
    if not ffmpeg_tools.read_timecode(tmp):
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return f"{preview}: remux dropped the timecode"
    os.replace(tmp, preview)
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=DEFAULT_ROOT)
    ap.add_argument("--apply", action="store_true",
                    help="remux the offenders (default: report only)")
    ap.add_argument("--limit", type=int, default=0,
                    help="stop after fixing N files (smoke-testing --apply)")
    args = ap.parse_args()
    root = Path(args.root)

    previews = candidate_previews(root)
    print(f"{len(previews)} previews on disk; probing with {WORKERS} workers…")

    todo: list[tuple[Path, str]] = []
    tallies = {"has-tc": 0, "no-source": 0, "source-no-tc": 0}
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for preview, (verdict, tc) in zip(previews, pool.map(plan, previews)):
            if verdict == "fix":
                todo.append((preview, tc))
            else:
                tallies[verdict] += 1

    print(f"needs timecode: {len(todo)}")
    for verdict, n in tallies.items():
        print(f"  {verdict}: {n}")
    if not args.apply:
        for p, tc in todo[:5]:
            print(f"  e.g.: {p.relative_to(root)}  <- {tc}")
        if todo:
            print("dry run — re-run with --apply to remux these.")
        return 0

    if args.limit:
        todo = todo[: args.limit]
    print(f"remuxing {len(todo)} previews with {WORKERS} workers…")
    failed: list[str] = []
    done = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for err in pool.map(lambda pair: remux(*pair), todo):
            done += 1
            if err:
                failed.append(err)
            if done % 200 == 0:
                print(f"  {done}/{len(todo)} ({len(failed)} failed)")
    print(f"done: {done - len(failed)} fixed, {len(failed)} failed")
    for f in failed[:20]:
        print("  FAILED:", f)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
