"""Generate semantic vectors for transcript cues.

Splits the embedding work the same way normalize_search.py splits the keyword
work: transcripts are already on disk, so their vectors can be built before the
visual index exists. That makes cross-lingual semantic search over SPEECH
available immediately — English "police raid" reaching Mandarin dialogue — and
proves the embed path at real scale before it has to run over ~35k visual
segments after the indexing pass.

    python embed_transcripts.py --config config.queue.yaml
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from pathlib import Path

import yaml

from broll_index import embed as embed_mod


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.queue.yaml")
    ap.add_argument("--batch", type=int, default=256)
    args = ap.parse_args()

    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    db_path = cfg["db"]["path"]
    model_name = (cfg.get("embedding") or {}).get(
        "model", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    )

    conn = sqlite3.connect(db_path, timeout=120)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=120000")

    rows = conn.execute(
        "SELECT t.id, t.video_id, t.text FROM transcript_segments t "
        "LEFT JOIN embeddings e ON e.source='transcript' AND e.source_id=t.id "
        "AND e.model=? WHERE e.source_id IS NULL AND t.text != ''",
        (model_name,),
    ).fetchall()
    print(f"{len(rows)} transcript cues need embedding ({model_name})", flush=True)
    if not rows:
        return 0

    t0 = time.time()
    done = 0
    for start in range(0, len(rows), args.batch):
        chunk = rows[start : start + args.batch]
        vecs = embed_mod.embed_texts([r["text"] for r in chunk], model_name)
        dim = int(vecs.shape[1])
        conn.executemany(
            "INSERT OR REPLACE INTO embeddings "
            "(source, source_id, video_id, model, dim, vec) "
            "VALUES ('transcript', ?, ?, ?, ?, ?)",
            [
                (r["id"], r["video_id"], model_name, dim, embed_mod.to_blob(vecs[i]))
                for i, r in enumerate(chunk)
            ],
        )
        conn.commit()
        done += len(chunk)
        el = time.time() - t0
        print(f"  {done}/{len(rows)}  {done/max(el,1e-9):.0f}/s", flush=True)

    print(f"\nembedded {done} cues in {(time.time()-t0)/60:.1f} min")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
