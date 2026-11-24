# Trace of cards-editor-2

## Coverage

- 19-045 | A cut list survives a crash, and damage costs only what came after it
- 28-015 | Ctrl+Z undoes, and Ctrl+Shift+Z and Ctrl+Y redo
- 28-062 | Every action takes effect on screen at once, and a refused one says why
- 28-063 | After an edit, the head stays on the same moment of the same clip
- 28-069 | Trimming an edge, and what a trim says when it removes the cut or shortens a fade
- 28-070 | Trimming to the playhead and taking a range out of a cut
- 28-071 | Splitting a cut and moving items
- 28-072 | Deleting stages cuts on the shelf under their section's name and takes gaps out
- 28-074 | Inserting and resizing gaps
- 28-075 | Fades, gain, clip colour, notes and markers are edits like any other
- 28-076 | Undo and redo take back only this editor's own edits, and refuse when someone else has since changed the same thing
- 29-021 | Inserting and resizing gaps
- 29-029 | The inspector shows and edits the selected cut's edges, gain and fades
- 29-033 | The edit view trims one cut, with its header, a trim lane and its words
- 29-034 | The edit view trims one cut, with its header, a trim lane and its words
- 30-031 | A cut's words always follow its span, on every device
- 30-032 | left out: cut by the owner (2026-11-24, cards-editor-2-Q7)
- 32-023 | A person can start a new, empty cut list in an episode
- 32-024 | A person can duplicate a cut list as it is now
- 32-025 | A cut list that nobody has open can be renamed, and everything tied to it follows
- 32-026 | Rename on the open cut list changes its title instead, on every device, undoably
- 32-027 | Cut list names follow the same rules everywhere, with a plain refusal for each
- 32-028 | Making a cut list never overwrites one, and a server that cannot write says so
- 33-015 | The shelf, its categories and saved sequences live in the cut list file itself
- 34-021 | A cut list survives a crash, and damage costs only what came after it ; Opening, browsing and playing never change a file of the episode
- 34-022 | The cut list file follows the editor within a moment and keeps a backup of its previous version
- 34-024 | The cut list file can be edited by hand, and the editor merges the change
- 34-025 | A cut list holds the cut, the bench and the timeline's facts
- 34-027 | Edits name what they change and can never break the cut list
- 34-028 | An edge is set to a source second, and everything after it ripples
- 34-029 | Splitting a cut and moving items
- 34-030 | Moving, staging, unstaging and throwing away cuts follow fixed rules ; Deleting stages cuts on the shelf under their section's name and takes gaps out ; Splitting a cut and moving items
- 34-031 | A new cut, a pasted run and a new gap are checked before they go in
- 34-032 | Inserting and resizing gaps ; Fades, gain, clip colour, notes and markers are edits like any other
- 34-033 | Fades, gain, clip colour, notes and markers are edits like any other
- 34-038 | Undo puts back only what the undone edit changed ; Edits name what they change and can never break the cut list
- 34-042 | The cut list file is one readable, hand-editable Markdown file per cut list, in a fixed order of parts
- 34-043 | The frontmatter block carries the timeline's facts in a fixed canonical form
- 34-044 | Clip lines and extra-data lines in the frontmatter
- 34-045 | The comment preamble and the title
- 34-046 | Headings: how each kind is written and recognised
- 34-047 | Bullets: cut lines, gap lines and note rows
- 34-048 | Lines under a cut: fade, gain, note, transcript link and words
- 34-049 | Comments, id lines, gap notes and section summaries
- 34-050 | The writer gives the same text for the same cut list, and a hand-formatted file keeps its formatting
- 34-051 | Numbers and white space in the file follow fixed rules so a file reads and writes back identically
- 39-032 | A cut list opens as cards with no editing program, and can be opened read-only
- 39-035 | Each card's words are read again from the transcript every time a cut list opens
- 39-040 | left out: cut by the owner (2026-11-24, cards-editor-2-Q5)
- 39-041 | Edits are applied in order, each one a numbered revision, and nothing is ever overwritten
- 39-042 | Reordering cards keeps each section heading with its own cuts
- 39-047 | Splitting, trimming, extending and inserting change the cut list exactly to the frame
- 39-048 | Fades, gain, clip colour, notes and markers are edits like any other
- 39-052 | Undo and redo take back only this editor's own edits, and refuse when someone else has since changed the same thing ; Every revision of a cut list is kept, thinned rather than lost
- 39-059 | The cut list file is one readable, hand-editable Markdown file per cut list, in a fixed order of parts
- 39-060 | The frontmatter block carries the timeline's facts in a fixed canonical form
- 39-061 | Headings: how each kind is written and recognised
- 39-062 | Bullets: cut lines, gap lines and note rows
- 39-063 | Colours, forgiving reading, loud errors and tidy writing ; Every revision of a cut list is kept, thinned rather than lost
- 40-061 | Every action takes effect on screen at once, and a refused one says why
- 40-089 | left out: for the builders only
- 28-073 | Staging without deleting, and putting shelf items back on the timeline
- 29-025 | A note can be written under any cut
- 29-030 | The inspector also shows a selected gap and a selected staged card
- 29-031 | The staged shelf keeps cards to hand, per section, ready to place
- 33-001 | The shelf panel shows cuts set aside from the cut, in two tabs, Staged and Sequences
- 33-002 | On the desk, the shelf can take the rail's whole height or share it with the section list
- 33-003 | Category chips filter the Staged tab
- 33-004 | A shelf category for interviewer questions is locked, for reference only
- 33-005 | Each staged card shows its words, speaker, duration and category, and can be selected
- 33-006 | Place puts a staged card back into the cut
- 33-007 | A staged card can be listened to off the timeline, from its start or from any word
- 33-008 | A staged card has a menu, by right-click on the desk or a long press on touch
- 33-010 | On the desk, a staged card is filed by dragging it onto a chip
- 33-011 | A card of the cut is staged by dragging it onto the shelf
- 33-012 | The Stage buttons stage the selection onto the shelf, and the shelf turns to show it
- 33-013 | The categories overlay lists every shelf category and lets each be renamed or removed
- 33-014 | The name dialogs for categories and sequences
- 33-016 | The Sequences tab lists every saved sequence with a preview of its cuts
- 33-017 | Play the run plays a saved sequence, black included, off the timeline
- 33-018 | Put back at the playhead returns a whole saved sequence into the cut
- 33-019 | A saved sequence can be dragged back into the cut, onto the cards or the lane
- 33-020 | Save as sequence takes an unbroken run out of the cut and keeps it whole
- 33-023 | Stage to files the selected cuts onto a chosen shelf category
- 33-035 | A gap can carry a short note saying what the black is for
- 33-036 | A gap card shows its note, or a button to add one
- 33-037 | The gap note is written in an inline editor on the gap card
- 33-041 | A Gap notes panel lists every gap of the cut with its note
- 34-035 | Cards are put on the shelf, taken back, moved within it and filed under categories
- 34-036 | Save as sequence takes an unbroken run out of the cut and keeps it whole ; A run of cuts is saved as a sequence, set aside whole, and brought back whole
- 39-039 | Everything set aside is listed beside the cut
- 39-043 | Deleting stages cuts on the shelf under their section's name and takes gaps out
- 39-044 | Cards are put on the shelf, taken back, moved within it and filed under categories
- 39-045 | A run of cuts is saved as a sequence, set aside whole, and brought back whole
- 39-050 | A note on a card or a gap is kept in the cut list as an edit like any other
- 39-051 | Phrases on a card or a shelf card can be highlighted, and must be the card's own words
- 40-018 | Notes on cards and gaps go with the cut when it is handed over
- 28-003 | Space plays and pauses with a tap, and plays at double speed while held
- 28-004 | K pauses, L plays, J jumps two seconds back
- 28-006 | Home, End and the edit-point keys jump the head
- 28-016 | Alt+Shift with the arrows, Page keys and 0 change a cut's gain
- 28-065 | Play, pause and what stops playback from starting
- 28-066 | Moving the head while stopped is heard, rates run from 0.25x to 4x, and sound problems are reported
- 29-022 | The cards list scrolls itself sensibly, and F follows or finds the card being heard
- 29-036 | The transport plays, steps cuts, shows timecode and zooms the lane
- 29-037 | Play, pause and what stops playback from starting
- 29-040 | Shift+P records a place in the cut and P jumps between recorded places
- 30-018 | The transcript plays its own audio, at the lane's levels, and Space decides what to play in a fixed order
- 32-037 | The video window shows the picture of the clip under the playhead, switched on and off from the toolbar or Shift+V
- 32-038 | The video panel can be sized, moved and resized, and says why there is no picture
- 32-039 | The video picture stays on the sound, while playing, scrubbing and across joins
- 32-040 | The video window can be moved into its own browser window
- 33-030 | The gain dialog sets a cut's loudness on top of the automatic levelling
- 33-065 | Preview sound brings every interviewee to the same loudness, or plays each clip at its own level
- 33-066 | A preview volume slider turns the whole preview up or down
- 33-072 | Playback runs through gaps as silence, and joins never click
- 33-073 | Fades and a cut's gain are heard as drawn, live while being dragged
- 33-074 | A master volume and a limiter keep the preview from clipping
- 33-075 | Pressing play starts quickly and the head on screen matches what is heard
- 33-076 | Seeking or editing while playing does not stop the sound
- 33-077 | A clip whose audio is missing or cannot be levelled still plays, and the editor is told
- 33-078 | Playback speed goes from a quarter to four times, keeping pitch
- 33-079 | Dragging the head, jogging or dragging a trim edge plays the sound under it
- 33-080 | The first Play is never delayed by a sleeping sound device
- 33-081 | Automatic levelling brings every interviewee to the same speech level
- 33-106 | Play, pause and what stops playback from starting
- 34-015 | Automatic levelling brings every interviewee to the same speech level
- 29-060 | A Video tab shows the interview under the playhead, in step with the sound
- 32-041 | Every clip is made ready to play without anyone asking ; The browser is given light copies, never the camera originals ; Each clip's picture copy comes from its own media, and a failure is remembered until the media changes
- 32-042 | Each clip's picture copy comes from its own media, and a failure is remembered until the media changes
- 34-013 | The editor finds each clip's sound by itself and lists the clips it cannot play ; The footage is never touched, and everything made for playback is kept apart from it
- 34-014 | Each clip's waveform is made once, fine enough for 1/200 of a second, and reused
- 39-034 | Facts the editing program knows about a clip win over what the cut list recorded
- 40-027 | The footage is never touched, and everything made for playback is kept apart from it
- 40-028 | A clip whose sound is still being prepared is dimmed on the lane ; The editor finds each clip's sound by itself and lists the clips it cannot play ; The browser is given light copies, never the camera originals
- 40-029 | left out: cut by the owner (2026-11-24, cards-editor-2-Q11)
- 40-030 | The browser is given light copies, never the camera originals ; Every clip is made ready to play without anyone asking
- 40-031 | Each clip's waveform is made once, fine enough for 1/200 of a second, and reused
- 40-090 | left out: for the builders only

