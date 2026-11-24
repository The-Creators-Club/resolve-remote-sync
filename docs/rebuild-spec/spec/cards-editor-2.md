# Timeline Cards: the editor, part 2 of 5

This part covers editing and undo, the cut list and its file, notes and the staged shelf, playback and audio, and the media the browser is given so that every clip plays.

## Editing, undo and the cut list

### Every action takes effect on screen at once, and a refused one says why

{{28-062}}

An edit appears at once, with no full redraw and no veil over the page; the card being saved carries only a small saving mark until the edit is confirmed, and a refusal puts the card back as it was and says why. Undo keeps the selection and the scroll where they are. Every action gives a visible result or a reason where the person is looking, on any device, and the reason names something the person can reach; a control that is disabled still answers a tap with its reason. Holding an editing key never repeats the edit: one press is one edit.

When an edit cannot be carried out, the editor is told in a plain sentence:

{{40-061}}

- Exact: yes

### Edits name what they change and can never break the cut list

Every edit names the cuts, gaps and headings it changes by their permanent ids (shelves and saved sequences by name), never by position, and sets values outright (set an edge to a second, a gain to a value), so applying the same edit twice changes nothing more. A refused edit changes nothing and shows its sentence. After every edit the cut list is checked: an edit that would add a problem the cut list did not already have is refused ("internal: that edit would break the cut list (...)"), while a cut list that arrived with an oddity of its own can still be edited. The cut list always keeps:

- every id unique;
- every cut with a clip name, its in before its out, fades within the cut and gain within plus or minus 30 dB;
- no interviewer question in the cut;
- every gap longer than 0;
- every section and note heading with a colour;
- no two shelves with the same category and no two saved sequences with the same name.

Common refusals: "name at least one of the cuts", "cuts are named by id", "the same cut is named twice (<id>)", "a place is before a cut OR after one, not both", "X must be a number of seconds", "that cut is no longer in the cut list", "that gap is no longer in the cut list".

Where a moved or inserted block lands in the cut: "before X" lands between the rows above X and X, so the block joins X's section (headings above X stay above the block); "after X" lands directly after X; neither means the end of the cut. The anchor is a cut or a gap in the cut.

