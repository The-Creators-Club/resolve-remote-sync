# dash-mounts-ui - the dashboard's mounts, page chrome, templates, static assets, deploy and CI

Files read (with approximate coverage):
- `git diff` over the whole territory, every hunk (100%): `dashboard/src/ccsync_dashboard/ui.py`,
  `broll.py`, `dashboard/templates/{cards_landing.html, partials/admin_dashboard_update.html,
  partials/admin_packages.html, partials/fleet_grid.html, partials/project_detail.html}`,
  `dashboard/static/style.css`, `dashboard/deploy/select_code_root.py`,
  `.github/workflows/{ci.yml, release-macos.yml, release-windows.yml}`.
- `dashboard/deploy/select_code_root.py` in full (main, check_tree, revert_refusal,
  record_revert_refusal, _retire, revert, boot counters).
- `ui.py`: CHIP_HELP / chip_help / skipped_scope, `_vendor_state` / `_vendor_rows` /
  `_packages_and_feed`, the Jinja env globals (~30% of a 4.5k-line file, chosen by the diff).
- `dashboard/templates/partials/admin_packages.html` (vendor_row + package_row macros in full),
  `fleet_grid.html` lanes/guard chips, `admin_dashboard_update.html`, `cards_landing.html`.
- `dashboard/static/sw.js` (cache/pass-through rules), `style.css` chip rules.
- Callees on both sides of every wire the diff touches: `mount_status.record_root/recheck/root_of`,
  `health.lane_strip`, `api.build_packages_view`, `release_feed.sha_conflict/build_feed_view`,
  `dashboard_update.status()` + `apply`, `notices._check_broll_archive`, `alerts` b-roll archive
  check, `db.mark_file_move_applied`, `broll/web/app/routes_api.insert_target_detail`,
  `cards_landing._state`, `tools/release.ps1` + `tools/release_macos.sh` (the other end of
  `CCSYNC_REQUIRE_FFMPEG`).
- Tests: `test_bug_hunt_2026_09_18_dashboard_lows.py` (the dash-mounts-ui-2 and regression-3
  sections), `test_bug_hunt_2026_09_18_dashboard_mediums.py` (dash-api-4/dash-mounts-ui-5,
  dash-mounts-ui-6), `test_select_code_root.py`, `test_broll_mount.py`, `test_no_em_dash.py`.

Tests run:
- `dashboard\.venv\Scripts\python.exe -m pytest tests/test_bug_hunt_2026_09_18_dashboard_lows.py
  tests/test_bug_hunt_2026_09_18_dashboard_mediums.py tests/test_broll_mount.py
  tests/test_select_code_root.py -q` -> 126 passed.
- Scratch boot harness against the real `select_code_root.main()` (scratchpad, outside the repo)
  driving three consecutive boots of a retired tree -> see dash-mounts-ui-1.

## Findings

### dash-mounts-ui-1 - a retire carries a refusal the admin can never clear, and the banner tells them to restore a backup
- Severity: medium
- Confidence: CONFIRMED
- Where: `dashboard/deploy/select_code_root.py:361-382` (`_retire`) and
  `dashboard/deploy/select_code_root.py:437-506` (`main`, the early `if not version:` return),
  rendered at `dashboard/templates/partials/admin_dashboard_update.html:32-35`.
- What: regression-3 made `_retire` CARRY `revert_refused_reason` / `revert_refused_from` into the
  retired record. But `_retire` also sets `version: ""`, and on every later boot `main()` returns at
  `if not version:` before the clearing rule (`revert_refused_reason and already_failed == 0`) is
  ever reached. So the carried refusal becomes permanent state with no code path that removes it,
  while the refusal it describes is by construction no longer true: the retire only happened because
  `revert_refusal("")` returned "" for this very database.
- Failure scenario: an OTA tree 0.7.43 fails its boots, the automatic revert to 0.7.40 is refused
  on schema (`revert_refused_reason` recorded). The admin follows the refusal's own advice and
  deploys a newer image (0.7.50, schema v54). Boot 1 retires 0.7.43 correctly and copies the stale
  refusal across. From then on, for ever, Settings -> the dashboard-update panel shows
  "▲ this dashboard did not roll itself back automatically: 0.7.40 knows database schema v47 and
  this database is on v54: booting it would fail on every start. Restore the backup taken before
  this update and roll back from the dashboard", on a container that is booting the image happily.
  The remedy it prints (restore a backup) is a destructive act on a healthy server.
