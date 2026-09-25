# Group C: the account JSON routes (account page 2026-09-25)

Built from `docs/ACCOUNT_PAGE_FEATURES.md` sections 3 and 7 (group C row of
section 8). Owner decisions D-1..D-15 taken at their recommended defaults.

## Files

- NEW `dashboard/src/ccsync_dashboard/account_api.py`
- `dashboard/src/ccsync_dashboard/app.py`: one hunk, `account_api.router` and
  `account_ui.router` included right before `ui.router` (imported in place, as
  `android` is). No change to `_OPEN_EXACT` or any CSRF-exempt list.
- NEW `dashboard/tests/test_account_api.py` (45 tests)

## What is in account_api.py

Routes (`router = APIRouter(prefix="/api/v1")`), all session-gated, every write
CSRF-checked by the existing gate, the blocking ones plain `def`:

| Route | Service the partial calls |
|---|---|
| `GET /me/account` | `build_account_view(request, conn)` |
| `PUT /me/display-name` | `set_own_display_name(request, conn, display_name)` |
| `PUT /admin/users/{username}/display-name` | `set_user_display_name(request, conn, username, display_name)` |
| `POST /me/password` | `change_password(request, response, conn, *, current_password, new_password, new_password_again)` |
| `GET /me/sessions` | `list_own_sessions(request, conn=None)` |
| `POST /me/sessions/{handle}/revoke` | `revoke_own_session(request, conn, handle)` |
| `POST /me/sessions/revoke-others` | `revoke_own_other_sessions(request, conn)` |
| `GET /me/sync-keys` | `build_sync_keys_view(settings, conn, user)` |
| `POST /machines/{editor}/{machine}/settings` | `ask_machine_settings(request, conn, editor, machine, body)` |
| `DELETE /machines/{editor}/{machine}/settings` | `withdraw_machine_settings(request, conn, editor, machine)` |

Plus 3.8: `display_names_for(app)` (30 s cache on
`app.state.display_names_cache`, `{}` on any error), `invalidate_display_names(app)`,
`shown_as(names, username)`. Every service raises `HTTPException` with the
spec's sentences, which are module constants (`NAME_TAKEN`, `SESSION_GONE`,
`MACHINE_TOO_OLD`, ...) so group F can render or compare them.

Decisions made where the spec was silent:

- **The password service is `account_api.change_password`** (the spec names the
  seven other services but not this one; hand-off 3 says F reaches B's code
  "through C's service"). It does step 1, calls B's `change_own_password`,
  then `rotate_after_password_change`, commits and answers with the NEW csrf.
  B's function already writes the audit row and the step-10 warning line, so
  the route does not log a second one. On a refusal it rolls back and raises
  with `Retry-After` for a 429.
- **Wrong TYPES in a settings ask** have no spec sentence: `jobs_enabled` not a
  bool answers 422 `Let the fleet use this computer must be on or off.`; a
  `jobs_kinds` that is not a list answers `The kinds of work must be a list.`
  A JSON body that is not an object answers the whitelist sentence.
- **`needed`** (sync keys) is true when the person has NO computers yet: the
  first one will need a key; "none needed" is only when every computer is
  wired.
- **Session list filters out expired-but-unswept rows** (idle or absolute
  lifetime passed), so the page never offers SIGN OUT for a browser that is
  already signed out.
- **Computer entries** add `lost` (a `db.lost_machines` row) beside the pinned
  fields; `live` is the grid's own freshness rule (`health.report_freshness`
  green). `jobs.enabled` is `null` when the computer never sent capabilities.
- **Display-name refusal wording** uses db.py's sentence when it is one of the
  spec's three, else classifies from the text, so the page's words are the
  spec's exactly whatever db.py says.
- `set_display_name` is called with A's keyword `other_usernames=` (A added it;
  it carries `settings.admin_users`, which the database cannot see).
- An unchanged ask (`{"ok": true, "unchanged": true}`) needs the computer to
  have reported capabilities at all; with none, it is stored as an ask.

## Tests run

`dashboard\.venv\Scripts\python.exe -m pytest tests/test_account_api.py
tests/test_sessions.py tests/test_no_em_dash.py` : 224 passed.
`tests/test_bug_hunt_2026_09_18b_collector_core.py tests/test_jobs_contract.py`
(route inventories): 27 passed.

`test_account_api.py` covers: 401 on every route with no session; 403 on
every write with no CSRF token from a tracked session (and nothing written);
no new path open or exempt; view shape, `?as=` ignored, suspended, a companion
with no section (settings null, too-old sentence), OIDC facts (issuer host
only); display name set/clear/NFC/refusals (empty, 65 chars, RLO, ZWJ, control,
another's sign-in name, another's display name, own sign-in name allowed, 257
chars), audit rows with actor = sign-in name, admin set/clear, unknown account
404, editor refused on the admin route and unable to name anyone else through
the self route, cache fails open; sessions list/revoke one/this browser 409/
another person's handle 404 and untouched/bad handle 422/revoke others/store
absent 503; sync keys pending + TrueNAS-shaped approved with the machine from
the exact-subject audit row, DSM `(installed)`, NAS error (`unreadable`,
waiting half still listed, backend text not in the answer), never another
person's, local approved + `needed`, no `key_text` or key body anywhere;
machine asks: owner ask + merge + withdraw, editor 403 on someone else's, admin
allowed and audited, whitelist (`mode`, volunteer minutes, empty, non-object,
unknown kind, bad type), every kind stored as `[]`, unknown machine 404, too
old / not reported / half-accepting companion 409, unchanged stores nothing
and a differing on-disk value makes it a real ask; password (local) rotates
this browser's cookie and csrf, signs the other out, the old csrf 403s, audit
and logs carry no password, mismatch/wrong-current sentences, the throttle's
429 with Retry-After, OIDC 409; no em dash in any sentence.

