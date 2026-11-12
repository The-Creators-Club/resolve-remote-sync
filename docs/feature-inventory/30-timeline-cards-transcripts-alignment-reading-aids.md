# Timeline Cards editor: the transcript panel, English-to-original alignment, and reading aids

Terms used throughout:

- **Cut list**: the editor's open document, a list of cuts. A **cut** (shown as a **card**) is one stretch of one interview clip: its clip name, its in and out point in **source seconds** (seconds from the clip's own start), its speaker, its colour, its words, its `^ref` and its highlights.
- **The shelf** (also "staged", "the bench"): cuts kept beside the cut list, not in the edit.
- **The lane**: the timeline strip of the cut list. **The lane head**: the lane's playhead.
- **Transcript**: an interviewee's `*_Transcript.md` in the episode vault. It is split into **paragraphs** (blocks between blank lines). Each paragraph has an optional `^ref` id (a `^` line), an **original line** (the spoken language: Mandarin, Russian, Ukrainian, ...) and an **English line**. A paragraph with a `#` line is an **interviewer question**.
- **Word index**: per transcript, every spoken token (word) mapped onto character offsets of a paragraph's line, with source seconds. Offsets are code points throughout.
- **Timed words**: a clip's `<clip>_words.json` (whisper word timings) or, failing that, its `.srt` subtitle cues.
- **Op**: one edit to the cut list. One op is one undo step (Ctrl+Z).
- **Episode**: the folder above `Script Docs/` in the cut list's key (path).
- **Fleet**: the CC Sync machines that take background jobs through the dashboard.
- **Claude runner**: the editor server's single shared way of calling Claude.
- **Python pool**: the editor server's shared pool of Python worker processes.

---

## 1. Opening, closing and placing the transcript panel

(source: transcripts/client.ts, transcripts/styles.ts)

- **The panel** is a side panel titled "Transcript", labelled as a dialog, hidden until opened.
  - Its bar shows the title, a quiet count on the right ("N in the episode" on the list of transcripts; "N paragraphs", plus " · lining up M" or " · K lined up" for the alignment progress on a transcript), and a Close button (x icon, key hint "2").
  - The count's tooltip on a transcript says "English lined up with the original in K of N paragraphs" and "(F could not be)" when some failed.
  - The transcript name in the header carries a tooltip with the file name, the paragraph count and the alignment progress (because the bar is hidden when docked).
- **Launcher button**: a "Transcript" button (key hint "2", tooltip "Read a transcript and insert passages from it") is added to the editor header after its spacer, or at its end. Clicking it opens the panel, or closes it if open. It shows pressed while the panel is open.
- **Key 2** (no Shift, no Ctrl/Alt/Meta, not auto-repeat, not while typing in a text box or editable area): opens the panel and moves the keyboard focus into its paragraphs, or closes it.
  - Shortcut sheet entry: "Open or close the transcript".
- **Shift+T** (same conditions): shows the selected cut in its transcript (the last selected card, else the cut under the lane head). With neither: "select a card first, or put the head on one".
  - Shortcut sheet entry: "Show the selected cut in its transcript".
  - Plain T is not this panel's (it is the translate feature's).
