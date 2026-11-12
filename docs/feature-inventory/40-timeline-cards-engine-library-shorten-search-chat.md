# Timeline Cards, the engine: the media library, shortening, search, chat edits, translation and the rest

Terms used throughout this section:

- **Episode root**: the folder for one episode in the vault, for example `X:\Vault\2026\FF5\Animals`. Everything per episode hangs off it: `Interviewees\<person>\` (interview transcripts), `Clips\` (montage source transcripts) and `Script Docs\` (caches, cut lists, notes).
- **Cut list**: a `.cut.md` file under `<root>\Script Docs\Cuts\`, the editor's ordered list of cards, section headings and a "shelf" of set-aside cards.
- **Card**: one span of one interview clip, with its spoken words.
- **The engine**: the Python half that the editor's Node server hands work to. "The page" means the browser client of the editor.
- **Claude door**: the one way every Claude feature reaches a model. Either the `claude` command-line program run as a child process ("the CLI door"), or a "runner" object handed in by a host such as the CC Sync dashboard ("the runner door").
- **Retained conversation** (session): a Claude conversation that is opened once and then resumed turn by turn, so the large text it was opened with (a "corpus") stays in the provider's prompt cache between questions.

## Which Claude models the editor can choose, and what they cost
(source: models.py)

- Three model choices are offered, each by a short name ("slug"):
  - `sonnet`: model `claude-sonnet-5`, shown as "Sonnet 5", note "fastest, $2/$10 per Mtok".
  - `opus`: model `claude-opus-5-5`, shown as "Opus 5.5", note "stronger, $4/$20 per Mtok".
  - `fable`: model `claude-fable-5-1`, shown as "Fable 5.1", note "most capable, $10/$50 per Mtok".
- Default per feature: transcript search defaults to `sonnet`; the edit chat defaults to `fable`.
- The picker list given to the page is the three rows (slug, model id, label, note) plus which one is the default for that feature.
- **Automatic move to newer models.** When the host hands in a model-listing function (the CC Sync dashboard does, from the Anthropic Models API), each slug resolves to the newest model id of its family that the host may call, matching exactly `claude-<sonnet|opus|fable>-<major>[-<minor>]` (one or two digits each, nothing after). Dated snapshots and suffixed variants never count. A family never resolves to anything older than its table row.
  - A newer model is labelled "<Family> <major>.<minor>" (or "<Family> <major>") and its note loses the price: just "fastest", "stronger" or "most capable", because the listing publishes no prices.
  - The listing is refreshed in the background at most every 6 hours; a failed listing is retried after 10 minutes. A failed listing keeps whatever the last good one said. Until a listing has answered, or on a host with no listing (the standalone server), the table is used.
  - The listing never runs on the caller's thread, so a page request never waits for it.
- **What a request may name**: a slug, a table model id, or any id of a family (older or newer). Anything else (empty, misspelt) silently falls back to the feature's default. Nothing is ever refused for a bad model name.
- **A conversation belongs to its model**: the default model's conversations keep their plain key; a non-default model adds `.m-<slug>` to the conversation's key and sidecar file name. Switching the picker therefore opens a separate conversation (and re-reads the corpus at that model's price) rather than continuing the one on screen. A family moving to a newer model keeps the same key, so an open conversation continues under the new model.

## How the engine runs Claude (the two doors)
(source: claude.py)

- **CLI door** (used by the standalone PC server and the standalone NAS container):
  - The program is found from environment variable `CLAUDE_BIN` first. If `CLAUDE_BIN` is set but names neither a file nor something on PATH, the error is "CLAUDE_BIN=<value> is not an executable file and is not on PATH".
  - Otherwise `claude` on PATH. If not found: "claude CLI not found on PATH (set CLAUDE_BIN). In the NAS container it is installed at /usr/local/bin/claude -- an image built before 2026-08-29 does not have it".
  - A `.cmd` or `.bat` program is run through `cmd /c` (Windows npm shims).
  - Whether Claude is available is checked once per process and cached; the answer (`ok` and a `why` sentence) is published in the page state so the translate, semantic search and summary buttons can be dimmed with the reason.
- **Runner door** (used when the CC Sync dashboard mounts the editor): no child process is started and the CLI is never looked for. Availability is the runner's own `ok`/`why`, plus the provider name the host reports (empty until the first call has resolved one).
  - If the runner's status check throws: "the AI provider could not be asked (<type>: <message>)". If it returns something that is not a status: "the AI provider answered <type>, not a status". A status failure dims a button and never fails a page poll.
  - If a run throws: the failure reads "the AI provider failed (<type>: <message>)". If it returns a non-result: "the AI provider answered <type>, not a result". A refusal with no reason: "the AI provider refused, and said why in no words at all".
  - The name of the provider that answered is remembered and shown as the provider.
- **Selected cards are offered to the runner**: when the editor has cards selected, the selection is passed to a runner that accepts it; for any other runner (and the CLI) it is dropped silently. The prompt always carries the selection as text anyway.
- **Retained conversations**:
  - Turn 0 opens the conversation under an id the engine chose (`--session-id <id>` on the CLI), every later turn resumes it (`--resume <id>`).
  - After each successful turn the turn count goes up and is saved immediately, so a page reload or server restart resumes rather than re-sending the corpus.
  - If the provider does not know the id ("No conversation found with session ID" or "is already in use" in the CLI's output, or the runner saying `session_lost`), the answer is "session lost" with NO retry; each feature decides to re-open, re-sending its corpus once, and says so on its status line.
  - Conversations live in the provider's store, which is per machine: one opened on the PC cannot be resumed in the NAS container, and a rebuilt container loses them. The CLI keeps them keyed by its working folder, which is always the MulticamPipeline folder.

## The conversation sidecar files
(source: claude_session.py)

- For each cut list `<name>.cut.md`, the id of its retained conversation is kept in `<name>.claude-session.json` beside it (for a plain `.md`, the `.md` is stripped instead).
- It records: the conversation id, when it was created, completed turns, a hash of the text that opened it (so a changed corpus can be detected), and which door answered last (`cli` or `runner`).
- A missing, half-written or hand-edited sidecar means "no conversation yet" and the next turn opens a new one. It never raises.
- Written atomically (temporary file then rename) after every turn. If the vault is offline the write is skipped silently and the conversation simply is not remembered.
- Deleting the sidecar is the supported "start over". A reset in place gives a new id, zero turns and no corpus hash.
- A conversation with no cut list (no `.cut.md` open) is kept in memory only.
- A cut list restored from its history keeps talking to the same conversation (the sidecar is not versioned).

## Where the last-picked episode is remembered, and which episodes are offered
(source: roots.py)

- The episode root the page last picked is saved to `cards_ui.json`, in the engine's data folder when one is given (the containers), otherwise beside the program. It holds a comment saying it is safe to delete, and the root path.
- On start, the saved root is used only if that folder still exists; otherwise the start falls back to `--root` or the built-in default `X:\Vault\2026\FF5\Animals`.
- Saving is best effort: a read-only folder does not stop the switch.
- A folder counts as an episode if it has an `Interviewees` folder or a `Clips` folder (or both).
- The episode menu offers: every episode folder under the current episode's show, plus every episode of every other show in the same vault year (`<vault>\<year>\<show>\<episode>`), plus the current folder even if it has neither subfolder. Offline shares and permission errors are skipped. Sorted by show then episode name, case-insensitively. Each entry shows the episode name and the show name.

## Finding ffmpeg and ffprobe, and reading what a media file holds
(source: media.py)

- ffmpeg is found on PATH, else at `~\tools\ffmpeg\bin\ffmpeg.exe`, else `C:\ffmpeg\bin\ffmpeg.exe`. None found means the features that need it are unavailable.
- ffprobe is found on PATH, else beside the ffmpeg that was found.
- Reading a file's first audio stream gives its codec and the audio stream's own duration (not the container's). Reading the first video stream gives codec, width, height and frame rate (average rate, else nominal rate, fractions resolved). Each probe has a 120 second limit; a missing ffprobe or a failed probe answers "nothing".
- On Windows every child process is started with no console window; on Linux and macOS no such flag is passed.

## Resolve's keyboard layout for the lane, and the keystroke helper
(source: keys.py, config.py)

- The engine reads the first preset in Resolve's `keyboard.preset.xml` (through the separate `resolve-left-hand-keys` tool) and gives the page, for each of the commands below, the list of single keystrokes bound to it, written as `Ctrl+Alt+Shift+<key>` in that order:
  - play toggle, play forward, stop, play reverse, step forward, step reverse, next clip, previous clip, timeline start, timeline end, first frame, last frame, nudge forward, nudge reverse, ripple trim start to playhead, ripple trim end to playhead, split clip, select clip at playhead, move clips up, move clips down, delete, backspace, mark in, mark out, reset in, reset out, add marker, clear marker, undo, select all clips after, trim mode, and "Extend Edit".
  - One command may have several keys (for example X and "." both nudge forward, by a second and by a frame), and the page gets all of them.
  - Two-keystroke chords are skipped. Keys with the Windows/Cmd modifier are skipped. Letters and digits are lower-cased. Named keys are translated: Left, Right, Up, Down, Home, End, Del (as Delete), Backspace, Return/Enter (as Return), Space. Any other named key (F-keys, Tab, Page Up) is left to the page and the browser.
  - With no preset to read (the NAS half has no Resolve) the answer is empty and the page keeps its own keys; a line "[keys] no Resolve keyboard preset (...) -- the lane keeps the page's own keys" is printed.
- The default keystrokes the engine sends when the preset cannot be read are Resolve's own defaults: deselect all Ctrl+Shift+A, select at playhead Shift+V, ripple cut Ctrl+Shift+X, paste insert Ctrl+Shift+V, match frame F, insert F9, split Ctrl+\, ripple trim start/end to playhead Shift+[ and Shift+], undo Ctrl+Z, redo Ctrl+Shift+Z, timeline focus Ctrl+4.
- Keystrokes reach Resolve through one long-running AutoHotkey v2 script (`ripple_keys.ahk`), fed one batch per line. AutoHotkey is looked for at environment variable `AUTOHOTKEY`, then `%LOCALAPPDATA%\Programs\AutoHotkey\v2\AutoHotkey64.exe`, then `C:\Program Files\AutoHotkey\v2\AutoHotkey64.exe`, then `AutoHotkey64` or `AutoHotkey` on PATH. Windows only in practice.
  - Each batch waits up to 15 seconds for an answer. Errors: "keystrokes to Resolve timed out", "the key helper died -- retry", "could not bring Resolve to the front to send keys (<reply>)". A dead or timed-out helper is restarted on the next batch.
- Marker add and delete calls are counted as Resolve undo steps (a fixed setting, `True`), so an undo walk counts them; one "bank" of a removed piece onto the offcuts timeline (timeline name `offcuts`) is counted as 3 undo steps.

## Switching the episode root
(source: library_engine.py, roots.py)

- A request to switch the episode root is refused with "no folder given" when empty, and "no such folder: <path>" when the folder does not exist. Surrounding quotes and spaces are stripped and the path is made absolute.
- The choice is saved (see `cards_ui.json` above) and the request does not answer until the switch has actually happened, waiting up to 8 seconds for the engine's own loop to do it. If nothing has driven the loop in the last 2 seconds (a server with no loop of its own), the switch is made at once on the request itself; if the 8 seconds run out it is made on the request too.
- The answer says whether the switch landed, and carries the warning "<root> has neither an Interviewees nor a Clips folder -- cards will have no transcripts" when that is true. The switch still happens.
- Switching re-reads, for the new episode: the notes file, the bins file, the per-timeline drafts, the placement store, the interviewee colour map, both translation caches; and forgets every transcript, clip name, clip media path, corpus registration and card cache of the old episode. The media pool is re-scanned against the new root.

## Where each card's words come from
(source: library_engine.py)

- For each clip, the words are taken, in this order of preference:
  1. A whisper word-timing file for the clip (`<stem>_words.json`, see the text and corpus sections), including per-word speaker labels when it has them. Shown on the card as source "whisper".
  2. Otherwise the transcription Resolve stored in the project library database (PostgreSQL). Shown as source "resolve". Synthetic montage clip ids (`clip:<stem>`) are never asked of the database.
  3. (In the cut-list engine covered by another section, a vault `.srt` export, shown as "srt".)
- A clip with no words is asked again at most every 60 seconds, so a timeline read before Resolve saved the transcription recovers on its own.
- If the database connection itself fails, it is closed, the error "project database: <message>" is published in the page state, and it is reopened later. If only one clip's query fails, that clip is treated as having no words and the connection stays open.
- **Linking the clip to its bilingual transcript document**:
  - A montage source's transcript is looked for in the episode's `Clips` folder by the clip's media file name; otherwise the clip's interviewee is guessed from the clip name against the interviewee names (colour map or `Interviewees` folders) and the transcript is looked for in `Interviewees\<person>`.
  - Each transcript file in that folder is scored by how many of its paragraphs can be found in the clip's words; a file needs at least 3 matching paragraphs to be accepted (prevents one interviewee's different shoot days being mixed up).
  - A `Clips` folder holding exactly one transcript is accepted without the 3-paragraph vote.
  - If the clip's own `.srt` export is available and covers the same stretch of time (overlap of more than half of the shorter range), the paragraph positions are worked out against the `.srt` instead of whisper's words (much faster and more paragraphs found), while card timing still uses whisper's words.
  - If no transcript file wins, the vote is retried with every other word source already on disk for the clip (the whisper words file, a `<clip>.whisper.srt`, a `<clip>.srt`), each only if it covers the same stretch of time; the source that places the most paragraphs wins. A log line names which source linked it. No transcription is run for this.
  - Paragraph positions are cached on disk in the engine's data folder, keyed on the words and paragraphs themselves.
- The clip is classed as "montage" (its transcript is in `Clips`), "interview" (its person's folder exists) or "cannot tell".

## What a card shows
(source: library_engine.py)

- **Its words**: the words whose midpoint lies inside the cut. A cut too short to contain any midpoint shows whatever words it touches, with both edges marked partial. Pause markers written as "(...)" are removed and whitespace collapsed.
- **Partial-word marks**: the first or last word is marked as partially cut only when at least 0.15 seconds AND at least 35% of that word falls outside the cut.
- **Silent cut**: a transcribed clip whose cut holds no words is marked silent rather than "no transcript".
- **English line under a non-English card**, three tiers, best available wins:
  - "exact": a stored Claude translation for exactly these words (see Translation).
  - "gt": a free Google Translate draft (see Translation).
  - "para": the human English of the transcript paragraphs the cut overlaps, cut down in proportion to the cut's time span. A paragraph counts if the overlap is at least 0.35 seconds or at least 30% of the paragraph.
- **Paragraph link**: each card links to the transcript paragraph it overlaps MOST (not the first it touches).
- **Other card facts**: interviewee and their colour; the cut's own clip colour only when someone chose a colour different from the interviewee's; clip name; start timecode; duration in frames and seconds (one decimal); gap before it (gaps under 2 frames are ignored) in frames and seconds; audio fade in and out in seconds (never longer than the cut); manual gain in dB; which transcription the words came from; whether the transcript is an interview or montage source.
- **Stacks (runs)**: consecutive cuts are grouped into one "stack" shown as one readable card. A new stack always starts on: a different clip, a gap on the timeline, a marker between the two cuts, or the stack reaching 90 seconds. A new stack also starts when the source jumps backwards (by more than 0.04 seconds) or forwards by more than 3 seconds, UNLESS the editor marked the cut "join". A cut the editor marked "split" always starts a new stack.
  - Marking a cut "join", "split" or back to the rule: refused with "that cut is no longer on the timeline" or "bad stack mark".
  - A stack's collapsed or open state is remembered per timeline and survives reloads and restarts.
- **Notes**: a note on a card, and a note on the gap before a card. Empty text removes it. Refused with "no timeline is open" or "that cut is no longer on the timeline". A card that exists only in the draft (a split half, an insert) can carry a note keyed by its source span; it moves onto the real cut once one with the same span exists. Notes, stack marks and collapsed state are kept in `<root>\Script Docs\timeline_notes.json` and follow a cut whose Resolve id changed (matched by clip, source in-point and duration).
- When a cut list is sent to Resolve, each gap's note is read fresh from the notes file at that moment (not from the page) and carried along; a log line "[conform] N gap note(s) carried from the notes store" is printed.
- **Page state totals**: total running time in seconds; per section (each section heading, plus an untitled lead-in row only if cards precede the first heading) its title, card count, seconds and start frame (an empty section still gets a row); count of distinct card texts still lacking an exact translation; exact timeline frame rate as well as the rounded one.
- Markers are published with a kind: "section" (a `## §` heading), "note" (a `## ◆` heading or note bullet) or "marker"; markers read off a Resolve timeline get their kind from their colour.

