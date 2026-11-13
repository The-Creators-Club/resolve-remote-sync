# Timeline Cards: the editor (piece 1)

## Chinese text and matching

### CE1-001: Written Chinese has no word spaces, even when phrases are spaced apart.
- What was going on: Each Chinese character is its own word; counting by spaces found 1 word in 53 on phrase-spaced Mandarin and refused every word-level cut.
- What the product must do: Word matching, word lighting and word-level cuts count Chinese characters as words whatever spacing appears, and the playing word lights in both languages.
- Kind: 1a
- From: C06-074, C05-072

### CE1-002: A Chinese search finds the same words in Simplified, Traditional or pinyin.
- What was going on: The owner: "the simp>trad agnostic search which we used to have disappeared"; the matching was missing on one install and search silently went literal.
- What the product must do: Transcript search matches Simplified, Traditional and pinyin on every install, and if that matching is unavailable the page says so instead of quietly matching less.
- Kind: 2
- From: C03-035, P04-059, P08-047, G01-064

### CE1-003: An edit failed because the selection was Simplified and the timed words Traditional.
- What was going on: A transcript export was in Simplified characters while the timed words had been converted to Traditional, so the edit "did not go through".
- What the product must do: Any matching of Mandarin text against timed words treats the Simplified and Traditional forms of a character as equal.
- Kind: 3
- From: C05-046

## Search and the transcript panel

### CE1-004: Search hits show the paragraph itself, never the assistant's retyped copy.
- What was going on: Answers repeated each passage plus its neighbours, about 8,000 characters and 139 s a turn; the owner: "the result itself is enough"; one-person searches read every transcript.
- What the product must do: The assistant returns only paragraph references and reasons; the page shows each matched paragraph from the transcript, 5 to 50 hits as chosen; a one-person search reads only theirs.
- Kind: 2
- From: P10-029, C05-055, D03-028, L05-027

### CE1-005: A meaning search named paragraphs and clips the episode does not have.
- What was going on: The assistant answers with paragraph references; some matched no transcript, so jumping went nowhere, and clips missing from the episode were returned.
- What the product must do: Every result is checked against the episode's real transcripts, unknown ones dropped, shown text is the transcript's, and the count reads like "3 of 5" when some were dropped.
- Kind: 3
- From: D03-027

### CE1-006: Search has a concept mode and a closest-literal-wording mode.
- What was going on: The owner: concept mode finds the idea; literal mode finds wordings "as close as possible" ("extraordinary": "amazing", "something special") and may suggest splices of sentence pieces.
- What the product must do: Literal mode returns the nearest real wordings in the original language only, never searching the English, and can propose multi-piece splices that form the phrase.
- Kind: 2
- From: P12-004

### CE1-007: Closing the search window abandoned a search already paid for.
- What was going on: The owner: on coming back "it should show that a search is still in progress if it hasn't completed yet. There should be a progress bar".
- What the product must do: A running search survives its window closing; reopening or asking the same question rejoins it with an estimated progress bar, and results arrive without searching again.
- Kind: 3
- From: C06-014, P12-001

### CE1-008: Transcript playback was slow and failed silently remotely, while the lane played fine.
- What was going on: The panel reloaded audio on every click, waited up to 8 s on a lookup before playing, and fell back to the full recording, about 38 times the compressed copy.
- What the product must do: Playing from the transcript starts as fast as the lane over a slow link, never reloads the same clip or fetches a full-size file, and names any failure on screen.
- Kind: 3
- From: L05-064, M02-070, C05-063, P10-031

### CE1-009: A clicked transcript word sets a playhead that Space plays from.
- What was going on: The owner asked for a transcript playhead: click a word, Space plays on, holding Space skims at 2x, Esc or a new selection drops it.
- What the product must do: Clicking a transcript word sets a playhead; Space plays continuously from it, held Space plays at 2x, and Esc clears it.
- Kind: 2
- From: D07-012

### CE1-010: Only one thing plays at a time, across views and windows.
- What was going on: The lane and the transcript are two players over the same words, and both could sound together, including across pop-out windows.
- What the product must do: Starting playback anywhere, in any window of the same episode, pauses every other player; two audio sources never sound together.
- Kind: 2
- From: D03-021, D07-011, P09-063, L04-018

### CE1-011: An interviewee vanished from the people list when their transcript could not be tied in.
- What was going on: One of 16 interviewees disappeared while his cards still had text, and the page blamed missing word timings.
- What the product must do: An interviewee stays listed whatever fails with their transcript, and the page names the actual problem, such as "transcript not linked".
- Kind: 3
- From: C06-047

### CE1-012: "Interview" means a transcript filed under a named person.
- What was going on: News clips with reporter speaker labels counted as interviewees; the owner: "'Interview' means one of my documentary interviews, so a transcript inside a named person folder".
- What the product must do: Only transcripts filed under a named person appear among the people; the browser lists every transcript and cut list in the episode, filterable, searchable and multi-selectable.
- Kind: 2
- From: C05-031, P09-049

## The English a cut shows

### CE1-013: A cut's English covered only one of the paragraphs it spans.
- What was going on: An older, shorter cut's stored English, missing a phrase, was trusted over the transcript, then stored again for the longer cut.
- What the product must do: A cut's English is built from the transcript paragraphs it spans, starting and stopping with its spoken words; older cuts' English is used only where paragraphs cannot cover it.
- Kind: 3
- From: P18-016, P16-029, C06-072

### CE1-014: A clip running over an interviewer's question showed no English at all.
- What was going on: Interview questions exist only in the timed speech, not in any transcript paragraph; the owner: "it should not refuse to show interview questions".
- What the product must do: Words no paragraph holds show as a gap in the original language, and the rest of the clip still shows its English, marked approximate.
- Kind: 3
- From: P17-031

### CE1-015: A re-cut card showed its paragraph's whole English, which read as clips shifted.
- What was going on: Split, trimmed or extended cards kept the parent paragraph's English or English matched by text; the owner read the wrong line as clips "shifted by seconds".
- What the product must do: A cut's English line translates exactly its own span, shows the original words until that exists, and adds nothing under speech already in English.
- Kind: 3
- From: P08-020, D02-041, M04-056, L05-054, C05-025, P09-030

### CE1-016: Clips said "no English yet" while their English existed or was still loading.
- What was going on: Split and trimmed pieces never asked for their own English, English vanished a second after load, and one message covered both waiting and missing.
- What the product must do: A cut's English appears within a frame of the edit; while being worked out it reads "loading…"; if none exists it gives the exact reason, such as "not aligned yet".
- Kind: 3
- From: P16-020, C06-073, P17-033

### CE1-017: A quick machine translation is never shown.
- What was going on: A clip showed poor English the owner took for a web translator's fallback; he never wants to see one again.
- What the product must do: Every English line shown comes from the transcript's own translation; no quick machine-translation draft is ever fetched or displayed.
- Kind: 2
- From: P16-028, C06-055, M04-101

### CE1-018: Selecting English text acts on the matching original words.
- What was going on: The owner wants a selection in the translation mapped to the smallest matching span of original words.
- What the product must do: Any English selection uses the timings of its matching original words, and a fallback to the whole sentence is labelled approximate.
- Kind: 2
- From: M04-114

