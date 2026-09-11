# comp-ui - the tray, its backends, the popup, the Settings window, ui_dispatch, crash_report, supervisor, stills

Files read (with approximate coverage):
`companion/src/ccsync_companion/tray.py` (the whole 18e69f3 diff plus
`start_tray`, the refresh/pulse loops, every `_*_line` producer, the
fingerprints, `quit_from_menu`, ~60%), `tray_native.py` (the `_WindowsIcon`
lifecycle, `_add_icon`, `_nim_add_delays`, `_wndproc`, `notify`, `stop`,
`_DarwinIcon.stop`, `_NullIcon`, ~70%), `settings_window.py`
(`_lane_advisories`, `_resolve_section`, `build_settings_model`,
`show_settings`, `_build_settings_window`, ~50%), `supervisor.py` (100%),
`crash_report.py` (the relaunch/supervisor half, ~40%), `popup.py` (the
diffed copy constant and `_set_copy_state`/`_publish` callers, ~20%),
`ui_dispatch.py` (`uses_main_thread`, `dispatch`, ~20%), `stills.py` (skim).
Tests read: `tests/test_bug_hunt_2026_09_11_comp_ui.py` (all 31 tests),
`test_sweep_2026_09_04_copy.py` UX-10 scan, `test_tray.py`,
`test_settings_window.py`.

Tests run: `cd companion; .venv\Scripts\python.exe -m pytest
tests/test_bug_hunt_2026_09_11_comp_ui.py tests/test_tray.py
tests/test_settings_window.py tests/test_supervisor.py
tests/test_tk_interpreter_hygiene.py tests/test_popup.py -q`
-> **511 passed in 18.04s** (no Tk window spawned; conftest guard held).
Plus three ad-hoc snippets from the companion venv (below).

## Findings

### comp-ui-1 - a failed Explorer-restart re-add kills the tray refresh loops for ever
- Severity: high
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/tray_native.py:1152-1166`
  (`_wndproc`, the TaskbarCreated branch -> `_announce_failure`) and
  `companion/src/ccsync_companion/tray.py:1018-1021`
  (`_report_windows_icon_failure` sets `icon._ccsync_stop = True`), read
  against `tray.py:4869` and `tray.py:4922` (the two loops' `while not
  getattr(icon, "_ccsync_stop", False)`).
- What: `_ccsync_stop` is the flag `start_tray` wraps `icon.stop()` to set -
  it means "this icon is dead, stop refreshing it", and nothing ever clears
  it. The comp-ui-1 fix reuses it as a side effect of the *diagnostic* path,
  and wires that path to the Explorer-restart handler as well as to the
  once-per-process startup failure. But an Explorer restart is recoverable:
  the pump thread is still alive, and the next `TaskbarCreated` broadcast
  calls `_add_icon()` again, which on success sets `self._added = True` and
  clears `_register_error`. The two loops are gone by then and there is no
  way to restart them.
- Failure scenario: Explorer restarts twice in quick succession (a shell
  crash, a GPU driver reset, an update). The first re-add races the second
  restart and fails -> `_announce_failure` -> `_ccsync_stop = True` -> the
  refresh and pulse threads exit. The third broadcast re-adds the icon
  successfully. The editor now has a CCSync icon in the tray showing the
  colour, the tooltip and the menu as they were at the moment of the failure,
  for the rest of the session: the lane lines never move, the icon never
  changes colour, and the lane B breaker / fleet halt / disk floor lines never
  appear in the menu. That is precisely "green while dead", and it is worse
  than the bug comp-ui-1 set out to fix, which at least had no icon to
  mislead anyone.
- Evidence: read `tray_native.py:1152-1166` (the except branch calls
  `_announce_failure` unconditionally), `tray.py:1018` (the hook sets
  `_ccsync_stop`), `tray.py:4869/4922` (the only readers, both `while not`),
  and `tray.py:4967-4976` (the only other writer, inside `_stop`). No reset
  path exists anywhere: `grep -n "_ccsync_stop" tray.py app.py` returns six
  hits, all of them the above. Verified the hook's effect in the venv:
  `tray._report_windows_icon_failure(App(), icon, "boom")` ->
  `icon._ccsync_stop is True` and one `*-tray.json` crash file written.
- Ledger: new (a regression opened by the CR-233..248 fix for comp-ui-1 in
  `docs/bug-hunt-2026-09-11/hunters/comp-ui.md`).
- Suggested fix: only the *terminal* failure in `run()` should stop the
  loops. Give `_announce_failure` a `fatal: bool` argument (True from `run()`,
  False from the TaskbarCreated handler), or have `_report_windows_icon_failure`
  set `_ccsync_stop` only when `getattr(icon, "registered", False)` is False
  *and* the pump is not running; better still, clear `_ccsync_stop` in
  `_add_icon` on success and make the loops re-startable.

### comp-ui-2 - the Explorer-restart re-add freezes the tray for 15.5 s, not the 2.5 s its own comment promises
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/tray_native.py:432-456`
  (`_nim_add_delays` and the comment above it) and `tray_native.py:1035-1063`
  (`_add_icon`, called with no `attempts` from `_wndproc:1157`).
