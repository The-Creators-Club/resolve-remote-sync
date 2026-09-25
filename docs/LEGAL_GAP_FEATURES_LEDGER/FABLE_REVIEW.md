# Final review of the legal-gap build (Fable, 2026-09-25)

Reviewed: the whole tree after groups G0, transport, G1a, G1b, G2a, G2b, G3,
G4, G6, G8 and G9, against `docs/LEGAL_GAP_FEATURES_PLAN.md` revision 2 and
the eleven ledgers in this directory. Method: read every diff on the wire
path end to end (companion -> dashboard -> views, and the reply back), then
probed with scratch scripts where reading was not enough. Small clear defects
were fixed here and are marked FIXED HERE; everything larger is under "Still
owed". No version bumped, nothing committed.

## Verdict

**CONDITIONAL PASS.** The build does what the six ENG-GAP paragraphs and the
Tier 2a items say, and it breaks nothing on the live fleet: the wire is
tolerant both ways, the cleartext guard classifies every address the fleet
actually uses as local or https, the site strip runs on arrival from every
companion version, export and erase reach every person-naming column and no
secret, and psycopg2 is one truth from the lock to the frozen binary.

It was NOT shippable as the ledgers left it. Two release blockers were open
hand-offs nobody had landed, and a further nine hand-offs were open. All of
them are landed by this review (section 1). One test is now RED BY DESIGN
(`dashboard/tests/test_legal_docs.py::test_lg1_markers_go_once_the_site_half_lands`):
it is G9's tripwire, and it fires precisely because the two blockers landed.
It stays red until the docs group replaces the two LG-1 paragraphs (section
3, item 1). That, the version bump and the overseer's release steps are what
remain between this tree and a ship.

## 1. Fixed here

Each was a real defect, traced before it was touched, and each has a test
that now covers it (existing pins were updated where their premise changed).

1. **BLOCKER, FIXED: `api.api_site` did not publish `telemetry`** (G2b
   hand-off 1). Traced consequence: a current companion never learned a site
   switch, so it SENT the withheld category (the dashboard stripped it, so
   nothing was stored, but it crossed the wire), the tray and wizard could
   not show "Turned off for everyone by your administrator", and, worse,
   `api._diagnostics_withheld_unredacted` treated a machine with an own list
   as "redacts its own bundle", so a current companion's unredacted
   diagnostics bundle WAS stored under a site switch. One line in `api_site`
   (`"telemetry": dict(site["telemetry"])`). `test_site.py`'s four pins pass.
2. **BLOCKER, FIXED: `dashboard/.../telemetry_fields.py` lacked the
   companion's two review-round rows and the `undo_detail` mask** (G1a
   hand-off). Under a site switch an older build's undo answers naming
   projects, and lane A's "skipped, exists" sample file names, were stored.
   Ported `resolve_undo_applied[].detail`, `sync_guard.skipped_exists.samples`,
   `MASKED["undo_detail"]` and `redact_undo_detail` with its two regexes. The
   Edit tool resolved the `“` escapes into the literal curly quotes, so
   the regex SOURCE differs from the companion's while the compiled pattern
   and every output are identical (probed on six sentences, including the
   three shapes `resolve_bridge` and `resolve_undo` actually produce). Both
   parity tests pass; `test_report_model_pin.py`'s NOT_PERSONAL entries for
   the two containers were reworded as containers.
3. **MEDIUM, FIXED: the grey chips and the licence line were never drawn.**
   `api.build_editors_view` never called `health.annotate_legal` (G2b
   hand-off 2) and `account_api._computer_view` did not carry `eula` /
   `report_withheld` (G2b hand-off 3). Both wired, wrapped so a failed read
   can never cost the status page. `test_site_telemetry.py`'s "says nothing
   without the facts" test now asserts the grey "Not reported" line and no
   colour, which is what the plan's LG-5 asks for.
4. **MEDIUM, FIXED: a site switch against an OFFLINE machine left the project
   slug in its stored journal ids** (G0 hand-off from G1a and G2a).
   `db._clear_categories` now masks the stored ids with the same
   `withheld:project/<file>` rule the report path applies.
   `test_legal_db.py`'s expectation updated.
