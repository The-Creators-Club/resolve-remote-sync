# sorter-py - the Footage Sorter's Python package (footage_sorter/) as mounted in the dashboard
Files read (approximate coverage): web.py (all), engine.py (all), moves.py (all), files.py (all), moveplan.py (all), catalog.py (all), scan.py (all), thumbs.py (all), ledger.py (~45%: plumbing, volumes, scan protocol, delta, summaries, backup, activity), ledger_sources.py (NAS walk, cloud poll), ingest.py (~30%: service, poll, receipt check), ccsync dashboard/src/ccsync_dashboard/sorter.py (all), docs/SORTER_DEPLOY.md; public/app.js and ingest.js polling only.
Probes run: (1) 500 short-lived threads each calling `Ledger.check_external()` on a scratch ledger.db -> `len(led._readers) == 500` after gc (dashboard venv, anyio 4.14.2 whose `WorkerThread.MAX_IDLE_TIME = 10`). (2) `Mover._journal_done()` over a copy-free read of the real 11 MB / 39,264-line move-journal.jsonl: 0.089 s (so not reported as a finding).

## Findings

### sorter-py-1 - Every thread that reads the ledger leaks a SQLite connection for the life of the process
- Category: leak
- Severity: medium
- Confidence: CONFIRMED
- Where: footage-sorter footage_sorter/ledger.py:342-351 (`_rd`), callers ledger.py:635 (`_decide_scans`), 1444 (`batch_summaries`), engine.py:767 (`computers`), autobackup.py:67/147
- What: `_rd()` opens one reader connection per thread (thread-local) and appends it to `self._readers`, which is only closed in `close()`. The list keeps every connection alive after its thread dies. In the dashboard the sync routes run on anyio worker threads, which exit after 10 s idle and are replaced; the engine also starts a new thread per event (`sorter-ledger-sums` on every ledger/clips change a page notices, `sorter-leaves-now`, `sorter-after-ingest`, `sorter-scan`, `sorter-move-*`, `sorter-ledger-nas`). Each of those that touches the ledger adds a connection that is never freed.
- Cost / failure scenario: companions post `/sorter/agent/volumes` every 5 min per machine (`_decide_scans` reads through `_rd`); with requests spaced over 10 s apart most land on a fresh worker thread, so about 12/h/machine = ~1,150 connections/day at 4 machines, ~6,000/day at 20 (estimated). Each holds a file descriptor for ledger.db (plus WAL index mapping) and its own page cache (up to 2 MB once it has served a `batch_summaries`-sized read). Weeks of uptime = tens of thousands of fds and hundreds of MB in the dashboard's one process.
- Evidence: probe (1): 500 threads -> 500 live connections retained; anyio `_backends/_asyncio.py:982 MAX_IDLE_TIME = 10`.
- Ledger: new
- Suggested change: open a short-lived read connection per call (`with closing(sqlite3.connect(...))`, ~0.1 ms) or a small bounded pool, and drop the `_readers` list; or key the thread-local on a `weakref.finalize(threading.current_thread(), c.close)`. Must keep `query_only` and WAL readers.
- Effort / risk: S effort; low risk

### sorter-py-2 - A move run that raises leaves the plan "moving" forever, with no reconcile and no rescan
- Category: resilience
- Severity: medium
- Confidence: CONFIRMED
- Where: footage-sorter footage_sorter/engine.py:1438-1451 (`execute_move.run`), moves.py:347-350, 370-371, 423
- What: the thread body has no try/except. `Mover.execute` only catches errors inside the per-entry rename; the folder creation loop (`os.makedirs(f)` for every planned folder), the `os.stat(dst)` in the carried check, and `verify()`'s `os.stat(dst)` all raise straight out. The thread dies with `m["state"] == "moving"`, so the page shows a run in progress forever, `execute` of that plan answers 409, `reconcile_moves()` (which sets `fulfilledAt` and updates the catalog from the journal) and the follow-up scan never run.
- Cost / failure scenario: permission denied creating a folder under Projects (the deploy notes already show the container cannot read `homes/*`; any dataset ACL change does the same), disk full, or a file vanishing between `lexists` and `stat` -> the admin sees "moving" with no error, and renames that did happen before the failure are not reflected in the manifest until some later scan. No footage is lost (the journal is written per entry), but nobody is told and the state machine is wedged.
- Evidence: read; `run()` lines 1438-1450 and the unguarded calls named above.
- Ledger: new
- Suggested change: wrap `run()` in try/except/finally: on exception set `state = "failed"`, record the error in `m["result"]`, and in `finally` always `reconcile_moves()` under the lock and start the scan. Move the folder creation inside the guarded section of `execute` so it returns `{"ok": False, ...}` like a failed rename.
- Effort / risk: S effort; low risk

