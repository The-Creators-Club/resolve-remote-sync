# Wave 2 ledger, group d-auth (2026-09-25)

Tests for every fix: `dashboard/tests/test_bug_hunt_2026_09_24_w2_d-auth.py`.
HEAD check: the six changed modules replaced with `git show HEAD:` copies in a
scratch package (`scratchpad/dauth_w2_head`): 19 of the 25 tests fail there,
every regression test among them. The 6 that pass on HEAD are guards for
behaviour that must NOT change (`auto`/`1`/`0` boot line, a single-hop or
untrusted-peer X-Forwarded-For, a mixed CJK+ASCII asset name). One more,
`test_the_wizard_signed_in_by_step_two_reaches_the_rest`, fails in the scratch
copy only because templates resolve next to the package; it passes in the repo
and is a guard, not a regression test.

Tests run: `cd dashboard; .venv\Scripts\python.exe -m pytest` over
test_android, test_auth, test_bug_hunt_2026_08_21, test_bug_hunt_2026_09_03_dash_api,
test_bug_hunt_2026_09_11b_dash_core, test_bug_hunt_2026_09_18_dashboard_mediums,
test_cross_seams_2026_08_21, test_hardening, test_links, test_project_setup,
test_provision, test_sessions, test_settings_auto_derived, test_setup_api,
test_setup_engine, test_setup_routes, test_shared_assets, test_site,
test_site_history, test_site_manifest_consumers, test_site_store,
test_site_store_projects_dir, test_sweep_2026_09_04_loopback_guard,
test_db_write_locks, test_bug_hunt_2026_09_24_w2_d-auth -> 664 passed, 1 skipped.

Skew / deploy order for the whole group: dashboard only. No wire key, no
schema change, nothing a companion, installer or wizard reads changes shape
(`/api/v1/site` can only lose a shared-asset entry that used to 500 the whole
response). Ships with the next dashboard in any order against companion 0.9.77.

## bug-dash-auth-2 - The session touch blocks the event loop for up to 20 s and then 500s a valid session
- Status: FIXED
- Verified as: verifier CONFIRMED (med-06). Read sessions.py: `validate` ran the once-a-minute `UPDATE ... last_seen` through `_connect()` with `BUSY_TIMEOUT_BACKGROUND_MS` (20 s) under the module `_write_lock`, and it is called inline from the async `login_gate`/`csrf_gate`. Reproduced on HEAD by the new test: 4.1 s blocked behind a 4 s BEGIN IMMEDIATE (would be 20 s and then a raise under a longer holder), and a validate() that queues forever behind a held `_write_lock`.
- Fix: `sessions.py`: new `TOUCH_BUSY_MS = 250`; `_connect`/`_run` take an optional `busy_ms`; the touch AND the delete of an expired row go through a new `_best_effort_write`, which takes `_write_lock` without waiting, uses the 250 ms busy timeout, and treats `OperationalError` as a skip (debug log). create/revoke/throttle writes keep the 20 s wait. last_seen is re-slid by the next request, so a skip costs at most a minute of idle lifetime.
- Regression test: `test_session_touch_under_a_held_write_lock_returns_fast_and_valid` (HEAD: 4.1 s > 2 s bound), `test_session_touch_skips_when_the_module_lock_is_held` (HEAD: validate() still blocked after 1 s; also checks the next lock-free request does slide last_seen).
- Tests run: see top.
- Skew / deploy order: dashboard only.
- OWED: none

## bug-dash-auth-3 - UNDO of a site change empties the project template and the shared asset folder list
- Status: FIXED
- Verified as: verifier CONFIRMED (med-06). Read `_settings_fallback` (returned "" for both csv keys), `diff_against_current` (records it as `from`), the undo route (replays `from` through `set_many`), and `_shape` (key present -> parse the row; absent -> provision defaults). HEAD test: diff `from` was `''`.
- Fix: `site_store._settings_fallback` now returns `",".join(provision.TEMPLATE_FOLDERS)` and the joined `provision.SHARED_ASSET_FOLDERS` rels, the same values `seed_from_env_once` stores. The diff's `from` is now what the site actually resolves to, so the dry-run preview is honest and an undo writes back an explicit row equal to the defaults, resolving to the same lists. `_shape` is unaffected (it only reads the fallback when the key has a row). A site whose undo already wrote "" rows cannot be told apart from an admin who cleared the list on purpose, so those are left alone.
- Regression test: `test_undo_of_a_template_change_restores_the_defaults_not_nothing` - HEAD: `from` is `''` and the lists come back empty.
- Tests run: see top.
- Skew / deploy order: dashboard only.
- OWED: none

