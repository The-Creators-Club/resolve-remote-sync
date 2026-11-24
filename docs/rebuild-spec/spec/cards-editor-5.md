# Timeline Cards: the editor, part 5 of 5

This part covers the editor on a phone and with a game controller, how fast and smooth it must be, the page itself (its panels, header, menus, messages and windows), opening episodes and cut lists and the editor always being there, and what the editor shows when the help for the editing program is switched off or Resolve is not running.

## Phone and game controller

### Timeline Cards installs on a phone as its own app that opens on the episode list

Timeline Cards can be added to a phone's home screen as an app called "Timeline Cards" (short name "Cards"), opening full screen without browser bars. Whichever Timeline Cards page it is installed from, the one app opens on the episode list, and every episode and cut list opened from there stays inside the app. Its icon is the Timeline Cards mark, shaped to fit any phone's icon style, and the colours the phone paints around the app match the editor's look. Installing it needs no sign-in, and what the phone fetches to install it reveals nothing private; opening an episode then asks for the dashboard's sign-in as in a browser.

The installed app:

- starts after the server has restarted with nobody having to open anything first, and keeps the same identity on the phone for its whole life;
- with no network, shows the last episode list it had within about 8 seconds, marks the cut lists saved on the phone, and opens them;
- takes a new version of the editor the next time it is opened, and never stays silently on an outdated copy.

The phone editor is reached over a secure address, since phone browsers grant full screen, vibration and installing only there. It asks for full screen on the first touch, and it works unchanged when a phone refuses full screen, vibration or installing. Playback and full screen are asked for inside the touch that wants them (phones start sound only inside a tap), sound is unlocked by the first touch, and a refusal is shown. The installed app covers Timeline Cards' own pages only: following a link to another part of the dashboard leaves the app's frame for the browser.

- Who: anyone; opening an episode needs a sign-in.
- Name and search words: the phone app. Search words: install, home screen, phone app, Cards app, offline.
- Phone and desk: on a desk the same pages are used in a browser window or in the editor's own window from the app on the editor's computer.

### The Android app gives the phone editor a full screen that never moves

An Android app of its own wraps the same editor for phones where the browser cannot give a steady full screen.

{{33-103}}

On Android, opening the lane turns the phone to landscape, and a copy the editor saves lands in the phone's Downloads. The phone's Back opens the app's menu on every Android version, and the app's settings and its update are reachable from the page as well. The app checks for, downloads, verifies and installs its own updates from its settings, keeping its settings and every cut list saved on the phone. Every update is signed so that it installs over the version before it: an update never forces an uninstall that would lose work kept on the phone.

- Who: anyone who installs it; it opens the studio's dashboard and asks for the same sign-in.
- Name and search words: the Android app. Search words: Android, app, phone, full screen, update.
- Exact: yes

### A phone has five tabs, full screen and landscape for the lane, and a Back gesture that never leaves the page by accident

{{29-038}}

On a phone the lane is entirely full screen: it covers the view above the bottom bar, and no scroll or over-scroll ever brings the cards into view behind it. Where a phone refuses to lock landscape (an iPhone always does), the lane still works on a 390 px wide portrait screen, and the person is told once, not every time. Back from any full-screen phone view returns to the cards without piling up history; Back on the cards is the browser's own Back.

- Name and search words: the phone tabs. Search words: phone tabs, lane tab, edit tab, staged, find.
- Phone and desk: tabs exist only in the two phone layouts; a desk shows every panel at once.
- Exact: yes

### The phone layout is chosen from the screen and the pointer, and can be pinned

{{33-068}}

A phone is recognised by a touch pointer that cannot hover as well as by width, so a phone browser that asks for the desktop site and reports about 980 px wide still gets the phone layout. A brief change of width (a window dragged between monitors) never switches the layout: a switch waits until the new width has held, the width that enters the phone layout is narrower than the one that leaves it, and going back to the desk restores the desk layout exactly as it was.

- Setting: Layout. Does: pins this device to the phone or the desk layout, or lets the screen decide. Default: Auto. Who: anyone, for their own device. Applies to: a computer. Search words: layout, phone layout, desktop layout, pin, tablet.
- Exact: yes

### On a phone a card's text gets nearly the whole width, and the selected card offers its actions

On a phone an unselected card shows no buttons and one line of details that never wraps; its words get nearly the whole width of the screen. The selected card shows its actions as buttons at least 44 px in size.

- Phone and desk: on a desk every card keeps its own buttons.

### On touch, cards are lifted by two taps or a long press, and the transcript opens from a button

- Two taps on one card within 450 ms lift it (with the rest of the selection if it is selected): a short vibration, the cards marked, and a toast "Moving cut N[ and M more]. Scroll, then tap where it goes: the top half of a card puts it before, the bottom half after. Tap it again to cancel." with Cancel. A gap lifts the same way ("Moving the gap").
- While lifted, tapping a card's top half puts them before it, its bottom half after it; a tap between cards puts them before the next card down (or after the last). Tapping a lifted card cancels ("Move cancelled."); Esc cancels. Toast "Moved the cut." / "Moved the gap." / "Moved N cuts." with Undo; they become selected.
- A long press on a card (500 ms without moving past 10 px) lifts it (or the selected block it belongs to) for dragging: the card follows the finger, the cards scroll by themselves while it is held near the top or the bottom edge, and letting go drops it there, as one undoable move. Moving more than 10 px before the press is long enough scrolls instead.
- The transcript of a card opens from the card's own button or from the bottom bar. The browser's own long-press menu never appears on cards, and nothing that means a right-click is reachable by a long press.
- On touch, two taps are never a double-click (no edit view, no transcript).

Every touch gesture has exactly one meaning in each phone view.

- Exact: yes

### Select mode lets a touch or narrow screen pick cards by tapping

{{33-024}}

- Ways in: the floating Select button, the View settings sheet's Select mode row, and its row in the drawer.
- Exact: yes

### On a phone, a staged card is lifted with a double tap and filed by tapping a chip

Every drag on the cards and the shelf has a touch way that works on iPhone and Android, where web drag and drop does not exist; filing a staged card into a category is this one.

{{33-009}}

- Exact: yes

### On touch, the lane is tapped, panned, pressed and pinched

