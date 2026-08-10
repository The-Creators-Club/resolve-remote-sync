"""What did the overnight run actually produce? One command, run it after.

Reports coverage, cost, quality signals and a search comparison against the
pre-indexing baseline recorded in OVERNIGHT.md, so the result is measured
rather than eyeballed.

    python morning_report.py
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import sys
from collections import Counter
from pathlib import Path

DB = r"E:\broll-queue\broll.db"
DATA = Path(r"E:\broll-queue")
REPO = Path(__file__).parent

# Recorded before any visual indexing — see OVERNIGHT.md.
BASELINE = {"recall": "19/20", "guards": "4/5"}


def main() -> int:
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    print("=" * 62)
    print("OVERNIGHT RUN REPORT")
    print("=" * 62)

    counts = dict(conn.execute("SELECT status, COUNT(1) FROM videos GROUP BY status").fetchall())
    eligible = sum(v for k, v in counts.items() if k != "skipped")
    indexed = counts.get("indexed", 0) + counts.get("sorted", 0)
    print(f"\nCOVERAGE  {indexed}/{eligible} indexed"
          f"   ({indexed/eligible*100:.0f}%)" if eligible else "")
    for k, v in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"    {k:<12} {v}")

    seg = conn.execute("SELECT COUNT(1) FROM segments").fetchone()[0]
    ost = conn.execute("SELECT COUNT(1) FROM segments WHERE onscreen_text != ''").fetchone()[0]
    cues = conn.execute("SELECT COUNT(1) FROM transcript_segments").fetchone()[0]
    emb = conn.execute("SELECT COUNT(1) FROM embeddings").fetchone()[0]
    print(f"\nINDEX     {seg} visual segments ({ost} with on-screen text)")
    print(f"          {cues} transcript cues, {emb} embeddings")

    # No-visual labels: the canonical ones should be present and consistent.
    labels = Counter(
        r[0] for r in conn.execute(
            "SELECT description FROM segments WHERE length(description) < 20"
        ) if r[0] in ("newsreader", "title card", "black frame", "colour bars", "station ident")
    )
    if labels:
        print(f"\nLABELS    {dict(labels)}")

    # Cost, from the instrumented usage log.
    usage = DATA / "usage.jsonl"
    if usage.exists():
        rows = [json.loads(l) for l in usage.read_text(encoding="utf-8").splitlines() if l.strip()]
        if rows:
            calls = len(rows)
            out_tok = sum(r.get("output_tokens", 0) for r in rows)
            cache = sum(r.get("cache_read_input_tokens", 0)
                        + r.get("cache_creation_input_tokens", 0) for r in rows)
            payload = sum(r.get("input_tokens", 0) for r in rows)
            print(f"\nMODEL     {calls} calls")
            print(f"          payload {payload:,} / overhead {cache:,} tokens"
                  f"  ({cache/(payload+cache)*100:.0f}% overhead)" if payload + cache else "")
            print(f"          output {out_tok:,} tokens")

    errs = conn.execute(
        "SELECT id, substr(rel_path,1,44) p, substr(error,1,90) e FROM videos WHERE status='error'"
    ).fetchall()
    print(f"\nERRORS    {len(errs)}")
    for r in errs[:10]:
        print(f"    [{r['id']}] {r['p']}")
        print(f"          {r['e']}")

    free = shutil.disk_usage("E:\\").free / 1e9
    print(f"\nDISK      {free:.0f} GB free")

    print("\n" + "=" * 62)
    print(f"SEARCH QUALITY (baseline before indexing: recall {BASELINE['recall']}, "
          f"guards {BASELINE['guards']})")
    print("=" * 62)
    conn.close()

    sys.stdout.flush()  # subprocess writes directly; flush ours first
    py = REPO / "web" / ".venv" / "Scripts" / "python.exe"
    subprocess.run(
        [str(py), str(REPO / "eval" / "run_eval_api.py"), DB,
         "--queries", str(REPO / "eval" / "queries_archive.yaml")],
        cwd=str(REPO),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
