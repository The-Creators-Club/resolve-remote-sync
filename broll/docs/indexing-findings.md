# Indexing findings — first real archive run (FF2 E1, 2026-07-20)

Test corpus: 17 clips / 2.07 h from `FF2 E1 - High Stakes/Archive` — Taiwanese
news packages (police operations, shootouts, prosecutions), Xiamen traffic and
dashcam recordings, and China Eastern aviation material. Indexed with Haiku 4.5.

## Bugs this corpus found (all fixed)

1. **Silent probe failure on non-ASCII media.** `subprocess` decoded ffprobe
   output with the Windows locale codec (cp950/cp1252). The `UnicodeDecodeError`
   is raised on subprocess's *reader thread*, so it never propagates — `stdout`
   became `None` and the pipeline reported a misleading JSON error. Every
   CJK-named file failed; the two ASCII-named ones did not. On a Taiwan-based
   archive this would have hit most of the library.
2. **Phantom frames.** Seeking past the real end of a stream writes no file but
   exits 0. Container duration routinely overstates the decodable stream on
   dashcam/continuous recordings — exactly what this corpus contains.
3. **Timecode misalignment (latent, worst-case).** Frames and timestamps were
   paired *by list position*, so a dropped mid-clip frame would shift every later
   burned-in timecode. Search hits would point at the wrong times while nothing
   looked broken. Frames now carry their timestamp as a pair.

## Quality assessment — Haiku 4.5

Good, and better than expected for the price tier:

- **Synonym expansion works**, which is the whole basis of plain-text search:
  "police vehicle, patrol car, sedan, emergency lights"; "bulletproof vest, body
  armor, protective vest, armor".
- **Segment boundaries track real shot changes** rather than fixed intervals.
- **Quality flags are used and plausible** (`noisy` on 1990s broadcast footage,
  `overexposed` on a bright hillside search).
- **Setting and motion are consistently populated** and useful as search filters.

## Open improvement: on-screen text is being ignored

