# dash-mounts-ui - the dashboard's HTML surfaces, the three SPA mounts, the static/PWA layer, the deploy scripts and the release workflows

Files read (with approximate coverage):
- `dashboard/src/ccsync_dashboard/ui.py` (the whole 34a3c8f..HEAD diff, plus
  `_fleet_view`, `_packages_and_feed`, `_vendor_rows`, `_kind_platform_groups`,
  the PWA routes `/manifest.webmanifest`, `/sw.js`, `/offline`, and
  `partial_admin_archive_project`) - ~40%
- `dashboard/src/ccsync_dashboard/broll.py`, `music.py`, `ytdl.py` (the
  18e69f3..34a3c8f diff in full: `_account_bar`, the three `_fleet_stamp`
  suspension gates, the three `record_root` calls) - ~35%
- `dashboard/templates/partials/admin_packages.html` (rewritten, read in full),
  `partials/fleet_grid.html` (rewritten, read in full),
  `admin_assignments.html` (read in full),
  `partials/admin_dashboard_update.html` (the current.json readers)
- `dashboard/static/sw.js` (full), `style.css` / `mobile.css` (the new class
  block and the `.stack` rules)
- `dashboard/deploy/select_code_root.py` (full), `deploy/run.sh` diff,
  `deploy/Dockerfile` diff, `deploy/requirements.txt` / `.lock` diff
- `.github/workflows/release-macos.yml` (the artifact change + the two build
  steps), cross-checked against `tools/release_macos.sh` and
  `tools/build_onboard_macos.sh` output paths
- Read as callees, not reported on: `api.build_packages_view`,
  `package_store.make_current_refusal`, `release_feed.build_feed_view` /
  `_record_key` / `package_records`, `health.lane_strip` /
  `fleet_headline` / `detail_notes` / `why_causes`, `assignments.py`
  (`_picker`, `_machine_options`, `_assignments_view`),
  `mount_status.record_root` / `recheck`, `dashboard_update.status`.

Tests run:
- `cd dashboard; .venv\Scripts\python.exe -m pytest tests/test_admin_assignments.py tests/test_packages.py tests/test_select_code_root.py tests/test_pwa.py tests/test_mount_status.py tests/test_bug_hunt_2026_09_11b_dash_mounts_ui.py tests/test_hand_off_2026_09_11b_dash_mounts_ui.py -q` -> **185 passed**
- two ad-hoc snippets against the dashboard venv (TestClient + `db`), output
  quoted in findings 3 and (negatively) in the coverage note.

## Findings

### dash-mounts-ui-1 - CR-270 writes `retired_from` / `retired_reason` into a file no surface reads, so an applied OTA update vanishes from Settings with no word
- Severity: medium
- Confidence: CONFIRMED
- Where: `dashboard/deploy/select_code_root.py:441-452` (writes the keys),
  `dashboard/src/ccsync_dashboard/dashboard_update.py:1592-1609` (the FIXED
  key set that does not carry them),
  `dashboard/templates/partials/admin_dashboard_update.html:22-35` (renders
  `reverted_reason` and `revert_refused_reason` only)
- What: CR-270's new retire branch clears `current.json` and records
  `retired_from` / `retired_reason` beside it. `dashboard_update.status()`
  builds its `current` dict from a deliberately fixed key list
  (`version`, `previous`, `applied_at`, `reverted_reason`,
  `revert_refused_reason`, `revert_refused_from`) and the Settings partial
  renders that dict, so neither key reaches the API body, the page, a notice
  or an alert. This is the same shape as res-fleet-3, which was fixed one
  commit earlier for `revert_refused_reason` with the comment "a refusal that
  reaches no API body reaches no notice and no alert either" - and the retire
  branch was then added without the matching read.
- Failure scenario: a site applies dashboard 0.7.46 over the air; weeks later
  a 0.7.49 image is deployed. On the next boot `select_code_root` retires the
  tree, clears `current.json` and logs `RETIRED 0.7.46 ...` to the container
  log. Settings -> the dashboard update panel now shows no applied version and
  no reason at all; an admin who applied that update and is looking for it is
  told nothing, and `previous` has been cleared too, so the tree cannot be
  named as a rollback candidate either. The only record is a stderr line in a
  container log the appliance's whole promise says nobody should need.
