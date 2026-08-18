"""The v7 COMPACT format for the local-VLM backend: prompt builder, GBNF
grammar, tolerant parser, nearest-neighbour category assignment, and pixel-stat
exposure flags.

This is the package's OWN copy of `broll/eval/local_vlm/format.py` — the eval
harness that proved this design out (`broll/docs/local-indexing-options-2026-08-17.md`
§3, `broll/eval/local_vlm/results/report.md`) is left untouched on purpose, so
its numbers stay reproducible against exactly the code that produced them.
This copy is the one `local_vlm.py` actually calls in production, and it is the
one this package's tests exercise.

Why compact, recapped from the eval doc: a 4B model spent its budget on JSON
punctuation, invented timecodes, and looped. Here the model gets frames
labelled F1..Fn with their timecodes IN THE TEXT and answers one line per shot:

    S F1-F3 | terse description | obj;obj;obj | onscreen text or - // english or -
    T theme;theme

Segment times are LOOKED UP from the frame table (never trusted from the
model), category is assigned in code by nearest neighbour, and exposure flags
come from pixel statistics. `parse_compact` returns the exact dict shape
`claude_client.validate_contract` accepts, and calls it to prove that.
"""
from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any, Sequence

from .claude_client import validate_contract

PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "index_clip_v7_compact.md"


def seconds_to_tc(s: float) -> str:
    s = max(0, int(round(s)))
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


# ---------------------------------------------------------------------------
# prompt
# ---------------------------------------------------------------------------

def frame_table(frames: Sequence[dict[str, Any]]) -> str:
    """`F1=00:00:00 F2=00:00:04 ...` — one token-cheap line the model can index."""
    return " ".join(f"F{i + 1}={f['tc']}" for i, f in enumerate(frames))


def build_compact_prompt(frames: Sequence[dict[str, Any]]) -> str:
    return PROMPT_PATH.read_text(encoding="utf-8").replace("__FRAME_TABLE__", frame_table(frames))


# ---------------------------------------------------------------------------
# GBNF grammar (llama.cpp `grammar` request field)
# ---------------------------------------------------------------------------

def build_grammar(n_frames: int, max_desc: int = 220, max_objs: int = 300,
                  max_text: int = 300, max_themes: int = 160) -> str:
    """Grammar for one window of `n_frames` frames.

    - F ids limited to F1..Fn (no F12 on a 9-frame window),
    - at most n_frames S lines (a shot needs at least one frame),
    - exactly one T line, then the grammar is exhausted so the only legal next
      token is EOS — this, not the sampler, is what ends a repetition loop,
    - every free-text field is length-bounded ({1,N} repetition), so a runaway
      description cannot eat the token budget either,
    - a text field is EITHER the single "-" OR text that does not start with a
      dash/space (the eval's smoke test saw the model keep writing after a
      bare "-" on the same line otherwise) — the grammar must make the newline
      the only continuation of a "-".
    `[^|\\n\\r→]` matches any codepoint but the separators, so CJK is fine.
    """
    n = max(1, int(n_frames))
    fids = " | ".join(f'"F{i}"' for i in range(1, n + 1))
    lines = [
        f"root ::= sline{{1,{n}}} tline",
        r'sline ::= "S " frange " | " desc " | " objs " | " ostext " // " ostext "\n"',
        'frange ::= fid | fid "-" fid',
        f"fid ::= {fids}",
        f"desc ::= tstart fchar{{0,{max_desc - 1}}}",
        f"objs ::= tstart fchar{{0,{max_objs - 1}}}",
        f'ostext ::= "-" | tstart fchar{{0,{max_text - 1}}}',
        f'tline ::= "T " tstart fchar{{0,{max_themes - 1}}} "\\n"?',
        r"tstart ::= [^|\n\r→ -]",   # a literal '-' must come last in a GBNF class; '\-' is an unknown escape
        r"fchar ::= [^|\n\r→]",
    ]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# parser
# ---------------------------------------------------------------------------

_S_LINE = re.compile(r"^\s*(?:[-*]\s*)?S(?:\d+)?\s*[:.]?\s*(F.*)$", re.IGNORECASE)
_T_LINE = re.compile(r"^\s*(?:[-*]\s*)?(?:T|themes?)\s*[:.]?\s+(.*)$", re.IGNORECASE)
_FID = re.compile(r"F\s*(\d+)", re.IGNORECASE)
_NONE_WORDS = {"-", "—", "–", "none", "n/a", '""', "''", "(none)", "no text", "null"}


def _parse_range(token: str, n: int) -> tuple[int, int] | None:
    ids = [int(m) for m in _FID.findall(token)]
    if not ids:
        ids = [int(m) for m in re.findall(r"\d+", token)]  # bare "1-3" — tolerated
    if not ids:
        return None
    a, b = min(ids), max(ids)
    a = min(max(a, 1), n)
    b = min(max(b, 1), n)
    return a - 1, b - 1


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def _dash_to_empty(s: str) -> str:
    s = _clean(s)
    return "" if s.lower() in _NONE_WORDS else s


