"""Pick ~100 clips for the local-VLM eval and write clips.json.

Reads the indexer DB READ-ONLY (sqlite `mode=ro`), verifies that every clip's
extracted frames are still on disk under DATA_ROOT/sheets/<id>/frames/, and
stratifies:

  text       ~25  baseline has non-empty onscreen_text on >= 1 segment
  multishot  ~25  baseline has >= 5 segments
  simple     ~25  baseline has <= 2 segments
  random     ~25  anything eligible not already picked

The Haiku baseline (segments/themes/flags/category_hint/category) is copied
into clips.json so scoring — and the Mac run — need no DB at all.

usage: python select_clips.py [--db PATH] [--data-root PATH] [--per-stratum 25]
                              [--max-frames 45] [--seed 20260817] [--out clips.json]
"""
from __future__ import annotations

import argparse
import json
import random
import sqlite3
import time
from collections import Counter
from pathlib import Path

from common import DEFAULT_CLIPS, DEFAULT_DATA_ROOT, DEFAULT_DB, seconds_to_tc


def _ro(db: Path) -> sqlite3.Connection:
    c = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    return c


def _baseline(c: sqlite3.Connection, vid: int) -> dict:
    segs = [dict(r) for r in c.execute(
        "select t_start, t_end, description, objects, setting, motion, onscreen_text, "
        "onscreen_text_en from segments where video_id=? order by t_start, id", (vid,))]
    themes = [r[0] for r in c.execute("select text from themes where video_id=?", (vid,))]
    flags = [r[0] for r in c.execute("select flag from quality_flags where video_id=?", (vid,))]
    return {"segments": segs, "themes": themes, "quality_flags": flags}


def _frames_on_disk(data_root: Path, vid: int) -> tuple[list[dict], list[str]] | None:
    d = data_root / "sheets" / str(vid)
    meta = d / "frames.json"
    if not (d / "_complete").exists() or not meta.exists():
        return None
    try:
        m = json.loads(meta.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    ts = m.get("timestamps") or []
    frames = []
    for i, t in enumerate(ts):
        p = d / "frames" / f"frame_{i:04d}.jpg"
        if not p.is_file() or p.stat().st_size == 0:
            return None  # a partial frames dir is not usable: the F-table would lie
        frames.append({"i": i, "t": float(t), "tc": seconds_to_tc(t),
                       "path": f"{vid}/frames/frame_{i:04d}.jpg"})
    if not frames:
        return None
    sheets = []
    for s in m.get("sheets") or []:
        sp = Path(s)
        if sp.is_file():
            sheets.append(f"{vid}/{sp.name}")
    return frames, sheets


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    ap.add_argument("--per-stratum", type=int, default=25)
    ap.add_argument("--max-frames", type=int, default=45,
                    help="skip clips with more extracted frames than this (bounds the "
                         "overnight run: 9 frames per call, ~5 calls per clip at most)")
    ap.add_argument("--min-frames", type=int, default=2)
    ap.add_argument("--seed", type=int, default=20260817)
    ap.add_argument("--out", type=Path, default=DEFAULT_CLIPS)
    args = ap.parse_args()

    if not args.db.exists():
        raise SystemExit(f"DB not found: {args.db} (set --db or BROLL_DB_PATH)")
    c = _ro(args.db)
    taxonomy = [dict(r) for r in c.execute("select slug, label, description from categories order by slug")]

    rows = c.execute(
        "select v.id, v.share, v.rel_path, v.duration_s, v.width, v.height, v.model, "
        "v.category_hint, v.category, "
        "(select count(*) from segments s where s.video_id=v.id) as n_seg, "
        "(select count(*) from segments s where s.video_id=v.id and s.onscreen_text<>'') as n_text "
        "from videos v where v.model is not null and v.duplicate_of is null "
        "and v.status in ('indexed','sorted') and (select count(*) from segments s where s.video_id=v.id) > 0"
    ).fetchall()
    print(f"{len(rows)} indexed clips with Haiku segments in {args.db}")

    t0 = time.time()
    eligible = []
    n_no_frames = n_too_many = 0
    frame_hist: Counter = Counter()
    for r in rows:
        got = _frames_on_disk(args.data_root, r["id"])
        if got is None:
            n_no_frames += 1
            continue
        frames, sheets = got
        frame_hist[min(len(frames) // 9 * 9, 99)] += 1
        if len(frames) > args.max_frames or len(frames) < args.min_frames:
            n_too_many += 1
            continue
        eligible.append((r, frames, sheets))
    print(f"frames on disk verified in {time.time()-t0:.0f}s: {len(eligible)} eligible, "
          f"{n_no_frames} without complete frames, {n_too_many} outside [{args.min_frames},{args.max_frames}] frames")
    print("frame-count histogram (bucketed by 9, all clips with frames):",
          dict(sorted(frame_hist.items())))

    rng = random.Random(args.seed)
    rng.shuffle(eligible)
    picked: dict[int, str] = {}

    def take(pred, label):
        n = 0
        for r, _f, _s in eligible:
            if n >= args.per_stratum:
                break
            if r["id"] in picked or not pred(r):
                continue
            picked[r["id"]] = label
            n += 1
        return n

    n_text = take(lambda r: r["n_text"] > 0, "text")
    n_multi = take(lambda r: r["n_seg"] >= 5, "multishot")
    n_simple = take(lambda r: r["n_seg"] <= 2, "simple")
    n_rand = take(lambda r: True, "random")
    print(f"strata: text={n_text} multishot={n_multi} simple={n_simple} random={n_rand}")

    clips = []
    for r, frames, sheets in eligible:
        if r["id"] not in picked:
            continue
        clips.append({
            "id": r["id"], "share": r["share"], "rel_path": r["rel_path"],
            "duration_s": r["duration_s"], "width": r["width"], "height": r["height"],
            "stratum": picked[r["id"]],
            "frames": frames, "sheets": sheets,
            "baseline": {**_baseline(c, r["id"]), "category_hint": r["category_hint"],
                         "category": r["category"], "model": r["model"]},
        })
    clips.sort(key=lambda x: x["id"])
    doc = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "db": str(args.db), "frames_root": str(args.data_root / "sheets"),
        "seed": args.seed, "per_stratum": args.per_stratum, "max_frames": args.max_frames,
        "n_indexed": len(rows), "n_eligible": len(eligible), "n_without_frames": n_no_frames,
        "taxonomy": taxonomy,
        "clips": clips,
    }
    args.out.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    tot_frames = sum(len(x["frames"]) for x in clips)
    print(f"wrote {args.out}: {len(clips)} clips, {tot_frames} frames "
          f"({tot_frames/len(clips):.1f}/clip), {sum(len(x['sheets']) for x in clips)} sheets")


if __name__ == "__main__":
    main()
