## The dashboard's self-diagnosis layer (CR-241, 2026-09-11)

Ten findings from the 2026-09-11 hunt, all in the layer whose whole job is
telling an owner the truth about his own server: the alerts scan and its
delivery, the notices ledger, the invariant pass, the feature-mount
registry and the restore page. Nine of the ten are the same sentence said a
different way. **Silence is not good news**, and this code kept spelling it
as good news: a check that stopped judging a subject, a cap that dropped
the overflow, a ledger row that was generated and never sent, a schedule
retired by a send that failed, a mount judged once at boot.

**dash-collector-alerts-1 / res-fleet-3 (high).** CR-232 taught
`_check_out_of_tree` to say nothing about a Resolve project this fleet does
not sync, and spelt that silence as `continue`. But the alert ledger is
keyed `(kind, subject)` and the subject is the stable `editor/machine`,
while the predicate now swings with whichever project happens to be open at
scan time: a subject that leaves the scan is declared RECOVERED by
`deliver`, so ruskin opening his wedding project for an hour CLOSED the row
about the forty clips outside the tree in a fleet project and mailed the
owner "this has cleared on its own or somebody fixed it. No action is
needed." He switched back after lunch and it was raised again as new, and
the weekly report counted the week as clean. `_f`'s own docstring names the
trap. Fixed with a third volume below `repeat=False`: a QUIET finding
(`_f(..., quiet=True)`) that stays in the scan, holds its ledger row
exactly where it is, sends nothing and is counted in the digest's "still
open from before". It is emitted only for a subject the ledger already
holds open - `Ctx.open_alert_subjects(kind)`, one grouped query per kind per
scan - so CR-232's silence for a personal project nobody was ever alerted
about is unchanged.

**dash-collector-alerts-2 (high).** `sink_deliverable` is the single shared
answer behind invariant 15, the protection panel's `alerts_sink` line and
the Alerts page: "would anything this server finds right now actually reach
a person". Its "has anything been delivered" probe was `SELECT at FROM
alert_log WHERE ok = 1` with no filter, and `run_cycle` deliberately
records the weekly report of a site with NO sink as `ok=1, "generated, not
sent (no sink configured)"`. So the moment an admin typed an SMTP host with
a typo in it, all three went green off a message that had never left the
container, and nothing tried a real send until the following Monday. The
probe now requires `sent_to <> ''` - keyed on the empty recipient rather
than on the detail prose, which is user-facing text somebody will reword.
No `kind` filter: a heartbeat is evidence about the channel exactly as an
alert is.

**dash-collector-alerts-3 (medium after the verdict).** `collector_stale`
is only ever computed inside `if reachable and finished_at`, so a collector
whose last act was a FAILED cycle could never be stale, and neither could a
Syncthing-less deployment, which runs no non-Syncthing-free kind at all.
The liveness question stopped being asked in the two states worth asking it
in. `_check_collector_stale` now also reads the START of the last cycle
over all kinds (`MAX(started_at)` against `db.COLLECTOR_STALE_SECONDS`): a
cycle that began proves the thread is turning, whatever it made of itself,
and "cannot tell" is never "stopped". The second half is the sharper one:
`_check_nas_engine` is gated on `settings.syncthing_url`, because a site
with no sync engine by configuration is not a site whose sync engine is
down, and that kind is an ERROR re-mailed daily. The stored flag
(`db.fetch_collector_status`) is unchanged and is OWED to the db territory.

**dash-collector-alerts-4 (medium).** `scan` capped each kind at
`MAX_FINDINGS_PER_KIND = 40` with no marker, and `deliver` reads "not in
this scan" as recovered - so any kind whose finding set exceeds 40 and
reorders between passes mailed a handful of real problems as cleared and
re-raised them next morning. `_check_notices` was the readiest trigger: its
`ORDER BY last_seen DESC LIMIT 40` had no tiebreaker while `last_seen` is
re-stamped every pass. Now an overflow emits its own finding under a
constant subject of its own (`alerts.TRUNCATED_SUBJECT`, never a real one's,
which would dedup against it), `deliver`'s recovery pass skips any kind that
was truncated this pass, `_check_notices` has `id DESC` as its tiebreaker
and reads a window wider than the cap so the overflow can be seen at all.
The same shape one layer down: `invariants.broken()` truncates to
`MAX_SUBJECTS = 20` and those survivors were the whole keep-list handed to
`clear_notices_of_kind`, so subject 21 onward had its `invariant_broken`
notice closed while the invariant was still broken on it. `Outcome` carries
`truncated` now and a truncated BROKEN verdict keeps the stored subjects.

