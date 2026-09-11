## The dashboard database: a move expiry that never read the answer, a liveness bound no Syncthing-less deployment could meet, a rollback push that forgot which way it pointed, and a cancelled job's third way back onto the queue (CR-258, 2026-09-11)

### CR-258A (comp-app-1 / regression-18) - a machine answering "retrying" every thirty seconds was still expired as never having answered - FIXED (`dashboard/src/ccsync_dashboard/db.py`)

comp-sync-20 taught the companion to answer `state="retrying"` while the sync
drive is out, on the stated ground that the dashboard "EXPIRES it after 7 days
of told and never answered". The dashboard never read `state`:
`expire_delivered_file_moves` selected on `applied_at IS NULL AND expired_at
IS NULL AND delivered_at < cutoff`, and the retrying arm of
`mark_file_move_applied` writes only `state`, `attempts`, `last_error` and
`detail` - no `applied_at`, no refreshed `delivered_at`. So the companion half
of that fix landed and the dashboard half did not: an editor away for a
fortnight with the drive in their bag had file move #7 delivered on day 1,
answered every report, and stamped `expired_at` on day 8 anyway.
`pending_file_moves` filters on `expired_at IS NULL`, so the command stopped
being offered; the drive came back on day 15, lane A (which never deletes)
re-uploaded the file at the OLD path, and the move was undone on the server -
the exact failure `docs/FILE_MOVES.md` exists to prevent.

The expiry now measures SILENCE rather than age: a target whose state is
`retrying` is spared for as long as its machine is still reporting, judged on
`machine_state`'s server-side `received_at` (never the companion's clock)
against the same 7 day cutoff. A machine that answered once and then vanished
still expires, and a target that never answered at all is untouched by the
change. `COALESCE(t.state, '')` in the predicate is load-bearing: a NULL state
compared to `'retrying'` is NULL, and `NOT (NULL AND 1)` is NULL, which would
have quietly spared every target that has never answered.

### CR-258B (dash-collector-alerts-1) - a Syncthing-less deployment reported its own healthy collector as STOPPED, for ever - FIXED (`dashboard/src/ccsync_dashboard/db.py`)

dash-collector-alerts-3 was right that liveness is the START of a cycle of any
kind and wrong to keep measuring it against a flat 180 s. A deployment with no
`syncthing_url` runs only `SYNCTHING_FREE_KINDS` - prune (3600 s), invariants
(900 s), alerts (600 s) - so the newest start on a perfectly healthy collector
is normally ten minutes old and `collector_stale` was permanently True.
`_check_collector_stale` is an `error` kind: within ten minutes of boot, every
vendor, zero-touch and bare dev dashboard said "The server's background
collector has not completed a cycle" on PROBLEMS THE SERVER FOUND, counted it
in the topbar's red chip and mailed it daily. At 40f931a `reachable` was False
on such a site so the flag was never computed at all; this was a new false
positive, one commit old.

`db.collector_stale_bound(conn, floor)` now reads the bound off the
collector's own observed rhythm - the shortest gap between two consecutive
starts of the same kind, doubled, floored at `COLLECTOR_STALE_SECONDS` and
capped at two hours - and `fetch_collector_status` measures the newest start
against that. A collector that has actually stopped still ages past it (a
bound, not a gate), at the cadence the deployment really runs at; a
Syncthing-backed site, whose fastest kind cycles in tens of seconds, keeps the
180 s constant; a container with no kind that has run twice keeps the floor,
because one run says nothing about cadence.

### CR-258C (dash-db-1 / res-fleet-1) - the per-machine [ UPDATE NOW ] still could not deliver a rollback - FIXED (`dashboard/src/ccsync_dashboard/db.py`)

