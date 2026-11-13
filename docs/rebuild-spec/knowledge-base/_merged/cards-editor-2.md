# Timeline Cards: the editor (piece 2)

## The lane: clicking, trimming and dragging

### CE2-001: The lane must handle like Resolve's own timeline.
- What was going on: The owner asked for Alt plus wheel to zoom "to match resolve", centred waveforms, the playhead following a ripple trim, and no momentum when panning.
- What the product must do: The lane uses the editor's own Resolve keyboard preset (Resolve's defaults otherwise), Alt+wheel zooms, ripple trims carry the playhead, waveforms sit centred, and panning stops with the mouse.
- Kind: 2
- From: P08-026, C04-074

### CE2-002: The lane plays the whole cut and edits exactly like the cards.
- What was going on: The owner asked for a resizable strip under the cards, with waveforms and each clip's words wrapped inside, for listening through and editing.
- What the product must do: The lane plays every cut in order, wraps clip words with an ellipsis when cut off, can be resized, and any edit made there matches the same edit made on the cards.
- Kind: 2
- From: P07-071

### CE2-003: Clicking a clip selects it and never moves the playhead.
- What was going on: The owner: "Sometimes you want to select a clip but leave the playhead elsewhere"; a click used to select and seek too.
- What the product must do: A click or tap on a clip only selects it, leaving playhead and view still; only the ruler, empty timeline or a dedicated key moves the playhead.
- Kind: 2
- From: D03-010, P16-015, P08-024

### CE2-004: Clicking a long clip while zoomed in made the lane jump away.
- What was going on: The lane re-centred whenever either edge of the clicked clip was off screen, which when zoomed in is every long clip.
- What the product must do: Clicking a clip moves the lane only when the whole clip is off screen; otherwise the frame under the pointer stays put.
- Kind: 3
- From: L05-031

### CE2-005: Zoomed out, drags grabbed the wrong clip or resized it.
- What was going on: At low zoom a press landed some pixels from where clips were drawn, and trim handles covered tiny clips entirely, for single and multiple selections.
- What the product must do: At every zoom a press acts on the clip drawn under the pointer, and a clip narrower than 24 px moves rather than trims.
- Kind: 3
- From: C06-086, P16-035

### CE2-006: Selecting several clips did not work and outlined the whole timeline.
- What was going on: Ctrl+click, Shift+click and box selection did not select several clips, and Shift+click drew a blue outline round the timeline.
- What the product must do: Ctrl+click, Shift+click and a drawn box select several clips, each selected clip is visibly tinted, and they drag as one group.
- Kind: 3
- From: P16-010

### CE2-007: Dragging a clip edge outward must lengthen it and show the words added.
- What was going on: The owner: "I still can't drag a clip out"; an outward drag was refused, and extending showed nothing of "what words you're adding to the edit".
- What the product must do: Dragging an edge outward extends it from its source, showing live the new extent and words; it is refused only when the source has nothing left, with the reason.
- Kind: 2
- From: P08-021, D03-011

### CE2-008: Extending over the next piece of the same recording is allowed.
- What was going on: Dragging an edge over the neighbouring cut from the same source raised a refusal; the owner said "allow it".
- What the product must do: A clip can be extended over material its neighbour also uses, with no refusal; the overlap then plays twice.
- Kind: 2
- From: P16-023, C06-089

### CE2-009: Trim to playhead left a one-frame sliver as its own card.
- What was going on: The trim re-derived the clip's edge from a rounded value, landed a frame short, and the leftover frame became a tiny separate cut.
- What the product must do: Trimming a cut's head or tail to the playhead never leaves a leftover cut of any length, at any frame rate.
- Kind: 3
- From: C05-034, P09-036

### CE2-010: A trimmed clip kept its whole sentence, and its English lagged.
- What was going on: Cutting a trimmed clip's text to its remaining words went through the server, which refused it on one host and gave up; when it worked it took seconds.
- What the product must do: After a trim or split the clip shows only the words inside its edges, and their English, in the same frame as the edit, with no network wait.
- Kind: 3
- From: P15-048, C06-088, P16-005, P16-027

### CE2-011: Trimming must repaint within about a tenth of a second.
- What was going on: The owner: "No lag now dragging around in the timeline" once trim-to-paint measured about 90 ms typical and 100-125 ms at the slow end.
- What the product must do: A trim gesture repaints within 125 ms for 95 of 100 tries on a desktop, and within 500 ms on a processor slowed four times.
- Kind: 3
- From: L04-022

### CE2-012: Go-to-clip-start and end keys act on the clip under the playhead.
- What was going on: The owner: these keys "should take the playhead as the 'current' position, not which lane card is selected."
- What the product must do: The go-to-clip-start and go-to-clip-end keys move the playhead within the clip it is in, whatever is selected.
- Kind: 2
- State: outcome not found
- From: P08-027

### CE2-013: Clips outside the current section must not be dimmed.
- What was going on: The timeline darkened everything outside the playhead's section, which "makes it harder to move clips between sections".
- What the product must do: Every clip on the timeline is drawn at full brightness whatever section the playhead is in.
- Kind: 2
- From: P16-016

### CE2-014: Lane text strained the eyes on bright clips; dark joins vanished.
- What was going on: White text sat on bright clip colours and joins between dark blue clips were invisible; owner chose "ink by luminance. Waveform faint at rest. Seam at every cut."
- What the product must do: Clip text is dark on light colours and white on dark ones, the waveform is faint at rest and full while adjusting, and every cut shows a seam.
- Kind: 2
- From: D02-053, P11-036, C06-039

### CE2-015: The lane bar juddered while playback speed changed.
- What was going on: The speed readout changed width with each step (1.3x, 1.35x, 2x) and pushed the controls beside it; the owner also wanted adjustable clip text size.
- What the product must do: Bar controls never move while a value they show changes, readouts reserve fixed width, and clip text size can be changed and is remembered.
- Kind: 3
- From: P11-037, C06-038

### CE2-016: The lane docks at the top or bottom with no gap under it.
- What was going on: The owner asked to "drag the lane to the top"; the first build left 71 px: "too much space between the lane and other windows".
- What the product must do: On desktop the lane docks top or bottom by drag or button, is remembered, and at the top leaves no more gap than the page's normal margin.
- Kind: 2
- From: D03-047

### CE2-017: The cards and transcript panels flow around the lane, never under it.
- What was going on: Resizing the lane covered the cards and browser panel; the owner wanted them to "flow around the lane", the browser open by default with adjustable width.
- What the product must do: However the lane is resized no panel is hidden beneath it; the browser panel opens by default on desktop and its width can be dragged.
- Kind: 2
- From: P09-052

## Cards, selection and keys

### CE2-018: Selection is one thing shared by the cards and the lane.
- What was going on: Clicking a card did not select it, selecting in the cards only moved the playhead, and F did nothing; the owner wanted one shared selection.
- What the product must do: Selecting in cards or lane selects the same item in both and scrolls the lane to it; F brings the playhead's card into view, expanded at every density.
- Kind: 2
- From: P09-053

### CE2-019: A click selects a card, shown by a red bar beside its colour bar.
- What was going on: The owner asked for a red selection bar, a persistent red dot on the playhead's card, compact unselected cards, and buttons that hold still on play.
- What the product must do: One click selects and a second opens; selection is a full-height red bar beside the colour bar, the playhead's card has a red dot, and play never moves controls.
- Kind: 2
- From: C05-024, P09-054

### CE2-020: The card under the playhead opens at every density.
- What was going on: At tight densities every card shrinks to a bar, so the playhead pointed at a nameless line.
- What the product must do: The cut the playhead is inside opens like the selected card at every density, and closes again when the playhead leaves it.
- Kind: 2
- From: D07-019

### CE2-021: When the playhead sits in a gap, the gap is highlighted.
- What was going on: With the playhead in a gap between clips, no card or gap showed as current.
- What the product must do: When the playhead is in a gap, that gap is highlighted in the card list the way a card would be.
- Kind: 2
- From: P04-068

### CE2-022: Switching between cards and lane keeps the same cut in view.
- What was going on: The owner asked that opening the lane centre on the selected card, and closing it scroll the cards to the cut under the lane's playhead.
- What the product must do: Flipping between cards and lane, either way and repeatedly, lands on the same cut at the same position.
- Kind: 2
- From: D05-052

### CE2-023: Cards are not collapsed into stacks unless the editor asks.
- What was going on: The owner ruled cards start expanded and the editor chooses what is a stack; joining lagged, a box selection offered no join, and closed stacks reopened after restart.
- What the product must do: No stack exists by default; any adjacent cards join or unjoin at once, including a box selection; a new stack starts closed, and closed stays closed after restart.
- Kind: 2
- From: P07-048, P07-049

