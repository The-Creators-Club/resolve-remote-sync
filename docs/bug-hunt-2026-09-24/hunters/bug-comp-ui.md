# bug-comp-ui - companion tray/popup/settings/ui_dispatch/crash_report/stills: threading, Tk lifetime (CR-93), crashes
Files read (approximate coverage): ui_dispatch.py (100%), tray_native.py (100%), crash_report.py (100%), stills.py (100%), ui_state.py (100%), theme.py (~60%: icon, styles, neon_button), popup.py (~40%: PopupDialog fix/teardown path, ProgressWindow, WorkProgressWindow, confirm/notice/licence dialogs, show_popup, the ingest picker), tray.py (~30%: start_tray loops, _MenuOpenGuard, _build_menu, _menu_fingerprint, every Tk dialog builder, _spawn/_guarded, quit_from_menu), settings_window.py (~25%: action_set_role, show_settings, _build_settings_window). Callers followed: app._open_work_window/_close_work_window, broll_server.pick_ingest_sources.
Tests/probes run: one ad-hoc probe from the companion venv (scratch file in %TEMP%, deleted) driving WorkProgressWindow's open/close state machine with a fake root (finding 3). No suite run.

## Findings

### bug-comp-ui-1 - The ingest file picker builds a Tk root outside `_popup_active_lock`, and its timeout abandons a live dialog whose answer is thrown away
- Severity: medium
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/popup.py:2694-2774 (`_tk_pick`, `pick_media_sources`); caller companion/src/ccsync_companion/broll_server.py:1967-1999
- What: `_tk_pick` is the one dialog site that neither takes `app._popup_active_lock` (it has no `app`) nor checks it, so on Windows it builds a second live Tk root on a loopback request's helper thread beside a fixer popup, Settings window or update dialog, which is the sibling-root condition every other `tk.Tk()` site in the package takes the lock to avoid (AUDIT_2 CORE-M3/H8, SYNC-5, the copy_diagnostics docstring), and `apply_upgrade`'s `_popup_active_lock.locked()` stand-down does not see it. Separately, `pick_media_sources` waits `PICK_TIMEOUT_SECONDS` (300 s) and then answers "cancelled", but the helper thread and the native dialog stay up: nothing closes the dialog, and whatever the editor picks afterwards lands in a `box` nobody reads. On macOS the docstring's promise ("must not park ... the UI dispatcher's main thread") is not kept either: the modal picker runs ON the main thread through `ui_dispatch.dispatch`, and timing out the waiter does not unpark it, so every later dialog queues behind the abandoned picker.
- Failure scenario: an editor clicks "Choose from this computer" on the b-roll page, goes to find the card, comes back after 5+ minutes and picks a folder: the page already showed "cancelled", the pick is silently dropped, and a second click opens a second picker while the first one is still on screen (two roots on two threads). Or: the watcher opens the fixer popup while the picker is up and both Tk roots are live at once.
- Evidence: read `_tk_pick` (no lock), `pick_media_sources` (`done.wait(timeout)` then `return []` with no close), `pick_ingest_sources` (no lock either), and grep for `_popup_active_lock` in popup.py/broll_server.py (only comments). The 2026-09-03 comp-ui hunt held `_tk_pick` up as "the correct pattern" for dispatch+release_root, which it is; it is the lock and the timeout that are missing.
- Ledger: new
- Suggested fix: give the picker the app's popup lock (pass it through `pick_ingest_sources`; refuse with "another CCSync window is open" when held), and on timeout close the dialog through its root (keep the root reachable and `after(0, root.destroy)` / on macOS the dispatcher's break path) instead of abandoning it; or drop the timeout and refuse a second concurrent pick.

