"""`taxonomy propose` / `taxonomy apply`."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

from .claude_client import InvokeFn, extract_claude_text, invoke_claude
from .storage.base import Storage

TAXONOMY_PROMPT_TEMPLATE = """\
You are designing a category taxonomy for a b-roll video library, based on the themes
that have been observed across the whole library so far. Themes are free-text tags
generated per-clip and may repeat; the count after each theme is how many clips it
appeared on.

Cluster these themes into a hierarchical taxonomy of category slugs, two levels deep,
e.g. `military/naval`, `nature/wildlife`, `urban/traffic`. Every category needs:

- `slug` — lowercase, `/`-separated, no spaces (e.g. `military/naval`)
- `label` — human-readable name (e.g. "Naval / Military Ships")
- `description` — one sentence on what belongs in this category

Observed themes:

__THEME_LIST__

Write your answer as a human-readable Markdown document: a level-2 heading per top-level
group, a bullet list of proposed slugs underneath each with their label and description.
End with a fenced ```yaml``` block containing the full list as
`categories: [{slug, label, description}, ...]` so a human reviewer can copy it directly
into a `taxonomy.yaml` file for `broll-index taxonomy apply`.
"""


def propose_taxonomy(
    storage: Storage,
    *,
    model: str = "sonnet",
    out_path: str | Path = "taxonomy_proposal.md",
    invoke: InvokeFn = invoke_claude,
) -> Path:
    themes = storage.all_themes()
    if not themes:
        raise ValueError("no themes indexed yet; run `broll-index run` first")

    counts = Counter(themes)
    theme_lines = "\n".join(f"- {theme} (x{count})" for theme, count in counts.most_common())
    prompt = TAXONOMY_PROMPT_TEMPLATE.replace("__THEME_LIST__", theme_lines)

    raw = invoke(prompt, model)
    text = extract_claude_text(raw)

    out_path = Path(out_path)
    out_path.write_text(text, encoding="utf-8")
    return out_path


def load_taxonomy_file(path: str | Path) -> list[dict[str, Any]]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict) and "categories" in data:
        categories = data["categories"]
    elif isinstance(data, list):
        categories = data
    else:
        raise ValueError("taxonomy.yaml must be a list of categories, or {categories: [...]}")

    for c in categories:
        missing = {"slug", "label"} - c.keys()
        if missing:
            raise ValueError(f"taxonomy entry missing keys {missing}: {c}")
    return categories


def apply_taxonomy_file(storage: Storage, path: str | Path) -> list[dict[str, Any]]:
    categories = load_taxonomy_file(path)
    storage.apply_taxonomy(categories)
    return categories


# --- rule-based assignment ----------------------------------------------------
#
# Themes are free text, one clip generates several, and there are 8,899 distinct
# ones across the archive with 75% appearing on exactly one video. Folders built
# from themes directly would be thousands of one-clip categories. These rules map
# many themes onto one subject folder instead.


def compile_patterns(patterns: list[str]) -> list[re.Pattern]:
    """`recycl*` -> prefix match; anything else -> whole word.

    Word boundaries are not optional here. Plain substring matching put 314
    videos in animals-pets because `cat` matches "education" and "category",
    and swept "transport" into sport. The correct count is 37.
    """
    out = []
    for p in patterns:
        if p.endswith("*"):
            out.append(re.compile(r"\b" + re.escape(p[:-1]) + r"\w*", re.IGNORECASE))
        else:
            out.append(re.compile(r"\b" + re.escape(p) + r"\b", re.IGNORECASE))
    return out


def score_categories(
    themes: list[str], categories: list[dict[str, Any]]
) -> dict[str, int]:
    """How many of this clip's themes each category matches. 0-scoring categories
    are omitted."""
    scores: dict[str, int] = {}
    for cat in categories:
        pats = compile_patterns(cat.get("match") or [])
        if not pats:
            continue
        n = sum(1 for t in themes if any(r.search(t) for r in pats))
        if n:
            scores[cat["slug"]] = n
    return scores


def pick_category(
    themes: list[str],
    categories: list[dict[str, Any]],
    breadth: dict[str, int] | None = None,
) -> str | None:
    """The single best subject folder for one clip, or None if nothing matches.

    A clip averages 2.17 matching subjects (1,173 of 1,904 covered videos match
    two or more), so with one home per clip the tie-break IS the design:

      1. most matching themes wins — the clip's dominant subject;
      2. then the NARROWER category, measured by how many videos it holds
         archive-wide. Without this the broad folders swallow everything: a
         reactor clip tagged both `nuclear` and `government-politics` belongs in
         nuclear, because "politics" (416 videos) tells an editor far less than
         "nuclear" (161);
      3. then slug order, so the result never depends on dict ordering.
    """
    scores = score_categories(themes, categories)
    if not scores:
        return None
    breadth = breadth or {}
    return min(
        scores,
        key=lambda slug: (-scores[slug], breadth.get(slug, 0), slug),
    )


def assign_categories(
    storage: Storage, path: str | Path, *, dry_run: bool = False,
    reassign: bool = False,
) -> dict[str, Any]:
    """Assign each UNCATEGORISED indexed video its best subject folder.

    Two passes on purpose: the first measures how broad each category actually is
    on THIS archive, so the tie-break in pick_category() reflects real populations
    rather than a hand-guessed priority list that would rot as the archive grows.

    CATEGORIES ARE STABLE. A clip that already has one keeps it, even if improved
    rules would now put it somewhere better. The category is part of the clip's
    path in the shared archive (`Downloads/<category>/Proxy/<name>.mp4`), that
    path is stored on the row, and editors' timelines point at it -- so moving a
    clip between categories moves a file out from under a cut that already uses
    it. Improving the rules therefore only ever affects clips with no category
    yet; existing ones are left exactly where they are.

    `reassign=True` overrides that for a deliberate, supervised migration. It
    will silently invalidate archive paths, so anything already referencing them
    has to be relinked afterwards.
    """
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    categories = load_taxonomy_file(path)
    # Applied ONLY to clips no real subject matched. Kept as a separate list,
    # not appended to `categories`, so a fallback can never outrank a subject:
    # "news broadcast" would otherwise beat "nuclear" on any clip whose themes
    # mention both, and most of the archive mentions both.
    fallbacks = data.get("fallback_categories") or []

    themes_by_video: dict[int, list[str]] = {}
    for video_id, text in storage.themes_with_video_ids():
        themes_by_video.setdefault(video_id, []).append(text)

    # Breadth (pass 1) is still measured across EVERY clip, categorised or not:
    # it describes how broad a subject is in this archive, which does not change
    # just because some clips are already filed. Only the writing is restricted.
    already = {v["id"] for v in storage.videos_by_status(["indexed"]) if v.get("category")}
    kept = 0 if reassign else len(already)

    # Pass 1 — breadth: how many videos each category matches at all.
    breadth: dict[str, int] = {c["slug"]: 0 for c in categories}
    per_video_scores: dict[int, dict[str, int]] = {}
    for vid, themes in themes_by_video.items():
        scores = score_categories(themes, categories)
        per_video_scores[vid] = scores
        for slug in scores:
            breadth[slug] += 1

    # Pass 2 — one winner each, subjects only.
    assigned: dict[str, int] = {}
    unmatched: list[int] = []
    for vid, scores in per_video_scores.items():
        if not reassign and vid in already:
            continue  # stable: never move a clip that is already filed
        if not scores:
            unmatched.append(vid)
            continue
        slug = min(scores, key=lambda s: (-scores[s], breadth.get(s, 0), s))
        assigned[slug] = assigned.get(slug, 0) + 1
        if not dry_run:
            storage.update_video(vid, category=slug)

    # Pass 3 — the leftovers. These describe only how the footage was shot
    # ("news broadcast", "interior", "daytime") with no subject to file them
    # under, so they get a fallback rather than a `_uncategorised` pile nobody
    # opens. Same tie-break, scored only against the fallback tier.
    fb_breadth: dict[str, int] = {}
    fb_scores: dict[int, dict[str, int]] = {}
    for vid in unmatched:
        s = score_categories(themes_by_video[vid], fallbacks)
        fb_scores[vid] = s
        for slug in s:
            fb_breadth[slug] = fb_breadth.get(slug, 0) + 1

    default_cat = data.get("default_category") or None
    still_unmatched: list[int] = []
    for vid in unmatched:
        s = fb_scores[vid]
        if not s:
            # Nothing matched at all. With a default configured every clip gets
            # a folder; without one it stays uncategorised, which is the older
            # behaviour and still valid.
            if default_cat:
                slug = default_cat["slug"]
                assigned[slug] = assigned.get(slug, 0) + 1
                if not dry_run:
                    storage.update_video(vid, category=slug)
            else:
                still_unmatched.append(vid)
            continue
        slug = min(s, key=lambda x: (-s[x], fb_breadth.get(x, 0), x))
        assigned[slug] = assigned.get(slug, 0) + 1
        if not dry_run:
            storage.update_video(vid, category=slug)

    if not dry_run:
        storage.apply_taxonomy(
            [*categories, *fallbacks, *([default_cat] if default_cat else [])])

    return {
        "categories": len(categories) + len(fallbacks),
        "videos_considered": len(themes_by_video),
        "kept": kept,
        "assigned": sum(assigned.values()),
        "by_fallback": len(unmatched) - len(still_unmatched),
        "unmatched": len(still_unmatched),
        "per_category": assigned,
        "breadth": breadth,
        "descriptors": data.get("descriptors") or {},
    }
