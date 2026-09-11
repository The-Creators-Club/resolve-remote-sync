# dash-db - db.py, links.py, assignments.py, runtime_id.py and the v40..v52 migrations

Files read (with approximate coverage):
`dashboard/src/ccsync_dashboard/db.py` (the whole 40f931a..HEAD diff hunk by
hunk; migration machinery 1737-2005; the suspension/archive readers 2466-2630;
the machine-update group 4699-5110; the jobs state machine 8840-9930; the
report-health writers 6286-6500 and 8744-8800; ~60% of the 10,204 lines),
`links.py` (100%), `assignments.py` (100%), `runtime_id.py` (100%),
plus the both-sides readers of what db.py writes: `api.py` (`_account_refusal`,
`_update_push_done`, `api_push_machine_update`, `api_claim_job`, the report
handler's clear rule), `ui.py` (the two per-machine push routes),
`collector.py` (the enforce cycle, `_timed`'s fault isolation, `_run_links`),
`notices.py` / `invariants.py` (the `for_enforce` callers),
`dashboard/tests/test_bug_hunt_2026_09_11_dash_db_core.py`, `test_links.py`,
`test_bug_hunt_2026_09_03_dash_db_core.py`.

Tests run:
- `cd dashboard; .venv\Scripts\python.exe -m pytest tests/test_links.py tests/test_bug_hunt_2026_09_11_dash_db_core.py tests/test_bug_hunt_2026_09_03_dash_db_core.py -q` -> 86 passed, 1 skipped.
- Scratch migration harness (scratchpad only, no live database): built a v50
  database with `git show 931c9b2:...db.py` + its `schema.sql` (dashboard
  0.7.34) and a v46 one with `a4b296a` (dashboard 0.7.29), then ran the
  CURRENT `migrate()` over both, twice. Result: both reach v52, the replay is
  a no-op, `machines.update_requested_from` is present, `PRAGMA
  integrity_check` = ok. **No migration finding: v40..v52 are gapless,
  replayable and forward-clean from both field shapes.**
- Scratch probes of `claim_job`'s new cap predicate, `request_job_cancel` ->
  `fail_job`, `resolve_marker_includes` scaling, and `_update_push_done`
  against a real v52 database (outputs quoted below).

## Findings

### dash-db-1 - the per-machine [ UPDATE NOW ] push still cannot deliver a rollback: dash-api-3 landed on the fleet route only
- Severity: high
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/db.py`:4699-4730 (`request_machine_update`, `from_version: str = ""` default), and the three callers that never pass it: `dashboard/src/ccsync_dashboard/api.py`:5163 (`POST /admin/machines/{editor}/{machine}/update`), `dashboard/src/ccsync_dashboard/ui.py`:3623 and `ui.py`:3689 (the Packages page's per-machine push)
- What: v52 and `_update_push_done` exist because "at or past the version
  asked for" retires a DOWNWARD push before `commands.upgrade` is ever
  emitted. The fleet route (`roll_fleet_back`, api.py:6331) passes
  `from_version=`; the three per-machine push routes do not, so their rows
  carry NULL, `machine_update_request` normalises that to `""`, and
  `_update_push_done` falls back to the old upgrade rule. The direction of a
  push is derivable from state the dashboard already holds
  (`machine_state.companion_version`), so defaulting it to "" is what makes
  the omission silent.
- Failure scenario: a build goes bad, the admin re-currents the previous one
  (CLAUDE.md: "republishing an older build is a first-class rollback"), then
  clicks [ UPDATE NOW ] next to one machine on Settings -> Packages. That
  route pushes `current["version"]` (ui.py:3689), which is now BELOW what the
  machine runs. The row is written, the admin gets `{"ok": true}` and a green
  partial, and on that machine's very next 30 s report the request is cleared
  with `"... is on v0.9.71 (asked for v0.9.70) -- the pushed update is done"`
  in the log. `commands.upgrade` is never emitted. Same for the canary path in
  `api_push_machine_update` when the staged build named is older than the one
  the canary is running.
- Evidence: scratch v52 DB, real functions:
  `request_machine_update(conn,"ed","LAP","0.9.70","admin",NOW)` ->
  `{'version': '0.9.70', ..., 'from_version': ''}`;
  `_update_push_done(row, "0.9.71")` -> **True** (retired, undelivered).
  The same call with `from_version="0.9.71"` -> `False` (delivered). No test
  in `test_bug_hunt_2026_09_11_dash_api_jobs.py` exercises the per-machine
  route's direction.
- Ledger: CR-247/dash-api-3 does not fix `dash-api-3` for the per-machine push routes (the fleet route is fixed)
- Suggested fix: give `request_machine_update` no way to be wrong - when
  `from_version` is empty, read the machine's last reported
  `companion_version` from `machine_state` inside the function and store
  that. One seam, and every caller (api.py, ui.py x2, any future one) is
  correct by construction.

### dash-db-2 - a cancelled job re-queued by an older companion becomes a permanently unclaimable `queued` row that still counts in the queue depth
- Severity: medium
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/db.py`:9089 (`queued_jobs`, new `AND cancel_requested_at IS NULL`) and 9306 (`claim_job`, same predicate) versus `db.py`:9445-9475 (`fail_job`, which sets `state=JOB_QUEUED` without consulting `cancel_requested_at`)
- What: dash-api-2/dash-release-jobs-1 closed the "a cancelled job comes back
  when the lease expires" hole in `expire_leases` (which now goes terminal)
  and belted `queued_jobs`/`claim_job`. But `fail_job(retryable=True)` is a
  third route from a held state back to `queued`, and it was not taught the
  rule. The resulting row is `queued` with `cancel_requested_at` set: invisible
  to `queued_jobs`, refused by `claim_job`, and never terminal.
- Failure scenario: an admin cancels a running proxy job on a companion in the
  field on 0.9.65..0.9.70, which predates `commands.jobs.cancel` and so never
  reports "cancelled, not retryable". That companion's ffmpeg fails for its own
  reason and it reports an ordinary retryable failure. The row parks in
  `queued` for ever: it appears on the jobs page as queued, and
  `queue_depth()` reports `queued: 1` with `oldest_age_s` growing without
  bound on every report reply - which is exactly the backpressure signal
  CLAUDE.md says the companion backs off on ("STOP ASKING"). A fleet with
  nothing to do looks like a fleet with a permanent backlog. The admin can
  recover only by pressing cancel a second time, and nothing tells them so.
- Evidence: scratch v52 DB -
  `request_job_cancel` -> `requested`; `fail_job(..., retryable=True)` ->
  `queued`; `queued_jobs()` -> `[]`; `claim_next_job()` -> `None`;
  `queue_depth()` -> `{'queued': 1, 'running': 0, 'pinned': 0,
  'oldest_age_s': 0.0}`; `finished_jobs()` -> `[]`.
- Ledger: CR-247/dash-api-2 (dash-release-jobs-1) opens this neighbour; new
- Suggested fix: in `fail_job`, when the row carries `cancel_requested_at`,
  force `state = JOB_FAILED` with the `JOB_CANCELLED_ERROR` prefix regardless
  of `retryable` - the same rule `expire_leases` just learned. Optionally have
  `queue_depth` count only rows `queued_jobs` would return, so the two answers
  can never disagree.

### dash-db-3 - dash-db-3's cap bounds the ROWS but not the WORK: `resolve_marker_includes` is still quadratic in a tampered marker
- Severity: medium
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/links.py`:192-213 (the two dedupe loops, which run over the FULL parsed list before the `MAX_INCLUDES` break at 220), reached from `collector.py`:767 (`_run_links`, every cycle) and `api.py`:3131
- What: the fix moved the cap to the results loop, but `parse_includes` and
  both dedupe passes still run over every declared entry first: `declared in
  ordered` is a list membership scan and the nested-include check is a
  `next(o for o in ordered ...)` inside a loop over `ordered`. Both are
  O(n^2). `provision.read_marker_data` puts no size limit on the marker file,
  so n is whatever an editor writes. MAX_INCLUDES' own comment promises "a
  tampered marker must not be able to make either unbounded".
- Failure scenario: any editor writes a ~700 KB `.ccsync-project` with 20,000
  `includes` entries on a project share (they all have SMB write access; the
  marker is the file this module says nothing in is trusted). Every provision
  cycle then spends 23 s of CPU on that one marker inside the collector's
  guarded loop, holding its connection; a 100,000-entry marker (about 3 MB)
  is roughly ten minutes per cycle. The collector is the thing that tells
  everyone whether their footage is syncing.
- Evidence: measured against the real function with a nonexistent projects dir
  (so the time is all in the dedupe, none in the filesystem):
  1,000 entries -> 0.05 s; 5,000 -> 1.13 s; 20,000 -> 22.87 s; results
  correctly bounded at 33 each time. The new regression test
  (`test_a_marker_with_thousands_of_includes_yields_a_bounded_number_of_rows`)
  itself spends ~1 s in this loop and asserts only on `len(results)`, so it
  passes while the cost is still unbounded.
- Ledger: CR-240/dash-db-3 does not fully fix `dash-db-3`
- Suggested fix: truncate `paths` to a hard ceiling (e.g. `MAX_INCLUDES * 4`)
  right after `parse_includes`, and make the exact-duplicate pass use a `set`
  and the nesting pass a sorted single scan. A byte cap in
  `provision.read_marker_data` would bound the whole class.

### dash-db-4 - the enforce cycle, the reader `for_enforce` is named for, does not pass it
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/db.py`:6727-6745 (the docstring: "`for_enforce=True` is the view for anyone deciding what SHOULD be happening on a machine") versus `dashboard/src/ccsync_dashboard/collector.py`:1317 (`db.fetch_machine_selections(conn, sync_modes=(db.SYNC_MODE_FULL,))`, no flag)
- What: `notices._check_plan_without_share` and
  `invariants._check_plan_has_share` were switched to `for_enforce=True`; the
  enforce cycle itself was not, and survives only on CR-110's separate
  `base_pairs` / `base_editors` belt further down the same function. So the
  two answers to "what should this machine hold" are computed by two different
  rules and agree only because a second filter happens to exist. The next
  hand to touch either side has nothing telling it they must match.
- Failure scenario: no wrong behaviour today (I traced the belt at
  collector.py:1321-1341 and it covers the `own` branch as well as the
  bucket). A future edit to the belt, or a new consumer written from the
  docstring, reintroduces the CR-110/B16 shape.
- Evidence: `grep -rn "fetch_machine_selections"` - four callers with
  `for_enforce=True` (api.py:2799, invariants.py:278 and :577, notices.py:537)
  and the enforce cycle is not one of them.
- Ledger: related to CR-110 (fixed) / CR-28
- Suggested fix: pass `for_enforce=True` at collector.py:1317 and keep the
  belt as belt, or say in the docstring that the enforce cycle deliberately
  filters later and why.

### dash-db-5 - dash-db-2's raise reaches two display-only admin pages, which now 500 on a transient lock
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/db.py`:2466/2480/2598/2618/2113 (the five readers that now re-raise a lock) reached unguarded from `dashboard/src/ccsync_dashboard/assignments.py`:126 (`fetch_archived_projects`) and `dashboard/src/ccsync_dashboard/api.py`:3829-3833 (`_build_admin_users_view`: `suspended_editors`, `editor_suspension`, `fetch_pending_ssh_keys`)
- What: the fix is right where the empty answer was a fail-OPEN (the enforce
  cycle) - and `api._account_refusal`:204 correctly catches `sqlite3.Error`
  and fails open for the report path. But the two ADMIN PAGE readers gain no
  safety from raising: they only render. A `database is locked` (a documented
  recurring condition here, 2026-09-03) now 500s the Users page, which is the
  only place [ RESUME ] and the pending-SSH-key approval live, and the
  assignments grid, which is where [ UNARCHIVE ] lives.
- Failure scenario: the collector is mid-write during a slow Syncthing cycle,
  the admin opens /admin/users to resume a suspended editor, and gets a 500
  instead of the page carrying the button that fixes the thing they came for.
- Evidence: read both call sites; neither is inside a `try`. Compare
  `api._account_refusal`, which the same hunter's note cites as "the caller
  that wants fail-open owns that decision explicitly" - the page readers were
  not given that decision.
- Ledger: CR-240/dash-db-2 opens this neighbour; new
- Suggested fix: wrap the three reads in `_build_admin_users_view` and the one
  in `_assignments_view` in `try/except sqlite3.OperationalError`, rendering
  the page with a "could not read this right now" strip rather than a 500.

## Coverage note
- Not reached: the `broll_*` / `music_*` / diagnostics / audit halves of db.py,
  `fetch_sync_backlog`'s manifest arithmetic, and the completion/lane tables -
  none of them changed since 40f931a.
- The v52 migration is proven forward-clean from the two real field shapes
  (v50 = dashboard 0.7.34, v46 = 0.7.29) and replay-safe, but there is no
  automated test in the suite that migrates an OLD build's database with the
  CURRENT code; the harness above exists only in my scratchpad. A standing
  `test_migrations.py` of that shape would be worth having (there is none -
  `ls dashboard/tests | grep migrat` is empty).
- Verified and NOT findings: `claim_job`'s new correlated fleet-cap predicate
  holds exactly (5 claims against a cap of 2 -> `[1, 2, None, None, None]`);
  `claim_next_job`'s per-job write attempt is bounded by `allowed_ids` from
  `offers_for_machine`, so the cap predicate cannot turn a deep backlog into a
  write storm; `open_retry_of`'s LIKE prefilter cannot produce a false
  negative (`_job_json` fixes the spelling) and its false positives are
  re-confirmed in Python; `fetch_collector_status`'s new `stale` is computed
  from `MAX(started_at)` and is correct for a wedged cycle too; the
  dash-db-2 raise is fault-isolated in the collector by `_timed` and
  explicitly caught in `api._account_refusal`.
- `runtime_id.py` and `assignments.py` had no defect I could substantiate.
- What the suite does not cover: the direction of a per-machine update push
  (dash-db-1), any route from a held state back to `queued` other than
  `expire_leases` (dash-db-2), and the COST rather than the row count of a
  hostile marker (dash-db-3).

## OUT OF TERRITORY
- `dashboard/src/ccsync_dashboard/provision.py`:298 - `read_marker_data` puts no size limit on `.ccsync-project`, so the whole marker of any size is read and json-parsed on every cycle; this is the root of dash-db-3's remaining cost.
- `dashboard/src/ccsync_dashboard/ui.py`:3689 - the per-machine [ UPDATE NOW ] partial pushes `current["version"]` with no check that it is newer than what the machine runs, and reports success either way (the other side of dash-db-1).
