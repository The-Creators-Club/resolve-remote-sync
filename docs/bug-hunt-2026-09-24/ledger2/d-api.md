# Wave 2 ledger - group d-api (api.py)

Builder d-api, chunk 1 of 1, 2026-09-25. All fixes in
`dashboard/src/ccsync_dashboard/api.py`; all regression tests in
`dashboard/tests/test_bug_hunt_2026_09_24_w2_d-api.py` (22 tests). Against a
scratch copy of the package with HEAD's api.py swapped in, 16 of them fail and
the 3 that pass are guards on behaviour that must not change (a key onto an
account with none, a plain move keeping the proxy's name, a real collision
still refused).

Deploy order for the whole group: dashboard alone, no schema change. Every
new reply key (`upgrade_none_reason` on /verify, `standins_known` sent empty)
is one a 0.9.77 companion either already reads with the right meaning or
ignores; `VerifyIn.arch` is optional and nothing sends it yet.

## bug-dash-api-1 - Approving a second computer's SSH key erases the first computer's key on the NAS
- Status: PARTIAL (rest OWED)
- Verified as: CONFIRMED medium by med-05. Re-read `approve_pending_ssh_key` (api.py), `truenas.create_or_update_editor` (PUTs `sshpubkey` to exactly what it is handed) and synology's `_INSTALL_KEY_SCRIPT` (`printf > tmp; mv -f authorized_keys`). Both replace.
- Fix: new `_key_identity` + `_install_nas_key_keeping_others` (beside `PendingKeyIn`), called from `approve_pending_ssh_key` in place of the bare `create_or_update_editor`. It uses a backend's `add_editor_ssh_key(username, key)` when there is one; otherwise it reads the account's `sshpubkey` text through `find_user` (TrueNAS carries the key text, one key per line, written out as authorized_keys whole), keeps every key line, adds the approved key unless the same type+body is already there (comment ignored), and writes the merged list. On a backend that shows no key text (DSM's `find_user` never does), it logs that the approved key becomes the only key and behaves as before.
- Regression test: `test_approving_a_second_computers_key_keeps_the_first`, `test_approving_a_key_already_installed_does_not_duplicate_it`, `test_a_backend_that_can_append_is_asked_to` (fail on HEAD: the write is K2 alone); `test_approving_on_an_account_with_no_key_installs_just_that_key` (guard).
- Tests run: see "Tests run" at the end (all 19 new tests pass; affected existing suites green after the two test edits named there).
- Skew / deploy order: dashboard only. Nothing on the wire changes.
- OWED: d-ops, `dashboard/src/ccsync_dashboard/nas/synology.py`: add `add_editor_ssh_key(username, ssh_pubkey)` that APPENDS to `~/.ssh/authorized_keys` when that exact key (type+body) is absent (same refusals as `create_or_update_editor`, same tmp+mv, chown and chmod as `_INSTALL_KEY_SCRIPT`, and `cat` the old file into the tmp first). api.py already prefers that method when it exists, so no api.py change is needed. Optionally the same method on truenas.py (read `sshpubkey`, append, PUT) so the merge lives in the backend. Until then a DSM site still replaces on approve.
- Review round (2026-09-25, reviewer: PROBLEM, accepted): the merge kept an existing line only if `_key_identity` recognised it, and `_key_identity` goes through `looks_like_ssh_pubkey` / `SSH_KEY_PREFIXES`, so a hardware-key line (`sk-ssh-ed25519@openssh.com`, `sk-ecdsa-sha2-nistp256@openssh.com`), a certificate line (`*-cert-v01@openssh.com`) or any unlisted type was dropped on approve. Reproduced: the first cut writes only the recognised lines plus the new key. Fixed in `_install_nas_key_keeping_others`: every existing line that is non-blank, not a `#` comment and has at least two fields is kept VERBATIM (options prefix included); `_key_identity` is now used only for the duplicate check (the new key is always a listed type, validated at offer time, so an unlisted line can never be its duplicate). The two-field rule is what keeps DSM's `(installed)` marker (one field, `synology.find_user`) from being written back as a key; a one-field line cannot be an authorized_keys key since type and body are both required. New tests: `test_existing_key_lines_of_unlisted_types_are_kept_verbatim` (fails on the first cut: sk, cert and an options-prefixed line are all kept, in order, then K2), plus guards `test_the_dsm_installed_marker_is_not_written_back_as_a_key` and `test_a_key_already_installed_behind_options_is_not_duplicated`. Run: the d-api file 22 passed; against a scratch copy with the first-cut filter restored, 1 failed (the new test) and 21 passed; test_admin_users, test_admin_users_local, test_admin_users_partial_parity, test_nas_backend, test_synology_client 128 passed. Status stays PARTIAL: the DSM append is still owed to d-ops as written above.

## bug-dash-api-2 - A file move that renames the file leaves its proxy under the old name; a same-folder rename reports PARTIAL with a false reason
- Status: PARTIAL (rest OWED)
- Verified as: CONFIRMED medium by med-05. Re-read `_move_proxy_siblings`: the target was `dest.parent/Proxy/<candidate.name>`, so a same-folder rename targets the proxy itself (`exists()` true, PARTIAL with a false reason) and a cross-folder rename keeps the old stem.
- Fix: `_move_proxy_siblings` now targets `dest.parent/Proxy/<dest.stem><proxy suffix>`; skips when that is the candidate's own path (compared as text, because a WindowsPath compares case-folded); a target that exists and IS the candidate (case-only rename on a case-folding filesystem) goes through a staging name and is restored if the second rename fails; a real collision is still refused. Stems are matched through the new `_proxy_stem_key` (NFC then lower-case, the companion's `_stem_key`), so an NFD proxy name from a Mac is found. New `_same_proxy_file` (samefile, never raises).
- Regression test: `test_a_same_folder_rename_renames_the_proxy_and_is_not_partial`, `test_a_rename_into_another_folder_pairs_the_proxy_with_the_new_name`, `test_a_case_only_rename_renames_the_proxys_spelling`, `test_an_nfd_stem_finds_its_proxy` (fail on HEAD); `test_a_plain_move_keeps_the_proxys_name`, `test_a_real_collision_is_still_refused` (guards).
- Tests run: see "Tests run" at the end (all 19 new tests pass; affected existing suites green after the two test edits named there).
- Skew / deploy order: dashboard only. With companions as they are, a cross-folder RENAME now leaves the NAS proxy at `Proxy/<new stem>` while the companion's `move_proxy_siblings` keeps `Proxy/<old stem>` locally; lane B then downloads the correctly named proxy and trashes the old one. That converges on the right state (it costs one proxy download per holding machine); before, both sides converged on a proxy Resolve could not pair. Case-only renames already matched the companion (`rename_proxy_siblings_case_only` renames to `dest.stem`), and now the NAS side agrees.
- OWED: c-sync, `companion/src/ccsync_companion/file_moves.py` `move_proxy_siblings`: target `target_dir / (dest.stem + candidate.suffix)` instead of `candidate.name`, as `rename_proxy_siblings_case_only` already does, so a renaming move does not cost each holding machine a proxy re-download and a lane B trash of the old name. Keep the "never overwrite" rule, and do NOT change the trash call site (`move_proxy_siblings(src, trash)` at ~:753, where `trash` has the source's own name, so it is unaffected).

## bug-wire-3 - Lane last_error/detail/current_project caps still RAISE, and the companion never caps them
- Status: PARTIAL (rest OWED)
- Verified as: CONFIRMED medium by med-08; its probe (`LaneReportIn(last_error='x'*2001)` -> string_too_long) repeated on HEAD's api.py by the regression test (a 422 of the whole report).
- Fix: a `mode="before"` `_bound_to_field_caps` model validator on `LaneReportIn`, `TransferIn`, `CompletedIn` and `MediaClipIn`, so their declared caps truncate like every other report section's since B6 / SYS-3. `name` keeps its min_length=1 refusal (an empty lane name is not a long one).
- Regression test: `test_a_long_lane_error_does_not_422_the_whole_report` (a 5000-char lane `last_error`, 900-char `detail`/`current_project`/transfer name: HEAD answers 422; now 200 with `last_error` stored at 2000 chars), `test_the_other_report_sub_models_truncate_too`. Existing tests EDITED because they pinned the defect: `test_hardening.py` (new `test_long_lane_and_clip_strings_truncate_rather_than_reject`; `test_report_fields_are_capped` keeps only the numeric cases) and `test_report_endpoint.py::test_report_transfers_list_is_capped` (257 transfers now 200).
- Tests run: see "Tests run" at the end (all 19 new tests pass; affected existing suites green after the two test edits named there).
- Skew / deploy order: dashboard only; fixes every companion in the field, which is the point.
- OWED: c-core, `companion/src/ccsync_companion/reporter.py` (~:807-809, the lane dict): cap `last_error` at 2000 and `detail` at 500 (and `current_project` at 512) before sending, so a dashboard OLDER than this fix (a customer who has not updated) cannot 422 a report on a long lane error. c-sync may also want `syncthing_lane.py`'s `", ".join(errored)` bounded to a count plus the first few folders, but the reporter cap is the one that closes the wire.

## bug-dash-api-3 - Creating or linking a project over an ARCHIVED project answers ok, and the project stays archived and invisible
- Status: FIXED
- Verified as: LOW, unverified by anyone before; verified here. `db.upsert_project` keeps an archived row at active=0 on purpose (`CASE WHEN projects.archived_at IS NULL THEN 1 ELSE 0 END`), `create_tree_project` takes the existing-marker branch and `adopt_folder` adopts the marker; neither read `archived_at`. The regression tests reproduce the ok answer on HEAD.
- Fix: new `_refuse_archived_project(conn, slug, rel)` raising `ProjectSetupError` ("<rel> is an archived project. An admin can put it back with [ UNARCHIVE ] under ARCHIVED PROJECTS on the SYNC PLANS page, and it keeps its folder, its files and its ticks"). Called in `create_tree_project` right after the slug is known (before any mkdir or marker write), in `adopt_folder` before it writes a marker on an unmarked folder, and in `_register_project` as the backstop for both (which also covers a marked folder being adopted). Both JSON routes turn it into a 422, and ui.py's two panels already render a `ProjectSetupError` as the panel's error line, so no ui.py change was needed. No em dash.
- Regression test: `test_new_project_over_an_archived_one_is_refused_and_names_unarchive`, `test_use_this_folder_on_an_archived_project_is_refused`, `test_an_unmarked_folder_whose_slug_is_archived_is_refused_before_the_marker` (all answer 200 on HEAD).
- Tests run: see "Tests run" at the end (all 19 new tests pass; affected existing suites green after the two test edits named there).
- Skew / deploy order: dashboard only.
- OWED: none.

## bug-dash-api-4 - An admin's password reset on a local account leaves every existing session of that account signed in
- Status: PARTIAL (rest OWED)
- Verified as: LOW, verified here. `local_users.set_password` updates `password_hash` only; `SessionStore.validate` never looks at the password; `api_admin_set_password` committed and returned. The test logs jsmith in, resets the password as owen, and on HEAD the session row still validates.
- Fix: new `revoke_sessions_after_password_reset(request, username, *, admin)` (after `api_admin_set_password`): after the commit, `session_store.revoke_user(username, by="admin:<a> (password reset)")`, keeping the admin's own current session when they reset their own password; never raises (the password has already changed). Called from both branches of `api_admin_set_password` (local and NAS, since an SMB-mode session is just as independent of the NAS password), and the answer now carries `sessions_revoked`. Report tokens are deliberately left alone: they authenticate a machine, not a login.
- Regression test: `test_a_password_reset_revokes_the_accounts_sessions` (on HEAD the session still validates and the answer has no `sessions_revoked`).
- Tests run: see "Tests run" at the end (all 19 new tests pass; affected existing suites green after the two test edits named there).
- Skew / deploy order: dashboard only.
- OWED: d-ui, `dashboard/src/ccsync_dashboard/ui.py` `partial_admin_set_password` (~:2856): the Users page's [ SET ] button is the door an admin actually uses, and it has the same defect in both branches. After each successful `conn.commit()` / `nas.set_known_password`, call `api.revoke_sessions_after_password_reset(request, username, admin=admin)` (the function returns the count; `admin` is `_require_admin_page(request)`'s return value), and add "and signed out N session(s)" to the `notice` when N > 0.

