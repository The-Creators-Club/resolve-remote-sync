# Decision list, page 29: Timeline Cards: the hand-over to Resolve, and exports

Stays behind: never shown to the session that rebuilds the product.

9 questions. Each has what exists today, the options, my recommendation and what you would notice. The specification is already written to the recommendation (or, where I recommend cutting something, still holds it, ready to delete). **Reply with the numbers you disagree with; anything you do not mention is taken as the recommendation.**

## Choices

### 29.1 Should handing a cut to Resolve always need Resolve open with the project on the sender's own computer (the timeline appears at once, nothing is closed), or should it also work with Resolve closed (written into the saved project and seen the next time the project is opened)?

- **Today:** there are two ways a cut reaches Resolve and a person gets different results from each. Through Resolve running on the editor's computer: missing clips are imported, a bin can be chosen, gap notes become titles where they fit, nothing is closed, but audio fades are dropped. Written into the saved project: fades arrive, gap notes are always markers, nothing can be imported, no bin can be chosen, the project is saved, closed and reopened on the editor's computer if it was open, and Resolve shows the result only when the project is opened. The second way is now refused for every real project library, because one such write left 63 half-linked clips that crash Resolve. The send in the new editor uses only the second way.
- **Options:** A: one hand-over, always into Resolve running on the sender's computer with the project open; missing clips imported, fades and gain carried, gap notes as titles (markers on short gaps), nothing closed; refused at the press with Resolve's state when Resolve is not there. B: also allow a hand-over with Resolve closed, written into the saved project, with the project closed and reopened when it is open somewhere, and the safety checks your lessons demand (links recorded both ways and checked, the editor's work saved first).
- **Recommended:** A, because your rulings already say only an unreachable Resolve blocks a send and that missing clips are imported first, and a write from outside Resolve is the one way a project has been damaged badly enough to crash Resolve.
- **What you would notice:** with A, an editor must have Resolve open with the project to send; the timeline appears at once and nothing is ever closed under them. With B, a cut can also be sent while Resolve is closed or the computer is off, seen on the next opening, and an open project is closed and reopened.
- (cards-to-resolve-and-exports-Q1)

### 29.2 Should Timeline Cards still let a person work directly on a timeline open in Resolve from the cards (moving, deleting, splitting, trimming, inserting and marking it live, or staging those edits and applying them), or is the cut list, sent as a new timeline and updated from Resolve's changes, the only way a cut is edited?

- **Today:** besides the cut list, there is a view that shows Resolve's open timeline as cards and edits it live by sending Resolve its own keys (Windows only, needing Resolve on the Edit page, not playing, with auto-select on for video track 1 and audio track 1 only), with a staged draft that can be applied, and a choice of saved timelines to view. The new editor refuses all of these while a cut list is open, and always has a cut list open, so these are reached only from the retired page. Your rulings about inserts at the playhead, single-undo moves and nothing cut ever lost were made for this view.
- **Options:** A: keep it, written as it is (the text holds it, marked pending), on Windows only, with a Mac told before trying. B: it goes; a cut is edited only as a cut list, handed over as a new timeline, and Resolve's later changes come back through the header chip and the Import tab as one undoable step. The Live tab (following Resolve's playhead and jumping Resolve to a cut) stays either way.
- **Recommended:** B, because your requirements make the editor the one place a cut is made and keep knowledge of the editing program to the hand-over, and this view is a second editor that depends on Resolve's keyboard and works on Windows only.
- **What you would notice:** with B, nobody edits a Resolve timeline from the cards; they edit the cut, send it, and bring Resolve's changes back. With A, the live editing stays for Windows editors.
- (cards-to-resolve-and-exports-Q2)

### 29.3 When a cut list names no start timecode, should its timeline start at 01:00:00:00 both in Resolve and in every export?

- **Today:** a timeline handed to Resolve starts at 01:00:00:00 when the cut list names none or it cannot be read, while the exports start at 00:00:00:00 with a note, so the same cut sits an hour apart in Resolve and in an exported file.
- **Options:** A: 01:00:00:00 everywhere (Resolve's own default). B: 00:00:00:00 everywhere. C: keep them different.
- **Recommended:** A, because 01:00:00:00 is what Resolve and most editing programs start a timeline at, and one start makes a sent timeline and an export line up.
- **What you would notice:** with A, an exported file of a cut list with no start begins at 01:00:00:00 instead of 00:00:00:00.
- (cards-to-resolve-and-exports-Q8)

### 29.4 The script export puts a long dash between each speaker and the timecode, but your rule is that nothing a person reads has a long dash. Should the script use a hyphen with spaces there?

- **Today:** each cut's header line in the Markdown script is the speaker in bold, a long dash, then the timecode.
- **Options:** A: a hyphen with spaces, as everywhere else. B: keep the long dash, because the script format is kept exactly.
- **Recommended:** A, because your no-long-dash rule covers everything a person reads, and the script is read.
- **What you would notice:** the script's header lines read "**Speaker** - 01:02:03:04".
- (cards-to-resolve-and-exports-Q9)

## Tidy-ups

One thing that can be done from several places, the same job existing twice, things switched off for everyone, things nobody can reach, and tools only the builders use.

| # | Question | Today | Recommended |
|---|---|---|---|
| 29.5 | If the live view stays, when the computer running Resolve goes away, should the cards show the timeline as it was last saved in the project (when that can be read) and otherwise as last seen, with one message? | two stand-ins exist, the timeline as last seen and the project as last saved, each with its own stale message, and which one shows depends on whether the server knows where the project library is and whether it has just restarted. | A, because the saved project is what Resolve really holds, and one rule is the fewest parts. (cards-to-resolve-and-exports-Q3) |
| 29.6 | Should Resolve on every editor's computer take part in Timeline Cards whenever Timeline Cards and the help for the editing program are on, with a switch per computer to keep one out? | a computer can let Timeline Cards see and drive its Resolve, through the app and the dashboard, but it is off on every computer and has never run live; the new editor does not yet reach an editor's Resolve this way at all. | A, because the one hand-over goes into Resolve on the sender's own computer, so without this there is no hand-over at all. (cards-to-resolve-and-exports-Q4) |
| 29.7 | Should sending, comparing and updating a cut list also be possible from a command line at the server, or only from the editor? | an admin at the server can send a cut list, compare it with its timeline, and rewrite it from the timeline from a command line, each a dry run unless told to write, beside the same three in the editor. | A, because one way to do each thing is the fewest parts, and the editor already shows each as a dry run first. (cards-to-resolve-and-exports-Q5) |
| 29.8 | The tools made for the people building the product (driving Resolve's own windows and menus from a command line, writing or rewriting a timeline straight into a Resolve project library, the library command lines, a switch that prints where each failed cut landed, and exporting a cut list file to all three formats from a command line) are left out of the specification for the new build to make its own. Agreed? | each exists as a command line or hidden switch used by whoever builds the product; the export from a command line can never link media. | A, because none is something an editor or admin does, and the export from outside the editor is already in the Export tab. (cards-to-resolve-and-exports-Q6) |
| 29.9 | Should the cut be downloadable as one audio file, as it plays in the editor? | an audio export is named but nothing makes one. (Bringing another program's timeline back as changes to the cut, named beside it, exists: it is the Import tab.) | A, because nobody has asked for it and Resolve renders the cut's sound already. (cards-to-resolve-and-exports-Q7) |

## Your answers

Not yet answered.
