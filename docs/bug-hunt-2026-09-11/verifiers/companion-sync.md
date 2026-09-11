# verdicts - companion-sync

Verified against git HEAD 40f931a (companion 0.9.70). Evidence produced from
the companion venv; no test reached a live Resolve (no `resolve_bridge`
import in any snippet below).

## comp-sync-1
- Verdict: DOWNGRADED to medium
- Reasoning: The mechanism is real and unarguable - `lane_guard._write_json`
  returns a bool nobody reads (`grep -n "_write_json("` finds exactly three
  call sites in the module, all `_persist_locked`, all discarding the value),
  there is no retry timer and no `sync_guard` field for a persist failure, so
  a latch whose write fails is in-memory only. That does breach CLAUDE.md's
  "never make a safety latch in-memory-only". What does not survive contact
  with the code is the severity, because the hunter's headline scenario picks
  the wrong disk and the wrong consequence: all three latch files live in
  `config_mod.CONFIG_DIR` (`~/.ccsync`), NOT under the sync tree
  (app.py:1425-1449 makes the choice explicitly, APP-3), so a full SYNC drive
  - the `DiskFloorLatch` condition and the `.ccsync-trash` 50 GB argument -
  cannot produce the ENOSPC that fails this write. The remaining triggers are
  a full/read-only home volume, EACCES or an AV lock. The blast radius is
  smaller too: (a) a failed write leaves the OLD file intact, so
  `_remote_counts` is not lost and the trigger-1 empty/shrink probes still
  re-trip on the next start BEFORE a delete, exactly as designed; (b)
  `HaltState` is re-derived from the report reply on every cycle
  (`app._apply_fleet_halt` -> `halt.note_fleet_flag`, app.py:7605-7635), so a
  fleet halt that failed to persist re-engages within one report interval - a
  LOCAL halt does not, which is the genuine loss; (c) `DiskFloorLatch` is
  re-evaluated per pass from real free space (`_check_disk_floor`), so a lost
  park re-parks; (d) a trigger-2/3 breaker trip lost to a restart costs at
  most one more capped pass, and lane B never deletes (everything goes to
  `.ccsync-trash`). Medium, not high: a real silent-failure hole in a safety
  latch, with a narrower trigger and a mostly self-healing aftermath.
- Evidence: app.py:1425-1449 (latch dir = CONFIG_DIR, deliberately not the
  tree); lane_guard.py:180-208 (`_write_json` warns and returns False, and
  deletes only the tmp); lane_guard.py:426, 823, 1203 (the three
  `_persist_locked` bodies, return value dropped); app.py:7617-7625 (the halt
  is re-adopted from `commands.halt` every report). No caller anywhere in
  `companion/src` inspects a `_write_json` result.
- Fix note: The suggested fix is right in shape. Raise the persist failure
  into `sync_guard` and retry, but note the surface it has to reach: the
  `sync_guard` block is assembled in `app.py` (`guard["halt"]` at :6165 and
  `RcloneLane.sync_guard_report`), the tray reads it through
  `tray._guard_fingerprint` (tray.py:3475), so a new field must be added to
  the fingerprint or the menu line will never appear - that is the exact
  UI-3 shape the fingerprint comment describes. The process-unique tmp name
  is worth doing and is already spelled in `root_guard.py:195`
  (`f"{target.name}.{os.getpid()}.tmp"`). Tests that pin the current shape:
  `companion/tests/test_lane_guard.py`.

## comp-sync-2
- Verdict: CONFIRMED (medium)
- Reasoning: Reproduced both halves from the companion venv. Both constants
  are FLOATS (`PROBLEM_RETRY_FIRST_SECONDS = 60.0`, `BACKOFF_START_SECONDS =
  30.0`), which is what turns `2 ** (attempts - 1)` from a harmless big int
  into `OverflowError: int too large to convert to float` at attempts >= 1025
  - with int constants Python would have shrugged. The reachability argument
  holds: `FolderProblems.due()` gates the retry, so after the 1800 s cap one
  attempt per 30 min gives ~21 days of tray uptime, and the supervisor's
  counter is PERSISTED (`syncthing_supervisor.json`, `_attempts` at :387,
  `_persist_locked` at :414) and cleared only by `_note_reachable`, so its
  600 s cap gives ~7 days of a machine whose Syncthing cannot start,
  accumulated across restarts. The re-entrant `except` arm is real:
  `shared_folders.reconcile`'s handler calls `self._problems.note(...)` again
  (shared_folders.py:311-313) and that second call raises out of a method
  documented as never raising. One correction to the finding: the two
  managers are reconciled in SEPARATE try/except blocks
  (`_reconcile_shared_folders` and `_reconcile_borrowed_folders`, sequencer.py
  :1224-1241), so an overflow in one does not silence the other - each has to
  reach 1025 on its own, which on the same 30 min cadence they do.
