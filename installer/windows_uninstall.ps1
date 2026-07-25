#requires -Version 5.1
<#
.SYNOPSIS
    Uninstall CCSync (companion + Syncthing autostart + drive mapping) from an
    editor's Windows machine.

.DESCRIPTION
    Removes the CCSync software this machine runs. It never touches your
    synced media: your Creators_Club folder and everything in it is left
    exactly as it is, in both modes. Two modes:

      (default) -- remove the CCSync app and its autostart entries, and keep
        your saved sign-in and Syncthing identity, so reinstalling is
        painless and Alex does not have to re-approve you. Removes: running
        processes, the three autostart entries, the P: drive mapping, and the
        program binaries under %LOCALAPPDATA%\ccsync\bin.

      -Full -- also remove your saved sign-in and Syncthing identity (a
        reinstall then needs Alex to re-approve you). Neither mode ever
        deletes your synced media in C:\Creators_Club, and neither mode
        deletes ~/.ccsync\state (the once-ever prompt answers and local
        caches -- see section 5).

    Never uninstalls Tailscale / rclone / Syncthing that were installed as
    system packages (winget/scoop) -- those may be shared with other tools;
    remove them from "Apps & features" yourself if wanted. The rclone SSH key
    in ~/.ssh is never deleted (shared location); -Full just notes it.

    Every step is guarded and idempotent -- safe to re-run. -DryRun prints
    what it would do and touches nothing.

.PARAMETER Full
    Also remove your saved sign-in and Syncthing identity (a reinstall then
    needs Alex to re-approve you). Your synced media is never touched, and
    ~/.ccsync\state is kept either way.

.PARAMETER DryRun
    Report actions without performing them.

.EXAMPLE
    .\windows_uninstall.ps1            # keep identity, ready to reinstall

.EXAMPLE
    .\windows_uninstall.ps1 -Full      # also drop the sign-in + device identity
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

Write-Step "mode: $(if ($Full) { 'FULL (also removes your sign-in + Syncthing identity)' } else { 'keep sign-in + settings' })"
Write-Step "your synced media is never touched by this script -- only the CCSync app itself."
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
# D-8: on the BASE rig, P:/T: are real SMB mappings of the NAS itself that
# this installer never created (onboarding/steps.py's build_cleanup_plan
# deliberately guards the same thing with unmount_p=(role=="editor")). This
# script has no -Role switch, so detect instead: a subst mapping has no
# DisplayRoot and is always ours (the bootstrap's fallback style); a net-use
# mapping is only ours if it points at our own loopback share. Anything
# else -- a net-use mapping to a real host -- must be left alone.
if (Test-Path "P:\") {
    $pDrive = $null
    try { $pDrive = Get-PSDrive -Name P -ErrorAction Stop } catch {}
    $displayRoot = $null
    if ($pDrive) { $displayRoot = $pDrive.DisplayRoot }
    $looksLikeOurs = [string]::IsNullOrWhiteSpace($displayRoot) -or
                     ($displayRoot -match '^\\\\localhost\\CCSync_P$')

    if (-not $looksLikeOurs) {
        Write-Skip "P: is mapped to '$displayRoot' -- not this installer's mapping (looks like a real NAS mapping, e.g. on the base rig). Leaving it alone; remove the share/label leftovers below only."
    }
    elseif ($DryRun) {
        Write-Step "[dry-run] would unmap P: ($(if ($displayRoot) { $displayRoot } else { 'subst mapping' }))"
    }
    else {
        # subst and net use are separate mechanisms; try both, ignore errors.
        # Redirect inside cmd -- a PowerShell-level 2>$null turns native
        # stderr into a NativeCommandError (fatal under EAP Stop).
        & cmd /c "subst P: /D >nul 2>&1"
        & cmd /c "net use P: /delete /y >nul 2>&1"
        Write-Step "unmapped P: (if it was mapped)"
    }
}
else { Write-Skip "P: not mapped" }