### CE1-019: The spoken word and its English equivalent light together everywhere.
- What was going on: The owner: "playhead over 1 word in Ukranian = that word highlighted in Ukrainian and its English equivalent"; the lit English jumped between phrases or sat words off.
- What the product must do: With no setup the spoken word and its English equivalent light on the lane, cards and transcript, even after trims; a word with no clear English lights nothing.
- Kind: 2
- From: P16-013, P15-028, P04-062

### CE1-020: A word-for-word literal English line can be toggled on under each clip.
- What was going on: The owner: "a purely literal translation of the foreign language which is also timed word for word for comparison and you can toggle it on and off".
- What the product must do: A toggle, off by default, shows a literal English line under every clip, each word lit as its spoken word plays.
- Kind: 2
- From: P15-039

## House style and the assistant

### CE1-021: Interviewer questions are never in the film.
- What was going on: The owner: "no questions included in the edit ever, generate suspense by tactically withholding information"; a rule held only by asking the assistant will eventually break.
- What the product must do: Any edit, by hand or by the assistant, that would put an interviewer's question in the cut is refused with a reason before anything changes.
- Kind: 2
- From: D05-082, D01-028

### CE1-022: The film reads as one conversation between people who never met.
- What was going on: The owner: people answering each other "'accidentally' is a core part of my style ... one large conversation"; suspense by withholding, partial sentences when tenser, splices highlighted.
- What the product must do: Assisted ordering and cutting see cards in cut order and choose each as a reply to the one before; the house style is the owner's to edit per series.
- Kind: 2
- From: D01-029, C05-065, P10-043

### CE1-023: An assistant cut point slightly off its quoted words was refused, or guessed.
- What was going on: The assistant names words by position and by quote; in Chinese the position was often a character off, and a next-best guess cuts in the wrong place.
- What the product must do: A position slightly off its quote snaps to the quoted words; words not found, ambiguous, or without word timings are refused in a sentence quoting the real words.
- Kind: 3
- From: P10-055, D03-054, D01-025

### CE1-024: When the assistant uses part of a paragraph, it highlights exactly that part.
- What was going on: The owner: "for splices and sections/sentences/words within a paragraph it should add a highlight to the specific bit it wants to pick out".
- What the product must do: Any assisted edit that keeps or inserts part of a paragraph highlights exactly the words that will play, and a highlight that cannot fit never costs the card.
- Kind: 2
- From: D01-027, P10-044

### CE1-025: The edit chat proposes changes, and only the one clicked is applied.
- What was going on: The owner: "first gives me a suggestion (or multiple if judged useful) ... then I click which change to make, or I give it more instructions".
- What the product must do: A chat turn shows previewed proposals and changes nothing until one is clicked, as one undo step; an impossible proposal stays with its reason; a follow-up revises proposals.
- Kind: 2
- From: C05-064, D03-043, P10-045, D01-023, L05-067

### CE1-026: The edit chat understands "that bit ... at the playhead".
- What was going on: The owner: "insert that bit where [he] talks about model airplanes at the playhead", or "make the current card selection a new group".
- What the product must do: Each request carries the playhead, selection and open transcript; the playhead's card is found from its time; inserts are real spans from any interview; an empty selection is refused in words.
- Kind: 2
- From: D03-041, D01-026, P10-042, M01-030

### CE1-027: The model a feature asks for must be the model that answers.
- What was going on: One route to the assistant dropped the requested model, so answers came from its default, looked plausible, and nothing showed it for six weeks.
- What the product must do: The model a person or feature picks answers on every route, and each call records which model answered.
- Kind: 3
- From: L05-066, M01-031

## Shortening

### CE1-028: Shortening only suggests; nothing changes until the editor accepts each one.
- What was going on: The owner: the shorten pass "must NEVER delete or stage anything by itself. It produces SUGGESTIONS ... the editor ... accepts or dismisses it individually".
- What the product must do: Shortening to a target, editable per section, lists removals with reasons wherever the cut shows; each is accepted, undone or dismissed alone, and dismissed ones can return.
- Kind: 2
- From: P10-051, C05-067, D03-049, M02-097, D01-015

### CE1-029: Shortening only removes, keeps sentences whole and protects the story.
- What was going on: The owner wanted a target length keeping structure and the most emotional content; story rules held only by asking the assistant will eventually break.
- What the product must do: Each suggestion is checked to only remove, never a noted card or a section's last card unless the section goes whole with its heading kept, cutting at sentence ends unless justified.
- Kind: 2
- From: D01-018, D03-053, C05-068

### CE1-030: Accepting one suggestion broke the next one on the same card.
- What was going on: Accepting a suggestion splits or renames the card the next suggestion is about, and the editor may hand-edit between clicks.
- What the product must do: Each suggestion still applies correctly after others on the same paragraph were accepted or hand edits made, and undoing an accept returns it to pending.
- Kind: 3
- From: D03-051

### CE1-031: A shortened or failed section could not be cut again after a reload.
- What was going on: Section answers arriving together overwrote each other, rerun buttons and progress lived only in the open page, and a call hung forever across a server restart.
- What the product must do: Every section's answer is kept with the file; any section can be cut again after reload; progress counts real running work; a call fails visibly within about eleven minutes.
- Kind: 3
- From: P10-056, C05-071, P11-003, P11-002

### CE1-032: Keep, free or drop choices on shortening rows reverted to free.
- What was going on: Recalculating the length budget reused the choices from when the pass started, overwriting ones clicked later.
- What the product must do: A keep, drop or free choice stays after every recalculation and reload until the editor changes it.
- Kind: 3
- From: M01-052, P10-054

## Editing: selecting, deleting, inserting

### CE1-033: Delete on one card removed an eight-cut selection scrolled out of view.
- What was going on: A box selection stayed active while the cursor sat on another card, so Delete there removed all eight unseen selected cuts.
- What the product must do: An action applies to the selection only while the cursor card is inside it; otherwise it touches that one card and the selection clears; every delete is undoable.
- Kind: 3
- From: M04-054, D05-021, P07-070

### CE1-034: After a multi-selection, Delete removed only the first card clicked.
- What was going on: A card was clicked, then others boxed or added, and the cursor stayed outside the new selection, so Delete acted on the single card.
- What the product must do: However a selection is built, by box, tap, drag or modifier click, the cursor lands inside it, so Delete removes every selected card.
- Kind: 3
- From: P11-020, C06-015

### CE1-035: A single Delete press never deletes; a second within 3 seconds does.
- What was going on: The owner asked that the first press arm delete (the card turns red) and a second within 3 s delete, on phone and desktop; a held key repeats.
- What the product must do: The first press arms for 3 s with a visible count that survives redraws; a held key never confirms; on a phone delete sits farthest from the resting thumb.
- Kind: 2
- From: D05-020, C06-070, L05-056

### CE1-036: The delete confirmation promised a Resolve edit on a file that never touches Resolve.
- What was going on: The arm message read "Delete again to ripple-delete this cut in Resolve" before checking where the edit would land, even in a read-only view.
- What the product must do: Every confirm message names where the edit will land, and a read-only view refuses at the first press.
- Kind: 3
- From: D05-019

