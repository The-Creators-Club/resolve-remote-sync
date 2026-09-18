# CR-303 - the -Full uninstall's closing paragraph: one verdict, and LOOK before claiming - FIXED in repo 2026-09-18 (installer)

The three findings are three faces of one paragraph, so they were fixed in one
change (the verifier asked for exactly that: fix install-onboard-4 first or in
the same change as -3, because -3's survivors inherit -4's wording).

### CR-303A (install-onboard-1) - the -Full leftovers verdict tells the editor to retry and, two lines later, to delete the retry path - FIXED (installer/windows_uninstall.ps1)
CR-286's new "NOT complete" branch in `Get-UninstallClosingAdvice` is keyed on
`$identityCount`, but the self-path arm below it was still keyed on
`$LeftoverCount -gt 0` alone. On the identity branch `$LeftoverCount` is 0 -
`Get-BinDirLeftovers` deliberately excludes the running script - so the same
paragraph printed "run this uninstaller again with -Full" and then "delete that
file, and the folder it is in, whenever you like". The arm is now gated on
`($LeftoverCount -gt 0 -or $identityCount -gt 0)` and its LEAVE line no longer
claims "the program files listed above" on the identity branch, where nothing
was listed. `Test-BinDirLeftovers.ps1` asserts the whole paragraph now, not the
"NOT complete" substring: an unfinished -Full run must carry the LEAVE line and
must not carry the delete-it notice.

### CR-303B (install-onboard-4) - any surviving file was called "your sign-in and Syncthing identity" - FIXED (installer/windows_uninstall.ps1)
Section 5's paragraph decided the identity question with
`Test-Path $SyncthingHome`; the closing verdict decided it with
`Get-FullRemovalLeftovers`, which returns every surviving top-level child of
`%LOCALAPPDATA%\ccsync` and called all of them items of the identity. The
ordinary split outcome - `bin\` survives because it is the CWD of the host Apps
& features launched, `syncthing-config\` really went - printed both "a reinstall
generates a NEW device ID" and "your sign-in and Syncthing identity are still on
this machine", which answers the admin's re-approve question both ways. The
verdict is measured once now (`$identityStillThere`, declared beside
`$fullLeftovers` so every path has it) and passed into the advice as
`-IdentityPresent`; the leftovers line says "item(s) of the CC Sync app folder"
and names the identity only when it really survived. Tests drive both
`-IdentityPresent` values and assert that SAME and NEW device ID never appear
together.

### CR-303C (install-onboard-3) - "removed your sign-in and settings" printed without looking - FIXED (installer/windows_uninstall.ps1)
The `~/.ccsync` loop deletes with `-ErrorAction SilentlyContinue` and printed
`$doomed.Count`, the count it INTENDED to delete, outside any leftovers test;
`$fullLeftovers` scans `%LOCALAPPDATA%\ccsync` only, so the closing verdict
could not catch it either and a run that removed nothing there still ended
"CCSync uninstall complete". `config.toml` holds the per-editor `cce1.` fleet
credential and `dashboard_token`, and `companion.log` is held open by the
companion section 1 killed without waiting. The block now re-reads the
directory (still excluding `state\`, which is KEPT on purpose), prints "removed
N, could NOT remove M" with the survivors named, and folds the survivors into
`$fullLeftovers` so the closing verdict sees them. The test executes the
script's own statements from its AST with `Remove-Item` stubbed (PowerShell
5.1's real locked case: nothing is deleted at all).

### Verification
- CR-303A: `Test-BinDirLeftovers.ps1` - "an unfinished -Full run does not tell the editor to delete its own retry path" / "... says to leave the uninstaller in place". Both FAIL on the pre-fix script (reverted copy in the scratchpad), pass now.
- CR-303B: same file - "leftovers that are not the identity are not called the identity", "an identity that survived is reported as the SAME device ID, once", "the two device ID answers never appear together". All FAIL pre-fix.
- CR-303C: same file - "a ~/.ccsync delete that removed nothing never claims it did", "the survivors ... counted from the directory, not from the intent", "the ~/.ccsync survivors reach the closing verdict" (2), "the surviving config.toml is named". All FAIL pre-fix; "state\ is still kept" guards the KEPT paragraph.
- Whole file green after: `powershell -NoProfile -ExecutionPolicy Bypass -File installer\tests\Test-BinDirLeftovers.ps1` -> all cases pass. `Test-UninstallEntry.ps1` (the other reader of this script) still passes. No uninstaller was executed at any point.
- Pre-fix run: 9 FAILED, all of them the new cases.

### Not fixed
- install-onboard-2, -5, -6 (downgraded to low by the verifier) were not started. install-onboard-2's workable half - the identity branch naming the exact hand-delete command - is partly covered: the branch now ends "or delete the item(s) listed above by hand", and section 5 lists them. A literal `Remove-Item -LiteralPath ... -Recurse -Force` line was left out of the box.
- install-onboard-7 (the -Full tests assert only the "NOT complete" substring) is answered in passing for this paragraph: the new cases assert the whole text.

### OWED TO ANOTHER GROUP
- None. Every change is inside `installer/windows_uninstall.ps1` and its own test file.

### Deploy order
- No wire. The uninstaller ships with the editor package (`windows_bootstrap.ps1` copies it into `bin\`), so the fix reaches a machine only on its next install or upgrade; an older copy on disk keeps the old paragraph and is harmless.

### Owner decisions
- None needed.
