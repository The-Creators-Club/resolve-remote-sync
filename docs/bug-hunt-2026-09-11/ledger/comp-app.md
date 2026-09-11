## The companion app core, 2026-09-11 (CR-233)

### CR-233 - "Sync now" answered "Sync requested" on a machine whose lanes it had refused to start, and six more in the app core - FIXED 2026-09-11 (companion, `app.py` / `machine.py` / `eula.py` / `ui_copy.py`)

**comp-app-1 - the most-clicked item in the menu lied to exactly the people
it must not.** `_start_lanes()` refuses on six conditions, in order: the
tray's own pause, a fleet or local halt, a config problem that stops syncing,
the licence gate, an absent sync drive, `sync_enabled=false`. APP-6's
`sync_now_result()` reproduced the LAST of them plus an empty-tick check and
answered `{"accepted": True, "lanes": [...]}` for the other five - so a
halted fleet, or an editor parked behind a new EULA version (the CR-27
population), clicked "Sync now" and was told in writing "Sync requested:
lane_a_video_up, lane_b_proxy_down, lane_c_syncthing". `sync_now()` then
called `trigger_pass_now()` on a sequencer `_start_lanes` had deliberately
never started, and the sentence that would have told them what to do
(`_halt_detail()`, `eula_problem()`) was two methods away. There is one
predicate now, `_lanes_refusal()`, returning `(gate, the sentence)` in
`_start_lanes`'s own order; `_start_lanes` dispatches on the gate id and
keeps every side effect it had (the lane detail it writes, the line it logs),
and `sync_now_result` reads the same answer. A gate added to one door cannot
be missed by the other.

**comp-app-2 - nine `resolve_health` fields the dashboard drops.** Wave 3 put
`connected`, `project_open`, `wedged_seconds`, `wedged_call`,
`missing_clips`, `non_canonical_refused`, `proxy_attach`, `proxy_gaps` and
`stills` on every report; `ResolveHealthIn` declares seven other keys and
inherits `extra="ignore"`, so all nine are discarded with no log line and no
ignored-sections banner - the third recurrence of SYS-3. The receiving half
is the dash-api-jobs builder's (recorded as OWED below). The companion half
is what is fixed here: the payload is now pinned by a test as the documented
contract, and its two unbounded lists are capped (below), so the dashboard
can declare against a shape that cannot quietly grow.

