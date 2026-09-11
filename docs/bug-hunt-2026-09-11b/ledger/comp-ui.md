## The tray, the Settings window and the supervisor, 2026-09-11 (CR-251)

### CR-251a (comp-ui-1 / regression-7) - a failed Explorer-restart re-add killed the tray refresh loops for the life of the process - FIXED (`tray_native.py`, `tray.py`)

`_ccsync_stop` is the flag `start_tray` wraps `icon.stop()` to set: it means
"this icon is dead, stop refreshing it", and NOTHING in the repo ever clears
it. CR-235 reused it as a side effect of the new diagnostic path
(`_report_windows_icon_failure`) and wired that path to the Explorer-restart
handler as well as to the terminal failure in `run()`. An Explorer restart is
recoverable: the pump thread is still alive and the next `TaskbarCreated`
broadcast calls `_add_icon()` again. So an Explorer that restarts twice in
quick succession (a shell crash, a GPU driver reset, an update) failed the
first re-add, ended the refresh and pulse threads, and then succeeded on the
third broadcast - leaving the editor a CCSync icon showing the colour, the
tooltip and the menu as they were at the moment of the failure, for the rest
of the session. The lane lines never move, the icon never changes colour, and
the lane B breaker, fleet halt and disk-floor lines can never appear. Green
while dead, which is worse than the headless companion CR-235 set out to fix.
`_announce_failure` now takes `fatal` (True from `run()`, where the pump never
started and stopping the loops is right; False from the TaskbarCreated
handler), and `_report_windows_icon_failure` sets `_ccsync_stop` only when
fatal. The ERROR line and the crash report are written either way, so the
diagnostic half of CR-235 is untouched. The hook's arity is asked with
`inspect.signature` rather than discovered by catching TypeError - a TypeError
raised inside a two-argument hook would otherwise be read as "it takes one"
and run the hook twice.

### CR-251b (comp-ui-2 / regression-16) - the Explorer-restart re-add froze the tray for 15.5 s, against its own comment - FIXED (`tray_native.py`)

CR-235 gave the first registration an exponential backoff and its comment
says, in as many words, "The Explorer-restart re-add keeps the short schedule;
it runs on the pump thread, where a two-minute sleep would freeze the tray."
Only the attempt COUNT stayed short. `_add_icon()` with no argument still got
six attempts, but the delays came from `_nim_add_delays(6)` =
`[0.5, 1, 2, 4, 8, 15]`, so a re-add against an Explorer that has only just
come back slept 0.5+1+2+4+8 = 15.5 s INSIDE the window procedure, against 2.5 s
before the change. For those 15.5 s the message pump processes nothing: no
right-click menu, no `_CCSYNC_WM_QUIT_TRAY`, no NIM_MODIFY from the refresh
thread, a `stop()` from another thread timing out at its own 5 s wait, and
Windows free to mark the window as not responding. `_add_icon` now takes a
`cap`, and the FLAT delay is its default: any caller that does not ask for the
long schedule gets the pump-safe one, and only `run()`'s first registration
opts in. The comment's arithmetic was wrong too and is corrected: twelve
attempts sleep 1 min 46 s, not two and a half minutes.

### CR-251c (comp-ui-3) - every relaunch was counted twice, so the "three relaunches an hour" ceiling fired after two - FIXED (`supervisor.py`)

`merge_history` de-duplicates through a set of floats, and the two sources
spell the same relaunch differently: `write_history` persists `time.time()` at
full precision, and `supervisor_argv` formats the argv copy `%.3f`. They are
two different floats, so the union carried two entries per relaunch and
`decide`'s `len(recent) >= MAX_RELAUNCHES` counted both. On the build that
aborts on every start - the CR-93 shape this supervisor exists for - the
companion got two attempts, not three, and the third was refused with "already
relaunched 4 times in the last 60 minutes"; `note["attempt"]`, rendered into
the editor-facing unclean-exit report as "relaunch N of 3", said "3 of 3" on
the second. The stamps are now quantised to milliseconds (`round(x, 3)`)
before the union, which makes the file spelling and the argv spelling the same
value and the merge idempotent; milliseconds is finer than anything here
measures. CR-234's own tests could not see this because every one of them uses
`NOW = 1_700_000_000.0`, which is exactly representable in `%.3f` and
round-trips unchanged - the "passes for a reason unrelated to the fix" shape.
The new tests use a `NOW` with microseconds.

