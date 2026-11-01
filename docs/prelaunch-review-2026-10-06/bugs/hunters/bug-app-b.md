# bug-app-b: companion app.py lines 6000-12142

Pre-launch bug hunt, 2026-10-06, working tree at HEAD 08b40eb plus uncommitted changes.

**Covered (read end to end):** the undo/licence/sign-in tray glue, project removal and its caught-up gate, the lane start/stop gates (`_lanes_refusal`, `_start_lanes`, `_stop_lanes`), sign-in/out, `apply_upgrade` and the auto/pushed update paths, the update ledger, `sync_guard` / `blocked_report`, the halt engage/release and re-pause, `_apply_resume_lane_b`, `_apply_machine_settings_request`, `_apply_file_moves` and the relink paths, `_apply_resolve_undo`, `_apply_fleet_halt`, the diagnostics channel and its redaction, `lane_statuses`/`sync_now`, `toggle_pause`, `start()`, the watcher and media-tree thread starters, the loopback bind, LUT link, the work windows, the ingest tray actions, the shutdown guard, `shutdown()`, the crash-loop revert, `run()`, and `setup_resolve_prefs_cli`.

**Read on the other side to close a trace:** `upgrade.py` (`apply`, `restart_self`, `revert_to_previous_build`, `note_version_start`, `note_clean_shutdown`), `resolve_bridge._bridge_call` and `undo_last_relink`, `file_moves.relink_moved`/`rclone_server_files`, `resolve_undo.apply_undo`, `machine_settings.apply_request`, `sequencer.start/stop/_unpause_all/thread_died`, `selection.untick`, `shutdown_guard.handle_end_session`, `LaneWatchdog`, `reporter.post_once`'s reply fan-out, and `docs/legal/TELEMETRY.md`.

**Not covered:** app.py before line 6000 (another lens), and the tray/settings_window UI code beyond the calls into this range.

---

### bug-app-b-1 - The reporter thread calls into Resolve in-process, so a busy or modal Resolve stops this machine's reports, fleet halt and pushed updates
- **Severity:** high
- **Confidence:** CONFIRMED
- **Where:** app.py:2566-2571 (`_on_report_response_locked` -> `_apply_file_moves`, `_apply_resolve_undo`); app.py:8813 (`_relink_moved_result` on the reporter thread); app.py:9005 (`resolve_undo_mod.apply_undo`); resolve_bridge.py:144 (`while not _API_LOCK.acquire(timeout=...)` loops forever); resolve_bridge.py:2685, 2723 (`current_project_name(max_age=0)`, `get_media_pool_items()`); file_moves.py:953
- **What:** `reporter.post_once` runs `on_report_response` inline on the reporter thread (reporter.py:1416). Two consumers there make live fusionscript calls:
  - an admin's dashboard undo: `apply_undo` -> `resolve_bridge.undo_last_relink` -> a live project-name read and a full media-pool walk;
  - a file move's relink: `relink_moved` -> `get_media_pool_items` -> `replace_clip` per clip.

  `_bridge_call.__enter__` waits on `_API_LOCK` with no deadline (it only logs a wedge warning). The repo's own notes (music_server.py:20-23, music_worker.py:17-20) say the scripting API "blocks indefinitely when Resolve is modal, busy, or sitting on the Project Manager window". That is why the music button runs Resolve in a killable child process. These two paths run on the one thread that carries the fleet's control channel.
- **Scenario:** An editor leaves Resolve on a modal dialog, or its media is on a share that has dropped (the watcher is wedged inside a call). An admin presses undo for that machine on the dashboard, or moves a file that this machine holds. On the next report reply the reporter thread enters Resolve and never comes back. From then on:
  - the machine stops reporting and drops off the fleet grid;
  - a fleet halt, a pushed update, a diagnostics ask and a lane B resume never reach it;
  - the off-cycle report thread queues behind `_report_response_lock`.

  It recovers only when Resolve unwedges. Separately, even with a healthy Resolve, an undo answered `retrying` (wrong project open) is redelivered on every report for up to a week. Each redelivery walks the whole media pool on the reporter thread (every 5-60 s) and competes with the watcher for `_API_LOCK`.
- **Recommendation:**
  - Move both Resolve acts off the reporter thread. Queue the undo and the relink to the watcher thread (it already owns Resolve and re-runs pending relinks on project change), or to a dedicated worker, and answer `retrying` until that worker has a result.
  - At minimum, give the reporter-side calls a bounded `_API_LOCK` acquire and skip them while `resolve_bridge.bridge_activity()` reports a call in flight.
  - Cheap-gate the retrying undo on the cached project name before the pool walk.