- Evidence: `grep -rn "retired_from\|retired_reason" dashboard/` matches only
  `deploy/select_code_root.py`; `dashboard_update.py:1592` and the template
  both enumerate their keys by name.
- Ledger: new (CR-270 does not fix the surfacing half; same shape as
  res-fleet-3, which IS fixed)
- Suggested fix: add `retired_from` / `retired_reason` to
  `dashboard_update.status()`'s `current` dict and render one calm line in
  `admin_dashboard_update.html` ("0.7.46 was retired: this image carries it"),
  the way `reverted_reason` is already rendered.

### dash-mounts-ui-2 - the new vendor section calls a locally RECALLED build "[ STAGED, NOT CURRENT ]" and offers [ MAKE CURRENT ] on it, and hides a sha conflict behind the same word
- Severity: medium
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/ui.py:3584-3620` (`_vendor_rows`,
  the `state` computation), `dashboard/templates/partials/admin_packages.html`
  (the `vendor_row` macro, the `state == "held"` branch)
- What: `_vendor_rows` classifies a vendor record as `current` / `held` /
  `available` purely on "is there a `companion_packages` row with this
  (kind, platform, version), and is it current". It reads neither
  `retracted_at` nor the sha. The `package_row` macro is careful about both
  (`{% if not p.retracted %}` guards MAKE CURRENT, and `build_feed_view`
  routes a sha mismatch into `conflicts` rather than into `available`), but
  `vendor_row` reproduces neither guard.
- Failure scenario: the vendor recalls companion 0.9.74 (`retracted_at` set on
  this server's row by the feed poller). In [ AVAILABLE FROM THE VENDOR ] the
  row renders as `[ STAGED, NOT CURRENT ]` with a live [ MAKE CURRENT ]
  button; the [ RECALLED ] chip only exists in the collapsed
  [ OTHER VERSIONS HELD ON THIS SERVER ] section below. The admin clicks and
  gets a 409 error banner - the gate holds (`package_store.make_current_refusal`
  refuses a retracted row first, before any confirmation) - but the page has
  offered an action it knows cannot work, on the one build it must steer them
  away from. Separately, a version this server published from a DIFFERENT
  binary (`release_feed.sha_conflict`, the `--allow-replace` case) is shown as
  "held", i.e. as if the vendor's bytes were already here.
- Evidence: read `_vendor_rows` (no `retracted`/`sha256` in the emitted dict)
  against `build_packages_view` (which does emit `retracted`) and
  `package_store.make_current_refusal:196-205` (the 409).
- Ledger: new
- Suggested fix: carry `retracted` and the held row's `sha256` into the vendor
  dict; render `[ RECALLED ]` and suppress MAKE CURRENT exactly as
  `package_row` does, and give a sha mismatch its own state word rather than
  letting it read as "held".

### dash-mounts-ui-3 - the Assignments computer picker offers the unassigned bucket to a person who HAS computers, and choosing it renders "this person has no computer to show a plan for yet"
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/templates/admin_assignments.html:41-56` (the picker and
  the `not assignments.columns` branch),
  `dashboard/src/ccsync_dashboard/assignments.py:171-186` (`_machine_options`)
  and `:88-110` (`_assignments_view`'s column loop)
- What: `_machine_options` appends the `db.ANY_MACHINE` option whenever
  `db.selections_for_machine(conn, editor, ANY_MACHINE)` is non-empty - i.e.
  whenever that person carries bucket ticks no companion has adopted - even if
  they also have real machines. `_assignments_view` only ever builds a
  bucket COLUMN for a person with NO machines at all (`if not machines:`), so
  selecting that option filters every column away and the template falls into
  the "this person has no computer to show a plan for yet" branch, which is
  false: they have one.
- Failure scenario: editor1 ticks a project before their companion ever
  reports (a bucket row), then DESKTOP-1 reports. The picker offers "no
  computer yet (ticks no computer has claimed)"; picking it and pressing
  [ SHOW ] gives an empty page saying the person has no computer. The bucket
  rows, which `db.selections_for_machine` still honours for any machine with
  no plan of its own, can be neither inspected nor removed from this page.
- Evidence (dashboard venv, TestClient):
  ```
  machines_of ['DESKTOP-1']
  bucket rows ['ff5']
  bucket option offered: True
  empty-grid message: True
  grid shown: False
  ```
  (Mitigation worth stating: `db.fetch_machine_selections` DOES expand the
  bucket onto real machines, so the DESKTOP-1 column's checkbox renders
  ticked and correct - the damage is confined to the dead-end option and the
  false sentence.)
- Ledger: new (CR-267e, `ledger/assignments-page-filter.md`)
- Suggested fix: either do not offer the bucket option to a person who has a
  real machine, or let `_assignments_view` build the bucket column whenever
  bucket rows exist; and change the empty-grid sentence so it cannot claim a
  person has no computer when the picker just listed one.

### dash-mounts-ui-4 - the fleet-grid declutter moved five amber conditions behind [ DETAILS ] that neither the headline nor the note count knows about, so folding a row hides them in silence
- Severity: medium
- Confidence: CONFIRMED
- Where: `dashboard/templates/partials/fleet_grid.html:217-315` (the
  `row-details` fold and the `problems` block),
  `dashboard/src/ccsync_dashboard/health.py:961-1010` (`detail_notes`),
  `dashboard/src/ccsync_dashboard/ui.py:659` (where the count is computed)
- What: `detail_notes`' own docstring says its count "is the one thing shown
  beside the collapsed expander, so that folding a row's diagnostics away can
  never hide a real problem silently". Five conditions that render an amber
  chip inside the now-collapsed block are in neither `detail_notes` nor
  `why_causes`/`fleet_headline`: `skipped_exists` ([ WON'T UPLOAD: n ]),
  `transport.express_last_error` ([ EXPRESS UPLOAD FAILED ]),
  `transport.express_dropped`, `guard.trash_bytes` > 5 GB and
  `guard.ingest_staging_bytes`. Before 2026-09-11 all five were on the row
  itself.
- Failure scenario: an editor's express upload has been failing for a week
  (`express_last_error` set, lane A otherwise "idle" and green). The row's
  headline reads "Idle, nothing owed" in muted grey, the three lane chips are
  quiet, and [ DETAILS ] shows no note count at all - the one place the
  failure is stated is inside a fold with nothing to suggest opening it. Same
  for a machine that is refusing to upload n files, or holding footage in its
  drop folder that exists on one disk.
- Evidence: `grep -c "skipped_exists\|express_last_error\|express_dropped\|trash_bytes\|ingest_staging_bytes" dashboard/src/ccsync_dashboard/health.py` -> `0`; the same identifiers all appear in `fleet_grid.html` inside the `{% set problems %}` block.
- Ledger: new (CR-267f, `ledger/fleet-grid-declutter.md`)
- Suggested fix: add those five to `health.detail_notes` (they are exactly its
  "states a person would act on"), so the count beside the collapsed summary
  is honest again.

### dash-mounts-ui-5 - a lane a machine never reported is drawn in the same quiet colour as a healthy one
- Severity: medium
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/health.py:877-883` (`lane_strip`
  gives an unreported lane `"chip": GREEN`),
  `dashboard/templates/partials/fleet_grid.html:206` (`{{ "quiet" if lane.chip == "green" else lane.chip }}`)
- What: the fixed three-lane strip fills a lane the report did not carry with
  `state: "not reported"` and `chip: GREEN`, and the template maps green to
  `quiet`. The strip carries a `reported: False` flag that nothing renders. So
  "this lane did not report" and "this lane is fine" are the same grey box,
  differing only in the word inside it - which is the "could not check must
  never render as a reassurance" rule the same file states twice (the disk
  chip's comment: "'could not check' must never render as a green
  reassurance"; the Resolve block's: "silence, never a reassuring
  'connected'").
- Failure scenario: a companion whose lane C section is missing from the
  report (an older build, or a report truncated by the model boundary) shows
  `folder sync: not reported` in the same colour as its two healthy
  neighbours. An admin scanning fifty rows for the one that is not grey sees
  nothing.
- Evidence: read `lane_strip` and the template line side by side; `reported`
  is produced and never consumed (`grep -rn "reported" dashboard/templates/partials/fleet_grid.html` finds only "not reported" inside `lane.state`).
- Ledger: new (CR-267f)
- Suggested fix: use the `reported: False` flag the strip already carries -
  draw an unreported lane in the "cannot tell" style (dashed/amber-muted),
  never in the healthy one.

### dash-mounts-ui-6 - the b-roll mount records its PROXIES directory as its root, so a degraded-mount notice names the wrong path
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/src/ccsync_dashboard/broll.py:592` (`mount_status.record_root("broll", str(broll_config.get_proxies_dir()))`),
  against `music.py:468-469` and `ytdl.py:736-737` (both `record_root(root, witness=...)`),
  and `mount_status.record_root`'s docstring at `mount_status.py:74-88`
- What: dash-mounts-ui-b-1 was first fixed in b-roll by replacing the recorded
  root with the proxies directory; the hand-off wave then added a `witness`
  parameter and updated music and ytdl to pass root AND witness, but left
  b-roll on the older single-argument shape. `record_root`'s docstring states
  the contract the other two now follow: "The root is still what the degraded
  sentence names: the admin has to be told which mount is gone, not which
  file this server happened to stat."
- Failure scenario: `/broll-data` stops being mounted. The collector's
  `recheck` correctly downgrades the b-roll mount (the proxies directory is a
  real witness, inside the root), but the notice and the home-page sentence
  name `/broll-data/proxies` as the missing root, sending the admin at the
  NAS to look for a subdirectory rather than at the bind mount.
- Evidence: the three call sites read side by side; `mount_status.record_root`
  stores `(root, witness)` and every message formats the first element.
- Ledger: related to dash-mounts-ui-b-1 (fixed 2026-09-11b) - the hand-off
  wave updated two of the three mounts
- Suggested fix: `mount_status.record_root("broll", str(broll_config.get_data_root()), witness=str(broll_config.get_proxies_dir()))`.

## Coverage note

Not reached, and worth another pair of eyes:
- `ui.py` is ~4,400 lines and I read the week's diff plus the packages, fleet,
  PWA and archive-redirect paths. The setup/provisioning partials, the project
  page, `/help` and the jobs partial were not read.
- I did not exercise the Packages page against a populated feed cache
  (`release_feed.verified_records` is process-local and empty until a check
  runs), so `_vendor_rows` was read, not run. Findings 2's classification
  logic is a code reading.
- `dashboard/deploy/Dockerfile` and `compose` were read only in diff; the
  four-root PYTHONPATH and the `app` / `musicweb` / `ytdlweb` collision rule
  were not re-verified against the image.
- The suite has no test that renders `partials/fleet_grid.html` with a row
  carrying `express_last_error` / `skipped_exists` and asserts anything about
  the note count (finding 4), none that renders a RECALLED build in the vendor
  section (finding 2), and none that picks the bucket option on
  `/admin/assignments` (finding 3). `test_select_code_root.py` covers the
  retire branch's file writes but nothing asserts that the reason reaches a
  surface (finding 1).
- `.github/workflows/*` beyond `release-macos.yml` (ci.yml, release-windows)
  were not read.

## OUT OF TERRITORY
- `dashboard/src/ccsync_dashboard/health.py`: `detail_notes` and `lane_strip`
  are where findings 4 and 5 must actually be fixed (dash-collector-alerts).
- `dashboard/src/ccsync_dashboard/assignments.py`: `_machine_options` /
  `_assignments_view` are the code half of finding 3 (dash-db).
- `dashboard/src/ccsync_dashboard/dashboard_update.py:1592`: the fixed key set
  is the code half of finding 1 (dash-release-jobs).
- `broll.py` / `music.py` / `ytdl.py` `_account_bar`: every fleet-stamped
  request now opens and closes a fresh sqlite connection to the dashboard DB
  before the sub-app sees it - correct, but it is a per-request connect on the
  ingest hot path and worth a look from res-fleet under the new busy-DB rule.
