"""Build the shared b-roll archive tree that editors link against.

    python build_archive.py --config config.queue.yaml --dest "P:/Assets/B-roll Archive"
    python build_archive.py --config config.queue.yaml --dest ... --apply

Copies each clip's PROXY -- not its source -- into a browsable tree:

    <dest>/Downloads/<category>/<original name>.mp4
    <dest>/Creators_Club/<share>/<shoot dirs>/<original name>.mp4

Proxies, because that is what an editor can actually play and sync: sources are
scattered across five drives, are up to 20x the size, and are frequently codecs
no browser and no remote link can handle. The proxy is H.264, ~27 MB, and is
already the thing the search UI previews.

Original filenames, not `{video_id}.mp4`, because the path ends up in an
editor's timeline and in their media pool. `4127.mp4` tells them nothing.

Layout mirrors the folder browser exactly, so what an editor sees in search is
where the file actually is.

WHAT THIS DOES NOT DO: it never touches source footage, and it never deletes
anything at the destination. Re-running it adds what is missing and leaves the
rest alone, so it is safe to interrupt and resume -- which matters, because a
full build is ~60 GB.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sqlite3
import sys
import time
from pathlib import Path, PurePosixPath

from broll_index.config import load_config

DOWNLOADS = "Downloads"
CREATORS = "Creators_Club"
# Clips the model described but whose themes carry no subject at all (only
# format/place/look: "news broadcast", "daytime", "interior"). They are real
# footage and must be reachable, but inventing a subject folder for them would
# be a lie -- same posture as the folder browser's Uncategorised bucket.
UNCATEGORISED_DIR = "_uncategorised"
# Local stages done, model stage deliberately skipped (ShareConfig index:false).
ORGANISED = "organised"

_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


# Windows MAX_PATH is 260. Three clips failed the first build outright with
# WinError 123 because their CJK news headlines ran past it once the archive
# root and category folders were prepended. Cap the stem well short of it.
MAX_STEM = 90


def safe_name(name: str, cap: int = MAX_STEM) -> str:
    """A filename Windows will accept, without mangling CJK.

    The archive is full of Chinese titles and they must survive: only the
    characters Windows actually forbids are replaced. Over-long names are
    truncated rather than dropped -- a shortened title still identifies the
    clip, and the DB holds the full one.
    """
    cleaned = _UNSAFE.sub("_", name).rstrip(". ")
    if len(cleaned) > cap:
        cleaned = cleaned[:cap].rstrip(". ")
    return cleaned or "untitled"


# Every file here is a PROXY, and it goes in a `Proxy/` subfolder beside where
# its original would be. That is not just tidiness -- it is what makes the
# existing cc_sync machinery work on this tree with no changes at all:
#
#   * lane B (`build_filter_rules_down`) syncs exactly `**/Proxy/**` down to
#     editors, so archive proxies fan out through the pipe that already exists;
#   * lane A (`build_filter_rules_up`) EXCLUDES `**/Proxy/**`, so an editor can
#     never upload archive media back over the top of it;
#   * Resolve and `proxy_relink.expected_proxy_paths` both look for a proxy at
#     `<parent>/Proxy/<stem>.<ext>`, so a timeline pointing at the (absent)
#     original auto-links to the proxy — the documented MISSING steady state.
#
# The original slot stays empty by design: sources live on the archive drives
# and never come to the NAS.
PROXY_DIR = "Proxy"


def creator_shares(cfg) -> set[str]:
    """Shares that are our own shoots, and so file under Creators_Club/.

    The discriminator is `source: proxies` — the share whose Proxy/ .mov IS the
    archive copy. It is NOT `index: false`, which asks the unrelated question
    "do we pay a model to describe this?".

    Those two travelled together only by accident. MOFA was originally
    index:false on the assumption that describing our own footage was expensive;
    measured, it was not (one contact sheet, one call per clip), so it was
    flipped to indexed. Because the rule keyed off `index`, that flip silently
    re-routed every indexed MOFA clip out of Creators_Club/ and into
    Downloads/_uncategorised/ — own shoots have no category and never will, as
    they are organised by shoot/day/camera, which is how an editor looks for them.
    """
    return {n for n, s in cfg.shares.items() if s.source == "proxies"}


def dest_dir(video: dict, creators: set[str]) -> str:
    """The clip's folder in the archive, without a filename or Proxy/ level."""
    if video["share"] in creators:
        # Own shoots keep the structure they were captured in (day / camera).
        # The source's own Proxy/ component is dropped: in the archive that
        # level means "the preview", and the shoot's .mov is not the preview.
        parts = [p for p in PurePosixPath(video["rel_path"]).parent.parts
                 if p.lower() != "proxy"]
        sub = "/".join(safe_name(p) for p in parts)
        return f"{CREATORS}/{safe_name(video['share'])}/{sub}".replace("//", "/").rstrip("/")
    return f"{DOWNLOADS}/{video['category'] or UNCATEGORISED_DIR}"