## Questions for the owner

### cards-editor-2-Q1: The cut list file still carries three marks of the notes program you cut. Do they stay exactly as they are, and does editing the file by hand outside Timeline Cards stay supported?
- Kind: other
- Today: you ruled that the `.cut.md` file stays as it is, and the text gives its format exactly. That format carries, under every cut, a link line to a transcript paragraph written in the notes program's form (`[[<speaker or clip>_Transcript#^<ref>]]`); two header keys that name the notes vault's root and the planning canvas (`vault_root`, `canvas`); a comment at the top written for someone editing the file by hand; and the file lives in the episode's `Script Docs/Cuts` folder. The editor also notices a hand edit of the file within 2 seconds and merges it in as edits.
- Options: A: keep every mark and the folder exactly, and keep hand editing supported (every existing cut list opens unchanged, and a person can still fix a cut list in a text editor). B: keep reading every mark so old files open unchanged, but stop writing the link line and the two keys in new files, and drop support for hand edits made while the editor has the file open.
- Recommend: A, because it is what you ruled ("the file stays as it is"), it costs nothing a person meets, and the link still points at the right paragraph of the one-file transcript.
- Changes for a person: with A nothing changes; with B new files look slightly different in a text editor, and a hand edit made while the editor is open is overwritten instead of merged.
- Text assumes: A
- Items: 34-024, 34-042, 34-043, 34-045, 34-048, 39-059, 39-060, 39-061, 39-062
- Covers: 34-Q7, 39-Q7
- Answered by the owner 2026-11-24: A: every mark and the folder kept exactly, hand editing stays supported

