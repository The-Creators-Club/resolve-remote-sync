"""Build the portable input bundle for running the eval on another machine
(the Mac): the selected clips' frames (960x540 JPEGs) and contact sheets
(arm C), plus a clips.json whose frames_root is RELATIVE, so the bundle needs
nothing from E:\\broll-queue.

  bundle/
    clips.json          same as ../clips.json but "frames_root": "sheets"
    sheets/<id>/frames/frame_NNNN.jpg
    sheets/<id>/sheet_NNNN.jpg
  bundle.zip            the same, zipped (deflate — JPEGs barely shrink)

usage: python make_bundle.py [--clips clips.json] [--out bundle] [--zip bundle.zip] [--no-sheets]
"""
from __future__ import annotations

import argparse
import json
import shutil
import time
import zipfile
from pathlib import Path

from common import DEFAULT_CLIPS, HERE, frame_abs, load_clips


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clips", type=Path, default=DEFAULT_CLIPS)
    ap.add_argument("--out", type=Path, default=HERE / "bundle")
    ap.add_argument("--zip", type=Path, default=HERE / "bundle.zip")
    ap.add_argument("--no-sheets", action="store_true", help="frames only (drops arm C on the other machine)")
    ap.add_argument("--no-zip", action="store_true")
    args = ap.parse_args()

    doc = load_clips(args.clips)
    out = args.out
    if out.exists():
        shutil.rmtree(out)
    (out / "sheets").mkdir(parents=True)
    n_files = 0
    n_bytes = 0
    t0 = time.time()
    for c in doc["clips"]:
        rels = [f["path"] for f in c["frames"]] + ([] if args.no_sheets else list(c["sheets"]))
        for rel in rels:
            src = frame_abs(doc, rel)
            dst = out / "sheets" / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            n_files += 1
            n_bytes += dst.stat().st_size
    portable = {k: v for k, v in doc.items() if not k.startswith("_")}
    portable["frames_root"] = "sheets"
    portable["bundle_built_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    portable["bundle_source_frames_root"] = doc["frames_root"]
    if args.no_sheets:
        for c in portable["clips"]:
            c["sheets"] = []
    (out / "clips.json").write_text(json.dumps(portable, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"bundle: {len(doc['clips'])} clips, {n_files} files, {n_bytes/1e6:.0f} MB in {out} ({time.time()-t0:.0f}s)")
    if not args.no_zip:
        if args.zip.exists():
            args.zip.unlink()
        with zipfile.ZipFile(args.zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=1) as z:
            for p in sorted(out.rglob("*")):
                if p.is_file():
                    z.write(p, p.relative_to(out).as_posix())
        print(f"zip: {args.zip} {args.zip.stat().st_size/1e6:.0f} MB")


if __name__ == "__main__":
    main()