v52's `update_requested_from` exists because "at or past the version asked
for" retires a DOWNWARD push before `commands.upgrade` is ever emitted. Only
`roll_fleet_back` passed it. The three per-machine doors - `POST
/admin/machines/{editor}/{machine}/update`, `[ PUSH TO ONE MACHINE ]` and its
"update to current" twin on Settings -> Packages - left the default `""`,
which `machine_update_request` normalises to `""`, which `_update_push_done`
reads as an upgrade. So an admin who re-currented the previous build (a
first-class rollback, per CLAUDE.md) and clicked [ UPDATE NOW ] next to the
one unhappy machine got `{"ok": true}`, a green partial, and a request cleared
on that machine's next 30 s report with nothing delivered and nothing on the
page or in the log saying so. That is the canary-rollback case REL-1's soak
flow depends on, and the one an admin reaches for before a fleet-wide recall.

`request_machine_update` now looks the direction up itself: with no
`from_version` from the caller it reads that machine's last reported
`companion_version` from `machine_state` and stores that. One seam, so api.py,
ui.py x2 and any fourth door are correct by construction. An explicit
`from_version` still wins (the fleet route knows what it is rolling back
from), and a machine that has never reported a version leaves the column NULL,
which is exactly the pre-v52 behaviour. Upward and same-version pushes are
unchanged: `_update_push_done` only takes the rollback branch when the
requested version is strictly below the one recorded.

### CR-258D (dash-db-2 / regression-3) - a cancelled job re-queued by an older companion became a permanently unclaimable row that still counted as backlog - FIXED (`dashboard/src/ccsync_dashboard/db.py`)

dash-api-2 closed "a cancelled job comes back when the lease expires" in
`expire_leases` and belted `queued_jobs` and `claim_job` with `AND
cancel_requested_at IS NULL`. `fail_job(retryable=True)` is the THIRD route
from a held state back to `queued` and was not taught the rule. A companion on
0.9.65..0.9.70 predates `commands.jobs.cancel`, so it never reports
"cancelled, not retryable" - it reports whatever its ffmpeg did. The row then
parked in `queued` carrying `cancel_requested_at`: invisible to `queued_jobs`,
refused by `claim_job`, never terminal, rendered on the jobs page as queued,
and counted by `queue_depth` with `oldest_age_s` growing without bound - which
is the backpressure signal the companion backs off on. A fleet with nothing to
do looked like a fleet with a permanent backlog, and the only recovery was to
press cancel a second time with nothing saying so.

`fail_job` now reads the row's `cancel_requested_at` (via `SELECT *` and
`_row_value`, so a database that predates the column reads as "not
cancelled") and forces `JOB_FAILED` with the `cancelled` prefix regardless of
`retryable` - the same rule `expire_leases` learned - and skips the machine
cooldown, since the machine that could not be told to stop must not be
punished for obeying late. `queue_depth` now counts and ages only the rows
`queued_jobs` would return, so the two answers can no longer disagree.

### CR-258E (dash-db-3 / regression-22) - the includes cap bounded the rows and left the work quadratic - FIXED (`dashboard/src/ccsync_dashboard/links.py`)

CR-240's fix moved the cap to the results loop, so a tampered marker could no
longer make `project_links` rows without bound. `parse_includes` and both
dedupe passes still ran over every declared entry first: `declared in ordered`
is a list scan, and the nesting check was a `next(o for o in ordered ...)`
inside a loop over `ordered`. Measured against the real function: 1,000
entries 0.05 s, 5,000 1.13 s, 20,000 22.9 s. `provision.read_marker_data` puts
no size limit on the marker, every editor can write the share, and `_run_links`
runs this on every provision cycle inside the collector's guarded loop holding
its connection - and the collector is the thing that tells everyone whether
their footage is syncing. CR-240's own regression test asserted only on
`len(results)`, so it passed while the cost stayed unbounded.

Three changes: `MAX_INCLUDE_ENTRIES` (four times the row cap) truncates the
parsed list before any dedupe, the exact-duplicate pass is a `set`, and the
nesting pass is one sorted scan with a stack of open ancestors. The sort key
is the path plus its separator, NOT the bare path: `a!` sorts between `a` and
`a/b`, so on bare keys the descendants of a declaration are not contiguous and
`a/b` would escape its ancestor. The refusal row still names the marker's OWN
declared total rather than what survived the entry cap - that number is how
big the file on the share is, which is the tampering worth seeing.

