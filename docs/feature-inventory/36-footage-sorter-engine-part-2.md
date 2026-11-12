# Footage Sorter: the engine, part 2 (the footage ledger, card tracking, audio matching, downloads, thumbnails, moves, automatic backup, audio sync)

Terms used throughout:

- **The ledger**: the sorter's record of every known copy of every tracked file, on every drive, the NAS and the cloud backup. It is a SQLite file, `<data>/ledger/ledger.db`.
- **Volume**: one place that holds copies: a drive (identified by its volume serial), the NAS pool, or the cloud backup.
- **Copy**: one file on one volume at one path, relative to that volume's root.
- **Companion**: the CC Sync tray app on an editor's computer. It reports which drives are plugged in and walks them when the ledger asks.
- **Pool**: the NAS's footage tree (`nas:thecreatorspool`).
- **Clip**: one recording as the sorter's scan sees it (a master, its proxy, sidecars).

## What the ledger counts as a copy, and when a clip is safe

(source: ledger_rules.py)

- Three roles of file are tracked; everything else is ignored by every scan and every report:
  - **master**: extensions `braw r3d ari mxf mov mp4 m4v mts m2ts avi crm dng arw cr3 nef insv`.
  - **audio**: `wav bwf aif aiff mp3 m4a flac`. Audio is audio wherever it sits, including inside a Proxy folder.
  - **proxy**: a video file (`mov mp4 m4v mxf avi mts m2ts mkv webm`) inside a folder called `Proxy` or `Proxies` (any case, any depth), or a Sony FX3 own-proxy named like `C0001S03.MP4` (digit, `S`, two digits, `.mp4`) anywhere.
  - A still or RAW clip inside a Proxy folder is not tracked. An `mkv` or `webm` outside a Proxy folder is not tracked.
