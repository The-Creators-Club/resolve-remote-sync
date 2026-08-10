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
- `onscreen_text` — **verbatim** text visible in the frame, in its original script, joined
  with `" | "` if there are several pieces. Empty string if there is none. See below.
- `onscreen_text_en` — a short English rendering of `onscreen_text` (translation if it is
  not English, otherwise a copy). Empty string if there is no on-screen text.

## On-screen text matters — do not skip it

Burned-in text is often the most valuable searchable information in a shot, and it is
frequently the only place the actual subject is named. Capture it exactly rather than
paraphrasing it.

Read and transcribe:

- broadcast lower-thirds / chyrons (these usually state the whole story: who, what, where)
- channel and programme names, broadcast dates and on-screen clocks
- signage, banners, shop and street signs, vehicle livery and unit markings
- name plates and title cards identifying a speaker
- licence plates, flight numbers, hull numbers when legible

Transcribe Chinese, Japanese and Korean text in the original characters — do **not**
romanize it — and put the English meaning in `onscreen_text_en`. If text is partly
illegible, transcribe what is readable and stop; never guess at unreadable characters.

Also fold any proper nouns you read (people, places, organisations, operation names,
vessel or aircraft names) into that segment's `objects` list, in **both** the original
script and English, so either query finds the clip.

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
  "themes": ["police operation", "shootout", "Taiwan", "1990s broadcast"],
  "category_hint": "news/crime",
  "quality_flags": ["noisy"],
  "segments": [
    {
      "t_start": 18.0,
      "t_end": 27.0,
      "description": "Officials address reporters outside a police compound, microphones crowded around a spokesman.",
      "objects": ["press conference", "reporters", "microphones", "police officials", "華視", "CTS", "惡龍", "Evil Dragon"],
      "setting": "police compound courtyard, daylight",
      "motion": "static with slow zoom",
      "onscreen_text": "華視新聞 | 警匪激烈槍戰 惡龍中彈落網",
      "onscreen_text_en": "CTS News | Fierce police shootout, suspect 'Evil Dragon' shot and captured"
    }
  ]
}
```
