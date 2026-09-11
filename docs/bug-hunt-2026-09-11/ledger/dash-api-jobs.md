## Dashboard API, jobs and the upgrade channel, 2026-09-11 (CR-239)

Ten findings from the 2026-09-11 hunt on `api.py`, the jobs state machine in
`db.py`, and the package/rollback path, plus two pieces owed in from other
territories. Schema v52 (one nullable column on `machines`) is the only
migration in this wave.

### dash-api-3 - [ ROLL THE FLEET BACK ] never delivered anything to anybody - FIXED (schema v52, `api.py`, `db.py`, `ui.py`)

The verifier upgraded this one to high, and it is worse than the hunter
found: the button was a no-op with a green toast, on every fleet, since
REL-16 (2026-09-04) widened the route past vendor recalls. `roll_fleet_back`
queues a per-machine update request; the report handler retires a pending
push when the machine reports a version **at or past** the one asked for (the
dash-core-6 widening, 2026-08-21). A rollback by definition asks for a
version BELOW what the machine is running, so `0.9.66 >= 0.9.64` was true on
that machine's very next report and the request was cleared before
`commands.upgrade` was ever emitted. Nothing was ever told to install
anything. Both existing tests stop at "the request was queued".

The clear rule has learned the push's DIRECTION. `machines.update_requested_from`
(v52) records the version the machine was on when the push was made;
`_update_push_done` clears on "at or past" for an upgrade and on the exact
version for a downgrade. NULL - every row written before v52, and every caller
that does not say - keeps the old behaviour, which is the safe direction for
an upgrade: a fleet mid-deploy must not start re-pushing builds it has
already taken.

The second half is the channel arguing with the rollback. `from_version` is
un-currented now: when the build being rolled off is what this dashboard is
still handing out, `roll_fleet_back` points `current` at the target first, so
a machine that takes 0.9.64 is not offered 0.9.66 again thirty seconds later
(unattended, where `[features] auto_update` is on). Nothing new is bypassed -
the soak gate exists to prove a build the fleet has never run actually runs,
and `ever_current` is evidence this one already earned - and a retracted
target is still refused. The "that is what they are already running" refusal
moved INTO `roll_fleet_back` as well, because the htmx door (`ui.py:3593`)
calls that function directly and a guard in the JSON route covers one of the
two buttons.

### dash-api-2 / dash-release-jobs-1 / res-fleet-1 - a cancelled job came back, and a cancel could be lost entirely - FIXED (`db.py`)

Two defects in the same mechanism, shipped together because they compose:
fixing the second makes more rows carry `cancel_requested_at`, which is the
column the first must honour.

`request_job_cancel` was the one write in the jobs state machine that did not
check `cur.rowcount`. It reads with `get_job`, and that read is genuinely
unlocked - `db.connect` leaves `isolation_level` at the legacy default, so a
bare SELECT runs in autocommit and opens no transaction. A `POST /jobs/claim`
committing in that window turned the queued UPDATE into a no-op: the held
branch never ran, `cancel_requested_at` stayed NULL, and the route answered
`{"ok": true, "state": "failed"}` over a job that ran to completion. It falls
through to the held branch now and returns the state that actually resulted.

`cancel_requested_at` then survived only as long as the lease.
`expire_leases` re-queued the row by lease alone and `queued_jobs` filtered
on `state` only, so an admin who stopped a job on a sleeping laptop had the
cancel discarded, an attempt burned, that machine cooled down and the work
handed to the next capable computer - one machine per retry until the budget
was spent and (for a media kind) the job was PINNED to this container's own
worker. A row carrying the flag goes terminal on expiry now, with
`cancelled` in `last_error`: the holder is gone by definition, so nothing is
being lied about behind a live child. `queued_jobs` and the compare-and-set
both skip a cancelled row as the belt.

### dash-api-1 - a deleted package's 30 days in the trash were counted from its PUBLISH date - FIXED (`api.py`)

