# tests - test QUALITY across the tree, above all this afternoon's regression tests

Files read (with approximate coverage): all 15 `test_bug_hunt_2026_09_11_*.py`
files (100% of their test names, ~40% of their bodies read line by line),
`installer/tests/Test-BinDirLeftovers.ps1` (100%),
`server/tests/test_cards_snapshot.py` (run, headers read),
`git diff 40f931a..HEAD -- '*/tests/*'` in full for the DELETIONS from the
pre-existing suites (~175 lines), `tools/run_all_tests.ps1` (installer row),
`.github/workflows/ci.yml` (job/runner matrix, installer enumeration),
`onboarding/steps.py` `installer_on_forbidden_drive` at 40f931a and at HEAD,
`broll/web/app/routes_fleet.py` diff, `dashboard/tests/test_selection_api.py`,
`companion/tests/test_app.py` around 6900.

Method (the brief's mutation test, done for real, never inside the repo): each
component was copied to the scratchpad, `git diff 40f931a..HEAD -- <src>` was
applied in REVERSE there (tests left at HEAD), and the new test file was run
from the scratch copy with the component's venv interpreter and
`PYTHONPATH=<scratch>/src` (which wins over the editable-install `.pth` that
points back at the repo - verified by the tracebacks naming the scratch paths).
Every test that PASSED against the reverted source was then read to decide
whether it is a deliberate control ("... still ...") or a regression test that
proves nothing.

Tests run:
- HEAD, all new files: companion 151 passed; dashboard 91 passed; broll/web 10;
  music/web 25; ytdl/web 12; onboarding 20; tools 19; server (bug-hunt +
  test_cards_snapshot) 20; `Test-BinDirLeftovers.ps1` 8/8 PASS. Nothing was
  committed red.
- REVERTED source (scratch copies): companion 62 failed / 4 passed / 16 errors
  (comp_app fails at import), comp_ui 31 failed / 0 passed; dashboard 62 failed
  / 9 passed / 1 error; broll 9 failed / 1 passed; music 19 failed / 6 passed;
  ytdl 9 failed / 3 passed; server 9 failed / 0 passed and test_cards_snapshot
  11 failed / 0 passed; tools 14 failed / 5 passed; **onboarding 8 failed / 12
  passed** - the only file where a genuine regression test survives its own bug.
- `python -c` snippet under a simulated APFS volume group (below) proving the
  onboarding canary asserts a different function from the one the code called.

## Findings

### tests-1 - the install-onboard-1 regression test passes against the bug, on every runner it actually runs on
- Severity: high
- Confidence: CONFIRMED
- Where: `onboarding/tests/test_bug_hunt_2026_09_11_install_onboard.py:84`
  (`test_the_simulation_really_is_a_mount_boundary`) and `:95`
  (`test_the_home_folder_and_applications_are_fine`), against
  `onboarding/steps.py:3285` as it was at 40f931a (`mount = is_mount or
  _default_is_mount`, and `_default_is_mount` is `os.path.ismount`).
- What: the file's headline finding is that the old macOS guard refused the
  frozen wizard from Downloads/Desktop/Applications because
  `os.path.ismount("/Users")` is True on a volume-group Mac. The new tests
  drive the REAL guard with `os.stat`/`os.lstat` swapped for a firmlink
  simulation - which is the right idea - but the old code reached the mount
  table through `os.path.ismount`, and on the Windows dev box and the Windows
  CI job `os.path` is `ntpath`, whose `ismount` never looks at `st_dev` at all
  and answers False for every POSIX path. So the pre-fix guard returns False
  there, i.e. "not refused", and the regression test is green against the bug.
  The canary test written expressly to stop this (`"If this stops being true
  the rest of the file proves nothing"`) probes `posixpath.ismount("/Users")`,
  not `os.path.ismount`, so it is green too. And the onboarding suite is run
  only by the Windows CI job and `run_all_tests.ps1`: `.github/workflows/ci.yml`
  line 464-537 runs only the COMPANION suite on `macos-latest`. The test can
  therefore not fail anywhere.
- Failure scenario: someone reverts or re-breaks the darwin branch of
  `installer_on_forbidden_drive` (it is the kind of code a later "simplify the
  mount check" touches). Windows CI and the local gate stay green, and every
  Mac editor's frozen wizard is refused from Downloads, the Desktop and
  /Applications with nowhere left to copy it to - exactly the shipped bug the
  test was written for.
- Evidence: reverting only `onboarding/steps.py` in a scratch copy and running
  the file gives `8 failed, 12 passed`, and the 12 include
  `test_the_simulation_really_is_a_mount_boundary` and all three
  `test_the_home_folder_and_applications_are_fine[...]` cases. Snippet under
  the same simulation:
  `os.path is ntpath: True` / `posixpath.ismount(/Users) = True` /
  `os.path.ismount(/Users) = False` /
  `OLD guard verdict for a Desktop app: False`.
- Ledger: new (CR-248 claims install-onboard-1 fixed; the fix is real, the
  regression test is not)
- Suggested fix: assert the pre-fix mechanism through the callable the code
  used - have the canary assert `steps._default_is_mount("/Users") is True`
  under the simulation (and `pytest.skip` where it cannot be, saying so out
  loud rather than passing), or better, keep a one-line
  `_old_guard`-equivalent in the test and assert it refuses while the shipped
  one does not. Separately, add the onboarding suite to the macOS CI job: it is
  the only suite whose subject is macOS-only behaviour and the only one that
  never runs there.

### tests-2 - the new installer regression test is not in the local gate
- Severity: medium
- Confidence: CONFIRMED
- Where: `tools/run_all_tests.ps1:161-203` (the installer row), vs
  `installer/tests/Test-BinDirLeftovers.ps1` (new this afternoon)
- What: the installer row names its scripts one by one (`Test-DriveMapParser`,
  `-LicenceGate`, `-PrevRollback`, `-ConsoleUser`, `-SmbShareGone`,
  `-ForeignDriveMiss`, `-UninstallEntry`) and aggregates exactly those seven
  exit codes. `ls installer/tests/*.ps1` is now EIGHT files;
  `Test-BinDirLeftovers.ps1` is in none of them, so the gate the owner runs
  before a ship ("all 13 suites") never executes it. `.github/workflows/ci.yml`
  line 208 enumerates the directory and does run it, so the miss is invisible
  until someone trusts a local green.
- Failure scenario: `windows_uninstall.ps1`'s `Get-BinDirLeftovers` is renamed
  or its call dropped in a later change; `run_all_tests.ps1` reports
  `installer PASS`; the defect only surfaces on a PR run, or not at all for a
  hotfix shipped with `ship.cmd` from this rig.
- Evidence: `grep -n installer tools/run_all_tests.ps1` lists seven
  `powershell -File` invocations and the seven-element `$installerExit` array;
  `ls installer/tests/*.ps1` lists eight scripts. Run by hand the new script
  passes 8/8.
- Ledger: new (the same list in `CLAUDE.md` "Running tests" also still says
  SEVEN scripts - the comment that has "now been wrong twice" is wrong a third
  time)
- Suggested fix: replace the hand-listed block with the same
  `Get-ChildItem installer/tests/*.ps1` enumeration CI already uses, so the row
  can never drift again, and update the `CLAUDE.md` note to point at the
  enumeration rather than a count.

### tests-3 - two assertions in the older suites are neutered with `or True`, one of them an authorization check
- Severity: low
- Confidence: CONFIRMED
- Where: `dashboard/tests/test_selection_api.py:75`
  (`assert client.get("/api/v1/selection/jsmith").status_code == 401 or True
  # other cannot read either`), `companion/tests/test_app.py:6914`
  (`assert "-" not in blocked["detail"].replace("CCSync", "") or True`)
- What: both assertions are unconditionally true. The dashboard one sits in
  `test_auth_matrix` and is the only line asserting that a signed-in editor
  cannot READ another editor's sync plan; it can never fail, so that row of the
  matrix is decorative. The companion one was meant as an em-dash check, tests
  a plain hyphen, and is saved only by the real `—` assert on the next
  line.
- Failure scenario: `/api/v1/selection/<other>` is later widened (the
  person-vs-machine work touched this area repeatedly) and the auth matrix
  stays green.
- Evidence: replacing the dashboard line with a real assert in a scratch copy
  of `dashboard/tests` (source read from the repo) still passes - the gate is
  correct TODAY (401), so this is a hole, not a live bug:
  `pytest tests/test_selection_api.py::test_auth_matrix -q` -> `1 passed`.
- Ledger: new
- Suggested fix: drop the `or True` from both; the dashboard one is already
  true as written, and the companion one should just be deleted (the `—`
  assert beside it is the real check).

### tests-4 - a regression test that skips itself when the thing it guards appears
- Severity: low
- Confidence: CONFIRMED
- Where: `music/web/tests/test_bug_hunt_2026_09_11_music.py:305-315`
  (`test_the_force_docstring_describes_what_actually_settles_a_batch`)
- What: the test greps the package for a production `apply_for_track(...,
  force=True)` caller and `pytest.skip()`s if one exists. music-4's point was
  that the docstring names a caller that does not exist; if a caller is added
  later the docstring becomes true and the test should be DELETED with the
  finding, not silently skipped - a skip in a suite of 25 is invisible, and the
  file then contains a test that never runs again.
- Failure scenario: a future `force=True` caller lands; the test skips for the
  rest of the repo's life and nobody revisits the docstring it was guarding.
- Evidence: read; `pytest -q` reports `25 passed` with no skip today.
- Ledger: new
- Suggested fix: make the caller case an explicit assertion about what the
  docstring must then say, or drop the test and keep the docstring fix.

### tests-5 - a large share of the new regression tests fail on the old code only because a new helper is missing
- Severity: low
- Confidence: CONFIRMED
- Where: whole-file examples: `server/tests/test_cards_snapshot.py` (11/11
  failures on reverted source are `AttributeError: module
  'install_dashboard_app' has no attribute 'write_cards_deploy_record'` and
  siblings), `server/tests/test_bug_hunt_2026_09_11_server_tools.py` (9/9,
  `... no attribute 'snapshot_propagation_note'`), large parts of
  `companion/tests/test_bug_hunt_2026_09_11_comp_ui.py`
  (`tray._persist_failed_line`) and of `..._comp_app.py` (the whole module
  fails to IMPORT on the old source: `cannot import name
  LANE_WATCHDOG_BACKOFF_SECONDS`).
- What: these tests do fail without the fix, so they satisfy the letter of the
  rule, but they fail because the symbol is new, not because the old code
  produced a wrong result. They pin the new helper's unit behaviour rather than
  the hunter's end-to-end scenario, so a future change that keeps the helper
  and stops calling it (or calls it after the irreversible step) is invisible
  to them. `Test-BinDirLeftovers.ps1` is the clearest case: it extracts
  `Get-BinDirLeftovers` with the PS parser and tests it thoroughly, and checks
  the delete/unregister ORDER with a line-number regex over the script text -
  neither of which would notice the helper's result being computed and not
  reported. (It IS called today, `windows_uninstall.ps1:472`.)
- Failure scenario: `install_dashboard_app` keeps `write_cards_deploy_record`
  but a later refactor stops calling it on the success path; every one of the
  11 snapshot tests stays green and the deploy record silently stops being
  written.
- Evidence: the reverted-source runs above; failure texts quoted.
- Ledger: new (a characteristic of the fix pass, not of one builder)
- Suggested fix: for the handful that matter (the Cards snapshot deploy record,
  the uninstaller's leftover report, the tray's persist-failed line) add one
  test each that drives the PUBLIC entry point and asserts the observable
  outcome, so the assertion survives the helper being bypassed.

## Coverage note

What this hunt DID establish, with the mutation test rather than by reading:
every one of the 15 new pytest files except the onboarding one contains at
least one test that fails against the pre-fix source, and every test that
passed against it was read and is a deliberate control (`... still ...`,
`... is untouched ...`, `... keeps today's behaviour ...`) - 4 in companion,
9 in dashboard, 1 in broll, 6 in music, 3 in ytdl, 5 in tools. No new test file
is wholly inert, and none was committed red.

What I did NOT get to: (a) reading every body in the ~7,300 new lines - I read
roughly 40%, concentrated on the ones whose names promised a scenario and on
every test that passed against the reverted source; (b) judging finding-by-
finding whether each test matches the hunter's described scenario (that is the
`regression` lens's sweep, and it needs the 131 findings side by side);
(c) the pre-existing suites beyond the diff, the deletions, and the
cannot-fail-assertion grep - there are ~13,000 lines of older tests I only
sampled; (d) the macOS runner beyond the `ctypes.get_last_error` case already
fixed in 06e6574 - I grepped the new companion tests for `windll`, `winreg`,
`startfile`, `WinError` and found none, but only a real macOS run proves it;
(e) the bash and PowerShell suites other than the two named in my brief.

What the suite structurally does not cover: the onboarding suite's macOS
branch runs on no macOS runner at all (tests-1); the installer row of the local
gate is hand-listed (tests-2); and nothing anywhere asserts that a test file
added by a fix pass is actually reached by `run_all_tests.ps1` - CI enumerates
directories, the local gate does not.

## OUT OF TERRITORY
- `CLAUDE.md` "Running tests": the installer row still says SEVEN scripts and
  names them; there are eight since this afternoon (see tests-2).
- `dashboard/tests/test_bug_hunt_2026_09_11_dash_api_jobs.py:401`: the
  docstring calls the last shipped build's schema "0.7.34, v50" while the
  hunt brief calls 0.7.34 v47; the test itself is sound (it builds v50 by
  slicing `_MIGRATION_STEPS`, then migrates twice), only the comment disagrees
  with the brief about which build sits at which version.