## bug-wire-4 - /verify builds its upgrade offer without the arch, the machine or the withheld reason, and sign_in adopts it as if it were a report reply
- Status: PARTIAL (rest OWED)
- Verified as: LOW, verified here. HEAD's `VerifyIn` declares no `arch`, so `getattr(payload, "arch", None)` is always None and `_arch_matches(rec, "")` offers everything; `_upgrade_info` is called with no `withheld`, so no `upgrade_none_reason`; companion `identity.py` sends no arch, and `app.py` `sign_in` feeds `{"upgrade": last_upgrade_info}` to `note_report_response`. All three gaps are real on the code as it stands. (b), the machine-targeted push, cannot be served at /verify at all: it has no machine.
- Fix: `VerifyIn.arch` declared (optional, truncated to 32 by a before-validator, a non-string reads as None: a sign-in never 422s on it); `api_verify` passes a `withheld` sink to `_upgrade_info` and puts `upgrade_none_reason` on the reply when a build exists and is being withheld, the report reply's shape exactly.
- Regression test: `test_verify_declares_arch`, `test_verify_passes_the_arch_and_a_withheld_sink` (on HEAD the arch is dropped and no reason is echoed).
- Tests run: see "Tests run" at the end (all 19 new tests pass; affected existing suites green after the two test edits named there).
- Skew / deploy order: dashboard first; the companion half is inert until then and harmless after (an older dashboard ignores `arch` in the body).
- OWED: c-core, `companion/src/ccsync_companion/identity.py` (the verify body, ~:320-328): send `"arch"` the same way reporter.py sends it on the report. c-app, `companion/src/ccsync_companion/app.py` `sign_in` (~:6505): do not build `{"upgrade": self.identity.last_upgrade_info}`; either pass the whole verify result (so `upgrade_none_reason` reaches `note_report_response`), or skip the `note_report_response` call entirely when the verify reply carried no `upgrade` key, so a sign-in can never clear a standing refusal (the comp-app-3 case) and the machine-targeted offer (CR-191) is left for the first report reply, which is the only reply that can name the machine. For the first option identity.py must also keep the verify reply's `upgrade_none_reason` (today it keeps only `upgrade` as `last_upgrade_info`).