## Exporting the cut as a script
(source: library_engine.py)

- Exports the current cards as plain text (`.txt`) or Markdown (`.md`), in the card's original language only (a Mandarin card exports its Mandarin, never the English).
- Refused with "not connected yet -- no cards to export" when there are no cards.
- Markdown: a `# <timeline>` title; section headings as `## <name>`; other markers as `> ◆ <name>`; each card as the person in bold and the timecode, joined by an em dash character, then its words; card notes as `> 📝 <note>`; gap notes as `> 📝 gap: <note>`.
- Plain text: section headings underlined with `=` (at least 4); other markers as `-- name --`; card heading "person timecode"; notes as `[note: ...]` and `[gap note: ...]`.
- Silent and untranscribed cuts are skipped. The file name is the timeline name with `\ / : * ? " < > |` replaced by `_`.

## Exact translation with Claude (the translate button)
(source: library_engine.py, config.py)

- Starting a run is refused with: "claude is not available on this server: <why>"; "a translation run is already going"; "not connected yet"; "nothing needs translating".
- What is sent: every card whose words need translation (see Translation for which do) and that has no exact translation yet, grouped by stack so a stack is translated as one passage; parts of the stack already translated are sent with their English so new parts read on from them. Each card on the shelf (set-aside cards) is sent as its own one-part passage. The same words are never sent twice in one run.
- Each passage carries: the person; up to 15 seconds of the clip's own words before and after it (trimmed to the last 160 and first 160 characters); the human-approved English of every overlapping paragraph, each paragraph once, in order; and per part, the proportional slice of that English that lines up with the part in time ("en_near").
- Model: `claude-haiku-4-5-20251001` (fixed), thinking turned off, effort low, 300 second limit per call.
- Batching: at most 50 parts and about 20,000 characters per call, never splitting a passage; up to 3 calls at once. Each batch is retried once for the parts that came back missing.
- The model's instruction (TX_PROMPT, quoted where it decides what a person sees): translate "Taiwanese Mandarin to natural English"; each part's English must "cover exactly what its own `zh` says -- no more, no less"; "These are card captions, so a sentence fragment is fine where the cut is one; do not pad a 3-word utterance into a full sentence"; reuse the human paragraph translation's terminology, names and register; reply with only a JSON object of part key to English.
- **Copied-from-the-wrong-place check**: an answer that copies sentences verbatim from the transcript's English is checked against where that sentence sits in time. Sentences under 20 characters are ignored. If at least 60 copied characters, and more than half of all copied characters, come from paragraphs outside the cut (with 2 seconds of slack either side), the answer is refused (log: "[tx] refused <key>: N of M copied transcript chars are from outside a-b s") and that card stays on its paragraph slice.
- Progress: "translating N of M" is published as parts land; each batch is saved as it lands.
- End states: done; or "<N> segment(s) came back empty -- hit translate again"; or the error text of a failed call ("translator returned no JSON (exit N): ...", "translator returned unparsable JSON: ...", or a provider error).
- Translations are stored keyed on person plus exact words, so a trim that changes a card's words makes it pending again, and a shelf card translated here is already translated when it returns to the cut.

## The Claude command line as this engine runs it
(source: library_engine.py)

- The prompt is always sent on standard input (Windows command lines are limited to 32,767 characters, 8,191 through a `.cmd` shim).
- Flags: `-p --model <model> --dangerously-skip-permissions --strict-mcp-config` (no MCP servers load), plus the session flags. Working folder is always the MulticamPipeline folder.
- Environment: every inherited `ANTHROPIC_*` and `CLAUDE_CODE_*` variable and `CLAUDECODE`, `CLAUDE_PID`, `CLAUDE_EFFORT` are removed; then `CARDS_CLAUDE_OAUTH_TOKEN` (if set) is passed as `CLAUDE_CODE_OAUTH_TOKEN` (subscription login), else `CARDS_ANTHROPIC_API_KEY` (if set) as `ANTHROPIC_API_KEY`; neither set leaves the CLI on its own login. `CLAUDE_EFFORT=low` always; `MAX_THINKING_TOKENS=0` for calls that do not think.
- On Windows the child runs at normal priority with no window and tries to break away from its parent's job (to avoid inherited efficiency throttling), falling back if refused.
- A run expected to write a JSON answer file that leaves none fails with "the model run produced no usable output (exit N): <last 300 characters>".

## The transcript viewer and plain-text search
(source: library_engine.py)

- **Opening a clip's transcript**: answers the transcript's file and path, the interviewee and colour, the paragraphs, a per-word timing index for highlighting and click-to-play, character and pinyin maps for searching, and what audio the preview can play ("wav", "ogg", "src", "srcwait" while the clip's own audio is being extracted, or nothing). Refused with "no transcript document for that clip".
- **The transcript list** (for the switcher): every transcript met so far, with interviewee, clip, file, colour, word source and "montage" or "interview", sorted by person then clip.
- **Search across every transcript** (the header search): every paragraph of every transcript known, both languages, case-insensitive and simplified/traditional Chinese insensitive, with pinyin queries (see the text section). A transcript reached through several clips is searched once. Up to 200 paragraphs are returned with highlight positions; the answer also carries the total count and whether it was cut short. Results are ordered by person.
- **Turning a highlighted selection into a cut** ("insert"):
  - If the page says which paragraphs the selection covered, the selection is first searched inside those paragraphs' stretch of the clip's words (with 8 characters of slack), then in the whole clip, at a 75% match confidence.
  - If that fails and the selection is the English of a Mandarin interview, every paragraph whose English contains the selection (or is contained in it; both at least 8 characters after normalising) contributes its whole Mandarin span.
  - If the text match failed, or landed more than 2 seconds outside the highlighted paragraphs, the highlighted paragraphs' own span is used instead.
  - In both of the last two cases the result is flagged "whole paragraph" with its length in seconds (the page warns), and its confidence is capped at 0.5.
  - Handles of 12 frames are added either side, never reaching into the neighbouring words and never before the clip's start. A span is at least one frame.
  - Refused with "couldn't find that text in the clip's transcript -- try selecting the Mandarin line, or a longer stretch", or "no transcript for that clip".
- **A span the page timed itself** (from the played preview): the same handles and clamping, confidence 1.0. Refused with "empty span" or "no transcript for that clip".
- **An explicit span by frames**: refused with "that clip is not in the bin scan" or "empty span".

## Pasting Obsidian paragraph links as cards
(source: library_engine.py)

- Pasting text containing Obsidian block links (`![[Note#^id]]` or `[[Note#^id]]`, with or without a folder path, alias or `.md`) resolves each link, in paste order, into a card-sized span: the whole paragraph, located like a highlighted selection.
- Each link succeeds or fails on its own, so one bad link does not stop the others. Per-link refusals:
  - 'no transcript named "<note>" under this episode root'
  - 'that transcript would not open: <message>'
  - '"<note>" has no transcript this server can read'
  - 'block ^<id> is not in "<note>" - copy the embed again from the paragraph you want'
  - '"<note>" has no word timings yet, so there is no span to cut - transcribe that clip first'
  - or the selection-matching refusal above.
- A paste with no block link at all: "that paste has no Obsidian block link in it".
- On a cut-list server every transcript under the episode resolves, opened or not; elsewhere only transcripts met so far.
- Each resolved item carries the clip, the paragraph's words and English, person, colour, frame rate, span and confidence. Nothing is edited by resolving; the page lands the cards through the ordinary insert routes.

Reachability note for the library engine sections above and below. The rebuilt editor reaches this engine through per-feature Python "bridge" modules (`editor/features/*/bridge.py`). Those bridges build the cut-list engine (which carries everything in the library engine) and call: card building, card word timing, selection matching, the section arithmetic, the chat, shortening, montage, transcript search, translation storage, gap notes, the notes store, the fleet client and the configuration. Several bridges carry their own re-implementations of library-engine functions (the transcript viewer, `locate`, selection matching, plain-text search, the fleet intake). Functions below marked `UNREACHABLE` are called from nothing but the retired page's server (`handler.py`), or from other functions of this part that only that server calls.

- `UNREACHABLE: only the retired page's server calls these`: the episode-root switch request; stack join/split marks and collapsed stacks; the library engine's card and gap note setter; the script export; the translate run (`start_translation` and its batching; the translate bridge re-implements it); the per-clip semantic search and the corpus search; the section summaries; plain-text search across transcripts; Obsidian paste resolution; the page-timed span; `locate`; the WAV render request; the whole media library (peaks, audio extraction, Opus copies, 480p proxies); the fleet intake worklist and the whisper button; the pinned-job seam (`fleet_execute`, which only the CC Sync dashboard's pinned-job executor calls, and which the dashboard gives no engine when the new editor is on); the published-state versions, deltas and gzip cache; the draft mode switch. They are listed in full because they are present in the code.

## The media library: what the lane and video window play, and the waveforms
(source: library_engine.py, media.py, config.py) `UNREACHABLE: only the retired page's server and offline.py call these state functions; the rebuilt editor has its own media service in Node`

