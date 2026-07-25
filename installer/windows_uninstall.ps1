#requires -Version 5.1
<#
.SYNOPSIS
    Uninstall CCSync (companion + Syncthing autostart + drive mapping) from an
    editor's Windows machine.

.DESCRIPTION
    Reverses what installer/windows_bootstrap.ps1 sets up. Two modes:

      (default) -- remove the CCSync SOFTWARE but KEEP the editor's identity
        and settings, so a reinstall is painless: the Syncthing device ID and
        the rclone SSH key survive, so the admin does NOT have to re-approve
        the device or re-issue a key. Removes: running processes, the three
        autostart entries, the P: drive mapping, and the program binaries
        under %LOCALAPPDATA%\ccsync\bin.

      -Full -- wipe everything, including the Syncthing config (device
        identity) and the ~/.ccsync settings/log. After this the machine is a
        clean slate; a reinstall produces a NEW Syncthing device ID that the
        admin must accept again (server/accept_device.py) before lane C syncs.

    Never uninstalls Tailscale / rclone / Syncthing that were installed as
    system packages (winget/scoop) -- those may be shared with other tools;
    remove them from "Apps & features" yourself if wanted. The rclone SSH key
    in ~/.ssh is never deleted (shared location); -Full just notes it.

    Every step is guarded and idempotent -- safe to re-run. -DryRun prints
    what it would do and touches nothing.

.PARAMETER Full
    Also remove the Syncthing identity and ~/.ccsync settings (clean slate).

.PARAMETER DryRun
    Report actions without performing them.

.EXAMPLE
    .\windows_uninstall.ps1            # keep identity, ready to reinstall

.EXAMPLE
    .\windows_uninstall.ps1 -Full      # remove everything
#>
[CmdletBinding()]
param(
    [switch]$Full,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

function Write-Step { param([string]$m) Write-Host "[uninstall] $m" }
function Write-Skip { param([string]$m) Write-Host "[uninstall] (skip) $m" -ForegroundColor DarkGray }
function Write-Warn2 { param([string]$m) Write-Host "[uninstall] WARNING: $m" -ForegroundColor Yellow }

$RunKeyPath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
$CcsyncLocal = "$env:LOCALAPPDATA\ccsync"
$BinDir = "$CcsyncLocal\bin"
$SyncthingHome = "$CcsyncLocal\syncthing-config"
$CcsyncProfile = "$env:USERPROFILE\.ccsync"

Write-Step "mode: $(if ($Full) { 'FULL (wipes identity + settings)' } else { 'keep identity + settings' })"
if ($DryRun) { Write-Step "DRY RUN -- nothing will be changed" }

# --- 1. stop running processes --------------------------------------------
foreach ($procName in @("ccsync-companion", "syncthing")) {
    $procs = Get-Process -Name $procName -ErrorAction SilentlyContinue
    if ($procs) {
        if ($DryRun) { Write-Step "[dry-run] would stop process: $procName ($($procs.Count))" }
        else {
            $procs | Stop-Process -Force -ErrorAction SilentlyContinue
            Write-Step "stopped process: $procName"
        }
    }
    else { Write-Skip "process not running: $procName" }
}
# The repo-from-source companion runs as pythonw launcher.py; stop those too.
$pyw = Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and $_.CommandLine -match "launcher\.py" }
if ($pyw) {
    if ($DryRun) { Write-Step "[dry-run] would stop $($pyw.Count) source-mode companion (pythonw launcher.py)" }
    else {
        $pyw | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
        Write-Step "stopped source-mode companion (pythonw launcher.py)"
    }
}

