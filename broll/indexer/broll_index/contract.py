"""The index CONTRACT: the dict shape every describing backend must produce,
its validator, and the per-window merge.

Split out of `claude_client.py` on 2026-08-18 (docs/BROLL_INGEST_PLAN.md §3.4).
Nothing here CHANGED in the move — claude_client re-imports every name below,
so `from broll_index.claude_client import validate_contract` still resolves and
every existing caller and test keeps its import.

Why it moved at all: the local backend's modules (`compact_format`,
`local_vlm`) are VENDORED VERBATIM INTO THE COMPANION (plan §3.3), a frozen
PyInstaller build that has no `anthropic`, no `xxhash`, no `requests` and no
`pyyaml` — and they needed exactly these three functions from claude_client,
whose import pulls the Anthropic SDK in. So this module imports NOTHING but
the stdlib and must stay that way: an import added here is an import added to
every editor's tray app.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


QUALITY_FLAG_VOCAB = {"shaky", "soft_focus", "overexposed", "underexposed", "noisy", "rolling_shutter"}


# Canonical labels for shots with no searchable visual content (see the prompt's
# "Shots with no usable visuals" section). Their whole value is being exactly
# matchable — so an editor can find newsreader cutaways, and more usefully
# exclude them — which only works if the spelling is consistent. The model
# varies capitalization ("newsreader" vs "Newsreader") and occasionally
# punctuates, so normalize here rather than relying on it to comply.
NO_VISUAL_LABELS = ("newsreader", "title card", "black frame", "colour bars", "station ident")

# Tolerated variants that mean the same shot, mapped to the canonical label.
_LABEL_ALIASES = {
    "news reader": "newsreader",
    "news anchor": "newsreader",
    "anchor": "newsreader",
    "presenter": "newsreader",
    "talking head": "newsreader",
    "color bars": "colour bars",
    "test pattern": "colour bars",
    "titles": "title card",
    "title cards": "title card",
    "blank frame": "black frame",
    "channel ident": "station ident",
    "ident": "station ident",
}


def canonicalize_no_visual_label(description: str) -> str:
    """Return the canonical label if `description` is one, else the input unchanged."""
    stripped = (description or "").strip().strip(".").strip()
    key = stripped.lower()
    if key in NO_VISUAL_LABELS:
        return key
    return _LABEL_ALIASES.get(key, description)


def validate_contract(obj: Any) -> dict[str, Any]:
    """Raise ValueError if `obj` doesn't match the index_clip.md JSON contract."""
    if not isinstance(obj, dict):
        raise ValueError("claude response is not a JSON object")

    required = {"themes", "category_hint", "quality_flags", "segments"}
    missing = required - obj.keys()
    if missing:
        raise ValueError(f"claude response missing keys: {sorted(missing)}")

    if not isinstance(obj["themes"], list):
        raise ValueError("themes must be a list")
    if not isinstance(obj["quality_flags"], list):
        raise ValueError("quality_flags must be a list")
    if not isinstance(obj["segments"], list):
        raise ValueError("segments must be a list")

    # Drop out-of-vocabulary flags rather than failing the clip. The prompt asks
    # for a fixed vocabulary, but a model occasionally invents a plausible one
    # ('pixelated' was seen on the real archive) — and discarding an entire
    # video's index, after paying for every one of its contact-sheet calls, is a
    # far worse outcome than losing one advisory tag. The schema's CHECK
    # constraint would reject the unknown value at write time anyway.
    unknown = [f for f in obj["quality_flags"] if f not in QUALITY_FLAG_VOCAB]
    if unknown:
        obj = {**obj, "quality_flags": [f for f in obj["quality_flags"]
                                        if f in QUALITY_FLAG_VOCAB]}

    required_seg_keys = {"t_start", "t_end", "description", "objects", "setting", "motion"}
    for i, seg in enumerate(obj["segments"]):
        if not isinstance(seg, dict):
            raise ValueError(f"segment {i} is not an object")
        missing_seg = required_seg_keys - seg.keys()
        if missing_seg:
            raise ValueError(f"segment {i} missing keys: {sorted(missing_seg)}")

    # PRESENT-BUT-NULL is not the same as missing, and only the check above was
    # being made. A segment carrying `"t_end": null` or `"setting": null` passed
    # validation and then died at the INSERT on a NOT NULL column, which threw
    # away the whole clip's index after every one of its contact-sheet calls had
    # already been paid for. Three clips on the real archive failed exactly this
    # way (segments.t_end x2, segments.setting x1) and would have failed
    # identically on every future run.
    #
    # The two kinds of field need opposite treatment:
    #   - the text fields all have DEFAULT '' in the schema and mean "nothing
    #     found", so a null coerces to "" exactly like _normalize_onscreen_text
    #     already does one block below;
    #   - t_start/t_end cannot be invented. A segment with no time cannot be put
    #     on a timeline, so it is DROPPED and the rest of the clip is kept --
    #     the same trade already made for out-of-vocabulary quality flags above.
    # `objects` is a LIST in the contract (the writer ", "-joins it); the rest
    # are plain strings. Coercing it to "" would silently drop every object
    # keyword on the clip, which is most of what makes it findable.
    _STR_SEG_FIELDS = ("description", "setting", "motion")
    timed_segments = []
    dropped = 0
    for seg in obj["segments"]:
        if isinstance(seg.get("t_start"), bool) or isinstance(seg.get("t_end"), bool) \
                or not isinstance(seg.get("t_start"), (int, float)) \
                or not isinstance(seg.get("t_end"), (int, float)):
            dropped += 1
            continue
        timed_segments.append({
            **seg,
            **{k: (seg[k] if isinstance(seg.get(k), str) else "")
               for k in _STR_SEG_FIELDS},
            "objects": seg["objects"] if isinstance(seg.get("objects"), list) else [],
        })
    if dropped and not timed_segments:
        # Every segment was untimed: there is nothing to write, and silently
        # marking the clip indexed with zero segments would hide that.
        raise ValueError(
            f"all {dropped} segment(s) had a null or non-numeric t_start/t_end")
    if dropped:
        logger.warning("dropped %d segment(s) with no usable t_start/t_end; "
                       "keeping the remaining %d", dropped, len(timed_segments))
    obj = {**obj, "segments": timed_segments}

    # `onscreen_text`/`onscreen_text_en` are required keys per SPEC.md's v2 contract, but
    # they are deliberately NOT enforced as strictly as required_seg_keys above: failing
    # the whole segment (and burning the retry, and then the whole clip's index pass and
    # its token spend) over a model dropping an optional-feeling text field is a worse
    # outcome than just treating a missing value as "no on-screen text found". So we
    # default rather than raise, and normalize whatever shape comes back (including the
    # list-of-strings shape models sometimes use despite the prompt asking for a single
    # " | "-joined string). Built as a new list of new dicts rather than mutating `seg`
    # in place, so this function stays a pure transform of its input, like the rest of
    # this module.
    normalized_segments = [
        {
            **seg,
            "description": canonicalize_no_visual_label(seg.get("description", "")),
            "onscreen_text": _normalize_onscreen_text(seg.get("onscreen_text")),
            "onscreen_text_en": _normalize_onscreen_text(seg.get("onscreen_text_en")),
        }
        for seg in obj["segments"]
    ]

    return {**obj, "segments": normalized_segments}


