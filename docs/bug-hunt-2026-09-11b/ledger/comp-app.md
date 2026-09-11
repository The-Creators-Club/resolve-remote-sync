# The companion's app core, 2026-09-11b (CR-250)

Twelve findings from the eighth fleet hunt's `comp-app` territory, plus three
routed here from other territories mid-pass: the file moves the report reply
carries, the thread watchdog comp-app-7 rewrote that afternoon, "Sync now",
and several half-landed fixes from the same day's pass.
Everything here is `companion/src/ccsync_companion/app.py` unless the heading
says otherwise; the regression tests are
`companion/tests/test_bug_hunt_2026_09_11b_comp_app.py`.

### CR-250a (res-companion-1 / wire-1) - the crash-resume for an interrupted file move was unreachable - FIXED (app.py)

The same-day fix wrote an `applying` intent row before the first filesystem
call and taught `file_moves.apply_move` to finish the job when a redelivered
command finds `src` gone, `dest` present and OUR row. `_apply_file_moves`
never called it again: the ledger gate short-circuits on
`done is not None and not retry_due(done)`, and `retry_due()` is False for
every state except `retryable`. An `applying` row therefore took the
already-answered branch and replied `ok=False, state=None`, which on the
dashboard means "an old companion answered, and a failure is an answer":
`applied_at` was stamped and the command retired for ever. The project page
showed that machine FAILED with an internal state name as the detail, the
`applying` row stayed in `recent_excludes`'s unresolved set so lane A was
muzzled on that path permanently, and in the kill-BEFORE-the-rename variant
the move was never applied at all while the server was told it had been
answered. The gate now recognises `STATE_APPLYING` as a move this machine was
interrupted in the middle of and falls through to `apply_move`, which either
finishes it or applies it from scratch; a drive that is out when the
redelivery arrives still answers `retrying`, because the root check sits
after the gate. Both of the fix pass's tests missed this (one calls
`apply_move` directly, the other monkeypatches it away), so the new ones
drive `_apply_file_moves` across a simulated kill on both sides of the
rename.

### CR-250b (comp-app-2) - "waiting for the sync drive" rode every report - FIXED (app.py)

comp-sync-20 was right that silence lets the dashboard's 7 day expiry drop a
move for an editor who is away with the drive in their bag, and wrong to say
it twice a minute. `pending_file_moves` re-offers every unanswered move on
every report and `mark_file_move_applied`'s retrying UPDATE matches while
`applied_at IS NULL`, so it can never become a no-op: three moves and a
fortnight away is tens of thousands of identical WARNING lines in the log an
admin opens to find out why something else went wrong. The answer is now
queued at most once per `FILE_MOVE_DRIVE_ANSWER_SECONDS` (30 minutes) per
move, and the record is cleared the moment a report is processed with the
drive present, so a new outage says so at once. Deliberately not "once per
outage": a lost report would then cost the move, and half an hour is well
inside the 7 days the answer exists to hold off. The dashboard half of this
finding (log only on a CHANGE of state or detail) is OWED to dash-api.

### CR-250c (comp-app-3) - the watchdog's hourly ceiling was dead code - FIXED (app.py)

`LANE_WATCHDOG_MAX_RESTARTS_PER_HOUR = 6` and a wait of
`60 * 2**len(recent)` capped at 30 minutes are one policy, and they
contradicted each other: the earliest six restarts fall at t = 0, 120, 360,
840, 1800 and 3720 s, by which time the first has aged out of the hour, so
`len(recent)` never reached 6. The branch that says "this needs a human, not
another restart" could not run, and a sequencer whose loop dies immediately
was restarted for ever - 97 times in a simulated day, which is the behaviour
comp-app-7 says it removed. The backoff cap is 10 minutes now, which leaves
room for six attempts (0, 120, 360, 840, 1440, 2040 s) inside the window they
are counted over. The two tests that claimed to assert the ceiling were
satisfied by the backoff alone; the new one counts the restarts in the first
hour and reads the ceiling's own line out of the log.

### CR-250d (comp-app-4) - the clock-skew tolerance was missing from the policy it was written for - FIXED (app.py)