### CE2-024: A cut with no transcript still appears as a card.
- What was going on: Some cuts have no transcript at all, and some are silent stretches of a transcribed clip.
- What the product must do: Such cuts show as cards labelled "no transcript" or "silent", move like any other, and are never dropped.
- Kind: 3
- From: D05-043

### CE2-025: Keys went to the wrong panel with the transcript open.
- What was going on: With the transcript viewer open, Space and Delete acted on the wrong panel; the owner wants keys on the focused panel and Tab to move with an obvious outline.
- What the product must do: Keys act only on the visibly focused panel, Tab cycles panels with a clear outline, and a selection made in one panel shows in the other.
- Kind: 2
- From: P08-023

### CE2-026: Keys pressed in a search window reordered the cuts hidden behind it.
- What was going on: With the search results window open, arrow-like keys reached the cards behind it and reordered a cut list nobody could see.
- What the product must do: While a window covers the page, no key reaches anything behind it.
- Kind: 3
- From: D06-049

### CE2-027: Everything a person sees and touches in the editor is kept exactly.
- What was going on: Asked whether the rebuild's purge covers screens, menus, keys and gestures, the owner answered "No exactly, keep all that"; only what is behind them goes.
- What the product must do: Every Timeline Cards screen, control, wording, key, controller binding and gesture behaves and reads as before.
- Kind: 2
- From: P19-003

### CE2-028: Panels close from their header, and the top bar shows icons only.
- What was going on: The owner: "need a way to close the browser", "an easy toggle", and "don't need the word 'overview' and 'lane' in the top bar, just their icons".
- What the product must do: Every panel tab can be closed, a top-bar toggle reopens it on the last tab, top-bar buttons are icons with tooltips, and phone menu rows keep their words.
- Kind: 2
- From: P10-049, D03-045, D03-046

### CE2-029: "Why has the overview button disappeared? I want it back."
- What was going on: The overview button was moved into the options panel, whose sections were later collapsed by default, so it effectively vanished.
- What the product must do: The overview button stays visible on the desktop top bar, and moving any control into a collapsed menu needs the owner's approval.
- Kind: 2
- From: D06-038

### CE2-030: Menu text must be legible, and settings sections start collapsed.
- What was going on: The owner found dropdown text "too light", red highlights "pixellated", a big gap, a stray chevron and loose options.
- What the product must do: Menu text meets readable contrast, highlights render crisply, and each settings section collapses, all collapsed by default, with one expand-all or collapse-all control.
- Kind: 2
- From: P09-056

### CE2-031: Floating controls covered the cards and the text being worked on.
- What was going on: The insert bar hid the top of a transcript and returned while selecting; the owner asked floating buttons be see-through (about 0.55, solid on touch).
- What the product must do: No floating bar or icon covers transcript text, the first card or the top line of a lane clip, including while text is being selected.
- Kind: 2
- From: D05-050, P07-065

## Sections and the overview

### CE2-032: A section is a heading of any colour, never decided by colour.
- What was going on: The owner: "Sections should keep the section heading styling in any colour"; recolouring turned a heading into a bullet, on the page and in the saved file.
- What the product must do: A marker's kind (section, note, marker) is stored apart from its colour; any colour can make a section, and recolouring never changes the kind.
- Kind: 2
- From: D03-016, L04-012, D05-037, D07-015

### CE2-033: Each section shows as a band on the ruler, a tint and a fold.
- What was going on: The owner wanted sections coloured on the timecode strip with labels inside, draggable as whole blocks from the overview.
- What the product must do: A folded section shows its cut count, length and summary; folds are remembered per project; the cursor landing inside opens it; whole sections drag from the overview.
- Kind: 2
- From: D07-017, P09-061

### CE2-034: Neighbouring sections never share a colour.
- What was going on: The owner: "by default adjacent categories are never the same colour (right now they're all blue)".
- What the product must do: Neighbouring sections get different colours by default, and the lane's time bar and a bottom stripe show where each section starts and ends.
- Kind: 2
- From: P11-056

### CE2-035: Dragging a card across a section boundary moved an unmoved card.
- What was going on: Headings were anchored by position, so dragging a card up shunted the previous section's last card into the next section.
- What the product must do: A drag changes only the dragged card's section; deleting a section's first card keeps the heading; both halves of a split stay in their section.
- Kind: 3
- From: C05-043, P09-060, L04-013, D05-038, D07-016

### CE2-036: Cuts dropped at the top of a section join it under its heading.
- What was going on: The owner: "when you move clips to the beginning of a section it should not move the position of the section".
- What the product must do: Dropping cuts in front of a section's first cut puts them inside it, under its heading, and no other cut moves.
- Kind: 2
- From: C06-059, P13-030

### CE2-037: An empty section could not be dragged and shared its fold with the next.
- What was going on: A section with no cuts takes the next section's position, so a drag read as "dropped on itself" and folding one folded both.
- What the product must do: Each section is told apart by its own identity, not position, for dragging, dropping, tap-to-place and folding, including sections with no cuts.
- Kind: 3
- From: D03-017, L04-017, D07-018

### CE2-038: A paid section summary vanished after any trim above it.
- What was going on: Summaries were tied to a time position, so a trim above or a section move orphaned them, showing "no summary yet" after the work was paid for.
- What the product must do: A summary follows its section through trims and moves; a renamed section loses it on purpose, and an orphan is never guessed onto another section.
- Kind: 3
- From: D07-014, D05-039, L04-014

### CE2-039: A side panel lists every marker, with short section summaries.
- What was going on: The owner asked for a closable outline of markers opened from a top-left icon, with a summary per section; the summaries came out "much too long".
- What the product must do: Clicking a marker in the overview jumps there, and each section summary fits in a few lines.
- Kind: 2
- From: P07-045

## Colours

### CE2-040: Some of Resolve's clip colours are nearly invisible on a dark card.
- What was going on: Resolve's sixteen clip colours are fixed; Navy is nearly black and measures 2.35:1 against a dark card, invisible as a waveform on a dark row.
- What the product must do: Every Resolve clip colour, drawn on a dark surface, stays recognisable at 3:1 or better without altering the colour itself.
- Kind: 1a
- From: C05-002, C04-089

### CE2-041: Card colours must match the clip colours in Resolve.
- What was going on: One interviewee was dark pink in Resolve and light pink on cards; the page is read on a calibrated monitor in a graded room.
- What the product must do: Interviewee colours equal their Resolve clip colours for all sixteen, and status colours like amber and red stay distinguishable at their real 11-12 px size.
- Kind: 3
- From: P07-038, D06-044

### CE2-042: Each interviewee has one unique colour, changed once for all cuts.
- What was going on: Clips with no stored colour got one made from the name, so one person showed orange beside navy; the owner wants the "interviewee's base colour everywhere".
- What the product must do: One action recolours every cut of a person in one undo, a cut with no colour takes its person's colour, and no two interviewees in an episode share one.
- Kind: 2
- From: P15-037, C06-093, P18-010

### CE2-043: The transcript panel is outlined in its interviewee's colour.
- What was going on: The owner wanted the transcript panel framed in the colour of the interviewee it belongs to.
- What the product must do: The open transcript panel is outlined in the same colour its interviewee carries on the cards and the lane.
- Kind: 2
- From: P04-063

### CE2-044: Neighbouring montage clips from different sources should differ in colour.
- What was going on: The owner: "assign separate colours to clips from a different speaker / source - ideally no clips touching each other".
- What the product must do: Each speaker or source in a montage gets its own colour, and no two adjacent clips from different sources share one.
- Kind: 2
- State: outcome not found
- From: P13-019

## Playback and audio

### CE2-045: A browser given a video file to play sound decodes the video too.
- What was going on: Chrome decodes the video track to reach the audio, contending for the decoder other tabs use, so the lane froze and YouTube stuttered; it also sends date-form range checks.
- What the product must do: The browser is only ever handed audio-only files for sound, and partial-file requests work with every validator form browsers send.
- Kind: 1a
- From: G01-058, C04-070, P08-043

### CE2-046: Chrome puts an idle sound output to sleep, and Bluetooth adds delay.
- What was going on: After silence Chrome parks the output, so sound came half a second late; Bluetooth adds 150-250 ms, and muted video ran 0.1 s ahead.
- What the product must do: The playhead moves the instant Play is pressed after any seek, eases into sync with what is heard within half a second, and picture waits for the sound.
- Kind: 1a
- From: P16-036, C06-084, P15-045