`_trash_package_file` moves the file with `source.replace(target)`, which
preserves mtime, and `_prune_package_trash` on the next line deletes
everything under `.trash` older than `PACKAGE_TRASH_DAYS` by mtime. A
package's mtime is its publish time, so any build published more than 30 days
ago was unlinked inside the same call that reported it trashed - and the
route and the audit row both named a path that no longer existed, which is
worse than the silent unlink UX-9 replaced. The trash entry is stamped with
the deletion time now (`target.touch()`, best effort with a WARNING when it
fails). The existing prune test ages the trashed file BY HAND after the
delete, which is exactly the state the real code reached on its own, so it
was green over this; the new test backdates the SOURCE.

### dash-api-5 - a `+dirty` build could never clear a pushed update - FIXED (`api.py`)

`_version_tuple` returned `()` for anything containing a character outside
`0123456789.`, so `0.9.70+dirty` - what `ship.cmd -AllowDirty` produces, and
what the base rig runs after a hotfix - never parsed and never matched. A
push of 0.9.70 to a machine already running a dirty 0.9.70 could not be
cleared: `commands.upgrade` rode every 30 s report for ever and the Packages
page showed a push that could never complete, which is precisely the state
dash-core-6 was raised to end. It parses the NUMERIC PREFIX now; a string
with no numeric prefix at all still returns `()` and still falls back to the
exact-match test.

### dash-api-4 - one computer's queue page showed another computer's Resolve project - FIXED (`api.py`)

`build_queue_view` took a `machine` parameter, used it for
`db.fetch_selections`, and then rebound the same name to
`db.latest_machine_state(conn, editor)` - the PERSON's most recently
reporting computer, whatever it is. So the per-machine page for leso's
MacBook named whatever project was open on the iMac and that machine's
destination root. A named machine reads its own `machine_state` row now; with
no machine named the view is the person's and the newest row stands.

### dash-api-6 - "suspended" meant `/report` and no other door - FIXED (`api.py`)

DCORE-4's suspend deliberately revokes no session and no `cce1.` token, and
`_account_refusal` was called from the report path only. A suspended
freelancer's laptop kept a working fleet credential everywhere else: it could
read the whole sync plan with its project roots, post diagnostics bundles,
and claim, heartbeat and finish fleet jobs that write into the shared vault
under roots it still has mounted. One helper (`_refuse_barred_account`) now
runs on the fleet-jobs gate, both selection gates and `/diagnostics`. The
COMPANION doors only: an admin, or the person signed in, must still be able
to read a suspended editor's plan, because [ RESUME ] has to put back exactly
what was there. It fails OPEN on a database error, like the original, so a
read that cannot answer never locks the fleet out.

### dash-db-4 - the retry guard stopped being a guard past 1,000 rows - FIXED (`db.py`)

