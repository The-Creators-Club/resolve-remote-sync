#requires -Version 5.1
<#
.SYNOPSIS
    Upgrade an existing CCSync install to a newer companion build, in place.

.DESCRIPTION
    For a machine that already ran installer/windows_bootstrap.ps1. Swaps in
    the new companion and leaves EVERYTHING else alone -- the Syncthing device
    identity, the rclone SSH key + config, the P: drive mapping, and the
    editor's settings all survive, so there is nothing for the admin to
    re-approve. Steps:

      1. Stop the running companion (packaged exe or source-mode pythonw).
      2. Copy the new ccsync-companion.exe into %LOCALAPPDATA%\ccsync\bin.
      3. Re-register the companion autostart (points at that exe).
      4. Add any config keys the new version needs that the file is missing
         (never overwrites existing values) -- and set dashboard_token if you
         pass -DashboardToken.
      5. Relaunch the companion.

    Syncthing, rclone, Tailscale, and the drive mapping are untouched. Safe to
    re-run; -DryRun changes nothing.

.PARAMETER CompanionExe
    Path to the new ccsync-companion.exe. Defaults to the copy sitting next to
    this script (i.e. run this from inside the CC_Sync package folder).

.PARAMETER DashboardToken
    If given, sets dashboard_token in the config (needed for fleet reporting +
    project selection). Omit to leave the existing value alone.

.PARAMETER DryRun
    Report actions without performing them.

.EXAMPLE
    .\windows_upgrade.ps1 -DashboardToken 5f0c7dd7ab0343509e5730ce5198967f2176ad8ec700bf1a
#>
[CmdletBinding()]
param(
    [string]$CompanionExe = "",
    [string]$DashboardToken = "",
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

function Write-Step { param([string]$m) Write-Host "[upgrade] $m" }
function Write-Skip { param([string]$m) Write-Host "[upgrade] (skip) $m" -ForegroundColor DarkGray }
function Write-Warn2 { param([string]$m) Write-Host "[upgrade] WARNING: $m" -ForegroundColor Yellow }

$RunKeyPath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
$BinDir = "$env:LOCALAPPDATA\ccsync\bin"
$CompanionExePath = "$BinDir\ccsync-companion.exe"
$ConfigPath = "$env:USERPROFILE\.ccsync\config.toml"
$DefaultDashboardUrl = "http://100.71.216.3:8480"

# --- locate the new exe ---------------------------------------------------
if (-not $CompanionExe) {
    $CompanionExe = Join-Path $PSScriptRoot "ccsync-companion.exe"
}
if (-not (Test-Path -LiteralPath $CompanionExe)) {
    Write-Warn2 "new companion exe not found at: $CompanionExe"
    Write-Warn2 "run this from inside the CC_Sync package folder, or pass -CompanionExe <path>."
    exit 1
}
$srcInfo = Get-Item -LiteralPath $CompanionExe
Write-Step "new build: $CompanionExe ($([int]($srcInfo.Length/1KB)) KB, $($srcInfo.LastWriteTime))"
if ($DryRun) { Write-Step "DRY RUN -- nothing will be changed" }

# --- 1. stop the running companion ----------------------------------------
$stopped = $false
$procs = Get-Process -Name ccsync-companion -ErrorAction SilentlyContinue
if ($procs) {
    if ($DryRun) { Write-Step "[dry-run] would stop ccsync-companion ($($procs.Count))" }
    else { $procs | Stop-Process -Force -ErrorAction SilentlyContinue; $stopped = $true; Write-Step "stopped ccsync-companion" }
}
$pyw = Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and $_.CommandLine -match "launcher\.py" }
if ($pyw) {
    if ($DryRun) { Write-Step "[dry-run] would stop source-mode companion (pythonw launcher.py)" }
    else { $pyw | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }; $stopped = $true; Write-Step "stopped source-mode companion" }
}
if (-not $stopped -and -not $DryRun) { Write-Skip "companion was not running" }
if (-not $DryRun) { Start-Sleep -Milliseconds 800 }  # let the file handle release

