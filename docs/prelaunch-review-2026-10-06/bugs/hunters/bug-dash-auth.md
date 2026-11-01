# bug-dash-auth - dashboard authentication, sessions, OIDC, local accounts, gates (pre-launch, 2026-10-06)

Covered (working tree as of 2026-10-06, HEAD 08b40eb + uncommitted): `auth.py`, `sessions.py`,
`oidc.py`, `local_users.py`, `secrets_boot.py`, `setup_api.py`, `account_api.py`,
`account_password.py`, `account_ui.py` (routes and gates), `subject_data_api.py`,
`protection.py` (route gating only), and in `app.py` the open-path tables, `login_gate`,
`csrf_gate`, `stale_page_gate`, `body_size_gate`, the boot-secret refusals. Followed into
`api.py` for `api_login`, `api_verify`, `_require_fleet_member`, `_account_refusal`, the
report identity check, `delete_user_everywhere`/`_purge_user_credentials`, the selection
gates; `ui.py` `page_login_submit`; `setup_routes.first_run_open`; `internal_sftp` token gate;
smbprotocol's `Session`/`Connection` in the dashboard venv.

Probes (dashboard venv, throwaway apps on temp DBs, no live system touched):
- `DASH_AUTH_METHOD=oidc`, credential verifier stubbed: `POST /api/v1/login` as a non-admin
  answers 200 with a session (`/api/v1/me` then names the user); `POST /login` for the same
  user is refused. Confirms finding 1.
- `DASH_AUTH_METHOD=local`, verifier stubbed to take 0.3 s and fail: 100 concurrent
  `POST /login` for one username ran the verifier 100 times (limit 5); the next request
  was throttled. Confirms finding 3.
- smbprotocol in the venv: `Session` never sets a `session_flags` attribute; `Connection`
  defaults `require_signing=True`. Confirms finding 7.

Not reached: protection.py internals beyond its routes; the mounted sub-apps' own auth
(broll/music/ytdl/cards) except where the dashboard gates decide; Synology backend's
`is_editor`.

### bug-dash-auth-1 - /api/v1/login accepts NAS passwords for everyone on an OIDC site
- Severity: high
- Confidence: CONFIRMED (probed)
- Where: dashboard/src/ccsync_dashboard/api.py:2255-2293 (`api_login`); auth.py:151-166 (`verify_credentials` runs the SMB probe for `oidc`); contrast ui.py:1028-1034
- What: With `DASH_AUTH_METHOD=oidc` the password form is meant to be break-glass for `DASH_ADMIN_USERS` only (ui.py refuses anyone else). The JSON twin `/api/v1/login` has no such check. `verify_credentials` treats `oidc` like `smb`, so any account the NAS's SMB service accepts gets a full browser session (and a CSRF token in the answer).
- Scenario: a customer moves to OIDC to get MFA and central off-boarding. A leaver is disabled in the IdP but their NAS SMB account still exists (or any NAS SMB account: a bookkeeper, a share-only user). `curl -X POST /api/v1/login -d '{"username":"leaver","password":"..."}'` returns 200 and a session cookie. MFA, `DASH_OIDC_ALLOWED_GROUPS` and `require_fleet_member` are all skipped.
- Recommendation: give `api_login` the same rule as `page_login_submit` (refuse non-admins when `auth_method == "oidc"`, record a failure, same generic message). Better, put the rule in one helper both routes call.
- Known: no

### bug-dash-auth-2 - Browser sign-in on smb sites checks the password only: no fleet membership, no suspension
- Severity: high
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/ui.py:984-1081 (`page_login_submit`), api.py:2255-2293 (`api_login`); only `api_verify` (api.py:2435) calls `_require_fleet_member`; api.py:4863-4885 (suspend signs nobody out)
- What: `_require_fleet_member` (the `editors` group / `DASH_ADMIN_USERS` check) guards only the companion's `/api/v1/verify`. `/login` and `/api/v1/login` mint a session for any account the NAS's SMB service accepts. Suspension is also never checked at sign-in, and suspending revokes no session. KNOWN_BUGS (the trust-model-5 entry) describes password sign-in as enforcing membership, so the docs and the code disagree.
- Scenario: the studio NAS has SMB accounts for an accountant and a guest share. Either one signs in to the dashboard and, as a non-admin, can browse the whole b-roll and music libraries and Timeline Cards (unreleased documentary cuts), create client folders (public links that the operator publishes through Funnel), and queue YouTube/AI work billed to the studio. A freelancer the owner SUSPENDED keeps all of that in the browser.
- Recommendation: call `_require_fleet_member` (and `_account_refusal` for suspension) in both sign-in routes before `start_session`. Revoke the person's sessions when they are suspended, or have `login_gate` refuse a suspended user's session.
- Known: no (the KNOWN_BUGS trust-model-5 entry assumes the opposite)

