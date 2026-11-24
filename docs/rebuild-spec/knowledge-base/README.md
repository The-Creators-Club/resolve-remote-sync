# The knowledge base: what real use taught

Step 2 of [`../../REBUILD_PLAN.md`](../../REBUILD_PLAN.md). The owner,
2026-11-12: "every thing that was found and reported and fixed makes it into
the rebuild document so that none of those bugs have to be re-discovered and
re-fixed. It should be like a knowledge base."

**State at 2026-11-13 00:30 UTC: written, and every count closes.** Each of
the register's 7,855 items is in a reader's entry, in a "Stays behind" list
or in a "No entry" list with a reason. The readers wrote 4,442 lessons. The
mergers made them 2,278 finished entries and 213 sealed notes and removed
53 (superseded, or about something the owner has cut). The pass across
capabilities folded 52 more repeats and moved 17 entries to the capability
they belong to. **What crosses: 2,230 lessons in 18 files** (445 facts about
givens, 583 rulings of the owner, 1,202 situations to survive). **Sealed:
209 notes in 57 tool files.**

**Since 2026-11-24: 2,175 lessons cross and 223 notes are sealed, in 59
files.** After the specification was written and the owner had answered
every decision page, 55 finished lessons were taken out of what crosses: 20
his answers overruled, 35 that only make sense for the present build's
arrangement (the promise a person needs is a behaviour of the
specification). 41 went to the trace and 14 to the sealed drawer. They are
listed, with the reason for each, in `_cross/TAKEN_OUT.txt`, which
`../tools/assemble_kb.py` applies; their full text and sources are kept in
`_trace/taken_out.tsv`. To take another lesson out, or put one back, edit
that file and run the script: never edit a merged file or a finished one.

| Where | What | Crosses? |
|---|---|---|
| `<capability>.md` in this folder (18 files) | The finished lessons: what a person saw, why, what the product must do, the kind | **Yes.** This is the knowledge base the rebuild reads. |
| `../sealed/` | Notes about tools and techniques the old build chose, one file per tool | Not until the rebuild's own design names the tool |
| `_owner/QUESTIONS.md` | 123 lessons still open, 150 with no outcome found, 108 fixed but never shipped, 8 questions, no conflicts (2026-11-24) | No. For the owner. |
| `_trace/` | Finished id to merged ids to readers' entries to register ids; what was removed and why; what was taken out afterwards | No |
| `_parts/`, `_merged/`, `_cross/`, this README | The working files and the briefs | No |

Still owed: the owner's answers to the questions; his test of twenty
remembered problems; razer's own history (see below); the top-up pass
before hand-over; and the fuller purge check of step 6 (the word scan built
from the code, and the blind reader). The purge net run so far is the
readers' and mergers' lint (`../tools/lint_parts.py`), not that check.

**Terse is the point.** The owner, 2026-11-12: "the point of this knowledge
base should ultimately be for it to be terse." A finished entry is three
short sentences at most (what a person saw, what was going on, what the
product must do), and one rule appears once however many times it was
reported. There is no limit on how many pages a capability's lessons run
to: the limit is on each entry, not on how many there are. The readers are held
to it by the brief; the mergers cut harder.

Nothing in this folder crosses to the rebuild as it stands. The parts in
`_parts/` cite bug numbers and commit ids and name the old build's tools in
their `Tool:` and "Stays behind" lines. The mergers (step 3 of the method)
turn them into the entries that cross, the sealed per-tool notes that are
released later, and the trace file that stays behind.

## How it is made

1. **The register.** `../tools/build_register.py` turns every place feedback
   was written down into numbered items and packs them into slices. It
   writes to `../_raw/`, which is gitignored and must never be committed: the
   owner's messages can hold passwords and people's names. Run it again to
   rebuild; it costs no usage.
2. **The readers.** One per slice, four at a time, each following
   [`_parts/KB_BRIEF.md`](_parts/KB_BRIEF.md) and writing `_parts/<slice>.md`.
3. **The mergers.** One pass per capability folds the copies of one problem
   into one entry, and removes from the finished document every repeat,
   every superseded lesson (only the current ruling or fact stays) and
   every lesson that no longer applies (about something the owner has cut
   from the rebuild, or made impossible by a decision of his). What is
   removed goes to the trace that stays behind, with the reason, so the
   count still closes. The list of what he has cut is in the plan, under
   "Timeline Cards in the rebuild" and the step 4 answers. Then one pass
   across capabilities and the split (see "Progress").