### CE1-037: A deleted cut moves to the staged shelf under the section it came from.
- What was going on: The owner: "when you delete it moves the clip into the staged section for the section you're currently in ... it disappears from the lane and cards but goes to staged".
- What the product must do: A deleted cut leaves the cards and lane and appears on the staged shelf, labelled with its section, keeping its words, English, colour and note, ready to put back.
- Kind: 2
- From: D05-018, P11-058, C06-009

### CE1-038: A gap behaves like any other clip.
- What was going on: The owner: "Gaps should behave like any other clip"; gaps carried along with the next cut "moved around weirdly" and could not be dragged.
- What the product must do: A gap stays put when neighbours move and can be selected, dragged to another boundary, resized, deleted and played as silence, each one undo; a gap at the very end is refused.
- Kind: 2
- From: M04-113, L05-051, P10-021

### CE1-039: Deleting a clip also deleted the unselected gap beside it.
- What was going on: The owner: "it will delete the gap also, even though the gap is not selected"; Resolve's own ripple delete keeps it.
- What the product must do: Deleting a cut keeps every unselected gap beside it; only black with nothing after it goes.
- Kind: 3
- From: P11-021, M01-045, C06-025

### CE1-040: A dropped clip landed on the other side of a gap from the drawn line.
- What was going on: The owner: "clips not landing correctly on the right or left side of a gap even though the 'selection' red line is there"; pointer position chose the side.
- What the product must do: A drop lands exactly where its insertion line is drawn, on either side of a gap, and any hint text agrees with it.
- Kind: 3
- From: C06-026

### CE1-041: Next and previous edit stopped short of or past the cut point after a gap.
- What was going on: Cut points were counted without gaps while the playhead counted them, so every jump after one 50-frame gap was 50 frames off.
- What the product must do: Next and previous edit land exactly on the cut point, before and after gaps, in both directions, at 25 and 29.97 fps.
- Kind: 3
- From: L05-052, P10-025

### CE1-042: Inserting highlighted transcript words put a different passage in the cut.
- What was going on: The words were matched at their first occurrence in the whole interview, so an earlier repeat landed, or a miss silently became the whole paragraph.
- What the product must do: One action inserts exactly the highlighted span, within two seconds of its own time; if only the whole paragraph can be placed, the page says so with its length.
- Kind: 3
- From: C05-039, L05-050, P10-020, M01-029, M03-050, P04-055

### CE1-043: The insert key opened the chat because a click had moved keyboard focus.
- What was going on: Selecting transcript words, clicking the target card, then pressing the insert key opened the assistant instead, since the click moved focus.
- What the product must do: While transcript words are selected, the insert key inserts them wherever keyboard focus is.
- Kind: 3
- From: C05-084, P11-017

### CE1-044: Selected words inside a clip can be deleted, highlighted or split.
- What was going on: The owner chose to edit by selecting words on the strip: delete removes only them, highlight marks the playing part, split cuts there.
- What the product must do: Delete, highlight and split act on a word selection inside a clip, with the sound ramped at every new join.
- Kind: 2
- From: M04-111

### CE1-045: Highlighted words stay on exactly the same words through trims.
- What was going on: Words highlighted while planning must show on the card, and the owner asked that highlights survive every view and every trim.
- What the product must do: A highlight shows on the card without markup, stays on the same words after any trim, and on a translated card marks the original words.
- Kind: 2
- From: D05-040, D07-013, L04-020

### CE1-046: A clip name with square brackets broke the cut list.
- What was going on: Downloaded YouTube clips carry their video id in square brackets, and a line break in a speaker name was read back as a new cut.
- What the product must do: Any punctuation or line break in a name or reference survives save and reload unchanged, and no supplied text can create, remove or change a cut.
- Kind: 3
- From: P09-047, C05-033, D05-086

### CE1-047: New found material goes after the editor's existing cut, not into it.
- What was going on: The owner had whittled a cut to "semi useful bits": "add the new material to the end of this cut file and I will continue going through it".
- What the product must do: Adding found material to an existing cut appends it after the last cut and leaves every existing cut and its order unchanged.
- Kind: 2
- From: P13-021

### CE1-048: Making a new cut list could overwrite an existing one.
- What was going on: Creating a cut list from a planning board can reuse a name already in the episode, which would destroy that list.
- What the product must do: A new cut list shows its counts before it is made, and a name already taken is refused before anything is converted.
- Kind: 3
- From: D05-035

### CE1-049: A file dropped into a browser page gives its name and size, never its path.
- What was going on: Browsers hand a page only a dropped file's name and size, so a clip dragged in must be found among the episode's files.
- What the product must do: Dropped media is found by name and size inside the episode, and the page says which files were not found or still lack a transcript or proxy.
- Kind: 1a
- From: C05-032, M04-050

## Notes and the staged shelf

### CE1-050: Notes attach to cards and gaps and show in yellow.
- What was going on: The owner asked for notes on gaps and cards, shown beneath them highlighted yellow, and "in the lane it should have a yellow square in the top right corner".
- What the product must do: Any card or gap takes a note shown beneath it on yellow, and its lane clip shows a yellow square in the top right corner.
- Kind: 2
- From: P07-037, P08-034

### CE1-051: Every note lives inside the cut list.
- What was going on: The owner wants every note, gap notes and section summaries included, in the cut list itself, never in a side file.
- What the product must do: All notes are stored in the cut list as ordinary undoable, synced edits, and notes from older side files are brought in once.
- Kind: 2
- From: M04-117

### CE1-052: Clicking "add note" appeared to do nothing.
- What was going on: The note editor opened, focused, in a column a few pixels wide beside the card text, so typing went somewhere invisible.
- What the product must do: A note editor, like every editor a gesture opens, appears inside its card at full text width, in every density and on a phone, from the first keystroke.
- Kind: 3
- From: D03-022, P09-058, L04-015, P10-001

### CE1-053: Note and section rows can be deleted in place and moved.
- What was going on: The owner: "the green sections should be deletable or movable, they are annoying".
- What the product must do: Every note or section row in the card list can be deleted in place with one click, as one undoable revision, and dragged to another position.
- Kind: 2
- From: P09-057, C05-038

### CE1-054: Named markers vanished after a reload.
- What was going on: Marker edits were refused and the page dropped the refusal, so markers lived only in the browser until the next reload.
- What the product must do: A marker, with its name, colour, note and length, survives reload and restart like any other edit.
- Kind: 3
- From: P08-033

### CE1-055: A staged shelf holds cuts taken out of the cut without deleting them.
- What was going on: The owner asked for a "staged clips" tab kept inside the cut file, whose cards look like timeline cards and reorder the same way.
- What the product must do: Cards dragged from the list or lane onto the shelf leave the cut but stay in the file, play on click, reorder, and drop back exactly where the line shows.
- Kind: 2
- From: P09-048, C05-029

