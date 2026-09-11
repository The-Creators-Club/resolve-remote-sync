# comp-sync - the companion sync engine: what goes up, what comes down, what is never deleted

Files read (with approximate coverage):
- `companion/src/ccsync_companion/sync/rclone_lane.py` (~60%: the whole
  097f5a3..HEAD diff, the lane A filter rules + `path_matches_lane_a_filter`,
  the express door, `_wait_with_watchdog` / `_record_stall` / `abort_run`,
  `run_once`/`_run_once_locked`, the breaker stand-down, `size_mismatch_samples`)
- `companion/src/ccsync_companion/sync/sequencer.py` (~70%: the whole diff, the
  selection validators, upload-only, `_process_project`, `_run_lanes_a_and_b`,
  `_lane_c_turn`, `project_status`, `_repath_blocked_by_slug`, the loop's
  failure handling)
- `companion/src/ccsync_companion/sync/repath.py` (100%)
- `companion/src/ccsync_companion/sync/shared_folders.py`,
  `borrowed_folders.py`, `base.py` (100%), `syncthing_lane.py`,
  `syncthing_supervisor.py` (100%), `syncthing_admin.py` (~40%)
- `companion/src/ccsync_companion/sync/lane_guard.py` (100%)
- `companion/src/ccsync_companion/file_moves.py`, `selection.py`,
  `manifest.py`, `watcher.py`, `consolidate.py` (100%)
- `companion/src/ccsync_companion/drive_reminder.py`, `drive_swap.py`,
  `root_guard.py` (~90%)
- Both sides of the wires: `dashboard/src/ccsync_dashboard/api.py` +
  `db.py` file-move halves, `companion/src/ccsync_companion/app.py` and
  `tray.py` consumer sites, `KNOWN_BUGS.md`, `docs/FILE_MOVES.md`,
  `docs/UPLOAD_ONLY_TICK.md`, `docs/SYNC_SAFETY.md`.

Tests run (companion venv, territory files only):
- `tests/test_sequencer.py tests/test_upload_only.py -q` -> 108 passed
- `tests/test_rclone_express.py tests/test_rclone_filters.py tests/test_sync_sequencer_policy.py -q` -> 170 passed
- `tests/test_lane_guard.py tests/test_drive_reminder.py -q` -> **1 failed, 123 passed** on the first run, 124 passed on four reruns (see comp-sync-15)
- `tests/test_borrowed_folders.py tests/test_repath.py tests/test_shared_folders.py tests/test_syncthing_lane.py tests/test_syncthing_supervisor.py tests/test_syncthing_admin.py -q` -> 221 passed
- `tests/test_file_moves.py tests/test_selection.py tests/test_manifest.py -q` -> 111 passed

## Findings

### comp-sync-1 - a latch whose write fails is in-memory only, and nothing retries or says so
- Severity: high
- Confidence: CONFIRMED (mechanism read end to end; needs ENOSPC/EACCES to fire)
- Where: `companion/src/ccsync_companion/sync/lane_guard.py:173` (`_write_json` returns False), and every `_persist_locked()` caller: `lane_guard.py:426`, `:447`, `:495`, `:826`, `:1204`
- What: `_write_json` degrades a failed write to one `log.warning` and a `False` return. No caller inspects the boolean, nothing retries, nothing surfaces it. Once lane B is tripped it stops running, so `note_pass`/`check_remote` never get another chance to persist the latch.
- Failure scenario: the sync drive fills (exactly the condition `DiskFloorLatch` exists for, and plausible when `.ccsync-trash` is allowed up to 50 GB). The breaker trips on a bad pass, `tmp.write_text` fails with ENOSPC, `lane_b_breaker.json` keeps its old "not tripped" content. The editor restarts the tray - the first thing anyone does - and lane B resumes moving files into the trash, with the breaker that stopped it gone. The same hole covers `HaltState` (a fleet halt not persisted) and `DiskFloorLatch`.
- Evidence: read `_write_json` and all five `_persist_locked` call sites; there is no retry timer in the module and no `sync_guard` field for a persist failure. CLAUDE.md: "Never make a safety latch in-memory-only."
- Ledger: related to CR-48 (which fixed the torn-write half, not the failed-write half)
- Suggested fix: on a `False` return from a trip/engage/park persist, raise a visible alarm (tray balloon plus a `sync_guard` field) and retry on the next tick; also make the tmp name process-unique (`root_guard.write_volume_record` already uses `.{os.getpid()}.tmp`) so two companions mid-upgrade cannot replace each other's partial tmp into a live latch.