## bug-wire-5 - standins_known is never sent empty, so a companion keeps the last non-empty set of stand-ins for the life of the process
- Status: FIXED
- Verified as: LOW, verified here. The reply built the key only `if known:`, against its own comment ("an empty list is sent for the same reason"); `proxy_relink.note_fleet_standins` keeps the old set on an absent key, and `fleet_says_standin` then answers True for rels the dashboard dropped. An empty list sets `_FLEET_KNOWN = True` with an empty set, so every rel answers False, which `_geometry_disagrees` treats as "not conclusive" and falls through to the probe: exactly "demux as before".
- Fix: the reply always carries `standins_known: {"rels": [...]}`, empty included, inside the same best-effort try.
- Regression test: `test_standins_known_is_sent_when_the_fleet_has_none` (HEAD: KeyError, the key is absent).
- Tests run: see "Tests run" at the end (all 19 new tests pass; affected existing suites green after the two test edits named there).
- Skew / deploy order: dashboard only; 0.9.74+ companions read the empty list correctly, older ones ignore the key.
- OWED: none.

## Tests run (all of this group)
- `cd dashboard; .venv\Scripts\python.exe -m pytest tests/test_bug_hunt_2026_09_24_w2_d-api.py -q` -> 19 passed.
- The same file against a scratch package with HEAD's api.py -> 16 failed, 3 passed (the three guards).
- 23 existing files that exercise the changed functions (test_admin_users, test_admin_users_local, test_admin_users_partial_parity, test_local_users, test_local_auth_mode, test_auth, test_nas_backend, test_synology_client, test_file_moves, test_project_setup, test_packages, test_report_endpoint, test_report_ingest_health, test_hardening, test_error_details, the 2026-08-21 / 09-11b / 09-18 / 09-18b / 09-24 crash_looped hunt files, the two 09-04 sweep files) -> 619 passed, 7 failed, and all 7 failures pinned the OLD bug-wire-3 behaviour: `test_hardening.py::test_report_fields_are_capped` asserted a 422 for a long lane `last_error`/`detail`/`last_sync`/`current_project`, a long transfer name and a long clip name (6 cases), and `test_report_endpoint.py::test_report_transfers_list_is_capped` asserted a 422 for 257 transfers. Both EDITED because the behaviour they pinned is the defect: the six string cases moved to a new `test_long_lane_and_clip_strings_truncate_rather_than_reject` asserting 200, the two negative/over-large manifest counts stay in `test_report_fields_are_capped` asserting 422 (numeric per-value caps still reject, unchanged), and the 257-transfer case now asserts 200. After the edits: `pytest tests/test_hardening.py tests/test_report_endpoint.py tests/test_bug_hunt_2026_09_24_w2_d-api.py` -> 84 passed.

