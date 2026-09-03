# Dashboard self-diagnosis and fleet jobs

## Summary

This is the best-written surface in the repo: every notice and alert kind
carries a diagnosis, a consequence and a named next action, the tri-state
(`NOT CHECKED` is never `OK`) is applied consistently across notices,
invariants and protection, and `jobs.explain` is a model of an explainable
scheduler. The usability gaps are therefore not in the copy but in the
WIRING: fleet jobs are the one subsystem with no notice kind, no alert kind
and no invariant, so a queue nothing drains is invisible outside one admin
page that hides abandoned jobs entirely; a failed `/broll`, `/music`, `/ytdl`
or `/cards` mount is announced by a link silently disappearing from the
topbar; and the alarm itself ships OFF with nothing on the protection panel
(the "a safety net is not there" panel) saying so. The biggest resilience
risk is that alert delivery runs in series on the collector thread with no
per-cycle budget: ~46 open findings against a mail server that hangs rather
than refuses exceeds the 900 s wedged-watchdog threshold and RESTARTS THE
CONTAINER, once per cycle, for ever. The best cheap wins are a delivery
budget, a "no alert sink" protection line, and a staleness cutoff on
`machine_silent` (today a retired laptop mails the owner an ERROR every day
for ever, which is how an alarm gets ignored).

## Findings

### DDIAG-1: a hanging SMTP server restarts the container, in a loop
- **Lens:** resilience
- **Who:** owner / admin
- **Where:** `dashboard/src/ccsync_dashboard/alerts.py:106` (`SEND_TIMEOUT_SECONDS = 20.0`), `alerts.py:1962` (`deliver` loops over every finding), `app.py:265` (`WATCHDOG_WEDGED_SECONDS = 900.0`), `app.py:383`
- **Today:** `deliver()` calls `send()` once per finding, in series, on the collector thread. The 20 s ceiling is documented as being per delivery ("an SMTP server that hangs rather than refuses must not park enforce"), but there is no ceiling on the PASS. `scan()` allows `MAX_FINDINGS_PER_KIND = 40` per kind across 42 kinds, and every `error` re-sends once a day, so a daily cycle on an unhappy fleet legitimately has dozens of sends. 46 × 20 s = 920 s > the 900 s wedged threshold, at which the watchdog logs "wedged inside one call" and calls `os._exit(75)`. On restart the same cycle is due again.
- **Proposed:** a per-cycle delivery budget in `deliver()` (`ALERT_CYCLE_BUDGET_SECONDS = 120`): stop sending when the budget is spent, leave the rest undelivered (they are still open, they re-send next cycle), and return `note = "12 of 46 alerts sent this pass; the mail server is slow"` so the collector health panel says it. Add a sink circuit breaker: three consecutive send failures parks the sink for an hour, recorded in `alert_log` and rendered on the Alerts page as `[ SINK PAUSED ]` with a `[ TRY AGAIN NOW ]` button.
- **Effort:** S   **Value:** critical   **Confidence:** high
- **Related:** `alerts.send`'s own "never raises for a delivery failure" rule; ops-efficiency-5 is cited for the per-send timeout but not for the pass.