# --- 2. autostart entries -------------------------------------------------
$runEntries = @("CCSyncCompanion", "CCSyncSyncthing", "CCSyncSubstP")
foreach ($name in $runEntries) {
    $exists = $null
    try { $exists = (Get-ItemProperty -Path $RunKeyPath -Name $name -ErrorAction SilentlyContinue).$name } catch {}
    if ($exists) {
        if ($DryRun) { Write-Step "[dry-run] would remove autostart: $RunKeyPath\$name" }
        else {
            Remove-ItemProperty -Path $RunKeyPath -Name $name -ErrorAction SilentlyContinue
            Write-Step "removed autostart: $name"
        }
    }
    else { Write-Skip "no autostart entry: $name" }
}

# scheduled-task variant of the P: mapping (used when bootstrap had admin rights)
$task = Get-ScheduledTask -TaskName "CCSync-SubstP" -ErrorAction SilentlyContinue
if ($task) {
    if ($DryRun) { Write-Step "[dry-run] would unregister scheduled task: CCSync-SubstP" }
    else {
        try { Unregister-ScheduledTask -TaskName "CCSync-SubstP" -Confirm:$false -ErrorAction Stop; Write-Step "unregistered scheduled task: CCSync-SubstP" }
        catch { Write-Warn2 "could not unregister task CCSync-SubstP: $($_.Exception.Message)" }
    }
}
else { Write-Skip "no scheduled task: CCSync-SubstP" }

# --- 3. P: drive mapping --------------------------------------------------
if (Test-Path "P:\") {
    if ($DryRun) { Write-Step "[dry-run] would unmap P:" }
    else {
        # subst and net use are separate mechanisms; try both, ignore errors.
        & cmd /c "subst P: /D" 2>$null
        & cmd /c "net use P: /delete /y" 2>$null
        Write-Step "unmapped P: (if it was mapped)"
    }
}
else { Write-Skip "P: not mapped" }

# --- 4. program binaries --------------------------------------------------
if (Test-Path -LiteralPath $BinDir) {
    if ($DryRun) { Write-Step "[dry-run] would delete $BinDir (rclone, syncthing, companion exe)" }
    else {
        Remove-Item -LiteralPath $BinDir -Recurse -Force -ErrorAction SilentlyContinue
        Write-Step "removed program binaries: $BinDir"
    }
}
else { Write-Skip "no bin dir: $BinDir" }

# --- 5. identity + settings (kept unless -Full) ---------------------------
if ($Full) {
    foreach ($dir in @($CcsyncLocal, $CcsyncProfile)) {
        if (Test-Path -LiteralPath $dir) {
            if ($DryRun) { Write-Step "[dry-run] would delete $dir" }
            else {
                Remove-Item -LiteralPath $dir -Recurse -Force -ErrorAction SilentlyContinue
                Write-Step "removed $dir"
            }
        }
        else { Write-Skip "already absent: $dir" }
    }
    Write-Warn2 "FULL uninstall: the Syncthing device identity is gone. A reinstall will generate a NEW device ID -- send it to the admin so they can re-approve it (server/accept_device.py) before lane C syncs again."
    $sshKey = "$env:USERPROFILE\.ssh\ccsync_ed25519"
    if (Test-Path -LiteralPath $sshKey) {
        Write-Step "NOTE: the rclone SSH key remains at $sshKey (left in place -- delete it manually if you want it gone; the admin would then re-run setup_editor_account.py)."
    }
}
else {
    if (Test-Path -LiteralPath $SyncthingHome) {
        Write-Step "KEPT Syncthing identity: $SyncthingHome (reinstall reuses the same device ID -- no admin re-approval needed)"
    }
    if (Test-Path -LiteralPath $CcsyncProfile) {
        Write-Step "KEPT settings: $CcsyncProfile (config.toml, state)"
    }
    Write-Step "run with -Full to also remove the identity and settings."
}

Write-Host ""
Write-Host "=================================================================="
Write-Step "CCSync uninstall complete$(if ($DryRun) { ' (dry run -- nothing changed)' })."
Write-Step "Tailscale / rclone / Syncthing installed as system packages were left alone; remove them from Apps & features if wanted."
Write-Host "=================================================================="
