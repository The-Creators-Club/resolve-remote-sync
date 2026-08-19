"""Encode editor-grade `Proxy/` files for own-shot footage that has none.

    python tools/make_own_proxies.py --root "Q:/FF2" --preset ff2          # dry run
    python tools/make_own_proxies.py --root "Q:/FF2" --preset ff2 --apply

WHY THIS EXISTS (2026-08-19). A `source: proxies` share archives the shoot's
own `Proxy/` file and leaves the camera original on the shoot drive -- that is
the whole "proxies on the NAS, never the originals" posture. But the scanner
only recognises a proxy by its PATH (`broll_index.scanner.PROXY_DIR_RE`), so a
project with no `Proxy/` folders indexes as nothing at all. FF2's older
episodes, the 2023 Disinformation backup and the 2022 WCT backup are all in
that state: 6,700 clips of our own footage that Resolve never made proxies for.
This walks such a tree and makes the missing half, so the share can then be
indexed exactly like ff3/ff4.

THE ENCODE SPEC IS NOT DEFINED HERE. It is imported verbatim from the
companion's `own_proxy_cmd` -- HEVC Main-10, 1080p, ~7 Mbit, `hvc1`, source
timecode and metadata carried over. Two reasons that import is worth the
sys.path poke: the flags encode hard-won constraints (the `hvc1` tag, the
`-f mp4` on a `.partial` name, `-map 0:a?` for dual-audio camera originals, the
10-bit pin against banding under a viewer LUT), and a proxy this tool makes
must cut identically to one the fleet's tray app makes. A second copy of the
spec would drift the first time one of them was tuned.

WHAT THIS NEVER DOES: it does not read, move, modify or delete a single source
file. It only ever creates `<dir>/Proxy/<stem>.mp4`, and it skips any clip that
already has one. Interrupting it is safe -- work in flight is written to
`.mp4.partial` and swapped into place only after the result has been proved to
decode, so a resumed run re-does at most the one clip that was mid-encode.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_INDEXER = _HERE.parent
_REPO = _INDEXER.parent.parent
sys.path.insert(0, str(_INDEXER))
sys.path.insert(0, str(_REPO / "companion" / "src"))

from broll_index import ffmpeg_tools  # noqa: E402
from broll_index.scanner import PROXY_DIR_RE  # noqa: E402
from ccsync_companion.ffmpeg_tools import own_proxy_cmd  # noqa: E402

VIDEO_EXTS = {".mp4", ".mov", ".mxf", ".mts", ".m4v", ".mkv", ".avi", ".m2ts"}
# Any of these beside the original counts as "already has a proxy". Resolve
# writes .mov, this tool writes .mp4, and a tree can hold both.
PROXY_EXTS = (".mov", ".mp4", ".mxf", ".mts")
PROXY_DIRNAME = "Proxy"

# Concurrent NVENC sessions on a consumer card silently emit damaged bitstreams
# rather than failing -- measured at 17% corruption under 6-way concurrency
# (broll_index/ffmpeg_tools.verify_decodes). Every output here is verified, so
# corruption is caught rather than shipped, but a default that provokes it just
# burns GPU time on retries. Two is the measured-safe number on this card.
DEFAULT_WORKERS = 2

# Directory patterns pruned before walking, per project. Graphics, renders and
# already-indexed download folders -- the same shape as the `exclude` lists the
# ff3/ff4 shares carry in config.queue.yaml, and kept here so the pre-pass and
# the scan agree on what the project's own footage is.
PRESETS: dict[str, list[str]] = {
    # Q:/FF2 -- the tree that used to be H:/FF2. Its three Youtube/Archive
    # folders are ALREADY indexed as the ff2-e1-yt / ff2-e24-birth /
    # ff2-e3-idols-ar shares; making proxies for them would put a second encode
    # of an already-archived download into the index, which content hashing
    # cannot catch (same footage, different bytes).
    "ff2": [
        "FF2 E1 - High Stakes/Youtube Downloads",
        "FF2 E2-4 - Birthrate/Youtube",
        "FF2 E3 - Idols/Archive",
        "*/AE",
        "*/Renders",
        "*/Resolve",
        "*/StoryToolkitAI",
        "*/Scripts",
        "*/Subs",
        "*/Audio",
        "*/VFX",
        "*/Multicams",
        # Voice-clone source takes for ElevenLabs, saved as .mov with an audio
        # stream and no video. Not footage, and not searchable as a shot.
        "*/Elevenlabs",
        "FF2 Shared Files",
        "Project Files",
        "Resolve Backups",
        "Subs",
    ],
    # R:/Project Backups/NAS Backup Projects-2023/Disinformation. E1..E5 are
    # the episode EDIT folders -- After Effects comps, renders and stock packs,
    # not footage. Footage/ and Interviews/ are the shoot.
    "disinfo": [
        "E1",
        "E2",
        "E3",
        "E5",
        # E4 is the one episode folder that also holds shoot material
        # (E4/Interviews), so it is pruned by part rather than whole.
        "E4/AE",
        "E4/Assets",
        "E4/Renders",
        "*/AE",
        "*/Renders",
        "*/Assets",
        "Davinci",
        "Branding",
        "Pitch Deck",
        "Storytoolkit",
        "Subs",
        "Audio",
        "Packs to Check Out",
        "Resolve Audio Captures",
    ],
    # R:/Project Backups/NAS Backup Projects-2022/2022/WCT Event Doc.
    # Footage/ is the whole shoot; everything else is post.
    "wct": [
        "AE",
        "Resolve",
        "Premiere",
        "Photoshop",
        "Images",
        "Audio",
        "Stock",
    ],
}


def is_excluded(rel_dir: str, patterns: list[str]) -> bool:
    """fnmatch `rel_dir` (forward slashes, relative to root) against `patterns`.

    Matches the semantics of `broll_index.scanner.is_excluded_dir` so this
    pre-pass and the scan that follows it prune the same subtrees. A pattern
    matches the directory itself or anything beneath it.
    """
    from fnmatch import fnmatch

    for pat in patterns:
        if fnmatch(rel_dir, pat) or rel_dir.startswith(pat.rstrip("/") + "/"):
            return True
        # `*/AE` should also catch a top-level `AE`, the way the ff3/ff4
        # exclude lists are read -- their `*` has no separator to match at the
        # root of the tree.
        if pat.startswith("*/") and fnmatch(rel_dir, pat[2:]):
            return True
        if pat.startswith("*/") and rel_dir.startswith(pat[2:] + "/"):
            return True
    return False


def existing_proxy(src: Path) -> Path | None:
    """The proxy already sitting beside `src`, or None."""
    pdir = src.parent / PROXY_DIRNAME
    if not pdir.is_dir():
        return None
    for ext in PROXY_EXTS:
        cand = pdir / (src.stem + ext)
        if cand.is_file() and cand.stat().st_size > 0:
            return cand
    return None


def find_candidates(root: Path, patterns: list[str]) -> list[Path]:
    """Own-footage files under `root` with no proxy beside them."""
    out: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = Path(dirpath).relative_to(root).as_posix()
        if rel_dir == ".":
            rel_dir = ""
        # Prune in place so os.walk never descends -- these trees are on
        # near-full spinning backup drives and a full walk is not cheap.
        dirnames[:] = [
            d for d in dirnames
            if not PROXY_DIR_RE.search(d)
            and not d.startswith(("@", "."))
            and not is_excluded(f"{rel_dir}/{d}".lstrip("/"), patterns)
        ]
        if rel_dir and is_excluded(rel_dir, patterns):
            continue
        for name in filenames:
            if Path(name).suffix.lower() not in VIDEO_EXTS:
                continue
            if name.startswith("._"):
                continue  # macOS AppleDouble junk, seen across these trees
            src = Path(dirpath) / name
            if existing_proxy(src) is None:
                out.append(src)
    return out


def long_path(p: Path) -> str:
    r"""Windows extended-length form for a path near MAX_PATH.

    These trees carry CJK news headlines as filenames and run to 275
    characters before `Proxy/` is inserted. ffmpeg accepts the `\\?\` prefix;
    without it the encode dies at fopen with a message that names no path.
    """
    s = str(p)
    if os.name == "nt" and len(s) > 240 and not s.startswith("\\\\?\\"):
        return "\\\\?\\" + str(p.resolve())
    return s


def encode_one(src: Path, cap_s: float, nvenc: bool, dry: bool) -> dict:
    """Probe, then encode one proxy. Returns a ledger record."""
    rec: dict = {"src": str(src), "status": "?"}
    try:
        info = ffmpeg_tools.probe_video(long_path(src))
    except Exception as e:  # noqa: BLE001 -- an unreadable source is data, not a crash
        rec.update(status="probe-failed", detail=str(e)[:200])
        return rec

    duration = info.get("duration_s") or 0.0
    rec["duration_s"] = duration
    if not duration:
        rec.update(status="no-duration")
        return rec

    # AUDIO IN A VIDEO CONTAINER. FF2's Elevenlabs/Input folders hold
    # voice-clone source takes saved as .mov with no video stream at all; ten of
    # them reached the encoder on the first pass and died on `-map 0:v:0`
    # ("Stream map '' matches no streams"), which reads like a broken encoder
    # rather than a file that was never footage. Caught here, at the probe we
    # already paid for, so the ledger says what is actually true.
    if not info.get("width") or not info.get("height"):
        rec.update(status="no-video-stream")
        return rec
    if cap_s and duration > cap_s:
        # The b-roll/interview discriminator, applied at the cheapest possible
        # place: a 40-minute A-cam take is dropped for the price of an ffprobe
        # rather than an encode. Same rule the shares' max_duration_s applies.
        rec.update(status="over-cap")
        return rec

    dest_dir = src.parent / PROXY_DIRNAME
    dest = dest_dir / (src.stem + ".mp4")
    rec["dest"] = str(dest)
    if dry:
        rec.update(status="would-encode")
        return rec

    dest_dir.mkdir(parents=True, exist_ok=True)
    partial = dest_dir / (src.stem + ".mp4.partial")

    timecode = None
    try:
        timecode = ffmpeg_tools.read_timecode(long_path(src))
        if timecode:
            timecode = ffmpeg_tools.dropframe_normalized(timecode, info.get("fps"))
    except Exception:  # noqa: BLE001 -- a proxy without timecode still beats no proxy
        timecode = None

    def _run(use_nvenc: bool) -> None:
        cmd = own_proxy_cmd(
            "ffmpeg", long_path(src), long_path(partial),
            nvenc=use_nvenc, timecode=timecode,
        )
        r = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
        if r.returncode != 0:
            raise RuntimeError(f"ffmpeg exited {r.returncode}: {(r.stderr or '').strip()[:300]}")

    def _bad() -> str | None:
        """Why the output is unusable, or None. Two independent failure modes.

        A damaged bitstream decodes with errors; a TRUNCATED file decodes
        cleanly and simply stops early, which passes an error check and then
        breaks anything that seeks past the cut. Both were seen on the b-roll
        archive, so both are checked.
        """
        errs = ffmpeg_tools.verify_decodes(long_path(partial))
        if errs > 0:
            return f"{errs} decode errors"
        try:
            got = ffmpeg_tools.probe_video(long_path(partial)).get("duration_s")
        except Exception:  # noqa: BLE001
            return None
        if got and got < duration * 0.97:
            return f"truncated: {got:.1f}s of {duration:.1f}s"
        return None

    try:
        _run(nvenc)
        reason = _bad()
        if reason and nvenc:
            # Fall back to libx265 for this one clip. Far slower, but a retry
            # on the same encoder that just produced a bad bitstream usually
            # produces another one.
            rec["nvenc_retry"] = reason
            partial.unlink(missing_ok=True)
            _run(False)
            reason = _bad()
        if reason:
            partial.unlink(missing_ok=True)
            rec.update(status="bad-output", detail=reason)
            return rec
    except Exception as e:  # noqa: BLE001 -- one clip's failure must not stop the run
        partial.unlink(missing_ok=True)
        rec.update(status="encode-failed", detail=str(e)[:300])
        return rec

    os.replace(partial, dest)
    rec.update(status="ok", bytes=dest.stat().st_size)
    return rec


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", required=True, help="project tree to walk")
    ap.add_argument("--preset", choices=sorted(PRESETS), help="exclude list to use")
    ap.add_argument("--exclude", action="append", default=[],
                    help="extra directory pattern to prune (repeatable)")
    ap.add_argument("--max-duration", type=float, default=300.0,
                    help="skip clips longer than this many seconds (0 = no cap)")
    ap.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    ap.add_argument("--apply", action="store_true", help="actually encode (default is a dry run)")
    ap.add_argument("--limit", type=int, default=0, help="stop after N clips (for a smoke test)")
    ap.add_argument("--ledger", default="", help="JSONL result log; defaults beside the root")
    args = ap.parse_args(argv)

    root = Path(args.root)
    if not root.is_dir():
        print(f"make_own_proxies: --root does not exist: {root}", file=sys.stderr)
        return 2
    patterns = list(PRESETS.get(args.preset, [])) + list(args.exclude)

    print(f"walking {root} ...")
    t0 = time.time()
    cands = find_candidates(root, patterns)
    print(f"  {len(cands)} clips with no proxy beside them ({time.time() - t0:.0f}s)")
    if args.limit:
        cands = cands[: args.limit]
        print(f"  limited to {len(cands)}")
    if not cands:
        return 0

    nvenc = ffmpeg_tools.detect_nvenc_available()
    print(f"  encoder: {'h264/hevc NVENC' if nvenc else 'libx265 (CPU)'}"
          f"   workers: {args.workers}   cap: {args.max_duration or 'none'}s")
    print(f"  mode: {'APPLY' if args.apply else 'DRY RUN'}")

    ledger_path = Path(args.ledger) if args.ledger else (
        _INDEXER / f"proxy-prepass-{args.preset or root.name}.jsonl")
    lock = threading.Lock()
    counts: dict[str, int] = {}
    total_bytes = 0
    done = 0

    with ledger_path.open("a", encoding="utf-8") as ledger, \
            cf.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(encode_one, c, args.max_duration, nvenc, not args.apply): c
                for c in cands}
        for fut in cf.as_completed(futs):
            rec = fut.result()
            with lock:
                done += 1
                counts[rec["status"]] = counts.get(rec["status"], 0) + 1
                total_bytes += rec.get("bytes", 0)
                ledger.write(json.dumps(rec, ensure_ascii=False) + "\n")
                ledger.flush()
                if done % 25 == 0 or done == len(cands):
                    el = time.time() - t0
                    rate = done / el * 60 if el else 0
                    print(f"  {done}/{len(cands)}  {rate:.1f}/min  "
                          f"{total_bytes / 1073741824:.1f} GB  {counts}")

    print("\nsummary:")
    for k in sorted(counts):
        print(f"  {k:<16} {counts[k]}")
    print(f"  proxies written  {total_bytes / 1073741824:.1f} GB")
    print(f"  ledger           {ledger_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
