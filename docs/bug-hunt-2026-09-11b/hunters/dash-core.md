# dash-core - the dashboard's app/auth/session/setup/help core

Files read (with approximate coverage):
- `dashboard/src/ccsync_dashboard/app.py` (the middleware stack, `_origin_mismatch`,
  `body_size_gate`, `csrf_gate`, `login_gate`, `unhandled_error`: ~60%, all of the
  18e69f3 diff)
- `auth.py` (100%), `sessions.py` (100%), `oidc.py` (100%), `setup_api.py` (100%),
  `setup_routes.py` (~70%, all gates), `internal_sftp.py` (100%),
  `tailscale_local.py` (100%), `truenas_client.py` (skim),
  `published_docs.py` (100%, new file), `help.py` (100%),
  `secrets_boot.py` (~80%), `setup_engine.py` (~45%: the state machine, the gates,
  the eula and secrets tasks), `site_store.py` (~35%: validators, cache, features)
- Read across the boundary to verify both sides: `notices.record_server_error`,
  `local_users.create_user`, `ui.py:_help_response`, `dashboard/static/setup.js`,
  `dashboard/deploy/Dockerfile`, `server/install_dashboard_app.py:_stage_docs_tree`,
  `tools/build_dashboard_bundle.py`, `dashboard_update.py` (extraction only).

Tests run:
`dashboard\.venv\Scripts\python.exe -m pytest tests/test_auth.py tests/test_sessions.py
tests/test_oidc.py tests/test_help_page.py tests/test_setup_engine.py
tests/test_setup_routes.py tests/test_setup_api.py tests/test_secrets_boot.py
tests/test_internal_sftp.py tests/test_site_store.py
tests/test_bug_hunt_2026_09_11_dash_db_core.py tests/test_local_auth_mode.py -q`
-> **381 passed, 1 skipped** in 70 s.
Plus three scratch scripts run from the dashboard venv (outside the repo) to prove
findings 1, 3 and the help audience gate.

## Findings