### bug-comp-ui-2 - macOS: an async menu rebuild that lands while the menu is open drops the open menu's delegate, so `ui_state.menu_open` can stay set forever
- Severity: medium
- Confidence: PLAUSIBLE
- Where: companion/src/ccsync_companion/tray_native.py:1767-1816 (`_apply_menu`, `_build_nsmenu`, `self._delegate = watcher`); companion/src/ccsync_companion/tray.py:4936-4973 (refresh loop), tray.py:279-315 (`_MenuOpenGuard`)
- What: on macOS `icon.menu = ...` only ENQUEUES `_apply_menu_now` on the main queue (comp-app-core-2's async hop). The refresh loop checks `guard.is_open()` before assigning, but the menu can be opened between the enqueue and the block running; the main queue is serviced in the event-tracking run-loop mode, so the block then runs mid-tracking, builds a new NSMenu and rebinds `self._targets`/`self._delegate`, releasing the old `CCSyncTrayMenuWatcher`. NSMenu's delegate (and NSMenuItem's target) are weak, so the menu still on screen loses its delegate: `menuDidClose_` never fires and `ui_state.menu_open` is never cleared. Nothing times that flag out on the tray side: both loops `continue` while it is set, and `resolve_bridge` waits up to 8 s before every Resolve call while it is set.
- Failure scenario: a Mac editor right-clicks the menu bar icon within the few milliseconds after a lane changed state (fingerprint moved). The menu opens, the queued rebuild runs under it, the editor closes the menu: from then on the icon colour, pulse, tooltip and menu never update again for the session, and every watcher/Resolve call is delayed 8 s. (Items clicked in that stale menu also do nothing, their weak targets having gone.)
- Evidence: read the enqueue path (`__setattr__` -> `_apply_menu` -> `_to_main` = `NSOperationQueue.mainQueue().addOperationWithBlock_`), the unconditional `self._delegate = watcher` / `self._targets = targets` replacement, and the refresh/pulse loops' `if guard.is_open(): ... continue` with no bound. Not run on a Mac (Windows-only hunt); AppKit's weak `delegate`/`target` semantics are documented.
- Ledger: new
- Suggested fix: in `_apply_menu_now`, skip (and re-queue) the rebuild while `self._menu_open` is set, and keep the previous watcher/targets alive until the new menu is installed and the old one has closed; additionally give the refresh loop a ceiling on how long it will honour a set flag (the way `wait_while_menu_open` already caps at 8 s).

### bug-comp-ui-3 - `WorkProgressWindow.close()` before the root exists reports "closed", and the window then opens anyway, untracked
- Severity: low
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/popup.py:2160-2205 (`open`, `close`, `_serve`); caller companion/src/ccsync_companion/app.py:235-260 (`_close_work_window`) and app.py:9836-9851 (`_open_work_window`)
- What: `open()` starts the window thread and returns; `self.root` is only assigned after `tk.Tk()` inside `_build_and_show`. A `close()` in that gap sees `root is None`, sets `_closed` and returns, so `_close_work_window`'s `wait_closed` succeeds at once and the app forgets the window; the thread then builds and shows it. Likewise a `close()` after `tk.Tk()` but before `run_dialog` is a cross-thread `after()` to a thread not yet in mainloop, which raises after _tkinter's 1 s wait, is caught, and again leaves the window to come up.
- Failure scenario: a b-roll batch starts (window auto-opens) and the editor immediately picks "Show proxy progress" (or shutdown begins): the ingest window "closes", the proxy window opens, and then the ingest window appears as well, a second live Tk root that `close_work_window()`/shutdown no longer knows about and will never close or wait for.
- Evidence: probe with a fake root (0.2 s build delay, close() at 0.05 s): `wait_closed returned: True is_open: False`, then `root now set = True (window is up)`, and the fake mainloop was never ended by the close.
- Ledger: new
- Suggested fix: record a "close requested" flag that `_build_and_show` checks after building the root (destroy immediately if set), and only set `_closed` from `_serve`'s finally, so `wait_closed` means what it says.

### bug-comp-ui-4 - The work-progress window is a Tk root outside `_popup_active_lock`
- Severity: low
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/popup.py:2207-2213; companion/src/ccsync_companion/app.py:9829-9848
- What: app.py's own comment says the work window is "ONE window at a time, deliberately: two live Tk roots in this process is CORE-M3's wedged interpreter", but that serialisation is only against other WORK windows (`_work_window_lock`). The window opens automatically on a batch start and never touches `_popup_active_lock`, so it routinely coexists with the fixer popup, Settings or an update/licence dialog on another thread, and `apply_upgrade`'s `_popup_active_lock.locked()` stand-down does not count it.
- Failure scenario: a b-roll batch starts while the out-of-tree fixer popup is up: two roots built and pumped on sibling threads at once, the condition the rest of the package treats as a wedge hazard (the fixer batch is then the one auto-ignored, per the copy_diagnostics docstring).
- Evidence: grep for `_popup_active_lock` in popup.py (comments only) and the `_open_work_window` body.
- Ledger: new
- Suggested fix: either make the monitor window take the popup lock non-blockingly (and simply not open while another window is up; the tray item re-opens it), or document that the sibling-root hazard does not apply and drop the contradicting comment.

### bug-comp-ui-5 - Five tray.py dialog builders abandon a mapped root when widget construction raises (the comp-ui-6 shape, fixed only in Settings)
- Severity: low
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/tray.py:1134-1231 (`_build_sign_in_dialog`), 1921-1976 (`_build_typed_confirmation`), 2189-2273 (`_build_credentials_dialog`), 1688-1722 (`_build_update_dialog`), 1781-1816 (`_build_scripting_warning_dialog`); contrast settings_window.py:1652-1690 and popup.py:913-924
- What: each builds `tk.Tk()` and then widgets with no `try/finally: root.destroy()`. The update and scripting-warning builders catch the exception but only log and notify; the other three let it propagate. comp-ui-6 (2026-09-11) established that a TclError/OSError mid-build leaves a mapped, unresponsive window with no mainloop, which `reclaim_mine` then pins for the life of the process because `winfo_exists()` is still true, and it fixed that for Settings and PopupDialog only.
- Failure scenario: an RDP reconnect or display change while the typed "REMOTE"/"DELETE ANYWAY" confirmation is being built: the half-built window stays on screen, frozen and uncloseable, the caller releases the popup lock, and every retry adds another one.
- Evidence: read the five builders; no destroy on the exception path.
- Ledger: related to comp-ui-6 (bug-hunt-2026-09-11, fixed for settings_window only)
- Suggested fix: wrap each body after `tk.Tk()` in `try: ... except: destroy root; raise/return default`, or factor one helper that every builder uses.

### bug-comp-ui-6 - `_WindowsIcon._teardown` iterates `_hicon_cache` unguarded while the pulse/refresh threads can still insert, and a raise there skips `_stopped.set()`
- Severity: low
- Confidence: PLAUSIBLE
- Where: companion/src/ccsync_companion/tray_native.py:923-927, 1474-1489 (`run`'s finally, `_teardown`), 1088-1107 (`_icon_handle`)
- What: `stop()` sets `_ccsync_stop` and posts the quit, but a pulse or refresh tick already past its loop check can still call `icon.icon = ...` -> `_modify` -> `_icon_handle`, which inserts into `_hicon_cache` while the pump thread is iterating `.values()` in `_teardown` (the per-item try does not cover the iteration). `RuntimeError: dictionary changed size during iteration` escapes `run()`'s `finally` before `self._stopped.set()`, so `stop()` waits its full 5 s and the thread dies with a crash report written for an ordinary Quit.
- Failure scenario: Quit or self-upgrade while the icon is pulsing a colour whose frames were not yet cached (a state change in the same second): 5 s frozen shutdown plus a spurious crash file that the next report counts.
- Evidence: read the code paths; noted but explicitly not reported in the 2026-09-03 comp-ui hunter's coverage note. Narrow window, not reproduced.
- Ledger: new
- Suggested fix: iterate `list(self._hicon_cache.values())`, and put `self._stopped.set()` in its own `finally` after `_teardown`.

## Coverage note
Not reached: most of settings_window.py's model builders (`build_settings_model` and the action_* functions other than set_role/restart), tray.py's snapshot and advisory-line builders, popup.py's row building and perform_fix_all, theme.py's branding registry half, supervisor.py (only crash_report's use of it). ui_dispatch's pin/free arithmetic (`_baseline`, `_try_free`) was checked by reading on Python 3.12 (the venv and CI interpreter) and holds; a move to 3.14's borrowed-reference `getrefcount` would need it re-measured. crash_report's faulthandler covers the Tcl_Panic breakpoint (0x80000003 has the high bit set, so faulthandler's Windows handler does not ignore it).

## OUT OF TERRITORY
- companion/src/ccsync_companion/broll_server.py:1967: `pick_ingest_sources` is the loopback half of bug-comp-ui-1 (no popup lock reachable there; needs `app` threaded through).