The single biggest gap. These news packages carry burned-in Chinese chyrons that
name the event, location, and people — e.g. clip 3's lower third reads
「警匪激烈槍戰 惡龍中彈落網」 (fierce police shootout, suspect "Evil Dragon" shot
and captured). The model described the *pictures* ("press briefing", "military
vehicle inspection") but never captured that text, so searching 惡龍, "Evil
Dragon", 華視, or the date would not find this clip.

For a documentary archive this is high-value metadata sitting in plain sight:
broadcast lower-thirds are essentially free structured data about who/what/where.

**Proposed change** (deliberately NOT applied mid-run, to keep this index
internally consistent):

- Add an `onscreen_text` field to the segment contract: verbatim visible text
  (chyrons, signage, plates, timestamps), in its original script.
- Add an `onscreen_text_en` field: a short English gloss, so both a Chinese and
  an English query reach the same clip.
- Index both into FTS alongside `description`/`objects`.
- Note in the prompt that broadcast lower-thirds usually state the story, and
  should be captured verbatim rather than paraphrased.

This needs a schema migration (`segments.onscreen_text`, `onscreen_text_en` +
FTS columns) and a prompt revision, then a re-run of the claude stage only —
proxies and contact sheets are unaffected, so re-indexing is cheap.

## Chinese text is unsearchable under the shipped FTS config

Discovered while designing the on-screen-text change, and it would have applied
to Chinese *descriptions* too. Measured on SQLite 3.49.1:

| query | `porter unicode61` (shipped) | `trigram` |
|---|---|---|
| `惡龍` (2 chars) | MISS | MISS |
| `惡龍中` (3 chars) | MISS | HIT |
| `激烈槍` (3 chars) | MISS | HIT |
| `視新聞` (3 chars) | MISS | HIT |
| `警匪激烈槍戰` (whole run) | HIT | HIT |
| `shoot` (prefix of "shootout") | MISS | HIT |

`unicode61` treats an unbroken run of CJK characters as a **single token**,
because Chinese has no spaces. So indexed text `警匪激烈槍戰 惡龍中彈落網` is only
findable by typing one of those six-character runs in full — every realistic
partial query silently returns nothing. Not an error, just no results, which is
the failure mode most likely to go unnoticed.

`trigram` fixes substring matching for both CJK and English, but is not a free
swap: it has a hard **3-character minimum** (so two-character terms like 惡龍,
警車, 台北 still miss), it loses Porter stemming for English (`ships` no longer
matches `ship`), and substring matching adds false positives (`car` matches
`carpet`).

**Design decision — index each field with the tokenizer that suits it, and union
the results:**

1. Keep `segments_fts` on `porter unicode61` for `description`, `objects`,
   `setting`, `onscreen_text_en` — English stemming and precision preserved.
2. Add `segments_cjk_fts` on `trigram` over `onscreen_text` and `objects` for
   substring matching in Chinese.
3. `/api/search` queries both and merges by best rank.

This also explains why the v2 prompt asks for proper nouns as **discrete entries
in `objects` in both scripts**: `unicode61` splits the comma-separated objects
list on punctuation, so a short term like `惡龍` becomes its own exact-matchable
token — which is what rescues the sub-3-character case that trigram cannot
reach. The two mechanisms are complementary by design, not redundant.

## Audio is a better index than pictures for talking-head footage — and it's free

Prompted by the question "why are we sampling frames every 4s through a newsreader
stretch?". Measured on the RTX 3080 (10 GB) using the existing
`~/tools/whisper` faster-whisper large-v3-turbo setup:

- 73.5 s Mandarin news clip → transcribed in **5.8 s (12.6× realtime)**, GPU-local,
  no API cost, no rate limit. The 2 h corpus would take ~10 min.

What the **visual** index produced for clip 3 (Haiku, contact sheets):

> "officials, personnel, courtyard, building, corridor, government facility",
> "press conference", "military vehicle inspection"

What the **audio** contained for the same clip:

> 侯友宜 (Hou Yu-ih, then police chief — later New Taipei mayor and presidential
> candidate) · 張啟民 (the suspect, by name) · 獵龍專案 ("Operation Dragon Hunt" —
> the source of the 惡龍 nickname) · 霹靂小組 (SWAT) · 裝甲車 (armoured vehicle) ·
> 大寮槍戰 7月26號 (the earlier Daliao shootout it references) · 台中 (location) ·
> named reporters

**None of that is visible in any frame.** Names, operation names, dates, places and
prior events are spoken, not shown. For a documentary archive this is the difference
between "some police footage" and "the Hou Yu-ih raid on Chang Chi-min".

### Consequences for the architecture

1. **Add a `transcribe` stage** (local, free, GPU): timestamped transcript segments
   stored in their own table and indexed in FTS — trigram for the CJK path, same
   dual-tokenizer reasoning as on-screen text. Cheap enough to run over everything
   unconditionally.
2. **Let audio drive visual sampling density.** Where speech is continuous and the
   picture is static (dedup already detects the latter), sample frames sparsely — the
   information is in the words. Reserve dense visual sampling for where the picture
   is actually changing.
3. **Transcription is not a model-quota cost**, so it does not compete with the
   visual indexing budget at all. It runs overnight on hardware already owned.

### Whisper hallucinates on silence — this MUST be filtered

Fed near-silence or steady noise, Whisper does not return nothing; it emits
plausible text from its training data. Measured across the 17-clip corpus, both
long dashcam recordings (road noise, no speech) produced garbage:

| clip | duration | output |
|---|---|---|
| 13 — 行车记录 dashcam | 38.6 min | `字幕志愿者 李宗盛` ×6 (subtitle-credit artifact) |
| 12 — 堵车的日常 dashcam | 22.5 min | `Não sei se` (wrong language entirely) |
| 15 — 能带救护车 | 1.3 min | *(correctly empty — VAD worked)* |

Unfiltered, that dashcam footage becomes findable under 李宗盛 — a well-known
Taiwanese singer who appears nowhere in it. **A confidently wrong hit is worse
than no hit:** an editor who finds nothing searches differently, while one who
gets a plausible-looking wrong result wastes time and stops trusting the tool.

`transcript_quality.py` gates transcripts on four signals: known artifact
strings, repetition loops (one line dominating), too little total content, and
implausible sparsity for the duration (a 38-minute file yielding one sentence is
noise, not speech). Verified against the real corpus: **14 kept, 3 rejected**
(both hallucinations plus the genuinely silent clip), and the artifact blocklist
dropped exactly 6 lines out of 1,590 — no false positives.

Calibration note: thresholds are tuned for CJK, which is far denser than latin
script. An English-tuned minimum (~24 chars) rejected real transcripts —
「警方展開了第一波攻堅行動 雙方爆發了激烈的槍戰」 is two full sentences in 23
characters. Caught by a test, not in production.

Caveat: transcription has errors (華視 came out as 華爾街; one clause garbled). Good
enough for search — a wrong character in one cue does not stop the clip being found
by the other twenty correct terms — but it should not be presented to editors as a
verbatim quote source without checking. Traditional/Simplified normalization (OpenCC
`s2twp`) should be applied for consistency with the rest of the Taiwan workflow.

## Two remaining CJK search gaps, and the fix for both

Found while checking real transcripts. This corpus mixes **Traditional** (Taiwan
news) and **Simplified** (mainland dashcam / aviation) Chinese — as any Taiwan
documentary archive will.

**Gap 1 — script variants don't cross-match.** A Taiwan editor types 廈門堵車;
the mainland clip is indexed as 厦门堵车. Different codepoints, no match, silent
miss.

**Gap 2 — two-character terms are unreachable in free text.** Below trigram's
3-character floor, and (unlike a discrete `objects` entry) not a standalone token
inside a run of prose. 堵車, 槍戰, 警匭, 惡龍 are all exactly the terms an editor
types, and all missed.

**Fix, measured:** at index time, store alongside the raw text a *search blob* =
raw + both script variants, each word-segmented (jieba) into space-separated
tokens. Segmentation makes 堵車 a standalone token that `unicode61` matches
exactly, reaching below trigram's floor; OpenCC (`s2twp` / `tw2sp`) makes the
match script-agnostic in both directions.

| query | raw only | + segmented/normalized blob |
|---|---|---|
| 堵車 / 堵车 (2 char, both scripts) | MISS | **HIT** |
| 廈門 / 厦门 | MISS | **HIT** |
| 槍戰, 惡龍, 警匪 (2 char) | MISS | **HIT** |
| 侯友宜 (3 char name) | HIT | **HIT** |
| 台北, 滑雪 (genuinely absent) | MISS | MISS ✓ |

No false positives — absent terms still correctly miss. Cost is pure CPU text
processing at index time; no model involved. New deps: `jieba`,
`opencc-python-reimplemented`.

Applies to `transcript_segments.text` and `segments.onscreen_text` (and is worth
applying to `objects`, which already carries CJK proper nouns). The raw text stays
untouched for display — only the search blob is derived. Scheduled as migration
**004**, after the v3 transcript work lands.

## Semantic search cannot prove absence — measured, and it constrains the design

Running the query set through the real `/api/search` (not the raw FTS tables)
gave 27/27 recall and **0/5 precision guards** — every query that should return
nothing returned 15–17 videos. Nearest-neighbour retrieval always returns
neighbours; asked for footage that does not exist, it hands back the least
dissimilar clips in the archive, confidently ranked.

Two attempts to gate it, both measured on the corpus:

**Absolute cosine floor — fails.** The distributions overlap:

| | top-1 cosine |
|---|---|
| should match | min 0.477, median 0.641 |
| should NOT match | max 0.642, median 0.429 |

`李宗盛` (a hallucinated singer, absent from the footage) scores **0.642** —
higher than the legitimate "body armor" at 0.477. Chinese queries score highly
against Chinese-language content regardless of meaning. No floor separates them:
at 0.50 it still keeps 13/14 real but leaks 2/9 absent.

**Relative z-score (does the top result spike above the field?) — fails worse.**
Noise queries reached z=5.05, above the median for genuine matches. Combining
both gates was no better.

### Consequence for the design

Semantic retrieval is excellent at *recall* — it is the only thing that bridges
"body armor" to a clip indexed as "protective armor", or English to Chinese —
but it is structurally incapable of answering "we don't have that". So it must
not run as an equal-weight source:

1. **Keyword-first.** Results come from keyword search. Semantic is a booster
   that adds matches keyword missed, not a parallel authority.
2. **Capped.** Semantic may contribute at most a small number of extra videos, so
   a hopeless query returns a handful of weak suggestions rather than the archive.
3. **Floored** at cosine ≥ 0.50 (keeps 13/14 genuine matches).
4. **Labelled.** Semantic-only hits are marked "related" in the UI so an editor
   can tell a confident keyword match from a suggestion.

An empty result must remain possible. "No matching footage" is a useful, honest
answer; fifteen unrelated clips is not — and it is worse than useless because it
looks like an answer.

Untested option if this proves limiting: a larger embedding model
(`intfloat/multilingual-e5-large`) may separate proper nouns better. Not
evaluated — the 384-dim model was chosen for speed and it satisfies the
cross-lingual requirement.

## Cost structure

Per-call context overhead measured at ~28k tokens (≈6.9k cache creation +
≈21.5k cache read) on a trivial call — independent of payload. A contact sheet
is ≈1.8k tokens. At the shipped default of 4 sheets/call (~7.2k of images),
**overhead outweighs the actual work roughly 4:1**.

Raising `sampling.frames_per_call` amortizes that overhead over more images and
should cut total archive cost substantially for a config change alone. Verify
against `usage.jsonl` via `tools/cost_report.py` before the full archive run,
and re-check whether it changes the Haiku/Sonnet decision — if overhead
dominates, call count matters more than per-token model price.
