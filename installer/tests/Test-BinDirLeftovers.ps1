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

# install-onboard-2 (2026-09-11b): before the function existed, the
# "delete that file, and the folder it is in" notice was an UNCONDITIONAL
# Write-Step in the script body, four lines under "run this uninstaller again
# from Apps & features". Checked structurally as well as behaviourally,
# because a script body cannot be called and the phrase moving back out of
# the function is exactly how the contradiction would return.
$uToks = $null; $uErrs = $null
$uAst = [System.Management.Automation.Language.Parser]::ParseFile(
    $UninstallScript, [ref]$uToks, [ref]$uErrs)
$adviceFn = $uAst.FindAll({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst]
}, $true) | Where-Object { $_.Name -eq "Get-UninstallClosingAdvice" } | Select-Object -First 1
$strayNotice = @($uAst.FindAll({
    param($node)
    ($node -is [System.Management.Automation.Language.StringConstantExpressionAst] -or
     $node -is [System.Management.Automation.Language.ExpandableStringExpressionAst]) -and
    $node.Value -match "elete that file, and the folder it is in"
}, $true) | Where-Object {
    -not $adviceFn -or
    $_.Extent.StartOffset -lt $adviceFn.Extent.StartOffset -or
    $_.Extent.EndOffset -gt $adviceFn.Extent.EndOffset
})
if ($strayNotice.Count -gt 0) {
    Write-Host ("  FAIL  the 'delete that file, and the folder it is in' notice is printed outside " +
        "Get-UninstallClosingAdvice (line $($strayNotice[0].Extent.StartLineNumber)), so a run that " +
        "left the binaries behind still tells the editor to delete the retry path it just named") -ForegroundColor Red
    exit 1
}

Invoke-Expression (Get-Function $UninstallScript "Get-BinDirLeftovers")
Invoke-Expression (Get-Function $UninstallScript "Get-UninstallClosingAdvice")

$fail = 0
function Ok  { param([string]$m) Write-Host "  PASS  $m" -ForegroundColor DarkGreen }
function Bad { param([string]$m) Write-Host "  FAIL  $m" -ForegroundColor Red; $script:fail++ }
function Check {
    param([string]$Label, $Expected, $Actual)
    if ("$Expected" -eq "$Actual") { Ok $Label } else { Bad "$Label`: got '$Actual' want '$Expected'" }
}

# $env:TEMP is 8.3 SHORT form on any profile that has one -- a hosted Windows
# runner's is C:\Users\RUNNER~1\AppData\Local\Temp -- while every FullName
# Get-ChildItem reports is the long one. Expectations built from the raw
# variable compared a short path against a long answer and failed seven cases
# on CI while passing here (2026-09-11, CI run 34583384353). One spelling, for
# every path this file builds.
$TempRoot = (Get-Item -LiteralPath $env:TEMP -Force).FullName
$BinDir = Join-Path $TempRoot "ccsync-test-leftovers"
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

# --- install-onboard-2 (2026-09-11b): the closing advice must not contradict
# itself. "Run this uninstaller again from Apps & features" and "delete that
# file, and the folder it is in" were printed four lines apart, and following
# the second deletes the retry path the first names.
$Bin = "C:\Users\leso\AppData\Local\ccsync\bin"
$Self = Join-Path $Bin "windows_uninstall.ps1"

$leftoverAdvice = @(Get-UninstallClosingAdvice -LeftoverCount 3 -BinDir $Bin -SelfPath $Self)
$leftoverText = ($leftoverAdvice | ForEach-Object { $_.Text }) -join "`n"
if ($leftoverText -match "NOT complete") {
    Ok "a run with leftovers says it is not complete"
} else {
    Bad "a run with leftovers does not say so: $leftoverText"
}
if ($leftoverText -match "elete that file, and the folder it is in") {
    Bad "the leftovers path still tells the editor to delete the uninstaller and the folder holding the program files it just asked them to retry with"
} else {
    Ok "the leftovers path does not tell the editor to delete its own retry path"
}
if ($leftoverText -match "LEAVE this uninstaller where it is") {
    Ok "the leftovers path says to leave the uninstaller in place"
} else {
    Bad "the leftovers path says nothing about the uninstaller still on disk"
}

$cleanAdvice = @(Get-UninstallClosingAdvice -LeftoverCount 0 -BinDir $Bin -SelfPath $Self)
$cleanText = ($cleanAdvice | ForEach-Object { $_.Text }) -join "`n"
if ($cleanText -match "uninstall complete") {
    Ok "a clean run still says complete"
} else {
    Bad "a clean run no longer says complete: $cleanText"
}
if ($cleanText -match "elete that file, and the folder it is in") {
    Ok "a clean run still offers to let the editor delete the leftover script"
} else {
    Bad "a clean run lost the self-on-disk notice (OPS-17)"
}
Check "a clean run warns about nothing" 0 (@($cleanAdvice | Where-Object { $_.Kind -eq "warn" }).Count)
Check "a run with leftovers warns" 1 (@($leftoverAdvice | Where-Object { $_.Kind -eq "warn" }).Count)

# An uninstaller run from somewhere else (a hand copy, the repo) is not in the
# bin dir and there is nothing to say about it.
$elsewhere = ((Get-UninstallClosingAdvice -LeftoverCount 0 -BinDir $Bin -SelfPath "D:\downloads\windows_uninstall.ps1" |
    ForEach-Object { $_.Text }) -join "`n")
if ($elsewhere -match "still on disk") {
    Bad "a script outside the bin dir is reported as a leftover of the install"
} else {
    Ok "a script run from outside the bin dir gets no self-on-disk notice"
}
$dash = [string][char]0x2014
if (($leftoverText + $cleanText) -like "*$dash*") {
    Bad "the closing advice contains an em dash"
} else {
    Ok "no em dash in the closing advice"
}

