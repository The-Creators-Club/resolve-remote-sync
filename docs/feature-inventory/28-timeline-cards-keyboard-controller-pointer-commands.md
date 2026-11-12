# Timeline Cards editor: every key, controller control, pointer gesture and editing command

Terms used throughout:

- **The cut list**: the document being edited. Its timeline is an ordered run of **items**: **cuts** (one piece of an interview clip, with a source in point and out point in seconds of that clip) and **gaps** (a stretch of silent timeline time with a length). Gaps behave like clips everywhere in this section: they are selected, moved, deleted and resized like one.
- **The bench / the shelf**: cuts that are "staged", kept in the document but not on the timeline. Deleting a cut from the timeline stages it under a shelf heading named after its section.
- **The head**: the playhead, a position in timeline seconds.
- **The lane**: the horizontal timeline strip at the bottom. **The strip**: the lane's track area itself holding keyboard focus (clicked or tabbed to).
- **Port**: where the keyboard focus is: the **lane** (default: the body, the lane, transport buttons), the **cards** list (focus inside an element marked as the cards port), or the **transcript** panel. The controller has its own ports: lane, transcript ("doc"), the transcript's list of transcripts ("sources"), search results ("results"), and "a box" (the caret in one of two page text boxes).
- **In / out range (marks)**: a pair of timeline positions set with I / O (or R3 on the controller). It belongs to this browser only: it is never saved, never synced, never part of undo, and is cleared when another cut list opens.
- **Armed edge**: one edge (in or out) of one item, chosen by clicking that edge on the lane, which the frame and second keys then trim instead of moving the head.
- **Frame**: 1 / the cut list's frame rate (29.97 fps when the cut list gives none, for the input layer; 30 fps for some state calculations).
- **MIN_CUT_S / MIN_GAP_S**: the shortest cut and the shortest gap, both 1/24 s.
- **A refusal**: a command that is not carried out. Unless noted, a refused edit posts its sentence as a notice (a toast-style message: level "warn", or "info" for "nothing to undo/redo"-type refusals), and the controller rumbles.

## Keyboard: how a key press is handled
(source: client/input/keyboard.ts)

