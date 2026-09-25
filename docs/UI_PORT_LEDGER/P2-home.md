# P2: phase 2, home and project (group `home`)

Builder P2 (two sessions; the second resumed the first's partial work),
2026-09-25. Plan: `docs/UI_REDESIGN_PORT_PLAN.md` 1.2, 3.1, 5.1, 7.1 row 2,
R15, D7, D11, D17. Nothing committed, no version bumped.

## Built

**Server half** (`src/ccsync_dashboard/ui_home.py`, new; from session 1):
- New-named routes, each 404 when the asking page's set has no `home`
  (the classic env cannot load the template): `/partials/projects-tree`,
  `/partials/home-problems`, `/partials/home-transfers`, `/partials/home-queue`,
  `/partials/computer-answer`.
- `toggle_answer` (`view=tree`, `view=home-queue`) and `dismiss_answer`
  (`view=home-problems`), called from two small hooks in `ui.partial_toggle`
  and `ui.partial_notice_dismiss`. Tree ticks carry `machine`, `as` and
  `slug_page`; the queue untick keeps `queue_machine` as a view key.
- Jinja globals: `home_readouts` (online excludes `no_selection`
  computers; problems is the HUD's error count with warnings as the foot),
  `home_tree`, `home_roots`, `cc_meter`, `cc_lane_tone` (a muted headline
  never draws a warn/err lane), `cc_tone`, filter `cc_title`.
- `app.py`: one `include_router` line.

**Templates** (`templates/cc/`):
- `fleet.html`: head (Stop the fleet as a link to `/go/admin-fleet-halt`,
  admin only), stale alert line, side (ticking_for with editor AND computer
  pickers, projects window with the find box outside the swap target),
  main (readouts, problems.log, computers, what_computers_said with the
  empty `#fleet-diagnostics`, transfers, plan_changes, sync_queue).
  Swap hooks and ids on bodies only.
- `project.html`: head, side (same two windows, current slug), main
  (`#project-detail` wrapper polling 10 s, media_presence window with
  `#media-presence`, project_roots window whose body is `id="roots"`).
- Partials: `home_macros.html` (win, readouts, tag, ticking_for,
  projects_win), `fleet_grid.html` (frame/body split: banners and LOST
  COMPUTERS stay in the polled body, rows keep `fleet_headline` text and
  level, issues worst first (D11 log), row expander with details and the
  admin keys Resume / Ask this computer why / Read the answer, readouts and
  bar meta out of band only on htmx answers that carry the projects view,
  a folded compact projects overview (D7 default), collector included),
  `plan_changes.html` (root always `#plan-changes`, Undo kept),
  `home_transfers.html` (moving only; safe-to-close line always reserved),
  `home_problems.html` (dismiss posts `?view=home-problems` into
  `#server-notices`; the checks fold), `home_collector.html` (keeps
  `id="fleet-collector"`), `home_queue.html` + `home_fix_root.html`,
  `computer_answer.html` ("every computer" targets its own route),
  `projects_tree.html` (real `<label>` + hidden checkbox rows with
  `hx-post`, `<details data-key="grp:...">` groups, "n of m ticked"),
  `project_detail.html` (windows sync_plan, computers, shared_folders,
  move_files; every hx-post keeps its URL and `#project-detail`; the move
  form keeps `hx-on::confirm` + `window.confirm`; the key reads "Move on the
  server and on every computer"; missing-files drawers keyed
  `missing-<device_id>` with `hx-preserve`, only for rows with a device),
  `bins.html`, `missing_files.html`, `project_roots.html` (root
  `.roots-box`), `project_roots_browse.html` (`data-poll-hold` kept).
- **Static**: `static/cc/home.css` (scoped `.home-page`; 4-line row slot in
  `em`; issues are not a scroller on a coarse pointer or under 760 px;
  checkbox-drawn tree squares with a focus ring; wrapping move key; 16 px
  fields on phones), `static/cc/home.js` (IME-safe NFC find box, `/` key,
  re-filter after each tree beat, opens a hashed `<details>` once).

## Omitted controls / not built (BACKEND tickets, per the owner's rule)

- **Check now** (no route; collector not re-entrant): not drawn.
- **Stop the fleet** as a dialog on home: a link to Users until the
  compact-answer ticket lands.
- **Dismiss all** on problems.log: not drawn (only per-notice dismiss exists).
- **Lane meter percent**: state-only meter (full / empty) as recommended.
- **Size per project** in the tree: not drawn.
- Dropped by wave 6: "N behind", "on since" (tested absent).

## Departures

- `#project-detail` owns several windows (sync_plan, computers,
  shared_folders, move_files) because every answer re-renders all of them;
  it is a plain wrapper, never a `.win`, and cc.js's `htmx.onLoad` keeper
  re-applies their folds after each beat (3.1's fallback). Media presence
  and roots are static windows whose bodies poll.
- The shared fixture's `UI_VARIANT_PARAMS` was NOT changed (other builders'
  files would all gain a parameter mid-build); `test_cc_home.py` uses a
  file-local fixture over classic, chrome, `chrome,home`, all.
  Hand-off: add `chrome,home` to `UI_VARIANT_PARAMS` at merge if wanted.
- The collector sits in a folded sub-window of the computers body (it must
  refresh with the grid); home.js opens it for `/#fleet-collector`.
- Queue and plan-change status use `.tag`/`.led`, and the readouts' problems
  foot says "listed below with what to do" when there are no warnings.

## Tests (run once at the end, dashboard venv)

- `tests/test_cc_home.py` (new): **90 passed, 10 skipped** (skips are the
  terminal-only checks under the classic and chrome parameters). Covers:
  group table and files, no em dash / no bracket control in every home
  template, IME-safe find box, move key and its own confirm, no "behind"/"on
  since", first-paint look per parameter, unique ids, no hook or poll on a
  `.win`, meta ids once, no oob on first paint, problems readout equals the
  HUD count, nothing-ticked never warns (readouts and lane tone), grid poll
  per look with oob readouts and `#fleet-collector`, the five new routes
  (404/refresh without home, terminal with it), computer_answer's own
  route, dismiss answers with the problems window, tree tick answers with
  that computer's tree and the poll keeps `as`, queue untick answers with
  home_queue, plan-changes root once, project page ids and drawers, and the
  five project partials in the asking look with no bracket control.
- Regression check of the classic suites nearest the hooks:
  `test_home_layout.py`, `test_admin_tick_for_editor.py`,
  `test_upload_only.py`, `test_file_moves.py`,
  `test_fleet_grid_declutter_2026_09_11.py`, `test_static_js_syntax.py`:
  **112 passed**.

## Not run (speed rules; for the sweep / adversarial pass)

- Chrome harness checks: poll survival, Tab/Space tree keyboard test,
  composition test, READ THE ANSWER into a folded window, missing list
  surviving two beats, `.pc .issues` swipe at 390, 44 px tree rows, move
  key wrap at 390 with a CJK name, census (static and click), phone census.
- Terminal parameters on the existing classic files the plan names
  (`test_home_layout.py`, `test_mobile_fleet.py`, `test_tab_memory.py`, d-ui).
- `NEW_NAME_TWINS` poll pins and the R15 fetch-map test.

## Hand-offs

- Phase 5 cross-group rule: the collector sub-window is drawn only while
  `settings-health` is off (`fleet_grid.html`, tested both ways).
  problems.log stays on home either way (D7: "the home page's first
  question") and so does the `#fleet-diagnostics` window, which READ THE
  ANSWER needs as its target.
- Phase 3's `person_fix_root` is separate from `home_fix_root` by design.
