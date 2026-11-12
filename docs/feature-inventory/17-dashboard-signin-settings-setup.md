# Dashboard: start-up, request gates, sign-in, every setting, and the first-run setup wizard

Terms used throughout:

- **Dashboard**: the web server (normally in a container on the NAS) that editors' computers report to and that people sign in to in a browser.
- **Companion**: the tray program on each editor computer. It authenticates to the dashboard with a **fleet token** (header `X-CCSync-Token`: either the one shared `DASH_REPORT_TOKEN`, or a per-editor token) plus, on most routes, a signed **identity token** (header `X-CCSync-Identity`) naming which person's computer it is.
- **Session**: a signed-in browser. It is a cookie named `ccsync_session` plus a row kept on the server; a cookie whose row is gone is not a session.
- **Admin**: a person named in `DASH_ADMIN_USERS`, or (only when the sign-in method is `local`) an account whose role is `admin`.
- **Mounted app**: a separate web app served inside the dashboard under a path prefix: b-roll (`/broll`), music (`/music`), YouTube downloader (`/ytdl`), Timeline Cards (`/cards`), the new Cards editor (`/cards/edit`), Footage Sorter (`/sorter`).
- **Site manifest**: the public description of this installation (organisation name, drive letter, URLs, feature switches) that installers and companions read.
- **Vendor build**: the image as shipped to customers, with optional features off.

## Process start-up (source: app.py)

- Two entry points start the same server: the factory used by the container start script, and the `ccsync-dashboard` console command (also `python -m ccsync_dashboard.app`). The console command listens on `0.0.0.0` at the port from `DASH_PORT` with exactly one worker.
- Order of start-up steps on both entry points:
  1. Fill in any of the five server secrets the environment lacks, from files under `<data>/secrets/` or freshly generated (see "Secrets bootstrap").
  2. Apply the appliance overlay: values an admin typed into the setup wizard fill any environment variable left blank (see "Appliance configuration overlay").
  3. Read every setting from the environment.
  4. Install the crash reporter (writes a JSON crash file for every unhandled exception; network sending only with `DASH_SENTRY_DSN` and an installed Sentry library; a rotating log file only with `DASH_LOG_DIR`).
  5. **Refuse to start** if a secret was freshly generated but could not be saved to disk (the file is read back and its content compared, an empty file counts as not saved). The message names each lost secret with what it would cost: `DASH_SESSION_SECRET` "every computer and every browser would be signed out the next time this server restarts"; `DASH_REPORT_TOKEN` "the computers in the fleet would stop being able to report..."; `BROLL_INGEST_TOKEN` "b-roll indexing would stop being accepted..."; `SYNCTHING_API_KEY` "this server would lose control of its own sync engine..."; `CCSYNC_INTERNAL_TOKEN` "the file-transfer sidecar would stop trusting this server...". It tells the operator to fix who owns the folder on the NAS or set the value in the environment. `DASH_DEV_INSECURE=1` turns this into a logged warning.
  6. **Refuse to start** on weak or bad secrets and sign-in configuration (see "Boot refusals"). The message ends "Generate secrets with `openssl rand -hex 24` and redeploy." (or "Fix it and redeploy." when the only problem is the sign-in method) and mentions the `DASH_DEV_INSECURE=1` bypass "never do that on a deployment". With `DASH_DEV_INSECURE=1` the refusal is skipped and a warning lists what was bypassed.
  7. Log one line describing the sign-in setup (method, cookie Secure policy, idle and absolute session lifetimes, trusted proxies) and one line about the 12-character password floor.
  8. **Refuse to start** when the b-roll app is on (`DASH_BROLL_ENABLED`) and `BROLL_INGEST_TOKEN` is missing or weak, naming the fix or the option `DASH_BROLL_ENABLED=0`.
- The web app's title is "`<org name>` - `<product name>` Dashboard" from the site manifest (product name defaults to "CC Sync"; with no org name just "CC Sync Dashboard").
- No interactive API documentation is published: `/docs`, `/redoc` and the OpenAPI schema do not exist.
- Steps run when the server begins serving (in order):
  - A start-up deadline is armed (from the code-update module) so a start that hangs before the boot watchdog is armed is caught; cancelled once start-up finishes.
  - The database is opened and migrated to the current schema.
  - A record of "ignored report sections" written by an older dashboard version is forgotten so this version re-records anything still undeclared.
  - The session tables are created if missing.
  - A log line reports how many machines still authenticate with the shared fleet token versus per-editor tokens. If the shared token is disabled, a warning lists machines that last reported with it "and will now be refused until they are given a per-editor token". If enabled and some machines use it, a warning names them and tells the operator to mint per-editor tokens and then set `DASH_SHARED_REPORT_TOKEN_ENABLED=0`.
  - On sign-in method `local`: a warning for each `DASH_ADMIN_USERS` name that has no matching local account.
  - One-time copy of `DASH_SITE_*` environment values into the stored site settings (see "Stored site settings").
  - A warning if this is the locked vendor build but the site has `features.ai_cli_providers=1` stored ("the Claude Code/Codex providers, CLI auto-update and the subscription path are OFF until the container env carries `DASH_STUDIO_CLI_PROVIDERS=1`"). Nothing stored is changed.
  - Stored settings that belonged to the retired look switch (`ui_terminal_groups`, `ui_preview`) are deleted.
  - A boot-time configuration check writes problem notices (for example a quoted or space-padded secret) to the home page's problems list.
  - Unfinished server-side file moves (a rename cut off by the container going down) are finished or quarantined.
  - Expired sessions and old sign-in failure records are pruned.
  - The "pinned job" executor (the dashboard running a media job the fleet gave up on, through the mounted Timeline Cards engine) is set up. If the old Cards page is retired it gets no engine and pinning is impossible (a spent job is abandoned). Otherwise, when Cards is mounted, jobs a previous run left "in hand" are released and the executor is started; when not, a log line says why jobs are never pinned here.
  - The new Cards editor's child process supervisor is started.
  - The background collector is started (it polls Syncthing, prunes the database, and periodically prunes sessions and sign-in failure records).
  - The collector watchdog is started (see "Collector watchdog").
  - The vendor release feed poller is started only if `DASH_RELEASE_FEED_URL` is set.
  - The code-update boot watchdog is armed (clears a boot-attempts file after a healthy boot; two failed boots revert an over-the-air code update at the next boot). Failure is logged, never fatal.
  - Every one of these steps except the database migration is wrapped so that a failure is logged and start-up continues.
- Shutdown steps, in order: stop the new Cards editor's child first (its stop signal saves every open cut list), then the watchdog, the collector, the pinned executor, the Cards engines, the Footage Sorter, the release feed poller; finally, if a staged code update asked for a restart, exit with code 75 so the start script re-selects the code and starts again.
- Mounted apps are attached after all dashboard routes so none can shadow a dashboard route. Each reports one of mounted / absent / degraded, and only a fully mounted app gets a navigation link. Each verdict is logged when not mounted and recorded for the health checks and boot notices.
  - b-roll: mounted only when `DASH_BROLL_ENABLED` is on; otherwise absent with "the b-roll platform is switched off on this server (DASH_BROLL_ENABLED)".
  - music, YouTube downloader: no switch; present if their code is shipped.
  - new Cards editor at `/cards/edit`: registered before `/cards`; off unless `DASH_CARDS_EDITOR`; a missing Node or bundle is "absent" with a page that says so.
  - Timeline Cards at `/cards`, then Footage Sorter at `/sorter` (its data loads in the background; requests wait until ready; a fast load failure flips it to absent).
- Every mounted app except `/cards` gets the dashboard's error answer (500 "internal error", or 503 "database busy").
- `/static/` serves the dashboard's static files (if the folder exists). `/favicon.ico` serves the product icon if the file exists.

## Collector watchdog (source: app.py)

- Checks the background collector every 30 seconds (`DASH_COLLECTOR_WATCHDOG_SECONDS`, 0 disables the watchdog entirely, negative becomes 0, a non-number is logged and the default used).
- If the collector thread has died: writes a warning notice "The background job thread stopped and had to be restarted (N time(s) since this server last started). While it was down, nothing about the fleet was being updated." with the fix "If this keeps happening, restart the dashboard and send the server log to support.", then restarts it. Up to 3 restarts; on the 4th death, or if a restart fails, the process exits with code 75 so the container is replaced.
- If the collector is alive but has not completed a loop in 900 seconds (`DASH_COLLECTOR_WEDGED_SECONDS`, 0 disables this check), the process exits with code 75.
- If the collector's state cannot be read, the watchdog assumes all is well.

## Request gates, applied to every request (source: app.py)

The gates run in this order from outermost: login gate, session-expiry header, body-size gate, stale-page gate, CSRF gate, then the route.

### Login gate: which paths need a signed-in browser

- Any path not listed below requires a valid session. Without one:
  - Paths under `/api/` answer 401 JSON `{"detail": "Your sign-in has expired. Sign in again.", "login": "/login"}`.
  - Mounted-app data paths answer 401 JSON `{"detail": "login required"}`: `/broll/api/`, `/broll/media/`, `/music/api/`, `/ytdl/api/`, `/cards/agent/`, `/sorter/api/`, `/cards/api/`, `/cards/audio`, `/cards/video`, `/cards/peaks`, `/cards/edit/api/`, `/cards/edit/media/`, and per episode `/cards/p/<slug>/api/`, `audio`, `video`, `peaks`.
  - An htmx (in-page partial) request gets 401 with an `HX-Redirect` header to `/login?next=<the page the fragment belongs to>` so the browser navigates to the sign-in page.
  - Any other request gets a 303 redirect to `/login?next=<path and query>`.
- Open to anyone with any method: `/login`, `/api/v1/login`, `/api/v1/logout`, `/api/v1/me`, `/api/v1/health`, `/api/v1/report`, `/api/v1/verify`, `/api/v1/diagnostics`, `/api/v1/ssh-key`, `/api/v1/site`, the two OIDC sign-in legs (`/auth/oidc/login`, `/auth/oidc/callback`), `/api/v1/setup/status`, `/api/v1/setup/admin`, `/setup`. These routes do their own credential checks where they need one.
- Open for GET and HEAD only: `/favicon.ico`, `/manifest.webmanifest`, `/sw.js`, `/offline`, `/cards/manifest.webmanifest`, `/cards/icon.svg`, `/cards/sw.js`, `/.well-known/assetlinks.json`, and `/cards/p/<slug>/sw.js|manifest.webmanifest|icon.svg` where the slug is lower-case letters, digits and hyphens, 1 to 48 characters, starting with a letter or digit. Any other method on these goes through the session check.
- Open by prefix: `/static/`, `/internal/sftp/` (its own bearer token), everything under `/api/v1/setup/` (each route checks setup access itself), `/broll/share/` (client folder link; the token in the path is the credential), `/sorter/share/` (Footage Sorter folder link; token in path).
- Open exact: `/ytdl/api/config/ytdl-client` (readable by anyone by design).
- Open only with a valid fleet token (shared or per-editor):
  - anything under `/api/v1/selection/`;
  - anything under `/api/v1/companion/package/` (upgrade downloads);
  - `GET /api/v1/fleet/halt` (reading the fleet halt; setting it stays session-only);
  - `/ytdl/api/jobs/<number>/claim|heartbeat|download-manifest|clips/<x>/status`;
  - `/broll/api/fleet/ingest/batches/<32 hex>/claim|heartbeat|release|items/<32 hex>/status|result|uploaded`;
  - the same shapes under `/music/api/fleet/ingest/batches/`;
  - `/api/v1/jobs/claim`, `/api/v1/jobs/machines`, `/api/v1/jobs/<number>/heartbeat|result`;
  - `/cards/agent/state|pending|result`;
  - the Footage Sorter's agent paths;
  - `/api/v1/files/locate`.