### DDIAG-2: fleet jobs are absent from every diagnosis channel
- **Lens:** both
- **Who:** owner / admin
- **Where:** `alerts.py:1424-1512` (42 kinds, none about `jobs`), `db.py:2561-2645` (`NOTICE_KINDS`, none about `jobs`), `invariants.py:653-745` (10 invariants, none about `jobs`), `alerts.py:1663` (the weekly report has no jobs section)
- **Today:** grep for `job` in `alerts.py` returns only the COLLECTOR's background jobs. The whole fleet queue, whose own module docstring says "THE FAILURE MODE OF A SCHEDULER IS INVISIBLE: a scheduler that quietly assigns nothing looks exactly like a fleet with nothing to do" (`jobs.py:19`), is diagnosed nowhere except `/admin/jobs`, which nothing links to from the home page and which the owner has no reason to open.
- **Proposed:** three alert kinds fed from state that already exists (`db.queue_depth`, `jobs.explain`): `jobs_starved` (SEV_WARN, "work is queued and nobody is taking it": oldest queued job older than 6 h with `reason_code` in `no_capable_machine`/`kind_not_allowed`/`halted`, fix "Open Settings, JOBS: the WHY line under each job names the computer that would have to change"), `jobs_abandoned` (SEV_WARN, "the fleet gave up on some work", fix "Settings, JOBS, [ SHOW FINISHED ], then [ TRY AGAIN ] once the machine that failed it is fixed"), `jobs_pinned_no_executor` (SEV_ERROR, see DDIAG-6). Add one line to `compose_weekly`: `JOBS: n queued, n running, n abandoned this week`.
- **Effort:** M   **Value:** high   **Confidence:** high
- **Related:** `docs/TIMELINE-CARDS-INTO-CCSYNC.md` phase 4 §6; `docs/API.md` §6c.

### DDIAG-3: `machine_silent` mails the owner an ERROR every day for a laptop that is simply gone
- **Lens:** both
- **Who:** owner
- **Where:** `alerts.py:657-673` (`_check_silent`), `alerts.py:1975` (errors repeat daily)
- **Today:** any machine row whose `received_at` is over 24 h old is an `error` finding for ever, and `error` severity means "re-alerts once a day for as long as it is still true (an outage nobody acted on must not go quiet)". A machine that has been retired, reinstalled under a new hostname, or belongs to an editor on a three-week shoot produces 21 identical emails. The fix text is "Ask that editor to check the CC Sync tray icon is running and that the computer is on and online" and never mentions that the row can be removed.
- **Proposed:** (a) stop alerting after `SILENT_GIVE_UP_DAYS = 14`: past that the machine is a standing NOTICE (`machine_forgotten`, warn) on the home panel rather than a daily mail; (b) add to the fix: "If that computer is gone for good, open FLEET and press [ FORGET ] on its row so this stops." `[ FORGET ]` already exists at `templates/partials/fleet_grid.html:370` and nothing in the alert points at it.
- **Effort:** S   **Value:** high   **Confidence:** high
- **Related:** CR-76 (delete a user / forget a computer, dashboard 0.7.9).

### DDIAG-4: turning the alert sink on never delivers the warnings that were already open
- **Lens:** resilience
- **Who:** owner
- **Where:** `alerts.py:1918-1922` (sink `none` records `ok=0` "no sink configured"), `alerts.py:1945` (`_is_open` reads `last_alert_at(..., ok_only=False)`), `alerts.py:1970` (`if was_open and severity != SEV_ERROR: continue`)
- **Today:** on the vendor default (`alerts_sink = none`) every finding still gets a row in `alert_log`, deliberately, so the page can say nobody was told. But that row is what `_is_open` reads. The day an admin configures SMTP, every `warn` that has been open since before then is already "said" and will never be sent - not until it clears and comes back. Errors survive (they repeat daily); every warn kind (17 of the 42, including `folders_unfiltered`, `versions_behind`, `ingest_staging`, `protection_unverifiable`) is silently swallowed on the one day the owner is most likely to be watching for a first message.
- **Proposed:** file the no-sink record under a distinct kind suffix (`kind + ".undelivered"`) so it shows on WHAT WAS SENT but does not count as raised; or, simpler, have `set_settings` write a `.ok` recovered row for every open subject when `alerts_sink` changes away from `none`, so the next scan re-raises everything with a real sink behind it. Say it on the page: "Saved. The next check will send everything that is currently open."
- **Effort:** S   **Value:** high   **Confidence:** high

