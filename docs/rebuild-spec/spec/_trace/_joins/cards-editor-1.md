# Joins aimed at cards-editor-1

## Checked

- J1 | fine
- J2 | F1
- J3 | fine
- J4 | F2
- J5 | F3, F4, F5
- J6 | F6, F7, F8
- J7 | fine
- J8 | fine
- J9 | F9
- J10 | F10
- J11 | F11
- J12 | F12
- J13 | F13

## Findings

### F1: The board points to this piece for the undo and redo keys, which are not here
- Kind: missing
- From: cards-board / The board works by touch first, and by keys
- Here: nowhere (undo and redo keys are in cards-editor-2, "Ctrl+Z undoes, and Ctrl+Shift+Z and Ctrl+Y redo")
- From says: "(selecting, moving, undo and redo), it uses the same keys and the same gestures, so nothing has to be learned twice. The keys of the editor are given in Timeline Cards: the editor (Selecting, deleting, inserting and keys)."
- Here says: nothing
- Settled by: OWNER_REQUIREMENTS.md section 6, The board: "where the same act exists in both (select, move, undo), the same keys and gestures."
- Fix: cards-board's pointer also names Timeline Cards: the editor, "Editing, undo and the cut list" for undo and redo.

### F2: The English toolbar offers Delete words, Highlight and Split here on a shelf card, but the lane refuses words of any card not in the cut
- Kind: contradiction
- From: cards-editor-3 / Selecting English on a card, a shelf item or a search result shows the original words it stands for in a floating toolbar
- Here: Words chosen on another surface can be acted on by the lane, which says when it cannot
- From says: "For a card on the shelf the same buttons without Play. Delete words, Highlight and Split here do what the lane's own word tools do, with their message"
- Here says: "Refusals: "That card is not in the cut, so the lane cannot act on its words.""
- Settled by: the owner must say: can a person delete, highlight or split the words of a staged card on the shelf from its English toolbar, or only those of a card in the cut?
- Fix: if yes, cards-editor-1 says how the word tools act on a shelf card and drops that refusal for it; if no, cards-editor-3 offers only Copy original on a shelf card.

### F3: Each reading aid is an on/off switch here, but three modes with different defaults there
- Kind: contradiction
- From: cards-editor-3 / Ten reading aids help an editor cut speech in a language they do not read, each switched Off, on for languages not read, or on for all
- Here: Language aids mark verbs, names, numbers, negation, fillers, safe cut points and sentences
- From says: "Modes per aid: Off (never), Not read (on for languages not in "Languages I read"; the default for eight aids), All (on for every language; the default for aid 1). Aid 7 is Off by default." (fillers: "Default: Not read")
- Here says: "Each aid is switched on or off by itself on each device. By default every aid is on for an interview whose language is not among the person's "languages I read", and off for one that is, except the faint strike through fillers, which is off until a person switches it on."
- Settled by: CE3-004 (ruling): "Each aid is a per-device toggle, on by default for languages outside "languages I read""; for fillers CE3-008 (ruling) declines "hesitation and filler marks", so the owner must say: should fillers be marked at all, and if so are they on by default for languages he does not read?
- Fix: cards-editor-3 makes each aid a per-device on/off switch defaulting as CE3-004 says (no Off/Not read/All modes, aid 1 not "All"), and both pieces give one fillers default once the owner has answered.

### F4: The lane's list of aids has seven, the reading aids have ten, and the word-by-word line is switched in two places
- Kind: differs
- From: cards-editor-3 / Ten reading aids help an editor cut speech in a language they do not read, each switched Off, on for languages not read, or on for all
- Here: Language aids mark verbs, names, numbers, negation, fillers, safe cut points and sentences; Each clip shows its speaker, its length and its words, sized to what fits
- From says: "| 7 | Word-by-word gloss | "A literal English word under each original word" | a "Word by word" line under the original (transcript, cards and lane)" with "Default: Off"
- Here says: "shows or hides each reading aid (verbs, names and places, numbers and dates, negation and contrast, fillers, safe cut points, sentence numbers)" and "Literal line (when switched on in the lane bar and available): an italic word-for-word English line under the first"
- Settled by: CE3-004 (ruling), the owner asked for ten aids; OWNER_REQUIREMENTS.md section 1: "One way to do each thing: ... one place a setting comes from".
- Fix: cards-editor-1's Language aids setting names the same ten aids as cards-editor-3 (or points to it), and its "Literal line" is stated to be aid 7, the word-by-word gloss, switched in one place only.

