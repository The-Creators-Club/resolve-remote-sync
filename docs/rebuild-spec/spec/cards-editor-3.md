# Timeline Cards: the editor, part 3 of 5

This part covers reading and searching the episode's transcripts from inside the editor, how Chinese and other scripts are matched, and the English every cut, card and transcript line shows.

## Search and the transcript panel

### The help sheet lists the keys of the transcript panel and of the search results

{{28-022}}

- Exact: yes

### An editor opens and closes the transcript panel

{{30-001}}

{{30-002}}

- Who: anyone who can open the editor.
- Ways in: the header's Transcript button, the 2 key, Shift+T on a selected cut, the pad's transcript view, a request to browse transcripts from any other part of the editor, a double-click on a card or a clip in the lane, Open transcript on a search result, Open in the transcript on an English selection, Ctrl+F.
- Name and search words: the transcript panel: transcript, read interview, paragraphs, insert passage, side panel.
- Exact: yes

### An empty transcript panel shows how to open a transcript

The panel is empty when the transcript tab is the one showing in its panel group and no transcript is open: none has been opened yet, or the open one was closed with 2 or its close button. It shows:

- "No transcript open."
- a primary "Browse transcripts" button marked with the key 2, which opens the panel on its list of transcripts;
- "Every interview and montage clip in this episode, with filters and bins. Or double-click a clip in the lane, or press Q on a card, to open its transcript."

The 2 key opens or closes the transcript panel on whichever page it last showed, so it does not always open on the list.

- Exact: yes

### Double-clicking a card or a clip in the lane opens that cut in its transcript

{{30-003}}

- Exact: yes

### While the panel is open it follows the card the editor selects

{{30-004}}

- Exact: yes

### The panel sits beside the lane on a desk, fills the screen on a phone, and goes full height with Shift+F

- Desktop (window wider than 700 px): the panel runs from the header's bottom edge (56 px from the top if there is no header) down to the lane dock's top edge when the dock is in the lower half of the window, or from the dock's bottom edge down when the dock is at the top. It never covers the lane and follows the dock live as it is resized or moved top/bottom and as the window resizes. If that leaves less than 240 px, the panel keeps 240 px and overlaps the dock instead. Default width up to 560 px, docked to the right edge.
- Phone (700 px or narrower): the panel is the whole screen width from the top.
- Shift+F with the pointer over the panel or the keyboard focus inside it (never while typing in a box, never with Ctrl/Alt/Meta, not auto-repeat): the panel goes to the full height of the window at the left edge and width it had, and the lane narrows to the width left beside it instead of being covered. Shift+F again, Esc, or closing the panel puts it back. It cannot be turned on while the panel is hidden.

- Phone and desk: beside the lane on a desk, the whole screen width on a phone.
- Exact: yes

### Closing the panel or changing cut list resets what the panel was doing

{{30-006}}

- Exact: yes

### The list of transcripts holds every interview and every montage source of the episode

The list shows one entry per interviewee (kind "Interview") and one per montage source (kind "Montage") of the episode that has a transcript or a clip with word timings or subtitles. "Interview" means a transcript that belongs to a named person: only those appear among the people. Each entry knows its clips, its total length (when known), and whether its timings are per-word speech-to-text timings, from subtitles only, or none. Entries are sorted by person, then by clip. A new or changed transcript shows in the list within a few seconds.

An interviewee stays listed whatever fails with their transcript. When their transcript cannot be read or tied to their clips, the row stays and names the actual problem (for example "transcript not linked") instead of the person disappearing from the list.

### The list of transcripts can be filtered by name, kind, use in the cut, person, length and timings, and each row says what it holds

- Header: "Transcripts" and the first part of the cut list path; a "Back to the transcript" button when a transcript was open.
- Filter box "Filter by name": matches the person name and the clip names, case-insensitive; keeps its text across redraws.
- Kind facet (three buttons): All / Interviews / Montage.
- Use facet (three buttons): Any use / In this cut (at least one cut of its clips in the cut list) / Not used (no cut of its clips in the cut list or on the shelf).
- Person filter (drop-down "Anyone" plus each interviewee name, sorted): shown only when the episode has more than one interviewee. Montage sources have no person entry. A remembered person that disappears resets to Anyone.
- Length filter (drop-down): Any length / Up to 30 s / 30 s to 2 min / 2 to 10 min / Over 10 min. A source of unknown length shows only under Any length.
- Word timings filter (drop-down): Any timings / [speech-to-text] words / Subtitles only / No timings.
- The bins rail (described below) under the filters, scrolling with the list; the intake (described below) above the list when it has rows.
- Each row is a button: a colour stripe in the speaker colour the cut list uses for that clip (the colour of the first cut of any of its clips); the person name; a meta line "Interview" or "Montage" · "1 clip" or "N clips" · length as m:ss (when known) · "[speech-to-text] words" / "subtitles only" / "no timings", or "no transcript yet"; chips: the bin name (only when the bin filter is All), "N in the cut", "N staged"; marked current when it is the transcript open in the panel. A row with no transcript is disabled and cannot be opened. Click (or Enter/Space on it) opens that transcript. An episode with hundreds of rows still scrolls smoothly.
- States: "Loading the episode's transcripts" with a spinner; on failure the warning line says "the transcripts did not load: <reason>" and the body shows a "Try again" button; with no cut list open: "open a cut list first"; "No transcript matches those filters." when filters hide everything; "This episode has no transcripts yet (<where transcripts are kept>)." when there are none.
- Drop hint at the bottom (hidden on a phone): it says that media files dropped here are made ready to cut.
- The list opens even when the bins or the intake fail to load.

- Phone and desk: the drop hint shows on a desk only.
- Exact: yes

### An editor groups transcripts into named bins and files each transcript into at most one

- A clip is in at most one bin; filing it moves it. A transcript with clips is filed by all its clips; one with no clips by its own name.
- The rail (shown when the bins loaded): an "All bins" chip with the total count, tooltip "Every transcript. Drop one here to take it out of its bin". One chip per bin with its count, tooltip "Show the transcripts in <bin>. Drop one here to file it"; clicking a chip filters the list to that bin. A delete (x) beside each bin chip, tooltip "Delete the bin <name> (its transcripts stay, unbinned)"; result "Deleted the bin <name>; its transcripts are unbinned". When the bin filter names a bin that no longer exists, it resets to All.
- "New bin" button: opens a name box ("Bin name", at most 60 characters) with "Make" (key hint Enter) and "Cancel". Enter in the box makes the bin; Esc in the box closes it and returns focus to the paragraphs. Refusals: "type a name for the new bin" (empty), "there is already a bin called <name>". Success: "Made the bin <name>. File transcripts with the bin control on each row, or drag them onto it".
- Bin drop-down on each row (when at least one bin exists): "No bin" plus each bin. Choosing files it there ("Filed <person> in <bin>") or takes it out ("Took <person> out of its bin"). Works by keyboard and touch.
- Drag a row onto a bin chip: files it there; dropping on "All bins" takes it out of its bin. The chip under the drag is highlighted.
- Limits: a bin name has its spaces collapsed, may not be empty ("a bin needs a name"), may not hold control characters ("a bin name cannot hold control characters"), and is at most 60 characters; at most 100 bins per episode ("an episode has at most 100 bins: delete one first"), also when filing would create a bin; at most 20,000 filed clips ("too many transcripts are filed in bins"). Making a bin that exists changes nothing.
- Any failure: "the bins did not change: <reason>".
- A change made by another program at the same time is never lost, and a crash never leaves the bins half written.