### DDIAG-5: the recovery restore blocks the entire dashboard, with no progress
- **Lens:** both
- **Who:** admin/owner (Settings → RECOVERY)
- **Where:** `ui.py:1409` and `ui.py:1431` (`async def partial_admin_recovery_preview` / `..._restore`), `recovery.py:251` (`_walk`, up to 50,000 files), `recovery.py:323` (up to `MAX_RESTORE_FILES = 20_000` `shutil.copy2` calls), `dashboard/deploy/run.sh:396` (`--workers 1`)
- **Today:** the htmx handlers are `async def` (they only await `_form(request)`), so both the double `os.walk` and the whole copy run ON THE EVENT LOOP of a single-worker uvicorn. While an owner restores 8,000 files from a snapshot over NFS, the fleet page, `/api/v1/report` from every companion and the container healthcheck all block. The admin meanwhile sees a spinner with no counter and no way to cancel; the API twins (`api.py:8093`, `api.py:8104`) are plain `def` and correctly land in the threadpool.
- **Proposed:** drop `async` from the three UI handlers and read the form with the same sync pattern the other partials use (or `await run_in_threadpool(...)` around the recovery call, which `api.py` already imports). Then make the restore progressive: write a `recovery_restore_progress` meta row per file batch and have the partial poll it, so the page can say "copied 812 of 8,000 files into FF5/.restored-20260903T1104".
- **Effort:** S (async) / M (progress)   **Value:** high   **Confidence:** high

### DDIAG-6: a pinned job is stranded for ever if `/cards` fails to mount on the next boot
- **Lens:** resilience
- **Who:** admin
- **Where:** `app.py:593-608` (`if executor.available(): ... db.release_pinned_jobs(conn)`), `db.py:8239` (`release_pinned_jobs` clears rows held by `PIN_HOLDER`), `db.py:8162` (`pinned_jobs` skips rows with a `claimed_machine`), `db.py:8190` (`pin_progress`: "NO LEASE IS EXTENDED")
- **Today:** the boot-time release of rows held by a previous run is INSIDE the `executor.available()` branch. The Timeline Cards mount is optional and fails to `absent` for ordinary reasons (`cards.py:346-357`: vault bind mount missing, checkout not shipped, import error - the class of thing an image update causes). A container that goes down mid-encode and comes back with `/cards` unmounted leaves `state=pinned, claimed_machine='(dashboard)'` rows that `pinned_jobs()` will never return again, on no lease and with no expiry. `jobs.explain` answers "the fleet could not finish this, so it is pinned to the dashboard's own worker" - which is now false - and `[ CANCEL ]` only records `cancel_requested_at` for a worker that does not exist. There is no heartbeat check on pinned rows anywhere.
- **Proposed:** move `release_pinned_jobs` out of the `available()` branch (release always, at boot). Add a staleness rule: a pinned row whose `heartbeat_at` is older than an hour with no executor becomes `abandoned` with `last_error = "pinned here, and this dashboard has no Timeline Cards worker any more"`, which is visible and honest. Have `_terminal_summary` say "pinned, but nothing here can run it: {executor.why_not()}" when `can_pin` is false.
- **Effort:** S   **Value:** high   **Confidence:** high
- **Related:** `docs/TIMELINE-CARDS-INTO-CCSYNC.md` §4.4 rule 5; CR-100/CR-101 are the recent evidence that the cards mount moves.

### DDIAG-7: a mounted app that fails to mount says so nowhere a human looks
- **Lens:** both
- **Who:** owner / editor
- **Where:** `app.py:1209-1244` (four `*_status` values), `templates/partials/topbar.html:97-121` (`{% if broll_mounted %}` … ), `cards.py:346-357`, `db.py:2561` (`NOTICE_KINDS` has no mount kind)
- **Today:** each of `/broll`, `/music`, `/ytdl`, `/cards` computes a careful tri-state with a sentence in `detail` ("the vault root is not mounted (/vault)", "the checkout did not import (ModuleNotFoundError: …)"). That sentence goes to the container log and to the authenticated `/api/v1/health` only. On the page, the topbar link simply DISAPPEARS. An editor asks "where has B-ROLL gone" and the owner has no page that answers; the self-diagnosis panel, whose whole premise is that a refusal must not end in a log, has no kind for the four biggest refusals the dashboard makes at boot.
- **Proposed:** one notice kind, `feature_not_mounted` (severity `warn`, subject the mount name), written once at boot from the four statuses, body "The B-ROLL page is not available on this server: {detail}. Editors will not see the link in the menu.", fix "Check the container's bind mounts (docs/DOCKER.md), then restart the dashboard." Registered WITH its writer, per the registry's own rule.
- **Effort:** S   **Value:** high   **Confidence:** high

