# MOBILE_PLAN.md -- the dashboard on a phone, in the browser and as an Android app

Plan, 2026-08-30. Status: **PLANNED, building** (orchestrated; the work
packages below run as parallel builders in worktrees, each on its own
branch off `mobile`). As-built notes are appended per package in §9 as
they merge.

Alex, 2026-08-30: *"I also want a mobile port of the dashboard which runs in
the browser and as an app on android."*

## 0. The decision in one paragraph

The dashboard stays ONE app: the same FastAPI + Jinja + htmx pages, made to
work at 390 px with a thumb, plus a web app manifest and a service worker so
a phone can install it, plus a Trusted Web Activity (TWA) wrapper so the
same install is a real Android app in the Play sense (its own icon, its own
task, no browser chrome, signed APK). Not a second front end: 19 page routes
and ~30 partials would be duplicated and drift the same week, and every
htmx partial already IS a small server-rendered component that can be
restyled without touching its data. The Timeline Cards page did exactly
this on 2026-08-29 (`docs/ANDROID-APP.md` in MulticamPipeline): manifest
with `display` set, `requestFullscreen` on first touch, then a TWA if a
home-screen icon is not enough. The dashboard is a status board, not a
timeline, so it wants `standalone` (status bar kept) rather than
`fullscreen`, and it needs the things that page did not: a secure origin
of its own, asset links for the TWA, and polling that does not drain a
phone.

## 1. What the survey found (2026-08-30, read-only)

* **Responsive CSS today**: one `@media (max-width: 900px)` with three
  declarations (`.layout` column, `.sidebar` full width). Nothing else.
  `dashboard/static/style.css` is 1194 lines, one file, no build step.
* **Concrete phone breakers**: `table.editors` (the fleet grid, the densest
  thing on the site) with no scroll wrapper; `<div class="rule">{{ "─" * 120 }}</div>`
  in `base.html:62` and `"─" * 100` in `fleet_grid.html:5`; `.sidebar {width:300px}`;
  `.login-box {width:380px}`; `.ai-key input {min-width:22rem}`; the
  assignments matrix `220px minmax(260px, 520px)`; `.toast {max-width:340px}`.
* **Tap targets**: `.btn` has no padding at all (a 12 px text run); `.chip`
  is 11 px with zero vertical padding and is often a link; `.assign-colbtns`
  is 10 px. The 44 px guideline is missed everywhere.
* **PWA**: no manifest, no service worker, no `theme-color`, no
  `apple-touch-icon`; the viewport meta is present and right; favicon is an
  SVG + a 10.7 KB PNG. `static/` and `templates/` ship in the image AND the
  OTA code bundle (`tools/build_dashboard_bundle.py`), so new static files
  need no deploy change.
* **Security headers**: none, and no CSP, so nothing blocks a service worker
  or the one inline script in `base.html`; nothing pins that either.
* **Polling**: `/partials/transfers` every **2 s** on `/` and `/transfers`;
  bins 5 s; fleet and jobs 15 s; sidebar 30 s on every page; fleet-halt
  banner 60 s on every page. Against `--workers 1`. htmx is vendored 1.9.12
  (`static/htmx.min.js`), whose trigger filter syntax
  (`every 2s [document.visibilityState === 'visible']`) is the cheapest fix.
* **Login**: cookie `ccsync_session` (httponly, samesite=lax, `secure` from
  `DASH_COOKIE_SECURE=auto` which honours `X-Forwarded-Proto` from trusted
  proxies); anonymous htmx requests get `401 + HX-Redirect` to the page.
  Open (no-session) paths are `app._OPEN_EXACT` + `/static/`.
* **Navigation**: `partials/topbar.html` with a script-free popover drawer
  (already touch-friendly, has a `[ X ]` for touch); `partials/settings_nav.html`
  is a 12-entry strip.
* **HTTPS**: the dashboard has NO secure origin yet. `ZERO_TOUCH_PLAN.md`
  plans a Tailscale sidecar with `TS_SERVE_CONFIG`; `docs/DOCKER.md` lists
  "Serve terminating TLS on :443" as not yet authorised. The studio's NAS
  already runs `tailscale serve` inside its `tailscale` app container for
  the Timeline Cards page (`https://truenas.tail26290e.ts.net/` -> :8800),
  so the studio path is one more `serve` line. A service worker,
  installability and a TWA all REQUIRE https.