def _split_list(s: str) -> list[str]:
    s = _dash_to_empty(s)
    if not s:
        return []
    parts = re.split(r"[;；]", s) if (";" in s or "；" in s) else re.split(r"[,，]", s)
    out, seen = [], set()
    for p in parts:
        p = _clean(p).strip(".").strip()
        if p and p.lower() not in seen:
            seen.add(p.lower())
            out.append(p)
    return out


def parse_compact_lines(text: str, n_frames: int) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    """-> (shots, themes, problems). Tolerant: unknown lines are recorded in
    `problems`, not fatal; missing fields default to empty."""
    shots: list[dict[str, Any]] = []
    themes: list[str] = []
    problems: list[str] = []
    text = (text or "").replace("```", "")
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = _S_LINE.match(line)
        if m:
            fields = m.group(1).split("|")
            rng = _parse_range(fields[0], n_frames)
            if rng is None:
                problems.append(f"no frame id: {line[:80]}")
                continue
            desc = _clean(fields[1]) if len(fields) > 1 else ""
            objs = _split_list(fields[2]) if len(fields) > 2 else []
            # everything after the 3rd '|' is the text field; on-screen text can
            # itself contain ' | ' (v6 joins pieces with it), so re-join.
            rest = " | ".join(f.strip() for f in fields[3:]) if len(fields) > 3 else ""
            if "//" in rest:
                ost, _, ost_en = rest.rpartition("//")
            else:
                ost, ost_en = rest, ""
            shots.append({
                "f_start": rng[0], "f_end": rng[1],
                "description": desc, "objects": objs,
                "onscreen_text": _dash_to_empty(ost),
                "onscreen_text_en": _dash_to_empty(ost_en),
            })
            if len(fields) < 4:
                problems.append(f"short S line ({len(fields)} fields): {line[:80]}")
            continue
        m = _T_LINE.match(line)
        if m:
            themes.extend(_split_list(m.group(1)))
            continue
        problems.append(f"unparsed: {line[:80]}")
    return shots, themes, problems


def parse_compact(text: str, frames: Sequence[dict[str, Any]]) -> tuple[dict[str, Any], list[str]]:
    """Parse one window's model text into the v6 CONTRACT dict (validated by
    claude_client.validate_contract) plus a list of tolerated problems.

    Segment times come from the frame table, never from the model. `setting`
    and `motion` are not asked for in the compact format and are ''.
    Raises ValueError (like parse_claude_response) when nothing usable came back.
    """
    shots, themes, problems = parse_compact_lines(text, len(frames))
    if not shots:
        raise ValueError("no S lines parsed" + (f" ({problems[0]})" if problems else ""))
    segments = []
    for s in shots:
        segments.append({
            "t_start": float(frames[s["f_start"]]["t"]),
            "t_end": float(frames[s["f_end"]]["t"]),
            "description": s["description"],
            "objects": s["objects"],
            "setting": "",
            "motion": "",
            "onscreen_text": s["onscreen_text"],
            "onscreen_text_en": s["onscreen_text_en"],
            # extra bookkeeping the contract ignores; handy for the merge step
            "f_start": s["f_start"], "f_end": s["f_end"],
        })
    obj = {"themes": themes, "category_hint": None, "quality_flags": [], "segments": segments}
    return validate_contract(obj), problems


# ---------------------------------------------------------------------------
# category by nearest neighbour (fastembed if importable, else TF-IDF)
# ---------------------------------------------------------------------------

_WORD = re.compile(r"[a-z0-9]+|[一-鿿]")


def _tokens(s: str) -> list[str]:
    return _WORD.findall((s or "").lower())


