# T15: test conversion after the collapse (six dashboard files)

Builder: T15, 2026-09-25, worktree branch `ui-replace`. Follows C-collapse.
Nothing committed, no version bumped. Final: 137 passed, 0 failed across the
six files (plus `test_cc_css_facts.py` still green alongside).

## Product fix

- **CR-188's CSS guard was lost with `mobile.css`.** The "== tab memory =="
  block (`html { scroll-behavior: auto }`, `overflow-anchor: auto` on the
  page and `.fleet-grid-wrap`) that `tab_memory.js` depends on was deleted and
  had no twin in the terminal sheets. It is now at the end of
  `dashboard/static/cc/terminal.css` (`.page` replaces the classic
  `.layout`). The test also checks that no `static/cc/*.css` sheet sets
  `overflow-anchor: none` or `scroll-behavior: smooth`.

## Per file

- `test_sweep_2026_09_04_second_customer.py`: 3 converted. Suspended is now
  a warn tag on the grid. The create form names "Archive" in sentence case.
  The SSH key row has the `no ssh key` err tag and the add/update key.
- `test_tab_memory.py`: 3 converted (`shell.html` asset_url order, the CSS
  block in terminal.css, the em dash scan over terminal.css), plus the
  product fix above.
- `test_templates_wave3_2026_09_04.py`: 12 failing tests converted.
  - DUI-3: the tag title, `hint_sheet` in shell.html, the htmx_errors.js
    hooks, and phone.css's coarse `.tag:is([title], [data-tip])`.
  - DUI-6: the `note err error-banner` panels and `cc/setup.js`.
  - DUI-19: the four terminal homes of the safe-to-close sentence.
  - DUI-20: "This computer" x3, and projects_tree in place of the sidebar.
  - REL-12: 9 busy forms (the 9th is the new roll-back shortcut),
    `settings_fleet.css`'s htmx-request busy word.
  - REL-16: "roll the fleet back".
  - RES-6: tag tones ok/warn/err, with the detail in the tag's own title.
  - DCORE-16: `health_collector.html`.
  - CYT-3: lowercase tags.

  Two tests had become VACUOUS without failing, and both are tightened:
  `test_a_machine_with_no_cards_role_gets_no_chip` still asserted `"[ CARDS"`
  absent, and CYT-3's last line still asserted `"YOUTUBE"` absent. They now
  check for the terminal tag and for lowercase "youtube".
- `test_theme_css.py`: rewritten onto `cc/hud.css`, `cc/terminal.css` and
  `cc/components.css`.
  - Header: nowrap labels, `.hud-meta` as one item, and the phone and tablet
    layers never re-enable wrapping. The brand gives way by ellipsis.
  - Fields: the one `input:not(...)` paint rule, plus `.inp`/`.area`/`.sel`
    for border, focus, placeholder and disabled. Checkboxes and radios stay
    drawn controls.
  - Scrollbar, range and selection tests: the same, read from terminal.css.
  - The theme-common drift test: the dashboard's copy is now terminal.css.
- `test_topbar_partial.py`: 9 converted to the HUD: the popovers `#hud-user`
  and `#hud-more`, the dock, `aria-current` in place of `drawer-current`,
  and the "settings" nav entry in place of the gear. One test is renamed to
  `test_every_destination_is_reachable_from_the_phone_dock_and_sheet`,
  because the HUD's bar has a nav again on purpose.
- `test_triage.py`: 1 converted (the "server check" window's fold label, the
  Run now key and its form).

## Deleted tests (the behaviour no longer exists)

- test_theme_css `test_nav_separators_are_pseudo_elements_not_text_nodes`:
  `.nav-sep` "//" was classic-only CSS. The HUD has no separators.
- test_theme_css `test_the_bar_itself_carries_no_module_links`: this reverses
  the classic rule. The HUD's bar carries `> sync  > transfers` on purpose.
- test_theme_css `test_the_section_header_carries_the_hairline_rule` and
  `test_a_section_header_that_is_a_link_still_reads_as_one`: `.side-head`
  was the classic section header. In the terminal, a window's bar is its
  header.

## For others

- The SPA `test_theme_css.py` copies (broll/music/ytdl) still point
  `FLEET_STYLESHEETS["dashboard"]` at `dashboard/static/style.css`. Their
  converter should use `dashboard/static/cc/terminal.css`, as this file does.
- Copy inconsistency (not changed): the account page says "tray: Settings,
  THIS COMPUTER", while assignments and the project tree say "tray, Settings,
  This computer.". The copy sweep should decide which one matches the tray.