### F5: Aid 4's snap of a dragged edge is given two different rules in this piece
- Kind: contradiction
- From: cards-editor-3 / Ten reading aids help an editor cut speech in a language they do not read, each switched Off, on for languages not read, or on for all
- Here: Safe cut points show whether a cut leaves a whole thought, and Alt+S moves an edge or a pick to the nearest one; Dragging a clip's edge trims it live, heard as it moves, and commits on release
- From says: "ticks between words of the original (see the lane's safe cut points); also turns on the nudge for picks and dragged edges"
- Here says: "Dragging an edge (with aid 4 on) snaps to the safe gap nearest the edge within 2.5 s" and, in the trim behaviour, "Safe cut snap (when language aids are on): within 9 px (16 px on touch) of the nearest point where a cut leaves a whole thought, the edge snaps to it; Alt drags free."
- Settled by: CE3-008 (ruling) lists "snapping trims" among features declined and never to be proposed again; the owner must say: does a dragged edge snap to a safe cut point at all, and if so from how far away?
- Fix: cards-editor-1 keeps one snap rule (or none, per the owner), tied to aid 4 alone, and cards-editor-3's "nudge for picks and dragged edges" matches it.

### F6: Where a section summary is kept, and what renaming does to it, differ from the summary piece
- Kind: contradiction
- From: cards-editor-4 / The assistant writes a one- or two-sentence summary of a section into the cut list, undoably
- Here: The assistant writes a one-sentence summary of what each section says
- From says: "it is written into the cut list as ONE undoable edit under the heading, together with a fingerprint of the words it was written from"
- Here says: "A summary is kept per timeline under the section's title (repeated titles numbered #2, #3), so it survives trims and moves; renaming a section loses its summary."
- Settled by: CE2-038 (situation, weaker): "A summary follows its section through trims and moves; a renamed section loses it on purpose, and an orphan is never guessed onto another section."; this piece's own fold behaviour already says "the summary stored under the heading in the cut list".
- Fix: cards-editor-1 replaces its full description with a pointer to cards-editor-4 (both describe it in full today), and cards-editor-4 says what a rename does to the summary stored under the heading.

### F7: A section's summary ends at the next marker here, but note rows do not end it there
- Kind: contradiction
- From: cards-editor-4 / The assistant writes a one- or two-sentence summary of a section into the cut list, undoably
- Here: The overview's list shows each section's length and takes the playhead there on a click; The assistant writes a one-sentence summary of what each section says
- From says: "up to the next heading of any kind; note rows do not end a section"
- Here says: "the sparkle button "AI summary of this section (up to the next marker)"" and "from the cards between its heading and the next" (a note row is a marker here: "a note (a note heading or a note line)")
- Settled by: the owner must say: does a section's summary cover the cuts that follow a note row inside the section, up to the next heading?
- Fix: the sparkle button's tooltip in cards-editor-1 says the same span as cards-editor-4 once the owner has answered.