* **Alerts**: SMTP and https webhook sinks only; no Web Push. Out of scope
  here (§7).
* **Tests**: `test_settings_hub.py` renders every hub page and pins the
  strip; `test_home_layout.py` pins `/`'s section order and the 35vh
  transfers window in BOTH the template and `style.css`; `test_theme_css.py`
  pins the topbar's `flex-wrap`/`flex: 0 0 auto`/`white-space: nowrap`
  triple and the byte-identical `theme-common` block across the four
  stylesheets; `test_no_em_dash.py` scans product copy. All of these must
  keep passing or be changed on purpose with the reason in the commit.
* **Tooling on the base rig**: node 24 and Chrome are installed (the
  MulticamPipeline tests drive headless Chrome over CDP with no npm
  dependency: `E:\Projects\_worktrees\Editing-fork\Resolve\MulticamPipeline\tests\test_looks.js`
  is the pattern); no PIL in the dashboard venv; no Java, so an APK cannot
  be built here -- it is built on CI or on a machine with a JDK.

## 2. Goals and non-goals

Goals, in the order they matter:

1. Every page usable one-handed at 390 x 844 (a normal Android phone) with
   no horizontal page scroll, every control at least 44 px tall on a touch
   screen, text no smaller than 12 px, and the console look intact (the
   `[ CHIP ]` idiom, the monospace, the red).
2. Installable: Chrome's "Add to Home screen" gives a standalone app with
   the right icon and splash, that opens on `/` and survives being offline
   long enough to say so instead of showing Chrome's dinosaur.
3. An Android APK (a TWA) built from that install, signed, that a studio can
   hand to its editors; the dashboard serves the asset links the TWA needs.
4. A phone does not pay for the desktop's polling: nothing polls while the
   page is hidden, and the 2 s transfers poll is 10 s on a touch device.
5. The desktop is unchanged: at 1280 px and above every page renders pixel-
   for-pixel as before, except where a tap-target fix is invisible at mouse
   pointer widths.

Non-goals (this round): push notifications (§7); an iOS app (the PWA works
in Safari as "Add to Home Screen"; nothing Apple-specific is built beyond
the two meta tags); redesigning what pages SAY; the three SPAs (`/broll`,
`/music`, `/ytdl`) beyond keeping their topbar swap working -- they get
their own round; the Timeline Cards page (it has its own phone layout and
manifest in MulticamPipeline; §5.4 says how it coexists).

## 3. The contract every package builds to

### 3.1 Breakpoints and media

```css
/* tokens added to :root in style.css (M1) */
--bp-phone: 600px;     /* below: phone layout */
--bp-tablet: 900px;    /* below: the existing column layout */
--tap: 44px;           /* minimum hit box on a coarse pointer */
--safe-t: env(safe-area-inset-top, 0px);   /* and -b, -l, -r */
```

* `@media (max-width: 600px)` is THE phone query. `(max-width: 900px)`
  stays what it is (tablet/narrow window).
* `@media (pointer: coarse)` is THE touch query: tap targets grow here, not
  by width, so a touch laptop gets them and a narrow desktop window does
  not.
* `@media (display-mode: standalone)` is where the installed app differs
  from the tab (no "install" hint; a little more top padding under the
  status bar via `--safe-t`).
* Never `@media (hover: none)` for behaviour; only for hiding hover-only
  affordances.

### 3.2 Class vocabulary (M1 defines them in `style.css`; everyone uses them)

| class | on | means |
|---|---|---|
| `.scroll-x` | a wrapper `div` around any table or matrix that cannot stack | horizontal scroll INSIDE the element, `-webkit-overflow-scrolling: touch`, a 1 px red-dim right edge as the "there is more" hint; never the page |
| `.stack` | a `table` | below `--bp-phone` every `tr` becomes a block, every `td` a row with its `data-label` shown before it in `.muted` 11 px; `thead` hidden. Cells without `data-label` render bare. |
| `.phone-hide` / `.phone-only` | anything | `display: none` on / off below `--bp-phone` |
| `.tap` | any control (`.btn`, `.chip` that is a link, form buttons) | `min-height: var(--tap)`, `min-width: var(--tap)`, `display: inline-flex; align-items: center`, `padding` so the visible text does not move on desktop; applied automatically to `.btn` and `a.chip` under `(pointer: coarse)`, so `.tap` itself is for the exceptions |
| `.sheet` | the sidebar on a phone | a bottom sheet: collapsed to a 44 px handle `[ PROJECTS ▴ ]` fixed above `--safe-b`; tapping expands it to 60vh; the popover API, no JS |
| `.rule` | the horizontal rules | a `border-top: 1px solid var(--red-dim)` element with `height: 0`; the `"─" * N` text goes away everywhere (M1 in base, M2/M3 in their partials) |

