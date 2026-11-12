# Music: the search app, its API, and the audio indexing pipeline

Terms used throughout:
- **Library**: the folder of music files, one flat folder called the "music share", at `<tree>/Assets/Music`.
- **Track**: one indexed audio file (one database row).
- **CLAP**: the audio/text AI model that turns audio and text into comparable vectors ("embeddings"). Model id `laion/larger_clap_music_and_speech`, fallback `laion/clap-htsat-unfused`.
- **Window**: a 10-second slice of a track that CLAP embeds on its own.
- **Base rig**: the workstation with a GPU that runs the indexer.
- **Companion / tray**: the CC Sync desktop app on each editor's computer, reached by the browser at `http://127.0.0.1:8899`.
- **Index**: the SQLite file `music.db`.
- **Proxy**: a 128 kbps mp3 preview copy of a track.
- **Percentile (pct)**: a score's rank among all tracks in the library, 0 to 100.

## The search page: layout and header (source: static/index.html, static/app.js, static/style.css)

- Page title "CC SYNC // MUSIC"; served at `/` standalone and at `/music/` when mounted in the dashboard. All asset and API URLs are relative to the page, so the same page works at both locations.
- Always in the "terminal look" (`html.cc` is in the markup). A 3-second safety timer ends the "hold header height" state; the page also clears a retired cookie `ccsync_ui_effective` on load.
- **Header, fallback version** (shown standalone or when the dashboard topbar cannot be fetched): brand text "CC SYNC // MUSIC" and a `[ DASHBOARD ]` link to `/` ("back to the CC Sync dashboard (SYNC STATUS)").
- **Dashboard topbar injection**: on load the page fetches `../partials/topbar?current=music`. If it answers 200, was not redirected (an expired session redirect is ignored), and contains `data-dash-topbar`, the real dashboard header replaces the fallback. Unreachable or refused: the fallback stays. The "cc-chrome" layout class stays only when a HUD came back.
- The header measures its own height continuously (ResizeObserver) so the filter rail parks directly under it; fallback height 134 px.
- **Search box** (`#q`): placeholder "describe the vibe… tense driving synth pulse, warm nostalgic piano, hopeful build for a montage". Pressing **Enter** runs the search. This is the only keyboard shortcut on the main page.
- **Pool selector**: "any moment" (score by best single 10 s window, default) or "whole track" (score by whole-track embedding). Changing it re-runs the search only if the box is not empty.
- **SEARCH** button: runs the search (empty box = browse instead).
- **clear** button: empties the box, clears the facet, axis slider, include-unknown tick, BPM and length boxes, resets all sliders to "off", re-lists the library.
- **[ ADD MUSIC ]** button (shown as "Add music" in the terminal look): opens the ingest panel. If the panel script did not load: toast "the add-music panel did not load: reload the page and try again".
- **Resolve status chip**: "Resolve · off" or "Resolve · <timeline or project or 'connected'>", tooltip "project X · timeline Y". Asks the companion `GET /music/status` at load, after every send, every 30 s while the tab is visible (not while hidden), and immediately when the tab becomes visible again. Green when connected, red when not.
- **Stats line**: "<n> tracks · <h>h · <GB> GB", plus " · tags catching up" when the library's tag scores are stale. Tooltip "search model: <model>" or "no search model recorded for this library yet". On failure: "library totals did not load" with the reason in the tooltip.
- **Example prompt buttons** (eight, each runs that search): "tense driving synth pulse", "warm nostalgic piano", "hopeful build for a montage payoff", "sparse ominous drone under an interview", "triumphant orchestral finale", "playful quirky plucked strings", "traditional east asian strings", "gritty industrial percussion".
- Below 900 px wide the header stops being sticky, the filter rail stacks above the results, and the ingest panel becomes full width. Below 600 px, terminal-look fields use 16 px text (no zoom on focus) and touch targets are 44 px on coarse pointers.
- If page start-up throws, the list shows "Loading the page failed: …".

## The filter rail (source: static/index.html, static/app.js)