### cards-editor-2-Q2: When two people edit the same cut list, should Undo take back only your own last edit, or step the file back to its previous version whoever made it?
- Kind: differs
- Today: the editor's Undo takes back only this person's own edits, per device, and refuses ("cannot undo the trim: cut 4 was changed since by another edit") when someone else has since changed the same thing; its history survives a reload. Another description has Undo put back the newest saved revision of the file whoever made it, with "nothing to undo -- this is the first revision of the file", "back to rev N" and redo lasting only the session. Your ruling says undo steps back through saved versions, which are kept and thinned.
- Options: A: Undo takes back your own edits only (each undo restores the version from before that edit, so it is still a saved version, and works after a restart); every revision is kept, the newest 200 and then every tenth, so a cut list can always be put back. B: Undo steps the whole file back one saved revision, including another person's edit.
- Recommend: A, because with two people on one episode B would silently take back someone else's work, while for one person working alone the two are the same.
- Changes for a person: with A a shared cut list never loses a colleague's edit to your Undo; with B the Undo button can undo things you did not do.
- Text assumes: A
- Items: 28-076, 39-052, 39-063
- Answered by the owner 2026-11-24: A: Undo takes back your own edits; every saved version is kept

### cards-editor-2-Q3: Is a gap a row of its own that stays where it was put, or the black before the cut that follows it?
- Kind: differs
- Today: the editor treats a gap as its own card: it stays where it was put when the clips beside it move, can be selected, moved, sized and deleted, and several gap lines in a row stay separate. Another description treats a gap as "the black before a cut": it belongs to the cut after it, several gap lines before a cut are added into one, and deleting a cut moves its black onto the next cut.
- Options: A: a gap is its own row (what the editor shows). B: a gap is the black before the following cut.
- Recommend: A, because it is what an editor sees and drags on screen, and every existing file reads the same either way.
- Changes for a person: with A deleting a cut leaves the gap where it was; with B the gap jumps onto the next cut and two gaps in a row merge into one.
- Text assumes: A
- Items: 28-072, 28-074, 29-030, 34-025, 34-047, 39-043, 39-048, 39-063
- Answered by the owner 2026-11-24: A: a gap is its own row that stays where it was put

### cards-editor-2-Q4: Should a cut list refuse to extend a cut's out point past the end of its clip?
- Kind: other
- Today: trimming in the editor refuses to extend past the end of the source clip once the clip's length is known ("the clip runs out N s before that -- there is no more source after this cut"); one description of extending in a cut list allows it without a check, and the live edit in Resolve refuses it.
- Options: A: always refuse once the clip's length is known. B: allow it in the cut list and leave the editing program to cope.
- Recommend: A, so a cut never asks for material that does not exist and every place behaves the same.
- Changes for a person: with A an over-long extend is refused with a sentence; with B the cut list can hold a cut that cannot be placed.
- Text assumes: A
- Items: 28-069, 34-028, 39-047
- Answered by the owner 2026-11-24: A: always refused once the clip's length is known