The suite runs with `DASH_DEV_INSECURE` removed (strict), because under the dev
flag a revoked cookie still signs in.

## Owed to other groups

- **F**: call the services above; the password partial should catch the
  `HTTPException` from `change_password` for the result fragment and, on
  success, answer `HX-Redirect: /account?changed=password&others=<n>` using
  `other_sessions_signed_out`. `account_ui.router` must keep existing (app.py
  imports it).
- **D**: `docs/API.md` for the routes above, including the two extra 422
  sentences for wrong types and the `lost` / `withdrawn` extras in answers.
- Nothing owed by A or B: every pinned signature was present and is used as
  pinned (plus A's `other_usernames=` keyword and B's `ValueError("current")`
  from `revoke_by_handle`, both handled).

## Review round (adversarial review, account page 2026-09-25)

Files touched: `dashboard/src/ccsync_dashboard/account_api.py`,
`dashboard/tests/test_account_api.py` (now 63 tests). `app.py` unchanged.

1. **Password echoed in a 422** - FIXED. `POST /me/password` no longer takes
   `ChangePasswordIn` as a FastAPI body parameter: it takes `Any` and
   validates with `ChangePasswordIn.model_validate` by hand
   (`_password_body`), so an over-long, wrongly typed or non-object body is
   422 `A password must be text of at most 1024 characters. Nothing changed.`
   (new constant `PASSWORD_BAD_FIELD`) with no `input`. The 401 is checked
   first. Probed: 1100-char field, int, list, form body, text body all clean;
   a malformed JSON document still gets FastAPI's `json_invalid` shape, whose
   `input` is `{}` (nothing typed). `/api/v1/login` keeps the old shape (not
   group C's file).
2. **Display-name cache race** - FIXED. `invalidate_display_names` bumps
   `app.state.display_names_generation`; `display_names_for` reads it before
   the DB read and stores only if it is unchanged.
3. **Sign-out-others count** - FIXED. The count (answer, audit row, log) is
   the number of LIVE other browsers (the list's own `_live` rule), capped by
   what `revoke_user` revoked. Expired rows are still revoked, just not counted.
4. **Unchanged check** - FIXED for kinds: `_running_kinds` answers None
   ("cannot tell") for a running list holding a kind this dashboard does not
   know, or a non-list, so the ask is stored. `jobs_enabled` is compared with
   `is not v`, so a missing or non-bool value is never "unchanged". Evidence
   that the missing case cannot reach here from the DB anyway:
   `db.store_machine_capabilities` stores `bool(caps.get("jobs_enabled", True))`
   and `machine_capabilities` reads back `bool(...)`; a NULL `cap_job_kinds`
   reads back `[]` = every kind (the scheduler's own contract), which the
   check keeps.
5. **`jobs_kinds: []`** - FIXED by refusing it: 422 with 4.8's sentence
   (`MACHINE_KINDS_EMPTY`, same words as `account_ui.LAST_KIND`). "Every kind"
   is asked by naming every kind (stored as `[]` as before). `account_ui`
   already refuses the last untick before calling the service, so the page is
   unaffected (test_account_page.py green).
6. **Sync keys on oidc / non-NasError** - FIXED. The NAS is read on `smb`
   only; any other exception from `make_nas_client`/`find_user` is the
   `unreadable` sentence, logging only the exception type.
7. **Admin display-name wording** - 401 FIXED (the service calls
   `_require_user` first, so a partial calling it sees `Sign in first.`).
   The 403 stays `admins only`: spec 3.2 pins `api._require_admin` for that
   route and names no 403 sentence.
8. **Test gaps** - FIXED: the CSRF test now checks owen's own name stays
   unset, his second browser stays signed in, his session list is unchanged
   and no sign-out audit row exists; `test_account_view_lists_a_lost_computer`
   covers the lost path (and never another person's lost row); password field
   over-length/wrong type/non-object tests; plus tests for 2-6.

Tests run: `tests/test_account_api.py` 63 passed; with
`test_account_page.py test_account_sessions.py test_account_password.py
test_account_db.py test_machine_settings_wire.py test_no_em_dash.py
test_jobs_contract.py test_bug_hunt_2026_09_18b_collector_core.py`: 395 passed.

Owed to **D** (`docs/API.md`): `POST /me/password` 422 `A password must be
text of at most 1024 characters. Nothing changed.`; `jobs_kinds: []` is
refused 422 with the 4.8 sentence (send every kind to mean every kind); the
sign-out-others `revoked` count is live browsers only; sync keys read from the
NAS on `smb` only.