def dest_rel(video: dict, creators: set[str], suffix: str = ".mp4", *,
             as_preview: bool = True) -> str:
    """Where this clip belongs in the archive, as a forward-slash relative path.

    ONE rule for both collections: the best available media sits in the folder,
    and the 540p preview sits in `Proxy/` beneath it.

        <folder>/<name>.<ext>          what Resolve imports and renders from
        <folder>/Proxy/<name>.mp4      what the browser plays and what syncs cheap

    For Downloads the top file is the actual original. For Creators_Club it is
    the shoot's own editor proxy -- which Resolve treats as the original, so the
    clip is ONLINE and renderable exactly like a download. Replacing it with the
    true camera file later is a deliberate, separate step, not a prerequisite
    for cutting.

    That uniformity is the point: no per-collection special case downstream, and
    no clip that can be cut but not exported.

    `suffix` follows the file actually being placed -- a `.mov` copied verbatim
    keeps its extension, because renaming it `.mp4` is a container lie that
    ffprobe, Resolve and every editor would eventually trip over.
    """
    stem = safe_name(PurePosixPath(video["rel_path"]).stem)
    folder = dest_dir(video, creators)
    return (f"{folder}/{PROXY_DIR}/{stem}{suffix}" if as_preview
            else f"{folder}/{stem}{suffix}")


def archive_source(video: dict, cfg, share_roots: dict[str, str],
                   proxies_dir: Path) -> Path | None:
    """The file to place in the archive for this clip, or None if not ready.

    On a `source: proxies` share the shoot's OWN proxy is used VERBATIM -- it
    is already a finished proxy, and re-encoding it would be a second
    generation of loss for no gain. The MOFA proxies are 1080p HEVC Main 10;
    the pipeline's own build_proxy would decode all of that and emit 540p
    H.264, throwing away half the resolution and all the 10-bit colour on
    footage we shot ourselves. Resolve plays HEVC natively, so nothing
    downstream needs the conversion.

    Everything else uses the generated proxy, because there the source is a
    full-size original (up to 20x bigger, often a codec no editor wants to cut
    against).
    """
    share_cfg = cfg.shares.get(video["share"])
    if share_cfg is not None and getattr(share_cfg, "source", "originals") == "proxies":
        root = share_roots.get(video["share"])
        if root:
            src = Path(root) / video["rel_path"]
            if src.is_file():
                return src
        return None
    # A download's top slot is its actual original. Measured on this
    # archive: 279 GB of originals against 614 GB of editor proxies for
    # the same clips -- these are YouTube files, already compressed, so a
    # 1080p 'proxy' of one is BIGGER than its own source.
    orig = video.get("original_path")
    if orig and Path(orig).is_file():
        return Path(orig)
    generated = proxies_dir / f"{video['id']}.mp4"
    return generated if generated.is_file() else None


def dedupe(path: Path, taken: set[str]) -> Path:
    """Resolve two clips wanting the same filename, deterministically.

    Collisions are settled against THIS run's claimed names only -- never
    against what is on disk. That distinction is the whole point: a file
    already at the target path is almost always this clip's own copy from an
    earlier run, and treating it as a collision renamed all 2,093 clips to
    `_2` on the second build.

    Because `videos` is walked in id order, the same clip resolves to the same
    name on every run. That stability is a requirement, not a nicety: the path
    is stored on the row and ends up in editors' timelines, so it must not move
    underneath them.
    """
    key = str(path).lower()
    if key not in taken:
        taken.add(key)
        return path
    n = 2
    while True:
        cand = path.with_name(f"{path.stem}_{n}{path.suffix}")
        if str(cand).lower() not in taken:
            taken.add(str(cand).lower())
            return cand
        n += 1


