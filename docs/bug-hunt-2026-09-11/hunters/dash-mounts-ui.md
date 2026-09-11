# dash-mounts-ui - dashboard HTML/JS surface, the /broll + /music mounts, and the deploy/CI machinery

Files read (with approximate coverage):
- `dashboard/src/ccsync_dashboard/help.py` (100%), `broll.py` / `music.py` mount halves (100% of the
  diff since 097f5a3, ~60% of the files), `ui.py` (100% of the 1063-line diff, ~40% of the file:
  `_render`, the stamp routes, `SETTINGS_NAV*`, `CHIP_HELP`/`chip_help`, `safe_to_close`, the
  manifest / sw.js / offline / help routes).
- `dashboard/static/`: `sw.js`, `pwa.js`, `tab_memory.js`, `htmx_errors.js`, `copy_value.js`,
  `confirms.js`, `dashboard_update.js`, `assignments.js` (copy-plan + filter halves),
  `site_settings.js` diff (100% each of those; style.css / mobile.css skimmed only).
- `dashboard/templates/`: `base.html`, `partials/topbar.html`, `partials/stamp.html`,
  `partials/chip_sheet.html`, `partials/settings_nav.html`, `partials/fleet_grid.html`,
  `partials/admin_packages.html` (policy form), `help.html`, `admin_assignments.html`. All 73
  `hx-get|post|put|delete` URLs across every template were mechanically diffed against the route
  decorators in `ui.py`/`api.py`/`android.py`/`setup_routes.py`/`settings.py` - no orphans.
- `dashboard/deploy/`: `run.sh` (100%), `select_code_root.py` (100%), `Dockerfile` (100%),
  the three compose files (env-key parity, mechanically), `.dockerignore`, line endings.
- `.github/workflows/`: `ci.yml`, `image.yml`, `release-dashboard.yml`, `android.yml` diffs.
- Tests: `test_static_js_syntax.py`, `test_no_em_dash.py`, `test_help_page.py`, `test_tab_memory.py`,
  `test_pwa.py`, `test_broll_mount.py`, `test_music_mount.py`.

Tests run:
- `node --check` on every hand-written `dashboard/static/*.js` -> all 10 parse.
- `cd dashboard; .venv\Scripts\python.exe -m pytest tests/test_static_js_syntax.py tests/test_no_em_dash.py
  tests/test_pwa.py tests/test_tab_memory.py tests/test_help_page.py tests/test_broll_mount.py
  tests/test_music_mount.py tests/test_run_sh_restart_loop.py tests/test_select_code_root.py
  tests/test_topbar_partial.py tests/test_theme_css.py tests/test_mobile_css.py tests/test_home_layout.py -q`
  -> **432 passed, 1 skipped** in 83 s.

## Findings