# the loopback share behind the labelled net-use mapping (needs admin)
$share = $null
try { $share = Get-SmbShare -Name "CCSync_P" -ErrorAction SilentlyContinue } catch {}
if ($share) {
    if ($DryRun) { Write-Step "[dry-run] would remove SMB share CCSync_P" }
    else {
        try {
            Remove-SmbShare -Name "CCSync_P" -Force -Confirm:$false -ErrorAction Stop
            Write-Step "removed SMB share CCSync_P"
        }
        # Targeted command, not "re-run this script elevated": an elevated
        # run of this script sees a DIFFERENT P: device map than the user's
        # own session, so the unmount above would silently do nothing there.
        catch { Write-Warn2 "could not remove the share CCSync_P: $($_.Exception.Message). Harmless leftover. To clear it, open an administrator PowerShell and run:  Remove-SmbShare -Name CCSync_P -Force" }
    }
}
else { Write-Skip "no SMB share: CCSync_P" }

# Explorer label leftovers. The MountPoints2 key is Windows' own per-user
# record of a mount point and carries more than our label (shell state,
# _CommentFromDesktopINI, ...) -- deleting the whole key recursively throws
# away data this installer never created. Remove only the ONE value we wrote.
$mpKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\MountPoints2\##localhost#CCSync_P"
if (Test-Path -LiteralPath $mpKey) {
    $hasLabel = $null
    try { $hasLabel = (Get-ItemProperty -LiteralPath $mpKey -Name "_LabelFromReg" -ErrorAction SilentlyContinue)._LabelFromReg } catch {}
    if ($null -eq $hasLabel) {
        Write-Skip "no _LabelFromReg value on $mpKey"
    }
    elseif ($DryRun) {
        Write-Step "[dry-run] would delete only the _LabelFromReg value under $mpKey (leaving the key itself)"
    }
    else {
        try {
            Remove-ItemProperty -LiteralPath $mpKey -Name "_LabelFromReg" -ErrorAction Stop
            Write-Step "removed the _LabelFromReg value under $mpKey (key left in place -- it is Windows', not ours)"
        }
        catch { Write-Warn2 "could not remove _LabelFromReg: $($_.Exception.Message)" }
    }
}
else { Write-Skip "no MountPoints2 entry for the CCSync_P mapping" }

# The legacy DriveIcons\P key WAS created wholesale by older installs (and
# never worked), so removing the key is correct there.
$driveIconsKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\DriveIcons\P"
if (Test-Path -LiteralPath $driveIconsKey) {
    if ($DryRun) { Write-Step "[dry-run] would delete $driveIconsKey" }
    else {
        try { Remove-Item -LiteralPath $driveIconsKey -Recurse -Force -ErrorAction Stop; Write-Step "removed $driveIconsKey" }
        catch { Write-Warn2 "could not remove ${driveIconsKey}: $($_.Exception.Message)" }
    }
}

# --- 4. program binaries --------------------------------------------------
if (Test-Path -LiteralPath $BinDir) {
    if ($DryRun) { Write-Step "[dry-run] would delete $BinDir (rclone, syncthing, companion exe)" }
    else {
        Remove-Item -LiteralPath $BinDir -Recurse -Force -ErrorAction SilentlyContinue
        Write-Step "removed program binaries: $BinDir"
    }
}
else { Write-Skip "no bin dir: $BinDir" }

