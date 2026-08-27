<!-- DRAFT FOR COUNSEL — NOT LEGAL ADVICE. Written 2026-08-17 for
     docs/COMMERCIAL_READINESS.md item 3, which found that the companion
     "reports the open Resolve project name, the local media manifest and the
     media-pool bin tree every few seconds, which is employee monitoring under
     GDPR" — and that nothing disclosed it anywhere.
     This document is an ENGINEER'S INVENTORY, verified line by line against
     the code on 2026-08-17. It is the factual basis a customer's DPO needs to
     run their own assessment; it is not a legal opinion and it has not been
     reviewed by a qualified legal professional.
     TODO(legal): replace "Cablewrap Creative" with the registered legal
     entity name. The placeholder was inferred from the operator's email
     domain and is almost certainly NOT the correct
     contracting entity — confirm before use.
     TODO(engineering): re-verify every citation here after any change to
     companion/src/ccsync_companion/reporter.py or the dashboard's
     /api/v1/report route. A telemetry disclosure that has drifted from the
     code is worse than none. -->

# CC Sync — telemetry disclosure

**Draft of 2026-08-17. DRAFT FOR COUNSEL — not legal advice.**

This document states, exactly, what the CC Sync companion sends from an
editor's workstation to the CC Sync dashboard, how often, over what transport,
where it is stored, for how long, and who can see it.

Two things make this disclosure necessary rather than nice to have:

1. The dashboard is operated **by the customer**, on the customer's own NAS.
   Nothing here reaches Cablewrap Creative. But it does reach the customer's
   **admins**, and it describes the customer's **staff**.
2. The payload includes the **name of the DaVinci Resolve project the editor
   currently has open**, the **file names and sizes of the video media on their
   workstation's local disk**, and their **Resolve media-pool bin structure** —
   refreshed continuously, all day, per named person. Under GDPR that is
   processing of personal data about employees, and in several EU member states
   it engages works-council/co-determination duties before it may be switched
   on at all. See "Employee monitoring", below.

**Nothing in this system is anonymous.** Every row is keyed by
`(editor_username, machine)`, and the username is a *verified* one: the
dashboard rejects a report whose signed identity token does not match the
claimed name (`api.api_report`).

## Verification

Every claim below was read out of the source on 2026-08-17 and is cited as
`file.py:symbol`. Anything that could not be verified is marked
**NOT VERIFIED** and says why.

Concurrency caveat: this was written during a multi-agent editing pass on the
same working tree. `sync_guard` in particular was added to the payload while
this document was being written. Re-verify before publication.

## The report payload, field by field

Built by `companion/src/ccsync_companion/reporter.py:DashboardReporter._build_payload`
and POSTed as one JSON body. Field names below are the **exact wire keys**.

### Always sent (every tick, "light" or "heavy")

