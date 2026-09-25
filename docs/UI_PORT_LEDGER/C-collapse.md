# C-collapse: the CC Terminal look becomes the only look (phase 8, early)

Builder: COLLAPSE, 2026-09-25, worktree branch `ui-replace`. Authority: the
owner on the UI port review ("Fix all, also we don't need to maintain the
switch to the old UI. This is completely replacing the old one."). Phase 8 of
`UI_REDESIGN_PORT_PLAN.md` built early, with no soak. Nothing committed, no
version bumped.

## What moved

- Every file under `dashboard/templates/cc/` moved up over its classic twin
  at the same path (`cc/fleet.html` -> `fleet.html`, `cc/partials/x.html` ->
  `partials/x.html`); the new-named partials (`home_*`, `health_*`,
  `person_*`, `halt_line`, `hint_sheet`, `ev_macros`, `computer_answer`,
  `projects_tree`) land under `partials/`; `cc/shell.html` -> `shell.html`,
  and every `{% extends "cc/shell.html" %}` now extends `"shell.html"`.
  `templates/cc/` no longer exists.
- `offline.html` was the one page with no terminal twin: rewritten on
  `shell.html` as a bare gate page (no HUD, "Try again" key, same
  empty-href retry and same "nothing live" rule).
- `ui_variant.py`'s asset half (`asset_hash`, `asset_url`, `precache_urls`,
  the woff2 mimetype) moved to the new `ui_assets.py`; `static_files.py` and
  the `/sw.js` route read it. `precache_urls` now also lists the hashed
  shared scripts (pwa, htmx, htmx_errors, tab_memory), which the offline page
  asks for by hash.
- `/go/<panel>` moved to `ui_chrome.py` as a one-answer table (the
  destination every panel has now).

## What was deleted

- Templates: `base.html` and the classic-only partials `admin_diagnostics`,
  `chip_sheet`, `collector_health`, `editor_switcher`, `fix_root`,
  `fleet_halt_banner`, `my_queue`, `notice_checks`, `notices`,
  `queue_section`, `sidebar`, `ui_look_form`, `ui_look_links`; and
  `partials/home_collector.html`, which only the home grid drew while the
  `settings-health` group was off (the collector lives on Health).
- Static: `style.css`, `mobile.css`, `ui_groups.js` and the frozen classic
  scripts `account.js`, `assignments.js`, `copy_value.js`,
  `dashboard_update.js`, `setup.js`, `site_settings.js`, and
  `cards_landing.css` (the landing uses `cc/cards_landing.css`).
- Routes that only classic pages polled: `GET /partials/queue`,
  `/partials/sidebar`, `/partials/notices`, `/partials/fleet-halt-banner`,
  `/partials/admin/diagnostics`, and `/ui/preview`. `partial_toggle` with no
  `view` (the classic sidebar and queue) now answers an empty 200 plus the
  `cc-plan-changed` event instead of classic markup;
  `POST /partials/notices/{id}/dismiss` always answers the home problems
  window.
- The overlay: `ui_variant.py`, `ui_variant_settings.py`,
  `tools/ui_variant.py` (+ `tools/tests/test_ui_variant.py`), the
  `ui_terminal_groups` / `ui_preview` site keys (KEYS, validation, manifest,
  fallbacks, the import refusal), `Settings.site_ui_*` and their
  `DASH_SITE_UI_*` env reads, the look-groups form on Settings, the "how
  this browser looks" window on the account page, "use the classic look" on
  sign in, the HUD's "look" menu section (both menus), the `data-ui-apps`
  marker, the `hud_next` / `hud_preview_cc` / `ui_look_form` /
  `ui_can_preview` globals, `data-ui-groups/-gen/-sig`, the signed X-CC-UI
  set, `X-CC-UI-Want` and its reload line (`cc.js`, `cc/dashboard_update.js`,
  `.cc-reload` CSS), `.ev-look` CSS, and every `sync_envs()` / group check
  / `NOT_THIS_LOOK` 404 in `ui_home.py`, `ui_everyday.py`, `ui_health.py`,
  `ui_chrome.py`.
- Tests: `tests/ui_variant_support.py` (the fixture and the coverage hook in
  conftest), `test_ui_variant_fixture.py`, `test_ui_variant_mechanism.py`,
  and the three SPA `test_look_cookie_lifetime.py` files (the cookie is
  gone). Replaced by `tests/test_every_template_renders.py`.

## What was added

