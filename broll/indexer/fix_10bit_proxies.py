"""Find (and with --apply, re-encode) 10-bit browser previews in the archive.

KNOWN_BUGS R9 (2026-08-11): build_proxy never pinned a pixel format, so every
preview cut from a 10-bit source (all FX3/FX30 shoots, i.e. essentially the
whole Creators_Club collection) came out H.264 High 10 / yuv420p10le. Posters
and sprites are JPEGs and look fine; the <video> element draws a black
rectangle. The encoder is fixed (ffmpeg_tools.py pins `-pix_fmt yuv420p`);
this script repairs the previews already in the archive.

DRY-RUN BY DEFAULT: probes every preview the DB serves and reports the
10-bit count, touching nothing. `--apply` re-encodes each offender through
the fixed build_proxy — from the adjacent top-slot original (full quality,
`<dir>/<stem>.*` next to `<dir>/Proxy/<stem>.mp4`) when exactly one exists,
else from the 10-bit preview itself (the 4 stem-diverged clips of archive
task #23; a second generation of a browsing proxy is invisible at 540p).
Writes `.fix~<name>.mp4` beside the target and os.replace()s it into place,
so the web app never serves a half-written file. The DB is not touched:
paths do not change, and the archive tree is not under any sync lane, so
nothing fans out to editors (their copies arrive per-clip via the
companion's on-demand fetch, which reads whatever the NAS has).

Run on the base rig with P: mapped:

    python fix_10bit_proxies.py                       # report only
    python fix_10bit_proxies.py --apply               # re-encode
    python fix_10bit_proxies.py --apply --workers 2   # NVENC session cap
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from broll_index import ffmpeg_tools, inplace_fixes

DEFAULT_ROOT = r"P:\Assets\B-roll Archive"
PROBE_WORKERS = 8


def probe_pixels(path: Path) -> dict:
    """{codec, profile, pix_fmt} for the first video stream, or {error}."""
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=codec_name,profile,pix_fmt",
         "-of", "json", str(path)],
        capture_output=True, encoding="utf-8", errors="replace", timeout=120,
    )
    if r.returncode != 0:
        return {"error": (r.stderr or "").strip()[:200] or f"ffprobe exited {r.returncode}"}
    streams = json.loads(r.stdout or "{}").get("streams") or []
    if not streams:
        return {"error": "no video stream"}
    s = streams[0]
    return {"codec": s.get("codec_name"), "profile": s.get("profile"),
            "pix_fmt": s.get("pix_fmt")}


def is_browser_hostile(info: dict) -> bool:
    """10-bit (any flavour) or non-H.264: the formats a fleet browser draws
    as black. yuvj420p and plain yuv420p pass."""
    if "error" in info:
        return False
    if info.get("codec") != "h264":
        return True
    return "10" in str(info.get("pix_fmt") or "")


def candidate_files(root: Path) -> list[tuple[int, Path]]:
    """(video_id, preview_path) for every preview the web app would serve,
    resolved the same way routes_media._proxy_path does."""
    conn = sqlite3.connect(f"file:{root / 'broll.db'}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    out: list[tuple[int, Path]] = []
    for row in conn.execute("SELECT id, archive_path FROM videos"):
        rel = row["archive_path"]
        path = (root / rel) if rel else (root / "proxies" / f"{row['id']}.mp4")
        if path.is_file():
            out.append((row["id"], path))
    conn.close()
    return out


PROXY_DIR_NAMES = {"proxy", "proxies"}


def is_a_proxy(path: Path) -> bool:
    """Is this file structurally a preview -- i.e. does it live in `Proxy/`?

    THE ONLY THING THAT MAKES THIS SCRIPT SAFE TO RUN (COMMERCIAL_READINESS.md
    item 9, 2026-08-17). `candidate_files` resolves `videos.archive_path`
    straight out of the database, and nothing in the schema promises that
    column points inside a `Proxy/` directory -- an older row, a hand-edited
    path or a clip published before the layout rule was enforced all resolve
    to the TOP-SLOT ORIGINAL. `reencode` then transcoded that original in
    place, at 540p, over itself: the archive's best copy of the clip,
    destroyed, with `fixed` printed next to it.

    Structural, matching the convention proxy_relink.py and proxy_scan.py use
    on the companion side (`<dir>/Proxy/<stem>.mp4`). Case-insensitive, and
    `proxies/` too because the flat fallback layout uses that name.
    """
    return path.parent.name.lower() in PROXY_DIR_NAMES


def source_for(preview: Path) -> Path:
    """The top-slot original this preview was cut from, else the preview.

    Layout rule (HANDOFF.md §1): best media at `<dir>/<stem>.*`, preview at
    `<dir>/Proxy/<stem>.mp4`. Anything other than exactly one stem match
    (0 = stem diverged, 2+ = ambiguous) falls back to transcoding the
    preview itself rather than guessing -- which is only ever safe because
    is_a_proxy() has already established that the preview IS a proxy.
    """
    parent = preview.parent.parent
    if not is_a_proxy(preview):
        return preview
    matches = [p for p in parent.glob(f"{preview.stem}.*") if p.is_file()]
    return matches[0] if len(matches) == 1 else preview


def reencode(preview: Path, root: Path | None = None) -> str | None:
    """Replace `preview` with an 8-bit encode. Returns an error string or None.

    Refuses anything that is not structurally a proxy (see is_a_proxy) --
    this function overwrites its target, and the one thing it must never
    overwrite is an original.
    """
    if not is_a_proxy(preview):
        return (f"{preview}: REFUSED -- this is not inside a Proxy/ folder, so it "
                f"is an original, not a preview. Transcoding it would destroy the "
                f"archive's best copy of the clip")
    src = source_for(preview)
    tmp = preview.with_name(f".fix~{preview.name}")
    try:
        ffmpeg_tools.build_proxy(src, tmp)
        os.replace(tmp, preview)
    except Exception as exc:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return f"{preview}: {exc}"
    # Recorded so `build_archive.py --apply` does not copy the 10-bit source
    # back over it: it compared sizes, and a re-encode is a different size
    # (item 9, 2026-08-17). See broll_index/inplace_fixes.py.
    if root is not None:
        inplace_fixes.record(root, preview, note="R9 10-bit preview re-encoded")
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=DEFAULT_ROOT)
    ap.add_argument("--apply", action="store_true",
                    help="re-encode the offenders (default: report only)")
    ap.add_argument("--workers", type=int, default=2,
                    help="parallel re-encodes; consumer NVENC caps sessions, keep small")
    ap.add_argument("--limit", type=int, default=0,
                    help="stop after fixing N files (smoke-testing --apply)")
    args = ap.parse_args()
    root = Path(args.root)

    files = candidate_files(root)
    print(f"{len(files)} previews on disk; probing with {PROBE_WORKERS} workers…")

    hostile: list[Path] = []
    errors: list[str] = []
    with ThreadPoolExecutor(max_workers=PROBE_WORKERS) as pool:
        for (vid, path), info in zip(files, pool.map(lambda f: probe_pixels(f[1]), files)):
            if "error" in info:
                errors.append(f"{path}: {info['error']}")
            elif is_browser_hostile(info):
                hostile.append(path)

    # The refusal is reported in the DRY RUN as well as under --apply: a row
    # whose archive_path points at an original is a database problem, and the
    # operator has to see it before it is silently skipped (item 9,
    # 2026-08-17).
    eligible = [p for p in hostile if is_a_proxy(p)]
    not_proxies = [p for p in hostile if not is_a_proxy(p)]

    print(f"browser-hostile previews: {len(hostile)}")
    print(f"probe errors: {len(errors)}")
    for e in errors[:10]:
        print("  probe error:", e)
    if not_proxies:
        print(f"REFUSED (not inside a Proxy/ folder — these are originals, not "
              f"previews): {len(not_proxies)}")
        for p in not_proxies[:10]:
            print("  refused:", p.relative_to(root))
    if not args.apply:
        for p in eligible[:10]:
            print("  e.g.:", p.relative_to(root))
        if eligible:
            print("dry run — re-run with --apply to re-encode these.")
        return 0

    todo = eligible[: args.limit] if args.limit else eligible
    print(f"re-encoding {len(todo)} previews with {args.workers} workers…")
    failed: list[str] = []
    done = 0
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        for err in pool.map(lambda p: reencode(p, root), todo):
            done += 1
            if err:
                failed.append(err)
            if done % 50 == 0:
                print(f"  {done}/{len(todo)} ({len(failed)} failed)")
    print(f"done: {done - len(failed)} fixed, {len(failed)} failed")
    for f in failed[:20]:
        print("  FAILED:", f)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