- Who: anyone who can open the editor.
- Exact: yes

### Dropping media files on the panel hands the clips to footage in and lists each one in the intake

- Media files dragged from the desktop onto the panel highlight it (dashed cyan outline, the drop hint lights up). On drop, the panel switches to the list of transcripts and looks for the files in the episode by name and size.
- While looking: "Looking for <name> under the episode" or "Looking for N files under the episode". With no cut list open: "open a cut list first, then drop the media on its transcripts". Nothing dropped: "nothing was dropped".
- At most 100 files per drop. A name is ignored if empty, over 255 characters, holding a slash or backslash, "." or "..", or control characters. Only media kinds are taken: mp4, mov, mxf, mkv, m4v, avi, mts, m2ts, wav, mp3, m4a, aac, flac, ogg, opus, webm, braw, r3d. Anything else is reported as skipped. Duplicate names (case-insensitive) are taken once; names already in the intake are not looked for again.
- Each name is looked for among the episode's media by name (case-insensitive) and, when a size was given, exact size; the first match in name order wins.
- The intake holds at most 200 rows per episode (the oldest drop off) and is forgotten when the server restarts.
- Result: "Added to the intake." plus, when some were not found, "One is / N are not in [the episode's media] yet: put it/them under the episode folder and drop again."; plus, when some were not media, "<name> is not media, so it was skipped" or "N files that are not media were skipped". Shown as a warning when either applies. Failure: "the intake did not take them: <reason>".

Every clip that is found is handed to footage in, which makes it ready to cut on its own, exactly as for clips dropped in anywhere else: the editor starts no step by hand and chooses no computer. How that happens, and every decision in it with its override by hand, is described in Timeline Cards: footage in, ready to cut.

The intake box shows in the list of transcripts while it has rows, titled "Intake", with a Clear button that empties the list (work already under way carries on). Each row gives the file name and says plainly:

- whether the file was found in the episode, and where; a row not found shows a "Not in [the episode's media]" chip and "Put it under the episode folder, then drop it again";
- for a found file, what its clip still lacks (a transcript, a proxy), and that each lack goes away by itself as footage in finishes it.

- Who: anyone who can open the editor.
- Phone and desk: dropping files is a desk gesture.
- Exact: yes

### Opening a transcript shows its header, and a person with several recordings can choose which recording's timings are used

- A transcript opens from a row, Shift+T, a double-click, or a search result. Opening one clears the find, picks, selection, the transcript playhead and the sentence cursor, and pauses its audio.
- Failure: the warning line "that transcript did not open: <reason>" (an error, no dismiss button), with a Try again available. Showing a cut whose clip has no transcript in this episode: "<person or clip> has no transcript in this episode". Showing a cut no longer in the cut list: "that cut is no longer in the cut list". A clip with no transcript at all: "no transcript document for that clip".
- Header: the person name in the speaker colour (tooltip: the file name), an "All transcripts" back button (to the list), the find box (see Chinese text and matching), the match count, previous/next match buttons, and, when the person has several recordings, a drop-down "Which recording the timings come from". Changing it reloads the transcript with that clip's timings.
- By default the timings come from the asked-for clip, else the first clip with per-word timings, else the first with subtitles.
- The header, with its find box and its recording drop-down, stays at the top of the panel and usable at every scroll position, on a desk and on a phone; the drop-down's list is drawn above every other bar.

- Exact: yes

### Any transcript of the episode can be opened from the episode picker on its own

The picker's third part lists every interview and clip transcript of the episode with person, clip, colour and whether it is already loaded. One opened on its own takes its timing from its own word timings, else its subtitles; with neither it can be read but has no word timing. Messages: "no such transcript in this episode"; "that transcript would not open: <error>".

The picker itself is described in Timeline Cards: the editor, Opening episodes and keeping the editor running.

- Exact: yes

### Each paragraph shows its id, its time in the clip, chips for its use, a Pick button, and the English above the original

{{30-013}}

Paragraphs are tightly spaced, so that as many as possible are visible at once, and their body text is white.

- Exact: yes

### A cut belongs to the transcript paragraph it overlaps most

A cut belongs to the paragraph it carries a reference to when the transcript has that paragraph, else to the paragraph its span overlaps most, as long as the overlap is at least 0.35 s or 30 % of the paragraph. This decides the "In the cut", "Staged" and "This cut" chips and which paragraph a cut is shown at.

{{40-014}}

- Exact: yes

### A warning line under the transcript header and a status line at the bottom say what cannot be done

{{30-015}}

- Exact: yes

### Typing in the transcript find marks hits without moving anything and Enter steps to a hit so Space plays it

{{30-017}}

- On a phone the on-screen keyboard offers a Search or Enter key in the find box (never Tab), and that key steps to the next hit exactly as Enter does, beside the on-screen previous and next buttons and the "3 / 17" count.
- The hits stay marked while the transcript plays.
- Each hit plays from its own first word at once, also when several hits sit in one card or the hits run across clips; an answer that arrives for an older hit is ignored.
- Finding stays instant at 500 transcripts: an answer within a second, a newer keystroke cancelling the older search, and the panel redrawn within 60 ms.

- Phone and desk: on a desk Enter lets go of the keyboard so Space plays the hit; on a touch screen the box keeps its keyboard and offers a Search key.
- Exact: yes

### Clicking a word puts the transcript playhead on it and clicking beside the words picks the paragraph

{{30-019}}

- Space plays continuously from the transcript playhead, a held Space plays at twice speed, and Esc clears the playhead. How the transcript plays is described with the rest of playback in Timeline Cards: the editor, Playback and audio.
- The transcript plays the interview's reference audio, a light copy of it, or the clip's own sound; while the clip's own sound is still being prepared the panel says so and asks again. Playing from the transcript starts as fast as the lane does over a slow link, never loads the same clip twice or fetches a full-size file to play it, and names any failure on screen.

- Exact: yes

### Where a paragraph's words could only be placed roughly the editor warns that an insert may be a little wide

