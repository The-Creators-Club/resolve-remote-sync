# dash-core - dashboard boot, auth/session gate, setup wizard, NAS backends

Files read (with approximate coverage):
`dashboard/src/ccsync_dashboard/app.py` (full), `auth.py` (full), `sessions.py`
(full), `oidc.py` (full), `local_users.py` (full), `secrets_boot.py` (full),
`runtime_id.py` (full), `tailscale_local.py` (full), `internal_sftp.py` (full),
`setup_api.py` (full), `setup_routes.py` (~80%), `setup_engine.py` (~60%: the
diff since 097f5a3 in full, plus eula/admin/studio/storage/secrets/tasks),
`site_store.py` (~70%), `settings.py` (~40%: `__post_init__`, `from_env` auth
block, the SYS-20 block), `provision.py` (~50%), `nas/base.py`, `nas/factory.py`,
`nas/truenas.py` (request layer), `nas/synology.py` (~70%),
`syncthing_client.py` (request layer), `truenas_client.py` (shim).
Also: `git diff 097f5a3..HEAD` over all of the above,
`static/setup.js`, `KNOWN_BUGS.md` CR-111..CR-114, `docs/bug-hunt-2026-09-03.md`.

Tests run:
`cd dashboard; .venv\Scripts\python.exe -m pytest tests/test_auth.py tests/test_sessions.py tests/test_oidc.py tests/test_local_users.py tests/test_secrets_boot.py tests/test_setup_api.py tests/test_setup_routes.py tests/test_site_store.py tests/test_synology_client.py tests/test_nas_backend.py -q`
-> **288 passed** in 104 s.

## Findings

### dash-core-1 - the Synology backend still follows redirects, so a 307 replays the DSM admin password
- Severity: high
- Confidence: CONFIRMED (code); exploitability PLAUSIBLE (needs a 307/308 from whatever answers for `DASH_NAS_HOST`)
- Where: `dashboard/src/ccsync_dashboard/nas/synology.py:321-330` (`SynologyClient._http`), against `dashboard/src/ccsync_dashboard/nas/truenas.py:112-137` which does it right
- What: CR-111 (dash-core-2, fixed 2026-09-03) put `allow_redirects=False` + an explicit 3xx refusal on the OIDC token POST and on `TrueNASClient._request`, and CLAUDE.md states the invariant as "No dashboard call follows a redirect". The Synology backend was missed: `_http` calls `self.session.post(...)` / `.get(...)` with `requests`' default `allow_redirects=True` and no 3xx check anywhere above it (`_json` only rejects non-2xx *after* the redirect chain has already been walked). Every DSM credential this dashboard holds rides in a POST **body**: `_ensure_session` posts `passwd=<DASH_NAS_PW>` (the NAS admin password, by design "in the body, not a query string"), and `_request` puts `_sid` and `SynoToken` into the same body, as it does the new editor password in `set_known_password`. `requests` strips `Authorization` across a host change but never a form body, and a 307/308 preserves method and body verbatim.
- Failure scenario: DSM (or anything in front of it - a reverse proxy, a captive portal, a DNS-hijacked `DASH_NAS_HOST`, a DSM configured to force-redirect `:5000` to an external hostname) answers the login POST with `307 Location: https://elsewhere/`. `requests` re-POSTs `account=<admin>&passwd=<DASH_NAS_PW>&session=CCSync` to `elsewhere`. On TrueNAS the identical shape was judged a defect and fixed; here it is still live. The same applies to `set_known_password`, which would replay a freshly set editor password, and to every `_call`, which would replay a live `_sid` + `SynoToken`.
- Evidence: `grep -n "allow_redirects" nas/*.py oidc.py` returns hits only in `nas/truenas.py:124` and `oidc.py`; `synology.py:325/327` have none. `KNOWN_BUGS.md:10373` (CR-111) says "The OIDC token POST and **every TrueNAS request** refuse a 3xx" - the Synology backend is not mentioned, and `docs/bug-hunt-2026-09-03.md:356` named only `oidc.py:127/135` and `nas/truenas.py:122`.
- Ledger: regression-scope gap of CR-111 (the fix was incomplete), new as a finding.
- Suggested fix: pass `allow_redirects=False` in `SynologyClient._http` and raise `NasError` naming the status and `Location` when `300 <= status < 400`, copying `nas/truenas.py:127-136` verbatim. Same one-liner in `syncthing_client._request` (see dash-core-2).

