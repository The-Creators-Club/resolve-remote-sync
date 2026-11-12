# Timeline Cards: the editor (piece 3)

## The lane: how clips look and read

### CE3-001: The timeline strip with words inside the clips is the product's heart.
- What was going on: The owner: "the most useful thing about this app is the timeline with text inside the clips, by far the most useful and used thing."
- What the product must do: The lane (the timeline strip) gets the most space, keeps clip text legible at every zoom and height, can be resized and docked, and never regresses.
- Kind: 2
- From: M04-109

### CE3-002: Lane clip text wraps Chinese by character but never splits an English word.
- What was going on: The owner: "frequentl / y" must not happen; Chinese wraps per character, and waveforms fill the clip's height behind the text.
- What the product must do: No Latin word is broken across lines in a lane clip; an overlong one ends in an ellipsis; Chinese wraps per character.
- Kind: 2
- From: D05-051

### CE3-003: Clips show English first, the original underneath, flipped by one control or F9.
- What was going on: The owner kept a one-control language switch and could not find it, asking for F9; Russian and Ukrainian interviews are coming, so nothing may assume Chinese.
- What the product must do: English shows first with the original underneath if it fits; one control and F9 flip them, remembered per browser; each clip's language comes from its transcript.
- Kind: 2
- From: M04-112, P12-068

### CE3-004: Reading aids let the owner cut languages he cannot read.
- What was going on: He reads Chinese but not Russian or Ukrainian, and asked for ten aids: playhead word in both languages, sentence ends, verbs, safe cut points, negations, a join check, and more.
- What the product must do: Each aid is a per-device toggle, on by default for languages outside "languages I read"; without the analysis the editor says so quietly and still works.
- Kind: 2
- From: M04-115, D05-089

### CE3-005: Dragging a clip's edge shows the trimmed-off words faded.
- What was going on: The owner chose faded handle text so that extending a clip is "drag until the sentence ends".
- What the product must do: While dragging or hovering near a clip edge, the words beyond the edge show faded.
- Kind: 2
- From: M04-110

### CE3-006: Narrow clips must keep their words and their waveform baseline.
- What was going on: The owner: "prevent the waveform from going into the middle of a clip and the text disappearing at small zoom levels when the clip gets too horizontally short".
- What the product must do: At any zoom a clip keeps its words, cut off at its edge, and its waveform sits on the same baseline as its neighbours.
- Kind: 2
- From: P15-038

### CE3-007: Clip text reflows only on zoom, never while scrolling.
- What was going on: Words inside clips re-wrapped as the lane scrolled; the owner: "the text only reflows when you zoom in and out".
- What the product must do: Scrolling moves clip text with its clip unchanged; text re-wraps only when the zoom level changes.
- Kind: 2
- From: P16-008

### CE3-008: Several lane features were declined and must not be proposed again.
- What was going on: Declined: words at spoken time, snapping trims, a read-the-joins mode, zoom-adaptive gist text, drawn pauses, search hits in the strip, a pacing ruler, stacked takes, hesitation and filler marks.
- What the product must do: None of these is built or proposed again; of the hesitation marks the owner said "lets ditch all this, it's not useful actually".
- Kind: 2
- From: M04-118, P11-063, C06-043

## The lane: zoom, scrolling and dragging

### CE3-009: Lane zoom stays under the pointer, and selection marks are thin.
- What was going on: The owner: "zooming the lane should always zoom it around where the cursor is"; selection markers should be "less thick, more subtle".
- What the product must do: Zooming keeps the point under the pointer still, and a selected clip's marks are thin and never extend past its top or bottom.
- Kind: 2
- From: C06-062, P15-025

### CE3-010: A middle-button drag pans the lane without the browser's autoscroll.
- What was going on: The owner asked that a middle-button drag pan and fling the lane; browsers otherwise start the Windows autoscroll ring or a middle-click paste.
- What the product must do: A middle-button drag on the lane pans it with no autoscroll or paste; the wheel scrolls and Ctrl+wheel zooms.
- Kind: 2
- From: D05-059

### CE3-011: Dragging a clip moves it rather than selecting its words.
- What was going on: Trying to drag a clip often selected text inside it; the owner asked that the dragged clip turn see-through with a line showing where it lands.
- What the product must do: A plain press-and-drag on a clip moves it; picking words needs a modifier; while dragging, the clip is see-through and a landing line shows.
- Kind: 2
- From: P16-011

### CE3-012: While moving clips, the words of the clip before the landing point show.
- What was going on: The owner asked for an overlay of the words of the clip just before the marker when moving clips by controller or mouse, appearing with no delay.
- What the product must do: From the first moment of a move, the words of the clip the moved clips will follow show beside the landing line, updating as it moves.
- Kind: 2
- From: P16-032

### CE3-013: Dragging shows the card's outline and never the system's "no" sign.
- What was going on: Dragging a card toward the staged tab lost its silhouette and showed the Windows stop sign; the owner: "I never want to see the windows STOP sign flashing on".
- What the product must do: While dragging cards anywhere on the page, a silhouette follows the pointer, the forbidden cursor never appears, and drags may start from blank space.
- Kind: 2
- From: P09-050

