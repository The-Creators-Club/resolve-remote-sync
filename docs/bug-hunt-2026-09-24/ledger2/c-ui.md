# Wave 2 ledger: c-ui (chunk 1 of 3)

Builder c-ui, 2026-09-25. Tests for every fix below:
`companion/tests/test_bug_hunt_2026_09_24_w2_c-ui.py` (18 tests). HEAD check:
the same file run against `git archive HEAD companion/src` in a scratch copy,
with 13 failed and 4 errors (the picker fixture needs names HEAD does not have). The one test that passes there,
`test_a_real_blocking_reason_is_still_red`, is a guard that the
ui-comp-windows-2 fix did not mute real faults.

Tests run (companion venv, from `companion/`):
`python -m pytest tests/test_popup.py tests/test_settings_window.py tests/test_tray.py
tests/test_tray_guard.py tests/test_tray_native_main_thread.py
tests/test_tray_wave3_says_what_it_knows.py tests/test_tray_copy_names_real_menu_items.py
tests/test_tk_interpreter_hygiene.py tests/test_bug_hunt_2026_09_11_comp_ui.py
tests/test_bug_hunt_2026_09_11b_comp_ui.py tests/test_bug_hunt_2026_09_18_companion_core.py
tests/test_broll_server.py tests/test_music_ingest.py tests/test_sweep_2026_09_04_copy.py
tests/test_tk_release_native.py tests/test_bug_hunt_2026_09_24_w2_c-ui.py -q`
-> 1327 passed.

## bug-comp-ui-1 - The ingest picker ignored the popup lock, and its timeout left a live dialog whose answer was dropped
- Status: PARTIAL (rest OWED)
- Verified as: CONFIRMED medium (med-02). Read `_tk_pick` / `pick_media_sources` (popup.py) and `broll_server.pick_ingest_sources`. On win32 `ui_dispatch.dispatch` is inline, so the root is built on the `ccsync-ingest-picker` thread with no lock anywhere on the path. After `done.wait(300)` it returned `[]` and never closed the dialog, and a second call started a second thread and a second root.
- Fix: popup.py, the picker block. (1) There is now ONE live picker per process (`_live_picker` under `_picker_state_lock`). A second call while one is up JOINS it and waits on the same answer, so no second Tk root is built. The answer is read with the OPENED dialog's kind. (2) At the timeout the waiter now CLOSES the dialog: `_close_picker_dialog` enumerates the picker thread's own windows (`EnumThreadWindows`, class `#32770`) and posts WM_CLOSE, which the native dialog treats as Cancel. Tk returns "" by its own path and the root is released on the thread that built it. There is a 5 s grace for a choice made in that race. On macOS the modal panel cannot be closed from another thread, so it stays up and the next pick joins it. (3) The picker takes the app's popup lock non-blocking. The lock comes from `popup_lock=`, or from `set_picker_popup_lock()` registered once. If the lock is held it raises `PickerBusy` (an editor-facing message with no em dash). The picker THREAD releases the lock when the dialog ends, because the dialog can outlive every waiter. A choice that arrives after every waiter has left is logged, not silently lost.
- Live probe (scratchpad, not a test): real `_tk_pick` with a 2 s timeout, for both `folder` and `files`. The native dialog closed in about 0.35 s after the timeout, `pick_media_sources` returned `[]` in 2.35 s, no picker thread survived, `_live_picker` was cleared, and the interpreter was freed on its own thread (`pinned: []`).
- Regression test: `test_a_timed_out_picker_is_closed_not_abandoned`, `test_a_second_pick_joins_the_open_picker_instead_of_a_second_root`, `test_the_picker_refuses_beside_another_ccsync_window` and `test_the_picker_holds_the_popup_lock_while_its_dialog_is_up`. They fail on HEAD because it has no `_close_picker_dialog`, `_live_picker` or `popup_lock`, and its dialog_fn is called twice.
- Tests run: see top.
- Skew / deploy order: companion only, no wire change. `pick_media_sources` keeps its old signature plus one optional keyword, so the existing doubles in `test_broll_server.py` still match.
- OWED:
  - c-app, `companion/src/ccsync_companion/app.py`: call `popup.set_picker_popup_lock(self._popup_active_lock)` in `CompanionApp.__init__` right after the lock is created (~line 1500). Until then only the one-picker rule and the timeout close apply, and the picker is still invisible to `apply_upgrade`'s stand-down and to the other dialogs.
  - c-broll-music, `companion/src/ccsync_companion/broll_server.py` `pick_ingest_sources`: add `except popup.PickerBusy as exc: return 200, {"ok": False, "message": str(exc)}` BEFORE the generic `except Exception`. Without it the page says "the file picker could not be opened on this computer" instead of naming the open window. The page already toasts any message other than "cancelled". Its docstring's CORE-M3 sentence can also say that the lock is now taken in popup.

## ui-comp-windows-2 - Having nothing ticked was drawn as a red blocking line in Settings and pulled HELP to the top
- Status: FIXED
- Verified as: CONFIRMED medium (med-17). Replayed `_lane_advisories({"blocked": {"reason": "no_selection", ...}})` and got `[("blocking", ...)]`. `rank_advisories` turns that into `style="warning"`, and `_help_first` then moves HELP first. This breaks the owner rule that nothing ticked is fine.
- Fix: settings_window.py `_lane_advisories`. The blocked summary is tagged INFO (muted) when `blocked.reason` is in `tray._BLOCKED_INFORMATIONAL`, the same set the tray already uses (live-5). New helper `_blocked_is_informational`. The sentence stays readable, muted, beside the PROJECTS section's own line. It is neither red nor a reason to move HELP. Every other blocked reason is unchanged.
- Regression test: `test_nothing_ticked_is_muted_in_settings_and_does_not_move_help` fails on HEAD with `('blocking', ...)`. `test_a_real_blocking_reason_is_still_red` is the guard.
- Tests run: see top.
- Skew / deploy order: companion only.
- OWED: none

## bug-comp-ui-2 - macOS: a menu rebuild that landed while the menu was open dropped the open menu's delegate
- Status: FIXED
- Verified as: DOWNGRADED to low (med-02). The mechanism holds, and it clears itself on the next open and close. Re-read `_apply_menu` -> `_to_main` (the main-queue block), `_apply_menu_now` and `_build_nsmenu`. The rebind of `self._targets`/`self._delegate` was unconditional. NSMenu's delegate and NSMenuItem's target are weak.
- Fix: tray_native.py. `_apply_menu_now` no longer rebuilds while `_menu_open` is set. It records `_menu_rebuild_pending` instead, so the open menu keeps its own watcher and targets alive. `menuDidClose_` now calls a new `_DarwinIcon._menu_did_close()`, which clears the flag and runs a pending rebuild through the new `_darwin_after_current()`. That helper queues on the main queue even when already on the main thread, so the menu is not replaced inside its own delegate callback. If the flag were ever stuck, the current menu's live watcher clears it on the next open and close, which then runs the rebuild. The hunter's second suggestion, a ceiling in tray.py's refresh loop, is not needed once the delegate can no longer be lost.
- Regression test: `test_a_rebuild_that_lands_while_the_menu_is_open_waits_for_it_to_close` fails on HEAD because `_build_nsmenu` is called while the menu is open and `_menu_did_close` does not exist. `test_a_closed_menu_with_nothing_pending_rebuilds_nothing` covers the idle path. Not run on a Mac (AppKit seams faked, like `test_tray_native_main_thread.py`).
- Tests run: see top.
- Skew / deploy order: companion only (macOS build must be made on a Mac as usual).
- OWED: none

