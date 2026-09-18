# install-onboard - installer/* (ps1, sh, tests) and onboarding/*

Files read (with approximate coverage):
- `installer/windows_uninstall.ps1` (full read of the diff, ~90% of the script:
  sections 1-5 and both helper functions)
- `installer/macos_uninstall.sh` (full read of the diff, sections 2-5 and
  `closing_verdict`)
- `installer/tests/Test-BinDirLeftovers.ps1` (100%),
  `installer/tests/test_macos_site_values.sh` (the new case plus the
  uninstall half, ~60%)
- `onboarding/steps.py` (the diff plus `normalise_dashboard_url`,
  `site_manifest_value`, `site_tree_name`, `site_drive_letter`, ~35%)
- `onboarding/tests/test_bug_hunt_2026_09_18_webapps_tools.py` (100%)
- cross-checked: `companion/src/ccsync_companion/config.py` (log/token
  locations), `companion/src/ccsync_companion/supervisor.py` (`decide`),
  `dashboard/src/ccsync_dashboard/site_store.py` (`dashboard_url` origin)

Tests run:
- `bash installer/tests/test_macos_site_values.sh` -> all pass (the 4 new
  dry-run cases included)
- `powershell -NoProfile -ExecutionPolicy Bypass -File installer\tests\Test-BinDirLeftovers.ps1`
  -> all pass (the 6 new -Full cases included)