# ...and the user PATH entry windows_bootstrap.ps1 added for it. Leaving a
# dangling PATH entry behind is what makes "uninstall then reinstall" produce
# a subtly different environment from a fresh machine.
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($null -eq $userPath) { $userPath = "" }
$pathParts = @($userPath -split ";")
$keptParts = @($pathParts | Where-Object { $_ -and ($_.TrimEnd("\") -ne $BinDir.TrimEnd("\")) })
if ($pathParts.Count -eq $keptParts.Count) {
    Write-Skip "$BinDir is not on the user PATH"
}
elseif ($DryRun) {
    Write-Step "[dry-run] would remove $BinDir from the user PATH"
}
else {
    try {
        [Environment]::SetEnvironmentVariable("Path", ($keptParts -join ";"), "User")
        Write-Step "removed $BinDir from the user PATH"
    }
    catch { Write-Warn2 "could not update the user PATH: $($_.Exception.Message)" }
}

# --- 5. identity + settings (kept unless -Full) ---------------------------
if ($Full) {
    if (Test-Path -LiteralPath $CcsyncLocal) {
        if ($DryRun) { Write-Step "[dry-run] would delete $CcsyncLocal" }
        else {
            Remove-Item -LiteralPath $CcsyncLocal -Recurse -Force -ErrorAction SilentlyContinue
            Write-Step "removed $CcsyncLocal"
        }
    }
    else { Write-Skip "already absent: $CcsyncLocal" }

    # ~/.ccsync loses config.toml, identity.json and the log -- but NOT
    # state\. That directory holds the questions this machine has already
    # answered once and for all: state\project_prompts.json is the
    # "Project '<X>' isn't set up on the server -- set it up now?" memory.
    # Deleting it makes every prompt the editor already dismissed come back
    # on the next install, which reads as "the fix didn't work" (that is
    # exactly how the Blackmagic Proxy Generator "New Doc" prompt kept
    # coming back; seen live 2026-07-25). It contains no identity, no
    # credentials and no media -- only local caches (lane filters,
    # selection) that regenerate themselves.
    if (Test-Path -LiteralPath $CcsyncProfile) {
        $keepNames = @("state")
        $doomed = @(Get-ChildItem -LiteralPath $CcsyncProfile -Force -ErrorAction SilentlyContinue |
            Where-Object { $keepNames -notcontains $_.Name })
        foreach ($item in $doomed) {
            if ($DryRun) { Write-Step "[dry-run] would delete $($item.FullName)" }
            else { Remove-Item -LiteralPath $item.FullName -Recurse -Force -ErrorAction SilentlyContinue }
        }
        if (-not $DryRun) {
            Write-Step "removed your sign-in and settings from $CcsyncProfile ($($doomed.Count) item(s))"
        }
        if (Test-Path -LiteralPath (Join-Path $CcsyncProfile "state")) {
            Write-Step "KEPT $CcsyncProfile\state -- the prompts you have already answered stay answered after a reinstall (no identity or credentials live there)."
        }
    }
    else { Write-Skip "already absent: $CcsyncProfile" }
    Write-Warn2 "FULL uninstall: your saved sign-in and Syncthing device identity are gone. A reinstall generates a NEW device ID -- send it to Alex so he can re-approve this machine on the dashboard before anything syncs again. Your media was not touched."
    $sshKey = "$env:USERPROFILE\.ssh\ccsync_ed25519"
    if (Test-Path -LiteralPath $sshKey) {
        Write-Step "NOTE: the rclone SSH key remains at $sshKey (left in place -- delete it manually if you want it gone; the admin would then re-run setup_editor_account.py)."
    }
}
else {
    if (Test-Path -LiteralPath $SyncthingHome) {
        Write-Step "KEPT Syncthing identity: $SyncthingHome (reinstall reuses the same device ID -- no re-approval needed)"
    }
    if (Test-Path -LiteralPath $CcsyncProfile) {
        Write-Step "KEPT your sign-in and settings: $CcsyncProfile (config.toml, state)"
    }
    Write-Step "run with -Full to also remove your sign-in and Syncthing identity."
}

Write-Host ""
Write-Host "=================================================================="
Write-Step "CCSync uninstall complete$(if ($DryRun) { ' (dry run -- nothing changed)' })."
Write-Step "Tailscale / rclone / Syncthing installed as system packages were left alone; remove them from Apps & features if wanted."
Write-Host "=================================================================="