### CE1-056: A card dropped on the staged shelf vanished and landed last.
- What was going on: The drop filed the card under the plain staged heading while another category was on show, with no position, so it went out of sight at the end.
- What the product must do: A card dropped on the shelf lands in the category being viewed, at the slot the insertion line showed, and is scrolled into view.
- Kind: 3
- From: L05-047, P10-015, D05-079

### CE1-057: Staged cards play from a chosen word, and categories open from anywhere.
- What was going on: The owner: staged cards "should have the same playhead selector as transcripts", and categories should open "from anywhere as an overlay without scrolling".
- What the product must do: Clicking a word on a staged card plays from it to the cut's end, and a key opens the category picker from any view.
- Kind: 2
- From: D05-078

### CE1-058: Staged cards can be filed into categories the editor names.
- What was going on: The owner: "right click > add to category > select existing categories or add a new one", with a strip filtering the shelf; a planning board's groups come across.
- What the product must do: Categories keep document order, never alphabetical; a card sits in one; deleting a category returns its cards to the plain shelf; a board made into a cut brings its groups.
- Kind: 2
- From: P09-059, D05-072

### CE1-059: Cards could not be dragged into shelf categories, or far up the list.
- What was going on: The category strip scrolled 1624 px out of view, auto-scroll moved the window not the panel, refreshes replaced the target mid-drag, and the wheel did nothing.
- What the product must do: While dragging, every drop target stays reachable and still, the wheel and edge scroll the panel under the pointer, and the target stays lit until the drop.
- Kind: 3
- From: D05-075, P07-051

### CE1-060: Chrome fires no drag-end when the dragged card is removed from the page.
- What was going on: When a dropped card is removed from the list, Chrome fires no drag-end, so the page believed a drag was running and stopped updating until reloaded.
- What the product must do: After any drop the page takes updates again at once, even when the dragged card is gone from it.
- Kind: 1a
- From: D05-077

### CE1-061: Browsers report "drag left" when the pointer moves onto a target's own child.
- What was going on: Moving over a drop target's count or close button fires a leave event on the target, so it was unlit at the moment of the drop.
- What the product must do: A drop target stays highlighted while the pointer is anywhere inside it, its children included.
- Kind: 1a
- From: D05-076

## The cut list, undo and saving

### CE1-062: The cut list is one plain, hand-editable file stored with the episode.
- What was going on: The owner: the way projects were stored was "extremely confusing"; he wants "a plain text format ... platform agnostic" beside the transcripts.
- What the product must do: A cut list is readable and editable by hand, names clips as their identity, stores seconds with each clip's frame rate, keeps every revision for undo, and opens without Resolve.
- Kind: 2
- From: D04-059, M04-122

### CE1-063: Opening a project changed files in the episode folder.
- What was going on: Opening recomputes card words from transcripts, and showing a read-only view filled a translation store, both writing to disk before any edit.
- What the product must do: Opening, browsing and playing leave every file in the episode byte-identical until the editor makes an edit or switches writing on.
- Kind: 3
- From: D05-022, D04-072

### CE1-064: Acknowledged edits were lost to a second writer, an undo race or a crash.
- What was going on: Two servers on one cut list lost confirmed edits, an undo racing an edit wiped it, and a crash mid-save ate an outside edit to the file.
- What the product must do: An acknowledged edit, or an outside edit to the file, survives a second writer, an undo racing it, and a crash at any point.
- Kind: 3
- From: D05-085

### CE1-065: The cut list changed on disk while the editor had it open.
- What was going on: Another program can edit the cut list while it is open, and an edit applied to the stale copy would overwrite that change.
- What the product must do: An outside change to the open cut list shows within 2 s, and an edit made against the old copy is refused with a message, never merged silently.
- Kind: 3
- From: D05-017

### CE1-066: One cut list saved from two places at once can lose one side's change.
- What was going on: The browser editor and a laptop app edited the same cut list; both merged this time, but nothing stopped two writers overwriting each other.
- What the product must do: When one cut list is saved from two places at once, both changes are kept or the second is refused, with the conflict shown to both people.
- Kind: 3
- State: still open
- From: P16-006, H08-074

### CE1-067: Every staged edit is saved the moment it is made.
- What was going on: A plan of staged edits lived only in memory, so a timeline switch, a restart, or a second reader's read without the moves wiped hours of work.
- What the product must do: Every staged edit is saved on change, per timeline, survives switches and restarts, can be reopened as a file, and a move whose cuts are missing from a read is held.
- Kind: 3
- From: P07-042, M03-045

## Edit speed and answering the editor

### CE1-068: Every edit must feel instant, a split included.
- What was going on: Edits waited for a slow confirmation and greyed the list: over 2 s, then 500-600 ms per edit from the phone; a split alone waited a 300-700 ms round trip.
- What the product must do: On a 433-cut project every edit, split included, is drawn within about 100 ms and saved behind it, greying nothing; a refusal takes it back with the reason; selection survives undo.
- Kind: 2
- From: D04-057, P09-033, C05-020, M01-048, P10-007, L05-053

### CE1-069: Edits grew slow on a 500-minute, 1,500-card cut.
- What was going on: A trim near the start ripples every later card, and each reply resent all of them whole: 2.3 MB against 27 KB near the end.
- What the product must do: An edit's reply carries only what changed, so a trim at the start of a 1,500-card cut appears as fast as one at the end.
- Kind: 3
- From: C06-040, P11-065

### CE1-070: Rapid edit keys silently did nothing.
- What was going on: A status update arriving just before an edit's confirmation faked it, so the page fell behind and refused later edits with no message.
- What the product must do: Every edit gesture takes effect or shows why it was refused, and rapid successive edits are all applied in order.
- Kind: 3
- From: M04-055, P09-034

### CE1-071: Edits were refused at random as "the timeline changed", then went through.
- What was going on: Background work republished the cut every 12 s without moving any card, including in the first seconds after opening, and 8 of 50 moves were refused.
- What the product must do: An edit is refused only when the cut's cards, order or timing really changed since the page saw it, and every page converges on the saved cut.
- Kind: 3
- From: D04-058, C06-041, P11-066

### CE1-072: No refused edit may be silent, on any device.
- What was going on: Splits refused on a phone showed nothing, refusals in a read-only view were dropped, and raw server errors reached the page verbatim.
- What the product must do: Every refused edit shows a plain sentence saying why on the device it came from, nothing changes, and technical detail sits behind a disclosure.
- Kind: 3
- From: C04-066, D02-061, M01-034

### CE1-073: The card list ignored the mouse after an action, while keys still worked.
- What was going on: A busy state set during apply, undo and outside updates was never cleared on success, so every click did nothing until a reload.
- What the product must do: Whenever an edit, apply, undo or outside update finishes or is refused, the list answers mouse and touch again at once.
- Kind: 3
- From: D03-019, L04-016, D07-022

### CE1-074: Opening a cut, or making one from a board, took seconds.
- What was going on: Opening cut lists was "extremely slow", and making a new cut from a large planning board took almost ten seconds.
- What the product must do: Opening a cut list or creating one from a board takes about one second at most on a typical episode.
- Kind: 3
- From: P09-037