### CR-258F (dash-db-4) - the enforce cycle does not pass the flag the reader is named for - DOCUMENTED, fix OWED (`dashboard/src/ccsync_dashboard/db.py`)

`fetch_machine_selections`'s docstring calls `for_enforce=True` "the view for
anyone deciding what SHOULD be happening on a machine", and
`collector._run_enforce` - the cycle that decides exactly that - does not pass
it. It survives only on CR-110's separate `base_pairs`/`base_editors` belt
further down its own function, so the two answers to "what should this machine
hold" are computed by two rules and agree only because a second filter happens
to exist. No wrong behaviour today (the belt covers the `own` branch as well
as the bucket); the defect is that the next hand to touch either side has
nothing telling it they must match. The docstring now says so, names the belt
and says the two must change together. The one-line call-site change is OWED
to dash-collector-alerts (collector.py is theirs).

### CR-258G (dash-db-5) - the archive read's new raise reached a display-only admin page - FIXED (`dashboard/src/ccsync_dashboard/assignments.py`)

CR-240's dash-db-2 made the five suspension/archive readers re-raise a
`database is locked` instead of answering the empty value, which is right
where the empty answer was a fail-OPEN (the enforce cycle re-sharing folders
an admin had just suspended). The admin PAGE readers gain no safety from
raising: they only render. `_assignments_view` calls `fetch_archived_projects`
unguarded, so a lock during a slow collector write 500s the assignments grid -
the page carrying [ UNARCHIVE ], which is what the admin came for. That read
is now guarded on its own: an empty list plus `archived_unreadable`, so the
page says "could not read this right now" instead of stating as fact that
nothing is archived. The `_build_admin_users_view` half (three reads in
api.py, the page where [ RESUME ] and the pending-SSH-key approval live) is
OWED to dash-api, and the strip that renders the flag is OWED to
dash-mounts-ui; until it lands the grid renders with no archived section,
which is the pre-CR-240 behaviour rather than a 500.

### Verification
All in `dashboard/tests/test_bug_hunt_2026_09_11b_dash_db.py`, run with
`dashboard\.venv\Scripts\python.exe -m pytest tests/test_bug_hunt_2026_09_11b_dash_db.py -q`
(17 passed; 9 of them fail against f1eeb42's db.py/links.py/assignments.py,
the other 8 are the controls that must keep passing).

- `::test_a_machine_still_answering_retrying_is_not_expired` -> fails at f1eeb42, passes now (comp-app-1)
- `::test_a_machine_that_went_silent_while_retrying_still_expires` -> control: the clock still measures silence
- `::test_a_machine_that_never_answered_at_all_still_expires` -> control: the original UX-5 case
- `::test_a_syncthing_less_collector_turning_normally_is_not_stale` -> fails at f1eeb42, passes now (dash-collector-alerts-1)
- `::test_a_fast_deployment_keeps_the_three_minute_floor` -> fails at f1eeb42 (no such function), passes now
- `::test_a_collector_that_has_actually_stopped_is_still_stale` -> control: the bound widens, it does not go away
- `::test_a_per_machine_push_records_the_version_the_machine_is_on` -> fails at f1eeb42, passes now (dash-db-1); asserts through the real `api._update_push_done`
- `::test_an_explicit_from_version_still_wins` / `::test_a_machine_that_has_never_reported_a_version_keeps_the_old_shape` -> controls
- `::test_a_cancelled_job_an_old_companion_fails_retryably_goes_terminal` -> fails at f1eeb42, passes now (dash-db-2)
- `::test_the_queue_depth_counts_what_the_scheduler_would_hand_out` -> fails at f1eeb42, passes now (dash-db-2)
- `::test_an_ordinary_retryable_failure_still_comes_back` -> control: an uncancelled failure still re-queues
- `::test_a_tampered_marker_cannot_buy_unbounded_work` -> fails at f1eeb42 (20.9 s for one call), passes now (dash-db-3)
- `::test_the_refusal_still_names_how_many_the_marker_declared` / `::test_nesting_and_duplicates_collapse_exactly_as_before` -> controls on the rewritten dedupe
- `::test_the_assignments_grid_renders_when_the_archive_read_is_locked` -> fails at f1eeb42, passes now (dash-db-5)
- `::test_the_grid_still_lists_archived_projects_when_the_read_works` -> fails at f1eeb42 (no flag), passes now

