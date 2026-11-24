# Timeline Cards: the editor: what real use taught

410 lessons. Each is one rule the product can be tested against: what a person saw (the heading), why it happened, and what the product must do. Kinds: *given* is a fact about something the studio has whatever is built; *ruling* is the owner's decision; *situation* is something the product must survive.

## The lane: how clips look and read

### CE3-001: The timeline strip with words inside the clips is the product's heart.
- Why: The owner: "the most useful thing about this app is the timeline with text inside the clips, by far the most useful and used thing."
- Must: The lane (the timeline strip) gets the most space, keeps clip text legible at every zoom and height, can be resized and docked, and never regresses.
- Kind: ruling

### CE3-002: Lane clip text wraps Chinese by character but never splits an English word.
- Why: The owner: "frequentl / y" must not happen; Chinese wraps per character, and waveforms fill the clip's height behind the text.
- Must: No Latin word is broken across lines in a lane clip; an overlong one ends in an ellipsis; Chinese wraps per character.
- Kind: ruling

### CE3-003: Clips show English first, the original underneath, flipped by one control or F9.
- Why: The owner kept a one-control language switch and could not find it, asking for F9; Russian and Ukrainian interviews are coming, so nothing may assume Chinese.
- Must: English shows first with the original underneath if it fits; one control and F9 flip them, remembered per browser; each clip's language comes from its transcript.
- Kind: ruling

### CE3-004: Reading aids let the owner cut languages he cannot read.
- Why: He reads Chinese but not Russian or Ukrainian, and asked for ten aids: playhead word in both languages, sentence ends, verbs, safe cut points, negations, a join check, and more.
- Must: Each aid is a per-device toggle, on by default for languages outside "languages I read"; without the analysis the editor says so quietly and still works.
- Kind: ruling

### CE3-005: Dragging a clip's edge shows the trimmed-off words faded.
- Why: The owner chose faded handle text so that extending a clip is "drag until the sentence ends".
- Must: While dragging or hovering near a clip edge, the words beyond the edge show faded.
- Kind: ruling

### CE3-006: Narrow clips must keep their words and their waveform baseline.
- Why: The owner: "prevent the waveform from going into the middle of a clip and the text disappearing at small zoom levels when the clip gets too horizontally short".
- Must: At any zoom a clip keeps its words, cut off at its edge, and its waveform sits on the same baseline as its neighbours.
- Kind: ruling

### CE3-007: Clip text reflows only on zoom, never while scrolling.
- Why: Words inside clips re-wrapped as the lane scrolled; the owner: "the text only reflows when you zoom in and out".
- Must: Scrolling moves clip text with its clip unchanged; text re-wraps only when the zoom level changes.
- Kind: ruling

### CE3-008: Several lane features were declined and must not be proposed again.
- Why: Declined: words at spoken time, snapping trims, a read-the-joins mode, zoom-adaptive gist text, drawn pauses, search hits in the strip, a pacing ruler, stacked takes, hesitation and filler marks.
- Must: None of these is built or proposed again; of the hesitation marks the owner said "lets ditch all this, it's not useful actually".
- Kind: ruling

## Colours

### CE2-040: Some of Resolve's clip colours are nearly invisible on a dark card.
- Why: Resolve's sixteen clip colours are fixed; Navy is nearly black and measures 2.35:1 against a dark card, invisible as a waveform on a dark row.
- Must: Every Resolve clip colour, drawn on a dark surface, stays recognisable at 3:1 or better without altering the colour itself.
- Kind: given

### CE2-042: Each interviewee has one unique colour, changed once for all cuts.
- Why: Clips with no stored colour got one made from the name, so one person showed orange beside navy; the owner wants the "interviewee's base colour everywhere".
- Must: One action recolours every cut of a person in one undo, a cut with no colour takes its person's colour, and no two interviewees in an episode share one.
- Kind: ruling

### CE2-043: The transcript panel is outlined in its interviewee's colour.
- Why: The owner wanted the transcript panel framed in the colour of the interviewee it belongs to.
- Must: The open transcript panel is outlined in the same colour its interviewee carries on the cards and the lane.
- Kind: ruling

### CE2-044: Neighbouring montage clips from different sources should differ in colour.
- Why: The owner: "assign separate colours to clips from a different speaker / source - ideally no clips touching each other".
- Must: Each speaker or source in a montage gets its own colour, and no two adjacent clips from different sources share one.
- Kind: ruling

### CE2-041: Card colours must match the clip colours in Resolve.
- Why: One interviewee was dark pink in Resolve and light pink on cards; the page is read on a calibrated monitor in a graded room.
- Must: Interviewee colours equal their Resolve clip colours for all sixteen, and status colours like amber and red stay distinguishable at their real 11-12 px size.
- Kind: situation

## Sections and the overview

### CE2-032: A section is a heading of any colour, never decided by colour.
- Why: The owner: "Sections should keep the section heading styling in any colour"; recolouring turned a heading into a bullet, on the page and in the saved file.
- Must: A marker's kind (section, note, marker) is stored apart from its colour; any colour can make a section, and recolouring never changes the kind.
- Kind: ruling

### CE2-033: Each section shows as a band on the ruler, a tint and a fold.
- Why: The owner wanted sections coloured on the timecode strip with labels inside, draggable as whole blocks from the overview.
- Must: A folded section shows its cut count, length and summary; folds are remembered per project; the cursor landing inside opens it; whole sections drag from the overview.
- Kind: ruling

### CE2-034: Neighbouring sections never share a colour.
- Why: The owner: "by default adjacent categories are never the same colour (right now they're all blue)".
- Must: Neighbouring sections get different colours by default, and the lane's time bar and a bottom stripe show where each section starts and ends.
- Kind: ruling

### CE2-036: Cuts dropped at the top of a section join it under its heading.
- Why: The owner: "when you move clips to the beginning of a section it should not move the position of the section".
- Must: Dropping cuts in front of a section's first cut puts them inside it, under its heading, and no other cut moves.
- Kind: ruling

### CE2-039: A side panel lists every marker, with short section summaries.
- Why: The owner asked for a closable outline of markers opened from a top-left icon, with a summary per section; the summaries came out "much too long".
- Must: Clicking a marker in the overview jumps there, and each section summary fits in a few lines.
- Kind: ruling

### CE2-035: Dragging a card across a section boundary moved an unmoved card.
- Why: Headings were anchored by position, so dragging a card up shunted the previous section's last card into the next section.
- Must: A drag changes only the dragged card's section; deleting a section's first card keeps the heading; both halves of a split stay in their section.
- Kind: situation

### CE2-037: An empty section could not be dragged and shared its fold with the next.
- Why: A section with no cuts takes the next section's position, so a drag read as "dropped on itself" and folding one folded both.
- Must: Each section is told apart by its own identity, not position, for dragging, dropping, tap-to-place and folding, including sections with no cuts.
- Kind: situation

### CE2-038: A paid section summary vanished after any trim above it.
- Why: Summaries were tied to a time position, so a trim above or a section move orphaned them, showing "no summary yet" after the work was paid for.
- Must: A summary follows its section through trims and moves; a renamed section loses it on purpose, and an orphan is never guessed onto another section.
- Kind: situation

## The lane: clicking, trimming, zooming and dragging

### CE1-095: Chrome and Edge keep F12 for developer tools, and no page can take it.
- Why: The owner's "head to mouse" shortcut on F12 opened developer tools instead, and his mouse side button sends F12.
- Must: No page shortcut uses F12 or another browser-reserved key, and a mouse button sending F12 is remapped before the browser, leaving Resolve's own F12 alone.
- Kind: given

### CE1-096: In Chrome on Windows a lone Alt press hands the keyboard to Chrome's menu.
- Why: After Alt was pressed and released alone, as after Alt plus wheel, click or drag, the next Space opened Chrome's three-dot menu instead of playing.
- Must: Space always plays or stops, straight after any Alt gesture, and never activates a browser menu or a focused button.
- Kind: given

### CE1-097: Many laptop keyboards have no Insert key.
- Why: Adding a gap at the head was bound only to Insert, which the owner's laptop lacks, and the controller had none; he chose a long press of X.
- Must: Every key action has a binding every laptop keyboard can reach and one on the controller; holding X adds a gap at the playhead.
- Kind: given

### CE1-098: A single click on a lane clip only selects it.
- Why: The owner: clicking a clip "should not move the timeline view" nor the transcript, "it should only be double click".
- Must: A single click or key selection leaves the transcript and view where they are unless the clip is wholly off screen; a double click opens that cut's paragraph in its transcript.
- Kind: ruling

### CE1-100: F splits the clip under the playhead.
- Why: The owner: "f blade split isn't working" on the lane.
- Must: Pressing F with the timeline focused splits the clip under the playhead at the playhead.
- Kind: ruling

### CE1-101: Stepping between clips moves the playhead and leaves the selection alone.
- Why: The owner: "if you have a clip selected and then d pad up to the previous clip, it will deselect... I don't want that to happen at all"; the keyboard likewise.
- Must: Next and previous edit, from the keyboard or the controller's D-pad, move the head only and leave a single or range selection exactly as it was.
- Kind: ruling

### CE2-001: The lane must handle like Resolve's own timeline.
- Why: The owner asked for Alt plus wheel to zoom "to match resolve", centred waveforms, the playhead following a ripple trim, and no momentum when panning.
- Must: The lane uses the person's Resolve keyboard preset (Resolve's defaults otherwise), Alt+wheel zooms, trims keep the playhead's spoken moment, waveforms share a baseline underneath, panning stops with the mouse.
- Kind: ruling

### CE2-002: The lane plays the whole cut and edits exactly like the cards.
- Why: The owner asked for a resizable strip under the cards, with waveforms and each clip's words wrapped inside, for listening through and editing.
- Must: The lane plays every cut in order, wraps clip words with an ellipsis when cut off, can be resized, and any edit made there matches the same edit made on the cards.
- Kind: ruling

### CE2-003: Clicking a clip selects it and never moves the playhead.
- Why: The owner: "Sometimes you want to select a clip but leave the playhead elsewhere"; a click used to select and seek too.
- Must: A click or tap on a clip only selects it, leaving playhead and view still; only the ruler, empty timeline or a dedicated key moves the playhead.
- Kind: ruling

### CE2-007: Dragging a clip edge outward must lengthen it and show the words added.
- Why: The owner: "I still can't drag a clip out"; an outward drag was refused, and extending showed nothing of "what words you're adding to the edit".
- Must: Dragging an edge outward extends it from its source, showing live the new extent and words; it is refused only when the source has nothing left, with the reason.
- Kind: ruling

### CE2-008: Extending over the next piece of the same recording is allowed.
- Why: Dragging an edge over the neighbouring cut from the same source raised a refusal; the owner said "allow it".
- Must: A clip can be extended over material its neighbour also uses, with no refusal; the overlap then plays twice.
- Kind: ruling

### CE2-012: Go-to-clip-start and end keys act on the clip under the playhead.
- Why: The owner: these keys "should take the playhead as the 'current' position, not which lane card is selected."
- Must: The go-to-clip-start and go-to-clip-end keys move the playhead within the clip it is in, whatever is selected.
- Kind: ruling

### CE2-013: Clips outside the current section must not be dimmed.
- Why: The timeline darkened everything outside the playhead's section, which "makes it harder to move clips between sections".
- Must: Every clip on the timeline is drawn at full brightness whatever section the playhead is in.
- Kind: ruling

### CE2-014: Lane text strained the eyes on bright clips; dark joins vanished.
- Why: White text sat on bright clip colours and joins between dark blue clips were invisible; owner chose "ink by luminance. Waveform faint at rest. Seam at every cut."
- Must: Clip text is dark on light colours and white on dark ones, the waveform is faint at rest and full while adjusting, and every cut shows a seam.
- Kind: ruling

### CE2-016: The lane docks at the top or bottom with no gap under it.
- Why: The owner asked to "drag the lane to the top"; the first build left 71 px: "too much space between the lane and other windows".
- Must: On desktop the lane docks top or bottom by drag or button, is remembered, and at the top leaves no more gap than the page's normal margin.
- Kind: ruling

### CE2-017: The cards and transcript panels flow around the lane, never under it.
- Why: Resizing the lane covered the cards and browser panel; the owner wanted them to "flow around the lane", the browser open by default with adjustable width.
- Must: However the lane is resized no panel is hidden beneath it; the browser panel opens by default on desktop and its width can be dragged.
- Kind: ruling

### CE3-009: Lane zoom stays under the pointer, and selection marks are thin.
- Why: The owner: "zooming the lane should always zoom it around where the cursor is"; selection markers should be "less thick, more subtle".
- Must: Zooming keeps the point under the pointer still, and a selected clip's marks are thin and never extend past its top or bottom.
- Kind: ruling

### CE3-010: A middle-button drag pans the lane without the browser's autoscroll.
- Why: The owner asked that a middle-button drag pan and fling the lane; browsers otherwise start the Windows autoscroll ring or a middle-click paste.
- Must: A middle-button drag on the lane pans it with no autoscroll or paste; the wheel scrolls and Ctrl+wheel zooms.
- Kind: ruling

### CE3-011: Dragging a clip moves it rather than selecting its words.
- Why: Trying to drag a clip often selected text inside it; the owner asked that the dragged clip turn see-through with a line showing where it lands.
- Must: A plain press-and-drag on a clip moves it; picking words needs a modifier; while dragging, the clip is see-through and a landing line shows.
- Kind: ruling

### CE3-012: While moving clips, the words of the clip before the landing point show.
- Why: The owner asked for an overlay of the words of the clip just before the marker when moving clips by controller or mouse, appearing with no delay.
- Must: From the first moment of a move, the words of the clip the moved clips will follow show beside the landing line, updating as it moves.
- Kind: ruling

### CE3-013: Dragging shows the card's outline and never the system's "no" sign.
- Why: Dragging a card toward the staged tab lost its silhouette and showed the Windows stop sign; the owner: "I never want to see the windows STOP sign flashing on".
- Must: While dragging cards anywhere on the page, a silhouette follows the pointer, the forbidden cursor never appears, and drags may start from blank space.
- Kind: ruling

### CE3-015: Section numbers follow their order, and sections drag by name or flag.
- Why: Reordering sections left their numbers unchanged, and sections could not be dragged in the overview or above the lane.
- Must: Moving a section renumbers every section in its new order; a section drags by its name in the overview and its flag above the lane.
- Kind: ruling

### CE3-016: The phone's vertical edit view must zoom out to an overview.
- Why: The owner: "The mobile vertical editor mode should still support zooming in and out vertically so you can get an overview of more content at once."
- Must: The phone's vertical edit view zooms vertically, from detail out to an overview of many cards.
- Kind: ruling

### CE3-018: Lane speed must be judged at the zoom the owner works at.
- Why: Checks measured low zoom on a small window while the owner works at zoom 42 to 205; he ruled the playhead leaving the view "is not a problem".
- Must: Lane speed is measured at real zoom levels and screen sizes with real waveforms; the playhead running off screen at high zoom is acceptable.
- Kind: ruling

### CE3-019: Each view remembers where you were when you come back.
- Why: The owner: "when you switch tabs it should remember your position from the last time you were in X or Y tab".
- Must: Re-entering a view, or reloading, restores its scroll and zoom, unless a jump, active playback or the person's own touch asks for somewhere else.
- Kind: ruling

### CE1-099: Lane keys stopped working, or did other things, with no Resolve connected.
- Why: The trim keys came only from the editor's Resolve key layout, which was forgotten at each server restart, so with no Resolve the keys fell through.
- Must: Lane keys follow the editor's Resolve preset by command where known and the editing-program help is on, else documented defaults, work the same without Resolve, a learned layout survives restarts.
- Kind: situation

### CE2-004: Clicking a long clip while zoomed in made the lane jump away.
- Why: The lane re-centred whenever either edge of the clicked clip was off screen, which when zoomed in is every long clip.
- Must: Clicking a clip moves the lane only when the whole clip is off screen; otherwise the frame under the pointer stays put.
- Kind: situation

### CE2-005: Zoomed out, drags grabbed the wrong clip or resized it.
- Why: At low zoom a press landed some pixels from where clips were drawn, and trim handles covered tiny clips entirely, for single and multiple selections.
- Must: At every zoom a press acts on the clip drawn under the pointer, and a clip narrower than 24 px moves rather than trims.
- Kind: situation