### dash-core-1 - a `warn` on the EULA task is sticky, so the licence is never accepted once it arrives
- Severity: medium
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/setup_engine.py:251-275` (`WARN_SATISFIES_IDS`,
  `_gate_satisfied`, `outstanding_required`) and `:396-398` (`outstanding_for_done`);
  the state it reads is written at `:293-307` (`run_check`) and read back from SQLite
  at `:235-247` (`list_states`).
- What: `_gate_satisfied` treats a **stored** `eula` status of `warn` as satisfied, but
  `list_states` reads the persisted `setup_tasks` row and **nothing re-runs
  `_check_eula` on its own** - `setup.js` only POSTs `/api/v1/setup/tasks/eula/check`
  when an admin clicks CHECK on that row. So the warn is a latch: once a build with no
  `docs/legal/EULA.md` has written it, the gate stays satisfied for ever, including
  after the licence file arrives. That is precisely the state the other half of the
  same fix (`eula_path()`, dash-core-6) exists to make recoverable - it re-resolves the
  path so a late OTA bundle or bind-mount IS seen - but the gate that would have sent
  the admin back to the step has already been switched off by the stored row.
- Failure scenario: an appliance boots on a build/bundle whose `docs/legal` did not
  land. The admin opens Setup, presses CHECK on "Welcome, EULA" -> row stored as
  `warn` ("no licence agreement is included in this build..."). The next OTA bundle
  carries `docs/legal/EULA.md`. From then on: `outstanding_required` does not list
  `eula`, `outstanding_for_done` does not list it, the Setup nav badge is clear, the
  wizard's `done` task passes, the post-login steer to `/setup` stops - and no human
  has ever accepted the licence agreement on that customer's server. The amber line
  the comment relies on ("the amber line still says so") is also stale: it still says
  *no licence is included in this build*, which is now untrue.
- Evidence: scratch script against a real `db.connect` DB, with the repo's own
  `docs/legal/EULA.md` present on disk:
  ```
  EULA file exists now: E:\Projects\Editing\ccsync\docs\legal\EULA.md True
  outstanding_required: False          # 'eula' absent
  outstanding_for_done: ['admin','studio','storage','secrets','syncthing',
                         'release_key','snapshots','alerts']   # 'eula' absent
  stored: {'id':'eula','status':'warn','detail':'no licence','at':...,'skipped':0}
  ```
  `grep -n "check" dashboard/static/setup.js` shows the only caller of the check route
  is the per-row `CHECK` button (`actionButton("CHECK", ...)`, line 252); the page's
  load path calls `GET /api/v1/setup/eula` and `GET /api/v1/setup/tasks`, neither of
  which re-evaluates a task.
- Ledger: new; CR-248's dash-core-6 half does not cover it (the pair of regression
  tests at `tests/test_bug_hunt_2026_09_11_dash_db_core.py:212-229` only pins the new
  "does not wall the wizard" direction).
- Suggested fix: make `_gate_satisfied` ask the world rather than the row for the one
  exempt id - e.g. `WARN_SATISFIES_IDS` becomes a map id -> predicate and `eula`'s is
  `not eula_path().is_file()`; or have `outstanding_required`/`outstanding_for_done`
  re-run `check` for any task whose stored status is in `WARN_SATISFIES_IDS` (it is one
  `is_file()` plus a small read). Either way the row must stop being the authority for
  a condition that is a property of the filesystem.

### dash-core-2 - the "other direction" regression test for dash-core-6 asserts a constant and can never fail
- Severity: medium
- Confidence: CONFIRMED
- Where: `dashboard/tests/test_bug_hunt_2026_09_11_dash_db_core.py:225-229`
- What: `test_a_required_task_that_is_merely_warn_still_gates` claims to prove "only
  `eula` is exempt. A required task that warns for a reason an admin can act on must
  keep the badge lit" - and its entire body is
  `assert setup_engine.WARN_SATISFIES_IDS == frozenset({"eula"})`. It never builds a
  state, never calls `_gate_satisfied`, and never calls `outstanding_required`. It
  asserts that a literal one line above it in the source has not been edited. If a
  future change made `_gate_satisfied` return True for every `warn` (dropping the id
  test) while leaving the constant alone, this test stays green; so does the whole
  suite, because no other test covers a non-`eula` required task in `warn`.
- Failure scenario: a later refactor widens the warn carve-out (deliberately or by a
  copy-paste that drops the `task_id in WARN_SATISFIES_IDS` clause). Every required
  task that warns - `storage` on a probe it could not complete, `syncthing` reachable
  but reporting no device id (`setup_engine.py:860`) - silently stops gating Done and
  the Setup badge, on every customer's first day. Nothing in the suite goes red.
- Evidence: read the test body; the suite passes with it, and the assertion has no
  dependency on any code path under test. `grep -n "status=\"warn\"" setup_engine.py`
  shows at least `_check_syncthing` (`:860`) can put a REQUIRED task in `warn` for a
  reason an admin CAN act on, which is exactly the case the docstring promises to
  cover and does not.
- Ledger: new (test quality, CR-248 / dash-core-6).
- Suggested fix: register a throwaway required task (or monkeypatch one of the real
  ones) into a `warn` state and assert it IS in `outstanding_required` and
  `outstanding_for_done`, i.e. exercise `_gate_satisfied`'s id test rather than the
  constant it reads.

### dash-core-3 - the login backoff raises OverflowError once a key passes ~1024 recorded failures
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/sessions.py:390-395` (`record_failure`)
- What: `delay = min(LOGIN_BACKOFF_BASE_SECONDS * (2 ** (failures - limit)),
  LOGIN_BACKOFF_MAX_SECONDS)`. The exponent is an unbounded Python int and the base is
  a `float`, so the multiplication is evaluated **before** `min` clamps it. Past
  `failures - limit == 1024` the product is larger than a float can hold and
  `float * int` raises `OverflowError`, which is not an `sqlite3.OperationalError`,
  so `_run` does not catch it and it escapes `auth.record_login_failure` into the
  route.
- Failure scenario: `failures` only grows on attempts made while the key is NOT
  blocked, and the block caps at `LOGIN_BACKOFF_MAX_SECONDS` (3600 s) while
  `LOGIN_FAILURE_WINDOW_SECONDS` is also 3600 s, so a patient attacker who retries
  once per hour keeps `last_failure` fresh and increments `failures` by one an hour
  indefinitely (the staleness test is `> 3600`, and a wait of exactly the block is
  `== 3600`). After ~43 days of that against one username (or one gateway IP, whose
  budget every editor behind Tailscale Serve shares - see `LOGIN_FAILURE_LIMIT_IP`'s
  own note), the next failed sign-in 500s instead of being throttled, and every
  subsequent failed sign-in for that key 500s too: the throttle for that key is
  effectively disabled and the login page breaks for whoever owns it.
