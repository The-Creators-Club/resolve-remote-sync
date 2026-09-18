# install-onboard - installer/* (ps1, sh, tests) and onboarding/*

Files read (with approximate coverage):
- `installer/windows_uninstall.ps1` (100%), `installer/drive_mapping.ps1` (100%),
  `installer/macos_uninstall.sh` (60%, sections 1-4 and the closing verdict in full),
  `installer/windows_bootstrap.ps1` (30%: the site-manifest block 640-790, the
  Apps & features entry 860-970, the BinDir copies, the config.toml write),
  `installer/windows_upgrade.ps1` (25%: version record, rollback, EULA gate),
  `installer/macos_bootstrap.sh` (20%: the tree-name / canonical-prefix block and
  the legacy-LaunchAgent + COMPANION_MISSING blocks),
  `installer/build_editor_package.ps1` (10%, version-parity checks only).
- `installer/tests/*.ps1` (all eight run; `Test-BinDirLeftovers.ps1` and
  `test_macos_site_values.sh` read closely).
- `onboarding/steps.py` (40%: `site_manifest_value`, `_same_dashboard`,
  `normalise_dashboard_url`, `run_bootstrap`, the breadcrumb helpers,
  `build_cleanup_plan`), `onboarding/onboard.py` (10%, role plumbing),
  `onboarding/tests/test_bug_hunt_2026_09_11b_install_onboard.py` (100%),
  `onboarding/build_onboard_macos.spec` (version marker).
- Diffs `34a3c8f..HEAD` and `18e69f3..34a3c8f` for the whole territory, hunk by hunk.

Tests run:
- `cd onboarding; python -m pytest tests -q` -> 428 passed, 1 skipped.
- every `installer\tests\Test-*.ps1` via `powershell -NoProfile -ExecutionPolicy Bypass -File`
  -> all eight exit 0.
- `bash installer/tests/test_macos_site_values.sh` -> (read; the shell harness in
  the repo passes, see finding install-onboard-3 for what it does not reach).
- scratch repro of `macos_uninstall.sh` section 3 + `closing_verdict` in the
  scratchpad (see install-onboard-1).

## Findings

### install-onboard-1 - a macOS `--dry-run` uninstall now ends "CCSync uninstall NOT complete"
- Severity: medium
- Confidence: CONFIRMED
- Where: `installer/macos_uninstall.sh:217-219` (the `[ -d "$BIN_DIR" ]` block) with
  `installer/macos_uninstall.sh:299-309` (`closing_verdict`)
- What: the install-onboard-3 fix (09-11b) made the closing line conditional on
  `REMOVAL_INCOMPLETE`, but the pre-existing "`$BIN_DIR` still exists" block sets
  `REMOVAL_INCOMPLETE=1` unconditionally and is not gated on `DRY_RUN`. In a dry run
  nothing is deleted, so `$BIN_DIR` is of course still there, so the flag is set and
  the run ends with a red warning instead of the "(dry run -- nothing changed)"
  sentence the dry-run mode exists to print.
- Failure scenario: a Mac editor is told to check what the uninstaller would do and
  runs `bash macos_uninstall.sh --dry-run` on a healthy install. Output:
  `DRY: would delete ~/.local/ccsync` ... `WARN: CCSync uninstall NOT complete: some
  of ~/.local/ccsync is still on this Mac (see the WARNING above). Remove it by hand,
  or run this script again, before reinstalling.` They either hand-`rm -rf` a tree the
  dry run never touched, or they conclude the uninstaller is broken. The dry run also
  loses its only "nothing changed" reassurance.
- Evidence: scratch reproduction of the exact three blocks (scratchpad `sim.sh`,
  `DRY_RUN=1`, a populated `.../ccsync/bin`) printed
  `WARN: CCSync uninstall NOT complete: ...` and no "(dry run -- nothing changed)".
  `git diff 18e69f3..34a3c8f -- installer/macos_uninstall.sh` shows `REMOVAL_INCOMPLETE=1`
  added to that block in the same commit as `closing_verdict`.
- Ledger: regression of CR-265 / install-onboard-3 (2026-09-11b) - the fix introduced it.
- Suggested fix: guard the block with `[ "$DRY_RUN" = 1 ] || { REMOVAL_INCOMPLETE=1; warn ...; }`,
  or pass `0` to `closing_verdict` whenever `DRY_RUN=1`.

