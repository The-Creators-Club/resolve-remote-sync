# Brief: merging one capability of the knowledge base

Readers have turned seven months of reports, bug-ledger entries, hunts, notes
and commits into about 4,300 short lessons. The same lesson was usually
written down three or four times, by different readers who could not see
each other's work. You are given every lesson filed under ONE capability (or
one piece of a large one) and you turn it into the finished text for that
capability: each rule once, terse, true today, and free of any trace of how
the old product was built.

The owner's words for what he wants:

- "every thing that was found and reported and fixed makes it into the
  rebuild document so that none of those bugs have to be re-discovered and
  re-fixed. It should be like a knowledge base."
- "the point of this knowledge base should ultimately be for it to be terse."
- "if there are any lessons which are no longer relevant, or repeated
  lessons, or superseded lessons, etc, they should all get removed from the
  final document."
- "NOTHING about how this product was actually built should make it into the
  rebuild document, only what it achieves."

First read the readers' brief,
`E:\Projects\Editing\ccsync\docs\rebuild-spec\knowledge-base\_parts\KB_BRIEF.md`,
for the kinds (1a, 1b, 2, 3), the purge rule ("The one rule that matters
most"), the terse limits and "The rule says what must hold, never how". All
of that binds you too. Then read your bundle completely.

## What you do with each entry in your bundle

Every entry id in your bundle must end up in exactly one place:

1. **Merged into a finished entry** (its id in that entry's `From:` line).
   Entries that teach the same rule become ONE finished entry. Take the
   sharpest wording and the best numbers from among them; do not write a
   longer entry to honour every source.
2. **Removed**, with one of these reasons:
   - `superseded by <finished id>`: a ruling the owner later changed, a fact
     a later finding corrected, a rule a later rule replaced. Dates are on
     each entry; the later one wins. The finished entry states only the
     current position, with no mention of the old.
   - `no longer applies: <why>`: the lesson is about something the owner has
     cut from the rebuild, or that one of his decisions about the rebuild
     makes impossible (the list is below).
   - `old build only`: on a second look it teaches nothing a different build
     would need: a slip in the old code that a reader let through.
   - `not a lesson`: steering, process, or a feature description with no
     rule in it.

"Repeated" is never a reason to remove: a repeat is MERGED, so its id goes in
a `From:` line.

Be bold about merging. "Could not check" being shown as "fine", "empty" or
"cleared" will appear dozens of times in different clothes: within your
capability that is one entry, or a few where the situations really differ
(say what was wrongly concluded and what must be shown instead). Two entries
are the same lesson when one test would catch both.

Be careful with what is unique. A fact about a given with its own numbers
(a camera, Resolve, a browser, the NAS, Windows, macOS) is never folded into
something vaguer. If in doubt whether two facts are the same fact, keep both.

## What the owner has cut or decided (2026-11-12)

Remove, as `no longer applies`, a lesson that is ONLY about one of these.
Where the entry also holds a fact about a given or a rule that still bites,
keep that part as its own entry and drop the rest.

- **Story Deck** (a game-like board for ordering the film with agents): cut
  whole. "The game thing is annoying."
- **The notes program (Obsidian)** and everything shaped by it: its canvas,
  block links, embeds, vault layout, plugins. Gone. The planning canvas is
  replaced by a board inside Timeline Cards: theme columns, transcript
  paragraphs as cards, dragged by hand; the assistant proposes the themes
  and makes a first sort; there is a place for notes on the board and the
  assistant can be called to update the board from them. A ruling about how
  planning should WORK (what goes where, what the assistant may and may not
  do, his editorial rules) still applies to the board and is kept, reworded
  without the canvas.
- **The translate button and the draft translations in the editor**: gone.
  Translation happens once, when footage is processed; a cut's English is
  picked from the transcript for exactly the words it plays. Rules about
  what English a cut must show are kept.
- **The old Timeline Cards page**: gone. Its features (cutting, the lane,
  search, shortening, the edit chat, the shelf, offline use, phone and
  controller use) all live on in the editor and are NOT cut.
- **Transcripts found by matching text**: gone. A transcript is now ONE
  file holding the text, the translation, every word's time and the links
  between English and original words, tied together directly, with a
  readable Markdown copy kept alongside. Lessons that exist only because
  separate files had to find each other by matching text no longer apply,
  except as lessons for bringing the studio's EXISTING transcripts in once
  (say so in the entry). Facts about speech-to-text, Mandarin text and
  timing accuracy are still facts and are kept.
- **Hand-run pipeline stages**: gone. Clips are dropped in and everything
  (grouping, sound sync, multicam, transcript, translation, word timing,
  first sort) runs on its own, with a manual override for every automatic
  decision. A lesson about remembering to run a stage no longer applies; a
  lesson about what a stage must get right still does.
- **Only Resolve at the start**, but nothing before the hand-over to the
  editing program may depend on it. Facts about Resolve are kept in full.
- **The dashboard's menu and settings layout are being redrawn from
  nothing.** A lesson about where the old dashboard put something is
  reworded as what a person must be able to find, see or do, or removed if
  it is only about the old arrangement. The square-bracket button style is
  gone: the whole product takes the Timeline Cards editor's look.
- **The cut list stays a Markdown file in its present format**, and exports
  (XML, OTIO, EDL, a text script) are kept.

## Fixing what the readers got wrong

- A kind 1a, 2 or 3 entry whose rule prescribes the old build's remedy
  ("read the project library instead", "keep a state file", "retry three
  times with a lock") is rewritten as what must hold for a person, or, if
  it is really a technique note, becomes kind 1b with the technique in its
  `Tool:` line.
- Any tool, file, setting, route, internal noun, bug number, version number
  or person's name that slipped into a text field comes out.
- A kind 3 entry that is really a fact about a given becomes 1a, and the
  other way round. A "ruling" the owner never made (a builder's choice
  written as his) is not kind 2.
- An entry filed under the wrong capability stays in your output (do not
  drop it); add `Move to: <capability>` under it.

## Your output file

Write ONE Markdown file at the path your prompt gives, in exactly this
shape (a script reads it):

```
# <the capability's name>

## <a sub-topic, in a few plain words>

### <cap>-001: <what a person saw, one plain sentence, 15 words at most>
- What was going on: <one sentence, 30 words at most>
- What the product must do: <one sentence, 30 words at most, testable>
- Kind: 3
- State: still open
- From: L01-032, P10-011, H02-005

## Sealed

### <cap>-S01: <title>
- What was going on: ...
- What the product must do: ...
- Kind: 1b
- Tool: <the tool or technique>
- From: G01-011, C01-025

## Removed

- D03-014 | no longer applies: Story Deck is cut
- P13-031 | superseded by <cap>-030
- L07-022 | old build only
```

- `<cap>` is the short prefix your prompt gives. Finished ids run
  `<cap>-001` onwards; sealed ones `<cap>-S01` onwards.
- Group finished entries under sub-topic headings (`## ...`) that a person
  looking for a lesson would recognise; facts about givens first within a
  sub-topic, then rulings, then situations to survive. Every kind 1b entry
  goes under `## Sealed`, grouped by tool.
- `State:` is written ONLY when it is `still open`, `outcome not found` or
  `fixed, never shipped` (these become questions for the owner). When the
  merged sources disagree, the latest dated one wins. Leave the line out
  otherwise.
- `From:` lists the ids of the bundle entries merged into it. Every bundle
  id appears in exactly one `From:` line or one `Removed` line.
- No dates, no source ids other than in `From:`, no "found by".

## Before you finish

Run `python E:\Projects\Editing\ccsync\docs\rebuild-spec\tools\check_merge.py <bundle name>`.
It lists every bundle id you have not placed, every id placed twice, entries
with missing fields, fields over the length limits and giveaway words. Fix
what it reports and run it again until it prints `OK`.

## Other rules

- Plain language. No em dashes. A term is defined the first time it is used.
- Touch nothing but your one output file. Do not commit. Do not start
  sub-agents. A temporary file's name must start with the prefix your prompt
  gives.
- Do not read the product's code, the bug ledger or the register: everything
  you need is in your bundle. If two entries contradict each other and the
  dates do not settle it, keep the later and add `Check: <the question>`
  under the finished entry, so it can be put to the owner.

## Your final reply

Short: the path; how many bundle entries went in and how many finished
entries, sealed entries and removals came out (with the removals counted by
reason); that the checker printed `OK`; any `Check:` or `Move to:` lines;
and the five lessons in this capability a rebuild would be most likely to
get wrong.