- Evidence: `backoff_seconds(1024) -> 600.0`; `backoff_seconds(1025) ->
  OverflowError: int too large to convert to float`; a real `FolderProblems`
  raises on `note()` call 1025 (attempt counter never advances past 1024, so
  it raises forever after). Supervisor path: `_note_unreachable` calls
  `backoff_seconds(attempts)` unguarded at syncthing_supervisor.py:596, and
  `tick` swallows it as "supervisor: tick failed" (:490-497), so no further
  start attempt is ever made.
- Fix note: `min(attempts - 1, 20)` in both places is correct and sufficient
  (2**20 * 60 already exceeds every cap). Also worth clamping `_attempts`
  itself on load in the supervisor, since it is read off disk with `_as_int`
  and a hand-edited or corrupted file can arrive at any value. Making
  `reconcile`'s `except` arm not re-enter `note()` is the second half and
  should not be skipped. Touch `companion/tests/test_shared_folders.py` and
  `test_syncthing_supervisor.py` for the clamp.

## comp-sync-3
- Verdict: CONFIRMED (medium)
- Reasoning: Reproduced exactly. The SYNC-101 block is the last thing
  `check_once` does (syncthing_lane.py:731-735) and every early `return`
  above it skips it: the unreachable/bad-key branches (:540-554), the empty
  `expected` branch (:563-576) and the config-read failure (:594-599). The
  empty-`expected` branch is the one that matters, because
  `expected_folder_ids_fn` is wired to `Sequencer.expected_folder_slugs()`
  (the PROJECT selection only - `_effective_folder_ids`, :345-352), and
  `shared_folders.py`'s own docstring says the manager must be online for an
  editor with zero projects ticked. One correction: the PAUSED branch is part
  of the if/elif chain and DOES fall through to the problems block, so it
  needs no fix; the branches that need one are empty-expected, unreachable,
  bad-key and config-failure.
- Evidence: a real `SyncthingLane` with `expected_folder_ids_fn=lambda: []`
  and a non-empty `shared_folder_problems_fn` answers `state=idle
  detail='no project folders to check yet' last_error=None` - the LUT
  sentence is dropped on the floor.
- Fix note: Computing `problems` before the branch tree and folding it into
  `_with_path_detail` on every status is right. Watch the error branches: the
  unreachable/bad-key statuses carry `last_error` and no `detail`, and the
  settings/tray renderers show `last_error` first, so appending to `detail`
  there may still not surface. `companion/tests/test_syncthing_lane.py:811`
  pins the current (working) happy path and will need a sibling for the empty
  case.