### dash-mounts-ui-1 - /help serves the whole internal docs tree (KNOWN_BUGS, CLAUDE.md, SECRETS.md, PRODUCT_REPO.md) to any signed-in editor
- Severity: high
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/ui.py:4152` (`page_help_document`, no admin check),
  `dashboard/src/ccsync_dashboard/help.py:262` (`resolve_document` allow-lists only the path *shape*,
  never the *audience*), `dashboard/src/ccsync_dashboard/ui.py:181`
  (`("help", "HELP", "/help", False)` - `admin_only` is False),
  `dashboard/deploy/Dockerfile:110,118` (`COPY docs /app/docs` + `COPY *.md /app/docs/_root/`).
- What: the 2026-09-04 widening of `/help` from one customer explainer to "every markdown file the
  repository carries" shipped the entire `docs/` tree plus `KNOWN_BUGS.md` / `CLAUDE.md` / `SPEC.md`
  into the image, and the route that serves them sits behind the **login** gate only, not the admin
  gate. Every editor on every customer's fleet can read the vendor's engineering documentation.
- Failure scenario: an editor at a second customer signs in, opens the topbar `[ ? ]`, and gets a
  133-entry index. `GET /help/_root/KNOWN_BUGS.md` returns 1.47 MB of rendered defect ledger;
  `/help/_root/CLAUDE.md` returns the build/release/secret layout; `/help/SECRETS.md` returns the
  secrets runbook; `/help/PRODUCT_REPO.md` returns the table that itself flags `100.65.15.123`,
  `tail26290e` ("one hit leaks the whole network's identity") and the first customer's share layout.
  It also directly contradicts CLAUDE.md's "No customer's name in code" and the second-customer
  separation work.
- Evidence: TestClient against `create_app(...)` with a plain `jsmith` session cookie and
  `admin_users={"owen"}`:

  ```
  _root/KNOWN_BUGS.md 200 1469667
  _root/CLAUDE.md     200 93580
  SECRETS.md          200 59674
  PRODUCT_REPO.md     200 72382
  legal/EULA.md       200 60492
  index entries: 133
  ```

  `tests/test_help_page.py::test_an_editor_can_read_it` asserts the editor *can* read it, so the
  suite pins this behaviour and would not catch it.
- Ledger: new (the route is REL-5 / UX-3; the widening is "Alex, 2026-09-04" in help.py's docstring;
  nothing in the ledger covers who may read what).
- Suggested fix: split the surface. Keep `/help` (HOW_IT_WORKS.md plus the glossary, the customer
  explainer) open to any session; put `help_groups`, `/help/{doc_path}` and the `_root/` allow-list
  behind `session_is_admin`, or better ship only a `docs/customer/` sub-tree in the image.
  `.dockerignore` re-including `*.md` wholesale is the other half: as it stands, this hunt's own
  `docs/bug-hunt-2026-09-11/hunters/*.md` would ship to customers in the next image.

### dash-mounts-ui-2 - "Safe to close" is computed for the PERSON, not the computer, and says "this computer"
- Severity: medium
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/ui.py:396-437` (`safe_to_close`), rendered by
  `dashboard/templates/partials/my_queue.html:17` and `partials/transfers.html:16`.
- What: the sentence is built from `build_transfers_view(conn, editor=...)`, which is scoped by
  editor only. `safe_to_close` filters live transfers and queues on `t["editor"] == editor` and
  never on `t["machine"]`, then renders copy that names "this computer" three times. CLAUDE.md's own
  invariant is that a plan belongs to a COMPUTER, and `selections` / `machine_state` /
  `editor_media_project` are all keyed `(editor, machine)` for exactly that reason.
- Failure scenario: an editor with two machines (the shape MULTI_MACHINE_PLAN.md exists for) is on
  their laptop with nothing owed while their desktop has 40 GB of lane-A backlog. The laptop page
  says "Not yet: 412 file(s) still uploading from this computer (41.2 GB), about 2h. Leave it
  running." They leave the wrong machine on overnight. Nothing on the page distinguishes "your
  desktop is still going" from "this laptop is still going".
- Evidence:

  ```
  >>> ui.safe_to_close({'transfers':[{'editor':'alex','machine':'DESKTOP','direction':'up',
  ...   'bytes_total':1000,'bytes_done':100,'speed_bps':0}],'queues':[]}, 'alex')
  {'safe': False, 'sentence': 'Not yet: 1 file(s) still uploading from this computer (900 B). ...'}
  ```

  A transfer explicitly tagged `machine: DESKTOP` produces copy about "this computer" for a session
  that could be on any machine.
- Ledger: new (the feature is DUI-19, sweep 2026-09-03).
- Suggested fix: either word it for the person ("nothing from your computers is waiting to go to the
  server" / "<MACHINE> is still uploading N files"), or name the machine in every branch. The
  dashboard cannot know which computer the browser is on, so the honest form names the machines.

### dash-mounts-ui-3 - run.sh writes `ok: true` for a youtube_unblock install it never performed or verified
- Severity: medium
- Confidence: CONFIRMED (mechanism), PLAUSIBLE (how often the trigger occurs)
- Where: `dashboard/deploy/run.sh`, the
  `if [ "$want_unblock" = "$have_unblock" ] && [ ! -f "$UNBLOCK_MARKER" ]; then write_unblock_marker 1 0 ""`
  block.
- What: the plugin's evidence of installation is a *stamp* (`$VENV/.requirements-unblock-hash`, or
  `/data/.requirements-unblock-hash` in image mode) that lives apart from the artefact
  (`/data/unblock-site`). When the stamp matches and the marker is absent, run.sh writes a marker
  claiming `ok: true, attempts: 0` without probing anything, so an install state it cannot verify is
  recorded as SUCCESS. `ytdlweb.routes_api._plugin_install_state` and the dashboard's
  self-diagnosis then read that marker as green. This is the shape SELF_DIAGNOSIS.md forbids: "an
  unverified check is NOT CHECKED, never OK".
- Failure scenario: `/data/unblock-site` is emptied (CR-84's own note records exactly this - a manual
  `docker exec -u 0 ... pip install` "that the next image update threw away") while
  `/data/.requirements-unblock-hash` survives. Next boot: `mkdir -p` recreates an empty directory, no
  install runs, a fresh `ok:true` marker is written. `/ytdl/api/health` reports the PO-token provider
  installed; every server download silently crawls the throttled HLS ladder at ~1.8 MiB/s or lands
  empty - CR-73/CR-75's symptom, now behind a green health route instead of a log WARNING.
- Evidence: read of run.sh. The stamp and the artefact are written at two different paths and only
  the stamp gates the install; `write_unblock_marker 1 0 ""` is reached on a code path where the
  script has run no pip and stat'd no package.
- Ledger: related to CR-84 (fixed) / YTWEB-5; the marker's "unknown means OK" branch is new.
- Suggested fix: gate on the ARTEFACT, not the stamp - add
  `[ -d "$UNBLOCK_SITE/yt_dlp_plugins" ]` (or the venv equivalent) to the skip condition - and write
  the no-evidence marker as a third state (`ok: null` / `"unknown"`) that the health route renders as
  `[ NOT CHECKED ]`, never as installed.

### dash-mounts-ui-4 - CI gates a release on one of the seven installer test scripts
- Severity: medium
- Confidence: CONFIRMED
- Where: `.github/workflows/ci.yml:192-195` (the only `installer/tests/*.ps1` step) vs
  `tools/run_all_tests.ps1:163,170,175,181,187,193,198` (seven scripts) and `ls installer/tests/*.ps1`.
- What: `ci.yml` runs `Test-DriveMapParser.ps1` only. `Test-LicenceGate.ps1`,
  `Test-PrevRollback.ps1`, `Test-ConsoleUser.ps1`, `Test-SmbShareGone.ps1`,
  `Test-ForeignDriveMiss.ps1` and `Test-UninstallEntry.ps1` never run in CI. Since
  `tools/publish_latest.py` publishes "the newest GREEN CI run on main" (the pathway that reached the
  fleet for 0.9.61 and 0.9.70), a green CI run is not evidence that six of the installer's seven
  covered behaviours still work - including the licence gate (the thing that parked self-upgraded
  editors) and the previous-install rollback.
- Failure scenario: a change to the installer's rollback or licence handling breaks
  `Test-PrevRollback.ps1`; CI is green; `publish_latest.py` signs and publishes that run; the fleet
  takes a build whose rollback path is broken, and an editor finds it.
- Evidence: the step list above; `CLAUDE.md` itself says "the 'installer' row is SEVEN scripts ...
  this comment has now been wrong twice".
- Ledger: new.
- Suggested fix: replace the single step with a loop over `installer/tests/*.ps1` (a glob, so an
  eighth script is covered the day it lands), which is what run_all_tests.ps1's own comment asks for.

### dash-mounts-ui-5 - a same-version dashboard redeploy leaves every installed phone on the old CSS/JS for ever
- Severity: medium
- Confidence: PLAUSIBLE
- Where: `dashboard/static/sw.js` (`CACHE = 'ccsync-' + VERSION`, the `/static/` cache-first branch),
  `dashboard/src/ccsync_dashboard/ui.py:4107-4125` (`service_worker`, substitutes VERSION),
  `dashboard/templates/base.html:21,25` (unversioned `/static/*` URLs).
- What: the whole cache-invalidation story rests on "a release changes VERSION, which changes the
  worker's bytes, which drops the old cache". `/static/` is cache-first with no revalidation and the
  asset URLs carry no version query. An image-mode redeploy of the SAME dashboard version with
  changed static (a hotfix redeploy, an OTA code bundle, `--allow-replace`) produces a byte-identical
  `sw.js`; the browser never installs a new worker, the cache name never changes, and the stale
  `style.css` / `pwa.js` / `tab_memory.js` are served from cache indefinitely - to exactly the phones
  the PWA work was built for.
- Failure scenario: a CSS or JS hotfix is deployed without bumping `VERSION` (memory records
  same-day 0.7.34 -> 0.7.35 image-mode redeploys, and the redeploy recipe reuses a live digest).
  Installed phones keep the broken asset, and a hard reload does not help because the worker answers
  before the network.
- Evidence: read of sw.js and base.html - no cache-busting query, no `stale-while-revalidate`, no
  background revalidation in the `/static/` branch.
- Ledger: new.
- Suggested fix: seed `CACHE` from a stamp that changes on every deploy (the runtime id, or a hash of
  the static tree) rather than `VERSION` alone; or make the `/static/` branch stale-while-revalidate
  so a changed asset is picked up on the second load instead of never.

### dash-mounts-ui-6 - the uid/gid mismatch warning run.sh added for a second customer is dead in bind-mount mode
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/deploy/run.sh` (the `APP_UID` / `APP_GID` advisory block) vs
  `dashboard/deploy/compose.yaml` (uses `user: "{{APP_UID}}:{{APP_GID}}"` at lines 96 and 715 but
  never puts `APP_UID`/`APP_GID` in `environment:`); `compose.image.yaml:86-87` does.
- What: run.sh's warning ("files written into the tree will have the WRONG owner") is guarded by
  `[ -n "${APP_UID:-}" ]`. In the bind-mount deployment - the default, and the one the live sites use
  - neither variable is in the container environment, so the check never fires. The warning exists
  specifically for COMMERCIAL_READINESS item 12 (DSM assigns uids >= 1026), i.e. for the
  second-customer deployment most likely to be bind-mount.
- Failure scenario: a second site's compose is rendered with a uid its NAS overrides or its operator
  edits; files land under the wrong owner in `/projects`, `/broll-data` and `/music-share`; editors
  browsing over SMB see files they cannot open, with no line in the container log to explain it.
- Evidence: mechanical env-key diff of the three compose files - `APP_UID`/`APP_GID` appear in
  `compose.image.yaml` only (94 keys vs compose.yaml's 92; those two are the entire difference).
- Ledger: new.
- Suggested fix: add `APP_UID: "{{APP_UID}}"` / `APP_GID: "{{APP_GID}}"` to compose.yaml's dashboard
  `environment:` block (and to `server/`'s `compose_config()` key list, where
  `test_env_keys_match_compose` will notice).

### dash-mounts-ui-7 - htmx_errors.js's "move the refusal to the button" can be stolen by a concurrent poll
- Severity: low
- Confidence: CONFIRMED (by reading), not exercised in a browser
- Where: `dashboard/static/htmx_errors.js`, the third IIFE (`lastPath` / `htmx:afterSwap`).
- What: `lastPath` is one module-level slot set on every write's `htmx:beforeRequest` and consumed by
  the NEXT `htmx:afterSwap`, whichever element that swap belongs to. The fleet grid polls every 15 s,
  notices and transfers on their own timers, and any of those settling between the click and the
  write's own swap consumes `lastPath` and searches the WRONG subtree for `.error-banner`.
- Failure scenario: an admin clicks `[ DELETE ]` on the fortieth package row; the packages poll (or
  the notices poll) settles first; `lastPath` is cleared; the refusal banner stays two thousand
  pixels above the viewport - the exact DUI-6 symptom the code was written to fix, intermittently.
- Evidence: read of the handler. There is no correlation between the `beforeRequest` element and the
  `afterSwap` target beyond "the next one wins".
- Ledger: related to DUI-6 (fixed) - this is the residual race.
- Suggested fix: hang the path on the request's own element (a WeakMap keyed by `evt.detail.xhr`, or
  `evt.detail.requestConfig.elt` read back in `afterSwap`) rather than a single shared slot.

### dash-mounts-ui-8 - select_code_root.py counts a boot against an OTA tree it never booted
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/deploy/select_code_root.py`, `main()` - `attempts = bump_boot_attempts(version)`
  runs BEFORE `check_tree(version, runtime_id)`.
- What: the boot counter is incremented for the named version even on the boots where `check_tree`
  refuses it and the IMAGE is booted instead. Two boots with `DASH_RELEASE_PUBKEYS` temporarily unset
  (the one refusal reason that is about the environment rather than the tree) reach
  `MAX_BOOT_ATTEMPTS` and permanently rewrite `current.json` back to the previous tree with
  `reverted_reason` "failed to reach a healthy boot 2 times", which is not what happened. The
  watchdog's premise, stated in `boot_attempts`' own docstring ("a non-zero count here always means
  the last boot of this tree did not work"), is untrue on this path.
- Failure scenario: an operator redeploys image-mode and omits `DASH_RELEASE_PUBKEYS` from the same
  command (the documented redeploy recipe notes it must be set there). Two container restarts later
  the installed OTA update has been reverted and the log blames the bundle.
- Evidence: read of `main()`. The bump is unconditional once `current.json` names a version, and
  `check_tree`'s environment-shaped refusals (`DASH_RELEASE_PUBKEYS is not set`, `this image has no
  /venv/.runtime-id`) are indistinguishable from tree-shaped ones to the counter.
- Ledger: new.
- Suggested fix: bump only on the path that actually prints a volume tree (move `bump_boot_attempts`
  below `check_tree`, after `reason` is found empty), or record the refusal reason beside the count
  and do not let an environment-shaped refusal contribute to a revert.

## Coverage note
- I did not read `style.css` / `mobile.css` beyond a skim (their own suites, `test_theme_css.py` and
  `test_mobile_css.py`, are green), nor `admin_health.html`'s 129 new lines in detail, nor
  `setup.js`'s 141-line diff, nor `assignments.js` beyond the copy-plan and filter halves.
- `deploy/sftp/*` and `deploy/tailscale/*` were checked for line endings only.
  `deploy/tailscale/serve.json` is CRLF in the working tree (`attr/text=auto`); Go's JSON parser
  tolerates it, so I did not raise it.
- The suite has no test that a non-admin cannot reach a document under `/help` (finding 1); no test
  that the `/static/` service-worker cache is invalidated by anything other than VERSION (finding 5);
  no test of `run.sh`'s unblock block beyond the restart loop (`test_run_sh_restart_loop.py`); and
  `test_static_js_syntax.py`'s `node --check` half SKIPS where node is absent, leaving a
  single-error-class scanner as the gate there.
- I exercised no JavaScript in a browser; findings 5 and 7 are read-only conclusions.
- Checked and found clean: every htmx URL in every template resolves to a real route; every static
  `.js` passes `node --check`; the em-dash scan covers templates, static JS and `src/**.py` string
  literals and is green; `compose.yaml` / `compose.image.yaml` env parity is exact apart from finding
  6; `mount_broll` / `mount_music` / `mount_ytdl` / `mount_cards` all return the new
  `(status, detail)` tuple and every caller unpacks it.

## OUT OF TERRITORY
- `dashboard/src/ccsync_dashboard/app.py:1372,1388,1398,1410`: the four mount calls have no
  try/except at the call site. The mount functions guard the import and the storage probe, but
  `BrollGate(...)` / `MusicGate(...)` construction and the final `app.mount(...)` sit outside every
  `try`; an exception there would stop the dashboard booting, which CLAUDE.md says a broken checkout
  must never do.
- `dashboard/src/ccsync_dashboard/api.py:682,710`: the `pending: True` "preparing" queue rows,
  including the UPLOAD-ONLY one, are excluded from `safe_to_close`'s counts, so a project whose
  machine has never reported a media manifest reads as "Safe to close: nothing is transferring".