### DDIAG-8: every "what to do" is prose naming a page, and nothing is a link
- **Lens:** usability
- **Who:** owner (FLEET → PROBLEMS THE SERVER FOUND)
- **Where:** `templates/partials/notices.html:26` (`WHAT TO DO: {{ n.fix }}`), `notices.py` passim ("Approve it on Settings, Users, in the pending devices list", "Update the dashboard (Settings, Packages, [ UPDATE THE DASHBOARD ])", "Open Settings, Invariants to see which check last ran")
- **Today:** the owner's only alarm panel tells a non-technical person to navigate by memory to a page whose name is written in prose, three levels into a twelve-entry settings strip. Every one of these targets is a URL this codebase knows.
- **Proposed:** an optional `href` on `db.notice()` (a column, or a `NOTICE_KINDS` entry keyed by kind since the destination is a property of the KIND, not of the row - no migration needed). Render it after the sentence as `[ TAKE ME THERE ]`. `pending_device_approval` → `/admin/users`, `feed_unreachable` → `/admin/packages`, `invariant_*` → `/admin/invariants`, `protection_*` → `/admin/protection`, `enforce_refusal` → the project page. Keep the prose: the mail body has no links to offer.
- **Effort:** S   **Value:** high   **Confidence:** high

### DDIAG-9: a decommissioned machine's year-old disk reading is a permanent warning
- **Lens:** resilience
- **Who:** owner
- **Where:** `notices.py:483-516` (`_check_machine_space`)
- **Today:** the query selects `disk_at` and `trash_bytes` and then never reads `disk_at`. Every row in `machine_state` is judged on whatever number it last reported, however old. A machine that reported 40 GB free and then stopped reporting (reinstalled, retired, sold) holds an un-clearable `machine_disk_low` warn on the home panel for ever: the condition can only clear if the same machine reports a bigger number. Same for `machine_trash_oversize`.
- **Proposed:** skip rows whose `disk_at` is older than `MACHINE_DISK_STALE_HOURS = 48`, and clear their notices, on the module's own "could not check is not fine" logic inverted correctly: this is not "could not check", it is "this reading is not about now". A silent machine is `machine_silent`'s business, and saying it twice in different words is worse than saying it once.
- **Effort:** S   **Value:** med   **Confidence:** high

### DDIAG-10: the server's own crash reports have no reader
- **Lens:** resilience
- **Who:** owner / developer
- **Where:** `crash_report.py:118` (`write_report` → `<data>/crashes/<ts>-<thread>.json`), `crash_report.py:283` (the thread excepthook), and nothing anywhere reads that directory
- **Today:** the module exists because "the collector runs in a BACKGROUND THREAD… a thread excepthook that writes the traceback somewhere persistent is how you find out WHY, days later". Editors' crash COUNTS ride the report channel and become the `crashes` alert (`alerts.py:835`); the dashboard's own crash files are visible only to somebody with a shell in the container - which is exactly the person this whole sweep assumes does not exist. `collector_stale` and `watchdog_restart` report the symptom and never the file that holds the cause.
- **Proposed:** count the files in `crash_dir()` newer than this boot in `notices.run_checks` as `server_crash_report` (error): "This server's own background tasks have crashed 3 time(s) since it started. The details are saved on the server.", fix "Send us the crash files: Settings, Diagnostics, [ DOWNLOAD CRASH REPORTS ]." Add that button (a zip of the newest 20, already redacted by `crash_report.redact`).
- **Effort:** M   **Value:** high   **Confidence:** high
- **Related:** DASH-2; APP-6 built the editor-side half only.