## Owed round (2026-09-25, builder "d-cards / d-api")
- bug-comp-media-3 (from c-media): the `api_create_job` 422 for an unwritable `out_stem` is recorded in full in `d-cards.md` "Owed round" (the rule lives in `jobs.py`, the refusal in `api.py`).


## Owed round (2026-09-25)

These are the items other groups left for api.py and docs/API.md. New tests
are appended to `dashboard/tests/test_bug_hunt_2026_09_24_w2_d-api.py`, which
now holds 34 tests. Deploy order for the round: the dashboard alone. There is
no schema change and no new wire key. The one new answer is a 409 on a route
whose non-2xx answers companions already treat as a refusal.

### bug-comp-core-4 (from c-core) - VerifyIn.arch and upgrade_none_reason on /verify
- Status: ALREADY_FIXED
- Verified as: this group's own chunk-1 fix for bug-wire-4 (above) already covers it. That fix declares `VerifyIn.arch` as optional and truncates it to 32 characters with a before-validator, not `max_length=32`, so an over-long value never 422s a sign-in. It also passes `withheld=` to `_upgrade_info` and answers `upgrade_none_reason = withheld[0]` when there is no offer. I re-read `api_verify`: it has not changed since. `test_verify_declares_arch` and `test_verify_passes_the_arch_and_a_withheld_sink` still pass.
- Fix: none this round.
- Regression test: the two tests above.
- OWED: none. The companion halves belong to c-core and c-app.

