# bug-wire - every wire between companion and dashboard (report + commands, upgrade offer, jobs, file moves, cards tunnel, 8899 loopback vs the web pages), both ends and both skew directions

Files read (approximate coverage):
- companion: reporter.py (payload build, section suppression, fit, post) ~70%; app.py report-reply fan-out (`_on_report_response`, `_apply_pushed_update`, `_apply_resume_lane_b`, `_apply_file_moves`, `_queue_file_move_answer`, `_relink_pending_moves`, `_apply_resolve_undo`, `_apply_diagnostics_request`, `_note_dashboard_version`, `sign_in`); jobs_runner.py (offer read, gate, claim/heartbeat/result, media + whisper runners) ~80%; timeline_cards_role.py tunnel client (`call`, `_note_answer`); broll_ingest.py FleetClient + `default_request` + cancel read; loopback_guard.py origins/host; broll_server.py CORS/body/dispatch envelope; upgrade.py `parse_upgrade`/`note_report_response`/`_accept_offer`; identity.py verify payload; proxy_relink.py fleet stand-ins; sync/syncthing_lane.py and sync/rclone_lane.py `last_error`/`detail` producers; sync/base.py LaneStatus.
- dashboard: api.py `ReportIn` and every sub-model it uses, `api_report` end to end (writes + reply builder), `_upgrade_info`, `_update_push_done`, `/verify`, package download + `_require_package_read`, `/diagnostics`, `_require_fleet_caller`, the whole `/jobs*` route group; db.py `mark_file_move_applied`, `_hydrate_file_move`, `claim_next_job`, `queued_jobs`, `pending_job_cancels`, `queue_depth`, `standins_known`, `version_tuple`, prune; cards_tunnel.py whole; broll.py BrollGate; music.py/ytdl.py header constants; app.py body limits.
- web apps: broll/web/app/routes_fleet.py, fleet_auth.py, identity.py; music/web/musicweb/fleet_auth.py (identity call); ytdl/web/ytdlweb/routes_fleet.py (identity call); broll/web/static/app.js insert loop; music/web/static/app.js send/reveal/status.
- templates/partials/project_detail.html (file-move target line).

Tests/probes run (dashboard venv, scratch files only):
- p1: `db.mark_file_move_applied` twice on one target - first `ok, relink_pending=True`, then the companion's later relink-done answer. Second call returns False; the row keeps `relink_pending=1` and the old detail.
- p2: an identity token minted with an OLD secret, read by the dashboard's `auth.read_identity_token_ex` with that secret in `session_secrets_previous` -> `('ruskin', True)`; read by `broll/web/app/identity.read_identity_token(NEW, tok)` -> `None`.
- p3: `api.ReportIn.model_validate` with one lane whose `last_error` is 2001 chars, and one whose `detail` is 501 chars -> `ValidationError` both times (a 422 of the whole report).
- p4: `urllib.request.Request(..., headers={'X-CCSync-Machine': '剪輯-PC'})` -> `UnicodeEncodeError: 'latin-1' codec can't encode` before any socket is opened.

## Findings

### bug-wire-1 - The "Resolve relinked after all" answer is dropped by the dashboard, so a move shows "Resolve not repointed yet" for ever
- Severity: medium
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/db.py:6237 (`mark_file_move_applied`, `AND applied_at IS NULL`); companion/src/ccsync_companion/app.py:8394 (`_relink_pending_moves` -> `_queue_file_move_answer(entry["id"], True, ...)`)
- What: RES-10's fix sends a move's answer twice: first `ok=True, relink_pending=True` (Resolve was closed or on another project), then, when a later project change lets the companion relink, a fresh `ok=True` answer with no `relink_pending`. The first answer sets `applied_at`, and every non-retrying write in `mark_file_move_applied` is `WHERE ... AND applied_at IS NULL`, so the second answer updates zero rows. The flag the page draws never clears.
- Failure scenario: An admin moves a clip of project B while the editor has project A open. The companion moves its copy and answers "moved; Resolve not relinked (not open)", `relink_pending=True`. Next morning the editor opens B, `_relink_pending_moves` relinks it, clears its own ledger flag and queues the done answer. The dashboard drops it. The project page says "moved, Resolve not repointed yet (moved; Resolve not relinked (not open))" for that computer for good, and the admin goes chasing a relink that already happened.
- Evidence: probe p1 (second call returns False, row still `relink_pending=1` with the first detail). project_detail.html:250 renders `moved, Resolve not repointed yet` from `t.relink_pending`. KNOWN_BUGS RES-10 says the fresh answer is sent "so the dashboard row updates", and nothing on the dashboard side does that.
- Ledger: regression of RES-10 (the dashboard half never worked)
- Suggested fix: in `mark_file_move_applied`, let an `ok` answer on an already-applied, `ok=1`, `relink_pending=1` row clear `relink_pending` and replace `detail` (a second UPDATE keyed on `relink_pending=1 AND ok=1`). Or have the companion send a separate `relink_done` state that the dashboard writes whatever `applied_at` says.