### DDIAG-11: the JOBS page hides everything that failed, and has no "try again"
- **Lens:** usability
- **Who:** admin
- **Where:** `ui.py:2395` (`db.list_jobs(conn, state="open", limit=100)`), `templates/partials/admin_jobs.html:40` ("Nothing is queued or running.")
- **Today:** `failed` and `abandoned` are terminal states and the page lists open jobs only. After the fleet spends the retry budget on twelve whisper jobs (a machine with a broken ffmpeg is the documented case) the operator's view of the queue reads "Nothing is queued or running." There is no count of what was abandoned, no link to it, and no way to re-queue one: `tools/jobs.py` can `submit` but the admin would have to retype the root, rel path and episode from nothing.
- **Proposed:** a `[ SHOW FINISHED ]` toggle listing the last 24 h of terminal jobs with their `last_error`, and a `[ TRY AGAIN ]` per abandoned row that re-queues the SAME `inputs` under a new id (never a resurrection of the old row, so the attempt history stays honest). Show the abandoned count in the `[ THE QUEUE ]` head beside queued/running.
- **Effort:** M   **Value:** high   **Confidence:** high

### DDIAG-12: the alerts page runs all 42 checks on every render, including three POSTs that have nothing to do with checking
- **Lens:** resilience
- **Who:** admin
- **Where:** `ui.py:1259-1277` (`_alerts_context` → `alerts.scan(...)`), called from `ui.py:1281` (GET), `ui.py:1518`, `ui.py:1541`, `ui.py:1578` (save / password / test)
- **Today:** `Ctx.__init__` builds the whole `build_editors_view`, and the scan runs 42 checks, on the same connection an admin's page request holds. Saving an SMTP port re-runs the fleet view; so does storing a password; so does sending a test. The invariants page deliberately refused a `[ RE-CHECK NOW ]` button for precisely this reason ("a page an admin can hammer is a page that can park the collector's single thread behind it", `ui.py:1290`), and the alerts page has four such buttons by accident.
- **Proposed:** cache the scan per (connection, minute) or read the LAST scan's findings the way the topbar already reads `db.META_ALERTS_OPEN`; store the findings JSON beside the counts in `alerts.run_cycle` and have the page render those with "checked 4 minutes ago" plus one explicit `[ CHECK NOW ]`.
- **Effort:** S   **Value:** med   **Confidence:** high

### DDIAG-13: the jobs page recomputes the whole fleet's facts once per job, every 15 seconds
- **Lens:** resilience
- **Who:** admin
- **Where:** `ui.py:2395-2407` (`jobs_mod.explain(conn, int(job["id"]), caps)` per job), `jobs.py:812` (`explain` calls `fleet_facts`), `jobs.py:499` ("policy()'s answer for EVERY machine, in five queries"), `templates/admin_jobs.html:21` (`every 15s`)
- **Today:** up to 100 open jobs × 5 queries = 500 queries plus 100 ranking passes per render, every 15 s per open browser tab, on the single-worker process the fleet reports go through. `fleet_facts` was itself written to kill exactly this N+1 for the claim path.
- **Proposed:** give `explain()` an optional `facts=` parameter (it already takes `caps`), build `fleet_facts` once in `_jobs_context` and pass it in. Two-line change, same output.
- **Effort:** S   **Value:** med   **Confidence:** high

### DDIAG-14: a 500 storm writes one database row per request, on the database that is probably the cause
- **Lens:** resilience
- **Who:** owner
- **Where:** `app.py:1136-1143` (a fresh `db.connect` per unhandled exception), `notices.py:672-698` (`record_server_error`)
- **Today:** every 500 opens a new SQLite connection and does a SELECT + upsert + commit. The failure modes that produce sustained 500s are mostly database or disk faults (`notices._DB_FAULT_MARKERS` lists seven of them), so the diagnosis amplifies the outage: N failing requests become N extra writers contending with the collector for the same file. The notice SUBJECT is `f"{path} ({type})"` with the raw request path, so a route with a path parameter that raises produces one unbounded row per distinct value - in a table nothing prunes (see DDIAG-15), and `_check_notices` then turns up to 40 of them into 40 alert deliveries.
- **Proposed:** an in-process rate limiter: keep `{(path, exc class): (count, last_written)}` in module state, write at most once per minute per key with the accumulated count, and drop the write entirely if the last one raised. Normalise the subject through the ROUTE template (`request.scope["route"].path`) rather than the concrete path, so `/partials/project/{slug}/bins` is one row and not one per project.
- **Effort:** S   **Value:** med   **Confidence:** high