- What: the fix introduced exponential backoff for the *startup*
  registration and states, in the comment at line 440, "The Explorer-restart
  re-add keeps the short schedule; it runs on the pump thread, where a
  two-minute sleep would freeze the tray." It does not. `_add_icon()` with
  `attempts=None` still gets `attempts = _NIM_ADD_RETRIES = 6`, but the delays
  now come from `_nim_add_delays(6)` = `[0.5, 1, 2, 4, 8, 15]` instead of the
  old flat `_NIM_ADD_RETRY_DELAY` per try. Only the *count* was kept short,
  not the schedule.
- Failure scenario: Explorer restarts while the editor is working. The
  notification area is briefly not ready, so the first few NIM_ADDs fail. The
  pump thread (`_wndproc` runs on it) sleeps 0.5+1+2+4+8 = **15.5 s** inside
  `_add_icon` before giving up, versus 2.5 s before this change. For those
  15.5 s the message loop processes nothing: no right-click menu, no
  `_CCSYNC_WM_QUIT_TRAY`, no NIM_MODIFY from the refresh thread, and a
  `stop()` from another thread times out at its own 5 s wait. An editor who
  clicks the icon during it sees a dead tray.
- Evidence: computed the schedule from the venv -
  `_nim_add_delays(6) == [0.5, 1.0, 2.0, 4.0, 8.0, 15.0]`, sum of the slept
  entries (all but the last, which `break`s) = **15.5**;
  `_nim_add_delays(12)` sums to 105.5 s, so the startup comment's "about two
  and a half minutes" is also wrong (it is 1 min 46 s). No test pins the
  Explorer-restart schedule:
  `test_a_tray_icon_that_will_not_register_retries_with_backoff` only ever
  calls `_add_icon(attempts=_NIM_ADD_STARTUP_ATTEMPTS)`.
- Ledger: new (regression opened by the CR-233..248 comp-ui-1 fix).
- Suggested fix: pass the schedule, not just the count -
  `_add_icon(attempts=_NIM_ADD_RETRIES, cap=_NIM_ADD_RETRY_DELAY)` from
  `_wndproc`, or give `_add_icon` a `backoff: bool = False` and only the
  startup call sets it. Add a test that asserts `sum(slept) <= 3.0` for the
  re-add path.

### comp-ui-3 - every relaunch is counted twice, so the "three relaunches an hour" ceiling fires after two
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/supervisor.py:359-363`
  (`supervisor_argv` formats each stamp `f"{t:.3f}"`) against
  `supervisor.py:186-196` (`write_history` persists the full-precision float)
  and `supervisor.py:471` (`merge_history(read_history(state_dir),
  args.get("prior"))`).
- What: `merge_history` de-duplicates through a `set` of floats. The file
  carries `when` at full `time.time()` precision; the argv copy of the same
  stamp is truncated to 3 decimals by `supervisor_argv`. They are two
  different floats, so the union of the two sources contains **two entries per
  relaunch**, and `decide`'s `len(recent) >= MAX_RELAUNCHES` counts both.
- Failure scenario: a build that aborts on every start (the CR-93 shape this
  supervisor exists for). Relaunch 1 -> history `[A]`; the next supervisor
  merges file `[A]` with argv `[round(A,3)]` -> 2 entries. Relaunch 2 -> 4
  entries -> `decide` refuses with "already relaunched **4** times in the last
  60 minutes", after two relaunches. The companion gets two attempts, not the
  three `MAX_RELAUNCHES` and the docstrings promise, and `note["attempt"]`
  (rendered into the editor-facing unclean-exit report as "relaunch N of 3",
  `crash_report.py:571`) is off by the same factor - it will say "relaunch 3
  of 3" on the second relaunch.
- Evidence: simulated the whole chain in the companion venv
  (`merge_history` -> `supervisor_argv` -> `_parse_prior` -> `merge_history`)
  with `decide(-1073741819, marker, ...)`:
  ```
  cycle 1 hist_len 0 -> True
  cycle 2 hist_len 2 -> True
  cycle 3 hist_len 4 -> False | already relaunched 4 times in the last 60 minutes
  file ['1789107426.687932', '1789107426.688000', '1789107427.387933']
  ```
  Two file stamps 68 microseconds apart are the same relaunch. The new tests
  cannot see this because every one of them uses `NOW = 1_700_000_000.0`,
  which is exactly representable in `%.3f` and round-trips unchanged - the
  "passes for a reason unrelated to the fix" shape the brief names.
- Ledger: new (defect introduced by the CR-233..248 comp-ui-2 /
  res-companion-4 fix).
- Suggested fix: quantise once, in `merge_history`:
  `seen.add(round(float(item), 3))`. That makes the file spelling and the
  argv spelling the same value and the union idempotent. Re-run the supervisor
  tests with a `NOW` that has microseconds (e.g. `1_700_000_000.123456`).

### comp-ui-4 - the "cannot save its safety state" line tells the editor to do the one thing that drops the latch
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/tray.py:3215-3216`
  (`_persist_failed_line`), rendered as a BLOCKING advisory from
  `companion/src/ccsync_companion/settings_window.py:179`.
