# live - what the LIVE dashboard was showing on 2026-09-18 (orchestrator, read-only probe of the NAS database)
Files read (with approximate coverage): the live `dashboard.db` (notices, alert_log, machine_state, lane_report_current) through `docker exec ... python` read-only; companion `app.py` blocked_report / `_lane_stall_record`, `sync/rclone_lane.py` `_record_stall` / `stall_report`; dashboard `alerts._check_lane_stalled`, `health._why_code`, `sessions.validate`, `db.age_seconds`, `api.StrayProjectsIn`, `package_store.store_verified_package`.
Tests run: none (live read only)

## Findings

### live-1 - a stall the companion killed and recovered from a week ago is reported as a CURRENT blockage, alerted daily, and shown red in the tray, for ever
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/sync/rclone_lane.py` `_record_stall` (writes `~/.ccsync/state/lane_stall.json`, nothing ever clears or ages it) and `stall_report` (puts it in `sync_guard.stalled` on every report); `companion/src/ccsync_companion/app.py:7173` (`_blocked_candidate("lane_stalled")` answers the sentence whenever a record exists) and `tray.py:156` (`lane_stalled` is a RED reason); `dashboard/src/ccsync_dashboard/health.py:727` (`_why_code`: any `stalled_lane`/`stalled_seconds` is "lane_stalled" now) and `alerts.py:1549` (`_check_lane_stalled`, no age test)
- What: SYNC-1 (2026-08-28) made the stall record persistent so a restart could not erase the evidence, and gave it no expiry and no "the lane has since completed a pass" condition. The companion reports the last stall in every report for the life of the install; the dashboard reads any record as a current blockage (`blocked_reason=lane_stalled`, `blocked_since=<the stall's own stamp>`), the fleet grid shows the machine as not syncing, the daily alert re-sends as "still not fixed after N days", and the tray shows a red line. Nothing any editor or admin can do clears it.
- Failure scenario: ruskin/DESKTOP-LQQ41TC: one lane A upload was killed after 25 minutes of no progress on 2026-09-11 16:26 UTC and restarted. On 2026-09-18 all three lanes are idle, nothing owed, last report 4 minutes old, companion 0.9.74 since 09-17 - and the row still says `blocked_reason=lane_stalled since 2026-09-11`, the mail "CC Sync: still not fixed after 4 day(s): a sync transfer is stuck" has gone out four days running, and his tray is red. leso's Mac has the same shape from a 2026-09-17 express stall.
- Evidence: the live rows above (machine_state: stalled_lane=A, stalled_seconds=1500, stalled_killed=1, stalled_at=2026-09-11T16:26:15, blocked_reason=lane_stalled; lane_report_current: three lanes idle, state_since 2026-09-18T03:35). `grep -n _stall_file rclone_lane.py` shows one writer and one reader, no unlink. `_check_lane_stalled` has no age comparison.
- Ledger: new (SYNC-1 / SYS-17 is FIXED and this is its missing other half; related to CR-91)
- Suggested fix: companion side: a stall record is CURRENT only until the same lane completes a later pass (clear `_last_stall` and the file, or stamp it `recovered_at`, when a pass of that lane ends without a kill), and never older than 24 h; keep the record in the report but under a key the dashboard can tell apart (`stalled.recovered_at`). Dashboard side, safe alone against a 0.9.74 companion: `_why_code` and `_check_lane_stalled` must not call a stall current when `stalled_at` is older than the machine's latest successful pass of that lane (`lane_report_current.last_sync` for that lane) or older than 24 h; the alert then RECOVERS on its own. Both sides deploy independently; the dashboard half stops the mails fleet-wide in one deploy.

