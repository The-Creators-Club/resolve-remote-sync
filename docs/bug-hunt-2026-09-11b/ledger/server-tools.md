## The deploy script and the release tooling (CR-264, 2026-09-11)

Nine findings from the 2026-09-11b hunt, all of them about the SAME DAY's
work: the Timeline Cards snapshot deploy, the docs-disclosure fix and the
-EmitKindExtras gate. The shape they share is a fix that removed one failure
and left the opposite one invisible.

### CR-264a (server-tools-b-1) - the cards snapshot shipped a commit and never said the checkout was dirty - FIXED (server/install_dashboard_app.py, tools/check_deploy_drift.ps1, tools/ship_gates.ps1)

Until 2026-09-11 `[timeline_cards] src` shipped the operator's WORKING COPY,
and the snapshot change made "half-finished edits cannot reach the NAS" true
by construction. In doing so it inverted the failure: FINISHED edits that were
never committed do not reach it either, and nothing anywhere compared the two.
`git status --porcelain` was never run, and `cards_head_moved_on` compares the
shipped commit against the ref's head - which are equal PRECISELY when the
work is uncommitted. So an evening's Cards wave (both the 2026-09-10 and
2026-09-11 waves are recorded as uncommitted) deployed, printed
`Timeline Cards snapshot: <sha> (main)` with no qualifier, and
`check_deploy_drift.ps1` then said `OK ... which is still its head` about a
page that had not changed. Every channel said success.

