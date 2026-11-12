# Timeline Cards: the shelf, gap notes, keep, looks, the lane feature, audio, the Windows and Android apps

Terms used throughout:

- **Cut list**: the editor's document, the ordered list of interview pieces that make the edit.
- **Cut** (or **card**): one piece of one interview clip, from an in point to an out point, with its words.
- **The cut**: the cuts that are on the timeline, in order (as opposed to the shelf).
- **Gap**: a stretch of black (silence) between cuts that is its own item on the timeline.
- **The shelf** (also "staged"): cuts kept to hand but out of the cut, stored in the cut list file's own `## staged` section(s).
- **Category**: a named sub-shelf, stored as a heading `## staged — <name>` in the file.
- **Saved sequence**: a run of cuts taken out of the cut whole and kept with its exact seconds and gaps, stored in a `## ⧉` section.
- **The head**: the playhead.
- **The lane**: the timeline strip of clips under the cards.
- **Toast**: the small transient message at the edge of the editor.
- **Every edit** listed below is one undoable step (Ctrl+Z undoes it) and is synced to every device on the same cut list like any other edit, unless a bullet says otherwise.

## The shelf panel: Staged and Sequences tabs
(source: features/shelf/client.ts, features/shelf/ops.ts, features/shelf/styles.ts)

- The shelf replaces the built-in shelf list in two places: the right-hand rail of the desk layout and the shelf tab of the phone layout. It is drawn only while a cut list is open; with none open it is empty.
- The panel's bar holds two tabs, each with a count: **Staged** (number of staged cuts in all staged sections) and **Sequences** (number of saved sequences).
  - The tab chosen is remembered per browser (local storage key `tc_shelf_tab`, values `staged`/`seqs`; default Staged). It is never written into the cut list file, so two devices may look at different tabs of one shelf.
- A hidden panel (for example the phone shelf tab while on the desk) is not redrawn until it shows.

### The desk rail split
- On the desk rail only, an icon button gives the shelf the rail's whole height ("Give the shelf the whole rail") or gives the section list its half back ("Show the sections"). It shows a pressed state while the shelf is tall.
- The choice is remembered per browser (`tc_shelf_rail`: `tall` or `split`).
- With no choice saved, the shelf takes the whole rail automatically whenever the rail is shorter than 440 pixels.
- While tall, the section list is folded to its title bar; clicking that bar sets the split back to half each.
- Normal split: section list 2 parts, shelf 3 parts of the rail's height.
- In the rail a staged card's meta line is kept to one line.

### Category chips (Staged tab)
- A horizontally scrolling row of chips: **All** (count of every staged cut), **Uncategorised** (count on the plain shelf), then one chip per named category in file order, including empty ones, each with its count.
- A category whose name contains "interviewer question" (any case) is **locked**: its chip carries a lock icon and nothing can be filed or staged into it.
- A file with the same category heading twice shows one chip; its count adds both.
- Clicking a chip filters the list to it. The filter is remembered per browser (`tc_shelf_filter`: `*` for All, `=` for Uncategorised, `=<name>` for a category). If the remembered category no longer exists (removed on another device), the shelf shows All and saves that.
- Choosing a filter while on the Sequences tab switches to the Staged tab.
- The chosen chip is scrolled into view inside its strip (never by scrolling the page).
- **New category** button (plus icon) opens the New category dialog.
- **All categories** button (more icon, key U) opens the categories overlay.

