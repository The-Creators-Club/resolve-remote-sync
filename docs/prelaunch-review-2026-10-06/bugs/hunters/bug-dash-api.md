# bug-dash-api - dashboard api.py: route auth, validation, idempotency, report ingestion, reply commands, packages

Pre-commercial-launch bug hunt, 2026-10-06, working tree at HEAD 08b40eb plus the uncommitted changes (api.py's only diff is the `groups` key on `GET /admin/alerts`).

**Covered.** api.py lines 1-330 (credentials, account gate), 1575-1700 (health), 2075-2960 (read views, login, verify, selection read/tick/untick), 3003-3400 (links gate, file moves, undo, reissue), 3600-3830 (links, `_require_admin`, project-roots, tree validation), 3926-4200 (create, archive, link), 4581-5300 (users create, password, suspend, SSH-key submit and approve, delete everywhere), 5437-6130 (keys, sessions, report tokens, fleet halt, per-machine commands, copy-plan, device approve), 6130-6260 and 6444-6620 (package helpers, `_upgrade_info`), 6780-7480 (packages view, publish, current, roll back, delete, download), 7777-7900 (`_register_machine`), 9900-11360 (ReportIn, the whole report handler and reply, diagnostics), 11440-12267 (alerts, recovery, resolve undo, the whole fleet job API, locate).

**Callees followed.** app.py csrf_gate, login_gate, the exemption lists and body limits; db.upsert_machine, release_device_id_elsewhere, forget_editor, suspended_editors, stamp_report_refused, record_diagnostics, prune_companion_packages, pending_file_moves; collector._run_enforce's device mapping; jobs.matches_target; companion job_paths and upgrade.offer_label.

**Probes run** (dashboard venv, scratchpad only, no Tk, collector start stubbed):
1. TrueNAS-fake smb site: suspend an editor, delete the editor, then report again with the shared token and their identity token.
2. A local-auth site with real random secrets and DASH_DEV_INSECURE unset: a logged-in admin's cookie plus a foreign `Origin` header, POSTed to the package routes and to a non-exempt control route.
3. Two editors: the second reports the first's Syncthing device id.
4. `_validate_tree_part` against Windows-invalid names, plus `mkdir` of the same names on this Windows host.

**Checked against.** KNOWN_BUGS.md (through CR-361), docs/bug-hunt-2026-09-24 (this lens's previous findings bug-dash-api-1..4 are all FIXED in the tree, including their owed halves in nas/synology.py and ui.py) and docs/COMMERCIAL_READINESS.md.

**Not covered.** The view builders at 330-1575 (only the scoping helpers were read), build_queue_view internals, the SyncGuardIn and flatten_* models between 7480 and 9900, forget_machine_everywhere, `_command_delivery` beyond its first screen, and setup_routes (it lives in another module).

---

### bug-dash-api-1 - Deleting an editor on an smb site lets their computers straight back in, and erases a suspension on the way
- **Severity:** high
- **Confidence:** CONFIRMED (probe 1)
- **Where:** dashboard/src/ccsync_dashboard/api.py:228-266 (`_account_refusal`), 10144-10260 (`api_report` auth), 5178-5300 (`delete_user_everywhere`); db.py:2803 (`suspended_editors` reads `known_editors`), db.py forget_editor (deletes the `known_editors` row)
- **What:** on `DASH_AUTH_METHOD=smb` (the shipped mode), `_account_refusal` checks suspension and nothing else. Suspension is stored on the `known_editors` row, and `forget_editor` deletes that row when a user is deleted. `delete_user_everywhere` revokes sessions and per-editor `cce1.` tokens. It cannot revoke the shared fleet token (enabled by default) or the identity token, which has had no expiry and no server-side row since CR-86. The next report from the deleted person's companion therefore passes every gate. `record_known_editor` re-registers the person, unsuspended, `_register_machine` puts their computer back in the registry, and the reply carries commands as normal. The same credential also opens `/files/locate` (the whole tree's inventory, by name and size), `/jobs/claim`, `/diagnostics`, `/ssh-key`, `GET /selection`, the full `/health` body and package downloads.
- **Scenario:** an admin suspends a freelancer who has left, then deletes them. Probe output: `report while suspended 401`, `delete 200`, `report after delete 200`, `locate 200`, `claim 200`, and `known_editors` holds `ruskin` again with `suspended_at=None`. The person who was removed is back on the fleet grid within 30 s. Their machine can query where any file is on the server and claim fleet jobs. If they are later re-added to the editors group, or a new hire is given the same username, their old computer is trusted without anyone approving it.
- **Recommendation:** add a durable "removed" tombstone that `delete_user_everywhere` writes and `_account_refusal` reads on every auth method, and keep the suspension fact out of the row that `forget_editor` deletes. Longer term this is trust-model-1: give each identity token a server-side row so delete, disable and password reset can revoke it, and retire the shared token on new installs (default `DASH_SHARED_REPORT_TOKEN_ENABLED=0` with the cce1 pairing flow).
- **Known:** trust-model-1 (docs/bug-hunt-2026-08-21.md, KNOWN_BUGS.md:2579, and the "trade this accepts" paragraph of CR-86) is OPEN. The deletion-erases-suspension half is new.

### bug-dash-api-2 - The package routes "make current" and "roll the fleet back" are CSRF-exempt session routes
- **Severity:** medium
- **Confidence:** CONFIRMED (probe 2)
- **Where:** dashboard/src/ccsync_dashboard/app.py:234 (`_CSRF_EXEMPT_PREFIXES` contains `/api/v1/admin/packages/`) and 1083 (an exempt path returns before the Origin check); api.py:7091 (`api_set_current_package`), 7281 (`api_roll_fleet_back`)
- **What:** the comment above the exemption list says only bearer-token routes are exempt. These two routes authenticate with the admin's session cookie (`_require_admin`). The publish tools (`tools/publish_package.py`, `build_editor_package.ps1`) also use a session cookie. The prefix exemption skips both the CSRF token and the Origin check. The routes are POSTs with every argument in the query string, so a "simple" cross-origin request sends no preflight. `force=1&confirm=<version>` is the soak gate's whole override, and an attacker can supply it.
- **Scenario:** with a real secret and a tracked session, a POST carrying `Origin: http://evil.example` reached the handler (`404 no published windows companion package`), while the control route `/api/v1/jobs/1/cancel` answered `403 missing or bad CSRF token`. In a browser, SameSite=Lax holds the cookie back from cross-SITE POSTs only. Every port on the dashboard's LAN IP counts as the same site, and so does every host under the customer's `<tailnet>.ts.net` (ts.net is a public suffix, so the tailnet name is the site). Any page an admin opens on another tailnet device, or on another app on the NAS IP, can make an old signed build current fleet-wide past the soak gate, or push a downgrade to every machine on a version (`roll-fleet-back` uses `commands.upgrade`, which bypasses "newer only").
- **Recommendation:** remove `/api/v1/admin/packages/` from the exemption list. The publish tools already get `csrf` in the `/api/v1/login` reply (api.py:2289) and only need to send it as `X-CSRF-Token`. If an exemption must stay for one release, narrow it to `PUT` and keep the Origin check for the POSTs.
- **Known:** new. The 09-24 hunt flagged the `/api/v1/selection/` prefix only, which is harmless because those routes are PUT/DELETE and need a preflight.

### bug-dash-api-3 - Any fleet member can take another editor's Syncthing device by reporting its id, and the enforce cycle then reshares that computer
- **Severity:** medium
- **Confidence:** CONFIRMED (probe 3, plus a read of collector._run_enforce)
- **Where:** dashboard/src/ccsync_dashboard/api.py:7896-7906 (`_register_machine` -> `db.release_device_id_elsewhere`); db.py:5215-5237; collector.py:1484-1489 and 1556-1580
- **What:** `syncthing_device_id` in a report is self-asserted. `release_device_id_elsewhere` moves the id to the reporting row from every other row, across editors, with no check that Syncthing's own device label (`id_to_editor`) names the reporting editor. The enforce cycle maps devices through `machines.syncthing_device_id`.
- **Scenario:** probe 3: bob reports device B, then alice reports device B. The table now reads `bob/BOB-PC device=None` and `alice/ALICE-PC device=B`, and `machine_by_device_id(B)` returns alice. On the next enforce pass, bob's computer is shared alice's ticked projects. Bob's own projects lose their device, because B is now "mapped" and so is excluded from bob's unmapped fallback, and they are unshared under the blast brake. Bob's companion claims the id back on its next report, so a malicious or misconfigured companion that keeps sending the id makes the shares flap every cycle. Each flap restarts the folder on bob's machine. A disk image cloned between two editors' PCs, with the same Syncthing key, does the same thing without anyone intending it.
- **Recommendation:** accept a reported device id only when Syncthing's device list has no label for it or labels it as the reporting editor (`id_to_editor`). Never release an id from a different editor's row. On a cross-editor collision, raise a notice instead (the `duplicate_machine_id` pattern).
- **Known:** new. data-model-5 (2026-08-21) made the release deliberately, and only for the same-editor case.

### bug-dash-api-4 - NEW PROJECT, USE THIS FOLDER and file moves accept names Windows cannot create, so Windows editors cannot sync the project
- **Severity:** medium
- **Confidence:** CONFIRMED (probe 4)
- **Where:** dashboard/src/ccsync_dashboard/api.py:3772-3787 (`_validate_tree_part`), used by `create_tree_project` (3951), `_safe_rel`, `_clean_project_rel` (file moves) and `adopt_folder`
- **What:** the validator refuses slashes, a leading `.`, `..` and control characters. It accepts `: * ? " < > |`, trailing dots and spaces, and reserved device names (`CON`, `NUL`, `COM1`). The NAS (Linux) creates them without complaint. The companion builds `local_root/Projects/<rel>` from the raw rel (sync/repath.py, sequencer.py), and nothing in its sync path sanitises a name for Windows.
- **Scenario:** an editor on a Mac presses NEW PROJECT -> `2026 / Shoot: Day 1`. The dashboard answers ok and the folder and marker are created on the NAS. On every Windows editor's machine, `mkdir 'Shoot: Day 1'` fails with `[WinError 267] The directory name is invalid` (probe), so lane B and lane C cannot place the project at all. `Final.` is created on Windows as `Final`, so the local path no longer matches the rel the dashboard knows, and repath, the manifest and presence all disagree with the server. rclone instead maps `:` and `?` to fullwidth characters (GOTCHAS on rclone fullwidth), which gives a third spelling of the name. An admin's file move can introduce the same names into an existing project.
- **Recommendation:** refuse, with an explanation the editor can act on, any segment containing `<>:"|?*`, any segment ending in `.` or a space, and any Windows reserved stem, in `_validate_tree_part`. That one function covers create, link, move and `_safe_rel`. Also report a Windows-invalid name on an existing folder (the collector's provision scan) as a notice.
- **Known:** new.

### bug-dash-api-5 - A shared-token holder can stamp "being turned away" on any editor's computer and set off the report_refused alert
- **Severity:** low
- **Confidence:** CONFIRMED (code read)
- **Where:** dashboard/src/ccsync_dashboard/api.py:10196-10220 (`_refuse_identity`, then `db.stamp_report_refused`); db.py:5668
- **What:** `_refuse_identity` stamps `machines.report_refused_at/reason` on the `(editor_name, machine)` named in the unverified body. It runs after the shared-token check has passed and the identity check has failed, so an identity is not required to reach it. The body's names are trusted for that one write.
- **Scenario:** any companion holding the shared token (every editor, and, per bug-dash-api-1, anyone deleted) POSTs a report with `editor_name=bob, machine=BOB-PC` and no identity. Bob's row shows refused with the reason "no computer identity token was sent", and the `report_refused` alert emails the admin a false incident about the secret rotation. Bob's next genuine report clears it, so a loop keeps it flapping.
- **Recommendation:** stamp only when the presented credential already proves the editor (a cce1 token bound to that editor), or when an identity token verifies for that same editor and fails only on the account gate. Otherwise refuse without writing.
- **Known:** new (DASH-2 introduced the stamp).

### bug-dash-api-6 - The job claim trusts the machine name in its body, so a hostname-only target_machine can be claimed by any editor
- **Severity:** low
- **Confidence:** CONFIRMED (code read)
- **Where:** dashboard/src/ccsync_dashboard/api.py:12104-12150 (`api_claim_job`: `machine = payload.machine.strip()`, never checked against `db.machines_of(editor)`); jobs.py:478-483 (`matches_target`: a target without `/` compares the hostname only)
- **What:** the identity token binds the editor and nothing binds the machine. A job aimed at a bare hostname (the shape the Timeline Cards picker and `tools/jobs.py` both produce) matches any claimant that names that hostname, under any editor. The per-machine cooldown and the "one job at a time" policy are keyed on the same unverified string.
- **Scenario:** an admin aims a whisper job at `EDIT-SUITE`. Alice's laptop, misconfigured or deliberately renamed, claims with `machine=EDIT-SUITE` and runs the job against her own mounts. Alternatively, a machine that fails jobs evades its cooldown by claiming under a fresh name.
- **Recommendation:** refuse a claim whose `machine` is not registered for the verified editor (`db.machines_of`). Store and match targets as `editor/machine`, which `matches_target` already supports.
- **Known:** new.

### bug-dash-api-7 - On an smb site a suspended editor can still sign in and write into the NAS tree
- **Severity:** low
- **Confidence:** CONFIRMED (code read)
- **Where:** dashboard/src/ccsync_dashboard/api.py:2255 (`api_login` has no account gate), 4107 (`api_create_project`), 4177 (`api_link_folder`), 3699 (`api_set_project_root`); the suspend route's docstring at 4880
- **What:** the docstring states that suspension is independent of sign-in. On local sites DISABLE covers sign-in, but smb sites have no equivalent control short of DELETE. A suspended person keeps a working dashboard session, or can make a new one. With it they can create project folders and markers on the NAS (`mkdir` plus `write_marker` through the container's mount), adopt folders, first-claim Resolve project roots and edit their own plan.
- **Scenario:** the owner suspends a freelancer "until next month". During that month the freelancer can still create `2026/<anything>` folders on the shared tree from the dashboard, and those projects appear for every editor.
- **Recommendation:** have every write route that needs only a session (create, link, project-roots, tick) refuse when `_account_refusal` answers. Optionally revoke the person's sessions on suspend for smb sites.
- **Known:** DCORE-4 made "independent on purpose" a design decision. The write-through-the-dashboard consequence is not recorded.

### bug-dash-api-8 - A file move can overwrite a file that appears at the destination after the exists() check
- **Severity:** low
- **Confidence:** PLAUSIBLE
- **Where:** dashboard/src/ccsync_dashboard/api.py:3207-3226 (`move_project_files`: `dest.exists()`, then `record_file_move` and a commit, then `src.rename(dest)`); 3151 (`_move_proxy_siblings`: `target.exists()`, then `candidate.rename(target)`)
- **What:** on the NAS (Linux), `rename(2)` silently replaces an existing file. The window between the check and the rename includes a SQLite commit, which can wait up to the 5 s busy timeout under exactly the contention CR-351 describes. Meanwhile editors' lane A and Syncthing write into the same tree.
- **Scenario:** an admin moves `A/A001.mov` into `B/` while an editor's lane A is uploading the same card's `B/A001.mov`, a different clip with the same camera filename. The upload lands during the commit, the rename replaces it, and that original is gone from the server.
- **Recommendation:** use `os.link` plus `unlink` (fails with EEXIST) or `renameat2(RENAME_NOREPLACE)` through ctypes, or at least re-check `dest.exists()` immediately before the rename and treat a collision as a refusal. Apply the same change to the proxy rename.
- **Known:** related to CR-333 (OPEN), which is the companion side of the same race, but this server-side overwrite is not recorded.

### bug-dash-api-9 - Per-machine storage bounds are keyed on a machine name the caller chooses
- **Severity:** low
- **Confidence:** CONFIRMED (code read)
- **Where:** dashboard/src/ccsync_dashboard/db.py:5983-6008 (`record_diagnostics` keeps N per `(editor, machine)`); api.py:11183 (`/diagnostics`), 10144 (`/report` creates `machines`/`machine_state`/lane rows for any name); db.py:2413 (`add_pending_ssh_key`, no per-user cap)
- **What:** each bound is per machine name, and a companion can invent machine names freely. The data lives on the same dataset as the SQLite database.
- **Scenario:** a broken or hostile companion loops `/diagnostics` with a new `machine` every call: 256 KB times N rows, unbounded, filling `/data` and with it the database. A smaller version of the same thing applies to report rows (every invented name becomes a fleet-grid computer) and to pending SSH keys (one row per distinct key).
- **Recommendation:** cap per editor as well (total diagnostics bytes, pending keys, and machines a report may create without an admin seeing a notice), and refuse diagnostics for a machine that is not in the registry.
- **Known:** new.

### bug-dash-api-10 - Publish-time prune can delete a build that a machine has a pending push for
- **Severity:** low
- **Confidence:** CONFIRMED (code read)
- **Where:** dashboard/src/ccsync_dashboard/db.py:5021 (`prune_companion_packages`: keeps only current plus the 2 newest non-current); package_store.py:535 (prune on by default, including the unattended vendor-feed publish); api.py `_machine_can_be_offered`
- **What:** prune never asks whether any `update_requested_version` names the row it is about to delete.
- **Scenario:** an admin stages 0.9.85 and pushes it to one canary. The vendor feed then auto-publishes 0.9.86 and 0.9.87 as staged builds. Prune deletes 0.9.85 while the canary's push still names it. The report path then withholds the command with the generic reason "the update you were sent cannot be installed on this computer", and the push sits on the Packages page for 14 days with a reason that is not the real one.
- **Recommendation:** exclude from prune any version named by a pending machine push or by an unfinished `roll_fleet_back`. Alternatively, have prune clear those pushes and name them in the publish answer.
- **Known:** new.
