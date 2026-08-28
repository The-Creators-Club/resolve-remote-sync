# Self-diagnosis: PROBLEMS THE SERVER FOUND, alerts, and the weekly report

Added 2026-08-28 for `RESILIENCE_SWEEP_2026-08-28.md` wave 4, items 25 (UX-10)
and 41 (SYS-8), widened the same day on the owner's instruction: "make the
server as self-diagnosing as possible. Any errors should be flagged, the
diagnosis should be as clear as possible." Code lives in
`dashboard/src/ccsync_dashboard/notices.py` (what the server FOUND) and
`alerts.py` (what the server would TELL somebody); the ledgers are the `notices`
table (schema v37) and `alert_log` (v38); the pages are the `[ PROBLEMS THE
SERVER FOUND ]` panel on the home page and Settings -> ALERTS.

Everything in this document is dashboard-side. It ships as a dashboard OTA and
needs no companion or installer change. Four alert kinds read report sections
that only a wave 4 companion sends (clips outside the tree, stray project
folders, moved project folders, footage waiting in a drop folder) and simply
stay silent until one does.

## Why any of this exists

The dashboard refuses things for good reasons. A `.ccsync-project` marker
copied onto a folder that already holds three projects is refused, because
setting it up would hide the three; two Syncthing folders over one directory
are refused; an enforce pass that would remove more shares than the safety
limit is refused in full. Every one of those refusals had an excellent
sentence attached, written to a container log a non-technical owner will never
open. The sweep counted sixteen such diagnoses reaching nobody.

And every alarm the dashboard did render was pull-only. Read as a taxonomy,
none of the ~120 entries in `KNOWN_BUGS.md` was discovered by the system
telling anybody; SYNC-17's eighteen hours of a dead sync engine, CR-27a's
eighteen hours, CR-86's two days were each found by the owner happening to
open the page. The dashboard, whose stated job is to tell everyone whether
their footage is syncing, had never once been the discoverer of an outage.

So there are two ledgers now, with one rule between them: **"could not check"
must never render as "fine".** A check that cannot run is its own finding,
and an empty panel says what it checked.

## 1. The two ledgers

| | `notices` (v37) | `alert_log` (v38) |
|---|---|---|
| Written by | `db.notice()` beside the refusal, plus `notices.run_checks()` every collector cycle | `alerts.send()` on every delivery attempt, successful or not |
| One row per | `(kind, subject)`, upserted: `first_seen` kept, `last_seen` bumped, `cleared_at` reopened | attempt, appended |
| Shown on | home page panel, topbar chip, `/api/v1/health` -> `notices` | Settings -> ALERTS "what was sent", weekly report |
| Closed by | the pass that wrote it seeing the condition gone, or `[ DISMISS ]` | never; pruned after 120 days (`db.ALERT_MAX_AGE_DAYS`) |
| Reaches the sink | as the `notice_error` alert kind (severity `error` rows only) | it IS the sink's record |

The alert side does not measure anything the notice side, the fleet view or
the collector do not already know: `alerts.scan()` is a reading of
`api.build_editors_view`, `db.collector_health`, `db.get_feed_state`,
`db.get_fleet_halt`, the release rows and the notices table, composed into
sentences. The gap was never the data.

## 2. PROBLEMS THE SERVER FOUND

Home page, above the fleet grid, admin only, polled every 60 s
(`templates/partials/notices.html`, `ui.partial_notices`). Each open notice
renders as a banner: a severity chip, the subject (a slug, a path, an
`editor/machine`, a device id), the body, and a `WHAT TO DO:` line. The fix is
mandatory - every writer names a button, a page or a command, because a
diagnosis an owner cannot act on is a log line with better placement. When
nothing is open the panel says so and shows only the collapsed `WHAT THE SERVER
CHECKS` list (`partials/notice_checks.html`): every kind in `db.NOTICE_KINDS`
with `[ FOUND ]`, `[ OK ]` or `[ NOT CHECKED ]` beside it. `[ OK ]` needs
EVIDENCE, not just a registry entry: `db.notice_check_times` reads a
`{kind: last_checked}` meta row that `db.notice` / `db.clear_notice` /
`db.clear_notices_of_kind` stamp every time some pass calls them for that
kind, whether or not it found anything, so a kind registered with no writer
behind it -- `plan_without_share` sat in exactly that state until the
resilience sweep 2026-08-28 fix pass gave it one -- renders `[ NOT CHECKED ]`
rather than a false `[ OK ]`.

