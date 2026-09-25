# P4b: phase 4, second half (group `settings-fleet`): Users, Sync plans, Jobs, History, Setup

Builder P4b, 2026-09-25 (two sittings: the templates in the first, the rest
on resume). Plan: `docs/UI_REDESIGN_PORT_PLAN.md` 1.3, 3.1, 3.2, 5.3, 7.1 row 4.
Nothing committed, no version bumped. P4a owns Site and Packages.

## Built

- **Users**: `cc/admin_users.html` (page: the frames), `cc/partials/admin_users.html`,
  `admin_sessions.html`, `admin_report_tokens.html`, `fleet_halt.html`,
  `admin_suspend_button.html`, `minted_secret.html`. Frames split (3.1):
  sessions, report tokens and the fleet stop each have a `.win` frame in the
  page whose `.body` polls (load + 30/60/60 s, innerHTML); each partial is the
  body, with `#admin-sessions`, `#admin-report-tokens`, `#admin-fleet-halt`
  on a div inside the body, and every form in it targets that id outerHTML as
  classic. The users partial is one swap unit of several windows
  (`closest .admin-users-box`, a plain div): cc.js's keeper re-applies folds.
  Every route that renders these (all `ui.py` handlers and `account_ui.py`'s
  display-name POST) draws the cc shape through the overlay, no route edits.
  `#minted-secret` sits in the page outside every window and poll; the minted
  window is `data-nofold` with no fold button and no `data-win` (wave 5).
- **Sync plans**: `cc/admin_assignments.html` + `static/cc/assignments.js`
  (fork: same PUT/DELETE/copy calls, same three `window.confirm`s, toast
  host `#assign-toast.sp-notes`). The computer select is filled in the
  browser from `picker.machine_map` (JSON in `#assign-machine-map`), built in
  `assignments.py` (4 lines, the classic page ignores it). Free space and
  proxy size shown as text. ARCHIVE keeps its `onsubmit` native confirm.
- **Jobs**: `cc/admin_jobs.html` + `cc/partials/admin_jobs.html` (self-poll
  15 s outerHTML keeps `?finished=1`; windows inside ride the keeper).
- **History**: `cc/admin_audit.html` (frame) + `cc/partials/admin_audit.html`
  (body with the `q` filter).
- **Setup**: `cc/setup.html` + `static/cc/setup.js` (fork of `setup.js`: same
  fetch calls, ids, form names and post-create reload; plain labels; the step
  strip and each step's bar show the checklist status; "Your studio"
  prefilled from `GET /api/v1/admin/site` when signed in, and a save sends
  only changed or newly filled fields, so an untouched default is never
  written as an explicit value; server text via textContent; errors land in
  the failing step and unfold it through `ccsyncRevealField`). The settings
  strip only for a signed-in visitor (first run is anonymous), as classic.
- `static/cc/settings_people.css`: the five pages' few rules (`sp-*`,
  saving pulse, the notes host above the dock, fixed field widths).
- Headings: every window's `h2.t` has an id, the section is
  `aria-labelledby` it, underscores are `aria-hidden` with a hidden space
  (same output as P2's `cc_title`, done in markup/macros so these pages do
  not depend on `ui_home` being imported).
- `ui_variant.TEMPLATE_GROUPS`: 13 rows for the files above.

## Omitted controls (backend tickets, not built)

- Names on Users and Jobs linking to a per-person page (`user.html`, 5.2).
- Real paging on History (the bench's pager; `fetch_audit` offset).
- Nothing the classic pages have is dropped. The sidebar is dropped on all
  five (D17); the census allow-list entries for that move are not written.

## Departures

- Window titles in the bars stay the bench's snake_case, drawn accessibly;
  the minted window's title is plain words (it carries a username).
- The users partial keeps its windows inside the swap unit (keeper fallback)
  instead of splitting accounts/computers/keys into separate routes.
- Setup ids `setup-step-N` on the step windows (anchors for the strip), not
  `win-<data-win>`.

## Tests (run once, dashboard venv)

- `tests/test_cc_settings_people.py` (new): 51 passed (classic, chrome, all
  per page and partial: look, hooks, swap targets never on `.win`, unique
  ids, `aria-labelledby`, typed buttons, `hx-confirm` only on htmx elements,
  no bracket labels, no underscore in heading names, minted secret never in a
  foldable window, ARCHIVE native confirm, machine map, setup ids and
  script, registry rows, forked scripts' calls and confirms, no em dash).
- Touched classic: `test_admin_assignments.py` + `test_static_js_syntax.py`
  63 passed.
- Not run: the Chrome checks of the phase row (fold-then-mint visibility in a
  real browser, folding sends no PUT, census), the sweep, screenshots.

## Hand-offs

- Census/sweep owners: D17 moves for the five pages' sidebar POSTs.
- `test_mobile_admin.py` twins against `cc/phone.css`, `test_jobs_retry.py`,
  `test_fleet_halt.py`, `test_hardening.py` terminal parameters are not
  added; the new file covers the same hooks under `ui_variant`.