# --- 2. copy the new exe into place ---------------------------------------
if ($DryRun) { Write-Step "[dry-run] would copy new exe -> $CompanionExePath" }
else {
    if (-not (Test-Path -LiteralPath $BinDir)) { New-Item -ItemType Directory -Path $BinDir -Force | Out-Null }
    Copy-Item -LiteralPath $CompanionExe -Destination $CompanionExePath -Force
    Write-Step "installed new companion: $CompanionExePath"
}

# --- 3. (re)register autostart --------------------------------------------
if ($DryRun) { Write-Step "[dry-run] would set autostart $RunKeyPath\CCSyncCompanion = $CompanionExePath" }
else {
    Set-ItemProperty -Path $RunKeyPath -Name "CCSyncCompanion" -Value $CompanionExePath
    Write-Step "autostart set: CCSyncCompanion -> $CompanionExePath"
}

# --- 4. non-destructive config migration ----------------------------------
if (-not (Test-Path -LiteralPath $ConfigPath)) {
    Write-Warn2 "no config at $ConfigPath -- run windows_bootstrap.ps1 to seed it, then re-run this."
}
else {
    $lines = @(Get-Content -LiteralPath $ConfigPath)
    $text = ($lines -join "`n")
    $added = @()

    function Test-Key { param([string]$key) return ($lines | Where-Object { $_ -match "^\s*$key\s*=" }).Count -gt 0 }

    if (-not (Test-Key "dashboard_url")) {
        $lines += "dashboard_url = `"$DefaultDashboardUrl`""
        $added += "dashboard_url (default $DefaultDashboardUrl)"
    }
    if ($DashboardToken) {
        # set/replace the token line explicitly
        if (Test-Key "dashboard_token") {
            $lines = $lines | ForEach-Object { if ($_ -match "^\s*dashboard_token\s*=") { "dashboard_token = `"$DashboardToken`"" } else { $_ } }
        }
        else { $lines += "dashboard_token = `"$DashboardToken`"" }
        $added += "dashboard_token (set from -DashboardToken)"
    }
    elseif (-not (Test-Key "dashboard_token")) {
        $lines += 'dashboard_token = ""'
        $added += "dashboard_token (blank -- fleet reporting stays off until you set it)"
    }
    # mode: default editor; only add if absent so a base rig's mode="base" is
    # kept. Harmless even if wrong: once the editor signs in, the dashboard's
    # role (DASH_ADMIN_USERS) overrides this static value entirely -- see
    # companion app.py's _apply_identity_role()/effective_mode().
    if (-not (Test-Key "mode")) {
        $lines += 'mode = "editor"'
        $added += "mode (editor)"
    }

    if ($added.Count -eq 0) {
        Write-Skip "config already has the new keys -- no changes"
    }
    elseif ($DryRun) {
        Write-Step "[dry-run] would add/update in ${ConfigPath}: $($added -join ', ')"
    }
    else {
        Set-Content -LiteralPath $ConfigPath -Value ($lines -join "`r`n") -Encoding UTF8
        Write-Step "config updated ($ConfigPath): $($added -join ', ')"
    }
}

# --- 5. relaunch ----------------------------------------------------------
if ($DryRun) { Write-Step "[dry-run] would relaunch $CompanionExePath" }
else {
    Start-Process -FilePath $CompanionExePath -WorkingDirectory $BinDir
    Write-Step "relaunched companion"
}

Write-Host ""
Write-Host "=================================================================="
Write-Step "Upgrade complete$(if ($DryRun) { ' (dry run -- nothing changed)' })."
Write-Step "Syncthing identity, rclone key, drive mapping, and settings were preserved."
if (-not $DashboardToken -and (Test-Path -LiteralPath $ConfigPath)) {
    $hasToken = (Get-Content -LiteralPath $ConfigPath | Where-Object { $_ -match '^\s*dashboard_token\s*=\s*"\S' }).Count -gt 0
    if (-not $hasToken) { Write-Warn2 "dashboard_token is blank -- fleet reporting + project selection are off. Re-run with -DashboardToken <value> (ask the admin) to enable them." }
}
Write-Host "=================================================================="
