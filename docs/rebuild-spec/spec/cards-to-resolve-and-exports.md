# Timeline Cards: the hand-over to Resolve, and exports

This is the last step of Timeline Cards, and the only one that knows about an editing program: the finished cut leaves Timeline Cards, either as a new timeline in DaVinci Resolve (the first editing program supported) or as a file any editing program reads (Final Cut Pro XML, OpenTimelineIO, a CMX3600 EDL) or as the script to read. What a person is promised here is that the cut arrives exactly, to the frame, with what the format can hold and a plain sentence for everything it cannot, and that changes made afterwards in Resolve or in another program can be brought back into the cut as one step that can be undone. It is used by whoever is cutting an episode in the Timeline Cards editor. Timeline Cards is one part a site can switch off: with it off, nobody but an admin sees it (in settings, with its switch), nothing is handed to Resolve, and nothing already made is deleted. With the help for the editing program switched off, nothing here mentions Resolve, and the exports and imports of files are the whole hand-over.

## Frames, frame rates and timecode

### A cut list states its timeline's facts and each clip's rate and start

A cut list carries, each on one line, the title, the name of the Resolve timeline it was last sent to, and when and on which computer it was last sent and last updated from a timeline. A title is trimmed. An empty line means none. A value that would run over more than one line is refused with "X is one line".

For each clip the cut list uses it records:

- a name that is not blank, has no spaces at either end, no colon and no line break, else "\"X\" cannot be a clip name in the frontmatter";
- a frame rate that is positive (or 0 for not known). Anything within 0.01 of 23.976, 29.97, 59.94 or 47.952 IS that broadcast rate (24000/1001, 30000/1001, 60000/1001, 48000/1001); anything else becomes the nearest fraction with a denominator of at most 1001;
- a start timecode, one plain word ("a start timecode is one plain word, like 01:00:00:00"); an empty one becomes 00:00:00:00;
- an id, one plain word or nothing ("a uid is one plain word, or null").

### Seconds and frames convert exactly at every frame rate

Every frame count is worked out from the exact rate, never from a rounded one: 29.97 is exactly 30000/1001, and so on for the other broadcast rates. Seconds become frames by rounding half up of seconds times the exact rate; frames become seconds by exact division. Frame counts, once known, are carried as frames and never worked out again from seconds, and a cut's out point stays current through every trim and split.

- A cut's source in and out are counted at the clip's own rate, with the out at least one frame after the in. The black before a cut is counted at the timeline's rate.
- Clips of a rate other than the timeline's are handled by converting and rounding to whole frames, and a cut list that mixes rates (29.97 clips on a 25 frames per second timeline, for example) gives exactly the frames worked out by hand.
- Frame rates anywhere strictly between 1 and 1000 frames per second are accepted. A rate is a decimal number (for example 29.97002997) plus whether it is drop-frame.

Facts about timecode, as Resolve counts it:

- A `;` in a timecode means drop-frame. Drop-frame exists only at 29.97 and 59.94. At 29.97 it skips 2 frame numbers each minute except every tenth minute; at 59.94 it skips 4. A cut list marked drop-frame at any other rate is treated as non-drop, with a note.
- A clip's start timecode is turned into nominal seconds, so 01:00:00;00 is exactly one hour even at 29.97, and transcript timing uses the same nominal seconds.
- A timecode that is not four fields means nothing. The timecode base is the timeline rate rounded.

### Which frame rate a clip is taken to have

The arithmetic for a cut needs its clip's real rate; a guessed rate once placed every clip of an episode at the wrong moment.

- On its own: a clip's rate is the one Resolve reports for it; else the one measured when the clip was transcribed; else the one the cut list records for it; else the timeline's rate. A clip of unknown rate is taken at the site's "Frame rate when nothing states one" (29.97 drop-frame unless an admin has changed it; see Timeline Cards: footage in, ready to cut: Frame rates, "Each interview's frame rate and drop-frame are chosen on its own"). The rate found is recorded on the cut list for each clip, and a cut list holding a rate that was only assumed is corrected from the measured one before anything is sent.
- By hand: each clip's rate and start timecode are shown in the cut list's facts and can be set there. A rate set by hand is never overwritten by a later measurement.

### A cut's in and out points sit 12 frames outside its words

When a cut is made from a stretch of transcript, it starts 12 frames before its first word and ends 12 frames after its last, but never reaches into the previous or next spoken word (pauses do not count as words), never before the clip's start and never past its end. A cut is always at least one frame.

- On its own: the 12-frame handles, the in and out points from the word timing, and the limits above.
- By hand: every in and out point can be trimmed in the editor, and a trimmed point is never moved again by the word timing.

### The timeline a cut builds runs at a chosen frame rate and start

A send offers the new timeline's frame rate before anything is built. The default is the rate the cut list states; a cut list that states none is sent at 29.97 drop-frame. The person can instead keep the Resolve project's own rate. The rate is set while the new timeline is still empty, because a fact about Resolve is that a timeline's frame rate can be set only while it holds nothing. The timeline starts at the cut list's start timecode, 01:00:00:00 when it names none; a start that cannot be read is taken as 01:00:00:00, with a note. The dry run says "-- timeline pinned to X fps" when a rate other than the project's is set.

- On its own: the rate and start, from the cut list, else 29.97 drop-frame at 01:00:00:00.
- By hand: the rate, or the Resolve project's own, is chosen for each send on the Send tab.

#### Lessons

- Met: CRX-001, CRX-003, CRX-005, CRX-006, CRX-007, CRX-009, CRX-010, CRX-011, CRX-012, CRX-013, CRX-014, CRX-015.

## Placing, deleting and linking clips in Resolve

### The clips in the Resolve project are known before a hand-over

While Resolve runs on the editor's computer with a project open, Timeline Cards knows which clips that project's media pool holds, by their exact names, within about two minutes, and at once on request ("Check again" on the Send tab). Every multicam clip in a media pool bin named `Multicams` (and the bins inside it) is known within about a minute. So the dry run can say, for every clip of the cut, whether it is already in the project or will be brought in first. A fact about Resolve: it writes its own transcriptions into the project only when the project is saved.

### A clip is found in Resolve by its exact name and never by guessing

Each cut names its clip, and the clip is looked for in the target project's media pool by exactly that name (or by the clip's unique id where the cut list holds it), never by a shortened display name. When a clip has been renamed, a short list of old name to new name (letter case ignored), kept in the cut list's folder, the folder above it, or the episode's documents folder, is used. A clip known only from the episode's transcripts and not in Resolve never counts as found.

- Only media of the target Resolve project is used; a clip or timeline of another project is never taken. Where the project holds both the original file and a re-wrap or subclip of it, the original is used.
- A fact about Resolve: it allows two clips of the same name in different bins. Same-named clips in different bins are reported as ambiguous, naming both bins, and never silently treated as one.
- The dry run reports how each clip was found: in the project, through the rename list, or to be brought in.
- By hand: the rename list is a plain file a person can edit, and the person can bring a clip into the project themselves.

### Clips the project lacks are brought into it before the cut is placed

For every clip of the cut that the project's media pool does not hold, the hand-over brings it into the project first, instead of refusing: the file the clip's transcript was made from, as the editor's computer sees it, is imported and matched back by file name. An interview whose multicam is not yet in the project gets it, made from the angles and the line-up Timeline Cards made when the footage came in (see Timeline Cards: footage in, ready to cut: Grouping clips and building the multicam), with the angle names and sync of that line-up, and placed in the `Multicams` bin. A fact about Resolve: its scripting cannot create a multicam clip, so the multicam arrives by a way that never relies on a scripted multicam creation; where no such way exists for a multicam, the dry run names exactly the step the person takes in Resolve to make it before sending, and the send never claims to have made it.