### CE1-075: Results finished in the background stayed invisible until the next edit.
- What was going on: A finished search was stored without telling the page, which refreshed only when something else changed: "it worked now, oddly".
- What the product must do: A background job's completion appears on the page within seconds with no other activity.
- Kind: 3
- From: G01-063

### CE1-076: Anything not ready on first ask was never asked for again.
- What was going on: Audio, waveforms and card words answered "still preparing" at first, especially after a restart, and views never asked again, staying silent, grey or "no transcript".
- What the product must do: Every view keeps asking until the audio, waveform or words it needs exist, then shows them and starts playback, with no refresh.
- Kind: 3
- From: D03-006, P08-042, P08-018

## Playback and audio

### CE1-077: A browser audio element only plays forwards.
- What was going on: Scrub audio built on a browser's audio element was silent when scrubbing backwards and when still.
- What the product must do: Reverse and slow scrubbing still sound like the words.
- Kind: 1a
- From: C04-069

### CE1-078: A browser's audio clock advances in steps of about 40 ms.
- What was going on: Zoomed in, 40 ms is 2 to 3 pixels, so a playhead drawn straight from the clock jerks.
- What the product must do: The playhead moves continuously at the play rate between clock readings and never steps backwards.
- Kind: 1a
- From: P08-030

### CE1-079: Every clip must play and show its waveform without an export step.
- What was going on: Only interview clips had prepared audio, so news and archive clips played silence; the owner: play "directly through to the lane, so we don't have to output wavs".
- What the product must do: Opening a cut starts preparing every clip's audio and waveform with progress per clip; any clip whose media exists plays, matching source timing within 0.05 s.
- Kind: 3
- From: P08-041, C05-012, P09-026, C04-071, G01-057, P09-027

### CE1-080: Clips with only a subtitle file beside them showed "no transcript" and did not play.
- What was going on: Downloaded clips had a subtitle file beside the video but no full transcription; 104 cards had no words and none played.
- What the product must do: A clip whose only text is a subtitle file beside its media plays, shows those words on its cards, and opens a transcript built from the cues.
- Kind: 3
- From: P13-012, M02-063, C06-053

### CE1-081: Several audio preparations at once starved the disks.
- What was going on: Each clip played started its own audio preparation beside the queued ones, so up to six competed and each took up to 336 s.
- What the product must do: Audio preparation never runs many jobs at once, and playing a clip moves its preparation to the front instead of starting another.
- Kind: 3
- State: outcome not found
- From: P15-015

### CE1-082: A partial project copy played silence and guessed the English.
- What was going on: A laptop's copy held only text files, so audio, word timings and translations were missing and the editor quietly substituted machine translation with no word lighting.
- What the product must do: When a project's audio, word timings or translations are missing, the editor names which, never showing an empty player, silence or substitute English.
- Kind: 3
- State: outcome not found
- From: M04-100, P15-043, P04-067

### CE1-083: Playback popped at splices, ruining the judgement of each cut.
- What was going on: The owner: the pop "ruins my ability to hear if a cut is smooth"; same-recording joins jumped position with no ramp, clicks up to 7.5 times the normal sample step.
- What the product must do: Across any join, at 1x and 2x and several in a row, no click is louder than the audio around it, and any smoothing stays a few milliseconds.
- Kind: 3
- State: fixed, never shipped
- Check: Sources from the same day disagree on whether click-free joins were shipped; were they?
- From: D01-011, P11-051, M01-024

### CE1-084: Cuts play back to back with no pause at the join.
- What was going on: The owner: "a short pause between clips negates the ability to test audio splicing"; the playhead also stepped backwards at each crossing.
- What the product must do: Across any join the next cut sounds the instant the previous ends, and during playback the playhead only moves forward.
- Kind: 2
- From: D01-013, P09-032, C05-019

### CE1-085: Audio fades drawn on the lane must be heard as drawn.
- What was going on: The owner ruled fades audio only and linear in gain, then: "make audio fades in the lane actually play, not just be visual".
- What the product must do: The lane and scrubbing play each fade as drawn at every rate, overlapping ends multiplied, with no click; there are no video fades; the transcript player never fades.
- Kind: 2
- From: M01-021, D02-044, C06-022

### CE1-086: Fade handles on cuts reach Resolve as real audio fades.
- What was going on: The owner asked for Resolve-style fade handles on cuts and ruled them audio only.
- What the product must do: A cut's audio fade handles arrive in Resolve as real audio fades, and no video fade is ever written.
- Kind: 2
- From: M01-021
- Move to: cards-to-resolve-and-exports

### CE1-087: Faster playback keeps the voice's pitch, and switching speed leaves no hole.
- What was going on: The owner: "at 2x the audio needs to not go high pitched"; switching speed mid-play gave about 380 ms of silence and skipped short clips.
- What the product must do: At any speed other than 1x voices keep their pitch, and a speed change keeps sound at the old speed until the new one is ready, then crossfades.
- Kind: 2
- From: P15-036, C06-083, P17-037

### CE1-088: Scrubbing is heard, at scrub speed and in both directions.
- What was going on: The owner: "hear audio as I'm scrubbing, at the speed I'm scrubbing, pitch normalised", "reverse scrub audio playback too", and audio while trimming.
- What the product must do: Dragging the playhead, jogging with a controller stick, or dragging a cut's edge plays the audio under it at that speed with natural pitch, forwards and backwards.
- Kind: 2
- From: L05-058, P08-035, P16-017

### CE1-089: The playhead, scrubbing and panning stay perfectly smooth at every zoom.
- What was going on: The owner wants it "perfectly smooth, like resolve"; lag returned five times, from full redraws per frame, bursts after load and requests repeated hundreds of times a second.
- What the product must do: Each lane frame draws in a few milliseconds at any zoom, 4K included and just after load, and no background request repeats faster than every few seconds.
- Kind: 2
- From: P09-035, P08-029, C04-067

### CE1-090: Zoomed in, the playing playhead jumped and the strip did not follow.
- What was going on: The playhead was redrawn only on each 250-600 ms update, jumping up to 240 px, and the strip never scrolled, so the head left a 4.8 s view.
- What the product must do: A playing playhead moves smoothly at every zoom, and the strip pages forward when the head reaches its edge unless the person is panning.
- Kind: 3
- State: still open
- From: D02-057

### CE1-091: No edit moves the playhead forward, and play starts where the playhead is.
- What was going on: Edge drags and ripple extends carried the head to the next cut, and the play button jumped to the new join; the owner reversed an earlier rule.
- What the product must do: After any edit the head stays on the same source frame of its cut, or that cut's nearest remaining frame if trimmed away, and play starts from it.
- Kind: 2
- From: P16-021, C06-067, D02-049

### CE1-092: The clip under the playhead is marked, separately from the selection.
- What was going on: The highlighted clip followed the selection, and the active card updated only on pause; the owner wants the mark to follow the playhead while scrubbing.
- What the product must do: The clip and card under the playhead carry their own mark, distinct from the selection colour, following within a quarter second during playback and scrubbing.
- Kind: 2
- From: P04-048, P16-002

