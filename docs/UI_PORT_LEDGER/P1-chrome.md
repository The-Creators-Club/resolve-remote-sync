# P1: phase 1, chrome (group `chrome`)

Builder P1, 2026-09-25. Plan: `docs/UI_REDESIGN_PORT_PLAN.md` 2.2, 2.5, 3.2
to 3.4, 4.1, 7.0, 7.1 row 1, R6, R9, R15, R16, R22. Nothing committed, no
version bumped.

## Built

- `dashboard/templates/cc/partials/topbar.html`: the HUD. Brand (the CC
  mark plus `brand_org` in the mono face, ellipsised, never Orbitron), the
  `>word` nav (sync, b-roll, music, youtube, cards, transfers, settings;
  modules only when mounted, trailing slashes kept; music and youtube are
  `hud-lowpri` and fold into "more" at 601 to 900 px, opened by
  `.hud-more-btn`), problem and alert counts absent at zero (problems link
  `/go/notices`), the polled stamp (`#topbar-stamp`, 30 s), the user link to
  `/account` plus a `<button popovertarget="hud-user">` menu (account, help,
  installer, the three look links, sign out, sign out everywhere with its
  C-9 confirm), the phone dock (sync, b-roll, cards, transfers, more) as a
  SIBLING of `.hud`, and `#hud-more` (counts, music, youtube, settings,
  installer, help, account, look links, sign out x2, `#install-slot`,
  close). `data-dash-topbar`, `data-csrf`, `data-ui-apps` (from `apps` in
  the resolved set) on the brand link. No script, every class `hud-*`.
  Anonymous render: brand plus "sign in" only (no nav, dock or menus).
- `cc/partials/stamp.html`: compact on phones (LED plus "stale" when
  Syncthing is unreachable, nothing when well), the full sentence in the
  element's `title`/`data-tip` for the hint sheet; not repeated in
  `#hud-more`.
- `cc/partials/settings_nav.html`: `.snav scroll-x`, same groups, keys and
  per-entry admin rule, lowercase labels, `>` by CSS, `aria-current`.
- `cc/partials/halt_line.html` on the new route `GET /partials/halt-line`
  (`ui_chrome.py`; 401 signed out, 404 when `chrome` is not in the resolved
  set, same context as the classic banner). `.alertline` with a fixed
  lowercase tag word and data in `.v` spans.
- `cc/partials/hint_sheet.html`: `#chip-sheet.hint-sheet` keeping block 2's
  three hooks, `hidden`.
- `cc/shell.html`: base.html's head with the four cc sheets and the six
  scripts through `asset_url()` in the plan's order (cc copy of
  copy_value.js, never the classic), `data-ui="cc"`, `data-ui-groups`,
  `data-ui-gen`, `data-ui-sig`, `hx-headers` with `X-CSRF-Token` FIRST then
  P0's `ui_hx_headers`, the keeper and deep-link scripts, the bare
  `hud-host`, the halt-line poll, `.shell`, hint sheet, `<dialog
  id="cc-confirm">` (Cancel autofocused), `#cc-toast`.
- `base.html` (surgical): when `'chrome' in ui_groups`, one added
  `<link href="{{ asset_url('cc/hud.css') }}">`, `<header class="hud-host">`
  instead of `<header class="topbar">` and no `.rule`. Everything else,
  including the classic halt banner and chip sheet, untouched.
