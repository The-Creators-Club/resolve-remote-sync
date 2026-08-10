"""Turn DATA_ROOT/usage.jsonl into a forecast for a full archive run.

Answers the only question that matters before committing days of indexing:
what does one hour of footage actually cost, and how much of that is real
work versus per-call context overhead?

    python tools/cost_report.py E:/broll-data [--archive-hours 500]
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path


def load(data_root: Path) -> list[dict]:
    path = data_root / "usage.jsonl"
    if not path.exists():
        raise SystemExit(f"no usage log at {path} — run the claude stage with instrumentation first")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("data_root")
    ap.add_argument("--archive-hours", type=float, default=None,
                    help="forecast a full archive of this many hours of footage")
    args = ap.parse_args()

    records = load(Path(args.data_root))
    by_model: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        by_model[r.get("model", "?")].append(r)

    for model, rows in sorted(by_model.items()):
        # A video is billed once but appears in several rows (one per window).
        minutes = sum({r["video_id"]: (r.get("duration_s") or 0) for r in rows}.values()) / 60
        cost = sum(r.get("total_cost_usd") or 0 for r in rows)
        payload = sum(r.get("input_tokens") or 0 for r in rows)
        cache_new = sum(r.get("cache_creation_input_tokens") or 0 for r in rows)
        cache_read = sum(r.get("cache_read_input_tokens") or 0 for r in rows)
        out = sum(r.get("output_tokens") or 0 for r in rows)
        overhead = cache_new + cache_read
        wall_s = sum(r.get("duration_ms") or 0 for r in rows) / 1000

        print(f"\n=== {model} ===")
        print(f"  calls              {len(rows)}")
        print(f"  videos             {len({r['video_id'] for r in rows})}")
        print(f"  footage            {minutes:.1f} min")
        print(f"  wall clock         {wall_s/60:.1f} min of model time")
        print(f"  input (payload)    {payload:>12,}")
        print(f"  cache creation     {cache_new:>12,}")
        print(f"  cache read         {cache_read:>12,}")
        print(f"  output             {out:>12,}")
        if payload + overhead:
            print(f"  -> overhead is {overhead/(payload+overhead)*100:.1f}% of all input tokens")
        print(f"  cost               ${cost:.2f}")
        if minutes:
            per_min = cost / minutes
            print(f"  cost / clip-minute ${per_min:.4f}")
            print(f"  cost / clip-hour   ${per_min*60:.2f}")
            print(f"  speed              {minutes/(wall_s/60):.1f}x realtime" if wall_s else "")
            if args.archive_hours:
                print(f"  --> {args.archive_hours:g} h archive: ${per_min*60*args.archive_hours:,.0f}, "
                      f"~{args.archive_hours*60/(minutes/(wall_s/3600)):.0f} h of model time"
                      if wall_s else "")
        if len(rows) and overhead:
            print(f"  overhead per call  {overhead/len(rows):,.0f} tokens "
                  f"(amortized over {sum(r.get('n_sheets') or 0 for r in rows)/len(rows):.1f} sheets)")


if __name__ == "__main__":
    main()
