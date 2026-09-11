# comp-sync - the companion's sync lanes, selection, file moves, drive/root guards

Files read (with approximate coverage):
`git diff 40f931a..HEAD` of the whole territory, hunk by hunk (100%); then
`sync/sequencer.py` (the lane A/B run block, the comp-sync-7 latch, ~30%),
`sync/lane_guard.py` (`_write_json`, `_PersistedLatch`, `LaneBBreaker`,
`DiskFloorLatch`, `HaltState`, ~60%), `sync/rclone_lane.py` (`run_once`'s
spawn/return paths, `_account_pass`, `_credit_deletes_in_flight`, the trash
summary, ~25%), `sync/repath.py` (`RepathLedger`, `reconcile`,
`retry_pending_relinks`, ~70%), `sync/shared_folders.py` +
`sync/borrowed_folders.py` (`reconcile`, `_accept`, `FolderProblems`, ~80%),
`sync/syncthing_lane.py` (`check_once`, `_with_problems`, ~40%),
`sync/syncthing_supervisor.py` (backoff/attempts, ~20%), `file_moves.py`
(100%), `selection.py` (fetch/cache/stamp, ~60%), `drive_reminder.py`
(~70%), plus `app.py`'s file-move handler, `_relink_pending_moves`,
`_on_moved_clip_missing` and `_show_moved_clip_dialog` (the other side of
res-companion-1's wire). `drive_swap.py`, `manifest.py`, `root_guard.py`:
skimmed only, unchanged since 40f931a.

Tests run:
`companion/.venv/Scripts/python.exe -m pytest tests/test_bug_hunt_2026_09_11_comp_sync.py tests/test_sequencer.py tests/test_lane_guard.py tests/test_repath.py tests/test_file_moves.py tests/test_drive_reminder.py tests/test_selection.py tests/test_shared_folders.py tests/test_borrowed_folders.py -q`
-> **423 passed**, 1 warning.
Plus two ad-hoc scripts from the companion venv (scratchpad), quoted below.

## Findings

### comp-sync-b-1 - the new abandoned-lane-B latch can be set after the thread has already cleared it, and then nothing ever clears it: proxy download is off for the rest of the process
- Severity: high
- Confidence: CONFIRMED (reproduced)
- Where: `companion/src/ccsync_companion/sync/sequencer.py:2088-2097` (the
  `if thread.is_alive(): ... with self._lock: self._lane_b_abandoned = subpath`)
  against `companion/src/ccsync_companion/sync/sequencer.py:2027-2033` (the
  lane B thread's `finally: self._clear_lane_b_abandoned()`)
- What: comp-sync-7 latches `_lane_b_abandoned` in the SEQUENCER thread,
  after `thread.is_alive()` has already returned True, while the only code
  that can ever clear it is that same lane B thread's own `finally`. If the
  wedged pass ends in the window between the `is_alive()` check and the
  assignment - `_note_lane_moved()` plus a lock acquire - the clear runs
  first and the set runs second. The latch is then permanently on, and
  `grep -n "_lane_b_abandoned" sequencer.py` shows the only writer that
  clears it is `_clear_lane_b_abandoned`, called from nowhere but that
  thread.
- Failure scenario: an rclone child that was unkillable for 30 s (the abort
  path) finishes 50 ms after the second `thread.join(LANE_B_ABORT_JOIN_SECONDS)`
  gives up. From that moment every project turn logs "not starting lane B
  for <x> - an earlier pass on <y> was abandoned and is still running",
  lane B's detail reads `stalled on <y>: waiting for an earlier pass to end`,
  and NO proxy ever downloads again until the editor restarts the tray. The
  lane is not red and no notice is raised, so this is "green while dead" for
  the one lane an editor notices last.
- Evidence: scratch repro (scratchpad `race.py`, uses `test_sequencer._build`,
  `lane_b_join_timeout -> 0`, `LANE_B_ABORT_JOIN_SECONDS = 0`, a lane B that
  sleeps 0.4 s, and a lock whose third acquire sleeps 0.6 s to make the
  window deterministic):
  ```
  sequencer: lane B is STILL running after the abort (no child to kill) -- continuing without it ...
  sequencer: not starting lane B for Projects/2026/FF5/Next -- an earlier pass on Projects/2026/FF5/Wedged was abandoned ...
  lane_b_abandoned after the thread ENDED: Projects/2026/FF5/Wedged
  lane B calls: ['Projects/2026/FF5/Wedged']
  ```
  The two comp-sync-7 tests
  (`test_no_second_lane_b_is_started_while_one_is_abandoned`,
  `test_a_queued_pass_for_a_stale_subpath_is_dropped`) set the latch by hand
  and never exercise the set/clear ordering, so neither can see this.
- Ledger: regression of CR-234 (comp-sync-7) - the fix introduces it
- Suggested fix: make the latch a thread identity rather than a bare string:
  set `self._lane_b_abandoned = (subpath, thread)` and, immediately after the
  assignment, re-check `thread.is_alive()` and clear if it has died; or have
  `_b`'s `finally` clear only its OWN generation (a monotonically increasing
  pass id captured before `thread.start()`), and re-check liveness once per
  sequencer pass in `_run_lanes_a_and_b` before honouring the latch.

### comp-sync-b-2 - res-companion-1's `applying` intent row is written with `relink_pending=True`, and `pending_relinks()` / `moved_to()` filter on neither `ok` nor `state`: Resolve can be repointed at a file that was never moved
- Severity: medium
- Confidence: CONFIRMED (code path; the trigger is a crash/kill window)
- Where: `companion/src/ccsync_companion/file_moves.py:472-484`
  (`record_intent(..., relink_pending=True)`),
  `companion/src/ccsync_companion/file_moves.py:520-528` (`pending_relinks`),
  `companion/src/ccsync_companion/file_moves.py:537-557` (`moved_to`), and
  the consumers `companion/src/ccsync_companion/app.py:7759-7780`
  (`_relink_pending_moves`, called on EVERY Resolve project change) and
  `app.py:7801-7823` (`_show_moved_clip_dialog`).
- What: before this afternoon, `old_local`/`new_local` and
  `relink_pending=True` were only ever written for a move that had ACTUALLY
  happened (`apply_move` returns the pair on success only). `record_intent`
  now writes both BEFORE the first filesystem call, and `record()`'s
  `elif previous.get("old_local")` branch carries them forward into every
  later row for that id. Neither `pending_relinks()` nor `moved_to()` looks
  at `state` or `ok`, and neither `_relink_moved` nor the dialog checks that
  `new_local` exists. So an intent row is indistinguishable from a completed
  move to every relink consumer.
- Failure scenario: the companion is killed (CR-93's routine "died without a
  shutdown", or the supervisor's own restart) between `ledger.record_intent`
  and `src.replace(dest)`. The file is still at the old path. On restart, the
  editor opens any project before the dashboard redelivers the command:
  `_relink_pending_moves()` fires, `_relink_moved` matches every clip under
  `old_local` and calls `resolve_bridge.replace_clip` to point them at
  `new_local`, which does not exist on this machine. Every one of those clips
  goes Media Offline, journalled as a real Resolve mutation, in a project the
  editor was in the middle of. The watcher's dialog is the same defect with a
  human in the loop: it says, in writing, "Your copy has already been moved
  to match" for a move that has not happened.
- Evidence: read `file_moves.py:520-528` (`pending_relinks` filters only
  `relink_pending` + `old_local` + the 30 day window) and `app.py:7769-7773`
  (no existence check on `entry["new_local"]`); `record_intent` passes
  `relink_pending=True` explicitly. `test_a_move_interrupted_before_the_ledger_row_is_finished_on_redelivery`
  tests only the crash-AFTER-the-rename half, which is the safe one.
- Ledger: regression of CR-234 (res-companion-1)
- Suggested fix: `record_intent` should write `relink_pending=False` (the
  resume path in `apply_move` sets it properly when it finishes the move),
  and both `pending_relinks()` and `moved_to()` should skip rows whose
  `state` is `STATE_APPLYING`; belt and braces, `_relink_pending_moves` and
  the dialog should refuse a `new_local` that does not exist on disk.

### comp-sync-b-3 - a lane B pass that returns without reaching `_account_pass` leaves `_in_flight_credited` set, and the NEXT pass's deletions never reach the breaker's account
- Severity: medium
- Confidence: CONFIRMED (reproduced)
- Where: `companion/src/ccsync_companion/sync/lane_guard.py:671-702`
  (`note_deletes_in_flight`) and `:725-735` (`note_pass`), against
  `companion/src/ccsync_companion/sync/rclone_lane.py:3530-3545` (the two
  `except Exception as exc: ... return self.status()` early returns, which
  sit ABOVE `_account_pass` at `:3560`).
- What: `_in_flight_credited` is only reset by `note_pass` and by `resume()`.
  `run_once` has return paths that skip `_account_pass` entirely (an
  exception out of `_run_popen` or `subprocess_run` after the run had already
  emitted `--stats` ticks). The counter is then left at the dead pass's
  total, `note_deletes_in_flight`'s `delta = total - self._in_flight_credited`
  is negative for the whole of the next pass, and `note_pass` subtracts the
  same stale `credited` a second time - so a real pass's deletions are
  discounted twice and vanish from the cumulative account the breaker trips
  on. Exactly the direction res-companion-5 was written to stop.
- Failure scenario: pass 1 trashes 50 proxies and then `_run_popen` raises
  (a decode error on the stderr pump, a watchdog bug, a Popen handle
  failure); pass 2 legitimately trashes 40 more. The breaker's cumulative
  `deletes` stays at 50: the 40 are invisible, and the "too much deleted
  since the counters were cleared" trigger is 40 files further from firing.
- Evidence:
  ```
  after pass1 50 50
  pass2 in flight credited? 50
  after pass2 note_pass 50 40
  ```
  (`LaneBBreaker.note_deletes_in_flight(50)`; no `note_pass`; then
  `note_deletes_in_flight(40)` + `note_pass(deleted=40)` - report shows
  `deletes == 50`, i.e. pass 2's 40 deletions are gone.)
- Ledger: regression of CR-234 (res-companion-5)
- Suggested fix: reset `_in_flight_credited` when a RUN starts rather than
  when it finishes - give the breaker a `begin_pass()` the lane calls before
  spawning rclone - or clamp `note_deletes_in_flight` so a total lower than
  the credited figure is treated as a new run (`if total < credited:
  credited = 0`) and have `note_pass` do the same.

### comp-sync-b-4 - a failed case-only rename can leave the editor's media file under a `.ccsync-move-<pid>-` name that lane A then uploads to the NAS
- Severity: low
- Confidence: PLAUSIBLE
- Where: `companion/src/ccsync_companion/file_moves.py:235-257`
  (`_rename_case_only`); lane A's filter set,
  `companion/src/ccsync_companion/sync/rclone_lane.py:1199-1200` (the only
  dot-name excludes are `.stversions/**`, `.stfolder/**` and `- ._*`).
- What: `_rename_case_only` stages the file at
  `.ccsync-move-<pid>-<original name>` and, if the second `replace` fails,
  tries to put it back; if that restore also fails it only logs. The staging
  name keeps the original extension, so it is a `.mov`/`.braw` as far as lane
  A's extension filter is concerned, and `recent_excludes` excludes the OLD
  rel path, not the staging name.
- Failure scenario: a case-only rename where Resolve grabs a handle on the
  file between the two `replace` calls (Windows, WinError 32 on both). The
  clip is now `.ccsync-move-8123-Clip.mov` on the editor's disk, the project
  shows it offline, and the next lane A pass uploads that name to the NAS
  beside the real one - the duplicate-at-the-cleared-path failure
  `docs/FILE_MOVES.md` exists to prevent, wearing a different name.
- Evidence: read `_rename_case_only` and the lane A filter builder; no
  `- .ccsync-move-*` rule anywhere (`grep -rn "ccsync-move" companion/src`
  finds only `file_moves.py`).
- Ledger: related to CR-234 (comp-sync-12)
- Suggested fix: stage inside `<local_root>/.ccsync-trash/` (already excluded
  everywhere) or add a `- .ccsync-move-*` rule to both lanes' filters, and
  register the staging path in the ledger so a restart can finish or undo it.

### comp-sync-b-5 - a fleet halt stops the borrowed folders from being accepted but not the shared asset libraries
- Severity: low
- Confidence: PLAUSIBLE
- Where: `companion/src/ccsync_companion/sync/shared_folders.py:455-495`
  (`SharedFolderManager._accept`, no halt check) against
  `companion/src/ccsync_companion/sync/borrowed_folders.py:358-372`
  (`BorrowedFolderManager._accept`, which returns `OUTCOME_HALTED`).
- What: `_accept` ends in `admin.accept_folder(...)`, which the borrowed
  manager's own comment says "ends in an unpause". `SharedFolderManager`'s
  reconcile honours the halt only for a folder that ALREADY exists and is
  paused (`shared_folders.py:404`); a folder being accepted for the first
  time goes straight online. comp-sync-10 touched both `_accept` methods this
  afternoon and added the halt branch to one of them only.
- Failure scenario: an admin halts the fleet, then the dashboard's provision
  cycle offers a new asset library (LUTs, music) to a machine. That machine
  accepts it and starts syncing it while every other lane is stopped - the
  sync-safety-2 / CR-48 shape.
- Ledger: related to CR-48 (the halt's asset-library half) - the asymmetry is
  pre-existing, but comp-sync-10 edited both sites without closing it
- Suggested fix: give `SharedFolderManager._accept` the same
  `if self.halted(): return OUTCOME_HALTED` guard the borrowed manager has.

## Coverage note
Not reached: `drive_swap.py`, `manifest.py` and `root_guard.py` beyond a
skim (all unchanged since 40f931a); `rclone_lane.py`'s filter construction,
express-upload and stray-project scan (the file is ~5,200 lines and only the
hunks above changed); `syncthing_admin.py` and `sync/base.py`; the
dashboard's rendering of the new `persist_failed` / `ask-failed` / `halted`
values (dash-mounts-ui / wire territory - I confirmed only that no dashboard
file mentions the outcome strings at all, so an unknown one is not parsed
anywhere).

Test-suite gaps I noticed: the two comp-sync-7 tests set `_lane_b_abandoned`
by hand and never run the set/clear ordering (finding b-1); the
res-companion-5 tests always call `note_pass` after the in-flight credits,
so the leak in b-3 cannot show; the res-companion-1 tests cover the
crash-AFTER-the-rename half only, never the crash-before-it that b-2 is
about. `_PersistedLatch`'s retry is tested through `report()` but nothing
tests that the retry stops once the write succeeds on a latch whose payload
changed in between.

## OUT OF TERRITORY
- `companion/src/ccsync_companion/app.py:7830` (comp-app): `_relink_moved`
  still compares media-pool paths with a bare
  `os.path.normcase(os.path.normpath(...))`, the exact thing comp-sync-11
  replaced with `file_moves.cmp_key` in `file_moves.relink_moved`. The
  KNOWN_BUGS note for comp-sync-11 calls this function its "twin"; on darwin
  it still folds neither case nor Unicode, so the decomposed-name relink is
  fixed on one of the two code paths only. (This is the path
  `_relink_pending_moves` and the moved-clip dialog actually use.)