comp-app-7 widened `_load_record`'s filter to tolerate an event stamped in
the future, with the comment "and the ceiling above reads these events". The
ceiling and the backoff still filtered `0 <= now - t`, so a clock that steps
BACKWARDS (an NTP correction, a VM resume, a dual-boot RTC: the three cases
the comment names) emptied `recent` for the length of the step and the dead
thread was restarted every 60 s tick with no backoff and no ceiling - exactly
what the persisted record exists to prevent. `_restart_held_off` now uses the
same `-_WATCHDOG_CLOCK_SKEW_SECONDS` bound, and clamps `since` at 0 so an
event in the future reads as "just now" rather than as older than the wait.

### CR-250e (comp-app-6) - "Sync now" ran a lane this machine has disabled - FIXED (app.py)

comp-app-1 unified the refusals behind `_lanes_refusal()` and left the
ACCEPTED path iterating `self.lanes` unfiltered. `_start_lanes` has always
skipped lane B where `lane_b_enabled=false` (a machine that reads the proxies
straight off the share) and writes "disabled: direct NAS access" on its
status line, and `rclone_lane.run_once` has no enable check of its own - its
early returns are the root, the stop event (never set on a lane that was
never started), the breaker and the disk floor - so the click ran a full
proxy pull DOWN onto that machine and named lane B in the toast over the
status line that says it is off. `_runnable_lanes()` is the one predicate
now, used by `sync_now`, by the `lanes` list in the verdict and by
`_start_lanes` itself, so a fourth caller cannot miss it.

### CR-250f (regression-5) - the relink twin comp-sync-11's own comment names - FIXED (app.py)

CR-234 routed `file_moves.relink_moved` through the public `cmp_key` (NFC
plus case fold) and its comment says "anything outside this module that
compares two paths must come through here". `CompanionApp._relink_moved` went
on comparing with a bare `os.path.normcase(os.path.normpath(...))` and taking
the folder tail with `os.path.relpath` on the raw strings - and the FILE MOVE
feature (the apply path, the pending-relink sweep and the RELINK IT dialog)
all go through that twin, while the fixed one has a single caller on the
project-rename path. A Mac answers NFD and the ledger's old path is the
dashboard's NFC, so a clip whose name carries a diacritic matched nothing,
`matched` stayed False, the ledger kept `relink_pending` for the whole 30 day
window and RELINK IT answered "Nothing in this project pointed at the old
location" about a clip sitting offline in front of the editor. The private
copy of the walk is gone: `_relink_moved` delegates to
`file_moves.relink_moved`, which is where the folded comparison and the
component-count tail live.

### CR-250g (comp-app-5) - the hold-off wrote a WARNING every tick - FIXED (app.py)

comp-app-7 removed the per-tick JSON write and left the per-tick log line, at
a different level: a thread down for a day produced about 1,350 WARNING lines
plus the ERRORs, and the 5 MB rotating log still lost the day's other
evidence. The refusal is written once per CHANGE of answer (a new wait, or
the transition into the ceiling) and at DEBUG in between, so the editor's log
still says the thread is down and says it about six times an hour instead of
sixty.

### CR-250h (comp-app-7) - the consolidate toast hid the count in the common case - FIXED (app.py)

`f"Copy & upload finished ({copied} copied in{skipped_part})." if skipped
else "Copy & upload finished."` - the conditional governs the whole f-string,
so the number appeared only where the editor had skipped something. A clean
40 clip consolidate said "Copy & upload finished." with nothing to compare
against the 40 they expected, while the rehearsal, the cancelled and the
failure branches all print one. comp-resolve-2 corrected the arithmetic in an
expression most editors never saw. The count is unconditional now.

### CR-250i (comp-app-8) - a corrupt machine.json was permanent, silent and unrepairable - FIXED (machine.py, app.py)