### bug-wire-2 - A session-secret rotation drain keeps the report and jobs alive but cuts every un-re-signed machine out of b-roll ingest, music ingest and ytdl
- Severity: medium
- Confidence: CONFIRMED
- Where: broll/web/app/fleet_auth.py:173, music/web/musicweb/fleet_auth.py:169, ytdl/web/ytdlweb/routes_fleet.py:267 (all `identity.read_identity_token(<current secret only>, ...)`); compare dashboard/src/ccsync_dashboard/auth.py:460 (`read_identity_token_ex`, which also accepts `DASH_SESSION_SECRET_PREVIOUS`)
- What: DASH-2 added an accept-only `DASH_SESSION_SECRET_PREVIOUS` so companion identity tokens survive a rotation, and api_report, `/jobs*` and `/cards/agent/*` (through `_require_fleet_caller`) use `read_identity_token_ex`. The three mounted apps verify `X-CCSync-Identity` against `DASH_SESSION_SECRET` alone. BrollGate, MusicGate and YtdlGate stamp the token verdict but pass the identity header through unchanged, so nothing on that path knows about the previous keys.
- Failure scenario: The owner rotates the secret by following docs/SECRETS.md. The fleet page says "[ N COMPUTER(S) STILL ON A RETIRED SIGNING KEY ]" and every report is accepted, so it looks healthy. On each of those N computers, every b-roll or music ingest claim, heartbeat, result and upload, and every requester-first YouTube download, gets 403 "a valid X-CCSync-Identity is required: sign in again". Clips dropped on the ingest page sit queued, and a batch that was mid-run loses its lease. None of it shows on the drain counter. The runbook says the drain keeps the fleet working.
- Evidence: probe p2 (the dashboard accepts the old-key token, the b-roll reader returns None). The grep for `SESSION_SECRET_PREVIOUS` across broll/web, music/web and ytdl/web finds nothing.
- Ledger: related to DASH-2 (FIXED; its fix did not reach the mounted apps)
- Suggested fix: have each gate verify the companion identity with `auth.read_identity_token_ex` and stamp the verified name the way it stamps the token verdict (strip inbound, append the gate's own header). Or pass the previous secrets to the sub-apps and loop over them in their `read_identity_token`.

### bug-wire-3 - Lane `last_error`/`detail`/`current_project` caps still RAISE, and the companion never caps them: one long lane error takes the whole report down with a 422
- Severity: medium
- Confidence: PLAUSIBLE
- Where: dashboard/src/ccsync_dashboard/api.py:6832-6858 (`LaneReportIn`: `last_error` max_length 2000, `detail` 500, `current_project` 512; `TransferIn.name`, `CompletedIn.name` 512; no before-validator); companion/src/ccsync_companion/sync/syncthing_lane.py:771 and :841 (`"folder(s) not configured/shared: " + ", ".join(...)` and `"folder(s) in error: " + ", ".join(errored)` with each folder's Syncthing error text); companion/src/ccsync_companion/reporter.py:792-808 (sent verbatim)
- What: B6/SYS-3 turned every other report ceiling into truncation, because a raising cap fires before the route body and drops the lanes, presence, alarms and the command reply along with the long string. `LaneReportIn` was never converted, and it is not a tolerant section. On the companion side, lane C's `last_error` is an unbounded join with one entry per ticked or borrowed folder, each carrying Syncthing's own error text. `_fit_payload` sheds manifests and trees but never touches the lanes.
- Failure scenario: An editor with about 15 folders (ticked plus shared libraries) has every folder in error at once. Two realistic ways: the external sync drive is pulled, or a mass "folder marker missing (this indicates potential data loss, search docs/forum to get information about how to proceed)". The joined `last_error` passes 2000 chars. Every report, heavy or light, now 422s until the error changes. The machine drops off the fleet grid while it is in the state an admin most needs to see, and the halt, pushed updates, file-move commands and job cancels stop reaching it. The reporter logs it as an ordinary failure streak.
- Evidence: probe p3 (a 2001-char `last_error` and a 501-char `detail` are each rejected by `ReportIn`). The companion has no `[:2000]`/`[:500]` on either field (grep over sync/*.py and reporter.py). The syncthing-lane joins are cited above.
- Ledger: new (same shape as B6 / SYS-3, on the one model they missed)
- Suggested fix: add `_bound_to_field_caps` as a `mode="before"` validator on `LaneReportIn`, `TransferIn` and `CompletedIn` (and on `MediaClipIn`). Also cap `last_error`/`detail` in the reporter's lane dict, so a dashboard older than the fix is safe too.

### bug-wire-4 - `/verify` builds its upgrade offer without the arch, the machine or the withheld reason, and `sign_in` adopts it as if it were a report reply
- Severity: low
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/api.py:2232 (`_upgrade_info(conn, platform, version, getattr(payload, "arch", None))`, where `VerifyIn` declares no `arch` and no `withheld` sink is passed); companion/src/ccsync_companion/identity.py:320-328 (verify body carries no `arch`); companion/src/ccsync_companion/app.py:6505 (`self.upgrade.note_report_response({"upgrade": self.identity.last_upgrade_info})`)
- What: This one path to the offer has three gaps. (a) `arch` is never sent or declared, so `_arch_matches(record, "")` is True and an Intel Mac is offered the arm64 build REL-16 exists to withhold; `_accept_offer` deliberately leaves arch to the dashboard. (b) There is no editor or machine, so a staged build pushed to this one computer (CR-191) is replaced by the channel's current build. (c) The synthetic `{"upgrade": None}` dict has no `upgrade_none_reason`, so `note_report_response` takes the comp-ytdl-jobs-1 exit and `_clear_refusal()` runs, the very case comp-app-3 closed for the report reply.
- Failure scenario: An editor signs in on an Intel Mac. Until the first report replaces the offer, the tray shows "Update available". A click downloads the arm64 bundle, verifies it, swaps it in, fails to exec it, and the crash-loop revert runs. On any machine with a standing refusal of a withheld build (for example one the vendor recalled), signing in clears the refusal, the `upgrade_refused` alert and the fleet chip. comp-app-3's comment says a refusal cleared this way can never be restored.
- Evidence: code read of the three sites above. `_arch_matches` docstring: "A machine that reports no arch is likewise offered everything".
- Ledger: related to REL-16 and comp-app-3 (both FIXED on the report path only)
- Suggested fix: send `arch` in the verify body and declare it on `VerifyIn`. Pass a `withheld` list and echo `upgrade_none_reason` from `/verify`. In `sign_in`, hand `note_report_response` the whole verify result (or skip the call when the verify carried no key), not a dict built without that key.

### bug-wire-5 - `standins_known` is never sent empty, so a companion keeps the last non-empty set of stand-ins for the life of the process
- Severity: low
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/api.py:9949-9952 (`if known: result["standins_known"] = {"rels": known}`); companion/src/ccsync_companion/proxy_relink.py:449-482 (absent key = change nothing), :574-581 (True is conclusive)
- What: The reply-builder comment says "an empty list is sent for the same reason, so the two shapes cannot be confused", but the code sends the key only when the list is non-empty. The companion reads an absent key as "this dashboard does not know" and keeps `_FLEET_STANDINS` and `_FLEET_KNOWN = True`. When the fleet's last stand-in is upgraded (`record_standins_placed` replaces the per-machine picture, so `broll_standins` empties), every running companion keeps answering True for the old rels.
- Failure scenario: The fleet's stand-ins are all upgraded to real editing proxies and the dashboard's set goes to empty. The wired rig, still holding the last set, treats those archive clips as "born from a stand-in": `_geometry_disagrees` returns True with no probe, a ReplaceClip on its own path goes through `replace_clip`, and a positive verdict is stored for those bytes. This repeats after every tray restart until the set happens to go non-empty again.
- Evidence: code read, dashboard lines 9939-9952 against their own comment and against `note_fleet_standins`.
- Ledger: new
- Suggested fix: always send `standins_known: {"rels": known}`, empty list included, as the comment says.

### bug-wire-6 - `_queue_file_move_answer` appends outside the lock it was given
- Severity: low
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/app.py:8253-8268
- What: res-companion-5 added `_file_move_answers_lock` so the reporter's swap in `_file_move_results` cannot interleave with a queue. Only the filter-assign is inside the `with`. The `self._file_move_answers.append(answer)` runs after the lock is released, and the watcher thread (`_relink_pending_moves`, line 8394) queues concurrently with the reporter thread's swap.
- Failure scenario: the watcher thread loads `self._file_move_answers` (list L), then the reporter swaps L out and copies it into the payload, then the watcher appends to the orphaned L. The answer is lost. The same happens when the reply path's filter replaces L between the watcher's attribute load and its append. This is the exact race the lock's comment describes.
- Evidence: code read. The `with` block ends at line 8255 and the append is at 8268.
- Ledger: related to res-companion-5 (FIXED; the fix is incomplete)
- Suggested fix: build `answer` first and do the filter plus the append in one `with` block.

### bug-wire-7 - A computer whose hostname is not Latin-1 cannot make any b-roll or music ingest fleet call
- Severity: low
- Confidence: PLAUSIBLE
- Where: companion/src/ccsync_companion/broll_ingest.py:400-406 (`"X-CCSync-Machine": self.deps.machine`) with `default_request` at :244
- What: http.client encodes header values as Latin-1, so a hostname with a character above U+00FF raises `UnicodeEncodeError` inside `urllib` before a socket opens. Every FleetClient call carries the header, claim included. The same name travels fine in the JSON body of the report and the jobs routes, so the machine looks healthy everywhere else.
- Failure scenario: A Windows machine named in Chinese (this studio is in Taiwan and has CJK project and person names) starts an ingest from the b-roll or music page. The claim raises, the loopback answers a failure, and nothing on the fleet page says why.
- Evidence: probe p4 (`UnicodeEncodeError` on a `剪輯-PC` header). How common such hostnames are in the fleet is not verified.
- Ledger: new
- Suggested fix: send the header percent-encoded (and decode it in `routes_fleet`), or drop the header and compare against the machine named in the claim body.

## Coverage note
Not reached: the ytdl executor to routes_fleet wire in depth (only its identity check), the music ingest client beyond its identity and cancel handling, `project_setup.note_report_response`, `_register_machine` rename adoption, the halt reader on the companion, the resolve-undo ledger internals, and the Timeline Cards engine side of `/agent/*` (another repo). The loopback CORS/Host/origin envelope was read and looked consistent. One thing I did not treat as a finding: `origins_for_url` keeps an explicit default port (":443"/":80"), which a browser's Origin never carries, but no config in the tree writes one.

## OUT OF TERRITORY
- companion/src/ccsync_companion/jobs_runner.py:795: `_claim` pops `_claim_ids` before `_call`, so a transport failure on a forced claim drops the forced ids until the next report refills them (harmless, one cycle).
- dashboard/src/ccsync_dashboard/db.py:10269 `queued_jobs` LIMIT 200 is shared by the offer and the claim; with more than 200 queued higher-priority jobs a machine can take nothing past the 200th (theoretical at current fleet size).