- Open with the b-roll ingest token (header `X-Ingest-Token`, compared to the token validated at boot): anything under `/broll/api/ingest/`.
- Open with the gear token (header `X-Gear-Token`): `POST` to the gear-identify path (the website's gear page asking what a photo shows).

### Session-expiry header

- Every response to a request that carried a valid browser session includes `X-CCSync-Session-Expires: <unix seconds>` when that session ends (the earlier of the cookie's signed expiry and the server's idle clock). Applies to the mounted apps too. Companion identity tokens never get it.

### Body-size gate

- Companion report `POST /api/v1/report`: 8 MB. The fleet token is checked BEFORE the body is read; a bad token is 401 "bad or missing X-CCSync-Token", or "report token not configured on server (set DASH_REPORT_TOKEN)" when the server has no shared token and the presented token is not per-editor-shaped (unless `DASH_REPORT_TOKEN_OPTIONAL` lets it through).
- `POST /api/v1/files/locate`: 512 KB.
- `POST /api/v1/diagnostics`: 256 KB, token checked first.
- `POST /cards/agent/state`: 6 MB; `POST /cards/agent/result`: 1 MB; both token checked first.
- Footage Sorter card report, volume report and ledger copies: limits set by the sorter module, token checked first. A drive scan chunk (job id in the path): sorter-set limit on the compressed body, token checked first.
- `PUT /api/v1/admin/packages/...` (publishing a companion build): 200 MB declared length only (the route counts the streamed bytes itself).
- `POST /music/api/ingest` (drag-and-drop music upload): 512 MB declared length only.
- Every other POST, PUT or PATCH: 4 MB.
- Declared `Content-Length` over the limit, or unparseable, is refused at once; a body with no length is read in pieces and refused the moment it passes the limit. Refusal: 413 `{"detail": "request body too large (max N bytes)"}`.

### Stale-page gate

- An htmx request (header `HX-Request: true`) that does not carry the current look header is answered with an empty 200 and `HX-Refresh: true` before the route runs, so a page drawn by an older build reloads and its write is never committed. Paths under `/api/`, `/cards/`, `/broll/`, `/music/`, `/ytdl/`, `/static/` are exempt.

### CSRF gate (cross-site request forgery)

- Applies to POST, PUT, PATCH, DELETE.
- Exempt exact paths: `/login`, `/api/v1/login`, `/api/v1/logout`, `/api/v1/report`, `/api/v1/verify`, `/api/v1/setup/admin`, `/api/v1/diagnostics`, `/api/v1/files/locate`, `/api/v1/gear/identify`.
- Exempt prefixes: `/api/v1/selection/`, `/api/v1/admin/packages/`, `/broll/`, `/music/`, `/ytdl/`.
- Exempt fleet paths: `/api/v1/jobs/claim`, `/api/v1/jobs/<n>/heartbeat|result`, `/cards/agent/state|result`, `/sorter/agent/cards`, `/sorter/agent/ingest/<n>/receipt|progress`, `/sorter/agent/volumes`, `/sorter/agent/ledger/scan/<n>/chunk|finish|progress`, `/sorter/agent/ledger/copies`.
- Under `/cards/` only an origin check applies: a request whose `Origin` (or, if absent or `null`, `Referer`) host differs from the `Host` header, or whose `Origin` is the literal `null` with no `Referer`, gets 403 `{"error": "this request came from another site"}`.
- Everywhere else, only requests carrying a session this server minted and still holds are checked. The token is taken from header `X-CSRF-Token`, or for a plain URL-encoded form from the hidden field `csrf`. A wrong or missing token, or a cross-site origin, gets 403 `{"detail": "missing or bad CSRF token: reload the page and try again"}` and a log warning.
- The token is derived from the session and the session secret, so it needs no storage; a request with no session gets an empty token.

### Unhandled errors

- Any unhandled error answers 500 `{"detail": "internal error"}` with nothing from the error itself; the traceback is logged with method and path, and a server-error notice is recorded on the home page's problems list (one row per route template and error type).
- A "database is locked" timeout answers 503 `{"detail": "the dashboard's database is busy; try again"}` with `Retry-After: 30`, and is counted under a separate warn-level "database busy" notice.
- Recording the notice waits at most 250 ms for the database and is dropped (logged) if busy. Mounted apps' errors are recorded once, in the dashboard's database.

## Sign-in methods and credential checks (source: auth.py)

- `DASH_AUTH_METHOD` chooses one of three methods: `smb` (default), `oidc`, `local`. Any other value refuses start-up.
- **smb**: a username and password are checked by opening an SMB session to `DASH_SMB_HOST` on port 445 with a 10 second timeout. A session the NAS mapped to guest or anonymous is rejected and logged as an error. At most 4 checks run at once; a 5th waits up to 2 seconds, then the caller is told the server is busy (the sign-in routes answer 503).
- **oidc** (single sign-on through an identity provider): passwords on the sign-in form are still checked over SMB, but the password form is break-glass: anyone who is not an admin is refused with 401 "bad username or password" (counted as a failure, logged).
- **local**: passwords are checked against the dashboard's own accounts (see "Local accounts"). A database that cannot be opened is a refusal.
- Empty username or password is always a refusal.
- Sign-in on a non-https connection when `DASH_COOKIE_SECURE` is forced on is refused with 403 "this dashboard is configured for https only (DASH_COOKIE_SECURE=1): use the https URL" (not counted as a failure). Here `X-Forwarded-Proto: https` is believed from anyone.
- A person an admin has deleted cannot start a browser session (unless named in `DASH_ADMIN_USERS`). If the database cannot be read the check lets them through. A suspended (not deleted) person can still sign in to the browser.

### Sign-in throttle

- Two budgets, stored in the database so they survive restarts: one per username and one per client address (see "Sessions and the sign-in throttle" for the numbers).
- The wait is shown as "Too many sign-in attempts. Try again in a minute / N minutes / about an hour." (rounded up to the whole minute; 45 minutes or more is "about an hour"), with a `Retry-After` header of at least 1 second.
- Each failure logs "login failure for '<user>' from <address>" (no password).
- A successful sign-in clears only the username budget; the address budget ages out on its own.

### Client address and proxies

- The client address is the network peer. `X-Forwarded-For` is believed only when the peer is inside `DASH_TRUSTED_PROXIES` (default loopback). Then the address is the rightmost hop that is not itself a trusted proxy; if every hop is trusted, the leftmost; a non-address hop stops the walk.
- When an untrusted peer sends `X-Forwarded-For`, one warning per peer per process says the header is ignored and every request through that proxy counts as one client.
- A trusted-proxies entry that is not an IP or CIDR is logged as an error and ignored. Entries may be separated by commas or semicolons.

### Browser session cookie

- Name `ccsync_session`, HttpOnly, SameSite=Lax, path `/`, lifetime equal to the absolute session lifetime (default 100 days).
- Secure flag: `DASH_COOKIE_SECURE=auto` (default) sets it only when the request is https (directly, or `X-Forwarded-Proto: https` from a trusted proxy); `1/true/yes/on` forces it; `0/false/no/off` forces it off.
- Each sign-in mints a unique cookie (random value inside) and records a server-side session row with the client address and a summary of the browser.
- A cookie with a valid signature but no live server row is not signed in (this is what makes sign-out, "sign out everywhere" and admin revoke work). `DASH_DEV_INSECURE=1` accepts it anyway.
- Sign-out revokes the server row first, then deletes the cookie.
- Cookies and identity tokens signed with any key in `DASH_SESSION_SECRET_PREVIOUS` are still accepted (nothing new is signed with them); a warning at every boot counts the retired keys and says to remove the variable once no machine still uses them. Each retired key must also pass the strength check.
- Tokens from before the current format (version 1) are rejected. A cookie with non-ASCII bytes is simply not signed in.

### Companion identity token

- Minted on companion sign-in, signed with the session secret, header `X-CCSync-Identity`. It effectively never expires (100 years). A session cookie can never be used as an identity token and vice versa.
- Older tokens that carried a 30-day expiry are still refused once past it.
- Revocation: each person can have a "valid after" time; a token issued before it is refused like a forged one. A token minted after a revocation is stamped no earlier than that time. If the revocation state cannot be read, the token is accepted.
- The dashboard can tell whether an accepted token was signed with a retired key, and counts such machines as still owing their editor one "Sign in..." click.

### Who is an admin, and what each person sees

- `DASH_ADMIN_USERS` (comma list, case-insensitive) is checked first, on every method, with no database.
- On `local` only, an account with role `admin` that is not disabled is also an admin.
- The account page can show where a person's admin power comes from: "admin_list" or "local_role".
- A non-admin only ever sees their own editor's data. An admin sees the whole fleet and may focus one editor with `?as=<editor>` in the URL (ignored for non-admins).
- A person may manage an editor's settings if it is themselves or they are an admin.

### Password floor

- A password the dashboard SETS must be at least 12 characters ("password must be at least 12 characters"). Existing passwords are never checked; a boot log line says so.

## Boot refusals for secrets and sign-in configuration (source: auth.py)

- Only secrets that are present are checked. A present but weak secret refuses start-up. "Weak" is the b-roll token rule: under 24 characters, a placeholder, or too little variety.
  - `DASH_SESSION_SECRET` weak.
  - `DASH_REPORT_TOKEN` weak.
  - any `DASH_SESSION_SECRET_PREVIOUS` entry weak.
- `DASH_COOKIE_SECURE` forced on while no TLS path is configured (the site's dashboard URL is not `https://` and `DASH_TRUSTED_PROXIES` is empty).
- `DASH_AUTH_METHOD` not one of smb, oidc, local ("Left as it is, every password would be refused").
- oidc: `DASH_OIDC_ISSUER` or `DASH_OIDC_CLIENT_ID` missing; issuer not `https://` (plain `http://` allowed only to localhost or a loopback address); no session secret.
- local: no session secret.
- smb: a session secret is set but `DASH_SMB_HOST` (and `DASH_NAS_HOST`) is empty ("no password can ever be checked and nobody could sign in. Set DASH_AUTH_METHOD=local ... or give the NAS address").
- With no `DASH_SESSION_SECRET` at all none of the session checks run (described in the code as "login switched off", a lab shape).

## Sessions and the sign-in throttle (source: sessions.py)

- Default session lifetimes: idle 100 days (time since the last request) and absolute 100 days (time since sign-in, never extended by activity). Both can be changed with `DASH_SESSION_IDLE_SECONDS` and `DASH_SESSION_ABSOLUTE_SECONDS`. Because idle equals absolute by default, a phone used offline for weeks is not signed out.
- The time a session ends is the earlier of (sign-in + absolute) and (last request + idle). This is what the `X-CCSync-Session-Expires` header reports.
- The "last seen" time is written at most once per 60 seconds per session, and that write gives up after 250 ms if the database is busy (the session stays valid).
- An expired session's row is deleted the first time a request carries it; a row whose times cannot be read means "not signed in".
- Each session row records: the user, created time, last-seen time, and "client" (address plus the first 200 characters of the browser's User-Agent, line breaks removed, "..." appended if cut).
- Browser description shown on the account page, computed from that client text, never the raw User-Agent: programs first (python-urllib, python-requests, python-httpx, curl, Wget, CCSync, "a test client"), then browser (Edge, Opera, Samsung Internet, Firefox, Chrome, Chromium, Safari; a "Safari" without "Version/" or "Mobile/" is not counted as Safari) and system (iPhone, iPad, Android, Windows, ChromeOS, macOS, Linux). Output looks like "Chrome, Windows"; "Unknown browser" when nothing matches; empty when nothing was recorded.
- Each session has a public "handle": the first 12 hex characters of its server id.
- Operations offered to other pages:
  - revoke one session (sign-out), recording who revoked it;
  - revoke all of a person's sessions, optionally except the current one ("sign out everywhere else");
  - revoke one of a person's own sessions by handle: refused as ambiguous if two of their live sessions share the handle, refused as "current" if it is the browser asking; a handle that is not 12 lower-case hex, or belongs to someone else, does nothing;
  - list a person's live sessions (newest activity first); list every live session for the admin view, capped at 200; count live sessions per person.
- Pruning (at boot and periodically by the collector): deletes sessions older than the absolute lifetime and sessions revoked more than 7 days ago.
- Personal data export for a person: their sessions (without server ids) and their username sign-in-failure row. Address-keyed failure rows are not included.
- Personal data purge:
  - "Erase history": deletes only already-dead sessions (revoked, idle-expired or past absolute) and the username failure row unless it is currently blocking sign-in. Live sessions are untouched.
  - "Delete": deletes every session and the username failure row.
- Sign-in throttle numbers:
  - Username budget: 5 failures. Address budget: 40 failures.
  - When a budget reaches its limit, sign-in is blocked for 60 seconds, doubling with each further failure (60, 120, 240 ...) up to 1 hour.
  - A failure older than 1 hour stops counting; the next failure starts a new count. Old rows are swept on every failure and at prune time.
  - Both budgets are consulted; the longer wait wins.

## Single sign-on with an identity provider (OIDC) (source: oidc.py)

- Active only when `DASH_AUTH_METHOD=oidc`. The routes always exist; when the OIDC settings are incomplete both answer 503 with the first configuration problem (for example "DASH_AUTH_METHOD=oidc but DASH_OIDC_ISSUER is not set").
- `GET /auth/oidc/login` (anyone):
  - Reads the provider's discovery document (`<issuer>/.well-known/openid-configuration`), cached 1 hour per issuer, 10 second timeout, redirects followed. The document must name an authorization endpoint, token endpoint, key set and issuer, and its issuer must equal `DASH_OIDC_ISSUER` (trailing slash ignored).
  - If discovery fails: 503 "the identity provider is unreachable. An admin can sign in at /login?local=1".
  - Otherwise a 303 redirect to the provider with a PKCE S256 challenge, random state and nonce, the configured scopes (`DASH_OIDC_SCOPES`), and the callback address (`DASH_OIDC_REDIRECT_URL`, or this request's host + `/auth/oidc/callback`, using https when the request is https).
  - Sets a signed, HttpOnly, SameSite=Lax flow cookie `ccsync_oidc` valid 10 minutes, carrying state, nonce, verifier and the `next` page (only same-site paths starting with a single `/` are kept; anything else becomes `/`).
- `GET /auth/oidc/callback` (anyone), refusals in order:
  - 400 "this sign-in expired or did not start here: try again" (flow cookie missing, tampered or older than 10 minutes);
  - 400 "bad sign-in state: try again" (state mismatch; logged with the client address);
  - 403 "the identity provider refused this sign-in" (provider returned an error; its description is not shown);
  - 400 "no authorization code in the callback";
  - 403 with a short reason when the code exchange or token check fails: the token endpoint redirected ("the sign-in was stopped rather than sending the client secret on. Point DASH_OIDC_ISSUER at the address the IdP actually serves"), the token endpoint answered non-200, no id_token, nonce mismatch, PyJWT missing ("add it to dashboard/deploy/requirements.txt and redeploy"), or "the identity provider's answer could not be verified" for any other failure;
  - 403 when the username claim (`DASH_OIDC_USERNAME_CLAIM`, default `preferred_username`) is missing, contains `@`, `/` or a backslash, or is not a valid username (starts with a letter; letters, digits, dot, dash, underscore; up to 32 characters). The username is lower-cased.
  - Fleet membership: allowed if the person is an admin, carries an admin claim value, or carries one of `DASH_OIDC_ALLOWED_GROUPS` in the groups claim (`DASH_OIDC_GROUPS_CLAIM`, default `groups`). If a group allow-list is configured and none match: 403 "this account is not a member of the group allowed to use this dashboard - ask your admin". With no allow-list, the person must be a username the dashboard already knows (ticked a project, reported, a known editor, or a local account), otherwise 403 "this account is not part of this fleet - ask your admin to add it". If the dashboard knows no editors yet, or its database cannot be read, the person is let in with a logged warning.
  - 403 "this account was removed from the dashboard - ask your admin" for a person an admin deleted.
  - Success: a session is started, the flow cookie deleted, 303 to the saved `next` page.
- The token exchange never follows redirects. The client secret (`DASH_OIDC_CLIENT_SECRET`) is sent as HTTP basic auth if the provider supports it (or does not say), else in the form body. A public client (no secret) sends none.
- The id_token signature must use an asymmetric algorithm (RS256, RS384, RS512, ES256, ES384, ES512, PS256) and is checked against the provider's key set, issuer, audience (the client id), expiry and issued-at.
- Admin by claim: if `DASH_OIDC_ADMIN_CLAIM` carries one of `DASH_OIDC_ADMIN_VALUES`, that only lets the person past the membership check and is logged at sign-in. Every later admin check reads `DASH_ADMIN_USERS` (and local roles) only, so a claim-admin is not an admin anywhere else.
- Break-glass: the password form at `/login?local=1` stays usable, but only for admins (enforced through auth by the sign-in routes).

## Local accounts (source: local_users.py)

- Used when `DASH_AUTH_METHOD=local`: the dashboard keeps its own accounts with role `admin` or `editor`, plus each account's SSH public keys (used by the internal file-transfer sidecar).
- Passwords are stored as scrypt hashes (cost 2^15, block size 8, parallelism 1, 32-byte salt, 32-byte hash); the stored cost parameters are read back on each check so they can be raised later.
- Username rule: starts with a lower-case letter; then lower-case letters, digits, `.`, `_`, `-`; up to 32 characters. Input is trimmed and lower-cased.
- Create an account: refusals "username must start with a letter and contain only lowercase letters, digits, '.', '_', '-'", "role must be one of ('admin', 'editor')", "password must be at least 12 characters", "'<name>' already exists".
- Set a password: refuses an unknown account ("'<name>' is not a local account") or a short password. Can mark the account "must change password".
- Check a password: false for an unknown or disabled account (indistinguishable from outside); a malformed stored hash is a refusal.
- Disable or re-enable: refuses disabling yourself ("you cannot disable the account you are signed in as - sign in as another admin to disable this one") and disabling the last enabled admin ("this is the last enabled admin account - create another admin before disabling it"). A disabled admin is not an admin and cannot sign in.
- Delete: the same two refusals with "delete" wording; removes the account and its SSH keys (logged as a warning); does NOT remove the person's fleet history, ticks or machine records.
- SSH keys: add (must look like an OpenSSH public key; re-adding the same key refreshes its label and time), remove by fingerprint (removing an absent key is not an error). The fingerprint is `SHA256:<base64>` of the key blob, so a trailing comment does not change it.
- Whether any account exists decides whether the first-admin window of the setup wizard is still open.

## Every environment variable the dashboard reads at start-up (source: settings.py)

Each bullet: variable, default, effect. "On only for `1`" means any other value, including `true`, is off. Where the effect is carried out by a module outside this section, the bullet says what the value is used for as far as these files show; the full behaviour belongs to that module's section.

### General and storage

- `DASH_DB_PATH`, default `/data/dashboard.db`: the database file. Its folder also holds `secrets/` and, by default, `packages/`.
- `DASH_PORT`, default 8480: listening port for the console-command start.
- `DASH_PACKAGES_DIR`, default empty (meaning `packages/` beside the database): where published companion builds are stored.
- `DASH_DEV_INSECURE`, on only for `1`: test and development hatch. Bypasses every boot refusal (weak secrets, unsaved generated secrets, unsupported projects folder name), accepts a validly signed cookie that has no server-side session row, and lets `DASH_REPORT_TOKEN_OPTIONAL` work. Logged loudly at every boot. DEV ONLY. Read from the environment even when settings are built by hand.

### Sync engine (Syncthing) and the collector

- `SYNCTHING_GUI_URL`, default empty (trailing slash removed): the NAS's Syncthing address. Empty means the collector skips every Syncthing-backed task but still prunes the database.
- `SYNCTHING_API_KEY`, default empty: Syncthing API key (also one of the five bootstrapped secrets).
- `DASH_PROJECTS_DIR`, default empty: where the dashboard sees the server's Projects tree; when set, the collector creates a Syncthing folder for any project folder lacking one. Empty disables auto-provisioning.
- `DASH_SYNCTHING_DATA_PREFIX`, default `/data/Projects`: where the Syncthing app sees that same tree.
- `DASH_SYNCTHING_ASSETS_PREFIX`, default `/data/Assets`: where Syncthing sees the shared asset libraries (LUTs); blank disables shared-folder provisioning.
- `DASH_SYNCTHING_TAILNET_IP`, default empty: when set, new device entries get direct tcp and quic addresses on this tailnet address before "dynamic".
- `DASH_SYNCTHING_TAILNET_ONLY`, on only for `1`: turn off Syncthing relays, global discovery and NAT traversal. DORMANT by default.
- `DASH_SYNCTHING_GUI_SECURE`, default on, only `0` turns it off: whether the dashboard puts a login on the Syncthing admin page when it finds none.
- Collector intervals in seconds: `DASH_INTERVAL_PROVISION` 300, `DASH_INTERVAL_CONFIG` 120, `DASH_INTERVAL_ENFORCE` 60, `DASH_INTERVAL_INVENTORY` 900, `DASH_INVENTORY_PROJECTS_PER_CYCLE` 8 projects, `DASH_INTERVAL_CONNECTIONS` 15, `DASH_INTERVAL_COMPLETION` 60, `DASH_INTERVAL_REMOTENEED` 60, `DASH_INTERVAL_PRUNE` 3600, `DASH_INTERVAL_ALERTS` 600, `DASH_INTERVAL_INVARIANTS` 900.
- `DASH_COMPLETION_BUDGET_SECONDS`, default 30 (0 disables): time budget for one sync-completion pass.
- `DASH_BACKOFF_MAX`, default 300: maximum back-off in seconds.
- `DASH_ENFORCE_MAX_REMOVALS`, default 3: an enforce pass that would unshare more than this many devices is refused (additions still apply).
- `DASH_COLLECTOR_WATCHDOG_SECONDS` 30 and `DASH_COLLECTOR_WEDGED_SECONDS` 900: see "Collector watchdog" (read in app.py, not in settings).
- A non-number in any numeric variable silently becomes its default (except the two watchdog ones, which log).

### Companion reports and fleet tokens

- `DASH_REPORT_TOKEN`, default empty: the shared fleet token. Must be strong if set.
- `DASH_REPORT_TOKEN_OPTIONAL`, on only for `1`: accept reports with no token. IGNORED (with an error in the log) unless `DASH_DEV_INSECURE=1` is also set. DEV ONLY.
- `DASH_SHARED_REPORT_TOKEN_ENABLED`: UNSET means OFF (a new site); `0/false/no/off` is off; anything else is on. Whether the one shared fleet token is still accepted beside per-editor tokens. (A settings object built in code without the environment defaults to on.)

### Sign-in

- `DASH_AUTH_METHOD`, default `smb`; trimmed and lower-cased; must be `smb`, `oidc` or `local`.
- `DASH_SMB_HOST`, default empty, falling back to the NAS host: where passwords are checked in smb mode.
- `DASH_SESSION_SECRET`, default empty: signs session cookies, identity tokens, CSRF tokens and the OIDC flow cookie. Must be at least 24 characters of random-looking text.
- `DASH_SESSION_SECRET_PREVIOUS`, comma list, default empty: retired keys still accepted, never used to sign.
- `DASH_ADMIN_USERS`, comma list, lower-cased: the admins (break-glass on every method).
- `DASH_COOKIE_SECURE`, default `auto`: see "Browser session cookie".
- `DASH_TRUSTED_PROXIES`, default `127.0.0.1,::1`: proxies whose forwarding headers are believed.
- `DASH_SESSION_IDLE_SECONDS` and `DASH_SESSION_ABSOLUTE_SECONDS`, both default 8,640,000 (100 days). A zero, negative or unreadable value falls back to the default and logs an error ("There is no 'unlimited' setting").
- `DASH_OIDC_ISSUER` (trailing slash removed), `DASH_OIDC_CLIENT_ID`, `DASH_OIDC_CLIENT_SECRET`, `DASH_OIDC_SCOPES` (default `openid profile email`), `DASH_OIDC_USERNAME_CLAIM` (default `preferred_username`), `DASH_OIDC_ADMIN_CLAIM` (default empty), `DASH_OIDC_ADMIN_VALUES` (comma list, lower-cased), `DASH_OIDC_GROUPS_CLAIM` (default `groups`), `DASH_OIDC_ALLOWED_GROUPS` (comma list, lower-cased; empty means "must be a known editor"), `DASH_OIDC_REDIRECT_URL` (default derived from the request).
- `CCSYNC_INTERNAL_TOKEN`, default empty: bearer token for the internal SFTP sidecar's routes; blank means those routes answer 503.

### NAS access (for the admin Users section and the sign-in probe)

- `DASH_NAS_KIND`, default `truenas` (or `synology`).
- `DASH_NAS_HOST` (or legacy `TRUENAS_HOST`), `DASH_NAS_USER` (or `TRUENAS_USER`), `DASH_NAS_PW` (or `TRUENAS_PW`): the new name wins when both are set. If any of SMB host, NAS host or NAS user is unset, one warning at start-up names them: "site identity not fully configured: ... The dashboard still runs; editor login (SMB probe) and the admin Users section are what need these."
- `DASH_NAS_API_KEY` (or `TRUENAS_API_KEY`): a scoped TrueNAS API key, preferred over the password. `DASH_NAS_API_KEY_USER` (or `TRUENAS_API_KEY_USER`): the account the key belongs to.
- `DASH_NAS_VERIFY_SSL` (or `TRUENAS_VERIFY_SSL`): UNSET means "trust on first use" (pin the certificate seen first); `0/false/no` is no verification; `1/true/yes` is full verification; any other value is a CA bundle path or a `sha256:` certificate pin.
- `DASH_NAS_HOMES_PARENT` (trailing slash removed): parent folder of editor home folders on the NAS.
- `DASH_NAS_SERVICE_USER`: the account the dashboard stack runs as; hidden from editor listings.
- `DASH_PROJECT_ACL`, default `shared`; `per-project` turns on per-project NAS groups.
- `DASH_NAS_PROJECTS_ROOT`: the NAS-side absolute path of the Projects folder.

### Site manifest values (published to installers and companions)

- `DASH_SITE_ORG_NAME`, `DASH_SITE_ORG_SHORT`, `DASH_SITE_SUPPORT_CONTACT`, `DASH_SITE_PRODUCT_NAME` (default `CC Sync`), `DASH_SITE_BRAND_LOGO`, `DASH_SITE_TREE_NAME`, `DASH_SITE_CANONICAL_PREFIX` (default `P:\`), `DASH_SITE_REMOTE_ROOT`, `DASH_SITE_SMB_UNC`, `DASH_SITE_SFTP_HOST`, `DASH_SITE_SFTP_PORT` (default 22), `DASH_SITE_SFTP_HOSTKEY` (whitespace collapsed; not editable from the browser), `DASH_SITE_SFTP_CHUNK_SIZE`, `DASH_SITE_SFTP_CONCURRENCY` (0 means "server does not say"), `DASH_SITE_SFTP_SHELL_TYPE`, `DASH_SITE_RCLONE_REMOTE`, `DASH_SITE_NAS_SYNCTHING_ID`, `DASH_SITE_DASHBOARD_URL` (trailing slash removed), `DASH_SITE_INDEXER_MODEL_TIER` (default `good`; anything other than `good`/`best` logs a warning and becomes `good`). See "Stored site settings" for how these are copied and overridden.
- Feature switches, each on only for `1`, all off by default: `DASH_SITE_YOUTUBE_DOWNLOAD` (the YouTube downloader), `DASH_SITE_YOUTUBE_UNBLOCK` (its anti-blocking components; meaningless without the first), `DASH_SITE_AI_CLI_PROVIDERS` (allow a Claude Code or Codex command-line tool on the host as an AI provider), `DASH_SITE_AI_CLI_AUTO_UPDATE` (keep that tool updated automatically), `DASH_SITE_AUTO_UPDATE` (companions install any newer offered build unattended).
- Reporting switches, each ON by default, only `0` turns one off: `DASH_SITE_TELEMETRY_RESOLVE_PROJECT`, `DASH_SITE_TELEMETRY_LOCAL_MANIFEST`, `DASH_SITE_TELEMETRY_MEDIA_TREE`, `DASH_SITE_TELEMETRY_INPUT_IDLE`.
- `DASH_SITE_PROJECTS_DIR` (read straight from the environment): any value other than blank or `Projects` refuses start-up with "refusing to start: DASH_SITE_PROJECTS_DIR=... - this build only supports a tree whose projects live in `Projects`..." (bypassable with `DASH_DEV_INSECURE=1`).

### Upgrade channel and vendor feed

- `DASH_RELEASE_PUBKEYS` (comma or space separated; with vendor defaults on and the variable unset, the vendor's key): Ed25519 public keys release signatures are checked against. Only values that decode to exactly 32 bytes are kept, so a placeholder counts as "no key configured".
- `DASH_RELEASE_FEED_URL` (with vendor defaults on and unset, the vendor's feed URL): the signed vendor feed. Empty disables the feed and its poller.
- `DASH_RELEASE_FEED_SIG_URL`: explicit signature URL; a warning is logged if set without a feed URL.
- `DASH_RELEASE_FEED_POLICY`, default `manual`; `stage` auto-publishes new builds without making them current; `current` auto-publishes and makes current. Any other value logs a warning and becomes `manual`.
- `DASH_RELEASE_FEED_INTERVAL`, default 86400 seconds: feed poll interval.
- `DASH_RELEASE_SOAK_MINUTES`, default 30: how long a staged build must have run crash-free on at least one machine before it can be made current (0 turns the gate off; a stored value overrides).
- `DASH_VENDOR_DEFAULTS`: see "Vendor defaults".
- `DASH_VENDOR_CUSTOMER`, on only for `1`: says the private half of the pinned vendor key is the vendor's.

### Mounted apps

- `DASH_BROLL_ENABLED`, on only for `1`: mount b-roll at `/broll`. `BROLL_INGEST_TOKEN` must then be strong or start-up is refused.
- `DASH_JOBS_MAX_RUNNING` (for example `whisper=2,proxy-480p=4`; bad entries dropped, minimum 1): fleet-wide cap per job kind.
- `DASH_JOBS_COOLDOWN_SECONDS`, default 120 (0 disables): how long a machine is skipped after a failed job.
- `DASH_JOBS_ROOTS` (for example `vault=/vault,media=/media`; names lower-cased, trailing slash removed): what this container calls each root for jobs it runs itself.
- `DASH_CARDS_SERVER_URL`, `DASH_CARDS_TOKEN`: the Timeline Cards server the agent tunnel forwards to; blank means the three `/cards/agent/*` routes answer 503 naming the variable.
- `DASH_CARDS_ENABLED` (on only for `1`), `DASH_CARDS_SRC`, `DASH_CARDS_VAULT_ROOT`, `DASH_CARDS_ROOT`, `DASH_CARDS_ENGINES` (default 2, minimum 1: episodes that may have an engine at once), `DASH_CARDS_PROJECT`, `DASH_CARDS_DB_HOST`, `DASH_CARDS_DB_NAME`, `DASH_CARDS_DB_WRITE_ALLOW`, `DASH_CARDS_DB_BACKUPS`, `DASH_CARDS_MEDIA_MAP`: Timeline Cards hosting.
- `DASH_CARDS_EDITOR` (on only for `1`), `DASH_CARDS_EDITOR_PORT` (default 0 = a free loopback port at each start), `DASH_NODE` (default `/opt/node/bin/node`, else `node` on the path): the new Cards editor.
- `DASH_CARDS_OLD_PAGE`, on only for `1`: with the new editor on, brings the old Cards page back (rollback).
- `DASH_SORTER_ENABLED` (on only for `1`), `DASH_SORTER_SRC`, `DASH_SORTER_DATA`, `DASH_SORTER_CACHE`, `DASH_SORTER_SETTINGS` (JSON): the Footage Sorter.

## Stored site settings (the site manifest as data) (source: site_store.py)

- The site manifest is stored as key/value rows in the dashboard database. For each key the answer is: the stored row if one exists, else the matching environment-derived setting, else a built-in default.
- **One-time seed from the environment**: at boot, if the table is empty AND the process environment has at least one non-blank `DASH_SITE_*` variable, every non-blank manifest value from the environment is copied into the table (logged "the database is now authoritative for the site manifest -- a later env change will not be picked up automatically"). After that, environment changes to these keys are ignored. A deployment with no `DASH_SITE_*` never seeds. The seed is exempt from the tree lock and the SFTP-window check.
- At every boot the site's reporting policy is also applied to every computer's held data (see telemetry below). Failure is logged, never fatal.

### Every stored key, its default and its validation

- `org_name` (text, default blank): the organisation's name; used in the app title and brand.
- `org_short` (text, default blank): short name for a topbar or tray tooltip.
- `support_contact` (text, default blank, which resolves to `support@thecreatorsclub.co`): where problems are sent. Help text that says "send us" or "to us/to support" gets " Support: <address>" appended (never twice). Settings and the export show only the site's own value, never the vendor default.
- `product_name` (text, default `CC Sync`).
- `brand_logo` (text, default blank = the product's own mark): a mark name shipped with the companion or an absolute path on the editor's machine.
- `tree_name` (text), `canonical_prefix` (default `P:\`), `remote_root` (text): the three "tree keys" (see the tree lock).
  - `canonical_prefix` must be a Windows drive letter (`P:` or `P:\`, a missing backslash is added) or a POSIX absolute path with no `..` (trailing slash removed). Blank is refused ("must not be blank"). Otherwise "must be a Windows drive letter like 'P:\\' or a POSIX absolute path like '/mnt/tree'".
- `smb_unc`, `sftp_host`, `sftp_shell_type`, `rclone_remote`, `nas_syncthing_id`, `dashboard_url`, `sftp_chunk_size` (text).
- `sftp_port` (whole number, default 22), `sftp_concurrency` (whole number, default 0). Whole numbers: blank allowed, not negative ("must not be negative"), "'x' is not a whole number".
- `template_folders` (list, default from the provisioning module): folders laid down in every new project.
- `shared_asset_folders` (list, default from the provisioning module): shared libraries synced to every computer (for example LUTs).
  - Both lists: each item must be a path under the tree root: not absolute ("must be a path under the tree root, not an absolute path"), no drive letter, no `..` ("must stay under the tree root: '..' is not allowed").
  - Shared asset folders additionally: each name must contain at least one ASCII letter or digit ("needs at least one letter A-Z or digit 0-9 in its name: the folder id every computer syncs it by is made from those"), and two names may not produce the same folder id ("would share the folder id ...: rename one of them").
- `nas_kind` (default `truenas`): lower-cased; must be a kind the NAS client can build, otherwise "must be one of ..."; blank refused.
- `features.youtube_download`, `features.youtube_unblock`, `features.ai_cli_providers`, `features.ai_cli_auto_update`, `features.auto_update` (switches, default off): must be `1` or `0`, blank becomes `0`.
- `indexer_model_tier` (default `good`): must be `good` or `best` (lower-cased); which local vision model the b-roll indexer loads.
- `android.package_name` (default blank = no Android app): two or more dot-separated parts, each starting with a letter or underscore, otherwise "must be an Android package name like 'net.ts.example.ccsync'...".
- `android.sha256_cert_fingerprints` (list, default blank): comma or newline separated; a leading `SHA256:` is stripped; upper-cased; each must be 32 colon-separated hex pairs; duplicates dropped. No environment twin: only settable from Settings or import.
- `telemetry.resolve_project`, `telemetry.local_manifest`, `telemetry.media_tree`, `telemetry.input_idle` (switches, default ON = reported): must be exactly `1` or `0` (blank is refused, because `0` deletes data fleet-wide).
- Every text value is trimmed and refused if it contains a control character. An unknown key is "not a recognised site setting". Validation of a whole form happens before anything is written, so one bad field changes nothing.
- Retired keys `ui_terminal_groups` and `ui_preview` are deleted at boot.

### Rules applied on every save (not the boot seed)

- **Tree lock**: once any computer has registered or reported, changing `canonical_prefix`, `tree_name` or `remote_root` is refused: "... cannot be changed once computers have registered: every installer and companion builds its paths from it. To move the tree on purpose, set DASH_SITE_TREE_KEYS_UNLOCKED=1 for the change, plan every computer's move first, and see docs/TREE_LAYOUT_AGNOSTICISM.md". Saving the value a key already has is not a change. `DASH_SITE_TREE_KEYS_UNLOCKED=1` in the environment lifts the lock.
- **SFTP window check**: a save, import or undo that changes the SFTP chunk size, concurrency or NAS kind is refused if the resulting combination would truncate large downloads on a NAS whose SSH server cannot serve it; the message ends ". Use 64Ki and 16, or leave both blank." (The rule itself lives in the SFTP-transport module.)
- **Telemetry hook**: any save that includes a telemetry key immediately applies the site's whole reporting policy: what a switched-off category left behind is deleted for every computer, and a log line records what was withheld and cleared.
- Each row records when and by whom it was updated.
- A key can also be deleted so it falls back to its default.

### What the manifest publishes

- The resolved manifest (used by the open `/api/v1/site` route and by page rendering) contains: org name, org short, support contact (or the vendor default), product name, brand logo, tree name, canonical prefix, remote root, SMB UNC path, SFTP host, SFTP port, SFTP chunk size and concurrency (on an affected NAS, blank or unsafe values are replaced by safe ones on the wire), shell type, rclone remote name, NAS Syncthing id, dashboard URL, template folders, shared asset folders (id, relative path, label), NAS kind, the five feature switches (the two command-line AI switches are forced off in the locked vendor build), indexer model tier, Android identity, the four reporting switches as set, which keys are stored in the database, and any SFTP-window problem.
- Feature check used everywhere ("is feature X on?"): a stored row wins over the environment (a stored `0` beats `DASH_SITE_*=1`); unknown feature names, unreadable tables and the build lock all read as OFF.
- Reporting policy check: the set of categories this site withholds; `resolve_project` withheld implies `media_tree` withheld. If the table cannot be read, the answer is the environment's values plus the policy last applied, so a stored "off" does not quietly lapse.
- The resolved manifest is cached per process and dropped on every site write; if the database cannot be read for a render, the environment-only values are used for that render only.
- Keys `dashboard_url`, `sftp_host` and `nas_syncthing_id` are marked as automatically derived (greyed out on Settings when a live value exists).

### Export and import as `site.toml` text

- Export writes the resolved values (with the raw, not resolved, support contact and the raw stored AI-tool switches) as TOML in sections: `[nas] kind`; `[tree] tree_name, remote_root, smb_unc, template_folders, shared_assets`; `[net] dashboard_url, sftp_host, sftp_port, sftp_chunk_size, sftp_concurrency, shell_type, rclone_remote`; `[syncthing] device_id`; `[site] org_name, org_short, support_contact, product_name, brand_logo, canonical_prefix`; `[features] youtube_download, youtube_unblock, ai_cli_providers, ai_cli_auto_update, auto_update`; `[indexer] model_tier`; `[android] package_name, sha256_cert_fingerprints`; `[telemetry] resolve_project, local_manifest, media_tree, input_idle`. It begins with three comment lines saying it carries only the fields the dashboard stores.
- Import parses pasted TOML ("could not parse: ..." on a syntax error). Any key in those sections that maps to a stored key is taken (true/false become 1/0, lists are comma-joined); every other section and key is silently ignored. One exception: `[tree] projects_dir` with any value other than blank or `Projects` is refused ("... is not supported: this build only supports a tree whose projects live in `Projects` ...").
- A change list can be computed before writing (for an import preview or the undo snapshot); values of any key whose name looks secret are shown as `********` (no current key does). The list of reporting categories a change would turn off is computed so the confirmation can say what will be deleted.

## Secrets bootstrap (source: secrets_boot.py)

- Runs before settings are read, on every start-up. Five secrets: `DASH_SESSION_SECRET`, `DASH_REPORT_TOKEN`, `BROLL_INGEST_TOKEN`, `SYNCTHING_API_KEY`, `CCSYNC_INTERNAL_TOKEN`.
- For each, in order:
  1. If the environment has a non-blank value, it is used and nothing is written ("env").
  2. Else, if `<data>/secrets/<lower-case name>` (for example `/data/secrets/dash_session_secret`) holds a value, it is used ("file").
  3. Else, for `SYNCTHING_API_KEY` and `CCSYNC_INTERNAL_TOKEN` only: if the sidecar's env file already holds one (`syncthing.env` key `STGUIAPIKEY`, or `internal.env` key `CCSYNC_INTERNAL_TOKEN`; tolerant of comments, blank lines, `export ` and quotes), it is adopted and mirrored into the plain file ("sidecar-file").
  4. Else a new random value (32 random bytes, URL-safe text) is generated and saved ("generated"). If saving fails, a warning says it "will be regenerated on the next boot unless the environment sets it" (and start-up is then refused by the app, see "Process start-up").
- `<data>` is the folder holding `DASH_DB_PATH` (default `/data`).
- One log line names where each secret came from; values are never logged.
- Files are written atomically with owner-only permission (a temporary sibling file, flushed to disk, then renamed), so a failed write never destroys the good copy and never leaves an empty file.
- Every start-up also rewrites the two sidecar env files from the current values:
  - `<data>/secrets/syncthing.env` with `STGUIAPIKEY=<key>`;
  - `<data>/secrets/internal.env` with `CCSYNC_INTERNAL_TOKEN=<token>` and, only if BOTH `APP_UID` and `APP_GID` are set, `APP_UID=` and `APP_GID=` lines (if only one is set, neither is written and a warning says the file-transfer sidecar keeps the container's own ownership);
  - an old `sftp.env` is deleted.
  - A failure to write these is a warning only. The sidecars read them only at their own start, so a rotated secret needs the sidecars restarted.
- The same atomic, owner-only writer is offered to other modules (the AI provider keys use it).

## Appliance configuration overlay: settings typed into the wizard instead of the container (source: appliance_config.py)

- File: `<data>/secrets/appliance_config.json`, owner-only. Holds values for an allow-list of environment variables. At start-up each stored value is copied into the environment ONLY if the real environment leaves that variable blank (the container's own environment always wins). The names applied are logged, never the values. A missing or damaged file is treated as empty.
- The allow-list, by wizard step, with field labels and help text:
  - `admin` step: `DASH_ADMIN_USERS` "admin account name" ("The sign-in account that may administer this dashboard. It must NOT be the NAS's own admin account. Several can be given, separated by commas."). Each name: 1 to 64 of letters, digits, `.`, `_`, `@`, `\`, `-`; at least one required ("enter at least one account name"); commas or semicolons separate.
  - `syncthing` step: `SYNCTHING_GUI_URL` "sync engine address" (placeholder `http://tailscale:8384`). Must be a full `http://` or `https://` address with a host and no username or password in it; trailing slash removed.
  - `nas_connect` step:
    - `DASH_NAS_KIND` "NAS type", a select of `truenas` / `synology` ("choose truenas or synology").
    - `DASH_NAS_HOST` "NAS address": a host name or IP with optional port, no `http://` ("enter the NAS's name or IP address, with no http:// in front").
    - `DASH_NAS_USER` "NAS admin account" (Synology only).
    - `DASH_NAS_API_KEY` "NAS API key" (TrueNAS only; secret).
    - `DASH_NAS_API_KEY_USER` "NAS API key account" (TrueNAS only; required with a key).
    - `DASH_NAS_PW` "NAS admin password" (Synology only; secret).
    - `DASH_NAS_VERIFY_SSL` "NAS certificate fingerprint": blank means record the certificate on first connect and refuse a different one later; `sha256:` plus 64 hex digits pins it; `1` verifies against system certificate authorities. There is no way to turn verification off from the wizard.
  - `release_key` step: `DASH_RELEASE_PUBKEYS` "update signing key": one or more keys that each decode to 32 bytes ("that is not an update signing key (it should be 44 characters of letters and digits ending in =)").
  - `software` step: `DASH_RELEASE_FEED_URL` "vendor update feed": must be `https://`.
- Secret values (longer than 400 characters or containing control characters are refused) are never shown back: the form says only whether something is set. A blank secret field keeps the stored value; a blank plain field clears it.
- Cross-checks on save:
  - `admin` and `nas_connect`: the NAS admin account may not be one of the dashboard admins ("the dashboard's admin account must not be the NAS's own admin account (...). Make a separate sign-in for the dashboard admin, so a stolen dashboard login is not the key to the whole NAS.").
  - `nas_connect` on TrueNAS: a password is refused ("a TrueNAS NAS is connected with an API key, never the admin password..."); an API key without its account name is refused ("a TrueNAS API key needs the name of the account it was made for...").
- Other refusals: "this step has nothing to fill in here" (a step with no form), "not a setting of this step: ...", "nothing to save", "could not store the setting (...)". Field errors are prefixed with the field label.
- Saving is followed by a process restart about 1.5 seconds later (exit code 75), so the response reaches the browser first and the new value is read at the next start.
- Each form also shows an operator note listing the environment variable names behind it.

## First-run setup wizard: the task list and every check (source: setup_engine.py)

- The wizard (page `/setup`, and the same list on the admin Settings page) is a list of tasks. Each task has a title, a description, a CHECK (looks and reports, changes nothing), an optional action button, and a state: `todo`, `ok`, `warn`, `fail` or `skipped`, with a one-line detail and a time. States are stored, so a restart mid-wizard resumes where it was.
- Pressing CHECK or the action on a task saves the resulting state. A task's check or action that crashes is shown as `fail` "internal error: ...", never a server error. Only one check or action per task runs at a time.
- Required tasks cannot be skipped ("... is required and cannot be skipped"). Skipping an optional task stores "skipped by admin" and a separate permanent skip record, so a later CHECK does not un-skip it for the completeness gate.
- "Outstanding required" (drives the wizard landing and the Setup badge in the navigation): every non-optional task not `ok`. Exception: the licence task in `warn` counts as satisfied only while the build really has no licence file (checked on the file system each time).
- **Completeness gate**: the `done` task stays `todo` "waiting on: <titles>" until every required task is satisfied AND each of `release_key`, `snapshots` and `alerts` is `ok`, `skipped`, or has a recorded skip.
- Task order and behaviour:

### 1. `eula` "Welcome, EULA" (required): "Read and accept the license agreement."

- The licence file is looked up in order: `DASH_EULA_DOC` (environment), `<app>/docs/legal/EULA.md`, `<repo>/docs/legal/EULA.md`. Re-looked-up later if it was missing at start-up and appears afterwards.
- Version is read from a `<!-- EULA-VERSION: x -->` marker (else "unversioned").
- Check: no file is `warn` "no licence agreement is included in this build, so nothing has been accepted"; unreadable is `fail` "could not read EULA: ..."; accepted for this exact version is `ok` "accepted v<version>"; otherwise `todo` "awaiting acceptance of v<version>". A new version therefore needs a new acceptance.
- Accept (only through the EULA route, which the page drives with a checkbox): `ok` "accepted v<version>" (or the same warn/fail as above).

### 2. `admin` "Create your admin account" (required, no action button): "A local account for you. No NAS credential is involved."

- If an identity module reports local-account status, that answer is used (no such module ships; see "Could not determine").
- Sign-in method `local`: `ok` "admin account: <names>" (or "an admin account exists") once any local account exists; else `todo` "no admin account yet"; a database without the accounts table gives `todo` "awaiting identity module".
- `smb` or `oidc` with `DASH_ADMIN_USERS` set: `ok` "admins are NAS accounts (<nas kind>): <names>" or "admins are your identity provider (oidc): <names>".
- `oidc` with no admin list: `todo` "no admin is configured for oidc login: type the account name(s) that may administer this dashboard in the box on this row and save" plus, if an admin claim is configured, "(the <claim> claim is only logged at sign-in; it does not make anyone an admin)".
- `smb` with no admin list: `todo` "no admin is configured for smb login: type the NAS account name(s) ...".
- The row carries the admin-name form (except on `local`, where the account is made by the first-admin form instead).

### 3. `studio` "Your studio" (required, no action button): "Name, tree name, drive letter and the project template."

- `ok` "<org name> / <tree name>" once organisation name, tree name, canonical prefix and template folders all have values; else `todo` "not set: <keys>". The values are written through the admin site-settings route.

### 4. `storage` "Storage check" (required): "Confirm the tree is writable and lay down the shared asset folders."

- The tree root is `DASH_TREE_DIR` if set (must exist), else the parent of `DASH_PROJECTS_DIR` unless that parent is a file-system root.
- Check: Projects folder not mounted is `todo` "DASH_PROJECTS_DIR is not mounted". With no visible tree root: `todo` "not yet probed: click Do it" if not writable, else `ok` "writable. The shared asset folders live beside Projects on the NAS, which this container does not mount; <free> free". With a tree root: `todo` "not yet probed: click Do it" while any shared asset folder is missing, else `ok` "writable; <free> free".
- Action ("DO IT"): writes, reads back and deletes a probe file `.ccsync-setup-probe` in the Projects folder. Failure is `fail` "could not write/read/delete a probe file: ..."; for a permission refusal it adds which account the container runs as, who owns the folder, and how to fix it (create a dedicated NAS account, set `APP_UID` and `APP_GID` "in the Environment tab, and redeploy"). Then, if the tree root is visible, creates each shared asset folder (never changes ownership): `ok` "writable; <free> free; created N shared asset folder(s)" or `warn` "writable, but could not create <folders> under <root> - check the mount's ownership". If not visible: `ok` with the "live beside Projects" sentence. Not mounted at all: `fail` "DASH_PROJECTS_DIR is not mounted: add the volume and redeploy".

### 5. `secrets` "Secrets" (required): "Session, report, ingest and sidecar credentials."

- Check: `ok` "all five secrets present" when each of the five is in the environment or has a file; else `todo` "not yet generated: <names>".
- Action ("DO IT"): runs the secrets bootstrap again for the data folder (writes files only; does not change the running process). If any was generated: "...; generated N just now. Press RESTART SERVER on this row to load them". The row offers a restart button.

### 6. `syncthing` "Sync engine" (required): "Confirm the bundled Syncthing is reachable."

- No address configured: `todo` "no sync engine address is set: type it in the box on this row and save (the bundled one is http://tailscale:8384)".
- Check (5 second timeout): unreachable is `fail` "unreachable: ..."; no device id is `warn` "reachable but reported no device id"; otherwise `ok` "device id <first 7 characters>...", turned into `warn` with "...; its admin page has no password, so anyone on your network can reach it. This server sets one itself on its next cycle, or now with the button on this row" when Syncthing's own admin page is unprotected.
- Action ("DO IT"): the same probe, then puts a password on Syncthing's admin page if it has none (failure only logged), and fills the site's `nas_syncthing_id` with the device id only if that is still blank.

### 7. `done` "Done" (required, check only): "Everything required is configured." See the completeness gate.

### 8. `tailnet` "Connect to your tailnet" (optional, button "SIGN IN OR PUBLISH"): "Sign this node into your Tailscale network."

- Check, when a bundled Tailscale node answers on its local socket:
  - Not running and has a sign-in link: `todo` "this node is not signed in yet (<state>): open <link> to add it to your tailnet".
  - Not running, no link: `todo` "the bundled Tailscale node is <state>, with no sign-in link yet: press SIGN IN OR PUBLISH on this task (docs/APPLIANCE_INSTALL.md step 4 is the command-line way in)".
  - Running: if the node's key expires within the warning window (set in tailnet_serve), `warn` "..., but its key expires in N day(s). When it does every editor loses the server at once. In the Tailscale admin console open Machines, this node, and choose Disable key expiry". Otherwise `ok` "the bundled Tailscale node is signed in as <name>, published at <url>" when Serve publishes it and the tailnet can issue https certificates, or `ok` "...; editors reach this dashboard at <url>, a tailnet address" when the site's dashboard URL is a tailnet address. A later key expiry date is appended as a note. Otherwise `todo`: https certificates are off on the tailnet; or the Serve settings could not be read; or "nothing publishes this dashboard on the tailnet, so no editor can reach it (it listens on the NAS itself only)". Each `todo` adds the by-hand command "docker compose exec tailscale tailscale serve --bg http://dashboard:8480".
- Check, with no bundled node: no dashboard URL is `todo` "no dashboard URL is published to editors yet: set dashboard_url on the Settings page, or publish this dashboard with Tailscale Serve (docs/INSTALL.md)"; a URL whose host ends `.ts.net` or is in 100.64.0.0/10 is `ok` "editors reach this dashboard at <url>, a tailnet address"; any other is `todo` "... which is not a tailnet address. Publish it with Tailscale Serve so editors need no VPN of their own".
- Action: if no bundled node, answers the check. If the node is signed in, publishes the dashboard through Tailscale Serve (see "Publishing on the tailnet"); on failure `todo` "the node is signed in, but the dashboard could not be published on the tailnet: ..."; on success the check's answer. If not signed in: returns the node's sign-in link, or starts an interactive login and waits up to 5 seconds (checking every half second) for a link; answers `todo` "open <link> and sign in, then press CHECK on this task". It never reports success by itself. Failures: "the bundled Tailscale node did not accept a sign-in request ..." or "... has not produced a sign-in link yet: press this again in a moment ...".

### 9. `nas_connect` "Connect to your NAS" (optional, no action button): "One-time admin credential for snapshots and SMB users."

- No credential stored: `todo` "no NAS credential is stored yet: fill in the NAS address and API key (TrueNAS) / admin password (Synology) in the boxes on this row and save". The row carries the NAS form (see "Appliance configuration overlay").
- Otherwise pings the NAS with a 3 second limit: refused is `fail` "<kind> at <host> refused the credential in this container: ..."; other errors `fail`; success is `ok` "<kind> <version> at <hostname> answered" (plus a support note if the TrueNAS version is outside the supported range) or `ok` "<kind> at <host> answered" when version information cannot be read. Error text is squeezed to one line of at most 100 characters.

### 10. `snapshots` "Protect your data" (optional, gate, no action button): "Schedule NAS snapshots or export a /data backup."

- `ok` "N periodic snapshot task(s) on the NAS" (plus the newest backup name) when the NAS lists any snapshot task; `ok` "/data backup <name> is under 7 days old, but there is no NAS snapshot schedule (<why>)" when only a recent backup exists; otherwise `todo` "no NAS snapshot schedule (<why>) and no /data backup in the last 7 days: docs/BACKUP_RESTORE.md section 2". On Synology the reason is "synology snapshot schedules cannot be read over its API".

### 11. `editors` "Editors" (optional, no action button): "Add your first editor."

- `ok` "N editor(s): <first five names>, and N more" from every username the dashboard knows plus, on `local`, enabled editor accounts; else `todo` "no editors yet: open Settings, then USERS, and add one".

### 12. `software` "Software for editors" (optional, button "CHECK NOW"): "Publish the current companion build for Windows and macOS."

- Check: `ok` "windows <v> current, macos <v> current" when both platforms have a current companion build; `warn` when only one does (the other says "<platform>: none published"); `todo` "no companion build is current for any platform: open Settings, then Packages, and publish one from the \"From the vendor\" window"; `fail` when the packages table cannot be read.
- Action: with no feed address, the check plus "; no vendor update feed address is set (type it in the box on this row and save), so there is nothing to check for". Otherwise polls the vendor feed now (applying this site's feed policy) and appends "; published from the vendor feed: <versions>" or "; the vendor feed has nothing this dashboard does not already hold", or turns an `ok` into `warn` with "; the vendor feed check failed: ...". The row carries the feed-address form.

### 13. `release_key` "Signing key for updates" (optional, gate, no action button): "The key this server checks every CC Sync build against."

- `ok` "the vendor's signing key is pinned: this server only accepts builds the vendor signed" on a vendor or vendor-customer build holding only the vendor's key; else `ok` "N release signing key(s) configured" (never the key itself); with none, `todo` "no release signing key: this server refuses every build until this server holds the vendor's public signing key, so your editors' computers can never be updated from here. Do not make a key of your own: paste the vendor's in the box on this row and save (docs/INSTALL.md step 6). Skipping means updates wait until you do". The row carries the key form.

### 14. `alerts` "Who should we tell?" (optional, gate, button "SAVE A DESTINATION")

- Description: "This server checks dozens of things about your fleet every few minutes. It needs somewhere to send what it finds. With nobody to tell, the first anyone hears of a stopped sync is an editor asking."
- Check: no destination is `todo` "nobody is being told: ... Add an email address or a webhook URL. ..."; webhook chosen without URL is `warn`; webhook set is `ok` "alerts go to <masked URL>"; email chosen without address is `warn`; address without mail server is `warn` "we have an address (<to>) but not the mail server that would send to it: open Settings, then ALERTS and fill in the mail server"; mail user without password is `warn`; otherwise `ok` "alerts go to <to> through <host>". Every `ok` adds whether the daily "still here" message is on ("; a daily still-here message is on" or "; the daily still-here message is off, so nothing tells you if this server itself goes down").
- Action: takes one email address OR one webhook URL (both is `todo` "pick one: ..."; neither repeats the check or says "enter an email address or a webhook URL under WHO SHOULD WE TELL above, or open Settings, then ALERTS for the full form"). An email must contain `@` not at either end ("... does not look like an email address"). Saving an email sets the sink to email, the recipient, and (only if none is stored) the sender to the same address. Saving a webhook sets the sink to webhook and its URL. An optional heartbeat choice turns the daily message on or off. Validation errors from the alerts module are shown as `fail`.

## First-run and setup HTTP routes (source: setup_api.py, setup_routes.py)

### Who may call the setup routes

- **First-run window**: open only when the sign-in method is not `oidc` AND (no identity module answers, so) the method is `local` and no local account exists. On `smb` and `oidc` it is never open.
- Every `/api/v1/setup/*` route (except the two below from setup_api) requires: a signed-in admin (non-admin session: 403 "admins only"), OR, only for the task list read and the two EULA routes, an anonymous caller during the first-run window. Anonymous during the window on any other route: 401 "create the admin account first (step 2), then this step opens". Otherwise 401 "log in first".

### Routes

- `GET /api/v1/setup/status` (anyone, no session): `{auth_method, users_exist}`. `users_exist` is the real answer only on `local`; on any other method it is always true so the wizard never offers to create a local admin.
- `POST /api/v1/setup/admin` (anyone, no session, no CSRF), body `{username 1-32 chars, password 1-256 chars}`: creates the FIRST local admin and signs that browser in. Refusals: 403 "first-admin setup only applies when DASH_AUTH_METHOD=local"; 409 "an admin account already exists" (checked inside a write-locked transaction so two simultaneous submissions cannot both win); 422 with the account rule that failed (username shape, 12-character password). Logged with the client address. Answers `{ok, user, is_admin: true}`.
- `GET /api/v1/setup/tasks` (admin or first-run): every task with id, title, description, optional, whether it has an action, the action label, when a skip was recorded, whether it is one of the three gate tasks, its form fields (only for a signed-in admin; never secret values; no admin-name form on `local`), the operator note naming the environment variables, whether it offers a restart (only `secrets`), and its state; plus the outstanding required list and what `done` is waiting on (id and title).
- `POST /api/v1/setup/tasks/{id}/check` (admin): runs and stores the check. Unknown id: 404 "unknown setup task '<id>'".
- `POST /api/v1/setup/tasks/{id}/run` (admin): runs the action. A task with none: 400 "'<id>' has no automatic action: see its description".
- `POST /api/v1/setup/tasks/{id}/skip` (admin): optional tasks only (400 for a required one).
- `POST /api/v1/setup/config/{id}` (admin session only), body `{values: {VAR: text}}`: saves that step's wizard form (see "Appliance configuration overlay"); 422 with the refusal text; writes an audit row naming the keys (never values); then restarts the server about 1.5 seconds later. Answers `{ok, saved: [names], restarting: true}`.
- `POST /api/v1/setup/restart` (admin session only): audit row "setup.restart", then restarts the server about 1.5 seconds later.
- `GET /api/v1/setup/eula` (admin or first-run): `{text, version}`; empty text and no version when the build has no licence file; 500 "could not read EULA: ..." if unreadable.
- `POST /api/v1/setup/eula` (admin or first-run): accepts the licence (see task 1).
- `POST /api/v1/setup/alerts` (admin), body `{email up to 320 chars, webhook up to 1024 chars, heartbeat true/false/absent}`: the alerts task action. When something was saved and did not fail, an audit row records the sink type only (never the address).
- `POST /api/v1/setup/alerts/test` (admin): sends a test alert ("This is a test of the CC Sync alert channel. Nothing is wrong.") with duplicate suppression off; answers `{ok, sent_to, detail}`.

### Site settings admin routes (admin session; 401 "log in first", 403 "admins only")

- `GET /api/v1/admin/site`: the resolved manifest, plus the list of automatically derived keys, plus counts of computers whose last report arrived over https, local plain http and public plain http.
- `PUT /api/v1/admin/site`, body `{values: {key: text}}`: saves (retired look keys silently dropped). Validation, tree lock, SFTP check and telemetry hook as in "Stored site settings"; 422 with the reason. A change to a tree key or a reporting switch is recorded in the site change history (who, when, before, after). Audit row names the keys only. Clears the cached manifest; logs the admin and keys. Answers the new manifest.
- `GET /api/v1/admin/site/export`: plain text TOML export.
- `POST /api/v1/admin/site/import`, body `{text up to 65,536 chars}`, query `dry_run`: 422 "no recognised [section] keys found in that text", or a validation, SFTP or tree-lock refusal. Dry run answers the masked change list, its count, and which reporting categories it would switch off, and writes nothing. A real import writes, records a history entry only if something changed, audits the keys and answers the new manifest.
- `GET /api/v1/admin/site/history`: each recorded change's time, actor, action (save, import or undo) and number of keys, never the values; the newest entry also lists the reporting categories undoing it would switch off.
- `POST /api/v1/admin/site/undo-last-change`, optional body `{expected_at}`: re-applies the newest history entry's "before" values through the same checks. Refusals: 404 "no site setting change is recorded to undo"; 409 "the newest change is no longer the one you confirmed (someone saved since): reload the page" when `expected_at` does not match; 409 "that change recorded no values to restore"; 422 validation or tree lock. Records the undo itself as a history entry (so an undo can be undone), audits, logs, and answers the manifest plus the masked change list.

## Reading the bundled Tailscale node (source: tailscale_local.py)

- Talks to a Tailscale node running beside the dashboard through its local socket (default `/var/run/tailscale/tailscaled.sock`, overridden by `TS_SOCKET`). Read only. 2 second timeout, at most 1 MB of answer.
- If the socket does not exist (every deployment without the bundled node, and always on Windows), every question answers "nothing there" quietly, with no log line.
- Reads the node's status and reduces it to: state (for example "Running"), sign-in link, the node's tailnet name (trailing dot removed) and its tailnet addresses. Any failure (refused, non-200, unreadable) is "no answer".

## Publishing the dashboard on the tailnet, and keeping it published (source: tailnet_serve.py)

- Writes the node's "Serve" configuration so the tailnet name answers https on port 443 and forwards everything to the dashboard. Forward address default `http://dashboard:8480`, overridable with `DASH_SERVE_BACKEND` (trailing slash removed). 3 second timeout.
- Reading the current Serve configuration distinguishes "empty" (nothing published) from "could not ask".
- An existing Serve configuration that publishes anything over https for this node (including one an admin wrote by hand) counts as published and is never overwritten.
- Whether the tailnet can issue https certificates is read from the node's status. If not, nothing is written and the answer is "HTTPS is off for your tailnet (open https://login.tailscale.com/admin/dns, press Enable HTTPS under HTTPS Certificates, then press this again), so no editor could connect".
- Publish (the wizard's tailnet button, and the watchdog's repair), refusals in order: "the bundled Tailscale node did not answer"; "the node is <state>, not Running"; https off (above); "could not read the node's Serve settings"; a write refused by Tailscale ("Tailscale says Serve is not turned on for your tailnet (...). Open the link in that message once, then press this again", or Tailscale's own text up to 300 characters); "the node has no name on the tailnet yet". On success logs a warning "published this dashboard at https://<name> through Serve" and, only if the site has no dashboard URL yet, stores `https://<name>` as the site's dashboard URL (a failure there is only logged).
- **Watchdog**: run once per collector cycle, but acts at most once per 60 seconds. If there is no node, or it is not running or has no name, it does nothing. If Serve is missing for a running node, it publishes again and logs "Serve was missing and has been put back" (or an error "Serve is missing and could not be restored: ..."). The last repair attempt (time, success, detail) is remembered for display. Never raises.
- **Key expiry**: the node's key expiry date is read (none for a node whose key does not expire). The warning window is 14 days.
- A snapshot for the self-diagnosis alerts: node state ("unreachable" if it does not answer), name, key expiry, and whether Serve is in place (unknown when not readable, which must be treated as "not checked").

## How a companion's report arrived: https, local http or public http (source: netclass.py)

- For each report, the dashboard records whether it arrived over https, plain http on a private network, or plain http from the public internet. Only a change is written (by the database layer); nothing is shown or refused here.
- The scheme is the connection's own, or `X-Forwarded-Proto` (http or https only) from a trusted proxy. The host is the `Host` header the companion sent; a host containing `/ ? # @` or a space, or a missing host, records nothing.
- Classification of a plain-http host: loopback (`localhost`, `*.localhost`, loopback addresses) counts as local; a single all-digit, hex (`0x..`) or octal label is read as an IPv4 address; private, link-local, loopback and 100.64.0.0/10 addresses are local, globally routable non-multicast addresses are public; a name with no dot, or ending `.ts.net`, `.local`, `.lan`, `.internal`, `.home.arpa`, is local; reserved names (`.test`, `.example`, `.invalid`, `.localhost`, `example.com/net/org`) are local; any other name is looked up in DNS and is public only if every address it resolves to is public.
- DNS lookups: at most 4 at once, 1 second each; a lookup that times out, cannot start or fails counts as local and is not remembered. Answers are remembered for 300 seconds, at most 256 names (expired entries dropped first, then the soonest to expire).
- Never raises; anything unclassifiable records nothing.

## Vendor defaults for the appliance build (source: vendor_defaults.py)

- `DASH_VENDOR_DEFAULTS=1` (exactly `1`) turns on two built-in defaults:
  - the release feed URL `https://github.com/The-Creators-Club/ccsync-releases/releases/download/ccsync-releases-v1/channel.json`;
  - the vendor's release public key `GKNmk8MktRkGkrBv+ziF7O6ZNKCnjXfC9/TwDiYwKDY=`.
- A default applies only when the variable (`DASH_RELEASE_FEED_URL` or `DASH_RELEASE_PUBKEYS`) is ABSENT from the environment. A variable that is present but empty means "none" and is respected.
- "Holds only vendor keys" (true when every configured key is the vendor's) lets other pages say the private half of the key is the vendor's, not something this site must back up.

## Locked vendor build versus the studio's own build (source: build_flavor.py)

- The command-line AI tools (Claude Code, Codex), their setup wizard and subscription sign-in, their automatic update and the command-line-only triage agent are hard-disabled unless the process environment has `DASH_STUDIO_CLI_PROVIDERS=1`.
- Locked means the feature switches `ai_cli_providers` and `ai_cli_auto_update` read as off whatever is stored or set in `DASH_SITE_*`.
- Message shown where such a feature would be: "Claude Code and Codex are not available in this build. Use an API key (Claude API, OpenAI or DeepSeek)."
- At boot, a locked build whose site has `features.ai_cli_providers=1` stored logs a warning (see "Process start-up").

## Version (source: __init__.py)

- The dashboard version is `0.7.80`. An older dashboard's record of ignored report sections is forgotten when a different version boots.

## The site.toml file every server script reads (source: site.example.toml, read by server/common.py, server/install_dashboard_app.py and server/backends)

- The operator copies `site.example.toml` to `site.toml`. Search order for the file: `--site <path>`, then `$CCSYNC_SITE`, then `<repo>/site.toml`. A missing key reads as blank (or the reader's default); booleans accept `1/true/yes/on` and `0/false/no/off`, anything else is the default. The file holds no secrets: the NAS password, API keys and tokens stay in the deploying shell's environment.
- The dashboard itself does not read this file at run time. It reaches the dashboard in two ways: the deploy script turns keys into `DASH_*` environment variables, and an admin can paste it into Settings > Import (see "Export and import as site.toml text", which takes only the keys the dashboard stores).
- Every key the example offers, with the reader confirmed in code (purposes are as far as the reader's name and these files show; the full behaviour belongs to the server-scripts section):
  - `[nas]` `kind` (default `truenas`; also import), `host`, `admin_user`, `verify_ssl` (unset means pin on first use; `sha256:<hex>`, a CA bundle path, `1`, or `0`), `ssh_hostkey` (also published to editors as the SFTP host key unless `[security] skip_lane_host_key_pin`), `ssh_port`: read by server/common.py and install_dashboard_app.py.
  - `[tree]` `pool_root`, `tree_name` (also import), `dataset`, `projects_dir` (server scripts use it as the projects folder name, default `Projects`; the dashboard refuses to import any other value), `template_folders` and `shared_assets` (lists; also import), `homes_parent`, `share_name`, `smb_unc` (also import): read by server/common.py, install_dashboard_app.py, backends.
  - `[apps]` `root`, `dataset`: read by server/common.py and install_dashboard_app.py.
  - `[net]` `dashboard_url` (also import), `bind_lan`, `bind_tailnet`, `sftp_port` (also import), `sftp_chunk_size`, `sftp_concurrency` (both commented out in the example; also import), `sftp_host` (also import), `rclone_remote` (also import), `shell_type` (also import), `trusted_proxies`, `docker_bridge_cidr`: read by server scripts.
  - `[syncthing]` `gui_url`, `gui_bind`, `device_id` (also import): read by server scripts.
  - `[site]` `org_name`, `org_short`, `support_contact`, `product_name`, `brand_logo`, `canonical_prefix`: read by install_dashboard_app.py; all six also import.
  - `[releases]` `feed_url`, `policy` (`manual`/`stage`/`current`): read by install_dashboard_app.py.
  - `[broll]` `default_collection`, `default_collection_label`, `creators_shares`, `archive_creators_dir`: read by install_dashboard_app.py.
  - `[features]` `youtube_download`, `youtube_unblock`, `ai_cli_providers`, `auto_update`: read by install_dashboard_app.py (projected to `DASH_SITE_*`) and by import. `ai_cli_auto_update`: read only by the dashboard's import (see "Claims the code does not back").
  - `[stack]` `uid` (default 3000), `gid` (default 3001), `owner`, `group`, `private_gid` (default the uid), `editor_shell`, `project_acl`, `mode`, `image`: read by install_dashboard_app.py and backends/truenas.py.
  - `[timeline_cards]` `enabled`, `src`, `vault_host`, `vault_gid`, `root`, `media_host`, `media_map`, `db_host`, `db_name`, `db_write_allow`, `db_backups`, `project`, `server_url`, `editor`: read by install_dashboard_app.py.
  - `[footage_sorter]` `enabled`, `src`, `pool_host`, `source_roots` (list), `dest_root`, `legacy_id_roots` (table), `vault_root`, `pool_gid`, `cloud_state`, `backup_out`, `backup_out_owner`, `timezone`: read by install_dashboard_app.py.
  - `[security]` `shared_report_token` (projected to `DASH_SHARED_REPORT_TOKEN_ENABLED`), `allow_nas_password_in_container`, `allow_nas_admin_as_dashboard_admin`, `skip_lane_host_key_pin`: read by server/common.py and install_dashboard_app.py.
- Keys the server scripts read that the example does NOT offer: `[studio] allow_cli_providers` (projected to `DASH_STUDIO_CLI_PROVIDERS`, the switch that unlocks the command-line AI tools), `[nas] ssh_key_probe`, `[net] smb_host`, `[net] tailnet_name`, `[tree] snapshot_dir`, `[tree] snapshot_projects_subpath`, `[stack] project_server`.
- Dashboard import also accepts `[android] package_name, sha256_cert_fingerprints`, `[indexer] model_tier` and `[telemetry] resolve_project, local_manifest, media_tree, input_idle`, none of which the example offers.

## Looks redundant or overlapping

- Two OIDC-related admin notions: the admin claim (`DASH_OIDC_ADMIN_CLAIM`/`VALUES`) only lets a person past the membership check, while every real admin check reads `DASH_ADMIN_USERS`. The setup task even has to explain that the claim makes nobody an admin.
- Three sign-in methods (smb, oidc, local) plus break-glass password login under oidc, each with its own boot checks and setup-task wording.
- Site identity lives in three places that override each other: `DASH_SITE_*` environment, the stored site settings (seeded once from the environment, then authoritative), and the appliance overlay file; plus `site.toml` turned into environment by the deploy and also importable on Settings.
- The NAS settings exist under two names each (`DASH_NAS_*` and `TRUENAS_*`), kept in step.
- Feature switches exist as `DASH_SITE_*` environment, stored rows, `site.toml [features]`, and a build lock on top for two of them.
- Settings page routes (`PUT/import/undo /api/v1/admin/site`) and the wizard's per-task forms (`/api/v1/setup/config/*`) are two separate configuration-writing paths with different storage (database rows vs a JSON file plus restart).
- Alerts destination can be set in the wizard (`/api/v1/setup/alerts`, with its own test route) and on Settings > ALERTS.
- The tailnet "is it reachable" logic is computed both by the wizard task and the tailnet watchdog/snapshot used by alerts.
- The release-key setup task duplicates the protection panel's release-key line (both read the same setting).
- Collector watchdog plus code-update boot watchdog plus a start-up deadline: three separate self-restart mechanisms.
- The old Cards page, the new Cards editor, and the Cards agent tunnel to a separate Cards server are three ways of serving Timeline Cards, each with its own settings and gate carve-outs.
- `DASH_REPORT_TOKEN_OPTIONAL` exists only to be ignored unless `DASH_DEV_INSECURE` is also set.

## Claims the code does not back

- The `admin` setup task's description says "A local account for you. No NAS credential is involved.", but on `smb` the task is satisfied by NAS account names in `DASH_ADMIN_USERS`.
- setup_engine and setup_routes refer to an "identity module" (`identity.py`, "WP C") that reports local-account status; no such module exists, so that branch never runs and the local-accounts table answers instead.
- Comments in auth.py and settings.py say a deployment with no `DASH_SESSION_SECRET` "has login switched off entirely". In these files, an empty secret makes every session unreadable, so every gated path refuses or redirects to `/login`; nothing here switches the gate off. (Whatever the sign-in page does in that case is outside this part.)
- settings.py's dataclass comment says the shared fleet token is accepted "today because every deployed companion holds only the shared token"; the shipped reading of the environment makes UNSET mean OFF.
- The app.py comment on the CSRF exemption for `/api/v1/setup/admin` says later calls are "a clean 409"; true only on `local`; on other methods every call is a 403.
- `site.example.toml [features] ai_cli_auto_update` is presented like the other feature switches, but the deploy does not project it to `DASH_SITE_AI_CLI_AUTO_UPDATE`; it takes effect only if the file is pasted into Settings > Import.
- The local-accounts "must change password" flag can be set but nothing in the dashboard code reads it.
- tailscale_local.py says it is read only and the sign-in drive "lands here when that package does"; the write paths actually live in setup_engine.py (login) and tailnet_serve.py (Serve).
- appliance_config's `DASH_NAS_KIND` check compares case-sensitively ("TrueNAS" is refused), unlike every other NAS-kind reader.

## Could not determine

- What the sign-in page (`/login`, `/api/v1/login`, `/api/v1/verify`, logout, `/login?local=1`, `/login?renew=1`) shows and enforces: it lives in ui.py and api.py, outside this part. Only the shared rules it calls (throttle, plaintext refusal, oidc break-glass, removed-person refusal) are described here.
- The 14-day session warning banner (`SESSION_WARN_DAYS = 14` in auth.py) is defined here but its use is outside this part.
- The exact SFTP window rule (`sftp_transport`), the Syncthing admin-page guard, the code-update watchdogs, the crash reporter, the collector's task bodies and the mounted apps' own gates are outside this part.
- Whether `DASH_SITE_PROJECTS_DIR` is ever set by any deploy (none found); the boot refusal it guards may be reachable only by hand.
- How the alerts module validates a webhook or email beyond the checks quoted here.
