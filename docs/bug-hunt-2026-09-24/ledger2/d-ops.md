# Wave 2 ledger - group d-ops

Builder d-ops, chunk 1 of 1 (2026-09-25). New tests in
`dashboard/tests/test_bug_hunt_2026_09_24_w2_d-ops.py`. Every regression test
was run against HEAD's copy of the file it covers (swapped in from
`git show HEAD:...`, then restored) and failed there.

## bug-dash-ops-2 - /ytdl drops the identity of every session signed with a previous DASH_SESSION_SECRET
- Status: FIXED (ytdl half); broll/music halves OWED
- Verified as: CONFIRMED medium (verifiers/med-07.md). Read `YtdlGate._identified_scope` (re-read the cookie with `self._secret` only, no `previous=`) against `auth._resolve_session` (accepts `session_secrets_previous`). New test through the full app with a cookie signed by the old key: HEAD's sub-app saw `{"user": None}`.
- Fix: `dashboard/src/ccsync_dashboard/ytdl.py` new `YtdlGate._session_user` (called from `_identified_scope`). When the scope carries the dashboard app (every production request) it asks `auth.get_session_user(Request(scope))`, i.e. login_gate's own verdict, already cached on the request state login_gate filled: previous keys, last-wins cookie and the session-store revocation check all come with it. With no app in the scope (unit tests, a standalone wrapper) it falls back to `read_session_cookie(..., previous=previous_session_secrets(settings))`.
- Regression test: `test_ops2_a_session_signed_with_the_previous_secret_still_names_its_owner`, `test_ops2_the_bare_gate_also_knows_the_previous_keys` - HEAD stamped no identity for an old-key cookie.
- Tests run: `dashboard\.venv\Scripts\python.exe -m pytest tests/test_bug_hunt_2026_09_24_w2_d-ops.py tests/test_ytdl_mount.py -q` -> pass (see the final run below).
- Skew / deploy order: dashboard-only, no wire or schema change.
- OWED: d-cards, `dashboard/src/ccsync_dashboard/broll.py` (`_identified_scope`, ~:232) and `dashboard/src/ccsync_dashboard/music.py` (`_identified_scope`, ~:242): the same gap. Resolve the stamped name through `auth.get_session_user(Request(scope))` when `scope["app"]` has `state.settings` (as `ytdl.YtdlGate._session_user` now does), falling back to `auth.read_session_cookie(secret, cookie, previous=auth.previous_session_secrets(settings))`, and make their cookie parse last-wins.

