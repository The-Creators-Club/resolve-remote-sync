# CR-300 - the dashboard release/update half of the 2026-09-18b mediums wave - FIXED in repo 2026-09-18 (dashboard_update.py and its tests)

### CR-300A (dash-release-jobs-1) - the restart intent lived only in the file that could not be written - FIXED (`dashboard/src/ccsync_dashboard/dashboard_update.py`)

CR-285S made `request_restart`'s state write best effort so a full or
read-only `/data` could not stop the SIGTERM, and in the same stroke lost the
decision: `consume_restart_request` reads `read_state(settings)`, a pure disk
read, so a swallowed write meant `finish_restart` answered False, uvicorn
exited 0, `run.sh`'s loop saw no 75, and the container went on serving the OLD
code while `current.json` already named the new tree. The fix carries the
intent on a second path no disk can break: a module-level
`_restart_requested_nonce`, set to `PROCESS_NONCE` by `request_restart` BEFORE
the write and OR'd into `consume_restart_request`, which clears it as it
clears the file flag. It holds the nonce rather than a bool so it can never be
read across the re-exec it asks for. The second half of the finding was the
stronger one: `apply` and `rollback` each ran an UNGUARDED
`_set_state(step="restarting", ...)` on the line before `request_restart`, so
the OSError escaped one line EARLIER than the guarded call, `start_apply`'s
generic `except` routed it to the silent `_fail_state`, and no restart was
ever asked for; both calls now pass `best_effort=True`, with a comment saying
why (the swap is already done at that point). Two tests: one drives
`request_restart` then `finish_restart` with a writer that raises `OSError(30)`
throughout and asserts exit 75 and that a second shutdown does NOT claim to be
a restart; one drives the real `rollback` end to end with a writer that fails
PART WAY (the state file only, which no earlier case did) and asserts the
signal fired and the process can still exit 75. `test_dashboard_update.py`'s
`test_a_restart_request_left_by_a_DEAD_process_is_spent_not_honoured` needed
one line: it fakes a dead owner by rewriting the nonce on disk, so it must
clear the in-memory carrier too or it is pretending to be two processes at
once.

### CR-300B (tests-1) - the only test for dash-release-jobs-5 re-implemented the fixed expression - FIXED (`dashboard/tests/test_bug_hunt_2026_09_18_dashboard_mediums.py`, `dashboard_update.py`)

`test_reapplying_the_running_version_keeps_the_rollback_target` wrote a
`current.json`, read it back and then evaluated a COPY of `apply`'s arithmetic
in the test body, so reverting the `apply` hunk left it green and the branch
the fix actually added (`carried == version`) was never reached. The three
lines are now a named helper, `dashboard_update._carry_previous(held,
version)`, called by `apply` on the line the fix lives at, with the
dash-release-jobs-5 reasoning moved into its docstring and the three-way
result (the superseded version, the held one, or `""` for the image) called
out, because `rollback` and `deploy/select_code_root.py` both read `""` as the
image. The test now drives that real function from a real `current.json` on
disk for all three branches and additionally pins that `apply` calls it
(`inspect.getsource`), so the only way to pass without guarding the fix is to
take the call out. Verified red on the reverted arithmetic
(`carried = previous if previous != version else ""`).

### Verification
- CR-300A: `test_the_restart_intent_survives_a_disk_that_never_took_the_note` and `test_a_rollback_whose_state_write_fails_still_asks_for_the_restart` both FAIL on the reverted source (in-memory flag removed, two `_set_state` guards removed) and pass after.
- CR-300B: `test_reapplying_the_running_version_keeps_the_rollback_target` FAILS with `apply`'s arithmetic reverted and passes after.
- `dashboard/.venv/Scripts/python.exe -m pytest tests/test_dashboard_update.py tests/test_bug_hunt_2026_09_11b_dash_release_jobs.py tests/test_bug_hunt_2026_09_18_dashboard_mediums.py tests/test_release_feed.py tests/test_release_channel.py -q` -> 229 passed.
- `py_compile` clean on `dashboard_update.py`.

### Not fixed
- Nothing in this group's assignment. dash-release-jobs-2 was REFUTED by the verifier and dash-release-jobs-3 (the same defect as tests-1, from the other hunter) is covered by CR-300B's helper.

### OWED TO ANOTHER GROUP
- None. Both fixes are inside `dashboard_update.py` and its own tests.

### Deploy order
- Dashboard only, no wire change. The in-memory flag and the two `best_effort`
  guards are process-local; a rollback to an older dashboard tree simply
  returns to the previous behaviour, and no companion, feed or state file
  format changed. `update_state.json` is written and read exactly as before.

### Owner decisions
- None needed.
