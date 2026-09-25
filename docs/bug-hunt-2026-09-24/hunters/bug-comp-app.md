# bug-comp-app - companion/src/ccsync_companion/app.py (CompanionApp, watchdog, single-instance guard, report-reply fan-out) and __main__.py
Files read (approximate coverage): app.py lines 1-2360 (module helpers, single-instance guard, LaneWatchdog, file-move helpers, __init__, _on_report_response), 2539-3000 (root guard), 3781-4130 (consolidate), 4223-4830 (media tree, bridge recovery, identity role), 5282-5322, 5759-6062 (removal gate), 6302-6770 (lane start/stop, sign-in, upgrade ledger), 6851-7150 (sync_guard), 7507-8512 (resume lane B, halt, auto/pushed update, file moves, resolve undo, fleet halt), 8512-8740 (diagnostics channel), 9112-9530 (pause, start), 10319-10600 (power guards, tmp sweep, identity watch), 10594-11275 (shutdown, run, entry points); __main__.py in full. Followed calls into sync/sequencer.py (stop/pause/_unpause_all/release_for_halt/thread_died), sync/rclone_lane.py (run_once early returns), sync/lane_guard.py (note_fleet_flag), reporter.py (post_diagnostics, payload assembly, post_once), selection.py (untick), file_moves.py (apply_move), dashboard api.py/db.py (file-move answer, diagnostics and resume commands).
Tests/probes run: one ad-hoc probe from the companion venv (scratchpad `probe_halt.py`) driving a real `Sequencer` with the suite's `FakeAdmin` through a halt followed by a second `stop()`; output quoted in finding 1. No suites run.

## Findings