### live-2 - publishing a version the dashboard already holds is a 500 (UNIQUE constraint) after the artefact on disk has already been replaced
- Severity: medium
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/package_store.py:~455-470` (`store_verified_package`: `os.replace(part_path, dest_dir / filename)` and THEN `db.insert_companion_package`, which raised `IntegrityError: UNIQUE constraint failed: companion_packages.kind, companion_packages.platform, companion_packages.version`); route `/api/v1/admin/feed/publish`
- What: the same defect dash-api-6 reports at low (the file is placed before the row is inserted), seen live: the 0.9.74 publish on 2026-09-17 hit the route twice for a version already held, each time answering a 500 that is now an open `server_error` notice telling the admin to "send the detail to support", and each time the live artefact under that filename was replaced before the insert refused. A version already held must be a clean refusal (409, "already published at this version; bump the version or --allow-replace") BEFORE anything on disk moves, and the same-bytes case a no-op.
- Failure scenario: `publish_latest.py` or `ship.cmd -Publish` runs twice for one version (a retry after a timeout, or CI republishing the same run): the second call 500s, the notice panel shows an error notice with a stack trace, and the artefact file has been swapped under a row that still describes the first upload's bytes.
- Evidence: live notice id 31552 (`first_seen 2026-09-17T11:23:43`, 2 times, `last_seen 11:59:04`), body quoted above; `package_store.py` order of operations.
- Ledger: new (extends dash-api-6, which should be fixed with it and raised to medium)
- Suggested fix: check for an existing `(kind, platform, version)` row first and refuse with 409 (same bytes: 200 no-op, "already held") before `os.replace`; insert the row BEFORE the swap (or in one transaction with a rollback that restores the previous file), and catch `IntegrityError` as a 409 rather than a 500.

### live-3 - a session row with a naive timestamp makes EVERY request with that cookie a 500 instead of a logout
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/sessions.py:216` (`validate` catches `ValueError` from `db.age_seconds` only) and `db.py:627` (`age_seconds`: `fromisoformat(now) - fromisoformat(ts)` raises `TypeError` when one side is naive)
- What: `validate` guards against an unparseable timestamp but not against a parseable NAIVE one; `datetime - datetime` across naive/aware raises `TypeError`, which escapes `_resolve_session` and `login_gate` as an unhandled 500 on every request carrying that cookie. Seen live from a hand-inserted admin session (the minted-session recipe writes `created_at` without a timezone), but any row written by an older build or a hand edit does the same.
- Failure scenario: an admin with such a cookie sees "internal error" on every page and cannot even reach /login; the only way out is clearing the browser cookie.
- Evidence: live notice id 31154 (`TypeError: can't subtract offset-naive and offset-aware datetimes` at `db.py:627 age_seconds <- sessions.py:216 validate <- auth.py:620 _resolve_session`, 2026-09-17T10:13:38).
- Ledger: new
- Suggested fix: `age_seconds` (or `parse_iso`) treats a naive timestamp as UTC; `validate` catches `(ValueError, TypeError)` and answers "no session" (which sends the browser to /login) rather than raising; the same for every other `age_seconds` caller that reads a row a human could have written.

