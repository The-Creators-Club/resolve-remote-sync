"""Turn an exported verdicts.json (judge.html's Export button) into
verdicts.md: per-source means/wins/flags, broken down by stratum, plus how
well score.py's automatic "agreement with Haiku" metric tracks what a human
actually thought — the point of building a human judging tool at all is to
find out whether the cheap automatic numbers in results/report.md can be
trusted for the runs nobody has time to sit and watch.

Only reads verdicts.json, --clips (for nothing but a sanity id check — the
export already carries share/rel_path/stratum) and each source's
results*/summary.json IF ONE EXISTS (score.py writes it; this script never
runs score.py itself and never touches results/*.jsonl — per the eval's rule,
only score.py or a human, never a second scorer, decides what "agreement"
means for a results dir).

usage: python summarise_verdicts.py [--verdicts verdicts.json] [--out verdicts.md]
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

JUDGE_DIR = Path(__file__).resolve().parent
LOCAL_VLM_DIR = JUDGE_DIR.parent

# where an automatic summary.json might live for a given source label — mirrors
# build_judge.py's default_sources() naming (results/ -> "local-4b", each
# results-mac/<model>/ -> "<model>")
AUTO_SUMMARY_CANDIDATES = {"local-4b": LOCAL_VLM_DIR / "results" / "summary.json"}
for p in sorted(LOCAL_VLM_DIR.glob("results-mac/*/summary.json")):
    AUTO_SUMMARY_CANDIDATES[p.parent.name] = p


def load_auto_agreement(label: str) -> dict[int, float] | None:
    """id -> score.py's per-clip 'agreement' (mean of segment F1, head-noun
    recall, OCR similarity, category agreement — see score.py's score_clip),
    for arm A only (every results dir here is an A-only or A/B/C run, and
    build_judge.py's default sources are all arm A). None if this source was
    never scored (no summary.json yet)."""
    path = AUTO_SUMMARY_CANDIDATES.get(label)
    if path is None or not path.exists():
        return None
    try:
        summary = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    per_clip_a = (summary.get("per_clip") or {}).get("A") or []
    return {int(m["id"]): m["agreement"] for m in per_clip_a if m.get("agreement") is not None}


# ---------------------------------------------------------------------------
# stats helpers (stdlib only — no numpy dependency for a script this small)
# ---------------------------------------------------------------------------

def mean(xs: list[float]) -> float | None:
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 2:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx <= 0 or vy <= 0:
        return None
    return cov / (vx * vy) ** 0.5


def spearman(xs: list[float], ys: list[float]) -> float | None:
    def ranks(vals: list[float]) -> list[float]:
        order = sorted(range(len(vals)), key=lambda i: vals[i])
        r = [0.0] * len(vals)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and vals[order[j + 1]] == vals[order[i]]:
                j += 1
            avg_rank = (i + j) / 2.0 + 1
            for k in range(i, j + 1):
                r[order[k]] = avg_rank
            i = j + 1
        return r
    if len(xs) < 2:
        return None
    return pearson(ranks(xs), ranks(ys))


# ---------------------------------------------------------------------------
# aggregation
# ---------------------------------------------------------------------------

def build_report(payload: dict[str, Any]) -> str:
    rows = payload.get("clips") or []
    sources = payload.get("sources") or sorted({k for r in rows for k in (r.get("per_source") or {})})
    lines = ["# Human verdicts — local-VLM b-roll eval", ""]
    lines.append(f"- **verdicts export:** {payload.get('generated_at', '?')}")
    lines.append(f"- **judge.html built from:** {payload.get('source_build', '?')}")
    lines.append(f"- **clips judged:** {len(rows)}")
    lines.append("")

    if not rows:
        lines.append("No clips with a vote were found in this verdicts.json.")
        return "\n".join(lines) + "\n"

    # ---- overall per-source table ----
    stats = {s: {"scores": [], "wins": 0, "flags": Counter()} for s in sources}
    for r in rows:
        for key, ps in (r.get("per_source") or {}).items():
            if key not in stats:
                stats[key] = {"scores": [], "wins": 0, "flags": Counter()}
            if ps.get("score") is not None:
                stats[key]["scores"].append(ps["score"])
            for f in ps.get("flags") or []:
                stats[key]["flags"][f] += 1
        if r.get("best") and r["best"] in stats:
            stats[r["best"]]["wins"] += 1

    lines += ["## Overall", "",
             "| source | mean score | n scored | best picks | hallucinated | missed_shot | ocr_wrong | over_segmented |",
             "|---|---|---|---|---|---|---|---|"]
    for s in sources:
        st = stats[s]
        m = mean(st["scores"])
        m_str = f"{m:.2f}" if m is not None else "–"
        lines.append(f"| {s} | {m_str} | {len(st['scores'])} | {st['wins']} | {st['flags']['hallucinated']} | "
                     f"{st['flags']['missed_shot']} | {st['flags']['ocr_wrong']} | {st['flags']['over_segmented']} |")
    lines.append("")

    # ---- per stratum ----
    by_stratum: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_stratum[r.get("stratum") or "?"].append(r)
    lines += ["## By stratum", ""]
    for stratum in sorted(by_stratum):
        srows = by_stratum[stratum]
        lines += [f"### {stratum} ({len(srows)} clips judged)", "",
                 "| source | mean score | n scored | best picks |", "|---|---|---|---|"]
        sstats = {s: {"scores": [], "wins": 0} for s in sources}
        for r in srows:
            for key, ps in (r.get("per_source") or {}).items():
                if key in sstats and ps.get("score") is not None:
                    sstats[key]["scores"].append(ps["score"])
            if r.get("best") in sstats:
                sstats[r["best"]]["wins"] += 1
        for s in sources:
            m = mean(sstats[s]["scores"])
            m_str = f"{m:.2f}" if m is not None else "–"
            lines.append(f"| {s} | {m_str} | {len(sstats[s]['scores'])} | {sstats[s]['wins']} |")
        lines.append("")

    # ---- notes ----
    noted = [r for r in rows if (r.get("note") or "").strip()]
    if noted:
        lines += ["## Notes", ""]
        for r in noted:
            lines.append(f"- **clip {r['id']}** ({r.get('stratum')}, {r.get('rel_path')}): {r['note'].strip()}")
        lines.append("")

    # ---- automatic-vs-human agreement ----
    lines += ["## Automatic metric vs human score", "",
             "How well score.py's per-clip `agreement` (mean of segment F1, head-noun recall, OCR "
             "similarity and category agreement against Haiku — see score.py's `score_clip`) tracks "
             "the 1-5 the human gave the SAME source on the SAME clip. Only sources with a "
             "`results*/summary.json` on this machine are covered; run `python score.py --results-dir "
             "...` for any source missing below to add it here.", "",
             "| source | clips with both | Pearson r | Spearman r |", "|---|---|---|---|"]
    any_auto = False
    for s in sources:
        auto = load_auto_agreement(s)
        if auto is None:
            lines.append(f"| {s} | not scored yet (no summary.json) | – | – |")
            continue
        any_auto = True
        human, machine = [], []
        for r in rows:
            ps = (r.get("per_source") or {}).get(s)
            if not ps or ps.get("score") is None:
                continue
            a = auto.get(int(r["id"]))
            if a is None:
                continue
            human.append(ps["score"])
            machine.append(a)
        pr = pearson(human, machine)
        sr = spearman(human, machine)
        lines.append(f"| {s} | {len(human)} | " + (f"{pr:.3f}" if pr is not None else "–") +
                     " | " + (f"{sr:.3f}" if sr is not None else "–") + " |")
    lines.append("")
    if not any_auto:
        lines.append("*(no source here has been scored with score.py yet — this table is empty of numbers "
                     "until one has.)*")
        lines.append("")
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verdicts", type=Path, default=JUDGE_DIR / "verdicts.json")
    ap.add_argument("--out", type=Path, default=JUDGE_DIR / "verdicts.md")
    args = ap.parse_args()

    if not args.verdicts.exists():
        raise SystemExit(f"not found: {args.verdicts} (Export from judge.html first, or pass --verdicts)")
    payload = json.loads(args.verdicts.read_text(encoding="utf-8"))
    report = build_report(payload)
    args.out.write_text(report, encoding="utf-8")
    print(f"wrote {args.out} ({len(payload.get('clips') or [])} clips)")


if __name__ == "__main__":
    main()
