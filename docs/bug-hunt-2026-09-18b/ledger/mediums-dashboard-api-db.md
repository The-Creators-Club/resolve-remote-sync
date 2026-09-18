# CR-297 - Dashboard api/db mediums - FIXED in repo 2026-09-18 (3 of 3)

### CR-297A (dash-api-2) - one transient inventory error excluded a project for ever - FIXED (dashboard/src/ccsync_dashboard/db.py)

`record_inventory_error` upserted `walked_at` and `last_error` and left
`tree_sig` standing. The collector's phase 1 skips the whole walk when the
directory signature matches the stored one, and `_dir_signature` is directory
mtimes only, so an archived project (the normal case, nothing in it is
changing) never produces a different signature again. One blink of the share
therefore stuck `last_error` on the row permanently: `last_error` is cleared
in exactly one place, the successful `replace_nas_media` upsert, which the
skip guarantees is never reached, and there is no admin re-walk route. Downstream
`locate`'s `COALESCE(s.last_error,'') = ''` filter then excluded the project
for ever, which the companion's lane guard reads as "those files are gone" -
the lane B breaker parks and only a human can clear it. The fix clears
`tree_sig` in that upsert (the verifier's smaller of the two shapes), which
forces exactly one re-walk; the cost for a project that really is still
unmounted is one `is_dir()` per cycle, before any `os.walk`. The test runs a
real collector cycle, renames the project dir away for one cycle and back
(a rename does not touch the mtimes inside the tree, so the signature that
returns is the same one), and asserts `last_error` is cleared by the third
cycle.

### CR-297B (dash-db-3) - the admin's MOVE button kept its own unescaped copy of the predicate - FIXED (dashboard/src/ccsync_dashboard/api.py)

dash-db-4's LIKE escaping (`_like_prefix` + `ESCAPE '\'`) was applied to
`db.file_move_target_machines`, whose only caller is the collector's DETECTED
hand-move path, while the admin MOVE route carried a byte-for-byte duplicate
of the same plan pass and manifest query with a raw `media_key + "/%"`. So the
path CR-267a added was escaped and the path the button runs was not: moving
`Gold_Card_Meetup` still matched a machine holding `Gold-Card-Meetup` (`_` is
a single-character wildcard) and sent it a `commands.file_moves` entry for a
file it does not hold - a harmless answer from the companion, a wrong
per-machine progress row on the project page. The route now calls the helper,
which the verifier diffed as identical in every other respect; the duplicate
query and its now-unused `media_key` local are gone (the verifier expected a
later use of `media_key` in the route, but it has none - grep confirms one
occurrence before the change and none needed after). The test drives the POST
route, not the helper, which is what the existing dash-db-4 test could not do.

### CR-306 (dash-api-3) - a push that could not be sent still cost the machine every job kind for 14 days - FIXED (dashboard/src/ccsync_dashboard/db.py, api.py, jobs.py, templates/partials/admin_packages.html)

Taken in a second pass the same day, once `jobs.py` was free. res-fleet-2's
withhold arm leaves the request standing on purpose (the build may become
offerable again), but `jobs.fleet_facts`/`machine_facts` read `upgrading` from
`machines.update_requested_version` alone and `policy_refusal` answers
`REFUSE_UPGRADING` before any capability, so a push nothing could deliver took
that computer out of the whisper/proxy/audio-extract/peaks fleet for the whole
14 days of `MACHINE_UPDATE_REQUEST_MAX_AGE_DAYS`.

The hunter's first suggestion (ask `_machine_can_be_offered` from jobs.py)
cannot be built - it needs the report payload, and `machines` has no arch - so
the verifier's shape was built instead: schema v55 adds
`machines.update_requested_withheld`, the report handler writes the real
`_upgrade_info` sentence into it when it withholds the command (and clears it
in the send arm, so the command and the return to "upgrading" ride one reply),
`request_machine_update` / `clear_machine_update_request` /
`expire_machine_update_requests` all null it, and both job readers consume it
failing CLOSED - NULL or '' is undecided, which is still upgrading. The
Packages page renders `[ CANNOT BE SENT ]` with the reason and says the
computer still takes jobs; [ CANCEL ] is the withdraw action it already had.
`policy_refusal` and the `/why` wording are untouched.

### Verification
- dash-api-2: `test_a_project_that_could_not_be_read_once_is_walked_again` - fails on the reverted `record_inventory_error` (last_error still set after the share returns), passes after.
- dash-db-3: `test_the_move_button_does_not_claim_a_lookalike_folders_machines` - fails on the reverted route (DESK-1 in `machines`), passes after.
- dash-api-3: `test_a_withheld_push_no_longer_costs_the_machine_every_job`, `test_the_flag_clears_the_moment_the_build_is_offerable_again`, `test_withdrawing_or_expiring_a_push_clears_the_verdict`, `test_the_packages_page_names_a_push_that_cannot_be_sent` (view dict AND the rendered partial), `test_v55_adds_the_withheld_column`.
- `dashboard\.venv\Scripts\python.exe -m pytest tests/test_bug_hunt_2026_09_18b_dashboard_api_db.py tests/test_bug_hunt_2026_09_18_dashboard_mediums.py tests/test_db.py tests/test_multi_machine.py tests/test_release_channel.py tests/test_packages.py tests/test_jobs*.py tests/test_bug_hunt_2026_09_11*_*jobs.py -q` -> 516 passed, 1 skipped; the schema-version readers (`test_dashboard_update.py`, `test_bug_hunt_2026_09_11b_dash_mounts_ui.py`, `test_bug_hunt_2026_09_18_dashboard_lows.py`) -> 111 passed.
- `py_compile` on api.py, db.py, jobs.py, locate.py.

### OWED TO ANOTHER GROUP
- Nothing. dash-api-3's `jobs.py` half, the only thing this group owed anyone, is included above.

### Deploy order
Dashboard only; no wire change, no companion change. Schema v55 is one
nullable column. The two 2026-09-18 fixes are read-side behaviour on the
dashboard's own database, so a rollback is safe: the cleared `tree_sig` only
costs an older build one extra walk, and the move route reverts to its own
copy of the query. CR-306 fails closed in both directions - an older dashboard
ignores the column and keeps refusing jobs to that machine exactly as today,
and a v55 dashboard reads a pre-v55 row as undecided, i.e. upgrading.

### Owner decisions
None needed.
