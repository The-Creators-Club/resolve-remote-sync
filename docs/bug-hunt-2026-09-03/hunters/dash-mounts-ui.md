# dash-mounts-ui — the four in-process mounts, the AI-provider chain, the CLI wizard, and the dashboard front end

Files read (with approximate coverage):
- `dashboard/src/ccsync_dashboard/broll.py` (100%), `music.py` (100%), `ytdl.py` (100%),
  `ai_providers.py` (~85%: key storage, mask, chain order, probe, routes, live test),
  `cli_tools.py` (~65%: install/checksum path, `cli_env`/overlay/`env_var_allowed`,
  pty sign-in + timeout + `_kill`, sign-out)
- `dashboard/src/ccsync_dashboard/app.py` (login_gate / csrf_gate / mount ordering, ~40%),
  `ui.py` (`_render`, `/manifest.webmanifest`, `/sw.js`, `/offline`, ~15%)
- `dashboard/static/`: `assignments.js`, `site_settings.js`, `setup.js`, `sw.js`, `pwa.js`,
  `confirms.js`, `dashboard_update.js` (all 100%), `manifest.webmanifest`
- `dashboard/templates/`: `base.html`, `offline.html`, `admin_settings.html`,
  `admin_assignments.html`, `partials/topbar.html` (100%); every other template grepped for
  `|safe`, `innerHTML`, em dashes, root-relative URL hazards
- `dashboard/tests/`: `test_pwa.py`, `test_no_em_dash.py`, `test_music_mount.py`,
  `test_admin_assignments.py` (read); the rest of the territory's suites run only

Tests run:
- `dashboard/.venv/Scripts/python.exe -m pytest tests/test_broll_mount.py tests/test_music_mount.py tests/test_ytdl_mount.py tests/test_ytdl_site_gate.py tests/test_ai_providers.py tests/test_cli_tools.py tests/test_no_em_dash.py tests/test_pwa.py tests/test_admin_assignments.py tests/test_settings_auto_derived.py -q` -> **all pass** (442 passed in the second, slightly narrower run; the full ten-file run also exited 0)
- `node --check` over every `dashboard/static/*.js` -> **1 failure** (finding 1)
- ad-hoc snippet rendering `/offline` with a live session (finding 2)

## Findings

### dash-mounts-ui-1 — `assignments.js` is a JavaScript syntax error: the entire admin assignment matrix is dead, and a tick is a silent no-op
- Severity: high
- Confidence: CONFIRMED
- Where: `dashboard/static/assignments.js:89-91` (the string literal in `confirmCapacity`); consumed by `dashboard/templates/admin_assignments.html:154`
- What: the UX-1 capacity confirm was written with two **raw newlines inside a double-quoted JS string literal**:
  ```js
  return window.confirm(sentence + "

  Sync it there anyway?");
  ```
  JavaScript string literals may not contain unescaped line terminators, so the file fails to parse. The whole file is one IIFE, so *nothing* in it runs: the `change` listener that writes a tick, the upload-only qualifier, `[ ALL ]` / `[ NONE ]`, "copy from ...", the CR-95 wired-column re-lock, and the project filter are all unregistered.
- Failure scenario: an admin opens `/admin/assignments`, ticks FF5 for `editor1` on `LESO-MBP`. The browser flips the checkbox (native behaviour), no request is made, no toast appears, no error is visible. The admin navigates away believing the plan is set; `selections` is unchanged and that machine syncs nothing. `[ ALL ]` and `[ NONE ]` do nothing at all. The failure is silent in exactly the direction CLAUDE.md calls out ("the dashboard is what tells everyone whether their footage is syncing").
- Evidence:
  ```
  $ node --check dashboard/static/assignments.js
  static/assignments.js:89
      return window.confirm(sentence + "
                                       ^
  SyntaxError: Invalid or unexpected token
  ```
  `cat -A` confirms real `$`-terminated lines inside the literal, not `\n`. `git log -S'Sync it there anyway'` dates it to `55fdfa7` (2026-08-28, "Resilience sweep wave 2"), i.e. it has been broken for every dashboard build since, including the 0.7.27 image now live. `node --check` over the other six static JS files passes, so this is the only one.
  `tests/test_admin_assignments.py` passes because it only asserts the *server* renders `data-proxy-bytes` / `data-free-bytes` / `data-col-free`; nothing in `dashboard/tests` parses or executes JS, and `test_no_em_dash.py` reads the JS as raw text only.
