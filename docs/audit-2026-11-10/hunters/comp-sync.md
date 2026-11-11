# comp-sync - companion sync lanes: sequencer, rclone lanes A/B, lane guard, Syncthing lane/admin, repath, originals, root guard
Files read (approximate coverage): sync/sequencer.py (~70%: the pass loop, _run_pass, _process_project, skip-ahead, lanes A+B, CR-381 plan, lane C turn, waits, bookkeeping), sync/rclone_lane.py (~35%: tuning/flags, filters, command builders, run_once, _build_command, _run_popen/_wait_loop/stderr reader, tally, hand-off, breaker accounting, trash/relocation entry points, orphan/size-mismatch/future-dated/stray scans, watchdog handler, _project_rel_for_path), sync/lane_guard.py (~45%: persistence, breaker check_remote/note_pass/in-flight credit, count_local_proxies), sync/syncthing_lane.py (check_once, key fallback, heal), sync/syncthing_admin.py (request surface), sync/repath.py (reconcile, ledger), sync/originals_lane.py (loop/cycle), root_guard.py (poll loop, probe cadence), skim of unopened_scan.py / originals_requests.py / drive_reminder.py cadences. KNOWN_BUGS CR-62, CR-381..383, bug-hunt-2026-08-21 ops-efficiency-1..4, bug-hunt-2026-09-18 dash-api-5 checked for overlap.
Probes run: count_local_proxies on a synthetic 32,000-file / 800-dir project (companion venv, warm cache): 61-99 ms per call; a scandir-only variant 45-57 ms. Everything else is from reading the code.

## Answer to the brief's per-pass question (steady state, nothing changed, N full ticks)