`cards_dirty_files()` now asks git what is modified, staged or untracked under
the subtree; `export_cards_snapshot` prints a NOTE naming the count and the
first files ("are therefore NOT in this deploy ... commit them first if they
were meant to ship") whenever the export is the CHECKED-OUT commit - a deploy
pinned with `--cards-commit` is a deliberate act and says nothing. The count
travels in `info`, in `DEPLOYED_COMMIT` on the NAS (`dirty_at_export=`) and in
the local record, and the drift doctor re-reads the live checkout: a clean
head is `OK ... and that checkout is clean`, a dirty one is DRIFT naming how
many files are not on the NAS.

### CR-264b (server-tools-b-2) - the two rollout blocks bucket a NULL platform differently, so the ship gate refused on a phantom - FIXED on the gate side (tools/ship_gates.ps1)

`machine_state.platform` is nullable (SCHEMA_V8 added it as a bare ALTER
TABLE, and `record_report` keeps a NULL with COALESCE). `db.rollout_status`
counts such a row as `windows`; the `_rollout_platforms_block` added on
2026-09-11 reports the same row as `unknown`. `Get-KindExtrasVerdict` then
found a platform with computers that no channel covers and refused
`-EmitKindExtras` for ever: "1 unknown computer(s) have no current build on
this dashboard, so their versions were never checked against 0.9.55" - a
platform that does not exist, about a machine that WAS checked inside the
windows channel, with no command anywhere that could clear it.

`Get-RolloutPlatformName` now gives one spelling to the platform NAMES on the
counting side (blank or `unknown` -> `windows`, the fallback the counting side
has always used), so a NULL row cannot be a straggler of its own. The honest
fix is on the dashboard, where one health body would stop naming two platforms
for one row; it is recorded as OWED below, and this gate is safe without it.

### CR-264c (server-tools-b-3) - an explicit --cards-src-dir deploy left the previous snapshot's record standing - FIXED (server/install_dashboard_app.py, tools/ship_gates.ps1, tools/check_deploy_drift.ps1)

`~/.ccsync/state/cards_deployed.json` was written only when a commit snapshot
shipped. The documented escape hatch (`--cards-src-dir`, `CARDS_SRC`) ships a
working directory and produces no `info`, so the LAST snapshot's record
survived untouched and the doctor - which has no NAS shell and reads nothing
else - printed `OK /cards was shipped from main at <old sha>, which is still
its head` about a tree that is nobody's commit. That is wave 4's own rule
("an unverified check is NOT CHECKED, never OK") broken by the new code.

`record_cards_deploy()` is now the ONE writer for every shape of cards deploy:
a snapshot records the commit, the override records `commit=""` plus the
directory it shipped, and a dry run records nothing. The doctor prints
`? /cards was last shipped as the DIRECTORY <path>, not a commit ... NOT
CHECKED, not OK` for the second. An absent commit can no longer be read as an
old commit.

### CR-264d (tests-2) - the eighth installer table test was in no local gate - FIXED (tools/run_all_tests.ps1)

The installer row named its scripts one by one and aggregated exactly seven
exit codes. `installer/tests` has held eight since the 2026-09-11 fix pass
added `Test-BinDirLeftovers.ps1`, so the gate the owner runs before a ship
never executed it: the uninstaller's leftover report was guarded only on a PR
run, and not at all for a hotfix shipped with `ship.cmd` from this rig. The
row now enumerates `installer\tests\Test-*.ps1` the way
`.github/workflows/ci.yml` always has, prints each script's name as it runs,
keeps the first non-zero exit for the one "installer" summary row, and FAILS
if the directory is empty or missing. The comment in `CLAUDE.md` that says
SEVEN and names them is now wrong a third time; it is OWED below.

### CR-264e (server-tools-b-4) - the drift doctor asked every site about a feature most do not have - FIXED (tools/check_deploy_drift.ps1, tools/ship_gates.ps1)

The TIMELINE CARDS section was unconditional, so every customer who did not
buy Cards - and any base rig that has never run the deploy - got a permanent
`? no cards deploy record ... NOT CHECKED, not OK` pointing at an internal
runbook. The expensive outcome is not the chase, it is learning to ignore the
doctor's `?` lines, which is how three other real checks report. The section
is now skipped entirely when the site manifest names no `[timeline_cards]`
src or enabled, there is no record and `CCSYNC_CARDS_RECORD` is unset.

### CR-264f (server-tools-b-5) - the docs staging could still raise out of a function documented never to - FIXED (server/install_dashboard_app.py)

`published_docs_module()` swallows every LOAD failure and documents None as
"ship the required set", but the two attribute reads that follow were outside
that guard: a module that imports cleanly and no longer defines
`PUBLISHED_DOCS`/`PUBLISHED_TREES` raised `AttributeError` straight out of
`_stage_docs_tree`. `ship_dashboard_docs`'s `try/finally` only removed the
temp dir, so it escaped to `main()` at step 2a - AFTER the code swap - and
skipped the container restart the swap requires, leaving the running container
on the old inode with a traceback instead of the documented NOTE. The reads
are `getattr(..., ())` now and the staging call is wrapped: a NOTE and False,
as the docstring always promised.

### CR-264g (server-tools-b-6) - a failed path comparison turned a subtree export into a whole-repo export - FIXED (server/install_dashboard_app.py)

`cards_repo_for` swallowed `ValueError`/`OSError` from `relative_to` and
returned an empty prefix, which is the value that means "this checkout IS the
repository": `export_cards_snapshot` then skipped the subtree check and
archived the ENTIRE repo. A `src` reached through a subst drive, a junction or
a UNC spelling that `git rev-parse --show-toplevel` does not resolve to the
same object would ship hundreds of MB of the wrong tree, fail the
`handler.py` check, and tell the operator the package was "missing AT THAT
COMMIT" - sending them to look at the wrong repository state. The two cases
are told apart now: only a src that resolves to the root itself gets the empty
prefix (and it is the empty string, not the `"."` the old code produced), and
a comparison that fails is a whole-sentence refusal naming both paths.

### CR-264h (server-tools-b-7) - ro,rslave reaches TrueNAS's middleware, and nothing offline can say it is accepted - MITIGATED (server/install_dashboard_app.py)

The 2026-09-11 fix changed the snapshot bind from `host:/snapshots:ro` to
`host:/snapshots:ro,rslave`. Unlike a `docker run -v`, this dict is POSTed to
the TrueNAS middleware, which VALIDATES the volume spec before creating or
updating the app; whether it accepts a propagation flag in the third field is
not verifiable from this repo and was never verified live. It cannot be
proved offline, so what it gets is a way through it at the NAS's keyboard:
`CCSYNC_SNAPSHOT_RSLAVE=0` ships the plain `:ro` bind this deploy used before
that date, and a refused create/update prints `snapshot_refusal_hint()` -
two lines saying the flag is new, that the middleware validates it, and how
to re-run without it. Nothing is retried automatically: a deploy POST is not
a thing to repeat on a guess.

### CR-264i (tests-5) - a new helper's unit test is not the hunter's scenario - PARTLY FIXED (server/tests/test_bug_hunt_2026_09_11b_server_tools.py)

A large share of the 2026-09-11 tests fail on the old code only because the
symbol is new, so a later change that KEEPS the helper and stops calling it
(or calls it after the irreversible step) is invisible to them. The cards
deploy record is the one in this territory: eleven tests drive
`write_cards_deploy_record` and nothing asserted the deploy calls it. The
record now has one writer, `record_cards_deploy`, and a test asserts `main()`
goes through it and no longer carries the old call. The other two cases the
lens names (the uninstaller's leftover report, the tray's persist-failed line)
are other territories and are OWED below.

### Verification
- server/tests/test_bug_hunt_2026_09_11b_server_tools.py::test_a_dirty_checkout_is_named_loudly_by_the_export -> fails at f1eeb42 (KeyError: dirty_at_export), passes now
- server/tests/test_bug_hunt_2026_09_11b_server_tools.py::test_a_clean_checkout_says_nothing -> fails at f1eeb42, passes now
- tools/tests/test_bug_hunt_2026_09_11b_server_tools.py::TestTheCardsVerdict::test_an_uncommitted_checkout_is_not_ok -> fails at f1eeb42 (no Get-CardsDeployVerdict; the doctor printed OK), passes now
- tools/tests/test_bug_hunt_2026_09_11b_server_tools.py::TestTheTwoRolloutBlocksAgreeOnANullPlatform::test_an_unknown_bucket_is_not_a_phantom_straggler -> fails at f1eeb42, passes now
- server/tests/test_bug_hunt_2026_09_11b_server_tools.py::test_an_explicit_directory_deploy_invalidates_the_previous_record -> fails at f1eeb42, passes now
- server/tests/test_bug_hunt_2026_09_11b_server_tools.py::test_a_dry_run_records_nothing -> fails at f1eeb42, passes now
- tools/tests/test_bug_hunt_2026_09_11b_server_tools.py::TestTheCardsVerdict::test_a_directory_override_is_not_checked -> fails at f1eeb42, passes now
- tools/tests/test_bug_hunt_2026_09_11b_server_tools.py::test_the_installer_row_enumerates_its_directory -> fails at f1eeb42, passes now
- tools/tests/test_bug_hunt_2026_09_11b_server_tools.py::TestTheCardsVerdict::test_a_site_without_timeline_cards_is_not_asked -> fails at f1eeb42, passes now
- server/tests/test_bug_hunt_2026_09_11b_server_tools.py::test_a_published_docs_module_without_the_constants_is_not_a_traceback -> fails at f1eeb42 (AttributeError), passes now
- server/tests/test_bug_hunt_2026_09_11b_server_tools.py::test_a_raising_staging_is_a_note_and_false -> fails at f1eeb42, passes now
- server/tests/test_bug_hunt_2026_09_11b_server_tools.py::test_a_src_that_does_not_sit_under_its_repo_root_is_refused -> fails at f1eeb42, passes now
- server/tests/test_bug_hunt_2026_09_11b_server_tools.py::test_the_propagation_flag_has_an_off_switch -> fails at f1eeb42, passes now
- server/tests/test_bug_hunt_2026_09_11b_server_tools.py::test_a_refused_deploy_names_the_off_switch -> fails at f1eeb42, passes now
- server/tests/test_bug_hunt_2026_09_11b_server_tools.py::test_the_deploy_writes_the_record_through_that_one_helper -> fails at f1eeb42, passes now
- Also run green, unchanged in meaning: server/tests/test_cards_snapshot.py, server/tests/test_snapshot_mount.py, server/tests/test_bug_hunt_2026_09_11_server_tools.py, tools/tests/test_bug_hunt_2026_09_11_server_tools.py, tools/tests/test_release_scripts.py (two assertions in the last now read the doctor's wording out of ship_gates.ps1, where the decision moved).

### OWED TO ANOTHER TERRITORY
- dash-api: dashboard/src/ccsync_dashboard/api.py: `_rollout_platforms_block`: bucket a NULL/blank `machine_state.platform` the way `db.rollout_status` does (`COALESCE(platform,'windows')`, lower-cased) instead of `unknown`, so the two blocks of one /health body cannot name different platforms for the same row. Dashboard deploys first; the gate is already safe without it (CR-264b), and this removes the phantom at the source. Related to dash-api-5, already assigned there.
- install-onboard: installer/tests/Test-BinDirLeftovers.ps1: add one case that drives the uninstaller's public path and asserts the leftover report is REPORTED, not merely computed (tests-5). No deploy ordering.
- comp-ui: companion/tests/...: the same for `tray._persist_failed_line` - a test through the public entry point, so the helper being bypassed is visible (tests-5). No deploy ordering.
- orchestrator (repo root, no territory): CLAUDE.md "Running tests": the installer row still says SEVEN scripts and names them. `tools\run_all_tests.ps1` enumerates `installer\tests\Test-*.ps1` now, so the comment should point at the enumeration rather than a count (`ls installer/tests/*.ps1` is still the list).

### Owner decisions
- server-tools-b-7: I did NOT add an automatic retry that drops `rslave` and re-POSTs. A refused create/update is a step to understand, not one to repeat on a guess, so what shipped is an off switch (`CCSYNC_SNAPSHOT_RSLAVE=0`) and two lines of advice printed on a failed deploy. If you would rather the deploy fell back by itself on a refusal whose message names the volume, say so - it is a small change on top.
- The dirty-checkout NOTE is advisory and never fails the deploy: shipping the last commit while you hold uncommitted work is a legitimate thing to do, and a deploy that refused it would be one more thing to override on a Cards evening. It is the doctor's OK line that was changed to DRIFT, because that is the line that told you nothing was owed.
- `Get-RolloutPlatformName` maps a blank/`unknown` platform to `windows` rather than treating it as covered by any channel: a Mac-only fleet with a NULL row would then be reported as an uncovered `windows` bucket, which is true and visible, instead of silently waved through.

### Hand-off wave

Three OWED lines routed here from wave 1 (`HANDOFFS.md`, `## server-tools`).
All three are vendor-side or CI-side: nothing in this section changes a byte
that reaches an editor's machine, and no deploy ordering applies.

#### CR-264j (dash-core-6) - the bind-mode deploy's required docs set was a stale copy of the policy - FIXED (server/install_dashboard_app.py)

`SHIPPED_DOCS` is a hand-written copy of `published_docs.REQUIRED_DOCS` -
server/ cannot import the dashboard package (its own venv; that is why
`published_docs_module()` loads by path), so the two lists cannot be one
object. dash-core promoted `EDITOR_SETUP.md` to REQUIRED on the image and
bundler side, because the Dockerfile's `COPY docs/HOW_IT_WORKS.md
docs/EDITOR_SETUP.md` fails the build when the file is absent. This list still
said `("HOW_IT_WORKS.md",)`, so the one deploy path that is neither the image
nor an OTA bundle would have shipped a thinner /help and printed nothing: the
same "an unverified check is not OK" direction wave 4 exists to close. The
required set is now both documents, and the test reads `REQUIRED_DOCS` out of
`published_docs.py` rather than restating it, so the next promotion fails here
by name instead of drifting.

#### CR-264k (install-onboard-1, second half) - the only macOS-only suite ran on no Mac - FIXED (.github/workflows/ci.yml)

The `macos` job ran the companion suite and the release dry run. The
onboarding suite - whose subject IS macOS-only behaviour: the firmlink home
guard, `macos_bootstrap.sh`'s argv, the launchd labels - ran only on the
Windows runners, where `os.path` is `ntpath` and `ntpath.ismount` never reads
a mount table, so the tests that matter most there SKIPPED everywhere in the
world. One of them says exactly that in its own skip reason. The job now
installs `onboarding/requirements.lock` with `--require-hashes` into
`onboarding/.venv` (`bin/python`, not `Scripts/`) and runs the suite from the
component directory, writing `junit-onboarding-macos.xml` so it cannot collide
with the Windows job's `junit-onboarding.xml` in the artefact namespace. The
lock is added to that job's pip cache key.

#### CR-264l (dash-release-jobs, the cause behind CR-260d) - a manifest could put an unclaimable platform into a SIGNED record - FIXED (tools/publish_feed.py)

`parse_args` guards `--platform` with `choices=sign_release.PLATFORMS`, and
`_apply_manifest` then assigns `args.platform` from the manifest AFTER argparse
has run - the one path into the value that no guard covers. The platform is
matched EXACTLY by every reader (the companion's channel pick, the feed's
`current` key, the per-platform artefact directory), so a manifest saying
`Windows`, `darwin` or `osx` produced a record that is published, verifiable,
signed and offered to no machine on earth: the shape CR-260d's rejection was
about. The manifest value is now folded to lower case where it enters, and one
that is still not a platform is a refusal (`EXIT_CONDEMNED`) naming the value
and the three canonical spellings, before anything is signed. `--platform`
passed explicitly is unchanged.

### Verification (hand-off wave)
- server/tests/test_bug_hunt_2026_09_11b_server_tools.py::test_the_required_docs_set_matches_the_dashboard_policy -> fails with SHIPPED_DOCS reverted to ("HOW_IT_WORKS.md",), passes now
- server/tests/test_bug_hunt_2026_09_11b_server_tools.py::test_a_missing_editor_setup_refuses_the_docs_ship -> fails with SHIPPED_DOCS reverted, passes now
- tools/tests/test_bug_hunt_2026_09_11b_server_tools.py::test_the_macos_job_runs_the_onboarding_suite -> fails at f1eeb42, passes now
- tools/tests/test_bug_hunt_2026_09_11b_server_tools.py::test_the_two_onboarding_junit_files_do_not_collide -> fails at f1eeb42, passes now
- tools/tests/test_bug_hunt_2026_09_11b_server_tools.py::test_a_manifest_platform_is_folded_and_re_validated -> fails at f1eeb42 (args.platform == "Windows", no refusal), passes now
- Also run green: server/tests/test_bug_hunt_2026_09_11b_server_tools.py (14), server/tests/test_image_mode.py (40, the two docs-staging cases), tools/tests/test_bug_hunt_2026_09_11b_server_tools.py (14), tools/tests/test_publish_feed.py, tools/tests/test_publish_latest.py.
- `test_a_raising_staging_is_a_note_and_false` (wave 1) now builds its fixture from `SHIPPED_DOCS` instead of naming HOW_IT_WORKS.md: with two required documents it was refusing at the missing-file check and never reaching the staging it is about.
- ci.yml parses as YAML and the macos job's step list reads: companion install, rclone, companion pytest, licence gate, onboarding install, onboarding pytest, release dry run, upload junit.

### OWED TO ANOTHER TERRITORY (hand-off wave)
- none. The three routed lines are done.

### Owner decisions (hand-off wave)
- The onboarding suite has never executed on a Mac, so its first green run is the CI run after this lands. It already carries `sys.platform != "win32"` skipifs written in anticipation (`test_cleanup_steps.py` even names a darwin runner), so the expectation is a clean run with the firmlink tests finally EXECUTING rather than skipping - but if that job comes back red, it is new information about the suite, not about the wizard, and the step can be dropped again in one edit.
- A non-canonical manifest platform is a refusal, not a fold-and-warn: publishing is the irreversible half (the record is signed), and a manifest whose platform is not one of three spellings is a broken builder, which is a thing to look at rather than to guess about.