comp-app-5 was right to stop minting a SECOND id over a file that exists but
cannot be read - the dashboard reads a new id as another computer and the old
one is gone for good - and gave the condition no exit. `machine_id()`
answered "" for ever, `reporter.py` cached that for the life of the process
by design, nothing wrote a notice, nothing reached the report, and the
machine kept its hostname key, so a power loss that truncated
`~/.ccsync/machine.json` cost the rename affordance invisibly until somebody
renamed that computer. `machine.machine_id_unreadable()` is the accessor,
`machine.remint()` the deliberate repair (it sets the unreadable bytes aside
as `machine.json.unreadable-<epoch>` rather than destroying them, and refuses
to touch a file it CAN read), and the companion says it once per process in
the log and in one tray line that does not ask the editor to do anything
risky. The tray/Settings button that calls `remint()` is OWED to comp-ui.

### CR-250j (regression-19) - four editor-visible "(s)" plurals still shipped from app.py - FIXED (app.py)

comp-ui-4's blanket "no new `(s)` in a visible string" loop names tray.py and
settings_window.py only, and app.py was still checked against a nine-phrase
retired list, so "Re-addressed 3 clip(s)", "Rehearsal finished: 5 file(s)
were checked", "(2 folder(s) are set to be left alone)", "and 3 other
clip(s)" and both LUT sentences went on reaching editors while the test that
asserts UX-10's plurals were retired passed. All six now go through
`ui_copy.count`. The remaining `(s)` in app.py are log lines, report `detail`
strings and the diagnostics block an admin pastes into a ticket: a different
audience, and the file-wide loop belongs with whoever converts those.

### CR-250k (regression-20) - the second trash-summary producer handed out the DEFAULT retention - FIXED (app.py)

comp-sync-15 passed `path` and `max_age_days` to the lane's producer and left
`app.trash_summary()`, which is in the pinned app contract, calling
`lane_guard.trash_summary(root)` with one argument and hardcoding
`DEFAULT_TRASH_MAX_AGE_DAYS` in its fallback branch. A site with
`trash_max_age_days = 3` would have had its next recovery-folder surface say
"copies are kept 14 days" about a folder pruned at 3, which is the
wrong-deadline defect SYNC-112 and comp-sync-15 both exist to stop, delivered
by the next caller. Both paths read the configured value now, through one
`_configured_trash_max_age_days()` that cannot raise.

### CR-250l (res-companion-5) - the answer queue was rebuilt from two threads with no lock - FIXED (app.py)

`_queue_file_move_answer` is a read-filter-assign followed by an append,
called from the report-reply path and from the watcher thread, while the
reporter swaps the list out. A swap landing between the filter-assign and the
append either dropped the answer being queued or assigned answers that had
just been reported back into the list, re-publishing a verdict the dashboard
had already acted on; comp-sync-20 made it hotter by queueing an answer on
every report while the drive is out. Both accesses are under one lock now.
The lock and comp-app-2's record are built on demand by module-level helpers
because `_apply_file_moves` and `_queue_file_move_answer` are called UNBOUND
on an object that never ran `CompanionApp.__init__` (the file-move suite's
stub is how the redelivery path is tested at all), and a new constructor
attribute would otherwise be an AttributeError swallowed by that function's
never-raise handler - silently no file moves applied on every machine.

### CR-250m (comp-broll-music-2, owed here) - CLEAR FINISHED STAGING said there was nothing to clear about bytes the editor can see - FIXED (app.py)

`prune_staging` now deliberately keeps a drop that was staged and never run:
it has no `ended_at`, so it is not FINISHED, and its retention clock is the
later of when it was staged and when a byte last landed in it. The button the
space refusal names answered "There is no finished staging to clear on this
computer" about exactly those bytes, which is the sentence that makes an
editor press it a second time. When nothing was removed and `held_unrun` is
not zero, the answer now says what that staging is - drops that were never
indexed - and that it clears itself once it is past the retention window, or
as soon as the drop is run.

### CR-250n (comp-resolve-b-2, owed here) - the relink limiter's hold-off line repeated every 900 s - FIXED (app.py)