**comp-app-3 - the licence refusal sent a parked editor to the wrong part of
the window.** All three sentences said "Press [ READ AND ACCEPT THE LICENCE ]
in Settings, THIS COMPUTER"; the button is appended to `lane_items`, i.e. the
SYNCING section, and THIS COMPUTER has no licence button at all. Because the
route was spelled by hand in `eula.py` rather than in `ui_copy`, neither copy
scan could see it - the exact failure `ui_copy`'s docstring says the module
exists to prevent. `ui_copy.ACCEPT_LICENCE_SETTINGS` ("Tray > Settings > READ
AND ACCEPT THE LICENCE") carries its `ROUTE_ROWS` row now, so the next time
that button moves the test fails, and `eula.acceptance_problem` interpolates
it.

**comp-app-4 - `non_canonical_refused` grew without bound and rode every
report.** `watcher._non_canonical_refused` is a dict that only a SUCCESSFUL
relink ever removes from, and neither the watcher's getter nor
`app._watcher_list` sliced it - unlike its sibling `missing_clips` (capped at
50 at the source) and unlike every other reported list (`repath_events[:10]`,
`moved_project_dirs[:20]`). A project in the 2026-08-12 "Energy Transition"
shape on a machine where Resolve refuses the relinks put its whole media pool
on the wire every 30 s, for a key the dashboard drops. `_watcher_list` caps
every list it returns at `MAX_REPORTED_LIST` (50, the same number for the
same reason). The cap at the source is owed to the watcher's owner.

**comp-app-5 - an unreadable `machine.json` minted a NEW id and wrote it over
the old one.** `read()` answered `None` for every exception, and `machine_id`
reads `None` as "no id yet", so a truncated write, a BOM-mangled restore, a
0-byte file after a power loss or an antivirus holding the handle produced a
second id - which the dashboard's `machines` registry reads as another
computer, losing the rename affordance the id exists for, permanently and
silently. The module's own rule is "never a value that was not persisted";
the code could not tell absent from unreadable. `read_record()` returns
`(record, readable)` now: absent still mints, unreadable reports no id for
that run and leaves the bytes alone for a support session to look at. A
machine with NO id syncs fine; a machine with a NEW one is a different
computer.

**comp-app-6 - the loopback rebind re-ran the whole server start every 120 s
and logged a six-line WARNING each time.** `retry_loopback_bind`'s docstring
claimed "one bind attempt a minute"; an attempt re-reads the config,
re-resolves the media/music/ytdl mounts (which probe `/Volumes` on macOS) and
takes `broll_server.start`'s un-latched `except OSError` arm, which names the
retired standalone BRoll Companion in six lines. On a machine where 8899 is
genuinely held that is ~720 copies of the same paragraph a day through a 5 MB
rotating log - and that log is what "COPY DIAGNOSTICS FOR YOUR ADMIN" sends.
The retry now backs off: the wait doubles from the caller's own tick up to 30
minutes while the bind error is unchanged, and resets the moment the error
changes or the port becomes ours. The state field CMEDIA-3 added
(`loopback.error`/`since`) is the diagnostic; the repeated log never was.

**comp-app-7 - `LaneWatchdog` restarted a thread with no ceiling and no
backoff.** `check()` consulted only `_must_not_restart()`; `_events` was
written for `sync_guard.restarts` and read back by nobody, so a thread whose
`restart()` raises, or whose loop dies again immediately, was restarted every
60 s for ever, with one JSON write per tick, and the only sign was a counter
climbing on a report field. The ledger is a policy input now
(`_restart_held_off`): an exponential wait between attempts on one thread
(120 s, 240 s, ... capped at 30 minutes) and a ceiling of six restarts in an
hour, after which the watchdog says so and stands down until they age out -
refused, not disabled, because the thread is still down and still wanted.
`_load_record`'s `0 < now - t` also erased every event stamped in what is now
the future, so one NTP correction wiped the crash-loop evidence the file is
persisted to survive, and that evidence is what the ceiling reads; the skew
is tolerated symmetrically (one hour).

**comp-resolve-2, the half owed to this territory.** The consolidate toast
counted `ok` as "copied in", and since RES-15 the fixer's rehearsal arm
answers `{"ok": True, "dry_run": True}` - it did what it was asked, which was
nothing. A rehearsal therefore reported "Copy & upload finished" and ran a
lane A push behind it. The toast reads `consolidate.count_copied()` now, a
rehearsal gets its own sentence ("Rehearsal finished: N file(s) were checked
and nothing was copied in or uploaded"), and the upload phase is skipped when
a run that had ops copied nothing. A consolidate with no ops at all (files
already in the tree, waiting to go up) still uploads, which is why the
condition is "results and nothing copied" rather than "nothing copied".

**comp-ui-1, the other half owed to this territory.** `run()` logged "tray
icon started" the moment `start_tray` returned, whatever had happened inside
it. On Windows a failed `Shell_NotifyIconW` registration is caught by
`_WindowsIcon.run`, which logs once and RETURNS - leaving a companion with no
icon, no pump to receive `TaskbarCreated`, and every later toast (the lane B
breaker, a fleet halt, free space, the drive pulled mid-transfer) discarded
in silence by `notify()`'s `if not self._added: return`. The two states read
identically in the log the support workflow collects. `_log_tray_state()`
asks the backend's new `registered` property and says which one it is, at
WARNING when the icon is not there; a backend that does not answer (macOS, a
double, an older build) is reported exactly as before, because absent
evidence is not a fault.

**The comp-sync hand-offs, app.py's half.** Six producers and guards whose
other end lives in this file. **comp-sync-4**: neither `shared_folder_problems()`
nor `repath_events()` had a caller anywhere, so a shared library that is not
linked on this machine and a project folder this machine MOVED because an
admin renamed it on the server were computed every pass and reached nobody.
Both ride `sync_guard` now, absent when there is nothing to say. **comp-sync-9**:
the wedged balloon and its episode sat inside `if not self._root_absent_announced:`,
so `absent -> not_answering` - an SMB mapping that drops and comes back as a
stale session, the common Windows shape - opened no episode at all: one calm
"is disconnected" line about a drive that is plugged in and wedged, then
silence. The per-state announcement is gated on the STATE having changed now;
the `unfinished` judgement stays exactly once per outage, which is CR-92's
whole point, and the current state is passed to `resume_remembered(state)` so
a wedge remembered from the previous run is not replayed at a drive in the
editor's bag (comp-sync-8). **comp-sync-21**: the grade-swap rollback sentence
hardcoded " P: was restored to your local copy." three lines below the
`letter` it had just unmapped and remapped with. **comp-sync-20**: a move
delivered while the sync drive is out cannot be applied and must not be
guessed at, but silence cost it the move - the dashboard expires a command
after 7 days of "told and never answered". It answers `state="retrying"` with
"waiting for the sync drive" (the shape v36 already carries), `attempts` left
at 0 because waiting for a drive is not an attempt and must not spend the
budget a real failure needs; nothing is decided and nothing is recorded.
**res-companion-1**: `_apply_file_moves` passes `ledger=self.file_moves` into
`apply_move`, which is what activates the crash-window fix (the intent row
written before the first filesystem call); `docs/FILE_MOVES.md` grows a
section 7 for the `applying` state and for the answer above.
**comp-sync-13**: the `waiting` de-dupe was inside `if user_initiated:` and
the comment claimed both producers latch once per process - RES-19's 15
minute cooldown made that untrue, so a project whose relinks Resolve refuses
queued the same clip again every quarter of an hour for the life of the
process and the rate limiter's "holding N clip(s)" counted each copy. The
de-dupe is unconditional now, the queue has a 1,000-clip ceiling that drops
the OLDEST offers (a full queue nothing new can enter is worse), and the
comment is gone.

### Verification
- `companion/tests/test_bug_hunt_2026_09_11_comp_app.py::test_sync_now_refuses_while_syncing_is_paused_from_the_tray` -> fails at 40f931a, passes now (comp-app-1)
- `companion/tests/test_bug_hunt_2026_09_11_comp_app.py::test_sync_now_refuses_and_says_so_while_the_fleet_is_halted` -> fails at 40f931a, passes now (comp-app-1)
- `companion/tests/test_bug_hunt_2026_09_11_comp_app.py::test_sync_now_refuses_on_a_config_problem_that_stops_syncing` -> fails at 40f931a, passes now (comp-app-1)
- `companion/tests/test_bug_hunt_2026_09_11_comp_app.py::test_sync_now_refuses_behind_the_licence_gate` -> fails at 40f931a, passes now (comp-app-1)
- `companion/tests/test_bug_hunt_2026_09_11_comp_app.py::test_sync_now_refuses_while_the_sync_drive_is_disconnected` -> fails at 40f931a, passes now (comp-app-1)
- `companion/tests/test_bug_hunt_2026_09_11_comp_app.py::test_sync_now_does_not_trigger_a_pass_on_a_halted_machine` -> fails at 40f931a, passes now (comp-app-1)
- `companion/tests/test_bug_hunt_2026_09_11_comp_app.py::test_every_gate_start_lanes_refuses_on_is_one_sync_now_can_name` -> fails at 40f931a, passes now (comp-app-1)
- `companion/tests/test_bug_hunt_2026_09_11_comp_app.py::test_resolve_health_sends_the_documented_keys_and_nothing_else` -> the wire contract comp-app-2's dashboard half declares against (passes at 40f931a by design: it pins the shape, the cap below is the behaviour)
- `companion/tests/test_bug_hunt_2026_09_11_comp_app.py::test_non_canonical_refused_is_capped_on_the_wire` -> fails at 40f931a, passes now (comp-app-4)
- `companion/tests/test_bug_hunt_2026_09_11_comp_app.py::test_the_licence_refusal_points_at_the_section_the_button_is_in` -> fails at 40f931a, passes now (comp-app-3)
- `companion/tests/test_bug_hunt_2026_09_11_comp_app.py::test_every_licence_refusal_uses_the_one_route` -> fails at 40f931a, passes now (comp-app-3)
- `companion/tests/test_bug_hunt_2026_09_11_comp_app.py::test_a_corrupt_machine_file_is_not_re_minted` -> fails at 40f931a, passes now (comp-app-5; three payloads)
- `companion/tests/test_bug_hunt_2026_09_11_comp_app.py::test_read_record_tells_absent_from_unreadable` -> fails at 40f931a, passes now (comp-app-5)
- `companion/tests/test_machine.py::test_a_corrupt_file_is_not_fatal_and_is_not_replaced` -> rewritten: it pinned the OLD behaviour (re-mint over the corrupt file), which comp-app-5 reverses
- `companion/tests/test_bug_hunt_2026_09_11_comp_app.py::test_the_loopback_retry_backs_off_while_the_port_stays_held` -> fails at 40f931a, passes now (comp-app-6)
- `companion/tests/test_bug_hunt_2026_09_11_comp_app.py::test_the_loopback_retry_clears_its_backoff_once_the_port_is_ours` -> fails at 40f931a, passes now (comp-app-6)
- `companion/tests/test_app.py::test_the_bind_is_retried_until_it_succeeds` -> kept, with the backoff's wait cleared between attempts; what it pins (retried until it is ours, never after) is unchanged
- `companion/tests/test_bug_hunt_2026_09_11_comp_app.py::test_a_thread_that_dies_again_is_not_restarted_every_tick` -> fails at 40f931a, passes now (comp-app-7)
- `companion/tests/test_bug_hunt_2026_09_11_comp_app.py::test_the_watchdog_stops_trying_after_the_hourly_ceiling` -> fails at 40f931a, passes now (comp-app-7)
- `companion/tests/test_bug_hunt_2026_09_11_comp_app.py::test_the_ceiling_lifts_once_the_hour_has_passed` -> passes now (comp-app-7, the "refused, not disabled" half)
- `companion/tests/test_bug_hunt_2026_09_11_comp_app.py::test_a_clock_that_steps_backwards_does_not_erase_the_evidence` -> fails at 40f931a, passes now (comp-app-7)
- `companion/tests/test_bug_hunt_2026_09_11_comp_app.py::test_a_rehearsed_consolidate_is_not_reported_as_copied` -> fails at 40f931a, passes now (comp-resolve-2, app.py's half)
- `companion/tests/test_bug_hunt_2026_09_11_comp_app.py::test_a_real_consolidate_still_copies_uploads_and_says_so` -> the control: a real copy still uploads and still says "Copy & upload finished"
- `companion/tests/test_bug_hunt_2026_09_11_comp_app.py::test_the_startup_line_says_whether_the_icon_is_actually_there` -> fails at 40f931a, passes now (comp-ui-1, app.py's half)
- `companion/tests/test_bug_hunt_2026_09_11_comp_app.py::test_a_backend_that_cannot_answer_is_not_reported_as_a_failure` -> fails at 40f931a, passes now (comp-ui-1, the fail-open half)
- `companion/tests/test_bug_hunt_2026_09_11_comp_app.py::test_the_report_carries_the_two_readers_nothing_called` -> fails at 40f931a, passes now (comp-sync-4)
- `companion/tests/test_bug_hunt_2026_09_11_comp_app.py::test_a_quiet_machine_sends_neither_section` -> the control: absent is how "nothing to say" is spelled
- `companion/tests/test_bug_hunt_2026_09_11_comp_app.py::test_a_drive_that_wedges_after_it_vanished_opens_an_episode` -> fails at 40f931a, passes now (comp-sync-9)
- `companion/tests/test_bug_hunt_2026_09_11_comp_app.py::test_the_unfinished_judgement_is_made_once_per_outage` -> the control for CR-92: passes at 40f931a and still passes (the restructure's own risk)
- `companion/tests/test_bug_hunt_2026_09_11_comp_app.py::test_the_current_state_is_passed_to_resume_remembered` -> fails at 40f931a, passes now (comp-sync-8/9)
- `companion/tests/test_bug_hunt_2026_09_11_comp_app.py::test_the_restored_drive_sentence_uses_the_sites_own_letter` -> fails at 40f931a, passes now (comp-sync-21)
- `companion/tests/test_bug_hunt_2026_09_11_comp_app.py::test_a_move_delivered_while_the_drive_is_out_answers_retrying` -> fails at 40f931a, passes now (comp-sync-20)
- `companion/tests/test_file_moves.py::test_a_missing_drive_answers_retrying_and_decides_nothing` -> rewritten from `test_a_missing_drive_defers_rather_than_answers`, which pinned the silence comp-sync-20 removes; the half that matters (nothing decided, nothing recorded, the file untouched) is unchanged
- `companion/tests/test_bug_hunt_2026_09_11_comp_app.py::test_the_move_is_applied_through_the_ledger` -> fails at 40f931a, passes now (res-companion-1)
- `companion/tests/test_bug_hunt_2026_09_11_comp_app.py::test_the_watchers_repeat_offers_are_de_duped_too` -> fails at 40f931a, passes now (comp-sync-13)
- `companion/tests/test_bug_hunt_2026_09_11_comp_app.py::test_the_relink_queue_has_a_ceiling` -> fails at 40f931a, passes now (comp-sync-13)

Run: `cd companion; .venv\Scripts\python.exe -m pytest tests/test_bug_hunt_2026_09_11_comp_app.py tests/test_app.py tests/test_lane_watchdog.py tests/test_machine.py tests/test_eula.py tests/test_sync_halt.py tests/test_app_contract.py tests/test_sweep_2026_09_04_copy.py tests/test_tray_copy_names_real_menu_items.py tests/test_no_em_dash.py tests/test_consolidate.py -q` -> 1103 passed (29 in the new file after the two hand-offs landed).
The "fails at 40f931a" column was measured by running this file against a copy
of the tree with `app.py`, `machine.py`, `eula.py` and `ui_copy.py` restored
from HEAD (19 failed, 6 passed), not by touching git state.

### OWED TO ANOTHER TERRITORY
- `companion/src/ccsync_companion/tray.py` (comp-ui), comp-sync-4: the tray half of the two new sections. The snapshot's `_get(...)` block needs `_get("shared_folder_problems", lambda: app.shared_folder_problems(), [])` and `_get("repath_events", lambda: app.repath_events(), [])`, and `_guard_fingerprint` needs both or the menu never redraws when one appears. The report half is done here, so the fleet grid and the log see them either way; what is missing without it is the line at the machine itself.
- `dashboard/src/ccsync_dashboard/api.py` (dash-api-jobs): the receiving half of comp-app-2. Either declare the nine wave-3 keys on `ResolveHealthIn` (with `max_length` on `missing_clips` / `non_canonical_refused` - the companion caps both at 50 now) or, more durably, flip `_BoundedSectionIn` to `extra="allow"` and teach `undeclared_report_sections` to walk sub-models, so the FOURTH recurrence of SYS-3 is a log line instead of silence. Anything meant to reach the grid also needs `db.store_resolve_health`'s column list and `flatten_sync_guard`. Nothing breaks without it: the companion has been sending these since 0.9.66 and they are simply dropped.
- `companion/src/ccsync_companion/watcher.py:202` (comp-resolve/comp-sync territory): cap `_non_canonical_refused` at the source, evicting oldest, so the dict itself cannot reach the size of a media pool. The report is bounded without it (comp-app-4), but the memory is not.
- `companion/src/ccsync_companion/broll_server.py:2219` (comp-media territory): latch the six-line `except OSError` WARNING to the first failure per distinct `_LAST_BIND_ERROR` and DEBUG thereafter. The backoff cuts the volume by roughly an order of magnitude; the latch is the real fix.
- `companion/src/ccsync_companion/identity.py:296`: the one-time plaintext warning still says "your TrueNAS username and password" where `site.server_phrase()` exists. Log line only, so not user-visible copy, and left alone rather than half-done.

### Owner decisions
- The licence refusal now reads "... Open Tray > Settings > READ AND ACCEPT THE LICENCE." Inside the Settings window itself that advisory renders directly above the button it names, which is mildly redundant; the alternative (having `settings_window._licence_advisory` strip the route sentence the way it already strips the old "setup wizard" one) is in another territory and was not taken. Say the word and it is two lines there.
- The watchdog's ceiling is SIX restarts of one thread in an hour, and it lifts as those age out. The tray advisory has said "three restarts in an hour needs a human" since SYS-2, so a lower ceiling (three) is defensible; six was chosen so the ceiling can never fire before the advisory the editor sees.
- comp-resolve-2's upload skip is conditioned on "there were ops and none of them copied" rather than the literal "count_copied() == 0" the hand-off asked for: a consolidate whose ops list is empty but whose NAS check found files already in the tree waiting to go up must still upload, and that run has `count_copied() == 0` too.

### Note for the orchestrator (not mine to fix)
`companion/tests/test_settings_window.py::test_the_skipped_clip_line_appears_in_sync_lanes` fails in the working tree: it pins "14 clip(s) skipped this session" and comp-ui-4's change to `tray._ignored_line` now renders `ui_copy.count(14, "clip")` = "14 clips". It passes with HEAD's `tray.py` and is unaffected by anything in this territory.
