# dash-api - the dashboard's JSON API surface (api.py: report, commands, packages/upgrade channel, selections, file moves, jobs, halt, site, admin)

Files read (with approximate coverage):
- `dashboard/src/ccsync_dashboard/api.py` (9,992 lines) - full read of the auth
  helpers (lines 55-240), the scope/redaction block (1178-1300), `/verify` +
  `_require_fleet_member` (1960-2135), the selection gates and tick/untick
  (2136-2560), `_require_admin` (3161-3178), the account disable/suspend and
  report-token routes (4143-4870), halt + per-machine command routes
  (4869-5260), the package helpers, publish, make-current, roll-back, delete
  and download (5306-6340), the report model and `api_report` end to end
  (6338-9058), `/diagnostics` + ask-why (9059-9200), and the whole jobs block
  (9486-9992). Skimmed the project/link/move/tree routes (2561-3660) and the
  admin user/device routes (3660-4143).
- `git diff 097f5a3..HEAD -- api.py` (+1666/-239) hunk list, read in full for
  the jobs, packages, roll-back, suspend and command-delivery hunks.
- Callees verified rather than assumed: `db.version_tuple`, `db.queued_jobs`,
  `db.claim_next_job`, `db.expire_leases`, `db.request_job_cancel`,
  `db.pending_job_cancels`, `db.pending_file_moves`, `db.fetch_selections`,
  `db.get_fleet_halt`, `db.queue_depth`.
- Both sides of two wire formats: `companion/src/ccsync_companion/jobs_runner.py`
  (`note_report_reply`, `wait_seconds`), `companion/src/ccsync_companion/app.py`
  (`_maybe_auto_update`, `_resolve_journals`), `resolve_journal.summaries`,
  `reporter.py`'s section assembly.
- Tests: `dashboard/tests/test_packages.py`, `test_release_channel.py`,
  `test_sweep_2026_09_04_says_what_it_knows.py`, `test_no_em_dash.py`,
  plus the ones run below.

Tests run:
`cd dashboard; .venv\Scripts\python.exe -m pytest tests/test_packages.py tests/test_report_endpoint.py tests/test_jobs.py tests/test_jobs_cancel.py tests/test_jobs_contract.py tests/test_upload_only.py tests/test_selection_api.py tests/test_file_moves.py tests/test_fleet_halt.py tests/test_site.py -q`
-> **259 passed, 1 skipped** (baseline green; every finding below is on a path
the suite does not exercise).

Also run: three ad-hoc reproductions from the dashboard venv (scratchpad), one
per CONFIRMED finding - output quoted inline.

## Findings

### dash-api-1 - a deleted package's "30 days in the trash" is measured from when it was PUBLISHED, so most deletes destroy the rollback bytes instantly
- Severity: medium
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/api.py:5341` (`_trash_package_file`) and
  `dashboard/src/ccsync_dashboard/api.py:5366` (`_prune_package_trash`); the same
  helper is the htmx door's (`ui.py:3835`).
- What: `_trash_package_file` does `source.replace(target)` into
  `<data>/packages/.trash/<platform>/`, and a rename PRESERVES the file's mtime.
  `_prune_package_trash`, called on the very next line of the same function,
  deletes everything under `.trash` whose `st_mtime` is older than
  `PACKAGE_TRASH_DAYS * 86400`. So the retention clock is the build's PUBLISH
  time, not its deletion time: any package published more than 30 days ago is
  unlinked in the same call that claims to have trashed it - and the route still
  answers `trashed_to: <path>` for a file that no longer exists.
- Failure scenario: an admin tidies the Packages page and deletes companion
  0.9.64 (published five weeks ago) to make room. UX-9's whole promise ("those
  are the bytes a rollback to that version needs") is void: the file is gone the
  instant it is trashed, the JSON answer and the audit row both name a path that
  does not exist, and the next incident that wants 0.9.64 back has to re-fetch
  and re-sign it from the vendor feed.
- Evidence (dashboard venv, scratchpad):
  ```
  f = packages/windows/ccsync-companion-0.9.1.exe   # mtime set to 40 days ago
  api._trash_package_file(S(), row)
  -> ('...\\packages\\.trash\\windows\\2026-09-11T031546+0000-ccsync-companion-0.9.1.exe', None)
  trash contents: [WindowsPath('.../packages/.trash/windows')]      # EMPTY
  ```
  The three existing tests cannot see it: `test_delete_moves_the_file_to_dot_trash_rather_than_unlinking`,
  `test_json_delete_uses_the_same_trash_as_the_partial` and
  `test_delete_prunes_only_trash_older_than_the_configured_age`
  (`tests/test_packages.py:305-365`) all delete a package published seconds
  earlier, and the third ages the trashed file BY HAND with `os.utime` - which
  is exactly the state the real code reaches on its own.
- Ledger: new. UX-9 (KNOWN_BUGS line 6562-6564) records "prunes trashed files
  older than PACKAGE_TRASH_DAYS = 30 by mtime" as the intended design, so this
  is the design being wrong rather than a regression.
- Suggested fix: `target.touch()` (or `os.utime(target, None)`) right after the
  `replace`, so the trash entry's mtime is the DELETION time; or stamp the
  deletion time into the filename (it already is - `db.utcnow_iso()`) and prune
  by parsing that prefix rather than by mtime. Add a test that backdates the
  SOURCE file before deleting it.

### dash-api-2 - cancelling a job a sleeping machine holds does not cancel it: the lease expires, the row goes back on the queue with the cancel flag still set, and another machine runs it
- Severity: medium
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/api.py:9825` (`api_cancel_job`) ->
  `db.request_job_cancel` (`db.py:9585`), `db.expire_leases` (`db.py:9247`),
  `db.queued_jobs` (`db.py:8884`), `db.claim_next_job` (`db.py:9088`).