### DDIAG-15: `notices` is never pruned, and `server_error` is what makes that unbounded
- **Lens:** resilience
- **Who:** developer
- **Where:** `db.py:6725-6760` (the prune cycle covers `fleet_audit`, `alert_log`, `diagnostics`, `poll_runs`, media tables - not `notices`), `docs/SELF_DIAGNOSIS.md:487`
- **Today:** documented as a known gap on the argument that the table "grows by distinct `(kind, subject)` only, so it is bounded by what the fleet has ever done". That argument holds for every kind except `server_error`, whose subject is a request path (DDIAG-14), and `plan_without_share` / `share_without_plan`, whose subjects are `editor/machine -> slug` triples.
- **Proposed:** one line in the prune cycle: `DELETE FROM notices WHERE cleared_at IS NOT NULL AND cleared_at < cutoff(days=90)`. Never touch open rows.
- **Effort:** S   **Value:** low   **Confidence:** high

### DDIAG-16: nothing ever says "the alarm is switched off"
- **Lens:** usability
- **Who:** owner (a new customer, most of all)
- **Where:** `alerts.py:150` (`"alerts_sink": SINK_NONE` is the default), `protection.py:602-687` (eight protection lines, none about being told)
- **Today:** the vendor build ships with no sink, which is right. But the panel whose entire job is "a safety net this server cannot positively verify renders as MISSING, never as silence" has lines for snapshots, signing keys, backup drills and versioning - and none for the fact that no human will ever be told when any of them break. The only place the state appears is the Alerts page itself, which is where somebody who already knows about alerts goes.
- **Proposed:** a ninth `ProtectionLine`, `alerts_sink`: title "somebody is told when this breaks", matters "whether a problem here reaches a person", consequence "This server checks 42 things every ten minutes and writes down what is wrong. With no way to send it, all of that waits until somebody opens the page.", fix "On Settings, Alerts: choose mail or a webhook, then press [ SEND A TEST ]." `ok` only when a sink is set AND `alert_log` holds a successful send in the last 30 days - a mailbox that stopped accepting mail in March is the same hole.
- **Effort:** S   **Value:** high   **Confidence:** high

### DDIAG-17: silence is ambiguous - there is no dead-man's heartbeat
- **Lens:** resilience
- **Who:** owner
- **Where:** `alerts.py:2035` (`run_cycle` is the ninth collector kind), `collector.py` (the alerts kind runs on the collector thread), `alerts.py:1424` (no heartbeat kind)
- **Today:** every alert is composed and sent BY the thing being monitored. A container that is off, a collector thread that exited past its restart limit (`app.py:347`, exit 75 with no restarter behind it), a NAS that is powered down or a Tailscale link that is gone all produce exactly the same experience as a healthy fleet: no mail. The weekly report is the only proof of life and it is a week wide.
- **Proposed:** a daily "still here" line: when `alerts_sink` is set and `alerts_heartbeat` is on, send one short message a day (subject `CC Sync: all quiet - 8 computers, 0 problems`). It costs one mail a day and converts silence from ambiguous to alarming, which is the only thing that makes an alarm system trustworthy. Say so on the Alerts page: "If these stop arriving, the server itself is down."
- **Effort:** S   **Value:** high   **Confidence:** med

