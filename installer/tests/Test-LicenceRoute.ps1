<#
.SYNOPSIS
    Table test for windows_upgrade.ps1's Select-LicenceRoute (bug hunt
    2026-09-24, logic-onboarding-3).

.DESCRIPTION
    A licence-only problem after a package upgrade used to launch onboard.exe,
    the whole reinstall, while the companion the script had just relaunched
    opened its own one-click licence dialog three seconds later. The rule now:
    a RUNNING companion owns the question ("tray"); the wizard is only for a
    machine where nothing else can ask it.

    Run:  powershell -NoProfile -ExecutionPolicy Bypass -File installer\tests\Test-LicenceRoute.ps1
    Exits 1 on any failure.
#>
$ErrorActionPreference = "Stop"

$UpgradePath = Join-Path (Split-Path -Parent $PSScriptRoot) "windows_upgrade.ps1"
$src = Get-Content -Raw $UpgradePath
$start = $src.IndexOf('function Select-LicenceRoute')
$end = $src.IndexOf('if (-not (Test-Path -LiteralPath $acceptancePath))')
if ($start -lt 0 -or $end -lt 0 -or $end -le $start) {
    Write-Host "FAIL: could not slice Select-LicenceRoute out of $UpgradePath -- did it get renamed or moved?" -ForegroundColor Red
    exit 1
}
Invoke-Expression $src.Substring($start, $end - $start)

$failures = 0
function Check {
    param([string]$What, $Expected, $Actual)
    if ($Expected -eq $Actual) { Write-Host ("  ok   {0}" -f $What) }
    else {
        $script:failures++
        Write-Host ("  FAIL {0}: expected [{1}], got [{2}]" -f $What, $Expected, $Actual) -ForegroundColor Red
    }
}

function Route {
    param([bool]$Needed = $true, [bool]$Running = $false, [bool]$Skip = $false,
          [bool]$Base = $false, [bool]$Dry = $false, [bool]$Onboard = $true)
    return Select-LicenceRoute -Needed $Needed -CompanionRunning $Running -SkipWizard $Skip `
        -IsBaseRig $Base -DryRun $Dry -OnboardPresent $Onboard
}

Write-Host "`n--- Select-LicenceRoute ---"
Check "nothing to accept"                          "none"    (Route -Needed $false -Running $true)
Check "running companion asks, not the wizard"     "tray"    (Route -Running $true)
Check "running companion beats -SkipWizard"        "tray"    (Route -Running $true -Skip $true)
Check "running companion on the base rig"          "tray"    (Route -Running $true -Base $true)
Check "no companion: the wizard"                   "wizard"  (Route)
Check "no companion, -SkipWizard"                  "skip"    (Route -Skip $true)
Check "no companion, base rig"                     "base"    (Route -Base $true)
Check "no companion, dry run"                      "dryrun"  (Route -Dry $true)
Check "no companion, no onboard.exe"               "missing" (Route -Onboard $false)
# Review round 2026-09-25: a -DryRun leaves $copySucceeded AND $relaunchAlive
# true (nothing ran to clear them), so the combination step 6 actually produces
# in a dry run is Running=$true. Nothing was relaunched, so it must not be "tray".
Check "dry run, as step 6 really calls it"         "dryrun"  (Route -Running $true -Dry $true)
Check "dry run + -SkipWizard"                      "skip"    (Route -Running $true -Dry $true -Skip $true)
Check "dry run on the base rig"                    "base"    (Route -Running $true -Dry $true -Base $true)

# The launch branch must be keyed on the route, not on $wizardNeeded alone.
if ($src -notmatch '\$licenceRoute\s*=\s*Select-LicenceRoute') {
    $failures++
    Write-Host "  FAIL step 6 no longer decides through Select-LicenceRoute" -ForegroundColor Red
}
else { Write-Host "  ok   step 6 decides through Select-LicenceRoute" }
# The dry-run branch launched nothing, so it must not claim the wizard is open.
$dryStart = $src.IndexOf('elseif ($licenceRoute -eq "dryrun")')
$dryEnd = $src.IndexOf('elseif ($licenceRoute -eq "missing")')
if ($dryStart -lt 0 -or $dryEnd -le $dryStart) {
    $failures++
    Write-Host "  FAIL could not find the dryrun branch of step 6" -ForegroundColor Red
}
elseif ($src.Substring($dryStart, $dryEnd - $dryStart) -match '\$wizardLaunched\s*=\s*\$true') {
    $failures++
    Write-Host "  FAIL the dryrun branch sets `$wizardLaunched (the summary would say the wizard is open)" -ForegroundColor Red
}
else { Write-Host "  ok   the dryrun branch does not claim a launch" }
if ($src.Contains("`t")) {
    $failures++
    Write-Host "  FAIL windows_upgrade.ps1 contains a literal TAB (an unescaped backslash-t in a path?)" -ForegroundColor Red
}
else { Write-Host "  ok   no literal TAB in windows_upgrade.ps1" }
if ($src -match "all three tray lines read") {
    $failures++
    Write-Host "  FAIL the stale 'all three tray lines' copy is back (untrue since CR-88)" -ForegroundColor Red
}
else { Write-Host "  ok   no stale tray-line copy" }

if ($failures -gt 0) {
    Write-Host "`n$failures failure(s)" -ForegroundColor Red
    exit 1
}
Write-Host "`nall passed" -ForegroundColor Green
exit 0