- Evidence:
  ```
  >>> min(60.0 * (2 ** (1029 - 5)), 3600.0)
  OverflowError: int too large to convert to float
  >>> min(60.0 * (2 ** (600 - 5)), 3600.0)   ->  3600.0
  ```
- Ledger: new.
- Suggested fix: clamp the exponent before the multiply -
  `delay = LOGIN_BACKOFF_BASE_SECONDS * (2 ** min(failures - limit, 16))` then `min(...,
  LOGIN_BACKOFF_MAX_SECONDS)`; or stop incrementing `failures` once
  `blocked_until` is already at the ceiling.

### dash-core-4 - APP_UID without APP_GID is written to internal.env but ignored by the reader
- Severity: low
- Confidence: PLAUSIBLE
- Where: `dashboard/src/ccsync_dashboard/secrets_boot.py:270-288` (writer, the
  dash-core-3 hunk from this afternoon) and
  `dashboard/src/ccsync_dashboard/internal_sftp.py:_uid_gid` (reader)
- What: the writer emits `APP_UID=` and `APP_GID=` **independently** (`if app_uid:` /
  `if app_gid:`), so a half-configured pair produces an `internal.env` with one of the
  two. The dashboard's own reader takes the pair or neither
  (`if app_uid and app_gid: ... return int(...)`) and otherwise falls back to
  `os.getuid()`/`os.getgid()` - with no log line, because the warning there only fires
  when the values are present but non-integer. The two sides therefore disagree about
  file ownership with nothing said.
- Failure scenario: a compose file (or an OTA-updated stack) that sets `APP_UID` and
  not `APP_GID`. `GET /internal/sftp/users` answers with the dashboard container's own
  uid/gid, while the sftp sidecar starts with `APP_UID` from `internal.env`: files the
  sidecar writes into `/tree` land owned by one id pair and the dashboard/Syncthing
  expect another - SPEC §3.1's whole reason for the variable. The symptom is a
  permission failure on an editor's lane, days later, with nothing in either log
  pointing at the mismatch.
- Evidence: read both sides; the writer's `lines.append` pair is unconditionally
  independent, the reader's guard is `and`. No test covers a half-set pair
  (`tests/test_internal_sftp.py` sets both or neither).
- Ledger: new; the writer half is the fix ledgered as CR-248 / dash-core-3.
- Suggested fix: treat the pair as atomic in the writer too (emit both or neither),
  and log one WARNING in `_uid_gid` when exactly one of the two is set, so the
  misconfiguration is visible rather than silently downgraded.