### bug-comp-syncthing-2 (from c-sync) - an upload-only borrower is sent includes
- Status: FIXED
- Verified as: `_expand_includes` expanded links for every row, whatever its `sync_mode`. The effect was worse than cosmetic. The upload-only row's include CLAIMED the subpath, so a FULL borrower of the same subtree listed after it lost the include to the longest-prefix dedupe. The 0.9.79 companion now skips upload-only borrowers, so in that case no machine would have received the subtree.
- Fix: in `api._expand_includes`, a row whose `sync_mode` is not full is skipped before any link is read or any subpath claimed. NULL and '' count as full.
- Regression test: `test_an_upload_only_borrower_gets_no_includes_and_claims_nothing`. On the pre-fix code the upload-only borrower gets the include and the full borrower gets none.
- Skew: this is the mirror c-sync asked for. Companions up to 0.9.78 no longer build the lender as `not-offered` for an upload-only tick. 0.9.79 already ignored those includes.
- OWED: none.

### bug-comp-syncthing-3 (from c-sync) - an upload-only lender marked `covered`
- Status: FIXED
- Verified as: the code set `covered = lender_slug in selected`, with `selected` built from every row. One part of the c-sync entry does not hold: it expected companions up to 0.9.78 to "then get the subtree too". HEAD's `_build_borrowed` still drops the include, because its `selected_rels` counts the upload-only lender's rel. The change is still right for three reasons: `covered` now means what it says, the include now enters the server-side dedupe, and 0.9.79 runs the include either way (through its `_covered_by_upload_only`).
- Fix: `selected` is built from FULL rows only, using the same `_full` helper. The entry is still sent, with `covered: false`, so the tray's removal gate still sees the lender relationship. The gate's borrower half now also counts the subtree's pending uploads, which matches what 0.9.79 runs.
- Regression test: `test_an_upload_only_lender_does_not_cover_a_full_borrower`. It fails on the pre-fix code, which answers covered true. A control checks that a FULL lender still covers.
- Skew: either order.
- OWED: none.

### logic-plans-5 (from c-sync, optional) - protect companions up to 0.9.78 from a no-op untick read as success
- Status: FIXED
- Verified as: c-sync's reasoning holds. In the renamed-PC window the machine-scoped DELETE removes nothing and answers 200 with `changed:false`. A 0.9.77 or 0.9.78 companion reads that as "unticked" and deletes the local copy. The old hostname's row then brings the project back.
- Fix: `api_untick` plus a new helper, `_untick_missed_a_standing_tick`. The route answers 409 when all of these hold:
  - the actor is `companion:<editor>`;
  - `?machine=` is given;
  - nothing was removed;
  - the slug is not in that machine's own view;
  - the person still has the slug ticked somewhere (`selection_placements` with machine=None).

  The 409 carries a plain sentence that names the computer and the rename case. These cases are left alone:
  - Ticked nowhere stays 200. This is the stale-plan case, which 0.9.79 also lets through.
  - The signed-in UI's untick stays idempotent, always 200.
  - A failed read counts as "no refusal".

  There is no 404: it would make old builds widen the untick to the whole person.
