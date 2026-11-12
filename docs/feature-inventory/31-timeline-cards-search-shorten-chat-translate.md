# Timeline Cards: search across transcripts, auto-shorten, the edit chat, translation

Terms used throughout:

- **Episode**: one documentary episode folder in the vault (the shared project tree). A cut list's key looks like `<Episode>/Script Docs/Cuts/<name>.cut.md`; the episode is everything before `/Script Docs/`.
- **Cut list**: the ordered list of cards the editor is building. A **card** (also "cut") is one span of one clip, with its words.
- **Transcript**: a `<stem>_Transcript.md` file. Interview transcripts live under `<Episode>/Interviewees/<person>/`; corpus-clip transcripts (b-roll and other clips) live under `<Episode>/Clips/<stem>/`.
- **Paragraph ref** (`^ref`): the short identifier a transcript paragraph carries on a line starting with `^`.
- **Original line**: the paragraph's line in the language it was spoken (Mandarin, Russian, Ukrainian, and so on); the **gloss** is its English line.
- **Question paragraph**: a transcript paragraph marked as the interviewer's question (a line starting with `#`).
- **Shelf**: the holding area beside the cut list where cards can be staged without being in the cut.
- **Claude runner**: the editor server's single shared facility that runs the Claude command-line program. Every Claude call in these four features goes through it.
- **Python pool**: the editor server's shared Python worker process; three of these features (search, shorten, translate, and the chat's old-engine half) run their Python code in it.
- Every HTTP route below is served by the Timeline Cards editor server and is subject to that server's general sign-in (no sign-in, a password, or the trusted-proxy mode used when the CC Sync dashboard fronts it). None of these routes adds a per-user or per-role check of its own unless stated.

## Search across transcripts: the server routes
(source: features/search/server.ts, features/search/bridge.py; behaviour of the reused search module confirmed in multicam_pipeline/cards/transcript_search.py and cards/config.py)

- Common to every search route:
  - Each request names a cut list with `project=<key>`; the server derives the episode folder from the key and refuses to look outside the vault.
    - Missing or empty key: HTTP 400 `bad-key`, "which cut list? (project=)".
    - An episode folder that does not exist: refused with "there is no episode folder for this cut list".
  - The work runs in the shared Python pool, always in the same worker (so conversations and caches stay warm).
  - Pool failures map to HTTP codes: busy 503, timeout 504, cancelled 503, stopped 503, a refusal from the Python side 422, no Python 503, closed 503, unknown command 422, module missing 503, answer too large 502, not registered 503. The error code is `search-<code>`. Any other failure is HTTP 500 `search-internal`, "the search failed: ...".
  - Every call carries the Claude runner's status, so asking "can Claude run here" never starts a process.
  - The default timeout for a call into the pool is 120 s.
- Data folder:
  - Session records and timing history are written to a data folder, never into the vault. Default: environment variable `TC_SEARCH_DATA`, else `<system temp>/tc-editor-search`.
  - One sub-folder per episode, named by the first 16 hex digits of a SHA-1 of the episode path.
  - The data folder must be an absolute path, or every call is refused: "the search's data folder must be an absolute path".
  - At most 8 distinct data folders are held in memory; the oldest is dropped (its files stay on disk).
  - File `transcript-search-timings.json` in the data folder: measured durations of past searches, the last 6 of each kind (warm, cold) per conversation.
  - File `transcript-search.claude-session.json` (per scope, model and mode): the Claude conversation record (its id, turn count, and a hash of the transcripts it holds).