## bug-comp-ui-3 - WorkProgressWindow.close() before the root existed reported "closed", and the window opened anyway, untracked
- Status: FIXED
- Verified as: real (low, unverified before). Read `open`/`close`/`_serve`/`_build_and_show` and app.py `_close_work_window` / `_open_work_window`. `close()` set `_closed` whenever `root is None`, including while the window thread was about to build. A close between `tk.Tk()` and the event loop was a cross-thread `after()` that raised and was swallowed. In both cases `wait_closed` returned True and the app forgot a window that then came up.
- Fix: popup.py WorkProgressWindow. New `_close_requested` Event (cleared by `open()`). `close()` sets it. `_closed` is now set only by `_serve`'s finally, or at once if no window thread is alive. `_build_and_show` checks the flag after building and before `run_dialog`, and destroys the root instead. `_tick` also checks it, which covers a close whose `after()` could not be marshalled yet. `wait_closed` now means the window is really gone. app.py's 3 s bound still caps the wait.
- Regression test: `test_close_before_the_root_exists_waits_for_the_window_thread` fails on HEAD because `wait_closed(0.2)` returned True mid-build. Also `test_the_first_tick_honours_a_close_that_could_not_be_marshalled` and `test_the_build_checks_for_a_close_before_entering_its_event_loop`, which is source-level because the real build needs a display (conftest).
- Tests run: see top.
- Skew / deploy order: companion only.
- OWED: none

## bug-comp-ui-4 - The work-progress window is a Tk root outside `_popup_active_lock`
- Status: DEFERRED
- Verified as: the facts are right. `WorkProgressWindow` never touches `_popup_active_lock`, it opens automatically on a batch start, and app.py's comments (lines ~1503 and ~10076) call two live roots "CORE-M3's wedged interpreter". But neither fix is proportionate or mine to choose. (a) Make the window hold the popup lock: a b-roll batch runs for hours, so for that whole time every fixer popup, Settings, sign-in and update offer would be refused and `apply_upgrade` would stand down. A take-at-open-only lock does not stop the other windows opening beside it, so it would be half a fix. (b) Declare coexistence safe and correct the comment: that asserts CORE-M3 no longer applies. Since CR-93 every root is pinned at birth and freed on its own thread, and the work window has coexisted with the fixer popup routinely since 2026-08-18 with no recorded wedge, but I cannot prove it. The comments are also in app.py (c-app).
- Decision needed (owner or lead): should the monitor window count as "a CCSync window is open", accepting that nothing else can pop up while a batch window is on screen? Or is sibling coexistence accepted, in which case c-app corrects the app.py comments? Given the choice, I would recommend the second.
- Fix: none.
- Regression test: none.
- Tests run: n/a.
- Skew / deploy order: n/a.
- OWED: none until decided (then c-app for the app.py comments or `_open_work_window`, c-ui for `WorkProgressWindow`).

## bug-comp-ui-5 - Five tray.py dialog builders abandoned a mapped root when construction raised
- Status: FIXED
- Verified as: real (low, unverified before). Read all five builders. None destroyed the root on the exception path. `ui_dispatch.reclaim_mine` / `_try_free` keep a root pinned while `winfo_exists()` is true, so a half-built mapped window stays on screen for the life of the process. That is the comp-ui-6 shape, which was fixed only for Settings and PopupDialog.
- Fix: tray.py. New `_discard_half_built(root, what)` routes to `ui_dispatch.release_root`, which never raises and runs on the building thread. The bodies of `_build_sign_in_dialog`, `_build_typed_confirmation` and `_build_credentials_dialog` after `tk.Tk()` are wrapped in `try: ... except BaseException: _discard_half_built(...); raise`, so the caller sees the same exception as before. `_build_update_dialog` and `_build_scripting_warning_dialog` start with `root = None` and discard it in their existing `except` before logging, notifying and returning False. That return is unchanged. The root is still built inside the dispatched function (test_tk_interpreter_hygiene).
- Regression test: `test_a_raising_dialog_build_destroys_its_root[sign-in|typed-confirmation|credentials]` and `test_a_caught_dialog_failure_still_destroys_its_root[update|scripting-warning]`. All fail on HEAD because the stub root's `destroy()` is never called.
- Tests run: see top.
- Skew / deploy order: companion only.
- OWED: none

## bug-comp-ui-6 - `_WindowsIcon._teardown` iterated `_hicon_cache` unguarded, and a raise there skipped `_stopped.set()`
- Status: FIXED
- Verified as: real but narrow (low, unverified before). The `icon` setter runs `_modify` -> `_icon_handle` on the CALLER's thread (the pulse and refresh loops). A tick past its `_added` check can insert while the pump thread iterates `.values()` in `_teardown`. In `run()` the `finally` called `_teardown()` then `_stopped.set()`, so a RuntimeError skipped the set and `stop()` waited 5 s.
- Fix: tray_native.py. New `_hicon_lock` guards `_icon_handle`'s lookup and insert and `_teardown`'s snapshot and clear. The handles are destroyed outside the lock, from a list. `run()` now calls `_teardown()` in a nested try, with `_stopped.set()` in its own `finally`.
- Regression test: `test_teardown_survives_an_icon_cached_mid_iteration` inserts from inside `DestroyIcon` and fails on HEAD with "dictionary changed size during iteration". `test_a_raising_teardown_still_releases_stop` fails on HEAD because `_stopped` is not set. The existing `test_a_terminal_registration_failure_frees_the_window` (09-18 suite) still passes.
- Tests run: see top.
- Skew / deploy order: companion only.
- OWED: none


# Wave 2 ledger: c-ui (chunk 2 of 3)

Builder c-ui, 2026-09-25. The new tests are appended to
`companion/tests/test_bug_hunt_2026_09_24_w2_c-ui.py` (15 new, 33 in the
file). HEAD check: the file was run in a scratch copy of the component built
from `git archive HEAD companion/src` plus the current tests. Every chunk-2
test failed there (28 failed, 4 errors, 1 passed; the one pass is chunk 1's
guard). Two existing tests pinned the old behaviour and were changed:
`test_settings_window.py::test_breaker_and_halt_actions_appear_in_sync_lanes`
(the button label) and `test_tray.py::test_sync_line_lane_c_counts_toward_both_totals`,
now `..._counts_once_in_its_own_direction`.

Tests run (companion venv, from `companion/`): the chunk 1 list plus
`test_no_em_dash.py test_drive_reminder.py test_root_guard.py`. Every file is
green: 1105 passed in the chunk 1 list, then 396 passed for test_tray,
test_no_em_dash, test_drive_reminder and test_root_guard after the
test_tray update.

Probe (scratchpad `probe_strip.py`). It uses a withdrawn Tk root that is never
mapped, and only measures reqwidths. Real neon_button widths for all eight
sections come to 895 px in one row. With the fix, at 720 px they wrap to 5+3
(row widths 639 and 256, space 684), and at 560 px to 3+5 (438 and 457, space
524). The WIRED confirm body is 1875 px unwrapped and 517 px wrapped (3 lines).
A ttk combobox is 387 px at 52 characters and 723 px at the 100 cap.

## ui-comp-windows-1 - confirm_dialog and notice_dialog never wrapped their body
- Status: FIXED
- Verified as: DOWNGRADED to low (med-17). The buttons stay reachable, because Tk clamps the window to its maxsize, but the Label is cut, so the end of the sentence is lost. Re-read HEAD popup.py confirm_dialog and notice_dialog: neither body Label has a wraplength. The probe measured the WIRED body at 1875 px.
- Fix: popup.py. New `DIALOG_WRAP_PX = 520` (~2456), the typed confirm's value. The body Label in confirm_dialog (~2493) and notice_dialog (~2555) now wraps at it. Explicit `\n` breaks in callers are kept.
- Regression test: `test_a_dialog_body_wraps_instead_of_running_off_the_screen[confirm|notice]` (fake tkinter widgets record their kwargs). It fails on HEAD because there is no wraplength and no `DIALOG_WRAP_PX`.
- Tests run: see top.
- Skew / deploy order: companion only.
- OWED: none