- Evidence: scratch run of the real `main()` (stubbed `check_tree` only), three boots:
  boot 1 prints `RETIRED 0.7.43: ... the image carries it` and writes
  `{"version": "", "retired_from": "0.7.43", "revert_refused_reason": "0.7.40 knows database schema
  v47 ...", "revert_refused_from": "0.7.43"}`; boots 2 and 3 leave the file byte-identical. The only
  writer that drops the keys is `dashboard_update.py:1439` (a later APPLY), so the banner survives
  every restart until another OTA update is applied. `dashboard/tests/test_bug_hunt_2026_09_18_
  dashboard_lows.py:test_a_retire_keeps_an_earlier_refusal_where_the_alert_looks_for_it` pins the
  carry and never boots a second time, so it cannot see this.
- Ledger: regression-3 (uncommitted, CR-285 wave) opens a neighbour; new.
- Suggested fix: carry the refusal only when it is still true - re-ask `revert_refusal("")` (or
  simply drop the two keys in `_retire`, since the image has just been judged able to run the
  database) - or make the `if not version:` early return run the clearing rule first.

### dash-mounts-ui-2 - the new "do not retire" branch keeps a tree that `check_tree` then refuses anyway, so the image boots regardless
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/deploy/select_code_root.py:462-487` (the retire branch) against
  `dashboard/deploy/select_code_root.py:252-255` (`check_tree`).
- What: regression-3's guard says "a refusal keeps the tree". It does not. The branch is entered
  exactly when `installed <= image`, and `check_tree` refuses any tree for which
  `installed <= image` with "the image wins". So after recording the refusal, `main()` falls through
  to `check_tree`, gets a refusal that is NOT environment-shaped, bumps `boot_attempts`, prints
  `image_pythonpath()` and boots the image - the very code the refusal said "would fail on every
  start". Two boots later the MAX_BOOT_ATTEMPTS arm runs `revert_refusal(previous)` and records a
  second refusal. The net behaviour is identical to before the fix, plus a growing counter and a
  refusal record written on every boot.
- Failure scenario: an image whose version is >= the applied tree's but whose schema is older
  (the case the fix was written for): the dashboard still boots the image and still raises out of
  `db.migrate()` on every start; the only difference is that the panel now says so.
- Evidence: code read of both branches; the branch condition `installed and image and
  installed <= image` is precisely `check_tree`'s refusal condition at line 253, and no path
  between them changes `version` or the image. No test exercises the refused-retire path past
  `main()`'s return value (`test_a_tree_the_image_cannot_run_is_not_retired` stubs `check_tree` to
  always succeed, which is the one thing the real one cannot do here).
- Ledger: regression-3 does not close its own scenario.
- Suggested fix: if the retire is refused, the tree has to be BOOTABLE - either exempt this case
  in `check_tree` (the tree is deliberately being kept) or state in the refusal record that the
  image is being booted anyway, so the sentence is not a promise the code does not keep.

### dash-mounts-ui-3 - the macOS release's `CCSYNC_REQUIRE_FFMPEG=1` is inert: the script overwrites it
- Severity: low
- Confidence: CONFIRMED
- Where: `.github/workflows/release-macos.yml:145-147` against `tools/release_macos.sh:509-533`.
- What: the workflow sets `CCSYNC_REQUIRE_FFMPEG: "1"` on the build step and its comment claims
  this "turns a missing binary from a skip into a failed release". `release_macos.sh` computes
  `REQUIRE_FFMPEG` from its own `have_cmd ffmpeg` probe and passes
  `CCSYNC_REQUIRE_FFMPEG="$REQUIRE_FFMPEG"` to pytest, so the workflow's value is discarded. The
  Windows half works (release.ps1 only ever SETS the variable, never clears it, so the job env
  survives) - the two halves of the same fix were built to two different contracts.
- Failure scenario: `brew install ffmpeg` succeeds but the binary is not on the build step's PATH
  (a brew prefix not yet on PATH, a cask/keg-only install, a partially failed formula). The suite
  then SKIPS the twenty media-job tests, pytest exits 0, and the macOS companion is published
  without the coverage the step exists to guarantee - silently, which is exactly the hole tests-1
  was written to close.
- Evidence: `grep -rn CCSYNC_REQUIRE_FFMPEG`; `release_macos.sh:533` is
  `CCSYNC_REQUIRE_RCLONE=1 CCSYNC_REQUIRE_FFMPEG="$REQUIRE_FFMPEG"` with `REQUIRE_FFMPEG` assigned
  unconditionally at 509-513. `tools/tests/test_release_scripts.py:578` only asserts the string
  `CCSYNC_REQUIRE_FFMPEG` appears in the script, so it cannot catch this.
- Ledger: new (tests-1, uncommitted).
- Suggested fix: in `release_macos.sh`, honour an inherited `CCSYNC_REQUIRE_FFMPEG=1`
  (`REQUIRE_FFMPEG="${CCSYNC_REQUIRE_FFMPEG:-}"` before the probe, probe only as the fallback), or
  make the workflow's brew step verify `command -v ffmpeg` and fail there.

### dash-mounts-ui-4 - the regression test for the unreported-lane chip half-passes on the unfixed template
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/tests/test_bug_hunt_2026_09_18_dashboard_mediums.py:379-389`
  (`test_the_grid_draws_an_unreported_lane_in_its_own_style`).