## comp-sync-4
- Verdict: DOWNGRADED to low
- Reasoning: The dead-code claim is exactly true and I re-ran the grep over
  `companion`, `dashboard` and `tools` (py/js/html): `app.shared_folder_problems`
  and `app.repath_events` have no caller outside their own definitions and
  `tests/test_app_contract.py`. `tray.py`'s snapshot `_get(...)` block pulls
  the sibling producers and not these two; `reporter.py` and
  `settings_window.py` mention neither. What refutes the SEVERITY is that
  both underlying facts DO reach a human by another route, so "computed,
  persisted, and nobody is told" is only half true: the shared-folder
  sentences reach the editor through the lane C detail
  (`app.py:2134` wires `shared_folder_problems_fn` into `SyncthingLane`,
  which renders `problems[0]` - subject to comp-sync-3's gap), and the
  blocked-repath sentence reaches the project row through
  `Sequencer._repath_blocked_by_slug` -> `project_status()`, which
  `settings_window.py:741` renders. The genuinely unsurfaced item is the
  SUCCESSFUL rename's note ("Resolve reconnects the clips next time you open
  that project") plus the report field CR-167 claimed. Two unused accessors
  and one missing sentence is low.
- Evidence: `grep -rn "shared_folder_problems\|repath_events"` over
  companion/dashboard/tools - hits only at app.py:2134/4858/4872,
  sequencer.py:906/926/941, syncthing_lane.py:198-226/406-414/733 and tests.
  sequencer.py:936-948 shows `_repath_blocked_by_slug` reading the same
  ledger for `project_status()`.
- Fix note: The suggested fix (tray snapshot + reporter payload) is right and
  cheap. If it lands, the tray's rebuild fingerprint must include the new
  values or the menu will not redraw (tray.py:3475 `_guard_fingerprint`), and
  the dashboard needs a reader if the report field is to be more than bytes
  on the wire - `dashboard/src/ccsync_dashboard/api.py`'s report handler and
  the grid template are the other side of that wire.

## comp-sync-5
- Verdict: CONFIRMED (medium)
- Reasoning: Read end to end and the trap closes. `reconcile` writes
  `moved=False` only on the blocked branch (repath.py:356) and writes
  `moved=True` only on a pass that both finds `actual != expected` and moves
  it; the `actual == expected` path `continue`s at :341 with no ledger write
  at all. `RepathLedger.record`'s dedup key is `(slug, old, moved)`
  (repath.py:232-240) so a blocked row is only ever replaced by another
  blocked row, `events()` applies no time cutoff (unlike `pending_relinks`,
  which does), and the file is persisted under `~/.ccsync/state/`. So
  `_repath_blocked_by_slug` keeps returning the sentence until the row is
  pushed out by EVENTS_MAX=20 other events - which on a machine with a
  handful of projects is never. The two escape routes the hunter names (the
  admin undoes the rename; the editor unticks and re-ticks so the folder is
  accepted fresh at `expected`) both land on the `continue`.
- Evidence: repath.py:47-52 (EVENTS_MAX 20, no age filter on `events()`),
  :232-243 (dedup key), :341 (`continue` with no clearing event), :356
  (blocked record), sequencer.py:936-948 (blocked wins until a `moved=True`
  for that slug).
- Fix note: The fix is right but has a trap: on the `actual == expected`
  path the folder may still be PAUSED, because the blocked branch
  deliberately leaves it paused (repath.py:357-370, AUDIT_2 DEL-5/L-8).
  Clearing the sentence without also unpausing would turn "says blocked, is
  blocked" into "says fine, syncs nothing" - strictly worse. Clear the event
  AND unpause on that path, or clear only after confirming the folder is not
  paused. `companion/tests/test_repath.py` and
  `test_sequencer.py:2289-2302` pin the current ledger behaviour.

## comp-sync-6
- Verdict: CONFIRMED (medium)
- Reasoning: The arithmetic is in the call graph, not in the hunter's head.
  `ProjectRepather.reconcile` calls `retry_pending_relinks()` unconditionally
  at its head (repath.py:319) and BEFORE the `get_config()` try, so it runs
  even with Syncthing unreachable; `Sequencer` calls `_reconcile_paths` once
  for the whole selection (sequencer.py:1102) and again per project
  (:1902, inside `_process_project`), so one pass is 1+N reconciles and the
  docstring's "once per sequencer pass" is false. Each pending event costs a
  full `resolve_bridge.get_media_pool_items()` through `file_moves.relink_moved`,
  and the events only retire when a walk FINDS clips at the old path
  (`_relink` maps a falsy match to None, never False), so a project the
  editor never opens is re-walked for the full 30 day RELINK_WINDOW. The walk
  is not cheap and is not cached: `_library_pool_read` takes `_LIBRARY_LOCK`
  and deliberately does not gate on `changed()`, with a comment that assumes
  it is "asked for every 120 s at most" - precisely the assumption this
  violates - and `_enrich_proxy_keys` then asks Resolve per clip.
- Evidence: repath.py:319 + 419-438; sequencer.py:1102 and 1902;
  resolve_bridge.py:1652-1658 and 1688-1725 (no per-call cache, lock held).
  The hunter's 3 pending x 7 reconciles = 21 walks per pass matches the call
  graph.
- Fix note: The throttle is right. Do it inside `ProjectRepather` (a
  monotonic stamp), not in the sequencer, because `reconcile` is also called
  from the per-project path and a sequencer-side guard would miss the
  startup call. Combine it with comp-sync-11's fix, or the walks stay
  permanent on a Mac: the events that never retire are what the walking
  costs. `companion/tests/test_repath.py` asserts `retry_pending_relinks`
  runs on each reconcile and will need updating.

## comp-sync-7
- Verdict: CONFIRMED (medium)
- Reasoning: All three cited sites read as described and the containment
  comment is provably wrong once the abort fails. `RcloneLane.run_once`
  acquires a plain blocking `threading.Lock` (rclone_lane.py:3334) and only
  then re-checks `_stop_event`, the root and the breaker - never "is this
  subpath still current". `_run_lanes_a_and_b` starts a lane B thread
  unconditionally whenever `concurrent_lanes and run_b` (sequencer.py:1995);
  nothing anywhere records that the previous one was abandoned, and the
  "It cannot start another pass" comment at :2040 is true only of the
  abandoned thread itself, not of the new one queued behind it. So every
  subsequent project turn leaks one blocked daemon thread, and when the wedge
  clears they drain in order, each running `rclone sync` against a subpath
  that may since have been repathed - the exact hazard the join exists to
  prevent. Trigger is the module's own documented "STILL running after the
  abort" branch (a child in an uninterruptible wait), so it is rare, but the
  consequence is unbounded and uncoordinated.
- Evidence: sequencer.py:1995 (unconditional start), :2036-2049 (short join,
  "continuing without it"), rclone_lane.py:3334-3345 (`with self._run_lock:`
  then the early-return checks). `lane_b_join_timeout(budget)` = 2*budget +
  300 + 120, i.e. ~35 min at the 900 s default, so the window is long.
- Fix note: The latch is the right fix, and `_run_once_locked` dropping a
  pass whose subpath is stale is the important half - without it a
  companion restart is the only thing that clears the queue. The latch must
  be cleared from the abandoned thread's own `finally` (the `_b()` closure at
  sequencer.py:1982), and the lane's state needs a "stalled" detail so the
  tray does not report lane B idle while it is wedged. Note the interaction
  with CR-91/SYNC-1: the bounded join is what this is the other half of, so
  the fix belongs in the same file and its tests
  (`companion/tests/test_sequencer.py`, the CR-91 guard).

