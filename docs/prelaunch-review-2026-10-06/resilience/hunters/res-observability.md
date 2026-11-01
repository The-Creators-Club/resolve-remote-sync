# Pre-launch resilience review, lens res-observability (2026-10-06)

Question asked: when something fails at a customer site we cannot reach, does
the failure SURFACE (alert / notice / tray line, to the right person, with the
next action), or does it only reach a log? Honest NOT CHECKED vs OK, alert
sinks failing quietly, notices nobody clears, triage agent failure modes.

Read: `dashboard/src/ccsync_dashboard/alerts.py` (settings, `sink_deliverable`,
heartbeat/weekly scheduling, `scan`, `Ctx`, `_transmit`/`send`/`deliver`,
`run_cycle`, smtp/webhook senders), `notices.py` (`run_checks`, collector job
notices, sink notice, server crash check, `RESOLVE_RULES`), `db.py` notice
evidence (`_mark_notice_checked`, `notice_check_times`, `alert_recently_sent`,
`last_alert_at`), `ui.py` `_notices_context` + `health_notices.html` /
`home_problems.html`, `invariants.py` invariant 15, `setup_engine.py` alerts
task, `app.py` `CollectorWatchdog` / `_exit_for_restart` / body limits,
`api.py` `/report` refusal stamping and `/health`, `triage.py` run/scheduling,
companion `tray.py` `_reporter_line`, `reporter.py` failure path, companion
`config.py` load fallback. Probed `deliver()` against a temp database with a
failing then recovering webhook opener (dashboard venv, collector stopped).
Checked against docs/RESILIENCE_SWEEP_2026-08-28.md, docs/USABILITY_RESILIENCE_SWEEP_2026-09-03.md
(+ both RES.md), KNOWN_BUGS.md, docs/bug-hunt-2026-09-24.md.

Not covered: companion lane-by-lane error classification, Resolve-side surfaces
(the RES.md lists already carry the open Resolve items: RES-3/RES-22 wedged
bridge, RES-14, RES-17), b-roll/music/ytdl SPA error surfaces, triage_mail reply
path in depth.