- Ledger: new (not in `KNOWN_BUGS.md`; the two `assignments.js` mentions at lines 1039 and 5049 describe intended behaviour, not this)
- Suggested fix: replace the literal newlines with `\n\n` (`sentence + "\n\nSync it there anyway?"`). Add a syntax gate to the suite — a test that runs `node --check` (or, to stay dependency-free, `Path.read_text()` + a check that no `"`/`'` literal spans a newline) over `static/*.js` excluding `htmx.min.js`; the em-dash scan already enumerates exactly that file list.

### dash-mounts-ui-2 — the service worker precaches `/offline`, which renders the signed-in user's name, admin drawer and CSRF token
- Severity: medium
- Confidence: CONFIRMED
- Where: `dashboard/static/sw.js:24` (`PRECACHE` contains `'/offline'`) + `dashboard/static/sw.js:70` (`cache.add(new Request(url, {cache: 'reload'}))`, default `credentials: 'same-origin'`) vs `dashboard/templates/offline.html:1` (`{% extends "base.html" %}`) and `dashboard/src/ccsync_dashboard/ui.py:125-135` (`_render` sets `session_user`, `session_is_admin`, `csrf_token` on every render, `/offline` included)
- What: sw.js's own header states the invariant "THIS WORKER NEVER CACHES ANYTHING THAT DEPENDS ON WHO IS ASKING", and `offline.html`'s comment says it "must say nothing that could be stale: no counts, no fleet state, no name". But it extends `base.html`, which emits `<meta name="csrf" content="...">`, `<body hx-headers='{"X-CSRF-Token": "..."}'>` and includes `partials/topbar.html`, which prints `{{ session_user }}{{ " (admin)" if session_is_admin }}` in three places (lines 92, 142, 194) and gates the drawer's admin links on the same flag. The precache fetch carries the session cookie, so the frozen copy is one specific user's page. It is only replaced when `VERSION` changes the cache name.
- Failure scenario: an editor installs the PWA and the worker installs while they are signed in. They sign out (or hand the phone/browser to a colleague who signs in as someone else). Any navigation that cannot reach the server now paints the offline page showing the *previous* user's username, "(admin)" if they were one, that person's admin nav, and their now-dead CSRF token. On a shared or handed-over device this is an identity disclosure; in every case it is the dashboard displaying a stale identity, which is the failure class the file was written to prevent.
- Evidence: with `DASH_DEV_INSECURE=1` and a session cookie for `owen`:
  ```
  GET /offline -> 200
  "owen" in body: True
  <meta name="csrf" content="d0b732a3441b5670...">
  ```
  `tests/test_pwa.py:193 test_offline_says_nothing_about_this_fleet` looks like it covers this and does not: it uses the anonymous `client` fixture *and* strips everything before `</header>` (`res.text.lower().split("</header>")[-1]`) — i.e. it explicitly excludes the topbar, which is the only place the name appears. That is a test that mocks away the exact thing that breaks.
- Ledger: new
- Suggested fix: render `/offline` from a session-free base (its own minimal layout, or `_render` with `session_user=None`/`csrf_token=""` forced for this one route), and widen the test to assert a *logged-in* `GET /offline` contains neither the username nor a non-empty `csrf` meta. Alternatively drop `/offline` from `PRECACHE` and fetch it with `{credentials: 'omit'}` — but the template still needs to stop carrying a token.

