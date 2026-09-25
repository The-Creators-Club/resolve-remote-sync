# bug-dash-diag - dashboard self-diagnosis: alerts, notices, invariants, health, collector loop, recovery, protection, mount_status
Files read (approximate coverage): mount_status.py (all), recovery.py (all), protection.py (all), alerts.py (delivery/ledger half 4150-4805, scan + registry 3480-3790, checks 1370-1670, 2586-2670), notices.py (run_checks, collector/tree/identity/pending/plan/space checks 98-660, CR-320 resolve rules 1540-1703), invariants.py (Ctx, checks 1-9, evaluate/run_cycle 177-676, 1196-1412), collector.py (lifecycle, _loop, run_cycle, _timed, _run_invariants/_run_alerts, hand-move recording 120-590, 1860-1935, 2291-2385), health.py (rollups, stall, disk, headline, detail notes 1-470, 1040-1314). Not read in depth: collector enforce/inventory/completion internals, alerts Ctx and the remaining ~40 checks, notices 660-1530.
Tests/probes run: two ad-hoc probes from the dashboard venv against a temp database (scratchpad p1.py, p2.py), quoted in the findings. No suite run.

## Findings

### bug-dash-diag-1 - A NAS that does not answer turns a MISSING protection line into a "this has cleared" mail and closes its notice
- Severity: medium
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/protection.py:881-906 (run_cycle keep-lists); dashboard/src/ccsync_dashboard/alerts.py:2617-2658 (_protection_findings)
- What: `protection.run_cycle` builds the `protection_missing` keep-list only from lines that are BROKEN this pass. A line that drops to NOT_CHECKED because the NAS could not be asked (tasks() is None) is left out, so its MISSING notice is closed, and `_check_protection_missing` stops returning it while the alerts check itself succeeded, so `deliver()` records and mails a RECOVERED. `invariants.run_cycle` has the exact guard for this (dash-collector-2: a no-verdict pass keeps `stored_broken` subjects open); protection never got it.
- Failure scenario: the tree dataset has no snapshot task, so `snapshot_tree` is MISSING and alerted. The NAS API is down for one 15-minute invariants pass: the owner gets "This has cleared on its own or somebody fixed it" about the snapshot schedule, the red card leaves PROBLEMS THE SERVER FOUND, and when the NAS answers again a fresh "new" error goes out. Every NAS blip flaps the most important safety line, and in the gap the page says nothing is missing.
- Evidence: probe p2.py: pass 1 with tasks=[{dataset: tank/other}] and DASH_TREE_DATASET=tank/Projects -> protection_missing for snapshot_tree, notice `snapshot_tree: tank/Projects` open. Pass 2 with tasks_fn returning None -> `deliver` returns recovered=1, alert_log gains `protection_missing.ok / snapshot_tree`, and the notice row has cleared_at set.
- Ledger: new (same shape as the fixed dash-collector-2 for invariants, 2026-09-03 hunt)
- Suggested fix: in `run_cycle` (and `refresh_line`), for a line that reached no verdict, keep the previous pass's BROKEN subjects in the `missing` keep-list and carry that line's previous BROKEN row into the stored results (or store the previous state beside the new one) so `_protection_findings` keeps the finding open until a real verdict says otherwise.

### bug-dash-diag-2 - `check_failed` alerts can never recover, so they stay open forever and a later failure is reported as weeks old
- Severity: medium
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/alerts.py:4565-4569 (`checked_kinds` in deliver), 3686-3688 (CHECK_FAILED outside ALERT_KINDS)
- What: the recovery pass only walks `_open_subjects(conn, checked_kinds)`, and `checked_kinds` is built from `ALERT_KINDS`. `check_failed` is deliberately not in that registry, so a `check_failed` row is never offered for recovery: no `check_failed.ok` is ever written and `_is_open("check_failed", <kind>)` answers True for the life of the database.
- Failure scenario: `_check_lane_error` raises once on a malformed report (error mailed "a health check could not run"). The next cycle it runs fine: no recovery mail, and the ledger says the check is still failing. Six weeks later the same check raises again: `deliver` treats it as a REPEAT, not a new failure (in digest mode it is listed as "still not fixed after 49 day(s)"), and on the Alerts page it has been "open" the whole time. The same applies to "the whole scan" subject.
- Evidence: probe p1.py: deliver([check_failed/breaker_tripped]) then deliver([]) 10 minutes later -> recovered=0, `_is_open` still True, `_open_days` 49 days later = 49. The same two calls for a registry kind (`crashes`) record the recovery and `_is_open` goes False.
- Ledger: new
- Suggested fix: add `CHECK_FAILED.kind` to `checked_kinds` whenever the scan itself completed (no "the whole scan" finding this pass); its subjects are kind names, so "not in seen" really does mean "that check ran this time".

