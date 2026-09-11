## Timeline Cards: an excerpt transcript follows its pointer, 2026-09-11

Not a hunt finding: the owner hit it converting `Reproductive Rights -
Ordered V7.canvas` to a cut list on the live page. 26 cards stayed
`(unmatched)` with "no matching clip (no sibling .srt, no fuzzy hit)", every
one of them linking `.../Interviewees/Brian Hioe/Brian Hioe_Transcript.md`.
His words: "brians whisper is in the civil defence vault". The work is in the
Timeline Cards repo (`E:\Projects\Editing\Resolve\MulticamPipeline`),
uncommitted by instruction.

### Why the cards were unmatched

Two independent causes on one canvas.

1. **The clip is an episode away.** `Reproductive Rights\Interviewees\Brian
   Hioe\` holds `Brian Hioe.md` and `Brian Hioe_Transcript.md` and nothing
   else: the interview was shot for Civil Defence, and the blocks were
   carried across by hand with their refs intact. `Brian Hioe.md` says so
   verbatim ("Excerpt of `Civil Defence/Interviewees/Brian/
   Brian_Transcript.md` ... The media is the Civil Defence Brian clip; time
   it from that project's sidecar when this conforms"), but nothing read it:
   `canvas_timeline.resolve_sources` looks for a sibling `.srt` in the
   transcript's own folder, then a fuzzy name against the clips it knows,
   and then gives up.
2. **The canvas spelled its links two ways.** `vault_root_for` picks ONE
   root for the whole canvas off the FIRST link that resolves. 483 cards
   were `2026/FF5/...` and 47 were `FF5/...`, and the 47 were unmatchable as
   a class, one folder below the root the canvas had been given. The owner
   repaired the canvas by hand before this was built; the converter must not
   be able to fail a class of cards over a spelling again.

### What it does now

**A Source with no clip looks for a pointer** (`excerpt_pointer`), in this
order: YAML frontmatter `source:` or `excerpt_of:` in the transcript, an
``Excerpt of `<path>` `` line in its first 20 lines, then the same line in
the interviewee note beside it (`<folder name>.md`, which is where Alex
wrote it). The path is vault-relative and may be spelled from the vault
root, the year, or the episode's parent, so it is resolved by CLIMBING from
the transcript's own folder exactly as `vault_root_for` climbs (`climb_base`
/ `climb_for`) -- Brian's `Civil Defence/...` resolves three levels up, at
`X:\Vault\2026\FF5`.

Each hop is then asked the same two questions the original folder was: the
sibling `.srt`, then the fuzzy name. The first that answers becomes the
source's `timing_abs`, and the clip, the `.srt` and the whisper sidecar all
come from there -- `WordsTokens.add_folder` indexes the source folder's
`*_words.json`, since the corpus was built over THIS episode and has never
seen it (a name already indexed wins, so a folder added for one source can
never re-time another). **The cut list keeps the card's own transcript
link**: the block refs are identical by contract, and that is what makes it
an excerpt. The person, and therefore the colour, stays the card's own.

**Two hops at most**, and a path already visited ends the chain: a pointer
at an excerpt that points back is a loop, and a loop followed is a hang.

**A pointer that resolves nowhere is a refusal**, not a guess: the card
keeps the old "no matching clip (no sibling .srt, no fuzzy hit)" reason with
"; pointer to X could not be resolved" appended. That extension is written
ONLY when the climb found nothing -- a pointer that resolved and merely led
to another empty folder is not a bad pointer, and neither is the second hop
of a loop.

**Where the timing came from is in the report.** `source.via` is the
pointer's own folder, and both dry-run tables print it:

    source : Brian Hioe_Transcript -> Brian Multicam [whisper, via Civil Defence/Interviewees/Brian]

**A link resolves per link** (`PathResolver`, `sources_for(entries, vault,
root)`): the canvas root `vault_root_for` chose is still the first thing
tried, and a link that misses climbs from the EPISODE root towards the
drive. The answer is cached per first path segment (a spelling is shared by
every link that starts the same way) and the cached candidate is still
`isfile`-checked, so a wrong hit cannot survive the cache. A link that
resolves nowhere comes back as the canvas root's own guess, so the report
reads exactly as it did before.

### Proof on the real canvas

`py -3 -m multicam_pipeline.canvas.canvas_to_cutlist --canvas "...
Reproductive Rights - Ordered V7.canvas" --root "X:\Vault\2026\FF5\
Reproductive Rights" --timing word` (dry run, wrote nothing):

    source : Brian Hioe_Transcript -> Brian Multicam [whisper, via Civil Defence/Interviewees/Brian]
    timing : word  (word timing: whisper)
    515 matched (0 low-confidence), 0 unmatched, 33 note(s), 0 alternate(s)

Brian's 26 cards are cut from the Civil Defence sidecar's words, spans
spread across the interview (3067.8-3098.4, 3645.2-3670.8, ...), not
clustered at zero.

### Files

- `multicam_pipeline/canvas/canvas_timeline.py`: `EXCERPT_RE`,
  `FRONTMATTER_RE`, `_head`, `_clean_pointer`, `excerpt_pointer`,
  `climb_base` / `climb_for`, `PathResolver`, `excerpt_hops`,
  `follow_excerpt`; `Source.timing_abs` / `via` / `pointer` / `folder()`
  (and `srt_stream` reads the timing folder); `sources_for(..., root)`;
  the one new branch in `resolve_sources` and the extended refusal; the
  CLI's `source :` line.
- `multicam_pipeline/canvas/canvas_to_cutlist.py`: `WordsTokens.add_folder`,
  `via` on each `report["sources"]` entry, `print_report`'s source line.
- `tests/test_canvas_to_cutlist.py`: sections (l) and (m), 13 checks.
- `docs/PROJECT-FORMAT-PLAN.md` (a dated section at the end),
  `docs/LAYOUT.md` (the `canvas_timeline.py` row).

### Tests

`py -3 tests/test_canvas_to_cutlist.py` all passed (13 new checks, and the
golden `--from-srt` dry-run table is byte-identical -- the Ghost transcript
that has no folder at all still reads "no matching clip (no sibling .srt, no
fuzzy hit)"). Also green: `test_cutlist.py`, `test_load_scaling.py`,
`test_project_picker.py`, `test_conform_no_timeline.py`, `test_corpus.py`,
`test_project_engine.py`, `test_page_golden.py`.

### Left out, deliberately

- The excerpt hops are tried only where the folder yields NO clip. A folder
  that has a wrong clip in it still wins; a pointer is a fallback, never an
  override.
- `cards/project_pick.py`'s NEW FROM CANVAS confirm lists `<clip>: whisper`
  per source and does not yet say `via`. The report carries it, so that is a
  one-line follow-up in the picker's own string.
- Nothing was committed, and no `.cut.md` was written: every run of the real
  canvas was a dry run.
