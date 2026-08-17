"""`taxonomy propose` / `taxonomy apply`."""

from __future__ import annotations

import functools
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
    settings: Any = None,
) -> Path:
    themes = storage.all_themes()
    if not themes:
        raise ValueError("no themes indexed yet; run `broll-index run` first")

    counts = Counter(themes)
    theme_lines = "\n".join(f"- {theme} (x{count})" for theme, count in counts.most_common())
    prompt = TAXONOMY_PROMPT_TEMPLATE.replace("__THEME_LIST__", theme_lines)

    # Text-only call, no contact sheets. `settings` carries the API key
    # resolution (env var or keyfile) from config; an injected fake keeps its
    # plain (prompt, model) signature.
    call = invoke
    if call is invoke_claude:
        call = functools.partial(invoke_claude, settings=settings)
    raw = call(prompt, model)
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


# --- the path prior -----------------------------------------------------------
#
# Themes describe what is IN a clip; the path knows something they cannot, which
# is where it was shot. On our own shoot shares (ff3, ff4) b-roll lives inside
# the interviewee's own folder:
#
#   Whisky/Interviews/黃培峻 Huang Pei-jun/Proxy/clip.mov
#   Nuclear/Interviewees/李桂林 Lee Kui-lin/Proxy/clip.mov
#
# Those cutaways are b-roll OF that person -- their distillery, their office,
# their hands -- and theme rules filed them as general/places, which tells an
# editor looking for "the Huang interview b-roll" nothing at all.
INTERVIEWEE_SLUG = "people/interviewee-broll"

# The trailing `[^/]+/` is load-bearing: the clip must sit INSIDE a person's
# folder, one level or more below the interviews dir. A file loose in
# `Interviews/` is the interview take itself, not b-roll of anyone.
INTERVIEWEE_PATH = re.compile(r"(?:^|/)interview(?:s|ee|ees)?/[^/]+/", re.IGNORECASE)

# Only consulted for clips already inside an interviewee folder, so these can be
# broad without dragging the archive's news packages in with them.
INTERVIEW_THEMES = compile_patterns(
    ["interview*", "talking head*", "testimony", "conversation", "speaking"]
)


def is_interviewee_path(rel_path: str | None) -> bool:
    """Does this clip live inside an interviewee's own folder?

    Backslashes are normalised because rel_path is written by the scanner on
    Windows and read back by rules that think in posix separators.
    """
    return bool(INTERVIEWEE_PATH.search((rel_path or "").replace("\\", "/")))


def has_interview_theme(themes: list[str]) -> bool:
    return any(r.search(t) for t in themes for r in INTERVIEW_THEMES)


def score_categories(
    themes: list[str], categories: list[dict[str, Any]]
) -> dict[str, int]:
    """How many of this clip's themes each category matches. 0-scoring categories
    are omitted.

    A category with no `match` patterns at all is skipped rather than scored 0,
    and that is a feature: it is how a path-prior category like
    INTERVIEWEE_SLUG stays unreachable by theme scoring.
    """
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

    One assignment does not come from themes at all: a clip sitting inside an
    interviewee's folder on our own shoot shares gets INTERVIEWEE_SLUG (see the
    path prior above). It obeys the same stability rule as everything else.
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
    #
    # ONE query, two uses: the same rows carry rel_path for the interviewee path
    # prior below. Asking twice would double the cost of the only full-table read
    # in this function for no new information.
    indexed = storage.videos_by_status(["indexed"])
    already = {v["id"] for v in indexed if v.get("category")}
    rel_paths = {v["id"]: v.get("rel_path") or "" for v in indexed}
    kept = 0 if reassign else len(already)

    # The path prior is refused if the taxonomy file has no such category: it
    # would file clips under a slug with no row in `categories`, i.e. an
    # unlabelled folder in the browser. The rules file owns the label; this
    # module only decides who lands there.
    path_prior = any(c["slug"] == INTERVIEWEE_SLUG for c in categories)

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
    by_path = 0
    for vid, scores in per_video_scores.items():
        if not reassign and vid in already:
            continue  # stable: never move a clip that is already filed
        # The path prior, ahead of the subject rules but NOT ahead of them
        # winning: a clip in an interviewee's folder goes to INTERVIEWEE_SLUG
        # only when its themes say interview, or when nothing else claimed it at
        # all. A nuclear-plant cutaway shot on the way to an interviewee's house
        # is still nuclear footage, and an editor searching the tree for reactors
        # must find it there. This also skips the fallback tier outright --
        # "general/places" is exactly the wrong answer for these clips.
        if (path_prior and is_interviewee_path(rel_paths.get(vid))
                and (not scores or has_interview_theme(themes_by_video[vid]))):
            assigned[INTERVIEWEE_SLUG] = assigned.get(INTERVIEWEE_SLUG, 0) + 1
            by_path += 1
            if not dry_run:
                storage.update_video(vid, category=INTERVIEWEE_SLUG)
            continue
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
        "by_path": by_path,
        "by_fallback": len(unmatched) - len(still_unmatched),
        "unmatched": len(still_unmatched),
        "per_category": assigned,
        "breadth": breadth,
        "descriptors": data.get("descriptors") or {},
    }