### bug-dash-diag-3 - A snapshot restore's `.restored-<ts>` folder is replicated by Syncthing to every editor who has the project ticked
- Severity: medium
- Confidence: PLAUSIBLE
- Where: dashboard/src/ccsync_dashboard/recovery.py:88-95, 424-458 (quarantine inside the live project folder); dashboard/src/ccsync_dashboard/provision.py:156-163 (project .stignore has no dot-directory or `.restored-*` rule)
- What: the quarantine directory is created INSIDE the live project folder, which is a sendreceive Syncthing root with fsWatcher on. The leading dot is documented as keeping it out of `provision.scan_project_dirs`, but Syncthing does not skip dot-directories and the project `.stignore` only excludes video extensions, `.partial`, ytdl fragments and `Proxy`. So every non-video file the admin restores (audio, .drp, stills, subtitles, sidecars) goes out to every full-tick editor machine.
- Failure scenario: the owner restores a project from a snapshot with "include changed" to compare versions: several GB of WAVs and project files land in `.restored-20260924T101500/` on the NAS and are then pulled to every editor with that project ticked. When the owner has moved back what they wanted and deletes the quarantine folder on the server, the editors' copies stay, because project folders were retrofitted with ignoreDelete on 2026-08-11. That leaves a permanent duplicate tree on every laptop, which the "costs disk space and nothing else" promise on the page does not mention.
- Evidence: read only. `build_stignore_lines()` has no dot or `.restored` pattern; the recovery module never adds an ignore; `_walk` skipping dot-dirs affects only this module's own comparison. Not reproduced against a live Syncthing.
- Ledger: new
- Suggested fix: add `(?d).restored-*` (or `/.restored-*`) to `build_stignore_lines` in all three byte-identical copies (server/common.py, provision.py, companion), or put the quarantine outside the synced folder (a sibling `.restored/<label>-<ts>` under the tree root, which is not itself a folder root).

### bug-dash-diag-4 - A failed `db.migrate` in the collector loop is never retried and leaves the collector running on the un-migrated connection
- Severity: low
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/collector.py:310-324
- What: `conn = self._open_conn()` is assigned before `db.migrate(conn)`. If migrate raises (the "database is locked against the app's own startup migration" case the comment names), the except waits and `continue`s, but `conn` is no longer None. So the next iteration skips the open-and-migrate block and runs every cycle on that connection, and the migration the comment says is "retried" never runs again from here. The failed connection is not closed either.
- Failure scenario: a boot where the collector thread starts while the app is still migrating: migrate raises "database is locked", and the collector proceeds without its own migration. It is harmless when the app's migration finishes. When the app's migration also failed, the collector keeps running cycles against a schema it never confirmed, and the only symptom is per-cycle failures.
- Evidence: read of lines 317-324. The assignment happens before the call that can raise, and `continue` re-enters with `conn` set.
- Ledger: new
- Suggested fix: open into a local, migrate, then assign `conn` only on success, and close the local in the except.

## Coverage note
Not reached: the alerts `Ctx` builder and roughly 40 of the 62 alert checks (jobs, ytdl, broll, rollout, code_not_applied), `compose_weekly` and `compose_digest`, notices 660-1530 (feature mounts, broll archive, server crashes, dashboard space, release feed, accounts, error redaction), collector enforce/inventory/completion internals, and health 470-1040 (why_not_syncing). Two things I left to wave 2 because they are rule problems, not wrong code. First, `protection._check_snapshot_recent` takes the newest run of ANY enabled task, so an hourly task on an unrelated dataset keeps "a snapshot was taken in the last day" green while the tree's task is weeks stale. Second, `notices.resolved_reason` measures `min_hours` from `last_seen` where its comment says "on the page for".

## OUT OF TERRITORY
- dashboard/src/ccsync_dashboard/provision.py:156: project `.stignore` has no rule for dot-directories the dashboard itself creates inside a project folder (see bug-dash-diag-3).
