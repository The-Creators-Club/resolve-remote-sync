# security - auth/session gates, fleet-credential binding, traversal, secret leakage, fail-closed, the /help audience gate

Files read (with approximate coverage):
- `dashboard/src/ccsync_dashboard/published_docs.py` (100%), `help.py` (100%),
  `ui.py` help routes + `_help_response` (100% of the help half), `app.py`
  `login_gate` / `csrf_gate` / `body_size_gate` and every carve-out regex
  (100%), `auth.py` cookie + identity token surface (skim), `api.py`
  `resolve_companion_credential`, `_account_refusal`,
  `_refuse_barred_account`, `_require_fleet_caller`, `_require_jobs_reader`,
  `api_verify`, `api_download_package` (100% of those), `site_store.py`
  masking (`_looks_secret`, `_display`, `mask_changes`), `cards.py` gate,
  `cards_tunnel.py` (diff), `secrets_boot.py` (diff), `provision.py` (diff),
  `music.py` / `broll.py` / `ytdl.py` mount gates (stamp + strip paths).
- `music/web/musicweb/fleet_auth.py` (100%), `config.py` login-gate half,
  `identity.py` header; `broll/web/app/fleet_auth.py` (trust switch),
  `routes_fleet.py` (diff), `routes_share.py` + `main.py` `ShareAssets`,
  `client_folders.py` (diff); `ytdl/web/ytdlweb/routes_fleet.py` (diff).
- `companion/src/ccsync_companion/loopback_guard.py` (100%),
  `broll_server.py` / `music_server.py` (diff only),
  `sync/syncthing_admin.py` + `sync/syncthing_lane.py` HTTP helpers.
- `git diff 40f931a..HEAD` filtered to auth/session/token/help/share/guard
  files; `KNOWN_BUGS.md` greps for CR-55, CR-86, DCORE-4, dash-api-6.

Tests run:
- `dashboard/.venv/Scripts/python.exe <scratch>/probe_help.py` -> the /help
  audience gate and 12 traversal shapes, as a non-admin session. Result
  below in security-0 (no finding).
- `dashboard/.venv/Scripts/python.exe <scratch>/gate.py` + `gate2.py` -> every
  `/admin*` and `/partials/admin*` route (127 of them) driven with a
  non-admin `jsmith` session and valid bodies. Result: all 401/403/404, no
  admin route reachable. No finding.
- `dashboard/.venv/Scripts/python.exe <scratch>/routes.py` -> the 236-route
  inventory used to pick targets (the app's routers are `_IncludedRouter`
  objects, so `app.routes` has to be walked through `.original_router`).
- No pytest suite run (another territory owns those files).

## Findings

### security-1 - the dash-api-6 "suspended means the same everywhere" gate stops at api.py; the three mounted fleet APIs and the package door never ask
- Severity: medium
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/api.py:229` (`_refuse_barred_account`,
  called at 2324, 2393, 9508, 9930 only), versus
  `broll/web/app/routes_fleet.py:131` (claim),
  `music/web/musicweb/routes_fleet.py` (claim/heartbeat/release/item posts),
  `ytdl/web/ytdlweb/routes_fleet.py:456` (claim) and
  `dashboard/src/ccsync_dashboard/api.py:6444` (`api_download_package`).
- What: this afternoon's dash-api-6 fix says in its own docstring that
  suspension "meant one door only: /report ... One line per gate makes the
  word mean the same thing everywhere". It added the line to four api.py
  doors (selection read, selection write, `/api/v1/diagnostics`, and
  `_require_fleet_caller`, which covers the fleet jobs and the Cards tunnel).
  It did NOT add it to the three mounted apps' fleet routes, which cannot
  reach it: `broll/web`, `music/web` and `ytdl/web` verify a fleet token plus
  a signed identity and have no notion of a suspended account at all (`grep
  -rn "_account_refusal\|suspended" broll/web/app music/web/musicweb
  ytdl/web/ytdlweb` -> no hits). The dashboard-side gates that COULD ask -
  `BrollGate._fleet_stamp`, `MusicGate._fleet_stamp`, ytdl's equivalent, and
  `login_gate`'s `_companion_token_ok` - resolve the credential with
  `api.resolve_companion_credential` and stop there.
- Failure scenario: an admin suspends a freelancer on Settings -> Users.
  DCORE-4 revokes neither their session nor their `cce1.` token and the
  identity token never expires (CR-86), so their laptop's companion keeps a
  working credential. `/report` and the sync plan now 403. But the same
  machine can still `POST /broll/api/fleet/ingest/batches/<uid>/claim` and
  push indexed clips, `POST /music/api/fleet/ingest/batches/<uid>/claim` and
  run `INSERT INTO tracks` plus a whole-library re-score, claim a ytdl job
  and download into the shared tree, and `GET
  /api/v1/companion/package/<platform>/current` to keep itself upgraded. Two
  of those three are exactly the "writes into the shared vault" the fix's own
  comment gives as the reason for adding the gate to the job routes.
- Evidence: the greps above; `_refuse_barred_account` has exactly four call
  sites, all in api.py; the mount gates' `_fleet_stamp` bodies
  (`dashboard/src/ccsync_dashboard/music.py:172-207`, and broll/ytdl's
  identical shape) call `resolve_companion_credential` and return a stamp
  with no account check.
- Ledger: CR-nn (dash-api-6, this afternoon's fix pass) does not fix
  dash-api-6 for the mounted apps; new for the package door.
- Suggested fix: check the account in the ONE place all four mounts already
  share - the three `_fleet_stamp` helpers and `login_gate`'s
  `_companion_token_ok` - so a barred editor's token resolves to `AUTH_NONE`
  (or no stamp) before the sub-app ever sees it; add the line to
  `_require_package_read` as well.

### security-2 - the login-gate carve-out for `GET /broll/api/fleet/ingest/batches` outlived the route it was written for
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/app.py:1075` and `:1177`
  (`_broll_fleet_list_re`), versus `broll/web/app/routes_fleet.py` (the
  `discover` route deleted in the same afternoon, finding broll-3).
