# CR-287 - the companion-core highs of the tenth hunt

## CR-287 - the file-move fixes of 2026-09-18 corrected - FIXED in repo 2026-09-18 (companion 0.9.75, unshipped)

All four findings are about fixes made THE SAME MORNING - CR-283Y's section 4b
branch, CR-283's dashboard-version gate and CR-282B's lane B relocation note -
and every one of them is a way those fixes lose an editor's original or take
their machine off the fleet grid. Nothing here is a wire change: the companion
says exactly what it said this morning, to exactly the same dashboards.

### CR-287A (comp-sync-1) - a machine with an empty plan trashed every file it was told to move - FIXED (companion/src/ccsync_companion/file_moves.py)

`app._synced_project_rels` returns `[]`, not `None`, for any managed companion
whose sequencer has an empty selection - an editor between projects, or one
whose admin has just cleared the ticks, which today's owner decision says must
never read as a fault anywhere. `_dest_is_synced_here` answered False for every
path against an empty list, so `apply_move` took the section 4b branch for
EVERY move, including a move whose source and destination are the one project
this machine is holding the file in. The local original went into
`.ccsync-trash`, `paths=None` meant Resolve was never relinked, `ok=True` meant
the dashboard recorded the machine as having followed, and
`lane_guard.prune_trash` deleted the batch on its age rule a fortnight later -
on a machine that may be the file's only holder.

**What the 4b branch may trust, stated:** a plan with AT LEAST ONE ENTRY that
also NAMES THE PLACE THIS MACHINE IS HOLDING THE FILE. Not an explicit "managed
and empty" signal: that would be a second thing for `_synced_project_rels` to
get right (it is driven unbound, through getattr, on stubs), and the honest
reading of an empty list is "cannot tell", which is what `None` already means
here. So `_dest_is_synced_here` now answers True - "move it normally, no
trash" - in three further cases, each with its own reason:

- the plan is empty (cannot tell; the pre-4b path, the same answer `None` gets);
- `to_project_rel` folds to `from_project_rel` (a move within the project the
  file is already sitting in; "the destination is not synced here" cannot be
  true of it whatever the plan says);
- the SOURCE path is not under any plan entry (this machine is holding the file
  in a project its plan does not account for, which proves the plan is not the
  whole truth about that disk - trashing on that evidence is a guess, following
  the move is not).

The destination prefix test is unchanged, and lifted into `_under_any` so the
source and the destination are judged by one rule: a selected project's rel is
a prefix of everything in it and a borrowed entry's key is the lender's
subpath, so the borrowed folder still passes and the rest of the lender's
project still does not.

Also here, from the same finding: the 4b branch now carries the
`Proxy/<stem>.*` siblings into the trash with the original, as every other
branch of `apply_move` carries them with the file. Left behind they are an
orphan whose original has gone, which lane B trashes on its own next pass, in
a different batch with a different age - so an admin's recovery was in two
places.

### CR-287B (comp-sync-2 = res-companion-1) - the 4b trash path became the "RELINK IT" destination - FIXED (companion/src/ccsync_companion/file_moves.py)

The 4b branch returns `paths=None` on purpose ("a relink to the trash would be
worse than the offline clip"), but it first wrote an INTENT row whose
`new_local` WAS the trash path, and `record()` carries `old_local`/`new_local`
forward from the previous row whenever `paths` is falsy. The completion row
therefore carried `<local_root>\.ccsync-trash\<stamp>\...` with state
`not_synced_here`, which `moved_to()` did not skip (it skips `applying` only) -
so the watcher's RES-10 hook offered the editor "CCSync can repoint Resolve to
where it is now", `_moved_destination_is_there` passed (the file really is in
the trash), and RELINK IT wrote that path into the media pool through
`replace_clip`. `prune_trash` then deletes the batch inside the 30 day relink
window, and every relinked clip is permanently Media Offline pointing at a
directory that no longer exists.

Three layers, because one of them is about rows already written:

1. the 4b intent row is written with an EMPTY `new_local`. It exists for its
   lane A exclusion and for the crash window, never as a destination;
2. `record()` does not inherit paths when the state is `not_synced_here`. A
   move with that word has no new path anywhere, by definition;
3. `moved_to()` and `pending_relinks()` skip `not_synced_here` rows the way
   they skip `applying` ones - which is what protects a ledger written by
   0.9.75 before this fix and read after the upgrade.

The lane A exclusion is untouched: `recent_excludes` keys on `from_project_rel`
/ `from_rel`, not on the local paths, so the old path still cannot re-upload
itself.

### CR-287C (comp-app-1) - a dashboard rollback 422'd every report from that machine for ever - FIXED (companion/src/ccsync_companion/app.py)

