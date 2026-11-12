# B-roll: the search app, its API, client folders and the public share page

Terms used throughout:

- **Clip**: one row in the archive index (a video file), with an id, a "share" (the source collection it was indexed from) and a relative path inside that share.
- **Segment**: a time range of a clip with a model-written visual description (what is seen, objects, setting, motion, on-screen text and its English rendering).
- **Transcript cue**: a time range of a clip with spoken words (from a local speech-to-text pass done elsewhere).
- **Proxy / preview**: the small playable MP4 of a clip served to the browser. **Sprite sheet**: a grid image of frames used for hover-scrubbing a thumbnail. **Poster**: one still image per clip.
- **Companion / tray**: the CC Sync desktop app on the editor's own computer, reachable from the browser at `http://127.0.0.1:8899`.
- **The dashboard**: the CC Sync web app that mounts this app at `/broll`; it supplies login, the top bar and the identity headers this app trusts.

## Hosting, startup and configuration
(source: main.py, config.py, db.py, Dockerfile, pyproject.toml, DEPLOY.md, schema.sql, migrations/*.sql)

- Runs as a FastAPI web app. Two ways to run:
  - Mounted inside the dashboard at `/broll` (the deployed way). In that case the dashboard's login gate protects every path except the public share prefix and the fleet ingest routes; this app has no login code of its own.
  - Standalone (DEV ONLY / fallback): `uvicorn app.main:app`, Docker image listening on port 8420, data root `/data`. Standalone there is no authentication on the search, media or editor routes at all.
- On standalone startup it creates the data root and its `proxies/`, `sprites/`, `posters/`, `sheets/` folders, creates or migrates `broll.db`, and creates `client_shares.db` best effort (a failure there is logged and does not stop startup). When mounted, this startup step does not run; the dashboard does the equivalent.
- Database `broll.db` (the archive index) is migrated forward through every known step in one startup; a database whose version is higher than this code knows (13) is a hard startup failure ("Refusing to run against a DB migrated by a newer version"). Schema and migration files are looked up first beside the repo root, then in the bundled copy; if neither exists startup fails loudly.
- `GET /` serves the search page (`static/index.html`) with `Cache-Control: no-cache`.
- `/static/*` serves every file in the static folder, always with `Cache-Control: no-cache` (browser revalidates; unchanged files cost a 304).
- `/share/assets/*` serves ONLY these seven files to the public: `style.css`, `share.css`, `share.js`, `sprite.js`, `favicon.svg`, `favicon.png`, `brand_mark.png`. Any other name is a plain 404. The `.js` files there carry `Cache-Control: no-cache`.
- Environment variables:
  - `BROLL_DATA_ROOT` (default `./data`; Docker `/data`): where `broll.db`, `client_shares.db`, `proxies/`, `sprites/`, `posters/`, `sheets/` and the shared archive tree live. Read on every use.
  - `BROLL_INGEST_TOKEN`: shared secret for the indexer's `/api/ingest/*` write routes. Unset means those routes answer 503 (no open "dev mode").
  - `DASH_REPORT_TOKEN`: shared fleet secret for `/api/fleet/ingest/*`. Unset means those routes answer 403.
  - `DASH_SESSION_SECRET`: key used to verify a companion's signed identity token. Unset means every fleet ingest call is refused 403 ("this dashboard cannot verify who is calling").
  - `DASH_SESSION_SECRET_PREVIOUS`: comma-separated retired keys, accepted (never minted) for identity verification.
  - `BROLL_DEFAULT_COLLECTION` (default `owned`): the URL slug of the "own footage" browse root; lowercased, anything not `a-z0-9_-` becomes `-`.
  - `BROLL_DEFAULT_COLLECTION_LABEL` (default `Our Footage`): what the folder tree calls that root.
  - `BROLL_CREATORS_SHARES` (default empty): comma-separated share names that count as own footage.
  - `BROLL_ARCHIVE_CREATORS_DIR` (default `Creators_Club`): top folder of the archive tree that dashboard-ingested shoots are filed under; sanitised like a filename.
  - `BROLL_SHARES`: `share:description;share:description` list, shown in the "tray + shares" panel. Purely descriptive.
  - `DASH_SITE_ORG_NAME` (default `CC Sync`): the organisation name the public share page shows.
  - `BROLL_EMBEDDING_MODEL` (default `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`): which stored embeddings semantic search uses and which model encodes the query.
- The legacy collection slug `creators_club` in a URL is still accepted and mapped to the own-footage collection; any other unknown collection value means "no filter".
- Optional dependencies and what they gate:
  - `fastembed` (not in the base install and not in `requirements.lock`): without it semantic search is unavailable. First semantic query loads the model (about 10 s) and, per DEPLOY.md, downloads about 100 MB from Hugging Face.
  - `numpy`: without it semantic search is unavailable.
  - `rapidfuzz`: without it typo correction is skipped.
  - `jieba` and `opencc`: without them Chinese word segmentation of queries and the server-side `search_norm` text are skipped (raw text only), logged once.

## Media serving (previews, sprites, posters)
(source: routes_media.py, media.py)

- `GET /media/proxy/{id}.mp4`: the clip's preview video. Served from the clip's archive path (inside the data root) when that file exists; otherwise from `proxies/{id}.mp4`. A stored path that would resolve outside the data root is ignored.
- `GET /media/sprite/{id}.jpg`: `sprites/{id}.jpg`.
- `GET /media/poster/{id}.jpg`: `posters/{id}.jpg`.
- No auth of their own (mounted, the dashboard's login gate applies; standalone, open).
- All three support HTTP Range: `bytes=a-b`, `bytes=a-`, `bytes=-n`. A malformed or unsatisfiable range answers 416 with `Content-Range: bytes */size`. A range answer is 206.
- Every answer carries a weak ETag built from size and modification time; a matching `If-None-Match` answers 304 (with or without Range).
- A missing file answers 404 "file not found".
- Streaming in 64 KiB chunks.

## Search API
(source: routes_api.py, search.py, fuzzy.py, semantic.py, normalize.py)

### `GET /api/search`
- Parameters: `q` (text, default empty), `category`, `flags`, `limit` (default 24, 1 to 200; outside that range is a 422), `offset` (default 0, not negative), `mode` (`hybrid` default, `keyword`, `semantic`; anything else is treated as `hybrid`), `fuzzy` (default true), `sources` (`all` default, `visual`, `transcript`; anything else is treated as `all`), `collection`, `shoot`, `path`.
- Answer: `results` (one page), `total` (number of matching clips), `mode_available` (for each mode: available yes/no and a reason sentence), and, only when there was query text and nothing matched, `scope_total` (how many clips the filters left to search).
- Each result: the full clip row, a `score` (null when browsing), `hits` (up to 20 per clip, best first; each with start/end time, description, highlighted snippet and `source` = `visual` or `transcript`), and `match` = `keyword` or `semantic`.

### Which clips can ever appear (search and browse alike)
- Never shown: clips with status `skipped` (editor proxy folders), `excluded` (camera originals of a proxy-only share), `ingesting` (reserved by dashboard ingest, media not yet on the NAS), and clips marked as a byte-duplicate of another clip.

### Filters (all ANDed together)
- `category`: a subject slug; matches that slug and everything under it (`military` also matches `military/naval`). The special slug `_uncategorised` matches clips with no category that HAVE been indexed (not clips still waiting for indexing).
- `collection`: `downloads` or the own-footage slug. Own footage = shares in `BROLL_CREATORS_SHARES`, plus shares the indexer pushed as proxy-only, plus shares recorded with the own-footage collection by dashboard ingest. Downloads = every other share. With no own-footage shares known, the own-footage filter matches nothing and downloads matches everything.
- `shoot`: `share` or `share::A / B / C`. Matches that share, and, if a path is given, clips whose path starts with that folder exactly at folder boundaries (`Day 1` does not match `Day 10`), also allowing a `Proxy` folder at any position in the path.
- `path`: `share` or `share::folder/sub`. Matches that share and clips under exactly that folder (folder boundary, so `B-roll` does not match `B-roll Archive`).
- `flags`: comma-separated quality flags; any clip carrying ANY of them is excluded. The flag vocabulary is `shaky`, `soft_focus`, `overexposed`, `underexposed`, `noisy`, `rolling_shutter`.
- `sources`: `visual` searches only what is seen (segments, including burned-in on-screen text) and only segment embeddings; `transcript` only what is said (transcript cues) and transcript embeddings. A clip with no surviving hit is dropped.

### Browse (no query text)
- Returns filtered clips with no scoring, newest first (highest id first), with no hits. `total` is the full filtered count.

### How query text is read
- Words are separate terms; text in double quotes is one exact phrase. All terms must match (AND). Any punctuation the user types is treated as literal text, never as query syntax.
- English is matched with stemming (`surf` matches `surfing`).
- Chinese is matched two ways: by substring (only for terms of 3 or more characters), and by word-segmented, script-normalised text, so 2-character words match and Traditional and Simplified script find each other. An unquoted Chinese term longer than 2 characters is also split into words by an additional pass (so `同志伴侶` finds clips indexed as `同志` and `伴侶`); quoting keeps it as one unbroken phrase.
- Text searched (visual): description, objects, setting, English on-screen text, original on-screen text, normalised text. Text searched (spoken): transcript text and its normalised form.

### Ranking, as a user can observe it
- `keyword` mode: four text indexes (English visual, Chinese visual, English spoken, Chinese spoken), each capped at its best 1000 rows; results are combined by rank position (reciprocal rank fusion with constant 60), so a clip found by several indexes moderately well can outrank one found by a single index strongly. Clips are ordered by their single best-scoring moment; ties by lower id.
- `hybrid` mode (default): exactly the keyword result set and order, then up to 5 extra clips found only by meaning ("semantic"), ranked by similarity, always listed after every keyword result. Semantic hits on clips keyword search already found are ignored entirely (they never reorder keyword results). A semantic hit counts only at cosine similarity 0.50 or above. If the query is mostly Chinese characters and keyword search found nothing, no semantic clips are added at all.
- `semantic` mode: meaning only, no keyword pass, no 5-clip cap, no Chinese restriction, still the 0.50 floor; considers the best 200 candidate moments after filters.
- Fuzzy fallback (when `fuzzy` is on, in keyword and hybrid modes only): runs only when the exact keyword pass found fewer than 5 distinct clips. It adds, as extra ranked sources:
  - prefix matching for terms of 5 or more characters (`ambul` finds `ambulance`); shorter terms are not expanded; skipped when it would be identical to the exact query;
  - the Chinese word-split pass described above;
  - typo correction: each term of 3 or more characters that is not already a known word is replaced by the closest word from the archive's own vocabulary, within 3 characters of length and with an edit-similarity score of at least 82 out of 100 (`ambluance` becomes `ambulance`).
  - Fuzzy hits never replace the display text of an exact hit.
- Snippets: matched words are wrapped in highlight markers; the page turns them into highlighted text after escaping everything else.
- Caches (background-free): the semantic vector matrix and the typo vocabulary are built on first use and rebuilt when the archive changes (a change counter bumped by every write that touches segments, cues or embeddings, plus row counts and highest ids).

### Mode availability
- Keyword is always available. Semantic is unavailable, with these exact reasons: "Meaning-based search is not available on this server: numpy is missing.", "Meaning-based search is not available on this server: the query model is not installed.", "No clips have been prepared for meaning-based search yet, so it can only find nothing." Hybrid is always available; when semantic is off it carries "Keyword only right now: the meaning-based half of this search is not available."

### `GET /api/videos/{id}`
- 404 "video not found" for an unknown id. Otherwise: the full clip row, all segments and all transcript cues in time order, themes (model-written phrases), quality flags.
- Adds what "Send to Resolve" needs: `insert_share` and `insert_rel_path`, and an `insert` object:
  - Clip not yet in the archive tree: the clip's own share and path.
  - Clip in the archive tree whose preview is not in a `Proxy` folder: share `broll`, the preview path itself, no original.
  - Normal case: share `broll`; the "original" is the single file beside the `Proxy` folder with the same base name (names compared after Unicode normalisation, so Mac-uploaded names match); zero or several candidates means no original (several is logged). The "editing proxy" is a single `.mov` of the same name inside `Proxy` that is not the preview itself.
  - `known: false` when either folder could not be read (for example the dataset unmounted); in that case `original_is_edit_weight` is forced to true.
  - `original_is_edit_weight`: whether the clip's own file is light enough to edit with: H.264, HEVC or any ProRes, at or below 1080 lines and at or below 12,000,000 bits per second; null when the bitrate (or a number) is unknown.
  - `geometry`: width, height, fps, frame count, start timecode.
  - When no original was found but dashboard ingest says the original is still uploading (item `proxies_live`, or `live` with original not sent, and the batch was set to upload originals), `original_rel` is filled with where it will land and `original_pending: true` is added.

### `GET /api/categories`
- Every subject category (slug, label, description), sorted by slug.

### `GET /api/shares`
- The `BROLL_SHARES` list as `{share, description}`.

### `GET /api/tree` (the folder browser data)
- Two roots, always in this order: Downloads (label "Downloads") and the own-footage root (label from config).
- Downloads is organised by subject: top-level groups (label = slug with dashes as spaces, title-cased) containing leaf categories (category labels), groups and leaves sorted by clip count descending, and an "Uncategorised" group always last if any indexed clip has no category. Counts here include only fully indexed clips. The Downloads root's total counts every browsable clip outside own-footage shares (so it can exceed the sum of its folders).
- The own-footage root is organised by shoot: one group per share, sorted by clip count descending; under it the share's real folder tree up to 5 levels deep, alphabetical, with any folder named `Proxy` left out. Counts are the same browsable clips a click returns.
- Folders with no clips are omitted.

## The search page: header and controls
(source: index.html, app.js, cc_spa.js, style.css)

- Page title "CC SYNC // B-ROLL". On load it fetches the dashboard's top bar (`../partials/topbar?current=broll`) and replaces the fallback header with it; if that fails, is redirected (expired session) or is not the dashboard's markup, the fallback header stays: "CC SYNC // B-ROLL" and a "[ DASHBOARD ]" link to `/`. A 3-second safety timer ends the space reserved for the top bar. On every load it deletes a retired cookie `ccsync_ui_effective`.
- The header stays at the top while scrolling; its measured height is tracked continuously so the folder rail sits just under it.
- Search box (placeholder `search segments… e.g. sailors pier "harbor exercise"`): searches 250 ms after typing stops; resets to page 1. Typing replaces the browser history entry rather than adding one.
- Category drop-down: "All categories" plus every category, indented by depth. Choosing one clears any path filter, resets to page 1, adds a history entry and searches. It shows blank while browsing own footage (shoot folders are not categories).
- Mode buttons Hybrid / Keyword / Semantic: switch mode, page 1, search. A mode the server cannot run is greyed and disabled, with the reason as its tooltip. If the page is in an unavailable mode it switches to Hybrid, repeats the search and shows a warning toast: "<reason> Switched to Hybrid." or "... Switched to Hybrid, which is searching by keyword only for now."
- Source buttons All / Visuals (tooltip "Visuals: what is seen on screen, including burned-in on-screen text") / Transcript (tooltip "Transcript: what is said (spoken word)").
- "fuzzy" checkbox, on by default.
- "hide flagged:" checkboxes, one per quality flag (shown with the first underscore as a space): ticking hides clips with that flag.
- Mode, sources, fuzzy and hidden flags are NOT kept in the URL and reset to defaults on reload.
- "+" button (tooltip "Add clips to the archive (or drag clips/folders anywhere on this page)"): toggles the ingest drawer.
- "client folders" button: toggles the client folders drawer.
- "tray + shares" button: opens the tray and shares drawer.
- While a search is in flight the grid is dimmed, marked busy for screen readers, and "Searching..." appears in the line above the grid. Only the newest search may paint; an older answer arriving later is discarded.
- A failed search shows an error toast "Search failed: <message>".
- If any API call answers 401 while the page is under `/broll`, it shows "Session expired, signing in again…" and goes to `/login?next=<this path>`.

### Terminal look (always on in this page)
- The page always carries the terminal look. Four areas are "windows" with a title bar: search, browse, results, clip. Clicking a title bar folds or unfolds that window; the folded state is remembered per page path in browser local storage (`ccsync.spafold:<path>`).
- Button labels written as `[ LABEL ]` are shown as plain sentence-case words; bracketed labels inside running text are shown in quotes.
- Element tooltips are shown as a styled tip on hover or keyboard focus, and on tap for non-controls on touch screens; Escape or scrolling hides it.
- Confirmation questions use a styled dialog with "Cancel" (focused) and "Go ahead" instead of the browser's own confirm.
- The clip detail opens beside the grid (the grid keeps its place and scroll). Below 1100 px wide the detail drops below the grid; below 760 px the folder tree stacks above the grid and cards become fluid.
- Below 700 px wide: header rows wrap, the folder rail becomes a short scrolling shelf (max 32% of the screen height) above the grid, the detail view is one column.

## The search page: folder tree, results grid and pager
(source: app.js, sprite.js, style.css)

- Folder rail ("Browse" with a "clear" button, tooltip "Show everything"): shows each non-empty root with its total, then nested folders with counts and an expand caret (no caret on folders with no children). A folder's children show only when it or a descendant is selected. Tooltip on each folder is its slug.
- Clicking a folder selects it (and its root). Clicking the folder already selected moves up exactly one level; clicking an already-selected root with no folder clears the filter. Selecting a folder clears any path filter, resets to page 1 and adds a history entry. "clear" selects nothing.
- Own-footage folders filter by `shoot`; Downloads folders filter by `category`.
- Line above the grid: `search: "<q>"`, `folder: <root> / <folder>`, `folder: <share>/<path>`, joined by "  ·  ", or "browsing all videos". When a path filter is on, a "clear folder" link appears.
- Cards are thumbnails only (240 px wide, height taken from the sprite sheet geometry). Tooltip: "<filename> - <category or category hint or uncategorised>". Duration badge (m:ss) bottom right.
- Poster loads lazily; if it fails, a striped "no preview" placeholder replaces it.
- Hover-scrub: moving the pointer across a thumbnail shows the frame at that horizontal fraction of the clip. The sprite sheet is fetched only on first pointer contact.
- Search results instead show the frame of the best hit permanently (sheet fetched when the card comes within 400 px of the screen), and snap back to it when the pointer leaves.
- Sprite geometry: uses the sheet's recorded geometry when present; otherwise assumes 10 columns, 240 px cells, cell height from the source aspect ratio (135 if unknown), one frame every 2 seconds, or duration/240 for clips longer than 8 minutes (max 240 frames).
- Clicking a card opens the clip detail at its best hit's start time (browse results open at 0).
- Semantic-only results get a dashed border and appear after a "Related" heading spanning the grid.
- Each card has a hover-only "+" in the top right (always visible on touch screens and when focused) that opens the client-folder popover without opening the clip.
- Pager: "← prev", "<from>–<to> of <total>", "next →"; 24 per page; each press adds a history entry.
- Empty grid:
  - Browsing: "There are no clips in <scope>." where scope is the root/folder/path names or "the whole archive".
  - Searching: `Nothing matched "<q>" in <scope>.`, then "N clips were searched." (or "1 clip was searched."), then "Try fewer words, or switch to Semantic search, which finds meaning rather than words."
  - If the mode is not Keyword and semantic is unavailable, its reason in red.
  - Shortcut links, each only when relevant: "switch to Semantic search", "clear the folder filter", "stop hiding flagged clips", "turn fuzzy matching back on".

### Browser history and deep links
- The address hash holds `q`, `cat`, `coll`, `path`, `off` (page offset), `v` (open clip id) and `t` (seconds the clip was opened at). Reloading or following such a link restores the search and reopens the clip. Back and Forward walk folder clicks, pages and clip openings. Search-hit seekbar bands are not restored from a link.

## The clip detail view
(source: index.html, app.js, style.css)

- Header button: "← back to results" (classic placement) or "close this clip" (beside the grid). It uses browser Back when the detail was a history entry, so both behave the same.
- Player: the preview video, no native controls. Opens at the hit time once metadata is in.
- Metadata panel:
  - Title: filename.
  - Path line: the share and every folder level are clickable, each filtering the grid to that folder (clears the query); then the filename, duration and fps ("@ ?fps" when unknown).
  - "category: <slug>" clickable: filters to that category, clears query, path and root. "none" when absent.
  - "themes:" each clickable: searches for the theme as a quoted phrase.
  - "flags: ..." listed (not clickable).
- "Visual segments" list: timecode range (HH:MM:SS:FF, at the clip's fps or 24 if unknown), description, on-screen text in quotes and its English rendering. Clicking seeks there and plays.
- "Transcript" list (only when the clip has cues), in green: timecode range and spoken text; clicking seeks and plays.
- Seekbar:
  - Amber bands for the search hits that opened the clip (minimum width 0.5% of the bar; a hit without an end is drawn 1 s long).
  - Green ticks at each visual segment start.
  - White (cyan in terminal look) playhead.
  - Red IN and OUT flags and a shaded range between them.
  - Positions use the loaded video's real duration first, then the stored duration.
  - Press-and-drag on the bar seeks absolutely (pauses while dragging, resumes if it was playing); left button only.
- Picture gestures: press-and-drag horizontally scrubs relative to the start point (full width = full clip) after moving 4 px; a click without moving toggles play/pause. Seeks during a drag are coalesced so the picture keeps up.
- Transport readouts: TC (current), IN, OUT, RATE.
- Keyboard (only while a clip is open, not while typing in a field, and not while any drawer or the popover is open or focused):
  - Space or K: play/pause.
  - L: play forward; repeated L steps 1x, 2x, 4x, 8x.
  - J: play backward (simulated by stepping back every 50 ms); repeated J steps 1x, 2x, 4x, 8x. Stops at 0.
  - Left / Right arrow: pause and step one frame back / forward.
  - I / O: set in / out point at the current position.
  - Enter: Append to Timeline (not when a focused button or link would take the Enter). Shift+Enter: Place at Playhead.
  - Keyhelp line: "space/K play/pause · J/L shuttle · ←/→ ±1 frame · I/O set in/out · Enter append · ⇧Enter place at playhead".
- Buttons: "Append to Timeline ⏎", "Place at Playhead ⇧⏎", "+ client folder" (opens the popover).

## Send to Resolve
(source: app.js)

- Requires both in and out points: otherwise error toast "Set both an in point (I) and an out point (O) first." In and out may be set in either order; the earlier one is used as in. If they round to the same frame or less: "Out point must be after in point."
- Sends `POST http://127.0.0.1:8899/insert` with share, path (archive identity when known), in frame, out frame, fps (24 if unknown), mode (`append` or `playhead`) and the `insert` object.
- One send at a time per page; both buttons are disabled during a send. While another clip is still being sent, the buttons of other clips carry the tooltip `Still sending "<name>" to Resolve. This clip can go when that one has finished.`, and pressing shows a warning toast saying the same.
- If the tray answers "downloading": toast "Clip isn't on this computer yet: syncing it down, then inserting.", the button reads "SYNCING <n>%" (or "SYNCING…"), and the request is repeated every 1.5 s with no time limit.
- If the tray answers "busy" (or an older "already downloading" refusal): toast "Waiting for this computer's other downloads to finish.", button "WAITING…", repeats after the tray's `retry_after` (minimum 1 s, default 1.5 s), giving up after 15 minutes with "This computer has been busy with other downloads for a while. Try again when they have finished."
- Unreachable tray: error toast "Couldn't reach the CC Sync tray. It may not be running, or your browser blocked the connection (look for a “local network” permission prompt, or allow it in site settings). Self-test: open http://127.0.0.1:8899/status - if that shows ok:true, it's the browser, not the CC Sync tray. Downloads are in Settings."
- Any other refusal: error toast with the tray's message, or "The CC Sync tray returned HTTP <n>". For Place at Playhead on an old tray answering "not implemented yet": "This CC Sync tray build predates Place at Playhead. Take the update your tray offers, or use Append."
- Success: success toast with the tray's message or "Sent to Resolve."
- When the editor has moved to another clip, every send toast is prefixed `"<filename>": `.

## Toasts (all pages built on app.js)
(source: app.js, style.css)

- Bottom-centre stack. Error toasts stay until dismissed (× button); at most 4 error toasts are kept. Other toasts stay 60 ms per character, between 5 and 15 seconds. An identical toast replaces its earlier copy. Toast text can be selected and copied.

## Tray and shares drawer
(source: index.html, app.js)

- Right-hand drawer "Tray and shares" with "× close". No Escape key.
- "Shares": each configured share and description; "no shares configured" or "failed to load shares". Explanatory text about mount paths in `~/.broll-companion.json` and the `broll` share.
- "CC Sync tray" status: square dot and text. Calls `http://127.0.0.1:8899/status` on open and on "recheck": "connected (Resolve: yes|no, v<version>)", "the CC Sync tray reports a problem", or "not reachable: the CC Sync tray is not running, or the browser blocked local connections (self-test: open http://127.0.0.1:8899/status)".

## Client folders: the editor's API
(source: routes_client_folders.py, client_folders.py, schemas.py, routes_batches.py require_user/is_admin)

- A **client folder** is a titled, ordered set of clips with a public link `<base>/broll/share/<token>/`. Stored in its own database file `client_shares.db` beside `broll.db` in the data root (so replacing the search index never removes folders).
- Every route requires the `X-CCSync-User` header stamped by the dashboard from the login session; missing or blank answers 401 "not signed in". Admin status comes from `X-CCSync-Admin: 1`.
- Every signed-in editor can see, edit, revoke and delete every folder (they belong to the studio); `created_by` is recorded and shown, not enforced.
- Limits (exceeding is a 422 with the message, never silent truncation): title 120 characters (required, "a folder needs a title"), description 2000, contact 200, clip caption 500, clips per folder 500, clip ids per add request 1 to 500, ids per reorder up to 500.
- Token: 22 random URL-safe characters (128 bits), stored as typed so the link can be copied again any time. Tokens outside the pattern `[A-Za-z0-9_-]{16,64}` are never looked up.
- Folder status: `revoked` (revoke time set), else `expired` (expiry time reached), else `live`.
- Routes:
  - `GET /api/client-folders` (also with trailing slash): every folder, newest first, each with clip count, status and `share_path`; plus `public_base_url`, `share_path` (`/share/`), `org`, `user`, `is_admin`. With `?video_id=N`, each folder also carries `contains` (whether it holds that clip).
  - `POST /api/client-folders` body `{title, description?, contact?, expires_at?}`: creates; 201. Expiry must be an ISO date/time (a time without zone is taken as UTC), else 422 "expires_at is not an ISO date/time".
  - `GET /api/client-folders/settings`: `{public_base_url}`.
  - `PUT /api/client-folders/settings` body `{public_base_url}`: admin only (else 403 "only an admin can change the public link base"). Value must be `http(s)://host[:port]` with no path; trailing slash removed; blank clears it; anything else 422 "the public base must be an origin like https://nas.example.ts.net:8443 (scheme and host, an optional port, no path)".
  - `GET /api/client-folders/{id}`: the folder plus its clips (see re-resolution below); clips that can no longer be found are listed with `missing: true`. 404 "no such client folder".
  - `PATCH /api/client-folders/{id}`: change only the fields sent; `"expires_at": null` clears the expiry (never expires).
  - `DELETE /api/client-folders/{id}`: deletes the folder and its clip list; 204.
  - `POST /api/client-folders/{id}/revoke`: link dead until reactivated.
  - `POST /api/client-folders/{id}/reactivate`: clears the revoke.
  - `POST /api/client-folders/{id}/rotate`: new token; old link dead immediately; also clears a revoke.
  - `POST /api/client-folders/{id}/items` body `{video_ids}`: appends clips in the order given, skipping ones already present; answers `{added, already, n_items}`. Pressing twice is not an error. Unknown clip: 422 "clip N is not in the archive index". Over the 500 cap: nothing is added and 422 says "a client folder holds at most 500 clips. This one has X, so there is room for Y more and Z new clips were sent. Nothing was added."
  - `DELETE /api/client-folders/{id}/items/{video_id}[?item_id=]`: removes; 404 "that clip is not in this folder".
  - `PUT /api/client-folders/{id}/items/{video_id}/note[?item_id=]` body `{note}`: sets the caption the client sees.
  - `PUT /api/client-folders/{id}/order` body `{video_ids}`: sets display order; ids not listed keep their relative order after the listed ones; ids not in the folder are ignored (a stale list cannot delete anything).
- Clip identity survives index rebuilds: each item stores the clip id, its share and path, and its content hash. When showing a folder, an item is matched to the current index by id (only if share and path still agree), else by share and path, else by content hash if exactly one clip in that share has it; otherwise it is missing. Items found by hash have their stored path updated; items whose clip now has a different id are re-stored under the new id when that number is free (both best effort, silently skipped if the database is busy). If two items resolve to the same clip, only the first is shown.
- On first open of an older ledger the database adds the hash column and fills hashes from `broll.db` (retried on each open until it completes). A ledger newer than this code is a hard failure.
- Any database error while opening the ledger is logged and does not take the routes down.

## Client folders: the drawer and the card popover
(source: clientfolders.js, index.html, style.css)

- "client folders" header button toggles a right-hand drawer "Client folders" (closes the ingest and tray drawers when it opens). Intro text: previews only, no login for the client.
- List view: "+ New folder", "refresh". If no public base is set, an amber notice: "No public link base is set: links only work for people on the tailnet. Set it below once Funnel is on." (admins) or "... Ask an admin (docs/CLIENT_FOLDERS.md)." (others). Empty: "No client folders yet. Make one, then add clips from the + on any thumbnail." Each row: title, status chip (live green with expiry tooltip, revoked red, expired amber), "<n> clips · by <user> · opened Nx" or "never opened". Clicking a row opens it. Load failure: "Could not load client folders: <message>".
- Admin-only section "Public link base": URL field and "Save" (toasts "Public link base set to <url>", "Public link base cleared", or "Not saved: <message>").
- "+ New folder": browser prompt "Name for the new client folder (the client sees this):"; blank warns "A folder needs a title"; success "Created "<title>"" and opens it; failure "Could not create the folder: <message>".
- Folder view:
  - "← all folders".
  - Title and status chip.
  - "Client link": read-only field with the link (public base origin if set, otherwise this dashboard's own address), "Copy" (toast "Link copied"; if the clipboard is not allowed, selects the field and warns "Copy failed: select the link and press Ctrl+C"), and "open" (new tab, adds `?preview=1` so the curator's look is not counted as a view).
  - Note under the link: revoked text, expired text, "Reachable inside the tailnet only until an admin sets the public link base.", or "Opened N time(s), last <date>." / "Not opened yet.".
  - "Revoke link" (confirm: Revoke this link? ...) or "Reactivate link" when revoked; "New link" (confirm: "Issue a new link? The old one stops working immediately."). Toasts "Link revoked" / "New link issued" / "Link reactivated" / "Failed: <message>".
  - Details form: Title, "Description (shown to the client)", "Contact for licensing (email or a line of text)", "Link expires" (keep current / never / in 7 days / in 30 days / in 90 days; computed from now), "Save details" (toasts "Saved" / "Not saved: <message>").
  - "Clips (N)": each row has the poster (click opens that clip in the archive detail view), name and duration, a caption field (placeholder "caption the client sees (optional)", saved when the field changes, a green "saved" mark for 1.8 s, error toast "Caption not saved: <message>"), ▲ / ▼ to reorder (saved immediately; "Order not saved: <message>"), ✕ to remove ("Not removed: <message>"). Missing clips are shown dashed as "<filename> (no longer in the archive index)" with only ✕ and arrows. Empty: "Empty. Hover any thumbnail in the grid and press its + to add it here."
  - "Delete folder" (confirm "Delete "<title>" and its link? This cannot be undone."); toasts "Folder deleted" / "Not deleted: <message>".
- The Escape key does not close this drawer.
- Popover (from a card's "+" or the detail view's "+ client folder"): "Add to client folder", one checkbox per folder (ticked if it already holds the clip) with the clip count. Ticking adds (toast `Added to "<title>"`), unticking removes (toast `Removed from "<title>"`); failure reverts the tick and toasts "Failed: <message>". "+ new folder…" creates a folder and adds the clip (if the add fails: `Folder "<title>" was created, but the clip was not added: <message>`). "manage folders" opens the drawer. 401 shows "Sign in to use client folders". It is placed below or above the anchor, whichever has room, 260 px wide, scrolling inside. Closes on any click outside or Escape.

## The public share page (what a client sees)
(source: routes_share.py, share.html, share.js, share.css, share_gone.html, sprite.js, client_folders.py, media.py)

- No login. Everything under `/share/<token>/` is answered on the token alone, read only. The dashboard lets `/broll/share/` through without a session; that prefix is the only one an operator needs to publish past the private network.
- Every public answer carries `X-Robots-Tag: noindex, nofollow, noarchive` and `Referrer-Policy: no-referrer`. Pages and JSON are `private, no-store`; media is `private, no-cache` with ETags (a revoked link stops serving at the next fetch).
- A dead link (revoked, expired, never existed or malformed) is the same 404 on every route. Liveness and membership are checked on every request.
- Routes:
  - `GET /share/{token}`: 303 to `{token}/` (relative). Dead link: the "not available" page.
  - `GET /share/{token}/`: the viewer page. Dead link: the "not available" page.
  - `GET /share/{token}/api/folder`: title, description, contact, org name, expiry, clip count, and the clips (only id, duration, fps, width, height, codec, shot date, sprite geometry, display name = file name without extension, caption). Never paths, share names, transcripts, themes or flags. Counts as one view (view count +1, last viewed time) unless the request carries a dashboard user stamp (a signed-in editor) or `?preview=1`.
  - `GET /share/{token}/api/videos/{id}`: one clip's public fields, its caption, and its visual segments (start, end, description, setting, motion). 404 if the clip is not in the folder.
  - `GET /share/{token}/media/proxy/{id}.mp4`, `.../sprite/{id}.jpg`, `.../poster/{id}.jpg`: the same files and Range handling as the editor media routes, only for clips in the folder.
- "Not available" page (404): "THIS LINK IS NOT AVAILABLE", "The footage preview you were sent has been closed, has expired, or the address is not quite right.", and either "Please contact whoever sent it to you for a fresh link." (unknown token) or, for a revoked or expired folder, "Please ask <creator> at <contact> for a fresh link." / "Please ask <creator> for a fresh link." / "Please contact <contact> for a fresh link." Nothing else about the folder is shown.
- Viewer page:
  - Header: product mark, "<ORG> // PREVIEW" (org upper-cased; "Footage" until loaded), clip count "N clip(s)". Browser tab title "<title> - footage preview".
  - Title, description, contact line "To licence any of this footage, contact <contact>." (an email address becomes a mailto link with subject "Licence enquiry: <title>").
  - How-to: "Tap or click a clip to play the preview and see what is in it. On a computer, hover over a thumbnail to scrub through it. Previews are low resolution. Full-quality masters are supplied on licence."
  - Grid of cards: poster, hover-scrub (sheet fetched on first pointer), duration badge, caption "<name> - <caption>" (up to 3 lines). Empty folder: "This folder is empty."
  - Footer: org name, "  ·  this preview is available until <local date>" when an expiry is set, and the contact line.
  - Load failure: a 404 shows "This link is not available" / "The preview you were sent has been closed or has expired. Please ask whoever sent it for a fresh link."; any other failure shows "The preview could not load just now" / "This is usually brief. Please try again in a moment." with a "Try again" button that reloads.
  - Clicking a card opens the detail: "← back to the folder", "← prev" / "N / total" / "next →" (disabled at the ends), a video player WITH native controls (download, remote playback and picture-in-picture disabled, plays inline on phones), title, "<w>x<h> · <fps> fps · <m:ss> · shot <date>", caption in italics, "What is in this clip" segment list (m:ss range, description · setting; click seeks and plays; "No description available." when none).
  - Clip removed while open: "This clip is no longer in this folder. Refresh the page to see what is." Other playback failure: "This clip could not be played just now. Refresh the page to see what is in this folder."
  - Keys in the detail: Space play/pause, Left/Right previous/next clip, Escape back to the folder. The key help line is hidden on touch devices.
  - The address hash `#v=<id>` opens that clip directly; Back from a clip returns to the grid (prev/next replace rather than add history entries).
- Narrow screens: long names and org names wrap; below 860 px the detail is one column.

## Dashboard b-roll ingest: the browser's API
(source: routes_batches.py, ingest_batches.py, archive_names.py, schemas.py, config.py)

- A **batch** is one drop of clips an editor asked to add to the archive; the editor's own computer's tray does the transcoding, describing with a local model and uploading. **Items** are the clips in it.
- Every route needs the dashboard's `X-CCSync-User` stamp (401 "not signed in"). Another editor's batch answers 404 "no such batch" unless the caller is an admin.
- Shoot name (`share`): must already be what the server would make of it: characters Windows forbids (`< > : " / \ | ? *` and control characters) replaced by `_`, trailing dots and spaces removed, capped at 90 characters, slashes replaced. Otherwise 422 "the shoot name must be '<suggestion>' (Windows forbids some characters, and the archive caps a name at N characters here)" with `reason: share_name` and the suggestion. Chinese and other scripts are kept.
- Settings: `tier` `good` (default) or `best`; `run_mode` `idle` (default) or `foreground`; `upload_originals` (default true); `keep_subfolders` (default true); `transcribe` must be false (else 422 "transcription is not available yet (phase 2)"). An unknown tier or mode is a 422.
- `POST /api/ingest-batches/precheck` `{share, keep_subfolders, items}`: per item, the name it would get in the archive (`final_name`, a preview only; nothing reserved) and, when the item's partial hash matches an existing clip, `duplicate_of` and that clip's file name. Duplicates are only reported, never skipped by the server.
- `POST /api/ingest-batches` `{share, collection?, settings, items}`: creates a queued batch; collection defaults to own footage. 1 to 2000 items (422 "a batch needs at least one item" / "a batch may hold at most 2000 clips (N were sent)"). Item names up to 255 characters, sub-folder up to 1024, each path component sanitised and `.`/`..` dropped; the sub-folder is emptied when keep-subfolders is off. Answers `{uid, state: queued, n_items}`. Batch ids are 32 random hex characters.
- `GET /api/ingest-batches?scope=mine|all`: newest first, up to 200. `all` needs admin (403 "only an admin can see every computer's batches"); other scope values 422. Sweeps expired leases first.
- `GET /api/ingest-batches/{uid}`: the batch and its items.
- `POST /api/ingest-batches/{uid}/cancel`: owner or admin. Already finished: answered `already_finished: true`. A batch no machine holds is cancelled immediately; a held batch gets a cancel request the machine learns on its next heartbeat or report.
- `POST /api/ingest-batches/{uid}/retry-failed`: owner or admin. Refused 409 "<machine> is still working on this batch. Stop it first, then try the failed clips again." while a machine holds a live lease. Otherwise puts every `failed` and every "original still owed" item back to pending and the batch back to queued, keeping their reserved names; answers how many.
- `POST /api/ingest-batches/{uid}/upload-paused` `{paused}`: holds or releases uploads while indexing continues.
- Batch states and their words: queued "waiting to start"; queued with a known machine "waiting: <machine> stopped answering <ago>"; claimed "starting on <machine>"; running "indexing on <machine>"; a pending cancel "stopping"; done "finished"; done_with_errors "finished, N could not be indexed"; cancelled "stopped"; failed "could not run". "ago" is "Ns ago" under 90 s, "Nm ago" under 90 minutes, else "Nh ago", or "never".
- Item states, in order: pending, proxying, framing, describing, indexed, uploading, proxies_live (shown as "original still owed"), live; endings: duplicate, failed, cancelled, skipped. Items may only move forward; `failed` may go to any state (retry); live, duplicate, cancelled and skipped are final.
- Lease: a claim lasts 300 s and the tray heartbeats every 30 s. There is no timer: expired leases are swept whenever anyone lists batches, reads one, cancels or claims. An expired lease sends the batch back to queued (keeping the machine name); an expired lease on a batch with a pending cancel finalises it as cancelled.

## Dashboard b-roll ingest: the tray's (fleet) API
(source: routes_fleet.py, fleet_auth.py, identity.py, ingest_batches.py)

- Machine-to-machine; all POST, all under `/api/fleet/ingest/batches/{uid}/...`.
- Authentication, in order: the shared `X-CCSync-Token` (or, when mounted, the dashboard's stamp saying it accepted a per-editor token), else 403 "missing or invalid X-CCSync-Token"; then `X-CCSync-Identity`, a signed identity token (current or retired key, purpose "identity" only, unexpired), else 403 "a valid X-CCSync-Identity is required: sign in again from the CC Sync tray"; a per-editor token belonging to a different editor than the identity is 403 "this report token belongs to a different editor".
- Machine name: header `X-CCSync-Machine`, or `X-CCSync-Machine-Pct` (percent-encoded, for non-Latin names). Absent means the machine check is skipped.
- Every call after claiming requires: this editor's batch, held by this machine, live lease, no pending cancel; otherwise 410 with reason `cancelled`, `finished`, `other_editor`, `other_machine` or `lease_expired`.
- `claim` `{machine, companion_version, tier, capabilities}`: 404 unknown; 403 another editor's; 410 cancelled or finished; 409 "<machine> is already indexing this batch" when another machine holds a live lease; 409 "another batch claimed one of these names first; retry" on a name race. Otherwise, in one step: reserves each item's archive name, creates its hidden clip row, records the shoot as own footage, sets the lease. Repeating the claim from the same machine returns the same work order. Answer includes settings, lease 300 s, heartbeat 30 s, archive location `Assets/B-roll Archive`, the category list and every item's archive folder and name.
- Archive naming: `<Creators_Club>/<shoot>/<sub-folders>/<name>`, preview at `.../Proxy/<name>.mp4`, editing proxy `.../Proxy/<name>.mov`; a name already published or reserved in that folder (case-insensitive, extension ignored) gets `_2`, `_3`, and so on. Names are capped at 90 characters.
- `heartbeat`: extends the lease 300 s; answers whether a cancel is requested and whether uploads are paused.
- `items/{iuid}/status` `{state, stage_percent, error, attempts, hash, probe}`: records progress (400 on an illegal transition or unknown state). Probe values (duration, fps, size, codec, shot date, frames, start timecode, bitrate) go onto the item and the clip. The first non-pending item moves the batch from claimed to running.
- `items/{iuid}/result` `{segments (max 500), themes (max 64), quality_flags (max 16), category_hint, model, probe fields, sprite geometry}`: replaces the clip's segments, themes and flags, computes searchable Chinese text server side, marks the item indexed. The clip stays hidden.
- `items/{iuid}/uploaded` `{files, original_uploaded, edit_proxy_rel}`: the server checks each file exists in the data root, is not empty and has the declared size; the preview is always required, the original when said uploaded, the editing proxy when named (it must be the allocated `.mov`, else 400). Missing or wrong size: 409 listing `missing` and `size_mismatch`. A path outside the data root: 400. A clip with no segments: 409 "this clip has no description yet; post its result first". Success makes the clip visible and searchable; the item becomes `live`, or "original still owed" when the original has not arrived and the batch uploads originals (a second post finishes it).
- `release` `{state: done|failed|cancelled, summary}`: ends the batch. `done` becomes done_with_errors when anything failed or an original is still owed. `cancelled` marks unfinished items cancelled and deletes their hidden clip rows (published clips stay); a cancelled release is accepted even after the lease expired, unless another machine of the same editor now holds the batch. The summary is stored truncated to 500 characters and shown as the batch's error.
- Also provided to the dashboard's report reply: the batch ids an editor's machine should stop.

## The ingest drawer
(source: ingest.js, index.html, style.css)

- Opened by the "+" header button, or by dropping files anywhere on the page (a full-window veil "Drop clips or folders to add them to the archive" shows while dragging files). Escape closes it. Closing stops all polling. It does not close the other drawers.
- Heading "Add b-roll". Tray status line with "recheck": "checking…", "connected (v<version>, <GPU detail or N GB VRAM or no GPU>)", "the CC Sync tray can't index yet: <reasons>", "your CC Sync tray is too old for b-roll ingest: take the update it offers, then reload this page" (tray answers 404), or "not reachable: the CC Sync tray is not running, or the browser blocked local connections (self-test: open http://127.0.0.1:8899/status in a tab; if that shows ok:true it is the browser, not the tray)".
- A persistent red notice box (with "dismiss") for refusals that must stay visible.
- Adding clips:
  - Drag and drop of files or folders (all nested folders read). One dropped folder becomes the suggested shoot name and its name is removed from the sub-folder paths; several dropped folders keep their names as sub-folders.
  - "Choose files…" / "Choose a folder…" ask the tray to open the computer's own picker; those clips are "indexed in place" (not copied through the browser).
  - Only video extensions are taken (from the dashboard's site settings, falling back to .braw .mov .mp4 .mxf .avi .mts .m2ts .mkv .r3d .crm .mpg .mpeg .wmv .webm .insv .360): "N of M files were not video and were left out." Nothing usable: "Nothing there this app can index: b-roll takes video files (...)".
  - At most 2000 clips: "Only the first N clips were taken: a batch holds 2000." / "A batch holds at most 2000 clips. Run this one first."
  - The whole drop (plus clips already listed) is refused before anything is copied if it does not fit the tray's reported free staging space plus its reserved margin ("That drop is X and this computer has Y free where clips are staged... Nothing was staged...").
  - Default shoot name: the dropped folder, else "<YYYY-MM-DD> ingest". Names are sanitised as typed; once typed, a later drop does not overwrite it.
- Clip list: "<chosen> of <n> clips selected"; per-row tick; thumbnail (made in the browser at 10% in, at most 1 s, 160x90, two at a time, 8 s timeout; otherwise the tray's own thumbnail once staged; else "no preview"); name with sub-folder; size, duration, "indexed in place", "will be saved as <name>"; upload progress bar. Duplicates show "already in the archive: clip #N (<name>)" and are unticked once, the first time found. Clips the tray refused show its reason and cannot be ticked.
- Staging: 700 ms after adding, the drop is sent to the tray; files then upload to the tray two at a time with progress. A network failure retries automatically up to 3 attempts in total (waits 2 s, then 4 s; "upload interrupted, retrying (n of 3)..."); no progress for 2 minutes counts as a failure. After that: "<message> Tried N times: press retry when the connection is back." with a per-row "retry" and "retry all failed (N)". A 409 from the tray (already staged) counts as success. Leaving the page while uploads are pending triggers the browser's leave warning.
- Duplicate check and final names are asked of the server 400 ms after changes and whenever new hashes arrive; a refused shoot name shows "the shoot name will be saved as “<name>”".
- Settings form: "Shoot name"; "Model": Good ("Qwen3-VL 4B, needs about 8 GB of VRAM") and Best ("Qwen3-VL 8B, needs about 12 GB of VRAM"), a model this GPU cannot hold is disabled with the reason, a model not yet downloaded says "not downloaded yet, about <size>"; default is the site's tier unless it does not fit. "When to run": "Only when idle" (default) or "Foreground". "Keep sub-folders" (on), "Upload the originals too" (on), "Transcribe speech" (always disabled, "phase 2, not available yet").
- Summary line "<n> clips, <size> - will run now|will run when you're away"; "Run" is enabled only with clips chosen, a reachable tray, a shoot name and staging done. "clear" empties the drop.
- Run: confirms drops of 50 GB or more ("This drop is X across N clips. Staging it needs X free on this computer and it has Y. Indexing will run for about H hours. Start it?", at 1.5 minutes per clip) and a model not yet downloaded ("The <tier> model isn't on this computer yet. Running this batch downloads it first (about X). Continue?"). Then creates the batch and hands its id to the tray. A tray refusal (503) leaves a persistent notice telling the editor to change the model or take over from another computer; other failures "The CC Sync tray did not take the batch: <message>". Success toasts "Indexing started on this computer." or "Queued: it starts when you step away from this computer."
- "Running" section: "<shoot> - <state words>"; counts "<done> of <n> indexed · <live> searchable · <failed> failed · <dup> already in the archive · <owed> still to send the original"; "heartbeat <ago>"; the tray's gate in words (waiting for the indexing model, waiting until you step away from the keyboard, waiting for DaVinci Resolve to close, paused, waiting for ffmpeg to be installed, waiting: the sync drive is not connected, waiting: this computer's sync config needs fixing, this GPU cannot run the chosen model, b-roll ingest is off on this computer, nothing to do, indexing); model download progress with rate and minutes left; current stage and percent; uploads queued or paused; up to 200 item lines. Buttons: Pause or Resume (whichever applies), "Start now" (only while waiting for the editor to step away or Resolve to close), "Pause uploads"/"Resume uploads" (saved on the server first, then told to the tray), "cancel batch…" (confirm "Stop this batch? Clips already in the archive stay there; the rest are dropped and their staged files are kept for a week."). All disabled once the batch is finished; Pause/Resume/Start now disabled while the tray does not answer, with the note "the CC Sync tray isn't answering right now - the batch keeps its place on the server (...)".
- Polling while open: tray progress every 1.5 s, server batch every 5 s, batch list every 10 s.
- "Batches" list with "Mine" / "All computers" tabs (the latter only if the server allows it for this user). Each card: shoot, state words, editor (all view), machine or "no computer yet", heartbeat, tier, "foreground" or "when idle", counts, "uploads paused", stored error. Actions: "clips"/"hide clips" (up to 200 item lines), "take over on this computer" (queued batches in Mine), "try the N failed again" or "finish the N still uploading" (finished batches in Mine), "cancel" (unfinished). Reopening the page re-attaches the live view to the newest unfinished batch of this editor.

## Indexer write API
(source: routes_ingest.py, schemas.py)

- For the base-rig indexer. Header `X-Ingest-Token` must equal `BROLL_INGEST_TOKEN` (401 "missing or invalid X-Ingest-Token"); token unset: 503 "ingest is not configured on this server (BROLL_INGEST_TOKEN unset)", logged on every call.
- `POST /api/ingest/video`: create or update a clip by (share, path). Fields left out do not erase stored category, error, duplicate mark, archive/original paths, sprite geometry, frames, timecode or bitrate. Unknown fields are logged and ignored. Answers the clip id.
- `POST /api/ingest/index`: replaces a clip's segments (with server-computed searchable Chinese text), themes and quality flags, removes its old segment embeddings, marks it indexed with time and model. When share and path are given they decide the clip (a disagreeing id is logged). 404 "video not found"; 400 on invalid data (for example an unknown quality flag).
- `POST /api/ingest/moved`: changes a clip's path, marks it sorted and out of the inbox; 409 if a clip already exists at the new path.
- `POST /api/ingest/shares`: records each share's root, whether it archives originals or proxies, description and indexed flag; never deletes.

## Looks redundant or overlapping

- Four controls onto one "where am I browsing" state: folder tree (`shoot` for own footage, `category` for Downloads), the category drop-down (duplicates the Downloads half of the tree), and detail-panel path crumbs (`path`), each clearing the others.
- Two clip-detail layouts (classic "replace the grid" and terminal "beside the grid"); the terminal look is hard-coded on, so the classic branch never runs.
- Three search modes plus a fuzzy switch plus a source switch; hybrid already contains keyword, and semantic is unavailable wherever `fastembed` is not installed (it is not in the lock file).
- The "tray + shares" drawer's tray check duplicates the ingest drawer's tray status line; its shares list is descriptive only.
- Ingest retry is three paths (browser upload retry, per-row retry, server retry-failed) and cancel is three channels (heartbeat 410, report reply, browser telling the tray directly).
- Batch state words and "ago" formatting are implemented twice (server and page) on purpose.
- share.js re-implements `$`, `el`, `formatDuration`, `toast`, `fetchJson`; its `toast` is never called.
- Client-folder clip identity is tracked three ways (id, path, hash) with self-healing writes on the public read path.
- The standalone Docker deployment duplicates the dashboard mount and is unauthenticated.
- `insert_share`/`insert_rel_path` repeat fields of the `insert` object.

## Claims the code does not back

- app.js says "The page defaults to hybrid and remembers a mode in the URL". The URL hash never stores the mode (nor sources, fuzzy or hidden flags).
- The Send-to-Resolve unreachable toast ends "Downloads are in Settings."; the "tray + shares" drawer has no downloads.
- DEPLOY.md says "the three `/api/ingest/*` endpoints"; there are four (`video`, `index`, `moved`, `shares`).
- DEPLOY.md says v1 has no auth; mounted, the dashboard's login gate applies, and the fleet and ingest routes have their own tokens.
- db.py's docstring says schema.sql sets user_version 4; it sets 13. schema.sql's own header says "schema v1".
- style.css (700 px block) says cards stay 240 px so sprite offsets stay right; under the always-on terminal look, below 760 px the grid columns are fluid (`minmax(150px, 1fr)`) while the thumbnail itself stays 240 px.
- index.html and app.js comments describe a classic look that can be switched; `html.cc` is in the markup and nothing removes it.
- The ingest counts line reads "<n_done> of <n_items> indexed", but n_done also counts failed, duplicate, cancelled and skipped items.
- The search box placeholder says "search segments"; it also searches transcripts.

## Could not determine

- What the tray (127.0.0.1:8899) does with `/insert`, `/status` and the `/broll/ingest/*` routes and its exact answer shapes; only this page's handling of them is described.
- What the dashboard's login gate, identity stamps and top-bar partial do; only the headers this app reads are described.
- Whether `fastembed` and the embedding model are present in the deployed container, so whether Semantic mode and the hybrid booster ever run in production.
- The images `favicon.svg`, `favicon.png`, `brand_mark.png` were not inspected as behaviour. The `data/` folder under broll/web is a git-ignored local dev database, not code, and was not inventoried.
- Whether anything uses the `sheets/` folder (this app only creates it at startup).
