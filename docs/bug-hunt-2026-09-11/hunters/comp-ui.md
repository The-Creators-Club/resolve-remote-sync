# comp-ui - the companion tray, its windows, and the crash/relaunch net

Files read (with approximate coverage):
- `companion/src/ccsync_companion/ui_dispatch.py` (100%), `supervisor.py` (100%),
  `idle.py` (100%), `ui_copy.py` (100%), `crash_report.py` (the marker/native/
  supervisor half, ~40%), `theme.py` (~30%, unchanged since 097f5a3),
  `shutdown_guard.py` (docstring + API surface only - unchanged since 097f5a3).
- `tray_native.py` (~70%: `fit_toast`, both `Icon` classes, the Win32 pump,
  `_add_icon`/`_modify`/`stop`, the whole darwin half).
- `tray.py` (~50%: the full `097f5a3..HEAD` diff, `compute_overall_color`,
  every `_*_line` advisory producer, `_tray_snapshot`, `_build_menu`,
  `start_tray` + both loops, `_confirm_quit_while_copying`, every `tk.Tk()`
  site).
- `settings_window.py` (~80%: the whole model half plus `show_settings` /
  `_build_settings_window`).
- `popup.py` (the full diff since 097f5a3 plus `PopupDialog._build`/`_run_fix`/
  `_deliver_results`/`_on_ignore*`/`show`, ~45%).
- Tests: `test_tray.py`, `test_popup.py`, `test_settings_window.py`,
  `test_ui_dispatch.py`, `test_tk_interpreter_hygiene.py`,
  `test_sweep_2026_09_04_copy.py` (skimmed), `test_supervisor.py` (skimmed).

Tests run:
`cd companion; .venv\Scripts\python.exe -m pytest tests/test_tray.py tests/test_popup.py tests/test_settings_window.py tests/test_ui_dispatch.py tests/test_theme.py tests/test_shutdown_guard.py tests/test_crash_report.py tests/test_supervisor.py tests/test_idle.py tests/test_no_em_dash.py tests/test_tk_interpreter_hygiene.py tests/test_tk_release_native.py tests/test_tray_guard.py tests/test_tray_native_main_thread.py tests/test_tray_copy_names_real_menu_items.py tests/test_tray_wave3_says_what_it_knows.py tests/test_crash_loop_revert.py -q`
-> **1054 passed in 30.48s**

## Findings

