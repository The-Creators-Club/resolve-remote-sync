## Settings, then SYNC PLANS: one person, one computer at a time, 2026-09-11

Not a hunt finding: the owner read the page and said what was wrong with it.
Verbatim: "rebuild this so it's filtered by default, by user and then by
computer, instead of showing all users at once, because if there are many many
users in a company, this would be very unwieldy."

The grid was projects x EVERY column in the fleet, and a column is a COMPUTER
(MULTI_MACHINE_PLAN.md WP5), so a fifteen-editor site with two machines each
opened on a thirty-column table before anybody had said who they came to look
at. It scrolled sideways by design, which is what made it survivable and also
what made it unreadable.

### What changed

`/admin/assignments` takes `?editor=<name>&machine=<host>` and renders the
grid only when both have been answered. The pickers are one plain GET form at
the top of the page (`.assign-pick`), so the choice is in the URL: a reload, a
bookmark and a link from anywhere land on the same plan, and there is no
JavaScript behind the filter to break.

The machine picker's values are the ones the rest of the product already uses:
a hostname from the `machines` registry, `""` for the unassigned bucket
(`db.ANY_MACHINE` - offered when the person has no computer yet, or carries
bucket rows no computer has claimed), and `*` for "this person, every
computer", which is the view a request with NO `?machine=` already means in
`db.selections_for_machine` and the tick API. `*` needs a spelling only here,
where "not chosen yet" and "all of them" are two states of one URL; a hostname
cannot contain it. The picker's own placeholder is `-` for the same reason:
`""` is a real answer on this page.

Preselection, so a small site is not made emptier for the sake of a large one:
exactly one known editor and no `?editor=` preselects them; a chosen person
with exactly one computer (a real machine, or the bucket when that is all they
have) preselects it. Otherwise nothing. A `machine` that is not that person's
is NOT a choice - it is what the form posts when the PERSON was changed in the
same submit, and the honest answer is their computer picker rather than an
empty grid for a computer they do not own.

The grid itself, its cells, the `up` upload-only box, [ ALL ] / [ NONE ] /
copy-from, the toast host and every write are untouched: `assignments.js` is
unchanged, and each cell is still the same PUT/DELETE
`/api/v1/selection/{editor}/{slug}` an editor's own tick makes.
`_assignments_view` gained two optional filters that narrow the COLUMNS only;
both default to None, which is the whole-fleet shape its existing callers (and
`test_bug_hunt_2026_09_11b_dash_db.py`) still get.

Two things that would otherwise have been lost:

- **The fleet's size.** The old page said it by being it. There is now one
  muted line beside the pickers: N people, N computers, N projects.
- **[ ARCHIVE ] / [ UNARCHIVE ] came back to an empty page.** Both forms POST
  and redirect (DCORE-5, deliberately not an htmx swap), and the redirect was
  the bare address. They carry the person and computer now and
  `ui.partial_admin_archive_project` redirects back to that plan. The archived
  list itself stays whole-fleet, below the grid, where it was.

One bug found while writing it, worth recording because it is a shape that
will recur: `_assignments_view`'s column loops bind `editor` and `machine` of
their own, so a filter written against the parameters of the same name read
the LAST column built instead. The wanted values are captured at the top of
the function now.

### Files

- `dashboard/src/ccsync_dashboard/assignments.py` - `MACHINE_ALL`,
  `_machine_options`, `_picker`, the two column filters on
  `_assignments_view`, and the route's query parameters
- `dashboard/templates/admin_assignments.html` - the picker form, the
  empty-state copy, the grid behind `picker.show_grid`, the archive forms'
  hidden `editor`/`machine`
- `dashboard/src/ccsync_dashboard/ui.py` - `partial_admin_archive_project`
  redirects back to the plan that was on screen
- `dashboard/static/style.css`, `dashboard/static/mobile.css` -
  `.assign-pick` (a wrapping one-line form; full-width selects on a phone)

### Verification

From `dashboard` with `.venv\Scripts\python.exe -m pytest <file> -q`.

New in `tests/test_admin_assignments.py`: the page opens with the pickers and
no grid; choosing a person offers their computers and still no grid; a
computer that is not theirs is not a chosen computer; the one-editor /
one-computer preselect (and that a second computer takes it away again); the
unassigned bucket is `machine=""` and is that person's only column; `machine=*`
is the person-wide view and shows nobody else; the fleet size is still said in
one line; [ ARCHIVE ] redirects back to the same plan.

Updated: the seven grid tests in `tests/test_admin_assignments.py` now ask for
a plan (a `grid()` helper, `machine="*"` where the test is about a person's
columns), `tests/test_mobile_admin.py`'s sideways-scroll test and
`tests/test_cross_seams_2026_08_21.py`'s wired-column test likewise.

Run: `test_admin_assignments.py`, `test_mobile_admin.py`,
`test_cross_seams_2026_08_21.py`, `test_no_em_dash.py`, `test_upload_only.py`,
`test_hand_off_2026_09_11b_dash_mounts_ui.py`, `test_settings_hub.py`,
`test_mobile_css.py`, `test_sweep_2026_09_04_dash_ui.py`,
`test_templates_wave3_2026_09_04.py`, `test_help_page.py`,
`test_bug_hunt_2026_09_11b_dash_db.py`, `test_sweep_2026_09_04_copy.py`,
`test_sweep_2026_09_04_second_customer.py` - 785 passed, 2 skipped.

### Owner decisions

- The page still BUILDS the whole-fleet view model on every load (presence,
  proxy bytes, disk, all selections) and then renders one person's columns
  out of it. What the owner asked for was the reading, and that is fixed; the
  reads themselves are the same ones the page has always made, so nothing new
  can go wrong. Narrowing them is a separate change with its own risk.
- The archived-projects list and the [ UNARCHIVE ] buttons stay whole-fleet:
  an archived project belongs to nobody, and hiding it behind a person's name
  would make it unreachable.
- "Every computer" is offered only when the person has more than one column,
  because with one it is the same view under a second name.

### Owed to another territory

- none. No route, schema or write path changed; `assignments.js` was not
  touched.
