# T10: six dashboard test files moved onto the terminal markup

Builder: test converter T10, 2026-09-25, worktree branch `ui-replace`. After
C-collapse deleted the old sheets and templates. Nothing committed, no
version bumped.

## Per file

### dashboard/tests/test_mobile_css.py (converted, 34 pass)

Read `style.css`, `base.html`, `sidebar.html` (all deleted). Rewritten as
the same phone contract against `static/cc/*.css`, `shell.html`,
`partials/topbar.html`, `partials/settings_nav.html`, `login.html`:
tokens in the terminal `:root` (`--tap`, `--safe-*`), phone rules in
`phone.css` (760 page query, one coarse-pointer block), the dock at 600 in
`hud.css`, `(hover: none)` only ever reveals, `.tbl.stack-sm` labels (12px,
empty label opts out), `.phone-only`, 44px targets by pointer not width
(page controls and every HUD control), the 12px phone floor, the PWA lines
in `shell.html` (manifest, theme colour now `#070403` = `--bg`, Apple metas,
touch icon, `pwa.js` before htmx, `phone.css` after the sheets it
overrides), viewport-fit, the install slot in the "more" sheet, visible-only
polls in the chrome, the halt line still loads immediately, the settings
strip snaps to the current entry, the 16px field rule and its
`html[data-ui="cc"]` hook, standalone pays the top inset.

Deleted (no terminal counterpart): `--bp-phone` / `--bp-tablet` tokens and
their query agreement (the terminal has no such tokens); the 900px narrow
query; the phone layer sitting before theme-common (no theme-common in
`phone.css`); the classic projects sheet (`#projects-sheet` popover and its
handle: the tree is a folded window now); `.rule` as a bordered div (no
such element; box drawing in templates is pinned by `test_cc_css_facts`);
`mobile.css` linked after `style.css`; the chip copy in the drawer
(`phone-hide` / `drawer-chips`: the dock and "more" sheet replaced the
drawer, pinned instead by `test_the_phone_bar_hides_the_desktop_nav_and_shows_the_dock`).

### dashboard/tests/test_mobile_fleet.py (converted, 52 pass; product fix)

The machine table is a `.pc` card per computer now: pinned that it reflows
below 1100 (header row hidden, lanes and issues on their own rows), that
every value on a card is named (lane words, `version` in the details list,
the issues aria-label), that the card's buttons are `.key` with the home
sheet's 44px coarse-pointer rule. Transfers: `tbl stack-sm fixed xft`,
lower-case data-labels, direction opts out with `data-label=""`, the file
cell wraps (`phone.css`). Project detail: every `<td>` labelled. Installer:
`key primary` download plus the coarse-pointer key rule. OWNED list swaps
the deleted `notices` / `queue_section` / `my_queue` for `home_problems`,
`home_queue`, `person_queue`, `home_transfers`, `projects_tree`,
`plan_changes`, `project_roots`. The scroll-x wrapper rule became "no table
can scroll the page": each table is directly inside a `scroll-x` div or is
`.tbl.fixed`. The nowrap test pins the terminal release selectors.

Deleted: `test_the_fleet_section_of_mobile_css_is_phone_only` (the
`mobile.css` fleet section is gone; phone rules living in `phone.css` is
pinned by `test_mobile_css`). `collector_health` / `notice_checks` left the
tables list (deleted; their terminal twins are on Health, not these pages).

Product fix: `static/cc/terminal.css` `.head .sub` gains
`overflow-wrap: anywhere`. The project page prints the whole server path
in the head's sub line with no break opportunity; old markup had `.path` for
it and the port dropped it, so a long path scrolled a phone page sideways.

### dashboard/tests/test_music_ingest_report.py (converted, all pass)

Chips are lower-case tags now: `>indexing music: 4/12</span>`,
`>indexing b-roll: 12/40</span>`, `<span class="w">music model</span>`; the
track name is asserted in the tag's tip (`music batch 01234567 - 03 Slow
Burn.wav`). Same convention as T2's `test_broll_ingest_report`. The "a
finished batch leaves the grid" check was vacuous after the collapse (it
looked for the upper-case word); it now looks for the real one.

### dashboard/tests/test_music_mount.py (converted, all pass)

The topbar marks music through `aria-current="page"` on both music links
(the bar's and the "more" sheet's) and on nothing else, as
`test_topbar_partial` does for transfers.

### dashboard/tests/test_notices.py (converted, all pass)

`/partials/notices` is gone; the checks list is Health's
`/partials/health-notices`. The test now reads each named check's own
tag (`found`, `ok`, `not checked`) instead of three strings anywhere on
the page, so it is stricter than before.

### dashboard/tests/test_notices_sweep_wave2.py (converted, all pass)

The take-me-there key is asserted on both panels that draw notices
(`/partials/home-problems` and `/partials/health-notices`): the key links
`/admin/users`, its words are "take me there" in any case (a key is cased
by CSS), no brackets, and the fix sentence stays.

## Noted, not fixed (outside these files)

- `partials/health_collector.html`, `account.html`,
  `partials/account_computer.html`, `partials/account_sessions.html`,
  `partials/admin_alerts.html`, `partials/admin_dashboard_update.html`,
  `partials/admin_packages.html`, `partials/recovery.html` render
  auto-layout tables with no `scroll-x` wrapper; between 760 and 1100 px a
  long cell can widen the page. Not measured here.
- `test_every_template_renders.py` fails on `/help` because another
  converter's ledger title contains the retired look's name, which that
  test forbids on every page. This ledger avoids the phrase.