| Wire key | What it actually is | Source |
|---|---|---|
| `editor_name` | The editor's verified NAS/dashboard username. Lower-cased server-side and used as the primary key of nearly every table. | `reporter.py:_build_payload`, resolved by `reporter.py:post_once` from `app.CompanionApp.editor_identity` (`identity.py`) |
| `machine` | **The workstation's hostname** — `platform.node()`, verbatim. In practice this is the name of the physical machine on the person's desk. | `reporter.py:_build_payload` |
| `companion_version` | The companion build running (e.g. `0.7.11`). | `reporter.py:_build_payload` ← `config.VERSION` |
| `platform` | `windows` or `macos`. | `reporter.py:_build_payload` ← `upgrade.platform_key()` |
| `reported_at` | UTC ISO-8601 timestamp of the tick. | `reporter.py:_build_payload` |
| `lanes[].name` | `A` / `B` / `C` — which sync lane. | `reporter.py:_build_payload` |
| `lanes[].state` | idle / syncing / error / … | `sync/base.py:LaneStatus` |
| `lanes[].queued`, `lanes[].transferring` | How many files are waiting / moving. | `sync/base.py:LaneStatus` |
| `lanes[].last_error` | **The last error string from that lane, verbatim** — which routinely contains file paths and therefore project and client names. | `sync/base.py:LaneStatus` |
| `lanes[].last_sync` | When that lane last completed. | `sync/base.py:LaneStatus` |
| `lanes[].detail` | Free-text status line shown on the fleet grid. | `sync/base.py:LaneStatus` |
| `lanes[].current_project` | Which project that lane is working on. | `sync/base.py:LaneStatus` |
| `lanes[].bytes_done`, `bytes_total`, `speed_bps`, `eta_seconds` | **Throughput and progress — i.e. a continuous measurement of the person's internet connection and how much work is moving.** | `sync/base.py:LaneStatus` |
| `lanes[].transfers[]` | Per-file live transfers: `name` (**the file name**), `direction`, `bytes_done`, `bytes_total`, `percentage`, `speed_bps`, `eta_seconds`, `project_slug`. | `reporter.py:_build_payload`; stored by `db.replace_active_transfers` |
| `completed[]` | Up to 200 recently finished files per tick: `lane`, `name` (**the file name**), `direction`, `at`. DRAIN semantics — a failed POST loses that tick's entries. | `reporter.py:_build_payload` (`get_completions`) |
| `queue[]`, `current_project` | Managed mode only: the editor's ordered project queue and the project being synced now. Capped at 64. | `reporter.py:_build_payload` (`get_queue_info`) |
| **`resolve_project`** | **The name of the DaVinci Resolve project this person currently has open**, live. Empty when Resolve is closed. Names in `ignored_resolve_projects` (default `Untitled Project`, `New Doc`) are suppressed locally, and again server-side. | `reporter.py:_build_payload` ← `watcher.TimelineWatcher.last_resolve_project` |
| `mode` | `base` or `editor` — the machine's role. | `reporter.py:_build_payload` ← `app.CompanionApp.effective_mode` |
| `transport_health` | Whether lane C is relayed or direct, orphaned `.partial` counts and bytes, express-lane failures. | `reporter.py:_build_payload` ← `app.CompanionApp.transport_health` |
| `proxy_coverage` | Counters for originals with no proxy beside them, plus a per-project map (capped at 64 projects). | `reporter.py:_build_payload` ← `app.CompanionApp.proxy_coverage` |
| `youtube_import` | Counters for whether downloaded YouTube clips reached the editor's Resolve bins. | `reporter.py:_build_payload` ← `app.CompanionApp.youtube_import_status` |
| `sync_guard` | Local safety-latch state: circuit breaker, trash guard, halt, and lane A's "skipped, exists" counter. Counters and flags; no file paths observed. **Added 2026-08-17 by concurrent work — re-verify.** | `reporter.py:_build_payload` ← `app.CompanionApp.sync_guard` (`app.py:3453`) |

### Sent on HEAVY ticks only

| Wire key | What it actually is | Source |
|---|---|---|
| **`local_manifest`** | Keyed by project rel-path, up to 64 projects. Per project: `n_originals`, `bytes_originals`, `n_proxies`, `bytes_proxies`, `truncated`, and — for projects the editor has selected — `originals` and `proxies`, each **a list of up to 2000 `[relative file path, size in bytes]` pairs**. That is a file-by-file inventory of the video media on the person's local disk under the sync root. | `manifest.py:scan_manifest` (entry built at `manifest.py:176-187`); wired at `app.py:953` |
| **`media_tree`** | Keyed by the **Resolve project name**; a list of every clip in that project's media pool: `bin_path` (**the editor's own bin folder structure**), `clip_name`, `file_path` (**the absolute path on their machine**), `kind`, `present`. | `app.py:get_media_tree` / `_refresh_media_tree_once` (`app.py:2239-2299`) |

### What is NOT sent (checked, so the absence is on the record)

- **No file contents.** Names, sizes and paths only.
- **No screenshots, no keystrokes, no webcam, no clipboard, no window titles**
  other than the Resolve project name above.
- **No installer version.** (`installer_version` appears only in
  `companion/tests/test_eula.py`; nothing in `companion/src` sends it.)
- **No EULA acceptance record.** It is written and read locally only
  (`companion/src/ccsync_companion/eula.py`, `~/.ccsync/eula_accepted.json`).
- **No password.** The tray sign-in POSTs the editor's NAS username and
  password to `/api/v1/verify` (`identity.py`), which verifies them against
  the NAS over SMB and stores nothing (`auth.verify_credentials`,
  `auth._verify_smb`). See the transport warning below, though.

## How often

| Cadence constant | Default | What it governs | Source |
|---|---|---|---|
| `INITIAL_DELAY_SECONDS` | `2.0` s | First report after the tray starts. | `reporter.py:85` |
| `dashboard_report_interval` | **60 s** | Normal tick, and the floor on HEAVY ticks. | `config.py:217`; `reporter.py:DashboardReporter.__init__` |
| `dashboard_report_interval_active` | **5 s** | Tick interval while ANY lane is actively syncing. | `config.py:223`; `reporter.py:_select_interval` |
| `manifest_refresh_interval` | 300 s | How often the local disk is re-walked to rebuild `local_manifest`. | `config.py:227`; `manifest.py:ManifestCache` |
| `media_tree_refresh_interval` | 120 s | How often Resolve's media pool is re-read. | `config.py:232` |