## comp-sync-8
- Verdict: CONFIRMED (medium)
- Reasoning: The ordering hole is exactly as described.
  `_on_root_absent` calls `end_state_episode()` only when the state CHANGED
  and is not `not_answering` (app.py:2266-2274); on a fresh process
  `_root_state` is empty so the first callback does take that branch, but
  `DriveReminder._kind` is still `""` at that moment (the record has not been
  read yet) and `end_state_episode` returns immediately on `_kind in ("",
  "unfinished")` (drive_reminder.py:356-363). `resume_remembered()` then
  reads the file and re-opens the persisted `not_answering` episode via
  `begin_state(record["kind"], record["sentence"])` with no reference to the
  state actually being reported (:294-318), and fires `remind_now()`. So a
  drive that is now simply ABSENT gets the wedged-drive sentence and the
  30-minute cadence, and only the drive coming back clears it. This does
  contradict SYNC-120's stated contract.
- Evidence: drive_reminder.py:294-318 and 356-363; app.py:2258-2300.
  The restored branch is taken whenever `summary` is empty, which is the
  definition of a state episode.
- Fix note: Passing the current state into `resume_remembered()` is the
  cleaner of the two suggestions - calling `end_state_episode()` after the
  resume would also cancel a legitimately restored episode one line after
  opening it if the state string differs only in spelling. Whatever lands
  must keep the `unfinished` branch untouched (work owed outlives every
  state change, which `end_state_episode` is careful about).
  `companion/tests/test_drive_reminder.py` pins the current resume shape.