### dash-mounts-ui-3 — `dashboard_update.js` swaps an unchecked response into the page, so an expired session injects the login document into the packages panel
- Severity: low
- Confidence: CONFIRMED (mechanism read; not exercised live)
- Where: `dashboard/static/dashboard_update.js:60-66` (`reloadPanel`)
- What: `reloadPanel()` does `fetch(PARTIAL_URL, {headers: {"HX-Request": "true"}})` then `host.outerHTML = html` with **no `resp.ok` check**. Because it sends `HX-Request: true`, `app.py`'s `login_gate` answers an expired session with the 303-avoidance path built for htmx: a response carrying `HX-Redirect`. Plain `fetch` does not understand `HX-Redirect` (only htmx does), so the login page's HTML is written into the panel via `outerHTML`. This is the DASH-4 shape (a login document swapped into a fragment slot) reappearing in the one panel that deliberately does not use htmx.
- Failure scenario: an admin leaves the Packages page open past session expiry, or the dashboard restarts mid-update and re-authentication is required; the panel silently becomes a nested login form instead of saying the session ended, and the update's real outcome is never shown.
- Evidence: `app.py` login_gate's htmx branch returns `HX-Redirect` rather than a 303 for `hx-request: true`; `reloadPanel` inspects neither status nor headers. The sibling helper `postJson` in the same file *does* check `resp.ok`.
- Ledger: related to DASH-4 (fixed for htmx, 2026-08-14) — this is a non-htmx caller re-opening the same hole
- Suggested fix: in `reloadPanel`, bail out (or `window.location.reload()`) when `!resp.ok` or when `resp.headers.get('HX-Redirect')` is present.

### dash-mounts-ui-4 — `BrollGate._token_ok` matches the ingest header case-sensitively, alone among the four gates
- Severity: low
- Confidence: CONFIRMED (code); PLAUSIBLE that it can ever bite
- Where: `dashboard/src/ccsync_dashboard/broll.py:299-306` (`if key == b"x-ingest-token"`)
- What: every other header read in the three gates uses `key.lower()` (`_fleet_stamp`, `_identified_scope`, `_session_cookie`, `music._header_value_of`); this one compares raw bytes. Under uvicorn/h11 ASGI header names arrive lowercased, so it is inert today — but it is the one place where a differently-cased `X-Ingest-Token` would read as *absent*, and absent is a **401 refusal**, so the failure direction is fail-closed rather than a bypass. Worth aligning anyway because this is the module whose whole purpose is "getting this wrong silently unguards the ingest routes", and a hand-built scope (a future middleware, another server, a test) would behave differently from every neighbour.
- Failure scenario: the dashboard is ever fronted by an ASGI server or middleware that preserves header case, or a future in-process caller constructs a scope by hand: the indexer's ingest POSTs are all refused 401 with "missing or invalid X-Ingest-Token" while the header is plainly present.
- Evidence: side-by-side with `broll.py:214-218` and `music.py:_header_value_of`, both of which lowercase.
- Ledger: new
- Suggested fix: `if key.lower() == b"x-ingest-token":`.

## Coverage note