### CE2-006: Selecting several clips did not work and outlined the whole timeline.
- Why: Ctrl+click, Shift+click and box selection did not select several clips, and Shift+click drew a blue outline round the timeline.
- Must: Ctrl+click, Shift+click and a drawn box select several clips, each selected clip is visibly tinted, and they drag as one group.
- Kind: situation

### CE2-009: Trim to playhead left a one-frame sliver as its own card.
- Why: The trim re-derived the clip's edge from a rounded value, landed a frame short, and the leftover frame became a tiny separate cut.
- Must: Trimming a cut's head or tail to the playhead never leaves a leftover cut of any length, at any frame rate.
- Kind: situation

### CE2-010: A trimmed clip kept its whole sentence, and its English lagged.
- Why: Cutting a trimmed clip's text to its remaining words went through the server, which refused it on one host and gave up; when it worked it took seconds.
- Must: After a trim or split the clip shows only the words inside its edges, and their English, in the same frame as the edit, with no network wait.
- Kind: situation

### CE2-011: Trimming must repaint within about a tenth of a second.
- Why: The owner: "No lag now dragging around in the timeline" once trim-to-paint measured about 90 ms typical and 100-125 ms at the slow end.
- Must: A trim gesture repaints within 125 ms for 95 of 100 tries on a desktop, and within 500 ms on a processor slowed four times.
- Kind: situation

### CE2-015: The lane bar juddered while playback speed changed.
- Why: The speed readout changed width with each step (1.3x, 1.35x, 2x) and pushed the controls beside it; the owner also wanted adjustable clip text size.
- Must: Bar controls never move while a value they show changes, readouts reserve fixed width, and clip text size can be changed and is remembered.
- Kind: situation

### CE3-014: Cards in the card list could not be dragged, showing a blocked sign.
- Why: Reordering in the list stopped working while dragging in the lane still worked; a page refresh did not help.
- Must: Cards in the list can always be dragged to a new place, with a steady drop marker.
- Kind: situation

### CE3-017: "Fit" showed only the first quarter of a 2.5-hour cut.
- Why: Fitting a 487-cut, 2.5-hour cut needs 0.08 px per second, but a zoom floor of 0.5 px that keeps cuts visible stopped it at a quarter.
- Must: Fit shows a 2.5-hour cut whole, or says its limit and keeps the head in view.
- Kind: situation

### CE3-020: A place arriving from elsewhere yanked the lane back mid-fling.
- Why: A view position adopted from another device or a refresh during a 1.4 s coast snapped the lane to another zoom under the finger, in about one fling of two.
- Must: Nothing from another device or a refresh moves or redraws a view while the person is dragging, trimming, or it is still coasting.
- Kind: situation

## Selecting, deleting, inserting and keys

### CE1-049: A file dropped into a browser page gives its name and size, never its path.
- Why: Browsers hand a page only a dropped file's name and size, so a clip dragged in must be found among the episode's files.
- Must: Dropped media is found by name and size inside the episode, and the page says which files were not found or still lack a transcript or proxy.
- Kind: given

### CE1-035: A single Delete press never deletes; a second within 3 seconds does.
- Why: The owner asked that the first press arm delete (the card turns red) and a second within 3 s delete, on phone and desktop; a held key repeats.
- Must: The first press arms for 3 s with a visible count that survives redraws; a held key never confirms; on a phone delete sits farthest from the resting thumb.
- Kind: ruling

### CE1-037: A deleted cut moves to the staged shelf under the section it came from.
- Why: The owner: "when you delete it moves the clip into the staged section for the section you're currently in ... it disappears from the lane and cards but goes to staged".
- Must: A deleted cut leaves the cards and lane and appears on the staged shelf, labelled with its section, keeping its words, English, colour and note, ready to put back.
- Kind: ruling

### CE1-038: A gap behaves like any other clip.
- Why: The owner: "Gaps should behave like any other clip"; gaps carried along with the next cut "moved around weirdly" and could not be dragged.
- Must: A gap stays put when neighbours move and can be selected, dragged to another boundary, resized, deleted and played as silence, each one undo; a gap at the very end is refused.
- Kind: ruling

### CE1-044: Selected words inside a clip can be deleted, highlighted or split.
- Why: The owner chose to edit by selecting words on the strip: delete removes only them, highlight marks the playing part, split cuts there.
- Must: Delete, highlight and split act on a word selection inside a clip, with the sound ramped at every new join.
- Kind: ruling

### CE1-045: Highlighted words stay on exactly the same words through trims.
- Why: Words highlighted while planning must show on the card, and the owner asked that highlights survive every view and every trim.
- Must: A highlight shows on the card without markup, stays on the same words after any trim, and on a translated card marks the original words.
- Kind: ruling

### CE1-047: New found material goes after the editor's existing cut, not into it.
- Why: The owner had whittled a cut to "semi useful bits": "add the new material to the end of this cut file and I will continue going through it".
- Must: Adding found material to an existing cut appends it after the last cut and leaves every existing cut and its order unchanged.
- Kind: ruling

### CE2-018: Selection is one thing shared by the cards and the lane.
- Why: Clicking a card did not select it, selecting in the cards only moved the playhead, and F did nothing; the owner wanted one shared selection.
- Must: Selecting in cards or lane selects the same item in both and scrolls the lane to it; F brings the playhead's card into view, expanded at every density.
- Kind: ruling

### CE2-019: A click selects a card, shown by a red bar beside its colour bar.
- Why: The owner asked for a red selection bar, a persistent red dot on the playhead's card, compact unselected cards, and buttons that hold still on play.
- Must: One click selects and a second opens; selection is a full-height red bar beside the colour bar, the playhead's card has a red dot, and play never moves controls.
- Kind: ruling

### CE2-020: The card under the playhead opens at every density.
- Why: At tight densities every card shrinks to a bar, so the playhead pointed at a nameless line.
- Must: The cut the playhead is inside opens like the selected card at every density, and closes again when the playhead leaves it.
- Kind: ruling

### CE2-021: When the playhead sits in a gap, the gap is highlighted.
- Why: With the playhead in a gap between clips, no card or gap showed as current.
- Must: When the playhead is in a gap, that gap is highlighted in the card list the way a card would be.
- Kind: ruling

### CE2-022: Switching between cards and lane keeps the same cut in view.
- Why: The owner asked that opening the lane centre on the selected card, and closing it scroll the cards to the cut under the lane's playhead.
- Must: Flipping between cards and lane, either way and repeatedly, lands on the same cut at the same position.
- Kind: ruling

### CE2-025: Keys went to the wrong panel with the transcript open.
- Why: With the transcript viewer open, Space and Delete acted on the wrong panel; the owner wants keys on the focused panel and Tab to move with an obvious outline.
- Must: Keys act only on the visibly focused panel, Tab cycles panels with a clear outline, and a selection made in one panel shows in the other.
- Kind: ruling

### CE2-027: Everything a person sees and touches in the editor is kept exactly.
- Why: Asked whether the rebuild's purge covers screens, menus, keys and gestures, the owner answered "No exactly, keep all that"; only what is behind them goes.
- Must: Every Timeline Cards screen, control, wording, key, controller binding and gesture behaves and reads as before.
- Kind: ruling

### CE2-028: Panels close from their header, and the top bar shows icons only.
- Why: The owner: "need a way to close the browser", "an easy toggle", and "don't need the word 'overview' and 'lane' in the top bar, just their icons".
- Must: Every panel tab can be closed, a top-bar toggle reopens it on the last tab, top-bar buttons are icons with tooltips, and phone menu rows keep their words.
- Kind: ruling

### CE2-029: "Why has the overview button disappeared? I want it back."
- Why: The overview button was moved into the options panel, whose sections were later collapsed by default, so it effectively vanished.
- Must: The overview button stays visible on the desktop top bar, and moving any control into a collapsed menu needs the owner's approval.
- Kind: ruling

### CE2-030: Menu text must be legible, and settings sections start collapsed.
- Why: The owner found dropdown text "too light", red highlights "pixellated", a big gap, a stray chevron and loose options.
- Must: Menu text meets readable contrast, highlights render crisply, and each settings section collapses, all collapsed by default, with one expand-all or collapse-all control.
- Kind: ruling

### CE2-031: Floating controls covered the cards and the text being worked on.
- Why: The insert bar hid the top of a transcript and returned while selecting; the owner asked floating buttons be see-through (about 0.55, solid on touch).
- Must: No floating bar or icon covers transcript text, the first card or the top line of a lane clip, including while text is being selected.
- Kind: ruling

### CE1-033: Delete on one card removed an eight-cut selection scrolled out of view.
- Why: A box selection stayed active while the cursor sat on another card, so Delete there removed all eight unseen selected cuts.
- Must: An action applies to the selection only while the cursor card is inside it; otherwise it touches that one card and the selection clears; every delete is undoable.
- Kind: situation

### CE1-034: After a multi-selection, Delete removed only the first card clicked.
- Why: A card was clicked, then others boxed or added, and the cursor stayed outside the new selection, so Delete acted on the single card.
- Must: However a selection is built, by box, tap, drag or modifier click, the cursor lands inside it, so Delete removes every selected card.
- Kind: situation

### CE1-036: The delete confirmation promised a Resolve edit on a file that never touches Resolve.
- Why: The arm message read "Delete again to ripple-delete this cut in Resolve" before checking where the edit would land, even in a read-only view.
- Must: Every confirm message names where the edit will land, and a read-only view refuses at the first press.
- Kind: situation

### CE1-039: Deleting a clip also deleted the unselected gap beside it.
- Why: The owner: "it will delete the gap also, even though the gap is not selected"; Resolve's own ripple delete keeps it.
- Must: Deleting a cut keeps every unselected gap beside it; only black with nothing after it goes.
- Kind: situation

### CE1-040: A dropped clip landed on the other side of a gap from the drawn line.
- Why: The owner: "clips not landing correctly on the right or left side of a gap even though the 'selection' red line is there"; pointer position chose the side.
- Must: A drop lands exactly where its insertion line is drawn, on either side of a gap, and any hint text agrees with it.
- Kind: situation

### CE1-041: Next and previous edit stopped short of or past the cut point after a gap.
- Why: Cut points were counted without gaps while the playhead counted them, so every jump after one 50-frame gap was 50 frames off.
- Must: Next and previous edit land exactly on the cut point, before and after gaps, in both directions, at 25 and 29.97 fps.
- Kind: situation

### CE1-042: Inserting highlighted transcript words put a different passage in the cut.
- Why: The words were matched at their first occurrence in the whole interview, so an earlier repeat landed, or a miss silently became the whole paragraph.
- Must: One action inserts exactly the highlighted span, within two seconds of its own time; if only the whole paragraph can be placed, the page says so with its length.
- Kind: situation

### CE1-043: The insert key opened the chat because a click had moved keyboard focus.
- Why: Selecting transcript words, clicking the target card, then pressing the insert key opened the assistant instead, since the click moved focus.
- Must: While transcript words are selected, the insert key inserts them wherever keyboard focus is.
- Kind: situation

### CE1-046: A clip name with square brackets broke the cut list.
- Why: Downloaded YouTube clips carry their video id in square brackets, and a line break in a speaker name was read back as a new cut.
- Must: Any punctuation or line break in a name or reference survives save and reload unchanged, and no supplied text can create, remove or change a cut.
- Kind: situation

### CE1-048: Making a new cut list could overwrite an existing one.
- Why: Creating a cut list from a planning board can reuse a name already in the episode, which would destroy that list.
- Must: A new cut list shows its counts before it is made, and a name already taken is refused before anything is converted.
- Kind: situation

### CE2-024: A cut with no transcript still appears as a card.
- Why: Some cuts have no transcript at all, and some are silent stretches of a transcribed clip.
- Must: Such cuts show as cards labelled "no transcript" or "silent", move like any other, and are never dropped.
- Kind: situation

### CE2-026: Keys pressed in a search window reordered the cuts hidden behind it.
- Why: With the search results window open, arrow-like keys reached the cards behind it and reordered a cut list nobody could see.
- Must: While a window covers the page, no key reaches anything behind it.
- Kind: situation

## Editing, undo and the cut list

### CE1-062: The cut list is one plain, hand-editable file stored with the episode.
- Why: The owner: the way projects were stored was "extremely confusing"; he wants "a plain text format ... platform agnostic" beside the transcripts.
- Must: A cut list is readable and editable by hand, names clips as their identity, stores seconds with each clip's frame rate, keeps every revision for undo, and opens without Resolve.
- Kind: ruling

### CE3-021: An edit shows at once, with only a small saving mark.
- Why: Every edit used to rebuild the whole list under a busy veil.
- Must: An edit appears immediately without a full redraw or blocking veil, the card being saved shows a small mark, a refusal corrects it, and undo keeps selection and scroll.
- Kind: ruling

### CE3-023: Undo steps back through saved versions of the cut.
- Why: The owner chose saved revisions of the project file, capped and thinned, over a log of operations that must be replayed to know the state.
- Must: Undo takes back the person's own last edit by restoring the version from before it, and older versions are kept, thinned rather than lost all at once.
- Kind: ruling

### CE3-031: A run of cuts can be saved aside as a sequence with exact timing.
- Why: The owner: "a 'staged' but for exact sequences", "stored as a sequence with exact second timing, not word timing", auto-named, on its own tab.
- Must: A run is stored and restored, by drag or at the playhead, with every span, fade, colour, note and the black before it exact; a run with a hole is refused.
- Kind: ruling

### CE3-032: Set-aside cuts live in the cut list, and panel tabs switch with Alt.
- Why: The owner chose a shelf of set-aside cuts kept inside the cut list but ignored when sending to Resolve, and Alt+1/2/3 for panel tabs.
- Must: Set-aside cuts stay in the cut list but never reach Resolve; panel tabs switch with Alt and a digit and can also be clicked.
- Kind: ruling

### CE3-033: A clip sits in exactly one bin, with an All view.
- Why: The owner chose strict one bin per clip over tag-like bins; bins belong to the episode, not to one cut list.
- Must: Filing a clip moves it out of any other bin, deleting a bin unfiles its clips, All lists every clip, and every device sees the same bins.
- Kind: ruling

### CE3-034: Existing cut lists keep their exact Markdown format and open unchanged.
- Why: The owner: "the cut list should remain a cut.md as it currently is".
- Must: Every cut list made before the rebuild opens, edits and saves in its present format with nothing lost.
- Kind: ruling

### CE1-063: Opening a project changed files in the episode folder.
- Why: Opening recomputes card words from transcripts, and showing a read-only view filled a translation store, both writing to disk before any edit.
- Must: Opening, browsing and playing leave every file in the episode byte-identical until the editor makes an edit or switches writing on.
- Kind: situation

### CE1-064: Acknowledged edits were lost to a second writer, an undo race or a crash.
- Why: Two servers on one cut list lost confirmed edits, an undo racing an edit wiped it, and a crash mid-save ate an outside edit to the file.
- Must: An acknowledged edit, or an outside edit to the file, survives a second writer, an undo racing it, and a crash at any point.
- Kind: situation

### CE1-065: The cut list changed on disk while the editor had it open.
- Why: Another program can edit the cut list while it is open, and an edit applied to the stale copy would overwrite that change.
- Must: An outside change to the open cut list shows within 2 s and is merged in as edits, told to every device; nothing made in the editor meanwhile is lost.
- Kind: situation

### CE1-066: One cut list saved from two places at once can lose one side's change.
- Why: The browser editor and a laptop app edited the same cut list; both merged this time, but nothing stopped two writers overwriting each other.
- Must: When one cut list is saved from two places at once, both changes are kept or the second is refused, with the conflict shown to both people.
- Kind: situation

### CE3-022: A held trim key during playback shrank a whole cut to frame-long pieces.
- Why: Holding the trim key while the lane played repeated the edit 350 times in 90 seconds, each on the next clip, until every clip was 1 to 7 frames.
- Must: Holding an editing key never repeats the edit; one press is one edit; every cut-list revision is kept so a damaged list can be restored.
- Kind: situation

### CE3-024: Undo was refused offline and took ages online.
- Why: The owner: "undo doesn't seem to work in offline mode" and "undos take ages"; one undo across 521 cuts of nine hour-long interviews took 1.7 s.
- Must: Undo works offline on unsent edits, never replays what was taken back, and online returns well under a second on long episodes.
- Kind: situation

### CE3-025: Redo history vanished when a note was saved beside an undo.
- Why: Saving a card's note at the same moment as an undo could wipe the redo history or make the file look changed by someone else.
- Must: Notes, undos and redos in any order and timing never lose a redo step or trigger a false outside-change reload.
- Kind: situation