### CE1-093: Follow keeps the card being heard centred above the lane.
- What was going on: Follow lost long cards, judged a card visible while it was hidden under the lane, and switched off on any scroll of the editor's own.
- What the product must do: With follow on the heard card stays centred in the unobscured card area; scrolling never turns it off; tap F jumps once, hold F toggles with a brief notice.
- Kind: 2
- From: P08-037, C04-073

### CE1-094: The playhead stopped, jumped back, and selections reverted, cause never found.
- What was going on: During normal, 2x and shuttle playback the head jumped back and clicks selected the previous clip; suspects were a second window, the controller, a stale offline copy.
- What the product must do: The playhead and selection move only by the editor's own action; a second window or a controller of the same episode never fights it.
- Kind: 3
- State: outcome not found
- From: M01-055, P11-048

## Lane clicks and keys

### CE1-095: Chrome and Edge keep F12 for developer tools, and no page can take it.
- What was going on: The owner's "head to mouse" shortcut on F12 opened developer tools instead, and his mouse side button sends F12.
- What the product must do: No page shortcut uses F12 or another browser-reserved key, and a mouse button sending F12 is remapped before the browser, leaving Resolve's own F12 alone.
- Kind: 1a
- From: L04-019, D07-020, P08-025, P09-065, D03-015

### CE1-096: In Chrome on Windows a lone Alt press hands the keyboard to Chrome's menu.
- What was going on: After Alt was pressed and released alone, as after Alt plus wheel, click or drag, the next Space opened Chrome's three-dot menu instead of playing.
- What the product must do: Space always plays or stops, straight after any Alt gesture, and never activates a browser menu or a focused button.
- Kind: 1a
- From: C04-068, P08-036, C06-087, P16-003, P15-044

### CE1-097: Many laptop keyboards have no Insert key.
- What was going on: Adding a gap at the head was bound only to Insert, which the owner's laptop lacks, and the controller had none; he chose a long press of X.
- What the product must do: Every key action has a binding every laptop keyboard can reach and one on the controller; holding X adds a gap at the playhead.
- Kind: 1a
- From: C06-037, P16-022

### CE1-098: A single click on a lane clip only selects it.
- What was going on: The owner: clicking a clip "should not move the timeline view" nor the transcript, "it should only be double click".
- What the product must do: A single click or key selection leaves the transcript and view where they are unless the clip is wholly off screen; a double click opens that cut's paragraph in its transcript.
- Kind: 2
- From: P17-038, C06-091, L05-043, P10-013

### CE1-099: Lane keys stopped working, or did other things, with no Resolve connected.
- What was going on: The trim keys came only from the editor's Resolve key layout, which was forgotten at each server restart, so with no Resolve the keys fell through.
- What the product must do: Lane keys follow the editor's Resolve preset by command when known and documented defaults otherwise, work the same without Resolve, and a learned layout survives restarts.
- Kind: 3
- From: C05-052, P10-014, L05-032, D05-058

### CE1-100: F splits the clip under the playhead.
- What was going on: The owner: "f blade split isn't working" on the lane.
- What the product must do: Pressing F with the timeline focused splits the clip under the playhead at the playhead.
- Kind: 2
- From: P14-019, P16-012

### CE1-101: Stepping between clips moves the playhead and leaves the selection alone.
- What was going on: The owner: "if you have a clip selected and then d pad up to the previous clip, it will deselect... I don't want that to happen at all"; the keyboard likewise.
- What the product must do: Next and previous edit, from the keyboard or the controller's D-pad, move the head only and leave a single or range selection exactly as it was.
- Kind: 2
- From: P14-006, C06-029, D02-046

## Game controller

### CE1-102: Controller edits must be safe from the sofa.
- What was going on: With no mouse the playhead is the only pointer, and a stale selection or stray press could delete or send the wrong thing.
- What the product must do: A refusal buzz always matches the on-screen message, typing in a box ignores the pad, and sending a cut to Resolve is never on the pad.
- Kind: 3
- From: D02-052

### CE1-103: Each cut edge has its own controller control, wherever the playhead is.
- What was going on: Picking trim or extend by where the playhead sat made extending unreachable; the owner chose "one control per edge, one meaning per modifier, no rule about where the head is".
- What the product must do: A bumper tap trims that edge to the head, and a held bumper with the right stick drags that edge either way, regardless of the playhead.
- Kind: 2
- From: D02-047, C06-027

### CE1-104: On the controller, Y picks a clip and LT plus Y selects back to it.
- What was going on: The owner: "press y to select one clip, move along the timeline any number of clips, press lt + y once again and it selects everything"; it deselected instead.
- What the product must do: Y anchors a clip; LT plus Y selects every cut from the anchor to the head in either direction; the pad's own steps keep it; B clears it.
- Kind: 2
- From: P11-032, C06-028, M03-057, D02-048

### CE1-105: Moving a clip twice on the controller moved its neighbour instead.
- What was going on: After a move the playhead stayed put, so a different clip slid under it and the next move grabbed that one.
- What the product must do: After a controller move the head stays on the moved cut, so repeating the move keeps moving the same cut.
- Kind: 3
- From: P11-034, C06-031, M03-058

### CE1-106: The controller's landing marker shows only while the left stick is held in.
- What was going on: The owner: "make it so the chevron marker only appears when you press down L3 also, it's distracting".
- What the product must do: The centre landing marker appears only while the left stick is pressed, can be aimed by panning, and the head lands there on release.
- Kind: 2
- From: C06-030, P16-018

### CE1-107: Selected clips can be carried a long way with the controller.
- What was going on: The owner wanted LT held and the right stick pushed to run a between-clips marker away from the selection, faster the harder he pushes.
- What the product must do: With clips selected, LT plus the right stick moves a landing marker gap by gap, faster with more push; releasing LT drops them there as one undo.
- Kind: 2
- From: P16-031

### CE1-108: The right stick is precise at small pushes and stops dead on release.
- What was going on: The owner: "the right stick should be a little more precise at low movement levels"; jog speed rose in a straight line from the dead zone.
- What the product must do: A quarter push jogs about 0.09x, rising smoothly to 1x and 8x at full push; releasing any jog, pan or scrub control stops on that frame with no coasting.
- Kind: 2
- From: C06-036, P17-040, D02-050

### CE1-109: A double Y opens the cut in its transcript.
- What was going on: Only a double-click opened a lane clip in the transcript, which a controller lacks; the owner: "it should be double y to open that clip in its transcript".
- What the product must do: A second Y on the same cut within about half a second opens its paragraph in the transcript, opening its interview first; a single Y still selects.
- Kind: 2
- From: D06-046, P12-045, P18-012

### CE1-110: The controller drives the transcript like the timeline.
- What was going on: The owner: "move the playhead with right stick, then hold lt and move right stick to make selection", then a button inserts after the selected card.
- What the product must do: The pad acts on the focused pane; in the transcript the right stick steps word by word, LT plus stick selects, and LT plus X inserts after the selected card.
- Kind: 2
- State: fixed, never shipped
- From: P18-014, M01-056

## Phone