def _normalize_onscreen_text(value: Any) -> str:
    """Coerce a segment's onscreen_text/onscreen_text_en value into a plain string.

    - missing / None -> ""
    - a list of strings (models sometimes return one piece of on-screen text per list
      item despite the prompt asking for a single string) -> " | "-joined
    - any other non-string value -> "" (never fail the segment over this field)
    """
    if isinstance(value, list):
        return " | ".join(str(v) for v in value)
    if isinstance(value, str):
        return value
    return ""


def merge_index_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Merge per-window claude results into one: union themes/flags, concat segments,
    first non-null category_hint wins.
    """
    themes: list[str] = []
    seen_themes: set[str] = set()
    flags: list[str] = []
    seen_flags: set[str] = set()
    segments: list[dict[str, Any]] = []
    category_hint = None

    for result in results:
        for t in result.get("themes", []):
            if t not in seen_themes:
                seen_themes.add(t)
                themes.append(t)
        for f in result.get("quality_flags", []):
            if f not in seen_flags:
                seen_flags.add(f)
                flags.append(f)
        segments.extend(result.get("segments", []))
        if category_hint is None and result.get("category_hint"):
            category_hint = result["category_hint"]

    return {
        "themes": themes,
        "quality_flags": flags,
        "category_hint": category_hint,
        "segments": segments,
    }