### comp-ui-1 - a Windows tray icon that fails to register is silently headless, and every toast after it is dropped with no word anywhere
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/tray_native.py:826-843` (`_WindowsIcon.run`),
  `:857-869` (`notify` -> `if not self._added: return`),
  `companion/src/ccsync_companion/tray.py:4736-4753` (`start_tray` returns before
  `run()` has done anything), `companion/src/ccsync_companion/app.py:9963-9964`
  ("tray icon started"), `app.py:3032-3040` (`_notify_tray`).
- What: on Windows `start_tray` starts `icon.run` on a daemon thread and returns
  the Icon immediately; `app.run()` then logs "tray icon started". If
  `_create_window` or `_add_icon` fails (the latter raises only after
  `_NIM_ADD_RETRIES` attempts - the documented "Explorer's tray not up yet at
  login" / Explorer crash case), `run()` logs once, sets `_stopped` and returns.
  Nothing reads `_stopped`; `_ccsync_stop` is never set, so `_refresh_loop` and
  `_pulse_loop` keep snapshotting and assigning on a dead icon for the life of
  the process. Worse, `notify()` returns early on `not self._added`, so from then
  on **every** tray toast is discarded in silence - including the four safety
  latches (breaker tripped, fleet halt, free-space park, drive pulled) and the
  "NOT SYNCING" startup toast. `_notify_tray` only logs on an *exception*, and
  there is none.
- Failure scenario: an editor logs in, Explorer's notification area is not ready
  (or Explorer dies later and the `TaskbarCreated` re-add fails); CCSync syncs
  all day with no icon, no menu, no Settings, no Quit, and no balloon when lane
  B's breaker trips. The log says "tray icon started" a line after "the tray icon
  could not be created", and nothing else ever mentions it.
- Evidence: read `run()`/`notify()`/`_add_icon` above; `grep -rn "_stopped"` in
  `tray.py`/`app.py` shows no reader; `app.py:9963` logs success unconditionally
  after `start_tray` returns. macOS has exactly this check
  (`_report_icon_placement` -> WARNING + a toast, MAC-7); Windows has none.
  `grep -an "NIM_ADD\|tray icon could not be created" KNOWN_BUGS.md` -> nothing.
- Ledger: new (the macOS half of the same question is MAC-7, already fixed).
- Suggested fix: have `_WindowsIcon.run` record the failure on the instance, and
  either have `start_tray` wait briefly on `_running` (it already does in
  `run_detached`) and log/report at ERROR, or have `_notify_tray` fall back to a
  `log.warning` plus a `notices`/crash-report entry when `notify()` could not be
  delivered. At minimum set `_ccsync_stop` so the two loops stop spinning.

### comp-ui-2 - the supervisor's "three relaunches an hour" ceiling is unenforceable when its history file cannot be written
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/supervisor.py:175-181` (`write_history`
  swallows every failure), `:167-172` (`read_history` returns `[]` on every
  failure), `:138-142` (`decide`'s cap is computed **only** from that list),
  `:431` (`main` writes the history before spawning).
- What: CLAUDE.md states the supervisor relaunches "three times an hour at most".
  That ceiling has no in-process memory - each supervisor lives for exactly one
  companion - so it is entirely a function of `<state>/supervisor.json`. Both the
  read and the write are `except Exception: pass`. A state directory that cannot
  be written (disk full - which is itself a plausible cause of the crash loop -
  a roaming/redirected profile, an AV lock, a permissions change) therefore hands
  `decide()` an empty history on every single death, and the supervisor
  relaunches a build that cannot stay up forever, roughly every 10 s + crash
  time, each relaunch spawning the next supervisor.
- Failure scenario: an editor's system drive fills; the companion aborts during
  startup on a native path (CR-93 shape, exit 0x80000003, not in
  `DELIBERATE_EXIT_CODES`); `write_history` cannot create the file; the machine
  enters an unbounded crash/relaunch loop with a 50 MB frozen exe extracting its
  `_MEI` each time. Secondary: `clock` is `time.time` (wall clock), so an NTP
  correction or a resume that moves the clock backwards makes `0 <= now - t`
  false for every entry and resets the cap the same way - on a codebase that
  treats clock skew as a first-class fault (`_clock_skew_line`).
- Evidence:
  ```
  >>> for i in range(6): print(supervisor.decide(0x80000003, {'pid':4242}, 4242, [], 1000.0*i).relaunch)
  True True True True True True          # empty history: relaunches forever
  >>> # with a history that persists: True True True False False False
  ```
- Ledger: new (CR-93's supervisor half, shipped 0.9.62).
- Suggested fix: treat "the history could not be written" as a reason to stand
  down (a supervisor that cannot count its own relaunches must not make another),
  or fall back to a second signal it can see - e.g. refuse when the previous
  run's marker `started` timestamp is under a minute old. Consider
  `time.time()`-independence by also storing the count, not just timestamps.

### comp-ui-3 - the fixer's "could not save that choice" line says "FOR YOUR ADMIN" twice
- Severity: low
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/popup.py:1516-1519`
  (`PopupDialog._on_ignore_folder`).
- What: the wave-4 copy pass replaced the literal route with
  `ui_copy.DIAGNOSTICS` but left the tail of the old literal behind:
  ```python
  text="CCSync could not save that choice, so these clips are only "
       f"skipped until you restart. {ui_copy.DIAGNOSTICS}"
       "FOR YOUR ADMIN."
  ```
  `ui_copy.DIAGNOSTICS` is already
  `"Tray > Settings > COPY DIAGNOSTICS FOR YOUR ADMIN"`, so the editor reads
  `"... COPY DIAGNOSTICS FOR YOUR ADMINFOR YOUR ADMIN."` - no space, no full
  stop after the route, the phrase doubled.
- Failure scenario: `perform_ignore_folders` fails to persist (read-only
  `~/.ccsync`, a locked ignore file) and the one sentence explaining that the
  "always leave this folder alone" choice did not stick is visibly garbled.
- Evidence:
  ```
  >>> 'CCSync could not save that choice, so these clips are only skipped until you restart. ' + ui_copy.DIAGNOSTICS + 'FOR YOUR ADMIN.'
  '... restart. Tray > Settings > COPY DIAGNOSTICS FOR YOUR ADMINFOR YOUR ADMIN.'
  ```
  `grep` over the package shows this is the only `ui_copy.<ROUTE>` interpolation
  followed by a stray literal.
- Ledger: new.
- Suggested fix: drop the trailing `"FOR YOUR ADMIN."` and end with `"."` after
  the constant. Add the `_on_ignore_folder` failure string to
  `test_popup.py`'s copy assertions.

### comp-ui-4 - the `(s)` plurals the sweep "retired" are still shipping from tray.py and settings_window.py, and the scan test cannot see them
- Severity: low
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/tray.py:3155`
  (`"{n} project(s) are not sharing yet"`), `:3272`, `:3276`, `:2179`, `:2181`,
  `:3862`; `settings_window.py:824-830`, `:1272`;
  test: `companion/tests/test_sweep_2026_09_04_copy.py:326-352`.
- What: UX-10 introduced `ui_copy.count(n, noun)` so no editor-facing string says
  `"3 file(s)"`, and `test_the_sentences_ux10_named_no_longer_say_lane_a_or_s`
  pins the retired sentences - but it scans **only** `app.py` and `popup.py`. One
  of the exact strings in its `retired` tuple,
  `"project(s) are not sharing yet"`, lives in `tray.py:3155` and is rendered as
  a Settings advisory line today. Ten more `(s)` parentheticals sit in `tray.py`
  and `settings_window.py`. The test therefore asserts the phrase is gone while
  the phrase is what the editor reads - rule 7's "a test that mocks away the
  exact thing that breaks".
- Failure scenario: any machine with a project whose filter list has not landed
  shows `"⚠ 1 project(s) are not sharing yet - waiting for their filter list"`,
  i.e. developer shorthand and a wrong plural, from the window the sweep
  converted.
- Evidence: `grep -n "clip(s)\|project(s)\|folder(s)\|file(s)" tray.py
  settings_window.py popup.py` -> 6 visible strings in `tray.py`, 5 in
  `settings_window.py` (the `popup.py` hits are `log.*` lines, correctly exempt);
  `git log -S "project(s) are not sharing yet"` shows the phrase last touched in
  `c50d274`, the same commit that added the test.
- Ledger: new (UX-10 / CR-145..CR-154 follow-up).
- Suggested fix: route these through `ui_copy.count`, and extend the scan's file
  list to `tray.py` and `settings_window.py` (the two files that hold most of the
  companion's visible copy).

### comp-ui-5 - the macOS Quit confirmation blocks the main thread, and with it ui_dispatch's pump, for up to two minutes
- Severity: low
- Confidence: PLAUSIBLE
- Where: `companion/src/ccsync_companion/tray.py:2222-2233`
  (`_confirm_quit_while_copying`, the darwin branch),
  `tray_native.py:1264-1269` (`CCSyncTrayTarget.invoke_` runs the action on
  whatever thread AppKit calls it on - the main thread),
  `ui_dispatch.py:438-461` (`_pump` is a `root.after` timer on that same thread).
- What: on macOS a tray menu action runs on the main thread. Quit calls
  `subprocess.run(["/usr/bin/osascript", ...], timeout=120)` **inline** there, so
  for as long as the editor leaves the alert on screen (up to 120 s) the main
  thread is in `waitpid`: `ui_dispatch`'s pump timer never fires, so every
  `dispatch(fn)` from a worker thread blocks, the FIX ALL progress window's
  `root.after` callbacks do not run, and `_darwin_on_main_thread` operations
  (tray title/image/menu) queue up. The module docstring for
  `_darwin_on_main_thread` states the rule this breaks ("a tray refresh thread
  must never be able to wait on an open window"); the same reasoning applies to
  the main thread itself.
- Failure scenario: an editor with a FIX ALL copy running clicks Quit, reads the
  alert, walks away. The fixer's progress window freezes (its Tk callbacks are on
  the blocked runloop), and any dialog the watcher wants blocks its thread until
  the alert is answered.
- Evidence: read `invoke_` (no thread hop), `_confirm_quit_while_copying`
  (`timeout=120`, no hop off the main thread), and `MainThreadDispatcher._pump`
  (re-arms only from a `root.after` on the thread that is blocked). Not
  reproducible from Windows - marked PLAUSIBLE.
- Ledger: related to MAC-11 (open in spirit: a main thread that cannot pump).
- Suggested fix: run the osascript alert on a worker thread and block only the
  caller of `on_quit` (it already returns a bool), or use a much shorter timeout
  with an explicit "assume keep copying" default.

### comp-ui-6 - an exception while building the Settings window leaves a Tk root on screen with no event loop and its interpreter pinned
- Severity: low
- Confidence: PLAUSIBLE
- Where: `companion/src/ccsync_companion/settings_window.py:1549-1702`
  (`_build_settings_window`: `tk.Tk()` is guarded, everything from `root.title()`
  at 1581 to `ui_dispatch.run_dialog(root)` at 1700 is not),
  `:1527-1534` (`show_settings`'s `except` releases the lock but destroys
  nothing).
- What: every other dialog in the package either destroys its root in a `finally`
  or hands it to `release_root`. Here, a `TclError`/`OSError` raised anywhere
  between `tk.Tk()` and `run_dialog` (widget construction on a display that went
  away, an RDP session change, `_refresh`'s unguarded
  `refresh_job[0] = root.after(...)` at line 1694 on a root Tk has torn down)
  propagates out of `_build_and_show`, through `ui_dispatch.dispatch`, into
  `show_settings`'s `except Exception`. The lock is released, but the root is
  never destroyed: a mapped, unresponsive window stays on screen with no
  mainloop, `reclaim_mine` sees `winfo_exists()` true and leaves the interpreter
  pinned (~1.8 MB) for the life of the process, and every later Settings click
  opens another one beside it.
- Failure scenario: a display/session change during the ~10 ms of widget
  construction; the editor is left with a dead grey CCSync window they cannot
  close, and after eight of them `reclaim_mine` starts logging the
  `PINNED_WARN_AT` error.
- Evidence: read the function; compare with `popup.py:839-850` (`_drop_widgets`
  + `release_root` in the failed-build path) and `tray.py:1298-1308`. Not
  reproducible without a real display - marked PLAUSIBLE.
- Ledger: related to CR-93 (fixed; this is a path the fix does not cover).
- Suggested fix: wrap 1581-1700 in `try/except`, and on failure call
  `_release_and_close()` (which already destroys and releases) before
  re-raising, matching the `PopupDialog` failed-build path.

## Coverage note
- Not covered: `shutdown_guard.py` beyond its docstring and method list - it is
  unchanged since 097f5a3 and I prioritised the ~2,900 changed lines in
  `tray.py`/`settings_window.py`/`popup.py`. Its `_WindowsKeepAwake` /
  `_DarwinKeepAwake` release paths and `PendingTracker`'s ceiling logic deserve a
  read.
- Not covered: the `theme.py` render helpers, `crash_report.py`'s report
  writing/pruning/redaction half, `tray.py`'s YouTube dialogs and
  `_build_credentials_dialog`, and roughly half of `popup.py`'s `PopupDialog`
  rendering.
- What the suite does not cover: no test spawns a real Tk root (correctly -
  `conftest._no_real_tk_windows` forbids it), so **every** CR-93 claim about a
  real interpreter's refcount, and every "the window is left on screen" path
  above, is unverifiable from the suite. Nothing tests `_WindowsIcon.run`
  failing, nothing reads `Icon._stopped`, and nothing exercises
  `supervisor.main` with an unwritable `state_dir`.

## OUT OF TERRITORY
- `companion/src/ccsync_companion/app.py:9963` - logs "tray icon started" before
  the tray has done anything on Windows (the other half of comp-ui-1).
- `companion/src/ccsync_companion/app.py:3032` - `_notify_tray` has no fallback
  when the backend silently drops a toast; a dropped safety-latch balloon is
  invisible.