The topbar carries `[ N PROBLEMS ]` on every full page (admin only, error
severity only, absent at zero: a bar that permanently reads `[ 0 PROBLEMS ]`
stops being read), linking to `/#server-notices`.

**`[ DISMISS ]` hides, it does not fix.** `db.dismiss_notice` sets
`cleared_at` and audits `notice.dismiss`; the next cycle that still sees the
condition calls `db.notice()` again, which NULLs `cleared_at` and the row comes
straight back with its original `first_seen`. A dismissal therefore clears a
diagnosis that has been acted on and cannot silence a live one. The confirm
dialog says exactly that. A dismiss on an id that is no longer open answers
"that notice is already gone. Reload the page." rather than pretending.

A condition that ends clears itself: the pass-shaped writers (provisioning
walks every slug each cycle) call `db.clear_notices_of_kind(kind,
still_failing)` at the end of the pass, and the checks call `db.clear_notice`
when they see the condition gone. A check that RAISES leaves its notices alone
rather than clearing them, for the rule above.

The panel shows at most 25 rows (`db.NOTICE_PANEL_LIMIT`); a fleet with more
open notices than that has one underlying fault, not thirty. Each check caps
itself at 20 subjects (`notices.MAX_ROWS_PER_KIND`).

## 3. What the server checks (notices)

Kinds registered in `db.NOTICE_KINDS`, grouped as the registry groups them.
Severity `error` rows also reach the alert sink through `notice_error`.

**Discovery and provisioning** (written by `collector._provision_slug` /
`_creatable` as they refuse things; cleared at the end of the same pass):

| kind | sev | fires when |
|---|---|---|
| `project_container_marker` | error | a marker sits on a folder that CONTAINS projects; setting it up would hide them, so the projects are missing from the dashboard until the marker in the parent is deleted |
| `project_nested_marker` | error | a marker inside another project |
| `duplicate_syncthing_folder` | error | two Syncthing folders point at one directory; only one is the folder editors are on (fix: delete the other in Syncthing; nothing on disk is removed by that) |
| `duplicate_slug_dirs` | error | two directories carry the same project identity, usually a COPIED folder; the body says whether the dashboard kept the one it knew or is leaving both alone |
| `unreadable_project_marker` | warn | a damaged `.ccsync-project`, so that folder is a project to nobody |
| `provision_failed` | error | a slug's setup raised (fix: look at the other problems first; usually a stray marker) |
| `shared_assets_failed` | error | the LUT library could not be set up |
| `project_links_failed` | warn | a borrowed-folder link could not be resolved |

**The collector itself** (`notices._check_collector_jobs`, the watchdog):

| kind | sev | fires when |
|---|---|---|
| `collector_cycle_failed` | error | a job's LAST run failed (`poll_runs`), one per kind, with `_JOB_MEANING` saying what that failure costs in words ("projects ticked or unticked on this dashboard are not reaching the editors' computers") and the server's own error truncated to 200 chars |
| `collector_db_write_failed` | error | that error names a disk fault (`disk i/o error`, `database or disk is full`, `readonly database`, `database is locked`, ...) |
| `collector_watchdog_restart` | warn | `app.CollectorWatchdog` had to restart the dead collector thread; written on its own connection so it can never stop the restart |
| `syncthing_unreachable` | error | `collector_health.syncthing_reachable` is False |

**The tree** (`_check_tree`, `_check_inventory`, `_check_collector_alarms`):

