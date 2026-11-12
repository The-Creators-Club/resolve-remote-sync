# Brief: one part of the knowledge base

You are writing ONE part of a knowledge base. The owner of this software is
having it rebuilt from scratch by a fresh team that will never see the
current code. He wants everything real use has taught, over seven months, to
reach that team, "so that none of those bugs have to be re-discovered and
re-fixed". Your prompt names one **slice** of a register: a file of numbered
items (his own messages, entries from the bug ledger, findings from code
hunts, notes, commit messages). You turn your slice into lessons.

The product, in one paragraph: a video studio keeps its projects on a NAS.
An app on each editor's computer syncs chosen projects (camera originals up,
small proxy copies down), keeps the editing program DaVinci Resolve pointed
at the right files, and reports to a web dashboard where people, computers,
projects and transfers are managed. Around that sit a b-roll search, a music
search, a YouTube downloader, a camera-card and footage sorter, and Timeline
Cards: a browser editor for cutting interviews from their transcripts
(often Mandarin with English), fed by a pipeline that transcribes,
translates and times every word, and that sends the finished cut to Resolve.

## The one rule that matters most

**Nothing about HOW the old product was built may be written into a lesson.**
The fresh team must not learn which tools it used, how many of anything it
had, or what its parts were called, or it will build the same thing again.
A lesson says what a person saw and what must hold for them. It never says
what was built to make it hold.

In the three text fields of an entry (the title, "What was going on", "What
the product must do") you must NOT write:

- any file, folder, function, class, route, setting, table, flag or
  environment-variable name;
- any tool, library, language or service the old build CHOSE to use (for
  example its sync, transfer, download, speech-to-text, database, packaging,
  container, tunnelling, mail or AI tools). Say "the sync", "the downloader",
  "the speech-to-text", "the assistant";
- the old build's own names for its insides (its names for its transfer
  routes, queues, roles, stores, switches, stages), or how many of anything
  it had;
- any bug number, commit id or version number;
- any password, token, key, address, e-mail, or person's name. Write "the
  owner", "an editor", "a client".

You MAY name **givens**: things the studio has whatever the build. These are
DaVinci Resolve, Windows, macOS, Android and iOS and their browsers, the
cameras, their cards and sound recorders, the kinds of NAS a studio owns,
YouTube, and the plain facts of a studio's network (slow uplinks, laptops
that sleep, drives that get unplugged). A fact about a given is the most
valuable thing you can write down.

## Terse

The owner's word for this knowledge base is **terse**. It will hold thousands
of lessons and is only useful if each one can be read in seconds.

- The title: one plain sentence, 15 words at most.
- "What was going on": ONE sentence, 30 words at most. The fact, not the
  story of how it was found.
- "What the product must do": ONE sentence, 30 words at most, that could be
  turned into a test.
- Keep the numbers that matter (a time, a size, a count a person would
  meet). Drop everything else: no history, no "it turned out", no hedging,
  no second example.
- Fewer, sharper entries beat many overlapping ones. If two items teach the
  same rule, that is one entry.

## What to do with each item

Read your slice file completely, start to end, in chunks. Every item is
wrapped as `<<<ITEM id | date | where>>> ... <<<END id>>>`. Every id must end
up in exactly one of three places in your output:

1. **In the Sources of an entry** (a lesson worth carrying across).
2. **In the "Stays behind" list**: it is real, but it is about the old
   build's own machinery (kind 4) or about running the live system (kind 5).
3. **In the "No entry" list**, with a reason.

Several items about the same problem become ONE entry citing all of them.
One item that teaches two different things becomes two entries.

### The kinds

| Kind | What it is | Where it goes |
|---|---|---|
| 1a | A fact about a GIVEN. "Resolve's scripting dies for the whole session if anything connects while it is still starting." "A Mac spells accented and Chinese file names differently from Windows and the NAS." | An entry. |
| 1b | A fact about a tool the old build CHOSE: how it behaves, where it fails. | An entry, with the tool named ONLY in the `Tool:` line. Write the text fields so they still make sense with the tool unnamed ("the sync tool"). These are sealed and released later, per tool. |
| 2 | The owner's ruling: how he wants something to behave, look or read. "A computer with nothing ticked is never an error." "No long dashes in anything a person reads." | An entry, quoting his words where you have them. |
| 3 | A situation the product must survive, whatever it is built from. "The sync drive is pulled out mid-upload." "A file moved by hand on the NAS comes back." "A proxy a few frames short that Resolve refuses." | An entry. |
| 4 | A mistake only the old build could make: a slip in its own code or wiring, with nothing a different build would need to know. | Stays behind, one line. BUT if it hides something a person needs ("a safety stop is still in force after a restart"), ALSO write that need as a kind 3 entry with no trace of the mechanism. |
| 5 | Running the live system: how to reach a machine, a deploy trap, where a secret lives, what was shipped when. | Stays behind, one line. |

**The rule says what must hold, never how.** "Other programs' clicks in
Resolve are never held up for more than half a second" is a rule. "Read the
project library instead of asking Resolve" is the old build's remedy, and it
does not belong in a kind 1a, 2 or 3 entry. Where the lesson IS a technique
for dealing with a given (for example what is found where when Resolve's own
project library is read directly, or how a particular file format is
decoded), write it as kind 1b and put the technique in the `Tool:` line
(`Tool: reading Resolve's project library directly`). It is released only if
the fresh team chooses that technique. The plain fact about the given that
made the technique necessary (how slow, how wrong, with the numbers) is its
own kind 1a entry.

