# FABLE_REVIEW_REPLACE: final adversarial review of the `ui-replace` branch

Fable reviewer, 2026-09-25, worktree branch `ui-replace` (uncommitted working
tree over `d920ff7`; 305 files, +8812 / -22891). Authority: the owner on
`docs/UI_PORT_REVIEW_2026-09-25.md`: "Fix all, also we don't need to maintain
the switch to the old UI. This is completely replacing the old one." Nothing
committed, no version bumped.

## Verdict

**PASS, with seven small defects fixed in this pass and three notes for the
next stage.** The 38 review findings are closed (37 re-verified live or in
code by me, 1 verified in code only, see the table). The classic look and the
switch are gone with nothing load-bearing dangling: the route census shows
six classic-only fragments removed and nothing added, the control census
shows every classic control target reached by a new template or script, the
settings keys, cookies, headers, static files and JS are gone, and the
remaining mentions are history comments, the deliberate `RETIRED_KEYS`
handling and old plan documents. Live-site safety holds: a stored
`ui_terminal_groups` row is dropped at boot and a PUT or an undo that still
names it is not refused for it, the service worker's cache name changed, a
tab drawn by 0.7.62 (either look) is told to reload before any write lands,
the SPAs carry `html.cc` in their markup and clear the retired cookie, the
share page is untouched, and the companion's only dashboard link (`/help`)
still resolves. Eleven suites green (dashboard 5924 with my test added).

## Method

- Seeded dev server from THIS worktree (`tools/mobile_sweep_seed.py`,
  `DASH_DEV_INSECURE=1`, port 8499), jsmith given a known password through
  `local_users.set_password`; music mounted (`/ytdl/` is 404 in the seed
  because `youtube_download` is off, `/broll/` and `/cards` are not mounted).
- Headless Chromium through the system Python's Playwright, at 1440, 768 and
  390 (mobile and touch emulation, plus a 390 desktop context for the
  layout-viewport trap the review named in settings-3), as admin and as
  editor. Every page, `/?as=`, the help documents, `/setup`, `/offline`,
  `/download`, `/login`, `/music/`.
- On every load: 5xx in any subrequest, console errors and exceptions,
  page-level and element-level sideways overflow outside `.scroll-x`,
  `aria_snapshot` of the whole body scanned for glyph or snake_case names,
  text under 12 px at 390, home tap targets under 44 px on touch, computed
  HUD rules, headline titles, tree position, `tr.drawer`.
- httpx probes with the page's CSRF token: the stale gate (GET and POST,
  no header and the 0.7.62 group header), every dead route, `mode=on/off`
  twice each against the DB and the audit table, the full 17-field alerts
  save, the dismiss trigger, `/go/*`, `/sw.js`, `/offline`.