Verified and found clean (worth recording as negative results):
- **Tri-state / never fatal.** All four mounts wrap the import in `except Exception` and log-and-continue; the storage probe is separately wrapped and downgrades to `DEGRADED` with the nav link hidden. The `_add_in_repo_*` fallbacks correctly refuse to fire when the package is already in `sys.modules`. `_init_broll_storage`'s optional `client_folders` import is `ImportError`-guarded. `mount_ytdl` leaves the mount off entirely when the tree is ABSENT at boot with the feature ON — documented as deliberate (a redeploy restarts the container).
- **Ingest gate fail-closed.** `check_ingest_token` refuses empty/placeholder/short/low-entropy; `mount_broll` returns ABSENT rather than mounting; `_token_ok` returns False on an unset token; `INGEST_PREFIX` (`/api/ingest/`) covers all four upstream routes (`app/routes_ingest.py` has only `/video`, `/index`, `/moved`, `/shares` under a `/api/ingest` prefix) and correctly does not swallow `/api/ingest-batches`. `sub_paths` checks both Starlette path conventions.
- **Bare `/music` -> `/music/`** is pinned by `tests/test_music_mount.py:291` and passes.
- **Provider order** is `(claude_code, anthropic_api, codex, openai_api, deepseek_api)` at `ai_providers.py:85`; env wins in `read_key`; `set_key` goes through `secrets_boot.write_secret_file` (0600) under `<db parent>/secrets/ai`; `PUT .../key` 409s when the env carries the variable. Keys are masked (`sk-…abcd`, whole-value mask under 12 chars) in `provider_states`; the only exit is `lookup_payload` in-process; no key reaches a log line, an error message (`validate_key` never echoes) or a query string. `_NoRedirect` on the live test call is correct.
- **cli_tools checksum is a condition**: `claude_platform_entry` raises when the manifest entry has no `_SHA_RE`-shaped checksum; `_install_codex` raises rather than installing when the publisher shipped no `sha256sums`; `_download` unlinks on every failure path and verifies sha *and* size before `_finish_install` flips the pointer. `cli_env` is the single helper used by the probe (`_probe_env`), the Test button (`test_provider` -> `probe_cli`) and the real ytdl call (`cli_env_overlay` in `lookup_payload`), and `_run_strategy` pops `CLAUDE_CODE_OAUTH_TOKEN` before a login. `SIGNIN_TIMEOUT` is enforced against `session.started_at` (monotonic) with `_kill` in both `_run_strategy` and `_signin_worker`'s `finally`; `_kill` is idempotent (`_master = -1`).
- **Front end**: exactly one `|safe` in the whole template tree and it is a constant (`partials/settings_nav.html:45`); Jinja autoescape is on and not disabled anywhere; `site_settings.js` uses `textContent` throughout; the sign-in link's `href` can only be an `https://` match (`_URL_RE`). CSRF: `base.html` puts the token on `<body hx-headers>` so every htmx request carries it, and the four `fetch()` callers all send `X-CSRF-Token`; the `/broll/ /music/ /ytdl/` CSRF exemptions are backed by `SameSite=Lax` on the session cookie. No em dash in any template, static JS, or the five territory modules (only `static/style.css:1`, a comment, correctly out of scope). `sw.js`'s `PASS_THROUGH` covers `/api/`, `/partials/` and all four mounts; `manifest.webmanifest` scope/start_url are `/` and carry no fleet data.
- CR-99's fix holds: `admin_settings.html` renders `readonly` only for live-derived keys, `site_settings.js` skips `el.readOnly` (which reflects for `<input type=checkbox>` too), the one `disabled` checkbox has no `name` so it is skipped, and `#settings-import-form` is a separate `<form>` so its textarea cannot leak into the site PUT.

Not reached: `cli_tools.py`'s HTTP routes and `setup_snapshot`/`install_status` rendering (~35% unread); `ai_providers.provider_states`' interaction with `cli_tools.setup_snapshot` under a partially-installed tool; the mounted sub-apps' own code (`broll/web`, `music/web`, `ytdl/web` — other territories) beyond the two route-prefix checks above; `cards.py` / `cards_wsgi.py` (a separate territory per the brief's file list, though it is the fourth mount). The suite has **no JavaScript parse/execution coverage at all** — that is the gap finding 1 lives in — and `test_pwa.py`'s offline assertion is scoped past the topbar (finding 2).

## OUT OF TERRITORY
- `dashboard/tests/test_pwa.py:193`: `test_offline_says_nothing_about_this_fleet` strips everything before `</header>` and uses an anonymous client, so it cannot see the identity it is named for (in territory, folded into finding 2).
- `dashboard/src/ccsync_dashboard/setup_engine.py`: `setup.js:153` writes `task.title` / `task.detail` into `tr.innerHTML`; several details interpolate values from outside the admin's own typing (`_check_tailscale`'s account `name` at :834, the NAS `hostname` at :964, raw exception strings). Admin-only page and no confirmed injection source, so not raised as a finding, but `createElement`/`textContent` would close it.