### install-onboard-2 - `-Full` on Windows says "removed" and "your identity is gone" without looking
- Severity: medium
- Confidence: CONFIRMED
- Where: `installer/windows_uninstall.ps1:620-627` (the `-Full` removal of
  `$CcsyncLocal`) and `:658` (the unconditional identity warning), against
  `:533-552` (the bin-dir path, which does look)
- What: install-onboard-3 (2026-09-11) taught section 4 to re-read `$BinDir` after
  `Remove-Item` because PS 5.1's `Remove-Item -Recurse` deletes NOTHING when one child
  is locked. Section 5's `-Full` removal of the whole of `%LOCALAPPDATA%\ccsync` - which
  contains that same bin dir plus `syncthing-config`, the device identity - was not
  given the same treatment: `Remove-Item ... -ErrorAction SilentlyContinue` is followed
  unconditionally by `Write-Step "removed $CcsyncLocal"`, and by
  `Write-Warn2 "FULL uninstall: your saved sign-in and Syncthing device identity are gone.
  A reinstall generates a NEW device ID -- send it to the admin..."`. The closing verdict
  is computed from `$binLeftovers`, which was measured before section 5 ran and says
  nothing about `syncthing-config`.
- Failure scenario: an editor runs `-Full` while `syncthing.exe` is still holding a
  handle in `bin\` (the `Stop-Process` in section 1 is never waited on). Section 4
  warns about leftovers; section 5 then deletes nothing, prints "removed
  %LOCALAPPDATA%\ccsync" and the "your device identity is gone" paragraph. They
  reinstall, Syncthing comes up on the OLD device ID, and the admin is chasing a new
  device ID that will never appear on the dashboard's pending list - the same shape as
  the stuck-lane-C / regenerated-device-ID incident, pointing the other way.
- Evidence: read of the whole file; `$binLeftovers` is assigned only at `:538` and is
  the sole input to `Get-UninstallClosingAdvice` at `:683`. `Test-BinDirLeftovers.ps1`
  exercises `Get-BinDirLeftovers` and `Get-UninstallClosingAdvice` and never enters the
  `-Full` path at all.
- Ledger: "CR-265 / install-onboard-3 does not fix the `-Full` path" (its Windows half
  fixed section 4 only; the Mac half was fixed on 09-11b, also for the tree, not for
  this claim).
- Suggested fix: re-`Test-Path` `$CcsyncLocal` (and `$SyncthingHome`) after the
  `-Full` delete; report "removed" only when it is gone, and downgrade the "your
  device identity is gone / expect a new device ID" paragraph to a warning that names
  what is still on disk when it is not.

### install-onboard-3 - the macOS uninstall test pins the verdict function, not the code path that sets its argument
- Severity: low
- Confidence: CONFIRMED
- Where: `installer/tests/test_macos_site_values.sh:396-417`
- What: the closing-verdict test extracts `closing_verdict` with `VERDICT_SRC`, forces
  `DRY_RUN=0`, and calls `closing_verdict 0` / `closing_verdict 1` directly. It never
  executes the section-3 block that actually computes `REMOVAL_INCOMPLETE`, so the one
  thing the 09-11b fix changed about the script's flow - which of the two branches a
  real run reaches - is untested, and install-onboard-1 above passes the suite.
- Failure scenario: any future change to the `REMOVAL_INCOMPLETE` bookkeeping is green
  in CI; the dry-run regression already is.
- Evidence: `bash installer/tests/test_macos_site_values.sh` passes on the current
  tree, which contains install-onboard-1.
- Ledger: new.
- Suggested fix: add a case that sources section 3 wholesale (the `remove_local_tree`
  definition plus the two `if` blocks) with `DRY_RUN=1` over a populated fake
  `CCSYNC_LOCAL`, and asserts the output contains "(dry run" and not "NOT complete".

### install-onboard-4 - `_same_dashboard` compares hostnames only, so two deployments on one host share a cache
- Severity: low
- Confidence: CONFIRMED (mechanism); PLAUSIBLE that a fleet hits it
- Where: `onboarding/steps.py:245-262`
- What: the install-onboard-1 (09-11b) identity check reduces both URLs to
  `urlparse(...).hostname` and compares those. Port and scheme are dropped, so a host
  that fronts two dashboards (the common shape when a customer runs a staging and a
  production container on one NAS, `nas:8480` and `nas:8481`, or moves from the plain
  container port to a Funnel port) is judged "the same dashboard" and the cached
  `canonical_prefix` / `tree_name` of the other one are put on the bootstrap's argv,
  where they beat `windows_bootstrap.ps1`'s own `Get-SiteValue` fetch (it only fetches
  when the flag is empty, `windows_bootstrap.ps1:724,740`).
- Failure scenario: a machine previously onboarded to `nas.tailnet.ts.net:8480`
  (tree `Creators_Club`, `P:\`) is re-onboarded to `nas.tailnet.ts.net:8481`
  (tree `Pool`, `Q:\`) while the second dashboard is briefly unreachable. The wizard
  passes `-CanonicalPrefix P:\ -TreeName Creators_Club`; the bootstrap skips its own
  fetch and maps the wrong letter and folder name - exactly the failure the fix was
  written to stop, one level down.
- Evidence: read of `_same_dashboard`; `urlparse("https://h:8480").hostname == "h"`.
  `onboarding/tests/test_bug_hunt_2026_09_11b_install_onboard.py` only varies the host.
- Ledger: "CR-265 / install-onboard-1 does not fix the same-host case".
- Suggested fix: compare `(hostname, port-or-default-for-scheme)` and treat a proven
  port mismatch as a different deployment, keeping the "either side is blank -> allow"
  rule unchanged.

### install-onboard-5 - a macOS dry run claims, in the past tense, that the Syncthing identity was deleted
- Severity: low
- Confidence: CONFIRMED
- Where: `installer/macos_uninstall.sh:210-212`
- What: the `warn "that included the Syncthing identity in $SYNCTHING_HOME. A reinstall
  generates a NEW device ID, so the admin has to approve this Mac again..."` line sits
  inside `if [ -d "$CCSYNC_LOCAL" ]` and is gated only on `REMOVAL_INCOMPLETE = 0`, not
  on `DRY_RUN`. A dry run prints "would delete ..." and then this sentence, which is
  written as a statement of fact about a deletion that did not happen.
