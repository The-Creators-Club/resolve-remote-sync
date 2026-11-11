# comp-app - companion app.py (CompanionApp, its loops and accessors), __main__.py, startguard.py
Files read (approximate coverage): `companion/src/ccsync_companion/app.py` about 35%: LaneWatchdog (1050-1420), `__init__` skimmed for I/O and containers, `_build_lanes`/watcher wiring (2560-2690), root/out-of-tree/canon-relink handlers (3359-3730), the media-tree loop and everything it calls (4687-5243), P: mapping probes (5369-5437), `resolve_health` and readers (5563-5812), removable/eula/licence/site loops (6326-6940), `_start_lanes` (7076-7205), `sync_guard` + `disk_snapshot` + `ingest_staging_report` + `blocked_report`/`_blocked_candidate` (7704-8373), `_report_off_cycle`, lifecycle `start()` and every starter (10527-10960), LUT loop, identity loop, `shutdown()` head, `CompanionApp.run()` and module `run()` (12321-12767); the diff of app.py since 2026-11-01. `__main__.py` and `startguard.py` in full. Followed into: `tray._tray_snapshot` (the 2 s caller), `broll_ingest.staging_report`/`_dir_bytes`, `broll_server.ingest_staging_root`, `ingest_kinds.staging_root`, `drive_swap.current_p_target`, `eula.acceptance_problem`, `identity.valid`, `crash_report.crash_summary`, `broll_standins._load_locked`, the start() of the jointly started workers.
Probes run (all under scratchpad\comp-app, companion venv):
- `python -X importtime -c "import ccsync_companion.app"` x4: 187-195 ms cumulative (warm); `broll_ingest` 97 ms of it (`broll_server` 65 ms inside), `config` 32 ms, `tkinter` 9 ms.
- `_dir_bytes` (the walk `sync_guard()` runs per retained staging batch) over a synthetic 3-batch / 1,500-file staging tree on local NVMe, warm cache: 17.3 ms per `ingest_staging_report`-equivalent call.
- `subprocess.run(["net","use","Q:"])` and `["subst"]` with CREATE_NO_WINDOW: 13.4 ms and 12.6 ms wall per spawn.
- `config.load_config` + `validate_config` on a scratch config with a fake HOME: 0.15 ms + 0.02 ms (start-up config work is not a cost; not reported).

## Findings