### CE3-026: Moving a whole section was refused with a word that did not apply.
- Why: The permission check asked where the cards came from instead of whether a cut list was open, blocking section moves, gaps and redo.
- Must: With a cut list open, moving a whole section is one undoable edit, and no refusal names a concept that does not apply.
- Kind: situation

### CE3-027: An action that is refused must say so where the person is looking.
- Why: Delete on a selected card did nothing visible; split on a phone said nothing, its reason hidden off screen, in a tooltip, or naming keys a phone lacks.
- Must: Every action gives a visible result or a reason where the person is looking on any device, naming something they can reach; a disabled control answers a tap.
- Kind: situation

### CE3-029: A word at a cut's edge came and went.
- Why: Two places used different rules for whether an edge word belonged to a cut, so it appeared or vanished depending on which answered.
- Must: Whether a word at a cut edge belongs to the cut is decided by one rule everywhere it is shown.
- Kind: situation

### CE3-030: Highlighted transcript text must become a card of exactly those words.
- Why: Selecting words in a montage clip's transcript matched text loosely, so the card that arrived was "not even close to what you highlighted".
- Must: Dragging highlighted transcript text into the cut creates a card covering exactly the highlighted words of that clip.
- Kind: situation

### CE3-035: Two cut files were listed under the same name.
- Why: Lists showed an inner title copied from the file's source, so two different cut files read the same.
- Must: Cut files are listed by their own file name, a differing inner title shown muted after it, and a new cut is titled after itself.
- Kind: situation

### CE3-036: Section colours disappeared from a cut.
- Why: A montage cut's section colours vanished; no cause was recorded.
- Must: Section colours persist through every edit, reload and import of a cut.
- Kind: situation

## Notes and the staged shelf

### CE1-060: Chrome fires no drag-end when the dragged card is removed from the page.
- Why: When a dropped card is removed from the list, Chrome fires no drag-end, so the page believed a drag was running and stopped updating until reloaded.
- Must: After any drop the page takes updates again at once, even when the dragged card is gone from it.
- Kind: given

### CE1-061: Browsers report "drag left" when the pointer moves onto a target's own child.
- Why: Moving over a drop target's count or close button fires a leave event on the target, so it was unlit at the moment of the drop.
- Must: A drop target stays highlighted while the pointer is anywhere inside it, its children included.
- Kind: given

### CE1-050: Notes attach to cards and gaps and show in yellow.
- Why: The owner asked for notes on gaps and cards, shown beneath them highlighted yellow, and "in the lane it should have a yellow square in the top right corner".
- Must: Any card or gap takes a note shown beneath it on yellow, and its lane clip shows a yellow square in the top right corner.
- Kind: ruling

### CE1-051: Every note lives inside the cut list.
- Why: The owner wants every note, gap notes and section summaries included, in the cut list itself, never in a side file.
- Must: All notes are stored in the cut list as ordinary undoable, synced edits, and notes from older side files are brought in once.
- Kind: ruling

### CE1-053: Note and section rows can be deleted in place and moved.
- Why: The owner: "the green sections should be deletable or movable, they are annoying".
- Must: Every note or section row in the card list can be deleted in place with one click, as one undoable revision, and dragged to another position.
- Kind: ruling

### CE1-055: A staged shelf holds cuts taken out of the cut without deleting them.
- Why: The owner asked for a "staged clips" tab kept inside the cut file, whose cards look like timeline cards and reorder the same way.
- Must: Cards dragged from the list or lane onto the shelf leave the cut but stay in the file, play on click, reorder, and drop back exactly where the line shows.
- Kind: ruling

### CE1-057: Staged cards play from a chosen word, and categories open from anywhere.
- Why: The owner: staged cards "should have the same playhead selector as transcripts", and categories should open "from anywhere as an overlay without scrolling".
- Must: Clicking a word on a staged card plays from it to the cut's end, and a key opens the category picker from any view.
- Kind: ruling

### CE1-058: Staged cards can be filed into categories the editor names.
- Why: The owner: "right click > add to category > select existing categories or add a new one", with a strip filtering the shelf; a planning board's groups come across.
- Must: Categories keep document order, never alphabetical; a card sits in one; deleting a category returns its cards to the plain shelf; a board made into a cut brings its groups.
- Kind: ruling

### CE1-052: Clicking "add note" appeared to do nothing.
- Why: The note editor opened, focused, in a column a few pixels wide beside the card text, so typing went somewhere invisible.
- Must: A note editor, like every editor a gesture opens, appears inside its card at full text width, in every density and on a phone, from the first keystroke.
- Kind: situation

### CE1-054: Named markers vanished after a reload.
- Why: Marker edits were refused and the page dropped the refusal, so markers lived only in the browser until the next reload.
- Must: A marker, with its name, colour, note and length, survives reload and restart like any other edit.
- Kind: situation

### CE1-056: A card dropped on the staged shelf vanished and landed last.
- Why: The drop filed the card under the plain staged heading while another category was on show, with no position, so it went out of sight at the end.
- Must: A card dropped on the shelf lands in the category being viewed, at the slot the insertion line showed, and is scrolled into view.
- Kind: situation

### CE1-059: Cards could not be dragged into shelf categories, or far up the list.
- Why: The category strip scrolled 1624 px out of view, auto-scroll moved the window not the panel, refreshes replaced the target mid-drag, and the wheel did nothing.
- Must: While dragging, every drop target stays reachable and still, the wheel and edge scroll the panel under the pointer, and the target stays lit until the drop.
- Kind: situation

## Playback and audio

### CE1-077: A browser audio element only plays forwards.
- Why: Scrub audio built on a browser's audio element was silent when scrubbing backwards and when still.
- Must: Reverse and slow scrubbing still sound like the words.
- Kind: given

### CE1-078: A browser's audio clock advances in steps of about 40 ms.
- Why: Zoomed in, 40 ms is 2 to 3 pixels, so a playhead drawn straight from the clock jerks.
- Must: The playhead moves continuously at the play rate between clock readings and never steps backwards.
- Kind: given

### CE2-045: A browser given a video file to play sound decodes the video too.
- Why: Chrome decodes the video track to reach the audio, contending for the decoder other tabs use, so the lane froze and YouTube stuttered; it also sends date-form range checks.
- Must: The browser is only ever handed audio-only files for sound, and partial-file requests work with every validator form browsers send.
- Kind: given

### CE2-046: Chrome puts an idle sound output to sleep, and Bluetooth adds delay.
- Why: After silence Chrome parks the output, so sound came half a second late; Bluetooth adds 150-250 ms, and muted video ran 0.1 s ahead.
- Must: The playhead moves the instant Play is pressed after any seek, eases into sync with what is heard within half a second, and picture waits for the sound.
- Kind: given

### CE2-047: Seeking a playing browser media element clicks, and its clock is coarse.
- Why: Setting a playing element's position discards and refills its buffer, a step plus a dropout; its position advances in about 40 ms steps.
- Must: Playback across any cut or chunk boundary is click-free, never jumps a playing element at a splice, never times a join from its coarse position, and seeks during first load work.
- Kind: given

### CE2-048: A position set on audio not yet loaded is silently lost.
- Why: In browsers, setting a media element's position before it has loaded is only a start hint, discarded if the source is assigned again.
- Must: A seek asked for before audio is ready is kept and applied once it loads, and the newest request always wins.
- Kind: given

### CE2-049: A play interrupted by the page's own pause is not a refusal.
- Why: A pending play the page interrupts with pause or a new load fails with an abort error, which was shown as "the browser would not start playback".
- Must: A play cut short by the page's own pause or reload is never shown as an error; real refusals still say what they are.
- Kind: given

### CE2-050: Browser audio ignores level changes during a scheduled ramp.
- Why: Chrome ignores a plain level write during a ramp (Firefox warns), a cancel mid-ramp does not hold the level, and a hidden tab draws about once a second.
- Must: Fades, joins and levels run on the audio clock, sound right in a background tab, survive a level change mid-fade, and pause mid-fade without a pop.
- Kind: given

### CE2-051: Resolve's scripting cannot load or position its source viewer.
- Why: The owner wanted selected text to cue Resolve's source viewer like its own transcript window, but that is not scriptable.
- Must: Selecting transcript text lets the editor hear exactly that passage, from the product's own audio, without Resolve and without leaving the page.
- Kind: given

### CE2-057: Matching interview peaks leaves speech 10 dB apart.
- Why: A peak is set by the loudest 20 ms in an hour (a door, a laugh), so "same peak" does nothing audible for speech.
- Must: Preview levelling matches speech loudness with pauses and room tone ignored, and a limiter stops raised clips distorting.
- Kind: given

### CE3-038: Chrome lets an idle audio device sleep, so the first Play waits.
- Why: Chrome puts an idle audio output to sleep, and Play then waits for the device to wake.
- Must: The first Play after a pause sounds without a wake-up delay.
- Kind: given

### CE3-039: A browser's plain audio player can only lower volume, never raise it.
- Why: The transcript played far quieter than the lane, which lifts quiet interviews by up to 18 dB, because plain playback cannot go above full level.
- Must: Audio heard from the transcript gets the same level lift, master volume and limiting as the same moment on the lane.
- Kind: given

### CE3-040: Any audio played in an Android web view stops the phone's music.
- Why: An Android web view takes full audio focus for any audio element playing aloud; a muted element routed elsewhere takes none.
- Must: On Android the preview lets the phone's music keep playing, ducked, and releases it about 1.5 s after playback stops.
- Kind: given

### CE1-084: Cuts play back to back with no pause at the join.
- Why: The owner: "a short pause between clips negates the ability to test audio splicing"; the playhead also stepped backwards at each crossing.
- Must: Across any join the next cut sounds the instant the previous ends, and during playback the playhead only moves forward.
- Kind: ruling

### CE1-085: Audio fades drawn on the lane must be heard as drawn.
- Why: The owner ruled fades audio only and linear in gain, then: "make audio fades in the lane actually play, not just be visual".
- Must: The lane and scrubbing play each fade as drawn at every rate, overlapping ends multiplied, with no click; there are no video fades; the transcript player never fades.
- Kind: ruling

### CE1-087: Faster playback keeps the voice's pitch, and switching speed leaves no hole.
- Why: The owner: "at 2x the audio needs to not go high pitched"; switching speed mid-play gave about 380 ms of silence and skipped short clips.
- Must: At any speed other than 1x voices keep their pitch, and a speed change keeps sound at the old speed until the new one is ready, then crossfades.
- Kind: ruling

### CE1-088: Scrubbing is heard, at scrub speed and in both directions.
- Why: The owner: "hear audio as I'm scrubbing, at the speed I'm scrubbing, pitch normalised", "reverse scrub audio playback too", and audio while trimming.
- Must: Dragging the playhead, jogging with a controller stick, or dragging a cut's edge plays the audio under it at that speed with natural pitch, forwards and backwards.
- Kind: ruling

### CE1-089: The playhead, scrubbing and panning stay perfectly smooth at every zoom.
- Why: The owner wants it "perfectly smooth, like resolve"; lag returned five times, from full redraws per frame, bursts after load and requests repeated hundreds of times a second.
- Must: Each lane frame draws in a few milliseconds at any zoom, 4K included and just after load, and no background request repeats faster than every few seconds.
- Kind: ruling

### CE1-091: No edit moves the playhead forward, and play starts where the playhead is.
- Why: Edge drags and ripple extends carried the head to the next cut, and the play button jumped to the new join; the owner reversed an earlier rule.
- Must: After any edit the head stays on the same source frame of its cut, or that cut's nearest remaining frame if trimmed away, and play starts from it.
- Kind: ruling

### CE1-092: The clip under the playhead is marked, separately from the selection.
- Why: The highlighted clip followed the selection, and the active card updated only on pause; the owner wants the mark to follow the playhead while scrubbing.
- Must: The clip and card under the playhead carry their own mark, distinct from the selection colour, following within a quarter second during playback and scrubbing.
- Kind: ruling

### CE1-093: Follow keeps the card being heard centred above the lane.
- Why: Follow lost long cards, judged a card visible while it was hidden under the lane, and switched off on any scroll of the editor's own.
- Must: With follow on the heard card stays centred in the unobscured card area; scrolling never turns it off; tap F jumps once, hold F toggles with a brief notice.
- Kind: ruling

### CE2-054: The lit word must match the audio at every zoom.
- Why: The owner wants the word under the playhead lit in white; it failed on split and edge-word cards, and starting playback zoomed out lit the wrong word thereafter.
- Must: During playback the exact word under the playhead is lit, on split, trimmed and edge-word cards, at every zoom and after zooming during playback.
- Kind: ruling

### CE2-056: Phone scrubbing sets the playhead's speed by finger distance.
- Why: The owner asked for rate scrubbing: an 8 px dead zone, 1 s/s at about 17 px, 10 s/s at 39 px, 180 s/s cap by 76 px.
- Must: A touch in the 96 x 96 px scrub pad drives the head at the rate its offset sets, finer with the finger higher, reverses past the start, and parks on release.
- Kind: ruling

### CE2-058: "Same level" brings every interviewee to the middle loudness of the cut's clips.
- Why: A fixed target never turned the loudest speaker down; one episode spanned about 20 dB; owner: "it's supposed to make all audio the same output level".
- Must: Every interviewee is brought to the median gated speech loudness of the clips in this cut, down as well as up, without clipping, and a separate trim sets overall loudness.
- Kind: ruling

### CE2-059: Automatic levelling stays, and any cut can carry its own gain.
- Why: A recorder gain rose about 12 dB mid-interview, leaving early answers 6-11 dB under; owner: "keep the existing auto loudness behaviour but add ... manually adjust levels per span".
- Must: Each cut is levelled by the speech around it and takes a manual gain (±30 dB, 0.1 dB steps), kept through split, trim, move, copy and undo, shown on the clip.
- Kind: ruling

### CE2-061: The editor warns when a join breaks meaning or grammar.
- Why: Asked whether the join check stays, the owner answered "yes".
- Must: After two pieces are joined, the editor reads the join afresh and warns when the sentence's meaning or grammar broke.
- Kind: ruling

### CE3-041: Preview loudness levelling must never touch the files.
- Why: The owner: "preview audio normalisation, so all peaks are the same", at a level he sets, that "should only affect preview and the waveforms, not the files themselves."
- Must: A user-set level makes every clip preview and draw at the same loudness, and no media file changes.
- Kind: ruling

### CE1-079: Every clip must play and show its waveform without an export step.
- Why: Only interview clips had prepared audio, so news and archive clips played silence; the owner: play "directly through to the lane, so we don't have to output wavs".
- Must: Opening a cut starts preparing every clip's audio and waveform with progress per clip; any clip whose media exists plays, matching source timing within 0.05 s.
- Kind: situation

### CE1-080: Clips with only a subtitle file beside them showed "no transcript" and did not play.
- Why: Downloaded clips had a subtitle file beside the video but no full transcription; 104 cards had no words and none played.
- Must: A clip whose only text is a subtitle file beside its media plays, shows those words on its cards, and opens a transcript built from the cues.
- Kind: situation

### CE1-081: Several audio preparations at once starved the disks.
- Why: Each clip played started its own audio preparation beside the queued ones, so up to six competed and each took up to 336 s.
- Must: Audio preparation never runs many jobs at once, and playing a clip moves its preparation to the front instead of starting another.
- Kind: situation

### CE1-082: A partial project copy played silence and guessed the English.
- Why: A laptop's copy held only text files, so audio, word timings and translations were missing and the editor quietly substituted machine translation with no word lighting.
- Must: When a project's audio, word timings or translations are missing, the editor names which, never showing an empty player, silence or substitute English.
- Kind: situation

### CE1-083: Playback popped at splices, ruining the judgement of each cut.
- Why: The owner: the pop "ruins my ability to hear if a cut is smooth"; same-recording joins jumped position with no ramp, clicks up to 7.5 times the normal sample step.
- Must: Across any join, at 1x and 2x and several in a row, no click is louder than the audio around it, and any smoothing stays a few milliseconds.
- Kind: situation

### CE1-090: Zoomed in, the playing playhead jumped and the strip did not follow.
- Why: The playhead was redrawn only on each 250-600 ms update, jumping up to 240 px, and the strip never scrolled, so the head left a 4.8 s view.
- Must: A playing playhead moves smoothly at every zoom, and the strip pages forward when the head reaches its edge unless the person is panning.
- Kind: situation