### CE2-047: Seeking a playing browser media element clicks, and its clock is coarse.
- What was going on: Setting a playing element's position discards and refills its buffer, a step plus a dropout; its position advances in about 40 ms steps.
- What the product must do: Playback across any cut or chunk boundary is click-free, never jumps a playing element at a splice, never times a join from its coarse position, and seeks during first load work.
- Kind: 1a
- From: D01-012, D05-088

### CE2-048: A position set on audio not yet loaded is silently lost.
- What was going on: In browsers, setting a media element's position before it has loaded is only a start hint, discarded if the source is assigned again.
- What the product must do: A seek asked for before audio is ready is kept and applied once it loads, and the newest request always wins.
- Kind: 1a
- From: L05-046

### CE2-049: A play interrupted by the page's own pause is not a refusal.
- What was going on: A pending play the page interrupts with pause or a new load fails with an abort error, which was shown as "the browser would not start playback".
- What the product must do: A play cut short by the page's own pause or reload is never shown as an error; real refusals still say what they are.
- Kind: 1a
- From: D04-030, L05-037

### CE2-050: Browser audio ignores level changes during a scheduled ramp.
- What was going on: Chrome ignores a plain level write during a ramp (Firefox warns), a cancel mid-ramp does not hold the level, and a hidden tab draws about once a second.
- What the product must do: Fades, joins and levels run on the audio clock, sound right in a background tab, survive a level change mid-fade, and pause mid-fade without a pop.
- Kind: 1a
- From: D02-045, C06-023

### CE2-051: Resolve's scripting cannot load or position its source viewer.
- What was going on: The owner wanted selected text to cue Resolve's source viewer like its own transcript window, but that is not scriptable.
- What the product must do: Selecting transcript text lets the editor hear exactly that passage, from the product's own audio, without Resolve and without leaving the page.
- Kind: 1a
- From: P04-056, D05-010

### CE2-052: Play starts wherever the playhead is, with sound, and never jumps.
- What was going on: Playback could only begin at a clip's start, and Space once played silence and threw the playhead to the timeline's end.
- What the product must do: Space plays with sound from the exact playhead point, mid-clip included, never jumps it, and the playhead's head is drawn in a colour that stands out.
- Kind: 3
- From: P07-072, P08-016

### CE2-053: Releasing a scrub could leave sound playing for the rest of the recording.
- What was going on: Stopping paused the clip under the head, not the one the sound started on, so after crossing into another clip the sound played on.
- What the product must do: Ending a scrub or playback silences every sound it started, whichever clip the head is on now.
- Kind: 3
- From: D05-056

### CE2-054: The lit word must match the audio at every zoom.
- What was going on: The owner wants the word under the playhead lit in white; it failed on split and edge-word cards, and starting playback zoomed out lit the wrong word thereafter.
- What the product must do: During playback the exact word under the playhead is lit, on split, trimmed and edge-word cards, at every zoom and after zooming during playback.
- Kind: 2
- From: P08-019, P16-014

### CE2-055: Scrubbing sent hundreds of audio requests and once killed the server.
- What was going on: Ten seconds of scrubbing sent 211 audio requests, 7 at once, each decoding a video file (about 2.7 GB read), plus 305 playhead sends; the server hit 78% CPU.
- What the product must do: At most one scrub request is in flight, for the current position, from audio-only copies; playhead sends stay near ten a second with the final one always sent.
- Kind: 3
- From: G01-060, D02-043, P08-031

### CE2-056: Phone scrubbing sets the playhead's speed by finger distance.
- What was going on: The owner asked for rate scrubbing: an 8 px dead zone, 1 s/s at about 17 px, 10 s/s at 39 px, 180 s/s cap by 76 px.
- What the product must do: A touch in the 96 x 96 px scrub pad drives the head at the rate its offset sets, finer with the finger higher, reverses past the start, and parks on release.
- Kind: 2
- From: D05-055

### CE2-057: Matching interview peaks leaves speech 10 dB apart.
- What was going on: A peak is set by the loudest 20 ms in an hour (a door, a laugh), so "same peak" does nothing audible for speech.
- What the product must do: Preview levelling matches speech loudness with pauses and room tone ignored, and a limiter stops raised clips distorting.
- Kind: 1a
- From: C06-016

### CE2-058: "Same level" must bring every interviewee to the episode's middle loudness.
- What was going on: A fixed target never turned the loudest speaker down; one episode spanned about 20 dB; owner: "it's supposed to make all audio the same output level".
- What the product must do: Every interviewee is brought to the episode's median gated speech loudness, down as well as up, without clipping, and a separate trim sets overall loudness.
- Kind: 2
- From: M01-043, P11-016, C06-017

### CE2-059: Automatic levelling stays, and any cut can carry its own gain.
- What was going on: A recorder gain rose about 12 dB mid-interview, leaving early answers 6-11 dB under; owner: "keep the existing auto loudness behaviour but add ... manually adjust levels per span".
- What the product must do: Each cut is levelled by the speech around it and takes a manual gain (±30 dB, 0.1 dB steps), kept through split, trim, move, copy and undo, shown on the clip.
- Kind: 2
- From: C06-018, P14-016, C06-019

### CE2-060: Resolve's scripting cannot set a clip's volume.
- What was going on: Per-cut gain set in the editor has no way into Resolve through scripting, because no clip-volume setter exists.
- What the product must do: Every send to Resolve states how many cuts' gains did not reach it, and names them.
- Kind: 1a
- From: M03-035, D03-058

### CE2-061: The editor warns when a join breaks meaning or grammar.
- What was going on: Asked whether the join check stays, the owner answered "yes".
- What the product must do: After two pieces are joined, the editor reads the join afresh and warns when the sentence's meaning or grammar broke.
- Kind: 2
- From: P19-023

## Media the browser gets

### CE2-062: A multicam clip in Resolve has no file path of its own.
- What was going on: Resolve multicam clips carry no file path, so the browser editor's video window could show nothing for them.
- What the product must do: Previewing a cut from a multicam clip shows picture taken from its angles' source files.
- Kind: 1a
- State: still open
- From: M03-038

### CE2-063: Chrome plays YouTube's audio as it comes; re-encoding wasted seconds.
- What was going on: YouTube audio is Opus, which desktop Chrome plays inside MP4; re-encoding took 4-24 s a clip where copying the track took 0.6 s.
- What the product must do: Audio the editor's browser can already play is copied, not re-encoded; conversion happens only for a browser that cannot play it.
- Kind: 1a
- From: M01-019

### CE2-064: The browser editor is never fed camera originals, and timing stays exact.
- What was going on: Rushes are too big for a browser; re-encoded audio drifted 6.5 ms per 20 s (a fifth of a frame), and a 30-frame keyframe interval is 2 s on 60p.
- What the product must do: The browser gets audio within 1 ms of the source duration and about 480p proxies with a keyframe every second of source time, never a camera original.
- Kind: 3
- From: D04-073, G01-059

### CE2-065: New clips must be playable without waiting for someone to ask.
- What was going on: Small playback copies were made only when a clip was first played, so a fresh batch stayed unplayable for minutes and offline offered 2.9 GB of full recordings.
- What the product must do: Every clip's small playback copy is made automatically when it lands or the project opens, before anyone plays or downloads it.
- Kind: 2
- From: P13-014, P14-014

### CE2-066: Each interview has a small video preview in its own tab.
- What was going on: The owner: render it "at the same time as the audio" and make video "a different tab the same as the main window"; 480p, about 1 GB per 3 hours.
- What the product must do: Each interview gets a small picture preview made with its audio, and a Video tab plays it in step with the playhead.
- Kind: 2
- From: P15-040

### CE2-067: An abandoned video request kept streaming the whole file.
- What was going on: After a seek or a closed page, the server kept reading an hour-long proxy (200 MB sent after 256 KiB read), stalling the page's own requests.
- What the product must do: When a browser abandons a media request, the server stops reading and sending it within a second.
- Kind: 3
- State: fixed, never shipped
- From: L11-073, H08-051

### CE2-068: Cuts kept showing old words after their transcript was replaced.
- What was going on: A cut stored quoted transcript text, so when an interview's transcript was replaced the cut kept the old words.
- What the product must do: Opening a cut re-reads its words from the current transcript.
- Kind: 3
- From: M02-068

### CE2-069: One empty answer left the lane's words blank until reload.
- What was going on: A temporary empty or timed-out answer was kept as final, leaving cards blank; treating it as "never asked" instead re-asked 400-600 times a second.
- What the product must do: An empty, failed or timed-out answer is asked again after a cool-down of seconds, never at once and never given up on; only a definite "not found" means no words.
- Kind: 3
- From: C05-022, D02-054, P09-029, C06-075

