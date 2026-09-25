# Fable review: the /account page features (2026-09-25)

Final reviewer's pass over the six groups' work (A schema/db, B auth/sessions/
password, C JSON routes, D the wire, E the companion, F the page and display
names), built from `docs/ACCOUNT_PAGE_FEATURES.md` on top of `f9d5176`,
uncommitted. Read-only: every file in the diff was read end to end, the pinned
signatures were traced to their callers, the test files the feature touches
were run (dashboard 722 passed, companion 443 passed, copy sweep 330 passed +
1 failed, below), and two scratch probes drove the real app and the real
companion module across the wire in both directions. No live system was
touched.

## Verdict

**Ship-shape as a feature; the commit is blocked by one red gate test and one
scope decision.** Nothing found breaks an existing surface, every permission
fence held under probing, the password change is safe, the settings-request
round trip works with the companion's own bytes, and the display name is a
label everywhere (no key, no wire, no alert, no tool reads it).

| # | Feature | Verdict |
|---|---|---|
| F1 / F1a | Display name (self, and admin for others) | OK. NFC + casefold "taken" check across sign-in names, local users, `admin_users` and other profiles; the check and the upsert are one `BEGIN IMMEDIATE` section (`db.py` `set_display_name`); the label reaches only `ui._render`, `cards_landing` phrases and the templates. Audit actor is always the sign-in name (probed: `account.display_name` actor `mallory`). |
| F2 | Change your own password | OK. Probed on `local` with strict sessions: five wrong tries 422, the sixth 429 `Retry-After: 60` and `/api/v1/login` throttled with it (D-3 as decided); success rotates this browser's cookie AND csrf (old csrf 403s, new one works), the other browser and the old cookie 401, the old password no longer signs in, the audit row carries `{method, other_sessions_signed_out}` only, nothing typed appears in any log record, and an over-long field is one sentence with no echo. NAS (`smb`) and `oidc` paths read correct; B's tests run them against both NAS fakes. |
| F3 / F3a / F3b | Signed-in browsers | OK. Own rows only (probed: another person's 12-hex handle answers 404 and their session survives); the current session is refused; `revoke_by_handle` is username-scoped in SQL with `substr`, not `LIKE`. |
| F4 | Sync keys | OK. Fingerprints and comments only; `key_text` never in the answer; NAS read on `smb` only; `NasError` and any other exception become the `unreadable` sentence with the waiting half still shown. |
| F5 | Ask a computer to change fleet-jobs settings | OK. Owner or admin only (probed: 403 for another editor, 422 for `mode`, 422 for `jobs_kinds: []`, 409 with the 4.7 sentence for a companion with no section); one row per computer, merge under a new id, withdraw, expire via `prune()`, forget-machine and forget-editor delete it, rename carries a pending ask (A's review fix). |
| F6 | Reported settings | OK. `store_machine_settings(None)` leaves the columns alone; a section is rebuilt from validated fields (no cookie, path or yt-dlp `reason` can be stored). |
| F7 | The page | OK. Always the session user; `?as=` ignored; password and YOU panels outside every poll; `?changed=` parsed as an int and clamped; every write partial needs a session and CSRF. |
| Wire | `machine_settings` section + `commands.machine_settings` | OK, probed with the companion's real section: no command before an ask; the command rides once asked with `delivered_at` set once; the companion's `applied` for that id finalises the row on that same reply (audit actor = the editor) and the command stops; a stale `applied` for an OLD id does not stop a NEWER ask; a future word (`something-new`) leaves it pending with its detail; withdrawn rows are not sent. |
| Companion | `machine_settings.py`, `app.py`, `reporter.py` | OK, probed against a real `config.toml`: applied writes `jobs_enabled = false` / `jobs_kinds = "peaks"` and the rest of the file byte for byte; a redelivered id answers from the ledger with no write; a `set` naming `mode` is refused whole with nothing written; the section carries `pending_restart` with the ON-DISK values and the ledger's last answer. |

## Problems, ranked

### 1. BLOCKS THE COMMIT: one red gate test (retired word)

`dashboard/src/ccsync_dashboard/db.py:12163`
`raise ValueError("no machine setting to request")` trips
`tests/test_sweep_2026_09_04_copy.py::test_no_retired_word_in_python_copy[db.py]`
(CR-181: "machine" is retired in copy; say "computer"). Confirmed red by running
the file: 330 passed, 1 failed. Group F's ledger flagged it; group A never took
it. The sentence is unreachable from a route (the route refuses first), so the
fix is a one-word edit or a `# noqa`-style allowance in that test's list. Until
it is fixed `tools\run_all_tests.ps1` reports a failed suite and `ship.cmd`'s
gate is red.

### 2. BLOCKS A `git commit -a` AS-IS: the tree carries an unrelated legal-docs pass, including an EULA version bump

The working tree also holds changes that are NOT the account page:
`docs/legal/{EULA,PRIVACY,TELEMETRY,THIRD_PARTY_NOTICES,YOUTUBE_FEATURE_NOTICE}.md`,
`companion/src/ccsync_companion/assets/EULA.md`, `onboarding/assets/EULA.md`,
`tools/gen_notices.py`, `docs/README.md`, `docs/TRANSFER_SPEED.md`, and the two
untracked plans `docs/LEGAL_GAP_FEATURES_PLAN.md`,
`docs/UI_REDESIGN_PORT_PLAN.md`. Among them the EULA marker moves
`<!-- EULA-VERSION: 1.0 -->` to `1.1` in all three copies. Per CLAUDE.md,
"bumping it pushes every editor in every fleet back through the wizard" on the
next companion release. That may well be intended (the docs are marked final
after counsel), but it is a fleet-visible consequence riding on an account-page
commit. Decide deliberately: commit the legal pass separately with its own
message, or state it in this commit's message. Not reviewed here beyond that.

### 3. OWED BEFORE SHIP, not before commit

- **Version bumps not done** (spec section 0.3): `dashboard/pyproject.toml` is
  still `0.7.59`, `companion/config.py` `VERSION` and `companion/pyproject.toml`
  still `0.9.79`. `ship.cmd` refuses a companion version already published, and
  the companion's wire changed, so this is a real ship blocker: 0.7.60 / 0.9.80.
- **The CLAUDE.md invariant paragraph** (hand-off 6) is not written: the display
  name is a label never a key; `commands.machine_settings` is standing and
  capability-gated by `cfg_accepts`; `mode` is never requestable.
- **Deploy order is the dashboard first**, and the live effect of a
  dashboard-only deploy is inert: every F5 control renders the 4.7 "too old"
  sentence until a companion advertises `accepts` (probed: a machine with no
  section 409s and never receives a command). A companion reporting to the OLD
  dashboard lands on the SYS-3 banner on every report (noise only).

### 4. Low: an absent `pending_restart` is stored as `{}`

`db.py` `store_machine_settings` -> `_clean_pending_restart(None)` returns `{}`,
so a companion that LEFT THE KEY OUT (E's review fix: config.toml unreadable or
unparseable with no backup) is stored as "nothing waiting". Consequences are
contained: `account_ui.request_status` (`account_ui.py:131-151`) says "In
effect." only when the RUNNING value matches the ask, so the worst case is the
"saved it" line staying up, and `_wanted` falls back to the running values for
the boxes. Fix when convenient: store NULL for an absent key and let the page
say it cannot tell what is saved there. Group E's ledger already owes this to D.

### 5. Low: two unlocked writers of `config.toml`

`companion/config.py:1542` `set_value` writes through a fixed
`config.toml.tmp` + `os.replace` with no lock. The tray's settings window (Tk
thread) and `machine_settings.apply_request` (reporter thread) can now both
call it. A simultaneous click and apply can lose one write or answer `failed`
(retried after 300 s, so the dashboard's ask is not lost). Rare in practice; a
module-level lock in `config.set_value` closes it. Outside every group's files
(E's ledger item 6).

### 6. Low: two spec-pinned sentences mislead in the rollback case

When a rollback shrinks `accepts`, `api.py`'s withhold rule (review round, D)
keeps the request pending and never marks it delivered, so the page says
"Asked ... gets it the next time it reports in" while the machine reports every
30 s, and after 14 days "did not report in for 14 days, so the request was
dropped" when it did. Both sentences are the spec's (4.5). A third line for
"reported, but its CCSync no longer takes this" would be honest; owner's call.

### 7. Low: each computer panel rebuilds the whole fleet view every 30 s

`account_api.build_account_view` calls `api.build_editors_view(conn, now)`
(the fleet grid's full builder) and `partial_account_computer` calls it once
per panel poll, so N open computer panels cost N fleet builds per 30 s on top
of the grid's own 15 s cycle. Fine for this fleet's size; a per-machine
builder would be the fix if the page ever feels slow.

### 8. Low: names that look like a colleague's

A's note 3: NFC + casefold (as the spec pins) lets full-width or Cyrillic
look-alikes of a sign-in name through; and a display name such as
`ruskin (admin)` renders as-is in the fleet grid's EDITOR cell. Every surface
keeps the sign-in name in a `title` or a muted line beneath (6.2), so it
cannot pass as a key, but an NFKC or confusables check is an owner decision.

### 9. Trivial

- `db.forget_editor` and `delete_user_everywhere` do not call
  `invalidate_display_names`, so a departed person's name can show for up to
  30 s on a page already open. The next cache expiry clears it.
- The Users page's SHOWN AS box sits inside the panel's 30 s poll, like the
  SET PASSWORD boxes beside it (F noted).
- `_UA_SUMMARY_CHARS` 80 -> 200 (B) makes the admin sessions page show up to
  200 characters of raw UA for new rows.

## What was verified, with the lines

- **Pinned signatures match their callers.** `db.set_display_name(..., other_usernames=)` (A's keyword addition) is what `account_api._write_display_name` passes (`account_api.py:388`); `sessions.SessionStore.revoke_by_handle(username, handle, *, by, except_sid)` raises `ValueError("ambiguous"|"current")`, both mapped at `account_api.py:580-583`; `account_password.change_own_password` / `rotate_after_password_change` called as pinned at `account_api.py:470,480`; `auth.admin_source(settings, username)` at `account_api.py:311`; `api.build_editors_view` returns `editors` and `lost_machines` with `editor_username`/`machine`/`capabilities`/`received_at` (api.py:963-1253); `api._require_admin(request)`; `db.audit(conn, actor, action, subject, detail, now=)`; `DashboardReporter(get_machine_settings=)` (reporter.py:474) wired from `companion/app.py:2375`; `machine_settings.apply_request/report_section/change_sentence/answer_for/ledger_path_of` called from `companion/app.py:8509-8563` with the pinned shapes.
- **Fail closed on auth.** `app.py:56` `_OPEN_EXACT` has `/api/v1/me` exact; `app.py:186` matches `path in _OPEN_EXACT` only (probed: `/api/v1/me/sessions` 401 anonymous, `/api/v1/me` 200). No new path in `_CSRF_EXEMPT_*`; `_CSRF_METHODS` covers PUT and DELETE (`app.py:256`; probed: a PUT without the token 403s and writes nothing).
- **The password rotation is correct in this codebase**, not just in the spec: `auth.start_session` (auth.py:682-712) resets `request.state.ccsync_session` to the new sid, so `auth.csrf_token(request)` at `account_api.py:485` is the NEW session's token; `change_own_password` commits before the rotation (`account_password.py:237`) because the store writes through its own connection; the partial (`account_ui.py:569-588`) returns the very `Response` `start_session` set the cookie on, with `HX-Redirect`. `db.connect` is `check_same_thread=False` (db.py:714), so handing `conn` to `run_in_threadpool` is safe.
- **The verifier is the sign-in page's** (`api.py:2154` and `account_password.py:176` read the same `app.state.credential_verifier` with the same `(settings, user, password)` call), and the throttle is `auth.login_throttled(request, user)` keyed like `/api/v1/login`.
- **The report handler writes the section AFTER `_register_machine` + `upsert_machine_state`** (api.py:10024 / 10182-10205), so the `UPDATE machine_state` in `store_machine_settings` has a row; the answer is written with the report's own commit BEFORE the commands block (api.py:10553-10572), which is why an `applied` stops the command on the same reply (probed).
- **`mode` cannot enter from either side.** `MachineSettingsIn._only_whitelisted_keys` (api.py) filters `accepts` to `db.MACHINE_SETTING_KEYS`; `db._clean_machine_settings` is the storage floor; the reply filters `set` again; the companion's `_validate` refuses the whole request on any key outside `ACCEPTS` (probed: refused, config untouched).
- **The display name is a label.** `display_names_for` is consumed only by `ui._render` (ui.py:211), `cards_landing._display_names` (cards_landing.py:84) and the templates; nothing under `alerts.py`, `tools/`, `ytdl`, `broll`, `music` or the companion reads it. `requested_by`, `revoked_by`, every audit actor and every hidden `editor` form field carry `acct.user`, the sign-in name.
- **Round trips.** Ask -> deliver -> apply -> acknowledge -> final; refuse (whole); `failed` / future word stays pending with detail; expire via `prune()` (A's tests); withdraw (probed 200); forget-machine deletes the request and the `cfg_*` row (probed: both `None` afterwards); rename adoption carries a pending ask over an answered row at the new name (A's review tests).
- **Tk thread hazards (CR-93).** The reporter thread now imports `tray` (`_ytdl_attested`: a file read, tray.py:1559) and `settings_window` (`_kind_label`: a dict lookup, settings_window.py:1248). Neither builds a Tk object; both modules are already imported by the main thread in the running app.

## Tests run

- Dashboard (`dashboard\.venv`): `test_account_api test_account_db test_account_page test_account_password test_account_sessions test_machine_settings_wire test_no_em_dash test_db test_report_endpoint test_sessions test_auth test_jobs_contract test_bug_hunt_2026_09_18b_collector_core test_admin_users test_admin_users_local test_capabilities_report test_fleet_audit test_topbar_partial`: 722 passed. `test_sweep_2026_09_04_copy.py`: 330 passed, 1 skipped, 1 failed (item 1).
- Companion (`companion\.venv`): `test_machine_settings test_reporter test_app_contract test_no_em_dash test_config`: 443 passed.
- Scratch probes (session scratchpad, not in the tree): `probe_companion.py` (apply, redeliver, `mode`, real section), `probe_dashboard.py` (the wire round trip with the companion's section, skew, withdraw, forget, twelve permission fences), `probe_password.py` (local auth, strict sessions, throttle, rotation, logs).

## What blocks the commit

1. Fix `db.py:12163` (one word) and re-run `tests/test_sweep_2026_09_04_copy.py`.
2. Decide the commit's scope: the legal-docs pass with the EULA 1.0 -> 1.1 bump is in the same tree.

Then bump the two versions and add the CLAUDE.md paragraph before shipping;
deploy the dashboard first.
