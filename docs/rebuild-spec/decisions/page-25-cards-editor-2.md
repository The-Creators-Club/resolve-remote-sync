# Decision list, page 25: Timeline Cards: the editor, part 2

Stays behind: never shown to the session that rebuilds the product.

14 questions. Each has what exists today, the options, my recommendation and what you would notice. The specification is already written to the recommendation (or, where I recommend cutting something, still holds it, ready to delete). **Reply with the numbers you disagree with; anything you do not mention is taken as the recommendation.**

## Choices

### 25.1 The cut list file still carries three marks of the notes program you cut. Do they stay exactly as they are, and does editing the file by hand outside Timeline Cards stay supported?

- **Today:** you ruled that the `.cut.md` file stays as it is, and the text gives its format exactly. That format carries, under every cut, a link line to a transcript paragraph written in the notes program's form (`[[<speaker or clip>_Transcript#^<ref>]]`); two header keys that name the notes vault's root and the planning canvas (`vault_root`, `canvas`); a comment at the top written for someone editing the file by hand; and the file lives in the episode's `Script Docs/Cuts` folder. The editor also notices a hand edit of the file within 2 seconds and merges it in as edits.
- **Options:** A: keep every mark and the folder exactly, and keep hand editing supported (every existing cut list opens unchanged, and a person can still fix a cut list in a text editor). B: keep reading every mark so old files open unchanged, but stop writing the link line and the two keys in new files, and drop support for hand edits made while the editor has the file open.
- **Recommended:** A, because it is what you ruled ("the file stays as it is"), it costs nothing a person meets, and the link still points at the right paragraph of the one-file transcript.
- **What you would notice:** with A nothing changes; with B new files look slightly different in a text editor, and a hand edit made while the editor is open is overwritten instead of merged.
- (cards-editor-2-Q1)

### 25.2 When two people edit the same cut list, should Undo take back only your own last edit, or step the file back to its previous version whoever made it?

- **Today:** the editor's Undo takes back only this person's own edits, per device, and refuses ("cannot undo the trim: cut 4 was changed since by another edit") when someone else has since changed the same thing; its history survives a reload. Another description has Undo put back the newest saved revision of the file whoever made it, with "nothing to undo -- this is the first revision of the file", "back to rev N" and redo lasting only the session. Your ruling says undo steps back through saved versions, which are kept and thinned.
- **Options:** A: Undo takes back your own edits only (each undo restores the version from before that edit, so it is still a saved version, and works after a restart); every revision is kept, the newest 200 and then every tenth, so a cut list can always be put back. B: Undo steps the whole file back one saved revision, including another person's edit.
- **Recommended:** A, because with two people on one episode B would silently take back someone else's work, while for one person working alone the two are the same.
- **What you would notice:** with A a shared cut list never loses a colleague's edit to your Undo; with B the Undo button can undo things you did not do.
- (cards-editor-2-Q2)

### 25.3 Is a gap a row of its own that stays where it was put, or the black before the cut that follows it?

- **Today:** the editor treats a gap as its own card: it stays where it was put when the clips beside it move, can be selected, moved, sized and deleted, and several gap lines in a row stay separate. Another description treats a gap as "the black before a cut": it belongs to the cut after it, several gap lines before a cut are added into one, and deleting a cut moves its black onto the next cut.
- **Options:** A: a gap is its own row (what the editor shows). B: a gap is the black before the following cut.
- **Recommended:** A, because it is what an editor sees and drags on screen, and every existing file reads the same either way.
- **What you would notice:** with A deleting a cut leaves the gap where it was; with B the gap jumps onto the next cut and two gaps in a row merge into one.
- (cards-editor-2-Q3)

### 25.4 Should a cut list refuse to extend a cut's out point past the end of its clip?

- **Today:** trimming in the editor refuses to extend past the end of the source clip once the clip's length is known ("the clip runs out N s before that -- there is no more source after this cut"); one description of extending in a cut list allows it without a check, and the live edit in Resolve refuses it.
- **Options:** A: always refuse once the clip's length is known. B: allow it in the cut list and leave the editing program to cope.
- **Recommended:** A, so a cut never asks for material that does not exist and every place behaves the same.
- **What you would notice:** with A an over-long extend is refused with a sentence; with B the cut list can hold a cut that cannot be placed.
- (cards-editor-2-Q4)

### 25.5 When someone changes an open cut list's file by hand, should the editor reload it from the file, or merge the change in as edits?

