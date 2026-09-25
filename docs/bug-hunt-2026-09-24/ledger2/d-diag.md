# Ledger, wave 2, group d-diag

## Chunk 1 (builder d-diag, 2026-09-25)

New tests for this chunk: `dashboard/tests/test_bug_hunt_2026_09_24_w2_d-diag.py`
(20 tests). Run against a scratch copy of the dashboard with HEAD's
`protection.py`, `notices.py`, `alerts.py`, `health.py`, `recovery.py` and
`triage_mail.py` swapped in: 16 fail, and the 4 that pass are the guard tests
(a line never MISSING still reads CANNOT VERIFY, a fresh lane error is still
the headline, a computer below current is still sent to UPDATE NOW, the
vendor's own site still gets the Mac commands).

Deploy order for the whole chunk: dashboard only. No wire key, no schema
change, no companion change. The stored protection results gain optional
`carried` / `verdict_at` / `verdict_detail` keys in the existing meta blob;
an older dashboard reading them ignores them, and a newer one reading an
older blob falls back to its top-level `checked_at`.

## bug-dash-diag-1 - A NAS that does not answer turns a MISSING protection line into a "this has cleared" mail and closes its notice
- Status: FIXED
- Verified as: CONFIRMED medium (med-05). Read `protection.run_cycle`: the `missing` keep-list is built only from lines BROKEN this pass, so a line that dropped to NOT_CHECKED (tasks() None) closed its notice, and `alerts._protection_findings` (reads the stored pass) stopped returning the finding, so `deliver()` recorded a recovery. Reproduced by the new test on HEAD.
- Fix: `protection.py` new `_carry_no_verdict()`: a line that reaches no verdict (NOT_CHECKED / CHECK_FAILED) and was BROKEN on the stored pass keeps its BROKEN row, subjects and all, marked `carried`, with the original detail and date plus "this pass could not check it again: ...". Every fresh BROKEN row records `verdict_at` / `verdict_detail` so a second carry never nests. `run_cycle` keeps a carried line's subjects in the MISSING keep-list without re-filing (its notice keeps the body and date of the pass that saw it) and files no "cannot verify" warn for it; `refresh_line` applies the same carry. Same rule as invariants' `stored_broken` (dash-collector-2). A real verdict (OK or BROKEN) always replaces a carried row.
- Regression test: `test_a_nas_that_does_not_answer_keeps_a_missing_line_missing` - fails on HEAD because the second (blind) pass closes `snapshot_tree: tank/Projects` and stores NOT_CHECKED; `test_a_line_that_was_never_missing_still_reads_cannot_verify` guards the other direction.
- Tests run: dashboard venv, `tests/test_protection.py tests/test_alerts.py tests/test_bug_hunt_2026_09_24_w2_d-diag.py` (in the combined run below) -> pass.
- Skew / deploy order: dashboard only.
- OWED: none

## bug-dash-diag-3 - A snapshot restore's `.restored-<ts>` folder is replicated by Syncthing to every editor who has the project ticked
- Status: FIXED (one template sentence OWED to d-ui)
- Verified as: CONFIRMED medium (med-05). `restore_into_quarantine` created `<project>/.restored-<ts>/`, inside the project's sendreceive Syncthing root; `build_stignore_lines` (provision.py / server/common.py / companion) has no dot-dir or `.restored` rule, and the provision cycle REPAIRS a drifted `.stignore`, so recovery could not add one itself. Also: the collector's per-project NAS inventory walks the project folder, so restored video there was inventory too.
- Fix: moved the quarantine OUT of the project instead of adding an ignore rule (which would need three byte-identical copies in three groups and a provision repair on every folder): `recovery.py` now writes `<tree>/.restored-<ts>/<project label>/...`. The tree root is no Syncthing folder and no project's scope; the leading dot still keeps `provision.scan_project_dirs` from finding the copied marker as a second project (existing test still passes). `where` is now `.restored-<ts>/<label>`, so "move it back" is the same relative path one level up. The preview `note` and the runbook step copy say where it goes and that it is not sent to any editor. Existing `tests/test_recovery.py::test_a_restore_writes_only_into_the_quarantine_folder` asserted the old in-project parent; changed because the behaviour changed.
- Regression test: `test_a_restore_lands_outside_every_project_folder` - fails on HEAD because `.restored-...` appears inside `2026/One`.
- Tests run: `tests/test_recovery.py` + new file -> pass.
- Skew / deploy order: dashboard only. Past restores stay where they were written (their recorded `where` is unchanged).
- OWED: d-ui, `dashboard/templates/partials/recovery.html` ~line 121: the paragraph under [ PUT A PROJECT'S FILES BACK ] still says "copied into a NEW folder inside that project, called .restored-<date>". Should say: copied into a new `.restored-<date>` folder at the top of the Projects folder on the server, under the project's own name, and it is not sent to any editor's computer. (Docstrings in `api.py:10681` (d-api) and `ui.py:2219` (d-ui) say `<project>/.restored-<ts>/`; comment-only, update to `<tree>/.restored-<ts>/<project>/` when next in those files.)

## bug-dash-ops-1 - The "same Message-ID is in my Sent folder" proof is an IMAP substring search, so a forged From passes the authentication check
- Status: FIXED
- Verified as: CONFIRMED medium (med-07). `_in_sent` counted any `SEARCH HEADER Message-ID "<mid>"` hit (a substring match, RFC 3501 6.4.4), and `handle_message` let that hit overrule even an explicit `dmarc=fail`.
- Fix: `triage_mail.py`: a Sent hit is only a candidate. Up to `SENT_HITS_COMPARED` (5) hits are fetched (`BODY.PEEK[]`) and one must BE this message (`_same_message`: exact Message-ID, same From address, same Subject, same body text). New `auth_results_fail(msg)`: the topmost Authentication-Results saying `dkim=fail`/`dmarc=fail` (or permerror), comments stripped, means the Sent proof is not applied at all. The owner's own no-header reply (the case the proof exists for) still passes.
- Regression test: `test_a_message_id_fragment_is_not_the_owners_sent_copy`, `test_a_matching_id_with_different_text_is_not_the_sent_copy`, `test_an_explicit_dmarc_fail_is_never_overruled_by_the_sent_proof`, `test_handle_message_refuses_a_sent_hit_over_a_dmarc_fail` - fail on HEAD because the substring hit returns True and the fail header is overruled. Existing `tests/test_triage_mail.py::_SentIMAP` gained a `fetch` (the proof now fetches the hit); changed because the behaviour changed.
- Tests run: `tests/test_triage_mail.py tests/test_triage.py` + new file -> pass.
- Skew / deploy order: dashboard only. Feature is off in the vendor build (`alerts_triage`).
- OWED: none

## logic-sync-truth-1 - A laptop that is merely asleep gets a red "Upload has stopped" headline after 15 minutes
- Status: FIXED
- Verified as: CONFIRMED medium (med-09). `health.lane_chip` reddened every lane at 15 min of silence while `report_freshness` (UX-2) is amber until 6 h; `fleet_headline` then took lane A's red and wrote "Upload has stopped: this companion has been silent...". The row's own `status` (worst of lane chips and freshness) was red at 15 min too.
- Fix: `health.py`: `lane_chip` uses the freshness steps for silence (AMBER from `STALE_EDITOR_AMBER_SECONDS` with `LANE_SILENT_AMBER_REASON`, RED from `STALE_EDITOR_RED_SECONDS` with `LANE_SILENT_RED_REASON`), still ahead of the stall test. `fleet_headline` ranks a new `not_reporting` headline ("Not heard from since YYYY-MM-DD HH:MM UTC", amber, red after 6 h) directly after a blocking `why` sentence and above out-of-date and lane faults (`_silence` reads the lane chip reasons, or the row's "no report since" `status_reason` for a machine with no lane rows). A computer with nothing ticked is untouched (the informational `why` path is below and muted as before).
- Regression test: `test_a_laptop_asleep_for_twenty_minutes_is_amber_not_upload_has_stopped`, `test_six_hours_of_silence_is_red_and_still_about_the_computer` - fail on HEAD because the headline is `lane_error` / red at 20 min. Existing `tests/test_health.py::test_lane_chip_status` and `::test_silence_still_outranks_a_stall_and_says_which_it_is` asserted RED at 30 min; changed to AMBER (and a 7 h case asserting RED) because the behaviour changed deliberately.
- Tests run: `tests/test_health.py tests/test_fleet_grid_declutter_2026_09_11.py tests/test_report_ingest_health.py` + new file -> pass.
- Skew / deploy order: dashboard only. `api.py` needed no change: it already passes the lane rows and the freshness `status_reason` through.
- OWED: none
- Review round (2026-09-25, adversarial reviewer): CONFIRMED. `_silence` took the silence reason of ANY lane, and a lane the companion stopped sending lives on in `lane_report_current` with its old `received_at`, so a computer that reported 10 s ago led with "Not heard from since <10 s ago>". Fixed in `health.py` `_silence`: the gate is now the ROW's own freshness (`status_reason` starting "no report since", which `build_editors_view` sets from `report_freshness(row received_at)` and only when the row is stale; lane reasons fill `status_reason` only when it is empty). The amber/red level comes only from lanes whose `received_at` equals the row's (the row's stamp is the max over its lanes, so those lanes' silence is exactly the row's); with none of those speaking of silence (no lane rows, or the latest lanes all in error) it falls back to the row's dot. No `api.py` change needed. New tests: `test_a_dropped_lanes_old_stamp_never_says_a_reporting_computer_is_silent` (the reviewer's probe: fresh row, lane C at 09:00, and again at 7 h), `test_a_dropped_lanes_old_stamp_does_not_redden_a_computer_asleep_briefly` (row 20 min quiet + 7 h leftover lane stays AMBER), `test_a_computer_with_no_lane_rows_still_reads_not_heard_from`. Known residue: a row with no lane rows whose dot is red from the DISK chip while freshness is only amber reads red; `fleet_headline` is pure (no `now`), so passing the freshness colour explicitly would need a `freshness` key from `api.py` (d-api) - judged not worth an OWED.

## logic-admin-1 - The "fleet-wide stop expired" alert can never fire
- Status: FIXED
- Verified as: CONFIRMED medium (med-10). `db._halt_state` returns `active = active and not expired`, and `_check_fleet_halt_expired` required both.
- Fix: `alerts.py` `_check_fleet_halt_expired` tests `expired` alone, and only for `FLEET_HALT_EXPIRED_WINDOW_SECONDS` (24 h, the stop's own default length) after `expires_at`: the stored blob keeps `expired` true until somebody sets a new stop and the expired panel has no "that is fine" button, so without a window it would stand for months. Fix text names Settings, Users and [ STOP ALL SYNCING ] (see ui-copy-1).
- Regression test: `test_an_expired_fleet_stop_is_reported_for_a_day` (drives a real halt through `db.set_fleet_halt` / `db.get_fleet_halt`, the way `Ctx.halt` is built) - fails on HEAD because the check returns `[]`.
- Tests run: `tests/test_fleet_halt.py tests/test_alerts.py` + new file -> pass.
- Skew / deploy order: dashboard only. After the window the finding leaves the scan, so a warn that was mailed gets one "cleared" line in the next mail/digest; judged acceptable against a months-long standing warn. If the owner prefers it to stand until acknowledged, that needs an [ OK ] control on the expired panel (d-ui) and is a decision, not a defect.
- OWED: none

## logic-alerts-1 - A mount a site deliberately left OFF raises a permanent "check the bind mounts" warning
- Status: FIXED
- Verified as: CONFIRMED medium (med-11). `cards.py` documents `disabled` as "this deployment did not ask for it" (flag off, no checkout, no vault); `ytdl.py` records `disabled` when the site has not enabled the downloader (the vendor default). `_check_feature_mounts` filed a warn for both.
- Fix: `notices.py` `_check_feature_mounts` treats `disabled` like `mounted`: no card, and left out of the keep-list so a card from an earlier boot where the page WAS asked for and missing closes. `absent` and `degraded` still file the card.
- Regression test: `test_a_page_the_site_left_off_raises_nothing_and_closes_an_old_card` - fails on HEAD because two `feature_not_mounted` cards open for ytdl and cards.
- Tests run: `tests/test_notices.py tests/test_bug_hunt_2026_09_11_dash_collector_alerts.py` + new file -> pass.
- Skew / deploy order: dashboard only.
- OWED: none

## logic-alerts-2 - versions_behind counts staged/feed builds, so a computer on the CURRENT build is told to UPDATE NOW
- Status: FIXED
- Verified as: CONFIRMED medium (med-11). `_check_versions_behind` counts every non-retracted package plus the feed's offer (SYS-2, intended) and always prescribed [ UPDATE NOW ], which pushes the current build.
- Fix: `alerts.py`: the per-computer UPDATE NOW finding is raised only for a computer running something OLDER than its platform's current build. Computers already on (or ahead of) current but still >= 3 builds behind the shelf/feed are said once per PLATFORM (subject `the <platform> computers`), naming them and the version they run, saying the newer builds are staged or refused, and prescribing "make it current on Settings, Packages; if it is not listed, update the dashboard first". The SYS-2 counting is unchanged (its test still passes: one finding, "3 releases behind").
- Regression test: `test_a_computer_on_the_current_build_is_never_told_to_update_now` - fails on HEAD because the finding's fix is [ UPDATE NOW ] on that computer; `test_a_computer_below_current_is_still_sent_to_update_now` guards the other branch.
- Tests run: `tests/test_sweep_2026_09_04_dashboard.py tests/test_alerts.py` + new file -> pass.
- Skew / deploy order: dashboard only. The subject changes for the on-current case, so an open `versions_behind` row for `leso/Mac` gets one "cleared" line and the platform subject opens once.
- OWED: none
- Review round (2026-09-25, adversarial reviewer): CONFIRMED (copy). A computer was bucketed "on current" when its platform had NO current build (`current_version_for` None), and the mail said it runs "this dashboard's current <platform> build". `alerts.py` `_check_versions_behind` now buckets by (platform, has_current): with nothing current the diagnosis says "this dashboard has no current <platform> build at all" and [ UPDATE NOW ] has nothing to send, and the fix is to make the newer build current on Settings, Packages or update the dashboard first. Same pass: a computer AHEAD of current (hand-installed build) is no longer said to run current either; the sentence names current ("this dashboard's current macos build is 0.9.70"). Subject is unchanged (`the <platform> computers`; a platform is in only one of the two states). New tests: `test_a_platform_with_nothing_current_is_not_called_the_current_build`, `test_a_computer_ahead_of_current_is_not_said_to_run_current`.

## logic-alerts-3 - platform_channel_stale says "build it" when the Mac build already exists staged, and names repo commands on customer sites
- Status: FIXED
- Verified as: CONFIRMED medium (med-11). The check never looked at the lagging platform's own newer published builds and always printed `release_macos.sh`, whatever the platform and whoever the site.
- Fix: `alerts.py` `_check_platform_channel_stale`: first looks for published, non-retracted builds of the LAGGING platform newer than its current; if any, the finding names the newest ("0.9.74 for macos is already published on this dashboard and is not current") and the fix is "make 0.9.74 current" on Settings, Packages, nothing to build. Otherwise: a dashboard with `release_feed_url` set is told the vendor has not published one (no repo commands); the vendor's own dashboard keeps the two Mac commands for macOS, and gets a docs/RELEASE.md pointer, not "On a Mac", when the platform behind is Windows.
- Regression test: `test_a_staged_mac_build_is_made_current_not_built`, `test_a_feed_site_is_never_handed_repo_commands`, `test_a_lagging_windows_channel_is_not_told_to_use_a_mac` - fail on HEAD because the fix is always the Mac commands; `test_the_vendor_site_still_gets_the_mac_commands` guards the kept case (as does `tests/test_alerts.py::test_a_mac_channel_left_behind_names_the_two_commands`).
- Tests run: `tests/test_alerts.py` + new file -> pass.
- Skew / deploy order: dashboard only.
- OWED: none

## ui-copy-1 - The fleet-halt alert sends the admin to a button and a page that do not exist
- Status: FIXED
- Verified as: CONFIRMED medium (med-18). `[ RELEASE THE HALT ]` exists nowhere in templates; the controls are `[ START SYNCING AGAIN ]` / `[ KEEP IT STOPPED ]` / `[ STOP ALL SYNCING ]` in `partials/fleet_halt.html` on Settings, Users (`/admin/users#admin-fleet-halt`). The recovery step linked to `/fleet` and said "Put the fleet on hold".
- Fix: `alerts.py` `_check_fleet_halt` fix: "Settings, Users, then [ START SYNCING AGAIN ] ... or [ KEEP IT STOPPED ]"; `_check_fleet_halt_expired`: "Settings, Users, and either [ STOP ALL SYNCING ] again or leave it running". `recovery.py` `_stop_the_fleet_step`: "Press [ STOP ALL SYNCING ] on Settings, Users", href `/admin/users#admin-fleet-halt`. Dropped the stale `("alerts.py", "[ RELEASE THE HALT ]", ...)` entry from `tests/test_sweep_2026_09_04_copy.py::VOCABULARY_ALLOWED`, so a future label using a retired word fails the scan.
- Regression test: `test_every_button_the_halt_alerts_name_is_on_the_halt_panel` (every `[ LABEL ]` the two halt findings name must appear in `partials/fleet_halt.html`, and neither says SYNC STATUS), `test_the_recovery_step_sends_the_admin_to_the_halt_panel` - fail on HEAD.
- Tests run: `tests/test_sweep_2026_09_04_copy.py tests/test_recovery.py` + new file -> pass.
- Skew / deploy order: dashboard only.
- OWED: none

### Tests run for the chunk
- `dashboard\.venv\Scripts\python.exe -m pytest tests/test_protection.py tests/test_alerts.py tests/test_notices.py tests/test_notices_sweep_wave2.py tests/test_notices_auto_resolve_cr320.py tests/test_health.py tests/test_recovery.py tests/test_triage_mail.py tests/test_triage.py tests/test_sweep_2026_09_04_copy.py tests/test_sweep_2026_09_04_dashboard.py tests/test_fleet_grid_declutter_2026_09_11.py tests/test_fleet_halt.py tests/test_report_ingest_health.py tests/test_bug_hunt_2026_09_11_dash_collector_alerts.py tests/test_bug_hunt_2026_09_11b_dash_collector_alerts.py tests/test_live_notices_2026_09_21.py tests/test_bug_hunt_2026_09_24_w2_d-diag.py` -> 847 passed, 1 skipped after the two `test_health.py` assertions were updated.
- Plus the other suites that read the headline, lanes, packages, restores or halts (`test_broll_ingest_report`, `test_bug_hunt_2026_09_11_dash_mounts_ui`, `test_bug_hunt_2026_09_18_dashboard_mediums`, `test_capabilities_report`, `test_cards_capability`, `test_music_ingest_report`, `test_packages`, `test_sweep_2026_09_04_says_what_it_knows`, `test_templates_wave3_2026_09_04`, `test_bug_hunt_2026_08_21`, `test_bug_hunt_2026_09_11b_dash_db`, `test_bug_hunt_2026_09_24_crash_looped`, `test_dashboard_update`, `test_invariants`, `test_multi_machine`, `test_tab_memory`, `test_health`) -> 510 passed, 1 failed: `test_templates_wave3_2026_09_04.py::test_the_four_long_controls_on_packages_show_that_they_are_working` (`hx-indicator="this"` counted 8, expected 4). That comes from d-ui's uncommitted edit to `templates/partials/admin_packages.html`, not from this chunk, which touches no template.

Note for the orchestrator: while making a HEAD scratch copy I ran `rm -rf` on
`<scratchpad>/headcopy`, which already existed in the shared session
scratchpad (another builder's scratch copy; one subdirectory was busy and
survived). Only scratch files; nothing in the repo. Any builder using that
path needs to re-create it.

### Review round tests
- `dashboard\.venv\Scripts\python.exe -m pytest tests/test_bug_hunt_2026_09_24_w2_d-diag.py tests/test_health.py tests/test_fleet_grid_declutter_2026_09_11.py tests/test_report_ingest_health.py tests/test_alerts.py tests/test_sweep_2026_09_04_dashboard.py tests/test_packages.py tests/test_multi_machine.py` -> 360 passed. (A first run showed one `test_packages.py::test_c4_unsigned_make_current_confirm_copy_is_pinned` failure that did not reproduce alone or in the rerun of the same set; this round touched no template, most likely another builder's template edit mid-run.)


## Chunk 2 (builder d-diag, 2026-09-25)

New tests appended to `dashboard/tests/test_bug_hunt_2026_09_24_w2_d-diag.py`
(18 tests under "Chunk 2"). Run against a scratch copy of the dashboard with
HEAD's `alerts.py`, `notices.py`, `collector.py`, `recovery.py`, `triage.py`,
`triage_mail.py`, `health.py` swapped in: 14 of the chunk-2 tests fail, and the
one that passes is the guard (`test_a_check_still_failing_is_not_recovered`).

Deploy order for the whole chunk: dashboard only. No wire key, no schema
change, no companion change. `fleet_headline` reads a new OPTIONAL row key
`owed_files` that nothing sets yet (OWED to d-api); absent, the line says
"Idle" and claims nothing.

## ui-copy-2 - "Settings, Diagnostics" is not a page, and the notice links land on an empty div
- Status: PARTIAL (rest OWED to d-db, d-ui and d-api)
- Verified as: CONFIRMED medium (med-18). `ui.SETTINGS_NAV_GROUPS` has no Diagnostics entry. Worse than reported: a TestClient GET as admin answers `/` 200, `/admin/health` 200 and **`/fleet` 404**. SYNC STATUS is served at `/`, and no route or redirect serves `/fleet`. So every registry href `/fleet` (db.py: nine kinds plus the `_slug_href` / `_plan_pair_href` fallbacks) and every `/fleet#fleet-diagnostics` (collector kinds, `db_busy`, `slow_write`, `slow_poll`, `server_error`, `feature_not_mounted`) is a 404, not merely an empty anchor.
- Fix (my files): `notices.py` `_JOB_MEANING["config"]`, the unknown-job fallback and `syncthing_unreachable` now name "the [ COLLECTOR ] panel under the computers table on SYNC STATUS" (review round; first written as "at the bottom of SYNC STATUS") (it exists: `partials/collector_health.html`, included server-side in the fleet grid, listing each cycle's last run and error); `server_crash_report` says "press [ DOWNLOAD CRASH REPORTS ] on this notice" (its registry row carries that button); `server_error`, `db_busy`, `slow_write` say "send the text of this notice to support" (the detail is the notice body). `collector.py` `provision_failed` likewise. `recovery.py` `_plan_resolve`: the "Undo it from here" action step (href `/fleet`) is now a note naming the companion's [ UNDO LAST FIX ] (review round; first written as href `/`).
- Regression test: `test_no_server_notice_sends_the_owner_to_a_page_that_does_not_exist` (drives the three writers and every `_JOB_MEANING` fix, and scans the non-comment source of notices.py + collector.py), `test_the_named_collector_panel_is_where_the_copy_says`, `test_the_resolve_undo_step_claims_no_dashboard_button_that_does_not_exist` - fail on HEAD (the strings and the `/fleet` action step) and on this chunk's first build ("bottom of SYNC STATUS"; an action step with href `/`).
- Tests run: see the chunk run below -> pass.
- Skew / deploy order: dashboard only.
- OWED:
  - d-db, `dashboard/src/ccsync_dashboard/db.py`: every notice registry `"href": "/fleet"` and the `_slug_href` / `_plan_pair_href` fallback `"/fleet"` -> `"/"` (verified 404 today). `"/fleet#fleet-diagnostics"` on `collector_cycle_failed`, `collector_watchdog_restart`, `syncthing_unreachable`, `db_busy`, `slow_write`, `slow_poll` -> `"/#fleet-collector"` (once d-ui adds the id below); on `server_error` and `feature_not_mounted` -> `"/admin/health"` (their detail is the notice text itself). `#fleet-diagnostics` is filled only by [ READ THE ANSWER ], so it is never the right target for a server notice.
  - d-ui, `dashboard/templates/partials/collector_health.html` line ~14: give the `[ COLLECTOR ]` side-head `id="fleet-collector"` so the d-db hrefs above scroll to it (the grid is included server-side in fleet.html, so a hash anchor works on first load).
  - d-ui + d-api (NEW, review round): a dashboard control for the Resolve undo. Only `POST /api/v1/admin/machines/{editor}/{machine}/resolve-undo` (api.py ~10766) and `GET .../resolve-journals` (~10724) exist; no template or static file calls either, so "pick the computer and the change" from the dashboard is impossible today. A per-machine panel listing the journals with [ UNDO THIS CHANGE ] (the route's own docstring name) would let `recovery._plan_resolve` go back to an `action` step with a real href; `test_the_resolve_undo_step_claims_no_dashboard_button_that_does_not_exist` pins the absence and is the test to change when it lands.
- Review round (2026-09-25, adversarial reviewer): both problems CONFIRMED.
  (1) The [ COLLECTOR ] panel is included at the end of `partials/fleet_grid.html` (after the computers table, and after the lost-machines table when there is one), and `fleet.html` renders plan changes, `#fleet-diagnostics`, transfers, the queue and project roots below it, so "at the bottom of SYNC STATUS" sent the owner to project roots. `notices.py` (three strings) and `collector.py` (one) now say "under the computers table on SYNC STATUS". The test now asserts the include sits after the grid's first `</table>`, that the phrase appears in all four places (implicit string concatenation joined before scanning), and that "bottom of SYNC STATUS" appears nowhere.
  (2) Checked: `grep resolve-undo|resolve-journals|UNDO THIS CHANGE` over `dashboard/templates` and `dashboard/static` finds nothing; only the API routes exist. So the step's body ("Pick the computer and the change") claimed a dashboard control that does not exist, and href `/` traded a 404 for a page without the button; the old test locked that in. The step is now a `note` with no href: "open Settings from the CC Sync tray icon and press [ UNDO LAST FIX ] in the RESOLVE section. The dashboard has no button for this yet, so somebody has to be at that computer." (verified: `settings_window._resolve_section` adds `Button("UNDO LAST FIX")` when `undo_last_fix_available()`, under `Section("RESOLVE")`; the old body's "same button in their tray" was also wrong, it is the Settings window). The missing dashboard button is recorded as OWED above, and this finding stays PARTIAL rather than FIXED.
  Tests: `dashboard\.venv\Scripts\python.exe -m pytest tests/test_bug_hunt_2026_09_24_w2_d-diag.py tests/test_recovery.py tests/test_notices.py tests/test_notices_sweep_wave2.py tests/test_notices_auto_resolve_cr320.py tests/test_collector.py tests/test_sweep_2026_09_04_copy.py tests/test_live_notices_2026_09_21.py tests/test_help_page.py` -> 509 passed, 2 skipped.

## bug-dash-diag-2 - check_failed alerts can never recover
- Status: FIXED
- Verified as: DOWNGRADE to low (med-05); mechanism confirmed by reading `deliver`: `checked_kinds` came from ALERT_KINDS only, and CHECK_FAILED is outside it. Found in the same line while fixing it, and fixed with it: when `scan` cannot build its context it returns ONLY `check_failed / "the whole scan"`; that subject is no kind name, so `checked_kinds` was the whole registry and `deliver` mailed every open alert as "cleared" after a scan that checked nothing.
- Fix: `alerts.py` `deliver`: if a `check_failed / SCAN_FAILED_SUBJECT` finding is present, `checked_kinds` is empty; otherwise it is ALERT_KINDS plus `check_failed`, minus the failing checks and the truncated kinds. New `SCAN_FAILED_SUBJECT` constant (used by `scan`). New `_known_kind()` so a recovered check_failed is titled "a health check could not run" in `compose_recovered` and `_digest_item`, not the raw key; CHECK_FAILED stays out of ALERT_KINDS.
- Regression test: `test_a_check_that_ran_again_records_its_recovery` (fails on HEAD: recovered 0, `_is_open` True), `test_a_scan_that_could_not_run_clears_nothing` (fails on HEAD: recovered 1); `test_a_check_still_failing_is_not_recovered` guards.
- Tests run: `tests/test_alerts.py` + new file -> pass.
- Skew / deploy order: dashboard only. On first deploy, every check_failed row left open by past hiccups gets ONE "cleared" line (one digest line on a digest sink), after which the ledger is right.
- OWED: none

## bug-dash-diag-4 - A failed db.migrate in the collector loop is never retried
- Status: FIXED
- Verified as: real (low, unverified before). `collector._loop` assigned `conn = self._open_conn()` before `db.migrate(conn)`; the except `continue`d with `conn` set, so the `if conn is None` block never ran again, and the failed connection was used and never closed.
- Fix: `collector.py` `_loop`: open into a local `fresh`, migrate it, assign `conn = fresh` only on success; on failure close `fresh` and wait `DB_OPEN_RETRY_SECONDS`.
- Regression test: `test_a_failed_migrate_is_retried_and_its_connection_closed` (migrate raises "database is locked" twice) - fails on HEAD: migrate called once, prune never recorded ("no such table" every cycle).
- Tests run: `tests/test_collector.py tests/test_db_write_locks.py` + new file -> pass.
- Skew / deploy order: dashboard only.
- OWED: none

## bug-dash-ops-5 - Reply poll cap counts already-handled messages
- Status: FIXED
- Verified as: real (low). `poll` sliced `numbers[-20:]` before the `triage_replies` skip, so 20 known messages in the 2-day window took every slot and an older unhandled reply was never read.
- Fix: `triage_mail.py` new `_unhandled_numbers()`: walks the hits newest to oldest with the header-only peek, skips known Message-IDs without counting them, stops at `MAX_MESSAGES_PER_POLL` unknown ones (bounded by new `MAX_HEADER_PEEKS_PER_POLL` = 500 peeks) and returns them oldest first. `poll` fetches bodies only for those.
- Regression test: `test_handled_messages_do_not_use_up_the_poll_cap` (25 hits, newest 20 known -> the 5 older ones are picked), `test_the_poll_cap_still_bounds_a_flood` - fail on HEAD (no such function; the HEAD loop is the one that re-picks the newest 20).
- Tests run: `tests/test_triage_mail.py` (its poll tests drive the real `poll` through FakeIMAP) + new file -> pass.
- Skew / deploy order: dashboard only; feature off in the vendor build.
- OWED: none

## bug-dash-ops-6 - The CCT reply token is stored in plaintext beside its hash
- Status: FIXED
- Verified as: real (low). `triage.run` stores `{"body": text}` in `triage_runs.report_json` via `_finish`; the body has `Reference: CCT-<token>`; `report_text` serves it. Nothing reads the token back out of the stored body (`find_run` matches the hash; the confirmation mail gets the token from the reply itself).
- Fix: `triage.py` new `mask_reference()` (`CCT-...<last 4>`); `_finish` masks the body before storing; `report_text` masks on the way out too, so a row written before this deploy is not shown in full.
- Regression test: `test_the_stored_report_never_holds_the_live_reference` - fails on HEAD because the stored JSON holds the token.
- Tests run: `tests/test_triage.py tests/test_triage_mail.py` + new file -> pass (the existing test that reads the token from the SENT mail is unaffected: the mail keeps it).
- Skew / deploy order: dashboard only. Rows written before the deploy keep the plaintext in the database until `prune` removes them (the token expires in 48 h regardless); the page no longer shows it.
- OWED: none

## bug-dash-ops-7 - Authentication-Results is trusted without checking its authserv-id
- Status: FIXED
- Verified as: PLAUSIBLE low, confirmed by reading: `auth_results_pass` took `headers[0]` whatever it named, and the 2026-09-24 comment in `handle_message` records that Google adds no header for intra-Workspace mail, so the topmost can be the sender's.
- Fix: `triage_mail.py`: `KNOWN_AUTHSERV_IDS` (`imap.gmail.com` -> `mx.google.com`), `expected_authserv_id(values)` from the IMAP host, `_receiver_header()` picks the first header naming that id (any header when the id is unknown, i.e. the old rule for non-Gmail hosts). `auth_results_pass` and `auth_results_fail` take the id; `handle_message` passes it. On a Gmail mailbox, a message whose only header names another host is treated as "no receiver header", so only the Sent-folder proof can pass it.
- Regression test: `test_a_sender_written_results_header_is_not_the_receivers` (Gmail site, header `attacker.example; dkim=pass header.d=example.com` -> refused; an `mx.google.com` pass -> acted) - fails on HEAD (acted); `test_an_unknown_receiver_keeps_the_topmost_rule` guards the non-Gmail case.
- Tests run: `tests/test_triage_mail.py` + new file -> pass.
- Skew / deploy order: dashboard only.
- Residue (stated in the code): a sender who writes `mx.google.com` itself is stopped only if Google strips such headers (RFC 8601 section 5 says a receiver SHOULD); the unexpired CCT token, which only the owner's inbox receives, is still required. A per-site authserv-id setting for non-Gmail hosts would need a Settings field; not built, judged not worth it for a low.
- OWED: none

## logic-sync-truth-5 - "Idle, nothing owed" is claimed without consulting what is owed
- Status: PARTIAL (rest OWED to d-api)
- Verified as: real (low). `fleet_headline`'s fallback reads only lane states; `build_editors_view` attaches no backlog count to the row, while `db.fetch_sync_backlog` (transfers page) knows it.
- Fix: `health.py` `fleet_headline`: idle rows read an optional int `owed_files`: > 0 -> "Idle between passes, N files still to move"; 0 -> "Idle, nothing owed"; absent -> "Idle" (no claim). All muted, reason `idle` as before. Existing `tests/test_fleet_grid_declutter_2026_09_11.py::test_a_row_with_nothing_wrong_says_so_quietly` asserted "Idle, nothing owed" for a row with no count; changed (to "Idle", plus an `owed_files=0` case) because the behaviour changed deliberately.
- Regression test: `test_idle_lanes_with_uploads_owed_never_say_nothing_owed` - fails on HEAD ("Idle, nothing owed" with no count and with 60 owed).
- Tests run: `tests/test_health.py tests/test_fleet_grid_declutter_2026_09_11.py tests/test_bug_hunt_2026_09_18_dashboard_mediums.py` + new file -> pass.
- Skew / deploy order: dashboard only. Until d-api lands, every idle row reads "Idle".
- OWED: d-api, `dashboard/src/ccsync_dashboard/api.py` `build_editors_view` (before `entry["headline"] = health.fleet_headline(entry)`, ~line 1122): set `entry["owed_files"]` to the int sum of `n_files` over the `db.fetch_sync_backlog(conn, editor=...)` groups whose `(editor, machine)` is this row's (lanes A up + B down; one fetch for the whole view, not one per row). Leave it unset for a base-mode machine (fetch_sync_backlog excludes them, and 0 would claim "nothing owed" about a machine that syncs nothing) and when the fetch raises.

## logic-admin-4 - After a restore, the recovery page still shows the same files as missing and invites the same restore again
- Status: FIXED (an optional result-line hint is OWED to d-ui)
- Verified as: DOWNGRADE to low (med-10); UX gap confirmed: the preview never consulted `history(RESTORES_META)`.
- Fix: `recovery.py`: new `_earlier_restores()` (same slug and snapshot, files > 0) and `_earlier_restore_sentence()`; `preview_restore` prefixes its `note` (already rendered under the counts by `partials/recovery.html`) with "This snapshot was already restored on <date> UTC: N file(s) went into <where> on the server. Those copies are there, not in the project, so the same files still count as missing below until someone moves them back; a name that starts with a dot may be hidden in Explorer or Finder until hidden items are shown. Restoring again makes another full copy." and returns `earlier_restores`. The counts stay true (the files ARE still missing from the project).
- Regression test: `test_a_preview_after_a_restore_says_it_was_already_restored` - fails on HEAD (no such sentence or key).
- Tests run: `tests/test_recovery.py` + new file -> pass.
- Skew / deploy order: dashboard only.
- OWED: d-ui, `dashboard/templates/partials/recovery.html` result block (~line 193, "Restored N file(s) into {{ recovery_result.where }}"): add that the folder is at the top of the Projects folder on the server and that a name starting with a dot may be hidden in Explorer/Finder until hidden items are shown (optional; the preview note now says it).

## logic-admin-5 - When only "changed" files exist, the restore form's defaults are refused, and the confirm quotes the wrong count
- Status: PARTIAL (template half OWED to d-ui)
- Verified as: real (low). Read `recovery.html` ~171-182 (form shown for `missing_count or changed_count`, box unticked, confirm quotes `missing_count` only) and `restore_into_quarantine` (`rels` empty -> "nothing to restore").
- Fix: `recovery.py` `restore_into_quarantine`: when nothing is missing, the box was unticked and files differ, the refusal says "... but N file(s) are there with different contents. Tick 'also bring back the ones that are there but different' to copy those into a new folder." (the label's exact words).
- Regression test: `test_a_changed_only_restore_names_the_box_that_does_it` - fails on HEAD (refusal says only "nothing to restore").
- Tests run: `tests/test_recovery.py` + new file -> pass.
- Skew / deploy order: dashboard only.
- OWED: d-ui, `dashboard/templates/partials/recovery.html` ~lines 171-182: render the `include_changed` checkbox `checked` when `recovery_preview.missing_count == 0 and recovery_preview.changed_count`; make the `hx-confirm` state both numbers, e.g. "Copy N missing file(s) (and M different one(s) if the box is ticked) into a new folder? Nothing there now changes." (no em dash).

### Tests run for chunk 2
- `dashboard\.venv\Scripts\python.exe -m pytest tests/test_bug_hunt_2026_09_24_w2_d-diag.py tests/test_alerts.py tests/test_notices.py tests/test_notices_sweep_wave2.py tests/test_notices_auto_resolve_cr320.py tests/test_collector.py tests/test_triage.py tests/test_triage_mail.py tests/test_health.py tests/test_fleet_grid_declutter_2026_09_11.py tests/test_recovery.py tests/test_bug_hunt_2026_09_18_dashboard_mediums.py tests/test_sweep_2026_09_04_copy.py tests/test_bug_hunt_2026_09_11_dash_collector_alerts.py tests/test_bug_hunt_2026_09_11b_dash_collector_alerts.py tests/test_live_notices_2026_09_21.py tests/test_db_write_locks.py tests/test_invariants.py` -> 859 passed, 1 skipped.
- Every dashboard test file carrying an em-dash scan -> 740 passed, 1 skipped.
- No template changed in this chunk, so no screenshots.


## Chunk 3 (builder d-diag, 2026-09-25)

New tests appended to `dashboard/tests/test_bug_hunt_2026_09_24_w2_d-diag.py`
(13 tests under "Chunk 3"). Run against a scratch copy of the dashboard with
HEAD's `triage.py`, `invariants.py`, `notices.py`, `alerts.py`,
`protection.py`, `collector.py` swapped in: 12 fail, and the one that passes is
the guard (`test_a_report_with_actions_still_carries_the_reply_address`).

Deploy order for the whole chunk: dashboard only. No wire key, no schema
change, no companion change.

## logic-alerts-4 - Replies to all-clear/fallback server-check emails are refused and leave a warn card with an impossible fix
- Status: FIXED
- Verified as: DOWNGRADE to low (med-11). Re-read `triage.run`: it calls `_send(..., reply_to, now)` for every report and fallback, while `compose_report` writes the CCT reference only when `offered`.
- Fix: `triage.py` `run`: Reply-To is now `reply_to if (offered and reply_enabled) else ""`. An all-clear, a "nothing can be done by reply" report and the fallback go out with no Reply-To. A reply to one of them goes to the owner's own From address, which the poll (`TO "<reply address>"`) never reads, so nothing is refused and no card opens. A report that offers actions is unchanged. Reports sent while replies are disabled also lose the header, because the +address is not polled then.
- Regression test: `test_an_all_clear_carries_no_reply_address`, `test_the_fallback_carries_no_reply_address` - fail on HEAD (reply_to is the +address); `test_a_report_with_actions_still_carries_the_reply_address` guards.
- Tests run: `tests/test_triage.py tests/test_triage_mail.py` + new file -> pass (`test_triage.py`'s header test uses an offered report, so it is unchanged).
- Skew / deploy order: dashboard only. The feature is off in the vendor build.
- OWED: none

## logic-alerts-5 - Invariant 9 is OK when any snapshot task exists, checks the dashboard's dataset, and its fix names the tree
- Status: FIXED
- Verified as: real (low). `_check_snapshot_schedule` checked only `DASH_UPDATE_SNAPSHOT_DATASET`. With one task on the apps dataset and none on the footage it returned OK, while `protection._check_snapshot_tree` (DASH_TREE_DATASET) returned BROKEN. The registry fix said "the dataset the project tree lives on" for a verdict about the dashboard's data.
- Fix: `invariants.py` `_check_snapshot_schedule` now checks BOTH `DASH_TREE_DATASET` and `DASH_UPDATE_SNAPSHOT_DATASET` through `protection._covers` (lazy import, because protection imports invariants). Each uncovered dataset is a subject with its own sentence. An OK detail names what was covered and which dataset the server was never told about ("not checked here"). Registry fix: "add a task for each dataset named below (or for its parent, with Recursive ticked)".
- Regression test: `test_a_task_on_the_dashboards_dataset_does_not_cover_the_tree`, `test_an_uncovered_dashboard_dataset_is_not_sent_to_snapshot_the_tree`, `test_a_recursive_parent_covers_both_and_an_unnamed_tree_is_said` - fail on HEAD (it reads OK, the fix names the tree, and the detail says nothing about the tree).
- Tests run: `tests/test_invariants.py tests/test_protection.py` + new file -> pass.
- Skew / deploy order: dashboard only. A site that sets DASH_TREE_DATASET but has no task on that dataset will see invariant 9 turn BROKEN on the first pass. The Protection panel already gives that verdict; the two now agree.
- OWED: none

## logic-alerts-6 - Invariants collector job is permanently amber ('2 not checked here')
- Status: FIXED
- Verified as: real (low). Every pass, `evaluate` emits NOT_CHECKED for `versioning_agrees` and `cards_tree_matches_source` (registry `skip_reason`). `_note` counts them, and `collector_health` renders any note amber.
- Fix: `invariants.py` new `_checkable()`. `run_cycle` now builds its `note` only from invariants this build can check at all. `counts`, and the Invariants page (which reads stored rows), still count the skips.
- Regression test: `test_a_clean_pass_leaves_the_collector_panel_green` (note is None on a clean pass; a checkable NOT_CHECKED still reads "1 not checked here") - fails on HEAD ("2 not checked here").
- Tests run: `tests/test_invariants.py tests/test_collector.py` + new file -> pass.
- Skew / deploy order: dashboard only.
- Not changed: per-pass "nothing to check" reasons (for example no vendor feed configured) still count. They describe site state rather than something fixed in the build, and whether to silence them is a separate decision.
- OWED: none

## logic-alerts-7 - file_move_detected with zero followers keeps its card for 7 days
- Status: FIXED
- Verified as: real (low). `_file_move_followed` returned "" when a move had no targets. The targets are written in the same `db.record_file_move` call as the move (collector.py ~1920), so an empty set is final rather than half-written.
- Fix: `notices.py` `_file_move_followed`: no targets -> "no computer held a copy to move". It is still gated by `min_hours` (24 h), so the card can be read for a day and then closes.
- Regression test: `test_a_hand_move_no_computer_held_closes_after_its_minimum_time` - fails on HEAD (still open at 24 h).
- Tests run: `tests/test_notices_auto_resolve_cr320.py tests/test_hand_moves_detected.py` + new file -> pass.
- Skew / deploy order: dashboard only.
- OWED: none

## logic-alerts-8 - Disk alerts for a computer that syncs nothing name an impossible consequence and fix
- Status: FIXED
- Verified as: real (PLAUSIBLE low, now confirmed). The companion sends `sync_guard.disk` from `lane_guard.disk_report(local_root)` on every heavy report without checking the plan, and api.py stores `disk_root_*` unconditionally. Neither `alerts._check_disk_low` nor `notices._check_machine_space` read the plan or the mode, and HEAD even alerted on a `mode=base` row.
- Fix: the `alerts.py` Ctx gains `full_tick_pairs`, one `db.fetch_machine_selections(sync_modes=(full,), for_enforce=True)` read, None when it cannot be read. `_check_disk_low` skips a base machine and one with no full tick. When the ticks cannot be read it keeps the old alert, because silence is the dangerous direction. `notices.py` `_check_machine_space` uses the same set plus `machine_state.mode`. For such a computer the `machine_disk_low` warn now says plainly that the drive is nearly full and syncing is not at risk. Its fix is "Ask whoever uses that computer to clear space on that drive.", with no untick. A machine that downloads keeps both old texts. `_check_disk_park` is untouched, because only a machine running lane B reports a park.
- Regression test: `test_a_computer_that_downloads_nothing_is_not_mailed_proxy_download_fears`, `test_the_disk_notice_for_a_computer_with_nothing_ticked_names_no_untick` - fail on HEAD (Razer and BASE are alerted; Razer gets the untick fix).
- Tests run: `tests/test_alerts.py tests/test_notices.py tests/test_bug_hunt_2026_09_18_dashboard_lows.py` + new file -> pass.
- Skew / deploy order: dashboard only.
- OWED: none
- Review round (2026-09-25, adversarial reviewer): both copy problems CONFIRMED. (1) `downloading` holds FULL ticks only, so a computer whose ticks are all upload_only lands in the no-download branch, and "nothing is ticked for it" was false in front of an admin who can see its tick. (2) "its syncing is not at risk" was false: SPEC "Shared asset libraries" puts the LUT library on every remote computer with no tick at all, and Syncthing stops a folder when the drive runs low. `notices.py` `_check_machine_space` body now reads "No project footage comes down to this computer (nothing it has ticked downloads, or it works straight off the server), so no project download will fill it, but the drive is nearly full, and anything else it syncs, such as the shared LUT library, stops when it runs out." The mechanism and the alert-side skip are unchanged (the reviewer found them right). Test `test_the_disk_notice_for_a_computer_with_nothing_ticked_names_no_untick` gains an upload-only-tick computer (LAPTOP) and asserts, for it and the no-tick one, no untick, no "nothing is ticked", no "not at risk", and that the shared LUT library is named; it fails on the first-round text.

## logic-alerts-9 - Reply poll caps at the newest 20 BEFORE skipping handled messages
- Status: ALREADY_FIXED
- Verified as: the same defect as bug-dash-ops-5, fixed (uncommitted) in this group's chunk 2 of wave 2. `triage_mail._unhandled_numbers` skips known Message-IDs before counting against `MAX_MESSAGES_PER_POLL`, and `poll` uses it (triage_mail.py ~720-790).
- Fix: none in this chunk.
- Regression test: chunk 2's `test_handled_messages_do_not_use_up_the_poll_cap`, `test_the_poll_cap_still_bounds_a_flood`.
- Tests run: new file -> pass.
- Skew / deploy order: dashboard only.
- OWED: none

## ui-dash-admin-10 - Protection refuses today's date as 'in the future' before 08:00 in UTC+8
- Status: FIXED
- Verified as: real (low). `set_ack` compared the typed date, which is in the browser's local time, with the UTC date.
- Fix: `protection.py` `set_ack` now refuses only dates later than the UTC date + 1 day. No time zone is more than +14:00 ahead, so every admin's local today passes, and a year typed wrong is still refused. This was chosen over the site time zone so that a missing tzdata or a travelling admin cannot bring the bug back.
- Regression test: `test_todays_local_date_east_of_utc_is_not_the_future` - fails on HEAD (ValueError at 23:00 UTC for the local date 2026-09-25). It also asserts that +2 days and +1 year are still refused.
- Tests run: `tests/test_protection.py` + new file -> pass.
- Skew / deploy order: dashboard only.
- OWED: none

## ui-dash-admin-13 - The restore confirm counts only missing files, so it can ask 'Copy 0 file(s)'
- Status: PARTIAL (template OWED to d-ui)
- Verified as: real (low). In the current working tree, `templates/partials/recovery.html` ~171-176 still reads `hx-confirm="Copy {{ recovery_preview.missing_count }} file(s) ..."` with the box unticked. d-ui's uncommitted edits to that file did not touch this line.
- Fix: the server half landed in chunk 2 (logic-admin-5): a changed-only restore with the box unticked is refused with a sentence that names the box by its label. Nothing more can be done in this group's files.
- Regression test: chunk 2's `test_a_changed_only_restore_names_the_box_that_does_it`.
- Tests run: new file -> pass.
- Skew / deploy order: dashboard only.
- OWED: d-ui, `dashboard/templates/partials/recovery.html` ~lines 171-182. This is the same item as chunk 2's logic-admin-5 OWED, and one change serves both. Render the `include_changed` checkbox `checked` when `recovery_preview.missing_count == 0 and recovery_preview.changed_count`. Word the `hx-confirm` from both counts, e.g. "Copy {{ missing_count }} missing file(s), and {{ changed_count }} different one(s) if the box is ticked, into a new folder? Nothing there now changes." Leave out the second clause when changed_count is 0, and use no em dash.

## ui-copy-3 - More next-action sentences name buttons or pages by names they do not have
- Status: FIXED
- Verified as: real (low). The real button is `[ ASK THIS COMPUTER WHY ]` (fleet_grid.html:465), not `[ ASK WHY ]`. No `[ UPDATE THE DASHBOARD ]` button exists; the Packages page's `[ DASHBOARD ]` panel has `[ UPDATE NOW ]` (admin_dashboard_update.html). `ui.SETTINGS_NAV_GROUPS` has no Projects page. Set-up is done from the tray's "Set up '<name>' on the server..." item (tray.py:4832). A crawl of every `[ X ]` label in this group's modules against templates/static finds no other unmatched label; the two hits are a docstring and the companion's own `[ UNDO LAST FIX ]`.
- Fix: the `alerts.py` red_unexplained fix now names "[ ASK THIS COMPUTER WHY ]". The `notices.py` ignored_report_sections fix now reads "Settings, Packages, then [ UPDATE NOW ] in the [ DASHBOARD ] panel. If that panel offers no update, this server needs a newer container image." The `collector.py` unreadable_project_marker fix and the `invariants.py` project_markers fix now read "set the project up again: open it in Resolve on a computer running CC Sync, then choose Set up '<project>' on the server from the CC Sync tray icon." The hunter's second suggestion, one label constant shared with the templates, would need d-ui's templates to read it and was not done for a low.
- Regression test: `test_the_named_controls_exist_under_the_names_the_copy_uses` - fails on HEAD (`[ ASK WHY ]`, `[ UPDATE THE DASHBOARD ]`, "Settings, Projects").
- Tests run: `tests/test_sweep_2026_09_04_copy.py tests/test_collector.py tests/test_invariants.py` + new file -> pass.
- Skew / deploy order: dashboard only. An `unreadable_project_marker` or `ignored_report_sections` notice that is already open gets the new fix text the next time it is re-filed.
- OWED: none
- Review round (2026-09-25, adversarial reviewer): CONFIRMED. `tray.py` ~4829 shows "Set up '<name>' on the server..." only when the report reply carries `resolve_project_unmapped`, and `api.py` ~9676 sends that only for a Resolve project with no `project_roots` row and no confident label match. A folder that lost its marker was a project, so its Resolve project is almost always already mapped and the item never appears. Both marker fixes now make restoring the file the only instruction and drop the tray route. `collector.py` (unreadable_project_marker) looks up the Syncthing folder serving that rel: when there is one, the fix names the exact value (`change its "slug" to "<that id>"`) and says the server usually writes a fresh marker itself within a few minutes (true: the self-heal in the same pass rewrites a damaged marker in a served folder that has `.stfolder` and no duplicate claimant, since `read_marker` returns None for it); otherwise it points at the id in the project's page address (`/project/<id>`, a real route in `ui.py`) or says to delete the damaged file if the folder was never a project. No literal `<project>` placeholder remains. `invariants.py` project_markers: "Restore the .ccsync-project file in each folder named below: copy the one from a working project and change its "slug" to the id this check names for that folder (the last part of the project's page address, /project/<id>)", plus when the server self-heals and that a file naming another id is never overwritten. Tests: `test_the_named_controls_exist_under_the_names_the_copy_uses` now asserts neither module's code names the tray icon or "Set up '", and that `/project/{slug}` is a route; new `test_a_damaged_marker_notice_says_how_to_put_the_file_back` drives the real `Collector._run_provision` over a FakeSyncthing with a damaged marker in a served folder (with `.stfolder`) and in a stray folder: it checks both fixes, and that a second pass closes the served folder's card (the self-heal claim is true) while the stray one stays open.

### Tests run for chunk 3
- `dashboard\.venv\Scripts\python.exe -m pytest tests/test_bug_hunt_2026_09_24_w2_d-diag.py tests/test_triage.py tests/test_triage_mail.py tests/test_invariants.py tests/test_protection.py tests/test_notices.py tests/test_notices_sweep_wave2.py tests/test_notices_auto_resolve_cr320.py tests/test_alerts.py tests/test_collector.py tests/test_hand_moves_detected.py tests/test_bug_hunt_2026_09_18_dashboard_lows.py tests/test_sweep_2026_09_04_copy.py tests/test_bug_hunt_2026_09_11_dash_collector_alerts.py tests/test_bug_hunt_2026_09_11b_dash_collector_alerts.py tests/test_live_notices_2026_09_21.py tests/test_sweep_2026_09_04_says_what_it_knows.py` -> 848 passed, 1 skipped.
- Every dashboard test file carrying an em-dash scan -> 652 passed, 1 skipped.
- No template changed in this chunk, so there are no screenshots.


# Owed round (2026-09-25, builder d-diag)

Items other groups left for d-diag's files. Tests appended to
`dashboard/tests/test_bug_hunt_2026_09_24_w2_d-diag.py` (section "OWED
round"). HEAD check: a scratch copy of the working-tree `src` with ONLY this
round's five edits reversed (the other groups' changes this relies on, such as
`jobs.REASON_SILENT` and `db.prune(jobs_cooldown_seconds=)`, left in place),
with conftest and the test file copied beside it: 6 of the 8 new tests fail
there; the 2 that pass are controls (a transient reason is still not starved;
a held job's cancel still names the computer).

Tests run (dashboard venv, from `dashboard/`): `pytest
tests/test_bug_hunt_2026_09_24_w2_d-diag.py tests/test_sweep_2026_09_04_copy.py
tests/test_alerts.py tests/test_triage.py tests/test_triage_mail.py
tests/test_bug_hunt_2026_09_18_dashboard_mediums.py tests/test_collector.py
tests/test_notices.py tests/test_help_doc_matches_the_companion.py
tests/test_diagnostics.py` -> 654 passed, 1 skipped, 1 failed. The one failure
is `test_sweep_2026_09_04_copy.py::test_no_retired_word_in_python_copy[jobs.py]`
and is not this round's: it parses the whole package and hit a SyntaxError in
`nas/synology.py:851`, a file another builder (d-ops) was editing at that
moment.

## ui-copy-5 (owed from c-ui) - the dashboard's route to Copy diagnostics
- Status: FIXED
- Verified as: `health.COMPANION_DIAGNOSTICS_PATH` was "Settings > Help > Copy diagnostics"; the companion's `ui_copy.DIAGNOSTICS` (c-ui, this wave) is "Tray > Settings > HELP > COPY DIAGNOSTICS FOR YOUR ADMIN". Consumers: alerts.py (three sentences), ui.py's `chip_help("crashes")`, admin_diagnostics.html (twice), fleet_grid.html's crash chip, all through the constant.
- Fix: health.py: the constant is the companion's wording word for word, "Tray >" kept. alerts.py `_check_restarts`, `_check_crashes`, `_check_upgrade_failed`: "Ask that editor to open {path}" became "to use {path}", since the route now ends at a button, not a window. Re-read the other consumers: "the editor used Copy diagnostics in the companion (Tray > ... ADMIN)" and "have the editor open Tray > ... ADMIN in the companion" still read; they are d-ui's, and not worth a route of their own.
- Existing test changed: `test_sweep_2026_09_04_copy.py::test_the_diagnostics_path_is_one_constant` asserted `"tray" not in path` (CR-88: the button is not on the tray menu). The new route starts at the tray but goes through Settings > HELP, so the assertion is now "Settings > HELP > COPY DIAGNOSTICS" in the path and the path does not start "Tray > Copy", which is CR-88's actual rule.
- Regression test: `test_the_dashboard_names_the_diagnostics_route_the_companion_uses` (reads `DIAGNOSTICS` from the companion's ui_copy.py source) and `test_the_crash_alert_reads_with_the_new_route` - both fail on HEAD's string.
- Skew / deploy order: none; copy only.
- OWED: d-ops, `docs/HOW_IT_WORKS.md` (served at /help by help.py) lines 857 and 893 still say "Settings > Help > Copy diagnostics"; make them "Tray > Settings > HELP > COPY DIAGNOSTICS FOR YOUR ADMIN" (`test_help_doc_matches_the_companion.py` passes either way). The fleet_grid.html ~477 and music app.js rows are already routed by c-ui.

## logic-ytdl-jobs-1 (owed from d-cards) - a queue only silent computers could take
- Status: FIXED
- Verified as: `_check_jobs_starved`'s `meaning` map named three codes; `jobs.REASON_SILENT` ("machines_not_reporting", non-transient since d-cards' fix) fell through to `return []`, so six hours of work waiting on switched-off machines raised nothing. It belongs with the three: waiting does not clear it.
- Fix: alerts.py `_check_jobs_starved`: `jobs_mod.REASON_SILENT` -> "every computer that could do it has stopped reporting to this dashboard". The transient codes stay out.
- Regression test: `test_a_queue_only_silent_computers_could_take_is_starved` (fails on HEAD's map: no finding); control `test_a_transient_reason_is_still_not_starved`.
- Skew / deploy order: dashboard only, ships with d-cards' jobs.py change (same package).
- OWED: none

## logic-ytdl-jobs-5 (owed from d-db) - the collector's lease sweep ignored DASH_JOBS_COOLDOWN_SECONDS
- Status: FIXED
- Verified as: `collector._run_prune` called `db.prune(conn, now, pin=pin)`, so d-db's new `jobs_cooldown_seconds` kwarg was never passed and the 120 s default applied on this path.
- Fix: collector.py `_run_prune`: passes `jobs_cooldown_seconds=getattr(self.settings, "jobs_cooldown_seconds", None)` (None keeps db's default for a stub settings object).
- Regression test: `test_the_collectors_lease_sweep_uses_the_operators_cooldown` - with the setting at 0, HEAD's call parks the machine for 120 s after its lease expires.
- Skew / deploy order: dashboard only, with d-db's db.py change.
- OWED: none

## logic-admin-7 (owed from d-ui) - a mailed cancel of a pinned job named a computer
- Status: FIXED
- Verified as: `triage_actions._x_cancel_job` answered every "requested" with "the computer running it is the only thing that can end it"; `db.request_job_cancel` returns "requested" for PINNED too, and a pinned job runs in this container's Timeline Cards worker.
- Fix: triage_actions.py `_x_cancel_job`: re-reads `db.get_job` after the request (it only writes `cancel_requested_*`) and for `JOB_PINNED` says "job #N will stop when this server's own worker next checks it; it is running here, not on any computer". No em dash (it goes out in the owner's mail).
- Regression test: `test_a_mailed_cancel_of_a_pinned_job_names_this_server` (HEAD: "computer running it"); control `test_a_mailed_cancel_of_a_held_job_still_names_the_computer`.
- Skew / deploy order: dashboard only.
- OWED: none

## ui-copy-6 (owed from d-ui) - " -- " in notices.py
- Status: FIXED
- Verified as: the AST scan d-ui used (docstrings, log calls and `execute()` SQL left out), run over every d-diag file (alerts, notices, invariants, health, collector, recovery, protection, mount_status, triage*): one hit, notices.py `record_slow_write`'s body, which is shown on the home page's PROBLEMS THE SERVER FOUND panel.
- Fix: notices.py: "Every other writer in that window (a companion report, the collector, a page) waited on it".
- Regression test: `test_the_slow_write_notice_has_no_typewriter_em_dash` - HEAD's body has " -- ".
- Skew / deploy order: dashboard only. A notice already open keeps its old body until the next slow write rewrites it.
- OWED: none

## Owed round 2 (2026-09-25)

### recovery.py: the rollback plan's create step linked `/projects` (owed from d-db)
- Status: FIXED, differently from the letter of the owed item.
- Verified as: `/projects` is not a page (the only route is the JSON `GET /api/v1/projects`), so [ GO ] was a 404. The owed fix, `href="/project-setup"`, would not have been honest either: ui.py `page_project_setup` 303s a bare `/project-setup` (no `resolve_project`) to `/`, which is the same "a page without the control" dead end the ui-copy-2 review refused for the Resolve step. PROJECT SETUP is keyed by a Resolve project name, and the plan does not know the lost project's name.
- Fix: recovery.py `_plan_whole_tree`: the step is now a NOTE (no [ GO ], no THIS SERVER CAN DO THIS chip) that says to open `/project-setup?resolve_project=` plus the project's name in Resolve, then [ CREATE & LINK ]. No em dash.
- Existing test changed: `test_recovery.py::test_the_rollback_plan_says_what_an_admin_can_do_and_who_to_ask` pinned `href == "/projects"`; it now pins that no step links `/projects` and a step names the keyed setup URL.
- Regression tests: `test_the_rollback_plans_create_step_names_a_page_the_dashboard_serves`, and `test_every_recovery_step_href_is_a_page_or_an_anchor_on_this_one` (every plan's every href is a GET route of ui.router, never a bare `/project-setup`, or an `id=` the recovery partial renders). Both fail on HEAD (ran HEAD's recovery.py in place, restored).
- Skew / deploy order: dashboard only; copy.
- OWED: d-ui, ui.py `page_project_setup`: a bare `/project-setup` could render a small "which Resolve project?" form instead of 303ing home. When it does, this step can go back to an action with `href="/project-setup"` (and the href test's `/project-setup` exclusion comes out).

### recovery.py `_plan_resolve`: "The dashboard has no button for this yet" (owed from d-ui)
- Status: FIXED
- Verified as: d-ui's `templates/partials/recovery.html` now draws `id="resolve-undo"` ([ UNDO A CLIP-PATH CHANGE ], per-journal [ UNDO THIS CHANGE ] posting to `/partials/admin/recovery/resolve-undo`) under `{% if recovery_problem == 'resolve' %}`, in the same partial and below the plan steps, so an in-page anchor resolves with no page load. `_plan_resolve` is only reached for problem=resolve.
- Fix: the first step is an action again, "Undo it from here", `href="#resolve-undo"`, naming [ UNDO THIS CHANGE ] and that it runs when the computer next reports with the project open; the tray's [ UNDO LAST FIX ] stays named for somebody at that computer.
- Existing test changed: `test_the_resolve_undo_step_claims_no_dashboard_button_that_does_not_exist` now pins the new truth: action, `#resolve-undo`, the anchor is inside the resolve-only block of the partial, the button names match the panel and the companion.
- Skew / deploy order: dashboard only; ships with d-ui's panel (same image).
- OWED: none

Tests: `dashboard\.venv\Scripts\python.exe -m pytest tests/test_bug_hunt_2026_09_24_w2_d-diag.py tests/test_recovery.py` -> 95 passed.

## Fable round (2026-09-25)

## logic-sync-truth-1 follow-up (fable-review-wave2-dashboard M2) - a quiet computer with nothing ticked led with an amber "Not heard from since ..."
- Status: FIXED
- Verified as: `health.fleet_headline` runs `_silence` before the informational `why` return, so a row with `why.reason == "no_selection"` and `status_reason` "no report since ..." answered `not_reporting` / amber (red after 6 h). The d-diag chunk ledger's claim that the informational path was untouched was wrong. Owner rule: nothing ticked is never an error, warning, blocked state or alert on any surface.
- Fix: `dashboard/src/ccsync_dashboard/health.py` fleet_headline: inside the silence branch, a row whose ranked why is `no_selection` returns `{reason: "no_selection", text: "Nothing ticked for this computer. Last report <YYYY-MM-DD HH:MM> UTC", level: muted}`. Any other row (including upload-only, which IS a tick) keeps `not_reporting` amber/red. `_silence_text` split into `_received_utc` + `_silence_text` + the neutral `_last_heard_text` ("Last report 15 minutes or more ago" when the stamp cannot be read). No em dash.
- Regression test: `dashboard/tests/test_bug_hunt_2026_09_24_w2_d-diag.py::test_a_quiet_computer_with_nothing_ticked_is_not_amber` (20 min and 7 h quiet, with and without lane rows) - fails on the pre-fix working tree (ran with the branch removed: 2 failed); on HEAD 4462a2a `_silence` did not exist, so this is a regression of this wave rather than of HEAD. Guards: `::test_a_quiet_computer_with_ticks_keeps_the_amber_headline`, `::test_a_reporting_computer_with_nothing_ticked_reads_as_before`.
- Tests run: see d-api Fable round (one run covered both).
- Skew / deploy order: dashboard only, no wire change.
- Note, not fixed here: the row's own status dot is still amber from `report_freshness` for a quiet nothing-ticked computer. That predates this wave (UX-2) and is composed in `api.build_editors_view`; if the owner reads the rule as covering the dot too, the change is there (d-api), not in the headline.
- OWED: none