### CE3-014: Cards in the card list could not be dragged, showing a blocked sign.
- What was going on: Reordering in the list stopped working while dragging in the lane still worked; a page refresh did not help.
- What the product must do: Cards in the list can always be dragged to a new place, with a steady drop marker.
- Kind: 3
- From: P08-032

### CE3-015: Section numbers follow their order, and sections drag by name or flag.
- What was going on: Reordering sections left their numbers unchanged, and sections could not be dragged in the overview or above the lane.
- What the product must do: Moving a section renumbers every section in its new order; a section drags by its name in the overview and its flag above the lane.
- Kind: 2
- From: P16-030

### CE3-016: The phone's vertical edit view must zoom out to an overview.
- What was going on: The owner: "The mobile vertical editor mode should still support zooming in and out vertically so you can get an overview of more content at once."
- What the product must do: The phone's vertical edit view zooms vertically, from detail out to an overview of many cards.
- Kind: 2
- State: outcome not found
- From: P08-050

### CE3-017: "Fit" showed only the first quarter of a 2.5-hour cut.
- What was going on: Fitting a 487-cut, 2.5-hour cut needs 0.08 px per second, but a zoom floor of 0.5 px that keeps cuts visible stopped it at a quarter.
- What the product must do: Fit shows a 2.5-hour cut whole, or says its limit and keeps the head in view.
- Kind: 3
- State: still open
- From: D05-060

### CE3-018: Lane speed must be judged at the zoom the owner works at.
- What was going on: Checks measured low zoom on a small window while the owner works at zoom 42 to 205; he ruled the playhead leaving the view "is not a problem".
- What the product must do: Lane speed is measured at real zoom levels and screen sizes with real waveforms; the playhead running off screen at high zoom is acceptable.
- Kind: 2
- From: L05-049

### CE3-019: Each view remembers where you were when you come back.
- What was going on: The owner: "when you switch tabs it should remember your position from the last time you were in X or Y tab".
- What the product must do: Re-entering a view, or reloading, restores its scroll and zoom, unless a jump, active playback or the person's own touch asks for somewhere else.
- Kind: 2
- From: D03-032

### CE3-020: A place arriving from elsewhere yanked the lane back mid-fling.
- What was going on: A view position adopted from another device or a refresh during a 1.4 s coast snapped the lane to another zoom under the finger, in about one fling of two.
- What the product must do: Nothing from another device or a refresh moves or redraws a view while the person is dragging, trimming, or it is still coasting.
- Kind: 3
- From: D05-054, D03-020

## Editing, undo and the cut list

### CE3-021: An edit shows at once, with only a small saving mark.
- What was going on: Every edit used to rebuild the whole list under a busy veil.
- What the product must do: An edit appears immediately without a full redraw or blocking veil, the card being saved shows a small mark, a refusal corrects it, and undo keeps selection and scroll.
- Kind: 2
- From: D07-021

### CE3-022: A held trim key during playback shrank a whole cut to frame-long pieces.
- What was going on: Holding the trim key while the lane played repeated the edit 350 times in 90 seconds, each on the next clip, until every clip was 1 to 7 frames.
- What the product must do: Holding an editing key never repeats the edit; one press is one edit; every cut-list revision is kept so a damaged list can be restored.
- Kind: 3
- Check: is every cut-list revision now kept so a damaged list can be restored?
- From: P14-005, M01-049

### CE3-023: Undo steps back through saved versions of the cut.
- What was going on: The owner chose saved revisions of the project file, capped and thinned, over a log of operations that must be replayed to know the state.
- What the product must do: Undo restores the previous saved version, and older versions are kept, thinned rather than lost all at once.
- Kind: 2
- From: D04-060

### CE3-024: Undo was refused offline and took ages online.
- What was going on: The owner: "undo doesn't seem to work in offline mode" and "undos take ages"; one undo across 521 cuts of nine hour-long interviews took 1.7 s.
- What the product must do: Undo works offline on unsent edits, never replays what was taken back, and online returns well under a second on long episodes.
- Kind: 3
- From: C05-076

### CE3-025: Redo history vanished when a note was saved beside an undo.
- What was going on: Saving a card's note at the same moment as an undo could wipe the redo history or make the file look changed by someone else.
- What the product must do: Notes, undos and redos in any order and timing never lose a redo step or trigger a false outside-change reload.
- Kind: 3
- From: C05-023

### CE3-026: Moving a whole section was refused with a word that did not apply.
- What was going on: The permission check asked where the cards came from instead of whether a cut list was open, blocking section moves, gaps and redo.
- What the product must do: With a cut list open, moving a whole section is one undoable edit, and no refusal names a concept that does not apply.
- Kind: 3
- From: P10-004

