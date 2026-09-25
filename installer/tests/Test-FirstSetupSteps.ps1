<#
.SYNOPSIS
    Table test for windows_bootstrap.ps1's Get-FirstSetupSteps
    (ui-onboarding-11, bug hunt 2026-09-24 wave 2).

.DESCRIPTION
    The bootstrap's end banner listed "1. tailscale up  2. ssh-keygen ... send
    the .pub file  3. SIGN IN" as remaining manual steps on every run, and
    onboard.exe streams that banner into the install log an editor sends
    their admin. The wizard has done all three before it runs the script, so
    a reader of the log made and sent a second key. onboard.exe now sets
    CCSYNC_FROM_WIZARD=1 in the script's environment and the banner's first
    three steps come from this function.

    Extracted with the PowerShell parser rather than dot-sourcing the script,
    which would run the installer.

    Run:  powershell -NoProfile -ExecutionPolicy Bypass -File installer\tests\Test-FirstSetupSteps.ps1
    Exits 1 on any failure.
#>
$ErrorActionPreference = "Stop"
$InstallerDir = Split-Path -Parent $PSScriptRoot
$BootstrapPath = Join-Path $InstallerDir "windows_bootstrap.ps1"

$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $BootstrapPath, [ref]$tokens, [ref]$errors)
if ($errors -and $errors.Count -gt 0) {
    Write-Host "FAIL: windows_bootstrap.ps1 does not parse: $($errors[0].Message)" -ForegroundColor Red
    exit 1
}
$fn = $ast.FindAll({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst]
}, $true) | Where-Object { $_.Name -eq 'Get-FirstSetupSteps' } | Select-Object -First 1
if (-not $fn) {
    Write-Host "FAIL: windows_bootstrap.ps1 does not define Get-FirstSetupSteps" -ForegroundColor Red
    exit 1
}
Invoke-Expression $fn.Extent.Text

$fail = 0
function Ok  { param([string]$m) Write-Host "  PASS  $m" -ForegroundColor DarkGreen }
function Bad { param([string]$m) Write-Host "  FAIL  $m" -ForegroundColor Red; $script:fail++ }

$key = "C:\Users\ana\.ssh\ccsync_ed25519"

# --- a wizard run: nothing to repeat ---------------------------------------
$wizard = (Get-FirstSetupSteps -FromWizard $true -KeyFilePath $key) -join "`n"
if ($wizard -match 'ssh-keygen') { Bad "a wizard run still tells the editor to run ssh-keygen" } else { Ok "a wizard run does not ask for a second key" }
if ($wizard -match 'tailscale up') { Bad "a wizard run still says 'tailscale up'" } else { Ok "a wizard run does not ask to join Tailscale again" }
if ($wizard -match 'docs/EDITOR_SETUP') { Bad "a wizard run points at a docs folder the editor does not have" } else { Ok "a wizard run names no docs folder" }
if ($wizard -match 'DONE BY THE SETUP WIZARD') { Ok "a wizard run says who did steps 1-3" } else { Bad "a wizard run does not say steps 1-3 are done: '$wizard'" }

# --- a hand run: unchanged ----------------------------------------------------
$hand = (Get-FirstSetupSteps -FromWizard $false -KeyFilePath $key) -join "`n"
if ($hand -match [regex]::Escape("ssh-keygen -t ed25519 -f `"$key`"")) { Ok "a hand run still gives the ssh-keygen line with the key path" } else { Bad "a hand run lost its ssh-keygen line: '$hand'" }
if ($hand -match 'tailscale up' -and $hand -match 'SIGN IN') { Ok "a hand run still lists tailscale up and SIGN IN" } else { Bad "a hand run lost a step" }
if ($hand -match 'TrueNAS') { Bad "a hand run names a storage vendor" } else { Ok "a hand run names no storage vendor" }

# --- no em/en dash in either (owner rule; code points keep this file ASCII) --
$DashClass = "[$([char]0x2014)$([char]0x2013)]"
if (($wizard + $hand) -match $DashClass) { Bad "an em/en dash in the banner" } else { Ok "no em dash in the banner" }

# --- the banner is wired to the wizard's marker -------------------------------
$src = Get-Content -Raw $BootstrapPath
if ($src -match 'Get-FirstSetupSteps -FromWizard \(\$env:CCSYNC_FROM_WIZARD -eq "1"\)') {
    Ok "the end banner asks Get-FirstSetupSteps with the wizard's marker"
} else {
    Bad "the end banner no longer goes through Get-FirstSetupSteps with CCSYNC_FROM_WIZARD"
}

Write-Host ""
if ($fail -gt 0) {
    Write-Host "$fail FAILED" -ForegroundColor Red
    exit 1
}
Write-Host "all first-setup-steps cases pass" -ForegroundColor Green
