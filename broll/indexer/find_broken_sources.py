"""List source files that cannot be read as media at all.

These are not pipeline failures — they are damaged files in the archive itself
(incomplete downloads, aborted copies). The pipeline correctly refuses them, but
the operator wants the LIST, because the fix is to re-download or re-copy the
source, and it is far cheaper to do that in one pass than to trip over them one
at a time.

    python find_broken_sources.py --config config.queue.yaml
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import sqlite3
import subprocess
import sys
from pathlib import Path

import yaml


def probe_error(path: Path) -> str | None:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if r.returncode == 0:
        return None
    err = (r.stderr or "").strip().splitlines()
    return err[0][:120] if err else f"rc={r.returncode}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.queue.yaml")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--out", default="broken_sources.md")
    args = ap.parse_args()

    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    roots = {k: Path(v["root"]) for k, v in cfg["shares"].items()}

    conn = sqlite3.connect(f"file:{cfg['db']['path']}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, share, rel_path, size_bytes FROM videos WHERE duplicate_of IS NULL"
    ).fetchall()
    conn.close()

    print(f"checking {len(rows)} source files with {args.workers} workers...", flush=True)

    def check(r):
        src = roots.get(r["share"], Path(".")) / r["rel_path"]
        if not src.is_file():
            return r, "MISSING from disk"
        return r, probe_error(src)

    broken = []
    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        for i, (r, err) in enumerate(ex.map(check, rows), 1):
            if err:
                broken.append((r, err))
                print(f"  [{r['id']}] {r['share']}: {err}", flush=True)
            if i % 500 == 0:
                print(f"  ...{i}/{len(rows)}", flush=True)

    out = Path(args.out)
    lines = [
        "# Unreadable source files",
        "",
        f"{len(broken)} of {len(rows)} source files cannot be read as media.",
        "These are damaged in the archive itself — re-download or re-copy them.",
        "",
    ]
    by_share: dict[str, list] = {}
    for r, err in broken:
        by_share.setdefault(r["share"], []).append((r, err))
    for share, items in sorted(by_share.items()):
        lines.append(f"## {share} ({len(items)})")
        lines.append("")
        for r, err in items:
            mb = (r["size_bytes"] or 0) / 1e6
            lines.append(f"- `{r['rel_path']}` ({mb:.0f} MB) — {err}")
        lines.append("")
    out.write_text("\n".join(lines), encoding="utf-8")

    print(f"\n{len(broken)} unreadable of {len(rows)}; wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