| kind | sev | fires when |
|---|---|---|
| `projects_dir_missing` | error | `settings.projects_dir` cannot be read, is absent, or is EMPTY ("which normally means the storage is not mounted rather than that the projects are gone. Nothing has been marked as deleted.") |
| `inventory_refused` | error | per project: `nas_inventory_state.last_error` is set (DASH-5's brake kept the last good walk) |
| `enforce_refusal` | error | DASH-3's brake: N share removals over the limit, so NONE applied; names the folders and `DASH_ENFORCE_MAX_REMOVALS` |
| `deactivation_refusal` | error | DASH-4's brake: too many projects looked deleted at once |
| `ignored_report_sections` | warn | computers are sending sections this dashboard is too old to store (SYS-3) |

**Identity and plans** (`_check_identity_collisions`, `_check_pending_devices`,
`_check_collector_alarms`, `_check_accounts`):

| kind | sev | fires when |
|---|---|---|
| `duplicate_machine_id` | error | one `machine_id` on two `machines` rows (a cloned disk; fix: delete `.ccsync/machine.json` on the newer computer and restart CCSync) |
| `duplicate_device_id` | error | one Syncthing device id on two rows |
| `pending_device_approval` | warn | a device in Syncthing's pending list for over 24 h; nothing is cleared when Syncthing could not be asked |
| `plan_without_share` | error | a full-mode tick with no matching Syncthing share to that machine's device id (the direct form of SYS-9 invariant 1; `notices._check_plan_without_share`, stays silent until the config job has cached a folder/device snapshot at least once) |
| `share_without_plan` | warn | a `(folder, device)` pair the refused enforce pass wanted to remove: a computer still being sent a project nobody ticked for it |
| `editor_without_machine` | info | a `known_editors` row older than 30 days with no computer ever reported |

**Space** (`_check_machine_space`, `_check_dashboard_space`):

| kind | sev | fires when |
|---|---|---|
| `dashboard_disk_low` | error | the volume holding `db_path` has under 2 GB free, or cannot be measured |
| `machine_disk_low` | warn | a machine's reported sync drive has under 50 GB free |
| `machine_trash_oversize` | warn | a machine's `.ccsync-trash` is over 200 GB |

**The release channel** (`_check_release_feed`, only when `release_feed_url`
is set): `feed_unreachable` (warn: an error on the last check, no check in 48
h, or never checked) and `feed_runtime_mismatch` (warn: every offered
dashboard build is for a different container image).

**Configuration and faults**: `insecure_secret` (error, boot-time: one of
`report_token` / `session_secret` / `syncthing_api_key` has whitespace or
matching quotes around it; the notice names the KEYS only), `dev_insecure`
(error, boot-time: `DASH_DEV_INSECURE` is set), `server_error` (error: a
request 500'd, one row per `(path, exception class)` with a rising count in the
body; the exception's message is never stored).

## 4. What the server checks (alerts)

`alerts.ALERT_KINDS` is a tuple of forty `AlertKind(kind, severity, title,
what, check)` rows evaluated by `scan()` every alerts cycle into findings of
`{subject, diagnosis, fix, detail}`. The diagnosis is one or two sentences an
owner can act on; `fix` names the button or the tray action; `detail` is the
technical line and is never in the sentence. The order matters once:
`red_unexplained` is last and only reports machines no other kind named.

Per machine (from the fleet view's `guard` section):

| kind | sev | threshold |
|---|---|---|
| `breaker_tripped` | error | `breaker_tripped` set (fix: FLEET -> `[ RESUME ]`, after checking the NAS looks right) |
| `disk_park` | error | `blocked_reason == "disk_full"` |
| `disk_low` | error | `health.disk_status()` says RED - the chip's own rule, not a second threshold; a machine that never reported a disk section gets nothing |
| `machine_silent` | error | no report for 24 h (`SILENT_SECONDS`; deliberately far above the grid's 6 h red) |
| `report_refused` | error | `report_refused_at` set: the machine IS trying and this server is turning it away |
| `clock_skew` | error | `clock_skew_seconds` over 5 min (the grid chips at 1 min; a mail is not free) |
| `engine_down` | error | `supervisor_down_since` older than 1 h |
| `lane_stalled` | error | a stalled lane, or `why.reason == "lane_stalled"` |
| `lane_error` | error | a lane in `error` for over 1 h |
| `folders_unfiltered` | warn | any shared folder with no ignore filter |
| `thread_restarts` | warn | 3 or more sync-thread restarts in 24 h |
| `crashes` | warn | any crash report counted |
| `upgrade_failed` | error | 8 or more failed attempts at one build (REL-8's cap) |
| `upgrade_reverted` | warn | the machine rolled a build back (APP-5) |
| `out_of_tree`, `stray_projects`, `moved_project_dir`, `ingest_staging` | warn | the v38 ingest columns; silent until a companion sends them |
| `versions_behind` | warn | 3 or more PUBLISHED, non-retracted builds newer than the one running (counts fixes missed, not version arithmetic) |
| `retracted_running` | error | running a build that has been recalled |
| `red_unexplained` | error | red for 1 h and no kind above named it (fix: `[ ASK WHY ]`) |

Fleet and server:

| kind | sev | threshold |
|---|---|---|
| `fleet_halt` / `fleet_halt_expired` | warn | a halt is live / a halt ran past its own expiry and syncing resumed by itself |
| `nas_engine_down` | error | the server cannot reach its own Syncthing |
| `collector_kind_failed` | error | a collector kind is red |
| `collector_stale` | error | the collector has not completed a cycle recently |
| `watchdog_restart` | error | the collector thread was restarted since the last alerts pass (handed in by `collector._run_alerts`; an event, not a state, so it is not derivable later) |
| `enforce_refusal`, `deactivation_refusal`, `enforce_plan` | error / error / warn | the persisted brakes and a held plan |
| `ignored_sections` | warn | report sections this build drops |
| `feed_stale` | warn | no successful feed check in 7 days, or a recorded error |
| `feed_runtime_mismatch` | warn | offered builds need a newer container |
| `data_disk` | error | the dashboard's own volume under 10 % free (`DATA_DISK_WARN_PERCENT`; 5 % is the red line, both rendered the same way); percentages only, because `/data` on an appliance is a share of a pool nobody sized for this container |
| `nas_tree` | error | `projects_dir` is absent or empty; an unreadable path raises into `check_failed` |
| `notice_error` | error | every open notice of severity error, up to 40 |
| `file_move_expired` | warn | a file move a computer never answered and that aged out |
| `soak_failed` | warn | a staged build with crashes or self-reverts on its canary |
| `key_drain` | warn | machines still on the old sign-in key 7 days after rotation |
| `weekly_send_failed` | error | the last weekly report was not delivered through a CONFIGURED sink; silent on a site whose sink is `none`, where the report is recorded generated-not-sent instead |

Each kind is capped at 40 findings per cycle (`MAX_FINDINGS_PER_KIND`) so one
fleet-wide condition cannot fill a mailbox.

## 5. `check_failed`

A check that raises is not skipped. `scan()` catches it, logs the traceback,
and appends a finding of kind `check_failed` (severity error, subject = the
kind that failed, diagnosis "the check for '<what>' could not run, so this
server does not know whether that is all right. Treat it as unchecked, not as
fine", fix "send us the container log"). If the scan context itself cannot be
built (the fleet view raised), the whole scan is one `check_failed` finding
with subject "the whole scan".

It matters twice more. `deliver()` sends recovery messages only for kinds whose
check actually RAN this cycle: a kind that failed has said nothing about its
subjects, and declaring them recovered would be "could not check" rendered as
"fine" in its purest form. And the weekly report has a `COULD NOT BE CHECKED`
section beside `CHECKED AND FOUND NOTHING WRONG (n of 40)`, so a clean report
is distinguishable from a report whose checks all crashed.

The notices side has the same posture in a different shape: `run_checks()`
isolates each check, and one that raises leaves its own notices untouched
rather than clearing them.

## 6. Where alerts go: the sink

Settings -> ALERTS (`/admin/alerts`; the JSON twin is
`GET /api/v1/admin/alerts`). The page is not polled, because a swap under the
reader would throw away a half-typed form.

`alerts_sink` is one of:

* **`none`** - the default, and the vendor build's shape. The scan still runs
  every cycle, the `CURRENTLY OPEN` table on the page is computed live from it,
  `/api/v1/health` -> `open_alerts` carries the counts, and every ordinary
  finding's delivery attempt is recorded in `alert_log` as `ok=0`, detail "no
  sink configured", so "why did nobody get told" has an honest answer. The
  collector panel shows the `alerts` kind amber with "N alert(s) could not be
  delivered" for the same reason. **The weekly report is the one exception**
  (resilience sweep 2026-08-28 fix pass, finding 2): `run_cycle` records it
  directly as `ok=1`, detail "generated, not sent (no sink configured)"
  rather than going through `send`, so it still shows up under WHAT WAS SENT
  for the admin who turns a sink on later, but `weekly_send_failed` does not
  stand open forever on a site that has simply never configured one -- that
  kind only fires when a CONFIGURED sink actually fails to send it.
* **`smtp`** - `alerts_smtp_host`, `alerts_smtp_port` (default 587),
  `alerts_smtp_user`, `alerts_smtp_from`, `alerts_smtp_to` (one or more
  addresses, comma or semicolon separated), `alerts_smtp_tls` (STARTTLS,
  default on). The password is NOT a site setting: `[ SET PASSWORD ]` writes it
  0600 to `<data>/secrets/alerts/smtp_password`, and `DASH_ALERTS_SMTP_PASSWORD`
  in the container's environment overrides the file (env always wins, and the
  page says the value comes from the deployment). It is never in the database,
  never in a response, and the page shows a mask that hides a short value
  entirely. An authentication failure is reported as "the mail server refused
  the sign-in", never with the server's own text, which can echo the username.
* **`webhook`** - `alerts_webhook_url`, https only: refused when typed, and
  refused again at send time (a row written by an older build or a restored
  backup must not put the fleet's state on the wire in the clear). A POST of
  `{"subject": ..., "text": ...}` as JSON, `User-Agent: ccsync-dashboard-alerts`,
  no redirects followed (`docs/GOTCHAS.md` §12: an alert body names editors,
  machines and what is broken, and a 302 is somebody else choosing where that
  goes). This is how a Tailscale-reachable receiver is fed without the
  container growing any inbound surface.

Every setting is validated before any is written (`alerts.set_settings`,
all-or-nothing, unknown keys refused; audited as `alerts.settings`). They are
`site_settings` rows written by `alerts.py` directly, deliberately NOT
`site_store` keys, so an SMTP username can never be published to every
installer through `/api/v1/site`. One delivery is bounded by
`SEND_TIMEOUT_SECONDS` (20): the collector is a single thread and an SMTP
server that hangs must not park enforce behind it. A delivery failure never
raises; it is logged, recorded `ok=0`, and shown under `WHAT WAS SENT` with
the reason, because a channel that has been refusing since Tuesday is worse
than no channel: you believe you have one.

`[ SEND A TEST ]` (`POST /api/v1/admin/alerts/test`) sends one message
through the configured sink with dedup OFF - an admin pressing it twice is
asking twice, and a silent "already sent today" is exactly the answer that
makes somebody believe a broken sink works.

## 7. Repeat, dedup and recovery

`alert_log` makes all of this durable across a container replacement; nothing
is a counter in memory.

* **Dedup window** is 24 h per `(kind, subject)` (`db.ALERT_DEDUP_SECONDS`),
  and it counts FAILED sends too: with the sink misconfigured, an ok-only
  window would re-attempt every open condition every cycle and fill the ledger
  with failures nobody can read through.
* **An `error` repeats once a day** for as long as it is still true. An
  outage nobody acted on must not go quiet.
* **A `warn` is said once**, and not again until it has cleared and come back.
* **Recovery.** When a `(kind, subject)` that was alerted stops appearing in
  a scan, a "cleared" message goes out and is filed under `<kind>.ok`. Whether
  a subject is currently open is the comparison of its last `<kind>` row
  against its last `<kind>.ok` row - two timestamps, no third table. Recovery
  is only declared for kinds whose check ran this cycle (section 5).
* **Unparseable timestamps** read as "not recently sent": the failure
  direction of the dedup is "say it again", never "stay quiet".

## 8. The weekly report

Monday 08:00 in `alerts_timezone` (an IANA name such as `Europe/London`,
validated when typed; blank means UTC, and a zone the container cannot resolve
logs a warning and falls back to UTC rather than moving the report by hours in
silence). The slot is computed on the local calendar (`previous_weekly_slot`),
so a DST change neither skips nor doubles a week. **"Owed" is durable, not a
timer**: `weekly_due` compares the last `weekly` row in `alert_log` against
the most recent slot, so a container replaced at 07:59 on Monday sends it
once, one down all Monday sends it on Tuesday, and six restarts on Monday
afternoon do not send it six times. `alerts_weekly=0` turns it off.
`[ PREVIEW THIS WEEK'S REPORT ]` (`/admin/alerts/preview`, text/plain) renders
it exactly as it would be sent.

Subject: `CC Sync weekly: N computer(s), E problem(s), W thing(s) to look at`.
Body, in order:

1. `PROBLEMS (n)` and `THINGS TO LOOK AT (n)`: every open finding, worst
   first, each with its fix and detail.
2. `BUILDS`: "0.9.55: 6 of 8 machine(s)" per version, then every outdated or
   unreported machine by name, since when, and what current is for its
   platform.
3. `WHAT CHANGED THIS WEEK`: the last seven days of the audit ledger
   (`db.audit_since`, first 40 rows, the rest pointed at the TIMELINE page).
4. `ALERTS SENT THIS WEEK`, failures marked `SEND FAILED`.
5. `BYTES MOVED` per lane per machine - a live probe of `lane_report_current`
   for a bytes column, omitted today because no lane report carries one; the
   section appears by itself the day one does.
6. `RECOVERABLE FILES IN .ccsync-trash` per machine that reported a figure.
   `.stversions` is not listed: no companion measures it, and a zero nobody
   measured would read as "nothing to clean up".
7. `CHECKED AND FOUND NOTHING WRONG (n of 40)`, one line per quiet kind by
   its `what`, then `COULD NOT BE CHECKED` when any check raised.

The finding also asked for "no snapshot schedule is configured on this NAS"
as a standing red line (SYS-14). That check is not in the registry.

## 9. Cadence, `/api/v1/health` and cost

* `notices.run_checks()` runs at the end of EVERY collector cycle, whichever
  kind ran; `notices.check_settings()` runs once at boot; `server_error` is
  written by the 500 handler at request time.
* `alerts` is the ninth collector kind (`collector.KINDS`), runs LAST so it
  reads the picture the other kinds just refreshed, is in
  `SYNCTHING_FREE_KINDS` so it can report Syncthing being unreachable, and
  runs every `interval_alerts` (`DASH_INTERVAL_ALERTS`, default 600 s: the
  conditions it looks for are measured in hours and the dedup window is a
  day, so faster would cost CPU on the box moving lane C bytes and change
  nothing an admin sees).
* `/api/v1/health` gains `notices: {error, warn}` (a count that cannot be read
  is one `error`) and `open_alerts: {error, warn}` - the latter from a LIVE
  `alerts.scan()` on every call, which walks the whole fleet view and all
  forty checks; a scan that cannot run returns `{error: 1, warn: 0,
  scan_failed: true}`, never zero. Both blocks are in the AUTHENTICATED body
  only: the container healthcheck's unauthenticated probe (every 60 s, 5 s
  timeout) gets `{ok, version}` before that block is built and never triggers
  the scan.
* The topbar reads notice counts with one indexed query per full-page render
  (`ui._notice_counts_safe`), and reads a stored alert count
  (`db.META_ALERTS_OPEN`, `ui._alert_counts_safe`) written at the end of every
  `alerts.run_cycle` (resilience sweep 2026-08-28 fix pass, finding 3) --
  the LAST scan's `open_counts`, not a fresh scan, for the same reason the
  notices count is a plain query rather than a re-run of the checks. Rendered
  as a `[ N ALERTS ]` chip beside `[ N PROBLEMS ]` in `partials/topbar.html`,
  linking to `/admin/alerts`; absent at zero, same rule as the PROBLEMS chip.

## 10. Adding a check

**A notice.** Add the kind to `db.NOTICE_KINDS` with its severity and a
one-line `what` (that line is what the panel shows as checked, and an unknown
kind renders as nothing). Then either write it beside the refusal with
`db.notice(conn, kind, severity, subject, body=..., fix=..., now=...)` and
close it with `db.clear_notice` / `db.clear_notices_of_kind` from the same
pass, or add a `_check_*` function to the tuple in `notices.run_checks` that
writes and clears its own subjects. The body must be built from names, counts
and timestamps, never a secret; the fix must name a button, a page or a
command. Registering a kind with no writer used to be worse than not
registering it -- the panel ticked it `[ OK ]` for ever -- but since the
resilience sweep 2026-08-28 fix pass `[ OK ]` requires evidence
(`db.notice_check_times`, stamped by `notice` / `clear_notice` /
`clear_notices_of_kind` themselves) rather than mere registry membership, so
an unwritten kind now renders `[ NOT CHECKED ]` instead. Still write the
check promptly: `[ NOT CHECKED ]` is honest, not a substitute for the
diagnosis.

**An alert.** Add one `AlertKind(kind, severity, title, what, check)` row to
`alerts.ALERT_KINDS`, above `red_unexplained`. `check(ctx)` returns
`[_f(subject, diagnosis, fix, detail)]` from what `Ctx` already gathered (no
per-machine queries; a table another work package owns is read through
`_rows`, which treats an absent table as empty), and calls `ctx.name(subject)`
for any machine it names so the catch-all skips it. Nothing else changes: the
dedup, the repeat rule, the recovery message, the Alerts page, the weekly
report's checked list and the `/health` counts all pick the row up. Severity
decides the repeat rule, not just the colour.

## 11. Known gaps

Observed while documenting the built code (2026-08-28); a first fix pass the
same day closed four of them (below) and added
`dashboard/tests/test_notices.py` and `dashboard/tests/test_alerts.py`. What
is left:

* **`plan_without_share` needs a live folder/device snapshot.**
  `notices._check_plan_without_share` reads `Collector._folder_devices`,
  which is only populated once the `config` collector kind has completed a
  pass in THIS process; a fresh boot, or a Syncthing that has never answered,
  reads as "not checked" (correctly) rather than a false clean bill of
  health, but it also means the check has a warm-up period the other
  identity checks do not.
* **Two floors for one fact.** `disk_low` deliberately reuses
  `health.disk_status`'s red; `machine_disk_low` (notice) introduces a
  separate 50 GB warn floor.
* **Some conditions are reported twice.** The enforce refusal, the
  deactivation refusal, an unreachable Syncthing and the ignored sections are
  each both a notice and an alert kind, and every error notice is ALSO
  surfaced as `notice_error`, so one brake can produce two rows on the Alerts
  page (deduped per `(kind, subject)`, so each sends once).
* **`notices` rows are never pruned.** Cleared rows stay; the table grows by
  distinct `(kind, subject)` only, so it is bounded by what the fleet has
  ever done, not by time.
* **DASH-10 is half built.** The boot-time notice exists; `settings.num()`
  still falls back silently and the token headers are still compared
  unstripped.