### sorter-py-3 - The rescan after a move is silently skipped when a scan is already running
- Category: bug
- Severity: low
- Confidence: PLAUSIBLE
- Where: footage-sorter footage_sorter/engine.py:1450, 930-933
- What: after a move, `start_scan(wait=False)` returns `{"running": True}` without queueing anything if a scan is in flight (an earlier manual scan, or `after_ingest`'s). That scan started before or during the renames, so the clips it stores carry pre-move paths, and no scan follows to correct them.
- Cost / failure scenario: admin presses Scan, then executes a move while it runs -> clips list shows moved clips at their old Temp Transfer paths until someone scans again; the next plan for those clips is blocked with "source missing". Nothing moves wrongly (dry-run catches it), but the page is wrong and a second plan fails.
- Evidence: read.
- Ledger: new
- Suggested change: keep a "rescan requested" flag that `run_scan`'s `finally` honours (one more pass when it was set during the run).
- Effort / risk: S effort; low risk

### sorter-py-4 - Two concurrent Execute presses on one plan: the loser overwrites the winner's state and starts a scan mid-move
- Category: concurrency
- Severity: low
- Confidence: PLAUSIBLE
- Where: footage-sorter footage_sorter/engine.py:1430-1452
- What: the `state == "dry-run"` check and the set to `"moving"` are not under any lock, and both request threads share the same `m` dict. The mover's own `_exec_lock` is non-blocking, so the second run returns `refused: another move is running`; its thread then sets `m["state"] = "refused"`, runs `reconcile_moves()` and starts a scan while the first run is still renaming. When the first finishes it overwrites the state again.
- Cost / failure scenario: double-click or two admins -> the page reports "refused" for a move that is running, and a scan walks the tree half-moved (see sorter-py-3). The renames themselves stay safe (NOREPLACE, one executor).
- Evidence: read; window is the GIL gap between two threadpool requests, small but real on a double-click.
- Ledger: new
- Suggested change: do the check-and-set under `self.lock` and refuse the second press with 409 before starting a thread.
- Effort / risk: S effort; low risk

### sorter-py-5 - Thumbnail workers block on the background semaphore while holding a popped job: interactive requests wait behind the backfill
- Category: perf
- Severity: medium
- Confidence: CONFIRMED
- Where: footage-sorter footage_sorter/thumbs.py:194-197, 433-447
- What: 6 workers, background gate `min(4, max(2, cpu//2))`. A worker pops the head of the heap and only THEN acquires the gate. With only LOW (backfill) work queued, all 6 workers pop LOW jobs: 4 run ffmpeg and 2 sit blocked in `gate.acquire()`. A HIGH request (someone hovering or scrolling) is at the head of the heap but no worker is free to pop it until one of the 4 ffmpeg runs ends.
- Cost / failure scenario: the backfill after a STRIP_VERSION bump or a big ingest is ~21k-33k jobs (hours, per the code's own note). For its whole duration every cold thumbnail/strip a person asks for waits for the next ffmpeg to finish: strips of big proxies take 3.5 s (measured in the code comment), up to the 45 s timeout; the web waits 10 s (thumb) / 20 s (strip) and then answers 404 "none" with a 5-minute cache header, so the grid shows blanks for 5 minutes.
- Evidence: read; the design intent ("A thumbnail somebody is looking at jumps the queue") is defeated because no worker is reserved for HIGH.
- Ledger: new
- Suggested change: acquire the gate before popping a LOW job (or have LOW workers take the gate non-blocking and leave the item if none is free), so at least `workers - background` threads are always idle for HIGH work.
- Effort / risk: S effort; low risk

### sorter-py-6 - Backfill ffmpeg runs unthrottled inside the dashboard container (no -threads, no nice), for hours after any STRIP_VERSION bump
- Category: perf
- Severity: low
- Confidence: PLAUSIBLE
- Where: footage-sorter footage_sorter/thumbs.py:51-54, 296-303, 522-533
- What: each of up to 4 concurrent ffmpeg processes uses ffmpeg's default thread count (all cores) and normal priority. A STRIP_VERSION bump deletes every old strip at the next backfill (`_drop_old_strips`) and re-queues every video clip (~25k-33k at today's 33,022 masters), so the NAS decodes for hours at full CPU next to SMB/Syncthing serving editors and the dashboard's own event loop. The old strips (correct for files under 50 MB) are deleted before replacements exist, so hover scrubbing is blank for most clips until the backfill reaches them.
- Cost / failure scenario: estimated 25k strips x 0.5-3.5 s / 4 parallel = 1-6 h of saturated CPU per bump; repeats on every future bump.
- Evidence: read; strip timing from the module's own measurements.
- Ledger: new
- Suggested change: add `-threads 1` (or 2) to LOW-priority runs and start them with `os.nice(10)`/`preexec_fn`; delete an old-version strip only when its replacement is written, not all up front.
- Effort / risk: S effort; low risk

### sorter-py-7 - Idle cost: the whole Projects tree is re-listed every 60 s, and the leaf refresh does disk I/O under the engine lock every 30 s
- Category: idle
- Severity: medium
- Confidence: PLAUSIBLE
- Where: footage-sorter footage_sorter/engine.py:297-298, 518-547; moveplan.py:76-108, 272-283, 404-426
- What: `refresh_tree` runs `read_dest_tree(destRoot, depth 8)` every 60 s forever: one `scandir` per directory down to depth 8 (every file name in each directory is read even though only directories are kept), then `json.dumps` + sha1 of the whole tree. `refresh_leaves` runs every 30 s and, when time folders are on, calls `assigned_dest_abs_list` WHILE HOLDING `self.lock`; that calls `canonical_dest` once per unfulfilled assignment (not per distinct dest), and each call does a sorted `scandir` of every path segment.
- Cost / failure scenario: today's pool scan saw 77,727 files under /pool; Projects at depth 8 is most of them, so ~1,440 full-tree listings/day (estimated tens of thousands of dirents and a few hundred ms CPU each). At 500 projects / 500k files the walk is ~7x larger and still every minute. The leaf refresh with e.g. 2,000 pending assignments x 4 segments = 8,000 `scandir`s every 30 s inside the lock that every edit, `/api/state` build and `/api/desttree` needs.
- Evidence: read; cadences from `start()` lines 297-298. Not timed on the pool (rule: no NAS access).
- Ledger: new
- Suggested change: walk only on demand plus a cheap change check (root mtimes of the first two levels, or after a move/scan/ingest, which already call `refresh_tree`), lengthen the timer to ~10 min; in `assigned_dest_abs_list` dedupe the sanitised dests before `canonical_dest` and pass a shared `seen`, and take the lock only to copy the manifest's dests.
- Effort / risk: S effort; low risk

### sorter-py-8 - /api/desttree: the full tree deep-copied under the engine lock and re-sent every 15 s per open tab, no ETag
- Category: perf
- Severity: low
- Confidence: CONFIRMED
- Where: footage-sorter footage_sorter/engine.py:1346-1351; public/app.js:479, 492-506, 4540
- What: every open sorter tab polls `api/desttree` every 15 s. Each call holds `self.lock` while it `copy.deepcopy`s the whole destination tree and merges planned folders, then sends the full JSON with `no-store`; the browser computes a signature and usually throws it away. The other big bodies (`/api/state`, `/api/clips`, `/api/dest/*`) already have versioned ETags and 304s; this one does not, though `v["dests"]` and `v["manifest"]` exist.
- Cost / failure scenario: 4 tabs = 16 deep copies and full serialisations per minute of a tree with thousands of nodes (estimated 10-100 ms each), each blocking edits for its duration; at 20 editors with the page open, 80/min.
- Evidence: read both sides.
- Ledger: new
- Suggested change: serve it through the existing `Served`/ETag path keyed on `(v["dests"], v["manifest"])`, so an unchanged tree is a 304 with no copy.
- Effort / risk: S effort; low risk

### sorter-py-9 - The catalog (25 MB) is rewritten and fsynced at least twice per scan even when nothing changed
- Category: perf
- Severity: low
- Confidence: CONFIRMED
- Where: footage-sorter footage_sorter/catalog.py:564-565, 386 (`seenAt`), engine.py:913-918, 989-991, 1041-1043, 1420-1422
- What: `reconcile_journal` sets `dirty = True` unconditionally, even when the journal had no new bytes; `link_scan`/`set_location` stamp `seenAt = now` on every location, so every scan dirties every linked entry. `run_scan` therefore saves the catalog in `reconcile_moves` and again in `link_staging_scan`, both under `self.lock`, and `plan_moves` saves it again via `_link_plan_clips`.
- Cost / failure scenario: per scan: clips.json (32 MB) + 2 x catalog.json (25.7 MB on creator-1's copy) written with fsync = ~83 MB, plus the json.dumps of the catalog (~0.1 s each per the module's comment) inside the lock. Scans run on demand, after every ingest and after every move. Also fills the nightly `state-<day>` backup copies with a new catalog every day.
- Evidence: read; file sizes from E:\Projects\Editing\footage-sorter\data.
- Ledger: new
- Suggested change: set `dirty` in `reconcile_journal` only when the offset moved or a location changed; do not dirty on a `seenAt`-only refresh (or keep `seenAt` out of the persisted document and update it once per scan); save once at the end of `run_scan`.
- Effort / risk: S effort; low risk

### sorter-py-10 - Move plans accumulate forever, in memory and on disk, and every scan walks all of them
- Category: leak
- Severity: low
- Confidence: CONFIRMED
- Where: footage-sorter footage_sorter/engine.py:1381-1383, 949-954, 994-1008; web.py:342-343
- What: every Plan press (including blocked plans and previews) stores the full plan (all entries) in `self.moves` and in `data/moves/<id>.json`; nothing removes either. `reconcile_moves` (every scan, every move end, the reconcile route) concatenates the entries of every plan ever made into `plan_entries` and walks them again in `_executed_entries`; `/api/moves` sorts and returns all of them.
- Cost / failure scenario: a plan of all pending assignments is thousands of entries (~400 B each); tens of plans a day over weeks of uptime = tens to hundreds of MB resident and a growing per-scan loop. Memory is reset only by a restart; the disk files never are.
- Evidence: read.
- Ledger: new
- Suggested change: keep only the newest N plans (or those not in a terminal state from the last 24 h) in memory, and prune `moves/*.json` older than 30 days; `_withheld_entries` already carries what restart-safety needs.
- Effort / risk: S effort; low risk

### sorter-py-11 - The thumbnail and strip cache has no cap and no pruning
- Category: disk-growth
- Severity: low
- Confidence: CONFIRMED
- Where: footage-sorter footage_sorter/thumbs.py:177-199, 493-533
- What: thumbnails and strips are keyed by recording and never deleted except old-version strips. Clips that leave the library (deleted, archived, cards dismissed) keep theirs.
- Cost / failure scenario: estimated ~20 KB thumbs + 15-61 KB strip per video clip: ~2 GB at today's ~36k clips, ~9 GB at 150k clips (500k files), on the apps dataset that also holds the dashboard's DB.
- Evidence: read.
- Ledger: new
- Suggested change: in `backfill`, which already lists both folders, remove files whose key is in no current clip and no catalog entry (older than N days, through `guard.remove`).
- Effort / risk: S effort; low risk

### sorter-py-12 - The scan's content memo is in memory only: every restart (every deploy) re-runs ~2,264 ffprobes and ~7,600 XML/WAV reads
- Category: perf
- Severity: low
- Confidence: CONFIRMED
- Where: footage-sorter footage_sorter/engine.py:174, 905-908; scan.py:510-528, 688
- What: `_scan_memo` caches ffprobe creation times, Sony XML and WAV headers by (path, size, mtime) but lives only in the process. The previous scan's results are already on disk in clips.json (per-clip `recordedAt`, `durationSec`, `umid`, with file sizes and mtimes).
- Cost / failure scenario: the first scan after each container restart spawns ~2,264 ffprobe processes (number from the module's own comment) over the pool; estimated 1-3 min of extra scan time and process churn per restart, scaling with the library.
- Evidence: read.
- Ledger: new
- Suggested change: seed the memo at load from clips.json (key the master's path/size/mtime to the stored values), or persist the memo beside clips.json.
- Effort / risk: S effort; low risk

## What is already good
- The mover itself: `renameat2(RENAME_NOREPLACE)` with an atomic hard-link / mkdir-claim fallback, EXDEV refused (never copy+delete), start/done journal per entry with recovery of a rename that lost its "done" line, a dry-run re-run inside the single non-blocking exec lock, and `same_file` proving identity byte for byte. Nothing in the package deletes a source file. Leave it.
- `/api/state`, `/api/clips`, `/api/dest/*`: versioned ETags, 304s, and pre-flushed deflate pieces so an edit does not recompress the 35 MB of clips.
- The ledger's scan protocol: chunks staged with `bump=False`, one-transaction delta at finish, attempt tokens, bounded gzip decode on the dashboard side.
- `WriteGuard`: atomic fsynced writes confined to the sorter's own folders.

## Coverage note
Not reached in the time box: audio_match.py, google.py, integrations.py, cardtracker.py, suggest.py, infer.py, timefolder.py, relocate.py, startview.py, autobackup.py (beyond its `_rd` use), the second half of ingest.py (drive copies, apply), ledger_import.py, migrate.py, and `_collation.py` / `jscompat.py` / `jsvalue.py` (the JS-compatibility port: whether ids and sort order still need it after the Node retirement was not assessed, so no streamlining finding is made). Event-loop blocking: web.py's async thumb/strip/proxy handlers do small local stats and a JSON read on the loop; judged negligible and not reported. Nothing was timed against a synthetic 20k-clip tree.

## OUT OF TERRITORY
- ccsync dashboard/src/ccsync_dashboard/sorter.py:233-260: `_inside_mover` opens a dashboard DB connection and reads every active project per moved file; fine at today's plan sizes, a per-entry cost at thousands of inside-Projects entries.
- footage-sorter public/app.js:479: the 15 s desttree poll (other side of sorter-py-8).