- A multicam that arrives is read back before any cut is placed: each angle's item count on its picture and sound tracks matches the line-up, and each item's source start is within one frame of the line-up's. An angle that is further out than one frame refuses the send, naming the interview and the angle that is out of sync, and nothing is placed. Where Resolve cannot report an item's source start, the person is told that this item was not checked, by name.
- When the multicam cannot be made, the send is refused before anything is placed, and the person is told in a sentence naming the interview what stood in the way: no project open in Resolve, a multicam of that name already in the `Multicams` bin, Resolve refusing the clip, a dialog open in Resolve, or the multicam arriving under another name that Resolve would not let be corrected.
- A multicam made here wears its interviewee's clip colour in Resolve from the moment it is made, read back like every property (see "Every name and property written into Resolve is read back"). Multicams already in the project are recoloured only by the action that asks first (see "An episode's multicams and a timeline's cuts can be coloured by speaker in Resolve").

The dry run says "-- importing N clip(s) from the corpus first". A send is refused only for a clip that is neither in the project nor has a file the editor's computer can reach, and then every such clip is named at once (see "A send is refused before anything is placed when it cannot succeed").

### Each cut lands as a linked picture and sound pair on the first tracks

Each cut's picture goes on video track 1 and its sound on audio track 1, linked to each other as a hand edit would link them, whichever destination tracks the editor has switched on in Resolve. A placement counts only once it has been read back: its start, its length and its source span, picture and sound both present. Cuts laid end to end butt-join with no gap and no frame lost; each starts at the read-back end of the item before it, and its placed length matches its clip's real rate within 0.04 seconds. A cut's in-point is rounded to the nearest frame and its out-point is the in-point plus its length, so a cut nobody touched never reads as trimmed by a frame. A timeline made from a cut holds exactly one clip per card, in the cut's order, and nothing else.

Every timeline the product creates or changes has each picture and sound link recorded on both sides, and this is checked after creation.

Facts about Resolve behind these promises:

- Its scripted append treats the end frame as exclusive.
- It reports a clip's source frames slightly wrong.
- A mixed-rate clip lands at a length Resolve decides, and a clip of another frame rate is speed-conformed by Resolve when inserted.
- Its set-marks call counts from the timeline's start, not from zero, so every conversion between item positions and those calls subtracts the timeline's start frame.
- With no track named, its append follows the destination-track buttons; naming a media type means placing picture and sound separately and linking them.
- An append to a track that does not exist reports success, and a clip appended to a chosen track gets no linked sound.
- A timeline whose picture and sound links are recorded on one side only crashes Resolve when it is opened.
- Its scripting cannot build a timeline from a transcript, so cuts made from word timings are placed one by one, and each placement is checked.
- Its scripted append lands on whichever timeline is current, while its scripted delete acts on the timeline it names. So before each placement the new timeline is confirmed to be the current one; if it is not, the send stops, the new timeline is removed and the person is told.
- Its scripting cannot move a clip, insert in the middle of a timeline, or announce that anything changed, and nothing in its scripting or its shortcuts can insert empty time. Gaps therefore exist only in timelines the product builds whole, from the start.
- Its select-at-playhead and split act on every track whose auto-select is on, and its scripted delete leaves a clip's linked sound behind on the timeline.

### A new cut shows the multicam's angle and arrives ungraded

Cuts are built from each interviewee's multicam where one exists, and from ordinary single clips otherwise. A multicam cut shows the angle the multicam clip shows in that project; the cut list does not choose the angle. A new cut arrives with no colour grade, no effects, no Fusion composition and no markers of its own; only the audio fades and gain the cut carries are put on (see "Audio fades and gain arrive in Resolve as set on the cards").

### What the hand-over understands in a Resolve timeline

- Cuts are read from video track 1 and placed on video track 1, with their sound on audio track 1. Cuts on any other track are not read, even when video track 1 is empty.
- Transitions are neither read nor written. A speed change on a clip is only noticed, never set.
- Fades are audio only, in whole frames.
- Grades and effects stay on cuts that are kept, moved or trimmed, and are absent on every new cut.
- Only timeline markers are handled; a marker's hidden custom data is not carried.
- A multicam or graded timeline is never rebuilt by exporting it and importing it again, because a fact about Resolve is that such a round trip damages multicam edits. Any timeline the product changes keeps every track, angle, link, colour, marker, subtitle and grade it does not mean to change.
- Where something in a timeline is not understood, the person is told in a sentence what it was; it is never skipped silently.
- Pending: cards-to-resolve-and-exports-U2

### A sent timeline is followed by its identity, not its name

A fact about Resolve: a timeline clip gets a new id on every ripple move, and a timeline rebuilt by duplicating and renaming has a new id. So what the product remembers about a cut (its notes, colours and marks) follows the cut's clip and source span, surviving ripple moves, project copies and other computers. The timeline a cut list was sent to is followed by its unique id in Resolve, so renaming it in Resolve loses nothing. When that timeline is duplicated or rebuilt and the id is gone, the product looks for it by name and says plainly that it lost track of the timeline it built and which one it is now comparing with, or that it found none.

#### Lessons

- Met: CRX-016, CRX-017, CRX-019, CRX-020, CRX-023, CRX-024, CRX-025, CRX-026, CRX-027, CRX-030, CRX-032, CRX-033, CRX-034.

## Undo, markers, titles, fades and properties

### Sections and notes arrive as markers

Every heading and note of the cut arrives on the new timeline as a timeline marker, one frame long:

- A section heading becomes a marker named after the heading, in the section's own colour (Blue when it has none). A section of any colour, Red and Green included, is sent in its own colour.
- A note heading becomes a Green marker, and each note line a Green marker carrying its text as its note; an unmatched note line has "(unmatched) " in front.
- A plain heading becomes a Red marker named after the heading.
- Each is placed at the start of the black before the next cut, so a section that opens on black is marked at the black. Markers that belong to a cut go on that cut's first frame. Extra timeline markers go on their own frames.
- Marker colours are matched ignoring case; an unknown colour becomes Blue.
- Read back from Resolve, a marker the cut list knows keeps the kind the cut list holds for it, whatever its colour. Only a marker the cut list does not know takes its kind from its colour: Green is a note, Red a plain heading, and every other colour a section.
- A fact about Resolve: it keeps one marker per frame and silently refuses a second. So a marker that would share a frame moves to the next free frame, and none is lost.
- Placing a marker moves no clip and changes nothing on any track.

The finished send says how many markers went on and how many moved to a free frame.

### A note on a gap arrives as on-screen text over the gap