- What: broll-3 removed `GET /api/fleet/ingest/batches` from the b-roll app
  because nothing called it. The other half of that wire - the middleware
  carve-out that let a bare fleet token skip `login_gate` for that exact path
  - was left in place. It is a half-landed fix in the direction the brief
  warns about (one side changed, not the other).
- Failure scenario: today it is only dead code: the request skips the login
  gate, reaches BrollGate, and the sub-app 404s it. The hazard is that the
  carve-out now names a path with NO route behind it, so the next person who
  adds any route at `/broll/api/fleet/ingest/batches` gets a
  session-gate bypass for free and nothing in the diff will say so.
- Evidence: `grep -n "_broll_fleet_list_re"
  dashboard/src/ccsync_dashboard/app.py` -> still present at 1075/1177;
  `grep -rn "fleet/ingest/batches" companion/src/ccsync_companion/` -> no
  caller anywhere in the companion.
- Ledger: new (the other side of broll-3).
- Suggested fix: delete `_broll_fleet_list_re` and its `or (...)` clause in
  the same change that removed the route, or restore the route.

### security-3 - musicweb believes `X-CCSync-Fleet-Auth` on an ENVIRONMENT VARIABLE, which its own comment says it does not
- Severity: low
- Confidence: CONFIRMED
- Where: `music/web/musicweb/config.py:206-219` (comment vs. line 209),
  read by `music/web/musicweb/fleet_auth.py:74` (`gate_stamp` ->
  `require_fleet_token` -> `require_fleet_caller`).
- What: the comment above the flag reads "It is NOT inferred from the
  environment: a host that merely has the variable set is not the same as a
  process that actually has the middleware wrapped around it" - and the very
  next line is `_LOGIN_GATED = os.environ.get('MUSIC_LOGIN_GATED','') == '1'`.
  b-roll and ytdl get this right: their `_trust_stamp = False` can only be
  turned on by a call from the mount (`broll/web/app/fleet_auth.py:90`,
  `ytdl/web/ytdlweb/routes_fleet.py:99`), with no environment hatch. Music is
  the odd one out, and the stamp is the credential that SKIPS the fleet-token
  comparison entirely (`require_fleet_token` returns on `kind == 'editor'`
  before `token_ok` is ever reached).
- Failure scenario: a standalone `uvicorn musicweb.main:app` behind any
  reverse proxy, with the documented `MUSIC_LOGIN_GATED=1` escape hatch
  (`music/web/DEPLOY.md:99`) and a proxy that does not strip the header. A
  caller sends `X-CCSync-Fleet-Auth: editor:jsmith` and the fleet-token check
  is skipped outright - DASH_REPORT_TOKEN stops being required for
  `/api/fleet/ingest/*`. The remaining barrier is `require_identity`, which
  does fail closed (no `DASH_SESSION_SECRET`, no bad signature), so this is
  one of two credentials lost rather than an open door - hence low, not high.
- Evidence: the three files side by side; `grep -rn "MUSIC_LOGIN_GATED"` ->
  exactly two hits, the config line and the DEPLOY.md hatch.
- Suggested fix: drop the environment initialiser and make it
  `_LOGIN_GATED = False`, set only by `config.set_login_gated(True)` from
  `dashboard/src/ccsync_dashboard/music.py:426` - i.e. the shape b-roll and
  ytdl already use. If the hatch must stay, split it: a separate
  `MUSIC_TRUST_GATE_STAMP` so "a login gate wraps me" and "believe a header
  somebody else could have set" are not one flag.

### security-4 - the companion's Syncthing helpers follow redirects while carrying `X-API-Key`
- Severity: low
- Confidence: CONFIRMED
- Where: `companion/src/ccsync_companion/sync/syncthing_admin.py:269`
  (`http_request`) and `companion/src/ccsync_companion/sync/syncthing_lane.py:178`
  (`default_http_get`).
