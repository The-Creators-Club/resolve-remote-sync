<!-- Maintainers: this is an inventory verified line by line against the
     code as it stood on 2026-09-25 (first written 2026-08-17). Re-verify
     every citation after any change to
     companion/src/ccsync_companion/reporter.py, capabilities.py or the
     dashboard's /api/v1/report route. A telemetry disclosure that has drifted
     from the code is worse than none. ENG-GAP markers flag statements that
     describe a missing feature; update them when the feature ships. -->

# CC Sync: telemetry disclosure

**Version 1.0, 2026-09-25.**

This document states, exactly, what the CC Sync companion sends from an
editor's workstation to the CC Sync dashboard, how often, over what transport,
where it is stored, for how long, and who can see it.

Two things make this disclosure necessary rather than nice to have:

1. The dashboard is operated **by the customer**, on the customer's own NAS.
   Nothing here reaches Cablewrap Creative Ltd. (the Licensor). But it does
   reach the customer's **admins**, and it describes the customer's
   **staff**.
2. The payload includes the **name of the DaVinci Resolve project the editor
   currently has open**, **how long since their workstation last received
   keyboard or mouse input**, the **file names and sizes of the video media on
   their workstation's local disk**, and their **Resolve media-pool bin
   structure**, refreshed continuously, all day, per named person. Under
   GDPR that is processing of personal data about employees, and in several
   EU member states it engages works-council or co-determination duties
   before it may be switched on at all. See "Employee monitoring", below.

**Nothing in this system is anonymous.** Every row is keyed by
`(editor_username, machine)`, and the username is a *verified* one: the
dashboard rejects a report whose signed identity token does not match the
claimed name (`api.api_report`).

## Verification

Every claim below was read out of the source and is cited as
`file.py:symbol`. Where a statement depends on how a customer has configured
their deployment, it says so.

## The report payload, field by field

Built by `companion/src/ccsync_companion/reporter.py:DashboardReporter._build_payload`
and POSTed as one JSON body. Field names below are the **exact wire keys**.

### Always sent (every tick, "light" or "heavy")