## ui-comp-windows-4 - The Settings jump strip was wider than the window, so HELP could not be seen, and Lines had a fixed 660 px wrap
- Status: FIXED
- Verified as: real (low). The strip packed every button `side="left"` in one row. With real widths the row is 895 px against a 720 px window (probe). Every Line had `wraplength=660` whatever the window width.
- Fix: settings_window.py. New pure helpers `_flow_rows` (~274) and `_line_wrap_px` (~291), and `_STRIP_PADX` / `_STRIP_GAP`. In the window, `_reflow_strip` (~1921) grids the jump buttons over as many rows as the strip's width needs. It runs after every render and on the strip's `<Configure>`, and returns early on a height-only change so it cannot loop. `_on_canvas_configure` now also sets each rendered Line's wraplength to `_line_wrap_px(canvas width)`: 660 at the 720 px default, narrower when the window is narrowed. The labels are tracked in `line_labels`, which is cleared on each render.
- Regression test: `test_the_jump_strip_wraps_so_help_is_reachable_at_the_default_size` and `test_lines_wrap_to_the_canvas_not_a_fixed_660`. They fail on HEAD because the helpers do not exist and the source still has `wraplength=660` and the one-row pack. The Tk half cannot run under conftest's no-Tk guard, so the probe above covers it with real widget widths.
- Tests run: see top.
- Skew / deploy order: companion only.
- OWED: none

