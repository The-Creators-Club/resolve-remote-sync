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

`alerts.ALERT_KINDS` is a tuple of fifty-nine `AlertKind(kind, severity, title,
what, check)` rows evaluated by `scan()` every alerts cycle into findings of
`{subject, diagnosis, fix, detail}`. The diagnosis is one or two sentences an
owner can act on; `fix` names the button or the tray action; `detail` is the
technical line and is never in the sentence. The order matters once:
`red_unexplained` is last and only reports machines no other kind named.

**Every one of those four strings is PRODUCT COPY and follows the sweep's one
vocabulary** (CR-181, 2026-09-04, `USABILITY_RESILIENCE_SWEEP_2026-09-03.md`
section 4): a **computer**, never a machine or a rig; **tick** / **sync plan**;
**upload** / **proxy download** / **folder sync**, never "lane"; and the three
ways sync can be off are **paused** (you did it), **stopped by your admin** (a
fleet halt) and **stopped itself** (the proxy-download brake or the disk
floor). "Halted", "parked" and "breaker" stay in the code, the columns and the
kind ids - `fleet_halt`, `disk_park` and `breaker_tripped` are all still called
that - and never reach a reader. `dashboard/tests/test_sweep_2026_09_04_copy.py`
scans for the retired words in every string this module hands a person.

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

**The fleet job queue** (added 2026-09-04, usability sweep wave 2, DDIAG-2 /
DDIAG-6). The queue's own module says "a scheduler that quietly assigns
nothing looks exactly like a fleet with nothing to do", and until this it was
diagnosed on `/admin/jobs` and nowhere else:

| kind | sev | fires when |
|---|---|---|
| `jobs_starved` | warn | the oldest QUEUED job is over 6 h old and `jobs.explain` answers `no_capable_machine`, `kind_not_allowed` or `halted`. `all_busy` / `idle_wait` / `fleet_cap` / `cooling_down` are deliberately absent: those are the scheduler working |
| `jobs_abandoned` | warn | anything abandoned in the last 24 h. ONE finding for the window, not one per job: a fleet that abandons twelve whisper jobs has one broken computer |
| `jobs_pinned_no_executor` | error | a pinned job with no Timeline Cards mount behind it (DDIAG-6: the boot-time release sits inside `executor.available()`), or a row this container holds whose heartbeat stopped an hour ago |

**The release channel reaching the fleet** (2026-09-04, REL-3 / REL-6 /
REL-13). `versions_behind` needs a computer to be three builds behind, so a
fleet that stopped updating after ONE release was silent for months:

| kind | sev | fires when |
|---|---|---|
| `upgrade_refused` | error | `machine_state.upgrade_refused_*` (v48) is set: that computer turned the offer down at receipt, made no attempt, and no button on the page can fix it |
| `rollout_stalled` | warn | a channel made current over 48 h ago with a computer that has REPORTED since and is still behind. Silent when `made_current_at` is NULL (a build made current before v48: cannot tell) |
| `platform_channel_stale` | warn | one platform's current build is over 7 days older than the other's by `made_current_at`, or more than 2 builds behind when the stamps are missing. The fix is the two Mac commands verbatim, because PyInstaller cannot cross-build a macOS bundle |

**Each computer's own tools** (2026-09-04, CYT-7 / CMEDIA-3), from
`sync_guard`:

| kind | sev | fires when |
|---|---|---|
| `ytdlp_stale` | warn | that computer's yt-dlp is past its shelf life and could not update itself. The body is the COMPANION's own message; the verdict used to reach one INFO line a day in an editor's log |
| `ytdlp_failed` | error | `action == "failed"`: no usable binary at all, which is a different alarm from an old one |
| `loopback_down` | warn | the 8899 loopback is enabled and not bound. `enabled` false is a choice and all-NULL is a companion too old to say; neither fires |

**The YouTube stack on this server** (2026-09-04, YTWEB-2 / YTWEB-5), from
`ytdl.health_snapshot` in process (no probe, no HTTP):

| kind | sev | fires when |
|---|---|---|
| `ytdl_worker_dead` | error | `worker_alive` is False: everything queued sits for ever with no error on it |
| `ytdl_downloads_failing` | warn | the last real download failed AND the canary failed too. One failed download alone is usually one bad video, and crying wolf on it is how a health strip stops being read |
| `ytdl_pot_provider_unreachable` | warn | `pot_provider == "unreachable"` ONLY. `unconfigured` is the shipped compose's normal state and `unknown` is "not asked" |
| `ytdl_plugin_install_failed` | warn | the anti-bot plugin's BOOT install failed (CR-73, CR-84), carrying its error and attempt count |
| `ytdl_stale` | warn | this container's own yt-dlp is past `YTDLP_MAX_AGE_DAYS`. The one signal that would have shown CR-80 and CR-83 coming |

**Nothing alerts on `cookies_state == "anonymous"`**: since CR-80 that is the
HEALTHY state, and the 2026-08-11 "cookies are mandatory" rule is inverted.

**The b-roll platform** (2026-09-04, BROLL-2), read from `broll.db` and
`client_shares.db` on their own read-only connections, silent when the mount
is absent:

| kind | sev | fires when |
|---|---|---|
| `broll_batch_stuck` | warn | a non-terminal ingest batch with no heartbeat for 24 h: those clips are not searchable and nothing is working on them |
| `broll_share_expiring` | warn | a live client link inside 7 days of its expiry. An already-expired one is not a warning: the client has met it |

