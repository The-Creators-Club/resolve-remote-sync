<#
.SYNOPSIS
    windows_bootstrap.ps1's "the tree drive is not ours" refusal is a
    CAPABILITY MISS, not a warning (OPS-1, usability + resilience sweep
    2026-09-04).

.DESCRIPTION
    $script:PIsForeign is set when the tree drive belongs to somebody else OR
    when this logon session would not say. The script then prints an error and
    four warnings and carries on -- and it was the one refusal in the file that
    never called Add-CapabilityMiss, so the run exited 0 and onboard.exe (which
    branches on the exit code alone) showed "DONE: SEND THESE TWO VALUES TO
    YOUR ADMIN" to a machine with no project drive at all: no Resolve path
    resolves, lane B has nowhere to land, and the editor has just told their
    admin they are set up.

    Two halves are checked here. The refusal block itself is top-level script
    code that cannot be run without a machine in a particular state, so it is
    read with the PowerShell parser: the assertion is that the block calls
    Add-CapabilityMiss at all. The message is a pure function precisely so the
    other half CAN be run, and both of its cases are pinned -- they are
    different advice (one the editor can act on in Explorer, one they cannot),
    and neither may drop the drive letter, which is site data.

    Run:  powershell -NoProfile -ExecutionPolicy Bypass -File installer\tests\Test-ForeignDriveMiss.ps1
    Exits 1 on any failure.
#>
$ErrorActionPreference = "Stop"
$InstallerDir = Split-Path -Parent $PSScriptRoot
$BootstrapPath = Join-Path $InstallerDir "windows_bootstrap.ps1"
if (-not (Test-Path -LiteralPath $BootstrapPath)) {
    Write-Host "FAIL: no windows_bootstrap.ps1 at $BootstrapPath" -ForegroundColor Red
    exit 1
}

$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $BootstrapPath, [ref]$tokens, [ref]$errors)
if ($errors -and $errors.Count -gt 0) {
    Write-Host "FAIL: windows_bootstrap.ps1 does not parse: $($errors[0].Message)" -ForegroundColor Red
    exit 1
}

$fail = 0
function Ok  { param([string]$m) Write-Host "  PASS  $m" -ForegroundColor DarkGreen }
function Bad { param([string]$m) Write-Host "  FAIL  $m" -ForegroundColor Red; $script:fail++ }
function Check {
    param([string]$Label, [bool]$Condition)
    if ($Condition) { Ok $Label } else { Bad $Label }
}

# -- half 1: the refusal reaches the capability channel ---------------------
# The block is `if ($script:PIsForeign) { ... }` at the top level of the
# script. Find every such statement and require an Add-CapabilityMiss call
# somewhere inside the one that also prints the "already mapped to" error, so
# a second, unrelated PIsForeign branch (the Explorer-label skip further down)
# cannot satisfy this by accident.
$ifs = $ast.FindAll({
    param($node)
    $node -is [System.Management.Automation.Language.IfStatementAst]
}, $true)
$refusal = $ifs | Where-Object {
    $_.Extent.Text -match '\$script:PIsForeign' -and $_.Extent.Text -match 'is already mapped to'
} | Select-Object -First 1
if (-not $refusal) {
    Write-Host "FAIL: could not find the PIsForeign refusal block -- was it renamed?" -ForegroundColor Red
    exit 1
}
$calls = $refusal.FindAll({
    param($node)
    $node -is [System.Management.Automation.Language.CommandAst]
}, $true) | ForEach-Object { $_.GetCommandName() }
Check "the foreign-drive refusal calls Add-CapabilityMiss (exit 3, not exit 0)" `
    ([bool]($calls -contains 'Add-CapabilityMiss'))

# -- half 2: the message itself ---------------------------------------------
$fn = $ast.FindAll({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst]
}, $true) | Where-Object { $_.Name -eq 'New-ForeignDriveMiss' } | Select-Object -First 1
if (-not $fn) {
    Write-Host "FAIL: windows_bootstrap.ps1 no longer defines New-ForeignDriveMiss" -ForegroundColor Red
    exit 1
}
Invoke-Expression $fn.Extent.Text

# A site that is not on P: -- the drive letter is site data (canonical_prefix),
# so nothing here may hardcode one (2026-08-17, COMMERCIAL_READINESS item 11).
$mapped = New-ForeignDriveMiss -DriveRoot "W:" -Target "\\nas\Pool\Tree"
$undetermined = New-ForeignDriveMiss -DriveRoot "W:" -Undetermined

Check "the mapped case names the drive"            ($mapped -like "*W:*")
Check "the mapped case names what holds it"        ($mapped -like "*\\nas\Pool\Tree*")
Check "the mapped case says Resolve cannot find the tree" ($mapped -match "(?i)resolve")
Check "the mapped case says how to clear it"       ($mapped -match "(?i)disconnect")
Check "the mapped case names the other role"       ($mapped -match "(?i)PHYSICALLY CONNECTED")
Check "the mapped case says re-run"                ($mapped -match "(?i)re-run")

Check "could-not-determine is different advice"    ($undetermined -ne $mapped)
Check "could-not-determine names the drive"        ($undetermined -like "*W:*")
Check "could-not-determine does not blame a target that was never read" `
    ($undetermined -notmatch "(?i)already mapped to")
Check "could-not-determine says sign out and back in" ($undetermined -match "(?i)sign out")

# House rule 2026-08-18: no em dash in anything an editor reads. Both of these
# land in the wizard's NOT-READY list verbatim.
foreach ($pair in @(@("mapped", $mapped), @("undetermined", $undetermined))) {
    Check "no em dash in the $($pair[0]) message" (-not $pair[1].Contains([char]0x2014))
}

# The wizard finds these by the marker Add-CapabilityMiss prints, one line per
# miss (steps.CAPABILITY_MARKER). A message with a newline in it would show as
# a truncated warning on the finish page.
foreach ($pair in @(@("mapped", $mapped), @("undetermined", $undetermined))) {
    Check "the $($pair[0]) message is a single line" (-not ($pair[1] -match "[\r\n]"))
}

if ($fail -gt 0) {
    Write-Host "FAILED: $fail check(s)" -ForegroundColor Red
    exit 1
}
Write-Host "OK: foreign tree drive is a capability miss" -ForegroundColor Green
exit 0