- Failure scenario: an editor dry-runs the uninstaller to see what it would do and
  mails the admin "my device ID has been reset, please re-approve me"; the admin
  removes and re-invites a device whose ID never changed.
- Evidence: the scratch reproduction in install-onboard-1 printed the `WARN: that
  included the Syncthing identity ...` line with `DRY_RUN=1`.
- Ledger: new (pre-dates the 09-11b fix but was moved into the new gate by it).
- Suggested fix: move the sentence into the non-dry-run success branch of
  `remove_local_tree`, or phrase it as "would also remove ..." under `DRY_RUN=1`.

## Coverage note

Not reached in the time box: `installer/build_editor_package.ps1` beyond its
version-parity block (the publish/`-MakeCurrent` path and the signature checks are
effectively dash-release-jobs' other end and deserve a read); the bulk of
`installer/windows_bootstrap.ps1` (Tailscale/rclone/Syncthing install steps, the
firewall rule, the loopback share creation, the config.toml heredoc) and of
`installer/macos_bootstrap.sh` (Homebrew handling, the Resolve Mapped Mount write,
the rclone stanza); `installer/windows_upgrade.ps1`'s rollback and stand-down logic;
`onboarding/onboard.py`'s Tk pages; the macOS-only branches of `steps.py`
(`build_cleanup_plan_macos`, `execute_cleanup`).

Suite gaps worth naming: nothing in the territory runs `macos_uninstall.sh` or
`windows_uninstall.ps1` end to end - both are tested by extracting single functions
with regex/AST, so any defect in the *flow between* those functions (both findings 1
and 2 above) is invisible to CI. There is no em-dash scan over
`installer/*.ps1`/`*.sh` as a whole; only four individual macOS functions and one
Windows message are checked (I scanned the whole territory by hand: clean). The
Windows `build_onboard.spec` carries no version resource, so the Windows `onboard.exe`
has no file version to compare against `INSTALLER_VERSION`, unlike the macOS bundle
(`test_macos_steps.py:770-774` checks three of the four places).

## OUT OF TERRITORY
- `companion/src/ccsync_companion/site.py:255-274`: `cached_site(max_age_seconds=...)`
  bounds on the file's mtime, so a `site.json` rewritten by any unrelated companion
  refresh keeps a stale deployment's values "fresh" for the wizard's 30-day window.
