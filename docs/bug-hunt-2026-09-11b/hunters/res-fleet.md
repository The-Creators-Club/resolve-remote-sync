# res-fleet - what the FLEET does when the SERVER side goes wrong (whole paths across dashboard/, server/, the mounts)

Files read (with approximate coverage):
`git diff 40f931a..HEAD -- dashboard/ server/` in full (every hunk read), then
in depth: `dashboard/src/ccsync_dashboard/api.py` (the report handler's
command block, the push/rollback routes, `_update_push_done`/`_version_tuple`,
the jobs routes), `db.py` (migrate/`_MIGRATION_STEPS`/v52, the jobs state
machine, `fetch_collector_status`, `prune`, `forget_machine`,
`fetch_machine_selections`), `collector.py` (cycle order, `_run_enforce`,
the diagnosis pass), `alerts.py` (`sink_deliverable`, `weekly_due`,
`heartbeat_due`, `_attempts_since`, `scan`/`deliver`), `notices.py`,
`invariants.py`, `mount_status.py`, `recovery.py`, `syncthing_client.py`,
`dashboard_update.py` (heal/restart/apply/rollback/status),
`release_feed.py` (poller + `_valid_records`), `app.py` (lifespan boot order,
CSRF origin), `ui.py` (the three package/machine push doors),
`dashboard/deploy/select_code_root.py`, `dashboard/deploy/run.sh`,
`server/install_dashboard_app.py` (skimmed - server-tools' territory),
`dashboard/tests/test_bug_hunt_2026_09_11_dash_api_jobs.py`,
`tests/test_release_channel.py` (push-one coverage).

Tests run:
- `dashboard\.venv\Scripts\python.exe -m pytest tests/test_bug_hunt_2026_09_11_dash_api_jobs.py -q` -> 20 passed
- ad-hoc snippets from the dashboard venv (scratchpad, nothing written into the repo):
  `api._update_push_done` against both row shapes; `db.claim_job(max_running=)`
  contention; `db.open_retry_of` against the real `inputs_json` spelling;
  `db.migrate` on a v52 database with the pre-v48 step list.

## Findings

### res-fleet-1 - the rollback fix landed on ONE of the three doors that push a version at a machine
- Severity: high
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/api.py:5163` (`api_push_machine_update`),
  `dashboard/src/ccsync_dashboard/ui.py:3623` (`partial_admin_package_push_one`,
  the `[ PUSH TO ONE MACHINE ]` button), against the clear rule at
  `dashboard/src/ccsync_dashboard/api.py:5551` (`_update_push_done`) and
  `api.py:9185`
- What: dash-api-3 fixed "a downward push is retired before it is delivered" by
  recording `update_requested_from` (v52) - but only `roll_fleet_back` passes it.
  The two per-machine doors still call `db.request_machine_update(...)` with the
  default `from_version=""`, which `machine_update_request` normalises to `""`,
  which `_update_push_done` reads as "an upgrade" and therefore clears at or past
  the requested version. Both doors accept ANY published version, including one
  below what that machine is running.
- Failure scenario: 0.9.71 goes out, one editor's machine is unhappy, the admin
  opens Settings -> Packages and clicks `[ PUSH TO ONE MACHINE ]` with 0.9.65 (or
  posts `{"version": "0.9.65"}` to `/api/v1/admin/machines/{editor}/{machine}/update`).
  The route answers `{"ok": true, ...}` plus a `_command_delivery` block saying it
  will arrive on the next report. That machine's next 30 s report says 0.9.71,
  `_update_push_done` returns True, the request is cleared and committed, and
  `commands.upgrade` is never emitted. Nothing on the page and nothing in the log
  says the push was dropped. This is the exact canary-rollback case REL-1's soak
  flow depends on, and the one an admin reaches for before a fleet-wide recall.
- Evidence: dashboard venv ->
  `api._update_push_done({"version": "0.9.65", "from_version": ""}, "0.9.71")` is
  `True`; with `from_version="0.9.71"` (what `roll_fleet_back` writes) it is
  `False`. `grep -rn "request_machine_update" dashboard/` shows three writers and
  only `api.roll_fleet_back` passes `from_version`. No test covers a downward
  push-one (`tests/test_release_channel.py:324` pushes forward only).
- Ledger: CR-247/dash-api-3 does not fix the per-machine push doors (new, same
  defect one door along)
- Suggested fix: both doors already read the machine's row - pass the machine's
  reported `companion_version` as `from_version` on every
  `request_machine_update` call (`ui.py:3689`'s "update to current" included, so a
  re-point of `current` downwards behaves too). The safest shape is to make
  `request_machine_update` look the running version up itself when the caller does
  not say, so a fourth door cannot repeat this.

### res-fleet-2 - the AUTOMATIC crash-loop revert has no schema check, and reverting past a migration is an unrecoverable dashboard
- Severity: high
- Confidence: PLAUSIBLE (every link verified separately; the compound scenario
  needs a post-migrate boot failure, which is what the watchdog exists for)
- Where: `dashboard/deploy/select_code_root.py:273` (`revert(...)` on
  `already_failed >= MAX_BOOT_ATTEMPTS`), against
  `dashboard/src/ccsync_dashboard/db.py:1965` (the fatal "schema is newer" guard)
  and `dashboard/src/ccsync_dashboard/app.py:640` (`db.migrate(conn)` uncaught in
  the lifespan)
- What: `dashboard_update.rollback()` refuses a MANUAL rollback whose target knows
  a lower schema than the live database (REL-10, `schema_rollback_check`, and it
  names the backup to restore). The automatic watchdog revert - the one that runs
  with nobody watching - has no equivalent: it rewrites `current.json` to
  `previous` or to the image and boots it. An OTA tree runs `db.migrate` at the
  top of the lifespan, so the database can already be at that tree's schema when
  the boot later fails; the older code it is reverted to then raises
  `RuntimeError: database schema is newer than this build` out of `migrate`, which
  nothing catches, so uvicorn's startup fails, run.sh loops, and the container
  crash-loops forever. The revert is the escape hatch, and it is the thing that
  closes the hatch.
- Failure scenario: `[ UPDATE ]` applies 0.7.43 (schema v52) on a customer
  appliance. The new process migrates the DB to v52 and then fails to reach
  `BOOT_HEALTHY_SECONDS` twice - a template/import error in the new tree, an OOM,
  a NAS hiccup while the mounts are probed, anything after line 640. The third
  boot reverts to the image (0.7.34-era, schema v50 or lower). That image's
  `migrate` raises immediately, every boot, for ever. There is no dashboard, so
  there is no rollback page, no `restore_db` button and no `/help`; the
  `before-0.7.43` backup that would fix it is on disk and unreachable without a
  shell on the NAS - the one shape ZERO_TOUCH/appliance deployments are supposed
  not to need.
- Evidence: dashboard venv: a fresh DB migrated to `user_version=52`, then
  `db.migrate(conn, steps=[s for s in db._MIGRATION_STEPS if s[0] <= 47])` raises
  `RuntimeError: database schema is newer than this build: user_version=52, this
  build knows 47`. `grep -n schema dashboard/deploy/select_code_root.py` -> no
  hits; `schema_rollback_check` is called only from `rollback()` and `status()`.
  `app.py:640` is outside any try. `revert()` writes `previous` or `""` (the
  image), and OTA records are filtered by `newer_than_image`, so the revert target
  is always at or below the image's schema.
- Ledger: related to REL-10 (which covers the manual door only); new for the
  automatic one
- Suggested fix: teach `select_code_root` the same test REL-10 already encodes:
  before reverting, compare the live `PRAGMA user_version` with the target tree's
  `manifest.json.schema_version` (the image's is readable from its own
  `db.SCHEMA_VERSION`); if the target is lower, do not revert - keep booting the
  applied tree and write the refusal into `current.json` as
  `reverted_reason`-style evidence so the page says why. Restoring
  `before-<version>` automatically is the other half, but refusing to revert into
  a dead boot is the part that must not wait.

### res-fleet-3 - after dash-mounts-ui-8, a tree the boot check permanently refuses never reverts and nothing anywhere says so
- Severity: medium
- Confidence: CONFIRMED
- Where: `dashboard/deploy/select_code_root.py:281-296` (the `if reason:` branch,
  `bump_boot_attempts` moved below it), with
  `dashboard/templates/partials/admin_dashboard_update.html:22` (the only surface
  that renders a revert)
- What: the fix moved the boot counter below `check_tree` so an
  environment-shaped refusal ("DASH_RELEASE_PUBKEYS is not set") stops counting
  against a good bundle. The other half of that move was not made: a refusal that
  is PERMANENT no longer accumulates either, so the container boots the image on
  every restart, for ever, while `current.json` still names the applied version
  and `reverted_reason` stays empty. Before the change, two boots produced a
  revert with a sentence on the page. Now the only evidence is a stderr line in
  the container log and `source: "image"` in `status()` / `/api/v1/health`, and no
  notice, alert or invariant reads either (`grep running_source|reverted_reason`
  across `alerts.py`, `notices.py`, `invariants.py` -> nothing).
- Failure scenario: an image update changes `/venv/.runtime-id` (a dependency
  bump - the documented "runtime update" case), so the applied 0.7.43 tree's
  `manifest.runtime_id` no longer matches. Every boot from then on silently runs
  the image's older code. The Packages page says 0.7.43 is the current tree, the
  admin sees no banner, and the fleet quietly runs a build the studio believes it
  replaced - including, if the image predates it, without the fixes that update
  was shipped for.
- Evidence: code path read end to end above; `reverted_reason` is written only by
  `revert()`, which is now unreachable for a tree that never passes `check_tree`.
  `dashboard/tests/test_bug_hunt_2026_09_11_dash_mounts_ui.py` pins that a refused
  boot does not count, and nothing pins that the state is reported.
- Ledger: related to CR-248/dash-mounts-ui-8 (the fix is right; its neighbour was
  opened by it)
- Suggested fix: keep the counter where it is, and separate "refused" from
  "reverted": record the refusal reason into `current.json` (a `refused_reason` +
  `refused_at` pair) whenever the image is booted while a version is named, render
  it in the same banner, and give `alerts.ALERT_KINDS` a row for "this dashboard is
  running the image while an applied tree is named" so the condition reaches the
  person who has to act.

### res-fleet-4 - `FeedPoller.stop()` drops the thread handle before the join succeeds, and `start()` then clears the stop event under it
- Severity: low
- Confidence: CONFIRMED (code); reachable in-process only where a poller is
  stopped and started again (tests, and any future settings-driven restart)
- Where: `dashboard/src/ccsync_dashboard/release_feed.py:1264-1281`
- What: `stop()` sets `_stop`, nulls `self._thread` and joins with a 5 s timeout.
  A poller inside a feed fetch (its own HTTP timeouts are larger) outlives that
  join, and the handle to it is already gone. A later `start()` sees
  `_thread is None`, calls `self._stop.clear()` - which un-stops the thread that
  never finished - and starts a second one. Two pollers then fetch, verify and
  `store_verified_package` concurrently on separate connections.
- Failure scenario: today only a test can reach it (`app.py` builds a new
  `FeedPoller` per lifespan), which is why this is low; but the fix's own docstring
  advertises stop-then-start as supported, so the next caller that takes it at its
  word gets two pollers and no way to stop either.
- Evidence: read at the site; `_run` loops on `while not self._stop.is_set()` and
  exits only via `self._stop.wait(interval)`, so clearing the event resurrects it.
- Ledger: related to dash-release-jobs-4 (new neighbour of that fix)
- Suggested fix: only null `self._thread` when the join actually finished
  (`if not thread.is_alive(): self._thread = None`), and refuse to `start()` while
  a previous thread is still alive rather than clearing the event under it.

## Coverage note

- I did not audit `server/install_dashboard_app.py`'s new Cards-snapshot path in
  depth (server-tools owns it); I read it for fleet consequences only.
- I did not exercise the alert SINKS (smtp/webhook) live, so res-fleet-4's
  attempt-ceiling behaviour (`_attempts_since` + `send`'s 24 h dedup, which
  records no `alert_log` row when it dedups) is reasoned about, not measured. It
  appears safe - a failed send DOES write a row, which is what the ceiling counts -
  but a suite that drives a refusing sink across a slot boundary does not exist.
- The dashboard suite has no test that boots an OLDER tree against a NEWER
  database, which is res-fleet-2's whole failure; nor one that asserts anything is
  said when `select_code_root` falls back to the image (res-fleet-3).
- Not covered by me: the companion halves of any of these wires (res-companion and
  wire own them), the /broll, /music and /ytdl web apps' own fleet routes, and the
  Cards tunnel.

## OUT OF TERRITORY
- `server/install_dashboard_app.py:export_cards_snapshot`: the temp directory
  created by `tempfile.mkdtemp()` is only removed on the failure paths - the
  success path returns `out` (a child of it) and the caller "ships and forgets",
  so every successful Cards deploy leaves a full copy of the snapshot in the base
  rig's temp directory.
- `dashboard/src/ccsync_dashboard/ui.py:_fleet_view`: one extra `meta` read per
  machine per grid render, and the grid polls every 15 s per open browser.
- `dashboard/src/ccsync_dashboard/db.py:forget_machine`: the per-machine `meta`
  rows (`resolve_health:`, `ytdlp:`, `youtube_import:`) are not removed with the
  computer, and `prune()` does not age them out.