- What: `request_job_cancel` on a CLAIMED/RUNNING job only stamps
  `cancel_requested_at` and leaves the row in its state - correct, per the
  docstring ("nothing here forces the row terminal behind a live ffmpeg"). But
  `expire_leases` re-queues that row (`state=queued`, holder cleared) without
  ever looking at `cancel_requested_at`, and neither `queued_jobs` nor
  `claim_next_job` filters on it. A cancel therefore survives only as long as
  the machine holding the job keeps its lease.
- Failure scenario: the exact case the route's own docstring names - "an admin
  clicking [ CANCEL ] while a laptop is asleep must not be a click that
  evaporates". The laptop is asleep, so it never reads `commands.jobs.cancel`;
  `JOB_LEASE_SECONDS` passes; the next `POST /jobs/claim` from anyone runs
  `expire_leases`, re-queues the job, burns an attempt, cools down the laptop,
  and hands the job to the next capable machine, which starts ffmpeg on it.
  That machine is then told to cancel on its next report (30 s later), so the
  job ping-pongs machine to machine, one attempt at a time, until the retry
  budget is spent - at which point a media job is PINNED to the dashboard's own
  worker. Nothing an admin can see says the cancel was undone.
- Evidence (dashboard venv, scratchpad, `db` only - no HTTP):
  ```
  claim: True
  cancel: requested
  expired: [1]
  state now: queued   cancel_requested_at: 2026-09-11T00:00:00+00:00
  in queued_jobs: [1]
  re-claimed by another machine: 1 claimed
  ```
- Ledger: new (phase-4 cancel, 2026-08-30). `tests/test_jobs_cancel.py` passes
  and does not cover a cancel that outlives its lease.
- Suggested fix: in `expire_leases`, a row with `cancel_requested_at` set goes
  to `failed` (`JOB_CANCELLED_ERROR`) rather than back to `queued` - the holder
  is gone, so there is no live child to lie about. Belt and braces: add
  `AND cancel_requested_at IS NULL` to `queued_jobs`.

