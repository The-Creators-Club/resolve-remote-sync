<#
.SYNOPSIS
    Table tests for the uninstaller's "did the binaries actually go?" check
    (bug hunt 2026-09-11, install-onboard-3).

.DESCRIPTION
    windows_uninstall.ps1 deleted %LOCALAPPDATA%\ccsync\bin with
    -ErrorAction SilentlyContinue, never re-read it, and printed "removed
    program binaries" either way -- after the Apps & features entry had
    already been deleted. A locked companion exe (Stop-Process -Force does
    not wait for the image handle to be released), an AV scan, or simply the
    uninstaller running out of that same directory therefore left the app on
    disk with nothing in Apps & features to retry with, and a report that
    said it was gone.

    Two files are EXPECTED to survive a healthy uninstall: the running script
    itself and the drive_mapping.ps1 it dot-sources, both of which
    windows_bootstrap.ps1 copies into the bin dir (OPS-17). A check that
    counted those would warn on every successful run and teach editors to
    ignore the warning, so Get-BinDirLeftovers excludes them.

    The function is extracted with the PowerShell parser rather than
    dot-sourced, which would run the uninstaller.

    Run:  powershell -NoProfile -ExecutionPolicy Bypass -File installer\tests\Test-BinDirLeftovers.ps1
    Exits 1 on any failure.
#>
$ErrorActionPreference = "Stop"
$InstallerDir = Split-Path -Parent $PSScriptRoot

function Get-Function {
    param([string]$Path, [string]$Name)
    if (-not (Test-Path -LiteralPath $Path)) {
        Write-Host "FAIL: no $Path" -ForegroundColor Red
        exit 1
    }
    $tokens = $null
    $errors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseFile(
        $Path, [ref]$tokens, [ref]$errors)
    if ($errors -and $errors.Count -gt 0) {
        Write-Host "FAIL: $Path does not parse: $($errors[0].Message)" -ForegroundColor Red
        exit 1
    }
    $fn = $ast.FindAll({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst]
    }, $true) | Where-Object { $_.Name -eq $Name } | Select-Object -First 1
    if (-not $fn) {
        Write-Host "FAIL: $Path no longer defines $Name" -ForegroundColor Red
        exit 1
    }
    return $fn.Extent.Text
}

$UninstallScript = Join-Path $InstallerDir "windows_uninstall.ps1"
Invoke-Expression (Get-Function $UninstallScript "Get-BinDirLeftovers")

$fail = 0
function Ok  { param([string]$m) Write-Host "  PASS  $m" -ForegroundColor DarkGreen }
function Bad { param([string]$m) Write-Host "  FAIL  $m" -ForegroundColor Red; $script:fail++ }
function Check {
    param([string]$Label, $Expected, $Actual)
    if ("$Expected" -eq "$Actual") { Ok $Label } else { Bad "$Label`: got '$Actual' want '$Expected'" }
}

$BinDir = Join-Path $env:TEMP "ccsync-test-leftovers"
$SelfPath = Join-Path $BinDir "windows_uninstall.ps1"

try {
    if (Test-Path -LiteralPath $BinDir) { Remove-Item -LiteralPath $BinDir -Recurse -Force }

    # A bin dir that is simply gone is the healthy end state.
    Check "a deleted bin dir has no leftovers" 0 `
        (@(Get-BinDirLeftovers -BinDir $BinDir -SelfPath $SelfPath).Count)

    # ...and so is one holding only the uninstaller and its drive library:
    # PowerShell may still have the running script open, and a script cannot
    # report its own corpse as a failure.
    New-Item -ItemType Directory -Path $BinDir -Force | Out-Null
    Set-Content -LiteralPath $SelfPath -Value "# the running uninstaller" -Encoding UTF8
    Set-Content -LiteralPath (Join-Path $BinDir "drive_mapping.ps1") -Value "# lib" -Encoding UTF8
    Check "the uninstaller and drive_mapping.ps1 are expected leftovers" 0 `
        (@(Get-BinDirLeftovers -BinDir $BinDir -SelfPath $SelfPath).Count)

    # The companion exe surviving is the whole point: it is the file a
    # Stop-Process that has not settled leaves behind.
    $Exe = Join-Path $BinDir "ccsync-companion.exe"
    Set-Content -LiteralPath $Exe -Value "MZ" -Encoding UTF8
    $left = @(Get-BinDirLeftovers -BinDir $BinDir -SelfPath $SelfPath)
    Check "a locked companion exe is reported" 1 $left.Count
    Check "the leftover is named in full" $Exe $left[0]

    # A file in a SUBDIRECTORY counts too (syncthing/rclone land there).
    New-Item -ItemType Directory -Path (Join-Path $BinDir "sub") -Force | Out-Null
    Set-Content -LiteralPath (Join-Path $BinDir "sub\rclone.exe") -Value "MZ" -Encoding UTF8
    Check "a leftover below the top level is found" 2 `
        (@(Get-BinDirLeftovers -BinDir $BinDir -SelfPath $SelfPath).Count)

    # A drive_mapping.ps1 somewhere else in the tree is NOT the expected one.
    Set-Content -LiteralPath (Join-Path $BinDir "sub\drive_mapping.ps1") -Value "# copy" -Encoding UTF8
    Check "only the top-level drive_mapping.ps1 is excused" 3 `
        (@(Get-BinDirLeftovers -BinDir $BinDir -SelfPath $SelfPath).Count)

    # An unreadable directory must not throw at the caller: the uninstall is
    # over by then and an exception would swallow the closing report.
    Check "an empty path answers nothing rather than throwing" 0 `
        (@(Get-BinDirLeftovers -BinDir "" -SelfPath $SelfPath).Count)
}
finally {
    if (Test-Path -LiteralPath $BinDir) {
        Remove-Item -LiteralPath $BinDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}

# The ORDER is the other half of install-onboard-3: the Apps & features entry
# is the only button an editor has to retry with, so it must not be removed
# before the binaries are known to be gone.
$text = Get-Content -LiteralPath $UninstallScript -Raw -Encoding UTF8
$lines = $text -split "`r?`n"
$entryLine = 0
$deleteLine = 0
for ($i = 0; $i -lt $lines.Count; $i++) {
    if (-not $entryLine -and $lines[$i] -match "Unregister-UninstallEntry -KeyRoot") { $entryLine = $i + 1 }
    if (-not $deleteLine -and $lines[$i] -match "Remove-Item -LiteralPath \`$BinDir -Recurse") { $deleteLine = $i + 1 }
}
if (-not $entryLine -or -not $deleteLine) {
    Bad "could not find the entry removal ($entryLine) and the bin-dir delete ($deleteLine)"
}
elseif ($deleteLine -lt $entryLine) {
    Ok "the bin dir is deleted before the Apps & features entry is removed"
}
else {
    Bad "the Apps & features entry (line $entryLine) is removed before the bin dir is deleted (line $deleteLine): an editor whose binaries survive has no button left to retry with"
}

Write-Host ""
if ($fail -gt 0) {
    Write-Host "$fail FAILED" -ForegroundColor Red
    exit 1
}
Write-Host "all bin-dir leftover cases pass" -ForegroundColor Green