Every gap of the cut that has a note arrives in Resolve as on-screen text showing that note. The note is taken fresh from what is saved at the moment of sending (the page's copy is not used); a note that cannot be read is skipped, said, and the send carries on. A gap note never makes a send fail. Notes on several gaps in a row before the same cut are joined with " · ".

- A gap of 5 seconds or more (Resolve's default title length) gets a Text+ title. A new video track named "Gap notes" is added above every other track, and over each such gap, exactly from its first frame to its last and moving nothing else, sits a title showing the note (wrapped at 34 characters a line, small text), named "Gap note - <note>" (at most 80 characters). If Resolve holds the title to a shorter length it is repeated to fill the gap (up to 64 pieces). The titles are kept in a media pool bin called "Gap notes", and the bin that was current before is made current again. Gap text never overlaps picture, no clip moves, and every track lock is put back as it was. If anything on the other tracks moved: "the picture on <track> is not where it was before the titles: check the timeline".
- A shorter gap, or a title that does not land exactly inside its gap (it is then removed without ripple), gets a Green duration marker spanning the gap instead, named with the note's text (runs of spaces collapsed), its note reading "Gap note from Timeline Cards (N.N s). Not a title because <reason>". Green is used because a marker read back from Resolve in Green is a note, never a section. Gap-note markers are placed after every other marker, so other markers never move for them; one whose first frame is taken starts at the next free frame and is shortened to end where its gap ends. None is lost.

The finished send says "N gap note(s): X as title(s) on the Gap notes track, Y as marker(s)" with the count for each reason, plus ". WARNING: ..." for each warning.

### Clip colours on a sent timeline

Each cut on the new timeline gets its clip colour: its own colour from the cut list, else its interviewee's colour. A colour set on a cut in the cards appears on that clip in the timeline Resolve receives, and is read back.

There is one set of colours: a cut's colour and an interviewee's colour are already Resolve's own clip colours (see Timeline Cards: the editor: Colours, "Each interviewee has a colour of their own"), and each is sent as it is, with nothing translated or paired. Resolve's Brown is never used anywhere. Any colour picker offers Resolve's 16 clip colours minus Brown, in Resolve's own menu order: Orange, Apricot, Yellow, Lime, Olive, Green, Teal, Navy, Blue, Purple, Violet, Pink, Tan, Beige, Chocolate. A cut naming a colour that is not one of these is refused before anything is built, naming the cut.

- Pending: cards-to-resolve-and-exports-U1

### An episode's multicams and a timeline's cuts can be coloured by speaker in Resolve

For a chosen bin (default: the bin open in Resolve), each multicam clip is matched to its interviewee and listed as "already <colour>" or "would set <colour> (now <colour>)". Nothing changes until the person confirms; then each shows "set" or "FAILED to set". A clip with no matching interviewee still gets a steady colour of its own, and the person is told which clips had no interviewee. Optionally the cuts on video track 1 of the timeline open in Resolve are brought to their speaker's colour too, only those that differ, each change one undo step in Resolve. Without Resolve, every interviewee's colour can still be seen. Refusals: "no project is open in Resolve", "no multicam clips in bin '<name>'", "no timeline is open in Resolve".

- Who: anyone signed in, on Resolve on a computer signed in to their own account.
- When the help for the editing program is off: this action is not offered.

### Audio fades and gain arrive in Resolve as set on the cards

Each cut's audio fade-in and fade-out arrive on its sound in Resolve at the lengths drawn on the cards and heard in the browser, in whole timeline frames (rounded), never negative, each shortened to the cut's own length if longer; zero means no fade. The picture is never faded. Each cut's manual gain (in steps of 0.1 dB, at most 30 dB up or down) arrives as that clip's level in Resolve, and is proven by reading the level back.

The fade sentence and the gain sentence of a send say how many cuts carry fades and a manual gain that go on with them. A fade or a level Resolve would not take is told, naming the cut, in the read-back sentence of "Every name and property written into Resolve is read back". An export to a format that has no clip gain or no fades says so in its own list of what the file does not carry (see "Each export format carries some of the cut and says what it lost"). The editor's automatic levelling is its own playback only, and every send says so.

### Every name and property written into Resolve is read back

A fact about Resolve: it silently refuses some property writes. Every name, colour, marker, rate or other property the product sets in Resolve is read back, and a refusal is shown to the person in a sentence naming what Resolve would not take. A fact about Resolve: it inserts a title only at the playhead, at a default length of 5 seconds; any title the product places is checked for its track, start and length afterwards, and removed without ripple when it is wrong.

### A hand-over can be taken back

A send changes nothing that was already in the project: it adds one timeline, and the clips it had to bring in. The record of every send is kept for good: when, on which computer, the project, the timeline it built, and the clips it brought in. From that record, a send can be taken back: its timeline is removed from the project, and the person is told which clips it brought in, which stay in the media pool. Taking back is refused, with the reason, when that timeline is used as a clip on another timeline, or when it has been changed in Resolve since it was built (the person deletes it in Resolve themselves if they mean to lose that work). If the timeline is already gone, it says so and carries on.

A fact about Resolve: its undo history is project-wide and counts every scripted change. A send costs a known small number of undo steps there, and nothing the product does ever undoes the editor's own work in Resolve.

- Who: the person who sent it, or an admin.
- Ways in: from the Send tab after a send, and from the cut list's record of the timeline it was sent as.

#### Lessons

- Met: CRX-035, CRX-037, CRX-038, CRX-039, CRX-040, CRX-041, CRX-042, CRX-043, CRX-044.

## Talking to Resolve: restarts, dialogs and speed

### Timeline Cards never connects to Resolve while Resolve is still starting

Timeline Cards talks to Resolve only when Resolve has finished starting, by the one rule every part of the product keeps (see Resolve on the editor's computer: Connecting to Resolve's scripting: launch, stalls and death, "The product never harms a Resolve session", and the facts behind it in "Facts about Resolve's scripting connection"). While Resolve is starting, the editor shows "Resolve is starting: waiting before connecting". This is a waiting state, not a failure, and it does not count towards giving up.

### Resolve showing a dialog answers nothing

A fact about Resolve: while it shows a dialog (a message box, a transcription in progress) it answers no scripted call at all, and every call returns nothing; the sign of it is that Resolve stops reporting which page it is on. A call that returns nothing is treated as a possible blocking dialog, and the person is told so in a sentence naming it (see "A send is refused before anything is placed when it cannot succeed"). An editor's own transcription in Resolve is never cancelled by the product.

### A link to Resolve is fresh after every restart

A fact about Resolve: a reference to a clip works only on the connection that fetched it, and references taken before Resolve restarted silently place nothing. So clips are fetched and placed on the same connection, a reference never outlives a restart of Resolve, and an append that returns nothing counts as a failure. Within seconds of Resolve reopening a timeline, even an unchanged one, Timeline Cards shows it again, with nothing restarted by hand.

### Only one program drives Resolve on a computer

There is never more than one connection to Resolve per computer on Timeline Cards' behalf. A second is refused, naming the one already running; a process list that cannot be read counts as one running; a start that fails leaves nothing running. A stop, of one computer or of the whole studio, lets an edit in Resolve that is in progress finish before it takes effect, so no edit is ever cut off halfway. Nothing the product installs ever intercepts keys the editor types into Resolve or any other program.

### Resolve keeps up at any length of timeline

- Reading a Resolve timeline of up to 500 cuts for the comparison takes under a second and never stalls the editor's own clicks in Resolve.
- A click on a card moves Resolve's playhead within half a second on several hundred cuts, even while other programs talk to Resolve.
- Building a timeline or changing several hundred items at once shows its progress as it goes and finishes in minutes.

### Facts about Resolve's windows and pictures

- A picture of a Resolve window taken while it is behind other windows shows its viewers black, so a check of what a viewer shows brings Resolve to the front first.
- A still grabbed from Resolve can come out all black while Resolve reports success, so wherever the product checks a picture from Resolve, it renders a single frame at the item's midpoint instead.
- Resolve's menus write their trailing dots as one ellipsis character.

#### Lessons

- Met: CRX-045, CRX-046, CRX-047, CRX-048, CRX-049, CRX-050, CRX-051, CRX-052, CRX-053, CRX-054, CRX-055, CRX-056, CRX-057.

## Sending a cut to Resolve

### The Resolve and exports dialog

The editor has one dialog for sending to Resolve, exporting, importing and following Resolve.

- Exact: yes
- When the help for the editing program is off: the dialog is titled "Exports" and has two tabs, "Export" and "Import"; the Import tab offers files only, and nothing in it names Resolve.

{{32-001}}

### Where the dialog and the script downloads are reached

- Toolbar button "Export" (download icon, tooltip "Resolve and exports: export, import, send, follow"): opens the dialog on the Export tab, or closes it if it is open.
- Sending is an action on the cut, not a button in the top bar: the cut's own actions hold "Send to Resolve", which opens the Send tab with a fresh dry run. The Send to Resolve key, Alt+Shift+M, does the same. When the dialog later closes after a successful send, a toast says "Sent to Resolve."; when it closes without a send, nothing is said; a failure toasts "Send to Resolve failed: <reason>".
- Command palette entries: "Send to Resolve" (found also by the words conform, timeline, library); "Export OTIO, FCPXML, EDL or the script" (opens Export); "Download the script as Markdown (.md)" (shows Ctrl+S); "Download the script as plain text (.txt)" (shows Ctrl+Shift+S); "Import a timeline from Resolve" (opens Import); "Follow Resolve's playhead" (opens Live); "Compare the cut list with its Resolve timeline" (compares now and opens Import).
- Ctrl+S downloads the plain script as Markdown, from anywhere, including while typing in a text field; the browser's own "save page" is suppressed.
- Ctrl+Shift+S downloads the plain script as plain text, same rules.
- Exact: yes
- When the help for the editing program is off: Alt+Shift+M does nothing; the "Send to Resolve", "Import a timeline from Resolve", "Follow Resolve's playhead" and "Compare the cut list with its Resolve timeline" entries are not offered, and the Export button's tooltip reads "Exports: export, import"; the export entries and both script keys work as above.

### What is asked of the editor before a hand-over

A cut is handed to DaVinci Resolve running on the sender's own computer, with the cut list's Resolve project open in it. That is all that is asked: no timeline needs to be open, and the project may hold no timeline at all; only its clips matter, and missing ones are brought in. Nothing in Resolve is closed or reopened: the new timeline appears in the open project at once.

A cut sent to Resolve reaches only a computer signed in to the sender's own account, never another person's. When the sender has more than one such computer with Resolve running, the Send tab names each and the sender picks one.

A send is refused at the press, before anything is built, with a sentence giving Resolve's state, when Resolve on that computer is closed, starting, unreachable, or has another project open: "<machine>: Resolve is not reachable"; "Resolve is starting: waiting before connecting"; "Resolve has '<a>' open, not '<b>'"; "no project is open in Resolve". A send never waits on a Resolve that is not there.

Nothing is ever written into Resolve's saved projects from outside Resolve. Facts about Resolve behind this: it does not re-read its project library while it has a project open, and silently overwrites anything written underneath it; and a project written from outside Resolve can be left with picture and sound linked on one side only, which crashes Resolve when that timeline is opened (one such write into a real episode left 63 half-linked clips). Reading a saved project, which changes nothing, is allowed at any time (see "The saved project is read when Resolve is closed").

- Who: anyone signed in who may open the cut list, on Resolve on a computer signed in to their own account.
- When the help for the editing program is off: there is no hand-over to Resolve; the cut leaves Timeline Cards as an export.

### The Send tab shows a dry run and sends on one press

- Lead text: the cut goes to Resolve as a new timeline; first a dry run; nothing is written until Send is pressed.
- "Timeline name" text field, pre-filled with the cut list's file name (trimmed, at most 200 characters). Typing in it throws away the current dry run and any "sent" result. Enter in the field runs the dry run.
- A choice of the new timeline's frame rate: the rate the cut list states (29.97 drop-frame when it states none), or the Resolve project's own (see "The timeline a cut builds runs at a chosen frame rate and start"). Changing it throws away the current dry run, as the name does.
- "Check the plan" / "Check again" button (shows "Checking" while busy) runs the dry run. Opening the Send tab with no dry run yet starts one by itself.
- After a dry run that succeeded, five figures: cuts, clips, running time (m:ss), markers, gaps.
- Below the figures: every reason a write would be refused as a warning line, then every note as an info line.
- A heading "Since the last send: in step" or "Since the last send: <summary>", with the list of differences (first 60 lines) when the Resolve timeline the cut list names differs from it.
- An expander "The conform table, cut by cut" with the full plan: for each cut its number, clip, person, start, duration, gap, colour, and how the clip was found.
- A refused plan shows the refusal sentence as an error ("The conform was refused." if none was given).
- Footer line saying why the primary button is or is not available: "Check the plan first.", "The conform is refused: nothing can be sent.", "Sent.", or "Writes <n> cuts into <project> in Resolve on <machine>."
- Red primary "Send to Resolve" (shows "Sending" while busy): enabled only when the dry run succeeded, Resolve is reachable with the project open, and nothing has been sent yet in this opening of the dialog.
- On success the cut list records, as one edit, the timeline it was sent as and when ("<local time> on <machine>"); the tab shows "Built <name> (<timeline>): <n> cuts. <notes>"; the news line "Built <name> in Resolve: <n> cut(s)." with " The cut list could not record it." appended when that edit was refused. When the dialog was opened from the cut's "Send to Resolve" action the toast is left to that action ("Sent to Resolve."); otherwise this news is toasted.
- On failure: "Send to Resolve failed: <reason>" as an error toast and in the tab.

Nothing is built in Resolve until the person has seen the dry run's cut, marker and length counts and pressed Send. What is sent is the editor's saved cut, never the assistant's candidate pool or a board's arrangement. A send that has started always finishes even if the page is closed; a dry run is abandoned when the page goes away. A send gives up after two minutes of waiting for Resolve, and the person then sees "Send to Resolve failed: <reason>".

- Exact: yes

### The dry run counts everything and shows the plan cut by cut

The dry run writes nothing. Its summary reads "N cut(s) of N clip(s), N marker(s), X.X min -- into Resolve on <machine> as '<name>' | -- but <why>", with the import, gap-note, pinned-rate and bin clauses where they apply. Its counts: cuts, markers, notes, unmatched lines, alternates (saved sequences not counted), clip names, gaps and how many have notes, total black, cuts with fades, cuts with a manual gain, total length and duration, rate, start timecode, drop-frame, timing kind, and how each clip was found.

Its plan has one line per cut (number, clip to 30 characters, source in and out as the clip's own timecode, timeline timecode, length in seconds, colour, person), with a "(gap)" line before each gap (timecode, length, note to 40 characters), a totals line "N cut(s) of N clip(s), N gap(s) (X.Xs), N marker(s): N frames = X.X min at X fps [drop]", and, where they apply: the fade sentence, the gain sentence, the gap-note sentence, "N alternate(s) and N unmatched card(s) are NOT in the cut (they stay in the file)", "clips resolved: N by name, N by the rename list, N to be imported", and for a cut list timed from subtitles "timing: srt -- the spans were cut at .srt cue granularity; they conform frame-exactly as written". Every unmatched card is listed by name.

- Exact: yes

### The dry run names every reason a send would be refused

Each of these makes a send impossible and is shown on the dry run:

- "this file does not say which Resolve project it belongs to (`project:` in the frontmatter)".
- "no project named <p> in Resolve on <machine>".

Notes, which do not stop the plan:

- "gap notes not read: <error>".
- a note about clip gain when the plan carries gains.

When Resolve is not reachable, the plan is drawn from the cut list's own record of its clips, which is enough to show a plan but never to send, and the footer says what Resolve's state is. When the timeline the cut list names is in the project, the differences against it are worked out and shown. A name that is already taken is never a refusal: the timeline is given the next free name (see "A sent cut arrives as a new timeline that matches it frame for frame").

- Exact: yes

### A sent cut arrives as a new timeline that matches it frame for frame

Nothing already in the project is changed. What arrives:

- a new timeline with the asked name (default: the cut list's timeline name, else its title, else its project, else its file name), so it is always named after its own cut, never a leftover default. A fact about Resolve: it refuses a timeline name that is taken with a bare "Failed to create timeline", so when the name is taken the timeline is made as "<name> (2)", "(3)" and so on up to 99, and the cut list records the name actually built;
- the timeline's settings are the project's own, except its frame rate and start (see "The timeline a cut builds runs at a chosen frame rate and start");
- cuts laid end to end from the timeline's start, each with the black before it as a gap of exactly its length, each occupying exactly its span of the source, on exactly the frames shown in the editor, on the clip's own frame grid. No screen calls a trim approximate;
- each cut's picture on video track 1 and its sound on audio track 1, linked;
- each cut's clip colour, audio fades and gain;
- the sections and notes as markers, and each gap note as on-screen text over its gap (see "A note on a gap arrives as on-screen text over the gap");
- one clip per card, in the cut's order, and nothing else.

A timeline built from a cut runs the cut list's length, give or take a frame per clip. Sending a cut list that is identical to the timeline it names writes nothing and says so, and cuts nobody touched keep their exact frames.

- Who: anyone signed in who may open the cut list.
- Ways in: from the Send tab of the editor's dialog, opened from the cut's own actions, the Send to Resolve key (Alt+Shift+M) or the command palette.

### A send is refused before anything is placed when it cannot succeed

Every check runs before anything is placed, and a refusal places nothing. Messages:

- "the new timeline needs a name"; "nothing to conform -- the draft is empty"; "this project file has no cuts in the cut -- nothing to conform"; "this draft has not finished loading yet"
- Resolve showing a dialog: "Resolve is showing a dialog (a message box, a transcription in progress...) and answers no edit until it is closed -- close it and conform again".
- every clip that is neither in the media pool nor can be brought in, all at once: "these clip(s) are not in the media pool, so the conform is refused -- ... : <names>", with whose media pool was searched and when: " (the media pool of <machine>'s Resolve, walked HH:MM:SS | not yet)"; a clip still unknown after importing: "clip <person or id> is not in the bin scan yet"
- several projects of the same name: refused, "refusing to guess which".
- "could not create timeline '<name>' (is the name taken?)"
- importing: "importing N clip(s) failed: <error>"; "<file> did not import -- nothing was placed"
- "none of the N cut(s) landed on the new timeline (removed it) -- ..."
- "the cut list and the conform list disagree (N cuts, N bullets) -- this is a bug"
- "an edit is already being applied -- wait a moment"
- per cut, numbered from 1 and naming the person speaking: no usable source frames, an empty span (start not before end), a start before the clip begins, an end past the end of the clip, an unknown clip colour, a fade that is not a number or is negative.

- Exact: yes

### A send lands whole or not at all

The whole timeline is read back before the send counts: its name, rate and start, the number of cuts, each cut's place, length, source start and clip, every picture still linked to its sound both ways with the same place and length, the cuts' order, no two cuts overlapping, and the marker count. A send reports done only when picture, sound and markers are all placed. Any disagreement removes the new timeline, puts back the bin and timeline the editor had current in Resolve, and tells the person "did not read back as planned, so nothing was written", with the first eight problems and how many more, naming each cut that did not land and each that landed without its sound. No partial timeline is ever left, and no empty one. While Resolve is idle the send's status stays steady.

### The editor is told exactly what arrived

When the send starts, the page answers at once "N cut(s) sent to <machine>: Resolve is building '<name>' - N gap note(s) go on as titles where one fits the gap, else as markers - <fade sentence> - <gain sentence>", and when it finishes: "conformed N cut(s) onto the new timeline '<name>' in X.Xs -- N marker(s) carried over (N moved to a free frame) -- N gap note(s): X as title(s) on the Gap notes track, Y as marker(s) -- N clip(s) imported first -- <fade sentence> -- <gain sentence>", followed by " -- <file> stamped with '<name>' (rev N)" or " -- but the file could not be stamped: <error>". The person is also told the new timeline's length in frames and seconds and how many cuts were recoloured.

- Exact: yes

### The cut list records the timeline it built

After a successful send the cut list is re-read, its timeline name set to the name Resolve actually gave the timeline (which may be "<name> (2)"), with the time of the send and the computer it was sent on, its revision raised by one and the previous revision kept in its history. The page then shows the stamped cut list. This timeline is the one later compared with the cut list.

A send from a cut list opened read-only builds its timeline and leaves the file as it was: nothing is stamped, and the news line ends " The cut list could not record it." Later comparisons then find that timeline by its name (see "A sent timeline is followed by its identity, not its name").

### Every sent timeline goes into the Timelines bin

A fact about Resolve: a new timeline is filed in whatever bin the editor last clicked. Each send puts its new timeline in a bin at the root of the media pool named `Timelines`, created if missing, and the bin the editor had current in Resolve is made current again afterwards. The dry run says "-- into the Timelines bin".

### What each gap note will become can be seen before sending

The Gap notes panel has a section "What the conform builds": "When this cut list is conformed into Resolve, each note becomes a Text+ title on its own Gap notes track, exactly inside its gap, or a Green marker spanning the gap where the gap is too short for a title." **Show what the conform builds** (busy "Working it out"; afterwards "Work it out again") works it out without writing anything or calling Resolve, at the cut list's own frame rate. Result: a summary sentence, then one row per noted gap: "Cut <n> · <timecode in> to <timecode out> · <seconds> s", the note, and chips: "Text+ title on <track name>" (a gap of at least 5 s); "Green marker spanning the gap" (gold, shorter than 5 s), with the footnote "A gap under 5 s is too short for a title, so it gets the Green marker."; a chip saying the marker starts 1 frame in (a section starts there); and a chip "starts at frame <n>" when the gap's first frames are all taken. With no notes: "No gap has a note, so the conform builds no titles or markers for gaps (N gaps in the cut)." Failure: "The conform plan could not be worked out: <reason>".

- Exact: yes
- When the help for the editing program is off: this section is not shown.

### Where Resolve's projects are kept is set once for the site

So that a cut list can be compared with its timeline while Resolve is closed or the editor's computer is asleep, the product needs to know where the studio's Resolve project library is.

- Setting: Resolve project library. Does: says where the studio's Resolve projects are kept and how to sign in to read them, so a cut can be compared with its Resolve timeline when no Resolve is running; with none set, the comparison needs Resolve running. Default: none. Who: an admin. Applies to: the site. Search words: resolve library, project database, compare, timeline.
- Setting: Resolve project for cut lists that name none. Does: the Resolve project a send and a comparison use when a cut list does not name its own. Default: none. Who: an admin. Applies to: the site. Search words: default project, resolve project, send, conform.

#### Lessons

- Met: CRX-058, CRX-059, CRX-060, CRX-061, CRX-062, CRX-063, CRX-064, CRX-065, CRX-066, CRX-067, CRX-068, CRX-069, CRX-070, CRX-071, CRX-072, CRX-073.

## Edits sent live and staged edits

### A cut list being edited never changes Resolve until it is sent

- Exact: yes

While a cut list is open, the computer with Resolve is used only to know its clips, to say what Resolve has open there (project and timeline, shown in the header, or nothing while Resolve is closed or starting), whether Resolve is reachable, its keyboard preset for the lane keys, and the timeline the cut list was last sent to (for the comparison, never shown as cards). Its playhead is used only by the Live tab. Only sending goes to that computer; anything else is refused: "a project file is edited in the file, not in Resolve -- the '<kind>' was not sent to the agent". Resolve's later changes reach the cut list only through the comparison and the Import tab.

## Bringing Resolve's changes back into the cut

### A header chip says whether the Resolve timeline still matches the cut list

- Exact: yes
- When the help for the editing program is off: there is no chip.

{{32-007}}

### The Import tab says how the Resolve timeline stands against the cut list

- Exact: yes
- When the help for the editing program is off: this box is not shown; the Import tab takes files only.

{{32-008}}

### An import becomes a proposal the editor previews before accepting

A timeline file from any editing program, or the Resolve timeline the cut list names, becomes a proposal of changes to the cut list.

- Exact: yes
- Ways in: a timeline file dropped on or chosen in the Import tab; reading the Resolve timeline the cut list names; the header chip; the command palette.
- When the help for the editing program is off: only a dropped or chosen file; "The Resolve timeline this list names" and its button are not shown.

{{32-014}}

### An import is matched to the cut list cut by cut

Matching never uses Resolve's own ids: notes, colours and marks follow each cut's clip and source span, so they survive ripple moves, project copies and other computers. A comparison reports the fewest moved cuts and a blade as one split, so a single drag reads as one move.

- Exact: yes

{{32-016}}

Except that a cut that is not on the timeline goes onto the shelf named after its section, exactly as a deleted cut does (see Timeline Cards: the editor: Editing, undo and the cut list, "Deleting stages cuts on the shelf under their section's name and takes gaps out"); there is no "Not on the timeline" category, and the Staged row of the preview names the shelf the cut goes to. And an unknown marker that is Red becomes a plain heading, not a note: Green is a note, Red a plain heading, and every other colour a section.

### Accepted changes become ordinary edits on the cut list

An accepted proposal becomes edits on the cut list in the one way any changed cut list does, the way a hand edit of the file is merged (see Timeline Cards: the editor: Editing, undo and the cut list, "The cut list file can be edited by hand, and the editor merges the change"): only what changed moves, and a cut removed in Resolve waits on the shelf named after its section. However many edits it takes, accepting is one step for undo.

### The editor always sees how far the Resolve timeline has drifted from the cut list

- Exact: yes
- Ways in: the header chip, the Import tab, the Send tab's "Since the last send" list.

{{39-057}}

### A cut list can be rewritten from its timeline in Resolve, keeping what only the cut list knows

The cut list is brought up to date with its timeline in Resolve only through the Import proposal, previewed and accepted in whole or in part (see "An import becomes a proposal the editor previews before accepting"). The proposal built from the Resolve timeline keeps what only the cut list knows: per matched cut its note, manual gain, person, transcript link and words (when the timeline has none); each clip's full name and start timecode; a heading matching a marker keeps its kind, and takes the marker's colour (the cut list's only when the marker has none); a Green marker that was a note line comes back as a note line inside the section it interrupted; markers after the last cut become empty headings at the end; the shelf, alternates and saved sequences are left as they are; the header keeps its project, title and timing and records when and from which timeline it was updated. A cut's colour comes only from a colour set on the clip in Resolve. A marker read from Resolve with only a colour is a note when Green, a plain heading when Red, and a section in any other colour; a kind the cut list already holds for that marker is never changed by its colour. Refused while the cut list is read-only. Once accepted, the cut list reports in step with its timeline. Messages: "there is no timeline here to update this file from"; "Resolve answered with no timeline"; "this project file was built from '<a>' and the cards here are '<b>' -- updating it from a different timeline needs force: true"; "an edit is already being applied -- wait a moment".

Updating from a timeline other than the one the cut list names is refused, naming both, until the editor confirms.

- Exact: yes

### The saved project is read when Resolve is closed

The cut list's timeline is read from Resolve on the editor's computer while Resolve runs with that project; when Resolve is closed, or the computer is asleep or away, it is read straight out of the studio's Resolve project library as it was last saved, without starting Resolve or touching its scripting, and changing nothing. Work not yet saved in a running Resolve is then invisible, and the person is told the time of the save that was read.

What is read for a timeline: its name, its project's name, its frame rate and whether it is drop-frame, its start, when it was last changed, every cut on video track 1 in timeline order, and the timeline markers. For each cut: where it starts and how long it is (in timeline frames), which clip and that clip's name, where in the clip it starts (in the clip's own frames), the clip's own frame rate, the cut's clip colour, and the audio fade-in and fade-out of its sound on audio track 1. For each marker: its frame, colour, name, note and duration (at least one frame).

- A fade, colour or marker that cannot be understood reads as "none" and does not stop the read; a marker list that exists but cannot be understood reads as "unknown", so markers known from elsewhere are kept rather than wiped.
- A read is refused, with a sentence naming what is wrong, when the timeline is not in that library, has no content or no video track, a cut's position is not a number, or the timeline's frame rate is not between 1 and 1000 frames per second.
- A change to the timeline is noticed within a couple of seconds of Resolve saving it. A change that touches only tracks other than video track 1 is not noticed.
- Pending: cards-to-resolve-and-exports-U2

#### Lessons

- Met: CRX-079, CRX-080, CRX-081, CRX-082.

## Which computer is driving Resolve

### Resolve on an editor's computer takes part in Timeline Cards through the app

The app on an editor's computer lets that computer's Resolve take part in Timeline Cards: the editor's Timeline Cards session sees what Resolve is showing (project and timeline), and a send reaches that Resolve. The computer reaches Timeline Cards by itself, through the studio's dashboard, with the computer's own sign-in, so nothing has to be opened on the network to reach it and it can be anywhere the dashboard can be reached; nothing secret to Timeline Cards is kept on the editor's computer. A new sign-in takes effect without restarting.

- A person drives only the computers signed in to their own account. Each of a person's computers appears separately, as "<person>/<computer>", from the computer's verified identity; a name the computer gave itself is marked unverified.
- Each computer follows the episode open on that computer: an editor's Resolve follows the episode the editor last opened as a page. Other activity (playing media, looking things up) moves it to another episode only when the editor has not opened the previous episode's page for 2 minutes. Activity in Resolve that changes something (a timeline sent, the playhead moved) also counts as the editor being in that episode. A request and its answer always reach the same episode.
- When the editor is in no episode, what the computer sends is set aside, and the computer's status says so: "<person> is not in a Timeline Cards episode on this dashboard: open one" on the episode list "and this agent attaches to it". It waits up to 25 seconds for one to be opened before saying it again.
- A problem inside Timeline Cards comes back to the computer as a sentence, never a crash. The app never connects to Resolve during Resolve's start-up window.

- Setting: Resolve takes part in Timeline Cards on this computer. Does: lets Timeline Cards see and drive this computer's Resolve for the person signed in on it. Default: on, wherever Timeline Cards and the help for the editing program are on. Who: the editor for their own computer, or an admin. Applies to: a computer. Search words: resolve, drive resolve, timeline cards, send to resolve.
- Windows and macOS: on both; on any other system the computer does not take part.
- When Timeline Cards is off: the computer's Resolve takes no part and the setting is not shown.

### A computer says what stops its Resolve taking part

A computer does not start taking part when something stands in the way, and says what, checked in this order:

1. switched off for this computer;
2. not signed in: "Sign in from the tray and this computer will pick the page up on its own within a minute";
3. the studio has stopped work: "syncing is stopped by your admin, so this computer is not taking work of any kind" (a stop prevents starting only; a send already running in Resolve finishes);
4. another program is already driving Resolve on this computer for Timeline Cards: "a Timeline Cards process is already driving Resolve here: <name> (pid <n>): <command line, shortened>. Close it and this computer picks the page up within a minute" (the other program is never closed by the product);
5. the computer's programs cannot be listed: treated as one running, and the person is told that another program may be driving Resolve and the computer's programs could not be listed, so it is not starting;
6. the app on this computer must be updated before its Resolve can take part, saying so.

Once the obstacle is gone (signing in, closing the other program, a stop ending) it starts on its own within about a minute, and the computer is looked at again on its own while it waits, so the editor need not restart anything. An obstacle on this list is a wait, never a failed start. Only a start that was tried and failed for some other reason counts: after 5 such failed starts in a row it stops trying until the app is restarted, and the computer's sentence says that it stopped trying and that restarting the app starts it again.

### Each computer shows whether its Resolve is taking part and if not why

Each computer reports one word and a sentence (up to 255 characters), seen on the computer and on the dashboard's per-computer view, and shown green only on "running":

- refused: never started; the reason from the list above;
- stopped: it stopped working; what stopped it, or that it is no longer running;
- credential refused: "the fleet credential is refused: sign in again from the tray";
- unreachable: the dashboard has not answered in the last 50 seconds (or nothing in the first 30 seconds): the last error, or that the dashboard has not answered this computer;
- running: "serving <episodes> to <dashboard>", or, when updates from Resolve are set aside because no episode is open, that reason with "open an episode".

Green needs a successful contact in the last 50 seconds. Also shown: when the dashboard last answered, the current timeline's name, and since when it has been running. Anything shown stopped is restarted within about a minute, except a computer stopped after 5 failed starts in a row, which stays stopped until the app is restarted (see "A computer says what stops its Resolve taking part").

### The Live tab follows Resolve's playhead and moves Resolve to the selected cut

- Exact: yes
- When the help for the editing program is off: there is no Live tab.

{{32-017}}

### The page says which computer's Resolve it is using

A computer running Resolve counts as present if heard from within the last 40 seconds, and never gives up on network trouble. What the page shows: "no Resolve agent has connected yet" or "Resolve agent away since HH:MM:SS"; "<machine>: Resolve open, no timeline (conform is available)"; "<machine>: Resolve is not reachable (<error>)"; and, before any computer has ever connected, an amber note "no Resolve agent yet -- pick a cut list or canvas; the agent is only needed to conform". The page also shows when that computer last looked through its media pool. The lane uses the keys of that computer's Resolve keyboard preset, remembered even after the server restarts.

- Exact: yes

### Work for Resolve is done one piece at a time and the editor is told when it could not be

Resolve on a computer does one piece of work at a time. A send is refused at once when it cannot be done: no computer present ("<away text> -- the cut was not sent"); Resolve gone ("<stale or resolve text> -- the cut was not sent"); "the agent already has a request in flight -- wait a moment". Work the computer has not started within 2 minutes is dropped ("<away text> -- the send was dropped"). Work the computer took and never answered is reported ("the Resolve agent went away with that <kind> -- it was never confirmed"); work that never reached it is offered again, never done twice; an answer for work no longer open gets "that request is no longer open". If Resolve never starts on it: "Resolve never started on that send". Resolve is given up to 8 minutes to finish one piece.

- Exact: yes

#### Lessons

- Met: CRX-083, CRX-084, CRX-085, CRX-086.

## Exports

### The Export tab downloads the cut as a timeline file or as the script

- A radio group of four tiles, "Final Cut Pro XML" selected by default:
  - "Final Cut Pro XML" (.fcpxml): "Resolve and Final Cut read it. Carries the most of the cut."
  - "OpenTimelineIO" (.otio): "The open interchange format. Round-trips back into the editor exactly."
  - "CMX3600 EDL" (.edl): "The oldest format: straight cuts and markers. Every tool reads it."
  - "Script" (.md or .txt): "The words of the cut to read, print or send..."
- For the three timeline formats, a "Media" choice: "Source files" (default; "The files the transcripts were made from; the lite audio where there is none.") or "Lite audio" ("The editor's own Opus copies: same timing, not the camera audio.").
- A "Levelling" switch "Bake automatic levelling into the gain" (default on). Active only for Final Cut Pro XML; for the others it is disabled with the hint "<format> has no clip gain: cuts play at source level."
- For Script, a "File" choice "Markdown (.md)" (its hint mentions Ctrl+S) or "Plain text (.txt)" (its hint mentions Ctrl+Shift+S).
- Before a download, a note says what the format does not carry, or, for the script, that it is the words as spoken in each clip's own language and the English lines stay in the editor.
- Primary "Download" ("Exporting" while busy) downloads every file produced. Changing format, media or script type clears the last result.
- After a download: "Downloaded <names>", "<n> clips linked, <m> offline, <k> cuts levelled", and an open expander "What the file does not carry (<n>)" listing every loss as a warning.
- Toast and news: "Downloaded <names>." Download errors show in the tab. A Ctrl+S or Ctrl+Shift+S failure toasts "The script download failed: <reason>"; with no cut list open it toasts "Open a cut list first: there is nothing to download." Only one keyboard script download runs at a time.

Another editing program is named on a tile only once importing that format into it has been tried and found to work; Premiere is named on the Final Cut Pro XML tile once that is so.

- Exact: yes
- When the help for the editing program is off: the tiles name no editing program ("Final Cut reads it. Carries the most of the cut."); everything else is as above, and the exports are the whole hand-over.

### Each export format carries some of the cut and says what it lost

- Exact: yes

{{32-010}}

### An exported timeline links each clip to its original media where it can

- Exact: yes

{{32-011}}

### A Final Cut Pro XML export can bake the automatic levelling into each cut's gain

- Exact: yes

{{32-012}}

### The script export is the words of the cut as spoken

The cut exports as plain text and as Markdown, in timeline order, each card in the language it was spoken only, without translations: a Mandarin card exports its Mandarin, never the English.

- Exact: yes


  - One file named after the cut list's timeline name, else its title, else its project, else the cut list's file name, else "Timeline Cards". Characters Windows refuses (`\ / : * ? " < > |` and control characters) become `_`; trailing dots and spaces are removed; at most 150 characters (counted in UTF-16 units, never splitting a pair).
  - Markdown starts with `# <name>`.
  - A section or plain heading becomes `## <title>` (Markdown) or the title underlined with `=` (text). The heading's kind decides this, never its colour.
  - A `◆` note heading or a note row becomes `> ◆ <text>` (Markdown) / `-- <text> --` (text); an "unmatched" note row is prefixed "unmatched: ".
  - Each cut: a header line with the speaker in bold, then a hyphen with a space on each side, then the record timecode, with a hard line break (Markdown), or `Speaker <timecode>` (text). The timecode is where the cut sits on the timeline a send would build.
  - Then the cut's words as spoken: when a cut has lines in a non-Latin script, those are kept and the Latin gloss lines beside them dropped; an all-Latin cut drops only plainly English lines beside non-English ones. Lines that would read as Markdown structure (`# `, `> `, `- `, `1. `, `===`) are escaped.
  - Then the cut's note: `> 📝 <note>` or `   [note: <note>]`.
  - A gap's note comes before the cut after it: `> 📝 gap: <note>` or `   [gap note: <note>]`, taken from the gap rows of the cut list.
  - A cut with no words is left out and counted.
  - The loss list always says "the words as spoken only: translations are not in the script", plus "<n> cut(s) with no words are left out", plus a sentence when gap notes could not be read (the download still happens).

### Imported timeline files are recognised and read by these rules

- Exact: yes

{{32-015}}

### Exports are frame-exact and the same every time

- Exact: yes

Only the cut is exported; the shelf and saved sequences are not.
  - Frame rate: the rate asked for, else the cut list's own. A rate within 0.01 of 23.976, 29.97, 47.952 or 59.94 is treated as the exact NTSC fraction (24000/1001 and so on); any other rate is read as the nearest fraction with a denominator of at most 1001.
  - Seconds become frames once, exactly, rounding to the nearest frame with ties to even (an option rounds ties up, matching the hand-over to Resolve frame for frame), so all three formats agree on every frame.
  - Drop-frame timecode only at 29.97 and 59.94; a cut list marked drop-frame at another rate is written non-drop, with a note.
  - Timeline start: the cut list's start timecode; none or unreadable means 01:00:00:00, with a note.
  - Source side: each cut's in and out in frames at the clip's own rate (unreadable rate: the timeline's, with a note), counted from the clip's start timecode (unreadable: from 00:00:00:00, with a note). Source drop-frame is used when the rate allows and the timeline is drop-frame or the clip's start timecode uses ";".
  - A cut shorter than one frame is exported as one frame, with a note.
  - Record side: cuts laid end to end after the black in front of them, so nothing drifts. A clip at another rate than the timeline has its record duration rescaled (it may differ by a frame), with a note per clip.
  - Gaps: every gap is exported as black at its own length, including gaps after the last cut; consecutive gaps are rounded as one run, so totals match the hand-over.
  - Fades in timeline frames, never longer than the cut.
  - Markers: section headings (Blue by default), note headings (Green by default; a heading's own colour wins) and note rows (Cream) become markers on whatever follows them.
  - Edges that fall between frames (more than 0.001 frame off) are reported as "falls between frames: rounded to the nearest frame (<rule>)".
  - Every export with a cut ends with the note "automatic levelling is the editor's playback only: exported audio plays at source level plus each cut's manual gain where the format carries it".
  - Each export lists "not carried" sentences naming what the format lost; nothing is lost silently. Cuts are named "cut N (<person or clip>)".
  - File names come from the timeline name (default the cut list's title, else its project name, else "Timeline Cards"), with characters Windows forbids replaced by "_" and trailing dots and spaces removed ("timeline" if empty). The same cut list always gives the same bytes.
  - Media paths, when known, are written as file addresses (Windows drive paths, network share paths and Mac paths converted).

### The OpenTimelineIO export

- Exact: yes

{{33-083}}

### The Final Cut Pro XML export

- Exact: yes

{{33-084}}

### The CMX3600 EDL export

- Exact: yes

{{33-085}}

#### Lessons

- Met: CRX-087, CRX-088.

## Renders from Resolve

### Several projects can be rendered from one queue that survives Resolve crashing

A person can queue renders of timelines from several Resolve projects on their own computer and leave them. When Resolve dies during a queued render, the queue starts Resolve again (waiting until its scripting is ready, by the rule in "Timeline Cards never connects to Resolve while Resolve is still starting"), runs the interrupted job again from its start, and carries on with the rest. Each job shows waiting, rendering with its progress, done, or failed with the reason, and the queue can be paused and a job cancelled.

- Who: anyone signed in, on Resolve on a computer signed in to their own account.
- When the help for the editing program is off: there are no renders.

### Before a queue starts each job that differs from the studio's render defaults is listed

The studio's default render is QuickTime H.264 at 3840x2160 with proxies off. Before a queue starts, every job whose project would render differently is listed per project, naming each difference, with a yes or no to switch it to the studio's default; nothing is changed without that answer.

- Setting: Studio render defaults. Does: the format, codec, size and proxy use every queued render is checked against before it starts. Default: QuickTime, H.264, 3840x2160, proxies off. Who: an admin. Applies to: the site. Search words: render, export settings, H.264, 4K, quicktime.

### Clips inside compound clips are checked online before a render is queued

Before a render is queued, every clip inside every compound clip on the timeline is checked, as well as the clips on the timeline itself, and each one that is offline is named with the compound clip it sits in. The person decides whether to queue it anyway.

### A timeline's real end is found before it is rendered

A timeline can hold the cut and, minutes later, clips parked out of the way. Its real end is taken at the first stretch of empty timeline lasting one minute or more, and renders stop there; the person sees where that end is each time and can move it.

- On its own: the real end, at the first stretch of empty timeline of at least the set length.
- By hand: each time, the person sees the end found and can set another for that render.
- Setting: Empty stretch that ends a timeline. Does: how long a stretch of empty timeline must be for the timeline to count as ending there when it is rendered. Default: 1 minute. Who: anyone signed in. Applies to: the site. Search words: timeline end, parked clips, render length, empty gap.

### Every render is checked before it is used

Every render is checked for a picture stream, for sound and for the expected length before anything uses it. A fact about Resolve: a render can come out without its picture or its sound while reporting success, and a 25-minute render that finishes in under a minute is audio only. A failed check is shown on the job as failed, naming what is missing. A fact about Resolve: an audio-only render as WAV can refuse to start; audio-only renders the product asks of Resolve start and finish without help from the person.

#### Lessons

- Met: CRX-089, CRX-090, CRX-092, CRX-093, CRX-094, CRX-095.

## Titles and compound clips

### A compound clip the product makes carries its clip's name and colour

A compound clip the product creates in Resolve is named after the clip it wraps and takes the clip colour of the related interviewee's multicam.

### Name titles a person adds in Resolve are left as they are

The product never places name titles. Name titles are the editor's own, added in Resolve: placed with the visible edge 50 px in from the side and from the bottom of the picture, on the side away from where the speaker appears, and, on a direct cut from one interviewee to another, with the first speaker's title playing its exit and the second speaker's title its entrance. The product leaves every such title where it is: nothing it does in Resolve moves, shortens or removes a title a person added, and no later hand-over or comparison loses one.

#### Lessons

- Met: CRX-096, CRX-097, CRX-098.

## Subtitles and delivery

### A finished cut gets English subtitles timed to its speech

A finished cut gets English subtitles in natural documentary English, timed to the speech, with each gap note carried as visible text over its gap. They are made from the cut's own words and English, and line up with the cut from frame zero: each cue is within a frame of its speech, with no shifting by hand. A fact about Resolve: it places imported subtitles offset along the track, so subtitles placed on a timeline are lined up by the product.

How lines are made:

- A cue ends at a paragraph break, at sentence-ending punctuation (Latin or Chinese, with any closing quote or bracket), or, where a sentence is too long, at a clause, so a line never starts with the tail of the previous sentence. A line holds at most about 95 characters in English and 42 in Chinese. Whether a text is Chinese, Japanese, Korean or Cantonese is taken from the language recorded, else from more than 30 % wide characters in its first 400 words. Times are worked out between the words, and all the text is kept.
- No line break falls inside a run of Latin letters, digits or `% ' . -`, and no line has a space at either end.
- Pause markers are left out. A line too short to have a length gets one millisecond.
- Times carry the clip's start timecode, as Resolve's own subtitle exports do.
- Captions hold through short pauses: a pause between two cues shorter than the set limit is bridged, so the first caption holds until the next; a longer pause stays empty.
- Before delivery: every stretch of speech has a subtitle, no cue spans a break in speech, no cues overlap, and none falls past the cut's end; each failure is named with its time.
- A fact about Resolve: subtitle files it exports carry invisible line-separator characters. Every subtitle file the product writes or passes on is free of them.

- Setting: Subtitle line length. Does: the longest a subtitle line may be, in characters, for English and for Chinese, Japanese, Korean and Cantonese. Default: 95 for English, 42 for Chinese. Who: anyone signed in, for a cut they work on. Applies to: a project. Search words: subtitle length, line length, captions, srt.
- Setting: Bridge short pauses between captions. Does: a pause between two captions shorter than this is closed so the caption holds; 0 turns bridging off. Default: 1 second. Who: anyone signed in, for a cut they work on. Applies to: a project. Search words: caption gap, bridge pauses, subtitle hold, srt.

### Subtitles already on a Resolve timeline are used rather than made again

When a Resolve timeline already carries subtitles, the product exports those rather than making new ones.

- When the help for the editing program is off: subtitles are always made from the cut.

### Two-language on-screen text splits its lines by count, Chinese above English

On-screen text in two languages splits its lines 1, 1+1, 1+2 or 2+2, with the Chinese above the English; both languages change at the same frames, and a block grows upward from a fixed margin. The text sizes and the gap between the languages can be set before anything is placed.

### A delivery to a TV network has two subtitle files and a name-strap list per episode

Each delivered episode gets an English and a Chinese subtitle file in its own folder, and a list of every speaker with a screenshot and the name as it appears on screen. Each person's name is spelled one way per language across every subtitle file and name-strap list of the episode; a second spelling is named before delivery.

#### Lessons

- Met: CRX-099, CRX-100, CRX-101, CRX-102, CRX-103, CRX-104, CRX-105, CRX-106, CRX-107, CRX-108, CRX-109.
