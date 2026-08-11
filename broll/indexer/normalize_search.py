"""Populate `search_norm` for transcripts and segments.

This is the keyword half of CJK search: jieba word-segmentation plus OpenCC
script conversion, stored alongside the raw text so FTS can match a 2-character
term like 堵車 or 檢調 (below trigram's 3-char floor, and not a standalone token
inside unbroken Chinese prose) and so a Traditional query finds Simplified
source text.

Separate from the `embed` stage because it needs no model and no GPU — pure
text processing — so it can run while the local pipeline is busy, and makes
Chinese searchable immediately rather than waiting on embeddings.

    python normalize_search.py --config config.queue.yaml
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from pathlib import Path

import yaml

from broll_index import normalize
from broll_index.storage.sqlite_backend import bump_search_generation


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.queue.yaml")
    ap.add_argument("--batch", type=int, default=500)
    args = ap.parse_args()

    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    db_path = cfg["db"]["path"]

    conn = sqlite3.connect(db_path, timeout=60)
    conn.row_factory = sqlite3.Row
    # Long-running writer alongside the pipeline; WAL + a busy timeout keeps
    # both sides from tripping over each other.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=60000")

    total = 0
    for table, fields in (
        ("transcript_segments", ("text",)),
        ("segments", ("description", "objects", "setting", "onscreen_text", "onscreen_text_en")),
    ):
        cols = ", ".join(fields)
        rows = conn.execute(
            f"SELECT id, {cols} FROM {table} WHERE search_norm = ''"
        ).fetchall()
        print(f"{table}: {len(rows)} rows need normalizing", flush=True)
        if not rows:
            continue

        t0 = time.time()
        batch: list[tuple[str, int]] = []
        for i, r in enumerate(rows, 1):
            raw = " ".join(str(r[f]) for f in fields if r[f])
            batch.append((normalize.searchable_blob(raw), r["id"]))
            if len(batch) >= args.batch or i == len(rows):
                conn.executemany(
                    f"UPDATE {table} SET search_norm = ? WHERE id = ?", batch
                )
                # search_norm feeds the typo-correction vocabulary, and an
                # UPDATE moves neither the row count nor the high-water mark
                # that cache also keys on (KNOWN_BUGS R2).
                bump_search_generation(conn)
                conn.commit()
                total += len(batch)
                batch = []
                rate = i / max(1e-9, time.time() - t0)
                print(f"  {i}/{len(rows)}  {rate:.0f}/s", flush=True)

    print(f"\nnormalized {total} rows")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