**dash-collector-alerts-5 (medium).** `_walk` stops at `MAX_SCAN_FILES =
50,000` and says so; `preview_restore` shows the flag, and
`restore_into_quarantine` bound it to `_cut`/`_cut2` and never read it -
"a restore that silently stopped at row 300 would be the worst possible
kind of half-recovery, one that looks complete", says the comment three
lines above the place it does exactly that at row 50,000. Worse, a
truncated LIVE walk classifies everything it never reached as missing, so
the comparison the copy is planned from is wrong too. Now refused with a
409 naming the limit and sending the operator to the printed commands,
which is already this module's answer for a project too big to click.

**dash-collector-alerts-6 (medium; the verdict resolved the open question
AGAINST the mount).** A parent `@app.exception_handler(Exception)` DOES run
for an exception raised inside a mounted sub-app, so a
`/broll/share/<128-bit token>/...` request that 500s wrote a client's live
credential into `notices.subject` - a table the home page renders, that
`_check_notices` quotes verbatim into an error alert body and mail, and
that travels in every database backup. Independently, the subject was the
concrete path, so one permanent row per job id for any route with a path
parameter, in a table nothing prunes. `notices.redact_path` now keeps the
matched ROUTE TEMPLATE when a caller has one and otherwise the first TWO
path segments and nothing else (two is load-bearing: the token is segment
three). `record_server_error` takes an optional `route=` so app.py can pass
the template later without a flag day.

**dash-collector-alerts-7 (low).** `_check_weekly_send` filtered a 200-row
recency window for the weekly row - the same cliff bug-hunt-2026-09-03
dash-collector-4 fixed for `_open_subjects` and did not apply here. On a
fleet writing a row per finding per cycle, a few hours of that pushed the
weekly row out, the check returned nothing, the subject left the scan and
`deliver` mailed "cleared" about the one channel that was still refusing.
It asks `alert_log` for the last row of that kind directly now.

**dash-collector-alerts-8 (low).** `_check_feature_mounts` walked the
entries `mount_status.snapshot()` happened to hold and then handed the
survivors to `clear_notices_of_kind`, so a mount that recorded NO verdict
was silently cleared. `mount_status.NAMES` exists precisely so "not
mounted" can be told from "never recorded" and its only reader ignored it.
It walks NAMES now; a missing entry writes nothing and clears nothing.

