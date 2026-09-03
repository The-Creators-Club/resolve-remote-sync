# dash-core — login gate, sessions/CSRF, OIDC, boot secrets, site store, setup wizard, NAS seam

Files read (with approximate coverage):
- `dashboard/src/ccsync_dashboard/auth.py` (912 lines, 100%)
- `dashboard/src/ccsync_dashboard/sessions.py` (431, 100%)
- `dashboard/src/ccsync_dashboard/oidc.py` (468, 100%)
- `dashboard/src/ccsync_dashboard/app.py` (lines 40–180, 470–520, 730–1130 — the
  open list, CSRF/body/login middleware, boot checks; ~55%)
- `dashboard/src/ccsync_dashboard/site_store.py` (902, ~95%)
- `dashboard/src/ccsync_dashboard/secrets_boot.py` (271, 100%)
- `dashboard/src/ccsync_dashboard/settings.py` (`__post_init__`, `from_env`, the
  dev-insecure and normalisation blocks; ~40%)
- `dashboard/src/ccsync_dashboard/setup_routes.py` (383, 100%),
  `setup_api.py` (105, 100%), `setup_engine.py` (~60%: registry, run_check/do_it/skip,
  eula, admin, studio, storage, secrets, syncthing)
- `dashboard/src/ccsync_dashboard/ui.py` (`_render`, `_safe_next`, `_login_context`,
  `page_login`, `page_login_submit`, `page_logout*`, `page_setup`; ~15%)
- `dashboard/src/ccsync_dashboard/runtime_id.py`, `tailscale_local.py`,
  `truenas_client.py` (100% each)
- `dashboard/src/ccsync_dashboard/nas/base.py`, `factory.py` (100%),
  `synology.py` (~45%: the SSH half, quoting, refusals), `nas/truenas.py` (~35%)
- `dashboard/tests/test_no_em_dash.py` (100%), skim of test_auth/test_oidc/test_setup_routes
- `CLAUDE.md`, `site.example.toml`, `KNOWN_BUGS.md` (grepped), `docs/bug-hunt-2026-08-21.md`
  (the dash-core/dash-admin sections)

Tests run:
- `dashboard\.venv\Scripts\python.exe -m pytest tests/test_auth.py tests/test_oidc.py
  tests/test_hardening.py tests/test_setup_engine.py tests/test_site.py
  tests/test_nas_backend.py tests/test_local_auth_mode.py -q` -> **241 passed**
- `... -m pytest tests/test_no_em_dash.py tests/test_setup_routes.py tests/test_sessions.py -q`
  -> **181 passed**
- ad-hoc snippets from the dashboard venv (see Evidence below)

## Findings