- Regression test: `test_a_companion_untick_that_misses_a_standing_tick_is_refused`, which gets a 200 on the pre-fix code. Guards: `test_a_companion_untick_of_a_tick_gone_everywhere_is_still_ok`, `test_a_companion_untick_of_its_own_tick_is_unchanged`, `test_the_signed_in_untick_stays_idempotent`.
- Skew: old companions show "dashboard refused the untick (HTTP 409)" and delete nothing, because `app.remove_project_from_machine` stops on False. 0.9.79 reaches the same refusal, but it shows that generic HTTP 409 text instead of its own sentence.
- OWED: c-sync, `companion/src/ccsync_companion/selection.py` `_delete_selection` (optional). On an `HTTPError`, read the JSON body's `detail`, bounded the way identity.py's `verify_credentials` does it, and use it as the message. A 409 from this guard then shows the dashboard's sentence instead of "HTTP 409".

### logic-ytdl-jobs-1 (from d-cards) - API.md reason_code row
- Status: FIXED
- Fix: in section 6c of `docs/API.md`, a `machines_not_reporting` row was added to the reason_code table, after `kind_unknown`, with `transient` no. The per-machine reason list also gained `not_reporting`, with a one-line explanation.
- Regression test: `test_api_md_names_the_silent_machines_reason_code`. It reads `jobs.REASON_SILENT` and `jobs.REFUSE_SILENT` and checks both are in the doc. It fails on HEAD's doc.
- OWED: none.

### bug-wire-1 (from d-db) - the "Terminal answers cannot repeat" comment
- Status: FIXED (comment only)
- Fix: this comment sits in the report route's file-move answer loop. It now names RES-10's relinked-after-all answer as the one exception: that answer clears `relink_pending` once, returns True and is logged once, and any repeat of it is a no-op. I checked it against d-db's `mark_file_move_applied` as it now stands.
- Regression test: none (comment only).
- OWED: none.

### logic-sync-truth-5 (from d-diag) - owed_files on the fleet row
- Status: FIXED
- Fix: a new `api._owed_files_by_machine(conn)` runs once per `build_editors_view`. It sums `n_files` over `db.fetch_sync_backlog(conn, files_per_group=0)` for each (editor, machine) pair. No file names are read, because the down list runs with LIMIT 0. It sets no count in three cases:
  - a machine with no `editor_media_project` row at all (no manifest means no data, not "nothing owed");
  - a machine whose only answer is an `uncertain` zero (logic-sync-truth-2);
  - a read failure, where the function returns None.

  In the row loop, `entry["owed_files"]` is set before `health.fleet_headline(entry)`, except on base-mode rows.
- Regression test: `test_the_fleet_row_carries_the_owed_file_count` and `test_a_manifest_with_nothing_owed_counts_zero` both fail on the pre-fix code, which sets no key. Guards: `test_no_count_is_claimed_without_data_or_on_failure`, `test_a_base_rig_row_claims_no_count`.
- Cost: one backlog pass per editors view. The alerts module builds that view every collector cycle. It is the transfers page's own query, bounded per pair by EDITOR_MEDIA_CAP originals. Worth watching on a large fleet.
- Skew: dashboard only.
- OWED: none.

### ui-copy-6 (from d-ui) - " -- " in user-visible api.py strings
- Status: FIXED
- Verified as: the AST scan found all 24 listed hits (it skips docstrings and log calls). Every hit is one of these: an HTTP `detail`, a ProjectSetupError or ValueError that becomes one, or the name of the transfers page's incoming row. None was SQL or a log line.
- Fix: each one now uses a colon, a semicolon or two sentences. Substrings that existing tests pin were kept: lowercase "try again", "recalled too" and "is not a Syncthing device ID". The new 409 above has no dash either.
- Regression test: `test_api_py_copy_has_no_typewriter_em_dash`, an AST scan of api.py. It finds 24 hits on HEAD.
- OWED: none for api.py.