### dash-api-3 - [ ROLL THE FLEET BACK ] silently undoes itself when the build being rolled off is still CURRENT (and with auto_update on, within one report)
- Severity: medium
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/api.py:6114` (`roll_fleet_back`) and
  `:6174` (`api_roll_fleet_back`); the other side is
  `dashboard/src/ccsync_dashboard/api.py:5493` (`_upgrade_info`) and
  `companion/src/ccsync_companion/app.py:6977` (`_maybe_auto_update`).
- What: `roll_fleet_back` queues a per-machine update request for every machine
  on `from_version` and does nothing else. It never un-currents `from_version`,
  and `api_roll_fleet_back` does not refuse (or warn) when `from_version` is the
  channel's current build. Once a machine reports the rolled-back version, the
  report handler clears the pending request (correct, dash-core-6), and from the
  NEXT report `_upgrade_info` falls back to the channel's current package - the
  build that was just rolled off - and offers it again.
- Failure scenario: REL-16's documented headline use - "Put the fleet back on
  0.9.64 after a bad ship nobody recalled". `POST /admin/packages/windows/0.9.66/roll-fleet-back?to=0.9.64`
  with 0.9.66 still current. Every machine takes 0.9.64, reports it, the push
  clears, and 30 s later each one is offered 0.9.66 again. On a site with
  `[features] auto_update` on, `_maybe_auto_update` sees 0.9.66 as NEWER and
  re-installs it unattended - the fleet is back on the bad build inside a minute
  and the admin has a green toast saying the rollback worked. With auto_update
  off, every editor gets an update toast for the build the admin just recalled
  by hand.
- Evidence (dashboard venv, scratchpad, `_upgrade_info` directly):
  ```
  with the push still pending, running 0.9.64 -> None
  next report, push cleared, running 0.9.64 -> offered 0.9.66
  ```
  `tests/test_sweep_2026_09_04_says_what_it_knows.py:346`
  (`test_the_rollback_works_without_a_recall`) pins exactly this scenario and
  stops at "the request was queued" - it never asks what the next report offers,
  so the suite is green over the bug (brief rule 7).
- Ledger: new (REL-16, 2026-09-04, widened the route from recall-only).
- Suggested fix: make the fan-out and the channel state one operation - when
  `from_version` is current, `roll_fleet_back` should make `to_version` current
  first (it has already checked the target is published and not retracted), or
  refuse with a sentence telling the admin to make `to_version` current before
  rolling back. Anything less is a rollback the channel immediately argues with.

### dash-api-4 - MY QUEUE for one named computer shows a DIFFERENT computer's open Resolve project and destination root
- Severity: low
- Confidence: CONFIRMED (code); the rendering side is `ui.py`, outside this territory
- Where: `dashboard/src/ccsync_dashboard/api.py:1803` (`build_queue_view`),
  specifically line 1874 `machine = db.latest_machine_state(conn, editor)` -
  the caller is `ui.py:1353`, which passes `machine=target`.
- What: `build_queue_view` takes a `machine` parameter, uses it correctly for
  `db.fetch_selections`, and then REBINDS the same name to
  `db.latest_machine_state(conn, editor)` - the person's most recently reporting
  computer, whatever it is. `resolve_project`, `root_slug`, `root_label` and
  `root_source` in the returned view therefore describe that machine, not the
  one the page is about.
- Failure scenario: leso has an iMac and a MacBook. The per-machine queue page
  for the MacBook says "Resolve project: <whatever is open on the iMac>" and
  names the iMac's destination root. An admin reading it to answer "is this
  laptop pointed at the right project root" is told about the wrong computer.
  Harmless on a single-machine editor, which is why nobody has hit it.
- Evidence: read - the parameter is shadowed at `api.py:1874` after its last
  legitimate use at `api.py:1829`, and `db.latest_machine_state` takes no
  machine argument. No test passes `machine=` to `build_queue_view`.
- Ledger: new (the `machine=` parameter arrived with WP2 per-machine plans).
- Suggested fix: rename the local (`state = db.latest_machine_state(...)`) and,
  when a machine was named, read that machine's `machine_state` row instead of
  the person's newest one.

### dash-api-5 - a `+dirty` companion version can never clear a pushed update
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/api.py:5413` (`_version_tuple`) and
  `:5428` (`_version_at_least`), used at `:8799` in the report reply.
- What: `_version_tuple` returns `()` for anything containing a character
  outside `0123456789.`, and `_version_at_least` then falls back to an exact
  string compare. A machine running a `+dirty` build (what
  `ship.cmd -AllowDirty` produces, and what the base rig runs after a hotfix)
  reports e.g. `0.9.70+dirty`, which never equals and never parses above the
  requested `0.9.70`.
- Failure scenario: an admin pushes 0.9.70 to the base rig, which already has a
  dirty 0.9.70. The request is never cleared: `commands.upgrade` rides every
  30 s report for ever, the companion logs "IGNORED" once, and the Packages page
  shows a push that can never complete - which is precisely the state dash-core-6
  was raised to end, for a version shape that fix did not consider.
- Evidence: read plus `_version_tuple("0.9.70+dirty") == ()`; the exact-match
  fallback at `:5435` is the only remaining branch.
- Ledger: new. The dash-core-6 fix (code comment at `api.py:8794`) widened
  the clear from "exactly it" to "at or past it" but did not consider a
  version string that will not parse.
- Suggested fix: compare on the numeric prefix - strip at the first character
  outside the dotted-numeric set before `_version_tuple`, so `0.9.70+dirty`
  reads as `(0, 9, 70)`. Keep the exact-match fallback for anything with no
  numeric prefix at all.

### dash-api-6 - a SUSPENDED editor's machines are turned away by /report but not by the jobs, selection, diagnostics or package routes
- Severity: low
- Confidence: PLAUSIBLE (the exploitable half depends on stale `machine_state`
  surviving long enough to produce an offer; I did not reproduce it end to end)
- Where: `_account_refusal` (`api.py:193`) is called from `api_report`
  (`api.py:8396`) and from `_require_fleet_member` (`api.py:1988`, local mode
  only). It is called from NONE of `_require_fleet_caller` (`api.py:9486`),
  `_require_selection_read` (`api.py:2232`), `_require_selection_untick`
  (`api.py:2303`), `api_diagnostics` (`api.py:9060`) or `_require_package_read`
  (`api.py:6242`).