## Search and the transcript panel

### CE2-070: On Android a plain text box shows Tab instead of Enter.
- What was going on: The transcript find box got a Tab key on Android's keyboard, so there was no way to reach the second match.
- What the product must do: A search box on a phone offers a search or Enter key that steps through matches, plus on-screen next and previous buttons and a "3 / 17" count.
- Kind: 1a
- From: D03-031

### CE2-071: Enter steps to the next result and Space plays it, endlessly.
- What was going on: Playing a result dropped focus, Enter scrolled the cards, Space with text selected scrolled the page; the owner wants to race through results listening to each.
- What the product must do: In transcript search Enter goes to the next result and Space plays or pauses it, repeatably with no mouse; focus stays, and nothing scrolls or stalls while typing.
- Kind: 2
- From: P07-053, P16-024, C06-090, P04-057

### CE2-072: Stepping through hits replayed the previous one and Chinese hits started early.
- What was going on: Each hit was cued only after a server round trip, so Space played the old cue and late answers overwrote newer ones; first-word hits played from the line start.
- What the product must do: Each hit plays from its own first word with no round trip, even several in one card and across clips; an answer for an older hit is ignored.
- Kind: 3
- From: C05-053, L05-045, P10-018, P05-038

### CE2-073: The find box and transcript switcher scrolled out of reach.
- What was going on: The owner: "the search and switch transcript function should float ... right now you have to scroll all the way up".
- What the product must do: The find box and switcher stay visible and usable at every scroll position, on desktop and phone, with the switcher's list drawn above other bars.
- Kind: 2
- From: P10-017, L05-044

### CE2-074: Nothing on the page moves by itself.
- What was going on: Selecting text jumped the view or scrolled away fast, the audio bar pushed content down, and after a delete the cards vanished for a second.
- What the product must do: Selecting never scrolls beyond what the pointer asks, the player appears without shifting content, and both panels stay on screen through edits.
- Kind: 3
- From: P04-060, P16-025

### CE2-075: Double-clicking a card opens its transcript beside the cards.
- What was going on: The owner wanted the card's transcript in a right-hand panel pushing the cards left, together filling the screen, searchable and switchable.
- What the product must do: Double-clicking a card opens its full transcript at that passage beside the cards; it can be searched, closed, and switched to any episode transcript.
- Kind: 2
- From: P04-054

### CE2-076: The transcript list showed 4 of an episode's 40 transcripts.
- What was going on: The list held only transcripts the cards had already used, so after a start most were missing.
- What the product must do: The transcript list shows every transcript in the episode, whether opened before or not.
- Kind: 3
- From: D05-036

### CE2-077: A key makes the transcript panel full height at its current width.
- What was going on: The owner: "I dont want the transcript to be full screen, I just want it to be full height, and maintain whatever width it had".
- What the product must do: One key toggles the transcript panel to full screen height at its current width and left edge, pushing the lane aside.
- Kind: 2
- From: P15-047

### CE2-078: The transcript shows as much text as possible, in white.
- What was going on: Paragraphs had too much spacing and off-cream text; the owner wanted it dense "like original timeline cards" and white.
- What the product must do: Transcript paragraphs are tightly spaced so many are visible at once, with white body text.
- Kind: 2
- From: P16-004

### CE2-079: Every transcript paragraph must have timing, or the panel goes dead.
- What was going on: Paragraphs were placed by exact text match against separately timed words; 80-90% missed, so click-to-play and the playhead silently stopped.
- What the product must do: When bringing the studio's existing transcripts in once, every paragraph gets timing, approximate where no exact match exists, so nothing is dropped silently.
- Kind: 3
- From: M02-064

### CE2-080: A cut links to the paragraph it overlaps most.
- What was going on: Transcript paragraphs overlap their neighbours by about 5 s, so taking the first one a cut touched linked 1,050 of 2,316 cuts to the previous paragraph.
- What the product must do: A cut links to the transcript paragraph it overlaps most.
- Kind: 3
- From: L10-025

### CE2-081: Card search finds cards by their English as well as the spoken words.
- What was going on: Searching the cards matched only the original-language text; the owner wanted English too.
- What the product must do: Card search matches each card's own words and its English, ignoring case and spacing, and a split piece matches only its own words.
- Kind: 2
- From: P16-034

### CE2-082: A literal search for "I" returns only a capital I.
- What was going on: The owner asked for a case-sensitive literal search mode beside the normal one.
- What the product must do: In literal mode a search matches exactly the characters and case typed, and nothing else.
- Kind: 2
- From: P07-067

### CE2-083: A meaning search returns five best passages by default.
- What was going on: Owner: "I need 5 of the best matches as output and that's it"; later "let you select how many results you want".
- What the product must do: Meaning search returns the five strongest passages, spread across speakers when equal; 10, 20 or 50 can be picked and remembered per device, odd values pulled into range.
- Kind: 2
- From: M04-125, P07-058, D03-029

### CE2-084: Finding words stays instant at hundreds of transcripts.
- What was going on: Exact find took 1.5 s per keystroke at 100 transcripts and 24 s at 520, uncancelled; the panel redraw took 255 ms for three hours of text.
- What the product must do: Find across 500 transcripts answers within a second, a newer keystroke cancels the older search, and the transcript panel redraws within 60 ms.
- Kind: 3
- State: still open
- From: H08-055

## The English a cut shows

### CE2-085: English leads on every card, with readable original text beneath.
- What was going on: The owner reads Chinese but grasps story flow faster in English; the Mandarin under it was dark, cut off on long cards, and smaller in the viewer.
- What the product must do: English is the top highlighted line with the original beneath; the active card shows all its original text, and in the viewer both share one size and colour.
- Kind: 2
- From: P04-050, P04-051

### CE2-086: A clip's English must cover exactly its words.
- What was going on: A clip ending at "president Lai" showed English running past it, another dropped "slaughter" though 殺戮 was in it, and 186 of 237 re-ordered clips showed none.
- What the product must do: Every clip shows the transcript's own English for exactly the words between its edges, for the whole episode, with no button needed.
- Kind: 2
- From: P16-026, P17-030

### CE2-087: Frame-exact cuts must never be called approximate.
- What was going on: Cuts whose text was matched by subtitle cue were labelled "trims are approximate", though every span was frame-exact; the owner flagged it twice.
- What the product must do: Wording about a cut's timing describes only what is truly approximate, and matches what the send to Resolve will actually produce.
- Kind: 2
- From: C05-037, M03-053

## Shortening and the assistant

### CE2-088: The assistant was shown unavailable when unchecked or only slow to start.
- What was going on: "Not checked yet" was read as "not there"; on a busy server the assistant took 50 s to cold-start (30 ms warm), and a timeout was kept as "no credential".
- What the product must do: Unchecked or slow answers use the last real check, a slow start says "too slow to start" and is re-checked within about 30 s, never reported as missing.
- Kind: 3
- From: L04-011, P09-064, L10-068, P12-054

### CE2-089: Showing whether the assistant is available must not spend a paid call.
- What was going on: The availability shown on the assistant buttons is read on every page refresh, and a real probe costs one paid call each time.
- What the product must do: Showing whether the assistant is available makes no paid call.
- Kind: 3
- From: D01-037

### CE2-090: The assistant keeps one warm conversation while the owner works.
- What was going on: The owner: "does the session stay active ... so the cached content remains cached? I don't want it to reset context every time"; search covers one or all transcripts.
- What the product must do: Follow-ups on one cut or montage share one conversation, a reload or second browser joins it, and a forced restart says so on screen and re-sends the material.
- Kind: 2
- From: D04-016, D01-031, D03-026

### CE2-091: Searching one person's interview read every transcript in the episode.
- What was going on: Owner: "it should only read that one relevant transcript"; a repeat search took 139 s re-sending 79% of the episode (about 145k tokens against 70k for one person).
- What the product must do: A search scoped to one person or clip sends only those transcripts, cold or warm, and logs how much was reused and how much sent fresh.
- Kind: 2
- From: M02-069, L05-026

### CE2-092: Shortening used a massive amount of assistant capacity.
- What was going on: Each of about 50 calls per pass carried six transcripts and the whole cut, about 180,000 tokens; a one-person search read 322,000 characters for a 97,000-character transcript.
- What the product must do: Each call carries only what that step needs, so a one-section or one-person request costs in proportion to that material, and each pass logs its cost.
- Kind: 2
- From: C05-062, D01-021, P10-058