### bug-dash-auth-3 - The login throttle can be bypassed with concurrent requests (unbounded on local accounts)
- Severity: high
- Confidence: CONFIRMED (probed)
- Where: dashboard/src/ccsync_dashboard/ui.py:1019 then 1042 (throttle read on the event loop, verify in the threadpool); api.py:2268/2422; sessions.py:580-671 (`throttled` only reads `blocked_until`, which is written only after a failure is recorded); auth.py:159 (the probe semaphore covers smb/oidc only)
- What: The throttle is check-then-act. Every request in a burst reads "not blocked" before any failure is recorded. On `POST /login` the check runs on the event loop and the verify is awaited in the threadpool, so a burst of any size passes the check together. Local accounts have no concurrency cap at all. Each local verify is a 32 MiB scrypt, and there is no container memory limit in the compose files. On smb, the 4-slot semaphore with its 2 s queue bounds the burst but does not stop it.
- Scenario: an appliance (`DASH_AUTH_METHOD=local`) reachable on the tailnet. An attacker sends 1,000 concurrent `POST /login` for `admin` with different passwords. All 1,000 are checked, against a budget of 5 per hour. Run once an hour, that is 24,000 guesses a day per username. The same burst also allocates up to 40 x 32 MiB of scrypt memory at once in the single worker.
- Recommendation: reserve an attempt before verifying: increment the user and IP counters atomically under `_write_lock` and refuse when they are over budget, then clear the counters on success. Add a semaphore for local scrypt like `_probe_slots`, and answer 503 when it is full.
- Known: no

### bug-dash-auth-4 - OIDC identity is the mutable preferred_username claim, matched straight against DASH_ADMIN_USERS
- Severity: high
- Confidence: CONFIRMED (code); exploitability depends on the IdP
- Where: dashboard/src/ccsync_dashboard/oidc.py:280-312 (`username_from_claims`, default claim `preferred_username`), :347-348 (`require_fleet_member` passes on `auth.is_admin(username)`), :359-365 (no editors on record = no membership check), :498 (`start_session(username)`); `sub`/`iss` never stored
- What: The dashboard identity is whatever the username claim says. The OIDC spec warns that `preferred_username` is neither unique nor stable, and many IdPs let users edit it: Keycloak with "edit username" on, Authentik, a multi-tenant or social issuer. Nothing binds a dashboard name to the IdP's `sub`. Fleet membership passes for any name in `DASH_ADMIN_USERS`. On a dashboard with no editors on record yet, any directory account gets in, and the first tick makes it "known" for good.
- Scenario: Keycloak realm with self-service profile edits. An ordinary member sets their username to `owen` (the operator in `DASH_ADMIN_USERS`) and signs in. `require_fleet_member` passes because `is_admin("owen")` is true, and they hold a full admin session: users, packages, OTA, AI keys, fleet halt.
- Recommendation: record `(iss, sub)` against the username the first time it signs in and refuse a later login whose claim maps to that name from a different `sub`. Document a non-editable claim as the requirement. Keep the empty-fleet bypass only while no admin has ever signed in, or require `DASH_OIDC_ALLOWED_GROUPS` on OIDC sites.
- Known: no

### bug-dash-auth-5 - Deleting a person on smb/oidc does not stop their companion, which re-registers them as a known editor
- Severity: high
- Confidence: CONFIRMED
- Where: dashboard/src/ccsync_dashboard/auth.py:74/375-391 (identity never expires, no server-side row); api.py:5114-5143 (`_purge_user_credentials` revokes sessions and per-editor tokens only); api.py:238-271 (`_account_refusal` returns None on smb/oidc unless suspended); api.py:10240-10270 (`record_known_editor` on every verified report); settings.py:135 (`shared_report_token_enabled=True` by default); oidc.py:359-371 (known editors pass membership)
- What: After `delete_user_everywhere` on an smb or oidc site, the person's companion still holds a valid identity token, which never expires and cannot be revoked, plus the shared report token, which is on by default and handed out by `/verify`. Its next report passes every check: the account refusal only knows "suspended" off local mode, and `forget_editor` cleared the suspension rows too. The report is accepted, `record_known_editor` puts the person back into `known_editor_usernames`, and their machine reappears in the grid. They can also keep claiming fleet jobs and using the other fleet-token doors. On OIDC that recreated "known" record satisfies `require_fleet_member` again for their IdP account.
- Scenario: an owner removes a departing freelancer with DELETE on the Users page. Thirty seconds later the freelancer's laptop reports, is accepted, and is back on the grid and in the known-editor list. Unless the owner also retires the shared token for the whole fleet, the only real stop is rotating `DASH_SESSION_SECRET`, which signs out every machine.
- Recommendation: leave a tombstone on delete (a `deleted_editors` row checked in `_account_refusal` on every auth method, cleared only by re-creating the account), or store an identity-token generation per editor and bump it on delete, disable and password reset. Ship new sites with the shared report token off.
- Known: trust-model-1 (KNOWN_BUGS, deferred as a security-model change; still open)