- `app.stale_page_gate`: every page's body sends `X-CC-UI: terminal`
  (`ui.LOOK_HEADER` / `LOOK_VALUE`, in `shell.html`'s hx-headers). An htmx
  request to the dashboard without it (a tab drawn by the classic look or by
  0.7.62's overlay) is answered 200, empty, `HX-Refresh: true`, BEFORE the
  route runs. `/api/`, `/static/` and the four mounts are exempt.
  `conftest.HX` is the header pair for tests.
- `site_store.RETIRED_KEYS` + `drop_retired_keys()`, run in the lifespan
  after the env seed: a stored `ui_terminal_groups` / `ui_preview` row is
  deleted at boot. A Settings PUT that still names one drops it silently
  (never a 422 for the rest of the save); `import_toml` already skips
  unknown keys. The `ui_groups_history` meta row is left alone (nothing reads
  it; harmless).
- `sw.js`: the cache name is `ccsync-<VERSION>-<LOOK>` with `LOOK =
  'terminal-1'`, so these bytes change, every installed worker updates, and
  `activate` drops the old cache with its precached classic `/offline`
  page. `style.css` / `mobile.css` left the precache list. Navigations were
  always network-first, so no browser is served a cached classic PAGE other
  than `/offline`.
- The SPAs: `<html lang="en" class="cc">` in markup (terminal body always,
  no first-paint switch); the head script only holds the HUD height
  (`cc-chrome`, `cc-chrome-pending`, 3 s net) and clears the retired
  `ccsync_ui_effective` cookie; `syncDashboardLook` only toggles `cc-chrome`
  on whether a HUD arrived. Document-relative URLs untouched. `cc_spa.js`
  comment updated identically in all three copies. The share page
  (`share.html`, `share.css`, `share.js`) is untouched (D10).
- Docs: CLAUDE.md's "OVERLAY" paragraph is now "the ONLY look"; the port
  plan's phase 8 row says built early, no soak, and how it differs.

## The review's mechanism findings

- **mechanism-1** (a 409 after a committed write, then the checkbox
  undone): FIXED by construction. The stale-page answer happens in
  middleware before the route, and is HX-Refresh, never 409, so nothing is
  committed behind it and nothing is undone on screen. Pinned by
  `test_a_stale_page_is_told_to_reload_and_its_write_never_lands` (asserts
  the selection is unchanged).
- **mechanism-2** (HEADER_FLOOR 0.7.61, never enforced): GONE with the
  switch; there is no group to enable, so nothing to refuse. Residual: an
  image rollback to 0.7.62 is safe (it reads `X-CC-UI: terminal` as an
  unknown group, answers HX-Refresh, and the page reloads classic, since the
  groups row was dropped); a rollback to 0.7.61 or older serves classic
  fragments into an open terminal page until that page is reloaded. That is
  the ordinary cost of a rollback across a look change, not a switch
  defect.
- **mechanism-3** (X-CC-UI-Want never shown on base.html pages): GONE; no
  base.html, no Want header.
- **mechanism-4** (SPA first paint trusts a stale cookie): GONE; html.cc
  is markup, the cookie is not read (and is cleared).
- **everyday-apps-4** (the SPA cookie lifetime / `/ui/preview` not updating
  it): GONE with the cookie.

## What remained, and why

- `static/cc/` stays where it is (not moved up): the SPAs, the hud-common
  byte-identity tests and every `asset_url('cc/...')` name it, and the move
  buys nothing.
- `static/cards_landing.js`, `confirms.js`, `htmx_errors.js`, `pwa.js`,
  `tab_memory.js`, `htmx.min.js`, icons, fonts, favicons, the manifest: the
  new pages load them.
- `ui_home` / `ui_everyday` / `ui_health` keep their module-level
  `_render_new` / `_render_health` names (now plain aliases of
  `ui._render`) so tests that patch them keep a seam.
- `ui._sidebar_context` and `_switcher_context` stay: page handlers still
  pass their values (as_qs, tick_for) to the pages.
- `cc_unbracket` stays (Python-built labels still carry brackets in a few
  places until the copy sweep reaches them).
- Comments in moved templates that say "as classic" / "classic twin" were
  left as history; nothing visible says "classic look" (the new test pins
  it on every page).
- The SPA sheets' classic rules (outside `html.cc`) were not stripped: the
  share page reads b-roll's sheet (R22), and stripping the rest is the next
  stage's call.

## Tests expected to break (the next stage converts them)

Dashboard, collection errors (import `ui_variant` or read deleted files):
`test_ui_chrome.py`, `test_cc_home.py`, `test_cc_everyday_review_fixes.py`,
`test_mobile_css.py` (reads `style.css` / `mobile.css`), `test_theme_css.py`
(reads `style.css`).

Dashboard, failing: every test that uses the `ui_variant` fixture or
`X-CC-UI` group sets (`test_cc_cards_landing.py`, `test_cc_everyday.py`,
`test_cc_home_review_fixes.py`, `test_cc_settings_people.py`,
`test_cc_settings_review_fixes.py`, `test_cc_settings_site_packages.py`,
`test_ui_health_group.py`, `test_bug_hunt_2026_09_24_w2_d-diag.py`,
`test_cc_a11y_copy.py`), every test that pins classic markup, a classic
route or a classic static file, and every test that sends `HX-Request`
without `X-CC-UI: terminal` (it now gets an empty HX-Refresh). The full
list from the run is in the builder's return.

SPAs (each of broll/web, music/web, ytdl/web, 9 each):
`test_cc_body.py` (4 head-script and marker tests),
`test_hud_common.py` (the first-paint and cookie-writing loader tests),
`test_theme_css.py` (the four-sheet theme-common block: the dashboard's
fourth sheet was `style.css`).
