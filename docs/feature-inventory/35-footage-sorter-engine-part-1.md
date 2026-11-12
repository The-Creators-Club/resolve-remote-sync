# Footage Sorter: the engine, part 1 (scanning, collating, sorting, ingest, suggestions, the catalogue)

Terms used throughout:

- **Clip**: one recording as the sorter sees it. Not a single file: a group of the master file plus its proxy, sidecar, XML and camera thumbnail. An image sequence (a folder of numbered frames) is one clip.
- **Master**: the one file that names a clip (the highest-ranked file of the group, see "Scanning").
- **Clip id**: a 12-character hex id derived from the master's full path. It changes when the file moves.
- **Clip key**: an identity that survives copying (UMID, sequence signature, or name+size+day). Used by the catalogue.
- **Source roots**: folders the sorter scans for footage that still needs sorting (staging, other PC folders).
- **Staging root**: where cards are dumped when they are not sorted straight away. Defaults to the first source root.
- **Destination root (`destRoot`)**: the studio's sorted project tree (the "final" shelf).
- **Destination ("dest")**: a folder path relative to the destination root, written with `/` (for example `2026/FF5/Energy Transition/B-roll`).
- **Manifest**: the sorter's record of intent: which clip should go to which destination, planned folders, calendar bindings.
- **Catalogue**: the sorter's record of fact: every physical place each clip has been seen.
- **Time folder / leaf**: an automatically named sub-folder under a destination, named for the day, the time span and the camera.
- **Card session**: one memory card sitting in a reader on some editor's computer, as reported by that computer's CC Sync companion.
- **Pool root**: the mount point of the NAS footage dataset that contains both the destination and staging roots.
- **The host**: whatever runs the engine: the CC Sync dashboard (mounted at `/sorter`) or the standalone development server.

## Running the engine standalone (development)
(source: __main__.py)

- Command: `python -m footage_sorter --data DIR [--cache DIR] [--port N] [--host-settings JSON] [--no-background]`. DEV ONLY.
  - `--data` (required): the data folder holding `settings.json`, `clips.json`, `manifest.json`, `catalog.json` and the rest.
  - `--cache`: thumbnail and strip cache folder. Default `<data>/../cache`.
  - `--port`: default `8790`.
  - `--host-settings`: a JSON object of settings that override `settings.json` (roots, ffmpeg folder and so on).
  - `--no-background`: starts none of the background loops (no calendar refresh, no tree walk, no thumbnail backfill, no folder watch, no nightly scan, no ingest polling).
- Always binds to `127.0.0.1` only. There is no login standalone: every caller is treated as user `local` with admin rights.
- Logs at INFO level to the console.

## Settings
(source: config.py, engine.py, ingest.py, startview.py, scan.py)