### comp-app-1 - The tray rebuilds `sync_guard()` every 2 s, and that walks every retained ingest staging folder on the sync drive
- Category: perf
- Severity: medium
- Confidence: CONFIRMED (cost path and measurement); the wedge on a not-answering drive is PLAUSIBLE (read, not reproduced)
- Where: app.py:7749 (`sync_guard` -> `ingest_staging_report`, app.py:8069) -> broll_ingest.py:3834-3839 (`staging_report` -> `_dir_bytes`, an `os.walk` + `getsize` per file, broll_ingest.py:692); caller tray.py:3075 inside `_tray_snapshot`, run by the tray refresh loop every `refresh_interval = 2.0` s (tray.py:5165, 5230); also reporter.py:1020 on every report tick (5 s while a lane is active, `dashboard_report_interval` otherwise)
- What: `sync_guard()` is the report section, but the tray also calls it whole on every 2 s refresh. One of its ~26 sections, `ingest_staging`, recursively walks and stats every finished/held staging batch directory of both ingest kinds on every call. The staging root is `<local_root>/Assets/B-roll Archive/.ingest` (broll_server.py:1649-1669) and the music one is under the music mount in local_root, i.e. ON THE SYNC DRIVE; batches are kept `broll_ingest_staging_retention_days = 7` days, and a held drop (`held_for_base_rig`) is never pruned at any age. `disk_snapshot()` three methods below is memoised to the heavy cadence for exactly this reason ("two stat-family syscalls against a drive that has just stopped answering is exactly the hot path SYNC-2 is about"); the staging walk, hundreds to thousands of syscalls on the same drive, is not.
- Cost / failure scenario: runs 43,200 times a day from the tray plus 1,440-17,280 times from the reporter, for 7 days after every ingest drop (for ever for a held one). n today: one drop of 100 clips is about 500 files of staging (original + browser proxy + editing proxy + thumbs + json); three drops in a week = 1,500 files = 17 ms per call measured on local NVMe warm, i.e. ~0.9% of a core continuously on the tray thread plus ~0.35% on the reporter, beside Resolve. On an external USB SSD with a cold cache or on the base rig (no `music_ingest_staging_dir` override, so music staging sits on the SMB share; PRAC-31 notes the b-roll override is a hand edit too), each `getsize` is a network or USB round trip: estimated 0.3-1 s per call at 1,500 files, so the tray refresh thread spends a large share of its life walking. Worst case: the drive enters ROOT_NOT_ANSWERING (SYNC-2's wedged mount), `os.path.isdir`/`os.walk` blocks, and BOTH the tray refresh thread and the reporter thread park inside `sync_guard()` - the tray stops updating and the machine stops reporting at exactly the moment `sync_guard.root_state = not_answering` is the thing the dashboard needs to hear. At commercial scale (an ingest station dropping several batches a day) n is 10k+ files and the walk is seconds per call.
- Evidence: read the full chain listed under Where; `_staging_entries` excludes only the running batch; `sync_guard` calls `ingest_staging_report()` unconditionally (no root-state check, no TTL); probe timing above.
- Ledger: new (KNOWN_BUGS 7107 documents the section; bug-comp-broll-4 / CR on held staging is related - the held entries are what keep this walk alive after the 7-day retention)
- Suggested change: memoise `ingest_staging_report()` on the app the same way `disk_snapshot()` is (TTL = `dashboard_report_interval`, floor 30 s), invalidate it from `clear_finished_ingest_staging()` and from the ingestors' batch-end/prune paths, and return the last value (or {}) without touching the disk while `_root_state` is not `present`. Better still, let each ingestor keep a running byte count per staging entry (it writes every byte that lands there) so the report never walks. Must not break MEDIA-3: the space refusal (`_space_refusal`) still needs an exact number at refusal time, so it can keep calling the walk directly.
- Effort / risk: S effort; low risk

### comp-app-2 - Two `net use` (+ `subst`) probes per media-tree tick when one is enough
- Category: idle
- Severity: low
- Confidence: CONFIRMED
- Where: app.py:5210 then 5217 (`_media_tree_loop`: `_refresh_media_tree_once()` -> `_classify_pool_once()` -> `p_mapping_mode()` at app.py:5047, then `_refresh_p_mapping_mode()`); probe at app.py:5383/5435 -> drive_swap.py:309-340
- What: with Resolve open, every media-tree tick first runs the pool classification, which asks `p_mapping_mode()`; its 10 s memo was set 120 s ago by the previous tick, so it spawns a fresh `net use P:` (and `subst` when `net use` fails, i.e. on every subst-mapped editor rig from the CCSync-SubstP logon task). A few seconds later the same tick calls `_refresh_p_mapping_mode()`, which spawns the identical probe again unconditionally.
- Cost / failure scenario: 720 ticks/day x 2 probes x (1 spawn on a net-use rig, 2 on a subst rig) = 1,440-2,880 process spawns a day on every Windows editor machine while Resolve is open, where 720-1,440 suffice; measured 13.4 ms (`net use`) + 12.6 ms (`subst`) wall per spawn, so ~19-38 s of spawn wall time a day of which half is redundant. At 20 machines it is pure duplicated fork load beside Resolve.
- Evidence: the loop order at app.py:5208-5217 and the uncached `p_mapping_mode()` call at app.py:5047; spawn probe above.
- Ledger: related to COMP-CORE-6 (2026-08-14), which deliberately moved the refresh onto this tick; this keeps that contract and removes the second probe
- Suggested change: call `self._refresh_p_mapping_mode()` at the TOP of the tick, before `_refresh_media_tree_once()`, so the classification's `p_mapping_mode()` reads a seconds-old cache; or have `_classify_pool_once` use `p_mapping_mode_cached()`. Must not break: a swap (`swap_p_to_server`/`_local`) still invalidates the cache, and the classification must still refuse while P: points at the server.
- Effort / risk: S effort; low risk

### comp-app-3 - Seven workers share one `try` in `start()`; one raising silently skips the rest under the wrong name
- Category: resilience
- Severity: low
- Confidence: CONFIRMED (structure); PLAUSIBLE (trigger)
- Where: app.py:10620-10646
- What: `proxy_generator`, `broll_ingestor`, `music_ingestor`, `job_runner`, and since 2026-11-09 `sorter_cards`, `sorter_volumes` and `ledger_outbox` are started inside ONE `try`, whose `except` logs "failed to start the proxy generator". The comment 25 lines below states the rule this violates ("Each behind its own try ... the rule is the general one, not that one value"), and the Timeline Cards role and youtube importer right after it each got their own `try` for that reason.
- Cost / failure scenario: any exception from an earlier starter (a `RuntimeError: can't start new thread` on a machine near its handle limit beside Resolve, an `enabled` property that raises on a future hand-edited value, a constructor that half-succeeded) leaves every later worker down for the life of the process, with a log line naming the proxy generator. E.g. the job runner failing to start silently takes the field-backup ledger outbox and the card reporter with it; nothing restarts them (none is supervised by LaneWatchdog).
- Evidence: app.py:10620-10646 read; the new sorter starters arrived in f8102a4 / 06f033b.
- Ledger: new
- Suggested change: move these seven into the existing `(name, starter)` tuple loop at app.py:10671 (each gets its own try and its own name in the log). No behaviour change on the happy path.
- Effort / risk: S effort; low risk

### comp-app-4 - `sync_guard()` is 282 lines of 26 hand-written try blocks, rebuilt in full by two threads; a table would make per-section cadence possible
- Category: streamline
- Severity: low
- Confidence: CONFIRMED
- Where: app.py:7704-7985 (and its readers tray.py:3075, reporter.py:1020; `blocked_report` writes `self._blocked_since` from both threads, app.py:8174-8179)
- What: every section is the same shape (call a getter, swallow and log, add the key when non-empty or always), written out 26 times; 29 distinct bug ids are cited inside it, more than any function in the file except `__init__` (921 lines, 42 ids). Because it is one monolith, every consumer pays for every section at the consumer's own rate: the tray rebuilds the whole report section every 2 s although it renders a handful of keys, and there is no place to give an expensive section (comp-app-1) a slower cadence without another hand-written memo.
- Cost / failure scenario: 43,200 full rebuilds a day from the tray (two `eula_accepted.json` reads per tray tick counting the snapshot's own, two stall-file reads, two stand-in ledger stats, the staging walk) for data the reporter already assembles every 5-60 s; ~280 lines that every new report key touches.
- Evidence: line counts and bug-id counts from an AST/grep pass over app.py (`__init__` 921 lines / 485 comment lines; `sync_guard` 282 / 126; `_build_lanes` 218 / 124).
- Ledger: new
- Suggested change: express the sections as a table of `(key, getter, emit_when, ttl_seconds)` with one loop doing the isolation (saves roughly 150 lines and makes "never raises" structural), give the walking/file-reading sections a TTL, and have the tray read the last built guard when it is younger than its own 2 s tick. Must keep: every section independently fault-isolated, the always-present sections (`standins_placed`, `halt`, `upgrade`, `loopback`, `root_state`, `resolve_health`) always present, and `blocked` computed LAST from the built picture.
- Effort / risk: M effort; low risk (pure restructuring with the existing sync_guard tests as the pin)

## What is already good
- The main thread's 1 s `Event.wait` on Windows, the 60 s identity and watchdog ticks, the 15-minute LUT and site loops and the 30-minute unopened sweep are all cheap and all stop on `_stop_event`; the watchdog's restart ledger is bounded (`_WATCHDOG_EVENTS_KEPT`, 24 h prune) and its log is once per change of answer.
- Containers on the app object that look unbounded are bounded: `_popup_snooze` is pruned per poll, `_canon_relink_pending` is de-duplicated and capped at 1,000, `_media_presence_cache` is rebuilt per pass (only positives kept, 900 s TTL), `_removal_overrides` is a `deque(maxlen=20)`, `_blocked_since` holds one key.
- `p_mapping_mode_cached()` for the tray, `disk_snapshot()` and `crash_summary()` memoisation, and the stand-in ledger's mtime stamp are the right pattern; leave them.
- Startup: `import ccsync_companion.app` is ~190 ms warm and config load/validate is sub-millisecond; `startguard` is import-light by design and every write is tmp+replace. Nothing here is worth optimising before the onefile extraction itself.
- No lock in app.py is held across network or disk I/O except the watchdog's tiny JSON write (outside its lock) and `_broll_server_lock` around a loopback bind, which is the intended single-flight.

## Coverage note
Not read: `__init__` beyond an I/O/container skim, consolidate (`_consolidate_project_inner`, 4203-4600), file moves (`_apply_file_moves`), upgrade/auto-update paths, removal gate (`removal_blockers`), diagnostics builders, `_shutdown_teardown` beyond its head, the root-guard handlers, Settings/tray action methods. No thread count was taken from a live process (the live companion was not touched). The media-tree pool walk's own cost every 120 s (the dominant idle cost of this file while Resolve is open) is resolve_bridge's to measure.

## OUT OF TERRITORY
- companion/src/ccsync_companion/resolve_bridge.py + app.py:5241: the whole-pool walk repeats every `media_tree_refresh_interval` (120 s) with no change check; a project-library mtime or pool-count short-circuit would turn most passes into a no-op - worth a measurement by the resolve_bridge hunter.
- companion/src/ccsync_companion/proxy_relink.py:379: `_GEOMETRY_VERDICTS` is a module-level dict keyed per (file, stored frames) with no eviction for the life of the process.
- companion/src/ccsync_companion/broll_standins.py:771: the stand-in ledger has only an explicit `forget()`; nothing prunes it, and `placed_report()` sorts/normalises all of it on every `sync_guard()` call.
- companion/src/ccsync_companion/sorter_cards.py:647, sorter_volumes.py:65, ledger_outbox.py:424: the same "tolerant bool" parse written three times, and both scanners default ON on every machine, so each one's `scan_seconds` drive scan is an idle cost on machines whose dashboard has no sorter.
- companion/src/ccsync_companion/fixer.py:363: `list_project_dirs` walks `local_root/Projects` (over SMB on the base rig) on every unopened-projects sweep.