For the playing-word highlight, click to play and playing a selection, each paragraph is placed in time as exactly as possible: found word for word in the clip's timed words (differences between Chinese scripts ignored); failing that, searched for within the paragraph's known time span or the subtitle lines it was made from, with 2 seconds of slack either side; failing that, placed by the subtitle lines themselves or as one row for the whole paragraph. A paragraph placed in either of the last two ways is marked approximate ("(approx)" on its time), and the page warns that an insert from it may be a little wider than the selection.

### A highlighted stretch of transcript becomes a card of exactly those words

When an editor highlights text in a transcript and inserts it:

- The selection is first looked for inside the stretch of the clip covered by the highlighted paragraphs (with 8 characters of slack), then in the whole clip, accepting a close match (about 75% alike).
- If that fails and the selection is the English of a Mandarin interview, every paragraph whose English contains the selection (or is contained in it, both at least 8 characters) contributes its whole Mandarin span.
- If the text match failed, or landed more than 2 seconds outside the highlighted paragraphs, the highlighted paragraphs' own span is used instead.
- In those last two cases the card is flagged "whole paragraph" with its length in seconds and the page warns.
- 12 frames of handle are added either side, never reaching into the neighbouring words and never before the clip's start; a card is at least one frame.
- Refused with "couldn't find that text in the clip's transcript -- try selecting the Mandarin line, or a longer stretch", or "no transcript for that clip".
- A span the page timed itself from a played preview gets the same handles; refused with "empty span" or "no transcript for that clip".

Dragging highlighted transcript text onto the lane or the cards does the same as inserting it: the card that lands covers exactly the highlighted words of that clip, by the same rules, in the place it is dropped.

- Exact: yes

### Highlights on a card's words land on the right copy of a repeated phrase and survive reworded text

Each highlight lands on the first free occurrence of its words at or after the previous highlight, otherwise on the first free one anywhere; a highlight whose words are no longer there is dropped. Where that would pick the wrong copy of a repeated phrase, the highlight remembers which occurrence it is, and the cut list only ever shows the marks in the right place.

When the words change, a highlight that still matches exactly is kept. Otherwise the longest shared run of letters and digits (ignoring case) is found and cut back to the whole words it fully covers, where each Chinese, Japanese or Korean character counts as a word. Fewer than 2 matching letters is no match, and very long texts are not fitted. Notes, gap notes and summaries keep their inner blank lines and drop blank lines at their ends.

### Find searches every card's words, English, speaker, clip, ref and note, in the cut and on the shelf

- Searches every cut in the cut and on the shelf: its words as the lane shows them (only its own in-to-out span), its English and stored gloss, the person, the clip, the ^ref, the note. Letter case and repeated spaces are ignored; spaces between Chinese characters are ignored; a leading "^" is ignored.
- Desk: a pop-over under the header's box while it has text: "N match(es)" / "No matches", "Esc clears", up to 30 rows, then "N more. Add a word to narrow it down."
- Phone and landscape phone: the Find tab, with its own box focused on opening; up to 40 results; empty box "Search the words, speakers and ^refs of every card, in the cut and on the shelf."; nothing found "Nothing matches "q"."
- A row: the speaker's colour, short name, where it is ("§ 1.1", the section's name, "In the cut", "Staged - 1.1", or the shelf section's title), ^ref, and about 34 characters each side of the match with the match underlined.
- Picking a row clears the search. A cut in the cut: selected, playhead to its start, Cards view. A staged cut: shown in the inspector, Staged view.

- Phone and desk: a pop-over of up to 30 rows on a desk, the Find tab with up to 40 results on a phone.
- Name and search words: card Find: find card, search cut, search shelf, speaker, ref.
- Exact: yes

### An editor opens and closes the transcript search sheet from the header, the phone's Find tab or a key

{{31-001}}

- Ways in: the header's Transcripts button, the phone's Find tab, Ctrl+Shift+F.
- Phone and desk: a centred dialog on a desk, the whole screen up to 700 px wide.
- Name and search words: the transcript search: search transcripts, by meaning, closest wording, every interview, quote.
- Exact: yes

### The search sheet offers three kinds of search, and switching kind never asks the assistant by itself

{{31-002}}

- When the assistant is off: the switch is not shown and the sheet searches Exact words only. No Results, Model or New conversation picker, no splices, no earlier questions and no assistant status line show.
- Exact: yes

### The search sheet has pickers for which transcripts, how many results, which strength of assistant, and a fresh start