- **Who listens for 2 and Shift+T**: when the platform mounts this feature, the two keys are registered in the shell's shared key list; until then, or after the feature is removed, the panel listens for them itself, so they never go dead.
- **The pad's "transcript" view**: switching the editor's view mode to "transcript" opens the panel; switching away from it hides the panel. Closing the panel while in that view switches the view back to "cards".
- **"Browse transcripts" from elsewhere**: a `tc:transcripts-browse` window event opens the panel on the list of transcripts with the keyboard focus inside it.
- **Double-click a card** (left button, on the card but not on its buttons, boxes, links or editable text): moves the lane head to the start of that cut and opens its transcript at the cut. The panel takes the double-click before the cards view does, so the cards view's own double-click action (open the edit view) does not run.
- **Double-click a clip in the lane** (left button; not on the lane's bar, ruler, minimap, buttons or boxes): opens the transcript of the clip under the pointer at that cut (found the same way a click selects a clip). In the zoomed trim lane it is the selected cut, else the cut under the head.
- **Selecting a card while the panel is open** follows it: the panel shows that cut in its transcript. Exceptions:
  - nothing happens while paragraphs are picked or text is selected in the panel (they would be lost);
  - a selection made in the lane does not move the transcript (a press in the lane within the last 1.5 s, or the keyboard focus in the lane). Only a double-click in the lane does.
  - Only a single selected card counts.
- **Placement on a desktop** (window wider than 700 px): the panel runs from the header's bottom edge (56 px if there is no header) down to the lane dock's top edge when the dock is in the lower half of the window, or from the dock's bottom edge down when the dock is at the top. It never covers the lane, and it follows the dock live as it is resized or moved top/bottom and as the window resizes.
  - If that leaves less than 240 px, the panel keeps 240 px and overlaps the dock instead.
  - Nothing is watched while the panel is closed.
  - Default width: up to 560 px, docked to the right edge.
- **Placement on a phone** (700 px or narrower): the panel is the whole screen width from the top.
- **Shift+F, full height**: with the pointer over the panel or the keyboard focus inside it (never while typing in a box, never with Ctrl/Alt/Meta, not auto-repeat), the panel goes to the full height of the window at the left edge and width it had, over the lane. Shift+F again, Esc, or closing the panel puts it back. It cannot be turned on while the panel is hidden.
- **Esc from anywhere** (no modifiers, panel open): see section 9 for the full order. If the panel is full height, Esc first puts it back.
- **Closing the panel** also: leaves full height, cancels the background alignment it queued, pauses the transcript's audio, ends a held Space, and stops watching the layout.
- **Changing cut list** (the open document changes): pauses the transcript audio, forgets the list of transcripts, the open transcript, picks, selection and the shown cut, and reloads the list if the panel is open.
- **Words service keep-alive**: while a cut list is open, the page asks the server to run the words service for it at once and again every 5 minutes (POST `/api/transcripts/watch`), whether or not the panel is open.

## 2. The list of transcripts (the picker)

(source: transcripts/client.ts, transcripts/library.ts, transcripts/shared.ts)

- **What it lists**: every folder under the episode's `Interviewees/` (kind "Interview") and `Clips/` (kind "Montage") that holds a `*_Transcript.md` or a clip's word or subtitle file.
  - Folders starting with "." and folders named `legacy` (any case) are skipped.
  - At most 2,000 folders are scanned per episode.
  - The transcript file is `<folder name>_Transcript.md` (any case), else the first `*_Transcript.md` in name order.
  - A folder's clips are every `<clip>_words.json` (whisper words), `<clip>.whisper.srt` and `<clip>.srt`. `<clip>.resolve.srt` files are ignored.
  - Length: the sum of the `duration` each words file states, read from the first 4 KB of the file only (cached by size and modification time, up to 4,000 entries).
  - Word timings per source: "whisper" when any clip has a words file, "srt" when any has subtitles, else "none".
  - The scan is cached for 3 seconds per episode (at most 32 episodes cached).
- **Header**: "Transcripts" and the first part of the cut list path; a "Back to the transcript" button when a transcript was open.
- **Filter box**: "Filter by name", matches the person (folder) name and the clip names, case-insensitive. It keeps its text across redraws.
- **Kind facet** (three buttons): All / Interviews / Montage.
- **Use facet** (three buttons): Any use / In this cut (at least one cut of its clips in the cut list) / Not used (no cut of its clips in the cut list or on the shelf).
- **Person filter** (drop-down "Anyone" plus each interviewee name, sorted): shown only when the episode has more than one interviewee. Montage sources have no person entry. A remembered person that disappears resets to Anyone.
- **Length filter** (drop-down): Any length / Up to 30 s / 30 s to 2 min / 2 to 10 min / Over 10 min. A source of unknown length shows only under Any length.
- **Word timings filter** (drop-down): Any timings / Whisper words / Subtitles only / No timings.
- **Bins rail** (see section 3), under the filters, scrolling with the list.
- **Intake** (see section 4), above the list when it has rows.
- **Each row** (a button):
  - a colour stripe in the speaker colour the cut list uses for that clip (the colour of the first cut of any of its clips);
  - the person name;
  - a meta line: "Interview" or "Montage" · "1 clip" or "N clips" · length as m:ss (when known) · "whisper words" / "subtitles only" / "no timings", or "no transcript yet";
  - chips: the bin name (only when the bin filter is All), "N in the cut", "N staged";
  - marked current when it is the transcript open in the panel;
  - a row with no transcript file is disabled and cannot be opened.
  - Click (or Enter/Space on it) opens that transcript.
  - Rows off screen are not laid out until scrolled near (an episode can have hundreds).
- **Empty and loading states**:
  - "Loading the episode's transcripts" with a spinner;
  - on failure, the warning line says "the transcripts did not load: <reason>" and the body shows a "Try again" button;
  - with no cut list open: "open a cut list first";
  - "No transcript matches those filters." when filters hide everything;
  - "This episode has no transcripts yet (Interviewees or Clips folders with a _Transcript.md)." when there are none.
- **Drop hint** at the bottom (hidden on a phone): "Drop media files here to queue whisper, proxy, audio or peaks jobs for the fleet".
- **Loading**: opening the list fetches the sources, the bins and the intake at once; the bins and intake are optional, so the list opens without them. If the intake has rows and a fleet is configured, the machine list is fetched too.

## 3. Bins (named groups of transcripts)

(source: transcripts/bins.ts, transcripts/client.ts, transcripts/server.ts)

- **Storage**: `<Episode>/Script Docs/cards_bins.json`, shape `{"bins": [names], "of": {clip stem: bin}}`, the same file and shape the old app uses.
  - Read from the working copy when there is one, else from the vault.
  - Written to the working copy when the editor runs with one; else to the vault when the run may write (`--write`); else never (read-only).
  - A working copy with no bins file starts from the vault's.
  - Every change re-reads the file first (another program may have changed it), changes are one at a time per file, and the file is written to a temporary file then renamed, so a crash never leaves half a file.
  - A file larger than 4 MB, or that does not parse, reads as empty. Unknown keys are dropped, duplicate bin names merged, and a filing to a bin not in the list adds that bin.
- **Strict filing**: a clip is in at most one bin; filing it moves it. A source with clips is filed under all its clip stems; a source with no clips under its folder name. A source's bin is the first of its keys that is filed.
- **The rail** (shown when the bins loaded):
  - "All bins" chip with the total source count; tooltip "Every transcript. Drop one here to take it out of its bin" (writable) or "Every transcript".
  - One chip per bin with its count; tooltip "Show the transcripts in <bin>" plus ". Drop one here to file it" when writable. Clicking a chip filters the list to that bin.
  - A delete (x) beside each bin chip when writable; tooltip "Delete the bin <name> (its transcripts stay, unbinned)". Result message: "Deleted the bin <name>; its transcripts are unbinned".
  - "New bin" button (writable only): opens a name box ("Bin name", at most 60 characters) with "Make" (key hint Enter) and "Cancel". Enter in the box makes the bin; Esc in the box closes it and returns focus to the paragraphs.
    - Refusals on the page: "type a name for the new bin" (empty), "there is already a bin called <name>".
    - Success: "Made the bin <name>. File transcripts with the bin control on each row, or drag them onto it".
  - When the bin filter names a bin that no longer exists, it resets to All.
- **Filing a row**:
  - **Bin drop-down on each row** (shown when writable and at least one bin exists): "No bin" plus each bin. Choosing files the source there ("Filed <person> in <bin>") or takes it out ("Took <person> out of its bin"). Works by keyboard and touch.
  - **Drag a row onto a bin chip** (rows are draggable only when writable): files it there; dropping on "All bins" takes it out of its bin. The chip under the drag is highlighted.
- **Read-only**: on the page, any change says "the bins cannot be changed in a read-only run without a working copy". The server refuses with 409 "this editor was started read-only with no working copy, so bins cannot be saved: start it with --write, or with a working copy".
- **Server limits and refusals**:
  - name: whitespace collapsed; refused when empty ("a bin needs a name"), holding control characters ("a bin name cannot hold control characters"), or over 60 characters;
  - at most 100 bins per episode (409 "an episode has at most 100 bins: delete one first"), also when filing creates a bin;
  - at most 20,000 filed stems (409 "too many transcripts are filed in bins");
  - at most 500 stems per call (400 "at most 500 at a time"); each stem at most 300 characters; no stems (400 "no transcript named");
  - creating a bin that exists is no change.
- **Any failure** on the page: "the bins did not change: <reason>".

## 4. Intake: dropping media and sending fleet jobs

(source: transcripts/intake.ts, transcripts/fleet.py, transcripts/client.ts, transcripts/server.ts)

- **Dropping files**: media files dragged from the desktop onto the panel highlight it (dashed cyan outline, the drop hint lights up). On drop, the panel switches to the list of transcripts and sends the dropped files' names and sizes (a browser drop carries no paths) to the server.
  - Message while looking: "Looking for <name> under the episode" or "Looking for N files under the episode".
  - With no cut list open: "open a cut list first, then drop the media on its transcripts".
- **What the server does with the names**:
  - Accepts at most 100 names per drop. A name is ignored if empty, over 255 characters, holding a slash or backslash, "." or "..", or control characters.
  - Only media extensions are taken: mp4, mov, mxf, mkv, m4v, avi, mts, m2ts, wav, mp3, m4a, aac, flac, ogg, opus, webm, braw, r3d. Anything else is reported as skipped.
  - Duplicate names (case-insensitive) are taken once; names already on the worklist are not looked for again.
  - Each new name is searched for under the episode folder by name (case-insensitive) and, when a size was given, exact size. The search skips dot folders, `legacy` and `node_modules`, stops at 50,000 entries or 8 folder levels, and takes the first match in name order.
  - A row records: the name, size, where it was found (relative to the episode) or not found, its stem (name without extension), whether it needs a transcript (no `<stem>_words.json` anywhere in the episode), and the jobs sent.
  - The worklist is kept in server memory per episode, at most 200 rows (the oldest drop off). It is lost when the server restarts.
  - Nothing dropped at all: 400 "nothing was dropped".
- **Result message**: "Added to the intake." plus, when some were not found, "One is / N are not in the vault yet: put it/them under the episode folder and drop again."; plus, when some were not media, "<name> is not media, so it was skipped" or "N files that are not media were skipped". Shown as a warning when either applies. Failure: "the intake did not take them: <reason>".
- **The Intake box** (in the list of transcripts, when it has rows):
  - Title "Intake", a **Machine** control, and a **Clear** button (tooltip "Empty the intake (jobs already sent keep running)"). Clear empties the worklist: "Cleared the intake (jobs already sent keep running)"; failure "the intake did not clear: <reason>".
  - **Machine control**: when the fleet's machine list is known, a drop-down "Any free machine" plus each machine ("<machine> (<editor>)"); a machine that is offline or has jobs turned off is listed but disabled with " - offline" / " - jobs are off". When the list is empty or unknown, a text box ("Any free machine": blank for any, a machine name, or editor/machine). The choice is remembered in this browser (`tc-fleet-target` in local storage) and preselected next time.
  - The machine control appears only when jobs can be sent from this run.
  - **Each row**: the file name; where it was found, or "Put it under the episode folder, then drop it again". A row not found shows a "Not in the vault" chip and no job buttons.
  - **Job buttons** for a found row: **Whisper** (only while the clip has no words file), **Proxy 480p**, **Audio**, **Peaks**. Each sends one fleet job of that kind. A sent kind becomes a chip "<Kind> · job <number>". A button shows busy while sending; a second press of the same one is ignored.
  - When jobs cannot be sent, the buttons are disabled with the reason as tooltip, and the reason shows as a line in the box.
- **Why jobs cannot be sent** (reason text):
  - read-only run: "this editor was started read-only (without --write), and a fleet job writes its output into the vault, so none is sent from here";
  - no fleet configured: "no fleet is configured on this server: set CARDS_FLEET_URL, CARDS_FLEET_USER, CARDS_FLEET_PASSWORD and CARDS_FLEET_ROOTS".
- **Sending a job** (server checks, in order):
  - kind not one of whisper, proxy-480p, audio-extract, peaks: 400 "that is not a fleet job";
  - name not on the worklist: 404 "that file is not in the intake: drop it again";
  - not found in the vault: 409 "that file is not in the vault yet: put it under the episode folder and drop it again";
  - read-only: 409 with the read-only reason;
  - no fleet: 409 with the no-fleet reason;
  - a target that is not "machine" or "editor/machine" (letters, digits, spaces, dot, underscore, hyphen; at most 120 characters): 400 "a target is a machine name, or editor/machine";
  - the fleet call failing: 502 with the reason; an answer without a job number: 502 "the fleet answered without a job number".
  - The server does not refuse a Whisper job for a clip that already has words; only the page hides the button.
- **What a job asks the fleet for** (through the old app's fleet client in Python):
  - The file is named to the fleet by shared root name and relative path, never as an absolute path. Refusals: "the fleet cannot name that file (no shared root covers it)", "(it is a whole root)".
  - Whisper: the file, aimed at the chosen machine or any, stating its requirements: whisper capability, that root mounted, and 6 GB of GPU memory.
  - Proxy 480p and Audio: output to `<Episode>/Script Docs/remote_audio/source/` named after the stem; Peaks: output to `<Episode>/Script Docs/remote_audio/`. Refusal when the output folder is not under a shared root: "the fleet cannot name the episode's remote_audio folder (no shared root covers it)"; "no output name" when the stem is empty.
  - The dashboard declining: "the fleet did not take the job (the dashboard is down, or refused it)".
- **Job messages on the page**:
  - accepted and schedulable: "<Kind> for <name> went to the fleet[ on <machine>] (job <n>)";
  - accepted but no machine can take it: "<Kind> for <name> is job <n>, but no machine can take it yet[: <summary>]" (warning; summary at most 400 characters);
  - failure: "the fleet did not take <Kind> for <name>: <reason>".
- **The fleet's machine list**: fetched when the intake has rows and a fleet is configured. The Python side signs in as the configured admin, keeps the session in one worker, caches the list for 30 seconds, and returns at most 200 machines. Any trouble returns an empty list (the page then shows the free-text machine box).
- **Fleet settings**: `CARDS_FLEET_URL`, `CARDS_FLEET_USER`, `CARDS_FLEET_PASSWORD`, `CARDS_FLEET_ROOTS` (environment variables, read once at server start). All four must be set, else there is no fleet. At most 4 fleet clients (distinct settings) are kept in the Python worker.
- **Fleet worker limits**: the fleet module runs pinned to one Python worker, 2 calls at once, 30 s timeout per call.
- **DORMANT**: the fleet module's `status` command (configured or not, root names) is never called by any route.

## 5. Reading a transcript

(source: transcripts/client.ts, transcripts/service.ts, transcripts/bridge.py, transcripts/shared.ts, transcripts/styles.ts)

- **Opening a transcript** (from a row, Shift+T, a double-click, a search result): the panel fetches the transcript and shows it. Opening one clears the find, picks, selection, the transcript playhead and the sentence cursor, and pauses its audio.
  - Failure: the warning line "that transcript did not open: <reason>" (an error, no dismiss button), with a Try again button available through the retry action.
  - Showing a cut whose clip has no transcript in this episode: "<person or clip> has no transcript in this episode".
  - Showing a cut no longer in the cut list: "that cut is no longer in the cut list".
- **Header on a transcript**: the person name in the speaker colour (tooltip: the file name), an "All transcripts" back button (back to the picker), the find box (section 6), the match count, previous/next match buttons, and, when the person has several recordings, a drop-down "Which recording the timings come from" to choose which clip's timings to use. Changing it reloads the transcript for that clip.
- **Which clip's timings are used by default**: the asked-for clip, else the first clip with a words file, else the first with subtitles.
- **Each paragraph** shows:
  - a meta row: `^ref` (or "^-"), the paragraph's time in the clip "m:ss - m:ss", with " (approx)" when it was placed from the subtitle export rather than its own words, or "not timed";
  - chips: "Question" with a lock icon for an interviewer question; "In the cut" / "In the cut ×N" (cuts of this paragraph in the cut list); "Staged" / "Staged ×N" (on the shelf); "This cut" on the paragraph of the cut the panel was opened on;
  - a **Pick** button (becomes "Picked" with a check) for a paragraph with a `^ref`;
  - the English line first, then the original line beneath at equal weight. The original line carries its language for the browser (Mandarin, Russian, Ukrainian, ...). Chinese, Japanese and Korean get slightly more line spacing.
  - Questions are greyed and italic with a neutral left border; other paragraphs have a speaker-colour left border.
  - The paragraph of the shown cut has a highlighted border, and the words of that cut (each word whose midpoint is inside the cut) are underlined in cyan on both lines where the word index has them.
  - A picked paragraph is outlined and tinted cyan.
  - A find hit paragraph (for an id find) is outlined gold; the current one more strongly.
  - The paragraph holding the transcript playhead gets a cyan left border.
- **Which cut counts for "In the cut" / "This cut"**: the paragraph named by the cut's `^ref` when the transcript has it, else the paragraph the cut's span overlaps most (at least 0.35 s, or 30% of the paragraph).
- **Paragraph parsing** (server side, through the old app's Python): paragraphs between blank lines; a YAML header is not a paragraph; the `^` line is the id; any `#` line marks a question (the `#` is removed); the line with the highest share of non-Latin script is the original line (none under 20%). Transcripts in which no Chinese original was found are re-read accepting any non-Latin script (Russian, Ukrainian). The rest is the English, joined.
  - Without Python, the page's server reads the transcript with its own parser (same rules, plus: for Latin-script languages such as Vietnamese, the last line of a block of two or more lines is the original unless it reads as English).
- **Paragraph placement in the clip** (timings): built by the old app's word index from the whisper words; paragraphs the whisper words cannot match are placed through the vault's own `<clip>.srt` (the subtitle file the transcript was written from), only when the clip has both a words file and that `.srt`. Without whisper words, the `.srt` or `.whisper.srt` cues are the timings.
- **Timecode clock**: words files and vault subtitles run on the clip's timecode clock (often 01:00:00:00); it is subtracted so everything shown is source seconds.
- **The document's language** is detected from its original lines (first ~4,000 characters); "en" for an English-only interview.
- **Warning line** under the header (one small line, full text in its tooltip, with a dismiss x; errors have no x):
  - no clip with timings: "<person> has no word timings yet, so passages can be read but not inserted - transcribe that clip first";
  - nothing placed: "none of these paragraphs could be found in the clip's words, so passages can be read but not inserted";
  - timed from subtitles: "timed from the subtitle export, not whisper words - an inserted cut may run a little wide";
  - Python unavailable or failing: "<error> - the transcript can be read but not inserted from" (this answer is not cached, so the next open retries Python).
- **Dismissing a hint**: the x on the warning line or the status line hides it, and the dismissal is remembered in this browser for that message (key `tc.tx.dis.<first 48 characters of the message, simplified>`), so it does not show again. An error is only cleared this once.
- **Status line** at the bottom of the panel: one small line (info, warning in gold, error in red) with a dismiss x. It carries every message in sections 5 to 11.
- **Rendering speed**: only paragraphs whose markup changed are replaced; those in view first, the rest in slices of about 12,000 characters per tick. Scroll position, keyboard focus and a mouse selection survive a redraw.
- **Server caches** for reading: up to 16 documents and 24 clips' word tokens in memory, keyed by the files' size and modification time; the Python side keeps up to 24 parsed transcripts. The alignment of paragraphs to timings is also cached on disk under `TC_MEDIA_CACHE/transcripts` (default the system temp folder's `tc-editor-cache/transcripts`).
- **Simplified/Traditional and pinyin maps** are sent with each document for the find (section 6). Without the server's Chinese conversion or pinyin library, the find is case-folded only (no Chinese folding, no pinyin). Maps are capped at 50,000 entries and only single characters and short ASCII readings (up to 8 letters and a tone digit, at most 8 readings per character) are kept.

## 6. The find box

(source: transcripts/client.ts, transcripts/shared.ts)

- **The box**: "Find: words, or pinyin (chu1, chuqu, 出qu)", in the transcript header, with a count and previous/next buttons (disabled with fewer than 2 hits).
- **Count display**: empty when nothing is typed; "0" with no hits; "17" after typing (no current hit yet); "3 / 17" once Enter has gone to a hit.
- **Query forms**:
  - **Plain text**: case-insensitive, on both lines, Simplified and Traditional characters treated as the same (醫院 finds 医院, 陳 finds 陈). Russian ё is treated as е, and the Ukrainian/typographic apostrophes (’ ʼ ‘ ` ´) as a plain apostrophe.
  - **Quoted** ("..." or with curly quotes, at least 3 characters including the quotes): exact case, no script folding, and whole word wherever the query's edge is a letter or digit that is not a Han character ("I" does not match the i in "it"; Cyrillic counts as letters).
  - **`^id`** (the first non-space character is ^, then letters, digits, _ or -): goes to the paragraph with that id (case-insensitive). Only when no paragraph has the whole id, every paragraph whose id starts with it.
  - **A pasted Obsidian embed** (`![[Name#^id]]` or `[[Name#^id|alias]]`): same as `^id`.
  - **Mixed Han and Latin letters** (老ren, yi院, 出qu, guo王): a pinyin search. Characters match themselves and each letter run must be the sound of the characters in that spot, where a prefix of each reading is enough (dh finds 的話).
  - **Pure pinyin** (letters only, with optional tone digits 1 to 5, spaces or apostrophes; at least 2 letters): each Han character takes a whole syllable, the last may still be being typed (chuq finds 出去). A digit after a syllable is its tone (5 = neutral); without one any tone matches. ü is typed v (lv = 綠). Ordinary text hits are kept as well ("he" finds the English word and 和). Every reading of a character counts (得 = de and dei).
  - Pinyin needs the server's pinyin map; queries longer than 64 characters are never treated as pinyin.
- **Typing** marks the hits (gold tint) and counts them; it moves nothing (no scroll, no playhead, no current hit). Exception: an id find lands on its paragraph as it is typed, scrolling only if the paragraph is not comfortably in view.
- **Enter in the box**: next hit (Shift+Enter: previous; a first Shift+Enter goes to the last). On a desktop the box then lets go of the keyboard so Space plays the hit; on a touch screen the box keeps its keyboard.
- **Going to a hit** (Enter, the buttons, Enter in the paragraphs while the find was last used):
  - the current hit gets a full gold fill;
  - the view scrolls only when the hit is not at least 50 px inside the visible area, and then centres it;
  - the transcript playhead goes to the hit's first timed word (if that line has no timings, the first timed word of the paragraph's other line);
  - the hit is cued, paused: from 0.2 s before its first word to the end of its last word plus 2 s (for an id hit, the first 60 characters of the paragraph);
  - if the transcript was playing, it pauses; the sentence cursor and its selection are dropped.
- **Space after Enter** plays that cued hit. Enter again pauses and cues the next (Enter, Space, Enter, Space).
- **Esc in the box** leaves the box and returns the keyboard to the paragraphs, keeping the text and the marks.
- **Ctrl+F (Cmd+F on macOS)** from anywhere (also from inside another text box), unless a menu or another dialog is open:
  - with a transcript loaded (open or panel hidden): opens the panel if hidden, switches to the transcript, focuses the find box with its text selected;
  - with no transcript loaded but the panel showing the picker: focuses the picker's name filter;
  - with neither: the browser's own find runs.
  - Ctrl+Shift+F is not this panel's (it belongs to search).
- **Speed**: each line is folded once per document (in 3 ms slices starting 200 ms after opening) so each key is a plain substring search.

## 7. Playing the transcript

(source: transcripts/client.ts, transcripts/player.ts)

- **The transcript's own player**: one audio element for every clip, playing `/media/audio?project=<cut list>&clip=<clip>`, from a source second, optionally stopping at another. Only the newest cue ever plays (a cue made before the file loaded is played once it can be).
- **Loudness**: when the editor's preview sound engine is present, the transcript plays through it, at the same per-clip level the lane uses (the lane levels each interview to the cut's speech level and runs it through the master volume and limiter). The level glides as playback moves. Without that engine (or if wiring fails), the bare element plays as recorded.
- **The player row** (header): a Play/Pause button (key hint Space, disabled when the transcript has no timings), and the time m:ss while playing. Its tooltip says what Space will play: "From ^<ref> at m:ss", "The selection, N.N s", "Click a word to put the playhead there", or "No timings: this transcript cannot play". Only an error shows as visible text.
- **What Space (or the Play button) does**, in order:
  1. if the transcript is playing: pause;
  2. if the transcript has no clip or no timings: "this transcript has no timings, so it cannot play";
  3. if a find hit was just cued and the head is still on it and no text is selected: play the cued hit;
  4. if a selection made with the pad's head is live: play it from 0.4 s before to 1 s after;
  5. if the transcript playhead is placed: play on from its word (no end);
  6. if a text selection with timings exists: play it from 0.4 s before to 1 s after;
  7. a text selection with no timings: "that selection has no word timings to play: insert it, or pick the paragraph";
  8. else the first picked paragraph that is timed, from its start to its end;
  9. else the cut the panel was opened on (if it is of this transcript's clips), its in to its out;
  10. else: "click a word to put the transcript playhead there, then press Space".
- **Hold Space** (in the panel, held for 280 ms or more): plays at 2x while held (starting playback if it was stopped). Releasing returns to 1x; if it was stopped before the hold, it pauses where it got to. A tap under 280 ms acts on release as Space above. Losing window focus ends a hold the same way.
- **Space anywhere else while the transcript plays** (not in a text box, button or editable area, no modifiers): pauses the transcript and does not start the lane.
- **One thing plays at a time**: starting the transcript pauses the lane; the lane starting pauses the transcript.
- **Following**: while playing, the transcript playhead follows the spoken word on the line it is on (or the cursor's line, or the original line when it has timings), 20 ms ahead; when it moves to another paragraph, that line is scrolled into view if needed.
- **Errors** (said in the status line and the row, never thrown):
  - "There is no audio for <clip> on this server, so the transcript cannot play it.";
  - "It would not play: <reason>" (a pause before play started is not reported).
- The frame-by-frame loop runs only while playing.

## 8. The transcript playhead (click on a word)

(source: transcripts/client.ts, transcripts/shared.ts)

- **Click on the words** of a paragraph (no modifiers, not the end of a drag selection): puts the transcript playhead on the word under the pointer (or the nearest timed word of that line), drawn as a solid cyan word. The keyboard focus moves to the paragraphs.
  - If the transcript is playing, playback jumps to that word and keeps playing.
  - The click drops the sentence cursor and its selection, a pad selection, and a cued find hit.
  - A line with no timed words: "this line has no word timings: click the other line, or pick the paragraph to play it whole" (or "this transcript has no timings, so it cannot play").
- **Click beside the words** (the paragraph's margin or its meta row) toggles the paragraph's pick (section 10).
- The playhead is a place, not a playback state: it survives pausing.
- The marks (playhead word, cursor sentences, the original words an English selection stands for) are drawn as text highlights that change no markup; on a browser without that support the state still works but is not drawn (the paragraph border cue still shows).

## 9. Keys while the transcript has the keyboard

(source: transcripts/client.ts)

These apply when the keyboard focus is inside the panel, a transcript is open, and no Ctrl/Alt/Meta is held (except where noted). The lane's and the cards' keys do not fire here.

- **Space**: tap or hold, as in section 7.
- **Enter**:
  - if there are find hits and the find (or a step) was the last thing used: next hit; Shift+Enter previous;
  - else if paragraphs are picked or text is selected: insert at the lane head; **Shift+Enter** puts it on the shelf;
  - else if there are hits: next/previous hit.
- **A** or **Up arrow**: previous sentence. **Shift+A** / Shift+Up: shrink the cursor selection by a sentence.
- **S** or **Down arrow**: next sentence. **Shift+S** / Shift+Down: grow the cursor selection by a sentence.
- **Z**: back to one sentence.
- **X**: switch the cursor's language between the original line and the English line, staying on the same paragraph. Says "The cursor is on the <language> line: it inserts word for word." or "The cursor is on the English line: an English sentence inserts its whole paragraph unless it has its own timings."
- **E**: the cursor to the paragraph under the lane head (if the head's cut is a clip of this transcript), else the cut the panel was opened on; the keyboard stays in the panel. Else "the head is not on a cut of this transcript". If that paragraph has no sentences in the cursor's language, it is only scrolled to.
- **C** (not auto-repeat): insert the selection at the lane head.
- **V**: refuses: "This editor has one track, so nothing can be placed on top: C inserts at the head instead (the cuts after it move along)."
- **Q**: back to the cards: focuses the last selected card, else the focusable card, else the first card.
- **R, D, W, B, J, Delete, Backspace**: do nothing in the panel (swallowed so the lane and cards do not act).
- **Alt+Left / Alt+Right**: move the start of a single-paragraph English pick one word earlier/later; **Alt+Shift+Left / Alt+Shift+Right**: move its end (section 12).
- **Esc** (also from anywhere, captured before other handlers, unless a text box, editable area, menu, sheet or other dialog has it; and unless, with the focus outside the panel, a box selection of several cards or an armed edge is active, which the keyboard drops first), in order:
  1. if full height: back to normal height;
  2. if the transcript is playing: pause;
  3. if a pad selection is live: drop it (the head stays);
  4. if the transcript playhead is placed: remove it;
  5. if paragraphs are picked, text is selected or the cursor is on: clear them;
  6. else close the panel (and, if the focus was inside it, focus the cards).
- **Enter or Space on a focused button** in the panel act as that button's click.
- **Typing in a text box** in the panel never reaches the editor's keys.

## 10. Selecting what to insert

(source: transcripts/client.ts, transcripts/shared.ts)

Four ways to select, the newest replacing the others:

- **Whole paragraphs (picks)**:
  - the paragraph's **Pick** button toggles it; **Shift+click** the Pick button picks a range from the last picked paragraph;
  - **Ctrl+click** (Cmd+click) anywhere on a paragraph toggles it; **Shift+click** anywhere on a paragraph picks the range from the last picked one;
  - a click beside the words (not on them) toggles it;
  - picking clears a text selection and the sentence cursor.
- **Mouse text selection** (a drag over the words, possibly across paragraphs and lines):
  - nothing is read until the mouse button comes up;
  - a drag that ends outside the words (over the bar below or above) selects to that edge;
  - it drops the sentence cursor and, unless playing, the transcript playhead; it clears the picks;
  - its span is taken from the word index (the timed words under the selected characters), so an insert takes exactly what the preview played.
- **The sentence cursor** (A/S, Shift+A/S, Z, X, E): the cursor's sentences become the selection, highlighted, scrolled into view when within 40 px of an edge. It replaces a mouse selection, the picks and the transcript playhead.
  - Sentences: ends at 。！？!?…；; or a line break, or a full stop followed by a space or the end (not in 3.5 or a.m.), closing quotes and brackets staying with their sentence. A sentence longer than 64 characters is split again at a comma (，,、) once at least 24 characters have passed.
  - Units are the original line where a paragraph has one (cursor language "original"), else its English; or English first (cursor language "English"). Paragraphs without a `^ref` are skipped.
  - The cursor starts on the sentence holding the transcript playhead's word, else the head's paragraph, else the first paragraph in view.
  - The cursor's language starts on the original line when the word index has timings on it, else English.
  - With nothing to step: "this transcript has no sentences to step through".
- **A pad selection** made by moving the transcript playhead with the controller (section 13).
- **Clear** (button, key hint Esc) drops all of them.

## 11. Inserting into the cut

(source: transcripts/client.ts, transcripts/shared.ts, transcripts/service.ts, transcripts/bridge.py)

- **The action bar** appears at the bottom of the panel when something is picked or selected (never more than 34% of the panel's height). It shows:
  - a summary:
    - text: `Selected: "<first 60 characters>…" · about N.N s`;
    - English selected (section 12): `Selected English: "<…>" · about N.N s`;
    - picks: "1 paragraph picked" / "N paragraphs picked", " · about N.N s" when timed, " · each becomes a cut";
  - a reason it cannot go in the cut, when one applies:
    - "This transcript has no timings, so nothing can be inserted from it.";
    - "A picked paragraph was / N picked paragraphs were not found in the clip's words, so there is no span to cut.";
    - "Interviewer questions never go in the cut: they can go on the shelf.";
  - a note when placed approximately: "Placed by a close match, not word for word: check the edges of the cut.";
  - the buttons:
    - **Insert at the head** (primary, key hint C; "Inserting" while busy). Disabled with no timings, an untimed pick, a question, no cut list open, or an English mapping still pending.
    - **After the selected card**. Also disabled when no card is selected ("select a card first").
    - **Put on the shelf** (key hint Shift Enter). Disabled with no timings, an untimed pick, no cut list, or a pending mapping. Questions are allowed.
  - Each disabled button's tooltip gives the reason (or "open a cut list first").
- **Where an insert lands**:
  - **At the head**: in front of the next cut when the head is in black before it; in a gap, beside the gap at its nearer edge; within one frame (or the minimum cut length, whichever is larger) of a cut's start, before it; within that of its end, after it; inside a cut, that cut is **split at the head first** and the passages go after the first half, in the same op; past the end, at the end.
  - **After the selected card**: after the last selected card.
  - **On the shelf**: in the shelf's default category, each passage after the previous one.
- **House rule 1**: an interviewer question can only go on the shelf. Refusal: "interviewer questions never go in the cut - put them on the shelf instead" (status line and a toast).
- **Nothing picked**: "nothing is picked - select words, or click paragraphs".
- **No cut list**: "open a cut list first".
- **One op per insert**: however many passages, the insert is one edit, so one Ctrl+Z removes it. A run into the cut lands whole and in order.
- **The new cuts**: clip, in and out (rounded to the microsecond), the person (the name this cut list already uses for that clip, else the transcript's person), the colour (the colour most used by this clip's other cuts, else none), the `^ref`, the words under the span (whitespace collapsed), no highlights, and marked as a question when it is one.
- **After an insert into the cut**: the new cuts are selected, the lane head goes to the first one's start, and the panel does not then "follow" that selection. The picks and selection are cleared.
- **Success message**: "1 cut / N cuts at the head / after the selected card / on the shelf - Ctrl+Z takes it/them out." plus, when it applies, " The selection could not be matched word for word, so the whole paragraph went in." and " The English was not lined up word for word, so the whole original sentence went in." (then shown as a warning).
- **Failure**: "the passage was not inserted: <reason>"; "the editor refused that insert" when the edit was refused.
- **Placing a passage (locate)**: for each passage the page asks the server where it sits in its clip, sending the text, the paragraph refs, and the span the page already timed from the word index.
  - With a span: the span, plus 12 frames of handle on each side, the start held off the end of the previous spoken word and the end off the start of the next one; if that leaves nothing, one frame. Confidence 1.
  - With text only: the text is matched inside the highlighted paragraphs first (within 8 tokens' slack), then anywhere in the clip, then by matching the English against each paragraph's English and taking that paragraph's original (only for texts of 8 or more letters), at a 0.75 match threshold. A text match more than 2 s outside the highlighted paragraphs' own span is replaced by those paragraphs' span (whole paragraph).
  - Text that does not match but whose paragraphs are placed: those paragraphs whole, confidence capped at 0.5, marked "whole paragraph" (CR-204).
  - The end is clamped to the clip's duration when known.
  - The words of the new cut are the words under the final span; its ref is the single paragraph, else the paragraph it overlaps most.
  - Picked paragraphs are each placed by their own timing (whole paragraph plus handles).
  - Refusals: "nothing is selected in the transcript" (400); "<person> has no word timings yet, so there is no span to cut - transcribe that clip first" (409); "couldn't find that text in the clip's transcript -- try selecting the Mandarin line, or a longer stretch" (409); "the selection is empty"; "that transcript is not in this episode" (404).
  - Server limits: text cut to 20,000 characters, at most 500 refs, body at most 256 KB.
- **Inserting with the server unreachable** (offline, no answer, or a gateway error 502 to 504 while it restarts):
  - a selection or pick that has its own timing is placed by the page itself, with the same rules as the server's span placement (12 frames of handle, held off neighbouring speech, words under the span), using the clip's timed words fetched when the transcript opened (waited for up to 5 s if still arriving) or the lane's.
  - When the browser reports it is offline, the page places it itself without trying the server first.
  - Text with no timing of its own still needs the server: "<error>; this selection has no timing of its own, so it needs the server to place it". If the words never reached the page: "<error>; and the word timings of this clip did not reach the page before it went - reopen the transcript once it is back".
  - Messages for an unreachable server: "the server did not answer - check the connection and try again"; a refusal: the server's own error text or "the server refused it (<status>)"; "the server sent something that is not an answer".
- **The selected English travels with the card**: when the insert came from an English selection that mapped word for word, the page announces (`tc:put-english` window event) the new cuts with that English, for the translate feature to keep as each cut's English.

## 12. Selecting English: the original words it stands for (transcript panel)

(source: transcripts/client.ts, align/paragraph.ts, align/shared.ts)

- **What it does**: in a paragraph with both an original line and an English line (and a transcript not in English), selecting part of the **English** line stands for the original words that English translates. From then on it acts exactly as if those original words had been selected: the same span, the same cut, the same card text, the same playback.
- **The original words** are highlighted in place on the original line (cyan tint and underline).
- **The action bar** then shows `Selected English: "<…>"` and a mapping row:
  - while the alignment is coming: a spinner, "Lining the English up with the original…" and **Cancel** (Cancel drops the selection: "the English was not lined up with the original, so nothing is selected");
  - when mapped: an arrow and the original words (first 90 characters), and, if approximate, an **Approximate** label with the reason;
  - **Start** earlier/later and **End** earlier/later buttons (key hints Alt ←, Alt →, Alt Shift ←, Alt Shift →): move each end of the mapped original words one word at a time, only for a selection inside one paragraph. An end that cannot move (paragraph edge) stays put;
  - **Copy original**: copies the original words to the clipboard ("the original words are copied"; "the clipboard would not take it").
  - While a mapping is pending, Insert and the shelf are disabled.
- **The mapping** (when a checked alignment exists for that paragraph): the English selection, trimmed to whole word characters, touches some phrases of the alignment; the original words are the smallest contiguous run covering every word those phrases map to (word order differs, so the run may include a word no selected phrase names; never scattered, never half a word).
- **Fallback (approximate)** when there is no valid alignment (Claude unavailable, the day's budget spent, an answer that failed its checks, "no alignment yet"): the whole original sentence(s) the selection is in, when the English and the original have the same number of sentences (more than one); else the whole original paragraph. Always labelled Approximate with the reason, e.g. "the alignment did not check out (<why>): the whole original sentence instead".
- **Asking**: a selection with no alignment yet asks for that one paragraph now (the "now" priority); a newer selection withdraws the older ask. A paragraph whose last answer was "Claude never answered" is asked again once per page session.
- **Multiple paragraphs**: an English selection across several paragraphs maps each paragraph's part; original selections in the same selection are used as they are; an English-only paragraph uses its own timed words.
- **The card's English**: the English that plays with the mapped words is the selection itself; after nudging an end, it is the alignment's phrases that lie wholly inside the new run.
- **Search results hand over**: a search result's English selection can be opened in the transcript ("Open in the transcript", section 16): the panel opens the clip's transcript at the paragraph and selects the same English there (finding a partial English inside the paragraph's English if needed). "that paragraph has no English line here" or "<clip> has no transcript in this episode" when it cannot.

## 13. The game controller in the transcript

(source: transcripts/client.ts; the button mapping itself lives in client/input, outside this part)

The panel offers these actions to the controller. Each returns failure when it cannot act, and the controller then rumbles. Button names below are only those the panel's own messages name.

- **Right stick moves the transcript playhead** through the words, as the lane's jog moves the lane head through time:
  - a word costs the time to the next word's start, at least 0.06 s and at most 0.5 s of stick (a silence is stepped over, a run of words with one start time is not crossed in one frame);
  - the first push puts the playhead on the sentence cursor's first word, else the first timed word in view, and moves nothing ("the playhead is on this word - the right stick moves it, LT + the right stick selects, A plays from it"); a playhead scrolled out of view is placed again the same way;
  - it pauses the transcript; the view follows, keeping the word at least min(48 px, a quarter of the view) from the edges;
  - stopping at the first or last word stops dead (the controller rumbles);
  - a plain move drops any selection.
  - No timed words: "this transcript has no word timings on these lines, so there is no playhead to move" (or "this transcript has no timings, so there is no playhead to move").
- **LT + right stick selects** what the playhead crosses, from where it stood when selecting began; letting go keeps the selection; holding LT again continues from its moving end; English selected this way stands for its original words (section 12). It is drawn like the cursor's selection and played whole by Space/A.
- **B (cancel)**, in order: a multi-sentence cursor goes back to one sentence ("back to one sentence"); a pad selection is dropped and the head stays ("the selection is off - the playhead stays where it is, B again takes it off"); a cursor, selection or picks are cleared ("the selection is off"); the transcript playhead is removed ("the transcript head is off").
- **Insert** (X, as the panel's own messages name it): at the lane head; **LT + X**: after the selected card (the panel's code takes "after" or "head"; which button sends which is decided outside this part).
- **Sentence step** (D-pad per the messages): previous/next sentence, starting on the sentence the head is in.
- **Paragraph step**: next paragraph's first sentence; back goes to the top of the current paragraph first, then the previous paragraph.
- **Edge**: move the start or the end of the cursor selection by a sentence ("LB / RB grow it").
- **Home (Y)**: right after stepping through find hits, selects the current hit's sentence ("the match’s sentence is selected - X inserts it at the head, LB / RB grow it"); a hit on the other language's line selects its paragraph's first sentence ("the match is on the other language’s line: its paragraph’s first sentence is selected (LT + L3 switches the cursor’s language)"). Otherwise, the paragraph under the lane head ("the block under the playhead - move with the D-pad, then LT + Y selects the run"). With no hit: "there is no match to take yet - type in the find box, then ◀ ▶".
- **Range (LT + Y)**: the first press sets the current sentence as the anchor ("this sentence is the anchor - move along, then LT + Y selects up to the cursor"); the next selects from the anchor to the cursor ("N sentences selected - X inserts them, B collapses").
- **Head on sentence**: puts the transcript playhead on the cursor sentence's first word ("the transcript head is on that sentence - A plays on from it"; "that line has no word timing, so the head cannot be placed on it").
- **Language (LT + L3)**: switches the cursor's language, as X on the keyboard.
- **Whole paragraph**: the cursor covers its whole paragraph. **Play paragraph**: selects the whole paragraph and plays it from 0.4 s before to 1 s after ("that paragraph has no word timings to play").
- **Find step (◀ ▶)**: previous/next hit ("there is nothing to find yet - Menu puts the caret in the find box").
- **Play (A) down/up**: as Space down/up (tap plays or pauses, hold skims at 2x); a cancelled release ends the hold.
- **Shuttle (RT)**: plays at the given rate while held (starting playback if stopped); releasing returns to 1x and pauses if it was stopped.
- **Scroll**: scrolls the paragraphs by a number of pixels.
- **Focus find (Menu)**: focuses the find box with its text selected; if the box is empty and the search sheet had a word, that word is typed into it first.
- **Leave find**: leaves the find box, keyboard back to the paragraphs.
- **List of transcripts**: **browse** (switch to the list and focus the open transcript's row or the first), **list step** (move up/down the rows; "the list is empty: nothing matches its filters"), **list open** (open the focused row), **list back** (back to the open transcript).
- **Show cut**: shows a cut in its transcript and focuses the paragraphs.

## 14. Pasting Obsidian block embeds

(source: transcripts/client.ts, transcripts/service.ts, transcripts/shared.ts)

- **Paste anywhere on the page** (not into a text box or editable area) of text holding `![[Note#^id]]` or `[[Note#^id]]` (with or without an `|alias`): each link becomes a card. The editor's own copied cuts (its clipboard type) and pastes without such links are left alone.
  - The note name is the last part of the link's path, without `.md`; it is matched case-insensitively to a transcript file name in this episode.
- **Where the cards go**: on the shelf when the shelf ("Staged") view is open; otherwise after the selected card if it is in the cut list, else at the end of the cut list. One op, one undo.
- **Each link** is placed by its paragraph's own timing when the word index has it, else by matching its text.
- **Per-link refusals** (the other links still land):
  - "no transcript named "<note>" under this episode";
  - "that transcript would not open: <reason>";
  - "block ^<id> is not in "<note>" - copy the embed again from the paragraph you want";
  - ""<note>" has no word timings yet, so there is no span to cut - transcribe that clip first";
  - a placing error from section 11.
  - A question link becomes a question cut; if the destination is the cut, house rule 1 refuses the whole paste.
- **Messages** (a toast in the cards panel's toast area, 5 s; also the status line when the panel is open):
  - "1 card / N cards from the paste, on the shelf / in the cut - Ctrl+Z takes it/them out", plus ". N refused: <first reason>" when some failed;
  - none placed: the first refusal, else "that paste has no Obsidian block link in it", else "nothing in that paste could be turned into a card";
  - no cut list: "open a cut list first";
  - failure: "that paste did not become a card: <reason>".
- **Limits**: the paste is read up to 1,000,000 characters; at most 200 links; the request body at most 1 MB. A second paste while one is being handled is ignored.

## 15. Keeping each cut's words in step with its span (the words service)

(source: transcripts/derive.ts, transcripts/shared.ts, transcripts/service.ts, transcripts/client.ts)

- **What it does**: whenever any edit changes a cut's clip, in point or out point (in the cut list or on the shelf), or adds a cut, the server re-slices that cut's words from its clip's timed words and re-finds its `^ref`, and writes the change back as an edit, so every client and the file agree. It is not in anybody's undo history: undoing a trim moves the span back and the words follow again.
- **Which words**: a word counts when its midpoint is inside the cut. A cut too short to hold any midpoint takes whatever words it touches. Pause markers "(...)" are removed and whitespace collapsed. If no words lie there, the cut keeps what it has.
- **Whose spelling**: the words are the **transcript's** characters, not whisper's: each placed paragraph is lined up with the tokens said within 2 s of its span (letters compared, Simplified and Traditional alike), and each token takes the paragraph's characters aligned to it, keeping the token's own times. Whisper's spelling stays where there is no paragraph, the paragraph was not placed, the paragraph is too long to line up (over 4,000,000 comparison cells), or fewer than 40% of its letters match. Whisper filler inside a paragraph that the transcript does not have is dropped; pure punctuation tokens inside a placed stretch are dropped. Without Python, whisper's own words are used.
- **The `^ref`**: a plain `^ref` is re-derived as the paragraph the span overlaps most (at least 0.35 s or 30% of the paragraph). A hand-written `Note#^ref` is never replaced.
- **Highlights**: highlights still present in the new words are kept (re-fitted to the surviving words); the server re-fits the cut's current highlights when it applies the change, so one made meanwhile is not wiped.
- **Freshness**: one refresh at a time per cut list; a fix computed for a span that has since changed is dropped (the next change recomputes it). Changes go out in batches of up to 100 cuts per edit.
- **Bounds**: at most 16 cut lists watched at once (the least recently touched is dropped when a 17th is asked for); a watcher untouched for 20 minutes closes (checked every minute). A watcher that is refused or disconnected reconnects with backoff, never giving up.
- **Starting it**: POST `/api/transcripts/watch` (the page sends it on opening a cut list and every 5 minutes).
- **Under the dashboard**: when `TC_PROXY_SECRET` is set, the service's own connection and edits go under `TC_MOUNT_BASE` (default `/cards`) carrying the proxy secret and the user "words-service".
- **Instant text on the page**: when the platform mounts this feature, the lane's live text for a trimmed cut is cut immediately from the timed words the page already holds, with the same rule, before the server's change arrives.
- **Refresh all**: POST `/api/transcripts/refresh` re-derives every cut now and returns how many changed. **UNREACHABLE from the page**: no control in this part calls it.

## 16. The transcript feature's server routes

(source: transcripts/server.ts, transcripts/service.ts)

All routes are under `/api` (covered by the server's origin check). Every route that takes `key` (the cut list's path) refuses a malformed key with 400 "bad-key". Errors from bins, intake and transcripts carry their own status and code.

- `GET /api/transcripts/sources?key=` : the episode name and its transcript sources (section 2).
- `GET /api/transcripts/doc?key=&source=[&clip=]` : one transcript: paragraphs with timings, the word index, whether it is timed, a warning, its language, and the Chinese fold and pinyin maps. 400 "which transcript?" without `source`; 404 "that transcript is not in this episode"; 404 "<person> has no transcript yet"; 404 "that transcript file could not be read".
- `POST /api/transcripts/locate?key=` body `{source, clip?, text?, refs?, span?}` : where a passage cuts (section 11). 400 "the body is not a selection".
- `POST /api/transcripts/embed?key=` body `{text}` : pasted embeds as passages or per-link refusals (section 14).
- `GET /api/transcripts/words?key=&clip=&in=&out=` : the words under a span (text, and whether the first/last word is partly outside: a "bite" of at least 0.15 s and 35% of the word). 400 "clip, in and out are needed". No words: an empty answer. Not called by the page in this part.
- `POST /api/transcripts/watch?key=` : start or keep alive the words service; answers `{watching: true}`.
- `POST /api/transcripts/refresh?key=` : re-derive every cut now; `{changed: N}`; 409 "the cut list is not open on this server" when the watcher cannot connect within 10 s.
- `GET /api/transcripts/bins?key=` / `POST /api/transcripts/bins?key=` body `{op:'new',name}` | `{op:'delete',name}` | `{op:'file',stems,bin|null}` : section 3. 400 "new, delete or file?" for any other op. Body at most 256 KB.
- `GET /api/transcripts/intake?key=` / `POST /api/transcripts/intake?key=` body `{names:[{name,size}]}` / `POST /api/transcripts/intake/send?key=` body `{name, kind, target?}` / `POST /api/transcripts/intake/clear?key=` : section 4. Send body at most 16 KB.
- `GET /api/transcripts/fleet/machines[?force=1]` : the fleet's machines (`[]` with no fleet or no answer); `force=1` bypasses the 30 s cache (the page never sends it).
- **Python**: the transcript logic runs pinned to one worker of the shared Python pool, one call at a time, 120 s timeout (including queue wait). The interpreter can be overridden with `TC_PYTHON`. With no Python, documents are read without timings and nothing can be inserted.
- **The vault is never written** by these routes (bins and fleet outputs follow the rules in sections 3 and 4).

## 17. English-to-original alignment: what an alignment is and how it is checked

(source: align/shared.ts, align/paragraph.ts)

- **A unit** is one stretch of speech with its English: a transcript paragraph (its original line and its English line, id = its `^ref`), or a cut (its timed spoken words and the English the lane shows, id = the cut id).
- **Its words**: the timed words (the word index's rows for a paragraph's original line; the clip's tokens for a cut) where they exist, and a plain split elsewhere: each Han, hiragana or katakana character is a word; a run of letters, digits and marks is a word (an apostrophe or hyphen inside one keeps it whole: "don't", "когда-нибудь").
- **An alignment** is Claude's phrase map over a unit: the English is split into short phrases, each with the range of original words it translates.
- **The key** an alignment is stored under is a hash of the original text and its English, whitespace aside. Editing either makes a new key, so an old alignment is never applied to changed words. A stored alignment whose text differs from the unit is treated as absent.
- **Unit limits** (refused otherwise, with the reason): original at most 4,000 characters, English at most 6,000, at most 1,500 words, words sorted, non-overlapping and inside the text; "nothing to align" when either side is blank.
- **The prompt** (model `claude-haiku-5-5`, strict JSON out): each item carries its key as id, the language name (Taiwanese Mandarin, Mandarin Chinese, Russian, Ukrainian, Russian or Ukrainian, Japanese, Korean; else "the language it is spoken in"), the numbered original words, and the English.
- **Checks before an answer is kept** (else it is stored as a failure with the reason):
  - every phrase has a word range "w" (a single number is accepted as a range of one); the range is inside the original and first <= last;
  - every phrase is found in the English (whitespace and case aside), in English order and without overlapping another; a phrase listed out of order is placed where it is in the English if that overlaps nothing;
  - every English word is inside some phrase ("<word> is not mapped to any original word");
  - with 4 or more original words, the phrases together reach at least half of them;
  - at most 400 phrases; no empty phrase.
  - The original side may cross (word order differs between languages); it is never refused for that.
- **Reading an answer**: answers are matched to units by id; a batch of one whose single answer has no id is still accepted; a unit missing from the answer is "missing" (asked again once, alone).

## 18. Alignment storage, queue and budget (the server)

(source: align/server.ts)

- **Where alignments are stored**: one JSON file per clip, `<cut list folder>/.tcards/@align/<clip, made file-safe, up to 80 characters>.<8-character hash>.json`, under the working copy when the editor runs with one, else under the vault when the run may write, else (read-only vault and no working copy) under `TC_ALIGN_DATA` (default `<state folder>/data/...`). Never inside a read-only vault.
  - A run that does not write the vault still reads alignments the pipeline stored in the vault's own `.tcards/@align/`; its own records win.
  - Writes are one at a time per file; before writing, the file on disk is read and any newer record another server stored is merged in (per key, the newer wins), then written atomically. A file that will not parse is treated as empty.
  - At most 5,000 records per clip file (the oldest go); at most 32 clip files cached in memory.
- **A cut's alignment without Claude**: a cut whose English is the transcript's own (whole or trimmed) is aligned by projecting the stored paragraph alignments it lies in (its spoken letters matched to the paragraphs' letters; it may start or end inside one and span several; the paragraphs must cover nine tenths of the cut; every kept phrase must appear word for word, in order, in the cut's English; and the cut's English may hold no more than 2 letters more of text outside the phrases than its paragraphs do). A phrase the cut divides is cut at the word by the stored word links (section 23) when there are any, else kept or dropped by its majority of words, or cut in proportion when it has 4 or more English words. Not stored; a miss is remembered for 20 s; up to 4,000 remembered.
- **The queue**: three priorities: `now` (a selection waiting, a spinner on screen), `visible` (paragraphs on screen), `background`.
  - At most 2 Claude calls at once (`TC_ALIGN_CONCURRENCY`, 1 to 8), up to 4 units per call (`TC_ALIGN_BATCH` or the settings route, 1 to 16), and a batch stays within one cut list, one priority, and about 12,000 characters.
  - Most urgent first, oldest first within a priority.
  - At most 2,000 queued; when full, the lowest-priority newest job nobody waits on is dropped; a `now` that cannot get in is answered "too much work is queued already; try again in a moment".
  - Each call times out after 180 s.
- **The day's budget**: at most `TC_ALIGN_DAILY_CALLS` Claude calls per calendar day (UTC date; default 300; 0 to 100,000; changeable in settings). One call counts per batch. When spent, the queue stands still with "today's alignment budget is spent (N Claude calls)", and every waiting selection is answered at once as failed (the page falls back to approximate). The count resets the next day.
- **Claude unavailable**: the queue stands still ("Claude is not available on this server (<why>)"), waiting selections are answered failed, and the server looks again every 60 s. A runner budget answer pauses with "the server's Claude budget is spent for now".
- **Failures**:
  - an answer that fails its checks is final for that text (stored, never asked again until the text changes);
  - Claude not answering (timeout, a CLI error) is stored as a retryable failure ("Claude did not answer (<reason>)") and asked again after an hour, or at once when a selection waits on it;
  - a unit left out of a batch is asked once more alone, then stored as retryable "Claude left it out of the answer".
- **Cancel by scope**: a transcript that closes cancels what it queued (unless someone is waiting on a unit); a running call that only it wanted is stopped. A `now` whose page gives up (Cancel, a new selection, the request closing) is withdrawn: if nobody else waits, the job goes back to on-screen priority, or out if it was only that wish.
- **Restart**: the queue (including calls in flight), the day, the day's count, the daily limit and the batch size are saved to `queue.json` in `TC_ALIGN_STATE` (default `<system temp>/tc-editor-align`), debounced 200 ms, and resumed at start (at most 2,000 jobs; a resumed `now` becomes on-screen work). On shutdown the state is written before calls are stopped, so they run again after a restart; waiting selections are answered "the server is stopping".
- **Counters** since the server started: alignments made, alignments failed.

## 19. Alignment routes

(source: align/server.ts)

All under `/api`; bodies are JSON objects up to 16 MB; a malformed cut-list key is 400 "bad-key"; at most 500 units per request (413); a unit that fails its checks is 400 "bad-unit" with the reason; text fields over their limits are 413 "too-large" (clip 400, id 200, original 20,000, English 24,000 characters).

- `POST /api/align/lookup` `{key, units}` : for each unit, by key: `ready` (with the alignment), `failed` (why, and code `retry` or `invalid`), `pending` (queued or running), or `none`. Never starts Claude.
- `POST /api/align/queue` `{key, scope, prio, units}` : queues the units not already stored, at `visible` (when asked) or `background`; answers counts `{queued, have, refused}`.
- `POST /api/align/now` `{key, scope?, unit}` : aligns one unit now and waits for the answer. Answers at once when stored, when a final failure is stored, when the budget is spent (code `budget`), when Claude is unavailable (`no-cli`), when the server is stopping (`closed`), or when the queue is full (`busy`). Closing the request withdraws the wish (`cancelled`).
- `POST /api/align/cancel` `{key, scope}` : drops that scope's queued work and stops calls only it wanted; `{cancelled: N}`.
- `GET /api/align/status` : queued, running, used today, daily limit, batch size, why it is paused, made, failed.
- `POST /api/align/settings` `{dailyCalls?, batch?}` : changes the daily limit (0 to 100,000) and batch (1 to 16), clears a "budget spent" pause if there is room again, saves, and answers the status.
- **Who may call**: anyone the server's origin check admits; there is no further permission check on these routes.

## 20. Alignment on the page (cache, lane, cards, search results, settings)

(source: align/client.ts)

- **The page's one alignment cache**: answers at once from memory (up to 4,000 answers) and asks the server behind it; lookups are batched 30 ms after the first ask, in chunks of 400; while anything is pending, it polls the status and looks up the pending units every 2.5 s. A lookup never takes back a ready or failed answer.
  - If the alignment service does not answer (feature off, server down), the units are marked failed "the alignment service did not answer" quietly.
  - When an alignment becomes ready, the page announces `tc:alignment-landed` (so a cut's English can appear without a reload).
- **The transcript panel** queues every paragraph that has both lines in the background when a transcript opens (scope `tx:<source>|<clip>`), and the paragraphs within 200 px of the view (up to 40) as `visible`, re-asked at most every 400 ms as you scroll or redraw. Closing or switching transcript cancels that scope. An English transcript queues nothing.
- **The lane's English picks**: the lane asks this feature to map an English pick on a clip to its spoken words (`ready`, `approx` with reason, `pending`, or `none` with "open a cut list first", "this clip has no word timings yet", the unit's problem, or "the selection holds no words"). Selecting a clip on the lane prefetches its alignment quietly (`visible`, scope `lane:<cut list>`, at most 500 remembered). The lane may also ask for "the English of words w0..w1", answered from stored alignments only, never by a new Claude call. (The lane's own controls are outside this part.)
- **Cuts near the lane head**: 1.5 s after the head moves to another cut, the cut list changes, or the lane's words or text change, the cuts within 12 of the cut under the head that show an exact English (not a dimmed machine draft) and have known timed words are queued in the background (each once; the memory resets after 4,000).
- **Selecting English on a card or a search result** (a selection inside one English line of a card, a shelf item, or a search result's English line):
  - the matching original words are highlighted in the card's or result's own original line;
  - a floating toolbar ("English selection: the original words") appears over the selection, kept inside the window, on the side away from the original line:
    - while mapping: spinner, "Lining the English up with the original…", **Cancel**;
    - when it cannot map: the reason;
    - when mapped: arrow, the original words, and **Approximate** (with the reason as tooltip) when it is;
    - **Start** earlier/later and **End** earlier/later buttons (one word each);
    - for a card (in the cut or on the shelf): **Play**, **Delete words** (tooltip "Cut exactly these original words out; the rest closes up"), **Highlight**, **Split here**, **Copy original**;
      - Play: plays those words on the lane (seeks the lane head and stops when it passes their end); a card not in the cut: "Only a card in the cut can play from here.";
      - Delete words, Highlight and Split here are handed to the lane's own word tools; their message is shown; after a successful Delete or Split the toolbar closes;
    - for a search result: **Open in the transcript** (tooltip "Insert, put on the shelf or play these words from the transcript"; "The transcript panel is not available here." when it cannot) and **Copy original**;
    - **Close** (x).
  - Esc closes the toolbar; clicking elsewhere (losing the selection) closes it unless the pointer is over it; pressing its buttons does not lose the selection.
  - Copy: "The original words are copied." / "The clipboard would not take it."
  - One ask at a time per surface: a newer selection withdraws the older `now` ask.
  - A card that is removed from the cut list closes its toolbar.
- **Settings row** "English to original alignment" (in the shared settings):
  - a status line: "Not available on this server." / "Waiting for the server…" / the pause reason / "Lining up N paragraph(s) in the background." / "N lined up since the server started, F could not be.";
  - **Claude calls a day** number box (0 to 100,000, step 10): saved to the server on change;
  - "N used today, B paragraphs a call".

## 21. Cut English from alignments (helpers other features call)

(source: align/shared.ts)

These functions live in this part but are called by the translate feature (outside this part). They decide what a cut's English becomes after a trim or split.

- **A cut inside one paragraph**: its English is every phrase of the paragraph alignment whose original words are all in the cut; a phrase the cut divides is cut at the word by word links when stored, else dropped when the cut has under half of its words, else cut in proportion (phrases of under 4 English words are kept whole); approximate when an edge falls inside a phrase or a cut word has no phrase. A trailing dash is removed.
- **Several stored alignments hold the cut**: the first stands, unless another leaves fewer of the cut's words without English while adding no more than about 14 English characters per recovered word (plus 10).
- **A cut across paragraphs**: the cut's letters are matched against the paragraphs (its head may be the tail of one, its end the head of another); up to max(4 letters, 15% of the cut) of unmatched scattered letters are tolerated; a stretch of 6 or more unmatched letters is untranscribed speech (an interviewer's question) and makes the English approximate, as long as the paragraphs still hold at least 30% of the cut's letters (and at least 8). A small part (under 4 words or 15% of the cut) without English is left out; any larger part without English fails the whole cut.
- **The same words in another script** (aligned on Traditional whisper words, now reading Simplified): same letter count and at least two fifths equal place for place: the alignment's whole English is the cut's.
- **Transcript paragraphs first**: the paragraphs' own alignments are tried before alignments stored for earlier cuts of the same words.
- **Overrun / underrun checks**: how many phrases of 12+ letters the cut has under half of but whose English is in the cut's English (overrun), and how many phrases of 4+ letters the cut covers whole but whose English is missing (underrun). Alignments made from the very English being checked are excluded.

## 22. Reading aids: the ten aids and their settings

(source: aids/shared.ts, aids/cache.ts, aids/client.ts)

- **What they are**: marks that help an editor cut speech in a language they do not read. Each aid is a separate toggle. They show on transcript paragraphs, on cards (including shelf items) and in the lane (the lane drawing itself is outside this part; this part supplies the lane's marks).
- **The ten aids** (number, settings label, settings hint):
  1. **Playhead word in both languages** ("The word being said, lit in the original and in its English"): the English that renders the word being spoken, tinted cyan, on the transcript paragraph holding the transcript playhead, on the playing card, and in the lane.
  2. **Sentence ends and numbers** ("Each sentence numbered, the same number on its English"): a small gold number at the start of each sentence of the original line and of its English (only when the original has more than one sentence); the lines get extra line spacing to hold them.
  3. **Verbs** ("Verbs underlined in both languages"): a solid gold underline. An auxiliary, a copula, or a verb inside a compound noun is not marked.
  4. **Safe cut points** ("Green: a cut here leaves a whole thought. Red: it strands a clause"): ticks between words of the original line (section 24). Also enables the nudge (Alt+S, and the lane's edge snap).
  5. **Not, if and but** ("Negation, conditions and contrast words flagged"): negation in red with a solid underline; conditions and contrast in red with a dashed underline.
  6. **Join check** ("After a splice or trim, Claude reads the joined original again"): section 25.
  7. **Word-by-word gloss** ("A literal English word under each original word"): a "Word by word" line under the original (transcript and cards; the lane may use the same literal line through its own drawing).
  8. **Names, places, numbers, dates** ("Marked so they can be heard and checked"): names and places dotted cyan underline; numbers and dates dashed cyan underline.
  9. **Fillers** ("Hesitations and filler words, marked as trimmable"): greyed with a faint strike-through.
  10. **Romanisation under Cyrillic** ("Latin letters under Russian and Ukrainian words"): a "Romanised" line under the original (transcript and cards).
- **Modes per aid**: **Off** (never), **Not read** (on for languages not in "Languages I read"; the default for nine aids), **All** (on for every language; the default for aid 1).
- **Languages I read**: toggles for English, Chinese, Russian and Ukrainian; default English and Chinese. Matching is on the base language (zh-Hant counts as Chinese; a mixed Russian/Ukrainian code counts as Russian).
- **So by default**: a Russian or Ukrainian clip shows every aid; a Mandarin or English clip shows only aid 1.
- **Where settings are kept**: this browser's local storage, key `tc.aids` (per device). Anything unreadable falls back to the defaults; at most 12 languages kept. If storage is denied, settings last for the session only.
- **Settings panel** "Language aids" (shared settings, order 870):
  - a status line: "The aids service is not on this server." / "Asking the server…" / "Asking the server about language analysis…" / "Language analysis: Stanza <version> (<languages>)." / "Language analysis is not available: <why>. Only the word lists and the romanisation show." (warning colour);
  - "Languages I read" toggle buttons (tooltip "I read <language>: its aids are off unless an aid is set to All");
  - one row per aid: number, label, hint, and Off / Not read / All buttons (tooltips "Off everywhere", "On for the languages I do not read", "On for every language");
  - "Claude calls a day for glosses and join checks" number box (0 to 100,000, step 10), saved to the server on change;
  - "N used today".
- **No mark changes size or weight**: every mark is an underline or a tint, so nothing reflows. Each kind has its own line style besides its colour. Marks never cover the line's own markup or a selection (they are painted as text highlights).
- **Which surfaces are skipped**: an English interview, a paragraph or card with no original line, or a line whose language cannot be told.

## 23. How the aids are worked out

(source: aids/shared.ts, aids/lexicon.ts, aids/safecut.ts, aids/translit.ts, aids/words.ts, aids/model.ts)

- **Language analysis**: each text (an original line or an English line) is analysed by Stanza on the server (section 26): its words with offsets, sentences, parts of speech, the dependency parse, lemmas, negation and conditional mood, and named entities. Languages with a pipeline: Russian, Ukrainian, Chinese (the Traditional model, for every Chinese code), English. A Cyrillic text with no language code is Ukrainian if it has і, є, ї or ґ, else Russian; a Han text with no code is Chinese. Other languages get no parsed aids.
  - Texts over 6,000 characters, blank texts, or languages without a pipeline are not analysed.
- **Verbs**: parse VERB, not inside a compound.
- **Numbers**: parse NUM; entities of number types (cardinal, quantity, money, percent, ordinal).
- **Names and places**: entities (places: LOC, GPE, FAC; names: person, organisation and other kinds). Where the language's model gives no entities (Chinese), runs of proper nouns are names.
- **Dates**: date/time entities, plus per-language date words as whole words (months and weekdays with their case endings, yesterday/today/tomorrow; for Chinese, a number followed by 年 月 日 號 點 分 秒 週 星期 and 昨天/今天/明天/去年/今年/明年/前年/後天) that are not adjectives, verbs, pronouns or similar.
- **Negation, condition, contrast, filler word lists** per language (Russian, Ukrainian, Chinese in both scripts, English), including two-word entries ("как бы", "you know", "тем не менее"). Chinese entries are found inside a word, longest first (沒有 before 沒). A list word counts:
  - always when the list marks it as sure (for example не, если, однако, 如果, 但是, not, if, um);
  - negation: also when the parse says negative polarity, an adverbial modifier, or a particle;
  - condition: also a subordinating marker, conditional mood, or a subordinating conjunction;
  - contrast: also a coordinating conjunction or marker, or a sentence-opening adverb;
  - filler: also a discourse word, an interjection, a sentence-opening adverb (not a particle), a hesitation, or a sentence opener followed directly by punctuation ("Ну, ...", "Well, ...").
  - Words the parse marks negative or conditional are marked even if not listed.
- **Hesitations** (always fillers): Russian э/эм/мм/хм runs, Ukrainian е/ем/мм/хм runs, Chinese 嗯呃欸誒诶唔, English uh/um/er/erm/hmm/mm/ah.
- **Without a parse (degraded)**: only sure list words, hesitation fillers, and numbers written in digits; sentences by punctuation; no verbs, names, cut ticks or parsed marks.
- **Sentences**: the parse's sentences, else punctuation (。！？!?…;； or a line break, a full stop followed by a space or the end and not by a digit, closing quotes and guillemets kept with their sentence).
- **Matching sentence numbers**: when the original and its English have the same number of sentences, they are numbered in order; otherwise each English sentence takes the number of the original sentence most of its phrases point into (through the phrase alignment), and an English sentence that points nowhere gets no number.
- **Romanisation** (no Claude, deterministic): Russian by BGN/PCGN (е is "ye" at a word start and after a vowel; ё "yo"; х "kh"; щ "shch"; ъ and ь dropped); Ukrainian by the national system (є ї й ю я are "ye yi y yu ya" at a word start, "ie i i iu ia" inside; зг is "zgh"; apostrophe and ь dropped). The system is the clip's language; a word with a letter only the other language writes uses the other system; letters of other Cyrillic alphabets use a plain fallback, so no Cyrillic letter ever appears in the Latin line. Capitalisation follows the original (all-caps words stay all caps). Latin words, digits and punctuation pass through.
- **Word links and the gloss** (aids 1 and 7): inside each phrase of the phrase alignment, Claude links each English word to the original word(s) it renders, gives every original word a literal 1 to 3 word gloss, and lists runs of original words that form one word, name or fixed expression ("units": a unit is linked and glossed as a whole, its gloss on its first word). Checked before kept:
  - every link stays inside its phrase (a stray number is dropped, not the answer);
  - at least half the phrases get a link;
  - a gloss is at most 40 characters, one line;
  - units must be in range, 2 to 12 words, and not overlap (odd ones dropped).
  - Model `claude-haiku-5-5`. Keyed by the phrase alignment's key, so it goes stale with it.
- **The gloss line**: each original word's gloss in the original's order, "·" for a word with none, words inside a unit skipped, two spaces between.
- **The English of a spoken word** (aid 1): its word links; with none, its whole phrase, but only when that phrase is 4 English words or fewer (a longer one lights nothing). With word links, a spoken word no link names (a filler) lights nothing. Links stored for a different word list are not used. A spoken token is matched to the alignment's words by its characters, not its number.
- **A cut's word links without Claude**: projected from its paragraphs' stored word links (when every paragraph it lies in has them), through the same projection as section 18. Glosses from several paragraphs on one word are joined with " / ".
- **Memo**: one surface may ask for the same stretch every frame; answers are memoised by the caches' versions (up to 1,500 stretches).

## 24. Safe cut points and the nudge (aid 4)

(source: aids/safecut.ts, aids/client.ts)

- **A cut point** is the gap between two timed words of the original. Each is classified from the dependency parse:
  - **a cut may end here** when nothing on the left waits for a head on the right, nothing the left needs went right (an object, a "that" clause, the rest of a name), and the left has a verb or a sentence root;
  - **a cut may start here** when only a new clause hangs off the left and the right has its own predicate;
  - a sentence end is safe both ways; so is a gap with only fillers (and punctuation) before it in its sentence, or only fillers after it;
  - a gap that splits one of the parser's words is unsafe both ways ("This splits the word "<w>"").
- **What is drawn**: **green** tick when both ways are safe; **red** tick only where a cut is tempting (a pause of 0.35 s or more, or punctuation in the gap) but would strand a clause; nothing for ordinary gaps inside a clause. A green tick drawn hollow means safe for the words but with less than 0.12 s of silence (the cut will clip). Each tick's reason ("A sentence ends here", "A whole thought ends here", "Cutting here strands a clause: "<w>" is left waiting for "<h>"", "There is no verb yet", "What follows has no verb of its own", "<h> loses its negation <w>", ...) is computed.
- **No parse, no ticks**.
- **Where a cut goes in a gap**: an out point a little after the left word (half the pause, at most 0.12 s); an in point a little before the right word (half the pause, at most 0.08 s).
- **Context**: a cut's edges are judged with up to 40 words (and 20 s) of the clip either side, analysed as one text.
- **The nudge for a dragged edge** (the lane asks this; the drag itself is outside this part): the safe gap nearest the edge within 2.5 s whose side fits the edge (an out edge needs "may end", an in edge "may start"), a gap with a breath preferred by 0.15 s over a tight one.
- **Alt+S** (shortcut sheet: "Move the armed edge, or the picked words, to the nearest safe cut"):
  - with words picked on the lane: moves both ends of the pick to safe boundaries inside its cut, each by the fewest words (up to 12; ties outward). Messages: "The pick now starts and ends where a cut leaves a whole thought." / "The pick already starts and ends at safe cuts.";
  - else with an armed edge: moves it to the nearest safe cut within 6 s (one undo step). Messages: "The <in/out> point moved to the nearest safe cut. Ctrl+Z puts it back." / "No safer cut point near this edge (or its words are still being read)." (also when the nearest is under 0.02 s away);
  - neither: "Arm an edge (click near a cut’s end) or pick words first.";
  - shown as a toast.
  - Alt+S on an armed edge does not check whether aid 4 is on; the pick and drag nudges do (they do nothing when it is off).

## 25. The join check (aid 6)

(source: aids/join.ts, aids/client.ts, aids/styles.ts)

- **A join** is where two consecutive cuts in the cut list meet and the speech should run on: the same clip (not simply continuing within 0.04 s with no gap), or the same speaker. Two speakers meeting is not checked. A gap row between them still counts (its length is recorded). A heading row ends the run. Cuts whose timed words are not known yet are skipped until they arrive.
- **What is compared**: the last words of the first piece (at most 30, from its last sentence start when that leaves at least 3) and the first words of the second (at most 30, up to its first sentence end); for the same clip, the words the cut dropped between them (at most 60, only when the second piece is later in the clip); the English of each cut when shown. Without timed words, the last/first 160 characters of each cut's original text.
- **The quick local check** (at once, free):
  - **meaning**: the dropped words hold a negation: "The cut drops "<word>" (a negation) from between the two pieces: the joined sentence may say the opposite.";
  - **grammar**: the first piece ends (not at a sentence end) on a condition or contrast word: "The first piece ends on "<word>", which waits for a clause that is not there.";
  - **grammar**: the parse says the first piece ends mid-clause or the second starts mid-clause: "The first piece ends mid-clause: ..." / "The second piece starts mid-clause: ..." (or "A side of the join strands a clause.").
  - Nothing found is not "ok"; only Claude says that.
- **Claude's check** (background, budgeted, model `claude-haiku-4-5-20251001`): the joined original is translated afresh and given a verdict: **ok**, **meaning** (changed meaning: a negation, condition or contrast lost, a reversed claim, the wrong subject) or **grammar** (a hanging clause, a missing verb or object, disagreement across the join), with a one-sentence note. Refused when the verdict is not one of the three, there is no translation, or it is over 2,000 characters; the note is cut to 300 characters.
- **When Claude is asked**: only for joins that an edit made or moved within the last 15 s (and only when aid 6 is on for that language). Opening a cut list only looks up existing checks. The pass runs 0.9 s after a change settles and gives the screen back every 3 ms.
- **Keyed by the joined text**: moving the join makes a new key; the old answer stops applying. A check never blocks an edit.
- **Switching cut list** cancels the previous list's queued checks.
- **On a card** (the second card of a join): a button above the card:
  - "Checking the join" (hollow dot), "Join reads well" (green), "Join: meaning changed" (red), "Join: grammar break" (gold); plus "quick check" when the answer is the local one;
  - accessible label "Join check with the card before: <label>" ("the join reads well", "meaning changed: <note>", "grammar break: <note>", "checking the joined words");
  - clicking it shows/hides a box with the note, the joined original, and "Now reads: <fresh translation>" (or "Claude is reading the joined words again."). Pressing it never selects or drags the card.
- **In the lane**: a dot on the seam with the same states and an open box ("Now reads: ..."); a local answer's dot has a dashed ring (the lane's drawing is outside this part; this part supplies the mark).
- **Pending** shows only after Claude was asked for this join (or the server reports it pending).

## 26. The aids server: queues, budget, storage and routes

(source: aids/server.ts, aids/bridge.py)

- **Language analysis (Stanza)**:
  - Runs in the shared Python pool, pinned to one worker so the models stay loaded, label "language analysis", 180 s timeout, 2 calls at once.
  - Stanza is never downloaded by the server. Models are looked for in `TC_STANZA_DIR`, else `%LOCALAPPDATA%\tc-editor\stanza_resources` (Windows, if it exists), else `~/stanza_resources`. Stanza itself may be in the user site-packages (or `TC_STANZA_SITE`), added to the end of Python's search path the first time it is needed.
  - A language is usable when its tokenize, pos, lemma and depparse models are present (mwt and ner used when present).
  - At most `TC_STANZA_MAX` pipelines loaded (default 3, least recently used dropped); torch uses `TC_STANZA_THREADS` threads (default 2); one analysis at a time; at most 64 texts per call, each at most 6,000 characters; a cancelled call stops between texts.
  - While any Python call for the aids runs, the server pings the workers every 300 ms (on Windows, loading torch otherwise stalls until the next request line arrives).
  - Stanza status is cached 60 s.
  - **Not installed**: every request answers `no-stanza` at once with the reason ("Stanza is not installed for this Python (py -3.12 -m pip install --user stanza): ..."), and nothing is queued (degraded mode). **No model for a language**: `no-model` ("no <lang> language model is installed"), final for those texts, remembered in memory only (installing the model fixes it after a restart).
  - Queue: batches of up to 8 texts and 16,000 characters, one language per batch, one batch at a time; resumable from `analysis-queue.json`.
  - Results are cached on disk by a hash of the language and the exact text in `TC_AIDS_STATE/analysis/<2 hash characters>/<key>.json` (default state folder `<system temp>/tc-editor-aids`), shared by every cut list, and up to 3,000 in memory.
- **Word links** queue: batches of `TC_AIDS_BATCH` (default 4, 1 to 16) alignments up to 12,000 characters, 2 calls at once; resumable from `words-queue.json`.
- **Join checks** queue: batches of `TC_AIDS_BATCH` (default 6) joins up to 10,000 characters, 1 call at a time; resumable from `joins-queue.json`.
- **One shared daily budget** for word links and join checks: `TC_AIDS_DAILY_CALLS` (default 200, 0 to 100,000; a setting), stored in `budget.json` in the state folder. When spent, those queues stand still and say so.
- **Claude unavailable**: requests that would queue Claude work answer failed at once ("Claude is not available on this server (<why>)"); queued work holds. A runner budget refusal holds without stopping for good.
- **Failures**: a check-failing answer is final for its key; "Claude did not answer" is retryable after an hour; an answer missing from a batch is handled by the shared queue.
- **Where word links and join checks are stored**: `<cut list folder>/.tcards/@aids/words.json` and `joins.json` under the working copy, or the vault when the run may write, else under `TC_AIDS_DATA` (default `<state folder>/data/...`). Never in a read-only vault. A run that does not write the vault still reads word links the pipeline stored in the vault's `@aids/words.json` (read-only, never written back).
  - Each file: at most 5,000 records (oldest dropped); writes debounced 150 ms; before writing, the file is re-read and newer records another writer stored are merged in per key; a read checks at most once a second whether someone else changed the file and takes their records in.
- **Routes** (all under `/api`, bodies up to 16 MB, at most 400 items per request (413 "at most 400 <what> at once"); a malformed cut-list key is 400 "bad-key"):
  - `GET /api/aids/status` : Stanza availability, version, models, why; each queue's status; used today; daily limit.
  - `POST /api/aids/analysis` `{items:[{lang,text}], prio?, scope?, queue?}` : each text's analysis by key (`ready` / `failed` / `pending` / `none`); queues missing ones unless `queue` is false. 400 "bad-text" with the reason for an unusable text.
  - `POST /api/aids/words` `{key, als:[alignment], prio?, scope?, queue?}` : each alignment's word links (stored, else projected from paragraphs, else queued unless `queue` is false). 400 "bad-alignment" ("not an alignment", "a phrase is out of bounds", or the unit's problem).
  - `POST /api/aids/joins` `{key, joins:[join], check?, scope?}` : each join's stored check; with `check: true`, queues Claude for those without one (`visible`). 400 "bad-join" ("a join does not read": both sides required, side text at most 2,000 characters, dropped and English at most 4,000, both cut ids required).
  - `POST /api/aids/cancel` `{key, scope}` : drops that scope's queued word links, joins and analyses; `{cancelled: N}`.
  - `POST /api/aids/settings` `{dailyCalls?}` : sets the shared daily budget; answers the status.
  - `prio` is `visible` unless `background` is given.
- **Who may call**: anyone the server's origin check admits; no further permission check.

## 27. The aids on the page: cache, painter, lane provider, notice

(source: aids/cache.ts, aids/dom.ts, aids/client.ts, aids/model.ts, aids/styles.ts)

- **The page's one aids cache**: analyses, word links and join checks, up to 4,000 of each; asks batched 40 ms after the first, in chunks of 200; every request times out after 15 s; while anything is pending it polls the status and the pending items every 1.5 s. A status poll redraws nothing unless the status changed.
  - If the aids service does not answer: analyses are marked "the language analysis service did not answer", word links "the aids service did not answer" (quietly; the surfaces degrade).
- **Painting transcript paragraphs and cards**: marks are text highlights over the surfaces' own text (no element added to the line, a mouse selection untouched); ticks and sentence numbers in a transparent overlay that never takes the pointer; the gloss and romanisation as separate non-selectable lines right after the original line, labelled "Romanised" and "Word by word".
  - Only paragraphs and cards on screen (or within 200 px) are painted; they are repainted when the surface redraws them, when they resize, or when anything the aids depend on changes, just after a frame.
  - On a card, the English used is the one English line actually shown; the card's spoken words are matched to the card's text (needing at least 60% of them found) to time the words.
  - Aid 1 on a card: while the lane plays inside that card, the English of the word under the lane head is lit; on a transcript paragraph, the English of the word under the transcript playhead (original line only), following playback frame by frame.
- **The lane provider** (what the lane asks this part for): marks per drawn line (spans by kind, ticks, sentence ends with numbers), the English to light for the spoken word, the literal gloss line and each word's place in it, the join mark between two cuts, the nearest safe time for a dragged edge, and the safe word boundaries for a pick. Memoised (800 lane lines, 2,000 literal lines, 8,000 contexts).
- **Degraded-mode notice**: one small line above the transcript panel's status line, shown when the server reports Stanza unavailable, a transcript paragraph with an original line is on screen, and any aid is on for its language: "Language aids are limited: the server has no language analysis (Stanza is not installed), so only the word lists and the romanisation show." It has a dismiss x; dismissing is remembered in this browser (`tc.aids.notice.dismissed`) for good.
- **When Claude is unavailable**: no gloss, word links or Claude join checks; the quick local join check still shows.
- **Accessibility**: the tick overlay is hidden from assistive technology; the join button has a spoken label; colours are never the only signal; touch targets are 44 px on coarse pointers; in forced-colours mode the ticks keep their colours.

## 28. Platform and environment differences

(source: all files in this part)

- **Ctrl+F**: Ctrl on Windows/Linux, Cmd (Meta) also accepted on macOS. Ctrl+click (Cmd+click) picks paragraphs.
- **Stanza models folder** default: `%LOCALAPPDATA%\tc-editor\stanza_resources` only when `LOCALAPPDATA` is set and the folder exists (Windows); otherwise `~/stanza_resources`.
- **The 300 ms ping** while a Stanza call runs exists because of a Windows pipe quirk but runs on every OS.
- **State folders** default to the system temp folder (`tc-editor-cache`, `tc-editor-align`, `tc-editor-aids`) on every OS.
- **Phone width (700 px or less)**: the transcript panel is full screen; the drop hint is hidden; the action bar's buttons stack; key hints on its buttons are hidden.
- **Touch (coarse pointer)**: 44 px controls; Enter in the find box keeps the on-screen keyboard instead of leaving the box.

## 29. Environment variables and settings in this part

(source: transcripts/*, align/server.ts, aids/server.ts, aids/bridge.py)

- `CARDS_FLEET_URL`, `CARDS_FLEET_USER`, `CARDS_FLEET_PASSWORD`, `CARDS_FLEET_ROOTS`: the fleet for intake jobs; all four or none.
- `TC_PYTHON`: the Python interpreter for the shared pool (per the transcripts README; the pool itself is outside this part).
- `TC_MEDIA_CACHE`: parent folder of the transcript alignment cache (`<it>/transcripts`).
- `TC_PROXY_SECRET`, `TC_MOUNT_BASE` (default `/cards`): the words service's own requests when the editor runs under the dashboard.
- `TC_ALIGN_STATE` (queue.json), `TC_ALIGN_DATA` (alignments when only a read-only vault exists), `TC_ALIGN_DAILY_CALLS` (300), `TC_ALIGN_BATCH` (4), `TC_ALIGN_CONCURRENCY` (2).
- `TC_AIDS_STATE` (analyses, queues, budget), `TC_AIDS_DATA`, `TC_AIDS_DAILY_CALLS` (200), `TC_AIDS_BATCH` (4 word links / 6 joins).
- `TC_STANZA_DIR`, `TC_STANZA_SITE`, `TC_STANZA_MAX` (3), `TC_STANZA_THREADS` (2).
- Command-line `--write` (outside this part) decides whether bins, alignments and aids are written into the vault; without it and with no working copy, bins are read-only and fleet jobs are refused.
- Browser storage: `tc.tx.dis.*` (dismissed transcript hints), `tc-fleet-target` (intake machine), `tc.aids` (aid settings), `tc.aids.notice.dismissed`.

## Looks redundant or overlapping

- Four ways to select a passage in the transcript (Pick buttons and clicks, mouse drag, the keyboard sentence cursor, the controller's head-moving selection), plus a separate word playhead, each with its own clearing rules and an Esc order to untangle them.
- The controller interface duplicates nearly every keyboard action of the panel (sentence step, extend, language switch, find step, play hold, insert), plus extra controller-only ones (paragraph step, anchor/range, whole paragraph, play paragraph, shuttle).
- Passage placement is implemented twice: in Python on the server (`_handles`) and again in TypeScript for offline use (`locateOffline`), with the same 12-frame handle rule.
- Paragraph parsing exists three times: the old app's Python reader, a second Python reader for non-CJK originals, and a TypeScript reader used when Python is missing.
- A cut's words after a trim are computed twice: by the server's words service and instantly on the page (when the platform mounts the feature).
- Sentence splitting is implemented at least three times with slightly different rules (the transcript cursor's `sentences`, the alignment's `sentencesOf`, Stanza's sentences).
- Find has two code paths meant to give identical answers (`findSpans` and `FindIndex`).
- "Character range to DOM Range" and "line text" helpers are written separately in the transcript panel, the alignment bar and the aids painter.
- Two separate Claude budgets and two settings rows ("English to original alignment", 300 a day; "Language aids", 200 a day), and two queue implementations (alignment's own queue; the aids' use of the platform work queue) with the same priorities, batching, cancel-by-scope and resume.
- Two sidecar-merge implementations (alignment clip files and the aids `Sidecar` class) doing the same read-merge-write.
- The English-selection toolbar on cards offers Delete words / Highlight / Split / Play, which duplicate the lane's own word-pick tools (it hands them to the lane).
- The "Approximate" fallback and nudge controls appear twice (transcript action bar and floating toolbar), built separately.
- Several ways to get a cut's English from alignments (single paragraph, several stored alignments, across paragraphs, other script, projection) live here though only the translate feature uses them.
- The intake's fleet job sending overlaps the CC Sync dashboard's own job submission (it signs into the same dashboard as an admin).
- Bins (a file shared with the old app) overlap the picker's other filters as a way to narrow the list.

## Claims the code does not back

- `derive.ts` comments mention "the panel's 'Refresh all words'" and the panel showing "N cuts' words refreshed": the panel has no such control or display; `/api/transcripts/refresh` is never called from this part.
- The aids server's route comment lists `now?` in the `/api/aids/words` body: the route ignores it.
- The alignment README says a staged card's English selection gets only "the highlight and Copy original": the floating toolbar shows Play, Delete words, Highlight and Split here for shelf cards too (Play then refuses with "Only a card in the cut can play from here."; the other three are passed to the lane).
- The intake comments say Whisper is offered "only while it has no words": only the page hides the button; the server sends a Whisper job for a clip that has words if asked.
- The panel's header comment says that while the panel is open, "selecting a card follows it": a selection made in the lane (a press within 1.5 s, or the focus in the lane) does not follow; only a double-click there does.
- The transcripts README says Esc drops "its playhead, then what is picked or selected": the code drops a controller selection before the playhead, and a full-height panel's Esc only restores the height.
- The aids README says each aid defaults to "on for a language he does not read": aid 1 (playhead word in both languages) defaults to on for every language.
- The aids README describes Alt+S as part of aid 4: Alt+S on an armed edge acts even when aid 4 is turned off (only the pick and drag nudges check it).
- The fleet module's docstring lists a `status` command as part of the bridge: no route or caller uses it.
- The alignment README describes the alignment `batch` as "a setting": it can be changed through the settings route, but no settings control offers it (only the daily calls box).

## Could not determine

- Which controller buttons call which panel actions (the panel only names A, B, X, Y, LT, LB, RB, L3, Menu, the D-pad and ◀ ▶ in its messages); the mapping lives in `client/input`, outside this part.
- Whether the platform actually mounts this part's `feature` exports (the transcripts README says the generator lists `feature: null` for every folder). If it does not: 2 and Shift+T are still answered by the panel's own listener, but the instant lane text after a trim (section 15) and the `align`/`aids` features' lane hooks, settings rows, Alt+S and painting would be dormant.
- Who calls `GET /api/transcripts/words` (nothing in this part does).
- How the lane draws the aids' marks, join dots, the safe-cut guide, the English pick and its "Safe" action, and whether holding Alt turns the edge snap off (all in lane code outside this part).
- The shared Python pool's own behaviour (`TC_PYTHON`, restarts, the "no Python" sentence) and the Claude runner's provider selection.
- The fleet client's behaviour inside the old app (`fleet_jobs.FleetJobs`): sign-in, what "schedulable" means, and its 30 s machine cache are as its callers describe, not read here.
- Whether the old app's `text.py` placement (word index, `build_en_index`, `match_selection`) behaves as the bridge's comments describe; only the bridge's calls into it were read.
- Whether the server enforces any user permission beyond the origin check on these routes (none is applied in this part).