### res-observability-1 - An alert that fails to send during a channel outage is never sent again (warns) or is a day late (errors)
- Severity: high
- Confidence: CONFIRMED (probed)
- Where: dashboard/src/ccsync_dashboard/alerts.py:4906-4922 (`_is_open`, ok_only=False), 5084-5091 (warn + was_open -> skipped), 4895-4897 (`send` dedup ok_only=False), 448-496 (`_requeue_undelivered` only on none -> configured); db.py:7477-7497
- What: every send attempt, failed or not, writes an `alert_log` row, and `_is_open` / the dedup read ANY row. A WARN finding whose first send failed (SMTP relay down for ten minutes, app password expired, Slack webhook revoked then re-created) is therefore "open and already said": `deliver` counts it as still_open and never transmits it again until the condition clears and recurs. An ERROR finding waits out the 24 h dedup window. A failed "cleared" message is recorded as the `.ok` row and is never retried either. The only re-queue (`_requeue_undelivered`) fires when the sink goes from `none` to configured, not when a broken configured channel is fixed (password re-saved, URL corrected).
- Scenario: probe: webhook sink configured, opener raises URLError for one cycle with a warn `ingest_staging` finding open; opener then succeeds. Cycles 10 minutes and 2 days later: `sent 0 failed 0`, webhook calls 0; the only ledger row is the ok=0 failure. Warn kinds affected include `fleet_halt`, `crashes`, `thread_restarts`, `upgrade_reverted`, `ingest_staging` (footage waiting in a drop folder), `out_of_tree`, `jobs_abandoned`, `file_move_expired`, `rollout_stalled`. The owner, who has no reason to open the dashboard because mail is "working again", never hears of any of them.
- Recommendation: make "said" mean DELIVERED for the open/dedup decision: `_is_open` and the delivery dedup should treat a failed row as not-yet-said (bounded retry, e.g. `_retry_due`'s attempts-per-window rule already used for weekly/heartbeat), so a finding is retried each cycle a few times and then hourly until one attempt succeeds. Also re-file failed rows as `.undelivered` (as `_requeue_undelivered` does) whenever the channel settings or SMTP password are saved, and after the first successful send following a failure. Retry failed recoveries the same way.
- Known: not recorded (res-fleet-4 fixed the same hole for weekly/heartbeat only; DDIAG-4 fixed it for the none -> configured case only).

### res-observability-2 - The dashboard restarting itself leaves no durable trace, so a crash-looping server looks healthy
- Severity: medium
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/app.py:432-495 (`CollectorWatchdog.check`, wedged path), 498-511 (`_exit_for_restart`); notices.py:1010-1062 (`_check_server_crashes` counts only files newer than `_PROCESS_STARTED`); collector.py:2409-2430 (watchdog restarts held in memory); alerts.py:4248-4261
- What: when the collector wedges past `WATCHDOG_WEDGED_SECONDS` (900 s) or dies more than the restart limit, the process `os._exit`s with nothing written: no notice, no crash file, no meta row. The replacement process starts with `watchdog_restarts = 0`, `_check_server_crashes` only counts crash files written since THIS boot (so it clears the card about the crash that killed the predecessor), and `collector_stale` cannot fire because the wedge is gone. During each wedge the alerts pass runs on the wedged thread, so nothing is sent then either.
- Scenario: an NFS/SMB mount under the tree hangs on stat; every collector cycle wedges in the tree walk, the watchdog exits, Docker restarts, the web UI is up for 15 minutes in every 16 and green each time it is looked at. No alert, no notice, no line on the home page; the only evidence is `docker inspect` RestartCount on a NAS the vendor cannot reach. With the heartbeat off (the default, see res-observability-3) the owner has no signal at all.
- Recommendation: before `_exit`, write a meta row (or a small file under `<data>`) naming the reason and time; at boot, count exits in the last 24 h from it and raise an error notice + alert ("this server restarted itself N times today: <reason>") that survives restarts. Make `_check_server_crashes` count crash files from the last 24 h rather than since this boot.
- Known: not recorded (REL-6 covers the OTA boot watchdog, not wedge exits).

### res-observability-3 - "The server itself is down" reaches nobody by default: the dead-man heartbeat is off and the setup gate never offers it
- Severity: medium
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/alerts.py:280-284, 297 (`alerts_heartbeat` default "0"), 880-918 (`heartbeat_due`); setup_engine.py:1567-1614 (alerts task asks only for a destination); api.py:1579-1620 (`/api/v1/health` open liveness, no doc pointing a monitor at it)
- What: every alert is composed and sent by the thing being watched. A stopped container, a powered-off NAS, a collector crash loop (res-observability-2) and a healthy quiet fleet all look identical: no mail. The daily heartbeat exists to make that silence meaningful but is opt-in and absent from the setup checklist, and there is no push-style integration (a ping URL for healthchecks.io / Uptime Kuma) or documented external monitor for the open `/api/v1/health` liveness. Editors' trays do eventually say "the dashboard has not accepted a report", but that tells the editor, not the person who can restart the server.
- Scenario: a new customer completes setup with an email destination, never visits Settings -> Alerts again. The NAS reboots after a power cut and the app does not come back. Lanes keep running on cached plans; nothing is shared for new ticks; no mail arrives, which reads as "all quiet" for weeks until an editor complains.
- Recommendation: default the heartbeat ON whenever a sink is configured (or make it a step in the setup alerts task with a clear "if these stop, the server is down" sentence), and add an optional outbound "check-in URL" (GET on every successful alerts pass) so a customer or the vendor can use any dead-man service. Document pointing an uptime monitor at `/api/v1/health` (`ok`).
- Known: KNOWN_BUGS DDIAG-17 records the deliberate "default off" decision; worth revisiting for commercial sites.

### res-observability-4 - A notice check that starts failing keeps showing [ OK ] for ever
- Severity: medium
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/db.py:3775-3809 (`_mark_notice_checked`, `notice_check_times`), ui.py:1835-1855 (`checked = set(db.notice_check_times(conn))`), templates/partials/health_notices.html:48 and home_problems.html:38; notices.py:198-207 (`run_checks` logs and continues)
- What: the WHAT THE SERVER CHECKS panel renders `[ OK ]` for any kind that has EVER been stamped, with no age test. `run_checks` isolates a raising check with `log.exception` and leaves its notices alone, so once a check raises every cycle (an OSError on the NAS mount in `_check_tree`, a schema drift in `_check_accounts`, a `disk_usage` failure in `_check_dashboard_space`), its kind keeps the stamp from the last good pass and reads `[ OK ]` indefinitely. The notices pass as a whole still reports success to the collector, so `collector_cycle_failed` / `collector_kind_failed` never fire either. This is the "unchecked rendered as fine" rule the panel exists to enforce, worn by the passage of time.
- Scenario: the tree canary check starts raising on a permission change on the projects dataset; the home panel shows `projects_dir_missing ... [ OK ]` for months while the condition it guards is undetectable; only the container log knows.
- Recommendation: store the stamp as a time and render `[ NOT CHECKED since <date> ]` when it is older than ~3 notice cycles; additionally record a `notice_check_failed` (error) notice keyed by the check name from `run_checks`' except branch, so a check that raises is itself a finding that is mailed (mirroring alerts' `check_failed`).
- Known: not recorded.

### res-observability-5 - Warn-severity notices are never pushed to anyone, not even in the weekly report
- Severity: medium
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/alerts.py:2197-2222 (`_check_notices` mails `severity='error'` only), 4512-4700 (`compose_weekly` has no notices section); db.py:3495-3615 (NOTICE_KINDS)
- What: notices of severity warn reach only someone who opens the dashboard home page. Several have no alert-kind twin: `pending_device_approval` (a computer has waited over 24 h to be approved into the sync network, so its lane C never syncs), `feature_not_mounted` (b-roll / music / YouTube / cards did not start on this server), `project_links_failed`, `share_without_plan`, `unreadable_project_marker`, `machine_trash_oversize`, `ignored_report_sections`, `collector_watchdog_restart`. The weekly report summarises alerts and the protection panel but not open notices.
- Scenario: a customer adds a new editor; the device sits pending; the editor's lane C stays empty for a week; the owner, who reads only the mails, never hears of it. Or an image update leaves the cards mount broken: editors get a missing menu entry, the owner gets nothing.
- Recommendation: add an "OPEN ON THE DASHBOARD" block to the weekly report listing every open warn notice with its age and fix, and/or promote the ones that block an editor (`pending_device_approval`, `feature_not_mounted`) to a warn alert kind once older than a day.
- Known: not recorded.