### bug-comp-app-1 - A halt's paused project folders are unpaused by the next sequencer stop()/pause() (tray Quit, self-upgrade, Resolve-exit restart, tray Pause, drive unplugged)
- Severity: high
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/app.py:6456-6461 (_stop_lanes -> sequencer.stop), 10705 (shutdown -> _stop_lanes), 9245-9247 (toggle_pause -> sequencer.pause), 2890-2892 (_root_pause_lanes -> sequencer.pause); companion/src/ccsync_companion/sync/sequencer.py:733-758 (stop()/pause() call `_unpause_all(self._last_selection)` with no halt check)
- What: `halt_all_sync` stops the sequencer and then PATCHes every lane C folder to paused. But `Sequencer.stop()` and `Sequencer.pause()` both end in `_unpause_all(self._last_selection)`, which checks neither `_is_halted()` nor the halt latch, and `_last_selection` is still populated. Every later stop()/pause() in the same process therefore releases every selected project's Syncthing folder while `self.halt.active` is still true. Syncthing runs as its own service, and a restart with a persisted halt does not re-pause anything (`_start_lanes`'s halt gate only rewrites lane details). CR-48 fixed this shape for the shared asset folders and the release path, but not for project folders going through stop/pause.
- Failure scenario: an admin engages a FLEET halt because the NAS tree is being rebuilt. Every tray says STOPPED and lane C folders are paused. Then, on any editor machine: (a) the editor quits the tray, logs off, or a pushed update restarts it, or (b) the editor quits Resolve and `_maybe_recover_stale_bridge` restarts the companion (this happens once per process after every Resolve exit), or (c) the editor clicks "Pause syncing", or (d) the external sync drive is pulled (`_root_pause_lanes`). Any one of these calls `sequencer.stop()`/`pause()` and unpauses every project folder. Syncthing then syncs project files, Fusion comps and audio both ways during the halt, while the tray, the fleet grid and `sync_guard.halt` all still say stopped.
- Evidence: probe with a real Sequencer and FakeAdmin: halt pauses s-a/s-b, then a second `seq.stop()` (what shutdown does) printed `pause calls during shutdown while halted: [('s-a', False), ('s-b', False)]` and `paused_state after shutdown: {'s-a': False, 's-b': False}`. Read: `_pause_lane_c_folders(True)` is called only from halt_all_sync (app.py:7649), so nothing re-pauses after a restart. tests/test_sync_halt.py uses `_FakeSequencer.stop()` (a no-op), so no test can see this.
- Ledger: new (a gap left by CR-48's fix; related to CR-48)
- Suggested fix: make `_unpause_all` (or stop()/pause()) return early when `self._is_halted()` is true, the same way SharedFolderManager refuses. Also have `_start_lanes`'s halt branch re-assert `_pause_lane_c_folders(True)`, so a halted machine that restarts puts its folders back in the halted state.

### bug-comp-app-2 - Consolidate ignores the halt, the licence gate and the sign-in gate, and runs lane A upload and lane B `rclone sync` directly
- Severity: medium
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/app.py:3802-3832 (the gates), 4108 and 4123 (`self._lane_a.run_once(subpath)`, `self._lane_b.run_once(subpath)`); sync/rclone_lane.py:3505-3570 (run_once has no halt check; its early returns are root, stop event, breaker, disk floor)
- What: `consolidate_project` checks sync_enabled, the tray pause, config_problems and the root, but not `_lanes_refusal()`, which comp-app-1 made the one shared predicate for sync_now and _start_lanes. It does not check halt, EULA or `_login_gate_blocks_sync()`. The lanes' only remaining brake is their stop event, and that is never set on a lane that was never started. That is the state of every lane after a restart with a persisted halt, an unaccepted EULA, or nobody signed in.
- Failure scenario: a fleet halt is active and the editor's companion restarted (the halt persists and the lanes never start). The editor clicks "Copy this project's media in" and confirms. The originals are uploaded to the NAS and a delete-capable `rclone sync` pulls proxies down during a halt the admin set to stop exactly that. The same happens on a machine whose licence was never accepted, or one that is not signed in (identity is then "" in the plan). When the halt was instead engaged mid-run, both run_once calls return early because the stop event is set, and the toast still says "Copy & upload finished (N copied in)" for an upload that never happened.
- Evidence: read of the four gates against `_lanes_refusal` (app.py:6311-6331). The comp-app-6 docstring at app.py:9174-9181 records that the stop event is never set on a lane that was never started, and grep shows no halt reference in sync/rclone_lane.py.
- Ledger: new
- Suggested fix: gate consolidate_project on `self._lanes_refusal()` (and the login gate), refusing with its sentence, as sync_now_result does. Skip the upload phase, and say that it was skipped, when the lanes are stopped.

### bug-comp-app-3 - An admin's "ask this machine why" is marked answered before the upload, so a failed upload is never retried and the request stands forever
- Severity: medium
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/app.py:8724-8733 (_apply_diagnostics_request); dashboard/src/ccsync_dashboard/api.py:9881 and 10171 (the command stands until a bundle arrives)
- What: `_apply_diagnostics_request` writes `applied_request = requested_at` to diagnostics_sent.json and only then starts `_upload_diagnostics_async`, which ignores the result. The dashboard deliberately keeps the command on every reply until the bundle lands (cleared only in the diagnostics POST handler), so a redelivery is meant to act as the retry. Every redelivery is then refused by the persisted stamp. The reporter's own docstring says "app.py's three triggers all treat a failure as 'try again later'", and this one does not.
- Failure scenario: an admin clicks [ ASK THIS MACHINE WHY ] on a machine with a flaky uplink (the machines the button exists for). The 256 KB POST times out or gets a 5xx or 413 while the small report POST succeeded. The companion never uploads, the dashboard shows "diagnostics requested" indefinitely, and nothing is sent until the admin clicks again (a new requested_at). The same happens when the identity lapses between the report and the upload: `_upload_diagnostics` returns False, and the stamp is already written.
- Evidence: read both sides. `db.clear_diagnostics_request` is called only on bundle arrival (api.py:10171), and `_upload_diagnostics`' boolean is discarded by the thread target.
- Ledger: new
- Suggested fix: write `applied_request` only after `post_diagnostics` returns True, for example from inside the upload thread. Keep an in-memory "in flight" key to stop a second upload starting while one is running.

### bug-comp-app-4 - The pending-relink "done" answer can never land: the dashboard only updates rows with applied_at IS NULL
- Severity: low
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/app.py:8390-8395 (_relink_pending_moves re-answers ok=True without relink_pending); dashboard/src/ccsync_dashboard/db.py:6236-6246 (mark_file_move_applied: `AND applied_at IS NULL`)
- What: RES-10's design is that a move first answered `ok, relink_pending=True` (which stamps applied_at) is later re-answered once a media pool walk matches, "so the dashboard row updates" (KNOWN_BUGS RES-10 fix text). The only writer on the dashboard side matches `applied_at IS NULL`, so the second answer updates zero rows. `file_move_targets.relink_pending` stays 1 forever and the relink text never reaches the detail. The companion has already called `clear_relink_pending`, so it never answers again either.
- Failure scenario: an admin moves a clip while the editor has another project open. The first answer is relink_pending=True, and the next day the editor opens the project and the relink succeeds. The dashboard's `move["relink_pending"]` count (db.py:6286) still says 1 for that machine, permanently. Today nothing renders the count (grep finds no template or JS reader), which is why this is low. Any surface that starts showing "Resolve not repointed yet", as KNOWN_BUGS says the page does, would show it forever.
- Evidence: read both sides. The companion test (`test_a_move_applied_with_no_project_open_stays_a_pending_relink`) checks only that the answer was queued, and the dashboard test only checks that the first answer stores the flag.
- Ledger: new (related to RES-10, which is recorded as fixed)
- Suggested fix: on the dashboard, accept a later ok answer for an applied row when it only clears relink_pending (a separate UPDATE `SET relink_pending=0, detail=? WHERE ... AND ok=1`). Alternatively, send an explicit `relink_done` state.

### bug-comp-app-5 - An off-cycle report runs `_on_report_response` concurrently with the reporter thread's own
- Severity: low
- Confidence: PLAUSIBLE
- Where: companion/src/ccsync_companion/app.py:7611-7629 (_report_off_cycle posts `reporter.post_once` on a new thread), 7579 (called from inside `_on_report_response` via resume_lane_b), 2269-2350; reporter.py:1223-1227 (post_once calls on_report_response, no lock anywhere in post_once)
- What: `resume_lane_b`, reached from the reporter thread while it is still inside `_on_report_response`, starts a second `post_once` on another thread. Its reply is fanned out through `_on_report_response` while the reporter thread is still working through `_apply_diagnostics_request`, `_apply_file_moves` and `_apply_resolve_undo` for the first reply. Those handlers do check-then-act on shared state with no lock: the diagnostics stamp read/compare/write, `file_moves.entry()` followed by `apply_move`, and `_resolve_undo_answers` list replacement.
- Failure scenario: an admin clicks RESUME on a tripped machine that also has a redelivered file move or a standing diagnostics ask. Both threads read the ledger as "not done" and both run `apply_move` for the same move (the second meets a half-renamed directory, or double-answers and double-toasts), or both upload a diagnostics bundle. A narrow window, but no lock prevents it.
- Evidence: read only. No lock in post_once. `_queue_resolve_undo_answer`/`_resolve_undo_results` (app.py:8290-8302) have none of the locking the file-move twin got.
- Ledger: new
- Suggested fix: serialise `_on_report_response` with a lock, or have the off-cycle post skip the response fan-out (it exists only to carry sync_guard up).

### bug-comp-app-6 - `_queue_file_move_answer` appends outside the lock res-companion-5 added
- Severity: low
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/app.py:8253-8268
- What: the comment says a swap landing between the filter-assign and the append loses an answer, and the fix put only the filter-assign under `_file_move_answers_lock`. The `self._file_move_answers.append(answer)` at 8268 runs after the `with` block. If the reporter's swap (8273) lands between the attribute load and the append, the answer goes into the list the reporter already took, after it copied it, and is lost. Two concurrent queuers for the same id can also both filter and then both append, which duplicates the id.
- Failure scenario: the watcher thread's `_relink_pending_moves` queues the relink-done answer at the moment the reporter drains. The answer is dropped, and because the ledger row was already cleared it is never sent again.
- Evidence: read (indentation of lines 8253-8268).
- Ledger: new (incomplete fix of res-companion-5, 2026-09-11b hand-off)
- Suggested fix: build `answer` first, then do the filter and the append inside one `with _file_move_answers_lock(self):` block.

### bug-comp-app-7 - The posix single-instance pid file never checks that the live pid is a companion
- Severity: low
- Confidence: PLAUSIBLE
- Where: companion/src/ccsync_companion/app.py:503-542 (_acquire_lock_file), 438-446 (_pid_is_alive on posix)
- What: on macOS the guard is `~/.ccsync/companion.pid` plus `os.kill(pid, 0)`. The file is never removed at shutdown. After a crash, a logout or a reboot, the recorded pid can belong to an unrelated live process (pids are reassigned from low numbers after boot, which is when the LaunchAgent starts the companion). The companion then concludes another instance is running, shows "CCSync is already running" and exits. Nothing is actually running, and nothing retries until that unrelated process exits and the editor relaunches.
- Failure scenario: a Mac reboots and at login the old companion pid (for example 812) now belongs to a system daemon. The LaunchAgent start refuses with the already-running alert, and the machine has no companion (no sync, no tray) until someone notices.
- Evidence: read only. There is no process-name or start-time check and no unlink in shutdown(). Whether pid reuse at login actually collides has not been measured.
- Ledger: new
- Suggested fix: unlink the pid file in shutdown(), and verify the holder's executable name (for example `ps -p <pid> -o comm=`) before treating it as a live companion. Better still, use `fcntl.flock` on the file, which the OS releases on death.

## Coverage note
Not read closely: the popup/out-of-tree batching and snooze (2998-3780), non-canonical relink loop, the P: grade-swap block (4824-5050), resolve_health/trash/proxy/ytdl status readers (5049-5760), EULA/licence dialog (6117-6300), blocked_report/_blocked_candidate (7294-7506), build_diagnostics body (8757-9110), the ingest/proxy window actions (9836-10318), LUT link loop. Earlier hunts covered the popup and relink areas heavily.

## OUT OF TERRITORY
- companion/src/ccsync_companion/sync/sequencer.py:733-758: stop()/pause() `_unpause_all` has no halt check (root cause of bug-comp-app-1, fix belongs there).
- dashboard/src/ccsync_dashboard/db.py:6236: `mark_file_move_applied` cannot record a relink completion on an applied row (other half of bug-comp-app-4); nothing renders `relink_pending` though KNOWN_BUGS RES-10 says the page does.
- companion/src/ccsync_companion/reporter.py:1253-1257: docstring claims app.py's triggers retry a failed diagnostics upload; the admin-request trigger does not.