- What: DCORE-4's suspend is described as "the report path turns their computers
  away ... and the enforce cycle removes their Syncthing shares", and
  `api_admin_suspend_user` deliberately revokes no session and no `cce1.` token.
  The consequence is that a suspended person's companion keeps a working fleet
  credential for every route except `/report`: it can still read its sync plan
  (`GET /selection/{editor}`, which includes the project roots), still download
  published companion packages, still post diagnostics bundles, and still
  `POST /jobs/claim` / `heartbeat` / `result`.
- Failure scenario: a freelancer is suspended at the end of a contract. Their
  laptop keeps polling; `GET /selection/<them>` keeps answering the full plan
  and the sticky Resolve-project-to-root map. If the scheduler still produces an
  offer for that machine from its last-stored capabilities, the machine can
  claim a fleet job and write its output into the shared vault under the roots
  it still has mounted.
- Evidence: read - `_account_refusal` has exactly two call sites in the file
  (`grep -n "_account_refusal" api.py` -> 193, 1988, 8396). The suspend route's
  own docstring states that nothing is revoked.
- Ledger: related to DCORE-4 (2026-09-04).
- Suggested fix: call `_account_refusal` from `_require_fleet_caller` and
  `_require_selection_read`/`_require_selection_untick` too (it already fails
  OPEN on a database error, so it cannot lock the fleet out). It is one line per
  gate and makes "suspended" mean the same thing on every door.

## Coverage note

Read but not exhaustively chased, and therefore NOT cleared:
- `move_project_files` / `undo_file_move` / `reconcile_file_moves`
  (`api.py:2674-3010`) - I verified the command's re-delivery contract
  (`db.pending_file_moves` is bounded by delivery, not age, and a delivered
  target only stops riding when `file_moves_applied` answers or
  `expire_delivered_file_moves` ages it out) but did not trace the filesystem
  half (proxy siblings, cross-device renames, the NFC/NFD comparison).
- `create_tree_project` / `adopt_folder` / `_safe_rel` / `_raise_if_container_of_projects`
  (`api.py:3277-3660`) - the path-traversal surface. Skimmed only.
- `api_publish_package`'s signature-verification tail lives in `package_store`
  (another territory); I read the route's framing and the `.part` staging (which
  looks correct - per-request uuid name, threadpool writes, running byte total)
  but not the store.
- The admin user/device/SSH-key routes (`api.py:3660-4143`, `4292-4706`) were
  skimmed for auth gates only.

Checks that came back CLEAN and are worth recording:
- **No em dash** anywhere in `api.py` (byte scan for U+2014/U+2013: zero hits),
  and `tests/test_no_em_dash.py` walks the AST of every `.py` in the package, so
  HTTP `detail` strings are genuinely covered.
- **Per-editor `cce1.` binding**: every companion-facing route that takes an
  identity claim re-checks `token_editor == editor` - `/report` (8328),
  `/diagnostics` (9088), selection read (2249) and untick (2320), and the fleet
  gate (9527). Shape-first resolution in `resolve_companion_credential` means a
  `cce1.` token is never compared against the shared secret.
- **`?machine=` absent means the PERSON**: `_machine_arg` correctly refuses to
  let a URL reach `db.ANY_MACHINE`; tick fans out with
  `add_selection_for_person`, untick removes everywhere including the unassigned
  bucket.
- **Base rig cannot hold a tick**: both the per-person (`base_only_editors`) and
  the per-machine (`base_machines`) 409s are present on `api_tick` AND on
  `api_copy_machine_plan`.
- **`JOBS_QUEUE_DEPTH_MIN_VERSION`**: `db.version_tuple` is numeric-per-part, so
  0.10.0 > 0.9.9 compares correctly; the gate and the companion's
  `wait_seconds` agree on "absent depth is the base cadence".
- **`sync_modes`**: every reader in api.py that decides what comes DOWN asks for
  `(db.SYNC_MODE_FULL,)` (`api.py:552`).
- **Fleet halt**: always present in the reply in both states, expiry evaluated
  on read, corrupt value reads as NOT halted.

## OUT OF TERRITORY
- `dashboard/src/ccsync_dashboard/db.py:6512` (`fetch_selections`, union branch):
  the person-level union dedupes by slug and keeps whichever row comes first, so
  the `sync_mode` it reports for a project ticked `full` on one computer and
  `upload_only` on another is arbitrary. Harmless today (a companion old enough
  to omit `?machine=` is also too old to read `sync_mode`), but it is a
  coin-flip an upload-only invariant could later be built on.
- `dashboard/src/ccsync_dashboard/ui.py:1353`: the render side of dash-api-4.