- Never tracked: files with no extension or dotfiles; names starting `._` (Mac AppleDouble); names ending `.part`, `.partial`, `.interrupted`, `.failed`; names matching `.tmp.<anything>`; anything under a folder named (any case) `CacheClip`, `OptimizedMedia`, `_sorter_test`, `THMBNL`, `dupe-quarantine`, `$RECYCLE.BIN`, `System Volume Information`, `#recycle`, `.git`, `node_modules`, `__MACOSX`, `.Spotlight-V100`, `.Trashes`, `.fseventsd`, `lost+found`, `.recycle`, `@eaDir`.
- The companion is sent these same rules with every scan request (extensions, proxy folder names, the FX3 proxy pattern, the temp pattern, skip folders, skip prefixes and suffixes, time slack), and the server applies them again to every row it receives.
- Paths are stored with `/` separators, no leading or trailing slash, in Unicode NFC (a Mac's decomposed spelling and Windows' composed spelling become one path).
- Drives (volume ids starting `vol:`) compare paths without case; the NAS pool and the cloud compare with case.
- Two copies are "the same file" when they have the same file name (case-insensitive) and the same byte size, and, when both have a modified time, the times are within 3 seconds (exFAT keeps 2 s). A modified time of 0, a negative, a non-number or one beyond year ~2096 (4e12 ms) counts as unknown.
- **Volume kinds**: `nas`, `ours` (a studio drive), `client` (a client's drive), `card` (a camera card), `laptop`, `cloud`, `unknown` (the default for a newly seen drive).
- **The "backed up" verdict** for one file: backed up when it has a live copy on the NAS ("at home"), or live copies on at least two different volumes that count. Volumes that count: `ours`, `laptop`, `nas`; the cloud counts too, but only for proxies and audio, never for a master. Client drives, cards and unknown drives never count. A missing copy counts for nothing.
- **Laptop-only**: a live copy on a laptop and none on an `ours` drive or the NAS.
- **A scan that looks wrong ("bad scan")**: a listing that found under 80 % of the copies the ledger had live under the same folders, when the ledger had more than 100 there, is treated as a bad scan and marks nothing missing (a half-mounted or damaged drive).
- Folder roots for a volume: `""` means the whole volume and swallows any other root; a root inside another root is dropped; a root with `..` or a drive letter is refused with "a root must be a folder inside the volume: ...".

## Volumes (drives) and their settings

(source: ledger.py `set_volume`, `report_volumes`, `volumes_view`; HTTP mapping in web.py)

- A drive's id is `vol:` plus its volume serial with every character other than letters, digits and `-` removed, upper-cased. A drive with no usable serial is ignored.
- The NAS pool is the volume `nas:thecreatorspool`, labelled "Home NAS", kind `nas`. The cloud backup is `cloud:hetzner`, labelled "Hetzner cloud", kind `cloud`. Both are created automatically the first time they are scanned, tracked as a whole.
- Fields a person can change on a volume (PUT `/api/ledger/volumes/<id>`, admin only; refusals map to 404 unknown, 400 bad request):
  - **label**, **owner**, **notes**: text, trimmed, cut to 200 characters, empty means cleared. A non-text value is refused with "<field> must be text".
  - **kind**: one of the seven kinds, else "kind must be one of nas, ours, client, card, laptop, cloud, unknown".
  - **roots**: the folders of the drive that make up its tracked part (default the whole drive).
  - **tracked**: whether the drive is walked every time it is plugged in. Switching it on, when the drive is plugged into a reporting computer right now, queues its first scan immediately and the answer carries `scan`.
  - **autoBackup**: whether the automatic backup copies the drive to the NAS (see "Automatic backup").
  - Refusals: "a volume id is required"; "no such volume: <id>"; on a computer's system drive (the one Windows runs from), tracking is refused with "the system drive cannot be tracked as a whole: watch a folder on it instead", and auto backup with "the system drive cannot be backed up as a whole: back up a watched folder on it instead".
- A label or a kind sent by a later report never overwrites one a person set: a label is only filled when empty, and a kind only when still `unknown`.

## Volume reports from companions (who has which drive plugged in)

(source: ledger.py `report_volumes`, `_decide_scans`, `plugged`; reached through the CC Sync dashboard's `/sorter/agent/ledger/...` routes)

- A companion reports the drives plugged into its computer (serial, label, drive letter, file system, size, free space, whether it is the system drive). Limits: at most 64 volumes per report; a machine name is required ("a machine name is required"); the body must be `{volumes: [...]}` ("expected {volumes: [...]}"). Machine names are cut to 128 characters, labels to 120, drive letters to 64, file system names to 16.
- A drive seen for the first time is recorded as kind `unknown`, untracked, with its label, size, free space, when and where it was last seen. A system drive is never recorded from a report (it is never offered as a new drive).
- A known drive gets its size, free space, last seen time and computer, and system flag updated.
- **Plugged in** means: reported by some computer within the last 15 minutes (companions report every 5). When two computers report the same drive, the fresher report wins.
- The answer lists any scans the report caused, plus how many drives were known and how many were new.
- **Automatic scans decided on each report**, per reported drive:
  - A tracked, non-system drive is scanned once per plug-in when it has never been scanned, its free space differs from what it was at its last scan, or its last scan is older than `ledger.rescanHours` (default 24 hours). "Once per plug-in" is remembered while the computer keeps reporting within 15 minutes.
  - Each watched folder on the drive (see below) whose computer matches (or names no computer) is scanned when it has never been scanned or its last scan is older than its own interval. A watch of a whole system drive is never scanned.
  - Only one scan per volume at a time; a drive with a scan still going is left alone.
  - If no scan could be queued (no job queue, or the queue refused), the drive stays "not scanned this plug-in" so the next report asks again.
- A scan is queued as a dashboard job of kind `ledger-scan`, targeted at the computer the drive is plugged into, submitted as user "ledger". If submitting fails the scan is recorded as failed with the error and a warning is logged.

## Watched folders

(source: ledger.py `add_watch`, `set_watch`, `remove_watch`, `_watch_dict`; routes in web.py)

- A watched folder is one folder on one volume, scanned on its own schedule, usable on drives that are not tracked as a whole and on a computer's system drive (the only way a system drive is ever scanned).
- **Add** (POST `/api/ledger/watch`, admin): volume id (required, "volumeId is required"), folder (default the whole drive), label (cut to 120), interval in minutes (default 60, clamped to 5 minutes .. 7 days), computer (default the one the drive is plugged into now).
  - One folder at a time ("one folder at a time").
  - A volume the ledger has never recorded is accepted only when it is a system drive plugged in right now; it is created then, flagged as system. Otherwise "no such volume: <id> (a companion has to have reported it first)".
  - The whole of a system drive is refused: "the system drive can only be watched folder by folder, never as a whole".
  - The same folder on the same volume twice: "already watching <folder or 'the whole drive'> on <id>".
  - Adding a watch queues a scan of that folder at once when the drive is plugged in.
- **Switch auto backup on or off** for a watch (PUT `/api/ledger/watch/<id>/auto`, admin): only `{autoBackup}` is accepted ("nothing to change: send {autoBackup: true|false}"); unknown id "no such watch".
- **Remove** (DELETE `/api/ledger/watch/<id>`, admin): "no such watch" when unknown. The copies it found stay in the ledger.
- **Scan now** for one watch (POST `/api/ledger/watch/<id>/scan`, admin).
- A watch is shown as **visible** when its drive is plugged in, on the watch's own computer if it names one (case-insensitive).
- Each watch records when it was last scanned and how many files that scan found; a scan of the whole volume, or of a root containing the watch, updates the watch too.

## The Drives view

(source: ledger.py `volumes_view`, `_volume_stats`; GET `/api/ledger/volumes`)

- Lists every volume ordered by label (or id) without case, each with: id, label, kind, owner, notes, tracked, system, roots, size, free space, last seen time and computer, last scan time and file count, when it was first recorded, auto backup switch; per role (master, proxy, audio) the number of live files and their bytes; the number of missing copies; the number of open questions; where it is plugged in now (computer, drive letter, seen at); and the scan going on now (status, job id, started at).
- **New drives** are listed separately as "untracked": a drive that is kind `unknown`, untracked, not watched, has been seen, has never been scanned, has no files, is a `vol:` drive and is not a system drive. Each shows its label, size, free space, computer, drive letter, file system and whether it is plugged in now.
- The watch list is included with each watch's visibility.
- The per-volume totals are worked out once per change to the ledger and reused until the next change.

## Scanning: on demand, and the companion's scan protocol

(source: ledger.py `scan_now`, `scan_manifest`, `scan_chunk`, `scan_progress`, `scan_finish`, `_active_scan`, `sweep`; companion routes live in the CC Sync dashboard)

- **Scan now** on a volume (POST `/api/ledger/volumes/<id>/scan`, admin):
  - The NAS: starts the NAS pool walk (below).
  - The cloud: re-reads the cloud listing even if its snapshot has not changed.
  - A drive: must be plugged in now, else "that drive is not plugged into any machine that reports to the dashboard right now". A system drive is scanned only through its watched folders, else "the system drive is only scanned through its watched folders". A tracked drive scans its roots plus every watched folder. An untracked drive scans only its watched folders, or the whole drive when it has none.
  - A scan already going returns its job id with `already: true`.
  - No job queue: HTTP 503 "the dashboard's job queue is not available".
- **The scan request a companion fetches** (the "manifest"): every time the job is claimed the scan starts over: anything an earlier attempt sent is discarded and a new attempt number is issued, which every later call must echo. It carries the volume id, serial, the folders to walk (on a drive, each folder spelled the way the ledger already spells it), the rules, a suggested 5,000 rows per chunk, and whether the volume is known. A finished scan refuses with "that scan is already finished" (HTTP 409).
- **Chunks of the listing**: each is a sequence number (a non-negative integer, else "seq must be a non-negative integer") and up to 10,000 rows of `[path, size, modified ms]` ("at most 10000 rows per chunk"; not a list: "rows must be a list of [path, size, mtimeMs]").
  - A row whose path is unusable (not text, over 2,048 characters, a NUL, undecodable text, a drive letter, a `..`) or whose size is missing or negative is skipped and counted, never fatal for the whole drive.
  - A row of a file type the ledger does not track, or outside the scan's folders, is dropped silently.
  - On a drive, a path inside a scan folder is respelled to the ledger's spelling of that folder.
  - The same chunk number sent twice is accepted once and answered `duplicate: true`.
  - A chunk from an attempt that a newer claim replaced is refused: "this attempt of the scan was replaced by a newer claim of the job: stop" (409).
- **Progress**: files done, bytes seen, speed, current path (cut to 300 characters). Progress for a finished scan is ignored. It is what the activity panel shows (below).
- **Finish**: declared file count and bytes, whether the walk was complete, and up to 5,000 folders that could not be read. A finish repeated after the first one is answered with the stored result and `already: true`.
- **Dead scans are closed**: a scan whose job the queue reports as ended (done, failed, abandoned, cancelled, error) without a finish, or, when the queue cannot say, a queued scan nobody claimed for 3 hours or a running scan silent for 30 minutes, is marked failed ("the job ended without a finish") and its partial listing is discarded. Checked whenever a volume's activity is looked at and by a sweep every 60 seconds.

## What a finished scan changes (the delta)

(source: ledger.py `_finish_scan`, `_apply_delta`, `_ask_about`; also used by the NAS walk and the cloud listing)

- All of it is applied in one step; a page never sees half a scan.
- **Status of the scan**:
  - `partial`: the walk said it was not complete; or (companion scans) it did not say how many files it sent, or a chunk number is missing; or fewer rows arrived than it declared.
  - `bad-scan`: the 80 % rule above.
  - `ok`: otherwise. Only an `ok` scan marks anything missing and updates the volume's "last scanned" time, file count and free space (and its covered watches).
- **New file at a new path**: recorded as a copy, verification level `listed`, with the tool and computer that found it.
- **Same path, different size, or modified time more than 3 s apart**: the old copy is retired and points to the new one (replaced in place).
- **A copy that was missing seen again at its path with the same size and time**: live again.
- **Not found any more** (only for `ok` scans, only for copies under the scanned folders, only for copies that existed when the scan began, never for folders the walk reported unreadable or left out on purpose; an unreadable root exempts the whole volume):
  - If another live copy with the same name, size and time exists on the same volume, the file was moved or replaced within the drive: the old copy is linked to it silently.
  - Otherwise the copy is marked missing since now, and one **question** is opened per folder ("where did these go?"), with the number of files and bytes. If one volume (not the cloud, not a card) holds a twin of every missing file of that folder, it is the suggested answer (the alphabetically first if several do). An open question for the same folder grows rather than a second one opening.
  - Cards and the cloud never open questions (a card is formatted on purpose; a cloud copy ages out with the backup's retention).
- After new or replaced files: open questions on that volume (unanswered, or answered "plug it in and rescan") try to link their missing files to live twins on the same volume; a question with nothing left missing closes with answer `within`, by `scan`. A pending answer "moved to X" is settled once X's copies are known.
- After new or returned files: a question whose files have all turned up again closes itself with answer `found again`, by `scan`.
- The scan's result: status, files, added, replaced, missing, back, the questions it opened, and how many folders were exempt.

## Questions about missing footage

(source: ledger.py `questions`, `answer_question`; GET `/api/ledger/questions`, POST `/api/ledger/questions/<id>`)

- The list: open questions (or every question with `?all=1`), largest first by bytes, at most 500. Each shows volume and label, folder, files, bytes, suggested volume and label, opened at, answer, answered at and by.
- Answers (admin only):
  - **`moved:<volume>`**: the files went to that volume. Each missing file is linked to a live twin there. If some have no twin yet (the target has not been scanned), the question stays open with that answer and settles itself when the target's copies arrive; the reply says how many were linked and how many wait. The target must be a known volume ("moved: the volume must be a known volume id").
  - **`within`**: moved or renamed inside the same volume. Each missing file is linked to a twin at the same path or with the same name, size and time elsewhere on the volume; closes only when none are left.
  - **`deleted`**: every missing file of the folder is marked deleted; the question closes.
  - **`pending-scan`** ("plug it in and rescan"): recorded, the question stays open.
  - Anything else: "answer must be 'moved:<volume>', 'within', 'deleted' or 'pending-scan'". Unknown id: "unknown question" (404). Already answered: "already answered: <answer>" (409).

## Copies reported by fleet tools and by the server's own recorders

(source: ledger.py `record_copies`, `record_trusted`, `_record_one`)

- **From a companion** (a field outbox, a copy receipt): at most 5,000 copies per call. A volume can only be named by `{serial, label}`; an `id` or `kind` it sends is ignored, so a USB stick cannot call itself the NAS. Each copy carries path, size, modified time, verification level (`listed`, `quick` or `full`; anything else becomes `quick`), when (an unparseable time becomes now) and tool (cut to 60 characters). The recorder is `<editor>/<machine>` (cut to 160).
  - Same file already live at the path: a duplicate; a higher verification level upgrades the stored one, and an unknown modified time is filled in.
  - A different file (another size) already live at that path: counted as a **conflict** and left alone; the existing copy is never retired on a fleet caller's say-so.
  - A missing copy at that path with the same size and time: brought back live.
  - Otherwise: recorded as new.
  - The reply: accepted, duplicates, skipped (unusable rows), conflicts.
- **From the server's own recorders** (card copies and drive copies it has checked on disk): explicit volume ids and kinds are allowed, and a changed file at a known path retires the old copy in favour of the new one.
- Both settle pending "moved to" answers and close questions whose files are back.

## The mirror (a companion's local copy of the ledger)

(source: ledger.py `mirror`; reached through the dashboard's `/sorter/agent/ledger/mirror`)

- Returns changed copies of the requested volumes (up to 200; default every volume) after a cursor `seq:id` (or a plain number), in change order, `limit` 1 to 20,000 (default 5,000), with `more` when another page waits, the next cursor, and each volume's id, label and kind. Each row: id, lower-case name, size, modified time, volume, path, role, verification, missing flag, gone flag (moved or deleted).
- A cursor that is not `seq:id` or a number: "since must be a cursor from an earlier answer (seq:id) or a number".

## Moves keep the ledger right

(source: ledger.py `apply_moves`; called by the engine after the mover runs)

- After the mover carries out a plan on the NAS, every entry the move journal says is done is applied to the ledger: the old copy is marked missing with "moved to" its new copy, and no question is opened. A folder entry moves every live copy beneath it. If a live copy already exists at the new path, the old one simply points to it.
- After a move run that finished cleanly, a NAS pool scan is started to catch anything the journal could not name.
- A failure in this follow-up is logged and never fails the move.

## Each clip's copies, and the badges on the clip grid

(source: ledger.py `clip_copies`, `clip_verdict`, `_summary_of`, `batch_summaries`, `clips_with_copy_on`; GET `/api/ledger/clip/<id>`, GET `/api/ledger/volume/<id>/clips`)

- **One clip's copies**: every copy (live or missing, not deleted, not moved) of each of the clip's tracked files, grouped by role, each with volume, label, kind, path, verification, when recorded, missing and since when, whether its volume is plugged in now and on which computer, and, for a missing copy, the open question about its folder.
- **The clip's summary**: number of master, proxy and audio copies, the volumes it is on, backed up, laptop-only, not at home, at home, and "cloud proxy" (the clip has a proxy and every proxy has a cloud copy).
- A clip of several master files (a split recording) is judged file by file and the answers are combined: backed up only if every file is; at home only if every file is; laptop-only if any file is; the copy count is the fewest places any file is in; card-only when every file's every live copy is on a card or client drive. A clip with no tracked master is judged by its audio.
- **Badges for every clip** (worked out in one pass and reused until the clips or the ledger change): copy count, at home, and flags: laptop-only, not backed up, not at home, every proxy in the cloud, card-only, has a proxy not all in the cloud.
- **Clips with a copy on a volume**: clip ids sorted, paged by `offset` and `limit` (1 to 50,000, default 5,000); unknown volume 404 "unknown volume".

## Planning a drive copy

(source: ledger.py `plan_copy`; used by the drive copy feature in ingest.py and by the automatic backup)

- Given a source volume, a list of files or folders on it, a destination volume and a destination folder: each live file under each path lands at `<destination folder>/<name of the path>/<rest of its path>`.
- A file the destination already holds at that exact path and size is skipped and counted.
- Optional "skip what is home": every file with a live copy anywhere on the NAS is left out and counted (the automatic backup uses this).
- Optional limit: stop at that many files and say `more` instead of refusing.
- Refusals: an unknown volume "no such volume: <id>"; a destination folder with `..` or a drive letter "toRoot must be a folder inside the destination volume"; two sources landing on one destination "<a> and <b> would both land at <dst>: copy them one at a time, or into different folders"; over 20,000 files (without a limit) "more than 20000 files: copy a smaller folder".

## "Not at home": what is not on the NAS

(source: ledger.py `not_home`, `_digest`; GET `/api/ledger/not-home`)

- Every master and audio file with live copies but none on the NAS, grouped by category, by the folder it sits in (the last folder name), and by where it is (volume labels joined by " + ").
- Categories, in this order: `laptop-only` (on a laptop, none on our drives), `ours` (on at least one of our drives), `not ours` (only on client drives, cards or unknown drives). Within each, biggest first.
- The answer: total bytes, file count, the groups (category, folder, where, files, bytes, volumes), the open questions, and a plain-text digest:
  - "Not at home: <size> in <n> folder(s)."
  - "Only on a laptop - <size>:", "On drives we own, not at home - <size>:", "Only on drives that are not ours (client drives, cards) - <size>:", each followed by lines "  <folder>  (<size>, <n> files)  on <where>".
  - "Where did these go? <n> folder(s) no longer where they were:" with lines "  <folder> on <volume> (<n> files, <size>) - probably <suggested volume>".
  - Sizes: TB with one decimal from 1 TB; GB with no decimals from 10 GB, else one decimal.
- Worked out once per change to the ledger.

## The activity panel

(source: ledger.py `activity`; GET `/api/ledger/activity`, which the engine extends with running card and drive copies and the cloud status)

- Lists every running scan:
  - NAS walk: "Scanning <label>", files and bytes so far, files per second, current folder.
  - Cloud listing: "Reading the <label> listing", files so far, the snapshot id.
  - Companion scan: "Scanning <label> on <computer>", shown as walking once rows arrive or progress came in the last 2 minutes, else queued; live files, bytes, speed and current path when fresh, else the rows received.
- Lists each queued companion scan: "Scan of <label> waiting for <computer>".
- Includes the last ledger backup's status and the last NAS walk's outcome (time, status, error count, up to 20 unreadable folders, files).
- Includes a version number that moves with every change, so a page knows to refresh.

## Backing up the ledger itself

(source: ledger.py `backup`, `_backup_state`, `_prune_backups`, `backup_status`; ledger_sources.py `backup_out`, `share`)

- Runs every day at `ledger.backupAt` (default 04:00, on the NAS's clock) and when an admin presses back up now (POST `/api/ledger/backup`).
- Writes a consistent snapshot of the ledger database (never a raw file copy) as `ledger-YYYY-MM-DD.db`, checks it with SQLite's integrity check, and deletes it and reports the error if the check fails.
- Also copies the sorter's own data folder (every file except `.tmp` files and the folders `cache`, `thumbs`, `thumbnails`, `strips`, `ledger`, and the backup folders themselves) to `state-YYYY-MM-DD/`, each file written to a temporary name then renamed. A file that cannot be copied (rewritten mid-copy) is skipped with a warning.
- Where: `<backupOut>/snapshots` when a backup folder is configured and exists (it is the folder the NAS's own upload carries to the cloud), else `<data>/ledger/backup`.
- Keeps the newest 7 snapshots and 7 state folders; older ones are deleted.
- Folders it makes are set to mode 2770 and files to 660 (group-writable, so the NAS's upload script, running as another user, can read and manage them). A failure to set them is ignored.
- The last result (time, file, bytes, ok, error, state file count) is kept and shown in the activity and cloud status.

## The NAS pool walk

(source: ledger_sources.py `start_nas_scan`, `scan_nas`, `_nas_walk`)

- Triggers: every night at `ledger.nightly` (default 04:30, NAS clock); after every clean move run; "Scan now" on the NAS volume.
- One at a time: a second start while one runs answers `started: false, running: true`.
- Refusals: "no pool root is configured: the NAS cannot be scanned from here"; "the pool is not mounted here (<root>)"; "the pool cannot be read: <error>". The nightly run logs these and does nothing (a standalone sorter has no pool).
- Walks the whole pool without following links, skipping the skip folders and every folder listed in `ledger.nasExclude` (pool-relative, case-insensitive). File names are read in NFC.
- Folders that could not be read, and folders left out on purpose, are exempt from "missing": their copies are not judged, the rest of the pool still is.
- Records the pool's total and free space.
- Progress (files, bytes, files per second, current folder) is updated once a second. The walk stops if the sorter is shutting down.
- Outcome kept for the activity panel: status, error count, up to 20 unreadable folders, files.

## The cloud backup: its listing, its status, its schedule

(source: ledger_sources.py `cloud_poll`, `_cloud_import`, `cloud_status`, `_cloud_progress`, `cloud_schedule`, `set_cloud_schedule`, `cloud_run_now`, `cloud_next_run`, `local_now`)

- The cloud copy is made by a script on the NAS (restic) that the sorter does not run. The sorter only reads what it writes and leaves it requests.
- **Reading the listing**: every 120 seconds, the sorter looks at `<cloudState>/snapshot-ls.jsonl.gz`. When its first line names a snapshot it has not read yet, every file under the pool prefix (`ledger.cloudPoolPrefix`, default `/mnt/tank/TheCreatorsPool/`) of a tracked type becomes the cloud volume's listing, applied like any scan. The snapshot id, time and file count are remembered. Quiet skips: no state folder, no listing yet, unreadable listing, first line not a snapshot, unchanged, already reading.
- Forcing a re-read ("Scan now" on the cloud volume) needs a state folder: "no cloud state folder is configured (cloudState)".
- **Status** (shown with the activity): whether configured; `LAST_STATUS` (`RUNNING`, `OK` or `FAIL`, with its time and text); `last-run.json` (reason, start, finish, exit code); `progress.json` (percent, bytes done and total, files done and total, speed averaged over the last two minutes, time left, current file, errors, elapsed, updated at, and "fresh" when updated in the last 30 s); `last-summary.json` (snapshot id, new, changed and unchanged files, data added, totals, duration, when); the snapshot the ledger last read; the schedule and next run time; whether a run is requested and when; whether a backup folder is configured; the retention (`ledger.cloudRetention`, default 24 hourly, 30 daily, 12 weekly, 24 monthly); the ledger backup status. "Running" is `RUNNING` or a fresh progress file. A field for box usage is always empty.
- **Schedule** (PUT `/api/ledger/cloud/schedule`, admin): `{enabled, nightlyAt}`, written to `<backupOut>/control/schedule.json` with who and when. Default when the file is absent or malformed: on, 04:15. Refusals: "expected {enabled, nightlyAt}", "enabled must be true or false", "nightlyAt must be HH:MM (24 hours)"; with no backup folder configured "no backup folder is configured (backupOut): the sorter cannot tell the NAS when to upload" (503); with the folder not mounted "the backup folder is not mounted here" (503).
- **Run now** (POST `/api/ledger/cloud/run`, admin, answers 202): writes `<backupOut>/control/run-now` with who and when; the answer says it starts within "10 minutes". Refused (409) with "a cloud backup is running already" or "a run was already requested; the NAS starts it within 10 minutes".
- **Next run** shown: none when off; today at the set time if not yet passed; "now" (the script's next 10-minute tick) if passed and today's marker file `.nightly-YYYY-MM-DD` is absent; tomorrow if today's marker exists.
- **The NAS's clock**: the time zone is `ledger.timezone`, else the host's `timezone` setting, else `SORTER_TZ`, else `TZ`, else the process's local time. An unknown zone name falls back to local time.

## Ledger settings, environment variables and background cadence

(source: ledger.py, ledger_sources.py, and the loops the engine starts for them)

- Settings under `ledger` in the sorter's settings: `rescanHours` (24), `nasExclude` (none), `cloudPoolPrefix` (`/mnt/tank/TheCreatorsPool`), `cloudRetention` (24/30/12/24), `timezone`, `nightly` (04:30, NAS walk), `backupAt` (04:00, ledger backup).
- Host settings: `backupOut` or `backup_out` (else env `SORTER_BACKUP_OUT`): the folder the NAS's upload carries; `cloudState` or `cloud_state` (else env `SORTER_CLOUD_STATE` or `CLOUD_STATE`): where the upload script writes its status; `timezone`.
- Background: every 3 seconds the sorter checks whether another process (the import tool) changed the ledger and refreshes the clip badges; every 60 seconds it closes dead scans; every 120 seconds it looks for a new cloud listing; nightly NAS walk; daily ledger backup.

## Importing the October ledger (command-line tool)

(source: ledger_import.py)

- `python -m footage_sorter.ledger_import --token-file <file> --data <sorter data folder> [--from-worker <url>] [--write] [--limit N] [--max-pages N] [--creators-club-tops Projects,Assets] [--prefix VOLUME=PREFIX ...] [--no-questions]`.
- Reads the old Cloudflare Worker ledger's change feed (`GET <url>/api/changes?since=<seq:id>&limit=`), page by page from the start, and its open questions (`GET <url>/api/questions`), with a bearer token. The token file is JSON `{url, token}` (a BOM is tolerated); `--from-worker` overrides its url; `/api` is appended if missing. User agent "footage-sorter-ledger-import/1". Timeout 60 s per page.
- `--limit` rows per page (default and maximum 5,000), `--max-pages` (default 200; exceeding it stops with "more than <n> pages: something is wrong (or raise --max-pages)"). A page whose cursor does not move ends the read.
- Without `--write` it is a **dry run**: it imports into a throwaway copy of the ledger and prints what a real run would do; the real ledger is never touched.
- With `--write` it imports into `<data>/ledger/ledger.db` and then takes a ledger backup.
- Path conversion: backslashes become `/`; on a NAS volume a path whose first folder is one of `--creators-club-tops` (default `Projects`, `Assets`) gets `Creators_Club/` in front; `--prefix VOLUME=PREFIX` puts every path of a volume under a folder ("--prefix wants VOLUME=PREFIX, got ..." on a bad value, exit 2). A missing token or url exits 2 with "the token file needs a token (and a url, unless --from-worker is given)". An HTTP error stops with "the Worker answered <code> for <url>".
- Re-running changes nothing: rows are keyed on their old id; only rows the old ledger changed since the last import are applied, and never over what the sorter has decided since (a copy a scan found gone, an answer "deleted", a replaced file stay as they are). Where the old ledger had two live rows at one path, the later is live. A row the sorter recorded itself at a path is never displaced by an imported one; the imported one is stored as the older copy. Old volumes are created (NAS volumes tracked); old questions are added once.
- Prints a JSON summary: pages, rows read, volumes read, questions read, rows per volume, inserted, updated, unchanged, skipped, links resolved, backup result.
- The running server notices the change within seconds (the 3-second check above).

## Automatic backup of drives and laptops to the NAS

(source: autobackup.py; the switches are on volumes and watches in ledger.py; the copy itself is the drive copy feature in ingest.py)

- **What it does**: every `autoBackup.everyMinutes` (default 10; first look 90 seconds after start), for each drive with auto backup on (never a system drive) and each watched folder with auto backup on, when it is plugged into a computer that reports to the dashboard, it starts ONE drive copy job of the files under it that have no copy anywhere on the NAS, at most `autoBackup.maxFiles` (default 2,000) per job.
- **Where the files go**: `<stagingRoot>/<autoBackup.folder>/<computer>/<drive label>/<the same path as on the drive>` on the NAS. Default folder name "Auto backup". The computer is the machine name the companion reports (the editor prefix dropped). The label is the drive's label, else its watch label, else its serial. Each name part has `\ / : * ? " < > |` and control characters turned into `-`, leading and trailing spaces, dots and dashes trimmed, cut to 80 characters, and becomes "drive" if empty. The staging folder must be inside the pool.
- For a whole drive, the copy is given the drive's top-level folders and files (taken from the ledger), so they land where the whole drive would have.
- **Away from home**: the job carries `autoBackup.homeHost` (default none) and `autoBackup.rttMs` (default 15) so the companion copies only on the home network; a job that ends saying the computer is "away from home" is shown as "waiting: this computer is away from home".
- After a failed or away-from-home attempt, that source is not tried again for `autoBackup.retryMinutes` (default 60).
- A watched folder whose drive letter is plugged into a different computer than the watch names counts as not plugged in.
- `autoBackup.enabled` (default on) switches the whole loop off. It also does nothing when the ledger is not running.
- **Status per source** (GET `/api/ledger/auto-backup`, keyed `vol:<id>` or `watch:<id>`), one of:
  - `copying` (job id, files, bytes, more, destination folder, computer; also while the job is queued, copying or verifying);
  - `done` (files, bytes, finished at);
  - `away` ("waiting: this computer is away from home");
  - `error` with a message: "no staging folder on the pool to copy into", the drive copy's refusal, or "the copy ended <state>" / the copy's error messages;
  - `nothing to copy`;
  - `not plugged in`.
- Nothing is deleted or overwritten; a drive copy only adds. The status lives in memory and is lost on restart.

## The crew's card tracker

(source: cardtracker.py, integrations.py `_attach_cards`, `_set_serial`, `cards_report`, `routes`)

- **What it is**: shooters record on their phones which camera cards they used on which day, on a public site (default `https://thecreatorsclub.co/cards`). The sorter pulls that record down, keeps a copy so the Cards tab works offline, lays it against the calendar and the catalog, and tells the site when a card's footage is backed up.
- **Files**: `<data>/card-usage.json` (the offline copy), `<data>/cards-token.json` (`{token}`); env `FS_CARDS_TOKEN` overrides the token file. The token is never logged.
- **Settings** (`cards` in settings): `url` (default above, trailing slashes dropped), `syncMinutes` (default 15, at least 1), `serials` (volume serial to card name, both upper-cased, e.g. `SD-2`), `capacities` (card name to bytes). `calendarFromDate` (default 2026-04-01) sets how far back usage is fetched and compared.
- **Sync**: in the background every `syncMinutes` (first 5 seconds after start) when a url and token exist. Fetches the card list (`GET <url>/api/state`, no token) and the usage (`GET <url>/api/usage?since=<date>&limit=5000`, with the token); 20-second timeout. Without a token the card list still updates and the days do not. Skipped when the last sync is younger than `syncMinutes` unless forced. Only one sync runs at a time; others wait for its answer. Offline, the last copy stands and the error is kept for the status.
- **Errors**: "settings.cards.url is empty"; "no card-tracker token (data/cards-token.json or FS_CARDS_TOKEN)"; "card tracker: <the site's error or HTTP status>". A 401 is "unauthorised" (HTTP 401 to the page), a 503 is "not configured" (503), anything else 502.
- **Marking cards backed up or used on the site** (`POST <url>/api/backup` with the token, body cards, backedUp, by): the local copy takes the site's answer.
- **Automatic "backed up" flip**: when a card copy run on the sorter finishes, the card is marked backed up on the site only if the tracker is configured, the card's serial is named in `serials`, and every clip on it has a backup copy in the catalog. Outcomes logged: "cards: serial <serial> (<camera>) is not mapped to a card label - map it in the Cards tab and it flips by itself next time"; "cards: <card> (<serial>) stays marked used: <n> of <m> clips have no copy yet"; a failed request is logged. The flip is recorded by "sorter:<session id>".
- **Which card is this?** For a card in a reader whose serial nobody has named (a camera gives a card a new random serial on every format, and the USB readers report their own serial), the sorter lists candidates from the active fleet: only the card family the camera uses (BRAW cameras: CF; Sony: SD; drone and audio: either), never a card already named for another card in a reader (scanning, ready, planned, copying, done), never a card whose recorded size differs by more than 2 % from this card's. Score: +2 if the crew recorded using it on a day this footage was shot ("used <days>"), +1 if marked used ("marked used"), "same size" noted. A single suggestion is made only when the top card scores at least 2 and no other card ties it. A named card's session still gets the list (so a person can say "that is not SD-2"). No list while the card is still being read or when the fleet list is empty.
- **Naming a serial** (POST `/api/cards/serial`, admin): serial 2 to 40 of `A-Z 0-9 _ -` ("serial required"); card like `SD-1` (1 to 4 letters, dash, 1 to 3 digits; "card must look like \"SD-1\"") or empty to unname. Written into `settings.json` (an environment override never lands on disk), along with the card's size from the session carrying that serial. Every session with that serial is then re-checked for the automatic flip.
- **Marking by hand** (POST `/api/cards/backup`, admin): `{cards: [...]}` or `{card}` plus `backedUp: true|false` ("cards required", "backedUp must be true or false"); recorded by "sorter:manual".
- **The Cards tab's report** (GET `/api/cards`, `?refresh=1` forces a sync; POST `/api/cards/sync` always syncs; any caller who can reach the sorter may use these two). The answer always comes from the last copy even if the sync failed (`syncError`), and contains:
  - status: url, configured, has token, synced at, last error, card and usage counts, sync minutes, serial map;
  - cards in fleet order (kind, CF before SD, then number, then id): backed up, active, updated at and by, last used, serials named for it;
  - one row per usage day, newest first: the cards used (who recorded, when, backed up, and the footage that came off that card that day per the catalog: clips, folders it landed in, how many copies in staging and in the final tree), the calendar events of that day (dismissed events left out) with the destination the sorter knows for each (from a binding or inference) and why, ranked: shoots with a destination, then timed events, then all-day events, then recurring all-day events; a "likely" event (strong when exactly one event has a destination, weak when none has one and exactly one timed event exists); the folders the footage landed in. Time-folder leaves (`YYYY-MM-DD HH.MM-HH.MM <camera>`) and `Proxy` are folded into their parent folder. Footage before `calendarFromDate` is not compared. Multi-day events cover each local day they touch (at most 60), an all-day end being exclusive; the default time zone offset is +8.
  - footage that came off a named card on a day nobody recorded (newest first);
  - serials seen in the catalog that are not named: label, kind, clips, last seen, the last 4 days, and a hint (CF for BRAW, SD for Sony), most recently seen first.
- Every Cards route bumps the page's "cards" version.

## Google Calendar

(source: google.py, integrations.py `GoogleBinding`, `_attach_google`, `_redirect_uri`, `routes`)

- **Files**: `<data>/google-oauth.json` (the OAuth client file exactly as Google Cloud hands it out, `installed` or `web` form), `<data>/google-token.json`, `<data>/calendar.json` (the synced events). Written as UTF-8 without a byte-order mark through a temporary file and rename (retried up to 40 times on Windows when the target is momentarily held). Tokens are never logged.
- **Access asked for**: read-only calendar access, offline (a refresh token), with consent always prompted.
- **Connect** (GET `/api/google/auth`, admin): redirects to Google's consent page. Without a usable OAuth file: HTTP 400 "data/google-oauth.json missing or incomplete" plus setup help (create a Desktop OAuth client in Google Cloud Console, save the JSON as that file, enable the Calendar API).
- **Where Google sends the browser back**: `<publicUrl>/sorter/api/google/callback` when the host gives a public URL (under the dashboard), else `http://127.0.0.1:<settings.port, default 8787>/api/google/callback`.
- **Callback** (GET `/api/google/callback`, no admin check; always an HTML page, with what it prints escaped):
  - Google reported an error: 400 "Not connected", "Google said: <error>".
  - The sign-in link is unknown or older than 10 minutes: 400 "The sign-in link had expired or was not started from this app. Try again from the sorter."
  - Success: "Connected to Google Calendar", "Signed in as <account>." (or "Signed in."), "You can close this tab. The sorter is already syncing." A calendar sync starts in the background.
  - A failed code exchange: 500 with the error.
  - After connecting, the account name is looked up from the primary calendar (best effort).
- **Token refresh**: one minute before expiry; only one refresh at a time. Google refusing the refresh token (401, or 400 `invalid_grant`) marks the connection revoked: "Google access was revoked or expired: <reason>". Any 401 from the Calendar API also marks it revoked.
- **Disconnect** (POST `/api/google/disconnect`, admin): deletes the token file (a refresh in flight cannot bring it back), clears the sync state and the calendar error, bumps the events version.
- **Status** (GET `/api/google/status`): where the calendar comes from (`google` when connected, else `ics` when an `icsZip` setting exists, else `none`), configured, connected, revoked, account, last sync, last error, event count, chosen calendar ids, refresh minutes (default 15), from date.
- **Calendars** (GET `/api/google/calendars`): id, name, primary, access role, colour, and which are selected. Not connected or revoked: 401; other failures 502.
- **Sync** (POST `/api/google/sync`, no admin check): fetches now and answers with the event count and status; a failure is HTTP 500.
- **Automatic sync**: the engine's calendar loop (every `calendarRefreshMinutes`, at least 5, default 15) fetches from Google when connected and `calendar.json` is not Google's, has no stamp, or is older than the refresh period.
- **What is fetched**: each chosen calendar (`googleCalendarIds`, default `primary`), single events in start order, from `calendarFromDate` (default 2026-04-01) local midnight to `calendarToDate` (default one year later), 2,500 per page, at most 50 pages per calendar. Cancelled or undated events are dropped. All-day events run from local midnight to the exclusive end day's midnight. A recurring event's occurrence gets an id with `#YYYYMMDD` appended and is flagged recurring. Times are written with a fixed offset (`tzOffsetHours`, default +8, no daylight saving). Events are sorted by start, then title.
- **Settings editable from the page** (POST `/api/settings`, admin): only `googleCalendarIds` (a list of strings under 300 characters), `calendarRefreshMinutes` (5 to 1,440), `calendarFromDate` (`YYYY-MM-DD`). Anything else is listed as rejected; nothing valid: 400 "nothing to change".

## "Whose interview is on this recording?" (the audio matcher)

(source: audio_match.py, integrations.py `AudioBinding`, `routes`)

- **Purpose**: field-recorder WAVs often carry a wrong date (the recorder's clock was reset), so the calendar cannot place them. This weighs every signal about who is talking and proposes a destination folder. It never assigns anything itself.
- **Inputs**: `<data>/whisper-names.json` (what an external transcriber heard per clip: roster names and spoken introductions), `<cache>/whisper/<clip id>.json` (one transcript per clip, in windows), the Vault folder (`settings.vaultRoot`, default `X:\Vault\2026\FF5`) whose `<episode>/Interviewees/<name>/*_Transcript.md` files are the reference interview transcripts (front matter, block references and the interviewer's `# ` prefix removed), the scanned clips, the assignments, the destination tree, and the roster inference (infer.py) when its config exists.
- **Which clips**: audio clips (kind audio, or a file ending `.wav .mp3 .m4a .aac .flac .ogg`) from the last scan (not cards in readers) that have a transcript or something heard.
- **Signals and their scores** (one candidate per destination folder; a second signal for the same folder adds 0.08, up to 1):
  - **copy**: another scanned clip with the same recorder stem and byte count (and durations within 2 s when both known) is already headed for, or sits in, a folder. 0.92 if that folder is an interviewee folder ("An identical file is already filed here: <path>"), else 0.3 ("An identical file was also copied to <path>").
  - **transcript**: share of the recording's word runs (runs of 4 tokens; every Chinese character is a token, every Latin word of 2+ letters is a token) found in a Vault interview. Counted only at 6 % and 25 shared runs or more; scores 0.85 to 0.95 at 25 % and 120 shared, 0.55 at 12 % and 60, else 0.3; top 4 references. The folder is the interviewee folder on the destination whose name matches the person (a Chinese name must appear whole; an English name needs two of its parts, or one part of 4+ letters that is not one of about 80 common Taiwanese surnames); ties broken by episode name; else the roster's answer; text notes "folder from the roster", "but two folders carry that name", "no folder on P: carries that name".
  - **name**: a roster name heard on the recording: 0.72, or 0.35 when only part of an English name was heard; a name on two episodes is a folderless 0.4 note; the quote (90 characters) and its second are shown.
  - **intro**: someone saying who they are, the name cut at the first word that cannot be part of a name (Chinese: at most 12 characters; English: first 4 words before punctuation); 0.6 with a folder, 0.3 without; first 6 introductions; the quote is 120 characters.
  - **calendar**: the calendar's suggestion for the clip, when it has a real date: 0.7 high confidence, else 0.35.
  - Confidence: high from 0.75, medium from 0.45, else low.
- **Disagreement**: a clip already filed under the destination whose best confident (high) content signal (copy or transcript) points elsewhere, unless an identical copy is also filed where it sits.
- **Suggestions on the main grid** (marked as from audio): the top candidate with a folder, for each clip that is not assigned, that the calendar has no suggestion for, whose top confidence is not low, and that is either not filed or filed where the audio confidently disagrees. Shown as "<label>", a long dash, then the signals joined by " + "; confidence high or low (medium shows as low); the first timed quote heard; up to 300 characters of evidence.
- **Audio tab** (GET `/api/audio`): the Vault root and how many interview references it holds, the transcriber's last run (time, model), how many audio clips exist, and per clip: transcribed, seconds scanned, duration, main language, where it is filed, where it is assigned, the top candidate (folder, label, confidence, signals, score), disagreement, whether anything was heard.
- **One clip** (GET `/api/audio/<clip id>`): every candidate with evidence, per-window best match (a window's best reference needs 6 % and 8 shared runs, among the top 6 references), and the transcript (model, scanned, duration, where it was adopted from, windows with segments at tenth-of-a-second times). Unknown clip 404 "unknown clip"; not audio 400 "not an audio clip".
- **Background**: every 15 seconds (first after 3) checks whether the transcriber wrote something new (the heard-names file, the number or newest time of transcripts, the Vault signature) and refreshes the page's state when so. The Vault is re-listed at most once a minute, the transcript list every 10 seconds; results are cached per clip until something feeding them changes. Log lines: "[audio] <n> clip(s) with something heard on them", "[audio] vault: <n> interview transcript(s) under <root>".
- Windows versus elsewhere: folder listings use the operating system's order on Windows and name order elsewhere.

## Downloading footage, and links for a folder

(source: downloads.py; public page files in public/share/)

- **Who**: under the dashboard ("trusted identity"), the download and preview routes need a signed-in person ("sign in to download footage", 401); standalone, anyone who can reach the sorter. Making and managing links needs an admin ("<what> needs an admin of this dashboard", 403). The public link routes need nothing but the link.
- **Download the selected clips**:
  - POST `/api/download/plan` with clip ids (at least one, "choose at least one clip"; at most 20,000, "that is more than 20000 clips at once: download a folder at a time") and whether to include proxies. Answers each file to fetch (clip id, index, path relative to the selection's common folder, or just the name when the files are on two drives, size, role, its URL) and the total bytes, plus how many were skipped as unknown clips, cards still in a reader, or files no longer on disk. Logged with who, counts and bytes.
  - The browser writes the files into a folder the person picks on their own computer.
  - GET or HEAD `/api/download/file/<clip id>/<index>?n=<name>`: the file, as an attachment, resumable (range requests answered with 206). Refusals: unknown clip or a card in a reader 404 "unknown clip"; "this clip has no such file" 404; the name no longer matches the planned one (a rescan reordered the clip) 409 "the clip changed since the download was planned: start the download again"; "the file is not on the server any more" 404. Only files a scan recorded for a clip are ever opened.
- **Links for a folder** (admin):
  - GET `/api/shares`: every link, newest first (label, folder shown, made by, made at, expires at, switched off at, times opened, last opened, status active/expired/revoked, its path `share/<token>/`) and the public base address (`settings.sharePublicBase`, used only when it starts with `https://`).
  - POST `/api/shares`: a folder by `{dest}` (under the destination) or `{root, rel}` (inside any of the sorter's roots: destination, staging, source roots, scan roots), a label (default the folder name, cut to 120), and days (default 14, 1 to 365, or 0 / empty for no end date). Refusals: "that folder is not inside one of the sorter's folders"; "choose a folder inside it: a link for a whole root would hand out everything"; "that is not a folder a link can be made for" (`.`, `..`, a colon, a hidden or junk name); "that folder is not on the server yet (a planned folder has nothing in it to share)" (404); "days must be a number"; "a link lasts between 1 and 365 days, or has no end date".
  - POST `/api/shares/<id>/revoke`: switches the link off at once ("no such link" 404).
  - Links live in `<data>/shares.json`. The token is 128 bits.
- **The public link** `/share/<token>/` (no account):
  - Unknown, switched off and expired links all look the same: a 404 page `gone.html`, and the API text "This link is not available. It may have been switched off or have run out. Ask whoever sent it for a new one."
  - `/share/<token>` without the slash redirects (307) to the slash form. The page is served with no referrer and "noindex, nofollow".
  - `/share/<token>/list`: label, expiry, every file (relative path, size, modified time), total bytes, and whether the list stopped early. The folder is walked without following links, at most 16 folders deep, at most 50,000 files; hidden names (starting with `.`), `thumbs.db`, `desktop.ini`, and names ending `.partial .tmp .part .crdownload .ccsync-tmp .lock` are never listed or served. The list is reused for 30 seconds. Each list request counts as an "open" (saved at once on the first open, then at most once a minute).
  - `/share/<token>/file/<path>`: one file, resumable. A path with backslashes, a leading slash, `.`/`..`, a colon or a hidden or junk segment, a link, or anything whose real location is outside the folder: 404 "no such file".
  - `/share/<token>/zip?dir=<sub folder>`: the whole folder or one sub folder as a ZIP, built as it streams, uncompressed, ZIP64; named after the sub folder or the link's label (default "footage"). A file that vanished is left out. Nothing there: 404 "nothing to download there"; a bad sub folder "no such folder".
  - `/share/assets/<name>`: the public page's own scripts and styles (never an `.html`, never a hidden name).
- **A picture and a preview by place** (for the dashboard's "bring originals" picker, which knows files by their path under the destination):
  - GET `/api/path/thumb?dest=<path>&s=s`: the thumbnail of that file (small with `s=s`, else large), made from its proxy (`Proxy/<same name>.<playable>` beside it) or the file itself. Waits up to 12 seconds for one to be made. No picture possible: 404 "no picture yet: this file has no proxy"; failed: 404 "no picture could be made" (both cached 60 s); not signed in 401 "sign in first"; unknown 404 "no such file". A found picture is cached privately for a day.
  - GET or HEAD `/api/path/stream?dest=<path>`: plays the proxy, or the file itself when a browser can play it; else 404 "nothing to play yet: this file has no proxy, and a browser cannot play the original". Cached privately 10 minutes.

## Thumbnails and scrub filmstrips

(source: thumbs.py; served through web.py routes and the path routes above)

- **Kept by recording, not by path**: every copy of one recording (card, staging, final folder) shares one picture, filed under a 16-character hash of the clip's identity key. Pictures live in `<cache>/thumbs/`, strips in `<cache>/strips/`.
- **Two sizes from one ffmpeg run**: 320 px and 160 px wide, WebP at quality 75, or JPEG if this ffmpeg has no WebP encoder (found out on the first failure, then JPEG from then on).
- **Which file a picture is made from**: an image sequence's first image or video in its folder (looking at up to 400 entries); else a playable proxy; else a playable master; else a still JPEG sidecar; else a master that is an image; else the JPEG preview embedded inside a TIFF-based RAW (`.arw .dng .nef .cr2 .srw .pef .orf .rw2`, the largest embedded preview up to 8 MB, nothing demosaiced); else any playable or image file.
- A video's picture is taken 1 second in; if that fails (a very short clip) from the first frame.
- **Filmstrips**: for video only: one frame per 10 seconds, at least 12, at most 50; each 160 px wide, tiled 10 across. For a file of 50 MB or more each frame is taken by its own short seek (falling back to the one-pass way if a seek fails); smaller files use one pass over keyframes. The duration comes from the clip, else from ffprobe (20-second timeout). A strip comes with a small description file (frames, columns, rows, frame width, duration).
- Strips have a format version (now 2); strips of other versions are deleted when the backfill runs, and every strip is remade.
- ffmpeg runs with 2 decoder threads, a 45-second timeout per run, no console window on Windows, and argument lists (so names with spaces or Chinese are safe). ffmpeg and ffprobe come from the configured ffmpeg folder (`.exe` or bare name) or the system path.
- **Queue**: 6 workers. A picture someone is looking at jumps the queue. The **backfill** (every 6 hours, first 10 seconds after start, and after scans) queues every missing thumbnail (not for audio or "other" clips) and then every missing strip (video only) at low priority; at most `min(4, max(2, cores/2))` low-priority jobs run at once, so workers stay free for a picture someone waits for.
- A thumbnail request waits up to 10 seconds, a strip request up to 20, then answers "none yet".
- **A failure is not retried for an hour**: a request for the same picture within that hour gets "none" at once.
- **Pictures a companion made** (for cards the server cannot read, such as BRAW): accepted when both sizes are JPEG or both WebP and each is at most 256 KB; an existing picture is kept.
- Statistics: queued, running, failed, whether WebP is in use.

## Destinations and the move plan

(source: moveplan.py; called by the engine and the `/api/moves/*` routes in web.py, which another section covers)

- **A destination** is a folder path under the destination root (`destRoot`), typed with `/` (a `\` is read as `/`). It is cleaned as follows, and refused (treated as no destination) when:
  - it is not text, contains an unpaired surrogate character, is empty, starts with a drive letter or `//`;
  - any part is only dots (`.`, `..`, `...`), contains `< > : " | ? *` or a control character, or is a Windows reserved name (`CON`, `PRN`, `AUX`, `NUL`, `COM1`-`COM9`, `LPT1`-`LPT9`, also with an extension);
  - a part becomes empty once trailing dots and spaces are trimmed (Windows drops them, so "Day 1." is stored as "Day 1"). Empty parts (double slashes) are skipped.
- **Spelled as the disk spells it**: each part that matches an existing folder without case takes the existing spelling (an exact match wins, else the first in sorted order), so "ff5/b-roll" lands in "FF5/B-roll" on the case-sensitive NAS. Parts that do not exist yet keep the first spelling used anywhere in the same plan.
- **The plan** (intent in the manifest, times what the last scan found):
  - Only assignments with a valid destination that are not yet fulfilled.
  - An assigned clip the scan no longer knows is listed as **missing**, unless something else holds it (a card in a reader).
  - Clips are grouped into time folders when `timeFolders.enabled` is on (with `timeFolders.labels`; the grouping rules are in timefolder.py).
  - Where each file of a clip goes, inside its base folder:
    - an image sequence moves as one whole folder, whatever the structure setting;
    - structure **preserve**: the file keeps its path relative to the clip's source root (or just its name if it is not under it);
    - structure **convention** (default): a proxy or sidecar inside a proxy folder (`Proxy`, `Proxies`, or a Sony card's `PRIVATE/M4ROOT/SUB`) goes to `<base>/Proxy/<its path inside that proxy folder>`; every other file, including a sidecar sitting next to its master (Resolve reads the grade there), goes straight into `<base>`.
  - Planned folders are created even when nothing is assigned to them yet; placeholder folders are not (they appear only once a clip lands in them).
  - Every parent of every target folder is listed (the destination root itself is assumed to exist).
  - The answer: entries (clip id, source, destination, bytes, whether it is a folder, role), folders (sorted), total bytes, missing clip ids, and the time-folder groups (destination, leaf name, base, camera, day, clip ids, bytes, whether it already exists, which existing folder it merges into, warnings).
  - On the NAS, file paths a Windows companion reported for a card (`H:\G013_C038.braw`) are split as Windows paths, so a card copy is not planned as one long file name.
- **Collisions before the mover is handed the plan**:
  - Two entries for the same destination (compared without case): when both are files of the same size and identical byte for byte, the second is dropped and reported under "duplicates" (kept source, dropped source, bytes); otherwise it is a **collision**.
  - Something already at the destination: an identical file of the same size is dropped and reported under "already there"; anything else is a collision.
  - "Identical" means a full byte-for-byte comparison in 8 MB chunks, stopping at the first difference; unreadable means not identical. Up to 32 files are compared at once.
  - A collision is never resolved automatically; it is a decision for a person.
- **The destination tree** for the page: folders only (never files) under the destination root, to a depth the caller sets, skipping names starting with `.` or `$` and folders called `Proxy`, `Render in place`, `Renders in place` (any case), sorted in the page's collation order. Planned folders that do not exist yet are merged in and marked planned. Helpers also answer "does this folder exist on disk" and "how many files are under this folder, up to a cap" (used to tell an empty folder from a full one).
- The time folders the current assignments imply are listed per destination for the tree (only when time folders are on).

## The mover: carrying out a move plan on the server

(source: moves.py; driven from the engine and the `/api/moves/*` routes)

- **It only ever renames.** It never deletes, never copies footage, never overwrites. A move across file systems is refused: "on a different filesystem: refused, nothing is ever copied".
- **Overwrite protection differs by system**: on Windows a rename never replaces; on Linux a rename with "no replace" is used; where the file system does not support that, a folder is moved by first creating the empty destination folder as a claim (the move fails if anything lands inside it first) and a file by hard-linking then removing the old name.
- **A plan that is not a plan is refused before anything is looked at** (each problem listed): "not a move plan"; "entry <i>: needs src and dst"; "entry <i>: needs a byte count" (a whole number, zero or more); "entry <i>: <src|dst> is not a clean absolute path: <p>" (not absolute, not normalised, or containing `..`); "entry <i>: destination outside <destRoot>: <dst>"; "entry <i>: two entries share the destination <dst>"; "folder outside <destRoot or 'an absolute path'>: <f>".
- **Dry run** (nothing changes). Reports: plan hash, ok, time, entries, pending, inside the Projects tree, already done, recovered, folders to create, bytes, and up to 500 problems with a total count. Problems:
  - "a file sits where a folder is planned: <f>";
  - an entry whose journal says done and whose destination exists is "already done";
  - "source missing: <src>", except when the journal shows it was started and the destination holds exactly the planned bytes (the move happened but was not journalled): then it is "recovered";
  - "expected a folder: <src>"; "source unreadable: <src> (<error>)";
  - "size changed: <src> (<n> bytes, the plan says <m>)" (a folder's size excludes `.DS_Store`, `Thumbs.db`, `desktop.ini`, `sync.ffs_db` and the skip folders: `$RECYCLE.BIN`, `System Volume Information`, `#recycle`, `.git`, `node_modules`, `__MACOSX`, `.Spotlight-V100`, `.Trashes`, `.fseventsd`, `lost+found`, `dupe-quarantine`);
  - "destination occupied: <dst>";
  - a source inside the destination root (the Projects tree, which editors' computers sync) must be moved by the CC Sync dashboard's own file move so every editor's copy follows. Without that hook: "inside Projects, so every editor's copy must follow; this server has no follow-up path for it: <src>". With it, a proxy inside the Projects tree is only movable when it will be carried along by its master's move (same stem in `Proxy/` beside the master, to exactly the planned place); else "inside Projects, in a Proxy folder: the dashboard moves a proxy only with its original (Proxy/<same name> beside it, to exactly the planned place), so <src> would be left behind. Move it by hand, or plan it without this proxy".
  - A clean dry run is remembered (in memory) for this exact plan (by a hash of its entries and folders).
- **Execute**, refused when: "no passing dry-run of this plan: dry-run it first"; "the passing dry-run is more than an hour old: dry-run it again"; "another move is running" (one at a time); the disk changed since: "the disk changed since the dry-run: nothing was moved" (with the problems); a Projects entry the dashboard could not move: "an entry cannot be moved by the dashboard: nothing was moved" (a clip is never split).
  - Creates the planned folders, then moves entry by entry; proxies the dashboard will carry with their master are done last so the carry is seen.
  - Each entry is written to the move journal `<logs>/move-journal.jsonl` before (`start`) and after (`done`), with time, source, destination, bytes, clip id and who. A file an earlier Projects move already carried along is journalled done with `carried`; an entry an earlier interrupted run moved is journalled done with `recovered`.
  - Stops at the first failure and undoes nothing: answers the failing entry's index, source, destination, reason, how many moved, bytes, folders created, skipped.
  - Success answers moved, skipped, recovered, bytes, folders created, and the source folders left empty (reported, never removed).
  - A progress callback reports done, of, bytes after each entry.
  - The catalog follows the journal, and the ledger follows the move (see "Moves keep the ledger right").
- **Verify** a plan afterwards: each destination present at the planned size and its source gone; problems "missing at destination: <dst>", "size differs at destination: <dst> (<n>, planned <m>)", "still at the source too: <src>" (up to 500).

## Adopting moves made outside the sorter

(source: relocate.py; run by the engine after every scan)

- Footage moved by hand (dragged in Explorer, copied onto the NAS by hand, an interviewee folder moved to the right episode) leaves assignments keyed by clip ids that no longer exist; without this, the next move plan would move the footage back.
- **Re-keying**: an assignment whose clip id is not in the scan is looked up through the catalog by its recording key; if exactly one present copy is in the scan (or exactly one in the final tree when several are), the assignment moves to that clip (remembering `rekeyedFrom`). If that clip already has its own assignment, the stale one is dropped. None found: counted "gone"; several: counted "ambiguous"; no key: counted "unknown". Never guessed.
- **For a clip under the destination root**:
  - in its assigned folder, or a time-folder leaf inside it: marked fulfilled (once);
  - elsewhere and never fulfilled: a pending re-file, left alone;
  - elsewhere after it was fulfilled: if another present copy sits in the assigned folder it is a duplicate, left alone; otherwise the hand move wins: the destination becomes where it is now (time-folder leaf folded into its parent), with `relocatedFrom` and `relocatedAt` recorded.
- A clip outside the destination root (still in staging) keeps its intent.
- **Folder moves**: when every adopted clip from one folder went to one other folder (not inside itself) and no clip is left in the old folder, the old folder is treated as renamed: planned folders, placeholder folders, calendar bindings and every other assignment under it are renamed too (duplicates removed without case), and the pair is reported.
- Nothing on disk is touched. A one-line summary is logged and shown, built from: "<n> re-keyed", "<n> found in place", "<n> moved by hand, adopted", "<n> folder move(s): <from> -> <to>; ...", "<n> duplicate copies left alone", "<n> gone", "<n> ambiguous".

## How long a WAV plays

(source: wav.py; used by the scan)

- Reads only the RIFF chunk table of a `.wav`: duration is data bytes divided by bytes per second, plus sample rate, channels and bits. A data size of `0xFFFFFFFF`, or one running past the end of the file, means the recorder never closed the header; what is on disk counts. Anything that is not a parseable WAV gives no answer. Read-only.

## Audio sync: placing loose recorder WAVs beside their video (new, uncommitted, possibly unfinished)

(source: audio_sync/*.py and audio_sync/ui/index.html; the whole folder is untracked in git and another session is working in it)

- **What it is**: a separate, staged pipeline, run from the command line, that works out which shoot folder each loose field-recorder WAV belongs to and when it really started, shows the answers in a local review page, and records a person's approve or reject. It is not wired into the sorter's web app or the dashboard; nothing in the rest of the sorter imports it.
- **How complete it is**: stages 0 to 5 and the review page are implemented and run end to end from the command line. The last stage (6, carrying approved matches out) only writes a move list to a file; nothing sends it to the sorter, and there is no command for it. See the lists at the end.

### Settings and files

(source: audio_sync/settings.py, audio_sync/store.py)

- Data folder: env `FS_AUDIO_SYNC_DATA`, else `<repo>/data/audio-sync` (created if missing).
- `settings.json` in that folder (or `--settings PATH`) overlays the defaults, nested objects merged key by key; a byte-order mark is tolerated.
- Defaults:
  - `audioRoots` (none): where loose audio is searched (recursively).
  - `videoRoots` (none): where video lives.
  - `skipDirNames`: `_duplicates`, `Proxy`, `$RECYCLE.BIN`, `System Volume Information`, `#recycle`, `dupe-quarantine`, `.git`, `node_modules`.
  - `duplicatesDir`: default `<first audio root>/_duplicates`.
  - `tzOffsetHours`: 8.
  - `ffmpegDir`: empty (use `ffmpeg`/`ffprobe` from the path).
  - `time`: `padMinutes` 15, `plausibleYears` 2024 to 2027, `mtimeAgreeSeconds` 120, `shiftHours` 5, -5, 6, -6, 8, -8, 1, -1, 2, -2, 3, -3, 4, -4, 7, -7.
  - `waveform`: `minPeak` 0.35, `minMargin` 0.05, `minSeconds` 20, `clipProbeSeconds` 90, `maxClipsPerFolder` 12, `agreeSeconds` 2.0, `singlePeak` 0.75, `singleMargin` 0.25, `searchPadMinutes` 20.
  - `clocks`: `driftSecondsPerHour` 2.0, `maxFilesFromAnchor` 25, `maxDaysFromAnchor` 14, `maxGapHours` 72.
  - `transcript`: `engine` "soniox", `firstMinutes` 10, `apiKeyEnv` "SONIOX_API_KEY"; also read if present: `model` (default `stt-async-v6`), `languageHints` (default en, zh, uk, ru).
  - `sorter`: `baseUrl`, `destRoot` (both empty).
  - `port`: 8794.
- State file `state.db` in the data folder: the indexed audio and video, duplicate groups, candidate placements per stage with their evidence, decisions, transcripts, and a small key-value store. Times are "wall seconds": the local clock the cameras and recorders showed, with no zone.
- Cache folders: `env-cache/` (loudness envelopes), `stt-cache/` (audio cut for transcription). Output files: `apply-YYYYMMDD-HHMMSS.json`, `not-on-nas.json`, `video-proposals.json`.
- When `ffmpegDir` is set, every stage looks for `ffmpeg.exe` / `ffprobe.exe` in it (the Windows names only).

### Command line

(source: audio_sync/__main__.py)

- `py -3.12 -m footage_sorter.audio_sync <command> [--settings PATH] [--only audio|video] [--path TEXT] [--yes]`:
  - `index`: stage 0 (`--only audio` or `--only video` limits it); prints row counts.
  - `dupes`: stage 1; prints group and duplicate counts.
  - `match`: stages 2 to 4; `--path` limits it to WAVs whose path contains the text.
  - `transcribe`: stage 5; without `--yes` it only prints the estimated hours and cost.
  - `serve`: the review page.
  - `report`: counts and hours by origin and status.
  - Anything else: "unknown command".
- Separate module commands: `python -m footage_sorter.audio_sync.notnas <found.jsonl ...>`, `python -m footage_sorter.audio_sync.videosort <folder prefix>`, and `discover.py` runnable as a lone script.

### Recorder knowledge

(source: audio_sync/devices.py)

- Reads a WAV's chunk table only: `RIFF` or `RF64`, format (rate, channels, bits, bytes per second), the broadcast-WAV `bext` block (description, originator, reference, origination date and time, time reference), and the data size (64-bit size from `ds64`; a header never closed after a power loss counts what is on disk).
- Recorder profiles, by originator then by file name:
  - **RODE Wireless PRO** (`<5 digits>_Wireless PRO` or originator): file counter from the name; clock from bext with the firmware's year bug fixed (year `0026` read as 2026); each transmitter's card identified by its folder.
  - **Zoom** (originator `ZOOM...`, or a name `DDMMYY_NNN` with no originator): counter from the name; clock from bext, else the date only from the name ("name-date-only").
  - **Tascam** (originator containing `TASCAM` or `FR-AV2`): counter from the name; clock from bext.
  - Any other broadcast WAV: `bwf:<originator>`, clock from bext.
  - Otherwise `unknown`.
- **Music, not field audio**, when: inside a folder named music, songs, bgm, sfx, sound effects, stems, soundtrack or library; the name contains music words (music, song, mix, remix, beat, instrumental, feat, OST, soundtrack, artlist, epidemic, musicbed, sfx, ambient, loop, stem, master/mastered, bgm, demo, jingle, intro, outro, vocal, bpm, "120bpm"); an "Artist - Title" name without a recorder number; or written by Pro Tools, Logic, Ableton, FL Studio, Reaper or Cubase.
- **Unusable**: "not a readable WAV", "no fmt chunk", "no audio data", "shorter than <n> s" (30 by default).
- Only 32-bit WAVs count as field audio anywhere in the pipeline (every recorder used writes 32-bit float).

### Stage -1: finding loose field audio on a computer

(source: audio_sync/discover.py)

- `discover.py <roots...> [--min-seconds 30] [--no-fp] [--workers 8] [--out FILE]`: walks the roots (skipping Windows, Program Files, ProgramData, `$RECYCLE.BIN`, System Volume Information, AppData, node_modules, `.git`, site-packages, `.venv`, venv, steamapps, MSOCache, Recovery, WindowsApps, `#recycle`, dupe-quarantine and hidden folders) for `.wav`/`.bwf` files (not `._` files), and writes one JSON line per WAV, rejects included with their reason: path, size, modified time, format, bext fields, recorder profile, broken reason, music reason, `field` (readable, not music, 32-bit), `recorder` (a known profile), the computer's host name, and for field audio a fingerprint (size plus a SHA-1 of the first and last MB).
- Output is UTF-8 (to a file with `--out`, else standard output switched to UTF-8 so Chinese names survive on Windows).

### Stage 0: index

(source: audio_sync/index.py)

- **Video**: runs the sorter's own scan over `videoRoots` (same recorded-at rules the sorter shows), keeps video clips, and records per clip: master path, shoot folder (the clip's folder, `Proxy`/`Proxies` stripped), size, modified time, start, duration, camera, proxy, whether it has sound. Duration and sound come from ffprobe (60-second timeout, 16 at a time; for BRAW the proxy is probed) unless an unchanged earlier row already has them. Scan warnings are printed. Every row not seen this time is marked absent.
- **Audio**: every `.wav`/`.bwf` under `audioRoots` (origin "loose") and under `videoRoots` (origin "filed", not already counted as loose), skipping the skip folders except `Proxy` and hidden folders. Unchanged files (same size, time within 2 s, with a fingerprint) are kept; others are read (16 at a time): format, bext, recorder profile, broken and music reasons, "file closed minus length" start time, fingerprint (not for broken files).
- **Is the clock real?** ("trusted", stage 2 only uses trusted clocks):
  - a bext clock in a plausible year: trusted, noted "recorder clock plausible and agrees with mtime" (within 120 s), "recorder clock plausible; mtime differs by <n> s", or "recorder clock plausible";
  - a clock in an implausible year: not trusted, "recorder clock reads <date>: reset";
  - no recorder clock, unknown recorder, plausible file time: unknown, "no recorder clock; mtime only";
  - otherwise not trusted, "no usable clock".

### Stage 1: duplicates

(source: audio_sync/dupes.py)

- WAVs with the same fingerprint are one recording. One is kept per group: an already filed copy beats a loose one, then the shortest path, then alphabetical. The others are recorded with "already filed at <path>" or "same as <path>". Nothing is moved. Re-running replaces the previous groups.

### Stages 2 to 4: time, waveform, clocks

(source: audio_sync/match.py, audio_sync/waveform.py)

- Works on usable WAVs: present, not broken, not music, 32-bit, not a duplicate. Video considered: present clips with a start time.
- Re-running clears earlier candidates (all of them, or only those of the WAVs `--path` selects).
- **Stage 2 (time)**: from the WAV's estimated start (a trusted recorder clock, else the file-closed time for unknown-trust files), the shoot folders whose clips overlap its span padded by 15 minutes (clips that started up to 4 hours earlier count), ranked by real overlap then padded overlap, with clip and camera counts. Recorded as a "time" candidate: score 0.8 when exactly one folder overlaps for real, else 0.4. A WAV with no estimate gets nothing.
- **Stage 3 (waveform)**: both sides are turned into a 250-per-second loudness curve (mono, 8 kHz, cached on disk per file, size, time and range) and compared by normalised cross-correlation on log-compressed curves. From the overlapping clips with sound and at least 8 s long, up to 24 spread over time are probed: 90 s from each clip's middle, searched within 20 minutes of where the time estimate expects it. A probe is "strong" at peak 0.35 and margin 0.05 (margin = peak minus the best rival more than half a second away). The match is accepted when at least two strong probes from one camera agree on the WAV's start within 2 s, or one probe has peak at least 0.75 and margin at least 0.25. The WAV's real start is the median of the agreeing group, on that camera's clock; the folder is the commonest among them. Recorded as a "waveform" candidate scored 0.6 plus half the top peak (at most 0.99); a comparison with no strong agreement is recorded as "waveform-weak". An unreadable file is recorded as an error and does not stop the run.
- **Time zone shifts**: when the clock as read finds nothing, whole-hour shifts are tried in the order of `shiftHours` (a recorder on Kyiv time against cameras on Taiwan time is 5 h out); a hit records which shift it took.
- **Stage 4 (clocks)**: a recorder's clock keeps running after a reset, so a placed file's offset (real start minus clock start) estimates its neighbours' on the same kind of recorder. Guards: counter order must agree with clock order; at most 25 files and 14 days from the anchor; no gap over 72 hours between files (nor an overlap over 60 s); a file between two anchors gets an estimate only if both agree within 2 s per hour of separation plus 1 s, else nothing between them is estimated. Each estimate is recorded as a "clock" candidate (always score 0.4) and re-checked by the waveform (no time-zone shifts are tried for an estimate); up to 7 rounds, stopping when a round confirms nothing new.
- **Sibling channels**: a dual-mono recorder writes one file per channel of the same take (same recorder kind, start and length to the second); an unplaced channel goes where its sibling was placed, scored 0.05 lower, noted as placed through a sibling.
- Prints progress and returns how many WAVs were usable and how many were placed by waveform; the last run's time and counts are stored.

### Stage 5: transcripts (paid)

(source: audio_sync/transcribe.py)

- For WAVs still unmatched, ambiguous, inferred or time-only, and for every clip with sound of 20 s or more that no placed WAV already covers (a clip starting within 5 s of a placed WAV's span in the same folder is covered): the first 10 minutes of each are transcribed by Soniox (`https://api.soniox.com/v1`), cut first to 16 kHz mono Opus at 24 kbit/s (cached), uploaded, transcribed with language identification and speaker separation, then the uploaded file and the transcription are deleted from Soniox.
- **Cost guard**: it first prints "<n> WAVs and <m> clips to transcribe (<h> h of audio, about $<cost>); already done: ...", at $0.10 per audio hour, and spends nothing unless `--yes` is given. Already transcribed files are skipped.
- Needs the key in the environment variable named by `apiKeyEnv` (default `SONIOX_API_KEY`): "set SONIOX_API_KEY first".
- 8 transcriptions at a time; each request retried up to 5 times on 429/500/502/503/504 or a network error, waiting 5, 10, 15, 20 s; a status poll every 5 s for up to an hour. If the configured model is refused, the newest `stt-async*` model offered is used instead.
- Matching: transcripts are cut into runs of 4 words (Latin, Cyrillic) or 6 characters (Chinese and Japanese); a WAV and a clip share at least 3 runs and 5 % of the smaller side to count. The commonest time difference between shared runs gives the offset. The best clip's folder and implied start become a "transcript" candidate (score 0.3 plus the share, at most 0.7, with the top 8 clips and folder votes from the top 5), then the waveform is checked around that start against every clip in that folder; a waveform match is recorded as a "waveform" candidate.
- Returns up to 20 errors, the error count, and how many WAVs got a transcript candidate.

### Verdicts and the text report

(source: audio_sync/report.py)

- One verdict per present WAV:
  - `duplicate` (with the kept copy and why);
  - `not-field` (broken, music, or not 32-bit, with the reason);
  - with a waveform candidate (best score): `matched` for a loose WAV; for a filed WAV `confirmed` when it sits in that folder or a sub folder of it, else `misplaced`;
  - else with a time candidate: `time-only` when exactly one folder overlapped, else `ambiguous`; a filed WAV in that one folder is `confirmed` (score at most 0.6);
  - else with a clock estimate: `inferred` (score 0.3);
  - else `unmatched`.
  - Transcript candidates and weak waveform results do not change the verdict.
- Destination: `<shoot folder>/Audio` (not for `confirmed`); a decision with a folder overrides it.
- `report` prints, per origin and status, the count and hours.

### Stage 6: the move list (incomplete)

(source: audio_sync/apply.py)

- Builds a list of moves from the verdicts and writes it to `apply-<date>-<time>.json` in the data folder: entries (source, destination, bytes, why, audio id), held, skipped.
  - A loose duplicate goes to `duplicatesDir`.
  - An approved decision goes to its destination (default `<folder>/Audio`).
  - Skipped: already in that folder ("already there"); an identical copy already at the destination ("identical copy already at <dst>", compared by size and the first MB).
  - Held: a destination inside an audio root or inside `W:\Temp Transfer` (a shoot itself still unsorted): "the shoot is itself still unsorted in W:; goes with it". Duplicates are never held.
  - A different file of the same name at the destination gets `_1`, `_2`, ... added before the extension.
- Nothing is moved, and nothing calls the sorter. UNREACHABLE from the command line (no `apply` command); only by importing it.

### Which found WAVs are not on the NAS

(source: audio_sync/notnas.py)

- Reads `discover.py` output files, keeps field WAVs (not broken, not music, 32-bit) whose fingerprint matches no WAV in the index, marks repeats among them, writes `not-on-nas.json`, and prints the count, unique count, unique hours, and the 40 biggest (computer, folder) groups.

### Placing loose video by the same method

(source: audio_sync/videosort.py)

- `videosort <folder prefix>`: for every indexed clip under that prefix, finds filed clips (outside the prefix and not under a `\youtube\` folder) overlapping its time padded by 15 minutes, and searches 60 s from its middle inside up to 12 of the longest of them with sound. A single probe must reach peak 0.75 and margin 0.25 to count ("waveform"); otherwise, if exactly one folder overlaps in time, "time (one shoot overlaps)"; if several, "ambiguous by time". Writes `video-proposals.json` and prints counts per outcome and folder. Nothing moves.

### The review page

(source: audio_sync/server.py, audio_sync/ui/index.html)

- `serve` starts a local web server at `http://127.0.0.1:<port, default 8794>/` (prints "audio sync review: <url>"). No sign-in of any kind. Requests are not logged.
- **Routes**:
  - GET `/` or `/index.html`: the page.
  - GET `/api/audio-sync/list` (`?fresh=1` recomputes): every WAV's id, name, path, origin, recorder, length, status, score, stage, folder, real start (and as text), destination, decision, reason, kept copy, clock note. Verdicts are computed once and reused until a decision or `fresh=1`.
  - GET `/api/audio-sync/item/<id>`: the WAV's full record (with its clock and file-time starts as text), its verdict, every candidate with evidence, the video clips overlapping its real start (padded 15 minutes; each with where it starts inside the WAV and whether it is in the chosen folder), the chosen folder, and its transcript. Unknown id: 404 "not found: <id>".
  - GET `/api/audio-sync/folders?q=<text>`: shoot folders containing the text, with clip counts and first clip time, oldest first, up to 200.
  - GET `/api/audio-sync/apreview?path=&start=&dur=` (default start 0, 60 s): an MP3 (stereo, 128 kbit/s) of that stretch of the WAV, cut by ffmpeg as it streams. GET `/api/audio-sync/vpreview?...`: a 360-line H.264 MP4 with AAC sound of that stretch of a clip. Only paths the index knows (a WAV, a clip, or a clip's proxy): otherwise 404 "unknown media".
  - POST `/api/audio-sync/decide` `{id, state, folder, trueStart, dest, note, by}`: state `approved`, `rejected`, `ambience` or `pending` (pending removes the decision); else "bad state". The destination defaults to `<folder>/Audio`; by defaults to "ui".
  - POST `/api/audio-sync/bulk` `{ids, state}`: applies the state (default approved) to each listed WAV that has a folder, with its own folder and start.
  - POST `/api/audio-sync/rescore` `{id, trueStart, folder, padMinutes}`: re-runs the waveform search at a hand-set start against the clips around it (within 60 s), optionally only one folder's, searching within `padMinutes` (default 1); answers the evidence and the start as text.
  - Any other path: 404 "not found". Any error: 500 with its message (the page shows it).
- **The page** (light or dark following the system):
  - Header: status chips (matched, misplaced, time-only, ambiguous, inferred, unmatched, confirmed, duplicate, not-field), each a toggle with its count (the first six on at load); an origin selector (loose + filed, loose, already filed); a search box (name or folder); a count "<n> shown"; "approve visible with score >=" (default 0.85, step 0.05) and an **Approve** button that approves every visible matched or misplaced WAV at or above that score that has a folder and no decision, after a confirm "Approve <n> matches?" (or the alert "Nothing visible at that score.").
  - List: one row per WAV with name, length, recorder, "filed" when filed, status badge, decision, and the folder and score (or the reason or clock note). Clicking a row opens it.
  - Detail sections:
    - header: path, recorder and counter, channels, bits, length, recorder clock and note, "file closed - length" time, real start, "goes to" folder;
    - **Why**: per candidate, the date/time or clock-offset evidence (estimated start, anchors and offset, a table of shoot folders with overlap, padded overlap, clips, cameras) and the waveform evidence (how many clips agree, the start, which camera's clock, top peak and margin, a table of probes with where in the WAV, peak, margin, strong); "No stage found anything yet. It goes to transcripts next." when there is nothing;
    - **Timeline**: the WAV as a dark bar with every overlapping clip on a lane per camera, blue for the chosen folder, pale for others, a green outline for a strong waveform hit, a tooltip with name, start and length; "No time estimate, so there is nothing to draw." without a start;
    - **Listen**: a video player and an audio player. Clicking a clip in the timeline plays 30 s of the clip (from up to 30 s in, around its middle) and the matching 30 s of the WAV together, starting both when both are ready; a BRAW or R3D without a proxy says it cannot be previewed. "WAV from <s> s" with **Play WAV** plays 120 s of the WAV.
    - **Transcript**: the stored text, or "None yet."
    - **Decide**: a folder box with suggestions from the folders search as you type; real-start nudge buttons -10 s, -1 s, -0.1 s, -1 frame, +1 frame, +0.1 s, +1 s, +10 s (a frame is 1/30 s) with the adjusted start shown; **Re-check waveform here** (reports a match with how many clips agree and the peak and offers **Use this start**, or "No strong match here (<n> clips compared, best peak <p>)", or "No clips with sound to compare here."); **Approve**, **B-roll ambience (no picture)**, **Reject** (sends no folder), **Clear decision**, and a note box. After a decision the list reloads and the next undecided visible WAV opens.

## Looks redundant or overlapping

- **Three WAV header readers**: `wav.py` (duration for the scan), `audio_sync/devices.py read_riff` (the same chunk walk plus RF64 and bext), and the RAW-preview IFD reader in thumbs.py is a fourth hand-written binary parser. The first two overlap almost entirely.
- **Two "whose recording is this" engines**: `audio_match.py` (transcripts from an external whisper run, Vault shingles, roster names, identical copies, calendar) and `audio_sync` (recorder clocks, waveform correlation, Soniox transcripts with shingles). Both score folders for audio clips; neither uses the other. Both have their own shingle tokeniser (4 tokens in one, 4 words / 6 characters in the other).
- **Two review surfaces for audio**: the sorter's Audio tab (`/api/audio`) and the separate audio-sync review page on port 8794.
- **Three identity rules for "the same file"**: the ledger's name + size + time within 3 s; audio_sync's size + SHA-1 of the first and last MB; moveplan's full byte-for-byte compare; plus audio_match's stem + size + duration within 2 s and audio_sync apply's size + first MB.
- **Three ffmpeg wrappers** with their own path rules: thumbs.py (configured folder, `.exe` or bare, else system path), audio_sync (only `ffmpeg.exe`/`ffprobe.exe` in the folder), and the preview cutter in audio_sync's server.
- **Two link and download mechanisms**: the sorter's folder links (`/share/<token>/`) and the dashboard's b-roll client folders (another section) do the same job with separate code and separate ledgers.
- **Two move-safety layers**: moveplan's collision check (byte compare at plan time) and the mover's dry run (size check at execute time) both look at the destination.
- **Skip-folder lists repeated**: ledger_rules `SKIP_DIRS`, moves `SKIP_DIR_NAMES`, audio_sync `skipDirNames`, discover `SKIP_DIRS`, downloads' hidden and junk names, moveplan `DESTTREE_SKIP`. Each slightly different.
- **Scheduling of the cloud upload is split**: the sorter writes `schedule.json` and `run-now`, the NAS script decides; the sorter also guesses the next run from a marker file.
- **Card tracker "sync" vs "get with refresh"**: POST `/api/cards/sync` and GET `/api/cards?refresh=1` do the same thing.
- `audio_match.audio_candidates` and `best_heard_name` are UNREACHABLE: nothing calls them (an older placing rule kept beside the one in use).
- `audio_sync/videosort.py` duplicates the WAV placement logic for video clips, as a separate command with its own thresholds (60 s probe instead of 90).

## Claims the code does not back

- `audio_sync/__init__.py` lists the stages as `timematch.py` and `clocks.py`; neither file exists (stages 2 to 4 are all in `match.py`).
- `audio_sync/__init__.py` and `apply.py` say stage 6 hands approved matches to the sorter's `/api/assign` and `/api/moves/plan` / `/api/moves/<id>/execute`. The code only writes a JSON move list to a file; nothing calls the sorter, and the command line has no `apply` command.
- The audio-sync state file's decision states include `applied`; nothing ever sets it.
- `audio_sync/match.py` refers to a setting `settings.fieldBits`; there is no such setting, 32-bit is hard-coded (in match.py, report.py, discover.py, notnas.py).
- audio_sync settings that nothing reads: `waveform.minSeconds`, `transcript.engine`, `sorter.baseUrl`, `sorter.destRoot`. Settings that are read but are not in the defaults: `transcript.model`, `transcript.languageHints`.
- `google.py`'s callback carries a note that the error text goes into the page unescaped "like the original"; under the sorter it is always escaped (integrations passes an escaper). Only a caller that passes none would print it raw.
- The docstring of `Ledger.set_volume` lists label, kind, owner, notes, tracked, roots; it also accepts `autoBackup`.
- `report_volumes` accepts a `digest` value and does nothing with it.
- `match.py`'s description says one strong clip anywhere in a long roll is enough to place a WAV; a single clip only counts at peak 0.75 and margin 0.25, and the waveform search is only tried when a time estimate (or a clock estimate) already overlaps some shoot.
- `cloud_status` returns a `boxUsage` field that is always empty.
- `integrations.py` says mutating routes need an admin; POST `/api/google/sync` and POST `/api/cards/sync` (which fetch from outside and rewrite local files) need none.

## Could not determine

- Who may call GET `/api/cards`, `/api/google/status`, `/api/google/calendars`, `/api/audio` and the ledger read routes: the `get`/`post` wrappers that decide sign-in live in web.py and the dashboard mount, outside this part.
- How the companion actually decides "home network" for an automatic backup (`homeHost`, `rttMs` and `homeOnly` are passed through ingest.py to the companion; the test is in the companion).
- What the `who(req)["admin"]` check means under the dashboard versus standalone (integrations says everyone is the local admin standalone; that is decided outside this part).
- The exact shape of `whisper-names.json` and the per-clip whisper transcripts: they are written by an external tool (`tools/whisper-names.py`) not in this part.
- Whether the time-folder grouping inside a move plan adds further refusals or warnings: that is timefolder.py, another reader's file.
- The audio-sync folder is being edited by another session right now; anything described here may already have changed, and the stage numbering in its docstrings suggests further files (a separate time stage and clock stage) were planned or are on their way.
- Whether `ledger_import.py` is still meant to run (the October Worker's feed it reads may no longer exist); the code gives no sign either way.
