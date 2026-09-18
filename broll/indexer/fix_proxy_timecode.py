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
import time
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
    """(verdict, wanted_tc): verdict in {fix, ok, no-source, source-no-tc}.

    "Has a timecode" is not the bar -- "carries the timecode Resolve will
    count for the source" is. Sony rtmd tags print colon (non-drop) forms
    for drop-frame material, and at 59.94 that is a different absolute frame,
    refused exactly like a missing timecode (measured live 2026-08-12), so
    every preview is compared against the DF-normalized source value and
    re-remuxed on any mismatch.
    """
    src = source_for(preview)
    if src is None:
        return "no-source", None
    src_tc, tc_from_tmcd = ffmpeg_tools.read_timecode_source(src)
    if not src_tc:
        return "source-no-tc", None
    try:
        fps = ffmpeg_tools.probe_video(src).get("fps")
    except Exception:
        fps = None
    # The tmcd flag travels with the value (audit F6, 2026-09-17), or this
    # repair tool would "fix" every genuinely non-drop 29.97 preview INTO the
    # semicolon form Resolve refuses -- the exact R17 case it exists to end.
    wanted = ffmpeg_tools.dropframe_normalized(src_tc, fps, tc_from_tmcd)
    if ffmpeg_tools.read_timecode(preview) == wanted:
        return "ok", None
    return "fix", wanted


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
    #
    # broll-indexer-5 (2026-09-18): the VALUE, not merely SOME timecode. Since
    # audit F6 the separator is the whole point of this tool - a colon and a
    # semicolon at the same numbers are different absolute frames, and writing
    # the wrong one is what makes Resolve refuse the proxy. `plan()` compares
    # `read_timecode(preview) == wanted` one function above, so the
    # post-condition was weaker than the precondition it closes: if ffmpeg
    # normalised the form on a given container, every file was reported
    # "fixed" and replaced while still carrying the form plan() rejected, the
    # next run re-planned all of them, and each run exited 0. The mp4 tmcd box
    # stores a drop-frame FLAG rather than a separator, which is exactly where
    # such a normalisation happens silently. Two distinguishable messages: a
    # DROPPED timecode and a REWRITTEN one are different faults.
    written = ffmpeg_tools.read_timecode(tmp)
    if not written or written != tc:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        if not written:
            return f"{preview}: remux dropped the timecode"
        return (f"{preview}: remux wrote {written}, not {tc} "
                f"(the container normalised it)")
    # Retried once: the web app (or a browsing editor's range request) can
    # hold an SMB read handle on exactly the preview being fixed, and Windows
    # answers os.replace with a sharing violation. One locked file must cost
    # that file, not the run -- the first --apply died here mid-pool
    # (WinError 32, 2026-08-12); a re-run skips already-fixed files, so
    # recording the failure and moving on converges.
    for attempt in (1, 2):
        try:
            os.replace(tmp, preview)
            return None
        except OSError as exc:
            if attempt == 2:
                try:
                    tmp.unlink(missing_ok=True)
                except OSError:
                    pass
                return f"{preview}: replace failed: {exc}"
            time.sleep(2.0)
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
    tallies = {"ok": 0, "no-source": 0, "source-no-tc": 0}
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
