# Timeline Cards: the editor, part 1 of 5

The Timeline Cards editor is where the film is cut: the owner and the studio's editors open an episode's cut list in a browser on a desk, a tablet or a phone, and shape it with keys, a mouse, a pen, a finger or a game controller. The cut is shown twice over and kept in step: as a lane, a timeline strip with each clip's words written inside it, and as cards, a reading surface grouped by section, beside the episode's transcripts. Everything up to the finished cut works with no editing program at all; handing the cut to one is the last step and a separate sub-topic. Timeline Cards is one part a site switches on and off as a whole (footage in, the board, this editor and the hand-over go together). When it is off, nobody but an admin sees it, and only in settings, where it is listed with its switch: editors find no Timeline Cards entry, page or control anywhere, and switching it off deletes nothing, so every cut list, transcript and fold is there again when it is switched back on. This part covers how the lane and the cards look and read, colours, sections and the overview, the mouse, pen and touch on the lane, and selecting, deleting, inserting and the keys.

## The lane: how clips look and read

### The lane shows the whole cut as a timeline with a section band, a ruler, the clips and a minimap

The lane is the editor's heart and gets the most room on the screen: clip text stays legible at every zoom and every height, the lane can be resized and docked at the top or the bottom, and it plays every cut in order. Any edit made on the lane is exactly the same edit as the one made on the cards. Its parts, from top to bottom:

- From top to bottom: the lane bar (its controls are described with the page's panels), the **section band** (one flag per section in view), the **ruler** (time ticks and marker ticks), the **track** (the clips), the **minimap**, and on top of these the selection outline, two edge handles, a readout, the playhead, an insertion line, the word bar and a line where the lane says what it did (shown for 4.5 s).
  - **Zoom and scroll**: zoom runs from "the whole cut with a little air either side" up to 400 px per second (about 13 px a frame). Scrolling always keeps at least a tenth of the window over the cut.
  - **Section band**: a flag over each section's span showing only what fits whole: "§ 1.1 Name N cuts", "§ 1.1 Name", "§ 1.1", or nothing. The current section is marked. Hover gives the name, plus "(drag to move the section, its cuts come too)" on a § section's flag or "(drag to another clip to move it)" on other headings.
  - **Ruler**: ticks at steps of 0.5, 1, 2, 5, 10, 15, 30 s, then 1, 2, 5, 10, 15, 30 min, the smallest step that keeps labels well apart, labelled m:ss (m:ss.s for half seconds). A coloured marker tick at the first cut of every heading. Labels under the readout are hidden while it shows.
  - **Minimap**: the whole cut as section-coloured segments with a box for the visible part; press or drag to centre the window there.
  - **Playhead**: a line, hidden when outside the window.
  - **In / out range**: when range marks are set, the range is washed with a bar at each set end, labelled "In m:ss.cc, out m:ss.cc" / "No in" / "no out".
  - **Phone reveal**: on phones, a newly selected item outside the window scrolls the window to show it, once per change of selection.
  - **Playback follow**: while playing with follow on, the window pages along: when the playhead leaves the part of the window from 2% to 92%, the window jumps so the playhead is at 10%.
  - On the portrait phone's mini lane there is no band, ruler, minimap, names or readout; on the landscape phone's small lane no band, ruler, minimap or readout.

On a desk the lane docks at the top or the bottom of the editor, by dragging or by its button; the choice is remembered, and docked at the top it leaves no more gap above it than the page's normal margin. However the lane is resized or moved, the cards and the transcript panel flow around it and are never hidden beneath it. The readouts on the lane and its bar keep a fixed width, so no control moves while a value it shows changes, and the size of the clip text can be changed and is remembered on the device. Coming back to the lane, or reloading, restores its scroll and zoom, unless a jump, playback that is running or the person's own touch asks for somewhere else. The lane stays smooth at the zooms and screen sizes an editor really works at, with real waveforms drawn; a playhead running off screen at a high zoom is acceptable. A playing playhead moves smoothly at every zoom, never in jumps, and when it reaches the edge of the window the lane pages forward with it, unless the person is panning the lane at that moment.

- Name and search words: the lane: timeline, clips, strip, track, minimap.
- Phone and desk: the portrait phone has a mini lane and the landscape phone a small lane, each with fewer parts, as listed above.
- Exact: yes

### Each clip shows its speaker, its length and its words, sized to what fits

- Each cut is a block in its speaker's colour, with a hard seam at its end. A very narrow clip (under 3 px) is only a colour tick.
- **Name row**: short speaker name and length ("15.4 s"), held at the clip's visible left edge, shown only when it fits whole (the name alone if only that fits, nothing if not). Not shown on very narrow clips, on a short track, or on the portrait phone's mini lane. After it, when it fits, a small tag: "English pick", "spoken words", or the no-English tag ("no English", "loading…" while the English is still being made, or the reason there is none).
- **Words in the clip** (when the track is tall enough): the leading language's text wrapped inside the clip. Wrapping never changes as the lane scrolls sideways; a clip wider than the screen slides its words to stay in view; a narrow clip lays its words out at a readable width and cuts them at its edge. Latin words are never broken; text that does not fit ends with "…".
- The second language shows under the first only if the first fitted completely and the second fits whole, a step smaller and quieter.
- **Literal line** (when switched on in the lane bar and available): an italic word-for-word English line under the first, up to 3 lines, its word lit with the spoken one.
- Text is dark on light clip colours and light on dark ones, so it is always readable.
- **The lit word**: in the clip under the playhead, the word being spoken is washed and underlined; words already said stay at full brightness and words still to come are slightly dimmer. During an edge drag the lit word is the word the trim will cut to, and on a shortening drag the words that would go are faded and struck through in red. Nothing is lit in a pause more than 0.3 s after a word. In an English line the lit word is carried across by position, or exactly when the links between English and original words are known.
- Words that have not been laid out yet appear within a frame or two; they never hold up the lane.

Chinese and other scripts written without spaces wrap by character; a Latin word is never split across lines. Clip text re-wraps only when the zoom changes, never while the lane scrolls. At any zoom a narrow clip keeps its words, cut off at its edge. During playback the lit word is exactly the word under the playhead, on a split, a trimmed or an edge-word clip alike, at every zoom, and still after the lane is zoomed while it plays.

- Exact: yes

### Clips show a waveform at the level they will play, with fades, gain, notes, gaps and the selection

{{29-044}}

A selected clip's outline and marks are thin and never reach past the clip's top or bottom.

- Exact: yes

### Every clip on the lane is drawn at full brightness whatever section the playhead is in

No clip is ever dimmed for lying outside the current section: every clip on the timeline is drawn at full brightness wherever the playhead is.

### Language aids mark verbs, names, numbers, negation, fillers, safe cut points and sentences

The language aids let the owner cut interviews in languages he cannot read.

{{29-054}}

Each aid is switched on or off by itself on each device. By default every aid is on for an interview whose language is not among the person's "languages I read", and off for one that is, except the faint strike through fillers, which is off until a person switches it on. Where an interview's words have not been analysed, the aids draw nothing and the editor says so quietly in one line; everything else works as usual.

- Setting: Language aids. Does: shows or hides each reading aid (verbs, names and places, numbers and dates, negation and contrast, fillers, safe cut points, sentence numbers) in the lane's clips. Default: on for languages outside "languages I read", off for the others, the strike through fillers off everywhere. Who: anyone using the editor. Applies to: a computer. Search words: language aids, reading aids, grammar marks, safe cuts, verbs.
- Exact: yes

### A note on a gap shows inside the gap on the lane

{{33-040}}

- Exact: yes

### F9 or Shift+X switches the words in the clips between English and the interview's language

- **F9** and **Shift+X** switch the words shown in the lane's clips between English and the interview's original language (any language, not assumed Chinese); only when a lane is up. Key repeat does nothing more. Listed as "F9, Shift+X: The words in the clips: the interview’s language, or English". Ignored while typing or composing text. Each clip in the lane shows two lines: by default English first and the original language second; when English leads but there is no English yet, the original leads and the clip is marked as having no English.

The same choice is also made by one control on the lane bar. It is remembered in this browser, and every surface of the editor follows it. Each clip's language is the language of its own transcript.

- Exact: yes

### A clip's timed words appear on the lane as soon as they are known

Each clip on the lane shows its own timed words, spelled exactly as the clip's transcript spells them, as soon as the lane needs them. A clip with no words shows none. When a clip's words cannot be had for a moment, the lane goes on without them and they appear once they can. Opening another cut list shows that cut list's own words.

### Where each card sits on the lane follows the cut list exactly

Cards start at the cut list's timeline start timecode (default 01:00:00:00). Each cut's black before it becomes timeline frames. Its source in and out are counted at the clip's real rate: what is known about the clip, else the rate the cut list names for it, else the timeline's rate. Its length on the timeline is its source length scaled to the timeline's rate, so it keeps its real running time, and is never less than one frame. Fades are shown in timeline frames, and the gain set by hand is carried in dB.


### A card shows the words spoken inside its cut, with partly cut words marked

{{40-012}}

A cut whose clip has no transcript at all is still a card and a clip like any other, labelled "no transcript"; one whose cut holds no words is labelled "silent". Such cuts move, trim and delete like every other and are never dropped.

- Exact: yes

### Each card shows who speaks, where, for how long and what was done to it

{{40-015}}

- Exact: yes

#### Lessons

- Met: CE3-001, CE3-002, CE3-003, CE3-004, CE3-005, CE3-006, CE3-007, CE3-008.
- Met for another part: CE1-090 (in "The lane shows the whole cut as a timeline with a section band, a ruler, the clips and a minimap"), CE2-054 (in "Each clip shows its speaker, its length and its words, sized to what fits").

## Colours

### The clip colours and the marker colours are the editing program's own

Clip colours (16): Orange, Apricot, Yellow, Lime, Olive, Green, Teal, Navy, Blue, Purple, Violet, Pink, Tan, Beige, Chocolate, Brown. Brown is never written: a cut given Brown is written as Chocolate, and the picker never offers it.

Marker colours (16): Blue, Cyan, Green, Yellow, Red, Pink, Purple, Fuchsia, Rose, Lavender, Sky, Mint, Lemon, Sand, Cocoa, Cream.

A new section takes the next colour in the rotation Blue, Sand, Purple, Mint, Rose, Sky, Lemon, Fuchsia, Cyan, Cocoa, Lavender, Yellow, Pink, Cream after the section above it (Blue when there is none, or when that section's colour is not in the rotation). A note heading takes Green. A plain heading takes none.

Each colour on a card or a clip is the very colour it is in DaVinci Resolve, for all sixteen clip colours. Drawn on the editor's dark surfaces, every one of them stays recognisable, at a contrast of 3:1 or better, without the colour itself being altered (an outline or a lighter edge may carry it). Status colours such as amber and red stay distinguishable from each other at the small sizes they are drawn at, 11 to 12 px.

### Each interviewee has a colour of their own

Every interviewee in an episode wears one colour, and no two interviewees of the same episode share one. A cut with no colour of its own takes its person's colour. Changing a person's colour is one action that recolours every one of their cuts in one undo (the picker's "Every cut of <speaker>" choice, below). In a montage, each speaker or source gets a colour of its own, and two neighbouring clips from different sources never share one. The open transcript panel is outlined in the colour its interviewee carries on the cards and the lane.

### The clip colour picker colours one cut, a selection or every cut of one person

{{33-028}}

- Ways in: right-clicking a card, the cut menu on the lane, a staged card's menu, the selection menu, Shift+C.
- Exact: yes

### Shift+C opens the colour picker for the cut that makes sense

{{33-029}}

- Exact: yes

#### Lessons

- Met: CE2-040, CE2-041, CE2-042, CE2-043, CE2-044.

## Sections and the overview

### What a marker is, and which kinds there are

Every marker in a cut list is one of three kinds: a section (a section heading), a note (a note heading or a note line), or a plain marker. The kind is kept apart from the colour: any colour can make a section, recolouring a marker never changes its kind, and the kind changes only when a person asks for it. Markers read off a Resolve timeline, which carry only a colour, take their kind from it: Green means a note, and the hand-over describes which colours mean a plain marker (see Timeline Cards: the hand-over to Resolve, and exports: Undo, markers, titles, fades and properties).

Each section is told apart by its own identity, never by its place in the list, for dragging, dropping, placing by tap and folding, and that includes a section with no cuts in it.


### Section headings and notes in a cut list show as markers on the lane

{{39-038}}

- Exact: yes

### Markers stay with the cut they stand in front of

{{39-049}}

A drag of a cut across a section boundary changes only the dragged cut's section; no other cut changes section. Deleting a section's first cut keeps the heading. When a cut is split, both halves stay in its section.

- Exact: yes

### A person adds, renames, recolours, moves and removes headings and note rows, and moves a whole section

- **Add** a section, a note heading, a plain heading or a note row in front of a cut or a gap, or at the end. A title is one line: runs of spaces become one, and a title may not hold a comment ("a marker cannot contain a comment"). An empty heading title becomes "Section"; an empty note row is allowed. A plain heading may not start with "Alternates", "staged" (in any case), §, ◆ or ⧉, and is refused with "a plain heading cannot start with "Alternates", "staged", §, ◆ or ⧉: the cut list reads those as a shelf or another kind of heading; make it a section instead". A colour must be one of the marker colours ("X" is not a marker colour) or none, which gives the kind's default colour (see "The clip colours and the marker colours are the editing program's own").
- **Change** a marker's title, colour or kind in place. A colour change never changes the kind; colour none gives the kind's default; section and note headings always keep a colour; an empty new title keeps the old one; a note row takes only new text. Refusals: "that is a cut, not a marker", "that is a gap, not a marker", "that marker is not in this cut list".
- **Move** one heading or note row in front of an item or to the end; the cuts and gaps stay where they are.
- **Remove** one heading or note row; the rows under it stay.
- **Move a section**: the heading and every row up to the next heading, in front of another heading or to the end. Refusals: "a section cannot be moved inside itself", "only a section heading can be moved that way".

Any punctuation, bracket or line break a person types into a title, a note or a name survives saving and reopening unchanged, and nothing typed into one can make, remove or change a cut.

### A sections rail on the desk and a strip of section chips on the phone list the sections and jump to them

{{29-018}}

- Name and search words: the sections rail: sections, chapters, jump to section, outline.
- Phone and desk: a rail on the desk, a strip of chips on a phone, nothing on a tablet.
- Exact: yes

### The cards panel shows the cut as a reading surface, grouped by section, with notes in place

{{29-019}}

- Name and search words: the cards: cards, cut list, reading view, script.
- Exact: yes

### Each cut's card shows who speaks, its span, its words, its gain, fades and length

- Speaker (the person, else the clip), "in → out" (m:ss.cc), chips for gain ("+2.0 dB"), "Fade in N.NN s", "Fade out N.NN s", a red "Delete again: N" countdown while a delete is armed, and the length (shown as live while an edge drag changes it).
- The words: the line in the interview's own script (any non-Latin script) leads; Latin lines beside it show under it as the English. "No words yet" when there are none. Highlighted phrases (the part that plays) are marked.
- Colour = the speaker's colour: the colour written for the cut in Resolve's colour names (15 names; "Brown" means Chocolate); a cut with none takes the colour most of that person's cuts carry; else a colour fixed for that person or clip that never changes between sessions.
- A note under the cut (flag); clicking it opens the note editor.
- While playing, the word being spoken is underlined from the clip's word timings (nothing between words); without timings a short phrase steps through by its share of the cut.
- The **primary selected card** shows actions: "Play"/"Pause", "Split", "Stage", "Edges" (phone only, opens the edit view), "More actions".
- W opens or closes a card's full text.
- States: the selected card has a full-height red bar beside its colour bar (never a red wash); the card under the playhead has a red dot in its left margin; a lifted card is outlined and raised; a delete-armed card has a red outline.

The card the playhead is inside opens like the selected card, at every density of the cards, and closes again when the playhead leaves it. When the playhead sits in a gap, that gap is highlighted in the cards the way a card would be. Playing never moves a control. The marks for the playhead (the dot on its card, the bright frame on its clip in the lane) are their own, apart from the selection's marks, and follow the playhead within a quarter of a second during playback and while scrubbing.

Every section, note and plain heading row and every note row in the cards can be deleted in place with one click on its own delete button, as one undoable edit (""<name>" deleted. Ctrl+Z brings it back."); the rows under it stay. Each can also be dragged to another place, as described under "Mouse and keyboard on the cards select, open, re-order and move markers".

- Phone and desk: "Edges" shows on a phone only.
- Exact: yes

### The Overview panel lists every section, note and marker of the cut list and opens with O

{{32-051}}

The Overview button always shows on the top bar on a desk; it is never folded into a menu.

- Name and search words: the overview: overview, sections, markers, outline, chapters.
- Ways in: the Overview button, the O key.
- Phone and desk: a floating panel on a desk, a full-screen sheet on a phone.
- Exact: yes

### The overview's list shows each section's length and takes the playhead there on a click

- Every marker in document order: `## §` sections (a coloured tag "§ <number>" taken from a "1.1 - Name" title, and the name), `## ◆` note headings, plain headings, and note rows (italic; a flag icon for a note starting "⚑", its lead-in markup stripped; "Empty note" when empty). Headings inside a § section are indented.
- Each heading shows "<n> cuts · <m:ss>" (a § counts up to the next §; any other heading up to the next heading; gaps add length) or "empty".
- The heading the playhead is under is highlighted.
- Click a marker or its name: the playhead goes to the start of the cut it stands in front of and that cut is selected (or the head goes to the marker's time when nothing follows it); the marker is selected; on a phone the panel closes on the way.
- Per-row buttons: a fold button for headings (see "A section can be folded away in the cards to read its summary instead"); the sparkle button "AI summary of this section (up to the next marker)" / "Summarise this section again" / "Summarising"; and the pencil "Edit this marker" / "Edit this note" / "Close the editor".
- None: "No sections or markers yet. Add a section to start one at the selected cut."

- When the assistant is off: there is no sparkle button and no summary.
- Exact: yes

### Sections and notes are added and edited from the overview, each change one undoable edit

{{32-053}}

- Exact: yes

### A section is moved with everything in it by dragging, by a long press on a phone, or by the arrow keys

{{32-054}}

- Ways in: dragging its grip or its name in the overview, a long press on a phone, the arrow keys on its grip, dragging its flag above the lane.
- Phone and desk: a long press and a tap to place on a phone, a drag with a mouse.
- Exact: yes

### A ruler shows the whole cut by section, and M or the controller marks a section at the playhead

{{32-055}}

- Exact: yes

### A section can be folded away in the cards to read its summary instead

{{32-056}}

- When the assistant is off: a folded section shows its head, its count of cuts and its length, with no summary row.
- Exact: yes

### The assistant writes a one-sentence summary of what each section says

- The assistant writes one sentence (two at most, 35 words) on what a section says, from the cards between its heading and the next, each as "person: words" (in English where English exists). Refusals: "the section summary needs Assistant: <why>", "no marker at frame N", "nothing transcribed between this marker and the next"; asking again while one is being written just shows it running; "Assistant returned nothing" when nothing came back. A summary is kept per timeline under the section's title (repeated titles numbered #2, #3), so it survives trims and moves; renaming a section loses its summary. A summary whose section's words have changed since is marked stale.

A summary whose section is gone is never guessed onto another section. Each summary fits in a few lines.

- When the assistant is off: no summary is written or offered.
- Exact: yes

### Send to moves the selected cuts to the end of a chosen section

{{33-026}}

- Exact: yes

### The editor shows the cut's running time and each section's length

The editor shows the cut's total running time in seconds and, for each section heading, its title, its count of cards, its length in seconds and the frame it starts on. An empty section still gets a row; an untitled lead-in row appears only when cards come before the first heading. The timeline's exact frame rate is shown as well as the rounded one.

### A proposed montage is shown section by section and inserted where the person chooses as one undoable step

- "Proposed" box: "<n> cuts · <total seconds> · <n> notes"; "Asked: <text>" or "Revised: <text>"; a warning "<n> cuts named a clip that is not in the corpus, and went nowhere: <up to four clip names>."; the sections ("§ 1", "§ 2", ... with their titles), each listing its cuts: clip name (any trailing `[id]` tag hidden), length, a gold "Whole segment" chip when the exact words were not found and the whole transcript segment is used, the words (marked with the clip's language from its transcript, else the language the script looks like, else none), and "Why: <the assistant's reason>". Unmatched quotes show a red "Not found" chip and "Kept as a note: nothing Assistant proposed is thrown away." A new proposal scrolls into view.
- "Insert it" choice: "At the end of the cut" (default), "At the start of the cut", "Before the selected cut (cut <n>)" (when a cut is selected), and "Before <§ / ◆ heading>" for every heading. A choice that no longer exists falls back to the end; the choice is never rebuilt while it has focus.
- Footer sentence: "Lands <where>. Its sections become § sections." or "...Inside a section, its sections become note rows, so the cuts after it stay where they are." plus " The cut goes from <m:ss> to <m:ss>." and " One undo takes it all out." If the montage cannot be placed, the reason replaces it and Insert is disabled.
- "Insert into the cut" (primary): builds the edit against the cut list as it is at that moment and applies it as ONE step, titled "Montage: <first 120 characters of the request>", which syncs like any edit and is one undo. The new cuts are then selected. "inserted <n> cuts <where>. Undo takes it all out again." Refused: "the montage was not inserted: <reason>"; cannot be placed: the reason or "the montage could not be placed: <reason>".
- "Discard": "discarded: nothing was changed".
- An inserted or discarded proposal is never offered again, on this page or any other.

- When the assistant is off: there is no montage builder.
- Exact: yes

### Where an inserted montage lands, and nothing it proposed is dropped

{{32-049}}

- Exact: yes

#### Lessons

- Met: CE2-032, CE2-033, CE2-034, CE2-035, CE2-036, CE2-037, CE2-038, CE2-039.
- Met for another part: CE1-053, CE1-092 (in "Each cut's card shows who speaks, its span, its words, its gain, fades and length").

## The lane: clicking, trimming, zooming and dragging

### The lane handles like the editing program's own timeline

The lane is worked the way the studio's editors work Resolve's timeline: Alt or Ctrl with the wheel zooms, a middle-button drag pans, edges ripple-trim, and the keys are the ones described under "The lane's keys follow the editor's own keyboard layout in Resolve, where one exists". A gesture started on the lane, a trim or a drag in progress, or a lane still coasting after a fling is never moved or redrawn from under the person by anything arriving from another device or from a refresh; that waits until the gesture ends.

A trim gesture repaints within 125 ms in 95 of 100 tries on a desk computer, and within 500 ms on a processor slowed four times. After a trim or a split the clip shows only the words inside its new edges, and their English, in the same frame as the edit, with nothing to wait for.

### After an edge edit the playhead stays on the same spoken moment

After any edge edit (dragging a clip's edge on the lane, the controller's bumpers, a hold on the phone, the trim and extend keys), the playhead stays on the same spoken moment of the clip it was in. A trim earlier on the timeline makes the playhead slide back with that moment. If the trim cut away the very moment the playhead was on, the playhead lands on the last frame of that same clip, never on the next clip's first frame. A playhead in a gap keeps its distance into that gap, and a playhead past the end of the cut keeps its time. An edit never carries the playhead forward: when a ripple extend adds material before it, the playhead stays where it is on screen. None of this applies while playing: the playhead is only put back when playback is stopped.


### Mouse, finger and pen each have their own click allowance and edge grab size on the lane

{{28-051}}

At every zoom a press acts on the clip drawn under the pointer.

- Exact: yes

### Gestures on the lane never scroll or zoom the page, and only one runs at a time

{{28-052}}

- Exact: yes

### With a mouse, a press on the lane moves the head, and clicks select

- Press on bare lane: the head goes there at once (silent). Drag from bare lane: the head follows the pointer and is heard as it moves. It stays inside the timeline.
- Click an item's body (released within the click allowance): select it, replacing the selection. Ctrl+click (Cmd on Mac): toggle it in the selection. Shift+click: select the range from the anchor to it. Shift+click on bare lane moves the head there.
- Double-click on a clip opens that cut's paragraph in its transcript (see Search and the transcript panel).

A click or a tap on a clip only selects it: the playhead stays where it is, and neither the lane nor the transcript moves, unless the whole clip is off screen, when the lane scrolls just enough to show it. Otherwise the frame under the pointer stays put. Only the ruler, bare lane or a key made for it moves the playhead.

- Exact: yes

### Clicks, taps, the ruler and the wheel move the playhead, scrub, scroll and zoom

{{29-048}}

- Exact: yes

### Dragging an item's body moves it, or the whole selected block

{{28-055}}

A plain press and drag on a clip always moves it; picking its words needs a modifier or a held finger (see "Words inside a clip can be picked, then deleted, highlighted, split at or moved to safe cuts"). While it is carried, the clip is see-through and a landing line shows. A drop lands exactly where its landing line is drawn, on either side of a gap, and every hint shown with the line says the same.

- Exact: yes

### Clips, markers, whole sections and staged cards are dragged into place on the lane

{{29-049}}

- Exact: yes

### Shift+drag draws a box that selects every item it touches

{{28-056}}

- Exact: yes

### Clicking an edge arms it, and dragging an edge trims a cut or resizes a gap

- Click an edge (no movement): arm that edge for the frame and second keys (see "The frame and second keys move the head, or trim an armed edge").
- Drag an edge of a cut: ripple trim or extend. A ghost shows the new edge while dragging. An in edge never goes before second 0 of the source clip and never within 1/24 s of the out edge; an out edge never within 1/24 s of the in edge; an out edge dragged past the end of the source is refused on release. Release commits one trim (if the edge moved).
- Drag an edge of a gap: resize the gap. Out edge later = longer; in edge later = shorter (the gap's start stays and what follows ripples). Never under 1/24 s. Release commits one change (if it changed).

Dragging an edge outward lengthens the cut from its source and shows the new extent and its words live; it is refused only when the source has nothing left, and the refusal says so. A cut may be lengthened over material its neighbour also uses, with no refusal: that stretch then plays twice.

- Exact: yes

### Dragging a clip's edge trims it live, heard as it moves, and commits on release

{{29-046}}

- Exact: yes

### Fades are set by dragging a handle at the top of a clip

{{29-047}}

- Exact: yes

### The frame and second keys move the head, or trim an armed edge

{{28-005}}

- Exact: yes

### E and Shift+E ripple-extend a cut's edge to the head

{{28-008}}

- Exact: yes

### Q and W trim the cut under the head to the head, and B, F and Ctrl+B split

{{28-010}}

Trimming a cut's start or end to the head never leaves a leftover cut behind, of any length, at any frame rate.

- Exact: yes

### Next and previous edit and the clip start and end keys move only the head

Stepping to the next or the previous edit point, from the keyboard or the controller's D-pad, moves the head and nothing else: a single selection or a range selection stays exactly as it was. Each step lands exactly on the cut point, before and after gaps, in both directions, at 25 and at 29.97 frames a second. The keys that go to the start or the end of a clip act on the clip the head is in, whatever is selected. Their keys are listed with editing the cut list (see Editing, undo and the cut list).

### F8 puts the head where the mouse is on the lane, and holding it scrubs

{{33-069}}

- Exact: yes

### = and - zoom the lane

Everywhere, repeating. = zooms the lane in by x1.25; - zooms out by x0.8. The zoom holds still the time under the mouse pointer when the pointer is over the lane, else the head. Keyboard zoom runs from the whole cut up to 400 px per second, the same limits as every other way of zooming the lane.

Zoomed all the way out, the lane shows the whole cut, however long: a cut of two and a half hours fits whole.

- Phone and desk: on a phone, the vertical edit view zooms vertically too, from the detail of one card out to an overview of many cards.
- Exact: yes

### The middle button pans, the wheel scrolls, and Alt or Ctrl with the wheel zooms

- Middle-button drag: pan the lane (the browser's own middle-click autoscroll is suppressed, and nothing is pasted). On release the pan coasts (see "A flung pan keeps coasting and slows to a stop").
- Wheel: scroll the lane sideways. Horizontal wheel movement is used when present, else vertical; with Shift, vertical is preferred, else horizontal. The distance is the wheel movement in px (a line counts as 16 px, a page as 400 px) divided by the zoom. The scroll stays between the start and the end of the timeline.
- Alt+wheel or Ctrl+wheel (Ctrl is what a trackpad pinch sends): zoom about the time under the pointer. 100 px of upward wheel zooms in by about x1.28 (a factor of e^(0.0025 per px)); downward zooms out. The zoom runs from the whole cut up to 400 px per second. The page itself never zooms or scrolls from a wheel over the lane.

- Exact: yes

### A flung pan keeps coasting and slows to a stop

{{28-061}}

- Exact: yes

### Escape during a lane gesture throws it away

Escape during a gesture is seen before any other key: a box selection is dropped; an edge drag that has moved, or a move drag, is dropped with nothing committed, and the key goes no further. Escape on an edge that was pressed but not moved goes on to the keyboard's Escape (which disarms the edge, see "Shift+Up and Shift+Down grow the selection, and Escape backs out"). After Escape, the rest of that pointer's movement and release are ignored. A gesture the browser cancels is thrown away, nothing committed.

- Exact: yes

### Safe cut points show whether a cut leaves a whole thought, and Alt+S moves an edge or a pick to the nearest one

The safe-cut aid is aid 4 of the language aids.

- Between two timed words of the original: a cut may end there when nothing on the left waits for a word on the right, nothing the left needs went right (an object, a "that" clause, the rest of a name) and the left has a verb or a sentence root; a cut may start there when only a new clause hangs off the left and the right has its own verb. A sentence end is safe both ways; so is a gap with only fillers before it in its sentence, or only fillers after it. A gap that splits one word is unsafe ("This splits the word "<w>"").
- Drawn: a green tick when both ways are safe; a red tick only where a cut is tempting (a pause of 0.35 s or more, or punctuation in the gap) but would strand a clause; nothing for ordinary gaps inside a clause. A hollow green tick is safe for the words but has less than 0.12 s of silence (the cut will clip). Each tick has a reason, for example "A sentence ends here", "A whole thought ends here", "Cutting here strands a clause: "<w>" is left waiting for "<h>"", "There is no verb yet", "What follows has no verb of its own", "<h> loses its negation <w>". Without the language analysis there are no ticks. The ticks are hidden from screen readers and keep their colours in high-contrast mode.
- In a gap an out point goes a little after the left word (half the pause, at most 0.12 s), an in point a little before the right word (half the pause, at most 0.08 s). Edges are judged with up to 40 words (and 20 s) of the clip on either side.
- Dragging an edge (with aid 4 on) snaps to the safe gap nearest the edge within 2.5 s whose side fits it (an out edge needs "may end", an in edge "may start"), preferring a gap with a breath by 0.15 s.
- Alt+S (shortcut sheet: "Move the armed edge, or the picked words, to the nearest safe cut"), shown as a toast:
  - with words picked on the lane: moves both ends of the pick to safe boundaries inside its cut, each by the fewest words (up to 12; ties outward): "The pick now starts and ends where a cut leaves a whole thought." / "The pick already starts and ends at safe cuts." This works even when aid 4 is off;
  - else with an armed edge: moves it to the nearest safe cut within 6 s, one undo step: "The <in/out> point moved to the nearest safe cut. Ctrl+Z puts it back." / "No safer cut point near this edge (or its words are still being read)." (also when the nearest is under 0.02 s away). This works even when aid 4 is off;
  - neither: "Arm an edge (click near a cut’s end) or pick words first.".

- Exact: yes

#### Lessons

- Met: CE1-095, CE1-096, CE1-097, CE1-098, CE1-099, CE1-100, CE1-101, CE2-001, CE2-002, CE2-003, CE2-004, CE2-005, CE2-006, CE2-007, CE2-008, CE2-009, CE2-010, CE2-011, CE2-012, CE2-013, CE2-014, CE2-015, CE2-016, CE2-017, CE3-009, CE3-010, CE3-011, CE3-012, CE3-013, CE3-014, CE3-015, CE3-016, CE3-017, CE3-018, CE3-019, CE3-020.

## Selecting, deleting, inserting and keys

### The editor's keys work on any keyboard layout and stay out of the way while the editor is typing

Terms used by every key behaviour below: the cut list is the document being edited; its timeline is an ordered run of items, which are cuts (one piece of an interview clip, with a source in point and out point in seconds of that clip) and gaps (a stretch of silent timeline time with a length). Gaps behave like clips everywhere: they are selected, moved, deleted and resized like one. The shelf holds staged cuts, kept in the document but not on the timeline. The head is the playhead. The lane is the horizontal timeline strip docked at the top or the bottom of the editor; "the strip" means the lane's track area itself holding the keyboard (clicked or tabbed to). The keyboard is in one of three places: the lane (the default: the page body, the lane, the transport buttons), the cards list, or the transcript panel. A frame is 1 / the cut list's frame rate. The shortest cut and the shortest gap are both 1/24 s.

- Keys are matched by physical key position, so every binding holds on any keyboard layout. Ctrl and Cmd are the same modifier. A chord is written modifiers first, in the order Ctrl, Alt, Shift.
- A key is ignored entirely (it goes to the page) when the focus is in a text box, text area, select list, anything editable, or an input of any kind other than button, checkbox, radio, submit, reset, range, colour, file or image; while an input-method composition (for example typing Chinese) is in progress; and when another part of the page has already handled the key.
- A key can be limited to some keyboard places. When a key has a meaning for the current place and one for everywhere, the place's own meaning wins. A key marked "strip only" works only when the lane's track area has the keyboard; elsewhere that key is not taken at all.
- Holding a key down: only the keys listed as repeating fire again on the operating system's key repeat. A held key that is the editor's but does not repeat is still swallowed, so the page does not scroll (for example a held Space).
- A key that is the editor's but means nothing in the current situation (for example Escape with nothing selected or armed) is left for the rest of the page; its repeats are still swallowed.

A cut list that names no frame rate counts 29.97 frames a second, for every key and every edit alike.

Keys act only on the place that visibly has the keyboard, shown by a clear outline; while a window or a sheet covers the page, no key reaches anything behind it. Every key action has a key every laptop keyboard has (no action needs Insert alone) and a button on the game controller; on the controller, holding X adds a gap at the playhead. No shortcut uses F12 or any other key the browser keeps for itself.

- Exact: yes

### Letter keys work on any keyboard layout, and Cmd counts as Ctrl

{{29-064}}

- Exact: yes

### Space and Alt never trigger the browser or the last clicked button by accident, and a lost window focus ends every held key cleanly

{{28-002}}

Space always plays or stops, straight after any gesture made with Alt held.

- Windows and macOS: the lone-Alt guard is for Chrome on Windows, which otherwise hands the keyboard to its own menu.
- Exact: yes

### The lane's keys follow the editor's own keyboard layout in Resolve, where one exists

Where the editor's keyboard layout in the editing program can be read (Resolve's first keyboard preset), the editor's lane uses the same keys for the same commands: play toggle, play forward, stop, play reverse, step forward, step reverse, next clip, previous clip, timeline start, timeline end, first frame, last frame, nudge forward, nudge reverse, ripple trim start to playhead, ripple trim end to playhead, split clip, select clip at playhead, move clips up, move clips down, delete, backspace, mark in, mark out, reset in, reset out, add marker, clear marker, undo, select all clips after, trim mode, and Extend Edit. A command bound to several keys gets all of them (for example X and "." both nudge forward, by a second and by a frame). Only single keystrokes with Ctrl, Alt and Shift carry across; two-key chords, keys using the Windows or Command key, and function keys, Tab and Page Up are left to the editor's own keys and the browser. Arrow keys, Home, End, Delete, Backspace, Return and Space carry across. With no layout to read (no Resolve), the lane keeps its own keys, which are Resolve's defaults.

The lane's keys work the same whether Resolve is connected or not, and a layout once learned is kept across restarts.

- When the help for the editing program is off: the lane keeps its own keys and nothing about Resolve's layout is read or mentioned.
- Exact: yes

### Every button that has a key shows that key

{{28-019}}

- Exact: yes

### Buttons carry key hints only where the hint is the real key

{{29-006}}

- Phone and desk: on touch devices key hints and tooltips are hidden.
- Exact: yes

### The help sheet lists every key, grouped by where it works

The sheet's keyboard rows are grouped: "Anywhere" first, then "Lane (the clips have the keyboard)" for keys that work only on the lane. An action with keys in both places (split: B on the lane only, Ctrl+B anywhere) gets a row in each. The full sheet, in order: the "Anywhere" rows; two fixed rows "Ctrl+K: Search the cards" and "?: This list of shortcuts"; the lane-only rows; then the place-specific rows (the cards, trim mode, words picked on the lane, the transcript panel and its search, and "Tools and panels", below); then any key a feature added that no row names yet, under "Tools and panels". Then the controller rows (see Phone and game controller).

- Exact: yes

### A shortcuts sheet lists every key, grouped by where it applies

{{29-028}}

- Name and search words: the shortcuts sheet: shortcuts, keys, help, keyboard, controller.
- Ways in: "?", the Shortcuts buttons, the H key, the controller's Menu button.
- Exact: yes

### The help sheet's rows for the cards, trim mode and words picked on the lane

{{28-021}}

- Exact: yes

### The help sheet's "Tools and panels" rows

{{28-023}}

- When the assistant is off: the rows for the edit chat, the montage builder (Alt+M) and shortening (Alt+H) are not there, and those keys do nothing.
- When the help for the editing program is off: there is no Send to Resolve key or row.
- Exact: yes

### Single keys open the help sheet, search, the edit chat, notes, places and Send to Resolve

{{28-017}}

While words are selected in the transcript panel, the insert key inserts them wherever the keyboard is, so C never opens the edit chat then.

- When the assistant is off: C opens nothing.
- When the help for the editing program is off: Alt+Shift+M does nothing.
- Exact: yes

### Ctrl+K or Cmd+K puts the caret in the search box

{{29-004}}

- Exact: yes

### The keys for searching every transcript, the edit chat and Send to Resolve say so when their tool is not ready

The key for "search every transcript" opens search; the key for "ask the assistant" opens or closes the edit chat; the key for "Send to Resolve" sends. When the tool behind a key has not started, a warning toast says so:

| Key's job | Tool failed to start | Tool not started yet |
|---|---|---|
| Search every transcript | "Search did not start: <reason>" | "Search is not ready yet." |
| Ask the assistant | "The chat did not start: <reason>" | "The chat is not ready yet." |
| Send to Resolve | "Resolve did not start: <reason>" | "Send to Resolve is not ready yet." |

A Send that fails toasts its error message. Q or Enter on a focused card opens that cut's transcript in the transcript panel. Every key label that names the assistant says "the assistant".

- Exact: yes

### In the cards and the transcript, F goes to the card under the head, or turns follow on and off

F in the cards and in the transcript: a tap (released before 450 ms) scrolls the cards to the card under the head, once, opening it at every density. Held 450 ms, it turns "follow" on or off (with it on, the card being heard stays centred). The tap acts on release; the hold acts once when 450 ms is reached, and the release then does nothing. (On the lane, F splits at the head.)

- Exact: yes

### How a selection is replaced, added to, toggled and extended

{{28-064}}

Selection is one thing shared by the cards and the lane: selecting in either selects the same items in both and scrolls the lane to them. However a selection is made (a box, taps, a drag or a modified click), the keyboard focus lands inside it. An action applies to the selection only while the focused card is inside it; when the focused card is outside it, the action touches that one card and the selection clears. Flipping between the cards and the lane, either way and as often as the editor likes, lands on the same cut at the same place.

- Exact: yes

### The editor's selection survives an edit that reshapes a cut

A cut is known by its clip and its exact span, so the same cut list always shows the same cards, and two identical cuts are told apart by their order. When a trim or a split turns a cut into a new one, the selection stays on the same material.

### Mouse and keyboard on the cards select, open, re-order and move markers

{{29-023}}

While cards are dragged anywhere on the page, a silhouette of the card follows the pointer and the drop marker stays steady; the system's "no entry" cursor never appears, and a drag may start from blank space on the card. Cards in the list can always be dragged to a new place.

- Exact: yes

### Shift+Up and Shift+Down grow the selection, and Escape backs out

Shift+Up arrow (everywhere, repeating): extend the selection one item up (a range from the anchor to the new focus). Shift+Down arrow: one item down. Escape (everywhere): with an edge armed, the first press disarms it; otherwise, with items selected, it clears the selection; with neither, the key is left for the page. Escape never clears the in / out range. A drag in progress on the lane is dropped by Escape before this happens (see "Escape during a lane gesture throws it away").

- Exact: yes

### R and D move the selection up and down the cut list

{{28-014}}

- Exact: yes

### Move up and Move down shift the selected block one item

{{33-022}}

- Exact: yes

### A floating selection bar acts on several selected cuts

{{33-021}}

The bar never covers the first card, the transcript's text or the top line of a lane clip, including while text is being selected.

- Name and search words: the selection bar: selection, selected cuts, move up, copy, stage.
- Exact: yes

### Right-click on a lane clip, or More for the selection, opens the cut menu

Right-click on a clip in the lane (desk only; suppressed on touch) opens a menu for that cut, or for the whole selection when the clicked cut is in it. A right-click on a gap in the lane opens nothing. **More for the selection** opens the same menu for the selection, with **Move up one slot** (R) and **Move down one slot** (D) first. Menu title "This cut" or "N cuts". Items:

- **Copy** (Ctrl C), **Cut** (Ctrl X).
- **Paste N cuts after this cut / these cuts** (Ctrl V), only when something was copied in this window.
- **Send to** (see "Send to moves the selected cuts to the end of a chosen section").
- **Stage to** (page).
- **Save as sequence**.
- **Clip colour…** (Shift C).
- **Gain… (<current>)** (key hint Alt Shift ↑↓); the current gain is the first cut's, or "mixed".
- **Reset gain to 0 dB** (key hint Alt Shift 0), shown only when one of the cuts has a gain. Toast "Gain reset on N cuts."

- Name and search words: the cut menu: right-click, context menu, more actions, cut menu.
- Phone and desk: a right-click on the desk only.
- Exact: yes

### Delete and Backspace take out the in and out range at once, or delete the selection on a second press

Delete and Backspace (everywhere):

- When the strip itself has the keyboard and a valid in / out range exists (both ends set, at least one frame apart, the whole range inside one cut), the range is taken out of that cut at once, with no arming.
- Otherwise, press twice. The targets are the selected items, else the keyboard-focused item. The first press arms them: the screen shows which items with a red edge, a 3-second count and a toast. A second Delete or Backspace with exactly the same targets within 3000 ms deletes them. A press with different targets re-arms for those instead. After 3 s the arm lapses and the screen says it is off. Changing the selection alone does not disarm.
- Gaps are armed and deleted like cuts.
- With no targets at all, the delete is refused at once: "select a cut first".

A held key never confirms a delete: the second press must be a fresh one. The count stays shown through any redraw. Deleting cuts keeps every unselected gap beside them; only black with nothing after it goes. Every delete can be undone. Where the cut list is open read-only, the delete is refused at the first press.

- Phone and desk: on a phone, the delete control sits farthest from the resting thumb.
- Exact: yes

### Delete must be pressed twice, and the first press arms it with a countdown

{{29-026}}

A deleted cut leaves the cards and the lane and goes onto the staged shelf, labelled with the section it came from, keeping its words, its English, its colour and its note, ready to be put back. Every confirming message names where the edit will land.

- Exact: yes

### I and O mark an in and out range at the head, and Alt+I and Alt+O clear each end

{{28-012}}

- Exact: yes

### The in and out range belongs to this browser alone

{{28-067}}

- Exact: yes

### Shift+Insert or Shift+G puts a one-second gap at the head

Shift+Insert and Shift+G (everywhere): insert a 1 second gap at the head. Shift+G exists because laptops lack an Insert key. Where the gap goes and what follows is described with editing the cut list (see Editing, undo and the cut list).

A gap stays where it is when the items around it move, and can be selected, dragged to another boundary, resized, deleted and played as silence, each as one undo. A gap at the very end of the cut is refused.

- Exact: yes

### Shift+N writes the note on the selected gap or on the gap before the selected cut

{{33-039}}

- Exact: yes

### Words inside a clip can be picked, then deleted, highlighted, split at or moved to safe cuts

On the dock lane, in the selected clip, when it has timed words and is at least 40 px wide.

- Mouse: Alt+drag across the words (a plain press moves or selects the clip). Shift+click grows a pick already in that clip. Finger: press and hold 450 ms on the words (short vibration), then drag; moving 10 px before the hold is a pan; a short tap acts as a tap on the clip.
- Keyboard, with the clips focused: Shift+Left/Right starts a pick at the word under the playhead (or the first/last word) and grows or shrinks it a word at a time.
- A pick shows the spoken words with the picked ones washed and underlined, and a **word bar** over the pick: "N word(s) · N.N s", "Delete words" (Del), "Highlight"/"Unhighlight" (H), "Split here" (B, also Ctrl+B; disabled when the pick starts the clip), "To safe cuts" (when safer boundaries are offered), "Clear the pick" (Esc). On a phone the labels are shorter ("Delete", "Split", "Safe") and the bar sits at the foot.
- **Delete words** removes exactly those words as one edit (cut halfway through the pauses either side; a word with no length is widened to one frame; a frame is kept from an unpicked neighbour): "Deleted one word / N words (N.N s). Ctrl+Z puts them back."
- **Highlight** marks those words as the part that plays, joining touching highlights, or takes the highlight off if the words are inside one: "Highlighted: those words are the part that plays." / "Highlight taken off those words." Refused when the words are not yet in the card's text: "those words are not in the card's text yet, so they cannot be highlighted (the words are still being refreshed)".
- **Split here** splits the cut where the pick starts: "Split where the picked words start." Refused: "The pick starts the clip, so there is nothing to split there."
- **To safe cuts** moves both ends to the nearest safe boundaries; if already safe: "These words already start and end where a cut leaves a whole thought."
- A click on a word without dragging moves the playhead to that word and drops any pick.
- A pick is dropped when the selection moves to another item, when its cut is deleted, or when an edge move trims the picked words out; if the edges move and the words remain, the pick follows them.
- Without timed words, Shift+arrows on the clips say: "Select a clip first, then pick its words.", "Fetching this clip's word timings…", or "This clip has no word timings yet (no [word timings] or subtitles), so its words cannot be picked."

The sound is ramped at every new join that deleting or splitting words makes. A highlight shows on the card without any markup, stays on exactly the same words through every later trim, and on a card shown in English marks the original words it stands for.

- Phone and desk: a hold and a drag on a phone, Alt+drag with a mouse.
- Exact: yes

### Words chosen on another surface can be acted on by the lane, which says when it cannot

{{29-052}}

- Exact: yes

### In the edit view, keys move a blade through the words to split or remove them

{{29-035}}

- Exact: yes

### While the transcript has the keyboard, its own keys act on it and the lane's and cards' keys do not

These apply when the keyboard focus is inside the panel, a transcript is open, and no Ctrl/Alt/Meta is held (except where noted).

| Key | What it does |
|---|---|
| Space | tap or hold: plays and pauses the transcript as described with its own playback (see Playback and audio) |
| Enter | if there are find hits and the find (or a step) was the last thing used: next hit (Shift+Enter previous); else if paragraphs are picked or text is selected: insert at the lane head (Shift+Enter puts it on the shelf); else if there are hits: next/previous hit |
| A or Up arrow | previous sentence |
| Shift+A / Shift+Up | shrink the cursor selection by a sentence |
| S or Down arrow | next sentence |
| Shift+S / Shift+Down | grow the cursor selection by a sentence |
| Z | back to one sentence |
| X | switch the cursor's language between the original line and the English line, staying on the same paragraph; says "The cursor is on the <language> line: it inserts word for word." or "The cursor is on the English line: an English sentence inserts its whole paragraph unless it has its own timings." |
| E | the cursor to the paragraph under the lane head (if the head's cut is a clip of this transcript), else the cut the panel was opened on; the keyboard stays in the panel; else "the head is not on a cut of this transcript"; if that paragraph has no sentences in the cursor's language, it is only scrolled to |
| C (not auto-repeat) | insert the selection at the lane head |
| V | refuses: "This editor has one track, so nothing can be placed on top: C inserts at the head instead (the cuts after it move along)." |
| Q | back to the cards: focuses the last selected card, else the focusable card, else the first card |
| R, D, W, B, J, Delete, Backspace | do nothing in the panel (so the lane and cards do not act) |
| Alt+Left / Alt+Right | move the start of a single-paragraph English selection one word earlier/later (see The English a cut shows) |
| Alt+Shift+Left / Alt+Shift+Right | move its end |
| Enter or Space on a focused button | that button's click |

Typing in a text box in the panel never reaches the editor's keys.

- Exact: yes

### Esc unwinds the transcript panel one layer at a time, from anywhere

{{30-021}}

- Exact: yes

### An editor selects what to insert in four ways and the newest replaces the others

- Whole paragraphs (picks): the paragraph's Pick button toggles it; Shift+click the Pick button picks a range from the last picked paragraph; Ctrl+click (Cmd+click) anywhere on a paragraph toggles it; Shift+click anywhere on a paragraph picks the range from the last picked one; a click beside the words toggles it. Picking clears a text selection and the sentence cursor.
- Mouse text selection (a drag over the words, possibly across paragraphs and lines): nothing is read until the mouse button comes up; a drag that ends outside the words (over the bar below or above) selects to that edge; it drops the sentence cursor and, unless playing, the transcript playhead; it clears the picks. Its span is the timed words under the selected characters, so an insert takes exactly what the preview played.
- The sentence cursor (A/S, Shift+A/S, Z, X, E): the cursor's sentences become the selection, highlighted, scrolled into view when within 40 px of an edge. It replaces a mouse selection, the picks and the transcript playhead.
  - A sentence ends at 。！？!?…；; or a line break, or a full stop followed by a space or the end (not in 3.5 or a.m.), closing quotes and brackets staying with their sentence. A sentence longer than 64 characters is split again at a comma (，,、) once at least 24 characters have passed.
  - The cursor steps the original line where a paragraph has one (cursor language "original"), else its English; or English first (cursor language "English"). Paragraphs without an id are skipped.
  - It starts on the sentence holding the transcript playhead's word, else the head's paragraph, else the first paragraph in view; its language starts on the original line when that line has timings, else English.
  - With nothing to step: "this transcript has no sentences to step through".
- A controller selection (see Phone and game controller).
- Clear (button, key hint Esc) drops all of them.

- Exact: yes

### An action bar shows what is selected, why it cannot go in, and the insert and shelf buttons

{{30-023}}

- Phone and desk: on a phone the buttons stack and their key hints are hidden.
- Exact: yes

### An insert lands at the head, after the selected card or on the shelf as one undo step, and interviewer questions only go on the shelf

{{30-024}}

When only the whole paragraph could be placed, the message also gives that paragraph's length. Found material added to a cut that already exists goes after its last cut by default and leaves every existing cut and its order as they were.

- Exact: yes

### A passage is cut with twelve frames of handle each side, kept clear of neighbouring speech, and placed by a close match when it has no timing of its own

{{30-025}}

- Exact: yes

### Ctrl+C copies cuts, and the text form can be pasted anywhere

{{33-031}}

- Exact: yes

### Ctrl+X cuts cuts out of the cut and keeps them on the shelf

{{33-032}}

- Exact: yes

### Ctrl+V pastes copied cuts after the cut under the head, within one episode

{{33-033}}

- Exact: yes

### Copied cards are pasted into the cut with everything they carried

{{39-046}}

- Exact: yes

### The shelf's keys, and what Escape does there

{{33-034}}

- Exact: yes

#### Lessons

- Met: CE1-033, CE1-034, CE1-035, CE1-036, CE1-037, CE1-038, CE1-039, CE1-040, CE1-041, CE1-042, CE1-043, CE1-044, CE1-045, CE1-046, CE1-047, CE2-018, CE2-019, CE2-020, CE2-021, CE2-022, CE2-024, CE2-025, CE2-026, CE2-027, CE2-029, CE2-031.
- Not yet met by any behaviour above: CE1-049 (dropping media on the editor is written once, with the transcript panel's intake in part 3), CE1-048 (making a new cut list is written with opening episodes in part 5), CE2-028 (the panels' headers and the top bar are written with the page in part 5), CE2-030 (menus and settings sections are written with the page in part 5).