### CR-251d (comp-ui-4) - the "cannot save its safety state" line told the editor to do the one thing that drops the latch - FIXED (`tray.py`)

The sentence ended "Restarting CCSync would clear it." Every other BLOCKING
advisory in that list ends with the action the editor should take, so that
read as the remedy on offer - and a restart is exactly what silently drops the
lane B breaker, the fleet halt or the disk-floor latch that the line exists to
protect. `docs/SYNC_SAFETY.md`'s rule is that only a human clears a latch; the
copy invited the editor to clear one by accident, with proxy download
resuming against the same NAS and no record that anything was ever set. It now
says what a restart would cost and names an action the editor can take: "...
so restarting CCSync would silently resume what it stopped. Press COPY
DIAGNOSTICS FOR YOUR ADMIN below and send that to your admin before you
restart." The button name comes from `ui_copy.ROUTE_ROWS`, so a rename of the
button moves the sentence with it.

### CR-251e (comp-ui-5) - the Quit-while-copying confirmation was garbled when the batch total was not known - FIXED (`tray.py`)

`quit_confirm_text` fell back to the fragment `"files in"` when `total` was
falsy and then spliced it after "copying file {index}": with an `index` and no
`total` - which `popup.py`'s progress publisher produces, since it coerces a
missing `total` to 0 - the editor was asked to confirm against "CCSync is
copying file 3 files in.", broken English on the one dialog that asks him to
make a careful choice. With no total there is no "N of M" to say, so the index
is dropped rather than half-rendered: "CCSync is copying a file into your
synced folder." The known-total sentences are unchanged.

### CR-251f (comp-ui-6) - three Settings-only advisories were in the tray MENU fingerprint - FIXED (`tray.py`)

`_guard_fingerprint` is what decides whether the tray menu is rebuilt, and
three entries in it (the persist-failure flags from CR-233's comp-sync-1, the
shared-folder count and the repath ids from comp-sync-4) each carried a
comment saying the value "adds a LINE, so without it here the line would not
appear until something unrelated moved the menu". They do not.
`_persist_failed_line`, `_shared_folders_line` and `_repath_line` have exactly
one caller in the repo, `settings_window._lane_advisories`, and every advisory
line was deliberately moved out of the tray menu into Settings, which
re-renders on its own 2 s timer. The entries bought nothing and cost a full
`_build_menu` plus its HMENU teardown every time a repath list or a flapping
state directory moved - and the fingerprint is the mechanism that keeps the
2026-07-26 hover hang away. They are gone and the comment now says where the
lines actually render, with the condition under which an input belongs back
there. CR-235's two tests asserted the fingerprint moves; they assert the
opposite now, citing this id.

### CR-251g (comp-ui-7) - show_settings could release a lock another window now held - FIXED (`settings_window.py`)

`_popup_active_lock` is a plain `threading.Lock`, so `locked()` cannot say
WHOSE. When the builder failed, CR-235's `_release_and_close` released the
lock and `_build_and_show` re-raised; `show_settings`' handler then asked
`lock.locked()` and released it again. A second Settings click or the
watcher's popup taking the lock in the microseconds between the two is enough
for the handler to release THEIR lock, and a third `tk.Tk` root can then be
built beside the second - the CR-93 shape. `show_settings` now tracks whether
the lock is still its own (`mine`, cleared the moment `_build_and_show` is
entered) instead of asking the lock.

### CR-251h (comp-resolve-b-1) - FIX ALL still counted a rehearsal as bytes copied - FIXED (`popup.py`)