`_note_dashboard_version` only WROTE `app._dashboard_version` when the reply
carried the key; an absent key left the remembered value in place, for the life
of the companion process. Its own docstring says the opposite ("an ABSENT
`dashboard_version` means a dashboard older than the one that started sending
it, which is the safe reading") and the whole `not_synced_here` gate rests on
that reading. So: 0.7.50 is deployed, a companion sees it once, the deploy is
rolled back (a scripted, documented operation - `install_dashboard_app.py
--rollback-on-unhealthy`, `docs/RELEASE.md`), 0.7.49 answers and sends no
version at all, the companion still puts `not_synced_here` on the wire, and
0.7.49's `FileMoveResultIn.state` Literal rejects it - a 422 for the WHOLE
report, lanes and presence and alarms and jobs, every thirty seconds. Nothing
recovers it: there is no 422 shedding path on the companion side, the dashboard
never records the answer so it redelivers the command for ever, and the machine
reads as silent on the fleet grid until somebody restarts the tray.

The absent key now clears the memory, so the very report that would have been
rejected is the one that stops sending the word. A reply that is not a dict at
all is not an answer and still says nothing either way (the redelivery harness
and the tests drive this unbound).

### CR-287D (res-companion-2) - the file-move ledger had two writer threads and no lock - FIXED (companion/src/ccsync_companion/file_moves.py)

CR-282B handed the sequencer/lane thread a writer (`record_relocation`, up to
rclone's 100 per pass) into a ledger that until this morning only the reporter
thread wrote (`record_intent` / `record`), with lane A reading
`recent_excludes` on a third. There was no lock anywhere in the class and both
`_save()`s wrote one fixed `file_moves.json.tmp` before promoting it, so
interleaved they publish a truncated or doubly-written file - and on Windows
the loser's `replace` raises PermissionError, which was caught, logged and
lost. `_load` runs once, in `__init__`, so nothing notices while the process
runs: the damage surfaces at the next restart, which after a crash is the ONE
case the whole `applying`/intent design exists for. A ledger that reads back as
`[]` loses every intent row AND every exclusion, so lane A - which never
deletes - re-uploads the moved file to the old path on the NAS, the single
failure `docs/FILE_MOVES.md` exists to prevent.

`FileMoveLedger` now holds a `threading.RLock` (reentrant: the writers call the
readers, and `record_attempt_failed` calls `record`) taken around the mutation
AND the `_save()` that follows it, by `entry`, `record`, `record_intent`,
`record_relocation`, `relocation_to`, `record_attempt_failed`,
`clear_relink_pending` and `_save` itself; `pending_relinks`, `moved_to` and
`recent_excludes` copy the list under the lock and iterate their copy. The
scratch file is `file_moves.json.<pid>.<counter>.tmp` on top of that, because
the lock covers the threads of ONE companion and a second process on the same
state directory (a supervisor relaunch racing the dying tray, CR-93's shape) is
covered by nothing; a tmp that could not be promoted is unlinked, since
`state/` is not somewhere anything prunes.

### Verification

New file `companion/tests/test_bug_hunt_2026_09_18b_companion_core.py`; the
eight named here all fail on the pre-fix tree, the other two are the "must
still work" guards (section 4b still trashes a real 4b move; a reply that is
not a dict still says nothing).

- `test_an_empty_plan_moves_the_file_normally_instead_of_trashing_it` -> fails before the fix (the file was in `.ccsync-trash`), passes now
- `test_a_move_within_the_project_holding_the_file_is_never_trashed` -> fails before, passes now
- `test_a_source_the_plan_does_not_account_for_takes_the_pre_4b_path` -> fails before, passes now
- `test_a_real_4b_move_is_still_trashed` -> passed before, passes now (plus the new proxy assertion, which failed before)
- `test_the_4b_completion_row_carries_no_path_into_the_trash` -> fails before (the row carried the trash path and `moved_to` returned it), passes now
- `test_a_not_synced_here_row_is_never_offered_as_a_relink` -> fails before, passes now
- `test_a_dashboard_rollback_stops_the_state_word` -> fails before (`state: not_synced_here` to a 0.7.49 reply), passes now
- `test_a_reply_that_is_not_a_dict_leaves_the_memory_alone` -> passed before, passes now (the guard on the forgetting)
- `test_two_threads_never_write_the_ledger_at_once` -> fails before (two threads inside `_save`, and a real PermissionError on the shared tmp on Windows), passes now
- `test_the_ledger_tmp_file_is_unique_per_write` -> fails before, passes now

Re-run green, unchanged by this pass: `test_file_moves.py`,
`test_bug_hunt_2026_09_18_companion.py`, `test_bug_hunt_2026_09_11_comp_sync.py`,
`test_bug_hunt_2026_09_11b_comp_sync.py`, `test_bug_hunt_2026_09_11b_comp_app.py`,
`test_repath.py`, `test_rclone_lane.py` (299 tests).

### Not fixed

- none of the four.

### OWED TO ANOTHER GROUP

- none. Every change is inside `file_moves.py` and `app.py`; no wire field,
  no dashboard behaviour and no state word changed.

### Deploy order

- Unchanged from this morning, and CR-287C is what makes it survivable in both
  directions: the dashboard still deploys first for the `not_synced_here` word
  (0.7.50 declares it, the companion only says it to a dashboard that has told
  it 0.7.50 or above on the report reply in hand), and a dashboard ROLLBACK now
  stops the word within one report instead of 422ing every report for ever.
- The companion half is safe alone against every dashboard in the field
  (0.7.34..0.7.50): a 0.9.75 with these fixes and a 0.7.49 dashboard answers
  ok=True with the same sentence it has always sent.

### Owner decisions

- The 4b branch's trust rule is stated above as a decision, not a guess: a plan
  is trusted only when it has an entry AND accounts for where this machine is
  holding the file. The cost is that a machine whose plan genuinely covers
  nothing now FOLLOWS a move into a project it does not sync (the pre-CR-283Y
  behaviour: the file lands in a directory with no `.ccsync-project` marker
  that neither lane can see) instead of trashing it. That is a recoverable,
  visible-on-disk wrong answer; the alternative was deleting the original a
  fortnight later, which is not.