### CE2-093: A server-side search failed because it was handed a file path.
- What was going on: The request told the assistant to read a transcript by path; the assistant on the server had no file access, asked permission, and answered nothing.
- What the product must do: Every request to the assistant carries the text it needs, never a path, and a failure shows its own sentence in the panel where it ran.
- Kind: 3
- From: D03-030

### CE2-094: The editor chooses which assistant model answers, and it really does.
- What was going on: Owner: "both panels ... sonnet/opus/fable options"; one host silently ignored the choice, so everything ran on a default.
- What the product must do: Search and edit chat each offer a model with its price, remembered per browser, used for every call including shortening; an unknown model falls back to the default.
- Kind: 2
- From: C06-011, D01-030

### CE2-095: The assistant was told about 40 of 120 selected cards.
- What was going on: The selection sent to the assistant was cut at 40 rows while its header said 120, so an edit named 40 cards as the answer for 120.
- What the product must do: When a selection sent to the assistant is shortened, every remaining card is still listed, so the count and the list agree.
- Kind: 3
- From: L07-055

### CE2-096: Closing a tab must stop the assistant work it started.
- What was going on: A closed tab kept a large call running up to 15 minutes, interactive and background work shared four places, and eight lookups started 32 processes.
- What the product must do: Closing the tab cancels its assistant work within seconds, and interactive requests never wait behind background ones.
- Kind: 3
- State: still open
- From: H08-075

### CE2-097: Shortening runs only on the sections the editor picks.
- What was going on: Owner: "select a section or multiple sections ... and ONLY run it against that"; he also wanted typed section targets, sticky pins and suggestions he could hide.
- What the product must do: Every step touches only ticked sections (none ticked is the whole cut), targets are typed per section, keep or drop pins stick, and lane suggestions hide and show.
- Kind: 2
- From: C05-070, P11-001, D01-022, P11-015

### CE2-098: The shortened length shown must be the film's real length.
- What was going on: Showing the length "if every suggestion were taken" made an untouched pass look finished, and the assistant's own arithmetic missed targets by minutes.
- What the product must do: The length shown counts only accepted removals, the offered length sits beside it, and a missed target is labelled, e.g. "lands at 3:06, asked for 3:00".
- Kind: 3
- From: D01-016, D03-050, C05-069

### CE2-099: After the first shortening step the owner could not find the next.
- What was going on: Next-step buttons sat in a hidden panel; the review used unlabelled dots and needed sideways scrolling: "I don't get how to use it."
- What the product must do: A multi-step task's next step appears where the person asked; a finished shortening opens its review, every marker is labelled, and nothing scrolls sideways.
- Kind: 3
- From: D01-020, P10-053

### CE2-100: A staged edit counted as held was shown nowhere.
- What was going on: The run button said "1 held" but no card showed which edit was held, so the count could not be answered.
- What the product must do: Every staged edit that cannot apply is marked "held" on the card it concerns, so every held count can be traced.
- Kind: 3
- From: D06-043

## Working offline