5. **MEDIUM, FIXED: the licence texts reached no deployed dashboard** (G2b
   hand-off 4). `.dockerignore` re-includes `docs/legal/licenses/**/*.txt`,
   `tools/build_dashboard_bundle.py` and `server/install_dashboard_app.py`
   admit a `.txt` only where `published_docs.is_licence_text` says so, and the
   three-routes seam test (`test_bug_hunt_2026_09_11_dash_mounts_ui.py`)
   derives the extra re-include from `published_docs.TEXT_TREE`. Probed:
   `collect_files` now packs 19 licence files.
6. **MEDIUM, FIXED: ship.cmd's own build path scanned neither exe** (G6
   review point 2). `installer/build_editor_package.ps1` runs
   `tools/scan_frozen.py` after `-RebuildExe` (companion, `build\build`) and
   after `-RebuildOnboard` (onboarding, `build\build_onboard`), before the
   restamp and the signature; a refused exe is deleted and `Set-Failed`
   blocks the publish. The script parses (PowerShell AST). While making this
   edit the session's heredoc turned `\\b` into a 0x08 byte, exactly G6's
   review point 1; found by a byte scan, fixed byte-wise, and the file is now
   in `test_scan_frozen.py`'s control-byte parametrisation so it cannot come
   back unseen.
7. **LOW, FIXED: the wizard's stale-companion warning could never fire.**
   Neither onboard spec bundled `ccsync-release.json` beside the companion
   (G8 review point 3). Both specs now add it when it exists (a dev build has
   none, and the wizard then logs its neutral note).
8. **LOW, FIXED: `ui.safe_to_close` gave the wrong reason** for a computer
   that withholds its file list (G0 hand-off 8): it now says the computer
   does not report its file list, and stays never "Safe to close".
9. **MEDIUM, FIXED (found by this review, not a hand-off): the diagnostics
   stub trusted the mere presence of an own list.** A current companion whose
   manifest cache predates the site switch (up to `SITE_REFRESH_SECONDS` =
   900 s, or a lost cache, or a dashboard older than item 1) redacts nothing
   under that category and sends a bare bundle, and the dashboard stored it.
   The list a companion sends is local AND site (`telemetry_policy.effective`),
   so the dashboard can tell: `_diagnostics_withheld_unredacted` now returns
   the site categories the machine's own last list did NOT name. G2a's
   "a build with the switches is stored as sent" test was rewritten to send
   the site category (that is what "has read the policy" looks like), and a
   new test covers `[]` and an unrelated own switch under a site switch.
10. **Test pins that the build moved on purpose:** `test_account_db.py`
    (v58 head -> `SCHEMA_VERSION`, G0 hand-off 1); `test_site_drive_letter.py`
    (`_on_verify` ends in `show_privacy()`, G8 review point 1); ytdl's
    `test_review_2_with_no_way_to_make_a_stand_in...` (its premise was G4's
    one-argument contract; `api._forget_elsewhere` now hands over the
    dashboard connection and the stand-in, G2a review point 1, so the delete
    goes through; the test now asserts that, and the warning path on a store
    failure).

## 2. Verified by probe or trace (no change needed)

- **Cleartext guard vs the live fleet.** Probed `transport.classify` and the
  real `upgrade.build_no_redirect_opener()` chain with DNS forced to fail:
  `http://192.168.0.10:8480`, `http://100.66.62.41:8480`, `http://truenas:8480`,
  `http://truenas.local:8480`, `http://ccsync.tail1234.ts.net`,
  `http://[fd7a:...]`, 10/8, 172.16/12 all `http_local`; loopback `loopback`;
  `https://...` `https`; an unresolvable public-looking name `http_local`
  (never on doubt); `http://8.8.8.8` and a HiNet-shaped public IP
  `http_public` and refused before any byte. A dead LAN port through the real
  opener is a plain `URLError`, never `CleartextRefused`. This base rig's
  `dashboard_url` is `https://truenas.tail26290e.ts.net:9443`. Start-up
  `validate_config` never asks DNS (`lookup=for_save`). The guard also covers
  lane C's Syncthing admin calls, whose default is loopback.
