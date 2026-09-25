# T16: test conversion after the look collapse

Builder: test converter T16, 2026-09-25, worktree branch `ui-replace`.
Nothing committed, no version bumped. Follows `C-collapse.md`.

## dashboard/tests/test_ui_chrome.py (19 pass)

Converted: the `chrome` fixture and the `ui_variant` import are gone; every
rendering test now asserts the one chrome.
- `test_topbar_is_the_hud`: was "with chrome on". The `data-ui-apps` marker
  and the `ccsync_ui_effective` cookie are now asserted ABSENT (retired).
- `test_topbar_counts_show_in_the_spas_when_nonzero`: the "look" menu link
  (`/ui/preview?variant=classic`) is asserted absent, plus no "classic".
- `test_a_page_gets_the_bare_host_and_hud_sheet`: was "a classic page under
  chrome". No `style.css` / `mobile.css`; the halt line on
  `/partials/halt-line`, never `fleet-halt-banner` (R15 inverted: there is
  no classic banner any more).
- `test_the_stamp_poll_from_a_page_gets_the_hud_stamp`: the page's header is
  `X-CC-UI: terminal` (`ui.LOOK_HEADER` / `LOOK_VALUE`).
- `test_the_halt_line_route_follows_the_page`: the headerless htmx asker now
  gets the stale-page gate's empty 200 + `HX-Refresh: true`.
- `test_the_offline_page_names_nobody`: the offline page is a bare gate page
  now (no HUD at all), so `hud-host` is asserted absent; still names nobody,
  no counts, no account link.
- `test_the_terminal_shell`: renders a probe child of `shell.html` through
  `ui.templates.env` with a ChoiceLoader (the ui_variant test loader is
  gone). Root is `<html lang="en" data-ui="cc">` with no group/gen/sig
  attributes; `hx-headers` is exactly CSRF + `X-CC-UI: terminal`.
- `test_pwa_install_button_is_the_hud_key`: see the product fix.

Deleted:
- `test_the_classic_drawer_block_is_still_in_every_sheet`: read the deleted
  `static/style.css` and pinned the drawer for "chrome off", which no longer
  exists.
- `test_classic_topbar_is_unchanged_with_chrome_off`: the switch.
- `test_a_classic_page_with_chrome_off_is_unchanged`: the switch.

## dashboard/tests/test_ui_health_group.py (30 pass)

Converted: the `ui_variant` parametrisation is gone; `_hx` is `conftest.HX`
plus `HX-Current-URL`.
- `test_each_page_renders_terminal` (was `..._in_its_look`, classic half
  dropped): `<html lang="en" data-ui="cc">`, `cc/health.css`, no sidebar.
- `test_health_partials_tell_a_stale_page_to_reload` (was "404 when the
  group is off"): a request without the look header gets the empty
  HX-Refresh answer and no markup.
- `test_a_health_dismiss_from_a_stale_page_changes_nothing` (was "... when
  the group is off", mechanism-1): HX-Refresh, empty, and the notice's
  `cleared_at` is still unset.
- `test_go_resolves_and_lands_on_a_rendered_anchor`: the classic row of the
  per-variant table is dropped (one answer per panel now, R13).
- Every other test: unchanged assertions, fixture argument removed.

Deleted: none (the classic-only parametrisations went with the fixture).

## dashboard/tests/test_upload_only.py (19 pass)

- `test_the_project_page_offers_upload_only_and_the_way_back`: bracket
  labels -> the terminal keys' `<span class="t">` labels ("Upload only for
  me", "Tick for me", "Switch to full sync", "Untick for me", "Switch to
  upload only"); UX-17's SELECTED BY marker is the `upload only` tag right
  after `<b>ruskin</b>`. The posts now send `conftest.HX`, as the page does.
  Set-not-toggle and the way back are asserted as before.
- `test_the_projects_tree_marks_an_upload_only_project` (was "the sidebar
  marks"): the classic sidebar chip is the projects tree's `upload only`
  tag; asserted on p1's row and absent from p2's (a full tick).

## dashboard/tests/test_ytdl_mount.py (pass)

- `test_a_signed_in_editor_renders_a_page_through_the_mount`: the classic
  `drawer-current` class -> every `aria-current="page"` link in the HUD
  (bar and "more" sheet) points at `/ytdl/` and nothing else. Added
  `import re`.

## broll/web/tests/test_cc_body.py and test_hud_common.py (28 pass)

- `test_html_cc_is_in_the_markup_and_the_head_script_reads_no_cookie` (was
  "sets html.cc from the cookie"): `class="cc"` on `<html>` in markup, the
  head script reads no cookie, never adds `cc`, and clears
  `ccsync_ui_effective`.
- `test_the_head_script_runs`: run under node with three old cookie values;
  each gives exactly `cc-chrome` + `cc-chrome-pending` and the clearing
  cookie write.
- `test_the_loader_toggles_only_cc_chrome_on_the_hud` (was "the topbar
  marker is authoritative for html.cc"): `syncDashboardLook` keys
  `cc-chrome` on `.hud`, never toggles `cc`, no `data-ui-apps`, still calls
  `relayoutDetail()`.
- test_hud_common: `test_the_first_paint_script_holds_the_hud_height` now
  pins the unconditional hold (no cookie read); `test_the_loader_trusts_what_
  arrived` (was "... and writes the cookie at the root") pins that the loader
  writes no cookie and reads no marker.

Left, noted: `test_the_classic_drawer_block_is_still_here` and
`test_hud_common_sits_after_every_existing_block` still pass and still pin
the classic drawer block in b-roll's sheet. That block is dead CSS now (no
page serves a drawer); stripping the SPA sheets' classic rules is the next
stage's call (C-collapse), and those two tests go with it.

## Product fix

- `dashboard/static/pwa.js`: `showInstall()` lost its classic branch (a
  `btn chip tap` with the label `[ INSTALL ]`, a bracket control). The only
  `#install-slot` left is in the HUD's "more" sheet, so the key is always
  the `hud-key` "install this app". `dashboard/tests/test_pwa.py`'s one line
  that required `[ INSTALL ]` now requires the HUD label and forbids the
  bracket (surgical edit to a file outside my list; 61 pass with
  test_ytdl_mount).

## Seen, not mine

- `broll/web/static/index.html`'s standalone-dev fallback header still has
  `[ DASHBOARD ]` and the `.rule` line. Only seen before the HUD arrives or
  in the dev loop.
