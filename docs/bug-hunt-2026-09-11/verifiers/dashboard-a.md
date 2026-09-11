# verdicts - dashboard-a

Verified at HEAD 40f931a. Everything below was read in the tree and, where a
mechanism could be staged, re-run from the dashboard venv
(`dashboard\.venv\Scripts\python.exe`) with scratch scripts, not from the
hunters' transcripts.

## dash-api-1
- Verdict: CONFIRMED (medium stands)
- Reasoning: `_trash_package_file` (api.py:5341) moves the file with
  `source.replace(target)`, which preserves mtime, and then calls
  `_prune_package_trash` on the very next line; the prune's only test is
  `path.stat().st_mtime < now - PACKAGE_TRASH_DAYS * 86400`. A package's mtime
  is its publish time (the publish writes a `.part` and renames it), so any
  build older than 30 days is unlinked inside the same call that reports it
  trashed. The route and the audit row then name a path that does not exist,
  which is worse than the pre-UX-9 silent unlink it replaced. One helper, two
  doors: `ui.py:3807` imports it, so the htmx delete behaves identically.
- Evidence: independent repro, a package file backdated 40 days, no HTTP:
  ```
  _trash_package_file -> ('...\\packages\\.trash\\windows\\2026-09-11T033238+0000-ccsync-companion-0.9.64.exe', None)
  trash dir contents: [WindowsPath('.../packages/.trash/windows')]      # EMPTY
  ```
- Fix note: `os.utime(target, None)` immediately after the `replace` and before
  `_prune_package_trash` is right and is the whole fix (parsing the timestamp
  prefix also works but adds a parser). Nothing pins the old behaviour:
  `test_delete_prunes_only_trash_older_than_the_configured_age`
  (tests/test_packages.py:346) ages the trashed file BY HAND with `os.utime`
  after the delete, so it still passes; the new test has to backdate the
  SOURCE. No other file needs touching.