- **Wire both ways across versions.** New companion -> 0.7.60 dashboard:
  `report_optouts` and `eula` are `extra="allow"` keys recorded on the SYS-3
  "ignored sections" banner, nothing 422s; deploy the dashboard first as the
  plan says. Old companion -> new dashboard: `_report_withheld` reads the
  site set, the absent key keeps the stored own list, `telemetry_fields.strip`
  runs on the parsed model before the first section write, then
  `apply_report_optouts` deletes what earlier reports left. Switching the
  site back on: `apply_site_optouts` recomputes every union, an old build's
  row returns to NULL, and its next report is stored again: nothing is
  withheld for good. `site.normalise` on an older dashboard's manifest reads
  all four as reported.
- **Telemetry switches stop the data AND delete what was held without
  breaking sync.** Collect-then-withhold is real: `_refresh_media_tree_once`
  still runs the stale-bridge recovery, relink and classify (tests count the
  calls); the reporter withholds BEFORE the unchanged-section suppression so
  a section switched back on is re-sent (its stamp is dropped by
  `_note_sections_sent`); the dashboard deletes `editor_media`,
  `editor_media_project`, `media_tree_clips`, the `resolve_health:` meta row
  or its path keys, NULLs `resolve_project`, `cap_resolve_project` and
  `cap_idle_seconds`, deletes diagnostics on a NEWLY withheld content
  category, and a machine withholding its file list is a file-move target
  for every active project and an `uncertain` backlog row that is never
  "Safe to close". Withheld is never a colour, alert or notice; open
  stray/moved findings are withdrawn silently. `report_*` keys are not
  remote-controllable (pinned on both sides).
- **Export and erase completeness.** Scanned the migrated v59 schema with a
  scratch script: no column matching editor/user/_by/actor/subject/holder/
  owner/sender/from_addr/requested/machine sits in a table outside
  `SUBJECT_TABLES` or `NOT_SUBJECT_TABLES`; no secret-shaped column is
  exported (`password_hash`, `token_hash`, `signature`, `site_settings.value`
  excluded; `progress_token`, `token_id`, `pubkey_id` and
  `must_change_password` are identifiers or flags, checked); the session
  export drops the sid; the client-folder export drops the link `token`; the
  ytdl schema keeps no secret. Erase deletes the `history` kind only and
  keeps `mode`, the breaker and halt latches, `editor_media` and the live
  session; an active lockout survives.
- **Delete leaves no real name behind.** After `db.forget_editor`
  pseudonymises, nothing writes the real name again: `user.delete`'s subject
  is the stand-in, `_purge_user_credentials` and
  `db.revoke_editor_report_token` write no audit row, `local_users.delete_user`'s
  row is written before `forget_editor` and rewritten by it, revoked tokens
  are deleted after the revocation, and `_forget_elsewhere` hands the
  dashboard connection and the stand-in to ytdl and client folders and
  commits after each. The stand-in salt never rotates.