| Wire key | What it actually is | Source |
|---|---|---|
| `editor_name` | The editor's verified dashboard username. Lower-cased server-side and used as the primary key of nearly every table. | `reporter.py:_build_payload`, resolved by `reporter.py:post_once` from `app.CompanionApp.editor_identity` (`identity.py`) |
| `machine` | **The workstation's hostname**, `platform.node()`, verbatim. In practice the name of the physical machine on the person's desk. | `reporter.py:_build_payload` |
| `machine_id` | A random identifier the companion creates once per computer (`~/.ccsync/machine.json`), so a renamed computer keeps its sync plan. | `reporter.py:_build_payload` ← `machine.machine_id` |
| `syncthing_device_id` | This computer's Syncthing device ID. | `reporter.py:_build_payload` |
| `companion_version`, `platform`, `arch` | The companion build running, `windows` or `macos`, and the processor architecture. | `reporter.py:_build_payload` ← `config.VERSION`, `upgrade.platform_key()`, `upgrade.arch_key()` |
| `reported_at` | UTC ISO-8601 timestamp of the tick, by the workstation's clock. | `reporter.py:_build_payload` |
| `lanes[].name` | `A` / `B` / `C`: which sync lane. | `reporter.py:_build_payload` |
| `lanes[].state`, `state_since`, `progress_token` | idle / syncing / error and so on, when that state began, and a token that changes whenever the lane makes progress. | `sync/base.py:LaneStatus`, `reporter.py:_lane_liveness` |
| `lanes[].queued`, `lanes[].transferring` | How many files are waiting or moving. | `sync/base.py:LaneStatus` |
| `lanes[].last_error` | **The last error string from that lane, verbatim**, which routinely contains file paths and therefore project and client names. | `sync/base.py:LaneStatus` |
| `lanes[].last_sync` | When that lane last completed. | `sync/base.py:LaneStatus` |
| `lanes[].detail` | Free-text status line shown on the fleet grid. | `sync/base.py:LaneStatus` |
| `lanes[].current_project` | Which project that lane is working on. | `sync/base.py:LaneStatus` |
| `lanes[].bytes_done`, `bytes_total`, `speed_bps`, `eta_seconds` | **Throughput and progress: a continuous measurement of the person's connection and how much work is moving.** | `sync/base.py:LaneStatus` |
| `lanes[].transfers[]` | Per-file live transfers: `name` (**the file name**), `direction`, `bytes_done`, `bytes_total`, `percentage`, `speed_bps`, `eta_seconds`, `project_slug`. | `reporter.py:_build_payload`; stored by `db.replace_active_transfers` |
| `completed[]` | Recently finished files: `lane`, `name` (**the file name**), `direction`, `at`. A failed POST loses that tick's entries. | `reporter.py:_build_payload` (`get_completions`) |
| `queue[]`, `current_project` | Managed mode only: the editor's ordered project queue and the project being synced now. Capped at 64. | `reporter.py:_build_payload` (`get_queue_info`) |
| **`resolve_project`** | **The name of the DaVinci Resolve project this person currently has open**, live. Empty when Resolve is closed. Names in `ignored_resolve_projects` (default `Untitled Project`, `New Doc`) are suppressed locally, and again server-side. | `reporter.py:_build_payload` ← `watcher.TimelineWatcher.last_resolve_project` |
| `lane_b_via` | `remote` or `remote_down`: which route proxy downloads used, sent only by a computer with a separate download route set. No personal data. | `reporter.py:_build_payload` ← `app` (companion 0.9.82+) |
| `mode` | `base` or `editor`: the machine's role. | `reporter.py:_build_payload` ← `app.CompanionApp.effective_mode` |
| **`capabilities`** | What this computer can do for the fleet's background jobs: GPU name and memory, whether ffmpeg, whisper and NVENC are available, CPU count and load, which storage roots it can see, which job kinds it accepts. Also, refreshed every tick: **`idle_seconds`, the seconds since this workstation last received keyboard or mouse input**; `resolve`, whether Resolve is running and the open project name; the Timeline Cards agent's state; whether the person has lent the machine to the fleet (`volunteer_until`); and why it is or is not taking work (`jobs_gate`). | `reporter.py:_build_payload` ← `app.CompanionApp.job_capabilities` ← `capabilities.build`; idle time from `idle.py` (Windows `GetLastInputInfo`, macOS `HIDIdleTime`: the time of the last input event only, never its content) |
| `transport_health` | Whether lane C is relayed or direct, orphaned `.partial` counts and bytes, express-lane failures. | `reporter.py:_build_payload` ← `app.CompanionApp.transport_health` |
| `proxy_coverage` | Counters for originals with no proxy beside them, plus a per-project map (capped at 64 projects). | `reporter.py:_build_payload` ← `app.CompanionApp.proxy_coverage` |
| `youtube_import` | Counters for whether downloaded YouTube clips reached the editor's Resolve bins. | `reporter.py:_build_payload` ← `app.CompanionApp.youtube_import_status` |
| `sync_guard` | Local safety-latch state and sync-health findings: circuit breaker, trash guard, halt, files skipped because they already exist, moved or stray project folders, shared-folder problems, clip relink events, b-roll stand-ins placed, YouTube import status, and the reporter's own health. Mostly counters and flags; some entries **name projects and files**. | `reporter.py:_build_payload` ← `app.CompanionApp.sync_guard` |
| `broll_ingest`, `music_ingest` | Progress of a b-roll or music ingest batch running on this machine, when there is one. | `reporter.py:_build_payload` ← `app.CompanionApp.broll_ingest_status`, `music_ingest_status` |
| `file_moves_applied`, `resolve_undo_applied` | This machine's answers to admin commands: a file moved on the server, a Resolve clip-path change put back. | `reporter.py:_build_payload` |

### Sent on HEAVY ticks only

| Wire key | What it actually is | Source |
|---|---|---|
| **`local_manifest`** | Keyed by project path, up to 64 projects. Per project: `n_originals`, `bytes_originals`, `n_proxies`, `bytes_proxies`, `truncated`, and, for projects the editor has selected, `originals` and `proxies`, each **a list of up to 2000 `[relative file path, size in bytes]` pairs**. That is a file-by-file inventory of the video media on the person's local disk under the sync root. | `manifest.py:scan_manifest`; wired in `app.py` (`get_local_manifest=self.manifest_cache.get`) |
| **`media_tree`** | Keyed by the **Resolve project name**; a list of every clip in that project's media pool: `bin_path` (**the editor's own bin folder structure**), `clip_name`, `file_path` (**the absolute path on their machine**), `kind`, `present`. | `app.py:get_media_tree` / `_refresh_media_tree_once` |
| `resolve_journals` | The names and counts of the Resolve clip-path changes this machine has recorded (project, time, number of clips), so an admin can choose one to undo. Never the paths themselves. | `reporter.py:_build_payload` ← `app.CompanionApp._resolve_journals` |

