# Joins aimed at cards-to-resolve-and-exports

## Checked

- J1 | F1
- J2 | F2
- J3 | fine
- J4 | F3
- J5 | F4
- J6 | F5
- J7 | F6
- J8 | F7, F8
- J9 | fine
- J10 | fine
- J11 | F9
- J12 | fine
- J13 | fine
- J14 | F10
- J15 | F11
- J16 | F12
- J17 | fine
- J18 | F13, F14
- J19 | F15

## Findings

### F1: A person's colour is "the same in the hand-over" in one piece, but Resolve gets a paired clip colour that two people can share from the ninth person on
- Kind: contradiction
- From: cards-board / Every interviewee has one colour everywhere
- Here: Clip colours on a sent timeline
- From says: "Each interviewee has one colour, the same on the board, on their clips and on their cuts in the editor and in the hand-over. ... With more than 16 people, colours repeat."
- Here says: "Each of the 16 interviewee palette colours is paired with one of Resolve's clip colours, in order: Blue, Violet, Green, Teal, Tan, Chocolate, Pink, Navy, Purple, Olive, Yellow, Blue, Purple, Green, Orange, Navy, so the first 8 speakers get 8 different clip colours and they repeat after that."
- Settled by: the owner must say: in an episode with between 9 and 16 interviewees, may two of them wear the same clip colour in Resolve (the 1st and the 12th both Blue) while they have different colours on the board and the cards?
- Fix: cards-board should say that in Resolve a person's colour is shown as its paired Resolve clip colour (pointing here for the pairing) and when two people can coincide there; if the owner wants no repeats below 16, this piece changes its pairing to 16 distinct clip colours.

### F2: The hand-over reserves Red and Green for problems and notes, while a section may be any colour
- Kind: contradiction
- From: cards-editor-1 / What a marker is, and which kinds there are
- Here: Sections and notes arrive as markers
- From says: "The kind is kept apart from the colour: any colour can make a section, recolouring a marker never changes its kind"
- Here says: "Red is kept for markers that report a problem, and Green for notes, so a marker read back from Resolve never turns a note into a section."
- Settled by: CE2-032 (ruling): "any colour can make a section, and recolouring never changes the kind."
- Fix: this piece should drop "Red is kept for markers that report a problem" (nothing in it makes such a marker) and say that a section of any colour, Red and Green included, is sent in its own colour and, when read back, keeps the kind the cut list holds for it; the read-back colour rule (Green a note, Red a plain marker, any other a section) applies only to markers the cut list does not know.

### F3: A cut's gain goes to Resolve in one piece, while this one keeps a "not yet carried" sentence on every send
- Kind: contradiction
- From: cards-editor-2 / The gain dialog sets a cut's loudness on top of the automatic levelling
- Here: Audio fades and gain arrive in Resolve as set on the cards
- From says: "goes with the cut to the editing program when the cut is handed over"
- Here says: "Until the product has proven, by reading them back, that fades and gain arrived, every send and every export says plainly ... \"N cut(s) carry a manual gain that is not yet carried into Resolve: the timeline will play them at the clips' own level\""
- Settled by: decisions page 25, 25.8 (answered 2026-11-24, recommendation A): "carry it into Resolve as the clip's volume"
- Fix: this piece should state the gain (and the fades, per decision 29.1 A "fades and gain carried") as arriving, with a read-back refusal sentence for a cut whose level Resolve would not take, and drop the standing "not yet carried into Resolve" sentence from sends (keeping the format sentence for the exports that have no clip gain).

### F4: cards-editor-2 describes notes on a live Resolve timeline and its draft cards, which this piece says do not exist
- Kind: contradiction
- From: cards-editor-2 / Notes on cards and gaps while a cut is worked on a live timeline
- Here: A cut list being edited never changes Resolve until it is sent
- From says: "Where a cut is being worked on a live timeline in the editing program (see Timeline Cards: the hand-over to Resolve, and exports: Edits sent live and staged edits), these rules hold for notes"
- Here says: "Only sending goes to that computer; anything else is refused: \"a project file is edited in the file, not in Resolve -- the '<kind>' was not sent to the agent\"."
- Settled by: decisions page 29, 29.2 (answered 2026-11-24, recommendation B): "it goes; a cut is edited only as a cut list, handed over as a new timeline, and Resolve's later changes come back through the header chip and the Import tab as one undoable step."
- Fix: cards-editor-2 should drop the live-timeline framing (and its refusals "no timeline is open", "that cut is no longer on the timeline" and draft-card notes), keeping only the notes rules of a cut list, with the gap-note-at-send rule pointing here.