- What: the test reads `fleet_grid.html` as text and asserts `"lane.reported" in text` and
  `"unknown" in text`. The second assertion cannot fail: the pre-fix template already contains
  "unknown" three times (`at an unknown time` twice, `[ VERSION UNKNOWN ]`). Nothing renders the
  template, nothing checks that the class the unreported branch emits is the one `style.css` has a
  rule for, and nothing checks the green-to-`quiet` mapping still holds for a REPORTED green lane.
  A fix that emitted `class="chip lane not-reported"` with no CSS rule would pass.
- Failure scenario: a later edit renames the CSS class on one side only; the suite stays green and
  "this lane did not report" silently goes back to looking identical to "this lane is fine" - the
  exact defect dash-api-4 = dash-mounts-ui-5 was written for.
- Evidence: `git show HEAD:dashboard/templates/partials/fleet_grid.html | grep -c unknown` -> 3.
- Ledger: new (test quality on the dash-api-4 fix).
- Suggested fix: render the partial with a `lane_strip` containing one unreported lane and assert
  the emitted class, plus assert `.chip.lane.unknown` exists in `style.css`.

### dash-mounts-ui-5 - admin-visible copy is produced in a file the copy scan does not cover, and it reads `--`
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/deploy/select_code_root.py:483-484` (`reason = f"... -- the image carries it"`),
  rendered at `dashboard/templates/partials/admin_dashboard_update.html:43-48`.
- What: `retired_reason` is now product copy: dash-mounts-ui-1's panel line prints it verbatim to an
  admin. `dashboard/tests/test_no_em_dash.py` scans `templates/`, `static/` and
  `src/ccsync_dashboard/` only, so `deploy/select_code_root.py` - which since today writes three
  admin-visible sentences (`retired_reason`, and the two refusal sentences the banner already
  prints) - is outside every copy gate, and its first sentence uses the code-comment `--` rather
  than the house spaced hyphen.
- Failure scenario: the panel reads "0.7.43 is not newer than the image's own 0.7.50 -- the image
  carries it"; a future edit there could ship a real em dash with the suite green.
- Evidence: `test_no_em_dash.py:28-32` (`SRC = ROOT / "src" / "ccsync_dashboard"`); the rendered
  string produced by the scratch boot run above.
- Ledger: new.
- Suggested fix: add `dashboard/deploy/*.py` to the Python half of the em-dash scan and reword the
  reason with a colon or a spaced hyphen.

## Coverage note
Covered in depth: every hunk of today's diff in the territory and both ends of each wire it
touches. Read but not exhaustively hunted: the rest of `ui.py` (4.5k lines - the parts the diff
does not touch, e.g. the project/assignments pages and the htmx partial routes), `music.py`,
`ytdl.py` (unchanged today; only their `record_root` contract was compared against b-roll's),
`dashboard/deploy/Dockerfile|compose|run.sh|requirements.lock` (unchanged today), and the static
JS beyond `sw.js`. The suite does not cover: template RENDERING for the new chip classes and the
two new vendor states (every new assertion is a substring scan of template source or a direct call
to `_vendor_state`), a second boot after a retire (dash-mounts-ui-1), the refused-retire path past
`main()`'s return value with the real `check_tree` (dash-mounts-ui-2), and anything about what the
release workflows actually do with `CCSYNC_REQUIRE_FFMPEG` (dash-mounts-ui-3).

## OUT OF TERRITORY
- `dashboard/src/ccsync_dashboard/notices.py:790-815` / `alerts.py:2016-2038`: both scandir
  `root_of("broll")[0]`, which dash-mounts-ui-6 re-pointed from the proxies dir to the data root in
  the same pass. That is coherent with `broll/web/app/routes_api.insert_target_detail`'s
  `get_data_root()/<top_dir>` listing, but the check now proves a directory the bind mount leaves
  behind is listable, not the archive subtree the insert path actually walks - dash-collector-alerts
  should decide whether the witness is the right thing to scandir.