`local_manifest` and `media_tree` are left out of a heavy tick when they are
unchanged since the last one the dashboard accepted, and re-sent at least every
10 minutes regardless (`reporter.py:SECTION_RESEND_SECONDS`).

### Sent separately: diagnostics bundles

A diagnostics bundle is a text report of this machine's sync state (versions,
settings, lane states, the open Resolve project, recent crash summaries and
the last 40 lines of the companion log), up to 256 KB. It is sent to
`POST /api/v1/diagnostics`, not in the report, on three occasions only: the
editor presses the diagnostics button, a sync lane fails, or an admin asks that
machine for one (`app.py:build_diagnostics`, `reporter.py:post_diagnostics`).
It is never sent under an unverified identity, and the companion removes its
own token from it first.

### What is NOT sent (checked, so the absence is on the record)

- **No file contents.** Names, sizes and paths only.
- **No screenshots, no keystrokes, no webcam, no clipboard, no window titles**
  other than the Resolve project name. The idle measurement is the time since
  the last input event; what was typed or clicked is never read.
- **No EULA acceptance record.** It is written and read locally only
  (`companion/src/ccsync_companion/eula.py`, `~/.ccsync/eula_accepted.json`).
- **No password.** The tray sign-in POSTs the editor's username and password
  to `/api/v1/verify` (`identity.py`); with NAS authentication the dashboard
  verifies them against the NAS over SMB and stores nothing
  (`auth.verify_credentials`, `auth._verify_smb`). See the transport section
  below.

## How often

| Cadence constant | Default | What it governs | Source |
|---|---|---|---|
| `INITIAL_DELAY_SECONDS` | `2.0` s | First report after the tray starts. | `reporter.py` |
| `dashboard_report_interval` | **60 s** | Normal tick, and the floor on HEAVY ticks. | `config.py:DEFAULTS`; `reporter.py:DashboardReporter.__init__` |
| `dashboard_report_interval_active` | **5 s** | Tick interval while ANY lane is actively syncing. | `config.py:DEFAULTS`; `reporter.py:_select_interval` |
| `manifest_refresh_interval` | 300 s | How often the local disk is re-walked to rebuild `local_manifest`. | `config.py:DEFAULTS`; `manifest.py:ManifestCache` |
| `media_tree_refresh_interval` | 120 s | How often Resolve's media pool is re-read. | `config.py:DEFAULTS` |

In plain terms: **a report leaves the workstation every 60 seconds while idle,
and every 5 seconds while anything is syncing.** `resolve_project`,
`capabilities` (with `idle_seconds`), `lanes[]`, the live per-file
`transfers[]` and every counter above ride *every* one of those ticks.
`local_manifest`, `media_tree` and `resolve_journals` ride at most one tick
per `dashboard_report_interval` (`reporter.py:_report_loop` computes `light`).

Over a normal working day that is on the order of **1,500 to 17,000 reports
per person per day**, each naming the project they have open and how long
since they last touched the keyboard or mouse.

## Transport and authentication

- `POST {dashboard_url}/api/v1/report`, JSON body, via `urllib.request`
  (`reporter.py:post_once`, `reporter.py:default_http_post`). No redirect is
  followed.
- **Plain http is refused on the internet and noted on a private network.**
  Every request the companion makes to `dashboard_url` goes through one guard
  (`transport.py`): a plain `http://` address on the public internet is
  refused before anything is sent, and the setup wizard will not save it;
  an address on the local machine, the studio's network or a tailnet is
  allowed with a note in Settings. A name is judged public only when every
  address it resolves to is public. The dashboard stores, per computer,
  whether its last report arrived over https, plain http on a private
  network, or plain http from the internet (`machine_state.report_via`), as
  far as it can tell: behind a proxy it is not configured to trust
  (`DASH_TRUSTED_PROXIES`), an https report is recorded as plain http on a
  private network.
- Two headers authenticate the report (`reporter.py:post_once`):
  - `X-CCSync-Token`: the editor's own report token (`cce1.…`, bound to that
    person), or, during migration, the shared fleet token
    (`DASH_REPORT_TOKEN`). Checked in `app.py:_report_auth_denial` before the
    body is read, and again in `api.api_report`.
  - `X-CCSync-Identity`: a dashboard-signed identity token of the form
    `v2.identity.<user_b64url>.<expires_epoch>.<hexsig>`, which has not
    expired on its own since 2026-08-27 (the field remains, stamped a century
    out). **Required** whenever the server has a `DASH_SESSION_SECRET`; the
    report is rejected if it is absent, invalid, or names a different user
    than `editor_name` (`api.api_report`). This is what makes `editor_name`
    trustworthy rather than self-asserted.
