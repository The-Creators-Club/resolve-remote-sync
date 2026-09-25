# T7: six dashboard test files onto the terminal look

Test converter T7, 2026-09-25, worktree branch `ui-replace`, after
C-collapse deleted the classic look. Tests only; no product code changed.
Nothing committed, no version bumped. Final: **141 passed, 0 failed** over
the six files.

## tests/test_cr335_packages_page.py (CR-335): 2 converted
- The busy label: `[ MAKING IT CURRENT... ]` is now the key's
  `<span class="busy-t">making it current</span>` beside `make current`.
- The refusal on the clicked row: rows split on `<tr class="pkg-row">`;
  "no top-of-panel banner" now asserts no `error-banner` at all.

## tests/test_dashboard_update.py: 4 converted
- The applied tree is checked for `templates/shell.html` (was `base.html`,
  deleted).
- The section: the partial carries `id="dashboard-update"`, a
  `data-dashupd-apply="<version>"` key labelled `update now`, and the
  Packages page carries the `this_dashboard` window that loads it (the
  classic `[ DASHBOARD ]` head is now that window's bar).
- Bind-mount and runtime-update: "no update button" is now "no
  `data-dashupd-apply`"; `RUNTIME UPDATE` is the `runtime update` tag.
- `reloadPanel` guard (dash-mounts-ui-3): reads `static/cc/dashboard_update.js`
  (the classic `static/dashboard_update.js` is deleted), and additionally pins
  the HX-Refresh check before the swap (the stale-page answer).

## tests/test_diagnostics.py: 3 converted
- The fleet grid on `/` carries the `Ask this computer why` key (UX-16).
- The admin partial `/partials/admin/diagnostics` is gone; the same
  newest-per-machine and per-machine-history assertions now run against both
  of its terminal homes, `/partials/health-diagnostics` (Health) and
  `/partials/computer-answer` (home READ THE ANSWER).
- Ask-why answer: the `asked why` tag, and no `Ask this computer why` key.

## tests/test_file_moves.py: 6 converted
Bracket chips to terminal tags/keys, same facts: `not applied: this computer
may upload the old path again` + `Ask that computer again`, `some proxies
stayed`, `unfinished on the server`, `Undo this move`, `1 blocked`, `Move on
the server and on every computer` (admins only; the non-admin check also
asserts the move form's hx-post is absent), and the move answer's `moved` +
`done` tags.

## tests/test_fleet_audit.py: 4 converted
- History page: the `what-changed` window (was `[ WHAT CHANGED ]`); the
  filter's empty line is now capitalised "Nothing in the timeline matches".
- Home panel: `#plan-changes` with an undo form and its `Undo` key.
- `test_an_empty_hour_renders_no_panel_at_all` renamed
  `test_an_empty_hour_offers_nothing_to_undo`: the terminal home keeps the
  plan_changes window and draws a muted all-clear by design (plan 5.1), so the
  test now asserts no table and no `/undo`, and the all-clear line.
- Project page untick (DASH-8): the confirm is asserted ON the `Untick for
  ruskin` key itself (regex over the button), not just somewhere on the page.

## tests/test_fleet_grid_declutter_2026_09_11.py: 4 converted
The helper now cuts the computers' rows (from `pc head-row` to the lost /
projects sub-windows). A shared `FAULT_CLASSES` list (row tone, LED, headline,
lane, tag; checked against a real error-lane row to be the classes the
template really draws) replaces the classic chip-colour checks.
- Healthy row: no fault class anywhere, three lanes in fixed order
  (upload, proxy download, folder sync) all idle, muted headline, `nothing
  wrong` in issues.
- Nothing ticked (owner rule): the muted sentence, no fault class anywhere.
- Clutter: exactly one collapsed `<details class="more">` per row whose
  summary says `4 notes` and names them in its title; the problems themselves
  are inline issue tags (D11), including `2 stray project dirs`. The classic
  `<dt>PROBLEMS</dt>` list has no terminal twin and its check was dropped with
  it (the issues column is that list).
- Buttons: `acts row-actions` holds `Ask this computer why` and `Resume` with
  the same routes, target and editor/machine fields, and neither key is inside
  the issues column.

## Deleted tests
None.

## Product bugs found
None.