- Two route-table censuses (main and worktree, walking FastAPI's
  `_IncludedRouter` wrappers) and a control census (every `hx-*`, `action`,
  `href` and `fetch()` target in main's classic templates and scripts
  against the worktree's).
- The whole dashboard suite in six shards, broll/web, music/web, ytdl/web
  and tools, with the main checkout's venvs.
- Scratch scripts live in the session scratchpad (`census_routes.py`,
  `census_controls.py`, `http_probe*.py`, `sweep.py`, `interact*.py`,
  `spa_probe.py`), not in the tree.

## The 38 findings

| Finding | Verdict | How I checked |
|---|---|---|
| home-project-1 (high) | CLOSED | 1440: Browse answers into `#roots-browse-u1` at 986 x 124; three `tr.row-drawer`, zero `tr.drawer` on both project pages at every width; no phone-side fixed box. |
| home-project-2 (high) | CLOSED | Tree checkbox posts `...toggle?view=tree&mode=off&as=jsmith` (ticked) / `mode=on` (unticked); the answer carries `HX-Trigger: cc-plan-changed` and the browser at once re-read `/partials/home-queue` and `/partials/home-transfers`. Server side: `mode=off` twice and `mode=on` twice each leave the DB unchanged on the second call and write no `fleet_audit` row for it; a stale `POST` without the look header lands nothing. |
| settings-1 (high) | CLOSED | The rendered `#alerts-form` has 17 `alerts_*` fields; posting all 17 answers 200 "saved." (cap is `len(SETTING_KEYS)+4`). |
| mechanism-1 | GONE | `app.stale_page_gate` answers 200 empty + `HX-Refresh` before the route: verified with a POST toggle that changed nothing. |
| mechanism-2 | GONE | No `HEADER_FLOOR`, no groups; residual rollback cost noted below. |
| mechanism-3 | GONE | No `base.html`, no Want header anywhere (`grep`). |
| mechanism-4 | GONE | `html.cc` is markup in all three SPA index files; the cookie is only ever cleared. |
| home-project-3 | CLOSED | Live: Cancel and Escape on the "This removes ..." dialog both leave the box ticked. |
| home-project-4 | CLOSED | Code: `_owes` counts `plan.count`, `_is_silent` uses `health._silence`. Live with tchen's tick deleted: "online 0 / 0, no computer has a project ticked", neutral class. |
| home-project-5 | CLOSED | Live: "moving 581.1 GB, 2 projects catching up" and "in sync 0 / 2" on a seed with no completion rows. |
| home-project-6 | CLOSED | `#win-projects` top at 390: 602 (admin), 540 (jsmith); at 768: 405; was ~10,000. |
| home-project-7 | CLOSED | `.hl` title equals the sentence; `white-space: normal`, clamp 3 at 1440, unclamped at 390. |
| home-project-8 | CLOSED | `/?as=jsmith`: the grid poll is `/partials/fleet?as=jsmith`, transfers `/partials/home-transfers?as=jsmith`. |
| home-project-9 | CLOSED | Home and project scrollWidth 768 at 768. |
| home-project-10 | CLOSED | No home control under 43 px at 390 touch (tick, name, summaries, fold, keys, `a.act`, sub-window summaries). |
| home-project-11 | verified in code | `#fleet-diagnostics[data-reveal]` present on every home render; the seed has no diagnostics bundle to press. |
| settings-2 | CLOSED | `row_version` hidden field in the rollback form; `partial_admin_package_current` keys `error_for` to it; banner fallback in `_packages_and_feed`. |
| settings-3 | CLOSED | 390 with NO mobile emulation: assignments, packages, setup, users, home all within 390. |
| settings-4 | CLOSED | `.scroll-x` inside `.scroll-y.hl-list` around sent.log; no element overflow at 768. |
| settings-5 | CLOSED | Live: features tab, link, features tab, link: the AI providers panel opens both times. |
| settings-6 | CLOSED | Live: dismiss through the dialog took "open findings (54)" to "(53)" and the notices list 16 to 15 with no reload. |
| everyday-apps-1 | CLOSED | Live as jsmith: queue Untick posts `mode=off`; the page at once re-read both `/partials/account/computer` windows; the stale keys are gone; DB shows one row left. |
| everyday-apps-2 | CLOSED | `.hud-meta` clip 0 and `.hud-name` 62 to 69 px on every page at 1440 / 768 / 390; hud-common md5 identical in all four sheets. |
| everyday-apps-3 | CLOSED | `.hud-more-btn` computes `none` at 1440 and 390, `flex` at 768; every `.hud-hide-sm` is `none` at 390. |
| everyday-apps-4 | GONE | No cookie is written anywhere (`grep`), none present in the browser after `/music/`. |
| everyday-apps-5 | CLOSED | `.doc pre` overflow-x auto; `/help`, `/help/EDITOR_SETUP.md`, `/help/API.md` at 390 within the viewport (the element census only sees `CODE` inside those scrolling `pre`s). |
| everyday-apps-6 | CLOSED | `/transfers` at 390 touch: adopted tags (data-tip, no title) are 44 px. |
| a11y-copy-1 | CLOSED | `aria_snapshot` on 26 admin pages, 6 editor pages, 3 widths: no button, link, tab, radio or checkbox name carries a glyph. |
| a11y-copy-2 | CLOSED | `#cc-confirm` described by `#cc-confirm-q` ("Stop jsmith signing in? ..."); SPA `ccSpa.confirm` dialog: aria-label "Are you sure?", described by `#cc-spa-confirm-q`, focus on Cancel. |
| a11y-copy-3 | CLOSED (code + HUD) | `cc_spa.js` sets `aria-description` on adoption and has focusin/focusout; the injected HUD brand shows the adopted description. The seed's music library is empty, so an in-app control's focus tip was not re-measured here (the F-a11y verifier measured it on data). |
| a11y-copy-4 | CLOSED | 1440: focusing "Send a test" shows its tip; a Tab pass shows a tip on 5 of the 5 titled stops. 390 touch: 39 `.tip-btn` on home ("What Stop the fleet does"); tapping opens `#chip-sheet` visibly (390 x 183, hit-tested on top). |
| a11y-copy-5 | CLOSED | No heading in any `aria_snapshot` starts with `>`, `//`, `##` or holds `a_b` (the one hit is a doc's own heading text in `/help/API.md`). |
| a11y-copy-6 | CLOSED | Fold buttons are named after their window; repeated keys carry the subject (from the AX scan and the F-a11y verifier's names). |
| a11y-copy-7 | CLOSED | No rendered text under 12 px on any page at 390 (touch). |
| a11y-copy-8 | CLOSED | No `hx-confirm` on `/admin/users` carries RESUME / DISABLE / DELETE / REMOVE in capitals; Packages says `Press "Check now"`. |
| a11y-copy-9 | CLOSED | No "machine" in `/admin/settings`' visible text or help JSON. |
| a11y-copy-10 | CLOSED | `/admin/alerts/preview`: no "since never"; "has never been able to check" and "(since when is not known)" present. |
| a11y-copy-11 | CLOSED | Placeholders read `2026/Show/Episode/Interviews/...` and `Interviews/Guest`. |

## The collapse: is the classic look and the switch fully gone?

- **Routes.** Route table diff main -> worktree: 278 -> 272. Removed:
  `GET /partials/admin/diagnostics`, `/partials/fleet-halt-banner`,
  `/partials/notices`, `/partials/queue`, `/partials/sidebar`, `/ui/preview`.
  Nothing added or renamed. All six answer 404 live; `/go/*` keeps its
  seven panels (`notices`, `collector`, `diagnostics`, `admin-fleet-halt`,
  `ai-providers`, `restore`, `dashboard-update`).
- **Controls.** Every URL a classic template or classic script reached is
  reached by a new template or `static/cc` script except the six routes
  above (each replaced: home-queue, projects-tree, home-problems +
  health-notices, halt-line, health-diagnostics + computer-answer) and two
  false alarms (the project-setup browse URL is built in a `{% set %}`, the
  site save goes through `api()`). Nothing an editor or admin could do at
  main is unreachable now.
- **Settings keys.** `ui_terminal_groups` / `ui_preview` exist only as
  `site_store.RETIRED_KEYS` (dropped at boot, filtered on PUT, and after
  this pass filtered on undo). Not in KEYS, the manifest, `/api/v1/site`,
  the export, `Settings`, or any `DASH_SITE_UI_*` read.
- **JS / CSS / templates.** `ui_variant.py`, `ui_variant_settings.py`,
  `tools/ui_variant.py`, `base.html`, `templates/cc/`, `style.css`,
  `mobile.css`, `ui_groups.js` and the seven frozen classic scripts are
  gone; `static/cc/` is the only script and sheet set and `shell.html` the
  only shell. No `X-CC-UI-Want`, `data-ui-*`, `hud_next`, `ui_look_*`,
  `ccsync_ui` writes. The SPA sheets keep their classic half because the
  public share page loads `../assets/style.css` (R22, D10); `share.html`,
  `share.css`, `share.js` and `routes_share.py` are untouched.
- **Docs.** `CLAUDE.md` and the port plan say the new truth. Fixed in this
  pass: `dashboard/README.md` (CSRF meta "in base.html"),
  `docs/SELF_DIAGNOSIS.md` (the notices partial and route),
  `docs/legal/TELEMETRY.md` (the dead `/partials/admin/diagnostics` row).
  Left as history: `docs/MOBILE_PLAN.md`, `docs/ACCOUNT_PAGE_FEATURES.md`,
  the sweep and hunt ledgers, `dashboard/design/*.html`.
- **Tests.** `ui_variant_support.py` and the two mechanism files are gone;
  `test_every_template_renders.py` replaces them. Fixed: `test_auth.py`
  drove the login redirect through the dead `/partials/sidebar` (it passed
  only because the login gate runs before routing); it names
  `/partials/projects-tree` now. Cosmetic and left: several test docstrings
  still narrate the classic look as history.

## Live-site safety on deploy

- **Stored `ui_terminal_groups` row:** `drop_retired_keys` runs in the
  lifespan after the env seed (`app.py`), pinned by
  `test_a_stored_look_setting_is_harmless`. A PUT that still names it is
  filtered. **Fixed here:** `POST /api/v1/admin/site/undo-last-change`
  handed the newest history entry's `before` values straight to
  `validate_many`, which refuses the retired key ("not a recognised site
  setting", 422), so a site whose last recorded change was the switch (the
  likeliest last change on a 0.7.62 site) could not undo anything. It now
  drops retired keys like the PUT does: the switch alone gets the existing
  409 "nothing to restore", a mixed entry restores its other keys. Test
  added to `test_every_template_renders.py`.
- **Cached service worker:** `/sw.js` is served with
  `CACHE = 'ccsync-<VERSION>-terminal-1'`, no `style.css` / `mobile.css` in
  its precache, hashed `cc/` urls in `CC_PRECACHE`; `activate` drops every
  other `ccsync-` cache. `/offline` renders on the shell with hashed sheets.
- **Open tabs:** an htmx request with no `X-CC-UI` (a classic 0.7.62 tab)
  or with `X-CC-UI: chrome,home` plus Gen/Sig (a terminal 0.7.62 tab) gets
  200 empty + `HX-Refresh: true` for GET and POST, before the route and
  before any write. Every classic page polled its sidebar every 30 s, so a
  wall display reloads within that. An unauthenticated stale request still
  gets the login `HX-Redirect` (test_auth).
- **The SPAs:** `/music/` at 1440 and 390: `html.cc cc-chrome`, the real
  HUD injected (`data-dash-topbar`), no look menu, no cookie, no overflow,
  no console error except the base rig's own companion refusing the seed's
  origin on `127.0.0.1:8899/music/status` (the loopback guard doing its
  job). The topbar fetch is a plain `fetch`, so the stale gate never sees
  it. `cc_spa.js` is byte-identical in the three apps.
- **The share page:** untouched (D10); its sheet is the SPA's own
  `style.css`, whose classic half is kept for it.
- **Companion:** its only dashboard path is `<dashboard_url>/help`
  (`ui_copy.py`, `settings_window.py`), which renders; the loopback API and
  origin allow-list are not in this diff.
- **Rollback:** to 0.7.62 is safe (its overlay reads `X-CC-UI: terminal` as
  an unknown set and answers HX-Refresh; the groups row is gone so it boots
  classic). To 0.7.61 or older, an open terminal tab is fed classic
  fragments until it is reloaded; that is the ordinary cost of a rollback
  across a look change and was already in C-collapse.

## Fixed in this pass (small, clear)

1. `dashboard/src/ccsync_dashboard/app.py`: `/ui/preview` was still in
   `_OPEN_GET_ONLY` (a no-session exemption for a route that no longer
   exists). Removed.
2. `dashboard/src/ccsync_dashboard/setup_routes.py`: undo-last-change drops
   `RETIRED_KEYS` from the values to restore (above), with a test.
3. `dashboard/tests/test_auth.py`: the login-redirect test names a live
   fragment (`/partials/projects-tree`) instead of the dead sidebar.
4. `dashboard/README.md`: the CSRF meta lives in `shell.html`.
5. `docs/SELF_DIAGNOSIS.md`: the problems panel is
   `partials/home_problems.html` / `ui_home.partial_home_problems`, the full
   list is Settings, Health.
6. `docs/legal/TELEMETRY.md`: the diagnostics row names
   `/partials/health-diagnostics` and `/partials/computer-answer` instead of
   the deleted classic partial.
7. `dashboard/static/cc/hud.css`: header comment no longer says the sheet is
   linked by `cc/shell.html` and classic `base.html`.

## Left for the next stage (not blocking)

- **Low, cosmetic:** at 390 the computers window's bar meta ("5 computers
  · collector 3m ago") is ellipsised down to 4 px because the nowrap bar
  gives the title the room and `.bar .meta` shrinks first. The facts are on
  the HUD stamp and the readouts, so nothing is lost, but the meta is
  effectively hidden on phones. A design call (wrap the meta under the
  title at phone width, or hide it on purpose).
- **Mechanism residual:** a rollback below 0.7.62 with terminal tabs open
  (above).
- **Housekeeping:** test docstrings and `ui.py` comments that narrate the
  classic sidebar polls as history; `dashboard/design/health.html` and the
  old plan docs that name `base.html` / `mobile.css`; the `ui_groups_history`
  meta row nobody reads.
- The SPA in-app focus tip (a11y-copy-3) was measured by the F-a11y
  verifier on data, not re-measured here (empty seed library).

## Suites (worktree code, main venvs, after my edits)

| Suite | Result |
|---|---|
| dashboard (206 files, 6 shards) | 5923 passed, 9 skipped, 0 failed; +1 new test passing (5924) |
| broll/web | 723 passed |
| music/web | 688 passed, 13 skipped |
| ytdl/web (dashboard venv) | 1058 passed |
| tools (dashboard venv) | 459 passed |

companion, server, onboarding, bench and the indexers are untouched by this
branch; INT2's note about the two companion vocabulary strings fixed on
`main` (`77916b8`) stands and goes away on rebase.