- The reply carries the update offer, admin commands for this machine and the
  `resolve_project_unmapped` prompt back to the companion (`api.api_report`).
- Body ceiling: 8 MiB (`app.MAX_REPORT_BODY_BYTES`); the companion sheds heavy
  sections to fit (`reporter.py:_fit_payload`).

## Where it is stored, and for how long

Storage is a single SQLite file on the customer's NAS: `/data/dashboard.db`
(`settings.py`, `DASH_DB_PATH`).

| Payload section | Table | Retention | Source |
|---|---|---|---|
| `lanes[]` current state | `lane_report_current` | **30 days** after the machine stops reporting | `db.LANE_HISTORY_MAX_AGE_DAYS`, `db.prune` |
| lane state changes | `lane_report_history` | **30 days** | `db.LANE_HISTORY_MAX_AGE_DAYS`, `db.prune` |
| `machine`, `resolve_project`, `mode`, `platform`, `companion_version`, `capabilities` (including `idle_seconds`), `transport_health`, `sync_guard`, `proxy_coverage`, `broll_ingest`, `music_ingest`, `resolve_journals`, detected project root, verified flag | `machine_state` | **30 days** after it stops reporting | `db.MACHINE_STATE_MAX_AGE_DAYS`, `db.prune` |
| `machine_id`, `syncthing_device_id` | `machines` (the computer registry) | until an admin removes the computer or deletes the person | `api._register_machine`, `db.forget_machine` |
| `lanes[].transfers[]` | `active_transfers` | rows expire **120 s** past `updated_at`; the set is replaced wholesale each report | `db.ACTIVE_TRANSFER_STALE_SECONDS`, `db.replace_active_transfers` |
| `completed[]` | `transfer_history` | **7 days** | `db.prune` |
| `local_manifest` rollups | `editor_media_project` | **14 days** after it stops reporting | `db.MEDIA_REPORT_MAX_AGE_DAYS` |
| `local_manifest` per-file lists | `editor_media` (`rel_path`, `kind`, `size`) | **14 days**; capped at 2000 rows per (editor, machine, project) per kind | `db.MEDIA_REPORT_MAX_AGE_DAYS`, `db.EDITOR_MEDIA_CAP` |
| `media_tree` | `media_tree_clips` (`bin_path`, `clip_name`, `file_path`, `kind`, `present`) | **14 days**; capped at 4000 rows per (editor, machine, project) | `db.MEDIA_REPORT_MAX_AGE_DAYS`, `db.MEDIA_TREE_CAP` |
| diagnostics bundles | `diagnostics` | **30 days**, and only the newest 5 per machine | `db.DIAGNOSTICS_MAX_AGE_DAYS`, `db.DIAGNOSTICS_KEEP_PER_MACHINE` |
| `resolve_project` → tree project mapping | `project_roots` | **no expiry, sticky by design**; the first confident match is stored and only an admin changes it | `api.api_report`, `db.sticky_project_root` |
| the fact that this editor exists | `known_editors` | **no expiry** until the person is deleted | `db.record_known_editor` |
| `queue`, `current_project`, top-level `youtube_import` | **not stored** | | the dashboard reads the YouTube import state from the copy inside `sync_guard` |

**Two honest caveats about "retention".**

1. **Retention is measured from the last report, not from collection.** Rows
   are upserted in place with a fresh timestamp. So for a person who is at
   work every day, the *current* picture (which project they have open,
   whether they are at their keyboard, what is on their disk, their bin tree)
   is held for as long as they keep working, and the 14- and 30-day figures
   only describe how long a record survives after someone stops using the
   Software. `lane_report_history` and `transfer_history` are the genuinely
   time-bounded histories.
2. **Pruning only runs if the collector runs.** `db.prune` is reachable from
   one place, the collector's hourly `prune` cycle (`collector.py`,
   `settings.interval_prune` = 3600 s). The collector keeps `prune` in
   `SYNCTHING_FREE_KINDS` so a deployment without Syncthing still expires
   data, and the dashboard's home page shows when the collector has stopped.
   The collector panel on the home page shows when retention last ran and turns
   amber when it is overdue, and a failed or overdue retention pass raises an
   alert.

An administrator can export everything the dashboard holds about a person,
erase their activity history while keeping their account, or delete them
entirely, as described under "Data-subject rights" in
`docs/legal/PRIVACY.md`. Each person can also export their own data from
their account page.