### F8: The summary's refusals and its out-of-date mark are worded differently
- Kind: contradiction
- From: cards-editor-4 / The assistant writes a one- or two-sentence summary of a section into the cut list, undoably
- Here: The assistant writes a one-sentence summary of what each section says
- From says: ""The summary needs Assistant on the server: <reason>"", ""Nothing transcribed between this marker and the next, so there is nothing to summarise."", "a gold "Out of date" chip"
- Here says: ""the section summary needs Assistant: <why>", "no marker at frame N", "nothing transcribed between this marker and the next"" and "A summary whose section's words have changed since is marked stale."
- Settled by: the owner must say: which sentences does a person read when a section summary cannot be written (this piece's own fold already shows "Out of date", as cards-editor-4 does)?
- Fix: cards-editor-1 drops its own refusal list and points to cards-editor-4 (the same change as F6).

### F9: A quick press of the controller's Menu opens the shortcuts sheet here, but goes to a find box there
- Kind: contradiction
- From: cards-editor-5 / The help sheet lists every controller button for each place
- Here: A shortcuts sheet lists every key, grouped by where it applies
- From says: "Ways in: the controller's Menu held, the "?" key and the Shortcuts buttons" (and in cards-editor-5: "Menu tap: put the caret into a find box ... Menu held 600 ms: open the controller map (the help sheet)")
- Here says: "Opened by "?", by the Shortcuts buttons, and by the controller's Menu (which toggles it)." and "Ways in: "?", the Shortcuts buttons, the H key, the controller's Menu button."
- Settled by: the owner must say: on the lane, does a quick press of the controller's Menu button open the shortcuts sheet, or put the caret in a find box with only a held Menu opening the sheet?
- Fix: cards-editor-1 says "the controller's Menu held" if cards-editor-5 is right, or cards-editor-5 changes its Menu tap if not.

### F10: Footage-in says frame-accurate cut points are measured from the sound, as this piece describes, but this piece places every cut point from word times
- Kind: missing
- From: cards-footage-in / Every word is timed, and a word's time is for finding it, not for cutting on it
- Here: nowhere (cut points come from word times, for example under "Safe cut points show whether a cut leaves a whole thought, and Alt+S moves an edge or a pick to the nearest one")
- From says: "it is never used as a frame-accurate cut point: anything that needs one measures the sound itself (see Timeline Cards: the editor: The lane: clicking, trimming, zooming and dragging)"
- Here says: "In a gap an out point goes a little after the left word (half the pause, at most 0.12 s), an in point a little before the right word (half the pause, at most 0.08 s)." (and Delete words cuts "halfway through the pauses either side")
- Settled by: CFI-059 (given, weaker): "No transcribed word time is treated as a frame-accurate cut point; anything needing one measures the audio itself."
- Fix: cards-editor-1 says that where an edge is placed at a word (safe cuts, Delete words, Split here, an insert's handles) the point is found in the sound itself, or cards-footage-in drops the pointer.

### F11: How a plain heading travels to Resolve and back is said nowhere
- Kind: missing
- From: cards-to-resolve-and-exports / Sections and notes arrive as markers
- Here: What a marker is, and which kinds there are; The clip colours and the marker colours are the editing program's own
- From says: "A section heading becomes a marker named after the heading, in the section's own colour (Blue when it has none). A note heading becomes a Green marker, and each note line a Green marker" (no plain heading); "an unknown colour becomes Blue"
- Here says: "A plain heading takes none." and "the hand-over describes which colours mean a plain marker (see Timeline Cards: the hand-over to Resolve, and exports: Undo, markers, titles, fades and properties)"
- Settled by: the owner must say: when a cut list holding a plain heading is sent to Resolve, what colour of marker does that heading become, so that reading the timeline back keeps it a plain heading?
- Fix: cards-to-resolve-and-exports says under "Sections and notes arrive as markers" how a plain heading is sent and which colour means a plain marker on reading back (today only its import section says "a plain marker when Red").

### F12: Interviewee colours are a palette of their own that repeats after eight there, but unique Resolve colours here
- Kind: contradiction
- From: cards-to-resolve-and-exports / Clip colours on a sent timeline
- Here: Each interviewee has a colour of their own; The clip colours and the marker colours are the editing program's own
- From says: "Each of the 16 interviewee palette colours is paired with one of Resolve's clip colours, in order: ... so the first 8 speakers get 8 different clip colours and they repeat after that. A colour chosen by hand that is not in the palette is matched to the nearest Resolve clip colour."
- Here says: "Every interviewee in an episode wears one colour, and no two interviewees of the same episode share one." and "Each colour on a card or a clip is the very colour it is in DaVinci Resolve, for all sixteen clip colours."
- Settled by: CE2-042 (ruling): "no two interviewees in an episode share one"; CE2-041 (situation, weaker): "Interviewee colours equal their Resolve clip colours for all sixteen".
- Fix: cards-to-resolve-and-exports drops the separate interviewee palette and its mapping: each interviewee's colour is already one of Resolve's clip colours, unique in the episode, and is sent as it is.

### F13: The Send to Resolve key sends here, but sending first opens a dry run there
- Kind: contradiction
- From: cards-to-resolve-and-exports / Where the dialog and the script downloads are reached
- Here: The keys for searching every transcript, the edit chat and Send to Resolve say so when their tool is not ready
- From says: "the cut's own actions hold "Send to Resolve", which opens the Send tab with a fresh dry run."
- Here says: "the key for "Send to Resolve" sends."
- Settled by: CRX-061 (ruling): "No timeline is built or changed in Resolve until the editor confirms after seeing the cut, marker and length counts."
- Fix: cards-editor-1 says Alt+Shift+M opens the Send tab with a fresh dry run, as the cut's own action does, and cards-to-resolve-and-exports lists Alt+Shift+M among its ways in.