### CE3-027: An action that is refused must say so where the person is looking.
- What was going on: Delete on a selected card did nothing visible; split on a phone said nothing, its reason hidden off screen, in a tooltip, or naming keys a phone lacks.
- What the product must do: Every action gives a visible result or a reason where the person is looking on any device, naming something they can reach; a disabled control answers a tap.
- Kind: 3
- From: P07-052, L05-041

### CE3-028: A pending edit stopped showing when its card folded into a group.
- What was going on: A staged move folded into a collapsed group lost its marking, and a marker staged on a member was invisible, though both were still queued.
- What the product must do: Every staged (pending, not yet applied) edit and marker is visible in any grouping, so the editor can see it and take it back.
- Kind: 3
- From: D05-045

### CE3-029: A word at a cut's edge came and went.
- What was going on: Two places used different rules for whether an edge word belonged to a cut, so it appeared or vanished depending on which answered.
- What the product must do: Whether a word at a cut edge belongs to the cut is decided by one rule everywhere it is shown.
- Kind: 3
- From: D02-042

### CE3-030: Highlighted transcript text must become a card of exactly those words.
- What was going on: Selecting words in a montage clip's transcript matched text loosely, so the card that arrived was "not even close to what you highlighted".
- What the product must do: Dragging highlighted transcript text into the cut creates a card covering exactly the highlighted words of that clip.
- Kind: 3
- From: P09-051

### CE3-031: A run of cuts can be saved aside as a sequence with exact timing.
- What was going on: The owner: "a 'staged' but for exact sequences", "stored as a sequence with exact second timing, not word timing", auto-named, on its own tab.
- What the product must do: A run is stored and restored, by drag or at the playhead, with every span, fade, colour, note and the black before it exact; a run with a hole is refused.
- Kind: 2
- From: M01-050, P11-068, C06-044, D05-080

### CE3-032: Set-aside cuts live in the cut list, and panel tabs switch with Alt.
- What was going on: The owner chose a shelf of set-aside cuts kept inside the cut list but ignored when sending to Resolve, and Alt+1/2/3 for panel tabs.
- What the product must do: Set-aside cuts stay in the cut list but never reach Resolve; panel tabs switch with Alt and a digit and can also be clicked.
- Kind: 2
- From: M04-049

### CE3-033: A clip sits in exactly one bin, with an All view.
- What was going on: The owner chose strict one bin per clip over tag-like bins; bins belong to the episode, not to one cut list.
- What the product must do: Filing a clip moves it out of any other bin, deleting a bin unfiles its clips, All lists every clip, and every device sees the same bins.
- Kind: 2
- From: D05-068, C05-030

### CE3-034: Existing cut lists keep their exact Markdown format and open unchanged.
- What was going on: The owner: "the cut list should remain a cut.md as it currently is".
- What the product must do: Every cut list made before the rebuild opens, edits and saves in its present format with nothing lost.
- Kind: 2
- From: P19-019

### CE3-035: Two cut files were listed under the same name.
- What was going on: Lists showed an inner title copied from the file's source, so two different cut files read the same.
- What the product must do: Cut files are listed by their own file name, a differing inner title shown muted after it, and a new cut is titled after itself.
- Kind: 3
- From: C06-045, P12-016

### CE3-036: Section colours disappeared from a cut.
- What was going on: A montage cut's section colours vanished; no cause was recorded.
- What the product must do: Section colours persist through every edit, reload and import of a cut.
- Kind: 3
- State: outcome not found
- From: P13-018

## Playback and audio

### CE3-037: Chrome resumes a partly played file with a dated range request.
- What was going on: Chrome resumes a partly played file by asking for a byte range conditioned on a date, not a tag; a server ignoring that form sent the whole file and playback froze.
- What the product must do: Audio the browser has partly played resumes instantly, whichever form of resume request the browser sends.
- Kind: 1a
- From: P08-015

### CE3-038: Chrome lets an idle audio device sleep, so the first Play waits.
- What was going on: Chrome puts an idle audio output to sleep, and Play then waits for the device to wake.
- What the product must do: The first Play after a pause sounds without a wake-up delay.
- Kind: 1a
- From: C06-085

### CE3-039: A browser's plain audio player can only lower volume, never raise it.
- What was going on: The transcript played far quieter than the lane, which lifts quiet interviews by up to 18 dB, because plain playback cannot go above full level.
- What the product must do: Audio heard from the transcript gets the same level lift, master volume and limiting as the same moment on the lane.
- Kind: 1a
- From: P16-033, C06-020

### CE3-040: Any audio played in an Android web view stops the phone's music.
- What was going on: An Android web view takes full audio focus for any audio element playing aloud; a muted element routed elsewhere takes none.
- What the product must do: On Android the preview lets the phone's music keep playing, ducked, and releases it about 1.5 s after playback stops.
- Kind: 1a
- From: C06-068

### CE3-041: Preview loudness levelling must never touch the files.
- What was going on: The owner: "preview audio normalisation, so all peaks are the same", at a level he sets, that "should only affect preview and the waveforms, not the files themselves."
- What the product must do: A user-set level makes every clip preview and draw at the same loudness, and no media file changes.
- Kind: 2
- From: P08-017