When you are unsure between 3 and 4, ask: would a completely different build,
made by people who never saw this one, be able to hit this? If yes, it is 3
(or 1a). Most items that look like 4 hide a 3. Look for it.

### One of the owner's messages (ids starting `P-`)

First decide what it is:

- **A report of real behaviour** ("Ruskin isn't syncing", "the tray keeps
  closing itself"). Follow it to its outcome: what it turned out to be and
  what was done. Use, in this order: the text under "what Claude answered at
  the end of that turn" when the item has it; the neighbouring messages of
  the same session; the day files (below) for that day and the next two; a
  search of the ledger and the commit slices. Then write the entry. If you
  cannot find the outcome, still write the entry, with `State: outcome not
  found`.
- **A ruling** on how he wants something to work, look or read: a kind 2
  entry with his words quoted.
- **A request for a feature.** If it says how the thing must behave or look
  in a way a rebuild could get wrong, it is a kind 2 entry. If it was asked
  and never built, it is a kind 2 entry with `State: still open`. A plain
  "add X" that was built and says nothing more: No entry, reason `feature
  request, built`.
- **None of these** (steering the session, a question about the work,
  thanks, a path pasted in): No entry.

His messages are the purest record there is. Do not skim them. A short,
irritated message is usually a report of real behaviour.

### Finding an outcome

`E:\Projects\Editing\ccsync\docs\rebuild-spec\_raw\by-day\<date>.md` lists,
for one day, every ledger entry, commit, note and hunt section dated that
day, with its id and where it is. `...\_raw\register.tsv` lists every item
(id, slice, date, where, title) and can be searched with Grep. The slices are
in `...\_raw\slices\`. You may read parts of other slices to follow an
outcome. Do not read the product's code: it is not your source, and time
spent there is wasted.

## The output file

Write ONE Markdown file at the path your prompt gives, in exactly this
shape. A script reads it, so keep the field names and the punctuation.

```
# Knowledge base part <slice>

## Entries

### <slice>-001: <what a person saw, in one plain sentence>
- What was going on: <the situation and the real cause, as a fact about the world where it is one>
- What the product must do: <one rule the rebuild can be tested against>
- Kind: 3
- Tool: <only for kind 1b: the tool's name>
- Capability: <one from the list below>
- Found by: real use
- Date: 2026-08-28
- State: fixed and live
- Sources: P-02512, L-0197, C-cc-904ee1135

## Stays behind

- L-0201, L-0202 | kind 4 | <one line saying what it was; this line stays behind, so it may be technical>
- C-cc-837591cf7 | kind 5 | <one line>

## No entry

- P-02502 | steering the session
- P-02520..P-02531 | not about the product
```

- `Found by` is one of: `real use`, `reading the code`, `a test`.
- `State` is one of: `fixed and live`, `fixed, never shipped`, `still open`,
  `declined by the owner`, `outcome not found`, `a standing rule` (for
  rulings and facts that have no fix).
- `Capability` is one of: `sync`, `proxies-and-file-moves`,
  `resolve-on-the-editors-computer`, `editor-app` (the app on an editor's
  computer: its tray, windows, install, update, crashes), `dashboard`,
  `server-install-and-running`, `releases-and-updates`, `broll`, `music`,
  `youtube`, `cards-editor` (cutting, playback, the transcript panel, phone
  and controller use, working offline), `cards-to-resolve-and-exports`,
  `cards-footage-in` (transcribing, translating, word timing, multicams),
  `cards-board` (planning the film before cutting), `footage-sorter-and-camera-cards`,
  `fleet-jobs`, `accounts-privacy-legal`, `whole-product` (the look, the
  wording, rules that apply everywhere).
- No entry reasons, use these words: `not about the product`, `steering the
  session`, `about how the work is done, not the product`, `feature request,
  built`, `duplicate of <id>`, `a heading or index with no content of its
  own`.
- In the two lists a run of neighbouring ids of the same kind may be written
  `P-00012..P-00020` (numeric `P-` and `L-` ids only).
- Write the file in several appends, so nothing is lost. Entries first.

## Before you finish

Run `python E:\Projects\Editing\ccsync\docs\rebuild-spec\tools\check_parts.py <slice>`.
It lists every id of your slice that your file does not account for, every
id accounted for twice in the lists, and every entry with a missing or
misspelt field. Fix what it reports and run it again until it prints `OK`.

## Other rules

- Plain language. Define a term the first time you use it. No em dashes.
- Touch nothing but your one output file. Do not modify, create or delete
  any other file in any repo. Do not commit. Do not run the product, its
  tests or its builds. Do not start sub-agents.
- If you write a temporary file, its name must start with the prefix your
  prompt gives, and you must not touch a temporary file without that prefix.

## Your final reply

Keep it short: the path you wrote; how many entries of each kind, how many
lines stay behind, how many ids got no entry; that the checker printed `OK`;
how many entries are `outcome not found`; and the five lessons in your part
that a rebuild would be most likely to get wrong, one line each.