In plain terms: **a report leaves the workstation every 60 seconds while idle,
and every 5 seconds while anything is syncing.** `resolve_project`,
`lanes[]`, the live per-file `transfers[]` and every counter above ride
*every* one of those ticks. `local_manifest` and `media_tree` ride at most one
tick per `dashboard_report_interval` (`reporter.py:_report_loop` computes
`light`).

Over a normal working day that is on the order of **1,500–17,000 reports per
person per day**, each naming the project they have open.

## Transport and authentication

- `POST {dashboard_url}/api/v1/report`, JSON body, via `urllib.request`
  (`reporter.py:post_once`, `reporter.py:default_http_post`).
- **The scheme is whatever `dashboard_url` says. Today, in the live fleet, it
  is plain HTTP.** VERIFIED on this machine: `~/.ccsync/config.toml` reads
  `dashboard_url = "http://192.168.0.10:8480"`. `config.validate_config`
  accepts `http://` with no cleartext warning (`config.py:1270`). The same
  cleartext channel carries the sign-in POST that contains the editor's **NAS
  password** (`identity.py`).
  - Mitigating context, not a fix: that traffic is confined to the customer's
    LAN or their Tailscale tailnet (WireGuard-encrypted). The decided publish
    path as of 2026-08-17 is Tailscale Serve, which terminates HTTPS
    (`docs/SERVER-SYNOLOGY.md`).
  - **TODO(engineering):** refuse, or at minimum warn loudly on, an `http://`
    `dashboard_url` that is not loopback. Related: `docs/COMMERCIAL_READINESS.md`
    item 4 (the upgrade channel has the same problem, with worse consequences).
- Two headers authenticate the report (`reporter.py:post_once`):
  - `X-CCSync-Token` — the fleet report token (`DASH_REPORT_TOKEN`). A
    **shared** secret held by every editor. Checked in
    `app.py:_report_auth_denial` before the body is read, and again in
    `api.api_report`.
  - `X-CCSync-Identity` — a dashboard-signed identity token of the form
    `v2.identity.<user_b64url>.<expires_epoch>.<hexsig>`, non-expiring since
    CR-86 (the field remains, stamped a century out). **Required** whenever
    the server has a `DASH_SESSION_SECRET`; the report is rejected 401 if it is
    absent, invalid, or names a different user than `editor_name`
    (`api.api_report`). This is what makes `editor_name` trustworthy rather
    than self-asserted.
- The reply carries the upgrade advertisement and the
  `resolve_project_unmapped` prompt back to the companion (`api.api_report`).
- Body ceiling: 8 MiB (`app.MAX_REPORT_BODY_BYTES`); the companion sheds heavy
  sections to fit (`reporter.py:_fit_payload`).

## Where it is stored, and for how long

Storage is a single SQLite file on the customer's NAS: `/data/dashboard.db`
(`settings.py:35`, `DASH_DB_PATH`).

| Payload section | Table | Retention | Source |
|---|---|---|---|
| `lanes[]` current state | `lane_report_current` | **30 days** after the machine stops reporting | `db.LANE_HISTORY_MAX_AGE_DAYS`, `db.prune` |
| lane state changes | `lane_report_history` | **30 days** | `db.LANE_HISTORY_MAX_AGE_DAYS`, `db.prune` |
| `machine`, `resolve_project`, `mode`, `platform`, `companion_version`, `transport_health`, detected project root, verified flag | `machine_state` (+ the `ALTER TABLE` columns at `db.py:126-261`) | **30 days** after it stops reporting | `db.MACHINE_STATE_MAX_AGE_DAYS`, `db.prune` |
| `lanes[].transfers[]` | `active_transfers` | rows expire **120 s** past `updated_at`; the set is replaced wholesale each report | `db.ACTIVE_TRANSFER_STALE_SECONDS`, `db.replace_active_transfers` |
| `completed[]` | `transfer_history` | **7 days** | `db.prune` |
| `local_manifest` rollups | `editor_media_project` | **14 days** after it stops reporting | `db.MEDIA_REPORT_MAX_AGE_DAYS` |
| `local_manifest` per-file lists | `editor_media` (`rel_path`, `kind`, `size`) | **14 days**; capped at 2000 rows per (editor, machine, project) | `db.MEDIA_REPORT_MAX_AGE_DAYS`, `db.EDITOR_MEDIA_CAP` |
| `media_tree` | `media_tree_clips` (`bin_path`, `clip_name`, `file_path`, `kind`, `present`) | **14 days**; capped at 4000 rows per (editor, machine, project) | `db.MEDIA_REPORT_MAX_AGE_DAYS`, `db.MEDIA_TREE_CAP` |
| `resolve_project` → tree project mapping | `project_roots` | **no expiry — sticky by design**; the first confident match is stored and only an admin changes it | `api.api_report`, `db.sticky_project_root` |
| the fact that this editor exists | `known_editors` | **no expiry** | `db.record_known_editor` |
| `proxy_coverage`, `youtube_import`, `sync_guard`, `queue`, `current_project` | **not stored at all** | — | no reference to them exists in `api.py` or `db.py`; pydantic's default `extra='ignore'` drops the first three before the route sees them |