## Who can see it

Access is decided by `auth.Scope` (`auth.scope_for`, `auth.is_admin`):

- **Admins** (usernames in `DASH_ADMIN_USERS`, and, with the dashboard's own
  accounts, users given the admin role) see the **whole fleet**, and may
  focus any single editor with `?as=<editor>`.
- **Non-admin editors** are locked to their own identity: `Scope.editor`
  returns their own username and `Scope.allows()` is false for anyone else,
  regardless of query string.
- The report endpoint accepts a report token, but a report can only be
  *written* as the editor named in the signed identity token.

Surfaces that render it (all behind the dashboard login; `app.py`
`_OPEN_EXACT` lists the routes that need no session, which are sign-in,
first-run setup, health, the public site manifest, and the companion's own
credential-checked write endpoints):

| Surface | Shows |
|---|---|
| `GET /` (`ui.page_fleet`) and `GET /partials/fleet` | The fleet grid: every machine, its editor, lane states, speeds, errors, and the Resolve project each person has open |
| `GET /transfers`, `GET /partials/transfers` | Live per-file transfers and recent history, per editor |
| `GET /project/{slug}`, `GET /partials/project/{slug}` | Per-project presence: which editor has which files |
| `GET /partials/project/{slug}/bins` | The Resolve media-pool bin tree reported by an editor's machine |
| `GET /partials/project/{slug}/missing/{device_id}` | Files an editor's device is missing |
| `GET /editors`, `GET /api/v1/editors` | The editor list view |
| `GET /api/v1/projects/{slug}/presence` | Presence view, scoped by `auth.scope_for` |
| `GET /admin/diagnostics`, `GET /partials/health-diagnostics`, `GET /partials/computer-answer` | Admin only: diagnostics bundles and crash reports |
| `GET /api/v1/jobs` and the Settings JOBS page | Background jobs, and each machine's capabilities and idle state as the scheduler sees them |
| `GET /admin/users`, `GET /partials/admin/users` | Admin-only user management |

Anyone with filesystem or shell access to the NAS can read
`/data/dashboard.db` directly, bypassing all of the above. That is the
customer's own infrastructure and its own access-control responsibility, and
its DPO should know it.

## What can be turned off

| Want to disable | How | Effect |
|---|---|---|
| **All reporting** | Leave `dashboard_url` blank in `~/.ccsync/config.toml` | `DashboardReporter.enabled` is false, `start()` is a no-op and the thread is never created (`reporter.py:enabled`, `reporter.py:start`). No reports also means no managed sync selections and no updates, so in practice this turns off the product for that workstation, not just the telemetry. |
| Reporting under an unverified name | `require_login = true` (the default) | `post_once` returns without making any request until the editor signs in (`reporter.py:post_once`). |
| Specific Resolve projects | Add the name to `ignored_resolve_projects` (default `["Untitled Project", "New Doc"]`) | That project's name is never reported and its `media_tree` is never cached or sent (`app.py:_refresh_media_tree_once`); the dashboard drops it again server-side (`api.is_ignored_resolve_project`). This is a per-project opt-out, not a per-person one. |
| Reporting *less often* | Raise `dashboard_report_interval` and `dashboard_report_interval_active` | Fewer ticks. Must be positive (`config.validate_config`). |
| Taking fleet background jobs | `jobs_enabled = false` | This machine takes no background jobs. It still reports `capabilities`, including `idle_seconds`. |