CR-236 taught three call sites that `fixer.fix_clip`'s rehearsal arm answers
`{"ok": True, "dry_run": True}` and copied nothing:
`consolidate.run_consolidation`, `consolidate.count_copied` and app.py's
consolidate toast. `popup.perform_fix_all`, the loop behind the FIX ALL button
every editor actually presses, was not touched - it still did
`if outcome.get("ok"): batch_done += file_total`. An admin who sets
`fixer_dry_run` (the RES-15 rehearsal switch, whose entire purpose is a screen
that can be trusted) and runs FIX ALL over 40 clips and 800 GB watched
`batch_bytes_done` climb to 800 GB in a second or two, the bar fill, and
RateEstimator's speed and ETA read off nonsense. The loop now credits bytes
only when the copy was real, counts `fixed` as ok-and-not-dry_run, publishes
`rehearsal` alongside it as `run_consolidation` does, and subtracts the
rehearsed files from `failed`. The counts are spelled out rather than imported
from `consolidate.count_copied`: consolidate imports popup, and the reverse
import would close the cycle.

### CR-251i (regression-12 / res-companion-3) - an interrupted self-upgrade left a machine with no companion and nothing that could put it back - FIXED (`supervisor.py`)

res-companion-3 was claimed fixed in the CR-233..248 pass and no fix existed
anywhere in the tree. A self-upgrade is two `os.replace` calls (exe -> exe.old,
then the download -> exe); killed between them - a power cut, a reboot, an AV
quarantine of the new binary - the machine has no `ccsync-companion.exe` at
all. Every in-companion recovery lives inside a companion that cannot start,
the Run key points at a name that is not there, and the supervisor, the one
awake process outside it, logged "the companion exe is no longer on disk:
nothing to relaunch" and exited. The machine then synced nothing until a human
renamed the file. `supervisor.restore_interrupted_upgrade` renames `<exe>.old`
back when, and only when, the exe is MISSING and the marker says the companion
we watched died: it fills a hole and never overwrites, because an `.old`
beside a companion that IS on disk is the ordinary post-upgrade state
(`upgrade.cleanup_old_exe` deletes it on the next start) and renaming over that
would silently downgrade the machine. Loud in the supervisor log either way -
`installer/windows_upgrade.ps1` swaps the same two paths and a human may be
mid-install. The `.old` suffix is spelled in `supervisor.py` rather than
imported: this module deliberately imports nothing from the companion package.

### CR-251j (regression-21) - the relaunch note is a file too, and it failed silently - FIXED (`supervisor.py`)

`merge_history`'s docstring calls the argv copy a source "that does not need a
filesystem at all", but the count only reaches the relaunched COMPANION
through `<crash>/relaunched.json`. CR-234 made `write_history` return a bool
and log a loud WARNING on failure and left `write_relaunch_note` returning
None, swallowing every failure with a bare `pass` and writing in place. With
that file unwritable (an AV lock, or it exists as a directory) and
`<state>/supervisor.json` unwritable too, `decide` saw an empty history for
ever and a build that could not stay up was relaunched every ten seconds with
nothing in any log saying the ceiling had been lost. It returns whether it
wrote, writes tmp+replace like everything else in the package, and `main` logs
the same loud line the history failure gets.

### Verification

Companion suite, run from `companion/` with `.venv\Scripts\python.exe -m pytest`:

