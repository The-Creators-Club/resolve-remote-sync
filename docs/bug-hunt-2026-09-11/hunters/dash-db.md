# dash-db - dashboard database layer (db.py, links.py, assignments.py)

Files read (with approximate coverage):
- `dashboard/src/ccsync_dashboard/db.py` (9,918 lines): migration machinery and
  every step script (full), `connect`/WAL/busy-timeout block (full), selections
  + machines + machine_state readers/writers (full), notices, alert_log, jobs
  (create/claim/heartbeat/finish/fail/expire/cooldown/pin), prune/retention,
  media presence + `media_rel_key`, report tokens, evict/forget. Skimmed: the
  companion_packages / feed_state / file_moves / diagnostics / invariant_results
  blocks.
- `dashboard/src/ccsync_dashboard/links.py` (224 lines, full).
- `dashboard/src/ccsync_dashboard/assignments.py` (139 lines, full).
- `git diff 097f5a3..HEAD` for all three (1,430 insertions, read in full for
  db.py's migration + jobs + suspension/archive sections).
- Callers traced out of territory only far enough to judge a finding:
  `collector.py:1300-1400` (`_run_enforce`), `notices.py:525-560`,
  `invariants.py:260-340`, `api.py:196-215`, `app.py:637-645`.

Tests run:
`cd dashboard; .venv\Scripts\python.exe -m pytest tests/test_db.py tests/test_db_write_locks.py tests/test_links.py tests/test_multi_machine.py tests/test_bug_hunt_2026_09_03_dash_db_core.py tests/test_jobs_machines.py -q`
-> **165 passed, 1 skipped** (23 s).

Migration hazard checked directly rather than by reading: I extracted `db.py` +
`schema.sql` from `ec857f2` (dashboard 0.7.28, builds to user_version 46) and
`931c9b2` (dashboard 0.7.34, user_version 50), built a database with each old
build, seeded an editor with a `machine=''` bucket row plus two machine rows,
then ran HEAD's `migrate()` over both. Both reached 51 with `sqlite_master`
byte-identical to a fresh HEAD database and all three `selections` rows intact.
Every step from v45 to v51 is `ALTER TABLE ... ADD COLUMN` or
`CREATE ... IF NOT EXISTS`, `_already_applied` covers the former, and
`migrate()` commits the `user_version` bump inside the same explicit
transaction as the statements, so an interrupt mid-step rolls back cleanly.
**No migration finding.**

## Findings

### dash-db-1 - a WIRED machine's OWN tick still comes out of `fetch_machine_selections`, so a base rig raises a permanent `plan_without_share` ERROR that nobody can clear
- Severity: medium
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/db.py:6570` (`fetch_machine_selections`,
  the `wired` test at :6629 is inside the bucket loop only), with the visible
  consequence at `dashboard/src/ccsync_dashboard/notices.py:532`
  (`_check_plan_without_share`) and `dashboard/src/ccsync_dashboard/invariants.py:270`.
- What: CR-110 dropped the unassigned bucket for wired machines and made
  `selections_for_machine` return `[]` for one, but `fetch_machine_selections`
  filters `base_machines()` only on the bucket-inheritance branch. A wired
  machine that has `selections` rows of its OWN is still reported as holding a
  full tick. The enforce cycle happens to survive this because of CR-110's belt
  (`collector.py:1397` re-filters `plan_rows` against `base_pairs`), but the two
  readers that decide what an admin is TOLD have no such belt.
- Failure scenario: an ordinary editor machine is ticked for `ff5`. Its owner
  later flips it to "wired" in the tray Settings window (CR-88 made that the
  computer's own one-click setting), so its next report writes
  `machine_state.mode = 'base'`. Nothing deletes its `selections` rows. From
  then on: the companion correctly syncs nothing (`selections_for_machine` ->
  `[]`), the enforce cycle correctly makes no share, and
  `notices._check_plan_without_share` writes a **severity `error`** notice on
  the home page's PROBLEMS THE SERVER FOUND - "alex/RIG has ticked ff5 to sync,
  but this server is not sending that project to it. Nothing about it is
  reaching that computer, and the tick looks exactly like it is working." - plus
  a permanently BROKEN invariant row. Its stated fix ("Untick and re-tick that
  project for that computer on its project page") cannot be carried out: the
  tick route 409s on a wired machine. `clear_notices_of_kind` re-asserts it
  every cycle and `db.notice` NULLs `cleared_at`, so [ DISMISS ] does not hold
  either. This is the CR-28 shape (a permanent, uncleanable red state about the
  base rig) reborn on the notices side.
- Evidence: reproduced against a fresh HEAD database from the dashboard venv -
  after `add_selection(..., machine="RIG")` and a `machine_state` row with
  `mode='base'`:
  ```
  base_machines:            {('alex', 'RIG')}
  selections_for_machine:   []
  fetch_machine_selections: {'ff5': [('alex', 'RIG')]}
  ```
  `notices.py:539-551` then has `machine != ANY_MACHINE`, no device/share match,
  and writes the notice; nothing in that function or in
  `invariants._check_plan_without_share` consults `base_machines` / `modes`
  (contrast `invariants.py:324`'s sibling check, which DOES skip
  `modes.get(key) == "base"`).
- Ledger: incomplete fix of **CR-110** (recorded FIXED 2026-09-03, dashboard
  0.7.28); related to CR-28 and CR-88.
- Suggested fix: apply the wired filter to the `own` branch of
  `fetch_machine_selections` too - i.e. skip any `(editor, machine)` in
  `base_machines(conn)` when building `own`, matching
  `selections_for_machine`'s "under-sharing is the safe direction, so both are
  dropped" rule. That fixes all five consumers at once and lets
  `collector.py:1397`'s belt stay as a belt.

### dash-db-2 - a transient `database is locked` reads as "nobody is suspended, nothing is archived", and the enforce cycle re-shares on it
- Severity: low
- Confidence: CONFIRMED (mechanism); PLAUSIBLE that the lock window is reached
  in the field
- Where: `dashboard/src/ccsync_dashboard/db.py:2427` (`suspended_editors`),
  `:2439` (`editor_suspension`), `:2555` (`archived_project_slugs`), `:2573`
  (`fetch_archived_projects`), `:2076` (`fetch_pending_ssh_keys`); consumed at
  `dashboard/src/ccsync_dashboard/collector.py:1322-1323`.
- What: these five swallow **every** `sqlite3.OperationalError` and answer the
  empty/None value. The docstrings justify it as tolerating a pre-v50 database,
  but `db.migrate()` runs at boot on every entry point that then reads them
  (`app.py:640` before the collector is started, `collector.py:297` on its own
  connection), so the missing-column case is unreachable in a running
  dashboard. What the bare `except` actually catches is `database is locked`
  (and `disk I/O error`), and for suspension that is a fail-OPEN of an admin
  control: `collector.py:1322` reads `suspended = db.suspended_editors(conn)` and
  `archived = db.archived_project_slugs(conn)` and filters the plan with them,
  so an empty answer makes that pass re-share every folder the admin just
  suspended or archived.
- Failure scenario: the collector's 20 s busy timeout is exceeded once (a long
  `api_report` write on ZFS, a `VACUUM`-scale pass, a restore drill). That
  enforce cycle computes `plan_rows` with nobody suspended, re-adds the
  suspended editor's device to every folder they still have ticks for, and the
  cycle logs nothing about it - `suspended_editors` is silent by design and the
  addition looks like any other. The next cycle removes them again, so what an
  admin sees is Syncthing churn and a suspended person briefly syncing.
- Evidence: read of the five call sites plus `collector.py:1310-1400`; the
  contrast is `api.py:203-208`, which wraps the SAME call in its own
  `except sqlite3.Error` with an explicit "FAILS OPEN on a database error"
  comment and a `log.warning` - the db.py helpers neither log nor discriminate.
- Ledger: new.
- Suggested fix: narrow the except to the compat case
  (`if "no such column" not in str(exc): raise`), or drop it entirely now that
  migrate always runs first; let the caller that wants fail-open own that
  decision explicitly the way `api.py:203` does, and log when it happens.

### dash-db-3 - `MAX_INCLUDES` bounds the resolution work but not the number of rows a tampered marker creates
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/links.py:39` (the cap's comment) and
  `:206` (`resolve_marker_includes`'s `if i >= MAX_INCLUDES`).
- What: the cap is documented as "a tampered marker must not be able to make
  either unbounded", but the loop does not stop at 32 - it appends an
  `invalid` `LinkResult` for every remaining entry. A marker with 10,000
  `includes` yields 10,000 `LinkResult`s and therefore up to 10,000
  `project_links` rows (the table is keyed `(borrower_slug, declared_path)`, and
  the declared path is attacker-chosen). The companion side is genuinely bounded
  because only `ok` rows are served, but the table, the collector's per-cycle
  write and the shared-folders admin page are not.
- Failure scenario: any editor with write access to the project share (the
  marker is "a plain JSON file on a share every editor can write", per the
  module docstring) drops a marker with a large `includes` array; every
  provision cycle rewrites tens of thousands of rows and the admin page renders
  them all.
- Evidence: read of `resolve_marker_includes` - `kept` is uncapped, and the
  `i >= MAX_INCLUDES` branch `continue`s after appending rather than breaking.
- Ledger: new.
- Suggested fix: `break` after appending one "too many includes" result (or slice
  `kept` to `MAX_INCLUDES` and append a single refusal row), so the row count is
  bounded by the constant the comment promises.

### dash-db-4 - `retry_job`'s duplicate guard silently passes on a queue deeper than 1,000
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/db.py:8957` (`open_retry_of`, which
  calls `list_jobs(conn, state="open", limit=1000)`).
- What: `retry_job` refuses to queue a second attempt at the same job by
  scanning the open queue in Python. The scan is capped at 1,000 rows; queued
  jobs are explicitly never aged out (`prune`'s comment: "queued ones never do,
  because a job nobody can run is the thing phase 0 exists to make visible"), so
  a fleet with a deep backlog can push the existing retry past the cap and the
  refusal becomes a no-op.
- Failure scenario: 1,200 queued `proxy-480p` jobs after a big card dump; an
  admin presses [ TRY AGAIN ] twice on an abandoned job whose retry is row
  1,100 of the open queue. Both clicks create a job, and the fleet does the same
  encode twice (the `.partial` + atomic-rename rule means no corruption, just
  wasted machine time and a doubled queue).
- Evidence: read of `open_retry_of` and `list_jobs`; `prune_jobs` only deletes
  rows in terminal states (`db.py:9629-9640`).
- Ledger: new.
- Suggested fix: make the guard a query rather than a scan - a `LIKE` on
  `inputs_json` narrowed by `state IN (open states)` and then confirmed in
  Python - or at least raise the limit and record a warning when the scan hits
  it, so the refusal cannot silently stop being a refusal.

## Coverage note

- Verified and found clean: the migration machinery (statement splitting via
  `sqlite3.complete_statement`, `_already_applied`, the per-step transaction and
  the `user_version > target_max` rollback refusal), replay from real 0.7.28 and
  0.7.34 databases, `media_rel_key`'s NFC-on-the-way-in rule (both writers use
  it, `file_moves` deliberately keeps raw bytes), `links.normalise_declared`,
  the `notices` `(kind, subject)` upsert and its `lastrowid` fix (CR-110), the
  jobs compare-and-set (`claim_job`, `heartbeat_job`'s refusal to re-claim an
  expired lease, `finish_job`'s deliberate acceptance of a late finish),
  `_job_lease_until`'s timestamp shape against `utcnow_iso()`,
  `job_requirements_met`'s fail-closed fall-through and its correct
  `bool`-before-`int` ordering, the `cce1.` token format (secret never stored,
  `report_token_id` exposing only the public half, no secret in any row or log -
  db.py has exactly one `log.*` call, at :7491, and it formats no secret).
- NOT reached: `file_moves` / `file_move_targets` state machine beyond a skim
  (v29/v36 two-phase retry), `companion_packages` rollout/recall reads,
  `diagnostics`, `invariant_results`, and `resolve_undo_requests`.
- What the suite does not cover: there is no test that a WIRED machine with its
  OWN selections row is excluded from `fetch_machine_selections`
  (`test_bug_hunt_2026_09_03_dash_db_core.py:53` pins only the bucket case), and
  none of the five `except sqlite3.OperationalError` helpers is exercised with a
  locked database - `test_db_write_locks.py` tests contention on the write
  paths, not these reads.
- Not pursued (noted, low confidence, likely out of territory): `dashboard_update.py:776`
  calls `db.migrate()` on its own connection, and `migrate()` reads
  `PRAGMA user_version` BEFORE its `BEGIN`, so two concurrent migrators would
  each replay a step from a stale version. Harmless for v45-v51 (all idempotent)
  but not for a future data-copy step. In the normal single-process boot the
  collector starts after lifespan's migrate, so there is no live race.

## OUT OF TERRITORY
- `dashboard/src/ccsync_dashboard/notices.py:532` and
  `dashboard/src/ccsync_dashboard/invariants.py:270`: neither `_check_plan_without_share`
  skips wired machines, which is what turns dash-db-1 into a visible, uncleanable
  error notice; `invariants.py:324`'s sibling check does skip them.
- `dashboard/src/ccsync_dashboard/db.py` `prune()`: the `notices` table has no
  retention at all. Bounded in practice (one row per `(kind, subject)`, and
  subjects are machine/slug names that are themselves capped and pruned), so not
  filed as a finding, but a cleared notice row lives forever.