BROLL-2's fourth kind, `broll_index_stale`, is NOT built: deciding "no new
clip in 90 days while the archive has newer files" needs a walk of the
archive share, and a filesystem walk on the collector's single thread is the
one thing `Ctx` forbids. It is named here so its absence is visible.

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
section beside `CHECKED AND FOUND NOTHING WRONG (n of 59)`, so a clean report
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
  default on), `alerts_smtp_verify_tls` (default on; since 2026-09-03,
  bug-hunt dash-collector-3, STARTTLS verifies the relay's certificate and
  hostname, and a mismatch is a refusal that names the host, never a silent
  unverified session; off is the one opt-out for a relay with its own
  certificate). The password is NOT a site setting: `[ SET PASSWORD ]` writes it
  0600 to `<data>/secrets/alerts/smtp_password`, and `DASH_ALERTS_SMTP_PASSWORD`
  in the container's environment overrides the file (env always wins, and the
  page says the value comes from the deployment). It is never in the database,
  never in a response, and the page shows a mask that hides a short value
  entirely. An authentication failure is reported as "the mail server refused
  the sign-in", never with the server's own text, which can echo the username.
* **`webhook`** - `alerts_webhook_url`, https only: refused when typed, and
  refused again at send time (a row written by an older build or a restored
  backup must not put the fleet's state on the wire in the clear). The URL is a
  bearer credential for most receivers (Slack, Teams, Discord put the secret in
  the path), so since 2026-09-03 (dash-collector-5) the page and the API show
  it masked past its origin and `alert_log.sent_to` records the origin only;
  the stored value itself still lives in `site_settings`, so a database backup
  still carries it (moving it beside the SMTP password is an owner decision).
  A POST of
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

**How many messages a cycle produces is the sink's, not the product's**
(CR-190, 2026-09-04): `smtp` (and `none`) send ONE digest per check cycle,
`webhook` sends one POST per finding, and `alerts_digest` overrides either.
See section 7.

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
* **A finding may opt out of its kind's daily repeat** (`_f(..., repeat=False)`,
  DDIAG-3, 2026-09-04) while staying open. `machine_silent` uses it past
  `SILENT_GIVE_UP_DAYS` (14): a retired laptop was an `error` for ever, so it
  mailed the owner the same sentence 21 times. It is deliberately not DROPPED
  from the scan - a subject that leaves the scan is declared RECOVERED, and
  "this has cleared, no action is needed" about a computer that is dead is a
  worse lie than the daily mail. Nothing may opt IN: the repeat rule stays the
  severity's. The fix text now names `[ FORGET ]` on the FLEET row.
* **Turning a sink on re-raises everything that is already open** (DDIAG-4,
  2026-09-04). With `alerts_sink = none` every finding still gets an
  `alert_log` row (ok=0, "no sink configured") so the page can answer "why was
  nobody told" - but that row is also what `_is_open` and the dedup window
  read, so the day an admin configured SMTP every warn open since before then
  counted as said and would not be sent again until it had cleared and come
  back. `set_settings` now re-files those rows under `<kind>.undelivered` when
  the sink leaves `none`: they stay on WHAT WAS SENT as the honest record of a
  period with no channel, and the next scan raises every open subject with a
  real sink behind it. The page says so on save: "Saved. The next check will
  send everything that is currently open."

### One message per cycle: the digest (CR-190, 2026-09-04)

The owner configured the SMTP sink at 17:09 on 2026-09-04 and received
**eleven separate emails inside the same minute**, one per open finding
("CC Sync: a safety net is not there - release key backup", "... - restore
drill", "... - snapshot", "CC Sync: project folders outside the tree", "CC
Sync: footage is outside the tree", ...). Four of them were error severity, so
they would have repeated as four more mails every day. His words: **"I'm
getting spammed with emails now."**

The rule, from that day: **a person gets at most ONE email per check cycle,
and the daily repeats are one email, not N.** Nothing is dropped to get there.

* **Every cycle's deliveries are one message** (`alerts.compose_digest`,
  `alerts._send_digest`). Subject `CC Sync: N new problem(s)`, or
  `CC Sync: 1 new problem: <title>` when there is one. The body is one block
  per new finding in severity order, carrying exactly the `diagnosis`, the
  `What to do:` and the `Detail:` each separate mail carried.
* **A finding that was in yesterday's message and has not changed is one
  line**, under `STILL NOT FIXED`, with how long it has been open. The daily
  repeat of the errors is therefore one mail listing them all, subject
  `CC Sync: still not fixed after N day(s): <titles>`; re-reading yesterday's
  diagnosis is not what a repeat is for.
* **Recoveries ride the same digest** as their own `CLEARED:` block. A fleet
  coming back from one outage used to send six "cleared" mails in a minute.
* **The catch-up is one message too.** `_requeue_undelivered` leaves a `meta`
  marker (`alerts_catch_up_at`) and the next delivery is
  `CC Sync: here is everything currently open (N)`, whose first line says it
  is the catch-up after a channel was configured, not N faults found in the
  last ten minutes.