## ui-comp-windows-5 - Settings said "Your drive was disconnected ... plug it back in" about a drive that was wedged or mounted in the wrong place
- Status: FIXED
- Verified as: real (low). `root_unfinished` comes from `drive_unfinished_summary`, which is gated only on `_root_absent`. That flag is also set for ROOT_NOT_ANSWERING and ROOT_MISPLACED (the tray reads the same snapshot through `drive_absent_phrase`). The Settings line was hard-coded, and it said "Your drive", not the site drive phrase.
- Fix: settings_window.py. New `_drive_owed_line(owed, root_state)` (~304), used at ~1450. Not answering: "... is not answering with N still to go - reconnect it or restart this computer to finish syncing" (the SYNC-120 action). Misplaced: "... is mounted at the wrong place with N still to go - eject it, delete the leftover empty folder, then plug it back in" (root_guard's own SYNC-105 action). Absent: the old sentence. All three start with `site.drive_phrase(capitalised=True)`, and there is no em dash. A `root_guard` import was added.
- Regression test: `test_a_wedged_drive_is_not_called_disconnected_in_settings`, `test_a_misplaced_drive_is_told_to_clear_the_leftover_folder` and `test_a_pulled_drive_still_says_plug_it_back_in`. They go through `build_settings_model` with the real `_tray_snapshot`. On HEAD all three fail: the wedged and misplaced ones say "disconnected", and the pulled one says "Your drive", not the site phrase.
- Tests run: see top.
- Skew / deploy order: companion only.
- OWED: none

## ui-comp-windows-6 - The Settings button for releasing a local stop still said START SYNCING AGAIN
- Status: FIXED
- Verified as: real (low). HEAD settings_window.py had the button "START SYNCING AGAIN" -> `action_release_halt`. The tray row is `halt_release_label` ("Clear the sync stop on this computer", UX-19), and `_confirm_halt`'s body tells the editor to look for that name. While a pause is also set, the old label is false.
- Fix: settings_window.py. New `CLEAR_SYNC_STOP_LABEL = "CLEAR THE SYNC STOP ON THIS COMPUTER"` (~265), used at ~1506. ui_copy.py has a new route, `CLEAR_SYNC_STOP = "Tray > Settings > CLEAR THE SYNC STOP ON THIS COMPUTER"`, with its ROUTE_ROWS entry, so `test_tray_copy_names_real_menu_items` pins that the row exists. Any later copy that needs the route uses the constant.
- Regression test: `test_settings_names_the_stop_release_the_way_the_tray_does`. It fails on HEAD because the constant and route do not exist and the button still has the old label. `test_settings_window.py::test_breaker_and_halt_actions_appear_in_sync_lanes` was updated because the label is the behaviour that changed.
- Tests run: see top.
- Skew / deploy order: companion only.
- OWED: none

## ui-comp-windows-7 - The licence refusal was cut before its action in the tooltip, and in Settings it told the reader to open Settings
- Status: FIXED
- Verified as: real (low). eula.acceptance_problem's three sentences end with "Open Tray > Settings > READ AND ACCEPT THE LICENCE." (comp-app-3). With "CCSync: " in front, the "updated" variant is 157 characters, and `[:127]` cut it inside the route. `_licence_advisory` filtered only "setup wizard", which no current sentence contains, so the Settings line routed the reader to the window they were in, directly above the button.
- Fix: (a) tray.py `_tooltip_text`. The blocked-detail tooltip goes through `tray_native.fit_toast(..., 127, log_full=False)`, which keeps the tail sentence and puts the ellipsis in the middle (APP-4's rule). tray_native.py `fit_toast` gained an optional `log_full=True` keyword. The tooltip passes False because it is recomputed on every refresh and would otherwise log the same sentence every few seconds. Balloon callers are unchanged. (b) settings_window.py `_licence_advisory` (~250) also drops a sentence that starts with "Open ". The old "setup wizard" filter is kept for records written in older wording.
- Regression test: `test_the_tooltip_keeps_the_end_of_a_long_blocked_sentence` (on HEAD the tooltip ends "...READ A") and `test_settings_drops_the_route_to_the_button_it_is_drawn_above` (on HEAD the text contains "Open Tray > Settings").
- Tests run: see top.
- Skew / deploy order: companion only.
- OWED: none

## ui-comp-windows-8 - The fixer popup's destination combobox was 52 characters wide and hid the default destination's last folder
- Status: FIXED
- Verified as: real (low). HEAD popup.py had `ttk.Combobox(..., width=52)`. Every option from `fixer.list_destination_dirs` carries the project prefix, and the ttk popdown is as wide as the field. The default destination "Projects/2026/FF5/Civil Defence/B-roll/Editor Added/ruskin" is 58 characters. I did not take the hunter's other suggestion, prefix-relative display. The field is editable, and its text is what `_run_fix` hands to fix_clip, so changing what it shows would change what a typed value means.
- Fix: popup.py. New `dest_combo_width(options, suggested)` (~864) sizes the field to the longest option + 2, with a floor of 52 and a cap of 100 characters (about 723 px of mono 9, measured). The combobox uses it (~1181). After it is gridded, the field is scrolled to the end (`icursor("end")`, `xview_moveto(1.0)`, best-effort), so a path longer than the cap shows its distinguishing tail.
- Regression test: `test_the_destination_field_is_wide_enough_for_the_default_folder`. It fails on HEAD because `dest_combo_width` does not exist and PopupDialog's source has `width=52`.
- Tests run: see top (test_popup.py included).
- Skew / deploy order: companion only.
- OWED: none

## logic-sync-truth-6 - The tray Sync line counted every lane C file twice, and the drive reminder repeats for downloads
- Status: PARTIAL (rest OWED)
- Verified as: real (low), both halves. (a) HEAD tray `_sync_line` added lane C's one count to `up` and to `down`. syncthing_lane.check_once sets `queued` either to our need (`needTotalItems`, a download) or, in its outgoing branch, to the server's need of us (an upload, detail "sending N file(s) (...) to the server"). It never sets both. (b) `drive_reminder.unfinished_work` counts lane B and C items, and a lane B pass that is `syncing` at 0/0 counts as 1. The reminder then repeats every `drive_reminder_minutes`. The module's own rationale for nagging is that an SFTP upload has no resume (rclone), which is not true of a download.
- Fix (a): tray.py. New `_lane_direction(status)` (~2490) and `_LANE_C_SENDING` (~2487). A lane named `_up` / `_down` keeps its direction. Lane C counts as an upload only when its detail carries the outgoing sentence (a search, because `_with_problems` and the path detail are joined on with "; "), and otherwise as a download. `_sync_line` counts each lane once (~2570). No wire or LaneStatus change.
- Regression test: `test_a_lane_c_download_is_not_also_counted_as_an_upload` and `test_a_lane_c_upload_is_counted_as_one[2 details]`. On HEAD both read "up 40 · down 40". `test_the_outgoing_sentence_the_tray_reads_is_the_lane_s_own` pins the producer's f-string in syncthing_lane.py, so a rewording there fails here rather than silently turning uploads into downloads. The existing test_tray test that pinned the double count was updated.
- Tests run: see top.
- Skew / deploy order: companion only.
- OWED:
  - c-sync, `companion/src/ccsync_companion/drive_reminder.py`, part (b). Keep the FIRST warning as it is (it names everything owed). Make the RECURRING reminder fire only while the episode's `Unfinished.lanes` includes `lane_a_video_up`, i.e. an upload was owed. Proxy downloads and lane C need resume when the drive returns, and the dashboard's safe-to-close rule says uploads alone decide. The wedged-drive reminder (SYNC-120, `begin_state`) is not about owed work and must stay as it is. This is a policy change to CR-92's recurrence. The c-sync builder should confirm the episode record keeps `lanes` across restarts (drive_unfinished.json) before gating on it, and add a regression test there.
  - c-sync, `companion/src/ccsync_companion/sync/syncthing_lane.py` (optional, longer term): an optional structured direction field on lane C's LaneStatus (default unset), so the tray can stop reading the sentence. Until then, the tray's pin test fails on any rewording of "sending N file(s)".

### Review round (2026-09-25) - logic-sync-truth-6
- Reviewer: c-sync's logic-sync-truth-3 no-peer branch (syncthing_lane.py ~903-911) replaces the "sending N file(s)" sentence with `NO_PEER_DETAIL (N file(s) owed)` for an upload too, so `_lane_direction` called it a download and the tray read "Sync: downloading N files" for files this computer owes the server.
- Verdict: AGREED. Reproduced: the pre-review tray, fed that detail, prints "Sync: downloading 40 files".
- Fix: tray.py. It now imports the lane's own constant (`from .sync.syncthing_lane import NO_PEER_DETAIL as _LANE_C_NO_PEER`, which is a stdlib-only module, so there is no cycle). `_lane_direction` returns "" (not moving) when lane C's detail carries it. It checks this first, because the no-peer sentence REPLACES the sending one. `_sync_line` skips a directionless lane in the up/down count. It falls through to the waiting line, which now reads "Sync: N files waiting (not connected to the server)" when a no-peer lane C is present. A lane A/B that really is moving still wins the line alone. No direction is claimed either way. The structured direction field stays OWED to c-sync (optional).
- Regression tests: `test_a_no_peer_lane_c_is_waiting_not_downloading`, `test_a_no_peer_lane_c_does_not_join_another_lane_s_movement` and `test_the_tray_reads_the_no_peer_sentence_from_the_lane_itself`. The last pins the import identity and the producer's f-string, so a reword on either side fails here.
- Tests run (companion venv): test_tray, test_no_em_dash, test_bug_hunt_2026_09_24_w2_c-ui, test_tray_wave3_says_what_it_knows, test_tray_copy_names_real_menu_items, test_tk_interpreter_hygiene and test_syncthing_lane gave 579 passed.

# Wave 2 ledger: c-ui (chunk 3 of 3)

Builder c-ui, 2026-09-25. All five findings are LOWS (never verified), so each
was verified here first. Tests: `companion/tests/test_bug_hunt_2026_09_24_w2_c-ui.py`,
chunk 3 block (13 test cases). HEAD check: `git archive HEAD companion/src` into the
scratchpad, today's tests dir beside it, chunk-3 tests selected with `-k`:
every chunk-3 case failed on HEAD (14 then, including a focus-ring test
later dropped, see ui-comp-windows-11). One existing test changed because the behaviour it
pins changed: `tests/test_resolve_journal.py::...::test_the_cap_says_what_to_do_about_it`
now expects the ui-copy-5 route.

Tests run (companion venv, from `companion/`):
`python -m pytest tests/test_bug_hunt_2026_09_24_w2_c-ui.py tests/test_popup.py
tests/test_settings_window.py tests/test_tray.py tests/test_tray_copy_names_real_menu_items.py
tests/test_sweep_2026_09_04_copy.py tests/test_resolve_journal.py
tests/test_bug_hunt_2026_09_11_comp_ui.py tests/test_bug_hunt_2026_09_11b_comp_ui.py
tests/test_tray_wave3_says_what_it_knows.py -q` -> 1062 passed;
`tests/test_theme.py tests/test_no_em_dash.py` -> 132 passed;
onboarding (system python, `python -m pytest tests -q`, it imports the companion
theme) -> 484 passed, 1 skipped.

## ui-comp-windows-9 - The fixer popup's width was unbounded; a long path pushed FIX ALL off the screen
- Status: FIXED
- Verified as: REAL. Real-Tk probe (scratchpad, not a test) building `PopupDialog` with one 294-character card-dump path and `winfo_screenwidth` reporting 1366: HEAD opens a 1,835 px window with FIX ALL's right edge at 1,817 px (off a 1,366 px screen); this build opens 744 px with FIX ALL at 726 px, the path wrapped over three lines (screenshot looked at).
- Fix: popup.py. The clip name and path Labels in each row take `wraplength=FIXER_ROW_WRAP_PX` (620, the header's own wrap); Tk breaks a space-less path at a character. New `fixer_canvas_width()` holds the window inside `FIXER_MAX_SCREEN_FRACTION` (0.9) of the screen by shrinking only the row canvas, applied after the height cap. Limit: on a screen narrower than the button bar itself (about 720 px) the bar is still the widest thing; no real editor screen is that small.
- Regression test: `test_the_fixer_row_list_gives_way_to_a_narrow_screen`, `test_the_fixer_rows_wrap_instead_of_setting_the_window_width` - fail on HEAD (no helper, no wraplength on the rows).
- Tests run: see top.
- Skew / deploy order: companion only.
- OWED: none

## ui-comp-windows-10 - Re-enabling fleet work omitted the restart note, and the kind sentence was ungrammatical
- Status: FIXED
- Verified as: REAL. settings_window.py `_fleet_jobs_controls`: the re-enable sentence had no restart note although every `jobs_*` key is read at start; `action_set_job_kind` produced "will no longer take transcribe audio (uses the graphics card) for the fleet".
- Fix: settings_window.py. The re-enable sentence ends "Takes effect the next time CCSync starts."; the kind balloon is built by new `_kind_change_sentence()` as "This computer will no longer do this for the fleet: Transcribe audio (uses the graphics card). Takes effect the next time CCSync starts." (and "now do this" for a tick).
- Regression test: `test_re_enabling_fleet_work_says_it_waits_for_a_restart`, `test_the_kind_sentence_quotes_the_kind_instead_of_mangling_it` - fail on HEAD (old sentence; no helper).
- Tests run: see top.
- Skew / deploy order: companion only.
- OWED: none

## ui-comp-windows-11 - Muted text failed contrast, no themed button showed keyboard focus, confirm/notice had no keys
- Status: FIXED (focus ring fixed in the review round; the first build called it NOT_A_DEFECT, wrongly)
- Verified as: contrast REAL (computed: MUTED #6f6f7a 3.98:1 on BG, 3.63:1 on FIELD; RED_DIM 1.86:1, used as text for the fixer's "dest:"). Keys REAL: confirm_dialog/notice_dialog bound nothing and focused nothing. Focus ring REAL on Windows (see Review round): with `highlightthickness=0` a focused neon_button changes 0 pixels.
- Fix: theme.py `MUTED = "#8a8a96"` (5.8:1 on BG, 5.28:1 on FIELD, 5.57:1 on PANEL). `neon_button` now `takefocus=1, highlightthickness=1, highlightbackground=BG, highlightcolor=TEXT`: invisible until focused, and on Windows the 1 px is what makes Tk draw the native dotted focus box (in the fg colour; Windows ignores highlightcolor on a Button, X11/Aqua paint with it). popup.py: "dest:" uses MUTED, not RED_DIM. confirm_dialog: `<Escape>` cancels and focus starts on CANCEL; `<Return>` deliberately left unbound (callers confirm destructive things). notice_dialog: `<Return>` and `<Escape>` dismiss, the OK button has focus.
- Regression test: `test_secondary_text_clears_aa_for_small_text[BG|FIELD|PANEL]`, `test_entries_and_the_dest_label_do_not_use_the_rule_colour`, `test_escape_cancels_a_confirm_and_return_does_not_confirm_it` (presses Escape mid-dialog; control run through OK returns True), `test_a_notice_can_be_dismissed_from_the_keyboard[<Return>|<Escape>]`, `test_a_themed_button_can_show_keyboard_focus` - fail on HEAD (old colour, RED_DIM label, no bindings, no focus, highlightthickness=0).
- Tests run: see top, and the Review round below.
- Skew / deploy order: companion only. The onboard wizard bundles the companion's theme at build time, so it picks MUTED and the ring up at its next build (its `_button` already set the same ring; now redundant, harmless).
- OWED: none (the wizard's borders are under ui-onboarding-9)

### Review round (2026-09-25) - ui-comp-windows-11
The reviewer was right; my measurement was wrong. Reproduced with a real Tk
root in the companion venv (scratchpad probe, not a test): window given the
foreground, UISF_HIDEFOCUS cleared with WM_CHANGEUISTATE, a noise grab taken
twice unfocused (0 px apart), then focused, then unfocused again. HEAD's
neon_button (primary and not): 0 px changed on focus. A flat Button with
highlightthickness=1 or 2: 80-84 px changed, all of them the fg grey, zero
red with highlightcolor=RED, i.e. the dotted focus box and not a coloured
ring (screenshot looked at). My first probe had not given the window the
foreground, so what it saw was not a focused button. With the fix, neon_button
changes 92 px (secondary) and 64 px (primary) on focus and returns to 0 on
blur. The docstring now says what was measured. The reviewer's second point
also held: the Escape test only checked the binding, and worse, asserts made
inside the dialog would have been swallowed by confirm_dialog's catch-all
(which returns the safe False). The test now presses Escape mid-dialog,
records outside the catch, checks the root was destroyed, and a control run
through OK must return True. Mutation checks: Escape bound to a no-op fails
the Escape test; `highlightthickness=0` fails the focus test.
Tests re-run: the companion list at the top plus test_theme/test_no_em_dash
-> 1196 passed; onboarding (system python) -> 486 passed, 1 skipped.

## ui-onboarding-9 - Secondary text and input borders below readable contrast
- Status: PARTIAL (rest OWED)
- Verified as: REAL, same numbers as above; RED_DIM input outlines are 1.86:1 on BG and 1.69:1 on FIELD, under the 3:1 a component boundary needs.
- Fix: the MUTED lift in theme.py fixes the text half in every surface that imports the theme, the wizard included. New `theme.FIELD_BORDER = "#6f6f7a"` (3.98:1 on BG, 3.63:1 on FIELD; grey so the RED focus outline still reads as a change). Used for the ttk combobox border (`style_combobox`) and every tray.py Entry (sign-in, YouTube and dashboard dialogs). A real-Tk probe confirmed a Windows Entry does paint its highlightbackground (unlike a Button).
- Regression test: `test_an_input_outline_is_visible_against_both_sides[BG|FIELD]`, `test_entries_and_the_dest_label_do_not_use_the_rule_colour` - fail on HEAD (no FIELD_BORDER; tray.py used RED_DIM).
- Tests run: see top.
- Skew / deploy order: FIELD_BORDER must exist in the theme the wizard bundles before onboard.py references it; both build from one tree, so no skew in practice.
- OWED: onboarding, `onboarding/onboard.py`: replace `highlightbackground=theme.RED_DIM` with `highlightbackground=theme.FIELD_BORDER` on the input and box outlines at lines ~101 (the Entry helper), ~463 (the text box frame), ~1151 (the log frame) and ~1694 (the readonly field). Leave the RULE labels on RED_DIM.

## ui-copy-5 - The companion and the dashboard gave two different routes to Copy diagnostics
- Status: PARTIAL (rest OWED)
- Verified as: REAL. `ui_copy.DIAGNOSTICS` was "Tray > Settings > COPY DIAGNOSTICS FOR YOUR ADMIN"; `health.COMPANION_DIAGNOSTICS_PATH` is "Settings > Help > Copy diagnostics"; fleet_grid.html:477 hand-writes "Settings, then Help, then Copy diagnostics". The button is in the Settings window's HELP section (settings_window.py `# -- [ HELP ]`).
- Fix: ui_copy.py `DIAGNOSTICS = "Tray > Settings > HELP > COPY DIAGNOSTICS FOR YOUR ADMIN"`, the one wording both sides are to say. tray.py's NOT SET UP menu row says "(Settings > HELP > COPY DIAGNOSTICS FOR YOUR ADMIN)". Every companion sentence already interpolates the constant.
- Regression test: `test_the_diagnostics_route_passes_through_help` (the route equals `HELP_PAGE + " > " + its button`, and the button is in the HELP block) - fails on HEAD.
- Tests run: see top; `test_tray_copy_names_real_menu_items.py` still passes (every route starts "Tray > ", ends at a row that exists).
- Skew / deploy order: none; copy only, each side independent.
- OWED:
  - d-diag, `dashboard/src/ccsync_dashboard/health.py` ~552: set `COMPANION_DIAGNOSTICS_PATH = "Tray > Settings > HELP > COPY DIAGNOSTICS FOR YOUR ADMIN"` (keep "Tray >": on the dashboard, "Settings" alone reads as the dashboard's own Settings page). Check the alerts.py sentences at ~1771/1791 ("Ask that editor to open {path} on ...") still read, and any dashboard test pinning the old string.
  - d-ui, `dashboard/templates/partials/fleet_grid.html` ~477: replace "Settings, then Help, then Copy diagnostics" with `{{ COMPANION_DIAGNOSTICS_PATH }}`.
  - music-ytdl, `music/web/static/app.js` ~378: the refused-send message says "Settings > Help > Copy diagnostics in the tray has the reason."; make it "Tray > Settings > HELP > COPY DIAGNOSTICS FOR YOUR ADMIN has the reason." (no em dash; `music/web/tests` has a copy scan).

### Review round (2026-09-25) - ui-copy-5
The reviewer was right: `music/web/static/app.js:378` hand-writes a fourth
route ("Settings > Help > Copy diagnostics in the tray"), shown when the
companion refuses a music send. It is the music web group's file, so it is
added above as an OWED row for music-ytdl rather than edited here. Searched
the rest of the tree for other hand-written routes (`grep -rni "copy
diagnostics"` over companion/src, dashboard/src, dashboard/templates,
broll/web/static, music/web/static, onboarding): no other hand-written
ROUTE outside the ones already listed. Three tray status lines (tray.py
~3590, ~3668, ~3743) say "Copy diagnostics for your admin" with no route at
all; they name the button, do not contradict the route, and are menu lines
kept short on purpose, so they are left as they are. Companion half unchanged; no tests touched this round.


# Owed round (2026-09-25): items other groups left in c-ui's files

Builder c-ui. Tests: `companion/tests/test_bug_hunt_2026_09_24_w2_c-ui.py`,
"owed round" block (26 cases), plus the MODULES/VOCABULARY_ALLOWED change in
`tests/test_sweep_2026_09_04_copy.py`. HEAD check: `git archive HEAD
companion/src` into the scratchpad with today's tests beside it, the owed-round
cases selected with `-k`: 24 failed, 2 passed (the two guards,
`test_a_real_skip_still_says_nothing_was_copied` and
`test_words_that_merely_contain_a_key_are_left_alone`). One existing test in
this group's own file changed because the behaviour it pins changed:
`test_a_no_peer_lane_c_is_waiting_not_downloading` now expects the
logic-sync-truth-3 wording.

Tests run (companion venv, from `companion/`):
`python -m pytest tests/test_bug_hunt_2026_09_24_w2_c-ui.py tests/test_popup.py
tests/test_tray.py tests/test_crash_report.py tests/test_theme.py
tests/test_sweep_2026_09_04_copy.py tests/test_no_em_dash.py
tests/test_tray_wave3_says_what_it_knows.py tests/test_tray_copy_names_real_menu_items.py
tests/test_tk_interpreter_hygiene.py tests/test_settings_window.py
tests/test_bug_hunt_2026_09_11_comp_ui.py tests/test_bug_hunt_2026_09_11b_comp_ui.py
tests/test_fixer.py -q` -> 1391 passed; `tests/test_bug_hunt_2026_09_18_companion_core.py
tests/test_proxy_history.py tests/test_crash_report.py` -> 95 passed; onboarding
(system python, it imports the companion theme) -> 487 passed, 1 skipped.

Probe (scratchpad `probe_popup_warning.py`, not a test): a real PopupDialog
with one root-level row and one Projects row. The warning Label is gridded
under the first row only. Picking a Projects folder in that row's combobox
(`<<ComboboxSelected>>`) removes it. With the probe's own locals dropped,
the dialog's interpreter was freed on its thread (no "still referenced"
warning from ui_dispatch). The first version watched the StringVar with
`trace_add`, which is a Tcl command no widget owns, so it would have pinned
the interpreter (CR-93 holder rule). It was replaced by combobox bindings
before any test was written.

## logic-resolve-1 (owed from c-resolve) - "copied N GB" counted a reused copy
- Status: FIXED
- Verified as: after c-resolve's fix, a retry that finds the copy already there returns `ok` with `reused_copy: True`, and `fix_copied_bytes` still added the source size, so the summary claimed a copy that did not happen this run.
- Fix: popup.py `fix_copied_bytes`: a result with `reused_copy` is excluded, like a rehearsal.
- Regression test: `test_a_reused_copy_is_not_counted_in_the_copied_total`. It fails on HEAD (1300 instead of 300).
- Tests run: see top.
- Skew / deploy order: companion only. An older fixer never sets the key, so nothing changes there.
- OWED: none

## logic-resolve-4 (owed from c-resolve) - the dialog says nothing, before or after, about a copy that will never sync
- Status: FIXED (the warning half; "require a project choice before FIX ALL" deliberately not built, see below)
- Verified as: with no matched project `effective_prefix` is "" and the suggestion is `B-roll/Editor Added/<editor>` at the tree root. The popup header says "Pick a destination" and nothing more. After the copy, `fix_summary_text` read "Fixed N of M" and ignored fixer's new `stays_local`.
- Fix: popup.py. (1) Before the copy: new `STAYS_LOCAL_WARNING` / `dest_stays_local_warning(dest)`, which delegates to `fixer.destination_stays_local` so there is one test and not two. Each row gets a red Label under its destination, gridded only while the value stays local. `PopupDialog._watch_destination` keeps it current through the combobox's own `<<ComboboxSelected>>`, `<KeyRelease>` and `<FocusOut>` bindings, which die with the widget. A StringVar trace was rejected: it is an unowned Tcl command that would pin the interpreter. (2) After the copy: new `stays_local_names` / `stays_local_sentence` ("Will not sync: A001.braw. Its copy is outside every project, so it stays on this computer and never reaches the server or other editors."). This line is added to `fix_summary_text` (the all-good notice) and to `_fix_done`'s kept-open status, on its own line, not folded into "Fixed N of M".
- Not built: disabling FIX ALL until a project is chosen. c-resolve decided that fixer does not refuse, because an editor may pick a local folder on purpose. With an empty prefix the dropdown already lists the whole tree (`list_destination_dirs`), including every Projects folder, so the editor can fix it from the row where the warning appears. Making it a refusal is an owner decision (it would stop an editor who has no project on this computer at all from fixing a clip), not a copy change.
- Regression test: `test_the_row_warns_before_the_copy_when_the_folder_will_not_sync[4 cases]`, `test_the_row_warning_follows_what_the_editor_picks`, `test_a_copy_that_stays_local_is_named_after_the_run`, `test_the_window_names_a_local_copy_when_it_stays_open` and `test_fixer_and_popup_agree_on_what_stays_local`. All fail on HEAD, which has no helper, no binding and no sentence.
- Tests run: see top, and the probe above.
- Skew / deploy order: companion only. Against an older fixer (no `stays_local` key) the after-copy line is simply absent. The pre-copy line uses fixer's helper, which ships in the same build.
- OWED: none

## logic-resolve-5 (owed from c-resolve) - a relink stopped part way was reported as "you skipped it, nothing was copied in or relinked"
- Status: PARTIAL (rest OWED; see Review round)
- Verified as: re-read `summarize_fix_results` and `_fix_done`. Every `aborted` result was counted "skipped by you" and put in the "You skipped ... Nothing was copied in or relinked ... the half-copied files were deleted" block. UNDO_POINTER was shown only when some result was `ok`.
- Fix: popup.py. `summarize_fix_results` counts `partial_relink` as its own "N stopped part way" and keeps it out of skipped and out of failed. `_fix_done` splits `partial` from `aborted`. It shows each partial row with fixer's own message ("■ a.braw: Stopped by you. a.braw was copied in and 1 of 3 clips were repointed ...") plus "Press RETRY FAILED to finish repointing them. The copy is not made again." (true since logic-resolve-1). It keeps the row in `_failed_rows`, and "Nothing was moved or deleted" is not added beside it. New `_changed_something(result)` decides the undo pointer in both `_fix_done` and `fix_summary_text`: `ok`, or `copied_to` set, or `relinked > 0`, never for a rehearsal.
- Regression test: `test_a_partial_relink_is_not_called_skipped_by_you` (the spec's own case, plus a mixed batch), `test_the_window_shows_the_part_way_message_and_the_undo` (message shown, no skip block, undo shown, row retryable, window stays) and the guard `test_a_real_skip_still_says_nothing_was_copied`. The first two fail on HEAD.
- Tests run: see top. `test_popup.py`'s existing skip and summary tests still pass unchanged.
- Skew / deploy order: companion only.
- OWED: c-resolve, fixer.py (see the Review round below)

### Review round (2026-09-25) - logic-resolve-5
- Reviewer: `_changed_something` counted `copied_to` alone as a change, so fixer's relink-failure result (copy landed, ReplaceClip refused every clip, e.g. a .srt) showed "To undo: ... [ UNDO LAST FIX ]". Nothing was journaled, and UNDO LAST FIX replays the newest journal, so the pointer sent the editor to undo an EARLIER fix. Agreed, the reviewer is right.
- Fix: popup.py `_changed_something`: `ok`, or `relinked > 0`; `copied_to` alone no longer counts, with a comment on why (only replace_clip journals). A result without `relinked` gets no pointer: under-claiming an undo is harmless, over-claiming one reverts the wrong fix.
- Regression test: `test_a_copy_with_nothing_relinked_does_not_point_at_the_undo[None|0]` (fix_summary_text and `_fix_done`); fails on the first build's rule (checked: the old predicate returns True for that result, the new one False). `test_a_relink_failure_that_repointed_some_clips_points_at_the_undo` pins the other side. The partial-relink tests are unchanged and pass (the aborted result already carries `relinked`).
- Tests run: `tests/test_bug_hunt_2026_09_24_w2_c-ui.py tests/test_popup.py tests/test_crash_report.py tests/test_bug_hunt_2026_09_18_companion_core.py tests/test_proxy_history.py tests/test_fixer.py tests/test_sweep_2026_09_04_copy.py tests/test_no_em_dash.py` -> 884 passed.
- OWED: c-resolve, `companion/src/ccsync_companion/fixer.py` relink-failure return (~1615-1628, the `if failures:` block after the relink loop): add `"relinked": relinked` (the count that succeeded). Until it lands, a relink that repointed SOME clips and failed others shows no undo pointer (the undo itself still works from Settings); after it, the pointer appears exactly when a clip was journaled.

## logic-sync-truth-3 (owed from c-sync) - the tray pulsed and said "syncing" for a lane C with no server connected
- Status: FIXED
- Verified as: after c-sync's lane change and this group's review round, `_sync_line` no longer said "downloading". But `should_pulse` still returned True for any `syncing` lane, so the mark breathed for as long as the link was down. The tooltip's syncing loop also said "CCSync: syncing".
- Fix: tray.py. New `_lane_is_moving(status)`: `syncing` and `_lane_direction` is not "" (only lane C's no-peer detail gives ""). `should_pulse` uses it, so the mark is steady. `compute_overall_color` is unchanged on purpose: owed files are not "caught up", so the colour stays amber, and the dashboard's stall rule turns it red after max(30 min, 3 rotations). `_sync_line`: when the no-peer lane is the only one claiming work, it says "Sync: waiting, not connected to the server (40 files owed)". When other lanes also queue, it keeps the review round's "N files waiting (not connected to the server)". `_tooltip_text` skips a non-moving lane in its syncing loop. After the blocked check, it says "CCSync: waiting, not connected to the server (N files owed)" instead of falling through to "up to date". No em dash.
- Regression test: `test_a_no_peer_lane_c_is_steady_amber_not_a_pulse` (steady amber, and a moving lane A beside it still pulses) and `test_the_tooltip_says_waiting_not_syncing_for_a_no_peer_lane`. They fail on HEAD. The updated `test_a_no_peer_lane_c_is_waiting_not_downloading` pins the new line.
- Tests run: see top (test_tray, test_tray_wave3_says_what_it_knows included).
- Skew / deploy order: companion only. It reads `NO_PEER_DETAIL` from the lane module in the same build.
- OWED: none

## ui-copy-4 (owed from c-ytdl) - the vocabulary scan did not cover the modules reworded in this pass
- Status: PARTIAL (rest OWED)
- Verified as: ran the suite's own `_sentences` / `_WORD_RE` scan over each candidate module in the current tree. ytdl_executor, ytdl_server, ytdlp_manager, proxy_gen, resolve_undo, timeline_cards_role and identity are clean (0 hits). ytdl_attestation has one hit, `NOTICE_TEXT` ("machine"), which c-ytdl deliberately left alone. file_moves.py still has 11 hits ("lane B had already moved this folder on this machine" and its siblings): c-sync has not reworded it yet.
- Fix: `companion/tests/test_sweep_2026_09_04_copy.py`. The eight clean modules plus ytdl_attestation join MODULES, with a comment saying why file_moves.py waits. `VOCABULARY_ALLOWED` gains `ytdl_attestation.NOTICE_TEXT` (imported, so the exemption is the exact text and follows it) with the reason: it is versioned legal text mirrored in ytdlweb.attestation, and it changes only with TEXT_VERSION on both sides.
- Regression test: `test_no_retired_word_in_a_sentence_an_editor_reads[ytdl_executor.py|ytdl_server.py|ytdlp_manager.py|ytdl_attestation.py|proxy_gen.py|resolve_undo.py|timeline_cards_role.py|identity.py]`. Per the c-ytdl ledger and the other owners' rewording, these fail on HEAD's wording. The existing self-check on the exemption list passes with the new entry.
- Tests run: see top (test_sweep_2026_09_04_copy.py green).
- Skew / deploy order: test only.
- OWED: c-sync, `companion/src/ccsync_companion/file_moves.py` (~473/483/517 and the "on this machine" family): the reword c-ytdl already asked for. Once it lands, add `"file_moves.py"` to MODULES in `companion/tests/test_sweep_2026_09_04_copy.py` (a one-line change, c-ui's test file).

### Review round (2026-09-25) - ui-copy-4
- Reviewer: timeline_cards_role.py is not clean for this finding. The vocabulary scan cannot see a bug id, and `_check_bridge_contract`'s refusals (~242-264) still end in "(CR-68)" and "(docs/TIMELINE-CARDS-INTO-CCSYNC.md §7c)" / "(§7c: SyncEngine(root, bridge=...))". `str(exc)` becomes the role's status sentence (~656-658, ~696-698), which the fleet grid chip shows. Agreed: "clean" was the scan's verdict, not the finding's.
- timeline_cards_role.py is c-resolve's file (`timeline_cards_*.py`), so no edit here. Status stays PARTIAL.
- OWED: c-resolve, `companion/src/ccsync_companion/timeline_cards_role.py` `_check_bridge_contract` (the three CardsRoleError messages, ~242-264): drop "(CR-68)", "(docs/TIMELINE-CARDS-INTO-CCSYNC.md §7c)" and "(§7c: ...)" from the text an admin reads (keep them in a comment or the log line), e.g. "...owns a Resolve connection of its own, which cannot run beside the companion's. Update that checkout to one that takes the companion's bridge (contract version N)." Add a test in c-resolve's wave-2 file that raises each refusal and asserts no `CR-\d+`, `§` or `docs/` in `str(exc)`. The file_moves.py item to c-sync above still stands.

## bug-dash-ops-4 (owed from d-ops) - the companion's crash redactor had the same `_` and quote gap
- Status: FIXED
- Verified as: HEAD's companion pattern `\b(token|...|dsn)\b\s*[:=]\s*\S+` left `TRUENAS_PW=`, `DASH_SESSION_SECRET=`, `SYNCTHING_API_KEY:`, `{'password': ...}`, `{"api_key": ...}` and `pw=` untouched (the regression test's 7 cases all fail on HEAD).
- Fix: `crash_report.py` `_REDACTIONS[0]` is now the dashboard's pattern, character for character: a letter/digit boundary, `_SUFFIX` parts, `pw`, an optional closing quote, and a quoted value taken whole. The output form `key=<redacted>` is unchanged.
- Regression test: `test_env_style_and_quoted_keys_are_redacted[7 cases]`, plus the guard `test_words_that_merely_contain_a_key_are_left_alone` (tokenizer, passwordless, dsnless; `token=` still redacted). The existing `test_secrets_in_the_breadcrumb_are_redacted` still passes.
- Tests run: see top.
- Skew / deploy order: companion only.
- OWED: none

## bug-dash-ops-9 (owed from d-ops) - the companion's crash file was also opened O_TRUNC
- Status: FIXED
- Verified as: real. `write_report` named the file `<second>-<thread>.json` and opened it with `O_TRUNC`, so two reports for one thread name in one second kept only the second. That can happen: thread names repeat (a pool or a restarted worker), and every UncleanExit report is "process".
- Fix: `crash_report.py` `write_report`: `O_EXCL`, retrying `-1` .. `-99` on `FileExistsError` (the dashboard's shape). It still uses 0o600, still returns None rather than raising, and still invalidates the summary. Side note: `_prune` sorts by name, and `X-thread-1.json` sorts before `X-thread.json`, so at the cap, within one second, the suffixed file is pruned first. This is harmless, and the dashboard behaves the same.
- Regression test: `test_two_crashes_in_one_second_on_one_thread_keep_both`. On HEAD it returns the same path twice and keeps only the second body.
- Tests run: see top (test_crash_report.py, test_bug_hunt_2026_09_18_companion_core.py and test_proxy_history.py, which write reports).
- Skew / deploy order: companion only. Readers glob `*.json`, so a `-1` suffix is read like any other.
- OWED: none

### Review round (2026-09-25) - bug-dash-ops-9
- Reviewer: `<base>-1.json` sorts BEFORE `<base>.json` (`-` 0x2d < `.` 0x2e), and every reader here sorts by name and takes the last as newest, so `crash_summary()["newest"]` named the first crash, `recent_reports` listed them oldest first, `_prune` deleted the later crash first, and `-10` sorted before `-2`. Agreed; my first note called this harmless, which was wrong for `newest`.
- A second defect found while testing the fix: a first-free-slot search reuses `<base>.json` once `_prune` has removed it, so the NEWEST crash of a long burst took the bare (oldest-sorting) name and was the next one pruned.
- Fix: crash_report.py. `_crash_name(base, n)` is `<base>.json`, then `<base>~01.json` .. `<base>~99.json` (`~` 0x7e sorts after `.`, zero-padded, and cannot come from `base`, whose thread part is reduced to `[A-Za-z0-9_.-]`, so a thread named "Thread-1" is not read as a counter). `_age_key` parses the counter and is the sort key for both `_prune` and `_crash_files`. `write_report` numbers past the HIGHEST slot on disk for that base, not into the first free one. Docstring line updated.
- Regression test: `test_the_second_crash_of_a_second_is_the_newest` (12 writes in one second: summary's newest is the last, recent_reports newest first, a "Thread-1" name sorts by its stamp) and `test_prune_keeps_the_latest_crashes_of_a_burst` (cap 3, 12 writes, the last 3 survive). Both fail on the first build's naming; the prune test also failed on my first review-round attempt (first-free slot), which is how the second defect was found. `test_two_crashes_in_one_second_on_one_thread_keep_both` now pins `~01`.
- Tests run: as logic-resolve-5's review round -> 884 passed.
- Skew / deploy order: companion only; no `-N` file exists in the field (the first build was never shipped). The dashboard reads the companion's crashes only as the `newest` filename string.
- OWED: d-ops, `dashboard/src/ccsync_dashboard/crash_report.py` `write_report` (~155-164) names the same `<base>-{n}.json` and `_prune` (~176) sorts by name, so at the cap it deletes the later crash of a burst first and a first-free search reuses the bare name after a prune. Same fix: `~NN` zero-padded suffix, number past the highest slot for that base, and a counter-parsing sort key in `_prune`. `notices.crash_files` sorts by mtime and is unaffected.

## ui-onboarding-8 (owed from onboarding) - the companion's themed buttons had no Enter key
- Status: FIXED
- Verified as: the focus ring half (`takefocus=1`, `highlightthickness=1`, `highlightbackground=BG`, `highlightcolor=TEXT`) was already in `theme.neon_button` from chunk 3's ui-comp-windows-11 review round. What was missing was Enter: a tk.Button answers Space only.
- Fix: theme.py `neon_button` binds `<Return>` and `<KP_Enter>` to `invoke()` (a no-op when disabled) and returns "break". Without "break", the root's own `<Return>` would ALSO fire: notice_dialog's destroys the root again, and in the update dialog it would turn Enter on a focused CANCEL into "apply the update". confirm_dialog still binds nothing on the root, so Enter confirms only when the editor has tabbed to the confirm button. onboarding's `_button` re-binds the same keys on the widget, which replaces this binding, so the wizard is unchanged (its suite passes).
- Regression test: `test_enter_presses_a_focused_themed_button[<Return>|<KP_Enter>]` (presses, returns "break", a disabled button ignores it). It fails on HEAD (no binding).
- Tests run: see top, and onboarding 487 passed.
- Skew / deploy order: the onboard wizard bundles the companion theme at build time. No skew: its own binding wins.
- OWED: none

## Owed round 2 (2026-09-25)

### Item 1: file_moves.py, identity.py, resolve_undo.py, timeline_cards_role.py join MODULES
- DONE. identity.py, resolve_undo.py and timeline_cards_role.py were already in MODULES (added in this group's ui-copy-4 item). `file_moves.py` now joins them. c-sync's rewording has landed: the scan finds 0 hits in it, with the old pattern and with the widened one. The comment that said it "still fails the scan today" is gone.
- Test: `test_no_retired_word_in_a_sentence_an_editor_reads[file_moves.py]` passes.

### Item 2: `_WORD_RE` takes an optional plural
- DONE (test side). `companion/tests/test_sweep_2026_09_04_copy.py`: the pattern is now `\b(<words>)s?\b`. I re-ran the scan over every MODULES entry plus file_moves.py and diffed old against new. The plural caught four strings, none of which the old pattern flagged:
  - `tray.py` `_conflicts_line`: "... edited on two machines at once, so Syncthing kept both copies". It reaches the tray and the Settings window (settings_window.py:184). FIXED (my file): now "two computers at once". No test pinned the old wording (grepped companion and dashboard).
  - `app.py` Copy diagnostics: "-- lanes --". This is a section header in the diagnostics dump, sitting above `vars(status)`, and only whoever debugs a pasted report reads it. ALLOW-LISTED in VOCABULARY_ALLOWED with that reason.
  - `app.py` ~7827 and ~7834: "This computer cannot reach the server: both sync lanes are failing" and its fallback "both sync lanes are failing". Real copy: the tray, the Settings window and the dashboard's machine row all show it (SYNC-113 comment). OWED to c-app.
  - `broll_server.py` `README_SNIPPET` (~250): "(over the same rclone remote the sync lanes use)". It is written as a README beside the Send-to-Resolve config on the editor's computer. OWED to c-broll-music.
- Regression tests (`test_bug_hunt_2026_09_24_w2_c-ui.py`):
  - `test_the_vocabulary_scan_catches_a_plural`: fails on HEAD's pattern. I checked each of its three sentences against the old regex and none matched. It also checks that "planes"/"machinery" stay unflagged.
  - `test_the_conflict_line_says_computers`: fails on HEAD, whose tray.py still says "two machines at once".
- Tests run: `companion\.venv\Scripts\python.exe -m pytest tests/test_bug_hunt_2026_09_24_w2_c-ui.py tests/test_sweep_2026_09_04_copy.py tests/test_settings_window.py tests/test_tray.py -q` gave 733 passed and 2 failed. Both failures are the scan cases `[app.py]` and `[broll_server.py]`, and they stay red on purpose until the two OWED rewords land. Allow-listing real copy to turn them green would break the rule the list itself states: a module passes because its strings were read, never because what counts was loosened.
- OWED:
  - c-app, `companion/src/ccsync_companion/app.py` ~7827/~7834: reword "both sync lanes are failing" in both places, for example "This computer cannot reach the server: upload and proxy download are both failing". That turns `[app.py]` green.
  - c-broll-music, `companion/src/ccsync_companion/broll_server.py` `README_SNIPPET`: "(over the same rclone remote the sync lanes use)" becomes "(over the same rclone remote syncing uses)". That turns `[broll_server.py]` green.