- tests/test_bug_hunt_2026_09_11b_comp_ui.py::test_a_failed_explorer_re_add_does_not_kill_the_refresh_loops -> fails at f1eeb42, passes now (comp-ui-1)
- tests/test_bug_hunt_2026_09_11b_comp_ui.py::test_a_first_registration_that_never_succeeds_still_stops_the_loops -> the other arm, unchanged behaviour (comp-ui-1)
- tests/test_bug_hunt_2026_09_11b_comp_ui.py::test_the_failure_hook_takes_a_one_argument_callable -> fails at f1eeb42, passes now (comp-ui-1)
- tests/test_bug_hunt_2026_09_11b_comp_ui.py::test_the_explorer_re_add_keeps_the_short_schedule -> fails at f1eeb42 (15.5 s), passes now (comp-ui-2)
- tests/test_bug_hunt_2026_09_11b_comp_ui.py::test_a_relaunch_is_counted_once_not_once_per_source -> fails at f1eeb42, passes now (comp-ui-3)
- tests/test_bug_hunt_2026_09_11b_comp_ui.py::test_the_ceiling_still_allows_three_relaunches_through_the_whole_chain -> fails at f1eeb42 (2 of 3), passes now (comp-ui-3)
- tests/test_bug_hunt_2026_09_11b_comp_ui.py::test_the_supervisor_puts_a_half_swapped_exe_back -> fails at f1eeb42, passes now (regression-12)
- tests/test_bug_hunt_2026_09_11b_comp_ui.py::test_the_restore_never_touches_a_live_exe -> fails at f1eeb42 (no such function), passes now (regression-12)
- tests/test_bug_hunt_2026_09_11b_comp_ui.py::test_a_relaunch_note_that_cannot_be_written_says_so -> fails at f1eeb42, passes now (regression-21)
- tests/test_bug_hunt_2026_09_11b_comp_ui.py::test_the_persist_failure_line_does_not_recommend_a_restart -> fails at f1eeb42, passes now (comp-ui-4)
- tests/test_bug_hunt_2026_09_11b_comp_ui.py::test_the_quit_confirmation_reads_as_english_with_no_batch_total -> fails at f1eeb42, passes now (comp-ui-5)
- tests/test_bug_hunt_2026_09_11b_comp_ui.py::test_settings_only_advisories_do_not_rebuild_the_tray_menu -> fails at f1eeb42, passes now (comp-ui-6)
- tests/test_bug_hunt_2026_09_11b_comp_ui.py::test_show_settings_never_releases_a_lock_another_window_took -> fails at f1eeb42 (two releases), passes now (comp-ui-7)
- tests/test_bug_hunt_2026_09_11b_comp_ui.py::test_fix_all_credits_no_bytes_for_a_rehearsal -> fails at f1eeb42, passes now (comp-resolve-b-1)

Also re-run green, with five CR-235-era assertions updated to the new
behaviour (the hook's arity, the reworded persist line, and the two
fingerprint tests that comp-ui-6 inverts):
tests/test_bug_hunt_2026_09_11_comp_ui.py (31), tests/test_supervisor.py,
tests/test_tray.py, tests/test_tray_guard.py, tests/test_crash_report.py,
tests/test_settings_window.py (389 together), tests/test_popup.py,
tests/test_consolidate.py, tests/test_sweep_2026_09_04_copy.py,
tests/test_tray_native_main_thread.py (501 together),
tests/test_tray_copy_names_real_menu_items.py, tests/test_no_em_dash.py (201
together). `py_compile` clean on all five source files.

### OWED TO ANOTHER TERRITORY

- comp-ytdl-jobs: `companion/src/ccsync_companion/upgrade.py`: `_OLD_SUFFIX`:
  no change needed today, but `supervisor.py` now spells `.old` itself
  (`_UPGRADE_OLD_SUFFIX`) because it must not import the companion package. If
  the suffix or the two-rename swap ever changes, `restore_interrupted_upgrade`
  changes with it. Companion-only; no deploy ordering.
- Nothing else. Every change here is inside the companion process: no wire
  field, no dashboard half, no schema. A companion carrying these can run
  against any dashboard 0.7.34..0.7.43, and an older companion is unaffected.

### Owner decisions

- comp-ui-6 offered two choices: drop the three entries from the tray menu
  fingerprint, or render those three lines in the tray menu. I dropped them,
  because the lines were moved to Settings deliberately and the menu rebuild
  is the thing the 2026-07-26 hover hang taught us to spend sparingly. If the
  intent was that a latch that cannot persist should also show in the tray
  MENU, that is the other fix and this one has to be reversed with it.
- comp-ui-4's new sentence names COPY DIAGNOSTICS FOR YOUR ADMIN as the
  action. The alternative was naming no action at all and only warning about
  the restart; the hunter's finding asked for an action the editor can take.
- `_add_icon`'s flat retry schedule is now the DEFAULT and the long backoff is
  opt-in, rather than the reverse. A future caller that forgets the argument
  then blocks its thread for 2.5 s, not 105.

### Hand-off wave

#### CR-251k (comp-app-8's owed half) - the unreadable machine id had an advisory and no way out - FIXED (`settings_window.py`)