`_handle_non_canonical`'s "holding N clip(s)" INFO line was written on every
refusal, and RES-19's watcher re-offers the same clips every 900 s for the
life of the process, so it repeated all afternoon about a queue that had not
changed. Once per `AUTOMATIC_MIN_INTERVAL_SECONDS` window now (and through
`ui_copy.count`, which is where the last of regression-19's plurals was).

### CR-250o (comp-sync-b-2, owed here) - a pending relink whose file is not on disk - FIXED (app.py)

The `applying` intent row is written before the rename and carries
`relink_pending`, so a companion killed in between leaves a ledger row that
reads like a completed move. `_relink_pending_moves` (watcher thread) and the
RELINK IT dialog would both repoint this project's clips at a path that does
not exist, which is worse than the offline clip they are fixing: the fixer's
answer to an in-tree missing clip is to copy it back to the path the admin
just cleared. `_moved_destination_is_there` asks the disk before either one
runs; a path that cannot be tested at all (a permission error, a drive that
is out) is never a refusal, because never relinking would be its own
permanent fault. The dialog says so to the editor instead of opening on a
move that has not landed. comp-sync fixed the ledger half in file_moves.py;
this is the defence in depth they asked for.

### Verification

All in `companion/tests/test_bug_hunt_2026_09_11b_comp_app.py` unless noted;
each fails at f1eeb42 (18 of the 20 do; the two named as controls pass before
and after on purpose) and passes now.

- `test_a_move_interrupted_after_the_rename_is_finished_on_redelivery` -> fails at f1eeb42, passes now (res-companion-1)
- `test_a_move_interrupted_before_the_rename_is_applied_on_redelivery` -> fails at f1eeb42, passes now (res-companion-1)
- `test_a_move_being_applied_when_the_drive_goes_out_is_not_retired` -> fails at f1eeb42, passes now (res-companion-1)
- `test_the_drive_is_out_answer_is_not_repeated_on_every_report` -> fails at f1eeb42, passes now (comp-app-2)
- `test_a_long_outage_still_re_answers_so_a_lost_report_is_not_final` -> fails at f1eeb42, passes now (comp-app-2)
- `test_the_drive_coming_back_ends_the_outage` -> CONTROL: green before and after (comp-app-2)
- `test_the_hourly_ceiling_is_reachable_within_the_hour` -> fails at f1eeb42 (5 restarts, no ceiling line), passes now (comp-app-3)
- `test_a_clock_that_steps_backwards_does_not_restart_on_every_tick` -> fails at f1eeb42, passes now (comp-app-4)
- `test_the_hold_off_does_not_write_a_warning_every_tick` -> fails at f1eeb42 (55 lines in an hour), passes now (comp-app-5)
- `test_sync_now_does_not_run_a_lane_this_machine_has_disabled` -> fails at f1eeb42, passes now (comp-app-6)
- `test_sync_now_still_runs_lane_b_where_it_is_enabled` -> CONTROL: green before and after (comp-app-6)
- `test_the_apps_relink_matches_a_mac_spelling_of_the_same_name` -> fails at f1eeb42, passes now (regression-5)
- `test_the_consolidate_success_toast_says_how_many_were_copied` -> fails at f1eeb42, passes now (comp-app-7)
- `test_an_unreadable_machine_file_is_reported_and_repairable` -> fails at f1eeb42, passes now (comp-app-8)
- `test_a_healthy_machine_file_is_never_reminted` -> fails at f1eeb42, passes now (comp-app-8)
- `test_the_editor_is_told_when_this_computer_cannot_read_its_id` -> fails at f1eeb42, passes now (comp-app-8)
- `test_app_py_writes_real_plurals` -> fails at f1eeb42, passes now (regression-19)
- `test_the_trash_summary_uses_the_sites_own_retention` -> fails at f1eeb42, passes now (regression-20)
- `test_the_trash_summary_fallback_uses_it_too` -> fails at f1eeb42, passes now (regression-20)
- `test_an_answer_already_reported_is_not_resurrected` -> fails at f1eeb42, passes now (res-companion-5)
- `test_clear_finished_staging_explains_a_drop_that_was_never_run` -> fails at f1eeb42, passes now (comp-broll-music-2, owed here)
- `test_clear_finished_staging_still_says_so_when_there_is_nothing` -> CONTROL: green before and after
- `test_the_rate_limiters_hold_off_is_logged_once_per_cooldown` -> fails at f1eeb42 (five lines), passes now (comp-resolve-b-2, owed here)
- `test_a_pending_relink_whose_file_is_not_there_is_not_offered` -> fails at f1eeb42, passes now (comp-sync-b-2, owed here)
- `test_the_relink_it_dialog_refuses_a_destination_that_is_not_there` -> fails at f1eeb42, passes now (comp-sync-b-2, owed here)

Also run (unchanged, still green): `tests/test_bug_hunt_2026_09_11_comp_app.py`,
`tests/test_file_moves.py`, `tests/test_sweep_2026_09_04_copy.py`,
`tests/test_app_contract.py`, `tests/test_app.py`, `tests/test_machine.py` -
850 passed with the 25 above. `py_compile` on both source files.

Three findings were folded in from other territories mid-pass (the
orchestrator's OWED routing): comp-broll-music-2's sentence, comp-resolve-b-2's
log throttle and comp-sync-b-2's on-disk check. All three are companion-only
and need no deploy ordering.

### OWED TO ANOTHER TERRITORY

- dash-db: `dashboard/src/ccsync_dashboard/db.py`: `expire_delivered_file_moves`: exclude rows whose `state` is `retrying` from the 7 day expiry (comp-app-1, already assigned to dash-db). With CR-250b the companion now re-answers every 30 minutes rather than every report, which is still far inside the window - but the expiry must read `state`, or an editor away for a fortnight still loses the move. Dashboard deploys first; the companion half is safe alone.
- dash-api: `dashboard/src/ccsync_dashboard/api.py` (~8994, the file-move result logging): log the `retrying` answer only when `state` or `detail` CHANGED for that move (the row already holds the previous detail), instead of on every `rowcount > 0`. comp-app-2's companion half cuts the volume by about sixty; a machine on 0.9.65..0.9.71 still answers on every report, so the dashboard's own de-dupe is what makes the log quiet for the fleet as it is today. Either side may deploy first.
- comp-ui: `settings_window.py` (and/or the tray menu): an item that calls `machine.remint()` when `machine.machine_id_unreadable()` is True, so the editor whose tray line CR-250i adds has a button to repair the file with. The companion half (the accessor, the repair function and the advisory) is in; the button is additive and needs no deploy ordering.
- comp-sync: `file_moves.py`: `record_intent` writes `relink_pending=True` before the file has moved (comp-sync-b-2, already assigned there). CR-250a makes the resume run, which makes that row shorter-lived, but it does not close the window where `_relink_pending_moves` can repoint a clip at a path that does not exist yet.
- comp-sync: `file_moves.relink_moved` returns the detail string `"N Resolve clip(s) relinked"`, which reaches the editor through the RELINK IT dialog now that app.py delegates to it. It is one `ui_copy.count` call in that module.

### Owner decisions

- dash-api's `state="applying"` tolerance is noted and NOT used: `_apply_file_moves` answers `retrying` for an `applying` ledger row it cannot resolve this pass, so a dashboard below 0.7.44 does not 422 on it.
- comp-app-2 is answered at most once per 30 minutes per move while the drive is out, not once per outage: once per outage is quieter still, but a single lost report would then cost the move. The interval is `CompanionApp.FILE_MOVE_DRIVE_ANSWER_SECONDS`.
- comp-app-3 was fixed by capping the backoff at 10 minutes rather than by counting the ceiling over 24 hours. The alternative would refuse a seventh restart of a thread that had recovered six times in a day, which is a different and worse policy; this way the ceiling means what its constant says.
- regression-19 converted the six toast/dialog plurals the finding names and did NOT add app.py to the blanket file-wide `(s)` loop in `test_sweep_2026_09_04_copy.py`: the remaining hits are log lines, wire `detail` strings and the diagnostics block, and that file is shared with comp-ui this pass.
- comp-app-8's tray line tells the editor to send their log to their admin and says CCSync will not overwrite the file on its own. It does not offer to re-mint from the toast: the id in the unreadable file may still be recoverable, and a one-click id change is not a decision to take from a notification.
