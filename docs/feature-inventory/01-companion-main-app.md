# Companion: start-up, the main cycle and every action

Terms used throughout:
- **The companion**: the tray app that runs on each editor's computer.
- **The tree**: the shared project folder tree, reached on each computer at the "canonical prefix" (by default the `P:\` drive on Windows).
- **The dashboard**: the central fleet web server the companion reports to.
- **Lane A / B / C**: the three sync channels. Lane A uploads original video files with rclone; lane B downloads proxies and other files with rclone; lane C is Syncthing (two-way sync of small project files).
- **The sequencer**: the part that takes the computer's ticked projects one at a time and runs the lanes for each.
- **A report**: the status message the companion posts to the dashboard on a fixed interval; the dashboard's **reply** can carry commands back.
- **State directory**: `~/.ccsync/state` (or the `state` folder beside the configured log file, see below).

## Process entry points and command-line flags
(source: __main__.py, __init__.py, app.py `run`)

- `python -m ccsync_companion` (and the frozen executable) start the app.
- Command-line flag `--supervise`: the process does not start the app at all; it becomes the crash supervisor (a separate module) and exits with that module's exit code.
- Command-line flag `--self-test`: the process runs the start-guard self test (a separate module) and exits with its code; the app is not started.
- Before the app is imported, the start guard (a separate module) is asked to begin; if it answers "reverted" the process exits with code 0 without starting the app (this is the hook for rolling back a bad upgrade).
- The package exposes only its version string (`VERSION`, read from the config module).

## Logging
(source: app.py `setup_logging`, `RotatingLogHandler`, `_fallback_logging`)

- The log file location comes from the config key `log_path` (resolved by the config module). Its parent folder is created if missing.
- Log level comes from the config key `log_level` (default `INFO`); an unknown level name falls back to INFO.
- The log rotates at 5,000,000 bytes per file and keeps 10 old files (about 55 MB in total).
- At the top of each new log file after a rotation, one line is written: "log rotated: 10 file(s) of ~5 MB are kept, anything older is gone".
- Each line is formatted as time, level, logger name, message.
- When the process has a console (running from source, or a console build), lines are also written to the console; the normal windowed build writes only to the file.
- A developer escape hatch (`CCSYNC_TRAY_BACKEND=pystray`, handled elsewhere) makes the old third-party tray library's log lines go to the same file. DEV ONLY.
- If the configured `log_path` is unusable (not text, on a drive not mounted, blank), the companion logs to the built-in default path instead and writes an error line naming the broken value and asking to fix `log_path` in the config file. If even the default fails, it logs to the console only (or nowhere) and still starts.
- On a forced hard exit, every log handler is flushed first so the reason is in the file.

## Interrupted-install detection
(source: app.py `install_in_progress_problem`)

- The installer wizard writes `~/.ccsync/state/install_in_progress.json` before it wipes the machine and deletes it on Finish. The companion always looks in `~/.ccsync/state` for it, never in the configured log folder.
- If that file exists, the companion treats it as a configuration problem and refuses to sync, with this message (the drive letter taken from `canonical_prefix`, else "your media drive"): "The last install of CCSync on this computer did not finish, so this computer may have no P: drive and a half-written setup. Nothing will sync until it is finished. Run the CCSync installer again and choose FINISH THE INSTALL."
- A folder that cannot be read counts as "no breadcrumb" (no refusal).

## Only one companion per computer (single-instance guard)
(source: app.py `acquire_single_instance` and helpers, `_warn_already_running`)

- Windows: a named mutex `Local\ccsync-companion-single-instance` marks the running companion. If it already exists, the new process refuses to run.
- macOS and Linux: a pid file `~/.ccsync/companion.pid` holds the running companion's process id. A new process refuses only if that pid is alive AND is positively a companion; it checks with `ps -p <pid> -o command=` (5 s timeout) and accepts it as a companion if the command line starts with this process's own executable path (frozen builds only) or contains "ccsync" anywhere. If `ps` cannot answer, the pid is assumed to be a companion. A stale file from a crash or a reboot (pid reused by another program) does not block start-up.
- On Windows, if the mutex machinery itself fails, it falls back to the pid file method.
- Any failure of the guard itself lets the process start (it never blocks a legitimate start).
- Self-upgrade hand-off: the new build is launched with environment variable `CCSYNC_REPLACES_PID=<old pid>`. The new process reads and removes the variable (so no child process inherits it) and, only when the slot holder is that pid, waits up to 90 s, polling every 0.25 s, for the old one to let go. On Windows it retries creating the mutex each poll; once the old pid reads as dead it keeps retrying for a further 15 s grace before concluding a different companion holds the slot. If the wait runs out, the new process refuses as a second instance.
- An ordinary double-click while a companion is running never waits; it refuses at once.
- When refused, the process logs "another ccsync-companion is already running -- this instance is exiting" and shows:
  - Windows: a message box titled "CCSync": "CCSync is already running.\n\nLook for the CCSync icon in your system tray (you may need to click the ^ arrow next to the clock)."
  - macOS: an alert via `osascript` (120 s timeout): "CCSync is already running." with "Look for the CCSync icon in the menu bar."
  - Linux: nothing visible.

## macOS appearance
(source: app.py `_set_darwin_activation_policy`)

- On macOS the companion makes itself a menu-bar-only app (no Dock icon, no application menu, no Cmd-Tab entry). If the macOS bridge library is missing, it keeps a Dock icon and carries on.

## Thread watchdog (restarts the companion's own stuck or dead loops)
(source: app.py `LaneWatchdog`, `_SupervisedThread`)

- Watches three internal loops: the sequencer, the timeline watcher (reads the open Resolve timeline) and the media-tree cache (reads the Resolve media pool).
- Runs every 60 s (`LANE_WATCHDOG_INTERVAL_SECONDS`); an interval of 0 or less disables it.
- A loop counts as needing a restart when its thread has died, or when it has not "heartbeat" for longer than its bound: 30 minutes for the watcher and media tree; for the sequencer the larger of 30 minutes and 3 x the project rotation time (`project_rotation_seconds`). A loop that publishes no heartbeat is never restarted for silence.
- Never restarts anything while the companion is shutting down, or while a work item that a restart would kill is running (the same "stand-down" test the self-upgrade uses: an open popup, a consolidate, and so on; see the upgrade section).
- Backoff between restarts of the same loop: 60 s x 2^(restarts in the last hour), capped at 10 minutes; the first restart is immediate.
- Ceiling: 6 restarts of one loop in an hour; after that it stops restarting it ("this needs a human, not another restart") until old restarts age out of the hour.
- A loop that is still alive but silent is only replaced if there is a way to retire it first; only the media-tree loop has one. A silent but alive sequencer or watcher is left running and only logged.
- Every restart is recorded on disk in `<state>/watchdog.json` (restart times kept for 24 h, at most 50 per loop, plus the last error) so a companion that keeps restarting does not reset the count. Clock jumps of up to 1 hour in either direction are tolerated when reading the record.
- The record is sent in each report as `sync_guard.restarts`: per loop, restarts in the last 24 h, restarts in the last hour, time of the last one, and the last error. An absent entry means nothing has been restarted.
- Three restarts of one loop in an hour (`LANE_WATCHDOG_ADVISORY_RESTARTS`) earns the editor a tray line (the line itself is described under the tray status section).

## Fixed limits used by several features
(source: app.py constants)

- Any per-clip list sent in a report is capped at 50 entries.
- The queue of clips waiting to be relinked from a non-canonical path is capped at 1000.
- The loopback server (port 8899) rebind retry backs off from 60 s up to 30 minutes.
- Licence (EULA) offer retry: every 60 s while the licence is required and the dialog has never been shown.
- A pushed update that could not be applied is retried after 90 s, or after 600 s if the download failed.
- Lane-error diagnostics upload: at most one per lane per hour; the record is `<state>/diagnostics_sent.json`.
- Shutdown backstop: if the tray has not returned 10 s after shutdown, the process exits hard. A second shutdown request waits up to 40 s for the first teardown.
- A closing progress window is waited on for at most 3 s.

## Proxy-generator status sentences (shown in the progress window)
(source: app.py `_proxy_state_note`)

- Waiting on user activity: "waiting until you're away from the keyboard".
- Resolve open: "waiting: DaVinci Resolve is open".
- Paused: "paused".
- No ffmpeg or ffprobe: "waiting: ffmpeg or ffprobe is not installed here".
- Sync drive missing: "waiting: the sync drive is not connected".
- Bad config: "waiting: this computer's sync config needs fixing".

## Removable sync drive absent
(source: app.py `_lane_root_absent_detail`)

- When the tree's local root does not exist (an external sync drive unplugged), each lane shows: "PAUSED: <drive phrase> is disconnected -- plug it back in and syncing resumes on its own". The drive phrase comes from the site manifest.

## What the companion builds at start (construction of the app)
(source: app.py `CompanionApp.__init__`, `_build_lanes`)

These are the parts the main app owns and the config keys it reads to build them. Each optional part is built inside its own guard: if it fails to build, the failure is logged and the companion still starts without that part.

- **Managed versus unmanaged mode.** The companion is "managed" when the config key `dashboard_url` is non-blank. Managed: the dashboard decides which projects this computer syncs and in which order (selection client, Syncthing admin, sequencer, originals inbox, project-setup prompter are built). Unmanaged ("legacy"): the whole tree, all lanes running continuously, no selection, no project-setup prompter.
- Config `lane_b_enabled` (default true). In managed mode with lane B enabled, a fourth lane, the **originals lane** (downloads original video files on request), is added to the lane list so the tray, the report, the power guards and the drive reminder all see it.
- Config `sync_enabled` (default true): the starting value of "does this computer sync at all"; may be overridden by a signed-in role (see sign-in section).
- Config `require_login` (default true): when on, no lane, sequencer or report starts until the editor signs in.
- Config `popup_snooze_seconds` (default 300): how long a dismissed out-of-tree popup stays quiet for the same paths.
- Config `identity_check_interval` (default 60 s): how often the sign-in token's expiry is checked.
- Config `keep_awake_stale_seconds` and `keep_awake_max_hold_seconds`: tuning for the power guards (keep the computer awake, or warn at Windows shutdown, while sync is actually moving data); defaults live in the power-guard module.
- Config `ignored_resolve_projects`: Resolve project names treated as if they do not exist (no popups, no media-tree reporting).
- Config `media_tree_refresh_interval` (default 120 s): how often the Resolve media pool bin tree is re-read.
- Config `poll_interval` (default 3 s): how often the open Resolve timeline is read.
- Config `syncthing_url` (default `http://127.0.0.1:8384`) and `syncthing_api_key`: the local Syncthing.
- Config `syncthing_folder_ids` (default empty): unmanaged mode's list of Syncthing folders lane C watches; in managed mode the list comes from the sequencer's current selection instead, re-read on every poll.
- Lane A (upload): rclone, direction up, `remote` + `remote_root`, `rclone_path` (default `rclone`), `transfers` (default 4), `scan_interval_up` (default 300 s), `watch_debounce_seconds` (default 10 s). Always writes to `remote`, never the alternative download route. Extra transport keys are passed through (handled in the lane module). In managed mode, file-change events are handed straight to the sequencer per project rather than triggering a whole-tree pass. Lane A excludes (a) old paths of files the server moved, for a day, and (b) originals the originals lane is fetching or has just fetched. For an upload-only project, lane A carries every file, not only video. If lane A cannot start its file watcher because the drive stopped answering, the tray is told.
- Lane B (download): rclone, direction down, `scan_interval_down` (default 120 s). Its route is chosen at the start of each pass: the config key `remote_down` if set, otherwise `remote` + `remote_root`. Files lane B would remove locally are moved into `.ccsync-trash` and the editor is told (see notifications). It shares the lane-B circuit breaker and disk-floor latch objects with the tray and the report. It can ask the dashboard where a missing file went across the whole tree, and a file it follows to a new server path is recorded in the file-move ledger.
- Lane C: Syncthing, with its own supervisor that restarts the Syncthing daemon (driven from lane C's poll). Lane C also reports per-project folders parked without a filter list, and problems with shared folders (LUT library, borrowed folders).
- Safety latches, all on disk in `~/.ccsync` (not in the state folder, so deleting the state folder does not clear them; a latch found in the old state-folder location is carried over once):
  - the **lane B circuit breaker** (stops proxy download when the server stops looking like the tree or a pass would trash too much; only a human clears it);
  - the **fleet halt** (an admin's stop-everything);
  - the **disk floor latch** (lane B stands down when the sync drive is nearly full).
- Persisted state in the state folder: b-roll stand-in ledger, Syncthing supervisor incident state, file-move ledger, Resolve-undo ledger, out-of-tree ignore list and skip ledger, watchdog record, VP9 guard state, drive-reminder episode.
- "Remove from this machine" actions that were overridden are remembered (at most 20) until a report carries them.
- The Resolve library configuration (six library keys) is pushed into the Resolve bridge at start.
- Other parts built at start (each described in its own section below or by its own module): proxy generator (with the Blackmagic Proxy Generator launcher for BRAW/R3D/CRM), b-roll ingest, music ingest, YouTube importer, yt-dlp manager, upgrade manager, project-setup prompter (managed only), fleet job runner, Footage Sorter card reporter (no-op unless `sorter_cards_enabled`), sorter volume reporter and ledger outbox (no-ops unless `sorter_ledger_enabled`), field backup service (only when its module says it is enabled), Timeline Cards role (built everywhere, starts only where enabled), VP9 guard, timeline watcher, unopened-project scan, drive reminder, dashboard reporter.
- The VP9 guard uses config `ffmpeg_path` (default `ffmpeg`).
- One "is anybody at the keyboard" probe is shared by the job capabilities report and the job runner, so the two never disagree.

## The report: what the companion sends and what it does with the reply
(source: app.py reporter wiring in `CompanionApp.__init__`, `_on_report_response`)

- Each report carries (as wired by the app; the reporter module decides timing and shape): lane statuses; queue information (managed only); the open Resolve project; the local media manifest; the Resolve media tree; the effective wired/remote mode; the machine id; the Syncthing device id; the editor's name and sign-in token; transport health; lane completions; proxy coverage; YouTube import status; b-roll and music ingest status; job capabilities (including idle seconds, every report); the safety latches (`sync_guard`, every report); the route lane B pulls through (`lane_b_via`, omitted unless set); answers to file-move commands; the list of Resolve clip-path journals and answers to undo requests; the fleet-jobs machine-settings section; the accepted licence record (heavy reports only).
- If the dashboard rejects the sign-in credential, the reporter shows a tray notification.
- Replies are handled one at a time, even when an extra off-cycle report is sent from another thread.
- On every accepted reply, in this order:
  1. Mark "a report was accepted" (the health signal that clears the upgrade revert marker and lets the rollback copy be made).
  2. Pass the reply to the upgrade channel (offers), the project-setup prompter, the music and b-roll ingestors (an ingest cancel rides the reply), the stand-in knowledge (`standins_known`: archive files placed as stand-ins by any machine), and the job runner (job ids offered).
  3. Apply a fleet halt, a pushed update, an admin's "resume lane B", an admin's diagnostics request, a machine-settings request, lane-error diagnostics, file moves, Resolve undo requests, and retry a stood-down unattended update. Each is described in its own section.
- The dashboard version from the reply is remembered; a reply without one makes the companion forget it (treat the dashboard as old).
- When the open Resolve project changes, the project-setup prompter is told and any file-move relinks still waiting are retried.
- The site manifest (brand strings, drive phrase, feature flags) is re-read every 900 s, and 120 s after a failed fetch.

## The sync drive coming and going (root guard)
(source: app.py `_demote_removable_root_problem`, `_on_root_absent`, `_on_root_present`, `_warn_root_misplaced`, `_check_macos_volume_access`, `_root_pause_lanes`)

- At start, if the ONLY config problem is "local_root does not exist:" and the local root is on a removable volume (macOS `/Volumes/...`, or a root the volume record knows), it is not treated as a broken install: syncing simply waits and the lanes start on their own when the drive appears. A blank `local_root` is still a config problem.
- A background guard watches the local root. States: present, absent, not answering (mounted but its filesystem does not respond), misplaced (macOS mounted it at a numbered path such as `/Volumes/Name 1`). "Cannot tell" always counts as present.
- When the tree goes (first time in an outage):
  - It records what was still owed (only lanes actually moving data, not a lane stuck in "syncing") before pausing.
  - If work was owed: the drive reminder starts (a warning naming what is owed, then a reminder every `drive_reminder_minutes`; the reminder module owns the wording and timing).
  - Otherwise, if a previous run remembered an unfinished episode for this state, the reminders resume.
  - Otherwise one notification, by state:
    - not answering: "Sync paused: <Drive> is not answering - reconnect it or restart this computer." and a repeating "wedged drive" reminder episode starts;
    - misplaced: "Sync paused: <Drive> is mounted at the wrong place. See the CCSync window for what to do.";
    - absent: "Sync paused: <drive> is disconnected."
  - A change of state within the same outage (for example absent to not answering) produces the matching sentence again; an outage that is no longer "not answering" ends the wedged-drive reminder.
  - Everything that writes to the tree stops: in managed mode the sequencer pauses; in unmanaged mode the lanes are stopped. The editor's own Pause toggle is not touched.
  - The time of each state change is kept for the report (`blocked.since`).
- Misplaced drive: in addition, once per outage, a tray notification "<Drive> is mounted at the wrong path. Sync is paused until it is fixed. See the CCSync window." and a dialog (title "... drive mounted at the wrong path", button OK) explaining that an empty leftover folder sits at the real mount point, with three steps: eject the drive, delete the leftover empty folder, plug it back in and check it appears at the right path. If another CCSync window is open, the dialog is skipped (the notification carried the message).
- When the tree comes back: reminders end and their record is deleted, the volume record (UUID and mount point) is refreshed (no-op on Windows), the cached "is the prefix under the local root" answers are dropped, lanes resume, and the notification "Drive reconnected, sync resumed." is shown. The first sighting on a healthy machine says nothing.
- Tray detail while the tree is out with work owed: for example "2 uploads (2.3 GB left)".
- macOS only, once after a self-upgrade, on a timer: if macOS blocks reading the local root (the ad-hoc-signed build lost its Full Disk Access grant), log an error and notify: "macOS is blocking access to the sync volume after the update. Re-grant CCSync Full Disk Access in System Settings → Privacy & Security → Full Disk Access." The flag is included in diagnostics.

## Moved files and masked journal ids (helpers used by later sections)
(source: app.py `_moved_destination_is_there`, `_file_move_drive_answer_due`, `real_journal_id`, `_licence_display_text`)

- A file move is only relinked in Resolve when the new path actually exists on this disk (a path that cannot be tested counts as existing). Otherwise the log says "not relinking yet - nothing is at <path> on this machine".
- "Waiting for the sync drive" about one file move is said to the dashboard at most once every 30 minutes per move (`FILE_MOVE_DRIVE_ANSWER_SECONDS`).
- A file move answer word `not_synced_here` is only sent when the dashboard has reported version 0.7.50 or later; unknown or older versions never get it.
- When the "Resolve project" reporting category is withheld, journal ids go out masked as `withheld:project/<file>`. An undo request using a masked id is mapped back to the one journal on this machine with that file name; if none or two match, the undo is refused as not found.
- The licence text shown in the licence dialog is cleaned for display only: authoring comments, heading marks and bold marks removed, em dashes turned into " - ", runs of blank lines collapsed. The accepted text and its hash are the untouched bundled document.

## Resuming after the drive returns
(source: app.py `_root_resume_lanes`, `_mark_lanes_root_absent`)

- A returning drive is not consent to sync. It resumes nothing if: the editor paused syncing from the tray; there is a config problem (lanes are marked misconfigured); sign-in is required and nobody is signed in (lanes are marked "pending sign-in").
- Otherwise: starts the lanes if they never started, or resumes the sequencer; un-pauses lane A's immediate ("express") upload; and asks the sequencer for an immediate pass so piled-up work does not wait for the next rotation.
- While the drive is out, lane A's express upload is paused too.

## Out-of-tree clips: the passive popup
(source: app.py `_handle_out_of_tree`, `_queue_popup_batch`, `_take_popup_batch`, `_show_out_of_tree_popup`, `_run_popup_batches`, `_drain_stranded_popup_batches`, `_show_one_popup`, `_local_root_is_broken`)

"Out of tree" means a clip on the open Resolve timeline whose file is outside the synced tree, so no other editor will ever get it.
- The timeline watcher reports out-of-tree clips every poll (3 s by default). Clips shown in a popup in the last `popup_snooze_seconds` (default 300) are skipped; the snooze list is pruned as entries expire.
- Config `popup_enabled` (default true): when false, no popup is shown (only a debug log line). A base rig typically has it off.
- Refused (error logged, no popup) when the local root is misconfigured or the drive is out, because every clip would look out-of-tree and FIX ALL would copy media somewhere wrong.
- The popup itself (contents and buttons belong to the popup/fixer modules) is opened on its own thread so the watcher keeps running.
- Only one CCSync window can be open at a time. A batch that arrives while any CCSync window is open is QUEUED (de-duplicated against the clips on screen and already queued) and shown the moment the current window closes, one popup per batch. Queued clips the editor skipped meanwhile are dropped from the queued batch. Anything left in the queue with nobody to show it is drained after the window closes.
- Before showing, the companion needs to know each project's folder on the server ("project roots") from the dashboard. If the dashboard cannot be reached, the popup is not shown and the notification says: "Can't reach the server right now, so CCSync doesn't know where this media belongs. It'll ask again once the connection is back. Nothing was changed." With no selection client (unmanaged), the popup falls back to its own guess.
- The popup is given: the local root, the editor's identity, the ignore tracker, `active_project` (config), the project roots and `canonical_prefix` (relinks always store the canonical path, never the local drive path).

## Scan whole project (tray action)
(source: app.py `scan_whole_project`, `_drain_held_relinks`)

- Walks every bin of the open Resolve project's media pool (not only the timeline) for out-of-tree media.
- Works even with `popup_enabled` off, and ignores the popup snooze.
- Refusals:
  - drive out: "<Drive> is disconnected, so CCSync can't tell where your media is. Plug it back in and try again.";
  - local root misconfigured: "CCSync's sync folder isn't set up correctly, so it can't tell which media is in the wrong place. <diagnostics sentence>.";
  - Resolve could not be read: "Whole-project scan failed: <message>".
- After a successful read it clears this session's skipped clips (so everything is shown again), then runs any held automatic relinks (below) immediately, bypassing the rate limit.
- Result: "Whole-project scan: all media is in the tree", or the out-of-tree popup for the clips found (queued like any popup).

## Automatic relink of clips stored under this machine's own drive spelling
(source: app.py `_handle_non_canonical`, `_canon_relink_loop`, `_relink_non_canonical`, `_note_non_canonical_result`)

"Non-canonical" means a clip whose file is in the tree but whose path in Resolve uses this computer's local spelling (for example `F:\Creators_Club\...`) rather than the shared prefix (`P:\...`), so it is offline for everyone else.
- Without asking, the companion repoints each such clip in Resolve to the canonical spelling (no file is copied). For a clip inside a multicam or compound clip, the angle's own clip is repointed.
- Clips are queued without duplicates, at most 1000 waiting; the oldest are dropped first when over (the watcher offers them again).
- Rate limit for the unprompted path: per Resolve project, the journal module decides whether an automatic pass is allowed (minimum interval set there). When held, the clips stay queued and the log says to use Tray > Settings > SCAN WHOLE PROJECT; this log line is written at most once per interval.
- Runs on its own thread, draining the queue; stops between clips when the companion is shutting down.
- A clip Resolve cannot find any more is skipped by name. A failed relink re-arms the clip so the watcher offers it again later (on its own cooldown); only a success stops it being offered.
- After at least one success: notification "Re-addressed <N clips> to <canonical_prefix> so they stay online for every editor."
- Every relink goes through the Resolve bridge's save point and journal (source label "auto-canonical").

## Undo the last clip-path change (tray Settings action)
(source: app.py `undo_last_relink`)

- Undoes the most recent recorded clip-path change for the project open in Resolve now (journal replay by the Resolve bridge).
- Notification titled "... undo": the bridge's message, or "Nothing to undo.", plus " (that pass changed <summary>)" when something was undone.
- On failure: "CCSync could not undo the last clip-path change. <open the log sentence>, and send it to your admin."

## Clips stored under another machine's path
(source: app.py `_handle_foreign`)

- One tray warning per such clip: "“<name>” points at <first 60 characters of the path>… - a path that only exists on another editor's computer, so it can never sync or come online here. Whoever imported it should re-import it through <prefix label> (their companion will offer the fix)." (prefix label falls back to "your media drive").

## Canonical drive not pointing at the synced folder (mapping warning)
(source: app.py `_handle_mapping_warning`)

- When a clip on the canonical prefix does not resolve under the local root, notify: "Resolve is looking for your media on <P:> but <P:> is not pointing at your synced folder, so clips will show offline. Your uploads and downloads are still running. <repair-drive sentence>." (title "... mapping warning").
- Suppressed while the drive letter is deliberately pointed at the server ("grade swap", see that section) or while a swap is in progress.

## Other notifications raised by the main app
(source: app.py `_notify_trash_recovery`, `_notify_breaker_tripped`, `_notify_disk_floor_park`, `_notify_watch_state`, `_show_vp9_warning`, `_notify_tray`)

- All notifications go to the tray icon's balloon/notification; with no tray icon nothing is shown. The default title is the site's brand title, read at the time of the notification.
- Lane B moved local files aside: "Some files in your project folder weren't on the server, so CCSync moved them (never deleted) to:\n<trash folder>\nCopy anything you still need back out of there." (title "... files moved to .ccsync-trash").
- Lane B circuit breaker tripped (once, on the trip): "CCSync STOPPED downloading proxies as a safety measure:\n<editor-facing reason>\nWhen your admin says the server is fine, use the tray's "Resume proxy download"." (title "... proxy download stopped").
- Disk nearly full, lane B parked (once, on the park): "CCSync is not downloading proxies:\n<reason>\nYour uploads are still running. Free up some space and it starts again on its own." (title "... proxy download paused").
- Lane A's file watcher stopped or came back because of the drive: the lane's own message.
- VP9 guard warning (VP9-coded originals fail a full-resolution render): a dialog with the guard's title, body and two buttons (a "stop warning me" label and a "dismiss" label from the guard module). If another CCSync window is open it is not shown and the guard asks again at its next check.

## When Syncthing must not be restarted
(source: app.py `_syncthing_supervision_suppressed`)

- The Syncthing supervisor does not restart Syncthing when: syncing is halted ("syncing is stopped on this computer", plus " by your administrator" for a fleet halt); the halt state cannot be read; syncing is paused from the tray; or `sync_enabled` is off on this computer. An unplugged drive does not stop it.

## Copy this project's media in (consolidate, tray action)
(source: app.py `consolidate_project`, `_consolidate_project_inner`, `_consolidate_upload_phase`, `_subpath_is_contained`)

Onboards a project that already exists: copies every out-of-tree clip in the open Resolve project's media pool into the project's folder in the tree, relinks Resolve, uploads originals and downloads proxies.
- Refusals, checked in this order, each a notification:
  - `sync_enabled` off: "This computer works directly off the server, so there's nothing to copy in."
  - paused: "Syncing is paused. Resume it from the tray first."
  - any config problem: "CCSync isn't fully set up on this computer yet, so nothing can be copied in. <diagnostics sentence>."
  - drive out or local root broken: "<Drive> is disconnected, so CCSync can't copy media in. Plug it back in and try again."
  - the general lane refusal (halt, licence not accepted, and so on; see "Sync now"): "Nothing was copied in or uploaded. <reason>"
  - sign-in required and nobody signed in: "Nothing was copied in or uploaded. Sign in from the tray first."
  - a consolidate already running: "Already copying a project's media in. Let it finish."
  - Resolve unreadable: "Consolidate failed: <message>"
  - dashboard unreachable for project roots: "Can't reach the server, so CCSync doesn't know where this project lives. Nothing was copied or uploaded. Try again once you're back online."
  - no project folder can be determined (from the dashboard's project roots by Resolve project name, else config `active_project`): "CCSync can't tell which project this is, so it won't copy anything in. Open the project in Resolve and set it up on the dashboard first." (it never runs on the whole tree)
  - project folder resolves outside the local root: "CCSync got a project location that points outside your sync folder, so nothing was copied or uploaded. <diagnostics sentence>."
  - another CCSync window is open: "A popup is already open. Close it first."
- Then: plans the copy, notifies "Checking the NAS…" (title "... consolidate"), dry-runs both rclone lanes against the server for that project, and builds a report.
  - Server check failed: "Couldn't check the server, so nothing was copied or uploaded. <diagnostics sentence>."
  - Nothing to copy and nothing to upload: "Nothing to copy in: this project is already tidy."
- Confirmation dialog titled "COPY THIS PROJECT'S MEDIA IN" showing the report, button "COPY & UPLOAD" (and a cancel button). Cancel does nothing.
- Progress window "COPYING THIS PROJECT'S MEDIA IN", subtitle "Your original files are COPIED, never moved. Everything stays where it is." It covers both phases and offers per-file controls (skip this file, cancel all, stop after this file; the window module owns them). The progress window keeps the one-window slot for the whole copy; other popups queue and are shown after.
- Upload phase: skipped if nothing was actually copied (a rehearsal or all failures) unless there were no copy operations at all. The general lane refusal is checked again before lane A and before lane B; if it closed meanwhile, the upload is skipped. Lane A uploads that project folder; the window shows "Uploading originals to the server…" then "Uploading to the server: <project>" with bytes, speed and time left, refreshed every 2 s. Then lane B downloads proxies for that folder ("Downloading proxies from the server…") only if lane B is enabled and the dry run reported no deletions.
- Final notification (one of):
  - some failed: "<copied>/<total> copied in[, N skipped by you], <F> failed. <diagnostics sentence>."
  - stopped or cancelled: "Cancelled: <n> of <planned> copied in[, N skipped by you], the rest were left alone. Nothing was moved or deleted." ("Stopped" instead of "Cancelled" for a graceful stop).
  - rehearsal only (config-driven dry run of the fixer): "Rehearsal finished: <N files> were checked and nothing was copied in or uploaded."
  - copy done but upload refused: "Copied in (<n> copied in[, N skipped by you]), but the upload did not run or did not finish. <reason>"
  - success: "Copy & upload finished (<n> copied in[, N skipped by you])."
- While a consolidate runs, the self-upgrade, the watchdog and the stale-bridge restart all stand down.

## Which project a file belongs to on this disk (lane B helper)
(source: app.py `_project_rel_for_slug`, `_borrowed_rel_for_slug`, `_selected_project_rels`, `_queue_info`, `_on_tree_change`)

- When the server says a file moved into project X, lane B places the local copy there only if this computer syncs X (either sync mode), or borrows from X and the file's path is inside one of the borrowed subfolders. Otherwise the local copy stays in `.ccsync-trash`.
- File-change events in managed mode are passed to the sequencer per project. The report's queue is the sequencer's project order plus the current project.
- The local media manifest builds per-file lists only for projects selected for this computer (managed), otherwise rollups only.

## Resolve media pool reporting and the pool-wide checks
(source: app.py `get_media_tree`, `_media_presence`, `_refresh_media_tree_once`, `_pool_walk_is_current`, `_classify_pool_once`, `_handle_foreign_batch`, `_classify_media_kind`)

- Every `media_tree_refresh_interval` (default 120 s) the companion walks the open Resolve project's media pool.
- Each clip is reported with bin path, clip name, file path, kind ("proxy" if any folder in its path is named `proxy`, "original" if its extension is a video extension, otherwise "other") and whether the file is present on disk.
- Presence: a file seen present is trusted for 15 minutes before it is checked again; absent or new files are checked every pass.
- Not reported (empty) when Resolve is unreadable, when the project is in `ignored_resolve_projects`, or when the editor or site has withheld the "media tree" reporting category (the walk still runs; only the report stays empty). The tree is keyed by the Resolve project name.
- Before each walk: the stale-bridge restart check (below).
- After the walk, and only if the same project is still open: the proxy relink pass (attaching proxies), then the pool-wide classification:
  - Skipped when the local root is broken, a drive-letter swap is in progress, or the drive letter points at the server.
  - Out-of-tree clips (not ignored) go to the out-of-tree popup.
  - Non-canonical clips go to the automatic relink, once per path per process.
  - Clips under another machine's path: one notification per walk, each path once per process: "“<first name>” and <N other clips> point at paths that only exist on another editor's computer..." (the wording continues in the next section of code).

## Resolve open but scripting dead (repeating warning)
(source: app.py `_handle_bridge_state`, `_scripting_warn_interval`, `_maybe_warn_scripting_dead`, `_show_scripting_warning`)

- When Resolve is running but its scripting server does not answer, every Resolve feature of the companion is silently gone. The companion warns, on a timer:
  - Config `resolve_scripting_warning` (default true): false turns the warning off.
  - Config `resolve_scripting_warning_interval` (default 300 s): the first warning waits a full interval after the bad state begins; then one every interval, measured from when the editor closed the last one. 0 or less turns it off.
  - Only when a process check positively sees Resolve running.
  - Never two warning dialogs at once.
  - The dialog (owned by the tray module) can be silenced ("stop warning me") until the link recovers; any good poll resets the clock and the silence.
  - If the dialog cannot be shown, a notification carries the bridge's scripting advice instead.

## Restart the companion when the Resolve it was connected to has quit (stale bridge recovery)
(source: app.py `_maybe_recover_stale_bridge`)

- Config `bridge_auto_restart` (default true).
- Once per process. Only when the companion had connected to Resolve at some point, is now disconnected, and a process check says Resolve is not running (an inconclusive check counts as running).
- Deferred (tried again on a later media-tree pass) while work that a restart would kill is running (consolidate, open popup, and so on).
- Then the companion restarts itself so the next Resolve gets a clean scripting link.

## Foreign clips found in the media pool (batched warning)
(source: app.py `_handle_foreign_batch`)

- One notification per pool walk (title "... foreign clips"): "“<first clip>”[ and <N other clips>] point at paths that only exist on another editor's computer, so they can never sync or come online here. Whoever imported them should re-import through <prefix label> (their companion will offer the fix). Details in the log." Each path is logged on its own line.

## Automatic proxy attach (relink proxies to synced copies)
(source: app.py `_relink_proxies_once`, `_note_proxy_attach`)

- Config `proxy_relink_enabled` (default true). Skipped when the local root is broken.
- On each media-pool walk, clips whose proxy attachment is stale or missing are repointed at the proxy copies lane B synced into the tree. Steady state makes no Resolve calls.
- For b-roll archive clips, frame counts are compared (a stored count, a cheap header estimate, then an exact count by ffmpeg) to detect a proxy that was a lower-quality "stand-in"; the media-tree heartbeat is stamped per clip during this so the watchdog does not think the loop is stuck.
- Rate-limited per Resolve project like the automatic canonical relink (source label "auto-proxy-relink"); held operations wait for the next pass.
- Each attach goes through the Resolve bridge's proxy-link function (save point and journal).
- The last pass's result is kept and reported: attached, refreshed, failed, a reason ("Resolve would not attach N proxy file(s) (first: <name>). A timecode that does not match the original is the usual cause."), and the time.

## The media-tree loop (one slow background tick)
(source: app.py `_media_tree_loop`)

- Runs every `media_tree_refresh_interval` (default 120 s). Each tick: stamp the heartbeat; walk the media pool (above); re-check where the canonical drive letter points (Windows); retry binding the loopback port 8899 if it is not held; resume b-roll editing-proxy downloads that the stand-in ledger still owes (even when Resolve is closed; skipped if the local root is broken).
- A media-tree loop retired by the watchdog exits at its next check, before or after a pass.

## Wired or remote ("base" or "editor") and sync on/off
(source: app.py `_apply_identity_role`, `effective_mode`)

- This computer's role comes only from the config key `mode`: "base" if it says `base`, otherwise "editor". The signed-in person's admin status is ignored. The role is reported to the dashboard.
- Whether this computer syncs comes only from the config (`sync_enabled`, which the config module turns off for `mode = "base"`). Signing in or out re-applies it but cannot change it.
- `popup_enabled` is not changed by the role.

## Syncthing device id
(source: app.py `syncthing_device_id`)

- The local Syncthing's own device id is read and reported (so the dashboard can share folders with this exact computer). Blank when Syncthing cannot be reached or the computer is unmanaged.

## Drive-letter "grade swap" and repair (Windows only)
(source: app.py `_server_p_unc`, `p_swap_available`, `p_mapping_mode`, `p_mapping_mode_cached`, `_refresh_p_mapping_mode`, `swap_p_to_server`, `canonical_prefix_label`, `canonical_drive_letter`, `p_repair_available`, `repair_p_mapping`)

"Grade swap" temporarily points the canonical drive letter (normally the local synced copy) at the server's tree so an editor can grade on full-resolution originals.
- Target: config `server_p_unc`; `none`, `off` or `disabled` turns the feature off; blank derives the server path from `dashboard_url` and `remote_root`.
- Offered only on Windows, when a target exists, and when this computer is not a base rig.
- Where the drive letter points is classified as local, server, other (something CCSync did not create) or none (unreadable or unmapped). macOS and Linux always answer "none". The tray reads a cached answer only; the cache is refreshed every media-tree tick (and expires after 10 s for non-tray callers), and is dropped after a swap.
- The drive letter comes from `canonical_prefix`; if that is not a drive letter, P: is used for Windows commands. In sentences, the prefix is shown as written, or "your media drive" if blank.
- Swap to server (optionally with a server username and password): if it fails, the local mapping is restored and the message ends " <letter> was restored to your local copy." (or " AND <restore error>"). A successful swap with a username saves the login in Windows Credential Manager. Refused with "grade-swap is not available on this computer" when not offered. Mapping warnings and pool classification stand down during the swap.
- Repair (the "REPAIR P: NOW" button): Windows only and needs a `local_root`; otherwise "<letter> cannot be repaired from here on this computer. <diagnostics sentence>."
  - already local: "<letter> is already pointing at your synced folder."
  - server: "<letter> is showing the server originals because you asked for a grade swap. Use FINISH GRADING to put it back."
  - other: "<letter> is mapped to <target or 'something else'>, which CCSync did not create. Nothing was changed. Ask your admin before removing it."
  - none: maps the letter back to the local synced folder (the swap-to-local action).

## Resolve health (reported as `sync_guard.resolve_health`, also read by the tray)
(source: app.py `resolve_health`, `_bridge_connected_now`, `_bridge_wedge`, `_watcher_list`)

- Counts from the last full timeline scan: out-of-tree, bad-prefix, missing clips.
- Whether the Resolve bridge is connected (unknown until the first poll); the open project; how long a Resolve call has been stuck and which call.
- The missing clips and the clips whose canonical relink was refused (each list capped at 50).
- The last proxy attach result; stand-ins whose editing-proxy upgrade gave up (count and first reason, up to 300 characters); proxy gaps (clips given up after repeated failures, low disk space, per-project cap hit); the stills folder check result; clips skipped this session; clips ever skipped (tray only); time of the last scan.
- Projects NOT open on this computer whose clips exist only on this computer (from the unopened-project scan): a list of project name and count, capped at 20, with the scan time; unknown until the first sweep.
- Any value whose producer has not answered is empty or unknown rather than zero.

## B-roll editing-proxy upgrades and stand-ins
(source: app.py `_resume_broll_proxy_upgrades`, `standins_owed`)

- A b-roll clip inserted from the browser preview is a "stand-in"; the proper editing proxy downloads later. Pending upgrades are resumed every media-tree tick (by the loopback server module).
- Upgrades that have given up are reported as a count plus one reason; none means nothing is owed.

## Stills folder check
(source: app.py `_note_stills`, `stills_state`)

- The result of the Resolve stills-folder check is kept: ok (switched off, already pointing at the shared folder, or just pointed there), status, the instruction text (for example "add it by hand") and the path. Empty until a check has run.

## "Sync now" (tray action) and what it says
(source: app.py `sync_now_result`)

- Refused with the general lane refusal reason (see "Starting the lanes") if any applies.
- Managed: if the dashboard's plan for this computer is known and empty: "Nothing is ticked for this computer, so there is nothing to sync."
- Otherwise accepted: "Checking the server for changes now." with the list of lanes that will run.

## The recovery folder (`.ccsync-trash`)
(source: app.py `trash_path`, `trash_summary`, `_configured_trash_max_age_days`)

- `<local_root>/.ccsync-trash` holds files lane B moved aside. The "OPEN THE RECOVERY FOLDER" button opens it; it is offered only if the folder exists.
- Summary shown: path, number of batches, total bytes, oldest batch time, and how many days copies are kept. Config `trash_max_age_days` (module default used if absent or unreadable). None when empty.

## Naming the broken setting
(source: app.py `config_problem_detail`, `config_problem_details`)

- The worst config problem is shown as one sentence (for example which key is blank and what to set); a "WHAT IS NOT SET UP" heading lists up to three problems, worst first.

## How old the sync plan is
(source: app.py `plan_fetched_at`, `plan_age_seconds`)

- When this computer last fetched its plan from the dashboard, and its age in seconds; unknown is never shown as fresh.

## YouTube: import state, sign-in progress and stopping local downloads
(source: app.py `youtube_import_state`, `ytdl_login_progress`, `note_ytdl_login_progress`, `cancel_local_downloads`)

- Import state shown locally: state, the reason clips have not reached Resolve ("" when nothing is in the way), how many are pending, and the last import time.
- While a YouTube browser sign-in runs (it can block up to ten minutes), what it is waiting for and the seconds left are kept for display; cleared when done.
- "Stop local downloads": stops every YouTube download running on this computer and returns how many stopped; the server then picks up the unfinished work when the lease expires.

## Upload-lane warnings shown in the tray
(source: app.py `future_dated_report`, `size_mismatch_samples`, `shared_folder_problems`, `repath_events`)

- Files dated in the future: lane A refuses files whose date is ahead (a camera clock set wrong). The tray's advisory reads lane A's last scan, limited to projects ticked here (plus borrowed subfolders); size-mismatch and orphan reports for unticked projects are forgotten at the same time. If no selection is known, nothing is pruned.
- Size mismatches: up to 5 files that exist on the server under the same name at a different size (so this computer's version will never upload), each with local and server size.
- Shared or borrowed folders not working on this computer (commonly the LUT library): up to 10 sentences.
- Projects an admin renamed on the server whose local folder this computer moved to match: up to 10 events (old, new, when, whether Resolve was relinked).

## B-roll indexing failures
(source: app.py `broll_failed_items`)

- Up to 5 clips this computer could not index, each with its name and the error.

## Fleet jobs: status, gate and stop
(source: app.py `jobs_status`, `jobs_gate`, `stop_current_job`)

- The job runner's snapshot is shown locally and why it is taking no work (for example someone is at the keyboard, Resolve open, no capability, nothing offered, forced).
- Reported in the capabilities section as "taking work" yes/no plus the state code and, when the runner gives one, a detail sentence (for example which local work it is waiting on). "Nothing offered" counts as taking work (open gate, empty queue).
- "Stop the current job": stops the running fleet job the same way an admin cancel does; it is posted as cancelled and not retried.

## Undo button label and licence and sign-in shortcuts
(source: app.py `undo_last_fix_summary`, `undo_last_fix_available`, `undo_last_fix`, `open_licence_dialog`, `sign_in_again`)

- The undo button shows what the last clip-path change was, for example "158 clip path(s) in "FF4 ROUGH", 14:22" (for the open project, else the latest of any project); the button is offered only when there is something to undo. Pressing it runs "Undo the last clip-path change".
- "Show the licence again" opens the licence dialog however many times it is asked, if there is anything to accept.
- "Sign in again" re-runs the sign-in dialog while already signed in (a token the server revoked still looks valid locally).

## Restart the companion (Settings "RESTART NOW")
(source: app.py `restart_self`)

- Restarts the companion in place. Refused (returns false, nothing happens) when work a restart would kill is in flight, when running from source, or when the replacement fails to start.

## Remove a project from this computer (Settings "REMOVE '<project>'")
(source: app.py `removable_projects`, `removal_blockers`, `_removal_extra_checks`, `_note_removal_override`, `remove_project_from_machine`, `swap_p_to_local`)

- The list of removable projects is the projects ticked for this computer (managed mode only), with whether each is upload-only. Empty on a base rig, in unmanaged mode, or with no known selection.
- Before deleting anything, a safety gate asks (it fails closed: a check that cannot answer blocks):
  - It first re-fetches the plan from the dashboard (a failed fetch keeps the cached plan).
  - "that project is not ticked for this computer" if it is not in the list.
  - If part of this project is shared into another project still selected here: "part of this project ('<sub>') is shared into <borrower>, which is still selected here".
  - Lane A dry run for the project folder and any borrowed subfolders: "<N video files> have not been uploaded yet (e.g. a, b, c)" ("files" for upload-only), or "CCSync could not reach the server to check whether your footage has been uploaded".
  - Files changed after upload (modification times): "<N files> changed after they were uploaded, and a changed file does not upload again on an upload-only project (e.g. ...). Rename them first, so they upload as new files", or "CCSync could not check whether you changed a file after it was uploaded".
  - Same name, different size on the server: "<N files> share a name with a different file already on the server, so they will never upload (e.g. ...). Rename them first", or "CCSync could not check whether the server already holds a different file under the same name as one of yours".
  - Files no lane carries: "<N files> in this folder are not carried by any sync, so the server will never have them (e.g. ...)"; folder unreadable: "CCSync could not read this project's folder to check what is in it".
  - Future-dated files: "<N files> are dated in the future (a camera clock set wrong), which CCSync will not upload (e.g. ...). One a few hours ahead uploads by itself once that time passes; otherwise its modified date has to be reset to now (ask whoever looks after your computers) before it can upload".
  - Syncthing (not for upload-only): "the shared files for this project are only <P>% synced to the server" and "<N shared files> have not arrived on this computer yet", or "CCSync could not ask Syncthing whether this project is fully shared".
- Refusals of the removal itself: "no project given"; "not in managed mode"; "refusing on a wired computer: its tree IS the server tree"; drive out: "<drive> is disconnected, so nothing was removed. Plug it back in and try again."; not ticked; "unsafe project path '<rel>' -- nothing was deleted".
- Blocked without override: "'<rel>' still has work that has not reached the server, so nothing was deleted:\n  - <reason>\n ... Leave CCSync running until it is finished, then try again."
- Override (the dialog makes the editor type the project name; that dialog is the tray's): allowed; a warning is logged and the override (project, time, pending count, up to 4 reasons) rides the next report's safety section (at most 20 kept).
- Steps, stopping before deletion on any failure:
  1. Untick on the dashboard; failure: "could not untick on the dashboard (<message>) -- nothing was deleted".
  2. Remove the folder from the local Syncthing (a folder that was never there is fine); failure: "the project was unticked, but the local Syncthing folder could not be removed -- nothing was deleted. Try again in a minute."
  3. Delete `<local_root>/Projects/<rel>`. No local root: "the project was unticked, but local_root is not configured -- nothing was deleted". Outside the Projects folder: "refusing to delete <path> (outside <Projects>)". Already gone: "'<rel>' is no longer synced here (its folder was already gone)". Delete error: "'<rel>' was unticked and unshared, but some files could not be deleted (<error>). Delete the folder by hand -- it is safe now."
  4. Success: "'<rel>' removed from this computer. The server copy is untouched." The future-dated warning for that project is forgotten.
- "Finish grading" (swap the drive letter back to the local copy) is the same swap-to-local action used by repair.

## Who this computer reports as
(source: app.py `editor_identity`)

- The signed-in user name when a valid sign-in exists. With `require_login` on and nobody signed in: no name, so no report is sent. With `require_login` off: config `editor_name` (blank counts as none, so no report).

## Lane detail lines when sync is blocked
(source: app.py `_lane_pending_login_detail`, `_lane_config_problem_detail`, `_mark_lanes_*`, `eula_problem`)

- Sign-in needed: 'sign in required -- use the tray's "Sign in..." to authenticate before syncing'.
- Config problem: "NOT SYNCING: this computer isn't fully set up -- <first problem, or 'see companion.log'>".
- Licence not accepted: "NOT SYNCING: <licence problem sentence>".
- The licence check failing with an error is treated as accepted.

## The licence (EULA) gate inside the companion
(source: app.py `prompt_licence_acceptance`, `_licence_watch`, `_show_licence_dialog`)

- If nobody on this computer has accepted the current licence version, the lanes do not start (everything else runs).
- Automatic offer: starts 3 s after launch and retries every 60 s until the dialog has actually been shown once (accepted, declined or closed), or the licence is accepted elsewhere, or the companion stops. It waits while another CCSync window is open (logged once, then quietly).
- Dialog (title "... licence agreement"): "This computer is NOT SYNCING until someone here accepts the <product> licence agreement (version <V>).\n\nRead it below. Accepting records your agreement on this computer only, and syncing starts straight away." followed by the cleaned licence text.
- Declined or closed: "NOT SYNCING: the licence agreement was not accepted. <accept-licence sentence>." The automatic offer stops; the tray item is the way back.
- Accepted: the acceptance is recorded; the lanes start immediately (still subject to every other gate) and "Licence accepted, syncing is starting." is shown. If the record cannot be written: "Couldn't save your acceptance. Check disk space and try again."
- Build missing its licence document: "NOT SYNCING: this build is missing its licence document. <diagnostics sentence>." (no retry).
- If the dialog cannot be built (for example no desktop yet at logon), it is retried a minute later.

## Keeping the site manifest current
(source: app.py `_site_refresh_loop`)

- In managed mode, the site manifest (brand, drive phrase, feature flags) is fetched from the dashboard and saved; every 900 s after a success, every 120 s after a failure. Feature flags read the saved copy on every use, so a flag flipped by the owner reaches running companions within 15 minutes. Keys merged into the config at load take effect at the next start.

## Starting and stopping the lanes (the one gate)
(source: app.py `_lanes_refusal`, `_start_lanes`, `_stop_lanes`)

- The reasons lanes do not run, in order of precedence, each with the sentence shown:
  1. paused from the tray: "Syncing is paused from the tray."
  2. halted (this computer or the whole fleet): the halt sentence (see "Halts").
  3. config problem: the worst problem's sentence, else "This computer is not set up for syncing yet."
  4. licence not accepted: the licence problem sentence.
  5. drive absent: "PAUSED: <drive> is disconnected -- plug it back in and syncing resumes on its own".
  6. `sync_enabled` off: "This computer works straight off the server, so there is nothing to sync."
- Starting: first re-asserts a fleet halt's pause of Syncthing folders (on another thread), then:
  - paused: nothing starts;
  - halted: every lane shows the halt sentence;
  - config: every lane shows "NOT SYNCING: this computer isn't fully set up -- <problem>"; the log asks to fix the config file and restart;
  - licence: every lane shows "NOT SYNCING: <problem>";
  - drive absent: every lane shows the disconnected sentence (lanes start by themselves when the drive returns);
  - `sync_enabled` off: every lane shows "sync disabled: this computer works directly off the server"; nothing starts but this counts as started;
  - managed: start lane C, start the sequencer (which drives lanes A and B per project), start lane A's file watcher only (so change events reach the sequencer), and start the originals lane if lane B is enabled;
  - unmanaged: start every runnable lane on its own timer;
  - if `lane_b_enabled` is false, lane B shows "disabled: direct NAS access (lane_b_enabled=false)".
- Stopping (sign-out and shutdown): managed: stop the sequencer, lane C, lane A, lane B (which kills a running rclone) and the originals lane; unmanaged: stop every lane.

## Sign in and sign out (tray)
(source: app.py `sign_in`, `on_signed_in`, `sign_out`)

- Sign in with username and password, verified by the dashboard. On success: re-apply the role (config only), take any update offer that came back with the sign-in reply (including a reason the dashboard is withholding a build), and start the lanes if they have not started and sign-in is no longer blocking. Returns success or the error message.
- Sign out: drop the identity. If `require_login` is on and the lanes were running, stop them and show the "sign in required" lane detail. Reports stop because there is no identity.

## Updates: offers, installing, back-off and refusals
(source: app.py `upgrade_available`, `_standing_down_would_kill_work`, `apply_upgrade`, `_load_upgrade_state`, `_note_report_accepted`, `_upgrade_attempt_blocked`, `upgrade_refusal`, `_note_upgrade_refusal`, `_note_upgrade_failure`)

- The tray offers "Update now" only on a frozen (installed) build and only while the dashboard advertises a build different from this one (it may be older: a rollback).
- Work that blocks any restart or update ("stand-down"): any CCSync window open (the one-window slot is held), or a consolidate in progress.
- Installing (tray click, pushed update or unattended update):
  - no offer: nothing;
  - a window open: "Can't update while a CCSync window is open. Close it and try again.";
  - consolidate running: "Can't update while media is being copied in. Let it finish, then try again.";
  - (both suppressed on quiet retries);
  - otherwise "Installing v<version>…", then download, verify, swap the executable and restart; on failure "Update failed. You're still on v<current>, nothing is broken. <diagnostics sentence>."
- A ledger of update attempts is kept in the state folder (the upgrade module's file) so a restart does not reset the back-off:
  - Running the version the ledger was counting means it succeeded; the counter is cleared.
  - If this computer reverted off a build because it kept crashing ("crash-looped"), it never installs that build unattended again; only a different version or a person's click in the tray moves it on (logged once per version). Once the computer has moved past it to a newer build, the failure counters for it are cleared (the crash-looped mark stays).
  - If the crash-looped build is the one running (installed by hand), its mark is cleared.
  - Too many failed attempts at one version ("given up"; the maximum is in the upgrade module) stops unattended tries; the tray and the report say so.
  - Between failed attempts: the upgrade module's back-off curve (10 minutes, 1 hour, then 6 hours according to the code comments).
- The "reverted from" marker rides reports until one report is accepted, then is cleared.
- A refused offer (one the upgrade module will not install, for example below the signed minimum) is backed off on the same curve, in memory only, and is not counted as a failed attempt.
- The refused build is reported (version and reason, from the upgrade module).

## yt-dlp sidecar status
(source: app.py `ytdlp_report`)

- The yt-dlp manager's last daily check is reported as `sync_guard.ytdlp`; empty when there is no manager. The binary is never run for this.

## Transport health (reported)
(source: app.py `transport_health`)

- Syncthing connection paths (which peers are relayed rather than direct), orphan reports from lanes A and B, and lane A's express-upload counters (express failures are warnings and counters rather than errors).

## Job capabilities (reported every report)
(source: app.py `job_capabilities`)

- What this computer can do for fleet jobs (built by the capabilities module) with: the shared idle probe, whether the Resolve process is running (process check only, never a scripting connection), the open Resolve project, the Timeline Cards role block, until when the person has volunteered this computer, and the job gate (above). Withheld reporting categories are blanked here too.

## Reporting switches (privacy)
(source: app.py `telemetry_withheld`)

- The set of reporting categories withheld right now is the union of this computer's own switches and the site's (from the reporter, else computed from config and the cached site manifest). Used to blank the media tree, capabilities and journal ids.

## Lane B route (reported)
(source: app.py `lane_b_via`)

- Only on a computer with config `remote_down` set: "remote_down" while lane B pulls through the download route, "remote" when it is configured but not in use (refused for security reasons, or no pass yet). Omitted otherwise.

## The safety section of the report (`sync_guard`)
(source: app.py `sync_guard`)

- Always included where available: lane B's breaker, trash and halt report (from the lane); lane A's "skipped because it exists at a different size" counter; project folders that were here last pass and have gone (up to 20); project folders in no sync plan (once a scan has run); ingest staging bytes held; shared-folder problems; server rename events; the archive originals this computer has placed stand-ins for (always sent, even empty, at most 200, never absolute paths); the halt state; whether the dashboard is accepting this computer's reports (the reporter's health); clock skew against the dashboard (once a reply has carried the server time); background-thread crashes (when any); Syncthing folders kept paused because their filter list never arrived (up to 20); Syncthing conflict copies held here (reported only, never acted on); the Syncthing supervisor's incident (how long down, failed restarts; the code notes the dashboard does not read this key yet); watchdog restarts; overridden project removals (last 5, never drained); `project_rotation_seconds` when above 0; the update ledger (always, including all zeros: attempts, reverted-from, refused offer, number of starts on this version); yt-dlp state; loopback port state (always); YouTube clips downloaded but not in Resolve (only when something is pending or blocked); the drive state as a word (always, including "unknown"); free space on the sync drive and system drive; Resolve health (always); and finally the one "why is this computer not syncing" answer.
- Each part is isolated: one failing never removes the others.

## Free space measurement
(source: app.py `disk_snapshot`)

- Free space on the sync drive and the system drive is measured at most once per `dashboard_report_interval` (default 60 s, minimum 30 s), and reused on lighter reports.

## Put a moved project folder back (button)
(source: app.py `put_project_dir_back`)

- When lane A notices a ticked project's folder is not where expected but found elsewhere, a button moves it back (never automatic). It refuses if the target already exists and never deletes.
- Messages: "CCSync could not check where that folder is. See the log."; "CCSync cannot find that project folder anywhere on this computer. If you moved it to another drive, move it back by hand."; "CCSync is still starting up. Try again in a moment."; all failed: "CCSync could not move that folder back. Close Resolve and Explorer on it and try again."; some failed: "<N folders> put back; <M> could not be moved. Close Resolve and Explorer on them and try again."; success: "<N project folders> put back where CCSync expects them. Syncing starts again on the next pass."

## Ingest staging space (b-roll and music)
(source: app.py `ingest_staging_report`, `clear_finished_ingest_staging`)

- Bytes, batches and oldest time held in the ingest staging folders across both kinds are reported (re-measured at most every 30 s).
- "Clear finished staging" button: deletes every staging folder whose batch has ended (never the running one). Messages: "Cleared <N finished staging folders>, <X.X> GB."; if only never-run drops are held: "The staging on this computer is <N drops> that were never indexed, so there is nothing FINISHED to clear. Those clear themselves once they are past the staging retention window, or as soon as the drop is run."; otherwise "There is no finished staging to clear on this computer."

## "Why is this computer not syncing?" (one sentence, `sync_guard.blocked`)
(source: app.py `blocked_report`, `_blocked_candidate`, `_lane_stall_record`)

- The first applying reason in this order is reported with a sentence and a "since" time (the time the condition began where known, else the first report that named it; kept in memory only):
  1. not signed in: "Nobody is signed in to CCSync on this computer, so nothing is syncing"
  2. licence pending: the licence sentence
  3. clock skew at or above the reporter's warning threshold: "This computer's clock is <N ahead of/behind> the server's, so proxy download will not transfer anything"
  4. drive absent, 5. drive not answering, 6. drive misplaced: the root guard's sentence for that state
  7. disk full: "Not downloading proxies: <reason or 'this drive is nearly full'>"
  8. fleet halt, 9. local halt: the halt sentence
  10. paused: "Syncing is paused from this computer's tray"
  11. breaker tripped: "Proxy download is stopped as a safety measure: <editor reason>"
  12. no selection: "No projects are ticked for this computer[ (<detail>)]"
  13. project folder moved: "Your project folder for <name> is not where CCSync expects it. Did you rename or move it?[ (<N> project folders are missing)]"
  14. folders unfiltered: "<N projects> are not sharing yet - waiting for their filter list: <up to 3 project labels>"
  15. lane stalled (from the lane's report, else the state file `lane_stall.json`; ignored if recovered or older than the lane module's maximum age): "<Lane words> stopped making progress for <N minutes> and was restarted"
  16. Syncthing down (not on a computer with sync off): "The sync engine (Syncthing) is not running on this computer, so project files are not being shared"
  17. transport offline (both rclone lanes in error): "This computer cannot reach the server: <classified error, or 'upload and proxy download are both failing'>"
- Nothing applying: the key is absent, which means "syncing".

## Resume proxy download (tray "Resume proxy download", and the dashboard's RESUME)
(source: app.py `resume_lane_b`, `_resume_lane_b_breaker`, `_report_off_cycle`)

- Clears the free-space park first, then the lane B circuit breaker. If neither was set (or this dashboard request was already applied): "proxy download is not stopped". Error: "could not resume proxy download -- see the log".
- A dashboard-requested resume carries a request id and is applied once only, even though the request rides every reply until a report shows the breaker clear (a later trip needs a fresh click). The applied id is remembered on disk by the breaker.
- On success: lane B is armed for an immediate turn, the sequencer runs a pass now, and an extra light report is sent at once so the dashboard can drop its request. Message: "Proxy download resumed."

## Halts: stopping all sync (tray "Stop syncing" and the fleet halt)
(source: app.py `halt_all_sync`, `release_halt`, `_halt_detail`, `_release_lane_c_folders`, `_reassert_halt_pause_soon`, `_reassert_halt_pause`)

- A halt is a stop, not a pause: lanes A and B stop (including the express upload), every Syncthing folder is paused through Syncthing's own interface, and the halt is saved to disk so a restart does not undo it. Scope is "local" (this computer) or "fleet" (an admin's halt for every computer).
- Every lane shows "STOPPED: syncing is STOPPED on this computer[ -- <reason>]" or, for a fleet halt, "STOPPED: your administrator stopped syncing for the whole fleet[ -- <reason>]".
- On a new halt: notification "SYNCING IS STOPPED on this computer.\n<reason>\nNothing is uploading, downloading or sharing until it is started again." (title "... syncing stopped"). Returns "Syncing is stopped."
- The Syncthing folders paused include the project folders from the cached plan even if the sequencer never ran in this process; folders already attempted are not written twice.
- While halted, every start of the lanes re-pauses Syncthing folders that are not paused, on a background thread (one at a time), stopping early if the halt is released meanwhile.
- Release: a fleet halt cannot be released from the tray (only by the dashboard's own release, applied from the report reply). On release, Syncthing folders are released through the sequencer (folders whose filter list never arrived stay paused; shared libraries are re-reconciled), the express upload follows the tray pause, and the lanes start (subject to every other gate). With no sequencer (unmanaged), folders are simply un-paused.
- Only the Syncthing folders this computer is assigned (its projects plus the fleet-wide shared asset libraries) are paused or released; other tools' folders on the same Syncthing are left alone.

## Update offers and unattended updates
(source: app.py `_on_upgrade_available`, `_maybe_auto_update`, `_run_auto_update`)

- When a new offer arrives: a notification with the upgrade module's offer wording (it never calls an older build an "update"). Not shown for a build this computer reverted off because it kept crashing (the tray menu still offers it).
- Site feature flag `auto_update` (off by default; fails closed if the site manifest is missing): when on, a NEWER offered build is installed without a click. An older build (rollback) is never taken unattended; it stays in the tray.
- The unattended attempt is retried from later reports while the same version is still offered: after a stand-down 90 s, after "no offer" 600 s, after a refused offer the refusal back-off, after a failed install the ledger back-off; the persistent blocks (crash-looped, given up, backing off) apply. It stops if the offer is withdrawn or replaced, or the site turns `auto_update` off. Refusal balloons are shown only on the first attempt.

## Pushed update (an admin's "UPDATE NOW" for this computer)
(source: app.py `_apply_pushed_update`, `_run_pushed_update`)

- Arrives in the report reply as `commands.upgrade` with `apply`, `version`, `requested_at`, `requested_by`.
- Ignored when the version is blank or already running. If the offer in hand (already signature- and floor-checked by the upgrade module) is not that version, it is ignored and logged once per version: "pushed update to v<X> IGNORED: this machine is not being offered that build".
- Otherwise installs exactly like the tray click (same stand-down rules). First attempt per request: notification "Your administrator is updating CCSync to v<X>." A repeat of the same request is retried after 90 s (stand-down), 600 s (no offer), or the failure or refusal back-off, with quiet refusal balloons. A new request for the same version (new `requested_at`) gets a fresh attempt at once. Persistent blocks apply.
- It never downloads anything other than the signed offer and cannot roll a computer back past its signed minimum (those checks belong to the upgrade module).

## Admin resumes proxy download from the dashboard
(source: app.py `_apply_resume_lane_b`)

- `commands.resume_lane_b` with `apply`, `requested_by`, `requested_at`. Applied only if the breaker is tripped; uses the one-shot resume above with the request time as id.
- On success: notification "<admin> checked the server and started proxy download again." (title "... proxy download resumed").

## Admin changes this computer's fleet-work settings (account page)
(source: app.py `_apply_machine_settings_request`)

- `commands.machine_settings` (rides every reply until answered). Applied through the machine-settings module, which writes only the asked keys (`jobs_enabled`, `jobs_kinds`) to the config file and records the answer in a ledger in the state folder. A redelivered request is answered from the ledger and writes nothing. Without a state folder, the request is not applied.
- Takes effect at the next start (nothing restarts).
- On a newly applied change: one notification (title "... fleet work settings changed") with the module's sentence naming who asked ("Your administrator" if blank, name cut to 64 characters). Refusals are logged only.

## Admin moves a file on the server (file moves)
(source: app.py `_apply_file_moves`, `_queue_file_move_answer`, `_file_move_results`)

- `commands.file_moves`: a list (capped at the ledger's maximum entries); malformed entries are logged and skipped.
- Each move is applied once; the on-disk ledger answers redeliveries with the earlier outcome (a move interrupted mid-way is resumed, not answered). A failed move that is still retryable answers "retrying" until its next attempt is due.
- If the drive is out or no local root: answer "waiting for the sync drive (<drive phrase>)" with state "retrying" and 0 attempts, at most once every 30 minutes per move (so the dashboard's 7-day expiry does not drop it).
- Otherwise the local copy (and its proxies) is moved the same way (the file-move module does the work, given the projects this computer syncs including borrowed subfolders, and a listing of the server files at the destination through `remote` + `remote_root`). Then every Resolve clip that pointed at the old path is repointed (through the media pool walk in the file-move module). If no open project matched, the relink stays pending and is retried on every Resolve project change.
- A move into a project not synced here is a done move with its own word `not_synced_here`, sent only to dashboards 0.7.50 or later.
- Answers queued for the next report: id, ok, detail (up to 512 characters), and optionally state ("retrying", "blocked", `not_synced_here`), attempts and `relink_pending`.
- Notifications:
  - moved and relinked: "<who> moved '<name>' to <where> on the server. Your copy followed and Resolve was relinked." (title "... file moved");
  - moved, relink pending: "... Your copy followed. The clip will reconnect the next time you open that project in Resolve.";
  - first failed attempt: "<who> moved '<name>' to <where> on the server, but your copy could not follow yet: <detail>. Nothing was deleted and CCSync will keep trying." (title "... file move needs attention");
  - given up (blocked): "Your copy of '<name>' still could not be moved to <where> after a week of trying: <detail>. Nothing was deleted; ask your admin." (title "... file move blocked").
- Nothing in this path deletes.

## Admin undoes a clip-path change from the dashboard (Resolve undo)
(source: app.py `_resolve_journals`, `_resolve_undo_results`, `_queue_resolve_undo_answer`, `_apply_resolve_undo`)

- Each report lists this computer's recorded clip-path change journals (names and counts only, never the paths).
- `commands.resolve_undo`: up to 8 per reply. A masked journal id is mapped back (see above). Each request is applied once; the ledger answers redeliveries, except those still "retrying".
- The undo replays the same journal as the tray's undo. If it cannot run yet (Resolve closed, a different project open) it answers "retrying"; after a week of retrying it answers "failed" with "(this computer has been unable to do it for a week)".
- On success: notification "<who> put back the clip paths CC Sync changed in Resolve." (title "... clip paths put back").
- When the Resolve-project reporting category is withheld at report time, the answer's detail is reworded to hide the project.

## Clips that went offline because the server moved them
(source: app.py `_relink_moved_result`, `_relink_pending_moves`, `_on_moved_clip_missing`, `_show_moved_clip_dialog`, `_relink_moved`)

- On every Resolve project change, pending move relinks are retried in one media pool walk, but only for moves whose new file exists here. Each that matches is cleared and re-answered to the dashboard.
- When the watcher sees a missing clip that this computer moved on the server's instruction, once per move per process: notification "'<name>' moved on the server. CCSync can repoint Resolve to where it is now." (title "... this clip moved") and then a dialog:
  - if the new file is not here yet: notification "That clip has not finished moving on this computer yet. CCSync will offer to repoint Resolve once it has.";
  - if another CCSync window is open: no dialog;
  - dialog (title "... this clip moved on the server"): "'<name>' is offline in this project because it was moved on the server.\n\nIt is now at:\n  <new path>\n\nYour copy has already been moved to match. CCSync can point this project's clips at the new location for you. Nothing is deleted and the change is journalled, so it can be undone." Button "RELINK IT" (and cancel). Result notification: the relink outcome, or "Nothing in this project pointed at the old location."
- Path comparison is Unicode- and case-folded (in the file-move module) so macOS names match.

## Fleet halt from the dashboard
(source: app.py `_apply_fleet_halt`)

- `commands.halt` on every reply is passed to the halt latch. When it newly engages: the full halt (above) with fleet scope. When the dashboard releases it: Syncthing folders are released through the filtered path, the express upload follows the tray pause, the lanes start, and the notification "Your administrator started syncing again." (title "... syncing resumed") is shown.

## Sequencer state for display
(source: app.py `sequencer_state`)

- The sequencer's state word and its human detail sentence are read for the tray, diagnostics and the "no projects ticked" reason; blank in unmanaged mode.

## Diagnostics: build, copy, upload
(source: app.py `_diagnostic_log_tail`, `_diagnostics_state_path`, `_read_diagnostics_state`, `_write_diagnostics_state`, `_upload_diagnostics*`, `_note_lane_error_diagnostics`, `_note_lane_error_states`, `_apply_diagnostics_request`, `_settle_diagnostics_request`, `_resolve_health_text`, `build_diagnostics`, `_redact_diagnostics`, `_known_project_names`, `_redaction_roots`, `_withheld_undo_detail`, `_resolve_bridge_text`, `_token_expiry_text`, `copy_diagnostics`)

- The diagnostics bundle is plain text beginning "=== CCSYNC DIAGNOSTICS ===", each line fault-isolated ("<failed: ...>" if a part errors). Contents:
  - time, companion version, platform, CPU architecture, whether it is an installed (frozen) build, config file path, log file path, effective mode, signed-in user (or "NOT SIGNED IN"), token expiry ("(no token)", "never (non-expiring token; nominal <date>)", or "<date> (<hours>h from now)"), sync enabled, paused, managed mode, lanes started, `local_root`, sync drive state (plus whether the missing-root problem was demoted, and whether macOS is blocking access), remote and remote root, download route (`remote_down`, its root and what lane B last used), `dashboard_url`, whether rclone is available, the Resolve project, the Resolve bridge ("never polled this session", "connected", or "NOT CONNECTED -- <reason>", plus whether it has connected this session), and a Resolve media line ("no timeline scan has completed yet (is Resolve open?)" or counts: outside the tree, on a broken mapping, missing on disk, "skipped for now (30 min)", skipped ever, last scan time);
  - updates: starts on this version, last attempted build, failed attempts with last error and time, "GIVEN UP on that build: it kept crashing and was rolled back (do not install it by hand)" or "GIVEN UP on that build: it has failed N times", "rolled back automatically from v<X> (it kept crashing)", "REFUSING v<X> since <time>: <reason>", and the rollback copy path or "none";
  - config problems ("ERROR: ...") and warnings;
  - sequencer state, detail and selected project folders;
  - fleet jobs: gate state, offered ids, the job held, Whisper capability, mounts, idle seconds ("None = cannot tell = not idle");
  - every lane's full status;
  - Syncthing: last cached state and detail, plus one live "api answers right now" ping;
  - transport health, with a "RELAYED: N Syncthing device(s) are NOT on a direct path" line when relevant;
  - last dashboard report: last accepted time (or "NEVER (nothing this computer has sent was accepted)"), last status, failures in a row, clock versus the server ("+Ns (this computer is AHEAD/BEHIND)" or "not measured yet");
  - background task crash reports: folder, count, and recent ones;
  - watchdog restarts per loop for 24 h and the last hour, and the record path;
  - the last 40 lines of the log (read from at most the last 64 KB).
- Redaction: if this computer or the site withholds any of the "Resolve project", "local manifest" or "media tree" categories, every known Resolve project name (current, last seen, ignored projects, every journal's project name and folder name) becomes `<project>` and every path under `local_root`, `remote_root`, `canonical_prefix`, `jobs_vault_root`, `jobs_media_root`, `jobs_pool_root`, `cards_vault_root`, the resolved local root and the undo journal folder becomes `<root>/<file>`, with a closing note naming the withheld categories. If redaction fails, the whole bundle is replaced by a one-line "withheld" notice.
- "Copy diagnostics" (tray/Settings button):
  - Normal: copies the bundle to the clipboard, uploads it to the dashboard in the background, and notifies "Diagnostics copied, and sent to your admin's dashboard."
  - Another CCSync window open: writes it to the log, uploads it, and notifies "Another CCSync window is open, so the diagnostics went to the log and to your admin's dashboard instead of the clipboard."
  - Clipboard error: logs it, uploads it, notifies "Couldn't reach the clipboard. The diagnostics were written to the log and sent to your admin's dashboard."
- Upload rules: never without a verified identity (signed in, or `editor_name` with login not required); errors are swallowed.
- Automatic upload when a lane FALLS INTO error (not while it stays there), at most once per lane per hour; the lane states and send times are kept in `<state>/diagnostics_sent.json`, written before the upload.
- Admin's "ASK THIS MACHINE WHY" (`commands.diagnostics` with `requested_at`, `requested_by`): uploaded once per request. One request in flight at a time. The request is marked answered on disk only after a successful upload; a failed upload may be retried on a redelivery after 300 s.

## Resolve bridge state for the tray
(source: app.py `resolve_bridge_state`)

- Whether the Resolve connection has ever connected this session, whether it is up now, and the reason; read from a cache, never by contacting Resolve.

## Lane statuses (tray and report)
(source: app.py `lane_statuses`)

- Each lane's status. In managed mode the project a lane is working on is reported as the dashboard's project id (slug) rather than the folder path; a borrowed folder is reported under the borrowing project.

## Sync now (doing it)
(source: app.py `sync_now`, `_runnable_lanes`)

- After the checks above: managed mode asks the sequencer for an immediate pass (failure: "CCSync could not start a sync pass. <open the log sentence>."); unmanaged mode runs every runnable lane once in turn (lane B is skipped when `lane_b_enabled` is false).

## Pause interplay with the express upload
(source: app.py `_set_express_paused`, `_toggle_express_pause`, `is_paused`, `_login_gate_blocks_sync`)

- Lane A's (and, if it has one, lane B's) express path is paused and resumed with the tray pause, a drive outage and a halt.
- Sign-in blocks sync exactly when `require_login` is on and there is no valid local sign-in.

## Pause and resume syncing (tray toggle)
(source: app.py `toggle_pause`)

- Flips the pause state. With `sync_enabled` off it changes nothing else.
- Resuming while sign-in is required and nobody is signed in: lanes show the sign-in detail and the notification "You're not signed in, so nothing will sync. Right-click the tray icon → Sign in…" is shown; nothing starts.
- Managed: pauses or resumes the sequencer's rotation and lane A's express upload; on resume, wakes the originals lane. Syncthing (lane C) keeps running through an ordinary pause.
- Unmanaged: stops all lanes, or starts them through the one gate.
- The pause is in memory only (not saved; a restart resumes syncing).

## Start-up sequence (after construction)
(source: app.py `start`)

1. Re-assert a persisted halt's Syncthing pauses in the background.
2. Lanes: a config problem marks lanes misconfigured; else a missing drive defers them (they start when it appears); else if sign-in is required and missing, lanes show "sign in required"; else the one gate starts them.
3. Start the reporter, the local media manifest cache, the media-tree loop.
4. In the background: report (never delete) partial copies left by an interrupted FIX ALL (the fixer module's sweep); sweep old Resolve rollback exports (the journal module's 60-day sweep loop).
5. Start the sign-in expiry watcher, and (managed) the site-manifest refresh loop.
6. Start the timeline watcher thread.
7. Start the proxy generator, b-roll ingest, music ingest, fleet job runner, Footage Sorter card reporter, sorter volume reporter and ledger outbox (one guard around all of these; a failure is logged as "failed to start the proxy generator").
8. Start the Timeline Cards role and the YouTube importer, each separately guarded.
9. Each separately guarded, in order: shutdown guard, keep-awake, LUT/stills link, root guard, the unreadable computer-id warning, the loopback server (port 8899), the field backup page, the yt-dlp manager, the Resolve menu scripts install, the originals request inbox, the unopened-projects sweep, and last the thread watchdog.

## Computer id file unreadable
(source: app.py `_warn_if_machine_id_is_unreadable`)

- Once per run, if this computer's id file cannot be read: notification (title "... this computer's id") "CCSync cannot read this computer's id file (<file name>). Syncing is not affected, but this computer cannot be recognised again if it is renamed. The file is repairable and CCSync will not overwrite it on its own: your tray's Settings window offers the repair, and your admin may want to look at the old file first." Reports then carry no machine id.

## Resolve menu scripts (originals on request)
(source: app.py `_start_resolve_menu_install`, `_start_originals_inbox`)

- At every start, in the background, writes the "request originals" menu scripts into Resolve's per-user Scripts folder (no feature flag; no Resolve call). The result is logged and kept. A build missing the installer module logs a warning and skips it.
- The originals inbox answers request files those menu scripts write (records the pick on the dashboard, labelled "via resolve"; a notification titled "... originals" can be shown; the originals lane is woken). It runs whether or not sync is paused. Only in managed mode.

## Unopened-projects sweep
(source: app.py `_start_unopened_scan`, `_unopened_scan_ready`, `_unopened_scan_known_rels`, `_unopened_scan_libraries`, `unopened_out_of_tree`, and its construction)

- A background sweep reads every project in this computer's Resolve libraries (not only the open one) for clips that exist only on this computer. Interval from the unopened-scan module's config reading.
- It does not run while the local root is broken, the drive is out, a drive swap is in progress or the drive letter points at the server.
- Known project folders are this computer's plan (including borrowed subfolders) plus every project marker folder on disk.
- Libraries: Resolve's database list is asked for only when the last timeline poll found Resolve connected; otherwise the module discovers libraries from config alone.
- It can show a balloon telling the editor to press FIX ALL, only when `popup_enabled` is on; the report carries the findings regardless.
- The tray and Settings list the flagged projects other than the one open now.

## Loopback server for "Send to Resolve" (port 8899)
(source: app.py `_start_broll_server`, `_start_broll_server_locked`, `_note_loopback_state`, `loopback_report`, `retry_loopback_bind`, `_ytdl_deps`)

- Started at launch (if the loopback module says it is enabled). It serves the b-roll and music web pages' Send to Resolve, the b-roll and music ingest routes (sharing the same ingestor objects) and the local YouTube download routes.
- Its state is always reported: enabled, bound, port, error ("" when bound or switched off; otherwise the last bind error or "the port could not be taken") and since when it has failed.
- If the port could not be taken, it is retried on the media-tree tick: first after max(`media_tree_refresh_interval`, 60 s), doubling up to 30 minutes while the error stays the same; a different error resets the wait. Never retaken during shutdown.
- Local YouTube downloads are given: the yt-dlp manager's cached check, the verified editor identity (never the raw config name), this computer's project plan (a project not synced here is refused), the sign-in token, and whether the drive is present. If these cannot be built, the computer advertises no local download ability and the server downloads instead.

## Field backup page
(source: app.py `_start_field_server`, `field_page_url`)

- When the field backup service is enabled, a local web page is served (its own port, from the field-server module); the tray's "Field backup..." opens it. A taken port loses only this page. No URL when off or not bound.

## Resolve LUT and stills folders
(source: app.py `_start_lut_link`, `_lut_link_loop`, `stray_lut_count`)

- On every computer including the base rig. If both the LUT link and stills features are off in config, nothing runs ("Resolve preference sync disabled by config").
- Every `lut_check_interval` seconds (default 900; 0 or less means 900): check and repair the Resolve LUT folder link to the shared library; check the stills folder (and keep its result, see "Stills folder check"); count LUTs on this computer that are not in the shared library (shown in the tray).

## Missing proxies and YouTube import (readers)
(source: app.py `proxy_gap`, `proxy_coverage`, `youtube_import_status`)

- The tray's missing-proxies line, the report's proxy coverage section and the report's YouTube import section are cached reads from their modules; empty when the module failed to build.

## Work-progress windows (b-roll indexing, music indexing, proxies)
(source: app.py `_open_work_window`, `close_work_window`, `show_ingest_progress`, `_broll_progress_model`, `show_music_ingest_progress`, `_music_ingest_window_action`, `_ingest_window_action`, `show_proxy_progress`, `_proxy_progress_model`)

- Only one work window at a time. Opening a different one closes the open one (waiting up to 3 s for it to close); opening the same one while it is open does nothing.
- "INDEXING B-ROLL": "Your clips are indexed on this computer and uploaded to the archive. Closing this window does not stop it." Opens by tray action, or by itself when a batch starts crunching or downloading a model. Shows up to 5 failed clips with their reasons. Buttons map to: pause, resume, start now, cancel (the same actions as the tray).
- "INDEXING MUSIC": "Your tracks are analysed on this computer and uploaded to the library. Closing this window does not stop it." Same buttons and behaviour for music.
- "MAKING PROXIES": "Proxies let the rest of the team see this footage. Closing this window does not stop them." Shows the clip being encoded (file name only) and its percent, done out of total, failed count, the generator's own time-left estimate, and when not encoding the reason it is waiting (the sentences listed under "Proxy-generator status sentences"). Button: "cancel" while encoding, otherwise "start now". Shown as finished when nothing is left.

## Who gets the GPU: indexing, proxies and fleet jobs
(source: app.py `_jobs_block_reason`, `_proxy_block_reason`)

- Proxy generation does not run while there is any config problem; and it stands aside (with the ingestor's own reason, for example "waiting: indexing b-roll first") while a b-roll batch is crunching.
- Fleet jobs are not taken while a b-roll or music batch is busy (that ingestor's reason) or while proxies are being encoded ("waiting: making proxies"). A config problem does not block fleet jobs.

## B-roll and music indexing (tray actions)
(source: app.py `_ingest_deps`, `broll_ingest_status`, `broll_ingest_view`, `music_ingest_status`, `music_ingest_view`, `index_*_now`, `pause_*_ingest`, `resume_*_ingest`, `cancel_*_ingest`)

- Indexing claims are made with the verified editor identity, the sign-in token and this computer's network name; signing out stops new claims at once.
- Reported sections `broll_ingest` and `music_ingest` are empty when nothing is happening.
- "Index now" (b-roll / music): starts the current batch without waiting for the computer to be idle. Notifications: "Indexing the b-roll batch now. It keeps going while you work." / "Analysing the music batch now. It keeps going while you work." Not set up: "B-roll indexing is not set up on this computer." / "Music indexing is not set up on this computer."
- Pause: "B-roll indexing paused. Nothing already indexed is lost." / "Music indexing paused. Nothing already indexed is lost."
- Resume: "B-roll indexing will carry on from where it stopped." / "Music indexing will carry on from where it stopped."
- Cancel (only when a batch exists; skipped silently if another CCSync window is open): confirmation dialog "STOP INDEXING THIS B-ROLL BATCH" ("<done> of <total> clips are already in the archive and they stay there.\n\nThe rest will not be indexed. The clips themselves are not deleted.") or "STOP INDEXING THIS MUSIC BATCH" (tracks, library), button "STOP INDEXING". On confirm: "B-roll indexing stopped." / "Music indexing stopped."

## Proxy generation (tray actions)
(source: app.py `generate_proxies_now`, `stop_proxy_generation`, `proxy_history_report`, `_proxy_window_action`)

- "Make proxies now": scans and encodes without waiting for idle, opens the "MAKING PROXIES" window, and notifies "Making the missing proxies now. It stops on its own when they're done." Not set up: "Proxy generation is not set up on this computer."
- "Stop making proxies": cancels the run (the queue is rebuilt on the next scan); "Stopped making proxies."
- "Proxy history": renders the generator's history ledger to a text file and returns its path for the tray to open; failure: "The proxy history could not be written."

## Share this computer's LUTs with the team (tray action)
(source: app.py `share_stray_luts`)

- Not set up: "LUT sharing is not set up on this computer."; none to share: "No LUTs to share -- the library already has everything here."; library not synced yet: "The shared LUT library hasn't synced to this computer yet -- try again later."; another window open: "Another CCSync window is open. Close it and try sharing again."
- Confirmation "Share these LUTs with the team?": "<N LUTs> on this computer (<X.X> MB) are not in the shared library.\n\nCopying them to <library> puts them on every editor's computer. Your own copies stay where they are." plus up to 12 names ("… and N more"). Button "SHARE".
- Copies (never moves) them into the library, then re-counts. Result: "Shared <N LUTs> with the team." plus " <E> could not be copied -- see the log." when some failed.

## Power guards: keep awake and warn at shutdown
(source: app.py `_start_keep_awake`, `_start_shutdown_guard`, `_shutdown_block_reason`, `_lane_peer_states`)

- Config `keep_awake_while_syncing` (default true): stop the idle timer sleeping the computer while there is a reason (below).
- Config `shutdown_warning_enabled` (default true): Windows shows "still syncing" with the reason on the shutdown screen. On macOS the guard turns a logout or service stop (SIGTERM) into a clean companion shutdown. When Windows ends the session, the run is marked as a clean exit (not a crash).
- The reason, or none: none while paused, with a config problem, or with the drive out. Otherwise: a lane actually moving data (the pending tracker ignores a lane reporting "syncing" with nothing moving, and Syncthing's backlog when it has no connected peers); else a b-roll batch in progress; else a proxy encode in progress.

## Leftovers from interrupted copies (start-up sweep)
(source: app.py `_sweep_stale_tmp_files`, `_recheck_orphan_reservations`)

- One walk of the tree at start, in the background:
  - partial copies from an interrupted FIX ALL are reported, never deleted: "Found <N half-copied files> from an interrupted copy. Nothing was deleted. <diagnostics sentence>."
  - empty placeholder files reserved by an interrupted copy are deleted (logged, no notification); ones too recent to judge are re-checked once after the fixer's idle time plus 1 s;
  - half-made proxy files (`.partial`) from killed encodes are logged, never deleted.

## Sign-in expiry watcher
(source: app.py `_identity_expired_text`, `_identity_watch_loop`)

- Every `identity_check_interval` seconds (default 60) checks whether the local sign-in is still valid.
- When it becomes invalid: if sign-in is required and lanes were running, they stop and show "sign in required"; notification: if the measured clock skew is at or above the reporter's threshold, "This computer's clock is <N ahead of/behind> the server's, which is why your CCSync sign-in looks expired. Fix the clock (Windows: Date and time -> Sync now) and syncing will start again."; otherwise "Your CCSync sign-in has expired, so syncing has stopped. Right-click the tray icon → Sign in…".
- When it becomes valid again: lanes start (through the one gate).

## Shutdown
(source: app.py `shutdown`, `_shutdown_teardown`, `_arm_ui_shutdown_backstop`, `_hard_exit_if_ui_wedged`)

- Runs once. A second call waits up to 40 s for the first to finish (a call from the thread already doing it returns at once).
- Order: mark the run as a clean exit (so the next start does not report a crash); signal every loop to stop; stop the VP9 guard, the watchdog, the drive reminder (its record is kept), the shutdown and keep-awake guards and the root guard; stop the fleet job runner (its job lease expires and goes back to the fleet), sorter reporters and outbox, the Timeline Cards role, b-roll ingest (its batch resumes from the last checkpoint on the next start), close any work window, stop the proxy generator, YouTube importer, yt-dlp manager and originals inbox; stop the lanes; stop the reporter and the manifest cache; stop the media-tree and sign-in loops; release port 8899 and the field backup page; wait up to 5 s each for the watcher and media-tree loops, the proxy generator, b-roll ingest and YouTube importer; stop the UI dispatcher (macOS); record a clean shutdown for the crash-loop counter.
- macOS only: if the UI loop is still running 10 s later, the process exits hard (logged, with the names of windows still open), so a wedged window cannot keep the single-instance slot forever.

## Crash-loop rollback of a bad update
(source: app.py `_revert_crashing_build`, `run`)

- Every start is counted per version (the upgrade module's version marker). If the upgrade module says this build is crash-looping (the code's log line: restarted N times in under the module's window; the comment says three times in ten minutes), the companion puts the previous build back and exits before starting anything, marking the run clean.
- If it cannot roll back (no rollback copy, unknown previous version, the signed minimum version, a failed restore), it logs why and carries on.
- After a rollback, once: notification 3 s after start "The last update kept crashing, so CCSync went back to v<version>." The "reverted from" version is reported until a report is accepted.

## The main run (what happens after the process may run)
(source: app.py `CompanionApp.run`, `_log_tray_state`)

- Sets up logging and logs the version and config path. Logs a warning if the Tk safety guard could not be installed.
- Counts this start for the crash-loop check; loads the update ledger; may roll back (above).
- Logs every config problem ("config has N problem(s) that STOP syncing -- fix these in <config path>:") and warning, or "config OK: remote=... remote_root=... local_root=...".
- Starts the main-thread UI dispatcher (macOS; dialogs then queue for the main thread), sets the macOS menu-bar-only policy, runs the start-up sequence, then shows the tray icon (the tray module). If the tray module cannot be imported or fails, the companion runs without a tray ("running headless").
- Logs whether the Windows tray icon actually registered with the desktop ("tray icon started and registered with the desktop" or "...is NOT in the notification area yet -- registration is being retried").
- Start-up notifications:
  - config problem: "NOT SYNCING: CCSync isn't fully set up on this computer. <diagnostics sentence>."
  - otherwise licence not accepted: "NOT SYNCING: <licence problem>" and the licence offer loop starts.
  - first start after a self-update: "Update complete. Now running v<version>." (3 s after start), plus the macOS Full Disk Access check.
- Keeps the previous executable (rollback copy) until this build proves healthy: one accepted report, or (per the comment) an hour of uptime when the dashboard is unreachable (the upgrade module decides).
- Marks the run as booted for the crash supervisor and start guard.
- Waits until asked to stop (on macOS the main thread runs the UI loop). Ctrl+C (console runs) shuts down. Always ends with shutdown and stopping the tray icon.

## Executable entry and its command-line flags
(source: app.py module `run`, `setup_resolve_prefs_cli`)

- `--setup-resolve-prefs [--wait-for-resolve SECONDS]`: used by the installers; does not take the single-instance lock or start a tray.
  - If Resolve is running, prints "DaVinci Resolve is running. It rewrites its own preferences when it exits, so anything set now would be thrown away.\n  --> Please quit DaVinci Resolve. This will continue automatically." and checks every 3 s until it quits or SECONDS pass (default 0: no wait). Timed out: "Still running -- skipping. The companion will apply these settings the next time Resolve is closed." and exit code 1.
  - Then turns Resolve's "External scripting using" to Local only if it is None (never overrides Local or Network, never creates the file): prints "External scripting: set to Local", "already on", or "not set (<reason>) -- in Resolve, Preferences > System > General > External scripting using: Local".
  - Then points Resolve at the shared LUT library and the shared stills gallery: each prints "set", "already correct", "not set (<message>)" or "failed (<error>)".
  - Exit code 0 if either LUT or stills was set or already correct, else 1 (scripting is not counted).
- The music "Send to Resolve" worker flag (from the music worker module): the executable re-enters as a killable child process for one Resolve call; no lock, no config, no tray.
- The supervisor flag: re-enters as the crash supervisor.
- Otherwise:
  1. Claims the app's identity for the Windows taskbar (branded icon).
  2. Loads the config and writes the start guard's "started" marker.
  3. Sets up logging (fallback on failure).
  4. Installs the local crash reporter (writes `~/.ccsync/crashes/<time>.json` for every unhandled exception with the log tail; sending to a network service is opt-in via config `crash_reporting` and `crash_dsn` and needs a library not in the frozen build; DORMANT in the shipped build).
  5. Points HTTPS at a bundled certificate store (for the frozen macOS build; never overrides `SSL_CERT_FILE` if already set).
  6. Windows: removes expired certificates from the trust used by this process.
  7. Repairs permissions on `~/.ccsync` if an older installer stripped them.
  8. Logs config problems.
  9. Takes the single-instance slot (see that section); tells the start guard whether it got it; if not, shows "already running" and exits.
  10. Installs the native-crash recorder (a run marker for this process and a thread dump on a hard abort in the crashes folder) and starts the crash supervisor (which relaunches a companion that died without shutting down; limits are in that module).
  11. Builds and runs the app; an exception during start-up or run is logged as "ccsync-companion crashed during startup/run" and re-raised.

## Looks redundant or overlapping

- Pause (tray toggle, in memory, leaves Syncthing running, lost on restart), local halt (persisted, stops Syncthing too), `sync_enabled = false`, and the sign-in gate are four separate ways to stop syncing, each with its own lane detail sentence.
- Three ways to install an update (tray click, an admin's pushed update, the site's unattended `auto_update`), with two near-identical retry loops (`_run_pushed_update` and `_run_auto_update`), two sets of in-memory retry state, plus a persisted attempts ledger, a refusal back-off and the crash-loop revert.
- Out-of-tree and wrong-path clip detection runs from five places: the timeline watcher (every 3 s), the media-pool walk (every 120 s), "Scan whole project", "Copy this project's media in" and the unopened-projects sweep. Foreign clips are warned about per clip from the watcher and in batches from the pool walk; non-canonical clips are offered by both with separate once-per-process latches.
- "Why is this computer not syncing" is computed twice with overlapping but different orderings: `_lanes_refusal` (6 gates, used by start and Sync now) and `blocked_report` (17 reasons, reported and shown in the tray).
- Diagnostics reach the admin four ways: clipboard button, log fallback, automatic upload on lane error, and the admin's "ask this machine why".
- `resolve_health` carries both `project_open` and `open_project` with the same value.
- Aliases that add no behaviour: `undo_last_fix` (= `undo_last_relink`), `restart_self` (= the upgrade module's restart with a stand-down check), `open_licence_dialog` (= forced licence prompt).
- Report section and tray view pairs that read the same producer: `broll_ingest_status`/`broll_ingest_view`, `music_ingest_status`/`music_ingest_view`, `proxy_gap`/`proxy_coverage`.
- Releasing a fleet halt (`_apply_fleet_halt`) re-implements the same steps as `release_halt`.
- Two local web servers run inside the companion: the 8899 loopback (Send to Resolve, ingest and YouTube routes) and the field backup page on its own port.
- The single-instance guard has two mechanisms on Windows (named mutex, then the pid file as fallback).
- The drive-letter "repair" and "finish grading" both end in the same swap-to-local action.

## Claims the code does not back

- `__init__.py`'s docstring describes the companion as a tray app plus "three supervised daemons" (watcher, fixer/popup, sync lanes). The code starts many more independent services (proxy generator, two ingestors, job runner, sorter reporters, ledger outbox, field page, Timeline Cards role, YouTube importer, yt-dlp manager, loopback server, unopened-projects sweep, watchdog, and others).
- `consolidate_project`'s docstring says the one-window lock is held "ONLY for the dialogs, never across the copy or the rclone runs". The code holds it for the whole copy and upload (an inner comment admits the reversal).
- A comment in `_start_lanes` (licence gate) says "The wizard, not the tray, is what records consent". The companion's own licence dialog records acceptance and starts syncing (`_show_licence_dialog`).
- A comment in `__init__` says "The licence dialog is offered ONCE per run". The code re-offers it every 60 s until it has been shown once, and the tray can force it any number of times.
- `_start_broll_server`'s docstring says it is "LAST in start()" and `_start_ytdlp_manager`'s says "LAST, next to the b-roll server". Neither is last: the field page, Resolve menu scripts, originals inbox, unopened-projects sweep and watchdog start after them.
- The headless fallback log line says "pystray/Pillow not installed -- running headless", but the tray no longer uses pystray; the line fires on any import failure of the tray module.
- The `__init__` comment on the ignore tracker says it has a persisted half "the folders an editor said to leave alone for good", while `scan_whole_project`'s docstring and `resolve_health` say those folder ignores were retired. app.py itself no longer reads any folder-ignore count.
- `sync_guard`'s docstring lists four states (breaker, trash, halt, skipped-exists); the section carries around thirty.

## Could not determine

- The exact wording and buttons of the out-of-tree popup, the scripting-dead warning dialog, the remove-project override dialog and the sign-in dialog (they live in the popup and tray modules).
- How long a "skip for now" lasts: the diagnostics line says "skipped for now (30 min)", but the duration is set in the fixer module; app.py's own popup snooze is 300 s.
- The minimum interval of the automatic relink rate limit (`resolve_journal.AUTOMATIC_MIN_INTERVAL_SECONDS`), the update back-off curve and maximum attempts, the crash-loop window, the drive-reminder default interval, and the unopened-scan interval: all defined in other modules.
- Whether `mode = "base"` really turns `sync_enabled` and `lane_b_enabled` off (stated in comments; done in the config module).
- Whether the dashboard reads `sync_guard.syncthing_supervisor` (a comment says it does not yet).
- Whether `--self-test` and the start guard's "reverted" answer are reachable in the shipped build (handled by other modules).
- Whether the field backup service is on by default (decided by the field service module's `enabled()`).