### DDIAG-18: a recovered message can be lost on a busy ledger
- **Lens:** resilience
- **Who:** owner
- **Where:** `alerts.py:2005-2013` (`_open_subjects` → `db.fetch_alerts(conn, limit=500)`)
- **Today:** "every (kind, subject) currently in an alerted state" is derived from the newest 500 `alert_log` rows. A fleet that has produced more than 500 rows since a condition was raised (the `notice_error` kind alone can emit 40 per cycle) drops that subject out of the window, so its RECOVERED message is never sent and the owner is left believing something is still broken. `_is_open` itself is exact; only the enumeration is windowed.
- **Proposed:** enumerate with SQL over the whole table (`SELECT DISTINCT kind, subject FROM alert_log WHERE kind NOT LIKE '%.ok'`) rather than a limited fetch, or keep an `open_alerts` meta set alongside `META_ALERTS_OPEN`.
- **Effort:** S   **Value:** med   **Confidence:** med

### DDIAG-19: montage sessions accumulate on the volume the dashboard warns about
- **Lens:** resilience
- **Who:** owner
- **Where:** `cards_ai.py:496-501` (`<data>/cards_sessions/<id>.json`), nothing deletes them; `notices.py:519` (`_check_dashboard_space`, floor 2 GB, severity error)
- **Today:** each montage conversation is stored whole - the corpus digest plus up to `MAX_TURNS = 40` turns of transcript - as a JSON file beside `dashboard.db`, keyed by a uuid from a sidecar in the vault. Nothing prunes them, nothing counts them, and no page shows how much room they take. The volume they land on is the one whose exhaustion `_check_dashboard_space` calls "one write away from being the thing that is broken".
- **Proposed:** prune in the collector's existing prune cycle: delete session files not modified in 30 days, and cap the directory at 200 files (oldest first). Report the total in the `cards` health block so it is visible before it is a problem.
- **Effort:** S   **Value:** med   **Confidence:** high

### DDIAG-20: `stop_engine` silently accepts an engine that cannot be stopped
- **Lens:** resilience
- **Who:** developer
- **Where:** `cards.py:250-261`
- **Today:** `stop = getattr(engine, "stop", None); if callable(stop): stop()`. A checkout whose engine renamed or lost `stop()` is a no-op with no log line: its library sweep, ffmpeg worker and translation threads survive the dashboard's shutdown, and on a dev reload two engines write to one vault. The code that USES the other repo's seam gets this right - `PinnedExecutor.available()` treats a missing `fleet_execute` as "no executor at all" and says why (`cards_exec.py:139`) - and the shutdown path does not.
- **Proposed:** `else: log.warning("the Timeline Cards engine has no stop(); its background threads will outlive this app (checkout %s)", src)`, and surface it in `cards.health_block` as `"stoppable": bool(...)`, on the same "name what you cannot verify" rule the rest of this area follows.
- **Effort:** S   **Value:** low   **Confidence:** high

### DDIAG-21: each connected cards agent permanently holds one of the 40 shared threadpool slots
- **Lens:** resilience
- **Who:** editor (indirectly - the whole fleet)
- **Where:** `cards_tunnel.py:256-267` (a blocking `def` long poll, `wait` up to `MAX_WAIT_SECONDS`), and no `anyio` capacity limiter is set anywhere in `app.py`
- **Today:** the comment is explicit and correct that a blocking `def` beats awaiting on the loop ("one worker per connected agent, and there is one agent per machine"). With Starlette's default limiter of 40 threadpool tokens shared by EVERY sync route in a `--workers 1` process, a fleet where the `cards_agent` role is on across, say, fifteen machines permanently occupies fifteen of them; the rest carry `/api/v1/report`, the fleet partials and the transfers poll. The feature is off everywhere today, so this is a trap set for the rollout rather than a live fault.
- **Proposed:** raise the limiter explicitly at startup (`anyio.to_thread.current_default_thread_limiter().total_tokens = 120`) with a comment naming the long poll as the reason, or cap concurrent agent polls (a semaphore sized from the machine count) and answer the excess immediately with an empty result so the agent re-polls.
- **Effort:** S   **Value:** med   **Confidence:** med