comp-app-5 stopped the companion minting a SECOND id over a `machine.json`
it could not read, which is right - the dashboard reads a new id as another
computer and the old one is gone for good - and gave the condition no exit.
comp-app-8 added the accessor (`machine.machine_id_unreadable`), the repair
(`machine.remint`) and one tray line per process; the button a human presses
was owed here. Settings -> THIS COMPUTER now carries the warning line while
the file is unreadable and a [ GIVE THIS COMPUTER A NEW ID ] button under
it. The button asks first, in the themed confirm dialog, because this is the
one act in that window whose undo lives only in the bytes `remint` sets
aside (`machine.json.unreadable-<epoch>`); a cancel never reaches `remint`.
"" back from `remint` means the file became readable in between or the new
one could not be written, and neither renders as done. The model builder
asks through `settings_window.machine_id_unreadable()`, which cannot raise:
this runs on the window's 2 s refresh timer, where one exception costs the
editor the whole window. NOT offered in the tray menu: comp-ui-6 has just
taken the Settings-only advisories out of the menu fingerprint, and the
ten-item layout (CR-88) is the owner's.

#### CR-251l (tests-5) - every assertion about the persist-failed line bypassed the caller - FIXED (`tests/test_bug_hunt_2026_09_11b_comp_ui.py`)

tests-5's point: a test that drives a new helper directly cannot see the
helper being kept and stopped being CALLED. `tray._persist_failed_line` had
five assertions across two files and all five called it directly, so
dropping its row from `settings_window._lane_advisories` - its only caller in
the repo, and what `build_settings_model` renders - was invisible. The new
test goes through `_lane_advisories`, checks the severity is BLOCKING
(comp-sync-1's reason: the latch it warns about is one a restart silently
drops) and re-ranks through `rank_advisories`, so SYNC-118's cap cannot hide
it either. Verified by mutation: deleting the producer row fails it.

### Verification (hand-off wave)

Companion suite, from `companion/` with `.venv\Scripts\python.exe -m pytest`:

- tests/test_bug_hunt_2026_09_11b_comp_ui.py::test_an_unreadable_id_file_gets_a_repair_button_in_settings -> fails at f1eeb42 and on wave 1 (no button anywhere), passes now
- tests/test_bug_hunt_2026_09_11b_comp_ui.py::test_a_readable_id_file_offers_nothing -> CONTROL: the button is an answer to a fault, not furniture
- tests/test_bug_hunt_2026_09_11b_comp_ui.py::test_an_id_check_that_raises_does_not_cost_the_whole_settings_window -> fails on an inline `machine_mod.machine_id_unreadable()` call, passes now
- tests/test_bug_hunt_2026_09_11b_comp_ui.py::test_the_repair_asks_first_and_never_reminds_on_a_cancel -> fails at f1eeb42 (no action), passes now
- tests/test_bug_hunt_2026_09_11b_comp_ui.py::test_the_repair_reminds_and_says_so -> fails at f1eeb42, passes now
- tests/test_bug_hunt_2026_09_11b_comp_ui.py::test_a_repair_that_changed_nothing_does_not_render_as_done -> fails at f1eeb42, passes now
- tests/test_bug_hunt_2026_09_11b_comp_ui.py::test_the_persist_failure_line_reaches_the_settings_window -> passes on wave-1 source (it is tests-5's missing coverage, not a defect); FAILS with the producer row removed from `_lane_advisories`, which is the bypass it exists to catch (mutation run)

Also re-run green with the change: tests/test_settings_window.py,
tests/test_sweep_2026_09_04_copy.py, tests/test_no_em_dash.py,
tests/test_tray_copy_names_real_menu_items.py,
tests/test_bug_hunt_2026_09_11b_comp_ui.py (654 together). The vocabulary
scan caught the first spelling of the worker-thread label ("Repair machine
id" - "machine" is a retired word); it is "Repair this computer id".
`py_compile` clean on settings_window.py.

### OWED TO ANOTHER TERRITORY (hand-off wave)

- none. The button is inside the companion process: no wire field, no
  dashboard half, no schema, and an older companion simply does not have it.

### Owner decisions (hand-off wave)

- The repair is in Settings only, not in the tray menu. The hand-off allowed
  either; the menu is the owner's ten-item layout (CR-88) and comp-ui-6 has
  just removed the Settings-only advisories from its fingerprint.
- The button label is "GIVE THIS COMPUTER A NEW ID" rather than "REPAIR...":
  what happens is a new id, and a label that says "repair" would read as
  "recover the old one", which is exactly what this cannot do.