## bug-dash-auth-4 - A shared asset folder name with no ASCII letter or digit 500s /api/v1/site and every manifest reader
- Status: FIXED
- Verified as: verifier CONFIRMED (med-06). `_validate_csv` never slugified; `provision.slugify('音效')` raises ValueError; `shared_asset_folders_for` is called from `_shape`, so every `resolved_manifest` raised. Duplicates (`Assets/SFX`, `Assets-SFX` -> `assets-sfx`) were also accepted. Same function runs at import time on `DASH_SITE_SHARED_ASSETS`, so a bad env value would have stopped the module importing.
- Fix: `site_store._validate_csv` calls new `_check_asset_folder_ids` for `shared_asset_folders`: normalises each rel the way `shared_asset_folders_for` does, refuses a name with no A-Z/0-9 and two names sharing a folder id, each with a sentence (no em dash). `provision.shared_asset_folders_for` now SKIPS (with a log warning naming the rel) an item slugify rejects or whose id is already taken, instead of raising, so a row stored before the validator (or the env value) cannot take the manifest down.
- Regression test: `test_an_asset_folder_with_no_ascii_letter_is_refused_in_words`, `test_two_asset_folders_with_one_folder_id_are_refused` (HEAD: did not raise), `test_a_stored_bad_row_is_skipped_not_raised` (HEAD: ValueError), `test_api_site_answers_with_a_stored_bad_row` (HEAD: 500). Guard: `test_a_mixed_name_with_ascii_is_still_accepted`.
- Tests run: see top.
- Skew / deploy order: dashboard only. A published manifest can now omit a bad entry that used to 500 it; companions already handle any list.
- OWED: none. (The hunter's out-of-territory note, `api.api_site` having no fallback when `resolved_manifest` raises, is no longer reachable through this finding; d-api may still want the `manifest_for_app`-style fallback as defence in depth, but nothing here needs it.)

## bug-dash-auth-1 - The anonymous first-run window opens every setup route, not only the EULA and create-admin steps
- Status: FIXED (low, downgraded from high by the verifier)
- Verified as: verifier kept it as a defence-in-depth low: shipped appliance compose binds the port to loopback before tailnet sign-in, but the code contradicts `docs/APPLIANCE_INSTALL.md` ("Steps 1 and 2 are reachable with no session") and the module docstring. Read `require_setup_access`/`first_run_open` and `static/setup.js`: before step 2 the page calls only GET `/setup/tasks`, GET/POST `/setup/eula` and `/setup/status` (setup_api, not this gate); step 2's POST `/setup/admin` signs the browser in and the page reloads, so nothing after it needs the window. HEAD test: anonymous POST `/setup/alerts` with an attacker webhook answered 200.
- Fix: `setup_routes.require_setup_access(..., first_run_ok=False)`; only `api_setup_tasks`, `api_setup_eula_get` and `api_setup_eula_accept` pass `first_run_ok=True`. Inside the window every other route (task check/run/skip, `/setup/alerts`, `/setup/alerts/test`) is a 401 "create the admin account first (step 2), then this step opens"; outside it, unchanged. Module docstring updated.
- Regression test: `test_first_run_window_opens_steps_one_and_two_only` - HEAD: alerts POST 200 and the webhook stored. Guard: `test_the_wizard_signed_in_by_step_two_reaches_the_rest` (after step 2, with the page's CSRF token, `/setup/alerts` works).
- Tests run: see top (test_setup_routes's existing local-mode window tests still pass unchanged).
- Skew / deploy order: dashboard only.
- OWED: none. (Cosmetic, optional, d-ui: `static/setup.js` still draws CHECK/DO IT/SKIP and the alerts form to an anonymous visitor; pressing them now shows the 401 sentence above. Not needed for correctness.)

## bug-dash-auth-5 - Setup reports the admin step done on an OIDC admin claim that grants nothing
- Status: FIXED
- Verified as: `auth.is_admin` reads `settings.admin_users` and (local only) the users table; `oidc.is_admin_by_claims` is used only by `require_fleet_member` and a log line (oidc.py comment: "DASH_ADMIN_USERS remains the list every authorization check reads"). `_check_admin` returned ok on the claim alone.
- Fix: `setup_engine._check_admin`: under oidc with no DASH_ADMIN_USERS the task is `todo`, telling the admin to set DASH_ADMIN_USERS and, when a claim is configured, that the claim is only logged and makes nobody an admin. With DASH_ADMIN_USERS set, the earlier `if admins:` branch still answers ok.
- Regression test: `test_oidc_claim_alone_does_not_satisfy_the_admin_step` - HEAD: status ok. Existing `tests/test_setup_engine.py::test_admin_ok_when_oidc_maps_admins_from_a_claim` pinned the old wrong behaviour; renamed to `test_admin_todo_when_oidc_has_only_a_claim` and flipped (edited because the fixed behaviour changed).
- Tests run: see top.
- Skew / deploy order: dashboard only. An oidc site relying on the claim alone will see its checklist go from green to todo, which is the truth.
- OWED: none

## bug-dash-auth-6 - The boot log misdescribes DASH_COOKIE_SECURE=true/yes/on/false/no/off
- Status: FIXED
- Verified as: `cookie_secure()` accepts 1/true/yes/on and 0/false/no/off; `describe_auth` mapped only "1"/"0".
- Fix: `auth.py`: module constants `_COOKIE_SECURE_ON` / `_COOKIE_SECURE_OFF`, used by both `cookie_secure()` and `describe_auth()`. (`check_boot_secrets`' two literal tuples hold the same values and were left alone.)
- Regression test: `test_boot_line_names_the_cookie_mode_cookie_secure_obeys[true|yes|on|false|no|off]` - HEAD: "follows the request scheme".
- Tests run: see top.
- Skew / deploy order: dashboard only (log line).
- OWED: none

## bug-dash-auth-7 - A trusted proxy's X-Forwarded-For is read from the client-controlled left end
- Status: FIXED
- Verified as: `client_ip` took `split(",")[0]` for a trusted peer. An appending proxy (nginx `$proxy_add_x_forwarded_for`) keeps the client's own value at the left, so the login-throttle IP bucket was client-chosen. Tailscale Serve sends one element, which both readings agree on. No test covered X-Forwarded-For at all.
- Fix: `auth.client_ip` walks the header from the right and returns the first address that is not in DASH_TRUSTED_PROXIES; a non-address at the right end falls back to the peer; if every hop is trusted it returns the leftmost (the old answer). Untrusted peers still ignore the header.
- Regression test: `test_an_appending_proxy_is_read_from_the_right`, `test_trusted_hops_on_the_right_are_walked_past`, `test_garbage_at_the_right_end_falls_back_to_the_peer` - HEAD returns the left element. Guards: single hop, untrusted peer.
- Tests run: see top.
- Skew / deploy order: dashboard only. Affects only sites with a proxy in DASH_TRUSTED_PROXIES that appends; there the throttle and the sessions page now show the address the proxy saw.
- OWED: none

# Owed round (2026-09-25)

Four items routed from d-ui. Tests: `dashboard/tests/test_bug_hunt_2026_09_24_w2_d-auth.py`
(section "owed round"). Proof they fail on the pre-owed code: the package was
copied to the scratchpad, these edits reversed in the copy, and the file run
there (src layout, same conftest): the stale-undo test, the button-name test,
five of the six copy-scan cases and the export-header test fail; all pass on
the tree.

Tests run: `cd dashboard; .venv\Scripts\python.exe -m pytest
tests/test_bug_hunt_2026_09_24_w2_d-auth.py tests/test_site_history.py` -> 58
passed; `tests/test_oidc.py test_setup_api.py test_setup_engine.py
test_setup_routes.py test_site_store.py test_site_store_projects_dir.py
test_project_setup.py` (plus the two above) -> 238 passed.

## ui-dash-static-3 (owed half) - the undo route checks which change the admin confirmed
- Status: FIXED
- Verified as: d-ui's ledger entry. `api_admin_site_undo_last_change` reverted `entries[0]` whatever the page had confirmed, so a second tab or second admin saving between page load and the click was undone unseen. d-ui's `site_settings.js` already posts `{"expected_at": latest.at}`.
- Fix: `dashboard/src/ccsync_dashboard/setup_routes.py`: new `SiteUndoIn` (`expected_at: str | None`, max 64), taken as an OPTIONAL body (`payload: SiteUndoIn | None = None`). When it is non-empty and differs from `entries[0]["at"]`, 409 "the newest change is no longer the one you confirmed (someone saved since): reload the page", checked right after the empty-history 404 and before anything is read or written. No body, `{}`, `""` or `null` keep today's behaviour (older pages, the JSON door, test_site_history).
- Residual: `at` is second-precision (`db.utcnow_iso`), so two changes stamped in the same second cannot be told apart by this check. The client reloads the history after its own saves, so the remaining window is two admins saving within one second of each other; not worth a d-db change to the stamp.
- Regression test: `test_an_undo_of_a_change_that_is_no_longer_newest_is_refused` (the pre-owed route ignored the body and reverted maria's R:), `test_an_undo_of_the_newest_change_it_names_goes_through`, `test_an_undo_with_no_expected_at_keeps_the_old_behaviour` (4 body shapes).
- Skew / deploy order: dashboard only; page and route are one deploy. Each half tolerates the other's absence (old route ignores the body; new route treats no body as no check).
- OWED: none

## ui-dash-admin-14 (owed half) - comments name [ UNDO LAST IMPORT ]
- Status: FIXED
- Verified as: grep; setup_routes.py named the old label three times (import's no-op comment, the history docstring, the undo docstring).
- Fix: all three now say `[ UNDO LAST CHANGE ]`. Comments only.
- Regression test: `test_setup_routes_names_the_undo_button_by_its_label` (source grep; fails on the old text).
- Skew / deploy order: none (no behaviour).
- OWED: none

## ui-copy-6 (owed half) - " -- " in d-auth's user-visible strings
- Status: FIXED
- Verified as: read each listed line. User-visible: setup_engine.py task description (admin), both "not yet probed" details, the DASH_PROJECTS_DIR detail, the "generated N just now" detail (setup wizard); app.py's CSRF 403 `detail`; oidc.py's three HTTP `detail`s (IdP unreachable, expired state, bad state); setup_routes.py's "no automatic action" 400; site_store.py's export header (the admin downloads it). NOT changed, with reasons: setup_engine.py:756 is the probe file's contents, written, read back and deleted in one motion, never shown; sessions.py:93 is inside the `SCHEMA` DDL string (an SQL `--` comment beside a column), not copy. The app.py:541/546 and site_store.py:561 hits are log lines (exempt).
- Fix: each now uses a colon or two sentences: `setup_engine.py` (admin description, lines ~738/742/751, ~866), `app.py` CSRF refusal, `oidc.py` (252, 460, 464), `setup_routes.py:191`, `site_store.py:899` (a comma). No test pinned the old wording (grep).
- Regression test: `test_visible_copy_in_the_auth_modules_has_no_typewriter_dash[*]` (AST scan of `detail=`/`description=` keywords and `{"detail": ...}` dicts in the six modules), `test_the_exported_toml_header_has_no_typewriter_dash`.
- Skew / deploy order: dashboard only. The TOML header is a comment, which `import_toml` ignores, so an old export still imports.
- OWED: none

## ui-copy-7 (owed half) - dashboard/README.md names [ LOGOUT ] / [ LOGOUT ALL ]
- Status: FIXED
- Verified as: README lines 105-106.
- Fix: `dashboard/README.md` now says `[ SIGN OUT ]` and `[ SIGN OUT EVERYWHERE ]`. Doc only.
- Regression test: none (a README wording change has no behaviour to pin).
- Skew / deploy order: none.
- OWED: none