`open_retry_of` scanned `list_jobs(state="open", limit=1000)` in Python, and
queued jobs are never aged out on purpose ("a job nobody can run is the thing
phase 0 exists to make visible"). A fleet with a 1,200-deep backlog pushed
the existing retry past the cap, so two clicks on [ TRY AGAIN ] queued the
same encode twice. The open rows are narrowed in SQL first with a LIKE on the
serialised breadcrumb (the spelling is `_job_json`'s own: sorted keys, no
spaces) and the answer is still confirmed in Python against the parsed value.

### dash-release-jobs-3 - the per-kind fleet cap was advisory across concurrent claims - FIXED (`db.py`, `api.py`)

The cap was counted at offer time on the caller's own connection and the
compare-and-set said nothing about it, so two claims arriving in the same
instant both read "three running" and both won: the overshoot equalled the
number of concurrent claims, which is the SMB saturation the cap exists to
stop. `claim_job` takes `max_running` and puts a correlated count of the
held rows of that kind in the same WHERE clause, evaluated inside the write's
transaction; the loser matches no row, exactly as it already does for a
contested id. The claim route passes `jobs.fleet_caps(settings)`, the same
table the offer used. `None` is no cap predicate, which is what every caller
with no fleet settings in hand can honestly ask for.

### comp-app-2 (dashboard side) - nine `resolve_health` fields dropped in silence, and the SYS-3 banner could not see it - FIXED (`api.py`)

`app.resolve_health()` has put `connected`, `project_open`,
`wedged_seconds`, `wedged_call`, `missing_clips`, `non_canonical_refused`,
`proxy_attach`, `proxy_gaps` and `stills` on the wire since 2026-09-04, and
`ResolveHealthIn`'s `extra="ignore"` threw every one away with no error and
no warning. The banner could not see it either: `undeclared_report_sections`
walked one level, and a sub-model with `extra="ignore"` has an empty
`model_extra` by construction. That is SYS-3's FOURTH recurrence.

All nine are declared (with `ResolveClipIn` / `ProxyAttachIn` /
`ProxyGapsIn` / `StillsIn` for the nested shapes), plus `skipped_ever`, which
the companion sends and calls its own tray line. `_BoundedSectionIn` is
`extra="allow"` now, on ReportIn's and SyncGuardIn's stated reasoning, and
`undeclared_report_sections` walks one level INTO `sync_guard`'s sub-models,
so the fifth recurrence announces itself as `sync_guard.<section>.<key>`
rather than waiting for a human to read the source. Nothing reads
`model_extra` except that reporting: an undeclared key is still not stored
and still cannot reach a table.

Declaring is necessary and not sufficient, and the other half landed in the
same wave: `flatten_sync_guard` carries `resolve_health_detail` (the whole
section, `exclude_none=False`, because the latch rule has to be able to see a
field this machine used to answer and does not now), and the report route
calls `db.store_resolve_health_detail`, which keeps it as one `meta` row per
machine. `meta` and not nine more columns: two of the nine are lists of clips
and three are little dicts, a schema number is a shared resource, and nothing
asks about any of it in SQL yet. Same latch rule as its neighbours - a
section that says nothing DELETES the row, because a wedged-call sentence
from last Tuesday is worse than silence. Nothing RENDERS it yet.

### comp-resolve-3 (dashboard side) - the Timeline Cards refusal lost its actionable half - FIXED (`api.py`)

The standalone-agent refusal is 247 characters before `describe_process`
appends the pid and command line, and `CardsAgentIn.detail` was
`max_length=255` on a model that TRUNCATES rather than 422s: RES-7's whole
reason for adding the process description was cut off after eight characters.
The cap is 1000.

### Owed in from other territories

* **server-tools-1** (`/api/v1/health`): `_rollout_block` answers `null` on
  its exception path rather than `[]`, because a ship gate must be able to
  tell "could not compute" from "nothing to report" - it passed on the empty
  list. New `rollout_platforms: {windows: n, macos: n}` counts MACHINES per
  platform from `machine_state` (counts only, no names), so a fleet with
  three Macs and no macOS channel published stops reading as a fleet with no
  Macs. Both optional for an older reader.
* **dash-db-1** (`move_project_files`): the "who has to follow" read passes
  `for_enforce=True`. This reader decides what a COMPUTER is told to do with
  its own copy, not what an admin is shown: a wired machine's tree root IS
  the NAS share, so the rename the dashboard has already made is the only one
  there is, and a `move your copy` command to it is the same file moved
  twice. A wired machine that really does hold the file is still picked up
  from its `editor_media` manifest on the next lines.

### Gate reds, fixed after the central run

Two reds landed in `api.py` from the gate, both of them the SYS-3 guard
working as designed.

`server/tests/test_cross_component.py::test_every_sync_guard_section_the_companion_sends_is_declared`
named `shared_folder_problems` and `repath_events`, which comp-sync-4 gave a
caller this wave: SYNC-101 and SYNC-102's readers had none, so a shared
library that is not working and a project folder this machine MOVED because
an admin renamed it on the server were computed every pass and reached
nobody. Both are declared on `SyncGuardIn` (a bounded list of sentences, and
`RepathEventIn` for the four-key events), with looser caps than the
companion's own 10 so a companion that raises its cap cannot 422 a whole
report against this build. While in there, the same scan by hand found four
more sub-keys the companion sends and no model declared - the test only
walks TOP-LEVEL sync_guard keys, so none of them would have failed it:
`lane_b_breaker.cause` / `.editor_reason` (SYNC-106), the three
`persist_failed` / `persist_error` / `persist_failed_at` keys that
comp-sync-1 adds to `lane_b_breaker`, `halt` and `disk_floor` (a latch that
could not be written to disk is one restart from un-tripping itself),
`trash.path` / `.max_age_days` (plus `retention_days`, `oldest`, `kept`,
`kept_bytes`, `truncated`, `at`) from comp-sync-15, and `ytdlp.sidecar`
(comp-ytdl-jobs-3, `YtdlpSidecarIn`). All declared, none stored.

`dashboard/tests/test_bug_hunt_2026_08_21.py::test_a_two_digit_minor_is_newer_than_a_one_digit_one`
pinned `_version_at_least("0.9.43+dirty", "0.9.43") is False`, which is
exactly what dash-api-5 fixed. The assertion is rewritten to pin the new
rule. Checked first: `api._version_at_least` has ONE caller in the whole
dashboard, the pushed-update clear (`_update_push_done`). The min_version
floor, the "same version, different bytes" refusal and the channel's own
ordering are `release_trust._version_tuple` / `package_store`, untouched, and
the companion's never-roll-back rule is its own code - so nothing anywhere
treats a dirty build as NEWER than the same clean version, and the test now
says so as well (`0.9.43+dirty` is not at least `0.9.44`, and `dev` is not at
least anything).

### Verification

- `dashboard/tests/test_bug_hunt_2026_09_11_dash_api_jobs.py::test_a_trashed_package_is_kept_thirty_days_from_the_DELETE` -> fails at 40f931a, passes now  (dash-api-1)
- `...::test_a_cancelled_job_does_not_come_back_when_the_lease_expires` -> fails at 40f931a, passes now  (dash-api-2 / dash-release-jobs-1)
- `...::test_a_cancel_lost_to_a_concurrent_claim_is_not_reported_as_done` -> fails at 40f931a, passes now  (res-fleet-1)
- `...::test_the_rollback_is_actually_delivered_to_the_machine` -> fails at 40f931a, passes now  (dash-api-3)
- `...::test_the_channel_stops_handing_out_the_build_being_rolled_off` -> fails at 40f931a, passes now  (dash-api-3)
- `...::test_an_upgrade_push_still_clears_at_or_past_the_version_asked_for` -> passes at both; the guard that dash-core-6 is not undone
- `...::test_a_dirty_build_clears_the_push_it_has_already_taken` -> fails at 40f931a, passes now  (dash-api-5)
- `...::test_a_version_with_no_numeric_prefix_still_reads_as_not_past_it` -> fails at 40f931a, passes now  (dash-api-5)
- `...::test_a_named_computers_queue_shows_that_computers_resolve_project` -> fails at 40f931a, passes now  (dash-api-4)
- `...::test_a_suspended_editor_is_turned_away_from_the_fleet_doors_too` -> fails at 40f931a, passes now  (dash-api-6)
- `...::test_the_retry_guard_holds_on_a_queue_deeper_than_a_thousand` -> fails at 40f931a, passes now  (dash-db-4)
- `...::test_the_fleet_cap_is_enforced_by_the_compare_and_set` -> fails at 40f931a, passes now  (dash-release-jobs-3)
- `...::test_the_wave_three_resolve_health_fields_survive_the_wire` -> fails at 40f931a, passes now  (comp-app-2)
- `...::test_a_field_dropped_inside_a_section_is_named_like_a_section` -> fails at 40f931a, passes now  (comp-app-2)
- `...::test_a_report_carrying_the_new_fields_is_still_accepted` -> passes at both; the tolerance guard
- `...::test_the_nine_fields_are_stored_and_read_back` -> fails at 40f931a, passes now  (comp-app-2: stored through `db.store_resolve_health_detail`, and the latch clears it)
- `...::test_the_cards_refusal_keeps_the_process_it_named` -> fails at 40f931a, passes now  (comp-resolve-3)
- `...::test_v52_runs_on_a_last_shipped_database_and_runs_twice` -> fails at 40f931a, passes now  (v52 from 0.7.34/v50, twice, nothing lost)
- `...::test_health_counts_machines_per_platform_and_says_when_it_cannot` -> fails at 40f931a, passes now  (server-tools-1)
- `...::test_a_wired_machine_is_not_told_to_move_its_own_copy` -> fails at 40f931a, passes now  (dash-db-1)

- `server/tests/test_cross_component.py::test_every_sync_guard_section_the_companion_sends_is_declared` -> red on the gate, green now  (comp-sync-4, and four more sub-keys declared with it)
- `dashboard/tests/test_bug_hunt_2026_08_21.py::test_a_two_digit_minor_is_newer_than_a_one_digit_one` -> red on the gate, rewritten to pin dash-api-5's rule, green now

Also run, unchanged and green: `test_jobs.py`, `test_jobs_cancel.py`,
`test_jobs_contract.py`, `test_jobs_backpressure.py`, `test_jobs_pinning.py`,
`test_packages.py`, `test_release_channel.py`, `test_report_endpoint.py`,
`test_sweep_2026_09_04_says_what_it_knows.py`, `test_file_moves.py`,
`test_health.py`, `test_selection_api.py` (285 + 95 passed).

### OWED TO ANOTHER TERRITORY

- `dashboard/src/ccsync_dashboard/ui.py` / templates (dash-mounts-ui): the
  nine wave-3 fields are accepted AND stored now
  (`db.resolve_health_detail(conn, editor, machine)`), and nothing renders
  them. "Resolve is wedged on GetMediaPool, 40 s" and "the attach pass
  refused 12 clips" are a query away from the machine panel.
- `dashboard/src/ccsync_dashboard/db.py` `store_machine_capabilities`
  (dash-db-core): `cap_cards_detail` is truncated to 255 on the way in, so
  comp-resolve-3's raised wire cap buys nothing until that column's write
  (and `ui.py`'s renderer) takes 1000.
- `companion/src/ccsync_companion/timeline_cards_role.py` (comp-resolve): the
  refusal should still truncate DELIBERATELY on its own side and lead with
  the process description - a sentence cut by a wire cap is cut at whatever
  character the cap lands on.
- `dashboard/src/ccsync_dashboard/api.py` `JobsGateIn.detail` carries the same
  255 cap and truncates `check_contract`'s and `load_engine`'s long refusals;
  left alone because no finding names it and the companion side has not been
  measured.

### Owner decisions

- A cancelled job whose lease expires goes to `failed`, and the machine that
  went quiet still earns its cooldown. The alternative (no cooldown, because
  the job was cancelled anyway) loses the evidence that the computer stopped
  answering.
- The rollback un-currents the build being rolled off by making the TARGET
  current, rather than refusing and telling the admin to do it first. It is
  one click instead of two, and the target has already been run by this fleet
  - but it does mean [ ROLL THE FLEET BACK ] now changes what new installs
  download, which the button's copy does not say.
- `/diagnostics` is refused for a suspended editor, like `/report`. An
  operator who wants a bundle from a suspended machine has to press
  [ RESUME ] first.