**res-fleet-2 (medium).** The four optional mounts were judged once inside
`create_app` and then rendered for the life of the container as a statement
about now. A NAS export that flapped at 03:00 left B-ROLL and MUSIC
advertised in the topbar, every request under them failing, `/api/v1/health`
saying all four were up, and nothing on PROBLEMS THE SERVER FOUND. Each
mount now records the data root it is serving (`mount_status.record_root`,
one line inside each mount's existing storage probe) and the collector
cycle calls `mount_status.recheck()` before the notice writer reads the
snapshot: one `is_dir` per mount, no import, no database. A root that has
gone downgrades a `mounted` verdict to `degraded` with the reason; a root
that comes back restores the BOOT verdict only for a mount this recheck
itself downgraded, because a mount that failed at boot was never mounted
into this process's ASGI app and "the directory is back" is not "the page
works". A probe that cannot answer changes nothing.

**res-fleet-4 (low after the verdict).** `weekly_due` and `heartbeat_due`
both asked `db.last_alert_at(..., ok_only=False)`, against a helper whose
own docstring says the parameter exists "because a send that FAILED has told
nobody". One refused SMTP attempt at 08:00 Monday retired the slot until
next Monday: the week's report was not late, it was gone, and a ten-minute
outage over the heartbeat slot removed that day's proof of life. Both are
`ok_only=True` now, bounded by `MAX_SEND_ATTEMPTS_PER_SLOT = 3` attempts
per slot (`_attempts_since`) so a sink that is down costs three socket
timeouts rather than one per collector cycle until Tuesday.

**res-fleet-5 (low after the verdict).** The enforce cycle's person-level
fallback adds every device of a ticked editor that no machine row claims,
so it carries every FULL-ticked project of that person whatever the
computer's own tick mode or wired flag says. The verdict is right that the
hunter's fix is a no-op: a device with a known id is already excluded from
the fallback, and an unmapped one is by construction unattributable, so no
per-machine predicate can reach it. The fallback stays (unsharing a device
the registry cannot place is the B16 shape) and stops being SILENT: one
warning per (editor, device) per process, naming the device and what cannot
be decided for it, beside the two warn-once messages that already live
there.

**res-fleet-6 (low).** The blast-radius brake counts removals against the
config snapshot the pass was planned from, while `_enforce_loop` writes
against a fresh per-folder read - so a device that entered a folder between
the two (an admin approving and sharing by hand) was dropped by the
comprehension without ever being counted by `enforce_max_share_removals`,
recorded in `record_enforce_plan` or named in the "REFUSING n share
removal(s)" log. A hole in a brake whose whole job is that no unshare
happens uncounted. Devices in the fresh read that were not in the plan's
snapshot are now KEPT and logged; the next cycle plans that folder against a
snapshot that has them, and decides it counted.

**dash-db-1 (the db territory's helper, used here).** With
`db.fetch_machine_selections(..., for_enforce=True)` landed, the two readers
that decide what an ADMIN is told use it:
`notices._check_plan_without_share`, `invariants._check_plan_has_share` and
the upload-only floor read at `invariants.py:565`. A machine that flipped to
wired in the tray kept its own `selections` rows, so a base rig that syncs
nothing raised a permanent severity-`error` `plan_without_share` notice and
a BROKEN invariant about a correct configuration - with a fix text whose
"re-tick" half 409s. The default is unchanged, so the admin tick grid still
shows the stale tick and still has a button to clear it.

### Verification
All in `dashboard/tests/test_bug_hunt_2026_09_11_dash_collector_alerts.py`;
every one of the twenty was run against the sources at 40f931a (a scratch
copy of `dashboard/` with the ten touched modules restored from that commit)
and nineteen fail there. The twentieth,
`test_a_personal_project_raises_nothing_when_nothing_was_ever_raised`, pins
CR-232's intent and passes on both sides on purpose.

- `test_a_personal_project_does_not_clear_an_open_out_of_tree_alert` -> fails at 40f931a, passes now (dash-collector-alerts-1 / res-fleet-3)
- `test_a_personal_project_raises_nothing_when_nothing_was_ever_raised` -> guard for CR-232, green both sides
- `test_a_weekly_that_was_never_sent_is_not_evidence_the_sink_works` -> fails at 40f931a, passes now (dash-collector-alerts-2)
- `test_a_collector_whose_last_cycle_failed_can_still_be_stale` -> fails at 40f931a, passes now (dash-collector-alerts-3)
- `test_a_site_with_no_syncthing_is_not_a_site_whose_sync_engine_is_down` -> fails at 40f931a, passes now (dash-collector-alerts-3)
- `test_a_truncated_kind_never_declares_anything_recovered` -> fails at 40f931a, passes now (dash-collector-alerts-4)
- `test_scan_says_so_when_a_kind_overflows` -> fails at 40f931a, passes now (dash-collector-alerts-4)
- `test_a_truncated_invariant_verdict_keeps_its_notices_past_the_cap` -> fails at 40f931a, passes now (dash-collector-alerts-4, the invariants half)
- `test_a_restore_refuses_a_tree_it_could_not_walk_to_the_end` -> fails at 40f931a, passes now (dash-collector-alerts-5)
- `test_a_client_share_token_never_reaches_the_notices_table` -> fails at 40f931a, passes now (dash-collector-alerts-6)
- `test_a_failed_weekly_is_still_found_under_a_wall_of_other_alerts` -> fails at 40f931a, passes now (dash-collector-alerts-7)
- `test_a_mount_that_recorded_no_verdict_does_not_clear_its_notice` -> fails at 40f931a, passes now (dash-collector-alerts-8)
- `test_a_mount_whose_root_goes_away_stops_reading_as_mounted` -> fails at 40f931a, passes now (res-fleet-2)
- `test_a_mount_that_failed_at_boot_is_not_healed_by_its_folder_returning` -> fails at 40f931a, passes now (res-fleet-2)
- `test_a_root_that_cannot_be_probed_changes_nothing` -> fails at 40f931a, passes now (res-fleet-2)
- `test_a_weekly_report_whose_send_failed_is_tried_again` -> fails at 40f931a, passes now (res-fleet-4)
- `test_a_heartbeat_whose_send_failed_is_tried_again` -> fails at 40f931a, passes now (res-fleet-4)
- `test_a_person_level_share_of_an_unplaceable_device_is_said_out_loud` -> fails at 40f931a, passes now (res-fleet-5)
- `test_a_device_that_appeared_after_the_snapshot_is_never_unshared_uncounted` -> fails at 40f931a, passes now (res-fleet-6)
- `test_a_wired_machines_stale_tick_is_not_a_permanent_error_notice` -> fails at 40f931a, passes now (dash-db-1, using the db territory's `for_enforce=True`)

Also run green, unchanged, after every edit: `test_alerts.py`,
`test_notices.py`, `test_notices_sweep_wave2.py`, `test_collector.py`,
`test_enforce.py`, `test_invariants.py`, `test_recovery.py`,
`test_mount_status.py`, `test_health.py`, `test_protection.py`,
`test_bug_hunt_2026_09_03_dash_collector.py`,
`test_bug_hunt_2026_09_11_dash_db_core.py`, `test_admin_assignments.py`
(388 + 129 passed).

### OWED TO ANOTHER TERRITORY
- `dashboard/src/ccsync_dashboard/db.py` (`fetch_collector_status`,
  dash-collector-alerts-3): `collector_stale` is still only computed inside
  `if reachable and latest["finished_at"]`, so the flag the HOME PAGE and
  `/api/v1/health` render is still False for ever after a failed last cycle
  and on a Syncthing-less site. The alert kind no longer depends on it
  (`alerts._collector_started_recently` asks `MAX(started_at)` over all poll
  runs itself), but the page does. The fix is the same predicate: compute
  staleness from the last cycle's START, over the kinds this deployment
  actually runs, independently of `ok`, and leave `reachable` alone.
- `dashboard/src/ccsync_dashboard/db.py` (`prune`, dash-collector-alerts-6):
  there is no `DELETE FROM notices` anywhere in the package, so cleared rows
  and one-off `server_error` rows accumulate for the life of the deployment.
  The subject is bounded now, the table is not. A retention clause for rows
  whose `cleared_at` is older than the audit window belongs beside the
  `alert_log` cutoff.
- `dashboard/src/ccsync_dashboard/app.py` (the 500 handler, line ~1289,
  dash-collector-alerts-6): it passes `request.url.path`. Passing
  `route=request.scope["route"].path` when the scope has one (it does NOT
  for an exception inside a mounted sub-app) would give the notice the exact
  route template instead of two segments. `record_server_error` already
  takes the keyword and is safe without it.
- `broll/web/app/routes_share.py` (dash-collector-alerts-6, the verdict's
  suggestion): a targeted 500 handler inside the share sub-app would stop
  the token leaving that app at all. Redaction here is the belt.

### Owner decisions
- A quiet `out_of_tree` finding for a project outside the tree still appears
  on the Alerts page and in the topbar count while its ledger row is open,
  because it IS an open condition. It is never mailed or digested again. The
  alternative (drop it from the page too) would mean an owner cannot see why
  the row is open. Say if you would rather the page hid it as well.
- `MAX_SEND_ATTEMPTS_PER_SLOT = 3`: three tries at a weekly report or a
  daily heartbeat before the slot is given up. Higher costs more blocked
  collector time against a dead SMTP server; lower loses more slots to a
  long outage.
- A restore of a project holding more than 50,000 files is now REFUSED
  rather than silently partial. That is the verdict's preferred form and
  matches the module's posture, but it does mean an owner with a very large
  project gets the printed commands instead of a button.
- `record_server_error`'s fallback subject is the first two path segments,
  so every unhandled 500 under `/api/v1/...` now shares one notice row
  (`/api/v1/… (RuntimeError)`) instead of one per route. The full path is
  still in the container log. Wiring the route template through app.py (the
  OWED item above) restores the detail safely.
