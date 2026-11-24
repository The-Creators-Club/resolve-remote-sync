# Joins aimed at cards-editor-2

## Checked

- J1 | F7, F9
- J2 | F7, F8
- J3 | F6
- J4 | F1
- J5 | fine
- J6 | fine
- J7 | F5
- J8 | F2, F3, F4
- J9 | fine
- J10 | F10
- J11 | F11
- J12 | fine
- J13 | F12

## Findings

### F1: A new gap that would land after the last cut is placed there here, but refused in part 1
- Kind: contradiction
- From: cards-editor-1 / Shift+Insert or Shift+G puts a one-second gap at the head
- Here: Inserting and resizing gaps
- From says: "A gap at the very end of the cut is refused."
- Here says: "By default it goes at the nearer boundary of the item under the head (before it when the head is in its first half, after it otherwise), else at the end."
- Settled by: CE1-038 (ruling): "a gap at the very end is refused"
- Fix: cards-editor-2 changes its gap placement so a new gap that would land after the last item (the head in the last item's second half, or past the end) is refused with a sentence, instead of going "at the end".

### F2: Part 4 says every edit is kept in the history; this piece thins older revisions to every tenth
- Kind: contradiction
- From: cards-editor-4 / Several people and devices edit one cut list live, and every edit is saved before it counts
- Here: Every revision of a cut list is kept, thinned rather than lost
- From says: "Every edit, its time and who made it are kept in the cut list's history"
- Here says: "The newest 200 revisions are all kept; older ones survive when their revision number is a multiple of 10"
- Settled by: CE3-023 (ruling): "older versions are kept, thinned rather than lost all at once"; and page 25.2, answered 2026-11-24 with option A: "every revision is kept, the newest 200 and then every tenth"
- Fix: cards-editor-4 says the history keeps the newest 200 revisions and then every tenth, pointing to cards-editor-2, instead of "every edit".

### F3: Part 4 has the history record who made each edit; this piece records no maker per revision
- Kind: missing
- From: cards-editor-4 / Several people and devices edit one cut list live, and every edit is saved before it counts
- Here: nowhere
- From says: "who is a person's device, a hand edit of the file, or the editor's own automatic work, decided by where the edit came from"
- Here says: nothing (the only stamp is the file's "written: <stamp>", "by Timeline Cards")
- Settled by: the owner must say: Can a person see, for each saved version of a cut list, when it was made and who made it (a person's device, a hand edit of the file, or the editor's own automatic work)?
- Fix: if yes, cards-editor-2 says each revision keeps its time and maker and where a person sees them; if no, cards-editor-4 drops "who made it".

### F4: An edit that finds the file changed is "reloaded, redo your edit" here, but worked out again and merged elsewhere
- Kind: contradiction
- From: cards-editor-4 / Several people and devices edit one cut list live, and every edit is saved before it counts
- Here: Edits are applied in order, each one a numbered revision, and nothing is ever overwritten
- From says: "a write that finds the cut list changed underneath it is refused and worked out again, never laid over the other"
- Here says: "Before every write, Timeline Cards checks the file on disk is still the one it loaded; if not, it reloads and refuses the edit." and "the project file changed on disk -- reloaded, redo your edit" (while this piece's own "The cut list file follows the editor..." says "that change is merged first, never overwritten")
- Settled by: page 25.5, answered 2026-11-24 with option A: "merge as edits"
- Fix: cards-editor-2 drops the reload-and-refuse rule and its sentence from "Edits are applied in order" and keeps only the merge of a changed file, so an editor's edit is never refused merely because the file changed on disk.

### F5: The transcript must never fetch a full-size file, but this piece plays the full reference recording while its light copy is not ready
- Kind: contradiction
- From: cards-editor-3 / Clicking a word puts the transcript playhead on it and clicking beside the words picks the paragraph
- Here: The editor finds each clip's sound by itself and lists the clips it cannot play
- From says: "never loads the same clip twice or fetches a full-size file to play it"
- Here says: "the light copy of the interview's reference sound recording; the reference recording itself while that copy is not ready"
- Settled by: CE1-008 (situation, weaker): "never reloads the same clip or fetches a full-size file"
- Fix: cards-editor-2 drops "the reference recording itself while that copy is not ready" from the order of sources, so a clip whose light copy is not ready is shown as being made (dimmed, asked again) rather than played from the full recording.

### F6: The board relies on "the key" that moves a cut to the shelf, and this piece names no such key
- Kind: missing
- From: cards-board / Setting cards aside and tagging the cold open
- Here: Staging without deleting, and putting shelf items back on the timeline
- From says: "The same key and the same gesture that move a cut to the shelf in the editor (see Timeline Cards: the editor: Notes and the staged shelf) set aside one card"
- Here says: "Ways in: the Stage buttons (on a card, in the inspector, in the edit view), dragging a card onto the shelf, and the shelf's Place."
- Settled by: the owner must say: On the board, which key sets a card aside: Delete pressed twice (as deleting a cut in the editor), Ctrl+X, or another?
- Fix: cards-board names the key and the gesture itself and points to cards-editor-1 (where Delete and Ctrl+X move a cut to the shelf), since cards-editor-2 names no staging key.

### F7: The board's "Uncategorised" arrives as a shelf category, but the editor's shelf already uses "Uncategorised" for the plain shelf
- Kind: differs
- From: cards-board / The board hands its order to the cut
- Here: The Stage buttons stage the selection onto the shelf, and the shelf turns to show it; A card of the cut is staged by dragging it onto the shelf
- From says: "| "Uncategorised" | A shelf category after the cut |"
- Here says: "the shelf turns to Uncategorised" and "All and Uncategorised both mean the plain shelf"
- Settled by: the owner must say: When the board's "Uncategorised" cards arrive in the cut, do they go on the plain shelf (the one the editor's shelf calls Uncategorised), or into a category of their own?
- Fix: cards-board says "the plain shelf (shown as Uncategorised)" if the former; if the latter, cards-editor-2 says how that category is told apart from the Uncategorised chip and overlay row.

### F8: The board's "Interviewer questions and chatter" group lands in a category the editor locks, so its chatter can never be placed
- Kind: contradiction
- From: cards-board / A full re-order makes a new version of the board
- Here: A shelf category for interviewer questions is locked, for reference only
- From says: "| Interviewer questions and chatter | One set-aside group, "Interviewer questions and chatter" |" (and, in "The first sort places every paragraph in one theme": "brings any card out of "Uncategorised" or a set-aside group into play")
- Here says: "A category whose name contains "interviewer question" (any letter case) is locked" and "Locked cards (in a locked category, or flagged as a question) show a lock chip "Question" instead of Place, cannot be dragged"
- Settled by: the owner must say: Should chatter cards that the board sets aside together with interviewer questions be placeable in the cut?
- Fix: if yes, either cards-board keeps chatter out of the questions group (or names that group without "interviewer question"), or cards-editor-2 locks only the cards flagged as questions, not every card in such a category.

### F9: The board's alternates arrive "ready to swap in", but this piece has no swap and keeps alternates only "as it is"
- Kind: missing
- From: cards-board / The board hands its order to the cut
- Here: A cut list holds the cut, the bench and the timeline's facts
- From says: "| The alternates column | An alternates section, its cards placed and ready to swap in |"
- Here says: "and the alternates section, kept as it is" (and the shelf panel has only "two tabs, Staged and Sequences"; "old alternates are never used as anchors")
- Settled by: the owner must say: When the board's alternate takes arrive in the cut, where does the editor show them, and can a person swap one in for the cut it is an alternative to in one step?
- Fix: cards-editor-2 says where the alternates section shows on the shelf and whether a swap exists; if there is no swap, cards-board says the alternates can be put back into the cut like any staged card instead of "ready to swap in".

### F10: Bringing Resolve's changes back replaces a cut whole when its speaker changed, but a hand edit fixes a speaker in place, and both pieces write the matching rules in full
- Kind: contradiction
- From: cards-to-resolve-and-exports / Accepted changes become ordinary edits on the cut list
- Here: The cut list file can be edited by hand, and the editor merges the change
- From says: "unless its clip, speaker or question mark changed, its colour is not a clip colour, or its new span is under 1/24 s or before 0: then the cut is replaced whole"
- Here says: "a clip name, speaker or link fixed by hand" (among what a hand edit changes) and "A cut whose new span cannot be reached by moving its edges is replaced whole." and "Changes brought back from the editing program into a cut list follow these same rules"
- Settled by: page 25.9, answered 2026-11-24 with the recommendation: "A, one way of turning a changed cut list into edits, and nothing removed in Resolve is lost from the cut list"
- Fix: cards-to-resolve-and-exports drops its own row-matching and replace-whole rules and points to cards-editor-2's hand-edit merge, which stays the one full description (naming shelf sections matched by kind and name there).

### F11: A cut missing from Resolve's timeline waits under "Not on the timeline" there, but this piece only says "a shelf"
- Kind: missing
- From: cards-to-resolve-and-exports / An import is matched to the cut list cut by cut
- Here: The cut list file can be edited by hand, and the editor merges the change
- From says: "A cut that is not on the timeline is moved to the shelf under the staged category "Not on the timeline", never deleted."
- Here says: "A cut bullet removed from the cut goes to a shelf, never lost" and "a cut removed there waits on a shelf"
- Settled by: page 25.9 (answered 2026-11-24: one way of turning a changed cut list into edits) makes the two the same rule; which shelf: the owner must say: When a cut is removed from the cut in Resolve or by a hand edit of the file, does it wait under "Not on the timeline", or under its section's category as a deleted cut does?
- Fix: cards-editor-2 names that shelf category in its merge rules, and cards-to-resolve-and-exports points to it.

### F12: Fleet jobs give up a piece that failed on the server too; this piece retries a failed waveform after 10 minutes and has no "given up" state
- Kind: contradiction
- From: fleet-jobs / Media for Timeline Cards is made by the studio's computers first, and by the server when none can
- Here: Each clip's waveform is made once, fine enough for 1/200 of a second, and reused; A clip whose sound is still being prepared is dimmed on the lane
- From says: "if it fails on the server too it is given up with the error" and "otherwise the piece is given up and shown as given up"
- Here says: "a failed one is tried again after 10 minutes" and "A clip's sound is in one of these states: ready, being made, failed (with the reason), or none (its media cannot be reached)."
- Settled by: the owner must say: When neither the studio's computers nor the server could make a clip's sound, picture or waveform, does the editor try again by itself later, and does the clip read "failed" or "given up"?
- Fix: both pieces adopt one retry rule and one name for the state, and fleet-jobs points to cards-editor-2 for what the clip shows.
