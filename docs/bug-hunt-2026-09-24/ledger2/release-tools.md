# Wave 2 ledger: release-tools (chunk 1 of 1)

Files touched: `tools/publish_feed.py`, `tools/publish_latest.py`,
`tools/ship.ps1`, `docs/RELEASE.md`, `docs/RELEASE_FEED.md`,
`docs/RELEASE_PATHWAYS.md`; new tests in
`tools/tests/test_bug_hunt_2026_09_24_w2_release-tools.py` (25 tests).

HEAD check: the new test file was run against a scratch tree holding HEAD's
`publish_feed.py`, `publish_latest.py`, `ship.ps1` and `RELEASE.md` (everything
else from the working tree): 19 failed / 6 passed. The 6 that pass on HEAD are
the negative guards (a retract of a non-current build, a retract of the only
build, "already current is nothing to do", "never move the pointer backwards",
a SIGNED requires_dashboard still refuses, a journal at `build` still probes).

Tests run (dashboard venv, from `tools/`):
`python -m pytest tests/test_publish_feed.py tests/test_publish_latest.py
tests/test_release_scripts.py tests/test_release_notes_flag.py
tests/test_bug_hunt_2026_09_24_webapps_ops.py tests/test_docs_index.py
tests/test_sign_release.py tests/test_bug_hunt_2026_09_24_w2_release-tools.py -q`
-> 239 passed. `ship.ps1` parses with 0 errors (PowerShell AST parser).

Skew / deploy order for all six: vendor-rig tooling only. No wire key, no
schema, nothing a companion or dashboard reads changed: the channel document
is the same shape (`current` was already a signed top-level map), so every
dashboard version reads a channel written by `--set-current` exactly as one
written by `--make-current`. Nothing to deploy; takes effect on the next
`publish_latest` / `publish_feed` / `ship.cmd` run from this checkout.

## logic-release-2 - Retracting the current build made `policy = current` sites take a newer STAGED build
- Status: FIXED
- Verified as: CONFIRMED medium (verifiers/med-12.md). Re-read at HEAD:
  `retract_record` pops `current[kind/platform]` and nothing sets a
  replacement; `release_feed.select_offered_records` with no pointer for the
  pair takes the highest version. The new test runs the dashboard's own
  `select_offered_records` on the resulting channel.
- Fix: `tools/publish_feed.py` main(): a `--retract` that removes the pair's
  `current` pointer is REFUSED (before anything is signed or written) unless
  the same run puts a pointer back (`--set-current KIND/PLATFORM/VERSION`, or
  `--artifact ... --make-current` for that pair) or passes the new
  `--allow-no-current`. The refusal names what customers would have received
  (and says NEWER when it is) and suggests the highest remaining version
  below the retracted one. A retract of a non-current build, or of the only
  build of a pair, is unchanged. The recall line publish_latest prints now
  carries `--set-current <previous current>` (see bug-ops-3). Docs:
  RELEASE.md rollback section + command list, RELEASE_FEED.md `--retract`.
- Regression test: `tools/tests/test_bug_hunt_2026_09_24_w2_release-tools.py::test_retracting_the_current_build_with_a_newer_staged_one_is_refused`,
  `::test_retract_with_set_current_rolls_the_fleet_back`,
  `::test_allow_no_current_keeps_the_old_highest_wins_on_purpose` - fail on
  HEAD because the retract exits 0 with `current` empty (and the flags do not
  exist).
- Tests run: see top -> 239 passed.
- Skew / deploy order: none (vendor tooling). The existing
  `test_a_retraction_removes_the_record_and_the_current_pointer` still passes:
  it retracts the only windows record, where no refusal applies.
- OWED: none. (Observation, not fixed: `merge_into_published` overlays the
  LOCAL feed dir's `current` over the published one, so a second rig with a
  stale `feed/` could re-point `current` after another rig's rollback. One
  rig publishes today; left as is.)

## logic-release-6 - "Re-run with --make-current" was a no-op
- Status: FIXED
- Verified as: CONFIRMED medium (verifiers/med-12.md). At HEAD the
  `(kind, plat, version) in already` skip runs before publish() and never
  reads `args.make_current`; publish_feed had no way to move the pointer
  without an artifact.
