# comp-ui - the companion's tray, popups, Settings window, Tk dispatch, crash reports and the stills link

Files read (with approximate coverage):
- `companion/src/ccsync_companion/tray_native.py` (1745 lines, ~70%: the whole
  Windows `_WindowsIcon` half in full, the macOS helpers and `_DarwinIcon`
  skimmed)
- `companion/src/ccsync_companion/tray.py` (5035 lines, ~35%: the
  `18e69f3..34a3c8f` diff in full, `_report_windows_icon_failure`,
  `_report_icon_placement`, `_notify`, `_persist_failed_line`,
  `_guard_fingerprint`, `_tray_snapshot`, `start_tray` + both loops,
  `quit_confirm_text`, `_spawn`)
- `companion/src/ccsync_companion/popup.py` (2681 lines, ~45%: `RateEstimator`,
  the formatters, `preflight_summary`, `perform_fix_all`, the whole fix-all
  dialog lifecycle `_run_fix` / `_deliver_results` / `_fix_done` / `_safe_after`)
- `companion/src/ccsync_companion/settings_window.py` (1852 lines, ~50%: the
  advisory model, `machine_id_unreadable`, `action_repair_machine_id`,
  `show_settings` / `_build_settings_window` / `_refresh` / `_render`)
- `companion/src/ccsync_companion/ui_dispatch.py` (1149 lines, 100%)
- `companion/src/ccsync_companion/crash_report.py` (751 lines, 100%)
- `companion/src/ccsync_companion/stills.py` (176 lines, 100%)
- Cross-checked (read, not owned): `machine.py` (`machine_id_unreadable`,
  `remint`), `supervisor.read_relaunch_note`, `app.py`
  `_log_tray_registration` / `_note_stills` / `sync_guard`, `ui_copy.ROUTE_ROWS`,
  `consolidate.count_copied`.
- Docs: `HUNTER_BRIEF.md`, repo `CLAUDE.md`, `KNOWN_BUGS.md` (grepped -an for
  tray/icon/toast/Tcl/CR-93/CR-251).

Tests run:
`companion\.venv\Scripts\python.exe -m pytest tests/test_bug_hunt_2026_09_11_comp_ui.py tests/test_bug_hunt_2026_09_11b_comp_ui.py tests/test_crash_report.py tests/test_popup.py tests/test_settings_window.py tests/test_stills.py tests/test_tk_interpreter_hygiene.py tests/test_tk_release_native.py tests/test_tray.py tests/test_tray_guard.py tests/test_ui_dispatch.py tests/test_tray_native_main_thread.py -q`
-> **639 passed in 21.03s**

Note on scope: `git diff --stat 34a3c8f..HEAD` touches NONE of this territory's
seven files. The week of unhunted work landed elsewhere, so the fresh material
here is the 09-11b fix pass itself (`18e69f3..34a3c8f`: comp-ui-1, comp-ui-2,
comp-ui-4..7, comp-resolve-b-1), which is what the findings below are mostly
about.

## Findings