### logic-onboarding-1 (from onboarding) - the api_verify `role` comment
- Status: FIXED (comment only)
- Fix: the comment on `"role"` in `api_verify` no longer says the companion flips its sync behaviour on it. It now says:
  - the value is about the PERSON;
  - since CR-88, wired or remote is the computer's own setting;
  - the wizard's radio decides the install role;
  - the key stays for diagnostics and for old clients.
- OWED: none.

### Tests run (owed round)
- `pytest tests/test_bug_hunt_2026_09_24_w2_d-api.py` -> 34 passed.
- The new owed-round tests, run against a scratch copy with the three behavioural fixes reverted -> 5 failed (the five fix tests) and 5 passed (the guards).
- The d-api file plus `test_selection_api`, `test_project_links_api`, `test_bug_hunt_2026_09_24_w2_d-diag`, `test_fleet_grid_declutter_2026_09_11`, `test_health`, `test_error_details`, `test_release_channel`, `test_packages`, `test_project_setup`, `test_auth`, `test_admin_assignments`, `test_upload_only` and `test_multi_machine` -> 452 passed, 3 failed before the casing fix. Two of the failures pinned lowercase "try again" in the fleet-membership 503. The wording now keeps it ("right now: try again shortly"), and no test was edited. The third failure is unrelated to this round: `test_bug_hunt_2026_09_24_w2_d-diag.py::test_the_resolve_undo_step_claims_no_dashboard_button_that_does_not_exist` asserts on `templates/partials/recovery.html`, which is d-ui's file and was not touched here.
- Every suite whose tests pin one of the changed detail strings -> 451 passed. These are `test_auth`, `test_bug_hunt_2026_09_18_dashboard_mediums`, `test_bug_hunt_2026_09_24_crash_looped`, `test_db_busy_2026_09_17`, `test_error_details`, `test_nas_backend`, `test_packages`, `test_presence`, `test_project_setup`, `test_report_endpoint`, `test_sessions`, `test_sweep_2026_09_04_says_what_it_knows`, `test_file_moves`, `test_cr312_transfer_names_wrap`, `test_release_channel` and the d-api file.


# Owed round 3 (2026-09-25)

## bug-dash-db-2 / logic-sync-truth-2 (owed from d-ui) - the transfers view dropped the capped zero-file upload row
- Status: FIXED
- Verified as: `build_transfers_view` filtered `queues` to `n_files > 0` after the active-transfer subtraction. That dropped the `uncertain` row `db.fetch_sync_backlog` keeps for an originals-capped machine before it reached `ui.safe_to_close` or `partials/transfers.html`, so the panel said "Safe to close" over an unknown backlog. d-ui's two strict-xfail end-to-end tests pinned exactly this.
- Fix: api.py `build_transfers_view` (~681): `queues = [q for q in queues if q["n_files"] > 0 or q.get("uncertain")]`, with a comment citing the finding. The same change removed both `xfail(strict=True)` markers in `dashboard/tests/test_bug_hunt_2026_09_24_w2_d-ui.py`.
- Regression test: `test_bug_hunt_2026_09_24_w2_d-ui.py::test_an_originals_capped_machine_is_not_safe_to_close_through_the_real_view` and `::test_the_editors_queue_panel_does_not_say_safe_to_close_over_a_capped_list` now run for real. They were strict-xfail on HEAD, which means they failed as asserted.
- Tests run: `dashboard\.venv\Scripts\python.exe -m pytest tests/test_bug_hunt_2026_09_24_w2_d-api.py tests/test_bug_hunt_2026_09_24_w2_d-ui.py -q` -> 137 passed; `tests/test_cr311_queue_says_on_hold.py tests/test_upload_only.py tests/test_multi_machine.py tests/test_bug_hunt_2026_09_24_w2_d-db.py tests/test_unicode_paths.py` -> 101 passed.
- Skew / deploy order: dashboard only. A row without `uncertain` (older d-db) is filtered exactly as before.
- OWED: none