- Keys are matched by physical key position (the browser's key code), so bindings hold on any keyboard layout. Ctrl and Cmd are the same modifier. A chord is written modifiers first in the order Ctrl, Alt, Shift.
- Ignored entirely (the key passes through to the page) when:
  - the focus is in a text box, text area, select list, any content-editable element, or an input of any type other than button, checkbox, radio, submit, reset, range, color, file, image;
  - an input-method composition is in progress;
  - another part of the page already handled the key (it marked the event as handled).
- A binding can be limited to some ports. When the same key has a binding for the current port and one for all ports, the port's own binding wins.
- A binding marked "strip only" works only when the focus is inside the lane's track area; elsewhere that key is not taken at all.
- Auto-repeat (holding a key down): only bindings marked repeating fire again on the operating system's key repeat. A repeat of a key that is ours but does not repeat is still swallowed so the page does not scroll (for example a held Space).
- A key that is ours but means nothing in the current situation (for example Escape with nothing selected or armed) is left for the rest of the page, except that its repeats are swallowed.
- Space taken by the editor while focus is on a button, link or other control: the browser's own "click on key release" is suppressed, and any keyboard-generated click (a click with zero click count) on that same control within 600 ms after the Space is swallowed. This stops Space re-activating the last clicked button (for example the settings menu).
- A lone Alt key press (down or up), outside a text box, is cancelled, and on Alt release the window takes the focus back. This stops Chrome on Windows moving focus to its own menu button after an Alt+drag / Alt+click / Alt+wheel, which made the next Space open Chrome's menu.
- When the window loses focus: a Space held for its "hold" meaning ends (see Space below: if the hold had not yet reached 280 ms, this counts as a tap and toggles play); an F key held for its hold meaning is abandoned without sending its tap.
- Removing the keyboard (unmount) ends any held Space without sending anything, abandons a held F, and drops a pending Delete arm.

## Keyboard: transport and the head
(source: client/input/keyboard.ts, client/state/commands.ts, client/state/store.ts)

- **Space** (all ports): play / pause, with a tap / hold distinction:
  - Tap (released before 280 ms): toggles play on release.
  - Held 280 ms: playback rate goes to 2x and, if stopped, playback starts ("the skim"). On release the rate goes back to 1x, and if it was stopped when Space went down, playback pauses where it got to.
  - The tap / hold handling applies only when no Ctrl, Cmd or Alt is held. The OS key repeat is ignored during a hold.
  - Because the tap fires on release, a press of Space does nothing until the key comes up.
- **K** (all ports): pause.
- **L** (all ports): play.
- **J** (lane port only): the head two seconds back. Repeats while held.
- **Left arrow** and **Comma** (all ports, repeating): one frame back. With an edge armed, they instead trim that armed edge one frame earlier (see trimBy).
- **Right arrow** and **Period** (all ports, repeating): one frame on; with an edge armed, trims that edge one frame later.
- **Shift+Left arrow** and **Z** (all ports, repeating): one second back; with an edge armed, trims it one second earlier.
- **Shift+Right arrow** and **X** (all ports, repeating): one second on; with an edge armed, trims it one second later.
- **Home** (all ports): the head to the start (0).
- **End** (all ports): the head to the end of the timeline.
- **A** and **Up arrow** (all ports, repeating): the head to the previous edit point (start of an item). Gaps are stops. From inside an item more than 0.25 s past its start, it first goes to that item's start. The selection does not change.
- **S** and **Down arrow** (all ports, repeating): the head to the next edit point.
- **Shift+A** (all ports, repeating): ten edit points back.
- **Shift+S** (all ports, repeating): ten edit points on.
- Zoom (all ports, repeating):
  - **=** (Equal): zoom the lane in by x1.25.
  - **-** (Minus): zoom out by x0.8.
  - The zoom holds still the time under the mouse pointer when the pointer is over the lane (the lane view reports it), else the head. Keyboard zoom is not clamped by the input layer; the state clamps it to 0.5 to 2000 px per second.

## Keyboard: selection and editing
(source: client/input/keyboard.ts, client/input/context.ts)

- **E** (all ports): ripple-extend the nearer edge to the head. The item acted on is the keyboard-focused cut, else the last selected, else the cut under the head. The edge nearer the head is moved to the head (lengthening the cut when the head is outside it, shortening it when inside), rounded to whole frames; everything after it slides. Nothing happens if the move rounds to under half a frame, or if there is no such cut. Sent as an absolute edge trim (trimEdge), so it is refused like any trim (see the command list).
- **Shift+E** (all ports): the same, moving the OTHER (farther) edge to the head.
- **Shift+Up arrow** (all ports, repeating): extend the selection one item up (a range from the anchor to the new focus).
- **Shift+Down arrow** (all ports, repeating): extend the selection one item down.
- **Escape** (all ports): first press with an edge armed disarms it; otherwise, with items selected, clears the selection; with neither, the key is left for the page. A drag in progress on the lane is dropped by Escape before this binding sees the key (see pointer section).
- **Q** (lane port only): trim the start of the cut under the head to the head ("trim in to playhead").
- **W** (lane port only): trim the end of the cut under the head to the head.
- **B** (lane port only): split the cut under the head at the head.
- **F** (lane port only): split at the head (the blade, as in the owner's Resolve preset).
- **Ctrl+B** (all ports): split at the head.
- **Delete** and **Backspace** (all ports):
  - When the strip itself has the keyboard and a valid in / out range exists (both ends set, at least one frame apart, and the whole range inside one cut), the range is taken out of that cut at once (deleteRange), with no arming.
  - Otherwise, press twice: the targets are the selected items, else the keyboard-focused item. The first press "arms" them: the views are told which items and that the countdown is 3 seconds (they draw the red edge, the count and a toast). A second Delete or Backspace with exactly the same targets within 3000 ms deletes them. A press with different targets re-arms for those instead. After 3 s the arm lapses and the views are told it is off.
  - If every target is a gap, the delete goes through on the first press.
  - With no targets at all, the delete command is sent at once and is refused ("select a cut first").
- **I** (strip only): mark in at the head.
- **O** (strip only): mark out at the head. Anywhere else, a bare O is not taken by this table (the help sheet lists O as the sections and markers overview, bound elsewhere).
- **Alt+I** (lane port only): clear the in mark.
- **Alt+O** (lane port only): clear the out mark.
- **Shift+Insert** and **Shift+G** (all ports): insert a 1 second gap at the head (Shift+G exists because laptops lack an Insert key).
- **R** (all ports, repeating): move the selection (else the item under the head) up one slot (in front of the item before the block's first item). Nothing at the top.
- **D** (all ports, repeating): move it down one slot (after the item after the block's last item). Nothing at the bottom.
- **Shift+R** (all ports, repeating): move up ten slots, or as far as the list goes.
- **Shift+D** (all ports, repeating): move down ten slots, or as far as the list goes.
- **Ctrl+Z** (all ports, repeating): undo.
- **Ctrl+Shift+Z** and **Ctrl+Y** (all ports, repeating): redo.
- Gain (all ports, repeating except reset):
  - **Alt+Shift+Up arrow**: gain +1 dB on the selected cuts (else the focused cut).
  - **Alt+Shift+Down arrow**: gain -1 dB.
  - **Alt+Shift+Page Up**: +3 dB.
  - **Alt+Shift+Page Down**: -3 dB.
  - **Alt+Shift+0**: gain back to 0 dB.

## Keyboard: keys that ask the views to do something
(source: client/input/keyboard.ts, client/input/types.ts)

These send a request to the views over the input bus; what the views then do is outside this section.

- **H** (all ports): open the sheet of keys (help).
- **G** (all ports): search every transcript.
- **C** (lane and cards ports; in the transcript it is left to the transcript): ask Claude to change the cut list in your own words (the chat).
- **N** (lane and cards ports): the note under the selected cut.
- **P** (all ports): go to the next recorded place.
- **Shift+P** (all ports): record where you are (a place).
- **F** in the cards and transcript ports: tap (released before 450 ms) = scroll the cards to the card under the head, once; held 450 ms = turn "follow" on / off (with it on, the card being heard stays centred). The tap is sent on release; the hold is sent once when 450 ms is reached, and then the release sends nothing.
- **Alt+Shift+M** (all ports): Send to Resolve.

## Keyboard: hints and the help sheet
(source: client/input/keyboard.ts, client/featureKeys.ts)

- Every button that has a key shows a separate key hint taken from this table (its first chord), and carries an accessibility shortcut attribute listing every chord for that action. Re-binding a key moves the handler, the hint and the help sheet together.
- Key names shown: arrows as arrow symbols, Comma ",", Period ".", Equal "=", Minus "-", Delete "Del", Page Up "PgUp", Page Down "PgDn", Escape "Esc", letters and digits by themselves.
- The help sheet's keyboard rows are grouped: "Anywhere" first, then "Lane (the clips have the keyboard)" for keys bound to the lane port only. An action with keys in both places (split: B lane-only, Ctrl+B anywhere) gets a row in each.
- A custom keymap can be supplied; a later binding for the same key and the same ports replaces an earlier one, a binding for all ports replaces every earlier binding of that key. DEV ONLY in practice: the app mounts with the default table.
- The full sheet, in order: the "Anywhere" keyboard rows; two fixed rows "Ctrl+K: Search the cards" and "?: This list of shortcuts" (not bound in this table); the lane-only keyboard rows; then the place-specific rows and the features' rows listed below; then any key a feature registered that no row names yet, under "Tools and panels".
- Place-specific rows the sheet lists (the bindings themselves live in other files; the sheet only lists them):
  - Cards (a card has the keyboard): Q / Enter open this cut in its transcript; B trim mode (this cut's words with a blade between them); W open the card's text in full and back (at the compressed densities); Tab / Shift+Tab the next keyboard place: cards, lane, transcript.
  - Trim mode (B on a card): A / S blade one word back / on (playhead follows); Shift+A / Shift+S extend the selection a word; Z collapse the selection to the blade; Enter split at the blade; Del / Backspace remove the selected words; Esc / B leave trim mode.
  - Words picked on the lane: Shift+Left / Shift+Right grow or shrink the pick a word; Del / Backspace take the picked words out; H highlight the picked words; B / Ctrl+B split at the picked words; Alt+Left / Alt+Right on an English pick move the start of the spoken words a word (Alt+Shift: the end); Esc drop the pick.
  - Transcript panel: Space play from the cursor; A / S / Up / Down previous / next sentence; Shift+S / Shift+A extend / shrink the selection a sentence; Z collapse to one sentence; X the cursor's language (as spoken / English); E back to the block under the playhead; C insert the selection at the playhead; Enter insert the selection at the playhead (Shift+Enter to the shelf), with nothing picked the next find match; Alt+Left / Alt+Right as on the lane; Q back to the cards; Shift+F transcript at full window height (Shift+F or Esc puts it back).
  - Search results: A / S / Up / Down previous / next hit; Q / Enter open that transcript there; Space play the hit or stop it; I insert the hit at the playhead (a question goes to the shelf); Esc close the reader, then the search.
  - Tools and panels: 2 open / close the transcript; Shift+T show the selected cut in its transcript; Ctrl+Shift+F search every transcript; T translate the cards that have no English yet; Alt+L English first or as spoken first; O sections and markers overview; M marker (a section) at the head; Shift+N note on the gap before the selected cut; U put the selection in a shelf category; Ctrl+C / Ctrl+X copy or cut the selected cuts; Ctrl+V paste the copied cuts after the cut under the head; Shift+C clip colour of the selected cuts (or the one under the head); Alt+S move the armed edge, or the picked words, to the nearest safe cut; Ctrl+S / Ctrl+Shift+S download the script (.md / .txt); Shift+V video window on / off; Alt+M montage builder; Alt+H shorten the cut; plus the lane feature's own list (imported from another file, not read here).

## Controller: connection, polling and general rules
(source: client/input/pad.ts, client/input/index.ts, client/input/surface.ts)

- Any game controller the browser exposes is used (Xbox-style standard button layout assumed: A 0, B 1, X 2, Y 3, LB 4, RB 5, LT 6, RT 7, View 8, Menu 9, L3 10, R3 11, D-pad up 12, down 13, left 14, right 15; left stick axes 0/1, right stick axes 2/3). Only the first connected controller is read.
- The controller is read once per screen frame, and only while at least one controller is connected. Polling starts on the browser's "controller connected" event (and at load if one is already connected) and stops when the last one disconnects. The frame time used for movement is clamped to 1 to 64 ms.
- The views are told when a controller connects or disconnects (so the shortcuts sheet can list its map), and every time LT crosses its threshold (so the views can show the LT layer).
- On disconnect, when the browser window loses focus, or on unmount, every hold ends without committing: an edge drag in the hand is dropped, a carry (long move) is dropped, an A-skim is undone (rate back to 1x, paused if it was stopped), a shuttle is let go (rate 1x, paused if it started stopped), View / Menu / X holds are dropped, the L3 landing line is cleared, and LT is reported released.
- A stick only counts once it has passed through its centre (both axes within the dead zone) since the controller connected, or since a text box let go of the controller. A drifting stick can never move anything on its own.
- Every command the controller sends that is refused makes the controller rumble (45 ms, half strength, both motors). Hitting a limit during a continuous movement gives one longer rumble (60 ms, 0.7 strength) per contact, not one per frame. Controllers without rumble are silently fine.
- LT counts as held past half its travel (0.5). RT starts acting past a tenth of its travel (0.1).
- D-pad buttons repeat while held: first repeat after 400 ms, then 8 per second (every 125 ms); with LT held, or with a bumper held on the lane (the fade), 15 per second (every 66.7 ms).
- Stick dead zone: 0.15 of travel.
- A text box has the caret: if it is one of the page's own two boxes (the transcript's find box, or the search sheet's query box) the "box" layer applies (below). For any other typing target (an input of any type except button, checkbox, radio, range; a text area; a select; anything content-editable, for example a note, the chat, a name field) the controller is ignored completely, every hold ends, and buttons already down are recorded as down so that letting go of the box does not fire whatever was under the thumb.
- On entering the box layer, every hold ends, the sticks are disarmed, and a button already down when the box took the caret is not treated as a press.
- Which map the buttons read (the controller's port), decided every frame:
  1. One of the page's own two boxes has the caret: the box layer.
  2. The search sheet is open: the results map (the sheet is modal).
  3. The keyboard focus is inside the transcript panel and it has a transcript loaded on its document tab: the transcript map. If instead it is showing its list of transcripts: the sources map. If neither: the lane map.
  4. Anything else: the lane map.
- View and Menu act on release so a tap can be told from a hold (600 ms). With LT held they act at once on press (their LT column). A hold of 600 ms fires its hold action once; the release then does nothing.
- LB and RB act on release so a tap can be told from a hold. Whether LT counts for a bumper's tap is read at the moment the bumper went down.

## Controller: the lane map
(source: client/input/pad.ts PAD_ROWS and verbs)

"The target cut" below is the cut under the head, else the first selected item. "The target items" are the selected items, else the item under the head.

- **A** (bare): play / pause, tap or hold. Tap (released before 280 ms): toggle play on release. Held 280 ms: rate 2x and play if stopped; on release rate back to 1x, and paused if it was stopped when A went down.
- **LT + A**: play the target cut from its start (the head goes to the cut's start, then play). Rumbles with no target cut.
- **B** (bare), in this order of priority:
  - during a bumper edge drag: throws the drag away (nothing committed) and the rest of that bumper hold does nothing;
  - during a carry (LT + right stick long move): cancels the move;
  - with an in or out mark set: clears both marks and shows the hint "The in / out range is off";
  - else with an edge armed: disarms it;
  - else with items selected: clears the selection;
  - else nothing.
- **LT + B**: undo.
- **X** (bare): tap (released before 600 ms) = split the cut under the head at the head, on release. Held 600 ms = insert a 1 second gap at the head (once, at the 600 ms mark); its length can then be dragged with a bumper and the right stick.
- **LT + X**: delete, at once (no two-press arming, unlike the keyboard). With a valid in / out range inside one cut, that range is taken out instead. Otherwise the target items are deleted. Rumbles with nothing to delete.
- **Y** (bare): select the item under the head (replacing the selection; it becomes the range anchor). Rumbles with no item under the head. A second Y within 450 ms on the same item, when that item is a cut and the transcript feature is present, opens that cut in its transcript and puts the keys on the transcript (rumbles if it has no transcript). The first Y does not wait to see whether a second is coming. A gap never opens.
- **LT + Y**: select from the anchor to the item under the head (a range). Rumbles with no item under the head. Never half of a double press.
- **LB** tap: trim the in edge of the cut under the head to the head (as Q). Rumbles if the head is not in a cut.
- **RB** tap: trim the out edge to the head (as W). Rumbles if the head is not in a cut.
- **LT + LB** tap: the head to the target cut's start. **LT + RB** tap: the head to the target cut's end (its last frame). Rumble with no target cut.
- **LB / RB held + right stick**: drag that edge (see "Lane: the right stick" below). The bumper's release commits.
- **LB / RB held + D-pad**: the audio fade on that edge, see below.
- **D-pad Left**: the head 1 second back. **LT + Left**: 1 frame back.
- **D-pad Right**: the head 1 second on. **LT + Right**: 1 frame on.
- **D-pad Up**: previous edit point (selection stays). **LT + Up**: move the target items up one slot; rumbles at the top or with nothing to move.
- **D-pad Down**: next edit point. **LT + Down**: move the target items down one slot; rumbles at the bottom.
- **L3** (bare): while held, a line shows where the head will land (the centre of the visible lane; it follows the left stick's pan). On release the head goes to the centre of the view (clamped to the timeline).
- **LT + L3**: add a marker at the head, or remove the marker standing there (through the markers feature). Shows the feature's message as a hint. Rumbles if the markers feature is absent or refuses.
- **R3**: mark in at the head, and the hint "In at m:ss.ss" (minutes, seconds to two decimals). **LT + R3**: mark out at the head, hint "Out at m:ss.ss".
- **View** tap: put the keys on the transcript (the views decide what that means: on the desk the transcript port, its list when none is open; on the phone the next tab). **View** held 600 ms: open the search sheet. **LT + View**: redo.
- **Menu** tap: put the caret into a find box (see "Menu: the caret into a box" below). **Menu** held 600 ms: open the controller map (the help sheet). **LT + Menu**: the video window on / off.
- **RT**: shuttle, see below.

### Lane: bumper held + D-pad, the fade
- With LB (in edge) or RB (out edge) held on the lane, the D-pad never steps the head; it changes that edge's audio fade on the target cut (fixed at the first D-pad press of the hold):
  - Right: fade one frame longer. Left: one frame shorter. Repeats at 400 ms, then 15 per second.
  - Down: the fade off (0).
  - Up: nothing.
  - The fade is kept between 0 and the cut's length; pressing past either end rumbles. Rumbles if there is no target cut.
- Once a fade was changed during the hold, releasing the bumper does nothing more (no edge-to-head trim), and the right stick no longer drags during that hold.
- A fade cannot be changed while an edge drag is in the hand.

### Lane: the right stick
- **Jog (no bumper, no carry)**: moves the head continuously and it is heard as it moves (scrub grains). Speed in timeline seconds per second: at 60 % of travel it is 1x real time; below that it rises as the 1.7th power of the push, so a light push creeps; from 60 % to full travel it rises in a straight line to 8x. Starting a jog pauses playback. The head stops dead where the stick is let go (no fling). The head is clamped to the timeline.
- **LT + right stick, nothing selected**: the fine jog: the whole travel spans 0 to 1x, rising as the 1.7th power of the push.
- **LB or RB held + right stick: the edge drag**. Right is later for both edges; LT held gives the fine curve. Starting it pauses playback. Nothing is committed while the stick moves: the lane shows a ghost of the new edge.
  - On a cut: the in edge cannot go before the start of the source (second 0) and cannot come within MIN_CUT_S of the out edge; the out edge cannot come within MIN_CUT_S of the in edge; the out edge has no upper limit the controller knows (the reducer refuses past the source's end on release). Touching a limit gives one rumble.
  - With the head in a gap: the bumper drags that gap's length instead. Out edge: right is longer. In edge: right is shorter (the gap's start stays and what follows ripples). Never shorter than MIN_GAP_S.
  - Release of the bumper commits one trim by the distance dragged (if not zero). B during the drag throws it away.
  - If there is no target cut and no gap under the head, the first stick movement rumbles and the rest of that hold is dead.
- **LT held + right stick with items selected: the carry (long move)**. A line is drawn between items, away from the selected block, showing where it would land.
  - A flick (stick moved from rest) moves the line one slot at once; held over, it runs at 2 slots per second at a light push up to 40 at the stop, rising with the square of the push.
  - At either end of the list: one rumble, the line stops.
  - The lane scrolls to keep the line inside the middle two thirds of the view (a sixth in from either side).
  - Starting a carry pauses playback. It needs the selection to include items on the timeline and at least one other item; otherwise it rumbles.
  - Letting go of LT moves the block to the line (nothing if that is where it already is). B cancels. Releasing the stick alone keeps the carry in the hand.

### Lane: the left stick (the view only, never the head)
- Sideways: pan the lane, 14 px per 60 Hz frame at full push (a quarter with LT).
- Up / down: zoom about the centre of the view; per 60 Hz frame at full push the zoom changes by a factor of e^0.045 (about 4.6 %), up zooms in; a quarter with LT. Zoom is clamped by the controller to 0.2 to 400 px per second and by the state to 0.5 to 2000, so effectively 0.5 to 400.
- Each frame of left-stick movement sends a scroll (and a zoom when it changed); the scroll is clamped to 0 .. timeline length.
- With L3 held, the landing line follows the pan.

### Lane: RT, the shuttle
- Pulled past 0.1: playback starts (if stopped) at a rate from 1x at a light pull to 4x at the stop, in steps of 0.05 (the rate is only re-sent when it changes by a step).
- With LT held: 0.5x at a light pull up to 1x at the stop.
- Let go: rate back to 1x, and paused where it got to if playback was stopped when RT was first pulled.
- A shuttle belongs to the port it started in: begun in the transcript it drives the transcript's own preview playback instead (below). In the results and sources ports, RT shuttles the lane's playback.

### Menu: the caret into a box
- In the results port: the caret into the search sheet's query box, hint "The search box has the keyboard: type, then ◀ or ▶ runs it. B or Menu leaves it".
- Else, with a transcript open: the caret into the transcript's find box with its text selected (typing replaces it), hint "The find box has the keyboard: type, then ◀ ▶ walk the matches, A plays the one you are on, Y selects its sentence, X inserts it. ▲ ▼ is the search over every transcript. B or Menu leaves it".
- Else, with the search feature present: the caret into the search sheet's query box (the sheet opens first when shut), with the same "search box" hint.
- Else: rumble.

## Controller: the transcript map ("doc" port)
(source: client/input/pad.ts PAD_DOC_ROWS, portVerb, docEdgeTick)

The panel has a sentence cursor, a selection of sentences with a start and an end, an anchor, a transcript playhead, and a find box with matches. Each button calls the panel; a false answer rumbles. What the panel does inside each call is described from the controller's side only (the panel's code is not in this section).

- **A**: press and release are passed to the panel (a tap plays / pauses the selection, the cued find match, or on from the transcript playhead; held 280 ms it plays at 2x while held and parks on release; the timer runs inside the panel).
- **LT + A**: play the current paragraph from its first sentence.
- **B**: collapse a grown selection to one sentence; pressed again, clear the selection; again, clear the transcript playhead.
- **LT + B**: undo.
- **X**: insert the selection at the head (the lane's head). Rumbles if the insert fails.
- **LT + X**: insert the selection after the selected card. Rumbles if it fails.
- **Y**: right after D-pad Left / Right, the sentence of the find match you are on; otherwise the paragraph under the transcript playhead. Either way the anchor is set at the cursor.
- **LT + Y**: select the run of sentences from the anchor to the cursor.
- **LB** tap: the selection's start one sentence back (grows it). **LT + LB** tap: the start one sentence forward (shrinks it).
- **RB** tap: the selection's end one sentence on (grows it). **LT + RB** tap: the end one sentence back.
- **LB / RB held + right stick**: drag the selection's start (LB) or end (RB) in sentences. Right is later for both. At the jog's 1x it moves 2 sentences per second, scaled by the jog curve; LT gives the fine curve. The selection updates as it goes (nothing to commit). Once the stick has moved, the bumper's release does not also tap. Hitting the first or last sentence stops the drag's accumulation. D-pad presses under a held bumper here are ordinary transcript D-pad presses (no fade).
- **D-pad Left / Right**: the previous / next find match, cued so A plays it.
- **LT + D-pad Left / Right**: meant to be the previous / next result in the open search results list. UNREACHABLE in effect: whenever the search sheet is open the controller is in the results port, so in the transcript this always shows the hint "There is no results list open: Ctrl+Shift+F searches every transcript" and rumbles.
- **D-pad Up / Down**: the previous / next sentence (repeats).
- **LT + D-pad Up / Down**: the previous / next paragraph (mid-paragraph, Up goes to the top of this one first).
- **L3**: place the transcript head on the cursor's first word (A then plays on from it).
- **LT + L3**: switch the cursor's language between the original and English.
- **R3**: select the whole paragraph.
- **LT + R3**: switch the panel to its list of transcripts, cursor on the open one; hint "The pad is on the list of transcripts: ▲ ▼ walk it (LT: five at a time), A opens one, B goes back". Rumbles if refused.
- **View** tap: keys back to the lane. **View** held: the search sheet. **LT + View**: redo.
- **Menu** tap: the caret into the transcript's find box. **Menu** held: the controller map. **LT + Menu**: video window on / off.
- **Right stick** (no bumper): moves the transcript's playhead through the words at the jog's curve (1.7 power below 1x, up to 8x at the stop; there is no fine curve here), later to the right. With LT held it also selects what the head crosses, from where it stood. The head stops dead when the stick is released (any part-word owed is dropped). At the first or last timed word, or with no timed words, one rumble. (The help sheet adds that a head out of sight lands on the first line in view; that is the panel's logic, not read here.)
- **Left stick** up / down: scroll the paragraphs, 26 px per 60 Hz frame at full push (a quarter with LT). Sideways does nothing. It never moves the head.
- **RT**: shuttle the transcript's preview: rate 1x to 4x (LT: 0.5x to 1x), steps of 0.05; let go: the panel is told to let go (back to 1x, parked if the trigger started it).
- Leaving the transcript with the right stick still pushed drops the playhead's part-word.

## Controller: the list of transcripts ("sources" port)
(source: client/input/pad.ts PAD_SOURCES_ROWS)

- **A**: open the transcript the cursor is on.
- **B**: back to the transcript that is open; if none is open, the keys go to the lane.
- **LT + B**: undo.
- **D-pad Up / Down**: previous / next transcript in the list (repeats). Rumbles at an end or with an empty list.
- **LT + D-pad Up / Down**: five back / five on.
- **View** tap: back to the lane. **View** held: the search sheet. **LT + View**: redo.
- **Menu** tap: the caret into a box by the Menu rules above (with no transcript open, the search sheet's query box). **Menu** held: the controller map. **LT + Menu**: video window.
- X, Y, LB, RB, L3, R3, D-pad Left / Right and both sticks do nothing here. RT shuttles the lane's playback.

## Controller: the search results ("results" port, the search sheet open)
(source: client/input/pad.ts PAD_RESULTS_ROWS)

- **A**: open the hit under the cursor in its transcript, cued.
- **LT + A**: listen to the hit where it stands, the sheet kept open.
- **B**: close the sheet. **LT + B**: undo.
- **D-pad Up / Down**: the previous / next hit (repeats). Rumbles at an end or with no hits.
- **View** tap: leave the list (closes the sheet). **View** held: asks for the search sheet (already open). **LT + View**: redo.
- **Menu** tap: the caret into the sheet's query box, with the search-box hint. **Menu** held: the controller map. **LT + Menu**: video window.
- X, Y, bumpers, L3, R3, D-pad Left / Right and both sticks do nothing. RT shuttles the lane's playback.

## Controller: a page box has the caret (the box layer)
(source: client/input/pad.ts PAD_BOX_ROWS, boxPress)

Applies only to the transcript's find box and the search sheet's query box. Only the buttons below are read; all other buttons, both sticks and both triggers are ignored. There is no D-pad repeat here. LT is read only for X.

- **A**: in the find box, play the cued match (a tap: press and release sent together). In the query box: nothing.
- **B**, **View**, **Menu**: leave the box with its text kept, the keys back on the paragraphs (find box) or the sheet (query box).
- **X**: in the find box, the sentence of the match you are on becomes the selection and anchor, then it is inserted at the head; the caret stays in the box for the next one. **LT + X**: the same, inserted after the selected card. In the query box: rumble. Rumbles with no match or if the insert fails.
- **Y**: in the find box, the sentence of the current match becomes the selection and anchor, the caret leaves the box, hint "That sentence is selected: X inserts it at the head, LB / RB grow it, A plays it". In the query box: rumble.
- **D-pad Up or Down** (same action): swap to the other box.
  - From the find box: leaves it and puts the caret in the search-every-transcript box, carrying the find text across if that box is empty; hint "The search over every transcript has the keyboard: ◀ or ▶ runs it. ▲ ▼ is this transcript’s find box again". Rumbles if either feature is missing.
  - From the query box: needs an open transcript, else hint "No transcript is open, so there is no find box to go to" and rumble. Otherwise leaves the query box, closes the search sheet, and puts the caret in the transcript's find box, carrying the query text across if the find box is empty; hint "This transcript’s find box has the keyboard: ◀ ▶ walk the matches". Rumbles if the find box cannot take the caret.
- **D-pad Left / Right**: in the find box, previous / next match, cued. In the query box, either one runs the search (rumbles with nothing typed).

## Controller: the shortcuts sheet's controller rows
(source: client/input/pad.ts padHelp)

- The sheet lists, in order: the lane map (one row per bare action, then one per LT action); five stick / trigger rows ("Left stick: Pan the lane (sideways) and zoom it (up and down); LT for fine"; "Right stick: Jog the head; with LB or RB held, drag that edge"; "LT+Right stick: Clips selected: carry them ... Nothing selected: the fine jog"; "RT: Shuttle: 1× at a light pull up to 4× · let go: parked there if it was standing still"; "LT+RT: Shuttle at half speed up to 1×"); the transcript map prefixed "Transcript: " (without View and Menu) and its four stick / trigger rows; the results map prefixed "Search results: "; the list-of-transcripts map prefixed "The list of transcripts: " plus its B row; and the box rows ("In the find box: ...", with Up and Down as one row "D-pad ▲ ▼", plus "LT+X: In the find box: insert that sentence after the selected card").

## Mouse, touch and pen on the lane: thresholds and hit testing
(source: client/input/pointer.ts)

- Three pointer kinds: mouse, touch (a finger), pen. A pen behaves like a mouse except for its thresholds.
- Click / tap slop (how far a pointer may wander and still be a click): mouse 4 px, pen 6 px, touch 10 px.
- Edge grab zone either side of an item's edge: mouse 6 px, pen 10 px, touch 22 px (half of a 44 px handle). For a narrow item the zone shrinks to a third of the item's drawn width.
- An item drawn narrower than mouse 24 px, pen 28 px, touch 30 px has no edges to grab: the whole item is its body (it moves, never trims). To trim it, zoom in.
- What a press lands on, in order:
  1. An item too narrow to trim under the pointer: that item's body.
  2. Mouse or pen in an item's body, clear of its own edge zones: that item's body (a neighbour's edge zone does not win).
  3. An edge within its grab zone. On touch, only SELECTED items have edges (so a finger on a butted join pans instead of trimming). Where two edges compete, a selected item wins, then the item the pointer is inside, then the nearer edge.
  4. Otherwise the item under the pointer's body, or bare lane.
- Time 0 sits where the lane draws it: the left of the lane's track element plus its 1 px border (measured at every press).
- Pointer moves are coalesced to one per screen frame (a high-polling mouse would otherwise send hundreds a second); a release processes any waiting move first.
- The browser is told not to scroll or zoom the page under lane gestures.
- The lane may report bands ("track", "ruler", or none). The ruler band scrubs like bare lane; a press in no band is ignored. DORMANT as wired: the app attaches the lane with no band layout, so the whole lane is "track".
- No gesture starts with no cut list open. Only one gesture at a time (except the second finger of a pinch). Any new press stops a coasting pan dead.
- Right button (secondary) presses are ignored here (the context menu belongs to the views). Double-click is not handled here (no double-click behaviour exists in this file).

## Mouse and pen gestures on the lane
(source: client/input/pointer.ts)

- **Press on bare lane**: the head goes there at once (no scrub sound). **Drag** from bare lane: the head follows the pointer and is heard as it moves (scrub grains). Clamped to the timeline.
- **Click an item's body** (released within the slop): select it, replacing the selection. **Ctrl+click** (Cmd on Mac): toggle it in the selection. **Shift+click**: select the range from the anchor to it (handled through the box path below; Shift+click on bare lane moves the head there).
- **Drag an item's body** (past the slop): move. If the item is selected, the whole selected block (cuts and gaps, in timeline order) moves; otherwise only that item. While dragging, a ghost and an insertion caret show where it would land: in front of the first other item whose middle is past the pointer's time, else after the last. Release commits one move. Nothing happens if the drop leaves the order unchanged (a drag ending where it began is never a hop into the next section).
- **Shift+drag** (from anywhere): box selection. Every item the box's time span touches is selected, replacing the selection; an empty box clears it. **Ctrl+Shift+drag** adds the touched items to the selection (an empty box then changes nothing). The views draw the box while dragging. A Shift press that never moves is the range click.
- **Click an edge** (no movement): arm that edge for the keys (the frame / second keys then trim it).
- **Drag an edge of a cut**: ripple trim or extend. A ghost shows the new edge while dragging. Clamped as the input knows: an in edge never before source second 0 and never within MIN_CUT_S of the out edge; an out edge never within MIN_CUT_S of the in edge; no upper limit (the reducer refuses past the source's end). Release commits one absolute edge trim (if the edge moved).
- **Drag an edge of a gap**: resize the gap. Out edge later = longer; in edge later = shorter (the gap's start stays and what follows ripples). Never under MIN_GAP_S. Release commits one gap-length change (if it changed).
- **Middle-button drag**: pan the lane (the browser's own middle-click autoscroll is suppressed). On release the pan coasts (see the coast below).
- **Wheel**: scroll the lane sideways. Horizontal wheel movement is used when present, else vertical; with Shift, vertical is preferred, else horizontal. The distance is the wheel delta in px (lines count as 16 px, pages as 400 px) divided by the zoom. Clamped to 0 .. timeline length.
- **Alt+wheel** or **Ctrl+wheel** (Ctrl is what a trackpad pinch sends): zoom about the time under the pointer. 100 px of upward wheel zooms in by about x1.28 (factor e^(0.0025 per px)); downward zooms out. Clamped to 0.2 to 400 px per second (then 0.5 to 2000 by the state). The page itself never zooms or scrolls from a wheel over the lane.
- **Escape** during a gesture (captured before any other key handler): a box selection is dropped; an edge drag that has moved, or a move drag, is dropped (nothing committed) and the key is consumed. Escape on an edge that was pressed but not moved is not consumed (it goes on to the keyboard's Escape). After Escape, the rest of that pointer's movement and release are ignored.
- **Pointer cancelled by the browser** (or capture lost): the gesture is thrown away, nothing committed.

## Touch gestures on the lane
(source: client/input/pointer.ts)

- **Tap an item** (released within 10 px): select it (replacing). Modifier keys on a touch press, if present, give toggle / range as with the mouse.
- **Tap bare lane**: the head goes there.
- **One finger dragged** (past 10 px, before a long press, anywhere not on a selected item's handle): pan the lane. On release it coasts.
- **Long press an item** (500 ms without moving past the slop): the item (or the selected block it belongs to) is lifted; the views are told which card was lifted. Then dragging moves it, with the same ghost, caret and drop rule as the mouse. Releasing commits the move even with no drag after the lift if the place differs (a lift counts as moved).
- **Drag a SELECTED item's edge handle** (22 px either side): trim the cut, or resize the gap, as with the mouse. Touching a handle and lifting without moving arms that edge.
- **Two fingers**: pinch zoom. The zoom changes by the ratio of the fingers' current distance to their distance at the start; the timeline second that was under the fingers' starting midpoint stays under their current midpoint. The second finger abandons whatever the first had started (a pending long press, a move, an edge drag), with nothing committed. A third finger is ignored. The pinch ends when either of its two fingers lifts; the other finger is then ignored until it lifts too.
- **Shift+drag box selection is mouse and pen only.**

## The coast after a pan
(source: client/input/pointer.ts)

- Applies to a one-finger pan and to a middle-button pan.
- The release speed is measured over the last 80 ms of movement (up to the last 12 samples; at least 4 ms apart). Under 0.05 px per ms it is a plain stop.
- Above that, the lane keeps scrolling, slowing by a factor of 0.985 per 60 Hz frame, until the speed falls under 0.02 px per ms or the lane reaches either end of the timeline.
- Any press on the lane stops it at once; the lane being detached stops it.

## Commands: how the editor's state takes a command
(source: client/state/store.ts, client/state/commands.ts)

- Every keyboard, controller and pointer action, and every view, changes the editor only by sending a command. Commands run synchronously: the screen state is updated before the sender continues; saving to the device, sending to the server and the audio follow behind.
- A command that throws an internal error never takes the editor down: it posts an error notice "internal: <message>" and returns a refusal.
- Edit commands (listed under "Editing commands") are planned into exactly one operation (a batch when several are needed, so it is one undo step), applied locally at once, queued for the server, and recorded as one undo step. Then the selection is moved if the plan says so, the head is kept (see the head rule) for edge edits, and any planned sentences are posted as info notices.
- Any refusal posts its sentence as a notice: level "info" for the "noop" kind, "warn" otherwise. Notices are kept newest last, at most 50.
- A command with no cut list open is refused "no cut list is open", except the purely view or transport ones that do not need one (see each).
- A command type the store does not recognise in the current state returns "<type> does nothing here" without a notice.

## Commands: the head rule after an edit
(source: client/state/headKeep.ts, client/state/store.ts)

- Applies after edge edits (trim to an absolute second, trim by an amount, trim to the playhead, range removal, gap resizes, a trim that deletes) when playback is stopped. It does not apply while playing.
- Before the edit the item under the head is remembered with the source second the head is on (for a gap: how far into the gap).
- After it, the head goes to that same source moment of that same cut, wherever earlier edits have slid it. If the edit took that moment away, the head goes to the nearest surviving point inside the cut; at the tail that is the cut's last frame (end minus one frame), never the next cut's first frame.
- After a range is taken out of the middle of a cut, the head goes to whichever of the two pieces now holds its moment; if the removed part held it, the last frame of the first piece.
- A head in a gap stays the same distance into that gap; if a resize took that distance away, the gap's last frame.
- A head past the end, or whose cut left the timeline (trimmed away), keeps its timeline time (clamped to the new length).
- An edit never carries the head FORWARD: if the rule would put it later than it was (for example an extend added material before the head's moment), it stays where it is on screen. Backwards it follows.
- The same rule (including "never forward") is applied when the cut list changes because of another editor's edit, or the server's echo of one's own, while stopped.
- After an undo or redo while stopped, the head is kept by the same rule but without the "never forward" limit.
- The head is always clamped to 0 .. timeline length, and the playhead's "cut under the head" and "source second" are re-derived after every change.

## Selection and navigation commands
(source: client/state/commands.ts reduceSelection, client/state/store.ts)

- **select** (items, mode): never refused; with no cut list it still records ids.
  - replace (default): the selection becomes those items in document order; the anchor is the first given, the keyboard focus the last given; any armed edge and selected marker are cleared.
  - add: the items are added; the anchor stays (or becomes the first given); the focus becomes the last given; the selected marker is cleared; the armed edge is kept.
  - toggle: each given item flips in or out; the anchor is kept if still selected, else becomes the last given (none if the selection is empty); the focus becomes the last given; the selected marker is cleared; the armed edge is kept.
  - range: from the anchor (or the first given if none) to the last given, in document order (timeline then bench), inclusive; the focus becomes the last given. With no cut list or no item given, nothing changes.
- **selectMarker** (id or none): selects one heading or note row (markers are selected one at a time), keeping the cut selection.
- **focusStep** (by, extend): moves the keyboard focus by that many items along the timeline (gaps included), clamped to the ends. Starting from the focused item, else the item under the head, else from before the first (forward) or after the last (backward). Without extend the selection becomes just that item (anchor and focus on it). With extend the selection becomes the range from the anchor (or the old focus) to the new item. Nothing happens with no cut list or an empty timeline.
- **armEdge** (item, in / out): arms that edge for the frame / second keys. **disarm**: clears it.
- Whenever the cut list changes, ids that no longer exist are dropped from the selection, anchor, focus, marker and armed edge.

## Transport commands
(source: client/state/store.ts, client/state/commands.ts seekTarget)

- **play**: refused with no cut list ("no cut list is open") and when this page has no audio engine ("playback is not available here"). Already playing: nothing. At the end of the timeline, play starts from 0. The view follows the head while playing. In the Android app shell, other apps' audio is ducked while playing and released on pause or stop.
- **pause**: always accepted; the head stays where the audio clock had got to.
- **togglePlay**: pause if playing, else play.
- **seek** (t, scrub): the head to t, clamped to the timeline. With scrub set and playback stopped, a short grain of audio sounds there (the dragged-head sound); without scrub, silent. Needs a cut list.
- **nudge** (by seconds): the head by that amount, clamped. Needs a cut list.
- **seekCut** (item, start or end): the head to the item's start, or to its end minus one frame. Nothing if the item is not on the timeline.
- **stepCut** (by): the head to the start of the item that many items away. Gaps are stops. Going back from more than 0.25 s inside an item counts its own start as the first step. From a gap boundary or past the end, counts from the next item start. Clamped to the first and last item. Nothing on an empty timeline.
- **scrubSource** (cut, source second): while stopped, a grain of that cut's clip at that source second (an edge being dragged heard as a temporary head). Always accepted; silent if the audio engine has no scrub support.
- **setRate** (rate): playback rate, clamped to 0.25 to 4 (an invalid number means 1). Always accepted; an engine without rate control plays at 1x. A reload starts at 1x.
- Audio problems are reported as notices: "playback is not available: <reason>" (once, when the audio for the cut list fails to load), "playback: <reason>" (the engine reports an error), "could not play: <reason>" (a play that failed; playback is marked stopped).
- The audio engine's clock is the head while playing; when the engine stops or errors, the editor marks playback stopped. A play still loading when the editor paused is stopped when it starts.

## The in / out range commands
(source: client/state/commands.ts reduceMarks)

- **mark** (in or out, optional t): sets that mark at t, else at the head; never below 0. Setting an in after the current out drops the out; setting an out before the current in drops the in, so in <= out always. An invalid t changes nothing. Always accepted; not an edit, not undoable, not synced.
- **resetMark** (in, out or both): clears that mark (or both).
- The marks are cleared when a range delete succeeds and when another cut list opens.

## View commands
(source: client/state/commands.ts reduceView, client/state/store.ts)

- **setView** (cards, lane, edit, transcript, bench): which view is shown. Starts at "cards".
- **zoom** (px per second, optional time to hold still): clamped to 0.5 to 2000 px per second (an invalid value keeps the current zoom). The given time (default: the left edge) keeps its screen position; the scroll is adjusted and never goes below 0. Starts at 40 px per second.
- **scroll** (t): the lane's left edge at timeline second t, never below 0 (no upper clamp in the state; the inputs clamp to the timeline length). An invalid value keeps the current scroll.
- **setCompact** (on / off): phone layout. Sent at start-up and whenever the window crosses "width 700 px or less, or a coarse pointer".
- **dismissNotice** (id): removes that notice.
- **retrySync**: reconnect to the server at once, even after a final error.

## Editing commands
(source: client/state/commands.ts planEdit, client/state/store.ts runEdit)

The reducer (the shared edit engine, outside this section) can still refuse any planned operation with its own sentence; those refusals are not listed here. "Selection after removal" means: the next surviving timeline item after the last removed one, else the one before the first removed, else nothing.

- **trimEdge** (item, in / out, to source second): one edge to an absolute source second (lane edge drags, E / Shift+E).
  - For a gap id the value is taken as the gap's new length (see setGap).
  - Refused: "that cut is no longer in the cut list" (the cut is gone); "that edge is not a number of seconds" (invalid value).
  - A shortening that would leave less than MIN_CUT_S: for a cut on the timeline it becomes a delete (the cut is staged), with the info notice "<clip> trimmed away -- staged under ## <shelf title>" and the selection after removal; for a cut on the bench it is refused "that would leave nothing of the cut -- delete it instead".
  - Otherwise one edge change. If it shortens the cut below the length of either of its audio fades, the info notice "cut <N>: the audio fade is longer than what is left of the cut, so it is shortened to <X.X> s" (N is the cut's place on the timeline; the clip name when not on the timeline).
  - Selection unchanged. Head rule applied.
- **trimBy** (item, in / out, by seconds): the edge moved by an amount (armed-edge keys, controller bumper drag). On a gap: the out edge by +x makes it longer by x, the in edge by +x shorter by x. Otherwise as trimEdge from the edge's current value. Refused "that gap is no longer in the cut list" / "that cut is no longer in the cut list".
- **trimToPlayhead** (in / out): the cut under the head, that edge to the head's source second. Refused "put the head inside a cut first" when the head is in a gap or past the end. Then as trimEdge.
- **deleteRange**: takes the in / out range out. Refused "the in / out range has to lie inside one cut" when either mark is missing, when they are less than one frame apart, or when the range is not inside one cut. Then as removeRange on that cut. On success both marks are cleared.
- **removeRange** (cut, from, to source seconds): the range is clamped to the cut. Refused "the selection is empty -- nothing removed" when invalid or shorter than MIN_CUT_S. A range reaching both ends (within MIN_CUT_S) is the whole cut: trimmed away (staged) as above. Reaching only the start: a trim of the in edge to the range's end. Reaching only the end: a trim of the out edge to the range's start. Otherwise the middle is removed and the cut becomes two cuts (the second gets a new id). Head rule applied.
- **splitAtPlayhead**: splits the cut under the head at the head's source second. Refused "put the head inside a cut first". The new second piece becomes the selection. The head stays at its timeline time.
- **split** (cut, at source second): the same at a given point.
- **move** (items, place): moves the items to a place (in front of an item, which joins its section, or after an item). Refused "select a cut first" with no items. The moved items become the selection.
- **delete** (optional items): the items given, else the selection, else the keyboard-focused item. Refused "select a cut first" with none. Only items on the timeline are acted on; if none of them are, refused "those cuts are already staged -- discard them from the shelf to remove them for good". Cuts are staged (moved to the bench, under a shelf named after the last section heading above each cut; a heading longer than 60 characters, or containing comment markers, or starting with #, is not used). Gaps are removed outright (undo puts them back). Info notice, the parts joined with "; ": "1 cut staged under ## <shelf>" or "<N> cuts staged under ## <shelf>, ## <shelf>", and "gap taken out" or "<N> gaps taken out". Selection after removal.
- **stage** (optional items, optional shelf place): the given (else selected, else focused) timeline items moved to the bench. Refused "select a cut first" when none of them is on the timeline. Selection after removal. No notice. (No key, button or gesture in this section sends it.)
- **unstage** (items, optional place): bench items back onto the timeline, by default after the item under the head, else at the end. Refused "select a cut first" with none. They become the selection.
- **setGap** (gap, seconds): a gap's new length. Refused "that gap is no longer in the cut list" or "a gap is a number of seconds". Below MIN_GAP_S: on the timeline the gap is taken out, with the info notice "gap taken out" and the selection after removal; elsewhere refused "a gap shorter than a frame is no gap -- delete it instead". Head rule applied.
- **insertGap** (seconds, optional place): a new gap. Refused "a gap shorter than a frame is no gap" below MIN_GAP_S or invalid. Default place: at the nearer boundary of the item under the head (before it when the head is in its first half, after it otherwise), else at the end. The new gap is selected, so its edges are the ones trimmed next. The head keeps its timeline time.
- **setFades** (cut, in fade and / or out fade seconds): sets the cut's audio fades as given. No checks in this layer.
- **setGain** (optional items, dB): sets the gain of the given (else selected, else focused) items. Refused "select a cut first".
- **nudgeGain** (by dB): each selected (else focused) cut's gain changed from its own value by that amount, rounded to 0.1 dB; gaps skipped; one undo step for all. Refused "select a cut first", or "that cut is no longer in the cut list" when none of them is a cut.
- **setColour** (optional items, colour or none): the clip colour. Refused "select a cut first".
- **setNote** (cut, text or none): the note on a cut.
- **addMarker** (section / note / note row, title, optional before): a new section heading or note (a note row gets a note id, the others a heading id), placed in front of the given item, else in front of the first selected timeline item, else in front of the item under the head, else with no item (as the reducer places it). No colour.
- **edit** (any raw operation): passed straight to the reducer as one undo step. Used by views for operations that have no dedicated command.
- A successful edit returns the operation and its sync id; a view can ask to be told when the server has taken ("saved") or refused ("dropped") that operation. It is never told if the cut list is closed first.

## Undo and redo
(source: client/state/undo.ts, client/state/store.ts runUndo)

- Undo is per browser: only this editor's own edits are undone, never anybody else's. Each step stores the exact inverse operation and a fingerprint of the rows it touched as they were right after the edit (and the order of the cut list, when the edit re-arranged it).
- **undo**: takes the newest step. **redo**: the newest redo step.
- Refused (info) "nothing to undo" / "nothing to redo" with an empty stack; "no cut list is open".
- Refused when somebody else's edit has since changed a row the step touches: "cannot undo the <label>: <what> was changed since by another edit" (or "cannot redo ..."), where <what> is "cut <N>", "the order of the cut list", or "that part of the cut list". The step is then thrown away. Undoing one's own later steps first never trips this.
- The undo is sent to the server carrying the same fingerprint, so the server refuses it too if an edit crossed it on the wire; a refusal at apply time says "cannot undo the <label>: <reason>" and throws the step away.
- Labels (the <label> above) are names of what the step was: trim, split, move, delete, stage, placing, shelf move, discard, insert, paste, new gap, gap resize, fade, gain change, colour change, note, highlight, words, gap note, section summary, marker, marker edit, marker move, marker removal, section move, new category, category removal, category rename, saved sequence, sequence restore, sequence rename, sequence removal, settings change, edit (a batch or anything else), undo.
- A successful undo moves its redo onto the redo stack; a successful redo moves its undo back onto the undo stack. Any new edit clears the redo stack.
- At most 200 steps are kept on each stack (oldest dropped).
- When the server refuses one of this editor's edits, every undo / redo step naming it is forgotten.
- The head after an undo or redo (while stopped) is kept on its moment as described in the head rule.
- The history survives a reload: per cut list, on this device, written 250 ms after it last changed (a run of nudges is one write), and at once when the cut list closes or the store is flushed. On opening a cut list it is read back before any edit can be made; anything malformed is dropped, the newest 200 kept. If storage refuses, undo still works until the page goes.
- Opening another cut list starts with that list's saved history (or empty).

## Opening a cut list, sync and offline work
(source: client/state/store.ts open/close, client/state/sync.ts, client/state/replica.ts)

- Opening a cut list clears the selection, the in / out range, the playhead (to 0, stopped), the notices, and the undo history (then loads the saved one), and shows the connection as "connecting".
- The editor shows what this device has (the last saved copy plus every unsent edit) at once, before the server answers. If the device has no saved copy, the cut list is also asked for over HTTP (GET /api/project?key=...), which the service worker may answer offline; the live connection's answer replaces it.
- The source clips' lengths are asked for (the media sources list) so that extends can be limited to the source; until it answers, extends are not limited by source length.
- Every edit applies on screen immediately and is queued. An edit is sent only once it is saved on this device. At most 64 edits are on the wire at once, always in order. After every reconnect, everything not yet confirmed is sent again with the same id, which the server de-duplicates.
- Connection states shown: offline, connecting, syncing (connected with edits waiting), live (connected, nothing waiting), error. The count of waiting edits and the last error sentence are shown with it.
- Reconnect after any drop with a random wait (full jitter) between 250 ms and a cap that doubles per attempt up to 10 s. Immediately when the browser says it is online again. The browser saying it is offline shows "offline" unless the connection is live.
- A ping every 15 s; a connection that has heard nothing for 45 s (three pings) is treated as dead and reconnected at once.
- After connecting, the server's fingerprint of the cut list is checked against this device's copy; on a mismatch the warning "this editor's copy did not match the server's, so it was reloaded from the server" and a full reload from the server.
- A gap in the server's version numbers, or a server change that will not apply here, makes the editor start over (reconnect, or ask for the whole cut list).
- When the server refuses one of this editor's edits: the warning "your <label> of cut <N> was refused: <reason>" (or "your <label> was refused: ..."), the edit disappears from the screen, and its undo steps are forgotten.
- An edit made here that has not yet left the device and no longer applies after other people's edits arrive is dropped with the warning "your <label> of cut <N> no longer applies: <reason>". An edit that has (or may have) reached the server is never dropped on a local guess; it waits for the server's verdict.
- Messages the server sends as notices are shown as notices.
- Server errors: "proto", "not-found" and "bad-key" are final: the connection shows "error" with the server's sentence as an error notice, and no retry happens until "Retry now" (retrySync). Any other server error (for example overload) shows "connecting" with the sentence and retries slowly (the wait cap starts at the sixth attempt's, which is the 10 s maximum).
- A connection refused before it ever opened, while online, triggers a check of the sign-in (GET /api/session). If that answers 401: the status error "Your sign-in has expired: sign in again to send your edits", and no retries until asked. Otherwise the normal retry.
- If this device's saved data cannot be read: the warning "could not read what this device saved (<reason>); loading from the server".
- If this device refuses to save edits (storage full, private mode): the error notice, once, "this device could not save your edits (<reason>): they are kept only until they reach the server"; edits are still sent.
- The saved copy of the cut list is written 500 ms after it last changed, at once when the page is hidden, and when the cut list closes. Closing a cut list (or opening another) writes everything, stops playback and closes the connection.

## What is kept on this device
(source: client/state/persist.ts)

- One browser database, "timeline-cards-editor", version 1, with three stores: the last confirmed copy of each cut list (with its version and fingerprint), the unsent edits, and small values (this install's client id "web-<random id>", the last cut list opened, and the undo history per cut list).
- Unsent edits are kept per browser tab, so two tabs on one cut list never overwrite each other's. Opening a cut list adopts every tab's unsent edits (the union, each edit once) in one step, so a closed tab's edits are sent by the next one to open it. An edit held by two tabs is sent by both and applied once.
- Writes are serialised, so a slow write can never land after a newer one. Empty per-tab slots are removed.
- When the browser offers no database (for example a private window), everything is kept in memory only: nothing survives a reload.
- Another tab upgrading the database makes this tab close its connection to it (its writes then fail loudly rather than block the upgrade).

## Start-up
(source: client/state/boot.ts)

- Which cut list opens: "?key=<path>" in the address, else the last one this device opened, else the most recently modified one in the server's list (GET /api/projects). The key is written back into the address so a reload, online or not, opens the same one.
- The audio engine is created with "keep the screen awake" on; a clip kept on this device plays from the device copy, online or not. If the browser has no web audio, editing still works without playback.
- Phone layout is on when the window is 700 px wide or less or the pointer is coarse, and follows changes.
- The input is bound to the lane element, and rebound whenever the views redraw the lane. Controller drag previews and controller requests (the map, the next port) are passed to the views. If a controller was already connected at start, the views are told once.
- Everything is written to the device when the page is hidden.
- The service worker "sw.js" is registered on http and https pages.
- The Android app shell, when present, gets "duck on / off" around playback.
- DEV ONLY: the running editor is exposed as a debug handle on the page (window.tc) for tests.

## Looks redundant or overlapping

- Many actions have two or three keys: one frame back is Left arrow and Comma; one second is Shift+arrow and Z / X; edit points are A / S and Up / Down; split is B (lane), F (lane) and Ctrl+B; a 1 s gap is Shift+Insert and Shift+G; redo is Ctrl+Shift+Z and Ctrl+Y.
- F means "split" in the lane port but "go to the head's card / follow" in the cards and transcript ports.
- Three ways to trim an edge to the head or near it: Q / W (and LB / RB taps), E / Shift+E (ripple-extend the nearer or other edge), and the armed edge plus frame keys; plus lane edge drags and controller bumper drags.
- Three "faster playback" mechanisms: Space held (2x skim), controller A held (2x skim), controller RT (1x to 4x shuttle).
- Delete behaves differently by device: the keyboard arms and needs a second press within 3 s; the controller's LT + X deletes at once; a gap deletes at once on the keyboard.
- Two zoom ranges: the input layer clamps to 0.2 to 400 px per second, the state to 0.5 to 2000. Keyboard zoom is only clamped by the state, controller and pointer zoom by both.
- Two "frame" fallbacks: 29.97 fps in the input layer, 30 fps in the state (deleteRange, the head rule).
- Two typing-detection rules: the keyboard ignores inputs except button / checkbox / radio / submit / reset / range / color / file / image; the controller's rule only exempts button / checkbox / radio / range.
- Escape (keyboard, and the lane pointer's capture) and controller B both cancel in priority order, but in different orders: the keyboard disarms the edge, then clears the selection, and never clears the in / out range; the controller clears the range first.
- Opening a cut in its transcript: controller Y twice; the help sheet also lists Q / Enter on a card and Shift+T (bound elsewhere).
- Searching every transcript: G (this table), Ctrl+Shift+F (listed in the help sheet, bound elsewhere, and named in a controller hint), and controller View held.
- The help sheet lists "Ctrl+K" and "?" as fixed rows without any binding in these files.
- The controller binding type "PadBinding" is declared and never used (the controller uses the row tables).
- The controller's "setView round" fallback for View exists only when there is no input bus, which the app always has.

## Claims the code does not back

- The controller's header comment, and comments at the bumper release, say that once an edge drag or a fade lands, A plays the join (from 1 s before the new edge to 1.5 s after, then parks). The code never sets the offer: the function that would offer it does nothing, the audition timer is never started, and A plays from the head. UNREACHABLE: the join audition.
- The transcript map's "LT + D-pad Left / Right: the previous / next result in the open results list" cannot happen: with the results list open the controller is always in the results port. It always shows "There is no results list open" and rumbles.
- The keyboard's Delete comment says "a different selection, or three seconds, drops the arming". Changing the selection does not disarm; only the 3 s timer, or a next Delete with different targets (which re-arms for those), does.
- The Delete key's help label says "with an in / out range on the lane, take the range out"; the code does this only while the lane's strip itself has the keyboard.
- The seek command's comment mentions "F8 held" as a scrub source; nothing in these files binds F8.
- The lane pointer supports a separate "ruler" band that scrubs; the app attaches the lane without a band layout, so it never applies.
- The state folder's index file calls itself a "stub" to which the store and sync client would be added; they exist and are not re-exported from it.

## Could not determine

- Whether the transcript panel, the cards and the lane's word pick mark their own keys (X, A, S, Z, E, Space, H, B, Enter) as handled before this global keyboard sees them. The global keyboard listens on the window in the normal (bubbling) phase and skips only keys already marked handled. If a feature does not mark them, both fire (for example X in the transcript would also move the head one second on, H on a word pick would also open the help sheet).
- What the views do with each request on the input bus (next port, follow, go to the head's card, the delete arm cue, the lifted card, hints, help, search, chat, note, places, send, video).
- Every refusal the shared reducer makes for an operation (extend past the source's end, moves, splits too close to an edge, fades); that code is outside this section.
- The exact shelf title format produced for staged cuts (made by the reducer).
- What the transcript panel does inside each controller call (sentence stepping, the 2x hold in the panel, how a head out of sight lands, insert after the selected card); only the controller side is read here.
- Where the lane's double-click and the cards' own keys are bound (the help sheet lists them; they are not in these files).