### CE2-101: A laptop's browser says "online" while the server is unreachable.
- What was going on: The online flag stays true while any adapter is up (a VPN's, Wi-Fi without internet), and Windows waits about 21 s per connection to an unreachable address.
- What the product must do: Reachability is measured with a request of about 3 s deadline, never read from the online flag, and with no server the offline copy answers within about 3 s.
- Kind: 1a
- From: L05-033, M01-038, P10-011, D04-028, C05-050

### CE2-102: Offline use in a browser needs https or the machine's own address.
- What was going on: Browsers allow offline page machinery only in a secure context; plain http by IP registers nothing, while the machine's own loopback address counts as secure.
- What the product must do: Where offline cannot work, the panel says so in a sentence instead of offering a download that cannot work.
- Kind: 1a
- From: D04-037

### CE2-103: Browser storage belongs to an address, port included.
- What was going on: Offline storage is kept per page origin and can be evicted, so changing the server address or the app's local port strands every downloaded copy.
- What the product must do: A released app's local address and port never change, and changing the server address keeps every downloaded copy and queued edit available.
- Kind: 1a
- From: M04-120, D04-026

### CE2-104: Browser caches belong to the whole site, not to one page.
- What was going on: Deleting "all caches" to clear one stale offline page also removed another app's offline page and media an editor had saved for offline work.
- What the product must do: Clearing a page's offline copy deletes only that page's own files, never another page's or saved media.
- Kind: 1a
- From: L09-005

### CE2-105: Retiring or updating a page wiped other pages' offline copies.
- What was going on: A retired page's clean-up deleted every stored page on the site; a retired page's own copy can also hold edits not yet sent.
- What the product must do: Retiring or updating a page never deletes anything a device saved; installed pages keep working offline, and unsent edits survive a rollback.
- Kind: 3
- State: fixed, never shipped
- From: L10-010, H06-073, C04-048, P18-015

### CE2-106: Only desktop Chrome and Edge let a page keep rewriting one chosen file.
- What was going on: Chrome and Edge on Windows and macOS let a page write repeatedly to a file picked once; Firefox, Safari, Android and iOS browsers do not.
- What the product must do: Any repeated save from a web page works on all these browsers, using silent overwrite only where the browser supports it.
- Kind: 1a
- From: L08-039

### CE2-107: iOS asks permission for every download a page makes.
- What was going on: Android Chrome asks once per site; iOS Safari asks before every file; iPadOS reports itself as a Mac; persistent storage is a request, not a promise.
- What the product must do: Automatic saving is on where it is silent and off by default on iPhone and iPad with the reason shown; closing the share sheet is not an error.
- Kind: 1a
- From: D04-045, C05-057

### CE2-108: Downloaded audio is loaded outside the page's own requests.
- What was going on: A media element's loading and range-seeking never pass through the page's request handling, so only a lower layer can answer them offline.
- What the product must do: Downloaded clips play and seek offline with nothing on the wire, including after skipping between clips.
- Kind: 1a
- From: D04-029

### CE2-109: The cut editor works fully offline, with 100-day sign-ins.
- What was going on: Owner: "you only need to be online once every 100 days to log in ... it should warn you while online if the login is about to expire".
- What the product must do: Sign-ins last 100 days, a warning shows from 14 days before expiry while online, and an expired sign-in never stops offline editing or deletes downloads.
- Kind: 2
- From: P14-026, C06-064

### CE2-110: Refreshing offline media must visibly check and report.
- What was going on: Owner: "It should run a check and say 'all media up to date' ... and then show the most recent time checked".
- What the product must do: Refresh checks every downloaded clip, says "all media up to date" or names what changed, shows the last-checked time, and says when the server is unreachable.
- Kind: 2
- From: P14-027

### CE2-111: Scrubbing and trimming use downloaded audio and need no server.
- What was going on: Owner: "when audio is downloaded offline the browser should use the downloaded audio instead of streaming it"; each 40 s scrub window cost 1.3 MB.
- What the product must do: With a clip downloaded, scrubbing and trimming stream nothing and work fully offline.
- Kind: 2
- From: C05-079

### CE2-112: Seeking in a large downloaded clip paused for seconds.
- What was going on: Downloaded recordings were 500 MB to 1 GB, and every seek read the whole stored file before serving the requested part.
- What the product must do: A seek anywhere in a downloaded clip of any size resumes playing within a fraction of a second.
- Kind: 3
- From: P10-019, C05-078, M01-054

### CE2-113: The offline copy kept playing an old recording after the server replaced it.
- What was going on: Downloaded media is served from the device first; a re-render keeps the duration and byte length, so only the modified time differed.
- What the product must do: A replaced source remakes its small copy and waveform, every device copy is detected stale by more than size and refetched, and the replaced clip is named.
- Kind: 3
- From: M01-053, C05-077, C06-010, P11-004

### CE2-114: Offline downloads run only where switched on and never repeat.
- What was going on: The installed app's "keep what is open" download ran everywhere, ignored its off switch, and re-downloaded every video proxy every ten minutes.
- What the product must do: Media downloads for offline use only where the person switched it on, and media already held is never downloaded again.
- Kind: 3
- State: fixed, never shipped
- From: H08-053

### CE2-115: Saving a cut list to the device froze the editor for seconds.
- What was going on: Checking downloaded files for the offline copy ran on the page itself, blocking it for up to 1.8 s at a time.
- What the product must do: No background download, check or save blocks the page longer than one frame; typing, playback and scrolling stay smooth throughout.
- Kind: 3
- From: P16-009

### CE2-116: One slow answer switched the page to an old offline copy.
- What was going on: Any timed-out call, even a meaning search that honestly takes a minute, declared the server dead and swapped in a stale copy for 20 s, so edits looked reverted.
- What the product must do: Only a failed short reachability check switches to offline; long requests carry no deadline; the screen never shows an older state; a live or offline marker stays visible.
- Kind: 3
- From: C05-051, L05-034, D04-031

### CE2-117: Undo failed offline.
- What was going on: Undo was refused outright while offline, and a page that lost the server answered from an old full copy, so recent edits looked reverted.
- What the product must do: Offline undo takes back the last unsent edit, and losing or regaining the server never shows an older state than the one on screen.
- Kind: 3
- From: P11-006

### CE2-118: Inserting a passage from a transcript failed with the server unreachable.
- What was going on: Insert asked the server where the passage sat, failing during a one-minute restart; owner: "This should be fully processable offline".
- What the product must do: Inserting any paragraph the panel shows works offline from the stored transcript, within 12 frames of the online placement, approximating edges if needed and saying so.
- Kind: 2
- From: P17-039, C06-092, L08-040

### CE2-119: Refused offline edits were queued, so cards jumped and blades did not take.
- What was going on: Edits the device's copy refused were queued as if accepted, so the page drew its own list and cards jumped.
- What the product must do: An edit refused while offline is shown on screen at once, is never queued, and the page returns to the device copy's list.
- Kind: 3
- From: L08-035, C05-081

### CE2-120: Splitting one card twice offline made two pieces with one name.
- What was going on: Offline pieces were named after their parent plus a fixed suffix, so a second split collided, and the server could not find pieces it never saw.
- What the product must do: Every offline split makes pieces with unique, repeatable identities, and on reconnect each is found by the source range it covers.
- Kind: 3
- From: L08-036, P11-007

### CE2-121: One refused edit stalled seventeen queued edits for an hour.
- What was going on: The first of 17 offline edits failed with "'base'" and parked the rest; a refusal inside an OK answer counted as synced and was lost.
- What the product must do: On reconnect each queued edit lands or is dropped with its reason in words, and the rest continue; only a file changed by others stops the queue.
- Kind: 3
- From: L08-037, D04-041

### CE2-122: Offline edits must never be forced over others' changes, nor nag per edit.
- What was going on: Queued edits assume each other, so replaying onto a moved-on file builds a cut nobody made; after one "keep mine" every later edit asked again.
- What the product must do: If the file moved on, waiting edits stop and offer keep or drop mine; one "keep mine" carries the rest, "keep all mine" exists, nothing is sent twice.
- Kind: 3
- From: C05-045, D04-035

### CE2-123: An offline edit that could not be stored was shown as made.
- What was going on: With the phone's browser storage full, saving an offline edit failed silently and the page showed the edit as made.
- What the product must do: If an offline edit cannot be stored, the page says so at once and the edit is not shown as saved.
- Kind: 3
- State: still open
- From: H08-070

### CE2-124: Unsent offline edits save themselves to a file, without nagging.
- What was going on: The only copy lived in browser storage; owner: "local copies should save to a directory automatically"; "Downloads on laptop is fine"; the first version prompted every minute.
- What the product must do: Unsent edits save within seconds, at most once a minute and always including the last, to one silently overwritten file, restorable without duplicating edits.
- Kind: 2
- From: C05-056, P10-024, D04-044, L05-038

### CE2-125: The phone's offline copy went blank.
- What was going on: A live state with no cards, naming no cut list, replaced a 251-cut download, while the picker still said 251 cuts.
- What the product must do: A downloaded copy is replaced only by a state for the same cut list and never by an empty one, and an emptied copy says so.
- Kind: 3
- From: C06-065, M03-056

### CE2-126: A 42-edit staged draft vanished in one save.
- What was going on: Each save replaced the draft, so an emptied draft left no trace of who or when; it came back only from the browser's own storage.
- What the product must do: Every revision of a cut or draft is kept with its time, an emptied one is logged, and any revision can be restored.
- Kind: 3
- From: C04-065, P08-022

### CE2-127: Changing where episode data lives abandoned existing state.
- What was going on: Moving to one storage area per episode left old settings and backups unread one folder up, with no record of which episode they belonged to.
- What the product must do: A storage change carries existing state across before use when ownership is certain; otherwise it keeps both and names both locations to the admin.
- Kind: 3
- From: H06-074, L09-006

### CE2-128: Downloaded projects sit in a readable folder chosen per computer.
- What was going on: Owner: "put them into a human readable projects folder" and "you can choose where a project lives per project per machine", pulling from the NAS directly.
- What the product must do: The desktop app opens projects from the NAS and keeps each downloaded cut list as named files in a visible folder chosen per project per computer.
- Kind: 2
- State: outcome not found
- From: D04-053, P15-042

### CE2-178: A helper server on the editor's own machine answers only its own app.
- What was going on: The app's local server writes and deletes files on disk, so any website or rebound host name reaching it could touch the projects folder.
- What the product must do: The local server refuses any other Host or another site's Origin, and every path it touches resolves inside its own project folder.
- Kind: 3
- From: D04-054

## Several people and devices

### CE2-129: Two people on different accounts cut two projects at once.
- What was going on: The editor ran one project for the whole server; owner: "at the landing page you just select a project and then go in".
- What the product must do: A landing page lists projects without loading any, and two people can each open and edit a different project at the same time.
- Kind: 2
- From: P11-023

### CE2-130: Who is working in which project is shown to every signed-in person.
- What was going on: A review asked to hide names from the "all seats taken" message; the owner had ruled "another person being live here is something to know".
- What the product must do: Who is in which open project is visible to all signed-in people, and messages may name them.
- Kind: 2
- From: L09-004

### CE2-131: An editor working offline could be thrown out of their episode.
- What was going on: Presence was measured by server requests, so after 15 quiet minutes an offline editor looked gone, while an always-on computer kept its editor "in" for ever.
- What the product must do: Presence follows a person actually working, offline or on a sleeping phone; unsent work keeps an episode occupied; a closer is told who was last in and when.
- Kind: 3
- State: still open
- From: H06-069, L10-011

### CE2-132: Phone and laptop share one draft, each keeping its own view.
- What was going on: Owner: "the timeline keeps appearing on the phone while the laptop is open"; he wants to "look at different sections on my phone and laptop".
- What the product must do: Every device agrees on one draft and its staged edits, while scroll, cursor, selection, playhead and view stay per device; a first visit starts at the latest place.
- Kind: 2
- From: M04-053, D05-053

### CE2-133: Phone and desktop were in different modes on the same draft.
- What was going on: The editing mode was a per-browser preference, so two devices disagreed about what the same draft was.
- What the product must do: Which mode a project is edited in follows the project itself, the same on every device.
- Kind: 3
- From: D04-067

### CE2-134: An edit took 709 ms to confirm though applied in 37 ms.
- What was going on: Owner wanted edits to "feel instant"; over a 100 ms one-way remote path, two full requests on fresh connections cost 637 of the 709 ms.
- What the product must do: An edit is confirmed by the answer to the edit itself, in one round trip, without refetching the whole cut.
- Kind: 3
- State: outcome not found
- From: D01-038

## Phones, installing and the controller

### CE2-135: Phone browsers grant full screen, vibration and install only over https.
- What was going on: Full screen, haptics, orientation lock and home-screen install are refused on plain http; full screen comes only inside a touch; iPhone has no full screen.
- What the product must do: The phone editor is served over https, asks for full screen on the first touch, and works unchanged when any of these is refused.
- Kind: 1a
- From: D01-002, M04-062

### CE2-136: Phone browsers start playback only inside a tap.
- What was going on: Playback started from a network reply or before audio was unlocked is refused, and full screen and orientation lock also need the user's gesture.
- What the product must do: Playback and full screen are requested inside the touch that wants them, audio unlocks on the first touch, and any refusal is shown.
- Kind: 1a
- From: C04-084, M03-048

### CE2-137: A phone fetches an app's install files without the sign-in.
- What was going on: Chrome fetches a web app's manifest and icons without cookies; behind the login they redirected, so Install made a shortcut with an address bar.
- What the product must do: Install files and icons for every installable page load without sign-in, reveal nothing private, and the installed page opens full screen.
- Kind: 1a
- From: L03-080, C03-037, M01-037, D01-003

### CE2-138: An installed app under a sub-path takes over the whole site.
- What was going on: An installed home-screen app whose scope is the site root claims every address on the host, including the dashboard it sits inside.
- What the product must do: An installed editor's scope and start address are its own folder, whether served at the root or under a sub-path.
- Kind: 1a
- From: D01-004

### CE2-139: A phone paints an installed app's frame from its declared colours.
- What was going on: The address bar, splash and task switcher kept a retired grey-blue after the page became black and red; changing it restyles every installed phone.
- What the product must do: The declared theme and icon colours match the page's current look, and changing them is treated as visible to every installed phone.
- Kind: 1a
- State: still open
- From: D03-024, L04-023

### CE2-140: The Android web view lacks full screen, landscape lock and blob saving.
- What was going on: Android's embedded web view ignores full-screen and orientation-lock calls, cannot save blob downloads, and its request interception cannot see request bodies.
- What the product must do: On Android, opening the lane turns the phone landscape, and saved copies land in the device's Downloads.
- Kind: 1a
- From: D04-027

### CE2-141: On Android 13 and later, Back left the app instead of opening its menu.
- What was going on: With a recent target version the back gesture never reaches the old back handler, so the only way to settings and updates vanished.
- What the product must do: Back opens the app's menu on every Android version, and settings and update stay reachable from the page as well.
- Kind: 1a
- From: C06-069

### CE2-142: An Android update signed with a different key will not install.
- What was going on: Android refuses an update signed differently, uninstalling deletes every offline copy, and the first in-app update sends the user to "Install unknown apps".
- What the product must do: Every Android release is signed with one key kept for the app's life, so an update never forces an uninstall that loses offline work.
- Kind: 1a
- From: D04-055, M04-121

### CE2-143: iPhones ignore a page's request to lock to landscape.
- What was going on: Android Chrome honours full screen and a landscape lock asked inside a tap; iOS refuses the lock, leaving a 390 px wide portrait screen.
- What the product must do: The lane works on a 390 px portrait screen when the lock is refused, and the editor is told once, not every time.
- Kind: 1a
- From: D05-047

### CE2-144: Web drag and drop does not exist on iPhones.
- What was going on: iOS browsers fire no native drag events, so dragging cards needs touch gestures such as hold, tap to pick up and tap a gap.
- What the product must do: Every drag action, including filing a card into a category, has a touch way that works on iPhone and Android.
- Kind: 1a
- From: D05-046

### CE2-145: On Android a long press fires the same event as a right-click.
- What was going on: A long press meant to open a transcript or move a clip opened the right-click colour picker under the finger.
- What the product must do: Every touch gesture has exactly one meaning in each phone view, and nothing that means right-click is reachable by a long press.
- Kind: 1a
- From: M04-061, D06-034

### CE2-146: Android Chrome with "Desktop site" on reports 980 px wide.
- What was going on: The owner's phone has Desktop site on, so a width test served it hover-only controls, a tiny gear, and a lane strip with cards behind.
- What the product must do: The phone layout is chosen from a touch pointer that cannot hover, not width alone, with a remembered manual override.
- Kind: 1a
- From: D06-030

### CE2-147: A window dragged between monitors briefly reports a narrow width.
- What was going on: On Windows, moving between monitors of different scaling briefly reports a narrow width, and the page flipped to phone layout for good.
- What the product must do: A brief width change never switches layout; the switch waits, uses different in and out widths, and leaving it restores the desktop layout exactly.
- Kind: 1a
- From: P08-028, C04-072

### CE2-148: Chrome on Android raises its own word overlay over any selection.
- What was going on: The "explore this word" panel and copy toolbar appear over a native selection, and a page cannot dismiss, move or restyle them.
- What the product must do: On touch, nothing outside text boxes is natively selectable; the transcript has its own word selection with draggable handles, double tap for a line, and its own copy button.
- Kind: 1a
- From: D03-034, C05-047

### CE2-149: The editor apps update themselves from inside the app.
- What was going on: The owner: "make the app installable inside the app, without needing to get pushed over adb", on Windows and Android.
- What the product must do: Each app checks, downloads, verifies and installs its own update from its settings, keeping its settings and offline copies.
- Kind: 2
- From: M04-119, D04-056

### CE2-150: On a phone the card text gets nearly the whole width.
- What was going on: The owner asked that unselected phone cards show only text and one line of name and number, margins cut to a few pixels.
- What the product must do: On a phone an unselected card has no buttons and one non-wrapping meta line; the selected card offers its actions as 44 px buttons.
- Kind: 2
- From: D05-049

### CE2-151: On the phone the playhead chooses which edge a held drag trims.
- What was going on: The owner: playhead in the first half of a card and hold-drag trims the start; in the second half, the end.
- What the product must do: A press held past 280 ms trims or extends the edge nearest the playhead, by the same rules as the desktop lane.
- Kind: 2
- From: C04-082

### CE2-152: On a phone the insert sheet belongs to the transcript view only.
- What was going on: Owner: "this insert overlay should never appear anywhere except the transcript page"; on Android the action bar sat under the header, beneath Chrome's copy menu.
- What the product must do: On touch, a transcript selection's actions sit in a bottom sheet shown only with the transcript, saying where the cut landed; the bottom bar names the view shown.
- Kind: 2
- From: L05-042, D03-033

### CE2-153: The lane's button bar does not fit a 390 px phone.
- What was going on: Nine lane buttons needed 414 px, then 419 px, and bigger thumb targets made 427 px, pushing the close button off a 390 px portrait screen.
- What the product must do: Every control bar, close included, fits and can be tapped on a 390 px portrait phone without clipping or sideways scrolling.
- Kind: 3
- State: still open
- From: D07-023, D03-025, L04-025, D05-048

### CE2-154: Phone taps seemed dead because panels opened behind a drawer.
- What was going on: "Download for offline" opened behind the full-screen settings drawer with silent failures, a drawer covered its own close, and Android back left the editor.
- What the product must do: An open drawer always shows a way to close it, Android back closes it, nothing opens underneath it, and every failure says why.
- Kind: 3
- From: C05-035, M02-072, P10-010

### CE2-155: "Pressing delete on mobile seems to do nothing."
- What was going on: Delete armed on first tap but said so on a scrolled-away line, and the next refresh erased the warning, so three seconds ran out invisibly.
- What the product must do: An armed delete shows a countdown on the button under the finger, and no refresh erases an arming or confirmation within six seconds.
- Kind: 3
- From: D06-032

### CE2-156: The editor pressed the blade 36 times because nothing showed it took.
- What was going on: Edits refused while another was in flight or with nothing selected said nothing, and refusals looked like confirmations.
- What the product must do: Every press visibly registers at once, each refusal says what happened and the way out, styled as a refusal and near the finger, and identical repeats collapse to one.
- Kind: 3
- From: D06-033, D04-042

### CE2-157: The installed app always opened on the same episode.
- What was going on: Installing from an episode page made it the app's home, and a phone keeps that home until the app is removed and reinstalled.
- What the product must do: The installed app opens on the episode list wherever it was installed from, and every episode stays inside the app.
- Kind: 3
- From: C04-029, P13-029

### CE2-158: With no network the installed app sat on its splash screen.
- What was going on: Nothing answered the app's home page offline, so a phone in aeroplane mode, or on a VPN with no route, showed nothing, not even saved cut lists.
- What the product must do: Offline, the installed app shows the last episode list within about 8 s, marks cut lists saved on the device, and opens them.
- Kind: 3
- From: C04-030, M03-055

### CE2-159: An installed phone app failed after a server restart.
- What was going on: The app's files answered "not open" until someone opened the episode on the server; changing the app's identity later forced reinstalls.
- What the product must do: An installed app starts after a server restart with nobody opening anything first, and its identity never changes.
- Kind: 3
- From: M01-036

### CE2-160: An installed copy of the editor can sit on an old version silently.
- What was going on: An installed web app keeps its saved page; with an expired sign-in the update check got the login page and the old version stayed.
- What the product must do: A republished editor replaces the installed copy on next open, and an outdated installed copy is never kept silently.
- Kind: 3
- From: D04-036

### CE2-161: Browsers hide a game controller until the page is touched.
- What was going on: Chrome, Edge and Firefox on Windows and Chrome on Android map an Xbox pad alike, but report one plugged in before load only after a key or click.
- What the product must do: The page tells the person to press a button if no controller shows, a stick acts only after passing centre once, and missing vibration causes no error.
- Kind: 1a
- From: D02-051, C06-032

### CE2-162: Everything but typing a search word works from the controller.
- What was going on: The owner: "The only touch I want to make to the keyboard is typing the actual input term to the find box."
- What the product must do: Switching panels, finding, walking and playing matches, choosing a transcript and inserting clips all work from a game controller with no mouse or other keys.
- Kind: 2
- From: P18-011, C06-035

### CE2-163: The controller drives the transcript with the lane's own buttons.
- What was going on: Owner: "keep the transcript controls as similar as possible to the lane controls so I dont have to memorise a new set of mappings".
- What the product must do: Every button does the same job on the transcript as on the lane, applied to text, a right-stick playhead included, and one button switches lane and transcript.
- Kind: 2
- From: P11-035, D06-045, C06-034

### CE2-164: On a controller, a clip edge is dragged by holding a trigger.
- What was going on: The owner: "Maybe LT pressed down and right stick left or right to extend or shorten the current clip under the playhead".
- What the product must do: Holding a shoulder button and moving the right stick extends or shortens the clip under the playhead, rippling what follows.
- Kind: 2
- From: P11-030

### CE2-165: Controller fades move one frame per tap.
- What was going on: The owner asked for fades on the controller: "yep build that, but it's a frame per tap".
- What the product must do: Holding a shoulder button and tapping the D-pad lengthens or shortens the clip's fade by exactly one frame per tap.
- Kind: 2
- From: P11-033

### CE2-166: A sleeping controller must not pull the cursor out of a text box.
- What was going on: Wireless controllers disconnect when idle, while a person may be typing in a box.
- What the product must do: A controller disconnecting never moves focus or the text cursor out of a box being typed in.
- Kind: 3
- From: D06-047

## Speed and smoothness

### CE2-167: Chrome slows sharply drawing thousands of thin bars as one shape.
- What was going on: A waveform of about 1,900 one-pixel bars in one canvas shape left the fast path past about 1,000 px wide: 0.19 ms became 1.5-3 ms a frame, invisible to page timers.
- What the product must do: Lane drawing cost stays flat at every zoom with real waveforms and Resolve sharing the GPU, measured with the browser's GPU trace at editors' real zooms and screens.
- Kind: 1a
- From: M01-047, C05-054, L05-048, D02-055, P10-016

### CE2-168: A filter on the page body makes fixed panels jump and vanish.
- What was going on: In browsers a filter on the body makes it the containing block for fixed elements, so a hover effect pinned the docked lane 44,000 px down or made it flicker.
- What the product must do: The lane and header stay exactly where docked in every hover and panel state, and nothing above the cards shifts on scroll.
- Kind: 1a
- From: P10-052, C05-073, M01-051

### CE2-169: A laptop's browser draws on integrated graphics, and switching changed nothing.
- What was going on: Chrome on a Windows laptop with switchable graphics used the integrated chip; the slow work was on the CPU, so the discrete GPU did not help.
- What the product must do: Drawing performance targets a laptop's integrated graphics and is fixed by reducing work, never by asking the person to change graphics settings.
- Kind: 1a
- From: P13-032

### CE2-170: Frame rates seen over Remote Desktop are not the real speed.
- What was going on: A Remote Desktop session displays at 32 Hz, and the browser's unlocked-frame test settings held it near 60 fps on a 144 Hz screen.
- What the product must do: Smoothness is judged from the app's own frame timings on the machine itself at the screen's real refresh rate before it is called done.
- Kind: 1a
- From: M04-059, P15-023

### CE2-171: Seeking, playback and lane zoom stay "butter smooth" at 100 frames a second.
- What was going on: Owner: "locked 100fps+"; on a 4K 150% laptop zoom frames took 65-217 ms with 1000 cuts, a held-stick zoom ran 5 fps, and arriving translations triggered rebuilds.
- What the product must do: During seek, playback, scroll and zoom, with 1000 cuts on a 4K screen and words still arriving, no frame takes longer than 10 ms on the studio's computers.
- Kind: 2
- From: P15-021, M04-057, L10-081, C06-060, P13-031, D02-056, M02-071

### CE2-172: The cut view must stay smooth on a phone at 500 cards.
- What was going on: Every change rebuilt every row, 5,000 elements at 500 cards: 23 ms on a desktop and an estimated 90-140 ms on a phone.
- What the product must do: At 500 cards one change updates the edit view on a mid-range phone within one frame (16 ms).
- Kind: 3
- State: still open
- From: H08-072

### CE2-173: Opening a big episode ate a server core for seconds.
- What was going on: An episode of 1,166 cards and 114,245 words cost seconds of server CPU per page open, slowing everything else the server did.
- What the product must do: Opening or editing the largest episode never makes other dashboard requests or reports wait.
- Kind: 3
- From: P12-067

## Opening episodes and keeping the editor running

### CE2-174: An episode that failed or hung while opening could never open again.
- What was going on: A failed open was remembered for good, and a hung read showed "opening" for ever while holding one of the limited places.
- What the product must do: Opening an episode has a time limit, a failure shows a plain reason, and the episode can be retried.
- Kind: 3
- From: H06-072

### CE2-175: Closing an episode leaked about 128 MB until memory ran out.
- What was going on: Closing an episode left its background work and memory behind.
- What the product must do: Closing an episode frees everything it used, so opening and closing episodes for days never exhausts the server.
- Kind: 3
- State: still open
- From: H07-137

### CE2-176: Edits silently did nothing, or the page waited forever on one.
- What was going on: An editing worker that died at start made every reorder and trim do nothing, and a server restart mid-edit froze the page on "an edit is still going through".
- What the product must do: An edit that cannot be applied says so within seconds, and a server restart mid-edit never leaves the page waiting forever.
- Kind: 3
- From: C05-021

### CE2-177: The editor's server vanished and had to be restarted by hand.
- What was going on: The owner found the service behind the editor gone more than once, and asked for a Start menu shortcut and a restart button.
- What the product must do: The editor comes back by itself after it stops, and nobody ever needs a terminal to start or restart it.
- Kind: 3
- From: P04-066

## Sealed

### CE2-S01: Only the marked prefix of a prompt is cached.
- What was going on: With the corpus in four messages and only the first marked, 79% of the text was billed in full each turn, and a "warm" search took 139 s.
- What the product must do: Long multi-part prompts are marked so the whole stored prefix is cached, and every call records tokens read from and written to the cache.
- Kind: 1b
- Tool: Anthropic Messages API prompt caching (cache_control breakpoints)
- From: L05-025, P10-030, C03-048

### CE2-S02: The prompt cache lasts five minutes unless an hour is asked for.
- What was going on: An editor who searches, watches and searches again pays full price to re-read every transcript after five minutes.
- What the product must do: Conversations meant to stay warm ask for the one-hour cache, and keep the cache length they were opened with.
- Kind: 1b
- Tool: Anthropic Messages API prompt caching
- From: L05-024

### CE2-S03: A prompt cache belongs to one model.
- What was going on: Resuming a conversation on another model re-reads the whole cached corpus at that model's price while reporting itself warm.
- What the product must do: Switching models starts a separate conversation, while the visible history of what was done to the cut is shared across models.
- Kind: 1b
- Tool: hosted AI provider prompt caching
- From: D01-035

### CE2-S04: An hour of speech is about 15,000 to 20,000 tokens of prose.
- What was going on: Mandarin is about one token per character and English one per four; both land near 15-20k per hour, so a 10-hour corpus is about 180k.
- What the product must do: The model is given sentence-level text, never per-word timing, so a 10-hour corpus fits in one request.
- Kind: 1b
- Tool: Claude models
- From: D04-013

### CE2-S05: Saved conversations resume only on the same machine and folder.
- What was going on: A conversation id resumes only with the same machine, home and working folder; unknown ids fail "No conversation found", reused ones "already in use"; rebuilds wipe them.
- What the product must do: The tool always starts from the same folder, and a conversation that cannot resume is restarted with its material re-sent, never answered without it.
- Kind: 1b
- Tool: Claude Code CLI sessions (--session-id / --resume)
- From: D01-034, D04-017

### CE2-S06: The desktop wrapper's window ran at 20 frames a second.
- What was going on: The packaged desktop window spent about 49 ms presenting each frame, while the same page in a browser app window held 144.
- What the product must do: Measure frame rate in the window the editor actually uses, and ship whichever window kind meets the performance goal.
- Kind: 1b
- Tool: Electron
- From: M04-058, C06-061

## Removed

- P04-042 | no longer applies: nothing before the hand-over may depend on Resolve, so the cards no longer mirror a live Resolve timeline
- P04-052 | no longer applies: the translate button and draft translations in the editor are cut
- C04-090 | superseded by CE2-086
- D05-074 | no longer applies: paragraph links pasted from the notes program are cut with it
- P09-062 | no longer applies: paragraph links pasted from the notes program are cut with it
- D03-018 | no longer applies: finding a paragraph by the notes program's block id is cut with it