# --- tests-5 (hand-off wave, 2026-09-11b): REPORTED, not merely computed ------
# Every case above drives Get-BinDirLeftovers / Get-UninstallClosingAdvice
# directly, so a refactor that keeps both functions and stops PRINTING their
# answer - the exact shape tests-5 names - passed the whole file. These two
# cases execute the script's OWN statements (taken from its AST, so they
# cannot drift from what runs) with the output functions captured and the
# delete stubbed out, which is PowerShell 5.1's real leftovers case: one
# locked child and Remove-Item -Recurse deletes nothing at all.

function Get-ScriptStatement {
    param($Ast, [string]$TypeName, [string[]]$Match)
    $found = $Ast.FindAll({
        param($node)
        $node.GetType().Name -eq $TypeName
    }, $true) | Where-Object {
        $text = $_.Extent.Text
        $all = $true
        foreach ($m in $Match) { if ($text -notmatch $m) { $all = $false } }
        $all
    } | Sort-Object { $_.Extent.Text.Length } | Select-Object -First 1
    if (-not $found) {
        Bad "the uninstaller no longer has a $TypeName matching $($Match -join ' + ')"
        return $null
    }
    return $found.Extent.Text
}

# 1. The delete-and-report block: the leftovers must reach Write-Warn2.
$reportBlock = Get-ScriptStatement -Ast $uAst -TypeName "IfStatementAst" `
    -Match @("Get-BinDirLeftovers", "Remove-Item -LiteralPath \`$BinDir -Recurse")
if ($reportBlock) {
    $Sandbox = Join-Path $TempRoot "ccsync-test-leftovers-report"
    try {
        if (Test-Path -LiteralPath $Sandbox) { Remove-Item -LiteralPath $Sandbox -Recurse -Force }
        New-Item -ItemType Directory -Path $Sandbox -Force | Out-Null
        $stuck = Join-Path $Sandbox "ccsync-companion.exe"
        Set-Content -LiteralPath $stuck -Value "MZ" -Encoding UTF8
        $selfInBin = Join-Path $Sandbox "windows_uninstall.ps1"
        Set-Content -LiteralPath $selfInBin -Value "# the running uninstaller" -Encoding UTF8

        $run = & {
            param($blockText, $BinDir, $PSCommandPath)
            $printed = New-Object System.Collections.ArrayList
            function Write-Step  { param([string]$m) [void]$printed.Add("step: $m") }
            function Write-Skip  { param([string]$m) [void]$printed.Add("skip: $m") }
            function Write-Warn2 { param([string]$m) [void]$printed.Add("warn: $m") }
            # The locked-child case: PowerShell 5.1 deletes NOTHING when one
            # file in the tree is open, and answers nothing either.
            function Remove-Item { }
            $DryRun = $false
            $binLeftovers = @()
            Invoke-Expression $blockText
            [pscustomobject]@{ Printed = @($printed); Count = @($binLeftovers).Count }
        } $reportBlock $Sandbox $selfInBin

        $out = ($run.Printed) -join "`n"
        Check "the script's own block finds the locked exe" 1 $run.Count
        if ($out -match [regex]::Escape($stuck)) {
            Ok "the leftover is PRINTED by the uninstaller's own statements, not just computed"
        } else {
            Bad "the uninstaller computed a leftover and printed nothing an editor can read: $out"
        }
        if ($out -match "run this uninstaller again from Apps & features") {
            Ok "the printed report names the retry path"
        } else {
            Bad "the printed report does not tell the editor how to retry: $out"
        }
        if ($out -match "removed program binaries") {
            Bad "the uninstaller reported success over a bin dir it had not emptied"
        } else {
            Ok "a run with leftovers never claims the binaries were removed"
        }
    }
    finally {
        if (Test-Path -LiteralPath $Sandbox) {
            Remove-Item -LiteralPath $Sandbox -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

# 2. The closing paragraph: Get-UninstallClosingAdvice returns Kind/Text, and
# a warn line that is printed with Write-Step is a warning nobody sees.
$closingLoop = Get-ScriptStatement -Ast $uAst -TypeName "ForEachStatementAst" `
    -Match @("Get-UninstallClosingAdvice")
if ($closingLoop) {
    $run2 = & {
        param($loopText, $BinDir, $selfOnDisk)
        $printed = New-Object System.Collections.ArrayList
        function Write-Step  { param([string]$m) [void]$printed.Add("step: $m") }
        function Write-Warn2 { param([string]$m) [void]$printed.Add("warn: $m") }
        $DryRun = $false
        $binLeftovers = @("a.exe", "b.exe", "c.exe")
        Invoke-Expression $loopText
        ,@($printed)
    } $closingLoop "C:\Users\leso\AppData\Local\ccsync\bin" "C:\Users\leso\AppData\Local\ccsync\bin\windows_uninstall.ps1"

    $warned = @($run2 | Where-Object { $_ -like "warn: *" -and $_ -match "NOT complete" })
    if ($warned.Count -eq 1) {
        Ok "the closing advice reaches the editor as a WARNING on the leftovers path"
    } else {
        Bad "the closing 'NOT complete' line was not printed as a warning: $($run2 -join '; ')"
    }
    if (($run2 -join "`n") -match "3 program file") {
        Ok "the closing advice names how many files are left"
    } else {
        Bad "the closing advice lost the count: $($run2 -join '; ')"
    }
}


Write-Host ""
if ($fail -gt 0) {
    Write-Host "$fail FAILED" -ForegroundColor Red
    exit 1
}
Write-Host "all bin-dir leftover cases pass" -ForegroundColor Green