### comp-sync-2 - `2 ** (attempts - 1)` overflows, and the shared/borrowed reconcile then dies for the life of the process
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/sync/shared_folders.py:106` (`FolderProblems.note`) and `companion/src/ccsync_companion/sync/syncthing_supervisor.py:760` (`backoff_seconds`)
- What: both compute `START * (2 ** (attempts - 1))` and only then clamp with `min(..., CAP)`. `attempts` is unbounded, and in the supervisor it is PERSISTED in `syncthing_supervisor.json` and reset only when the API answers. At `attempts >= 1025` the multiplication raises `OverflowError: int too large to convert to float`.
- Failure scenario: (a) a `not-offered` LUT library retried every 30 min reaches 1024 attempts after ~21 days of tray uptime; `note()` then raises INSIDE `reconcile`'s `try`, whose `except` arm calls `note()` again and raises out of a method whose docstring says "Never raises". `Sequencer._reconcile_shared_folders` catches it at DEBUG, so accepting offers, re-asserting `.stignore` and unpausing after a halt become a permanent silent no-op for both the shared AND borrowed managers. (b) a machine whose Syncthing cannot start accumulates attempts across restarts on disk; after ~7 days `_note_unreachable` raises on every poll, `tick` swallows it as "supervisor: tick failed" every 15 s, and no further restart is ever attempted.
- Evidence: from the companion venv - `backoff_seconds(1024) -> 600.0`, `backoff_seconds(1025) -> OverflowError`; `SharedFolderManager.reconcile()` after 1024 notes -> `reconcile() RAISED out: OverflowError`.
- Ledger: new (SYNC-101 / the supervisor's own backoff)
- Suggested fix: clamp the exponent (`min(attempts - 1, 20)`) in both places, and make `reconcile`'s `except` arm not re-enter the thing that just threw.

### comp-sync-3 - the SYNC-101 folder problems never reach the editor they were written for
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/sync/syncthing_lane.py:568` (the early `return` for an empty `expected`) and `:727` (the SYNC-101 block that never runs); producer docstring at `shared_folders.py:9`
- What: the only delivery path for `FolderProblems` sentences is `SyncthingLane.check_once`, which appends `problems[0]` to `status.detail` at the very END of the method. Every early `return` above it skips the block, including the "no project folders to check yet" branch taken when `expected_folder_ids_fn()` is empty. That fn is `Sequencer.expected_folder_slugs()` (sequencer.py:760), which is the PROJECT selection only and never names `assets-luts`, `assets-stills` or a borrowed lender.
- Failure scenario: an editor with zero ticked projects (or all of them upload-only) whose LUT library the server has never shared. `shared_folders.py`'s own docstring says the manager "must be online even for an editor with zero projects ticked, which is exactly the state in which the sequencer does nothing at all" - and in that state the sentence "Assets/Luts (LUT library) has not been shared with this computer yet. Ask your admin to approve it." reaches no tray line, no detail, nothing. The exact silence SYNC-101 was written to remove.
- Evidence: ran the real class from the companion venv: `SyncthingLane(..., expected_folder_ids_fn=lambda: [], shared_folder_problems_fn=lambda: ['The LUT library has not been shared...'])`, `check_once()` -> `state=idle detail='no project folders to check yet' last_error=None`.
- Ledger: new (the wiring half of CR-167/CR-168, both recorded FIXED 2026-09-04)
- Suggested fix: compute `problems` before the branch tree and apply it in `_with_path_detail` on every status this method builds (at minimum the empty-`expected` and paused branches).