### dash-core-1 — `DASH_AUTH_METHOD` with different case or a stray newline silently refuses every login, and boot says nothing
- Severity: medium
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/auth.py:139` and `:157` (`verify_credentials`),
  against `auth.py:707` (`check_boot_secrets`), `auth.py:790` (`describe_auth`),
  `setup_api.py:37` (`_auth_method`), `setup_routes.py:71`, `ui.py:295`/`364`
- What: every consumer of `settings.auth_method` normalises it with
  `.strip().lower()` — except `verify_credentials`, which compares the raw value
  (`if settings.auth_method in ("smb", "oidc")` / `== "local"`). `Settings.from_env`
  stores `env.get("DASH_AUTH_METHOD", "smb")` verbatim, no strip, no lower. So
  `DASH_AUTH_METHOD=SMB` (or `local\n`, which a compose/`.env` heredoc or a
  Windows-edited env file produces) falls through to the final
  `log.error("unknown DASH_AUTH_METHOD ... rejecting all logins")` and returns
  False for every credential, while `check_boot_secrets` (which lowercases) finds
  no problem and boots, and `describe_auth` logs the *normalised* name — so the
  boot log claims `auth method=smb` on a dashboard where no password can ever be
  right.
- Failure scenario: an operator sets `DASH_AUTH_METHOD=Local` on an appliance.
  `setup_api.setup_admin` (`_auth_method` lowercases) happily creates the first
  local admin and mints their session; the moment that session expires, `/login`
  refuses them forever with the generic "sign-in refused" message, and the only
  clue is one ERROR line in the container log contradicted by the INFO line above
  it. Nothing on the Settings page, the setup wizard or `/api/v1/health` says why.
- Evidence:
  ```
  >>> s = Settings.from_env({'DASH_AUTH_METHOD':'SMB','DASH_SESSION_SECRET':'x'*40,'DASH_SMB_HOST':'nas'})
  auth_method repr: 'SMB'
  boot problems: ['DASH_SESSION_SECRET has too little variety to be a random secret']   # nothing about the method
  describe:  auth method=smb; session cookie: Secure ...
  verify:    False                       # log: unknown DASH_AUTH_METHOD 'SMB' -- rejecting all logins
  >>> Settings.from_env({'DASH_AUTH_METHOD':'local\n', ...}) -> verify False, boot []
  ```
- Ledger: new (`grep -n DASH_AUTH_METHOD KNOWN_BUGS.md` -> only lines 575 and 2099,
  neither this)
- Suggested fix: normalise once in `Settings.__post_init__`
  (`object.__setattr__(self, "auth_method", str(self.auth_method or "smb").strip().lower())`)
  and add an unknown-method entry to `check_boot_secrets` so a typo refuses to
  start rather than refusing every login.

### dash-core-2 — the OIDC (and TrueNAS) HTTP calls follow redirects, against the codebase's own stated rule
- Severity: medium
- Confidence: CONFIRMED (the code path; the exfiltration is the worst case, not observed)
- Where: `dashboard/src/ccsync_dashboard/oidc.py:127` (`_http_get_json`) and
  `oidc.py:135` (`_http_post_form`); same shape at
  `dashboard/src/ccsync_dashboard/nas/truenas.py:122` (`_request`)
- What: CLAUDE.md states the invariant "No dashboard call follows a redirect"
  with exactly one carve-out (`release_feed.py`'s vendor-feed fetch), and five
  modules implement it with an explicit `_NoRedirect` opener
  (`ai_providers.py:1048`, `alerts.py:1806`, `cards_tunnel.py:89`,
  `dashboard_update.py:345`, `release_feed.py:158`). `oidc.py` uses plain
  `requests.get` / `requests.post` with `allow_redirects` left at its default
  `True`, and so does the TrueNAS client's `session.request`. The token-endpoint
  POST carries the client secret — as Basic auth, or, when the IdP does not
  advertise `client_secret_basic`, **in the form body** (`_exchange`,
  `oidc.py:397`). `requests` strips `Authorization` across a host change but
  never strips a body: a 307/308 from the token endpoint replays
  `client_secret=` to wherever it points.
- Failure scenario: an IdP (or anything that can answer for its token endpoint —
  a stale DNS entry, a compromised reverse proxy in front of Keycloak) answers
  the token POST with `308 Location: https://attacker/`. `requests` re-sends the
  same form, including `client_secret`, to the attacker. Nothing in the dashboard
  logs the hop. The discovery GET has the same property, though the issuer check
  in `Discovery.get` limits what a redirected document can claim.
- Evidence: `grep -rn "allow_redirects\|_NoRedirect" dashboard/src/ccsync_dashboard`
  returns the five `_NoRedirect` classes and no `allow_redirects` anywhere; both
  oidc helpers and `nas/truenas.py:_request` are plain `requests` calls.
- Ledger: new (the invariant is in CLAUDE.md; `release_feed.py`'s comment says
  explicitly it "is not precedent")