### CE3-042: Speech played in one ear because a near-silent second mic counted as live.
- What was going on: Inputs with no speech peaked between -57 and -59 dB, just over the dead-channel floor, so the speech stayed in one ear.
- What the product must do: A channel peaking below -30 dB is treated as dead, and the live channel's speech plays in both ears.
- Kind: 3
- From: P14-015

### CE3-043: Playback stalled at the join into a clip that had just finished processing.
- What was going on: The next clip's player was prepared while its audio was still being made, failed, and that dead player was used at the join once the clip was ready.
- What the product must do: A clip that becomes ready while the page is open plays at its first join without a stall (under 100 ms); nothing prepared while unavailable is reused.
- Kind: 3
- From: C06-057, P13-015, M01-020

### CE3-044: A phone opening straight into the edit view never found a playable cut.
- What was going on: Audio readiness was re-checked only while the lane showed, so the edit view asked once, before the audio was ready.
- What the product must do: Every view that plays audio keeps checking until its clips are ready, tested from a cold start on a phone.
- Kind: 3
- From: G01-075

### CE3-045: The first cut list of an episode said "no audio sources" until reloaded.
- What was going on: Opening an episode's first cut list read seven 35-minute audio files; the page gave up after a few seconds and stayed stuck on the error.
- What the product must do: A slow first audio load shows loading and keeps retrying, including on Play, and never stays stuck on an error that has since cleared.
- Kind: 3
- State: outcome not found
- From: P17-034

### CE3-046: A momentary connection reset stopped the clip that was playing.
- What was going on: One reset marked the server down for 4 s, and the playing clip's next range request was refused on that guess.
- What the product must do: Audio, video and waveform requests always get a real attempt, unless the person chose to work offline.
- Kind: 3
- From: D04-052

### CE3-047: The picture drifted 0.13 s behind the sound during playback.
- What was going on: Median picture drift measured 0.133 to 0.137 s against a 0.12 s limit, after a correction for slow remote links over-corrected on the local network.
- What the product must do: During playback the picture stays within three frames of the sound, on the local network and over a slow remote link.
- Kind: 3
- State: still open
- From: D05-091

## Search and the transcript panel

### CE3-048: Pinyin search works with tones, without characters, and mixed with characters.
- What was going on: The owner wants "chu1" for first-tone chu, "chuqu" for 出去, "出qu", "guo王", and 我d to find 我的, 我得, 我德.
- What the product must do: A tone digit narrows to that tone, no digit matches all tones, partial and spaced syllables match, and Latin letters after characters match following syllables starting with them.
- Kind: 2
- From: P17-036, P07-068

### CE3-049: Search must reach every clip of the episode, not just those in the cut.
- What was going on: Clips the cut did not use were invisible to search; an episode can hold 200 clips and 139 MB of word timing.
- What the product must do: Search reaches every transcribed clip of the episode and returns sentence-level spans in the language spoken, each playable and draggable onto the lane.
- Kind: 3
- From: C05-006

### CE3-050: Search hits show which one is current, the count, and play from the word.
- What was going on: Highlights vanished during playback, there was no count, all hits looked alike, and playback from a hit started too early.
- What the product must do: The current hit is fully highlighted, others outlined, a count like 3/12 shows, highlights stay during playback, and playback starts just before the found word.
- Kind: 2
- From: P04-058

### CE3-051: Switching transcript re-ran the last search, and history searched again.
- What was going on: The owner: "if you switch transcripts it starts searching the search term just searched for"; each re-ask costs a minute, and history kept only the questions.
- What the product must do: Changing scope never starts a search; a past search's answer is kept with its history row and shown instantly, labelled as shown again.
- Kind: 2
- From: P11-019, C06-012, M01-044, C06-013

### CE3-052: Dropping one search result onto a cut wiped the rest of the results.
- What was going on: Every refresh cleared the transcript search results, and since edits answer instantly a dropped result took the others with it.
- What the product must do: Dropping one result never silently loses the others; results stay until the person runs a new search or closes them.
- Kind: 3
- State: still open
- Check: should transcript search results survive every refresh of the page's state?
- From: D03-023, L04-024

### CE3-053: An empty transcript panel must show how to open a transcript.
- What was going on: The owner: "there should be a button for this, and prompt. it's not obvious how to open the browser".
- What the product must do: The empty transcript panel shows a "Browse transcripts" button, its key, and a line on the other ways to open one.
- Kind: 2
- From: P17-035

### CE3-054: A montage is built from folders of clips by describing it.
- What was going on: The owner asked to pick clip folders, describe the montage and get ordered extracts; each revision re-read the whole episode, so it was slow and costly.
- What the product must do: A described montage becomes a cut list, a revision returns in seconds, unplaced quotes are listed, and results play and drag into the cut.
- Kind: 2
- From: D04-001, C05-007

## Shortening and the edit chat

