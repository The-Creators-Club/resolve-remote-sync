## The sync engine, the file moves and the drive reminder, 2026-09-11 (CR-234)

Bug hunt 2026-09-11, comp-sync territory: `companion/src/ccsync_companion/sync/*`,
`file_moves.py`, `selection.py`, `watcher.py`, `drive_reminder.py`. Twenty-two
findings from `docs/bug-hunt-2026-09-11/hunters/comp-sync.md` plus two from the
resilience hunter, every verdict in `verifiers/companion-sync.md` and
`verifiers/companion-a.md` read first. Four of them have a fix that lives in
`app.py` or `tray.py` and are recorded under OWED rather than half-done here.

### CR-234 - a safety latch whose write failed was in memory only, and nothing said so (comp-sync-1) - FIXED 2026-09-11 (companion, `sync/lane_guard.py`)

`_write_json` returned a bool and all three `_persist_locked` bodies dropped
it: a breaker trip, a disk-floor park or a halt whose write failed (a full or
read-only home volume, EACCES, an AV lock - the latches live in
`~/.ccsync`, not on the sync drive, so the hunter's ENOSPC scenario is not one
of them) survived only until the tray restart an editor tries first. That is
the one thing CLAUDE.md says a latch may never be. `_PersistedLatch` now keeps
the last payload, RETRIES it on the next `report()` (the report loop's and the
tray's own cadence, throttled to 60 s, no new thread), and reports
`persist_failed` / `persist_error` / `persist_failed_at` in that latch's
`sync_guard` block - absent on the happy path, so an older dashboard reading
the wire sees nothing new. The tmp file is process-unique
(`<name>.<pid>.tmp`, `root_guard.write_volume_record`'s spelling) so two
companions overlapping across a self-upgrade cannot replace each other's
half-written bytes into a live latch.

### CR-234 - `2 ** (attempts - 1)` overflowed, and both folder managers then did nothing for the life of the process (comp-sync-2) - FIXED 2026-09-11 (`sync/shared_folders.py`, `sync/syncthing_supervisor.py`)

Both backoffs computed `START * 2 ** (attempts - 1)` and only then clamped.
The constants are FLOATS, so at 1025 attempts the multiplication raised
`OverflowError: int too large to convert to float` - a folder retried twice an
hour reaches that in about 21 days of tray uptime, and the supervisor's counter
is PERSISTED, so a machine whose Syncthing cannot start reaches it in a week
across restarts. Inside `FolderProblems.note`, which is documented as never
raising and is called from `reconcile`'s try AND from its except arm, which
re-entered it. Both sites now clamp the EXPONENT (`min(attempts - 1, 20)`,
already past every cap), the supervisor bounds `_attempts` as it reads it off
disk, and both managers' except arms wrap the `note` call so a reconcile
documented as never raising keeps that promise even when its own bookkeeping
is what failed.

### CR-234 - the SYNC-101 folder problems never reached the editor they were written for (comp-sync-3, comp-sync-19) - FIXED 2026-09-11 (`sync/syncthing_lane.py`)

The one delivery path for "the LUT library has not been shared with this
computer yet" was a block at the very END of `check_once`, and every early
return above it skipped it - including the "no project folders to check yet"
branch, which is the exact state `shared_folders.py`'s own docstring names (an
editor with zero projects ticked, or all of them upload-only). The problems are
now folded into every status the poll builds, through one `_with_problems`
helper, and the sentence carries a count when there is more than one
("+2 more"): two libraries failing used to look exactly like one, so the editor
fixed the one named and the detail then named the second.

### CR-234 - a blocked repath's "not syncing" sentence could never be cleared, and its retries walked Resolve N+1 times a pass (comp-sync-5, comp-sync-6, comp-sync-17) - FIXED 2026-09-11 (`sync/repath.py`)

A blocked repath writes `moved=False` and the project row renders its sentence
until a `moved=True` event for the same slug replaces it. When the mismatch
stopped existing by any other route (the admin undoes the rename; the editor
unticks and re-ticks so the folder is accepted fresh at the right path) the
reconcile `continue`d and nothing ever cleared it: a project that was syncing
normally said "is not syncing because CC Sync could not move its folder" for
ever. The `actual == expected` path now clears it - and UNPAUSES the folder
first, because the blocked branch deliberately leaves it paused (AUDIT_2
DEL-5/L-8) and clearing the sentence alone would turn "says blocked, is
blocked" into "says fine, syncs nothing". Only a blocked project is unpaused:
the sequencer pauses all but the current one by design. `retry_pending_relinks`
is throttled to once per five minutes and de-duplicated by destination: it ran
at the head of every reconcile, which is once for the whole selection AND once
per project turn, each time walking the whole media pool once per pending event
(21 enumerations a pass on a six-project plan, holding `_API_LOCK`, for the
full 30 day window). Event ids are `uuid4().hex` rather than a millisecond
stamp, and `mark_relinked` checks slug and old path too: two events written in
the same millisecond could never both retire, and the twin stayed pending for
30 days.

### CR-234 - a lane B the rotation walked away from queued a new blocked thread every project turn (comp-sync-7) - FIXED 2026-09-11 (`sync/sequencer.py`, `sync/rclone_lane.py`)

When the bounded join expires and `abort_run` cannot kill the child (the case
SYNC-1 says it is the backstop for), the sequencer walks away while that thread
still holds `RcloneLane._run_lock`. Every later project turn started another
lane B thread, which blocked forever on that lock - one leaked daemon thread
per turn, unbounded - and when the wedge cleared they drained in order, each
running `rclone sync` against a subpath the repath may since have moved, which
is the hazard the join exists to prevent. The abandoned subpath is now LATCHED
on the sequencer: while it is set no lane B thread is started and the lane
carries a "stalled on <subpath>" detail rather than reading idle, and it is
cleared from the abandoned thread's own `finally`. The other half is in the
lane: `_run_once_locked` asks the sequencer whether its subpath is still the
current one and drops the pass if not (`subpath_still_current`, optional and
duck-typed, and "cannot tell" is always yes).

### CR-234 - a restored drive-reminder episode ignored what the drive was doing now, and a new episode could inherit the last one's mute (comp-sync-8, comp-sync-16) - FIXED 2026-09-11 (`drive_reminder.py`)

`_on_root_absent`'s `end_state_episode()` guard runs BEFORE the record is read,
so at startup it is a no-op, and `resume_remembered()` then re-opened the
persisted `not_answering` episode whatever the drive was actually doing. A
drive that wedged with nothing owed, was quit and then unplugged came back
ballooning "your drive is still not answering, reconnect it or restart this
computer" every 30 minutes about a drive in the editor's bag, and only plugging
it in ever ended it. `resume_remembered(state)` now keeps a STATE episode only
when the drive is in that state now; with no state given there is no basis for
the claim and the record is dropped, and the caller's own first announcement
re-opens the right episode a moment later. The unfinished-work branch is
untouched - work owed outlives every state change, which is the whole of CR-92.
Episode identity is a counter, not `time.time()`: Windows ticks at 15.6 ms, so
a new episode beginning in the same tick as the muted one ended inherited its
mute (Settings said reminders were off while `begin()`'s thread was still
ballooning), and `clear()` now drops the mute with the episode. That is the
intermittent `test_drive_reminder.py` failure at HEAD, and it was the code, not
the test.

### CR-234 - `not-offered` was three situations wearing one sentence (comp-sync-10) - FIXED 2026-09-11 (`sync/shared_folders.py`, `sync/borrowed_folders.py`)

`_accept` returned the same literal when the server genuinely has not offered
the folder, when the local Syncthing could not be asked, and - in the borrowed
manager - when a halt is deliberately holding the offer. SYNC-101 turns that
one string into "Ask your admin to approve it", so a restarting local Syncthing
sent the editor to chase their admin, and their own pause did too. A read
failure is now `ask-failed` with its own sentence ("CC Sync could not ask the
sync engine about it"), and a halt is `halted`, which is deliberately NOT in
`PROBLEM_OUTCOMES`: it records no problem at all, because there is nothing
wrong.

### CR-234 - a moved clip never relinked on a Mac, a case-only rename was recorded as done and never applied, and an accented proxy was orphaned (comp-sync-11, comp-sync-12, comp-sync-18) - FIXED 2026-09-11 (`file_moves.py`)

Three CR-90-class holes in one file, all in comparisons that did not go through
`_cmp_key` (now public as `cmp_key`). `relink_moved` compared media-pool paths
with a bare `normcase(normpath(...))`, which folds neither case nor Unicode on
darwin, while `old_local` is built from the dashboard's NFC `from_rel` and
Resolve answers NFD - so the walk matched nothing, `matched` stayed False, the
pending relink never retired and the toast's promise was never kept for any
accented name. The folder arm's `os.path.relpath` had the same premise and came
back full of `..`; the tail is taken by component count off the RAW path now,
so the spelling written into Resolve is still the one on the disk.
`apply_move` short-circuited a case-only rename as "already where the server
has it": the NAS (case-sensitive) DID rename it, nothing moved on the editor's
disk, and a day later - once the exclusion lapsed - lane A uploaded the old
spelling back beside the new one, which is the duplicate-at-the-cleared-path
failure `docs/FILE_MOVES.md` exists to prevent. It is now a two-step rename
through a temporary name (the only place the fold is bypassed; a spelling-only
rename of a FOLDER is refused with a sentence rather than guessed at).
`move_proxy_siblings` compared stems with a raw `.lower()`, so an NFD proxy
stayed behind under the old project for lane B to trash.

### CR-234 - a companion killed mid file-move applied it and reported it fully applied (res-companion-1) - FIXED 2026-09-11 (`file_moves.py`)

The ledger row was written only AFTER the filesystem move and the relink, and
the window between them is the proxy-sibling loop plus a media-pool walk -
seconds to tens of seconds, on a codebase where dying without a shutdown is
routine (CR-93). A process killed there left the file moved, no row, and a
redelivered command that took the "nothing at the old path on this machine"
arm: `paths` is None, so no relink, `relink_pending` False, and the dashboard
told the move applied. Both recovery routes were closed by the same missing
field, and the fixer's answer to an in-tree missing clip is to copy it back to
the path the admin cleared. `apply_move` now takes an optional `ledger` and
writes an INTENT row (`STATE_APPLYING`, with `old_local`/`new_local`
precomputed) before the first filesystem call; a redelivery resumes from it on
exactly the evidence the verdict names - our own applying row AND src gone AND
dest present - so a machine that never held the file still answers "nothing at
the old path". An applying row holds its lane A exclusion open like every other
unresolved one.

### CR-234 - a refused canonical relink re-queued itself every 3 s behind a 15 minute limiter (comp-sync-13) - PARTLY FIXED 2026-09-11 (`watcher.py`; the de-dupe in `app.py` is OWED)

RES-19 made the watcher re-offer a NON_CANONICAL path on every poll once a
relink fails, and `app._handle_non_canonical` de-dupes only on the
`user_initiated` branch - so on a machine with a wrong `canonical_prefix` and
158 non-canonical clips, every 3 s poll re-offered all of them and the
unprompted branch appended them again, ~300 times per 900 s window, while
`resolve_journal.allow_automatic` refused the burst that would have drained the
list. The watcher's half: a re-arm is now a COOLDOWN (900 s, the limiter's own
window - an offer it cannot act on is an entry on a list nobody drains), and
the re-arm book is bounded. RES-19's retry itself is unchanged; only its cadence
is.

### CR-234 - the plan's age froze at the first fetch of a process (comp-sync-14) - FIXED 2026-09-11 (`selection.py`)

`_write_cache` returns early when the response is byte-identical (AUDIT_2 P11's
write storm), so `selection.json`'s `fetched_at` never advanced after the first
successful fetch of a run. A companion up for 10 days with an unchanged plan,
restarted with the dashboard briefly down, told the editor "sync plan from 10
days ago: the dashboard has not answered since" about a plan that was live a
minute earlier. The live stamp is now its own tiny file
(`selection_fetched.json`, written at most once an hour, throttled on the
STORED stamp rather than on the response), `selection.json` stays byte-stable,
and `fetched_at()` answers with whichever of the two is newer.

### CR-234 - the recovery-folder line read two keys nothing produced (comp-sync-15) - FIXED 2026-09-11 (`sync/rclone_lane.py`)

`tray._trash_line` reads `trash["path"]` and `trash["max_age_days"]`; the
producer emitted neither, so every editor got the bare `.ccsync-trash` and the
hardcoded 14 day default even on a site configured for three - precisely the
defect SYNC-112 records as fixed. `_maybe_prune_trash` now puts the real path
and the configured `trash_max_age_days` into the summary. Additive on the wire.

### CR-234 - the structure clone ran for an upload-only project (comp-sync-22) - FIXED 2026-09-11 (`sync/sequencer.py`)

`docs/UPLOAD_ONLY_TICK.md` says upload-only is lane A alone. The clone is an
`rclone lsf --dirs-only -R` over SFTP plus a local mkdir loop, and it sat ahead
of the upload-only early return, so an editor who ticked a finished project
upload-only to get their originals onto the server had the NAS's whole bin
skeleton created inside their local folder, one SSH handshake per project per N
passes. Skipped for an upload-only project.

### CR-234 - a hard kill mid lane-B pass erased that pass's deletions from the breaker's account (res-companion-5) - FIXED 2026-09-11 (`sync/lane_guard.py`, `sync/rclone_lane.py`)

The cumulative deletion account was credited once per pass, from the parsed
result, after the child had exited. A power cut halfway through a pass emptying
a scope lost every deletion it had already made: the files are in
`.ccsync-trash`, but the counter that would have tripped the breaker on the
next pass never saw them, and the machine came back with a full fresh budget.
Deletions are now credited as they happen, from the `--stats` tick the lane
already parses (`note_deletes_in_flight`, persisted at most every 20 s so a
pass trashing thousands of files does not write per file), and `note_pass`
subtracts what the pass already credited so nothing is counted twice.

### Verification

Companion venv, `tests/test_bug_hunt_2026_09_11_comp_sync.py` unless said
otherwise. Each fails at 40f931a and passes now.

- comp-sync-1 -> `test_a_breaker_that_cannot_write_its_latch_says_so_and_retries`, `test_the_halt_reports_a_failed_persist_too`, `test_the_latch_tmp_file_is_process_unique`
- comp-sync-2 -> `test_the_folder_problem_backoff_does_not_overflow`, `test_the_supervisor_backoff_does_not_overflow`, `test_a_corrupt_attempt_count_is_clamped_on_load`, `test_a_reconcile_whose_note_raises_still_does_not_raise`
- comp-sync-3 -> `test_an_editor_with_no_ticked_projects_still_hears_about_the_lut_library`
- comp-sync-5 -> `test_a_blocked_repath_stops_saying_so_once_the_folder_is_where_it_belongs`, `test_a_rotation_pause_is_not_unpaused_by_the_clearing_path`
- comp-sync-6 -> `test_the_pending_relink_walk_is_throttled`
- comp-sync-7 -> `test_no_second_lane_b_is_started_while_one_is_abandoned`, `test_a_queued_pass_for_a_stale_subpath_is_dropped`
- comp-sync-8 -> `test_a_remembered_wedge_is_not_replayed_at_a_drive_that_is_simply_gone`, `test_a_remembered_wedge_is_kept_while_the_drive_is_still_wedged`
- comp-sync-10 -> `test_a_read_failure_is_not_ask_your_admin`, and `tests/test_borrowed_folders.py::test_halted_machine_leaves_the_offer_pending` (updated: the halt has its own outcome and records no problem)
- comp-sync-11 -> `test_a_moved_clip_relinks_even_when_resolve_spells_it_decomposed`, `test_a_moved_folder_relinks_its_decomposed_children`
- comp-sync-12 -> `test_a_case_only_rename_is_actually_applied`
- comp-sync-13 -> `test_a_refused_relink_is_not_re_offered_on_every_poll`, and `tests/test_watcher.py::test_a_refused_non_canonical_relink_is_offered_again` (updated for the cooldown)
- comp-sync-14 -> `test_the_plan_stamp_advances_when_the_dashboard_answers_again`
- comp-sync-15 -> `test_the_trash_summary_carries_the_path_and_the_configured_retention`
- comp-sync-16 -> `test_a_new_episode_never_inherits_the_last_ones_mute`
- comp-sync-17 -> `test_two_repaths_in_the_same_millisecond_can_both_retire`
- comp-sync-18 -> `test_a_decomposed_proxy_follows_its_original`
- comp-sync-19 -> `test_more_than_one_folder_problem_is_counted`
- comp-sync-22 -> `test_an_upload_only_project_gets_no_structure_clone`
- comp-app-4 (owed to this territory by the comp-app builder) -> `test_the_refused_relink_book_is_capped_at_the_source`
- res-companion-1 -> `test_a_move_interrupted_before_the_ledger_row_is_finished_on_redelivery`, `test_a_machine_that_never_held_the_file_still_answers_nothing_here`
- res-companion-5 -> `test_deletions_made_before_a_hard_kill_are_still_on_the_account`, `test_an_in_flight_credit_is_not_counted_twice_by_the_finished_pass`

Suites run (companion venv, territory files only): the new file plus
`test_repath.py test_file_moves.py test_lane_guard.py test_drive_reminder.py
test_watcher.py test_selection.py test_shared_folders.py
test_borrowed_folders.py test_syncthing_lane.py test_syncthing_supervisor.py
test_upload_only.py test_sequencer.py test_lane_b_resume_requests.py` -> 585
passed, and `test_no_em_dash.py` -> 100 passed. Three existing tests were
updated, each with the finding id in a comment: the repath retry now needs
`force=True` (the throttle), the borrowed halt outcome is `halted`, and the
watcher re-offer waits out the cooldown.

One addition arrived from the comp-app builder mid-pass (comp-app-4): the
report caps `non_canonical_refused` at 50, but `watcher.py`'s own
`_non_canonical_refused` dict was unbounded, so the memory that cap was meant
to save was already held on the one machine that produces refusals in bulk - a
wrong `canonical_prefix` and a media pool full of them. It is capped at the
source now (`MAX_NON_CANONICAL_REFUSED = 200`, oldest evicted first, above the
report's 50 because a surface may want more than the wire sends).

### OWED TO ANOTHER TERRITORY

- `companion/src/ccsync_companion/tray.py` (comp-ui): `tray._guard_fingerprint`
  must include the new persist-failure field or the menu never redraws when it
  appears. The exact keys are `sync_guard["lane_b_breaker"]["persist_failed"]`,
  `sync_guard["disk_floor"]["persist_failed"]` and
  `sync_guard["halt"]["persist_failed"]` (booleans, absent when the disk is
  fine), plus a line an editor can act on: "CC Sync cannot save its safety
  state on this computer (<error>). Restarting CC Sync would clear it." My side
  is complete without it - the failure is in the report, in the fleet grid's
  payload and at ERROR in the log, and the write is retried every 60 s.
- `companion/src/ccsync_companion/app.py` (comp-app), comp-sync-4: neither
  `app.shared_folder_problems()` nor `app.repath_events()` has a caller. The
  fix is the tray snapshot's `_get(...)` block and the reporter payload beside
  the existing `sync_guard` sections, with the values added to
  `tray._guard_fingerprint`. The producers are correct and the lane C detail
  now carries the shared-folder half on every branch (comp-sync-3), so the
  genuinely unsurfaced item is the successful repath's note.
- `companion/src/ccsync_companion/app.py` (comp-app), comp-sync-9: the wedged
  balloon and `begin_state` sit inside `if not self._root_absent_announced:`,
  so `absent -> not_answering` (an SMB mapping that drops and comes back as a
  stale session) opens no episode at all. Gate the per-state balloon/episode on
  the STATE having changed, keeping the `unfinished` judgement once per outage
  (CR-92). My side is ready for it: `resume_remembered(state)` takes the
  current state, and `app.py` should pass it at `app.py:2379` - without that
  argument a remembered state episode is dropped rather than replayed, which is
  the safe direction.
- `companion/src/ccsync_companion/app.py` (comp-app), comp-sync-21: `suffix =
  " P: was restored to your local copy."` at `app.py:4373` hardcodes the drive
  letter three lines below a `letter=self.canonical_drive_letter()`. One line:
  `f" {letter} was restored to your local copy."`.
- `companion/src/ccsync_companion/app.py` (comp-app) + dashboard, comp-sync-20:
  a move delivered while the sync drive is out expires after 7 days of "told
  and never answered" while the companion is deliberately silent. Either answer
  `state="retrying"` with "waiting for the sync drive" (the shape v36 already
  carries) or skip the delivery stamp for a machine whose last report said the
  root was absent.
- `companion/src/ccsync_companion/app.py` (comp-app), res-companion-1: to get
  the crash-window fix, `_apply_file_moves` must pass the ledger:
  `file_moves.apply_move(move, local_root, ledger=self.file_moves)`. Without
  it `apply_move` behaves exactly as it does today (the parameter is optional
  and defaults to None), so nothing breaks if it lands later. `docs/FILE_MOVES.md`
  should record the `applying` state.
- `companion/src/ccsync_companion/app.py` (comp-app), comp-sync-13: move the
  `waiting` de-dupe out of the `if user_initiated:` block in
  `_handle_non_canonical` and cap `_canon_relink_pending` (prefer dropping
  duplicates over dropping new items). The comment at `app.py:2811` ("both
  producers latch once per process") was made untrue by RES-19 and should go
  with it. The watcher's cooldown bounds the growth to one offer per path per
  15 minutes in the meantime.
- `companion/tests/test_settings_window.py` (comp-ui), comp-sync-15: the guard
  dict at :915 is hand-built with `"path"` and `"max_age_days": 30`, a shape
  the producer never emitted. It is now real, so the test is no longer pinning
  a phantom - but it should be built from `RcloneLane.trash_report()` rather
  than by hand.
- `dashboard/src/ccsync_dashboard/api.py` (dash territory): the report's
  `sync_guard.trash` now carries `path` and `max_age_days`, and the three latch
  blocks can carry `persist_failed` / `persist_error` / `persist_failed_at`.
  Both are additive and ignorable; no deploy order is forced either way.

### Owner decisions

- `resume_remembered()` called with NO state now DROPS a remembered state
  episode instead of replaying it (comp-sync-8). That is the safe direction and
  the caller re-opens the right episode within the same callback, but it does
  mean that until `app.py` passes the state (OWED above), a genuinely still
  wedged drive gets its reminder from the fresh announcement rather than from
  the record.
- A spelling-only rename of a FOLDER is REFUSED with a sentence rather than
  renamed through a temporary name (comp-sync-12). A directory two-step is a
  much bigger blast radius on a machine where Syncthing may be watching the
  path, and the dashboard could equally refuse a case-only move at `api.py`
  instead - worth deciding which end owns it.
- The pending-relink walk is throttled to once per 5 minutes
  (`RELINK_RETRY_MIN_SECONDS`, comp-sync-6) and the non-canonical re-offer to
  once per 15 minutes (`REARM_COOLDOWN_SECONDS`, comp-sync-13, matched to
  `resolve_journal.allow_automatic`). Both are judgement calls about how soon a
  human could possibly have fixed the thing.
- A note about `db.fetch_machine_selections(for_enforce=True)` and `api.py`
  around line 2713 was sent to this builder mid-pass and then withdrawn by the
  orchestrator as misrouted. Nothing in the dashboard was touched.