### CE1-094: The playhead stopped, jumped back, and selections reverted, cause never found.
- Why: During normal, 2x and shuttle playback the head jumped back and clicks selected the previous clip; suspects were a second window, the controller, a stale offline copy.
- Must: The playhead and selection move only by the editor's own action; a second window or a controller of the same episode never fights it.
- Kind: situation

### CE2-052: Play starts wherever the playhead is, with sound, and never jumps.
- Why: Playback could only begin at a clip's start, and Space once played silence and threw the playhead to the timeline's end.
- Must: Space plays with sound from the exact playhead point, mid-clip included, never jumps it, and the playhead's head is drawn in a colour that stands out.
- Kind: situation

### CE2-053: Releasing a scrub could leave sound playing for the rest of the recording.
- Why: Stopping paused the clip under the head, not the one the sound started on, so after crossing into another clip the sound played on.
- Must: Ending a scrub or playback silences every sound it started, whichever clip the head is on now.
- Kind: situation

### CE2-055: Scrubbing sent hundreds of audio requests and once killed the server.
- Why: Ten seconds of scrubbing sent 211 audio requests, 7 at once, each decoding a video file (about 2.7 GB read), plus 305 playhead sends; the server hit 78% CPU.
- Must: At most one scrub request is in flight, for the current position, from audio-only copies; playhead sends stay near ten a second with the final one always sent.
- Kind: situation

### CE3-042: Speech played in one ear because a near-silent second mic counted as live.
- Why: Inputs with no speech peaked between -57 and -59 dB, just over the dead-channel floor, so the speech stayed in one ear.
- Must: A channel peaking below -30 dB is treated as dead, and the live channel's speech plays in both ears.
- Kind: situation

### CE3-043: Playback stalled at the join into a clip that had just finished processing.
- Why: The next clip's player was prepared while its audio was still being made, failed, and that dead player was used at the join once the clip was ready.
- Must: A clip that becomes ready while the page is open plays at its first join without a stall (under 100 ms); nothing prepared while unavailable is reused.
- Kind: situation

### CE3-044: A phone opening straight into the edit view never found a playable cut.
- Why: Audio readiness was re-checked only while the lane showed, so the edit view asked once, before the audio was ready.
- Must: Every view that plays audio keeps checking until its clips are ready, tested from a cold start on a phone.
- Kind: situation

### CE3-045: The first cut list of an episode said "no audio sources" until reloaded.
- Why: Opening an episode's first cut list read seven 35-minute audio files; the page gave up after a few seconds and stayed stuck on the error.
- Must: A slow first audio load shows loading and keeps retrying, including on Play, and never stays stuck on an error that has since cleared.
- Kind: situation

### CE3-046: A momentary connection reset stopped the clip that was playing.
- Why: One reset marked the server down for 4 s, and the playing clip's next range request was refused on that guess.
- Must: Audio, video and waveform requests always get a real attempt, unless the person chose to work offline.
- Kind: situation

### CE3-047: The picture drifted 0.13 s behind the sound during playback.
- Why: Median picture drift measured 0.133 to 0.137 s against a 0.12 s limit, after a correction for slow remote links over-corrected on the local network.
- Must: During playback the picture stays within three frames of the sound, on the local network and over a slow remote link.
- Kind: situation

See also, filed under another capability:

- CRX-041 (Timeline Cards: the hand-over to Resolve, and exports): Fade handles are audio only, heard in the browser and exact in Resolve.
- CRX-038 (Timeline Cards: the hand-over to Resolve, and exports): Resolve's scripting cannot set fades, keyframes, transitions or clip volume.

## Media the browser gets

### CE2-062: A multicam clip in Resolve has no file path of its own.
- Why: Resolve multicam clips carry no file path, so the browser editor's video window could show nothing for them.
- Must: Previewing a cut from a multicam clip shows picture taken from its angles' source files.
- Kind: given

### CE2-063: Chrome plays YouTube's audio as it comes; re-encoding wasted seconds.
- Why: YouTube audio is Opus, which desktop Chrome plays inside MP4; re-encoding took 4-24 s a clip where copying the track took 0.6 s.
- Must: Audio the editor's browser can already play is copied, not re-encoded; conversion happens only for a browser that cannot play it.
- Kind: given

### CE2-065: New clips must be playable without waiting for someone to ask.
- Why: Small playback copies were made only when a clip was first played, so a fresh batch stayed unplayable for minutes and offline offered 2.9 GB of full recordings.
- Must: Every clip's small playback copy is made automatically when it lands or the project opens, before anyone plays or downloads it.
- Kind: ruling

### CE2-066: Each interview has a small video preview in its own tab.
- Why: The owner: render it "at the same time as the audio" and make video "a different tab the same as the main window"; 480p, about 1 GB per 3 hours.
- Must: Each interview gets a small picture preview made with its audio, and a Video tab plays it in step with the playhead.
- Kind: ruling

### CE2-064: The browser editor is never fed camera originals, and timing stays exact.
- Why: Rushes are too big for a browser; re-encoded audio drifted 6.5 ms per 20 s (a fifth of a frame), and a 30-frame keyframe interval is 2 s on 60p.
- Must: The browser gets audio within 1 ms of the source duration and about 480p proxies with a keyframe every second of source time, never a camera original.
- Kind: situation

### CE2-067: An abandoned video request kept streaming the whole file.
- Why: After a seek or a closed page, the server kept reading an hour-long proxy (200 MB sent after 256 KiB read), stalling the page's own requests.
- Must: When a browser abandons a media request, the server stops reading and sending it within a second.
- Kind: situation

### CE2-068: Cuts kept showing old words after their transcript was replaced.
- Why: A cut stored quoted transcript text, so when an interview's transcript was replaced the cut kept the old words.
- Must: Opening a cut re-reads its words from the current transcript.
- Kind: situation

### CE2-069: One empty answer left the lane's words blank until reload.
- Why: A temporary empty or timed-out answer was kept as final, leaving cards blank; treating it as "never asked" instead re-asked 400-600 times a second.
- Must: An empty, failed or timed-out answer is asked again after a cool-down of seconds, never at once and never given up on; only a definite "not found" means no words.
- Kind: situation

## Search and the transcript panel

### CE2-070: On Android a plain text box shows Tab instead of Enter.
- Why: The transcript find box got a Tab key on Android's keyboard, so there was no way to reach the second match.
- Must: A search box on a phone offers a search or Enter key that steps through matches, plus on-screen next and previous buttons and a "3 / 17" count.
- Kind: given

### CE1-004: Search hits show the paragraph itself, never the assistant's retyped copy.
- Why: Answers repeated each passage plus its neighbours, about 8,000 characters and 139 s a turn; the owner: "the result itself is enough"; one-person searches read every transcript.
- Must: The assistant returns only paragraph references and reasons; the page shows each matched paragraph from the transcript, 5 to 50 hits as chosen; a one-person search reads only theirs.
- Kind: ruling

### CE1-006: Search has a concept mode and a closest-literal-wording mode.
- Why: The owner: concept mode finds the idea; literal mode finds wordings "as close as possible" ("extraordinary": "amazing", "something special") and may suggest splices of sentence pieces.
- Must: Literal mode returns the nearest real wordings in the original language only, never searching the English, and can propose multi-piece splices that form the phrase.
- Kind: ruling

### CE1-009: A clicked transcript word sets a playhead that Space plays from.
- Why: The owner asked for a transcript playhead: click a word, Space plays on, holding Space skims at 2x, Esc or a new selection drops it.
- Must: Clicking a transcript word sets a playhead; Space plays continuously from it, held Space plays at 2x, and Esc clears it.
- Kind: ruling

### CE1-010: Only one thing plays at a time, across views and windows.
- Why: The lane and the transcript are two players over the same words, and both could sound together, including across pop-out windows.
- Must: Starting playback anywhere, in any window of the same episode, pauses every other player; two audio sources never sound together.
- Kind: ruling

### CE1-012: "Interview" means a transcript filed under a named person.
- Why: News clips with reporter speaker labels counted as interviewees; the owner: "'Interview' means one of my documentary interviews, so a transcript inside a named person folder".
- Must: Only transcripts filed under a named person appear among the people; the browser lists every transcript and cut list in the episode, filterable, searchable and multi-selectable.
- Kind: ruling

### CE2-071: Enter steps to the next result and Space plays it, endlessly.
- Why: Playing a result dropped focus, Enter scrolled the cards, Space with text selected scrolled the page; the owner wants to race through results listening to each.
- Must: In transcript search Enter goes to the next result and Space plays or pauses it, repeatably with no mouse; focus stays, and nothing scrolls or stalls while typing.
- Kind: ruling

### CE2-073: The find box and transcript switcher scrolled out of reach.
- Why: The owner: "the search and switch transcript function should float ... right now you have to scroll all the way up".
- Must: The find box and switcher stay visible and usable at every scroll position, on desktop and phone, with the switcher's list drawn above other bars.
- Kind: ruling

### CE2-075: Double-clicking a card opens its transcript beside the cards.
- Why: The owner wanted the card's transcript in a right-hand panel pushing the cards left, together filling the screen, searchable and switchable.
- Must: Double-clicking a card opens its full transcript at that passage beside the cards; it can be searched, closed, and switched to any episode transcript.
- Kind: ruling

### CE2-077: A key makes the transcript panel full height at its current width.
- Why: The owner: "I dont want the transcript to be full screen, I just want it to be full height, and maintain whatever width it had".
- Must: One key toggles the transcript panel to full screen height at its current width and left edge, pushing the lane aside.
- Kind: ruling

### CE2-078: The transcript shows as much text as possible, in white.
- Why: Paragraphs had too much spacing and off-cream text; the owner wanted it dense "like original timeline cards" and white.
- Must: Transcript paragraphs are tightly spaced so many are visible at once, with white body text.
- Kind: ruling

### CE2-081: Card search finds cards by their English as well as the spoken words.
- Why: Searching the cards matched only the original-language text; the owner wanted English too.
- Must: Card search matches each card's own words and its English, ignoring case and spacing, and a split piece matches only its own words.
- Kind: ruling

### CE2-082: A literal search for "I" returns only a capital I.
- Why: The owner asked for a case-sensitive literal search mode beside the normal one.
- Must: In literal mode a search matches exactly the characters and case typed, and nothing else.
- Kind: ruling

### CE2-083: A meaning search returns five best passages by default.
- Why: Owner: "I need 5 of the best matches as output and that's it"; later "let you select how many results you want".
- Must: Meaning search returns the five strongest passages, spread across speakers when equal; 10, 20 or 50 can be picked and remembered per device, odd values pulled into range.
- Kind: ruling

### CE3-048: Pinyin search works with tones, without characters, and mixed with characters.
- Why: The owner wants "chu1" for first-tone chu, "chuqu" for 出去, "出qu", "guo王", and 我d to find 我的, 我得, 我德.
- Must: A tone digit narrows to that tone, no digit matches all tones, partial and spaced syllables match, and Latin letters after characters match following syllables starting with them.
- Kind: ruling

### CE3-050: Search hits show which one is current, the count, and play from the word.
- Why: Highlights vanished during playback, there was no count, all hits looked alike, and playback from a hit started too early.
- Must: The current hit is fully highlighted, others outlined, a count like 3/12 shows, highlights stay during playback, and playback starts just before the found word.
- Kind: ruling

### CE3-051: Switching transcript re-ran the last search, and history searched again.
- Why: The owner: "if you switch transcripts it starts searching the search term just searched for"; each re-ask costs a minute, and history kept only the questions.
- Must: Changing scope never starts a search; a past search's answer is kept with its history row and shown instantly, labelled as shown again.
- Kind: ruling

### CE3-053: An empty transcript panel must show how to open a transcript.
- Why: The owner: "there should be a button for this, and prompt. it's not obvious how to open the browser".
- Must: The empty transcript panel shows a "Browse transcripts" button, its key, and a line on the other ways to open one.
- Kind: ruling

### CE3-054: A montage is built from folders of clips by describing it.
- Why: The owner asked to pick clip folders, describe the montage and get ordered extracts; each revision re-read the whole episode, so it was slow and costly.
- Must: A described montage becomes a cut list, a revision returns in seconds, unplaced quotes are listed, and results play and drag into the cut.
- Kind: ruling

### CE1-005: A meaning search named paragraphs and clips the episode does not have.
- Why: The assistant answers with paragraph references; some matched no transcript, so jumping went nowhere, and clips missing from the episode were returned.
- Must: Every result is checked against the episode's real transcripts, unknown ones dropped, shown text is the transcript's, and the count reads like "3 of 5" when some were dropped.
- Kind: situation

### CE1-007: Closing the search window abandoned a search already paid for.
- Why: The owner: on coming back "it should show that a search is still in progress if it hasn't completed yet. There should be a progress bar".
- Must: A running search survives its window closing; reopening or asking the same question rejoins it with an estimated progress bar, and results arrive without searching again.
- Kind: situation

### CE1-008: Transcript playback was slow and failed silently remotely, while the lane played fine.
- Why: The panel reloaded audio on every click, waited up to 8 s on a lookup before playing, and fell back to the full recording, about 38 times the compressed copy.
- Must: Playing from the transcript starts as fast as the lane over a slow link, never reloads the same clip or fetches a full-size file, and names any failure on screen.
- Kind: situation

### CE1-011: An interviewee vanished from the people list when their transcript could not be tied in.
- Why: One of 16 interviewees disappeared while his cards still had text, and the page blamed missing word timings.
- Must: An interviewee stays listed whatever fails with their transcript, and the page names the actual problem, such as "transcript not linked".
- Kind: situation

### CE2-072: Stepping through hits replayed the previous one and Chinese hits started early.
- Why: Each hit was cued only after a server round trip, so Space played the old cue and late answers overwrote newer ones; first-word hits played from the line start.
- Must: Each hit plays from its own first word with no round trip, even several in one card and across clips; an answer for an older hit is ignored.
- Kind: situation

### CE2-074: Nothing on the page moves by itself.
- Why: Selecting text jumped the view or scrolled away fast, the audio bar pushed content down, and after a delete the cards vanished for a second.
- Must: Selecting never scrolls beyond what the pointer asks, the player appears without shifting content, and both panels stay on screen through edits.
- Kind: situation

### CE2-080: A cut links to the paragraph it overlaps most.
- Why: Transcript paragraphs overlap their neighbours by about 5 s, so taking the first one a cut touched linked 1,050 of 2,316 cuts to the previous paragraph.
- Must: A cut links to the transcript paragraph it overlaps most.
- Kind: situation

### CE2-084: Finding words stays instant at hundreds of transcripts.
- Why: Exact find took 1.5 s per keystroke at 100 transcripts and 24 s at 520, uncancelled; the panel redraw took 255 ms for three hours of text.
- Must: Find across 500 transcripts answers within a second, a newer keystroke cancels the older search, and the transcript panel redraws within 60 ms.
- Kind: situation

### CE3-049: Search must reach every clip of the episode, not just those in the cut.
- Why: Clips the cut did not use were invisible to search; an episode can hold 200 clips and 139 MB of word timing.
- Must: Search reaches every transcribed clip of the episode and returns sentence-level spans in the language spoken, each playable and draggable onto the lane.
- Kind: situation

### CE3-052: Dropping one search result onto a cut wiped the rest of the results.
- Why: Every refresh cleared the transcript search results, and since edits answer instantly a dropped result took the others with it.
- Must: Dropping one result never silently loses the others; results stay until the person runs a new search or closes them.
- Kind: situation

See also, filed under another capability:

- CFI-099 (Timeline Cards: footage in, ready to cut): The editor found no transcripts in an episode's folder.
- CFI-106 (Timeline Cards: footage in, ready to cut): Existing transcript paragraphs went dead when timed from a second transcription.

## Chinese text and matching

### CE1-001: Written Chinese has no word spaces, even when phrases are spaced apart.
- Why: Each Chinese character is its own word; counting by spaces found 1 word in 53 on phrase-spaced Mandarin and refused every word-level cut.
- Must: Word matching, word lighting and word-level cuts count Chinese characters as words whatever spacing appears, and the playing word lights in both languages.
- Kind: given

### CE1-002: A Chinese search finds the same words in Simplified, Traditional or pinyin.
- Why: The owner: "the simp>trad agnostic search which we used to have disappeared"; the matching was missing on one install and search silently went literal.
- Must: Transcript search matches Simplified, Traditional and pinyin on every install, and if that matching is unavailable the page says so instead of quietly matching less.
- Kind: ruling