### CE3-055: Assisted shortening shows every deletion where it was, restorable.
- What was going on: The owner: keep "the most emotionally powerful content"; "very sensitive", so "a doubled lane ... see all the content that got deleted and easily restore it".
- What the product must do: Each removed passage shows where it was, playable while scrubbing, with a one-line reason and a one-click restore.
- Kind: 2
- From: D01-014

### CE3-056: Tightening a cut keeps the best material and sets the rest aside.
- What was going on: The owner, cutting 160 minutes to 90: "keep only the best material that strengthens the argument and flow ... stage everything else".
- What the product must do: Tightening to a target length keeps the strongest material and transitions and moves everything removed to the shelf, never deleting it.
- Kind: 2
- From: P14-020

### CE3-057: Word-level cuts must name the words exactly and keep sentences whole.
- What was going on: The owner: "a lot of word-level and sentence-level work, so the model's understanding has to be extremely fine"; a guessed cut point is a blade in the wrong place.
- What the product must do: A proposed cut whose words do not match the card is refused; a mid-sentence cut needs a stated reason; a splice not reading as one breath keeps the card whole.
- Kind: 2
- From: D01-017

### CE3-058: A suggested mid-paragraph cut shows the sentence the join would make.
- What was going on: Removing words inside a paragraph creates a new joined sentence, which is what is really being approved and which no other view shows.
- What the product must do: A splice suggestion shows the struck words, kept head and tail, the joined sentence and a play button, or says it cannot be previewed.
- Kind: 2
- From: D03-052

### CE3-059: Shortening gave no suggestions for one section and many for another.
- What was going on: Sections answered in parallel wrote to the same record without coordination, so some answers erased others.
- What the product must do: When sections are processed in parallel, every section's result is kept.
- Kind: 3
- From: P10-057

### CE3-060: "Accept all" looped for ever when an item did not change.
- What was going on: Batch accept took the first pending item, acted and asked again; an answer that left it pending repeated it endlessly.
- What the product must do: A batch action checks each item actually changed and stops with a message when one did not.
- Kind: 3
- From: D03-056

### CE3-061: A chat turn can take a minute, and an idle-looking box gets pressed again.
- What was going on: A box showing nothing for a minute invites a second send, and a sentence replayed later against a changed cut would edit unseen.
- What the product must do: One turn at a time, the box locked with a ticking "thinking N s"; offline the chat refuses and never queues sentences for later.
- Kind: 3
- From: D03-042

### CE3-062: The assistant must never work from an outdated copy of the transcripts.
- What was going on: A conversation kept the transcripts and house style it opened with, so a paragraph that had since moved named the wrong words.
- What the product must do: When transcripts or the house style change, the next request works from the new ones and says which of the two changed.
- Kind: 3
- From: D01-032

### CE3-063: An assisted edit applies whole or not at all.
- What was going on: Two thirds of a request carried out is not what was asked, and undoing it under later edits takes away other work.
- What the product must do: If any step fails, every step already made is undone; undoing an assisted edit is refused once anything else has changed the cut since.
- Kind: 3
- From: D01-024

### CE3-064: New assistant models arrive with no action from the owner.
- What was going on: The owner wanted each family to "move to the latest" as released, "with no action from you"; the picker had stayed on its built-in list.
- What the product must do: Each model-family choice uses the newest model available without a code change or admin step, and a failure to stay current shows as a problem.
- Kind: 2
- From: L10-026, P12-002

## The English a cut shows

### CE3-065: A cut shows the transcript's own English for exactly the words it plays.
- What was going on: The owner: "The high quality english already exists so why doesn't it just load it in", and "you adjust a clip and it just pulls out the relevant translation section".
- What the product must do: Every cut and set-aside card, whole or trimmed, shows the transcript's own English for exactly the words it plays, never the whole paragraph's.
- Kind: 2
- From: P15-020, C06-071

## Working offline and on several devices

### CE3-066: Whether the editor is live or on its offline copy must be obvious.
- What was going on: The owner: "When it's offline and online it should display so it's obvious." The only sign was muted text inside a panel.
- What the product must do: A device holding an offline copy always shows a calm live chip or a loud offline-copy chip with waiting edits, in every view, with a message at each change.
- Kind: 2
- From: L05-036, P10-023, D04-033

### CE3-067: Every transcript in the episode comes down with the offline copy.
- What was going on: The owner: "do transcripts also get saved offline, they should"; only the four the cut used, of forty, came down.
- What the product must do: An offline download includes every transcript in the episode, those the cut uses first.
- Kind: 2
- From: C05-080

### CE3-068: Keeping a cut list on the device offers to keep its video too.
- What was going on: The offline keep saved audio and words only; the owner asked for the preview video too, as a choice.
- What the product must do: Keeping a cut list on a device offers an "include video" choice, and with it on the video plays offline with seeking.
- Kind: 2
- From: P16-001

