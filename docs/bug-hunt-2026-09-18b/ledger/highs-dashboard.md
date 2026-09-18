# CR-289 - the dashboard highs of the tenth hunt - FIXED in repo 2026-09-18

## CR-289 - the morning's own fixes finished: the answer half of res-fleet-4, a liveness test on identity, and corroboration before the fleet is told to move a file - FIXED in repo 2026-09-18 (db.py, api.py, collector.py)

All three findings are about CR-285AM (res-fleet-4) and CR-285AL
(dash-collector-alerts-1), built ON them rather than around them. Schema stays
at v54 (unshipped): one index is added to that block, no new table.

### CR-289A (dash-db-1 = res-fleet-1 = dash-api-1) - a command offered under a computer's FORMER hostname could never be answered - FIXED (db.py, api.py)

res-fleet-4 taught the OFFER and the delivery stamp to look under every
hostname of one `machine_id` (`command_machine_names`, `_by_target_machine`).
The three writers that record the machine's ANSWER were not taught: they
matched `machine = <reporting hostname>`, so for exactly the rows that fix
newly offers - the ones filed under the old name, inside the window SYS-18a
defers the adoption by, or for ever when the new name has a plan of its own -
the answer updated zero rows. `applied_at` stayed NULL, the same move rode
every report at thirty-second intervals, the companion re-applied it or
answered its not-found arm each time, and `expire_delivered_file_moves`
finally stamped `expired_at` and raised a `file_move_expired` warn for a move
that HAD been applied: verbatim the outcome res-fleet-4 was written to end.
The Resolve undo path had the same shape, and is worse, because an undo is
replayed against the editor's own Resolve.

Offer and answer read ONE function now (`db.file_move_answer_names`, which is
`command_machine_names`), so the two directions cannot drift apart again:
`mark_file_move_applied` and `mark_resolve_undo_applied` take the reporting
`machine_id` and match `machine IN (...)`, and `api._file_move_answer` - the
comp-app-2 log de-dupe - reads the same set, preferring this computer's own
row, because a de-dupe that reads a different row from the one it writes says
"no previous answer" every time and is the WARNING flood it exists to stop.
`machine_id` is optional everywhere: a companion whose report carries no id
answers under its own hostname, which is every build's behaviour to date.

### CR-289B (dash-db-2) - two live computers on one machine_id were each offered the other's file moves and Resolve undos - FIXED (db.py, api.py)

`command_machine_names` returned every registry row sharing the `machine_id`
with no test of whether that row is still LIVE, while SYS-18a's clone refusal
exists precisely to leave TWO live rows on one id, indefinitely, on a copied
disk. So on a cloned disk the predicate did what its own docstring forbids: it
handed each twin the other's commands, and a Resolve undo addressed to
creator-1 would be replayed against whatever project the clone has open.