- Settings are layered: built-in defaults, overlaid by `<data>/settings.json`, overlaid by what the host supplies. Host values always win. A nested object (for example `timeFolders`) merges key by key one level at a time; anything else replaces the lower value.
- After merging: `destRoot`, every `sourceRoots` entry and `stagingRoot` are path-normalised; an empty `stagingRoot` becomes the first source root.
- `settings.json` may start with a byte-order mark; a missing or unparseable file is treated as empty.
- Settings with defaults:
  - `sourceRoots` (default empty list): folders scanned in full.
  - `destRoot` (default empty): the destination root. Many features refuse without it (see each).
  - `stagingRoot` (default empty, then the first source root): where staged card copies land.
  - `icsZip` (default empty): path to a zip of calendar exports, used when no Google calendar is connected.
  - `icsCalendarPrefix` (default empty): which file inside that zip is the calendar (the first entry whose name starts with this).
  - `calendarFromDate` (default `2026-04-01`): events starting before this local day are not kept from the zip.
  - `googleCalendarIds` (default empty): shown in the calendar status block.
  - `calendarRefreshMinutes` (default `15`, minimum 5 in effect): how often the calendar background refresh runs.
  - `ffmpegDir` (default empty): folder holding `ffprobe`/`ffprobe.exe`; empty means look on the PATH.
  - `vaultRoot` (default empty): transcript folder for the audio matcher (used by the second half).
  - `tzOffsetHours` (default `8`): the studio's fixed UTC offset; used for every recorded time without its own zone.
  - `thumbWidth` (default `320`).
  - `timeFolders.enabled` (default `false`): whether sorted clips get automatic time folders.
  - `timeFolders.labels` (defaults: FX3 `A-CAM`, other Sony `B-CAM`, Blackmagic `BMCC`, drone `DRONE`, audio `AUDIO`): the camera word in a time-folder name.
  - `cards` (defaults: url `https://thecreatorsclub.co/cards`, syncMinutes 15, serials {}, capacities {}): the card tracker (second half).
  - `legacyIdRoots` (default empty): a map from NAS path prefix to the Windows path the old Windows machine knew it by, so a clip keeps the same clip id after the move to the NAS.
  - `shallowRoots` (default empty): folders scanned for their own files only, never their sub-folders (for loose WAV files beside a drone card's DCIM folder). A shallow root that is also a full source root is scanned in full.
- Settings without a default that the engine reads:
  - `poolRoot`: the NAS footage mount. If absent, the common parent of `destRoot` and `stagingRoot` is used; if they share no parent below a drive or filesystem root, card copies and NAS drive copies are refused.
  - `machineName`: what this server calls itself in computer lists (default `NAS` on Linux/macOS, the host name in lower case on Windows).
  - `computers`: extra computer names always shown in the Source panel's computer list.
  - `legacyMachine`: the computer that Windows-drive source roots belonged to (written by the migration tool).
  - `sourceMachines`: map of source root to computer name (written by the migration tool).
  - `watchSeconds` (effective default 20, minimum 5): interval of the folder watch.
  - `nightlyScanAt` (effective default `03:30` local): time of the nightly full scan.
  - `ingest.copyProxies` (effective default false): whether card copies include proxy files when the request does not say.
  - `ingest.freeSpaceMarginMB` (effective default 256): free-space margin a card copy plan requires on top of the bytes it needs.
- Writing settings: only the source-roots route (below) and the Google calendar routes (second half) write `settings.json`. Settings are written pretty-printed (2-space indent).

## Where the sorter writes, and how
(source: files.py, engine.py, catalog.py, migrate.py)

- Every write the engine makes is refused unless the target is inside the data folder or the cache folder ("refusing to write outside the sorter's own folders: <path>"). Footage itself is never written by the engine; only the mover (second half) renames footage.
- Every file write is atomic (temporary file, flush, fsync, rename). Appends to log files are fsynced line by line.
- Files the engine maintains in the data folder:
  - `settings.json`: settings (see above).
  - `clips.json`: the last scan (scan time and every clip), written compact.
  - `manifest.json`: intent (assignments, planned folders, placeholder folders, bindings, dismissed events), written compact.
  - `catalog.json`: the catalogue, written compact.
  - `calendar.json`: parsed calendar events (when built from the ICS zip).
  - `episodes.json`: hand-edited inference rules (read only).
  - `roster.json`: the people roster (read only by the engine).
  - `watch.json`: every folder the last scan walked, with its modified time (for the folder watch).
  - `moves/<id>.json`: each move plan made.
  - `moves/withheld.json`: clips whose master moved but whose other files have not yet.
  - `logs/manifest-ops.jsonl`: one line per manifest edit (time, user, operation, detail).
  - `logs/manifest-YYYYMMDD.json`: a copy of the manifest, rewritten on every save that local day (so it holds the day's last state).
  - `logs/journal-redirects.json`: old destination path to new path, written when a whole destination folder is found moved outside the sorter.
  - `ledger/ledger.db`: the ledger (second half).
- In the cache folder: `mediainfo/<clipId>.json` (media-info answers), plus thumbnails and strips (second half).

## Clip identity
(source: ids.py, clipkey.py)

- Clip id: first 12 hex digits of SHA-1 of the master's full path (for an image sequence, the folder's path).
  - When `legacyIdRoots` maps a NAS prefix to a Windows path, a path under that prefix is hashed in its Windows form (backslashes, drive letter), so ids made on the old Windows machine stay valid. The deepest matching prefix wins.
- Clip key (the identity the catalogue uses), most trusted first:
  - `umid:<UMID>` when the Sony XML gave a UMID.
  - `seq:<folder name lower-case>|<file count>|<bytes>` for an image sequence.
  - `fs:<stem lower-case>|<master size>|<YYYY-MM-DD recorded day>` for everything else.
- Twin key: `<stem lower-case>|<day>`, used only to find a size-confirmed twin (the same recording on a camera's second card slot, or the same footage catalogued under a different key). Never an identity on its own.
- Camera label for time folders (first rule that applies):
  - audio clips: the audio label; stills, sequences and "other": no label (no time folder).
  - Sony model from the XML containing `FX3` (not `FX30`): A-camera label.
  - any other Sony model prefix (ILME, ILCE, ILX, PXW, FX, ZV, DSC): B-camera label. The model beats the folder name.
  - master is `.braw` or the scan's camera guess is BMCC: BMCC label.
  - stem starts `DJI_`: drone label.
  - camera guess `A-CAM` or `FX3`: A label; `B-CAM`: B label; else none.

## Scanning footage folders
(source: scan.py, wav.py usage)

- A scan is read-only on footage: it lists folders, stats files, reads the first 4 KB of Sony XML files, reads WAV headers and occasionally runs ffprobe. It never writes, renames or deletes anything under a scanned root.
- What gets scanned by a full scan: every source root, plus the destination root (added automatically if not already listed), plus shallow roots.
- Per root:
  - A root that does not exist gives the warning `source root unavailable: <root> (ENOENT)`; a root that is a file gives `source root is not a directory: <root>`. The scan carries on with the other roots.
  - A folder that cannot be listed gives `readdir failed: <folder> (<error code>)`.
- Folders skipped (case-insensitive): `$recycle.bin`, `system volume information`, `#recycle`, `.git`, `node_modules`, `__macosx`, `.spotlight-v100`, `.trashes`, `.fseventsd`, `lost+found`, `dupe-quarantine`; any folder whose name starts with `.`; any folder whose name starts with `_sorter_test`; any folder inside the sorter application's own folder.
- Files skipped: `.ds_store`, `thumbs.db`, `desktop.ini`, `sync.ffs_db`, and any file starting `._`.
- Symbolic links are not followed.
- Proxy folders: a sub-folder named `proxy` or `proxies` (any case) is not scanned as its own folder; its whole contents, including nested folders, are read as part of the folder above it.
- Image sequences: a folder (other than a root itself) holding a numbered run of at least 3 frames with the same prefix, extension and digit count, in `.exr .png .tif .tiff .dpx`, becomes ONE clip and is not descended into.
  - Its size and file count are the whole folder tree's.
  - Its recorded time: a date found in the path, with the time of day of the oldest file's modified time; else the oldest modified time.
  - Camera is always `other`.
- Grouping files in one folder into clips, by file name without extension ("stem"):
  - The master is the highest-ranked extension of the stem. Ranking (high to low): BRAW, R3D, MXF, MOV, MP4, M4V, MTS, M2TS, AVI, MKV, MPG, MPEG, WMV; then raw stills ARW, DNG, CR3, CR2, NEF, RAF, ORF, RW2, SRW, PEF; then PSD, EXR, DPX, TIF/TIFF, HEIC/HEIF, PNG, BMP, JPG/JPEG; then audio WAV, AIF/AIFF, FLAC, M4A, MP3, AAC, OGG. Ties broken by name order.
  - A JPG beside a raw still of the same stem is that still's `still-jpg` companion; other second-ranked files are `other`.
  - Files in a proxy folder join the clip of the same stem as `proxy` (or `sidecar` for `.sidecar .bnr .cube`, `meta` for `.xml .bim .ppn .smi .srt .thm`). A Sony proxy named `<stem>S03` joins `<stem>`. A proxy with no matching clip becomes a clip of its own so nothing is lost.
  - Other files beside the master join it as sidecar, meta or other. A Sony `<stem>M01.XML` joins `<stem>`.
  - A group with no master-ranked file (a lone XML or LUT) still becomes a clip: its first file by name is called the master.
- Clip kind from the master's extension: `video`, `audio`, `still`, or `other`; `sequence` for image sequences.
- Camera guess (first match): the folder path contains `B-cam`/`Bcam` as a word: `B-CAM`; `A-cam`: `A-CAM`; `bmcc`, `bmpcc` or `blackmagic`: `BMCC`; stem contains `fx3` as a word: `FX3`; master is `.braw`: `BMCC`; stem starts `DJI_`: `DRONE`; else `other`.
- Recorded time (`recordedAt`, an ISO time with a fixed offset), first source that works:
  1. Blackmagic file names such as `A007_08090854_C137` give month, day, hour, minute. The year comes from a date in the path with the same month and day, else a year in the path, else the file's modified time; if that guess would be more than 30 days after the modified time, the previous year is used (shot in December, copied in January).
  2. Sony XML `CreationDate` (kept at its own offset; a zone-less value gets `tzOffsetHours`).
  3. A date in the file name (`2026-08-09`, `2026_08_09`, `20260809`), else a date in the folder path (deepest folder first). If the file's modified day matches that date, the modified time's hour and minute are used; if not, ffprobe is asked for the container's `creation_time` (converted from UTC to the studio offset; 20 s timeout); if ffprobe has nothing, the date with the modified time's hour and minute is used.
  4. The file's modified time.
  - For a WAV whose time came from the modified time, the start is moved back by the recording's length (a recorder stamps a WAV when it closes it).
- Duration: from the Sony XML (frames divided by capture, format or timecode frame rate, rounded to 0.01 s), or from the WAV header.
- Sony XML also supplies the UMID and the camera model.
- Sony card structure is folded after grouping:
  - A camera thumbnail `THMBNL/<stem>T01.JPG` (or such a JPG beside its video when a card was copied flat) is moved into its video clip as a non-master file, so it travels with the video.
  - Proxies in a Sony card's `SUB` folder (`<stem>S03.MP4`) are moved into the matching video in the sibling `CLIP` folder as proxies.
  - Clips made only of card index files (anything under `AVF_INFO`, `MEDIAPRO.XML`, `CUEUP.XML`, `STATUS.BIN`) are flagged as card index clips: never listed in the grid, but copied when a whole card is copied.
  - This folding is also applied to a stored `clips.json` when the engine loads, so older scans are regrouped without rescanning.
- Clips are sorted by recorded time, then by stem.
- Performance limits: 24 parallel workers for stats and per-file reads. What was learned from reading a file's content (XML, WAV length, ffprobe time) is remembered against the file's path, size and modified time between scans; the memory is cleared when it exceeds 200,000 entries.
- Platform differences: ffprobe is looked for as `ffprobe.exe` then `ffprobe` in `ffmpegDir`; when absent there, `ffprobe.exe` on Windows and `ffprobe` elsewhere; with no `ffmpegDir`, the PATH. On Windows ffprobe runs with no console window.

## Full scan
(source: engine.py)

- Started by `POST api/scan` (see routes), after every move, after every card copy, nightly, and once on first start when there is no folder-watch map yet.
- Only one full scan at a time: a second request answers `started: false, running: true` with the previous clip count and byte total.
- `?wait=1` (or body `wait: true`) runs the scan inside the request and answers the new count, bytes, scan time and any error.
- During a scan the clip count is published as progress.
- On completion, in order: the clips replace the old ones; `clips.json` is rewritten; the folder-watch map is replaced by what this scan walked; the move journal is reconciled into the catalogue; staging/destination clips already in the catalogue are re-linked and anything under a scanned root that was not seen is marked "not present"; clips moved outside the sorter are adopted (relocation, second half); thumbnails are queued (staging first, newest first); the destination tree is re-read; the opening page answers are rebuilt ahead of time.
- An exception in the scan is recorded as the scan's `error`; the previous clips stay.
- Nightly full scan: once a day at `nightlyScanAt` (default 03:30 local), as a safety net under the folder watch.

## Folder watch (new footage without a rescan)
(source: engine.py, scan.py)

- Every `watchSeconds` (default 20 s, minimum 5 s; first look 20 s after start) the engine reads the modified time of every folder the last scan walked and rescans only folders whose time changed.
- A new sub-folder is found because its parent's time changes; it is scanned with everything under it.
- A deleted folder drops its clips.
- A root that is not reachable (drive unplugged, pool not mounted) concludes nothing: its clips stay as they were.
- Files still being copied are not clips yet: a clip is only accepted once its files are seen with the same size and time at two consecutive looks. Until then the clip as it was before is kept (if it existed), and the folder is looked at again for 3 more looks after it last changed.
- Skipped while a full scan is running ("a full scan is running") or while a previous look is still under way.
- When anything changed: clips are merged and regrouped, the move journal is reconciled, staging is re-linked in the catalogue, out-of-sorter moves are adopted, new clips get thumbnails, the destination tree is re-read, and opening answers are rebuilt.
- `clips.json` is written at most once a minute after watch changes, and on shutdown.
- `scan_status` reports the watch's last look time, folders looked at, folders changed, and files still arriving.
- Rescan specific folders now: `POST api/scan` with `{"paths": [...]}`. Only folders that exist and are inside a source root or the destination root count; if none do, 400 "none of those is a folder inside a source or destination root". Runs in the background; answers `{started: true, folders: N}`. This catches a file replaced in place under the same name, which does not change the folder's time.

## The catalogue (where every clip physically is)
(source: catalog.py, engine.py)

- One entry per clip key, holding: stem, kind, camera, model, UMID, recorded time, duration, bytes, master size, hash, origin (card serial, card label, card kind, session, first seen), and a list of locations.
- A location holds: shelf (`card`, `staging`, `final`, `other`), path, clip id at that path, last seen time, present yes/no, how it was learned (`scan`, `ingest`, `move`), verified yes/no and when, the copy job id, file count, per-file sizes, damaged yes/no.
- Shelf of a path: under `destRoot` is `final` (wins over staging if they overlap); under `stagingRoot` is `staging`; else `other`. Path comparison is case-insensitive with either slash.
- Nothing is ever deleted from the catalogue. A location that is not found gets `present: false` and keeps its last-seen time. An unplugged card, unmounted drive and deleted file look the same.
- A richer scan's details are never erased by a thinner scan's blanks.
- A corrupt or unreadable `catalog.json` is logged ("catalog: <file> is corrupt (...) - starting empty") and the catalogue starts empty (it can be rebuilt by rescans and an audit).
- Backup status of a clip ("backup" label shown on each clip), from present, undamaged locations only: `final-verified` if a verified copy is in the destination; `final` if any copy is in the destination; `staging` if a copy is in staging; else none.
- Twin matching: when a clip's own key is not in the catalogue (and it is not a sequence), an entry with the same stem and day whose master size matches (or, when master sizes are unknown, total bytes match) is used. If several match, the one best backed up wins (final-verified, then final, then staging), then key order. A clip that borrowed a twin's status is flagged `backupTwin`.
- Recording a copy (from card ingest): the source location is recorded with its per-file sizes; the destination location is recorded with per-file sizes, verified only if every file reported verified; a verified master hash is stored in upper case, and a hash that differs from a previously stored one is logged ("catalog: hash mismatch for <key>: had X, copy says Y").
- Reconciling the mover's journal (on every scan, watch change, plan, and `POST api/catalog/reconcile`): new "done" lines since the last read are applied. Each moved master gets a new location (shelf from its new path, via `move`, keeping its verification, file count and sizes) and its old location is marked not present. Moves of proxies and XML are not locations. A journal shorter than the stored read offset is treated as rotated and reread from the start. A torn last line is left for next time. Unparseable lines are logged and skipped. Lines whose clip cannot be identified are counted as skipped.
- After reconciling, an assignment is marked fulfilled only when ALL of the clip's planned files moved (journal says done, or the destination exists and the source is gone). A clip whose master moved but whose other files did not is "withheld" (persisted in `moves/withheld.json`) so its leftover files can be planned again, even after a restart.
- Audit (`POST api/catalog/audit`): scans the destination root in the background and links every clip found as `final`, marking anything under the destination that was not seen as not present. Refused with 400 "destRoot not configured". A second audit while one runs answers `started: false`. Progress, linked count and any error are in `GET api/catalog/audit/status`.
- Summary: clip count, location count, present locations per shelf, number of clips with a verified destination copy.

## Calendar: reading events
(source: suggest.py, engine.py)

- Event sources: a connected Google calendar (second half) is synced first; otherwise `calendar.json`. If `calendar.json` has no events list and `icsZip` is set, the zip is parsed and `calendar.json` is written.
- `calendar.json` is reloaded only when its modified time changes.
- ICS parsing:
  - Folded lines are unfolded on raw bytes (so a fold inside a multi-byte character still decodes).
  - Only `VEVENT` blocks are read; properties inside nested blocks (alarms, time zones) are ignored.
  - Start and end: UTC times (`Z`) as given; floating or `TZID` times are read as studio-local (`tzOffsetHours`, default 8) whatever the zone named; date-only values are all-day events.
  - Missing end: an all-day event lasts one day; a timed event has zero length. An end before the start is ignored.
  - Text unescaping of `\n`, `\,`, `\;`, `\\`.
  - An overridden recurring instance gets uid `<UID>#<RECURRENCE-ID>`.
  - Recurrence: only DAILY and WEEKLY rules are expanded, honouring INTERVAL, COUNT, UNTIL, BYDAY and WKST, between `calendarFromDate`'s default 2026-04-01 and 2027-01-01 (the end is fixed in code), at most 2,000 instances and 40,000 days stepped. Each instance's uid is `<UID>#<YYYYMMDD>`, flagged `recurring`. Any other rule (monthly, yearly), or a rule with nothing in the window, keeps only the first instance, flagged `recurring`.
  - Events from the zip are kept only from `calendarFromDate` on, sorted by start then title.
  - Missing zip entry: error naming the prefix and listing the entries found; logged as "sorter: calendar zip unreadable", and the calendar stays empty.
- Calendar status block (in the page state): source (`google`, `ics` or `none`), Google connection fields, last error, configured calendar ids, refresh minutes, the from-date.
- Background refresh: every `calendarRefreshMinutes` (min 5, default 15; first run 2 s after start). Also reloads `episodes.json` and `roster.json` if their modified time changed (they are edited by hand while the server runs).
- `GET api/events` returns the current events; `?refresh=1` forces a refresh (including a Google sync) inside the request.

## Calendar: where does an event's footage belong (inference)
(source: infer.py, roster.py, engine.py)

- Reads hand-edited rules from `episodes.json`: `routes` (each `{when: regex, skip?, kind?, interviewees?, episode?, dest?}`), `aliases` (`{regex: episode}`), `root` (default `2026/FF5`), `episodes`, `layout`. With no `episodes.json`, there is no inference and no "misses".
- Reads `roster.json` (episode, Chinese name, English name per person). Missing or unreadable means an empty roster.
- For each event title, in order:
  1. The first route whose `when` matches (case-insensitive): `skip` drops the event; otherwise it can set the kind, the interviewee branch name, the episode, or a full destination.
  2. Else the leftmost (then longest) episode alias found in the title.
  3. A roster name found in the title: Chinese name, Chinese given name alone for 3-4 character names, full English name, and English surname-like words of 4+ letters (not "the", "and", titles such as dr/mr/prof, jr/sr/iii). Latin names must match as whole words. With an episode already known, a person in that episode is preferred. Without one, a name belonging to exactly one episode sets the episode.
  4. Else, for non-b-roll events, an existing `.../Interviewees/<Person>` folder whose first word appears in the title (longest wins).
- Kind: `broll` if the title has a b-roll hint (b-roll, event, 記者會, 遊行, 演習, 競賽, 公開賽, 課程, 活動, shooting, filming, montage) and no interview hint (interview, 訪談, 專訪); `interview` if it has an interview hint; otherwise `interview`.
- Destination built as `<root>/<episode>/<B-roll or Interviewees branch>/<subject>`:
  - Subject: the person's folder name (`中文 English`, or whichever exists) for interviews; otherwise the title stripped of the alias at either end, of trailing "interview/broll/filming" words and of leading "broll", and of leading/trailing separators.
  - Characters illegal in Windows folder names become spaces; control characters removed; spaces collapsed; trailing dots and spaces dropped.
  - A b-roll event with no subject goes to the episode's B-roll folder itself; an interview with no subject is not placed.
  - An existing sibling folder whose name equals, starts with, or is the start of the wanted name is reused (shortest wins), so `陳昭姿` lands in an existing `陳昭姿 Chen Chao-Tzu`.
- Each inference carries `via` (`route`, `prefix`, `roster`, `folder`) and a human `why` (for example `"X" is in the Y roster`, `title matches /pattern/`, `route /pattern/`, `"X" already has a folder in Y`).
- Misses (events not inferred and not bound): reason `skipped` (with the rule), `ambiguous` (a roster name in several episodes, with the name and episodes), or `unmatched`.
- The existing-folder list used here is the destination tree flattened to 6 levels.
- Roster building from the planning CSV (columns `Episode`, `Name`, optional `Name EN`; names split on newline, `;` and `、`, bracketed text removed, words like broll/個案/相關負責人/request comment ignored; only episode and names kept, never contact details): UNREACHABLE: no route, command or background task in the Python engine calls it.
- Episode skeleton listing (every `<root>/<episode>/<layout entry>` path): UNREACHABLE: nothing calls it.

## Calendar suggestions (which destination a clip probably belongs to)
(source: suggest.py, engine.py)

- An event is "bound" to a destination either by inference (above) or by a manual binding in the manifest; a manual binding overrides inference for that event.
- Only bound events produce suggestions. All clips are considered, including clips on cards in readers.
- For each clip with a recorded time:
  - **High confidence**: the clip was recorded between 1 hour before the event's start and 2 hours after its end.
  - **Low confidence**: no high match, but a bound event covers the clip's local day.
  - Among candidates: timed events beat all-day ones, then the nearest in time, then the shorter event, then the earlier one.
  - `offMin`: minutes between the clip and the event's window (0 if inside), rounded.
  - Up to 3 alternatives are attached: other events in the high window or on the same day that point to a DIFFERENT destination, one per destination, nearest first. Each carries its window (`high` or `day`) and minutes off.
- Each suggestion carries `via`: `binding` for a manually bound event, `inferred` otherwise (with the inference's `why`).
- The audio matcher (second half) adds suggestions for clips the calendar left without one.
- Days an event covers are capped at 400.
- Event times without an offset are read at +8 for suggestion purposes (not `tzOffsetHours`).

## Time folders (automatic day/time/camera sub-folders)
(source: timefolder.py, engine.py)

- Off by default (`timeFolders.enabled`). Always on for card copies to staging (see card ingest).
- A clip gets a time folder only when: time folders are on, its assignment's structure is not `preserve`, it is not a still, sequence or "other", it has a recorded time, and it has a camera label.
- Clips are grouped by destination x camera label x local day. The folder name is `YYYY-MM-DD HH.mm-HH.mm <LABEL>` (earliest to latest recorded time; a dot replaces the colon).
- Reuse rule: an existing leaf for the same day and label that already holds one of the group's clips (by the catalogue's destination paths, or by matching stem and master size among its files, not counting sub-folders) is reused under its existing name. If its range differs, the group records `mergesInto` and the warning `range widened: <fresh name> reused <existing name>`. Leaves are never renamed.
- A leaf with the fresh name that holds none of the group's clips belongs to another shoot: the new folder becomes `<name> (2)`, `(3)` and so on.
- Existing leaves are read from disk every 30 s (first after 1 s) and right after any edit that changes assignments, but only when time folders are on and `destRoot` is set. Only folders named in the leaf pattern count. Reads run 8 folders in parallel.
- The page state carries the computed leaves for every assigned clip.

## The manifest: assignments, folders, bindings
(source: engine.py, moveplan.py usage)

- Contents: `assignments` (clip id to `{dest, structure, ...}`), `plannedFolders`, `placeholderFolders`, `bindings` (event uid to dest), `dismissedEvents`. Version 2.
- Every edit is all-or-nothing: if writing `manifest.json` fails, the in-memory manifest is rolled back. Once written, a failure of the ops log or daily snapshot does not roll back.
- Every edit appends a line to `logs/manifest-ops.jsonl` with the time, user (from the host's identity header), operation and detail, and rewrites the day's snapshot.
- Destination text rules (applies to every route that takes a dest): backslashes become `/`; leading/trailing whitespace trimmed; empty segments dropped; refused if empty, if it starts with a drive letter or `//`, if any segment is only dots, if a segment is empty after trimming trailing junk, or if it contains unpaired surrogate characters.
- Spelling: each dest is re-spelled to match existing folders on disk case-insensitively (exact match preferred), and to match a planned folder that differs only in case, so `ff5/b-roll` does not create a second tree beside `FF5/B-roll` on the case-sensitive NAS.
- Assign (`POST api/assign`, body `clipIds`, `dest`, `structure`): sets each clip's assignment; `structure` is `preserve` (rebuild the source sub-folders under the destination, no time folders) or anything else meaning `convention`. Refusals: 400 "clipIds required" (missing or empty list), 400 "invalid dest", 400 "clipIds: not valid text". Non-string ids are skipped. Answers the count, the clean dest, structure, the whole manifest and the leaves.
- Unassign (`POST api/unassign`, `clipIds`): removes assignments. 400 "clipIds required". Answers count, manifest, leaves.
- Add a planned folder (`POST api/folders`, `dest`): adds to planned folders, kept sorted by UTF-16 code unit order. 400 "invalid dest".
- Add many (`POST api/folders/bulk`, `dests`, optional `placeholder: true`): adds each new one (case-insensitive duplicates skipped); with `placeholder: true` each is also marked a placeholder folder. Invalid entries are returned in `rejected`. 400 "dests[] required". Saves only when something was added or placeholder was asked.
- Remove a folder (`POST api/folders/remove`, `dest`, optional `preview`): covers the folder and everything under it.
  - Preview answers what would go: planned folders, assigned clips, bindings, whether it exists on disk, and how many files are on disk (counted up to 2,000).
  - Removes planned and placeholder entries, assignments into it, and bindings to it. Never touches disk.
  - Refusals: 400 "invalid dest"; when nothing in the manifest refers to it: 409 `"<dest>" only exists on disk. This app never deletes inside <destRoot>.` if it is on disk, else 404 "nothing here to remove".
- Move or rename a folder (`POST api/folders/move`, `from`, optional `toParent` (missing means the same parent; empty or null means the top), optional `name`):
  - Rewrites planned folders, placeholder folders, assignments and bindings under the old path to the new one. Never moves anything on disk.
  - An on-disk folder holding no files is allowed (its now-empty path is returned as `leftOnDisk`).
  - Refusals: 400 "invalid source folder"; 400 "invalid target folder"; 400 "that is not a usable folder name" (empty or contains `/`); 400 "a folder cannot be moved inside itself"; 409 `"<from>" holds N file(s) on disk. Move it with the dashboard's file move, then reload.`; 409 `"<from>" is not a folder this app can move.` (not on disk and unknown to the manifest); 409 `"<to>" already exists` (a planned folder); 409 `"<to>" already exists on disk and is not empty`.
  - Same source and target answers `unchanged: true`.
- Dismiss or restore a calendar event (`POST api/dismiss-event`, `eventUid`, `dismissed`): `dismissed: false` restores; anything else dismisses. 400 "eventUid required"; 400 "eventUid: not valid text".
- Bind an event to a destination (`POST api/bindings`, `eventUid`, `dest`): an empty or null dest removes the binding. 400 "eventUid required", 400 "invalid dest". Answers the bindings, the manifest and the freshly computed suggestions.
- Source roots (`POST api/source-roots`, `path`, optional `remove`):
  - Under the dashboard: always 403 "the source folders are set by the server's configuration, not from the page".
  - Standalone: adds or removes a full source root in `settings.json`. Surrounding quotes are stripped. Refusals: 400 "no folder given"; 400 "give the full path"; removing: 404 "not a source root", 400 "that is the only source root"; adding: 404 "no such folder: <path>", 400 "that sits inside the destination <destRoot>", 409 "already a source root", 400 "already covered by <root>", 400 "that contains the existing root <root>". Comparisons are case-insensitive.
- Card dismissal also edits the manifest (see card ingest).

## Destination tree
(source: engine.py, moveplan.py usage, web.py)

- The folders under `destRoot` (names only, 8 levels deep; skipping hidden, `$` and a skip list) are re-read every 60 s, after scans, moves and card copies. A change is detected by content signature.
- `GET api/desttree`: the tree with planned folders merged in, plus `destRoot`. Carries an ETag that changes only when the disk tree, the manifest or the settings change; an unchanged poll answers 304. With no `destRoot`, an empty tree named `destRoot`.

## Moving sorted footage (plan, dry run, execute)
(source: engine.py, web.py)

- Plan (`POST api/moves/plan`, also `POST api/export-moveplan`, optional `clipIds`): any signed-in user.
  - Refused 400 "destRoot not configured".
  - Re-reads leaves, builds the plan from every pending assignment (or only the given clips), adds leftover files of withheld clips still at their source, resolves targets, and links the plan's clips into the catalogue.
  - If any target is occupied by a different file, the plan is `blocked` with problems "destination occupied by a different file: <path>". Otherwise the mover's dry run decides `dry-run` (ok) or `blocked`.
  - Answers: plan id, entry count, folder count, total bytes, collisions, already-there, duplicates, clips that could not be found (withheld clips excluded), groups, dry-run result, time.
  - Each plan is written to `moves/<id>.json`; plans are kept in memory only, so the list is empty after a restart.
- List (`GET api/moves`): every plan made since start, newest first, without its entries. One plan: `GET api/moves/<id>` (404 "no such move plan").
- Execute (`POST api/moves/<id>/execute`): ADMIN ONLY (403 "moving footage needs an admin of this dashboard"). 404 "no such move plan"; 409 "this plan is <state>" unless the plan is in `dry-run`.
  - Runs in the background. Progress (done of total) is on the plan.
  - States: `moving`, then `done` (verified), `verify-failed`, `failed`, or `refused` (the mover's refusal).
  - If the run raises, the plan still ends `failed` with the message "the move stopped with an error (<type>: <message>). What had already moved is where the journal says it is; nothing was copied or deleted. Dry-run the plan again to carry on."
  - Afterwards always: the ledger follows every journalled move (and a clean run starts a NAS ledger scan), the journal is reconciled, the tree is re-read, and a full scan starts.

## Clips moved outside the sorter
(source: engine.py)

- After every scan and watch change, relocation (second half) re-keys and fulfils assignments for clips found moved by other means. Its counts (re-keyed, fulfilled, adopted, folder moves, gone, ambiguous) and a sentence describing them appear in the scan status as `relocated`, and changes are saved with operation `relocate`.
- When a whole destination folder is found moved, old-to-new absolute paths are recorded in `logs/journal-redirects.json`.

## The page's data: state, clips, start view
(source: engine.py, startview.py, web.py)

- `GET api/state`: everything in one answer: settings, all decorated clips, card sessions, scan time, manifest, events, inferences, suggestions, heard names and audio summary (audio matcher), roster (episode and names only), misses, scan running/count, leaves, calendar status, card-tracker status.
- `GET api/state/meta`: the same without clips. `?lean=1` additionally leaves out manifest entries, suggestions and heard names that belong to destination clips, and adds:
  - `destSummary`: destination clip count and bytes; per-destination assignment counts and bytes; assignment count; "duplicate stubs" (destination clips whose stem matches a source clip); per-day counts, bytes and cameras for a day picker; uids of timed events that have destination footage within 30 minutes of their window.
  - `heardNames`: lower-case name to number of clips it was heard on.
  - `sourceMachines`: each source root to the computer it is on.
  - `computers`: the distinct computers to offer (see below).
- `GET api/dest/summary` and `GET api/dest/detail`: the destination summary alone, and the destination clips' manifest entries and heard names (what the lean meta left out).
- `GET api/clips`: the clips alone. `?location=` limits to `staging`, `final`, `other`, `card` (comma-separated; `source` means staging, other and card). `?slim=1` drops each clip's file list and adds its master file. Slim and location views also carry, per clip, the ledger's copy count, whether a copy is at home, and flags.
- `GET api/clip/<clipId>`: one decorated clip with its files; 404 "unknown clip".
- Every clip as served gains: `location` (`staging`, `final`, `other`, or none for a card clip), `backup` label, `backupTwin`, and a thumbnail key. Card clips also gain whether a thumbnail exists yet (`th`), and `filedAt` when the same clip is already filed in the destination (matched by clip key, or by stem plus exact master size); such a card clip then shows backup `final` if it had none.
- Card index clips are never listed.
- Caching: each answer is built once per change of its inputs and served gzipped when the browser accepts gzip. Each carries an ETag (which also changes on every server restart) and an unchanged request answers 304. Answers are `no-cache` (revalidate).
- Pre-building: the lean meta, the source clips, the destination summary, the destination clips and the destination detail are built in the background 3 s after start, daily, and after every scan or watch change, so the first page load does not wait.
- Which computer a source root is on:
  1. A recorded `sourceMachines` entry (the deepest recorded parent).
  2. A root under this server's own source, staging or destination roots, or any absolute POSIX path: this server (`machineName`, default `NAS` on Linux/macOS, host name on Windows).
  3. Any other Windows drive path: `legacyMachine`, else "Unknown computer".
- Computer list: computers of source roots, this server, `settings.computers`, computers that reported cards, computers where the ledger saw a drive or watches a folder. Spellings are merged case-blind with spaces and underscores as hyphens ("Creator_1" equals "creator-1"); the first readable spelling wins; "Unknown computer" is never listed; NAS first, then alphabetical.
- `GET api/whoami`: the user name, whether admin, and `csrf: null`.
- `GET api/scan/status`: whether a scan runs, clip count (live while running), total bytes (0 while running), scan/start/finish times, error, the first 50 warnings, the last relocation result, and the folder-watch state.

## Media for the page
(source: web.py)

- Thumbnail (`GET api/thumb/<key>`, `?s=s` for the small size, else large):
  - Served from disk with an immutable one-year cache header and an ETag; files up to 256 KB are held in a 48 MB in-memory cache, larger ones streamed.
  - If not made yet, a thumbnail job is requested and the request waits up to 10 s for it.
  - 404 "unknown clip" for an unknown clip or a clip on a card (the server cannot read cards); 404 `{"status":"none","error":"no thumbnail available"}` (cached 5 minutes by the browser) when no source exists or the job did not produce one.
- Scrub strip (`GET api/strip/<key>`): the strip's geometry plus its image URL, cached 1 hour; waits up to 20 s for a strip job. 404 "unknown clip" or `{"status":"none"}`. Image: `GET api/strip/<key>/img` (404 "no strip").
- Playback (`GET`/`HEAD api/proxy/<clipId>`): streams the clip's proxy if it has a playable one, else its master, else any playable file. Playable: MP4, M4V, MOV, MKV, WebM, WAV, MP3, M4A, AAC, FLAC, OGG. Supports byte ranges (seeking), 256 KB chunks, cached 10 minutes. 404 "unknown clip" (also for card clips), 404 "no playable file for this clip", 404 "file unavailable".
- Media info (`GET api/mediainfo/<clipId>`): ffprobe of the master (30 s timeout): container, duration, bit rate, stream count; video codec, profile, size, frame rate and average frame rate, pixel format, bit depth, colour space/transfer/primaries, sample aspect, frame count; audio codec, channels, layout, sample rate, bit depth. Cached per clip in the cache folder until the master's path or size changes; errors are not cached. Errors: "ffprobe not found", "ffprobe timed out", the first line of ffprobe's error, "unreadable ffprobe output", "no data". 404 "unknown clip" (also for card clips), 404 "clip has no files".
- Reveal in Explorer (`POST api/reveal`): always 501 "there is no Explorer on the server: the path is in the info pane".

## The page's own files
(source: web.py, config.py)

- `GET /` serves `public/index.html` with every same-folder script and stylesheet URL stamped `?v=<version>`, revalidated on every visit. The version is the first 12 characters of the commit in a `DEPLOYED_COMMIT` file beside `public/` (line `commit=...`), else a digest of the names, sizes and times of the scripts and stylesheets.
- Other files under `public/` are served after all routes (no file can shadow a route). A request with `?v=` is cached immutably for a year, and scripts/stylesheets are served gzip (level 9) when accepted; other requests are `no-cache`.
- JSON answers of 8 KB or more built per request are gzipped when the browser accepts it. Ordinary JSON answers are `no-store`.

## Catalogue routes
(source: web.py, engine.py)

- `GET api/catalog/summary`: the summary above.
- `GET api/catalog?clipId=` / `?path=` / `?stem=`: matching entries (a stem search returns at most 50). 400 "give ?stem=, ?path= or ?clipId=".
- `GET api/catalog/<key>`: one entry with its backup status; 404 "not in the catalog".
- `POST api/catalog/reconcile`: apply the move journal now; answers what was applied, skipped, and the new offset.
- `POST api/catalog/audit` and `GET api/catalog/audit/status`: see the catalogue section. No admin requirement.

## Who may call what
(source: web.py)

- Under the dashboard, the user comes from the `X-Sorter-User` header and admin from `X-Sorter-Admin: 1` (with a non-empty user), which only the dashboard's gate sets. Standalone, everyone is user `local` and admin.
- Admin-only routes: move execution; ledger drive edits, drive and folder scans, adding/removing/changing watched folders, answering ledger questions, cloud backup schedule and run, ledger backup, drive copies and cancelling them. Refusal: 403 "<what> needs an admin of this dashboard" (what: moving footage, changing a drive, scanning a drive, watching a folder, removing a watched folder, changing a watched folder, scanning a folder, answering a question about footage, changing the cloud backup schedule, starting a cloud backup, backing up the ledger, copying footage, cancelling a copy).
- Every other route here, including assignments, folder edits, move planning, scans, catalogue audits and card copies, is open to any signed-in user.

## Cards in readers (card sessions)
(source: ingest.py, scan.py, engine.py)

- A computer's CC Sync companion reports the cards in its readers (through the dashboard's fleet route `POST /sorter/agent/cards`, which identifies the editor; that route is outside this part). Each report REPLACES that editor-and-computer's list of cards.
- A card in a report needs a serial and a drive; others are silently ignored.
- Accepted drive forms: a Windows drive root (`X:` or `X:\` / `X:/`) or a macOS volume `/Volumes/<name>`. Anything else is rejected for that card with "the drive must be a Windows drive root or /Volumes/<name>". (A Linux mount is never accepted.)
- Limits:
  - At most 4 computers per editor: a report from a 5th computer is refused with "at most 4 machines per editor" (the dashboard answers 413).
  - At most 16 cards per computer per report: extra cards are dropped silently.
  - At most 5,000 files per card: that card is rejected with "more than 5000 files".
- A card's listing is turned into clips with exactly the scanner's grouping and timing rules (see "Scanning"), using the first 4 KB of each XML and each WAV's length that the companion sends, but with no ffprobe (the card is not on this machine). Card clip paths are `<drive>\<path on card>` (or `<drive>/<path>` for a macOS volume), so card clip ids match the old Windows ingest.
- An unchanged card (same drive and same file names and sizes) keeps its session, including any running copy; only its last-seen time moves.
- Each card session carries: id (`<editor>~<computer>~<serial>`), editor, computer, drive, kind (default `generic`), serial, label, capacity, free space, detected time, scan time, last seen, state, error, warnings, clips, total bytes, the current plan, the current copy run, and a camera summary (up to two camera models or guesses joined by `/`, else the kind).
- Cards that disappear from a computer's report are dropped, unless a copy is running on them.
- Sessions nobody has re-reported for 30 minutes are dropped (unless a copy is running), checked every 2 s.
- Card session states: `ready`, `planned` (after a plan), `copying` (a run queued or running), `dismissed` (closed by someone). After a run ends the session returns to `ready`.
- Card list summary per card: id, drive, kind, serial, label, camera, state, listed clip count (card index clips not counted), bytes, detected/scanned time, error, warning count, computer, run progress (state, done, total, bytes done/total, plus live speed, ETA, phase, current file, copier), plan id, capacity, the fleet card name (from the card tracker, else the label), a "which card is this" guess (card tracker), and how many thumbnails are still missing.
- `GET api/ingest/sessions`: open cards, plus `closed`: cards someone closed that are still in a reader, so the page can offer them back; `warnings` is always empty.
- Close a card (`POST api/ingest/dismiss`, `sessionId`): refused 409 "a copy is running for this card" while copying; 404 "unknown session". Closing also DROPS every assignment of that card's clips (saved with operation `ingest-dismiss`).
- Restore a closed card (`POST api/ingest/restore`, `sessionId`): it returns to the state it was closed in; its clips come back unassigned. 404 "that card is not in a reader any more. Put it back in and it will be listed again."
- Rescan a card (`POST api/ingest/rescan`): does nothing but answer the card's summary (the companion relists cards itself). 404 "unknown session".
- `POST api/ingest/link-folder` and `POST api/ingest/detected`: always 501 "not here: the card is in a PC, and its CC Sync companion reads it".
- `GET api/ingest/events`: a server-sent event stream that only sends a 5-second retry hint and an idle comment every 25 s. It carries no events.

## Card thumbnails from the companion
(source: ingest.py)

- The server cannot read a card, so each report's reply lists, per card serial, every card clip still lacking a small thumbnail (up to 2,000 per card, ordered by recorded time), naming the file on the card to make it from (`rel`) and whether it is a video or an image. Audio, "other" and card index clips are never asked for.
- The companion sends thumbnails in later reports as `thumbs: [{rel, l, s}]` (large and small, base64 JPEG or WebP). Each is matched to its clip by card path (case-insensitive) and stored; undecodable ones are skipped. Up to 2,000 per card per report.
- The reply carries how many were stored (`thumbsStored`) and what is still needed (`needThumbs`); the card's row reports `thumbsMissing`.

## Card copy plans
(source: ingest.py, timefolder.py, moveplan.py usage)

- `POST api/ingest/plan` (`sessionId`, `mode`, `clipIds`, `copyProxies`). 404 "unknown session" (also for a closed card).
- Mode `stage`: copy to the staging root; any other value means `final`: copy straight to each clip's assigned destination under `destRoot`. Refused 409 "stagingRoot not configured" / "destRoot not configured".
- Which clips: the listed `clipIds`, or every clip. The card's index files are included only when every listed clip is selected (a whole-card copy).
- Proxies (and anything inside a proxy folder) are left out unless `copyProxies` is true (or, when the request does not say, `ingest.copyProxies` is true). Default: not copied.
- Final mode:
  - A clip with no assignment is not copied. If its clip is already in the destination (a catalogue destination path that exists with the same master size), it is listed under `unassignedBackedUp` with that path; otherwise under `unassigned`.
  - Assigned destinations are spelled to match folders on disk (case-insensitive), consistently within one plan.
  - Time folders apply only if `timeFolders.enabled`.
- Stage mode: time folders are always used. Clips that get no time folder go to `<detected day> <label or serial or drive or "card"> loose` in the staging root (illegal characters replaced by `_`).
- Each clip in the plan gets a state and a mode:
  - `absent` / `copy`: nothing at the target.
  - `present` / `skip`: the same clip is already at the target (identified by catalogue path or by the UMID in a neighbouring `<stem>M01.XML`) at full size, or a file of exactly the same size is there.
  - `partial` / `copy` (resumed): the same clip is there but smaller; only the difference is counted.
  - `differs` / `collision`: a different file is at the target; it will be written beside it under another name.
  - `elsewhere`: no file at the target but the catalogue has a destination copy of the same size elsewhere; not counted towards space and not copied unless explicitly selected.
  - A clip whose files would land on a name another clip in the same plan writes is turned into a collision.
  - A clip with nothing to copy (only unwanted proxies) is skipped.
- Warnings: `long path (N): <path>` for targets over 240 characters; `not enough free space on <target>: need X + Y margin, have Z` when free space is under need plus the margin (default 256 MB). The plan's `ok` is false in that case. Free space unknown counts as enough.
- The plan carries a stamp of the clips' assignments at planning time.
- Groups are reported per time folder or destination, each with its path, whether it exists, `mergesInto`, camera, day, bytes, per-state counts and clips (copy first, then collisions, then skips).
- Not done: the cross-project link offer (`linkable` is always null), a card health check (`health` always null), and thumbnail borrowing from a card's own thumbnails.

## Card copy runs (one fleet job per run)
(source: ingest.py, web.py)

- `POST api/ingest/run` (`sessionId`, `planId`, optional `copyProxies`, `unassignedAction`, `clipIds`). Any signed-in user. Refusals:
  - 503 "card copies need the CC Sync dashboard's job queue" (standalone, no host queue);
  - 503 "no pool root: destRoot and stagingRoot share no parent";
  - 409 "plan first (POST api/ingest/plan)";
  - 409 "that plan is stale: plan again" (planId given and not the current one);
  - 409 "a copy is already running for this card";
  - 409 "assignments changed since the plan was made: plan again";
  - 409 "nothing to copy: every selected clip is already there";
  - 404 "unknown session".
- A `copyProxies` value different from the plan's re-plans first (the dialog's "Back up proxies too" box).
- `unassignedAction: "stage"` with a final plan also stages the unassigned clips in the same run.
- `clipIds` selects clips within the plan; with no selection, `elsewhere` clips are left out.
- The run is submitted as ONE `card-ingest` job targeted at the reporting computer, requiring the pool mount, with verification `quick`. The job row carries only serial, label, mode, verification, file count, bytes and session; the full copy list is fetched by the companion.
- Each file copy has a write mode: `resume` for a partial clip, `collision` for a different file at the target (written beside it), else `copy`. Sequences become every file under the folder.
- `POST api/ingest/stage` (`sessionId`, `clipIds`): plan in stage mode and run it in one go.
- `POST api/ingest/cancel` (`sessionId`): asks the host to cancel the job and marks the run cancelled; answers `running: false` if nothing is running.
- `GET api/ingest/status?sessionId=`: the run's state, plan id, mode, times, groups, done/total, bytes, errors, unverified count, cancelled flag, job id, and live fields; `state: idle` with no run. `current`, `teracopy` and `health` are always null.
- Run states: `queued`, `copying`, then `done`, `error` or `cancelled`. (`verifying` is treated as running but nothing sets it.)
- Companion-facing (reached through dashboard fleet routes outside this part, only by the editor whose computer claimed the job):
  - Copy list for a claimed job: refused "that copy is already finished" once applied; "no card copy has that job id" when unknown.
  - Live progress, about every 2 s: bytes done/total, files done/total, current file (cut to 300 characters), speed, phase `copy` or `verify`, copier `teracopy` or `python`. Ignored after the run is applied. Speed, ETA (bytes left divided by speed, only while copying), phase and current file are shown only while the run is running and the last progress is under 30 s old. The page's change counter moves at most once a second for progress.
  - Receipt: lists `copied`, `skipped`, `conflicts`, `failed` (each must be a list, else "expected {copied, skipped, conflicts, failed}"). `final: false` applies what landed and keeps the run open for a retry; otherwise the run closes. A repeat receipt after closing answers `already: true`.
- How a receipt is judged (never on the companion's word alone): an entry counts only if its source is a planned file, its destination equals the planned one, the planned destination is inside the pool (symbolic links resolved), and a file of the planned size is really there. A collision copy may name a different plain file name in the same folder (no separators, `..`, colons, control characters, trailing dot or space). Each refusal becomes a run error: "<src>: not a file this copy asked for; ignored", "<src>: the receipt's destination is not the planned one; ignored", "<src>: the planned destination is outside the pool; ignored", "<src>: '<name>' is not a name this copy may be written under; ignored", "<src>: '<name>' is outside the pool; ignored", "<src>: not at <path> with N bytes; not counted"; conflicts become "left alone, a different file is at <path>"; failures "<src>: <why or failed>".
- A file once verified stays verified when a retry reports it skipped.
- Applying a receipt, per clip: a clip with a missing master or missing files is an error ("not copied" / "N of its files not copied"). Every landed clip is recorded in the catalogue as a copy from the card (with card serial, label, kind, session as its origin). Only a fully VERIFIED clip then:
  - final mode: marks its assignment fulfilled (time, job id, clip key);
  - stage mode: carries its assignment to the staged copy's new clip id (marked `carriedFrom`, and the original gets `carriedTo`), so the next scan shows it assigned and the mover will take it.
- Every verified copy that landed on the NAS is also recorded in the ledger as a trusted copy on the NAS volume (verification `quick` unless the job asked `full`, tool `card-ingest`). Ledger failures never undo a copy.
- A closed run ends `done` only if every clip was copied; otherwise `error`; `cancelled` if cancelled. A run that ended `done` with no unverified clips triggers the card-tracker hook (second half) that may mark the card backed up.
- After any receipt (final or not): leaves and tree are re-read and a full scan starts, so the copies show.
- If the host's job ends (`done`, `failed`, `abandoned`) without a receipt, the run closes as `error` (or `cancelled`) with the job's error or "the copy job <state>" / "the companion finished without a receipt", and nothing is recorded; the next scan finds whatever landed. Before the companion reports live progress, the job's own progress fraction drives the bar.

## Drive copies (one volume to another on one computer)
(source: ingest.py, web.py)

- `POST api/ledger/copy` (admin only), body `{machine?, fromVolume, toVolume, paths | folder, toRoot?}`. Volumes are ledger ids: a drive plugged into a PC (`vol:<serial>`) or the NAS.
- Refusals (400 unless stated): 503 "the ledger is not running"; 503 "drive copies need the CC Sync dashboard's job queue"; "fromVolume, toVolume and paths (or folder) are required"; "copy to a different volume"; "toRoot must be a folder path"; 503 "no pool root: destRoot and stagingRoot share no parent" (NAS end); "<vid> cannot be copied from or to: only a drive plugged into a PC, or the NAS"; "<vid> is not plugged into any machine that reports to the dashboard right now"; "the two drives are on different machines"; "a drive copy needs a drive plugged into a PC" (NAS to NAS); "<machine> does not have those drives plugged in (they are on <who>)"; "nothing to copy: every file is already on the destination (or the ledger knows no files there)".
- Add-only: files already on the destination are left out (`skippedExisting`).
- Submitted as one `drive-copy` job to the computer holding the drive, verification `quick`; requires the pool mount when the NAS is one end.
- The automatic backup (second half) uses the same path with: files already on the NAS anywhere left out, at most `limit` files (default 2,000), and the job told to copy only on the home network (home host, round-trip threshold default 15 ms).
- `GET api/ledger/copy/<job>`: state, times, done/total, bytes, errors, cancelled, volumes, computer, live fields. 404 "no drive copy has that job id".
- `POST api/ledger/copy/<job>/cancel` (admin only): asks the host to cancel a running one.
- Receipts: one at a time per run; same shape and refusal messages as card receipts; NAS destinations are checked on disk ("<rel>: not on the NAS with N bytes; not counted"). Verified files are recorded in the ledger on the destination volume (tool `drive-copy`). A final receipt closes the run `done` if every file landed, else `error` (or `cancelled`). A NAS destination triggers a rescan.
- The 40 most recent drive runs are kept; older finished ones are forgotten.
- Running copies (card and drive) appear in the ledger activity list as "Copying <card label or serial> to the NAS" and "Copying <fromVolume> to <toVolume>", with phase, bytes, files, speed, ETA, current file and start time.

## Ledger routes mounted by this web layer
(source: web.py; behaviour belongs to the ledger, second half)

- `GET api/ledger/volumes`; `PUT api/ledger/volumes/<vid>` (admin); `POST api/ledger/volumes/<vid>/scan` (admin).
- `POST api/ledger/watch` (admin; `volumeId` required, else 400 "volumeId is required"; `root`, `label`, `every_minutes`/`everyMinutes` default 60, `machine`); `DELETE api/ledger/watch/<id>` (admin); `POST api/ledger/watch/<id>/scan` (admin); `PUT api/ledger/watch/<id>/auto` (admin).
- `GET api/ledger/auto-backup`: the automatic backup's status.
- `GET api/ledger/clip/<clipId>` (404 "unknown clip"); `GET api/ledger/volume/<vid>/clips?offset=&limit=` (default 0 and 5,000; 400 "<name> must be a number"; 404 "unknown volume").
- `GET api/ledger/questions?all=1`; `POST api/ledger/questions/<id>` (admin).
- `GET api/ledger/not-home`; `GET api/ledger/activity` (ledger activity plus running copies plus cloud status).
- `POST api/ledger/backup` (admin); `PUT api/ledger/cloud/schedule` (admin); `POST api/ledger/cloud/run` (admin, answers 202).
- Ledger refusals map to: ledger not running 503 "the ledger is not running"; finished or already answered 409; unknown 404; no job queue 503; bad request 400.
- Further routes are added by the integrations module (Google calendar, card tracker, audio matcher) and the downloads module (personal downloads, folder share links): second half.

## Background tasks
(source: engine.py)

- All are off with `--no-background`. A failing run is logged and the loop continues.
- Destination tree re-read: every 60 s.
- Time-folder leaves re-read: every 30 s (first after 1 s), plus on demand after assignment edits.
- Calendar refresh: every `calendarRefreshMinutes` (min 5, default 15), first after 2 s.
- Thumbnail backfill: every 6 hours, first after 10 s (staging first, newest first).
- Automatic backup tick: every `everyMinutes` of the auto-backup settings (min 1), first after 90 s.
- Opening answers pre-built: daily, first after 3 s.
- Card ingest poll (expire stale sessions, follow job states): every 2 s, first after 2 s.
- Folder watch: every `watchSeconds` (default 20, min 5), first after 20 s.
- `clips.json` flush after watch changes: every 60 s, and on shutdown.
- Ledger: summaries warmed every 3 s; dead scan jobs swept every 60 s; cloud listing polled every 120 s; NAS pool walked daily at the ledger's `nightly` setting (default 04:30); ledger backed up daily at `backupAt` (default 04:00).
- Full scan: daily at `nightlyScanAt` (default 03:30), and once when no folder-watch map exists yet.
- Integrations add their own loops (second half).
- The ledger's "copies" summary used in clip rows is rebuilt in the background after a change; a page gets the last built one meanwhile, and the clips' ETag moves only when a summary actually changed.

## One-time migration from the Windows (Node) sorter
(source: migrate.py)

- Command: `python -m footage_sorter.migrate --from <old data folder> --to <empty staging folder> --roots '<JSON {pool path: Windows path}>' [--write] [--machine NAME]`. `--roots` may be `@file` holding the JSON.
- Without `--write`, nothing is written: it reports how many files and MB would be written, which roots were rewritten how many times, up to 12 unmapped path prefixes, and what was not carried over.
- Refusals: "--from, --to and --roots are required"; "--roots must be a JSON object"; with `--write`, "<dst> is not empty: stage into an empty folder".
- What it does:
  - Every top-level `*.json` is copied with every string (and object key) that starts with a mapped Windows root rewritten to the pool path (longest root first, case-insensitive). Paths under no mapped root (card drive letters, `C:\Users`) are left alone and counted.
  - Not copied: files starting `manifest.backup`, `moveplan`, `clips.json.bak`, `dupes-`, `server.`; non-JSON files; the `ingest` folder; old thumbnails.
  - `settings.json` loses `sourceRoots`, `destRoot`, `stagingRoot`, `ffmpegDir`, `icsZip`, `port`, `host`, and `ingest.teraCopyPath` / `ingest.historyDir`; gains `legacyMachine` = `--machine` (default this computer's name in lower case) and `sourceMachines` for every Windows-drive source root that had no mapping.
  - `catalog.json`'s journal offset is reset to 0.
  - `logs/` is copied as is, except the old mover journal is renamed `logs/move-journal.node.jsonl`.
  - `<old data>/../cache/whisper` transcripts are copied to `cache/whisper`.
- `--record-machine NAME --data <sorter-data> [--root PATH ...]`: writes only `legacyMachine` (and `sourceMachines` for each `--root`) into an already migrated `settings.json`. Refused "--record-machine needs --data".

## Behaviour kept identical to the old Node server
(source: jscompat.py, jsvalue.py, _collation.py)

- Sorting of folder names, groups and plan entries follows the old server's ICU collation for locale en-GB (ICU 78.2): whitespace before punctuation, symbols, digits, Latin, other scripts, then Chinese characters in radical-stroke order; accents outrank case; lower case before upper case. The order is a fixed generated table of 3,201 characters plus 27,584 Chinese characters; unlisted characters sort after everything listed, by code point. This decides which of two same-range shoots is called " (2)".
- Every regular expression in the rules (including the ones an operator writes in `episodes.json`) behaves as JavaScript's: ASCII-only `\d \w \s \b`, `.` stops at line breaks, `$` only at the true end. An `episodes.json` pattern that cannot be translated is skipped silently.
- Paths in stored data may be Windows (`P:\...`) or POSIX (`/pool/...`); each path is handled in its own style.
- Number printing, string length and slicing in UTF-16 units, object key order, URL encoding and ISO time printing follow JavaScript's (used by the Google calendar, card tracker and audio matcher, second half).

## Outgoing web requests
(source: netio.py)

- The engine's outgoing HTTP calls (made by the Google calendar and card tracker, second half) always send the User-Agent `footage-sorter` unless the caller sets its own (a website behind Cloudflare refused the default Python agent with 403).
- Default timeout 60 s. A 4xx or 5xx answer is returned as an answer, not raised; a network failure is raised.

## Platform differences
(source: engine.py, scan.py, startview.py, ingest.py, web.py, catalog.py)

- This server's own computer name defaults to `NAS` on Linux/macOS and to the lower-case host name on Windows.
- ffprobe: `ffprobe.exe` preferred on Windows, `ffprobe` elsewhere; no console window on Windows.
- Card drives are accepted only as Windows drive roots or macOS `/Volumes/<name>`; a Linux mount path is refused.
- Catalogue paths compare case-insensitively with either slash on every platform, although the NAS filesystem is case-sensitive; destination spellings are forced to match disk to avoid case-only twins.
- Under the dashboard (Linux container), source roots cannot be edited from the page; standalone they can.
- `Reveal in Explorer` is refused everywhere.

## Looks redundant or overlapping

- `GET api/state` duplicates `api/state/meta` plus `api/clips`; the page's start view uses the lean meta and slim clips, and the engine's own comment says no page has asked for `/api/state` since 2026-11-10. `state_body` (an older way to serve it) is not called by anything.
- `POST api/export-moveplan` is an alias of `POST api/moves/plan`.
- `GET api/ingest/events` is an event stream that never carries an event (keep-alive only).
- `POST api/ingest/rescan` does nothing but return the card summary; `link-folder` and `detected` only answer 501; `api/reveal` only answers 501.
- Status fields that are always null: `teracopy`, `health`, `current` (ingest status), `linkable`, `health` (plan clips), `csrf` (whoami); `warnings` in the sessions list is always empty.
- Card listing logic (`scan_listing`) re-implements the folder walk, image-sequence detection and Sony XML reading of the disk scanner (a second XML reader from text exists alongside the file reader).
- Three refreshes of the clip list overlap: full scan (on demand, after moves, after card copies, nightly), folder watch every 20 s, and "rescan these folders"; every card copy receipt (even a partial one) triggers a FULL scan rather than a folder rescan.
- Card-thumbnail regrouping (`regroup_card_files`) runs on load, after every scan, after every watch change and on every card report.
- Two ways a clip is considered "already backed up in the destination": the catalogue (with twin matching) and the separate "filed" index built from the current destination scan (key, or stem plus master size).
- Calendar suggestions and the audio matcher (second half) both produce destination suggestions into the same list.
- Two "which shelf" helpers (catalogue `root_of`, start view `location_of`) and many copies of "find the master file" logic.
- The daily manifest snapshot is rewritten on every save, overlapping the per-edit ops log as a recovery aid.
- Drive copies (a ledger feature) live inside the card ingest service and share its job and receipt machinery.

## Claims the code does not back

- `scan.py` module text: "The only write is the clips document, through scan_to_file()". `scan_to_file` is never called; the engine writes `clips.json` itself.
- `scan.py` module text: stat and per-clip reads run "at Node's concurrency (24 and 8)". Only one pool of 24 workers is used.
- `infer.py` module text: "Three signals, in order of trust". The code has four (the fourth is an existing Interviewees folder named in the title).
- `__init__.py`: describes "Phase 1 is the pure logic" and exports only three modules; the package is the whole server.
- `config.py` module text: card-ingest settings "are kept for the companion ... and are ignored here". `ingest.copyProxies` and `ingest.freeSpaceMarginMB` are read and used by the engine's card copy planner.
- `engine.py` `refresh_events` text: Google sync happens "in the background, never inside a request". `GET api/events?refresh=1` runs it inside the request.
- `ingest.py` module text: "the companion verifies every copy instead" of a health check. The job always asks for `quick` verification; a clip the companion did not verify is recorded but fulfils nothing.
- `engine.py` `save_manifest` text: "one snapshot a day". The day's snapshot is overwritten on every save that day.
- `roster.py`: "The roster file is gitignored" cannot be confirmed from this code, and the CSV-to-roster builder is not reachable from the Python engine.

## Could not determine

- Whether anything outside this part (the dashboard, a Node tool) still builds `roster.json` from the planning CSV, since the Python builder is never called.
- The exact Google-calendar, card-tracker, audio-matcher, downloads, relocation, mover, thumbnail and ledger behaviours that this part calls into: they are in the second half.
- Whether the `verifying` run state can ever be reached: nothing in this part sets it.
- Whether `poolRoot` is ever set by the dashboard host, or always derived from `destRoot` and `stagingRoot`.
- The full content of `_collation.py` was inspected by structure (header, how its tables are built, first and last entries), not entry by entry: it is a generated data table with no behaviour beyond sort order.
