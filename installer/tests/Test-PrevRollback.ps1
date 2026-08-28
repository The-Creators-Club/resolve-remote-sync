<#
.SYNOPSIS
    Table tests for windows_upgrade.ps1's Move-InstalledAside and
    Restore-InstalledFromPrev -- the two renames REL-12 turns on.

.DESCRIPTION
    Until 2026-08-28 step 2 copied the new exe straight over the live one.
    When the new build then exited inside $RelaunchConfirmSeconds, the script
    printed an accurate and useless warning: this machine now has no
    companion, no lanes, no Resolve bridge, and nothing retries before the
    next logon. There was no <exe>.old on this path, unlike the self-upgrade
    path, so there was nothing to put back even by hand.

    Both directions are failure-shaped, which is why they are tested:

      * Failing to keep the previous build must NOT abort the upgrade -- an
        upgrade that cannot be rolled back is still better than none -- but
        it must be visible, so the function returns $false rather than
        throwing, and the caller says so.
      * Restoring must never delete the build that failed (it is the only
        evidence of why) and must never leave the machine with no exe at all.

    Run:  powershell -NoProfile -ExecutionPolicy Bypass -File installer\tests\Test-PrevRollback.ps1
    Exits 1 on any failure.
#>
$ErrorActionPreference = "Stop"

# Same slicing trick as Test-LicenceGate.ps1: pull the two functions out of
# the upgrade script so they run against temp files with no machine involved.
$UpgradePath = Join-Path (Split-Path -Parent $PSScriptRoot) "windows_upgrade.ps1"
$src = Get-Content -Raw $UpgradePath
$start = $src.IndexOf('function Move-InstalledAside')
$end = $src.IndexOf('$BinDir = "$env:LOCALAPPDATA')
if ($start -lt 0 -or $end -lt 0 -or $end -le $start) {
    Write-Host "FAIL: could not slice the rollback helpers out of $UpgradePath -- did a function get renamed?" -ForegroundColor Red
    exit 1
}
Invoke-Expression $src.Substring($start, $end - $start)

$failures = 0
function Check {
    param([string]$What, $Expected, $Actual)
    if ($Expected -eq $Actual) {
        Write-Host ("  ok   {0}" -f $What)
    }
    else {
        $script:failures++
        Write-Host ("  FAIL {0}: expected [{1}], got [{2}]" -f $What, $Expected, $Actual) -ForegroundColor Red
    }
}

$tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("ccsync-prev-test-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tmp | Out-Null
try {
    $exe = Join-Path $tmp "ccsync-companion.exe"
    $prev = "$exe.prev"
    $failed = "$exe.failed"

    Write-Host "`n--- Move-InstalledAside ---"

    Set-Content -LiteralPath $exe -Value "v0.9.54" -Encoding ASCII
    Check "keeps the installed build" $true (Move-InstalledAside -ExePath $exe -PrevPath $prev)
    Check "  the exe has moved out of the way" $false (Test-Path -LiteralPath $exe)
    Check "  and its bytes are at .prev" "v0.9.54" (Get-Content -LiteralPath $prev -Raw).Trim()

    # A first install: nothing to keep, and that is not a failure.
    Remove-Item -LiteralPath $prev -Force
    Check "no installed exe yields false, not an error" $false (Move-InstalledAside -ExePath $exe -PrevPath $prev)

    # A second upgrade must overwrite the older .prev rather than refuse: the
    # rule is "keep the build being replaced until the next successful
    # upgrade", not "keep every build ever".
    Set-Content -LiteralPath $prev -Value "v0.9.53" -Encoding ASCII
    Set-Content -LiteralPath $exe -Value "v0.9.54" -Encoding ASCII
    Check "a newer .prev replaces an older one" $true (Move-InstalledAside -ExePath $exe -PrevPath $prev)
    Check "  .prev is the build just replaced" "v0.9.54" (Get-Content -LiteralPath $prev -Raw).Trim()

    Write-Host "`n--- Restore-InstalledFromPrev ---"

    # The REL-12 case: the new build is installed and will not start.
    Set-Content -LiteralPath $exe -Value "v0.9.55-broken" -Encoding ASCII
    Check "restores the previous build" $true (Restore-InstalledFromPrev -ExePath $exe -PrevPath $prev -FailedPath $failed)
    Check "  the installed exe is the previous build" "v0.9.54" (Get-Content -LiteralPath $exe -Raw).Trim()
    Check "  the build that failed is kept as evidence" "v0.9.55-broken" (Get-Content -LiteralPath $failed -Raw).Trim()
    Check "  .prev is consumed" $false (Test-Path -LiteralPath $prev)

    # Nothing to restore: say so rather than leave the caller thinking it
    # rolled back.
    Check "no .prev yields false" $false (Restore-InstalledFromPrev -ExePath $exe -PrevPath $prev -FailedPath $failed)
    Check "  and the installed exe is untouched" "v0.9.54" (Get-Content -LiteralPath $exe -Raw).Trim()

    # The copy-failed case: no exe in place at all, and no $FailedPath given.
    Set-Content -LiteralPath $prev -Value "v0.9.54" -Encoding ASCII
    Remove-Item -LiteralPath $exe -Force
    Check "restores with no exe in place" $true (Restore-InstalledFromPrev -ExePath $exe -PrevPath $prev)
    Check "  the machine has an exe again" "v0.9.54" (Get-Content -LiteralPath $exe -Raw).Trim()
}
finally {
    Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host ""
if ($failures -gt 0) {
    Write-Host "$failures check(s) FAILED" -ForegroundColor Red
    exit 1
}
Write-Host "all checks passed" -ForegroundColor Green
exit 0