## comp-sync-9
- Verdict: CONFIRMED (medium)
- Reasoning: `RootGuard.probe_once` fires `_fire(state)` on ANY changed
  non-unknown state (root_guard.py:767-778), so `absent -> not_answering`
  does reach `_on_root_absent`. But the wedged balloon and `begin_state`
  both sit inside `if not self._root_absent_announced:` (app.py:2280-2313),
  and that flag is cleared only in `_on_root_present`. So the second state of
  an outage opens no episode, and `end_state_episode()` is skipped as well
  because the new state IS `not_answering`. The path is reachable in the
  field: an SMB mapping that drops (absent) and comes back as a stale
  session that hangs on open() is exactly `absent -> not_answering` with no
  `present` in between. Confidence upgraded from the hunter's PLAUSIBLE to
  confirmed by reading; severity unchanged.
- Evidence: root_guard.py:767-778 (`_fire` on every changed state),
  app.py:2266-2274 (end_state_episode skipped for `not_answering`), :2279
  (`if not self._root_absent_announced:` wrapping both the balloon and
  `begin_state`).
- Fix note: Gating on "the state changed" rather than on
  `_root_absent_announced` is right, but the flag also suppresses the
  `log.warning` and `_unfinished_before_pause()`, and `unfinished` is
  deliberately computed only on the first announcement (CR-92: work owed at
  the moment the drive went). A fix must keep the unfinished judgement
  once-per-outage while letting the per-state balloon/episode fire on each
  transition, or a wedge after an unplug will re-ask "what was owed" against
  a tree that is not there. `companion/tests/test_app.py` carries the CR-92
  four-sentence tests.

## comp-sync-10
- Verdict: DOWNGRADED to low
- Reasoning: The conflation is real - `_accept` returns the literal
  `"not-offered"` from three places in the borrowed manager (an exception
  reading `pending_folders`, a genuinely empty `offeredBy`, and the
  `halted()` branch) and from two in the shared one, and `problem_sentence`
  turns all of them into "Ask your admin to approve it". But the failure
  SCENARIO the severity rests on does not happen. The tray's pause is not
  this halt at all (`halted=lambda: self.halt.active`, app.py:1517), and a
  real halt STOPS the sequencer (`halt_all_sync` -> `_stop_lanes` ->
  `sequencer.stop()`, app.py:6841-6848) while `_start_lanes` refuses to start
  it again for as long as the halt is active (app.py:5616-5629). With no
  sequencer there is no reconcile, so the `halted()` branch is reachable only
  in the race where the halt engages between `pending_folders()` and the
  accept - once per halt at most. What remains is the transient-read-failure
  conflation, which is genuine (a restarting local Syncthing tells the editor
  to chase their admin) but is a wrong sentence, not a wrong state, and
  clears on the next successful reconcile.
- Evidence: borrowed_folders.py:344-360 (three returns, one literal);
  shared_folders.py:425-448; app.py:1517, 5616-5629, 6841-6848.
- Fix note: The distinct outcome strings are still worth having and the fix
  is safe (the callers use the outcome for the log and the sentence, not for
  control flow - both `reconcile`s only test membership in
  `PROBLEM_OUTCOMES`). Adding a new outcome means updating `PROBLEM_OUTCOMES`
  in BOTH modules and `problem_sentence`, or the new string will record no
  problem at all - which is correct for the halt and wrong for the read
  failure. `companion/tests/test_borrowed_folders.py` and
  `test_shared_folders.py` assert on the current literals.

## comp-sync-11
- Verdict: CONFIRMED (medium)
- Reasoning: The contrast inside one file is damning. `_cmp_key`
  (file_moves.py:113-136) folds NFC and, on darwin, case, and its docstring
  cites CR-90 and the macOS CI runner for both folds. `relink_moved`
  (:243-262), added in the same wave and now depended on by
  `sync/repath.py`, compares with a bare
  `os.path.normcase(os.path.normpath(...))` - on darwin `normcase` is a
  no-op, so neither fold happens, while `old_local` is built from the
  dashboard's NFC `from_rel` and the Resolve/library path is NFD. So the walk
  matches nothing, `matched` is False, the pending relink never retires, the
  clip stays offline and the toast's promise is never kept. The twin at
  app.py:7568-7573 is byte-for-byte the same comparison and has the same
  hole. Windows is unaffected (both sides NFC, `normcase` folds case), which
  is why nothing in the field has reported it.
