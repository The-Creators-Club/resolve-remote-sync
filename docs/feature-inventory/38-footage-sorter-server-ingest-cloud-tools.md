# Footage Sorter: the server, ingest, the NAS and cloud parts, the tools and the mover script

Terms used throughout:

- **Clip**: one recording as the sorter sees it: a master file plus its proxy, sidecar and metadata files, or (for an image sequence) a whole folder.
- **Source roots**: the folders footage arrives in (camera dumps). **Staging root**: where a card is copied when it is not sorted straight to its final place; defaults to the first source root. **Destination root** (`destRoot`): the studio's final folder tree (on this studio, the `P:` drive).
- **Manifest**: the sorter's record of intent: which clip should go to which destination folder (an **assignment**), which calendar event points at which folder (a **binding**), which folders are planned, which shoots are dismissed.
- **Catalog**: the sorter's record of fact: for each clip (keyed by a content-derived **clip key**), every place a copy of it is known to exist, and whether each copy is a staging copy, a final copy or a card.
- **Move plan**: a list of source-to-destination file moves the server writes for the PowerShell mover script to carry out.
- **Card session**: one inserted camera card (or drive) as the ingest part sees it, with its own scanned clips and state.
- **TeraCopy**: a third-party Windows copy program the ingest drives to copy and verify card contents.

## The local server: listening, access, files it owns
(source: server.js, package.json)

- Starts with `npm start` (runs `node --disable-warning=ExperimentalWarning server.js`). Other package scripts: `npm run scan` (runs the scanner standalone, see "The scanner"), `npm run roster` (rebuilds the roster, see "The roster"), `npm test` (runs the test files; not inventoried).
- The only declared dependency is the Express web framework (version 5.2 or later).
- Listens on **127.0.0.1 only**, port from settings (`port`, default **8787**), overridable by the `FS_PORT` environment variable. Prints the listening URL, the source roots, the destination root, the clip count with the last scan time ("never" if none), and the number of catalogued clips.
- If the port cannot be bound, prints `[listen] <message>` and exits with code 1.
- On SIGINT or SIGTERM: stops accepting connections and exits; forces exit after **1.5 seconds** if connections linger.
- **No authentication of any kind.** Every route below can be called by any process on the same computer. No route checks an origin, a token or a session. (Nothing in this part makes the server reachable from another machine; see "Could not determine" about how the CC Sync dashboard shows it.)
- Every response carries `Cache-Control: no-store`, except the thumbnail (one day) and the stream route (ten minutes private), which set their own.
- Request bodies are JSON, up to **8 MB**.
- `GET /` serves `public/index.html`; if that file does not exist it answers a small HTML page reading "footage-sorter" and "public/index.html not present yet. API is live at /api/state."
- Every other file under `public/` is served as a static file (no directory index).
- Any unknown path answers **404** `{error: "not found", path}`.
- Any unhandled error answers **500** with the error message; if the response was already partly sent, the connection is dropped.
- **Write safety rule (enforced in code):** the server writes files only inside its own `data/` and `cache/` folders; any attempt to write elsewhere throws "refusing to write outside data/ and cache/: <path>". The single exception: it may **create folders** (never files) under the destination root and the staging root, so TeraCopy has somewhere to copy into; any other folder creation throws "refusing to create a folder outside the ingest roots: <path>".
- Every file write is atomic (written to a temporary name beside the target, then renamed), in UTF-8 without a byte-order mark. JSON files it reads tolerate a byte-order mark.
- At boot it creates `data/`, `data/logs/`, `cache/thumbs/`, `data/cards/` and `data/ingest/lists/`.
- Files it keeps, all under `data/` unless noted:
  - `settings.json`: settings (see next group).
  - `clips.json`: the result of the last scan.
  - `manifest.json`: the manifest. Every save also writes a timestamped copy `logs/manifest-YYYYMMDD-HHMMSS.json` (with `-1`, `-2` ... suffixes for saves in the same second, up to 99), and the oldest copies beyond **200** are deleted.
  - `calendar.json`: the cached calendar events.
  - `moveplan.json`: the last exported move plan.
  - `google-oauth.json`, `google-token.json`: Google sign-in client details and token.
  - `catalog.json`: the catalog.
  - `cards/`: one file per card session.
  - `ingest/lists/`: file lists handed to TeraCopy.
  - `card-usage.json`, `cards-token.json`: the crew card tracker's cached copy and its access token.
  - `logs/ingest-journal.jsonl`: one line per ingest event.
  - `logs/move-journal.jsonl`: written by the mover script, read by the server.
  - `logs/journal-redirects.json`: folder renames the server noticed, for the mover's verify mode.
  - `whisper-names.json`: written by the audio name tool, read by the server.
  - `cache/whisper/<clipId>.json`: per-clip transcripts written by the audio tool (files starting `_` are ignored).
  - `cache/mediainfo/<clipId>.json`: cached technical metadata.
  - `cache/thumbs/`: thumbnails.
- At boot, in order: loads settings, the last scan, the manifest, tries to load the suggestion module, starts the thumbnailer (2 at a time), loads the catalog and the card tracker, builds the ingest driver, reconciles the mover's journal into the catalog (a failure is logged as "reconcile at boot failed" and boot continues), and checks TeraCopy (a missing TeraCopy is logged as "[teracopy] not available: ..." and boot continues).
- The suggestion module is optional: if it fails to load, suggestions are simply empty, and loading is retried at most once every **5 seconds**.

## Settings, environment variables and their defaults
(source: server.js)