## dash-api-2 + dash-release-jobs-1 (one defect, one verdict)
- Verdict: CONFIRMED (medium stands)
- Reasoning: `db.request_job_cancel` on a held job only stamps
  `cancel_requested_at` (db.py:9601), and `expire_leases` (db.py:9247) re-queues
  by lease alone: its `SELECT`, its `UPDATE` and `_spent_state` never look at
  that column, and `queued_jobs` (db.py:8884) filters on `state=queued` only.
  So the cancel survives exactly as long as the lease. The module comment at
  db.py:9560-9581 asserts the opposite ("stays visible as cancelling until the
  lease expires, and the lease is what ends it"), which makes this a contract
  violation, not a design choice. The expiry also burns an attempt and cools
  the sleeping machine down, so a cancelled job walks the fleet one machine per
  retry until the budget is spent and (for a media kind) is then PINNED to the
  dashboard's own worker.
- Evidence: independent repro against real `db.py`:
  ```
  claim: True / cancel: requested / state: claimed
  expired: [(1, 'queued')]
  state now: queued   cancel_at still: 2026-09-11T00:01:00+00:00
  in queued_jobs: [1]
  re-claimed by another machine: 1 claimed
  pending_job_cancels for BOX2: [1]
  ```
  One correction to the hunters' scenario: the new holder IS told to cancel on
  its next report (the last line above), so the second machine's ffmpeg runs for
  up to one report interval rather than to completion. That bounds the damage;
  it does not make the behaviour correct.
- Fix note: the suggested fix is right - in `expire_leases`, a row with
  `cancel_requested_at` set goes terminal (`failed`, `JOB_CANCELLED_ERROR`)
  instead of back to `queued`; the holder is gone by definition, so nothing is
  lied about behind a live child. The belt (`AND cancel_requested_at IS NULL` in
  `queued_jobs`) is safe. Callers to check when changing `expire_leases`: it is
  called from `api.py:9910` (the claim route), `db.py:7970` (the prune/retention
  path) and four tests - `tests/test_jobs.py:165,190`,
  `test_jobs_backpressure.py:161`, `test_jobs_pinning.py:124` - none of which
  cancels first, so none pins the old behaviour. Do NOT also make
  `request_job_cancel` force a held row terminal: that is the rule this fix must
  keep.

## dash-api-3
- Verdict: CONFIRMED and UPGRADED to high
- Reasoning: `roll_fleet_back` (api.py:6114) fans out per-machine update
  requests and never un-currents `from_version`, and `api_roll_fleet_back`
  refuses only `to == version`, never "from_version is still current". But the
  route is broken one step earlier than the hunter found, and worse: the report
  handler clears a pending push when the machine reports a version **at or past**
  the requested one (api.py:8799, the dash-core-6 widening). A rollback by
  definition asks for a version BELOW what the machine is running, so
  `_version_at_least("0.9.66", "0.9.64")` is True on the machine's very next
  report and the request is retired before `commands.upgrade` is ever emitted.
  [ ROLL THE FLEET BACK ] is therefore a no-op with a green toast on every
  fleet: no machine is ever told to apply anything. The hunter's re-offer effect
  is real but is the second-order one (it bites the machine whose editor took
  the older build by hand, or clicked the one-report-long tray offer).
- Evidence: end-to-end through the app (TestClient, machine on 0.9.66, channel
  current 0.9.66, roll back to 0.9.64):
  ```
  roll -> 200 ['jsmith/EDIT-PC']      pending: 0.9.64
  REPORT#1 commands.upgrade: None     upgrade offer: 0.9.64
  pending after report#1   : (cleared)
  REPORT#2 commands.upgrade: None     upgrade offer: None
  REPORT#3 (on 0.9.64) offer: 0.9.66      # the channel argues with the rollback
  ```
  Both existing tests stop at "the request was queued"
  (`test_sweep_2026_09_04_says_what_it_knows.py:346`,
  `test_release_channel.py:495`); neither ever reports afterwards.
- Fix note: the hunter's fix (make `to_version` current, or refuse) is necessary
  but NOT sufficient - it does not make the push deliver. The clear rule has to
  learn the push's direction: record the version the machine was on at push time
  (a column beside `update_requested_version` in `machines`, so db.py +
  schema.sql + a migration step + `db.request_machine_update`) and clear on "at
  or past" only for an upgrade, on exact match for a downgrade. A fix must also
  touch `ui.py:3593` (`partial_admin_roll_fleet_back` calls the same
  `roll_fleet_back` but not `api_roll_fleet_back`'s guards, so a guard added in
  the route only covers one door), and both tests above should be extended past
  the queueing step.

## dash-db-1
- Verdict: CONFIRMED (mechanism), DOWNGRADED to low
- Reasoning: the code is exactly as reported - `fetch_machine_selections`
  (db.py:6572) applies `base_machines` only in the bucket-inheritance loop
  (:6629), so a wired machine's OWN `selections` rows still come out, and
  neither `notices._check_plan_without_share` (:532) nor
  `invariants._check_plan_has_share` (:270) consults `base_machines` or `modes`
  (its sibling at invariants.py:324 does). The enforce cycle is safe because of
  CR-110's belt at collector.py, so the damage is confined to what an admin is
  TOLD: a permanent severity-`error` notice plus a BROKEN invariant row about a
  correct configuration. What downgrades it is that the state is escapable:
  unticking the project for that machine removes the row, `open_subjects` drops
  the subject and `clear_notices_of_kind` clears the notice - only the "and
  re-tick" half of the notice's fix text 409s, and a wired machine syncs nothing
  anyway, so the untick costs nothing. `plan_without_share` is also not in
  `alerts.ALERT_KINDS`, so nobody is mailed about it.
- Evidence: read of all three functions plus CR-110 in KNOWN_BUGS (line 10360),
  which records the fix as covering the bucket read, `selections_for_machine`,
  `copy_machine_plan` and the collector belt - the `own` branch is genuinely
  outside its scope. Reachability needs a machine that reports
  `machine_state.mode = 'base'` while still carrying its own rows and a known
  `syncthing_device_id`, which is exactly the "ex-editor machine flips to wired
  in the tray" path CR-110 itself names.
- Fix note: the suggested one-line fix ("skip `(editor, machine)` in
  `base_machines` when building `own`") fixes the two readers but has a side
  effect the hunter did not name: `assignments.py:67` builds the admin tick grid
  from the same map, so the wired machine's stale tick would become an INVISIBLE
  cell - present in the table, unticked on the page, with no button left to
  clear it. Either filter in the two consumers (notices/invariants), or add an
  opt-out parameter and keep the grid unfiltered, or delete the rows when a
  machine reports `mode='base'`. Also worth checking under any of those:
  `api.py:2713` (file-move fan-out) and `invariants.py:565`.

## dash-release-jobs-2
- Verdict: CONFIRMED (mechanism), DOWNGRADED to low
- Reasoning: `_heal_orphaned_progress` (dashboard_update.py:467) returns before
  the pid/nonce comparison whenever `restart_requested` is set, and the flag is
  cleared only by `consume_restart_request`, reached only from `finish_restart`
  in the lifespan shutdown (app.py:774). A process killed between
  `request_restart` and that shutdown does leave `in_progress: true,
  restart_requested: true` owned by a dead nonce, and `preflight` (:614) and
  `rollback` (:1399) both 409 on `in_progress`. What downgrades it: the latch
  does NOT survive "for ever". The next CLEAN shutdown of any later process
  (`docker compose restart`, a stack stop/start, any SIGTERM that reaches the
  lifespan) runs `consume_restart_request`, which clears the flag first and only
  then exits - so the recovery is a container restart, not a shell and not a
  hand-edited `/data/code/update_state.json`. On the appliance shape a restart
  is available from the container manager UI. Both wedged routes also refuse in
  bind-mount mode first, so only image-mode deployments can reach it at all.
- Evidence: read of `_heal_orphaned_progress`, `request_restart` (:1207),
  `consume_restart_request` (:1212), `finish_restart` (:1234) and the two 409
  sites; the ordering inside `consume_restart_request` ("the flag is cleared
  FIRST") is what makes the restart a real cure.
- Fix note: the suggested fix is right and low-risk - treat a
  `restart_requested` state whose `owner_nonce != PROCESS_NONCE` as spent on the
  first `read_state` of a new process. Watch one thing: `finish_restart` uses
  the same flag to choose the RESTART_EXIT_CODE, so healing it at startup means
  a process that was killed mid-restart will exit 0 rather than 75 at its next
  shutdown. That is correct (the re-exec already happened), but
  `tests/test_dashboard_update.py` has cases around the exit code and the
  exemption, and they should be read before changing the early return.

## dash-core-1
- Verdict: CONFIRMED (high stands)
- Reasoning: `SynologyClient._http` (nas/synology.py:321-330) calls
  `self.session.post/get` with no `allow_redirects`, i.e. `requests`' default of
  True, and nothing above it inspects a 3xx (`_json` only rejects a non-2xx
  AFTER the chain has resolved). Every DSM credential this dashboard holds is in
  a POST BODY: `_ensure_session` posts `passwd=<DASH_NAS_PW>`, `_request` puts
  `_sid` and `SynoToken` in the body, `set_known_password` a freshly set editor
  password. `requests` strips `Authorization` across a host change but never a
  form body and never a custom header, and a 307/308 preserves method and body
  verbatim. `nas/truenas.py:112-137` does the identical call correctly, with a
  comment citing the same invariant; CR-111 (KNOWN_BUGS:10373) says the fix
  covered "the OIDC token POST and every TrueNAS request" and never mentions
  this backend.
- Evidence: measured, not argued - two loopback servers, one 307ing to the
  other, called in exactly `_http`'s shape (requests 2.34.2):
  ```
  final url    : http://127.0.0.1:52505/steal
  history      : [307]
  body replayed: api=SYNO.API.Auth&method=login&account=dsm-admin&passwd=SUPER-SECRET&session=CCSync&format=sid
  X-SYNO-TOKEN : tok-123
  Authorization: None          # stripped, which is why the BODY is the exposure
  ```
  `grep -n allow_redirects nas/*.py` hits only `nas/truenas.py:124`.
- Fix note: copy `nas/truenas.py:127-136` verbatim into `_http` -
  `allow_redirects=False` plus a `NasError` naming the status and the `Location`
  and saying nothing was sent on. No test pins the old behaviour:
  `tests/test_synology_client.py` stubs `_http` or the session entirely. Note
  that the one-line refusal must go in `_http`, not `_json`, because `_json`
  only ever sees the resolved response. The same one-liner belongs in
  `syncthing_client._request` (dash-core-2, not my assignment, but it is the
  same wire and should ship in the same change).

## dash-core-3
- Verdict: CONFIRMED (mechanism), DOWNGRADED to low
- Reasoning: reproduced exactly - `_run_secrets` (setup_engine.py:781) passes a
  snapshot of the five `SECRET_ENV_VARS` only, `ensure_secrets` ends with an
  unconditional `_write_sidecar_env_files(env, secrets_dir)`, and that function
  reads `env.get("APP_UID")`/`APP_GID`, which the snapshot does not carry, so
  `internal.env` is rewritten with the token line alone. What downgrades it is
  the consumer: `internal.env` is read by exactly one service in one file
  (`dashboard/deploy/compose.appliance.yaml:300`), and that same service block
  ALSO sets `APP_UID: "${APP_UID:-3000}"` / `APP_GID:` in its `environment:`
  key (:302), which takes precedence over `env_file:` in docker compose. The
  sidecar therefore still starts with the right uid/gid; the two lines in
  `internal.env` are belt to that brace. CR-57's write-up of this file
  (KNOWN_BUGS:2090) is about the internal TOKEN, not the uid pair.
- Evidence: independent repro (boot with the real environment, then the
  wizard's snapshot, same directory):
  ```
  after boot      : 'CCSYNC_INTERNAL_TOKEN=tok-abc\nAPP_UID=3000\nAPP_GID=3001\n'
  after setup task: 'CCSYNC_INTERNAL_TOKEN=tok-abc\n'
  ```
  plus `grep -rn internal.env dashboard/deploy/*.yaml` - only
  compose.appliance.yaml, with the `environment:` override beside it.
- Fix note: the second of the two suggested fixes is the better one - have
  `_write_sidecar_env_files` fall back to `os.environ` for the non-secret keys,
  so no future narrow-mapping caller can drop them. Adding the two names to
  `_run_secrets`' snapshot also works and is smaller. Either way the test to add
  is the one that does not exist: `ensure_secrets` called twice with two
  different env shapes against one directory (`tests/test_secrets_boot.py`).

## dash-core-4
- Verdict: CONFIRMED (logic), DOWNGRADED to low
- Reasoning: the logic defect is exactly as reported - `_origin_mismatch`
  (app.py:911-914) folds `Origin: null` into the same branch as an absent
  Origin, and with no `Referer` returns False, i.e. "not a mismatch". `null` is
  an opaque origin and means the opposite of same-origin, so the check inverts
  its meaning for the one value that is unambiguous. It is low rather than
  medium because nothing under `/cards/` is reachable without a session:
  `_LOGIN_GATE` opens only `/cards/manifest.webmanifest`, `/cards/icon.svg` and
  `/cards/sw.js` (GET, no secret), the ~70 POST routes stay session-gated, and
  `auth.start_session` sets `samesite="lax"` (auth.py:673), so every shape that
  produces `Origin: null` (sandboxed iframe, `data:`/`blob:` document,
  cross-origin redirect chain) is also cross-site and arrives with no cookie and
  a 401. The layer is not doing what its comment claims, but no request gets
  through it today.
- Evidence: read of `_origin_mismatch`, `csrf_gate` (app.py:945-953),
  `_CSRF_ORIGIN_ONLY_PREFIXES` (:187), the login-gate carve-outs (:104-124) and
  the cookie attributes. `/cards/agent/{state,result}` is exempted separately
  and is a fleet-token route with no cookie behind it, so it is not a second
  door here.
- Fix note: the suggested split is right and is genuinely two lines: keep an
  ABSENT Origin a pass (the documented carve-out for same-origin form posts),
  treat a literal `null` with no usable `Referer` as a mismatch. No test pins
  the current behaviour (there is no `Origin: null` case anywhere in the suite),
  so the fix comes with its own new test. Nothing else on the wire changes: the
  Cards page's own fetches are same-origin and send a real Origin.

## res-fleet-1
- Verdict: CONFIRMED, DOWNGRADED to medium
- Reasoning: `request_job_cancel` (db.py:9585) is the one write in the jobs
  state machine that does not check `cur.rowcount` - `claim_job`,
  `heartbeat_job`, `finish_job` and `take_pinned_job` all return
  `bool(cur.rowcount)`. It reads with `get_job`, branches on `JOB_QUEUED`, and
  the read is genuinely unlocked: `db.connect` leaves `isolation_level` at the
  legacy default, so a bare SELECT runs in autocommit and opens no transaction
  for a concurrent claim to conflict with. When a claim commits in that window
  the queued UPDATE matches nothing, the held branch never runs,
  `cancel_requested_at` stays NULL, and the route answers
  `{"ok": true, "state": "failed"}` and logs "cancelled" over a job that will
  run to completion. Downgraded from high because the window is the few
  microseconds between one SELECT and one UPDATE on the same connection, it
  needs an admin click to coincide with a `POST /jobs/claim`, and the outcome is
  one job completing (the `.partial` + atomic-rename rule means no corrupt
  output) rather than anything destroyed.
- Evidence: independent repro with one claim interleaved between the read and
  the write:
  ```
  interleaving claim: True
  request_job_cancel returned: failed
  actual state: claimed   cancel_requested_at: None
  pending_job_cancels BOX1: []
  ```
- Fix note: the suggested fix is right (on `rowcount == 0`, re-read and fall
  through to the held/pinned branch, and return the state that actually
  resulted). One fix does NOT cover all three job findings: this one is about a
  cancel that is never recorded, dash-api-2/dash-release-jobs-1 about a cancel
  that IS recorded and is then discarded by `expire_leases`. They compose in the
  right direction - fixing this one makes more rows carry
  `cancel_requested_at`, which is exactly the column the other fix must then
  honour - so ship them together. `api.py:9825` needs no change beyond
  reflecting the returned state; `tests/test_jobs_cancel.py` has no
  concurrent-writer case to break.

## res-fleet-2
- Verdict: CONFIRMED (medium stands, with one correction)
- Reasoning: `mount_status` is a write-once registry - `record()` is called only
  from the boot block (app.py:1439, after `reset()` at :1355) and from
  `ytdl.py:456` on the feature-flag flip. Nothing re-probes. The three readers
  (`notices._check_feature_mounts`, `alerts.Ctx.mounts`, `api._mounts_block`)
  therefore render a boot-time verdict as a statement about now, and a mount
  whose data root disappears at runtime keeps reading `mounted`, so
  `_check_feature_mounts` writes nothing and clears nothing and
  `/api/v1/health` says all four are up. `_run_inventory`'s not-mounted canary
  (collector.py:1566) covers `DASH_PROJECTS_DIR` only, so a vault-only or
  music-only flap is invisible to every channel. Correction to the hunter: the
  inverse case is not silent - `feature_not_mounted`'s fix text already says
  "Check the container's bind mounts (docs/DOCKER.md), then restart the
  dashboard" (notices.py:692), so an admin IS told a restart is what is needed;
  what is missing is the notice clearing itself when the mount returns.
- Evidence: `grep -rn mount_status` over the package - two `record()` call
  sites, both above; `mount_status.py`'s own docstring ("written from inside the
  boot block"); the readers at notices.py:670, alerts.py:940, api.py:1429.
- Fix note: the suggested `recheck()` is the right shape, but it must stay
  exactly as cheap as claimed (an `is_dir()` on the already-resolved data root,
  no import, no DB) because it would run on the collector thread every cycle,
  and it must preserve the tri-state vocabulary rather than invent a fifth
  value - `ui.py` and `_mounts_block` compare against `broll.MOUNTED` and
  friends. A mount that has come back must NOT be flipped to `mounted` by the
  recheck alone: the ASGI sub-app was never mounted in this process, so the
  honest verdict is "degraded, restart to serve it again". Files a fix touches:
  `mount_status.py`, `broll.py`/`music.py`/`cards.py` (each needs to expose its
  root), and the collector cycle that calls it.

## res-fleet-4
- Verdict: CONFIRMED (mechanism), DOWNGRADED to low
- Reasoning: both schedules do pass `ok_only=False` (alerts.py:704, :741)
  against a helper whose own docstring says the parameter exists "because a send
  that FAILED has told nobody", so an `ok=0` row retires the slot exactly as a
  success does and the week's report is lost rather than delayed. The hunter is
  also right that flipping them would not reintroduce the vendor-build noise:
  the no-sink case is recorded `ok=1` directly at alerts.py:3869, outside
  `send()`. What downgrades it is that neither half is silent in the dangerous
  direction. A failed weekly raises `weekly_send_failed` (SEV_ERROR,
  `_check_weekly_send` at :2024) which stands open on the Alerts page and is
  mailed the moment the sink recovers, so the owner learns the channel broke;
  what is lost is one summary email. And a missed heartbeat is a DEAD MAN'S
  switch failing towards alarm - the owner sees no proof of life and
  investigates - which is the safe direction for that feature.
- Evidence: code read of `weekly_due`, `heartbeat_due`, `db.last_alert_at`
  (db.py:6257) and `run_cycle` (:3850-3895).
- Fix note: `ok_only=True` in both is correct but is not free: with a sink that
  is down, `weekly_due` then stays True and `run_cycle` attempts an SMTP send on
  EVERY collector cycle until Tuesday's slot, each attempt blocking the collector
  thread for the socket timeout. Ship it with the ceiling the hunter mentions (a
  small per-slot attempt budget, or a backoff keyed on the last `ok=0` row) or
  the cure costs a stalled collector. `tests/test_alerts.py` has weekly-schedule
  cases that assert "sent once per slot"; read those before changing the
  predicate.

## res-fleet-5
- Verdict: CONFIRMED (mechanism and reachability), DOWNGRADED to low
- Reasoning: settled by reading `_run_enforce` end to end. The two routes into
  `desired` really are filtered at different granularities: `plan_rows` is
  narrowed by `base_pairs` and by `fetch_machine_selections(sync_modes=FULL)`,
  while the fallback at collector.py:1428-1433 iterates `plan_editors` (from
  `fetch_all_selections`, filtered only by `base_only_editors` and `suspended`)
  and adds every device of that PERSON that is not in `mapped_device_ids`.
  `editor_devices` is built from the Syncthing device NAME resolving to an
  editor account (:1262-1267), so a device labelled with the username but absent
  from `machines.syncthing_device_id` does get a person-level share of every
  FULL-ticked project, whatever that machine's own tick mode or wired flag says.
  Reachability is narrower than the hunter implies, which is why this is low:
  the companion self-reports its device id on a refresh cycle, so a regenerated
  identity is re-mapped within a report or two. The durable shape needs a
  machine whose Syncthing is up and approved while its companion cannot read
  `myID` (wrong or rotated local `syncthing_api_key`, admin API unreachable) -
  real, and in this fleet's history, but not the common case.
- Evidence: collector.py:1230-1440 read line by line; `editor_devices`
  construction at :1262; the fallback at :1428; `base_pairs`/`base_editors` at
  :1313-1314; `fetch_all_selections(sync_modes=(SYNC_MODE_FULL,))` at :1301.
- Fix note: the suggested fix is a NO-OP as written. It proposes subtracting
  "the devices of that person's machines that are base/suspended/upload-only
  where those machines' device ids ARE known" - but a known device id is in
  `mapped_device_ids` and is already excluded from the fallback by the existing
  comprehension. An unmapped device is by construction unattributable to a
  machine, so no per-machine predicate can reach it. What would actually work:
  narrow the fallback to editors who have NO machine-mapped device at all (the
  "dashboard upgraded ahead of the companion" case it was written for), or keep
  it and emit the once-per-(editor, device) warning the hunter suggests so the
  state is visible instead of silent. The warning alone is the safe half and
  matches `_warned_unknown_editor` / `_warned_unapproved_device` beside it.