- "In" (which transcripts): All (labelled "All transcripts" in Exact words, "All interviews" in the assistant kinds), one row per interviewee, and "All corpus clips" (shown only when the episode has clip transcripts). Each row shows a count (interviews, that person's paragraphs, or clips). Changing it re-runs Exact words; in the assistant kinds it does not ask, shows a kept answer if any, else "press Search to ask this of <scope>". The scope goes back to All when a cut list of another episode is opened.
- What each scope covers in the assistant kinds: "All interviews" searches and ranks across every interview of the episode and leaves the corpus clips out; a person searches only that person's interview transcripts, and a passage from anybody else is not an answer; "All corpus clips" searches only the montage source clips, not the interviews. Each scope is its own conversation holding only its own transcripts: a search scoped to one person or to the clips reads only those transcripts, on its first search and on every later one, never the rest of the episode.
- "Results" (assistant kinds only): 5, 10, 20 or 50, default 5, remembered per device. Changing it re-asks the current question if an answer is on show. The server accepts 1 to 100 and brings any number outside that range within it; anything unreadable counts as 5.
- "Model" (assistant kinds only): three strengths of the assistant, named by what they do with the price of each: fastest (default), stronger, most capable, remembered per device. Changing it reloads the status line and, if an answer was on show, asks again, since each strength is its own conversation. The strengths themselves are described in The whole product: The assistant.
- "New conversation" (assistant kinds only, tooltip "Start this scope's Assistant conversation over: the next search reads its transcripts again"): starts the conversation for this scope, strength and kind over, forgets this scope's kept answers for that kind, and says "a new conversation: the next search reads <thing>". Other scopes' conversations are untouched.

- When the assistant is off: none of the assistant-only pickers show, and "In" offers its scopes to Exact words only.
- Exact: yes

### Exact words searches every transcript of the episode and the open cut list instantly as the editor types

{{31-004}}

Every paragraph of every transcript of the episode is searched in both languages; a transcript reached through several clips is searched once, and results are ordered by person. Answers stay instant at 500 transcripts: within a second, with a newer keystroke cancelling an older search.

- Exact: yes

### By meaning and Closest wording read every transcript in the chosen scope

The assistant kinds read every interview transcript of the episode (interviews first, in name order) and every transcribed montage source clip, as far as the chosen scope allows. Each paragraph goes to the assistant with its reference and, for a montage clip, its time; a paragraph with both lines goes with its English and its original. Interviewer questions are included. A paragraph with no reference can never be a result. A search writes nothing into the episode except the conversations it remembers.

- When the assistant is off: nothing is read and these kinds are not offered.

### By meaning asks the assistant which passages answer a question and shows only passages that really exist

{{31-005}}

- Of the two assistant kinds, By meaning is the one first offered. Meaning counts, not shared keywords, both languages count, and a later question may narrow, widen or argue with the last answer.
- When two transcripts share a paragraph reference, the paragraph of the interviewee the assistant named wins; a result outside the chosen scope is dropped.
- When several passages are equally strong, they are spread across the speakers.
- Each result shows the paragraph's own text, its time, whether it is a question, its transcript, and a way to open it in its transcript.

- Exact: yes

### Closest wording finds the spans where someone said something close to the words typed, in the original language only

{{31-006}}

A query in one language may be answered by words said in another. Each span shows its words as they are in the transcript, the whole paragraph with the place the words sit in it, the language, and the English beside it for a line that is not English.

- Exact: yes

### Assistant searches also suggest splices of fragments from different places that cut together into the idea

{{31-007}}

Each fragment is checked like a Closest wording span. A splice shows its total length in seconds when every fragment is timed. In By meaning, fragments are taken from the Mandarin where a paragraph has both languages.

- Exact: yes

### The first assistant search of a set of transcripts is slow because it reads them, and the sheet says which

- One conversation per episode, chosen transcripts, strength and kind, shared by every browser working on that episode. It stays warm while it has answered at least once, the transcripts have not changed, and it was last used under an hour ago, also across a restart of the server. A cold one first reads all the chosen transcripts, then answers.
- Status line, warm: "<strength> · by meaning|closest wording · warm, <n> turns in: it still remembers <thing> and your last questions"; cold: "... cold: the first search reads <thing>, about <time>". The "thing" is "every transcript", "the corpus clips" or "<person>'s transcript". The time is estimated from how long past searches took. The status line also shows the seconds since the last question, how much the scope and the whole episode hold, and the expected time warm and cold.
- When an answer came from a cold conversation its note says why: "the first search of the session reads <thing>", "a transcript changed since the last search, so <thing> <is/are> read again", or "the conversation had gone cold (over an hour), so <thing> <is/are> read again". The note, or "the same question was already running: this is its answer", appears on the status line.
- If the assistant lost the conversation, the transcripts are read again once and the question asked again; the note says "the Assistant session was lost (new machine or a rebuilt server), so the transcripts were read again". Lost twice: "the Assistant session was lost twice running: give it a moment and retry". Could not be opened twice: "the Assistant session could not be opened: the provider refused the id twice running".
- Before Search is pressed, the status line also shows the expected cost of this search in money, from its expected reading (cold or warm), and every assistant search counts against the site's one daily budget for the assistant (see The whole product: The assistant).
- When the assistant is not available: the line says "Searching by meaning needs Assistant on the server: <why or 'not installed'>" and Search shows the same as an error.
- Every answer records how much of what the assistant read was already held by the conversation and how much was read fresh, and the status line after an answer says both.
- Reading the transcripts gives up after 15 minutes per part, a question after 10 minutes, and a whole search after 40 minutes.

- Exact: yes

### Only one assistant search runs at a time per episode and asking the same question again joins the running one

{{31-009}}

The same question means the same words, transcripts, strength, number of results, kind and splices, wherever it is asked from: after a reload, from a second tab or from another person's browser.

- Exact: yes

### While an assistant search runs the sheet shows what it is doing and an estimated progress bar

The wait panel reads "Searching [for the closest wording in] <scope> [(<strength>)]: <query>", with a progress bar and a line such as "reading every transcript, part 2 of 4, about 60 s (an estimate) · 34 s so far", "the transcripts are read, now asking", "finding the closest words said", "asking". Past 115% of the estimate: "taking longer than the <n> s estimate". The bar runs evenly to 85% at the estimated time, then eases toward 95%, and is never full until the answer lands; it moves smoothly (about four times a second). Progress is refreshed from the server about every 2 s while the sheet is open, and the server's elapsed time wins over the device's clock.

The estimate says where it came from: measured (the middle of this conversation's last 6 searches of the same kind, warm or cold), scaled (from other conversations at the same strength and kind, scaled by size for a cold read), or a default (25 seconds warm, 60 seconds cold for the whole episode, scaled down for a smaller scope). It is never under 5 seconds. A warm search that has to read the transcripts again grows its estimate from that moment.

- Exact: yes

### A running assistant search outlives the page and reopening or reloading within an hour picks its answer up

{{31-011}}

- Exact: yes

### The sheet keeps the last 40 questions and their answers on the device

"Earlier questions": the last 40 assistant questions for this episode on this device, newest first (the same question, scope and kind listed once), each with the question, a "closest wording" chip when it was that kind, its scope and how long ago ("just now", "<n> min ago", "<n> h ago", "<n> days ago"). Each row keeps its answer. Clicking one restores the count, strength and kind it was asked with and shows its kept answer at once, marked "shown again, not asked again"; only a row whose answer the device had to drop is asked again. "Clear" forgets the history and every kept answer for the episode. Empty: "Nothing asked yet. A question is a sentence, not keywords: "the moment they realised nobody was coming"." Each kept answer is at most 160,000 characters; when the device's storage is full the oldest answers are dropped.

- Exact: yes

### Each search result is a card showing who said it, where, when, and the words with the English under them

{{31-013}}

- Exact: yes

### An editor can play any timed search result's audio straight from the sheet

{{31-014}}

Only one thing plays at a time: starting a result, the transcript, the lane or any other player, in any window of the same episode, pauses every other player, so two sounds never play together.

- Exact: yes

### An editor can insert a search result or a whole splice into the cut, and an interviewer question goes to the shelf

{{31-015}}

A result can also be dragged onto the lane and lands where it is dropped, with the same rules. Inserting or dropping one result never clears the others: the results stay until the editor runs a new search or closes them.

- Ways in: the Insert, Stage it and Insert all buttons, the I key on a result, dragging a result onto the lane.
- Exact: yes

### An editor can open the whole transcript at a result's paragraph and read, play and insert from it

{{31-016}}

- Ways in: Open transcript on a result, a right-click on a result, a touch-and-hold, the Q key.
- Exact: yes

### The search sheet is fully driven from the keyboard and its keys never reach the editor's own shortcuts

{{31-017}}

- Exact: yes

### The search refuses clearly when there is nothing to search or the request is wrong

Messages: no cut list named, "which cut list?"; no episode folder, "there is no episode folder for this cut list"; empty query, "type what you are looking for"; assistant unavailable, "the transcript search needs Assistant: <why>"; "this episode has no corpus clips to search"; "there is no interview transcript for <person> under this episode"; "no such search scope: <scope>"; no transcripts at all, "there are no transcripts under this episode yet: nothing to search"; a transcript asked for that is not there, "that transcript is not in this episode" or "there is no paragraph ^<ref> in it"; any other failure, "the search failed: ...". Search never looks outside the studio's project tree.

- Exact: yes

### A passage's clip and time come from its transcript's word timing and untimed passages cannot play or be inserted

Each interview transcript belongs to its interview's multicam, and a clip's transcript belongs to its own clip. Where each word is timed, a passage is placed exactly. Where only subtitle-level timing exists, every time is approximate and shown with "≈". With no timing at all, nothing in that transcript can play or be inserted.

The original-language line of a paragraph is recognised by its script (any non-Latin script making up at least a fifth of the line), so Russian and Ukrainian interviews search as well as Chinese ones. A line's language is decided by its script: Chinese, Russian, Ukrainian, or "Russian or Ukrainian" when it cannot tell, in which case the transcript's own language is used where that is clear. A new or changed transcript is seen by search within a couple of seconds.

#### Lessons

- Met: CE2-070, CE1-004, CE1-006, CE1-009, CE1-010, CE2-071, CE2-073, CE2-075, CE2-077, CE2-078, CE2-081, CE2-082, CE2-083, CE3-048, CE3-050, CE3-051, CE3-053, CE1-005, CE1-007, CE1-008, CE1-011, CE2-072, CE2-074, CE2-080, CE2-084, CE3-049, CE3-052.
- Met for another part: CE1-049 (in "Dropping media files on the panel hands the clips to footage in and lists each one in the intake"), CE3-030 (in "A highlighted stretch of transcript becomes a card of exactly those words"), CE2-091 (in "The search sheet has pickers for which transcripts, how many results, which strength of assistant, and a fresh start").
- Not yet met by any behaviour above: CE1-012 (choosing several transcripts at once in the episode's browser of transcripts and cut lists: no behaviour here shows it, and it belongs with opening episodes), CE3-054 (building a montage by describing it belongs with the board and footage-in montages, not with search).

## Chinese text and matching

### Every search in the editor matches Chinese and English forgivingly and understands pinyin

{{40-024}}

- Exact: yes

### The transcript's find box searches both lines, folding Chinese scripts, Russian ё and apostrophes, and understands quotes, paragraph ids and pinyin

- The box: "Find: words, or pinyin (chu1, chuqu, 出qu)", in the transcript header, with a count and previous/next buttons (disabled with fewer than 2 hits).
- Count: empty when nothing is typed; "0" with no hits; "17" after typing (no current hit yet); "3 / 17" once Enter has gone to a hit.
- Plain text: case-insensitive, on both lines, Simplified and Traditional characters treated as the same (醫院 finds 医院, 陳 finds 陈). Russian ё is treated as е, and the typographic apostrophes (’ ʼ ‘ ` ´) as a plain apostrophe.
- Quoted ("..." or with curly quotes, at least 3 characters including the quotes): exact case, no script folding, and whole word wherever the query's edge is a letter or digit that is not a Han character ("I" does not match the i in "it"; Cyrillic counts as letters).
- "^id" (the first non-space character is ^, then letters, digits, underscore or hyphen): goes to the paragraph with that id (case-insensitive). Only when no paragraph has the whole id, every paragraph whose id starts with it.
- Mixed Han and Latin letters (老ren, yi院, 出qu, guo王): a pinyin search. Characters match themselves and each letter run must be the sound of the characters in that spot, where a prefix of each reading is enough (dh finds 的話).
- Pure pinyin (letters only, with optional tone digits 1 to 5, spaces or apostrophes; at least 2 letters): each Han character takes a whole syllable, the last may still be being typed (chuq finds 出去). A digit after a syllable is its tone (5 = neutral); without one any tone matches. ü is typed v (lv = 綠). Ordinary text hits are kept as well ("he" finds the English word and 和). Every reading of a character counts (得 = de and dei). A query longer than 64 characters is never pinyin.
- Each key gives its answer at once, even in a long transcript.

Script folding and pinyin work on every install. If the server ever cannot fold Chinese scripts or give readings, the find still matches with letter case folded, and the panel's warning line says that Chinese script matching and pinyin are not available on this server, so that the find never quietly matches less than it seems to.

- Exact: yes

### Chinese in either script is compared as the same words

Matching text, searching and placing a cut all compare Traditional Chinese (including Taiwan forms such as 臺) and Simplified Chinese as the same words, character for character, without changing lengths or positions and without rewriting any text. So a selection made in one script always finds the timed words written in the other, and a cut placed from either script lands on the same words. Chinese characters count as words whatever spacing appears between them.

#### Lessons

- Met: CE1-001, CE1-002, CE1-003.

## The English a cut shows

### Which words a clip shows and in which language follows set rules

- A card's lines in a non-Latin script are the spoken words; Latin lines beside them are its English. An all-Latin card is English (an English interview), unless a translation says otherwise.
- The English comes from, in order: the English the editor's analysis provides; the card's own English line. No other English is ever shown: every English line comes from the transcript's own translation.
- With English leading, a clip with no English leads with its original and carries the no-English tag ("no English", "loading…" while it is being made, or the reason once known).
- The second line shows only when it differs from the first.
- While an edge moves, the clip's text is re-cut from its timed words at once, before the server has saved it; the stored English is kept only while the words are the same (within two characters, ignoring spaces and punctuation).
- A word belongs to a cut when its midpoint is inside the cut. A clip's word timings come from its per-word timings, else its subtitles; a clip without any is checked again after about half a minute, so new timings appear by themselves. Up to 60,000 words per clip.

- Exact: yes

### The editor names the language of a stretch of speech by its script

The script with the most letters wins.

- Han with kana: Japanese when kana is at least 10 percent of it, else Traditional Chinese when characters only Traditional writes outnumber those only Simplified writes, else Chinese.
- Hangul: Korean.
- Cyrillic: Ukrainian or Russian by the letters only one of them writes; with neither, Russian at 200 or more Cyrillic letters, else "Russian or Ukrainian".
- No such script: English when plainly English (at least one, and at least 20 percent, common English words; accented letters only in capitalised Latin names, at most a third of the words), else unknown.

A line of a cut is the original language when its share of non-Latin characters is at least half that of the most original line; with no non-Latin script, a line that has letters and is not plainly English is the original.

Names shown: Mandarin, Russian, Ukrainian, "Russian or Ukrainian", Japanese, Korean, English. Labels on the language switch: 中文, RU, UK, RU/UK, 日本語, 한국어, EN, or "Original". A Russian and Ukrainian mix says RU/UK; three or more languages say "Original".

### An editor switches between English first and the words as spoken first everywhere at once

{{31-052}}

- Setting: English first or the words as spoken first. Does: chooses which line leads on cards, the shelf, the edit view and the lane. Default: English first. Who: anyone who can open the editor. Applies to: a computer. Search words: English first, original first, spoken words, language order, EN.
- Ways in: the EN and Original buttons in every editor header, the switch in the edit view's header, the lane bar's language toggle, Alt+L.
- Exact: yes

### A card shows its English and its spoken words in the order the switch says

{{31-053}}

The card the editor is working on shows all of its original text, never cut short. In the edit view the English and the original share one size and one colour.

- Exact: yes

### A card's English is taken from the transcript's own English and follows every trim at once

{{31-054}}

- Exact: yes

### Under a card not in English the matching slice of the transcript's English is shown dimmed

{{40-013}}

- Exact: yes

### A trimmed or split cut's English is worked out from the line-ups and marked approximate only when it truly is

The English of every cut is built from the transcript's own line-ups of original phrases with their English, for exactly the words the cut plays.

- A cut inside one paragraph: its English is every phrase whose original words are all in the cut. A phrase the cut divides is cut at the word by the word links between the original and the English when there are any, else dropped when the cut holds under half of its words, else cut in proportion (phrases under 4 English words are kept whole). The English is approximate when an edge falls inside a phrase or a word of the cut belongs to no phrase. A trailing dash is removed.
- Where several line-ups hold the cut, the first stands unless another leaves fewer of the cut's words without English at a cost of no more than about 14 English characters per recovered word (plus 10).
- A cut across paragraphs: its letters are matched against the paragraphs (its head may be the tail of one, its end the head of another). Scattered unmatched letters are tolerated up to the larger of 4 letters or 15 % of the cut. A stretch of 6 or more unmatched letters is speech no paragraph holds (an interviewer's question, for example): that stretch shows as a gap in the original language, the rest of the cut still shows its English, and the English is marked approximate, as long as the paragraphs still hold at least 30 % of the cut's letters (and at least 8). A small part (under 4 words or 15 % of the cut) without English is left out; a larger part without English fails the whole cut.
- The same words in the other Chinese script (same letter count, at least two fifths equal place for place) take the line-up's whole English.
- The transcript paragraphs' own line-ups are tried before those made for earlier cuts of the same words.
- The product can tell when a cut's English says more than the cut (a phrase of 12 or more letters the cut holds under half of, whose English is there) or less (a phrase of 4 or more letters the cut holds whole, whose English is missing).
- "Approximate" only ever describes what truly is approximate: the English of a cut, or a time placed from subtitles. A cut's own edges are frame-exact and are never called approximate, and what the editor says about a cut's timing matches what the hand-over to the editing program will produce.

How the line-ups and the word links are made is described in Timeline Cards: footage in, ready to cut, Word links between the original and the English.

### The lane shows each card's English or says why there is none

{{31-055}}

- Exact: yes

### Standing problems with the English are listed in View settings instead of covering the cards

View settings row "Translation problems". Logged: "Offline: the English on this device is shown; new translations wait for the network."; "The server did not answer for the English: <why>". The same sentence is one row with first and last time and a count, newest first, at most 40 rows, sentences cut to 400 characters. Header "none" or "<n> conditions, <k> current"; empty "Nothing has gone wrong with translation on this page."; "Clear the log" keeps the current ones.

- Name and search words: Translation problems: English problems, translation log, offline English, no English.
- Exact: yes

### Picking English words on the lane maps them to the spoken words they stand for

{{29-051}}

- Exact: yes

### Selecting part of the English line in a transcript selects the original words it translates

{{30-028}}

- Exact: yes

### When an insert comes from an English selection that lined up word for word the new cut keeps that English

The English the editor selected travels with the new card and becomes the English that cut shows, so the card reads exactly what was chosen. When the English did not line up word for word, the cut takes the whole original sentence, marked approximate, and its English follows the usual rules for a cut's English (above).

### Selecting English on a card, a shelf item or a search result shows the original words it stands for in a floating toolbar

- A selection inside one English line of a card, a shelf item, or a search result highlights the matching original words in that card's or result's own original line.
- A floating toolbar ("English selection: the original words") appears over the selection, kept inside the window, on the side away from the original line:
  - while mapping: spinner, "Lining the English up with the original…", Cancel;
  - when it cannot map: the reason;
  - when mapped: arrow, the original words, and "Approximate" (reason as tooltip) when it is;
  - Start earlier/later and End earlier/later buttons (one word each);
  - for a card in the cut: Play, Delete words (tooltip "Cut exactly these original words out; the rest closes up"), Highlight, Split here, Copy original. Play plays those words on the lane (moves the lane head there and stops after their end). For a card on the shelf the same buttons without Play. Delete words, Highlight and Split here do what the lane's own word tools do, with their message; after a successful Delete or Split the toolbar closes;
  - for a search result: Open in the transcript (tooltip "Insert, put on the shelf or play these words from the transcript"; "The transcript panel is not available here." when it cannot) and Copy original;
  - Close (x).
- Esc closes the toolbar; clicking elsewhere (losing the selection) closes it unless the pointer is over it; pressing its buttons does not lose the selection. A card removed from the cut list closes its toolbar. A newer selection withdraws the older one's ask.
- Copy: "The original words are copied." / "The clipboard would not take it."
- Open in the transcript: the panel opens the clip's transcript at the paragraph and selects the same English there (finding a partial English inside the paragraph's English if needed); "that paragraph has no English line here" or "<clip> has no transcript in this episode" when it cannot.
- On the lane, an English pick on a clip maps to its spoken words the same way, answering ready, approximate with a reason, pending, or nothing with "open a cut list first", "this clip has no word timings yet", the text's problem, or "the selection holds no words".

The word tools the toolbar shares with the lane (Delete words, Highlight, Split here) are described in Timeline Cards: the editor, Selecting, deleting, inserting and keys.

- Ways in: the transcript's action bar, the floating toolbar on a card, a shelf item or a search result, a drag or hold across a clip's English in the lane.
- Exact: yes

### A settings row shows how far the English is lined up with the original

Settings row "English to original alignment":

- status line: "Not available on this server." / "Waiting for the server…" / the pause reason / "Lining up N paragraph(s) in the background." / "N lined up since the server started, F could not be.";
- "<amount> spent today, B paragraphs a call": what lining up has cost today, out of the site's one daily budget for the assistant (see The whole product: The assistant).

Lining up runs on its own until the site's daily budget for the assistant is spent; it then waits for the next day's budget, with nothing failed and nothing lost, and the row says it is waiting for tomorrow's budget and an English selection waiting on it falls back to the whole original sentence, marked approximate.

- When the assistant is off: the row is not shown, and every English selection takes the whole original sentence, marked approximate.
- Exact: yes

### Ten reading aids help an editor cut speech in a language they do not read, each switched Off, on for languages not read, or on for all

The aids show on transcript paragraphs, on cards (including shelf items) and in the lane.

| # | Settings label | Settings hint | What shows |
|---|---|---|---|
| 1 | Playhead word in both languages | "The word being said, lit in the original and in its English" | the English that renders the word being spoken, tinted cyan, on the transcript paragraph holding the transcript playhead (original line only), on the playing card (the word under the lane head while the lane plays inside it), and in the lane, frame by frame |
| 2 | Sentence ends and numbers | "Each sentence numbered, the same number on its English" | a small gold number at the start of each sentence of the original and of its English (only when the original has more than one sentence); the lines get extra spacing to hold them |
| 3 | Verbs | "Verbs underlined in both languages" | a solid gold underline; an auxiliary, a copula, or a verb inside a compound noun is not marked |
| 4 | Safe cut points | "Green: a cut here leaves a whole thought. Red: it strands a clause" | ticks between words of the original (see the lane's safe cut points); also turns on the nudge for picks and dragged edges |
| 5 | Not, if and but | "Negation, conditions and contrast words flagged" | negation in red with a solid underline; conditions and contrast in red with a dashed underline |
| 6 | Join check | "After a splice or trim, Assistant reads the joined original again" | the join check, below |
| 7 | Word-by-word gloss | "A literal English word under each original word" | a "Word by word" line under the original (transcript, cards and lane), each gloss lit as its spoken word plays |
| 8 | Names, places, numbers, dates | "Marked so they can be heard and checked" | names and places dotted cyan underline; numbers and dates dashed cyan underline |
| 9 | Fillers | "Hesitations and filler words, marked as trimmable" | greyed with a faint strike-through |
| 10 | Romanisation under Cyrillic | "Latin letters under Russian and Ukrainian words" | a "Romanised" line under the original (transcript and cards) |

- Modes per aid: Off (never), Not read (on for languages not in "Languages I read"; the default for eight aids), All (on for every language; the default for aid 1). Aid 7 is Off by default.
- Languages I read: toggles for English, Chinese, Russian and Ukrainian; default English and Chinese. Traditional Chinese counts as Chinese; a mixed Russian/Ukrainian clip counts as Russian.
- So by default a Russian or Ukrainian clip shows every aid except the word-by-word gloss, and a Mandarin or English clip shows only aid 1.
- The settings are kept per device (this browser); unreadable settings fall back to the defaults; if the browser refuses to keep them, they last for the session.
- No mark changes size or weight: every mark is an underline or a tint, so nothing reflows. Each kind has its own line style besides its colour, colour is never the only signal, and marks never cover a selection. The "Romanised" and "Word by word" lines cannot be selected as text.
- Skipped: an English interview, a paragraph or card with no original line, or a line whose language cannot be told.
- With no set-up at all, the spoken word and its English light together on the lane, the cards and the transcript, also after trims. A spoken word with no clear English lights nothing.
- The gloss and the word links of aid 1 and the join check by the assistant are absent when the assistant is off or unavailable; the other aids still show.

The safe cut points and the key that moves an edge to one are described in Timeline Cards: the editor, The lane: clicking, trimming, zooming and dragging.

- Setting: Playhead word in both languages. Does: lights the word being said in the original and in its English. Default: All. Who: anyone who can open the editor. Applies to: a computer. Search words: playhead word, lit word, both languages, reading aid.
- Setting: Sentence ends and numbers. Does: numbers each sentence of the original and gives its English the same number. Default: Not read. Who: anyone who can open the editor. Applies to: a computer. Search words: sentence numbers, sentence ends, reading aid.
- Setting: Verbs. Does: underlines the verbs in both languages. Default: Not read. Who: anyone who can open the editor. Applies to: a computer. Search words: verbs, grammar, underline, reading aid.
- Setting: Safe cut points. Does: shows green and red ticks where a cut leaves a whole thought or strands a clause, and turns on the nudge for picks and dragged edges. Default: Not read. Who: anyone who can open the editor. Applies to: a computer. Search words: safe cut, cut points, ticks, clause, reading aid.
- Setting: Not, if and but. Does: flags negation, condition and contrast words. Default: Not read. Who: anyone who can open the editor. Applies to: a computer. Search words: negation, condition, contrast, not if but, reading aid.
- Setting: Join check. Does: has the assistant read the joined original again after a splice or trim. Default: Not read. Who: anyone who can open the editor. Applies to: a computer. Search words: join check, splice, meaning changed, grammar break.
- Setting: Word-by-word gloss. Does: shows a literal English word under each original word. Default: Off. Who: anyone who can open the editor. Applies to: a computer. Search words: gloss, word by word, literal English, reading aid.
- Setting: Names, places, numbers, dates. Does: marks them so they can be heard and checked. Default: Not read. Who: anyone who can open the editor. Applies to: a computer. Search words: names, places, numbers, dates, reading aid.
- Setting: Fillers. Does: marks hesitations and filler words as trimmable. Default: Not read. Who: anyone who can open the editor. Applies to: a computer. Search words: fillers, hesitations, um, trimmable, reading aid.
- Setting: Romanisation under Cyrillic. Does: shows Latin letters under Russian and Ukrainian words. Default: Not read. Who: anyone who can open the editor. Applies to: a computer. Search words: romanisation, Cyrillic, Latin letters, Russian, Ukrainian.
- Setting: Languages I read. Does: decides which languages the aids set to Not read stay off for. Default: English and Chinese. Who: anyone who can open the editor. Applies to: a computer. Search words: languages I read, reading aids, my languages.
- When the assistant is off: the gloss, the word links of aid 1 and the join check by the assistant are absent, and their rows are not offered; every other aid still shows.
- Exact: yes

### The language aids settings panel shows what the server can analyse and what the editor's own assistant work has spent today

Settings panel "Language aids":
- a status line: "The aids service is not on this server." / "Asking the server…" / "Asking the server about language analysis…" / "Language analysis: <what is available> (<languages>)." / "Language analysis is not available: <why>. Only the word lists and the romanisation show." (warning colour);
- "Languages I read" toggle buttons (tooltip "I read <language>: its aids are off unless an aid is set to All");
- one row per aid: number, label, hint, and Off / Not read / All buttons (tooltips "Off everywhere", "On for the languages I do not read", "On for every language");
- "<amount> spent today, <amount> left": what the editor's work running on its own (lining the English up with the original, glosses, word links and join checks) has cost today, and what is left of the site's one daily budget for the assistant. The budget itself is set by an admin, in money, with the assistant's other settings (see The whole product: The assistant); there is no count of calls.
- This work may spend the whole day's budget. When the budget is spent, lining up, glosses, word links and join checks by the assistant wait for the next day's budget, like everything else that uses the assistant; nothing fails and nothing is lost, and the panel says it is waiting for tomorrow's budget. Searches and other work a person starts show their expected cost before they run and count against the same budget.

- Name and search words: Language aids: reading aids, languages I read, gloss, verbs, safe cuts.
- When the assistant is off: the amounts spent and left are not shown.
- Exact: yes

### The aids read each line's grammar, words and names in Russian, Ukrainian, Chinese and English, and fall back to word lists when that analysis is missing

- Russian, Ukrainian, Chinese (both scripts) and English lines are analysed for words, sentences, parts of speech, grammar and names. Other languages get only the romanisation and no analysed aids. A Cyrillic line with no stated language counts as Ukrainian if it has і, є, ї or ґ, else Russian; a Han line counts as Chinese. Lines over 6,000 characters are not analysed.
- Verbs: the grammar's verbs, not inside a compound. Numbers: numerals and amounts, money, percentages, ordinals. Names and places: named people, organisations, places and buildings; for Chinese, runs of proper nouns.
- Dates: dates and times, plus each language's date words as whole words (months and weekdays with their case endings, the words for the day before, the same day and the day after; for Chinese, a number followed by 年 月 日 號 點 分 秒 週 星期, and 昨天/今天/明天/去年/今年/明年/前年/後天) when they are not used as adjectives, verbs or pronouns.
- Negation, condition, contrast and filler word lists per language (Russian, Ukrainian, Chinese in both scripts, English), including two-word entries ("как бы", "you know", "тем не менее"). Chinese entries are found inside a word, longest first (沒有 before 沒). Sure words always count (for example не, если, однако, 如果, 但是, not, if, um); others count when the grammar agrees (a negating particle; a subordinating "if"; a joining "but" or a sentence-opening adverb; a discourse word, interjection, hesitation, or an opener followed by punctuation such as "Ну, ..." or "Well, ..."). Words the grammar marks negative or conditional are marked even if not listed.
- Hesitations are always fillers: Russian э/эм/мм/хм, Ukrainian е/ем/мм/хм, Chinese 嗯呃欸誒诶唔, English uh/um/er/erm/hmm/mm/ah.
- Without the analysis: only sure list words, hesitations and numbers written in digits; sentences by punctuation; no verbs, names, cut ticks or analysed marks. A small line above the panel's status line then says "Language aids are limited: the server has no language analysis (it is not installed), so only the word lists and the romanisation show." when a paragraph with an original line is on screen and any aid is on for its language; it has a dismiss x, remembered on this device for good.
- Sentences: as the grammar finds them, else by punctuation (。！？!?…;； or a line break, a full stop followed by a space or the end and not by a digit, closing quotes and guillemets kept with their sentence).
- Sentence numbers: when the original and its English have the same number of sentences, they are numbered in order; otherwise each English sentence takes the number of the original sentence most of its phrases point into, and one that points nowhere gets no number.
- Each line is analysed once, and the result is kept and used by every cut list.

### Romanisation under Russian and Ukrainian follows the national standards and never leaves a Cyrillic letter

Russian follows BGN/PCGN: е is "ye" at a word start and after a vowel, ё is "yo", х is "kh", щ is "shch", and ъ and ь are dropped. Ukrainian follows the national system: є ї й ю я are "ye yi y yu ya" at a word start and "ie i i iu ia" inside a word, зг is "zgh", and the apostrophe and ь are dropped.

The system is the clip's language, but a word with a letter only the other language writes uses the other system. Letters of other Cyrillic alphabets get a plain fallback, so no Cyrillic letter ever appears in the Latin line. Capitals follow the original, and all-caps words stay all caps. Latin words, digits and punctuation pass through unchanged. Romanisation needs no assistant, so it shows when the assistant is off.

### The join check reads every new splice of one speaker again and says on the card and in the lane whether it reads well, changed the meaning, or broke the grammar

- A join is where two consecutive cuts meet and the speech should run on: the same clip (not simply continuing within 0.04 s with no gap) or the same speaker. Two speakers meeting is not checked. A gap row between them still counts; a heading row ends the run. Cuts whose word timings are not known yet are checked when they arrive.
- Compared: the last words of the first piece (at most 30, from its last sentence start when that leaves at least 3), the first words of the second (at most 30, up to its first sentence end), for the same clip the words dropped between them (at most 60, only when the second piece is later in the clip), and each cut's English when shown. Without word timings, the last/first 160 characters of each cut's text.
- Quick check (at once, needs no assistant):
  - meaning: "The cut drops "<word>" (a negation) from between the two pieces: the joined sentence may say the opposite.";
  - grammar: "The first piece ends on "<word>", which waits for a clause that is not there." (the first piece ends, not at a sentence end, on a condition or contrast word);
  - grammar: "The first piece ends mid-clause: ..." / "The second piece starts mid-clause: ..." (or "A side of the join strands a clause.").
  - Nothing found is not "ok"; only the assistant says that.
- The assistant's check: the joined original is translated afresh and judged ok, meaning (a negation, condition or contrast lost, a reversed claim, the wrong subject) or grammar (a hanging clause, a missing verb or object, disagreement across the join), with a one-sentence note (at most 300 characters).
- The assistant is asked only for joins an edit made or moved within the last 15 s, when aid 6 is on for that language, about a second after the edit settles; opening a cut list only shows checks already made. A check belongs to the joined words: moving the join makes the old answer stop applying. A check never blocks an edit. Switching cut list withdraws the previous list's waiting checks. It counts against the site's one daily budget for the assistant, and when that is spent it waits for the next day's.
- On the second card of a join: a button above the card: "Checking the join" (hollow dot), "Join reads well" (green), "Join: meaning changed" (red), "Join: grammar break" (gold), plus "quick check" when the answer is the quick one. Spoken label "Join check with the card before: <label>" ("the join reads well", "meaning changed: <note>", "grammar break: <note>", "checking the joined words"). Clicking it shows/hides a box with the note, the joined original, and "Now reads: <fresh translation>" (or "Assistant is reading the joined words again."). Pressing it never selects or drags the card. Touch targets are 44 px on touch screens.
- In the lane: a dot on the seam with the same states and an open box ("Now reads: ..."); a quick answer's dot has a dashed ring.
- "Checking" shows only after the assistant was asked for this join.

- When the assistant is off: only the quick check shows, with its "quick check" mark, and no join is ever marked "Join reads well".
- Exact: yes

#### Lessons

- Met: CE1-017, CE1-018, CE1-019, CE1-020, CE2-085, CE2-086, CE2-087, CE3-065, CE1-013, CE1-014, CE1-015, CE1-016.
- Met for another part: CE2-061 (in "The join check reads every new splice of one speaker again and says on the card and in the lane whether it reads well, changed the meaning, or broke the grammar").
