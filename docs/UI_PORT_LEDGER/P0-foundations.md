# P0: phase 0, foundations (UI_REDESIGN_PORT_PLAN.md 7.0, 7.1 row 0)

Builder P0, 2026-09-25, worktree branch `ui-port`. Not committed, no version bump.

## Built

**The overlay mechanism**: `dashboard/src/ccsync_dashboard/ui_variant.py` (new).
- `GROUPS`, `TEMPLATE_GROUPS` (P1's chrome rows are in it), `NEW_NAME_TEMPLATES`,
  `ROUTE_GROUPS` (page path to group), `HEADER_FLOOR`, `GO_PANELS`.
- `ClassicLoader` (refuses `cc/*`), `GroupFilteredLoader` (a fixed set),
  `install(templates)` (called from `ui.py` right after `templates` is built),
  `templates_for(groups)` (one env per set, `templates.env.overlay(...)`,
  memoised under a lock), `sync_envs()`, `built_environments()`,
  `add_test_loader()`/`remove_test_loader()` (for `tests/templates/cc_probe.html`).
- `build_groups()` (groups with at least one existing cc/ file), `refresh()`.
- `site_groups(conn, settings, app=None)`: THE seam the test fixture patches.
- `resolve(request)`: 7.0's order (signed `X-CC-UI` on htmx; htmx with no
  header = classic + `HX-Refresh`/409 when a full load would differ for
  chrome or the asking page's group; else cookie then setting), every set
  intersected with the build, "cannot serve" (unknown group, group not in
  build, bad signature) = empty body + `HX-Refresh` (GET) or 409 + Want (write).
- `generation(groups)` (scoped digest: cc/ asset hashes + the set's cc/
  template bytes), `current_generation()`, `header_sig()`, `hx_headers()`.
- `render(request, name, context)`: what `ui._render` now returns through.
  Sets `ui_groups`, `ui_groups_attr`, `ui_hx_headers`, `oob` in the context;
  `ccsync_ui_effective` (dot-separated, Path=/, readable) on full pages only,
  and only when it changes (a classic site never gets a Set-Cookie).
- `is_partial(name)` replaces both `name.startswith("partials/")` in `_render`.
- Cookie `ccsync_ui`: `classic`, or signed `cc.<user>.<hmac>`; `/ui/preview?variant=cc|classic|site&next=`
  (303 to `next` or a same-host Referer path; 180-day Max-Age, Path=/,
  SameSite=Lax, HttpOnly, Secure per `cookie_secure`); `cc` needs a session and
  the `ui_preview` setting (`off`/`admins`/`everyone`); signed-out a `cc`
  cookie counts only if its signer is a current admin and preview is not off.
  `/ui/preview` added to `app._OPEN_GET_ONLY`.
- `/go/<panel>` with the R13 panel table and 7.0's cross-group rule.
- Template globals: `asset_url`, `ui_look_form`, `ui_can_preview`, defaults
  for `ui_groups`/`ui_groups_attr`/`ui_hx_headers`.
- `.woff2` MIME registered at import.

**Settings plumbing**: `site_store.KEYS` gains `ui_terminal_groups` (csv) and
`ui_preview` (str), `UI_KEYS`, `delete_key()`, validators in `ui_variant`
(`none`, `chrome` required and never added, 422 "waiting for its build" for a
group with no templates, `site` = delete), `_shape` fields, `_settings_fallback`
entries, `import_toml` refuses either key, `manifest_for_app` no longer caches
its fallback. `Settings.site_ui_terminal_groups`/`site_ui_preview` +
`DASH_SITE_UI_TERMINAL_GROUPS`/`DASH_SITE_UI_PREVIEW`. `api_admin_site_put`
routes the two keys through `ui_variant_settings.apply()` (new module): own
meta history `ui_groups_history` (capped 20), never `site_history`, audit
`site.ui_look`. Not in `/api/v1/site` (tested).

**Templates**: classic `base.html` gains `data-ui-groups` on `<html>` and the
new `hx-headers` keys appended after `X-CSRF-Token` via `tojson`.
`partials/ui_look_form.html` (its own `#ui-groups-form`, outside
`#settings-form`) included on classic Settings, with `static/ui_groups.js`.
`partials/ui_look_links.html` (the three look links) included on classic `/account`.

**Static**: `static/cc/terminal.css` (fonts, `:root` with D5 bench defaults
baked in, `--red-dim`, `--tap`, `--safe-*`, `color-scheme`; theme-common
byte-identical; 2px `--hi` focus; switch/check/radio rings; forced-colours;
reduced motion kills the grain; `scroll-padding` for the sticky HUD; key
primary `#d01818`/hover `#b81414`; LED blink 4 beats; grain static; no
backdrop-filter; data-URI slashes percent-encoded), `static/cc/components.css`
(cc-components + the seven bench sheets deduplicated, the `<dialog>` confirm,
the fold button, `.tip-btn`, field/select paint, `.cc-reload`),
`static/cc/phone.css` (every 760px rule, 12px floor, coarse-pointer 44px
block, `data-label` stacking, wrap rules, 16px fields LAST),
`static/cc/hud.css` scaffold (P1 has since filled hud-common),
`static/cc/cc.js`, `static/cc/copy_value.js` (fork, unbracketed labels).
`static/fonts/`: JetBrains Mono 400/500/700 (subset) + Orbitron variable
(whole, it has a Reserved Font Name), OFL texts, `manifest.json` (name to
sha256). Notices: fonts in the HAND-MAINTAINED block of
`docs/legal/THIRD_PARTY_NOTICES.md`.
`static_files.CachedStaticFiles` on `/static`: `no-cache`; current `?h=`
immutable; wrong `?h=` no-store; fonts immutable. `sw.js`: `CC_PRECACHE`
(substituted by `/sw.js` from `ui_variant.precache_urls()`), revalidation
`fetch(req, {cache: 'no-cache'})`.

**cc.js**: folds (`ccsync.fold:<path>`, `data-win`, `button.fold` first child
of `.bar`, bar click excluding controls, `data-nofold`), unfold-without-store
on user swaps / hash / banners / `#minted-secret` oob; tips (title to
`data-tip` + `aria-description`, tabindex on non-controls, Escape, anchored to
the rect, hover-intent, delayed on controls, hidden on beforeSwap/hashchange/
scroll; `.tip-btn[data-tip-for]` calls `window.ccsyncOpenHint(title, text)`
if the hint sheet defines it); confirm through `<dialog id="cc-confirm">` with
`[data-cc-confirm-q]`, `[data-cc-confirm-ok]`, `[data-cc-confirm-cancel]`
(question check, `__ccConfirmed` re-dispatch by `data-confirm-key`, submitter
kept as a temp hidden input, every request held while open, "nothing was
sent" when the source is gone); APG tabs (`ccsync.cctab:<path>`, hash tab
opened before scrolling, `window.ccsyncRevealField(el)`); `html.cc-hidden`;
the Want reload line on cc pages.

**Tests**: `tools/ui_variant.py` (off / site / set / preview / show, reusing
`jobs.py`'s Client, Http and password reader).

## Tests (run once at the end, dashboard venv)

- `dashboard/tests/test_ui_variant_mechanism.py` 46 passed (marked `ui_mechanism`).
- `dashboard/tests/test_ui_variant_fixture.py` 4 passed, 3 skipped by parameter.
- `dashboard/tests/test_cc_css_facts.py` 23 passed.
- `tools/tests/test_ui_variant.py` 7 passed.
- Touched existing suites: site*, sessions, pwa, no_em_dash, mobile_css,
  theme_css, home_layout, account_db, account_page, settings_hub,
  bug_hunt_2026_09_18_dashboard_mediums, sweep_2026_09_04_dash_ui: 651 passed
  (after the sw.js fix); ai_providers, android, the two 09-11 dash_mounts_ui,
  09-24 w2 d-ui, mobile_admin, mobile_origin, settings_auto_derived,
  setup_routes, tab_memory, static_js_syntax, pwa: 499 passed.

## Hand-offs (for P1 and later phases)

- **Coverage hook is live**: on a FULL run, `pytest_sessionfinish` fails when
  an existing file in `TEMPLATE_GROUPS` was never rendered inside a test that
  uses the `ui_variant` fixture (mechanism tests do not count). P1: render
  shell, topbar, stamp, settings_nav, halt_line, hint_sheet under
  `ui_variant` (shell through `tests/templates/cc_probe.html` +
  `ui_variant.add_test_loader`).
- The fixture: `ui_variant` (params `classic`, `chrome`, `all`), with
  `.groups`, `.is_classic`, `.check_page(html)`, `.htmx_headers(client, current_url)`.
  Add the cumulative prefix to `UI_VARIANT_PARAMS` in `tests/ui_variant_support.py` per phase.
- `partial_topbar` must call `ui_variant.set_effective_cookie(request, response, res.groups)`
  itself (fragments never get the full-page cookie); the login gate's SPA
  navigation pass-through cookie is not built.
- `htmx_errors.js` (shared, P1 editing): the Want line for CLASSIC pages and
  the document-level `#cc-confirm[open]` hold in `busy()` are not added
  there (cc.js does both on cc pages).
- `tab_memory.js` cc branch (skip zero-rect headings) not built.
- Class renames in the dedup: `.toggle`, `.toggle-rows`, `.dirfold`,
  `.path-crumbs`, `.fgroup`/`.fgroup-body`, `.filenav`, `.vstack`, `.bar-rule`;
  `.fold` is the window's fold BUTTON; phone tables use `data-label`.
- The shell's confirm dialog markup cc.js expects: `<dialog id="cc-confirm" class="cc-dialog">`
  with `[data-cc-confirm-q]`, `[data-cc-confirm-ok]`, `[data-cc-confirm-cancel]` (autofocus).

## Omitted (listed, not built, for speed)

- `HEADER_FLOOR` image-version refusal and the signed `min_image_version` preflight (constant only).
- `tools/mobile_sweep.js` changes, the control census (static and click
  halves), the bracket scan, the retired-phrase twin table, the d-ui Chrome
  harness parametrisation, `OWNED_TEMPLATES`/`CC_OWNED_TEMPLATES` and d-ui glob
  changes, the `/offline` precache subresource test with its five-entry allow-list.
- `cc/terminal.css` as a fifth `FLEET_STYLESHEETS` entry in the four suites
  (identity with the classic block is tested in `test_cc_css_facts.py` instead).
- `jobs.py` Client not factored into a shared module (the tool imports it).
- The `.woff2` MIME line in each SPA's standalone app (dashboard only).

(`test_sessions.py:377` and `test_pwa.py:215` pass unchanged with the new
`hx-headers` keys.)

## Departures

- `RECORDING` is a process-wide flag, not a ContextVar: TestClient renders on
  its portal thread, which never sees a context variable set by the test.
- Orbitron ships unsubsetted (Reserved Font Name); JetBrains Mono is subset.
- The generator scripts that built the three sheets from the bench live in the
  session scratchpad, not the repo; the sheets are now the source.
