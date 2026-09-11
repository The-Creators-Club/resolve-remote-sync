## The companion tray, its windows and the relaunch net (CR-235, 2026-09-11)

### comp-ui-1 - a Windows tray icon that failed to register was silently headless, and every toast after it was dropped without a word - FIXED (companion, `tray_native.py`, `tray.py`)

`_WindowsIcon.run` caught a failed `_create_window`/`_add_icon`, logged one
line, set `_stopped` and returned. Nothing in the repo read `_stopped`:
`start_tray` neither waited nor asked, `app.run()` logged "tray icon started"
on the very next line, and the refresh and pulse loops went on snapshotting
and assigning to a dead icon for the life of the process. `notify()` was
`if not self._added: return`, so from that moment **every** tray toast was
discarded in silence - the lane B breaker, a fleet halt, the free-space park
and a sync drive pulled mid-transfer included. An editor could sync all day
with no icon, no menu, no Settings, no Quit and no balloon when sync stopped
itself, and the log said "tray icon started". macOS has had this check since
MAC-7; Windows had none.

Four changes. The first registration now backs off instead of giving up after
six half-second tries: 0.5, 1, 2, 4, 8 then 15 s a try, twelve attempts, about
two and a half minutes, because at LOGIN Explorer's notification area is
regularly not ready inside three seconds. Every failed attempt is a WARNING
naming the attempt number and `GetLastError`, so "my tray icon is missing"
has a timeline in the log. The Explorer-restart re-add keeps the short
schedule - it runs on the pump thread, where a two-minute sleep would freeze
the tray - but now announces its failure too. `notify()` logs at WARNING what
it dropped and why. And a registration that never succeeds calls
`on_register_failure`, which `start_tray` wires to
`tray._report_windows_icon_failure`: an ERROR line telling the editor what
they can do, a crash report (so it rides the existing `sync_guard.crashes`
block and `build_diagnostics` - no new wire field, nothing to deploy in
order), and `_ccsync_stop`, which finally stops the two loops spinning on a
dead icon. `_WindowsIcon`, `_DarwinIcon` and `_NullIcon` all carry
`registered` and `on_register_failure` now, so "is it actually there?" is one
question on every platform.

### comp-ui-2 / res-companion-4 - the supervisor's "three relaunches an hour" ceiling was unenforceable when its history file could not be written - FIXED (companion, `supervisor.py`, `crash_report.py`)

CLAUDE.md and the module docstring both promise three relaunches an hour at
most. That ceiling had no memory outside `<state>/supervisor.json` - each
supervisor lives for exactly one companion - and both `read_history` (returns
`[]`) and `write_history` (returned None) swallowed every failure. A state
directory that could not be written handed `decide()` an empty history on
every death, and a build that could not stay up was relaunched every ten
seconds for ever, each relaunch spawning the next supervisor and extracting a
50 MB `_MEI`. The verifier is right that the common scenario (disk full) also
breaks the run marker, which caps the loop at one relaunch; the unbounded
shape needs an asymmetric filesystem condition - a per-file AV lock or ACL,
or `supervisor.json` existing as a directory - which is narrow but real. The
second half of `decide`'s window test was file-independent and stood on its
own: `0 <= now - t` meant a stamp in the FUTURE did not count, so an NTP
correction or a resume that stepped the wall clock backwards forgave every
relaunch the build had just made.

The count now travels on the child's command line as well as in the file. The
supervisor writes the merged history into its relaunch note;
`crash_report.install_native` reads it (`note_relaunch_history`) and
`start_supervisor` passes it to the next supervisor as `--prior t,t,t`, which
`main` unions with whatever the file could give it (`merge_history`, higher
count wins - a ceiling that over-counts leaves a machine to its logon
autostart, which a human notices; one that under-counts relaunches for ever).
`write_history` returns whether it wrote, and a supervisor that could not
record its own relaunch says so loudly in `supervisor.log`. The window test
is `abs(now - t)`, so a stamp we cannot place is still a relaunch. The flag is
omitted entirely when there is nothing to carry and a malformed value falls
back to the file, so a companion one release older produces exactly the argv
it always did.

### comp-ui-3 - the fixer's "could not save that choice" line said FOR YOUR ADMIN twice - FIXED (companion, `popup.py`)

