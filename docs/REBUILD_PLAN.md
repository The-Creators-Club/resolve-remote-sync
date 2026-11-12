# The clean rebuild: what we are doing, where it stands, how to resume

Written 2026-11-12. This is the hand-over note for the work started that
day. Paste the "To resume" text at the bottom into a new Claude Code session
in `E:\Projects\Editing\ccsync` to carry on.

## What the owner wants

In his words, 2026-11-12:

- "I believe ccsync may be extremely bloated."
- "The point of this is for a completely fresh instance of claude to look at
  the feature list and start a complete rebuild of the whole project, without
  having any bias as to how the original architecture was built. I imagine
  there is a lot of frankenstein patches on patches as I was designing as I
  built, so I want a completely clean rebuild of the whole thing."
- "Would it be possible to build it in rust?"
- "This rebuild should include footage sorter, too."

So the product of this work is **a briefing pack a fresh Claude can rebuild
from**, covering CC Sync, the Timeline Cards editor and the Footage Sorter.
The rebuild itself is a later job, done by a different session that must not
read the current code.

## The plan (approved 2026-11-12)

| Step | What | State |
|---|---|---|
| 1 | **Finish the inventory**: a list of everything the software does, read from the code alone, in `docs/feature-inventory/`. | 29 of 34 sections written. Five owed, plus the Footage Sorter (not started). |
| 2 | **Rewrite it as one specification organised by what people do** (sync a project, make proxies, find b-roll, cut in Timeline Cards, and so on). No source-file tags, no route or config-key names, each capability described once. | Not started. |
| 3 | **A decision list for the owner**: every overlap, every several-ways-in, every dormant or dead feature, each as a keep / cut / merge question with a recommendation. | Not started. |
| 4 | **Two short companions**: (a) the outside-world constraints a rebuild must respect; (b) what data and formats must carry over from the live system. | Not started. |

The fresh instance is then given the trimmed specification and the two
companions. The raw inventory stays behind as the reference for "what exactly
did the old one do here"; it is NOT part of the brief, because its shape
follows the old code.

## Why the inventory alone is not the brief

- It lists what exists, not what is wanted: every duplicate, dormant feature
  and workaround is in it.
- Its sections are cut along the old code's seams, each heading carries a
  source tag, and it lists routes, config keys and per-computer command
  channels. A fresh instance would copy those shapes.
- Anything that spans the editor's machine and the server is described two or
  three times, once from each side.
- Hard-won facts about the outside world are mixed in with features instead
  of standing as a list of constraints.
- Nothing in it says what data must survive the rebuild.

## Decisions and steers so far

- **Ask every overlap question.** Shown examples of overlaps, the owner said
  "most of these I would want to keep", and then: "Six places to tick a
  project is an example of something that could be removed. The questions
  should still be asked." So step 3 puts EVERY overlap to him, including the
  several-ways-in ones. Nothing is kept or dropped by default.
- **Keeping a feature is not keeping every copy of it.** Where one capability
  has several ways in, or is written two or three times, the specification
  describes it once with all its ways in, and flags where the current copies
  behave differently so he can pick which behaviour wins.