### comp-sync-4 - `shared_folder_problems()` and `repath_events()` on the app object have no reader at all
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/app.py:4858` and `app.py:4872`; producers at `sequencer.py:868` / `sequencer.py:919`
- What: CR-167's ledger entry says these were added "so the tray (C1) and the Settings window (C1b) had something exact to render and the dashboard something exact to parse", and `repath.py`'s own comment says the ledger is "kept where the tray and the Settings window can read it" and reaches "the fleet grid" "through the report". Neither method has a caller outside its own definition and a contract test. `tray.py`'s snapshot builder pulls the sibling CR-167 producers (`size_mismatch_samples`, `broll_failed_items`, `jobs_status`, ...) at `tray.py:2718` but not these two; `reporter.py` and `settings_window.py` mention neither.
- Failure scenario: an admin renames a project on the server; the companion moves the editor's copy, records "Resolve reconnects the clips next time you open that project", persists it to `repath_events.json` - and no human surface anywhere shows that sentence. A problem is computed, persisted, and still nobody is told.
- Evidence: `grep -rn "shared_folder_problems\|repath_events" companion/src/ccsync_companion` returns only app.py's own definitions, the lane wiring at `app.py:2134` and sequencer.py.
- Ledger: new (regression of the CLAIM in CR-167/CR-168, both recorded FIXED)
- Suggested fix: add both to the tray snapshot `_get(...)` block and to the reporter payload beside the existing `sync_guard` sections.

### comp-sync-5 - a blocked repath's "not syncing" sentence can never be cleared
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/sync/repath.py:356` (the blocked `record`), `repath.py:341` (the `continue` when `actual == expected`), `companion/src/ccsync_companion/sync/sequencer.py:936` (`_repath_blocked_by_slug`)
- What: a blocked repath writes `moved=False` into the PERSISTED ledger, and `_repath_blocked_by_slug` keeps showing its sentence on the project row until a `moved=True` event for the same slug appears. `reconcile` records `moved=True` only on a pass that actually finds a path mismatch AND moves it; when the mismatch stops existing by any other route, no clearing event is ever written, and the ledger survives restarts. `RepathLedger.record`'s dedup key is `(slug, old, moved)`, so a blocked row is never replaced by anything but another blocked row for the same `old`.
- Failure scenario: the move is blocked because Resolve holds a handle (the branch's own comment calls this the routine one). Either the admin undoes the rename on the NAS, or the editor does the natural thing and unticks/re-ticks the project so it is accepted fresh at the correct path. From then on `actual == expected`, `reconcile` `continue`s, and `project_status()` shows that project **blocked** with "<name> is not syncing because CC Sync could not move its folder. Your files are safe where they are." forever, for a project that is syncing normally.
- Evidence: scratch script against the real `ProjectRepather` with a `move_fn` that raises OSError, then a second `reconcile` with the rel renamed back:
  `after blocked: paused = {'s1': True} ledger= [('s1', False)]`
  `after rename-back: paused = {'s1': True}` / `ledger still blocked: [('s1', False, '2026/New is not syncing because CC Sync ')]`
- Ledger: new (SYNC-102)
- Suggested fix: clear any blocked event for a slug whose folder now sits at `expected` on the `actual == expected` path, and age blocked events out.

### comp-sync-6 - `retry_pending_relinks` walks Resolve's media pool N+1 times per pass, for 30 days
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/sync/repath.py:319` (called at the head of `reconcile`), `companion/src/ccsync_companion/sync/sequencer.py:1102` and `sequencer.py:1901` (`_reconcile_paths` is called once for the whole selection AND once per project)
- What: `retry_pending_relinks` does one full `resolve_bridge.get_media_pool_items()` walk per pending event, and its docstring claims it runs "once per sequencer pass". It does not: `_process_project` calls `_reconcile_paths([item])` for every project, so the cost is `(1 + N_projects) * N_pending` media-pool walks per pass. An event only retires when a walk actually finds clips at the old path (`_relink` returns `True` or `None`, never `False`), so an event the editor never resolves is retried for the full `RELINK_WINDOW_SECONDS` (30 days). It also runs BEFORE the `get_config()` try, so it fires even with an empty selection and with Syncthing unreachable.
- Failure scenario: three project renames the editor has not opened yet, on a six-project plan -> 21 full media-pool enumerations per pass, each a `resolve_bridge.connect()` round trip holding `_API_LOCK`, every pass, for a month.
- Evidence: scratch script against the real `ProjectRepather` with a counting `relink_fn` and three pending events, simulating one pass (`reconcile` x7): `media-pool relink attempts in ONE sequencer pass: 21`.
- Ledger: new (SYNC-102)
- Suggested fix: throttle `retry_pending_relinks` to at most once per pass (a monotonic stamp in the repather), and dedupe the events walked so one `get_media_pool_items()` result serves all pending old paths.

### comp-sync-7 - a lane B the sequencer walked away from queues a new blocked thread every project turn, and the stale pass eventually runs
- Severity: medium
- Confidence: CONFIRMED (mechanism; trigger is the module's own documented "STILL running after the abort" branch)
- Where: `companion/src/ccsync_companion/sync/sequencer.py:1995` (unconditional `threading.Thread(target=_b).start()`), `sequencer.py:2041` (the short second join, then "continuing without it"), `companion/src/ccsync_companion/sync/rclone_lane.py:3334` (`with self._run_lock:` - a BLOCKING acquire)
- What: when the bounded join expires and `abort_run` cannot kill the child (a process in an uninterruptible kernel wait - the case the code says it is the backstop for), the sequencer continues while that thread still holds `_run_lock`. Every subsequent project turn starts another lane B thread, which blocks forever on that lock. Nothing checks whether the previous one is alive, and `_run_once_locked` re-checks `_stop_event`, the root and the breaker but never "is this subpath still the current project". So the comment's containment claim ("It cannot start another pass -- RcloneLane's `_run_lock` is still held by it") is only true while the wedge lasts.
- Failure scenario: the wedge clears after an hour (the SMB mapping comes back). The queued threads wake in order and each runs `rclone sync NAS:<its old subpath> -> local/<its old subpath>` back to back, uncoordinated with the live rotation - which is exactly the "lane B still writing into the project directory while the next project's repath moves it" hazard the join exists to prevent, plus N lane B passes racing the current one for the link and the disk. In the meantime one blocked daemon thread leaks per project turn, unbounded.
- Evidence: REPRODUCED. A scratch harness drove the real `Sequencer._run_lanes_a_and_b` over six project turns against a lane B whose `run_once` blocks on a held `_run_lock` and whose `abort_run` returns False (the uninterruptible-child case). Output: six "lane B did not finish within 421s on Projects/pN" / "lane B is STILL running after the abort (no child to kill) -- continuing without it" pairs, then `lane-b threads still alive after one 6-project pass: 6`. `run_once` acquires a plain blocking `threading.Lock` (`rclone_lane.py:3334`) and nothing between the walk-away log and the next `_run_lanes_a_and_b` records that lane B was abandoned. `lane_b_join_timeout(budget)` = `2*budget + 300 + 120`, i.e. 35 min per turn at the default 900 s rotation.
- Ledger: related to CR-91 / SYNC-1 (the bounded join that this is the other half of)
- Suggested fix: latch "lane B was abandoned on <subpath>" on the sequencer; while it is set, do not start another lane B thread (report the lane as stalled instead), and clear it when the abandoned thread finally returns. Additionally have `_run_once_locked` drop a pass whose subpath is no longer the sequencer's current project.

### comp-sync-8 - a restored drive-reminder episode ignores what the drive is doing now
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/drive_reminder.py:294` (`resume_remembered`), with `companion/src/ccsync_companion/app.py:2270` (`_on_root_absent`)
- What: SYNC-120 says a state episode "ends by itself when the state changes", enforced by `end_state_episode()` at the top of `_on_root_absent`. After a restart that guard runs BEFORE the episode is loaded (`_kind` is still `""`, so it is a no-op), and `resume_remembered()` then restores the persisted `not_answering` episode whatever the current root state is.
- Failure scenario: the drive wedges with nothing owed -> `drive_unfinished.json` holds `{summary: null, kind: "not_answering"}`. The editor quits CCSync and unplugs the drive. On the next start `_on_root_absent("absent")` calls `end_state_episode()` (no-op), then `resume_remembered()` -> the companion balloons "Your drive is still not answering, so nothing is syncing. Reconnect it or restart this computer." every 30 minutes about a drive that is in the editor's bag, and only plugging it in ever ends it.
- Evidence: scratch script reproducing the two runs: `after end_state_episode, active: False` then `resumed: True kind: not_answering`, with the wedged sentence emitted.
- Ledger: new (breaks SYNC-120's stated contract, KNOWN_BUGS:12390)
- Suggested fix: have `resume_remembered()` take the current root state and drop a restored state episode whose `kind` is not the state now being reported (or call `end_state_episode()` after the resume).

### comp-sync-9 - a drive that goes absent first and wedges afterwards never gets a SYNC-120 episode
- Severity: medium
- Confidence: PLAUSIBLE
- Where: `companion/src/ccsync_companion/app.py:2276`
- What: the wedged balloon and `begin_state(...)` sit inside `if not self._root_absent_announced:`, and `_root_absent_announced` is reset only in `_on_root_present`. So only the FIRST non-present state of an outage can open a state episode.
- Failure scenario: the drive is unplugged (calm "Sync paused: disconnected" balloon, announced=True); the editor replugs it and the filesystem wedges -> `root_guard` reports `not_answering`, `end_state_episode()` is a no-op, and no wedged balloon and no reminder episode is ever opened. The exact silence SYNC-120 removes, reached by the other order of events.
- Evidence: read `_on_root_absent` and `RootGuard.probe_once` - transitions between two non-present states do fire the callback, but the announce gate swallows them.
- Ledger: related to SYNC-120 (KNOWN_BUGS:12390)
- Suggested fix: gate the per-state balloon/episode on the state having CHANGED, not on `_root_absent_announced`.

### comp-sync-10 - `not-offered` is three different situations wearing one sentence
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/sync/borrowed_folders.py:356` and `:344`; `companion/src/ccsync_companion/sync/shared_folders.py:438`; the sentence at `shared_folders.py:151`
- What: `_accept` returns `"not-offered"` when the server genuinely has not offered the folder, when `pending_folders()` raised (a transient local Syncthing error), and - in the borrowed manager - when `self.halted()` is true so the offer is deliberately left pending. SYNC-101 now turns that one string into a user-facing sentence with a single fixed meaning: "<name> has not been shared with this computer yet. Ask your admin to approve it."
- Failure scenario: an editor presses the tray's pause, or an admin presses the fleet halt. On the next reconcile every not-yet-accepted borrowed folder records a `not-offered` problem, and the lane C detail tells the editor to chase their admin about a share that is fine and that their own halt is holding back.
- Evidence: read `_accept` in both managers - the `halted()` branch returns the same literal as the exception branch and the genuine-no-offer branch, and `reconcile` (borrowed_folders.py:181) feeds it straight into `FolderProblems.note` -> `problem_sentence`.
- Ledger: new
- Suggested fix: give the halt and the read-failure their own outcome strings so `problem_sentence` can say "syncing is stopped on this computer" / "CC Sync could not ask the sync engine about it", and record no problem at all for the halt case.

### comp-sync-11 - `relink_moved` compares Resolve paths raw, so a moved clip never relinks on a Mac
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/file_moves.py:243` (and its twin `companion/src/ccsync_companion/app.py:7568`)
- What: `relink_moved` keys the media-pool walk on `os.path.normcase(os.path.normpath(...))`, which on macOS folds neither case (APFS is case-insensitive) nor Unicode (listdir and Resolve give NFD while `old_local` is built from the dashboard's NFC `from_rel`). The same module's `_cmp_key`, twelve lines above, exists precisely because of both folds and cites CR-90 for it - so `moved_to()` was fixed and the function added in the same fix pass was not. This is also the relink `sync/repath.py` now depends on (SYNC-102).
- Failure scenario: an admin moves `Matej Šimalčík.mov` on the NAS; the Mac moves its copy fine (APFS lookups are normalisation-insensitive), then the media-pool walk matches nothing, `matched=False`, the ledger keeps `relink_pending` for 30 days, the clip stays Media Offline, and the tray toast promises "the clip will reconnect the next time you open that project in Resolve" - which never happens. Combined with comp-sync-6, those never-retiring events are also what drives the 21-walks-per-pass cost.
- Evidence: read `file_moves.py:120-150` (`_cmp_key`'s two documented folds) against `file_moves.py:243-262` and `app.py:7568-7573`; KNOWN_BUGS.md:3530 (SYNC-11) states the NFC/NFD premise and that APFS hides it from `apply_move`.
- Ledger: regression of CR-90's class in new code; breaks RES-10
- Suggested fix: route both functions' comparisons through `file_moves._cmp_key`, keeping `os.path.relpath`/`os.path.join` on the raw strings (those build a path something opens).

### comp-sync-12 - a case-only rename is recorded as done and never applied, then lane A recreates the old spelling
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/file_moves.py:184` (`apply_move` -> `_same_file` -> `_cmp_key`)
- What: `_cmp_key` folds case, so `_same_file(src, dest)` is True for a rename that only changes case. `apply_move` returns `(True, "already where the server has it", None)`, the ledger records DONE, and nothing is renamed on the editor's disk.
- Failure scenario: an admin fixes `clip.mov` -> `Clip.mov` through the project page. The NAS (ZFS, case-sensitive) renames it; every Windows/macOS editor answers "done" without touching their copy; 24 h later the `recent_excludes` window lapses and lane A - which never deletes and uses `--ignore-existing` - uploads the still-lower-case local file, recreating `clip.mov` beside `Clip.mov` on the NAS. That is the duplicate-at-the-cleared-path failure `docs/FILE_MOVES.md` exists to prevent.
- Evidence: ran `apply_move` on a real temp tree with `from_rel="clip.mov"`, `to_rel="Clip.mov"` -> `(True, 'already where the server has it', None)`, directory still listing only `clip.mov`. The dashboard permits the move (`api.py:2700`: `dest.exists()` is False and `src == dest` is False on a case-sensitive filesystem).
- Ledger: new
- Suggested fix: detect a case-only (or spelling-only) difference before the `_same_file` short-circuit and rename through a temporary name.

### comp-sync-13 - a refused canonical relink re-queues itself every 3 s behind a 15-minute rate limiter
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/watcher.py:459` (`rearm_non_canonical`) + `companion/src/ccsync_companion/app.py:2810`
- What: RES-19 made the watcher re-offer a NON_CANONICAL path on every poll once a relink fails. But `app._handle_non_canonical` de-dupes against `_canon_relink_pending` only on the `user_initiated` branch - its comment still says "both producers latch once per process", which RES-19 made untrue - so the unprompted path does a bare `extend(fresh)` each poll while `resolve_journal.allow_automatic` (900 s) refuses the burst.
- Failure scenario: a machine whose `canonical_prefix` is wrong, with 158 non-canonical clips: every 3 s poll re-offers all 158 and appends them again. Over one 900 s window that is ~300 appends of 158 items (~47,000 queued duplicates) plus 300 INFO lines; when the limiter lifts, the drain loop attempts all of them, one `replace_clip` (API lock + save point) each, and every failure re-arms the cycle.
- Evidence: scratch harness against the real `TimelineWatcher` - with no rearm the path is offered once in three polls; with a rearm after each attempt it is offered on every poll (4 offer batches for the same path). `app.py:2812` shows the de-dupe inside `if user_initiated:`.
- Ledger: new (RES-19 recorded FIXED at KNOWN_BUGS.md:12378; this is the consequence it did not account for)
- Suggested fix: move the `waiting` de-dupe out of the `if user_initiated:` block, and cap `_canon_relink_pending`.

### comp-sync-14 - the selection cache's `fetched_at` freezes at the first fetch of a process
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/selection.py:279` (`_write_cache`), read back at `selection.py:327`, rendered at `tray.py:670`
- What: `_write_cache` returns early when the response is byte-identical to the last one written (the normal case - a plan changes rarely), so the file's `fetched_at` stamp is never refreshed after the process's first successful fetch. `fetched_at()` falls back to that file whenever no live fetch has succeeded this run, which is exactly the post-restart window SYNC-110 was written for.
- Failure scenario: a companion runs 10 days with an unchanged plan, fetching every 30 s; the editor restarts the tray and the dashboard is briefly unreachable. The lane lines read "(sync plan from 10 days ago: the dashboard has not answered since)" about a plan that was live one minute earlier - the false-positive twin of the condition SYNC-110 added.
- Evidence: scratch script against the real `SelectionClient`: the cache stamp after the 2nd successful fetch is byte-identical to the 1st (`unchanged: True`) while the in-memory stamp advanced; a fresh client then reports the old stamp.
- Ledger: new (related to SYNC-110, recorded FIXED)
- Suggested fix: keep the write-on-change test on `response` only, but rewrite the file when the stored `fetched_at` is older than a floor (say an hour), or store the live stamp separately from the payload.

### comp-sync-15 - the tray's recovery-folder line reads two keys nothing produces, and a test pins the phantom shape
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/tray.py:2941` (`_trash_line`); producers at `companion/src/ccsync_companion/sync/rclone_lane.py:4032` + `:1236` (`scan_trash_dir`) and `lane_guard.py:1131` (`prune_trash`'s return)
- What: `_trash_line` reads `trash["path"]` and `trash["max_age_days"]`, but `sync_guard["trash"]` is `{**prune_trash(...), **scan_trash_dir(...)}` = `{removed, removed_bytes, kept, kept_bytes, at, count, bytes, truncated}`. Neither key is produced anywhere in the tree. The new `lane_guard.trash_summary()` that does carry them is reached only by `app.trash_summary()`, which has no caller in `companion/src` - and it passes the DEFAULT 14 days rather than the configured `trash_max_age_days`.
- Failure scenario: on a site with `trash_max_age_days = 3` the editor reads "Recoverable files in .ccsync-trash: 12.0 GB (40 files). Copies older than 14 days are removed automatically" - a wrong deadline plus the bare folder name instead of the path, which is precisely the defect SYNC-112 claims to have fixed.
- Evidence: read all four files; `grep -rn 'retention_days|max_age_days' companion/src` shows only the config read and the lane's own local. `companion/tests/test_settings_window.py:915` builds the guard dict by hand with `"path"` and `"max_age_days": 30`, so the suite pins a shape the producer never emits (brief rule 7).
- Ledger: new (SYNC-112, KNOWN_BUGS:12179)
- Suggested fix: have `RcloneLane._maybe_prune_trash` put `path` and `max_age_days=self._trash_max_age_days` into `self._trash_summary`, and build the test dict from the real producer.

### comp-sync-16 - `reminders_muted` identifies an episode by a float wall-clock stamp, and Windows ticks at 15.6 ms
- Severity: low
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/drive_reminder.py:551` (`reminders_muted`), `:365` (`clear()` never resets `_muted_since`)
- What: episode identity is `_muted_since == self._since`, both from `time.time()`. `time.get_clock_info('time').resolution` is 0.015625 s here and two reads in one tick are byte-identical (99996/100000 in a measurement), so a new episode starting in the same tick as the muted one ended inherits its mute.
- Failure scenario: (a) Settings renders "Reminders about this drive are off until it is plugged back in." and hides both buttons while `begin()`'s thread is in fact still ballooning; (b) the gate case - `companion/tests/test_drive_reminder.py::test_the_drive_coming_back_ends_the_mute_with_the_episode` fails intermittently at HEAD.
- Evidence: `pytest tests/test_lane_guard.py tests/test_drive_reminder.py -q` -> `1 failed, 123 passed` on the first run, 124 passed on four reruns; forced deterministically with `clock=lambda: 1000.0` -> `NEW episode inherits the last one's mute -> True`.
- Ledger: new (contradicts SYNC-117's ledger claim at KNOWN_BUGS:13370 that "a new episode never inherits the last one's click")
- Suggested fix: set `self._muted_since = None` in `clear()`, and give the episode a monotonic counter/id rather than a wall-clock float.

### comp-sync-17 - RepathLedger event ids collide, and a collision strands a pending relink for 30 days
- Severity: low
- Confidence: CONFIRMED (collision measured; the two-renames-in-one-pass trigger is PLAUSIBLE)
- Where: `companion/src/ccsync_companion/sync/repath.py:248` (`"id": int(float(self._now()) * 1000)`), `repath.py:284` (`mark_relinked` returns on the first id match)
- What: the event id is a millisecond wall-clock stamp with no uniqueness check, and `mark_relinked` returns at the FIRST event carrying that id, so two events sharing one id can never both be retired.
- Failure scenario: an admin reorganises the tree and two projects are repathed in one pass with Resolve closed. If the two `record()` calls land in the same millisecond, `mark_relinked` later flips the first event instead of the second; the second stays pending and is re-walked at the head of every pass for 30 days (compounding comp-sync-6).
- Evidence: 10 back-to-back `record()` calls to a real state dir produced 6 distinct ids out of 10 (1 of 10 in memory).
- Ledger: new
- Suggested fix: make the id unique (a counter or `uuid4().hex`) and match on `(id, slug, old)` in `mark_relinked`.

### comp-sync-18 - `move_proxy_siblings` folds case but not Unicode, so an NFD proxy is orphaned
- Severity: low
- Confidence: CONFIRMED (mechanism)
- Where: `companion/src/ccsync_companion/file_moves.py:168`
- What: the sibling test is `candidate.stem.lower() != src.stem.lower()` - a raw compare between `iterdir()`'s spelling (NFD on a Mac) and the command's NFC `from_rel`. Every other comparison in the module goes through `_cmp_key`.
- Failure scenario: an admin moves `Šimalčík_A001.mov`; the original follows, its `Proxy/Šimalčík_A001.mov` does not. The orphan stays under the old project's `Proxy/`, where lane B's `rclone sync` eventually trashes it, and the moved original has no local proxy until lane B re-downloads one.
- Evidence: scratch run - an NFD proxy against an NFC source returns 0 moved; the ASCII control returns 1.
- Ledger: new (same CR-90 class as comp-sync-11)
- Suggested fix: compare `unicodedata.normalize("NFC", stem).lower()` on both sides; keep `candidate.replace(target)` on the raw paths.

### comp-sync-19 - only the first folder problem is ever shown, with no count
- Severity: low
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/sync/syncthing_lane.py:733`
- What: `problems[0]` is prepended to `status.detail` and the rest are discarded. Two libraries and three borrowed lenders failing look identical to one.
- Failure scenario: the LUT library and a borrowed lender are both unshared; the editor fixes the one named, the detail then names the second, and nothing ever said there were two.
- Evidence: read the block; `Sequencer.shared_folder_problems()` returns the full list and `CompanionApp.shared_folder_problems()` caps at 10, so the information exists.
- Ledger: new
- Suggested fix: `problems[0]` plus a "+N more" suffix, as `unfiltered_sentence` already does.

### comp-sync-20 - a move delivered while the sync drive is out expires while the companion is deliberately silent
- Severity: low
- Confidence: CONFIRMED (code path)
- Where: `companion/src/ccsync_companion/app.py:7285` + `dashboard/src/ccsync_dashboard/db.py:5413` / `api.py:8900`
- What: when `local_root` is absent the companion deliberately sends no answer, but the dashboard stamps `delivered_at` at reply-build time, not on an answer. `expire_delivered_file_moves` then expires the target after 7 days of "told and never answered", `pending_file_moves` stops offering it, and the companion has no ledger entry - so `recent_excludes` holds no exclusion either.
- Failure scenario: an editor takes their external SSD off for a two-week shoot. The command expires; when the drive returns nothing tells that machine about the move, and lane A puts the file back at the path the admin cleared. It is visible on the project page and in the alert, so it is loud rather than silent - but the machine that expired is the one still holding the file.
- Evidence: `app.py:7285` ("Not an answer: the drive may be back next report"), `api.py:8900` (delivery stamped on offer), `db.py:5413` (`expired_at IS NULL` filter), `FILE_MOVE_MAX_AGE_DAYS = 7`.
- Ledger: related to UX-5 / DASH-9 (both recorded FIXED)
- Suggested fix: have the companion answer `state="retrying"` with "waiting for the sync drive" instead of staying silent, or skip the delivery stamp for a machine whose last report said the root was absent.

### comp-sync-21 - the grade-swap rollback sentence still hardcodes "P:"
- Severity: low
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/app.py:4373`
- What: `suffix = " P: was restored to your local copy."` - a literal drive letter in user-visible copy, in the one function SYNC-103 converted to take `letter=self.canonical_drive_letter()` three lines above. CLAUDE.md: the drive letter is site data.
- Failure scenario: a customer whose `canonical_prefix` is `Q:` fails a grade swap and is told "P: was restored to your local copy", about a drive they do not have.
- Evidence: read `app.py:4360-4378` against the whole SYNC-103 diff in `drive_swap.py`, where every other letter-carrying sentence is a template.
- Ledger: related to SYNC-103 (KNOWN_BUGS:11261)
- Suggested fix: `f" {letter} was restored to your local copy."`.

### comp-sync-22 - the structure clone runs for an upload-only project
- Severity: low
- Confidence: PLAUSIBLE
- Where: `companion/src/ccsync_companion/sync/sequencer.py:1907` (`_maybe_clone_structure` is called before the `if upload_only:` early return at `:1923`)
- What: `docs/UPLOAD_ONLY_TICK.md` says upload-only is lane A alone. The structure clone is neither lane, but it is an `rclone lsf --dirs-only -R` over SFTP plus a local mkdir loop - a remote listing and local directory creation for a project whose whole point is that nothing comes down.
- Failure scenario: an editor ticks a finished project upload-only to get their originals onto the server; the companion creates the NAS's whole bin skeleton inside their local project folder, which is not what they asked for, and pays one SSH handshake per project per N passes for it.
- Evidence: read `_process_project` - the `upload_only` early return is AFTER both `_reconcile_paths` and `_maybe_clone_structure`; `_maybe_clone_structure` has no upload-only arm.
- Ledger: new
- Suggested fix: skip the structure clone for an upload-only project, or state in the docstring why it is deliberately kept.

## Coverage note
Not reached: `rclone_lane.py`'s JSON-log parser and the orphan/consolidate scan
paths in depth (~40% of that file unread); `syncthing_admin.py`'s `_request`
retry/timeout logic and `accept_folder` write path line by line;
`consolidate.py`'s rclone dry-run parsing against a live rclone (no findings by
reading); the watcher's `_heartbeat`/`LaneWatchdog` restart path; `root_guard`
against a real wedged volume or on macOS (`probe_root`'s darwin arms were read,
not run); the supervisor's macOS `launchctl` path; and the dashboard half of
`sync_guard.lane_b_breaker.editor_reason`. NFC/NFD in
`restricted_ignore_lines` on a macOS lender with accented subtree names could
not be proven without a Mac.

What the suites do not cover: a `_write_json` that fails; two companion
processes writing one latch; `_trash_line` against a real `sync_guard` payload;
any `_on_root_absent` state-to-state transition; the empty-`expected` lane C
path with problems present; the 1024-attempt overflow; a blocked repath that
stops being needed; `relink_moved` at all; `move_proxy_siblings` with a
decomposed name; a case-only rename; `fetched_at()` after a second unchanged
fetch; and a lane B thread abandoned after `abort_run`.

## OUT OF TERRITORY
- `companion/src/ccsync_companion/app.py:4858` / `:4872` and `tray.py:2718`: the two SYNC-101/102 producers have no consumer (reported as comp-sync-4 because the producers are in sync/, but the fix is in the tray snapshot and the reporter payload).
- `companion/src/ccsync_companion/app.py:5105`: `removable_projects` reads an unknown `sync_mode` as "not upload-only" - it guesses where `sequencer._item_sync_mode` fails closed.
- `companion/src/ccsync_companion/proxy_scan.py:561`: passes a raw (unfolded) `selected_rels` to `manifest.prioritize_project_rels`, which folds the walked rel - correct only because the dashboard's selection happens to be NFC.
- `companion/src/ccsync_companion/watcher.py:562`: `self._heartbeat` is first assigned inside `run()`; the watchdog tolerates it, but a wedge during the very first poll is unmeasurable.