### CE1-111: On a phone the lane is absolutely full screen.
- What was going on: The owner: "on mobile the lane should still be absolutely full screen, no cards behind it"; over-scroll showed the list under it.
- What the product must do: On a phone the lane covers the view above the bottom bar, and no scroll or over-scroll reveals the cards.
- Kind: 2
- From: D06-029

### CE1-112: On a phone a long press lifts a card to reorder it.
- What was going on: The owner: "no way to reorder cards on mobile, long press opens the transcript page"; the transcript should still open at any time.
- What the product must do: On touch a long press lifts a card for dragging with edge auto-scroll, and the transcript opens from a button on the card or the bottom bar.
- Kind: 2
- From: D03-038, C05-048

### CE1-113: The phone edit view shows the whole current cut and the word being heard.
- What was going on: The owner: "you should be able to see all the text, and it should highlight which word you are currently over".
- What the product must do: The row under the playhead shows its full text, scrollable within the row, lights the current word, and says "no word timing" when there is none.
- Kind: 2
- From: D03-039

### CE1-114: In the phone edit view only a dial strip on the right moves the playhead.
- What was going on: With the playhead on a one-finger drag, every brush while reading moved it; the owner then moved the dial from the left edge to the right.
- What the product must do: Only the right-edge dial, finer further from the edge, moves the head; a tap plays or pauses; controls sit beside it, never over text; cards show only their English.
- Kind: 2
- From: M04-060, C04-081, D06-041, L05-059, M01-033

### CE1-115: A double tap picks up a cut to move it on the phone.
- What was going on: The owner: "you should be able to move cards in the edit tab by double tapping them"; a single tap's play now waits 300 ms for a second tap.
- What the product must do: A double tap picks up a cut; a tap on another cut's top or bottom half drops it before or after; tapping it again or leaving the tab lets go.
- Kind: 2
- From: L05-055

### CE1-116: On a phone an edge trim takes a tap to arm, then a drag.
- What was going on: The owner: a drag starting at a clip edge must not trim; tap the edit point first, then drag; a plain drag pans and coasts longer, about 4.8 s.
- What the product must do: On touch a drag trims only after a tap armed an edit point, also under a marker flag, where a hold instead picks up the marker.
- Kind: 2
- From: D05-057

### CE1-117: Holding the play button plays at double speed.
- What was going on: The owner: "in lane mode if you hold down play pause button it should 2x playback", the same as holding Space.
- What the product must do: A tap on play toggles once; holding it plays at 2x, and release returns to the previous speed, stopping if it was stopped before.
- Kind: 2
- From: L05-057

### CE1-118: On a phone, card text ran 1,638 pixels wide off a 412-pixel screen.
- What was going on: Card text, details and options ran unwrapped off the right edge, and short cuts with long clip names spilled 300-400 px past it.
- What the product must do: On a 390 to 412 pixel screen, at every zoom, no card, details line or panel is wider than the screen; text wraps and long names end in an ellipsis.
- Kind: 3
- From: D06-031, C05-013, D03-014

## Panels and layout

### CE1-119: On desktop the transcript opens beside the cards, never over them.
- What was going on: The owner preferred the page "split when you open" the transcript, not a panel floating over the cards; on a phone the panel is a full-screen pane.
- What the product must do: On desktop an opened side panel sits beside the cards, which reflow, and never covers them; on a phone it takes the screen and has its own close.
- Kind: 2
- From: D06-036, D03-004, P08-051, M04-048, D05-070

### CE1-120: Opening one panel never changes another panel's width.
- What was going on: The owner: "which panels are open should not affect other panels width"; a hidden overview widened everything and the shortening panel squeezed the cards.
- What the product must do: Each panel keeps its own width to the pixel when others open or close, a hidden panel changes nothing, and only the card column grows or shrinks.
- Kind: 2
- From: D07-001, P11-014, D06-037, C05-004

### CE1-121: No mix of open panels may crush the cards or scroll sideways.
- What was going on: Fixed-width panels let three open panels squeeze a laptop's cards to nothing, and a phone page once scrolled sideways.
- What the product must do: At 1440x900 and 412x915, every combination of open panels keeps the card column above its minimum and the page never scrolls horizontally.
- Kind: 3
- From: D07-002

### CE1-122: Panels tab, dock and resize like After Effects.
- What was going on: The owner: the transcript is "the second most important after the lane, but ... an afterthought"; panels should "drag them out and dock them like AE does".
- What the product must do: Cards, transcript, staged and video panels can be tabbed, docked side by side and resized, the layout is kept per device, and bottom bars take minimal height.
- Kind: 2
- From: C06-076, P15-026

### CE1-123: The timeline sits at the top by default.
- What was going on: A rebuilt editor put the timeline at the bottom; the owner asked for it at the top like the original.
- What the product must do: The timeline is docked at the top by default, and a person's own choice of position is kept.
- Kind: 2
- From: P16-007

### CE1-124: Each panel can pop out to another screen, one copy each, synced instantly.
- What was going on: The owner: "there should only ever be allowed to be one instance of each thing", and updates between windows "should be instant".
- What the product must do: Popping a panel out moves it to its own window, one per panel; selection, playhead and edits reach every window within a frame; one control brings everything back.
- Kind: 2
- From: C05-066, D03-048, P10-050, L05-068

## Opening episodes, restarts and Resolve

### CE1-125: The project is the episode; cut lists and timelines are members inside it.
- What was going on: The owner: a cut's name "is not a project name"; "'Project' should be the name of the episode root".
- What the product must do: The header reads "episode · open cut" with recent episodes; switching opens the last cut or a picker of that episode's cuts and its own Resolve timelines only.
- Kind: 2
- From: P09-039, C05-026, M04-124

### CE1-126: After switching episode, lists still showed the previous one.
- What was going on: The switch answered before taking effect and old lists stayed cached, so the page kept the old cuts and interviewees, and a just-created cut list never showed.
- What the product must do: After a switch nothing from the previous episode shows anywhere, a new cut list opens without reload, and the last episode and cut are remembered across restarts.
- Kind: 3
- From: P09-038, L05-070, C05-027, D03-044, P10-048, C03-057

### CE1-127: Switching cut lists within an episode cost a restart and a 12-second reload.
- What was going on: Opening another cut list of the same episode threw away loaded transcripts, audio and translations and paid a 12 s cold load.
- What the product must do: Switching cut lists within an episode keeps everything loaded, and an episode reopens on the cut list last left on.
- Kind: 3
- From: D05-034

### CE1-128: Two people can work in two different projects at once.
- What was going on: The owner ruled that people drive only the computers signed in to their own account; one account may also use a laptop and a phone.
- What the product must do: Each person picks a project from a landing page, and their edits reach only Resolve on their own signed-in computers, with no studio-wide lock or hand-over.
- Kind: 2
- From: C03-066

### CE1-129: With Resolve closed, the page went blank and edits hung for minutes.
- What was going on: The page needed a live Resolve to show anything; closing Resolve blanked it, and edits waited eight minutes before failing.
- What the product must do: Whatever came from Resolve stays on screen marked stale since when; edits needing Resolve are refused at once with the reason; a missing Resolve is a soft note.
- Kind: 3
- From: M03-046, C04-060, D06-023, P08-010