### res-observability-6 - A report the dashboard rejects as malformed (422/413) leaves no trace, and the admin is told the computer is switched off
- Severity: medium
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/api.py:10144-10147 (`payload: ReportIn` validated by FastAPI before the handler), 10202-10208 (only identity refusals call `db.stamp_report_refused`); app.py:936-941 (413 before the route); alerts.py:1580-1606 (`_check_silent`'s fix: "check the CC Sync tray icon is running"); companion tray.py:3581-3626 (generic message for any non-401/403 status)
- What: `report_refused_at` is stamped only for a credential refusal. A wire-shape mismatch (pydantic 422, the exact failure that held companion 0.9.71 on 2026-09-11) or an oversize body (413) is answered before the route body runs, so nothing is recorded: no notice, no stamp, only an access-log line. The machine goes dark and `machine_silent` tells the admin to check the computer is on. The editor's tray says only "the dashboard has not accepted a report for 3h", with no hint that the server is refusing the content.
- Scenario: a customer runs a companion build a step ahead of their dashboard (or vice versa) and one field's type differs; every editor on the new build goes silent at once; the admin chases power and network on every desk.
- Recommendation: add a `RequestValidationError` handler (and the 413 path) for `/api/v1/report` that, when the credential headers verify, stamps `report_refused_at/reason` with "the server could not read this computer's report (field X)" and files a notice; have `_check_report_refused` render that reason so the fix names "update the dashboard / the companion". On the companion, name a 4xx other than 401/403 as "the server refused this computer's report: tell your admin, the two versions do not match".
- Known: not recorded (DASH-2 covers the identity half only).

### res-observability-7 - The alerts page suggests SMTP port 465, which the sender cannot speak: the channel times out with no hint why
- Severity: medium
- Confidence: CONFIRMED (code read; smtplib behaviour)
- Where: dashboard/templates/partials/admin_alerts.html:134 ("or 465 for mail servers that want it"); dashboard/src/ccsync_dashboard/alerts.py:4761-4821 (`_send_smtp` always `smtplib.SMTP`, optional STARTTLS; no `SMTP_SSL`); triage_mail IMAP unaffected
- What: port 465 is implicit TLS. `smtplib.SMTP(host, 465)` waits for a plain-text 220 greeting the server never sends, so every send and every "Send a test" fails after the 20 s timeout as "could not send through <host> (SMTPServerDisconnected/TimeoutError ...)". The page's own hint leads a customer there, and the error does not say "use 587, or switch to implicit TLS". Each failing send also spends 20 s of the 120 s per-pass budget.
- Scenario: a customer on a provider documenting 465 (common for business mail hosts) sets it as the page suggests; the setup alerts task shows green (it checks only that fields are filled); invariant 15 goes red with a timeout string; the customer cannot tell what to change, and alerting never works.
- Recommendation: use `smtplib.SMTP_SSL` (verified context) when the port is 465 or a new "implicit TLS" option is set; until then remove 465 from the hint and make the timeout error on port 465 say "port 465 needs implicit TLS, which this server does not support: use 587 with STARTTLS".
- Known: not recorded.

### res-observability-8 - Unreadable inputs to the alerts scan read as "nothing wrong", and open alerts are mailed as cleared
- Severity: low
- Confidence: PLAUSIBLE (code read; trigger needs a per-query sqlite error while Ctx itself builds)
- Where: dashboard/src/ccsync_dashboard/alerts.py:1308-1320 (`_rows` returns [] on ANY sqlite3.Error, 27 call sites), 1166-1171 (`rollout` -> channels []), 1236-1242 (`plan_slugs` -> {}), 1252-1255 (`withheld` -> {}); recovery pass 5132-5170
- What: `_rows` was written so a MISSING table (an older migration) reads as nothing to report, but it swallows every sqlite error, including I/O errors, "database is locked" and "no such column" after a half-applied migration. Same for several `Ctx` reads. A check that silently got [] produces no findings, its kind counts as checked, and `deliver`'s recovery pass mails "this has cleared, no action is needed" for every open subject of that kind, then re-raises them as new on the next good cycle.
- Scenario: a transient read failure on the `notices` table during one alerts pass: every open error notice (`notice_error`) is mailed as cleared, and as new again ten minutes later; the owner learns to ignore "cleared" mails.
- Recommendation: narrow `_rows` to "no such table" (return []) and let every other error raise so the kind becomes `check_failed` (which already keeps the recovery pass off its subjects); have the swallowed `Ctx` reads set a flag that makes their dependent checks raise rather than return [].
- Known: not recorded.