### dash-core-2 - `syncthing_client` follows redirects with the API key attached
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/syncthing_client.py:125-131`
- What: the same invariant miss as dash-core-1, one tier down. `self.session.request(...)` carries `headers={"X-API-Key": self.api_key}` and leaves `allow_redirects` at its default. `requests` strips only `Authorization`, `Proxy-Authorization` and `Cookie` on a cross-host redirect - a custom header such as `X-API-Key` is re-sent verbatim. The `if resp.status_code >= 300: raise` line reads like a redirect refusal but runs *after* the chain has been followed, so it never sees a 3xx that resolved.
- Failure scenario: `SYNCTHING_GUI_URL` points at something that 302s (a reverse proxy in front of Syncthing, an http->https upgrade) and the fleet's Syncthing API key is handed to the redirect target. Lower severity than dash-core-1 because that URL is normally loopback or the NAS itself.
- Evidence: no `allow_redirects` anywhere in `syncthing_client.py`; contrast `nas/truenas.py:124` and `release_feed.py:171`'s `_NoRedirect` opener.
- Ledger: new (same class as CR-111).
- Suggested fix: `allow_redirects=False`, and treat a 3xx as a `SyncthingError` naming the `Location`.

### dash-core-3 - the Secrets wizard task rewrites `internal.env` and drops `APP_UID`/`APP_GID`
- Severity: medium
- Confidence: CONFIRMED (reproduced)
- Where: `dashboard/src/ccsync_dashboard/setup_engine.py:758-800` (`_run_secrets`) -> `dashboard/src/ccsync_dashboard/secrets_boot.py:227-270` (`ensure_secrets` -> `_write_sidecar_env_files`)
- What: `_run_secrets` deliberately passes a **snapshot containing only the five secret names** (`env_snapshot = {name: os.environ.get(name, "") for name in secrets_boot.SECRET_ENV_VARS}`) so the running process's environment is not mutated. But `ensure_secrets` ends with an unconditional `_write_sidecar_env_files(env, secrets_dir)`, and that function reads `env.get("APP_UID")` / `env.get("APP_GID")` - neither of which is in the snapshot. So the sftp sidecar's `env_file` is rewritten with the token line only, silently deleting the uid/gid pair that boot had written from the real environment. It also unlinks `sftp.env` again, which is harmless, and the same call re-writes `syncthing.env`.
- Failure scenario: an admin on an appliance opens Setup and presses [ DO IT ] on "Secrets" (the intended first-run action, and the one `_check_secrets` invites when any secret is missing). `<data>/secrets/internal.env` loses `APP_UID=`/`APP_GID=`. Nothing fails at that moment. The next `docker compose up -d sftp` (or a host reboot) starts the sftp sidecar with no uid/gid, so it owns `/tree` writes as whatever its own default is - the exact ownership mismatch `_write_sidecar_env_files`' own comment says the pair exists to prevent, and the shape dash-admin-2 (2026-08-21) was filed for.
- Evidence: ran from the dashboard venv with `APP_UID=3000 APP_GID=3001 CCSYNC_INTERNAL_TOKEN=tok-abc` in the environment:
  ```
  after boot:       'CCSYNC_INTERNAL_TOKEN=tok-abc\nAPP_UID=3000\nAPP_GID=3001\n'
  after setup task: 'CCSYNC_INTERNAL_TOKEN=tok-abc\n'
  ```
  (first call `ensure_secrets(dict(os.environ), data_dir=d)`, second `ensure_secrets(snap, data_dir=d)` with `snap` built exactly as `_run_secrets` builds it). `tests/test_secrets_boot.py` passes because no test calls `ensure_secrets` twice with two different env shapes against the same directory.
- Ledger: new (regression of the dash-admin-2 fix's intent, via a caller added afterwards).
- Suggested fix: carry the two through - `env_snapshot` should also copy `APP_UID`/`APP_GID` from `os.environ` - or, better, have `_write_sidecar_env_files` fall back to `os.environ` for the non-secret keys so no future caller can drop them by choosing a narrow mapping.

### dash-core-4 - `Origin: null` is treated as "no Origin", so the /cards/ origin-only CSRF gate lets an opaque-origin POST through
- Severity: medium
- Confidence: CONFIRMED (logic); exploitability PLAUSIBLE (SameSite=Lax is what actually holds the line)
- Where: `dashboard/src/ccsync_dashboard/app.py:900-917` (`_origin_mismatch`), used by `csrf_gate` for `_CSRF_ORIGIN_ONLY_PREFIXES = ("/cards/",)`
- What: the Timeline Cards page's ~70 POST routes are exempted from the CSRF **token** but not from the origin check, explicitly because "it drives a Resolve timeline (delete, trim, conform)". `_origin_mismatch` maps `Origin: null` onto the same branch as a missing Origin and then, when there is also no `Referer`, returns `False` = "not a mismatch" = allowed. `null` is an *opaque* origin: it is the value a browser sends precisely when the request comes from somewhere that is definitively not this site (a sandboxed iframe, a `data:`/`blob:` document, some cross-origin redirect chains). Treating it as same-origin inverts its meaning.
- Failure scenario: an attacker page with `<meta name="referrer" content="no-referrer">` hosting `<iframe sandbox="allow-scripts allow-forms">` whose document auto-submits a form to `https://<dash>/cards/api/<mutating route>` produces `Origin: null` with no `Referer`, and the gate the comment says "stops the whole class on its own" passes it. In practice the session cookie is `SameSite=Lax`, so the forged POST arrives without a session and `login_gate` 401s it - i.e. the *only* thing stopping this today is the cookie attribute the code describes as holding the line "until" the origin check exists. The defence-in-depth layer is not doing what it claims.
- Evidence: `app.py:911-914` - `if not origin or origin.lower() == "null": origin = referer...; if not origin: return False`. `auth.start_session` sets `samesite="lax"` (`auth.py:673`).
- Ledger: new.
- Suggested fix: split the two cases - an *absent* Origin stays a pass (some browsers omit it on same-origin form posts, which is the documented reason for the carve-out), but a literal `null` with no usable `Referer` is a mismatch and should be refused.