### cards-editor-2-Q5: When someone changes an open cut list's file by hand, should the editor reload it from the file, or merge the change in as edits?
- Kind: differs
- Today: one description reloads the file within about a second, clears redo and shows "changed on disk, reloaded"; another turns the hand change into edits on top of the current cut list, keeps everyone's undo, sends a removed cut to the shelf rather than losing it, and tells every device "merged an edit made to the file outside the editor (N change(s))".
- Options: A: merge as edits. B: reload from the file and clear redo.
- Recommend: A, because nothing made in the editor meanwhile is lost and undo keeps working.
- Changes for a person: with A a hand edit and an editor's work both survive; with B redo is lost and an edit in flight is refused.
- Text assumes: A (the reload passage is written, marked, to be deleted if A is chosen)
- Items: 39-040, 34-024
- Answered by the owner 2026-11-24: A: a hand change is merged in as edits; the reload passage is deleted

### cards-editor-2-Q6: Should Resolve's changes brought back into a cut list follow the same rules as a hand edit of the file?
- Kind: built twice
- Today: a hand edit of the file sends a removed cut to a shelf and keeps moves made meanwhile; bringing Resolve's changes back replaces whole cuts and places rows by Resolve's layout.
- Options: A: both follow the hand-edit rules (removed cuts go to the shelf, only what changed moves). B: keep the two different.
- Recommend: A, one way of turning a changed cut list into edits, and nothing removed in Resolve is lost from the cut list.
- Changes for a person: with A a cut removed in Resolve waits on the shelf; with B it is gone from the cut list.
- Text assumes: A
- Items: 34-024
- Covers: 34-Q1
- Answered by the owner 2026-11-24: A: Resolve's changes follow the hand-edit rules

### cards-editor-2-Q7: A "refresh every cut's words now" action exists that nobody can reach. Should it become a button, or go?
- Kind: unreachable
- Today: the product can re-take every cut's words from the transcript at once and say how many changed, but no control calls it. Words are already refreshed on their own whenever a span changes and every time a cut list opens.
- Options: A: drop it. B: offer it as a button in the editor.
- Recommend: A, since the words already follow the transcript by themselves at every open and every edit.
- Changes for a person: none with A; with B one more button.
- Text assumes: written and marked, to be deleted if A is chosen
- Items: 30-032
- Covers: 30-Q5
- Answered by the owner 2026-11-24: A: dropped; the passage is deleted

### cards-editor-2-Q8: Should a person be able to open a cut list read-only from the list of cut lists?
- Kind: other
- Today: a cut list can be opened read-only only by starting the server that way; nobody can choose it from a page.
- Options: A: a person chooses "read-only" when opening a cut list. B: drop read-only opening.
- Recommend: A, because it is useful for review and needs no admin step.
- Changes for a person: with A anyone can look without risk of changing the cut; with B there is no read-only view.
- Text assumes: A
- Items: 39-032
- Covers: 39-Q17
- Answered by the owner 2026-11-24: A: a person chooses read-only when opening a cut list

