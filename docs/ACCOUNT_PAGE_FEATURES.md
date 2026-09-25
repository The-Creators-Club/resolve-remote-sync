# The account page: build spec

Written 2026-09-25, from the owner's ask the same day:

> start a fleet of opus builders to work on all the new features that will
> need to be implemented for the new functions on the user page

This is the spec those builders build from. The design is
`dashboard/design/account.html` (+ `dashboard/design/css/account.css`); every
control it outlines as **new** (the "mark what is new" switch) is in scope, and
everything it gathers from existing surfaces is wired to the routes that
already exist. The page ships in the CURRENT dashboard look (`base.html`,
`[ BRACKET ]` buttons, the existing `static/style.css` classes); the UI
redesign port restyles it later.

Every file, function, table and column named below was checked against the
tree at `4462a2a` plus the uncommitted 2026-09-25 fix wave. Where this spec
says NEW, the thing does not exist yet and the named group creates it.

Related: `docs/MULTI_MACHINE_PLAN.md` (the `(editor, machine)` key),
`docs/API.md` (the wire and every route), `docs/GOTCHAS.md` §12 (credentials),
`KNOWN_BUGS.md` CR-88 (wired or remote is the computer's own setting),
`docs/UPLOAD_ONLY_TICK.md` (the per-machine tick modes the page reuses).

---

## 0. Before anyone starts

1. **The fix wave under review is committed first.** It touches `api.py`,
   `auth.py`, `db.py`, `sessions.py` and `ui.py`, which five of the six groups
   below edit. Builders start from a clean tree.
2. **Schema number.** The current head is **v57** (`SCHEMA_V57`, the triage
   ledger). This work takes **v58**. If anything else lands a v58 first, take
   the next free number: `_MIGRATION_STEPS` must stay gapless
   (`test_db.py`'s ordering test).
3. **Versions.** One dashboard minor bump (`dashboard/pyproject.toml`, owned by
   group D) and one companion bump (`companion/src/ccsync_companion/config.py`
   `VERSION` and `companion/pyproject.toml`, owned by group E). After 0.9.9
   comes 0.10.0, never 1.0.
4. **Tests run once, centrally.** Each builder runs only the test files it
   creates or touches; the orchestrator runs `tools\run_all_tests.ps1` once at
   the end.
5. **Deploy order: the dashboard first, then the companions.** A companion
   carrying the new report section, reporting to an old dashboard, lands on
   the SYS-3 "report sections this dashboard does not read" banner
   (`api.undeclared_report_sections`) on every report. The reverse order is
   harmless (section 4.6).

### Invariants every group holds

- **Keys never change.** Everything is keyed by the sign-in name
  (`editor_username`, lowercase) and, per computer, by `(editor_username,
  machine)`. A display name is a LABEL rendered at display time; it is never
  written into `fleet_audit.actor`, a selection, a job, a session row or a
  wire key.
- **A new wire key is optional on read and harmless when ignored, both
  directions.** New report fields live in a `_ReportSectionIn` subclass
  (extras ignored, every field optional, state words are plain bounded
  strings, never a `Literal`). A `Literal` inside a non-tolerant list is what
  422'd whole reports in res-fleet-3; do not repeat it.
- **No em dash in user-visible text** (templates, HTTP `detail`, tray copy).
  `dashboard/tests/test_no_em_dash.py` scans templates; new tests assert the
  new `detail` sentences too.
- **Secrets never in logs, API responses or audit rows.** No password (typed,
  old or new, nor its length) is logged or audited. Session ids are shown as
  the same 12-character handle `api_admin_sessions` already truncates to. A
  private key never exists server-side; a PUBLIC key is shown as its
  fingerprint only. YouTube cookies never leave the machine; only a status word
  does.
- **CSRF on every write.** None of the new paths go into
  `app._CSRF_EXEMPT_EXACT`, `_CSRF_EXEMPT_PREFIXES` or `_CSRF_EXEMPT_RE`.
  htmx forms carry the token through `base.html`'s `hx-headers`; plain forms
  carry the hidden `csrf` field.
- **Fail closed on auth.** Every new route requires a session (none are added
  to `app._OPEN_EXACT`; `/api/v1/me` is open by EXACT match only, so
  `/api/v1/me/...` is gated). "Cannot tell" is a refusal, never an allow.
- **NFC.** The display name is NFC-normalised on the way in (it is only ever
  compared and shown, `docs/GOTCHAS.md` §17). Machine names are NOT normalised
  (they are matched exactly against `db.machines_of`, as every existing
  machine route does).
- **Blocking work off the event loop.** The SMB probe, a NAS call and the
  scrypt hash block. Routes that do any of them are plain `def` (FastAPI runs
  them in the threadpool), the same as `api_admin_set_password`.

---

## 1. The features, the rules, and who may do what

| # | Feature | Today | Who may do it | To whom |
|---|---|---|---|---|
| F1 | Set your display name | nobody can | any signed-in user | themselves |
| F1a | Set or clear someone else's display name | nobody can | admins | anyone with an account |
| F2 | Change your own password | admin-only (`POST /api/v1/admin/users/{u}/password`, Settings > Users) | any signed-in user on `smb` or `local`; nobody on `oidc` (refused with directions) | themselves only |
| F3 | List your own signed-in browsers | admin-only (`GET /api/v1/admin/sessions`) | any signed-in user | their own sessions only |
| F3a | Sign out one of your browsers | admin-only, per person | any signed-in user | one of their own sessions, never the current one |
| F3b | Sign out your other browsers | nobody (only "everywhere", `ui.page_logout_everywhere`) | any signed-in user | all their sessions except the current one |
| F4 | See your sync keys | admin-only (Users page) | any signed-in user | their own keys, read-only |
| F5 | Ask a computer to change its fleet-jobs settings (`jobs_enabled`, `jobs_kinds`) | only at the computer's tray (Settings > FLEET JOBS) | the computer's owner, or an admin | one computer, `(editor, machine)` |
| F6 | See a computer's lend length, drive reminder interval and YouTube sign-in state | not reported | the owner, or an admin | read-only |
| F7 | The `/account` page itself | does not exist | every signed-in user, admins included | always about the signed-in user |

Rules that are NOT features, stated so nobody builds them:

- **Wired or remote is never requestable** (CR-88). `mode` is not in the
  request whitelist on either side, and the companion refuses a request that
  names it.
- **`jobs_volunteer_minutes` is read-only here.** It is reported and shown,
  not requested (owner decision D-11).
- **Sync keys are read-only here.** Adding, approving and removing keys stay
  on the Users page (admin), because removing a key stops that computer's
  upload and proxy download.
- **The page never shows or acts on another person.** `?as=` is ignored on
  `/account` (it is always `auth.get_session_user`). An admin looks after
  other people from Settings > Users; the page says so and links there.

---

## 2. Schema: v58

One step, appended to `_MIGRATION_STEPS` in `dashboard/src/ccsync_dashboard/db.py`
as `(58, SCHEMA_V58)` with the usual comment. Owned by **group A**.

```sql
-- v58: the account page (docs/ACCOUNT_PAGE_FEATURES.md, 2026-09-25).
CREATE TABLE IF NOT EXISTS user_profiles (
  username      TEXT PRIMARY KEY,          -- the sign-in name, lowercase: the KEY
  display_name  TEXT NOT NULL,             -- NFC, 1..64 chars; no row = no name
  updated_at    TEXT NOT NULL,
  updated_by    TEXT NOT NULL              -- the session user who wrote it
);
CREATE TABLE IF NOT EXISTS machine_setting_requests (
  editor_username TEXT NOT NULL,
  machine         TEXT NOT NULL,
  request_id      TEXT NOT NULL,           -- secrets.token_hex(8), minted per (re)ask
  settings_json   TEXT NOT NULL,           -- {"jobs_enabled": bool?, "jobs_kinds": [..]?}
  requested_by    TEXT NOT NULL,
  requested_at    TEXT NOT NULL,
  delivered_at    TEXT,                    -- first reply that carried THIS request_id
  state           TEXT NOT NULL DEFAULT 'pending',
                                           -- pending|applied|refused|expired|withdrawn
  answered_at     TEXT,
  detail          TEXT NOT NULL DEFAULT '',-- the machine's own sentence, bounded 255
  PRIMARY KEY (editor_username, machine)
);
ALTER TABLE machine_state ADD COLUMN cfg_accepts TEXT;                 -- JSON list
ALTER TABLE machine_state ADD COLUMN cfg_jobs_volunteer_minutes INTEGER;
ALTER TABLE machine_state ADD COLUMN cfg_drive_reminder_minutes REAL;
ALTER TABLE machine_state ADD COLUMN cfg_youtube TEXT;                 -- JSON object
ALTER TABLE machine_state ADD COLUMN cfg_pending_restart TEXT;         -- JSON object
ALTER TABLE machine_state ADD COLUMN cfg_at TEXT;                      -- server clock
```

Why this shape:

- **`user_profiles` is its own table**, not a column on `users` (that table
  exists only for `DASH_AUTH_METHOD=local`) nor on `known_editors` (an admin who
  never ticked or reported has no row there). One row per person, whatever the
  identity backend.
- **One settings request per computer, latest wins.** A second ask while one is
  pending MERGES into it (per key, the newer value wins) under a NEW
  `request_id`, so the companion never has two to reconcile. The answered row
  stays (overwritten by the next ask) so the page can say "last asked ... and
  applied".
- **A separate table, not columns on `machines`**, so `forget_machine` and the
  rename adoption treat it like the other command tables
  (`file_move_targets`, `resolve_undo_requests`).
- **Reported settings are columns on `machine_state`**, the per-machine current
  state, which `_MACHINE_STATE_TABLES` already forgets with the computer.

NULL handling: every new `machine_state` column is NULL until a companion that
sends the section reports; NULL means "not reported", never a default value.
`cfg_accepts` NULL or `[]` means "this computer cannot take a request from the
dashboard".

Replay and old databases: both tables are `CREATE TABLE IF NOT EXISTS`, and
`db._already_applied` skips an `ADD COLUMN` that is present, so the step runs
on any database from v1 up (a fresh one runs `schema.sql` then v2..v58) and a
step interrupted half way replays cleanly. `migrate()` runs it once per
`user_version`; running `migrate()` twice is a no-op.

Rollback: an older image refuses to start on a v58 database ("database schema
is newer than this build"), which is the existing contract. The step is
additive, so the only rollback is forward or a snapshot restore
(`docs/BACKUP_RESTORE.md`).

### 2.1 Group A's db.py functions (exact signatures others call)

```python
# ---- display names (F1) ----
DISPLAY_NAME_MAX_CHARS = 64

class DisplayNameError(ValueError):
    """str(exc) is a plain sentence an editor reads (no em dash)."""

def normalise_display_name(text: str) -> str:
    """NFC, strip, collapse every run of whitespace to one space. Refuses
    (DisplayNameError): empty after that; longer than 64; any character in
    Unicode category Cc, Cf, Cs, Co, Cn (controls, format marks including
    zero-width and bidi overrides, surrogates, private use, unassigned)."""

def get_display_name(conn, username: str) -> str | None
def display_names(conn) -> dict[str, str]           # username -> display_name, every row
def set_display_name(conn, username: str, display_name: str, *, by: str, now: str) -> str
    # normalises, checks display_name_taken, upserts; returns the stored value
def clear_display_name(conn, username: str) -> bool
def display_name_taken(conn, username: str, display_name: str,
                       other_usernames: Iterable[str]) -> bool
    # casefold(NFC) of the name equals another person's sign-in name (from
    # other_usernames, which the caller builds: known_editor_usernames(conn)
    # | local users | settings.admin_users | user_profiles usernames) or
    # another person's display name. Your OWN sign-in name is allowed.

# ---- machine setting requests (F5) ----
MACHINE_SETTING_KEYS = ("jobs_enabled", "jobs_kinds")   # the dashboard's whitelist
MACHINE_SETTING_REQUEST_MAX_AGE_DAYS = 14               # = MACHINE_UPDATE_REQUEST_MAX_AGE_DAYS

def request_machine_settings(conn, editor: str, machine: str, settings: Mapping[str, Any],
                             *, requested_by: str, now: str) -> dict[str, Any] | None
    # None when (editor, machine) is not in `machines`. Merges into a pending
    # row (new request_id, delivered_at=NULL) or replaces an answered one.
    # Audits "machine.settings_request". Returns the row as a dict.
def machine_settings_request(conn, editor: str, machine: str) -> dict[str, Any] | None
    # the row, settings_json decoded as "settings"; None when there is none
def withdraw_machine_settings_request(conn, editor: str, machine: str,
                                      *, by: str, now: str) -> bool
    # pending -> withdrawn; audits "machine.settings_withdraw"; False if not pending
def mark_machine_settings_delivered(conn, editor: str, machine: str,
                                    request_id: str, now: str) -> None
    # sets delivered_at only if NULL and the id still matches
def answer_machine_settings_request(conn, editor: str, machine: str, request_id: str,
                                    state: str, detail: str, now: str) -> bool
    # ignores an id that is not the pending one (a merged newer ask stands).
    # state 'applied'|'refused' -> final, audits "machine.settings_applied" /
    # "machine.settings_refused" with actor = editor (a companion-originated
    # write). Any other word ('failed', or one this build has never heard)
    # stays pending and only updates `detail`. Returns True when it finalised.
def expire_machine_settings_requests(conn, now: str) -> int
    # pending older than 14 days -> 'expired'. Called from prune() right beside
    # expire_machine_update_requests (db.py, inside prune).

# ---- reported settings (F6) ----
def store_machine_settings(conn, editor: str, machine: str,
                           section: Mapping[str, Any] | None, now: str) -> None
    # None leaves the cfg_* columns ALONE (a report without the section says
    # nothing). A section replaces all six wholesale; JSON columns are
    # re-serialised from the validated section only (never raw client text).
def machine_settings_map(conn) -> dict[tuple[str, str], dict[str, Any]]
    # (editor, machine) -> {"accepts": [...], "jobs_volunteer_minutes": int|None,
    #  "drive_reminder_minutes": float|None, "youtube": {...}|None,
    #  "pending_restart": {...}, "at": str|None}; unparseable JSON reads as empty.

# ---- audit action names ----
AUDIT_ACCOUNT_DISPLAY_NAME = "account.display_name"     # self
AUDIT_USER_DISPLAY_NAME = "user.display_name"           # an admin, on someone else
AUDIT_ACCOUNT_PASSWORD = "account.password_change"
AUDIT_ACCOUNT_SIGNOUT_ONE = "account.signout_one"
AUDIT_ACCOUNT_SIGNOUT_OTHERS = "account.signout_others"
AUDIT_MACHINE_SETTINGS_REQUEST = "machine.settings_request"
AUDIT_MACHINE_SETTINGS_WITHDRAW = "machine.settings_withdraw"
AUDIT_MACHINE_SETTINGS_APPLIED = "machine.settings_applied"
AUDIT_MACHINE_SETTINGS_REFUSED = "machine.settings_refused"
```

Existing functions group A also changes:

- `_MACHINE_STATE_TABLES`: append `"machine_setting_requests"`, so
  `forget_machine` and `forget_editor` delete it.
- `forget_editor`: also `DELETE FROM user_profiles WHERE username=?`, and
  report it in `deleted["user_profiles"]`. A new person given a departed
  editor's sign-in name must not inherit their display name (the
  bug-dash-db-3 shape).
- `adopt_renamed_machine`: carry a PENDING request across, beside the
  `file_move_targets`/`resolve_undo_requests` loop:
  `UPDATE OR IGNORE machine_setting_requests SET machine=? WHERE
  editor_username=? AND machine=? AND state='pending'`.
- `prune()`: call `expire_machine_settings_requests(conn, now)` next to
  `expire_machine_update_requests(conn, now)`.

---

## 3. Routes

Two NEW modules, both registered in `app.py` beside the existing
`include_router` calls, BEFORE `ui.router`:

- `dashboard/src/ccsync_dashboard/account_api.py` (group C):
  `router = APIRouter(prefix="/api/v1")`, the JSON routes and the view
  builder.
- `dashboard/src/ccsync_dashboard/account_ui.py` (group F):
  `router = APIRouter(default_response_class=HTMLResponse)`, the page and its
  htmx partials. Every partial calls the SAME service function its JSON twin
  does; nothing is implemented twice.

Partials answer **200 with a result fragment** for every expected refusal
(wrong password, throttled, name taken, too old to ask) so htmx swaps it into
the page's one result slot; 401/403 stay HTTP errors. JSON routes answer the
HTTP codes below. All `detail` sentences are exactly as written here.

### 3.1 The account view (F7, and the data for F1-F6)

`GET /api/v1/me/account` (session). Built by
`account_api.build_account_view(request, conn) -> dict` which the page route
renders from too.

```json
{
  "user": "tchen",
  "display_name": "T. Chen",            // null when unset
  "shown_as": "T. Chen",                // display_name or user
  "is_admin": false,
  "admin_source": "",                   // "admin_list" | "local_role" | "" (auth.admin_source)
  "auth_method": "smb",                 // "smb" | "local" | "oidc"
  "password": {"changeable": true, "where": "server",   // "server"|"dashboard"|"organisation"
               "min_chars": 12, "oidc_host": null},     // issuer hostname only, oidc only
  "account": {"suspended": false},      // db.suspended_editors
  "computers": [ /* 3.1.1 */ ],
  "site": {"canonical_prefix": "P:\\", "auto_update": false,
           "youtube_download": true, "fleet_halt": false},
  "csrf": null                          // never here; only /login and 3.3 return one
}
```

`site` comes from `site_store.manifest_for_app(request.app, settings)`
(`canonical_prefix`, `features.auto_update`, `features.youtube_download`) and
`db.get_fleet_halt(conn)["active"]`. Sessions and sync keys are NOT in this
view: each has its own route so a slow NAS never holds the page (3.4, 3.5).

#### 3.1.1 One computer

Source: `api.build_editors_view(conn, now)["editors"]` filtered to
`editor_username == user` (the fleet grid's own entries, so the page and the
grid can never disagree), plus `db.lost_machines` rows for the same user, plus
`db.machine_settings_map(conn)` and `db.machine_settings_request`.

```json
{
  "machine": "TCHEN-RIG", "platform": "windows", "mode": "editor",   // "base" = wired rig
  "companion_version": "0.9.80", "current_version": "0.9.80",
  "last_seen": "...", "live": true, "why": {...} | null,             // the grid's own entry fields
  "plan": [{"slug": "...", "label": "2026/FF5/Elections", "sync_mode": "full"}],
  "jobs": {"enabled": true, "kinds": [], "idle_seconds": 300,
           "volunteering": {...}, "gate": {"reason": "", "detail": ""},
           "running": {...} | null, "gpu": "RTX 4080, 16 GB"},       // from capabilities (running values)
  "settings": {"accepts": ["jobs_enabled", "jobs_kinds"],
               "jobs_volunteer_minutes": 30, "drive_reminder_minutes": 30.0,
               "youtube": {"downloads": true, "signin_enabled": true,
                           "terms_accepted": true, "signin": "ok"} | null,
               "pending_restart": {"jobs_enabled": false},
               "at": "..."} | null,                                   // null = never reported
  "settings_request": {"request_id": "...", "settings": {...}, "state": "pending",
                       "requested_by": "tchen", "requested_at": "...",
                       "delivered_at": null, "answered_at": null, "detail": ""} | null,
  "can_request": true,          // owner or admin AND accepts non-empty
  "request_blocked": ""         // the sentence when can_request is false (4.7)
}
```

### 3.2 Display name (F1, F1a)

| Route | Body | Answer |
|---|---|---|
| `PUT /api/v1/me/display-name` | `{"display_name": str}` (max_length 256 before normalising; `""` clears) | 200 `{"ok": true, "display_name": "T. Chen" \| null}` |
| `PUT /api/v1/admin/users/{username}/display-name` | same | same; admin only (`api._require_admin`) |
| `POST /partials/account/display-name` (F) | form `display_name` | the "you" fragment with a result line |
| `POST /partials/admin/users/display-name` (F) | form `username`, `display_name` | the Users row fragment |

Errors (422 unless noted):

- empty after trimming: `A name cannot be empty. To go back to your sign-in name, clear the box and save.` (Only when the client sent whitespace; `""` is a clear.)
- too long: `A name can be at most 64 characters.`
- bad characters: `A name cannot contain invisible or control characters.`
- taken (409): `Someone else already goes by that name. Pick another.`
- admin route, unknown account (404): `There is no account called {username}.` An account is known when it is in `db.known_editor_usernames(conn)`, `local_users.get_user`, `settings.admin_users` or `user_profiles`.

Audit: `db.audit(conn, user, "account.display_name", user, {"before": old, "after": new})`
before the commit; the admin route writes `"user.display_name"` with actor =
the admin and subject = the person. After the commit, the route calls
`account_api.invalidate_display_names(request.app)` (3.8).

### 3.3 Change your own password (F2)

`POST /api/v1/me/password` (session, CSRF, plain `def`). Body model
`ChangePasswordIn`: `current_password`, `new_password`, `new_password_again`,
each `str` with `max_length=1024`. Implemented by group B's
`account_password.change_own_password` (signature in 3.3.1); the route only
maps its result to HTTP and handles the cookie.

Order of operations (the route):

1. `user = auth.get_session_user(request)`; 401 `Sign in first.` when None.
2. `settings.auth_method == "oidc"` -> 409 `You sign in with your organisation's account, so there is no password here to change. Change it where your organisation looks after its accounts.`
3. `new_password != new_password_again` -> 422 `The two new passwords are not the same. Nothing changed.`
4. `auth.check_password(new_password)` fails -> 422 `The new password needs at least 12 characters. Nothing changed.` (the number from `auth.MIN_PASSWORD_CHARS`)
5. `new_password == current_password` -> 422 `The new password is the same as the current one. Nothing changed.`
6. **Throttle, same budgets as sign-in** (owner decision D-3):
   `wait = auth.login_throttled(request, user)`; if `wait`: 429 with
   `auth.throttle_message(wait)` and `auth.throttle_headers(wait)`.
7. **Verify the current password** exactly as `/api/v1/login` does:
   `verifier = getattr(request.app.state, "credential_verifier", auth.verify_credentials)`;
   `auth.CredentialProbeBusy` -> 503 `The server is busy checking other sign-ins. Try again in a minute. Nothing changed.`;
   false -> `auth.record_login_failure(request, user)` then 422
   `That is not your current password, so nothing changed. Several wrong tries in a row make this form wait, like the sign-in page.`;
   true -> `auth.clear_login_failures(request, user)`.
8. **Set it:**
   - `local`: `local_users.set_password(conn, user, new_password)` then commit.
     `LocalUserError` for a missing row (a `DASH_ADMIN_USERS` break-glass name
     with no local account) -> 409 `{user} is not an account this dashboard keeps a password for. Ask another admin, or change it where that account lives.`
   - `smb`: `nas_factory.nas_configured(settings)` false -> 503
     `This dashboard holds no server credential, so it cannot change server passwords. Ask your admin.`
     Then `nas = nas_factory.make_nas_client(settings)`;
     `nas.is_editor(user)` raises `NasError` -> 502
     `Could not reach the server, so nothing changed. Try again in a minute.`;
     false -> 409
     `The server does not let this dashboard change the password of {user}. Change it in the NAS's own settings, or ask your admin.`
     Then `nas.set_known_password(user, new_password)`; `NasError` -> 502
     `The server refused the change, so nothing changed. Try again, or ask your admin.`
     (the exception text is LOGGED at warning, never returned: a NAS response
     body is not an editor's sentence and may carry backend detail).
9. **Sign the other browsers out and rotate this one** (owner decisions D-1,
   D-2): `store = auth.session_store(request)`; count the user's live sessions
   except the current one (`store.list_for_user`, `auth.get_session_id`), then
   `store.revoke_user(user, by=f"self:{user} (password change)")` (ALL,
   including this one), then `auth.start_session(request, response, user)`
   mints a fresh cookie for this browser. Never raises past this point: the
   password HAS changed, so a revocation failure is logged
   (`log.exception`) and reported as `other_sessions_signed_out: null`.
   Report tokens and identity tokens are untouched: they authenticate a
   machine, as `api.revoke_sessions_after_password_reset` already reasons.
10. Audit `db.audit(conn, user, "account.password_change", user, {"method": method, "other_sessions_signed_out": n})`, commit.
    `log.warning("%r changed their own password (%s) and signed out %s other session(s)", ...)`.

Answer 200:
`{"ok": true, "method": "smb", "other_sessions_signed_out": 2, "csrf": "<new token>"}`
(`auth.csrf_token(request)` AFTER `start_session`, so a non-browser client can
keep going, the same reason `api_login` returns it).

The partial twin `POST /partials/account/password` (F) answers a failure with
the result fragment; on success it answers `HX-Redirect:
/account?changed=password&others=<n>`, because the CSRF token in the page's
`hx-headers` belonged to the rotated session and the very next htmx request
would 403. The page renders the success line from those two query values.

#### 3.3.1 Group B's service

```python
# dashboard/src/ccsync_dashboard/account_password.py  (NEW, group B)
@dataclass
class PasswordChangeResult:
    ok: bool
    status: int            # the HTTP code the route answers
    detail: str            # the sentence (for ok: "")
    method: str
    other_sessions_signed_out: int | None = None
    retry_after: float = 0.0

def change_own_password(request: Request, conn: sqlite3.Connection, user: str,
                        current_password: str, new_password: str,
                        new_password_again: str) -> PasswordChangeResult
    # steps 2-8 and the audit of step 10 (NOT the commit of the audit, NOT
    # the cookie). Step 9 is `rotate_after_password_change` below.

def rotate_after_password_change(request: Request, response: Response,
                                 user: str) -> int | None
    # step 9: count, revoke all, start_session; returns the count or None.
```

The route (group C) calls `change_own_password`, then on `ok`
`rotate_after_password_change`, commits, and answers.

### 3.4 Your signed-in browsers (F3, F3a, F3b)

| Route | Answer |
|---|---|
| `GET /api/v1/me/sessions` | `{"sessions": [{"handle": "3fa9c01b77de", "ip": "100.64.3.21", "browser": "Chrome, Windows", "created_at": "...", "last_seen": "...", "current": true}]}` |
| `POST /api/v1/me/sessions/{handle}/revoke` | `{"ok": true, "revoked": 1}` |
| `POST /api/v1/me/sessions/revoke-others` | `{"ok": true, "revoked": 2}` |
| `GET /partials/account/sessions` (F) | the panel; polled every 30 s like the admin panel |
| `POST /partials/account/sessions/revoke` (F) | form `handle`; the panel |
| `POST /partials/account/sessions/revoke-others` (F) | the panel |

`handle` = the first 12 hex characters of `auth_sessions.sid`, the same
truncation `api_admin_sessions` publishes. `current` compares the row's full
sid with `auth.get_session_id(request)`. `ip`/`browser` come from group B's
`sessions.describe_client(row["client"])`.

Refusals:

- store is None (sessions not recorded) -> 503 `Signed-in browsers are not being recorded on this server.`
- `handle` not 12 lowercase hex -> 422 `That is not a browser on this list.`
- no live session of THIS user matches -> 404 `That browser is already signed out.`
- the match is the current session -> 409 `That is this browser. Use Sign out instead.`
- more than one match (a 48-bit collision within one person's sessions, never seen) -> 409 `Two browsers match that; use sign out the others instead.`

Audit: `account.signout_one` (detail `{"handle": h}`) and
`account.signout_others` (detail `{"revoked": n}`), actor and subject = the
user. `/logout-everywhere` stays exactly as it is.

### 3.5 Your sync keys (F4)

`GET /api/v1/me/sync-keys` (session, plain `def`: it may call the NAS).
Implemented by `account_api.build_sync_keys_view(settings, conn, user) -> dict`.

```json
{"keys": [
   {"fingerprint": "SHA256:q3Rf...", "state": "approved", "machine": "TCHEN-RIG",
    "comment": "tchen@TCHEN-RIG", "at": null},
   {"fingerprint": "SHA256:7bLm...", "state": "waiting", "machine": "TCHEN-LAPTOP",
    "comment": "", "at": "2026-09-24T..."}],
 "installed_unknown": false,     // DSM: "a key is installed" and nothing more
 "unreadable": "",               // the sentence when the approved half could not be read
 "needed": true}                 // false when every computer of theirs is wired
```

Sources, per identity backend:

- **waiting** (every backend): `db.fetch_pending_ssh_keys(conn, user)` ->
  fingerprint, machine, `submitted_at`. `key_text` is never returned.
- **approved, `local`**: `local_users.keys_for(conn, user)` -> fingerprint,
  label (the machine), `added_at`.
- **approved, `smb` with a NAS**: `nas.find_user(user)["sshpubkey"]`, split into
  lines, each line `>= 2` fields and not `#` (the rule
  `api._install_nas_key_keeping_others` uses), fingerprint via
  `local_users.pubkey_fingerprint` (a `LocalUserError` line is skipped), comment
  = the third field onward, bounded to 64 characters. `machine` = the
  `detail.machine` of the newest `ssh_key.approve` audit row for that
  fingerprint (`db.fetch_audit(conn, subject=user, actions=("ssh_key.approve",))`,
  filtered in Python on `subject == user`), else `null`. A value of
  `"(installed)"` (DSM, `nas/synology.py`) sets `installed_unknown` instead.
  `NasError` -> `unreadable = "The server could not be asked which keys are approved just now."`
  and the waiting half still shows.
- **no NAS configured and not local**: approved half empty, `unreadable = ""`.

`needed` is false when `db.base_machines(conn)` holds every machine of the
user: the mock's "none, and none needed: a wired rig syncs nothing".

### 3.6 Ask a computer to change its fleet-jobs settings (F5)

| Route | Body | Answer |
|---|---|---|
| `POST /api/v1/machines/{editor}/{machine}/settings` | `{"jobs_enabled": bool?, "jobs_kinds": [str]?}` (at least one key) | 200 `{"ok": true, "request": {...}}` or `{"ok": true, "unchanged": true}` |
| `DELETE /api/v1/machines/{editor}/{machine}/settings` | none | `{"ok": true}` (withdraws a pending ask) |
| `POST /partials/account/machines/settings` (F) | form `editor`, `machine`, `jobs_enabled` and/or `jobs_kinds` (repeated) | that computer's fleet-jobs fragment |
| `POST /partials/account/machines/settings/withdraw` (F) | form `editor`, `machine` | the same fragment |

Rules, in order:

1. `auth.can_manage(settings, user, editor)` false -> 403 `Only the person this computer belongs to, or an admin, can change it.` (401 `Sign in first.` when no session.)
2. `machine not in db.machines_of(conn, editor)` -> 404 `{editor} has no computer called {machine}.`
3. No known key in the body, or a key outside `db.MACHINE_SETTING_KEYS` (including `mode`) -> 422 `Only these can be changed from here: whether the fleet may use the computer, and which kinds of work it takes.`
4. `jobs_kinds` validation: every entry in `db.JOB_KINDS`, else 422 `{kind} is not a kind of fleet work.`; duplicates dropped; the list with every kind in it is stored as `[]` ("every kind", the settings window's own rule), and an EMPTY list sent by a client that meant "none" cannot be expressed: the UI refuses the last untick before sending (4.8).
5. `cfg_accepts` of that machine must contain every key asked for, else 409 with the sentence from 4.7.
6. If a request is pending, merge. If nothing pending and every asked value already equals BOTH the running value (`capabilities`) and the on-disk value (`pending_restart` absent for that key): answer `{"ok": true, "unchanged": true}` and store nothing.
7. `db.request_machine_settings(...)` (audits), commit, answer the row.

No rate limit beyond the session: every ask overwrites one row per computer.

### 3.7 The page (F7)

`GET /account` (F, session). Always the signed-in user; `?as=` ignored.
`?changed=password&others=<n>` renders the success line of 3.3 (the value is
parsed as an int and clamped; anything else renders nothing). Admins get the
admin badge and the note linking `/admin/users`.

### 3.8 The display-name cache (group C, used by group F)

```python
# account_api.py
def display_names_for(app) -> dict[str, str]
    # db.display_names over a short-lived connection, cached on
    # app.state.display_names_cache for 30 s; {} on any error (a label must
    # never fail a page).
def invalidate_display_names(app) -> None
def shown_as(names: Mapping[str, str], username: str | None) -> str
    # names.get(username) or username or ""
```

---

## 4. The wire (F5, F6)

### 4.1 Report: a new tolerant section `machine_settings`

Dashboard side (group D, `api.py`): `class MachineSettingsIn(_ReportSectionIn)`
and `ReportIn.machine_settings: MachineSettingsIn | None = None`.

```python
class MachineSettingsAppliedIn(_ReportSectionIn):
    id: str = Field(default="", max_length=64)
    state: str = Field(default="", max_length=32)     # plain string, NOT a Literal
    detail: str = Field(default="", max_length=255)
    at: str = Field(default="", max_length=64)

class MachineYoutubeIn(_ReportSectionIn):
    downloads: bool | None = None          # this machine's own opt-out (ytdl_local_downloads)
    signin_enabled: bool | None = None     # the site's youtube_unblock + the local switch
    terms_accepted: bool | None = None
    signin: str = Field(default="", max_length=16)   # ok|stale|expired|none; unknown = shown as-is

class MachineSettingsIn(_ReportSectionIn):
    accepts: list[str] | None = Field(default=None, max_length=16)
    jobs_volunteer_minutes: int | None = Field(default=None, ge=0, le=100000)
    drive_reminder_minutes: float | None = Field(default=None, ge=0, le=100000)
    youtube: MachineYoutubeIn | None = None
    pending_restart: dict[str, Any] | None = Field(default=None, max_length=16)
    applied: MachineSettingsAppliedIn | None = None
```

**Register it as a tolerant section**: add `"machine_settings":
MachineSettingsIn` to `api._TOLERANT_SECTIONS` AND add `"machine_settings"` to
the field list of `ReportIn._a_bad_section_never_422s`. Then out-of-range
numbers and over-long strings are clamped and cut by `_bound_to_field_caps`,
and a section that will not parse at all (a wrong type) is DROPPED with a
warning while the rest of the report lands: a settings echo must never cost a
machine its place on the fleet grid. A dropped section costs only its answer,
which the companion sends again on the next report.
`accepts` entries are intersected with `db.MACHINE_SETTING_KEYS`
before storing; `pending_restart` keeps only keys in
`("jobs_enabled", "jobs_kinds", "jobs_volunteer_minutes", "drive_reminder_minutes")`
with the right value type (bool / list of str / int / number); everything else
is dropped silently.

Report handler (`api.api_report`), right after
`db.store_machine_capabilities(...)`:

```python
db.store_machine_settings(conn, editor, machine,
    None if payload.machine_settings is None else payload.machine_settings.model_dump(),
    received_at)
applied = payload.machine_settings.applied if payload.machine_settings else None
if applied is not None and applied.id:
    db.answer_machine_settings_request(conn, editor, machine, applied.id,
                                       applied.state, applied.detail, received_at)
```

These are written with the report's own commit, which happens BEFORE the
commands block is built, so an answer that finalises a request stops it being
re-sent on this same reply.

### 4.2 Reply: `commands.machine_settings`

In the commands block, after `diagnostics` and before `broll_ingest`:

```python
req = db.machine_settings_request(conn, editor, machine)
if req and req["state"] == "pending":
    result["commands"]["machine_settings"] = {
        "id": req["request_id"],
        "set": req["settings"],            # only keys in MACHINE_SETTING_KEYS
        "requested_by": req["requested_by"],
        "requested_at": req["requested_at"],
    }
    if not req["delivered_at"]:
        db.mark_machine_settings_delivered(conn, editor, machine, req["request_id"], received_at)
        conn.commit()          # the report's own commit is above us (the pushed-update rule)
```

**Standing, not one-shot** (the `file_moves` rule, not `resume_lane_b`'s): it
rides every reply until the machine answers `applied` or `refused`, because
applying it is idempotent on the companion (same id answered from its ledger)
and the failure that matters is a click that evaporates while a laptop sleeps.
Present only while pending: an absent key means "nothing asked", and that is
also what an older dashboard's silence means.

### 4.3 The companion's section (every report, light ticks included)

```json
"machine_settings": {
  "accepts": ["jobs_enabled", "jobs_kinds"],
  "jobs_volunteer_minutes": 30,          // RUNNING value (app.config), validated
  "drive_reminder_minutes": 30.0,        // RUNNING value, validated as drive_reminder.py reads it
  "youtube": {"downloads": true, "signin_enabled": true,
              "terms_accepted": true, "signin": "ok"},   // omitted when the site's youtube_download is off
  "pending_restart": {"jobs_enabled": false},            // ON-DISK values that differ from RUNNING
  "applied": {"id": "9f3c...", "state": "applied", "detail": "", "at": "..."}  // the ledger's last answer
}
```

A few hundred bytes. It is NOT one of the sections `_fit_payload` sheds
first; if it is ever shed, the only cost is that the answer arrives on the
next report (the request is redelivered and answered from the ledger).

### 4.4 The acknowledgement states

| `applied.state` | Meaning | Dashboard |
|---|---|---|
| `applied` | written to config.toml and read back | final; the page shows "saved; takes effect when CCSync next starts there" while `pending_restart` holds the key, then "in effect" once the running value matches |
| `refused` | this computer will not take it (unknown key, bad value, a kinds list with no kind this build knows) | final; the page shows `{machine} refused: {detail}` |
| `failed` | could not write config.toml | stays pending; `detail` shown with "it will try again" |
| any other word | a future companion's word | stays pending; `detail` shown |

### 4.5 What the page shows while waiting

| Request row | Page line (no em dash) |
|---|---|
| pending, `delivered_at` NULL | `Asked {ago}. {machine} gets it the next time it reports in.` |
| pending, delivered | `Sent to {machine} {ago}. Waiting for its answer.` |
| pending, `detail` set | `{machine} could not save it yet and will try again: {detail}` |
| applied, key in `pending_restart` | `{machine} saved it. It takes effect the next time CCSync starts there.` |
| applied, running value matches | `In effect.` (and the row is quiet) |
| refused | `{machine} refused: {detail}` |
| expired | `{machine} did not report in for 14 days, so the request was dropped.` |
| withdrawn | nothing |

A [ WITHDRAW ] button shows while pending.

### 4.6 Version skew, both directions

| Dashboard | Companion | What happens |
|---|---|---|
| new | old | No `machine_settings` section: `cfg_*` stay NULL. The page shows every F6 row as `not reported` and the F5 controls disabled with the 4.7 sentence. The request route answers 409, so no command is ever stored for it. |
| old | new | The old `ReportIn` (`extra="allow"`) accepts the report and names `machine_settings` on the SYS-3 banner on every report; no command is ever sent. Harmless but noisy: **deploy the dashboard first.** |
| new | new, then rolled back to old | A pending request rides the reply and is ignored; it expires in 14 days and the page says so. |
| future | new | Keys outside the companion's `accepts` are never sent (the dashboard sends only keys in the machine's `accepts`). If one arrives anyway the companion refuses the whole request (4.9). |
| new | future | Unknown `accepts` entries and unknown `pending_restart` keys are dropped; an unknown `applied.state` keeps the request pending with its detail. |

Capability, not version: the dashboard decides from `cfg_accepts`, never from a
version compare. A `+dirty` build and a build that later grows a key both
answer correctly.

### 4.7 The "too old" and "not yours" sentences

- no row in `machine_state` for it: `{machine} has not reported yet.`
- `cfg_accepts` NULL or missing the key: `{machine}'s CCSync is too old to change this from here. Update it, or change it in its tray: Settings, FLEET JOBS.`
- not the owner and not an admin: the controls are not rendered at all.

### 4.8 One UI rule the wire depends on

`jobs_kinds = []` means EVERY kind on both sides. So "none" cannot be sent.
Unticking the last ticked kind is refused in the page before any request, with
the settings window's own sentence: `That is the last kind of work this
computer takes. Untick Let the fleet use this computer instead.`

### 4.9 Deploy order

1. Dashboard (v58, the section, the command, the routes, the page). Live and
   inert for every machine: nobody can ask until a companion advertises
   `accepts`.
2. Companion release through the normal pathway (`docs/RELEASE_PATHWAYS.md`),
   Windows and Mac. Each machine lights up on its first report.

---

## 5. The companion (group E)

### 5.1 NEW module `companion/src/ccsync_companion/machine_settings.py`

```python
ACCEPTS = ("jobs_enabled", "jobs_kinds")
REPORTED_RESTART_KEYS = ("jobs_enabled", "jobs_kinds",
                         "jobs_volunteer_minutes", "drive_reminder_minutes")
LEDGER_NAME = "machine_settings_request.json"      # under the state dir (~/.ccsync/state)
FAILED_RETRY_SECONDS = 300

def apply_request(command: Mapping[str, Any], *, config_path: Path,
                  ledger_path: Path, now: float) -> dict[str, Any]
    # -> {"id","state","detail","at"}; see 5.2. Never raises.
def report_section(app) -> dict[str, Any]
    # 4.3's section. Never raises (an empty dict on failure, which the
    # reporter omits). Re-reads config.toml only when its mtime changed.
def change_sentence(applied_settings: Mapping[str, Any], by: str) -> str
    # the tray balloon, no em dash
```

### 5.2 Applying (`apply_request`)

1. `id` must be a non-empty str of at most 64 characters, `set` a dict; else
   answer nothing (a malformed command is logged and ignored).
2. The ledger already holds this `id` with `applied` or `refused`: return that
   answer, write nothing. With `failed` and less than `FAILED_RETRY_SECONDS`
   ago: return it, write nothing.
3. Any key in `set` outside `ACCEPTS` (including `mode`): `refused`,
   `this computer does not take {key} from the dashboard`.
4. `jobs_enabled` not a bool: `refused`, `jobs_enabled must be true or false`.
5. `jobs_kinds` not a list of str: `refused`. Filter it to
   `capabilities.KNOWN_KINDS`. A NON-empty list that filters to nothing:
   `refused`, `this computer does not know those kinds of work`
   (because `capabilities.job_kinds` reads an all-unknown list as `[]`, which
   is EVERY kind: the opposite of what was asked). Store `""` when the result
   covers every known kind or the list was `[]`, else `", ".join(result)`
   (the settings window's own encoding, `settings_window._fleet_jobs_controls`).
6. Write each key with `config_mod.set_value(config_path, key, value)`; any
   `False` or exception: `failed`, `could not save config.toml`.
7. Record the answer in the ledger (tmp + `os.replace`), return it.

### 5.3 Wiring in `app.py`

- `CompanionApp._apply_machine_settings_request(resp)`: read
  `resp["commands"]["machine_settings"]` (the `_apply_resume_lane_b` shape:
  every step guarded, never raises, runs on the reporter thread). Calls
  `machine_settings.apply_request(...)` with `config_mod.CONFIG_PATH` and the
  state dir the other ledgers use. On a NEW `applied`: `log.warning` naming who
  asked and what, and
  `self._notify_tray(machine_settings.change_sentence(set, by), site_mod.notify_title("fleet work settings changed"))`.
  Called from `_on_report_response_locked` right after
  `self._apply_diagnostics_request(resp)`.
- The `Reporter(...)` construction (the call that passes
  `get_file_moves_applied=self._file_move_results`) gains
  `get_machine_settings=lambda: machine_settings.report_section(self)`.

Balloon copy (examples):
`tchen asked this computer to stop taking fleet work. It takes effect the next time CCSync starts.`
`owen asked this computer to take only these kinds of fleet work: Make small preview copies of video, Draw audio waveforms. It takes effect the next time CCSync starts.`
Kind names use the settings window's labels (`settings_window._kind_label`).

### 5.4 `reporter.py`

`Reporter.__init__` gains `get_machine_settings: Optional[Callable[[], dict[str, Any]]] = None`;
the payload builder adds `payload["machine_settings"]` on EVERY tick (light
ones included, like `capabilities`) when the getter returns a non-empty dict;
a getter that raises is logged and the section omitted.

### 5.5 What `report_section` reads

- `accepts`: `list(ACCEPTS)`.
- `jobs_volunteer_minutes`: the running `app.config`, through the same
  coercion `settings_window._volunteer_minutes` applies (a positive int, else 30).
- `drive_reminder_minutes`: the running value as `config.validate_config`
  accepts it (a number >= 0, 0 = first warning only), else the default.
- `youtube`, only when `ytdlp_manager.youtube_enabled(app.config)`:
  `downloads` = the tray snapshot's `ytdl_local_downloads` rule,
  `signin_enabled` = `ytdlp_manager.youtube_enabled(cfg) and ytdlp_manager.unblock_enabled()`,
  `terms_accepted` = `tray._ytdl_attested(app)`,
  `signin` = `ytdl_cookies.health(app.config)["status"]` when signin is enabled,
  else `"none"`. The health record's `reason` is NOT sent (it is yt-dlp's
  own text), nor any cookie, nor the cookies path.
- `pending_restart`: `config_mod.load_config(config_mod.CONFIG_PATH)` (cached
  by mtime) compared key by key with `app.config` for `REPORTED_RESTART_KEYS`;
  `jobs_kinds` compared as `capabilities.job_kinds(cfg)` lists. Only keys that
  differ are included, with the ON-DISK value.
- `applied`: the ledger's last answer, if any.

### 5.6 Tray and settings window

No new control. The Settings window's FLEET JOBS section already reads
config.toml on every render and already says "The settings above were changed
and take effect when CCSync next starts." when the file differs from the
running config (`settings_window._setting_changed`), so a dashboard-applied
change shows there with no code change. The balloon (5.3) is the only new
surface. Nothing restarts CCSync remotely (owner decision D-8).

---

## 6. The UI on the live dashboard (group F)

### 6.1 `/account` (`templates/account.html`, extends `base.html`)

Sidebar as on every page; `nav_current = "account"`. Panels, top to bottom,
following the mock's order and words:

1. **Head**: `[ YOUR ACCOUNT ]`, `signed in as <b>{user}</b> · admin|editor ·
   server password|local account|single sign-on · N computers, M wired rigs`.
   Admin: the admin chip and the note "This page is about you only. To change
   someone else's password, sign them out, or look after their computers, use
   Settings, Users." with a `[ SETTINGS, USERS ]` link to `/admin/users`.
2. **YOU** (`partials/account_you.html`): the name form (F1), sign-in name
   "(cannot be changed: it is the key every computer, plan and file uses)",
   role with its source (`admin_source`: "on the server's admin list" /
   "an admin in this dashboard's accounts"), signs-in-with, account state
   (active / suspended by an admin), and SYNC KEYS loaded with
   `hx-get="/partials/account/sync-keys" hx-trigger="load"` so the NAS never
   holds the page.
3. **CHANGE YOUR PASSWORD** (`partials/account_password.html`): the facts
   list from the mock per `auth_method`, the three boxes (current,
   new, again, with `autocomplete` set as in the mock), the live counter and
   match hints (small inline script or `static/account.js`), the one result
   slot. **This panel is never inside a polling wrapper**: a 30 s poll would
   wipe what the editor is typing. On `oidc`: no form; the organisation's
   issuer host and "No password here." For an admin on `oidc`, the
   emergency-sign-in note.
4. **YOUR COMPUTERS** and **YOUR WIRED RIGS**
   (`partials/account_computer.html`, one per computer, refreshed per
   computer by `GET /partials/account/computer?machine=<m>` every 30 s):
   - facts: role, sync drive, CCSync version + up-to-date chip, system, last
     report, and the grid's own `why` sentence;
   - PROJECTS (remote computers only): the plan with the mode chip and two
     buttons per row, wired to the EXISTING
     `POST /partials/selection/{editor}/{slug}/toggle?machine=<m>` (untick) and
     `...?machine=<m>&mode=upload_only|full` (switch), with `hx-swap="none"`
     and `hx-on::after-request` re-fetching this computer's fragment; the add
     row uses the same route with `mode`. The existing confirms
     (`static/confirms.js`) and the UX-1 capacity sentence apply unchanged;
   - FLEET JOBS: the facts (now / running / takes / starts after / graphics),
     then the F5 controls (`Let the fleet use this computer` and one box per
     `db.JOB_KIND_LABELS` entry) posting to
     `/partials/account/machines/settings`, the 4.5 status line, and
     `[ WITHDRAW ]` while pending. Rendered only when `can_request`, else the
     4.7 sentence. Hint under them: "Asked of {machine} on its next report,
     and it takes effect when CCSync next starts there.";
   - READ-ONLY (F6): lend length, drive reminder (remote computers only),
     YouTube terms and sign-in (only when `site.youtube_download`), each
     "not reported" when NULL;
   - admins only: the EXISTING `[ UPDATE NOW ]`
     (`/partials/admin/machines/update`) and `[ ASK THIS COMPUTER WHY ]`
     (`/partials/admin/machines/ask-why`) forms. An editor sees the tray
     directions instead;
   - the footer: "Remote or wired, pause, stop all syncing, YouTube sign-in:
     {machine}'s tray, Settings."
   Empty states as in the mock (no computers: link to `/download`; no wired
   rigs: how a computer becomes one).
5. **WHERE EACH SETTING LIVES**: the mock's table, rows filled from the view.
   Static wording, dynamic values.
6. **SIGNED-IN BROWSERS** (`partials/account_sessions.html`, polled 30 s):
   from / browser / signed in / last seen, "this browser" chip, `[ SIGN OUT ]`
   per other row, `[ SIGN OUT THE OTHERS ]` (both `hx-confirm`), and the
   existing `[ SIGN OUT EVERYWHERE ]` plain form to `/logout-everywhere` with
   its existing confirm.

Every visible string follows the mock's wording (it has already been through
the no-em-dash and plain-words passes). New CSS goes in `static/style.css`
(and `static/mobile.css` for the phone stack), using the existing panel,
chip and button classes; `account.css` from the design bench is NOT copied
(the redesign port brings the new look later).

### 6.2 Where the display name shows

Group F adds to `ui._render`:
`context.setdefault("display_names", account_api.display_names_for(request.app))`
and `context.setdefault("session_shown_as", ...)`, and registers a
`@pass_context` filter `shown_as` (`{{ row.actor | shown_as }}`) that reads
`display_names` from the context and falls back to the value itself.
Everywhere below, the name is shown and the sign-in name stays one hover or
one muted line away, so nobody can pass as someone else by picking a name:

| Surface | File | Change |
|---|---|---|
| topbar session label (bar + drawer + phone copy) | `templates/partials/topbar.html` | `{{ session_shown_as }}` as a link to `/account`, `title="signed in as {{ session_user }}"`; the drawer foot gets `[ YOUR ACCOUNT ]` |
| the topbar the SPAs fetch | `ui.partial_topbar` | same context (it renders through `_render`) |
| fleet grid EDITOR cells | `templates/partials/fleet_grid.html` (lines with `e.editor_username` / `m.editor_username` in `td.who`) | name, sign-in name muted beneath when they differ |
| audit timeline WHO | `templates/partials/admin_audit.html` | `row.actor \| shown_as`, actor in `title` |
| recent plan changes WHO | `templates/partials/plan_changes.html` | same |
| Users page | `templates/partials/admin_users.html` | a "shown as" column + the admin F1a form |
| Timeline Cards landing: "in it now", "who opened it", "last in" | `cards_landing.py` (`occupants`, `opened_phrase`, `last_in_phrase`) | map usernames through `display_names_for(request.app)` before building the phrase |

Not changed: JSON APIs (they keep usernames), the companion, emails and
alerts (`alerts.py`, owner decision D-7), `tools/*.py`.

---

## 7. Tests

Each group writes its own file(s); names below are new files unless noted.

### Group A: `dashboard/tests/test_account_db.py`
- v58 runs on a fresh DB, on a v57 DB, on a v50 DB, and twice; an interrupt
  between the two `ADD COLUMN`s replays (the `_already_applied` path);
  `_MIGRATION_STEPS` stays gapless and `SCHEMA_VERSION == 58`.
- `normalise_display_name`: NFC (a decomposed `Š` stores composed), whitespace
  collapse, 64/65 characters, RLO (U+202E), ZWJ, a control char refused; CJK
  and accented names accepted.
- `display_name_taken`: another person's sign-in name (any case), another
  person's display name, your own sign-in name allowed.
- `request_machine_settings`: unknown machine -> None; merge keeps per-key
  newest and mints a new id and clears `delivered_at`; answered row replaced.
- `answer_machine_settings_request`: stale id ignored; `applied`/`refused`
  final + audited with actor = editor; `failed` and an unknown word stay
  pending with detail.
- `expire_machine_settings_requests` via `prune()`.
- `forget_machine` / `forget_editor` delete the request and (editor) the
  profile; `adopt_renamed_machine` carries a pending request and not an
  answered one.
- `store_machine_settings(None)` leaves columns alone; a section replaces them.

### Group B: `dashboard/tests/test_account_password.py`, `dashboard/tests/test_account_sessions.py`
- password, per method (smb with `fake_truenas.py`/`fake_synology.py`, local,
  oidc): success; wrong current (records a failure, 422); throttled (429 +
  Retry-After); probe busy (503); same-as-current; too short; mismatch;
  NAS unreachable (502); not an editor (409, `set_known_password` never
  called); `DASH_ADMIN_USERS` break-glass without a local row (409); oidc
  refused.
- after success: every other session revoked, this browser gets a NEW cookie
  and the old cookie no longer validates, report tokens untouched, audit row
  present with no password in `detail_json`, and no password in any log
  record (caplog).
- `sessions.describe_client` on real UA strings (Chrome/Windows, Safari/iPhone,
  Firefox/Linux, Edge, python-urllib, empty).
- `SessionStore.revoke_by_handle`: scoped to the username (another person's
  session with the same prefix is never touched), refuses the current sid,
  refuses ambiguity.

### Group C: `dashboard/tests/test_account_api.py`
- every route: 401 without a session; 403 on a CSRF-less POST from a tracked
  session; an editor cannot reach another person's anything (sessions,
  keys, display name via the self route, a machine request for someone
  else's computer); an admin CAN request for another person's computer and
  set another person's name.
- `/api/v1/me/account` shape; `?as=` ignored; a suspended account shows
  `suspended: true`.
- sync keys: pending, local approved, TrueNAS approved with machine from the
  audit row, DSM `(installed)`, NAS error -> `unreadable` and pending still
  listed; no `key_text` anywhere in the response.
- machine settings request: whitelist (a body with `mode` 422s), unknown kind
  422, every kind stored as `[]`, `cfg_accepts` NULL -> 409 with the exact
  sentence, unchanged -> nothing stored, withdraw.
- every new `detail` string has no em dash.

### Group D: `dashboard/tests/test_machine_settings_wire.py`
- a report with no section leaves `cfg_*` alone; with it, stores; out-of-range
  numbers are clamped, unknown keys ignored, and a section with a wrong type
  is dropped while the whole report still lands (200, lanes written).
- `commands.machine_settings` present while pending, absent otherwise;
  `delivered_at` set once; an `applied` answer in a report stops the command
  on THAT reply; a stale id does not.
- skew: a report carrying `machine_settings.applied.state = "something-new"`
  is accepted (200) and leaves the request pending; a report from a companion
  with no section never gets the command.
- the section is NOT in `undeclared_report_sections`.
- `docs/API.md` examples parse (the JSON blocks load).

### Group E: `companion/tests/test_machine_settings.py`
- `apply_request`: applied (config.toml rewritten, other lines byte-for-byte,
  read back), idempotent on a redelivered id, `mode` refused, bad types
  refused, all-unknown kinds refused, full kind list written as `""`,
  `set_value` False -> failed and retried only after the floor.
- `report_section`: `pending_restart` shows only differing keys with on-disk
  values; YouTube omitted when the feature is off; no cookie text, no `reason`.
- reporter: the section rides light and heavy ticks; a raising getter omits
  it and the report still posts.
- app: `_apply_machine_settings_request` never raises on garbage replies and
  balloons once per new id (follow the conftest patterns so no real Tk
  window spawns).

### Group F: `dashboard/tests/test_account_page.py`
- `/account` renders for an editor and an admin (admin note present only for
  the admin); every panel present; oidc shows no password form.
- the password panel is not inside any `hx-trigger="every ..."` element.
- the display name appears in the topbar, fleet grid, audit and plan-change
  rows, Users page and Cards landing phrases, with the sign-in name in a
  `title` or muted line.
- `?changed=password&others=abc` renders nothing unsafe.
- the page's template strings pass `test_no_em_dash.py`.

---

## 8. File ownership: six builder groups

No two groups edit the same file. Everything a group calls in another group's
file is pinned by signature in this spec, so all six can start at once and
code against the signatures; merge in the order A, B, then C/D/E, then F.

| Group | Owns (edits or creates) | Defines for others | Calls from others |
|---|---|---|---|
| **A: schema + db** | `dashboard/src/ccsync_dashboard/db.py`; NEW `dashboard/tests/test_account_db.py` | everything in 2.1 | nothing new |
| **B: auth, sessions, password** | `dashboard/src/ccsync_dashboard/auth.py`, `dashboard/src/ccsync_dashboard/sessions.py`; NEW `dashboard/src/ccsync_dashboard/account_password.py`; NEW `dashboard/tests/test_account_password.py`, `dashboard/tests/test_account_sessions.py` | `auth.admin_source(settings, username) -> str`; `sessions.describe_client(client: str) -> dict` (`{"ip", "browser"}`); `SessionStore.revoke_by_handle(username, handle, *, by, except_sid=None) -> int` (raises `ValueError("ambiguous")` on >1 match; returns 0 for none; the route decides the sentence) ; 3.3.1 | A's `db.audit`, `AUDIT_ACCOUNT_PASSWORD` |
| **C: account JSON routes** | NEW `dashboard/src/ccsync_dashboard/account_api.py`; `dashboard/src/ccsync_dashboard/app.py` (two `include_router` lines: `account_api.router` and `account_ui.router`, both before `ui.router`); NEW `dashboard/tests/test_account_api.py` | `build_account_view`, `build_sync_keys_view`, the service functions each partial calls (`set_own_display_name`, `set_user_display_name`, `list_own_sessions`, `revoke_own_session`, `revoke_own_other_sessions`, `ask_machine_settings`, `withdraw_machine_settings`, each `(request, conn, ...) -> dict` raising `HTTPException` with 3.x's sentences), and 3.8 | A (2.1), B (3.3.1, `describe_client`, `revoke_by_handle`, `admin_source`), existing `api.build_editors_view`, `api._require_admin` |
| **D: the wire, dashboard side** | `dashboard/src/ccsync_dashboard/api.py`; `docs/API.md` (all new routes from section 3 AND the wire from section 4, in §2 `/api/v1/me`, a new §5 "Account" and the report/commands sections); `dashboard/pyproject.toml` (version); NEW `dashboard/tests/test_machine_settings_wire.py` | `MachineSettingsIn` and friends, `ReportIn.machine_settings`, the report-handler and commands-block code of 4.1/4.2 | A's `store_machine_settings`, `answer_machine_settings_request`, `machine_settings_request`, `mark_machine_settings_delivered` |
| **E: companion** | NEW `companion/src/ccsync_companion/machine_settings.py`; `companion/src/ccsync_companion/app.py`; `companion/src/ccsync_companion/reporter.py`; `companion/src/ccsync_companion/config.py` (VERSION only) and `companion/pyproject.toml`; NEW `companion/tests/test_machine_settings.py` | section 5 | nothing on the dashboard; the wire contract of section 4 |
| **F: page + display names** | NEW `dashboard/src/ccsync_dashboard/account_ui.py`; `dashboard/src/ccsync_dashboard/ui.py` (`_render` context, the `shown_as` filter, nothing else); `dashboard/src/ccsync_dashboard/cards_landing.py`; NEW `dashboard/templates/account.html`, `partials/account_you.html`, `partials/account_password.html`, `partials/account_computer.html`, `partials/account_sessions.html`, `partials/account_sync_keys.html`; `templates/partials/topbar.html`, `partials/fleet_grid.html`, `partials/admin_audit.html`, `partials/plan_changes.html`, `partials/admin_users.html`, `templates/cards_landing.html` (only if a phrase moves into it); `dashboard/static/style.css`, `dashboard/static/mobile.css`, optional NEW `dashboard/static/account.js`; NEW `dashboard/tests/test_account_page.py` | the page routes and partials of section 3 (paths as listed there) | C's service functions and 3.8; the existing toggle, update and ask-why routes |

Hand-offs, in words:

1. **F creates `account_ui.py` with `router = APIRouter(default_response_class=HTMLResponse)` as its first act**, because C's `app.py` edit imports it. Until F's routes exist the router is simply empty.
2. **A's signatures are the contract.** If A has to change one, A says so before merging and the caller group adapts; nobody edits `db.py` but A.
3. **B's `account_password.change_own_password` is called only by C** (JSON) and, through C's service, by F (partial). F never imports `account_password` directly.
4. **D writes the whole `docs/API.md` change**, from sections 3 and 4 of this doc; C and E send D nothing but a note if a sentence changes.
5. **The admin password-reset audit** (owner decision D-15) is D's, in `api.api_admin_set_password` and `api.api_admin_create_user`'s password branch, if the owner says yes; the ui twin in `ui.py` (`partial_admin_set_password`, `POST /partials/admin/users/password`) is F's.
6. **After merge, the orchestrator** adds the CLAUDE.md invariant paragraph (one line each: the display name is a label never a key; `commands.machine_settings` is standing and capability-gated by `cfg_accepts`; mode is never requestable), and runs `tools\run_all_tests.ps1` once.

---

## 9. Open decisions for the owner

Each has the default the builders will use unless the owner says otherwise.

| # | Question | Recommended default |
|---|---|---|
| D-1 | After a self-service password change, are the other browsers signed out always, or is there an "also sign out my other browsers" box? | **Always**, no box. A password change is most often "someone may know it"; the mock already promises it. |
| D-2 | Is THIS browser's cookie replaced with a fresh one on a password change? | **Yes**, invisibly (the person stays signed in). Closes a copied-cookie hole at no cost. |
| D-3 | Do wrong "current password" tries count against the sign-in throttle (same per-name and per-address budgets)? | **Yes, the same budgets.** Side effect: someone holding a stolen browser can delay the real person's sign-in by up to an hour; the alternative is a separate budget, which gives a stolen session five free guesses an hour on top of the sign-in page's. |
| D-4 | May a display name match another person's sign-in name or display name? | **No**, refused with "Someone else already goes by that name." |
| D-5 | May an admin set or clear someone else's display name? | **Yes**, from Settings > Users, audited. |
| D-6 | What shows before anyone sets a name? | **The sign-in name.** Not the NAS "full name" (one NAS call per page, and absent on local and SSO accounts). |
| D-7 | Where does the name show? | The surfaces in 6.2. **Not** in emails, alerts, JSON APIs or the companion's tray. |
| D-8 | Does a fleet-jobs change asked from the dashboard take effect at once or at CCSync's next start? | **Next start**, exactly like the tray's own control (every `jobs_*` key is read at construction). Live apply means reworking `jobs_runner`. |
| D-9 | Is the person at the computer told when someone changes it from the dashboard? | **Yes**, one tray balloon naming who asked. |
| D-10 | How long does an unanswered ask wait? | **14 days**, the pushed update's window. |
| D-11 | Is "lend this computer for N minutes" changeable from the dashboard? | **No**, shown only. It only matters to the person at the keyboard. |
| D-12 | May an editor remove one of their own sync keys from this page? | **No**, read-only. Removing a key stops that computer syncing; it stays an admin action. |
| D-13 | May the signed-in-browsers list sign out THIS browser? | **No**, it says "Use Sign out instead." |
| D-14 | YouTube rows when the site has YouTube downloads off? | **Hidden.** |
| D-15 | Today an admin resetting someone's password is not in the audit timeline. Add a `user.password_reset` row while we are here? | **Yes** (small, group D and F). |
