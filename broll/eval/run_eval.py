"""Score a b-roll index against a query set.

Runs each query directly against the SQLite FTS tables (no web app needed) and
reports recall, precision guards, and per-tag breakdowns. Use it to compare two
indexes fairly — v1 vs v2 prompt, or Haiku vs Sonnet — since the query set is
fixed and written from an editor's point of view rather than from the index.

    python eval/run_eval.py E:/broll-data/broll.db --queries eval/queries_ff2.yaml
    python eval/run_eval.py a.db b.db --queries eval/queries_ff2.yaml   # compare

Exit code is non-zero if any precision guard fails (a query expected to return
nothing returned something), because that is a correctness bug rather than a
quality score.
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from pathlib import Path

import yaml

_TOKEN_RE = re.compile(r'"([^"]*)"|(\S+)')


def sanitize(raw: str) -> str | None:
    """Mirror of the web app's FTS sanitizer: quote every term, AND them."""
    terms = []
    for m in _TOKEN_RE.finditer(raw.strip()):
        text = (m.group(1) if m.group(1) is not None else m.group(2)).strip()
        if text:
            terms.append(text)
    if not terms:
        return None
    return " AND ".join('"' + t.replace('"', '""') + '"' for t in terms)


def has_table(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ?", (name,)
    ).fetchone() is not None


# (fts table, base table, join column) — every place a query can match.
# Transcript tables only exist at schema v3; trigram tables only at v2+.
_SOURCES = [
    ("segments_fts", "segments", False),
    ("segments_cjk_fts", "segments", True),
    ("transcript_fts", "transcript_segments", False),
    ("transcript_cjk_fts", "transcript_segments", True),
]


def search(conn: sqlite3.Connection, q: str) -> list[tuple[str, float]]:
    """Return (rel_path, t_start) for every matching segment across all indexes."""
    fts_q = sanitize(q)
    if not fts_q:
        return []

    # trigram needs >=3 chars per term; skip those tables rather than let them raise
    trigram_ok = all(len(t) >= 3 for t in re.findall(r"[^\s\"]+", q))
    hits: dict[tuple[str, float], None] = {}

    for fts_table, base_table, is_trigram in _SOURCES:
        if not has_table(conn, fts_table) or not has_table(conn, base_table):
            continue
        if is_trigram and not trigram_ok:
            continue
        try:
            rows = conn.execute(
                f"SELECT v.rel_path, s.t_start FROM {base_table} s "
                f"JOIN {fts_table} f ON f.rowid = s.id "
                f"JOIN videos v ON v.id = s.video_id WHERE {fts_table} MATCH ?",
                (fts_q,),
            ).fetchall()
        except sqlite3.OperationalError:
            continue  # some queries are rejected outright; treat as no hits
        for r in rows:
            hits[(r[0], r[1])] = None

    return sorted(hits)


def evaluate(db_path: Path, queries: list[dict]) -> dict:
    conn = sqlite3.connect(db_path)
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    n_videos = conn.execute("SELECT COUNT(*) FROM videos WHERE status='indexed'").fetchone()[0]
    n_segments = conn.execute("SELECT COUNT(*) FROM segments").fetchone()[0]

    results, guard_failures = [], 0
    for spec in queries:
        q = spec["q"]
        hits = search(conn, q)
        paths = {p for p, _ in hits}

        if spec.get("expect_none"):
            ok = not hits
            if not ok:
                guard_failures += 1
            kind = "guard"
        else:
            wanted = spec.get("expect_any") or []
            ok = any(any(w in p for p in paths) for w in wanted)
            kind = "recall"

        results.append(
            {"q": q, "ok": ok, "kind": kind, "n_hits": len(hits),
             "n_videos": len(paths), "tags": spec.get("tags") or []}
        )

    return {"db": str(db_path), "user_version": version, "videos": n_videos,
            "segments": n_segments, "results": results, "guard_failures": guard_failures}


def report(run: dict) -> None:
    recall = [r for r in run["results"] if r["kind"] == "recall"]
    guards = [r for r in run["results"] if r["kind"] == "guard"]
    hit = sum(1 for r in recall if r["ok"])

    print(f"\n=== {run['db']} (schema v{run['user_version']}) ===")
    print(f"  {run['videos']} indexed videos, {run['segments']} segments")
    print(f"  recall: {hit}/{len(recall)} ({hit/len(recall)*100:.0f}%)" if recall else "")
    print(f"  precision guards: {len(guards)-run['guard_failures']}/{len(guards)} clean")

    by_tag: dict[str, list] = {}
    for r in recall:
        for t in r["tags"] or ["general"]:
            by_tag.setdefault(t, []).append(r)
    for tag, rows in sorted(by_tag.items()):
        n = sum(1 for r in rows if r["ok"])
        print(f"    {tag:12} {n}/{len(rows)}")

    print("\n  misses:")
    for r in recall:
        if not r["ok"]:
            print(f"    MISS  {r['q']!r}  ({r['n_hits']} hits, none expected-matching)")
    for r in guards:
        if not r["ok"]:
            print(f"    LEAK  {r['q']!r} returned {r['n_hits']} hits (expected none)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dbs", nargs="+")
    ap.add_argument("--queries", default="eval/queries_ff2.yaml")
    args = ap.parse_args()

    queries = yaml.safe_load(Path(args.queries).read_text(encoding="utf-8"))["queries"]
    runs = [evaluate(Path(db), queries) for db in args.dbs]
    for run in runs:
        report(run)

    if len(runs) > 1:
        print("\n=== comparison ===")
        for i, r in enumerate(zip(*[run["results"] for run in runs])):
            if len({x["ok"] for x in r}) > 1:
                flags = "  ".join(f"{'HIT ' if x['ok'] else 'MISS'}" for x in r)
                print(f"  {r[0]['q']!r:30} {flags}")

    sys.exit(1 if any(run["guard_failures"] for run in runs) else 0)


if __name__ == "__main__":
    main()