- Evidence: file_moves.py:113-136 vs :243-262; app.py:7568-7573;
  KNOWN_BUGS.md SYNC-11 states the NFC/NFD premise and that APFS hides it
  from `apply_move`.
- Fix note: Routing both through `_cmp_key` is correct, and the caveat the
  hunter gives is the important one - `os.path.relpath`/`os.path.join` must
  keep operating on the RAW strings, since `target` is handed to
  `canon.local_to_canonical` and then written into Resolve. Note that
  `app.py`'s copy would have to import `_cmp_key` from `file_moves` (it is
  private today); make it public or move the comparison into a shared helper.
  Fixing this is also what stops comp-sync-6's walks being permanent.

## comp-sync-12
- Verdict: CONFIRMED (medium)
- Reasoning: Reproduced on a real temp tree. `_same_file` is `_cmp_key(a) ==
  _cmp_key(b)` and `_cmp_key` folds case on Windows (via `normcase`) and on
  darwin (explicit `.lower()`), so a case-only rename short-circuits at
  file_moves.py:184 with `(True, "already where the server has it", None)` -
  the ledger records DONE, nothing is renamed, and the `None` pair means no
  relink and no exclusion is recorded either. The dashboard does permit the
  move: on the NAS's case-sensitive filesystem `dest.exists()` is False and
  `src == dest` is False (api.py:2697-2705), so the server renames and only
  the editors' machines no-op. Lane A then re-creates the old spelling when
  `recent_excludes` lapses, which is the duplicate-at-the-cleared-path
  outcome `docs/FILE_MOVES.md` exists to prevent.
- Evidence: `apply_move({'from_rel': 'clip.mov', 'to_rel': 'Clip.mov', ...})`
  on a real tree -> `(True, 'already where the server has it', None)` with
  the directory still listing only `clip.mov`. api.py:2697-2705 for the
  server-side permission.
- Fix note: The two-step rename through a temporary name is right, and it
  must be the ONLY place case folding is bypassed - `_is_inside`,
  `_under` and `moved_to` all need to keep folding. Two other files are
  involved: `move_proxy_siblings` has the same blind spot for the proxy
  (comp-sync-18), and the dashboard could equally refuse a case-only move at
  api.py rather than fix it on 30 machines - worth deciding which end owns
  it. `companion/tests/test_file_moves.py` has no case-only case today.

## comp-sync-13
- Verdict: CONFIRMED (medium)
- Reasoning: The de-dupe really is inside `if user_initiated:`
  (app.py:2809-2819) and its comment - "both producers latch once per
  process, this one does not" - was made untrue by RES-19, which added
  `TimelineWatcher.rearm_non_canonical` (watcher.py:459-479) discarding the
  key from the add-only `_offered_non_canonical` set on every failed relink.
  The cycle closes: a relink attempt fails -> `_note_non_canonical_result`
  rearms (app.py:2948-2965) -> the next 3 s poll re-offers the path
  (watcher.py:317-322 only skips keys still in the set) -> the unprompted
  branch does a bare `extend(fresh)` -> and `resolve_journal.allow_automatic`
  (900 s) then refuses the burst, so the pending list is not drained while it
  keeps growing. `_canon_relink_pending` has no cap.
- Evidence: app.py:2809-2819 (de-dupe under `if user_initiated:`), :2823
  (`extend(fresh)`), :2836-2845 (the limiter leaves the items pending),
  watcher.py:317-322 and 459-479. The hunter's harness result (offered once
  in three polls without a rearm, every poll with one) matches the code.
- Fix note: Moving the `waiting` de-dupe out of the `user_initiated` block
  is correct and safe - the user-initiated branch needs it for the same
  reason. A cap on `_canon_relink_pending` is the belt; prefer dropping
  duplicates over dropping new items, since the watcher may now be the only
  source. Fix the comment at app.py:2811 at the same time - it is what made
  this survivable-looking. `companion/tests/test_watcher.py` covers the
  rearm; the app-side de-dupe has no test today.

