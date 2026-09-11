# dash-api - the dashboard's JSON API, packages/upgrade channel, settings, provisioning, local users

Files read (with approximate coverage): `dashboard/src/ccsync_dashboard/api.py`
(the whole `git diff 40f931a..HEAD` hunk by hunk, ~100%; plus the surrounding
package/upgrade/rollback, report-model, selection-gate, jobs-claim and
health-block regions in full, ~35% of the 10k-line file), `provision.py`
(100%), `settings.py` (the diff plus `__post_init__`, ~40%),
`package_store.make_current_refusal` (100%), `local_users.py` /
`android.py` (skimmed, untouched since 40f931a), plus the callees the diff
reaches: `db.set_current_package`, `db.request_machine_update`,
`db.machine_update_request`, `db.expire_machine_update_requests`,
`db.claim_next_job`, `db.store_resolve_health_detail`,
`db.record_ignored_report_sections`, `db.rollout_status`, `db.forget_machine`,
`ui.py`'s three `build_queue_view` callers,
`templates/partials/{my_queue,queue_section,fix_root}.html`,
`tools/ship_gates.ps1` (the rollout gate),
`companion/sync/lane_guard.py` (`_persist_report`) and
`companion/jobs_runner.py` (result/heartbeat status handling).

Tests run:
`dashboard\.venv\Scripts\python.exe -m pytest tests/test_bug_hunt_2026_09_11_dash_api_jobs.py tests/test_packages.py tests/test_api.py tests/test_multi_machine.py -q`
-> 142 passed.
`dashboard\.venv\Scripts\python.exe -m pytest tests/test_jobs_backpressure.py tests/test_jobs_cancel.py tests/test_fleet_scope.py tests/test_hardening.py tests/test_android.py tests/test_local_users.py tests/test_release_channel.py -q`
-> 200 passed.
Two ad-hoc scripts in the scratchpad (a pytest module run against the dashboard
venv, and a one-liner against the report models); both outputs quoted below.

## Findings

### dash-api-1 - the rollback button is a sixth door into "make current", and it walks past the gate
- Severity: high
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/api.py:6304-6320` (`roll_fleet_back`), against `dashboard/src/ccsync_dashboard/package_store.py:172-242` (`make_current_refusal`) and `dashboard/src/ccsync_dashboard/db.py:3977-3983`
- What: the dash-api-3 fix added `db.set_current_package(...)` straight into
  `roll_fleet_back`, which is the one call `db.set_current_package`'s own
  docstring forbids ("New callers go through `package_store.make_current`,
  never here") and which `make_current_refusal`'s docstring already counts as
  one of the five doors it gates ("the roll-back button"). The in-line comment
  justifies it with "`ever_current` is the evidence this one already earned" -
  but nothing on this path reads `ever_current`; `db.set_current_package` only
  *sets* it. So the REL-1 soak gate, the UX-9 unsigned-binary confirmation and
  the REL-4 `requires_dashboard` ordering check are all bypassed for any
  published, non-retracted version an admin types into `?to=`.
- Failure scenario: two windows companion rows exist, 0.9.66 (current) and a
  0.9.64 that was hand-published with no release signature and has never been
  current. `POST /admin/packages/windows/0.9.64/current` is refused 409 ("has
  no release signature ... making it current stops EVERY computer in the fleet
  from updating, silently"). `POST /admin/packages/windows/0.9.66/roll-fleet-back?to=0.9.64`
  makes exactly that version current, with no confirmation and no refusal.
  Every companion then verifies the record signature on the offer, refuses it,
  and the whole platform stops updating with nothing on any page saying why -
  UX-9's scenario, reachable again by one click. The `requires_dashboard`
  variant is worse in a quieter way: `_upgrade_info` re-applies REL-4 and
  returns None, so the channel offers nothing at all to every machine on that
  platform, including new installs.
- Evidence: scratch pytest module in the scratchpad (`t_gate.py`), run from
  `dashboard/.venv`, with `release_soak_minutes=600`:
  `ever_current: 0 signature: ''`, then
  `rollback: {'ok': True, ..., 'uncurrented': '0.9.66'}` and
  `db.get_current_package(conn,'windows')['version'] == '0.9.64'` - the
  unsigned, never-current build is current. The front door refuses the same
  version with `409 ... has no release signature`.
- Ledger: new (regression of UX-9 / REL-1 / REL-4 through a new door; opened by the CR-239 fix for dash-api-3)
- Suggested fix: call `make_current_refusal(conn, settings, kind=kind,
  platform=platform, version=to_version)` before re-pointing, and on a refusal
  either raise it or do the fan-out and leave `current` alone with the refusal
  reported in the response. `roll_fleet_back` needs `settings` passed in, which
  both of its callers already hold.

### dash-api-2 - the new undeclared-key walker is blind to the five sync_guard sections where this afternoon's dropped fields actually lived
- Severity: medium
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/api.py:8441-8464` (`_nested_extra_keys`), `api.py:6961-6985` (`_BoundedSectionIn`), and the models at `api.py:6988` (`BreakerIn`), `7019` (`TrashIn`), `7040` (`HaltIn`), plus `SkippedExistsIn` and `RemovalOverrideIn`
- What: `_nested_extra_keys` can only see an undeclared key on a sub-model that
  keeps its extras, i.e. one whose `model_config` is `extra="allow"`. Only
  `_BoundedSectionIn` was switched; five of `SyncGuardIn`'s sub-models are
  plain `BaseModel` (pydantic default `extra="ignore"`) and still drop
  undeclared keys with an empty `model_extra`. Those five are `lane_b_breaker`,
  `halt`, `trash`, `skipped_exists` and `removal_overrides` - exactly the
  sections whose silently-dropped fields comp-sync-1 (`persist_failed`,
  `persist_error`, `persist_failed_at`) and comp-sync-15 (`path`,
  `retention_days`, ...) were raised about this afternoon. The detector was
  taught to see the recurrence in `resolve_health` and left blind to the
  recurrence in the three models the same fix pass was patching.
  Second half: those five do not inherit `_bound_rather_than_reject` either, so
  a value over a declared `max_length` 422s the WHOLE report instead of
  truncating - the SYS-3 shape. Today's companion caps `persist_error` at a
  short path string, so that half is latent, but `editor_reason` (1000) and
  `reason` (1000) on `BreakerIn` are free text.