### DDIAG-22: the same fact is worded two ways on two pages, and one of them says "hour(s)"
- **Lens:** usability
- **Who:** owner
- **Where:** `notices.py:62-71` (`_since` → "for about 5 hour(s)"), `alerts.py:440-451` (`_duration_words` → "5 hours"), and "time(s)", "project(s)", "computer(s)" throughout both
- **Today:** the home panel says "The 'enforce' job has been failing for about 5 hour(s)"; the mail about the same job says "5 hours". `(s)` is programmer shorthand in the one panel written specifically for a non-technical reader.
- **Proposed:** move `_duration_words`/`_bytes_words` and a two-line `_plural(n, "project")` into one shared helper module (or import `alerts`' from `notices`) and use them in both. "for about 5 hours", "1 project", "3 projects".
- **Effort:** S   **Value:** low   **Confidence:** high

### DDIAG-23: invariant 8 is a permanent NOT CHECKED whose fix is "nothing to press"
- **Lens:** usability
- **Who:** owner (Settings → INVARIANTS)
- **Where:** `invariants.py:716-727` (`versioning_agrees`, `check=None`, fix "Nothing to press. This one is a code change, tracked as R5 in KNOWN_BUGS.")
- **Today:** one of ten rows on the invariants page is, and will remain until R5 is fixed, a grey NOT CHECKED with a fix that tells the owner to read the developers' bug ledger. A page whose value is that an unchecked row means something has one permanently unchecked row, which is how a reader learns to skim it.
- **Proposed:** either give it the check it needs (have the companion report its `.stversions maxAge` in the report - one integer, and then this is `ok` or `broken` like the others), or move it off the page into a `KNOWN LIMITS` footer: "one fact this server cannot check yet, and why". Do not leave an unactionable row in the list of actionable ones.
- **Effort:** S (footer) / M (report field)   **Value:** low   **Confidence:** high

## Still open from 08-28

- **`notices` rows are never pruned** (`SELF_DIAGNOSIS.md` §12): not built - see DDIAG-15 for why the "bounded by distinct subjects" argument does not hold.
- **DASH-10 half built**: the boot-time `insecure_secret` notice exists; `settings.num()` still falls back silently and token headers are compared unstripped.
- **Some conditions are reported twice** (enforce refusal, deactivation refusal, Syncthing unreachable, ignored sections are each a notice AND an alert, plus `notice_error`): still true, deduped per `(kind, subject)` so it costs one extra row on the Alerts page and no extra mail. Not worth fixing.
- **Two disk floors for one fact** (`health.disk_status` red vs `MACHINE_DISK_FLOOR_BYTES` 50 GB warn): still true.
- **`plan_without_share` has a warm-up period** (needs `Collector._folder_devices` from a completed `config` pass in this process): still true, and correctly renders as not checked.
- **CR-10, `apps` is a plain directory with no snapshot task**: the protection panel now NAMES it (`snapshot_apps`), which was the ask; the NAS-side fix is still not applied.

## Cross-cutting notes

- **For the SYNC/APP agent:** `alerts._check_lane_stalled` is the server-side half of CR-91b ("a lane that never finishes and never errors"). It fires on `state_since` age, so it depends entirely on the companion setting `state_since` honestly - worth confirming from the companion side that a lane wedged inside one `proc.wait()` still refreshes it.
- **For the REL/OPS agent:** `alert_log` is pruned at 120 days (`db.py:5133`) and `_is_open` derives "currently alerted" from it, so a condition open for longer than 120 days re-alerts as brand new. Probably harmless, arguably right, but it is undocumented in `SELF_DIAGNOSIS.md` §7.
- **For the UX agent:** the settings strip is now twelve entries (`templates/partials/settings_nav.html`), five of which (ALERTS, JOBS, INVARIANTS, PROTECTION, RECOVERY) are "what is wrong / what is unsafe" pages built by one sweep. They read as five separate products. A single `HEALTH` hub with five sections would cost one template and would put PROTECTION in front of an owner who has never heard the word.
