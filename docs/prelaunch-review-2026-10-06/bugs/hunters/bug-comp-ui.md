# bug-comp-ui: companion UI and process lifecycle (pre-launch bug hunt, 2026-10-06)

Lens: the companion's UI and process lifecycle on the working tree as it stands (HEAD 08b40eb plus uncommitted changes).

Covered: ui_dispatch.py (all of it, including the CR-93 pin/reclaim registry), supervisor.py (all), crash_report.py (run marker, atexit stamp, report writing, redaction), shutdown_guard.py (Windows and Darwin guards), eula.py and idle.py (all), tray_native.py (Windows pump, menu, Darwin NSStatusItem and main-thread hop), and these parts of the bigger files:
- tray.py: start_tray, the menu, Quit and Restart, _tray_snapshot
- settings_window.py: the Tk shell and the actions
- popup.py: FIX ALL dialog, ProgressWindow, WorkProgressWindow, confirm and licence dialogs, and the uncommitted CR-358 project-mismatch path
- app.py: run(), shutdown() and the licence flow

I also read the uncommitted CR-356 diffs (folder-ignore retirement) across popup, settings, tray, fixer and app, and found no leftover references.

Probe: `scratchpad/probe_shutdown.py` runs the real `CompanionApp.shutdown` against a stub app with a 3 s `_stop_lanes`. The second call (the one `run()`'s `finally` makes) returned after 0.016 s, with the lanes not yet stopped and no clean shutdown recorded.

Not covered in depth: ui_copy.py and theme.py (skimmed), the remaining ~4,000 lines of tray.py line producers, and every individual dialog builder in tray.py.

### bug-comp-ui-1 - shutdown() re-entry returns at once, so the process exits while Quit/Restart/self-upgrade teardown is still running on a daemon thread
- Severity: high
- Confidence: CONFIRMED (code path read end to end, and probed)
- Where: companion/src/ccsync_companion/app.py:11453-11469 (the ONCE guard and `_stop_event.set()` at the top), app.py:11939-11956 (run()'s wait loop and finally), tray.py:2433-2446 (quit_from_menu), tray.py:5190 (daemon icon thread), upgrade.py:2142-2147 (restart_self), app.py:6821-6855 (_stop_lanes: the sequencer join is up to 10 s before lane B's rclone is killed)
- What: every path except a SIGTERM runs shutdown() on a worker thread. That covers the tray Quit (on the Windows tray pump thread, which is daemon; on macOS a `_spawn` daemon thread), Restart CCSync, stale-bridge recovery and the self-upgrade (restart_self / UpgradeManager request_shutdown). shutdown() sets `_stop_event` near its top, before any teardown. The main thread wakes, and run()'s `finally` calls shutdown() again, which hits "already ran -- ignoring the repeat call" and returns immediately. run() then returns and the interpreter exits, killing the daemon thread part-way through teardown. On Windows Quit the main thread waits up to 5 s in `_tray_icon.stop()`. On macOS and on every restart/upgrade path it waits about 0 s.
- Scenario: a self-upgrade or Restart CCSync while lane B is mid `rclone sync`.
  1. The old process exits within milliseconds of request_shutdown().
  2. `_stop_lanes()` never reaches `self._lane_b.stop()`, the only path to `_kill_running_process()`.
  3. On Windows the rclone child outlives its parent.
  4. The replacement build gets the single-instance slot at once and starts its own lane B against the same destination. That is the delete-authorised two-`rclone sync` race SYNC-1 / AUDIT_2 L-12/C-7 closed, reopened by the ONCE guard. app.py:331-339 even sizes the newcomer's wait on the assumption that the predecessor "holds the slot for exactly as long as its lanes take to stop".
  5. Also, `upgrade.note_clean_shutdown()` is never written. Three Quit-or-Restart cycles of one build inside 10 minutes therefore read as `crash_loop`, and while the `.old` rollback copy still exists (the first hour after an update) APP-5 reverts the machine to the previous build.
  6. Reporter, manifest cache, job runner leases and the ffmpeg/whisper children are likewise cut off mid-stop.
- Recommendation: make the second caller wait, not return. Add a `_shutdown_done` Event that shutdown() sets in a `finally`, and have the repeat call `wait()` on it with a generous bound (the 30-40 s the R11 comment already sums). Alternatively, have Quit, restart and upgrade only set `_stop_event` and let run()'s `finally` (the main thread) do the one real teardown. Add a regression test that drives shutdown from a worker thread and asserts run() does not return before `_stop_lanes` and `note_clean_shutdown` have run.
- Known: not in KNOWN_BUGS (searched for "repeat call", "already ran", "teardown" and related phrasing).

### bug-comp-ui-2 - Quit is only confirmed for a FIX ALL copy; a CONSOLIDATE copy in flight is killed mid-write with no question
- Severity: medium
- Confidence: CONFIRMED
- Where: tray.py:2362-2411 (_confirm_quit_while_copying reads only popup.copy_in_progress()); popup.py:910-925 (_set_copy_state is published only by PopupDialog._run_fix); consolidate.py:405-503 (run_consolidation copies through the same fixer.fix_clip path); app.py:6948-6966 (_standing_down_would_kill_work knows about consolidate, but Quit does not ask it)
- What: RES-8's question ("CCSync is copying... Quit anyway?") is keyed on the FIX ALL dialog's copy state alone. A consolidate run (ProgressWindow, `_consolidate_active`) never publishes to `_copy_state`, so `_confirm_quit_while_copying` answers True and Quit goes straight to icon.stop() and shutdown().
- Scenario: an editor starts Consolidate on a 400-clip project and, an hour in, picks "Quit CCSync" from the tray.
  1. No question is asked.
  2. The process exits; see bug-comp-ui-1, which makes this immediate. The copy is killed inside shutil.copy2.
  3. That leaves a multi-GB `.ccsync-tmp` in the synced tree, and possibly a clip whose copy landed but which Resolve was never repointed at. This is exactly the AUDIT_2 CORE-H8/H5 shape that Restart and the self-upgrade already refuse for this very state.
- Recommendation: have Quit ask `app._standing_down_would_kill_work()` (or a copy-state that consolidate also publishes) and show the same native confirm for "consolidate".
- Known: RES-8 (closed) covered only FIX ALL.

### bug-comp-ui-3 - macOS: a quit Apple event (logout, restart, Activity Monitor "Quit") ends the process through Tk's default handler, bypassing shutdown(), the marker removal and atexit
- Severity: medium
- Confidence: PLAUSIBLE (Tk-Aqua behaviour; not tested on a Mac)
- Where: app.py:11812-11829 (Tk owns NSApp, the activation policy is Accessory); shutdown_guard.py:1145-1191 (the delegate half stands down because TKApplication already owns the delegate slot, `existing is not None`); no `::tk::mac::Quit` is defined anywhere in the package (grep); crash_report.py:586-605 (the "exiting" stamp is a Python atexit hook); supervisor.py:159-203
- What: on macOS the main thread runs Tk's mainloop and Tk-Aqua's TKApplication answers kAEQuitApplication. With no `::tk::mac::Quit` command defined, Tk evaluates Tcl `exit`, which is a C exit(). Python's atexit hooks do not run on that path, and neither does shutdown(). The SIGTERM half of the Darwin guard is never reached, because the app is gone before launchd would escalate.
- Scenario:
  1. Every logout or restart of a Mac editor leaves `running.marker` without `"exiting"`. The next login files an UncleanExit crash report, the CR-316 phantom-crash noise on the fleet grid's [ CRASHES ] chip, now for Macs.
  2. A Quit from Activity Monitor (not Force Quit) reads to the supervisor as a crash: marker present, pid matches, no "exiting" stamp. The supervisor relaunches the companion 10 s later, against the editor's explicit action.
  3. Lanes are not stopped, so an rclone child is orphaned under launchd.
- Recommendation: register `root.createcommand("::tk::mac::Quit", ...)` on the dispatcher's hidden root. It should call `app.shutdown()` off the UI thread and then let serve() return, so the Apple-event quit takes the same path as the tray Quit. Verify on a Mac with a logout and with Activity Monitor > Quit, checking the marker afterwards.
- Known: not recorded. CR-316 fixed the Windows half (WM_ENDSESSION) only.

### bug-comp-ui-4 - Settings > [ GIVE THIS COMPUTER A NEW ID ] opens a Tk dialog without taking _popup_active_lock
- Severity: low
- Confidence: CONFIRMED
- Where: settings_window.py:548-595 (action_repair_machine_id calls popup_mod.confirm_dialog directly on a `_spawn` thread). Compare tray.py:1912/2041/2083/2113/2160/2223 and app.py:3113/4178/9093/10997/11051/11149, where every other confirm_dialog caller takes the lock.
- What: this is the one confirm_dialog site that neither takes nor checks the popup lock. The Settings window releases the lock before spawning the action, by the module's own rule.
- Scenario:
  1. While the confirm is up, the watcher's out-of-tree popup (or the licence offer) can acquire the free lock and build a second Tk root on another thread beside it. That is the sibling-root shape CORE-M3/H8 and the module docstring exist to prevent.
  2. apply_upgrade's stand-down test (`_popup_active_lock.locked()`) does not see this dialog either. A pushed update can therefore restart the process under an open confirm, and the id repair the editor was answering silently never happens.
- Recommendation: take `app._popup_active_lock` (non-blocking, with the standard "Another CCSync window is already open" toast) around the confirm, as action_set_role does.
- Known: not recorded.