Per PASS (once): selection fetch (TTL'd, 30 s), shared + borrowed folder reconcile (local REST), repath reconcile (1 GET /rest/config), unpause sweep (1 GET /rest/config/folders), trash prune (gated to 6 h).

Per PROJECT per pass:
- Lane A: CR-381 SKIP = 0 processes; VERIFY (every 2 h) or FULL = 1 rclone `copy` (local walk + recursive NAS listing, pool 4 or 16) plus a whole-file rewrite of project_dirs.json.
- Lane B (never skipped): 1 `rclone lsf` (breaker probe, its own SSH login), 1 local os.walk (count_local_proxies), 1 `rclone sync` (recursive listing of EVERY NAS directory of the project, originals included, because `+ **/Proxy/**` cannot prune any directory; local walk; pool up to 16), 2 rewrites of lane_b_breaker.json.
- Lane C turn: ~8 loopback REST calls including 2 more full GET /rest/config, 1 PATCH of the folder config (always), folder_status + completion polls during the settle.
- Every 10th turn: structure clone (`rclone lsf -R --dirs-only`). Every 20th turn: orphan .partial listing + size-mismatch listing + local future-date walk + two TREE-WIDE local scans.

So the steady-state floor is 2 rclone processes, 1 recursive NAS listing and 2 local walks of each project per pass, all from lane B; CR-381 removed lane A's share. Redundant within a pass: count_local_proxies repeats the local walk rclone sync does a second later (cheap, measured 65 ms / 32k files, leave it); the 1+3N full-config reads; the tree-wide scans repeated N times on the orphan cadence (finding 3). Separately, the Syncthing lane's own 15 s poll runs 3 + 2N REST calls around the clock (finding 5).

## Findings

### comp-sync-1 - Lane B still spends a full-width SSH pool and a recursive NAS listing on every project every pass; CR-381's cheap half was never applied to it
- Category: perf
- Severity: medium
- Confidence: CONFIRMED (code path), cost estimated from CR-381's measurement
- Where: companion/src/ccsync_companion/sync/rclone_lane.py:3840-3852 (lane B always `tuning=self.tuning`), :4856-4867 (`list_remote_top` + `count_local_proxies` every lane B run), :623-638 (`for_verify`, lane A only, :3837); sync/sequencer.py:2705-2713 (lane B runs every turn, no plan)
- What: CR-381 gave lane A a SKIP/VERIFY plan and a narrow 4/4 pool for re-checks. Lane B has neither: each project's turn spawns `rclone lsf` (one SSH login for the breaker probe) and `rclone sync` with `--sftp-connections 16 --checkers 16`, and because the lane B filter's `+ **/Proxy/**` makes every directory potentially relevant, rclone lists every directory of the project on the NAS, originals included, to find the Proxy/ dirs.
- Cost / failure scenario: CR-381 measured the SAME pool flags on lane A at 100-180 SSH logins per 27-project pass (~4-7 per rclone), 1,600-1,950 logins an hour on one idle machine. Lane B on a machine with lane B running is the same order: 27 projects x (1 lsf + ~5 pool logins) per pass, a pass every ~6 min at the idle-backoff ceiling = roughly 1,000-1,600 logins/h and 540 rclone spawns/h per idle editor, plus 270 recursive SFTP walks/h on the NAS (estimated). At 20 machines x 30 projects that is ~20-30k logins/h against sshd's MaxStartups, which DEFAULT_SFTP_CONNECTIONS' own comment says the pool exists to avoid tripping.
- Evidence: read; CR-381 entry in KNOWN_BUGS (measured on DESKTOP-LQQ41TC, lane B parked there, so the measurement is lane A only); lane B's tuning is never narrowed anywhere (`grep for_verify` hits lane A only).
- Ledger: related to CR-62 (open: "the per-project change signal") and CR-381 (fixed, lane A only)
- Suggested change: two steps, both keeping every latch. (a) Now, small: when the subpath's previous lane B outcome was RUN_OUTCOME_NOTHING and nothing failed this pass, build lane B with `self.tuning.for_verify()` (4/4); a run that finds work still downloads it, only on fewer streams. The lsf probe, --max-delete, --min-age, --backup-dir and the breaker accounting are untouched. (b) The CR-62 signal: the dashboard already computes a per-project tree signature (`collector._dir_signature` -> `nas_inventory_state.tree_sig`); ship it (or a Proxy/-only mtime digest) on the selection reply and SKIP lane B when it is unchanged since the last clean lane B run, with a max age (like `lane_a_verify_seconds`) after which it runs anyway so a hand move on the NAS is still caught. Must not break: a SKIP is "found nothing" for CR-319 exactly as lane A's is, and an absent/unknown signature means FULL.
- Effort / risk: S for (a), M for (b); low / medium risk

### comp-sync-2 - CR-381's clean-project skip survives an untick/re-tick and a full <-> upload-only flip, so lane A skips files it has never looked at for up to 2 h
- Category: bug
- Severity: medium
- Confidence: CONFIRMED (code path)
- Where: companion/src/ccsync_companion/sync/sequencer.py:2808-2842 (`_lane_a_plan`, keyed only on subpath + slug), :1808-1853 (`_update_known_selection`, which detects a mode flip and a tick change but forgets nothing), :1955-1995 (`_prune_bookkeeping` prunes turn records and ages but not `_lane_a_clean` / `_lane_a_changed_at`), :1340-1360 (`notify_change` only marks slugs in the CURRENT selection); rclone_lane.py:3661 (`carries_everything` widens lane A's filter for an upload-only tick)
- What: a clean check records "this subpath, under the filter it ran with, had nothing to upload". Two real events invalidate it and neither clears it. (1) Full -> upload-only: lane A's filter widens from video-only to every file (GL-13), so the earlier "found nothing" says nothing about the WAVs, project files and GFX now in scope; the next turn SKIPs. (2) Untick, files written, re-tick: while unticked, `notify_change` cannot map the path to a slug, so no change time is recorded; on re-tick the old clean check and unchanged watcher epoch make the turn SKIP. Both hold until the clean check is `lane_a_verify_seconds` (7200 s) old.
- Cost / failure scenario: an editor flips a finished project to upload-only to get its non-video files onto the server (the documented use) and the files do not start for up to two hours, with the tray and the CR-319 record saying "found nothing". Same for a project re-ticked within two hours of its last clean run. No data loss (the removal gate runs its own dry run), but it is the CR-383 shape of "sat on the editor's disk and nothing said so", in code shipped 2026-11-05.
- Evidence: read; `_lane_a_clean` is written only by `_note_lane_a_check` and cleared only by `_forget_clean_checks` (resume, Sync now) and a non-clean run.
- Ledger: new (regression introduced by CR-381)
- Suggested change: in `_update_known_selection`, under the lock, drop `_lane_a_clean` entries for any slug whose mode changed or that left/entered the selection (compare old/new `_slug_to_item` and `_upload_only_slugs`, mapping slug -> subpath via `_item_rel` and the borrowed includes), and prune `_lane_a_clean` / `_lane_a_changed_at` in `_prune_bookkeeping` with the other per-slug state. Cheaper alternative with the same guarantee: store the filter mode in the clean-check tuple and treat a mismatch as FULL.
- Effort / risk: S; low risk

### comp-sync-3 - The "skipped, exists" alarm and the orphan .partial report hold only the LAST project scanned, so a clean project hides another project's mismatches for ~20 passes; the tree-wide scans run N times
- Category: bug
- Severity: medium
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/sync/rclone_lane.py:4199-4200 (`self._orphans = report`), :4268-4269 (`self._size_mismatches = report`), contrast :4453-4457 (`_future_dated_by_sub[subpath]`, already per project, with the comment saying why); sequencer.py:3095-3116 (`_maybe_scan_orphans` per project, ages all start together); app.py:7721-7724 (reports the single slot as `sync_guard.skipped_exists`)
- What: `refresh_orphan_report(subpath)` runs per project on the 20-turn cadence, and every project's age starts at None, so all N projects are scanned in the same pass, one after another. Each scan replaces the single report slot, so when the pass ends the report describes only the last project. A project with real size mismatches (a re-exported clip `copy --ignore-existing` will never re-upload, the "one silent data-loss shape on lane A" per SYNC-109) is reported for the minutes until the next project's scan, then replaced by that project's 0 and hidden until the next scan pass ~20 passes later, where it again survives only if it is scanned last. Inside the same call `scan_trash_dir(local_root)` and `_refresh_stray_projects()` are tree-wide and are repeated N times in that pass.
- Cost / failure scenario: 27 projects, project 3 has 4 stranded re-exports; the dashboard's skipped_exists alarm shows them for one project-turn every ~20 passes (~2 h at the idle cadence) and shows 0 the rest of the time, so the alarm effectively never stays up. Waste: N-1 redundant trash walks (up to 50,000 stats each) and marker scans per scan pass.
- Evidence: read; the future-dated report got the per-project fix in the same function family, these two did not.
- Ledger: related to dash-api-5 (bug-hunt-2026-09-18, dashboard side: the count was rendered as tree-wide); this is the companion side, not covered there
- Suggested change: key `_size_mismatches` and `_orphans` by subpath like `_future_dated_by_sub` (prune keys not in `known_rels_fn()`), and report the sum plus the per-subpath list (the dashboard already accepts `subpath`; an older dashboard reading `count` gets the sum, which is the honest number). Move `scan_trash_dir` and `_refresh_stray_projects` to a once-per-pass hook (or gate them on their own monotonic interval).
- Effort / risk: S-M; low risk (wire shape must stay readable by the current dashboard)

### comp-sync-4 - Every lane C turn PATCHes the folder's config even when it is already running, and reads the full Syncthing config three times per project
- Category: perf
- Severity: low
- Confidence: CONFIRMED (calls), PLAUSIBLE (Syncthing-side cost)
- Where: companion/src/ccsync_companion/sync/sequencer.py:3260-3267 (`_set_paused(slug, False)` unconditionally), :3332-3341 (the turn has ALREADY fetched this folder's config, `paused` included), :3416 (`_verify_current_folder_unpaused`: GET /rest/config), :3478-3479 (`_remote_device_ids`: GET /rest/config + /rest/system/status), sync/repath.py:462 (reconcile's GET /rest/config, called once per pass AND once per project from `_process_project`)
- What: SYNC-7 (2026-08-14) removed exactly this no-op write from the between-passes sweep ("essentially all of those writes were no-ops that still took Syncthing's config lock"), but the per-turn copy remains: a config-mutating PATCH on the 30 s write timeout for every project on every pass. Syncthing's config handler saves config.xml (atomic write) and broadcasts ConfigSaved on every PATCH whether or not anything changed. The same turn also pulls the whole config (every folder, every device) three times.
- Cost / failure scenario: N=27 at ~10 passes/h = 270 config commits/h plus ~810 full-config reads/h per idle editor (estimated); at 100 folders config.xml is on the order of 100-300 KB, so tens of MB/h of config rewrites and JSON parsing for no state change.
- Evidence: read; set_folder_paused is `PATCH /rest/config/folders/<id>` (syncthing_admin.py:498-501).
- Ledger: related to SYNC-7 (fixed for the sweep only)
- Suggested change: in `_lane_c_turn`, have `_reassert_folder_policy` return the folder dict it fetched and skip the unpause PATCH when `folder.get("paused") is False`; keep the PATCH when the fetch failed (None), which preserves the hand-pause / crashed-pass release and the halt check in `_set_paused`. Fetch `/rest/config` once per turn and hand it to repath's per-project check, `_remote_device_ids` and the verify step.
- Effort / risk: S; low risk

### comp-sync-5 - The Syncthing lane polls 3 + 2N REST calls every 15 s for the life of the process, including one "expensive" /rest/db/status per folder
- Category: idle
- Severity: medium
- Confidence: CONFIRMED (calls and cadence), cost estimated
- Where: companion/src/ccsync_companion/sync/syncthing_lane.py:248 (poll_interval 15.0, not configurable from app.py:2863), :706-882 (`check_once`: ping, connections, full config, then per expected folder `/rest/db/status` and `/rest/db/completion` per remote device), :991-1000 (fixed-interval loop)
- What: the poll is unconditional and fixed-rate: idle, nothing owed, Resolve busy, it still asks Syncthing for every folder's status and remote completion every 15 s. Syncthing's own REST documentation flags `/rest/db/status` as an expensive call to use sparingly and offers the events API (FolderSummary, FolderCompletion, StateChanged, FolderErrors) for exactly this.
- Cost / failure scenario: N=27 ticked projects (one remote device each): 57 requests every 15 s = ~13,700/h, ~330k/day per idle editor, each db/status and completion computed by Syncthing on the editor machine beside Resolve. N=100 at commercial scale: ~48,000/h. The sequencer's own lane C settle loop adds folder_status + completion every 5 s for the current project.
- Evidence: read; request count matches the SYNC-8 docstring's own "roughly 3 + 2N requests every 15 s".
- Ledger: new
- Suggested change: cheapest safe version: adaptive cadence, 15 s while the last verdict was syncing/error or a peer/connection change was seen, backing off to 60-120 s after two consecutive all-idle polls, reset by any sequencer turn or tray action. Better: one long-poll consumer of `/rest/events?events=FolderSummary,FolderCompletion,FolderErrors,StateChanged&since=<id>` keeping a per-folder cache, with the full per-folder poll kept as a reconciliation every few minutes. Must keep: the supervisor's liveness verdict (ping can stay at 15 s, it is cheap), the CR-278 heal, logic-sync-truth-3's progress token.
- Effort / risk: S for adaptive cadence, M for events; low / medium risk

### comp-sync-6 - Breaker and project-dir state files are rewritten every pass when nothing changed; the breaker persists the OLDEST 512 scopes and never prunes unticked ones
- Category: disk-growth
- Severity: low
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/sync/lane_guard.py:662-664 (`check_remote` persists on every successful probe), :775-783 (`note_pass` persists every pass, deleted=0 included), :538 (`dict(list(self._remote_counts.items())[:512])`); rclone_lane.py:4506-4524 (`_note_project_dir_seen` reads and rewrites the whole project_dirs map every lane A run, entries never pruned)
- What: two atomic JSON writes of lane_b_breaker.json per lane B run and one read+rewrite of the lane A project-dirs map per lane A run, whether or not any value changed (the map's `last_seen_at` changes by design). Separately, `_remote_counts` (the ONLY memory trigger 1 has of how big each scope's NAS listing was) is never pruned on untick, and the persisted copy is the first 512 keys in insertion order, so once a machine has ever synced 512 scopes (renames and borrowed subpaths count), every newer project's count is kept in memory only and is lost on restart, which is the window `sync-safety-8` says must not exist.
- Cost / failure scenario: 2N + N small file writes per pass (~810/h at N=27, each a create + rename in ~/.ccsync/state, AV-scanned on Windows): small. The 512 cap is a commercial-scale cliff: a long-lived machine past 512 scopes restarts and its first lane B pass on a newly ticked project cannot trip the "listed as EMPTY" rule.
- Evidence: read.
- Ledger: new
- Suggested change: in `_PersistedLatch._write_state`, skip the write when the payload equals `_persist_payload` and the last write succeeded (keeps the failure retry); persist the NEWEST 512 scopes (or prune `_remote_counts` to the live selection's scopes from the sequencer's prune) instead of the oldest. Throttle `_note_project_dir_seen` to once per project per day (it records a date) and prune entries not seen for 90 days.
- Effort / risk: S; low risk

## What is already good
- The stderr path is bounded end to end: RcloneRunTally keeps 200-line deques, the reader is joined with a ceiling, and the hand-off reuses the same tally; no unbounded line buffer survives a run.
- The stall watchdog polls proc.wait at 30 s and the sequencer's waits are single Event.wait calls (no 50 ms spin); the idle backoff (1/2/5 x 60 s) and the 30 s selection TTL in selection.py work as described.
- count_local_proxies is cheap enough to keep as the breaker's denominator: 61-99 ms for a 32,000-file project (probe), against an rclone run that takes seconds.
- Repath's relink retry is throttled, the between-passes unpause sweep reads once and writes only what is paused (SYNC-7), and `_reassert_folder_policy` reads ignores before writing them.

## Coverage note
Not read in depth: rclone_lane.py's express path (7,100-7,664), trash relocation internals (5,399-5,730), route/remote_down plumbing, scan_size_mismatches_strict and the consolidate/removal-gate scans; syncthing_supervisor.py, shared_folders.py, borrowed_folders.py, server_locate.py, drive_swap.py, drive_reminder.py and unopened_scan.py beyond their cadences. No live measurement of Syncthing REST cost or SSH login counts (live processes off limits).

## OUT OF TERRITORY
- companion/src/ccsync_companion/app.py:6492-6493: a further folder_completion + folder_status pair per project on its own cadence, adding to finding 5's load.
- (in territory, not a finding) root_guard.py:123 + rclone_lane.py:1291-1318: `cmd /c dir` spawned every 60 s for the life of the process; deliberate MAC-12 out-of-process probe, ~1,440 spawns/day, cheap, leave it.