4. **The count.** `../tools/check_parts.py` with no arguments. Step 2 is not
   finished until it prints `OK`: every one of the register's ids is in an
   entry's sources, in a "Stays behind" list, or in a "No entry" list with a
   reason.

A reader's prompt is: "First read the brief at
`E:\Projects\Editing\ccsync\docs\rebuild-spec\knowledge-base\_parts\KB_BRIEF.md`
and follow it exactly. Do NOT start sub-agents of your own. Your slice is
`<S>`: read `E:\Projects\Editing\ccsync\docs\rebuild-spec\_raw\slices\<S>.md`
completely." Then one sentence on what the slice holds, the output path
`...\knowledge-base\_parts\<S>.md`, that entry ids are `<S>-001` onwards, and
that temporary files start `kb<S>-`.

## What the register holds, and how far each source was read

Built 2026-11-12. A top-up pass from these marks runs before the pack is
handed over.

| Slices | Source | Items | Read up to |
|---|---|---|---|
| P01 to P19 | Everything the owner typed to Claude Code on creator-1, in the product's folders or naming something of the product. 331 of them carry Claude's closing answer for that turn (session files survive only from October). | 3,871 | his last message of 2026-11-12 |
| L01 to L11 | The bug ledger, `KNOWN_BUGS.md`, one item per entry | 1,247 | ccsync `1457afc` |
| G01 | The two gotchas files | 46 | ccsync `1457afc`, Editing `94cbab7` |
| H01 to H08 | Ten hunt summaries, three review notes from the last hunt, two sweeps, the UI port review, the pre-launch review, the 2026-11-10 audit | 556 | ccsync `1457afc` |
| D01 to D07 | Plans and investigations in the other two repos' `docs` folders | 451 | Editing `94cbab7`, footage-sorter `663080d` |
| M01 to M06 | Memory notes from the product's folders, plus those from the home and `E:\Projects` folders that name something of the product | 383 | 2026-11-12 |
| C01 to C07 | Commit messages: ccsync (669), the Editing repo where they touch the Timeline Cards or montage pipelines (545), footage-sorter on every branch (87) | 1,301 | the heads above |

Left out, on purpose, and why:

- **5,182 of the owner's messages**: 3,931 typed outside the product's
  folders and naming nothing of it, 1,251 bare slash commands.
- **338 raw files inside the hunt folders** (each hunter's and verifier's own
  output, tallies, briefs, JSON). The hunt summaries above are their digest.
  The cross-check against bug numbers cited in the code is the net for
  anything a summary dropped.
- **61 notes and commits** the script itself set aside (a note with no
  product word in it; a commit touching another part of the Editing repo).
  Listed with reasons in `../_raw/auto_no_entry.tsv`.
- **Memory notes of other projects** (After Effects scripts, the website,
  and so on).

Not yet in the register, and owed:

- **Razer's own message history and notes.** Only creator-1's are read.
- **Anything editors told the owner outside Claude Code.** He has not said
  whether any of it should be read.
- **Session transcripts before October 2026** are gone (deleted at 30 days),
  so a report from before then is followed to its outcome through the
  ledger, the commits and the notes of the same days.

## Progress

**Readers: done.** `python docs/rebuild-spec/tools/check_parts.py` prints
`OK` for all 59 parts. A part cost about 2.2 % of a five-hour usage window.

**Mergers: done, all 20 bundles (2026-11-13).** A merger cost about 1.5 to
3 % of a five-hour window. `python docs/rebuild-spec/tools/build_merge_bundles.py`
gathers the parts' entries into one bundle per capability under
`../_raw/merge/`. **Do not run it again:** the merged files are keyed to
those bundles (a re-run after new parts means re-merging). Each merger follows [`_parts/KB_MERGE_BRIEF.md`](_parts/KB_MERGE_BRIEF.md)
and writes `_merged/<bundle>.md`. `python docs/rebuild-spec/tools/check_merge.py`
with no arguments shows which bundles are merged and passing.