- Suggested fix: pass `allow_redirects=False` on both oidc helpers (and on the
  NAS client's `session.request`), turning a 3xx into an `OidcError`/`TrueNASError`
  that names the Location, as the other five modules already do.

### dash-core-3 — `template_folders` / `shared_asset_folders` accept `..` segments, and setup's storage task mkdir's them relative to the tree root
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/site_store.py:220` (`_validate_csv`),
  consumed at `dashboard/src/ccsync_dashboard/setup_engine.py:597`
  (`_run_storage`: `target = tree_root / rel; target.mkdir(parents=True, exist_ok=True)`)
- What: `_validate_csv` only refuses control characters. Its sibling
  `_validate_canonical_prefix` explicitly rejects `..` (`site_store.py:174`), so
  the intent to reject traversal exists in this module and is not applied to the
  two list keys. `provision.shared_asset_folders_for` strips leading `/` (so an
  absolute path is neutralised) but leaves `..` intact.
- Failure scenario: an admin saves `shared_assets = ["../../etc/ccsync"]` on
  Settings, or pastes a site.toml containing it into Settings -> Import (which is
  presented as a "paste this file" operation, i.e. a value that may have come from
  elsewhere). `POST /api/v1/setup/tasks/storage/run` then creates
  `<tree_root>/../../etc/ccsync` — outside the tree — and the same rel is what the
  collector hands Syncthing as a shared folder path.
- Evidence:
  ```
  >>> site_store.validate('shared_asset_folders','../../etc/ccsync, /tmp/x')
  '../../etc/ccsync,/tmp/x'
  >>> provision.shared_asset_folders_for(['../../etc/ccsync'])
  [('etc-ccsync', '../../etc/ccsync', '../../etc/ccsync')]
  >>> site_store.validate('canonical_prefix','/mnt/../etc')   # refused
  ```
- Ledger: new (dash-admin-7 in the 2026-08-21 hunt fixed `nas_kind`'s validator
  but did not revisit the csv one)
- Suggested fix: in `_validate_csv`, refuse any item whose `/`- or `\`-split parts
  contain `..`, and refuse a leading `/` or a drive letter, for the two path-list
  keys.

## Coverage note

What I checked and did **not** find a defect in, so a later hunter need not
re-do it:

- **Exemption widening in `login_gate`.** Proved by construction with Starlette
  1.6.0 that the router performs no dot-segment normalisation, so a path that
  satisfies `path.startswith("/broll/share/")` cannot then route to
  `/broll/api/...`:
  `'/broll/share/../api/x'`, `'/broll/share/..//api/x'`, `'/broll/share//../api/x'`,
  `'/broll/share/./../api/x'` all reach the mount and 404; only the literal
  `/broll/api/x` reaches the route, and it is gated. Uvicorn percent-decodes
  `scope["path"]` before both the gate and the router, so an encoded `%2e%2e` or
  `%2f` behaves identically. Case and trailing dots do not help either: Starlette
  route regexes are exact, so any mutation moves *away* from a real route
  (fail-closed direction). The four fleet-token regexes are anchored `^...$` and
  per-suffix as their comments claim.
- **Sessions/CSRF.** Token purpose separation, the six-field nonce shape, the
  `compare_digest` TypeError guards, `sid` derivation under the secret that
  verified the cookie (DASH-2), revoke-then-delete on logout, and the
  `session_is_tracked` gate all read correctly. The CSRF exempt prefixes
  (`/broll/`, `/music/`, `/ytdl/`, `/api/v1/admin/packages/`) are only safe
  because the cookie is `SameSite=Lax`; that is documented, and it does hold.
- **OIDC.** state/nonce/PKCE-S256 in an HMAC-signed 10-minute cookie, asymmetric
  algs only, `aud`/`iss`/`exp`/`iat` required, discovery issuer mix-up check,
  fail-closed group allow-list, `require_fleet_member`, and `_safe_next`'s
  `//host` / `/\host` rejection are all correct. `redirect_uri` derived from
  `request.url.netloc` when `DASH_OIDC_REDIRECT_URL` is unset is bounded by the
  IdP's own registered-URI check; not reported.
- **Boot secrets.** `check_boot_secrets` reuses `broll.check_ingest_token` for
  the current and every retired key, refuses `DASH_COOKIE_SECURE=1` with no TLS
  path, and `DASH_DEV_INSECURE` is loud at boot (`app.py:491`), raises a
  `dev_insecure` notice (`notices.py:650`) and is the only bypass. No leak of a
  secret into `/api/v1/site`, a log line or an error body was found.
- **The setup wizard.** Every `/api/v1/setup/*` route calls
  `require_setup_access` first; `first_run_open` fails closed on `oidc` and on an
  unknown probe, and is only open under `local` with zero accounts;
  `setup_api.setup_admin` re-checks under `BEGIN IMMEDIATE` and enforces the
  12-character floor through `local_users.create_user` -> `auth.check_password`.
  It can be "re-run" only by deleting every local account, which is itself an
  admin action.
- **NAS backends.** Every interpolation into `_INSTALL_KEY_SCRIPT` and
  `_KEY_PROBE_SCRIPT` is `shlex.quote`d, the whole script is quoted again into
  `sudo -S -p '' /bin/sh -c ...`, and the sudo password goes on stdin, never argv.
  `nas.factory` refuses an unknown kind rather than defaulting to TrueNAS.
- **Em dashes.** `tests/test_no_em_dash.py` walks templates, static JS and the AST
  of every `src/ccsync_dashboard/*.py` string literal (f-string parts included,
  docstrings excluded) and passes. The `--` in HTTP `detail` strings is a spaced
  hyphen pair, not U+2014, and is not covered by the rule.

Not covered: `ui.py` beyond the auth/setup pages (~2 700 lines of grid/admin
render), `nas/truenas.py`'s user-creation half and `nas/synology.py`'s DSM API
half, `setup_engine`'s tailscale/software/done tasks, the live behaviour of an
IdP or a real DSM, and anything reachable only through `api.py` (other territory).
The suite has no test that drives a malformed `DASH_AUTH_METHOD` (finding 1), no
test that asserts an outbound call refuses a redirect for `oidc.py`/`nas`
(finding 2), and no test that a `..` in a site path list is refused (finding 3).

## OUT OF TERRITORY

- `dashboard/src/ccsync_dashboard/provision.py:186` — `shared_asset_folders_for`
  strips a leading `/` but keeps `..` segments; it is the shared normaliser for
  finding dash-core-3 and is probably where the fix belongs.
- `dashboard/src/ccsync_dashboard/nas/synology.py:884` — `int(home_mode[-2])`
  would `IndexError` on a one-character stat mode; a task's `run()` catches it
  into a "internal error" TaskState, so cosmetic, but it is an unguarded index on
  parsed remote output.