- What: both build a `urllib.request.Request` with the Syncthing API key in a
  header and hand it to the bare `urllib.request.urlopen`, which follows 3xx
  by default and RE-SENDS the header to the redirect target. Every other
  outbound caller in this product installs a no-redirect opener for exactly
  this reason - `upgrade.py:800`, `release_feed.py:158`,
  `dashboard_update.py:345`, `alerts.py:3538`, `ai_providers.py:1150`,
  `cards_tunnel.py:89`, and the dashboard's own `syncthing_client.py:129`
  (`allow_redirects=False`). These two are the only ones left.
- Failure scenario: `base_url` defaults to `http://127.0.0.1:8384`, so in the
  shipped configuration the peer is local and benign. A site that points a
  companion at a Syncthing GUI on another host (the constructor takes
  `base_url`) over plain http, or anything that can answer on that port
  first, gets the machine's Syncthing API key posted to a location of its
  choosing with one 302. The key is lane C's full admin credential.
- Evidence: read both call sites; compared against the seven no-redirect
  openers listed above.
- Ledger: new. CLAUDE.md states the no-redirect rule for the dashboard; these
  are its companion-side counterparts and were missed.
- Suggested fix: give both helpers the same `build_opener(NoRedirectHandler)`
  the companion's `upgrade.py` already defines, and reject a non-loopback
  `base_url` over http.

## Coverage note

What I verified and found CLEAN, so nobody re-hunts it:

- **The /help audience gate landed this afternoon works.** As a non-admin
  session, `/help/KNOWN_BUGS.md`, `/help/_root/KNOWN_BUGS.md`,
  `/help/SECRETS.md` and nine traversal shapes (`legal/../SECRETS.md`,
  `..%2f`, `%2e%2e/`, `legal/./../GOTCHAS.md`, `//SECRETS.md`,
  `legal/subdir/../../SECRETS.md`, case-varied `LEGAL/../`) all answer 404
  with the NOT_FOUND sentence; `HOW_IT_WORKS.md` and `legal/EULA.md` answer
  200. The index rendered for that editor lists exactly the seven published
  documents and nothing else. `is_published` normalises before matching and
  fails closed; `resolve_document` re-checks shape independently and its
  `..`/`:`/NUL/realpath rules run after the audience check, so the two cannot
  disagree in the permissive direction. The `_root/` branch is allow-listed
  to four names and admin-only.
- **Admin authorization.** All 127 `/admin*` and `/partials/admin*` routes
  answer 403 `admins only` to a non-admin session, including the 16 that at
  first look reachable because FastAPI validates the body before the
  endpoint's gate runs (they 422 on an empty body, 403 on a valid one).
- **CSRF.** `/broll/`, `/music/` and `/ytdl/` are exempt wholesale, including
  their session-authorised SPA routes, with no origin check (unlike
  `/cards/`). This is defended in depth by `SameSite=Lax` on the session
  cookie (`auth.py:673`) and is documented at `app.py:144`, so I am not
  filing it - but it is the single largest standing CSRF exposure and it
  rests on one cookie attribute.
- **Secret leakage.** `site_store._looks_secret` / `_display` /
  `mask_changes` mask the import-diff and undo responses; no log statement in
  dashboard, broll, music, ytdl or companion formats a token, key or password
  value (only names, ids and "missing or invalid"). `cards_tunnel` strips the
  caller's `token` from the body before forwarding.
- **The client-share prefix.** `ShareAssets` narrows StaticFiles to a
  seven-name frozenset; `PUBLIC_VIDEO_COLUMNS` is an allow-list; membership
  is re-checked per request through `_live_folder`.
- **Fleet-credential binding (CR-55 shape).** All four verifiers now bind the
  `cce1.` token's editor to the signed identity and refuse a mismatch:
  `api._require_fleet_caller`, `broll/web/app/fleet_auth.require_fleet_caller`,
  `ytdl/web/ytdlweb/routes_fleet.require_fleet_caller`, and music's new
  `require_fleet_caller` (this afternoon's work, correct). The three mount
  gates strip every inbound `X-CCSync-Fleet-Auth` / `X-CCSync-User` /
  `X-CCSync-Admin` on EVERY request, not only the ones that read them.
- **CORS on 8899.** `loopback_guard` is exact-match origin, Host-header
  rebinding defence, json-only POST bodies, single-segment `share`
  validation, realpath containment. No change since 40f931a weakened it.
- **Redirect following** on the dashboard: no call follows one except
  `release_feed`'s documented https-only vendor-feed carve-out.

What I did NOT get to: the setup wizard's anonymous first-run window
(`setup_routes.require_setup_access`) beyond reading its docstring; the OIDC
callback's state/nonce handling; `internal_sftp`'s bearer token; the Android
`assetlinks.json` route; `cli_tools`' pty sign-in and the checksum condition;
and live proof of security-1 against the mounted b-roll/music apps (it is a
code-and-grep confirmation, not a TestClient one, because standing the three
mounts up with a suspended editor needs a seeded dashboard DB I judged too
slow for the time-box). The suites do not cover any of security-1's four
doors with a suspended account, and nothing anywhere tests that the mount
gates refuse a barred editor.

## OUT OF TERRITORY

- (none - this lens owns no files, and everything above is inside it.)