The wave-4 copy pass replaced the hand-written menu route with
`ui_copy.DIAGNOSTICS` and left the tail of the old literal behind, so an
editor whose "always leave this folder alone" choice failed to persist read
"... COPY DIAGNOSTICS FOR YOUR ADMINFOR YOUR ADMIN." - no space, no full
stop, the phrase doubled. It is a module constant now
(`popup.IGNORE_FOLDER_FAILED`), so the suite can assert on it without
building a dialog.

### comp-ui-4 - the "(s)" plurals UX-10 retired were still shipping from tray.py and settings_window.py, and the scan test could not see them - FIXED (companion, `tray.py`, `settings_window.py`, `tests/test_sweep_2026_09_04_copy.py`)

UX-10 introduced `ui_copy.count(n, noun)` so no editor-facing string says
"3 file(s)", and `test_the_sentences_ux10_named_no_longer_say_lane_a_or_s`
pins the retired sentences - while scanning `app.py` and `popup.py` only. One
of the exact phrases in its `retired` tuple, "project(s) are not sharing
yet", lives in `tray.py` and was being rendered as a Settings advisory the
whole time the test asserted it was gone. Eleven visible "(s)" strings across
the two files are now real plurals with their verbs agreeing ("1 project is
not sharing yet" / "2 projects are"), and the scan reads all four files plus
a blanket "no new (s) in these two" check, which is what would have caught
them.

### comp-ui-5 - the macOS Quit confirmation blocked the main thread, and with it ui_dispatch's pump, for up to two minutes - FIXED (companion, `tray.py`)

On macOS a tray menu action runs on the main thread (`CCSyncTrayTarget.invoke_`
does no hop), and the main thread is also `ui_dispatch`'s pump - a
`root.after` timer that cannot fire while that frame is on the stack. Quit
called `osascript` with `timeout=120` inline there, so an editor who left the
"CCSync is still copying" alert on screen froze the FIX ALL progress window
and every `dispatch(fn)` a worker thread made, for as long as they read it.
`_darwin_on_main_thread`'s own docstring states the rule this broke. The Quit
item is `tray.quit_from_menu` now: on macOS the whole ask-then-shutdown moves
to a worker thread (`_DarwinIcon.stop()` and the toasts under it already hop
to the main thread themselves, and `app.shutdown()` was never main-thread
work), and on Windows it stays inline on the pump thread, which is the thread
Quit is supposed to end. The confirmation still fails OPEN, unchanged: a Quit
that silently does nothing is the worse bug.

### comp-ui-6 - an exception while building the Settings window left a Tk root on screen with no event loop and its interpreter pinned - FIXED (companion, `settings_window.py`)

Every other dialog in the package destroys its root in a `finally` or hands
it to `release_root`. Here, a `TclError`/`OSError` raised anywhere between
`tk.Tk()` and `run_dialog` - widget construction on a display that went away,
an RDP session change, `_refresh` arming a timer on a root Tk has torn down -
propagated out through `ui_dispatch` into `show_settings`, which released the
lock and destroyed nothing: a mapped, unresponsive window with no mainloop
that the editor cannot close, an interpreter `reclaim_mine` pins for the life
of the process because `winfo_exists()` is still true (CR-93), and another one
beside it on every later Settings click. `_build_settings_window` now hands
its `_release_and_close` to a one-slot holder the moment the root exists, and
`show_settings`'s dispatched builder calls it if anything below raises. A
holder rather than a wrapper function on purpose: the Tk root has to be built
in the function the dispatcher calls directly, which
`tests/test_tk_interpreter_hygiene.py` pins.

### comp-ytdl-jobs-3 (the tray/Settings half) - a persistently failing ffmpeg sidecar install reached nobody - FIXED (companion, `tray.py`, `settings_window.py`)

`ytdlp_manager.sidecar_warning_line()` (comp-ytdl-jobs' half) is rendered
through `tray.ytdlp_sidecar_line`, in Settings beside the yt-dlp line and in
the tray menu's state block. Both, and not only Settings > YOUTUBE: "this
computer cannot install ffmpeg" is about proxies and fleet media work, and
that section is absent on a machine with the YouTube features off. It is in
`_menu_fingerprint` too, or the line would not appear until something
unrelated moved the menu and would linger after the install finally worked -
UI-3's shape.

### comp-sync-1 (the tray half) - a safety latch that could not write its state file said so nowhere an editor looks - FIXED (companion, `tray.py`, `settings_window.py`)

The three latches comp-sync taught to report a failed persist (lane B's
breaker, the free-space park, a fleet halt) are all "never in-memory only" by
rule, precisely so that only a human clears them. A latch whose file will not
write is therefore a latch the next restart silently drops - a machine that
quietly resumes doing the thing a safety latch stopped. `tray._persist_failed_line`
reads all three (`persist_failed`, with the reason in the sibling
`persist_error`), collapses them into one sentence because they share a
directory and are one fault with up to three symptoms, and returns None when
the keys are absent, which is how the happy path is spelled on a wire whose
other end may be older. It is registered BLOCKING in `_lane_advisories`, and
the three booleans are in `_guard_fingerprint` - without that the line would
not appear until something unrelated moved the menu and would linger after
the 60 s retry finally wrote, which is UI-3's shape.

### comp-sync-15 (the test half) - the Settings trash assertion hand-built a shape no producer emitted - FIXED (companion, `tests/test_settings_window.py`)

`test_the_lanes_section_ranks_a_halt_above_the_trash_size` built its
`sync_guard["trash"]` by hand with `path` and `max_age_days`, keys nothing
produced until comp-sync-15 added them: the test pinned a phantom while every
editor read the bare folder name and a hardcoded default. The block now comes
from a real `RcloneLane.trash_report()` (a lane pointed at tmp_path, its own
prune run), with only the size and count substituted, so the same drift
cannot happen again silently.

### comp-sync-4 (the tray half) - two producers computed on every pass and read by nobody - FIXED (companion, `tray.py`, `settings_window.py`)

`app.shared_folder_problems()` (SYNC-101) and `app.repath_events()`
(SYNC-102) had no caller anywhere: not the tray snapshot, not the report. A
shared LUT library that is not working on this machine, and a project folder
this machine MOVED because an admin renamed it on the server, were computed
every sequencer pass and reached only companion.log. comp-app put both into
`sync_guard` (absent when empty, capped at 10); this side reads them.

Both are in the tray snapshot's `_get(...)` block - lock-guarded reads with no
I/O, which is the only kind allowed on that path (COMP-CORE-6) - and are
folded into the snapshot's guard when `sync_guard()` did not carry them, so
the lines appear on a companion whose app half is older too. Two producers,
`_shared_folders_line` and `_repath_line`, sit beside `_conflicts_line` in
`_lane_advisories` at WARNING: syncing continues in both cases, and what the
editor has lost is a shared library or a set of Resolve links. The repath line
names the old and the new folder and points at SCAN WHOLE PROJECT, and is
silent for an event whose clips were already relinked - there is nothing left
to do then, which is also why this cannot be driven off a count alone. The
fingerprint carries the COUNT and the repath ids (old, new, relinked), never
the sentences: those hold absolute paths and would rebuild the menu for a
string that never changes.

### Verification
- `companion/tests/test_bug_hunt_2026_09_11_comp_ui.py::test_a_tray_icon_that_will_not_register_retries_with_backoff` -> fails at 40f931a (no `attempts` argument, six fixed half-second tries, no log line), passes now
- `companion/tests/test_bug_hunt_2026_09_11_comp_ui.py::test_a_registration_that_never_succeeds_announces_itself` -> fails at 40f931a, passes now
- `companion/tests/test_bug_hunt_2026_09_11_comp_ui.py::test_a_dropped_toast_says_what_it_dropped` -> fails at 40f931a, passes now
- `companion/tests/test_bug_hunt_2026_09_11_comp_ui.py::test_the_failure_is_reported_and_stops_the_refresh_loops` -> fails at 40f931a, passes now
- `companion/tests/test_bug_hunt_2026_09_11_comp_ui.py::test_start_tray_wires_the_failure_hook_on_windows` -> fails at 40f931a, passes now
- `companion/tests/test_bug_hunt_2026_09_11_comp_ui.py::test_the_ceiling_survives_a_history_file_that_cannot_be_written` -> fails at 40f931a, passes now
- `companion/tests/test_bug_hunt_2026_09_11_comp_ui.py::test_merge_history_is_a_union_and_stays_bounded` -> fails at 40f931a, passes now
- `companion/tests/test_bug_hunt_2026_09_11_comp_ui.py::test_a_clock_that_steps_backwards_does_not_forgive_the_relaunches` -> fails at 40f931a, passes now
- `companion/tests/test_bug_hunt_2026_09_11_comp_ui.py::test_main_carries_the_history_to_the_relaunched_companion` -> fails at 40f931a, passes now
- `companion/tests/test_bug_hunt_2026_09_11_comp_ui.py::test_a_history_that_cannot_be_written_is_logged_loudly` -> fails at 40f931a, passes now
- `companion/tests/test_bug_hunt_2026_09_11_comp_ui.py::test_write_history_reports_whether_it_wrote` -> fails at 40f931a, passes now
- `companion/tests/test_bug_hunt_2026_09_11_comp_ui.py::test_start_supervisor_hands_on_the_count_it_was_relaunched_with` -> fails at 40f931a, passes now
- `companion/tests/test_bug_hunt_2026_09_11_comp_ui.py::test_the_fixer_s_could_not_save_line_is_not_garbled` -> fails at 40f931a, passes now
- `companion/tests/test_bug_hunt_2026_09_11_comp_ui.py::test_no_visible_string_in_the_tray_or_settings_says_s_in_brackets` -> fails at 40f931a, passes now
- `companion/tests/test_bug_hunt_2026_09_11_comp_ui.py::test_the_unfiltered_line_counts_properly` -> fails at 40f931a, passes now
- `companion/tests/test_bug_hunt_2026_09_11_comp_ui.py::test_the_quit_confirmation_counts_properly` -> fails at 40f931a, passes now
- `companion/tests/test_sweep_2026_09_04_copy.py::test_the_sentences_ux10_named_no_longer_say_lane_a_or_s` -> fails at 40f931a once tray.py and settings_window.py are in its file list, passes now
- `companion/tests/test_bug_hunt_2026_09_11_comp_ui.py::test_quit_asks_off_the_main_thread_on_macos` -> fails at 40f931a (no `quit_from_menu`), passes now
- `companion/tests/test_bug_hunt_2026_09_11_comp_ui.py::test_quit_runs_inline_where_the_pump_is_not_the_caller` -> fails at 40f931a, passes now
- `companion/tests/test_bug_hunt_2026_09_11_comp_ui.py::test_a_settings_window_that_fails_mid_build_is_destroyed` -> fails at 40f931a (the root is never destroyed), passes now
- `companion/tests/test_bug_hunt_2026_09_11_comp_ui.py::test_a_failing_ffmpeg_install_reaches_the_tray_menu` -> comp-ytdl-jobs-3, passes now
- `companion/tests/test_bug_hunt_2026_09_11_comp_ui.py::test_the_sidecar_line_moves_the_menu_fingerprint` -> comp-ytdl-jobs-3, passes now
- `companion/tests/test_bug_hunt_2026_09_11_comp_ui.py::test_the_sidecar_line_is_in_the_settings_youtube_section` -> comp-ytdl-jobs-3, passes now

- `companion/tests/test_bug_hunt_2026_09_11_comp_ui.py::test_a_latch_that_cannot_persist_gets_a_line` -> comp-sync-1, fails before the fix (no `_persist_failed_line`), passes now
- `companion/tests/test_bug_hunt_2026_09_11_comp_ui.py::test_all_three_latches_are_read_and_the_line_names_them_once` -> comp-sync-1, passes now
- `companion/tests/test_bug_hunt_2026_09_11_comp_ui.py::test_the_persist_failure_moves_the_menu_fingerprint` -> comp-sync-1, fails before the fix, passes now
- `companion/tests/test_bug_hunt_2026_09_11_comp_ui.py::test_the_persist_line_is_one_of_the_settings_advisories` -> comp-sync-1, fails before the fix, passes now
- `companion/tests/test_settings_window.py::test_the_lanes_section_ranks_a_halt_above_the_trash_size` -> comp-sync-15, now built from `RcloneLane.trash_report()` rather than by hand

- `companion/tests/test_bug_hunt_2026_09_11_comp_ui.py::test_a_broken_shared_folder_gets_a_line` -> comp-sync-4, fails before the fix, passes now
- `companion/tests/test_bug_hunt_2026_09_11_comp_ui.py::test_a_renamed_project_folder_gets_a_line` -> comp-sync-4, fails before the fix, passes now
- `companion/tests/test_bug_hunt_2026_09_11_comp_ui.py::test_both_sections_move_the_menu_fingerprint` -> comp-sync-4, fails before the fix, passes now
- `companion/tests/test_bug_hunt_2026_09_11_comp_ui.py::test_both_sections_are_settings_advisories` -> comp-sync-4, fails before the fix, passes now
- `companion/tests/test_bug_hunt_2026_09_11_comp_ui.py::test_the_snapshot_reads_both_producers` -> comp-sync-4, fails before the fix, passes now

Suites run (only the files touched): `test_bug_hunt_2026_09_11_comp_ui.py`,
`test_sweep_2026_09_04_copy.py`, `test_tray.py`, `test_settings_window.py`,
`test_tray_wave3_says_what_it_knows.py`, `test_popup.py`,
`test_supervisor.py`, `test_crash_report.py`, `test_crash_loop_revert.py`,
`test_tray_native_main_thread.py`, `test_ui_dispatch.py`,
`test_tk_interpreter_hygiene.py`, `test_tk_release_native.py`,
`test_tray_guard.py`, `test_tray_copy_names_real_menu_items.py`,
`test_no_em_dash.py`, `test_idle.py`, `test_theme.py`,
`test_shutdown_guard.py`, `test_ytdlp_manager.py` - all green.

### OWED TO ANOTHER TERRITORY
- `companion/src/ccsync_companion/app.py:9963` (comp-app): `log.info("tray icon
  started")` fires unconditionally on the line after `start_tray` returns, and
  on Windows `start_tray` returns before `run()` has done anything. It should
  read the icon instead - `getattr(icon, "registered", True)` is now a real
  answer on all three backends - and say "the tray icon could not be placed"
  when it is False. comp-ui-1 is safe without it: the failure is already an
  ERROR line and a crash report, but the log still contradicts itself.
- `companion/src/ccsync_companion/app.py:3032` (comp-app): `_notify_tray` only
  logs on an exception, so it still cannot tell a delivered toast from a
  dropped one. comp-ui-1 covers this from the backend side (`notify()` logs
  what it dropped at WARNING with the reason), so this is a nicety now, not a
  gap.
- `companion/src/ccsync_companion/upgrade.py` (comp-app): res-companion-4's
  second counter. `_write_json` returns False and logs at DEBUG, and
  `note_version_start` does not check the return, so APP-5's crash-loop revert
  degrades silently from the same directory. It should log at WARNING when the
  write fails. Not touched here - out of territory - and the supervisor half
  is fixed independently of it.
- comp-sync's two owed items landed here after the first pass and are DONE:
  the three `persist_failed` booleans are in `tray._guard_fingerprint` with a
  BLOCKING advisory line (comp-sync-1), and the Settings trash assertion is
  built from `RcloneLane.trash_report()` (comp-sync-15), and both
  `shared_folder_problems` and `repath_events` are read by the snapshot, the
  fingerprint and an advisory line each (comp-sync-4). Nothing further is
  owed back to comp-sync.

### Owner decisions
- The "report" channel for a tray icon that will not register is a crash
  report (`sync_guard.crashes`), not a new field. It keeps the change
  deploy-order-free and puts the failure where `build_diagnostics` already
  looks, but it does mean a headless tray shows on the dashboard as "a
  background task failed" rather than by name. A named `sync_guard.tray` field
  would read better on the fleet grid and would need the dashboard deployed
  first.
- The first registration now spends up to ~2.5 minutes retrying before giving
  up. That is deliberate (Explorer at login), and the cost is that a genuinely
  broken tray takes that long to report itself. The lanes are unaffected - the
  icon lives on its own thread.
- The two comp-sync-4 lines are WARNING, not BLOCKING: neither stops a lane,
  and the advisory cap ranks BLOCKING first. If the owner would rather a
  renamed project folder outrank, say, the trash size, it is one word.
- comp-sync's owed line was quoted as "CC Sync cannot save its safety state
  ...". I shipped it as "CCSync", which is what every other tray and Settings
  line in this file says; the product name elsewhere comes from the site
  manifest, and a one-off spacing would be the only place in the companion
  that differs. Easy to flip if the owner wants the spaced form everywhere.
- The macOS Quit confirmation still fails OPEN on a timeout (assume "quit"),
  unchanged from RES-8. The verifier suggested "assume keep copying" instead;
  I kept the existing contract because a Quit that silently does nothing is
  the failure that posture was chosen against, and the blocking half - which
  was the actual defect - is gone either way.
