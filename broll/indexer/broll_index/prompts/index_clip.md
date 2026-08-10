You are indexing a clip of b-roll video footage for a searchable library. You are shown a
series of contact-sheet images. Each contact sheet is a 3x3 grid of 9 still frames sampled
from the clip at scene changes. Every cell has its timecode burned in at the bottom-left,
formatted `HH:MM:SS`. These timecodes are **absolute**, measured from the very start of the
whole clip (00:00:00 = the first frame of the clip) — this holds even if you are only being
shown one window of frames from a longer clip, so always report segment boundaries using
these absolute timecodes converted to seconds.

Read each of these contact sheet images before answering:

__SHEET_PATHS__

## What to describe

Break the frames shown into visually distinct segments (a segment is a run of frames that
share a scene / shot / setting). For each segment report:

- `t_start`, `t_end` — seconds from the start of the clip (derive from the burned-in
  absolute timecodes of the first and last frame belonging to that segment).
- `description` — one or two plain-English sentences describing what's on screen.
- `objects` — a list of nouns for everything visible. **This is the most important field for
  search: include synonyms and hypernyms, not just the literal term.** For example, for a
  grey navy frigate, list `navy ship, warship, frigate, military vessel` — not just
  `frigate`. Err on the side of more terms; someone searching plain text for any of them
  should find this clip.
- `setting` — location/environment and lighting, e.g. `"harbor, overcast daylight"`.
- `motion` — camera movement, e.g. `"slow pan left"`, `"static"`, `"handheld tracking shot"`.

## Themes and category

- `themes` — a short list of tags summarizing the whole clip (not per-segment), e.g.
  `["naval exercise", "harbor", "overcast", "telephoto"]`.
- `category_hint` — pick the single best-fitting slug from this approved taxonomy list, or
  `null` if nothing fits (or if the list below is empty, meaning no taxonomy exists yet):

__TAXONOMY_LIST__

## Quality flags

- `quality_flags` — zero or more flags from this **fixed vocabulary only** (do not invent
  new flags): `shaky`, `soft_focus`, `overexposed`, `underexposed`, `noisy`,
  `rolling_shutter`. Use an empty list if none apply.

## Output format

Respond with **STRICT JSON only** — no markdown code fences, no commentary before or after
the JSON, matching exactly this shape:

```json
{
  "themes": ["naval exercise", "harbor", "overcast", "telephoto"],
  "category_hint": "military/naval",
  "quality_flags": ["shaky"],
  "segments": [
    {
      "t_start": 0.0,
      "t_end": 8.5,
      "description": "Grey navy frigate moored at a concrete pier, sailors on deck",
      "objects": ["navy ship", "warship", "frigate", "military vessel", "pier", "sailors"],
      "setting": "harbor, overcast daylight",
      "motion": "slow pan left"
    }
  ]
}
```