### CE3-069: The offline rescue copy asked to save a growing file every minute.
- What was going on: While offline, the browser opened a save prompt once a minute, each time a new file of 1 to 1.7 MB.
- What the product must do: The rescue copy of unsent edits interrupts at most once per ten minutes and, where the browser allows, quietly overwrites one file chosen once.
- Kind: 3
- From: L08-038

### CE3-070: An offline session lost cuts and hid refusals when it reconnected.
- What was going on: Two splits of one card got the same name, refusals answered "ok", and replay failed on 17 edits.
- What the product must do: Offline edits get collision-free names, refusals show, and reconnecting replays every edit and follows any renaming the server made.
- Kind: 3
- From: M01-040

### CE3-071: Restoring a saved file of edits must never apply an edit twice.
- What was going on: A restored file can overlap the edits already waiting on the device, or belong to another cut list.
- What the product must do: A restore adds each edit once in oldest-first order, refuses another cut list's file naming both, and says how many it added.
- Kind: 3
- From: D04-046

### CE3-072: Unsynced offline work is never deleted to make room.
- What was going on: Storage fills up, and evicting the oldest copy would delete an editor's unsent edits; a cut list is read, not merged.
- What the product must do: When storage is short a download is refused showing both sizes, and nothing holding unsent edits is removed without asking.
- Kind: 3
- From: D04-049

### CE3-073: Looking at download sizes started work for every clip on the server.
- What was going on: Asking whether each clip's audio was ready started its preparation, so opening the download panel queued about thirty jobs.
- What the product must do: Showing download sizes starts no work; audio is prepared only when a download is actually requested.
- Kind: 3
- From: D04-038

### CE3-074: A phone and a desktop with staged edits diverged, and the last writer won.
- What was going on: Each browser kept its own copy of staged edits; the owner agreed one shared draft per timeline was a hard requirement.
- What the product must do: Staged edits are one draft per timeline: an edit on one device shows on the others within seconds, and a stale write is refused and replayed.
- Kind: 2
- From: D06-024

### CE3-075: Edit plans must have exactly one stored copy.
- What was going on: Keeping episode files on a second box was rejected, because two synced copies of the plans file is exactly how plans get lost.
- What the product must do: Each plan, note and draft has exactly one stored copy that every device reads and writes.
- Kind: 3
- From: D06-025

### CE3-076: Two writers of the same file erased each other's work.
- What was going on: Two machines each saved a shared file whole, wiping the other's additions; the cut file can also be edited by hand.
- What the product must do: Shared files are merged on save, and a write that finds the file changed underneath it refuses rather than overwrites.
- Kind: 3
- From: C04-075

### CE3-077: An expired sign-in let the editor keep editing an old version.
- What was going on: The owner: "it will allow me to keep editing even though I'm not working on the latest version." Refusals looked like empty states; queued edits were dropped as landed.
- What the product must do: When sign-in lapses or the episode closes, edits are refused with the reason and a fix, queued work is kept, conflicts go to the conflict view, recovery loads the latest.
- Kind: 3
- From: C06-063, D04-034

### CE3-078: The editor works over the internet on a computer without the project files.
- What was going on: The owner asked to use the editor remotely, including on a machine that holds none of the footage folders.
- What the product must do: The editor opens and plays from a remote computer or phone that holds none of the project's files.
- Kind: 2
- From: P07-073

## Resolve is optional

### CE3-079: The editor is standalone, with Resolve as a secondary feature.
- What was going on: The owner: drafting without Resolve is "by far the most useful mode"; "this can run without a timeline, run entirely without resolve"; "waiting for the Resolve agent" read as a fault.
- What the product must do: Every editing feature works with Resolve closed or absent and nothing shows as a fault; sending to, importing from and following Resolve are separate commands.
- Kind: 2
- From: D05-081, P09-020, C05-014

### CE3-080: The editor must not jump to Resolve's active timeline on load.
- What was going on: Refreshing switched to whatever timeline Resolve had active; the owner: it "should reopen to the same previously open project" and "default on load should be follow off".
- What the product must do: On load or refresh the editor reopens what was last open in that episode, and following Resolve is off until switched on.
- Kind: 2
- From: P09-022

### CE3-081: Scrolling never switches following off; one key in Resolve switches it on.
- What was going on: The owner asked that a key pressed in Resolve turn following on and jump to the current card; he later ruled that scrolling must not turn it off.
- What the product must do: Every way of scrolling leaves following on; it changes only through its own control or the key in Resolve, which also brings the current card into view.
- Kind: 2
- From: P07-047, D03-012

### CE3-082: Following failed to bring a new playhead card into view.
- What was going on: A guard against retrying a stuck scroll compared only the scroll position, so a new card at the old position was never scrolled to.
- What the product must do: With following on, every change of the card under the playhead brings that card into view.
- Kind: 3
- From: D03-013

### CE3-083: A person's key preset vanished after restarts, with no message.
- What was going on: The preset was not stored, and when no computer could drive Resolve for the page, only a log said so.
- What the product must do: A person's key preset survives restarts, and when no computer can drive Resolve for the page, the page says so.
- Kind: 3
- From: M01-042

