# Dashboard core: API, db/schema, report ingest, enforce, auth/sessions, provisioning, collector

## Summary
The 08-28 sweep landed almost everywhere in this area: the report route now
stamps refusals and clock skew, the file move is two-phase and reconciled, both
blast-radius brakes persist and surface, plan changes are audited with a 60 s
enforce freeze and an [ UNDO ], and forty alert kinds carry a next action. What
is left is not missing guards but **guards that stop at the account boundary**
and **one write path that walked past the ledger everything else goes through**.
The biggest risk is that taking a person's access away does not take their
footage away: DISABLE revokes sessions and per-editor tokens but never touches
Syncthing, the identity token never expires, and the shared report token is
fleet-wide, so a disabled contractor's laptop keeps receiving projects
indefinitely and nothing anywhere says so. The cheapest high-value win is the
"copy from ..." dropdown on the assignments grid: one `change` event silently
`DELETE`s a computer's whole plan with no confirm, no audit row and no undo,
while the tick beside it has all three.

## Findings

### DCORE-1: disabling or deleting an editor does not stop their computer syncing
- **Lens:** both
- **Who:** admin / owner
- **Where:** `dashboard/src/ccsync_dashboard/api.py:3793-3860` (`api_admin_disable_user`),
  `api.py:3863-3892` (`_purge_user_credentials`), `api.py:129-151`
  (`resolve_companion_credential`), `auth.py:311-327` (`make_identity_token`,
  `IDENTITY_TTL_SECONDS = 100 years`), `settings.py:99`
  (`shared_report_token_enabled: bool = True`), `collector.py:1142-1435`
  (`_run_enforce`). Screen: Settings > Users > [ DISABLE ].
- **Today:** disable revokes browser sessions and every `cce1.` per-editor
  token. It does not remove that editor's Syncthing devices, does not remove
  their `selections`, and nothing in the report path or the enforce cycle ever
  reads `users.disabled` (`grep disabled collector.py db.py` finds only the
  column definition at `db.py:549`). So on any site still on the shared
  `DASH_REPORT_TOKEN` (the default, and the current fleet), a disabled editor's
  companion keeps posting `/api/v1/report` with its never-expiring identity
  token, `db.record_known_editor` re-registers them every 30 s, and every
  project ticked for them stays shared over lane C. The admin's answer is
  `{"ok": true, "purged": {"sessions_revoked": 1, "report_tokens_revoked": 0}}`
  and a row that says DISABLED.
- **Proposed:** (a) make the report path refuse an identity for an account that
  is disabled or absent, with the existing `stamp_report_refused` reason "this
  account has been disabled"; (b) have disable call `_remove_editor_devices`
  the way delete already does, or at minimum print the consequence in the
  confirm: "This stops <name> signing in. Their computers keep the projects
  they already have until you also remove their computers - [ FORGET
  COMPUTERS ]"; (c) add an invariant beside `plan_has_share`: "no disabled
  account still has a project shared with it", with the fix text naming the
  button. Today the Users page implies a revocation it does not perform.
- **Effort:** M   **Value:** critical   **Confidence:** high
- **Related:** dash-core-3 / trust-model-2 (what disable DOES revoke), CR-76
  (delete-a-user), CR-86 (non-expiring identity), 08-28 DASH-2.

### DCORE-2: "copy from ..." wipes a computer's plan with no confirm, no audit and no undo
- **Lens:** both
- **Who:** admin
- **Where:** `dashboard/static/assignments.js:265-292`, `api.py:4463-4504`
  (`api_copy_machine_plan`), `db.py:4740-4771` (`copy_machine_plan`),
  `api.py:2135-2159` (`audit_plan_change`), `db.py:5288-5330`
  (`recent_plan_change_devices`). Screen: Settings > Assignments, the
  "copy from ..." `<select>` in a machine column header.
- **Today:** the handler fires on `change` - a stray scroll over a focused
  select is enough - and does `DELETE FROM selections WHERE editor_username=?
  AND machine=?` before inserting the source's rows. There is no
  `confirmCapacity`-style dialog (contrast `assignments.js:139-146`, where a
  single tick asks), no `db.audit` call anywhere on this path, and therefore
  no row for `recent_plan_changes` / [ UNDO ] and no `frozen_devices` entry -
  so the next enforce cycle unshares the wiped projects **immediately**, with
  none of the 60 s grace an untick gets. The only feedback is
  `toast("copied 8 project(s) from FF-DESK to LESO-MBP")`, which never
  mentions that 14 projects were removed. A source with an empty plan copies
  nothing and silently empties the target.
