"""Score an index through the REAL search endpoint, not the raw FTS tables.

`run_eval.py` queries the FTS tables directly, which measures only the keyword
half of the shipped system — no rank fusion, no semantic retrieval, no fuzzy
fallback. That understates (and can misattribute) real-world quality: a query
scored a miss there may be answered perfectly by the semantic side.

This runs the same query set through the web app's /api/search, so the number
reflects what an editor actually experiences.

    python eval/run_eval_api.py E:/broll-data/broll.db   # --queries defaults to DEFAULT_QUERIES below
    python eval/run_eval_api.py <db> --mode keyword    # isolate one half
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict
from pathlib import Path

import yaml

# Query sets are written against one site's real footage — the expectations are
# substrings of that customer's filenames and transcripts — so they live outside
# the tracked tree from 2026-08-17 (COMMERCIAL_READINESS.md item 10 / section B).
# Resolved from __file__ rather than the cwd, which used to decide whether the
# default found anything at all. Pass --queries for any other set, e.g.
# `--queries private/broll/eval/queries_archive.yaml` for the whole archive.
DEFAULT_QUERIES = str(
    Path(__file__).resolve().parents[2] / "private" / "broll" / "eval" / "queries_ff2.yaml"
)


def evaluate(db_path: Path, queries: list[dict], mode: str, fuzzy: bool) -> dict:
    # The app reads its DB location from the environment at import time.
    os.environ["BROLL_DATA_ROOT"] = str(db_path.parent)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "web"))

    from fastapi.testclient import TestClient

    from app.main import app  # noqa: E402

    results, guard_failures = [], 0
    with TestClient(app) as client:
        version = 0
        try:
            import sqlite3

            c = sqlite3.connect(str(db_path))
            version = c.execute("PRAGMA user_version").fetchone()[0]
            n_vid = c.execute("SELECT COUNT(*) FROM videos WHERE status='indexed'").fetchone()[0]
            n_emb = c.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
            c.close()
        except Exception:
            n_vid = n_emb = 0

        for spec in queries:
            q = spec["q"]
            r = client.get(
                "/api/search",
                params={"q": q, "mode": mode, "fuzzy": str(fuzzy).lower(), "limit": 50},
            )
            if r.status_code != 200:
                results.append({"q": q, "ok": False, "kind": "error",
                                "n": 0, "tags": spec.get("tags") or [],
                                "detail": f"HTTP {r.status_code}"})
                continue
            payload = r.json()
            # Match on "share/rel_path": rel_path is relative to the share root,
            # so the episode identifier (ff2-e1-yt, ff4-nuclear...) lives in the
            # share name and would otherwise be invisible to expectations.
            paths = {
                f"{res['video'].get('share', '')}/{res['video']['rel_path']}"
                for res in payload.get("results", [])
            }

            if spec.get("expect_none"):
                ok = not paths
                if not ok:
                    guard_failures += 1
                kind = "guard"
            else:
                wanted = spec.get("expect_any") or []
                ok = any(any(w in p for p in paths) for w in wanted)
                kind = "recall"
            results.append({"q": q, "ok": ok, "kind": kind, "n": len(paths),
                            "tags": spec.get("tags") or []})

    return {"db": str(db_path), "version": version, "videos": n_vid, "embeddings": n_emb,
            "mode": mode, "fuzzy": fuzzy, "results": results, "guard_failures": guard_failures}


def report(run: dict) -> None:
    recall = [r for r in run["results"] if r["kind"] == "recall"]
    guards = [r for r in run["results"] if r["kind"] == "guard"]
    hit = sum(1 for r in recall if r["ok"])

    print(f"\n=== {Path(run['db']).name}  mode={run['mode']} fuzzy={run['fuzzy']} "
          f"(schema v{run['version']}) ===")
    print(f"  {run['videos']} videos, {run['embeddings']} embeddings")
    if recall:
        print(f"  recall: {hit}/{len(recall)} ({hit/len(recall)*100:.0f}%)")
    print(f"  precision guards: {len(guards)-run['guard_failures']}/{len(guards)} clean")

    by_tag = defaultdict(list)
    for r in recall:
        for t in (r["tags"] or ["general"]):
            by_tag[t].append(r)
    for tag, rows in sorted(by_tag.items()):
        n = sum(1 for r in rows if r["ok"])
        print(f"    {tag:12} {n}/{len(rows)}")

    misses = [r for r in recall if not r["ok"]] + [r for r in guards if not r["ok"]]
    if misses:
        print("  misses:")
        for r in misses:
            label = "LEAK" if r["kind"] == "guard" else "MISS"
            print(f"    {label}  {r['q']!r} ({r['n']} videos returned)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("db")
    ap.add_argument("--queries", default=DEFAULT_QUERIES)
    ap.add_argument("--mode", default="hybrid", choices=["hybrid", "keyword", "semantic"])
    ap.add_argument("--no-fuzzy", action="store_true")
    args = ap.parse_args()

    queries = yaml.safe_load(Path(args.queries).read_text(encoding="utf-8"))["queries"]
    run = evaluate(Path(args.db), queries, args.mode, not args.no_fuzzy)
    report(run)
    sys.exit(1 if run["guard_failures"] else 0)


if __name__ == "__main__":
    main()