- `GET /api/search/scopes?project=&scope=&model=&mode=`: the scope list, the conversation status line, whether Claude is available, and the model list.
  - Scopes: "All interviews" (id `all`, count = number of interview transcripts); one row per interviewee (`person:<name>`, count = number of paragraphs in that person's interview transcripts); "All corpus clips" (`clips`, count = number of clip transcripts), shown only when the episode has any.
  - Models offered: sonnet, opus, fable, each with a display label.
  - The session line: whether this conversation is warm, its turn count, its age in seconds, its id and key, its mode, scope and model, the number of characters a cold search of this scope must read and the number for the whole episode, and the expected seconds for a warm and a cold search with where each estimate came from.
  - Timeout 60 s.
- `POST /api/search` (body `{project, query, scope, limit, model, mode, splices}`, body at most 64 KB): one Claude search, answered in the reply. Runs to the end even if the client goes away.
  - Body not a JSON object: HTTP 400 `bad-body`.
  - The query is cut to 2000 characters; scope and model to 500.
  - Overall timeout 40 minutes.
  - `limit`: clamped to 1 through 100; anything that is not a number (including true/false or nothing) becomes 5. Never refused.
  - `model`: normalised to one of sonnet, opus, fable; anything else becomes the default (sonnet).
  - `mode`: `literal` if the text is exactly "literal" (any case), else `concept`.
  - Empty query: answered `ok:false`, "type what you are looking for".
  - Claude not available: `ok:false`, "the transcript search needs claude: <why>".
  - Only one search runs at a time per episode:
    - The same question (same query, scope, model, limit, mode and splices) asked while it runs joins it and waits for its answer, marked `joined`. If the wait (600 s + 8 x 900 s) ends with no answer: "the same search is still running: its answer will be here when it lands".
    - A different question while one runs is refused: "a transcript search is already running: one question at a time keeps the conversation in order", with the running search's record attached.
  - Scope refusals: "this episode has no corpus clips to search"; "there is no interview transcript for <person> under this episode"; "no such search scope: <scope>"; and with no transcripts at all, "there are no transcripts under this episode yet: nothing to search".
  - One conversation per (episode, scope, model, mode). A conversation is warm when it has taken at least one turn, the transcripts it holds have not changed, and it was last used under 3600 s ago. A cold conversation first sends that scope's transcripts to Claude in parts of at most 100,000 characters each (one Claude turn per part, 900 s timeout per part, no extended thinking), then asks the question (600 s timeout).
  - If the conversation was cold, the answer carries a note saying why: "the first search of the session reads <thing>", "a transcript changed since the last search, so <thing> <is/are> read again", or "the conversation had gone cold (over an hour), so <thing> <is/are> read again".
  - If the Claude conversation is lost (for example a rebuilt container), the transcripts are read again once and the question asked again; the note says "the Claude session was lost (new machine or a rebuilt container), so the transcripts were read again". Lost twice: "the Claude session was lost twice running: give it a moment and retry". A conversation id refused twice when opening: "the Claude session could not be opened: the provider refused the id twice running".
  - Concept mode ("by meaning"): Claude names passages by paragraph ref with a reason; each named ref is checked against the transcripts and dropped if no such paragraph exists or it is outside the scope. The text shown is always the file's own paragraph, never Claude's words. Results stop at `limit`. `offered` reports how many rows Claude gave (capped at `limit`), so the page can say how many were dropped.
  - Literal mode ("closest wording"): searches the original-language lines only, never the English translation. Before Claude answers, an instant local pass finds the query's own words as typed (at least 2 letters or digits after folding) in the original lines of the scope; these "early" hits are shown while waiting and are added to the answer if Claude missed them, labelled "the words as typed".
    - Claude names short spans with a tier: exact, near, synonym, paraphrase. Each span is kept only if its text really is in that paragraph's original line (letters and digits only, case-folded, Traditional Chinese folded to Simplified). A span whose words equal the query is forced to "exact"; a span called exact whose words differ (in the same script) is demoted to "near"; an unknown tier becomes "paraphrase". Duplicates are dropped; results are sorted exact, near, synonym, paraphrase and capped at `limit`.
    - Each span is given clip seconds from the word timing when possible: "words" when timed words cover it, "paragraph" when only its paragraph can be placed, "none" when the transcript has no timing.
  - Splices (asked for when `splices` is true; the page always asks): suggestions of 2 to 6 fragments from different places that cut together into the idea or phrase. At most 3 splices. A splice is dropped whole if any fragment cannot be found in the words actually spoken. Each splice carries its total seconds when every fragment has timing, else none.
  - The answer carries a summary sentence from Claude, the results, the note, the mode, the elapsed seconds and the new session line.
  - Every result row is decorated with: the clip (media) name, the speaker as the cut list writes it (interview only), a reference to its transcript, and clip seconds. A row with no seconds of its own gets its paragraph's span from the word timing ("paragraph"), or none. A literal row on an original line also gets that line's language by script (zh, ru, uk, ru-uk).
  - A successful search's duration is recorded for future estimates.
- `GET /api/search/status?project=&job=`: the running search (whatever its scope and model), the searches that finished within the last 3600 s (at most 12, newest first, without their answers), and, when `job` names one, that job's full answer. Elapsed time is counted on the server. Running records include the early literal hits. Timeout 60 s.
- `POST /api/search/reset` (body `{project, scope, model, mode}`, at most 16 KB): starts THIS scope, model and mode's conversation over (a new conversation; the transcripts are sent again on the next search). Other scopes' conversations are untouched. Returns the new session line.
- `POST /api/search/find` (body `{project, q, scope, max, cards}`, at most 2 MB): plain-text search, no Claude.
  - Body not a JSON object: HTTP 400 `bad-body`.
  - `max` clamped to 1 through 200 (default 200); timeout 90 s.
  - Query parsing (from the old text module): text in quotes means exact case and whole word, no folding; otherwise case-insensitive, Simplified matches Traditional, and pinyin works for a mixed query (for example "chu1", "chuqu", "出qu").
  - Searches both the English and the original line of every paragraph of every transcript in the scope (`everything` covers interviews and clips). Each matching paragraph is one row with match spans for each language, its question flag, its ref, and its clip seconds when known.
  - Counts every matching paragraph (`total`) but returns at most `max`; `truncated` says so.
  - Also searches the open cut list's own card texts sent in `cards` (at most 2000 cards, ids cut to 64 characters, texts to 20,000), with the same rules; at most 200 matching cards returned.
  - An empty query returns nothing.
- `GET /api/search/doc?project=&uid=`: one transcript as paragraphs (original line, English line, question flag, language, clip seconds and whether they are approximate), with its file name, person, clip, kind, speaker and timing source ("words", "srt" or "none").
  - Missing uid: HTTP 400 `bad-uid`, "which transcript? (uid=)". Unknown uid: "that transcript is not in this episode".
- `GET /api/search/pin?project=&uid=&ref=&text=`: clip seconds for some words inside one paragraph (or the whole paragraph's original line when `text` is empty). Refusals: "that transcript is not in this episode"; "there is no paragraph ^<ref> in it".
- How a transcript is tied to a clip and timed (applies to every route):
  - An interview transcript's clip is found from the files beside it: a `<clip>_words.json` word-timing file or a `<clip>.srt` subtitle file (files ending `.whisper.srt` or `.resolve.srt` ignored). One candidate is the answer; several prefer `<person> Multicam`; none falls back to `<person> Multicam`.
  - A corpus clip transcript's clip is its folder name; its id is `clip:<stem>`.
  - Timing comes from the word file when there is one; with no word file, from the `.srt` cues (coarse, every span marked approximate); with both, the `.srt` places each paragraph and the words are matched inside it. No word file and no `.srt`: no timing.
  - A transcript in which the original line was not detected (for example Russian or Ukrainian) is re-read so the original line is found by any non-Latin script (Cyrillic, Greek, Arabic, Hebrew, Devanagari, Thai, CJK, kana, hangul) when at least 20% of a line's characters are in such a script.
  - The list of transcripts is looked at again at most every 2 s; a transcript asked for by name and not found triggers a fresh look at most every 0.25 s. Up to 600 parsed transcript folders and 24 word indexes are kept in memory per episode; the oldest go first.
  - The language of an original line is decided by script: Han characters mean zh; Cyrillic with letters only Ukrainian writes means uk, only Russian writes means ru; unclear Cyrillic is ru when 200 or more Cyrillic letters, else "ru-uk", and a paragraph's "ru-uk" takes the whole transcript's language when that is ru or uk.

## Search across transcripts: the search sheet
(source: features/search/client.ts, features/search/logic.ts, features/search/ops.ts, features/search/styles.ts, features/search/types.ts)

- Opening and closing:
  - Desktop header button "Transcripts" (search icon, shortcut hint "Ctrl Shift F", tooltip "Search every transcript of this episode"). When the shell provides toolbar slots, the button is drawn by the shell instead (same label, order 20).
  - Phone Find tab: a full-width button "Search the transcripts" added below the Find field.
  - Ctrl+Shift+F (Cmd+Shift+F on a Mac) toggles the sheet from anywhere, including while typing in a text field. Opening carries the words typed in the visible card-search box into the sheet's box.
  - Opening with words already in the box in "Exact words" mode runs the search at once.
  - The sheet is a centred dialog over a dark scrim on desktop (at most 980 px wide and 900 px tall); on screens up to 700 px wide it fills the screen.
  - Close: the X button (hint Esc), Esc, a click on the scrim, or the phone's back gesture (opening adds a browser history entry). Closing stops any playback and returns focus to where it was.
  - Esc while a transcript is open inside the sheet goes back to the results instead of closing.
  - Only one sheet exists per page; a second mount drives the first.
  - The header shows the episode's folder name.
- Search kinds (a three-way switch, remembered per device): "Exact words" (default), "By meaning", "Closest wording".
  - Changing the kind never asks Claude by itself. Switching to Exact words re-runs the plain search. Switching to a Claude kind shows an answer already kept for this exact question, else the line says "press Search to ask this by meaning" / "press Search to ask this for the closest wording".
  - The box placeholder changes per kind: "Words or a name; pinyin too (chu1, chuqu, 出qu); "quotes" for exact case" / "A question, as a sentence" / "The words you want someone to have said".
- Pickers:
  - "In" (which transcripts): All (labelled "All transcripts" in Exact words, "All interviews" in Claude kinds), each interviewee, "All corpus clips". Changing it re-runs Exact words; in Claude kinds it does not ask, shows a kept answer if any, else "press Search to ask this of <scope>". The scope resets to All when a different cut list's episode is opened.
  - "Results" (Claude kinds only): 5, 10, 20 or 50, default 5, remembered per device. Changing it re-asks the current question if an answer is on show.
  - "Model" (Claude kinds only): Sonnet (default), Opus, Fable, remembered per device. Changing it reloads the status line and, if an answer was on show, asks again (a model is a separate conversation).
  - "New conversation" button (Claude kinds only, tooltip "Start this scope's Claude conversation over: the next search reads its transcripts again"): resets the conversation for this scope, model and kind, forgets this scope's kept answers for that kind, and says "a new conversation: the next search reads <thing>".
- Search button: "Search", showing "Searching" while busy.
- Exact words behaviour:
  - Searches as you type, 250 ms after the last keystroke; a newer keystroke cancels an older answer.
  - Status line: "<n> match(es)", ", the first <k> shown" when truncated, " · <n> card(s) in this cut list", " · exact case, whole word" for a quoted query. Before typing: "Instant, in both languages. Simplified matches traditional."
  - Results: first "In this cut list (<n>)": matching cards of the open cut list and its shelf, with the match highlighted, numbered "#<position>" or "shelf", showing 4 and a "Show all <n>" / "Show fewer" toggle. Clicking one selects it, moves the playhead to its start if it is in the cut, and closes the sheet.
  - Then "In the transcripts (<total>)" with result cards. None found: "No transcript says that. Try fewer words, or search by meaning." Empty box: "Type to search every transcript of this episode, word for word. Results come in as you type."
- Claude kinds behaviour:
  - Status line: "<model> · by meaning|closest wording · warm, <n> turns in: it still remembers <thing> and your last questions", or "... cold: the first search reads <thing>, about <time>". The "thing" is "every transcript", "the corpus clips" or "<person>'s transcript".
  - Claude unavailable: the line says "Searching by meaning needs Claude on the server: <why or 'not installed'>" and Search shows the same as an error.
  - Asking the exact same question (same kind, scope, count, model, words) as an answer already kept shows the kept answer with "shown again, not asked again", without asking.
  - One search at a time: pressing Search with a different question while one is waiting says "one search at a time: ask this when the running one lands".
  - If the server is running someone else's search, the page adopts it and shows its progress: "another search was already running, so yours was not asked: its answer will show here".
  - The wait panel: "Searching [for the closest wording in] <scope> [(<model>)]: <query>", a progress bar and a line such as "reading every transcript, part 2 of 4, about 60 s (an estimate) · 34 s so far", "the transcripts are read, now asking", "finding the closest words said", "asking". Once elapsed exceeds 115% of the estimate: "taking longer than the <n> s estimate".
    - The bar is an estimate: linear to 85% at the estimated time, then easing toward 95%, never full until the answer lands. Redrawn every 250 ms.
    - The page asks the server for progress every 2 s while waiting and the sheet is open; the server's elapsed time wins over the device clock.
    - Literal mode shows "The words as typed, found already" with the early hits while waiting.
  - A search outlives the page: the waiting search is remembered on the device per episode for up to 1 hour; reopening the sheet (or reloading) picks it up from the server and shows its answer when it lands.
  - Network failure while waiting: the page keeps asking the server for the answer; if both fail: "the search did not answer: <why>". Search gone from the server: "the search that was running is not on the server any more (it restarted, or the answer is over an hour old): ask it again". Finished but answer missing: "the search finished, but its answer is no longer on the server: ask it again".
  - The answer: Claude's summary in a highlighted box; a count line "<n> passages" (or "spans" in literal mode), or "<n> of <offered> passages (the rest could not be found in the transcripts, so they are not shown)", plus " · the most this search asked for" when the count reached the limit. Numbered result cards "#1", "#2"...
  - Nothing found: "Nothing in these transcripts answers that." / literal: "Nothing said in these transcripts comes close to that."
  - The answer's note (why it was cold) or "the same question was already running: this is its answer" goes on the status line.
  - Splices section "Splices: pieces from different places, cut together in this order": each splice shows its reason, a "Play all, <n> s" button (only when every part is timed; toggles to "Stop") that plays the parts one after another, an "Insert all" button, and its numbered parts as result cards.
  - "Earlier questions": the last 40 Claude questions for this episode on this device (newest first; the same question, scope and kind is listed once), each showing the question, a "closest wording" chip when literal, its scope and how long ago ("just now", "<n> min ago", "<n> h ago", "<n> days ago"). Clicking one restores the count, model and kind it was asked with and asks it (a kept answer is shown without asking). "Clear" forgets the history and every kept answer for the episode. Empty: "Nothing asked yet. A question is a sentence, not keywords: "the moment they realised nobody was coming"."
  - Kept answers: up to 24 answers per episode, each at most 160,000 characters, stored on the device; when storage is full the oldest are dropped (up to 3 tries).
- A result card shows: the speaker (coloured by the speaker colour used in the cut list), the clip (or file) name and time (clip time "m:ss" or "h:mm:ss", or the transcript's own time stamp), "≈" when the time is approximate, a tier chip in literal mode (exact, near, synonym, paraphrase), a "question" chip for an interviewer question, the rank, the words (the matched span inside up to 60 characters of its paragraph either side, with highlights), the English gloss when the words are not English, Claude's reason in italics, and the paragraph ref "^<ref>".
  - "Play" (or "Play <n.n> s" when the span's own words are timed; "Stop" while playing): plays the span's audio from the clip on the server, pausing the editor's own playback, and stops at the span's end. Disabled with tooltip "This transcript has no timing to play from" when untimed. Audio missing: "There is no audio for <clip> on this server, so it cannot play here." Refused by the browser: "It would not play: <why>".
  - "Insert" (tooltip "Insert after the selected cut") or, for a question paragraph, "Stage it" (tooltip "An interviewer question never goes in the cut: it goes on the shelf").
  - "Open transcript": opens the whole transcript at that paragraph. Disabled with "This transcript belongs to no clip in this episode" when there is no tie.
  - Right-click a result (desktop), or touch-and-hold for 350 ms (cancelled by moving more than 10 px), also opens the transcript. The click that follows a hold is swallowed for 500 ms.
- Inserting a result:
  - Lands after the last selected card that is in the cut, else at the end of the cut; the message says "after cut <n>" or "at the end of the cut".
  - The new card carries the transcript's own words (the spoken line, then the English gloss on a second line when it differs), the clip, the start and end seconds, the speaker, the paragraph ref, and the question flag.
  - An interviewer question is staged on the shelf instead: "on the shelf (an interviewer question never goes in the cut)".
  - The inserted cards become the selection and the playhead moves to the first one's start (not for a staged question).
  - One undo step. Message: "Inserted after cut 3. Undo puts it back." / "Staged ..." / "Inserted the splice ...".
  - Refusals ("Not inserted: <why>."): "this transcript is not tied to a clip, so there is no media to cut from"; "this transcript has no word timing, so there is no span to cut"; "the words are too short to be a cut" (shorter than the editor's minimum card length); "a splice with an interviewer question in it cannot go in the cut"; the editor refusing the edit. No cut list open: "Open a cut list first: there is nothing to insert into."
- The transcript reader inside the sheet:
  - First offered to any other transcript view on the page; if one takes it, the sheet closes. Otherwise the sheet shows the transcript itself ("Opening the transcript…" while loading).
  - Header: "Back to results", the person, file name, paragraph count, and the timing kind: "word timing", "subtitle timing (approximate)", or "no timing: nothing here can play or be inserted".
  - Every paragraph with its original and English lines, its own Play/Stop, Insert or Stage it, a "question" chip, its time ("≈" when approximate) and its ref. The paragraph that was asked for is outlined and scrolled to the middle.
  - No tie: "That transcript belongs to no clip in this episode, so there is nowhere to jump to."
- Keyboard inside the sheet (keys pressed here never reach the editor's own shortcuts):
  - Enter in the box: if the results on show are for this exact text, steps to the next result (Shift+Enter: previous); otherwise searches.
  - Down arrow in the box: to the first result.
  - On the results: A previous result, S next result (by physical key position, so they work on Russian or Ukrainian layouts; not with Ctrl, Cmd or Alt; not while a transcript is open in the sheet).
  - Q: open the transcript of the result in hand.
  - Up/Down arrows: previous/next result; Up from the first result returns to the box.
  - Enter on a result: next result (Shift+Enter previous). Space: play or stop the result in hand ("That passage has no timing here, so there is nothing to play." when untimed). I: insert (or stage) it.
  - Tab and Shift+Tab cycle within the sheet.
  - If focus fell outside the sheet while it is open, Enter and Space still walk and play the results.
  - The result in hand keeps focus across redraws.
- Game controller (through the editor's controller mapping): step through results, open the one in hand, play/stop it, B goes back from the transcript then closes the sheet, focus the search box (filling it with the word from the transcript's find box when empty), read the box text, run the query, leave the box.
- Remembered on the device: result count, model, search kind (keys `tc_search_limit`, `tc_search_model`, `tc_search_kind`); per episode: history (`tc_search_hist:<episode>`), kept answers (`tc_search_ans:<episode>`), the waiting search (`tc_search_pend:<episode>`).
- Touch screens: pickers and buttons are at least 44 px tall.
- Server not running the search: "the transcript search is not running on this server".

## Auto-shorten: the server routes
(source: features/shorten/server.ts, features/shorten/bridge.py, features/shorten/ops.ts, features/shorten/types.ts; reused rules from multicam_pipeline/cards/shorten.py and cards/config.py)

Terms: a **pass** (also "review") is one shortening attempt on one cut list. A **section** is the run of cards under one `§` section heading in the cut list. A **suggestion** is one proposed removal (a whole card, a whole section, or a span of words cut out of a card, called a splice). The **budget** is the per-section plan: keep, thin (shorten to a length) or drop.

- General rules:
  - The server never edits the cut list. It plans, proposes and records; edits happen only in the editor when a person accepts a suggestion.
  - All routes answer `{ok:true, shorten:<pass>}` or `{ok:false, error:<sentence>}`. Input-shape refusals (HTTP 4xx, code `bad-request`) are returned as `ok:false` with the sentence; an over-size body or bad JSON stays a real HTTP error. Any other failure is logged and returned as `ok:false` with its message, never a crash trace.
  - Request bodies at most 8 MB. At most 20,000 cards per request; card texts cut to 20,000 characters, notes to 4000, up to 50 highlights of up to 2000 characters each.
  - The cut list key must be a vault-relative path ending `.cut.md` with no empty, `.`, `..` or hidden segments, no leading slash, no characters a path cannot have, at most 1024 characters, and must not leave the vault.
  - A card must have `in_s` >= 0 and `out_s` > `in_s` ("a card needs in_s < out_s") and an id of `c` plus 7 lowercase letters or digits ("a card id is c + 7 characters").
  - Model: environment variable `TC_SHORTEN_MODEL`, default `opus`. Every model call is a single stand-alone turn (no conversation), with extended thinking on, answered as JSON in the reply, through the shared Claude runner.
  - The Python helper runs at most 4 calls at once for this feature, 60 s per call. Environment variable `TC_PY_ROOT` overrides where the reused Python package is found.
  - If the page that asked closes or reloads before Claude answers, the call is stopped: "stopped: the page that asked went away before Claude answered, so nothing was changed" (code `cancelled`). A stopped section keeps whatever it had.
  - The style rubric ("what counts as fluff") is the episode's `<Episode>/Script Docs/shorten-style.md` when present and non-empty, else the built-in default.
  - Where things are kept: `<cut list folder>/.tcards/<cut list name>/shorten.json` (the passes, at most the last 8 kept) and `<same folder>/shorten-scores.json` (the scores), under the working-copy root, or the vault when there is no separate working copy. On a read-only vault with no working copy, both are kept in memory only and nothing is written.
  - Word timing is looked for as `<clip>_words.json` anywhere up to 4 folder levels under the episode (hidden folders skipped). A file not found is looked for again after 30 s; up to 512 lookups and 16 parsed word files are kept in memory.
- `GET /api/shorten/state?key=`: the newest still-open pass for the cut list, or null.
- `POST /api/shorten/start` (body `{key, target, steer, pins, scoped, every, now_s, sections}`): pass 1, the section budget.
  - Only sections with a title count. None: "this cut list has no section headings, so there is no structure to budget. Add headings first, or ask the chat to cut it down in words."
  - Current length: the sum of the chosen sections when `scoped`, else the `now_s` sent (the whole timeline, gaps included) or the sections' sum.
  - Target: a number of seconds, or text: `12:00`, `1:02:30`, `720`, `12m`, `12 min`, `90s`, or `60%` (the percentage to keep, more than 0 and under 100). Unreadable: "say how long it should be: a length like 12:00, or a percentage of what it runs now". Not shorter than now: "this cut already runs <now>, which is inside <target> - there is nothing to shorten".
  - Pins: per section title, `keep`, `drop` or `free`. Steer: free text up to 2000 characters, passed to Claude as "THE EDITOR ALSO SAYS".
  - One plan at a time per cut list: "a shortening is already being planned for this cut list - wait for it".
  - Claude is sent: the target, now, the difference, the scope note when only some sections are in play ("ONLY THESE SECTIONS ARE IN PLAY..."), pinned sections, the rubric, one line per section (title, cards, length, pin), and one line per card (id, speaker, seconds, its words cut to 160 characters, "NOTE (protected)" when it has a note).
  - Claude's budget is checked against the real sections with the pins winning, and summed. If Claude gives no answer: "Claude gave no answer, so nothing was planned".
  - The new pass replaces (closes) any open pass on that cut list; what earlier passes put on the shelf stays there.
  - The pass records: target, now, the budget rows (plan, thin-to length, reason, pin, Claude's original plan for each, where the section landed), the shelf category it will file removals under (`shortened <target> <YYYY-MM-DD>`), the parallel limit (4) and the tolerance (10%), Claude's summary sentence, and timestamps.
- `POST /api/shorten/budget` (body `{key, turn, budget}`): the editor's edited table. The posted row's pin wins (`free` removes a pin). Re-checked and re-summed; each row keeps its earlier landed length, error and note. The pass returns to the budget phase.
  - Unknown pass: "that shortening is not on this cut list any more".
- `POST /api/shorten/words` (body `{key, turn, section, cards, order, clips}`): passes 2 and 3 for one section, using the cards as the cut has them now.
  - Unknown section: "there is no section called "<title>" in this budget". The same section already being cut: ""<title>" is already being cut - wait for it".
  - A section planned `keep` or `drop` needs no model: a drop produces section-removal suggestions directly.
  - A `thin` section: the words of each card are read from its clip's word-timing file (offset by the clip's start timecode). No timing for any card: nothing is cut, note "no word timing in this section, so nothing was cut in it".
  - Pass 2: Claude proposes which words to keep in each card. The proposal is checked against fixed rules (from the reused module; see "Could not determine"); each refused proposal is kept with its sentence, and the note says "<n> op(s) refused: <first three reasons>".
  - Pass 3 (read-back): when any card was cut inside, Claude reads the resulting joins back. A verdict of ok keeps the cut, a valid fix replaces it, an invalid fix keeps the card whole. If the read-back call itself fails, the splices stay and are marked "unchecked" with the failure.
  - The resulting removals become suggestions, each with: an id, the card it came from, speaker, section, the card it followed, its clip and clip seconds, duration, kind (restate, detail, set-up, scene-setting, second example, run-up and fluff, section dropped, spliced), reason, the words that go, whether it is a whole card, whether it cuts mid-sentence and why, its shelf category, a title ("drop: <reason>", "splice: <reason>", "drop the section: <reason>", reason cut to 60 characters), and, for a splice, the source card's words with timings.
  - A section that fails is left untouched and its row shows the error; the response is `ok:false` with the error and the updated pass.
  - Decisions already made on suggestions survive a re-run of the section; accepted removals from an earlier run stay on the record.
  - The pass's phase moves: budget, then words (some sections done), preview (every non-keep section done), applied (any suggestion accepted). Summary sentence: "<n> suggestion(s), <m:ss> if you take them all", or "nothing left to decide: the cut runs <m:ss>", plus ", asked for <target>" when the offer lands more than max(1 s, 10% of the target) away from it.
  - Two lengths are kept: what the cut runs with accepted removals out, and what it would run if every pending one were also taken.
- `POST /api/shorten/dismiss` (body `{key, turn, rid, dismissed}`): dismiss (default) or un-dismiss one suggestion; it stays on the record. Refused for an accepted one: "that one has been accepted already: undo it to put the words back in the cut" (HTTP 409 code `refused`, returned as `ok:false`). Unknown suggestion: "that suggestion is not part of this shortening any more".
- `POST /api/shorten/mark` (body `{key, turn, rid, status, uid, after, error}`): the editor reports a decision.
  - `status` must be accepted, pending or invalid ("status is accepted, pending or invalid").
  - Accepted must name the shelf card it created ("an accepted suggestion names the cut it put on the shelf") and records the card it followed.
  - Invalid records why (up to 600 characters; default "this suggestion cannot be made to the cut list as it is"); an accepted one is never made invalid.
  - Pending clears the error (used for put-back and for a suggestion that became possible again).
- `POST /api/shorten/close` (body `{key, turn}`): closes the review. The shelf keeps what was taken.
- `GET /api/shorten/scores?key=`: the cut list's card scores, or null.
- `POST /api/shorten/scores` (body `{key, cards}`): builds card scores with ONE Claude call; cuts nothing.
  - More than 3000 cards: "this cut list has more than 3000 cards, more than one scoring call can read; shorten it a section at a time". No cards: "there are no cards to score". Already building: "the scores for this cut list are already being built - wait for them".
  - Claude reads one line per card (id, speaker, seconds, words cut to 600 characters, its note) under the rubric and returns per card: a keep score from 0 (nobody would miss it) to 1 (keep firmly), a kind, the cards it depends on, a reason (cut to 300 characters).
  - Rows for unknown cards or without a number are dropped; scores clamped to 0..1; unknown kinds become fluff; at most 20 dependencies, only on existing cards. Each row remembers a fingerprint of the card's words, so a card whose words changed later is treated as unscored.
  - None scored: "Claude scored none of the cards, so nothing was saved and the slider still needs them". Saved whole (replacing any earlier scores); the last 32 cut lists' scores are kept in memory.
- Python helper commands present but not used by any route: `sentences` (where a card's sentences break, a 0.7 s silence counting as a break) and `parse_target`. DORMANT (reachable only from tests).

## Auto-shorten: the panel
(source: features/shorten/client.ts, features/shorten/ops.ts, features/shorten/audition.ts, features/shorten/styles.css)

- Opening: toolbar button "Shorten" (tooltip "Shorten the cut to a length, section by section", hint "Alt H", shown pressed while open), the Alt+H key, or "Open in the panel" from a marker. A column at the right between the header and the lane on desktop (320 to 460 px wide); full screen on screens up to 700 px wide or 500 px tall. Opening refreshes the review from the server and focuses the panel. Close: its X button, the toolbar button, Alt+H, or Esc; focus returns where it was.
- With no review open:
  - "Target length" box (hint "12:00, 12m or 60%") and a "Plan the cut" button ("Planning…" while busy). Unreadable target: "a target is a length like 12:00, minutes (12m) or a percentage to keep (60%)".
  - "Or drag to a length" slider: 30% to 100% of the cut's current length in whole percent; the line under it reads "<m:ss> · <pct>% of <now>". Dragging writes the length into the target box. Before it is touched it sits at the typed target, or 70%. A repaint never interrupts a drag.
  - Under it, without scores: "Build the scores once and this slider shows what would go at any length, on the lane, as you drag. One long Claude call reads every card; it cuts nothing." and a "Build the scores" button ("Scoring…" while busy; the line says "Scoring every card once. This is the long call, and it cuts nothing."). Done: "<n> cards scored: drag the slider and the lane shows what would go at that length".
  - With scores: a preview line ("Drag the slider: the lane shows what would go at each length, from the scores", or "<n> card(s) would go · lands <m:ss> · from the scores, not a pass", or "nothing the scores would cut · ..."), "<n> of <m> cards changed since they were scored / have no score; they stay at every length. Score again to count them.", "Ask for the real cut at <m:ss>" (runs pass 1 at the slider's length), "Clear the preview" (when the preview removes anything), "Score again", and "A guess from the scores, drawn in gold on the lane. The real pass reads the words and suggests; nothing is cut until you accept."
  - The score preview picks whole cards to drop, lowest keep score first (ties: longer card first), until the length reaches the target. It never drops a card with a note, the last card of a section, a card that a surviving card depends on, or a card without a current score. The preview is recomputed when the cut changes. It is a preview only: it cannot be accepted.
  - "Steer (optional)" box (placeholder "keep everything with the daughter").
  - Section scope: "Shorten: All <n> sections" / "<k> of <n> sections" opens a tick list of the titled sections with their lengths; "None ticked is the whole cut."
  - Hint: "Say how long the cut should run. Claude plans a budget per section first; nothing is cut until you say the plan looks right, and nothing leaves the cut until you accept it."
- Status line: "target <m:ss> · now <m:ss> · −<diff>" then, during a review, "lands <m:ss>" and "<m:ss> if you take them all", or in the budget phase "the plan comes to <m:ss>". Messages appear after it in gold. Claude's summary sentence is shown under it.
- With a review open the target form folds to one line ("target <m:ss>", the steer in quotes, "Change the plan"); unfolded it shows "Plan again" and "Keep this plan". The header shows the phase (budget, words, preview, applied).
- The next step box:
  - Budget phase: "Looks right: cut the words" and "Pin a section Keep or Drop and the plan is worked out around it. Nothing has moved yet."
  - While cutting: "Cutting the words: <r> running · <w> waiting · <d> done · <f> failed" with a progress bar. Up to 4 sections are cut at once; when all finish and there are suggestions, the Suggestions tab opens.
  - After: "<n> suggestion(s) waiting on you" / "Nothing left to decide" / "Every suggestion has been dismissed"; "Open one to read what goes and why, then take it or leave it. Each is its own change with its own undo." plus "<n> can no longer be placed."; buttons "Review the suggestions", "Cut the other <n> section(s)", "Accept all <n>", "Close the review".
  - Closing the review: "the review is closed; everything you took is on the shelf under its pass".
- Tabs: Sections, Suggestions (with a count of pending ones), Read.
- Sections tab: "One bar a section: the pale part is how long it was, the bright part how long it will be. Gold lost a lot of itself; an empty outline is dropped whole." Per section: title, card count, a before/after bar (gold when it loses 45% or more, a dashed outline when dropped), its current length, a plan chip (keep/thin/drop), a length box, "lands <m:ss>" ("…" while running, "whole" when it failed), Keep / Free / Drop pins (tooltips "this section is not touched", "the pass decides", "this whole section goes"), Claude's reason, the error or note, and "Cut again" / "Cut this section again". The row's left edge colour shows running, done or failed.
  - Typing a length in a row's box (on Enter or leaving the box): 0 drops it, its full length or more keeps it, anything between thins it to that length; the pin is cleared. Accepted forms: m:ss, minutes, seconds, a percentage of itself. Unreadable: "a section length is m:ss (1:40), minutes (2m), seconds (45s) or a percentage of itself (60%)".
- Suggestions tab:
  - Stats: "<now> → <lands if all taken> · <n> removed · <m> to decide".
  - "Showing the whole cut" or the open suggestion's section ("· close the suggestion to see the whole cut").
  - The doubled lane (a 76 px drawing): top, the cut as it would run with every pending and accepted removal out, coloured by speaker; below, each removal hanging under the join it leaves (pending: hatched red, solid when picked by the slider; accepted: solid red; dismissed or invalid: faint outline; the open one outlined in cyan); red ticks at the joins; "−m:ss" counters where there is room; the playhead in cream. Clicking the top half moves the playhead to that real moment; clicking a block below opens that suggestion. Caption: "Top: the cut as it would run. Below: what goes, under the join it leaves. Click the top lane to play from there; click a block below to open it."
  - "At a length" slider (30% to 100%): marks the pending suggestions whose durations together come closest to taking out the needed time (whole seconds; a tie goes to the smaller cut; at most 2000 items and 6 hours considered). "The quick answer from the suggestions already on the table, not a new pass: drag, and the ones that would go are marked." Buttons "Accept these <n>" (or disabled "Nothing to accept at this length") and "Plan again at <m:ss>". Marked rows read "at this length · ".
  - Switch "Mark them on the lane and the cards" (remembered per browser, key `tc.shorten.marks`, default on).
  - "Hear" control (hint "Alt B"): "As it stands" (default), "Shortened", "Original", each with an explanation:
    - As it stands: "Hearing the cut as it stands: a scrub across a seam plays half a second of what was taken out".
    - Shortened: "Hearing the shortened cut: playback jumps what would go, and a seam plays half a second, ducked".
    - Original: "Hearing the original: what would go plays, and crossing a seam plays what was taken out, whole".
  - "On the lane" control (hint "Shift B"): In full, Ribbon, Hidden (remembered per browser, key `tc.shorten.lane`, default In full).
  - Reason buttons: one per kind of pending removal, "<kind> · <count> · <m:ss>", largest total first; clicking one dismisses every pending one of that kind ("A reason button dismisses all of its kind: "keep all the scene-setting".").
  - One row per suggestion grouped under its section: kind chip, reason, "−m:ss", speaker, section, "taken out" or "dismissed". Opening a row shows the words that go struck through, for a splice the words either side ("reads <before> | <after>"), "Cut inside a sentence: <why>" when it is mid-sentence, the error if it can no longer be placed, and buttons:
    - Pending: Accept, Dismiss, Hear it.
    - Dismissed: Bring it back. No longer placeable but still pending on the record: "Keep it on the list" and Dismiss.
    - Accepted: Put it back.
  - Empty: "No suggestions yet. Cut the words of a section and they appear here."
- Read tab: the cut's budgeted sections as prose, each card's words with its speaker; words a pending suggestion would remove are struck through (the whole card when it is a whole-card removal).
- Accepting one suggestion:
  - Found in the cut as it is now by its clip and clip seconds (never by the card id it was made against). A card holds the removal if it covers it except for up to 0.6 s at its edges; of several, the shortest wins.
  - Whole card (or what would be left either side is shorter than the editor's minimum card length): the card is moved to the shelf under the pass's category.
  - Head of a card: split at the end of the span and shelve the head. Tail: split at its start and shelve the tail. Middle: split twice and shelve the middle; the two kept halves play back to back.
  - Each resulting piece gets its own words from the word timing (a word belongs to a piece by its midpoint), and highlights that no longer occur are dropped.
  - Nothing is deleted: removed material always goes to the shelf.
  - One accept is one change with one undo. Refusals: "that removal does not say where in the clip it came from, so it cannot be made now"; "the words "<first 40 chars>" are not one card in this cut any more, so this suggestion cannot be made. Dismiss it, or ask for the pass again."; "that removal is shorter than a frame now, so there is nothing to take out"; or the editor's own refusal. If the edit worked but the server could not record it: "taken out of the cut, but the review could not record it: <why>".
- "Accept all <n>" (and "Accept these <n>"): every pending one that can still be made, in one change with one undo: "<n> taken out in one change; Undo puts them all back". None possible: "none of those suggestions can be made to this cut list any more".
- Put it back: moves the shelf card back after the card it followed; if that card is gone, before the first card of the cut (or with no position). Not on the shelf any more: "that one is not on the shelf any more, so there is nothing to put back".
- Hear it: a pending suggestion is still in the cut, so the playhead jumps to it and plays. An accepted one plays on its own from the clip, whole: "playing what was taken out: <m:ss> of <speaker>". Failure: "the audio for that removal could not be played here (no audio on this page, or the media service did not answer)". No position: "that removal does not say where in its clip it was, so there is nothing to play".
- Audio of removed material: one thing at a time (a new one stops the last), at most 60 s per span, 12 ms fade in and out, decoded from the editor's media service; a page without Web Audio plays nothing.
- Background checks:
  - Whenever the cut changes during a review, each pending or invalid suggestion is re-checked against the cut; one that can no longer be made is reported invalid with its sentence, and one that can again (for example after an undo) goes back to pending. Not while sections are being cut or a batch is being recorded.
  - Every 8 s while a review is open and nothing is running, the panel re-reads the review from the server (to pick up decisions made in another window or on a phone).
  - A newer review from the server replaces the one on screen; an older answer arriving late is ignored. A review closed elsewhere turns the A/B player off.
- Keys:
  - Alt+H: open or close the panel.
  - Shift+B (only while there is a review or a score preview with removals): cycle the lane drawing In full, Ribbon, Hidden, with a toast "Suggestions on the lane: in full" / "Suggestions on the lane: the ribbon only" / "Suggestions on the lane: hidden (they stay in the panel)".
  - Alt+B (only while a review is open): the first press switches to Shortened, then flips between Shortened and Original, with a toast of the explanation above. Back to "As it stands" only from the panel or by closing the review.
  - Keys typed in the panel's text boxes never reach the editor's shortcuts.
- Server unreachable: "the server could not be reached (<why>); nothing changed".
- Touch: 44 px targets; on narrow widths the pins take their own line. Nothing scrolls sideways.

## Auto-shorten: markers on the lane, cards, edit view and overview
(source: features/shorten/marks.ts, features/shorten/ops.ts, features/shorten/styles.css)

- Shown while a review with suggestions is open and the marks switch is on.
- A marker is a small "✂" badge with a label: "−m:ss" for one pending suggestion, "<n> · −m:ss" for several (only pending ones count; without pending ones no minus sign). Colour by the loudest status: pending red, accepted quiet grey, invalid gold, dismissed faint. Tooltip and spoken label: "Shorten: <reason>, <m:ss>, suggested|taken out|can no longer be placed|dismissed. Open it to read it".
- Where markers appear:
  - The main lane: the material that would go is a hatched red strip along the foot of the clip with dashed edges (dismissed: grey); an accepted removal leaves a tick at its join (red for a section); a "✂" tab at the right end of each span or on the join (tabs closer than 48 px merge into one with a count). Ribbon mode: the strip and short ticks only. Hidden mode: nothing. Only what is in view is drawn. On a lane under 48 px tall the tab hides its text. Invalid suggestions are not drawn on the lane.
  - Each card in the card list: a badge in its header row and a coloured rule down its left edge (red pending, grey accepted).
  - The section rail, the phone's section chips and the section heads in the card list: a badge with the section's suggestions.
  - The edit view's Before / This / After rows: a badge on each row whose card has suggestions.
- Clicking any marker (the click never selects, scrubs or jumps underneath) opens one popover for that suggestion; clicking the same marker again closes it; clicking elsewhere closes it; switching cut list closes it.
  - Contents: kind chip, "−m:ss", status chip, a close button, the reason, the words that go struck through (for a splice, with the kept words either side and "reads as <joined sentence>"; for a whole card with no words, "this card, whole"), speaker and section, why it can no longer be placed, and buttons: Accept and Dismiss (pending), Put it back (accepted), Bring it back (dismissed), Dismiss (invalid); always "Hear it" and "Open in the panel". Several suggestions under one marker: Previous, "<i> of <n>", Next (wrapping).
  - A message raised since the popover opened (an accept refused, a sound that would not play) is shown in it.
  - On a phone (width up to 700 px or height up to 500 px) the popover is a bottom sheet; otherwise it sits under (or above) the marker. Esc closes it and returns focus to the marker. Keys pressed inside it never reach the editor's shortcuts.
- Hearing what was taken out while moving the playhead (never when the lane mode is Hidden):
  - A scrub (a move of up to 2 s) across the join an accepted removal left, when not playing, in "As it stands" or "Shortened": half a second of what was removed at 35% volume.
  - In "Original": crossing such a join plays the removed block whole at full volume; while playing, playback pauses at the join, the block plays, and playback resumes from the join (cancelled if the editor moved meanwhile).
  - In "Shortened" while playing: playback jumps over any pending removal it enters (and any that start where that one ends).
  - The same join is not heard again within 700 ms.
- The score preview (no review open): whole cards that would go at the slider's length are drawn as a gold hatched strip on the lane; no tabs, nothing to accept.
- Keep heat (lane mode "In full", with scores and a review or a preview open): kept cards the scores nearly cut get a pale wash rising from the clip's foot, stronger the lower the keep score (drawn when 1 minus the keep score is at least 0.25). Hovering shows "Kept, but the next to go at a shorter target" (0.8 and up) or "Kept, and close to the line" (0.5 and up). Not drawn in high-contrast mode.
- Markers are put back whenever the views redraw, and follow scrolling, zooming and resizing.

## Auto-shorten: the demo page
(source: features/shorten/demo/build.ts, features/shorten/demo/entry.ts)

- DEV ONLY: a build script bundles the editor with only the shorten feature mounted (toolbar button, Alt+H, the dock) into an output folder for browser tests and screenshots, and exposes the panel and markers on the page as `window.shorten` and `window.shortenMarks`.

## The edit chat ("Ask Claude"): the server routes
(source: features/chat/server.ts, features/chat/store.ts, features/chat/legacy.ts, features/chat/models.ts, features/chat/prompts.ts, features/chat/reply.ts, features/chat/types.ts)

Terms: a **turn** is one message from the editor and Claude's answer. A **proposal** is one suggested change in an answer, made of edit steps; nothing is applied until the editor clicks Apply. A **conversation** is the retained Claude session for one cut list and one model.

- Models: Sonnet 5 (`sonnet`, "fastest, $2/$10 per Mtok"), Opus 5.5 (`opus`, "stronger, $4/$20 per Mtok"), Fable 5.1 (`fable`, "most capable, $10/$50 per Mtok"). Default Fable. An unknown value (or a full model id of one of the three families) becomes the matching slug or the default. Environment variable `TC_CHAT_MODEL` pins one model id for everyone and overrides the picker. Each model is its own conversation.
- Where the chat keeps its state: `<cut list folder>/.tcards-chat/<cut list name>/chat.json` (visible history, cards already sent in full, used conversation ids, when the conversation was opened, the transcripts and style fingerprints) and `session.json` (Fable) or `session.m-<slug>.json` (others). Root: environment variable `TC_CHAT_DIR`, else the working-copy root, else on a read-only vault with no working copy a temp folder `<system temp>/tc-editor-chat/<12 hex of the vault path>`, else the vault. Writes are atomic; a write that fails loses only the history line, never the turn.
  - Kept: the last 50 turns, the last 20,000 "known card" entries, the last 50 used conversation ids (the first is always kept).
  - When a cut list is renamed, its chat folder moves with it; a folder already under the new name is moved aside as `<name>.before-<ms>`, never merged or deleted.
- Importing the old app's history: the first time a cut list's chat state is read, the old app's `<cut list name>.chat.json` beside the cut list (working copy first, then the vault) is read once and its turns are put in front of the new history, marked as old; the old file is never written. Files over 8 MB are skipped. If the old file exists but cannot be read or parsed, the import is retried on the next load.
  - Old turns can do nothing: their proposals carry no edit steps. An old applied proposal shows the lines it applied and any failure ("<msg> (nothing was changed: the proposal/turn was put back)" when it was rolled back); an unapplied one shows as out of date; an old dismissed shorten proposal shows "this suggestion was dismissed". Old turns are never mentioned to Claude.
- House style: the episode's `<Episode>/Script Docs/chat-style.md` replaces the built-in house style whole when present and non-empty. The built-in style has 7 rules: no interviewer questions ever; withhold then reveal; part of a sentence can be the whole card; end sections on a cliffhanger; space revelations; never invent tension (speakers' own words in their own order); cut it as one conversation across speakers. When the editor's request conflicts with the style, Claude is told to do what was asked and say what the style would have done.
- `GET /api/chat/state?key=&model=`: the panel's state: whether Claude is available (yes/no and why, never the program path), the model id, slug and label, the model list, whether a turn is running for this cut list, the conversation (id, turns, warm, seconds since last turn, provider), the transcripts (count, interviewees, clip count, characters, parts, whether the warm conversation holds the current transcripts and style, whether a custom style is in use, or an error sentence if they could not be read), and the history. Also triggers the one-time import above.
  - Bad key: HTTP 400 `bad-key` with the reason.
- `POST /api/chat/ask` (body `{key, text, model, project, fp, ctx}`, at most 16 MB): one message; answers with a stream of lines (newline-delimited JSON).
  - Refusals before streaming: not an object, HTTP 400 "the request is not a chat message"; empty text, HTTP 400 `empty` "type what you want changed"; over 4000 characters, HTTP 413 `too-long` "that message is over 4000 characters: say it in fewer words"; no valid cut list in the body, HTTP 400 `bad-project` "open a cut list first - the chat edits a .cut.md, not a live timeline"; Claude unavailable, HTTP 503 `no-claude` "the edit chat needs claude: <why>"; a turn already running for this cut list, HTTP 409 `busy` "Claude is still working on the last message".
  - Stream events: status ("reading the transcripts, part k of n", "thinking", "checking the suggestions against the cut list"), the answer's `say` text as it is written, then done (the turn and conversation) or error.
  - If the page closes the stream, the turn is stopped and Claude's process is ended.
  - Context the page sends: playhead time, selected cards in click order, the current view. The server recomputes which card is under the playhead from the time and the project sent, never trusting an id.
  - Cold or warm: the conversation is warm if it has completed a turn under 3600 s ago. It is cold if not warm, or if the transcripts or the house style changed since it was opened. A cold turn starts a new conversation (if the old one had turns), sends the episode's transcripts in parts of at most 100,000 characters (one Claude turn each, thinking off, 900 s timeout, Claude told to reply "ok"), then sends the rules, the edit vocabulary, the house style and the full cut list followed by the message (900 s timeout). A warm turn sends the cut list again with cards already seen in full shortened to their first 60 characters, plus the context and the message (600 s timeout, thinking on).
  - Why a new conversation was opened (shown as a note "opened a new conversation: <why>"): "the first message of the session reads the transcripts and the cut list"; "the house style changed since the last message, so it and the cut list were read again"; "the transcripts changed since the last message, so they and the cut list were read again"; "the conversation had gone cold (over an hour), so the cut list was read again"; "the conversation could not be dated, so the cut list was read again"; "the Claude session was lost (new machine or a rebuilt store), so the cut list went in again".
  - A lost conversation is re-opened once; lost twice: "the Claude session was lost twice running: give it a moment and retry". A conversation id refused twice: "the Claude session could not be opened: the provider refused the id twice running". A conversation that never completed its first turn is discarded. Conversation ids: the first for a cut list and model is derived from the cut list key (so two browsers share it); every id used is remembered and never reused.
  - Transcripts that could not be read do not stop the turn: note "the transcripts could not be read (<why>), so nothing can be brought in from them this turn".
  - What Claude is sent about the cut list: a header line (frames per second, drop-frame, revision, number of cards, total length, number of sections), then one line per row in order: each card with id, speaker, seconds, colour, its words, highlights and note; gaps ("gap <n>s of black"); section, heading and note markers with their start time and, for sections, card count and length; then the staged shelf by category, saved sequences, and alternates. A card counts as "seen" by its id plus a fingerprint of its span, words and note; change any and it is sent in full again. Highlights are always sent.
  - The context block: what became of the last turn's proposals ("last turn: proposal "<title>" was applied" / "last turn: none of the <n> proposals was applied"), the playhead (time, which card and how far in, or "not on a card"), selected cards (in cut order), view, and a "SELECTED CARDS" block listing each selected card (and selected shelf cards) with id, speaker, time, first 60 characters and section.
  - The answer must be one JSON object with `say` (one to three sentences) and up to 4 proposals (title, why, edit steps). A reply with top-level steps and no proposals is read as one proposal titled from `say`. Not JSON: "Claude answered with something that is not an instruction, so nothing was changed". Nothing to say and nothing to suggest: "Claude answered with nothing to say and nothing to suggest. Try asking again in other words."
  - Every proposal is checked on the server against the project the page sent, step by step, through the editor's own edit rules; a proposal that fails is kept, marked invalid with the sentence, naming the step ("step <i> of <n> (<op>): ..."). One that changes nothing: "that would change nothing". Each valid step produces a plain-English line (see the next section).
  - Stopping: "stopped: nothing was asked of the cut list" (code `cancelled`).
- `POST /api/chat/cancel` (body `{key}`): stops the running turn for that cut list; answers whether one was stopped.
- `POST /api/chat/reset` (body `{key, model}`): a new conversation for that model; refused while a turn runs (409 "Claude is still working on the last message"). The visible history is kept and a divider is added: "new conversation: the next message reads the transcripts and the whole cut list again".
- `POST /api/chat/mark` (body `{key, turn, proposal, state, fpAfter}`): records that a proposal was applied (with the cut list's fingerprint after) or undone. Applying one marks every other unapplied proposal of that turn out of date.
  - Refusals (HTTP 409 `gone`): "that message is not in this conversation any more"; "that suggestion is from the old app: ask again to have it worked out against this cut list"; "that suggestion is not in this message any more"; "that suggestion has not been applied, so there is nothing to undo". State other than applied/undone: HTTP 400 "a mark is applied or undone". Missing turn or proposal: HTTP 400 "the turn is missing" / "the proposal is missing".
- On server shutdown every running turn is stopped.

## The edit chat: what a proposal can do
(source: features/chat/ops.ts, features/chat/digest.ts, features/chat/prompts.ts, features/chat/bridge.py)

- Card handles: a card id as `cut:<id>` (in the cut) or `alt:<id>` (on the shelf); `@playhead` (the card under the playhead); `@selected` (the selected cards); `new:<name>` (a card made earlier in the same proposal by an insert with `as`). Placement may also be `at_playhead`: before the card under the playhead if the playhead is in its first half, else after it.
- Steps and their result lines:
  - move: moves cards before/after a card, to the start or the end, or at the playhead. "moved <n> card(s) <where>". Refused: "those cards are already there"; "a card cannot be moved before or after itself"; "that card is the one the playhead is in, so there is nowhere to move it to".
  - delete: takes cards out of the cut onto the shelf under the name of their section. "deleted <n> card(s) (onto the shelf under its section)".
  - stage: shelves cards under an optional category. "staged <n> card(s) [under <cat>]". A non-text category is refused.
  - unstage: puts a shelf card back into the cut at a placement. "put a staged card back into the cut <where>".
  - trim: keeps the words from one phrase to another (either may be omitted), using the card's word timing; the cut point is midway between words; the card's words are rewritten to the kept words and the kept words are highlighted unless the step says not to. "trimmed a card to keep "<from> to <to>" [(highlighted)]". Refused: "a trim needs the words to keep: keep_from, keep_to, or both"; "<to> comes before <from> in that card, so there is nothing between them"; "that card already begins and ends on those words, so there is nothing to trim".
  - split: blades a card just before a phrase; each half gets its own words and the highlights that still fit. "split a card before "<phrase>"". Refused when the phrase is the card's start.
  - gap: sets the black before a card (sizes an existing gap, inserts one, or removes it when 0). "put <n> s of black before "<card>"" / "removed the gap before "<card>"". Refused: a non-number; "there is no gap before "<card>" to take out".
  - color: sets or clears a Resolve clip colour on cards (Orange, Apricot, Yellow, Lime, Olive, Green, Teal, Navy, Blue, Purple, Violet, Pink, Tan, Beige, Brown, Chocolate). Refused: "<colour> is not a Resolve clip colour".
  - note: writes or clears a card's note (in the cut or on the shelf).
  - highlight: marks words of a card (in the cut or on the shelf) as highlighted, or clears it; the words must be the card's own. Refused: ""<text>" is not in that card. Its words are: "<first 80 chars>"".
  - section_add: adds a section or note heading before a card, at the playhead, or at the end. Refused with no title.
  - section_from: gathers the named cards where the first of them sits and puts a new section heading in front ("grouped <n> card(s) under the new section "<title>"", plus "(the cards after it stay under it until the next heading)").
  - section_remove, section_rename, section_move (before a card's section, above another section, or to the end). Headings are found by title, case-insensitive. Refused: "there is no heading called "<title>""; "more than one heading is called "<title>", so it is not clear which one was meant"; moving a note ("is a note, not a section"); moving a section above itself.
  - insert: brings in new material from a transcript paragraph by its `^ref`, optionally narrowed from one phrase to another, optionally naming the person when two transcripts share a ref. Placed like a move, at the playhead (which splits the card under the playhead when both halves would be at least the minimum card length), or onto the shelf with an optional category. Adds the clip's facts (frame rate, start timecode) to the cut list the first time a clip is used, read from the clip's word-timing file beside the transcript when present. The narrowed words are highlighted. "inserted <n> s of <speaker> ("<from ... to>") <where>", plus "(the whole paragraph: the words could not be narrowed)" or "(the highlight would not fit the words, so it was left off)".
    - Refused: no ref; "this episode has no transcripts to insert from"; "there is no paragraph ^<ref> in this episode's transcripts"; "that block is a question, and questions are never in the edit" (when every paragraph with that ref is an interviewer question); a non-text shelf category; the transcript reader's own sentence (for example no word timing).
- Common refusals: "Claude named no card."; "Claude named a card that is not in the cut list (<id>)."; "Claude named a staged card that is not on the shelf (<id>)."; ""<new:x>" is not a card this proposal has made."; "the page did not say where the playhead is, so there is nothing here to point at"; "the playhead is not on a card right now, so there is nothing under it to name"; "nothing is selected on the page right now"; ""@selected" is more than one card here, and this op takes one"; "a selected card is no longer in the cut list"; "Claude asked for something this cut list cannot do (<name>)."; "that card has no word timing, so its own words cannot be found in it"; ""<words>" is not in that card. Its words are: ..."; ""<words>" is in that card, but not on any word that can be timed". Most end "Nothing was changed."
- Matching a card's words ignores case and spaces (so "我今年19歲" matches "我今年 19歲").
- The transcript reader (a Python helper on the shared pool, one call at a time, 120 s default, 180 s for reading the transcripts, 60 s for words and inserts) reads every interview and corpus-clip transcript of the episode, cached until a file changes; it never writes anything under the vault (enforced by refusing any write under an episode folder during a chat call) and never starts audio extraction. It keeps up to 4 reading sessions in memory, in a temp folder removed when the process exits. Environment variable `TC_PIPELINE_DIR` overrides where the reused Python package is found. A `ping` command exists for diagnostics.

## The edit chat: the panel
(source: features/chat/client.ts, features/chat/styles.ts, features/chat/models.ts, features/chat/types.ts)

- Opening: toolbar button "Ask Claude" (speech-bubble icon, tooltip "Say what to change; Claude suggests, and nothing changes until you apply one", shown pressed while open; when not mounted with toolbar slots, a header button of its own). On a phone (up to 700 px wide): an icon button in the editor's header row and another in the edit view's top bar, never floating over content. One panel per page.
- Placement: on desktop over the inspector column (or, if that is hidden, a 420 px column at the right between the header and the dock); on a phone a full-screen sheet with the composer above the keyboard; the phone's back gesture closes it.
- Close: X button (hint Esc), Esc (when the text box is not focused; Esc in the box only leaves the box), the toolbar button again. Focus returns to the opener.
- Header: "Ask Claude" and a model picker (Sonnet 5 / Opus 5.5 / Fable 5.1, each with its price note as tooltip; remembered on the device as `tc_chatmodel`, default Fable). Changing the model reloads the state for that model's conversation.
- Status line (with a dot: running, warm, cold):
  - Problems: "the chat is not available: <why>"; "open a cut list first - the chat edits a .cut.md, not a live timeline"; "the chat needs claude on this server: <why or 'not installed'>". While any of these holds, the box and Send are disabled.
  - While a turn runs: "<status>, <n> s" counting each second (no progress bar).
  - Otherwise "Warm, <n> turns in" or "Cold: the next message reads everything", then "<n> transcripts" (", changed since" when the warm conversation holds older transcripts), "no transcripts", or "transcripts could not be read", and any note. Tooltip: "<model>: it still has this cut list in mind" or "...the first message reads the transcripts and the whole cut list", and "<n> transcripts in <k> parts".
- Empty history: "Say what to change, in your own words: "drop the second pangolin story and move the handbook cut to the end". Claude answers with suggestions; nothing changes until you apply one, and each one is a single undo step."
- History: each turn shows the editor's message, Claude's reply (streaming in with a blinking caret), its proposals, and any error. Dividers: "new conversation: ..." lines; when old-app turns exist, "Earlier messages, from the old Timeline Cards" before them and "In this editor" before the first new one. A turn that just landed is scrolled to its top; otherwise the log stays at the bottom only if it was already there.
- A proposal card: title, "<i> of <n>", why, the result lines, and a summary of what it would change against the cut list as it is now: length change ("+n.n s" / "−n.n s"), "<n> in", "<n> out", "<n> card(s) moved" (the fewest cards that must move), "<n> trimmed", "+/−<n> heading(s)", or "no change in length or order".
  - Apply (the only thing in the chat that changes the cut list): applies all its steps as one change with one undo step through the editor's shared proposal pipeline, then tells the server. Refusals shown on the card: "open a cut list first"; "those are not the newest suggestions in this conversation. Ask again to bring them up to date."; "that suggestion has been applied already"; the invalid reason; "the cut list changed since these were suggested - ask again" (the cut list's fingerprint differs from the one sent with the message); "this would not apply now: <why>"; "this one would not apply to the cut list as it is". Applying marks the other proposals of that turn out of date ("The cut list has moved on: ask again to have this one worked out against it"). If the server could not record it: "applied, but the chat could not record it (<why>)".
  - After applying: "Applied, one undo step" and "Undo this". Undo this works only while the cut list is exactly as the apply left it; otherwise "the cut list has changed since this was applied, so undoing it here would take later work with it. Use Undo in the editor, step by step." Then "Undone".
  - Old-app turns: "Applied in the old app", "Applied, then undone, in the old app", or "Suggested in the old app: ask again to have it worked out against this cut list"; no buttons.
- Composer: text box (placeholder "Say what to change, in your own words", or "Apply one of these, or say how to change them" when the newest turn has proposals waiting). Enter sends; Shift+Enter is a new line (not while an input method is composing). Buttons: "New conversation" (tooltip "Start over: the next message reads the transcripts and the whole cut list again"; disabled while busy), "Send", and "Stop" while a turn runs (stops it on the server and in the page).
  - One message at a time; the message appears immediately. Errors: "Stopped. Nothing was asked of the cut list."; "the chat stopped answering before it finished"; "the chat did not answer: <why>".
  - After every turn the state is reloaded so the warm/cold line is current.
- Switching to another cut list clears the panel and reloads it if open. The proposal previews are re-checked whenever the cut list changes.
- Touch: 44 px targets; 16 px text in the box (no zoom on focus on iPhone).

## The edit chat: the test page
(source: features/chat/entry.ts)

- DEV ONLY: a page entry that starts the editor without other features and mounts only the chat (its toolbar button and Apply), for the browser test and screenshots.

## Translation: the server routes
(source: features/translate/server.ts, features/translate/ops.ts, features/translate/bridge.py; values confirmed in multicam_pipeline/cards/config.py)

Terms: a card's **key** is the first 16 hex digits of a SHA-1 of "<speaker>|<words>" with all whitespace removed (byte-identical to the old app's key, so its stored translations still match). Changing a card's words changes its key, so a trimmed card asks for English again. A **statement** is a run of consecutive cards translated together. Translations are never written into the cut list file and never become edits.

- Where translations are kept (in the episode's `Script Docs` folder):
  - `card_translations.json`: Claude's translations ("exact"), each with the original words (field `zh`, any language) and the English.
  - `gt_translations.json`: Google drafts; read only for its "this is English already" verdict (see below).
  - On a read-only vault with a separate working copy: read from the vault and the working copy (working copy wins), written to the working copy. With no working copy: kept in memory only.
  - Engine cache folder: environment variable `TC_TRANSLATE_CACHE`, default `<system temp>/tc-translate-cache`.
- Which words want English: any Chinese characters, or letters that do not look like English (Cyrillic, accented Latin and so on).
- Source language: a statement's language is its clip's, read from the clip's own transcript words (about the first 4000 characters), else from the statement's words: zh, zh-Hant (more Traditional than Simplified characters among a fixed list of common ones), ja (kana is 10% or more of CJK letters), ko, ru, uk, ru-uk, en, or unknown. Cached per cut list and clip, up to 4000 entries (then cleared). Named in the prompt as Taiwanese Mandarin, Mandarin Chinese, Russian, Ukrainian, "Russian or Ukrainian", Japanese, Korean or English.
- `POST /api/translate/lookup` (body `{project, items, para, clips}`, at most 8 MB): the English the server knows for each card.
  - At most 5000 items (HTTP 413) and 500 clips (HTTP 413). Each item must carry a key matching its speaker and words, or HTTP 400 `bad-key` "an item key does not match its words". Texts at most 20,000 characters (413), speaker and clip at most 400, key at most 64; numbers must be numbers (400).
  - Order of preference per card: Claude's exact translation (unless it runs past the cut, below); the transcript's own human English when the card covers whole transcript paragraphs (it covers at least 90% of each paragraph it touches, or misses less than 1 s of each); the transcript's English cut to the phrases the card keeps, from stored phrase alignments of the clip ("aligned"; tried first on the transcript's own paragraph alignments, then any); and, when `para` is asked, the transcript paragraph's English under the card as a dimmed hint ("para").
  - An exact translation that runs past its card (whole phrases of paragraphs the card barely reaches appear in it) is replaced by the aligned English.
  - A card Google once judged to be English already gets no line.
  - Why a card has no English (returned per card for the lane): "transcript could not be read", "no transcript paragraph under this clip", "transcript has no English here", "transcript not phrase-aligned yet", "words not found in the aligned transcript", "no English found".
  - Also returns the original language of each clip asked about, and the run status (below).
  - If a translation lands while a lookup is reading, the cards not yet answered are re-read up to 3 times; if still moving, the answer says one more is owed so the page asks again.
- `POST /api/translate/run` (body `{project, statements}`, at most 16 MB, at most 5000 statements): starts a Claude translation run and returns at once with the number of parts and statements.
  - Refusals (answered `ok:false`): "Claude is not available on this server: <why>"; "a translation run is already going" (one per cut list); "nothing needs translating". Each statement must have a non-empty parts list (HTTP 400).
  - Model: from the old app's settings (`claude-haiku-4-5-20251001`), no extended thinking, 300 s per call.
  - Each statement is sent with: the speaker, its language, the words spoken just before and after it in the interview, the human English of the paragraphs it spans (each paragraph once; left out for a single shelf card), each part's words, any part's existing English (kept, as context), and each new part's approximate slice of the paragraph English.
  - Parts are grouped into calls of at most 50 parts and about 20,000 characters, never splitting a statement; 3 calls at a time. Parts a call left empty are asked once more.
  - An answer that copies English from the wrong stretch of the transcript is dropped (checked by the old engine).
  - Results are saved after each call. When done: "<n> segment(s) came back empty: press Translate again" if any are missing; a failure's sentence; or "the translation run was stopped".
- `POST /api/translate/stop` (body `{project}`): stops the cut list's run.
- `POST /api/translate/put` (body `{project, items}`, at most 4 MB, at most 200 items): stores English the editor chose for a card (from a transcript paragraph's English selected when inserting its words) as that card's exact translation.
- `GET /api/translate/clip-english?project=&clip=`: one clip's stored phrase alignments and word links (100 to 550 KB per interview), gzipped when the browser accepts it and it is over 2 KB. A clip name with `/`, control characters or `..` is refused ("which clip?").
- `GET /api/translate/status?project=`: whether Claude is available (and why not), the run (running, done, total, error, a counter that rises each time translations land), the Google tier's last trouble and how many drafts are queued.
- Bad cut list key on any route: HTTP 400 `bad-key`.
- Google Translate tier: DORMANT. A background queue that fetches free Google drafts for every card without English (1 s between calls at rest, doubling to at least 3 s after a rate limit and up to 30 s, easing back by 10% per success, a 5 s pause after an error, at most 2000 queued for the machine, saved every 25 drafts) is fully present, but no fetcher is supplied in the shipped server, so nothing is ever queued. Existing drafts are never shown. The Python helper's `gt_fetch` is unused.
- Python helper commands present but unused by any route: `keys`, `lang`, `gt_fetch`, `ping`.
- The Python helper reads transcripts through a read-only copy of the old engine opened over the cut list file (up to 4 kept, reopened when the file changed and a clip it does not know is asked about); it never fetches from Google, never starts audio work, and refuses with "the cut list is not on disk yet: <path>" when the cut list file does not exist.

## Translation: in the editor
(source: features/translate/client.ts, features/translate/language.ts, features/translate/local.ts, features/translate/cache.ts, features/translate/problems.ts, features/translate/styles.ts, features/translate/ops.ts)

- Language switch in every editor header: "EN" (tooltip "English first, the words as spoken under it") and an Original button named after the cut list's original language(s) (tooltip "The words as spoken first (<language>), the English under them"). In the edit view's header only the switch appears.
  - One per-device setting for cards, shelf, edit view and lane (`tc.text.primary`, values `en` or `original`, default English first), kept in step with the lane bar's own language toggle and with other tabs. A device that never chose here takes the lane's stored choice.
  - Alt+L flips it anywhere (not while typing in a text field).
- What a card shows:
  - An English interview (by its transcript or its words): only its own words.
  - A card whose text carries both original and English lines: the original lines are the words as spoken; the English lines are the gloss. A line counts as original when its share of non-Latin script is at least half the most original line's.
  - English first: the English leads (the card's own gloss, else Claude's, the transcript's whole-paragraph English, or the aligned English) with the spoken words smaller under it. Original first: the spoken words lead, the English under them.
  - No English yet: the words lead and, on a card only (never the lane), the paragraph's English under the card is shown dimmed with a "¶" mark (tooltip "The transcript paragraph’s English for this stretch, not a translation of this cut.").
  - Aligned English tooltip: "The transcript’s own English for these words, phrase by phrase (it follows every trim)."
  - The words get the right language attribute for fonts and line spacing; the browser is asked to load the Cyrillic or CJK font slices the cut list needs, once per script.
- Shelf cards always show the English under the words, whatever the switch says (two lines at most).
- The lane gets each card's English (never the "¶" hint) and the reason when there is none ("loading" while a run is going or a lookup is pending, else the specific reason from the server, or "offline" / "server did not answer").
- Translate button (header): "Translate <n>" (on a phone just the number) where n is the cards and shelf cards with no Claude, whole-paragraph or aligned English, each set of words counted once. Tooltip "Translate <n> card(s) with Claude", or with a problem noted "...Something went wrong earlier: see Translation problems in View settings.", or when Claude is unavailable "<why>. It is listed under Translation problems in View settings." (button greyed). Hidden when nothing needs translating. T starts it (not while typing, not with Ctrl, Cmd, Shift or Alt, not on key repeat).
  - While running: "Starting", then "Translating <done> of <total>" (phone: "<done>/<total>"), disabled; cards fill in as each call lands.
  - What a run sends: every stack of consecutive cards with any untranslated card goes whole (already translated members carry their English as context), then every untranslated shelf card on its own. A stack breaks at another clip, a heading, note or gap row between cards, more than 90 s total, the source jumping back (more than 0.04 s) or forward more than 3 s.
  - Refusals shown under the button until dismissed (X button "Dismiss"; the same sentence does not come back after dismissal): "Claude is not set up on this server, so translation is off. The details are under Translation problems in View settings."; "You are offline. Translating needs the server; the English already on this device stays."; "could not reach the server: <why>"; the server's refusal; and, for a run this page started, its failure or "<n> segments came back empty: press Translate again".
- Background behaviour:
  - 300 ms after the cut list changes, the page asks the server for the English of every card still without a final English (including the words a trim or split currently shows on the lane), and for the languages of clips not yet asked about (each clip's words sampled up to 1200 characters). One lookup at a time; a change during one queues another.
  - While a run is going (or drafts are owed) the page asks for status every 1.5 s and looks up again when translations land.
  - Looks up again when a phrase alignment lands or a clip's timed words arrive.
  - A trimmed or split card's English is worked out in the page itself from the clip's stored alignments (fetched once per clip, every clip of the cut list prefetched one at a time in the background, the clip in view first), so it appears in the same moment as the edit; the server's answer replaces it when it has a better one.
  - English chosen when inserting transcript words appears on the new card at once and is stored on the server.
  - Device cache: the English and clip languages are kept per cut list in the browser's IndexedDB database `tc-translate` (at most 12 cut lists, the least recently saved dropped first; 6000 lines per cut list, Claude's kept first; 600 clip languages; lines over 8000 characters not kept; cached Google drafts dropped). Saved 1 s after the English changes, when leaving the cut list, and when the page is hidden. On opening a cut list the cache fills whatever the server has not answered, so a reload offline still shows the English. Any storage failure just turns the cache off.
- Translation problems log (View settings, row "Translation problems", order 900): standing conditions are logged instead of shown over the content, and the Translate button wears a gold dot while one is current. Logged: "Claude is not available on this server: <why>"; "The last translation run: <error>"; "Google’s instant drafts: <trouble>" (unreachable while the Google tier is off); "Offline: the English on this device is shown; new translations wait for the network."; "The server did not answer for the English: <why>". The same sentence is one row with first and last time and a count; newest first; at most 40 rows; sentences cut to 400 characters. Header "none" or "<n> conditions, <k> current"; empty text "Nothing has gone wrong with translation on this page."; "Clear the log" keeps the current ones.
- Touch: 44 px targets; on a phone the refusal spans the screen width under the header and the header never shrinks under its second row.

## Looks redundant or overlapping

- Three separate transcript readers load the same episode transcripts in the same Python worker, each with its own caches and limits: the search's (2 s re-look, 600 folders, 24 word indexes), the chat's (its own corpus build plus up to 4 engine copies), and translation's (up to 4 read-only engine copies). Shorten has a fourth word-file finder (walks 4 levels for `<clip>_words.json`).
- Three language detectors with different answers: the search's (zh, ru, uk, ru-uk), translation's (adds zh-Hant, ja, ko, en, unknown), and the editor core's used by the page.
- Two retained Claude conversations that each send the whole episode transcript corpus in 100,000-character parts: the search (one per scope, model and mode) and the chat (one per cut list and model). Each re-reads after an hour idle.
- Four different model rules: search picker (Sonnet default, Sonnet/Opus/Fable), chat picker (Fable default, same three, plus a server pin `TC_CHAT_MODEL`), shorten (environment only, Opus default), translation (fixed Haiku).
- Bringing transcript words into the cut exists three ways here: the search sheet's Insert (and Insert all for splices), the search sheet's own transcript reader Insert, and the chat's `insert` step; the sheet's reader is itself a fallback for a separate transcript view.
- The search sheet's "Exact words" mode also searches the open cut list's cards, which overlaps the editor's own card Find.
- Two audio players for snippets: the search sheet's audio element (`/media/audio`) and shorten's Web Audio player (`/media/pcm`).
- Shorten has two length sliders on different data (card scores before a pass; pending suggestions during a review), plus "Accept all", "Accept these", per-reason dismiss, and per-suggestion accept; suggestions are shown in five places (panel list, doubled lane, Read tab, markers on four surfaces, the popover) with the same four actions.
- Shorten refuses a cut list without section headings and tells the user to "ask the chat to cut it down in words": the chat can also delete and trim cards, overlapping shorten's job.
- Translation works out a trimmed card's English twice: on the server from stored alignments during a lookup, and in the page from the same alignments fetched per clip.
- The Google Translate tier (queue, pacing, saving, status field, problems-log line, cache handling, `gt_translations.json` writer) is complete code that is switched off.
- Unused Python commands: shorten `sentences`, `parse_target`; translation `keys`, `lang`, `gt_fetch`, `ping`; chat and search `ping`.
- The chat's one-time import of the old app's chat history and the cached-old-history rendering exist only for migration.
- Search history and kept answers on the device overlap the server's own record of finished searches (kept 1 hour, 12 at most).

## Claims the code does not back

- `features/translate/server.ts` header: says a Google draft is "fetched in the BACKGROUND for every card that has no exact one". The shipped server never supplies a fetcher, so nothing is fetched.
- `features/translate/server.ts` `TranslateOptions.gtFetch` comment: "Default: the bridge's fetch, except under a test runner or TC_TRANSLATE_GT=off". The default is null (off); `TC_TRANSLATE_GT` is not read anywhere in this part.
- `features/translate/client.ts` header and `features/translate/language.ts` header: say "≈" marks Google's draft on cards and that English falls back to Google's draft. The page discards Google lines (`kind 'gt'`) and `clipLines` never uses them.
- `features/translate/cache.ts` header: says the device keeps Google's draft. Cached Google lines are dropped on read and never saved.
- `features/translate/ops.ts` header: says translations live in `card_translations.json` and `gt_translations.json` as the two tiers; the second is no longer written or shown.
- `features/translate/client.ts` `TranslateHandle.lineFor` comment: "(exact, gt or para)". It never returns a gt line.
- `features/shorten/ops.ts` `pickToTarget` comment: "The old slider ran its knapsack over a scores sidecar; this one runs over what the pass has already proposed". A scores-based knapsack (`knapsack`) also exists and is used by the pre-pass slider.

## Could not determine

- The exact rules that refuse a pass-2 proposal in shorten (`_check`, the "never-rules"), what a `drop` section produces in `_section`, and the read-back verdict format: they are in `multicam_pipeline/cards/shorten.py`, outside this part, and were not read.
- The exact wording of the search prompts (concept, literal, splice rules) and the structure, words and scores prompts for shorten: they are constants in `multicam_pipeline/cards/config.py`, not read.
- How the shared Claude runner limits concurrency, cost and timeouts, and what `TC_CLAUDE_BIN` does; these live in `server/ai`.
- Who may call these routes beyond the editor server's general sign-in (no-login, password, or trusted proxy); the chat's comment says an origin guard covers `/api`, not verified.
- What the editor does with a chat `delete` (the shelf category it files under) and with `stage`/`unstage` placements: decided by the core reducer, not read.
- The labels the language switch's Original button shows (`langsShort`, `langName`, `langsName` in core): not read.
- How the phrase alignments and word links used by translation are made and stored (`features/align`, `features/aids`): not in this part.
- The `/media/audio` and `/media/pcm` routes the search and shorten players use: not in this part.
- Whether the search sheet's "tc:open-transcript" event is taken by any transcript view in the shipped editor (decides whether the sheet's own reader is ever shown).
- Files not read because the brief says documentation is not trusted: `features/search/README.md`, `features/shorten/README.md`, `features/translate/README.md`, `features/chat/PARITY.md`. Compiled `__pycache__` files were skipped.