class CategoryAssigner:
    """slug = argmax cosine(embed(clip text), embed(slug label + description)).

    Uses the SAME fastembed model as the indexer's embed stage
    (sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2) when
    fastembed is importable, so the assignment lives in the space search
    already uses; otherwise a plain TF-IDF cosine over word/CJK-char tokens.
    `.method` says which one ran.
    """

    def __init__(self, taxonomy: Sequence[dict[str, str]], min_score: float = 0.15,
                 prefer: str = "auto", cache_dir: str = "") -> None:
        self.taxonomy = list(taxonomy)
        self.slugs = [t["slug"] for t in self.taxonomy]
        self.texts = [f"{t.get('label') or t['slug']}. {t.get('description') or ''}".strip()
                      for t in self.taxonomy]
        self.min_score = min_score
        self.method = "none"
        self._model = None
        self._mat = None
        self.fastembed_error = ""
        self._cache_dir = cache_dir
        if not self.taxonomy:
            return
        if prefer in ("auto", "fastembed"):
            try:
                from fastembed import TextEmbedding  # type: ignore
                kwargs = {"cache_dir": cache_dir} if cache_dir else {}
                self._model = TextEmbedding(
                    model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
                    **kwargs)
                self._mat = self._embed(self.texts)
                self.method = "fastembed:paraphrase-multilingual-MiniLM-L12-v2"
                return
            except Exception as e:  # noqa: BLE001 — fall through to TF-IDF
                if prefer == "fastembed":
                    raise
                self.fastembed_error = str(e)[:200]
                self._model = None
        self._build_tfidf()

    def _embed(self, texts):
        import numpy as np
        v = np.array(list(self._model.embed(list(texts))), dtype="float32")
        n = np.linalg.norm(v, axis=1, keepdims=True) + 1e-9
        return v / n

    def _build_tfidf(self):
        docs = [_tokens(t) for t in self.texts]
        df: dict[str, int] = {}
        for d in docs:
            for w in set(d):
                df[w] = df.get(w, 0) + 1
        n = len(docs)
        self._idf = {w: math.log((n + 1) / (c + 1)) + 1 for w, c in df.items()}
        self._docvecs = [self._tfidf_vec(d) for d in docs]
        self.method = "tfidf"

    def _tfidf_vec(self, toks: list[str]) -> dict[str, float]:
        tf: dict[str, float] = {}
        for w in toks:
            tf[w] = tf.get(w, 0) + 1
        vec = {w: c * self._idf.get(w, 1.0) for w, c in tf.items()}
        norm = math.sqrt(sum(x * x for x in vec.values())) or 1.0
        return {w: x / norm for w, x in vec.items()}

    def assign(self, clip_text: str) -> tuple[str | None, float]:
        if not self.taxonomy or not clip_text.strip():
            return None, 0.0
        if self._model is not None:
            import numpy as np
            q = self._embed([clip_text])[0]
            sims = self._mat @ q
            i = int(np.argmax(sims))
            best = float(sims[i])
        else:
            q = self._tfidf_vec(_tokens(clip_text))
            sims = [sum(q.get(w, 0) * x for w, x in d.items()) for d in self._docvecs]
            i = max(range(len(sims)), key=lambda k: sims[k])
            best = float(sims[i])
        if best < self.min_score:
            return None, best
        return self.slugs[i], best


def clip_text_for_category(result: dict[str, Any]) -> str:
    parts = list(result.get("themes") or [])
    for s in result.get("segments") or []:
        parts.append(s.get("description") or "")
        objs = s.get("objects")
        parts.append("; ".join(objs) if isinstance(objs, list) else str(objs or ""))
    return ". ".join(p for p in parts if p)


# ---------------------------------------------------------------------------
# quality flags from pixels
# ---------------------------------------------------------------------------

def frame_stats(path: Path) -> dict[str, float]:
    """Luminance mean, clipped-dark/bright fractions and a Laplacian-variance
    sharpness proxy, on a 480px-wide grey copy. Pillow only."""
    from PIL import Image, ImageFilter, ImageStat
    im = Image.open(path).convert("L")
    if im.width > 480:
        im = im.resize((480, max(1, round(im.height * 480 / im.width))))
    hist = im.histogram()
    n = float(sum(hist)) or 1.0
    dark = sum(hist[:16]) / n
    bright = sum(hist[250:]) / n
    mean = ImageStat.Stat(im).mean[0]
    lap = im.filter(ImageFilter.Kernel((3, 3), [0, 1, 0, 1, -4, 1, 0, 1, 0], scale=1, offset=128))
    var = ImageStat.Stat(lap).var[0]
    return {"mean": round(mean, 1), "dark": round(dark, 3), "bright": round(bright, 3),
            "lapvar": round(var, 1)}


def pixel_quality_flags(paths: Sequence[Path], share: float = 0.3) -> tuple[list[str], list[dict]]:
    """Clip-level exposure flags from per-frame stats.

    overexposed  : >= `share` of frames have mean > 200 or >= 25 % of pixels clipped white
    underexposed : >= `share` of NON-black frames have mean < 45 (a black frame is
                   content, not an exposure fault)
    soft_focus   : OPTIONAL heuristic, median Laplacian variance < 20 across the
                   non-black frames; reported but do not read much into it.
    Returns (flags, per_frame_stats).
    """
    stats = []
    for p in paths:
        try:
            st = frame_stats(Path(p))
        except Exception as e:  # noqa: BLE001
            st = {"error": str(e)[:80]}
        stats.append(st)
    ok = [s for s in stats if "error" not in s]
    if not ok:
        return [], stats
    for s in ok:
        s["black"] = bool(s["mean"] < 12 and s["dark"] > 0.95)
    non_black = [s for s in ok if not s["black"]]
    flags = []
    over = [s for s in ok if s["mean"] > 200 or s["bright"] >= 0.25]
    if over and len(over) / len(ok) >= share:
        flags.append("overexposed")
    if non_black:
        under = [s for s in non_black if s["mean"] < 45]
        if under and len(under) / len(non_black) >= share:
            flags.append("underexposed")
        lv = sorted(s["lapvar"] for s in non_black)
        if lv[len(lv) // 2] < 20:
            flags.append("soft_focus")
    return flags, stats