## comp-sync-14
- Verdict: DOWNGRADED to low
- Reasoning: The mechanism is confirmed by reading: `_write_cache` returns
  early on `response == self._last_written` (selection.py:279-284), so after
  the first successful write of a process the file's `fetched_at` is frozen
  for as long as the plan is unchanged, and `fetched_at()` falls back to that
  file whenever no live fetch has succeeded this run (:337-347). But the
  consequence is one PARENTHETICAL on a tray line, nothing more: the only
  reader is `tray._plan_stale_phrase` via `app.plan_fetched_at`, it is purely
  cosmetic, and it renders only when a live fetch has NOT succeeded this run
  - i.e. when the dashboard genuinely is not answering right now. So the
  sentence's claim ("the dashboard has not answered since") is true at the
  moment it is shown; only the AGE is overstated. No lane, no selection and
  no report decision reads the stamp. Low.
- Evidence: selection.py:279-284, 337-347; tray.py:646-681
  (`PLAN_STALE_SECONDS`, `_plan_stale_phrase`); `grep -rn fetched_at` shows
  no other consumer in companion or dashboard.
- Fix note: The "rewrite when the stored stamp is older than an hour"
  suggestion re-introduces a fraction of the AUDIT_2 P11 write storm the
  early return was added to stop - one write an hour is fine, but the test
  must be on the STAMP, not on the response, or it will write every poll.
  Storing the live stamp in a separate tiny file is cleaner and keeps
  `selection.json` byte-stable. `companion/tests/test_selection.py` pins the
  write-on-change behaviour.

## comp-sync-15
- Verdict: DOWNGRADED to low
- Reasoning: Both halves check out. `sync_guard["trash"]` is built in
  `RcloneLane._maybe_prune_trash` as `{**prune_trash(...),
  **scan_trash_dir(...)}` (rclone_lane.py:4031-4048) =
  `{removed, removed_bytes, kept, kept_bytes, at}` + `{count, bytes,
  truncated}`; neither producer emits `path` or `max_age_days`
  (lane_guard.py:1133-1140, rclone_lane.py:1236-1266), so `tray._trash_line`
  always falls back to `lane_guard_trash_name()` (the bare `.ccsync-trash`)
  and `_default_trash_days()` (the hardcoded DEFAULT 14, tray.py:2970-2976),
  regardless of the configured `trash_max_age_days`. The new
  `lane_guard.trash_summary()` that does carry `path` and `retention_days` is
  reached only by `app.trash_summary()`, which has no caller anywhere in
  `companion/src` (settings_window imports `tray_mod._trash_line`, not it).
  I downgrade because the damage is one imprecise menu line that only appears
  above 1 GB, on a site that has overridden the default - the size, count and
  the fact of recoverability are all still correct - and because
  `trash_folder(app)` (tray.py:2979, used at :4180) does give the editor the
  real path by another route.
- Evidence: `grep -rn "trash_summary"` -> app.py:4673 (definition, no
  callers), lane_guard.py, rclone_lane.py's private `_trash_summary`;
  `grep -rn "max_age_days" companion/src` -> only config.py:240, the lane's
  own `_trash_max_age_days` (rclone_lane.py:2447) and tray.py:2950's read of
  a key nobody writes. `companion/tests/test_settings_window.py:915` builds
  the guard dict by hand with `"path"` and `"max_age_days": 30`.
- Fix note: The suggested fix is right and is a two-line change in
  `_maybe_prune_trash` (add `path` and `max_age_days=self._trash_max_age_days`
  to `self._trash_summary`). Two other places must move with it: the
  hand-built dict in `companion/tests/test_settings_window.py:915` (it pins a
  shape the producer never emits - brief rule 7), and the dashboard, which
  parses `sync_guard.trash` on the fleet grid, so adding keys there should be
  checked against `dashboard/src/ccsync_dashboard/api.py`'s report ingest
  before it ships. Deciding what to do with the now-dead
  `app.trash_summary()` belongs with comp-sync-4.
