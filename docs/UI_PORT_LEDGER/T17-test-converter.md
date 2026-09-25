# T17: SPA theme / body / HUD tests after the collapse

Test converter T17, 2026-09-25, worktree branch `ui-replace`. Follows
`C-collapse.md` (the classic look and its switch deleted). No product code
changed; nothing deleted; no version bumped.

## broll/web, music/web, ytdl/web: `tests/test_theme_css.py`

- **Converted.** The theme-common drift check named the dashboard's copy as
  `dashboard/static/style.css`, which the collapse deleted. The dashboard's
  copy is `dashboard/static/cc/terminal.css` now (the same block, already
  byte-identical to the three SPA sheets and pinned from the dashboard side
  by `test_cc_css_facts.py`). `FLEET_STYLESHEETS["dashboard"]` and the drift
  message point there; same two tests, same four-way byte identity.

## music/web, ytdl/web: `tests/test_cc_body.py`

- `test_the_head_script_sets_html_cc_from_the_cookie` -> 
  `test_html_cc_is_in_the_markup_and_the_head_script_only_holds_the_hud`:
  pins `<html lang="en" class="cc">` in the markup, the head script adding
  `cc-chrome` / `cc-chrome-pending`, reading no cookie and never touching
  `cc`; kept the no-`document.body` and no-root-URL checks.
- `test_the_head_script_runs` (node): same four cookie values, now every one
  must give the same result (`cc` kept, `cc-chrome` + `cc-chrome-pending`
  held, the 3000 ms net drops only the pending class) and the one cookie
  write must be `ccsync_ui_effective=; path=/; max-age=0`.
- `test_the_topbar_marker_is_authoritative_for_html_cc` -> 
  `test_the_topbar_loader_never_switches_html_cc` (node): runs the real
  `syncDashboardLook` with a HUD host, a bare host and null; `cc-chrome`
  follows the HUD, `cc` survives all three; no `data-ui-apps` in app.js.
- Module docstring updated. Every other test unchanged.

## music/web, ytdl/web: `tests/test_hud_common.py`

- `test_the_first_paint_script_holds_the_hud_height`: the cookie-parsing
  asserts (`split('; ')`, `slice(20)`) replaced by: reads no cookie, adds
  `cc-chrome`, clears the retired cookie at `path=/`; the script-before-
  stylesheet, pending + setTimeout, no regex, no em dash checks kept.
- `test_the_loader_trusts_what_arrived_and_writes_the_cookie_at_the_root` ->
  `test_the_loader_trusts_what_arrived_and_writes_no_cookie`: cc-chrome keyed
  on `.hud`, no `document.cookie` and no `data-ui-apps` anywhere in app.js;
  the loader's `finally` pins kept.

## Deleted tests

None. Every failing test pinned a behaviour that still exists in another
form (first-paint hold, loader, theme-common identity).

## Not mine, seen failing

`broll/web/tests/test_cc_body.py` and `broll/web/tests/test_hud_common.py`
(7 failures, the same shape as the music/ytdl ones) belong to another
converter.

## Result

- broll/web `test_theme_css.py`: 40 passed.
- music/web the three files: 64 passed.
- ytdl/web the three files: 63 passed.