## Phone and game controller

### CE3-084: Chrome blocks phone vibration until the page has had a real tap.
- What was going on: Chrome refuses a page's vibration request, logging an error, until the page has received a genuine tap.
- What the product must do: Haptic buzzes are optional: a blocked vibration never shows as an error and never changes what the action does.
- Kind: 1a
- From: D05-061

### CE3-085: Chrome keeps Ctrl plus a digit for its own tabs.
- What was going on: In a normal Chrome tab Ctrl+1 to Ctrl+8 switch browser tabs and never reach the page; in an installed app window they arrive.
- What the product must do: No in-page shortcut depends on Ctrl plus a digit.
- Kind: 1a
- From: C05-028, D05-069

### CE3-086: The phone edit view must stay full screen the whole time.
- What was going on: The phone's address bar and system bars come and go, changing the view's height mid-drag; the owner: "remains full screen constantly", "android only required".
- What the product must do: On Android the edit view runs with no browser or system bars, in portrait, with fixed geometry, installed as an app or by asking on the first touch.
- Kind: 2
- From: C04-083, D01-001

### CE3-087: Android's back gesture means "back to the cards" from every full-screen view.
- What was going on: Phone views had four different ways out.
- What the product must do: Back from any full-screen phone view returns to the cards without piling up history, and back from the cards leaves the page.
- Kind: 3
- From: D06-042

### CE3-088: Controller zoom keeps the view's centre; holding L3 aims a playhead jump.
- What was going on: The owner wanted zoom not tied to the playhead, a jump to "whatever I'm looking at", and the marker shown only while L3 is held: "it's distracting".
- What the product must do: Controller zoom keeps the view's centre; holding L3 shows the centre marker, panning moves it, release moves the playhead there; nothing shows otherwise.
- Kind: 2
- From: P11-031

### CE3-089: The controller never sends a cut, and a text box takes it over.
- What was going on: Sending to Resolve and switching modes stay on the keyboard, and typing in a box must not trigger edits.
- What the product must do: No controller input sends to Resolve, and while a text box has focus only the controller's leave, step and play buttons act.
- Kind: 3
- From: C06-033

### CE3-090: A held controller button keeps driving where it started after focus moves.
- What was going on: Focus could switch between lane and transcript under a held trigger or bumper, so a shuttle or edge drag acted on the wrong place.
- What the product must do: A hold acts only on the place it started in, until released, whatever focus does meanwhile.
- Kind: 3
- From: D06-048

### CE3-091: Leaving the transcript took one controller press, coming back took two.
- What was going on: The controller's panel button cycled through three panels.
- What the product must do: One controller press moves from the transcript to the lane, and one press moves back.
- Kind: 3
- From: P18-013

## The page: header, warnings and redrawing

### CE3-092: The desktop editor is one whole window, like Resolve.
- What was going on: The owner: "like it's one whole window, somewhat like resolve": no system title bar, the header is the drag area.
- What the product must do: The desktop editor shows as one window whose header doubles as its title bar, with the window buttons in the editor's colours.
- Kind: 2
- State: fixed, never shipped
- From: C06-077

### CE3-093: The header stays on one line, and long names shorten.
- What was going on: Added buttons wrapped the header onto several lines; a long timeline name pushed controls off the page and left a blank strip at the bottom.
- What the product must do: The header stays one line at desktop widths, long names end in an ellipsis with every control visible, and content fills the window.
- Kind: 2
- From: P04-070, P09-055

### CE3-094: The audio preview bar matches the page and appears only when needed.
- What was going on: The owner found the player "really ugly", always shown, cut off at the top; he wants it dark blue, semi-transparent, with a neon azure seek bar.
- What the product must do: The player animates in only while audio is wanted, sits under the insert bar below the header, and deselecting text hides the insert bar.
- Kind: 2
- From: P04-061

### CE3-095: Standing warnings must not pop up and shift the page.
- What was going on: The owner: "having it constantly pop up and shift the main screen around is highly annoying"; cards also showed "through the top here in a slit."
- What the product must do: Ongoing conditions go to a problems window; only a failed edit or send shows on the page; nothing above the cards moves or lets cards show through.
- Kind: 2
- From: P10-059, C05-074, C06-008, P11-057

### CE3-096: Hovering a menu entry made the whole menu judder.
- What was going on: Hovering made a status line wrap onto two lines, and a list redrawn from scratch on each refresh jumped under the mouse.
- What the product must do: Hovering never changes another element's size or position, and an open list that refreshes updates in place.
- Kind: 3
- From: P07-066, P08-012

### CE3-097: Background updates made the page choppy and the lane flash.
- What was going on: Each arriving answer rebuilt all 519 cards, 29 times in 12 s with 130 to 160 ms gaps; the shortening panel redrew the lane 22 times where 1 was needed.
- What the product must do: Background answers update only the cards they concern, and a side panel redraws the lane only when what the lane shows has changed.
- Kind: 3
- From: D02-039, D02-058

