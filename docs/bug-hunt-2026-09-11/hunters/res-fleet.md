# res-fleet - cross-cutting resilience lens: what the fleet does when the server side goes wrong

Files read (with approximate coverage):
- `dashboard/src/ccsync_dashboard/collector.py` (the whole enforce/inventory/alerts cycle, ~60%; `_run_enforce` + `_enforce_loop` + `_run_inventory` read line by line)
- `dashboard/src/ccsync_dashboard/api.py` (the report reply's whole `commands` block 8740-9010, the jobs routes 9825-9900, `_version_tuple`/`_version_at_least`, `_mounts_block`, `_wants_idle_queue_depth`; ~25% overall)
- `dashboard/src/ccsync_dashboard/db.py` (jobs lease/claim/cancel/pin 8650-9660, selections/enforce readers 2341-2366 + 6532-6560, `version_tuple`, `store_machine_capabilities`, `pending_file_moves`, `pending_resolve_undos`, `last_alert_at`; ~20%)
- `dashboard/src/ccsync_dashboard/alerts.py` (`Ctx`, `_check_out_of_tree` + `_synced_project` (CR-232, HEAD commit), `send`/`deliver`/`_send_digest`/`run_cycle`, `weekly_due`/`heartbeat_due`, `sink_deliverable`; ~35%)
- `dashboard/src/ccsync_dashboard/jobs.py` (`offers_for_machine`, `machine_facts`, `fleet_facts`, `policy_refusal`, pin verdict; ~50%)
- `dashboard/src/ccsync_dashboard/mount_status.py` (100%), `notices.py::_check_feature_mounts`, `broll.py::mount_broll` tail, `ytdl.py` mount record, `cards_exec.py` (skim)
- `dashboard/src/ccsync_dashboard/dashboard_update.py` (`apply`, `rollback`, `version_tuple`, `release_pinned_jobs` caller in `app.py`; ~30%)
- `dashboard/src/ccsync_dashboard/syncthing_client.py` (surface)
- `companion/src/ccsync_companion/reporter.py` (auth/failure/health-state paths, `_run_cycle`, `_report_loop`; ~25%), `identity.py` (token parse/validity)
- `git show 40f931a` (CR-232, the newest commit in the tree)

Tests run: none of the suites. One ad-hoc repro from the dashboard venv
(`dashboard/.venv/Scripts/python.exe`, scratchpad script) against a fresh
migrated DB - output inline in res-fleet-1.

## Findings

### res-fleet-1 - a job cancelled in the same instant a companion claims it is reported cancelled and keeps running
- Severity: high
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/db.py:9585-9609` (`request_job_cancel`), reached from `dashboard/src/ccsync_dashboard/api.py:9825-9857` (`api_cancel_job`); the racing writer is `db.claim_job` (`dashboard/src/ccsync_dashboard/db.py:9067-9086`) on the fleet claim route, which the companion calls from `companion/src/ccsync_companion/jobs_runner.py`
- What: `request_job_cancel` reads the job with `get_job`, branches on `state == JOB_QUEUED`, and then issues an `UPDATE ... WHERE id=? AND state=?` - but **never checks `cur.rowcount`**. Every other write in this file is a compare-and-set whose result is returned (`claim_job`, `heartbeat_job`, `finish_job`, `take_pinned_job` all `return bool(cur.rowcount)`); this one is the single CAS in the jobs state machine whose failure is swallowed. When a claim commits between the read and the UPDATE, the queued-branch UPDATE matches no row, the "held" branch (the one that writes `cancel_requested_at`) never runs, and the function still returns `"failed"`.
- Failure scenario: an admin clicks [ CANCEL ] on a queued `whisper` job at the moment the base rig's `POST /api/v1/jobs/claim` lands. The API answers `{"ok": true, "state": "failed"}` and logs `job #N cancelled by alex (failed)`. The job is in fact `claimed`, `cancel_requested_at` is NULL, so `db.pending_job_cancels` returns nothing, `commands.jobs.cancel` never carries the id, the companion never kills its child, and the job runs to completion and reports `done`. The admin's cancel has evaporated with a success message - exactly the shape CLAUDE.md's "nothing forces a row terminal behind a live ffmpeg" rule is trying to avoid, arrived at from the other side.
- Evidence: repro from the dashboard venv, `db.get_job` wrapped so one claim interleaves between the read and the UPDATE:
  ```
  claim -> True
  request_job_cancel returned: failed
  actual state: claimed cancel_requested_at: None
  pending_job_cancels for that machine: []
  ```
  (The route's echoed `job` object does show `claimed`, so the page is not wholly lying - but `state` says `failed`, the log line says cancelled, and nothing anywhere will ever stop that job.)
- Ledger: new (no `request_job_cancel` entry in KNOWN_BUGS; the closest is the CR-1xx cancel design note at the file's §"cancel (v45)").
- Suggested fix: make `request_job_cancel` a real CAS - if the queued UPDATE's `rowcount` is 0, re-read the row and fall through to the "held/pinned" branch (recording `cancel_requested_at`), or loop once; return the state that actually resulted.

### res-fleet-2 - the four feature mounts are judged once at boot, so a NAS export that flaps leaves "mounted" standing for ever (and a mount that comes back stays broken on the page)
- Severity: medium
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/mount_status.py:1-71` (write-once registry), written from `dashboard/src/ccsync_dashboard/app.py:1355,1439` (the boot block) and nowhere else except the ytdl feature-flag flip (`dashboard/src/ccsync_dashboard/ytdl.py:441-456`); read by `dashboard/src/ccsync_dashboard/notices.py:655-695` (`_check_feature_mounts`), `dashboard/src/ccsync_dashboard/alerts.py:940` (`Ctx.mounts`) and `dashboard/src/ccsync_dashboard/api.py:1416-1440` (`_mounts_block` on `/api/v1/health`); the verdicts themselves come from `broll.py:416-498`, `music.py`, `cards.py`, each of which probes its data root with `is_dir()` once.
- What: the tri-state plus reason sentence that DDIAG-7 built the registry for is computed exactly once, inside `create_app`. Nothing re-probes. The collector runs `_check_feature_mounts` every cycle but only re-reads the frozen snapshot, so the notice it writes or clears is a statement about boot time rendered as a statement about now.
- Failure scenario: the NAS SMB/NFS export under the container flaps at 03:00 (scenario 4). `/vault` and the music data root vanish. `mount_status` still says `("mounted", "serving /broll")`; `_check_feature_mounts` therefore *clears* nothing and *writes* nothing, `/api/v1/health` reports all four mounted, the topbar still shows B-ROLL and MUSIC, and every request under them 500s or serves an empty library - with no notice, no alert kind, and nothing on PROBLEMS THE SERVER FOUND. The inverse is as bad and more common: the container was restarted while the NAS was still coming up, `broll` recorded `absent`, and after the mount returns the link stays hidden and the `feature_not_mounted` notice stays open until somebody restarts the container - and nothing tells the admin that a restart is what is needed. Compare `_run_inventory` (`collector.py:1565-1580`), which does have a per-cycle not-mounted canary; the feature mounts have none.
- Evidence: `grep -rn "mount_status" dashboard/src/ccsync_dashboard` - the only `record()` calls are in `app.py`'s boot block and `ytdl.py`'s feature gate. `mount_status.py`'s own docstring says the state is "written from inside the boot block"; `_check_feature_mounts`'s docstring says "a status this pass could not read is not evidence that the four pages are up", but a status it *can* read is treated as evidence that they are.
- Ledger: new (KNOWN_BUGS 11689/11823/12111 describe DDIAG-7's registry, none mention re-probing).
- Suggested fix: give each mount a cheap `recheck()` (the same `is_dir()` on its data root, no import, no DB) and call it from the collector cycle before `_check_feature_mounts`, re-recording the verdict; a mount whose root has gone becomes `degraded` with the reason, and a mount that has come back either clears or says "restart the dashboard to serve it again".

### res-fleet-3 - CR-232 makes "footage is outside the tree" send a false RECOVERED every time an editor opens a personal project
- Severity: medium
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/alerts.py:1771-1779` (`_check_out_of_tree`, the `if project and not slug: continue` added at HEAD commit 40f931a) interacting with `dashboard/src/ccsync_dashboard/alerts.py:3726-3757` (`deliver`'s recovery pass over `_open_subjects`), reading `Ctx.open_projects` built at `alerts.py:965-985` from `machine_state.resolve_project`
- What: the new filter drops the finding for a machine whose open Resolve project cannot be tied to the tree. `deliver` treats "this subject left the scan" as RECOVERED and mails/digests "this has cleared, no action is needed" - the exact lie the `repeat=False` mechanism was invented to avoid for dead machines (`_f`'s docstring). The subject is `editor/machine`, which is stable, but the *predicate* now swings with whichever project happens to be open at scan time, while the `resolve_out_of_tree` count it is about does not.
- Failure scenario: ruskin's machine is correctly alerted ("footage is outside the tree in 'FF5 Civil Defence'"). He opens his own wedding project for an hour. The next collector cycle drops the finding, `_open_subjects` still has `(out_of_tree, ruskin/DESKTOP-LQQ41TC)` open, and the owner gets "RECOVERED: footage is outside the tree" for a fault that is unchanged. He switches back after lunch and gets the alert again. On a machine where the editor moves between a fleet project and a personal one a few times a day this flaps once per switch, and the recovery mail is the one the owner will act on.
- Evidence: read `deliver` at `alerts.py:3726` - `checked_kinds` includes `out_of_tree` (its check did not fail), `(kind, subject)` is not in `seen` because the loop `continue`d before appending, so `compose_recovered` is composed and sent (or added to the digest with `recovered += 1`). Nothing in the CR-232 diff touches the recovery pass; `dashboard/tests/test_alerts.py`'s new cases (128 added lines) assert on the findings list only, never on a recovery.
- Ledger: new, on code committed 2026-09-10 (CR-232).
- Suggested fix: keep the subject in the scan when the count is non-zero but suppress delivery for it - e.g. emit the finding with `repeat=False` and a "not a tree project" body, or add it to a `seen`-equivalent set so the recovery pass skips it. Silence must not be spelled as recovery.

### res-fleet-4 - a weekly report (and a daily heartbeat) whose send FAILS is recorded as done and never retried
- Severity: medium
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/alerts.py:685-713` (`weekly_due`) and `:716-747` (`heartbeat_due`), both calling `db.last_alert_at(..., ok_only=False)` at `dashboard/src/ccsync_dashboard/db.py:6257-6276`; the send itself at `alerts.py:3868-3879` (`run_cycle`, `dedup=False`)
- What: `last_alert_at`'s own docstring says `ok_only` exists "because a send that FAILED has told nobody: suppressing the retry on the strength of it would be the dedup silencing the alert outright". Both schedules pass `ok_only=False`, so an `ok=0` row - the row `send()` writes when a *configured* sink refuses - satisfies the schedule exactly as a successful one does.
- Failure scenario: scenario 7. Google's SMTP is refusing at 08:00 Monday (an app password rotated, a TLS blip, the container's DNS not up yet). One attempt is made, fails, writes `alert_log(kind='weekly', ok=0)`. `weekly_due` is then False until next Monday's slot: the week's report is gone, not late. `weekly_send_failed` does raise an error finding - through the same sink that is down, so on a single-sink site nobody is told by mail either; it only lands on the Alerts page. Same for the DDIAG-17 dead-man's heartbeat: one failed attempt retires the day, so a ten-minute outage over the heartbeat slot silently removes that day's proof of life. `weekly_due`'s own docstring ("a container down for the whole of Monday still sends it on Tuesday") states the intent this defeats.
- Evidence: code read; `run_cycle` passes `dedup=False` for both, so the *only* thing gating a re-attempt is `weekly_due`/`heartbeat_due`. The `sink == SINK_NONE` case is handled separately and records `ok=1` deliberately, so flipping these two to `ok_only=True` does not reintroduce the vendor-build noise that motivated that branch.
- Ledger: new.
- Suggested fix: pass `ok_only=True` in both, and bound the resulting re-attempts (e.g. at most one attempt per collector cycle is already the shape, or add a small "N attempts per slot" ceiling) so a dead sink costs one SMTP timeout per cycle rather than losing the week.

### res-fleet-5 - the enforce cycle's person-level fallback can share a folder with a machine whose tick is upload-only, or with a base rig, whenever that machine's Syncthing device is unmapped
- Severity: medium
- Confidence: PLAUSIBLE
- Where: `dashboard/src/ccsync_dashboard/collector.py:1424-1436` (the `for editor in plan_editors:` fallback in `_run_enforce`), fed by `db.fetch_all_selections(conn, sync_modes=(db.SYNC_MODE_FULL,))` (`dashboard/src/ccsync_dashboard/db.py:6532-6549`) and filtered only by `db.base_only_editors` (`db.py:2355-2366`) and `suspended_editors`; the per-machine path immediately above is filtered by `db.base_machines` (`db.py:2341-2352`) and by the FULL-mode `fetch_machine_selections`
- What: the two routes into `desired` are filtered at different granularities. The per-machine route is per `(editor, machine)`: upload-only ticks are excluded (mode filter) and wired machines are excluded (`base_pairs`). The fallback is per PERSON: it adds *every* device of a ticked editor that no machine row claims. A person's second computer is only protected from it by being in `mapped_device_ids`, i.e. by having reported a `syncthing_device_id`.
- Failure scenario: alex is ticked FULL for `2026/FF5/Animals` on the Razer, and `upload_only` for the same project on a second machine whose Syncthing identity was regenerated (memory: "Stuck lane C = regenerated device ID" is a state this fleet has really been in) so `machines.syncthing_device_id` no longer matches any approved device. `plan_rows` correctly omits that machine; `plan_editors` contains `alex` because the Razer's FULL tick is there; the fallback adds the second machine's device to `desired`, Syncthing shares the folder, and lane B content lands on a computer whose whole tick mode exists to stop that ("no share", deliberately not `sendonly` - CLAUDE.md / `docs/UPLOAD_ONLY_TICK.md`). The same shape puts every FULL-ticked project on an unmapped base-rig device belonging to a person who also owns an editing machine, since `base_only_editors` is the rollup and is false for that person (`base_machines` is the per-pair predicate CR-28 added for exactly this, and the fallback does not use it).
- Evidence: read both paths; `db.fetch_all_selection_modes`'s docstring even names the state ("`mixed` - one person, two computers, two answers"), which is precisely what the person-level fallback collapses to FULL. I did not construct a live Syncthing config to demonstrate it, hence PLAUSIBLE rather than CONFIRMED.
- Ledger: new; related to CR-28 (fixed) and the B16 family the fallback was written to avoid.
- Suggested fix: keep the fallback (its purpose - not unsharing a device the registry cannot place - is right) but subtract from it the devices of that person's machines that are base, suspended or upload-only-for-this-slug where those machines' device ids ARE known, and consider warning once per (editor, device) that an unmapped device is receiving a person-level share.

### res-fleet-6 - the blast-radius brake counts removals from a snapshot the loop then does not use
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/collector.py:1443-1483` (`removals` computed from `actual`, which came from `cfg = self.client.config()` at line 1184) vs `collector.py:1514-1533` (`_enforce_loop` re-reads `live = self.client.get_folder(slug)` and keeps only `existing` entries that are in `desired`)
- What: the brake is computed against the config snapshot taken at the top of the pass; the write is applied against a fresh per-folder read. Any device that entered a folder between the two reads (an admin approving a pending device, `_ensure_shared_folders` creating and sharing, another enforce-style writer) is silently dropped by the loop without ever having been counted by `enforce_max_share_removals`, recorded in `record_enforce_plan`, or named in the "REFUSING n share removal(s)" log.
- Failure scenario: an admin approves a device and shares a folder with it through the Syncthing GUI while a cycle is between its `config()` call and its `get_folder()` call for that folder; the share disappears with no line anywhere saying it was removed, and the brake's count was computed as if it had never existed.
- Evidence: code read. The window is short (one HTTP round trip per folder) and the next cycle usually re-adds a legitimate share, so this is low, not high - but it is a hole in a brake whose whole job is that no unshare happens uncounted.
- Ledger: new; related to the B16 family and DASH-3.
- Suggested fix: compute the removal set for a folder from `live` inside `_enforce_loop` and refuse (rather than silently apply) a folder whose fresh read disagrees with the planned `actual`, re-planning it next cycle.

## Coverage note
Traced end to end: scenario 1 (container restart) for the pinned-job path
(`release_pinned_jobs` at boot, `take_pinned_job` CAS - clean), the
file-move/resolve-undo re-delivery contract (`pending_*` bounded by
ANSWER not by delivery - clean, a lost reply re-sends), the pushed-upgrade
clear (`_version_at_least`, committed in the reply - clean), the
dashboard self-update swap (`apply`'s ordering and `_heal_orphaned_progress`
- clean; the only gap found is a kill between `rmtree(final)` and
`staging.rename(final)` when re-applying the SAME version, which leaves
`current.json` naming a tree that is gone and falls back to the image,
not worth a finding). Scenario 2 version skew: `db.version_tuple` /
`api._version_tuple` / `dashboard_update.version_tuple` all handle two-digit
minors correctly and read an unparseable version as OLD;
`JOBS_QUEUE_DEPTH_MIN_VERSION`, `machine_allows_kind` (empty = every kind),
`store_machine_capabilities` (None writes nothing) and
`policy_refusal`'s `REFUSE_NO_CAPABILITIES` all hold CLAUDE.md's
"silence is not an instruction" rule. Scenario 3: the empty-`myID` skip, the
seed-flag guard, the unmapped-device rule and the per-folder failure
isolation are all in place; the two holes I found are res-fleet-5 and -6.
Scenario 4: `_run_inventory`'s canary and `replace_nas_media`'s collapse
brake are good; the gap is res-fleet-2.

NOT reached: the three mounted web apps' own `routes_fleet.py` (b-roll,
music, ytdl) and their ingest-batch/lease wires from the companion side
(`broll_upload.py`, `music_ingest.py`, `ytdl_executor.py`) - I read only the
dashboard-side cancel lookups (`broll_cancel_requested` /
`music_cancel_requested`, both correctly best-effort); `server/` and
`publish_db.py` / snapshot behaviour against a missing mount (scenario 4's
second half); scenario 5 (token rotation) beyond the companion's
`AUTH_REJECT_CODES` handling and identity token validity, which looked sound
- I did not trace the dashboard's `resolve_companion_credential` fallbacks;
scenario 8's per-contract deploy-order matrix beyond jobs/capabilities and
upload-only. The suites do not cover any of the interleavings in
res-fleet-1 (no concurrent-writer test exists for the jobs state machine)
nor a runtime mount disappearance (res-fleet-2).

## OUT OF TERRITORY
- `dashboard/src/ccsync_dashboard/alerts.py:3608-3616`: `_take_catch_up` clears `META_CATCH_UP` before `_send_digest`, but the budget-exhausted branch at `:3761-3764` returns without writing any ledger row, so the one-off "here is everything currently open" catch-up digest is lost when a sink is configured during a slow pass.
- `dashboard/src/ccsync_dashboard/alerts.py:3619-3647` (`_send_digest`): a failed digest writes `ok=0` rows for every finding, and `send`'s dedup reads any row, so a single SMTP blip mutes the entire cycle's findings for 24 h. Documented as deliberate for per-event sends; worth re-checking now that one failure covers N findings at once.
- `dashboard/src/ccsync_dashboard/jobs.py:486-521` (`machine_facts`): stored capabilities are never aged out, so a machine rolled BACK below 0.9.56 (a first-class operation per CLAUDE.md) keeps advertising nvenc/whisper it can no longer act on; bounded by RANK_GRACE_SECONDS, so only a 60 s delay per job.