**Two honest caveats about "retention".**

1. **Retention is measured from the last report, not from collection.** Rows
   are upserted in place with a fresh timestamp. So for a person who is at
   work every day, the *current* picture — which project they have open, what
   is on their disk, their bin tree — is held **indefinitely**, and the 14/30
   day figures only describe how long a record survives after someone stops
   using the software. `lane_report_history` and `transfer_history` are the
   only genuinely time-bounded histories.
2. **Pruning only runs if the collector runs.** `db.prune` is reachable from
   exactly one place, the collector's hourly `prune` cycle
   (`collector.py:1212`, `settings.interval_prune` = 3600 s). The collector
   deliberately keeps `prune` in `SYNCTHING_FREE_KINDS` so a Syncthing-less
   deployment still expires data (`collector.py:42,243-247`) — but a
   deployment whose collector thread has died expires nothing, silently, and
   nothing alarms on that. **TODO(engineering):** surface last-prune time on
   the admin page.

There is **no** "delete this editor's telemetry now" action, and no export
action. See "Data-subject rights" in `docs/legal/PRIVACY.md`.

## Who can see it

Access is decided by `auth.Scope` (`auth.scope_for`, `auth.is_admin`):

- **Admins** — usernames listed in `DASH_ADMIN_USERS` — see the **whole
  fleet**, and may focus any single editor with `?as=<editor>`.
- **Non-admin editors** are locked to their own identity: `Scope.editor`
  returns their own username and `Scope.allows()` is false for anyone else,
  regardless of query string.
- The report endpoint itself is open to any holder of the report token, but a
  report can only be *written* as the editor named in the signed identity token.

Surfaces that render it (all behind the dashboard login, `app.py` `_OPEN_EXACT`
lists the exceptions):

| Surface | Shows |
|---|---|
| `GET /` (`ui.page_fleet`) and `GET /partials/fleet` | The fleet grid: every machine, its editor, lane states, speeds, errors, and the Resolve project each person has open |
| `GET /transfers`, `GET /partials/transfers` | Live per-file transfers and recent history, per editor |
| `GET /project/{slug}`, `GET /partials/project/{slug}` | Per-project presence — which editor has which files |
| `GET /partials/project/{slug}/bins` | The Resolve media-pool bin tree reported by an editor's machine |
| `GET /partials/project/{slug}/missing/{device_id}` | Files an editor's device is missing |
| `GET /api/v1/editors` | The editor list view |
| `GET /api/v1/projects/{slug}/presence` | Presence view, scoped by `auth.scope_for` |
| `GET /admin/users`, `GET /partials/admin/users` | Admin-only user management |

Anyone with filesystem or shell access to the NAS can of course read
`/data/dashboard.db` directly, bypassing all of the above. That is the
customer's own infrastructure and their own access control problem, but a DPO
should know it.

## What can be turned off

| Want to disable | How | Effect |
|---|---|---|
| **All reporting** | Leave `dashboard_url` blank in `~/.ccsync/config.toml` | `DashboardReporter.enabled` is false, `start()` is a no-op and the thread is never created (`reporter.py:enabled`, `reporter.py:start`). **But**: no reports also means no managed sync selections and no upgrades (`installer/windows_upgrade.ps1:264`), so in practice this disables the product, not the telemetry. |
| Reporting under an unverified name | `require_login = true` | `post_once` returns without making any request until the editor signs in (`reporter.py:post_once`). |
| Specific Resolve projects | Add the name to `ignored_resolve_projects` (`config.py:524`, default `["Untitled Project", "New Doc"]`) | That project's name is never reported and its `media_tree` is never cached or sent (`app.py:_refresh_media_tree_once`); the dashboard drops it again server-side (`api.is_ignored_resolve_project`). This is a per-project opt-out, not a per-person one. |
| Reporting *less often* | Raise `dashboard_report_interval` and `dashboard_report_interval_active` | Fewer ticks. Must be positive (`config.validate_config`). |