* **`Still open from before: k (see the HEALTH page)`** closes the body
  whenever something open is not in this mail (a warn already said, an error
  that has opted out of its repeat, anything inside its dedup window). One
  message a cycle is only safe if it can say what it is not carrying.
* **A webhook keeps one POST per finding.** Its consumer wants structured
  events, so the default flips on the sink (`alerts.digest_enabled`), and
  `alerts_digest` ("", "1", "0", the HOW MANY MESSAGES control on the page)
  overrides it either way. Blank stays blank on purpose: it means "whatever
  suits the channel", and folding it to a 0/1 would freeze today's default.
* **The heartbeat and the weekly report stay their own messages.** They are
  scheduled, not raised, and the heartbeat's whole meaning is that one arrives
  every day whatever else does.
* **`alert_log` still keeps one row per finding**, because the dedup
  (`alert_recently_sent`), the recovery comparison (`_is_open`) and the page
  all read it that way. `batch_id` (v51) is the message those rows shared, and
  WHAT WAS SENT groups by it: "one message, 3 finding(s)". Per-event rows
  carry no batch id, because they really were separate messages.

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
5. `BYTES MOVED` per transfer per machine - a live probe of `lane_report_current`
   for a bytes column, omitted today because no lane report carries one; the
   section appears by itself the day one does.
5b. `JOBS: n queued, n running, n abandoned this week` (DDIAG-2,
   2026-09-04), printed every week including all zeros: the queue is invisible
   on every other page an owner opens, and a line that appeared only on bad
   weeks would make its absence read as good news. Omitted entirely on a
   database with no `jobs` table, rather than printed as a zero nobody
   measured.
6. `RECOVERABLE FILES IN .ccsync-trash` per machine that reported a figure.
   `.stversions` is not listed: no companion measures it, and a zero nobody
   measured would read as "nothing to clean up".
7. `CHECKED AND FOUND NOTHING WRONG (n of 59)`, one line per quiet kind by
   its `what`, then `COULD NOT BE CHECKED` when any check raised.

The finding also asked for "no snapshot schedule is configured on this NAS"
as a standing red line (SYS-14). That check is not in the registry.

## 8a. The daily heartbeat

DDIAG-17, 2026-09-04. Every message in this document is composed and sent BY
the thing being watched, so a container that is off, a collector thread past
its restart limit, a NAS that is powered down and a Tailscale link that is
gone all produce exactly the same experience as a healthy fleet: no mail. The
weekly report was the only proof of life, and it is a week wide.