### 3.3 Files each package OWNS (nobody else edits them)

| package | owns |
|---|---|
| M0 | `tools/mobile_sweep.js`, `tools/mobile_sweep_seed.py`, `docs/mobile/` (screenshots + `SWEEP.md`) |
| M1 | `static/style.css` (the responsive layer and the vocabulary), `templates/base.html`, `partials/topbar.html`, `partials/sidebar.html`, `partials/settings_nav.html`, `templates/login.html`, `tests/test_mobile_css.py`, `tests/test_theme_css.py` (adjust deliberately) |
| M2 | `partials/fleet_grid.html`, `partials/fleet.html`, `partials/project_detail.html`, `partials/project_bins.html`, `partials/transfers.html`, `partials/notices.html`, `partials/sync_queue.html`, `templates/fleet.html`, `templates/project.html`, `templates/transfers.html`, `templates/installer.html`, `static/mobile.css` **section `== fleet ==` only**, `tests/test_mobile_fleet.py`, `tests/test_home_layout.py` (adjust deliberately) |
| M3 | every `templates/admin_*.html`, `partials/admin_*.html`, `partials/recovery.html`, `partials/assignments*.html`, `static/site_settings.js`, `static/assignments.js`, `static/dashboard_update.js`, `static/mobile.css` **section `== admin ==` only**, `tests/test_mobile_admin.py`, `tests/test_settings_hub.py` (adjust deliberately) |
| M4 | `static/manifest.webmanifest`, `static/sw.js`, `static/pwa.js`, `static/icons/*`, `templates/offline.html`, the routes in `ui.py` for `/manifest.webmanifest`, `/sw.js`, `/offline` and their `_OPEN_EXACT` entries in `app.py`, `tests/test_pwa.py` |
| M5 | `src/ccsync_dashboard/android.py` (asset links), the `[android]` site-manifest fields in `setup_routes.py`/`site_manifest` schema, `partials/android_settings.html` + one `{% include %}` line in `admin_settings.html`, `tools/android/` (the TWA project generator + checker), `.github/workflows/android.yml`, `tests/test_android.py`, `docs/ANDROID.md` |
| M6 | `docs/MOBILE.md` (the user-facing doc), `dashboard/deploy/compose.appliance.yaml` + a `deploy/tailscale/serve.json` (`TS_SERVE_CONFIG`), the studio recipe in `docs/DOCKER.md`, `tools/check_mobile_origin.py`, `tests/test_mobile_origin.py` |

Cross-package edits are done by CONTRACT, not by touching the other's file:
M1 adds these lines to `base.html` for M4 (exact text, M4 makes the targets
exist):

```html
<link rel="manifest" href="/manifest.webmanifest">
<meta name="theme-color" content="#0a0a0d">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<link rel="apple-touch-icon" href="/static/icons/icon-180.png">
<script src="/static/pwa.js" defer></script>
```

and changes the viewport to
`<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">`.
M2 and M3 add `static/mobile.css` rules ONLY inside their own marked
section (the file is pre-created with the markers on the `mobile` branch);
M1 adds `<link rel="stylesheet" href="/static/mobile.css">` after
`style.css` in `base.html`.

### 3.4 Rules that apply to every package

* **No em dashes in user-visible text** (`CLAUDE.md`, `tests/test_no_em_dash.py`).
* The `[ CHIP ]` idiom, the monospace face and the token colours are the
  brand; a phone layout changes size, wrapping and hit boxes, never the
  vocabulary.
* `test_theme_css.py`'s `theme-common` block stays byte-identical across
  the four stylesheets: do not put phone rules inside it.