A former name is by definition QUIET; a twin is by definition not. The
predicate that already decides this for the adoption (`_previous_row_is_live`,
five minutes, measured on `last_seen`, i.e. the SERVER's `received_at` and
never the companion's clock) moved into `db.machine_row_is_live` and is now
the one rule both sides read - api keeps its `CLONE_ADOPTION_WINDOW_SECONDS`
name and delegates, because `health` imports `db` and not the reverse.
`pending_resolve_undos` gained the `now` its sibling already had, so the quiet
test is measured against the report's own instant.

The cost is stated plainly: inside the first five minutes after a rename the
old name still looks live, so a move outstanding under it is NOT offered until
either it goes quiet (and `adopt_renamed_machine` re-keys the rows, which is
the normal path) or the adoption is refused for good. That is a delay of
minutes on a file lane A would need a pass to undo, against a file move and a
Resolve undo executed on the wrong computer. Under-acting is SYS-18a's own
ruling in the same situation.

### CR-289C (dash-collector-alerts-1) - a cross-cycle pair turned a COPY into a fleet-wide, unattended file move - FIXED (collector.py, db.py)

Within a pass, two halves are one act because they come out of a single
before/after picture of the same projects in the same window.
`pair_across_cycles` dropped that proof and kept pairing on `(basename, size,
mtime_ns)` alone, across up to two days and every project in the fleet - and
the result is not a suggestion: `_record_detected_moves` writes a `file_moves`
row in state DONE, targeted at every machine holding the source, each of which
moves its own copy and relinks Resolve with no admin anywhere in the path. The
act that fakes it is a COPY: an editor duplicates a clip into a second project
(size and mtime survive the copy), the original is deleted a day later, and
the two halves are indistinguishable from a move.

**Corroboration, not a notice, and asked at the moment each half is SEEN.**
The evidence that tells a copy from a move exists only while both copies are
on the NAS: `nas_media` still holds the other one, because the partner project
has not been walked since. By the time the two halves meet, the tree looks the
same either way. So `_the_file_is_also_somewhere_else` asks
`db.media_key_elsewhere` about every fresh half before it is carried, and a
half whose file is also elsewhere is dropped outright - not carried, not
paired - which is exactly the behaviour this product had before the feature
existed. `_one_copy_in_the_tree` asks the same question of the PAIR at pairing
time (a file in three places was never moved out of one of them), and both
halves are consumed when it refuses: evidence the tree contradicts does not
improve by being kept for another two days. A read that fails is not
corroboration - it drops the half and records nothing.

A notice for an admin to confirm was the alternative and was not taken: the
incident CR-285AL was built for (CR-267a) is two days of parked lane B
breakers and lane A re-uploading to the old path, which a notice nobody opens
does not stop. Corroborated pairs still act; uncorroborated ones now do not
exist. The within-pass matcher is untouched - it has its own proof.

`ix_nas_media_identity` on `nas_media(size, mtime_ns)` is added to the v54
block (unshipped) so that query is an index seek and not a full scan of the
fleet's inventory on the collector thread, with the report path waiting on the
same database.

### Verification

Run: `dashboard\.venv\Scripts\python.exe -m pytest tests/test_bug_hunt_2026_09_18b_dashboard_highs.py -q` (8 passed). Six of the eight fail on the tree as the morning left it (measured by reverting the three call sites into a scratch copy of the package and running the same file: 6 failed, 2 passed).

- `tests/test_bug_hunt_2026_09_18b_dashboard_highs.py::test_an_answer_retires_a_move_offered_under_a_former_hostname` -> fails before CR-289A, passes now
- `...::test_an_answer_retires_a_resolve_undo_offered_under_a_former_hostname` -> fails before CR-289A
- `...::test_the_answer_de_dupe_reads_the_row_the_answer_is_written_to` -> fails before CR-289A (the comp-app-2 flood)
- `...::test_a_live_twin_is_never_offered_the_other_computers_commands` -> fails before CR-289B
- `...::test_a_copy_whose_original_is_deleted_later_is_not_a_move` -> fails before CR-289C
- `...::test_a_half_whose_corroboration_cannot_be_read_is_dropped` -> fails before CR-289C
- `...::test_a_real_move_between_two_projects_is_still_paired_across_cycles` -> a GUARD on CR-289C (CR-285AL's own case, with a real inventory under it); passes before and after
- `...::test_a_third_copy_in_the_tree_refuses_the_pair` -> a unit test of the new pairing-time seam (it asserts first that the pairing rules alone would have recorded the move)

Edited: `tests/test_bug_hunt_2026_09_18_dashboard_lows.py::test_a_command_under_a_former_hostname_is_still_offered` - OLD-PC is an hour old there now. It upserted the former name with `now=NOW`, i.e. as a LIVE twin, which is the case CR-289B refuses; the test's own subject (a QUIET former name is still offered) is unchanged and still passes.

Also run, unchanged: `test_bug_hunt_2026_09_18_dashboard_lows.py`, `test_hand_moves_detected.py`, `test_bug_hunt_2026_09_11b_dash_db.py`, `test_bug_hunt_2026_09_18_dashboard_mediums.py` (108 passed), and `test_db.py test_api.py test_invariants.py test_file_moves.py` (139 passed).

### Not fixed
- none

### OWED TO ANOTHER GROUP
- none. All three fixes are inside `dashboard/`, and none of them changes the wire: the companion sends `machine_id` on the report already (res-fleet-4 reads it for the offer), and no field, key or word is added to the report or to the reply.

### Deploy order
- Dashboard alone, any time, in either direction. A companion older or newer than this dashboard is unaffected: a report with no `machine_id` answers under its own hostname exactly as today, and a rollback to the morning's dashboard restores the morning's behaviour with no state left behind (nothing new is written to any row).
- The v54 migration gains one index. A dashboard already migrated to v54 in a dev tree will not re-run the block, so its `nas_media` query falls back to a scan; v54 has shipped nowhere, so no deployment is in that state.

### Owner decisions
- CR-289B costs a few minutes of delay on a command outstanding across a hostname rename (the old name has to go quiet first). Recorded above; the alternative is a cloned disk executing the other computer's Resolve undo.
- CR-289C keeps the cross-cycle move AUTOMATIC when it can be corroborated, rather than downgrading every one to a notice. If the owner would rather see a confirmation on the project page for any move detected across two passes, that is a small change on top of this one (the pair is already refused or accepted in a single place).