### CE1-003: An edit failed because the selection was Simplified and the timed words Traditional.
- Why: A transcript export was in Simplified characters while the timed words had been converted to Traditional, so the edit "did not go through".
- Must: Any matching of Mandarin text against timed words treats the Simplified and Traditional forms of a character as equal.
- Kind: situation

## The English a cut shows

### CE1-017: A quick machine translation is never shown.
- Why: A clip showed poor English the owner took for a web translator's fallback; he never wants to see one again.
- Must: Every English line shown comes from the transcript's own translation; no quick machine-translation draft is ever fetched or displayed.
- Kind: ruling

### CE1-018: Selecting English text acts on the matching original words.
- Why: The owner wants a selection in the translation mapped to the smallest matching span of original words.
- Must: Any English selection uses the timings of its matching original words, and a fallback to the whole sentence is labelled approximate.
- Kind: ruling

### CE1-019: The spoken word and its English equivalent light together everywhere.
- Why: The owner: "playhead over 1 word in Ukranian = that word highlighted in Ukrainian and its English equivalent"; the lit English jumped between phrases or sat words off.
- Must: With no setup the spoken word and its English equivalent light on the lane, cards and transcript, even after trims; a word with no clear English lights nothing.
- Kind: ruling

### CE1-020: A word-for-word literal English line can be toggled on under each clip.
- Why: The owner: "a purely literal translation of the foreign language which is also timed word for word for comparison and you can toggle it on and off".
- Must: A toggle, off by default, shows a literal English line under every clip, each word lit as its spoken word plays.
- Kind: ruling

### CE2-085: English leads on every card, with readable original text beneath.
- Why: The owner reads Chinese but grasps story flow faster in English; the Mandarin under it was dark, cut off on long cards, and smaller in the viewer.
- Must: English is the top highlighted line with the original beneath; the active card shows all its original text, and in the viewer both share one size and colour.
- Kind: ruling

### CE2-086: A clip's English must cover exactly its words.
- Why: A clip ending at "president Lai" showed English running past it, another dropped "slaughter" though 殺戮 was in it, and 186 of 237 re-ordered clips showed none.
- Must: Every clip shows the transcript's own English for exactly the words between its edges, for the whole episode, with no button needed.
- Kind: ruling

### CE2-087: Frame-exact cuts must never be called approximate.
- Why: Cuts whose text was matched by subtitle cue were labelled "trims are approximate", though every span was frame-exact; the owner flagged it twice.
- Must: Wording about a cut's timing describes only what is truly approximate, and matches what the send to Resolve will actually produce.
- Kind: ruling

### CE3-065: A cut shows the transcript's own English for exactly the words it plays.
- Why: The owner: "The high quality english already exists so why doesn't it just load it in", and "you adjust a clip and it just pulls out the relevant translation section".
- Must: Every cut and set-aside card, whole or trimmed, shows the transcript's own English for exactly the words it plays, never the whole paragraph's.
- Kind: ruling

### CE1-013: A cut's English covered only one of the paragraphs it spans.
- Why: An older, shorter cut's stored English, missing a phrase, was trusted over the transcript, then stored again for the longer cut.
- Must: A cut's English is built from the transcript paragraphs it spans, starting and stopping with its spoken words; older cuts' English is used only where paragraphs cannot cover it.
- Kind: situation

### CE1-014: A clip running over an interviewer's question showed no English at all.
- Why: Interview questions exist only in the timed speech, not in any transcript paragraph; the owner: "it should not refuse to show interview questions".
- Must: Words no paragraph holds show as a gap in the original language, and the rest of the clip still shows its English, marked approximate.
- Kind: situation

### CE1-015: A re-cut card showed its paragraph's whole English, which read as clips shifted.
- Why: Split, trimmed or extended cards kept the parent paragraph's English or English matched by text; the owner read the wrong line as clips "shifted by seconds".
- Must: A cut's English line translates exactly its own span, shows the original words until that exists, and adds nothing under speech already in English.
- Kind: situation

### CE1-016: Clips said "no English yet" while their English existed or was still loading.
- Why: Split and trimmed pieces never asked for their own English, English vanished a second after load, and one message covered both waiting and missing.
- Must: A cut's English appears within a frame of the edit; while being worked out it reads "loading…"; if none exists it gives the exact reason, such as "not aligned yet".
- Kind: situation

## Shortening, the edit chat and the assistant

### CE1-021: Interviewer questions are never in the film.
- Why: The owner: "no questions included in the edit ever, generate suspense by tactically withholding information"; a rule held only by asking the assistant will eventually break.
- Must: Any edit, by hand or by the assistant, that would put an interviewer's question in the cut is refused with a reason before anything changes.
- Kind: ruling

### CE1-022: The film reads as one conversation between people who never met.
- Why: The owner: people answering each other "'accidentally' is a core part of my style ... one large conversation"; suspense by withholding, partial sentences when tenser, splices highlighted.
- Must: Assisted ordering and cutting see cards in cut order and choose each as a reply to the one before; the house style is the owner's to edit per series.
- Kind: ruling

### CE1-024: When the assistant uses part of a paragraph, it highlights exactly that part.
- Why: The owner: "for splices and sections/sentences/words within a paragraph it should add a highlight to the specific bit it wants to pick out".
- Must: Any assisted edit that keeps or inserts part of a paragraph highlights exactly the words that will play, and a highlight that cannot fit never costs the card.
- Kind: ruling

### CE1-025: The edit chat proposes changes, and only the one clicked is applied.
- Why: The owner: "first gives me a suggestion (or multiple if judged useful) ... then I click which change to make, or I give it more instructions".
- Must: A chat turn shows previewed proposals and changes nothing until one is clicked, as one undo step; an impossible proposal stays with its reason; a follow-up revises proposals.
- Kind: ruling

### CE1-026: The edit chat understands "that bit ... at the playhead".
- Why: The owner: "insert that bit where [he] talks about model airplanes at the playhead", or "make the current card selection a new group".
- Must: Each request carries the playhead, selection and open transcript; the playhead's card is found from its time; inserts are real spans from any interview; an empty selection is refused in words.
- Kind: ruling

### CE1-028: Shortening only suggests; nothing changes until the editor accepts each one.
- Why: The owner: the shorten pass "must NEVER delete or stage anything by itself. It produces SUGGESTIONS ... the editor ... accepts or dismisses it individually".
- Must: Shortening to a target, editable per section, lists removals with reasons wherever the cut shows; each is accepted, undone or dismissed alone, and dismissed ones can return.
- Kind: ruling

### CE1-029: Shortening only removes, keeps sentences whole and protects the story.
- Why: The owner wanted a target length keeping structure and the most emotional content; story rules held only by asking the assistant will eventually break.
- Must: Each suggestion is checked to only remove, never a noted card or a section's last card unless the section goes whole with its heading kept, cutting at sentence ends unless justified.
- Kind: ruling

### CE2-090: The assistant keeps one warm conversation while the owner works.
- Why: The owner: "does the session stay active ... so the cached content remains cached? I don't want it to reset context every time"; search covers one or all transcripts.
- Must: Follow-ups on one cut or montage share one conversation, a reload or second browser joins it, and a forced restart says so on screen and re-sends the material.
- Kind: ruling

### CE2-091: Searching one person's interview read every transcript in the episode.
- Why: Owner: "it should only read that one relevant transcript"; a repeat search took 139 s re-sending 79% of the episode (about 145k tokens against 70k for one person).
- Must: A search scoped to one person or clip sends only those transcripts, cold or warm, and logs how much was reused and how much sent fresh.
- Kind: ruling

### CE2-092: Shortening used a massive amount of assistant capacity.
- Why: Each of about 50 calls per pass carried six transcripts and the whole cut, about 180,000 tokens; a one-person search read 322,000 characters for a 97,000-character transcript.
- Must: Each call carries only what that step needs, so a one-section or one-person request costs in proportion to that material, and each pass logs its cost.
- Kind: ruling

### CE2-094: The editor chooses which assistant model answers, and it really does.
- Why: Owner: "both panels ... sonnet/opus/fable options"; one host silently ignored the choice, so everything ran on a default.
- Must: Search and edit chat each offer a model with its price, remembered per browser, used for every call including shortening; an unknown model falls back to the default.
- Kind: ruling

### CE2-097: Shortening runs only on the sections the editor picks.
- Why: Owner: "select a section or multiple sections ... and ONLY run it against that"; he also wanted typed section targets, sticky pins and suggestions he could hide.
- Must: Every step touches only ticked sections (none ticked is the whole cut), targets are typed per section, keep or drop pins stick, and lane suggestions hide and show.
- Kind: ruling

### CE3-055: Assisted shortening shows every deletion where it was, restorable.
- Why: The owner: keep "the most emotionally powerful content"; "very sensitive", so "a doubled lane ... see all the content that got deleted and easily restore it".
- Must: Each removed passage shows where it was, playable while scrubbing, with a one-line reason and a one-click restore.
- Kind: ruling

### CE3-056: Tightening a cut keeps the best material and sets the rest aside.
- Why: The owner, cutting 160 minutes to 90: "keep only the best material that strengthens the argument and flow ... stage everything else".
- Must: Tightening to a target length keeps the strongest material and transitions and moves everything removed to the shelf, never deleting it.
- Kind: ruling

### CE3-057: Word-level cuts must name the words exactly and keep sentences whole.
- Why: The owner: "a lot of word-level and sentence-level work, so the model's understanding has to be extremely fine"; a guessed cut point is a blade in the wrong place.
- Must: A proposed cut whose words do not match the card is refused; a mid-sentence cut needs a stated reason; a splice not reading as one breath keeps the card whole.
- Kind: ruling

### CE3-058: A suggested mid-paragraph cut shows the sentence the join would make.
- Why: Removing words inside a paragraph creates a new joined sentence, which is what is really being approved and which no other view shows.
- Must: A splice suggestion shows the struck words, kept head and tail, the joined sentence and a play button, or says it cannot be previewed.
- Kind: ruling

### CE3-064: New assistant models arrive with no action from the owner.
- Why: The owner wanted each family to "move to the latest" as released, "with no action from you"; the picker had stayed on its built-in list.
- Must: Each model-family choice uses the newest model available without a code change or admin step, and a failure to stay current shows as a problem.
- Kind: ruling

### CE1-023: An assistant cut point slightly off its quoted words was refused, or guessed.
- Why: The assistant names words by position and by quote; in Chinese the position was often a character off, and a next-best guess cuts in the wrong place.
- Must: A position slightly off its quote snaps to the quoted words; words not found, ambiguous, or without word timings are refused in a sentence quoting the real words.
- Kind: situation

### CE1-027: The model a feature asks for must be the model that answers.
- Why: One route to the assistant dropped the requested model, so answers came from its default, looked plausible, and nothing showed it for six weeks.
- Must: The model a person or feature picks answers on every route, and each call records which model answered.
- Kind: situation

### CE1-030: Accepting one suggestion broke the next one on the same card.
- Why: Accepting a suggestion splits or renames the card the next suggestion is about, and the editor may hand-edit between clicks.
- Must: Each suggestion still applies correctly after others on the same paragraph were accepted or hand edits made, and undoing an accept returns it to pending.
- Kind: situation

### CE1-031: A shortened or failed section could not be cut again after a reload.
- Why: Section answers arriving together overwrote each other, rerun buttons and progress lived only in the open page, and a call hung forever across a server restart.
- Must: Every section's answer is kept with the file; any section can be cut again after reload; progress counts real running work; a call fails visibly within about eleven minutes.
- Kind: situation

### CE1-032: Keep, free or drop choices on shortening rows reverted to free.
- Why: Recalculating the length budget reused the choices from when the pass started, overwriting ones clicked later.
- Must: A keep, drop or free choice stays after every recalculation and reload until the editor changes it.
- Kind: situation

### CE2-088: The assistant was shown unavailable when unchecked or only slow to start.
- Why: "Not checked yet" was read as "not there"; on a busy server the assistant took 50 s to cold-start (30 ms warm), and a timeout was kept as "no credential".
- Must: Unchecked or slow answers use the last real check, a slow start says "too slow to start" and is re-checked within about 30 s, never reported as missing.
- Kind: situation

### CE2-089: Showing whether the assistant is available must not spend a paid call.
- Why: The availability shown on the assistant buttons is read on every page refresh, and a real probe costs one paid call each time.
- Must: Showing whether the assistant is available makes no paid call.
- Kind: situation

### CE2-093: A server-side search failed because it was handed a file path.
- Why: The request told the assistant to read a transcript by path; the assistant on the server had no file access, asked permission, and answered nothing.
- Must: Every request to the assistant carries the text it needs, never a path, and a failure shows its own sentence in the panel where it ran.
- Kind: situation

### CE2-095: The assistant was told about 40 of 120 selected cards.
- Why: The selection sent to the assistant was cut at 40 rows while its header said 120, so an edit named 40 cards as the answer for 120.
- Must: When a selection sent to the assistant is shortened, every remaining card is still listed, so the count and the list agree.
- Kind: situation

### CE2-096: Closing a tab must stop the assistant work it started.
- Why: A closed tab kept a large call running up to 15 minutes, interactive and background work shared four places, and eight lookups started 32 processes.
- Must: Closing the tab cancels its assistant work within seconds, and interactive requests never wait behind background ones.
- Kind: situation

### CE2-098: The shortened length shown must be the film's real length.
- Why: Showing the length "if every suggestion were taken" made an untouched pass look finished, and the assistant's own arithmetic missed targets by minutes.
- Must: The length shown counts only accepted removals, the offered length sits beside it, and a missed target is labelled, e.g. "lands at 3:06, asked for 3:00".
- Kind: situation

### CE2-099: After the first shortening step the owner could not find the next.
- Why: Next-step buttons sat in a hidden panel; the review used unlabelled dots and needed sideways scrolling: "I don't get how to use it."
- Must: A multi-step task's next step appears where the person asked; a finished shortening opens its review, every marker is labelled, and nothing scrolls sideways.
- Kind: situation

### CE3-059: Shortening gave no suggestions for one section and many for another.
- Why: Sections answered in parallel wrote to the same record without coordination, so some answers erased others.
- Must: When sections are processed in parallel, every section's result is kept.
- Kind: situation

### CE3-060: "Accept all" looped for ever when an item did not change.
- Why: Batch accept took the first pending item, acted and asked again; an answer that left it pending repeated it endlessly.
- Must: A batch action checks each item actually changed and stops with a message when one did not.
- Kind: situation

### CE3-061: A chat turn can take a minute, and an idle-looking box gets pressed again.
- Why: A box showing nothing for a minute invites a second send, and a sentence replayed later against a changed cut would edit unseen.
- Must: One turn at a time, the box locked with a ticking "thinking N s"; offline the chat refuses and never queues sentences for later.
- Kind: situation

### CE3-062: The assistant must never work from an outdated copy of the transcripts.
- Why: A conversation kept the transcripts and house style it opened with, so a paragraph that had since moved named the wrong words.
- Must: When transcripts or the house style change, the next request works from the new ones and says which of the two changed.
- Kind: situation

### CE3-063: An assisted edit applies whole or not at all.
- Why: Two thirds of a request carried out is not what was asked, and undoing it under later edits takes away other work.
- Must: If any step fails, every step already made is undone; undoing an assisted edit is refused once anything else has changed the cut since.
- Kind: situation

## Working offline, connections and several devices

### CE1-133: An installed web app with no declared id is identified by its start address.
- Why: Without an id in its manifest, one page at two addresses is two apps, and moving the address loses stored offline data.
- Must: The installed editor keeps its identity and offline copies under any address prefix, and the same bookmark or app opens the downloaded copy with no network.
- Kind: given

