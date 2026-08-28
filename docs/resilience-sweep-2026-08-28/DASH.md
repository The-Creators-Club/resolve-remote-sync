# Dashboard core (DASH)

## Summary
This is the most defensively-written area of the repo: the migration runner is
replayable statement-by-statement (`db.py:944-987`), the collector has a
watchdog that exits 75 rather than serve a dead thread (`app.py:392-296`), the
enforce cycle carries three separate B16 guards plus a blast-radius brake, and
almost every dangerous path has a dated comment explaining the incident that
produced it. The remaining risk is therefore not "no guards" but **guards whose
alarm goes only to the container log** and **write orders that are not
journalled**. The biggest single risk I found is the server-side file move
(`api.py:1986-2014`): it renames on the NAS and only then records the move, and
a failure inside the proxy-sibling loop returns a 503 whose message ("leave the
file where it was") is provably untrue - the tree is half-moved and no machine
is told. The two cheapest high-value wins are (a) persist and surface the
enforce blast-radius brake instead of logging it, and (b) accept a *previous*
`DASH_SESSION_SECRET`, because rotating that one env var 401s every companion
report in the fleet until each editor clicks "Sign in" at their own tray.

## Findings

### DASH-1: the server-side file move renames first and records second, and its 503 message is wrong
- **Lens:** pitfall
- **Where:** `dashboard/src/ccsync_dashboard/api.py:1986-2014`, `api.py:1930-1951` (`_move_proxy_siblings`), `docs/FILE_MOVES.md`
- **Scenario:** an admin uses [ MOVE ON THE SERVER AND ON EVERY MACHINE ] on a
  card dump mis-filed into the wrong project. `src.rename(dest)` succeeds. Then
  one proxy in `Proxy/` is held open by a Resolve on a wired rig, or the
  destination `Proxy/` dir cannot be created, and `candidate.rename(target)`
  raises `OSError`. Alternatively the rename succeeds and the container is
  restarted (or `/data` is full) before `conn.commit()` at `api.py:2019`.
- **Today:** the `try` at `api.py:1987` wraps `mkdir`, `src.rename` **and**
  `_move_proxy_siblings`, so any OSError from the proxy loop 503s with
  `"the server could not move it"` and the comment above it claims "all of them
  leave the file where it was, which is the safe outcome". The original has
  already moved and some proxies with it. No `file_moves` row is written, so no
  machine is ever told - which is exactly the FILE_MOVES failure mode (lane A
  never deletes, every holder re-uploads the old path) that this feature exists
  to end, now with the original *also* gone from where the editors' Resolve
  projects point.
- **Proposed:** two-phase. Write the `file_moves` row with `state='pending'`
  and commit **before** `src.rename`; flip it to `done` after. On boot (and in
  a collector cycle) reconcile `state='pending'` rows by stat-ing both paths:
  if only the destination exists, complete the record and fan the commands out;
  if both exist, quarantine and raise an admin banner. Move
  `_move_proxy_siblings` out of the fatal try so a proxy failure returns
  `207`-style partial success naming exactly which proxies did not move, and
  never claims nothing happened.
- **Effort:** M   **Severity:** high   **Confidence:** high
- **Related:** `docs/FILE_MOVES.md`, schema v29, the undo-journal pattern in
  `companion/resolve_bridge`.

### DASH-2: rotating (or losing) DASH_SESSION_SECRET 401s every companion in the fleet
- **Lens:** pitfall
- **Where:** `api.py:5238-5259` (identity required whenever `settings.session_secret` is set), `auth.py:376-380`, `auth.py:310-326`, `secrets_boot.py:11-20`
- **Scenario:** the owner rotates `DASH_SESSION_SECRET` (secrets_boot's
  docstring explicitly says "rotating one by setting the env var stays
  possible"), or restores `/data` from a snapshot taken before
  `<data>/secrets/dash_session_secret` was generated, or moves the container to
  a host whose `.env` was regenerated.
- **Today:** `X-CCSync-Identity` is an HMAC over the same secret and never
  expires (`IDENTITY_TTL_SECONDS` = 100 years). After the rotation every
  companion's stored identity token fails `read_identity_token`, so
  `POST /api/v1/report` 401s for the entire fleet. The dashboard's fleet grid
  goes blank/stale, the halt / pushed-update / lane-B-resume / file-move command
  channel dies, and the only cure is each editor clicking "Sign in…" in their
  own tray - the "restart everything in order" class of failure, fleet-wide,
  with no message anywhere saying why.
- **Proposed:** `DASH_SESSION_SECRET_PREVIOUS` (comma-separated, accept-only)
  consulted by `_read_token` for both purposes; a boot log and an admin banner
  counting machines whose last accepted identity was signed with a retired key,
  so the operator can see the rotation drain. Separately: when a report is
  refused *only* because the identity is unverifiable, still record
  `machines.last_seen` + a `report_refused_reason` so the grid says "this
  computer is trying to report and being refused: sign in on its tray" instead
  of showing nothing.
- **Effort:** M   **Severity:** high   **Confidence:** high
- **Related:** CR-86 (identity tokens made non-expiring), `docs/SECRETS.md`.

### DASH-3: the enforce blast-radius brake fires into the container log and nowhere else
- **Lens:** safeguard (existing guard with a hole)
- **Where:** `collector.py:1151-1180`, `settings.py:427`, `settings.py:647`; not referenced by `api_health` (`api.py:918-988`) or any template
- **Scenario:** Syncthing is restarted with a re-created config (the
  "regenerated device ID" incident), or four editors' devices are not yet
  approved. The next enforce cycle computes >3 share removals and refuses them
  all.
- **Today:** `log.error("REFUSING %d share removal(s)…")` and nothing else.
  `_timed` records the cycle as **ok** (the function returned normally), so
  `poll_runs`, `/api/v1/health` and the health panel all say enforce is fine.
  Meanwhile every genuine untick made since is silently not being applied -
  including an admin unticking a project to stop an editor filling their drive.
  The state is per-cycle and in-memory; a container restart loses even the log.
- **Proposed:** persist the refusal (a `meta` key or a `poll_runs` note:
  timestamp, count, the device/folder pairs), return it from `/api/v1/health`,
  and render a red fleet banner "N share removals refused - shares are FROZEN.
  Approve pending devices, or raise DASH_ENFORCE_MAX_REMOVALS". Add a "dry run"
  view on the admin page that shows the pending `+`/`-` diff enforce would
  apply, so the admin can see what is being held back before overriding.
- **Effort:** S   **Severity:** high   **Confidence:** high
- **Related:** KNOWN_BUGS B16; the brake itself (correctly counting share
  removals rather than devices).

### DASH-4: an empty Syncthing folder list deactivates every project - no brake, unlike enforce
- **Lens:** pitfall
- **Where:** `collector.py:874-931` (`_run_config`), `db.py:1430-1450` (`deactivate_missing_projects`), `db.py:3476-3483` (`purge_nas_media_for_inactive`), `db.py:3471`
- **Scenario:** Syncthing on the NAS comes back with a default/empty config -
  a re-created config dir, a restore, an upgrade that failed to load
  `config.xml`. `/rest/config` answers **200 with zero folders**; `myID` is
  present, so the empty-myID guards above do not fire.
- **Today:** `seen = []`, and 15 minutes later `deactivate_missing_projects`
  flips **every** project `active=0`. Then the hourly prune's
  `purge_nas_media_for_inactive` deletes the entire `nas_media` and
  `nas_inventory_state` content. Consequences, all silent: the project list and
  fleet grid empty out, `fetch_sync_backlog` (which joins `p.active = 1`)
  returns nothing so nobody appears behind, and `api_tick` answers
  `404 unknown or inactive project` so an admin cannot even re-tick. It does
  self-heal when the folders return (`upsert_project` sets `active=1`), but the
  NAS inventory must be fully re-walked and in the meantime the dashboard is
  lying about the one thing it exists to tell people.
- **Proposed:** the same brake enforce already has, one function up: refuse a
  deactivation pass that would deactivate more than `max(2, 25%)` of active
  projects, log/persist it and raise a banner ("Syncthing reported 0 of 37
  folders - not deactivating anything"). Cheaper still: skip deactivation
  entirely when `seen` is empty and the DB has active projects, since that is
  never a legitimate steady state.
- **Effort:** S   **Severity:** high   **Confidence:** high
- **Related:** DASH-7 (empty myID), the "stuck lane C = regenerated device ID"
  incident, `docs/BACKUP_RESTORE.md`.

### DASH-5: an unmounted / transiently-empty project dir wipes that project's NAS inventory
- **Lens:** pitfall
- **Where:** `collector.py:1229-1248`, `db.py:3513-3546` (`replace_nas_media`)
- **Scenario:** the ZFS dataset under `/projects/<project>` is not mounted when
  the container starts (pool import ordering after a NAS reboot), or a project
  is being renamed by hand on the NAS while the inventory cycle runs. The
  parent `/projects` exists (the bind mount point), so the
  `projects_dir.is_dir()` guard at `collector.py:1211` passes; the project dir
  itself exists but is empty.
- **Today:** `_dir_signature` differs from the stored one, `_walk_media_files`
  returns `[]`, and `replace_nas_media` does an unconditional
  `DELETE FROM nas_media WHERE project_id=?` followed by zero inserts, then
  writes the rollup as 0 originals / 0 proxies with `last_error=NULL`. Every
  media-presence view says the NAS holds nothing; `fetch_sync_backlog` then
  reports every original an editor holds as "the NAS is missing this", i.e. the
  page tells the owner his footage is not on the server. There is no floor and
  no "this looks wrong" check.
- **Proposed:** in `replace_nas_media`, refuse a walk that takes a project from
  `n_originals > 0` to `0` (or drops more than ~90% of files) unless a
  `force` flag is passed: keep the previous inventory, set
  `nas_inventory_state.last_error = "walk returned 0 of N files - not
  replacing"`, and surface that on the project page. Add a boot/cycle canary:
  `Projects/` containing zero entries, or a project dir with no `.stfolder`,
  reads as "not mounted", not as "empty".
- **Effort:** S   **Severity:** high   **Confidence:** high
- **Related:** the "eight tables grow without bound" retention work; DASH-4.

### DASH-6: approving a device with an owner the registry contradicts is not questioned
- **Lens:** user-error
- **Where:** `api.py:3757-3788`, `api.py:2863-2881` (`_pending_owner_hint`), `api.py:2845` (`approve_username_error`)
- **Scenario:** two editors' laptops go pending at once. The admin types (or
  picks from the datalist) `leso` on the row that the registry already knows is
  `ruskin`'s machine - the companion self-reported
  `machines.syncthing_device_id` before the admin ever opened the page.
- **Today:** CR-91 added `suggested_owner`/`suggested_machine`, but they are
  **display only**. `api_admin_approve_device` validates the device-id shape and
  that the username is an editor the dashboard knows, and nothing else. The
  device is named `leso` in Syncthing, `record_known_editor(leso)` fires, and
  the next enforce cycle shares **leso's** entire project plan with ruskin's
  laptop. Nothing detects the contradiction; unwinding it means an admin
  noticing folders appearing on the wrong machine.
- **Proposed:** when `_pending_owner_hint` returns a non-empty
  `suggested_owner` that differs from the submitted username, refuse with 409
  unless `confirm_owner=1`, and spell the consequence: "this computer
  (`DESKTOP-X`) has been reporting as ruskin's since <date>. Approving it as
  leso will share leso's 6 projects with it and none of ruskin's." Same check on
  the htmx form path.
- **Effort:** S   **Severity:** med   **Confidence:** high
- **Related:** CR-91, `dash-admin-6`/`comp-lane-c-1` (unapproved-device warning).

### DASH-7: nothing on this dashboard measures free space where its own database lives
- **Lens:** pitfall
- **Where:** `settings.py:47`/`543` (`db_path` default `/data/dashboard.db`), `settings.py:500` (packages default to `<db dir>/packages`), `db.py:3421-3474` (prune), `app.py:110-121` (`MAX_PACKAGE_BODY_BYTES` = 200 MB)
- **Scenario:** `/data` fills - a run of published packages, a code-bundle
  history from `dashboard_update`, crash-report json-lines, or simply the DB
  and its WAL growing on a small appliance dataset.
- **Today:** `shutil.disk_usage` appears only in `dashboard_update.py:408` and
  `setup_engine.py:541/574` (the setup wizard and the self-update). Nothing
  checks the dataset the SQLite DB is on. When it fills, every write - the
  report upsert included - raises `sqlite3.OperationalError: disk I/O error`;
  the collector's `_timed` catches it and records a failed poll, but
  `/api/v1/health` still answers `ok: true` as long as Syncthing is reachable
  and the thread is alive, so the container healthcheck is green while the
  fleet's status is frozen. Prune only ever DELETEs; there is no
  `wal_checkpoint(TRUNCATE)` and no `VACUUM` anywhere in the tree, so freed
  pages are never returned and the WAL is never truncated on demand.
- **Proposed:** the prune cycle records `shutil.disk_usage(dirname(db_path))`
  into `meta`; `/api/v1/health` gains `data_free_bytes` and `ok` goes false
  below a hard floor; the fleet page shows an amber banner below ~2 GB and a
  red one below ~500 MB. `api_publish_package` refuses when free space is less
  than 3x the declared body. After prune, run
  `PRAGMA wal_checkpoint(TRUNCATE)` and an occasional `VACUUM` (or enable
  `auto_vacuum=INCREMENTAL` for new DBs).
- **Effort:** S/M   **Severity:** high   **Confidence:** high
- **Related:** `MAX_PACKAGE_BODY_BYTES`'s own comment ("a filled dataset takes
  the SQLite DB down with it") - the ceiling exists, the measurement does not.

### DASH-8: a tick or untick leaves no record of who did it, and no undo
- **Lens:** user-error
- **Where:** `api.py:1822-1836` (`api_untick`), `db.py:2373-2403` (`remove_selection`), schema v24 `selections`
- **Scenario:** an admin on the fleet grid unticks a project on the wrong row
  (the person-level control removes it from **every** computer, deliberately),
  or unticks with no `?machine=` from a stale page.
- **Today:** the row is `DELETE`d. `selections` keeps `created_by`/`created_at`
  for an add, but a removal writes nothing anywhere - no history table, no log
  line, no audit. Within one enforce cycle the folder is unshared from every one
  of that person's machines and the editor's companion stops syncing that
  project. There is no page that answers "who stopped this syncing, and when",
  and no way to put it back except remembering what was there.
- **Proposed:** an append-only `selection_events(editor, machine, slug, action,
  mode, by_user, at)` written by `add_selection`/`remove_selection`; a
  "recent plan changes" panel on the fleet page with a one-click UNDO for the
  last hour; and a confirm on the person-level untick that names the machines
  it will affect ("this removes 2025/FF4 from ruskin's 2 computers").
- **Effort:** S   **Severity:** med   **Confidence:** high
- **Related:** `dash-core-1` (bucket materialisation on untick), CR-28.

### DASH-9: a file-move command that expires unapplied is silent, and the file comes back
- **Lens:** pitfall
- **Where:** `db.py` `pending_file_moves` (bounded by `FILE_MOVE_MAX_AGE_DAYS`/`FILE_MOVE_COMMAND_LIMIT`), `api.py:5578-5596`
- **Scenario:** an editor's laptop is away for the trip; the move was made three
  weeks ago. Or the companion applies the move and reports `ok: false` once,
  then the row ages past the cutoff.
- **Today:** the command simply stops being offered. `file_move_targets` keeps
  `applied_at IS NULL` forever and nothing looks at it. When the machine comes
  back, lane A - which never deletes - re-uploads the file to the **old** path,
  recreating exactly the duplicate the move existed to remove, and no page says
  a move was never completed.
- **Proposed:** a "moves awaiting machines" panel (the data is already in
  `file_move_targets`) with an age-based amber/red chip; an explicit
  `expired` state written when a target ages out, with a fleet banner naming
  the machine; and, on the next report from a machine holding an expired move,
  a one-click re-issue rather than silence.
- **Effort:** S   **Severity:** med   **Confidence:** high
- **Related:** `docs/FILE_MOVES.md`, DASH-1.

### DASH-10: a mis-set numeric or whitespace-padded secret in the environment is accepted silently
- **Lens:** user-error
- **Where:** `settings.py:509-560` (`num()` at 512, `report_token=env.get(...)` at 545), `auth.py:628-643`, `api.py:5198` (`request.headers.get("x-ccsync-token", "")` - never stripped)
- **Scenario:** the owner edits the NAS `.env` by hand and writes
  `DASH_REPORT_TOKEN="abc…"` (with quotes), or pastes a token with a trailing
  space, or sets `DASH_ENFORCE_MAX_REMOVALS=10 ` / `="10"`.
- **Today:** `num()` swallows the `ValueError` and returns the default with no
  log at all - so a deliberately raised removal limit stays 3 and the admin
  believes he overrode it. Secrets are stored unstripped and unquoted;
  `check_boot_secrets` only measures length, so `"abc…"` passes the floor and
  then mismatches every companion's token: the entire fleet 401s on report with
  a boot log that says the configuration is fine. `app.py:_watchdog_intervals`
  already does the right thing (`log.warning("%s=%r is not a number…")`) - the
  same treatment is simply missing one file over.
- **Proposed:** `num()` logs a WARNING naming the key and the raw value (as
  `%r`) whenever it falls back; secrets are `.strip()`ed and, when they arrive
  wrapped in matching quotes, refused at boot with "DASH_REPORT_TOKEN looks
  quoted - remove the quotes from .env"; the incoming `x-ccsync-token` and
  `x-ccsync-identity` headers are stripped before comparison.
- **Effort:** S   **Severity:** med   **Confidence:** high

### DASH-11: two live computers sharing one Syncthing device id ping-pong the registry every report
- **Lens:** pitfall
- **Where:** `api.py:4513-4563` (`_register_machine`), `db.py` `release_device_id_elsewhere`, `db.py` `adopt_renamed_machine`, `collector.py:1058-1064` (`machine_devices`)
- **Scenario:** a studio clones the base rig's disk to a second box (a normal
  thing to do), so both carry the same `~/.ccsync/machine.json` **and** the same
  Syncthing config. Both report every 30 s.
- **Today:** `adopt_renamed_machine` correctly refuses (the name is taken) and
  logs; then `release_device_id_elsewhere` moves the device id onto whichever
  machine reported **last**, every single report. The enforce cycle therefore
  sees the device belonging to a different `(editor, machine)` pair each cycle,
  computes a different `desired` set, and issues `put_folder` on the affected
  folders every 60 s - each of which restarts the folder in Syncthing, so lane C
  never settles. The only signal is a `log.warning` per report. Cross-**editor**
  clones are covered by `release_device_id_elsewhere` (it is not scoped to the
  editor), but a duplicate `machine_id` across two editors is not detected at
  all: `machine_by_machine_id` is per editor.
- **Proposed:** count device-id reclaims per `(device_id)` in a small `meta`
  counter; more than N flips in an hour records a persistent "two computers are
  claiming Syncthing device X / machine_id Y" alarm on the fleet page, and
  enforce freezes that device's shares (leaves them as they are) until an admin
  resolves it. Point the message at the fix: regenerate `machine.json` and the
  Syncthing identity on the clone.
- **Effort:** M   **Severity:** med   **Confidence:** high
- **Related:** `data-model-5` (2026-08-21), `ultrareview 2026-08-19`.

### DASH-12: /api/v1/health cannot say "my database is unwritable" or "the tree is not mounted"
- **Lens:** safeguard
- **Where:** `api.py:918-988`, `deploy/compose.yaml` healthcheck (reads `ok`)
- **Scenario:** the pool is not mounted, or `/data` is read-only (a ZFS
  quota/full dataset, a bind mount that lost its target after a host reboot).
- **Today:** `ok` = "Syncthing reachable (or not configured) AND the collector
  thread is alive". Both can be true while every write fails and `/projects` is
  an empty directory. The container healthcheck stays green, `ship.ps1`'s
  post-deploy poll passes, and the first person to notice is an editor asking
  why their name has vanished from the grid.
- **Proposed:** add two cheap self-tests to the authenticated body **and** to
  `ok`: a write canary (`INSERT OR REPLACE INTO meta('health_canary', now)` in
  its own try) and a mount canary (`projects_dir` exists, is non-empty, and at
  least one active project's directory resolves). Keep them cached for ~30 s so
  the probe cost stays flat. Note `health.py` is deliberately pure - these
  belong in `api_health`/the collector, not in `health.py`.
- **Effort:** S   **Severity:** med   **Confidence:** high
- **Related:** DASH-2 (ops-efficiency-6) collector watchdog; CR-67's note that
  `health.py` must stay I/O-free.

### DASH-13: `foreign_keys=ON` plus table-rebuild migrations is a latent half-migration
- **Lens:** pitfall
- **Where:** `db.py:605-614` (`connect` sets `PRAGMA foreign_keys=ON`), `db.py:944-987` (`migrate` runs inside `BEGIN`), v11 and v24 rebuild tables with `DROP TABLE` + `RENAME`
- **Scenario:** a future migration rebuilds a table that another table
  references (`completion_current`/`missing_files` reference `projects(id)`), the
  way v11 and v24 rebuilt `companion_packages` and `selections`.
- **Today:** the runner is genuinely good - explicit transaction, per-statement
  replay, `ADD COLUMN` idempotency, and a refusal when `user_version` is ahead
  of the build. But `foreign_keys` is left ON during the rebuild and
  `legacy_alter_table` is not set, so a `DROP`+`RENAME` on a referenced table
  can either fail mid-step or silently rewrite the referencing tables' FK
  clauses. There is also no post-migration `PRAGMA foreign_key_check` and no
  backup of the DB file before a migration that rebuilds a table.
- **Proposed:** in `migrate`, wrap each step with `PRAGMA foreign_keys=OFF` /
  restore-after (SQLite's own documented recipe), run
  `PRAGMA foreign_key_check` before the `user_version` bump and roll the step
  back if it reports anything, and copy `dashboard.db` to
  `dashboard.db.pre-v<N>` (once, best-effort, subject to the free-space check
  from DASH-7) before the first rebuild step of a boot. That gives the
  non-technical owner a file to hand back, not a shell recipe.
- **Effort:** S   **Severity:** med   **Confidence:** med

### DASH-14: an enforce cycle that early-returns or refuses is recorded as a successful poll
- **Lens:** pitfall
- **Where:** `collector.py:353-370` (`_timed`), `collector.py:946-952` (empty-myID early return), `collector.py:1164-1174` (removal refusal), `collector.py:1008-1013` (seed not marked done)
- **Scenario:** Syncthing answers with an empty `myID` for ten minutes during a
  restart, so `_run_enforce` returns immediately every cycle.
- **Today:** `_timed` records `ok=True` because nothing raised. `poll_runs`,
  `/api/v1/health`'s `last_polls`, and the health panel all say enforce last ran
  successfully N seconds ago. Three distinct "I did nothing" outcomes are
  indistinguishable from "I reconciled everything".
- **Proposed:** `_run_enforce` (and the other runners) already may return a
  **note** string that `_timed` stores - use it: `"skipped: empty myID"`,
  `"refused 12 removals"`, `"seed deferred"`. Render the note beside each kind in
  the health panel, and colour a kind amber when its last note is non-empty.
  Nearly free, and it turns three silent states into visible ones.
- **Effort:** S   **Severity:** med   **Confidence:** high
- **Related:** ops-efficiency-5 (which added the note mechanism for completion).

### DASH-15: `_walk_media_files` is the one uncapped collection in the media tables
- **Lens:** pitfall
- **Where:** `collector.py:1276-1294`, `db.py:26-30` (`EDITOR_MEDIA_CAP`=2000, `MEDIA_TREE_CAP`=4000 - no NAS equivalent)
- **Scenario:** someone drops a DCIM card with 90k stills, or a back-catalogue
  ingest lands 250k files into one project on the NAS.
- **Today:** the walk builds an unbounded Python list, then
  `replace_nas_media` deletes and re-inserts every row in one statement inside
  the collector's connection. Every editor-side manifest is capped; the NAS
  side is not. On the single-worker container this is a long write transaction
  and a large memory spike, and it is exactly the shape that produced
  "database is locked" on editors' `POST /api/v1/report` before (the docstring
  at `collector.py:1206-1208` records that lesson for the *walk*, not for the
  *write*).
- **Proposed:** a `NAS_MEDIA_CAP` mirroring `EDITOR_MEDIA_CAP`, with a
  `truncated` flag on `nas_inventory_state` surfaced on the project page (the
  rollup counts can stay exact - they only need a running total, not the rows);
  and insert in chunks with an interleaved commit so the write burst is
  bounded.
- **Effort:** S   **Severity:** med   **Confidence:** med
- **Related:** B6 (truncation is never silent) - the same posture applied to
  the NAS side.

### DASH-16: a machine that dies is pruned out of the fleet rather than marked lost
- **Lens:** user-error / safeguard
- **Where:** `db.py:579` (`MACHINE_STATE_MAX_AGE_DAYS`=30), `db.py:3448-3453`, `db.py:26-29` (`MEDIA_REPORT_MAX_AGE_DAYS`=14), `templates/partials/fleet_grid.html:116`
- **Scenario:** an editor's PC dies, or an editor leaves and takes the laptop.
  Nobody tells the owner.
- **Today:** the grid does the right thing for a day (`received_at | ago` plus
  a red lane chip after 15 minutes - `health.py:105-107`). At 14 days its media
  presence disappears; at 30 days its `machine_state` row is deleted and the
  computer quietly leaves the grid, while its `machines` registry row, its
  `selections` plan and its Syncthing share all remain. The fleet looks
  healthier than it is, and a Syncthing device that still holds project data is
  shared with nothing watching it.
- **Proposed:** keep the registry row as the anchor (it already survives) and
  render a `LOST` row for any `machines.last_seen` older than N days, with the
  plan it still holds and two buttons: [ FORGET THIS COMPUTER ]
  (`api_forget_machine`, which already does the full job) or [ KEEP ]. Never
  let a machine vanish from the page just because a status table aged out.
- **Effort:** S   **Severity:** med   **Confidence:** high
- **Related:** CR-76 (delete-a-user / forget-a-computer).

### DASH-17: report ingest has no per-machine rate limit or clock-skew handling
- **Lens:** pitfall
- **Where:** `api.py:5195-5601`, `db.py` `evict_extra_machines`, `db.py:592-602` (`utcnow_iso`, all server-clock)
- **Scenario:** a companion enters a fast-retry loop (a bug, or a machine
  waking from sleep with a backlog) and posts a full report several times a
  second; or an editor's laptop has its clock two days ahead after a battery
  change.
- **Today:** the body size is capped (`app.py:_BODY_LIMITS`) and every field is
  individually capped, and every freshness decision correctly uses
  `received_at` (server clock) - so skew is largely handled. But the route
  itself is unthrottled: each call does ~10 writes plus up to two extra
  commits, on the single worker whose SQLite the collector is also writing.
  `payload.reported_at` is stored unvalidated and shown to admins, so a skewed
  machine displays a nonsense "reported at" beside a correct "received".
- **Proposed:** a cheap per-`(editor, machine)` token bucket in `meta` (or
  in-process, since there is one worker by construction) that 429s more than
  ~6 reports/minute with `Retry-After`, and logs once per machine; and clamp
  `reported_at` to a sane window of `received_at`, recording a
  `clock_skew_seconds` on `machine_state` so the grid can chip a machine whose
  clock is wrong (skew is a real cause of confusing lane timestamps in the
  companion logs).
- **Effort:** S   **Severity:** low/med   **Confidence:** med
- **Related:** SEC-4 (runaway lane count), the existing write-time
  `evict_extra_machines` cap.

### DASH-18: the collector's first cycle can hold a write transaction across Syncthing HTTP calls
- **Lens:** pitfall
- **Where:** `collector.py:1003-1013` (the seed commits before the HTTP loop - the fix), `collector.py:1176-1191` (`get_folder`/`put_folder` loop), `_timed`'s `conn.commit()` at `collector.py:368`
- **Scenario:** the enforce pass reaches the `put_folder` loop with pending
  writes from `_refresh_shared_folders` or `record_known_editor` earlier in the
  same cycle, and Syncthing takes its per-call timeout on each of 40 folders.
- **Today:** the seed path was explicitly fixed to commit first (with the
  comment naming the "database is locked" 500s it caused), but the general case
  is not enforced: any write made earlier in the cycle stays in an open
  transaction across the whole `get_folder`/`put_folder` loop, and editors'
  reports contend on a 5 s `busy_timeout`.
- **Proposed:** make it structural rather than remembered: `_run_enforce`
  starts with `conn.commit()` and asserts `not conn.in_transaction` immediately
  before the HTTP loop (raise in tests, log in production), and give the
  collector a **second, read-only connection** for the config/status reads so
  the writer connection is only ever open for the short write burst - the same
  split `_run_inventory`'s two-phase design already uses.
- **Effort:** M   **Severity:** low/med   **Confidence:** med

## Cross-cutting notes
- **Companion agent:** DASH-2 has a companion half - a companion whose identity
  token is refused should say so in the tray line ("the dashboard is refusing my
  identity: sign in") rather than showing a generic report error, and should
  keep retrying rather than backing off to nothing.
- **Companion agent:** the report reply's `commands.resume_lane_b` is
  deliberately one-shot and cleared as it goes out (`api.py:5540-5556`); if the
  HTTP response is lost in flight the admin's click is silently spent. Worth
  confirming the companion treats a *received* command idempotently by
  `requested_at`, which the dashboard already sends for that purpose.
- **Server/NAS agent:** DASH-4 and DASH-5 both hinge on "the pool is not
  mounted but the mount point exists". A marker file on the pool
  (`/projects/.ccsync-pool`) that the dashboard checks for would make both
  cases a one-line refusal instead of two separate heuristics.
- **Release agent:** `MAX_PACKAGE_BODY_BYTES` (200 MB) and the code-bundle
  history both write into the same dataset as `dashboard.db`; whatever retention
  the packages/bundles have should be counted against the DASH-7 free-space
  floor.