### cards-editor-2-Q9: The editor has two places that show the picture: the Video tab you asked for, and a floating video window that can be moved into its own browser window. Keep both, or make one video panel?
- Kind: built twice
- Today: a dockable Video tab on the desk (zoomable, not on phones) plays each interview's small preview in step with the playhead, as you ruled. A separate floating "Video" window (Shift+V, on phones too) shows the clip under the head and can be moved into its own browser window, which comes back differently from the other panels that can be moved into windows.
- Options: A: one video panel: the Video tab, which can also float, be moved into its own window like every other panel, and show on a phone. B: keep both as they are.
- Recommend: A, one place for the picture, with every panel moving to its own window the same way.
- Changes for a person: with A Shift+V and the toolbar's Video button open the one panel; with B the two stay, with their different ways back.
- Text assumes: B as written (the floating window's passages are marked, so they can be folded into the Video tab if A is chosen)
- Items: 29-060, 32-037, 32-038, 32-040
- Covers: 32-Q7
- Answered by the owner 2026-11-24: A: one video panel, the Video tab, which also floats, moves into its own window like every other panel, and shows on a phone

### cards-editor-2-Q10: Should "Same loudness" level to the middle of the clips used in this cut, or of all the episode's interviews?
- Kind: differs
- Today: one description takes the middle of the speech levels of the clips the cut uses (shelf clips and other cut lists never count); another takes the middle of every source's level; your ruling says "the episode's median".
- Options: A: the clips used in this cut. B: every interview of the episode.
- Recommend: B if "the episode's median" meant exactly that, otherwise A; the text follows A because it is what the editor says on screen ("the middle of what this episode's own clips measure") and the level does not move when an unused interview is added.
- Changes for a person: with A adding a clip to the cut can shift every clip's level slightly; with B the levels stay put while cutting.
- Text assumes: A
- Items: 33-065, 33-081, 34-015
- Answered by the owner 2026-11-24: the recommendation as written: the clips used in this cut (the text's reading)

### cards-editor-2-Q11: Keep the dimmed clip while its sound is being made, and the "N of M" count with the studio's computers' share?
- Kind: unreachable
- Today: an earlier page of the editor dimmed a clip on the lane while its sound copy was being made, made sound before pictures, and showed progress as "N of M" plus the share done on the studio's other computers. Those pages are retired; with every copy now made on its own when a clip arrives, a clip that is not ready is rare.
- Options: A: keep both (the dimmed clip and the count). B: drop them; the per-clip progress already written stays.
- Recommend: A for the dimmed clip (it says plainly why a clip is silent) and B for the count, which repeats what the per-clip progress shows.
- Changes for a person: with A a clip that cannot play yet looks different on the lane; without the count nothing else is lost.
- Text assumes: both written and marked
- Items: 40-027, 40-028, 40-029, 40-030, 40-031
- Answered by the owner 2026-11-24: A for the dimmed clip (kept), B for the count (deleted)

### cards-editor-2-Q12: Two maintenance commands are for the people building the product. May they go?
- Kind: dev only
- Today: a command run by hand brings every cut list of an episode in line with the montage sources' real names and frame rates; another makes the light sound copies of every interview in advance.
- Options: A: they go; the product keeps names and rates right by itself and makes the copies when clips arrive. B: keep them as admin buttons.
- Recommend: A, since the copies are made automatically and nothing a person does needs them.
- Changes for a person: none.
- Text assumes: left out
- Items: 40-089, 40-090
- Answered by the owner 2026-11-24: A: they stay left out

### cards-editor-2-Q13: When a cut is deleted, should it always go to the cut list's shelf, even when the cut is being edited live in Resolve?
- Kind: built twice
- Today: deleting in the editor puts the cut on the cut list's shelf, under its section's name; deleting in the live Resolve view removes it from Resolve and keeps the piece on an "offcuts" timeline; a staged draft applied in Resolve uses "OffCuts".
- Options: A: always the shelf, and the live Resolve view mirrors it. B: keep the three.
- Recommend: A, one place where a deleted cut waits, inside the cut list where it can be put back.
- Changes for a person: with A no offcuts timelines appear in Resolve; deleted cuts are always on the shelf.
- Text assumes: A (the editor's delete; the live Resolve view is written with the hand-over)
- Items: 39-043
- Covers: 39-Q3
- Answered by the owner 2026-11-24: A: a deleted cut always goes to the shelf

### cards-editor-2-Q14: Should the gain set on a card be carried into Resolve when the cut is handed over?
- Kind: other
- Today: the gain set on cards (plus or minus 30 dB) is heard in the editor but never sent to Resolve; every send says so.
- Options: A: carry it into Resolve as the clip's volume. B: leave it in the editor only.
- Recommend: A, so the cut sounds in Resolve as it did in the editor.
- Changes for a person: with A no level work is done twice; with B the editor keeps warning that gain stays behind.
- Text assumes: left out (it is the hand-over's behaviour)
- Items: 39-048
- Covers: 39-Q4
- Answered by the owner 2026-11-24: A: the gain goes with the cut into Resolve

## Readers' questions and unsettled points

- 28-Q1 | with cards-editor-1
- 28-Q4 | answered: owner's requirements, section 4 (every key, button and gesture of the editor is kept)
- 28-Q7 | with cards-editor-1
- 29-Q6 | with cards-editor-1
- 29-Q7 | answered: owner's requirements, section 4 (both the hold and the toggle are controls of the editor and are kept)
- 30-Q5 | cards-editor-2-Q7
- 32-Q7 | cards-editor-2-Q9
- 33-Q11 | with cards-editor-1
- 34-Q1 | cards-editor-2-Q6
- 34-Q7 | cards-editor-2-Q1
- 39-Q3 | cards-editor-2-Q13
- 39-Q4 | cards-editor-2-Q14
- 39-Q7 | cards-editor-2-Q1
- 39-Q8 | cards-editor-2-Q4
- 39-Q17 | cards-editor-2-Q8
- 40-Q7 | with cards-editor-1
- U-28-3 | settled: the refusals and their sentences are those of the edit rules written under the editing headings
- U-28-4 | settled: the shelf is the file's `## staged` heading with the category after a spaced long dash, the category named after the last section heading above the cut
- U-32-1 | settled: a cut list stops counting as open about ten minutes after the last device left it or last did anything with it; the exact refusal stays and the truth is said beside it
- U-33-3 | settled: shown to the editor (lessons CE1-082 and CE3-027)
- U-33-4 | settled: the edits behind the shelf and their refusals are written in this piece

## Still unsettled


## Conflicts between an item and a lesson

- CE3-023 | 28-076, 39-052 | the editor's undo takes back only its own edits; the ruling says undo steps back through saved versions. Wrote the editor's undo, framed so each undo restores a saved version, with every version kept and thinned; asked in cards-editor-2-Q2
- CE2-065 | 32-041, 40-030 | picture copies made only when someone has the video window on; the ruling says every clip's small copy is made when it lands or the project opens. Wrote the ruling
- CE1-051 | 39-050 | a gap's note kept outside the cut list; the ruling says every note lives in the cut list. Wrote the ruling
- CE1-063 | 34-021 | rows without an id given one and the file written back at once on opening; the lesson says opening leaves every file byte-identical. Wrote the lesson (ids are the same from the same content, so nothing needs writing)
- CE1-088 | 28-066, 33-079 | a short grain, or 70 ms snatches at normal pitch; the ruling says scrubbing plays at scrub speed in both directions. Wrote the ruling
- CE1-077 | 33-079 | the same: reverse and slow scrubbing must still sound like the words. Wrote the lesson
- CE2-062 | 32-038, 32-042 | a multicam shows "it has no file of its own"; the lesson says its picture comes from its angles' source files. Wrote the lesson
- CE3-047 | 29-060 | the Video tab is pulled back only past a quarter of a second; the lesson says within three frames. Wrote the lesson
- CE2-064 | 40-028 | a copied sound within 0.05 s of the original's length; the lesson says within 1 ms. Wrote the lesson
- CE3-040 | 28-065, 33-106 | other apps' sound back up on pause or stop; the lesson says released about 1.5 s after playback stops. Wrote the lesson
- CE2-058 | 33-081 | the target is the middle of the clips in the cut; the ruling says the episode's median. Wrote the item's reading, asked in cards-editor-2-Q10

## New in this text

- Every action takes effect on screen at once, and a refused one says why | the small saving mark, undo keeping selection and scroll, a disabled control answering a tap, one press one edit (CE3-021, CE3-027, CE3-022)
- Edits name what they change and can never break the cut list | a clashing edit refused, never merged silently, both people told (CE1-065, CE1-066)
- Edits are applied in order, each one a numbered revision, and nothing is ever overwritten | an acknowledged edit survives a second writer, a racing undo and a crash (CE1-064, CE1-066)
- Undo and redo take back only this editor's own edits, and refuse when someone else has since changed the same thing | offline undo, speed, notes never losing redo (CE3-024, CE3-025)
- Every revision of a cut list is kept, thinned rather than lost | written as a behaviour of its own (CE3-022, CE3-023)
- A cut list opens as cards with no editing program, and can be opened read-only | read-only chosen when opening, by a person (cards-editor-2-Q8)
- Opening, browsing and playing never change a file of the episode | the lesson CE1-063
- A person can start a new, empty cut list in an episode | the list names cut lists by file name, a differing title muted after it (CE3-035)
- A note can be written under any cut | notes on yellow, a yellow square on the lane clip, the note box at full width from the first keystroke (CE1-050, CE1-052)
- A note on a card or a gap is kept in the cut list as an edit like any other | notes from side files brought in once (CE1-051)
- A card of the cut is staged by dragging it onto the shelf | drop lands where the line showed, targets stay lit and reachable, updates resume after any drop (CE1-056, CE1-059, CE1-060, CE1-061)
- Cards are put on the shelf, taken back, moved within it and filed under categories | categories in document order, one per card, All lists every card (CE1-058, CE3-033)
- Dragging the head, jogging or dragging a trim edge plays the sound under it | scrubbing at speed, both directions, silenced on release (CE1-088, CE2-053)
- Automatic levelling brings every interviewee to the same speech level | a dead second channel played from the live one in both ears (CE3-042)
- Fades and a cut's gain are heard as drawn, live while being dragged | background tab, mid-fade changes and pauses, no picture fades (CE2-050, CE1-085)
- A clip whose audio is missing or cannot be levelled still plays, and the editor is told | missing timings or English named, slow first load retried (CE1-082, CE3-045, CE2-049)
- Every clip is made ready to play without anyone asking | copies made on arrival, progress per clip, playing moves a clip to the front (CE2-065, CE1-079, CE1-081)
- The browser is given light copies, never the camera originals | sound-only files, copy not convert, abandoned requests stopped (CE2-045, CE2-063, CE2-064, CE2-067)
- The editor finds each clip's sound by itself and lists the clips it cannot play | a clip with only a subtitle file plays and shows its words (CE1-080)
- A clip that becomes ready while the page is open plays at once, and every request gets a real try | CE3-043, CE3-044, CE3-046, CE2-069
- The video panel can be sized, moved and resized, and says why there is no picture | a multicam's picture from its angles (CE2-062)

## Parts of items left out

- 39-041 | the reload-and-refuse before a write and its sentence "the project file changed on disk -- reloaded, redo your edit": cut by the joins (2026-11-24, cards-editor-2 F4, page 25.5 A); written as an "Except that" sentence because the line is carried exactly
- 40-018 | its refusals "no timeline is open" and "that cut is no longer on the timeline", notes on draft cards and notes following a re-identified card: cut by the joins (2026-11-24, cards-to-resolve-and-exports F4, page 29.2 B); written as an "Except that" sentence because the line is carried exactly
- 30-031 | the letter comparison with the paragraph (40 %) and the speech-to-text's spelling elsewhere: cut by the joins (2026-11-24, cards-footage-in F3, owner's requirements section 6)
- 34-013 | playing the full reference recording while its light copy is not ready: cut by the joins (2026-11-24, cards-editor-2 F5)

- 29-060 | "It is not on phones": by the owner's answer to cards-editor-2-Q9 the Video tab is the one video panel, which floats on a phone
- 32-037 | framed as the one video panel (cards-editor-2-Q9); its exact text is kept

- 19-045 | the 15 seconds the editor is given to save when the server stops: an arrangement; the promise (nothing is lost) is written
- 28-066 | "a short grain of audio where it lands": replaced by the scrubbing ruling CE1-088
- 29-060 | the preview file's name and "the pipeline makes it" in the no-preview message (replaced by a plain reason, as the item itself asks); the quarter-second drift (lesson CE3-047)
- 30-031 | "for every cut list that has been open in the last 20 minutes": an arrangement; the promise is every cut list open on any device
- 32-026 | the separate retitle action with no button of its own: an inside; the same change is reached through Rename on the open list
- 32-028 | the working copy a server with a read-only tree keeps, and the refusal's wording naming the vault: an arrangement; the plain refusal is written
- 32-038 | "No video for this clip: a multicam is a sequence, it has no file of its own." (lesson CE2-062)
- 32-039 | proxies being checked for every 4 s (8 s after a failure): an arrangement; the promise (shows at once when ready) is written
- 32-041 | made only when the window is on, one at a time, 64 waiting, the 8 GB store and its eviction, at most 500 clips, "the cut list does not use that clip", counts since the server started, "The video window is off.": arrangements, and the ruling CE2-065
- 32-042 | reusing 480p proxies earlier tools made, and the server setting that maps editors' drive letters to server paths: arrangements (an admin has nothing to set; the product knows where its files are)
- 33-074 | "the browser's own make-up gain is taken back out": an inside
- 34-013 | sound requests turned away for a second under heavy load and asked again: an arrangement; the promise (every request gets a real try) is written
- 34-014 | kept beside the clip's listening copy, and two computers making one at once: arrangements
- 34-021 | ids written back at once on opening (lesson CE1-063); "move the history aside" reworded as telling the person how to start again from the file
- 34-022 | the 0.15 s delay and the doubling retry times: arrangements; "at most 30 seconds apart" is kept
- 34-024 | "sooner when the computer reports it": an inside
- 39-032 | read-only chosen only when the server is started: an arrangement (cards-editor-2-Q8)
- 39-043 | its note "N cut(s) deleted -- staged under ## staged — <name>" (the editor's own notice is written) and the black moving onto the next surviving cut (cards-editor-2-Q3)
- 39-047 | "In a cut list an out point can be extended past the end of the clip's source without refusal" (cards-editor-2-Q4)
- 39-048 | the gap as "the black before a cut", moved from another cut, and its notes (cards-editor-2-Q3)
- 39-050 | the gap's note kept outside the cut list in the episode's notes (ruling CE1-051)
- 39-052 | its messages ("nothing to undo -- this is the first revision of the file", "back to rev N", "forward to rev N") and redo lasting only the session (cards-editor-2-Q2)
- 39-060 | "by update-project" in the `written` stamp: a tool's name, replaced by its role
- 39-063 | "Several gap lines before a cut are added into one; a gap always belongs to the cut after it." (cards-editor-2-Q3)
- 40-028 | the state "the tool for making it missing", the 30-minute give-up, and how a copy is re-encoded: insides
- 40-029 | left out: cut by the owner (2026-11-24, cards-editor-2-Q11)
- 40-030 | made only once a page turns the video window on (ruling CE2-065); the copy carrying its sound (sound is never taken from a video file); the 60 minutes kept as "an hour"
- 40-031 | at most 2 made at once, and the "tool missing" state: insides
- CE2-055 | playhead positions sent about ten times a second: the half of the lesson that is an arrangement; the promise (one request in flight, the final position always heard) is written

## Joins with other capabilities

- Timeline Cards: the hand-over to Resolve, and exports / Sending a cut to Resolve | The gain dialog sets a cut's loudness on top of the automatic levelling | a cut's own gain is carried into Resolve (cards-editor-2-Q14)

- Timeline Cards: the hand-over to Resolve, and exports / Undo, markers, titles, fades and properties | Notes on cards and gaps go with the cut when it is handed over | a gap's note is taken fresh from what is saved at the send
- Timeline Cards: the hand-over to Resolve, and exports / Bringing Resolve's changes back into the cut | The cut list file can be edited by hand, and the editor merges the change | Resolve's changes become edits (cards-editor-2-Q6)
- Timeline Cards: the hand-over to Resolve, and exports / Sending a cut to Resolve | A cut list opens as cards with no editing program, and can be opened read-only | a read-only cut list can still be handed over
- Timeline Cards: the hand-over to Resolve, and exports / Exports | A cut list holds the cut, the bench and the timeline's facts | frames appear only in exports; per-clip rate and start timecode are used where Resolve's project does not know the clip (exports, a clip a send brings in)
- Timeline Cards: the hand-over to Resolve, and exports / Placing, deleting and linking clips in Resolve | Deleting stages cuts on the shelf under their section's name and takes gaps out | where a delete goes in Resolve (cards-editor-2-Q13)
- Timeline Cards: footage in, ready to cut / The transcript and its English | A cut's words always follow its span, on every device | word timings, transcript spelling and paragraph references
- Timeline Cards: footage in, ready to cut / Footage files and files made from them | Every clip is made ready to play without anyone asking | which copies each clip gets (an interview's, a montage clip's), made as clips arrive
- Work shared out across the computers / Choosing who runs what | A clip whose sound is still being prepared is dimmed on the lane | a piece of work given up there; the clip here reads "failed" with the reason
- the carry-over companion to this specification (owner's requirements, section 7) | A note on a card or a gap is kept in the cut list as an edit like any other | side-file notes brought in once with the carry-over
- Timeline Cards: the board / What the board is | A cut list holds the cut, the bench and the timeline's facts | the planning board a cut list came from, and a board made into a cut bringing its groups
- Work shared out across the computers / Choosing who runs what | Sound is always prepared before video, and progress is shown as a count | making copies on the studio's computers
- Timeline Cards: the editor (part 1) / The lane: how clips look and read | Playback runs through gaps as silence, and joins never click | the lit word, the playhead mark and paging, written there
- Timeline Cards: the editor (part 5) / Phone and game controller | Dragging the head, jogging or dragging a trim edge plays the sound under it | the phone scrub pad and the controller's jog

## Joins settled

- cards-board F2 | no change here: the board's hand-over gives one note row per line; the cut list format is kept as it is
- cards-editor-1 F6 | no change here: cards-editor-1 points to cards-editor-4; the summary lines under an in-cut heading already stand here
- cards-editor-2 F1 | changed: Inserting and resizing gaps | a new gap that would land after the last item is refused (an "Except that" sentence after the carried line)
- cards-editor-2 F2 | no change here: cards-editor-4 changes; this piece already keeps the newest 200 and then every tenth
- cards-editor-2 F3 | changed: Every revision of a cut list is kept, thinned rather than lost | each revision keeps its time and who made it
- cards-editor-2 F4 | changed: Edits are applied in order, each one a numbered revision, and nothing is ever overwritten | no reload-and-refuse; a change on disk is merged first (an "Except that" sentence; the carried line still holds the old rule, reported to the lead)
- cards-editor-2 F5 | changed: The editor finds each clip's sound by itself and lists the clips it cannot play | the full reference recording dropped from the order; a clip without its light copy shows as being made
- cards-editor-2 F6 | no change here: cards-board names the keys itself and points to cards-editor-1
- cards-editor-2 F7 | no change here: cards-board's row reads the plain shelf (shown as Uncategorised)
- cards-editor-2 F8 | no change here: cards-board names its group "Interviewer questions" and sends chatter to Uncategorised
- cards-editor-2 F9 | changed: Everything set aside is listed beside the cut | no swap; an alternates card is put into the cut by unstaging it. The shelf panel's tabs show no alternates section (only the listing does): reported to the lead
- cards-editor-2 F10 | changed: The cut list file can be edited by hand, and the editor merges the change | bench sections matched by kind and name; Resolve's changes named as the one way a changed cut list becomes edits
- cards-editor-2 F11 | changed: The cut list file can be edited by hand, and the editor merges the change | a removed cut goes onto the shelf named after its section, as a deleted cut does
- cards-editor-2 F12 | changed: A clip whose sound is still being prepared is dimmed on the lane | the clip reads "failed" with the reason, never "given up"; a later request is new work; pointer to fleet-jobs
- cards-footage-in F3 | changed: A cut's words always follow its span, on every device | words taken straight from the transcript's timed words, no letter comparison, no speech-to-text spelling
- cards-footage-in F4 | changed: Every clip is made ready to play without anyone asking | points to footage-in for which copies each clip gets; playing order and progress kept
- cards-footage-in F5 | no change here in the text: only this trace's join line now points to the carry-over companion, not footage-in
- cards-footage-in F13 | no change here: footage-in and fleet-jobs change; this piece's picture-only copy, at most 480 lines and never enlarged, already agrees
- cards-to-resolve-and-exports F3 | no change here: cards-to-resolve-and-exports drops its standing "not yet carried" sentence
- cards-to-resolve-and-exports F4 | changed: Notes on cards and gaps go with the cut when it is handed over | renamed from "Notes on cards and gaps while a cut is worked on a live timeline"; live-timeline framing dropped; the refusals and draft-card notes cut by an "Except that" sentence (the carried line still holds them, reported to the lead); the gap-note-at-send rule points to the hand-over
- cards-to-resolve-and-exports F5 | no change here: cards-to-resolve-and-exports points to this piece's merge
- cards-to-resolve-and-exports F6 | no change here: cards-to-resolve-and-exports says a read-only send is not stamped; this piece already says the file is not changed
- cards-to-resolve-and-exports F7 | changed: A cut list holds the cut, the bench and the timeline's facts | "(hints for exports only)" replaced: per-clip rate and start used where Resolve's project does not know the clip; a hand-set value never overwritten
- cards-to-resolve-and-exports F8 | no change here: cards-to-resolve-and-exports moves the rate choice to the Send tab; the frontmatter rule here is unchanged
- fleet-jobs F12 | no change here: fleet-jobs adds that playing a clip puts its waiting media first