- **Known:** not in KNOWN_BUGS (SYS-15b and RES-10 introduced these paths; neither records the thread hazard).

### bug-app-b-2 - The update stand-down test runs before a minutes-long download and is never repeated before the exe is swapped and the process stood down
- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:** app.py:6984-7002 (`apply_upgrade`); upgrade.py:1920-1986 (`_apply_inner`: download, swap, spawn, `request_shutdown()` with no re-check); app.py:11591-11599 (`shutdown` joins the watcher for 5 s only)
- **What:** `_standing_down_would_kill_work()` (popup lock held / `_consolidate_active`) is checked once. Then `self.upgrade.apply()` downloads and verifies the build (about 20 MB, more for macOS bundles, over the tailnet), swaps the exe, spawns the child, waits the 2 s takeover grace and calls `self.shutdown()`. Nothing re-asks the stand-down predicate after the download. This gap matters most on the unattended paths (auto_update, admin push), where nobody chose the moment. The docstring at 6952-6960 names the outcome the guard exists to prevent: a copy killed inside `shutil.copy2`, a partial `.ccsync-tmp`, and a project half relinked.
- **Scenario:** An admin pushes 0.9.x. Ruskin's out-of-tree popup was closed at that instant, so the stand-down test passes and the download starts. Ten seconds later the watcher re-raises the popup, the editor clicks FIX ALL, and consolidate starts copying. The download completes and the swap goes through. `shutdown()` joins the watcher for 5 s and the process exits mid-copy. The result is the CORE-H8/H5 state: partial tmp files, some clips relinked and some not, which the next start only reports.
- **Recommendation:** Pass the stand-down predicate into `UpgradeManager.apply` and re-check it after `download_and_verify`, immediately before `_replace(exe, old)`. On refusal, keep the verified download for the retry. Better still, hold a "standing down" latch from that check through `request_shutdown()` that FIX ALL / consolidate and new popups test and refuse to start under (they already defer on the popup lock). The same applies to `restart_self`.
- **Known:** not recorded (KNOWN_BUGS covers the stand-down's retry cadence, not the check-then-act gap).

### bug-app-b-3 - Accepting the licence, or clearing a sync stop from the tray, starts the lanes on a require_login machine nobody is signed in to
- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:** app.py:6666-6695 (`_lanes_refusal` has no login gate); app.py:6638-6646 (`_show_licence_dialog` -> `_start_lanes()`); app.py:8150-8162 (`release_halt` -> `_start_lanes()`); tray.py:2139 and settings_window.py:1676 (the UI doors to `release_halt`)
- **What:** `_start_lanes()` is described as "the ONE door every start path goes through" and it "re-checks every other gate", but its predicate `_lanes_refusal()` checks pause, halt, config, EULA, root and sync_enabled, and not `_login_gate_blocks_sync()`. `start()`, `on_signed_in()` and `toggle_pause()` each apply the login gate themselves before calling in. The licence-accept path and `release_halt` do not.
- **Scenario:** A shared machine runs with `require_login = true`. Its editor signed out, or a pre-CR-86 token expired: the identity watcher stopped the lanes and `_lanes_started=False`. Then either:
  - (a) an update raises the EULA version (the 1.1 re-consent seen on 2026-09-25), and whoever is at the desk clicks ACCEPT on the licence dialog that `_licence_watch` puts up; or
  - (b) someone clicks "Clear the sync stop" on a local halt.

  `_start_lanes()` starts lane C, the sequencer and lane A's watchdog with no verified identity. The reporter still skips every cycle (`editor_identity()` is None), so the machine uploads and shares project files while invisible on the fleet grid. That is exactly what require_login exists to stop, and it repeats the SYNC-3 shape that `toggle_pause` was fixed for.
- **Recommendation:** Put the login gate into `_lanes_refusal()`, just after pause/halt, with `_mark_lanes_pending_login()` as its action in `_start_lanes`, so every door inherits it. Then drop the per-caller checks, or keep them as belt and braces.
- **Known:** not recorded (SYNC-3 / comp-app-1 fixed sibling doors only).

### bug-app-b-4 - A Windows shutdown or log-off is never stamped as a clean exit for the crash-loop counter, so reboots after an update can count as crashes
- **Severity:** low
- **Confidence:** CONFIRMED (mechanism); low likelihood
- **Where:** app.py:11212-11215 (`on_session_end` only calls `crash_report.mark_clean_exit`); shutdown_guard.py:590-614; upgrade.py:289-305 (`note_version_start`: only `last_clean_shutdown` resets `starts`); app.py:11634-11637 (`note_clean_shutdown` only at the end of `shutdown()`)
- **What:** CR-316 made a Windows session end a deliberate exit for the crash marker, but not for APP-5's start counter. `note_version_start`'s own comment says "the editor quitting the tray (or a reboot) is not a crash", but on Windows a reboot never reaches `shutdown()`, so `last_clean_shutdown` stays None. macOS is fine (SIGTERM -> `shutdown()`).
- **Scenario:** An auto-update lands on a laptop that is off the tailnet, so no report is accepted and `<exe>.old` is kept for an hour. The editor restarts Windows twice within ten minutes (Windows Update, a driver install). Start 3 reads `crash_loop`, and `_revert_crashing_build` restores the previous build. `note_reverted_from` then writes `crash_looped` for a healthy build, so `_upgrade_attempt_blocked` refuses every later auto-update and admin push of that version on this machine. The tray announces "the last update kept crashing" and diagnostics say "do not install it by hand".
- **Recommendation:** Have the session-end callback also call `upgrade_mod.note_clean_shutdown(self._state_dir)`. It is one small atomic JSON write and fits the "marker only" budget `handle_end_session` allows.
- **Known:** not recorded (CR-316 covers the crash marker only).

### bug-app-b-5 - Restarting the watcher thread clears the process-wide stop event, which can undo a shutdown that races it
- **Severity:** low
- **Confidence:** PLAUSIBLE (narrow race)
- **Where:** app.py:10331 (`self._stop_event.clear()` in `_start_watcher_thread`); app.py:1206-1229, 1094-1163 (`LaneWatchdog` checks `_shutdown_started` / `_stop_event` once, at the top of a tick); app.py:11459-11478 (`shutdown` sets the flag and the event, then `watchdog.stop()` joins for up to 5 s); app.py:11946 (`run()`'s Windows loop waits on `_stop_event`)
- **What:** `_stop_event` is not the watcher's own event. It is the event `run()`'s main loop, `_licence_watch`, `_site_refresh_loop`, `_lut_link_loop` and `keep_old_exe_until_healthy` all exit on. The watchdog tests for shutdown at the top of `check()` and can call `_start_watcher_thread()` after `shutdown()` has set the event, while `shutdown()` is blocked in `watchdog.stop()`'s join.
- **Scenario:** The watcher thread has died (the watchdog restarts it about once a minute). The editor clicks Quit, or a pushed update calls `request_shutdown`, inside that tick. The event is cleared after `shutdown()` set it. On Windows the main loop never sees it set, so the process stays alive with lanes, reporter and loopback stopped, still holding the single-instance mutex. The next logon autostart says "already running", and the updated child waits on a mutex that is never released.
- **Recommendation:** Give the watcher its own stop event, as the media-tree thread has `_media_tree_stop_event`, and never clear `_stop_event` outside construction. At minimum, re-check `_shutdown_started` inside `_start_watcher_thread` under `_shutdown_lock`.
- **Known:** not recorded.

### bug-app-b-6 - "Copy diagnostics" tells the editor the bundle was sent to the admin's dashboard when it was not
- **Severity:** low
- **Confidence:** CONFIRMED
- **Where:** app.py:9918-9922, 9949-9952, 9957-9960 (toasts); app.py:9291-9293 (`_upload_diagnostics_once` returns False silently when not signed in)
- **What:** All three toasts say the diagnostics were "sent to your admin's dashboard". The upload is asynchronous, its result is never read, and it is skipped entirely when `editor_identity()` is None (debug log only). Not being signed in is one of the commonest reasons an editor presses this button. A failed POST (the dashboard unreachable, the other common reason) is also announced as sent.
- **Scenario:** An editor whose sign-in was revoked presses Copy diagnostics, is told the admin has the bundle, and waits. The admin's Diagnostics page has nothing.
- **Recommendation:** Say "copied" synchronously, and toast the upload's real outcome from the upload thread ("sent to your admin" / "could not be sent: not signed in" / "the dashboard could not be reached").
- **Known:** not recorded.