### CE1-130: An open editor page stuck after the server restarted.
- What was going on: A page left open across a server restart stopped working until it was reloaded.
- What the product must do: An open editor page reconnects by itself after a server restart, without a manual reload and without losing work.
- Kind: 3
- State: outcome not found
- From: P16-038

### CE1-131: After every server restart the assistant showed as unavailable.
- What was going on: The assistant's sign-in state lived only in memory, and the reason showed only in a hover tooltip, which a phone cannot show.
- What the product must do: A signed-in assistant shows available straight after a restart, and any reason a feature is unavailable is printed on screen, never only in a tooltip.
- Kind: 3
- From: C03-050, M01-025

### CE1-132: A feature that could not run hid its reason where the next edit overwrote it.
- What was going on: With the assistant unavailable, search and summaries failed and the error showed in one shared message line that the next edit replaced.
- What the product must do: A feature that cannot run shows its reason on its own control, and the message stays until it can run.
- Kind: 3
- From: G01-061, P08-044

## Offline and several devices

### CE1-133: An installed web app with no declared id is identified by its start address.
- What was going on: Without an id in its manifest, one page at two addresses is two apps, and moving the address loses stored offline data.
- What the product must do: The installed editor keeps its identity and offline copies under any address prefix, and the same bookmark or app opens the downloaded copy with no network.
- Kind: 1a
- From: D04-048, P10-012

### CE1-134: An installed offline worker keeps serving its old page over moved addresses.
- What was going on: An installed worker controls every address under its scope, so after the page moved it served the old page; a scope of "/" claimed the whole site.
- What the product must do: When pages move, the old worker is switched off for everyone without losing unsent edits, and no worker claims more than its own section.
- Kind: 1a
- From: C03-038

### CE1-135: An installable editor under a sub-path claimed every page of the site.
- What was going on: Served under a sub-path of the dashboard, the editor declared the site root as its installed-app scope, handing every dashboard page to it.
- What the product must do: An editor installed from a sub-path claims only that sub-path, and every link it makes works under any prefix.
- Kind: 3
- From: C05-005, D03-009

### CE1-136: A downloaded cut list can be cut and listened to with no network.
- What was going on: The owner: "I'm about to get on a flight and I want to be able to edit offline with audio"; on Windows, a project folder separate from the browser cache.
- What the product must do: A kept cut list is sized before download, resumes cut-short files, and opens, edits and plays offline with words and English; each offline edit lands exactly once.
- Kind: 2
- From: P10-009, D04-024, D05-090, M04-116

### CE1-137: Any cut list of any episode can be kept offline.
- What was going on: A cut list could be downloaded only while open on the server, unopened lists were not listed offline, and their queues waited until reopened.
- What the product must do: Any cut list of any episode can be downloaded and listed offline, and its queued edits replay without it being opened first.
- Kind: 2
- State: still open
- From: D04-025

### CE1-138: Working offline can be chosen while online.
- What was going on: The owner: "I also want to be able to enable offline mode even if I'm online, in all the apps, and in the browser."
- What the product must do: A work-offline switch in every app and browser makes no server requests, reads "offline (your choice)", survives restart, and replays the queue when switched back.
- Kind: 2
- From: D04-050

### CE1-139: One slow reply flipped the page onto an offline copy hundreds of revisions old.
- What was going on: The owner: "the lane and the order keep jumping around"; one slow poll switched to a copy at revision 231 while the live cut was at 507.
- What the product must do: Only a measured, repeated outage switches to offline; the copy follows every live state; an older revision never replaces a newer one; the screen says live or offline.
- Kind: 3
- From: L05-035, D04-032, M01-039, P10-022

### CE1-140: A second queued offline edit on one cut was "no longer in the cut list".
- What was going on: A trim or split renames the cut it touches, so a queued edit naming the old name could not find it on replay.
- What the product must do: Any number of queued edits on one cut replay correctly, finding the cut by its clip and span when its name changed.
- Kind: 3
- From: D04-043

### CE1-141: Offline edits must land on exactly the frames an online edit would.
- What was going on: In floating point 6.1 x 25 is 152.4999, so naive rounding gave one frame off; offline ripple also moved the first cut over black before it.
- What the product must do: An edit made offline gives the same frames, gaps and leading black as the same edit online, to the frame.
- Kind: 3
- From: D04-039

### CE1-142: Where the offline copy cannot know an edit's result, the card says so.
- What was going on: Some offline edits, such as an insert from a transcript, can only be settled later, and showing the old words would mislead.
- What the product must do: An offline card whose final words or span are unknown is visibly marked pending, never shown with guessed numbers.
- Kind: 3
- From: D04-040

### CE1-143: The app hung skipping clips abroad because only one clip's audio was kept.
- What was going on: The owner: "hanging when I skip to the next clip"; a remote link dropped every 20-60 s and only the playing clip's audio was kept locally.
- What the product must do: The apps keep every clip's audio of the open cut list automatically, and offline, skipping between clips starts playback in under a second.
- Kind: 3
- From: D04-051

### CE1-144: Updating one episode's offline copy deleted every other episode's.
- What was going on: Each update replaced every stored episode page, and downloaded media was never removed.
- What the product must do: Each episode's offline copy survives updates to the others, and downloaded media is removed when no longer needed or space runs low.
- Kind: 3
- State: still open
- From: H08-071

## Connections

### CE1-145: Windows turns a refusal into a reset if the request body was not read.
- What was going on: A server refusing an upload before reading its body makes Windows reset the connection, so slow clients, a phone for one, never see the refusal.
- What the product must do: Every refusal reaches the client as the server's own message, with the body read, within a size limit, before answering.
- Kind: 1a
- From: M01-046, C05-049

### CE1-146: Browsers drop connections constantly.
- What was going on: Closed tabs, locked phones and abandoned reloads arrive on Windows as connection-reset or aborted errors, each logged as a forty-line traceback hiding real ones.
- What the product must do: A client dropping its connection is one log line naming the client; every other error keeps its full detail.
- Kind: 1a
- From: D03-057

## Sealed

### CE1-S01: The command-line assistant answers with its default model unless told.
- What was going on: Without an explicit model on each call, the command-line assistant uses its default, and the answers look plausible.
- What the product must do: Every call names the model the feature asked for.
- Kind: 1b
- Tool: Claude Code CLI (--model)
- From: C03-049

### CE1-S02: A conversation id is spent even when its first turn fails.
- What was going on: After any attempt with an id, even a failed one, later turns get "Session ID ... is already in use"; an unknown id answers "No conversation found".
- What the product must do: "Already in use" or "not found" means the conversation is lost; a fresh id opens a new one with a visible note, and "new conversation" always starts one.
- Kind: 1b
- Tool: Claude Code CLI sessions (--session-id / --resume)
- From: L05-069, P10-047, C05-008, D01-033

### CE1-S03: One assistant conversation cannot take two turns at once.
- What was going on: Sending several sections in parallel on one conversation failed with "Session ID ... is already in use".
- What the product must do: Turns on one conversation run one after another, even when the page sends several at once.
- Kind: 1b
- Tool: Claude Code CLI
- From: D03-055

## Removed