- **Where derived files go**: everything is written under `<root>\Script Docs\remote_audio\`. Audio extractions and 480p proxies of a clip's own media go one level down, in `remote_audio\source\`. Nothing is ever written beside the original media (the NAS mounts media read-only).
- **File naming**: every derived file is named after the clip name the page knows. If any derived file name would exceed 255 bytes (the longest suffix while writing is about 17 bytes), the name is shortened: the head cut on a character boundary, then `~` and 8 hex characters of a hash of the full name, then the trailing ` [<id>].<ext>` tag kept if it is short enough. A name that fits is never changed.
- **What the lane can play for a clip** (answer to the page, in order):
  - "ogg": the stage-2 reference WAV exists (`<transcript folder>\<clip>.wav`) and its Opus copy is current.
  - "wav": the reference WAV exists and the Opus copy is not ready.
  - "src": no reference WAV, and an audio-only extraction of the clip's own media is ready.
  - "srcwait": that extraction is being made (the page dims the clip and asks again).
  - nothing: no audio at all.
  - Asking is what starts an extraction.
- **An excerpt's WAV**: if the clip's transcript is an "Excerpt of" another transcript, the WAV beside the source transcript is used, following up to 3 pointers, ignoring loops. Looked up at most once a minute per clip.
- **The media file itself is never served** for audio; only the WAV, its Opus copy, or an audio-only extraction (served as `audio/mp4` for `.m4a` and `.opus.m4a`, `audio/ogg` for `.ogg`, `audio/wav` for the WAV).
- **Reaching the clip's own media** (setting `--media-map` / `CARDS_MEDIA_MAP`, default empty): pairs `<path as the Resolve machine names it>=<path here>`, separated by semicolons, compared case-insensitively with either slash. Without a map, only absolute paths that exist here work. A montage clip known only by its transcript folder is found through the `source` recorded in its `<stem>_words.json` (looked up at most once a minute after a miss).
- **Audio extraction recipe** (one-time, per clip, files newer than the media count as current):
  - The audio stream is probed first; no audio stream: failed "no audio track".
  - AAC audio: copied without re-encoding into `<clip>.m4a` (`-vn -sn -dn -c:a copy -movflags +faststart`). Accepted only if its duration is within 0.05 seconds of the source's; otherwise falls through to Opus.
  - Opus audio: copied without re-encoding into an MP4, `<clip>.opus.m4a`, same duration check.
  - Anything else (or a failed copy): decoded to mono Opus, 64 kbit/s, variable bit rate, in `<clip>.ogg`.
  - A browser that says it cannot play Opus in MP4 gets an `.ogg` made on request, queued behind the other extractions.
  - Files written to a temporary name and renamed in. A 30 minute limit per ffmpeg run.
  - An extraction named either `<clip>.mp4.m4a` or `<clip>.m4a` (when the clip name ends in a video extension: mp4, mov, mkv, webm, m4v, avi, mts, mxf) counts.
  - When the media cannot be reached at all but an extraction is on disk (an audio-only pool), the extraction plays.
  - States: ready, making, failed (with the reason), none (no reachable media), noffmpeg.
- **Order and parallelism**: one worker thread makes extractions, then Ogg requests, then 480p proxies, strictly audio first. When audio is waiting and the worker is busy, a second audio-only worker is started. Never more than these two ffmpegs for extraction and proxies. Progress shown as "N of M" (extractions finished of those asked for this session), with " + fleet 62%" or " + fleet: N" appended while fleet jobs are in flight.
- **480p proxy for the video window**:
  - Made only once some page has turned the video window on (until then the answer is "off"), only after audio work, one at a time.
  - Recipe: first video stream and first audio stream if any; scaled to at most 480 lines high (never enlarged; width keeps aspect, even); x264 `veryfast`, CRF 26, a keyframe every second (GOP = the source frame rate rounded, default 30), no scene-cut keyframes, yuv420p; AAC 96 kbit/s stereo; `+faststart`. A 60 minute limit. Output `<clip>.480p.mp4`.
  - No video stream: failed "no video track". If the proxy's audio length differs from the source's by more than 0.05 seconds a warning is logged.
  - The page is told "vid" (ready), "vidwait" (being made) or nothing. Progress "N of M".
- **Opus copy of a reference WAV** (for browsers on other machines): mono Opus 40 kbit/s VBR Ogg, `<clip>.ogg` in `remote_audio`. Made in the background for every clip that has a WAV as soon as the lane asks for that clip's waveform (one at a time), and also on first play. A 30 minute limit.
- **Waveform peaks**:
  - Made from the reference WAV, else from the clip's own media. File `<clip>.peaks` in `remote_audio`: the bytes `PK`, the rate (200), a zero, then one byte (0-255) per 1/200 second, the loudest sample in that slice scaled from 16-bit (decoded as mono 8 kHz).
  - A file made at a different rate (older files at 50 per second) or older than its source is remade.
  - At most 2 decodes at once; others wait and are reported as "making". A failed decode of the same source version is not retried for 10 minutes (answer "failed"). A 30 minute limit per decode.
  - States: ready, making, failed, none, noffmpeg.
- **Reference WAV render request**: refused with "a WAV render is already running", "that interview already has a WAV", "no interviewee folder known for that clip -- nowhere to put the render", "that multicam isn't in the bin scan yet -- give it a moment and retry". On success the render is queued for the Resolve side (covered by another section) and shown as a running job with a percentage.

## Handing media work to the CC Sync fleet
(source: fleet_jobs.py, library_engine.py, config.py)

- **Turned on by settings** `--fleet-url`, `--fleet-user`, `--fleet-password`, `--fleet-roots` (environment `CARDS_FLEET_URL`, `CARDS_FLEET_USER`, `CARDS_FLEET_PASSWORD`, `CARDS_FLEET_ROOTS`). All blank by default, which is off: everything is made by this process.
- **Roots map** (`--fleet-roots`): `name=prefix` pairs separated by commas or semicolons, for example `media=/media,vault=/vault` in a container or `media=P:/,vault=X:/` on a PC. Only the names `tree`, `vault` and `media` are accepted; any other is dropped with "[fleet] ignoring root <name>: the fleet knows tree, vault, media". Trailing slashes are removed. A path is sent as (root name, relative path), never as an absolute path. A path under no root is made locally.
- **Signing in**: `POST /api/v1/login` with the user name and password; the account must be a dashboard admin, otherwise jobs stay local ("[fleet] <user> is not a dashboard admin, and submitting a job is work on somebody else's computer -- jobs stay local"). The session cookie and CSRF token are kept; a 401 or 403 signs in once more and retries once. No redirect is ever followed.
- **Timing**: a 3 second TCP probe first (a pass is trusted for 10 seconds), then a 10 second limit per request. Each job is polled at most every 2 seconds. The machine list is cached 30 seconds, failures included.
- **Job kinds and priority**: `audio-extract` (priority 2), `peaks` (2), `proxy-480p` (1), plus `whisper` for transcription. Each job names its source (root, relative path), its output folder (root, relative path) and the output name (the clip name the page knows). The recipes the fleet runs are the ones above, byte for byte.
- **How a job is used**: when the page asks for a clip's audio, proxy or peaks, a fleet job is submitted first (before ffmpeg is even looked for locally). While it runs the answer is "making". When it is done, the file on disk decides. If the dashboard says nothing in the fleet can run it ("[fleet] job #N (<kind>) can be run by nothing in the fleet: <summary> -- making it here"), or the dashboard is down, slow, refuses, returns no id, or the job fails or is abandoned for any reason other than "no audio track" or "no video track", the file is made locally instead. "no audio track"/"no video track" are recorded as permanent failures.
- **Never two writers**: the local worker never makes a file a fleet job is making; if a finished file appears while the local worker is encoding, the local copy is discarded ("the fleet got there first; dropping ours").
- **Log noise**: each kind of trouble prints one `[fleet]` line, then nothing for 5 minutes.
- **Machine picker**: the list of machines a job can be aimed at (editor, machine, mode, online, last report, jobs enabled, kinds, capabilities, idle seconds, current job), and the job kinds the dashboard schedules; empty when anything fails.
- **The intake worklist** (`UNREACHABLE` in this module; the editor carries its own copy): files dropped on the page are matched by name (and size, when given) anywhere under the episode root; each row says whether it was found and whether it needs a transcript (no `Clips\<stem>\<stem>_words.json`) or a proxy. A row can be sent to the fleet as `proxy-480p`, `audio-extract`, `peaks` or `whisper`, optionally to one named machine. Refusals: "'<kind>' is not a fleet recipe", "that file is not in the vault yet -- put it under the episode root and drop again", "no fleet is configured on this server", "the fleet cannot name <path> (no shared root covers it)", "the fleet did not take the job".
- **The whisper button** (`UNREACHABLE`): one fleet `whisper` job per clip, requiring a whisper-capable machine with the share mounted and 6 GB of GPU memory, to any machine ("here") or one named machine (machine or editor/machine). Several clips at once are sent in order; the first refusal stops the rest and says "(N of M already sent)". Refusals: "that clip belongs to <episode>, not this one: switch to that episode to transcribe it"; "this clip's media is not reachable from the server - transcribe it on <agent machine> or from the base rig (tried <paths>; the media map covers <prefixes>)" (or "...no path to try...", "the media map is empty"); "no fleet is configured on this server -- run pipeline.py transcribe --folder ... by hand for now"; "the fleet did not take the whisper job"; "no clips named for whisper". Success note: "whisper queued on the fleet: N clip(s)" or "... on <machine> ...".
- **Pinned jobs** (`UNREACHABLE` from the editor; called only by the CC Sync dashboard's pinned-job executor when the old page is mounted): a media job the fleet gave up on can be run by this engine through the same queue and recipes. Refusals: "'<kind>' is not a recipe this engine makes", "a pinned job must name the stem its output goes under (out_stem)", "<path> is not a file this server can open", "this server has no ffmpeg". An output already current is answered "skipped". A cancel removes a queued job or kills a running ffmpeg; the disk has the last word. A heartbeat every 5 seconds while running. Pinned jobs survive the engine being stopped; ordinary queued clip work is dropped on stop.

## Semantic search inside one transcript, and search over the montage corpus
(source: library_engine.py, config.py) `UNREACHABLE: only the retired page's server starts these; the editor's search bridge uses transcript_search.py instead`

- Refused with "semantic search needs the claude CLI: <why>" or "a semantic search is already running". One search at a time per engine.
- **One transcript**: the transcript is sent inline, one paragraph per line as `^<id> <English> / <Mandarin>`, a `#` after the id marking an interviewer's question. A transcript longer than 120,000 characters is sent in pieces in order and the answers combined. Model `claude-sonnet-5`, 600 second limit per piece. The model is asked for every relevant paragraph, at most 20, each with a reason under 10 words; at most 20 are kept, duplicates removed. Errors: "that transcript has no paragraphs with block ids to search", "no transcript document for that clip".
- **The montage corpus** (the page names "corpus", or names nothing on a root that has a corpus): the question goes into the montage's retained conversation (see Montage builder). If the conversation is new or the corpus changed it is opened first. If the provider lost the conversation, the status line says "the Claude session was lost (new machine or a rebuilt container); re-reading the corpus", it re-opens once; a second loss fails with "the Claude session could not be opened even after re-reading the corpus". No corpus: "there is no corpus under this root -- nothing in Clips\ has been transcribed yet".
  - Answers are spans: clip stem plus the exact words. A clip not in the corpus is dropped; the words are located in that clip's word timing (75% confidence, with handles); a quote that matches nothing falls back to the segment it came from; a quote in no segment is dropped. At most 20. Each result carries clip, start and end in seconds and frames, the clip's frame rate, the words, the reason, the model's 0 to 1 score and the match confidence.
  - Status while running: "asking Claude about the corpus...".

## Section summaries on the overview panel
(source: library_engine.py, config.py) `UNREACHABLE: only the retired page's server starts these`

- One sentence (two at most, 35 words) of what a section says, written by `claude-sonnet-5` with thinking off and a 300 second limit, from the cards between that section marker and the next, each as "person: words" (English where an exact or Google translation exists).
- Refused with "the section summary needs the claude CLI: <why>", "no marker at frame N", "nothing transcribed between this marker and the next". Asking again while one runs just reports it running. Error "claude returned nothing".
- Stored per timeline in the notes file, keyed by the section's title (with `#2`, `#3` for repeated titles), so it survives trims and moves; a renamed section loses its summary. A summary whose section's words changed since it was written is marked stale. Old summaries keyed by frame are adopted when the title still matches.

## The project library database connection
(source: library_engine.py, config.py)