### comp-ui-1 - the startup registration backoff widened the "every toast is dropped" window from 2.5 s to 105 s, and nothing queues or replays a dropped toast
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/tray_native.py:316-330` and `:1094-1108` (`notify`), with the second side at `companion/src/ccsync_companion/app.py:10680-10696` (the +3 s toast timers)
- What: `_WindowsIcon.notify()` refuses to emit when `self._added` is False - it
  logs `tray toast DROPPED, no icon is registered` at WARNING and returns. There
  is no queue, no replay and no deferred send. comp-ui-1 (2026-09-11) changed
  the FIRST registration from 6 flat 0.5 s attempts (2.5 s) to 12 attempts with
  a 15 s cap, which is 105.5 s of sleeping before it gives up, and `run()` does
  not enter the message pump until `_add_icon` returns. Everything that raises a
  toast during those ~1 min 46 s is lost with only a log line. app.py's own
  comment ("Slight delay: the tray icon thread has only just started and Windows
  drops notify() calls for icons not yet registered") picked 3.0 s against the
  OLD schedule and was not revisited.
- Failure scenario: an editor logs in on a busy machine - precisely the case the
  backoff was added for, "Explorer's notification area is regularly not ready
  for far longer than [three seconds]" - and the companion has just
  self-upgraded. At t+3 s `app.py` fires `_notify_tray("Update complete. Now
  running v0.9.74.")`; `_added` is still False, the toast is discarded. Same for
  the crash-loop rollback toast ("The last update kept crashing, so CCSync went
  back to v...") at `app.py:10670`, which is the ONE sentence that explains a
  silent downgrade. Any safety latch that trips inside the same window (a fleet
  halt arriving on the first report, a disk floor read at startup) is dropped
  too.
- Evidence: `_nim_add_delays(12, base=0.5, cap=15.0)` = `[0.5, 1, 2, 4, 8, 15,
  15, 15, 15, 15, 15, 15]`; `_add_icon` sleeps all but the last, i.e. 105.5 s
  (the source comment agrees: "1 min 46 s across twelve attempts"). `run()`
  (`:865-878`) calls `_create_window()` then `_add_icon(...)` then `self._pump()`
  - the pump is unreachable for the whole retry. `notify()` (`:1094`) is `if not
  self._added: log.warning(...); return`. `grep -rn "DROPPED"` finds no reader,
  no queue, no retry anywhere in the repo.
- Ledger: new (a side effect of CR-251's comp-ui-1/comp-ui-2 work; not in
  `KNOWN_BUGS.md`)
- Suggested fix: give `_WindowsIcon` a small bounded pending-toast deque (say 5
  entries, dropped oldest-first) that `_add_icon` flushes on the success path,
  or have `app.py` schedule its post-upgrade toasts off `icon.registered`
  rather than off a fixed 3 s timer.

### comp-ui-2 - a failed Explorer-restart re-add leaves the companion permanently headless: nothing ever retries NIM_ADD again
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/tray_native.py:1185-1212` (the `TaskbarCreated` branch) and `:1053` (`_add_icon`, whose only other call site is `:868`)
- What: comp-ui-1 (2026-09-11b) correctly stopped a re-add failure from setting
  `_ccsync_stop` - the refresh and pulse loops now stay alive. But its
  justification ("the next TaskbarCreated broadcast can still succeed") is the
  ONLY recovery that exists: `_add_icon` has exactly two callers in the repo,
  `run()`'s first registration and this handler, and the handler runs only when
  Explorer restarts again. The original comment on the same branch already says
  that next broadcast "may be never". So after one failed re-add the editor has
  no icon, no menu, no Settings and no Quit for the life of the process, every
  toast is dropped (see comp-ui-1 above), and the two loops spend the session
  snapshotting `app.lane_statuses()` and assigning to an icon whose setters
  no-op on `if self._added`.
- Failure scenario: Explorer crashes and restarts while the shell is under load
  (a common pairing). The `TaskbarCreated` handler sets `_added = False` and
  calls `_add_icon()` with the pump-safe flat schedule - six 0.5 s attempts,
  2.5 s total, deliberately short so the window procedure is not frozen. Explorer
  is not ready in 2.5 s, so the re-add fails. Explorer never restarts again that
  day. The companion syncs correctly and is invisible and unquittable until the
  editor kills it from Task Manager.
- Evidence: `grep -rn "_add_icon(" companion/src` returns exactly
  `tray_native.py:868` and `tray_native.py:1196`. `grep -rn "\.registered\b"`
  returns only `app.py:10504`, a one-shot line at startup. No timer, no WM_TIMER,
  no loop re-checks `_added`. `tests/test_bug_hunt_2026_09_11b_comp_ui.py::test_a_failed_explorer_re_add_does_not_kill_the_refresh_loops`
  asserts the loops keep running but asserts nothing about the icon ever
  coming back.
- Ledger: new ("CR-251's comp-ui-1 does not fix the headless half")
- Suggested fix: on a failed re-add, arm a `SetTimer` on the tray window (the
  pump is alive, which is the whole premise of `fatal=False`) that retries
  `_add_icon()` on a slow cadence - once a minute, indefinitely, since a
  successful add is cheap and `_added` gates it.

### comp-ui-3 - a self-recovering re-add failure writes a crash report and prints the terminal remedy
- Severity: low
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/tray.py:1022-1049` (`_report_windows_icon_failure`)
- What: `fatal` gates only the `_ccsync_stop` assignment. Both the ERROR log
  line and the `crash_report.write_report({... "type": "TrayIconUnavailable"})`
  run unconditionally. The log sentence ends "Sign out and back in, or restart
  CCSync, to get it back", which contradicts the `fatal=False` premise that the
  next `TaskbarCreated` recovers by itself; and each occurrence adds a `.json`
  to `~/.ccsync/crashes`, which is counted by `crash_report.crash_summary()`,
  reported to the dashboard as `sync_guard.crashes` on every tick and surfaced
  by `tray._crashes_line`.
- Failure scenario: an Explorer crash-loop (shell restarting every few minutes)
  produces one `TrayIconUnavailable` crash file per broadcast. The editor's
  Settings window and the dashboard both show a rising crash count for a tray
  that is, on the code's own account, transiently unavailable - and `_prune`
  silently deletes the older, real crash reports the admin actually needed
  (`MAX_CRASH_FILES = 20`).
- Evidence: `tray.py:1022` `log.error(...)` and `:1032` `crash_report.write_report(...)`
  are both outside the `if fatal:` block at `:1029`. `crash_report._prune` keeps
  the newest 20 `*.json` by filename.
- Ledger: new
- Suggested fix: on `fatal=False` log at WARNING with recovery wording ("the
  icon will be re-added the next time Explorer restarts") and skip the crash
  report, or write one only on the first non-fatal failure per process.

### comp-ui-4 - a terminal registration failure leaks the tray window and its HICON cache: `run()`'s error path never calls `_teardown()`
- Severity: low
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/tray_native.py:865-880`
- What: the happy path is `self._pump()` in a `try` whose `finally` calls
  `self._teardown()` (which removes the icon, `DestroyIcon`s every cached HICON
  and clears `_hwnd`). The `except Exception` arm above it announces the failure,
  sets `_stopped` and returns - with the window created by `_create_window()`
  still alive, its per-instance window class (`CCSyncTray_<id>`) still
  registered, the `WNDPROC` reference still held and `self._running` never set.
- Failure scenario: `_add_icon` exhausts its twelve attempts. The process keeps a
  window and a registered class it can never use and never frees its icon
  handles; `_hwnd` still names a window that `stop()` will `PostMessageW` into
  with no pump to read it (the 5 s `_stopped.wait` short-circuits because
  `_stopped` is already set, so this is a leak, not a hang).
- Evidence: read `run()` at `:861-880`; `_teardown` at `:1338-1351` is only
  reachable from the `finally` around `_pump()`.
- Ledger: new
- Suggested fix: call `self._teardown()` in the except arm too (it is already
  exception-safe throughout).

### comp-ui-5 - the FIX ALL bar now reads a flat 0% for a whole rehearsal, while the file line says "Copying"
- Severity: low
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/popup.py:645` (`if outcome.get("ok") and not outcome.get("dry_run"): batch_done += file_total`) with the render at `:1338-1355` and the wording at `:87-110`
- What: comp-resolve-b-1 (2026-09-11b) correctly stopped a rehearsal from
  crediting bytes it never copied. But `batch_bytes_total` is still
  `batch_total_bytes(rows)` - the real size of everything - so during
  `fixer_dry_run` the batch bar is pinned at 0 of 800 GB for the whole run and
  `RateEstimator` never sees a moving sample, so speed and ETA render as
  nothing. Meanwhile `format_file_progress` prints `Copying "A001_C012.braw":
  0 B of 12.7 GB` for each file in turn, because `_on_bytes` never fires on the
  dry-run arm. One misleading screen (a bar that fills instantly) was swapped
  for another (a bar that never moves, under the word "Copying"), on the run
  whose stated purpose (RES-15) is a screen an admin can trust.
- Failure scenario: an admin turns on `fixer_dry_run` to see where 40 clips
  would land, presses FIX ALL, and watches a 0% bar and "Copying ...: 0 B of
  12.7 GB" scroll past. The correct answer only appears at the end, in
  `_fix_done`'s rehearsal block.
- Evidence: `perform_fix_all` publishes `batch_bytes_total=batch_total`
  unconditionally (`:667` and `:683`); `_render_progress` computes
  `int(1000 * batch_done / batch_total)` with `batch_done` stuck at 0. The
  `REHEARSAL_WARNING` banner at `popup.py:952` is drawn once at the top of the
  dialog, not in the progress area that `_run_fix` overwrites at `:1226`.
- Ledger: "CR-251's comp-resolve-b-1 fixes the accounting, not the display"
- Suggested fix: when the batch is a rehearsal, publish `batch_bytes_total=0`
  and drive the bar off `index/total` instead, and have
  `format_file_progress` say "Checking" rather than "Copying".

### comp-ui-6 - the stills "gallery moved" line joins a POSIX path with a backslash on macOS
- Severity: low
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/stills.py:148` (`f"gallery moved to {root}\\{GALLERY_FOLDER}"`), surfaced at `companion/src/ccsync_companion/settings_window.py:950-953`
- What: `root` comes from `desired_entry()`, which on macOS returns the REAL
  LOCAL path (`/Users/<them>/.../Assets/Stills`) and puts the canonical
  `P:\Assets\Stills` in `mapped_root`. The success message hard-codes a
  backslash separator, so a Mac editor is told the gallery moved to
  `/Users/leso/.../Assets/Stills\.gallery` - a path that does not exist in that
  spelling.
- Failure scenario: the Mac editor's Settings window shows that line under
  RESOLVE; they paste the path into Finder's Go > Go to Folder and it fails.
- Evidence: `app.py:_note_stills` copies `result["message"]` straight into
  `stills_state()["instruction"]`, and `settings_window.py:952` renders it as a
  `Line`. `desired_entry(cfg, root, windows=False)` returns
  `(str(stills_dir(local_root)), canonical)` - verified by reading
  `stills.py:60-76`; `tests/test_stills.py` exercises the entry pair but never
  the message text.
- Ledger: new
- Suggested fix: build the message with `os.path.join(root, GALLERY_FOLDER)`, or
  use `"\\"` only when `self._windows`.

## Coverage note
- `_DarwinIcon` and the PyObjC helpers (`tray_native.py:1400-1745`) got a read
  but no real scrutiny: nothing here can execute them and the suite drives them
  through doubles, so the "NSStatusItem plus Tk-Aqua on one runloop" claim in
  the docstrings remains, as it says, the unproven first-Mac-run spike.
- `tray.py` is 5035 lines; I read the 09-11b diff in full plus the snapshot,
  menu, icon-failure and quit paths. The dozen individual tray ACTIONS
  (`_install_youtube_cookies`, the ytdl dialogs, `action_*`) were only skimmed
  for the `_popup_active_lock` acquire/release shape, which is uniform and
  correct in all fourteen sites I checked.
- I verified comp-ui-6 (2026-09-11b)'s claim that `_persist_failed_line`,
  `_shared_folders_line` and `_repath_line` have exactly one caller
  (`settings_window._lane_advisories`) and that no tray MENU item is gated on
  `persist_failed`, `shared_folder_problems` or `repath_events` - so dropping
  them from `_guard_fingerprint` is safe. No finding.
- `ui_dispatch.py`'s CR-93 machinery (the pin, `_try_free`, `_baseline`,
  `holder_chains`) I read end to end and found nothing wrong: `_try_free`'s
  same-thread + refcount + `_root_in_use` triple gate is sound, and
  `install_tk_guard`'s `finally: adopt(self)` correctly covers a half-raised
  `Tk.__init__`. I did NOT try to prove the refcount baseline empirically
  against a real root (conftest forbids building one).
- comp-ui-7 (2026-09-11b)'s `mine[0]` latch in `show_settings` I traced through
  all five exit paths (dispatch raises before fn, tkinter import fails,
  `tk.Tk()` fails, a raise before `closer[0]` is set, a raise after) and found
  no double-release and no missed release. No finding.
- The suite does not cover: the toast-drop window (comp-ui-1), any re-add retry
  (comp-ui-2), the crash-report side effect of a non-fatal failure (comp-ui-3),
  `run()`'s teardown path (comp-ui-4), the rehearsal progress DISPLAY (comp-ui-5,
  only the counts are pinned), or any stills message text (comp-ui-6).
- Not reached at all: `popup.py`'s ingest file picker and work-progress window
  (lines 1600-2681 skimmed only), and `settings_window.py`'s section builders
  outside the advisory and THIS COMPUTER blocks.

## OUT OF TERRITORY
- `companion/src/ccsync_companion/app.py:10670-10696`: the +3 s `threading.Timer`
  toasts after a self-upgrade and after a crash-loop rollback were tuned to the
  tray's old 2.5 s registration schedule and now sit inside the dropped-toast
  window (the second side of comp-ui-1 above; comp-app owns the file).
- `companion/src/ccsync_companion/crash_report.py:270` (mine, noted for
  res-companion rather than re-reported): `write_report`'s filename is
  `<utc-seconds>-<thread>.json` opened `O_TRUNC`, so two crashes on the same
  thread within the same second silently overwrite one another.
