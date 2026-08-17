"""Build the shared b-roll archive tree that editors link against.

    python build_archive.py --dest "P:/Assets/B-roll Archive"
    python build_archive.py --dest ... --apply
    # --config defaults to private/broll/indexer/config.queue.yaml

Copies each clip's media into a browsable tree, plus the two stills the search
UI previews it with:

    <dest>/Downloads/<category>/<original name>.mp4
    <dest>/Creators_Club/<share>/<shoot dirs>/<original name>.mp4
    <dest>/posters/<video id>.jpg
    <dest>/sprites/<video id>.jpg

Proxies, because that is what an editor can actually play and sync: sources are
scattered across five drives, are up to 20x the size, and are frequently codecs
no browser and no remote link can handle. The proxy is H.264, ~27 MB, and is
already the thing the search UI previews.

Posters and sprites because the deployed site's DATA_ROOT *is* this archive
root: it serves `media/poster/{id}.jpg` from `<DATA_ROOT>/posters` and
`media/sprite/{id}.jpg` from `<DATA_ROOT>/sprites`. Until 2026-08-10 this
script shipped media only and the two JPEG folders were copied by hand, so
every clip whose pair was missed showed a "no preview" placeholder on a site
that had indexed it perfectly.

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

from broll_index import inplace_fixes
from broll_index.config import load_config
from broll_index.site_data import DEFAULT_QUEUE_CONFIG

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

# The stills are addressed by ID, never browsed by name -- the exact opposite of
# the media above, which ends up in an editor's timeline. So they keep the
# indexer's own data_root layout (`posters/{video_id}.jpg`, `sprites/...`),
# because that layout IS the web app's contract: on the NAS the archive root and
# the site's DATA_ROOT are the same directory, and routes_media.py looks them up
# there by id. Putting them beside the clip would be tidier and completely
# invisible to the thing that has to read them.
POSTER_DIR = "posters"
SPRITE_DIR = "sprites"
STILL_DIRS = (POSTER_DIR, SPRITE_DIR)


def still_pairs(video: dict, data_root: Path, dest_root: Path
                ) -> tuple[list[tuple[Path, Path]], list[str]]:
    """This clip's (poster, sprite) copy jobs, and which of the two are absent.

    A missing still is a COUNTED SKIP, never an abort. They are produced by the
    pipeline's stage_proxy, so a clip whose ffmpeg run failed on a broken stream
    -- or one indexed before that stage existed -- has no pair on disk and never
    will until it is re-run. Its media is still worth shipping, and refusing to
    build a 60 GB archive over a 40 KB thumbnail would be the wrong trade.
    """
    found, missing = [], []
    for kind in STILL_DIRS:
        src = data_root / kind / f"{video['id']}.jpg"
        if src.is_file():
            found.append((src, dest_root / kind / f"{video['id']}.jpg"))
        else:
            missing.append(kind)
    return found, missing


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
             as_preview: bool = True, stem: str | None = None) -> str:
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

    `stem` overrides the name derived from the source file: main() passes the
    one this clip already holds (see claim_name), so the top slot and the
    preview beneath it always share a name and neither moves between runs.
    """
    stem = stem or safe_name(PurePosixPath(video["rel_path"]).stem)
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


def preview_source(video: dict, top: Path | None, proxies_dir: Path) -> Path | None:
    """The file that belongs in this clip's `Proxy/` folder, or None.

    Normally the generated 540p H.264. Two cases used to fall through it and
    leave the clip with nothing under `Proxy/` at all — which matters more than
    the missing file suggests, because only a file there is recorded as the
    row's `archive_path` (what the web app plays) and only `**/Proxy/**` is what
    lane B syncs to editors:

      * the generated proxy IS the top slot (a Downloads share whose
        `original_path` has not been resolved yet, or whose originals drive is
        unmounted). The old `preview != top` guard skipped the copy as
        redundant; two copies of a ~27 MB proxy is the cheaper mistake
        (BROLL-6, 2026-08-11);
      * an audio-only clip has no generated proxy at all — stage_proxy never
        runs, there being no video stream to encode — yet its speech is
        transcribed and searchable, so search returns it and the player 404s.
        Its source is a small audio file, so it stands in as its own preview
        (BROLL-14, 2026-08-11).
    """
    generated = proxies_dir / f"{video['id']}.mp4"
    if generated.is_file():
        return generated
    if top is not None and video.get("status") == "skipped":
        return top
    return None