- The engine reads word timings straight from Resolve's project library (PostgreSQL) using connection facts the Resolve machine pushed, or `--db-host` / `--db-name` (environment `CARDS_DB_HOST`, `CARDS_DB_NAME`, default empty). A failed open is retried after 60 seconds; the failure is shown as "project database: <message>".
- Other settings in this family (used by the parts covered by another section): `--db-write-allow` / `CARDS_DB_WRITE_ALLOW` (which library names may be written directly; empty means none, the default); `CARDS_DB_BACKUPS` (where a row backup goes before every write; default `library_backups` under the data folder); wait 60 seconds for the Resolve machine to save and close a project before a write, 120 seconds for it to reopen, and a held agent reopens the project itself after 300 seconds.

## What the page is served, and how it stays current
(source: library_engine.py) `UNREACHABLE (the versioning, deltas, gzip and fail/idle states): only the retired page's server serves this state; the card building itself is reachable through the cut-list engine`

- Every published state carries: the cards, markers, section totals, summaries, translate job, search job, whether Claude is available here (always this server's own answer), WAV render job, Google Translate error, episode root and its name, a "follow" counter, the stale note, playhead, card under the playhead, undo availability, last edit result and an edit sequence number.
- A new version number is issued only when something a page can see changed. The last 32 versions are kept so a page can ask "what changed since my version": the answer lists changed cards (or, on request, only the changed fields of each card), removed cards, the full order and the changed top-level fields. Unknown starting points get the full state. The compressed full state is cached per version, up to 16 variants.
- An edit made on an older version is still accepted if the cut's shape (which cards, in which order, where each starts) has not changed since.
- **No-timeline states**: a fault shows the error as a red banner; a non-fault ("no agent has pushed yet", a timeline closed on purpose) shows as an amber note and the page shows the episode landing instead; "Resolve open on no timeline at all" is a fault flagged as such. Each bumps the version so the page redraws.
- **Draft mode switch**: "independent" mode's base is a snapshot of the cards every page sees, taken once on the server, only for the timeline currently open.
- Initial state before anything has been read: not connected, error "starting up", with the Claude availability already filled in.
- Stopping an engine flushes and stops its Google Translate worker; a translator that will not stop logs "[engine] the translator would not stop: <message>".

## Translation: which cards get an English line, the stored translations and the Google drafts
(source: translate.py, config.py)

- **Which card text needs translating**: any text containing Chinese characters; or text with letters that does not look like English. "Looks English" means: no letter outside basic ASCII (é, ß and so on mean not English), and at least one word, and at least 20% of the words, from a fixed list of common English words (the, a, and, of, to, in, is, ... plus "film", "films", "movie", "cinema"). Numbers and blanks never need translating.
- **Exact (Claude) translations** are stored in `<root>\Script Docs\card_translations.json`, keyed on a 16-character hash of the person's name plus the exact words with all whitespace removed. Each entry stores the original words, the English, the model name (`claude-haiku-4-5-20251001`) and a time stamp (minute). The file carries a comment saying entries are "safe to delete ... to force retranslation".
  - Two machines (the Resolve PC and the NAS container) can write this file: each reader checks the file at most once a second and re-reads it if it changed; each write first re-reads and merges, then writes atomically. Deleting an entry by hand does force retranslation.
- **Google drafts** ("≈" tier) are stored in `<root>\Script Docs\gt_translations.json`, same key scheme, with a comment that Claude translations always override them and the file is safe to delete.
  - A card with no exact translation is queued for a draft the first time its text is seen; a background worker fetches one at a time.
  - Two free, unkeyed Google endpoints are tried in order: `clients5.google.com/translate_a/t?client=dict-chrome-ex` then `translate.googleapis.com/translate_a/single?client=gtx`, target English, browser User-Agent `Mozilla/5.0`, 10 second limit. Source language `zh-TW` when the text has Chinese characters, otherwise `auto`. Text is sent with whitespace flattened to single spaces.
  - When automatic detection says the text is English already, an empty draft is stored (nothing shown, never asked again).
  - Pacing: at least 1 second between calls at rest. On a 429, 403 or 503 the gap doubles (at least 3 seconds, or the server's `Retry-After`), up to 30 seconds, and walks back down by 10% per success. The error line shows "google translate: rate-limited (<code>), slowing to N s between calls". Other failures show "google translate: <message>" and pause 5 seconds. A failed item is re-queued by a later read of the cards.
  - Saved every 25 fetched drafts and whenever the queue empties; a save failure shows "google cache: <message>". Writes merge with whatever the other machine wrote. A read-only cut list writes nothing to this file (drafts stay in memory).
  - When a draft lands, a hook lets a server with no timeline sweep republish so the English appears without waiting for the next edit.
  - Switching episode flushes unsaved drafts to the old episode's file first. Stopping the engine stops the worker after flushing.

## Transcript documents and text handling
(source: text.py)

- **Reading transcripts**: every file ending `_Transcript.md` in a folder is read as paragraphs separated by blank lines, a YAML frontmatter block at the top being dropped. In each paragraph: a line starting `^` is its block id; a line starting `#` marks it as an interviewer's question (the `#` marks are removed from the text); the line with the highest share of Chinese characters is the original-language line, provided at least 20% of it is Chinese; otherwise, if the paragraph has two or more lines and the last one does not look English, the last line is the original (for languages without Chinese characters, such as Vietnamese); the remaining lines are the English.
- **Finding a montage clip's transcript folder** `<root>\Clips\<stem>`: by exact stem, then case-insensitively, then by a YouTube-style `[<id>]` tag (6 or more letters, digits, `_` or `-`) anywhere in a folder name. The folder list is cached against the folder's modification time, except within 2 seconds of a change.
- **Finding a clip's whisper word file** (`<stem>_words.json`): first in its `Clips` folder (exact name, else the first file in that folder ending `_words.json`, alphabetically); otherwise in each `Interviewees\<person>` folder by exact name, trying the clip name before the media file's stem.
- **Reading a word file**: each word's start, end and text; words with empty text are skipped; a missing leading space is added unless the word starts with a Chinese, Japanese or full-width character; a word whose end is before its start ends at its start. Speaker labels per word are kept. Other keys of the file (for example `source`, `language`, `fps`) are kept as facts.
- **Search folding**: case-insensitive, and Simplified and Traditional Chinese characters treated as the same (using the `zhconv` package when installed, otherwise a table bundled with the pipeline).
- **Quoted queries** (`"..."`, straight or curly quotes, at least 3 characters with the quotes): exact case, no Chinese folding, and whole words where the query's edge is a letter or digit (so `"I"` does not match the I of "In").
- **Pinyin queries** (need the `pypinyin` package; without it pinyin search is off):
  - A query mixing Chinese characters and Latin letters: each run of letters stands for the sound of the characters in that position. A run may cover several characters, each contributing the start of one of its readings (so `我dh` finds 我的話, `我d` finds 我的, 我得, 我德).
  - A query of letters only (optionally with tone digits 1-5, spaces or apostrophes, at least 2 letters), such as `chu1`, `chuqu`, `guo2wang2`: searched both as plain text in the English and as pinyin in the Chinese, where each character must take a whole syllable (except the last letters, still being typed). Results of both are merged.
  - A tone digit after a syllable must match the character's tone (5 is the neutral tone); no digit matches any tone. `ü` is typed as `v`. Every reading of a character with several is accepted. Longest matches are preferred.
- **Placing paragraphs in time for the word-by-word transcript view** (each word mapped to its characters in the paragraph, for the playing-word highlight, click-to-play and selection play), best first:
  1. The paragraph found exactly (Chinese script differences ignored) in the clip's words.
  2. The paragraph found in the vault `.srt` the transcript was exported from, or the paragraph's span from the English index; then the clip's words are searched inside that stretch (plus 2 seconds either side) at 72% similarity.
  3. Otherwise the `.srt` cues themselves, or one row for the whole paragraph.
  - Rows from tiers 2 and 3 are marked approximate so the page can warn that an insert may be a little wider than the selection.
- **The English index** (paragraph time spans): each paragraph's original line (or English line) looked up exactly in the clip's words. A transcript file with 3 or more exact hits then has its other paragraphs searched at 75% similarity. A file with fewer than 3 exact hits gets a second chance at 82% similarity only if at least one of up to 3 sample paragraphs matches at 82%. A file needs 3 or more placed paragraphs in total to be accepted as this clip's transcript; the file with most wins. Answers are cached in `<data folder>\en_index\<hash>.json` keyed on all words and paragraphs (cache format version 2).
- **Proportional English slice** for the dimmed paragraph tier: the words of the paragraph's English covering the same fraction of the paragraph as the cut covers, at least 3 words, "…" marking each cut end; a cut within 8% of both paragraph edges, or an English line of 3 words or fewer, shows the whole line.

## The montage corpus (every transcribed clip under Clips)
(source: corpus.py)

- A corpus clip is a folder `<root>\Clips\<stem>` holding `<stem>_words.json` (or any file ending `_words.json`). Each is known by the id `clip:<stem>` so it can be named, previewed and inserted even when no cut uses it. Registering reads no transcript, only folder listings; the clip's words are read when first needed.
- A clip's frame rate is read from its `<stem>_Transcript.md` frontmatter (`fps`), default the house rate 29.97.
- **What Claude reads (the digest)**: for each clip, a header line `### <stem> [<id>] <channel> -- <title> (<duration>s, speakers: A, B)` (parts the clip lacks are left out; the id, title and channel come from the transcript frontmatter, the id falling back to the `[<id>]` tag), then one line per whisper segment, `<start> <end> <text>`, seconds to one decimal. Never the individual words.
- The digest is split into messages by clip, at most 25 clips and about 100,000 characters per message; a single clip over the budget gets a message of its own and is never split.
- The digest is cached per root against each word file's modification time and size; a re-transcribed corpus produces a new digest and a new hash (which re-opens any conversation that read the old one).
- **Fallback for a quote that cannot be located in a clip's words**: the segment containing its first 5 words (at most 24 letters and digits after normalising, retried with the first 8), needle at least 4 characters.
- **Corpus summary** for the page: the clips (stem, id, title, channel, duration, speakers, language, frame rate, segment count, characters), the count, digest size, number of messages and hash.

## The stores in Script Docs
(source: stores.py)

- **Notes store** (`<root>\Script Docs\timeline_notes.json`, reachable: the gap-notes bridge uses it): per timeline, buckets of card notes, gap notes, stack marks, collapsed flags and section summaries. Each note is kept under the cut's id with its (clip, source in-point, duration) key; empty text deletes. When a cut's id disappears, its notes move to the one live cut with the same key, if exactly one exists. Saved atomically; a failed save logs "[notes] could not save <path>: <message>".
- **The shared draft** (`<root>\Script Docs\timeline_plans.json`) `UNREACHABLE: only the retired page's server and its agent link use it`:
  - One draft per "project|timeline": a revision number that only ever goes up, a mode (`now`, `queue` or `indep` for independent), the device that last set the mode, independent mode's base snapshot of the cards (dropped when leaving that mode, and stripped from old files on load), and the staged edits.
  - Every write names the revision it was made against; a stale revision is refused with "the plan moved on (rev N) -- re-applied" and the current plan is returned so the page re-applies its edit on top.
  - Edit kinds accepted: move (a block of cuts, before a cut or at the end), trim (frames off head and tail), split (offset), delete (cuts), insert (clip, source span, words, English, person, colour, clip name, clip frame rate, before which cut), extend (edge in/out, signed frames), marker (cut, offset, colour default Blue, name, note, duration default 1, custom data), color (cuts, one of the pipeline's clip colours or none), gap (frames before a cut, absolute; can record the cut it moved from), fade (fade in/out frames, absolute), gain (dB on cuts, rounded to 0.1, clamped to plus or minus 30). Each edit can carry source keys so it still applies after cuts are renamed.
  - Refusals: "a plan is a list of edits", "bad edit in the plan", "unknown edit '<k>' in the plan", "bad move in the plan", "bad delete in the plan", "bad colour edit in the plan", "'<name>' is not a clip colour this pipeline sets" (with " (Resolve's Brown is never assigned -- Chocolate is the brown)" for Brown), "a gap edit has to name the cut it sits before", "a gap's length has to be a whole number of frames, not <x>", "a gap cannot be N frames long", "a fade edit has to name its cut", "a fade has to be a whole number of frames, not <x>", "a fade cannot be N frames long", "a fade edit has to set an end", "a gain edit has to name its cuts", "a gain has to be a number of dB, not <x>", "a gain has to be a number of dB", "unknown mode '<m>'", "could not save the plan: <message>".
  - Operations: replace the whole draft, append one edit, undo the last edit (an empty draft still bumps the revision), set the mode.
  - Every revision is appended to `timeline_plans.history.jsonl` (time, timeline, revision, mode, device, count, edits; never read by the server). A draft going from some edits to none logs a line naming the device.
  - Named copies in `<root>\Script Docs\plans\<name>.json` (name cleaned of `< > : " / \ | ? *` and control characters, trimmed, at most 120 characters, default "plan"); saving an empty draft is refused with "nothing staged -- nothing to save"; the list shows name, project, timeline, saved time and edit count, newest first; loading a bad file: "could not read that plan: <message>". Old files that are a bare list still load.
- **Where each device was** (`<root>\Script Docs\timeline_place.json`) `UNREACHABLE: only the retired page's server uses it`: per timeline and per device id (up to 24 devices, newest kept): the selected card (by source key), the card at the top, the view ("lane" or "cards"), lane head, zoom and scroll. A device's first visit to a timeline is handed the most recent place any device saved, flagged as a first visit. Up to 50 recorded places ("marks") per timeline, shared across devices. Server-clock stamps, always increasing. Device labels up to 32 characters. A failed save is logged and ignored. Refusals: "a place is an object", "marks are a list of places".
- **Bins for the browse tab** (`<root>\Script Docs\cards_bins.json`) `UNREACHABLE: only the retired page's server uses it`: named bins; each clip in at most one bin (filing moves it); deleting a bin unbins its clips. Refusals "no clip named", "a bin needs a name".

## The montage builder ("describe a montage, get a cut list")
(source: montage.py, config.py, claude_session.py)

Reachability: the editor's montage bridge reuses the prompts, the corpus digest, the quote resolver (`resolve_quote`) and the frame-rate lookup from this part, and runs the Claude conversation and the file write itself. The describe job below (`start_describe`, its worker and `write_cutlist`) is `UNREACHABLE: only the retired page's server starts it`.

- **One Claude conversation per cut list**, remembered in the `.claude-session.json` sidecar beside the `.cut.md`. Model `claude-sonnet-5`. Opening timeout 900 seconds per corpus part; describe and revise turns 900 seconds each. Thinking off while the corpus is read in.
- **Opening the conversation**: the corpus digest goes in one message per chunk, each message being the chunk, then a line `---INSTRUCTIONS---`, then the instruction (the runner door caches everything above the last such line). Every part but the last asks for the single reply "ok" without summarising; the last part states the ground rules and also asks for "ok".
  - The ground rules (MONTAGE_OPEN_PROMPT), which decide what the editor gets: a cut is a span of one clip named by quoting the clip's own words exactly (never paraphrased, translated or tidied); clips are named by stem exactly as in the header; "Languages stay mixed through the whole piece. Never put an English speaker over a Mandarin one to say the same thing; a soundbite is never dubbed"; spread the cut across sources without filling a quota, long runs on one clip allowed; every quote must be words actually said, and the model should say when the corpus cannot carry a beat.
  - Re-opened when the conversation has had no turns, or its recorded corpus hash differs from the current digest's.
  - If the provider does not know the conversation, the corpus is sent again from part one in a new conversation; refused a second time: "the Claude session could not be opened: the provider refused the id twice running". No corpus: "this episode has no corpus yet: transcribe some clips into Clips\ first (pipeline.py transcribe --folder ...)".
- **Describe**: the editor's text (braces turned into parentheses) is sent with the instruction to choose extracts, order them, group them into titled sections ("a cold open, the threat, the argument -- whatever this material wants") and give each cut a reason under 12 words, answered as JSON (sections, each with cuts of clip, quote, why).
- **Revise**: the same, prefixed "Revise your previous cut list. Keep what still works, change what the note below asks for, and reply with the WHOLE list again".
- Refusals before starting: "say what the montage should be first"; "the montage builder needs claude: <why>"; the cut list's read-only reason or "this cut list is open read only"; "the montage builder writes a cut list, so it needs one open (--project FILE)"; "a describe is already running".
- Job states shown: opening (with "part k of N"), describing, writing, done (cuts, sections, unmatched, dropped clips, seconds), failed. A lost conversation shows "the Claude session was lost (new machine or a rebuilt container); re-reading the corpus" and is re-opened once; lost twice: "the Claude session was lost twice running -- give it a moment and retry".
- **Turning the answer into cuts**:
  - A clip not in the corpus is dropped (logged).
  - The quote is located in the clip's words at 75% confidence or better (with handles clamped to neighbouring speech); otherwise the segment containing its first words is used; otherwise the cut stays in the file as an "unmatched" note "<stem> -- <quote>" so nothing proposed is silently lost.
  - Sections become `## §` section headings; each cut carries its reason as its note.
  - No cut placed and none unmatched: "the model proposed no cuts this server could place -- try saying it another way".
  - The cut list's frontmatter, the shelf, its categories and saved sequences are kept; only the cut is replaced. The revision number goes up, "written" is stamped "<time> by the montage builder", the file is saved with history and reloaded.

## Gap notes carried into Resolve
(source: gap_notes.py)

- **On the server**: when a cut list is sent to Resolve, every cut with a gap before it (gap > 0 frames) gets the gap's note taken from the notes store at that moment (whitespace collapsed); any note the page sent is ignored. A note lookup that fails logs "[gap-notes] no note for <cut>: <message>" and the conform continues. A cut that exists only in the draft keeps its note under its own card id.
- **On the Resolve machine (the route the engine uses, "Fusion clip")**:
  - A media-pool bin "Gap notes" is found or created; a scratch timeline "zz gap notes scratch (Claude)" is created in it.
  - For each gap note: a Text+ title is inserted at the end of the scratch timeline, its text set to the note wrapped at 34 characters per line, size 0.065, and turned into a Fusion clip named "Gap note - <note>" (at most 80 characters).
  - Back on the conformed timeline, a new video track named "Gap notes" is added on top and each Fusion clip is placed over its gap exactly (start frame to gap end, no ripple), repeated if Resolve held it to a shorter length (up to 64 pieces); each placed item is named with the note.
  - A clip that does not land exactly inside its gap is removed and the note becomes a marker instead.
  - The scratch timeline is deleted afterwards (if it cannot be: warning "the scratch timeline 'zz gap notes scratch (Claude)' is still in the Gap notes bin: delete it"); the Fusion clips stay in the bin. The previously current bin is restored. If anything on the other tracks moved: warning "the picture on <track> is not where it was before the titles: check the timeline".
- **Fallback marker**: a Green duration marker spanning the gap, named with the note, its note text "Gap note from Timeline Cards (N.N s). Not a title because <reason>", custom data `cards:gap-note`. If Resolve refuses a marker on that frame, it is placed one frame in and one frame shorter; if that also fails the note is counted as lost. Green is used because markers read back from Resolve in any other colour (except Red) would become section headings.
- **Summary line** added to the conform's message: "N gap note(s): X as title(s) on the Gap notes track, Y as marker(s) (counts per reason), Z could not be placed at all", plus ". WARNING: ..." for each warning.
- **Directly-written project library route** (covered by another section): gap notes always become markers; the message adds " -- N gap note(s) as marker(s) over their gaps (the library route carries gap notes as markers, never titles)" and " -- N gap note(s) could not be placed: their frames already had a marker".
- **First route (title inserted at the playhead with every other track locked)**: `UNREACHABLE: kept only for the tests; the engine calls the Fusion-clip route`. It locked all other tracks, inserted Text+ at the gap with In/Out marks, verified track, position and length (a title longer than its gap is removed), stopped placing titles if the picture moved, unlocked only what it locked (warning "<tracks> stayed locked: unlock it in Resolve"), restored the playhead, and deleted the notes track if nothing landed.

## Searching every transcript in the episode with Claude (the search panel)
(source: transcript_search.py, config.py, models.py)

Reachable: the editor's search bridge uses this module.

- **What is searched (the corpus)**: every `*_Transcript.md` under `<root>\Interviewees\<person>\` (interviews, first, in name order) and every `_Transcript.md` in each `<root>\Clips\<stem>\` folder that has a word file (corpus clips). Each transcript is sent as a header `### <interviewee or clip> :: <transcript name>` then one line per paragraph, `^<block id> [<time>] <words>`. A paragraph of a Mandarin interview carries `<English> / <Mandarin>`. Headings in clip transcripts of the form `## [hh:mm:ss:ff] Speaker` give the time shown on the paragraphs under them; interview paragraphs have no time. Interviewer questions are included. Paragraphs without a block id are not results.
- **Scopes** (the drop-down): "All interviews" (count of interview transcripts), one row per interviewee (count of their paragraphs), and "All corpus clips" (only when there are any). Each scope is its own conversation holding only its own transcripts. A scope sentence is added to each question:
  - all: "Search every interview in this episode, and rank across all of them. Ignore the corpus clips."
  - person: "Search ONLY the interview transcripts of <person>. A passage from anybody else is not an answer."
  - clips: "Search ONLY the corpus clips (the transcripts under Clips), not the interviews."
  - Refusals: "this episode has no corpus clips to search"; "there is no interview transcript for <person> under this episode"; "no such search scope: <scope>"; "there are no transcripts under this episode yet: nothing to search".
- **Two modes**:
  - **Concept** (default): paragraphs that discuss an idea, in any language. The model returns a one-line summary and up to N results, each a block id with the interviewee, transcript and a one-sentence reason; it is told not to write the paragraph's text. Each result is checked: a block id in no transcript is dropped; when two transcripts share a block id the one matching the named interviewee wins; a result outside the scope is dropped. The result shows the paragraph's own text from the file, its time, whether it is a question, the transcript, and the clip id so the page can jump to it (empty when the engine has not met that transcript yet).
  - **Literal**: the words actually spoken that come closest to the words typed, searched only in the original-language lines (the conversation's corpus is the original lines alone, never translations). Results are short spans ranked in tiers "exact", "near", "synonym", "paraphrase". Each span must be found, letter for letter (ignoring spacing, punctuation, case and Simplified/Traditional differences), in the original line of the paragraph it names, otherwise it is dropped. A span whose words equal the query is promoted to "exact"; one the model called "exact" whose words differ in the same script is demoted to "near". Before Claude answers, an instant local pass finds the query's own words as typed (at least 2 letters or digits) in the original lines, shown while waiting and added to the exact tier if the model missed them. Same span twice is shown once.
  - Literal spans carry: the words as in the file, the whole paragraph, the character positions, the language, the English beside it (for non-English lines), the time in seconds where word timing exists ("words"), the whole paragraph's time when only it can be placed ("paragraph"), or none, and whether that timing is approximate.
- **Splices** (optional, either mode, when the page asks): up to 3 suggestions, each an ordered list of 2 to 6 fragments from different places that, cut together, say what was searched for. Each fragment is verified like a literal span; a splice with any fragment not found is dropped whole. Each carries its total seconds when every fragment is timed. In concept mode the fragments must be copied from the Mandarin where a line has both languages.
- **How many results**: default 5; the page offers 5, 10, 20 or 50; any number is accepted and clamped to 1-100; anything not a number (including true/false) gives the default. The answer reports how many the model offered (capped at the limit) so "3 of 5" is visible when some were dropped.
- **Model**: Sonnet by default, or Opus or Fable chosen per search (see the models section). Each model and each mode is a separate conversation.
- **Retained conversations**: one per (episode root, scope, model, mode), with a deterministic id derived from the root, scope, model and mode, so two servers on one vault join the same conversation. Sidecars in `<root>\Script Docs\`: `transcript-search.claude-session.json` (all), `transcript-search.person-<Name>.claude-session.json`, `transcript-search.clips.claude-session.json`, with `.m-opus` / `.m-fable` and `.literal` added for non-default models and literal mode. (A person's name is turned into a file-name part: letters and digits of any script kept, everything else a hyphen.)
- **Opening**: the scope's corpus goes in parts of at most 100,000 characters, split between transcripts (a longer transcript is split between paragraphs, each part repeating its header); every part but the last asks for "ok"; the last carries the rules. Opening timeout 900 seconds per part, thinking off.
  - The concept rules (TSEARCH_OPEN_PROMPT): answers name paragraphs by block id exactly and never invent one; quotes are exact; "Meaning matters, not keyword overlap, and both languages count"; remember the conversation, a later question may narrow, widen or argue with the last answer.
  - The literal rules: find wording, not ideas; copy words character for character in the language spoken; a query in one language may be answered by words in another.
- **Warm or cold**: a conversation is warm if it has had a turn, holds the current corpus (no transcript changed since), and its last turn was less than 3600 seconds ago (measured in memory, or from the sidecar's modification time after a restart). A cold search opens a new conversation and re-sends the scope's transcripts, and the answer says why:
  - "the first search of the session reads <thing>"
  - "a transcript changed since the last search, so <thing> was read again"
  - "the conversation had gone cold (over an hour), so <thing> was read again"
  - where <thing> is "every transcript", "<person>'s transcript" or "the corpus clips".
  - If the provider lost the conversation: "the Claude session was lost (new machine or a rebuilt container), so the transcripts were read again"; lost twice: "the Claude session was lost twice running: give it a moment and retry". An id refused twice while opening: "the Claude session could not be opened: the provider refused the id twice running".
- **Question timeout** 600 seconds.
- **Refusals before searching**: "type what you are looking for"; "the transcript search needs claude: <why>"; "a transcript search is already running: one question at a time keeps the conversation in order" (with the running search's details). Only one search runs at a time per engine.
- **Asking the same question again while it runs** (same query, scope, model, limit, mode and splices; for example after a reload or from a second tab) joins the running search and gets its answer, marked as joined; if it does not finish in time: "the same search is still running: its answer will be here when it lands".
- **Status for the page**: the search running now (query, scope, model, limit, mode, phase "starting", "reading" with "part k of N", or "asking", elapsed seconds counted on the server, whether it is cold, characters to read, expected seconds and where that estimate came from) and the searches finished within the last hour (at most 12), newest first; a finished search's answer is handed out when asked for by id.
- **Session line** for the page: warm or not, turns, seconds since the last turn, conversation id and key, mode, scope, model and its label, characters in the scope and in the whole episode, and expected durations warm and cold.
- **Time estimates for the progress bar**: the median of this conversation's last 6 searches of the same kind (warm or cold) ("measured"); else, from other conversations on the same model and mode, the median warm time, or the median seconds-per-character times this scope's characters for cold ("scaled"); else defaults: 25 seconds warm, 60 seconds cold for the whole episode, scaled down by characters for a smaller scope ("default"). Never below 5 seconds. A warm search that has to re-open grows its estimate by a cold read from that moment. Timings are kept in `transcript-search-timings.json` in the engine's data folder (not the vault); a failed save logs "[tsearch] timings not saved: ...".
- **Start over** (button): resets only the conversation for the scope, model and mode on screen; its transcripts go in again on the next question.
- Nothing is written to the vault except the conversation sidecars; no prompt ever names a vault path.

## Working offline: download, refresh and replaying edits
(source: offline.py) `UNREACHABLE: the manifest, prepare, words, revision and replay functions are only called by the retired page's server. The two error-wording functions are used by the cut-list engine's edit routes`

- **Download manifest** (what "download for offline" would fetch, with sizes, before it starts): the current state; the word timing of every card and shelf card in one answer (cached per version); every transcript the engine has met, those used by the cut list first (in cut order) then the rest by name; and, for each clip the cut list uses, its audio (the lane's own choice: Opus copy, WAV, or extracted audio, including an extraction whose media is unreachable), its 480p proxy if already made, and its waveform peaks if already made, each with size and modification time (so a re-rendered file is noticed). Totals: JSON bytes, audio bytes, video bytes, clip count, transcript count. Project facts: file, path, revision, version, read-only. All addresses are relative so they work under `/` and under `/cards/`.
  - Building a manifest starts no audio extraction or proxy encode (peaks are an exception: asking for them starts making missing ones, as the lane does).
- **Prepare**: asks for the audio of every referenced clip that has none yet (queuing extractions), and reports how many are ready, which are being made and which cannot be.
- **Revision check** (for the offline badge and refresh): revision, version, file, path, and whether the file on disk moved.
- **Replay plan for edits made offline**: given the revision the copy was taken at and the queued edits in order, decides per edit:
  - "send": a replayable edit, replayed through its own route by the page;
  - "skip": not a replayable edit ("that is not an edit an offline page can replay");
  - "stop": the replay cannot continue. The first stop says why; everything after it says "the replay stopped before this one". The page shows these with keep-mine / drop-mine choices.
  - The replay stops at the first edit if no cut list is open ("this server has no cut list open, so there is nothing to replay onto"), or if the server's revision differs from (or the copy does not know) its base revision ("the cut list on the server moved on while you were away (rev N, your copy was taken at rev M)").
  - Replayable edits: reorder, trim, split, delete, insert, extend, marker, color, note, gap, fade, gain, section move, stack, stage, unstage, stage move, stage category, new stage category, delete stage category, bin, new bin, delete bin. Not replayable: anything needing Resolve, the project library, Claude or the fleet, and undo/redo.
- **Renamed cuts during replay**: an edit may carry, for each cut name it uses, the cut's span (clip, source in, source out in frames). A name the server no longer knows is replaced by the one current cut with that exact span; if none or several match, the name is left and the edit is refused normally. Applies to the fields uid, before, after, from, uids, target and a gap's uid/from.
- **What a refusal means**: an error containing "changed on disk", "the timeline changed", "the cut list changed" or "the plan moved on" is a conflict (stop the replay and ask the editor); any other error is a refusal (drop that edit with its reason and carry on).
- **Error wording shown to the editor**: a missing field reads "that edit did not carry everything the server needs (the <name> field is missing)"; deliberate refusals and number errors keep their own sentence; anything else reads "the server could not carry that edit out: <message>" (or "... (<kind>)" with no message, or "the server could not carry that edit out" with nothing).

## The "ask Claude" edit chat (talking to the open cut list)
(source: chat_edit.py, config.py, models.py, claude_session.py)

Reachability: the editor's chat bridge reuses this module's paragraph resolution (`_locate`, the needle rule, the question refusal) and the engine's selection matching; the editor runs the conversation, the proposals and their application in its own code. The conversation, proposal, apply and undo machinery below (`ChatEditor.ask`, `apply_proposal`, `undo_turn`, `reset`, `state`) is `UNREACHABLE: only the retired page's server calls it`, except that `turn_json` / `lean_json` are also driven by the shortening module, itself reached only through the same server (the editor's shorten bridge uses only that module's prompt builders and checks; see the next section).

- **Only for an open cut list**: refused with "open a cut list first - the chat edits a .cut.md, not a live timeline" when no `.cut.md` is open (a live Resolve timeline does not count). A read-only cut list: "this cut list is open read only, so nothing can be changed in it".
- **Model**: Fable by default (`claude-fable-5-1`), or Sonnet or Opus from the picker. Environment variable `CARDS_CHAT_MODEL` pins the default model for a whole server. The picker is a property of the panel: an empty model in a request keeps the panel on its current model. Each model is a separate conversation.
- **One retained conversation per cut list and model**: sidecar `<name>.chat.claude-session.json` beside the cut list (`.chat.m-opus` / `.chat.m-fable` for non-default models), separate from the montage builder's. The panel's own memory is `<name>.chat.json`: the visible history (last 50 turns), which cards the conversation has already been given in full, the revision last seen, every conversation id ever used for this file (up to 50, the first never dropped) and what the conversation was opened with.
  - The first conversation of a file uses an id derived from the file path (so two browsers join it); every later one gets a random id never used before for that file. A conversation whose first turn failed for any reason has its id treated as used, and the next message opens a new one.
  - A provider error containing "already in use" is treated as a lost conversation.
- **Turn limits**: 900 seconds for a cold turn (the whole digest goes in), 600 seconds for a warm one. Warm for 3600 seconds after the last turn.
- **What the model is given on a cold start**:
  1. Every transcript of the episode (the same corpus the transcript search builds, all interviews and corpus clips), one part per message, each answered "ok" (CHAT_PART_PROMPT).
  2. Then the rules, the ops vocabulary, the house style and the whole cut list (CHAT_OPEN_PROMPT), then the editor's message.
  - With no transcripts on disk, the model is told "This episode has no transcripts on disk, so the cards below are the only material there is".
- **The cut list as the model reads it (the digest)**: a header line "FPS <rate>[ DF]   REV <n>   CUTS <n>   TOTAL hh:mm:ss   SECTIONS <n>"; then in cut order, headings as `§ SECTION "<name>"   @ frame N   <k> cards hh:mm:ss` (notes as `◆ NOTE ...`), and each card as `[<uid>] <person>  <seconds>s` plus " gap-before Ns" and " color X" when present, its words on a `text:` line, its highlights on an `hl:` line as `==words==`, its note on a `note:` line; then `--- STAGED SHELF ---` grouped by category (`## staged - <category>`) and `--- ALTERNATES ---`. On warm turns a card the conversation has already seen in full is one line with its first 60 characters (highlights still shown); a trimmed or split card has a new id and is sent in full again. Every turn re-sends the current digest with "CURRENT STATE (rev N)".
- **The rules that decide what the editor gets** (CHAT_OPEN_PROMPT): answer one JSON object `{"say", "proposals": [{"title", "why", "ops"}]}`; "NOTHING YOU WRITE IS APPLIED WHEN YOU WRITE IT"; one proposal when there is one obvious way, up to four only when they are real alternatives; `say` alone (no proposals) is a question or an answer, right when guessing would be needed; revise the same request on follow-ups; never invent an id; smallest set of ops; ask when ambiguous; `say` is one to three plain sentences; quote card words exactly; new material only from the transcripts, by block id, with exact words; a paragraph whose transcript has no word timings cannot be cut; CONTEXT words like "here", "this card", "the playhead", "what I have selected" mean what the context says.
- **House style** (CHAT_HOUSE_STYLE, editorial policy given to the model; replaceable per episode by `<root>\Script Docs\chat-style.md`, an empty or unreadable file falling back to the default): no interviewer questions ever; withhold then reveal; part of a sentence can be the whole card; end sections on a cliffhanger; space out revelations; never invent tension or change what was said; make the cut feel like one conversation between people who never met. When the editor's request conflicts with the style, do what was asked and say in one sentence what the style would have done. Changing the style file (or the shortening rubric) opens a new conversation.
- **Context the page sends with each message**, all optional: the playhead frame and timecode, selected card ids (with person, timecode and words, in click order), selected shelf cards, first and last visible card, the view, whether the shelf is open and its category, and the transcript pane (person or file, selected text, paragraph ids). The engine re-derives the card under the playhead from the frame (never trusts the page's card id), drops selected ids that are no longer in the cut list, takes person and words from the live card, and works out each selected card's section. The model is told: "playhead: <tc>, inside [uid] (person "words"), N.N s in" or ", not on a card"; "selected: ..."; "visible: [a] .. [b]"; "view: ..."; "shelf: open, category ..."; "transcript pane: ..."; plus a fenced "SELECTED CARDS" ... "END SELECTED CARDS" block (header wording shared with the CC Sync dashboard's runner so the block appears once); plus what became of the last turn's proposals ("last turn: proposal "<title>" was applied" or "last turn: none of the N proposals was applied").
- **Handles the model may use instead of an id**: `@playhead` (the card the playhead is in), `@selected` (the selected cards, in cut order), `at_playhead: true` (place at the playhead), and `new:<name>` for a card inserted earlier in the same proposal (`"as": "<name>"`). Unresolvable handles fail with: "the page did not say where the playhead is, so there is nothing here to point at" / "... so there is nowhere to put it"; "the playhead is not on a card right now, so there is nothing under it to name"; "nothing is selected on the page right now".
- **The ops** (each one engine revision unless noted):
  - `move` uids `after`/`before` a card, `to_start`, `to_end` (the default with no anchor) or `at_playhead` (before the playhead's card if the playhead is in its first half, else after). Errors: "no card was named to move", "a card cannot be moved before or after itself", "that card is the one the playhead is in, so there is nowhere to move it to", "the card under the playhead is not in the cut list any more", "the card to move before/after is not in the cut list any more", "those cards are already there". Line: "moved N card(s) <where>".
  - `delete` uids: out of the cut onto the shelf under the name of the section they came from. "no card was named to delete"; "deleted N card(s)".
  - `stage` uids with optional category: onto the shelf. "staged N card(s)[ under <cat>]".
  - `unstage` a shelf card back into the cut, optionally before/after a card. Must be on the shelf: "Claude named a staged card that is not on the shelf (<uid>). Nothing was changed."
  - `trim` a card to keep from one substring to another (either optional): up to two trims (head, then tail), cut at the midpoint of the silence between words; the kept words are highlighted on the card unless `"highlight": false`. Errors: "a trim needs the words to keep: keep_from, keep_to, or both"; "'<b>' comes before '<a>' in that card, so there is nothing between them"; "that card already begins and ends on those words, so there is nothing to trim".
  - `split` a card just before the first word of a substring. "'<words>' is the start of that card, so there is nothing to split off before it".
  - `gap` seconds before a card (converted to frames at the cut's rate; 0 removes). Must be a number: "Claude asked for a gap of <x>, which is not a number of seconds. Nothing was changed."
  - `color` uids one of Orange, Apricot, Yellow, Lime, Olive, Green, Teal, Navy, Blue, Purple, Violet, Pink, Tan, Beige, Brown, Chocolate, or empty to clear. Others: "<x> is not a Resolve clip colour. Nothing was changed."
  - `note` on a card ("" clears).
  - `highlight` words on a card, which may be on the shelf ("" clears).
  - `section_add` a heading (kind section, Blue, or note, Green) before a card, at the end (default) or at the playhead's exact frame. "a heading needs a title".
  - `section_from` uids + title: gathers the cards where the first of them sits and puts a Blue section heading before them; the line warns "(the cards after it stay under it until the next heading)" when cards follow. Errors "no card was named to group", "none of those cards is in the cut list any more", "the first card of the group is not in the cut list any more".
  - `section_remove`, `section_rename` ("a rename needs the new title"), `section_move` (before a card, which means before the section that card begins or the next one; `before_section` another heading; `at_playhead`; or at the end). "a section cannot be moved above itself". Headings are matched by title, case-insensitively; refused if none ("there is no heading called "<t>" in this cut list. Nothing was changed.") or more than one ("more than one heading is called "<t>", so it is not clear which one was meant. Nothing was changed."), or empty ("Claude named no heading. Nothing was changed."). A heading added earlier in the same proposal can be renamed, moved or removed later in it.
  - `insert` a transcript paragraph by block id, optionally from one substring to another, optionally naming the person (to settle a block id two transcripts share), placed like a move or `"stage": true` with optional category onto the shelf. The substrings are looked for in the original line first, then the English; the words are located in the clip's word timing like a highlighted selection. The picked fragment is highlighted on the new card; a whole-paragraph fallback says "(the whole paragraph: the words could not be narrowed)". Refusals: "this episode has no transcripts to insert from", "there is no paragraph ^<id> in this episode's transcripts", "^<id> is <A>'s, not <B>'s: name the block you meant", "^<id> is in more than one transcript (A and B), so it is not clear which was meant: say whose it is", "that block is a question, and questions are never in the edit" (always enforced, whatever the prompt says), "'<name>' has no word timings yet, so there is no span to cut - transcribe that clip first", "that paragraph has no words in it", "'<words>' is not in paragraph ^<id>. Its words are: '...'", the card-to-place-before/after-is-gone errors, and "Claude asked to shelve the new card under <x>, which is not a category name."
  - `keep` (used only by the shortening pass, never by the chat model): keep given word ranges of a card, split it at each boundary and shelve the dropped pieces under the pass's category.
- **Validation before anything is shown as applicable**: unknown op ("Claude asked for something this cut list cannot do (<op>). Nothing was changed."), an id not in the cut list ("Claude named a card that is not in the cut list (<uid>). Nothing was changed."), an insert with no block id ("Claude asked to bring in a paragraph without saying which one. Nothing was changed."), a heading with no title, and the per-op checks above.
- **Proposals, not edits**: each turn returns up to 4 proposals (an older reply with a bare `ops` list is read as one proposal titled from `say`). Each is validated and previewed in the exact words an apply would report; an invalid one is still shown with its reason. Nothing is applied. If the model said nothing and proposed nothing: "Claude answered with nothing to say and nothing to suggest. Try asking again in other words."
- **Applying a proposal (the editor's click)**: the ops run in order, one revision each; the first failure undoes every revision this proposal made, newest first, and reports whether the rollback succeeded. After an apply the sibling proposals become stale (visible, not clickable). Each op waits up to 20 seconds for its apply ("the edit was queued but the cut list did not come back: the file may be busy"); an edit already in progress: "an edit is already being applied - wait a moment". Refusals: "that message is not in this conversation any more", "that message made no suggestions to apply", "those are not the newest suggestions in this conversation. Ask again to bring them up to date.", "that suggestion is not in this message any more", "that suggestion has been applied already", the proposal's own invalid reason, "the cut list changed since these were suggested - ask again".
- **Undoing an applied proposal** (one gesture, as many undos as revisions it made): refused unless the file is still at the revision the apply left: "the cut list has been edited since then, so undoing that would take the later work with it. Use undo on the cards instead." Also "none of those suggestions has been applied, so there is nothing to undo", "that one has been undone already", "that one changed nothing, so there is nothing to undo".
- **Other refusals for a message**: "type what you want changed"; "the edit chat needs claude: <why>"; "the cut list changed under you - the page has reloaded, ask again" (the page's version is out of date); "Claude is still working on the last message" (one message at a time); "Claude answered with <type> instead of an instruction, so nothing was changed"; a lost conversation twice: "the Claude session was lost twice running: give it a moment and retry"; "the Claude session could not be opened: the provider refused the id twice running".
- **Why a turn was slow** (shown as "opened a new conversation: ..."): "the first message of the session reads the transcripts and the cut list"; "the transcripts changed since the last message, so they and the cut list were read again"; "the house style changed since the last message, so it and the cut list were read again"; "the conversation had gone cold (over an hour), so the cut list was read again"; "the conversation could not be dated, so the cut list was read again"; "the Claude session was lost (new machine or a rebuilt container), so the cut list went in again".
- **New conversation button**: a fresh conversation (the old id is never reused); the visible history is kept and gets a "new conversation" line.
- **Panel state**: whether a cut list is open (and why not), Claude availability, project file name, the model (id, slug, label) and the three choices, revision, version, the conversation (id, turns, warm, seconds since the last turn, provider), the corpus (documents, interviewees, clips, characters, parts, short hash, whether a custom style file is in use, whether this conversation holds the current corpus), and the history.

## Auto-shortening ("make it twelve minutes")
(source: shorten.py, config.py, chat_edit.py)

Reachability: the editor's shorten bridge subclasses this module's shortener over its own data and reuses its target parsing, sentence finding, card rendering, prompts, budget checking and arithmetic, and word-range checks. Which of the workflow steps below (assemble, accept, dismiss, accept-all, scores, knapsack) the editor drives through this code rather than its own could not be settled from this part (see Could not determine).

- **What a shortening is**: a set of removals, never a rewrite. It never reorders, never inserts, never changes a word. Every removal, once accepted, is a move onto the shelf under the pass's own category, named `shortened <target> <date>` (for example "shortened 12:00 2026-09-11"), so it stays in the file, playable and restorable. Nothing is deleted.
- **Refusals shared by every step**: "open a cut list first - the chat edits a .cut.md, not a live timeline"; "this cut list is open read only, so nothing can be changed in it"; "shortening needs claude: <why>". Every step answers a sentence rather than failing.
- **Target**: a number of seconds, or text: `720`, `12:00`, `1:02:30`, `12m`, `12 min`, `12 minutes`, `720s` (a bare number is seconds); zero or negative is not a target. Or a percentage of the current length to keep. Lengths are shown as `m:ss`, or `h:mm:ss` past an hour.
  - "say how long it should be: a length like 12:00, or a percentage of what it runs now"; "this cut already runs <now>, which is inside <target> - there is nothing to shorten"; "this cut list has no section headings, so there is no structure to budget. Add headings first, or ask the chat to cut it down in words."
- **Scope**: the editor may choose which sections the pass may touch; the target and current length then refer to those sections only, the model is told the other sections are outside the plan, and the turn reads "shorten to <t> (N of M sections)". None of the chosen sections present: "none of the chosen sections is in this cut list any more - reload the page and choose again".
- **Steer**: free text from the editor, passed as "THE EDITOR ALSO SAYS: ...".
- **Pins** per section: keep, drop or free. Pinned sections are shown to the model as "[PINNED KEEP]" / "[PINNED DROP]" and a pin always overrides the model's plan (the row's reason becomes "pinned KEEP by the editor" / "pinned DROP by the editor"). Removing a pin restores the model's own plan for that section.
- **Pass 1, structure** (on the edit chat's retained conversation, 600 seconds): the model is given the target, current length, how much must go, the rubric, and a table of sections with the server's own card counts and lengths, and returns per section `keep`, `thin` (to about N seconds) or `drop`, with a reason, plus a two-or-three-sentence note to the editor. Checking:
  - A section the model left out is kept whole ("Claude said nothing about this section, so it is kept whole"); a row for a section that does not exist is ignored.
  - A `thin` with no number, or a number not below the section's length, becomes `keep` ("the thinning target did not make sense").
  - Where the plan lands is the server's own sum (dropped sections count 0, thinned ones their target, kept ones their length), never the model's arithmetic.
  - A non-object answer: "Claude answered with <type> instead of a budget, so nothing was planned".
  - The pass is recorded as a turn of the edit chat ("shorten to <t>") holding the budget, target, current length, landing length, category, steer, pins, scope, the page's parallel width (4) and the tolerance (10%).
- **Editing the budget table**: the editor's edited plans are taken as written and re-summed; pins posted with the table win.
- **Pass 2, the words of one section** (one call per section, NOT on the conversation: the call carries only that section's cards, 600 seconds; the page may have up to 4 sections in flight, run one at a time on the server):
  - `keep` sections: nothing ("kept whole"). Sections with no cards: nothing.
  - `drop` sections: every card is removed except cards carrying a note; the heading stays, empty ("section dropped; its heading stays, empty; N card(s) kept for its note").
  - `thin` sections: each card with word timing is shown with one line per sentence and every word numbered `⟨n⟩word`; a sentence ends at `. ? ! …` or `。？！`, or at a silence over 0.7 seconds between words (marked with `|`). A card with a note is marked "(this card is protected)"; highlighted words are listed. Cards without word timing are left whole ("no word timing in this section, so nothing was cut in it" when none have it). The model is also told pass 1's reason for this section.
  - The model returns `drop` (whole card) or `keep` (word ranges to keep, each with `from`, `to`, `head` and `tail`, the first and last two or three words copied) ops with a reason and a kind (restate, detail, setup, scene, second example, fluff).
- **Rules enforced on the server for every op, whatever the model says** (a refused op costs only itself; the section's note says "N op(s) refused: ..." with the first three reasons):
  - op must be drop or keep; the card must be in the section; one op per card;
  - a card with a note is never removed ("[uid] carries a note, and a card the editor has written on is never removed");
  - every removal needs a reason ("... would be removed with no reason, and a removal without a reason is refused");
  - the last card of a section is never dropped unless the whole section is ("... a section keeps its last card unless the whole section is dropped (the cliffhanger rule)");
  - a keep needs ranges ("... is a keep with no ranges. To remove the whole card, say {"op": "drop"}."), whole word indices inside the card, `head` and `tail` present and at most 6 words each;
  - index and text must agree: the copied words must spell the card's own words at that end (ignoring case, spacing and punctuation), over a window of up to 12 tokens; if they spell the words at exactly one shift of up to 3 tokens either way, that end is moved to match (logged); otherwise refused "the index and the text disagree: head says "...", but words a to b of that card are "...". Nothing is guessed - say which one you meant.";
  - ranges must start at a sentence start and end at a sentence end unless the op says `mid_sentence: true` with a `splice_reason` (a mid-sentence flag with no reason is refused);
  - ranges in order and not overlapping; a keep that keeps the whole card is not a removal.
- **Pass 3, read-back** (one call per section, not on the conversation): every card cut inside is shown as its kept words with `⟨|⟩` at each seam, and the model says per card "ok" or "fix" with new ranges. A fix is checked by the same rules; a fix that does not validate keeps the card whole ("kept whole: the splice did not read"). If the read-back call fails, the cuts stand and are marked "unchecked".
- **The rubric** (CHAT_SHORTEN_RUBRIC; replaceable per episode by `<root>\Script Docs\shorten-style.md`, empty or unreadable falls back): keep, in order of stubbornness, the sentence a paragraph walks towards, concrete details, turns, first mentions later cards depend on, editor-highlighted spans, a section's summary card and its last card; cut first restatement, scene-setting the picture covers, the second of two examples, throat-clearing, and cards in a "maybe" colour; never remove a noted card, a section's last card, or a card another kept card refers back to; every removal has a one-clause reason in the editor's terms. Changing this file opens a new chat conversation.
- **Suggestions, one per removal**: nothing is removed by the pass. Each removed card or removed piece becomes its own suggestion with a title ("drop: <reason>", "splice: <reason>" or "drop the section: <reason>"), the reason, the kind, the seconds it saves, the words, the person, the section, where in the clip it came from (clip, media id, start and end seconds) and which card it follows.
  - Each suggestion is re-resolved against the cut as it stands every time (from the clip seconds it recorded, matched within 0.05 seconds, words within 0.02 seconds), so accepting one does not make the others stale. One that can no longer be made becomes "invalid" with its reason, e.g. 'the words "..." are not one card in this cut any more, so this suggestion cannot be made. Dismiss it, or ask for the pass again.', "that removal does not say where in the clip it came from, so it cannot be made now", "[uid] has no word timing any more, so there is nothing in it to cut on", 'the words "..." are not in [uid] any more'.
  - States: pending, accepted, dismissed, invalid. Accepting one applies it as an edit-chat proposal (its own revision and its own undo): a whole card is staged onto the shelf; a piece of a card is split out and staged. Refusals: "that suggestion is not part of this shortening any more", "that one has been accepted already", "that one was dismissed: put it back on the table before accepting it".
  - Dismissing keeps it on the record, dimmed; dismissing again restores it. An accepted one cannot be dismissed ("that one has been accepted already: undo it to put the words back in the cut").
  - Undoing an accepted suggestion makes it pending again.
  - **Take every suggestion**: all pending suggestions in one proposal and one undo, grouped per card (several pieces of one card become one cut keeping what all of them leave). "there is no suggestion left to take: every one has been accepted or dismissed"; "none of those suggestions can be made to this cut list any more".
- **Lengths shown**: what the cut runs now, where it lands with the accepted suggestions only, and where it would land if every pending one were taken. The summary line reads "N suggestion(s), <length> if you take them all", plus ", asked for <target>" when that is more than 10% (and at least 1 second) away from the target.
- **The whole review** lives on the edit chat's turn record (`<name>.chat.json`) so a reload, a second window or the phone see the same review; writes to it are serialised.
- **Plan C, a slider** (scores):
  - Once per cut list, the model scores every card from 0 ("nobody would miss it") to 1 ("the cut is not this cut without it"), with a kind (turn, detail, restate, setup, scene, fluff, ...), the cards it depends on and a reason; on the chat conversation, 900 seconds. Saved to `<name>.shorten-scores.json` beside the cut list with a hash of each card's words. "there are no cards to score"; "the scores could not be saved: <message>".
  - Given a target, the slider instantly (no model call) proposes dropping the lowest-scored cards (longest first among equal scores) until the target is reached, never a card with a note, a section's last card, or a card a remaining card depends on; a card unscored or whose words changed since scoring stays. "say the length to land on, like 12:00"; "this cut list has no scores yet - build them once and the target becomes a slider". It applies nothing and also returns a keep score per remaining card for a heat display.

## Command-line maintenance tools
(source: make_lite_audio.py, refresh_cuts.py, recolour_sections.py)

All three are run as `pipeline.py` subcommands (`make-lite-audio`, `refresh-cuts`, `recolour-sections`). `refresh_cuts` is also used by the conform code covered by another section.

- **make-lite-audio** `--root <episode>` [`--dry-run`] [`--force`]: makes the 40 kbit/s mono Opus copy (`<root>\Script Docs\remote_audio\<clip>.ogg`) of every `.wav` under `<root>\Interviewees\` (any depth, skipping folders named `legacy`), with the same recipe as the server. A copy is made only if missing or older than its WAV, unless `--force`. Dry run lists "would be made". Writes to its own temporary name (`.tmp-cli.ogg`) so a server making the same copy cannot collide. Per-file line "ok <MB> -> <MB> in Ns" or "FAILED ffmpeg failed: ..."; summary "N made, N already up to date, N failed" (prefixed "DRY RUN: "). Exit 2 with "no Interviewees\*\*.wav under <root>" or "no ffmpeg on PATH"; exit 1 if any failed. 60 minute limit per file. Waveform peaks are not made here.
- **refresh-cuts** `--root <episode>` [`--dry-run`]: for every `<root>\Script Docs\Cuts\*.cut.md`, renames each clip to its corpus folder's real stem (found by exact name, case-insensitively, or by `[<id>]` tag) and sets each clip's frame rate to the rate recorded in its `_words.json` (when it differs by more than 0.005). Cut times are never touched. Writes a new revision through the cut-list saver. Prints renames (first 4) and rate fixes (first 6), clips not in the corpus, "already true to the corpus" or "N file(s) updated"/"would change". Exit 2 with "no Cuts folder under <root>".
- **recolour-sections** `--root <episode>` or `--file <cut.md>` (repeatable) [`--apply`] [`--all`]: gives every in-cut section heading the default colour rotation (the nth section gets the nth colour of the rotation). Only Blue headings are changed unless `--all`. Dry run by default ("re-run with --apply to write them"); nothing but heading colours changes; writes a new revision. Exit 2 with "no Cuts folder under <root>" or "nothing to do: give --root or --file".

## Settings, environment variables and fixed numbers
(source: config.py, claude.py, library_engine.py, fleet_jobs.py, models.py)

- **Environment variables read by this part**:
  - `CARDS_DATA`: the engine's data folder (mirror, pick file, keys file, paragraph-index cache, search timings, library backups). Default: the MulticamPipeline folder; `/data` in the container.
  - `CARDS_DB_HOST`, `CARDS_DB_NAME`: where the Resolve project library is, for a server that has not heard from a Resolve machine. Default empty.
  - `CARDS_DB_WRITE_ALLOW`: library names this server may write directly. Default empty (write nothing).
  - `CARDS_DB_BACKUPS`: where row backups go before a write. Default `library_backups` under the data folder.
  - `CARDS_MEDIA_MAP`: path translation pairs `<Resolve machine prefix>=<local prefix>;...`. Default empty (only stage-2 WAVs play).
  - `CARDS_FLEET_URL`, `CARDS_FLEET_USER`, `CARDS_FLEET_PASSWORD`, `CARDS_FLEET_ROOTS`: the CC Sync fleet. Default empty (off).
  - `CARDS_CHAT_MODEL`: pins the edit chat's model for the whole server. Default unset (Fable).
  - `CARDS_CLAUDE_OAUTH_TOKEN`, `CARDS_ANTHROPIC_API_KEY`: the credential handed to the Claude CLI (see the CLI section).
  - `CLAUDE_BIN`: the Claude program. Default `claude` on PATH.
  - `AUTOHOTKEY`: the AutoHotkey v2 program for keystrokes.
  - `LOCALAPPDATA`: used to find AutoHotkey.
- Each of the CARDS_ database, media-map and fleet variables is the default for a matching command-line flag (`--db-host`, `--db-name`, `--db-write-allow`, `--media-map`, `--fleet-url`, `--fleet-user`, `--fleet-password`, `--fleet-roots`), parsed by the server covered by another section.
- **Fixed defaults**: default episode root `X:\Vault\2026\FF5\Animals`; default media-pool bin "Multicams"; house frame rate 29.97 drop-frame (re-exported from the canvas code); `cards_ui.json` for the last root.
- **Numbers used by the Resolve and agent halves (defined here, behaviour covered by another section)**: full timeline sweep every 1.0 s; playhead read every 0.1 s; whole media-pool name walk at most every 120 s; 20 undo snapshots; agent long-poll 25 s, agent counted away after 40 s of silence, an uncollected edit failed after 120 s, agent heartbeat at least every 5 s; 40 cuts per append call; last good state mirrored to `cards_mirror.json`, written at most every 3 s; `cards_pick.json` (which library/project/timeline is shown when not following the agent); `cards_lane_keys.json` (the last keyboard preset an agent pushed); library re-read every 2.0 s; 60 s for Resolve to save and close a project before a direct write, 120 s to reopen, a held agent reopens by itself after 300 s.
- **Numbers used by this part** (each also given in its feature above): gaps under 2 frames ignored; stack break at a 3.0 s source jump and at 90 s length; 12 frames of insert handles; 8 characters of slack for highlighted-paragraph matching; translation 50 parts / 20,000 characters per call, 3 calls at once, 15 s context, copy check 20/60 characters, 2 s pad, 50%; Google pacing 1 s, 3 s first backoff, 30 s ceiling, 10% decay; one-transcript semantic search 120,000 characters per piece; corpus search at most 20 results; search 5 results by default, 1 to 100 allowed, page choices 5/10/20/50, 600 s per question, 900 s per corpus part, warm 3600 s, estimates 60/25/5 s, last 6 timings kept, finished searches kept 3600 s and at most 12; splices at most 3 of 2 to 6 parts; chat 600/900 s, warm 3600 s, 50 history turns, 4 proposals; shortening 4 sections in flight, 10% tolerance, 0.7 s sentence gap; montage 900 s per part and per turn.
- **Process setup on import**: the MulticamPipeline folder, the sibling `resolve-left-hand-keys` folder and the `Launcher` folder are put on the import path (for the shared theme and the Resolve keymap reader); standard output is re-wrapped as UTF-8, line by line, or replaced by a null stream when there is none (a windowed host such as the CC Sync tray), so printing never stops the engine loading.

## Not code: the package description
(source: __init__.py)

- The file contains only a long description and no executable code. It describes the retired page and server (dragging cards to reorder Resolve through keystrokes, trim mode, offcuts banking, the keyboard map, the two-machine split, the command lines `python reorder_web.py ...`). None of it is behaviour of this part; see the claims list.

## Looks redundant or overlapping

- Four separate Claude searches over transcripts: the per-clip semantic search (`library_engine.start_semsearch`), the montage corpus search (`library_engine._corpus_worker`), the episode-wide transcript search (`transcript_search.py`, concept and literal modes), and the edit chat's own reading of the same transcripts. The first two are only reachable from the retired page.
- The "open a conversation with the corpus in parts, answer ok, rules on the last part, re-open once if lost" sequence is written four times: `montage.montage_open`, the fallback `library_engine.montage_open` (unreachable while `montage.py` exists), `transcript_search._open` and `chat_edit._open_corpus`.
- Separate retained conversations that each pay to read the same episode transcripts: one per search scope, per model and per mode, one per cut list for the chat (per model), one per cut list for the montage builder.
- Two gap-note placement routes in Resolve: the Fusion-clip route (used) and the playhead-title route (`gap_notes.place`, kept only for tests).
- The Opus copy of a WAV is made three ways: lazily on play (`lite_state`), in a background sweep whenever peaks are asked for (`lite_sweep`), and by the `make-lite-audio` command.
- English under a card comes from three tiers (Claude exact, Google draft, proportional paragraph slice), and the Google tier runs constantly in the background against free unkeyed endpoints with its own backoff machinery.
- Shortening has two independent mechanisms: the three-pass suggestion review (plan B) and the score-and-slider knapsack (plan C), plus the earlier per-section summary feature, which also asks Claude what each section says.
- Much of `library_engine.py` (plain-text search, selection matching, `locate`, the fleet intake, the media library) has been re-implemented in the rebuilt editor's own bridges and Node media service, leaving the engine copies reachable only from the retired page.
- Stores that serve only the retired page: the shared draft (`timeline_plans.json` plus its history log and named plans), per-device places (`timeline_place.json`) and browse bins (`cards_bins.json`); and the published-state versioning, delta ring and gzip cache.
- The whole offline package (manifest, prepare, replay plan, cut renaming) serves only the retired page.
- Fixed model choices that bypass the model picker: translation is always Haiku 4.5; per-clip semantic search, section summaries and the montage builder are always Sonnet 5.

## Claims the code does not back

- `__init__.py` describes behaviour (Resolve-driven drag reordering through AutoHotkey, offcuts banking, the keyboard map, `reorder_web.py` command lines) that is not in this file and belongs to the retired page; its claim that the Google draft is for "every Mandarin cut" is out of date (any non-English text is drafted, `translate.needs_translation`), and its "tones ignored" for pinyin is out of date (tone digits are honoured, `text._match_syllables`).
- `shorten.py`'s module description says "ONE PASS, ONE TURN, ONE UNDO. The section turns are gathered into ONE edit-chat proposal"; `assemble` makes one proposal per removal, and only "take every suggestion" is one proposal.
- `shorten.ShortenEditor.words` and the `CHAT_SHORTEN_PARALLEL` comment say section turns run "one at a time on the one conversation"; pass 2 and pass 3 use `lean_json`, which uses no conversation, and nothing in `words` serialises concurrent calls.
- `offline.py` says building a manifest is "a LOOK ONLY" and "must never queue thirty ffmpeg extractions"; `_peaks_path` calls `peaks_state`, which starts missing peaks decodes and, through `lite_sweep`, queues Opus copies of every clip with a WAV.
- The comment above the peaks code in `library_engine.py` says "50 peaks a second ... ~190 KB"; the rate is 200 per second (`PEAK_RATE`).
- `gap_notes.py`'s description says the agent route is `place` (a Text+ title with tracks locked); the engine calls `place_fusion`, and `place` is kept only for tests.
- `transcript_search.scope_sentence` says the scope "is a sentence in the QUERY turn and never a different corpus", and the module description says all transcripts go into the `all` conversation; each scope has its own conversation holding only its own transcripts (`_pick`, `corpus_for`).
- `config.py` says the 480p proxy is "Made only after every audio extraction is done"; the main worker takes audio first, but a proxy already encoding is not interrupted by newly queued audio (the second, audio-only worker takes that audio instead).
- `roots.saved_root` says the root is "Kept beside the script"; with a data folder it is kept there instead.
- `PlanStore`'s description says "every run is saved there first as 'last run -- <timeline>'"; nothing in `stores.py` does this.

## Could not determine

- Which steps of the shortening workflow (assemble, accept, dismiss, take-all, scores, slider) the rebuilt editor drives through `shorten.py`'s own methods and which it re-implements: its bridge subclasses `ShortenEditor`, and the editor's code is outside this part.
- Whether the retired page is still served anywhere (for example the CC Sync vendor build with the new editor turned off); if it is, every `UNREACHABLE` item above is live there, including the dashboard's pinned-job executor calling `fleet_execute`.
- What the edit chat's `delete` op does on the engine side (the ops reference tells the model it goes onto the shelf under its section's name); the request is handled by the cut-list engine covered by another section.
- How the CC Sync runner treats the `---INSTRUCTIONS---` marker and the `selection` argument; that code is in the CC Sync repository.
- Whether `ripple_keys.ahk` (used by the keystroke helper) behaves as the reply codes expect; it is not a Python file of this part.