### live-4 - the dashboard throws away two `sync_guard.stray_projects` fields every 0.9.74 companion sends, and has said so on the home page since 2026-09-11
- Severity: medium
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/api.py:7569` (`StrayProjectsIn`: `count`, `bytes`, `paths`) vs `companion/src/ccsync_companion/app.py:6650` (`guard["stray_projects"] = self._lane_a.stray_projects()`, which carries `checked_at` and `slugs`)
- What: the companion's stray-projects section gained `checked_at` and `slugs` (the 09-11 fix pass) and the dashboard's bounded model never declared them, so `ignored_report_sections` (the notice that exists to catch exactly this) has been open as a warn since 2026-09-11 with the fix line "Update the dashboard", on a dashboard that IS current. The grid's stray-projects figure is right (count and bytes land) but `slugs` (which projects) and `checked_at` (how fresh) are dropped, and the notice can never clear.
- Failure scenario: every report from every 0.9.74 machine adds to the ignored-fields notice; an admin who follows its fix line finds nothing to update; a real future "companions ahead of the dashboard" event is invisible behind a warn that has been on the page for a week.
- Evidence: live notice id 21334 (`sync_guard.stray_projects.checked_at, sync_guard.stray_projects.slugs`, `first_seen 2026-09-11T09:09:43`, `last_seen 2026-09-18T03:42:07`).
- Ledger: new (related to CR-267b, "report fields skipped_exists.subpath declared")
- Suggested fix: declare `checked_at: str | None` and `slugs: list[str] | None = Field(max_length=20)` on `StrayProjectsIn` (bounded like `paths`), store `slugs` where the grid can show which projects, and add a test that feeds the companion's real `stray_projects()` output through the model so the next added field fails a test instead of opening a notice.

### live-5 - the tray colours a computer with nothing ticked ORANGE ("not syncing"), which the owner has twice said is not a fault
- Severity: medium
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/tray.py:161` (`_BLOCKED_BASE_RIG_EXEMPT` exempts `no_selection` on the base rig only) and `:234-236` (`compute_overall_color`: any other blocked reason is orange); the Settings/tray blocked line via `app.py:7142` (`_blocked_candidate("no_selection")`)
- What: CR-267f (2026-09-11) made the dashboard treat `no_selection` as informational (`health.WHY_INFORMATIONAL`, the muted "Nothing ticked for this computer" line) on the owner's words "Alex laptop just happens to have no synced projects, not an error". The tray was never given the same rule: on an editor machine `no_selection` still colours the icon orange, the colour every fault shares, and the blocked line reads "No projects are ticked for this computer (Nothing to sync yet: ...)". The owner restated the rule on 2026-09-18: "A computer having nothing ticked is FINE."
- Failure scenario: alex/Razer, mode editor, nothing ticked, everything working as planned: orange tray icon since 2026-09-17 23:39, reading as a machine that is not syncing.
- Evidence: live machine_state row for Razer (`blocked_reason=no_selection`); `tray.py:234-236`.
- Ledger: new (the tray half of CR-267f)
- Suggested fix: make `no_selection` (and `upload_only` if it is ever a blocked reason) informational on EVERY machine in `compute_overall_color` (green, not orange), keep the sentence as a plain status line without the fault vocabulary, and pin it with a test that a nothing-ticked editor machine is green. Nothing on the dashboard side needs to change.

## Open items already in the ledger that the live dashboard is showing, folded into this pass
- **CR-279, queueing half OPEN**: `thread_restarts` alerts fired for all three editor machines in the last three days (`restarts_count_24h`: leso 8, Razer 5, ruskin 3). The watchdog half is fixed; the queueing half (a sequencer busy with one long upload is not wedged, and a restart of it does nothing) is what the alert counts. Owned by `companion-core`.
- **CR-280 OPEN**: `ytdlp_failed` on leso's Mac twice on 2026-09-17: every HTTPS download from the frozen macOS companion fails certificate verification. Owned by `companion-core` (the fix is the bundled CA store / SSL context in the frozen build; verify what can be verified without a Mac and say what cannot).

## Not defects (for the record)
- `server_error /api/v1/report (OperationalError: database is locked)`, 9 times, last 2026-09-14: predates the busy-database rework (`4aaca6a`, live in 0.7.49), which turns it into a 503 and its own warn notice; the open error notice is stale and can be dismissed once 0.7.50 is live. Note that a `server_error` notice never clears itself even when its route has not failed for days; a builder may add an age-out if cheap, but it is not a queue item.
- `slow_write collector poll alerts 5.8 s`: this IS dash-db-1 (the collector poll timed as a write), already in the queue.
- leso `root_absent` (the sync drive is disconnected), Razer `no_selection`: operational, true, nothing to fix.
- `invariant_broken fleet_current_with_vendor: macos 0.9.74` recovered by itself on 2026-09-17.

## OUT OF TERRITORY
- none