Also run, unchanged and green, because they read the functions touched:
`test_links.py`, `test_file_moves.py`, `test_jobs.py`, `test_jobs_cancel.py`,
`test_jobs_retry.py`, `test_jobs_backpressure.py`, `test_db.py`,
`test_release_channel.py`, `test_admin_assignments.py`, `test_collector.py`,
`test_alerts.py`, `test_health.py`,
`test_bug_hunt_2026_09_11_dash_db_core.py`,
`test_bug_hunt_2026_09_11_dash_collector_alerts.py` (478 passed, 2 skipped).

### OWED TO ANOTHER TERRITORY
- dash-collector-alerts: `collector.py`: `_run_enforce` (line ~1317): pass `for_enforce=True` to `db.fetch_machine_selections(conn, sync_modes=(db.SYNC_MODE_FULL,))` and keep CR-110's `base_pairs`/`base_editors` belt as a belt (dash-db-4). Dashboard-only, no deploy ordering.
- dash-collector-alerts: `alerts.py`: `_collector_started_recently`: it compares against the flat `db.COLLECTOR_STALE_SECONDS`, which is the same false positive CR-258B fixes one layer down - it is the OTHER way `_check_collector_stale` can fire. Use `db.collector_stale_bound(ctx.conn)` instead of the constant (it takes the floor as its argument). Dashboard-only.
- dash-api: `api.py`: `_build_admin_users_view` (lines ~3829-3833): wrap `suspended_editors`, `editor_suspension` and `fetch_pending_ssh_keys` in `try/except sqlite3.OperationalError` and render the Users page with a "could not read this right now" strip rather than 500ing (dash-db-5). Dashboard-only.
- dash-mounts-ui: `dashboard/templates/admin_assignments.html`: render an "the archived list could not be read right now" strip when the new `archived_unreadable` context key is true (dash-db-5). Harmless if never rendered; dashboard-only.

### Owner decisions
- CR-258A spares a `retrying` target while its machine is REPORTING (the
  server's `received_at`), rather than sparing every retrying row for ever or
  bumping `delivered_at` on each answer. Bumping `delivered_at` would have
  been one line, but that column is also the project page's "how long has
  this machine been owed this" chip, and a move that has been outstanding for
  a fortnight would have rendered as thirty seconds old. No schema change was
  needed; v53 is still unused.
- CR-258B derives the staleness bound from the collector's own observed
  cadence rather than importing the interval settings (db.py cannot import
  collector.py) or gating the flag on `syncthing_url` (db.py has no settings).
  The visible consequence: on a Syncthing-less deployment a genuinely stopped
  collector is now reported after about 20 minutes instead of 3. If the owner
  would rather have the flag gated on the deployment shape, that belongs in
  alerts.py next to `_check_nas_engine`'s twin gate.
- CR-258E drops marker entries past 128 unread. A marker whose first 128
  entries are all duplicates of each other would previously have found
  distinct folders further down; that is not a shape an editor writes by
  hand, and the alternative is leaving the collector's CPU bounded only by
  what an editor can type into a file on the share.
- CR-258C stores the machine's last REPORTED version as the push's
  `from_version`. If a machine upgraded itself and has not reported since,
  that value is stale and the push reads as an upgrade - which is exactly the
  behaviour before v52, so nothing regresses, but it means a rollback aimed
  at a machine that is offline right now can still be retired when it comes
  back on a newer build than the dashboard last saw.