* Every htmx poll a package owns gets the visibility filter
  (`hx-trigger="every 15s [document.visibilityState === 'visible']"`);
  M4's `pwa.js` additionally cancels any in-flight poll on `visibilitychange`
  and slows `every 2s` to `10s` on `(pointer: coarse)` by rewriting the
  attribute once at load -- so a partial that forgets the filter still
  behaves. Both belts.
* Nothing is added to `_OPEN_EXACT` except what a browser must fetch with
  no session: the manifest, the icons (under `/static/` already), `sw.js`,
  `/offline`, `/.well-known/assetlinks.json`. None of them may carry a
  secret or a session-specific value.
* Tests run with the main checkout's venv from the worktree's component
  dir (`tests/conftest.py` puts the worktree's `src` first):
  `cd <worktree>\dashboard && E:\Projects\resolve-remote-sync\dashboard\.venv\Scripts\python.exe -m pytest tests -q`.
  The whole dashboard suite must stay green.
* Commit on the package's branch with exact paths; do not push; do not
  merge; do not touch `docs/MOBILE_PLAN.md` (the orchestrator appends §9).

## 4. The work packages

### M0. The sweep: screenshots and overflow checks at phone width

The proof for every other package. `tools/mobile_sweep.js` (node, no
npm dependencies, the CDP pattern from MulticamPipeline's
`tests/test_looks.js`) starts headless Chrome, logs in to a dashboard URL
with a username and password (posts `/login` with the CSRF token it reads
from the page), and for each page in a list visits it at **390 x 844,
DPR 3** and **768 x 1024**, waits for htmx to settle (`htmx:afterSettle`
or 1.5 s), and records: a PNG to `docs/mobile/<w>/<page>.png`, whether
`document.documentElement.scrollWidth > window.innerWidth` (a horizontal
overflow is a FAIL), the smallest bounding box among `button, a.chip, .btn,
input, select` that is visible (below 44 px on either axis is a WARN, listed
with its selector), and the smallest computed font size in use (below 12 px
is a WARN). It prints a table and exits non-zero on any FAIL.

`tools/mobile_sweep_seed.py` starts a dashboard on a free port with a
temporary data dir and ENOUGH DATA to make the pages honest: three editors,
five machines with lanes in mixed states (one halted, one breaker-tripped,
one with a running job at 37 %), two projects with bins, a transfers list
with 12 rows, four queued jobs (one forced, one targeted -- see
`docs/TIMELINE-CARDS-INTO-CCSYNC.md` §10 if that has merged, otherwise plain),
notices and an alert, packages published. Reuse `dashboard/tests/conftest.py`'s
fixtures and `db.py`'s writers; the point is the pages, not the data.
`python tools/mobile_sweep_seed.py --port 8499` prints the URL and the
admin password and stays up until Ctrl+C.

Deliverables: the two tools, `docs/mobile/SWEEP.md` (how to run it, what a
FAIL means, the page list), and the BASELINE run against the `mobile`
branch before any other package merges (commit the PNGs at 390 only, under
`docs/mobile/baseline/`; they are the "before"). The page list is every
route in §1's table except `/setup`, `/download*`, `/admin/alerts/preview`
and `/admin/site*`.

### M1. The chrome: base layout, navigation, tokens, tap targets, login

* `style.css`: the tokens (§3.1), the vocabulary (§3.2), the phone query
  block at the END of the file (before `theme-common`), the coarse-pointer
  block. `.btn` gets padding that keeps its desktop text position (`padding:
  0; ` today -> a hit box via `::before` inset or `padding + negative
  margin`; verify at 1280 px that nothing shifts). `.chip` links get the
  same under `(pointer: coarse)`.
* `base.html`: the meta/link lines from §3.3, the `.rule` element instead of
  the 120 box-drawing characters, `mobile.css` linked, the layout wrapper
  gets `padding-bottom: calc(var(--tap) + var(--safe-b))` on phones so the
  sheet handle never covers content.
* `topbar.html` at phone width: the brand and the drawer button on one 44 px
  row; the chips (`[ N PROBLEMS ]`, `[ N ALERTS ]`, the user name) move
  INTO the drawer head; `flex-wrap` stays (the test pins it). The drawer
  itself is already a popover: make it full-height, 86vw, with 44 px rows
  and the `[ X ]` reachable by a thumb (bottom-right on phones).
* `sidebar.html` -> `.sheet` on phones (§3.2). The 30 s poll gets the
  visibility filter.
* `settings_nav.html`: a horizontally scrolling `.scroll-x` strip of 44 px
  chips on phones, the current one scrolled into view (CSS
  `scroll-snap` + the `nav_current` class; no JS).
* `login.html`: `.login-box` `width: min(380px, 100% - 2rem)`, inputs
  `font-size: 16px` on phones (Android and iOS zoom into anything smaller),
  the SSO button 44 px.
* Tests: `tests/test_mobile_css.py` pins the tokens, the three media
  queries, the vocabulary classes existing, `.rule` having no text, the
  meta lines in `base.html`, the visibility filter on the sidebar poll;
  `test_theme_css.py` is extended, never weakened.

### M2. The editor's pages: fleet, project, transfers, installer

* `fleet_grid.html`: the machine table becomes `table.editors.stack` with
  `data-label` on every `td`; the lane chips wrap; the `"─" * 100` becomes
  `.rule`; the project `.cards` grid goes to one column below `--bp-phone`
  (`minmax(320px, 1fr)` already does, but check the card's inner rows). The
  fleet-halt / breaker / stopped banners become full-width blocks with the
  action button on its own 44 px row.
* `fleet.html` / `transfers.html`: the transfers window (35vh, pinned by
  `test_home_layout.py`) keeps its height; the 2 s poll gets the visibility
  filter AND `hx-trigger="every 10s [...]"` inside a
  `<template class="phone-only">`-free way: since htmx reads one attribute,
  the rule is "2 s on the desktop, and `pwa.js` (M4) rewrites it to 10 s on a
  coarse pointer before htmx processes the node". M2 adds the filter only.
* `project_detail.html`, `project_bins.html`, `sync_queue.html`,
  `notices.html`: stack or scroll-x per §3.2, whichever keeps the data
  readable; long paths get `overflow-wrap: anywhere` and a `title`.
* `installer.html`: the two-platform chooser stacks; the download button is
  44 px; on Android the page says which one this phone should send to the
  editor's computer (it cannot run the companion itself) -- one sentence.
* Tests: `tests/test_mobile_fleet.py` renders `/`, `/project/x`,
  `/transfers`, `/installer` with the conftest fixtures and asserts the
  vocabulary classes and `data-label`s are present, no `"─" *` remains, and
  every poll in these templates carries the visibility filter.

### M3. The admin pages

`admin_jobs`, `admin_users` (296-line partial), `admin_packages` (347),
`admin_settings` (181 + `site_settings.js` 808), `admin_assignments`
(the matrix: `.scroll-x`, sticky first column, the 10 px `.assign-colbtns`
to 12 px and 44 px hit boxes), `admin_audit`, `admin_alerts`,
`admin_invariants`, `admin_protection`, `admin_recovery` (196), `setup`
is excluded. Same recipe: `.stack` where rows are records, `.scroll-x`
where columns carry meaning, 44 px controls, forms one column with
`font-size: 16px` inputs on phones, `.ai-key input {min-width: 22rem}`
-> `width: 100%`, every poll filtered, no `"─" *`. The jobs page's
`[ CANCEL ]` and the users page's session/token actions are the controls
an admin most wants on a phone: they get `.tap` and a confirm that fits
the screen (`hx-confirm` text under 90 characters).
Tests: `tests/test_mobile_admin.py` renders every admin page as admin and
asserts the same properties as M2's; `test_settings_hub.py` keeps passing.

### M4. The PWA: manifest, icons, service worker, polling discipline

* `static/manifest.webmanifest`: `name` "CC Sync", `short_name` "CC Sync",
  `id` "/", `start_url` "/", `scope` "/", `display` "standalone",
  `display_override` ["standalone", "minimal-ui"], `orientation` "any",
  `background_color` and `theme_color` `#0a0a0d`, `icons` 192 and 512 PNG
  (`purpose: any` and a separate `maskable` pair), plus the SVG. `lang` "en".
  The `name` may be the site manifest's `brand_product` if `ui._render`'s
  brand values are available at serve time -- then the route renders the
  manifest through Jinja with `application/manifest+json`; the static file
  is the fallback.
* Icons: `static/icons/icon.svg` (the brand mark: the `//` idiom in the red on
  the panel black, safe within the maskable 80 % circle), and PNGs at 180,
  192, 512 (any) and 192, 512 (maskable). No PIL: render them with headless
  Chrome over CDP (`Page.captureScreenshot` of the SVG at the size; the M0
  harness pattern) via `tools/make_icons.js`, commit the PNGs, and pin their
  dimensions in the test by reading the PNG IHDR (16 bytes, stdlib).
* `static/sw.js`: versioned by the dashboard `VERSION` (the route renders it
  with the version in a comment so a release changes the byte content and
  the browser updates); precaches `/offline`, `style.css`, `mobile.css`,
  `htmx.min.js`, `pwa.js`, the icons; **network-first** for navigations
  with the offline page as the fallback; **cache-first** for `/static/`;
  **never touches** `/api/`, `/partials/`, `/cards/`, `/broll/`, `/music/`,
  `/ytdl/`, `/login`, `/logout*` (pass-through, no cache). `skipWaiting` +
  `clients.claim`. Served at `/sw.js` (scope `/` needs the root path) with
  `Service-Worker-Allowed: /` and `Cache-Control: no-cache`.
* `static/pwa.js` (deferred, runs on every page): registers the SW when
  `isSecureContext`; on `visibilitychange` -> hidden, aborts in-flight htmx
  requests (`htmx.trigger(document.body, 'htmx:abort')` per polling
  element) and on visible triggers one immediate refresh of each polled
  element; on `(pointer: coarse)` rewrites `hx-trigger="every 2s"` to
  `every 10s` and `every 5s` to `every 15s` BEFORE `htmx.process` (it is
  deferred and htmx is deferred; order the script tags so `pwa.js` runs
  first, or hook `htmx:load`); listens for `beforeinstallprompt`, stashes
  it, and shows a `[ INSTALL ]` chip in the drawer foot (M1 leaves an empty
  `<span id="install-slot" class="phone-only"></span>` there by contract)
  that calls `prompt()`; hides it under `display-mode: standalone`.
* `templates/offline.html`: the console look, one sentence, a `[ RETRY ]`.
* `app.py`: `/manifest.webmanifest`, `/sw.js`, `/offline` in `_OPEN_EXACT`.
* Tests: `tests/test_pwa.py` -- manifest served anonymously with the right
  content type and valid JSON, every icon it names exists with the pinned
  size, `sw.js` served with the header and contains the `VERSION`, `/offline`
  renders anonymously, `sw.js` source never lists `/api/` or `/partials/` in
  a cache list (a text assertion), `pwa.js` rewrites exactly the two
  intervals.

### M5. Android: the TWA, asset links, the build

* **Asset links**: `GET /.well-known/assetlinks.json` (open) answers
  `[]` until the site has an Android package configured, then the standard
  `delegate_permission/common.handle_all_urls` statement for
  `[android] package_name` and `sha256_cert_fingerprints` (a list) from the
  site manifest (`setup_routes` schema + `site_manifest` defaults). Served
  `application/json`, `Cache-Control: max-age=3600`. Nothing else at
  `/.well-known/`.
* **Settings**: `partials/android_settings.html` (package name, fingerprints
  textarea one per line, a `[ CHECK ]` that fetches the site's own
  `/.well-known/assetlinks.json` and Google's digital asset links check URL
  is NOT called from the server -- print the URL for the admin instead),
  included in `admin_settings.html` under an `[ ANDROID ]` heading;
  `site_settings.js` is M3's -- so the partial is a plain form posting to
  `/api/v1/setup/android` (M5's route) with the CSRF hidden field, htmx
  target the partial.
* **The TWA project**: `tools/android/twa_manifest.py` writes a Bubblewrap
  `twa-manifest.json` for a given `--origin https://...` (package name from
  the origin reversed, e.g. `net.ts.tail26290e.truenas.ccsync`, overridable),
  `startUrl "/"`, `display standalone`, the icon and colours read from the
  live `/manifest.webmanifest`, `enableNotifications false`, `fallbackType
  customtabs`, `shortcuts []`. `tools/android/build_apk.sh` runs
  `npx @bubblewrap/cli init --manifest <origin>/manifest.webmanifest
  --directory <out>` and `bubblewrap build --skipPwaValidation` (Bubblewrap
  installs its own JDK and Android SDK on first run; `--skipPwaValidation`
  because the origin is on a tailnet Lighthouse cannot reach), signing with
  a keystore whose path and passwords come from env
  (`CCSYNC_ANDROID_KEYSTORE`, `..._KEYSTORE_PASSWORD`, `..._KEY_ALIAS`,
  `..._KEY_PASSWORD`), never from the repo; prints the SHA-256 fingerprint
  the admin pastes into settings. `tools/android/check_assetlinks.py
  <origin> <fingerprint>` fetches the site's statement and says whether the
  fingerprint is in it.
* **CI**: `.github/workflows/android.yml`, `workflow_dispatch` with inputs
  `origin` and `package_name`; ubuntu runner; installs node 20, runs the two
  tools with a DEBUG keystore it generates (so the artifact is installable
  for testing and its fingerprint is printed in the step summary), uploads
  the APK and the AAB as artifacts. A release-signed build uses the same
  workflow with the four secrets present (same posture as
  `release-windows.yml`'s signing: unsigned unless the secrets are there,
  and it says so). The workflow must run green once from the builder's
  branch (`gh workflow run android.yml --ref <branch> -f origin=https://example.invalid`
  is not enough -- Bubblewrap fetches the manifest; point it at a GitHub
  Pages or a raw-content manifest the builder commits under
  `tools/android/fixture/` and serves with `python -m http.server` in the
  job).
* Tests: `tests/test_android.py` -- the route open, empty by default,
  populated from settings, content type, cache header; the twa-manifest
  generator output against a fixture manifest; the checker on a served
  fixture.
* Docs: `docs/ANDROID.md` -- the whole path for a studio admin: https first
  (§M6), build the APK (CI or a machine with node), paste the fingerprint,
  verify with the checker, install on the phone (sideload; Play Store is
  its own doc later), what "the app shows a URL bar" means (asset links not
  verified) and how to fix it.

### M6. The secure origin, and the user doc

* The studio path, today: on the NAS, inside the `tailscale` app container,
  `tailscale serve --bg --https=8443 http://192.168.0.102:8480` (8443 is
  taken by an unrelated Funnel per the 2026-08-29 note -- use the next
  free, `--https=9443`, and say so), giving
  `https://truenas.tail26290e.ts.net:9443/`; `dashboard_url` in `site.toml`
  changes to it; `DASH_COOKIE_SECURE=auto` turns `secure` on by itself
  behind the proxy (`auth.cookie_secure` honours `X-Forwarded-Proto` from
  trusted proxies -- verify `tailscale serve` sets it and that the trusted
  proxy list covers the tailscale container's address; if not, the exact
  setting to add). The companions' CORS allow-list is built from
  `dashboard_url` (`docs/COMMERCIAL_READINESS.md` item 156): a changed URL
  is a companion restart, say so.
* The product path: `dashboard/deploy/tailscale/serve.json` for
  `TS_SERVE_CONFIG` (the `ZERO_TOUCH_PLAN.md` sidecar), wired into
  `compose.appliance.yaml`'s `tailscale` service as a bind-mounted file +
  env, with the same TLS-on-443 posture `docs/DOCKER.md` §"not authorised"
  describes -- so add it BEHIND an explicit `DASH_TAILSCALE_SERVE=1` in the
  compose env, off by default, and update that DOCKER.md paragraph to say
  the switch exists.
* `tools/check_mobile_origin.py <url>`: https? certificate valid? manifest
  reachable anonymously and well-formed? `sw.js` served with the header?
  `/.well-known/assetlinks.json` reachable? `/api/v1/health` says
  `version`? One line per check, exit non-zero on the first FAIL; this is
  what the runbook in `docs/MOBILE.md` tells the admin to run.
* `docs/MOBILE.md`: the user-facing document. What works in a phone
  browser, how to install (Android Chrome, iOS Safari), the app (points at
  `docs/ANDROID.md`), what polls when, what does not work offline, the
  https prerequisite and the studio recipe above, and the checker. Written
  from this plan's contracts; updated by the orchestrator after the merges
  with what actually shipped.
* Tests: `tests/test_mobile_origin.py` runs the checker against a
  TestClient-backed fake (monkeypatch its fetch) for each verdict.

## 5. Sequencing, merging, versions

* **Round 1** (parallel): M0-M6, seven builders, seven worktrees under
  `E:\Projects\_worktrees\ccsync-m0` .. `ccsync-m6`, branches `mobile-m0` ..
  `mobile-m6` off `mobile` (which is `main` + this plan + the `mobile.css`
  skeleton).
* **Merge order**: M1 first (the vocabulary), then M2, M3 (their CSS lives
  in their own `mobile.css` sections; template conflicts with the
  fleet-force branch's `admin_jobs.html`/`fleet_grid.html` chip lines are
  resolved by the orchestrator), then M4, M5, M6, then M0 last so its
  baseline PNGs are the pre-merge state and its sweep runs on the result.
* **Round 2**: the M0 sweep against merged `mobile`; every FAIL and WARN
  becomes a fix-up task handed back to the package that owns the file.
  Round 2 ends when the sweep is clean at 390 and 768 on every page.
* **Version**: dashboard `0.7.24` at the merge to `main` (after fleet-force's
  `0.7.23`); the code bundle carries `static/` so this is an OTA release for
  bind-mount sites and needs no image change (no lock change here -- keep
  it that way: a lock edit makes it a runtime update, `docs/RELEASE.md`).
* **Then** the studio steps: serve on 9443, `dashboard_url`, the checker,
  install on Alex's phone, build the APK on CI, paste the fingerprint.

## 6. Risks, named

* **The fleet grid is a table of chips.** Stacking it on a phone makes a
  machine a card of ten rows; five machines is a long scroll. Acceptable:
  the alternative (horizontal scroll) hides the problem chips off-screen,
  and the point of the page on a phone is "is anything red".
* **Polling on `--workers 1`.** A phone in a pocket holding an htmx poll is
  a connection the base rig's editors share. The visibility filter is the
  fix, and `pwa.js`'s abort-on-hidden is the belt for a partial that
  forgot it. The 2 s transfers poll stays 2 s on the desktop by design.
* **The service worker and login.** A network-first navigation strategy
  never serves a cached page to a signed-out phone (the 303 to `/login` is
  a network response); the SW must never cache `/login` or anything under
  `/api/`. `test_pwa.py` pins this in text; a review reads `sw.js` by eye
  too.
* **TWA verification is silent when it fails**: the app opens with a URL
  bar and nothing says why. `docs/ANDROID.md` leads with that symptom; the
  checker and the settings `[ CHECK ]` exist for it.
* **Bubblewrap on CI** is the one step nobody here has run. It is
  workflow_dispatch, it fails loudly, and the studio can build on a laptop
  with node instead; the plan does not depend on it.
* **The Timeline Cards page** has its own manifest with `scope: "."` under
  `/cards/`; the dashboard's manifest has `scope: "/"`. Two installs, two
  icons, by design (the cards page wants `fullscreen`, the board wants
  `standalone`); the dashboard's SW passes `/cards/` through untouched.

## 7. Later, not now

* Web Push for alerts (VAPID keys in the site secrets, a `push_subscriptions`
  table, the SW's `push` handler, a fourth alert sink). Real work; wanted
  after the board is good on a phone.
* The three SPAs (`/broll`, `/music`, `/ytdl`) at phone width and inside the
  SW's scope (they are pass-through now).
* Play Store listing (the AAB the workflow uploads is the input).
* iOS specifics beyond the two meta tags.

## 8. What Alex has to do, after the merge

1. On the NAS: the `tailscale serve` line from §M6; `dashboard_url` in
   `site.toml`; restart the companions (CORS).
2. `python tools/check_mobile_origin.py https://truenas.tail26290e.ts.net:9443`
   until every line is OK.
3. Phone: open it in Chrome, sign in, `⋮` -> Add to Home screen. That is the
   browser deliverable done.
4. `gh workflow run android.yml -f origin=https://truenas.tail26290e.ts.net:9443`
   (or `tools/android/build_apk.sh` on a laptop with node), install the APK,
   paste the printed fingerprint into Settings -> ANDROID, reopen the app:
   no URL bar. That is the app deliverable done.

## 9. As built

(appended per package as they merge)