- What: the sentence is "CCSync cannot save its safety state on this computer
  (<error>). **Restarting CCSync would clear it.**" Every other BLOCKING
  advisory in that list ends with the action the editor should take, so
  "Restarting CCSync would clear it" reads as the remedy on offer - and a
  restart is exactly what silently drops the lane B breaker / fleet halt /
  disk-floor latch that this line exists to protect. The line also never
  names an action the editor *can* take, which is what the finding it
  implements asked for.
- Failure scenario: lane B's breaker has tripped (too many deletions seen on
  the NAS) and `lane_b_breaker.json` will not write. The editor opens
  Settings, reads a red line saying a restart would clear it, restarts
  CCSync - and proxy download resumes against the same NAS with the safety
  latch gone and no record that it was ever set. Nobody is told.
- Evidence: read the string at `tray.py:3215`; read `_lane_advisories`'
  BLOCKING tier and the sentences beside it (`_breaker_line`, `_halt_line`,
  `_disk_line`), all of which end in an instruction. `docs/SYNC_SAFETY.md`'s
  rule is that only a human clears a latch; the copy invites the editor to
  clear it by accident.
- Ledger: new (copy defect in the CR-233..248 comp-sync-1 fix).
- Suggested fix: reword to the warning it means, with the real action, e.g.
  "CCSync cannot save its safety state on this computer (<error>), so a
  restart would silently resume what it stopped. Copy diagnostics for your
  admin before restarting" (`ui_copy.DIAGNOSTICS`).

### comp-ui-5 - the Quit-while-copying confirmation is garbled when the batch total is not known
- Severity: low
- Confidence: CONFIRMED (the garbling); PLAUSIBLE (how often the state is reached)
- Where: `companion/src/ccsync_companion/tray.py:2248-2253` (`quit_confirm_text`).
- What: `where` falls back to the fragment `"files in"` when `total` is
  falsy, but the `index` branch splices it after "copying file {index}". The
  comp-ui-4 plural pass rewrote both halves and left the join broken.
- Failure scenario: a FIX ALL progress callback that publishes an `index`
  without a `total` (`popup.py:1222-1224` takes both off the worker's `info`
  dict and coerces a missing one to 0). The editor clicks Quit and is asked
  to confirm against the sentence "CCSync is copying file 3 files in." - a
  confirmation dialog whose first line is broken English, at the one moment
  the product is asking the editor to make a careful choice.
- Evidence: from the venv -
  `tray.quit_confirm_text({'index':3,'total':0})` ->
  `'CCSync is copying file 3 files in.'`. The new test
  `test_the_quit_confirmation_counts_properly` exercises only
  `{"total": 1}`, `{"total": 12}` and `{"index": 3, "total": 12}`.
- Ledger: new (pre-existing shape, carried through the CR-233..248 comp-ui-4 fix).
- Suggested fix: when `index` is set and `total` is not, say "CCSync is
  copying a file into your synced folder." and drop the index; add the
  `{"index": 3, "total": 0}` case to the test.