### F5: Changes brought back from Resolve replace cuts whole and lose removed ones here, while cards-editor-2 says they follow the hand-edit merge (removed cuts wait on a shelf)
- Kind: contradiction
- From: cards-editor-2 / The cut list file can be edited by hand, and the editor merges the change
- Here: Accepted changes become ordinary edits on the cut list; A cut list can be rewritten from its timeline in Resolve, keeping what only the cut list knows
- From says: "Changes brought back from the editing program into a cut list follow these same rules: a cut removed there waits on a shelf, and only what changed moves"
- Here says: "The order, new and removed rows, headings, the shelf and the remaining facts come in as one restoring edit" and "The whole cut is replaced from the timeline's clips and markers, as one revision"
- Settled by: decisions page 25, 25.9 (answered 2026-11-24, recommendation A): "one way of turning a changed cut list into edits, and nothing removed in Resolve is lost from the cut list."
- Fix: this piece should say that an accepted import goes through the same merge as a hand edit of the file (pointing to cards-editor-2), with a cut removed in Resolve going to the shelf, and should drop its own separate replace-whole conditions and the whole-cut rewrite.

### F6: A send from a read-only cut list "does not change the file" in one piece, while every send stamps the cut list here
- Kind: contradiction
- From: cards-editor-2 / A cut list opens as cards with no editing program, and can be opened read-only
- Here: The cut list records the timeline it built
- From says: "except handing it to the editing program, which builds a timeline and does not change the file"
- Here says: "After a successful send the cut list is re-read, its timeline name set to the name Resolve actually gave the timeline ... its revision raised by one"
- Settled by: the owner must say: when someone sends a cut list they opened read-only, should the cut list still record which Resolve timeline it was sent as and when?
- Fix: both pieces should say the same thing: either a read-only send is stamped like any other (cards-editor-2 changes), or it is not stamped and the send says " The cut list could not record it." (this piece names read-only as that case).

### F7: Resolve's clip rate wins over the cut list's in cards-editor-2, while a rate set by hand is never overwritten here
- Kind: contradiction
- From: cards-editor-2 / A cut list holds the cut, the bench and the timeline's facts (and its next heading, Facts the editing program knows about a clip win over what the cut list recorded)
- Here: Which frame rate a clip is taken to have
- From says: "When Resolve's project knows a clip's real frame rate and start timecode, those are used instead of the values written in the cut list." and "per clip its rate, start timecode and Resolve id (hints for exports only)"
- Here says: "a clip's rate is the one Resolve reports for it; else the one measured ... By hand: each clip's rate and start timecode are shown in the cut list's facts and can be set there. A rate set by hand is never overwritten by a later measurement."
- Settled by: OWNER_REQUIREMENTS section 6: "A value set by hand is never overwritten by a later automatic pass."
- Fix: cards-editor-2 should say a rate or start set by hand wins over Resolve's, and that the per-clip facts serve the hand-over as well as the exports (the send finds a clip by its id and uses its rate); this piece should put a hand-set rate first in its order.

### F8: This piece lets a person change the timeline's rate and start in the cut list's facts; cards-editor-2 says no edit can change them
- Kind: contradiction
- From: cards-editor-2 / The cut list file can be edited by hand, and the editor merges the change
- Here: The timeline a cut builds runs at a chosen frame rate and start
- From says: "Ignored and written back as they were: ... the episode, root, board, rate, drop-frame, start and timing facts at the top (\"the frontmatter's X was edited; no edit can change it, so it is kept as it was\")"
- Here says: "By hand: both can be changed in the cut list's facts, and the rate can be changed for one send on the Send tab."
- Settled by: the owner must say: can a person change a cut list's timeline frame rate, drop-frame and start timecode, and if so where?
- Fix: if yes, cards-editor-2 names the control that changes them and accepts them in a hand edit; if no, this piece drops "both can be changed in the cut list's facts" (and its Send tab, which lists no rate control, drops the one-send rate too).

### F9: Every import is a proposal accepted in whole or in part in cards-editor-4, while this piece also has a whole-cut rewrite from the timeline
- Kind: contradiction
- From: cards-editor-4 / Every suggestion from the assistant and every import arrives as a proposal the editor previews and accepts in whole or in part
- Here: A cut list can be rewritten from its timeline in Resolve, keeping what only the cut list knows
- From says: "Every suggestion from the assistant and every import arrives as a proposal the editor previews and accepts in whole or in part" and "only proposals that do not come from the assistant (bringing changes back from Resolve) arrive"
- Here says: "The whole cut is replaced from the timeline's clips and markers, as one revision ... A preview gives counts and the rows without writing."
- Settled by: decisions page 25, 25.9 (answered 2026-11-24): "one way of turning a changed cut list into edits"; and page 29, 29.2 B: "Resolve's later changes come back through the header chip and the Import tab as one undoable step."
- Fix: this piece should keep one way back, the proposal accepted in whole or in part, and fold what the rewrite keeps (notes, gain, person, colours from the clip, Green markers as notes, the refusal for a different timeline) into how that proposal is built.

### F10: cards-editor-5 puts a red Send to Resolve button in the header; this piece says sending is not a top-bar button
- Kind: contradiction
- From: cards-editor-5 / The header shows the brand, where you are, search, undo, redo and Send to Resolve
- Here: Where the dialog and the script downloads are reached
- From says: "**Send to Resolve** (desk only): a red primary \"Send to Resolve\" when a cut list is open and sending is available ... The red button opens the send panel"
- Here says: "Sending is an action on the cut, not a button in the top bar: the cut's own actions hold \"Send to Resolve\", which opens the Send tab with a fresh dry run."
- Settled by: CRX-065 (ruling): "A cut offers one action that sends it to a new Resolve timeline: name it, see dry-run counts, confirm; the top bar holds no such button."
- Fix: cards-editor-5 should drop the header's Send to Resolve button and its "Resolve: not connected" label (or move that label somewhere that is not a send control), and its compaction rule for it, pointing to the cut's own action here.