- Failure scenario: the next field the companion adds to `sync_guard.breaker`,
  `.halt` or `.trash` (the three latches an editor's safety depends on) is
  dropped by the dashboard exactly as silently as the last three were - no
  warning, no `meta` row, nothing on the SYS-3 banner - and the only way
  anybody finds out is another hunt.
- Evidence: `.venv\Scripts\python.exe -c "... api._nested_extra_keys('sync_guard.', api.SyncGuardIn(breaker={'tripped':True,'zzz':1}))"`
  -> `[]`, while the same call for `resolve_health={'brand_new_key':...}` ->
  `['sync_guard.resolve_health.brand_new_key']`. Enumerating
  `SyncGuardIn.model_fields` for sub-models whose
  `model_config.get('extra') != 'allow'` prints the five named above.
- Ledger: CR-239 / comp-app-2 does not fix comp-app-2's own generalisation ("a field dropped inside a section is exactly as invisible as a whole section")
- Suggested fix: make `BreakerIn`, `TrashIn`, `HaltIn`, `SkippedExistsIn` and
  `RemovalOverrideIn` subclass `_BoundedSectionIn` (they get extra="allow" and
  the truncate-rather-than-reject validator in one change), and add a test that
  asserts every `SyncGuardIn` sub-model is a `_BoundedSectionIn`, so the next
  model added cannot be silent by default.

### dash-api-3 - dash-api-4's per-machine queue fix is unreachable from any page that renders the thing it fixes
- Severity: medium
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/api.py:1918-1933` (`build_queue_view`), `dashboard/src/ccsync_dashboard/ui.py:649`, `ui.py:925`, `ui.py:1396`, `dashboard/templates/partials/{my_queue,queue_section,fix_root}.html`
- What: the fix scopes exactly two outputs to the named machine -
  `resolve_project` and `root_slug`/`root_label`/`root_source` (`machine` was
  already threaded into `db.fetch_selections` before it). Those keys are read
  by ONE template, `partials/fix_root.html`. The only caller that passes
  `machine=` is `ui.py:1396`, the tick POST's re-render, which returns
  `partials/my_queue.html` - a template that does not reference
  `resolve_project`, `root_slug` or `root_source` at all. The two callers that
  do render `fix_root.html` (the home page at `ui.py:649` and the 10 s
  `/partials/queue` poll at `ui.py:925`) still pass no machine, so they still
  show `db.latest_machine_state(editor)`: whichever of the person's computers
  reported last.
- Failure scenario: leso signs in with an iMac and a MacBook. The MacBook is in
  front of him; the iMac reported 20 s ago. [ FIX DESTINATION ROOT ] on the
  home page still says "open in Resolve: THE IMAC PROJECT -> <that machine's
  detected root>", which is the exact sentence dash-api-4 reported, and
  pressing the button there still pins the root the wrong computer detected.
- Evidence: `grep -rn "build_queue_view(" dashboard/src/ccsync_dashboard` gives
  the three callers above; grepping `resolve_project|root_source|root_slug`
  over the queue templates hits only `partials/fix_root.html`, and
  `queue_section.html` (the `/partials/queue` fragment) includes
  `my_queue.html` + `fix_root.html` while the tick re-render returns
  `my_queue.html` alone. The regression test
  (`test_a_named_computers_queue_shows_that_computers_resolve_project`) calls
  `api_mod.build_queue_view` directly, so it is green over a page nothing
  changed on - the shape brief rule 7 asks about.
- Ledger: CR-239 does not fix dash-api-4
- Suggested fix: give the home page and `/partials/queue` a machine to be about
  (the `?machine=` the assignments grid already uses, or the person's single
  machine when they have one) and pass it through, or move the
  destination-root panel onto the per-machine page. Either way the test should
  go through the HTTP route and assert on the rendered sentence.

### dash-api-4 - suspending an editor mid-job throws away the work their machine has already done
- Severity: medium
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/api.py:9926-9930` (`_require_fleet_caller` -> `_refuse_barred_account`), reached from `api.py:10348` (`/jobs/{id}/heartbeat`) and `api.py:10371` (`/jobs/{id}/result`); companion side `companion/src/ccsync_companion/jobs_runner.py:764` and `:781-788`
- What: dash-api-6 put the account bar on `_require_fleet_caller`, which gates
  the job heartbeat and result routes as well as claim. The companion's runner
  treats ONLY 410 as "this job is no longer ours, stop" (`jobs_runner.py:764`,
  comp-ytdl-jobs-1's rule); a 403 falls through, so a machine whose owner is
  suspended mid-transcode runs the job to completion and then posts a result
  that is refused. `_post_result` logs and returns; the lease expires and the
  job is re-queued for another machine.
- Failure scenario: an admin presses SUSPEND on a freelancer at 14:00 while
  their box is 40 minutes into a `whisper` job. The box burns the GPU for
  another 40 minutes, writes its output into the shared vault (that write is
  SMB, not the API, so the bar does not reach it), posts the result, is told
  403, and the dashboard re-queues the same job onto a second machine to do it
  all again. Nobody is told, and dash-api-6's intent ("a suspended person's
  computers are not writing rows under their name") is not achieved either.
- Evidence: read of `_require_fleet_caller` (all three job routes call it), so
  `db.finish_job` is never reached; `jobs_runner.py`'s status handling has
  `if status == 410:` as the only branch that stops work, and `_post_result`'s
  except path says "a lost result costs one retry".
- Ledger: related to CR-239 (dash-api-6) - a fix that closed the reported door and opened its neighbour
- Suggested fix: let heartbeat and result through the account bar (they only
  RETIRE work already claimed), or answer 410 rather than 403 on those two
  routes when the refusal is an account bar, so the companion's existing "stop,
  the job is not ours" path runs and the row ends cancelled rather than
  silently re-queued.

### dash-api-5 - `rollout` and `rollout_platforms` on the same /health answer disagree about a machine with no platform, and the ship gate cannot clear it
- Severity: low
- Confidence: PLAUSIBLE
- Where: `dashboard/src/ccsync_dashboard/api.py:1526-1546` (`_rollout_platforms_block`) against `dashboard/src/ccsync_dashboard/db.py:4293` (`rollout_status`), consumed by `tools/ship_gates.ps1:120-133`
- What: `ReportIn.platform` is optional (`api.py:8517`), so a `machine_state`
  row can carry NULL/''. `rollout_status` reads that as `"windows"`
  (`str(_row_value(r,"platform") or "windows")`); the new
  `_rollout_platforms_block` reads the same row as `"unknown"`. The ship gate
  then looks for a channel covering the platform key `unknown`, never finds
  one, and emits a straggler on every ship.
- Failure scenario: one decommissioned or pre-`platform` machine row with a
  NULL platform (a laptop nobody pressed [ FORGET THIS COMPUTER ] on) makes
  `tools\ship.cmd` report "1 unknown computer(s) have no current build on this
  dashboard, so their versions were never checked against <floor>" for ever,
  with no build an admin could publish to clear it.
- Evidence: the two coercions read side by side;
  `ship_gates.ps1`'s `foreach ($prop in $platforms.Value.PSObject.Properties)`
  loop adds a straggler for any key with `count > 0` that is not in `$covered`,
  and `$covered` is built from `rollout`'s channels, which only exist per
  published-current platform. Not reproduced against a live database (rule 1
  forbids touching the deployed dashboard), hence PLAUSIBLE.
- Ledger: related to CR-239 (server-tools-1)
- Suggested fix: use the same coercion as `rollout_status` (`or "windows"`), or
  keep "unknown" and have the gate treat an `unknown` bucket as "cannot tell"
  with its own sentence rather than as a platform with no channel.

### dash-api-6 - `resolve_health_detail` carries unbounded undeclared keys out of the validator, against its own comment
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/api.py:6977-6980` (the comment) and `api.py:7719-7725` (`flatten_sync_guard`'s `rh.model_dump(exclude_none=False)`)
- What: `_BoundedSectionIn`'s new comment asserts "nothing reads `model_extra`
  except that reporting, so an undeclared key is still not stored". That is not
  true of the value: `model_dump()` on an `extra="allow"` model includes the
  extras, so `flatten_sync_guard`'s `resolve_health_detail` carries them, and
  `_bound_to_field_caps` bounds declared fields only, so an extra's value is
  capped by nothing but the request-size limit. Only
  `db.store_resolve_health_detail`'s `RESOLVE_HEALTH_DETAIL_KEYS` allow-list
  keeps it out of `meta` - the claim is true by accident of a different
  function, and the next reader of `resolve_health_detail` inherits the hole.
- Failure scenario: a caller holding the fleet token posts
  `sync_guard.resolve_health = {"junk": "x"*200000}`; the whole 200 KB is held
  in the flattened dict for the life of the request and handed to two db
  writers. Both filter it today; a third writer, or a `dict(...)` of the whole
  thing into `meta`, would persist it.
- Evidence: `flatten_sync_guard(SyncGuardIn(resolve_health={'brand_new_key':'x'*5000}))['resolve_health_detail']`
  contains `brand_new_key` with `len == 5000`.
- Ledger: new
- Suggested fix: restrict the dump to `ResolveHealthIn.model_fields` (or
  `exclude=set(rh.model_extra or {})`), and correct the comment to say where
  the real bound is.

### dash-api-7 - the rollback re-points `current` for the whole platform, not just the machines being rolled back
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/api.py:6313-6320`
- What: when `from_version` is current, the rollback makes `to_version`
  current, and `_upgrade_info` offers "a version that DIFFERS", not "a newer
  one" (`api.py:5667`, equality by design). Machines that were never on
  `from_version` are therefore offered `to_version` too. For the normal case
  (everyone else is older) that is an upgrade and harmless; for a machine on a
  NEWER build than current - the base rig after a `-AllowDirty` hotfix, or a
  machine that took a targeted push - the tray starts offering a downgrade
  nobody asked for, and the audit row (`uncurrented`) does not name which
  machines the re-pointing newly affects.
- Failure scenario: an admin rolls the fleet from 0.9.71 back to 0.9.70; the
  base rig, running a locally built 0.9.72, is now offered 0.9.70 in its tray
  for ever.
- Evidence: `_upgrade_info`'s `running == current["version"]` test is equality,
  and its docstring says so deliberately ("Different, not newer").
- Ledger: new (introduced by CR-239's dash-api-3 fix)
- Suggested fix: name the affected machines in the response and the audit row,
  or gate the re-pointing on "no machine on this platform is running something
  newer than `to_version`".

## Coverage note
- `local_users.py`, `android.py` and `package_store.py` are unchanged since
  40f931a and were read only for the paths the diff reaches
  (`make_current_refusal`, `blocks_on_dashboard_version`); their own logic was
  not hunted in depth.
- I did not exercise the htmx twin of the rollback in `ui.py` (dash-mounts-ui's
  territory) beyond confirming it calls the same `roll_fleet_back`, so
  dash-api-1 applies to both buttons.
- `settings.py`'s dash-core-7 session-lifetime clamp reads correctly
  (`object.__setattr__` on a frozen dataclass, both readers fixed at the
  source); the only nit is that the two defaults are now written in three
  places (`settings.py:173-174`, `:642-643`, `:771-772`) and can drift.
- `provision.py`'s `..`-dropping reads correctly for the container (Linux)
  case; I did not chase a drive-qualified value like `C:/x`, which pathlib
  would treat as absolute on Windows - the dashboard does not run there.
- `_version_tuple`'s numeric-prefix change was re-checked against every caller
  (`_version_at_least`, `_update_push_done` only) and against the 14-day
  `expire_machine_update_requests` safety net; I found nothing wrong with it.
- The suite has no test that a `sync_guard` sub-model 422s a whole report on an
  over-long field, and none that renders the destination-root panel through
  HTTP for a named machine (dash-api-3).

## OUT OF TERRITORY
- `companion/src/ccsync_companion/jobs_runner.py:764`: only a 410 stops a running job, so any other refusal (403, 500, a proxy's 502) is burned through to completion and the result thrown away - the companion half of dash-api-4.
- `tools/ship_gates.ps1:120-133`: treats any `rollout_platforms` key with no matching channel as a straggler, including the synthetic `unknown` bucket, with no way for an admin to clear it.
- `dashboard/src/ccsync_dashboard/db.py:3963`: `set_current_package`'s docstring forbids exactly the new call site in `api.roll_fleet_back` - worth an assertion rather than a comment.