### CE3-098: A page must never flash another timeline's cards.
- What was going on: Opening a cut list could briefly show cards remembered from another timeline before its own loaded.
- What the product must do: An editor page shows only its own cut list's cards, never another's, not even for a moment while loading.
- Kind: 3
- From: D02-062

### CE3-099: Inside the dashboard there was no way back from the editor.
- What was going on: When the editor ran within the dashboard, nothing on its page led back.
- What the product must do: The editor, when part of the dashboard, always shows a one-click way back to it.
- Kind: 3
- From: C05-087

### CE3-100: One raw control character in page code kills the whole page in browsers.
- What was going on: A raw NUL byte in an inline script passes checks outside a browser, but the browser's HTML parser turns it into U+FFFD and the page's script dies at load.
- What the product must do: Page sources are checked for raw control characters, and the editor is tested loaded in a real Chrome and Safari before release.
- Kind: 1a
- From: C05-058, D04-047, M01-041

## Opening episodes

### CE3-101: The episode picker looks like the studio's folders, recently opened first.
- What was going on: The picker was one flat table; the owner asked for the year and show folders, "ordered by most recently opened instead of date".
- What the product must do: Episodes show in their folders in the person's last-opened order, filter by year, sort by last opened, size, date and name, search by keyboard, and remember open folders.
- Kind: 2
- From: C04-003, P12-024

### CE3-102: The episode list was empty on the studio's real folder layout.
- What was going on: Episodes sit four levels down (share, year, show, episode); the scan stopped at three and tests used two, and an empty list looked legitimate.
- What the product must do: The episode list reaches the depth the studio really uses, is tested on that real layout, and an empty list says where it looked.
- Kind: 3
- From: L08-041, C03-067, M01-035

### CE3-103: One passing failure left an episode or transcript unusable until restart.
- What was going on: A failed open (NAS share not up yet) marked the episode failed until redeploy; a swallowed transcript read failure left every clip's transcript empty.
- What the product must do: A failed open or read is shown, retried (opens spaced about 20 s apart), and one unreadable clip never stops other transcripts loading.
- Kind: 3
- From: L09-001, D03-005

### CE3-104: After switching episode the panel claimed there were no documents.
- What was going on: Switching episode cleared the document list, but a refresh throttle blocked the refetch for 30 seconds.
- What the product must do: Switching episode refreshes the document list at once, and a failed fetch is never shown as "none".
- Kind: 3
- From: L03-081

### CE3-105: An editor blocked by a limit on open episodes had nothing they could do.
- What was going on: One editor could hold every open-episode place, only an admin could free one, the refusal named others' episodes, and anyone could close a shared one.
- What the product must do: A person may close an episode they are in or one idle 15 minutes; closing one others are using is admin-only, named and warned; refusals reveal no one's work.
- Kind: 3
- From: H06-070, L09-003

### CE3-106: A trial or read-only editor must never write to the real projects.
- What was going on: The owner: "let me test it on a live vault, don't replace the current timeline cards"; a read-only copy nearly wrote an empty word file over the real one on close.
- What the product must do: A trial or read-only editor reads the real projects but writes nothing to them unless switched, and two versions never drop each other's data.
- Kind: 2
- From: P15-019, C06-082

### CE3-107: When the server stops, open cut lists are saved first.
- What was going on: The server gets 10 seconds to stop, but about 20 seconds of other shutdown steps ran before open cut lists were saved, so that step was killed.
- What the product must do: On a normal server stop, every open cut list is saved first, within the stop grace period.
- Kind: 3
- State: still open
- From: H08-064

## Sealed

### CE3-S01: A waveform drawn one rectangle per pixel column costs 198 ms a frame.
- What was going on: About 3,400 sub-shapes per path loaded the browser's graphics process; one outline per clip took 5.6 ms, and evicting cached images mid-frame forced reallocations.
- What the product must do: Each clip's waveform is drawn as one outline, cached image sizes are capped, and no image being drawn this frame is evicted.
- Kind: 1b
- Tool: browser 2D canvas
- From: L10-082

### CE3-S02: An older assistant command-line tool refuses a newer model's exact name.
- What was going on: The installed tool rejects a model id newer than its catalogue with "update required", but resolves family aliases itself; it can report an error with a zero exit code.
- What the product must do: Models are asked for by family alias unless pinned, the tool keeps itself updated, a zero-exit error counts as failure, and a refusal names the outdated tool.
- Kind: 1b
- Tool: Claude Code CLI (model ids versus aliases, self-update)
- From: L10-027, P12-003, M01-032, P10-046

### CE3-S03: The first visit after a release saved nothing for offline use.
- What was going on: Re-registering the page's offline cache handler at the same address does not check for a new one, and the page's own check raced the new one taking control.
- What the product must do: After a release, one online open is enough for the editor to work offline again.
- Kind: 1b
- Tool: browser service workers
- From: C04-031

## Removed

- D02-034 | superseded by CE3-081
- P04-049 | superseded by CE3-065