**Four more switches, per computer or for the whole site.** On a computer:
Settings, THIS COMPUTER, PRIVACY (or the setup wizard's privacy step). For
the whole site: the dashboard's Settings, Site, TELEMETRY. They are:
`resolve_project` (the open project's name, wherever the companion reports
it, including Resolve health, fix journals and the answers to an undo),
`local_manifest` (the disk file list, plus the file names in the Resolve
health and sync-conflict checks, which are then sent only as counts, the
names of stray or moved project folders, and the sample file names from
upload checks), `media_tree` (the bin structure; switching off the project
name switches this off too, because the bin structure is organised by
project name), and `input_idle` (the idle time, which is also not sent while
`jobs_enabled` is false). Sync is not affected.

A switched-off item is not sent. The dashboard also discards it on arrival
from any computer while the site switch is off, including computers whose
companion predates these switches. It deletes what it already held: for a
site switch at once for every computer, and for a computer's own switch on
that computer's next report, together with that computer's stored
diagnostics bundles. A site switch can only switch items off; a computer
cannot switch back on what the site has switched off, and the dashboard
cannot switch a computer's own switches back on.

Still sent, because sync or the editor's own action needs them: the names
of files being transferred and recently transferred, the result of a file
move the dashboard ordered, a project name the editor types or sends when
setting up a project, and, only if an editor turns on the Timeline Cards
agent for their computer, the project and timeline it is driving.

The costs are deliberate. With the file list off, the dashboard sends every
file move in every active project to that computer, and shows its holdings
and upload progress as "not reported". With the project name off, the
dashboard does not offer to set up a new project for it, the editor cannot
be the first to map a Resolve project to a folder (an administrator can),
and projects are not mapped automatically from that computer. With the idle
time off, that computer is not offered background jobs that wait for an
idle computer. While the project name is switched off for the whole site, a
computer whose companion predates these switches cannot have CC Sync's
fixes to its Resolve projects undone from the dashboard (it can still undo
them from its own tray). While the project name, the file list or the bin
structure is switched off for the whole site, that computer's diagnostics
bundles are replaced by a note, because it cannot remove the withheld names
from them itself; the same note replaces a bundle from any computer that
has not yet read a site switch that was just turned off (a computer rereads
the site's settings every 15 minutes).

## Employee monitoring: for the customer's DPO

Read this part twice.

CC Sync continuously records, per named employee:

- **which project they are working on right now**, updated as often as every
  5 seconds;
- **whether they are at their keyboard**: `capabilities.idle_seconds` is the
  time since the last keyboard or mouse input, on every report;
- **when they start and stop**: `reported_at`, `idle_seconds` and
  `lanes[].last_sync` make presence and idleness trivially derivable, whether
  or not anyone intends to derive them;
- **what is on their workstation's disk**, file by file, with sizes;
- **how they have organised their own work**: the Resolve bin tree;
- **how fast their connection is** and how much data they move.

The idle time exists so background jobs run only on machines nobody is using;
it is also, plainly, a presence signal.

This is systematic monitoring of workers' activity. Plainly:

1. **You are the data controller.** The dashboard runs on your hardware, your
   admins read it, and you decide who is an admin. Cablewrap Creative Ltd.
   receives none of it (see `docs/legal/PRIVACY.md`).
2. **"Legitimate interests" is the realistic lawful basis, and consent is
   not.** Consent from an employee to their employer is rarely freely given
   (EDPB Guidelines 05/2020; WP29 Opinion 2/2017 on data processing at work).
   Do the balancing test and write it down.
3. **You almost certainly need a DPIA.** Art. 35(3)(b) GDPR, and "systematic
   monitoring of employees" appears on essentially every supervisory
   authority's mandatory-DPIA list.
4. **Works councils.** In Germany a system capable of monitoring employee
   performance or behaviour requires the works council's agreement *before*
   rollout (BetrVG §87(1) No. 6), and courts read "capable of" broadly, so it
   applies even if you never look. Comparable duties exist in Austria, the
   Netherlands, France and the Nordics. **Settle this before deployment, not
   after.**
5. **Tell people.** Arts. 13 and 14 GDPR. `docs/legal/PRIVACY.md` is written
   to be adapted into a staff-facing notice; the field tables at the top of
   this document are the part employees are entitled to see.
6. **Data minimisation (Art. 5(1)(c)) is the weak point.** `resolve_project`,
   `idle_seconds`, `local_manifest` and `media_tree` exist to make *sync* and
   background work run and be diagnosable, not to measure people, but they
   cannot currently be switched off individually (see "What can be turned
   off"). Weigh that in your assessment.
7. **Purpose limitation.** Decide, in writing, that this data is used for
   diagnosing sync problems and scheduling background work and not for
   performance management, and enforce it, because a supervisory authority
   will ask, and every admin can see the fleet grid.

**Not a defence, but relevant to proportionality:** the data never leaves the
customer's own infrastructure, retention is bounded once a person stops
reporting, and non-admin editors can see only themselves.

## Other records the dashboard keeps

- **Web server access logs.** Off by default: the container starts uvicorn
  with `--no-access-log` (`dashboard/deploy/run.sh`). A customer that sets
  `DASH_ACCESS_LOG=1` turns on uvicorn's per-request log (client address,
  method, path, status) in the container's log output, which is then a
  second record of who used the dashboard when; how long it is kept is
  decided by the customer's container host.
- **The admin audit log** (`fleet_audit`): which admin took which fleet
  action, and when. 180 days.
