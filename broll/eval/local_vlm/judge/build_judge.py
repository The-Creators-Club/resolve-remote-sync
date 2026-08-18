"""Build judge.html: a self-contained, offline page for a HUMAN to blind-judge
the local-VLM b-roll indexing eval against the Haiku baseline and each other.

Why a static page and not a little Flask app: the eval already produces
everything it needs (clips.json's frames + baseline, results/*.jsonl, the
portable bundle/) and the judging session has exactly one user on their own
machine — a page that opens with a double-click has no server to keep
running, no port to free before the next companion loopback test, and
survives a reboot via localStorage. See judge/README.md for the open/serve
split (file:// works in Chrome/Edge; Firefox needs judge/serve.py).

Inputs (read-only — this script must never touch clips.json, results/*, or
the harness scripts, per the eval's own rule that Haiku is a *reference*):
  --clips PATH        defaults to bundle/clips.json (NOT the top-level
                       clips.json) because only the bundle has a frames_root
                       that is relative and small enough to ship — the frame
                       image <img> src values are computed relative to the
                       bundle, so judge.html only works if the bundle exists
                       (docs/README.md tells you to run make_bundle.py first).
  --source LABEL=PATH one VLM's results/<arm>.jsonl (or the literal path
                       "baseline" for the Haiku segments already inside
                       clips.json); repeatable. Default (no --source given):
                       haiku=baseline, local-4b=results/A.jsonl, plus every
                       results-mac/<model>/A.jsonl this checkout currently has
                       (add a model later by re-running this script — no code
                       change needed).
  --order              disagreement (default) | random | id. "disagreement"
                       front-loads the 20 clips results/summary.json flagged
                       as furthest from Haiku (arm A) — the clips most worth
                       a human's time — then the rest in a seeded shuffle so
                       every rebuild without --limit still covers all 100.
  --limit N            judge only the first N clips of that order.

Output: judge.html next to this script (gitignored — rebuild it, don't
version the generated file; see judge/.gitignore). The blind label<->source
mapping is NOT decided here: each browser generates and persists its own
per-clip shuffle in localStorage on first view, so two people judging from
the same judge.html see different, but each internally consistent, letter
assignments (docs/README.md).
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
from pathlib import Path, PurePosixPath
from typing import Any

JUDGE_DIR = Path(__file__).resolve().parent
LOCAL_VLM_DIR = JUDGE_DIR.parent
if str(LOCAL_VLM_DIR) not in sys.path:
    sys.path.insert(0, str(LOCAL_VLM_DIR))
from common import frame_abs, load_clips, read_jsonl  # noqa: E402  (sys.path side effect above)

DEFAULT_CLIPS = LOCAL_VLM_DIR / "bundle" / "clips.json"
DEFAULT_SUMMARY = LOCAL_VLM_DIR / "results" / "summary.json"
DEFAULT_SEED = 20260817  # the clips.json selection seed — reused so re-running with the
                          # same inputs reproduces the same non-disagreement ordering


# ---------------------------------------------------------------------------
# source loading — normalises both shapes clips.json/results ever hand us:
# baseline "objects" is a comma-joined STRING (Haiku's v6 prompt asked for a
# flat noun list), predicted "objects" is already a list (format.py's parser).
# ---------------------------------------------------------------------------

def _objects_list(objs: Any) -> list[str]:
    if isinstance(objs, list):
        return [str(x).strip() for x in objs if str(x).strip()]
    if isinstance(objs, str):
        return [x.strip() for x in objs.split(",") if x.strip()]
    return []


def _segment(seg: dict[str, Any]) -> dict[str, Any]:
    return {
        "t_start": float(seg.get("t_start") or 0.0),
        "t_end": float(seg.get("t_end") or 0.0),
        "description": str(seg.get("description") or ""),
        "objects": _objects_list(seg.get("objects")),
        "onscreen_text": str(seg.get("onscreen_text") or ""),
        "onscreen_text_en": str(seg.get("onscreen_text_en") or ""),
    }


def baseline_records(doc: dict[str, Any]) -> dict[int, dict[str, Any]]:
    out = {}
    for c in doc["clips"]:
        b = c["baseline"]
        out[c["id"]] = {
            "status": "ok", "error": "",
            "themes": list(b.get("themes") or []),
            "quality_flags": list(b.get("quality_flags") or []),
            "category_hint": b.get("category") or b.get("category_hint"),
            "category_approved": b.get("category"),
            "segments": [_segment(s) for s in (b.get("segments") or [])],
        }
    return out


def result_records(path: Path) -> dict[int, dict[str, Any]]:
    out = {}
    for r in read_jsonl(path):
        res = r.get("result") or {}
        out[r["id"]] = {
            "status": r.get("status") or "error", "error": r.get("error") or "",
            "themes": list(res.get("themes") or []),
            "quality_flags": list(res.get("quality_flags") or []),
            "category_hint": res.get("category_hint"),
            "category_approved": None,
            "segments": [_segment(s) for s in (res.get("segments") or [])],
        }
    return out


def default_sources() -> list[tuple[str, str]]:
    """[(label, path-or-'baseline'), ...] — 'baseline' is a sentinel, never a
    real file path, so it can't collide with a results/*.jsonl on disk."""
    out = [("haiku", "baseline")]
    local4b = LOCAL_VLM_DIR / "results" / "A.jsonl"
    if local4b.exists():
        out.append(("local-4b", str(local4b)))
    for p in sorted(LOCAL_VLM_DIR.glob("results-mac/*/A.jsonl")):
        out.append((p.parent.name, str(p)))
    return out


