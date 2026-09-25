# Group B: auth, sessions, password (account page 2026-09-25)

Built from `docs/ACCOUNT_PAGE_FEATURES.md` sections 3.3, 3.4, 7 (group B) and
the group B row of section 8. Owner decisions D-1, D-2, D-3 and D-13 taken at
their recommended defaults (always sign the other browsers out; re-issue this
browser's cookie; wrong "current password" tries share the sign-in budgets;
the list never signs out THIS browser).

## Files

- `dashboard/src/ccsync_dashboard/auth.py`: NEW `admin_source(settings,
  username, conn=None) -> str` ("admin_list" | "local_role" | ""), plus the two
  constants `ADMIN_SOURCE_LIST` / `ADMIN_SOURCE_LOCAL_ROLE`. Same order and
  rules as `is_admin`, so the two can never disagree (tested).
- `dashboard/src/ccsync_dashboard/sessions.py`:
  - NEW `describe_client(client) -> {"ip", "browser"}`: words we chose
    ("Chrome, Windows", "Safari, iPhone", "python-urllib", "Unknown browser",
    "" when nothing was recorded), never the raw User-Agent. Never raises.
  - NEW `SessionStore.revoke_by_handle(username, handle, *, by,
    except_sid=None, now=None) -> int`: 1 revoked / 0 none (also for a
    malformed handle); raises `ValueError("ambiguous")` on >1 match and
    `ValueError("current")` when the one match is `except_sid`. Username-scoped
    in SQL, `substr` not `LIKE` (a `%` can never widen it), select + update in
    one transaction under the module lock.
  - NEW `SESSION_HANDLE_CHARS = 12`, `session_handle(sid)`,
    `is_session_handle(handle)` (helpers; C kept its own copy, which is fine).
  - `_UA_SUMMARY_CHARS` 80 -> 200. At 80 a desktop Chrome/Edge UA was cut
    inside "(KHTML, like Gecko)", before the only token naming the browser, so
    the page could never have said "Chrome". Rows written before this still
    describe as their system only ("Windows"), which is honest.
- NEW `dashboard/src/ccsync_dashboard/account_password.py`:
  `PasswordChangeResult`, `change_own_password(...)`,
  `rotate_after_password_change(...)` with the pinned signatures of 3.3.1, and
  every 3.3 sentence as a `MSG_*` constant (no em dash, tested).
- NEW `dashboard/tests/test_account_password.py` (33 tests, smb cases run
  against both NAS fakes via `nas_case`)
- NEW `dashboard/tests/test_account_sessions.py` (35 tests)

## Two deliberate departures from the spec's wording (same outcome)

1. **`change_own_password` COMMITS `conn` on success.** The spec leaves the
   commit to the route after `rotate_after_password_change`. Measured: the
   audit INSERT (and on local the hash UPDATE) holds the SQLite write lock on
   the request connection, and the rotation writes through the session
   store's own connection, so the rotation waited out the 20 s busy timeout
   and failed, leaving the other browsers signed in. Committing inside means
   the route order C already wrote (change, rotate, commit) works unchanged;
   its commit is a no-op, and its `rollback()` on a refusal is harmless
   (nothing was written).
2. **The rotation mints the new session FIRST, then revokes everything else
   (`except_sid` = the new sid)**, instead of "revoke all, then mint". End
   state identical; but a failed mint now leaves this browser signed in on its
   old session while every OTHER session is still revoked (review round
   fix, below), and a failed revoke leaves it signed in
   on the new one. The returned count is revoked minus this browser's old
   session.
3. (Minor) On `local`, a `DASH_ADMIN_USERS` name with no local row is refused
   with the 409 sentence BEFORE the current password is verified, not at step
   8: the local verifier answers False for a missing row, so the spec's order
   would have charged a sign-in failure and said "That is not your current
   password" to someone who typed it correctly. The step-8 `LocalUserError`
   catch is kept for a row deleted mid-request.

The audit's `other_sessions_signed_out` is counted in `change_own_password`
(live sessions of the user other than this one), just before the rotation
revokes them; the route answers the rotation's own count.

Secrets: no password, typed, old or new, nor its length, is logged, audited
or returned. A NAS error's text is logged at warning with both passwords
masked (`***`) and never returned (tested with a NAS error that echoes the new
password, and a caplog scan over a full success).

## Tests run

- `tests/test_account_password.py tests/test_account_sessions.py`: 68 passed.
- Existing suites that exercise what changed: `test_auth.py`,
  `test_bug_hunt_2026_09_24_w2_d-auth.py`, `test_admin_users_local.py`,
  `test_no_em_dash.py` (247 passed); `test_admin_users.py`,
  `test_bug_hunt_2026_09_24_w2_d-api.py`, `test_bug_hunt_2026_09_24_w2_d-ui.py`,
  `test_hardening.py` (213 passed).

The password tests drive the real request path through a harness route that
is 3.3's route shape verbatim (C's `POST /api/v1/me/password` did not exist
when they were written); C's own tests cover the real route.

## Owed to / notes for other groups

- **C**: nothing required. `account_api.change_password` already matches
  (its commit after the rotation is now a no-op). `revoke_own_session`
  already maps `ValueError("current")` and `"ambiguous"`.
- **A**: `account_password` reads `db.AUDIT_ACCOUNT_PASSWORD` through
  `getattr` with the pinned literal as fallback, so it works before or after
  A's constants merge.
- **D**: `docs/API.md` sentences for `/api/v1/me/password` are the `MSG_*`
  constants in `account_password.py`, verbatim from 3.3; one extra refusal
  exists for a sign-in method this build does not know (409, `MSG_UNKNOWN_METHOD`),
  unreachable on a booted dashboard (boot refuses an unknown method).
- **Orchestrator**: the admin sessions page (`api_admin_sessions`) shows the
  raw `client` column, which is now up to 200 characters of UA instead of 80
  for new sessions.

## Review round (2026-09-25)

1. **Medium, fixed: a failed mint left every other browser signed in.**
   `account_password.rotate_after_password_change` now, when
   `auth.start_session` raises, still calls
   `store.revoke_user(user, by=..., except_sid=old_sid)`: the others are
   signed out (D-1 "always") and this browser keeps its old session. If that
   revoke fails too, it logs and returns None (never raises). The departure
   from the spec's order (mint first, then revoke all but the new sid) stays,
   and now every failure lands safe. Test
   `test_rotation_failure_to_mint_revokes_nothing` is replaced by
   `test_rotation_failure_to_mint_still_signs_the_others_out` (a second tchen
   session is revoked, count 1, the asking one still validates) and
   `test_rotation_failure_to_mint_and_to_revoke_is_not_raised`.
2. **Low, fixed: "cros" matched inside "Microsoft".** `sessions._SYSTEM_TOKENS`
   now matches `"cros "` (with the space). The WSLg Firefox UA
   (-> "Firefox, Linux") and a real ChromeOS UA (-> "Chrome, ChromeOS") are
   in `test_describe_client_names_real_user_agents`.
3. **Low, fixed: a non-NasError from the NAS client setup was a 500.**
   `change_own_password` also catches `Exception` around
   `make_nas_client` / `is_editor`, logs the type and the masked text, and
   answers the 502 `MSG_NAS_UNREACHABLE`. Test
   `test_smb_nas_setup_error_of_any_kind_is_a_502_not_a_500` (both NAS kinds:
   502, no host text in the response, neither password in the log, the NAS
   password never set).

Tests: `test_account_password.py` + `test_account_sessions.py` 73 passed;
`test_account_api.py` + `test_account_page.py` (group C's real route) 87 passed.
