# bug-dash-api - dashboard/src/ccsync_dashboard/api.py: routes, auth, validation, report ingestion
Files read (approximate coverage): api.py lines 1-420, 1247-1360, 1854-1920, 2030-3830, 4208-4610, 4856-5500, 5495-5915, 6124-6760, 6756-7165, 8977-9060, 9154-11111 (roughly 55% of the file, weighted to auth gates, the report path and the reply's commands, packages, file moves, links, project create/adopt, users/keys/sessions, jobs, diagnostics, recovery). Callees followed: app.py login_gate and CSRF exemptions, db.upsert_project / archive_project / create_job / request_machine_update / machine_update_request, provision.write_marker, local_users.set_password, nas/truenas.py and nas/synology.py create_or_update_editor, onboarding/onboard.py _offer_ssh_key, companion file_moves.py proxy helpers.
Tests/probes run: two ad-hoc snippets from the dashboard venv (scratchpad only): `_move_proxy_siblings` on a same-folder rename and a case-only rename; `create_tree_project` / `adopt_folder` against an archived project on a migrated temp DB.

## Findings

### bug-dash-api-1 - Approving a second computer's SSH key erases the first computer's key on the NAS
- Severity: medium
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/api.py:4555 (approve_pending_ssh_key); dashboard/src/ccsync_dashboard/nas/truenas.py:266 and nas/synology.py:218
- What: `approve_pending_ssh_key` installs the offered key through `nas.create_or_update_editor(username, key_text, None)`. Both NAS backends REPLACE the account's key with the one they are handed: TrueNAS PUTs `sshpubkey` to that single key, and Synology writes `authorized_keys` with `printf '%s\n' {key} > ...; mv -f`. Local mode (`local_users.add_ssh_key`) appends, so only the shipped NAS modes are affected. The same file's own comment at api.py:4258-4264 says "both backends write the key they are handed", which is why a blank key is refused for an existing account. The approve path has no equivalent guard for a non-blank key that is not the existing one.
- Failure scenario: an editor with one working computer (key K1 on the NAS) runs the wizard on a second computer, the multi-machine shape MULTI_MACHINE_PLAN.md supports. `onboard._offer_ssh_key` posts K2 to /api/v1/ssh-key. The admin presses the one-click approve on Users. The NAS account now holds only K2, and computer 1's lane A upload and lane B proxy download start failing SFTP auth. Nothing on the approve row warned that a key would be replaced.
- Evidence: read approve_pending_ssh_key (api.py:4532-4573), truenas.create_or_update_editor (the existing-account branch PUTs `{"sshpubkey": ssh_pubkey, ...}`), the synology `_install_authorized_keys` script (lines 209-225, `>` then `mv -f`), and onboard.py:1105-1133 (every install offers its own freshly generated key).
- Ledger: new
- Suggested fix: on the NAS backends, merge the approved key with the account's current keys (read `sshpubkey` / authorized_keys, append if absent), or at minimum make approve refuse, or require confirmation, when the account already has a different key, naming the computer that would lose access.

### bug-dash-api-2 - A file move that renames the file leaves its proxy under the old name; a same-folder rename reports PARTIAL with a false reason
- Severity: medium
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/api.py:2770-2806 (_move_proxy_siblings); the two-sided mismatch is at companion/src/ccsync_companion/file_moves.py:317-340 (rename_proxy_siblings_case_only)
- What: `FileMoveIn.to_path` is "folder or full path inside it", so a move can rename, and undo relies on that (api.py:2972-2980). But `_move_proxy_siblings` always moves each proxy to `dest.parent/Proxy/<candidate.name>`, the proxy's OLD name. For a same-folder rename the target is the proxy itself, `target.exists()` is true, and the proxy is reported as "something is already at the destination", so the move is stored as `partial` with a misleading detail and the HTTP answer is 207. For a rename into another folder the proxy moves but keeps the old stem, so Resolve's `Proxy/<stem>.*` auto-link no longer pairs it with the renamed original. For a case-only rename the companion side DOES rename the local proxy to `dest.stem` (its docstring says "The dashboard renames the proxy on the NAS with the original"), so the NAS keeps `Proxy/A001.mov` while the editor's disk has `Proxy/a001.mov`. Lane B then sees one proxy missing and one extraneous, downloads the first, trashes the second, and charges the delete to the breaker.
- Failure scenario: an admin renames `A/A001.mov` to `A/Renamed.mov` from the project page. The original is renamed. The proxy stays `A/Proxy/A001.mov`, the move shows PARTIAL "these proxies did not move: A001.mov (something is already at the destination)", and every machine's Resolve loses the proxy link for that clip.
- Evidence: probe from the dashboard venv. `_move_proxy_siblings(A001.mov -> Renamed.mov)` returned `(0, ['A001.mov (something is already at the destination)'])`, and `A001.mov -> a001.mov` returned the same, with the proxy still at `Proxy/A001.mov` in both cases.
- Ledger: new (related to the comp-sync / regression-6 case-only work on the companion side)
- Suggested fix: target `dest.parent / "Proxy" / (dest.stem + candidate.suffix)`, skip when that is the candidate itself, and route a case-only collision through a temporary name as the companion does. Also fold the stem compare through NFC, like the companion's `_stem_key`.

### bug-dash-api-3 - Creating or linking a project over an ARCHIVED project answers ok, and the project stays archived and invisible
- Severity: low
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/api.py:3614-3656 (create_tree_project), 3659-3731 (adopt_folder), 3528-3552 (_register_project)
- What: neither path looks at `archived_at`. Archiving keeps the folder and its marker (DCORE-5), so NEW PROJECT with the same parent and name takes the "marker already carries this slug" convergence branch, and USE THIS FOLDER adopts the marker. Both reach `db.upsert_project`, which deliberately keeps an archived row at `active=0`. The route answers `{"ok": true, "slug": ...}` and writes a `project.create` audit row, and a supplied `resolve_project` is sticky-mapped onto the archived slug. The project is still missing from every tick list, and `PUT /selection` 404s with "unknown or inactive project".
- Failure scenario: an admin archives `2026/Shoot`. An editor, not knowing that, presses NEW PROJECT -> 2026 / Shoot and is told it was created. Nothing appears, ticking it fails, and their companion's Resolve project is now permanently mapped to a slug nobody can see.
- Evidence: probe on a migrated temp DB. Create, archive, then create again returned `{'slug': '2026-shoot', ...}` with the row still `active=0, archived_at=<ts>`. `adopt_folder` behaved the same.
- Ledger: new
- Suggested fix: in both helpers, refuse (409/422) when the slug's row has `archived_at`, with a sentence that names UNARCHIVE on the project page as the next action and says who can press it.

### bug-dash-api-4 - An admin's password reset on a local account leaves every existing session of that account signed in
- Severity: low
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/api.py:4298-4304 (api_admin_set_password, local branch)
- What: the local branch calls `local_users.set_password` (an UPDATE of `password_hash` and nothing else) and commits. Sessions are server-side rows validated without reference to the password (see the dash-core-3 note on disable), so a reset keeps every open browser session alive for up to 7 days. The DISABLE and DELETE doors revoke through `_purge_user_credentials`, but the reset door does not.
- Failure scenario: an admin resets a local editor's password because the old one leaked. Whoever signed in with the leaked password keeps a working dashboard session. They can still tick and untick projects, create projects and read the fleet, until that session expires or the admin also finds and presses sessions/revoke.
- Evidence: read api.py:4282-4317, local_users.set_password (local_users.py:223-236), and the revocation reasoning in api_admin_disable_user's docstring (api.py:4339-4350).
- Ledger: new (local mode only, which is not in the field yet)
- Suggested fix: after the commit, revoke that user's sessions through `auth.session_store(request).revoke_user(username, by=f"admin:{admin}")`, as disable does, and say how many were revoked in the answer.

## Coverage note
Not read in depth: the view builders at api.py:284-1180 (build_transfers_view, build_editors_view internals; the scoping helpers were read), build_queue_view, the SyncGuardIn and flatten_* models at 7165-8960, build_packages_view, delete_user_everywhere / forget_machine_everywhere (4605-4830), and `_command_delivery`. Checked and found sound: the version-tuple handling of two-digit minors and `+dirty`, the rollback push direction (from_version is derived in db), the fleet-job gates, package path handling (server-chosen filename, version regex), `_safe_rel` traversal guard, and the scope redaction of the fleet view.

## OUT OF TERRITORY
- dashboard/src/ccsync_dashboard/app.py:234: `/api/v1/selection/` is CSRF-exempt as a prefix, which also covers the session-only PUT (tick) route. Only SameSite=Lax protects it, while the comment reasons only about token-bearing companion callers.
- dashboard/src/ccsync_dashboard/api.py:10150-10156 (logged here for completeness, low): the docstring says an unknown diagnostics trigger is "Recorded as `other`", but `trigger or "other"` stores the unknown word itself.