def source_display(label: str, path: str) -> str:
    """label plus, if a sibling <arm>.meta.json exists, the model + host —
    the string revealed to the judge after they vote (never before)."""
    if path == "baseline":
        return f"{label} (Haiku claude-haiku-4-5-20251001, the archive's index)"
    meta_path = Path(path).with_suffix("").with_suffix(".meta.json")
    if not meta_path.exists():
        return label
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return label
    model = meta.get("model_label") or "?"
    host = meta.get("host_label") or meta.get("host") or "?"
    return f"{label} ({model}, {host})"


# ---------------------------------------------------------------------------
# ordering
# ---------------------------------------------------------------------------

def disagreement_ids(summary_path: Path) -> list[int]:
    """The 20 clip ids results/summary.json's build_report flagged as the
    largest disagreement with Haiku (arm A), worst first. Falls back to
    regex-scraping report.md's '### clip NNNN' headings under the
    disagreement section if summary.json is missing (older results dirs)."""
    if summary_path.exists():
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            return [int(f["id"]) for f in summary.get("flagged") or []]
        except (OSError, json.JSONDecodeError, KeyError, TypeError):
            pass
    report_path = summary_path.parent / "report.md"
    if report_path.exists():
        text = report_path.read_text(encoding="utf-8")
        section = text.split("largest disagreements", 1)
        if len(section) > 1:
            return [int(m) for m in re.findall(r"^### clip (\d+)", section[1], re.MULTILINE)]
    return []


def order_clip_ids(doc: dict[str, Any], order: str, seed: int, summary_path: Path) -> list[int]:
    all_ids = [c["id"] for c in doc["clips"]]
    if order == "id":
        return sorted(all_ids)
    if order == "random":
        ids = list(all_ids)
        random.Random(seed).shuffle(ids)
        return ids
    if order == "disagreement":
        worst = [i for i in disagreement_ids(summary_path) if i in set(all_ids)]
        rest = [i for i in all_ids if i not in set(worst)]
        random.Random(seed).shuffle(rest)
        return worst + rest
    raise ValueError(f"unknown --order {order!r}")


# ---------------------------------------------------------------------------
# frame URLs — relative to wherever --out ends up, so the page still works if
# it is copied somewhere other than judge/ (as long as bundle/ moves with it).
# ---------------------------------------------------------------------------

def frame_url_root(doc: dict[str, Any], out_dir: Path) -> str:
    frames_root: Path = doc["_frames_root"]
    try:
        rel = os.path.relpath(frames_root, out_dir)
        return PurePosixPath(rel.replace("\\", "/")).as_posix()
    except ValueError:
        # different drive on Windows (e.g. --clips points at the un-bundled
        # E:\broll-queue\sheets while judge.html is being built on the repo's
        # own drive) — a file:// absolute URI still opens locally, it just
        # stops being portable to another machine. --clips defaults to the
        # bundle precisely so this branch is not the common case.
        return frames_root.as_uri()


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------

def build_data(doc: dict[str, Any], sources: list[tuple[str, str]], order: str, seed: int,
               limit: int | None, summary_path: Path, out_dir: Path) -> tuple[dict[str, Any], int, int]:
    clips_by_id = {c["id"]: c for c in doc["clips"]}
    slug_to_label = {t["slug"]: t.get("label") or t["slug"] for t in doc.get("taxonomy") or []}
    url_root = frame_url_root(doc, out_dir)

    loaded: dict[str, dict[int, dict[str, Any]]] = {}
    for label, path in sources:
        loaded[label] = baseline_records(doc) if path == "baseline" else result_records(Path(path))

    ids = order_clip_ids(doc, order, seed, summary_path)
    if limit is not None:
        ids = ids[:limit]

    n_frames_total = 0
    n_frames_missing = 0
    clips_out = []
    for cid in ids:
        c = clips_by_id[cid]
        frames = []
        for f in c["frames"]:
            rel = f["path"].replace("\\", "/")
            frames.append({"i": f["i"], "t": f["t"], "tc": f["tc"], "url": f"{url_root}/{rel}"})
            n_frames_total += 1
            if not frame_abs(doc, f["path"]).exists():
                n_frames_missing += 1
        srcs = {}
        for label, _ in sources:
            rec = loaded[label].get(cid)
            if rec is None:
                srcs[label] = None
                continue
            rec = dict(rec)
            cat = rec.get("category_hint")
            rec["category_label"] = slug_to_label.get(cat, cat)
            srcs[label] = rec
        clips_out.append({
            "id": cid, "share": c["share"], "rel_path": c["rel_path"],
            "duration_s": c["duration_s"], "stratum": c["stratum"],
            "frames": frames, "sources": srcs,
        })

    data = {
        "generated_at": doc.get("generated_at"),
        "order": order, "seed": seed,
        "sources": [{"key": label, "display": source_display(label, path)} for label, path in sources],
        "clips": clips_out,
    }
    return data, n_frames_total, n_frames_missing