`alerts_heartbeat` (default **off**, editable on the Alerts page beside the
weekly toggle) sends ONE short message a day while a sink is set: subject
`CC Sync: all quiet - 8 computer(s), 0 problem(s)`, from the counts
`run_cycle` already has. `heartbeat_due` compares the DATE of the last
`heartbeat` row in `alert_log` against today's in `alerts_timezone` - a
calendar day, not "24 hours since", which drifts an hour later every day until
it lands in the middle of the night - so it is durable across a container
replacement exactly as `weekly_due` is. It is NOT a registry kind: it reports
no condition, so it can never count as a raised problem, be recovered or reach
CURRENTLY OPEN. The weekly report does not double as it, and the page says the
only thing that makes any of it worth a mail a day: "If these stop arriving,
the server itself is down."

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
  fifty-nine checks; a scan that cannot run returns `{error: 1, warn: 0,
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

A `NOTICE_KINDS` entry may also carry **`href`** and **`href_label`**
(DDIAG-8, 2026-09-04). The destination is a property of the KIND, not of the
row, so it lives in the registry and needs no column: the panel renders it
after the sentence as a `[ TAKE ME THERE ]` button (`href_label` overrides
that wording). Keep the prose fix as well - a mail body has no links to
offer, and the sentence is what an owner reads there.

**An alert.** Add one `AlertKind(kind, severity, title, what, check)` row to
`alerts.ALERT_KINDS`, above `red_unexplained`. `check(ctx)` returns
`[_f(subject, diagnosis, fix, detail)]` from what `Ctx` already gathered (no
per-machine queries; a table another work package owns is read through
`_rows`, which treats an absent table as empty), and calls `ctx.name(subject)`
for any machine it names so the catch-all skips it. Nothing else changes: the
dedup, the repeat rule, the recovery message, the Alerts page, the weekly
report's checked list and the `/health` counts all pick the row up. Severity
decides the repeat rule, not just the colour.

## 11. Fault injection: the chaos suites

Every mechanism in this document answers a CONDITION, and until the
resilience sweep the thirteen test suites were strong on logic and near
silent on conditions: the systems agent read `KNOWN_BUGS.md` as data and
found that about 2 % of entries were discovered by a test and none by the
system telling anyone (SYS-18). The chaos suites are the answer to the first
half of that.

    companion/tests/chaos/test_fault_injection.py     7 of the 9 injections
    dashboard/tests/chaos/test_fault_injection.py     the 3 server-side ones

They run with the rest of each suite and need no flag:

```powershell
cd companion;  .venv\Scripts\python.exe -m pytest tests/chaos -q
cd dashboard;  .venv\Scripts\python.exe -m pytest tests/chaos -q
```

Nine injections, each closing a CLASS rather than a bug, each tied to a
ledger entry: a child that never exits (CR-91b), a clock 20 minutes slow
(SYS-4), `disk_usage` at 1 GB (SYS-5), a report POST that 401s and then
recovers (APP-1), the loop raising on its third pass (SYS-2), a kill between
an atomic latch's tmp-write and its `os.replace` (class G), a report carrying
an undeclared section (SYS-3), a second hostname reporting an existing
`machine_id` (DASH-11), and a folder listing that answers 200 with nothing in
it (CR-44 / CR-47 server-side, DASH-4).

Two rules govern anything added here, and they are what make these different
from the unit tests next door:

* **Assert the OBSERVABLE, never the call.** The state the lane reports, the
  sentence the tray shows, the file the next boot reads, the notice a person
  is handed. A test that asserts "the guard function ran" passes against a
  guard whose answer nobody surfaces, which is the exact defect (UX-10)
  sections 2 and 3 above exist to close: sixteen `log.error` diagnoses that
  reached only the container log would have had a green test each.
* **No sleeps, no spawns, no network.** Clocks are injected (`lane._monotonic`,
  a scripted `received_at` in the report reply), children are scripted
  (`popen_factory`), and hours-long ceilings are crossed in milliseconds.
  A chaos suite that took a minute per fault would be run once.

The seams were already there before any of this -- `popen_factory`, the
reporter's `_http_post`, the selection client's opener, `subprocess.run`,
`_monotonic` -- so what the suites add is the injections, not a harness.

A fault that finds a real gap is marked `xfail(strict=True)` with the finding
in its `reason` and an entry in `KNOWN_BUGS.md`, never weakened to green: a
chaos test that was adjusted until it passed is worth less than no test. Two
such xfails exist today (see the wave 5 ledger section).

## 12. Known gaps

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

## 13. Invariants: the facts nothing re-checks

Added 2026-08-29 for the sweep's wave 5, item 40 (SYS-9). Code:
`dashboard/src/ccsync_dashboard/invariants.py`; ledger: the
`invariant_results` table (schema v39); page: Settings -> INVARIANTS
(`/admin/invariants`). It is the ninth collector kind, `invariants`, running
every `interval_invariants` (`DASH_INTERVAL_INVARIANTS`, default 900 s) just
before `alerts`.

### What an invariant is here

A fact that spans two components and that is enforced only at the moment
something WRITES it. A tick becomes a Syncthing share at tick time; a project
folder gets its `.ccsync-project` marker when it is set up; a package's
`min_version` is checked when it is published; a computer's identity is
minted once. Nothing ever asks whether any of them is still true.

`collector.folder_tuning_drift` is the pattern, already correct and already
in the tree: it re-reads a Syncthing folder's settings every cycle and
repairs the keys that drifted. It covers folder tuning and nothing else.

**This checker repairs nothing. It names things.** A checker trusted to
write to Syncthing, the tree and the registry on a timer has B16 as its
failure mode (the whole fleet unshared in one pass). Naming is the gap;
repairing stays a button a human presses.

**The invariants are DATA** (`invariants.INVARIANTS`), the same shape as
`alerts.ALERT_KINDS`: one row per invariant with its key, SYS-9's number, the
fact in one line, the CONSEQUENCE a non-technical owner understands, the
exact next action, its severity and its callable.

### The list

Numbered as SYS-9 numbers them.

| # | key | the fact | state today |
|---|---|---|---|
| 1 | `plan_has_share` | every full tick is a Syncthing share to that computer's device id | checked (needs one completed `config` pass in this process) |
| 2 | `machine_has_plan` | what each reporting computer is set to sync: a plan, the unassigned bucket, a base rig (CR-28), or nothing at all | checked, INFORMATIONAL - never broken (owner, 2026-09-04: an empty plan is a legitimate state for a spare or a laptop between shoots), so it files no notice; the detail names the computers with nothing ticked |
| 3 | `one_identity_per_computer` | one `machine_id` and one Syncthing device id per computer, INCLUDING the disk-clone signature | checked |
| 4 | `project_markers` | every active project's marker exists and its slug matches the row | checked when a tree is mounted |
| 5 | `tree_markers` | the tree root still looks like the tree, rather than an empty mount | checked when a tree is mounted |
| 6 | `package_floor` | a current package's `min_version` is at or below its own version, and not below a floor already published (CR-52) | checked |
| 7 | `companion_floor` | every computer runs a build new enough for its plan (0.9.3 pushes, 0.9.43 RESUME, 0.9.54 upload-only) | checked |
| 8 | `versioning_agrees` | `.stversions` retention agrees between NAS-side and editor-side (R5) | **NOT CHECKED, by design** |
| 9 | `snapshot_schedule` | the customer's data is on a snapshot schedule (SYS-14's standing red line) | checked when the NAS can be asked |
| 10 | `proxy_pairs` | every `Proxy/<stem>.*` on the server has its original beside it, a camera proxy suffix (Sony `S03`) allowed for | checked, `warn` |
| 11 | `fleet_current_with_vendor` | the newest companion build the VENDOR feed offers (`db.get_feed_offered`, written by every feed check) is published here and is current (SYS-2) | checked when a feed is configured and one check has recorded what it offers |
| 12 | `dashboard_meets_requirements` | this dashboard's `VERSION` is at or above the `requires_dashboard` of every non-retracted record in the channel, through `package_store.blocks_on_dashboard_version` rather than a second comparison | checked once anything is published |
| 13 | `mount_assets_open` | every mounted app's installable-app files (`PWA_MOUNT_ASSETS`: the dashboard's manifest and `sw.js`, Timeline Cards' manifest and icon) are in `app._OPEN_EXACT`, so the outer gate does not 303 them (CR-100) | checked always, from the gate's own set and never by fetching |
| 14 | `cards_tree_matches_source` | the served `cards-web` tree matches the checkout it was shipped from (CR-101 was hand-copied with a `.bak`) | **NOT CHECKED, for want of a record: see below** |
| 15 | `alerts_deliverable` | a sink is configured and its last send arrived, through `alerts.sink_deliverable` (SYS-1) | checked, `warn`; NOT CHECKED on a build without that helper or a ledger it cannot read |

Invariants 11 to 15 were added 2026-09-04 for SYS-17: the first ten look at
state that has gone wrong INSIDE one deployment, and every recent ledger entry
a machine could have caught is about the relationship between what the vendor
published, what this server is deployed with, and what it renders.

Three deliberate narrowings, each so the check can be honest rather than
loud:

* **Invariant 3's clone signature.** Two rows on one `machine_id` are both
  reported, but only two rows that BOTH reported inside one interval
  (`CLONE_WINDOW_SECONDS`, 15 min) get the "a copied disk is in use on two
  computers at once" sentence. That is the case that makes
  `adopt_renamed_machine` ping-pong one plan between two live PCs every
  report; the other case is usually a rename nobody tidied up.
  **It could not see a same-editor clone until 2026-08-29** (SYS-18a): when
  both computers were signed in as one person, `adopt_renamed_machine`
  deleted one of the two `machines` rows on every report, so there was no
  second row to group. The fix landed at the adoption path, where it
  belonged, and not here: `api._register_machine` refuses the adoption while
  the previous hostname is still reporting
  (`api.CLONE_ADOPTION_WINDOW_SECONDS`, five minutes, the same
  `health.STALE_REPORT_SECONDS` line the rest of the dashboard uses for "this
  report is no longer current"). Both rows survive a refusal, so a
  same-editor clone now reaches this check and `duplicate_machine_id` exactly
  as a two-editor one always did. The refusal also raises
  `duplicate_machine_id` itself, at the moment of the report, because that is
  the only place that knows both computers were live in the same instant.

  **The verdict is two-step, and an ordinary rename trips it on purpose.** A
  renamed computer reboots and reports under its new name one to three
  minutes later, which is inside any window wide enough to catch a clone, so
  its FIRST report is refused and does raise this finding. It then clears
  ITSELF: every later report asks again, and once the old hostname has been
  quiet for the window the rename is confirmed, the plan moves across and the
  notice is closed - about five minutes, no operator action. So a
  `duplicate_machine_id` that appears once and disappears is a rename that
  sorted itself out; one that is still there after five minutes is two live
  computers, and the fix text on it is the one to follow. The single case
  that stays refused for good is a new hostname that was given a sync plan of
  its own in between, which is an admin decision and is never overwritten.
* **Invariant 4 ignores a MISSING directory.** That is the deactivation
  grace's business one function up, and a project being renamed on the NAS
  while the pass runs would otherwise read as a fault every fifteen minutes.
  What it reports is a directory that is there and has lost, or disagrees
  with, its identity.
* **Invariant 10 checks one direction.** A proxy with no original is the
  signature of a half-finished reorganisation. An original with no proxy is
  the normal state of footage uploaded this morning, so counting it would
  make the check cry wolf every shoot day.
* **Invariant 10 knows a camera's own proxy** (2026-09-03, owner's call:
  "this will happen to a lot of users"). Sony XAVC bodies write `<clip>S03.MP4`
  into the card's `SUB` folder, and editors copy those into `Proxy/` beside
  the ones we generate, so the stem never matched anything and one drone
  shoot raised 44 orphans. A proxy whose stem ends in a suffix from
  `invariants.CAMERA_PROXY_SUFFIXES` is tried a second time with the suffix
  stripped, case-insensitively; matching under neither stem is still broken,
  because that is footage really gone.
* **Invariant 14 is registered with a `skip_reason`, like invariant 8**
  (2026-09-04). Nothing on this server records which checkout the Timeline
  Cards tree came from: `install_dashboard_app.install_tree` uploads the
  files, verifies count and bytes, and swaps the directory, keeping no commit
  id, file list or checksum, and `CARDS_EXCLUDE_DIRS` drops `.git` from the
  upload, so the served tree carries no provenance either. Hashing it would
  therefore be hashing it against itself. To make this checkable the deploy
  would have to WRITE what it shipped - the source commit and a per-file
  sha256 manifest into `<host-root>/cards-web` (or into `meta` through the
  dashboard) at install time - and then the check is a walk and a compare.
  Until somebody records it, the honest page entry is `[ NOT CHECKED ]` with
  that sentence on it: CR-101 was fixed by a hand copy on the NAS with a
  `.bak` beside it, and the next `install_dashboard_app.py` run is still the
  only thing that reconciles a tree edited that way.

### NOT CHECKED is not OK

Four states, stored (`invariant_results.state`, with `ok` as 1/0/NULL so no
reader can flatten the tri-state into a boolean):

* `ok` - the check RAN this pass and the fact is still true. The detail line
  carries the evidence ("34 full tick(s), all shared"), because a green row
  with no number behind it is the thing this sweep keeps finding.
* `broken` - with one row per subject, capped at
  `db.INVARIANT_MAX_SUBJECTS` (20): one broken cross-component fact usually
  breaks it for many subjects at once.
* `not_checked` - this deployment cannot evaluate it, and the detail says
  what would have to be true for it to run: no project tree mounted, no NAS
  API key, no `config` pass completed yet, nothing published, invariant 8's
  standing reason. **It renders `[ NOT CHECKED ]` and never `[ OK ]`.**
* `check_failed` - the check RAISED. `evaluate()` catches it, logs the
  traceback and records the exception class, exactly as `alerts.scan` does
  with its own `check_failed`; a notice of kind `invariant_check_failed` says
  "treat it as unchecked, not as fine". One raising invariant never stops the
  other nine, and the collector kind still succeeds: a checker that took the
  collector down with it would cost more than it tells anybody.

Invariant 8 is the worked example of the rule. The NAS-side `.stversions`
`maxAge` is 365 d and the editor-side is 30 d (R5), and the editor-side value
lives in the companion build: no machine reports it, so this server can see
only one of the two numbers it would have to compare. Registering it with a
`skip_reason` is what puts "nobody is checking this" on the page. Deleting
the row would have hidden the same fact behind an absence.

### Where the results go

Nothing needed a second edit for any of this:

* **Ledger.** `invariant_results`, one row per (invariant, subject), rewritten
  every pass. Unlike `notices` it is a picture of the LAST pass, not a
  history: subject rows the pass did not name are deleted.
* **Notices.** Each broken subject is a `db.notice` of kind
  `invariant_broken` at the invariant's own severity, carrying the registry's
  consequence and fix, so it appears in PROBLEMS THE SERVER FOUND and (at
  `error`) reaches the sink through `notice_error`. A pass that finds it
  fixed closes it. A raising check writes `invariant_check_failed`.
* **Alerts.** One kind, `invariant_broken`, placed above `red_unexplained`.
  It READS the rows the invariants kind just wrote rather than re-evaluating,
  for the reason `alerts.Ctx` gives, and an older database with no such table
  reads as nothing to report here (`db.fetch_invariant_results` /
  `broken_invariants` treat a missing table as an empty picture).
* **The weekly report** picks the kind up through the same registry as
  everything else, including the "checked and found nothing wrong" list.
* **The page**, Settings -> INVARIANTS, lists every invariant with its state,
  its subjects, its last-checked time and, for a broken or failed one, the
  consequence and the fix. THE REGISTRY IS THE SPINE: an invariant with no
  row yet (a fresh boot) renders `[ NOT CHECKED ]` rather than being absent.
  There is no [ RE-CHECK NOW ] button on purpose - the pass walks the tree
  and asks the NAS, and a button an admin can hammer is a button that parks
  the collector's single thread.

### Adding an invariant

Add one `Invariant(key, number, title, consequence, fix, check, severity)`
row to `invariants.INVARIANTS`. `check(ctx)` returns `ok(detail)`,
`broken([(subject, detail), ...], detail)` or `not_checked(reason)` from what
`Ctx` already gathered, and must not go back for a per-machine query: this
runs on the collector's single thread beside enforce and completion.

Rules the reviewer will hold you to:

1. **Never return `ok` for a fact you did not actually evaluate.** If the
   data was not there, that is `not_checked(reason)` and the reason names
   what is missing.
2. **`consequence` is about the world, not the database** - what goes wrong
   for the owner, in one sentence - and `fix` names a button, a page or a
   command.
3. **Nothing formats a secret.** Details are names, counts, versions and
   timestamps.
4. If you cannot evaluate it honestly ANYWHERE, register it anyway with a
   `skip_reason`, like invariant 8. A registered invariant nobody checks is
   visible; an absent one is not.

## 14. What is protected: the absence panel

SYS-14 (resilience sweep 2026-08-28), built 2026-08-29 as wave 5.
`dashboard/src/ccsync_dashboard/protection.py`, Settings -> PROTECTION.

**Every other panel in this product reports what is WRONG. This one reports
what is NOT THERE**, which is a different question and had never been asked.
Nothing in the system had ever said "this NAS has no snapshot schedule": the
live TrueNAS keeps `dashboard.db`, `broll.db` and `music.db` under
`/mnt/tank/apps`, a plain directory and not a dataset, so it has no scheduled
snapshot at all (CR-10, open since 2026-08-17) - and every page rendered
green about it, because a mechanism that is absent produces no errors.

### The inverted default

A safety mechanism this server cannot POSITIVELY VERIFY is reported. Green
requires evidence: a snapshot task it can see, a last run it can date, a key
it holds, a date somebody recorded. Four states, the same four
`invariants.py` uses and out of the same `Outcome`:

| Chip | Means |
|---|---|
| `[ PROTECTED ]` | a check ran and found positive evidence, named in the detail line |
| `[ MISSING ]` | the mechanism is provably not there |
| `[ CANNOT VERIFY ]` | this deployment has no way to get evidence, and the line says what would give it one |
| `[ COULD NOT RUN ]` | the check itself raised |

**`[ CANNOT VERIFY ]` is not `[ PROTECTED ]`, and amber forever is an
acceptable answer.** On a Synology the snapshot lines stay amber for the life
of the deployment: DSM keeps its schedules in the Snapshot Replication
package, which has no supported CLI or API, so the line reads "cannot verify,
confirm in DSM" and never resolves. That is honest. Green there would be a
guess, and "could not ask" rendered as "fine" is the mistake `folder_errors`
and the container healthcheck have each made once already.

### The lines

| Line | Green when |
|---|---|
| the project tree is on a snapshot schedule | an enabled `pool.snapshottask` covers `DASH_TREE_DATASET` (a recursive task on a parent counts) |
| this dashboard's own data is on a snapshot schedule | the same, for `DASH_UPDATE_SNAPSHOT_DATASET` - **the CR-10 line** |
| a snapshot was actually taken in the last day | the newest enabled task's last run is under 25 h old (WPK-6: a schedule that stopped running looks identical to one that works) |
| this server only accepts CC Sync builds we signed | `DASH_RELEASE_PUBKEYS` is set. Only the COUNT is ever rendered, never a key |
| the release signing key has been backed up | an admin recorded a date. Not applicable, so `[ CANNOT VERIFY ]`, on a site with no signing key at all |
| somebody has actually restored from a backup this year | a recorded date under 365 days old |
| files deleted on the server are kept for a year | every project's live Syncthing folder carries versioning with a `maxAge` |
| deleted-file copies on editors' computers are within their limit | every reporting machine's `.ccsync-trash` is under 50 GB (the 14-day half of the rule is not reported by any companion, and the line says so) |
| somebody is told when this server finds a problem | a sink is configured AND `alert_log` holds a successful send inside 30 days |

**The ninth line** (SYS-1 / DDIAG-16, 2026-09-04) is the panel's own
mechanism: eight lines about safety nets and none about whether their failure
ever reaches a person. It is `error`, so a vendor default with no sink says so
out loud on PROBLEMS THE SERVER FOUND, and its consequence sentence counts
`alerts.ALERT_KINDS` rather than naming a number that goes stale. Green needs
BOTH halves, because a mailbox that started bouncing in March is the same hole
as no sink at all and it is the more dangerous of the two. The verdict itself
is **`alerts.sink_deliverable(conn) -> (ok, one line in editor English)`**,
shared with invariant 15 (`alerts_deliverable`) so the panel and the invariant
can never disagree; it RAISES rather than answering False when the ledger
cannot be read, and both callers turn that into `[ CANNOT VERIFY ]`.

Both dataset names come from the site manifest (`[tree] dataset`,
`[apps] dataset`) or, unset, from the deploy's own lookup on the NAS -
see "What this deployment has to be given" below (2026-09-03).

Neither dataset name is a Settings field: a container sees `/data` and
`/projects`, never the pool path behind them, so the pool-side names are
deployment facts from the environment. **Unset is `[ CANNOT VERIFY ]` naming
the variable, never "there is no snapshot"** - a question nobody asked is not
an answer.

### The two dates only a human can supply

The signing key lives on one workstation and is deliberately in no
repository; a restore drill happens outside this product. Both are stored as
**dates, not booleans** (`meta.protection_acks`), because "the key is backed
up" is a claim that ages and a drill from 2024 is not a drill. The buttons
are `[ I HAVE BACKED IT UP ]` and `[ RECORD A RESTORE ]`, both audited
(`protection.ack`), both refusing an unreadable or future date on the page
rather than swallowing it. `protection.record_restore_drill()` is the same
store for a drill the dashboard performs itself (SYS-15d).

### Where the results go

* **One NAS read per pass, shared.** The panel rides the `invariants`
  collector kind and the memoised `protection.nas_probe`, so
  `/pool/snapshottask` is fetched once and the invariant and the panel can
  never disagree about what the NAS said at two different moments. Every
  external read is bounded and fails to `[ CANNOT VERIFY ]`, never to an
  exception on a page or in the cycle.
* **Notices** (`protection_missing`, error; `protection_unverifiable`, warn),
  so PROBLEMS THE SERVER FOUND carries them with no second edit. Unverifiable
  is a warn deliberately: a warn is said once and not again until it clears,
  which is what makes DSM's permanent amber honest instead of nagging.
* **Alerts**, the two matching kinds in `alerts.ALERT_KINDS`.
* **The weekly report**, as a standing WHAT IS PROTECTED block printed every
  week whether or not anything is wrong. A block that appeared only on bad
  weeks would make its absence read as good news.
* **The panel**, Settings -> PROTECTION. THE REGISTRY IS THE SPINE: a line no
  pass has evaluated yet renders `[ CANNOT VERIFY ]` rather than being absent
  from the page.

There is no new table. The last verdict per line and the two dates live in
`meta` (`protection_results`, `protection_acks`); the schema number reserved
for this package was given back unused (wave 5 ended up 39 invariants, 40
recovery, 41 unused - see section 15).

### Adding a protection line

Add one `ProtectionLine(key, title, what, consequence, fix, check, severity)`
to `protection.LINES`. The rules are the invariant rules, plus one: **never
return `ok` for a mechanism you inferred rather than observed.** The whole
package exists because absence is silent.

## 15. Getting something back: the recovery page

SYS-15 (resilience sweep 2026-08-28), built 2026-08-29 as wave 5.
`dashboard/src/ccsync_dashboard/recovery.py`, Settings -> RECOVERY.

Section 14 tells the owner what is not protected. This one is what he does
when the thing that was protected has to come back.

**Every recovery this product documented was a root SSH session** requiring
judgements a non-technical owner cannot supply: is `apps` a dataset or a plain
directory (which decides which of two `cp` lines is right, and whether a
snapshot of it exists at all), which snapshot, is everything since it
expendable, has the fleet stopped writing - and, platform dependent and
destructive if wrong, `chown` is REQUIRED on TrueNAS and DELETES the share's
ACL on DSM. `docs/BACKUP_RESTORE.md` is still the reference for what those
commands do; what changed is that it is no longer the first thing anybody
reaches for.

### The four parts

**(a) Snapshot browse-and-restore, into a quarantine folder.** Pick a project,
pick a snapshot, see what is missing, restore. Everything lands in
`<project>/.restored-<ts>/`: **nothing is overwritten, nothing is deleted and
nothing is chowned**. That is the design, not a limitation. It removes the one
judgement an owner cannot make, because a wrong snapshot now costs disk space
and nothing else, and the two copies can be compared afterwards by somebody
looking at files rather than at a shell. A destination that already exists is
refused rather than merged, and the leading dot keeps a restored copy of a
project (marker and all) out of `provision`'s project scan.

**(b) An admin-side Resolve undo.** The tray's "Undo the last clip-path change
CCSync made" on somebody else's computer, delivered as `commands.resolve_undo`
on the report channel and answered on it. It replays the same journal through
the same `resolve_bridge.undo_last_relink`, so both routes carry the same
refusals; a refusal that clears itself (Resolve closed, another project open)
is answered `retrying` and the command comes back on the next report.

**(c) The guided runbook.** Five questions in the owner's words, each with a
plan: what this server can do itself, and what has to be typed on the NAS -
with this NAS's real names already in it.

**(d) The restore drill.** One real file, out of a real snapshot, into a
scratch folder under `/data`, hashed, deleted, and the DATE recorded through
`protection.record_restore_drill`. It is what turns section 14's "somebody has
actually restored from a backup this year" line green, and a drill that fails
records nothing there.

### The rule that makes the printed commands safe

**A command is never printed on a guess.** Each step declares the facts it
needs; a fact this server could not VERIFY produces a refusal naming the fact
and how to supply it, and no command at all.

| Fact | Verified by | Unverified means |
|---|---|---|
| which kind of NAS this is | a bounded `ping` to the NAS | no command that differs between TrueNAS and DSM is printed at all, `chown` above all |
| the dataset the tree is on | a snapshot task on the NAS naming it, or a recursive parent | this server will not print a path with that name in it: it cannot tell a dataset from a plain directory, which is CR-10 exactly |
| the dataset this dashboard's data is on | the same | as above, and this is the one that is a directory on the live NAS today |
| the storage pool | follows from the tree's dataset | not printed |
| the container's name | `DASH_CONTAINER_NAME` | no `docker stop` line |
| snapshots this server can read | a readable `DASH_SNAPSHOT_DIR` | no self-service restore and no drill; the page says so and offers the manual route |

A generated `zfs rollback` with a guessed dataset in it is worse than no
command at all: the doc at least makes the reader think about the name.

### What this deployment has to be given

Both are read-only facts about the deployment, not settings an editor sees:

* `DASH_SNAPSHOT_DIR` - a directory inside the container whose ENTRIES are
  snapshots (`/mnt/<pool>/<dataset>/.zfs/snapshot` on TrueNAS,
  `/volume1/@sharesnap/<share>` on DSM), mounted read-only. **Unset is "this
  server was never told", never "there are no snapshots."**
* `DASH_SNAPSHOT_PROJECTS_SUBPATH` - the path from one snapshot's root to the
  Projects tree inside it, e.g. `Creators_Club/Projects`. Empty means the
  snapshot root is the tree.
* `DASH_TREE_DATASET` / `DASH_UPDATE_SNAPSHOT_DATASET` - the two dataset
  names, shared with the protection panel. **The deploy sets both since
  2026-09-03** (`server/install_dashboard_app.datasets_env`): site.toml
  `[tree] dataset` / `[apps] dataset` if the manifest names them, otherwise
  what the deploy's own dataset lookup on the NAS answers for the tree root
  and the apps root. Where it cannot ask - Synology, a dry run, no SSH - it
  passes a blank rather than the string-surgery guess, so the line stays
  CANNOT VERIFY instead of reporting a backup that is missing. Until then
  the panel told operators to set a variable the deploy had no source for,
  so `protection_unverifiable` could not be cleared by an operator at all.
* `DASH_CONTAINER_NAME` - only ever substituted into a printed command.

### Storage

Schema **v40**: `resolve_undo_requests` (the undo's request ledger, on the
`file_moves` acknowledgement contract) and `machine_state.resolve_journals`
(what each machine reports it holds, names and counts only). The restore and
the drill add no table: files into a quarantine directory, and a date into
`meta` (`recovery_restores`, `recovery_drills`, plus the protection panel's
`protection_acks`).

### Adding a recovery

Add a `Problem(key, question, detail, build)` row to `recovery.PROBLEMS`. The
`build` callable returns `Step`s; use `_command_step(title, body, commands,
needs, facts)` for anything printed, never a formatted string of your own -
that helper is where the refusal lives, and it is the finding.