### Staged card list
- Each staged card shows: a grip, its words (the card's lead line, or the clip name when it has none), the speaker's short name, its duration, its block reference (`^<id>`) when it has one, and on the All filter the category it is under ("uncategorised" for the plain shelf). Its left edge carries the speaker's colour.
- Each card has a **Listen** button (play icon) and a **Place** button. While the card plays, Listen turns into **Stop**. Listen is absent when playback is turned off (no Web Audio available).
- Locked cards (in a locked category, or flagged as a question) show a lock chip "Question" instead of Place, are not draggable, and are listed after the rest under the heading "Interviewer questions: reference only, not placeable". Only the first 3 are shown, with a **Show all N** / **Show fewer** button when there are more than 3.
- Empty states (exact text):
  - nothing staged at all: "Nothing staged yet. Stage a card to keep it to hand: it leaves the cut and waits here, in the file's own ## staged section."
  - a filter with nothing in it: "Nothing in <the shelf | category | the plain shelf> yet. Right-click a staged card (hold it on a phone) to file it here, or drop one on the chip above."
- Clicking a staged card (not on a button) selects it; the views' inspector then shows it as "Staged card".
- A card just staged here is scrolled into view once and marked (cyan border) for 2.4 seconds.
- **Place** (or "Place in the cut" in its menu) takes the card off the shelf and puts it into the cut: right after the focused cut if one is focused, otherwise at the playhead boundary rule (see "Put back at the playhead" below). The placed cut becomes the selection. Toast: "Placed <speaker> in the cut." with Undo. Refused for locked cards (menu item disabled with the tip "Interviewer questions are reference only: they never go in the cut").

### Listening to staged cards (the bench player)
- Clicking anywhere on a staged card other than its words and buttons plays the card from its in point to its out point, off the timeline. Clicking the card that is already playing (not on its words) stops it.
- Clicking on a **word** of a staged card plays from that word to the card's out point and marks that word in the card's line. The word is found by matching the card's displayed line against the clip's timed words (the words service's tokens); if the clip's timed words have not arrived within 1.5 seconds, or the line and the timed words differ in length by more than max(3 characters, 20 percent), it plays from the card's start instead. A word that starts before the in point starts at the in point. A click between two words picks the nearer word. Works for any language, including ones written without spaces.
- Pressing on a staged card asks for its clip's timed words in advance so the click has them.
- No playback while a card is lifted (phone) or select mode is on.
- Only one thing plays at a time: starting the bench pauses the timeline's playback; starting timeline playback stops the bench.
- Escape stops the bench and clears the marked word.
- Opening a different cut list stops the bench and discards its audio engine.
- Errors shown as warnings: "There is nothing to play there." (zero-length cut), "Playback is not available here." (no Web Audio), "Could not play it: <reason>".
- The bench has its own audio cache of 16 MB (about 1.4 minutes of mono 48 kHz audio), separate from the main 64 MB cache, created on the first play.

### Staged card context menu (desk) / long press (touch)
- Right-click on a staged card opens its menu; right-click on the shelf background opens the categories overlay.
- On a touch screen, holding a finger 350 ms on a staged card (without moving more than 10 pixels) opens the card's menu, or the categories overlay when held on the background; the device vibrates 12 ms. The click that the lift produces is swallowed for 500 ms. Right-click on touch devices does nothing here.
- Menu title "1 staged cut" (or "N staged cuts"). Items:
  - **Place in the cut** (disabled for locked cards).
  - **File under (now: <category or uncategorised>)** opens the File under page: Uncategorised (the plain shelf), every unlocked category (plus the current one if locked), each with a count and a check on the current one, then **New category…** (opens a dialog to file under a new name).
  - **Listen** / **Stop listening** (when playback exists).
  - **Clip colour…** (Shift+C) opens the colour page.
- Filing: one edit moving the staged cut(s) to that category (created if needed). Toast "Filed under <cat>." or "N cuts filed under <cat>." with Undo. Refusals: "Those cuts are no longer on the shelf.", "Already under <cat>." / "Already on the plain shelf."

### Phone: lift and file
- On a touch screen, two taps on the same staged card within 450 ms **lift** it (dashed cyan outline, vibrate 15 ms, bench stops). Toast: "Lifted: tap a category chip to file it there, or tap the card again to put it down."
- With a card lifted: tapping a chip files it there (the All chip is refused: "Pick a category, or Uncategorised: All is only a view."); tapping the same card again puts it down ("Put down."); tapping another card says "Tap a category chip at the top of the shelf to file the lifted card, or tap it again to put it down."
- Escape puts a lifted card down.

### Desk: drag a staged card onto a chip
- A staged (unlocked) card can be dragged with the mouse onto a category chip (not a locked one); the chip highlights; dropping files it there.

### Staging cuts of the cut into the shelf
- **Drag a card of the cut onto the shelf** (mouse or pen, not touch): after 6 pixels of movement, the shelf shows as a drop target. Over a chip: stages under that chip's category. Over the top or bottom half of a staged card: lands before or after that card in its shelf. Elsewhere on the shelf: lands in the category the shelf is showing (All and Uncategorised both mean the plain shelf). A selected card carries the whole selection. Escape or the window losing focus cancels. The drop cancels the views' own reorder drag. Presses on a card's controls or words do not start this drag.
- **The views' Stage buttons** (on a card, in the inspector, in the edit view) also stage into the shelf on show, using the selection; from the edit view the editor then switches to the cards view.
- Staging into a locked category is refused silently into the plain shelf, with the warning "Interviewer questions are reference only: nothing is staged into them. It went to the plain shelf." and the shelf turns to Uncategorised.
- After staging, the shelf switches its filter or tab so the staged card is visible, scrolls to it, and marks it for 2.4 s.
- Toast "Staged <speaker ^ref> under <cat>." / "...on the plain shelf." (or "Staged N cuts ..."), with Undo. Refusal: "Those cuts are no longer in the cut."

### Categories overlay (key U, or the All categories button, or right-click on the shelf background)
- A popover titled "Staged · categories" listing All, Uncategorised and every category with counts and a check on the current filter; locked categories show a lock icon. Clicking a row sets the filter and closes the overlay.
- Each named category row has **Rename <cat>** (pencil) and **Remove <cat>** (trash) buttons.
- **New category…** at the bottom.
- Pressing U again closes it. U works only while the editor is on screen with a cut list open.
- **Remove**: one edit removing the category; its cards go to the plain shelf. Toast "Category <name> removed. Its cards are on the plain shelf." with Undo. If the shelf was filtered to it, the filter goes to All. No confirmation.

### Dialogs (names)
- Fields accept up to 120 characters; spellcheck and autocomplete off. Enter confirms, Escape cancels, typing in the field never triggers shortcuts. Errors appear in place under the field and clear when typing.
- **New category**: "A shelf of its own in the file (## staged — name). Cards are filed under it from their menu, or dropped on its chip." Button "Add category". Refuses an existing name ("There is already a category called <name>."), an empty name ("A category needs a name."), and anything the file's naming rule refuses (its message, capitalised). On success the filter switches to the new category; toast "Category <name> added."
- **File under a new category**: button "File it".
- **Stage to a new category**: "N cuts leave the cut and wait on the shelf under the new name." Button "Stage".
- **Rename <cat>**: button "Rename". Unchanged name closes silently. A refusal from the editor shows its sentence, or "That name was refused." Toast "Renamed to <name>." with Undo. The filter follows the rename.
- **Rename the sequence**: same shape for sequences (also opened by double-clicking a sequence's name).
- **Delete this saved sequence?**: "“<name>” and its cuts leave the file. Undo brings it back while this window is open." Button "Delete for good" (danger). Toast "The sequence “<name>” was deleted."

## Saved sequences (Sequences tab)
(source: features/shelf/client.ts, features/shelf/ops.ts, features/shelf/player.ts)

- Empty state: "No saved sequences. Select a run of cards and press Save as sequence: the run leaves the cut and is kept here whole, with its exact seconds and the gaps between its cuts, in the file's own ## ⧉ section."
- Each sequence row shows: its name; meta "N cuts · total seconds · N notes · speaker names" (total includes every gap, including black before the first cut and after the last); up to 6 of its cuts (speaker colour bar, first line of words, duration) with "<x.xx> s black" lines between cuts that have a gap before them; "N before" / "and N more" lines when there are more than 6. While it plays, the 6 shown follow the cut that is sounding, which is marked.
- Buttons per row: **Play the run** (or **Stop**), **Put back at the playhead**, **Rename**, and a **Sequence actions** menu: Play the whole run / Stop playing, Put back at the playhead, Rename…, Delete for good… (danger).
- **Play the run** plays every cut in order with the black between them, off the timeline, through the bench player; empty sequence warns "That sequence has no cuts to play." Any timeline play stops it.
- **Put back at the playhead**: one edit putting the whole run back into the cut; the run becomes the selection. Placement: if the head is in black before an item, in front of it; if inside an item, before it when the head is in the item's first half, otherwise after it; past the end, after the last item; empty cut, at the end. Toast "The sequence “<name>” is back in the cut."
- **Drag a sequence row** onto the cards (lands before or after the card under the pointer, by top/bottom half, with an insertion line) or onto the lane (before the first clip whose middle is right of the pointer; after the last otherwise); dropped elsewhere in the cards area, it goes at the end. This restores it.
- A sequence just saved is marked and scrolled into view once.

### Save as sequence
- Available from the selection bar, the selection menu and the lane menu.
- The selection must contain at least one cut ("Select the cuts to save as a sequence.") and must be one unbroken run: every cut between the first and last selected item must be selected ("A sequence is a run of cuts next to each other: select one unbroken stretch."). Gaps inside the run go with it.
- Name: generated as "<speaker or clip>: <first words> (N cuts, S.Ss)" capped at 60 characters (words truncated with "..."); a typed category or sequence name is also limited to 60 characters by the file's naming rule; `#`, `<!--` and `-->` are stripped; a taken name gets " (2)", " (3)" and so on.
- On success: one edit, toast "N cuts saved as the sequence “<name>”.", the selection is cleared, select mode ends, the shelf turns to the Sequences tab.

## The selection bar and select mode
(source: features/shelf/client.ts, features/shelf/styles.ts)

- A floating bar over the top of the cards appears when 2 or more cuts are selected, or while select mode is on, and never in the edit view.
- Shows "N cuts selected" (narrow screens: "N cuts"), or "Tap cards to select" when none.
- Buttons (disabled when nothing is selected): **Move up** (R), **Move down** (D), **Save as sequence**, **Stage to** (opens the Stage to page: Uncategorised, unlocked categories, New category…), **Copy** (Ctrl C), **Cut** (Ctrl X), **More for the selection** (the selection menu), and **Clear selection** (Esc) or, in select mode, **Done** (ends select mode and clears the selection).
- Layout: on screens 700 px or narrower, Stage to, Copy and Cut are hidden and Save as sequence is icon only; between 701 and 1180 px Copy and Cut are hidden.
- **Move up / Move down**: one edit moving the selected block one item (cut or gap) up or down past the nearest unselected item. At the edge: "Already at the top." / "Already at the bottom."
- **Stage to <cat>**: one edit staging the selected cuts under that category (created on demand). Toast "Staged under <cat>" / "N cuts staged under ...". In select mode the selection is cleared afterwards.
- **Select mode** button: a floating button at the bottom right of the cards, shown only on screens 700 px or narrower or touch screens: **Select** / **Done selecting**. Turning it on says "Select mode: tap cards to pick them. Done ends it."; turning it off clears the selection. In select mode a tap on a card toggles it in the selection (not on its buttons), and a double tap does not open the edit view. Escape ends select mode. It is also exposed for the drawer's "select mode" row.

## The cut menus: lane right-click, selection menu, card right-click
(source: features/shelf/client.ts, features/shelf/ops.ts)

- **Right-click on a clip in the lane** (desk only; on touch the right-click is suppressed): opens a menu for that cut, or for the whole selection when the clicked cut is in it. A right-click on a gap in the lane opens nothing.
- **More for the selection** opens the same menu for the selection, with **Move up one slot** (R) and **Move down one slot** (D) first.
- Menu title "This cut" or "N cuts". Items:
  - **Copy** (Ctrl C), **Cut** (Ctrl X).
  - **Paste N cuts after this cut / these cuts** (Ctrl V), only when something was copied in this window.
  - **Send to** (page "Send to the end of"): every heading of the cut list in order (section headings prefixed "§ ", note headings "◆ ") with its count of cuts. Disabled with "This cut list has no sections" when there are none. Sends the block to the end of that section, after its last cut that is not moving. Refusals: "Select the cuts to send.", "That section is no longer in the cut list.", "Already at the end of "<name>".", ""<name>" is empty: drag a cut under its heading to start it." (an empty section followed by other cuts). An empty last section takes the block at the end of the cut. Toast "The cut / N cuts sent to the end of <section>."
  - **Stage to** (page).
  - **Save as sequence**.
  - **Clip colour…** (Shift C).
  - **Gain… (<current>)** (key hint Alt Shift ↑↓); the current gain is the first cut's, or "mixed".
  - **Reset gain to 0 dB** (key hint Alt Shift 0), shown only when one of the cuts has a gain. Toast "Gain reset on N cuts."
- **Right-click on a card of the cut** (desk only, not on text fields) opens the clip colour page directly, for that card or the selection containing it; Back gives the rest of the menu.
- Menus are a popover at the pointer on the desk (kept on screen, flipping up or left), and a bottom sheet with a grab handle on screens 700 px or narrower or on touch. Up/Down arrows move between items (wrapping), Enter/Space press, Escape closes. Clicking outside closes. Resizing the window closes an open menu. Keyboard-opened menus focus their first item.

### Clip colour picker
- Fifteen swatches (DaVinci Resolve's clip colours, never "Brown"), five to a row, each named in a tooltip; the current colour is checked when every target cut has it.
- **Default: <speaker>'s colour** (or "each interviewee's colour") removes the cut's own colour.
- **Every cut of <speaker> (N cuts)**: shown when all target cuts belong to one person and that person has more cuts than are targeted; widens the picker to every cut of that person in the cut list and on the shelf, so the next swatch colours them all in one edit.
- Toasts: "The cut coloured <colour>." / "N cuts coloured <colour>." / "... back to the interviewee’s colour." with Undo.
- **Shift+C** opens the picker for: the selection when the focused cut is in it, else the focused cut, else the selection, else the staged card shown in the inspector, else the cut under the head. With none: "There is no cut to colour: select one first." Opened near the card.

### Gain dialog
- Title "Gain for this cut" / "Gain for N cuts". Text: "In dB, on top of the automatic levelling: −30 to +30, 0 resets." plus, when the cuts differ, "These cuts have different gains now: all of them get this one."
- A text field starting at the first cut's gain, with "Down 1 dB" and "Up 1 dB" buttons; Up/Down arrow keys step 1 dB, with Shift 3 dB.
- Accepts "3", "+3", "-4.5", "3 dB", typographic minus signs, and a decimal comma; rounded to 0.1 dB and clamped to plus or minus 30 dB (not refused). Anything else: "“<text>” is not a number of dB."
- One edit; toast "Gain +3.0 dB on N cuts." / "Gain reset on 1 cut." with Undo. With no live cuts: "There is no cut to set a gain on."

## Copy, cut and paste of cuts
(source: features/shelf/client.ts, features/shelf/ops.ts, features/shelf/keys.ts)

- **Ctrl+C** copies the selected cuts (and selected gaps), else the cut under the head. If the reader has selected words on the page, Ctrl+C is the browser's own text copy instead. With nothing: "There is no cut under the head to copy."; with only non-timeline items: "Only cuts in the cut can be copied." Toast "N cuts copied. Ctrl+V pastes them after the cut under the head."
- The clipboard gets two things: plain text (one line per cut: its Obsidian block embed `![[<ref>]]` or `![[<person>_Transcript#^<ref>]]`, else its words) and a private type `application/x-timeline-cards-cuts` with the exact cuts (clip, person, in, out, fades, gain, colour, ref, words, highlights, note) and gaps (length, note), and the episode they came from. If the private copy fails, only the text is written; the window still remembers the copy.
- **Ctrl+X** copies, then removes the cuts from the cut; removed cuts go to the shelf (into the category of the section they were in). Toast "N cuts cut, and kept on the shelf too. Ctrl+V pastes them."
- **Ctrl+V** (the browser's paste event, not typing in a field, editor showing): takes only a paste of Timeline Cards cuts (private type, under 4,000,000 characters, valid shape, at most 2000 items), or plain text identical to this window's last copy. Anything else is left to other handlers.
  - Refused across episodes: "Those cuts were copied in another episode: they cannot be pasted here." (episode = the part of the cut list path before "/Script Docs/").
  - Lands after the cut under the head; if that cut is inside a selected stretch, after the stretch (so repeated pastes follow each other); with the head in black, before the next item; past the end, at the end.
  - One edit; every pasted cut and gap gets a new id; the pasted items become the selection and the head jumps to the first. Toast "N cuts pasted." or "Gap pasted."
  - An older copy format with a "gap before" on a cut (at least the minimum gap length) recreates that black as a gap item, except before the first cut.

## Shelf keyboard shortcuts
(source: features/shelf/keys.ts, features/shelf/client.ts)

- U: categories overlay (toggle). Ctrl+C: copy. Ctrl+X: cut. Ctrl+V: paste (listed, handled by the paste event). Shift+C: clip colour. All act only with a cut list open and the editor showing.
- Listed for the shortcuts sheet ("?") as four rows.
- Escape (heard, not bound): ends select mode, puts a lifted card down, stops the bench.
- Escape inside a menu or dialog closes it before any other key handler.

## Gap notes: on the cards and on the lane
(source: features/gapnotes/client.ts, features/gapnotes/ops.ts, features/gapnotes/styles.ts)

- A **gap note** is a short text on a gap ("danielle yen b-roll" on a 3.9 s gap), saying what the black is for. It is stored in the cut list file itself, as `<!-- note: … -->` lines under the gap's line, so it is visible in Obsidian. It belongs to the gap: it moves, copies, pastes and is deleted with it, including inside saved sequences.
- Maximum length 2000 characters (code points); the field stops there.
- Every change is one edit (synced, kept on the device while offline, undone by Ctrl+Z). If another device changes the same note, the last save wins.
- **On a gap card**: a note shows as a button with a pencil icon and the text (gold rule); a gap with no note shows an icon button "Add a note to this gap" (Shift N hint) in the card's head row.
- The card's accessible label reads "Gap of <x.x s> before cut <n> / at the end of the cut. Note: <text>".
- Clicking the note or the add button opens an inline editor on the card: label "Note on the <x.x s> gap before cut <n>", a 2-line text box (placeholder "What is this gap for? (b-roll, a title, music)", spellcheck on), buttons **Save** (Enter), **Cancel** (Esc), **Remove note** (only when there is a note), and the hint "Shift+Enter for a new line" (hidden on touch).
  - Enter saves; Shift+Enter adds a line; Escape cancels; clicking away from the editor saves (but switching to another window does not); opening another gap's editor saves the first.
  - An empty note removes the note. Saving unchanged text does nothing.
  - **Remove note** saves an empty note; toast "Note removed. Ctrl+Z brings it back."
  - If the note changes on another device while the editor is open, a warning shows inside it: "Changed on another device to “<text>”." or "Removed on another device." followed by "Saving puts yours in its place; Cancel keeps theirs."
  - If the gap disappears while its editor is open, the editor closes and, if the draft had new text, warns "That gap is no longer in the cut list, so the note was not saved: “<text>”".
  - A refused save warns "Not saved: <reason>. The note was: “<text>”".
  - Clicks inside the note area do not select or drag the card.
  - After the editor closes, the keyboard focus returns to the gap card.
  - Keys typed into the editor never trigger editor shortcuts. If the views redraw the card while typing, the editor is put back at once with the draft and caret kept.
- **Shift+N**: edits the note of the selected gap; if a cut is selected instead, the gap directly before it. Warnings: "Select a gap or a cut first: Shift+N writes the note on the gap (or the gap before the cut)." and "There is no gap before this cut." Listed in the keys list as "Note on the gap before the selected cut".
- **On the lane** (every lane except the edit view's): each noted gap shows its note inside the gap's span on the timeline (gold, up to 3 lines; 2 on screens 700 px or narrower), whitespace collapsed to one line, full text in a tooltip. Only the visible part of a gap is labelled; a visible width under 6 pixels shows nothing; under 56 pixels shows only a marker without text. Hidden in the edit view. Redrawn on lane scroll and zoom.

## Gap notes panel
(source: features/gapnotes/client.ts, features/gapnotes/styles.ts)

- **Header button "Gap notes"** in the editor's top bar (desk: text button with a count "N" of noted gaps, plus "+M" in gold when M old notes are waiting to be moved in; phone landscape: icon only with label "Gap notes, N, M to move in"). Clicking toggles the panel; pressed while open.
- The panel is a side sheet on the right, 560 pixels wide (a bottom sheet up to 88 percent of the screen height on screens 700 px or narrower), with a dimmed backdrop; clicking the backdrop or Close (Esc) closes it and focus returns to the header button.
- Bar: "Gap notes", "<N> gaps · <M> noted", Close.
- Without a cut list: "Open a cut list first."
- A status line: "Each note is saved in the cut list itself, under its gap: synced like any edit, kept on this device while offline, and Ctrl+Z undoes it."
- **The list**: every gap of the cut in order, each with: its section title, "Before cut <n>" or "At the end", the speaker of the following cut, its length and its start time (m:ss.s), its note or "No note", and buttons **Edit** / **Add note** (closes the panel, selects the gap and opens its inline editor) and **Go to the gap** (selects the gap, puts the head at its start, closes the panel, scrolls the gap into view).
- With no gaps: "This cut has no gaps. A gap is black between two cuts: add one with Shift+Insert at the head (or a card's More menu), then give it a note here."
- Footer: "Shift N writes the note on the selected gap, or the gap before the selected cut."
- Panel errors appear as a status line at the top of the panel. Opening another cut list clears the panel's proposal, plan, links and messages.

### Moving notes kept beside the cut list into the file (one-time migration)
- When a cut list opens, the page reads the old note files kept beside it (read-only): `.tcards/<name>/gapnotes.json` (gap notes) and `.tcards/<name>/summaries.json` (section summaries), plus this browser's own queue of note changes that an older page saved offline (local storage `tc-gapnotes-pending:<key>`, and its backup `tc-gapnotes-pending-backup:<key>`; at most the last 200 entries are applied, newest wins, an empty text removes).
- Files over 4 MB are not read ("it is too large to be a notes file, so it was not read"); unreadable JSON is reported ("it could not be read (<reason>)"). At most 5000 notes and 1000 summaries are taken from them; summaries longer than 4000 characters are shortened. If the server cannot be reached, only the browser queue counts and the files are read next time.
- The plan of what to move: each old note goes onto its gap (by the gap's id; an older note keyed by the cut after the gap goes onto the gap before that cut; one whose cut is gone goes onto the single free gap in front of a cut with the same clip and in/out, if exactly one exists). Each summary goes onto the section heading with the same section key. Anything that cannot go in is listed with its reason and left in the old file: "its gap is no longer in this cut list", "there is no gap before its cut any more", "its cut is on the shelf", "its cut is no longer in this cut list", "that gap already has a note in the file: “<text>”", "another old note goes onto that gap", "no section of that name is in this cut list now", "that section already has a summary in the file: “<text>”". Notes already identical in the file count as done.
- If some old notes are already in the file and others are not, the move is treated as done before, and the missing ones are listed as "it was moved into the file before and taken out since" rather than offered again.
- **On open, a toast** when there is something to move: "N notes kept beside this cut list can now live in it." with a **Review** button that opens the panel at that section. Offered once per page per state of the old files, and not at all if "Not now" was pressed for the same contents (remembered in local storage `tc-notes-move-later:<key>`).
- **Panel section "Notes kept beside the cut list"** (with a count): explains "Gap notes and section summaries now live in the cut list itself (the .cut.md), so they sync, undo and show in Obsidian. These were kept in <files> [, and N changes were waiting on this device]. Moving them writes them into the cut list as one change; Ctrl+Z takes it out. The old files are left as they are, as a backup." Then a "+" line per note or summary to be added ("Gap before cut 4, 3.9 s: “…”", "Summary of “<section>”: “…”"; texts over 60 characters shortened with "…") and an "=" line per leftover with its reason; read errors as warnings.
  - **Move N notes into the cut list**: checks the whole batch first; applies it as one edit. Refusal: "Nothing was moved: <reason>". Success toast: "N notes moved into the cut list. The old files stay as a backup." with Undo. The "Not now" memory is cleared.
  - After a move, once the editor is live and has nothing waiting to send, the page asks the server for the cut list and, if every queued offline note is in it, copies the queue to the backup slot and removes the queue. Otherwise the queue stays and is offered again.
  - **Not now**: remembers the dismissal for these contents; message "Left where they are. They are offered again here whenever you want them."
  - **Put it on the gap before the same cut** (on a leftover, when a free gap in front of a cut with the same span exists): one edit putting that note on that gap; toast "Note put on that gap. Ctrl+Z takes it off."
- The old files are never written or deleted by the editor.

### The old app's notes
- Section "The old app's notes": "Notes typed on gaps in the old Timeline Cards page are kept in the episode's timeline_notes.json. Bring them in to see what they would add first; nothing changes until you accept."
- **Bring in the old app's notes** (busy text "Reading the old notes") sends the current cut list to the server, which reads `<Episode>/Script Docs/timeline_notes.json` (only for a cut list stored under a `Cuts` folder) through the old Python code, and answers with a proposal. Each old note (keyed in the old store by the cut after the gap) goes onto the gap before that cut. Skipped (listed with "=" and "Before cut <n>: left as it is, <why>"): "there is no gap before this cut any more", "this gap already has a note: “<text>”". Notes already identical are silently skipped. Old notes longer than 2000 characters are shortened.
- Result text: "No old notes file was found at <path>." / "N notes from <path> would be added." / "<path> has nothing new for this cut list."
- **Add N notes** applies all as one edit; toast "N gap notes added from the old app." with Undo; a refusal says "Nothing was added: <reason>. Bring them in again to see the new picture." **Not now** / **Close** discards the proposal.
- Failure: "The old notes could not be read: <reason>".

### What the conform builds
- Section "What the conform builds": "When this cut list is conformed into Resolve, each note becomes a Text+ title on its own Gap notes track, exactly inside its gap, or a Green marker spanning the gap where a title cannot be placed exactly."
- **Show what the conform builds** (busy "Working it out"; afterwards "Work it out again") sends the current cut list to the server, which runs the old conform planner dry (nothing written, Resolve not called). Notes of several gaps in a row before the same cut are joined with " · ".
- Result: a summary sentence ("N gap note(s): the AGENT route puts each one in a title over its gap where one fits, else a marker; the LIBRARY route always writes a marker spanning the gap"), then one row per noted gap: "Cut <n> · <timecode in> to <timecode out> · <seconds> s", the note, and chips:
  - "Text+ title on <track name>" when the gap is at least 5 seconds;
  - "Title if it fits, else a Green marker" (gold) when shorter than 5 seconds (Resolve's default title length), with the footnote "A gap under 5 s gets a title only if Resolve honours the In/Out marks; otherwise it gets the Green marker (GAP-NOTES.md)."
  - "Library route: marker 1 frame in (a section starts there)" when another marker already holds the gap's first frame; "Library route: no free frame for the marker" (red) when the gap is one frame and that frame is taken.
- With no notes: "No gap has a note, so the conform builds no titles or markers for gaps (N gaps in the cut)."
- Failure: "The conform plan could not be worked out: <reason>".
- The page never sends a frame rate, so the plan always uses the rate the cut list implies.

### Story Deck links and deep links
- Section "Story Deck": **Look for Story Deck work** fetches: the canvas the cut list was made from (its `canvas:` frontmatter), whether that is an "ordered" canvas in Script Docs ("Made from the canvas <name>, an ordered canvas (Story Deck builds these)." / "Made from the canvas <name>." / "This cut list names no canvas."), the episode's Story Deck work folders (folders named `storydeck-*`, newest 20, each "a board" or "no board yet" with its date), and up to 6 ordered canvases in Script Docs ("Ordered canvases in Script Docs: …"). Without the work folder setting: "Set TC_STORYDECK_WORK on the server to list this episode's Story Deck work folders."; none found: "No Story Deck work folder for <episode> yet." Failure: "Story Deck: <reason>".
- **Open Story Deck** link (new tab) when the server has a Story Deck URL configured.
- **Copy a link to the selected cut** (disabled with "Select a cut first"): copies the editor URL with `?key=<cut list>&ref=<block ref>` (or `&cut=<id>` when the cut has no plain ref). Toast "Link copied. Opening it selects this cut." If the clipboard is refused, the link is shown in the panel: "Copy this link: <url>".
- **Opening a deep link** (`?ref=<ref>` with or without a leading ^, or `?cut=<id>`), once per page load after the cut list arrives: selects that cut (in the cut or on the shelf) and scrolls to it; in the cut it also puts the head at its start; on the shelf it says "^<ref> is on the shelf, not in the cut." Not found: "No cut in this cut list comes from ^<ref>." / "That cut is not in this cut list."
- Gap-notes toasts appear centred near the bottom (140 px up; 200 px on phones), 5 s, or 12 s when they carry a button; each has Dismiss. A new toast replaces the previous one.

## Gap notes and Story Deck: server routes
(source: features/gapnotes/server.ts, features/gapnotes/sidecar.ts, features/gapnotes/bridge.py)

- These routes add no access check of their own; whoever the editor server lets in may call them. None writes a file, calls Resolve or calls Claude.
- Cut list keys are checked: a bad key answers 400 `bad-key`; a cut list that is not a file answers 404 `not-found` "there is no cut list <key>".
- **GET /api/gapnotes?key=<key>** (also `?project=`), and the same at **GET /api/gapnotes/legacy**: returns the two old sidecar files for that cut list (read only): for each, its relative name, whether found, a read error, and its entries.
- **POST /api/gapnotes**: always 410 `moved` "gap notes live in the cut list now: reload the page, and the note is saved as an edit" (for old pages and their offline queues).
- **POST /api/gapnotes/import** `{project, state}` (body up to 16 MB): `state` is the page's current cut list (pending edits included); refused 400 `bad-body` (not a JSON object), 400 `bad-state` "the cut list sent with the request is not readable" / "the cut list sent with the request is not valid: <first problem>". Answers `{project, store, store_found, store_notes, matched, ops, labels, skipped}`. 409 `changed` "the cut list changed while it was being read; try again" when the Python side sees different cuts.
- **POST /api/gapnotes/plan** `{project, state, fps?}`: `fps` used only when a number from 10 to 120. Answers the frame rate, drop-frame flag, start timecode, track name, marker colour, counts of cuts/gaps/gap notes, duration and one span per noted gap (start/end frame, frames, seconds, note, timecodes, short flag and reason, the fallback marker's colour/name/note/duration, and the library route's frame/duration/shifted/lost). At most 5000 notes per request.
- **GET /api/storydeck/links?project=<key>** (or `?key=`): `{project, episode, canvas, url, workConfigured, work, canvases, fromStoryDeck}`. Canvases: `.canvas` files in the cut list's Script Docs folder, newest 40. Directory listings stop at 2000 entries and skip dot-files. Only the first 64 KB of the cut list is read for its `canvas:` line.
- Python helper failures map to: 422 `bridge-refused` (the helper refused, with its sentence, for example "the cut list is empty", "the reference reader cannot read this cut list: …", "a note names cut …, which this cut list does not have", "cut N is not the cut the note was written for (the cut list changed while it was being read); try again", "the notes are not a list of at most 5000", "the request is not a JSON object", "the gap-notes bridge failed: <type>: <what>"), 504 `bridge-timeout` (30 seconds per call), 503 `no-python`, 503 `busy` (queue full; at most 2 gap-notes calls run at once), 503 `bridge-failed` (anything else, or an answer without its cuts/spans).
- The Python helper is registered when the server starts (a missing helper file fails the server's mount), and started on the first call; it also answers a `ping`.
- Environment variables:
  - `TC_STORYDECK_URL`: the Story Deck address for the Open Story Deck link (only http/https accepted; otherwise no link).
  - `TC_STORYDECK_WORK` (fallback `STORYDECK_WORK`): Story Deck's work folder base; the episode's `storydeck-*` folders are listed from `<base>/<episode>`. Unset: no work listing.

## Keep a cut list on this device (offline copy): the "On this device" panel
(source: features/keep/client.ts, features/keep/styles.ts)

- Purpose: a cut list kept on a device opens, edits and plays with no network.
- Opened from: the toolbar button **On this device** (down-arrow icon, tooltip "Keep cut lists on this device: what is kept, how big, remove"), the command palette entry "On this device: keep this cut list offline" (also found by the words offline, download, storage, keep, device), and a "Keep" action on a cut list in the projects sheet (that sheet is another section). Only mounted when the page has a device store.
- The panel is a centred dialog 640 px wide (a bottom sheet on screens 700 px or narrower or touch screens, 44 px targets), titled "On this device", with Close (Esc). Escape first closes an open folder form, then a remove confirmation, then the panel. Tab cycles within the panel. Closing returns focus to where it was. Progress repaints at most about every 250 ms.
- Status messages appear at the top: success (cyan), warning (gold), error (red).

### "This cut list" (the open cut list, or the one picked)
- With no cut list open: "No cut list is open."
- Name, and status: "On this device · <size> · brought up to date <date time>" / "Partly on this device · …" / "Not on this device". The card's edge is cyan when complete, gold when partial.
- On opening, the panel works out what the list needs ("Working out what it needs") before fetching anything, and shows sizes: **Audio**, **Video** (with an **Include video** checkbox; shows the size, "none", or "not kept"), **Waveforms**, **Transcripts and data** ("about <size>", an estimate of 32 KB per document), **Clips** (count).
  - Unchecking Include video stores `tc.keep.video = off` in local storage (checking removes it) and recomputes the sizes. Default is video included.
- Warnings in the plan: "The server has no audio for <clips>: it/they will not play offline." and (with video on) "No preview video yet for <clips>."
- A failure to work out the plan shows the reason and **Try again**.
- Main button: **Keep on this device · <total size>** when not kept; **Update the copy · <size still to fetch>** (or just "Update the copy" when only documents would be fetched) when kept.
- While keeping: a progress bar, "<fetched> of <total> · <what>" ("Asking the server what it needs" before the first progress; lines such as "Starting", "Audio: <clip>", "Video: <clip>", "Peaks: <clip>", "Documents N of M", "Translations", "Done"), and **Stop**.
- On the first non-background keep, the browser is asked to keep the site's storage permanently (persistent storage request).
- Outcomes:
  - "<name> is on this device: it opens, edits and plays with no network."
  - "<name> is on this device. The server has no audio for <clips>."
  - Stopped (warning): "Stopped. What landed stays on this device; keep again to finish."
  - No network: "the server cannot be reached (<reason>): connect, then keep again; what landed stays"
  - Device full: "This device has no room left. Remove another cut list from it, then keep again." (or "this device has no room left for it" when even the first write fails)
  - Server error: "<url or clip>: the server answered <status>" or "<clip>: it did not arrive whole, twice".
  - Removed during keep: "It was removed from this device while it was being kept." (the keep stops at its next write and anything it wrote afterwards is deleted again).
  - Not a cut list: "<key> is not a cut list".
- **Remove from this device** asks to confirm: "Remove <name> from this device? Its edits are safe on the server; only the copy here goes." with **Keep it** / **Remove**. Removing stops a keep of the same list first. Result: "<name> is no longer on this device (<size> freed)." or "Not removed: <reason>".
- Only one keep runs at a time; a second request while one runs is ignored.

### "Kept here": every kept list
- Each kept list, newest first: name, episode, size, "up to date" or "part" and the date; the open list is marked. Buttons: **Details** (shows that list in the upper section and works out its plan), and a trash icon **Remove <name> from this device** (with the same Keep it / Remove confirmation).
- Empty: "Nothing is kept on this device yet."
- Total: "Using <size>" plus "of <quota> this browser allows" (browser) or "· <free> free on the disk" (apps).

### "Where" things are kept
- In a browser: "This browser's own storage for this site." with a tag: "Kept until you remove it" (persistent granted), "The browser may clear it when space runs low" (refused) or "Not asked yet"; button **Ask to keep it** (asks the browser again) unless granted.
- A browser that can keep nothing (private window, storage off): "This browser cannot keep anything (private window, or storage turned off). Cut lists open only with a connection here."
- In the Windows or Android app: "The Windows app's project folder" / "The Android app's projects folder": "real files, by episode and cut list, the clips by name. Separate from the app's browser cache.", the folder path, **Open folder** (opens the kept list's folder if the shown list is kept, else the root), and **Change folder**:
  - A text field "New folder" and **Use this folder**; empty: "Type the folder to keep things in".
  - If cut lists are already kept in the current folder, the app refuses with "N cut lists are kept in the current folder: move them, or leave them where they are." and offers **Move them there** or **Leave them, use the new folder** (or Cancel). Nothing is moved silently.
  - Results: "Moved N cut lists to <folder>." / "Now keeping in <folder>. N cut lists stay in the old folder." / "Now keeping in <folder>."

## Keep: what is fetched, and background top-ups
(source: features/keep/plan.ts, features/keep/client.ts)

- **What a kept list holds**, in a folder `<episode>/<cut list>` of the device store:
  - each clip's audio as the server's file (`<clip>.ogg` or `<clip>.wav`) and its waveform (`<clip>.peaks`);
  - each clip's preview video (`<clip> Preview.mp4`, typically 80 to 350 MB each) unless video is turned off;
  - `Data/project.json`, `Data/sources.json`, `Data/episode.json`, `Data/episodes.json`;
  - `Data/Words/<clip>.json` (word timings for the lane);
  - `Transcripts/sources.json`, `Transcripts/<person>.json`, `Transcripts/<person> - <clip>.json` for the transcripts that use the list's clips;
  - `Analysis/…` (translations, alignments, language aids) filed by the page's offline layer;
  - a manifest with sizes, hashes and what each file is.
- Clips of the cut and of the shelf both count as used.
- File names: a clip's file name is its name without the media extension; when two clips would get the same name (compared ignoring case, as Windows and Android storage do), the colliding ones keep their whole name (for example "C0001.MP4.ogg") and further collisions get " (2)", " (3)".
- Sizes are exact for audio and video (asked by HEAD request) and for waveforms (computed from the clip's length); documents are estimated.
- Clips with no audio on the server, or whose audio is not Ogg Opus or WAV (for example AAC extracted from a news montage), are listed as having no audio offline; they still play online.
- Already-held audio, waveform and video files are skipped when their source hash (or video tag) and size are unchanged; a re-rendered clip is fetched again. Documents are always fetched again and rewritten only when their bytes changed.
- Fetching runs 3 files at a time; audio and documents first, the preview videos last (so a stop leaves a list that plays).
- An interrupted audio, waveform or video download resumes from where it stopped (HTTP Range), but only if the partial file belongs to the same source; otherwise it starts again. A body that arrives short or fails its check is retried once; the size is checked and a SHA-256 recorded.
- A server answering 503 is waited out up to 4 times (its Retry-After, else 0.6 s doubling, at most 5 s each).
- A document the server has none of (404) is not a failure for optional documents (episode lists, words, transcripts).
- After a complete run, files of clips the list no longer uses are deleted (the Analysis folder is kept). A list is "complete" when every required file is on the device.
- After the files, the translations of every card are asked for once (in batches of 2000 cards), so the offline layer files them.
- **Background top-ups**: 20 seconds after the page opens and then every 10 minutes, if the sync connection is live and the device is not set to "work offline" (`tc.offline.force = 1`), every kept list is brought up to date quietly (open list first), fetching only what changed. Not in a browser that can keep nothing. Errors are logged, not shown.
- **In the Windows and Android apps**, the open cut list is kept automatically by these top-ups even if never kept by hand; turned off by local storage `tc.offline.autoKeep = off`.
- Local storage settings: `tc.keep.video` (`off` = no preview videos), `tc.offline.autoKeep` (`off` = apps do not auto-keep the open list), `tc.offline.force` (`1` = working offline by choice; no top-ups).
- The panel's handle is also exposed to the page as `window.tcKeep` (open, keep, remove, topUp, list of kept keys, busy state, and test hooks to pick another store type and decode a window of kept audio). DEV ONLY: the test hooks.

## Looks: the View settings sheet (per-device view settings)
(source: features/looks/client.ts, features/looks/settings.ts, features/looks/styles.ts)

- Everything here is a setting of THIS device only, never of the cut list: stored as one JSON value in local storage under `tc.looks`. A value at all defaults is stored as nothing (the key is removed). An unreadable or out-of-range stored value falls back to the default for that field. Another tab of the same browser changing it is picked up live.
- If the browser refuses to save: announced "This browser would not save the setting: it applies until the page is closed."
- Opened by the toolbar button **View settings** (sliders icon, tooltip "View settings: card density, text size, preview sound, layout and panel widths on this device"). The sheet is titled "View" with "this device only"; a centred sheet up to 460 px wide and 86 percent of the height (up to 720 px) on larger screens, a bottom sheet on phones. Escape or the backdrop or **Close** (Esc) closes it; focus returns to whatever opened it. Tab cycles inside it. While open, keys pressed in it never reach the editor (Space presses the focused button, it does not start playback).
- The sheet also draws every other feature's row registered as a setting; a broken row shows "<label> is not available in this window." and the rest still work.
- **Reset all view settings** (footer, disabled when everything is default): back to all defaults, announced "View settings reset".
- Announcements go to a screen-reader live region.

### Cards: density (row 1)
- Five levels with a five-block meter: **Full** (default; "The whole card: the words, the English and the notes."), **Tight** ("Two lines of words, no English."), **Compact** ("One line of words under the speaker."), **Index** ("One line per cut: the speaker and the words."), **Strip** ("One line per cut, a bar as long as the cut.").
- Help line adds "The selected card always opens to full size." and "Ctrl + wheel" (desk) or "Pinch" (other shapes) "over the cards changes it too."
- The selected card is always drawn full; a card opened with W (expanded) shows in full at any density. Gap cards are thin rows at every non-full density.
- Strip: each card's bar length is its duration against the longest cut in the list (minimum 2 percent); the words stay readable to screen readers only.
- **Ctrl+wheel** (or Cmd+wheel) over the cards list: changes density by one level per 60 pixels of accumulated wheel movement (a mouse notch is always one level), wheel down denser; the page's own zoom is prevented. A trackpad pinch sends the same.
- **Two-finger pinch** over the cards (touch or pen): one level per 22 percent change of the finger distance; pinching in is denser, out is fuller; applies live while moving and is saved once at the end. The cards list takes over pinch so the browser does not zoom the page.
- After a density change: announced "<Name> cards" (Full adds ", the full card back"), and the selected card is scrolled to the centre.

### Follow, places and keys (row 2)
- **Follow the playhead** (toggle, tooltip "Keep the card being heard centred, playing or not (hold F)"): flips the views' follow switch; disabled when not available.
- **Record this place (N)** (Shift+P equivalent): records where you are (card, scroll, lane head). **Next recorded place (i/N)** (P equivalent): closes the sheet and jumps to the next, wrapping; disabled with none. When some exist: **Drop this place** (disabled when not at one) and **Clear all places**.
- **Select mode** / **Select mode: on**: toggles the shelf's select mode and closes the sheet; disabled if the shelf is not mounted.
- **All stacks**: always answers "This cut list has no stacks".
- **Keyboard shortcuts**: closes the sheet, then opens the shortcuts sheet (as pressing "?").
- Help: "Follow keeps the card being heard centred, playing or not." plus "Recorded places are not available in this window." / "Select mode is not available in this window." when missing. Missing pieces announce "Follow is not available in this window", "Recorded places are not available in this window", "Nothing is recorded yet: Record this place first", "Select mode is not available in this window".
- UNREACHABLE (possibly): the recorded places list is looked up at `window.tc.places`; whether anything provides it is outside this part (see "Could not determine").

### Card text size (row 3)
- **Small** (16 px card line, 14.5 px English), **Medium** (default, 18 / 16), **Large** (20 / 17.5), **Larger** (23 / 19.5). A chosen size also overrides the landscape phone's fixed card size.

### Lane (row 4, text only)
- Desk: "Drag the bar above the lane to make it taller or shorter, or press its arrow button to move the lane to the top or the bottom. Double-click the bar to reset its height." Other shapes: "On a phone the lane sits by the play bar; the Lane tab shows it larger, with the size of the words in the clips." (The lane's height and position are owned by the lane bar, not this feature.)

### Preview sound (row 5)
- **Same loudness** (default) / **Own level**: turns the player's automatic levelling on or off. Announced "Same loudness: every interviewee at the same level" / "Each clip at its own level". Also tells the views to draw lane waveforms without levelling when off.
- **Volume** slider from −12 to +12 dB in whole dB, with **Quieter by 1 dB** / **Louder by 1 dB** buttons (disabled at the ends) and the value in words ("+3 dB", "0 dB", "−3 dB"). Heard live while dragging, saved at release; announced "Preview volume <value>". **Volume back to 0 dB** appears when not 0.
- A status line says what it is doing: with levelling on, "Every interviewee is brought to the same speech level, the middle of what this episode’s own clips measure, so the loud ones come down and the quiet ones come up, with a limiter after it so nothing distorts."; off, "Each clip plays at its own level, with only its own gain."; plus " The whole preview is louder/quieter by N dB." and always " Only the preview: no file is touched." Without a player: "Playback is not available in this window, so there is nothing to level or turn up. The setting is kept for when it is." If the player cannot level: "This window’s player cannot level the clips, so each one plays at its own level." If it has no master volume, the volume is disabled and the line adds " The volume needs the player’s master control, which this build does not have yet."
- Only the preview changes; no cut, gain or file changes. If the player rejects the settings, one console warning.
- When the feature is unmounted, the player goes back to levelling on and 0 dB.

### Panels (row 6, desktop 1024 px wide or more only)
- "Drag the edge between the cards and a side panel to resize it (now: sections N px, inspector N px). Each panel keeps its width whatever else is open." **Reset panel widths** (disabled at defaults), announced "Panel widths reset".
- **Panel grips**: on desktop windows at least 1024 px wide and taller than 500 px, with a cut list open, a 12 px grip sits at the edge of the sections panel (rail) and of the inspector.
  - Rail: default 272 px, 200 to 440. Inspector: default 352 px, 280 to 560. The cards column is kept at least 420 px by shrinking the rail first, then the inspector.
  - Drag with the left mouse button (rail grows to the right, inspector to the left); saved at release. Escape during a drag cancels it.
  - Keyboard on a focused grip: Left/Right arrows 8 px (Shift: 32 px), Home = minimum, End = maximum, Enter or Space resets. Arrow keys on a grip do not move the playhead.
  - Double-click resets that panel; announced "Sections panel width reset" / "Inspector width reset".
  - Grip tooltip "Drag to resize the sections panel/inspector. Double-click resets."; screen readers hear "<N> px. Drag, or the arrow keys. Double-click resets."

### Layout on this device (row 7)
- **Auto** (default), **Phone**, **Desktop**. Help: "Auto follows the screen. Phone or Desktop pins this device to that layout (on a computer the window's width decides). Now: desktop / tablet / phone / phone, landscape."
- Works by rewriting the page's viewport: Desktop on a screen narrower than 1024 px lays out at 1280 px wide; Phone on a screen wider than 700 px lays out at 430 px wide; otherwise device width. Desktop browsers ignore this, so there the window width decides.
- Shapes: phone at 700 px wide or less; "phone, landscape" at 500 px tall or less; otherwise desk (desktop at 1024 px or wider, tablet below).

## The lane feature: keys, word timings and languages
(source: features/lane/keys.ts, features/lane/client.ts, features/lane/server.ts)

- The lane itself (the timeline strip) is drawn by the core views (another section). This feature adds its keys, its word timings and its language lines.
- **F8** (only when the dock lane is on screen; otherwise the key is left alone):
  - mouse over the dock lane: puts the head at the time under the mouse;
  - mouse elsewhere: puts the head at the start of the selected cut (the focused one if selected, else the last selected); with none: warning "No cut is selected: point at the lane, or select a cut first".
  - **held**: the head follows the mouse along the lane (one move per frame), playback pauses and the audio scrubs as it moves; on release, playback resumes if it was playing before the hold. Losing window focus ends the hold without resuming. Key repeat does not repeat the jump. The edit view's trim lane is not an F8 target.
- **F9** and **Shift+X**: switch the words shown in the lane's clips between English and the interview's original language (any language, not assumed Chinese); only when some lane is up. Key repeat does nothing more.
- These three keys are listed on the shortcuts sheet: "F8: The head to the mouse on the lane (the selected cut when the mouse is elsewhere); hold it and the head follows the mouse" and "F9, Shift+X: The words in the clips: the interview’s language, or English". Keys are ignored while typing in a text box or composing.
- **Lane lines**: each clip in the lane shows two lines from the language model: by default English first, and the original language as the second line; when English leads but there is no English yet, the original leads and the clip is marked as having no English. A machine translation is drawn dimmer.
- **Word timings**: for the open cut list, each clip's timed words are fetched from the server on demand (one request per clip; 45 second timeout); a 404 means "no words" and is final, any other failure is asked again later. A new cut list switches to its own words.
- **GET /api/lane/words?key=<cut list>&clip=<clip>**: returns `{clip, tokens: [[in seconds, out seconds, text], ...]}` in source seconds: the words service's own timings (from `<clip>_words.json`, else the vault's `.srt`), spelled as the clip's transcript spells them. At most 60,000 words. No access check of its own. Refusals: 400 `bad-key` for a bad cut list key; 400 `bad-request` "which clip?" when the clip name is empty, over 200 characters, contains a slash, a backslash, a control character or "..". A clip with no words answers an empty list. Errors from the transcripts service pass through with their status and code. Nothing is written. The transcripts cache lives under `TC_MEDIA_CACHE` (default `<system temp>/tc-editor-cache`)`/transcripts`.

## Audio: the preview playback engine
(source: audio/engine.ts, audio/plan.ts, audio/graph.ts, audio/levels.ts, audio/cache.ts, audio/http.ts, audio/stretch.ts, audio/types.ts, audio/index.ts)

What a person hears when they play the cut in the editor (the main timeline) and on the shelf's bench player.

### Playback behaviour
- Plays the cut in order; a **gap is played as silence** with the clock running through it (it does not stop at a gap). Cuts on the shelf are not played by the main engine.
- Every cut boundary gets a 4 millisecond fade (splice ramp) so joins never click; a start or seek in the middle of a cut ramps in over the same 4 ms.
- **Fades**: each cut's fade-in and fade-out are linear in gain, clamped to the cut; where they overlap (a short cut) they multiply. Changes to fades and to a cut's gain while dragging are heard live without a reload, gliding rather than jumping.
- **Gain per cut** = automatic level (when "Same loudness" is on) plus the cut's manual gain in dB, the sum clamped to plus or minus 30 dB.
- **Master volume**: from −24 to +12 dB (the View settings slider uses −12 to +12), glided over about 15 ms while playing so it never clicks; applied before the limiter.
- **Limiter** on the master: threshold −2 dBFS, no knee, ratio 20:1, attack 3 ms, release 250 ms. The browser's own automatic make-up gain of the limiter is measured once at start-up and taken back out, so levels below the threshold are unchanged (Chrome otherwise adds about +1.1 dB).
- **Start**: playing at the end of the cut starts over from 0. Before sound starts, the first 1.5 seconds of audio after the head (up to the next 4 cuts) is fetched, waiting at most 4 seconds before starting anyway. A pause while waiting cancels the play. On phones the audio device is resumed inside the gesture; the play never waits more than 1 second on that.
- **The head on screen** moves at once on play and eases into exact sync with what is heard (allowing for the output device's latency, for example Bluetooth) over 0.5 seconds, never jumping backwards.
- **While paused**, after the head has rested for 40 ms in a new spot, the audio under it is fetched in advance so the next play starts quickly.
- **Seek while playing**: continues from the new place without a gap longer than 2 seconds.
- **Editing while playing**: the sound continues from the same moment of the same clip; cuts that only slid along are not interrupted. While paused, an edit keeps the head on the same moment of the same cut (or the same gap), clamped inside it; if that cut is gone, it keeps its timeline time.
- **A clip with no audio** plays silent, with one warning "no audio for <clip>: it plays silent". A failed window of audio warns once "audio for <clip> at <s> s failed: <reason>". A clip whose levels cannot be read warns once "no levelling for <clip>: <reason>" and plays at 1x.
- A window of audio that arrives late starts as soon as it lands (10 ms ahead, ramped in) rather than holding the head still.
- Engine states: empty, loading, ready, playing, paused, error. A first load with no source list available is an error ("the project has no audio sources"); playing with nothing loaded refuses ("no project loaded").
- **Playback rate** from 0.25x to 4x with pitch kept (time-stretched speech, best between 1.25x and 3x, 0.5x acceptable). A rate change while playing keeps the old rate sounding until the new rate's first audio is ready (at most 4 seconds), then switches, so 2x never starts with a hole. Stretching runs off the main thread; if that is impossible it runs on the main thread in small steps.
- **Scrub audio**: while the head (or an F8 hold) or a trim edge is dragged and playback is paused, short 70 ms grains of the clip under it are played at normal pitch, at most one every 22 ms (8 ms rise, 12 ms fall), at that cut's level and fade; holding still is silent. A gap is silent. A dragged trim edge is heard at the clip's level without fades.
- **Keep the sound device awake** (the editor's engine): while the page is visible, an inaudible constant signal (−130 dBFS) is sent so the browser does not put the output to sleep, and the audio device is started on the first click or key anywhere, so the first Play is not delayed. Stopped while the page is hidden.
- **Automatic levelling ("Same loudness")**, on by default:
  - Each clip's speech level is measured from its waveform file (`.peaks`): a gated mean square (quieter parts more than 10 dB under the average are ignored), so a door slam does not set the level.
  - The target is the **median** of the speech levels of the clips used in the cut (shelf clips and clips of other cut lists never count). Loud clips come down, quiet ones come up.
  - Each cut is levelled by the speech in a 2-minute window either side of its middle (quantised to 5 s), never more than 18 dB from the clip's whole level; a clip with under 20 seconds of waveform uses its whole level.
  - The automatic gain is between 0.05x and 8x.
  - Other players (the transcript) can ask the same level for any clip and moment so they sound like the lane; a clip not in the cut has its waveform fetched once for that and never moves the target.
  - Waveform files: "PK" header, a rate byte (200 per second today; 0 means an old 50 per second file), a pad byte, then one byte per bin.
- **Audio fetching**: decoded mono audio arrives from the media service in 5-second windows on a fixed grid (each with 40 ms of overlap), at the device's own sample rate when the service offers it, else 48 kHz. Kept in a memory cache capped at 64 MB for the main engine (about 5.5 minutes) and 16 MB for the bench, least-recently-used dropped first; at most 3 fetches at once, the soonest-needed first. Audio is scheduled 2 seconds ahead and fetched 8 seconds beyond that; a scheduler runs every 50 ms. A failed window waits 0.5 s before it is asked again, doubling up to 15 s. Windows no longer needed after a seek are dropped from the queue.
- **Media service calls** (same origin): `GET /media/sources?project=<key>`, `GET /media/pcm?project=&clip=&from=&to=&rate=` (raw little-endian 32-bit float samples; long requests split at the service's window cap), `GET /media/peaks?project=&clip=`. A `503` answer is waited out up to 4 times (its Retry-After, else 250 ms doubling, at most 3 s each) before it counts as a failure.

## Export adapters: EDL, FCPXML, OTIO and the command line
(source: adapters/*.ts)


These turn a cut list into files another tool imports (DaVinci Resolve, Final Cut Pro, Premiere). The same three exporters are used by the Resolve feature's export route (another section) and by a command-line tool here.

### What every export shares (the frame plan)
- Only the cut is exported; the shelf, saved sequences and alternates are not.
- **Frame rate**: the requested rate, else the cut list's `fps`. A rate within 0.01 of 23.976, 29.97, 47.952 or 59.94 is treated as the exact NTSC fraction (24000/1001 and so on); any other is read as the nearest fraction with denominator at most 1001.
- **Seconds to frames** is done once, in exact arithmetic, rounding to the nearest frame with ties to even by default (an option rounds ties up, matching the old Python conform frame for frame). All three formats therefore agree on every frame.
- **Drop-frame timecode** only at 29.97 and 59.94; a cut list marked drop-frame at another rate is written non-drop, with a note.
- **Timeline start**: the cut list's `tl_start` timecode; unreadable means 00:00:00:00, with a note.
- **Source side**: each cut's in and out in frames at the clip's own rate (from the cut list's clip facts; unreadable rate falls back to the timeline rate with a note); source timecode counts from the clip's start timecode (unreadable: from 00:00:00:00, with a note). Source drop-frame is used when the rate allows and the timeline is drop-frame or the clip's start timecode uses ";".
- A cut shorter than one frame at the clip rate is exported as one frame, with a note.
- **Record side**: cuts laid end to end after the black in front of them, so nothing drifts. A clip at another rate than the timeline has its record duration rescaled (may differ by a frame), with a note per clip.
- **Gaps**: every gap item is exported as black at its own length, including gaps after the last cut. Consecutive gaps are rounded as one run and split at their cumulative edges, so totals match the conform.
- **Fades** in timeline frames, never longer than the cut.
- **Markers**: section headings (default Blue), note headings (default Green; a heading's own colour wins) and note rows (Cream) become markers on whatever follows them.
- Sub-frame edges (in, out, fade, gap lengths more than 0.001 frame off the grid) are reported as "falls between frames: rounded to the nearest frame (<rule>)".
- Every export ends with the note "automatic levelling is the editor's playback only: exported audio plays at source level plus each cut's manual gain where the format carries it" when it has any cut.
- Each export returns a list of "not carried" sentences naming what the format lost; nothing is lost silently. Cuts are named as "cut N (<person or clip>)".
- File names come from the timeline name (default the cut list's title, else its project name, else "Timeline Cards") with Windows-reserved characters replaced by "_" and trailing dots and spaces removed ("timeline" if empty). Exports are deterministic: the same input gives the same bytes.
- Media paths, when supplied, are written as file URLs (Windows drive paths, UNC paths and POSIX paths converted).

### OpenTimelineIO (.otio)
- Label "OpenTimelineIO (.otio)". OTIO 0.15 schema, one audio track "A1", global start = timeline start.
- Each cut is a clip with its source range at the clip's rate starting at its source timecode; media as an external reference (file URL) or, without a path, a missing reference ("no media path for <clips>: written as MissingReference (relink in the target tool)").
- Each gap is a Gap. Markers sit at the start of the black before the cut they precede; Resolve marker colours are mapped to OTIO's set (Fuchsia to MAGENTA, Rose to PINK, Lavender to PURPLE, Sky to CYAN, Mint to GREEN, Lemon to YELLOW, Sand and Cocoa to ORANGE, Cream to WHITE, unknown to BLUE), the exact colour kept in metadata.
- Gain, fades, clip colour, note and block reference are kept only in each clip's `metadata.timeline_cards`; reported as not carried ("gain … and fades … not carried by OTIO (kept in metadata.timeline_cards only)", "… OTIO 0.15 has no clip colour …").
- Mixed rates: "N cut(s) from clips at another rate than the timeline: OTIO lays each at its source duration, so on this mixed-rate timeline later cuts may sit up to a frame off the timeline grid".

### Final Cut Pro XML (.fcpxml)
- Label "Final Cut Pro XML 1.10 (.fcpxml)". FCPXML 1.10, one library, event and project named after the timeline; a 1920x1080 format named for standard rates (23.98, 24, 25, 29.97, 30, 50, 59.94, 60) or a custom frame duration; stereo, 48 kHz sequence; audio only.
- One asset per clip (duration the longer of the furthest out point used and the media's own length; channels and sample rate from the media service when known, else 2 and 48000); without a media path, an offline placeholder URL and the note "no media path for <clips>: written as offline media (relink in the target tool)".
- Each gap is a `<gap>`; each cut an asset-clip named "<person>: <clip>" with dialogue role.
- Carries: per-cut gain (`adjust-volume`, e.g. "+3.0dB"), fades (ease in / ease out, in frames), the cut's note, and markers (on the first gap in front of the clip, else on the clip). Times are exact rationals on frame boundaries.
- Not carried: clip colour ("N cut(s) carry a clip colour: FCPXML has no clip colour"); markers after the last cut when there is no gap to hang them on.
- Text is XML-escaped; characters XML cannot hold are removed.

### CMX3600 EDL (.edl)
- Label "CMX3600 EDL (.edl)". UTF-8, CRLF line ends. "TITLE:" (first 70 characters, never splitting an emoji) and "FCM: DROP FRAME / NON-DROP FRAME".
- One event per cut on track AA, reel "AX", straight cut, with "* FROM CLIP NAME: <clip>" and, if any, "* COMMENT: <note>" (line breaks shown as " / ").
- Each gap is a "BL" (black) event at its own length (source 00:00:00:00 to its length).
- Markers as Resolve marker comments ` |C:ResolveColor<colour> |M:<title> |D:1` on the following event ("|" in titles turned to "/"; empty titles "(note)" / "(marker)").
- Not carried: gain and fades (named per cut), clip colour, markers after the last cut. More than 999 events: "CMX3600 numbers events to 999; later events are numbered past it, which Resolve and Premiere read but strict CMX readers may not".

### Command line: export a .cut.md file
- `npx tsx adapters/cli.ts <file.cut.md> [--out <dir>] [--fps <rate>] [--format otio,fcpxml,edl]` (run by an operator; not reachable from the page).
- Default output folder: beside the input, `<name>.export`; created if missing. Default formats: all three.
- Each file is written to a temporary name (`.tmp-<process id>`) and renamed, so a half-written file never has the real name.
- Prints "warning: …" for parse warnings and problems ("line N: …"), "wrote <path>" per file, and "not carried: <format label>: <sentence>" per loss.
- Refusals (exit code 1, message printed): no input ("usage: tsx adapters/cli.ts <file.cut.md> [--out <dir>] [--fps <rate>] [--format otio,fcpxml,edl]"), "<option> needs a value", "--fps must be a positive number", "unknown option <x>", "unexpected argument <x>", "unknown format <x> (have otio, fcpxml, edl)".
- Media paths cannot be passed from the command line, so command-line exports always have offline or missing media references.
- An importer contract (another tool's timeline turned into edits) and a "wav" export id are declared but no importer or audio exporter exists in this folder. DORMANT.

## The Windows and Android apps: what they share
(source: apps/app.config.json, apps/shell/app.html, apps/shell/offline.html, apps/windows/src/proxy.js, apps/android/.../LocalServer.java)

- Both apps ("Timeline Cards" on Windows and on Android) show the Timeline Cards page from a server (by default the CC Sync dashboard's `/cards/`) inside the app, through a **local server inside the app** at `http://127.0.0.1:47823`. Everything the page stores offline belongs to that local address, which the app owns, so changing the server address never strands what was downloaded, and the browser does not evict it.
- **Build-time defaults** (`apps/app.config.json`, shared by both apps): first-run server `https://truenas.tail26290e.ts.net:9443/cards/` (only the first-run default; changed on the device in the settings page), local port 47823 (fixed: part of the page's origin), version 1.0.6.
- **Forwarding**: every request is passed to the server unchanged (same path, query and body), except: Host, Origin and Referer are rewritten to the server's; redirects (Location) back to the server are rewritten to the local address; cookies coming down lose Domain, Secure and Partitioned, and SameSite=None becomes Lax (so sign-in cookies work on the local http address); HSTS and Alt-Svc headers are dropped. A request to `/` goes to the server's start page (for the dashboard, `/cards/`, not the dashboard home). With no server set, everything redirects to the settings page `/__app/`.
- **WebSocket upgrades are refused** with 501 by both local servers.
- **Server reachability**: measured by one HEAD request to the start page; any HTTP answer counts as up. Connect plus TLS limited to 4 seconds. While down, re-measured every 5 seconds. A "down" verdict younger than 4 seconds makes non-media requests fail immediately (the socket is closed, so the page sees a plain network error and its own offline mode takes over) instead of waiting for the operating system's ~21 second timeout. Audio, video and `/api/peaks` requests are always really attempted. "Last answer" time is saved at most once a minute.
- **Saved pages**: every page (HTML navigation) and static asset (js, css, svg, png, ico, webmanifest, fonts, jpg, webp, gif) that passes through is saved in the app's data folder (never API answers, media, `/agent/` routes or the login/logout pages; at most 32 MB each). Saved copies are always the current bytes (the browser's cache validators are dropped for them). While the server is unreachable, a saved page is served with status 503 and two meta tags marking it as an offline copy (so a service worker takes its own offline path; with none, the saved page shows); a saved asset is served normally. A page never saved shows the app's offline page (below); an asset never saved is refused.
- **Media files in the projects folder** (the older page's offline download): an audio or video request carrying the page's keep header is written as it passes into `<projects folder>/<episode>/<cut list>/Audio|Video/<clip name>.<ext>` (extension from the content type: ogg, opus, m4a, aac, wav, mp3, webm, mp4, else bin), through a `.partial` file renamed only when complete. From then on, a request for that clip is answered from the file (with Range support) before the network, online or offline. Index file `.timeline-cards-index.json` (Windows) / `.timeline-cards-index.tsv` (Android) in the projects folder.
- **"Keep on this device" file routes** (`/__app/api/keep/...`), used by the editor's "On this device" panel (see Keep above) to store real files: listed under "Keep file routes" below.
- **Working offline by choice**: a switch that makes the app answer everything as if the server were unreachable, even when it is up; saved in the app's config, so it survives restarts; no reachability checks are made while on.
- **In-app updates**: see each app.

### The app's settings page (`/__app/`, also the App menu / Back menu "App settings and status")
- Works with no network at all; never forwarded to the server. Refreshes its status every 5 seconds.
- Heading "TIMELINE CARDS" and a subline "opens <start page>" or "set the server address to begin".
- **SERVER**: field "Address of the Timeline Cards page" (Enter saves) with help text; **Save and open** and **Check connection**.
  - Address rules: http or https only ("the address must be http or https"); a bare host gets https://; no user name or password ("put no user name or password in the address"); a trailing "/" is added; a query string (for example a key) is kept. Errors: "the server address is empty", "that is not an address: <text>".
  - Save: "checking <address> ..." then "saved, the server answers" (and opens the page after 0.4 s) or "saved. The server did not answer, so the app will work offline". Saving keeps everything downloaded.
  - Check: "the server answers" / "the server did not answer". If the app does not respond: "the app did not answer".
- **WORK OFFLINE**: "Use what is on this device even with the server up, as on a plane. Nothing goes to the server; edits wait here until you switch back." Button **Work offline** / **Go back online**. Also sets the page's own local-storage flag `cards_force_offline` so the next cut list opened starts offline. Messages: "working offline: the app will not contact the server", "back online: the server answers", "back online, but the server did not answer".
- **STATUS**: server chip ("OFFLINE BY CHOICE", "reachable", "UNREACHABLE: working offline", "not measured"), last answer ("N s/min/h ago" or a date, "never"), saved pages (count and size), projects folder, app platform and version. Help: offline the app opens the episode list and every downloaded cut list; edits wait and are sent when the server is back.
- **KEEP ON THIS DEVICE**: explains that every cut list opened with the server up is kept automatically (audio, waveform, transcripts, translations, language aids; only what changed is fetched every ten minutes). Toggle button **On: turn off** / **Off: turn on**, which sets both `cards_auto_keep` and `tc.offline.autoKeep` to `off` in local storage (or removes them). Messages "cut lists you open are kept on this device" / "cut lists are kept only when you press Keep on this device".
- **PROJECT FOLDER**: the folder and "N cut lists (size), <free> free"; **Open folder**; "Move it to (the whole path)" field (placeholder `D:\Timeline Cards`, Enter submits) and **Use this folder**. If cut lists are kept in the current folder, it asks: "N cut lists are kept in the current folder: move them along, or leave them where they are." with **Move them there** / **Leave them, use the new folder**. Results "moved N to <folder>", "now keeping in <folder>; N left in the old folder", "now keeping in <folder>"; empty field "type the whole path of the new folder".
- **UPDATES**: "New versions of this app are published on the server. Checking needs the server, and you signed in." **Check for update** then: "this is the newest version (<v>)" or "version <v> is available (this is <current>)" with **Install <v>**; installing: Windows "installing <v>: the app closes and opens again by itself", Android "installing <v>: confirm on the screen Android shows". Errors: "set the server first", "you are working offline: go back online to check for an update", "this server has no app builds published" (404), "sign in first" (401 or 303), "the server answered <code>", "latest.json is not JSON", "latest.json names no file", "this build cannot install updates", "the download did not match its checksum: try again", "the server stopped answering" (30 s timeout).
- **Open Timeline Cards** (disabled until a server is set).

### The offline page
- Shown (status 503) when the server is unreachable and the requested page was never saved: "THE SERVER CANNOT BE REACHED", "This page has not been saved on this device yet, so it cannot open offline. A page is saved the first time it opens with a connection.", a link **Open the episode list** (opens offline once seen online, listing every downloaded cut list), and **App settings and status**.

### App routes (local only, never forwarded)
- `GET /__app/` (also `/__app`, `/__app/index.html`): the settings page.
- `GET /__app/api/status`: server, start page, origin, local address, up (true/false/null), last checked, last seen, saved page count and bytes, version, platform, working-offline flag, projects folder, keep root.
- `POST /__app/api/check`: re-measures the server now and answers the status.
- `POST /__app/api/config {server}`: sets the server (refusal sentences above, returned in the status as `error`), saves it, resets reachability and measures again. Body over 64 KB or not JSON: 400 "not JSON" (Windows).
- `POST /__app/api/offline {on}`: working offline by choice on or off; going back online re-measures at once.
- `POST /__app/api/update {install}`: checks `<start page>app/latest.json` on the server with the editor's own sign-in cookie, compares this platform's entry by dotted version numbers, and with `install: true` and a newer version downloads `<start page>app/<file>` into the app's `updates` folder and installs it (file name must match a safe pattern ending `.exe` or `.apk`).
- Any other `/__app/` path: 404 "no such app route".
- These app routes check neither the Host nor the Origin header (only the keep routes do).

### Keep file routes (`/__app/api/keep/...`)
- Refused 403 "not the app" unless the Host header is `127.0.0.1:<port>` or `localhost:<port>`; refused 403 "another site may not use the app" when an Origin header is present and is not the app's own.
- Files live in `<keep root>/<episode>/<cut list>/` (episode and cut list from the key `<…>/<Episode>/Script Docs/Cuts/<name>.cut.md`; other keys go under `Other/`), names made safe for Windows (reserved characters replaced, reserved device names prefixed "_", at most 120 characters); a second list with the same folder name gets " (2)" and so on. Index `.timeline-cards-keep.json` in the root; each list has a `manifest.json` with every file's size, SHA-256 and time, plus the editor's metadata.
- Keep root default: Windows `Documents\Timeline Cards` (overridable by `CARDS_APP_PROJECTS`), Android the app's external files folder `Android/data/com.cablewrap.timelinecards/files/Timeline Cards` (visible to a computer over USB, no permission needed); a changed root is saved in the app's config (`config.json` key `keep_root` on Windows, `keep.json` on Android).
- `GET /__app/api/keep`: root, platform, total bytes, free disk space, and each kept list (key, folder, bytes, file count, updated, metadata).
- `POST /__app/api/keep/root {path, mode?}`: changes the root. Refusals: 400 "which folder?", 400 "give the whole path of the folder" (Windows adds "(C:\Users\...)"), 400 "the new folder cannot be inside the old one, or the old one inside it", 400 "that folder cannot be written[: <code>]", 409 `kept` "cut lists are kept in the current folder" with the list keys when lists exist and no mode was given. Mode `move` moves each list folder (rename, or copy then delete across drives), renaming on clashes, and removes episode folders left empty; mode `leave` leaves them. Same folder: nothing happens.
- `POST /__app/api/keep/open {list?}`: opens the list's folder (or the root) in the file manager; 404 "that cut list is not kept here". On Android nothing is opened (see below).
- With `?list=<key>` (400 "which cut list? (list=)" if missing, over 1024 characters or with control characters):
  - `GET …/manifest`: the list's manifest, or 404 "not kept here".
  - `POST …/meta`: stores the editor's metadata in the manifest (must be a JSON object, up to 8 MB on Windows).
  - `DELETE …/list`: deletes the list's folder and index entry, answers `{freed}`; 400 if the folder is not under the root.
  - With `&path=<relative path>` (at most 4 segments, 600 characters, each segment safe, never `.partial`, `manifest.json` or `.timeline-cards*`; 400 "not a path the store keeps: …"):
    - `GET …/partial`: bytes already written to the unfinished file.
    - `PUT …/append?offset=N`: appends a piece (at most 16 MB, Content-Length required on Windows) to `<path>.partial`; 409 "the partial holds N bytes" when the offset does not match; 400 "offset= is a byte count"; 413 when too big; 400 "the piece was cut short".
    - `POST …/commit?size=N&sha256=…`: checks the partial's size (422 `integrity` "<path>: N bytes arrived, M were expected") and, when given, its SHA-256 (422 `integrity` "the bytes on disk are not the bytes that were sent"), then renames it into place and records it; 404 "nothing was written for <path>".
    - `POST …/discard`: deletes the partial.
    - `GET|HEAD …/file`: serves a kept file with Range support (`.mp4` as video/mp4); 404 "not kept here" / "the file went away".
    - `DELETE …/file`: deletes a file, answers `{freed}`.
- A full disk answers 507 `full` ("the disk is full" / "the storage is full"). Anything else: 500 with the reason. Any other keep path: 404 "no such keep route". Requests that change an index or manifest are handled one at a time.

## The Windows app (Timeline Cards for Windows)
(source: apps/windows/src/main.js, apps/windows/src/proxy.js, apps/windows/src/keep.js, apps/windows/package.json)

- An Electron desktop app, product "Timeline Cards", app id `com.cablewrap.timelinecards`, version 1.0.6, author "Cablewrap Creative". Built as a one-click per-user NSIS installer (`Timeline-Cards-Setup-<version>.exe`) and a portable exe (`Timeline-Cards-<version>-portable.exe`), x64, with `npm run dist`; `npm start` runs it from source. Bundles the settings and offline pages and `app.config.json`.
- **One instance only**: a second launch focuses (and restores) the existing window.
- **Startup**: starts the local server on 127.0.0.1:47823 and measures the server; if the port is taken, an error box "The app could not open its local address http://127.0.0.1:47823 (<code>). Something else on this computer is using port 47823. Close it and start the app again." and the app quits.
- **Window**: dark background, menu bar hidden until Alt, title "Timeline Cards", opens at the server's start page (or the settings page with no server). Size, position and maximised state are remembered (`window.json` in the app data folder; default 1400 x 900). Background throttling is off, spellcheck off, the page is sandboxed with no Node access.
- **Links**: pop-out windows the page opens on the local address (for example the lane in its own window) become more app windows; any other http/https link opens in the default browser; navigation away from the local address is blocked and opened in the browser instead.
- **A failed page load** (other than an aborted one) is logged and the window goes to the settings page.
- After each page load the app asks for persistent storage; a refusal is logged.
- **Permissions**: every browser permission (full screen, clipboard, notifications, persistent storage, and so on) is granted automatically to the local address and refused to anything else.
- **Downloads** (the page's rescue copy, exports) save straight into the Windows Downloads folder under their own name, no save dialog; logged.
- **Menu**:
  - App: **Episodes (home)** (Alt+Home), **App settings and status** (Ctrl+,), **Open the project folder** (creates it if needed), **Open the app data folder**, **Quit**.
  - Edit: the standard edit menu (undo, cut, copy, paste, select all).
  - View: **Reload** (F5, also Ctrl+R), **Force reload**, **Reset zoom**, **Zoom in**, **Zoom out**, **Toggle full screen** (F11), **Toggle developer tools** (Ctrl+Shift+I).
  - Go: **Back** (Alt+Left), **Forward** (Alt+Right).
- **Quitting** (any way): the saved-pages index is written and the port released first (bounded to 1 second). Closing the last window quits.
- **Update install**: after the settings page's Install, the checked installer is run silently (`/S --force-run`), detached, and the app quits; the new version starts itself. **No checksum, no install**: an update entry without a 64-character SHA-256 is refused ("this update carries no checksum, so it was not installed: publish it again with apps/publish.ps1"); a mismatch deletes the download. The checksum sits beside the file on the server; it is not a signature.
- **Files**: app data folder (Electron user data) holds `app/config.json` (server, last seen, working offline, keep root), `app/saved/` (saved pages and `index.json`, written within 300 ms of a change and on quit), `app/updates/`, `window.json`, and `app.log` (rotated to `app.log.1` above 2 MB). Projects folder `Documents\Timeline Cards`.
- **Environment variables** (test hooks, DEV ONLY): `CARDS_APP_PORT` (local port), `CARDS_APP_USERDATA` (profile folder), `CARDS_APP_DOWNLOADS` (download folder), `CARDS_APP_SERVER` (first-run server), `CARDS_APP_PROJECTS` (projects folder).
- **Upstream connections** reuse up to 16 keep-alive sockets per protocol, idle sockets dropped after 4 seconds. A request on a reused socket the server had closed is retried once on a new socket. Request bodies up to 8 MB are buffered so they can be retried. Saved pages are decompressed (gzip, deflate, brotli) before saving.

## The Android app (Timeline Cards for Android)
(source: apps/android/app/src/main/java/com/cablewrap/timelinecards/MainActivity.java, LocalServer.java, KeepStore.java, AndroidManifest.xml, app/build.gradle, res/)

- Package `com.cablewrap.timelinecards`, label "Timeline Cards", Android 10 (API 29) or newer, target API 36, version name from `app.config.json`, version code computed from it (1.0.6 = 10006). No AndroidX. The settings and offline pages are the same files as the Windows app.
- **Permissions asked for**: internet, vibrate, and "install packages" (for in-app updates). No storage permission (kept files go in the app's own external folder; downloads go through the system Downloads collection).
- **Network security**: plain http is allowed only to 127.0.0.1 and localhost; the WebView only ever loads the local server, which itself may reach an http server.
- **No backup**: Android app backup is disabled.
- **Window**: full screen always (status and navigation bars hidden; a swipe shows them briefly), dark background and system bar colours, content allowed into the display cutout, **portrait** by default. One activity, single task. The system text size is ignored (the page has its own scale). Keyboard resizes the page.
- **Startup**: starts the local server once per process (it survives the activity being recreated). If port 47823 is taken: a page "Timeline Cards could not start: Its local address 127.0.0.1:47823 is in use by another app. Close it and open Timeline Cards again."
- **The WebView**: JavaScript, DOM storage and databases on; media may play without a tap; no file or content URL access; no multiple windows. Remote debugging is always on (chrome://inspect over USB). Page errors are written to the Android log.
- **Links**: anything not on the local address opens in another app (the browser).
- **A failed main-frame load** (not the settings page) goes to the settings page.
- **Back gesture / button**: goes back in the page's history; at the start, a menu "Timeline Cards" with **App settings and status**, **Episodes (home)**, **Leave the app** (sends the app to the background). Works on Android 13+ gestures as well.
- **Page hooks** injected on every page: remembers download file names; asks for persistent storage; full-screen requests always succeed (the app is already full screen); an orientation lock request "landscape..." turns the app to sensor landscape (either way up), anything else or unlock returns to portrait.
- **Downloads**: a download the page starts (including blob: and data: links) is read by the page and handed to the app, which writes it to **Downloads/Timeline Cards/<name>**, replacing a file of the same name (so the rescue copy stays one file). Toasts "Saved to Downloads/Timeline Cards/<name>" or "Could not save <name>: <reason>". Invalid file-name characters become "_"; no name gives "Timeline Cards download".
- **File picker**: the page's file inputs open the system chooser ("Choose a file"), any file type.
- **Music ducking**: when the page says it is playing, the app takes a transient "may duck" audio focus, so other apps' music (for example Spotify) gets quieter instead of stopping; released when the page goes quiet and when the app is paused.
- **Update install**: Install on the settings page downloads the APK (checked against `sha256` only if latest.json has one; a mismatch deletes it), then: if the app may not install apps yet, toast "Allow Timeline Cards to install apps, then press INSTALL again" and opens the system "Install unknown apps" setting for it; otherwise starts a system install session (toast "Installing Timeline Cards <version>"), Android shows its confirmation, and failures toast "The update was not installed: <reason>" or "Could not install the update: <reason>". The same signing key lets the update replace the app in place, keeping offline data.
- **Projects folder / keep root**: the app's external files folder `Timeline Cards`; changeable on the settings page (saved in `keep.json`). **Open folder** answers success with the path but opens nothing on Android (no file manager is wired). UNREACHABLE: opening the folder on Android.
- **Upstream connections**: one new connection per request (always "Connection: close"); DNS answers cached for 60 seconds and reused when DNS fails; one 4-second budget across all of a host's addresses; the server certificate's host name is verified. Request heads up to 64 KB; request bodies up to 8 MB (413 "too large" above); long responses may run up to 15 minutes; browser sockets time out after 30 seconds idle. Saved pages are decompressed from gzip or deflate (the app asks only for gzip).
- **Files**: app files `app/config.json` (server, last seen, working offline), `app/saved/` (pages and `index.tsv`), `app/updates/`, `app/keep.json`.

## Building, publishing and testing the apps (operator tools)
(source: apps/publish.ps1, apps/android/build_apk.ps1, apps/android/app/build.gradle, apps/android/build.gradle, apps/android/settings.gradle, apps/android/gradle.properties, apps/android/gradle/wrapper/gradle-wrapper.properties, apps/android/local.properties, apps/android/gradlew, apps/android/gradlew.bat, apps/make_icons.py, apps/e2e_offline.py, apps/android/e2e_device.py, apps/android/test_desktop.sh, apps/android/desktop/DesktopMain.java)

- **Android build**: `powershell -ExecutionPolicy Bypass -File apps\android\build_apk.ps1`.
  - Uses `JAVA_HOME` (else the tree's `Utilities\_tools\jdk17`) and `ANDROID_HOME` (else `Utilities\_tools\android-sdk`); writes `local.properties` with the SDK path.
  - Signing key kept outside the repo in `%USERPROFILE%\.timeline-cards-release\android.keystore` (alias `timelinecards`), its password DPAPI-protected in `android.keystore.pw.dpapi` (only that Windows user can read it). The first run creates a 4096-bit RSA key valid 100 years (`CN=Timeline Cards, O=Cablewrap Creative`) and prints "NEW SIGNING KEY made at … -- back up …; every later APK must be signed with it."
  - Runs `gradlew assembleRelease` (Gradle 8.11.1, Android Gradle Plugin 8.9.1, Java 17, 2 GB Gradle heap, no minify, lint never fails the build) with the key in environment variables (`CARDS_ANDROID_KEYSTORE`, `CARDS_ANDROID_KEYSTORE_PASSWORD`, `CARDS_ANDROID_KEY_ALIAS`, `CARDS_ANDROID_KEY_PASSWORD`; the password variable is removed afterwards). Without a keystore variable, Gradle signs with the debug key.
  - Copies the result to `apps\dist\Timeline-Cards-<version>.apk` and prints its certificate's SHA-256. Errors: "keytool could not make the signing key", "the Gradle build failed".
- **Windows build**: `npm run dist` in `apps\windows` (installer and portable exe in `apps\windows\dist`).
- **Publish**: `powershell -ExecutionPolicy Bypass -File apps\publish.ps1 [-Dest "X:\Apps\Timeline Cards"]` (default destination `X:\Apps\Timeline Cards`, the vault folder the dashboard serves at `/cards/app/`).
  - Refuses when `apps\windows\package.json`'s version differs from `app.config.json` ("…make them agree and rebuild").
  - Copies this version's APK and Windows installer if built ("no <platform> build of <v> (<path>): <platform> left as it was" otherwise) and updates `latest.json` with, per platform, version, file, bytes, SHA-256 and publish time. A platform with no new build keeps its old entry. Old builds stay in the folder (rolling back is publishing an older version). Nothing built at all: "nothing to publish for <v>: build first".
- **Icons**: `python apps/make_icons.py` (needs Pillow) draws the app icon (dark rounded square with rows and a red playhead) into `apps/windows/build/icon.png` (512 px) and the Android launcher icons, square and round, at 48/72/96/144/192 px.
- **Tests** (DEV ONLY, never touch a real vault):
  - `python apps/e2e_offline.py --project <copy>.cut.md --root <copy episode> [--impl node|java] [--shots DIR]` (ports 8812 and 47960 by default): starts a real old-page Timeline Cards server on a copy and the app's local server (Windows or the Java one), then in headless Chromium checks: the cut list opens; the offline download works and the app saved the page; with the server killed, a cold start opens the copy within 15 seconds with the OFFLINE chip; an offline edit is queued; with every service worker and cache deleted the app's saved page still opens it and the queued edit survives; with the server back the edit reaches the file. Exit 1 on any failure.
  - `python apps/android/e2e_device.py --project … --root … [--apk …] [--serial …] [--host 10.0.2.2] [--cards-port 8814] [--shots DIR]`: installs the APK on a device or emulator over adb and drives the app's WebView: settings take the server, the cut list opens, a service worker is active on 127.0.0.1, the offline download works, a clip answers a Range request, a download lands in Downloads/Timeline Cards, a force-stopped cold start with the server gone opens the copy saying OFFLINE, an offline edit is replayed. Default APK path names version 1.0.0.
  - `bash apps/android/test_desktop.sh`: compiles the Android local server and keep store with a desktop JDK and runs the Windows app's proxy and keep test suites against it (`DesktopMain`, flags `--data --shell --port --server --connect --recheck --failfast --projects`; its installer is a stub writing `installed.txt`).

## Timeline Cards Editor: Windows test app (the new editor, standalone)
(source: apps/windows-editor/src/main.js, apps/windows-editor/package.json, apps/windows-editor/app.config.json, apps/windows-editor/scripts/stage.mjs, apps/windows-editor/perf/lane-perf.mjs, apps/windows-editor/.gitignore)

- A separate Electron app, "Timeline Cards Editor", app id `com.cablewrap.timelinecards.editor`, version 0.1.5, marked TEST BUILD and never published. It runs the editor's own server on a vault folder on this computer (no CC Sync dashboard, no sign-in) and shows it. Port 47930 (fixed, part of the page's origin); defaults in its own `app.config.json` (first-run vault suggestion `X:\Vault\2026\FF5`).
- **One instance only**. A second launch re-opens the editor window (in the browser app window or the app window).
- **First start**: asks for the vault folder (dialog "Timeline Cards Editor: choose the vault folder (it holds the episodes)"); cancelling quits. A vault folder that no longer exists asks again.
- **Read-only by default**: the server edits a working copy of the vault's cut lists kept in the app's profile (`work`), reading audio, transcripts and waveforms from the vault. Pages and the title say "READ-ONLY: working copy" / "read-only copy"; the editor's header gets a small "READ-ONLY COPY" tag under the logo.
- **Write mode** (App > **Edit the vault's own files (write mode)**): after a warning dialog ("Edit the vault's own files?": "From now on your edits are written into the vault's .cut.md files." with notes that the website's /cards writes the same files and must not have the same cut list open, that the old app drops the notes this editor writes, that history is kept in a `.tcards` folder beside each cut list, and that edits made in the read-only copy are not carried over), the server restarts with `--write`. The header tag reads "WRITING TO VAULT" in red with a red top line; the title "WRITING TO THE VAULT". Turning it off restarts read-only.
- **Starting the server**: shows "Starting the editor…" (with the mode and vault, and "The first start reads every cut list in the vault, which can take a minute on the NAS."), checks the port is free (else "Port 47930 is already in use." with "Another copy of the editor server (an npm start, or this app) is running on it. Close it and use App > Restart server."), starts the editor server with Electron's built-in Node, and waits up to 2 minutes for `/api/projects` to answer (else "The editor server did not answer within 2 minutes."). If the server exits: "The editor server stopped (exit <code>)." with its last 4000 characters of error output. Error pages say "App > Restart server tries again; App > Open the server log has the whole story."
- **Server environment it sets**: `TC_VAULT` (the vault), `TC_PORT`, `TC_HOST=127.0.0.1`, `TC_STATIC` (the built client), `TC_WORK` (working copy), `TC_MEDIA_CACHE` (`media-cache` in the profile). If `py -3.12` does not work but `py -3` does, it sets `TC_PYTHON=py -3`. Claude Code session variables are removed from the server's environment.
- **Where the editor is shown** (App > **Show the editor in**): **A Chrome app window (smooth; Edge if no Chrome)** (default), **An Edge app window**, or **This app's own window**. The browser window is the browser's `--app` mode (no tabs or address bar) with its own profile in the app folder (`browser`), first opened at the remembered window size and position; autoplay allowed, translation off. Closing that browser window quits the app; the app's own window hides while the browser window is used. If neither browser is installed, the app's own window is used.
- **The app's own window**: no system title bar; Windows' minimise / maximise / close buttons are drawn over the editor's 56-pixel header in its colours; the header drags the window; the search box narrows to make room. **F10** or a right-click on the header opens the app menu. Window size and position remembered (`window.json`, default 1440 x 900). The page title is replaced by "Timeline Cards Editor (test) — <mode> — <vault>". Links outside the local address open in the default browser.
- **Tray icon** "Timeline Cards Editor: <mode> - <vault>": a click opens the same App menu.
- **App menu**: Show the editor in (above); **Choose vault folder…** (then restarts); **Edit the vault's own files (write mode)**; **Restart server**; **Open the working copy folder** (disabled in write mode); **Open the server log**; **Quit**. **View** menu (own window): Reload, Toggle full screen (F11), Zoom in / Zoom out (half a step), Actual size, Developer tools (Ctrl+Shift+I).
- **Quitting** stops the browser window and the whole server process tree first.
- **Files** in the app profile: `settings.json` (vault, write, shell), `server.log` (rotated above 4 MB to `server.log.1`), `work/`, `media-cache/`, `browser/`, `window.json`. Environment overrides (DEV ONLY): `TCE_USERDATA`, `TCE_PORT`.
- **Build**: `npm run dist` (or `npm start` to run unpacked) first runs the stage script, which refuses if the editor client is not built ("the editor client is not built: cd editor; npm run build") and copies into `runtime\` the editor's sources and built client (skipping node_modules, design, test coverage, screenshots, Python caches and source maps), the run-time packages tsx, esbuild (with its Windows binary) and ws ("missing <pkg> (cd editor; npm install)" if absent), the `multicam_pipeline` Python package and the top-level `.py` / `.json` files (not `*.example.json`); prints the staged size. Outputs `Timeline-Cards-Editor-Setup-<version>.exe` and `Timeline-Cards-Editor-<version>-portable.exe`. Machine needs ffmpeg/ffprobe, Python 3.12 (or 3.x) and optionally the claude CLI for the features that use them.
- **Performance harness** (DEV ONLY): `node perf/lane-perf.mjs --profile <profile dir> [--key <cut list>] [--cpu] [--vsync] [--headless] [--cdp <port, default 9339>]` launches the unpacked app with the frame cap off, waits 12 s, and runs scenarios (idle, playback, play/pause x12, lane wheel scroll, seek clicks, seek while playing, ruler drag-scrub, Ctrl+wheel zoom), printing frame-interval statistics, long-frame attributions and optionally the top CPU functions, and whether the worst non-idle 99th percentile meets the 10 ms (100 fps) budget.

## Looks redundant or overlapping

- Two separate "keep offline" mechanisms live side by side in both apps: the older page's per-clip "projects folder" (`<episode>/<cut list>/Audio/<clip>`, `X-Cards-Keep`, its own index file) and the new editor's "Keep on this device" store (`/__app/api/keep`, `<episode>/<cut list>/<clip>.ogg`, `.timeline-cards-keep.json`). Both default to the same folder on Windows and Android.
- Two auto-keep switches for the same idea: local storage `cards_auto_keep` (old page) and `tc.offline.autoKeep` (new editor); the settings page flips both at once.
- Two "working offline" flags: the app's `force_offline` (local server) and the page's `cards_force_offline`, plus the editor's `tc.offline.force`; the settings page sets only the first two.
- The Windows and Android local servers are the same contract written twice (JavaScript and Java), and the Android app carries its own small JSON parser.
- Two Windows Electron apps (Timeline Cards and Timeline Cards Editor), each with its own window code, menus, single-instance and window-position logic; the Editor app additionally can hand its window to Chrome or Edge.
- The shelf has two players: the main timeline engine and a second "bench" engine with its own 16 MB cache.
- The project folder can be changed from two places (the editor's "On this device" panel and the app settings page), with the same move/leave dialogue built twice.
- "Select mode" is reachable from the shelf's floating button, from the View settings sheet, and from a drawer row.
- The clip colour picker is reached from the card right-click, the lane menu (Clip colour…), the staged card menu, the selection menu and Shift+C.
- Gap notes: three import/migration paths (the old app's `timeline_notes.json`, the editor's earlier `.tcards` sidecars, and the browser's offline queue), all aimed at the same one-time move.
- Gap-note conform preview runs the old Python conform planner dry, separately from the Resolve feature's own conform plan route (another section).
- The lane's "All stacks" button in View settings always answers that a cut list has no stacks.
- The Story Deck links (canvas, work folders) sit inside the Gap notes panel although they are unrelated to gap notes.

## Claims the code does not back

- `features/lane/client.ts`: `wordsFetcher` is documented as "Bounded: a 10 s timeout per clip"; the code aborts after 45 seconds.
- `features/lane/client.ts` treats a 404 from `/api/lane/words` as "the clip has no words"; the server answers an empty list for that case, not a 404.
- `features/shelf/keys.ts` labels Ctrl+X "copy them, then stage them"; the code deletes them from the cut, and the core delete puts them back on the shelf in the category of their section (the effect is staging, but it is a delete, not a stage, and they do not go to the shelf view's current category).
- `apps/android/.../LocalServer.java` says the downloaded build "is ... checked against its sha256"; it is checked only when latest.json carries one. The Windows code refuses an update with no checksum (comment dated 2026-11-11 says this rule was added); the Android code still installs an unchecked one.
- `apps/shell/app.html` comment lists `POST /__app/api/keep/open` as "show it in the file manager"; on Android nothing is opened (no opener is set) although success is reported.
- `apps/windows-editor/README.md` says the app "shows it in a window with no system title bar"; by default the editor is shown in a Chrome (or Edge) app window, and the app's own window is only used when chosen or when neither browser is installed.
- `adapters/cli.ts` says "the server has no export route"; the Resolve feature's server (another section) has `POST /api/resolve/export` and uses these exporters.
- `adapters/resolve/COMPANION.md` calls the live Resolve companion "not built"; the Resolve feature's server (outside this part) has `/api/resolve/companion/*` routes. Not verified further here.
- `features/looks/client.ts` sound row text "The volume needs the player’s master control, which this build does not have yet": the shipped audio engine does have a master volume (`setMasterDb`), so this line shows only if the window's player is something other than that engine.
- `apps/shell/app.html` KEEP ON THIS DEVICE says "Every cut list you open with the server up is kept on this device in the background"; the editor's top-up only adds the cut list that is open when a top-up runs (20 s after page load, then every 10 minutes), not every one opened in between.
- `apps/e2e_offline.py` and `apps/android/e2e_device.py` drive the OLD page's functions (`oflDownload`, `OFLQ`, `sendEdit`, `.card[data-uid]`, `reorder_web.py`); they do not exercise the new editor's offline store.

## Could not determine

- Whether the new editor's live sync (a WebSocket) works through the Windows and Android apps: both local servers answer any upgrade request with 501. Whether the editor falls back to plain HTTP there is in other sections.
- Who provides `window.tc.places` (recorded places) and `window.tc.follow` used by the View settings navigation row; if nothing does, those buttons are permanently disabled.
- Who calls the gap-notes `/api/gapnotes/plan` `fps` field: the page never sends one.
- The exact behaviour of the core reducer ops the shelf dispatches (`stage`, `unstage`, `moveStaged`, `addCategory`, `removeCategory`, `renameCategory`, `saveSequence`, `restoreSequence`, `deleteSequence`, `renameSequence`, `setColour`, `setGain`, `insertRun`, `move`, `setGapNote`, `setSummary`) beyond what the shelf shows: they live in the core section. Refusal sentences from the reducer are shown as notices by the store, which is outside this part.
- What the CC Sync dashboard serves at `/cards/app/latest.json` and whether it checks sign-in (the apps treat 401 or 303 as "sign in first").
- Whether `X:\Apps\Timeline Cards` (publish destination) and the hard-coded first-run server address match any customer other than this studio.
- The `.md` files in these folders (shelf, gapnotes, keep, looks, lane READMEs, `adapters/resolve/COMPANION.md`, `apps/windows-editor/README.md`) were treated as documentation only; the binary and generated files (icons, `gradle-wrapper.jar`, `__pycache__`, `package-lock.json` files) were not inventoried.