HTML_HEAD = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>local-VLM b-roll eval — judge</title>
<style>
"""

CSS = r"""
:root {
  --bg: #0a0a0d;
  --panel: #101014;
  --field: #17171c;
  --red: #ff2140;
  --red-hot: #ff5c73;
  --red-dim: #7c1322;
  --text: #e8e8ea;
  --muted: #6f6f7a;
  --ok: #2ecc71;
  --warn: #e8a33d;
}
* { box-sizing: border-box; }
html, body { height: 100%; }
body {
  margin: 0; background: var(--bg); color: var(--text);
  font-family: Consolas, Menlo, "DejaVu Sans Mono", monospace;
  font-size: 16px; line-height: 1.4;
}
button, input, textarea, select { font-family: inherit; font-size: inherit; }
a { color: var(--red-hot); }

#app { display: flex; flex-direction: column; height: 100vh; overflow: hidden; }

.topbar {
  display: flex; align-items: center; gap: 1rem; padding: 0.6rem 1rem;
  border-bottom: 1px solid var(--red-dim); background: var(--panel); flex: 0 0 auto;
}
.topbar .brand { color: var(--red); font-weight: bold; letter-spacing: 0.04em; }
.topbar .progress { font-size: 1.1rem; }
.topbar .spacer { flex: 1; }
.topbar button {
  background: var(--field); color: var(--text); border: 1px solid var(--red-dim);
  padding: 0.35rem 0.8rem; cursor: pointer;
}
.topbar button:hover { border-color: var(--red); color: var(--red-hot); }
.topbar .clip-meta { color: var(--muted); font-size: 0.9rem; }