- Classic `partials/topbar.html`: only `data-ui-apps` added on the brand.
- `static/cc/hud.css` (P0's scaffold, filled): header, JetBrains Mono
  400/500/700 `@font-face` (`url(../fonts/..)`, P0's unicode-range), the
  hud-common block, then the lifts outside it: `--cc-dock-h` on
  `html:has(.hud-dock)` inside the one 600 px dock query, `scroll-padding`
  top and bottom on `html:has(.hud)`, body padding plus stale banner, chip
  sheet, sheet handle and toast-host lifts keyed on `body:has(.hud-dock)`,
  the classic `.project-tree` sticky lift, and the cc hint-sheet look.
- hud-common (byte-identical in `cc/hud.css` and the three SPA sheets,
  appended after every existing block so first-occurrence slices are
  unaffected): `--cc-*` tokens on `.hud, .hud-dock, .hud-more, .hud-menu,
  .snav`; `header.hud-host` and `#dash-topbar:has(> .hud)` as
  `display: contents` (the HUD sticks); sticky 58 px bar (52 on phones),
  no backdrop blur; brand shrinks first; popover base rules with no
  `display`; LED blink capped at 4; 601 to 900 tablet block; 600 px dock
  block (12 px floor, `letter-spacing: 0`, real-inset padding); coarse
  pointer 44 px; standalone top inset; forced colours; reduced motion; 2 px
  `--cc-hi` focus ring. No quote/paren before a slash, no long dash.
- SPA sheets (broll, music, ytdl): per-sheet `@font-face`
  (`../../static/fonts/` for b-roll, `../static/fonts/` for the others),
  hud-common, the dock lift, scroll-padding, `#dash-topbar:has(> .hud) +
  .rule` hide, the `html.cc-chrome-pending` header hold (58/52 px), the
  body-height fix in b-roll and music, and R6 lifts (b-roll toast, three
  panels, `#grid-view`/`#detail-view` padding; music toast and `.mi-panel`;
  ytdl toast). All scoped.
- SPA first-paint head script in each `index.html` (before the sheet):
  reads `ccsync_ui_effective` with `split('; ')`, sets `cc-chrome` and
  `cc-chrome-pending`, 3 s safety timer. Each `app.js` loader: `finally`
  always clears the hold, keeps `cc-chrome` only if a HUD arrived, and
  `syncDashboardLook()` sets or clears `html.cc` from `data-ui-apps` and
  rewrites the cookie with `path=/; samesite=lax` (+ `secure` on https).
- b-roll `main.py`: `Cache-Control: no-cache` on `index()` and the
  `/static` mount (R16); the share-assets mount unchanged.
- `ui.py` `partial_topbar` (surgical): passes `hud_notice_counts` /
  `hud_alert_counts` (admin only) and calls
  `ui_variant.set_effective_cookie` itself.
- `ui_chrome.py` (new): the halt-line route, Jinja globals `hud_next`
  (SPA home for `?current=`, else this path) and `hud_preview_cc`
  (`ui_variant.preview_allowed`), `topbar_extras`. `app.py`: one
  `include_router` line.
- `static/htmx_errors.js` block 2: one explicit selector (`[data-tip],
  [data-chip-detail], .tag[title], .led[title], .hud-led[title],
  .chip[title], .dot[title]`), `summary` added to the control exemption,
  text read `data-tip || data-chip-detail || title`.
- `static/pwa.js`: install button branch, `hud-key install-btn` "install
  this app" inside `.hud-more`, classic `[ INSTALL ]` chip unchanged.

## Omitted controls / not built

- None of the live topbar's controls is lost. The bench's Taipei clock is
  not built (D4). The bench's "N problems" is absent at zero (product rule).
- The login gate's pass-through cookie for SPA navigations (7.0) is not
  set by me; the SPAs get the cookie from `/partials/topbar` (first visit
  paints once without the hold). Hand-off to P0 if wanted.
- `sw.js` PRECACHE of `cc/hud.css` and the fonts (R9): P0's file.
- The Chrome-harness, sweep and screenshot checks of the phase 1 row
  (sticky after 1000 px, 360/390/768 overflow, occlusion, installed-app
  screenshot, `.folder-tree`/`.filter-rail` screenshots, `#pager-next`
  hit-test) are NOT run (speed rules); they belong to the adversarial or
  sweep pass.
- The `/offline` precache-with-chrome test is not written; the chrome-on
  offline identity twin is (no user, no counts).

## Departures

- hud-common's token selector also covers `.hud-menu` (the `#hud-user`
  popover's class) and `.snav` (the strip sits in the page, not in `.hud`).
- The hint sheet's look lives in `cc/hud.css` after the END marker, keyed
  `html[data-ui="cc"] .hint-sheet`, not in `components.css` (P0's file).
  Hand-off: move it into `components.css`/`phone.css` if preferred.
- `hud-hide-sm`, `hud-lowpri`, `hud-mi*`, `hud-stale`, `hud-sr` are extra
  HUD-owned names beyond the plan's list.
- The halt line's key is a plain link to `/admin/users#admin-fleet-halt`
  (as classic); the terminal key classes (`key quiet sm`, `tag solid`,
  `alertline`, `.v`, `.dim`) are P0's `terminal.css`/`components.css`.
- SPA tests are new files (`tests/test_hud_common.py` in each suite)
  rather than additions to each `test_theme_css.py`; the dashboard's are in
  `tests/test_ui_chrome.py`.
- `ytdl` suite has no venv; run with the dashboard venv, as CLAUDE.md says.

## Tests (run once, at the end)

- `dashboard`: `tests/test_ui_chrome.py` 22 passed (new). Also re-ran the
  touched classic files: `test_topbar_partial.py`, `test_pwa.py`,
  `test_templates_wave3_2026_09_04.py`, `test_static_js_syntax.py`,
  `test_mobile_css.py`, `test_theme_css.py`, `test_no_em_dash.py`,
  `test_sessions.py`, `test_settings_hub.py`: 419 passed, 1 failed:
  `test_pwa.py::test_the_workers_precache_holds_nothing_session_specific`
  ('/api/' in sw.js's PRECACHE list), caused by the in-flight `sw.js` edit
  (P0's file, not touched by P1).
- `broll/web` (own venv): `test_hud_common.py` 11 new; with
  `test_mounted_prefix.py`, `test_theme_css.py`, `test_no_em_dashes.py`,
  `test_bug_hunt_2026_09_24_w2_broll.py`: 136 passed.
- `music/web` (own venv): `test_hud_common.py` 10 new + mounted-prefix,
  theme, em-dash, w2 music-ytdl: 132 passed.
- `ytdl/web` (dashboard venv): `test_hud_common.py` 11 new + mounted-prefix,
  theme: 56 passed; no-em-dash, w2 music-ytdl, says-what-it-knows: 73 passed.
- `node --check` on the three SPA `app.js`: ok.

## Hand-offs

- P0: `sw.js` PRECACHE must include `cc/hud.css?h=` and the fonts (R9);
  the `test_pwa.py` failure above is in P0's sw.js change.
- P0: `test_hud_css`-style asserts that ban `.hud` selectors outside the
  block must allow `:has(.hud...)` (the plan's own lift selectors).
- P0's `cc.js` confirm handler: `#cc-confirm` is a `<dialog>` holding
  `<form method="dialog">`, `.cc-confirm-q` for the question, buttons with
  `value="cancel"` (autofocus) and `value="ok"`; adjust to cc.js's needs.
- Phase 2+: pages extend `cc/shell.html` with `{% block layout %}`; the
  settings strip is `{% include "partials/settings_nav.html" %}` as today.
