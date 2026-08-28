<#
.SYNOPSIS
    Table tests for windows_bootstrap.ps1's OPS-7 wrong-profile refusal and
    its UX-14 low-space warning (resilience sweep 2026-08-28).

.DESCRIPTION
    Test-ConsoleUserMismatch decides whether the whole install is refused, so
    two things have to be exactly right: a domain prefix or a UPN suffix is
    NOT a difference (DOMAIN\alex, alex@corp and alex are one person, and
    the two probes report them in different shapes), and an UNKNOWN console
    user says nothing at all -- refusing on "could not check" would lock
    somebody out of their own machine on a locked or RDP session.

    Get-LowSpaceWarning is the opposite: it must never refuse, and it must
    never invent a figure it could not measure (-1 = "df said nothing").

    Both are pure string/number in, string out, precisely so they can be
    checked here. They live inside windows_bootstrap.ps1 rather than in
    drive_mapping.ps1 because nothing else uses them; this extracts them with
    the PowerShell parser instead of dot-sourcing the script, which would run
    the installer.

    Run:  powershell -NoProfile -ExecutionPolicy Bypass -File installer\tests\Test-ConsoleUser.ps1
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
$LowSpaceWarnBytes = 200GB
foreach ($name in @('Get-BareAccountName', 'Test-ConsoleUserMismatch', 'Get-LowSpaceWarning')) {
    # FindAll + Where-Object rather than a closing predicate: PS 5.1's Find()
    # takes a scriptblock that cannot see $name without GetNewClosure games.
    $fn = $ast.FindAll({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst]
    }, $true) | Where-Object { $_.Name -eq $name } | Select-Object -First 1
    if (-not $fn) {
        Write-Host "FAIL: windows_bootstrap.ps1 no longer defines $name" -ForegroundColor Red
        exit 1
    }
    Invoke-Expression $fn.Extent.Text
}

$fail = 0
function Ok  { param([string]$m) Write-Host "  PASS  $m" -ForegroundColor DarkGreen }
function Bad { param([string]$m) Write-Host "  FAIL  $m" -ForegroundColor Red; $script:fail++ }
function Check {
    param([string]$Label, [string]$Expected, [string]$Actual)
    if ($Expected -ceq $Actual) { Ok $Label } else { Bad "$Label`: got '$Actual' want '$Expected'" }
}

# --- Get-BareAccountName ---------------------------------------------------
Check "a domain prefix is stripped"  "alex" (Get-BareAccountName "STUDIO\alex")
Check "a UPN suffix is stripped"     "alex" (Get-BareAccountName "alex@studio.local")
Check "a bare name survives"         "alex" (Get-BareAccountName "  alex ")
Check "nothing in, nothing out"      ""     (Get-BareAccountName "")

# --- Test-ConsoleUserMismatch ---------------------------------------------
$refusal = Test-ConsoleUserMismatch -ConsoleUser "STUDIO\leso" -RunningUser "administrator"
if ($refusal -like "You are running as administrator but leso is signed in.*per-user*administrator rights*") {
    Ok "a genuine mismatch names both accounts and says it is per-user"
} else {
    Bad "the refusal wording changed: '$refusal'"
}
# The dashes as code points, so this file itself stays pure ASCII (PS 5.1
# reads an unmarked .ps1 in the ANSI codepage and would mangle a literal one).
$DashClass = "[$([char]0x2014)$([char]0x2013)]"
if ($refusal -match $DashClass) { Bad "the refusal contains an em/en dash" } else { Ok "the refusal has no em dash" }

Check "the same account, domain-qualified" "" (Test-ConsoleUserMismatch -ConsoleUser "STUDIO\alex" -RunningUser "alex")
Check "the same account, different case"   "" (Test-ConsoleUserMismatch -ConsoleUser "STUDIO\Alex" -RunningUser "alex")
Check "an unknown console user says nothing" "" (Test-ConsoleUserMismatch -ConsoleUser "" -RunningUser "alex")
Check "an unknown running user says nothing" "" (Test-ConsoleUserMismatch -ConsoleUser "STUDIO\alex" -RunningUser "")

# --- Get-LowSpaceWarning ---------------------------------------------------
Check "plenty of room says nothing" "" (Get-LowSpaceWarning -FreeBytes ([long]1TB))
Check "exactly at the floor"        "" (Get-LowSpaceWarning -FreeBytes ([long]200GB))
Check "an unmeasurable volume says nothing" "" (Get-LowSpaceWarning -FreeBytes ([long](-1)))
Check "41 GB free" `
    "This drive has 41 GB free. Synced proxies for one project are typically 50 to 300 GB." `
    (Get-LowSpaceWarning -FreeBytes ([long]41GB))

# --- the call sites are still wired ---------------------------------------
$src = Get-Content -Raw $BootstrapPath
if ($src -match 'Test-ConsoleUserMismatch -ConsoleUser \$ConsoleUserName') {
    Ok "the bootstrap still runs the console-user check"
} else {
    Bad "nothing in windows_bootstrap.ps1 calls Test-ConsoleUserMismatch any more"
}
if ($src -match 'Get-LowSpaceWarning -FreeBytes \$LocalRootFreeBytes') {
    Ok "the bootstrap still warns about a full sync root"
} else {
    Bad "nothing in windows_bootstrap.ps1 calls Get-LowSpaceWarning any more"
}

Write-Host ""
if ($fail -gt 0) {
    Write-Host "$fail FAILED" -ForegroundColor Red
    exit 1
}
Write-Host "all console-user / low-space cases pass" -ForegroundColor Green
