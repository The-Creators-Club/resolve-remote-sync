<#
.SYNOPSIS
    Table tests for windows_uninstall.ps1's share/firewall-rule ordering
    (bug-hunt-2026-09-03 install-onboard-3).

.DESCRIPTION
    The inbound 139/445 block rule is what scopes the loopback tree share --
    the editor's ENTIRE project tree -- to this machine, and only a re-run of
    windows_bootstrap.ps1 ever re-applies it. So it may only be removed once
    the share is PROVEN gone. It used to be gated on "we deliberately kept the
    share", which meant a clean unmap plus a Remove-SmbShare that threw (a
    handle open on the tree) dropped the block while the share stayed
    published.

    Test-SmbShareGone is the whole decision, pure and separate precisely so it
    can be checked here: a re-read that FAILED is "still there", never "gone".
    Extracted with the PowerShell parser rather than dot-sourced, which would
    run the uninstaller.

    Run:  powershell -NoProfile -ExecutionPolicy Bypass -File installer\tests\Test-SmbShareGone.ps1
    Exits 1 on any failure.
#>
$ErrorActionPreference = "Stop"
$InstallerDir = Split-Path -Parent $PSScriptRoot
$UninstallPath = Join-Path $InstallerDir "windows_uninstall.ps1"
if (-not (Test-Path -LiteralPath $UninstallPath)) {
    Write-Host "FAIL: no windows_uninstall.ps1 at $UninstallPath" -ForegroundColor Red
    exit 1
}

$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $UninstallPath, [ref]$tokens, [ref]$errors)
if ($errors -and $errors.Count -gt 0) {
    Write-Host "FAIL: windows_uninstall.ps1 does not parse: $($errors[0].Message)" -ForegroundColor Red
    exit 1
}
$fn = $ast.FindAll({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst]
}, $true) | Where-Object { $_.Name -eq 'Test-SmbShareGone' } | Select-Object -First 1
if (-not $fn) {
    Write-Host "FAIL: windows_uninstall.ps1 no longer defines Test-SmbShareGone" -ForegroundColor Red
    exit 1
}
Invoke-Expression $fn.Extent.Text

$fail = 0
function Ok  { param([string]$m) Write-Host "  PASS  $m" -ForegroundColor DarkGreen }
function Bad { param([string]$m) Write-Host "  FAIL  $m" -ForegroundColor Red; $script:fail++ }
function Check {
    param([string]$Label, [bool]$Expected, [bool]$Actual)
    if ($Expected -eq $Actual) { Ok $Label } else { Bad "$Label`: got '$Actual' want '$Expected'" }
}

# A share object shaped like the one Get-SmbShare returns; only its presence
# is read.
$stillThere = [PSCustomObject]@{ Name = "CCSync_P"; Path = "C:\CCSync" }

Check "a re-read that returns nothing means gone" $true `
    (Test-SmbShareGone -ShareAfter $null -ReadFailed $false)
Check "a re-read that still finds the share means NOT gone" $false `
    (Test-SmbShareGone -ShareAfter $stillThere -ReadFailed $false)
# The Get-SmbShare-throws path: $null with nothing behind it. Treating that
# as "gone" is how the block rule went away on a machine still serving the
# tree.
Check "an unreadable re-read counts as still there" $false `
    (Test-SmbShareGone -ShareAfter $null -ReadFailed $true)
Check "an unreadable re-read counts as still there even with an object" $false `
    (Test-SmbShareGone -ShareAfter $stillThere -ReadFailed $true)

# --- the call sites are still wired ---------------------------------------
$src = Get-Content -Raw $UninstallPath
if ($src -match '\$sharePublished = -not \(Test-SmbShareGone') {
    Ok "the uninstaller re-reads the share after trying to remove it"
} else {
    Bad "nothing in windows_uninstall.ps1 calls Test-SmbShareGone any more"
}
if ($src -match 'if \(\$smbRule -and \$sharePublished\)') {
    Ok "the firewall rule is gated on the share actually being gone"
} else {
    Bad 'the firewall-rule gate is not "$smbRule -and $sharePublished" (install-onboard-3)'
}
if ($src -match 'if \(\$smbRule -and \$share -and -not \$unmapSettled\)') {
    Bad "the old gate is back: a failed Remove-SmbShare drops the block rule"
} else {
    Ok 'the old "-not $unmapSettled" gate is gone'
}
# Two reads, not one: the pre-removal read decides what to do, the
# post-removal read decides whether the block rule may go.
$reads = ([regex]::Matches($src, 'Get-SmbShare -Name \$ShareName')).Count
if ($reads -ge 2) { Ok "the share is read both before and after the removal" }
else { Bad "only $reads Get-SmbShare call(s): the post-removal re-read is missing" }

Write-Host ""
if ($fail -gt 0) {
    Write-Host "$fail FAILED" -ForegroundColor Red
    exit 1
}
Write-Host "all SMB share / firewall-rule ordering cases pass" -ForegroundColor Green