def claim_key(folder: str, stem: str) -> str:
    """The name two clips contend for: a folder and a stem, extension aside.

    Claimed per stem rather than per full path so a clip's top slot and the
    preview under `Proxy/` always resolve to the SAME name. Keying on the whole
    path let them diverge whenever the two files had different extensions --
    `<folder>/name.mov` (base name free) beside `<folder>/Proxy/name_2.mp4`
    (taken) -- which is how a newcomer could still land on top of an already
    published clip's original (BROLL-IDX-5, 2026-08-14).
    """
    return f"{folder}/{stem}".lower()


def published_names(db_path: str) -> dict[int, tuple[str, str]]:
    """{video id: (folder, stem)} for every clip that already has an archive path.

    Read from the DB, not from this run's plan: the rows that make a name unsafe
    to re-derive are precisely the ones the current run may not select (see
    claim_name).
    """
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT id, archive_path FROM videos WHERE archive_path IS NOT NULL "
            "AND archive_path <> ''"
        ).fetchall()
    finally:
        conn.close()
    out: dict[int, tuple[str, str]] = {}
    for vid, rel in rows:
        p = PurePosixPath(rel)
        parent = p.parent
        # The stored path is the PREVIEW, i.e. <folder>/Proxy/<stem>.<ext>; the
        # name is contended for at <folder> level.
        if parent.name == PROXY_DIR:
            parent = parent.parent
        out[int(vid)] = (str(parent), p.stem)
    return out


def claim_name(folder: str, stem: str, taken: set[str], *,
               published: tuple[str, str] | None = None) -> str:
    """This clip's name in `folder`, suffixed `_2`.. only if it must be.

    Collisions are settled against claimed names, never against what is on disk.
    That distinction is the whole point: a file already at the target path is
    almost always this clip's own copy from an earlier run, and treating it as a
    collision renamed all 2,093 clips to `_2` on the second build.

    A clip that already HOLDS a name keeps it, unconditionally. The old rule was
    "walk `videos` in id order and the same clip resolves to the same name every
    run", which only holds while the eligible set grows at the tail -- and it
    does not: a 'discovered' or 'error' row re-run to 'indexed', or a Downloads
    row that finally gets a category (the BROLL-7 carve-out), joins at its own
    low id. It then claimed the base name, every later colliding clip shifted by
    one, write_paths rewrote their `archive_path`, and the copy loop wrote the
    newcomer's bytes over a file already recorded on another row, already served
    by the web app and already cut into editors' timelines (BROLL-IDX-5,
    2026-08-14). main() seeds `taken` from every published name for the same
    reason, so a newcomer cannot claim one even when its owner is not in this
    run's plan.
    """
    if published is not None:
        # Its own claim, already registered by the seed. Honoured even if the
        # folder has since changed (a Downloads clip categorised after it
        # shipped): moving a clip between folders is a deliberate re-file, but
        # its NAME must not change under the editors who already linked it.
        taken.add(claim_key(folder, published[1]))
        return published[1]
    if claim_key(folder, stem) not in taken:
        taken.add(claim_key(folder, stem))
        return stem
    n = 2
    while True:
        cand = f"{stem}_{n}"
        if claim_key(folder, cand) not in taken:
            taken.add(claim_key(folder, cand))
            return cand
        n += 1