- **psycopg2.** `companion/requirements.lock` carries `psycopg2-binary==2.9.13`
  with 67 hashes (win_amd64 and macosx arm64 among them per G6's PyPI check);
  the allowlist targets `companion`; `check_licenses.py --only companion` is
  OK; `release.ps1`, `release_macos.sh` and CI install from the lock with
  `--require-hashes` and run `scan_frozen.py`, which also ties the committed
  licence texts to the frozen versions; ship.cmd's path is covered since item
  6 above. The lock also carries `pg8000` (both drivers freeze; not a defect,
  G6's hand-off about the stale pyproject comment stands).
- **Retention alarm.** `collector_health` marks a kind overdue only when its
  last run was ok, it is scheduled here, the collector is not stale, and its
  age passes `max(180 s, 2 x max(observed gap, configured interval)) + the
  longest recent cycle`; `prune`'s configured interval is 3600 s; the panel
  line reads `retention_last_ran`; `collector_kind_overdue` is debounced by
  one alerts interval, holds quiet under a stale collector or a failed run,
  and `prune` has its own wording. Failure stays `collector_kind_failed`.
- **Site policy from the environment** is applied at boot
  (`seed_from_env_once` -> `enforce_telemetry_policy`, after `db.migrate`),
  and every Settings save, import and undo pass through `set_many`.

## 3. Still owed (not fixed here)

1. **BLOCKER for the version bump: the LG-1 wording.** With items 1 and 2
   landed, `test_legal_docs.py::test_lg1_markers_go_once_the_site_half_lands`
   is red on purpose. The docs group replaces the two
   `telemetry-opt-out-switches` paragraphs with plan 8.1 as amended in the G9
   ledger (hand-off 1 there: the undo-answer and skipped-samples parentheses
   and the pre-switch-companion cost sentence), removes both markers, empties
   `EXPECTED_ENG_GAPS`, and deletes the "pending as of 2026-09-25" notes in
   `docs/CONFIG.md` and `docs/API.md`. Add G4 review point 7's wording
   (search text survives on job and download records and folder names under
   the stand-in). Item 9 above can be stated as: a bundle from a computer
   that has not yet read the site policy is replaced by a note.
2. **Overseer, release steps** (from the ledgers, unchanged): bump versions
   and fill `<DASH>`/`<COMP>` in KNOWN_BUGS CR-336..CR-345; regenerate
   `THIRD_PARTY_NOTICES.md` with plain `python tools/gen_notices.py` after
   `companion/.venv` has been rebuilt from the lock (`--check` is out of date
   now, as expected; never `--venv companion=<scratch>` for the document);
   commit `docs/legal/licenses/`; re-ship the music encoder NOTICE/LICENSE
   (`install_dashboard_app.py --music-data encoder`); Mac builds on a Mac
   (`release_macos.sh`, `build_onboard_macos.sh`); deployed-build checks (the
   Cards role reads a project library from the FEED build, the
   `[scan_frozen] OK` line, About -> Open-source licences, the wizard's
   privacy page and a public-http refusal on its role page); pre-ship check
   that no machine shows `report_via = 'http_public'`; set
   `DASH_TRUSTED_PROXIES` for the Tailscale Serve layout or accept that the
   Settings count reads Serve traffic as `http_local` (informational only,
   no alert). Do not make an onboard build current on a platform until that
   platform's bundled companion is the G1a build.
3. **Docs outside G9's files:** `onboarding/README.md` wizard flow (privacy
   step, role-page refusal, licences button); `docs/SELF_DIAGNOSIS.md` gains
   `collector_kind_overdue` (WARN) and `dashboard_reached_over_public_http`
   (ERROR); the plan's own section 4.4 "cached for 10 minutes" reads 30 s and
   its section 4.1 table gains the two rows.
4. **(counsel) items, collected from G6 and G9 for the owner:** PRIVACY
   section 8 "Objection"; THIRD_PARTY "Licence texts" bundled-copy sentence;
   the psycopg2 paragraph's "unmodified" on macOS; rclone v1.75.0 and
   editor-side Syncthing v2.1.3 are pinned, not resolved at install time;
   TELEMETRY's jobs row says `idle_seconds` is still reported while
   `jobs_enabled = false` (D4 made it null); the TELEMETRY payload table's
   two moved keys and the "still sent" `sync_guard` keys.
5. **Low, noted, not changed.** (a) `_JOURNAL_IN_TEXT` masks a journal id
   only when `.json` is followed by `:`, whitespace or end of line; a sentence
   ending `(record <id>)` would keep it. No current sentence has that shape
   and the companion replaces known names first, so it is a note for whoever
   adds an undo sentence. (b) An admin's own export includes every audit row
   they acted on (`actor = :username`), whose detail can name other people;
   that is the plan's "actor or subject" rule and the file is the admin's
   own, but it is worth a sentence in the wording one day. (c) The tray copy
   for a refused address says "CCSync" where the product name elsewhere is
   "CC Sync" (`config.DASHBOARD_URL_PUBLIC_HTTP`); cosmetic.

## 4. Tests run (only files touched by this review, plus the files that pin
the code it changed)

