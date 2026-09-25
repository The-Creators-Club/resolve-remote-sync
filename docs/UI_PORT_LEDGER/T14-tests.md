# T14: test conversion after the collapse (six dashboard files)

Builder: test converter T14, 2026-09-25, worktree branch `ui-replace`. After
C-collapse made the terminal markup the only markup. Nothing committed, no
version bumped. Every conversion keeps the test's intent and its bug id; no
test was deleted, several were strengthened.

## Per file

- `dashboard/tests/test_static_js_syntax.py`: converted. The two "every page
  loads these scripts" lists (base.html's, shell.html's) are one list now,
  pinned against what `shell.html` actually loads (a new check reads the
  shell's `asset_url('*.js')` calls, so the list cannot drift again).
- `dashboard/tests/test_site_telemetry.py` (LG-1 / LG-4 / LG-5 / LG-17):
  converted. Telemetry switches: pinned inside the `telemetry` window inside
  `#settings-form`, with `data-initial` and the checked state read per box.
  Fleet grid: the withheld section is a `tag mute` (grey, never warn/err) in
  the row's `report-withheld` details, with `health.WITHHELD_HELP` as its
  title; licence line `ok` / `dim`. Account computer: `tag warn` licence and a
  `tag mute` withheld label. Collector retention line: rendered from
  `partials/health_collector.html`. Settings script parse and the Chrome
  confirm test: `static/cc/site_settings.js`; the page asks through its
  `<dialog id="site-ask">`, so the test reads `#site-ask-q` and answers
  Cancel, and now fails if `window.confirm` is used. The wording pinned is
  "deleted for every computer ... for good" (the terminal copy of "cannot be
  brought back") and the tick's own label, never the key `local_manifest`.
- `dashboard/tests/test_subject_data.py`: converted. `[ ERASE HISTORY ]`
  became the key `erase history` (with its visually hidden "of jsmith") on the
  `/partials/admin/users/erase-history` form.
- `dashboard/tests/test_sweep_2026_09_04_copy.py`: converted four.
  UX-6 counts: both "nothing wrong" surfaces (`home_problems.html`,
  `health_notices.html`). DUI-7: the scroller is in `shell.html`, and every
  `/go` panel's anchor exists on `/admin/health`; the home page's
  `#server-notices` is the load-triggered problems window. CR-88: the path
  constant is checked in `health_diagnostics.html` and `computer_answer.html`
  (plus `fleet_grid.html`). The comment-blanking self-test uses its own file
  instead of the deleted classic sidebar.
- `dashboard/tests/test_sweep_2026_09_04_dash_ui.py`: converted fifteen.
  DUI-1 titles are lower case (`new password for jsmith`), the copy key is a
  `.key ... copy-btn` and `cc/copy_value.js` is loaded by the shell;
  "a failed creation mints nothing" now looks for the minted window's ids,
  because every account row says "new password for <name>" on its
  set-password control and the old word check would have passed on nothing.
  DUI-2: the Syncthing warning is only in the polled `#topbar-stamp`; the
  stale banner needs a fixed rule in `cc/terminal.css`. DUI-4: the per-sheet
  `form.htmx-request` rules for the three slow forms and their `.busy-t`
  words. DUI-5 / DCORE-2: `static/cc/assignments.js`, and the error note's
  `cursor: pointer` in `settings_people.css`. REL feed: the `refused` tag next
  to the version.
- `dashboard/tests/test_sweep_2026_09_04_says_what_it_knows.py`: converted
  two. DCORE-9: `static/cc/assignments.js`. D4: a held enforce cycle is now
  asserted by its words on `/partials/health-collector` (the old test only
  checked a 200 from the deleted `/partials/admin/diagnostics`).

## Product fixes (two, small)

- `static/cc/terminal.css`: `.banner.alarm.stale-banner` is fixed to the
  bottom again, with `body[data-stale]` padding and the toast lift. The rule
  lived only in `style.css`, which terminal pages never loaded, so on every
  terminal page the DUI-2 "this page has stopped updating" banner was a plain
  `.alarm` appended after the last element: out of sight until scrolled to.
  `hud.css`'s dock offset for it assumed this rule existed.
- `static/cc/settings_people.css`: the Create keys on Settings, Users
  (`.sp-busy`) never showed their busy words ("creating the account...")
  because `terminal.css` hides `.busy-t` unless the key is `.busy`, which
  nothing sets there. Both labels now share one grid cell (the `#pw-go`
  pattern), swapped by visibility on `form.htmx-request`, so the key keeps
  its width.

## Found, not fixed (outside my files)

- `db.notice_href` still sends the collector's notice kinds to
  `/#fleet-collector`; the home page has no `#fleet-collector` any more (the
  collector window lives on `/admin/health`, which `GO_PANELS` already
  knows). The link lands at the top of the home page. The fix is
  `/admin/health#fleet-collector` in `db.py`; `tests/test_bug_hunt_2026_09_24_w2_d-db.py:464`
  pins the old value, so it belongs to whoever owns that file.
- `tests/test_every_template_renders.py` fails on `/help` because another
  ledger's title in this directory contains the retired look's name
  (T12-tests.md); not mine.
- `assignments.js` still says "change(s)" and "project(s)" in toasts (UX-10
  style); the DUI-5 test pins "change(s) failed: " and I kept it.

## Final numbers

The six files: 532 passed, 1 skipped (the skip is a pre-existing
node-absent / platform skip), 0 failed.