- **Feel** section: one slider per axis returned by the server, in order arousal, valence, tension, organic (others appended alphabetically). Labels: "arousal: calm → intense", "valence: dark → bright", "tension: resolved → tense", "organic: electronic → acoustic"; unknown axes "low → high".
  - Range 0 to 100, step 5. Value 0 shows "off"; value v shows "top (100 − v)%".
  - On release, all other sliders reset to 0 ("One at a time: moving a slider clears the others." is printed above them). Filter = tracks whose percentile on that axis is at least v. Re-runs the current search if there is text, otherwise the browse list.
  - There is no way in the UI to set an upper bound (the API's `axis_max` is never sent).
- **Tempo & length** section: BPM min/max (0 to 300 inputs), Secs min/max, and an **apply** button that commits all four and re-runs the current search or browse. Empty or 0 means unbounded.
- **Include tracks with no BPM or length** tick box: shown only when some tracks lack BPM or duration; count text "<n> tracks have no BPM or length yet" (n = the larger of the two missing counts) or "every track has a BPM and a length". Ticking widens tempo/length filters to also keep tracks whose value is missing.
- **Facet sections** (one per tag category: genre, mood, instrument, use case, texture, then any others alphabetically): a chip per label with its track count, ordered by count. Clicking a chip selects that facet, empties the search box, and browses; clicking the selected chip again deselects it. Selected chip is highlighted. Only one facet at a time.
- In the terminal look, every rail section and the results area become foldable "windows" with a title bar; fold state is remembered per page path in browser localStorage (`ccsync.spafold:<path>`).

## The results list (source: static/app.js)

- **Sort** selector: filename (default), newest (by analysis time), bpm, length. Applies to the browse list only; disabled while a search or similar result is shown, with the note "search results are in order of match" and tooltip "Search results are ordered by how well they match. Clear the search to sort the library." When a facet is selected and sort is filename, the server orders by that tag's percentile instead.
- **Result head**: headline plus "<n> track(s)". Headlines: "All tracks"; filter summary joined by " · " ("<category>: <label>", "<axis> ≥ <v>", "<min>–<max> bpm", "<min>–<max> s"); "“<query>” · any moment|whole track"; "Similar to <filename>"; "Just added"; "Searching…"; "Finding similar…"; error headlines.
- Hidden-unknowns note: "<n> track(s) have/has no <bpm|length> and are/is not shown" plus a `[ include them ]` button (tooltip "Show tracks the indexing computer has not analysed yet") that turns on the include tick and re-runs.
- **Empty states**: search "Nothing matches. Try a looser description or clear the filters."; filtered browse "No tracks match these filters. Clear one and try again."; unfiltered browse "The library is empty. Drop some music in to get started."; similar "Nothing in the library sounds like this one yet."
- **Failure texts**: 401 → "<what> failed: your session expired. Reload the page to sign in again."; otherwise "<what> failed: the server answered <status> (or the network reason). Try again, and if it keeps happening tell your admin what this line says."
- Only the newest request renders: a slow search that returns after a later filter is discarded.
- Browse loads at most 500 tracks (server default); search asks for 60 hits; similar asks for 25.
- **Each track row**:
  - Play button (▶). Clicking opens the player pane under the row and starts playback; clicking again on the open track toggles pause/play.
  - Filename (bold), pills for length (m:ss), BPM (rounded, if known), key (if known).
  - Tag pills: top genre, top two moods, top instrument, top use case. Tooltip "<category> · score <s> · <pct>th percentile". Clicking a pill selects that facet (same as a chip).
  - Match percentage (search and similar only).
  - **similar** button: replaces the list with the 25 nearest tracks.
  - **→ Resolve** button: opens the player pane without autoplay.
- Replacing the list always closes any open pane and pauses audio.

## The player pane (source: static/app.js)

- One pane open at a time, animated open under its row; closing removes it after 280 ms.
- Waveform canvas (64 px tall) drawn from the stored overview; played part red, rest grey, recomputed every animation frame and on window resize. Clicking anywhere on the waveform seeks to that fraction.
- Play/pause button (❚❚ / ▶) and a time readout "m:ss / m:ss".
- Audio comes from `api/audio/<id>` (the proxy mp3 if one exists, else the original).
- Waveform captions under the strip: 404 → "No waveform yet: this track was added by the fleet and the indexing computer has not analysed it. Seeking still works." (server reason in tooltip); network loss → "The waveform could not be loaded: this page lost the server."; other status → "The waveform could not be loaded (the server answered N)." Only successful waveforms are cached in the page.
- **Send to Resolve buttons** (talk to the companion on the editor's computer, never to the server):
  - "import to bin" (tooltip "Import into the Music bin in the media pool. Nothing is placed on a timeline.")
  - "place underneath" ("Place at the playhead on the first free audio track from A2 down. Nothing moves.")
  - "insert at playhead" ("Ripple insert on A2: clips at or after the playhead on that track shift later. Refuses if that track is linked to video.")
  - Each POSTs `{action: bin|under|insert, share, rel_path}` to `http://127.0.0.1:8899/music/send`. While the companion answers `state: downloading`, the page shows "track isn’t on this computer yet: syncing it down, then sending…" then "syncing the track to this computer: N%" and re-posts every 1.5 s. While it answers `busy`/`queued` (or an older build's "already downloading" error) it shows the companion's message or "waiting for this computer’s other download to finish, then sending…" and retries after `retry_after` seconds (default 1.5 s). Final line: the companion's note or "done" (green) / its error or "failed" (red). All pane buttons are disabled during the exchange. Status line starts "talking to Resolve…".
  - Companion answered with an HTTP error: "the CC Sync tray answered but refused the request (tray HTTP N). Tray > Settings > HELP > COPY DIAGNOSTICS FOR YOUR ADMIN has the reason." Unreachable: "couldn’t reach the CC Sync tray: it is not running, or the browser blocked local connections (self-test: open http://127.0.0.1:8899/status)".
- **similar** button (same as the row's).
- **reveal** button: POSTs `{share, rel_path}` to the companion's `/music/reveal` to open the file's folder on this computer. "opening the folder…" then the companion's message or "opened". HTTP error: "the CC Sync tray refused the request (tray HTTP N): an older build has no reveal. Take the update your tray offers."
- When playback ends the play button shows ▶.

## Drag-and-drop onto the page (source: static/app.js, static/ingest.js)

- Dragging files anywhere over the page shows a full-window veil: "Drop audio to add it to the library" / "Your own computer analyses it and uploads it. .ogg is transcoded to mp3."
- On drop the page first asks the companion for ingest capabilities. If the companion answers, the drop goes to the companion flow (the ingest panel). If not (no companion, or one without `/music/ingest/*`), the files are uploaded straight to the server's `api/ingest` (the fallback path).
- Folders are walked recursively (all directory pages read), keeping only audio extensions, stopping at 500 items.
- A drop containing nothing indexable: toast "Nothing there this app can index: music takes .wav, .mp3, .flac, .aac, .m4a, .ogg and similar."
- **Fallback upload toast**: "Uploading N file(s)…" / "checking for duplicates: this can take a few seconds each" (sticky), then "Queued q/n" or "Added a/n". Queued mode adds "nothing was analysed: this host has no GPU. They are in the library and will not be searchable until the indexing computer indexes them (N waiting in all)." Per file: "◷ name (transcoded to mp3) - m:ss, queued for indexing", "✓ name - m:ss, NNN bpm", or "✕ name - <error>". Shown 9 s. Failure: "Ingest failed: …". When anything was added inline, facets and stats refresh and the list shows "Just added".

## The ingest ("Add music") panel (source: static/index.html, static/ingest.js)

- A drawer over the right of the page (560 px). Opened by [ ADD MUSIC ], by a companion-handled drop, or by the picker. **Escape** closes it; "× close" closes it. Closing stops all its polling.
- **Companion status**: dot (amber checking, green ok, red not ok) and text: "checking…", "connected (v<version>, model ready | model not downloaded yet, about <size>)", "the CC Sync tray can't index yet: <reasons>", the too-old text "your CC Sync tray is too old for music ingest: take the update it offers, then reload this page. Until then, dropped tracks are uploaded here and indexed on the indexing computer." (companion answers 404), or the unreachable hint "not reachable: the CC Sync tray is not running, or the browser blocked local connections (self-test: open http://127.0.0.1:8899/status in a tab; if that shows ok:true it is the browser, not the tray)". **recheck** re-asks and toasts a failure.
- Explanatory text: "Your own computer does the work: the CC Sync tray converts, analyses with the CLAP model and uploads the finished track to the library. The dashboard never sees the audio."
- **Persistent notice** box (amber) with a **dismiss** button, used for companion refusals.
- **Choose files…** / **Choose a folder…**: ask the companion (`POST /music/ingest/pick {kind}`) to open a native picker; picked files are analysed where they lie (not copied into the browser). Non-audio is filtered out. A "cancelled" answer is silent.
- Empty-state text: "Nothing staged yet. Audio only: wav, mp3, flac, aac, m4a, aiff, opus. A folder brings everything audio inside it. Duplicates are spotted before anything uploads."
- Accepted extensions come from the server's limits route, then the companion's capabilities; fallback list .wav .mp3 .flac .aac .m4a .ogg .aiff .aif .opus.
- Batch cap 500 tracks: "A batch holds at most 500 tracks. Run this one first." / "Only the first N tracks were taken: a batch holds 500."
- **Staging**: 700 ms after the last addition, the page asks the companion to prepare a staging area (`POST /music/ingest/prepare`); dropped files are then streamed to the companion with HTTP PUT (two at a time, header `X-CCSync-Ingest: 1`), with a per-row progress bar. A 409 from the companion counts as already uploaded. Failure text "upload failed. Is the CC Sync tray still running?" or the companion's message. Companion not answering: notice "The CC Sync tray is not answering, so these tracks cannot be staged: …"; prepare refused: "The CC Sync tray could not stage this drop: …". A new drop re-stages everything.
- **Pre-check**: 400 ms after changes, and again whenever a file's hash or duration arrives from the companion, the page asks the server which tracks are duplicates and what each will be named. Duplicates are unticked once, the first time found.
- **Track rows**: tick box (disabled while running or if the companion refused it), name, and a line with size, length, "analysed where it is" for picked files, "will be saved as <name>" when renamed; or in red the companion's refusal ("the CC Sync tray refused this track") or error; or in amber "already in the library as <name or track #id>". Head: "<k> of <n> track(s) selected".
- **When to run** radios: "Only when idle" (starts when you step away, pauses when you return; default) or "Foreground" (starts now, one CPU core, not the GPU).
- Summary: "<n> track(s), <size> - will run now | will run when you're away" or "nothing selected".
- **Run** (enabled only with a selection, a reachable companion, staging done, and nothing running): if the model is not on this computer, asks "The music indexing model isn't on this computer yet. Running this batch downloads it first (about <size>). Continue?" (terminal-look dialog with Cancel / Go ahead, else the browser confirm). Creates the batch on the server, then hands its id to the companion (`POST /music/ingest/run`). Companion 503: notice "<reason> The batch is queued on the server: another of your computers can run it, or drop the tracks again to upload them here and let the indexing computer index them."; other refusal: "The CC Sync tray did not take the batch: …". Accepted: toast "Analysing on this computer now." or "Queued: it starts when you step away from this computer."
- **clear**: empties the staged list (not while running).
- **Running / Last batch section**: state sentence and machine ("working on DESKTOP-X"), counts "N of M done · L in the library · F failed · D duplicate", companion detail (idle gate, current file and stage, "downloading the model N%", "uploads: N queued", "uploads paused"), or "the CC Sync tray isn't answering right now - the batch keeps its place on the server (…)". Up to 200 per-track lines "<state words> · <name> - <error>" (raw state in tooltip). Heading changes to "Last batch" and all controls disable when the batch is finished.
  - **Pause**, **Resume**, **Start now**: send `pause` / `resume` / `start_now` to the companion's control route; toast "CC Sync tray: <state>."
  - **Pause uploads / Resume uploads**: sets the durable server flag first, then tells the companion `pause_upload` / `resume_upload` (embedding continues, uploads wait).
  - **cancel batch…**: confirm "Stop this batch? Tracks already in the library stay there; the rest are dropped and their staged files are kept.", then server cancel and companion `cancel`; toast "Cancel requested: the computer stops within a heartbeat."
- **Words shown for states**: batch queued "waiting for your computer", claimed "starting", running "working", done "all done", done_with_errors "finished, some tracks failed", cancelled, failed. Item pending "waiting", transcoding "converting", embedding "analysing", indexed "analysed", uploading, live "in the library", duplicate "already in the library", failed, cancelled, skipped, queued_for_base_rig "couldn't be analysed here - drop it again to upload it instead". Unknown states shown raw.
- **Batches list**: tabs **Mine** and **All computers** (the second appears only if the server lets this user list all, i.e. admins). Each card: state words, editor (in All), coarse age ("just now", "N min ago", "N h ago", "yesterday", "N days ago"; full timestamp in tooltip), machine or "no computer yet", run mode, counts, "uploads paused", "cancelling", error text. Buttons: **tracks** / **hide tracks** (expand up to 200 item lines), **cancel** (unfinished batches), **take over on this computer** (queued batches, Mine tab only), **try the failed tracks again** (finished batches with failures, Mine tab only). Empty: "no batches yet".
  - Take over: hands the batch to this computer's companion; a "staging id missing" refusal is retried once with the id the companion names. Toast "This computer has taken the batch on." or the refusal text.
  - Retry failed: server resets failed items, then asks this computer's companion to pick it up (`/music/ingest/retry`). Toasts: "Nothing in that batch had failed.", "N track(s) back in the queue on this computer.", "… back in the queue, but this computer did not pick them up: <reason>", or "… back in the queue. <hint> Open this page on the computer that has the tracks and press take over on this computer."
- **Waiting for the indexing computer** box (the older server-side queue): "Waiting for the indexing computer: N track(s). They are in the library already and are not searchable until the indexing computer indexes them." with up to 20 names; "N could not be analysed. Nothing retries these on their own: fix the file and drop it again." with up to 20 "✕ name - reason". Hidden when both counts are zero.
- **Polling while the panel is open**: companion progress every 1.5 s, the running batch from the server every 5 s, the batch list every 10 s, the base-rig queue every 15 s.
- After a reload the panel re-attaches to this editor's newest queued/claimed/running batch.
- When any batch moves into a finished state while watched, toast "Ingest <state words>: the library below is refreshed, newest first." and the main page refreshes stats, facets, sliders and switches sort to newest. The tracks this page ran are removed from the staged list.

## The terminal-look helper (source: static/cc_spa.js)

- Active only when the page carries `html.cc` (always, in practice).
- Turns elements marked `data-cc-win` into foldable windows (click the bar to fold/unfold; remembered in localStorage).
- Rewrites bracketed button labels: "[ ADD MUSIC ]" shows as "Add music" (acronyms such as BPM, CLAP, CPU, GPU kept; "resolve" → "Resolve"); bracketed labels inside running text become quoted. Original text is restored if the look is switched off.
- Tooltips: any `title` is shown as a styled tip on hover, keyboard focus, and on tap for non-controls on touch screens; Escape or scrolling hides it.
- Confirm dialog with Cancel (focused) and "Go ahead".

## Static file routes (source: musicweb/main.py)

- `GET /` (the page), `GET /app.js`, `GET /ingest.js`, `GET /cc_spa.js`, `GET /style.css`, `GET /favicon.svg`. No authentication of their own (when mounted, the dashboard's login is in front). Each reads the file from disk on every request.
- Running standalone: `python -m musicweb.main` or uvicorn, host `MUSIC_HOST`/`HOST` (default 127.0.0.1), port `MUSIC_PORT`/`PORT` (default 8790).

## Read API: stats, facets, browse, search, similar, reload (source: musicweb/routes_api.py, musicweb/search.py)

No route here checks a credential itself; mounted, the dashboard login gates them.
- `GET /api/stats`: track count, total hours (1 decimal), total GB (2 decimals), model name, `tagged_at`, `scores_stale` (time tags fell behind, or null), share name `music`, and `music_root` (this host's library path).
- `GET /api/facets`: per category, every label with its track count (most common first), categories ordered genre, mood, instrument, use_case, texture then others alphabetically; `_axes` (ordered arousal, valence, tension, organic); `_bpm` min/max; `_unknown` counts of tracks with no BPM and with no duration.
- `GET /api/tracks` (browse): parameters `category`+`label` (both needed for a tag filter), `axis` with `axis_min` (default 0) / `axis_max` (default 100) on the axis percentile, `bpm_min`/`bpm_max`, `dur_min`/`dur_max` (0 = unbounded), `sort` = filename (default) | bpm | duration | newest (unknown values fall back to filename; filename with a tag filter sorts by that tag's percentile, highest first), `limit` (default 500), `include_unknown` (tracks with a missing BPM/duration also pass a set range). Returns tracks with all their tags (label, score, pct) and axes (pct), plus `unknown_hidden` (how many otherwise-matching tracks a range filter dropped only because the value is missing; 0 when include_unknown) and `unknown_fields`.
- `POST /api/search` body `{query, k=60, pool='max'|'mean', plus the same filter fields}`: empty query returns no tracks. The text is embedded by the CLAP text model; `max` scores each track by its best window, `mean` by the whole-track vector. The top k by similarity are taken first, then the filters remove non-matching ones (filters can only shrink the k, never pull in more). Each track gets `match`: 0 to 100, min-max rescaled within this result set (top hit 100, bottom 0, a lone hit 0). Sorted by match. Also returns `query`, `unknown_hidden`, `unknown_fields`. A library with no window vectors returns nothing for `max`; with no track vectors nothing for `mean`. Text search does NOT apply the source-bias removal.
- `GET /api/similar/{track_id}?k=20`: nearest tracks by whole-track vector after removing the "source catalogue" directions, excluding the track itself; `match` = cosine x 100 (1 decimal). Unknown id → empty list.
- `POST /api/reload`: drops every cached database connection, rebuilds the search matrices, returns the stats. Not called by the page.
- Automatic pickup of index changes: every database access checks whether `music.db` was replaced (the path now names a different file); if so all cached connections reopen (logged warning). The search matrices are rebuilt when the database file or its write-ahead log changed, checked at most every 2 s.
- Text model loading: on first search the ONNX text model is loaded from `<data>/text_encoder` (`MUSIC_TEXT_ENCODER_DIR`), with `MUSIC_TEXT_ENCODER_THREADS` CPU threads (default 4). Used only if its manifest says artefact_version 1, records a check with min cosine of at least 0.999, and both model and tokenizer files exist. Otherwise (or if onnxruntime is missing or loading fails, which prints a "! text encoder artefact ..." line) the full torch CLAP model from the indexer checkout is used; with neither, search fails with an error naming `export_text_encoder.py`.
- The text model is released after `MUSIC_ENCODER_IDLE_SECONDS` (default 600) with no search, checked by a background thread every min(60, idle/4) s (at least 1 s); 0 keeps it forever. The next search reloads it.
- Query text longer than 512 tokens (including start/end markers) is cut.

## Audio and waveform routes (source: musicweb/routes_media.py)

- `GET`/`HEAD /api/audio/{track_id}`: streams the proxy `<proxies>/<id>.mp3` if that file exists, otherwise the original from the library. `?original=1` forces the original. Header `X-Audio-Source: proxy|original`. Single byte ranges answer 206 with Content-Range (suffix `bytes=-N` and open-ended ranges supported); unsatisfiable (start past the end, `bytes=-0`, empty file) → 416; invalid, multi-range or non-bytes Range headers are ignored (whole file, 200). Streamed in 256 KB chunks; HEAD sends headers only. Unknown id → 404 "unknown track"; original missing → 404 "file missing: <rel_path>"; a stored path that is absolute, contains `..` or a drive segment, or escapes the library → 400.
- `GET /api/peaks/{track_id}`: the stored waveform overview (raw bytes, one 0-255 value per bucket, 900 buckets). If none stored: unknown track → 404; file missing → 404 "file missing"; no indexer on this host → 404 "no stored waveform and no indexer on this host to build one: ..."; decode failure → 503 "the waveform could not be built from this file: ..." (logged); decodes to nothing → 404. With the indexer present it builds one (8 kHz decode), stores it and returns it.

## Browser upload ingest, the fallback path (source: musicweb/routes_ingest.py, musicweb/db.py, music_index/ingest.py)

- `POST /api/ingest`, multipart field `files` (one or more), optional header `X-Ingest-Token`.
- **Who may call**: `MUSIC_INGEST_TOKEN` unset: allowed when mounted behind the dashboard login, otherwise 503 "ingest is not configured on this server (MUSIC_INGEST_TOKEN unset)" (logged). Set: the header must match (constant time), except that behind the dashboard login the session alone is still accepted; otherwise 401 "missing or invalid X-Ingest-Token".
- **Request limits** (413, nothing written): more than 64 files; any file over 512 MiB; total over 512 MiB.
- **Two modes**, chosen per request: *inline* when the indexer checkout and torch are importable on this host (the base rig), otherwise *queued* (the NAS container).
- **Queued mode**: needs ffmpeg and ffprobe (env `FFMPEG`/`FFPROBE`, then PATH, then `MUSIC_FFMPEG_DIR/<name>.exe`), else 503 naming the missing tool and refusing the whole request. Needs the library to look mounted (below), else 503 with the reason. Per file:
  - Name reduced to its basename (either slash), characters `<>:"/\|?*` replaced with `_`, Unicode NFC; empty → "untitled".
  - Extension must be .wav .mp3 .flac .aac .m4a .ogg .aiff .aif .opus, else "not an audio file (.ext)".
  - Written to `<data>/staging/ing-*/` first (removed afterwards).
  - ffprobe (120 s limit) must find an audio stream with duration above 0, else "no decodable audio stream".
  - Duplicate defence 1 (re-encode): same normalised name (NFC, lowercase, leading "es_"/"es " stripped, "(2)"/"[2]" removed, only a-z and 0-9 kept) and duration within 2 s of an existing track, or of a pending/done queue row → "already in the library as <path> (same track)".
  - .ogg is transcoded to 320 kbps mp3 (900 s limit, metadata kept); a transcode producing nothing or no audio fails the file.
  - Duplicate defence 2 (identical bytes): blake2b-128 of the whole file compared against library files of the same byte size and against pending/done queue rows → "already in the library as <path>".
  - The library folder is created only on a fresh deployment (parent exists, index empty); if the index holds only not-yet-landed fleet rows: "the music library folder is not there yet on the server. A drop that is still uploading will create it; try again once that has finished."
  - Final name: flat in the library root; if taken on disk (either Unicode spelling), by a track row, or promised to an unlanded fleet item, "name (2).ext", "(3)" ... up to about 1000 tries, then refused. The name is claimed by creating an empty placeholder first.
  - File permissions widened to 0664 on Linux/macOS (not on Windows) so editors can see it over SMB; failure only logged.
  - A queue row is written `pending` (new random id; re-using the name of a failed row resets that row).
  - Response per file: `status: queued` with queue id, rel_path, duration, or an `error` text with `duplicate: true` where relevant. Totals `queued` and `pending` (everything pending in the queue). Nothing is searchable until a base-rig drain runs.
- **Inline mode** (base rig): same checks and naming, then decode, CLAP embed, BPM/key/loudness, waveform, database row; if analysis fails the landed file is deleted ("could not analyse the audio"). After any success the whole library is re-tagged and the search matrices rebuilt; added tracks come back with tags. Response `mode: inline`, `added`.
- `GET /api/ingest/queue?limit=50`: counts by state (pending/done/failed) and the newest `limit` failed and pending rows (name, path, error, attempts, times).
- There is no server route for Resolve actions or reveal; those are the companion's.

## The library-mounted check (source: musicweb/config.py)

- Before writes the server asks whether the library is really visible. Refused when: the folder cannot be read; it does not exist and either its parent is missing or the index names landed tracks ("the music library is not mounted here (nothing at <path>). Nothing is written until it is back."); or none of a sample of up to 25 newest and 25 oldest landed track files exists ("the music library at <path> is there but empty: none of the indexed tracks are visible, so this looks like a share that is not mounted rather than an empty library. Nothing is written until it is back.").
- Rows of fleet items still pending/transcoding/embedding/indexed/uploading/failed are left out of the sample.
- A positive answer is cached 5 s (the folder-exists check runs every time). Fails open when the root is a symbolic Windows path on a non-Windows host, or the schema cannot be read.

## Ingest batches: the browser's API (source: musicweb/routes_batches.py, musicweb/ingest_batches.py, musicweb/schemas.py)

A **batch** is one drop handed to an editor's companion; each dropped file is an **item**. Identity comes from the header `X-CCSync-User` (and `X-CCSync-Admin: 1`) that the dashboard stamps from the login session; any route below answers 401 "not signed in" if that header is missing or blank. Prefix `/api/ingest-batches`.
- `POST /precheck` body `{items: [{local_id, name, size, duration, content_hash, source}]}` (max 500 items; name max 255 chars; hash max 64; source `upload` or `path`): per item `duplicate_of` (track id), `duplicate_name`, `final_name` (preview of the name it would get, considering names already promised to unlanded items; reserves nothing), `unsupported` (true if not an audio extension). Can answer 503 if the library looks unmounted (same as name allocation).
- `POST` (with or without trailing slash) body `{settings: {run_mode}, items}`: `run_mode` `idle` (default) or `foreground`, else 422; settings must be an object, else 422. No items → 422 "a batch needs at least one track"; over 500 → 422; any non-audio name → 422 "<n> of these are not audio files" with up to 20 names. Creates a `queued` batch owned by the caller, items `pending`, each marked with any duplicate found. Returns `{uid (32 hex), state: queued, n_items}`. Writes no tracks and no files.
- `GET ?scope=mine|all`: this editor's batches (or everyone's for `all`, admin only: 403 "only an admin can see every computer's batches"; other scope values 422). Newest first, at most 200. First returns any batch whose lease expired to `queued` (or finalises it as cancelled if a cancel was pending).
- `GET /limits`: `max_items` 500, `audio_exts`, `transcode_exts` (.ogg), `run_modes`.
- `GET /{uid}`: one batch with all items. Another editor's batch (non-admin) → 404 "no such batch" (never 403). Sweeps expired leases first.
- `POST /{uid}/cancel` (owner or admin): sweeps leases first. Already finished → `{ok, already_finished}`. Queued or with a dead lease → finalised immediately as cancelled. Held by a live machine → only flags `cancel_requested`; the machine learns on its next call (410) and stops. Tracks already live stay.
- `POST /{uid}/retry-failed` (owner or admin): 409 "<machine or 'another computer'> is still working on this batch. Stop it first, then try the failed tracks again." if a live lease exists. Otherwise failed items go back to `pending` (keeping their allocated name and track row), the batch goes back to `queued` with cancel/lease/error cleared. Returns how many were retried; nothing failed = success with 0.
- `POST /{uid}/upload-paused` body `{paused: true|false}` (owner or admin): sets the durable "hold uploads" flag.

## Ingest batches: the companion's fleet API (source: musicweb/routes_fleet.py, musicweb/fleet_auth.py, musicweb/identity.py, musicweb/ingest_batches.py)

Prefix `/api/fleet/ingest`. Called by companions with no browser session.
- **Credentials, checked on every call in this order**:
  - Machine credential: header `X-CCSync-Token` must equal `DASH_REPORT_TOKEN` (constant time; unset token means always refused) → else 403 "missing or invalid X-CCSync-Token" (logged). When mounted, the dashboard may instead stamp `X-CCSync-Fleet-Auth: shared` or `editor:<name>` (for per-editor tokens it verified); that stamp is believed only when the dashboard mount declared itself, never standalone.
  - Signed identity: header `X-CCSync-Identity` = `v2.identity.<base64 username>.<expiry>.<hmac-sha256>` signed with `DASH_SESSION_SECRET` (or any key in `DASH_SESSION_SECRET_PREVIOUS`, comma separated). Secret unset → 403 `identity_unconfigured` "this dashboard cannot verify who is calling"; bad, expired, wrong-purpose or old-format token → 403 `identity` "a valid X-CCSync-Identity is required: sign in again from the CC Sync tray".
  - If the machine credential is bound to an editor and differs from the identity → 403 `identity_mismatch` "this report token belongs to a different editor".
- **Machine name** after claim: header `X-CCSync-Machine`, or percent-encoded `X-CCSync-Machine-Pct` for names that cannot be sent plainly. If absent, the machine check is skipped.
- **"Your claim is over" answers are 410**, with `reason`: `cancelled` ("this batch has been cancelled", checked first), `finished` ("this batch is <state>"), `other_editor` ("this batch is no longer yours to index"), `other_machine` ("<machine> holds this batch now"), `lease_expired` ("this batch's lease has expired and the server has taken it back"). Unknown batch → 404; unknown item → 404 "no such item in this batch".
- `POST /batches/{uid}/claim` body `{machine, companion_version, capabilities}` (capabilities only logged): sweeps leases; not this editor's → 403 "this batch belongs to another editor"; cancelled → 410; finished → 410; another machine with a live lease → 409 "<machine> is already indexing this batch". Otherwise sets machine and a 300 s lease (state `claimed`, or stays `running`). Idempotent for the holder. Returns the batch, settings, `lease_seconds` 300, `heartbeat_seconds` 30, `library_remote_rel` "Assets/Music", audio and transcode extensions, and every item (uid, order, name, size, hash, duration, state, duplicate, source, dest_name, track_id, attempts).
- `POST /batches/{uid}/heartbeat`: extends the lease 300 s; returns `cancel_requested`, `upload_paused`, expiry.
- `POST /batches/{uid}/items/{iuid}/status` body `{state, stage_percent 0-100, error ≤2000 chars, attempts, content_hash, transcoded, probe}`: records progress. Allowed order pending → transcoding → embedding → indexed → uploading → live (repeating the same state is allowed; going backwards → 400 "an item cannot go back from X to Y"). Endings: duplicate, failed, cancelled, skipped, queued_for_base_rig; once in live/duplicate/cancelled/skipped/queued_for_base_rig nothing else is allowed (400 "item is already X; it cannot become Y"); `failed` can move on again (retry). Unknown state → 400. The first non-pending item moves the batch from `claimed` to `running`. Batch counters are recomputed from items each time.
- `POST /batches/{uid}/items/{iuid}/result` body (embedding as base64 of little-endian float32, max 32,768 chars; optional `dim`, `model`, preferred `name`, `transcoded`, `content_hash`, `size_bytes`, `duration`, `bpm`, `music_key`, `key_conf`, `lufs`, `peak_db`, `probe`, `peaks` base64 max 8,192 chars, `windows` up to 64 of `{idx, t0, t1, vector}`):
  - Allocates the final library name (unless the item already has a track, which is updated in place). Library unmounted → 503 `share_not_ready` with `retry: true`; filename check impossible → 503 `library_unavailable` (retry); 1000 collisions → 503 `too_many_collisions`.
  - Refusals: bad base64 → 422 `encoding`; byte length not a multiple of 4, empty, mismatched `dim`, or non-finite → 422 `embedding`; dimension differs from the library's → 409 `model_mismatch` "this library is indexed at N dimensions and the embedding has M; the CC Sync tray is running a different CLAP model version"; a name taken by a concurrent batch → 409 `name_race` "another batch claimed that filename first; retry" with `retry: true`; illegal transition → 400.
  - Writes the track row (embedding re-normalised to unit length), windows (bad or zero windows silently dropped; old windows replaced), waveform, item becomes `indexed`. A newly created row deletes any leftover proxy with the same id.
  - Then re-scores the whole library's tags and axes, but at most once per `MUSIC_RESCORE_MIN_SECONDS` (default 60; the first in a process always runs). Inside that window it marks the library "scores stale" and answers `scores.deferred`. A rescore failure is logged, marks stale, and is returned as `scores.error`, not as an HTTP error. On success the response carries this track's tags and axes.
  - The track is searchable immediately; its audio is not there until `uploaded`.
- `POST /batches/{uid}/items/{iuid}/uploaded` body `{size}`: no track yet → 409 `unindexed`; file not in the library under either Unicode spelling → 409 `not_uploaded` "the library does not hold this file yet"; size differs → 409 `size_mismatch` "the file in the library is not the size the CC Sync tray sent". Otherwise widens permissions to 0664, corrects the stored name to the spelling on disk if different (logged), records the real size, item becomes `live`.
- `POST /batches/{uid}/release` body `{state: done|failed|cancelled, summary}`: `done` becomes `done_with_errors` if any item failed. Summary stored as text, cut to 500 chars. On `cancelled`: unfinished items become cancelled, and the track rows of indexed/uploading items whose file is not on disk are deleted (with their proxies), unless the library looks unmounted. A cancelled release is accepted even after the lease expired (only "this editor's batch" is checked, plus a live different machine → 410 `other_machine`); already finished → `already_finished`. After any release, if scores are stale, the whole library is re-scored once (failure only logged).
- **Lease expiry** has no timer: it happens whenever the batch list, a single batch, cancel, retry or claim is called. Expired held batches go back to `queued` (machine name kept); expired batches with a pending cancel are finalised as cancelled.
- **queued_for_base_rig** item ending: accepted, but nothing is queued anywhere; the audio stays on the editor's machine.
- A helper lists batch ids with a pending cancel for an editor/machine (used by the dashboard's report reply; outside this part).

## Source-bias removal and tagging (source: musicweb/rescore.py, musicweb/vocab.py, musicweb/projection.py)

- **Vocabulary** (each label described by three captions; a label's vector is the mean of its caption vectors):
  - genre (18): orchestral, ambient, electronic, synthwave, hip hop, rock, post-rock, folk acoustic, jazz, classical, east asian, world folk, lo-fi, pop, trailer epic, choral, experimental, blues soul.
  - mood (19): tense, ominous, dark, uplifting, hopeful, triumphant, melancholy, nostalgic, peaceful, mysterious, urgent, playful, romantic, aggressive, contemplative, eerie, grand, lonely, determined.
  - instrument (17): piano, strings, solo cello, acoustic guitar, electric guitar, synth, drums, percussion, brass, woodwind, choir, electronic beat, bass, east asian str, mallets, organ, harp.
  - use_case (10): interview bed, montage, opening titles, tension build, emotional payoff, action, underscore, credits, reveal, timelapse.
  - texture (8): sparse, dense, lo-fi tape, clean, gritty, pulsing, drone, glitchy.
  - axes (4, each a high pole minus a low pole): arousal (energetic vs calm), valence (happy vs sad), tension (anxious vs relaxed), organic (acoustic vs electronic).
- **Tags kept per track**: top 3 genre, 4 mood, 4 instrument, 3 use case, 3 texture. Score = softmax (temperature 0.5) over labels after each label's similarity is standardised across the library (calibration strength 0.5); pct = percentile of that standardised value across the library.
- **Axis value**: raw = similarity to high pole minus low pole; pct = its percentile across the library.
- Every rescore replaces all tags and axes for every track in one transaction (failure keeps the previous ones and marks the library stale). Records `vocab_hash`, `tagged_at`, and clears the stale marker only if no track was added during the pass.
- **Source-bias directions**: tracks are grouped by filename shape: `ES_` prefix ("epidemic"), UUID-like, 20+ uppercase/digit characters ("ulid"), numeric ids, other. Every group with at least 8 members contributes one direction (group mean minus the rest, made mutually orthogonal). These directions are removed from track vectors for "similar" only, recomputed on every rescore.

## Drain bundles: moving base-rig results into the live index (source: musicweb/drain.py)

- A **bundle** is a small SQLite file holding the analysed results of queue rows a base-rig drain closed (track rows without ids, windows, waveforms), the rows it failed with reasons, and optionally the whole library's tags, axes and bias directions. Version 1.
- `python -m musicweb.drain apply <bundle> [--db PATH] [--no-rescore]`:
  - Index = `--db`, else `MUSIC_DB_PATH`, else the packaged default `<data>/music.db`. Missing file → "no index at <path>", exit 2. Index without the queue identity column → error telling the operator to start the app once or deploy the dashboard first, exit 2. Not a bundle or wrong version → exit 2.
  - One transaction. Each bundle row is applied only if the live queue row with that id exists, is not already done, names the same path, and (when both know it) has the same content hash; otherwise SKIPPED with the reason. Each written track is read back and must have an embedding of the declared size, else rolled back ("write not verified"). Windows replaced, waveform written, queue row marked done.
  - Failed rows mark the live queue row `failed` with the base rig's reason (same agreement checks).
  - Library-wide scores from the bundle are applied unless `--no-rescore`, or the live index was re-scored after the bundle was created ("RESCORE SKIPPED: ... Run a retag on this index instead, or apply with --no-rescore to silence this.").
  - New rows delete leftover proxies at their id.
  - Prints "applied N track(s) to <path>", "re-scored N track(s) library-wide", "parked N row(s) as failed; the ingest panel shows the reason. Nothing retries them on their own.", "SKIPPED <uid>: <reason>", and a note that the live app picks it up on its next search (older versions need `POST /music/api/reload` or a restart). Exit 1 if anything was skipped, else 0.
  - Needs only the Python standard library, except when library-wide scores are applied: that step imports the rescore module, which imports numpy.
- `python -m musicweb.drain inspect <bundle>`: prints metadata and every track uid and path.
- Export side (`--export-drain` on the indexer, below): refuses to overwrite an existing bundle file; a half-written bundle is deleted on error.

## Storage, schema and settings of the web half (source: musicweb/db.py, musicweb/config.py, schema.sql, migrations/*.sql)

- One SQLite database in WAL mode, `MUSIC_DB_PATH`, else `MUSIC_DATA_ROOT`/`DATA_ROOT` + `/music.db`, else `music/web/data/music.db`. Holds tracks, windows, tags, axes, waveforms, bias directions, the browser upload queue, batches, items and a key/value meta table.
- Schema upgrades run automatically on first connection: four migrations (track share column; upload queue; queue identity; batches and items), each applied only if its effect is missing. A database newer than version 4 is refused with "FATAL: ... newer than this app supports".
- Track paths are always stored as (share `music`, relative path); the real path is computed per host.
- Library location: `MUSIC_LIBRARY_ROOT`, else `MUSIC_SHARE_ROOT`, else `MUSIC_ROOT`, else `<CCSYNC_CANONICAL_PREFIX or P:\>Assets\Music` (written in Windows form even on Linux, where it is then symbolic).
- Proxies: `MUSIC_PROXIES_DIR`, else `<data>/proxies`; bitrate `MUSIC_PROXY_KBPS` (default 128). Indexer checkout: `MUSIC_INDEXER_DIR` (default `music/indexer`). Data folder is created at start-up, not import.
- Deleting a track row anywhere (prune, cancelled release) or creating one at a reused id deletes the proxy file for that id, best effort.
- Deleting a track removes its windows, tags, axes and waveform; queue/item references become empty.

## The indexer CLI (source: indexer/index_music.py, music_index/audio.py, music_index/features.py, music_index/clap_model.py, music_index/config.py)

Base rig only (needs torch, librosa, pyloudnorm, ffmpeg; GPU used if present, else CPU). `python index_music.py [flags]`:
- **Required index**: `--db PATH`, else `MUSIC_DB_PATH` or `MUSIC_DATA_ROOT` must be set; otherwise exits with "no index selected. Pass --db <path> ... or set MUSIC_DB_PATH ...". `--db` naming a missing file exits "--db: no database at <path>".
- `--root PATH` library folder (default: the configured library); missing → "music root not found: <root>".
- ffmpeg/ffprobe must resolve (`FFMPEG`/`FFPROBE` env or PATH) before anything decodes, else exits naming the missing tool (not needed for `--queue-status`).
- **Default run (sweep)**: walks every file under the root with an audio extension, skipping any inside a folder named `_stems`. A file is analysed if new or its size+mtime fingerprint changed (`--force`: all). `--limit N` takes only the first N files. Per file prints progress with length, BPM, key and ETA; failures print "FAIL" or "SKIP (no audio)" and continue. Then prunes, closes queue rows the sweep indexed, re-tags the whole library, prints totals.
- **Analysis of one file**:
  - ffprobe for samplerate, channels, codec; ffmpeg decode to 48 kHz mono float (900 s limit; NaN/Inf zeroed).
  - Windows: 10 s each, up to 12, evenly spaced after trimming 2% from each end; a track of 10 s or less gives one zero-padded window.
  - Each window embedded with CLAP (batch `BATCH_SIZE`, default 16) and L2-normalised; track vector = mean of windows, re-normalised; 512 numbers.
  - BPM: librosa beat tracking on the first 360 s resampled to 22,050 Hz, folded into 60 to 190 BPM, 1 decimal; none if it fails.
  - Key: chroma correlated with Krumhansl-Schmuckler major/minor profiles, e.g. "A minor", with confidence = margin over second best.
  - Loudness: integrated LUFS (pyloudnorm, only if over 0.5 s), peak dBFS (-120 for silence).
  - Waveform: 900 peak buckets scaled to the track's own maximum.
  - Duration from the decoded sample count, not ffprobe.
- **Prune**: deletes rows whose file the sweep did not see. Skipped (message "skipping the prune pass ...") with `--limit`, `--no-prune`, or `--db` without `--prune`. Refused (printed "! ...") if the scan found no files ("... a share that is not mounted, not an empty library. Nothing pruned.") or if more than max(5, 20% of the library) are missing, unless `--prune`. Prints up to 20 pruned names and suggests `python make_proxies.py --prune`.
- `--retag`: re-scores tags, axes and bias directions from stored embeddings only (seconds).
- `--peaks`: builds waveforms for tracks without one (8 kHz decode), committing every 50.
- `--fix-durations`: re-decodes every track at 8 kHz and replaces any stored duration off by more than 0.5 s; prints the 8 worst corrections and counts by extension.
- `--queue`: drains the browser upload queue: first closes pending rows already indexed by a sweep, then analyses each pending row (`--retry-failed` also failed rows; `--limit` caps). A row is parked `failed` with the reason if its path is unusable, the file is missing, or analysis fails; nothing retries a failed row unless asked. Re-tags if anything was added. Exit code 1 if any failed.
- `--export-drain BUNDLE` (with `--queue`): writes the bundle of closed and failed rows plus library-wide scores; prints counts, rows not exported and the apply command.
- `--queue-status`: prints counts, every pending row, every failed row with attempts and error, and "-> N row(s) are parked and will NOT be retried. Re-run with --queue --retry-failed once the cause is fixed." No CLAP or ffmpeg needed.
- Records the model name in the index meta at each CLAP run. If the configured CLAP model cannot load, falls back to `laion/clap-htsat-unfused` with a printed warning.
- Model weight cache: `MUSIC_MODEL_CACHE` or `HF_HOME`.

## Base-rig ingest module (source: music_index/ingest.py)

- Used by the inline mode of `POST /api/ingest`: stage, probe, re-encode check, .ogg → 320k mp3, identical-bytes check, claim a flat name, move in, analyse, write row. Creates the library folder unconditionally if missing (unlike the queued path's first-run rule). An optional whole-library hash map can be passed but nothing passes it.

## Preview proxies (source: indexer/make_proxies.py, music_index/proxies.py)

`python make_proxies.py [flags]` on the base rig (requires ffmpeg; uses the default index location, no `--db`):
- For every indexed track, writes `<proxies>/<track id>.mp3` at 128 kbps (`--kbps`), `--jobs` parallel encodes (default 4), `--limit N` first N tracks, `--root` to override the library.
- Skips a track whose proxy exists, is non-empty and is not older than the source ("already up to date"), unless `--force`.
- Skips (no proxy, original served instead) any source whose bitrate is at or below 105% of 128 kbps, whatever its codec; `--force` does not override this.
- Encode: audio only (cover art dropped), surround downmixed to stereo, mono kept, sample rate unchanged; written to `.part` then renamed. Refused as "truncated" if the proxy is more than 3% shorter than the source (re-checked against a full decode for unreliable container durations).
- Outcomes per track: generated, already up to date, skipped (already ≤128k, with codec counts), source missing, failed (reason listed). Prints bytes before/after and the ratio.
- `--dry-run`: estimates the same counts without encoding.
- `--prune` (with optional `--dry-run`): deletes proxy files whose id is no longer a track, leftover `.part` files, and non-id-named files; prints freed MB.

## Model export tools (source: indexer/export_text_encoder.py, indexer/export_audio_encoder.py, indexer/mel_numpy.py, indexer/music_models.py)

- `python export_text_encoder.py [--out DIR] [--model NAME] [--opset 17]`: exports the CLAP text half to ONNX with its tokenizer and a manifest into `<data>/text_encoder` (or `MUSIC_TEXT_ENCODER_DIR`). Built in `<out>.new`; must match the real tokenizer on all 49 check queries and reach cosine of at least 0.999 against the full model on each, else "FAIL ... Not writing it." and the old artefact stays. On success the old one moves to `<out>.prev`.
- `export_text_encoder.py --check`: re-verifies an existing artefact; if it lacked a recorded check and passes, records it ("it will load now").
- `python export_audio_encoder.py`: exports the CLAP audio half for companions to `<data>/audio_encoder` (`MUSIC_AUDIO_ENCODER_DIR`): `music-clap-audio-1.onnx`, `music-clap-audio-1.params.json`, optional `.fp16.onnx` (`--no-fp16` to skip; skipped with a note if converters are missing), and `report.md`. Refuses checkpoints with feature fusion. Requires the numpy mel front end to be bit-identical to the model's own feature extractor. Verifies against the torch model on `--tracks` (20) x `--windows-per-track` (4) library windows taken from the index (`--db`) or, with no index, from files directly in the library folder; if neither is readable (or `--synthetic`), on generated test signals, which the report records. Cosine must be at least 0.999 per window and per mean-pooled track (fp16 measured but not enforced). Prints the catalogue block to paste into `music_models.py`. `--check` verifies an existing artefact; `--print-catalogue` prints the block only. ffmpeg required unless `--synthetic`. Threads for the check: `MUSIC_AUDIO_ENCODER_THREADS` (default 8).
- `mel_numpy.py`: the audio front end (log-mel spectrogram) in numpy only, driven by the params file; refuses a params_version other than 1 and unsupported window/padding/truncation settings. Vendored by the companion.
- `music_models.py`: the catalogue of the published audio artefact: version "1", file names, sha256 and sizes (280 MB onnx, 1,355 byte params), 512 dimensions, fp32; download URL `<feed base>/<filename>`; refuses with no feed base; a "TODO-sha256" placeholder marks an unpinned (must not be downloaded) entry.

## Quality measurement (source: eval/eval.py, eval/validate.py)

- `python eval/eval.py`: reads the configured index; prints, per category, how concentrated the top-ranked label is (share of tracks whose rank-1 label is the most common one, with the top 6), and a retrieval test of 10 fixed queries each expecting a named track (e.g. "retro neon synthwave" → "Neon City"): rank, ok (≤10)/near (≤30)/MISS, top-10 hit rate, mean reciprocal rank, median rank. Queries whose track is not in the library are skipped.
- `eval.py --sweep`: copies the index to a temporary file and re-scores it at calibration strengths 0, 0.25, 0.5, 0.75, 1.0, printing label concentration for each; the real index is untouched; then prints the retrieval test.
- `python eval/validate.py`: 15 spot checks that a track named like "Solo Piano" carries an expected label in its stored tags; prints ok/MISS per track and "N/M plausible (K skipped, no matching file)".

## Not described as features

- `web/requirements.lock`, `indexer/requirements.lock`: pinned dependency lists. `pyproject.toml` (web, indexer): package metadata. `.gitignore`. `static/favicon.svg`: the tab icon. `schema.sql` and `migrations/*.sql`: the database definition (summarised above). `README.md`, `SPEC.md`, `web/DEPLOY.md`, `migrations/README.md`: documentation. `web/data/` holds the live index, proxies, staging and model artefacts (data, not tracked).

## Looks redundant or overlapping

- Two ingest paths for the same job: the browser upload to `/api/ingest` (queued for a base-rig drain, or inline on the base rig) and the companion batch flow; the page silently picks one. The queued path then needs a third mechanism (drain bundles) to get results back.
- Two duplicate defences implemented in the queued web path and again in `music_index/ingest.py` (transcode, probe), and the ffprobe/ffmpeg calls are duplicated between `routes_ingest.py` and `music_index/audio.py`/`ingest.py`.
- `_make_readable_to_the_fleet` is copied twice (routes_ingest.py and ingest_batches.py); extension lists are copied three times (routes_ingest, ingest_batches, music_index/config) plus a fallback in ingest.js.
- Three ways to refresh the search index after a change: automatic file watching, `POST /api/reload`, and explicit refreshes after writes.
- Two waveform producers on the server (indexer at analysis, `/api/peaks` on-demand fallback) plus `--peaks` backfill plus companion-supplied peaks.
- Lease expiry is swept from five different routes instead of one timer.
- `music_index/tagging.py`, `debias.py`, `vocab.py` are aliases of `musicweb` modules.
- `export_text_encoder.py --check` and `export_audio_encoder.py --check` repeat each exporter's own verification.
- Pause/Resume/Start now buttons are always shown together rather than as a toggle.
- The "similar" button appears both on the row and in the player pane.
- `/api/ingest/queue` panel ("Waiting for the indexing computer") and the batch list show two separate queues of uploads in the same drawer.
- Identity verifier `identity.py` is a vendored copy of the ytdl one; ingest batch logic duplicates b-roll's (stated in its own header).

## Claims the code does not back

- `drain.py main()`: comment says "Deliberately no fall-through to a packaged default", but with no `--db` and no `MUSIC_DB_PATH` it does fall through to `config.DB_PATH`.
- `migrations/004_ingest_batches.sql` header: an item ending `queued_for_base_rig` gets "a `pending` row there" in `ingest_queue`; the code writes no queue row (ingest_batches.py says so itself).
- `rescore.label_space` docstring: the cache key includes `vocab_hash` so that `eval.py --sweep` changing CALIBRATION cannot serve a stale space; CALIBRATION is not in `vocab_hash` and is not used by the label space at all.
- `index_music.py` after prune prints "their proxies are now orphaned: python make_proxies.py --prune", but `prune_missing` already deletes those proxies itself.
- `proxies.py`: outcome comment says ALREADY_SMALL means "source is mp3 at/below the proxy bitrate"; the rule applies to any codec.
- `export_audio_encoder.py` docstring: fp16 "~170 MB vs ~340 MB"; the catalogue records 141 MB vs 280 MB.
- `style.css` cc-spa block: "html.cc, which only the dashboard's apps group turns on"; index.html always sets it.
- README: "only `/api/search` needs CLAP and it is imported lazily" (search uses the ONNX text model by default); "migrations/ empty for now" (four exist); "Nothing here writes to W:" (ingest writes into the library); the Resolve section says the web app must run on the same machine "until port step 8" (Resolve calls already go to the companion); "a base-rig `--retag` fills the rest in" for companion tracks' bpm/key/loudness (retag only recomputes tags/axes); "the NAS turns the vector into tags, axes and a waveform" (the waveform comes from the companion, the NAS builds none in that path); "Reveal opens the file in Explorer" (it asks the companion, and its OS behaviour is outside this code).
- `routes_ingest.py` module docstring: queued items are filled in by "`index_music.py --queue`", but that only reaches the NAS rows via a pulled copy plus `drain apply`.

## Could not determine

- What the companion's `/music/send`, `/music/reveal`, `/music/status`, and `/music/ingest/{capabilities,pick,prepare,upload,progress,run,retry,control}` actually do (other part); this section lists only what the page sends and how it reads replies.
- Whether `cancel_requested_for` is reached in practice (called from dashboard `api.py`, outside this part).
- How the dashboard mount sets the login-gated flag, strips and stamps `X-CCSync-User`/`X-CCSync-Admin`/`X-CCSync-Fleet-Auth`, and exempts `/api/fleet/ingest/*` from login (outside this part).
- Whether `idle` versus `foreground` run modes behave differently anywhere but the companion (the server only stores the value).
- Exact content of the injected dashboard topbar/HUD (served by the dashboard); this sheet only paints it.
- `SPEC.md` and `web/DEPLOY.md` were not read (documentation, not executable), so their claims were not checked.