### comp-ui-6 - the three new Settings-only advisories are in the tray MENU fingerprint
- Severity: low
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/tray.py:3721-3736` (`_guard_fingerprint`,
  the `_PERSIST_LATCHES` tuple, `shared_folder_problems` length and the
  `repath_events` tuple).
- What: the comments there say each of these "adds a LINE, so without it here
  the line would not appear until something unrelated moved the menu". They do
  not: `_persist_failed_line`, `_shared_folders_line` and `_repath_line` have
  exactly one caller in the repo, `settings_window._lane_advisories`, and the
  advisory lines were deliberately moved out of the tray menu (`tray.py:4747`,
  "every advisory line that used to sit here moved to Settings"). So the
  entries buy nothing and cost a full `_build_menu` rebuild (and the HMENU
  teardown that goes with it) every time a repath event list or a
  persist-failure flag changes.
- Failure scenario: a machine with a flapping state directory toggles
  `persist_failed` between passes; the tray rebuilds its menu every 5 s for a
  line that is not in it. Cosmetic, but the fingerprint is the mechanism that
  keeps the 2026-07-26 hover hang away, and a comment that misstates what is
  rendered where is how the next fix gets it wrong.
- Evidence: `grep -n "_persist_failed_line\|_shared_folders_line\|_repath_line"
  tray.py settings_window.py` -> definitions in `tray.py`, callers only in
  `settings_window.py:179/187/188`.
- Ledger: new.
- Suggested fix: either drop them from `_guard_fingerprint` and correct the
  comments, or render the lines in the tray menu as the comments assume.

### comp-ui-7 - show_settings can release a lock another window now holds
- Severity: low
- Confidence: PLAUSIBLE
- Where: `companion/src/ccsync_companion/settings_window.py:1567-1572`
  (the `except` around `ui_dispatch.dispatch`) with
  `settings_window.py:1551-1561` (`_build_and_show`).
- What: when the builder fails, `_release_and_close` already released
  `_popup_active_lock`, and `_build_and_show` re-raises. `show_settings` then
  tests `lock.locked()` - a `threading.Lock` has no owner - and releases it
  again if anything has taken it in the meantime.
- Failure scenario: the build fails, the editor immediately clicks Settings
  again (or the watcher opens the popup) and takes the lock in the microseconds
  before `show_settings`' handler runs; `show_settings` releases the new
  holder's lock, and a third window can then be built alongside it. Two `tk.Tk`
  roots in one process is the CR-93 shape.
- Evidence: read both blocks; `_popup_active_lock` is a plain
  `threading.Lock` (`app.py`), so `locked()` cannot tell whose.
- Ledger: new (the shape predates the fix; the comp-ui-6 change made the
  double-release reachable by giving the inner path its own release).
- Suggested fix: have `_build_and_show` swallow rather than re-raise once it
  has closed the window (it has already logged), or track "did I release it"
  in a flag instead of asking the lock.

## Coverage note
Not reached: `stills.py` beyond a skim, `popup.py`'s dialog body (row
construction, the dest dropdown, `perform_fix_all`'s progress publisher - the
comp-ui-5 finding's reachability was judged from the call site only),
`ui_dispatch.py`'s pinning/`_try_free` internals against the new Settings
closer, `tray_native._DarwinIcon`'s menu/target lifetime, and the
`tray.py` sections untouched by the diff (icon rendering, `_tooltip_text`,
the jobs/ytdl lines). The suite does not cover: the Explorer-restart re-add
schedule at all; any supervisor path with a sub-second-precision clock (every
supervisor test uses an exactly representable `NOW`); the tray refresh loops'
lifetime (nothing asserts they are still running after a recoverable icon
failure); `quit_from_menu` with two Quit clicks in flight on macOS (two
osascript alerts and two `app.shutdown()` calls are possible, guarded only by
`shutdown`'s own once-latch).

## OUT OF TERRITORY
- `companion/src/ccsync_companion/reporter.py` / `app.py`: the comp-sync-4 fix
  wires `shared_folder_problems` and `repath_events` into the tray snapshot
  only; its own comment says they reached "not here, not the report", and the
  report half still does not exist, so the dashboard cannot see a broken
  shared folder or a server-side project rename.
- `companion/src/ccsync_companion/ytdlp_manager.py:449`:
  `sidecar_warning_line` stays silent until `consecutive_failures >= 2`, but
  nothing in the record is reset on a success path I could find from the tray
  side - worth a comp-ytdl-jobs check that the line clears.