| Suite | Files | Result |
|---|---|---|
| dashboard | the ten new legal-gap files, `test_site`, `test_account_db`, `test_diagnostics`, the 09-11 mounts-ui and 09-24 w2 d-ui hunts, `test_templates_wave3`, `test_admin_delete`, `test_admin_users_local`, `test_help_page`, `test_account_page`, `test_site_history`, `test_multi_machine`, `test_upload_only`, `test_site_manifest_consumers`, `test_site_store` | **823 passed, 1 skipped, 1 failed** (the LG-1 docs tripwire, red by design) |
| companion | `test_telemetry_policy`, `test_telemetry_disclosure`, `test_eula_report`, `test_transport`, `test_identity`, `test_config`, `test_reporter`, `test_upgrade`, `test_site`, `test_capabilities`, `test_settings_window`, `test_app`, `test_resolve_undo_command`, `test_diagnostics_upload` | **1489 passed** |
| onboarding | `test_legal_steps`, `test_site_drive_letter`, `test_no_em_dashes`, `test_release_gates`, `test_macos_steps` | **197 passed** |
| tools | `test_scan_frozen`, `test_gen_notices`, `test_check_licenses`, `test_release_scripts`, `test_docs_index` | **151 passed** |
| ytdl/web | `test_ytdl_subject` | **25 passed** |
| server (Git Bash) | `test_bug_hunt_2026_09_11b_server_tools`, `test_bug_hunt_2026_09_18_webapps_tools`, `test_cross_component`, `test_image_mode` | **142 passed** |

Also: `check_licenses.py --only companion` OK; `build_dashboard_bundle.collect_files`
packs the 19 licence texts; `build_editor_package.ps1` parses and carries no
control byte. The full gate (`tools\run_all_tests.ps1`) is the overseer's,
per the owner's rule.

## 5. Files changed by this review

- `dashboard/src/ccsync_dashboard/api.py` (api_site `telemetry`;
  `build_editors_view` -> `health.annotate_legal`;
  `_diagnostics_withheld_unredacted` reads the sent list)
- `dashboard/src/ccsync_dashboard/telemetry_fields.py` (two rows, the
  `undo_detail` mask and `redact_undo_detail`)
- `dashboard/src/ccsync_dashboard/account_api.py` (`eula`, `report_withheld`)
- `dashboard/src/ccsync_dashboard/db.py` (`_clear_categories` masks stored
  journal ids)
- `dashboard/src/ccsync_dashboard/ui.py` (`safe_to_close` wording)
- `.dockerignore`, `tools/build_dashboard_bundle.py`,
  `server/install_dashboard_app.py` (licence texts ship)
- `onboarding/build_onboard.spec`, `onboarding/build_onboard_macos.spec`
  (`ccsync-release.json` beside the companion)
- `installer/build_editor_package.ps1` (two `scan_frozen` gates)
- tests: `dashboard/tests/test_legal_db.py`, `test_report_optouts.py`,
  `test_report_model_pin.py`, `test_site_telemetry.py`, `test_account_db.py`,
  `test_bug_hunt_2026_09_11_dash_mounts_ui.py`;
  `onboarding/tests/test_site_drive_letter.py`;
  `tools/tests/test_scan_frozen.py`; `ytdl/web/tests/test_ytdl_subject.py`

## Progress at pause (closing pass, 2026-09-25)