## bug-dash-ops-3 - The ytdl gate reads the FIRST ccsync_session cookie while login_gate reads the LAST, and never checks revocation
- Status: FIXED (ytdl); broll/music OWED (same item as above)
- Verified as: real. Starlette 1.6 `cookie_parser` (request.cookies, what login_gate reads) keeps the last duplicate; `ytdl._session_cookie` returned the first. `_resolve_session` checks the server-side row; the gate checked signature and expiry only. Low: needs two cookies of one name or a revoked cookie still in a browser.
- Fix: same `_session_user` as above (login_gate's cached verdict, so the same cookie and the revocation check); `_session_cookie` in ytdl.py is now last-wins for the fallback path.
- Regression test: `test_ops3_two_session_cookies_name_the_one_login_gate_authenticated` (HEAD stamped `alice`, the gate had authenticated `bob`), `test_ops3_the_cookie_helper_is_last_wins`, `test_ops3_the_gate_defers_to_login_gates_verdict` (login_gate's cached "not live" verdict for a revoked session; HEAD stamped the cookie's owner anyway).
- Tests run: as above.
- Skew / deploy order: dashboard-only.
- OWED: d-cards, broll.py / music.py, as in bug-dash-ops-2.

## bug-dash-ops-4 - crash_report.redact misses the very secrets its docstring names
- Status: FIXED (dashboard); companion copy OWED
- Verified as: CONFIRMED medium (verifiers/med-07.md: HEAD's pattern leaves `DASH_SESSION_SECRET=`, `TRUENAS_PW=`, `SYNCTHING_API_KEY:`, `{'password': ...}`, `{"api_key": ...}` untouched). Reproduced by the new parametrised test on HEAD (8 of 8 cases unchanged).
- Fix: `dashboard/src/ccsync_dashboard/crash_report.py` `_REDACTIONS[0]`: boundary `(?<![a-z0-9])` / `(?![a-z0-9])` so `_` separates, optional `_SUFFIX` parts on the key (`SECRET_PREVIOUS`), optional closing quote before `:`/`=`, and a quoted value is taken whole (`'two words'`). Output form `key=<redacted>` unchanged. `notices.error_detail` goes through the same function, so notice bodies get it too.
- Regression test: `test_ops4_env_style_and_quoted_keys_are_redacted[*]` (8 cases), plus `test_ops4_what_was_already_redacted_still_is` and `test_ops4_words_that_merely_contain_a_key_are_left_alone` as guards.
- Tests run: with test_crash_report.py, test_bug_hunt_2026_09_24_crash_looped.py, test_bug_hunt_2026_09_11b_cr266_live_notices.py -> pass.
- Skew / deploy order: none.
- OWED: c-ui, `companion/src/ccsync_companion/crash_report.py:88`: the same `\b(token|password|passwd|secret|api[_-]?key|dsn)\b\s*[:=]\s*\S+` pattern with the same `_`/quote gap; port the dashboard's new pattern (it also lacks `pw`).

## bug-dash-ops-8 - A second CLI update inside the grace hour deletes the still-in-grace version at once
- Status: FIXED
- Verified as: real. `_finish_install` rebuilt the state record naming only the version just replaced; `_prune_old_versions` spared `{keep, previous}`, so A (replaced minutes earlier, CR-309's grace still running) was rmtree'd on the B -> C flip. New test on HEAD: `2.1.100` gone after the second update.
- Fix: `dashboard/src/ccsync_dashboard/cli_tools.py`: `_finish_install` carries forward every replaced version still inside its own grace (and still on disk), `_superseded_entries`/`_set_superseded` read and write them (newest stays in `previous_version`/`superseded_at_epoch`, older ones in a new optional `superseded_earlier` list), `_prune_old_versions(spare=[...])` spares them all, and `sweep_superseded` retires each on its own clock (returns the removed versions comma-joined; its one caller ignores the value).
- Regression test: `test_ops8_a_second_update_inside_the_grace_spares_the_first_replaced_version` (HEAD pruned 2.1.100 immediately), `test_ops8_the_record_keeps_the_shape_an_older_dashboard_reads`, `test_ops8_reinstalling_a_version_in_grace_does_not_list_it_as_replaced`.
- Existing test changed: `tests/test_cli_auto_update.py::test_a_third_install_prunes_everything_but_the_live_and_the_last` pinned the defect (three installs in the same instant, first one pruned); it now moves the clock past the first grace before the third install, which is the behaviour it was meant to pin.
- Tests run: `pytest tests/test_bug_hunt_2026_09_24_w2_d-ops.py tests/test_cli_auto_update.py tests/test_cli_tools.py tests/test_bug_hunt_2026_09_11b_cr266a_cli_tools.py -q` -> 183 passed.
- Skew / deploy order: the state file is per-container; a rolled-back dashboard reads `previous_version` as before and ignores `superseded_earlier` (those directories are then pruned by its next install, the pre-fix behaviour). No wire change.
- OWED: none

## bug-dash-ops-9 - Two crashes of the same thread in the same second overwrite one crash file
- Status: FIXED
- Verified as: real; `write_report` named files `<second>-<thread>.json` and opened with `O_TRUNC`.
- Fix: `dashboard/src/ccsync_dashboard/crash_report.py` `write_report`: `O_EXCL`, retrying `-1` .. `-99` on `FileExistsError`; still `0o600`, still never raises.
- Regression test: `test_ops9_two_crashes_in_one_second_on_one_thread_keep_both` - HEAD returned the same path twice and kept only the second body.
- Tests run: with test_crash_report.py -> pass.
- Skew / deploy order: none.
- OWED: c-ui may want the same for `companion/src/ccsync_companion/crash_report.py:276` (also `O_TRUNC`); not verified here, it is not this finding.

## logic-release-3 - A STAGED vendor record (and a pointer moved back) counts as "offered" on every customer dashboard
- Status: FIXED
- Verified as: CONFIRMED medium (verifiers/med-12.md). Read `record_offer_state` (walked every `package_records`), `_apply_policy` (uses `select_offered_records`), `invariants._check_fleet_current_with_vendor` (max of `feed_offered`), `alerts._check_versions_behind`, `package_store.what_is_running` (dashboard `newest_offered` = max record).
- Fix: `dashboard/src/ccsync_dashboard/release_feed.py`: `record_offer_state` takes the channel (`check_now` passes `_cache(app_state)["channel"]`) and measures against `select_offered_records` - `feed_offered[platform]` is the pointed (or, with no pointer, highest) version plus every version BELOW it, so staged and pointer-withdrawn builds are gone while SYS-2's "N releases behind" count still sees older fixes; the `feed_publish_refused` notice is raised only for the selected record. New `offered_dashboard_version(app_state)` gives the pointed dashboard version; `package_store.what_is_running` uses it for `dashboard.newest_offered`. Readers in invariants.py / alerts.py are unchanged (d-diag files), they read the corrected data.
- Regression test: `test_rel3_a_staged_companion_is_not_what_the_vendor_offers`, `test_rel3_a_pointer_moved_back_withdraws_the_build_above_it`, `test_rel3_a_staged_build_that_needs_a_newer_dashboard_raises_no_notice`, `test_rel3_a_real_check_measures_against_the_signed_pointer` (signed channel through `/api/v1/admin/feed/check`), `test_rel3_the_dashboard_offered_is_the_pointer_not_the_highest`, `test_rel3_what_is_running_reports_the_pointed_dashboard`; guard `test_rel3_no_pointer_keeps_the_highest_and_everything_below_it`. All but the guard fail on HEAD.
- Tests run: with test_release_feed.py, test_sweep_2026_09_04_dashboard.py (SYS-2's "3 releases behind" still passes), test_invariants.py, test_packages.py -> see final run.
- Skew / deploy order: `feed_offered` is rewritten on every feed check; no schema change. `record_offer_state`'s new `channel` argument is optional (None = no pointer = the highest, the old selection rule for older feeds).
- OWED: none

## logic-release-4 - The dashboard's own auto-update ignores the channel's `current` pointer
- Status: FIXED (forward half); auto-rollback on a pointer moved back DEFERRED
- Verified as: CONFIRMED medium (verifiers/med-12.md). `_dashboard_auto_apply_reason` took `code_updates[0]` (highest newer than running) with no look at `current["dashboard/linux"]`.
- Fix: `release_feed._dashboard_auto_apply_reason`: when the channel carries a dashboard pointer, only the pointed version is taken unattended (both `code_updates` and `runtime_updates` are filtered to it); a newer bundle that is not the pointed one returns a note ("... is not the version the vendor currently offers (X), so it is not taken automatically. [ APPLY ] on the Packages page takes it by hand") that `apply_dashboard_policy` records under `AUTO_UPDATE_NOTE_KEY`. No pointer keeps the old highest-first rule. `dashboard_update.status` is unchanged, so every version is still a manual [ APPLY ] row.
- Regression test: `test_rel4_a_staged_dashboard_bundle_is_not_applied_unattended` (HEAD returned `9.9.9`, the staged bundle); guard `test_rel4_no_pointer_keeps_the_highest_first_rule`.
- Tests run: with test_release_feed.py, test_dashboard_update.py -> see final run.
- Skew / deploy order: none; reads a key the signed channel already carries.
- DEFERRED: "a pointer moved back does not roll a customer dashboard back". Doing that means an unattended DOWNGRADE of the container's own code (schema is forward-only; the boot selector already refuses a revert onto an older schema), which is an owner/vendor decision, not a bug fix. Decision needed: should `policy = current` follow a dashboard pointer backwards, and if so only within one schema version?
- OWED: none

## ui-dash-admin-8 - An Android validation refusal throws away the fingerprints the admin just pasted
- Status: FIXED
- Verified as: real. `api_setup_android`'s `SiteValidationError` branch re-rendered `_context` from `site_store.resolved_manifest` (the saved values); the template reads only `manifest.android.*`. New test on HEAD: the two good fingerprints and the package name were gone from the re-rendered panel.
- Fix: `dashboard/src/ccsync_dashboard/android.py`: `_context(..., draft=)` overlays the submitted package name and the raw fingerprint text on a copy of the manifest's `android` block; the refusal branch passes it. The raw text goes in as ONE list entry, so the template's existing `{% for f %}{{ f }}\n{% endfor %}` prints it back exactly as typed (autoescaped). No template change needed.
- Regression test: `test_admin8_a_refused_save_keeps_what_the_admin_pasted` - HEAD's panel had neither good fingerprint nor the package name.
- Tests run: with tests/test_android.py -> 63 passed (together with the new file at that point).
- Skew / deploy order: none. No layout change (same fields, same markup), so no screenshot.
- OWED: none

## Final run (all eight findings together)
`cd dashboard; .venv\Scripts\python.exe -m pytest tests/test_bug_hunt_2026_09_24_w2_d-ops.py tests/test_ytdl_mount.py tests/test_ytdl_site_gate.py tests/test_crash_report.py tests/test_bug_hunt_2026_09_24_crash_looped.py tests/test_bug_hunt_2026_09_11b_cr266_live_notices.py tests/test_cli_auto_update.py tests/test_cli_tools.py tests/test_bug_hunt_2026_09_11b_cr266a_cli_tools.py tests/test_release_feed.py tests/test_release_channel.py tests/test_sweep_2026_09_04_dashboard.py tests/test_invariants.py tests/test_packages.py tests/test_dashboard_update.py tests/test_android.py tests/test_error_details.py -q` -> 628 passed.

# Owed round (builder d-ops, 2026-09-25)

Items other groups left for d-ops files. New tests appended to
`dashboard/tests/test_bug_hunt_2026_09_24_w2_d-ops.py` (section "owed round",
all named `test_owed_*`). HEAD check: `git archive HEAD dashboard` into the
scratchpad, this test file copied in, run with `PYTHONPATH` on that copy's
`src` (confirmed the import resolved there): 19 of the 21 owed tests fail on
HEAD; the 2 that pass are guards (no-feed site keeps ship.cmd; no verdict in
the state still reads the cookie).

## bug-dash-api-1 (owed from d-api) - DSM approve replaces the first computer's key
- Status: FIXED (the DSM half; TrueNAS optional half not done, see below)
- Verified as: read `_INSTALL_KEY_SCRIPT` (`printf > tmp; mv -f authorized_keys`: a replace) and `api._install_nas_key_keeping_others` (calls `nas.add_editor_ssh_key` when the backend has it, else merges from `find_user()["sshpubkey"]`, which DSM never fills). So on DSM, until now, approve still replaced.
- Fix: `dashboard/src/ccsync_dashboard/nas/synology.py`: new `_APPEND_KEY_SCRIPT` (same `set -e`, MISSING_HOME check, `umask 077`, tmp + `mv -f`, `chown -R` of `~/.ssh`, `chmod 700/600`, stat read-back as the install script; it `cat`s the old file into the tmp, adds a newline when the old file lacks a final one, appends the key, and skips the write with `ALREADY` when an awk scan finds the same type and body as adjacent fields on any line, so a key behind an options prefix or with another comment counts). New `SynologyClient.add_editor_ssh_key(username, ssh_pubkey)`: refuses a key that is not one `<type> <body> [comment]` line (a newline would add an unreviewed key), then `_refuse_non_editor` (same refusals as create); an account that does not exist goes down `create_or_update_editor` (no other key to keep). `_install_ssh_key` takes `append=` and `unwritten_raises=`: for the add call a key that was NOT written (SSH down, MISSING_HOME, non-zero exit) RAISES `NasError`, because `approve_pending_ssh_key` keeps the queued offer only on a raise, and a warning would have dropped the offer with no key on the NAS. Create keeps its warning behaviour. StrictModes read-back problems stay warnings on both (the key was written).
- Regression test: `test_owed_api1_dsm_adds_a_second_key_and_keeps_the_first`, `..._a_key_already_there_is_not_written_twice`, `..._a_file_without_a_final_newline_is_not_glued`, `..._an_account_with_no_key_file_gets_just_the_new_key`, `..._the_append_touches_only_dot_ssh` (the generated script is RUN in Git Bash against a home under tmp_path, chown/getent stubbed, so awk/cat/tail/mv/chmod/stat are real; skipped if no POSIX shell), `..._a_key_that_could_not_be_written_raises`, `..._a_multi_line_key_is_refused_before_any_ssh`, `..._no_account_yet_goes_down_the_create_path`. All fail on HEAD (no such method).
- Tests run: `cd dashboard; .venv\Scripts\python.exe -m pytest tests/test_bug_hunt_2026_09_24_w2_d-ops.py tests/test_admin_users.py tests/test_admin_users_local.py tests/test_admin_users_partial_parity.py tests/test_ai_providers.py tests/test_bug_hunt_2026_09_24_w2_d-api.py tests/test_cr335_packages_page.py tests/test_dashboard_update.py tests/test_nas_backend.py tests/test_packages.py tests/test_release_feed.py tests/test_synology_client.py tests/test_ytdl_mount.py tests/test_ytdl_site_gate.py tests/test_release_channel.py -q` -> 615 passed.
- Not done, on purpose: the optional TrueNAS `add_editor_ssh_key`. api.py already merges against TrueNAS's `sshpubkey` text (with the review round's keep-every-line rule), so a second copy of the merge in truenas.py would only be a second place to keep in step.
- Not live-verified: the append script has never run on a real DSM box. Its tools (awk, tail, cat) are in DSM's base system, but the first real approve on the Synology test NAS should be checked (`cat ~/.ssh/authorized_keys` shows both keys).
- Skew / deploy order: dashboard only; no wire or schema change.
- OWED: none

## bug-dash-cards-jobs-4 (owed from d-cards) - YtdlGate identity minting
- Status: FIXED (the ytdl half of this finding was mostly already done by my chunk 1, bug-dash-ops-2/-3; this round lines it up with the broll/music rule)
- Verified as: chunk 1's `YtdlGate._session_user` already used login_gate's cached verdict (`auth.get_session_user(Request(scope))`) when the dashboard app is in the scope, and the cookie with every accepted key otherwise. The one gap left against d-cards' rule: with a verdict in `scope["state"]` but no app with settings in the scope, it ignored the verdict and read the cookie, so a revoked session's owner (or the wrong one of two cookies) could still be stamped.
- Fix: `dashboard/src/ccsync_dashboard/ytdl.py` `_session_user`: read `scope["state"]["ccsync_session"][0]` first when present (None = no header; a malformed entry fails closed), then login_gate's resolver when the app is there (an exception now fails closed instead of a 500), then the cookie with `previous=auth.previous_session_secrets(settings)`. Same order and fail-closed shape as `broll.py`/`music.py`.
- Regression test: `test_owed_cards_jobs_4_the_resolved_identity_wins_over_the_cookie` (HEAD and chunk 1 stamped alice from the cookie where login_gate resolved bob), `test_owed_cards_jobs_4_a_not_live_verdict_mints_no_header_without_the_app` (they stamped the revoked session's owner); guard `test_owed_cards_jobs_4_no_verdict_still_reads_the_cookie`.
- Tests run: as above (test_ytdl_mount, test_ytdl_site_gate green).
- Skew / deploy order: dashboard only.
- OWED: none

## logic-admin-6 (owed from d-ui) - the unsigned make-current refusal names tools\ship.cmd on a feed site
- Status: FIXED
- Verified as: read `package_store.make_current_refusal`: the unsigned branch said "Republish it through tools\ship.cmd instead" to every site; RELEASE_PATHWAYS.md makes ship.cmd the studio's own pathway A.
- Fix: `dashboard/src/ccsync_dashboard/package_store.py` `make_current_refusal`: when `settings.release_feed_url` is set, the sentence is "Publish the signed build from AVAILABLE FROM THE VENDOR instead."; otherwise the ship.cmd sentence exactly as before (test_packages.py:267 still pins it for a no-feed site and passes).
- Regression test: `test_owed_admin6_a_feed_site_is_sent_to_the_vendor_list` (HEAD: ship.cmd on a feed site); guard `test_owed_admin6_a_site_with_no_feed_keeps_ship_cmd`.
- Tests run: as above (test_packages, test_cr335_packages_page, test_release_channel green).
- Skew / deploy order: dashboard only.
- OWED: none

## ui-dash-admin-14 (owed from d-ui) - docs/ANDROID.md names the old button
- Status: FIXED
- Verified as: `docs/ANDROID.md:219` said `[ UNDO LAST IMPORT ]`; d-ui renamed the button to `[ UNDO LAST CHANGE ]`.
- Fix: `docs/ANDROID.md:219` now names `[ UNDO LAST CHANGE ]`.
- Regression test: none (a doc line; nothing executes it).
- Tests run: none needed.
- Skew / deploy order: none.
- OWED: none

## ui-copy-6 (owed from d-ui) - " -- " in d-ops user-visible strings
- Status: FIXED
- Verified as: the d-ui AST scan (docstrings and log calls excluded) over the eight files found 57 string constants with " -- ". One is not copy: `dashboard_update._STAGE_VERIFY_SOURCE`, a Python script the staged tree runs, where the only " -- " is a comment inside that script. It is left alone and the test excludes it by name. The other 56 are HTTP `detail`s (dashboard_update, release_feed, ai_providers), `FeedError`/`PackageStoreError`/`ProviderError` text the admin pages show, NAS refusals and create warnings (synology, truenas), the `DASH_NAS_KIND` error (factory), the signature refusal (package_store) and the runtime-id error.
- Fix: each of those literals now uses ": " where " -- " stood, edited token by token (only string tokens inside the flagged constants, so no comment, docstring or log line changed). Read through the result: all read as "<what>: refused", "<what>: refusing to ...", "<what>: <consequence>". `release_feed._presigned_hint` is appended after the error text, so it now reads "...: this feed URL is PRE-SIGNED, ...". The synology `MISSING_HOME` warning was rewritten by hand as part of the bug-dash-api-1 change. No test pinned any of the old spellings (grep of tests/, tools/, server/; `tests/fake_synology.py`'s own copies of the refusals are the fake's text, not the product's, and were left).
- Regression test: `test_owed_copy6_d_ops_copy_has_no_typewriter_em_dash[<file>]` for each of the eight files, fails on HEAD for all eight.
- Tests run: as above, plus `tests/test_admin_delete.py tests/test_bug_hunt_2026_09_11_dash_mounts_ui.py tests/test_bug_hunt_2026_09_11b_dash_mounts_ui.py tests/test_bug_hunt_2026_09_18_dashboard_lows.py tests/test_select_code_root.py tests/test_site_manifest_consumers.py` -> 134 passed.
- Skew / deploy order: dashboard only. No wire value changed: these are messages, and nothing parses them (grep).
- OWED: none. For d-ui's closing step: the eight d-ops files are clean now, so widening DUI-14's scan to the package will not trip on them (it will need the same `_STAGE_VERIFY_SOURCE` exclusion).

## Owed round 2 (2026-09-25)

### Crash-file naming and prune order (owed by c-ui, from bug-dash-ops-9)
- Status: FIXED.
- Verified as: this wave's first cut of bug-dash-ops-9 named the second crash of a second `<base>-1.json` into the first free slot and `_prune` sorted by name. `-` (0x2d) sorts before the `.` of the bare `<base>.json`, so the later crash read as OLDER and was pruned first; `-10` sorted before `-2`; and once the prune freed `<base>.json`, a first-free search gave the bare (oldest-sorting) name to the newest crash.
- Fix: `dashboard/src/ccsync_dashboard/crash_report.py` now carries the companion's scheme verbatim: `_COUNTER_SEP = "~"`, `_crash_name(base, n)` -> `<base>~NN.json`, `_age_key` (base, counter) used by `_prune`, and `write_report` numbers past the HIGHEST existing slot for that base (`glob.escape(base)`). Module docstring names the `~01` suffix. `notices.crash_files` sorts by mtime and needed no change.
- Regression tests (`dashboard/tests/test_bug_hunt_2026_09_24_w2_d-ops.py`, `test_owed2_*`): the prune keeps the latest two of a three-crash burst; a freed slot does not go to the newest (four-crash burst, keep 2); twelve in one second keep 7..11; a thread named `Thread-1` is not parsed as a counter. The first three fail on HEAD (O_TRUNC keeps one file) AND on the pre-owed working copy (`-N`, first free, name sort), checked by swapping each into place and running them.
- Wire/deploy: none. File names only; nothing outside this module parses them.

### Diagnostics route in the /help document (owed by d-diag)
- Status: FIXED. The text lives in `docs/HOW_IT_WORKS.md` (the file help.py serves), not help.py itself.
- Fix: lines 857 and 893 now say `Tray > Settings > HELP > COPY DIAGNOSTICS FOR YOUR ADMIN`, the same string as `health.COMPANION_DIAGNOSTICS_PATH` and the companion's button label.
- Regression test: `test_owed2_the_help_doc_names_the_companions_real_diagnostics_route` (old phrase absent, the constant present at least twice) - fails on HEAD's document.

Tests run: `dashboard/.venv` pytest on `test_bug_hunt_2026_09_24_w2_d-ops.py`, `test_crash_report.py`, `test_help_doc_matches_the_companion.py`: 91 passed.