def eligible(db_path: str, creators: set[str] | None = None) -> list[dict]:
    """Everything whose local stages are done: indexed, organised, or proxied.

    'proxied' joined 2026-08-10 (shipping ff3 ahead of its overnight claude
    run): the archive serves exactly what the proxy stage produced -- the
    proxy, the poster, the sprite -- and none of that changes when the model
    later describes the clip. An editor browsing their own shoot should not
    wait days for a model queue to see footage that is already playable.
    Media placement is additive and idempotent, so a clip shipped at
    'proxied' is simply already in place when it reaches 'indexed'.

    That idempotence is only true where the destination does not depend on
    something the model is about to change. For a Creators_Club share it never
    does (the path is the shoot's own folders); for a Downloads share it is
    `videos.category`, which is NULL at 'proxied' and set at 'indexed' -- so
    such a clip is filed under _uncategorised, then filed AGAIN under its real
    subject on the next build, with the first copy stranded (nothing here ever
    deletes) and dedupe's name claims shifted underneath everyone (BROLL-7,
    2026-08-11). Those rows wait for the model pass instead. `creators` is what
    tells the two apart; passing None keeps every eligible row, for callers with
    no config to hand.

    Audio-only clips are 'skipped' but belong here (BROLL-14, 2026-08-11):
    stage_probe parks them there because there is nothing to SEE, while their
    speech is transcribed and fully searchable -- so search returns them and,
    unless their media is shipped, the player 404s on the clip search just
    found. They are told apart from the scanner's own 'skipped' rows (editor
    proxy folders -- 2,100 files, 660 GB, deliberately excluded) by having been
    probed at all: a duration but no video codec.
    """
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT id, share, rel_path, category, status, codec, duration_s, "
            "original_path FROM videos "
            "WHERE (status IN ('indexed', 'proxied', ?) "
            "       OR (status = 'skipped' AND codec IS NULL "
            "           AND duration_s IS NOT NULL)) "
            "AND duplicate_of IS NULL ORDER BY id",
            (ORGANISED,),
        ).fetchall()
        videos = [dict(r) for r in rows]
        if creators is None:
            return videos
        return [
            v for v in videos
            if not (v["status"] == "proxied" and v["category"] is None
                    and v["share"] not in creators)
        ]
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


# mtimes are compared with a tolerance: shutil.copy2 preserves them, but SMB,
# exFAT and FAT round to 1-2 s, so an exact comparison would call every file
# on the NAS share "different" and re-copy 60 GB on every run.
MTIME_TOLERANCE_SECONDS = 2.0