The closing pass (overseer's steps 1-6 after this review) was paused at the
owner's session limit. Nothing is committed and no file is half-edited.

**Done:**

1. **LG-1 wording.** Each claim of plan 8.1 was checked in code first
   (`telemetry_policy.FIELDS`/`effective`, `settings_window._privacy_controls`,
   the wizard's `show_privacy`, `admin_settings.html` TELEMETRY,
   `db.apply_report_optouts`/`apply_site_optouts`/`_clear_categories`,
   `db.file_move_targets`' withheld arm, `_backlog_not_reported`,
   `capabilities` D4, `api._diagnostics_withheld_unredacted`). PRIVACY 6 has
   8.1 verbatim; TELEMETRY "What can be turned off" has 8.1 with the G9
   amendments, the pre-switch-companion cost worded to the code (undo: project
   name only; the diagnostics note: any of the three content categories) and
   review item 9 (a computer that has not yet read a site switch; the 900 s
   `SITE_REFRESH_SECONDS` stated as 15 minutes). Both markers are out;
   `EXPECTED_ENG_GAPS` is empty; the CONFIG.md and API.md pending notes are
   gone, and so is API.md's erase-history pointer to them. G4 review point 7
   is in PRIVACY 8 (search text stays on job and download records and folder
   names under the stand-in; the erase bullet says the same). The EULA needed
   no change. `test_legal_docs.py` + `test_help_page.py` +
   `test_published_licenses.py`: 74 passed, 1 skipped.
2. **Notices.** `companion/.venv` was synced to its lock
   (`pip install --require-hashes -r requirements.lock`: it lacked
   `psycopg2-binary` 2.9.13); `gen_notices.py` then `--write-texts`;
   `--check` exits 0. `docs/legal/licenses/` holds all 17 companion
   distributions plus both bundles (the two pyobjc texts are kept from the
   previous run, since they are macOS-only and absent from this venv).
   `tools/tests/test_gen_notices.py`, `test_scan_frozen.py` and
   `test_check_licenses.py`: 82 passed.
3. **KNOWN_BUGS.** The heading and CR-339 now say dashboard 0.7.61 /
   companion 0.9.81 / installer 1.0.46. The "open"/"owed" notes in CR-336,
   CR-340 and CR-341 now say the item has landed. Edited byte-wise: the NUL
   and the CRLF count are unchanged.
4. **Versions.** Dashboard 0.7.61 (`pyproject.toml`, `__init__.py`),
   companion 0.9.81 (`pyproject.toml`, `config.py`). The wizard changed in
   this build, so installer 1.0.45 -> 1.0.46 in the four places commit
   823c9c9 bumped (`macos_bootstrap.sh`, `windows_bootstrap.ps1`,
   `onboarding/steps.py`, `build_onboard_macos.spec`).
5. **Small docs.** `onboarding/README.md`: the role page's public-http
   refusal, a 4b privacy step and the finish pages' licences button.
   `docs/SELF_DIAGNOSIS.md`: `dashboard_reached_over_public_http` and
   `collector_kind_overdue` rows, and the kind count, which was already
   stale at 59, is now 64. Plan 4.4: the cache is 30 s, with the reason.
   Plan 4.1: rows for the two masked fields and `skipped_exists.samples`, and
   `sync_guard.` qualifiers. `docs/GOTCHAS.md` section 24 already had the
   30 s TTL, the two-lookup race and the Syncthing coverage (checked against
   `transport.RESOLVE_TTL_SECONDS` and `syncthing_admin._opener`), so it is
   unchanged.

**Not done:**

6. **The full gate.** It was started before the pause, in the background,
   and was still in the companion suite, about 6% through, when this was
   written. The log is the session scratchpad's `gate.log`, which may not
   survive the session. **Next action:** from the repo root, run
   `powershell -NoProfile -ExecutionPolicy Bypass -File tools/run_all_tests.ps1`
   (use forward slashes from Git Bash: a backslash path was eaten once), then
   read the summary table and fix any red that belongs to the legal-gap build.
   Suites most likely to notice this pass: onboarding (the installer version
   pins), `tools/` (release-script and docs-index tests) and dashboard
   (`test_legal_docs.py`).

**Gate result (the run that was already going finished after this note was
written; nothing has been fixed since).** 2 of 13 suites failed: companion
FAIL (1 failed, 8021 passed), dashboard FAIL (3 failed, 5516 passed); server,
onboarding, bench, broll/web, broll/indexer, music/web, music/indexer,
ytdl/web, tools, installer and installer/macos PASS. All four reds belong to
the legal-gap build, not to the closing pass:

- `companion/tests/test_shutdown_guard.py::test_every_module_logs_under_the_ccsync_logger`:
  `transport.py` logs under `ccsync_companion.transport`, a logger nothing
  listens to. Fix: its logger must hang under the `ccsync` tree like the
  other modules do (see how its neighbours name theirs). Mind that it is a
  leaf module loaded by path from the wizard and the dashboard's parity test.
- `dashboard/tests/test_mobile_admin.py::test_confirms_fit_a_phone_dialog[/admin/users]`
  and `[/partials/admin/users]`: the ERASE HISTORY confirm is 155 characters
  against the 90 cap ("Erase the history of newbie? This removes their past
  activity. Their computers keep reporting their current state unless you
  switch reporting off for them."). Fix: shorten it to 90 or fewer, and keep
  no em dash.
- `dashboard/tests/test_sweep_2026_09_04_copy.py::test_no_retired_word_in_rendered_copy[admin_users.html1]`:
  `admin_users.html` line 23 says "past lane and transfer history". CR-179
  retired "lane" in shown copy. Fix: say "sync and transfer history", for
  example.

Next action: fix those three things, re-run the companion and dashboard
suites, then run the full gate once.