- Fix: `tools/publish_feed.py` gains `--set-current KIND/PLATFORM/VERSION`
  (pointer only; refused for a version the channel does not carry, for a
  recalled one, and by the REL-7 key check against the build current before
  the run). `tools/publish_latest.py`: when the version is already published
  and `--make-current` is given: already current -> "nothing to do (and
  CURRENT)"; older than current -> refuses to move the pointer backwards and
  names the deliberate `--set-current` rollback; same sha256 as this run ->
  `move_pointer()` runs `publish_feed.py --set-current ... --github-upload`;
  different sha256 -> moves nothing, says NOT made current, prints the exact
  `--set-current` line for the staged record. Skips now say "still STAGED
  (current is X)". The STAGED summary sentence now says what the re-run does.
  RELEASE_PATHWAYS.md step 4 and RELEASE.md updated (they documented the
  trap and a by-hand same-bytes recovery).
- Regression test: `...::test_make_current_on_a_staged_same_bytes_version_moves_the_pointer`
  (fails on HEAD: no publish_feed call at all, "nothing to do"),
  `::test_make_current_with_different_bytes_says_how_and_moves_nothing`
  (fails on HEAD: no guidance line), plus the `set_current_*` publish_feed
  tests; `::test_make_current_never_moves_the_pointer_backwards` and
  `::test_make_current_on_a_version_already_current_is_nothing_to_do` guard
  the new branch.
- Tests run: see top -> 239 passed.
- Skew / deploy order: none.
- OWED: none.