### bug-dash-auth-6 - The first local admin is whoever reaches /api/v1/setup/admin first
- Severity: low
- Confidence: CONFIRMED (code); exposure depends on deployment
- Where: dashboard/src/ccsync_dashboard/setup_api.py:63-105; app.py:90 (`_OPEN_EXACT`); setup_routes.py:47-84
- What: On `DASH_AUTH_METHOD=local` with an empty `users` table, an anonymous POST creates an admin and signs that caller in. No setup code is involved (printed to the container log, or shown on the NAS console). The appliance compose binds 8480 to loopback, which narrows the window. But once the bundled Tailscale node is up (pre-authed, or the operator joins it before step 2), anyone on that tailnet can claim the appliance.
- Scenario: a customer runs the compose with a Tailscale auth key so the node joins at boot, then gets to the wizard the next day. A tailnet member who browses to it first creates `admin` and owns the dashboard.
- Recommendation: generate a one-time setup code at first boot (log it, write it to `<data>/secrets/setup_code`) and require it on `/api/v1/setup/admin`.
- Known: related to bug-hunt-2026-09-24 bug-dash-auth-1 (the window's scope, fixed); the claim itself is not recorded

### bug-dash-auth-7 - The SMB guest/null-session rejection is dead code
- Severity: low
- Confidence: CONFIRMED (probed the library)
- Where: dashboard/src/ccsync_dashboard/auth.py:115-126
- What: `getattr(session, "session_flags", 0)` is always 0, because smbprotocol's `Session` has no such attribute (the flags are local to `Session.connect`). A guest-mapped session is refused today only because `Connection` defaults to `require_signing=True` and smbprotocol raises for a guest session under signing. The guard the comment describes, which protects against "every password authenticates for every username", does not exist.
- Scenario: a later change passes `require_signing=False` (for example for an old NAS that rejects signing), and the NAS maps bad users to guest (TrueNAS does when guest shares exist). Any username with any password then signs in.
- Recommendation: check `session.session_key is None` after `connect()` (smbprotocol clears it for guest and null sessions), or pin `require_signing=True` explicitly with a comment, and add a test against a fake guest response.
- Known: no

### bug-dash-auth-8 - Non-ASCII header or query values 500 two pre-auth comparisons
- Severity: low
- Confidence: CONFIRMED (code; same DASH-5 shape fixed elsewhere)
- Where: dashboard/src/ccsync_dashboard/internal_sftp.py:89; oidc.py:462
- What: `hmac.compare_digest` raises TypeError on non-ASCII `str`. The internal sftp bearer check and the OIDC `state` compare pass attacker-shaped strings straight in. A latin-1 decoded `Authorization` header, or a percent-encoded UTF-8 `state`, gives a 500 with a traceback instead of a 401 or 400.
- Scenario: `GET /internal/sftp/users` with `Authorization: Bearer é` gets a 500, and an error notice is recorded on each request.
- Recommendation: route both through `api.token_ok` (it compares bytes), or catch TypeError as auth.py does.
- Known: no

### bug-dash-auth-9 - /broll, /music, /ytdl writes skip CSRF and Origin checks and rely on SameSite=Lax alone
- Severity: low
- Confidence: PLAUSIBLE
- Where: dashboard/src/ccsync_dashboard/app.py:234-235 (`_CSRF_EXEMPT_PREFIXES`), :1083-1085; music/web/musicweb/routes_ingest.py:432 (multipart upload); ytdl/web/ytdlweb/routes_api.py (bodyless POSTs: cancel, download, select)
- What: These prefixes are fully exempt, and unlike `/cards/` they get no Origin check either. SameSite=Lax stops cross-site requests but not same-site ones. Same-site means other ports on the NAS host and other hosts under the same registrable domain: a customer domain, or any host sharing the tailnet name if the PSL does not split it. A multipart form POST and a bodyless POST are both "simple" requests a page can send with the editor's cookie.
- Scenario: a customer serves the dashboard at `dash.studio.com` and also has a CMS or other user-content site under `studio.com`. A page there auto-submits a form to `https://dash.studio.com/ytdl/api/jobs/12/cancel`, or a multipart upload to `/music/api/ingest`, and the signed-in editor's cookie goes with it.
- Recommendation: apply `_origin_mismatch` to these prefixes now, as `/cards/` already does. It costs nothing and does not need the SPAs to send a token.
- Known: no (the exemption is documented as a deliberate interim)