**Everything else cannot be turned off.** There is **no** configuration key
that disables `resolve_project` reporting, `local_manifest` reporting, or
`media_tree` reporting while leaving the sync lanes working. Verified by
reading `config.py`'s `DEFAULTS` and the `DashboardReporter` construction at
`app.py:949-976`: every getter is wired unconditionally except
`get_queue_info`, which is gated on managed mode.

**TODO(engineering) — required before sale.** Add three config switches, each
defaulting to the current behaviour so no fleet changes underfoot, and each
surfaced in the onboarding wizard rather than buried in a TOML file:

- `report_resolve_project` (bool) — send the open project name or not;
- `report_local_manifest` (bool) — send the per-file disk manifest or not;
- `report_media_tree` (bool) — send the media-pool bin tree or not.

A customer whose works council refuses the monitoring has, today, no option
except turning the whole product off.

## Employee monitoring — for the customer's DPO

Read this part twice.

CC Sync continuously records, per named employee:

- **which project they are working on right now**, updated as often as every
  5 seconds;
- **when they start and stop** — `reported_at` and `lanes[].last_sync` make
  presence and idleness trivially derivable, whether or not anyone intends to
  derive them;
- **what is on their workstation's disk**, file by file, with sizes;
- **how they have organised their own work** — the Resolve bin tree;
- **how fast their connection is** and how much data they move.

This is systematic monitoring of workers' activity. Plainly:

1. **You are the data controller.** The dashboard runs on your hardware, your
   admins read it, and you decide who is in `DASH_ADMIN_USERS`. Cablewrap
   Creative receives none of it (see `docs/legal/PRIVACY.md`).
2. **"Legitimate interests" is the realistic lawful basis, and consent is
   not.** Consent from an employee to their employer is rarely freely given
   (EDPB Guidelines 05/2020; WP29 Opinion 2/2017 on data processing at work).
   Do the balancing test and write it down.
3. **You almost certainly need a DPIA.** Art. 35(3)(b) GDPR, and "systematic
   monitoring of employees" appears on essentially every supervisory
   authority's mandatory-DPIA list.
4. **Works councils.** In Germany a system capable of monitoring employee
   performance or behaviour requires the works council's agreement *before*
   rollout (BetrVG §87(1) No. 6) — and courts read "capable of" broadly, so it
   applies even if you never look. Comparable duties exist in AT, NL, FR, and
   the Nordics. **This must be settled before deployment, not after.**
5. **Tell people.** Arts. 13–14 GDPR. `docs/legal/PRIVACY.md` is written to be
   adaptable into a staff-facing notice; the table at the top of this document
   is the part employees are entitled to see.
6. **Data minimisation (Art. 5(1)(c)) is the weak point.** `resolve_project`,
   `local_manifest` and `media_tree` exist to make *sync* debuggable, not to
   measure people — but they cannot currently be switched off, and "we
   collected it because the vendor gave us no way not to" is not a defence
   available to a controller. Track the three TODOs above.
7. **Purpose limitation.** Decide, in writing, that this data is used for
   diagnosing sync problems and not for performance management — and enforce
   it, because a supervisory authority will ask, and every admin can see the
   fleet grid.

**Not a defence, but relevant to proportionality:** the data never leaves the
customer's own infrastructure, retention is bounded once a person stops
reporting, and non-admin editors can see only themselves.

## Open items

- **TODO(engineering):** the three opt-out switches above.
- **TODO(engineering):** an admin action to purge one editor's telemetry
  (Art. 17), and one to export it (Art. 15/20). Neither exists.
- **TODO(engineering):** refuse non-loopback `http://` dashboard URLs.
- **TODO(engineering):** alarm when the prune cycle has not run.
- **TODO(legal):** confirm the "customer is controller, Licensor is not a
  processor for telemetry" analysis in `docs/legal/PRIVACY.md`, since it is
  what keeps this document's exposure with the customer rather than with us.
- **NOT VERIFIED:** whether the deployed dashboard's HTTP access logs record
  anything beyond method and path. Not read for this document; a DPO should
  ask, because access logs are a second, undocumented copy.