def eligible(db_path: str) -> list[dict]:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT id, share, rel_path, category, status, original_path FROM videos "
            "WHERE status IN ('indexed', ?) AND duplicate_of IS NULL ORDER BY id",
            (ORGANISED,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def write_paths(db_path: str, pairs: list[tuple[int, str]]) -> None:
    """Store each clip's archive-relative path so the web app can serve it.

    Stored rather than recomputed: the on-disk name is the product of filename
    sanitising, MAX_PATH truncation and collision de-duplication, and a second
    implementation of those rules in the web app would drift from this one.
    """
    conn = sqlite3.connect(db_path)
    try:
        conn.executemany("UPDATE videos SET archive_path = ? WHERE id = ?",
                         [(rel, vid) for vid, rel in pairs])
        conn.commit()
    finally:
        conn.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.queue.yaml")
    ap.add_argument("--dest", required=True, help=r'e.g. "P:/Assets/B-roll Archive"')
    ap.add_argument("--apply", action="store_true", help="without this, plan only")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    cfg = load_config(args.config)
    dest_root = Path(args.dest)
    proxies = cfg.data_root / "proxies"
    creators = creator_shares(cfg)

    videos = eligible(cfg.db.path)
    if args.limit:
        videos = videos[: args.limit]

    share_roots = {n: s.root for n, s in cfg.shares.items()}

    plan, missing = [], []
    taken: set[str] = set()
    for v in videos:
        # The TOP slot: the best media we have for this clip. For a download
        # that is the actual original; for our own shoots it is the shoot's
        # editor proxy, which Resolve treats as the original -- so the clip is
        # online and renderable either way, with no per-collection special case.
        top = archive_source(v, cfg, share_roots, proxies)
        if top is not None:
            plan.append((v, top, dedupe(
                dest_root / dest_rel(v, creators, top.suffix.lower(),
                                     as_preview=False), taken)))
        else:
            missing.append(v)

        # The PREVIEW: always the generated 540p H.264, always in Proxy/.
        preview = proxies / f"{v['id']}.mp4"
        if preview.is_file() and preview != top:
            plan.append((v, preview, dedupe(
                dest_root / dest_rel(v, creators, ".mp4", as_preview=True), taken)))

    total = sum(s.stat().st_size for _v, s, _d in plan)
    print(f"eligible videos : {len(videos)}")
    print(f"files to place  : {len(plan)}  ({total / 1024**3:.1f} GB)")
    if missing:
        print(f"NO proxy yet    : {len(missing)}  (not yet through the local stages)")

    if args.apply:
        # Record where every planned clip lives, INCLUDING ones already on disk
        # from an earlier run: the DB is what the web app serves from, so a
        # resumed or already-complete build must still leave every clip
        # addressable. Written before the copy so an interrupted run still
        # points at the files it did manage to place.
        # Only the preview (the file inside a Proxy/ dir) is the clip's
        # archive_path -- that is what the web app serves. The original
        # placed beside it is addressed by convention, not by column.
        write_paths(cfg.db.path, [
            (v["id"], d.relative_to(dest_root).as_posix())
            for v, _s, d in plan if d.parent.name == PROXY_DIR])
        print(f"recorded {len(plan)} archive path(s) in the database")

    todo = [(v, s, d) for v, s, d in plan
            if not d.exists() or d.stat().st_size != s.stat().st_size]
    todo_bytes = sum(s.stat().st_size for _v, s, _d in todo)
    print(f"to copy now     : {len(todo)}  ({todo_bytes / 1024**3:.1f} GB)")
    print(f"already present : {len(plan) - len(todo)}")

    if not args.apply:
        print("\n-- plan only, nothing copied. Sample:")
        for _v, _s, d in plan[:12]:
            print("   ", d.relative_to(dest_root))
        print("\nre-run with --apply to copy")
        return 0

    if not todo:
        print("\nnothing to do")
        return 0

    print(f"\ncopying to {dest_root} ...", flush=True)
    start = time.time()
    done = copied_bytes = 0
    for video, src, dst in todo:
        dst.parent.mkdir(parents=True, exist_ok=True)
        # Copy to a temp name then rename: an interrupted run must never leave
        # a half-file that looks complete to the next pass (it compares size).
        tmp = dst.with_suffix(dst.suffix + ".part")
        try:
            shutil.copy2(src, tmp)
            tmp.replace(dst)
        except Exception as e:  # noqa: BLE001 - one bad file must not stop 2,000
            print(f"  FAILED {dst.name}: {e}", flush=True)
            tmp.unlink(missing_ok=True)
            continue
        done += 1
        copied_bytes += src.stat().st_size
        if done % 25 == 0:
            el = time.time() - start
            rate = copied_bytes / el / 1024**2
            eta = (todo_bytes - copied_bytes) / (copied_bytes / el) / 60
            print(f"  [{done}/{len(todo)}] {copied_bytes/1024**3:.1f} GB  "
                  f"{rate:.0f} MB/s  eta {eta:.0f} min", flush=True)

    el = (time.time() - start) / 60
    print(f"\ncopied {done} file(s), {copied_bytes/1024**3:.1f} GB in {el:.1f} min")
    return 0


if __name__ == "__main__":
    sys.exit(main())