### dash-core-5 - the /help index re-walks and re-opens the whole docs tree on every admin render
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/help.py:238-295` (`document_groups`), called
  from `ui.py:_help_response` on every `GET /help` and `GET /help/{doc_path}`
- What: each render does `root.rglob("*.md")` plus, per entry, a `resolve_document`
  (`Path.resolve()` + `is_file()`) and a `_title_of` (open + up to 60 readlines).
  Nothing is cached, and there is no mtime check. The audience gate added this
  afternoon filters the list but does not reduce the work for an admin.
- Failure scenario: on a dev checkout / the base rig the admin index is 185 documents,
  so one `/help` page load is ~185 `rglob` hits plus ~370 filesystem calls plus 185
  file opens, synchronously on the single-worker container's event loop (the route is
  `def`, so FastAPI does run it in a threadpool - but it still competes with the
  collector for the same disk, and every internal link click repeats it). Measured
  from the venv: `document_groups(True)` -> 185 entries, `document_groups(False)` -> 7.
  On a customer's 0.7.43 image it is 7 entries, so this is a base-rig/dev cost only.
- Evidence:
  ```
  editor entries: 7   docs/: HOW_IT_WORKS.md, EDITOR_SETUP.md
                      docs/legal/: EULA, PRIVACY, TELEMETRY, THIRD_PARTY_NOTICES,
                                   YOUTUBE_FEATURE_NOTICE
  admin entries: 185
  ```
- Ledger: new (pre-existing shape, made visible by dash-mounts-ui-1).
- Suggested fix: cache the (rel, title) index on `app.state` keyed by the docs root's
  mtime, the way `site_store.manifest_for_app` caches the manifest, and drop it on a
  root mtime change.

## Verified NOT defects (checked because the diff invited it)

- `app.py:_origin_mismatch` (dash-core-4 of the morning hunt): the function returns
  True for a MISMATCH, so `return opaque` correctly refuses a literal `null` origin
  with no Referer. I initially read it as inverted; it is not. `tests/...:179-199`
  covers both directions against the real `/cards/` origin-only gate.
- `app.py`'s `route=str(route_path or "")` hand-off matches
  `notices.record_server_error(conn, path, exc, now=None, route="")` exactly, and
  `scope["route"]` is set by FastAPI's `APIRoute.matches`
  (`fastapi/routing.py:836,1258`), absent for a starlette `Mount` - which is what the
  comment claims.
- The `/help` audience gate holds: `resolve_document("SECRETS.md", False)` -> None,
  `("_root/KNOWN_BUGS.md", False)` -> None, `("legal/../SECRETS.md", any)` -> None
  (the `..` rule refuses it for an admin too). `published_docs.is_published` fails
  closed on a non-`.md`, a normpath escape and an unknown name.
- `published_docs` has exactly the four readers its docstring names, and all three
  shipping routes fail CLOSED on an unreadable list (`published_docs_module()` -> None
  ships only `SHIPPED_DOCS`/`SHIPPED_DOC_TREES`). The Dockerfile's COPY lines
  (`:116-117`) match `PUBLISHED_DOCS`/`PUBLISHED_TREES`. `_root/` is gone from the
  image and `help._APP_ROOT.parent` on the container is `/app`, which holds none of
  `ROOT_FILES` - so the dev-checkout branch cannot leak there.
- OTA bundles extract into a fresh versioned tree and swap (`dashboard_update.py`
  `extract_bundle` -> `staging` -> `final`), so a server that previously carried the
  whole docs tree does not keep stale copies after the 0.7.43 bundle.
- `setup_api.setup_admin`'s `password: Field(min_length=1)` is not the password floor
  bypass it looks like: `local_users.create_user` calls `auth.check_password`
  (12 chars) and turns the refusal into a 422.
- `body_size_gate`'s two carved-out prefixes (`/api/v1/admin/packages/`,
  `/music/api/ingest`) are both inside `_CSRF_EXEMPT_PREFIXES`, so `_csrf_from_form`
  can never steal an unbuffered stream from them.
- No em dash in any user-visible string across the fourteen territory files (scanned
  for U+2014 and U+2013; zero hits).

## Coverage note

Not covered: `setup_engine.py`'s ~1100 lines of individual task implementations
(storage probe, admin, studio, syncthing, release_key, snapshots, alerts, done) beyond
their status transitions; `site_store.py`'s validators in detail and `export_toml` /
`import_toml` round-tripping; `truenas_client.py` (skim only); `app.py`'s lifespan,
the collector thread wiring and the mount bootstrap; `oidc.py` against a live IdP.

What the suite does not cover, that I would want covered: (a) any task whose stored
status is `warn` and whose world has since changed - the whole class dash-core-1 falls
into; (b) a required non-`eula` task in `warn` reaching `outstanding_required`
(dash-core-2); (c) the login throttle at large failure counts (dash-core-3 -
`test_sessions.py` stops at a handful); (d) `/help` rendered as a non-admin against a
tree that contains unpublished documents - `test_help_page.py` does not construct one,
so the audience gate is only proven by the `published_docs` unit tests and by my
scratch run.

## OUT OF TERRITORY

- `dashboard/src/ccsync_dashboard/oidc.py` is mine, but its counterpart
  `auth.is_admin` deliberately ignores `is_admin_by_claims`: an OIDC deployment whose
  admins come only from the admin CLAIM has no admins at all for `/help`, `/setup`,
  `require_setup_access` or any `/api/v1/admin/*` route. Documented at
  `oidc.py:479-486` as a decision, so not filed as a finding - but worth a line in
  `docs/` because the wizard is then unreachable on such a deployment.
- `dashboard/src/ccsync_dashboard/notices.py:redact_path` - not read in depth; the
  new `route=` argument's redaction of a route template (as opposed to a concrete
  path) belongs to dash-collector-alerts.
- `dashboard/static/setup.js` - the checklist never re-checks a task on load, which is
  what makes dash-core-1 reachable; the fix may belong on that side instead
  (dash-mounts-ui).