def needs_copy(src: Path, dst: Path) -> bool:
    """Does `dst` still need to be (re)placed from `src`?

    Size alone was the whole test until 2026-08-17, and it is both too weak
    (a truncated copy that happens to match, a different clip of the same
    length) and, paired with the in-place repair path, actively destructive
    (COMMERCIAL_READINESS.md item 9 -- see the `protected` list in main()).

    The ladder is cheap-first: absent, then size, then mtime (copy2 preserves
    it, so a faithful copy agrees), and only when size agrees but mtime does
    not is a quick head+tail hash read -- two seeks, not a full 60 GB pass.
    """
    try:
        if not dst.exists():
            return True
        d_stat, s_stat = dst.stat(), src.stat()
        if d_stat.st_size != s_stat.st_size:
            return True
        if abs(d_stat.st_mtime - s_stat.st_mtime) <= MTIME_TOLERANCE_SECONDS:
            return False
        return inplace_fixes.quick_hash(dst) != inplace_fixes.quick_hash(src)
    except OSError:
        # Cannot tell: copying again is additive and reversible (the old copy
        # goes to the trash), so it is the safe side of the doubt.
        return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=DEFAULT_QUEUE_CONFIG)
    ap.add_argument("--dest", required=True, help=r'e.g. "P:/Assets/B-roll Archive"')
    ap.add_argument("--apply", action="store_true", help="without this, plan only")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    cfg = load_config(args.config)
    dest_root = Path(args.dest)
    proxies = cfg.data_root / "proxies"
    creators = creator_shares(cfg)

    videos = eligible(cfg.db.path, creators)
    if args.limit:
        videos = videos[: args.limit]

    share_roots = {n: s.root for n, s in cfg.shares.items()}

    plan, missing = [], []
    # Every name any clip already holds, claimed before a single new one is
    # handed out -- including clips this run will not even look at (BROLL-IDX-5).
    published = published_names(cfg.db.path)
    taken: set[str] = {claim_key(folder, stem) for folder, stem in published.values()}
    stills_planned = {kind: 0 for kind in STILL_DIRS}
    no_still = {kind: 0 for kind in STILL_DIRS}
    for v in videos:
        # One name per clip, used by both slots below, so they can never diverge.
        name = claim_name(dest_dir(v, creators),
                          safe_name(PurePosixPath(v["rel_path"]).stem),
                          taken, published=published.get(v["id"]))

        # The TOP slot: the best media we have for this clip. For a download
        # that is the actual original; for our own shoots it is the shoot's
        # editor proxy, which Resolve treats as the original -- so the clip is
        # online and renderable either way, with no per-collection special case.
        top = archive_source(v, cfg, share_roots, proxies)
        if top is not None:
            plan.append((v, top, dest_root / dest_rel(
                v, creators, top.suffix.lower(), as_preview=False, stem=name)))
        else:
            missing.append(v)

        # The PREVIEW: what goes in Proxy/, which is what the site plays and
        # what lane B syncs. See preview_source for the two cases that used to
        # leave a clip with nothing there.
        preview = preview_source(v, top, proxies)
        if preview is not None:
            plan.append((v, preview, dest_root / dest_rel(
                v, creators, preview.suffix.lower(), as_preview=True, stem=name)))

        # The STILLS: poster and sprite, by id, in flat top-level folders. Not
        # run through dedupe() -- `{video_id}.jpg` cannot collide, and passing
        # them through would only pollute the names the media contends for.
        stills, gaps = still_pairs(v, cfg.data_root, dest_root)
        plan.extend((v, s, d) for s, d in stills)
        for kind in STILL_DIRS:
            if kind in gaps:
                no_still[kind] += 1
            else:
                stills_planned[kind] += 1

    total = sum(s.stat().st_size for _v, s, _d in plan)
    print(f"eligible videos : {len(videos)}")
    print(f"files to place  : {len(plan)}  ({total / 1024**3:.1f} GB)")
    print(f"  media         : {len(plan) - sum(stills_planned.values())}")
    for kind in STILL_DIRS:
        # A gap here is not fatal, but it IS the "no preview" placeholder on the
        # live site, so it gets its own line rather than a silent shortfall.
        gap = (f"   ({no_still[kind]} clip(s) have none -- 'no preview' on the site)"
               if no_still[kind] else "")
        print(f"  {kind:<14}: {stills_planned[kind]}{gap}")
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
        recorded = [(v["id"], d.relative_to(dest_root).as_posix())
                    for v, _s, d in plan if d.parent.name == PROXY_DIR]
        write_paths(cfg.db.path, recorded)
        print(f"recorded {len(recorded)} archive path(s) in the database")

    # WHAT STILL NEEDS COPYING. Size alone used to decide this, and size is
    # not identity: `fix_10bit_proxies.py --apply` re-encodes a preview in
    # place (KNOWN_BUGS R9), which changes its size, so every repaired file
    # looked un-copied and the next build put the 10-bit source back over it
    # -- undoing the repair silently, on every clip, every run
    # (COMMERCIAL_READINESS.md item 9, 2026-08-17). A destination recorded in
    # the in-place-fix manifest AND still hashing to what was recorded is
    # deliberately not a byte-copy of its source, and is left alone.
    fixed = inplace_fixes.load(dest_root)
    protected = [(v, s, d) for v, s, d in plan
                 if d.exists() and inplace_fixes.is_fixed(dest_root, d, fixed)]
    protected_dests = {str(d) for _v, _s, d in protected}
    todo = [(v, s, d) for v, s, d in plan
            if str(d) not in protected_dests and needs_copy(s, d)]
    todo_bytes = sum(s.stat().st_size for _v, s, _d in todo)
    print(f"to copy now     : {len(todo)}  ({todo_bytes / 1024**3:.1f} GB)")
    print(f"already present : {len(plan) - len(todo) - len(protected)}")
    if protected:
        print(f"repaired in place: {len(protected)}  (left alone — see "
              f"{inplace_fixes.MANIFEST_NAME})")

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
            # Anything already under the final name goes to the archive's
            # trash first, never straight under the wheels: this loop is the
            # only place in the pipeline that overwrites a file somebody may
            # have repaired, re-cut or hand-placed, and until 2026-08-17 an
            # overwrite here was unrecoverable (item 9). The trash is never
            # swept automatically -- the operator empties it.
            if dst.exists():
                kept = inplace_fixes.stash(dest_root, dst)
                print(f"  replacing {dst.name} (old copy kept at {kept})", flush=True)
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