### F11: The multicam the hand-over builds has no read-back within a frame and none of its build messages here
- Kind: missing
- From: cards-footage-in / The interview's multicam is ready for the editing program without one being open
- Here: Clips the project lacks are brought into it before the cut is placed
- From says: "what Resolve built is read back and fails loudly when any item is more than one frame from where it was meant to be" (the join hands this piece item 39-085's dialog facts and messages and item 39-083's read-back messages)
- Here says: "An interview whose multicam is not yet in the project gets it, built in Resolve from the angles and the line-up ... and placed in the `Multicams` bin." (nothing on reading it back, nothing on how a failed build is told)
- Settled by: CFI-018 (kind given, weaker): "each build is read back in seconds and fails loudly beyond one frame."
- Fix: this piece should say that a multicam it builds is read back (item counts per track as planned, each source start within one frame, else the send is refused naming the angle that is out of sync) and give the sentences a person sees when building it fails.

### F12: The multicam wears its interviewee's colour in Resolve from the moment it is made, but this piece only colours multicams on request
- Kind: missing
- From: cards-footage-in / Each interviewee is given a colour
- Here: An episode's multicams and a timeline's cuts can be coloured by speaker in Resolve; Clips the project lacks are brought into it before the cut is placed
- From says: "used for their cards on the board and for their multicam wherever it is shown, including in the editing program from the moment it is made there"
- Here says: "Nothing changes until the person confirms" (colouring by speaker) and nothing on colouring a multicam the hand-over builds
- Settled by: CFI-038 (ruling): "Every interviewee's multicam clip shows that interviewee's plan colour in Resolve from the moment it is made."
- Fix: this piece should say that a multicam it builds in Resolve gets its interviewee's paired clip colour at once, read back like every property, and keep the confirm-first action for multicams that already exist.

### F13: The rule for when Resolve may be connected to is written out in full in both pieces
- Kind: said twice
- From: resolve-on-the-editors-computer / The product never harms a Resolve session (and Facts about Resolve's scripting connection)
- Here: Timeline Cards never connects to Resolve while Resolve is still starting
- From says: "The product connects to Resolve only when Resolve's scripting helper is listening AND Resolve itself has registered with it. ... Only when it cannot tell at all (the computer's list of connections cannot be read, or something other than Resolve's helper holds port 1144) does it go ahead and connect."
- Here says: "Timeline Cards connects only when it shows the script server listening AND Resolve itself connected to it. ... Only when the check itself cannot be made (the table cannot be read, or the port is held by some other program) does it go ahead and connect."
- Settled by: OWNER_REQUIREMENTS section 1: "One way to do each thing"
- Fix: this piece should keep only its waiting sentence ("Resolve is starting: waiting before connecting") and point to resolve-on-the-editors-computer for the rule and the facts behind it.

### F14: Another program driving Resolve is looked for again with no restart in one piece, while here five failed starts need the app restarted
- Kind: contradiction
- From: resolve-on-the-editors-computer / The product never harms a Resolve session
- Here: A computer says what stops its Resolve taking part
- From says: "Another program found driving Resolve on the same computer is named to the editor and left alone, never stopped, and is looked for again on its own so the editor need not restart anything"
- Here says: "Once the obstacle is gone (signing in, closing the other program, a stop ending) it starts on its own within about a minute. After 5 failed starts in a row it stops trying until the app is restarted."
- Settled by: the owner must say: when Resolve on a computer cannot take part in Timeline Cards several times in a row, does it keep trying on its own, or wait for the editor to restart the app?
- Fix: this piece should say whether an obstacle from its list (another program, no sign-in, a stop) counts as a failed start; if the owner wants no restart, it drops "until the app is restarted" or limits it to starts that fail for some reason not on its list.

### F15: The check for clips Resolve cannot render (VP9 and AV1 from YouTube) that youtube points to is not in this piece's renders
- Kind: missing
- From: youtube / Before Resolve renders, the editor is told which clips would stop the render
- Here: Renders from Resolve (Clips inside compound clips are checked online before a render is queued)
- From says: "Before a render, a timeline's sources are checked for such codecs, and the editor is told by name which clips will make it fail. See Timeline Cards: the hand-over to Resolve, and exports: Renders from Resolve."
- Here says: nothing (only offline clips, render defaults, the timeline's end and the finished render's streams are checked)
- Settled by: YTD-039 (kind given, weaker): "Before a render, a timeline's sources are checked for such codecs and the editor is told which clips will fail."
- Fix: this piece's check before a render is queued should also name every clip (inside compound clips too) whose codec Resolve stops a render on, pointing to resolve-on-the-editors-computer's VP9 warning for the wording and the repair; or youtube points there instead of here.