- **Language.** Rust is the working choice for the editor-machine app (the
  biggest gain: one native program, no bundled Python, no window-toolkit
  thread crashes) and for the server. The browser pages stay JavaScript or
  TypeScript. The Resolve link stays a small Python or Lua helper, because
  Resolve's scripting only speaks those. The indexers CAN be Rust if every
  model runs through a portable engine (ONNX Runtime, a llama.cpp-style
  runtime, whisper.cpp, ffmpeg); proposed as a rule for the specification.
  Stanza (Timeline Cards' reading aids, Python only, about 1.7 GB) is an open
  question for the decision list.
- **Size.** Measured 2026-11-12: ccsync's Python is 309,710 lines outside the
  tests, of which 173,105 (56 %) hold code; the tests are another 325,786
  lines. The editor is about 95,000 lines and the Footage Sorter about 45,000.
  A rebuild loses the comment-and-history lines and the duplicated
  implementations; Rust gives some of that back. Expect smaller, not
  dramatically smaller, unless features are cut in step 3.

## Step 1 in detail: what is owed

The index and the status table are in
[`feature-inventory/README.md`](feature-inventory/README.md). The rules every
reader follows are in
[`feature-inventory/_parts/INVENTORY_BRIEF.md`](feature-inventory/_parts/INVENTORY_BRIEF.md):
the code is the only source of truth, read every line, describe behaviour and
not architecture, end with three lists (looks redundant, claims the code does
not back, could not determine).

Each reader's prompt is: "First read the brief at
`E:\Projects\Editing\ccsync\docs\feature-inventory\_parts\INVENTORY_BRIEF.md`
and follow it exactly. Do NOT start sub-agents of your own." Then one
paragraph saying what the software is, the files that are its part, the
output path and the section title.

### Owed in CC Sync

| | Files | Write to |
|---|---|---|
| 24 | every non-test file in `ccsync\broll\indexer\` and `ccsync\broll\eval\`, and anything directly under `ccsync\broll\` that is not `web` | `24-broll-indexer-and-search-eval.md` |

### Owed in the Timeline Cards editor (`E:\Projects\Editing\Resolve\MulticamPipeline\editor`)

Skip folders named `test` and `shots`, and files ending `.test.ts`.

| | Files | Write to |
|---|---|---|
| 31 | `features\search`, `features\shorten`, `features\chat`, `features\translate` | `31-timeline-cards-search-shorten-chat-translate.md` |
| 32 | `features\resolve`, `features\projects`, `features\video`, `features\montage`, `features\markers` | `32-timeline-cards-resolve-projects-video-montage-markers.md` |
| 33 | `features\shelf`, `features\gapnotes`, `features\keep`, `features\looks`, `features\lane`, `audio`, `adapters`, and `..\apps` (the Windows and Android apps) | `33-timeline-cards-shelf-notes-looks-audio-apps.md` |
| 34 | `server`, `core`, `cutmd` (the editor's own server, every route; the cut-list model; the `.cut.md` file format exactly as a person or another tool meets it) | `34-timeline-cards-server-and-cut-list-format.md` |

### The Footage Sorter (`E:\Projects\Editing\footage-sorter`, not started)

Check out nothing: read the working tree as it is (branch
`sorter-dashboard-module` on 2026-11-12; four files had uncommitted changes).
Skip `node_modules`, `cache`, `data`, `test` and `tests`.

| | Files | About | Write to |
|---|---|---|---|
| 35 | `footage_sorter\` (first half of the modules, by size) | 19,656 lines in all | `35-footage-sorter-engine-part-1.md` |
| 36 | `footage_sorter\` (second half) | | `36-footage-sorter-engine-part-2.md` |
| 37 | `public\` (the pages: every screen and control) | 13,376 lines | `37-footage-sorter-pages.md` |
| 38 | `server.js`, `lib\`, `ingest\`, `nas\`, `cloud\`, `tools\`, `mover.ps1` | about 18,000 lines | `38-footage-sorter-server-ingest-cloud-tools.md` |

For 35 and 36, list the modules with `wc -l` first and split them into two
halves of about 10,000 lines each, by subject where possible.

When a section is written, change its row in `feature-inventory/README.md`
from OWED to a link, and add the Footage Sorter rows there.

## Running it without burning the usage allowance

What happened on 2026-11-12: twenty readers launched at once took the account
from low usage to the hard five-hour limit in about 25 minutes.

- **Arm the watcher first.** "The watcher" is
  `E:\Projects\Utilities\claude-usage\usage.mjs`. Run
  `node usage.mjs wait-high --at 70 --poll 240` as a background command before
  starting any reader. When it prints PAUSE, stop every reader and report.
  `node usage.mjs status` reads the figures at any time.
- **Four readers at a time**, a new one only as one finishes.
- **Readers must not start sub-agents.** Stopping a parent does not stop its
  children.
- **A stopped reader keeps what it read.** Send it a message to carry on; do
  not start it again from nothing.
- **Cost to expect:** one section is roughly 4 to 6 % of a five-hour window.
  The nine owed sections are about half a window. Step 2 is about the same
  again.

## Steps 2 to 4: how to do them

**Step 2, the specification.** One document set under `docs/rebuild-spec/`,
organised by capability, not by program. A first cut of the capabilities:
signing in and people; computers and what each one syncs; uploading
originals; downloading proxies and originals; the shared-folder lane; safety
stops; proxies; Resolve (relinking, fixing, undo, LUTs and stills); moving
files; camera cards and field backup; the footage ledger and the sorter;
b-roll (search, ingest, indexing, client folders); music; YouTube downloads;
Timeline Cards (cut lists, lane, cards, transcripts, search, shorten, chat,
translation, sending to Resolve, offline); fleet jobs; updates and releases;
alerts and self-diagnosis; recovery and snapshots; installing a site;
installing an editor's machine; personal data. For each capability: what a
person can do, what happens on its own, every limit, number and message that
matters to a person, and every refusal. Write it from the inventory; settle
each "could not determine" by reading the other section that answers it, or
the code.

**Step 3, the decision list.** `docs/rebuild-spec/DECISIONS.md`. One numbered
question per overlap, in plain words, each with: what exists today, the
options, a recommendation, and what the choice changes for a person. Gather
them from every section's "Looks redundant or overlapping" list and from the
duplicates found while writing step 2. Group them so he can answer a page at
a time. Kinds of question: several ways in to one thing (keep which?), the
same job built twice (which behaviour wins?), dormant or dead features (can
they go?), and either-or tools (built-in card copier or TeraCopy, and so on).

**Step 4, the two companions.**
- `CONSTRAINTS.md`: facts about the outside world, stated without reference
  to the old code. For example: Resolve's scripting server and the launch
  window in which a client must not connect; macOS file names being a
  different Unicode form from Windows and the NAS; what Syncthing, rclone,
  TrueNAS and Synology DSM do and refuse; what YouTube blocks. Take them from
  the inventory's behaviour and from `docs/GOTCHAS.md`, but check each one
  against the code before writing it down.
- `CARRY_OVER.md`: everything the live system holds that a rebuild must read
  or migrate: the dashboard's records, the `.cut.md` cut lists, the b-roll
  and music indexes, client share links, each editor's settings and sync
  identities, the Resolve undo journals, the signed release channel and its
  keys. And how the live fleet moves from the old build to the new one.

## Things found along the way

- **Shipped the same day, both live:** dashboard 0.7.80 (the old Timeline
  Cards page retired, the picker's Open opens the editor;
  `docs/CARDS_OLD_PAGE_RETIREMENT.md`) and Timeline Cards at Editing commit
  `94cbab7` (the controller moves the transcript's playhead, LT plus the
  right stick selects, LT + X inserts after the selected card).
- **Deploy trap:** the installer's default Footage Sorter ref is `master`,
  which was OLDER than the live sorter. Read the live
  `sorter-web/DEPLOYED_COMMIT` and pass `--sorter-commit <live>`.
- **The Editing repo's `main` is 160 commits ahead of GitHub** and was not
  pushed.
- **A controller behaviour that cannot work** (inventory section 28): in the
  transcript, LT + D-pad left/right is meant to step through search results,
  but the controller switches to the results map whenever results are open.

## To resume

Paste this into a new Claude Code session opened in
`E:\Projects\Editing\ccsync`:

> Read `docs/REBUILD_PLAN.md` and `docs/feature-inventory/README.md`, then
> carry on with the plan from step 1. Arm the usage watcher at 70 % first
> (`E:\Projects\Utilities\claude-usage\usage.mjs`), run at most four readers
> at a time, tell every reader not to start sub-agents, and stop and report
> when the watcher says PAUSE. Do the nine owed inventory sections first
> (24, 31 to 34, and the Footage Sorter 35 to 38), then step 2. Bring me the
> step 3 questions a page at a time. Commit each finished section.