.filmstrip-wrap { flex: 0 0 auto; border-bottom: 1px solid var(--red-dim); background: var(--panel); padding: 0.5rem 1rem; }
.filmstrip { display: flex; gap: 6px; overflow-x: auto; padding-bottom: 4px; }
.frame-thumb { flex: 0 0 auto; text-align: center; cursor: pointer; border: 2px solid transparent; }
.frame-thumb img { display: block; width: 96px; height: 54px; object-fit: cover; background: #000; }
.frame-thumb .tc { font-size: 0.7rem; color: var(--muted); }
.frame-thumb.hl-hover { border-color: var(--warn); }
.frame-thumb.hl-pin { border-color: var(--red); box-shadow: 0 0 6px rgba(255, 33, 64, 0.7); }
.frame-thumb.hl-pin .tc, .frame-thumb.hl-hover .tc { color: var(--text); }
.big-frame { display: none; margin-top: 0.5rem; }
.big-frame.shown { display: block; }
.big-frame img { max-height: 260px; border: 1px solid var(--red-dim); }

.columns {
  flex: 1 1 auto; display: grid; grid-auto-flow: column; grid-auto-columns: 1fr;
  gap: 1px; background: var(--red-dim); overflow: hidden; min-height: 0;
}
.column { background: var(--bg); display: flex; flex-direction: column; min-width: 0; min-height: 0; }
.column.focused { outline: 2px solid var(--red); outline-offset: -2px; }
.column-head {
  flex: 0 0 auto; padding: 0.5rem 0.7rem; background: var(--panel); cursor: pointer;
  border-bottom: 1px solid var(--red-dim); display: flex; align-items: baseline; gap: 0.5rem;
}
.column-head .letter { color: var(--red); font-weight: bold; font-size: 1.2rem; }
.column-head .revealed-name { color: var(--muted); font-size: 0.85rem; word-break: break-word; }
.column-body { flex: 1 1 auto; overflow-y: auto; padding: 0.6rem 0.7rem; }
.column-vote { flex: 0 0 auto; padding: 0.5rem 0.7rem; border-top: 1px solid var(--red-dim); background: var(--panel); }

.segment { border: 1px solid var(--red-dim); padding: 0.4rem 0.5rem; margin-bottom: 0.5rem; cursor: pointer; }
.segment:hover, .segment.hl-hover { border-color: var(--warn); background: var(--field); }
.segment.hl-pin { border-color: var(--red); background: var(--field); box-shadow: 0 0 6px rgba(255, 33, 64, 0.5); }
.segment .t { color: var(--muted); font-size: 0.8rem; }
.segment .desc { margin: 0.15rem 0; }
.segment .objs { color: var(--red-hot); font-size: 0.85rem; }
.segment .ocr { font-size: 0.85rem; color: var(--warn); }
.segment .ocr .en { color: var(--muted); }
.no-result { color: var(--muted); font-style: italic; }

.chips { display: flex; flex-wrap: wrap; gap: 4px; margin: 0.3rem 0; }
.chip { border: 1px solid var(--red-dim); padding: 0.1rem 0.4rem; font-size: 0.8rem; color: var(--muted); }
.chip.flag { border-color: var(--warn); color: var(--warn); }
.meta-block { margin-top: 0.6rem; padding-top: 0.5rem; border-top: 1px dashed var(--red-dim); }
.meta-block .label { color: var(--muted); font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em; }
.category-line { font-size: 0.9rem; margin-top: 0.2rem; }

.score-row { display: flex; align-items: center; gap: 0.4rem; margin-bottom: 0.35rem; }
.score-row .score-btn {
  background: var(--field); color: var(--text); border: 1px solid var(--red-dim);
  width: 1.8rem; height: 1.8rem; cursor: pointer;
}
.score-row .score-btn.active { background: var(--red); border-color: var(--red); color: var(--bg); font-weight: bold; }
.score-row .score-btn:hover { border-color: var(--red-hot); }
.best-row label { display: flex; align-items: center; gap: 0.35rem; margin-bottom: 0.35rem; cursor: pointer; }
.flags-row { display: flex; flex-wrap: wrap; gap: 0.5rem; margin-bottom: 0.2rem; }
.flags-row label { display: flex; align-items: center; gap: 0.25rem; font-size: 0.85rem; cursor: pointer; }

.note-row { flex: 0 0 auto; padding: 0.5rem 1rem; border-top: 1px solid var(--red-dim); background: var(--panel); }
.note-row textarea {
  width: 100%; background: var(--field); color: var(--text); border: 1px solid var(--red-dim);
  padding: 0.4rem; resize: vertical; min-height: 2.4rem;
}

.summary-panel {
  position: fixed; top: 0; right: 0; width: 420px; height: 100vh; background: var(--panel);
  border-left: 1px solid var(--red-dim); padding: 1rem; overflow-y: auto; display: none; z-index: 10;
}
.summary-panel.shown { display: block; }
.summary-panel h2 { color: var(--red); margin-top: 0; }
.summary-panel table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
.summary-panel th, .summary-panel td { border-bottom: 1px solid var(--red-dim); padding: 0.25rem 0.3rem; text-align: left; }
.summary-panel .close-btn { float: right; cursor: pointer; color: var(--muted); }

.hint { color: var(--muted); font-size: 0.75rem; }
"""

HTML_TAIL = """
</style>
</head>
<body>
<div id="app">
  <div class="topbar">
    <span class="brand">JUDGE</span>
    <span class="progress" id="progress">-/-</span>
    <span class="clip-meta" id="clip-meta"></span>
    <span class="spacer"></span>
    <span class="hint">&larr;/&rarr; clip &middot; click column then 1-5 to score</span>
    <button id="btn-export">Export verdicts.json</button>
    <button id="btn-import">Import</button>
    <input type="file" id="file-import" accept="application/json" style="display:none">
    <button id="btn-summary">Summary</button>
  </div>
  <div class="filmstrip-wrap">
    <div class="filmstrip" id="filmstrip"></div>
    <div class="big-frame" id="big-frame"><img id="big-frame-img"></div>
  </div>
  <div class="columns" id="columns"></div>
  <div class="note-row">
    <textarea id="note" placeholder="notes for this clip (saved as you type)"></textarea>
  </div>
</div>
<div class="summary-panel" id="summary-panel">
  <span class="close-btn" id="summary-close">&times; close</span>
  <h2>Summary (clips judged so far)</h2>
  <div id="summary-body"></div>
</div>
<script id="eval-data" type="application/json">
__EVAL_DATA__
</script>
<script>
__JS__
</script>
</body>
</html>
"""

JS = r"""
(function () {
"use strict";

var DATA = JSON.parse(document.getElementById("eval-data").textContent);
var LS_PREFIX = "brolljudge_v1_";
var LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";
var FLAG_DEFS = ["hallucinated", "missed_shot", "ocr_wrong", "over_segmented"];
var FLAG_LABELS = {hallucinated: "hallucinated", missed_shot: "missed the shot",
                   ocr_wrong: "OCR wrong", over_segmented: "over-segmented"};
var HL_PAD = 2.0; // seconds either side of a segment's [t_start,t_end] a frame still counts as "in" it —
                   // Haiku's baseline segments are captioned on arbitrary times, not frame timestamps

var state = { idx: 0, focusedCol: 0, pinned: null };

function lsGet(key) {
  var raw = localStorage.getItem(LS_PREFIX + key);
  return raw ? JSON.parse(raw) : null;
}
function lsSet(key, val) { localStorage.setItem(LS_PREFIX + key, JSON.stringify(val)); }

function shuffledSourceKeys(seedTag) {
  var keys = DATA.sources.map(function (s) { return s.key; });
  for (var i = keys.length - 1; i > 0; i--) {
    var j = Math.floor(Math.random() * (i + 1));
    var t = keys[i]; keys[i] = keys[j]; keys[j] = t;
  }
  return keys;
}

function getVerdict(clip) {
  var v = lsGet("verdict_" + clip.id);
  if (!v) {
    v = { clipId: clip.id, revealed: false, shuffle: shuffledSourceKeys(),
         scores: {}, flags: {}, best: null, note: "", ts: null };
    lsSet("verdict_" + clip.id, v);
  }
  // a clip re-judged after --source changed the source list still needs every
  // current source represented in the shuffle, and no stale ones
  var known = {};
  DATA.sources.forEach(function (s) { known[s.key] = true; });
  v.shuffle = v.shuffle.filter(function (k) { return known[k]; });
  DATA.sources.forEach(function (s) { if (v.shuffle.indexOf(s.key) === -1) v.shuffle.push(s.key); });
  return v;
}

function saveVerdict(v) { v.ts = new Date().toISOString(); lsSet("verdict_" + v.clipId, v); }

function displayFor(key) {
  var s = DATA.sources.filter(function (x) { return x.key === key; })[0];
  return s ? s.display : key;
}

function el(tag, attrs, children) {
  var e = document.createElement(tag);
  attrs = attrs || {};
  Object.keys(attrs).forEach(function (k) {
    if (k === "class") e.className = attrs[k];
    else if (k === "text") e.textContent = attrs[k];
    else if (k === "html") e.innerHTML = attrs[k];
    else if (k.indexOf("data-") === 0) e.setAttribute(k, attrs[k]);
    else e[k] = attrs[k];
  });
  (children || []).forEach(function (c) { if (c) e.appendChild(c); });
  return e;
}

// -------------------------------------------------------------------------
// filmstrip
// -------------------------------------------------------------------------

function renderFilmstrip(clip) {
  var strip = document.getElementById("filmstrip");
  strip.innerHTML = "";
  clip.frames.forEach(function (f) {
    var img = el("img", {src: f.url, loading: "lazy", alt: f.tc});
    var tc = el("div", {class: "tc", text: f.tc});
    var thumb = el("div", {class: "frame-thumb", "data-t": f.t}, [img, tc]);
    thumb.addEventListener("click", function () { onFrameClick(f, thumb); });
    strip.appendChild(thumb);
  });
}

function onFrameClick(frame, thumbEl) {
  var big = document.getElementById("big-frame");
  var bigImg = document.getElementById("big-frame-img");
  bigImg.src = frame.url;
  big.classList.add("shown");
  var pinned = state.pinned && state.pinned.type === "frame" && state.pinned.t === frame.t;
  clearPins();
  if (!pinned) {
    state.pinned = {type: "frame", t: frame.t};
    applyPins();
  }
}

function frameCoversSeg(t, seg) {
  return t >= (seg.t_start - HL_PAD) && t <= (seg.t_end + HL_PAD);
}

function clearPins() {
  document.querySelectorAll(".hl-pin").forEach(function (e) { e.classList.remove("hl-pin"); });
  state.pinned = null;
}

function applyPins() {
  if (!state.pinned) return;
  if (state.pinned.type === "frame") {
    var t = state.pinned.t;
    document.querySelectorAll(".frame-thumb").forEach(function (th) {
      if (parseFloat(th.getAttribute("data-t")) === t) th.classList.add("hl-pin");
    });
    document.querySelectorAll(".segment").forEach(function (seg) {
      var a = parseFloat(seg.getAttribute("data-tstart")), b = parseFloat(seg.getAttribute("data-tend"));
      if (frameCoversSeg(t, {t_start: a, t_end: b})) seg.classList.add("hl-pin");
    });
  } else if (state.pinned.type === "segment") {
    var a = state.pinned.a, b = state.pinned.b;
    document.querySelectorAll(".frame-thumb").forEach(function (th) {
      var t2 = parseFloat(th.getAttribute("data-t"));
      if (frameCoversSeg(t2, {t_start: a, t_end: b})) th.classList.add("hl-pin");
    });
    if (state.pinnedEl) state.pinnedEl.classList.add("hl-pin");
  }
}

function hoverFrames(a, b, on) {
  document.querySelectorAll(".frame-thumb").forEach(function (th) {
    var t = parseFloat(th.getAttribute("data-t"));
    if (frameCoversSeg(t, {t_start: a, t_end: b})) th.classList.toggle("hl-hover", on);
  });
}

// -------------------------------------------------------------------------
// columns
// -------------------------------------------------------------------------

function renderSegment(seg, segEl) {
  var t = el("div", {class: "t", text: fmtT(seg.t_start) + "\u2013" + fmtT(seg.t_end)});
  var desc = el("div", {class: "desc", text: seg.description || "(no description)"});
  var parts = [t, desc];
  if (seg.objects && seg.objects.length) {
    parts.push(el("div", {class: "objs", text: seg.objects.join(", ")}));
  }
  if (seg.onscreen_text) {
    var enSpan = seg.onscreen_text_en ? (" \u2192 " + seg.onscreen_text_en) : "";
    parts.push(el("div", {class: "ocr"}, [
      document.createTextNode(seg.onscreen_text),
      el("span", {class: "en", text: enSpan}),
    ]));
  }
  parts.forEach(function (p) { segEl.appendChild(p); });
}

function fmtT(s) {
  s = Math.round(s);
  var m = Math.floor(s / 60), sec = s % 60;
  return m + ":" + (sec < 10 ? "0" : "") + sec;
}

function renderColumn(clip, verdict, colIdx, letter, sourceKey) {
  var rec = clip.sources[sourceKey];
  var head = el("div", {class: "column-head"}, [
    el("span", {class: "letter", text: letter}),
    verdict.revealed ? el("span", {class: "revealed-name", text: displayFor(sourceKey)}) : null,
  ]);
  var body = el("div", {class: "column-body"});
  if (!rec) {
    body.appendChild(el("div", {class: "no-result", text: "(no result for this clip from this source)"}));
  } else if (rec.status !== "ok" && (!rec.segments || !rec.segments.length)) {
    body.appendChild(el("div", {class: "no-result", text: "status: " + rec.status + (rec.error ? " \u2014 " + rec.error : "")}));
  } else {
    (rec.segments || []).forEach(function (seg) {
      var segEl = el("div", {class: "segment", "data-tstart": seg.t_start, "data-tend": seg.t_end});
      renderSegment(seg, segEl);
      segEl.addEventListener("mouseenter", function () { if (!state.pinned) hoverFrames(seg.t_start, seg.t_end, true); });
      segEl.addEventListener("mouseleave", function () { if (!state.pinned) hoverFrames(seg.t_start, seg.t_end, false); });
      segEl.addEventListener("click", function (ev) {
        ev.stopPropagation();
        var already = state.pinned && state.pinned.type === "segment" && state.pinnedEl === segEl;
        clearPins();
        if (!already) {
          state.pinned = {type: "segment", a: seg.t_start, b: seg.t_end};
          state.pinnedEl = segEl;
          applyPins();
        }
      });
      body.appendChild(segEl);
    });
    var meta = el("div", {class: "meta-block"});
    if (rec.themes && rec.themes.length) {
      meta.appendChild(el("div", {class: "label", text: "themes"}));
      var themeChips = el("div", {class: "chips"});
      rec.themes.forEach(function (t) { themeChips.appendChild(el("span", {class: "chip", text: t})); });
      meta.appendChild(themeChips);
    }
    if (rec.quality_flags && rec.quality_flags.length) {
      var qfChips = el("div", {class: "chips"});
      rec.quality_flags.forEach(function (f) { qfChips.appendChild(el("span", {class: "chip flag", text: f})); });
      meta.appendChild(qfChips);
    }
    if (rec.category_hint) {
      var catLine = rec.category_approved
        ? ("category: " + rec.category_approved + (rec.category_hint !== rec.category_approved ? " (hint: " + rec.category_hint + ")" : ""))
        : ("category: " + (rec.category_label || rec.category_hint));
      meta.appendChild(el("div", {class: "category-line", text: catLine}));
    }
    body.appendChild(meta);
  }

  var vote = el("div", {class: "column-vote"});
  var scoreRow = el("div", {class: "score-row"}, [el("span", {class: "hint", text: "accuracy "})]);
  for (var s = 1; s <= 5; s++) {
    (function (score) {
      var btn = el("button", {class: "score-btn" + (verdict.scores[sourceKey] === score ? " active" : ""), text: String(score)});
      btn.addEventListener("click", function (ev) { ev.stopPropagation(); setScore(clip, verdict, sourceKey, score); });
      scoreRow.appendChild(btn);
    })(s);
  }
  vote.appendChild(scoreRow);

  var bestLabel = el("label", {}, [
    el("input", {type: "radio", name: "best-" + clip.id, checked: verdict.best === sourceKey}),
    document.createTextNode(" best"),
  ]);
  bestLabel.querySelector("input").addEventListener("change", function () { setBest(clip, verdict, sourceKey); });
  vote.appendChild(el("div", {class: "best-row"}, [bestLabel]));

  var flagsRow = el("div", {class: "flags-row"});
  FLAG_DEFS.forEach(function (fk) {
    var checked = (verdict.flags[sourceKey] || []).indexOf(fk) !== -1;
    var lbl = el("label", {}, [
      el("input", {type: "checkbox", checked: checked}),
      document.createTextNode(" " + FLAG_LABELS[fk]),
    ]);
    lbl.querySelector("input").addEventListener("change", function (ev) {
      toggleFlag(clip, verdict, sourceKey, fk, ev.target.checked);
    });
    flagsRow.appendChild(lbl);
  });
  vote.appendChild(flagsRow);

  // a click on any vote control (radio/checkbox/button) must NOT bubble to the
  // column's own click handler below: that handler does a synchronous innerHTML
  // rebuild, and if it runs during a checkbox/radio click's bubble phase the
  // element is detached before the browser's post-click activation step fires
  // "change" — the vote is silently dropped (found via a Playwright repro: the
  // checkbox's own .checked flipped but no "change" handler ever ran)
  vote.addEventListener("click", function (ev) { ev.stopPropagation(); });

  var col = el("div", {class: "column" + (state.focusedCol === colIdx ? " focused" : "")}, [head, body, vote]);
  col.addEventListener("click", function () {
    state.focusedCol = colIdx;
    clearPins(); // renderColumns below rebuilds the segment DOM; a stale pinned-segment
                 // reference would silently stop highlighting anything, so drop it instead
    renderColumns(clip, verdict);
  });
  return col;
}

function renderColumns(clip, verdict) {
  var wrap = document.getElementById("columns");
  wrap.innerHTML = "";
  verdict.shuffle.forEach(function (key, i) {
    wrap.appendChild(renderColumn(clip, verdict, i, LETTERS[i], key));
  });
}

function reveal(verdict) { if (!verdict.revealed) verdict.revealed = true; }

function setScore(clip, verdict, key, score) {
  verdict.scores[key] = (verdict.scores[key] === score) ? undefined : score;
  if (verdict.scores[key] === undefined) delete verdict.scores[key];
  reveal(verdict);
  saveVerdict(verdict);
  renderClip(state.idx);
}

function setBest(clip, verdict, key) {
  verdict.best = key;
  reveal(verdict);
  saveVerdict(verdict);
  renderClip(state.idx);
}

function toggleFlag(clip, verdict, key, flag, on) {
  var list = verdict.flags[key] || [];
  var i = list.indexOf(flag);
  if (on && i === -1) list.push(flag);
  if (!on && i !== -1) list.splice(i, 1);
  verdict.flags[key] = list;
  reveal(verdict);
  saveVerdict(verdict);
  renderClip(state.idx);
}

// -------------------------------------------------------------------------
// clip navigation
// -------------------------------------------------------------------------

function renderClip(idx) {
  state.idx = idx;
  lsSet("pos", idx);
  var clip = DATA.clips[idx];
  var verdict = getVerdict(clip);
  document.getElementById("progress").textContent = (idx + 1) + "/" + DATA.clips.length;
  document.getElementById("clip-meta").textContent =
    clip.share + "/" + clip.rel_path + "  \u00b7  " + clip.stratum + "  \u00b7  " + Math.round(clip.duration_s) + "s";
  document.getElementById("note").value = verdict.note || "";
  document.getElementById("big-frame").classList.remove("shown");
  state.pinned = null;
  renderFilmstrip(clip);
  renderColumns(clip, verdict);
  renderSummary();
}

function nav(delta) {
  var next = state.idx + delta;
  if (next < 0 || next >= DATA.clips.length) return;
  renderClip(next);
}

document.addEventListener("keydown", function (ev) {
  var tag = document.activeElement.tagName;
  if (tag === "TEXTAREA" || tag === "INPUT") return;
  if (ev.key === "ArrowRight") { nav(1); ev.preventDefault(); }
  else if (ev.key === "ArrowLeft") { nav(-1); ev.preventDefault(); }
  else if (ev.key >= "1" && ev.key <= "5") {
    var clip = DATA.clips[state.idx];
    var verdict = getVerdict(clip);
    var key = verdict.shuffle[state.focusedCol];
    if (key) setScore(clip, verdict, key, parseInt(ev.key, 10));
  }
});

document.getElementById("note").addEventListener("input", function (ev) {
  var clip = DATA.clips[state.idx];
  var verdict = getVerdict(clip);
  verdict.note = ev.target.value;
  saveVerdict(verdict); // no re-render — would steal the cursor mid-sentence
});

// -------------------------------------------------------------------------
// export / import
// -------------------------------------------------------------------------

function collectVerdicts() {
  var out = [];
  DATA.clips.forEach(function (clip) {
    var v = lsGet("verdict_" + clip.id);
    if (!v) return;
    var hasData = Object.keys(v.scores || {}).length || v.best || (v.note && v.note.trim()) ||
                  Object.keys(v.flags || {}).some(function (k) { return (v.flags[k] || []).length; });
    if (!hasData) return;
    out.push({
      id: clip.id, share: clip.share, rel_path: clip.rel_path, stratum: clip.stratum,
      per_source: DATA.sources.reduce(function (acc, s) {
        var score = v.scores[s.key], flags = v.flags[s.key] || [];
        if (score !== undefined || flags.length) acc[s.key] = {score: score === undefined ? null : score, flags: flags};
        return acc;
      }, {}),
      best: v.best || null, note: v.note || "", revealed: !!v.revealed, ts: v.ts,
    });
  });
  return out;
}

document.getElementById("btn-export").addEventListener("click", function () {
  var payload = {generated_at: new Date().toISOString(), source_build: DATA.generated_at,
                 sources: DATA.sources.map(function (s) { return s.key; }), clips: collectVerdicts()};
  var blob = new Blob([JSON.stringify(payload, null, 1)], {type: "application/json"});
  var a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "verdicts.json";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
});

document.getElementById("btn-import").addEventListener("click", function () {
  document.getElementById("file-import").click();
});
document.getElementById("file-import").addEventListener("change", function (ev) {
  var file = ev.target.files[0];
  if (!file) return;
  var reader = new FileReader();
  reader.onload = function () {
    var payload;
    try { payload = JSON.parse(reader.result); } catch (e) { alert("not valid JSON: " + e); return; }
    (payload.clips || []).forEach(function (row) {
      var v = {clipId: row.id, revealed: true, shuffle: shuffledSourceKeys(),
              scores: {}, flags: {}, best: row.best || null, note: row.note || "", ts: row.ts || null};
      Object.keys(row.per_source || {}).forEach(function (key) {
        var ps = row.per_source[key];
        if (ps.score !== null && ps.score !== undefined) v.scores[key] = ps.score;
        if (ps.flags && ps.flags.length) v.flags[key] = ps.flags;
      });
      saveVerdict(v);
    });
    ev.target.value = "";
    renderClip(state.idx);
    alert("imported " + (payload.clips || []).length + " verdict(s)");
  };
  reader.readAsText(file);
});

// -------------------------------------------------------------------------
// summary panel
// -------------------------------------------------------------------------

function renderSummary() {
  var body = document.getElementById("summary-body");
  if (!document.getElementById("summary-panel").classList.contains("shown")) return;
  var rows = collectVerdicts();
  var stats = {};
  DATA.sources.forEach(function (s) { stats[s.key] = {n: 0, sum: 0, wins: 0, flags: {}}; });
  rows.forEach(function (row) {
    Object.keys(row.per_source).forEach(function (key) {
      var st = stats[key]; if (!st) return;
      var ps = row.per_source[key];
      if (ps.score !== null && ps.score !== undefined) { st.n++; st.sum += ps.score; }
      (ps.flags || []).forEach(function (f) { st.flags[f] = (st.flags[f] || 0) + 1; });
    });
    if (row.best && stats[row.best]) stats[row.best].wins++;
  });
  var html = "<p>" + rows.length + " clip(s) with at least one vote, out of " + DATA.clips.length + " in this build.</p>";
  html += "<table><tr><th>source</th><th>mean score</th><th>n scored</th><th>best picks</th><th>flags</th></tr>";
  DATA.sources.forEach(function (s) {
    var st = stats[s.key];
    var mean = st.n ? (st.sum / st.n).toFixed(2) : "\u2013";
    var flagStr = Object.keys(st.flags).map(function (f) { return FLAG_LABELS[f] + "=" + st.flags[f]; }).join(", ") || "\u2013";
    html += "<tr><td>" + s.key + "</td><td>" + mean + "</td><td>" + st.n + "</td><td>" + st.wins + "</td><td>" + flagStr + "</td></tr>";
  });
  html += "</table>";
  body.innerHTML = html;
}

document.getElementById("btn-summary").addEventListener("click", function () {
  document.getElementById("summary-panel").classList.toggle("shown");
  renderSummary();
});
document.getElementById("summary-close").addEventListener("click", function () {
  document.getElementById("summary-panel").classList.remove("shown");
});

document.addEventListener("click", function (ev) {
  // click anywhere outside a segment/frame clears a pin — the filmstrip and
  // column click handlers above run first and re-pin if that's what fired
  if (!ev.target.closest(".segment") && !ev.target.closest(".frame-thumb")) {
    clearPins();
  }
});

var startIdx = lsGet("pos");
renderClip((typeof startIdx === "number" && startIdx < DATA.clips.length) ? startIdx : 0);

})();
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--clips", type=Path, default=DEFAULT_CLIPS,
                    help=f"default {DEFAULT_CLIPS} (the bundle's copy, for portable relative frame URLs)")
    ap.add_argument("--source", action="append", default=None, metavar="LABEL=PATH",
                    help="repeatable; PATH may be the literal 'baseline'. Replaces the defaults entirely if given.")
    ap.add_argument("--order", choices=["disagreement", "random", "id"], default="disagreement")
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY,
                    help="results dir's summary.json, for --order disagreement")
    ap.add_argument("--out", type=Path, default=JUDGE_DIR / "judge.html")
    args = ap.parse_args()

    if not args.clips.exists():
        raise SystemExit(f"clips file not found: {args.clips}\n"
                          f"(the default expects the bundle — run make_bundle.py in {LOCAL_VLM_DIR} first)")
    doc = load_clips(args.clips)

    if args.source:
        sources = []
        for s in args.source:
            if "=" not in s:
                raise SystemExit(f"--source must be LABEL=PATH, got {s!r}")
            label, path = s.split("=", 1)
            sources.append((label, path))
    else:
        sources = default_sources()
    if not sources:
        raise SystemExit("no sources found (and none given with --source)")
    for label, path in sources:
        if path != "baseline" and not Path(path).exists():
            raise SystemExit(f"source {label!r} not found: {path}")

    data, n_frames_total, n_frames_missing = build_data(
        doc, sources, args.order, args.seed, args.limit, args.summary, args.out.parent)

    # </script> inside a clip description (Chinese news chyrons quote all sorts of
    # things) would otherwise close the data <script> tag early and truncate the page
    data_json = json.dumps(data, ensure_ascii=False).replace("</script", "<\\/script")
    html = (HTML_HEAD + CSS +
            HTML_TAIL.replace("__EVAL_DATA__", data_json)
                     .replace("__JS__", JS))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(html, encoding="utf-8")

    print(f"wrote {args.out} ({args.out.stat().st_size / 1e6:.1f} MB)")
    print(f"  clips: {len(data['clips'])} (order={args.order}, seed={args.seed})")
    print(f"  sources: {', '.join(s['key'] for s in data['sources'])}")
    print(f"  frame images referenced: {n_frames_total}, missing on disk: {n_frames_missing}")
    if n_frames_missing:
        print(f"  WARNING: {n_frames_missing} frame(s) will show broken images — "
              f"re-run make_bundle.py or check --clips points at the right bundle")


if __name__ == "__main__":
    main()