- Tap an item (released within 10 px): select it, replacing the selection. Modifier keys on a touch press, if any, toggle or select a range as with the mouse.
- Tap bare lane: the head goes there.
- One finger dragged (past 10 px, before a long press, anywhere not on an armed edge's handle): pan the lane. On release it coasts.
- Long press an item (500 ms without moving past 10 px): the item (or the selected block it belongs to) is lifted, and the screen shows the lifted card. Dragging then moves it, with the same ghost, caret and drop rule as the mouse, and the lane scrolls by itself while the lifted card is held near either end of the view. Releasing commits the move even with no drag after the lift, if the place differs.
- Touching an edge handle (22 px either side of an edge) and lifting without moving arms that edge. Dragging the handle of an ARMED edge trims the cut, or resizes the gap, as with the mouse. Under a marker's flag a tap still arms the edge there, and a long press picks up the marker instead.
- Two fingers: pinch zoom. The zoom changes by the ratio of the fingers' current distance to their distance at the start; the timeline second that was under the fingers' starting midpoint stays under their current midpoint. The second finger abandons whatever the first had started (a pending long press, a move, an edge drag), with nothing committed. A third finger is ignored. The pinch ends when either of its two fingers lifts; the other finger is then ignored until it lifts too.
- Shift+drag box selection is mouse and pen only.

- Exact: yes

### The phone's Edit tab shows the cut running down the screen as rows, with the playhead travelling through them

On phone and landscape-phone layouts, under the Edit tab.

- One row per cut in timeline order; a gap is a thin row reading "gap N.N s". A point along a row is a point in time; the timeline runs down the screen.
- Each cut row: its number, short speaker name, its English (only at row heights of 48 px or more), its length (or "+/-N.NN s" while a trim is held), and the cut's waveform behind at the playing level (a flat line when there is none). Selected and picked-up rows are marked.
- The row under the playhead shows the cut's whole text, scrollable within the row, with the word being heard lit; a cut with no word timing says "no word timing" there.
- **The playhead** is a marker that travels across the row it is in; the list moves up under it so it stays 38% of the way down. A finger scrolling the list "browses": the playhead stays and the list stays where it was put until the playhead moves again (or play starts).
- **Row height**: four steps, 24, 48, 72, 96 px (48 by default), set with "Shorter rows" / "Taller rows" or a two-finger pinch (each 30% change in finger distance is one step). Remembered per device.
- **The dial** (a strip down the right edge) is the only thing that scrubs. Dragging it pauses playback and moves the playhead down or up the rows, heard as it goes; the further left of the dial the finger is, the finer (down to a quarter, over 160 px). Keyboard on the dial: Up/Down one second, Shift ten. The bar's buttons sit beside the rows, never over their text.
- **Tap** in the list: play / pause, after a 300 ms wait (so a second tap can be a pick-up).
- **Two taps** on the same row within 450 ms pick it up (short vibration; it becomes selected): "Picked up cut N / the gap. Tap where it goes: the top half of a row puts it before, the bottom half after. Tap it again to put it back." The next tap moves it ("Moved. Undo puts it back.") or, on itself or empty space, puts it back ("Put back."). Leaving the Edit tab puts it back too.
- The browser's long-press menu never appears on the list or the loupe.

- Name and search words: the phone edit view. Search words: edit tab, rows, dial, phone cut, scrub.
- Setting: Row height. Does: sets how tall each row of the phone's edit view is. Default: 48 px. Who: anyone, for their own device. Applies to: a computer. Search words: row height, taller rows, shorter rows, phone rows.
- Exact: yes

### On the phone's rows, a held press trims an edge, auditions it, and a loupe shows the waveform close up

- **Press and hold past 280 ms then drag** on a cut row (short vibration): trims or extends the edge of that cut nearest the playhead, by the same rules as the lane, arms that edge, heard as it moves. A drag the full width of the screen moves the edge 5 s whatever the cut's length; the cut keeps at least 1/24 s; values move in 1 ms steps. On release one trim is committed and auditioned: the playhead goes 1.5 s before the new edge and plays for 3 s, then pauses. Moving 10 px before the hold cancels it.
- **Loupe**: a 4 s waveform strip (2 s either side of the playhead, or of the edge being trimmed) at the foot of the list, with the cut's own in/out lines labelled, a centre line (one colour for the playhead, another for a held edge), and under it the word at that point, "· 4 s across" and "· trim"/"· fine". "the head is in a gap" when it is. It appears by itself while a trim is held; the Loupe button pins it on ("Loupe on: the waveform around the head, 4 s across" / "Loupe off. It still appears while you trim."), remembered per device. A press-and-hold that starts on the loupe trims the nearer edge of the cut the playhead is in, 4 times finer; in a gap: "The head is standing in a gap. A hold trims the cut the head is in; take it into one with the dial."
- **Bar buttons**: "2x" (twice speed with pitch following; again for normal speed), "Split" (splits the cut at the playhead), "Delete" (the first tap turns it into "Tap again" for 3 s; the second deletes the cut under the playhead: "Deleted the cut under the head (it is on the shelf). Undo puts it back."), "Loupe", "Shorter rows", "Taller rows". Split and Delete are disabled with "Put the head inside a cut first" when the playhead is in no cut; tapping them then toasts that reason. Delete sits farthest from the resting thumb.

- Exact: yes

### On a phone, the scrub pad drives the head at a speed set by the finger's distance

The scrub pad is a 96 x 96 px square. A touch in it pauses playback and sets the place where the finger landed as the origin; from then on the head moves at a speed set by how far the finger is from that origin: nothing within 8 px, 1 second per second at about 17 px, 10 seconds per second at 39 px, and at most 180 seconds per second from 76 px on. Sliding the finger higher on the pad makes the same distance finer. Moving back past the origin runs the head the other way. Letting go parks the head where it is, with no coasting.

- Ways in: the scrub pad on the phone, and the "◐" rate scrub pad on the lane bar, which works the same way.

### On a phone, holding Play plays at twice speed

A tap on the play bar's Play button plays or pauses, once. Holding it plays at twice speed; letting go returns to the speed before, and stops again if playback was stopped when the finger went down.

### On a phone or touch screen the transcript panel adapts

{{30-045}}

- Exact: yes

### On touch, the transcript has its own word selection and its own insert sheet

On a touch screen nothing outside a text box can be selected the browser's way, so no phone's own word overlay ever covers the transcript. The transcript has its own word selection instead: a press on a word starts it, two handles drag its ends, a double tap selects a line, and its own copy button copies the words. The actions for a transcript selection (insert at the head, insert after the selected card, to the shelf) sit in a sheet at the bottom of the screen that shows only with the transcript and says where the cut landed. The bottom bar always names the view on screen.

### Phone screens fit, and every press shows that it took

- On a screen 390 to 412 px wide, at every zoom, no card, details line or panel is wider than the screen: text wraps and long names end in an ellipsis. Every control bar, its close included, fits and can be tapped on a 390 px portrait phone with nothing clipped and no sideways scrolling.
- An open drawer always shows a way to close it, Android's Back closes it, nothing opens underneath it, and a tap that cannot act says why.
- Every press visibly registers at once. A refusal says what happened and the way out, looks like a refusal, and shows near the finger; the same refusal repeated shows once, not stacked.
- An armed delete shows its countdown on the button under the finger, and nothing redrawn on the page clears an arming or a confirmation within six seconds.
- A vibration is a bonus: where the phone blocks it (before a first real tap), nothing shows as an error and the action does exactly the same.
- No shortcut anywhere in the editor needs Ctrl with a digit, which browsers keep for their own tabs.

### Any game controller works, and letting go of it or of the window ends every hold without doing anything

{{28-025}}

A browser shows a controller to the page only once a button has been pressed: until then, wherever the controller map is shown, the page says to press any button on the controller. A missing vibration motor causes no error. A controller that goes to sleep or disconnects never moves the keyboard or the text cursor out of a box being typed in.

- Exact: yes

### The controller rumbles on every refusal, and its triggers, D-pad and sticks have fixed thresholds

{{28-026}}

Every rumble comes with the same refusal written on screen, so the buzz in the hand always matches the message.

- Exact: yes

### While the editor is typing, the controller keeps out of the way

When a text box has the caret: if it is one of the editor's own two boxes (the transcript's find box, or the search sheet's query box) the box layer applies (see "While the find box or the search box has the caret, a few controller buttons still work"). For any other typing target (an input of any kind except button, checkbox, radio, range, submit, reset, colour, file or image; a text area; a select list; anything editable, for example a note, the edit chat, a name field) the controller is ignored completely, every hold ends, and buttons already down count as already down, so that leaving the box does not fire whatever was under the thumb. On entering the box layer, every hold ends, the sticks must pass their centre again, and a button already down when the box took the caret is not a press.

- Exact: yes

### Which map the controller's buttons follow depends on where the editor is

Decided afresh every moment, in this order:

1. One of the editor's own two boxes has the caret: the box layer (see "While the find box or the search box has the caret, a few controller buttons still work").
2. The search sheet is open: the search results map (the sheet is modal) (see "With the search sheet open, the controller walks the hits, plays them and opens them").
3. The keyboard is inside the transcript panel and it has a transcript open: the transcript map (see "In the transcript, the controller's buttons play, select and insert sentences"). If instead it is showing its list of transcripts: that list's map (see "On the list of transcripts, the controller walks the list and opens one"). If neither: the lane map.
4. Anything else: the lane map (the lane's buttons below).

A button held down keeps acting on the place where it went down until it is released, whatever happens to the keyboard meanwhile.

- Exact: yes

### View, Menu and the bumpers act on release, so a tap can be told from a hold

{{28-029}}

- Exact: yes

### On the lane, A plays and B backs out

{{28-030}}

- Exact: yes

### On the lane, X splits or makes a gap, LT + X deletes, and Y selects or opens a cut's transcript

- X (bare): tap (released before 600 ms) splits the cut under the head at the head, on release. Held 600 ms: inserts a 1 second gap at the head (once, at the 600 ms mark); its length can then be dragged with a bumper and the right stick.
- LT + X: delete, as Delete on the keyboard. With a valid in / out range inside one cut, that range is taken out at once. Otherwise the first LT + X arms the target items for 3 s with a visible count, and a second LT + X within 3 s deletes them; a button held down never confirms. Rumbles with nothing to delete.
- Y (bare): select the item under the head (replacing the selection; it becomes the range anchor). Rumbles with no item under the head. A second Y within 450 ms on the same item, when it is a cut, opens that cut in its transcript (opening its interview first) and puts the keys on the transcript (rumbles if it has no transcript). The first Y does not wait to see whether a second is coming. A gap never opens.
- LT + Y: select from the anchor to the item under the head (a range), in either direction. Rumbles with no item under the head. Never half of a double press. The D-pad's own steps keep the anchor; B clears it with the selection.

- Exact: yes

### On the lane, the bumpers trim to the head, jump to a cut's ends, drag an edge or change a fade

- LB tap: trim the in edge of the cut under the head to the head (as Q). RB tap: trim the out edge to the head (as W). Both rumble if the head is not in a cut.
- LT + LB tap: the head to the target cut's start. LT + RB tap: the head to the target cut's end (its last frame). Both rumble with no target cut.
- LB / RB held + right stick: drag that edge (see "A bumper held with the right stick drags that edge, shown as a ghost until the bumper is let go"). The bumper's release commits.
- LB / RB held + D-pad: the audio fade on that edge (see "Holding a bumper and pressing the D-pad changes that edge's audio fade").

- Exact: yes

### On the lane, the D-pad steps the head, jumps edit points, and with LT moves items

{{28-033}}

After a move made from the controller the head stays on the moved cut, so pressing the same move again keeps moving the same cut.

- Exact: yes

### On the lane, L3 lands the head in the middle of the view, R3 marks in and out, and LT + L3 adds or removes a marker

{{28-034}}

- Exact: yes

### On the lane, View and Menu reach the transcript, search, the help, redo and the video window

- View tap: put the keys on the transcript (on the desk the transcript, or its list when none is open; on the phone the next tab). View held 600 ms: open the search sheet. LT + View: redo.
- Menu tap: put the caret into a find box (see "Menu puts the caret into a find box, with a hint saying what the controller now does"). Menu held 600 ms: open the controller map (the help sheet). LT + Menu: the video window on / off.
- RT: the shuttle (see "RT is a shuttle: the harder the pull, the faster the playback").

One View tap moves the keys from the lane to the transcript, and one moves them back.

- Exact: yes

### Holding a bumper and pressing the D-pad changes that edge's audio fade

{{28-036}}

- Exact: yes

### The right stick jogs the head, heard as it moves

{{28-037}}

- Exact: yes

### A bumper held with the right stick drags that edge, shown as a ghost until the bumper is let go

{{28-038}}

- Exact: yes

### LT with the right stick carries the selected items to a new place in the cut list

{{28-039}}

The drop is one move, undone in one step, and the head stays on the moved block.

- Exact: yes

### The left stick pans and zooms the lane, never the head

Sideways: pan the lane, 14 px per 60 Hz frame at full push (a quarter with LT). Up / down: zoom about the centre of the view; per 60 Hz frame at full push the zoom changes by a factor of e^0.045 (about 4.6 %), up zooms in; a quarter with LT. The controller's zoom runs from the whole cut in to 400 px per second, the same range as every other way of zooming the lane. The pan stays between the start and the end of the timeline. With L3 held, the landing line follows the pan.

- Exact: yes

### RT is a shuttle: the harder the pull, the faster the playback

Pulled past 0.1: playback starts (if stopped) at a rate from 1x at a light pull to 4x at the stop, in steps of 0.05. With LT held: 0.5x at a light pull up to 1x at the stop. Let go: rate back to 1x, and paused where it got to if playback was stopped when RT was first pulled. A shuttle belongs to the place it started in: begun in the transcript it drives the transcript's own preview playback instead (see "In the transcript, View, Menu, the sticks and RT"). In the search results and in the list of transcripts, RT shuttles the lane's playback.

- Exact: yes

### Menu puts the caret into a find box, with a hint saying what the controller now does

{{28-042}}

- Exact: yes

### In the transcript, the controller's buttons play, select and insert sentences

{{28-043}}

- Exact: yes

### In the transcript, View, Menu, the sticks and RT

{{28-044}}

- Exact: yes

### What the transcript says when a controller press acts or cannot

The transcript panel's own messages for the controller's actions. Which button sends which action is the transcript map above: the paragraph step is LT + D-pad Up / Down, the edge is the bumper taps, the head on a sentence is L3, the whole paragraph is R3, playing the paragraph is LT + A, scrolling is the left stick, leaving the find box is B, View or Menu in the box, the list of transcripts is LT + R3 and the list's own map, and showing a cut is Y twice on the lane.

Each action that cannot act fails and the controller rumbles. Button names are those the panel's own messages use.
- Right stick moves the transcript playhead through the words, as the lane's jog moves the lane head: a word costs the time to the next word's start, at least 0.06 s and at most 0.5 s of stick (a silence is stepped over; a run of words sharing one start is not crossed in one frame). The first push puts the playhead on the sentence cursor's first word, else the first timed word in view, and moves nothing ("the playhead is on this word - the right stick moves it, LT + the right stick selects, A plays from it"); a playhead scrolled out of view is placed again the same way. It pauses the transcript; the view keeps the word at least min(48 px, a quarter of the view) from the edges; the first or last word stops dead (rumble); a plain move drops any selection. No timed words: "this transcript has no word timings on these lines, so there is no playhead to move" (or "this transcript has no timings, so there is no playhead to move").
- LT + right stick selects what the playhead crosses, from where it stood when selecting began; letting go keeps the selection; holding LT again continues from its moving end; English selected this way stands for its original words. Drawn like the cursor's selection and played whole by Space/A.
- B (cancel), in order: a multi-sentence cursor back to one sentence ("back to one sentence"); a controller selection dropped, head stays ("the selection is off - the playhead stays where it is, B again takes it off"); a cursor, selection or picks cleared ("the selection is off"); the transcript playhead removed ("the transcript head is off").
- X: insert at the lane head; LT + X: after the selected card.
- D-pad: previous/next sentence, starting on the sentence the head is in. Paragraph step: next paragraph's first sentence; back goes to the top of the current paragraph first, then the previous paragraph.
- Edge: move the start or the end of the cursor selection by a sentence ("LB / RB grow it").
- Y (home): right after stepping through find hits, selects the current hit's sentence ("the match’s sentence is selected - X inserts it at the head, LB / RB grow it"); a hit on the other language's line selects its paragraph's first sentence ("the match is on the other language’s line: its paragraph’s first sentence is selected (LT + L3 switches the cursor’s language)"). Otherwise the paragraph under the transcript playhead (under the lane head when the transcript has no playhead) ("the block under the playhead - move with the D-pad, then LT + Y selects the run"). With no hit: "there is no match to take yet - type in the find box, then ◀ ▶".
- LT + Y (range): the first press sets the current sentence as the anchor ("this sentence is the anchor - move along, then LT + Y selects up to the cursor"); the next selects from the anchor to the cursor ("N sentences selected - X inserts them, B collapses").
- Head on sentence: puts the transcript playhead on the cursor sentence's first word ("the transcript head is on that sentence - A plays on from it"; "that line has no word timing, so the head cannot be placed on it").
- LT + L3: switches the cursor's language, as X on the keyboard.
- Whole paragraph: the cursor covers its paragraph. Play paragraph: selects the whole paragraph and plays it from 0.4 s before to 1 s after ("that paragraph has no word timings to play").
- ◀ ▶: previous/next find hit ("there is nothing to find yet - Menu puts the caret in the find box").
- A down/up: as Space down/up (tap plays or pauses, hold skims at 2x); a cancelled release ends the hold.
- RT (shuttle): plays at the given rate while held (starting playback if stopped); releasing returns to 1x and pauses if it was stopped.
- Scroll: scrolls the paragraphs.
- Menu: focuses the find box with its text selected; if the box is empty and the search sheet had a word, that word is typed into it first. Leave find: back to the paragraphs.
- List of transcripts: browse (switch to the list and focus the open transcript's row or the first), list step up/down ("the list is empty: nothing matches its filters"), list open, list back (to the open transcript).
- Show cut: shows a cut in its transcript and focuses the paragraphs.

- Exact: yes

### On the list of transcripts, the controller walks the list and opens one

{{28-046}}

- Exact: yes

### With the search sheet open, the controller walks the hits, plays them and opens them

{{28-047}}

{{31-018}}

- Exact: yes

### While the find box or the search box has the caret, a few controller buttons still work

{{28-048}}

- Exact: yes

### What the editor's views do with the controller

Once a controller is connected, the shortcuts sheet lists its map from then on. A hint from the controller shows as a toast.

| Controller | What it does |
|---|---|
| LT + Menu | Shows or hides the video window, or says there is no video window to show. |
| Menu held | Opens or closes the shortcuts sheet. |
| Go to head, follow, note, record/jump place, delete (armed then confirmed) | As the keyboard. |
| View | Moves to the lane or the transcript panel (the transcript list's open row, else its first row, else its body); on a phone, to the next of Cards, Lane, Staged. |
| L3 held | Shows a landing line where the playhead's clip would drop. |
| LT + right stick | A long clip move, drawn on the lane ("Let go of LT to drop · B cancels"). |
| LB/RB + right stick | An edge drag drawn like a mouse drag, the sound scrubbed to the new edge. |

A mouse drag in progress is never taken over by the controller.

- Exact: yes

### The help sheet lists every controller button for each place

{{28-050}}

- Name and search words: the controller map. Search words: controller, gamepad, buttons, pad map, help.
- Ways in: the controller's Menu held, the "?" key and the Shortcuts buttons (the shortcuts sheet, in part 1).
- Exact: yes

### The controller never sends anything to the editing program

No button or combination on the controller sends a cut, or anything else, to the editing program: sending is a deliberate act from the keyboard, the mouse or a finger. Editing from the sofa with a controller is safe: a refusal always buzzes and says why, and a box being typed in ignores the pad.

#### Lessons

- Met: CE2-135, CE2-136, CE2-137, CE2-138, CE2-139, CE2-140, CE2-141, CE2-142, CE2-143, CE2-144, CE2-145, CE2-146, CE2-147, CE2-148, CE2-161, CE3-084, CE3-085, CE1-103, CE1-104, CE1-107, CE1-108, CE1-109, CE1-110, CE1-111, CE1-112, CE1-113, CE1-114, CE1-115, CE1-116, CE1-117, CE2-149, CE2-150, CE2-151, CE2-152, CE2-162, CE2-163, CE2-164, CE2-165, CE3-086, CE3-088, CE1-102, CE1-105, CE1-118, CE2-153, CE2-154, CE2-155, CE2-156, CE2-157, CE2-158, CE2-159, CE2-160, CE2-166, CE3-087, CE3-089, CE3-090, CE3-091.
- Met for another part: CE2-056 (in "On a phone, the scrub pad drives the head at a speed set by the finger's distance").

## Speed and smoothness

Every promise here is measured on the studio's own kinds of computer and phone, by the editor's own frame timings taken on the device itself at its screen's real refresh rate (never through a remote-desktop view, which shows a different speed), with real cut lists, real waveforms and words still arriving.

### Every edit appears at once, on a long cut as on a short one

- On a cut of 433 cuts, every edit, a split included, is drawn within about 100 ms of the key, click or tap, and saved behind it. Nothing greys out or waits while it saves. If the server then refuses it, the edit is taken back on screen with the reason, and a selection survives an undo.
- The time an edit takes grows with the edit, not with the cut: a trim at the start of a 1,500-card, 500-minute cut appears as fast as one at its end.
- On a mid-range phone, at 500 cards, one change updates the edit view within one frame (16 ms).
- Edit keys pressed in quick succession all take effect, in the order pressed; none is dropped silently.
- Whenever an edit, an undo or an update from elsewhere finishes or is refused, the cards answer the mouse and touch again at once, as they answer keys.

### The lane stays smooth at 100 frames a second

While the lane sits idle, plays, starts and stops, scrolls with the wheel, seeks on a click (also while playing), is dragged along its ruler and zooms with Ctrl+wheel, no frame takes longer than 10 ms, that is 100 frames a second, even at the worst moment (the 99th percentile frame). This holds:

- with 1,000 cuts on a 4K screen, words still arriving;
- at every zoom an editor really uses, with real waveforms, drawing costing the same zoomed in as zoomed out;
- on a laptop drawing on its built-in graphics, and with Resolve open on the same computer sharing the graphics card. Smoothness is reached by the editor doing less, never by asking the person to change a graphics setting.

The lane and the header stay exactly where they are docked in every hover and panel state, and nothing above the cards shifts when the cards scroll.

Each frame of the lane is drawn within a few milliseconds at any zoom, on a 4K screen too, and also in the first seconds after a cut list opens, with no burst of lag while things arrive. Nothing the page asks the server for in the background is asked again more often than every few seconds.

### Text and the first Play never stutter

On a desk computer a card showing Chinese characters (or any other script) not seen before appears without a stutter, and the first Play after a cut list opens does not stutter either. On a phone nothing is downloaded ahead of need, to save data: characters are fetched as they first appear. The editor's typefaces come with it, so text looks the same with no network. While playing, long cut lists (1,500 cards and more) stay as smooth as short ones, and the selected card and the playing card are always ready on screen.

### Reading aids and line-ups never hold the editor back

The reading aids and the line-ups between the original and the English arrive in the background and are painted as they come, on the paragraphs and cards on screen or about to come on screen. Waiting for them never blocks typing, playing or editing. When the aids cannot be had, the surfaces quietly show less. A card's aids follow the one English line actually shown on it.

Anything finished in the background (a waveform, an aid, a job's result) appears on the page within a few seconds, with nothing else happening on the page. A view that needs audio, a waveform or words that are not ready yet keeps asking until they exist, then shows them and starts playback, with no reload.

### An edit is refused only for a real reason, and never in silence

An edit is refused as out of date only when the cut's cards, their order or their timing really changed since the page saw them; an edit made on a view that is a little behind in anything else goes through, and every page showing the cut list settles on the saved cut. Every refused edit shows, on the device it came from, a plain sentence saying why, with any technical detail behind a disclosure, and nothing changes.

### Opening a cut list takes about a second and never slows anything else

Opening a cut list, or making one from the board, takes about one second at most on a typical episode. Opening or editing the studio's largest episode never makes other pages of the dashboard, or the reports from editors' computers, wait.

#### Lessons

- Met: CE2-167, CE2-168, CE2-169, CE2-170, CE1-068, CE2-171, CE1-069, CE1-070, CE1-071, CE1-072, CE1-073, CE1-074, CE1-075, CE1-076, CE2-172, CE2-173, DSH-129.
- Met for another part: CE1-089 (in "The lane stays smooth at 100 frames a second").

## The page: panels, header, warnings and redrawing

### The editor starts on the cards view and switches to the phone layout on a narrow window or a touch screen

The views are the cards, the lane, edit, the transcript and the shelf; the editor starts on the cards. The zoom starts at 40 px per second and runs from the whole cut in to 400 px per second, for every way of zooming; a zoom holds the chosen time still on screen and never scrolls before 0. The phone layout is on when the window is 700 px wide or less or the pointer is coarse (a touch screen), and follows changes as they happen. "Retry now" reconnects to the server at once, even after a final error.

- Exact: yes

### While the editor is starting, a placeholder of the editor is already on screen

{{29-001}}

- Exact: yes

### When the editor cannot start, the person is told why, or sent to sign in and brought back

{{29-002}}

The editor loads and works in current Chrome and Safari on desk and phone; a page that fails to load in either is not ready to reach the studio.

- Exact: yes

### The header holds a Tools group for the editor's tools, folding into a drop-down on narrow screens

{{29-008}}

- Exact: yes

### The header shows the brand, where you are, search, undo, redo and Send to Resolve

- **Brand**: the CC mark and "TIMELINE CARDS"; clicking it switches back to the Cards view (it does not leave the page).
- **Breadcrumb**: the episode name, "/", then the cut list's title. The title is the list's project name, else its title, else the file's name without its ending, else "No cut list open". A leading episode name is dropped, and anything in the title that marks a list as made by Assistant is dropped. The full title is the hover text.
- **Search box** (desk only): placeholder "Search the cards", key hint "Ctrl K". Typing filters live (see Find). Esc in a non-empty box clears it.
- **Undo / Redo** icon buttons (desk only), disabled when there is nothing to undo or redo.
- **Send to Resolve** (desk only): a red primary "Send to Resolve" when a cut list is open and sending is available; "Sending" with a spinner while it runs; a second press meanwhile is ignored. When no computer can drive Resolve for this page (list open), a quiet label "Resolve: not connected" whose hover says why. With no list open nothing is drawn. Success toast "Sent to Resolve."; failure (error level) "Send to Resolve failed: <message>"; closing the Resolve panel without sending reports nothing. The red button opens the send panel; if that panel is not available it fails with the reason, or "the Resolve panel is not available yet".
- **Phone header buttons**: Undo (icon) and More (opens the header More sheet).
- **Header compaction** on the desk: below 1600 px wide the "TIMELINE CARDS" text is hidden; below 1500 px the search box drops its "Ctrl K" hint; below 1200 px Send to Resolve becomes an icon with a tip, the search box narrows, and the tools fold into the Tools drop-down. On a phone the brand text and the episode part of the breadcrumb are hidden and the tool buttons drop to a second header row.

At desk widths the header stays on one line: long names end in an ellipsis, every control stays visible, and the content fills the window below it. The top bar's buttons are icons with a tooltip each; on a phone, menu rows keep their words.

- When the help for the editing program is off: no Send to Resolve button, label or tip is drawn; the header offers the exports in its place (see Resolve is optional).
- Exact: yes

### Toasts: one at a time, with set lifetimes, Dismiss, and an Undo after every edit

{{29-017}}

- Exact: yes

### A More menu offers each card's less common actions, and the header's

Opened from a card's "More actions" and the phone header's More. A sheet from the bottom on phones (grab handle, darkened background), a centred dialog on the desk; the first enabled item has focus. Closed by Close (Esc hint), Esc, the background, a click outside, running any item, or the back gesture.

- On a gap: "Move this gap" (lifts it), "Remove the gap".
- On a cut: "Edit edges", "Add a note"/"Edit the note", "Zoom to cut", "Move this cut" (lifts it), "Add a 1 s gap before" or "Remove the gap before" (toasts "A 1 s gap went in. Drag its edge to size it." / "Gap removed. Undo puts it back."), "Remove from cut".
- Header extras: "Redo", "Send to Resolve" (or a quiet row with the reason: "Resolve: not connected" / "Open a cut list first"), "Shortcuts" (hidden on touch screens).
- On touch, tapping a disabled control that has a reason toasts the reason.

- When the help for the editing program is off: the "Send to Resolve" row is not there; the exports are offered instead.
- Exact: yes

### The lane bar sets the lane's height, top or bottom, panels hidden, language, literal line and word size

{{29-055}}

- Setting: Lane position. Does: docks the lane at the top or the bottom of the editor on this device. Default: top. Who: anyone, for their own device. Applies to: a computer. Search words: lane position, top, bottom, dock, timeline place.
- Setting: Lane language. Does: shows English first, or the words as spoken first, on every surface of the editor. Default: English. Who: anyone, for their own device. Applies to: a computer. Search words: language, English, original, F9, words.
- Exact: yes

### On a desk, the panels sit in tab groups the person can rearrange, resize and reset

{{29-059}}

Opening, closing or moving one panel never changes another panel's width, to the pixel: a hidden panel changes nothing, and only the card column grows or shrinks. On a desk a panel opened beside the cards sits beside them, and the cards reflow; it never covers them. Every panel tab can be closed from its header, and a toggle in the top bar reopens it on its last tab. The bars along the bottom take as little height as they can. Alt with a digit switches panel tabs: Alt+1 the cards, Alt+2 the transcript, Alt+3 the shelf (staged), and on through the panels in the order their tabs stand; every tab can also be clicked or tapped. No panel key uses Ctrl with a digit.

- Name and search words: the panel layout. Search words: panels, tabs, dock, layout, reset panels.
- Exact: yes

### The editor lays itself out for desk, tablet, portrait phone and landscape phone

{{29-061}}

At 1440 x 900 and at 412 x 915, every combination of open panels keeps the card column above its minimum width, and the page never scrolls sideways.

- Exact: yes

### On a desktop, the toolbar offers "Bring windows back" and a "Windows" menu

{{32-044}}

- Exact: yes

### The Windows menu moves a panel, or the whole editor, into a window of its own

Rows: Lane ("The timeline with the words in its clips"), Transcript ("The transcript beside the cut"), Ask Assistant ("Ask Assistant for changes"), Overview ("Sections and markers"), each "Move out" or "Elsewhere" (gold; "In another window: bring it back here"); Cards ("A second view of the cards", "New window"); a separator; "Whole editor" ("This cut list in another window", "New window"); "Bring everything back" (only when other windows are open or a panel is out). Up/Down/Home/End move between rows; Escape closes the menu and returns focus to the Windows button; a press outside closes it; it sits under the Windows button (else centred near the top). "Whole editor" opens this cut list again in a new window.

- When the assistant is off: the Ask row is not in the menu.
- Name and search words: the Windows menu. Search words: windows, second screen, pop out, move out, bring back.
- Exact: yes

### A panel moved into its own window shows only that panel, and comes home when its window goes

{{32-046}}

Selection, the playhead and every edit reach every window of the same cut list within a frame.

- Exact: yes

### How the editor's menus open, move and close

{{33-027}}

Hovering never changes the size or the place of any other element, and a list that refreshes while open updates where it stands. Menu text is easy to read against its background and a highlighted row is drawn crisply. Each section of a settings sheet can be folded; all start folded, with one control to unfold or fold them all.

- Exact: yes

### Gap-notes messages appear as toasts near the bottom

{{33-044}}

- Exact: yes

### The View settings sheet holds this device's own view settings

{{33-058}}

- Name and search words: the View settings sheet. Search words: view settings, density, text size, layout, this device.
- Exact: yes

### Card density has five levels

{{33-059}}

- Setting: Card density. Does: sets how much of each card the cards panel shows. Default: Full. Who: anyone, for their own device. Applies to: a computer. Search words: density, compact, index, strip, card size.
- Exact: yes

### Ctrl+wheel or a two-finger pinch over the cards changes density

{{33-060}}

- Exact: yes

### The View sheet holds follow, recorded places, select mode and the keyboard shortcuts

{{33-061}}

- Exact: yes

### Card text comes in four sizes

{{33-063}}

- Setting: Card text size. Does: sets the size of the words on every card. Default: Medium. Who: anyone, for their own device. Applies to: a computer. Search words: text size, font size, larger, smaller, cards.
- Exact: yes

### The View sheet explains how to size and place the lane

{{33-064}}

- Exact: yes

### The sections panel and the inspector can be resized on a wide desk

{{33-067}}

- Exact: yes

### In a desktop app window the editor is one whole window whose header is its title bar

Where the editor runs in a window of its own on a desktop (opened from the app on the editor's computer), it shows as one window, like Resolve: the editor's header doubles as the window's title bar and drags the window, and the window's own minimise, maximise and close buttons are drawn over the header in the editor's colours.

### Standing conditions go to one problems window and never pop up over the cards

A condition that lasts (the server cannot be reached, a part cannot run, something is missing for the English) is listed in a problems window the person opens when they choose, never shown as a banner across the page. Only a failed edit or a failed send shows on the page itself, as a toast. Nothing above the cards moves to make room for a message, and no message lets the cards show through it.

### The audio preview bar appears only while sound is wanted

The small player for previewing a passage's sound slides in only while audio is wanted, sits under the insert bar below the header, and matches the page's look. Deselecting the text hides the insert bar.

### Background answers redraw only what they concern, and a page never shows another cut list's cards

An answer arriving in the background updates only the cards it concerns, and a side panel redraws the lane only when what the lane shows has changed, so the page never goes choppy and the lane never flashes. An editor page shows only its own cut list's cards, never another's, not even for a moment while loading.

#### Lessons

- Met: CE3-100, CE1-119, CE1-120, CE1-122, CE1-123, CE1-124, CE3-092, CE3-093, CE3-094, CE3-095, CE1-121, CE3-096, CE3-097, CE3-098.
- Met for another part: CE2-028 (in "On a desk, the panels sit in tab groups the person can rearrange, resize and reset" and "The header shows the brand, where you are, search, undo, redo and Send to Resolve"), CE2-030 (in "How the editor's menus open, move and close"), CE3-032 (in "On a desk, the panels sit in tab groups the person can rearrange, resize and reset").

## Opening episodes and keeping the editor running

### The Timeline Cards page lists every episode in its folders, most recently opened first

The Timeline Cards page is the front door: it lists every episode of the studio, to find and open. Every episode appears on it by itself within about 30 seconds of being made, at whatever depth of folders the studio keeps its episodes; nothing needs registering.

At the top: "N episodes", "Carry on with <episode>" (see the next behaviour but one), and the line "Open goes into the cut list you last left this episode on, or its newest. Another cut list is one tap away inside the editor." Under it, "your recent": up to 5 episodes this person opened themselves, newest first, each with its name, its path or show, and when it was opened.

- **Folders**: episodes sit in their year and show folders, each folder with a count of episodes and their total size. Levels every episode shares are left out (at least one is kept). The top level, folders that were busy lately and folders holding an episode this person opened are unfolded at first. "unfold all" and "fold all" act on every folder.
- **Each episode**: its name; "in <path>"; when it was opened: "you opened it <ago>" (marked as the person's own), "<name> opened it <ago>", "somebody opened it <ago>" or "never opened"; who is in it now; its size ("sizing" while it is being counted, with "+" or "partial" when not all of it could be counted); "changed <when>", written like "3 Sep 2026"; and "Open". Ago reads "just now" (under 90 seconds), "<N> min ago", "<N> h ago", "<N> d ago" (under 60 days), then "<N> mo ago". Sizes are in B and KB with no decimals, and in MB, GB and TB with one, counted by 1024. A folder's size is the sum of its episodes', with "+" when any of them is unknown. A person whose display name is "you", "somebody", "nobody" or "someone" is shown by their sign-in name instead. If the record of who opened what cannot be read, the list still shows, without it.
- **Search**: a box ("search episodes, shows, years", with "clear"). Every word typed must appear, ignoring case, in the episode's name, show, path or year. Matching letters of the name are highlighted; folders holding a match open and the others close and hide, and clearing the search gives the folders back as the person had them. While filtered, folder counts read "N of M" and the total "N episode(s)" or "N of M episodes"; the recent tiles stay, dimmed. When nothing is left: "Nothing matches." with "Show everything". "/" (outside a text box) jumps to the search, Escape in it clears it, and Enter opens the episode when exactly one is left.
- **Sort**: last opened (the default: by when this person opened it, then by when anyone did), date last changed, largest, or A to Z. Episodes within each folder, and the folders themselves (by their newest or largest content), are re-ordered; ties and A to Z use natural order, ignoring case.
- **View**: folders (the default), or a flat list of every episode, without the folding controls.
- **Year**: all, or one year's episodes, the year taken from a year folder above the episode, else from its last change. The recent tiles follow the year too. A remembered year that no longer exists falls back to all. A reset clears the year and the search.
- With no episodes: it says there are no episodes yet, and where it looked.

Sort, view, year and each folder's open or closed state are remembered on the device; the search text only for that tab. The page works with scripts switched off too: folders fold, buttons work, and the order is A to Z.

- Who: anyone signed in.
- Ways in: the dashboard's menu, the installed phone app, the editor window's "Episodes (home)", and "All episodes" inside the editor.
- Name and search words: the Timeline Cards page. Search words: episodes, episode list, open episode, recent, Timeline Cards.

### Episode sizes are counted by themselves and kept fresh

Each episode's size (its bytes, its number of files and its newest change) is counted in the background, the episode counted longest ago first, and counted again after about 12 hours. An episode of more than 400,000 files and folders, or with a folder inside that cannot be read, shows a partial size. If the episode itself cannot be read, the last good size stays.

### The episode list offers to carry on with the last episode opened

"Carry on with <episode>" names the last episode this person opened, the top of their recent episodes, on whatever device they opened it, and goes into it. It is kept across restarts of the server, and offered only while that episode still exists.


### Opening an episode goes into the editor at the cut list last left there

Pressing Open on an episode records it as opened by this person (each person's last opening of each episode is kept, and who opened each one last) and takes them into the editor on that episode: at the cut list this device last left the episode on, if it still exists; else the newest cut list that reads (by last change, hidden files ignored); else the editor's own start sheet. Loading or reloading the editor reopens what was last open in that episode, never whatever timeline happens to be open in Resolve. An episode that is not one of the studio's is refused, back on the list, with a sentence saying so; when Timeline Cards is not running, the person is told it is not running.

While an episode is getting ready it shows "loading" on the list, and the list looks again about every 3 seconds (not while the tab is hidden; after a failure it waits longer, up to 15 seconds). When the episode the person was waiting for is ready, the browser goes straight into it, and Back does not return to the waiting list. Opening has a time limit: an episode that fails or takes too long shows a plain reason and can be tried again, and is never left unable to open; it is not tried again by itself sooner than about 20 seconds after the last try. One clip that cannot be read never stops the other transcripts loading.

Any number of people can each be in their own episode at the same time: opening one never waits on, or is refused because of, what anyone else has open, and nobody locks anything for anyone else. After switching to another episode, nothing of the previous one shows anywhere (its clips, transcripts, lists, colours and media), the lists of documents are read again at once, and a list that failed to load says so instead of saying there is none. Closing an episode frees everything it used, so opening and closing episodes for days on end never wears the server down.

- Who: anyone signed in.
- On its own: which cut list opens, from the one this device last left the episode on, else the newest.
- By hand: the Cut lists sheet in the editor opens any other cut list of the episode at once.

### Each episode has an address of its own that can be bookmarked

An episode's address reads as its name, in plain letters and digits (at most 32 characters), followed by a short code; a name with no Latin letters gets the code alone. The same episode has the same address on every computer and after every restart, so it can be bookmarked and shared, and an accented name spelled differently by a Mac and by Windows is still one episode with one address.

### The editor is reached through the dashboard, behind its sign-in, and knows who is signed in

The editor is reached at an address under the dashboard, behind the dashboard's sign-in. The signed-in person's name is shown in the projects sheet's footer ("Signed in as <user>"), and "All episodes" goes back to the dashboard's episode list. Every part of the editor, including the video pop-out window and working offline, works the same under that address.

- Who: anyone signed in.
- Exact: yes

### The editor is there whenever the dashboard is, and says so plainly when it cannot be

Whenever the dashboard is up, the editor is up: nobody ever starts or restarts it, and nobody ever needs a terminal for it. If it stops, it comes back by itself within seconds, and something it needs that is installed later is picked up within about 30 seconds, with no restart of the server.

Opening the editor while it is starting shows a page headed "Timeline Cards is starting", which reloads itself every 4 seconds; while it cannot run, "Timeline Cards is not running". Both give the reason, the line "Your cut lists are untouched.", and a link "Back to the Timeline Cards page". The reasons, in plain words: Timeline Cards is not installed on this server, or is incomplete; the place the episodes are kept is not set or cannot be reached; the server lacks something the editor needs; the editor has nowhere to keep its working files. Anything else that keeps the editor from answering reads "the editor did not answer".

- When Timeline Cards is off: nobody but an admin meets these pages; for everyone else Timeline Cards is not there at all.

### Stopping or restarting the server never loses an edit

When the server is stopped or restarted, every open cut list is saved to its file first, within the time the stop allows, before anything else goes down. A second stop asked for meanwhile changes nothing, a part that fails to close does not keep the others from closing, and any assistant or background work started for the editor stops with it, so nothing is left running afterwards.

### An open editor page carries on through a server restart

An open editor page reconnects by itself after the server restarts, with no reload by hand and no work lost. An edit that cannot be applied says so within seconds, and a restart in the middle of an edit never leaves the page waiting forever. A signed-in assistant shows as available straight after a restart. Whenever a feature cannot run, the reason is printed on screen on that feature's own control, never only in a tooltip, and it stays there until the feature can run.

### Which cut list opens on start, and the address that reopens it

{{28-082}}

- Exact: yes

### One tool of the editor that fails to start never stops the editor or the other tools

{{29-003}}

The tools the page shows are exactly the ones the server is running for it.

- Exact: yes

### The editor shows only the tools the site has switched on

The editor's tools follow the site's switches. With the assistant switched off, no assistant tool appears (the edit chat, shortening by the assistant, assistant searches, the Ask window). With the help for the editing program switched off, nothing that sends to, reads from or follows Resolve appears (see Resolve is optional). A tool that is off is simply not there: no greyed button, no empty panel. If the server cannot be asked, nothing is taken off.


### With no cut list open, the editor offers to open one or a recent one

Panel "Empty", aside "no cut list open": "Open a cut list to start editing" with the line "Pick a cut list of this episode, start an empty one, or hand the board over." and, when there are any, " Recent lists:". Buttons: "Open cut list" (primary; disabled, with a tip saying why, while opening is not possible) and one button per recent list (its title, and "rev N" when known); pressing one opens it. Offline with no list loaded, this empty state shows.

- Exact: yes

### While a cut list opens, the editor says nothing made offline is lost

{{29-013}}

- Exact: yes

### Each device remembers where the person was in each cut list

Each browser keeps, for itself only (not in the cut list, not on the server): the playhead, the lane's zoom and scroll, the selected cuts (up to 500), the top card in the list and how far it was scrolled, and the view (cards, lane or staged). It is saved within about half a second of any change, scrolling included, and when the page is hidden or closed. Up to 40 cut lists are remembered per device; the one used longest ago is forgotten first. On opening a list it is put back once: the selection (without scrolling), the phone's tab (never over the edit view), the zoom, the scroll, and the playhead (left alone if already playing). The list holds on its top card for 2.5 seconds while things settle; any wheel, touch, pointer or key lets go at once. A damaged record is ignored, and a browser that refuses to store anything remembers nothing.

- Phone and desk: each device keeps its own places, so a phone and a desk can stand at different points of the same cut list.

### The Cut lists sheet opens from the header and switches cut list or episode

- The header crumb (the open cut list's name) is the sheet's trigger: a focusable button, tooltip "Switch cut list or episode", a small chevron after it. Click, Enter or Space opens the sheet.
- The empty editor's "Open a cut list" button opens the sheet on the lists page.
- Desktop: a 600 px dialog in the middle (at most 760 px tall), red rule on top. Phone (700 px or narrower, or a coarse pointer): a bottom sheet the full width, 92% of the height, 48 px row actions shown as icons with full accessible names ("Duplicate E1 V2").
- The sheet is modal: keys typed in it never reach the editor; Tab and Shift+Tab cycle inside it.
- Escape on any inner page (name form, confirm, episodes, offline) steps back to the lists page; Escape on the lists page closes the sheet.
- A close button (shows "Esc") and a click on the backdrop close it. Focus returns to what had it.
- Every time the sheet opens it reads the server again (another device may have made a list).
- Sheet titles: "Cut lists", "Episodes", "Offline".
- Loading lines: "Reading the episodes", "Reading <episode>". A failed read shows the error and a "Try again" button, which reads everything afresh.
- Any request that cannot reach the server says "the server cannot be reached: cut lists are listed and made by the server, so this needs a connection".
- An answer that arrives for a page the person has already left is ignored.

- Who: anyone signed in.
- Name and search words: the Cut lists sheet. Search words: cut lists, switch cut list, open cut list, episodes, projects.
- Exact: yes

### The lists page shows the episode's cut lists, newest first, with what is open, last opened and kept on this device

- Episode box: "Episode <name>" and a "Change episode" button.
- The episode shown first: the open list's episode, else the episode with the newest cut list.
- An "Offline" row: one line saying what is kept on this device ("<n> cut lists on this device · <size>", "Nothing kept on this device for offline yet.", "Downloading <name> for offline…") or "Working offline: edits wait on this device." (gold), and a button "Offline" or "Offline settings".
- "Cut lists", newest first (by last change, then name). Each row shows the FILE NAME (not the title); a muted line: "from <title>" only when the title differs from the file name, "<n> cut(s)" (cuts in the cut, not on the shelf), "rev <n>", or "cannot be read" for a file that will not open (it is still listed, with its error); tags "Open now" (the open list), "Last opened here" (gold; the list this device last left this episode on, remembered per device for up to 200 episodes, only marked and never opened by itself from this sheet), "On this device" or "On this device (part)" (kept for offline here, or by the keep-on-this-device feature). The tags and the Offline row update as a download runs (at most four times a second).
- Clicking a row opens that list (clicking the open list just closes the sheet).
- Row buttons: "Keep" (only where the keep-on-this-device feature is present: closes the sheet and hands the list to it; offered for any list), "Duplicate" and "Rename" (only when the server can write cut lists).
- Empty episode: "No cut lists in <episode> yet. Hand the board over, or start an empty one."
- "Start a cut list" section (only when the server can write): "Empty cut list". Where the episode cannot be written, the sheet says that cut lists cannot be made in it because it is read-only.
- When the editor is opened through the dashboard, a footer: "Signed in as <user>" and an "All episodes" link back to the dashboard's episode list. While offline the link is refused with "You are offline: the episode list needs the server, so this cut list stays open"; otherwise edits waiting on the device are sent before leaving.

A cut list made on one device appears at once there and within about 10 seconds on every other device showing the sheet.

- Exact: yes

### Opening another cut list keeps every unsent edit and everything already loaded

Opening a list first saves the edits still waiting to this device's storage, then opens the new list in place, without reloading the page: the episode's transcripts, clips and media stay loaded. The list being opened becomes this episode's "Last opened here" list on this device.

Opening another is refused, with the reason, when it is not a cut list ("a project file is a .cut.md -- <x> is not one"), does not exist ("no such project file: <path>"), is not one of this episode's cut lists ("<x> is not one of this episode's cut lists -- switch the episode first"), is already open ("<x> is already open"), or an edit is running ("an edit is being applied -- wait a moment, then switch"). A cut list that will not read opens as an error: "<x> did not open: <error>". Note "<x> is open".

- Exact: yes

### The episodes page lists every episode with its counts

A "Back to the cut lists" button. This person's recent episodes first, then every episode: its last folder name, "<n> cut list(s)", "in <parent folders>" when nested, "Open now" on the open one. A click shows its lists. With none, it says there are no episodes yet, and where it looked. A new list appears at once on the device that made it and within about 10 s elsewhere. Naming an episode that is not there is refused: "there is no episode <ep> here"; a malformed episode name: "that is not an episode".

- Exact: yes

### A new, empty cut list is made from the sheet

"Empty cut list" asks for a name. The name has spaces and quotes trimmed and a trailing file ending dropped. Refused: empty ("give the new project a name"); any folder part, "." or "..", or any of \ / : * ? " < > | ('a project name is a file name: no folders, no \ / : * ? " < > | in it'); an existing name ("<x> already exists -- pick another name (nothing here overwrites a cut list)"); a read-only cut list open. A name over 1024 characters, holding a control character, starting with "." or starting or ending with a space is refused the same way. A name already taken is refused before anything is made. Before the list is made the sheet shows what it will hold (its name, the episode, its number of cuts and its frame rate), and nothing is written until the person confirms. A new cut list starts at revision 1, stamped "by Timeline Cards (new, empty)", its project the episode's name, its title the given name, word timing, no cuts, and takes the open cut list's frame rate, drop-frame and timeline start, or the defaults (01:00:00:00). It opens at once.

- Who: anyone signed in, where the episode can be written.
- Exact: yes

### With the help for the editing program on, the sheet also offers the episode's live Resolve timeline

Where a computer with Resolve is connected for this person, a row names the project and timeline Resolve last reported, and says whether Timeline Cards could go to the live timeline. Going back to the live timeline: "the live timeline is already open"; refused while an edit runs; shows the last-seen timeline at once, marked as waiting for Resolve's next report; note "the live timeline". On a server with no computer running Resolve, the person is told there is no Resolve to go back to. Only this episode's own Resolve timelines are offered.

- When the help for the editing program is off: no such row; the sheet lists cut lists only.
- Exact: yes

### The episode's browser lists every transcript and cut list, and several can be chosen at once

Inside the editor, the episode's browser lists every transcript and every cut list of the episode, can be filtered and searched, and lets a person choose several at once: Ctrl or Cmd with a click adds or removes one, Shift with a click takes a run, and on touch, select mode ticks each one tapped. What is done next (opening, filing into a bin, searching within them) applies to every one chosen. Among the people, only transcripts filed under a named person count as interviews; a news clip or other montage source is listed with the montage material even when its speakers carry names.

- Who: anyone signed in.
- Name and search words: the episode's browser. Search words: transcripts, cut lists, browse, choose several, interviews.

### A link to one cut can be copied, and opening it selects that cut

{{33-045}}

- Ways in: the cut's More menu, and the selection's.
- Exact: yes

### Cut lists that cannot be written are opened read-only and nothing is written to them

Where a cut list or its episode cannot be written, the editor opens it read-only: every edit is refused with the reason, and nothing is ever written to it. An editor never drops anything a cut list file holds that it does not itself show: every save keeps the rest of the file as it was.

### The app on the editor's computer opens the editor in a window of its own

On an editor's computer the editor can also be opened in a window of its own, with no browser around it, from the app on the editor's computer: the editor's header is the window's title bar (see "In a desktop app window the editor is one whole window whose header is its title bar"), it signs in to the same dashboard, opens on the episode list, and updates itself with the app, from its settings, keeping its settings and everything kept on the computer. It needs the studio's dashboard to be reachable, as the browser does. Its menu:

{{33-099}}

- Name and search words: the editor window. Search words: editor window, desktop, window, menu, app.
- Windows and macOS: the menu's keys are given as on Windows; on a Mac, Cmd stands for Ctrl and the menu sits in the menu bar.
- Exact: yes

#### Lessons

- Met: CE1-125, CE1-128, CE3-101, CE3-106, CE1-126, CE1-127, CE1-129, CE1-130, CE1-131, CE1-132, CE2-174, CE2-175, CE2-176, CE2-177, CE3-102, CE3-103, CE3-104, CE3-107.
- Met for another part: CE1-048 (in "A new, empty cut list is made from the sheet"), CE1-012 (in "The episode's browser lists every transcript and cut list, and several can be chosen at once").
- Tied to an arrangement: CE3-105 (the promise is in "Opening an episode goes into the editor at the cut list last left there").

## Resolve is optional

### With the help for the editing program switched off, the editor never mentions it and offers the exports

When a site switches off the help for the editing program, nothing in the editor names Resolve or any editing program: no Send to Resolve button, label, tip or menu row, no "Resolve: not connected", no live timeline in the Cut lists sheet and no "last sent to" timeline on a cut list's row, no following of Resolve, and no keys taken from a preset in Resolve (the lane uses the editor's own keys). Where Send to Resolve stands, the editor offers the exports instead: an XML, an OTIO and an EDL of the cut, and a text script (see Timeline Cards: the hand-over to Resolve, and exports: Exports). Everything else works exactly the same: the cut, playback, the transcripts and search, the shelf, offline work, and every key, button and gesture.

- When the help for the editing program is off: as above; switching it on again brings every Resolve control back with nothing lost. A new site starts with the help for the editing program on (and Timeline Cards itself off until an admin switches it on).

### With Resolve closed or absent, everything still edits and nothing shows as a fault

With the help for the editing program on, every editing feature works with Resolve closed, or on a computer that has none, and nothing about Resolve being away shows as a fault. Sending a cut to Resolve, bringing Resolve's changes back, and following Resolve are three separate commands, each the person's own choice, and none happens as a side effect of another. Whatever came from Resolve stays on screen, marked as stale and since when. An action that needs Resolve is refused at once with the reason, never left waiting. That no computer can drive Resolve for this page is said in a soft note, once, not as an error. A person's own key preset from Resolve survives every restart of the server and the editor.

- Who: anyone signed in; only their own signed-in computers' Resolve is ever driven (see Timeline Cards: the hand-over to Resolve, and exports: Which computer is driving Resolve).

### Following Resolve is off until switched on, and scrolling never switches it off

On loading or refreshing, the editor reopens what was last open in that episode and never jumps to whatever timeline is active in Resolve; following Resolve's playhead is off until the person switches it on. It is switched on or off only by its own control in the editor, or by its key in Resolve, which also brings the current card into view. No way of scrolling (wheel, drag, keys, touch, controller) switches it off. While it is on, every change of the card under Resolve's playhead brings that card into view.

- Ways in: the editor's follow control, and its key in Resolve.

#### Lessons

- Met: CE3-079, CE3-080, CE3-081, CE3-082, CE3-083.
