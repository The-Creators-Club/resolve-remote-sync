# T6: test conversion after the collapse (six dashboard files)

Builder: test converter T6, 2026-09-25, worktree branch `ui-replace`. Nothing
committed, no version bumped. The classic look is gone (C-collapse.md); these
tests pinned it or ran through the retired `ui_variant` fixture.

| File | Result | Pass |
|---|---|---|
| `tests/test_cc_settings_people.py` | converted | 20/20 |
| `tests/test_cc_settings_review_fixes.py` | converted | 17/17 (Chrome ran) |
| `tests/test_cc_settings_site_packages.py` | converted | 10/10 (node ran) |
| `tests/test_copy_sweep_phase7.py` | converted, plus one product fix | 51/51 |
| `tests/test_cr311_queue_says_on_hold.py` | converted | 5/5 |
| `tests/test_cr312_transfer_names_wrap.py` | converted | 3/3 |

All six together with `test_setup_engine.py`: 205 passed.

## How each was converted

- **ui_variant fixture, all three cc_settings files.** The fixture, the
  `_terminal()` branches and the classic halves are gone. Requests carry
  `conftest.HX` (plus `HX-Current-URL`) as the page does. `check_page`
  (data-ui-groups) became `data-ui="cc"` present and no `data-ui-groups`.
  The `@TERMINAL` parametrisation is gone. People's partial test also asserts
  a non-empty body, so an answer from the stale-page gate cannot pass as the
  partial.
- **Parity against deleted classic files.** Three tests compared a terminal
  script or panel with its classic twin, which has been deleted. Each
  comparison now uses the classic set, pinned as a constant read from
  77916b8, so the test still means "keeps every classic call or control":
  - people: `CLASSIC_CALLS` / `CLASSIC_CONFIRMS` for `setup.js` and
    `assignments.js`;
  - site: `CLASSIC_SITE_ROUTES` for `site_settings.js`;
  - packages census: `CLASSIC_PACKAGES_CONTROLS`, the four (verb, path,
    fields) that the classic `/partials/admin/packages` drew for this
    fixture. They were read by running HEAD's code from the main checkout
    (read-only, scratch script).
- **dashboard_update.js harness.** The `X-CC-UI-Want` 409 scenario was
  retired along with the header. The expired-session scenario (200 +
  `HX-Redirect`: reload, never swap) replaces it. The page header the
  script forwards is now `terminal`.
- **Site page.** `ui-groups-form` left the list of sibling forms. The test
  now asserts that `ui-groups-form` and `ui_terminal_groups` are absent.
- **Review fixes.** `_shell_inline` reads `templates/shell.html`. The two
  alerts-save tests sent `HX-Request` without `X-CC-UI`, so the stale-page
  gate answered them with an empty 200. They now send `HX`.
- **copy sweep phase 7.** Each D8 label is now checked against the
  template's own **named things**, not against `[ LABEL ]` in classic
  markup. A named thing is a key's `.t` / `.key` text, a HUD menu item
  (`hud-mi`), or a window title (`win(key, title)` or `bar(title)`). A key
  drawn as `{{ button }}` from a `{% for %}` literal list also counts. The
  match is on the whole label, never a substring. A test pins the matcher.
  Three re-pointed templates:
  - "Send a test" is now on `admin_alerts.html`;
  - "Download crash reports" is now on `partials/health_diagnostics.html`
    (`admin_diagnostics` was deleted);
  - the file-move key "Move on the server and on every computer" is now
    pinned on `partials/project_detail.html`, which the old test could not
    do.

  The `[ {{ ...href_label | upper }} ]` wrap test became: the plain label is
  drawn in a key's `.t`, and no template wraps it in brackets. It covers
  `health_notices`, `home_problems` and `admin_health` (href and detail).
  `partials/notices.html` was deleted.
- **CR-311.** Renders the terminal `partials/transfers.html` and looks inside
  `#xf-queued` (between `id="xf-queued"` and `id="xf-history"`) for:
  - the `on hold` tag;
  - the sentence;
  - the "(since" clause;
  - no em dash.

  It imports `ui_home`, which registers the `cc_title` filter every window
  title uses.
- **CR-312.** The terminal fix is a different mechanism with the same
  outcome. It no longer uses `td.path` normal + nowrap numbers in
  `style.css`. Instead, both transfer tables are `tbl fixed xft`
  (`table-layout: fixed`). The LIVE colgroup gives progress, speed and eta
  fixed widths and leaves the file column as the one bare `<col>`. Also,
  `.xft td.file { overflow-wrap: anywhere }` in `cc/everyday.css`. All of
  that is pinned.

## Deleted tests

- `test_cc_settings_people.py::test_every_cc_template_of_mine_is_registered_and_owned`:
  `ui_variant.TEMPLATE_GROUPS` and `templates/cc/` no longer exist. The
  files' existence is still covered, because the em-dash test reads each
  one.
- `test_copy_sweep_phase7.py::TERMINAL_GAPS` and its skip: there is no
  second look for a key to be missing from.

## Product fix

- `setup_engine.py` `_check_software`: the Setup task told a new customer
  to publish a build under "Available from the vendor". That was the old
  section name, and no page draws it now. The Packages window is titled
  "from the vendor" (`bar("from_the_vendor", ...)`). The task now reads
  `publish one from the "From the vendor" window`. Pinned by D8_LABELS.

## Reported, not fixed (other builders' files)

- `package_store.py:226`: the unsigned-build refusal still says `Publish the
  signed build from AVAILABLE FROM THE VENDOR instead.` That is the old
  section name, in capitals. The same fix applies ("from the From the vendor
  window"). It is pinned by `test_packages.py:426` and
  `test_bug_hunt_2026_09_24_w2_d-ops.py:677/685`, which belong to another
  converter.
