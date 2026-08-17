"""Score one results dir (results/ or results-mac/<model>/) against the Haiku
baseline in clips.json and write report.md + summary.json into it.

Haiku is a REFERENCE, not ground truth: the 2026-08-17 study saw Haiku wrong
on clip 13454 (a shade-house described as an apartment complex). Every metric
below is "agreement with Haiku"; the 20 largest disagreements are listed with
their frame paths so a human can decide who was right.

Metrics per clip (then mean over clips, overall and per stratum):
  seg_f1        temporal-IoU F1 between predicted and baseline segments
                (greedy one-to-one match at IoU >= 0.5; every interval is
                padded to at least one sampling gap long so a single-frame
                segment is not a zero-length point)
  seg_ratio     predicted / baseline segment count
  coverage      fraction of the clip's frames inside >= 1 predicted segment
  obj_jaccard   Jaccard between normalised object-noun sets (whole clip)
  head_recall   fraction of baseline object phrases whose HEAD noun (last
                word; a CJK phrase is its own head) appears in the predicted
                objects (head_recall_obj) or anywhere in predicted text
                (head_recall_any) — Haiku listed synonyms, we no longer ask
                for them, so this is the fairer recall
  ocr_exact / ocr_sim / ocr_char_recall / ocr_detected  on clips whose
                baseline has on-screen text (normalised: whitespace and
                punctuation stripped, case-folded)
  cat_agree     category_hint == baseline category_hint (where baseline has one)
  cat_agree_approved  == the approved `category` (where set)
  theme_jaccard / theme_soft   themes as normalised token sets
  wall_s, call_s, prompt/decode share, tokens, tok/s, validity, finish=length

usage: python score.py [--results-dir results] [--clips clips.json] [--recategorize]
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import statistics
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from common import DEFAULT_CLIPS, HERE, frame_abs, load_clips, read_jsonl
from format import CategoryAssigner, clip_text_for_category

ARMS_ORDER = ["A", "B", "C"]
ARM_NAMES = {"A": "frames + compact + grammar", "B": "frames + compact, no grammar",
             "C": "sheets + v6 JSON (old path)"}


# ---------------------------------------------------------------------------
# normalisation helpers
# ---------------------------------------------------------------------------

_CJK = re.compile(r"[㐀-鿿豈-﫿]")
_WORD = re.compile(r"[a-z0-9]+(?:'[a-z]+)?|[㐀-鿿豈-﫿]+")
_STOP = {"a", "an", "the", "of", "in", "on", "at", "with", "and", "or", "to", "from", "by",
         "view", "shot", "scene", "background", "foreground", "visible", "close", "up",
         "multiple", "several", "some", "various", "area", "areas", "possibly", "n/a"}


def singular(w: str) -> str:
    if len(w) <= 3 or _CJK.search(w):
        return w
    if w.endswith("ies") and len(w) > 4:
        return w[:-3] + "y"
    if w.endswith(("ses", "xes", "zes", "ches", "shes")):
        return w[:-2]
    if w.endswith("ss") or w.endswith("us") or w.endswith("is"):
        return w
    if w.endswith("s"):
        return w[:-1]
    return w


def norm_phrase(s: str) -> str:
    toks = [singular(t) for t in _WORD.findall((s or "").lower())]
    toks = [t for t in toks if t and t not in _STOP]
    return " ".join(toks)


def head_noun(s: str) -> str:
    n = norm_phrase(s)
    if not n:
        return ""
    return n.split()[-1]


def tokens(s: str) -> set[str]:
    return {singular(t) for t in _WORD.findall((s or "").lower())} - _STOP


def norm_text(s: str) -> str:
    return "".join(ch for ch in (s or "").lower() if ch.isalnum() or _CJK.match(ch))


def jaccard(a: set, b: set) -> float | None:
    if not a and not b:
        return None
    return len(a & b) / len(a | b)


def mean(xs) -> float | None:
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 4) if xs else None


def median(xs) -> float | None:
    xs = [x for x in xs if x is not None]
    return round(statistics.median(xs), 4) if xs else None


# ---------------------------------------------------------------------------
# per-clip metrics
# ---------------------------------------------------------------------------

def _pad(segs: list[dict], pad: float) -> list[tuple[float, float]]:
    out = []
    for s in segs:
        a = float(s["t_start"]); b = float(s["t_end"])
        if b < a:
            a, b = b, a
        out.append((a, max(b, a) + pad))
    return out


def _iou(x, y) -> float:
    inter = max(0.0, min(x[1], y[1]) - max(x[0], y[0]))
    union = (x[1] - x[0]) + (y[1] - y[0]) - inter
    return inter / union if union > 0 else 0.0


def segment_f1(pred: list[dict], base: list[dict], pad: float, thr: float = 0.5) -> dict[str, Any]:
    P, B = _pad(pred, pad), _pad(base, pad)
    if not P and not B:
        return {"seg_f1": None, "seg_p": None, "seg_r": None, "seg_ratio": None, "seg_matched": 0}
    pairs = sorted(((_iou(p, b), i, j) for i, p in enumerate(P) for j, b in enumerate(B)), reverse=True)
    used_p, used_b, matched = set(), set(), []
    for iou, i, j in pairs:
        if iou < thr:
            break
        if i in used_p or j in used_b:
            continue
        used_p.add(i); used_b.add(j); matched.append((i, j, iou))
    m = len(matched)
    p = m / len(P) if P else 0.0
    r = m / len(B) if B else 0.0
    f1 = 2 * p * r / (p + r) if (p + r) else 0.0
    return {"seg_f1": round(f1, 4), "seg_p": round(p, 4), "seg_r": round(r, 4),
            "seg_ratio": round(len(P) / len(B), 3) if B else None, "seg_matched": m,
            "matches": matched}


def coverage(pred: list[dict], frames: list[dict], pad: float) -> float | None:
    if not frames:
        return None
    covered = 0
    for f in frames:
        t = float(f["t"])
        if any(float(s["t_start"]) - 0.01 <= t <= float(s["t_end"]) + pad + 0.01 for s in pred):
            covered += 1
    return round(covered / len(frames), 4)


def objects_of(segs: list[dict]) -> list[str]:
    out = []
    for s in segs:
        o = s.get("objects")
        if isinstance(o, list):
            out.extend(str(x) for x in o)
        elif isinstance(o, str):
            out.extend(x.strip() for x in o.split(","))
    return [x for x in out if x and x.strip()]


def object_metrics(pred: list[dict], base: list[dict]) -> dict[str, Any]:
    po = objects_of(pred); bo = objects_of(base)
    pset = {norm_phrase(x) for x in po} - {""}
    bset = {norm_phrase(x) for x in bo} - {""}
    ptok = set()
    for x in po:
        ptok |= tokens(x)
    ptext = set(ptok)
    for s in pred:
        ptext |= tokens(s.get("description", ""))
        ptext |= tokens(s.get("onscreen_text_en", ""))
    heads = {head_noun(x) for x in bo} - {""}
    hr_obj = len([h for h in heads if h in ptok]) / len(heads) if heads else None
    hr_any = len([h for h in heads if h in ptext]) / len(heads) if heads else None
    return {"obj_jaccard": (round(jaccard(pset, bset), 4) if jaccard(pset, bset) is not None else None),
            "head_recall_obj": round(hr_obj, 4) if hr_obj is not None else None,
            "head_recall_any": round(hr_any, 4) if hr_any is not None else None,
            "n_obj_pred": len(pset), "n_obj_base": len(bset)}


def ocr_metrics(pred: list[dict], base: list[dict]) -> dict[str, Any]:
    def collect(segs):
        pieces, seen = [], set()
        for s in segs:
            for piece in str(s.get("onscreen_text") or "").split("|"):
                p = piece.strip()
                if p and p not in seen:
                    seen.add(p); pieces.append(p)
        return pieces
    bp, pp = collect(base), collect(pred)
    b = norm_text("".join(bp)); p = norm_text("".join(pp))
    if not b:
        return {"ocr_applicable": False, "ocr_false_positive": bool(p)}
    sm = difflib.SequenceMatcher(None, b, p, autojunk=False)
    matched = sum(bl.size for bl in sm.get_matching_blocks())
    return {"ocr_applicable": True, "ocr_exact": float(b == p), "ocr_sim": round(sm.ratio(), 4),
            "ocr_char_recall": round(matched / len(b), 4), "ocr_detected": float(bool(p)),
            "ocr_base": " | ".join(bp)[:300], "ocr_pred": " | ".join(pp)[:300]}


def theme_metrics(pred: list[str], base: list[str]) -> dict[str, Any]:
    ps = {norm_phrase(t) for t in pred} - {""}
    bs = {norm_phrase(t) for t in base} - {""}
    j = jaccard(ps, bs)
    ptok = set()
    for t in pred:
        ptok |= tokens(t)
    soft = None
    if bs:
        soft = len([t for t in base if tokens(t) & ptok]) / len(base)
    return {"theme_jaccard": round(j, 4) if j is not None else None,
            "theme_soft": round(soft, 4) if soft is not None else None}


def score_clip(rec: dict, clip: dict, taxonomy_slugs: set[str]) -> dict[str, Any]:
    base = clip["baseline"]
    frames = clip["frames"]
    ts = sorted(float(f["t"]) for f in frames)
    gaps = [b - a for a, b in zip(ts, ts[1:]) if b > a]
    pad = min(4.0, statistics.median(gaps)) if gaps else 4.0
    res = rec.get("result") or {}
    pred_segs = res.get("segments") or []
    m: dict[str, Any] = {
        "id": clip["id"], "stratum": clip.get("stratum"), "status": rec.get("status"),
        "valid": rec.get("status") in ("ok", "partial_invalid", "partial"),
        "fully_valid": rec.get("status") == "ok",
        "n_windows": rec.get("n_windows"), "n_valid_windows": rec.get("n_valid_windows"),
        "n_seg_pred": len(pred_segs), "n_seg_base": len(base["segments"]),
        "wall_s": rec.get("wall_s"), "prompt_tokens": rec.get("prompt_tokens"),
        "completion_tokens": rec.get("completion_tokens"),
        "prompt_ms": rec.get("prompt_ms"), "predicted_ms": rec.get("predicted_ms"),
        "peak_mem_mb": rec.get("peak_mem_mb"),
        "n_length_finish": sum(1 for c in rec.get("calls") or [] if c.get("finish_reason") == "length"),
        "n_problems": sum(len(c.get("problems") or []) for c in rec.get("calls") or []),
        "call_s": [c.get("wall_s") for c in rec.get("calls") or []],
        "tg_tps": [c.get("predicted_per_second") for c in rec.get("calls") or [] if c.get("predicted_per_second")],
        "pp_tps": [c.get("prompt_per_second") for c in rec.get("calls") or [] if c.get("prompt_per_second")],
    }
    m.update(segment_f1(pred_segs, base["segments"], pad))
    m["coverage"] = coverage(pred_segs, frames, pad)
    m.update(object_metrics(pred_segs, base["segments"]))
    m.update(ocr_metrics(pred_segs, base["segments"]))
    m.update(theme_metrics(res.get("themes") or [], base.get("themes") or []))
    pc = res.get("category_hint")
    m["cat_pred"] = pc
    m["cat_in_taxonomy"] = (pc in taxonomy_slugs) if pc else None
    m["cat_agree"] = (float(pc == base.get("category_hint")) if base.get("category_hint") else None)
    m["cat_agree_approved"] = (float(pc == base.get("category")) if base.get("category") else None)
    m["flags_pred"] = res.get("quality_flags") or []
    m["flags_base"] = base.get("quality_flags") or []
    fj = jaccard(set(m["flags_pred"]), set(m["flags_base"]))
    m["flag_jaccard"] = round(fj, 4) if fj is not None else None
    # disagreement score for the human-review list (only over what applies)
    parts = [m["seg_f1"], m["head_recall_any"]]
    if m.get("ocr_applicable"):
        parts.append(m.get("ocr_sim"))
    if m["cat_agree"] is not None:
        parts.append(m["cat_agree"])
    parts = [p for p in parts if p is not None]
    m["agreement"] = round(sum(parts) / len(parts), 4) if parts else None
    if not m["valid"]:
        m["agreement"] = 0.0
    return m


# ---------------------------------------------------------------------------
# aggregation
# ---------------------------------------------------------------------------

AGG_KEYS = ["seg_f1", "seg_p", "seg_r", "seg_ratio", "coverage", "obj_jaccard", "head_recall_obj",
            "head_recall_any", "ocr_exact", "ocr_sim", "ocr_char_recall", "ocr_detected",
            "cat_agree", "cat_agree_approved", "cat_in_taxonomy", "theme_jaccard", "theme_soft",
            "flag_jaccard", "agreement"]


def aggregate(ms: list[dict]) -> dict[str, Any]:
    out: dict[str, Any] = {"n": len(ms)}
    for k in AGG_KEYS:
        out[k] = mean(m.get(k) for m in ms)
    out["n_ocr_applicable"] = sum(1 for m in ms if m.get("ocr_applicable"))
    out["ocr_false_positive_rate"] = mean(float(m.get("ocr_false_positive")) for m in ms
                                          if m.get("ocr_applicable") is False)
    out["valid_rate"] = mean(float(m["valid"]) for m in ms)
    out["fully_valid_rate"] = mean(float(m["fully_valid"]) for m in ms)
    nw = sum(m.get("n_windows") or 0 for m in ms)
    out["n_calls"] = nw
    out["window_valid_rate"] = round(sum(m.get("n_valid_windows") or 0 for m in ms) / nw, 4) if nw else None
    out["length_finish_rate"] = round(sum(m.get("n_length_finish") or 0 for m in ms) / nw, 4) if nw else None
    out["problems_per_call"] = round(sum(m.get("n_problems") or 0 for m in ms) / nw, 3) if nw else None
    out["wall_s_mean"] = mean(m.get("wall_s") for m in ms)
    out["wall_s_median"] = median(m.get("wall_s") for m in ms)
    calls = [c for m in ms for c in (m.get("call_s") or []) if c is not None]
    out["call_s_mean"] = mean(calls)
    out["call_s_median"] = median(calls)
    pm = sum(m.get("prompt_ms") or 0 for m in ms); dm = sum(m.get("predicted_ms") or 0 for m in ms)
    out["prompt_share"] = round(pm / (pm + dm), 3) if (pm + dm) else None
    out["prompt_tokens_mean"] = mean(m.get("prompt_tokens") for m in ms)
    out["completion_tokens_mean"] = mean(m.get("completion_tokens") for m in ms)
    out["tg_tps_mean"] = mean(x for m in ms for x in (m.get("tg_tps") or []))
    out["pp_tps_mean"] = mean(x for m in ms for x in (m.get("pp_tps") or []))
    out["peak_mem_mb"] = max((m.get("peak_mem_mb") or 0) for m in ms) if ms else None
    out["seg_pred_mean"] = mean(m.get("n_seg_pred") for m in ms)
    out["seg_base_mean"] = mean(m.get("n_seg_base") for m in ms)
    return out


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------

def _f(x, pct=False, nd=2):
    if x is None:
        return "–"
    if isinstance(x, float):
        return f"{x*100:.0f}%" if pct else f"{x:.{nd}f}"
    return str(x)


def _table(rows: list[list[str]], header: list[str]) -> str:
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


METRIC_ROWS = [
    ("clips scored", "n", False), ("clip valid rate", "valid_rate", True),
    ("clip fully valid (every window)", "fully_valid_rate", True),
    ("window valid rate", "window_valid_rate", True), ("finish=length rate (windows)", "length_finish_rate", True),
    ("segment F1 (IoU≥0.5)", "seg_f1", True), ("segment precision", "seg_p", True), ("segment recall", "seg_r", True),
    ("segment count ratio pred/base", "seg_ratio", False), ("frame coverage", "coverage", True),
    ("segments/clip pred vs Haiku", None, None),
    ("objects Jaccard", "obj_jaccard", True), ("head-noun recall (objects)", "head_recall_obj", True),
    ("head-noun recall (any text)", "head_recall_any", True),
    ("OCR clips (baseline has text)", "n_ocr_applicable", False), ("OCR exact match", "ocr_exact", True),
    ("OCR char similarity", "ocr_sim", True), ("OCR char recall", "ocr_char_recall", True),
    ("OCR detected any text", "ocr_detected", True), ("OCR text where Haiku had none", "ocr_false_positive_rate", True),
    ("category agreement (Haiku hint)", "cat_agree", True), ("category agreement (approved)", "cat_agree_approved", True),
    ("category slug in taxonomy", "cat_in_taxonomy", True),
    ("themes Jaccard", "theme_jaccard", True), ("themes soft overlap", "theme_soft", True),
    ("quality flags Jaccard", "flag_jaccard", True),
    ("mean agreement (review score)", "agreement", True),
    ("wall s/clip mean", "wall_s_mean", False), ("wall s/clip median", "wall_s_median", False),
    ("wall s/call mean", "call_s_mean", False), ("prompt (image encode) share of time", "prompt_share", True),
    ("prompt tokens/clip", "prompt_tokens_mean", False), ("completion tokens/clip", "completion_tokens_mean", False),
    ("decode tok/s", "tg_tps_mean", False), ("prompt tok/s", "pp_tps_mean", False),
    ("peak memory MB", "peak_mem_mb", False),
]


def metric_table(aggs: dict[str, dict], cols: list[str]) -> str:
    rows = []
    for label, key, pct in METRIC_ROWS:
        if key is None:
            rows.append([label] + [f"{_f(aggs[c].get('seg_pred_mean'), nd=1)} vs {_f(aggs[c].get('seg_base_mean'), nd=1)}"
                                   for c in cols])
        else:
            rows.append([label] + [_f(aggs[c].get(key), pct=pct) for c in cols])
    return _table(rows, ["metric"] + cols)


def build_report(results_dir: Path, doc: dict, per_arm: dict[str, list[dict]], metas: dict[str, dict],
                 recat_method: str | None) -> tuple[str, dict]:
    clips_by_id = {c["id"]: c for c in doc["clips"]}
    arms = [a for a in ARMS_ORDER if a in per_arm]
    summary: dict[str, Any] = {"results_dir": str(results_dir), "scored_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                               "clips_json": str(doc["_path"]), "arms": {}}
    lines = [f"# Local VLM eval — {results_dir.name}", ""]
    m0 = metas.get(arms[0], {}) if arms else {}
    lines += [f"- **Host:** {m0.get('host_label') or m0.get('host', '?')}  ",
              f"- **Runtime:** {m0.get('runtime_label', '?')}  ",
              f"- **Model:** {m0.get('model_label', '?')} (`{Path(str(m0.get('model', ''))).name}` + `{Path(str(m0.get('mmproj', ''))).name}`)  ",
              f"- **Context / image-min-tokens / frames per call:** {m0.get('ctx')} / {m0.get('image_min_tokens')} / {m0.get('frames_per_call')}  ",
              f"- **Sampler:** A/B `{json.dumps(metas.get('A', metas.get('B', {})).get('sampler'))}`, C `{json.dumps(metas.get('C', {}).get('sampler'))}`  ",
              f"- **Clips:** {len(doc['clips'])} selected from {doc.get('n_indexed')} Haiku-indexed ({doc.get('n_eligible')} eligible with ≤{doc.get('max_frames')} frames on disk; {doc.get('n_without_frames')} had no complete frames dir); strata: "
              + ", ".join(f"{k}={v}" for k, v in sorted(_count(c['stratum'] for c in doc['clips']).items())) + "  ",
              f"- **Category assignment (arms A/B):** {recat_method or (per_arm.get('A') or per_arm.get('B') or [{}])[0].get('cat_method', '?')}  ",
              f"- **Scored:** {summary['scored_at']}", "",
              "Haiku (`claude-haiku-4-5-20251001`, the archive's index) is the *reference*, not ground truth — the "
              "2026-08-17 study saw it wrong on 13454 — so every number below is agreement with Haiku, and the "
              "largest disagreements are listed at the end for a human look. Segment F1 uses temporal IoU ≥ 0.5 "
              "with every interval padded to at least one sampling gap. Head-noun recall is the fairer object "
              "metric: Haiku listed synonyms/hypernyms, the compact format asks for the head term plus one hypernym.",
              ""]
    # arm summary
    aggs = {a: aggregate(per_arm[a]) for a in arms}
    for a in arms:
        aggs[a]["name"] = ARM_NAMES[a]
        summary["arms"][a] = {"name": ARM_NAMES[a], "meta": metas.get(a, {}), "overall": aggs[a]}
    lines += ["## Arms", ""]
    lines += [f"- **{a}** — {ARM_NAMES[a]} ({len(per_arm[a])} clips" +
              (f", grammar {'on' if metas.get(a, {}).get('grammar_used') else 'off'}" if a != 'C' else "") + ")" for a in arms]
    lines += ["", "## Overall (all clips each arm ran)", "", metric_table(aggs, arms), ""]
    # common subset
    common = set.intersection(*[{m["id"] for m in per_arm[a]} for a in arms]) if len(arms) > 1 else set()
    if common and len(arms) > 1 and any(len(per_arm[a]) != len(common) for a in arms):
        sub = {a: aggregate([m for m in per_arm[a] if m["id"] in common]) for a in arms}
        summary["common_subset"] = {"ids": sorted(common), "arms": sub}
        lines += [f"## Same {len(common)} clips, all arms (arm C ran on a subset)", "", metric_table(sub, arms), ""]
    # per stratum for each arm
    for a in arms:
        by = defaultdict(list)
        for m in per_arm[a]:
            by[m["stratum"] or "?"].append(m)
        strata = sorted(by)
        sa = {s: aggregate(by[s]) for s in strata}
        summary["arms"][a]["per_stratum"] = sa
        lines += [f"## Arm {a} by stratum", "", metric_table(sa, strata), ""]
    # flagged disagreements (arm A preferred)
    fa = "A" if "A" in per_arm else arms[0]
    worst = sorted(per_arm[fa], key=lambda m: (m.get("agreement") if m.get("agreement") is not None else 1.0))[:20]
    lines += [f"## 20 largest disagreements with Haiku (arm {fa}) — for a human look", "",
              "Agreement = mean of segment F1, head-noun recall, OCR similarity (if applicable) and category "
              "agreement (if Haiku gave one). Low means *different from Haiku*, not necessarily *wrong*.", ""]
    flagged = []
    for m in worst:
        c = clips_by_id[m["id"]]
        fr = c["frames"]
        fpaths = [str(frame_abs(doc, f["path"])) for f in fr]
        rec = m.get("_rec") or {}
        pred = (rec.get("result") or {}).get("segments") or []
        base = c["baseline"]["segments"]
        lines += [f"### clip {m['id']} — {c['share']}/{c['rel_path']} ({m['stratum']}, {c['duration_s']:.0f}s, {len(fr)} frames)",
                  f"agreement {_f(m['agreement'])} · seg F1 {_f(m['seg_f1'])} · head recall {_f(m['head_recall_any'])} · "
                  f"OCR sim {_f(m.get('ocr_sim'))} · cat {m.get('cat_pred')} vs Haiku {c['baseline'].get('category_hint')} · status {m['status']}",
                  f"frames: `{fpaths[0]}` … (`{Path(fpaths[0]).parent}`)", "",
                  "| | Haiku | local |", "|---|---|---|",
                  f"| segments | {len(base)} | {len(pred)} |"]
        for i in range(max(len(base), len(pred))):
            b = base[i] if i < len(base) else None
            p = pred[i] if i < len(pred) else None
            bt = f"{b['t_start']:.0f}–{b['t_end']:.0f}s {b['description'][:110]}" + (f" ⟨{b['onscreen_text'][:60]}⟩" if b['onscreen_text'] else "") if b else ""
            pt = f"{p['t_start']:.0f}–{p['t_end']:.0f}s {p['description'][:110]}" + (f" ⟨{p['onscreen_text'][:60]}⟩" if p.get('onscreen_text') else "") if p else ""
            lines.append(f"| {i+1} | {bt.replace('|', '¦')} | {pt.replace('|', '¦')} |")
        lines.append("")
        flagged.append({"id": m["id"], "agreement": m["agreement"], "frames_dir": str(Path(fpaths[0]).parent),
                        "rel_path": c["rel_path"], "share": c["share"], "stratum": m["stratum"]})
    summary["flagged"] = flagged
    summary["per_clip"] = {a: [{k: v for k, v in m.items() if k not in ("_rec", "matches", "call_s", "tg_tps", "pp_tps")}
                               for m in per_arm[a]] for a in arms}
    return "\n".join(lines) + "\n", summary


def _count(it):
    d: dict[str, int] = {}
    for x in it:
        d[x] = d.get(x, 0) + 1
    return d


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results-dir", type=Path, default=HERE / "results")
    ap.add_argument("--clips", type=Path, default=None,
                    help="defaults to <results-dir>/../clips.json when the results dir sits beside one, else clips.json here")
    ap.add_argument("--recategorize", action="store_true",
                    help="re-assign category_hint for arms A/B on this machine (so a Mac run scored here uses fastembed too)")
    ap.add_argument("--category", choices=["auto", "fastembed", "tfidf"], default="auto")
    args = ap.parse_args()

    clips_path = args.clips
    if clips_path is None:
        cand = [args.results_dir / "clips.json", args.results_dir.parent / "clips.json", DEFAULT_CLIPS]
        clips_path = next((c for c in cand if c.exists()), DEFAULT_CLIPS)
    doc = load_clips(clips_path)
    clips_by_id = {c["id"]: c for c in doc["clips"]}
    slugs = {t["slug"] for t in doc.get("taxonomy") or []}

    per_arm: dict[str, list[dict]] = {}
    metas: dict[str, dict] = {}
    recat = None
    if args.recategorize:
        recat = CategoryAssigner(doc.get("taxonomy") or [], prefer=args.category)
    for arm in ARMS_ORDER:
        p = args.results_dir / f"{arm}.jsonl"
        recs = read_jsonl(p)
        if not recs:
            continue
        mp = args.results_dir / f"{arm}.meta.json"
        metas[arm] = json.loads(mp.read_text(encoding="utf-8")) if mp.exists() else {}
        ms = []
        for r in recs:
            c = clips_by_id.get(r["id"])
            if not c:
                continue
            if recat is not None and arm != "C" and r.get("result"):
                slug, sc = recat.assign(clip_text_for_category(r["result"]))
                r["result"]["category_hint"] = slug
                r["result"]["category_method"] = recat.method
            m = score_clip(r, c, slugs)
            m["cat_method"] = (r.get("result") or {}).get("category_method")
            m["_rec"] = r
            ms.append(m)
        per_arm[arm] = ms
        print(f"arm {arm}: {len(ms)} clips scored")
    if not per_arm:
        raise SystemExit(f"no <arm>.jsonl in {args.results_dir}")
    report, summary = build_report(args.results_dir, doc, per_arm, metas, recat.method if recat else None)
    (args.results_dir / "report.md").write_text(report, encoding="utf-8")
    (args.results_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {args.results_dir / 'report.md'} and summary.json")
    for a, ms in per_arm.items():
        ag = summary["arms"][a]["overall"]
        print(f"  {a}: n={ag['n']} valid={ag['valid_rate']} segF1={ag['seg_f1']} headRecall={ag['head_recall_any']} "
              f"ocrSim={ag['ocr_sim']} cat={ag['cat_agree']} wall/clip={ag['wall_s_mean']}s")


if __name__ == "__main__":
    main()