A merger's prompt is: "First read the brief at
`E:\Projects\Editing\ccsync\docs\rebuild-spec\knowledge-base\_parts\KB_MERGE_BRIEF.md`
and follow it exactly. Do NOT start sub-agents of your own. Your bundle is
`<name>`: read `...\_raw\merge\<name>.md` completely." Then the output path
`...\knowledge-base\_merged\<name>.md`, the id prefix (below), and the
temporary-file prefix `kbm<name>-`.

| Bundle | Entries in | Prefix |
|---|---|---|
| accounts-privacy-legal | 122 | ACC |
| broll | 244 | BRO |
| cards-board | 95 | BRD |
| cards-editor-1, -2, -3 | 860 | CE1, CE2, CE3 (then one pass folds the three into CED) |
| cards-footage-in | 291 | CFI |
| cards-to-resolve-and-exports | 205 | CRX |
| dashboard | 273 | DSH |
| editor-app | 316 | APP |
| fleet-jobs | 66 | JOB |
| footage-sorter-and-camera-cards | 317 | SRT |
| music | 84 | MUS |
| proxies-and-file-moves | 177 | PRX |
| releases-and-updates | 173 | REL |
| resolve-on-the-editors-computer | 284 | RSV |
| server-install-and-running | 226 | SRV |
| sync | 312 | SYN |
| whole-product | 167 | ALL |
| youtube | 230 | YTD |

After the mergers, in this order (all run 2026-11-13: 174 groups ruled with 52
`same`, 118 `distinct` and 5 `conflict` lines; of 30 marked entries 17
moved, 9 stayed, 4 were already in the target, and one more conflict was
found among them). **Do not run
`build_cross_candidates.py` again**: it renumbers the groups the rulings
name. A lesson added later is placed by hand in a merged file and the split
is re-run.

1. **The pass across capabilities.** `python docs/rebuild-spec/tools/build_cross_candidates.py`
   lays side by side, under `_cross/`, the finished entries from different
   merged files that read alike (it decides nothing), plus one group per
   entry a merger marked `Move to:`. One reader per batch follows
   [`_parts/KB_CROSS_BRIEF.md`](_parts/KB_CROSS_BRIEF.md) and writes
   `_cross/<batch>.rulings`: `same` (one stays, the other becomes a pointer
   to it), `distinct`, `conflict` (a question for the owner) or, for a
   marked entry, `move` / `stay`. Nobody rewrites an entry in this pass, so
   nothing can be lost in it. `python docs/rebuild-spec/tools/check_cross.py`
   checks the rulings. A cross reader's prompt is the brief line, "Your
   batch is `<name>`: read `...\knowledge-base\_cross\<name>.md`
   completely", the output path `...\_cross\<name>.rulings` and the
   temporary-file prefix `kbx<name>-`.
2. **The three pieces of the Timeline Cards editor become one** in the same
   pass (they are different merged files, so repeats between them are found
   like any other), plus `_cross/topics.tsv`, which maps each piece's
   sub-topics onto one list (`bundle <tab> old heading <tab> new heading`).
3. **The split.** `python docs/rebuild-spec/tools/assemble_kb.py` applies the
   rulings and writes the text that crosses (`<capability>.md` in this
   folder), the sealed notes (`../sealed/<tool>.md`), the trace
   (`_trace/`, stays behind) and the owner's list (`_owner/QUESTIONS.md`,
   stays behind). It refuses to write while the merge count, the rulings or
   the purge net report a problem. An id is never renumbered.
4. The owner's test (twenty things he remembers going wrong, each must be
   findable).

What each kind of slice needs said in its reader's prompt, beyond the
standard paragraph above:

- **P** (the owner's messages): each session's messages are together; some
  carry Claude's closing answer under a dashed line; the rest are followed
  to their outcome through the day files.
- **L** (the ledger): written by the builders, so full of the old build's
  names and tools; get the lesson out and leave those behind.
- **H** (hunts): found by reading the code; most findings are slips of the
  old build (kind 4); write a repeated pattern once, citing every item.
- **D** (plans and investigations): the plan's own design stays behind;
  what matters is what the owner asked for, what was measured, what went
  wrong. Lessons only about things he has cut get one entry each.
- **M** (memory notes): many are about running the live system or how the
  work is done; the rulings and root causes are the point.
- **C** (commits): most are machinery or "shipped" notes; a run of commits
  about one problem is one entry.
