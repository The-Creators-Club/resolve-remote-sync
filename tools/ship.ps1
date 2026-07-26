#requires -Version 5.1
<#
.SYNOPSIS
    One command to ship everything: deploy the dashboard, publish the
    companion + installer, upgrade this machine, verify.

.DESCRIPTION
    Wraps the whole release cycle that was previously four hand-typed
    commands plus environment-variable setup:

      1. DASHBOARD  python server\install_dashboard_app.py  (code-only
         deploy; compose-level changes still need --recreate by hand),
         then confirms /api/v1/health reports the repo's dashboard VERSION.
      2. PUBLISH    installer\build_editor_package.ps1 -RebuildExe
         -RebuildOnboard -Publish -MakeCurrent  (prompts once for your
         dashboard admin password).
      3. LOCAL      installer\windows_upgrade.ps1 with the exe just built,
         then tools\check_deploy_drift.ps1.

    Secrets come from user environment variables (set once with setx):
    TRUENAS_PW, DASH_REPORT_TOKEN, DASH_SESSION_SECRET, SYNCTHING_API_KEY.
    The script refuses to start with any of them missing rather than let
    install_dashboard_app.py fail halfway.

    Run it via tools\ship.cmd to skip the execution-policy dance.

.PARAMETER DashboardOnly
    Stop after step 1 (server-side template/API changes only).

.PARAMETER SkipLocalUpgrade
    Do steps 1-2 but leave this machine's companion alone.

.EXAMPLE
    .\tools\ship.cmd
.EXAMPLE
    .\tools\ship.cmd -DashboardOnly
#>
[CmdletBinding()]
param(
    [switch]$DashboardOnly,
    [switch]$SkipLocalUpgrade
)

# "Continue", not "Stop": the deploy script prints an SSH host-key WARNING to
# stderr, and PS 5.1 + Stop turns any native stderr line into a terminating
# NativeCommandError (see GOTCHAS.md section 2). Success is judged by exit
# codes below.
$ErrorActionPreference = "Continue"

function Write-Step { param([string]$m) Write-Host "[ship] $m" }
function Write-Fail { param([string]$m) Write-Host "[ship] FAILED: $m" -ForegroundColor Red }

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot
Write-Step "repo root: $RepoRoot"

# --- secrets present? -------------------------------------------------------
$missing = @()
foreach ($name in @("TRUENAS_PW", "DASH_REPORT_TOKEN", "DASH_SESSION_SECRET", "SYNCTHING_API_KEY")) {
    if (-not [Environment]::GetEnvironmentVariable($name)) { $missing += $name }
}
if ($missing.Count -gt 0) {
    Write-Fail "missing environment variable(s): $($missing -join ', ')"
    Write-Step "set each once with:  setx <NAME> `"<value>`"  then open a NEW window"
    exit 1
}

# --- repo versions (for the verify steps) ----------------------------------
$DashVersion = (Select-String -Path "dashboard\src\ccsync_dashboard\__init__.py" -Pattern 'VERSION\s*=\s*"([^"]+)"').Matches[0].Groups[1].Value
$CompanionVersion = (Select-String -Path "companion\src\ccsync_companion\config.py" -Pattern '^VERSION\s*=\s*"([^"]+)"').Matches[0].Groups[1].Value
Write-Step "repo says: dashboard v$DashVersion, companion v$CompanionVersion"

# --- fail fast if this companion version is already published ---------------
# The publish guard refuses to reuse a version number for different bytes --
# correctly -- but discovering that AFTER a five-minute PyInstaller build (and
# a password prompt) wasted a run twice on 2026-07-26. The download endpoint
# answers with the shared token, so check FIRST.
if (-not $DashboardOnly) {
    $pubCode = curl.exe -s -o NUL -w "%{http_code}" -H "X-CCSync-Token: $env:DASH_REPORT_TOKEN" `
        "http://192.168.0.102:8480/api/v1/companion/package/windows/$CompanionVersion"
    if ($pubCode -eq "200") {
        Write-Fail "companion v$CompanionVersion is ALREADY published on the server."
        Write-Step "bump VERSION in companion\src\ccsync_companion\config.py AND companion\pyproject.toml"
        Write-Step "(and, if onboard.exe's contents changed, `$InstallerVersion in installer\windows_bootstrap.ps1 + onboarding\steps.py), then re-run"
        exit 1
    }
}

# --- 1. dashboard -----------------------------------------------------------
Write-Host ""
Write-Step "--- step 1: deploy dashboard ---"
python server\install_dashboard_app.py
if ($LASTEXITCODE -ne 0) {
    Write-Fail "install_dashboard_app.py exited $LASTEXITCODE -- stopping"
    exit 1
}
Start-Sleep -Seconds 8
$live = ""
try {
    $health = curl.exe -s -H "X-CCSync-Token: $env:DASH_REPORT_TOKEN" "http://192.168.0.102:8480/api/v1/health" | ConvertFrom-Json
    $live = "$($health.version)"
}
catch {}
if ($live -eq $DashVersion) {
    Write-Step "dashboard is LIVE at v$live"
}
else {
    Write-Fail "dashboard /health says '$live', repo says '$DashVersion' -- investigate before continuing"
    exit 1
}
if ($DashboardOnly) {
    Write-Step "done (-DashboardOnly)"
    exit 0
}

# --- 2. publish companion + installer --------------------------------------
Write-Host ""
Write-Step "--- step 2: build + publish (password prompt is your DASHBOARD login) ---"
& powershell -NoProfile -ExecutionPolicy Bypass -File "installer\build_editor_package.ps1" `
    -RebuildExe -RebuildOnboard -Publish -MakeCurrent
if ($LASTEXITCODE -ne 0) {
    Write-Fail "build_editor_package.ps1 exited $LASTEXITCODE -- stopping before the local upgrade"
    exit 1
}
if ($SkipLocalUpgrade) {
    Write-Step "done (-SkipLocalUpgrade). Editors get the tray offer; this machine stays as-is."
    exit 0
}

# --- 3. upgrade this machine + verify --------------------------------------
Write-Host ""
Write-Step "--- step 3: upgrade this machine ---"
& powershell -NoProfile -ExecutionPolicy Bypass -File "installer\windows_upgrade.ps1" `
    -CompanionExe "companion\dist\ccsync-companion.exe"
if ($LASTEXITCODE -ne 0) {
    Write-Fail "windows_upgrade.ps1 exited $LASTEXITCODE"
    exit 1
}
& powershell -NoProfile -ExecutionPolicy Bypass -File "tools\check_deploy_drift.ps1"
Write-Host ""
Write-Step "ship complete. Editors' trays will offer v$CompanionVersion on their next report."
exit 0