### CE2-101: A laptop's browser says "online" while the server is unreachable.
- Why: The online flag stays true while any adapter is up (a VPN's, Wi-Fi without internet), and Windows waits about 21 s per connection to an unreachable address.
- Must: Reachability is measured with a request of about 3 s deadline, never read from the online flag, and with no server the offline copy answers within about 3 s.
- Kind: given

### CE2-102: Offline use in a browser needs https or the machine's own address.
- Why: Browsers allow offline page machinery only in a secure context; plain http by IP registers nothing, while the machine's own loopback address counts as secure.
- Must: Where offline cannot work, the panel says so in a sentence instead of offering a download that cannot work.
- Kind: given

### CE2-106: Only desktop Chrome and Edge let a page keep rewriting one chosen file.
- Why: Chrome and Edge on Windows and macOS let a page write repeatedly to a file picked once; Firefox, Safari, Android and iOS browsers do not.
- Must: Any repeated save from a web page works on all these browsers, using silent overwrite only where the browser supports it.
- Kind: given

### CE2-107: iOS asks permission for every download a page makes.
- Why: Android Chrome asks once per site; iOS Safari asks before every file; iPadOS reports itself as a Mac; persistent storage is a request, not a promise.
- Must: Automatic saving is on where it is silent and off by default on iPhone and iPad with the reason shown; closing the share sheet is not an error.
- Kind: given

### CE2-108: Downloaded audio is loaded outside the page's own requests.
- Why: A media element's loading and range-seeking never pass through the page's request handling, so only a lower layer can answer them offline.
- Must: Downloaded clips play and seek offline with nothing on the wire, including after skipping between clips.
- Kind: given

### CE1-136: A downloaded cut list can be cut and listened to with no network.
- Why: The owner: "I'm about to get on a flight and I want to be able to edit offline with audio"; on Windows, a project folder separate from the browser cache.
- Must: A kept cut list is sized before download, resumes cut-short files, and opens, edits and plays offline with words and English; each offline edit lands exactly once.
- Kind: ruling

### CE1-137: Any cut list of any episode can be kept offline.
- Why: A cut list could be downloaded only while open on the server, unopened lists were not listed offline, and their queues waited until reopened.
- Must: Any cut list of any episode can be downloaded and listed offline, and its queued edits replay without it being opened first.
- Kind: ruling

### CE1-138: Working offline can be chosen while online.
- Why: The owner: "I also want to be able to enable offline mode even if I'm online, in all the apps, and in the browser."
- Must: A work-offline switch in every app and browser makes no server requests, reads "offline (your choice)", survives restart, and replays the queue when switched back.
- Kind: ruling

### CE2-110: Refreshing offline media must visibly check and report.
- Why: Owner: "It should run a check and say 'all media up to date' ... and then show the most recent time checked".
- Must: Refresh checks every downloaded clip, says "all media up to date" or names what changed, shows the last-checked time, and says when the server is unreachable.
- Kind: ruling

### CE2-111: Scrubbing and trimming use downloaded audio and need no server.
- Why: Owner: "when audio is downloaded offline the browser should use the downloaded audio instead of streaming it"; each 40 s scrub window cost 1.3 MB.
- Must: With a clip downloaded, scrubbing and trimming stream nothing and work fully offline.
- Kind: ruling

### CE2-118: Inserting a passage from a transcript failed with the server unreachable.
- Why: Insert asked the server where the passage sat, failing during a one-minute restart; owner: "This should be fully processable offline".
- Must: Inserting any paragraph the panel shows works offline from the stored transcript, within 12 frames of the online placement, approximating edges if needed and saying so.
- Kind: ruling

### CE2-124: Unsent offline edits save themselves to a file, without nagging.
- Why: The only copy lived in browser storage; owner: "local copies should save to a directory automatically"; "Downloads on laptop is fine"; the first version prompted every minute.
- Must: Unsent edits save within seconds, at most once a minute and always including the last, to one silently overwritten file, restorable without duplicating edits.
- Kind: ruling

### CE2-128: Downloaded projects sit in a readable folder chosen per computer.
- Why: Owner: "put them into a human readable projects folder" and "you can choose where a project lives per project per machine", pulling from the NAS directly.
- Must: The desktop app opens projects from the NAS and keeps each downloaded cut list as named files in a visible folder chosen per project per computer.
- Kind: ruling

### CE2-129: Two people on different accounts cut two projects at once.
- Why: The editor ran one project for the whole server; owner: "at the landing page you just select a project and then go in".
- Must: A landing page lists projects without loading any, and two people can each open and edit a different project at the same time.
- Kind: ruling

### CE2-130: Who is working in which project is shown to every signed-in person.
- Why: A review asked to hide names from the "all seats taken" message; the owner had ruled "another person being live here is something to know".
- Must: Who is in which open project is visible to all signed-in people, and messages may name them.
- Kind: ruling

### CE2-132: Phone and laptop share one draft, each keeping its own view.
- Why: Owner: "the timeline keeps appearing on the phone while the laptop is open"; he wants to "look at different sections on my phone and laptop".
- Must: Every device agrees on one cut list, while scroll, cursor, selection, playhead and view stay per device; a first visit starts at the latest place.
- Kind: ruling

### CE3-066: Whether the editor is live or on its offline copy must be obvious.
- Why: The owner: "When it's offline and online it should display so it's obvious." The only sign was muted text inside a panel.
- Must: A device holding an offline copy always shows a calm live chip or a loud offline-copy chip with waiting edits, in every view, with a message at each change.
- Kind: ruling

### CE3-067: Every transcript in the episode comes down with the offline copy.
- Why: The owner: "do transcripts also get saved offline, they should"; only the four the cut used, of forty, came down.
- Must: An offline download includes every transcript in the episode, those the cut uses first.
- Kind: ruling

### CE3-068: Keeping a cut list on the device offers to keep its video too.
- Why: The offline keep saved audio and words only; the owner asked for the preview video too, as a choice.
- Must: Keeping a cut list on a device offers an "include video" choice, and with it on the video plays offline with seeking.
- Kind: ruling

### CE3-078: The editor works over the internet on a computer without the project files.
- Why: The owner asked to use the editor remotely, including on a machine that holds none of the footage folders.
- Must: The editor opens and plays from a remote computer or phone that holds none of the project's files.
- Kind: ruling

### CE1-135: An installable editor under a sub-path claimed every page of the site.
- Why: Served under a sub-path of the dashboard, the editor declared the site root as its installed-app scope, handing every dashboard page to it.
- Must: An editor installed from a sub-path claims only that sub-path, and every link it makes works under any prefix.
- Kind: situation

### CE1-139: One slow reply flipped the page onto an offline copy hundreds of revisions old.
- Why: The owner: "the lane and the order keep jumping around"; one slow poll switched to a copy at revision 231 while the live cut was at 507.
- Must: Only a measured, repeated outage switches to offline; the copy follows every live state; an older revision never replaces a newer one; the screen says live or offline.
- Kind: situation

### CE1-140: A second queued offline edit on one cut was "no longer in the cut list".
- Why: A trim or split renames the cut it touches, so a queued edit naming the old name could not find it on replay.
- Must: Any number of queued edits on one cut replay correctly, finding the cut by its clip and span when its name changed.
- Kind: situation

### CE1-141: Offline edits must land on exactly the frames an online edit would.
- Why: In floating point 6.1 x 25 is 152.4999, so naive rounding gave one frame off; offline ripple also moved the first cut over black before it.
- Must: An edit made offline gives the same frames, gaps and leading black as the same edit online, to the frame.
- Kind: situation

### CE1-142: Where the offline copy cannot know an edit's result, the card says so.
- Why: Some offline edits, such as an insert from a transcript, can only be settled later, and showing the old words would mislead.
- Must: An offline card whose final words or span are unknown is visibly marked pending, never shown with guessed numbers.
- Kind: situation

### CE1-143: The app hung skipping clips abroad because only one clip's audio was kept.
- Why: The owner: "hanging when I skip to the next clip"; a remote link dropped every 20-60 s and only the playing clip's audio was kept locally.
- Must: The apps keep every clip's audio of the open cut list automatically, and offline, skipping between clips starts playback in under a second.
- Kind: situation

### CE1-144: Updating one episode's offline copy deleted every other episode's.
- Why: Each update replaced every stored episode page, and downloaded media was never removed.
- Must: Each episode's offline copy survives updates to the others, and downloaded media is removed when no longer needed or space runs low.
- Kind: situation

### CE2-105: Retiring or updating a page wiped other pages' offline copies.
- Why: A retired page's clean-up deleted every stored page on the site; a retired page's own copy can also hold edits not yet sent.
- Must: Retiring or updating a page never deletes anything a device saved; installed pages keep working offline, and unsent edits survive a rollback.
- Kind: situation

### CE2-112: Seeking in a large downloaded clip paused for seconds.
- Why: Downloaded recordings were 500 MB to 1 GB, and every seek read the whole stored file before serving the requested part.
- Must: A seek anywhere in a downloaded clip of any size resumes playing within a fraction of a second.
- Kind: situation

### CE2-113: The offline copy kept playing an old recording after the server replaced it.
- Why: Downloaded media is served from the device first; a re-render keeps the duration and byte length, so only the modified time differed.
- Must: A replaced source remakes its small copy and waveform, every device copy is detected stale by more than size and refetched, and the replaced clip is named.
- Kind: situation

### CE2-114: Offline downloads run only where switched on and never repeat.
- Why: The installed app's "keep what is open" download ran everywhere, ignored its off switch, and re-downloaded every video proxy every ten minutes.
- Must: Media downloads for offline use only where the person switched it on, and media already held is never downloaded again.
- Kind: situation

### CE2-115: Saving a cut list to the device froze the editor for seconds.
- Why: Checking downloaded files for the offline copy ran on the page itself, blocking it for up to 1.8 s at a time.
- Must: No background download, check or save blocks the page longer than one frame; typing, playback and scrolling stay smooth throughout.
- Kind: situation

### CE2-116: One slow answer switched the page to an old offline copy.
- Why: Any timed-out call, even a meaning search that honestly takes a minute, declared the server dead and swapped in a stale copy for 20 s, so edits looked reverted.
- Must: Only a failed short reachability check switches to offline; long requests carry no deadline; the screen never shows an older state; a live or offline marker stays visible.
- Kind: situation

### CE2-117: Undo failed offline.
- Why: Undo was refused outright while offline, and a page that lost the server answered from an old full copy, so recent edits looked reverted.
- Must: Offline undo takes back the last unsent edit, and losing or regaining the server never shows an older state than the one on screen.
- Kind: situation

### CE2-119: Refused offline edits were queued, so cards jumped and blades did not take.
- Why: Edits the device's copy refused were queued as if accepted, so the page drew its own list and cards jumped.
- Must: An edit refused while offline is shown on screen at once, is never queued, and the page returns to the device copy's list.
- Kind: situation

### CE2-120: Splitting one card twice offline made two pieces with one name.
- Why: Offline pieces were named after their parent plus a fixed suffix, so a second split collided, and the server could not find pieces it never saw.
- Must: Every offline split makes pieces with unique, repeatable identities, and on reconnect each is found by the source range it covers.
- Kind: situation

### CE2-121: One refused edit stalled seventeen queued edits for an hour.
- Why: The first of 17 offline edits failed with "'base'" and parked the rest; a refusal inside an OK answer counted as synced and was lost.
- Must: On reconnect each queued edit lands or is dropped with its reason in words, and the rest continue; only a file changed by others stops the queue.
- Kind: situation

### CE2-122: Offline edits must never be forced over others' changes, nor nag per edit.
- Why: Queued edits assume each other, so replaying onto a moved-on file builds a cut nobody made; after one "keep mine" every later edit asked again.
- Must: If the file moved on, waiting edits stop and offer keep or drop mine; one "keep mine" carries the rest, "keep all mine" exists, nothing is sent twice.
- Kind: situation

### CE2-123: An offline edit that could not be stored was shown as made.
- Why: With the phone's browser storage full, saving an offline edit failed silently and the page showed the edit as made.
- Must: If an offline edit cannot be stored, the page says so at once and the edit is not shown as saved.
- Kind: situation

### CE2-125: The phone's offline copy went blank.
- Why: A live state with no cards, naming no cut list, replaced a 251-cut download, while the picker still said 251 cuts.
- Must: A downloaded copy is replaced only by a state for the same cut list and never by an empty one, and an emptied copy says so.
- Kind: situation

### CE2-126: A 42-edit staged draft vanished in one save.
- Why: Each save replaced the draft, so an emptied draft left no trace of who or when; it came back only from the browser's own storage.
- Must: Every revision of a cut or draft is kept with its time, an emptied one is logged, and any revision can be restored.
- Kind: situation

### CE2-127: Changing where episode data lives abandoned existing state.
- Why: Moving to one storage area per episode left old settings and backups unread one folder up, with no record of which episode they belonged to.
- Must: A storage change carries existing state across before use when ownership is certain; otherwise it keeps both and names both locations to the admin.
- Kind: situation

### CE2-131: An editor working offline looked gone from their episode.
- Why: Presence was measured by server requests, so after 15 quiet minutes an offline editor looked gone, while an always-on computer kept its editor "in" for ever.
- Must: Presence follows a person actually working, offline or on a sleeping phone, and unsent work keeps an episode shown as occupied.
- Kind: situation

### CE3-069: The offline rescue copy asked to save a growing file every minute.
- Why: While offline, the browser opened a save prompt once a minute, each time a new file of 1 to 1.7 MB.
- Must: The rescue copy of unsent edits interrupts at most once per ten minutes and, where the browser allows, quietly overwrites one file chosen once.
- Kind: situation

### CE3-070: An offline session lost cuts and hid refusals when it reconnected.
- Why: Two splits of one card got the same name, refusals answered "ok", and replay failed on 17 edits.
- Must: Offline edits get collision-free names, refusals show, and reconnecting replays every edit and follows any renaming the server made.
- Kind: situation

### CE3-071: Restoring a saved file of edits must never apply an edit twice.
- Why: A restored file can overlap the edits already waiting on the device, or belong to another cut list.
- Must: A restore adds each edit once in oldest-first order, refuses another cut list's file naming both, and says how many it added.
- Kind: situation

### CE3-072: Unsynced offline work is never deleted to make room.
- Why: Storage fills up, and evicting the oldest copy would delete an editor's unsent edits; a cut list is read, not merged.
- Must: When storage is short a download is refused showing both sizes, and nothing holding unsent edits is removed without asking.
- Kind: situation

### CE3-073: Looking at download sizes started work for every clip on the server.
- Why: Asking whether each clip's audio was ready started its preparation, so opening the download panel queued about thirty jobs.
- Must: Showing download sizes starts no work; audio is prepared only when a download is actually requested.
- Kind: situation

### CE3-075: Edit plans must have exactly one stored copy.
- Why: Keeping episode files on a second box was rejected, because two synced copies of the plans file is exactly how plans get lost.
- Must: Each plan, note and draft has exactly one stored copy that every device reads and writes.
- Kind: situation

### CE3-076: Two writers of the same file erased each other's work.
- Why: Two machines each saved a shared file whole, wiping the other's additions; the cut file can also be edited by hand.
- Must: Shared files are merged on save, and a write that finds the file changed underneath it refuses rather than overwrites.
- Kind: situation

### CE3-077: An expired sign-in let the editor keep editing an old version.
- Why: The owner: "it will allow me to keep editing even though I'm not working on the latest version." Refusals looked like empty states; queued edits were dropped as landed.
- Must: When sign-in lapses or the episode closes, edits are refused with the reason and a fix, queued work is kept, conflicts go to the conflict view, recovery loads the latest.
- Kind: situation

See also, filed under another capability:

- ACC-009 (Accounts, privacy and the legal paperwork): One online sign-in every 100 days, everything else works offline.
- ACC-039 (Accounts, privacy and the legal paperwork): Any website in an editor's browser could drive programs on that computer.

## Phone and game controller

### CE2-135: Phone browsers grant full screen, vibration and install only over https.
- Why: Full screen, haptics, orientation lock and home-screen install are refused on plain http; full screen comes only inside a touch; iPhone has no full screen.
- Must: The phone editor is served over https, asks for full screen on the first touch, and works unchanged when any of these is refused.
- Kind: given

### CE2-136: Phone browsers start playback only inside a tap.
- Why: Playback started from a network reply or before audio was unlocked is refused, and full screen and orientation lock also need the user's gesture.
- Must: Playback and full screen are requested inside the touch that wants them, audio unlocks on the first touch, and any refusal is shown.
- Kind: given

### CE2-137: A phone fetches an app's install files without the sign-in.
- Why: Chrome fetches a web app's manifest and icons without cookies; behind the login they redirected, so Install made a shortcut with an address bar.
- Must: Install files and icons for every installable page load without sign-in, reveal nothing private, and the installed page opens full screen.
- Kind: given

### CE2-138: An installed app under a sub-path takes over the whole site.
- Why: An installed home-screen app whose scope is the site root claims every address on the host, including the dashboard it sits inside.
- Must: An installed editor's scope and start address are its own folder, whether served at the root or under a sub-path.
- Kind: given

### CE2-139: A phone paints an installed app's frame from its declared colours.
- Why: The address bar, splash and task switcher kept a retired grey-blue after the page became black and red; changing it restyles every installed phone.
- Must: The declared theme and icon colours match the page's current look, and changing them is treated as visible to every installed phone.
- Kind: given

### CE2-140: The Android web view lacks full screen, landscape lock and blob saving.
- Why: Android's embedded web view ignores full-screen and orientation-lock calls, cannot save blob downloads, and its request interception cannot see request bodies.
- Must: On Android, opening the lane turns the phone landscape, and saved copies land in the device's Downloads.
- Kind: given

### CE2-141: On Android 13 and later, Back left the app instead of opening its menu.
- Why: With a recent target version the back gesture never reaches the old back handler, so the only way to settings and updates vanished.
- Must: Back opens the app's menu on every Android version, and settings and update stay reachable from the page as well.
- Kind: given

### CE2-142: An Android update signed with a different key will not install.
- Why: Android refuses an update signed differently, uninstalling deletes every offline copy, and the first in-app update sends the user to "Install unknown apps".
- Must: Every Android release is signed with one key kept for the app's life, so an update never forces an uninstall that loses offline work.
- Kind: given

### CE2-143: iPhones ignore a page's request to lock to landscape.
- Why: Android Chrome honours full screen and a landscape lock asked inside a tap; iOS refuses the lock, leaving a 390 px wide portrait screen.
- Must: The lane works on a 390 px portrait screen when the lock is refused, and the editor is told once, not every time.
- Kind: given

### CE2-144: Web drag and drop does not exist on iPhones.
- Why: iOS browsers fire no native drag events, so dragging cards needs touch gestures such as hold, tap to pick up and tap a gap.
- Must: Every drag action, including filing a card into a category, has a touch way that works on iPhone and Android.
- Kind: given

### CE2-145: On Android a long press fires the same event as a right-click.
- Why: A long press meant to open a transcript or move a clip opened the right-click colour picker under the finger.
- Must: Every touch gesture has exactly one meaning in each phone view, and nothing that means right-click is reachable by a long press.
- Kind: given

### CE2-146: Android Chrome with "Desktop site" on reports 980 px wide.
- Why: The owner's phone has Desktop site on, so a width test served it hover-only controls, a tiny gear, and a lane strip with cards behind.
- Must: The phone layout is chosen from a touch pointer that cannot hover, not width alone, with a remembered manual override.
- Kind: given

### CE2-147: A window dragged between monitors briefly reports a narrow width.
- Why: On Windows, moving between monitors of different scaling briefly reports a narrow width, and the page flipped to phone layout for good.
- Must: A brief width change never switches layout; the switch waits, uses different in and out widths, and leaving it restores the desktop layout exactly.
- Kind: given

### CE2-148: Chrome on Android raises its own word overlay over any selection.
- Why: The "explore this word" panel and copy toolbar appear over a native selection, and a page cannot dismiss, move or restyle them.
- Must: On touch, nothing outside text boxes is natively selectable; the transcript has its own word selection with draggable handles, double tap for a line, and its own copy button.
- Kind: given

### CE2-161: Browsers hide a game controller until the page is touched.
- Why: Chrome, Edge and Firefox on Windows and Chrome on Android map an Xbox pad alike, but report one plugged in before load only after a key or click.
- Must: The page tells the person to press a button if no controller shows, a stick acts only after passing centre once, and missing vibration causes no error.
- Kind: given

### CE3-084: Chrome blocks phone vibration until the page has had a real tap.
- Why: Chrome refuses a page's vibration request, logging an error, until the page has received a genuine tap.
- Must: Haptic buzzes are optional: a blocked vibration never shows as an error and never changes what the action does.
- Kind: given

### CE3-085: Chrome keeps Ctrl plus a digit for its own tabs.
- Why: In a normal Chrome tab Ctrl+1 to Ctrl+8 switch browser tabs and never reach the page; in an installed app window they arrive.
- Must: No in-page shortcut depends on Ctrl plus a digit.
- Kind: given

### CE1-103: Each cut edge has its own controller control, wherever the playhead is.
- Why: Picking trim or extend by where the playhead sat made extending unreachable; the owner chose "one control per edge, one meaning per modifier, no rule about where the head is".
- Must: A bumper tap trims that edge to the head, and a held bumper with the right stick drags that edge either way, regardless of the playhead.
- Kind: ruling

### CE1-104: On the controller, Y picks a clip and LT plus Y selects back to it.
- Why: The owner: "press y to select one clip, move along the timeline any number of clips, press lt + y once again and it selects everything"; it deselected instead.
- Must: Y anchors a clip; LT plus Y selects every cut from the anchor to the head in either direction; the pad's own steps keep it; B clears it.
- Kind: ruling

### CE1-107: Selected clips can be carried a long way with the controller.
- Why: The owner wanted LT held and the right stick pushed to run a between-clips marker away from the selection, faster the harder he pushes.
- Must: With clips selected, LT plus the right stick moves a landing marker gap by gap, faster with more push; releasing LT drops them there as one undo.
- Kind: ruling

### CE1-108: The right stick is precise at small pushes and stops dead on release.
- Why: The owner: "the right stick should be a little more precise at low movement levels"; jog speed rose in a straight line from the dead zone.
- Must: A quarter push jogs about 0.09x, rising smoothly to 1x and 8x at full push; releasing any jog, pan or scrub control stops on that frame with no coasting.
- Kind: ruling

### CE1-109: A double Y opens the cut in its transcript.
- Why: Only a double-click opened a lane clip in the transcript, which a controller lacks; the owner: "it should be double y to open that clip in its transcript".
- Must: A second Y on the same cut within about half a second opens its paragraph in the transcript, opening its interview first; a single Y still selects.
- Kind: ruling

### CE1-110: The controller drives the transcript like the timeline.
- Why: The owner: "move the playhead with right stick, then hold lt and move right stick to make selection", then a button inserts after the selected card.
- Must: The pad acts on the focused pane; in the transcript the right stick steps word by word, LT plus stick selects, and LT plus X inserts after the selected card.
- Kind: ruling

### CE1-111: On a phone the lane is absolutely full screen.
- Why: The owner: "on mobile the lane should still be absolutely full screen, no cards behind it"; over-scroll showed the list under it.
- Must: On a phone the lane covers the view above the bottom bar, and no scroll or over-scroll reveals the cards.
- Kind: ruling

### CE1-112: On a phone a long press lifts a card to reorder it.
- Why: The owner: "no way to reorder cards on mobile, long press opens the transcript page"; the transcript should still open at any time.
- Must: On touch a long press lifts a card for dragging with edge auto-scroll, and the transcript opens from a button on the card or the bottom bar.
- Kind: ruling

### CE1-113: The phone edit view shows the whole current cut and the word being heard.
- Why: The owner: "you should be able to see all the text, and it should highlight which word you are currently over".
- Must: The row under the playhead shows its full text, scrollable within the row, lights the current word, and says "no word timing" when there is none.
- Kind: ruling

### CE1-114: In the phone edit view only a dial strip on the right moves the playhead.
- Why: With the playhead on a one-finger drag, every brush while reading moved it; the owner then moved the dial from the left edge to the right.
- Must: Only the right-edge dial, finer further from the edge, moves the head; a tap plays or pauses; controls sit beside it, never over text; cards show only their English.
- Kind: ruling

### CE1-115: A double tap picks up a cut to move it on the phone.
- Why: The owner: "you should be able to move cards in the edit tab by double tapping them"; a single tap's play now waits 300 ms for a second tap.
- Must: A double tap picks up a cut; a tap on another cut's top or bottom half drops it before or after; tapping it again or leaving the tab lets go.
- Kind: ruling

### CE1-116: On a phone an edge trim takes a tap to arm, then a drag.
- Why: The owner: a drag starting at a clip edge must not trim; tap the edit point first, then drag; a plain drag pans and coasts longer, about 4.8 s.
- Must: On touch a drag trims only after a tap armed an edit point, also under a marker flag, where a hold instead picks up the marker.
- Kind: ruling

### CE1-117: Holding the play button plays at double speed.
- Why: The owner: "in lane mode if you hold down play pause button it should 2x playback", the same as holding Space.
- Must: A tap on play toggles once; holding it plays at 2x, and release returns to the previous speed, stopping if it was stopped before.
- Kind: ruling

### CE2-149: The editor apps update themselves from inside the app.
- Why: The owner: "make the app installable inside the app, without needing to get pushed over adb", on Windows and Android.
- Must: Each app checks, downloads, verifies and installs its own update from its settings, keeping its settings and offline copies.
- Kind: ruling

### CE2-150: On a phone the card text gets nearly the whole width.
- Why: The owner asked that unselected phone cards show only text and one line of name and number, margins cut to a few pixels.
- Must: On a phone an unselected card has no buttons and one non-wrapping meta line; the selected card offers its actions as 44 px buttons.
- Kind: ruling

### CE2-151: On the phone the playhead chooses which edge a held drag trims.
- Why: The owner: playhead in the first half of a card and hold-drag trims the start; in the second half, the end.
- Must: A press held past 280 ms trims or extends the edge nearest the playhead, by the same rules as the desktop lane.
- Kind: ruling

### CE2-152: On a phone the insert sheet belongs to the transcript view only.
- Why: Owner: "this insert overlay should never appear anywhere except the transcript page"; on Android the action bar sat under the header, beneath Chrome's copy menu.
- Must: On touch, a transcript selection's actions sit in a bottom sheet shown only with the transcript, saying where the cut landed; the bottom bar names the view shown.
- Kind: ruling

### CE2-162: Everything but typing a search word works from the controller.
- Why: The owner: "The only touch I want to make to the keyboard is typing the actual input term to the find box."
- Must: Switching panels, finding, walking and playing matches, choosing a transcript and inserting clips all work from a game controller with no mouse or other keys.
- Kind: ruling

### CE2-163: The controller drives the transcript with the lane's own buttons.
- Why: Owner: "keep the transcript controls as similar as possible to the lane controls so I dont have to memorise a new set of mappings".
- Must: Every button does the same job on the transcript as on the lane, applied to text, a right-stick playhead included, and one button switches lane and transcript.
- Kind: ruling

### CE2-164: On a controller, a clip edge is dragged by holding a trigger.
- Why: The owner: "Maybe LT pressed down and right stick left or right to extend or shorten the current clip under the playhead".
- Must: Holding a shoulder button and moving the right stick extends or shortens the clip under the playhead, rippling what follows.
- Kind: ruling

### CE2-165: Controller fades move one frame per tap.
- Why: The owner asked for fades on the controller: "yep build that, but it's a frame per tap".
- Must: Holding a shoulder button and tapping the D-pad lengthens or shortens the clip's fade by exactly one frame per tap.
- Kind: ruling

### CE3-086: The phone edit view must stay full screen the whole time.
- Why: The phone's address bar and system bars come and go, changing the view's height mid-drag; the owner: "remains full screen constantly", "android only required".
- Must: On Android the edit view runs with no browser or system bars, in portrait, with fixed geometry, installed as an app or by asking on the first touch.
- Kind: ruling

### CE3-088: Controller zoom keeps the view's centre; holding L3 aims a playhead jump.
- Why: The owner wanted zoom not tied to the playhead, a jump to "whatever I'm looking at", and the marker shown only while L3 is held: "it's distracting".
- Must: Controller zoom keeps the view's centre; holding L3 shows the centre marker, panning moves it, release moves the playhead there; nothing shows otherwise.
- Kind: ruling

### CE1-102: Controller edits must be safe from the sofa.
- Why: With no mouse the playhead is the only pointer, and a stale selection or stray press could delete or send the wrong thing.
- Must: A refusal buzz always matches the on-screen message, typing in a box ignores the pad, and sending a cut to Resolve is never on the pad.
- Kind: situation

### CE1-105: Moving a clip twice on the controller moved its neighbour instead.
- Why: After a move the playhead stayed put, so a different clip slid under it and the next move grabbed that one.
- Must: After a controller move the head stays on the moved cut, so repeating the move keeps moving the same cut.
- Kind: situation

### CE1-118: On a phone, card text ran 1,638 pixels wide off a 412-pixel screen.
- Why: Card text, details and options ran unwrapped off the right edge, and short cuts with long clip names spilled 300-400 px past it.
- Must: On a 390 to 412 pixel screen, at every zoom, no card, details line or panel is wider than the screen; text wraps and long names end in an ellipsis.
- Kind: situation

### CE2-153: The lane's button bar does not fit a 390 px phone.
- Why: Nine lane buttons needed 414 px, then 419 px, and bigger thumb targets made 427 px, pushing the close button off a 390 px portrait screen.
- Must: Every control bar, close included, fits and can be tapped on a 390 px portrait phone without clipping or sideways scrolling.
- Kind: situation

### CE2-154: Phone taps seemed dead because panels opened behind a drawer.
- Why: "Download for offline" opened behind the full-screen settings drawer with silent failures, a drawer covered its own close, and Android back left the editor.
- Must: An open drawer always shows a way to close it, Android back closes it, nothing opens underneath it, and every failure says why.
- Kind: situation

### CE2-155: "Pressing delete on mobile seems to do nothing."
- Why: Delete armed on first tap but said so on a scrolled-away line, and the next refresh erased the warning, so three seconds ran out invisibly.
- Must: An armed delete shows a countdown on the button under the finger, and no refresh erases an arming or confirmation within six seconds.
- Kind: situation

### CE2-156: The editor pressed the blade 36 times because nothing showed it took.
- Why: Edits refused while another was in flight or with nothing selected said nothing, and refusals looked like confirmations.
- Must: Every press visibly registers at once, each refusal says what happened and the way out, styled as a refusal and near the finger, and identical repeats collapse to one.
- Kind: situation

### CE2-157: The installed app always opened on the same episode.
- Why: Installing from an episode page made it the app's home, and a phone keeps that home until the app is removed and reinstalled.
- Must: The installed app opens on the episode list wherever it was installed from, and every episode stays inside the app.
- Kind: situation

### CE2-158: With no network the installed app sat on its splash screen.
- Why: Nothing answered the app's home page offline, so a phone in aeroplane mode, or on a VPN with no route, showed nothing, not even saved cut lists.
- Must: Offline, the installed app shows the last episode list within about 8 s, marks cut lists saved on the device, and opens them.
- Kind: situation

### CE2-159: An installed phone app failed after a server restart.
- Why: The app's files answered "not open" until someone opened the episode on the server; changing the app's identity later forced reinstalls.
- Must: An installed app starts after a server restart with nobody opening anything first, and its identity never changes.
- Kind: situation

### CE2-160: An installed copy of the editor can sit on an old version silently.
- Why: An installed web app keeps its saved page; with an expired sign-in the update check got the login page and the old version stayed.
- Must: A republished editor replaces the installed copy on next open, and an outdated installed copy is never kept silently.
- Kind: situation

### CE2-166: A sleeping controller must not pull the cursor out of a text box.
- Why: Wireless controllers disconnect when idle, while a person may be typing in a box.
- Must: A controller disconnecting never moves focus or the text cursor out of a box being typed in.
- Kind: situation

### CE3-087: Android's back gesture means "back to the cards" from every full-screen view.
- Why: Phone views had four different ways out.
- Must: Back from any full-screen phone view returns to the cards without piling up history, and back from the cards leaves the page.
- Kind: situation

### CE3-089: The controller never sends a cut, and a text box takes it over.
- Why: Sending to Resolve and switching modes stay on the keyboard, and typing in a box must not trigger edits.
- Must: No controller input sends to Resolve, and while a text box has focus only the controller's leave, step and play buttons act.
- Kind: situation

### CE3-090: A held controller button keeps driving where it started after focus moves.
- Why: Focus could switch between lane and transcript under a held trigger or bumper, so a shuttle or edge drag acted on the wrong place.
- Must: A hold acts only on the place it started in, until released, whatever focus does meanwhile.
- Kind: situation

### CE3-091: Leaving the transcript took one controller press, coming back took two.
- Why: The controller's panel button cycled through three panels.
- Must: One controller press moves from the transcript to the lane, and one press moves back.
- Kind: situation

## Speed and smoothness

### CE2-167: Chrome slows sharply drawing thousands of thin bars as one shape.
- Why: A waveform of about 1,900 one-pixel bars in one canvas shape left the fast path past about 1,000 px wide: 0.19 ms became 1.5-3 ms a frame, invisible to page timers.
- Must: Lane drawing cost stays flat at every zoom with real waveforms and Resolve sharing the GPU, measured with the browser's GPU trace at editors' real zooms and screens.
- Kind: given

### CE2-168: A filter on the page body makes fixed panels jump and vanish.
- Why: In browsers a filter on the body makes it the containing block for fixed elements, so a hover effect pinned the docked lane 44,000 px down or made it flicker.
- Must: The lane and header stay exactly where docked in every hover and panel state, and nothing above the cards shifts on scroll.
- Kind: given

### CE2-169: A laptop's browser draws on integrated graphics, and switching changed nothing.
- Why: Chrome on a Windows laptop with switchable graphics used the integrated chip; the slow work was on the CPU, so the discrete GPU did not help.
- Must: Drawing performance targets a laptop's integrated graphics and is fixed by reducing work, never by asking the person to change graphics settings.
- Kind: given

### CE2-170: Frame rates seen over Remote Desktop are not the real speed.
- Why: A Remote Desktop session displays at 32 Hz, and the browser's unlocked-frame test settings held it near 60 fps on a 144 Hz screen.
- Must: Smoothness is judged from the app's own frame timings on the machine itself at the screen's real refresh rate before it is called done.
- Kind: given

### CE1-068: Every edit must feel instant, a split included.
- Why: Edits waited for a slow confirmation and greyed the list: over 2 s, then 500-600 ms per edit from the phone; a split alone waited a 300-700 ms round trip.
- Must: On a 433-cut project every edit, split included, is drawn within about 100 ms and saved behind it, greying nothing; a refusal takes it back with the reason; selection survives undo.
- Kind: ruling

### CE2-171: Seeking, playback and lane zoom stay "butter smooth" at 100 frames a second.
- Why: Owner: "locked 100fps+"; on a 4K 150% laptop zoom frames took 65-217 ms with 1000 cuts, a held-stick zoom ran 5 fps, and arriving translations triggered rebuilds.
- Must: During seek, playback, scroll and zoom, with 1000 cuts on a 4K screen and words still arriving, no frame takes longer than 10 ms on the studio's computers.
- Kind: ruling

### CE1-069: Edits grew slow on a 500-minute, 1,500-card cut.
- Why: A trim near the start ripples every later card, and each reply resent all of them whole: 2.3 MB against 27 KB near the end.
- Must: An edit's reply carries only what changed, so a trim at the start of a 1,500-card cut appears as fast as one at the end.
- Kind: situation

### CE1-070: Rapid edit keys silently did nothing.
- Why: A status update arriving just before an edit's confirmation faked it, so the page fell behind and refused later edits with no message.
- Must: Every edit gesture takes effect or shows why it was refused, and rapid successive edits are all applied in order.
- Kind: situation

### CE1-071: Edits were refused at random as "the timeline changed", then went through.
- Why: Background work republished the cut every 12 s without moving any card, including in the first seconds after opening, and 8 of 50 moves were refused.
- Must: An edit is refused only when the cut's cards, order or timing really changed since the page saw it, and every page converges on the saved cut.
- Kind: situation

### CE1-072: No refused edit may be silent, on any device.
- Why: Splits refused on a phone showed nothing, refusals in a read-only view were dropped, and raw server errors reached the page verbatim.
- Must: Every refused edit shows a plain sentence saying why on the device it came from, nothing changes, and technical detail sits behind a disclosure.
- Kind: situation

### CE1-073: The card list ignored the mouse after an action, while keys still worked.
- Why: A busy state set during apply, undo and outside updates was never cleared on success, so every click did nothing until a reload.
- Must: Whenever an edit, apply, undo or outside update finishes or is refused, the list answers mouse and touch again at once.
- Kind: situation

### CE1-074: Opening a cut, or making one from a board, took seconds.
- Why: Opening cut lists was "extremely slow", and making a new cut from a large planning board took almost ten seconds.
- Must: Opening a cut list or creating one from a board takes about one second at most on a typical episode.
- Kind: situation

### CE1-075: Results finished in the background stayed invisible until the next edit.
- Why: A finished search was stored without telling the page, which refreshed only when something else changed: "it worked now, oddly".
- Must: A background job's completion appears on the page within seconds with no other activity.
- Kind: situation

### CE1-076: Anything not ready on first ask was never asked for again.
- Why: Audio, waveforms and card words answered "still preparing" at first, especially after a restart, and views never asked again, staying silent, grey or "no transcript".
- Must: Every view keeps asking until the audio, waveform or words it needs exist, then shows them and starts playback, with no refresh.
- Kind: situation

### CE2-172: The cut view must stay smooth on a phone at 500 cards.
- Why: Every change rebuilt every row, 5,000 elements at 500 cards: 23 ms on a desktop and an estimated 90-140 ms on a phone.
- Must: At 500 cards one change updates the edit view on a mid-range phone within one frame (16 ms).
- Kind: situation

### CE2-173: Opening a big episode ate a server core for seconds.
- Why: An episode of 1,166 cards and 114,245 words cost seconds of server CPU per page open, slowing everything else the server did.
- Must: Opening or editing the largest episode never makes other dashboard requests or reports wait.
- Kind: situation

### DSH-129: Each edit in the editor recomputed the whole cut.
- Why: Recomputing every card's words after each edit took 4 s at 97% of a core.
- Must: Work done per edit scales with the edit, not with the whole cut.
- Kind: situation

## The page: panels, header, warnings and redrawing

### CE3-100: One raw control character in page code kills the whole page in browsers.
- Why: A raw NUL byte in an inline script passes checks outside a browser, but the browser's HTML parser turns it into U+FFFD and the page's script dies at load.
- Must: Page sources are checked for raw control characters, and the editor is tested loaded in a real Chrome and Safari before release.
- Kind: given

### CE1-119: On desktop the transcript opens beside the cards, never over them.
- Why: The owner preferred the page "split when you open" the transcript, not a panel floating over the cards; on a phone the panel is a full-screen pane.
- Must: On desktop an opened side panel sits beside the cards, which reflow, and never covers them; on a phone it takes the screen and has its own close.
- Kind: ruling

### CE1-120: Opening one panel never changes another panel's width.
- Why: The owner: "which panels are open should not affect other panels width"; a hidden overview widened everything and the shortening panel squeezed the cards.
- Must: Each panel keeps its own width to the pixel when others open or close, a hidden panel changes nothing, and only the card column grows or shrinks.
- Kind: ruling

### CE1-122: Panels tab, dock and resize like After Effects.
- Why: The owner: the transcript is "the second most important after the lane, but ... an afterthought"; panels should "drag them out and dock them like AE does".
- Must: Cards, transcript, staged and video panels can be tabbed, docked side by side and resized, the layout is kept per device, and bottom bars take minimal height.
- Kind: ruling

### CE1-123: The timeline sits at the top by default.
- Why: A rebuilt editor put the timeline at the bottom; the owner asked for it at the top like the original.
- Must: The timeline is docked at the top by default, and a person's own choice of position is kept.
- Kind: ruling

### CE1-124: Each panel can pop out to another screen, one copy each, synced instantly.
- Why: The owner: "there should only ever be allowed to be one instance of each thing", and updates between windows "should be instant".
- Must: Popping a panel out moves it to its own window, one per panel; selection, playhead and edits reach every window within a frame; one control brings everything back.
- Kind: ruling

### CE3-092: The desktop editor is one whole window, like Resolve.
- Why: The owner: "like it's one whole window, somewhat like resolve": no system title bar, the header is the drag area.
- Must: The desktop editor shows as one window whose header doubles as its title bar, with the window buttons in the editor's colours.
- Kind: ruling

### CE3-093: The header stays on one line, and long names shorten.
- Why: Added buttons wrapped the header onto several lines; a long timeline name pushed controls off the page and left a blank strip at the bottom.
- Must: The header stays one line at desktop widths, long names end in an ellipsis with every control visible, and content fills the window.
- Kind: ruling

### CE3-094: The audio preview bar matches the page and appears only when needed.
- Why: The owner found the player "really ugly", always shown, cut off at the top; he wants it dark blue, semi-transparent, with a neon azure seek bar.
- Must: The player animates in only while audio is wanted, sits under the insert bar below the header, and deselecting text hides the insert bar.
- Kind: ruling

### CE3-095: Standing warnings must not pop up and shift the page.
- Why: The owner: "having it constantly pop up and shift the main screen around is highly annoying"; cards also showed "through the top here in a slit."
- Must: Ongoing conditions go to a problems window; only a failed edit or send shows on the page; nothing above the cards moves or lets cards show through.
- Kind: ruling

### CE1-121: No mix of open panels may crush the cards or scroll sideways.
- Why: Fixed-width panels let three open panels squeeze a laptop's cards to nothing, and a phone page once scrolled sideways.
- Must: At 1440x900 and 412x915, every combination of open panels keeps the card column above its minimum and the page never scrolls horizontally.
- Kind: situation

### CE3-096: Hovering a menu entry made the whole menu judder.
- Why: Hovering made a status line wrap onto two lines, and a list redrawn from scratch on each refresh jumped under the mouse.
- Must: Hovering never changes another element's size or position, and an open list that refreshes updates in place.
- Kind: situation

### CE3-097: Background updates made the page choppy and the lane flash.
- Why: Each arriving answer rebuilt all 519 cards, 29 times in 12 s with 130 to 160 ms gaps; the shortening panel redrew the lane 22 times where 1 was needed.
- Must: Background answers update only the cards they concern, and a side panel redraws the lane only when what the lane shows has changed.
- Kind: situation

### CE3-098: A page must never flash another timeline's cards.
- Why: Opening a cut list could briefly show cards remembered from another timeline before its own loaded.
- Must: An editor page shows only its own cut list's cards, never another's, not even for a moment while loading.
- Kind: situation

See also, filed under another capability:

- ALL-026 (The whole product): The owner: every app reached from the dashboard has a way back to it.

## Opening episodes and keeping the editor running

### CE1-125: The project is the episode; cut lists are members inside it.
- Why: The owner: a cut's name "is not a project name"; "'Project' should be the name of the episode root".
- Must: The header reads "episode · open cut" with recent episodes; switching opens the last cut or a picker of that episode's own cut lists only.
- Kind: ruling

### CE1-128: Two people can work in two different projects at once.
- Why: The owner ruled that people drive only the computers signed in to their own account; one account may also use a laptop and a phone.
- Must: Each person picks a project from a landing page, and their edits reach only Resolve on their own signed-in computers, with no studio-wide lock or hand-over.
- Kind: ruling

### CE3-101: The episode picker looks like the studio's folders, recently opened first.
- Why: The picker was one flat table; the owner asked for the year and show folders, "ordered by most recently opened instead of date".
- Must: Episodes show in their folders in the person's last-opened order, filter by year, sort by last opened, size, date and name, search by keyboard, and remember open folders.
- Kind: ruling

### CE3-106: A cut list opened read-only must never write to the real project.
- Why: The owner: "let me test it on a live [project], don't replace the current [editor]"; a read-only copy nearly wrote an empty word file over the real one on close.
- Must: A cut list opened read-only is read from the real project but nothing is written to it, and two versions never drop each other's data.
- Kind: ruling

### CE1-126: After switching episode, lists still showed the previous one.
- Why: The switch answered before taking effect and old lists stayed cached, so the page kept the old cuts and interviewees, and a just-created cut list never showed.
- Must: After a switch nothing from the previous episode shows anywhere, a new cut list opens without reload, and the last episode and cut are remembered across restarts.
- Kind: situation

### CE1-127: Switching cut lists within an episode cost a restart and a 12-second reload.
- Why: Opening another cut list of the same episode threw away loaded transcripts, audio and translations and paid a 12 s cold load.
- Must: Switching cut lists within an episode keeps everything loaded, and an episode reopens on the cut list last left on.
- Kind: situation

### CE1-129: With Resolve closed, the page went blank and edits hung for minutes.
- Why: The page needed a live Resolve to show anything; closing Resolve blanked it, and edits waited eight minutes before failing.
- Must: Whatever came from Resolve stays on screen marked stale since when; edits needing Resolve are refused at once with the reason; a missing Resolve is a soft note.
- Kind: situation

### CE1-130: An open editor page stuck after the server restarted.
- Why: A page left open across a server restart stopped working until it was reloaded.
- Must: An open editor page reconnects by itself after a server restart, without a manual reload and without losing work.
- Kind: situation

### CE1-131: After every server restart the assistant showed as unavailable.
- Why: The assistant's sign-in state lived only in memory, and the reason showed only in a hover tooltip, which a phone cannot show.
- Must: A signed-in assistant shows available straight after a restart, and any reason a feature is unavailable is printed on screen, never only in a tooltip.
- Kind: situation

### CE1-132: A feature that could not run hid its reason where the next edit overwrote it.
- Why: With the assistant unavailable, search and summaries failed and the error showed in one shared message line that the next edit replaced.
- Must: A feature that cannot run shows its reason on its own control, and the message stays until it can run.
- Kind: situation

### CE2-174: An episode that failed or hung while opening could never open again.
- Why: A failed open was remembered for good, and a hung read showed "opening" for ever while holding one of the limited places.
- Must: Opening an episode has a time limit, a failure shows a plain reason, and the episode can be retried.
- Kind: situation

### CE2-175: Closing an episode leaked about 128 MB until memory ran out.
- Why: Closing an episode left its background work and memory behind.
- Must: Closing an episode frees everything it used, so opening and closing episodes for days never exhausts the server.
- Kind: situation

### CE2-176: Edits silently did nothing, or the page waited forever on one.
- Why: An editing worker that died at start made every reorder and trim do nothing, and a server restart mid-edit froze the page on "an edit is still going through".
- Must: An edit that cannot be applied says so within seconds, and a server restart mid-edit never leaves the page waiting forever.
- Kind: situation

### CE2-177: The editor's server vanished and had to be restarted by hand.
- Why: The owner found the service behind the editor gone more than once, and asked for a Start menu shortcut and a restart button.
- Must: The editor comes back by itself after it stops, and nobody ever needs a terminal to start or restart it.
- Kind: situation

### CE3-102: The episode list was empty on the studio's real folder layout.
- Why: Episodes sit four levels down (share, year, show, episode); the scan stopped at three and tests used two, and an empty list looked legitimate.
- Must: The episode list reaches the depth the studio really uses, is tested on that real layout, and an empty list says where it looked.
- Kind: situation

### CE3-103: One passing failure left an episode or transcript unusable until restart.
- Why: A failed open (NAS share not up yet) marked the episode failed until redeploy; a swallowed transcript read failure left every clip's transcript empty.
- Must: A failed open or read is shown, retried (opens spaced about 20 s apart), and one unreadable clip never stops other transcripts loading.
- Kind: situation

### CE3-104: After switching episode the panel claimed there were no documents.
- Why: Switching episode cleared the document list, but a refresh throttle blocked the refetch for 30 seconds.
- Must: Switching episode refreshes the document list at once, and a failed fetch is never shown as "none".
- Kind: situation

### CE3-107: When the server stops, open cut lists are saved first.
- Why: The server gets 10 seconds to stop, but about 20 seconds of other shutdown steps ran before open cut lists were saved, so that step was killed.
- Must: On a normal server stop, every open cut list is saved first, within the stop grace period.
- Kind: situation

## Resolve is optional

### CE3-079: The editor is standalone, with Resolve as a secondary feature.
- Why: The owner: drafting without Resolve is "by far the most useful mode"; "this can run without a timeline, run entirely without resolve"; "waiting for the Resolve agent" read as a fault.
- Must: Every editing feature works with Resolve closed or absent and nothing shows as a fault; sending to, importing from and following Resolve are separate commands.
- Kind: ruling

### CE3-080: The editor must not jump to Resolve's active timeline on load.
- Why: Refreshing switched to whatever timeline Resolve had active; the owner: it "should reopen to the same previously open project" and "default on load should be follow off".
- Must: On load or refresh the editor reopens what was last open in that episode, and following Resolve is off until switched on.
- Kind: ruling

### CE3-081: Scrolling never switches following off; one key in Resolve switches it on.
- Why: The owner asked that a key pressed in Resolve turn following on and jump to the current card; he later ruled that scrolling must not turn it off.
- Must: Every way of scrolling leaves following on; it changes only through its own control or the key in Resolve, which also brings the current card into view.
- Kind: ruling

### CE3-082: Following failed to bring a new playhead card into view.
- Why: A guard against retrying a stuck scroll compared only the scroll position, so a new card at the old position was never scrolled to.
- Must: With following on, every change of the card under the playhead brings that card into view.
- Kind: situation

### CE3-083: A person's key preset vanished after restarts, with no message.
- Why: The preset was not stored, and when no computer could drive Resolve for the page, only a log said so.
- Must: A person's key preset survives restarts, and when no computer can drive Resolve for the page, the page says so.
- Kind: situation