- ad-hoc: extracted `Get-UninstallClosingAdvice` to the scratchpad and called
  it directly (see install-onboard-1's evidence)

## Findings

### install-onboard-1 - the -Full leftovers verdict tells the editor to retry and, two lines later, to delete the retry path
- Severity: medium
- Confidence: CONFIRMED
- Where: `installer/windows_uninstall.ps1:271` and `installer/windows_uninstall.ps1:278-285`
- What: today's fix added a second "NOT complete" branch keyed on
  `$identityCount`, but the self-path paragraph below it is still keyed on
  `$LeftoverCount -gt 0` alone. On the new branch `$LeftoverCount` is 0, so
  the function falls into the "delete that file, and the folder it is in,
  whenever you like" arm. That is exactly the contradiction
  install-onboard-2 (2026-09-11b) created this function to remove, reopened
  for the new case.
- Failure scenario: a `-Full` run where section 4 cleared `bin\` but section
  5 could not clear `%LOCALAPPDATA%\ccsync` prints, in one paragraph:
  "CCSync uninstall NOT complete ... run this uninstaller again with -Full"
  and then "this uninstaller is still on disk at ...\bin\windows_uninstall.ps1
  (it was running). Delete that file, and the folder it is in, whenever you
  like." An editor who follows the second sentence destroys the only thing
  that could carry out the first, and deletes the folder the uninstaller just
  said it could not clear.
- Evidence: extracted the function to the scratchpad and dot-sourced it:
  `Get-UninstallClosingAdvice -LeftoverCount 0 -BinDir ...\bin -SelfPath
  ...\bin\windows_uninstall.ps1 -IdentityLeftovers @("...\bin")` ->
  warn "NOT complete: 1 item(s) ... run this uninstaller again with -Full",
  step "... Delete that file, and the folder it is in, whenever you like."
- Ledger: CR-286/install-onboard-2 (2026-09-18) does not fix its own
  neighbour; regression of the 2026-09-11b install-onboard-2 contract.
- Suggested fix: make the self-path arm test `($LeftoverCount -gt 0 -or
  $identityCount -gt 0)`, and word the LEAVE line so it covers both.

### install-onboard-2 - the Apps & features entry is removed before the -Full delete that may fail, then the new verdict says "run this uninstaller again"
- Severity: medium
- Confidence: CONFIRMED
- Where: `installer/windows_uninstall.ps1:597-607` (section 4's entry removal)
  vs `installer/windows_uninstall.ps1:663-691` and `:271`
- What: section 4 removes the Apps & features entry whenever
  `$binLeftovers.Count -eq 0`, which is now no longer the same thing as "the
  uninstall succeeded": section 5's `-Full` delete of the whole tree runs
  afterwards and can fail on its own. The new closing line then directs the
  editor to "run this uninstaller again with -Full" with the registered entry
  already gone and (normally) the script itself deleted with `bin\`.
- Failure scenario: `-Full` run, `bin\` clears, `syncthing-config\` is still
  held (Syncthing not yet exited - see install-onboard-5). Entry removed,
  script gone, closing verdict asks for a retry that has no launcher and no
  file. The editor's only route is a hand `rm -rf`, which the verdict does not
  give them (only the section 5 warning lists the paths, thirty lines
  earlier and above the banner).
- Evidence: control flow read end to end; section 4's `elseif
  (Unregister-UninstallEntry ...)` at line 602 executes unconditionally
  before `if ($Full)` at line 662. This is the same shape as
  install-onboard-3 (2026-09-11), whose own comment at line 561 says "an
  entry removed before a delete that did not happen is worse".
- Ledger: CR-286/install-onboard-2 does not fix install-onboard-3's
  invariant for the section it added.
- Suggested fix: move the entry removal below section 5, gated on
  `$binLeftovers.Count -eq 0 -and $fullLeftovers.Count -eq 0`; or have the
  identity branch print the hand-delete command.

### install-onboard-3 - section 5 reports "removed your sign-in and settings" from ~/.ccsync without looking, and the verdict never checks that tree
- Severity: medium
- Confidence: CONFIRMED
- Where: `installer/windows_uninstall.ps1:704-714` (`$doomed` loop and the
  unconditional `Write-Step`), and `:677` (`Get-FullRemovalLeftovers` is
  given `$CcsyncLocal` only)
- What: the whole point of today's install-onboard-2 was "LOOK, the way
  section 4 does" before claiming a delete happened. The block immediately
  below it still deletes every child of `%USERPROFILE%\.ccsync` with
  `-ErrorAction SilentlyContinue` and then prints "removed your sign-in and
  settings from $CcsyncProfile ($($doomed.Count) item(s))" computed from the
  list it *intended* to delete, never re-reading the directory. `$fullLeftovers`
  scans `%LOCALAPPDATA%\ccsync` only, so the closing verdict cannot catch it
  either: the run ends "CCSync uninstall complete".
- Failure scenario: `~/.ccsync` holds `companion.log`
  (`config.py:1039 log_path = "~/.ccsync/companion.log"`), held open by the
  companion that section 1 killed without waiting. `config.toml` (which holds
  `report_token`, the per-editor `cce1.` fleet credential, and
  `dashboard_token`) and `identity.json` are in the same directory; whichever
  of them the delete misses stays on the machine while the script reports
  them removed and the banner says complete. On a machine handed to another
  person, that is a live fleet credential the editor was told was gone.
- Evidence: `config.py:337/1039` puts the log in `~/.ccsync`;
  `config.py:358-364` puts `dashboard_token`/`report_token` in `config.toml`;
  section 1 (line 294-305) has no `Wait-Process`; the `Write-Step` at 713 is
  outside any leftovers test.
- Ledger: CR-286/install-onboard-2 does not fix the identical defect in the
  block below its own.
- Suggested fix: re-read `$CcsyncProfile` after the loop (ignoring `state`),
  fold the survivors into `$fullLeftovers`, and print "removed N, could not
  remove M" instead of the intended count.

### install-onboard-4 - any surviving file is reported as "your sign-in and Syncthing identity", and one run can say both that the identity is gone and that it is still there
- Severity: medium
- Confidence: CONFIRMED (wording and predicate divergence); PLAUSIBLE that
  the split-outcome state is common
- Where: `installer/windows_uninstall.ps1:271` vs `:727-733`
- What: the section 5 paragraph decides what to tell the editor about their
  device ID with `Test-Path $SyncthingHome`; the closing verdict decides with
  `Get-FullRemovalLeftovers`, which returns *every* surviving top-level child
  of `%LOCALAPPDATA%\ccsync` (`bin`, `Temp`, a stray log) and calls all of
  them "item(s) of your sign-in and Syncthing identity". The two predicates
  disagree whenever the delete is partial in the common direction.
- Failure scenario: `syncthing-config\` is deleted but `bin\` survives (it is
  the working directory of the powershell host Apps & features launched, and
  Windows will not delete a process's CWD). The run prints "FULL uninstall:
  your saved sign-in and Syncthing device identity are gone. A reinstall
  generates a NEW device ID - send it to the admin" and then "CCSync
  uninstall NOT complete: 1 item(s) of your sign-in and Syncthing identity
  are still on this machine". The editor cannot tell whether to ask for
  re-approval, which is precisely the admin-facing question this fix exists
  to settle (the stuck-lane-C device-ID incident).
- Evidence: the scratchpad call in install-onboard-1 produced that exact
  sentence for a leftover that is `...\ccsync\bin`; the two code paths use
  different inputs and are 460 lines apart.
- Ledger: new (opened by CR-286/install-onboard-2).
- Suggested fix: compute one verdict. Pass `Test-Path $SyncthingHome` into
  the closing advice as its own flag and word the leftovers line as "N
  item(s) of the CC Sync app folder", naming the identity only when
  `syncthing-config` is among them.

### install-onboard-5 - the fix names the root cause (Stop-Process is never waited on) and does not fix it; the supervisor can also outrun it
- Severity: medium
- Confidence: CONFIRMED (no wait exists); PLAUSIBLE (supervisor race)
- Where: `installer/windows_uninstall.ps1:294-315` (section 1), consumed by
  `:576` and `:666`
- What: the new comment at line 668 states the mechanism - "section 1's
  Stop-Process -Force is never waited on - so a syncthing.exe still holding
  a handle left the whole tree" - and the fix only reports the consequence.
  `Stop-Process -Force` is asynchronous; two lines of `Wait-Process -Timeout`
  plus a `Get-Process` re-check would turn most of these runs into successful
  uninstalls instead of "sign out and back in, then run this again". Second
  half: `supervisor.py` relaunches a companion that died without starting a
  shutdown, and a `Stop-Process` kill leaves the run marker in place, so the
  supervisor's `decide` returns relaunch. Its only stand-down guards are the
  marker and `exe_exists`, and the exe is not deleted until section 4 - a
  window of several seconds in which a relaunched companion re-takes
  `bin\ccsync-companion.exe` and re-creates `~/.ccsync/companion.log`.
- Failure scenario: an editor runs the uninstaller from Apps & features with
  the tray running. The companion is terminated, the supervisor relaunches it
  before its own termination lands, section 4's delete then fails on the live
  exe, and the uninstall ends "NOT complete" on a machine where nothing was
  actually wrong.
- Evidence: no `Wait-Process` anywhere in the script (`grep -n Wait-Process
  installer/windows_uninstall.ps1` is empty); `supervisor.py:126-150`
  (`decide`) stands down only on a missing/mismatched marker, a clean code or
  a missing exe.
- Ledger: related to CR-286/install-onboard-2 (it diagnoses this and stops
  short).
- Suggested fix: after the kills, `Wait-Process -Name ccsync-companion,
  syncthing -Timeout 10 -ErrorAction SilentlyContinue`, and delete
  `~/.ccsync/crash/running.marker` before the kill so the supervisor stands
  down by its own rule.

### install-onboard-6 - the Mac uninstaller destroys the Syncthing identity on every run; Windows keeps it and says "no re-approval needed"
- Severity: medium
- Confidence: CONFIRMED
- Where: `installer/macos_uninstall.sh:65` and `:204-219` vs
  `installer/windows_uninstall.ps1:662` and `:740-741`
- What: on macOS `SYNCTHING_HOME="$CCSYNC_LOCAL/syncthing-config"` sits
  inside the tree section 3 deletes unconditionally, so a plain
  `macos_uninstall.sh` (no `--full`) removes the device identity. Windows
  scopes its delete to `$BinDir` and only touches `syncthing-config` under
  `-Full`, printing "KEPT Syncthing identity ... reinstall reuses the same
  device ID - no re-approval needed". The same flag means opposite things on
  the two platforms, and the mode line on macOS says "mode: keep sign-in and
  settings".
- Failure scenario: a Mac editor reinstalls after a plain uninstall; the new
  Syncthing comes up on a new device ID that the admin must find on the
  pending list and approve before lane C works. The admin, going by the
  Windows behaviour and the mode line, does not expect to. That is the
  stuck-lane-C shape (`stuck-lane-c-device-id-regen`) reached by the
  supported path.
- Evidence: line numbers above; `remove_local_tree` is called with
  `$CCSYNC_LOCAL` outside any `FULL` test (line 205), while `if [ "$FULL" = 1 ]`
  starts only at line 263.
- Ledger: new (pre-existing; today's diff touches these exact lines without
  changing the scope).
- Suggested fix: on macOS, delete `bin/` unconditionally and
  `syncthing-config/` only under `--full`, matching Windows; or say in the
  mode line that the device identity always goes.

### install-onboard-7 - the new -Full tests assert only the "NOT complete" word, which is why install-onboard-1 and -4 are green
- Severity: low
- Confidence: CONFIRMED
- Where: `installer/tests/Test-BinDirLeftovers.ps1:232-266` and `:377-417`
- What: the new cases check that the verdict contains "NOT complete" and that
  the `-Full` block prints "could NOT remove all of", and nothing else. They
  never read the rest of the paragraph the same function returns (the
  self-path advice) and never exercise the section 5 identity paragraph at
  all, so both contradictions above ship green. The second block is also
  keyed on an AST match for `Get-FullRemovalLeftovers`, i.e. it can only ever
  test the new code, never prove the old code was wrong.
- Failure scenario: a reviewer runs the suite, sees 28 passes, and ships a
  closing paragraph that contradicts itself.
- Evidence: ran both suites, all pass, while the scratchpad call in
  install-onboard-1 shows the contradiction from the same function.
- Ledger: new.
- Suggested fix: assert the WHOLE paragraph on the identity path (no "delete
  that file" line), and add a case over the section 5 identity `if/elseif/else`
  statement the way the -Full delete block is driven.

### install-onboard-8 - `_same_dashboard`'s port rule refuses a dashboard reachable on two published ports
- Severity: low
- Confidence: CONFIRMED (behaviour); the consequence is a degrade, not a
  wrong value
- Where: `onboarding/steps.py:265-272` and `:275-289`
- What: the new rule treats two explicitly stated, different ports on the
  same host as two deployments. This deployment publishes the dashboard on
  more than one port on purpose: Tailscale Serve on 443, the client-share
  Funnel on 8443 (CLAUDE.md, client folders), and the container's own port
  (8480) on the tailnet. `dashboard_url` in the manifest is a free-text
  admin setting (`site_store.py:771`, `DASH_SITE_DASHBOARD_URL`), so a site
  whose manifest says `https://nas.ts.net:8443` while the editor types
  `https://nas.ts.net:8480` now reads as a mismatch. The docstring's claim
  that "only a PROVEN mismatch is False" is no longer accurate. In the other
  direction the guard is still open: the staging/production case it targets
  passes whenever either side omits the port, which is the common spelling.
- Failure scenario: `site_manifest_value` returns "", the wizard passes empty
  `-CanonicalPrefix`/`-TreeName` to the bootstrap, and the bootstrap does its
  own `Get-SiteValue` fetch - correct, but it is the fallback the cache path
  exists to avoid, and on a machine that cannot reach the dashboard at that
  moment it lands on the `P:` default on a `Q:` site.
- Evidence: read `normalise_dashboard_url` (line 988) - it preserves whatever
  port the text carries and never adds one - and `_url_port`, which returns
  the explicit port or 0.
- Ledger: new (opened by CR-286/install-onboard-4).
- Suggested fix: either compare on a stronger identity key (have the manifest
  carry a site id) or restrict the port test to ports that differ and are both
  non-default for their scheme; at minimum correct the docstring.

## Coverage note
Not covered: `installer/windows_bootstrap.ps1` and `macos_bootstrap.sh` (not
touched by today's diff, and large), the rest of `onboarding/` (`onboard.py`,
the wizard pages, `tests/` beyond the new file), `installer/tests/Test-*.ps1`
other than `Test-BinDirLeftovers.ps1`. I did not run the onboarding pytest
suite (system python, and the territory's Python change is one function I
tested by reading); a run of `cd onboarding; python -m pytest tests -q` is
still owed centrally. Neither uninstaller was executed for real, per the
brief - all Windows evidence is from the extracted function and the AST-driven
harness, all macOS evidence from the sliced-section harness. The suites cover
neither the section 5 identity paragraph nor `~/.ccsync` removal at all.

## OUT OF TERRITORY
- `companion/src/ccsync_companion/supervisor.py`: `decide` has no "an
  uninstall is in progress" stand-down; only a missing exe stops a relaunch,
  and the exe survives section 1 of the uninstaller (cited in
  install-onboard-5, comp-app's to judge).