- Settings are read from `data/settings.json`, merged one nesting level deep over the defaults (a partial file is fine). Missing or unreadable file means all defaults.
- `port`: **8787**.
- `sourceRoots`: empty list. Environment `FS_SOURCE_ROOTS` (semicolon-separated) replaces it.
- `destRoot`: empty. Environment `FS_DEST_ROOT` replaces it.
- `stagingRoot`: empty, which then means the first source root. Environment `FS_STAGING_ROOT` replaces it.
- `icsZip`: empty. A zip of calendar `.ics` exports used when Google is not connected.
- `icsCalendarPrefix`: empty (used by the suggestion module, not in this part).
- `calendarFromDate`: **2026-04-01**; events before it are not fetched.
- `googleCalendarIds`: empty list, meaning the account's primary calendar.
- `calendarRefreshMinutes`: **15**. Also sets the background calendar refresh interval (minimum **5** minutes).
- `ffmpegDir`: `C:\Users\alex\tools\ffmpeg\bin` (a hard-coded personal path as the default).
- `vaultRoot`: `X:\Vault\2026\FF5` (the interview transcript archive the audio matcher reads; hard-coded default, repeated as a second constant).
- `tzOffsetHours`: **8** (the studio's time zone, UTC+8).
- `thumbWidth`: **320** pixels.
- `timeFolders.enabled`: **false**. When on, every assigned destination gets per-day, per-camera subfolders named `<YYYY-MM-DD> <HH.mm>-<HH.mm> <CAMERA LABEL>`. `timeFolders.labels` default: Sony FX3 `A-CAM`, other Sony `B-CAM`, Blackmagic `BMCC`, drone `DRONE`, audio `AUDIO`.
- `cards.url`: the crew card tracker site (default from the card tracker, see that group). Environment `FS_CARDS_URL` replaces it (for pointing at a local test copy).
- `cards.syncMinutes`: **15**.
- `cards.serials`: map from a card's volume serial number to the label written on the card (for example `1038701C` to `SD-1`).
- `cards.capacities`: map from card label to its size in bytes, learnt when a serial is named.
- The card tracker token is not a setting: it comes from `data/cards-token.json` or the `FS_CARDS_TOKEN` environment variable.
- `ingest.teraCopyPath`: `C:\Program Files\TeraCopy\TeraCopy.exe`.
- `ingest.historyDir`: empty, meaning `%APPDATA%\TeraCopy\History`.
- `ingest.pollSeconds` **5**, `ingest.startGraceSeconds` **120**, `ingest.idleGraceSeconds` **60**, `ingest.verifyGraceSeconds` **180**, `ingest.timeoutMinutes` **0** (no timeout): TeraCopy job watching limits, see "TeraCopy driver".
- `ingest.conflictSwitch`: `/OverwriteDiffSize`. `ingest.collisionPolicy`: `Rename`.
- `ingest.allowUnverified`: **false**. Whether a copy TeraCopy did not verify may count as done.
- `ingest.copyProxies`: **true**. `ingest.proxySubfolder`: `proxy`.
- `ingest.freeSpaceMarginMB`: **256**.
- `ingest.sony.clipPath` `PRIVATE\M4ROOT\CLIP`, `ingest.sony.proxyPath` `PRIVATE\M4ROOT\SUB`, `ingest.sony.thumbPath` `PRIVATE\M4ROOT\THMBNL`, `ingest.sony.fx3ModelRegex` `FX3(?!0)` (FX3 but not FX30).
- `ingest.drone.path` `DCIM`, `ingest.drone.exts` `.mp4`, `.mov`, `ingest.drone.minValidYear` **2020**.
- `ingest.audio.patterns`: `*Wireless PRO*` and `^\d{6}_\d{3}$` (volume names treated as audio recorders). `ingest.audio.matchPaddingMinutes`: **0**.
- `ingest.audit.enabled`: **true**.
- After loading, the destination root, source roots and staging root are normalised as paths.
- The whole settings object (including every path) is returned to the page in `/api/state`.

## The state the page polls
(source: server.js)

- `GET /api/state` (anyone local): returns, in one answer: the settings; every clip (the last scan plus the clips of every live card session), each decorated with where it sits (destination, staging, card, or other) and its backup label from the catalog (and whether that backup was found through a "twin", a copy catalogued under another key); the card session summaries; the last scan time; the manifest; the calendar events; the inferred event-to-folder bindings; the suggestions; everything the audio tool heard; the per-clip audio summary; the roster (episode, Chinese name, English name only); a "miss" explanation for every event that got no folder; whether a scan is running and its count; the time folders the current assignments imply; the calendar status; the card tracker status.
- Suggestions are built from the calendar first; an audio suggestion is added only for clips the calendar said nothing about.
- Each suggestion is marked `via: binding` (an explicit event binding) or `via: inferred` (worked out from the event title; carries the reason) or `via: audio`.
- Explicit bindings always win over inferred ones.
- Event "miss" reasons are only produced when the episode configuration exists; an event that is bound or inferred gets none.

## Calendar: Google first, then the cached file, then the ICS zip
(source: server.js)

- Events come from Google Calendar when connected. The cached `calendar.json` is refetched when it is not from Google, has no fetch time, or is older than `calendarRefreshMinutes` (15), or when a refresh is forced.
- If the Google fetch fails, the error is kept for the status chip and the last cached events are used, so the app keeps working offline.
- When Google is not connected, the cached file is used; if there is none (or a refresh is forced), the optional suggestion module parses the `icsZip` file.
- The events are re-read whenever `calendar.json` changes on disk (another program may rewrite it).
- Calendar status reports source `google`, `ics` (an ICS zip is set) or `none`, plus the Google status, last error, calendar ids, refresh minutes and from-date.
- Background task: every `calendarRefreshMinutes` (minimum 5) the server refetches from Google, only while connected.
- `GET /api/events` returns the events; `?refresh=1` forces a refetch.

## Inferring which folder an event belongs to (server side)
(source: server.js; the rules themselves are in lib/infer.js, see that group)

- Event titles are matched against the episode configuration and the roster to produce a destination folder per event, reusing folders that already exist on the destination root (read down to **6** levels, cached **30 seconds**).
- The episode configuration and the roster are re-read whenever either file changes. On load it logs "[infer] N episodes, M people in the roster".
- If no episode configuration exists, nothing is inferred. If inference fails, it logs and returns nothing.

## Audio: who is on a recording (server side)
(source: server.js; scoring in lib/audio-match.js)

- A clip counts as audio if its kind is audio or any file ends in `.wav`, `.mp3`, `.m4a`, `.aac`, `.flac` or `.ogg`.
- Reads `data/whisper-names.json` (names heard per clip) whenever it changes; logs "[audio] N clips with something heard on them" when the count changes.
- Reads per-clip transcripts from `cache/whisper/`; the list of transcribed clips is re-read at most every **10 seconds**; each transcript is re-read only when its file changes.
- Reads the interview transcripts in the Vault: every `<vaultRoot>/<episode>/Interviewees/<person>/*_Transcript.md`. Checked for changes at most once a **minute** (it is a network share); re-indexed only when a transcript appears, disappears or changes. Logs "[audio] vault: N interview transcripts under <root>".
- "Copies" of an audio clip: other audio clips with the same file-name stem and the same byte count, and (when both are known) durations within **2 seconds**. Each copy reports its path, its destination and whether it is assigned.
- Each audio clip is scored from its transcript, the names heard, the Vault index, existing destination folders, its copies, and the calendar's suggestion; the result lists ranked candidate folders with evidence, the main language of the transcript, how much was scanned, the model used, where the clip is already filed (if it sits under the destination root), its assignment, and a "disagree" flag when the audio points somewhere other than where it is filed. Results are cached until any input changes.
- Only audio clips that have a transcript or a "heard" finding are scored.
- Audio suggestions (shown as the "♪" badge): the top candidate with a folder, for a clip that is not assigned, not covered by a calendar suggestion, whose confidence is not "low", and that is either not filed anywhere or filed in a folder the audio confidently contradicts. Confidence shown is "high" or "low". The suggestion carries a summary, the moment something was heard and its text, and a reason built from the evidence (cut to 300 characters).
- `GET /api/audio`: the Vault root and transcript count, the last audio run (time, model), how many audio clips the scan holds, and the per-clip summary (top candidate with score rounded to two decimals, disagreement, whether any name or self-introduction was heard).
- `GET /api/audio/:clipId`: the full score of one clip plus its transcript (model, seconds scanned, duration, where it was adopted from, and each window's start, length, language and segments with times to a tenth of a second). Refusals: **404** "unknown clip"; **400** "not an audio clip".

## Scanning the footage (server side)
(source: server.js; the walk itself in lib/scan.js)

- A scan walks every source root **plus the destination root** (added even though it is not a source root, so footage already sorted stays browsable and movable).
- `POST /api/scan`: starts a scan. If one is running, answers `{started: false, running: true}` with the previous clip count and bytes. With `?wait=1` or body `{wait: true}` it waits and returns the new count, bytes, scan time and error. Without it, it answers at once with the previous numbers marked as previous.
- `GET /api/scan/status`: running or not, live count while running, bytes, scan/start/finish times, the error, up to **50** warnings, and what the out-of-band move check found.
- After every scan, in order: the mover's journal is reconciled into the catalog; clips under the scanned roots refresh their presence in the catalog, and catalogued copies under a scanned root that the scan no longer saw are marked absent; then "out-of-band moves" are adopted (see "Footage moved by hand"). Failures in these steps are logged and do not fail the scan.

## Footage moved by hand in Explorer (server side)
(source: server.js; detection in lib/relocate.js)

- After a scan, the server notices clips that were moved outside the app: re-keys their assignments, marks assignments fulfilled when the clip is already where it was meant to go, adopts the folder a clip now sits in, and records folders that were moved whole.
- The result (counts re-keyed, fulfilled, adopted, folder moves, gone, ambiguous, and a one-line description) is shown in the scan status.
- When anything changed, the manifest is saved; for every whole-folder move, the old and new absolute paths are written to `data/logs/journal-redirects.json` so the mover's verify mode can follow them.

## Editing the manifest: assignments, folders, bindings, dismissed shoots
(source: server.js)

- Folder names (destinations) are cleaned the same way everywhere: backslashes become slashes, empty segments are dropped, trailing dots and spaces are trimmed from each segment (Windows would drop them silently). Refused (treated as invalid): anything empty, a drive-letter or `//` path, any segment made only of dots (rejected before trimming), any segment containing `< > : " | ? *` or a control character, and any segment whose name before the first dot is `CON`, `PRN`, `AUX`, `NUL`, `COM1`-`COM9` or `LPT1`-`LPT9`.
- `POST /api/assign` `{clipIds, dest, structure}`: assigns clips to a folder. `structure` is `preserve` (keep the card's sub-paths) or anything else meaning `convention`. Refusals: **400** "clipIds required"; **400** "invalid dest". Non-string ids are skipped. Returns the count, the manifest and the implied time folders.
- `POST /api/unassign` `{clipIds}`: removes assignments. **400** "clipIds required".
- `POST /api/folders` `{dest}`: adds a planned folder (kept sorted, no duplicates). **400** "invalid dest".
- `POST /api/folders/bulk` `{dests, placeholder}`: adds many planned folders in one save (used for an episode skeleton). Duplicates are matched ignoring case. Invalid names come back in `rejected`. With `placeholder: true` each folder is also a **placeholder**: shown in the tree but not created on disk until a clip is assigned into it. **400** "dests[] required".
- `POST /api/folders/remove` `{dest, preview}`: takes a folder and everything beneath it out of the plan: planned folders, placeholders, assignments into it (clips go back to unsorted; no file is touched) and event bindings to it. With `preview: true` it only reports the counts (planned folders, clips, bindings, whether it exists on disk and how many files, counting up to **2000**). Refusals: **400** "invalid dest"; when nothing in the plan refers to it, **409** `"<dest>" only exists on disk. This app never deletes inside <destRoot> - remove it in Explorer, then reload.` (the real text uses an em dash) if it is on disk, otherwise **404** "nothing here to remove". A folder on disk is never deleted.
- `POST /api/folders/move` `{from, toParent, name}`: moves or renames a folder in the plan, carrying its subtree's planned folders, placeholders, assignments and bindings. `toParent` omitted keeps the parent (a rename); `""` or null means the destination root. Refusals, in order: **400** "invalid source folder"; **400** "invalid target folder"; **400** "that is not a usable folder name" (a name with a slash or invalid); **400** "a folder cannot be moved inside itself"; **409** `"<from>" holds N file(s) on disk. This app never moves anything inside <destRoot> - move it in Explorer, then reload.` (counted up to 2000; em dash in the real text); **409** `"<from>" is not a folder this app can move.` (nothing refers to it and it is not on disk); **409** `"<to>" already exists` (a planned folder has that name); **409** `"<to>" already exists on disk and is not empty`. An empty folder on disk may be moved in the plan; the empty original is reported back as `leftOnDisk` and not deleted. Moving onto itself answers OK with `unchanged`. The tree used for these checks is read **8** levels deep.
- `POST /api/source-roots` `{path, remove}`: adds or removes a source root and saves settings. Surrounding quotes are stripped. Refusals: **400** "no folder given"; **400** "give the full path, starting at the drive"; on remove, **404** "not a source root" and **400** "that is the only source root"; on add, **404** "no such folder: <path>", **400** "that is a file, not a folder", **400** "that sits inside the destination <destRoot>", **409** "already a source root", **400** "already covered by <root>", **400** "that contains the existing root <root>". Comparisons ignore case. Note: this writes the whole in-memory settings object to disk, so environment-variable overrides in force at the time are saved into `settings.json`.
- `POST /api/dismiss-event` `{eventUid, dismissed}`: marks a shoot as needing no footage (or, with `dismissed: false`, restores it). Kept in the manifest so it holds across machines. **400** "eventUid required".
- `POST /api/bindings` `{eventUid, dest}`: binds an event to a folder; an empty, null or missing dest removes the binding. **400** "eventUid required"; **400** "invalid dest".
- Every edit saves the manifest (with its timestamped copy).

## The destination tree
(source: server.js)

- `GET /api/desttree`: the folders on the destination root, read **8** levels deep, sorted by name, skipping folders starting with `.` or `$` and folders named `proxy`, `render in place` or `renders in place` (any case). Planned folders that do not exist yet are merged in and marked planned. With no destination root set, an empty root node.

## Time folders (per-day, per-camera subfolders), server side
(source: server.js; naming rules in lib/timefolder.js)

- Only when `timeFolders.enabled` is on (off by default). Every answer that changes assignments returns the implied time folders per destination (name, camera, day, clip ids, bytes, whether a folder of that name already exists on disk and which existing folder it merges into), covering both scanned clips and card clips.
- The existing time folders under every assigned destination are read from disk and cached; a cache older than **30 seconds** is refreshed in the background while the old answer is served; a move-plan export, an ingest job finishing, a scan or an audit forces a fresh read.

## Exporting the move plan
(source: server.js)

- `POST /api/export-moveplan`: builds the move plan from every assignment that is not yet fulfilled and whose clip is in the last scan, and writes `data/moveplan.json` (generation time, destination root, the folders to create, and the file entries). **400** "destRoot not configured".
- Clips held only by a card session are left to the ingest, neither moved nor reported missing. Assigned clips that are neither scanned nor on a card are reported as `missingClips`.
- Where each file goes:
  - An image-sequence clip moves as one whole folder into the destination.
  - `preserve`: each file keeps its path relative to the source root (or just its name if outside it).
  - `convention`: masters go straight into the destination; proxy and sidecar files that sit in a proxy folder (a folder named `proxy` or `proxies`, or a Sony card's `M4ROOT\SUB`) go into a `Proxy` subfolder, keeping any nested path below that proxy folder; a sidecar beside its master (a Blackmagic RAW `.sidecar`) stays beside it.
  - With time folders on, the destination is the time folder under the assigned folder.
- Planned folders are included even with nothing assigned (the episode skeleton is created empty), except placeholders, which are created only once a clip is assigned into them. Every parent folder down from the destination root is listed too.
- Before writing, it removes from the plan:
  - Entries whose destination already holds an identical file ("already there"): same size, and for files of **64 MB** or less the same SHA-256 hash; above 64 MB the size match alone counts. Checked **32** at a time.
  - Duplicate entries that target the same destination with identical content (the same card staged twice): one is kept, the other reported.
  - Anything not identical (a different file at the destination, or two different files for one name) stays a **collision** and is reported; the plan is still written with the colliding entry in it (the mover then refuses it).
- After writing, the clips in the plan are recorded in the catalog under their current root, so the mover's journal can be matched back afterwards.
- Answer: entry and folder counts, total bytes, collisions, already-there list, duplicates, missing clips, the time-folder groups and warnings, and the plan's path.
- This server never moves a file itself; the mover script does.

## Mover journal reconciliation
(source: server.js; matching in lib/catalog.js)

- At boot, after every scan, and on request, the mover's `move-journal.jsonl` is read against the last `moveplan.json`; every move found is applied to the catalog (a staging copy becomes a final copy), and the matching assignment is marked fulfilled with the clip key. Logs "[catalog] N move(s) reconciled from the mover journal".

## Auditing the destination root
(source: server.js)

- A background audit scans the whole destination root and records every clip found there in the catalog as a final copy. Only one runs at a time; starting one while running reports the running state. Refused with **400** "destRoot not configured". Status reports running, start/finish times, count so far, clips linked, error. Logs "[catalog] audit of <root>: N clips linked, M new, K gone". (Route: see "Catalog routes".)

## Thumbnails, stream, technical metadata, reveal in Explorer
(source: server.js)

- `GET /api/thumb/:clipId`: the clip's thumbnail (scan clips and card clips alike). Ready: the JPEG with a **one day** cache. Still being made: **202** `{status: "pending"}` (the page retries). Otherwise **404** "no thumbnail available" with the status. Unknown clip: **404** "unknown clip".
- `GET /api/proxy/:clipId` (also answers HEAD): streams a playable file of the clip, preferring a proxy, then the master, then any playable file. Playable types: `.mp4`, `.m4v`, `.mov`, `.mkv`, `.webm`, `.wav`, `.mp3`, `.m4a`, `.aac`, `.flac`, `.ogg`. Supports byte ranges (206), including suffix ranges; a malformed or out-of-range request gets **416**. Refusals: **404** "unknown clip"; **503** "card is being copied" (TeraCopy is reading that card); **404** "no playable file for this clip"; **404** "file unavailable".
- `GET /api/mediainfo/:clipId`: technical metadata of the master file through `ffprobe` (found on the system PATH, not in `ffmpegDir`): container, duration, bit rate, stream count; video codec, profile, size, frame rates, pixel format, bit depth, colour space, transfer and primaries, sample aspect ratio, frame count; audio codec, channels, layout, sample rate, bit depth. Cached in `cache/mediainfo/` and reused while the path and size are unchanged; a failed probe is not cached. Concurrent requests for one clip share one probe. Errors returned in the body: "ffprobe not found on PATH", the first line of ffprobe's error, or "unreadable ffprobe output". Refusals: **404** "unknown clip", **404** "clip has no files".
- `POST /api/reveal` `{clipId, role}`: opens Windows Explorer with the clip's folder (for a sequence) or file selected; `role` may name a specific file path of the clip, otherwise the master. The path comes from the scan, never from the request. Refusals: **404** "unknown clip"; **404** "nothing to show"; **404** "not on disk any more - rescan?" (em dash in the real text); **501** "Windows only" on any other operating system; **400** "unusable path" (a path containing a quote).

## Card sessions and the manifest (server side)
(source: server.js)

- When a card copy finishes a clip in **final** mode, its assignment is marked fulfilled (time, the ingest job id unless the clip was skipped, the clip key). In **stage** mode, the assignment (if any) is carried to the staged copy's id, so the next staging scan shows it assigned and the mover picks it up.
- When an ingest job ends, a changed manifest is saved and the time-folder and destination caches are cleared.
- When a card session is **dismissed**, every assignment of its clips is deleted (an **ejected** card keeps them, since it may come back).
- When a card that was seen before comes back and is scanned again (the new session supersedes old ones), assignments are carried to the new clip ids by clip key, and the old ids dropped.
- When a card session reaches **done** and the card tracker is configured: if the card's serial is mapped to a card label and every clip on it has a known copy in the catalog, the tracker is told the card is backed up (tagged `sorter:<sessionId>`). Otherwise it logs either "serial X (camera) is not mapped to a card label - map it in the Cards tab and it flips by itself next time" or "<card> (<serial>) stays marked used: N of M clips have no copy yet".
- For each card session the server works out which fleet card it is (by serial) and, for a serial nobody has named, a ranked guess of which cards it could be (using the card kind, capacity, the recording days, usage history, learnt capacities, and excluding cards that are in a reader right now: sessions in state scanning, ready, planned, copying or done).
- The copy plan for a card: **final** mode copies only assigned clips (to their destinations); **stage** mode copies everything to the staging root. It takes a fresh look at existing time folders (unless asked for a "quick" plan, which uses the cache and skips the free-space check).
- Card detail for the page: the session with decorated clips, suggestions for its clips, and the runner's status.

## Catalog routes
(source: lib/routes/catalog.js, server.js)

- `GET /api/catalog/summary`: counts of catalogued clips, known locations, locations per root, and clips with a verified final copy. With no catalog, zeros.
- `POST /api/catalog/reconcile`: reads the mover journal into the catalog now (see "Mover journal reconciliation"); returns what was applied and skipped.
- `POST /api/catalog/audit`: starts the background audit of the destination root. Refused when no destination root is set: the error is marked 400 internally, but the generic error handler answers every thrown error as **500**, so the caller gets **500** "destRoot not configured".
- `GET /api/catalog/audit/status`: the audit's progress.
- `GET /api/catalog?clipId=` / `?path=` / `?stem=`: look a clip up in the catalog by scan id, by any file path it is known at, or by file-name stem (case-insensitive, at most **50** results). None of the three: **400** "give ?stem=, ?path= or ?clipId=". No catalog: empty list.
- `GET /api/catalog/:key`: one catalog entry and its backup state. **404** "not in the catalog".

## Google Calendar connection
(source: lib/routes/google.js, lib/google.js)

- The connection is Google's OAuth sign-in for a desktop app, read-only calendar access (`calendar.readonly`), with offline access and the consent screen forced every time.
- The client details are read from `data/google-oauth.json`; the file as Google Cloud downloads it (`installed` or `web` wrapper) is accepted as-is. "Configured" means it holds a client id and secret.
- "Connected" means `data/google-token.json` holds a refresh token and is not marked revoked.
- `GET /api/google/status`: the calendar status (source, configured, connected, revoked, account, last sync time, last error, event count, calendar ids, refresh minutes, from-date).
- `GET /api/google/auth`: redirects (302) the browser to Google's consent page with a one-time random state that expires after **10 minutes**; the return address is always `http://127.0.0.1:<port>/api/google/callback`. Refused with **400** `data/google-oauth.json missing or incomplete` plus help text telling the operator to create a "Desktop app" OAuth client in the Google Cloud Console, save its JSON as `data/google-oauth.json`, and enable the Google Calendar API.
- `GET /api/google/callback`: Google's return. Answers a small dark HTML page:
  - "Not connected" with "Google said: <error>. You can close this tab." if Google returned an error (the error text is inserted into the page as received).
  - "Not connected" with "The sign-in link had expired or was not started from this app. Try again from the sorter." if the state is unknown or expired (each state works once).
  - On success, exchanges the code for tokens, saves them, tries to read the account's primary calendar id as the account name (never fatal), starts a calendar fetch, and shows "Connected to Google Calendar", "Signed in as <account>." (or "Signed in."), "You can close this tab. The sorter is already syncing."
  - If the exchange fails, **500** "Not connected" with the message ("token exchange failed (HTTP n): <first 300 characters of Google's answer>").
- `POST /api/google/disconnect`: deletes the token file, clears the cached events and error, returns the status. Nothing on Google's side is revoked.
- `GET /api/google/calendars`: the account's calendars (id, name, primary flag, access role, colour) and which are selected. **401** when not connected or access was revoked (body carries `revoked`), **502** for any other Google failure.
- `POST /api/google/sync`: refetches events now; returns the count and status.
- `POST /api/settings`: the only general settings edit from the page, limited to three keys: `googleCalendarIds` (list of strings each under 300 characters), `calendarRefreshMinutes` (a number from **5** to **1440**), `calendarFromDate` (`YYYY-MM-DD`). Any other key or invalid value is listed in `rejected`. If nothing valid remains: **400** "nothing to change". Valid keys are written into `settings.json` on disk (not the in-memory copy, so environment overrides are not saved) and settings are reloaded.
- Access tokens are refreshed **one minute** before they expire; concurrent requests share one refresh. A refresh that Google answers with 401, or 400 with `invalid_grant`, marks the token revoked (the access token is dropped and the reason stored), after which every call fails with "Google access was revoked or expired: <reason>" until the operator connects again. Any calendar API 401 also marks it revoked.
- Fetching events: for each selected calendar (default `primary`), every event from local midnight of `calendarFromDate` to one year later (or to `calendarToDate`, a setting read here that has no default and is not listed in the defaults), recurring events expanded into single occurrences, up to **2500** per page and **50** pages per calendar. Cancelled events and events with no date are dropped. All-day events run from local midnight of the first day to local midnight of the day after the last. A recurring occurrence's id gets `#YYYYMMDD` appended. All times are written at the fixed `tzOffsetHours` offset (no daylight saving).
- Each successful fetch writes `data/calendar.json` (fetch time, source `google`, calendar ids, events) and logs "google: synced N events from M calendar(s) since <date>". A sign-in logs "google: connected as <account>". Tokens are never logged.

## The crew card tracker (which physical camera card is which, and is it backed up)
(source: lib/cards.js, lib/routes/cards.js, server.js)

- The crew records on their phones which camera cards they used on which day; that record lives on the studio's public web site (default `https://thecreatorsclub.co/cards`, setting `cards.url`, environment `FS_CARDS_URL`). The sorter keeps a copy in `data/card-usage.json` so the Cards tab works offline, and pushes back one fact: "this card is backed up now" (or "used").
- Token: `FS_CARDS_TOKEN` environment variable, else `token` in `data/cards-token.json`. Never logged. "Configured" means a URL and a token.
- Without a token, the card list itself is still fetched (the site's state call needs no token), but usage days are not, and the status carries "no card-tracker token (data/cards-token.json or FS_CARDS_TOKEN)".
- Sync: fetches `<url>/api/state` (cards) and, with the token, `<url>/api/usage?since=<calendarFromDate>&limit=5000` (usage rows and backup history). Each call times out after **20 seconds**. Skipped when the last sync is younger than `cards.syncMinutes` (**15**, minimum 1) unless forced. Concurrent syncs share one call. On success, saves the copy and logs "cards: synced N cards, M usage rows"; on failure, the last copy stands, the error is kept for the status, and it logs "cards: sync failed: <error>".
- Background task: only if configured at boot, one sync at boot and then every `cards.syncMinutes` minutes.
- Errors from the site: "card tracker: <site's err text or HTTP n>"; 401 is classed `unauthorised`, 503 `not-configured`, others `http`.
- Mark backed up / used: `POST <url>/api/backup` with the card ids, the flag and who did it (`sorter:<sessionId>` automatically, `sorter:manual` from the tab); the local copy takes the site's answer. Logs "cards: <ids> marked backed up|used (<by>)".
- Card status (in `/api/state` and every cards answer): URL, configured, has token, last sync time, last error, card count, usage row count, sync minutes, the serial map.
- `GET /api/cards` (`?refresh=1` forces a sync): syncs if stale (a failed sync is reported as `syncError` and the last copy still answers), then returns the status and the report.
- `POST /api/cards/sync`: forced sync, then the same answer.
- `POST /api/cards/backup` `{cards: [ids]` or `card, backedUp}`: flips cards on the public site. Card ids are trimmed and upper-cased. Refusals: **400** "cards required"; **400** "backedUp must be true or false"; tracker failures answer **503** (not configured), **401** (unauthorised) or **502** (anything else) with the message and code.
- `POST /api/cards/serial` `{serial, card}`: names a card. The serial is trimmed and upper-cased and must be 2 to 40 letters, digits, `_` or `-` (**400** "serial required"). The card must look like 1 to 4 letters, a hyphen and 1 to 3 digits, for example `SD-1` (**400** `card must look like "SD-1"`). An empty or null card removes the mapping. Any existing mapping of the same serial (any case) is replaced. If a live card session has that serial and a known capacity, the card's capacity is learnt (`cards.capacities`). Written into `settings.json` on disk (not the in-memory settings, so environment overrides are not saved) and settings reloaded. Then every session with that serial is re-checked, so a card named after its copy finished is flipped to backed up right away.
- Guessing which card a freshly formatted card is (cameras give a card a new random serial at every format, and the USB readers here report their own serial):
  - Family: a Blackmagic RAW session can only be a `CF` card, a Sony session only an `SD` card; drone and audio can be either.
  - Inactive cards, and cards already named for another card currently in a reader, are excluded.
  - A card whose learnt capacity differs from this volume's by more than **2%** is excluded.
  - Score: +2 if the crew recorded that card used on a day this footage was shot ("used <days>"); +1 if the card is marked used rather than backed up ("marked used"); "same size" noted when capacities match.
  - A single card is suggested only when the top score is at least 2 and nothing ties with it. The full fleet list is returned too.
- The Cards report:
  - Cards in fleet order (by family, then number): id, family, number, backed up, active, last update time and who, last used, and the serials mapped to it.
  - Usage days, newest first: each card used that day with who recorded it, its backed-up state, and the footage the catalog knows came off that card that day (clip count, folders it landed in under the destination root with time-folder leaves and `Proxy` folded into their parent, staged and final copy counts). Footage before `calendarFromDate` is not compared.
  - Each day's calendar events (dismissed shoots excluded), each with its folder from a binding or inference, ranked: events with a folder first, then timed events, then all-day, then recurring all-day. A day's "likely" event: the only event with a folder ("strong"), or failing that the only timed event ("weak"). Events spanning days appear on each day (at most **60** days per event).
  - "Unrecorded": footage that came off a named card on a day the crew did not record that card.
  - "Unmapped serials": serials seen on ingested clips that are not named yet, with volume label, kind, clip count, last seen, the last **4** days, and a hint (`CF` for Blackmagic RAW, `SD` for Sony), most recently seen first.

## Card ingest: recognising a card
(source: lib/ingest/detect.js, lib/ingest/session.js)

- A card is reported by drive letter (for example `K:`), or by an absolute folder (a card image mounted elsewhere). Anything else is refused: "drive must look like "K:"" (**400**).
- What kind of card it is is decided by its **content**, never by the drive letter, in this order (first match wins):
  1. **Sony**: the folder `PRIVATE\M4ROOT\CLIP` exists (even empty). Scanned: that folder, plus `DCIM` if present (stills on the same card).
  2. **Drone**: `DCIM` holds at least one subfolder named three digits plus `MEDIA` (for example `100MEDIA`) containing `.mp4` or `.mov` files. Scanned: `DCIM`.
  3. **Blackmagic RAW** (`braw`): a `.braw` file in the card's root folder, ignoring macOS `._` files. Scanned: the whole card.
  4. **Audio**: `.wav` files in the root whose name (without extension) matches an audio pattern (`*Wireless PRO*` as a wildcard, or `^\d{6}_\d{3}$` as a regular expression; both case-insensitive). Scanned: the root.
  - On a Sony or drone card, matching audio files in the root are also included (root files only, not its subfolders).
  - Nothing recognisable: **422** "nothing recognisable on <drive> (no Sony/BRAW/DJI/audio structure)".
- Volume serial and label: taken from the reporter; if missing, read with Windows `vol` (5 second timeout; the serial loses its dash). On any other operating system, or for a folder path, they stay empty.
- Card capacity is read from the volume (total size).

## Card ingest: card sessions and their states
(source: lib/ingest/session.js, lib/routes/ingest.js)

- States: **scanning**, **ready**, **planned**, **copying**, **done**, **error**, **ejected** (the drive went away), **dismissed** (closed by the user), **superseded** (the same card came back and got a new session).
- One live session per card: a report for a card whose serial or drive letter already has a session in scanning, ready, planned or copying returns that session (`existing: true`) instead of a new one.
- When the same card comes back (same serial, or same drive letter if it has no serial) while an old session is ejected, done or error, the old session becomes superseded (hidden from every list, so its clips are not in the grid twice), and the new session inherits its assignments (see "Card sessions and the manifest").
- Session id: the serial (or drive) cleaned to letters, digits, `_` and `-` (at most 40 characters), plus a timestamp; `-2`, `-3` ... if it collides.
- Scanning happens in the background; the reporter gets the id at once. After the scan: logs "session <id>: <kind> on <drive>, N clips, X GB"; on failure the session goes to **error** with the message and logs "scan failed".
- What the scan does on a card:
  - Sony housekeeping files (clips made only of `.bim`, `.bin`, `.smi`, `.ppn`, `.txt`, `.dat`, `.ind` or `.xml` files) are dropped.
  - Each clip is marked as on the card, tied to the session, and given a clip key.
  - A drone clip dated before `ingest.drone.minValidYear` (**2020**) is flagged as having a bad timestamp.
  - Sony: proxy files in `PRIVATE\M4ROOT\SUB` named `<clip>S<nn>.<ext>` are attached to their clip as proxies; the camera's own thumbnails in `PRIVATE\M4ROOT\THMBNL` named `<clip>T<nn>.jpg` are copied into the thumbnail cache (unless a thumbnail already exists). Logs "paired N proxies, borrowed M thumbnails".
  - A health check of every clip (see next group) runs **before** the session becomes ready, so a damaged clip is on screen while the card is still unformatted.
  - The camera label: up to two distinct camera models seen on the card, joined with `/`, else the card kind.
  - Clips the catalog already knows a backup of are marked with that backup label (and whether it was found by key or by a twin).
- Every state change is saved to `data/cards/<id>.json` (the session minus its in-memory run handle). Sessions are kept in memory only: they are **not** reloaded from those files at start, so a server restart forgets every card (the tray notices the restart and re-reports its cards; see the tray group).
- Ejection: a report with `removed: true` turns every live or done session on that drive into **ejected**.
- Dismiss: refused while copying ("a copy is running for this card", **409**).
- Rescan: refused while a copy is running (**409** "a copy is running for this card"); refused when the drive no longer holds a recognisable card (**410** "<drive> no longer holds a recognisable card"); otherwise the session goes back to scanning, its plan is cleared, and it is scanned again.
- A clip on a card that is being copied cannot be streamed (see the stream route), and while any copy runs the thumbnailer is told not to read from cards being copied.

## Card ingest: health check of footage on the card (and of the copies)
(source: lib/ingest/health.js)

- Checked per clip master whose file type is `.mp4`, `.mov`, `.m4v`, `.mxf`, `.braw`, `.r3d`, `.crm`, `.wav`, `.bwf` or `.rsv`; stills and image sequences are not checked. Reads are a few small reads per file, one file at a time.
- Problems and their level (a clip with any "damaged" problem is **damaged**, with only "suspect" ones **suspect**, else fine). Shown texts, quoted:
  - `empty` (damaged): "The file is 0 bytes."
  - `zeros` (damaged), first 1 MiB all zero: "Reads as nothing but zeros (<size>). The camera never committed this clip; the footage may still be on the card, but only a raw image of the whole card can get it back. Don't format the card." or, if data exists later: "The first MiB is zeros (the header is gone). Data from about <size> before the end. Image the card before formatting it."
  - `rsv` (damaged), a Sony `.RSV` unfinished recording: "An unfinished Sony recording (.RSV, <size>): the camera never turned it into an MP4. Put the card back in the same camera and let it recover the clip; failing that, untrunc can rebuild it using a healthy clip from the same camera and settings. Keep the .RSV either way."
  - `truncated` (damaged), for `.mp4`, `.mov`, `.m4v`, `.braw`: a container box claims to run past the end of the file: "Cut short: the '<box>' box claims <size> but the file ends <size> before that (<size> on disk)." plus, if there is also no index, " No index (moov) either, so it will not open; " and the rebuild advice.
  - `no-moov` (damaged), same file types: "No index (moov box): it won't open. " plus the rebuild advice, plus (when the tail is zeros) " The last <size> (<n>%) are zeros: the recording was cut off, and that part exists only on the card."
  - Rebuild advice: for `.braw` "untrunc does not handle BRAW: a BRAW recovery tool or service rebuilds the index from the frames, using a healthy clip from the same camera and settings. Keep this file exactly as it is."; otherwise "untrunc can rebuild it using a healthy clip from the same camera and settings."
  - `zero-tail` (suspect), other video types over 2 MiB whose last 1 MiB is zero: "The last <size> are zeros: the recording may have been cut off."
  - `unreadable` (damaged): "Could not read the file: <error>".
  - Sony cards only: `no-xml` (suspect): "No M01.XML: the camera never closed this clip normally." or "The M01.XML is 0 bytes: the camera never closed this clip normally (it was likely rebuilt by the camera's recover function)."; `no-proxy` (suspect), only when other clips on the card have proxies: "No proxy, although the other clips on this card have one."
  - Proxies get the same media checks, always demoted to suspect, code prefixed `proxy-`, text prefixed "Proxy: ".
  - Box walking reads at most **256** top-level boxes. Sizes are shown as GB with one decimal from 1 GB, otherwise whole MB (minimum 1).
- Each problem clip is logged: "health: <stem> <status>: <codes>".
- After a copy, the same checks run on what landed, plus: `<role>-missing` ("The copied <role> is not there: <path>") and `<role>-size` ("The copied <role> is N bytes; the card's is M."), damaged for a master and suspect otherwise, and a copied `M01.XML` that is 0 bytes while the card's is not ("The copied M01.XML is 0 bytes although the card's is not."). A problem counts as **introduced by the copy** when the source does not have it (the source is re-read only when the copy shows a problem; if the card is gone, the card's recorded verdict stands in).

## Card ingest: the copy plan
(source: lib/ingest/plan.js, server.js)

- Two modes. **final**: only clips assigned to a folder, copied to their destination under the destination root. **stage**: every clip (or the chosen ones) copied to the staging root, always into time folders (time folders forced on); clips that get no time folder (stills, no time, unknown camera) go into a folder named `<detection day> <volume label or serial or drive> loose`.
- Refused when the target root is not set: "stagingRoot not configured" / "destRoot not configured" (**400**).
- In final mode, unassigned clips are split into: clips the catalog already holds at a present final path of the right size ("unassigned but backed up", no warning), and clips a wipe would lose ("unassigned").
- Per clip, judged from its master at the planned destination:
  - Nothing there: **copy** (state `absent`).
  - Same clip there (identified through the catalog by path, or for Sony through the `M01.XML` sidecar's recording id) and the source is larger: **copy** to resume a partial (state `partial`, only the difference counts toward space).
  - Same clip there, source not larger: **skip** (`present`).
  - Different or unknown clip of the same size: **skip** (`present`).
  - A folder of the same name for an image sequence: **collision** (`differs`), never merged blind.
  - Different size: **collision** (`differs`); TeraCopy then renames the incoming file (or skips it, see collision policy).
  - Nothing at the destination but the same clip (by key) is already present at another final path with the same size: state `elsewhere`, mode still copy, but **not selected by default** and not counted toward free space. If that existing copy sits inside a different CC Sync project from the planned destination, the plan offers a "link folder" action (see "Linking a folder into a CC Sync project").
- Proxies are left out when `copyProxies` is off (per request, else `ingest.copyProxies`, default on).
- A destination path longer than **240** characters adds a warning "long path (<n>): <path>".
- Free space: the volume of the target root must hold the bytes to copy plus `freeSpaceMarginMB` (**256 MB**); otherwise the plan is marked not OK with the warning "not enough free space on <root>: need N + M margin, have F". Unknown free space counts as OK.
- Each plan carries: an id, mode, target root, conflict switch (`ingest.conflictSwitch`, default `/OverwriteDiffSize`), collision switch (`/SkipAll` when `ingest.collisionPolicy` is `Skip`, else `/RenameCopied`), groups (one per destination or time folder, with per-state counts, bytes and clips sorted copy, collision, skip), unassigned lists, skipped clips, collisions, warnings, needed and free bytes, margin, and an **assignments stamp** (a fingerprint of the assignments of the clips in the plan) that makes the plan stale when assignments change.
- A placeholder for "two cameras rolling on the same take" warnings exists but always returns nothing (DORMANT).

## Card ingest: running the copy
(source: lib/ingest/run.js, lib/routes/ingest.js)

- A copy is a series of TeraCopy **jobs**, one per destination folder and conflict switch (masters and proxies go to different folders, so they are different jobs; collisions are separate jobs with the collision switch). Jobs are ordered so a folder's masters go before its `Proxy` folder.
- A file whose planned destination name differs from its source name is skipped with a log line "cannot rename via TeraCopy" (TeraCopy keeps the source name).
- Jobs for one card run one after another. Different cards (different drives) run side by side, each in its own lane keyed by drive letter, so a card pulled and re-inserted waits for its earlier run.
- Starting: the session goes to **copying**. Clips the plan skips (already present) are recorded in the catalog straight away as copies at the destination (unverified if the catalog did not know that file) and on the card, and reported to the manifest as copied.
- Before copying, each skipped clip's existing destination file is health-checked, because "present" was only a name-and-size match.
- For each job: the destination folder is created (inside the ingest roots only), TeraCopy is run and watched (see "TeraCopy driver"), and per file the receipt says verified, landed unverified, or failed. Progress per group (files done, verified, failed, bytes) is updated as TeraCopy reports; the run state shows **verifying** once TeraCopy reports the copy phase finished.
- A master that landed (verified or not) is recorded in the catalog as a copy from the card into staging or final (at its real name, if TeraCopy renamed it), with the job id and the card's serial, label and kind as origin. A master that did not land adds an error "not copied (TeraCopy code N)" (or TeraCopy's error).
- After each job, landed files are health-checked. A copy found damaged is recorded in the catalog as damaged and not verified (it is never a backup). Damage the card did not have adds the error "the copy of <stem> is damaged but the card's is not (<codes>): delete <path> and copy it again" and fails the run. Logs "post-copy check <stem>: <status> (<codes>) - introduced by the copy: <codes>".
- After each job: the catalog is saved and one line is appended to `data/logs/ingest-journal.jsonl` (time, run, session, plan, mode, destination folder, switch, TeraCopy code, list file, and per file: source, destination, size, verified, hash, renamed name).
- Group outcome by TeraCopy code: 0 or none is **done**; 10 or 12 is **done-unverified** (the run is marked "some unverified" but is **not** failed); anything else is **failed**.
- Cancel: lets the current TeraCopy job finish and launches nothing more; remaining groups show cancelled. An ejected card also stops further jobs.
- Run end state: **cancelled** (session back to ready), **error** (any error; session to error with the first error message, or "copy failed"), or **done** (session to done). An ejected session stays ejected. Logs "run <id> <state> - N clips, M error(s), some unverified".
- Status reports per group (path, folder, destination, total, done, verified, failed, bytes, bytes done, state, code), totals, the current job (folder, file count, tag), errors, TeraCopy's last tick (state, seconds elapsed, files OK, total), whether anything was unverified, whether cancel was requested, and the post-copy health findings. A session with no run reports state **idle**.

## Card ingest: HTTP routes
(source: lib/routes/ingest.js)

- All routes are open to any local caller. A route that needs the runner before the server has finished starting answers **503** "ingest is still starting up - try again in a moment". An unknown session id answers **404** "unknown session" (session id from the body or the `sessionId` query).
- `GET /api/ingest/events`: a Server-Sent Events stream each open sorter tab holds. Tells the browser to reconnect after **2 seconds**; sends a keep-alive comment every **25 seconds**. Messages held for an expected tab are delivered when a tab connects. The open connections are the server's list of open tabs.
- `GET /api/ingest/tabs`: the number of open tabs and a `boot` timestamp that changes every server start (the tray uses it to notice a restart).
- `POST /api/ingest/detected` `{drive, kind, serial, label, removed, quiet}`: the tray reports a card inserted or removed. **400** "drive required (e.g. "K:")". For an insertion that is not `quiet`: if a tab is listening, every tab is told to open that card and the answer says `opened: true` (so the tray does not open another tab); if no tab is listening but one is expected (within **30 seconds** of telling the tray to open one, or within **10 seconds** after the last tab dropped), the message is held for it and `opened: true`; otherwise held messages are discarded and `opened: false`, so the tray opens a tab. `quiet` (a re-report of a card already in the reader) registers it and opens nothing. The `kind` field sent by the tray is passed along but the server decides the kind from the card's content.
- `GET /api/ingest/sessions`: every session summary (id, drive, kind, serial, label, camera, state, clip count, bytes, detection and scan times, error, warning count, health counts, run progress, plan id, capacity, which card it is and the card guess) plus TeraCopy warnings.
- `GET /api/ingest/sessions/:id`: the full card detail.
- `POST /api/ingest/plan` `{sessionId, mode, clipIds, copyProxies}`: builds and stores the session's plan; a ready session becomes **planned**. **409** "still scanning the card".
- `POST /api/ingest/link-folder` `{sessionId, planId, clipId}`: see "Linking a folder into a CC Sync project". Refusals: **409** "plan first (POST /api/ingest/plan)"; **409** "that plan is stale: plan again" (planId differs); **503** "folder linking is not available".
- `POST /api/ingest/run` `{sessionId, planId, clipIds, unassignedAction, copyProxies}`: runs the stored plan. Refusals in order: **409** "plan first (POST /api/ingest/plan)"; **409** "that plan is stale: plan again"; **409** "a copy is already running for this card"; **409** "TeraCopy is not available: <warnings>"; **409** "TeraCopy verify is off (TestAlways=1 missing in Options.ini). Run ingest/tray/Install.ps1, or set ingest.allowUnverified." (unless `ingest.allowUnverified`); **409** "assignments changed since the plan was made: plan again" (a quick re-plan gives a different assignments stamp). In final mode with `unassignedAction: "stage"` and unassigned clips, a second plan stages those clips to the staging root in the same run. `clipIds` narrows the first plan to the ticked clips. Returns the run id and job count.
- `POST /api/ingest/stage` `{sessionId, clipIds}`: plans and immediately runs a staging copy of the card (or the chosen clips), with no review. **409** "a copy is already running for this card". It does not apply the TeraCopy availability or verify-off refusals that `/run` applies.
- `GET /api/ingest/status?sessionId=`: the run status, the session state and the summary.
- `POST /api/ingest/dismiss` `{sessionId}`: dismisses the card (its assignments are deleted).
- `POST /api/ingest/cancel` `{sessionId}`: asks the run to stop after the current job; answers `ok: false` if nothing is running.
- `POST /api/ingest/rescan` `{sessionId}`: rescans the card.

## Linking a folder into a CC Sync project instead of copying
(source: lib/ingest/ccsyncLink.js, server.js, lib/routes/ingest.js)

- Offered only for a clip in state `elsewhere` in a final-mode plan: the same recording already sits, same size, at another final path.
- The offer exists only if: the existing copy's folder (or, if it is inside a folder named `Proxy`, the folder above that) is inside a folder marked as a CC Sync project (nearest `.ccsync-project` file walking up to the destination root, whose JSON has a `slug` of lowercase letters, digits and hyphens); that folder is not the project's own top folder ("tick both projects instead"); the planned destination is inside a different marked project.
- On the click (`POST /api/ingest/link-folder`), the server re-derives everything from its own stored plan (never a path from the request) and appends to the **borrowing** project's `.ccsync-project` file an `includes` entry: `{path: "Projects/<path below the destination root>", note: "clip <stem> already final here; folder linked instead of copied", added_by: "footage-sorter", added_at: <UTC time>}`. The leading segment is always the literal `Projects`, whatever the destination root's folder is called. Every other key in the marker is kept; the write is atomic (temporary file then rename).
- Already declared (compared after normalising slashes, trailing slash and Unicode form): answers `changed: false` and writes nothing.
- Refusals: **404** "unknown clip in this plan"; **409** "this clip is not filed elsewhere on the destination"; **409** "the existing copy is not inside another ccsync project"; marker not valid JSON: "the project marker is not valid JSON - fix <path> first" (em dash in the real text; answered as **500**); marker without a slug: "the project marker carries no identity (slug) - refusing to edit it" (**500**).
- Answer: whether the marker changed, the include path, the borrowing and lending project slugs.
- This is the one place the Node server writes a file inside the destination root.

## TeraCopy driver
(source: lib/teracopy.js)

- **Windows only** in practice: it runs `TeraCopy.exe` and `tasklist`, and reads TeraCopy's settings and history under `%APPDATA%\TeraCopy`. Needs Node's built-in SQLite module.
- Availability check (at boot, before every run, in the sessions list): TeraCopy present at `ingest.teraCopyPath`; history folder present (else warning "TeraCopy history folder not found at <dir> - copies can then only be checked by presence and size, never by TeraCopy's own hash verify."); `Options.ini` present (else "TeraCopy Options.ini not found at <path> - launch TeraCopy once, then re-check."); verify on, meaning `TestAlways=1` under `[Transfer]` (else "TeraCopy verify is OFF: set TestAlways=1 under [Transfer] in Options.ini, then restart TeraCopy so it reloads the file."). Missing exe: "TeraCopy not found at: <path>" and not available. (Em dashes in the real texts.)
- Launching a job: writes the list of source files (UTF-8, one per line, Windows line endings, atomic) to `data/ingest/lists/<tag>-<unix seconds>.txt` (with `-2` ... if taken; the tag is the folder name with non-ASCII-word characters turned into `_`), creates the destination folder, and runs `TeraCopy.exe Copy *"<list>" "<dest>" <switch> /Close` detached. Refuses a path containing a quote ("teracopy: unusable path (empty, or contains a quote)"), an empty list ("teracopy: nothing to copy") or no destination ("teracopy: no destination"). Logs the command line.
- Waiting for a job: every `pollSeconds` (**5**) it reads TeraCopy's per-job history database: the newest database created no earlier than **5 seconds** before launch, whose destination matches and whose first source file is one of this job's (so two cards copying into one folder never read each other's record). States: missing, locked (being written; never treated as finished), queued, running, copied (copy phase done, verify not yet), done (copy and verify both finished).
  - Done: returns.
  - Copied but no verify pass within `verifyGraceSeconds` (**180**): gives up waiting, logs "copy finished but no verify pass after N s."
  - TeraCopy not running for `idleGraceSeconds` (**60**) in a row: returns (logs "process gone; falling back to a destination check." or "process gone and no job record appeared.").
  - No job record and TeraCopy not running after `startGraceSeconds` (**120**): logs "no job started within N s." and returns.
  - `timeoutMinutes` (**0** = never): logs "still unfinished after N min; giving up waiting."
  - A progress line every **60 seconds**: "<state>, ok/total file(s) verified, N min elapsed" or "waiting (<state>), N min elapsed".
- Result codes: no files: none; **0** every file copied and hash-verified (logs "N/N file(s) copied and verified."); **10** finished but some files not verified (logs "finished with N of M file(s) not verified."); without a readable record it checks the destination itself by name and size: **11** a file missing or a different size (logs "N file(s) missing and M with a different size at the destination."), **12** all present with matching sizes but unconfirmed (logs "... treating as UNCONFIRMED."). A per-file receipt gives source, size, verified (TeraCopy result 3 is the only verified state), hash and the name actually written (if TeraCopy renamed the file).
- A job that throws counts as code 11.

## Clip identity (the clip key) and camera labels
(source: lib/clipkey.js)

- A clip's scan id is a hash of its master file's path, so it changes whenever the file moves. The **clip key** survives copying, in order of trust:
  - `umid:<id>`: Sony clips, from the recording id in the clip's XML sidecar.
  - `seq:<folder name>|<file count>|<bytes>`: image sequences (moved as a whole folder).
  - `fs:<lower-case stem>|<master size>|<YYYY-MM-DD recording day>`: everything else (Blackmagic RAW, drone, WAV, stills).
- A weaker **twin key** (`<stem>|<day>`) marks two clips that might be the same recording (for example both card slots of an FX3 recording to two cards, whose recording ids differ by one byte). It is never trusted alone: a twin only counts when the master sizes (or total sizes) match. No twin key without a stem and a day.
- Camera label for time folders: audio clips get the audio label; stills, sequences and "other" get none (they go straight into the destination, no time folder). A Sony model matching `FX3` but not `FX30` gets the FX3 label (`A-CAM`), other Sony models (`ILME`, `ILCE`, `ILX`, `PXW`, `FX`, `ZV`, `DSC`) the other-Sony label (`B-CAM`); then `.braw` or camera `BMCC` gets `BMCC`; a stem starting `DJI_` gets `DRONE`; a camera folder named `A-CAM` or `FX3` gets `A-CAM`, `B-CAM` gets `B-CAM`; otherwise none. The model from the sidecar beats the folder name.

## The catalog: where every copy of every clip is
(source: lib/catalog.js)

- Kept in `data/catalog.json`, one entry per clip key: stem, kind, camera, model, recording id, recording time, duration, bytes, master size, content hash (from TeraCopy, when verified), origin (card serial, card label, card kind, session, first seen), and a list of **locations**.
- Each location: shelf (`card`, `staging`, `final`, or `other`), path, scan id, last seen, present or not, how it was learnt (`scan`, `ingest`, `move`), verified and when, job id, file count, per-file sizes, damaged.
- Shelf of a path: `final` if under the destination root (wins if roots overlap), `staging` if under the staging root, else `other`. Path comparisons ignore case and slash direction and match whole folder names.
- **Nothing is ever deleted** from the catalog: a location that cannot be found is marked not present and keeps its last-seen time.
- Re-scanning a clip refreshes its fields, but a missing value never erases a known one. The origin is set once.
- Backup label of a clip, from present, non-damaged locations: `final-verified` (a verified final copy), `final`, `staging`, or none. A clip not catalogued under its own key is matched to a twin (same stem, same day, same master size; a twin with a safer copy wins); a sequence is never matched to a twin.
- A recorded copy: the source location (card or staging) and the destination location are both set; the destination is verified only if every file in the receipt was verified. When verified, the master's hash is stored on the clip; a different hash from an earlier copy logs "catalog: hash mismatch for <key>: had X, copy says Y" (it is still replaced).
- Folding a scan in: every scanned clip is recorded at its path under the given shelf, and (only for the roots actually scanned) locations under that root that were not seen are marked absent. A card scan never marks the destination absent.
- Reading the mover's journal: resumes from the byte offset it stopped at last time; a shrunk journal is re-read from the start (logs "journal ... shrank (rotated?) - rereading from 0"); a half-written last line is left for next time; an unparseable line is skipped and logged. Only lines marked `done` with a source and destination count. The clip is found by the line's clip id, then by the source path, then through the last move plan. Only the master's line changes the clip's location (proxies and XML lines are ignored); the new location keeps the old verified state; the old location is marked absent. Lines for unknown clips are counted as skipped.
- Loading: a missing catalog starts empty; an unreadable or corrupt one is logged ("... is corrupt (...) - starting empty") and replaced by an empty catalog in memory (overwritten on the next save).
- Saves are queued one after another so overlapping card copies never overwrite a newer catalog with an older one; a failed save keeps the changes pending.

## Footage moved by hand: the rules
(source: lib/relocate.js)

- Runs after every scan; never touches the disk.
- An assignment whose scan id is gone is looked up by its clip key; if exactly one present location of that key is in the scan (preferring the single final one if there are several), the assignment moves to that id ("re-keyed"). No key: unknown. No present location in the scan: "gone". Several: "ambiguous". Both left untouched. If the new id already has its own assignment, the stale one is just deleted.
- If the clip now sits under the destination root:
  - inside its assigned folder or a time folder of it: marked fulfilled ("found in place");
  - elsewhere and the assignment was never fulfilled: left alone (the next export moves it);
  - elsewhere, already fulfilled, and another present copy sits in the assigned folder: counted as a duplicate and left alone;
  - elsewhere and already fulfilled: the hand move wins; the destination becomes where the clip is (time-folder leaf folded into its parent), with the old one remembered ("moved by hand, adopted").
- Outside the destination root (moved around staging): only re-keyed.
- When every adopted clip of one folder went to the same other folder and no clip is left in the old one, that is a **folder move**: planned folders, placeholders, bindings and other assignments under it are renamed as the folder-move route would, and the pair is reported (for the mover's verify redirects).
- Description line, for example "3 re-keyed, 2 found in place, 1 moved by hand, adopted, 1 folder move(s): A -> B, 1 duplicate copies left alone, 4 gone, 1 ambiguous".

## The scanner: turning folders into clips
(source: lib/scan.js, lib/ingest/wav.js)

- Read-only on the footage. Writes only `data/clips.json` (atomically) when run as a full scan.
- Command line: `node lib/scan.js [root ...]` (also `npm run scan`): reads `data/settings.json` (a file with a byte-order mark fails to parse and defaults are used), replaces the source roots with any roots given, scans, writes `data/clips.json`, shows a running count every **500** clips, and prints "scanned N clips, X TB in Y s" and up to **20** warnings. It does not add the destination root (the server does).
- Roots: each root must exist and be a folder, else a warning "source root unavailable: <root> (<code>)" or "source root is not a directory: <root>". A "shallow" root (used for loose WAVs in a card's root) has only its own files scanned, not its subfolders. An unreadable folder adds "readdir failed: <dir> (<code>)".
- Skipped folders: `$RECYCLE.BIN`, `System Volume Information`, `#recycle`, `.git`, `node_modules`, `__MACOSX`, `.Spotlight-V100`, `.Trashes`, `.fseventsd`, `lost+found`, `dupe-quarantine` (where the duplicate purge tool parks files), any folder starting with `.` or `_sorter_test`, and the sorter's own program folder. Skipped files: `.DS_Store`, `Thumbs.db`, `desktop.ini`, `sync.ffs_db`, and names starting `._`.
- **Image sequences**: a folder (not the root itself) with a numbered run of at least **3** frames of the same name pattern and extension (`.exr`, `.png`, `.tif`, `.tiff`, `.dpx`) becomes one clip of kind `sequence`; the whole folder (all files below it) is the clip and is not descended into. Its date: a date found in its path with the time of day of its oldest file, else the oldest file's time.
- **Grouping**: files in a folder are grouped by name without extension. In each group, the highest-ranked file type is the **master** (video first: `.braw`, `.r3d`, `.mxf`, `.mov`, `.mp4`, `.m4v`, `.mts`, `.m2ts`, `.avi`, `.mkv`, `.mpg`, `.mpeg`, `.wmv`; then raw stills; then other stills; then audio). A JPG next to a raw still is its companion. Files in a `proxy` or `proxies` subfolder (and any folders inside it) join the clip of the same name as `proxy` (or `sidecar`/`meta`), with Sony's `S01`-style suffix stripped to match; an unmatched proxy becomes its own clip. Other files next to a master join it as `sidecar` (`.sidecar`, `.bnr`, `.cube`), `meta` (`.xml`, `.bim`, `.ppn`, `.smi`, `.srt`, `.thm`) or `other`, with Sony's `M01`-style suffix stripped to match. A group with no rankable file takes its first file (by name) as master.
- **Kind**: video, audio, still, or other, from the master's extension.
- **Camera**: `B-CAM` or `A-CAM` if the folder path names one, `BMCC` if the path mentions bmcc, bmpcc or blackmagic, `FX3` if the file name contains FX3, `BMCC` for `.braw`, `DRONE` for names starting `DJI_`, else `other`.
- **Recording time**, in order:
  1. Blackmagic file names `A007_08090854_C137` give month, day, hour and minute; the year comes from a date in the path, else a year in the path, else the file's modified time (moved back a year if that would put the shot more than **30 days** after the file was written).
  2. A Sony XML sidecar's creation date (its own time zone kept). The XML also gives duration (frames divided by frame rate), the recording id and the camera model; only the first **4 KB** are read.
  3. A date in the file name (or the path) with the time of day from the modified time. If the modified time falls on a different day than the name says, the container's own creation time is read with `ffprobe` from `ffmpegDir` (**20 second** timeout); only if that fails is the name-plus-modified-time used.
  4. The file's modified time.
  - All times are written at `tzOffsetHours` (default **8**).
  - WAV files: the duration is read from the header (an unclosed header uses the bytes actually on disk); if the time came from the modified time, the start is moved back by the duration (the recorder stamps a file when it closes it).
- Each clip gets a scan id (first 12 hex characters of a SHA-1 of the master path), a clip key, its source root and its folder relative to it, its files (master first), total bytes and file count.
- Clips are sorted by recording time, then name. Up to **24** files are checked at once per folder and **8** groups finished at once.

## Time folders: naming and reuse rules
(source: lib/timefolder.js)

- A time folder is named `<YYYY-MM-DD> <HH.mm>-<HH.mm> <camera label>`, for example `2026-08-09 08.54-15.06 A-CAM` (a dot instead of a colon, which Windows forbids). Clips are grouped by destination, camera label and local day; the range is the earliest to latest recording time in the group. The day and time are read straight from the recording time string (already in the shoot's local zone).
- No time folder for: time folders switched off, `preserve` structure, sequences, stills, "other" files, clips with no recording time, clips with no camera label. Those share one group per destination folder and land directly in it.
- Reuse, never rename: if an existing time folder under the destination for the same day and camera already holds one of the group's clips (known from the catalog's final paths, or by a file there with the same name stem and master size), its name is kept even if the new range is wider; the group records `mergesInto` and the warning "range widened: <fresh name> reused <existing name>".
- A folder with exactly the fresh name that holds none of the group's clips is someone else's shoot: the new folder takes ` (2)`, ` (3)` ... instead.
- Reading existing time folders: lists each destination (up to **8** at once), and for each folder whose name parses as a time folder, the name stem and size of every file directly inside it (subfolders such as `Proxy` are not looked into). A destination that does not exist reads as empty. Read-only.

## Thumbnails
(source: lib/thumbs.js, server.js)

- Made with `ffmpeg.exe` from `ffmpegDir` (default when unset: an `ffmpeg\bin` folder beside the program folder), at `thumbWidth` (**320**) pixels wide, JPEG quality 4, into `cache/thumbs/<clipId>.jpg` (written to a temporary name first).
- Source picked: for a sequence, the first image or video file found (searching subfolders, up to about **400** entries); otherwise a playable proxy (`.mp4`, `.m4v`, `.mov`, `.mxf`, `.mts`, `.m2ts`, `.avi`, `.mkv`), then a playable master, then a still's JPG companion, then an image master (`.jpg`, `.jpeg`, `.png`, `.tif`, `.tiff`, `.bmp`, `.exr`, `.dpx`, `.webp`), then any playable or image file. Nothing suitable (audio, Blackmagic RAW without a proxy, project files): failed.
- Video: tries the frame at **1 second**, then the first frame. Each ffmpeg run is killed after **45 seconds**.
- **2** thumbnails are made at a time. A request jumps to the front of the queue. A failed thumbnail stays failed until the server restarts.
- While a card is being copied, requests for its clips answer "pending" without reading the card.
- Sony cards: the camera's own thumbnails are copied in at card scan time (see card sessions), so most Sony card clips need no ffmpeg run.

## Reading a calendar title: which folder an event belongs to
(source: lib/infer.js)

- Configuration: `data/episodes.json` (no defaults in code beyond the root `2026/FF5`): `root`, `episodes`, `layout` (subfolders of every episode), `routes` (rules), `aliases` (title pattern to episode). Without the file, nothing is inferred.
- Kind of shoot from the title: **b-roll** if it contains `b-roll`/`broll`, `event`, `shooting`, `filming`, `montage` or the Chinese words for press conference, march, drill, competition, open tournament, course, activity, and no interview word; **interview** if it contains `interview` or the Chinese words for interview; otherwise b-roll if any b-roll word, else interview.
- In order of trust:
  1. **Routes**: the first route whose pattern matches the title (case-insensitive). A route can skip the event entirely (`skip`), force the kind, rename the interviewees branch, name an episode, or give a destination outside the episode tree. Reason: "route /<pattern>/".
  2. **Episode alias** in the title: the leftmost (then longest) matching alias picks the episode. Reason: "title matches /<pattern>/".
  3. **Roster name** in the title (Chinese name; the Chinese given name without its surname for 3-4 character names; the English name and each English word of 4 or more letters except titles; English names must match as whole words): with an episode already chosen, a person in that episode is preferred; with no episode, only a name that belongs to exactly one episode decides it. Reason: `"<name>" is in the <episode> roster`.
  4. **An existing interviewee folder** anywhere on the destination whose person folder's first word appears in the title (longest wins), for non-b-roll events only. Reason: `"<name>" already has a folder in <episode>`.
- Destination: `<root>/<episode>/B-roll/<subject>` for b-roll, `<root>/<episode>/Interviewees/<subject>` (or the route's branch) for interviews. The subject is the person's folder name `<Chinese> <English>` when a person was found (interviews), else the title with the leading/trailing ASCII alias and the words interview/broll/filming/online stripped. Characters Windows forbids become spaces; trailing dots and spaces go.
- An existing folder under the same parent whose name equals, starts with, or is the start of the subject is reused (the shortest such).
- A b-roll event with no subject goes into the episode's `B-roll` folder itself; an interview with no subject is not placed.
- Why an event was not placed: `skipped` (a skip route matched, with the rule), `ambiguous` (a roster name in the title belongs to several episodes, with the name and episodes), or `unmatched`.
- The standard episode skeleton (every episode plus every `layout` subfolder) is produced by this module; the server does not use it, only `tools/plan-episodes.js` does.

## Calendar suggestions: which shoot a clip belongs to
(source: lib/suggest.js)

- Only events with a folder (an explicit binding, or an inferred one) produce suggestions.
- **High** confidence: the clip's recording time is within **1 hour before** the event's start to **2 hours after** its end. **Low**: the nearest event with a folder on the same calendar day. Among candidates: a timed event beats an all-day one, then the closest, then the shorter, then the earlier.
- Each suggestion carries the folder, the event, its title, the confidence, the minutes off, and up to **3** alternatives (events that also fitted but point at other folders, with their window and minutes off).
- Event days are counted at most **400** days per event.

## The ICS calendar fallback
(source: lib/suggest.js)

- Reads the zip at `icsZip` (a Google Takeout style export), takes the first entry whose file name starts with `icsCalendarPrefix`, parses it and writes `data/calendar.json` (parse time and events, no `source` field).
- Errors: "not a zip file (no end-of-central-directory record)", "ZIP64 archives are not supported", "corrupt zip central directory at offset N", "corrupt zip local header for <name>", "unsupported zip compression method N for <name>", `no entry starting with "<prefix>" in <zip> (found: <names>)`. Entries are inflated up to **512 MB**.
- Times: UTC times as given; times with a time zone or none are treated as `tzOffsetHours` local time (no time-zone database); date-only values are all-day. A missing end means zero length (one day for all-day events).
- Recurring events: only daily and weekly rules (with interval, count, until, weekdays, week start) are expanded, between `calendarFromDate` (default **2026-04-01**) and **2027-01-01** (fixed), at most **2000** occurrences per event; monthly, yearly and others keep only their first occurrence, flagged recurring. An occurrence id gets `#YYYYMMDD`; an overridden occurrence gets `#<recurrence id>`.
- Events before `calendarFromDate` are dropped.

## The roster (who belongs to which episode)
(source: lib/roster.js)

- Command line only: `node lib/roster.js "<path to the planning sheet CSV>"` (also `npm run roster`). Without an argument it prints the usage line and exits 1.
- Reads a CSV with columns `Episode`, `Name` and optionally `Name EN` (refused with "CSV is missing an Episode/Name column" or "empty CSV"). The episode is set once per block of rows and carries down. A cell may hold several names separated by newlines, `;` or the Chinese enumeration comma (not by commas, since English names are written surname first); text in brackets is removed; the words broll, b-roll and some Chinese placeholder words are dropped. Chinese and English names are paired by position.
- Writes `data/roster.json` with only episode, Chinese name and English name per person (the sheet's emails, phones and addresses are not copied), the build time and the source file name. Prints "roster: N people across M episodes -> <path>" and a count per episode.

## Whose interview is on a recording: the scoring rules
(source: lib/audio-match.js)

- Text is split into tokens (each Chinese character is one token; each Latin word of 2+ letters is one), and compared in runs of **4** tokens. A recording matches a Vault transcript when at least **6%** of its runs are in it and at least **25** runs are shared.
- Vault transcripts: frontmatter, block reference lines and the leading `#` of interviewer lines are stripped.
- Signals, each proposing a folder with a score (the same folder proposed twice gets the higher score plus **0.08**, capped at 1):
  - **copy**: an identical file (same stem and size) is filed elsewhere: **0.92** if that folder is an interviewee folder ("An identical file is already filed here: <path>"), else **0.3** ("An identical file was also copied to <path>").
  - **transcript** (top 4 matches): **0.85** plus up to 0.1 if at least 25% and 120 runs match; **0.55** if at least 12% and 60 runs; else **0.3**. Evidence: "<n>% of what was said is in the Vault transcript of <name> (<episode>)", plus ", folder from the roster", ", but two folders carry that name" or ", no folder on P: carries that name". The folder is the interviewee folder on the destination whose name matches the person (Chinese name run contained, or two English name parts, or one distinctive English part of 4+ letters that is not one of about 70 common Taiwanese surnames); a tie is broken by episode; failing that, the roster inference.
  - **name** heard: **0.72** ("<name>" was heard on the recording, with a quote and time), **0.35** when only part of an English name was heard; a name on two episodes gives a folderless candidate at **0.4** ("... was heard, but is on two episodes (...)").
  - **intro** (first 6 self-introductions): the name cut at the first word that cannot be part of a name; **0.6** with a folder, **0.3** without ("Said: "<text>" @<n>s").
  - **calendar**: **0.7** for a high-confidence calendar suggestion, **0.35** otherwise ("Calendar: <title> - <why>").
- Confidence: **high** at 0.75 or more, **medium** at 0.45 or more, else **low**.
- Per transcript window, the best of the top 6 matching people is named when the window shares at least 6% and 8 runs with them.
- "Disagrees with where it is filed": only when the top candidate backed by a copy or a transcript is high confidence, points elsewhere, and no identical copy is filed where the clip sits.
- Nothing here assigns anything; the page shows the candidates and the person decides.

## The card tray (Windows system-tray watcher)
(source: ingest/tray/AutoBackupTray.ps1, ingest/tray/Config.psd1, ingest/tray/Start-Tray-Hidden.vbs)

- **Windows only** (PowerShell with Windows Forms). Started hidden by `Start-Tray-Hidden.vbs` (no console window), normally from the Startup folder at logon.
- Only one tray may run: a second start shows the message box "Auto Backup Utility is already running (see the system tray)." and exits.
- Tray icon: the standard Windows information icon; tooltip "Footage Sorter (watching for cards)" or "Footage Sorter (paused)". At start a balloon "Watching for cards."
- At start, deletes files in its `Logs` folder older than `LogRetentionDays` (**60**; 0 keeps everything), except `.handled.txt`.
- At start, if `StartServerOnLaunch` (**true**) and the sorter server does not answer, starts `node --disable-warning=ExperimentalWarning server.js` hidden in the repository folder (`RepoRoot`, default two folders up; `NodeExe` default `node`). It does not open a browser tab by itself.
- "Server answers" means `GET <ServerUrl>/api/scan/status` replies within **3 seconds** (`ServerUrl` default `http://127.0.0.1:8787`). Starting the server waits up to **15 seconds** (30 checks every 0.5 s) for it to answer.
- **Polling**: every `PollSeconds` (**3**) seconds, unless paused, it looks at every ready drive of a watched type (`WatchDriveTypes`: `Removable` and `Fixed`, so internal disks are checked too) and decides what the drive carries, in this order: Sony card (`PRIVATE\M4ROOT\CLIP` exists; an empty one still counts), drone (`DCIM\100MEDIA` holding `.MP4` or `.MOV`), Blackmagic (`.BRAW` in the root, not `._` files), loose audio (`.WAV` in the root whose name matches `*Wireless PRO*` or the recorder pattern `^\d{6}_\d{3}$`).
- Each drive gets a content signature (kind, volume serial or drive letter, file count, newest file name). A drive whose signature appears or changes is an **insertion**; a card sitting still never fires again; a card pulled and reinserted always fires.
- Cards already handled are remembered in `Logs\.handled.txt` (one signature per line). This list is only used on the first poll after the tray starts, so a card left in the reader at logon is not processed again.
- On an insertion:
  - Starts the server if needed, then reports the card (`POST /api/ingest/detected` with drive, serial, label and kind; **15 second** timeout).
  - The server answered and a sorter tab is showing it: balloon "<what> - showing in the sorter." (`<what>` is "Card on K:", "Drone clips on K:", "Blackmagic BRAW on K:" or "Loose audio on K:").
  - The server answered, no tab: balloon "<what> - opening the sorter..." and opens `<ServerUrl>/#ingest/<sessionId>` in the default browser.
  - The server answered but did not recognise the card: balloon "<what> - the sorter did not recognise it." (warning).
  - The server could not be reached and `LegacyWorkers` is off: balloon "<what> - but the sorter server is not running and could not be started." (error); the card is not marked handled, so it is tried again.
  - The server could not be reached and `LegacyWorkers` is on (**the default**): runs the old backup script for that kind (see "Legacy backup scripts") hidden, at most one per drive at a time, with the balloon "<what> - sorter unreachable, starting the old backup..." titled "Auto Backup (legacy)".
- On a removal: reports it to the server with `removed: true` (no answer awaited).
- After a server restart (the `boot` value from `GET /api/ingest/tabs` changed), every card still in a reader is reported again **quietly** (registered, nothing opened), because the server forgets cards when it restarts.
- Tray menu (right-click):
  - **Scan inserted cards now**: processes every inserted drive of a recognised kind again, even if handled before. If none could be processed: balloon "No Sony cards or Wireless PRO drives available to scan (none inserted, or all are already being backed up)."
  - **Open log folder**: opens the tray's `Logs` folder in Explorer.
  - **Pause monitoring** / **Resume monitoring**: toggles polling.
  - **Open Footage Sorter**: starts the server if needed (failure: balloon "The server could not be started. Run `npm start` in the repo."), then brings to the front any visible window whose title contains "Footage Sorter" (restoring it if minimised); if none, opens `ServerUrl` in the default browser.
  - **Server: ...**: a status line refreshed each time the menu opens: "Server: running (<url>)" or "Server: stopped (click a card action to start it)". Clicking it does nothing.
  - **Legacy: default target folder** (only when `LegacyWorkers` is on): submenu "A-CAM target: <path or (auto-detect)>" and "B-CAM target: <path or (auto-detect)>"; each opens a folder picker ("Choose the default <label> target folder. Dated subfolders are created inside it.", with a New Folder button) and writes the choice back into `Config.psd1` (`Fx3TargetPath` / `BCamTargetPath`), keeping comments; balloon "<label> target set to: <path>".
  - **Exit**: stops the tray.
- The tray sends a `kind` but the server decides the kind itself; the tray recognises drone footage only in `DCIM\100MEDIA`, while the server accepts any `DCIM\<nnn>MEDIA`.
- Any error during a poll is swallowed so the tray keeps running.

## Tray and legacy settings (Config.psd1)
(source: ingest/tray/Config.psd1, and the scripts that read it)

- Read by the tray, the installer and the legacy scripts; not by the Node server.
- `TeraCopyPath` `C:\Program Files\TeraCopy\TeraCopy.exe`.
- `SourceClipPath` `PRIVATE\M4ROOT\CLIP`; `ClipExtensions` `.MP4`, `.MXF`.
- `CopyProxies` true; `ProxySourcePath` `PRIVATE\M4ROOT\SUB`; `ProxySubfolderName` `proxy`.
- `Fx3ModelRegex` `FX3(?!0)`.
- `Fx3TargetFolderName` `FF-A-CAM`; `BCamTargetFolderName` `FF-B-CAM`.
- `Fx3TargetPath` `W:\Temp Transfer`; `BCamTargetPath` `W:\Temp Transfer` (per-camera target folders, set from the tray menu; when set, used as given and must exist, else the group is skipped).
- `TargetBasePath` `D:\Temp_Transfer` (used only for a camera whose per-camera path is empty: the `FF-*` folder under it). With both empty, every drive is searched for a root folder of that name.
- `Fx3FolderLabel` `A-CAM`; `BCamFolderLabel` `B-CAM`; `DateFormat` `yyyy-MM-dd`; `TimeRangeFormat` `HH.mm`.
- `AudioFilePattern` `*Wireless PRO*`; `AudioExtensions` `.WAV`; `AudioTargetFolderName` `FF-A-CAM`; `AudioMatchPaddingMinutes` **0**; `RecorderFilePattern` `^\d{6}_\d{3}$` (empty disables it).
- `DroneSourcePath` `DCIM\100MEDIA`; `DroneExtensions` `.MP4`, `.MOV`; `DroneTargetFolderName` `FF-B-CAM`; `DroneMinValidYear` **2020**.
- `BlackmagicExtensions` `.BRAW`; `BlackmagicFolderLabel` `BMCC`; `BlackmagicTargetFolderName` `FF-A-CAM`; `BlackmagicProxySourceFolder` `Proxy`.
- `WatchDriveTypes` `Removable`, `Fixed`; `PollSeconds` **3**.
- `TeraCopyConflictSwitch` `/OverwriteDiffSize`.
- `PythonPath` empty (auto-detect); `TeraCopyPollSeconds` **5**; `TeraCopyStartGraceSeconds` **120**; `TeraCopyIdleGraceSeconds` **60**; `TeraCopyVerifyGraceSeconds` **180**; `TeraCopyTimeoutMinutes` **0**.
- `CollisionPolicy` `Rename` (`Rename` keeps both, `Subfolder` puts colliding clips in a per-card subfolder, `Skip` drops the incoming file).
- `DualRecordSizeToleranceMB` **2**.
- `FreeSpaceMarginMB` **256**.
- `SlowMountRetries` **6**: defined, but nothing reads it (the scripts use a fixed 5 retries of 0.6 s).
- `ConfirmBeforeBackup` true.
- `LogRetentionDays` **60**.
- `ServerUrl` `http://127.0.0.1:8787`; `RepoRoot` empty; `NodeExe` `node`; `StartServerOnLaunch` true; `LegacyWorkers` true.

## Tray installer
(source: ingest/tray/Install.ps1)

- `Install.ps1`, re-runnable, Windows only:
  1. Checks TeraCopy exists ("[OK] TeraCopy found: ..." or a warning to fix `TeraCopyPath`).
  2. Edits TeraCopy's `%APPDATA%\TeraCopy\Options.ini` after backing it up to `Options.ini.bak`: `TestAlways=1` (verify after copy) and `Jobs=1` (one job at a time) under `[Transfer]`, `SaveReport.Enabled=0` under `[OnFinish]` (TeraCopy's own HTML report off). Tells the user to restart TeraCopy. If the file is missing: "launch TeraCopy once, then re-run Install.ps1."
  3. Creates the `Logs` folder.
  4. Creates `Auto Backup Utility.lnk` in the user's Startup folder, running `wscript.exe Start-Tray-Hidden.vbs`, with TeraCopy's icon and the description "Footage Sorter - card auto-backup tray monitor".
  5. Removes any "disabled in Task Manager" startup flag recorded for that shortcut name ("[OK] Cleared a stale 'disabled in Task Manager' flag on ..."); on failure a warning to re-enable it in Task Manager.
  6. Reports whether the A-CAM and B-CAM target folders can be found ("FX3 target ... not found on any drive yet." etc.).
  - Ends with "Install complete." and hints to double-click `Start-Tray-Hidden.vbs` and to test with `Backup-Card.ps1 -Drive K: -DryRun`.
- `-Uninstall`: removes the Startup shortcut ("Removed Startup shortcut." or "No Startup shortcut found."); TeraCopy settings are left alone.

## Legacy backup scripts: shared behaviour
(source: ingest/tray/Common.ps1, ingest/tray/TeraCopyStatus.py)

- Used only when the tray cannot reach the sorter server and `LegacyWorkers` is on, or when run by hand. They copy cards into the A-CAM / B-CAM transfer folders (not into the destination tree) with their own Windows dialogs. **Windows only**.
- Each run writes a log file in the tray's `Logs` folder (`backup|blackmagic|audio|drone <yyyy-MM-dd HH-mm-ss> <drive>.log`) and puts TeraCopy file lists there too (`list <stamp> <tag>.txt`).
- Notifications are tray balloons shown for **10 seconds** (text cut to 255 characters).
- Target folder for a camera: the per-camera path from the tray menu if set (must exist, else skipped); else `TargetBasePath\<FF-* folder>` (the base must exist); else the first drive (excluding the card itself) with a root folder of that name.
- TeraCopy is run with `Copy *"<list>" "<dest>" <switch> /Close` and then watched with the same rules as the Node driver (poll **5 s**, start grace **120 s**, idle grace **60 s**, verify grace **180 s**, no timeout by default), reading TeraCopy's history through `TeraCopyStatus.py` with Python (from `PythonPath`, else `python.exe` on the PATH, else `%LOCALAPPDATA%\Programs\Python\Python312\python.exe`; the Microsoft Store stub is ignored). Without Python, it waits for TeraCopy to exit.
- Result codes: **0** all copied and verified; **10** some not verified; **11** missing or wrong-size files; **12** completion not confirmed. Unlike the Node driver, when TeraCopy's record cannot be read but every file is present with the right size, the scripts return **0** and log "treating as copied, UNVERIFIED".
- `TeraCopyStatus.py <history dir> <destination> <since>` prints one line `state=... found=... copy_done=... verify_seen=... verify_done=... total=... ok=... bad=... db=...` and always exits 0. Unlike the Node driver, it does not check that the job's files are this run's own, so two jobs into one folder can be confused.
- Time-range folder names `HH.mm-HH.mm` (with optional ` (n)`); a range ending before it starts is taken to cross midnight.
- Dialogs: dark-themed windows always on top; if the rich dialog cannot be drawn, a plain Yes/No box with the plan as text; if even that fails, the script proceeds as if Yes was pressed.

## Legacy: Sony card backup
(source: ingest/tray/Backup-Card.ps1)

- `Backup-Card.ps1 -Drive K: [-DryRun]`.
- Refusals: TeraCopy missing (balloon "TeraCopy not found. Fix TeraCopyPath in Config.psd1."); no `PRIVATE\M4ROOT\CLIP` after waiting up to 3 seconds (logged, nothing to do); no `.MP4`/`.MXF` clips (balloon "No clips found on K:").
- Per clip, from its XML sidecar: camera model, recording date and recording id; without a sidecar, the file's modified time (logged). A model matching `Fx3ModelRegex` goes to the FX3 (A-CAM) target, anything else (including unknown model) to B-Cam.
- Proxies from `PRIVATE\M4ROOT\SUB` with the same name start ride with their clip.
- Grouped by camera type and date into `<target>\<date> <label>\<HH.mm-HH.mm>\` (one time-range folder per card). A folder already holding one of this card's recording ids is reused; otherwise a new folder is made (` (2)` ... if the name is taken). A sibling folder where at least half of this card's clip start times match but recording ids differ is flagged as a probable **dual record**.
- Per clip state against the compared folder: **MISSING - will copy**, **PARTIAL - will complete (+size)** (same recording id, card copy larger), **already backed up**, or **DIFFERS +/-size - likely same footage** (within `DualRecordSizeToleranceMB`, 2 MB) / **likely a DIFFERENT take**. Missing and partial clips are ticked by default; "differs" is unticked when a dialog is shown, ticked when running unattended.
- A group whose target is missing is shown red and skipped ("target folder '<name>' not found on any drive"); a group short of free space (needs size plus `FreeSpaceMarginMB`) is skipped with "not enough free space (...)".
- Plan dialog "Auto Backup - K:": header "Auto Backup - K:", "Card '<label>' · N clip(s) · X selected"; one card per destination group (green ok, orange warning, red missing target) with the destination, "X of Y selected (a missing, b partial, c present, d differ)" plus "[WILL SKIP: ...]" or "[overlaps '<folder>']", and "click to choose clips ▸". Buttons **Back up selected** and **Cancel**.
- Clicking a group opens "Choose clips - <type>": a checklist (name, time, size, note; coloured dot green missing, cyan partial, grey present, amber/red differs), with **All**, **None**, **Only missing**, **OK**, **Cancel**; for a dual-record group, a choice between "Write to NEW folder: <name>" and "MERGE into: <name>".
- Cancel: balloon "Backup of K: cancelled."
- Copying: each selected clip is re-checked against the final folder: **copy** (absent, or same recording id with a larger source; switch `/OverwriteDiffSize`), **collision** (same name, different id and size; handled by `CollisionPolicy`: `/RenameCopied`, `/SkipAll`, or a `<card serial or label or drive>` subfolder), **skip** (already there at full size). Proxies go into `proxy\` beside the clips.
- `-DryRun`: logs the plan with ticked/unticked clips and copies nothing.
- End balloon: "Backup complete (K:)" or "Backup finished with issues (K:)" with one summary line per group ("OK ...: copied=N, proxies=M, ... -> path", "SKIPPED ...", "ERROR ...").

## Legacy: Blackmagic card backup
(source: ingest/tray/Backup-Blackmagic.ps1)

- `Backup-Blackmagic.ps1 -Drive H: [-IgnoreUpTo <clip>] [-DryRun]`.
- `.braw` files in the card root (not `._` files). `-IgnoreUpTo` drops every clip whose clip number (`C<nnn>`) is at or below the one given (full name or `C197`); an unparseable value is ignored with a warning.
- Recording time: month, day, hour and minute from the name (`_MMDDHHMM_C`), year from the creation date in the macOS `._` metadata file, else the modified-time year; failing the name, the metadata date, else the modified time.
- Target: the A-CAM target (`Fx3TargetPath`, folder `FF-A-CAM`); missing: balloon "Target 'FF-A-CAM' not found (check Fx3TargetPath / drive connected)."
- Destination `<target>\<date> BMCC\<HH.mm-HH.mm>\`; an existing time folder already holding one of this group's clip names is reused.
- Before planning it indexes every `.braw` anywhere under the target by name and size; a clip found there is "already backed up elsewhere" and never copied.
- Clip states: **MISSING - will copy**, **DIFFERS - will re-copy** (different size), **already in this folder** / "media present - proxy will copy", **already backed up elsewhere**. Proxies (`Proxy\<clip>.*` on the card) go to `proxy\`.
- Dialog "Blackmagic footage - H:" with one card per date ("<date> BMCC - <range>"), per-clip chooser with **All**, **None**, **Only new**, **OK**, **Cancel**; buttons **Back up selected** / **Cancel**. Shown even when nothing is new.
- Messages: "Nothing to copy from H: (already backed up)." / "No clips selected from H: - nothing copied." / "Blackmagic backup of H: cancelled." / "Not enough free space on target (X free)." / "Blackmagic backup complete (H:)" / "Blackmagic backup finished with issues (H:)".

## Legacy: loose audio backup
(source: ingest/tray/Backup-Audio.ps1)

- `Backup-Audio.ps1 -Drive R: [-DryRun]`. Root `.WAV` files matching the Wireless PRO wildcard or the recorder pattern.
- Each file's interval: end = modified time, start = end minus the duration read from the WAV header (zero length if unreadable, with a warning).
- Placed into every A-CAM day folder whose name starts with the start date, and within it every time-range subfolder overlapping the interval (padded by `AudioMatchPaddingMinutes`); a day with no overlapping subfolder gets the file in its root ("root-fallback"). No day folder: skipped ("no FF-A-CAM folder for <date>"); audio never creates day folders.
- Per destination: new, re-copy (different size), or skip (same size).
- Dialog "Loose audio - R:" (one card per file; red for no matching day, orange for fallback or nothing to copy); buttons **Copy audio now** / **Cancel**. No per-file chooser.
- Messages: "Nothing to copy from R: (already backed up, or no matching days)." / "Audio backup of R: cancelled." / free-space error / "Audio backup complete (R:)" / "Audio backup finished with issues (R:)".

## Legacy: drone backup
(source: ingest/tray/Backup-Drone.ps1)

- `Backup-Drone.ps1 -Drive H: [-DryRun]`. Clips in `DCIM\100MEDIA` (`.MP4`, `.MOV`), dated by modified time.
- Placed in the root of every B-CAM day folder whose name starts with that date. No such folder: if the year is at least `DroneMinValidYear` (2020), a new `<date> B-CAM` folder is proposed (shown as "NEW FOLDER", blue) and created on copy; if earlier, the clip is skipped as a bogus timestamp ("bogus timestamp (<date>) - drone clock not set", "SKIPPED - can't route").
- Dialog "Drone footage - H:" with one card per clip; buttons **Copy drone now** / **Cancel**.
- Messages: "Nothing to copy from H: - already backed up. (N skipped: bogus timestamp)" / "Drone backup of H: cancelled." / free-space error / "Drone backup complete (H:)" / "Drone backup finished with issues (H:)".

## Legacy: field recorder audio placement (manual)
(source: ingest/tray/Backup-RecorderAudio.ps1)

- Run by hand only (not by the tray): `Backup-RecorderAudio.ps1 [-ManifestCsv <csv>] [-SourceFolder <dir>] [-IncludeBracketDay] [-DryRun]`. Defaults: manifest `Tools\recorder_dates.csv` beside the script, source `M:\FF-A-CAM\Audio Backup`, bracket-day placement on.
- Reads recovered recording times per file from the CSV (`file`, `status`, `real_date`, `real_time`, `duration_s`). `MATCHED` files with a time go into overlapping time-range folders of their day (else the day root); `BRACKET_DAY` files (date only) go into the day root; `BRACKET_RANGE` and `UNKNOWN` are listed as not placed.
- Refusals logged: manifest not found, source folder not found, TeraCopy not found, target not found, not enough free space. No dialog and no balloons; log only.

## NAS: cloud backup to the Hetzner storage box
(source: nas/cloud-backup.sh)

- A POSIX shell script that runs on the TrueNAS server (installed there by hand; this file is the source copy). It is meant to be started by a NAS cron job every **10 minutes** as the user `alex` (the cron entry itself is not in this repository).
- What it backs up, with restic into the repository `rclone:hetzner:restic` (a Hetzner Storage Box reached through rclone): `/mnt/tank/TheCreatorsPool/Creators_Club`, `/mnt/tank/backups/resolve-db`, and `/mnt/tank/backups/sorter/snapshots` when that folder exists (it creates it if it can). Exclusions come from `/mnt/tank/backups/cloud/restic-excludes.txt` (case-insensitive patterns; the file itself is not in this repository).
- Only one run at a time: a lock file `/mnt/tank/backups/cloud/.lock`; a tick that finds a run in progress exits silently.
- **When it uploads** (otherwise the tick exits doing nothing):
  - **Run now**: the file `/mnt/tank/backups/sorter/control/run-now` exists (written by the footage sorter). The trigger is claimed by renaming it to `run-now.taken` (or deleting it) before the run starts.
  - **Nightly**: `control/schedule.json` says enabled (default on) and the current time is at or past `nightlyAt` (default **04:15**, format `HH:MM`), and tonight's run has not started (marker `.nightly-<YYYY-MM-DD>`). A malformed or missing schedule file means the defaults. Day markers older than **7 days** are deleted.
  - A failed run is not retried automatically that night (the trigger was already claimed).
- The schedule file is read as data only (validated with Python), never executed.
- Settings for the upload: restic password from `~/.config/cloud-backup/restic-password`; cache in `/mnt/tank/backups/restic-cache`; progress reported every 2 seconds; bandwidth limit **12 MB/s from 08:00, 30 MB/s from 23:00**; **16** rclone connections; **64 MB** packs; skips creating a snapshot if nothing changed; tags the snapshot `manual` or `nightly`. Removes a stale restic lock first.
- Files it writes for the sorter to read, in `/mnt/tank/backups/cloud/`:
  - `LAST_STATUS`: one line `RUNNING|OK|FAIL <ISO time> <message>` ("started (<reason>)", "complete (<reason>)", "restic backup failed (<reason>), see <log>").
  - `last-run.json`: `{reason, startedAt}` at start, then `{reason, startedAt, finishedAt, rc}` at the end.
  - `progress.json`: the latest restic progress line while running (deleted at the end).
  - `last-summary.json`: restic's final summary. Success means a summary newer than the run's start.
  - `snapshot-ls.jsonl.gz`: after a successful run, the full file listing of the new snapshot (gzip). If listing fails it logs "ERROR listing ... failed" and keeps the previous listing; the backup still counts as successful.
  - `logs/cloud-backup-<date>.log`: start, end, errors, summary; logs older than **60 days** are deleted.
- Weekly pruning: the first successful run on a **Sunday** each ISO week forgets old snapshots keeping **24 hourly, 30 daily, 12 weekly, 24 monthly**, and repacks when more than **10%** is unused. Week markers older than **30 days** are deleted.
- Deletions on the NAS are not mirrored immediately: a deleted file stays restorable from older snapshots for the retention above.
- Exit code is 0 on success, 1 on failure.
- Not called by anything in the Node server; the sorter side that writes `control/` and reads these files is not in this part (see "Could not determine").

## Cloud: the backup ledger web service
(source: cloud/ledger/src/index.js, cloud/ledger/src/rules.js, cloud/ledger/wrangler.toml, cloud/ledger/package.json)

- A Cloudflare Worker named `backup-ledger` over one Cloudflare D1 database (`cc-backups`), served at `thecreatorsclub.co/backups/api/*`. Only the part of the path from `/api/` on matters, so it also works mounted at `/api/*`. One online record of every copy of every footage file, reported by every copying tool.
- Package scripts: `npm run dev` (local with token `devtoken`), `npm run deploy`, `npm test`.
- Tables are created automatically on first use.
- **Access**: every route except health needs `Authorization: Bearer <LEDGER_TOKEN>` (compared in constant time). No token configured: **503** "LEDGER_TOKEN is not configured". Wrong token: **401** "bad token". No database bound: **503** "storage not configured (bind a D1 database as DB)". The header `X-Ledger-By` names who answered a question (default `token`). A body that is not JSON: **400** "body is not JSON". Unknown route: **404** "no such route"; a path without `/api/`: **404** "not found". Any other failure: **500** with the message.
- **What is tracked**: only footage masters by extension (`.braw`, `.r3d`, `.ari`, `.mxf`, `.mov`, `.mp4`, `.m4v`, `.mts`, `.m2ts`, `.avi`, `.crm`, `.wav`, `.bwf`, `.aif`, `.aiff`, `.dng`, `.arw`, `.cr3`, `.nef`, `.insv`, `.lrv`); never anything under a `Proxy` folder, a `.sidecar`, an FX3 proxy (name ending `S03.mp4`), a macOS `._` file, or a temporary `*.tmp.<ext>` file. Untracked paths in a request are silently skipped.
- **Matching**: two copies are the same file when name (ignoring case) and size match and, when both have one, the modified times are within **3 seconds**.
- **Volumes**: a drive, card or share, with an id (for example `vol:<serial>`, `nas:P`), label, kind and owner. Kinds: `card`, `ours`, `client`, `nas`, `laptop` (a volume created without a kind is `unknown`); any other kind is refused (**400** "volume.kind must be one of ..."). A missing id: **400** "volume.id required". Updates keep fields that are not given.
- **Copies are never deleted**: a copy no longer found gets a "missing since" time and raises a question; it can later be marked moved (pointing at its new copy) or deleted (answered as such), but the row stays.
- Every write takes the next number of a global change counter, so a client can mirror the ledger.
- Every list in a request is limited to **5,000** items (**413** otherwise).
- `GET /api/health` (no token): whether storage works and whether a token is configured.
- `POST /api/copies` `{copies: [{volume, name, path, size, mtime, verified, byTool, byHost, clipKey, at}]}`: records verified copies. **400** "copies: [] required" or "each copy needs path and size". A known copy that was missing is marked present again; a copy recorded as `listed` is upgraded to `quick` when the report says `quick` or `full`; new copies are added (verification default `quick`, tool and host default `unknown`). Answers added, already known, skipped (untracked) count, and the change number. Then settles any pending "moved to this volume" answers.
- `POST /api/scan/delta` `{volume, roots, total, added: [[path, size, mtime]], gone: [[path, size]], back: [[path, size]]}`: what changed on a volume since the client's last look. **400** "added: [[path, size, mtime]]" on a malformed entry. `roots` limits which copies the listing speaks for. **Suspect-listing guard**: if something is marked gone, the volume previously had more than **100** live copies under those roots, and `total` is below **80%** of that: **409** "suspect listing: N files where M were; nothing changed (a half-mounted drive or a scan during chkdsk?)". Added files are recorded as `listed`; gone ones are marked missing; back ones present again. Answers counts and the questions raised.
- `POST /api/scan/begin` `{volume, byTool, byHost, roots}` returns a scan id; `POST /api/scan/chunk` `{scanId, files: [[path, size, mtime]]}` uploads part of a full listing (**400** "files: [[path, size, mtime]] required" / "each file is [path, size, mtime]"); `POST /api/scan/finish` `{scanId}` compares the full listing with the ledger: present-again, missing (under the roots), and new (`listed`). Unknown scan: **404** "unknown scan"; already finished: **409** "that scan is finished". The same suspect-listing guard applies (then the scan is closed as `suspect` and nothing changes).
- **Questions** ("these files left <folder> on <volume>: where did they go?"): raised per folder when files go missing. First, missing files that are still on the same volume (a file at the same path with a new size, or same name and size at another path) are linked to that copy and need no question. For the rest, one question per folder (added to an open question for that folder if there is one) with file count, bytes, and a suggested volume when one other volume holds a live copy of every missing file in it.
  - A question whose files all turn up again closes itself with the answer "found again" by "scan".
  - `GET /api/questions`: open questions, largest first.
  - `POST /api/questions/<id>` `{answer: "deleted"}`: marks the folder's missing copies deleted. `{answer: "moved", volume}`: links each missing copy to its live twin on that volume (must be a known volume, **400** "moved: volume must be a known volume id"); copies with no twin yet wait, and the question closes by itself once that volume's next scan or copy report supplies them. `{answer: "within"}`: links copies moved or replaced on the same volume; closes when none are left. Anything else: **400** "answer must be 'moved' (with volume), 'within' or 'deleted'". Unknown: **404** "unknown question". Already answered: **409** "already answered: <answer>".
- `POST /api/where` `{files: [[name, size, mtime]]}`: for each file, its copies (volume, label, kind, path, verification, missing) and a **verdict**: at home (a live copy on a `nas` volume), safe (at home, or live copies on at least two volumes of kind `ours`, `nas` or `laptop`), on a laptop, laptop-only (on a laptop and on no `ours`/`nas` volume), and how many counting volumes. Missing copies count for nothing. **400** "files: [[name, size, mtime]] required".
- `GET /api/changes?since=<seq>:<id>&limit=`: copies changed after the cursor, in order, up to `limit` (default and maximum 5,000), plus every volume, the next cursor and whether there is more.
- `GET /api/volumes`, `PUT /api/volumes` `{volumes: [...]}`: list and update volumes.
- `POST /api/repair/paths` `{volume, renames: [[id, newPath]]}`: rewrites the path and name of given copies on a volume (a one-off repair). **400** "volume and renames: [[id, newPath]] required" / "renames: [[id, newPath]]".
- `GET /api/not-home`: everything with no live copy on a `nas` volume, grouped by category (**laptop-only** first, then **ours** (on drives we own, not at home), then **not ours** (only on client drives or cards)), folder and where it sits, largest first; total bytes and file count; open questions; and a plain-text digest ("Not at home: X in N folders.", sections "⚠ Only on a laptop", "On drives we own, not at home", "Only on drives that are not ours (client drives, cards)", and "Where did these go? N folders no longer where they were:" with "probably <volume>"). Cached until the ledger changes.
- **Daily reminder email**: a scheduled trigger at **00:00 UTC** (08:00 in Taipei) sends the digest through the studio's mail relay (`LEDGER_RELAY_URL`, default `https://relay.thecreatorsclub.co/send`, key `LEDGER_RELAY_KEY`, **10 second** timeout) to `alex@thecreatorsclub.co`, sender name "Backups", subject "[backups] Not at home: X" plus " · ⚠ Y only on a laptop" and " · N to answer". Nothing is sent when the digest is empty; without the relay key nothing is sent (logged as not configured).
- Secrets and bindings: `LEDGER_TOKEN`, `LEDGER_RELAY_KEY`, `LEDGER_RELAY_URL` (optional), database binding `DB`.
- Not called by the Node server in this part (see "Could not determine").

## Operator tool: check footage already on disk for dead clips
(source: tools/check-footage.js)

- `node tools/check-footage.js <folder> [<folder> ...] [--json out.json] [--all]`. No folder: prints the usage line and exits **2**.
- Walks every folder given, skipping `$RECYCLE.BIN`, `System Volume Information`, `.cache`, `proxy`, `sub`, `thmbnl`, `_quarantine` folders and `._` files; checks every file of the health-check types with the same checks as card ingest (see "health check"), plus: an `.mp4` named like a Sony clip (`fx3_`, `fx6_`, `fx30_`, `C<4 digits>`) whose `M01.XML` beside it is 0 bytes is suspect (a missing XML is not reported).
- Prints `DAMAGED <path>` or `check   <path>` with each problem (`ok      <path>` too with `--all`), a progress line every **200** files on standard error, and "N files checked in X s: D damaged, S to check". `--json` writes the folders, time, count and results to the file given.
- Exit code **1** when anything is damaged, **2** on a crash, else 0. Read-only on the footage.

## Operator tool: generate the sort-order table for the Python engine
(source: tools/gen-collation.js)

- `node tools/gen-collation.js`: writes `footage_sorter/_collation.py`, a generated table of Node's own text-sorting weights (locale `en-GB`, three levels: base, accent, full) for punctuation, symbols, Latin, Greek, Cyrillic, kana and full-width characters plus every character in this machine's `data/clips.json` and `data/manifest.json`, and the order of every Chinese ideograph in the basic plane, so the Python engine sorts names exactly as the Node server does. Prints the count and the ICU version. DEV ONLY.

## Operator tool: raw image of a camera card
(source: tools/image-card.ps1)

- `tools\image-card.ps1 -Drive K: [-OutDir <dir>] [-Name <name>] [-BufferMB 8] [-SourcePath <file>]`. **Windows only; needs an elevated PowerShell.**
- Takes a sector-by-sector copy of the whole physical disk behind the drive letter, so clips the health check flags (zeros, no index, `.RSV`) can be carved out later after the card is reused.
- Refusals (red "image-card: ..." and exit 1): "give the card as -Drive K:"; "raw disk reads need an elevated PowerShell (Run as administrator), then run this again"; "no partition has the letter K:"; "K: is on the system disk - refusing"; "<size> to write but only <free> free on <root>" (needs the disk size plus **1 GB**; skipped for a network path); with `-SourcePath`, "no such file: <path>".
- Output: `<OutDir>\<label>_<serial>_<yyyyMMdd-HHmmss>.img` (default folder `W:\Card Images`; name from the volume label and serial, else `card_<letter>`; forbidden characters become `_`), never overwriting an existing file, and a `.json` beside it with drive, label, file system, serial, disk number, model, bus, size, partition style, image path, bytes read, complete or not, SHA-256 of the image, unreadable ranges and their total, start and finish times.
- Reads in **8 MB** blocks (`-BufferMB`); a block that fails is retried in **4096**-byte sectors, and unreadable sectors are written as zeros and listed. A progress bar every **2 seconds** shows done, total, speed and time left.
- Ends with "Done: <size> in <time>, sha256 <hash>", "<n> unreadable range(s), <size> zero-filled - see <json>" if any, and "Recover from the image, not the card: PhotoRec / untrunc -s on <img> (mount it read-only with OSFMount to browse)." A short read prints "Short: read N of M bytes" and exits **2**.
- `-SourcePath` images an ordinary file instead (for tests). DEV ONLY in that mode.

## Operator tool: plan the episode folder skeleton
(source: tools/plan-episodes.js)

- `node tools/plan-episodes.js [--port 8787] [--dry]`: builds every episode folder plus every `layout` subfolder from `data/episodes.json` (error "data/episodes.json not found") and sends them to the running server's `POST /api/folders/bulk` (port from `--port`, else `settings.json`, else 8787). Prints "<n> episodes x <m> folders = <k> planned folders", then "added N new planned folder(s); M planned in total", any rejected names, and "They are created on disk when you run mover.ps1 -Execute." `--dry` lists the folders and sends nothing. Failure: "failed: <message>" and "(is the server running? node server.js)", exit 1.

## Operator tool: plan a folder for every interviewee on the sheet
(source: tools/plan-interviewees.js)

- `node tools/plan-interviewees.js [--port 8787] [--dry] [--for "<Episode>=<path>"] ...`: gives every person in `data/roster.json` a folder in their episode's `Interviewees` folder, as **placeholders** (shown in the tree, not created on disk until a clip lands in one).
- Needs `data/episodes.json` and a non-empty roster ("data/roster.json is empty - run: npm run roster -- "...FF5 - FF5.csv"").
- Reads the running server's destination tree and state to learn every known folder and which folders hold assigned clips. The episode's `Interviewees` folder is the one ending in `/<episode>/Interviewees` that holds clips (shortest path wins), else any such folder (flagged "<-- nothing is filed here, check this"), else `<root>/<episode>/Interviewees`. `--for "Bear=2026/FF5/Animals/Interviewees"` pins one.
- A person already filed under that episode's folder (a folder holding clips whose path contains their Chinese name, or their English name of 5+ characters) is left alone. Otherwise the folder name is `<Chinese> <English>`, reconciled onto an existing near-identical folder.
- Prints people count, already-filed count, to-plan count, skipped rows, the folders per episode, and "N folder(s) still empty - held as placeholders: shown greyed out in the tree, and NOT created on disk until a clip lands in one." `--dry` sends nothing. Otherwise sends the still-empty folders (or, if there are none, the new ones) to `POST /api/folders/bulk` with `placeholder: true`, then prints the result and "No assignment was touched."

## Operator tool: quarantine verified duplicate copies
(source: tools/purge-dupes.js)

- `node tools/purge-dupes.js [plan|verify|execute] [--date YYYYMMDD] [--port N] [--jobs N] [--quarantine PATH]`; no command means a dry run. An unknown command prints usage and exits 2. Needs `data/settings.json` to exist (it crashes otherwise).
- **This tool moves footage** (the only Node code in this part that does): it moves redundant copies from the staging root or destination root into a quarantine folder, default `W:\Temp_Backup\Dupe-Quarantine`, keeping their path relative to the root they came from. It never deletes; the operator deletes the quarantine folder by hand. The scanner skips any folder named `dupe-quarantine`.
- `plan`: asks the running server (port from `--port`, `FS_PORT`, settings, else 8787; **20 minute** timeout) for a fresh move-plan export, saves the answer to `data/logs/export-response-<date>.json`, reads `data/moveplan.json`, and lists candidates in `data/dupes-<date>.json`:
  - "already there": the identical file is already at the destination;
  - "duplicate": two identical sources for one destination; which copy is kept is decided by preference lists (folders named `2026-04-12 B-Cam` are kept; `Editor Added\home`, `Leso\FF5未備份`, `Leso\遊行` lose ties);
  - "collision, destination exists": the destination holds a different copy;
  - "collision, several sources": the first by preference is kept, the rest are candidates.
  - A kept copy that is itself a candidate is followed to the copy that really stays; a loop is refused ("circular keep chain"). Anything outside the staging and destination roots is refused ("outside allowed roots").
- `verify` (resumable, **3** workers by default): per candidate against its kept copy: identical SHA-256 (same size); else, for media (`.mp4`, `.mov`, `.mxf`, `.braw`, `.m4v`, `.avi`, `.wav`, `.mp3`, `.m4a`) with ffmpeg from `ffmpegDir`, identical video and audio packet checksums ("streams"); else, if the candidate is smaller, each stream's frame checksums being a strict prefix of the kept one ("streams-prefix", a card that stopped early); finally an XML or sidecar whose media sibling verified ("sibling"). Anything that fails stays put with the reason. Saves progress every 10 items; prints a summary per bucket and state, and up to 40 failures.
- Dry run / `execute`: for each verified item, refuses (logged as skip) when: outside allowed roots, source gone, source size changed, the kept copy is gone ("kept copy is gone - refusing to quarantine the only copy"; a kept copy the mover has since moved, per the mover journal, still counts), or the quarantine path is taken. `execute` renames each file into quarantine, journaling `start`, `done`, `skip` and `error` lines to `data/logs/dupes-journal.jsonl`; the first rename error stops the run (exit 1). Prints "moved N file(s), X GB; skipped M".

## Operator tool: re-key assignments after a move
(source: tools/rekey-assignments.js)

- `node tools/rekey-assignments.js [--apply] [--data DIR]`: for assignments whose clip id is no longer in `clips.json`, looks up the assignment's clip key in the catalog, finds the clip id of its present final location, and moves the assignment to that id, but only if that id is in the current scan and has no assignment of its own.
- Prints counts (total, still live, re-keyable, no key, no present final location, new id already used, new id not in scan) and up to 10 example re-keys; a note when some point at footage the scan does not contain ("Rescan with destRoot included first, or those stay orphaned.").
- Dry run by default ("Dry run - nothing written. Re-run with --apply to write."). `--apply` copies the manifest to `manifest.backup-<timestamp>.json`, writes the new manifest atomically, and says to restart the server or rescan. It writes the manifest file directly, without the server's timestamped copy.

## Operator tool: screenshots of the pages
(source: tools/ui-shots.js)

- `node tools/ui-shots.js <prefix> [url]`: DEV ONLY. Starts headless Chrome (`CHROME`, default `C:/Program Files/Google/Chrome/Application/chrome.exe`) with a debugging port of 21000 plus the last three digits of the port, opens the page (default `http://127.0.0.1:<FS_PORT or 8787>/?mock=1&n=400`, the page's built-in mock data), answers thumbnail requests from the mock itself, and writes `docs/ui/<prefix>-<name>.png` for 18 fixed views (desktop 1440x900; phone 390x844 at 2x with touch): start, clips (two picked), events, suggest-menu, review, drives, info, move, ingest, source, source-hidden, calendar, overlays (a right-click menu and four toasts), phone-start, phone-clips, phone-filters, phone-source, phone-drives, phone-folders. Reduced motion is emulated and local storage cleared before each shot. Needs the server running.

## Operator tool: find who is talking on audio clips (Whisper)
(source: tools/whisper-names.py)

- `python tools/whisper-names.py [--all] [--limit N] [--window 300] [--max-minutes 0] [--model large-v3] [--beam 5] [--batch 0] [--device cuda] [--rescan] [--full] [--under <folder> ...] [-v]`. Needs Python with `faster-whisper` and `pypinyin`, and `ffmpeg`/`ffprobe` on the PATH. On Windows it adds NVIDIA libraries installed in Python's site-packages to the PATH.
- Which clips: every scanned clip with a `.wav` file; by default only those not assigned (`--all` includes assigned ones); `--under` limits to folders (and then includes assigned ones); `--limit` caps the count. Clips with an identical copy elsewhere (same stem and size) go last; otherwise smallest first.
- Per clip: reuses its cached transcript in `cache/whisper/<clipId>.json` (`--rescan` ignores it); a clip with no cache adopts the transcript of a clip with the same stem, same size (if known) and duration within **1 second** (a moved file). Missing files ("MISSING, skipped") and files under **5 seconds** ("no usable audio, skipped") are skipped.
- Transcribes in windows of `--window` seconds (**300**), cutting each window out with ffmpeg as 16 kHz mono, with Whisper model `--model` (**large-v3**) on `--device` (**cuda**, float16; otherwise int8), beam `--beam` (**5**), with voice-activity filtering, or batched (`--batch` > 0). It stops at the first roster name or self-introduction, unless `--full` (whole file). `--max-minutes` caps how far into a file it goes. Saves after every window, so a run can be resumed.
- Names: a roster person's Chinese name (3+ syllables) heard as the same pinyin sequence (so a different character with the same sound still matches); an English name heard whole, or two of its 5+ letter parts; a name with a single usable part matches as "english-partial" (flagged). A name on two episodes is marked ambiguous. A quote with its time is kept.
- Self-introductions: lines with "我是", "我叫", "這位是", "我們今天訪問" or "my name is", "i am called" followed by a name ("某某" placeholders excluded).
- Writes `data/whisper-names.json` (`version`, time, model, and per clip: stem, seconds scanned, duration, names heard, introductions) after every clip, dropping entries for clips no longer in the scan. Prints a line per clip ("+ name (via) -> episodes "quote" @Ns", "~" for ambiguous, "? <name>" for an introduction only, "." for nothing with any cue words heard), and a summary. It never assigns anything.

## The mover script: carrying out the move plan
(source: mover.ps1)

- `mover.ps1` (Windows PowerShell 5.1 or later) is the component that moves footage from the source and staging folders into the destination tree, following `data\moveplan.json` written by the server. Three modes; the default is a dry run:
  - `powershell -NoProfile -File mover.ps1` (dry run), `-Execute`, `-Verify` (optionally with `-ThisRun` or `-Since <line number or ISO time>`).
  - `-Plan <path>`: the plan file (default `data\moveplan.json` beside the script).
  - `-LogDir <path>`: where markers, the journal and reports go (default `data\logs`; created if missing).
  - Refusals before anything runs: "Use either -Execute or -Verify, not both."; "-ThisRun and -Since only apply to -Verify."; "Plan file not found: <path>"; "Plan file is empty: <path>"; "Plan file is not valid JSON: <message>"; "Plan file parsed to null.". Any such error prints "MOVER ABORTED", the message, and "Nothing was deleted or overwritten.", exit 1.
- **What it never does**: delete anything, copy footage, overwrite (moves are made without force, so an occupied destination makes the move fail), or remove emptied source folders (they are listed as "REPORTED ONLY, nothing is deleted"). The only things it creates are destination folders, its own markers, journal, reports and mapping file.
- Paths may contain brackets, spaces and Chinese characters; paths of 240 characters or more use the Windows long-path form for file reads and writes. Console output is UTF-8.
- **Plan checks** (every entry needs `src` and `dst` strings, a non-negative number `bytes`, optional `isFolder` true/false; a missing `entries` list is a problem, an empty one is allowed for a folders-only plan):
  - source and destination must be clean absolute paths (no `*` or `?`, no `..`, `.` or doubled separators);
  - source and destination not the same; a folder not moved into itself;
  - every destination (and every planned folder) inside the plan's `destRoot`;
  - no two entries with the same destination, no two with the same source;
  - on disk: the source exists and is the right type (file or folder), its size equals the plan's (folders are summed recursively, skipping the same junk files and folders the scanner skips), the destination does **not** exist ("COLLISION - dst already exists"), and the destination's parent is not a file.
- **Journal**: `move-journal.jsonl` in the log folder, one line per event `{ts, src, dst, bytes, phase, clipId}`, phases `start` and `done`, written and closed line by line so a crash loses nothing. A malformed last line is ignored as a torn write ("NOTE: ignoring malformed final journal line N (torn write)."); a malformed line anywhere else is a problem that blocks the run.
- **Dry run**:
  - Prints a header "FOOTAGE SORTER - MOVER *** DRY RUN (nothing will move) ***" with plan path, SHA-256, generation time, destRoot, entry count, run time.
  - Entries the journal records as done, whose destination exists and source is gone, are "already done" and skipped; if the journal says done but the disk disagrees, that is a problem.
  - Prints files to move, folders to move, already done, total size, and the destination folders that will be created (console shows the first 25 of any list, the report file has all).
  - Clean: "RESULT: CLEAN - every source exists with the expected size and no destination path is occupied.", writes a **dry-run marker** `dryrun-ok-<first 16 of SHA-256>.json` (plan path, hash, entry count, total bytes, time, `pass`), and says "-Execute" is now allowed for **60 minutes**. Exit 0.
  - Problems: "RESULT: N PROBLEM(S) - nothing may be moved.", lists up to 50 on screen, writes no marker. Exit 1.
  - Report file `dryrun-report-<yyyyMMdd-HHmmss>.txt` with the full planned move list.
- **Execute**:
  - Gate 1: a passing dry-run marker for this exact plan content, no older than **60 minutes** and not more than 5 minutes in the future. Otherwise "REFUSED - no valid dry-run gate:" with the reason (no passing dry run for this content, unreadable marker, not a pass, hash mismatch, unparseable time, "dry-run is stale (N minutes old, limit 60)", "dry-run marker is dated in the future (clock problem)"), the dry-run command to run, "Nothing was moved.", exit 1.
  - Resume from the journal: `done` with destination present and source gone is skipped; `done` otherwise is a problem; `start` with destination present and source gone is "recovered" (the journal gets its missing `done` line); `start` with source present and no destination is retried; `start` with both or neither present is a problem needing manual review.
  - Gate 2: all plan and disk checks again for every pending entry. Any problem: "REFUSED: re-validation found N problem(s). NOTHING was moved.", exit 1.
  - Creates every planned folder and every destination parent (even when there is nothing to move, so a folders-only episode skeleton still gets made). A folder that cannot be created stops the run ("FAILED to create folder: ...", "Nothing was moved.").
  - Nothing to move: "No files to move - this plan only carried folders." or "Nothing left to move - the plan is already complete. Run -Verify to confirm.", then "RESULT: OK - N folder(s) created, nothing moved." Exit 0.
  - Moves one entry at a time: checks again that the destination is still free ("COLLISION: destination appeared before the move") and the source still there ("source vanished before the move"), writes `start`, moves, checks the destination exists ("move reported success but dst does not exist"), writes `done`, and checks the destination's size ("moved, but dst size is N B (expected M B)"). The **first error stops the run**. Progress every **25** moves.
  - End: "RESULT: OK - N item(s) moved, X." (plus how many were already done), or "RESULT: STOPPED ON FIRST ERROR" with the failed entry, the reason, counts completed / skipped / not attempted, the list still to move, and "Nothing was deleted or overwritten. Fix the cause, re-run the dry-run, then -Execute again: already-moved entries are skipped via the journal." Lists source folders now empty. Report `execute-report-<stamp>.txt`. Exit 0 or 1.
- **Verify**:
  - "No journal found - nothing has been moved yet." exit 1 if there is no journal.
  - Checks every distinct `done` entry (or, with `-ThisRun`, only those in the plan file, default `data\moveplan.json`, refused with "-ThisRun needs a plan file to scope to: <path>" if missing; with `-Since`, only lines from that line number or time).
  - Each destination must exist with the journalled size and its source must be gone ("dst MISSING", "size mismatch", "cannot read dst size", "src STILL EXISTS after move"). A destination later moved again by the mover is followed through the journal (up to **64** hops, "superseded"); a destination under a folder the server recorded in `journal-redirects.json` (longest prefix first) is checked at its new place ("relocated"). Both count as verified.
  - Always rewrites `moved-mapping.csv` (every `src,dst` ever moved, UTF-8 with a byte-order mark so Excel shows Chinese names).
  - Prints counts (journalled, verified OK with size, superseded, relocated, problems, CSV path), source folders now empty, and "RESULT: ALL VERIFIED - every moved item is at its destination with the expected size and no source remains." (exit 0) or "RESULT: N PROBLEM(S)" (exit 1). Report `verify-report-<stamp>.txt`.
- The server reads the journal afterwards to update the catalog and mark assignments fulfilled (see "Mover journal reconciliation"). The server never runs the mover; a person runs it in a PowerShell window.

## Which side does what: the Node server versus the Python engine
(source: server.js and lib/routes/*.js; the Python engine's route table in footage_sorter/web.py was looked at only to settle overlap, not inventoried)

- The Node server is a local, single-user program on one Windows computer (127.0.0.1:8787, no login). Nothing in the Node code makes it reachable from the CC Sync dashboard.
- The Python engine answers most of the same paths with the same shapes, and is the one mounted inside the CC Sync dashboard (at `/sorter`); it is the side that knows who is asking. Paths both answer: `/api/state`, `/api/scan`, `/api/scan/status`, `/api/assign`, `/api/unassign`, `/api/folders`, `/api/folders/bulk`, `/api/folders/remove`, `/api/folders/move`, `/api/source-roots`, `/api/dismiss-event`, `/api/bindings`, `/api/desttree`, `/api/events`, `/api/thumb/...`, `/api/proxy/...`, `/api/mediainfo/...`, `/api/reveal`, `/api/export-moveplan`, `/api/catalog/summary`, `/api/catalog/reconcile`, `/api/catalog/audit`, `/api/catalog/audit/status`, `/api/catalog`, `/api/catalog/:key`, `/api/ingest/events`, `/api/ingest/sessions`, `/api/ingest/status`, `/api/ingest/plan`, `/api/ingest/run`, `/api/ingest/stage`, `/api/ingest/cancel`, `/api/ingest/dismiss`, `/api/ingest/rescan`.
- Differences visible from the route tables:
  - Moves: the Node server only writes `moveplan.json` and the PowerShell mover carries it out by hand; the Python engine answers `/api/export-moveplan` with its own planner and adds `/api/moves/*`, where an administrator executes the moves on the server itself.
  - Cards: the Node server takes cards from the Windows tray (`/api/ingest/detected`) and copies with TeraCopy on this PC; the Python engine answers `/api/ingest/detected` and `/api/ingest/link-folder` with 501 ("not here: the card is in a PC, and its CC Sync companion reads it").
  - Only the Node server answers: `/api/google/*` (Google sign-in and calendar choice), `/api/settings`, `/api/cards*` (crew card tracker), `/api/audio` and `/api/audio/:clipId`, `/api/ingest/tabs`, `/api/ingest/sessions/:id`, `/api/ingest/link-folder` (as a working route).
  - Only the Python engine answers: `/api/state/meta`, `/api/dest/*`, `/api/clips`, `/api/clip/...`, `/api/whoami`, `/api/strip/...`, `/api/ingest/restore`, and the whole `/api/ledger/*` family (volumes, watched folders, auto-backup, questions, not-home, cloud backup schedule and run-now, drive copies).
- The cloud ledger web service and the NAS cloud-backup script are not called by any Node code in this part; the Python engine's ledger routes are the likely client (not confirmed here).

## Looks redundant or overlapping

- Two complete servers for one product: the Node server and the Python engine answer the same ~35 routes with the same shapes; every rule in `lib/` (scan, infer, suggest, timefolder, catalog, relocate, plan, health) has a Python twin, and `tools/gen-collation.js` exists only to make the Python side sort text exactly like Node.
- Three generations of card copying: the legacy PowerShell scripts (`Backup-Card/Blackmagic/Audio/Drone.ps1`, own dialogs, copying into `FF-A-CAM`/`FF-B-CAM`), the Node ingest (sessions, plans, TeraCopy, catalog), and the Python engine's companion-based cards. The tray still falls back to the legacy scripts by default (`LegacyWorkers = $true`).
- Card-kind detection is written twice in this part (the tray's `Resolve-DriveWork` and `lib/ingest/detect.js`) and they already differ (drone: `DCIM\100MEDIA` only versus any `DCIM\<nnn>MEDIA`).
- TeraCopy job watching is written twice (`Common.ps1` + `TeraCopyStatus.py`, and `lib/teracopy.js`), with different results for an unreadable record (0 versus 12) and different job matching (destination only versus destination plus own source files).
- WAV duration reading is written twice (`lib/ingest/wav.js`, `Get-WavInfo` in `Backup-Audio.ps1`).
- Time-range folder naming exists in three forms: the server's `<date> <HH.mm>-<HH.mm> <CAM>` leaf, the legacy scripts' `<date> <label>\<HH.mm>-<HH.mm>` two-level layout, and the cloud ledger's own folder notion.
- Two ways to re-key assignments after footage moves: automatic after every scan (`lib/relocate.js`) and the manual `tools/rekey-assignments.js`.
- Two "is this footage backed up?" records: the local catalog (`data/catalog.json`) and the cloud ledger (D1), with different identity rules (clip key versus name + size + time).
- Two health-check entry points over the same checks: card ingest and `tools/check-footage.js`; plus `tools/image-card.ps1` as the follow-up.
- Two duplicate handlers: the export's "already there / duplicates" filtering and `tools/purge-dupes.js`, which re-runs the export to find the same items.
- Calendar input has two paths (Google Calendar and the ICS zip) with separate parsers.
- Settings writes go three ways: `/api/settings` (three keys, on-disk merge), `/api/cards/serial` (on-disk merge), `/api/source-roots` (writes the whole in-memory settings, including environment overrides).
- The Vault root default is written twice in `server.js` (`DEFAULT_SETTINGS.vaultRoot` and `VAULT_DEFAULT`).

## Claims the code does not back

- `server.js` header: "this process NEVER writes, renames, moves or deletes anything under settings.sourceRoots or settings.destRoot". The link-folder action (`lib/ingest/ccsyncLink.js` `addInclude`) writes `.ccsync-project` files inside the destination root directly, outside the write guard; TeraCopy launched by the server writes footage there; `lib/teracopy.js` creates the destination folder itself (`mkdirSync`) besides the guarded creation. The route comment does call link-folder "the ONE write outside data/".
- `server.js` header: "Every write goes through writeAppFile()/appPath()". There is no `appPath()`; `lib/scan.js` (clips.json), `lib/google.js` (token and calendar files), `lib/suggest.js` (calendar.json), `lib/thumbs.js`, `lib/ingest/session.js` (Sony thumbnails) and `lib/teracopy.js` (list files) write with plain file calls.
- `lib/routes/catalog.js` and `server.js` `audit.start()`: the "400 destRoot not configured" is answered as 500, because the server's error handler ignores the error's status.
- `lib/routes/catalog.js` header lists a `lookupByStem` dependency; nothing passes or uses it (stem lookup scans the catalog inline).
- `lib/ingest/plan.js` header promises dual-record warnings ("two cameras rolling on the same take"); `dualRecordWarnings` always returns an empty list.
- `lib/ingest/session.js` header: states "scanning -> ready -> planned -> copying -> done | error"; a cancelled run sends the session back to `ready`, which the header does not list.
- `mover.ps1` comment: its skip lists "MUST use the same exclusions as lib/scan.js"; the scanner also skips `dupe-quarantine`, folders starting with `.` or `_sorter_test`, and `._` files, which the mover's size check does not, so the mover counts bytes the scan did not.
- `mover.ps1` header: "No Copy-Item of footage". True of the script's own calls, but `Move-Item` between different drives (for example `W:` staging to `P:`) is itself a copy followed by a delete of the source.
- `tools/purge-dupes.js` header: moves are "same volume, no copy, no delete". It accepts files under the destination root as well as the staging root while the quarantine default is on `W:`; a file on another drive cannot be renamed there and the run stops with an error.
- `ingest/tray/Backup-Drone.ps1` header: "A date with no matching B-CAM day folder is skipped and reported". The code proposes and creates a new `<date> B-CAM` folder (only pre-2020 dates are skipped).
- `ingest/tray/AutoBackupTray.ps1` "Scan inserted cards now" balloon says "No Sony cards or Wireless PRO drives"; the action covers drone and Blackmagic drives too.
- `ingest/tray/Config.psd1`: `SlowMountRetries = 6` "How many poll ticks the tray keeps re-checking a freshly inserted drive"; nothing reads it.
- `ingest/tray/Config.psd1` / `Install.ps1` describe `LegacyWorkers` as a transition aid to be turned off; it is on in the shipped config.
- `ingest/tray/Install.ps1` synopsis: "turns on TeraCopy's own saved report, pointed at this utility's Logs folder"; the code turns the report off (`SaveReport.Enabled=0`).
- `cloud/ledger/src/rules.js` comment: "lib/ledger.js, which mirrors it and is tested against it"; there is no `lib/ledger.js` in the working tree (the Python engine has `ledger_rules.py`).
- `ingest/tray/Backup-RecorderAudio.ps1` defaults its manifest to `Tools\recorder_dates.csv` beside the script, made by `Tools/wavematch*.py`; neither exists in the working tree.

## Could not determine

- How the CC Sync dashboard shows the sorter. Nothing in the Node code serves it to another machine; the Python engine's header says the dashboard mounts the Python app. Whether the Node server is still used at all on the studio's machines, beyond the tray starting it at logon, cannot be told from this part.
- Who writes `/mnt/tank/backups/sorter/control/run-now` and `schedule.json`, and who reads `LAST_STATUS`, `progress.json`, `last-run.json` and `snapshot-ls.jsonl.gz` for the NAS backup; no Node code does. The cron job itself and `restic-excludes.txt` are not in the repository.
- Who calls the cloud ledger web service and with which token file (`wrangler.toml` mentions `data\ledger-token.json`); no Node code in this part does.
- Whether `Move-Item` of a whole image-sequence folder across drives succeeds in the mover (PowerShell refuses cross-volume directory moves in some versions); the code does not handle it specially.
- Whether the tray's `kind` field is used anywhere: `lib/ingest/session.js` receives it but decides the kind from the card's content.
- The exact page behaviour behind `#ingest/<sessionId>` and the Server-Sent Events `open` message (the pages are another section).
- `settings.calendarToDate` is read by the Google fetch but has no default and is not editable through any route; whether anyone sets it by hand is unknown.
- `skeleton()` in `lib/infer.js` is used only by `tools/plan-episodes.js` (and the Python side); whether the page offers an equivalent is in another section.
- What the cards tracker site's `/api/state`, `/api/usage` and `/api/backup` do on their side (another repository).
- `lib/timefolder.js` contains one NUL byte inside a string literal (the key prefix for groups without a time folder); it behaves as an ordinary separator, but whether it is deliberate is unknown.