- **Today:** one description reloads the file within about a second, clears redo and shows "changed on disk, reloaded"; another turns the hand change into edits on top of the current cut list, keeps everyone's undo, sends a removed cut to the shelf rather than losing it, and tells every device "merged an edit made to the file outside the editor (N change(s))".
- **Options:** A: merge as edits. B: reload from the file and clear redo.
- **Recommended:** A, because nothing made in the editor meanwhile is lost and undo keeps working.
- **What you would notice:** with A a hand edit and an editor's work both survive; with B redo is lost and an edit in flight is refused.
- (cards-editor-2-Q5)

### 25.6 Should a person be able to open a cut list read-only from the list of cut lists?

- **Today:** a cut list can be opened read-only only by starting the server that way; nobody can choose it from a page.
- **Options:** A: a person chooses "read-only" when opening a cut list. B: drop read-only opening.
- **Recommended:** A, because it is useful for review and needs no admin step.
- **What you would notice:** with A anyone can look without risk of changing the cut; with B there is no read-only view.
- (cards-editor-2-Q8)

### 25.7 Should "Same loudness" level to the middle of the clips used in this cut, or of all the episode's interviews?

- **Today:** one description takes the middle of the speech levels of the clips the cut uses (shelf clips and other cut lists never count); another takes the middle of every source's level; your ruling says "the episode's median".
- **Options:** A: the clips used in this cut. B: every interview of the episode.
- **Recommended:** B if "the episode's median" meant exactly that, otherwise A; the text follows A because it is what the editor says on screen ("the middle of what this episode's own clips measure") and the level does not move when an unused interview is added.
- **What you would notice:** with A adding a clip to the cut can shift every clip's level slightly; with B the levels stay put while cutting.
- (cards-editor-2-Q10)

### 25.8 Should the gain set on a card be carried into Resolve when the cut is handed over?

- **Today:** the gain set on cards (plus or minus 30 dB) is heard in the editor but never sent to Resolve; every send says so.
- **Options:** A: carry it into Resolve as the clip's volume. B: leave it in the editor only.
- **Recommended:** A, so the cut sounds in Resolve as it did in the editor.
- **What you would notice:** with A no level work is done twice; with B the editor keeps warning that gain stays behind.
- (cards-editor-2-Q14)

## Tidy-ups

One thing that can be done from several places, the same job existing twice, things switched off for everyone, things nobody can reach, and tools only the builders use.

| # | Question | Today | Recommended |
|---|---|---|---|
| 25.9 | Should Resolve's changes brought back into a cut list follow the same rules as a hand edit of the file? | a hand edit of the file sends a removed cut to a shelf and keeps moves made meanwhile; bringing Resolve's changes back replaces whole cuts and places rows by Resolve's layout. | A, one way of turning a changed cut list into edits, and nothing removed in Resolve is lost from the cut list. (cards-editor-2-Q6) |
| 25.10 | A "refresh every cut's words now" action exists that nobody can reach. Should it become a button, or go? | the product can re-take every cut's words from the transcript at once and say how many changed, but no control calls it. Words are already refreshed on their own whenever a span changes and every time a cut list opens. | A, since the words already follow the transcript by themselves at every open and every edit. (cards-editor-2-Q7) |
| 25.11 | The editor has two places that show the picture: the Video tab you asked for, and a floating video window that can be moved into its own browser window. Keep both, or make one video panel? | a dockable Video tab on the desk (zoomable, not on phones) plays each interview's small preview in step with the playhead, as you ruled. A separate floating "Video" window (Shift+V, on phones too) shows the clip under the head and can be moved into its own browser window, which comes back differently from the other panels that can be moved into windows. | A, one place for the picture, with every panel moving to its own window the same way. (cards-editor-2-Q9) |
| 25.12 | Keep the dimmed clip while its sound is being made, and the "N of M" count with the studio's computers' share? | an earlier page of the editor dimmed a clip on the lane while its sound copy was being made, made sound before pictures, and showed progress as "N of M" plus the share done on the studio's other computers. Those pages are retired; with every copy now made on its own when a clip arrives, a clip that is not ready is rare. | A for the dimmed clip (it says plainly why a clip is silent) and B for the count, which repeats what the per-clip progress shows. (cards-editor-2-Q11) |
| 25.13 | Two maintenance commands are for the people building the product. May they go? | a command run by hand brings every cut list of an episode in line with the montage sources' real names and frame rates; another makes the light sound copies of every interview in advance. | A, since the copies are made automatically and nothing a person does needs them. (cards-editor-2-Q12) |
| 25.14 | When a cut is deleted, should it always go to the cut list's shelf, even when the cut is being edited live in Resolve? | deleting in the editor puts the cut on the cut list's shelf, under its section's name; deleting in the live Resolve view removes it from Resolve and keeps the piece on an "offcuts" timeline; a staged draft applied in Resolve uses "OffCuts". | A, one place where a deleted cut waits, inside the cut list where it can be put back. (cards-editor-2-Q13) |

## Your answers

Not yet answered.