- **Proposed:** confirm first, naming both sides ("Replace LESO-MBP's 14
  projects with FF-DESK's 8? LESO-MBP stops syncing 9 of them."); write a
  `plan.copy` audit row through `audit_plan_change`'s before/after shape so it
  appears in RECENT PLAN CHANGES with [ UNDO ]; feed its removals into
  `recent_plan_change_devices` so the undo window costs Syncthing nothing;
  refuse a copy from a source with zero rows with 409 "FF-DESK has no projects
  ticked - copying it would empty LESO-MBP".
- **Effort:** S   **Value:** high   **Confidence:** high
- **Related:** 08-28 DASH-8 (built for tick/untick only), SYS-11, dash-core-1.

### DCORE-3: a session secret that could not be written works until the next restart, then 401s the fleet
- **Lens:** resilience
- **Who:** owner / admin
- **Where:** `secrets_boot.py:207-215` (the `_write_secret_file` failure path),
  `secrets_boot.py:74-86`, `app.py:462-463` (`secrets_boot.ensure_secrets()` -
  return value discarded), `notices.py:620-649` (`check_settings` checks quoting
  and `dev_insecure`, not persistence).
- **Today:** if `<data>/secrets/` cannot be written - the exact case the
  docstring names, "this process does not own it yet", routine on a Synology
  volume or a restored dataset - `ensure_secrets` logs one warning
  ("it will be regenerated on the next boot unless the environment sets it")
  and carries on with an in-memory `DASH_SESSION_SECRET`. Everything works.
  The next `docker restart` mints a different one, and because the identity
  token is an HMAC over it and never expires, **every companion in the fleet
  401s at once and every browser session dies**. DASH-2's accept-only
  `DASH_SESSION_SECRET_PREVIOUS` cannot help: nobody knows the old value.
- **Proposed:** `create_app` keeps the provenance dict and, for any secret
  whose file does not exist after the call, writes a notice: kind
  `secret_not_saved`, severity error, body "The sign-in key could not be saved
  to the server's data folder. It works now, but every computer and every
  browser will be signed out the next time this server restarts.", fix "Fix the
  permissions on <data>/secrets on the NAS, then restart the dashboard." Add
  the same kind to `alerts.ALERT_KINDS` so it leaves the box. Cheap second
  belt: refuse to serve when `session_secret` provenance is `generated` AND the
  DB already holds machines (a fresh secret on a populated fleet is never
  right).
- **Effort:** S   **Value:** high   **Confidence:** high
- **Related:** 08-28 DASH-2 (rotation), `docs/SECRETS.md`, `insecure_secret`
  notice (the neighbouring check that WAS built).

### DCORE-4: on an SMB site there is no [ DISABLE ] at all, only DELETE
- **Lens:** usability
- **Who:** admin / owner
- **Where:** `api.py:3782-3790` (`_require_local_mode` -> 400 "this action is
  only available with DASH_AUTH_METHOD=local"), `api.py:3793` (disable),
  `ui.py:2084` (`/partials/admin/users/disable`). Screen: Settings > Users.
- **Today:** the shipped fleet runs `DASH_AUTH_METHOD=smb`, so the only
  "stop this person" control the Users page offers is DELETE, which removes
  the NAS account, forgets every computer, removes Syncthing devices and drops
  the plan. An owner who wants "pause the freelancer until next month" has
  either a destructive button or nothing.
- **Proposed:** a non-destructive [ SUSPEND ] that is auth-method independent
  because it acts on fleet state, not on the account: mark the editor
  suspended in `known_editors` (or a `suspended_at` column), have the report
  path refuse with a named reason, have the enforce cycle remove their shares,
  and show a SUSPENDED chip with [ RESUME ] that puts the plan back untouched.
  That is the button the owner actually reaches for, and it is the same
  mechanism DCORE-1 needs.
- **Effort:** M   **Value:** high   **Confidence:** high

### DCORE-5: any signed-in editor can create a project, and nothing can ever delete one
- **Lens:** usability
- **Who:** admin / editor
- **Where:** `api.py:3310-3327` (`api_create_project` - `auth.get_session_user`
  only), `api.py:3329-3342` (`api_link_folder`), `ui.py:788`
  (`/partials/project-setup/create`); no `DELETE /projects/{slug}` or archive
  route exists anywhere in `api.py` or `ui.py`.
- **Today:** the NEW PROJECT flow an editor reaches from their own tray popup
  creates real folders on the NAS tree and a `projects` row, with no audit
  entry (contrast every file move, which is admin-only and audited at
  `api.py:2521`). A typo makes a permanent project: it appears in every
  editor's tick list, in the assignments grid, and in the queue, and the only
  way to remove it is to delete the folder on the NAS by hand and wait up to
  15 minutes for `deactivate_missing_projects` - which the DASH-4 brake may
  itself refuse on a small site.
- **Proposed:** an [ ARCHIVE PROJECT ] admin action that sets `active=0`,
  removes its Syncthing shares and keeps the folder and the marker (reversible,
  no data touched), with a confirm naming how many editors currently sync it;
  and a `project.create` / `project.archive` audit row on both paths. If
  editor-side creation is intended to stay open, say so in the copy: today an
  editor cannot tell that their mistake is permanent.
- **Effort:** M   **Value:** high   **Confidence:** high

### DCORE-6: the fleet-membership gate is inert on exactly the deployment shape it ships on
- **Lens:** resilience
- **Who:** owner (second customer)
- **Where:** `api.py:1808-1832` (`_require_fleet_member`), `nas/factory.py:17-29`
  (`nas_configured`), `local_users.py:39` (`ROLES = ("admin", "editor")`),
  `api.py:1834-1900` (`api_verify`).
- **Today:** `_require_fleet_member` proves membership by asking the NAS whether
  the account is in the `editors` group. On a `DASH_AUTH_METHOD=local`
  appliance with no NAS credentials - the zero-touch shape
  (`docs/ZERO_TOUCH_PLAN.md` WP C) - `nas_configured` is False, so the whole
  check is skipped with `log.warning("minting an identity for %r without an
  editors-group check: DASH_NAS_PW is not configured on the dashboard")`. Local
  accounts carry a `role`, and nothing consults it: **any** local account,
  including one created for browsing the b-roll library, gets an identity token
  and the shared report token from `/api/v1/verify` and can write reports as
  itself. The log line also points the operator at `DASH_NAS_PW`, which is
  irrelevant on that site.
- **Proposed:** when `auth_method == "local"`, membership is `local_users.get_user
  (username) is not None and not disabled` - roles `admin` and `editor` both
  pass, anything else does not - and the skip-with-warning path is reserved for
  smb/oidc sites with no NAS credential. Reword that warning to name the
  actual configuration ("no membership backend for auth_method=%r").
- **Effort:** S   **Value:** high   **Confidence:** high

### DCORE-7: half the admin surface writes nothing to the fleet audit ledger
- **Lens:** usability
- **Who:** admin / owner
- **Where:** `db.audit` callers: `api.py:2155, 2521, 2631, 4018, 4068, 4535,
  5213, 5352, 5394, 5451, 7915`. Not called by: `api_set_fleet_halt`
  (`api.py:4296`), `api_admin_disable_user` (`3793`), `api_admin_set_password`
  (`3743`), `api_admin_create_report_token` (`4206`),
  `api_admin_revoke_report_token` (`4229`), `api_admin_revoke_sessions`
  (`4166`), `api_copy_machine_plan` (`4463`), `api_create_project` (`3310`),
  `api_link_folder` (`3329`), `api_push_machine_update` (`4345`). Screen:
  Settings > Audit.
- **Today:** the audit page answers "who ticked and who published" and is
  silent on "who halted the fleet at 3 am", "who reset that password", "who
  minted a fleet token", "who created this project". For a non-technical owner
  the page reads as a complete record, which is the failure mode an audit page
  has.
- **Proposed:** one `db.audit(conn, admin, "<verb>", subject, {...})` line per
  route above, before its existing `conn.commit()` (the docstring at
  `db.py:5044-5055` already specifies the ordering). Names: `fleet.halt`,
  `fleet.halt_release`, `user.disable`, `user.password`, `token.mint`,
  `token.revoke`, `session.revoke`, `plan.copy`, `project.create`,
  `machine.update_push`. No new table, no new page.
- **Effort:** S   **Value:** high   **Confidence:** high

### DCORE-8: a 429 on sign-in never says how long, and the wait is already computed
- **Lens:** usability
- **Who:** editor (at the tray) / admin
- **Where:** `api.py:1746-1748` (`/api/v1/login`), `api.py:1846-1848`
  (`/api/v1/verify`), `auth.py:234-240` (`login_throttled` returns SECONDS),
  `sessions.py:LOGIN_BACKOFF_BASE_SECONDS = 60.0` ... `MAX = 3600.0`.
- **Today:** both routes do `if auth.login_throttled(...)` and throw away the
  float, answering `detail="too many failed attempts; wait and retry"` with no
  `Retry-After` header. After six wrong passwords the wait doubles to as much
  as an hour, and an editor whose tray says "too many failed attempts; wait and
  retry" has no way to tell a one-minute lockout from a sixty-minute one - so
  they retry, which is the one thing that does not help.
- **Proposed:** `wait = auth.login_throttled(...)`, then
  `raise HTTPException(429, detail=f"too many failed sign-in attempts - try
  again in {humanise(wait)}", headers={"Retry-After": str(int(wait))})`, with
  `humanise` giving "2 minutes" / "about an hour". One line each, and the tray
  and the login page both already render `detail`.
- **Effort:** S   **Value:** med   **Confidence:** high

### DCORE-9: an expired session turns an admin's click into "login required" in a toast
- **Lens:** usability
- **Who:** admin
- **Where:** `app.py:1083-1088` (JSON 401 for `/api/` when unauthenticated),
  `static/assignments.js:105-120` and `:160-165` (`toast('could not update
  "leso": ' + err.message)`), `static/assignments.js:286-291`. Screen:
  Settings > Assignments.
- **Today:** htmx fragments handle expiry properly (`HX-Redirect`,
  `app.py:1096-1110`), but those polls only run while
  `document.visibilityState === 'visible'`. An admin who comes back to a tab
  that was in the background for 12 hours and starts ticking gets the checkbox
  flipped back and `could not update "leso": login required` - copy that reads
  as a permissions bug, not as "you were signed out". `setup.js:82` already
  special-cases 401/403; `assignments.js` does not.
- **Proposed:** in `writeCell`'s and the copy-plan handler's rejection path,
  `if (resp.status === 401) { location.href = "/login?next=" +
  encodeURIComponent(location.pathname + location.search); return; }` - the
  same `?next=` the gate already builds. Failing that, the toast should read
  "Your sign-in has expired. Reload the page and sign in again."
- **Effort:** S   **Value:** med   **Confidence:** high

### DCORE-10: `Settings.num()` swallows a bad number and the operator believes the override took
- **Lens:** resilience
- **Who:** owner / developer
- **Where:** `settings.py:635-640`; contrast `app.py:_watchdog_intervals`
  (`log.warning("%s=%r is not a number...")`) and the quoted-secret check that
  WAS built (`notices.py:620-649`).
- **Today:** `DASH_ENFORCE_MAX_REMOVALS="10"` (quoted), `= 10 ` with a stray
  character, or any typo returns the default 3 with no log line at all. The
  admin who deliberately raised the removal limit to clear a frozen enforce
  pass gets the brake refusing again, an `enforce_refusal` notice telling him
  to raise `DASH_ENFORCE_MAX_REMOVALS`, and no way to discover that he already
  did. Same silence for every interval, every session lifetime and
  `DASH_PORT`.
- **Proposed:** `except ValueError: log.warning("%s=%r is not a number - using
  %s", name, raw, default); return default`, plus a `check_settings` notice
  listing the keys that fell back, on the same page as `insecure_secret`. The
  quoted-secret half of 08-28 DASH-10 was built; this half was not.
- **Effort:** S   **Value:** med   **Confidence:** high

### DCORE-11: a device the companion reported but Syncthing has never seen is a log line only
- **Lens:** resilience
- **Who:** admin
- **Where:** `collector.py:1338-1358` (`_warned_unapproved_device`, a
  per-PROCESS set), `notices.py:401-428` (`_check_pending_devices`),
  `notices.py:47` (`PENDING_DEVICE_HOURS = 24`).
- **Today:** the notice that reaches the home page is driven by Syncthing's
  *pending* list, i.e. devices that have actually dialled in, and only after 24
  hours. The collector's own case is different and more common during
  onboarding: `machines.syncthing_device_id` is self-reported the moment the
  companion has a local Syncthing, and if that device has not yet reached the
  server (relay blocked, hotel wifi, discovery off) it is in neither the config
  nor the pending list. The enforce cycle then `continue`s past it every 60 s
  forever, logging once per container lifetime. The editor sees a plan with no
  data arriving and the fleet page shows nothing wrong.
- **Proposed:** raise the notice from the enforce cycle's own knowledge, not
  only from the pending list: kind `device_never_seen`, subject the device id,
  body "<editor>/<machine> has been waiting to join the sync network since
  <date>. None of its projects can reach it.", fix "Approve it under Settings,
  Users, DEVICES AWAITING APPROVAL. If it is not listed there, that computer
  has never reached this server - check its network." Clear it the cycle the
  device appears in `id_to_editor`. Drop the 24 h floor to ~2 h for a machine
  that has a plan (an editor waiting on their first sync is the case).
- **Effort:** S   **Value:** med   **Confidence:** high
- **Related:** dash-admin-6 / comp-lane-c-1, CR-91's `suggested_owner`.

### DCORE-12: eviction deletes a computer's registry row while leaving its plan and its share
- **Lens:** resilience
- **Who:** admin
- **Where:** `db.py:6291-6330` (`evict_extra_machines`), `db.py:585`
  (`MAX_MACHINES_PER_EDITOR = 20`), `api.py:2245-2252` (`api_tick`'s
  "has no computer named").
- **Today:** past 20 machines the oldest `machine_state` AND `machines` rows are
  deleted, with the comment noting the plan is deliberately kept. But a
  computer with no registry row has no `syncthing_device_id` the enforce cycle
  can address, so its plan falls back to the person-level share set, and
  `api_tick` answers 404 `"'leso' has no computer named 'LESO-MBP'"` for a
  machine that is still holding footage and still in Syncthing. No notice, no
  audit, no log line at all.
- **Proposed:** log the eviction at WARNING naming the machine; do not delete
  the `machines` row while a `selections` row or a Syncthing share for it
  exists - keep it and render it in the LOST state instead, which is the same
  state 08-28 DASH-16 asked for. Raise the cap warning rather than silently
  reshaping the fleet.
- **Effort:** S   **Value:** med   **Confidence:** med

### DCORE-13: a pushed update, a resume and an ask-why all answer `{"ok": true}` with no arrival estimate
- **Lens:** usability
- **Who:** admin
- **Where:** `api.py:4345-4382` (`api_push_machine_update`),
  `api.py:4410-4450` (`api_resume_machine_lane_b`), `api.py:7924-7942`
  (`api_admin_ask_why`). Screens: Settings > Packages, FLEET grid.
- **Today:** all three park a request that rides the machine's next report
  reply. The response says `{"ok": true, "version": "0.9.64"}`; the toast says
  the click landed. Nothing consults `machines.last_seen`, so an admin pushing
  an update to a laptop that has been off for nine days gets exactly the same
  confirmation as one pushing to a live machine, and then watches a queued row
  that will never move. `resume-lane-b` at least refuses when the last report
  shows no trip (409, good copy) - the other two refuse nothing.
- **Proposed:** include the machine's last-seen age in the answer and in the
  toast: "asked LESO-MBP to update to 0.9.64. It will apply on its next
  check-in - last heard from 9 days ago." Warn (not refuse) above ~1 day. The
  data is one query on a row these routes already read.
- **Effort:** S   **Value:** med   **Confidence:** high

### DCORE-14: revoking a fleet token does not say which computers it will stop
- **Lens:** usability
- **Who:** admin
- **Where:** `api.py:4229-4239` (`api_admin_revoke_report_token`),
  `api.py:4241-4256` (`build_report_tokens_view`), `db.touch_editor_report_token`
  (records last use). Screen: Settings > Users, token panel.
- **Today:** [ REVOKE ] answers `{"ok": true}` or `404 "no such live token"`.
  The view knows `shared_machines` for the migration counter but the per-token
  row does not say which machines last authenticated with THAT token, so an
  admin tidying up old tokens cannot tell a dead one from the one holding
  somebody's MacBook on the fleet. The consequence - that machine's reports
  401 within 30 s and its editor must be handed a new token by hand - is
  nowhere in the copy.
- **Proposed:** carry the machines that last used each token into the row, and
  confirm with them named: "Revoke this token? LESO-MBP is using it and will
  stop reporting within a minute. You will have to give <editor> a new token."
  Then the count in the answer, not just `ok`.
- **Effort:** S   **Value:** med   **Confidence:** high

### DCORE-15: report ingest is still unthrottled per machine
- **Lens:** resilience
- **Who:** developer / admin
- **Where:** `api.py:7179-7783` (`api_report`), `db.py:6291`
  (`evict_extra_machines` is the only bound), `db.py:656` (`busy_timeout=5000`).
- **Today:** the skew half of 08-28 DASH-17 was built (`client_reported_at`,
  the clamp at `db.py:640-649`, the `clock_skew` alert). The rate half was not:
  one report is ~15 writes plus up to three extra commits on the single worker
  whose SQLite the collector also writes, and a companion in a fast-retry loop
  (or a laptop waking with a backlog) can post several times a second with
  nothing refusing it. The symptom is other editors' reports timing out on
  `busy_timeout`, which reads on the fleet page as those machines going quiet.
- **Proposed:** an in-process token bucket keyed `(editor, machine)` - there is
  one worker by construction - that 429s past ~6 reports/minute with
  `Retry-After: 30` and logs once per machine per hour, plus a
  `machine_state.reports_throttled_at` so the grid can chip it rather than
  showing a machine that looks fine while being turned away.
- **Effort:** S   **Value:** med   **Confidence:** med

### DCORE-16: `_run_config`'s and `_run_enforce`'s notes are recorded, but nothing renders a HELD share
- **Lens:** resilience
- **Who:** admin
- **Where:** `collector.py:1400-1420` (`db.record_enforce_plan` before the HTTP
  loop), `alerts.py:1469` (`enforce_plan`, SEV_WARN, "a sharing change is
  held"), `collector.py:1428-1435` (the `put_folder` loop).
- **Today:** `record_enforce_plan` stores the diff the cycle was about to apply
  and `enforce_plan` alerts on it, which is the 08-28 DASH-3 fix and it is
  good. The remaining hole is the loop itself: if `put_folder` raises on folder
  10 of 40, the exception propagates, `_timed` records the cycle as failed, and
  the 30 folders after it are never attempted this pass - but the stored plan
  still describes all 40, so the alert says "held" for shares that were in fact
  applied and stays silent about the ones that were not. There is no per-folder
  record of what actually went out.
- **Proposed:** wrap each folder's `get_folder`/`put_folder` in its own try,
  count applied vs failed, mark the stored plan rows applied as they land, and
  return a note ("applied 9 of 40; syncthing refused the rest") so one bad
  folder cannot cost the rest of the fleet a cycle. The seed and the plan write
  are already committed before the loop, so this costs nothing structurally.
- **Effort:** S   **Value:** med   **Confidence:** med

## Still open from 08-28
- DASH-12: `/api/v1/health`'s `ok` still has no DB write canary and no tree
  mount canary - partly built (the `data_disk` and `nas_tree` alert kinds and
  `_feed_and_space_block` surface both, but the container healthcheck's `ok`
  at `api.py:1234` is still "Syncthing reachable AND collector alive").
- DASH-13: migrations still run with `PRAGMA foreign_keys=ON` (`db.py:660`),
  there is no `PRAGMA foreign_key_check` after a step and no pre-migration copy
  of `dashboard.db` - not built.
- DASH-15: `_walk_media_files` still has no NAS-side equivalent of
  `EDITOR_MEDIA_CAP` - not built (the collapse refusal from DASH-5 was).
- DASH-16: a machine still leaves the grid when `machine_state` ages out rather
  than showing as LOST - not built; see DCORE-12 for a second route to the
  same disappearance.
- DASH-17 (rate half) and DASH-18 (a read-only second collector connection) -
  not built; DCORE-15 restates the first with a machine-visible symptom.

## Cross-cutting notes
- **Companion agent:** DCORE-1's other half. A companion whose editor has been
  disabled should say "your account has been turned off - ask your admin"
  rather than retrying silently; the refusal reason is already carried on
  `machines.report_refused_reason` and could ride the 401 `detail`.
- **Dashboard UI agent:** `assignments.js` is the only place in the SPA where a
  destructive write has no confirm (DCORE-2) and where 401 is not special-cased
  (DCORE-9). `confirms.js` already has the pattern.
- **Server/NAS agent:** DCORE-3 hinges on `<data>/secrets/` ownership at first
  boot. Whatever the installer does to create `/data` should chown the
  `secrets` subdirectory explicitly and the deploy script should verify one
  secret file exists after the first start.
- **Release agent:** nothing here blocks a ship, but DCORE-1 and DCORE-6 are
  both second-customer items (`COMMERCIAL_READINESS.md`) rather than
  this-fleet items, and DCORE-6 lands on the zero-touch shape specifically.
