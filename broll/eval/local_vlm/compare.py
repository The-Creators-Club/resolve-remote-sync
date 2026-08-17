"""Put several scored runs side by side: arm A (the recommended design) across
hosts/models — 3080-4B-Q4, mac-8B-Q8, mac-30B-A3B, mac-32B — with quality
metrics AND s/clip, tok/s and peak memory. Also shows arms B/C for any run
that has them.

usage: python compare.py results results-mac/qwen3-vl-8b-q8_0 results-mac/... [--out compare.md]
       (each argument is a results dir containing summary.json from score.py,
        or a summary.json path; label defaults to "<host_label> · <model_label>")
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from common import HERE
from score import METRIC_ROWS, _f, _table

# the rows that matter for the cross-model view, in order
COMPARE_ROWS = [
    ("clips", "n", False), ("clip valid rate", "valid_rate", True), ("window valid rate", "window_valid_rate", True),
    ("finish=length rate", "length_finish_rate", True),
    ("segment F1", "seg_f1", True), ("segment recall", "seg_r", True), ("segment count ratio", "seg_ratio", False),
    ("frame coverage", "coverage", True), ("segments/clip vs Haiku", None, None),
    ("objects Jaccard", "obj_jaccard", True), ("head-noun recall (objects)", "head_recall_obj", True),
    ("head-noun recall (any text)", "head_recall_any", True),
    ("OCR char similarity", "ocr_sim", True), ("OCR char recall", "ocr_char_recall", True), ("OCR exact", "ocr_exact", True),
    ("category agreement (Haiku hint)", "cat_agree", True), ("category agreement (approved)", "cat_agree_approved", True),
    ("themes soft overlap", "theme_soft", True), ("mean agreement", "agreement", True),
    ("wall s/clip mean", "wall_s_mean", False), ("wall s/clip median", "wall_s_median", False),
    ("wall s/call mean", "call_s_mean", False), ("image-encode share of time", "prompt_share", True),
    ("decode tok/s", "tg_tps_mean", False), ("prompt tok/s", "pp_tps_mean", False),
    ("completion tokens/clip", "completion_tokens_mean", False), ("peak memory MB", "peak_mem_mb", False),
]


def load(arg: str) -> tuple[str, dict]:
    p = Path(arg)
    if p.is_dir():
        p = p / "summary.json"
    s = json.loads(p.read_text(encoding="utf-8"))
    return str(p.parent), s


def label_of(s: dict) -> str:
    arms = s.get("arms") or {}
    meta = (arms.get("A") or next(iter(arms.values()), {})).get("meta") or {}
    host = meta.get("host_label") or meta.get("host") or "?"
    return f"{host} · {meta.get('model_label', '?')}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+")
    ap.add_argument("--out", type=Path, default=HERE / "results" / "compare.md")
    ap.add_argument("--labels", nargs="*", help="override column labels, same order as runs")
    args = ap.parse_args()

    runs = [load(r) for r in args.runs]
    labels = args.labels or [label_of(s) for _, s in runs]
    lines = ["# Local VLM eval — cross-host / cross-model comparison", "",
             "Arm A = frames (960x540, 9 per call) + v7 compact format + GBNF grammar, scored against the same "
             "Haiku baseline on the same clips (clips.json / bundle). Quality numbers are agreement with Haiku, "
             "which is a reference, not ground truth (see each run's report.md).", ""]
    lines += ["| run | host | runtime | model | ctx | img-min-tokens | scored |", "|---|---|---|---|---|---|---|"]
    for (d, s), lab in zip(runs, labels):
        arms = s.get("arms") or {}
        meta = (arms.get("A") or next(iter(arms.values()), {})).get("meta") or {}
        lines.append(f"| {lab} | {meta.get('host_label') or meta.get('host','?')} | {meta.get('runtime_label','?')} | "
                     f"{meta.get('model_label','?')} (`{Path(str(meta.get('model',''))).name}`) | {meta.get('ctx')} | "
                     f"{meta.get('image_min_tokens')} | {s.get('scored_at','?')} |")
    lines.append("")

    for arm in ("A", "B", "C"):
        cols = [(lab, s["arms"][arm]["overall"]) for (_, s), lab in zip(runs, labels) if arm in (s.get("arms") or {})]
        if not cols:
            continue
        rows = []
        for label, key, pct in COMPARE_ROWS:
            if key is None:
                rows.append([label] + [f"{_f(a.get('seg_pred_mean'), nd=1)} vs {_f(a.get('seg_base_mean'), nd=1)}" for _, a in cols])
            else:
                rows.append([label] + [_f(a.get(key), pct=pct) for _, a in cols])
        title = {"A": "Arm A — frames + compact + grammar (the recommended design)",
                 "B": "Arm B — frames + compact, no grammar", "C": "Arm C — sheets + v6 JSON (old path)"}[arm]
        lines += [f"## {title}", "", _table(rows, ["metric"] + [c for c, _ in cols]), ""]

    # per-stratum arm A seg F1 / head recall / OCR, per run
    lines += ["## Arm A by stratum (segment F1 / head-noun recall any / OCR char similarity)", ""]
    strata = ["text", "multishot", "simple", "random"]
    rows = []
    for (_, s), lab in zip(runs, labels):
        ps = ((s.get("arms") or {}).get("A") or {}).get("per_stratum") or {}
        rows.append([lab] + [f"{_f(ps.get(st, {}).get('seg_f1'), True)} / {_f(ps.get(st, {}).get('head_recall_any'), True)} / "
                             f"{_f(ps.get(st, {}).get('ocr_sim'), True)}" for st in strata])
    lines += [_table(rows, ["run"] + strata), ""]

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