Where a block lands on the bench: in a category (made when first used; no name means the plain shelf), or before or after a cut already there (that cut's shelf wins over a category; "a cut cannot be put next to itself"; "that staged cut is no longer in the file"; an anchor in the alternates section is ignored and the category used).

Several edits can be made as one: the group is applied all or none ("an empty batch"; "batches nested too deep" past 32 levels), and is one undo step.

An edit made by one editor while another editor's edit has changed the same thing meanwhile is refused with its sentence, never merged silently, and both people see what happened; edits that touch different things both stand. Edits carrying the order the page saw are refused if the order changed meanwhile ("the cut list changed -- re-synced, try again").

### Edits are applied in order, each one a numbered revision, and nothing is ever overwritten

{{39-041}}

An edit the server has confirmed survives a second writer, an undo racing it, and a crash at any moment. When the same cut list is saved from two places at once, both changes are kept, or the second is refused and the conflict is shown to both people.

- Exact: yes

### Ctrl+Z undoes, and Ctrl+Shift+Z and Ctrl+Y redo

Ctrl+Z (everywhere, repeating): undo. Ctrl+Shift+Z and Ctrl+Y (everywhere, repeating): redo. What undo does is described under the next two headings.

- Exact: yes

### Undo and redo take back only this editor's own edits, and refuse when someone else has since changed the same thing

Each undo puts back the cut list as it was before that edit, which is a saved version of the cut list in its own right, so undo works after a reload and a restart. Undo works offline on edits not yet sent, never replays what was taken back, and online answers well under a second on a long episode. Notes, undos and redos made in any order and at any speed never lose a redo step and never set off a false "changed outside" reload.

{{28-076}}

- Exact: yes
- Pending: cards-editor-2-Q2

### Undo puts back only what the undone edit changed

Every edit can be undone and redone. Undo is refused when someone has since changed what it touches: "cannot undo: that part of the cut list was changed since by another edit", or "cannot undo: the order of the cut list was changed since by another edit". A cut's words, highlights and transcript link being refreshed does not count as a change, and rows others added or threw away do not block it. "cannot undo: that cut is no longer in the cut list" when a cut to bring back has nowhere to go.

- Highlights made since are kept: they are carried onto the restored words (grown by an overlapping restored highlight); one removed since stays removed; highlights on a piece the undo drops move to the restored cut of the same clip that covers them.
- A heading's summary or a gap's note that the undo did not mean to change keeps its current value.
- Only rows the undone edit moved or added are put back in place; every other row keeps its current place, so a move someone made since is not undone, and rows others added stay after the row they followed.

### Every revision of a cut list is kept, thinned rather than lost

Before each save the previous version of the cut list is kept in its history. The newest 200 revisions are all kept; older ones survive when their revision number is a multiple of 10, so a damaged or unwanted cut list can always be put back to an earlier revision.

### After an edit, the head stays on the same moment of the same clip

{{28-063}}

No edit moves the head forward while it is stopped, and play starts from wherever the head is.

- Exact: yes

### Trimming an edge, and what a trim says when it removes the cut or shortens a fade

A trim (an edge drag, E / Shift+E, an armed-edge key, a bumper drag):

- Refused "that cut is no longer in the cut list" (the cut is gone), "that gap is no longer in the cut list", "that edge is not a number of seconds".
- A shortening that would leave less than 1/24 s: for a cut on the timeline it becomes a delete (the cut is staged), with the info notice "<clip> trimmed away -- staged under ## <shelf title>" and the selection moving on as after a delete; for a cut on the shelf it is refused "that would leave nothing of the cut -- delete it instead".
- If it shortens the cut below the length of either of its audio fades, the info notice "cut <N>: the audio fade is longer than what is left of the cut, so it is shortened to <X.X> s" (N is the cut's place on the timeline; the clip name when not on the timeline).
- Extending past the end of the source clip is refused. Until the clips' lengths are known after opening, extends are not limited by the source's length.
- The selection does not change. The head rule applies (the head stays on the same moment of the same clip).

- Exact: yes
- Pending: cards-editor-2-Q4

### An edge is set to a source second, and everything after it ripples

An edge is set to a source second, on a cut in the cut or on the bench, and every cut and gap after it moves up or back. Refusals: an in point before 0, "the clip starts N s later than that -- there is no more source before this cut"; an out point past the known end of the source, "the clip runs out N s before that -- there is no more source after this cut"; a cut left at 0 or less, or under 1/24 s and shorter than before, "that would leave nothing of the cut -- delete it instead" (a cut already under 1/24 s may still be lengthened). Fades shrink to fit. Pulling an edge out over a neighbouring cut of the same source is allowed (that stretch then plays twice).

- Pending: cards-editor-2-Q4

### Trimming to the playhead and taking a range out of a cut

- Trim to the playhead (Q, W, LB, RB): the cut under the head, that edge to the head. Refused "put the head inside a cut first" when the head is in a gap or past the end.
- Taking the in / out range out: refused "the in / out range has to lie inside one cut" when either mark is missing, when they are less than one frame apart, or when the range is not inside one cut. On success both marks are cleared.
- Removing a range from a cut: the range is kept inside the cut. Refused "the selection is empty -- nothing removed" when it is shorter than 1/24 s. A range reaching both ends (within 1/24 s) is the whole cut: trimmed away (staged) as when a trim leaves less than 1/24 s. Reaching only the start: the in edge moves to the range's end. Reaching only the end: the out edge moves to the range's start. Otherwise the middle is taken out and the cut becomes two cuts. The head rule applies.
- For these, a frame is 1/30 s when the cut list gives no frame rate; for the keys and the controller it is 1/29.97 s.

- Exact: yes

### Splitting a cut and moving items

{{28-071}}

Taking a stretch out of a cut leaves the cut up to the stretch and a new cut from the stretch's end to the cut's out, placed right after it (the stretch is kept within the cut). Splitting does the same with nothing removed. The first piece keeps the cut's id and fade in; the second takes the fade out; both keep gain, colour, note, link, words and highlights. Gaps are not touched. Refusals: "the selection is empty -- nothing removed" (under 1/24 s); "that is the whole cut -- delete it instead"; "that would leave a piece shorter than a frame -- trim the edge instead"; for a split within 1/24 s of an edge, "the blade is at the edge of the cut -- nothing to split"; "the second piece needs a well-formed id"; "that id is already in use in this cut list".

A move takes a block of cuts and gaps, in the order named, to a place in the cut. A gap moves only when it is named. Only items in the cut move; "a block cannot be put next to itself".

- Exact: yes

### Reordering cards keeps each section heading with its own cuts

{{39-042}}

- Exact: yes

### Splitting, trimming, extending and inserting change the cut list exactly to the frame

Every edge an edit makes is snapped to the clip's own frames, so the cut list always maps back to the frame that will be placed in Resolve.

- Split at a word: "the blade is at the edge of the cut -- nothing to split" (less than a frame either side). The black before stays on the first half, the fade-out goes to the second half, everything else is copied to both. Note "split into two cuts".
- Trim (take out a stretch, clamped to the cut): "the selection is empty -- nothing removed" (under a frame); from the head or tail the in or out moves; from the middle it leaves two adjoining cuts, the fade-out moving to the second, both keeping note, colour, highlights, person and gain. Fades are shortened so neither is longer than the cut (together they may still overlap). Covering the whole cut: it becomes a delete with the note "<clip> trimmed away -- staged under <where>"; otherwise "X.X s taken out of the cut".
- Extend an edge: "edge is 'in' or 'out'"; "that edge is there already -- nothing to extend"; "the clip starts X.X s later than that -- there is no more source before this cut"; "that would leave nothing of the cut -- delete it instead"; note "the in/out point out/in X.X s". Fades are re-clamped.
- Insert a transcript passage: at a timeline frame (inside a cut, that cut is split and the passage goes between the halves; otherwise before the cut that starts at or after it), else after a named cut, else at the end; the clip is recorded in the cut list on first use. Note "inserted X.X s of <clip>".
- Insert straight onto the shelf (pasting a transcript paragraph while the shelf is open): note "staged X.X s of <clip>".

- Exact: yes
- Pending: cards-editor-2-Q4

### Deleting stages cuts on the shelf under their section's name and takes gaps out

{{28-072}}

Nothing is lost by a delete: each cut goes onto the shelf named after the last section heading above it (a note heading or a plain heading does not count); before the first section, or when the section's title cannot be a category name, onto the plain shelf. Shelves are made as needed, at the end of the bench. A deleted gap is simply removed, and undo puts it back.

- Exact: yes
- Pending: cards-editor-2-Q3

### Moving, staging, unstaging and throwing away cuts follow fixed rules

- Stage: cuts leave the cut for a chosen place on the shelf; named gaps are removed.
- Unstage: cuts from any shelf, saved sequence or the alternates section go back into the cut at a place. Refusals: "that cut is already in the cut"; "that staged cut is no longer in the file"; "that is an interviewer question -- questions never go in the cut".
- Move on the bench: within or between shelves. "that cut is in the cut -- stage it first"; "a staged cut moves next to another staged cut". With an anchor, the anchor's shelf decides; with a category, cuts already in it stay put and the rest go to its end.
- Throw away: the only true delete, for cuts on the bench only: "that cut is in the cut -- only a cut on the bench can be thrown away".

### A new cut, a pasted run and a new gap are checked before they go in

A new cut goes to a place in the cut or straight onto a shelf. It must be at least 1/24 s long, cannot run past the known end of its source, and an interviewer question may go only onto a shelf. Paste puts a run of new cuts and gaps in, whole, in its own order, gaps with their notes; "nothing to paste - copy some cuts first"; no question may be in it. A new gap must be at least 1/24 s ("a gap shorter than a frame is no gap -- delete it instead").

Rules for every new cut, and for fixes made in the file by hand:

- "a cut needs the name of its clip" (empty, or with a backtick or a line break); "a clip name cannot start or end with a space"; "a clip name cannot contain a comment";
- the in point is not before 0; "a cut ends after it starts"; "a fade cannot be negative"; fades are cut to the cut's length;
- gain is rounded and held within plus or minus 30 dB;
- a colour is kept as given (Brown becomes Chocolate; empty is none; "a colour cannot contain a comment");
- "a speaker name is one line of plain text (no line break, ** or a backtick)" (trimmed; empty is none);
- "a transcript ref is one line with no [[ or ]]";
- note lines are trimmed and blank end lines dropped;
- highlights are kept only where their words are in the text (a partly matching one keeps the whole words that match).

### Inserting and resizing gaps

{{28-074}}

{{29-021}}

A gap's length, in the cut or in a saved sequence, is at least 1/24 s ("a gap shorter than a frame is no gap -- delete it instead").

- Exact: yes
- Pending: cards-editor-2-Q3

### Fades, gain, clip colour, notes and markers are edits like any other

{{28-075}}

- Fades: either or both fades of a cut can be set; a fade not given is left alone; a negative one is refused; each is cut to the cut's length. Notes "fade in X.X s, fade out X.X s", "the fades are gone".
- Gain: the same value on each named cut (in the cut or on the bench), absolute dB, rounded to 0.1 dB (halves to even) and held within plus or minus 30 dB; 0 removes it; several cuts in one revision; kept through a trim and by both halves of a split. "no cut to set a gain on"; notes "gain +X.X dB on N cuts", "gain reset on N cuts".
- Colour: one of the 16 clip colours, or none (back to the speaker's): "\"X\" is not a clip colour". Brown is written Chocolate. Notes "N cut(s) <colour>", "back to the interviewee's colour".
- Note: empty or blank removes it; each line trimmed, blank end lines dropped.
- Highlights: phrases not found in the cut's words are dropped (a partly matching one is cut to the whole words that match).
- Gap note (in the cut or in a saved sequence): empty removes it; lines trimmed; control characters become spaces; at most 2000 characters ("a gap note is at most 2000 characters").
- Summary (headings only): its text and a short mark of what it was written from ("what a summary was written from is a short hash"); empty removes both; at most 4000 characters; "only a heading carries a summary"; "that section is no longer in this cut list".

- Exact: yes

### The inspector shows and edits the selected cut's edges, gain and fades

{{29-029}}

- Name and search words: the inspector: selected cut, edges, gain, fades, source in.
- Phone and desk: the inspector is on the desk only; on a phone the edit view and the card's own controls do this work.
- Exact: yes

### The edit view trims one cut, with its header, a trim lane and its words

{{29-033}}

{{29-034}}

- Name and search words: the edit view: trim, edges, split bar, play the join, words.
- Phone and desk: on a phone the controls come in thumb order with larger words, as above.
- Exact: yes

### A cut's words always follow its span, on every device

- Whenever an edit changes a cut's clip, in point or out point (in the cut or on the shelf), or adds a cut, the cut's words are taken again from its clip's word timings and its paragraph reference is found again, and every open device and the cut list file agree. This update is not an undo step of its own: undoing a trim moves the span back and the words follow again.
- A word counts when its midpoint is inside the cut; a cut too short to hold any midpoint takes whatever words it touches. This one rule decides, everywhere a cut's words are shown, whether a word at its edge belongs to it. Pause markers "(...)" are removed and spaces collapsed. If no words lie there, the cut keeps the text it has.
- The words are spelled as the transcript spells them, not as the speech-to-text heard them, wherever the transcript's paragraph lines up with the spoken words (letters compared, Simplified and Traditional alike, at least 40 % matching); filler the transcript left out is dropped. Elsewhere the speech-to-text's spelling stays.
- A plain paragraph reference is found again as the paragraph the span overlaps most (at least 0.35 s or 30 % of the paragraph); a reference typed by hand that points somewhere else is never replaced.
- Highlights still inside the new words are kept, fitted to the surviving words; one made meanwhile is not wiped.
- On the page the lane's text for a trimmed cut changes at once, before the confirmed update arrives.
- This happens whether or not the transcript panel is open, for every cut list open on any device.

### Each card's words are read again from the transcript every time a cut list opens

At every open or reload, the words of every cut (and its link into the transcript) are taken afresh from the transcript for its span, so a corrected transcript shows on the cards. The file itself is not rewritten until the next edit. Highlights are refitted onto the new words; a highlight whose words have all gone is dropped.

### Every cut's words can be refreshed at once

The product can take every cut's words again at once and say how many changed; when it cannot reach the open cut list within 10 s it refuses with "the cut list is not open on this server".

- Pending: cards-editor-2-Q7

### A person can start a new, empty cut list in an episode

{{32-023}}

The list of an episode's cut lists names each by its own file name, with a title that differs from it shown muted after it.

- Exact: yes

### A person can duplicate a cut list as it is now

{{32-024}}

- Exact: yes

### A cut list that nobody has open can be renamed, and everything tied to it follows

{{32-025}}

- Exact: yes
- Pending: cards-editor-2-U1

### Rename on the open cut list changes its title instead, on every device, undoably

{{32-026}}

- Exact: yes

### Cut list names follow the same rules everywhere, with a plain refusal for each

{{32-027}}

- Exact: yes

### Making a cut list never overwrites one, and a server that cannot write says so

A name already in use is refused before anything else is done: "<name>.cut.md already exists -- pick another name (nothing here overwrites a cut list)". Two devices making the same name at the same moment get one list and one refusal. Where the server has nowhere it may write cut lists, every attempt to make, copy or rename one is refused with a sentence saying this server cannot write cut lists here.

### A cut list opens as cards with no editing program, and can be opened read-only

A cut list is read, every clip it names is found, and its cuts become cards exactly as a timeline's clips would (words, person, colour, markers, lane and search all work). Nothing needs Resolve. Timeline Cards can also be open with no cut list open.

A person can choose to open a cut list read-only when opening it. Then every change is refused, with a sentence saying that this cut list was opened read-only and nothing here may change it, except handing it to the editing program, which builds a timeline and does not change the file.

- Ways in: from the list of an episode's cut lists, when opening one.
- When the help for the editing program is off: the read-only list offers its exports instead of the hand-over.
- Pending: cards-editor-2-Q8

### Opening, browsing and playing never change a file of the episode

Opening a cut list, browsing it and playing it leave every file in the episode byte for byte as it was, until the editor makes an edit. A row of the file that carries no id is given the same id from the same content every time it is read, so nothing needs writing back on opening. The editor works directly on the episode's own files on the NAS.

### A cut list survives a crash, and damage costs only what came after it

Opening a cut list never trusts luck:

- The first time, the file is the whole truth. A file with a line the editor cannot read is not opened: "the cut list has a line I cannot read: line N: <reason>".
- After that the cut list is rebuilt from its saved history. If the history is damaged part way, the cut list opens at the last good point and every device is told: "the edit history of this cut list was damaged after version N (<reason>); everything up to version N is safe, and the rest is kept aside". An edit cut off mid-save that was never confirmed is quietly dropped.
- A file left half-written by a stop is written again from the history: "the cut list file was being written when the server stopped and holds only part of it; it was written again from the edit history (nothing was lost; the partial copy is kept aside)".
- If nothing can be rebuilt and the file is not the one last written, the cut list is refused with a sentence telling the person how to start again from the file.
- A file claiming more edits than the history holds is treated as an edit made by hand and merged, as below.

Stopping or restarting the server never loses an edit: every open cut list is saved first.

### The cut list file follows the editor within a moment and keeps a backup of its previous version

Within a moment of the last confirmed edit, and when the cut list is put away, the file is rewritten with its edit count and a "written by Timeline Cards" stamp (UTC). The previous version is kept as a backup beside it. If the file changed on disk in a way the editor did not make, that change is merged first, never overwritten ("the file changed while it was being written; merging that first"). A file held open by another program on Windows is still written. A failed write tells every device once: "could not write the cut list file (<reason>); every edit is safe in the edit history and the write will be tried again", and the write is tried again, soon at first and then at most 30 seconds apart. A file deleted while the cut list is open is written again: "the cut list file had gone, so it was written again; nothing was lost". A save is never seen half-written.

### A cut list changed by hand outside Timeline Cards shows on the page within about a second

{{39-040}}

- Exact: yes
- Pending: cards-editor-2-Q5

### The cut list file can be edited by hand, and the editor merges the change

A change made to the file in a text editor is noticed within 2 seconds, when the cut list opens, and before every write. A file still reading the same as the last write is ignored.

- A file that cannot be read is looked at twice more (the person may still be typing); then a copy is kept aside and every device is told: "the file has a line I cannot read: line N: <reason>. A copy is kept aside; the editor's version stands and is written back on the next edit".
- A file that reads is compared with what the editor last wrote and turned into edits applied on top of the current cut list, then rewritten keeping the person's formatting where possible. Rows are matched by their ids; a row whose id line was deleted is matched back (cuts by clip and span: exact, one inside the other, then overlapping, ties to the nearest in order; headings, note rows, bench sections and gaps by kind and words, gaps by length). Only then is a row new.
- What a hand edit can change: the title, clip facts, the timeline's name and the hand-over stamps; new cuts, headings, note rows and bench sections; a clip name, speaker or link fixed by hand; removed headings and sections; the order (merged so only what the file moved moves); each cut's edges, fades, gain, colour, note and highlights; each gap's length and note; each heading's summary.
- A cut bullet removed from the cut goes to a shelf, never lost; one removed from the bench is really removed. A cut whose new span cannot be reached by moving its edges is replaced whole.
- Ignored and written back as they were: a cut's words, its "(12.4s)" length and its transcript link text; the episode, root, board, rate, drop-frame, start and timing facts at the top ("the frontmatter's X was edited; no edit can change it, so it is kept as it was").
- The person is told "merged an edit made to the file outside the editor (N change(s))"; or "the file was edited outside the editor, but nothing in the edit changes the cut (the words are written from the transcript), so it was written back as it was"; plus "K of the file's changes no longer apply and were skipped: <up to 5 reasons>" and up to 5 warnings. A merge that could not be saved is tried again at the next look; the same file after a crash gives the same edits, which can never apply twice.
- An edit an editor made against the copy the hand edit replaced is refused with its sentence where it clashes with the hand edit, never merged silently.

- Pending: cards-editor-2-Q5
- Pending: cards-editor-2-Q6
- Pending: cards-editor-2-Q1

### A cut list holds the cut, the bench and the timeline's facts

A cut list has the timeline's facts, an optional title, the cut's rows in order, then the bench sections in order, and any extra data a part of the editor keeps with it.

- Rows in the cut: a cut, a gap, a heading, or a note row.
- A cut is one piece of a source: the clip's name exactly as written (that name is the clip's identity, never an editing program's own id), the speaker or none (a montage clip), in and out in source seconds (in always before out), a fade in and a fade out (each no longer than the cut; they may overlap), a gain of its own in dB (0.1 dB steps, within plus or minus 30, on top of levelling), a clip colour or none (the speaker's colour), a link into the transcript or none, its words (kept fresh from the transcript, never cut up by an edit), its highlighted phrases in order, and a free note of one or more lines. A cut can be marked as an interviewer's question: a question can never be in the cut (the house rule "no questions included in the edit ever"), only on the bench, and the mark is not kept in the file.
- A gap is black and silence of a set length (more than 0) with an optional note. It is its own row: it stays where it was put when a neighbour moves or is deleted, and is selected, moved, resized, deleted and copied like a cut.
- A heading is a section (default colour Blue), a note heading (default colour Green) or a plain heading (no colour); it has a title, a marker colour, and optionally a summary of its section written by the assistant, with a mark of the words it was written from, so a changed section can read "out of date".
- A note row is a direction card or an "unmatched" line, one line of text (it may be empty).
- The bench, always after the cut: shelves (each named by its category; the unnamed one is the plain shelf; holding cuts, note rows and gaps), saved sequences (a run kept whole with its gaps and note rows), and the alternates section, kept as it is. Each has a name, its title as read, and a colour.
- Timeline facts: the edit count, when and by what it was written, the episode, the episode's root folder, the planning board it came from, the Resolve timeline's name, when it was handed over and when it was last updated from the timeline, the timeline rate (default 29.97), drop-frame (default on for a new list), the start timecode (default 01:00:00:00), whether the text was timed by words or by subtitle cues, and per clip its rate, start timecode and Resolve id (hints for exports only).
- Times are seconds, never frames; frames appear only in exports. Every edit rounds what it writes to 6 decimal places; a time beyond 1,000,000,000 seconds is refused ("X is past 1 000 000 000 seconds -- no clip is that long").
- Limits: the shortest cut or gap an edit may leave is 1/24 s (a file may hold a shorter cut, such as one 29.97 frame); category and sequence names at most 60 characters; gap notes at most 2000 characters; summaries at most 4000.
- A new cut list is empty, edit count 0, 29.97 drop-frame, starting 01:00:00:00, timed by words.
- The timeline is worked out from the cut, never stored: each cut and gap starts where the ones before it end, so every trim ripples; each knows the heading it sits under; the total length follows.
- Every cut, gap, heading, note row and bench section has a permanent id written in the file and is never matched by name, time or position; a row arriving without one gets the same id from the same content every time.
- A cut list longer than 16 MiB is refused as too large.

- Pending: cards-editor-2-Q3
- When the assistant is off: no section summary is written; summaries already in the file are kept and shown.

### Facts the editing program knows about a clip win over what the cut list recorded

When Resolve's project knows a clip's real frame rate and start timecode, those are used instead of the values written in the cut list. The person named on a cut sets that clip's interviewee and colour.

- When the help for the editing program is off: the frame rate and start timecode written in the cut list, or read from the clip itself, are used.

### The shelf, its categories and saved sequences live in the cut list file itself

{{33-015}}

Cuts set aside on the shelf stay in the cut list but never reach the editing program.

- Exact: yes

### The cut list file is one readable, hand-editable Markdown file per cut list, in a fixed order of parts

A UTF-8 Markdown file at `<Episode>/Script Docs/Cuts/<name>.cut.md`, meant to be read and edited by hand in a text editor.

- In order: the frontmatter block; a comment preamble; an optional `# Title`; the cut's rows (headings, cut bullets, gap bullets, note bullets) in order; then the bench sections, each a `##` heading followed by its items.
- Line endings `\r\n`, `\r` and `\n` are all read. The writer keeps the file's dominant ending.
- Blank lines anywhere in the body are ignored on read. The canonical writer puts one blank line between blocks and ends the file with exactly one newline.
- Reading never fails: a line that cannot be accepted is recorded as a **problem** (1-based line number and a sentence) and kept as an opaque line that is written back as it was. A never-opened file with a problem is refused; an outside edit with one is set aside (see "A cut list survives a crash" and "The cut list file can be edited by hand"). Non-fatal oddities are **warnings**. A strict reading that stops at the first problem is available to tools.
- A cut list is named by its path relative to the episode root, forward slashes, ending `.cut.md`.

{{39-059}}

- Exact: yes
- Pending: cards-editor-2-Q1

### The frontmatter block carries the timeline's facts in a fixed canonical form

- **Must** start on line 1 with `---` and end with a line `---`. Otherwise problems: line 1 "a cut list starts with a --- frontmatter block"; "the frontmatter is never closed".
- **Written in this order** (canonical form):
  - `---`
  - `kind: timeline-cards/cut-list`
  - `rev: <whole number>`: the edit count the file encodes.
  - `written: <stamp>`: `YYYY-MM-DDTHH:MM:SS+0000 by Timeline Cards` (UTC) when the editor writes.
  - `project: <text>`, `vault_root: <text>`, `canvas: <text>`, `timeline: <text>`: written even when empty (as `key:` with nothing after).
  - `conformed: <text>` and `updated_from_timeline: <text>`: only when set.
  - `fps: <rate>`: `25.0` for a whole rate, else up to 8 decimal places with trailing zeros removed (`29.97002997`).
  - `drop: true` or `drop: false`.
  - `tl_start: <timecode>`
  - `timing: word` or `timing: srt`
  - `x-<name>: "<json>"` lines (extra data, below), sorted by name.
  - `clips:` then one indented line per clip (below).
  - `---`
- **Value quoting** (writer): none is written as nothing; an empty string as `""`; a value is double-quoted (with `\` and `"` escaped) when it has leading or trailing whitespace, starts with a double quote, single quote, `[`, `{`, `>`, `|`, `&`, `*`, `#`, `!`, `%`, `@`, a backtick, `-` or `?`, contains `:` or `#`, or looks like a number; otherwise bare.
- **Reading values**: empty is none; a value in matching single or double quotes is the inside with `\"` and `\\` unescaped; bare `true` / `false` are booleans (written back as `true` / `false`); anything else verbatim.
- **Reading rules per key**:
  - `kind`: if present and not `timeline-cards/cut-list`: problem "this is a 'X' file, not timeline-cards/cut-list".
  - `rev`: a whole number (Unicode digits, `_` separators and a sign accepted), else problem "rev is not a whole number: 'X'". Absent: 0. Negative counts as 0.
  - `fps`: a number (including exponents, `inf`, `nan`), else problem "fps is not a number: 'X'". Snapped to the exact rate (within 0.01 of 23.976, 29.97, 47.952 or 59.94 it IS that rate; else the nearest fraction with denominator at most 1001). Absent: 30000/1001.
  - `drop`: true when `true` or any non-empty text (even `0`); false when `false` or empty.
  - `tl_start`: absent means `01:00:00:00`.
  - `timing`: `word` or `srt`; anything else is a problem ("timing is 'word' or 'srt', not 'X'"); absent means `word`.
  - `conformed`, `updated_from_timeline`: empty means none.
  - The same key twice: the last one counts; the earlier lines are kept as written.
  - A line with no `:`: problem "'X' is not a frontmatter key".
  - An unknown key: warning "unknown frontmatter key 'X' kept as written"; kept on write.
  - Blank lines are allowed.
- Meaning: `rev` the edit count; `written` the last writer's stamp; `project` the episode; `vault_root` the episode root; `canvas` the planning board it came from; `timeline` the Resolve timeline's name; `conformed` when it was handed over; `updated_from_timeline` when Resolve's changes were last brought back; `fps`, `drop`, `tl_start` the timeline's rate, drop-frame and start; `timing` whether the words were placed by word timing or matched from subtitle cues.
- `written` reads like "<time> by Timeline Cards" (or "(new, empty)", "(new from canvas)", "by [the tool that brings cut lists in line with the montage sources]"); `conformed` reads "<time> via <how>"; `updated_from_timeline` reads "<time> from <timeline>". The `clips:` lines are sorted by name, `Name: {fps: .., start_tc: "..", uid: ..}`; the uid is a hint only, and handing over always finds the clip again by name.

- Exact: yes
- Pending: cards-editor-2-Q1

### Clip lines and extra-data lines in the frontmatter

{{34-044}}

- Exact: yes

### The comment preamble and the title

{{34-045}}

- Exact: yes

### Headings: how each kind is written and recognised

{{34-046}}

{{39-061}}

- Exact: yes

### Bullets: cut lines, gap lines and note rows

{{34-047}}

{{39-062}}

- Exact: yes

### Lines under a cut: fade, gain, note, transcript link and words

{{34-048}}

- Exact: yes
- Pending: cards-editor-2-Q1

### Comments, id lines, gap notes and section summaries

- Any line whose trimmed text starts `<!--` is a comment. One without `-->` on the same line runs until a line containing `-->`; everything inside is skipped.
- **Id line** `<!-- id: <letter><7 characters> -->` (any spacing): the letter is `c` cut, `g` gap, `s` heading or bench section, `n` note row, and the 7 characters are from `0-9a-z`. It attaches to the row directly above it when the letter matches that row's kind and the row has no id yet. Otherwise warning "line N: an id line that belongs to no row above it is kept as a comment".
- An id used twice in the file: the second row gets a new id, warning "line N: id X is used twice; this row is given a new one".
- A row with no id line gets a deterministic id: its kind letter plus 7 characters worked out from its kind, its content (cut: clip, in and out to 6 places; gap: length; heading or bench section: kind and title; note row: kind and text) and how many times that content has occurred, counted up until unused. The same bytes always get the same ids. Ids are never matched back by name, time or position.
- **Gap note lines** `<!-- note: <text> -->` directly under a gap (after its id line, before any other non-comment line). **Summary lines** `<!-- summary: <text> -->` or `<!-- summary [<hash>]: <text> -->` directly under an in-cut heading; the first hash given wins; the hash is 1 to 32 characters of `0-9a-z`. A note line under a heading, a summary under a gap, or a `note [hash]` form is just a comment.
  - Escapes inside these lines: `\` is written `\\`; the `>` of `-->` or `--!>` is written `\>`. A lone backslash in a hand edit is kept.
  - Read text is normalised as an edit would (lines trimmed, control characters become spaces, broken surrogate characters become U+FFFD, blank end lines dropped); a gap note over 2000 characters or a summary over 4000 is cut there with a warning ("a gap note is longer than 2000 characters; the rest is not read").
- Every other comment is ignored by the reader, and kept by the preserving writer (below).

- Exact: yes

### The writer gives the same text for the same cut list, and a hand-formatted file keeps its formatting

{{34-050}}

- Exact: yes

### Numbers and white space in the file follow fixed rules so a file reads and writes back identically

{{34-051}}

- Exact: yes

### Colours, forgiving reading, loud errors and tidy writing

- Colours are Resolve's clip colour names. "Brown" is never written: it is written as "Chocolate". A colour from a planning board is mapped to the nearest Resolve clip colour.
- Reading forgives extra blank lines, a missing quote, a missing length, either kind of line ending, comments over several lines, transcript names containing square brackets, and a fade line under a note.
- Reading is loud, always with a line number, about: no header ("a cut list starts with a --- frontmatter block"), an unclosed header, a bad header line, a clip entry without `{...}` or without fps, a file of another kind ("this is a '<x>' file, not timeline-cards/cut-list"), a bad timing value, an unreadable bullet ("cannot read this bullet: ..."), a line that is not a bullet, heading or blank, and a negative fade ("a fade in cannot be -1.0 seconds long").
- Gain read from the file is rounded to 0.1 dB and limited to plus or minus 30 dB (a typed -40 becomes -30); unit and sign are optional when read.
- Only balanced `==...==` pairs are highlights; a lone `==` is kept as typed. Each highlight is written on its first free occurrence at or after the previous one, so repeated phrases come back the same; a highlight no longer in the text is dropped. When words change, each highlight is refitted as the longest run of letters and digits it shares with the new words (ignoring case); under 2 matching characters it is dropped.
- The same cut list always gives the same bytes, with LF line endings, and a save is never seen half-written.
- Before each save the previous version is kept in the cut list's history. The newest 200 revisions are kept; older ones survive only if their revision number is a multiple of 10.

- Exact: yes

#### Lessons

- Met: CE1-062, CE3-021, CE3-023, CE3-031, CE3-033, CE3-034, CE1-063, CE1-064, CE1-065, CE1-066, CE3-022, CE3-024, CE3-025, CE3-026, CE3-027, CE3-029, CE3-035, CE3-036.
- Not yet met by any behaviour above: CE3-032 (the shelf staying out of the editing program is written here; switching panel tabs with Alt and a digit belongs with the page's panels in part 5), CE1-067 (staged edits waiting for the editing program belong with the hand-over to Resolve), CE3-028 (the same: staged edits and markers waiting for the editing program), CE3-030 (a highlighted stretch of transcript becoming a card is written with the transcript panel in part 3).

## Notes and the staged shelf

### A note can be written under any cut

{{29-025}}

A note on a card or a gap shows beneath it on yellow, and its clip on the lane carries a yellow square in its top right corner. The note box, like every editor a gesture opens, appears inside its card at the card's full text width, in every density and on a phone, and takes the first keystroke.

- Exact: yes

### A note on a card or a gap is kept in the cut list as an edit like any other

A note on a card goes into the cut list under that cut (trimmed; empty removes it), applied in turn like any edit, with the note "note on a cut"; while another edit is running: "an edit is already being applied -- wait a moment". A note on a gap is kept in the cut list under its gap, and travels with the gap into Resolve.

Every note lives in the cut list as an ordinary undoable edit that reaches every device. Notes the studio kept in side files beside earlier cut lists are brought into their cut lists once, when the studio's existing work is carried over.

- Exact: yes

### Notes on cards and gaps while a cut is worked on a live timeline

Where a cut is being worked on a live timeline in the editing program (see Timeline Cards: the hand-over to Resolve, and exports: Edits sent live and staged edits), these rules hold for notes:

{{40-018}}

- When the help for the editing program is off: there is no live timeline; notes are only the cut list's own.
- Exact: yes

### Phrases on a card or a shelf card can be highlighted, and must be the card's own words

{{39-051}}

- Exact: yes

### A gap can carry a short note saying what the black is for

{{33-035}}

- Exact: yes

### A gap card shows its note, or a button to add one

{{33-036}}

- Exact: yes

### The gap note is written in an inline editor on the gap card

{{33-037}}

- Exact: yes

### A Gap notes panel lists every gap of the cut with its note

{{33-041}}

- Name and search words: Gap notes: gap notes, black, silence, b-roll note.
- Phone and desk: on screens 700 px wide or narrower the panel is a bottom sheet; on a landscape phone its button is an icon only.
- Exact: yes

### The shelf panel shows cuts set aside from the cut, in two tabs, Staged and Sequences

{{33-001}}

- Name and search words: the staged shelf: staged, shelf, set aside, sequences, categories.
- Phone and desk: a rail on the desk, the shelf tab on a phone.
- Exact: yes

### On the desk, the shelf can take the rail's whole height or share it with the section list

{{33-002}}

- Exact: yes

### The staged shelf keeps cards to hand, per section, ready to place

{{29-031}}

- Exact: yes

### Category chips filter the Staged tab

{{33-003}}

- Exact: yes

### A shelf category for interviewer questions is locked, for reference only

{{33-004}}

- Exact: yes

### Each staged card shows its words, speaker, duration and category, and can be selected

{{33-005}}

- Exact: yes

### The inspector also shows a selected gap and a selected staged card

{{29-030}}

- Exact: yes

### Place puts a staged card back into the cut

**Place** (or "Place in the cut" in the card's menu) takes the card off the shelf and puts it into the cut: right after the focused cut if one is focused, otherwise by the playhead rule of "Put back at the playhead" (below). The placed cut becomes the selection. Toast "Placed <speaker> in the cut." with Undo. Refused for locked cards (interviewer questions, above). One undoable edit, sent to every device on the same cut list.

- Exact: yes

### Staging without deleting, and putting shelf items back on the timeline

{{28-073}}

- Ways in: the Stage buttons (on a card, in the inspector, in the edit view), dragging a card onto the shelf, and the shelf's Place.
- Exact: yes

### A staged card can be listened to off the timeline, from its start or from any word

{{33-007}}

- Exact: yes

### A staged card has a menu, by right-click on the desk or a long press on touch

{{33-008}}

- Exact: yes

### On the desk, a staged card is filed by dragging it onto a chip

An unlocked staged card can be dragged with the mouse onto a category chip (not a locked one); the chip highlights, and dropping files the card there (as filing from the card's menu does).

- Exact: yes

### A card of the cut is staged by dragging it onto the shelf

{{33-011}}

A card dropped on the shelf lands in the category being viewed, at the slot the insertion line showed, and is scrolled into view. While dragging, every drop target stays reachable and still, the wheel and the panel's edge scroll the panel under the pointer, and a target stays lit while the pointer is anywhere inside it, over its own children included, until the drop. After any drop the page takes updates again at once, even when the dragged card is gone from the page.

- Exact: yes

### The Stage buttons stage the selection onto the shelf, and the shelf turns to show it

{{33-012}}

- Exact: yes

### Stage to files the selected cuts onto a chosen shelf category

{{33-023}}

- Exact: yes

### The categories overlay lists every shelf category and lets each be renamed or removed

{{33-013}}

- Name and search words: categories: staged categories, shelf categories, file under, U key.
- Exact: yes

### The name dialogs for categories and sequences

{{33-014}}

- Exact: yes

### Cards are put on the shelf, taken back, moved within it and filed under categories

{{39-044}}

A new empty category has a cleaned name (one line; leading spaces, colons, slashes, bars, dashes and middle dots removed). Refusals: "a category name cannot contain a comment or a #"; "a category name is a heading, not a paragraph" (over 60 characters); "a category needs a name"; "that category already exists"; on rename, "there is already a category called \"X\"". Removing a category moves its items to the plain shelf, never deleting them ("no category called \"X\""; "which category? none was named"). Categories keep the order they have in the cut list, never alphabetical, and a staged card sits in exactly one of them; the All chip lists every staged card, and every device sees the same categories.

- Exact: yes

### Everything set aside is listed beside the cut

Every cut on the shelf, in a shelf category or among the alternates is listed and never dropped, with its clip, span, person, words, English, colour, length and category. Categories are listed in the order they appear in the cut list, empty ones included. Each saved sequence is listed whole: its cuts (with the black before each, fades and gain and English), how many, its total length, and its note lines.

### The Sequences tab lists every saved sequence with a preview of its cuts

{{33-016}}

- Exact: yes

### Save as sequence takes an unbroken run out of the cut and keeps it whole

{{33-020}}

Saving takes the stretch from the first to the last named item out of the cut as a saved sequence. Every cut in the stretch must be named ("a sequence is a run of cuts next to each other - select one unbroken stretch"); gaps and note rows inside it travel with it; headings inside it stay in the cut; at least one cut is needed ("a sequence needs at least one cut"); a gap just before the first cut goes only if it is named. Names follow the category rules; "there is already a sequence called \"X\"". A run is stored and restored with every span, fade, colour, note and the black before it exact.

- Exact: yes

### A run of cuts is saved as a sequence, set aside whole, and brought back whole

{{39-045}}

Restoring puts the sequence back whole at a place (gaps and note rows as saved) and removes the saved sequence; "the sequence \"X\" has no cuts in it"; no interviewer question may go in; "no saved sequence called \"X\"". A sequence can be renamed, or deleted with everything in it.

- Exact: yes

### Play the run plays a saved sequence, black included, off the timeline

**Play the run** plays every cut of the sequence in order with the black between them, off the timeline, in the same way as listening to a staged card (above). An empty sequence warns "That sequence has no cuts to play." Any timeline playback stops it.

- Exact: yes

### Put back at the playhead returns a whole saved sequence into the cut

One edit puts the whole run back into the cut; the run becomes the selection. Placement: if the head is in black before an item, in front of that item; if inside an item, before it when the head is in the item's first half, otherwise after it; past the end, after the last item; in an empty cut, at the end. Toast "The sequence “<name>” is back in the cut." The same playhead rule places a staged card when no cut is focused (see Place).

- Exact: yes

### A saved sequence can be dragged back into the cut, onto the cards or the lane

{{33-019}}

- Exact: yes

#### Lessons

- Met: CE1-060, CE1-061, CE1-050, CE1-051, CE1-055, CE1-057, CE1-058, CE1-052, CE1-054, CE1-056, CE1-059.
- Not yet met by any behaviour above: CE1-053 (deleting and dragging note and section rows in place is written with sections in part 1).

## Playback and audio

### Space plays and pauses with a tap, and plays at double speed while held

{{28-003}}

Space plays with sound from the exact point the head is on, mid-clip included, and never makes the head jump.

- Exact: yes

### K pauses, L plays, J jumps two seconds back

{{28-004}}

- Exact: yes

### Home, End and the edit-point keys jump the head

{{28-006}}

- Exact: yes

### Play, pause and what stops playback from starting

{{28-065}}

The head and the selection move only by the editor's own actions: a second window or a game controller on the same episode never fights them.

- Phone and desk: on an Android phone, inside the studio's app, other apps' music is lowered rather than stopped while the editor plays, and comes back about 1.5 s after playback stops and whenever the app is paused; in a plain browser nothing happens to other sound.
- Exact: yes

### Moving the head while stopped is heard, rates run from 0.25x to 4x, and sound problems are reported

A head dragged while stopped plays the audio under it as it moves (see the next heading); a head set by a click is silent. An edge being dragged is heard at the edge, as a temporary head. The playback rate runs from 0.25x to 4x; where rate control is not available, playback runs at 1x; after a reload it starts at 1x. Sound problems are shown as notices: "playback is not available: <reason>" (once, when the sound for the cut list fails to load), "playback: <reason>" (an error during playback), "could not play: <reason>" (a play that failed; playback shows stopped). A play still loading when the editor paused is stopped when it starts.

- Exact: yes

### Dragging the head, jogging or dragging a trim edge plays the sound under it

While the head, a controller stick's jog or an F8 hold moves the head, or a trim edge is dragged, and playback is paused, the audio under the head is played at the speed and in the direction it moves, forwards and backwards, with the voice at its natural pitch, so slow and reverse scrubbing still sound like the words. It plays at that cut's level and fade; a dragged trim edge is heard at the clip's level without fades. Holding still is silent and a gap is silent. Ending a scrub, or ending playback, silences every sound it started, whichever clip the head is on by then. Scrubbing is heard from the light listening copies and never floods the server: only the newest position is ever asked for, and the final position is always heard.

### Playback speed goes from a quarter to four times, keeping pitch

At every rate from 0.25x to 4x other than 1x the speaker keeps their pitch (best between 1.25x and 3x; 0.5x acceptable). A rate change while playing keeps the old rate sounding until the new rate is ready (at most 4 seconds), then crossfades, so 2x never starts with a hole.

### The cards list scrolls itself sensibly, and F follows or finds the card being heard

{{29-022}}

With follow on, the card being heard stays centred in the part of the cards area the lane and the panels do not cover, and scrolling by hand never turns follow off.

- Exact: yes

### The transport plays, steps cuts, shows timecode and zooms the lane

{{29-036}}

- Phone and desk: the transport sits in the lane's bar on the desk; a phone has a play bar instead, as above.
- Exact: yes

### Shift+P records a place in the cut and P jumps between recorded places

{{29-040}}

- Exact: yes

### The transcript plays its own audio, at the lane's levels, and Space decides what to play in a fixed order

{{30-018}}

Selecting transcript text lets the editor hear exactly that passage, from the product's own audio, without the editing program and without leaving the page. Audio heard from the transcript gets the same level lift, master volume and limiting as the same moment on the lane. The transcript player never fades.

- Exact: yes

### Alt+Shift with the arrows, Page keys and 0 change a cut's gain

{{28-016}}

- Exact: yes

### The gain dialog sets a cut's loudness on top of the automatic levelling

{{33-030}}

A cut's own gain is kept through a split, a trim, a move, a copy and an undo, and is shown on its clip.

- Exact: yes

### Preview sound brings every interviewee to the same loudness, or plays each clip at its own level

Row 5: **Same loudness** (default) / **Own level** turns the automatic levelling (below) on or off. Announced "Same loudness: every interviewee at the same level" / "Each clip at its own level". With it off, lane waveforms are drawn without levelling too. A status line: with levelling on, "Every interviewee is brought to the same speech level, the middle of what this episode’s own clips measure, so the loud ones come down and the quiet ones come up, with a limiter after it so nothing distorts."; off, "Each clip plays at its own level, with only its own gain."; plus " The whole preview is louder/quieter by N dB." and always " Only the preview: no file is touched." Without a player: "Playback is not available in this window, so there is nothing to level or turn up. The setting is kept for when it is." If the player cannot level: "This window’s player cannot level the clips, so each one plays at its own level." Only the preview changes; no cut, gain or file changes.

- Setting: Preview loudness. Does: brings every interviewee to the same speech loudness in the preview, or plays each clip at its own level. Default: Same loudness. Who: anyone using the editor. Applies to: a computer. Search words: same loudness, own level, levelling, loudness, preview sound.
- Exact: yes

### A preview volume slider turns the whole preview up or down

{{33-066}}

- Setting: Preview volume. Does: turns the whole preview up or down, without touching any cut or file. Default: 0 dB. Who: anyone using the editor. Applies to: a computer. Search words: volume, louder, quieter, preview volume, master.
- Exact: yes

### A master volume and a limiter keep the preview from clipping

The whole preview's volume can go from -24 to +12 dB (the View sheet offers -12 to +12); changes glide over about 15 ms while playing so they never click. A limiter sits after it: anything above -2 dBFS is held down hard (20:1, 3 ms attack, 250 ms release), and levels below -2 dBFS are left exactly as they are, with no make-up gain added.

### Automatic levelling brings every interviewee to the same speech level

On by default (Same loudness). Each clip's loudness is measured once, second by second over a 3-second window by the broadcast loudness standard, counting only speech: stretches more than 10 dB quieter than the clip's average, pauses and room tone are ignored, so a door slam or a long silence does not set it, and anything at or below -120 LUFS counts as silence. The target is the middle (median) of the speech levels of the clips the cut uses; clips only on the shelf and clips of other cut lists never count, and a clip not in the cut never moves the target. Loud clips come down, quiet ones come up, with the limiter after it so a raised clip never distorts.

Each cut is levelled by the speech within 2 minutes either side of its middle (judged in 5-second steps), never more than 18 dB from the clip's whole level; a clip with under 20 seconds measured uses its whole level. The levelling gain is constant across a cut and stays between 0.05x and 8x (-26 dB to +18 dB). A person's own gain on the cut is added on top, the total held within plus or minus 30 dB. Every other player in the editor (the transcript, a staged card, a saved sequence) uses the same level for any clip and moment, so it sounds like the lane.

A recording channel that never peaks above -30 dB counts as dead: the live channel's speech is played in both ears rather than in one.

The levelling is only for listening: no media file is ever changed by it.

- Pending: cards-editor-2-Q10

### Playback runs through gaps as silence, and joins never click

The cut plays in order; a gap plays as silence with the clock running through it. Cuts on the shelf are not played by the main playback. Across any join the next cut sounds the instant the previous one ends, and during playback the head only moves forward. Every cut boundary gets a 4 millisecond fade, and a start or seek in the middle of a cut ramps in over the same 4 ms: at 1x and 2x, and over several joins in a row, no click is louder than the audio around it, and a join is never timed from a coarse reading of the audio's position.

### Fades and a cut's gain are heard as drawn, live while being dragged

A cut's fade-in and fade-out are straight-line in gain and never longer than the cut; where they overlap on a short cut they multiply. Each fade is heard as drawn at every rate, while playing and while scrubbing, with no click. Changes to fades and gain while dragging are heard at once, gliding rather than jumping. Fades, joins and levels keep their timing when the tab is in the background, a level changed in the middle of a fade is honoured, and pausing in the middle of a fade makes no pop. There are no picture fades. A cut's loudness is its automatic level (when Same loudness is on) plus its own gain, the total held within plus or minus 30 dB.

### Pressing play starts quickly and the head on screen matches what is heard

Playing at the end of the cut starts over from 0. Before sound starts, the first 1.5 seconds after the head (up to the next 4 cuts) are fetched, waiting at most 4 seconds before starting anyway; a pause while waiting cancels the play. On phones the play never waits more than 1 second for the sound device. The head moves the instant Play is pressed, after any seek, and eases into exact step with what is heard (allowing for the output device's delay, for example Bluetooth) over 0.5 seconds, never jumping backwards; between readings of the audio clock it moves smoothly at the play rate. While paused, once the head has rested 40 ms in a new spot, the audio there is fetched in advance so the next play starts quickly. A late stretch of audio starts as soon as it lands, ramped in, rather than holding the head still. A position asked for before a clip's audio is ready is kept and applied once it loads, and the newest request always wins.

### The first Play is never delayed by a sleeping sound device

While the editor is visible, it keeps the computer's sound output awake with an inaudible signal, and wakes the sound device on the first click or key anywhere, so the first Play after a pause sounds at once. This stops while the page is hidden.

### Seeking or editing while playing does not stop the sound

A seek while playing continues from the new place without a silence longer than 2 seconds. An edit while playing continues the sound from the same moment of the same clip; cuts that only slid along are not interrupted. While paused, an edit keeps the head on the same moment of the same cut (or gap), held inside it; if that cut is gone, it keeps its time on the timeline.

### A clip whose audio is missing or cannot be levelled still plays, and the editor is told

A clip with no audio plays silent, with one warning shown to the editor: "no audio for <clip>: it plays silent". A stretch of audio that fails warns once: "audio for <clip> at <s> s failed: <reason>". A clip whose levels cannot be read warns once, "no levelling for <clip>: <reason>", and plays at its own level. Playing with nothing loaded is refused ("no project loaded"). When an episode's audio, word timings or English are missing, the editor names which, and never shows an empty player, plays silence in their place or puts substitute English on a card. A slow first load of a cut list's audio shows that it is loading and keeps trying, also when Play is pressed, and never stays stuck on an error that has since cleared; only when the cut list truly has no audio at all is it an error ("the project has no audio sources"). A play cut short by the editor's own pause or a reload is never shown as an error.

### The video window shows the picture of the clip under the playhead, switched on and off from the toolbar or Shift+V

{{32-037}}

- Name and search words: the video window: video, picture, proxy, Shift V.
- Exact: yes
- Pending: cards-editor-2-Q9

### The video panel can be sized, moved and resized, and says why there is no picture

- Bar: a move grip (desktop only), "Video", the speaker or clip name under the head (tooltip: the clip), the source time `m:ss.t` (or `h:mm:ss.t`), and buttons "Window size" (cycles small, medium, large), "Open in its own window" (only when the browser can let windows talk to each other), "Close the video window".
- A black 16:9 stage; when there is no picture, a centred sentence on a faint hatched background:
  - "Asking the server for this cut list’s video proxies…" before the first answer.
  - "No cut under the head." (a gap or past the end).
  - "The video proxy would not play." (that clip is not tried again until the window reopens).
  - "Making the video proxy… <done> of <total>" or "Waiting for the server to make the video proxy… <done> of <total>".
  - "No video for this clip: its media is sound only." / "...its media file was not found." / "...the file has no video track." / "No video for this clip: <reason>".
  - "Open a cut list: the window shows the clip under the head." when no list is open.
- Sizes: small 240 px, medium 360 px (default), large 560 px wide; remembered.
- Free resize from the bottom-right corner: width follows the pointer, height keeps 16:9; 200 to 1280 px and never wider than the window less 16 px; remembered. Keyboard on the corner handle: Right/Up grow 20 px, Left/Down shrink 20 px, 80 px with Shift. Choosing a size clears the free width.
- Drag by the bar (not its buttons) to move; the panel is always kept inside the window; the spot is remembered and kept inside on the next open and on every window resize. Keyboard on the grip: arrows move 16 px, 64 px with Shift.
- Default place: top right under the header. On a phone (700 px or narrower) it starts top right, at most two thirds of the screen wide, with no pop-out button. On touch screens the bar, grip, resize handle and buttons are 44 px.
- A small panel hides the clip name below 330 px wide and the time below 290 px.

A cut from a multicam shows the picture of the angle in use at that moment, taken from that angle's own media.

- Phone and desk: on a phone the window starts smaller and has no pop-out, as above.
- Exact: yes
- Pending: cards-editor-2-Q9

### The video picture stays on the sound, while playing, scrubbing and across joins

The picture follows the editor's playhead and playback speed (including varispeed, from one sixteenth to sixteen times). During playback it stays within three frames of the sound, on the local network and over a slow remote link. Paused, it shows the head's source frame; while scrubbing it jumps at most ten times a second and always lands on the final scrub position. Playing, a picture within 0.035 s of the sound is left alone; up to 0.3 s off it is gently sped up or slowed (by up to 8%) until it catches up; further off it jumps, aiming ahead by how long jumps have been taking (up to 2 s) so a slow network still lands on time. When Play is pressed the picture holds on the head's frame until the sound actually starts (at most 2 s). Past the end of the picture (the camera stopped before the sound) the last picture holds. The next cut is made ready up to 1.5 s before the join so the picture changes on the join; a following cut that continues the same clip exactly carries straight on. A clip whose picture becomes ready while the window is open shows at once, and a change of the cut list's clips is noticed at once.

### The video window can be moved into its own browser window

{{32-040}}

- Exact: yes
- Pending: cards-editor-2-Q9

#### Lessons

- Met: CE1-077, CE1-078, CE2-045, CE2-046, CE2-047, CE2-048, CE2-049, CE2-050, CE2-051, CE2-057, CE3-038, CE3-039, CE3-040, CE1-084, CE1-085, CE1-087, CE1-088, CE1-091, CE1-093, CE2-058, CE2-059, CE3-041, CE1-079, CE1-080, CE1-081, CE1-082, CE1-083, CE1-094, CE2-052, CE2-053, CE2-055, CE3-042, CE3-043, CE3-044, CE3-045, CE3-046, CE3-047.
- Not yet met by any behaviour above: CE1-089 (the lane drawing every frame in a few milliseconds belongs with speed and smoothness in part 5), CE1-092 (the mark on the clip and card under the playhead is written with the lane and the cards in part 1), CE2-054 (the lit word is written with the lane in part 1), CE2-056 (the phone's scrub pad belongs with the phone and game controller in part 5), CE2-061 (the join check is written with the English a cut shows in part 3), CE1-090 (the lane paging along with a playing head is written with the lane in part 1).

## Media the browser gets

### A Video tab shows the interview under the playhead, in step with the sound

- A dockable desk panel showing a small preview of the interview under the playhead, lined up with the clip's sound. It is not on phones.
- Always muted (the sound comes from playback). No picture-in-picture.
- It only runs while its tab is visible; otherwise nothing plays or decodes.
- Playing: it follows the playhead's speed (between 0.2x and 4.5x) and is pulled back when it drifts more than three frames from the sound. Paused: it shows the frame under the playhead.
- In a gap: "A gap: nothing plays here." A clip with no preview: "No preview video for this interview yet." followed by why there is none and when there will be one, in plain words (remembered for that clip for the session).
- When the cut list is kept on the device, the kept preview plays instead; one that will not play falls back to the server for that clip.
- **Zoom**: the wheel zooms at the pointer (faster with Ctrl, as a trackpad pinch), from 100% to 800%; buttons "−", "100%" (fit), "+" step ×1.5; double-click fits; drag pans while zoomed; the picture always fills the frame. The zoom buttons show on hover, while zoomed, or when focused.

- Name and search words: the Video tab: video, preview, picture, interview video.
- Phone and desk: desk only; a phone uses the video window.
- Exact: yes

### Every clip is made ready to play without anyone asking

Each clip's small playback copies (its light sound, its small picture and its waveform) are made by themselves when the clip arrives in the episode, and for any clip still without them when a cut list is opened, before anyone plays or downloads it. Every clip whose media exists plays and shows its waveform with no export step and nothing for a person to start. While copies are still being made, the editor shows progress clip by clip. Sound is always made ready before pictures. Playing a clip that is not ready yet moves its preparation to the front, rather than starting more work at once; making copies never runs so much at once that the disks are starved.

### The browser is given light copies, never the camera originals

- The browser is only ever handed sound-only files for listening; it is never given a camera original or a video file to get sound from. A sound copy lasts within 1 ms of its source and every moment in it plays at the source's own time (within 0.05 s).
- Sound the browser can already play is copied as it is, not converted; it is converted to a small copy only for a browser that cannot play it, and a browser that cannot play the kind it was given is given another kind when it asks.
- The picture is a picture-only copy no taller than 480 lines (never enlarged, keeping its shape), with a whole picture every second of source time, so it can start playing before it is fully fetched and jump anywhere quickly.
- Fetching part of a file works with every way a browser asks for one. When a browser gives up on a request, the server stops reading and sending it within a second.

### The editor finds each clip's sound by itself and lists the clips it cannot play

For each clip a cut list names, the editor plays, best first: the light copy of the interview's reference sound recording; the reference recording itself while that copy is not ready; the interviewee's multicam sound file; or the sound taken from the clip's own video (used for news montages). A clip named after a video file is found by its name without the file ending, and a clip name too long for the disk still finds its file. A clip whose transcript is an excerpt of another transcript plays the other's recording (following up to 3 such links). A clip whose only text is a subtitle file beside its media plays, shows those words on its cards, and opens a transcript built from the cues. Only files that exist are matched, and a clip name never reaches outside the episode.

The editor can list the sound of every clip a cut list uses (in the cut and on the bench, in first-use order) and of every clip an episode has, each with its length, rate and channels; clips with no sound, or whose sound cannot be read, are listed as missing ("no audio track"). Sound plays from any point. Sound already made still plays when the original media can no longer be reached. A clip whose sound cannot be decoded gives up after 20 seconds, and making a whole sound copy gives up after 10 minutes; either says why.

- When the help for the editing program is off: nothing changes; no clip's sound depends on the editing program.

### A clip whose sound is still being prepared is dimmed on the lane

While a clip's sound copy is being made, the clip is dimmed on the lane and the page asks again until it is ready. A clip's sound is in one of these states: ready, being made, failed (with the reason), or none (its media cannot be reached).

- Pending: cards-editor-2-Q11

### Sound is always prepared before video, and progress is shown as a count

Sound extractions are made before small video copies; a video copy already being made is not interrupted, but waiting sound is then made alongside it. Progress is shown as "N of M" (finished of those asked for), with " + [the studio's other computers] 62%" or " + [the studio's other computers]: N" added while work handed to other studio computers is in flight.

- Exact: yes
- Pending: cards-editor-2-Q11

### Each clip's picture copy comes from its own media, and a failure is remembered until the media changes

A clip's picture is made from the original media recorded for its transcript (an interview clip, or a montage source clip found by name, exactly and then ignoring case), else from a video file named after the clip among the episode's montage clips. A cut from a multicam takes its picture from its angles' own media. A source that is sound only says so ("its media is sound only"); nothing found says so ("its media file was not found"); a file with no picture says so ("the file has no video track"). Making a picture copy gives up after an hour and says so. A failure is remembered and shown until the media file itself changes, which earns a new try, and a changed media file gets a new copy. A copy already made is reused as long as it is not older than the media it was made from.

### Each clip's waveform is made once, fine enough for 1/200 of a second, and reused

A clip's waveform shows the loudest moment of every 1/200 s, made from its reference recording, else from its own media. It is made once and kept, and anyone's later request reuses it as long as it is not older than the sound; one older than its sound, or made more coarsely, is made again. Several viewers asking at once share the one making. A waveform shows "making" while it is made and "failed" when it could not be, and a failed one is tried again after 10 minutes. A waveform that cannot be kept is still shown.

### The footage is never touched, and everything made for playback is kept apart from it

Every file made so the editor can play a clip (light sound copies, small picture copies, waveforms) is kept in the episode's own working area, never beside the original media, which the server may only be able to read. Each is named after the clip as the editor knows it; a name too long for the file system is shortened with a short unique tag, and a name that fits is never changed. No file of the episode is changed by any of this.

### A clip that becomes ready while the page is open plays at once, and every request gets a real try

Every view that plays sound (the lane, the edit view, the transcript, the shelf) keeps checking until its clips are ready, also when a phone opens straight into one of them. A clip that becomes ready while the page is open plays at its first join without a stall (under 100 ms), and nothing made while it was unavailable is reused. Requests for sound, pictures and waveforms always get a real attempt, unless the person chose to work offline; a momentary dropped connection never stops the clip that is playing. An answer that comes back empty, or a request that fails or times out (for a clip's words, sound, picture or waveform), is asked again after a pause of a few seconds, never at once and never given up on; only a definite "not found" means there is nothing. (Making a copy that failed is a different matter: it is retried as each copy above says.)

#### Lessons

- Met: CE2-062, CE2-063, CE2-065, CE2-066, CE2-064, CE2-067, CE2-068, CE2-069.