## bug-dash-api-4 (owed from d-ui) - the JSON create-or-update route reset a password without signing the account out
- Status: FIXED
- Verified as: `POST /api/v1/admin/users` (NAS branch) calls `create_or_update_editor`, then `set_known_password` when a password is given. On an existing username that is a password reset. Unlike the page twin (`ui.partial_admin_create_user`) and `/admin/users/{u}/password`, it never called `revoke_sessions_after_password_reset`. The local-mode branch only creates and refuses an existing name, so it is not a reset door.
- Fix: api.py `api_admin_create_user`: after the commit, when `payload.password` was set, `response["sessions_revoked"] = revoke_sessions_after_password_reset(request, username, admin=admin)`. This is a new optional key, absent when no password was sent.
- Regression test: `test_bug_hunt_2026_09_24_w2_d-api.py::test_the_json_create_setting_a_password_signs_the_account_out` (fails on HEAD: the old session still validates and there is no `sessions_revoked`), and `::test_the_json_create_without_a_password_signs_nobody_out`.
- Tests run: as above, plus `tests/test_admin_users.py tests/test_admin_users_partial_parity.py tests/test_admin_users_local.py` -> 57 passed.
- Skew / deploy order: dashboard only. A caller that ignores the new key is unaffected.
- OWED: none

## api_recovery_restore docstring (owed from d-diag) - named the old quarantine location
- Status: FIXED (comment only)
- Verified as: recovery.py (bug-dash-diag-3) restores into `<tree>/.restored-<ts>/<project>/`. The route's docstring still said `<project>/.restored-<ts>/`.
- Fix: the api.py `api_recovery_restore` docstring now says `<tree>/.restored-<ts>/<project>/` and why: a folder inside the project is a Syncthing root, so a restore there would be pushed to every machine that has the project ticked.
- Regression test: none (docstring only).
- Tests run: n/a
- Skew / deploy order: none
- OWED: none

## Fable round (2026-09-25)

## logic-sync-truth-5 follow-up (fable-review-wave2-dashboard M1) - the owed-files diff ran on every fleet-grid build
- Status: FIXED
- Verified as: `api._owed_files_by_machine` runs `db.fetch_sync_backlog(files_per_group=0)` (a NOT EXISTS diff per ticked pair) inside `build_editors_view`, which serves `/partials/fleet` every 15 s per admin tab, `/api/v1/editors` and every alerts cycle. Fable measured 77 ms on 48 pairs.
- Fix: `dashboard/src/ccsync_dashboard/api.py`: the diff moved to `_count_owed_files` unchanged; `_owed_files_by_machine` now returns a cached copy when the database file (`PRAGMA database_list`, or the connection for :memory:) and a FINGERPRINT of the inputs are unchanged and the entry is under `_OWED_CACHE_TTL_SECONDS` (15 s). The fingerprint is every row of the small tables that every writer of the big ones stamps in the same call: `editor_media_project` (replace_editor_media is always paired with upsert_editor_media_project), `nas_inventory_state` (replace_nas_media and its refusal/failure paths), `selections` (tick, untick, mode, machine) and `projects(id, slug, active)`; a prune or purge deletes rows there too. The TTL is a backstop for a writer the list does not know. A failed count (None) is never cached; the cache is behind a lock and hands out copies.
- Regression test: `dashboard/tests/test_bug_hunt_2026_09_24_w2_d-api.py::test_two_builds_with_nothing_changed_diff_once` (real backlog, counting wrapper around the real fetch_sync_backlog; also pins the TTL re-count) - fails without the cache (ran with it bypassed: 2 calls, not 1). Correctness guards, pass both ways: `::test_a_new_manifest_is_seen_on_the_next_build`, `::test_a_nas_walk_and_a_mode_change_are_seen_on_the_next_build` (owed 2 -> 1, 2 -> 3 -> 0 on consecutive builds, each re-diffed).
- Tests run: `cd dashboard; .venv/Scripts/python.exe -m pytest tests/test_bug_hunt_2026_09_24_w2_d-api.py tests/test_bug_hunt_2026_09_24_w2_d-diag.py tests/test_fleet_grid_declutter_2026_09_11.py tests/test_bug_hunt_2026_09_18_dashboard_mediums.py tests/test_bug_hunt_2026_09_11_dash_mounts_ui.py tests/test_sweep_2026_09_04_copy.py tests/test_alerts.py tests/test_triage.py -q` -> 608 passed, 1 skipped, 1 failed: `test_sweep_2026_09_04_copy.py::test_no_retired_word_in_python_copy[jobs.py]` (retired word "machine" in a string at `jobs.py:120`, a d-cards file modified by another builder this wave; not touched here).
- Skew / deploy order: dashboard only, no wire or schema change.
- OWED: d-cards, `dashboard/src/ccsync_dashboard/jobs.py:120`: the new "is not a plain file name ..." copy trips the CR-181 retired-word scan ("machine", say "computer").