### dash-core-5 - `DASH_SITE_TEMPLATE_FOLDERS` is the one path-list door with no `..` filter
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/provision.py:37-50` (`_site_list`) and `:70` (`TEMPLATE_FOLDERS`), consumed at `dashboard/src/ccsync_dashboard/api.py:3478`
- What: the CR-111/dash-core-3 fix hardened both path-list keys on the DB/import side (`site_store._validate_csv` refuses a leading separator, a drive letter and any `..` segment for `template_folders` and `shared_asset_folders`) and additionally made `provision.shared_asset_folders_for` drop `..` itself, with the stated reason "this is also the door the `DASH_SITE_SHARED_ASSETS` environment value comes through, which no validator sees". The identical env door for template folders - `_site_list("DASH_SITE_TEMPLATE_FOLDERS", ...)` - only strips leading/trailing separators and normalises backslashes; `..` survives. `site_store._shape` falls back to `provision.TEMPLATE_FOLDERS` verbatim whenever no DB row exists (every deployment that has not saved on the Settings page), and `api.create_tree_project` does `(target / sub).mkdir(parents=True, exist_ok=True)` for each.
- Failure scenario: a site.toml rendered into compose with `[tree] template_folders = ["../../Assets"]` (or a typo producing one) makes every project creation mkdir outside the project - silently, since the same list is also what `/project-setup` previews. Not an attack from an untrusted party (it is an operator-set env var), which is why this is low, but it is exactly the reasoning the sibling fix already accepted.
- Evidence: `provision.py:47-49` vs `provision.py:190` (the `..`-dropping comprehension added by the previous fix pass).
- Ledger: new (incomplete companion to the dash-core-3 fix in CR-111's pass).
- Suggested fix: apply the same `"/".join(p for p in rel.split("/") if p and p != "..")` filter inside `_site_list`, so both env doors are covered by one rule.

### dash-core-6 - a build with no EULA file leaves the wizard permanently un-finishable
- Severity: low
- Confidence: CONFIRMED (logic); PLAUSIBLE that a real deployment hits it
- Where: `dashboard/src/ccsync_dashboard/setup_engine.py:388-418` (`_check_eula`, `_accept_eula`), registration at `:421-425`
- What: REL-5 (2026-09-04) changed both the check and the accept action from `ok` to `warn` when `EULA_PATH` does not exist, on the sound reasoning that "a build that ships without a licence agreement is now visibly wrong rather than quietly complete". But the `eula` task is registered with the default `optional=False`, so it is **required** and cannot be skipped (`run_skip` raises `ValueError`, `api_setup_task_skip` 400s). `outstanding_required` therefore contains `eula` for ever, `_check_done` never reaches `ok`, and the "Setup" nav badge never clears. `_accept_eula` also returns `warn`, so pressing ACCEPT cannot clear it either - there is no action of any kind that resolves the state.
- Failure scenario: any deployment whose code root does not carry `docs/legal/EULA.md` at `parents[2]` or `parents[3]` (a bind-mount that mounts only `dashboard/src`, an image built before the 2026-09-04 `COPY docs /app/docs`, a hand-assembled code root) shows a permanent amber row and a Setup badge that never goes away, with no button that changes it. `EULA_PATH` is also resolved at **import time**, so an OTA bundle that adds the file cannot fix it without a process restart.
- Evidence: `_find_eula()` is called once at module import (`EULA_PATH = _find_eula()`); `Task.optional` defaults False (`eula` passes no `optional=`); `run_skip` refuses a non-optional task.
- Ledger: new.
- Suggested fix: either make the no-EULA state `ok`-with-a-warning-detail that `_check_done` tolerates, or keep `warn` and let `outstanding_for_done`/`outstanding_required` treat `warn` on `eula` as satisfied, so the amber line informs without being a wall. Re-resolving `EULA_PATH` per call would also let an OTA bundle fix it.

### dash-core-7 - `DASH_SESSION_ABSOLUTE_SECONDS=0` bricks sign-in with no message
- Severity: low
- Confidence: CONFIRMED (by reading; not exercised)
- Where: `dashboard/src/ccsync_dashboard/auth.py:657-662` (`start_session`) and `sessions.py:210-222` (`SessionStore.validate`)
- What: the two consumers of the setting disagree about what `0` means. `start_session` does `int(getattr(settings, "session_absolute_seconds", ...) or SESSION_TTL_SECONDS)`, so `0.0` is falsy and the **cookie** gets the 7-day module default; `SessionStore` stores `absolute_seconds = 0.0` literally, so `validate` computes `age > 0` -> true on the first request after the create, deletes the row and returns `None`. `_resolve_session` reads "no row" as a revocation and answers `None`.
- Failure scenario: an operator sets `DASH_SESSION_ABSOLUTE_SECONDS=0` meaning "no absolute limit" (a common convention) and nobody can stay signed in: `/login` succeeds, sets a cookie, and the very next request is a 303 back to `/login`. Nothing is logged and `check_boot_secrets` says nothing.
- Evidence: `settings.from_env`'s `num()` returns `float("0") == 0.0` for a set-but-zero value (`float(raw) if raw else default` - `"0"` is a truthy *string*).
- Ledger: new.
- Suggested fix: refuse (or clamp, loudly) a non-positive `session_idle_seconds`/`session_absolute_seconds` in `Settings.__post_init__` or `check_boot_secrets`, and make the two readers agree.

## Coverage note
Not covered: `setup_engine`'s NAS-connect / snapshots / syncthing / software tasks
below line 800 were only skimmed; `site_store.set_many`, `export_toml` and the
`site_history`/undo path were read but not traced end to end; `nas/truenas.py`'s
provisioning half (user/group/dataset calls) and `nas/synology.py`'s
`_install_ssh_key` shell script were not audited line by line; `settings.py`
outside `__post_init__` and the auth block. `api.py` (which owns
`/api/v1/verify`, `/api/v1/report` and the admin user routes those backends
serve) is another hunter's territory, so the *route-side* throttle and fleet-
membership checks were not re-verified.

What the suite does not cover: no test calls `secrets_boot.ensure_secrets`
twice with two different env mappings against one directory (dash-core-3);
nothing asserts `allow_redirects` on the Synology or Syncthing clients
(dash-core-1/-2) - `test_synology_client.py` stubs `_http`/the session entirely;
`_origin_mismatch` has no `Origin: null` case (dash-core-4); there is no test
for the missing-EULA state's interaction with `outstanding_required`
(dash-core-6), only for the `warn` status itself.

## OUT OF TERRITORY
- `dashboard/src/ccsync_dashboard/api.py:3478` - `create_tree_project` mkdirs each `site_store.template_folders(...)` entry under the project with no per-segment check of its own; see dash-core-5 for the source of the unvalidated value.