## bug-ops-2 - ship.cmd -Resume past the publish died on "already published, bump VERSION"
- Status: FIXED
- Verified as: DOWNGRADE to low (verifiers/med-08.md). Confirmed at HEAD:
  both curl probes (companion, installer) run after `-Resume` sets
  `$script:ResumeFrom` and nothing between reads it, so a journal at
  `publish` (step 2b exit 3, the soak refusal whose message says "re-run:
  tools\ship.cmd -Resume") or `current` always exits 1. A second defect on
  the same path, found while tracing it: the resumed step 2b passed
  `-RebuildOnboard` again, and a PyInstaller rebuild under the same installer
  version is a different-bytes 409 in build_editor_package.ps1 (Set-Failed,
  exit 1), so even past step 0 the resume failed.
- Fix: `tools/ship.ps1`: `$script:ResumedPastPublish = Test-StepDone
  "publish"`; when true both probes are skipped with a one-line note
  (`$InstallerVersion` is still parsed, later steps need it). `$pkgArgs` drops
  `-RebuildOnboard` only when resumed past the publish AND
  `onboarding\dist\onboard.exe` is newer than `companion\dist\
  ccsync-companion.exe` (i.e. the earlier 2b really built it); otherwise it
  rebuilds as before. A journal at `build` (nothing published by this ship)
  still probes, so a real version collision is still caught.
- Regression test: `...::test_resume_after_the_publish_is_not_a_version_collision[publish-True|current-True|build-False]`
  EXECUTES the step-0 block out of ship.ps1 in real PowerShell with a stubbed
  journal and curl (the two True cases fail on HEAD: exit 1, "ALREADY
  published"); `::test_a_resumed_publish_reuses_the_onboard_exe_it_published`
  (source guard; fails on HEAD).
- Tests run: see top -> 239 passed; ship.ps1 AST parse 0 errors.
- Skew / deploy order: none (operator script).
- OWED: none. (build_editor_package.ps1, onboarding group, already treats a
  byte-identical companion/installer 409 as "continue", which is what makes
  the resumed 2b work; no change needed there.)

## bug-ops-3 - The recall command publish_latest prints does not parse
- Status: FIXED
- Verified as: DOWNGRADE to low (verifiers/med-08.md). Confirmed at HEAD:
  the printed `--retract --kind <kind> --platform ... --version ...` hits
  argparse "expected one argument", and it lacked `--feed-dir` /
  `--github-repo`.
- Fix: `tools/publish_latest.py` `recall_argv()` builds the argv from the same
  constants publish() uses (`--retract k/p/v --reason "<why...>" --feed-dir
  feed --github-repo The-Creators-Club/ccsync-releases --github-upload`), one
  line per record published (or made current) in the run, quoted with
  `subprocess.list2cmdline`. When the run made the record current it adds
  `--set-current <previous current>` (or `--allow-no-current` when there was
  none), so the line passes logic-release-2's new refusal and IS the rollback.
- Regression test: `...::test_the_printed_recall_line_parses_and_rolls_back`
  (parses the printed line with publish_feed.parse_args, then RUNS it against
  a local feed and checks `current` went back to the previous build; fails on
  HEAD at the parse), `::test_a_staged_publish_recall_line_needs_no_successor`.
- Tests run: see top -> 239 passed.
- Skew / deploy order: none.
- OWED: none.

## logic-release-5 - The SYS-7 ordering gate judged a requires_dashboard that is never signed, and hid the note
- Status: FIXED
- Verified as: DOWNGRADE to low (verifiers/med-12.md). Confirmed: sign_release
  drops requires_dashboard unless `--emit-kind-extras` /
  `CCSYNC_EMIT_KIND_EXTRAS=1` (publish_feed passes no flag, so the env var is
  the only way), and publish_latest wrote publish_feed's stderr only on a
  non-zero exit. The customer-side absence of the check is the deliberate
  REL-4/REL-16 overlap policy and is NOT changed.
- Fix: `tools/publish_latest.py`: `kind_extras_signed()`; with extras off, a
  manifest `requires_dashboard` produces one NOTE saying it is NOT signed and
  customers get no ordering check (and naming the newest dashboard bundle)
  instead of a refusal; with `CCSYNC_EMIT_KIND_EXTRAS=1` the SYS-7 gate runs
  exactly as before. publish()/move_pointer() now always echo publish_feed's
  stderr, so sign_release's own NOTE reaches the operator. `--allow-behind`
  help says when it applies.
- Regression test: `...::test_an_unsigned_requires_dashboard_is_a_note_not_a_refusal`
  (fails on HEAD: SystemExit from the gate, and stderr swallowed),
  `::test_a_signed_requires_dashboard_still_refuses` (guard).
- Tests run: see top -> 239 passed (test_publish_latest's source guards on
  `--allow-behind` / `carries no dashboard bundle at all` still hold).
- Skew / deploy order: none.
- OWED: none.

## logic-release-7 - --allow-older documented as the rollback; nothing moved the pointer alone
- Status: FIXED
- Verified as: low, not verified by anyone before; verified here. At HEAD
  publish_latest only takes the newest green run (a rollback target is either
  "already published, nothing to do" or not the run it looks at), `set_current`
  was reachable only inside publish_feed's `--artifact` branch, and
  RELEASE.md:183 said "`--allow-older` for a deliberate rollback".
- Fix: the pointer-only move is `publish_feed.py --set-current` (see
  logic-release-6). `--allow-older` help and the "OLDER than" refusal now say
  it is not a rollback and name `--set-current`. RELEASE.md: the
  `--allow-older` sentence is corrected and a "Rolling the vendor feed back"
  section gives the two commands (pointer move; retract + set-current in one
  run); the command list and RELEASE_FEED.md document `--set-current`.
- Regression test: `...::test_set_current_rolls_back_to_an_older_record`,
  `::test_set_current_alone_makes_a_staged_record_current`,
  `::test_release_md_no_longer_calls_allow_older_the_rollback` - fail on HEAD
  (no such flag; the doc sentence is there).
- Tests run: see top -> 239 passed.
- Skew / deploy order: none.
- OWED: none.

## Review round (2026-09-25)

Tests run after the round (dashboard venv, from `tools/`): the same eight
files as above -> 250 passed (the w2 file now holds 36 tests). `ship.ps1`
parses with 0 errors. HEAD-of-round check: the new tests were run against a
scratch copy with this round's changes backed out: all 8 new ones fail there
(`pointer_move_forwards_allow_key_rotation`, `pointer_move_names_the_flags...`,
`different_bytes_guidance_carries_allow_key_rotation`,
`resume_after_an_installer_bump_probes_again[publish|current]`,
`onboard_reuse_needs...[steps.py|bootstrap]`,
`a_failed_step_2b_does_not_advance_the_journal_to_publish`).

### logic-release-6 - review: move_pointer dropped --allow-key-rotation
- Reviewer was right. `move_pointer()` built its own argv and never saw
  `extra`, so publish_feed's REL-7 refusal on `--set-current` ("pass
  --allow-key-rotation") could not be answered through publish_latest.
- Fix: `move_pointer(..., allow_key_rotation)` appends `--allow-key-rotation`
  when publish_latest was given it; the "different bytes" guidance line
  carries it too, so that printed command also clears the refusal the
  operator already chose to override. `--min-version` / `--notes` on the
  pointer-only path are now named in a NOTE ("NOT applied: the staged record
  keeps the values it was published with") and are not forwarded (a pointer
  move rewrites no record; `--set-current` does not take them).
- Tests: `::test_pointer_move_forwards_allow_key_rotation` (parses the argv
  with publish_feed.parse_args), `::test_pointer_move_without_the_flag_does_not_add_it`,
  `::test_pointer_move_names_the_flags_it_cannot_apply`,
  `::test_different_bytes_guidance_carries_allow_key_rotation`.

### bug-ops-2 - review: the resume shortcuts were under-guarded
- Reviewer was right on both counts.
  (1) `Save-ShipStep -Step "publish"` ran before `$pkgRc` was read (as at
  HEAD). It now runs only for exit 0 or 3; a failed 2b leaves the journal at
  `build`, which resumes exactly as HEAD's journal-at-publish did (skips the
  build, runs the probes), so nothing that used to work stops working.
  (2) `$InstallerVersion` is now parsed before the resume decision and
  `ResumedPastPublish` requires the journal's `installer_version` to equal
  it; otherwise it says "probing as a new ship" and both probes run (the
  onboard reuse is gated on the same flag, so it rebuilds). In the
  409-then-bump case that means the companion probe stops the run, which is
  what HEAD did; the stale-installer path is gone. Documented in RELEASE.md.
  (3) The reuse now goes through `Test-OnboardReusable`: onboard.exe must be
  newer than the companion exe, every `onboarding\*.py` and
  `installer\windows_bootstrap.ps1` (the inputs build_editor_package.ps1's
  staleness check reads); any missing input means rebuild.
- Tests: `test_resume_after_the_publish_is_not_a_version_collision` now
  writes `installer_version` into the stubbed journal and checks
  `ResumedPastPublish` is really true;
  `::test_resume_after_an_installer_bump_probes_again[publish|current]`
  EXECUTES the step-0 block with a mismatched journal version;
  `::test_onboard_reuse_needs_an_exe_newer_than_every_input[4 cases]`
  EXECUTES `Test-OnboardReusable` against files with set mtimes;
  `::test_a_failed_step_2b_does_not_advance_the_journal_to_publish` (source
  order guard: the save sits inside the exit-code check). The old
  source-text test was changed to pin the new wiring, as the reviewer noted
  it proved nothing on its own.

## Owed round (2026-09-25)

### bug-ops-4 (from onboarding) - the macOS bash gate ran one named file
- Status: FIXED (the owed half; onboarding fixed the uninstaller itself).
- Verified as: HEAD `tools/run_all_tests.ps1` "installer/macos" row and `.github/workflows/ci.yml` step "installer -- macOS bootstrap site values (bash)" both ran `bash installer/tests/test_macos_site_values.sh` by name, so `test_macos_uninstall_profile.sh` gated nothing. All three `installer/tests/test_*.sh` pass in Git Bash today.
- Fix: `tools/run_all_tests.ps1` (installer/macos row) enumerates `installer\tests\test_*.sh` (sorted), runs every one even after a failure, reports the first non-zero exit, and FAILS when none are found. `.github/workflows/ci.yml`: the step (renamed "installer -- macOS bootstrap bash tests", `shell: bash`) loops over `installer/tests/test_*.sh` with the same three rules.
- Regression test: `tools/tests/test_bug_hunt_2026_09_24_w2_release-tools.py` - `::test_ci_step_names_no_single_bash_test`, `::test_ci_step_runs_every_bash_test_and_fails_on_any` and `::test_ci_step_with_no_bash_tests_is_a_failure` EXECUTE the ci.yml step's script (as GitHub's `bash -eo pipefail`) in a scratch tree; `::test_run_all_tests_names_no_single_bash_test`, `::test_run_all_tests_macos_row_runs_every_bash_test_and_fails_on_any`, `::test_run_all_tests_macos_row_passes_when_all_pass`, `::test_run_all_tests_macos_row_with_no_bash_tests_is_a_failure` EXECUTE the .ps1 row sliced out of run_all_tests.ps1 under powershell. 6 of the 7 fail against HEAD's two files (ran in a scratch copy); the seventh (empty dir fails) passes on HEAD by accident, since HEAD runs a missing file.
- Tests run: `cd tools; ..\dashboard\.venv\Scripts\python.exe -m pytest tests/test_bug_hunt_2026_09_24_w2_release-tools.py -q` -> 43 passed. The sliced row also run against the real repo: all three scripts ran, row PASS. ci.yml still parses as YAML; LF kept.
- Skew / deploy order: gate only, nothing ships.
- OWED: none. Note for the orchestrator: root `CLAUDE.md` "Running tests" still lists only `bash installer/tests/test_macos_site_values.sh`; it could say `for t in installer/tests/test_*.sh; do bash "$t"; done` (CLAUDE.md belongs to no builder group).

### ui-onboarding-11 (from onboarding) - test_macos_first_steps.sh gated nothing
- Status: FIXED by the same change (enumeration covers `test_macos_first_steps.sh`; the executed tests above prove every `test_*.sh` in the directory runs). `Test-FirstSetupSteps.ps1` needed nothing: the .ps1 row already enumerates.
- Tests run / skew: as above.
- OWED: none.
