#requires -Version 5.1
<#
.SYNOPSIS
    Creators Club Sync -- Windows editor bootstrap.

.DESCRIPTION
    Idempotent setup for a remote Resolve editor's Windows machine:
      - Tailscale (winget, else prints download URL and exits)
      - rclone   (winget, else scoop, else direct zip to %LOCALAPPDATA%\ccsync\bin)
      - Syncthing (winget, else direct zip to the same bin folder)
      - the local sync root (-LocalRoot, default C:\Creators_Club)
      - a logon task that runs `subst P: <LocalRoot>`, run once now too
      - the Syncthing daemon: started now AND registered for autostart
      - an rclone remote config stanza template in %APPDATA%\rclone\rclone.conf
      - a seeded companion config at ~/.ccsync/config.toml
      - the companion app (ccsync-companion.exe) installed to P:\ (if
        -CompanionExeSource is given, or it's already there), registered for
        autostart, launched immediately, and confirmed still running a few
        seconds later
      - prints this machine's Syncthing device ID at the end

    Every step checks current state before acting and prints a line saying
    what it did or what it skipped, so this script is safe to re-run.

    This script does NOT run `tailscale up` (joining the tailnet) or
    generate SSH keys -- those are one-time interactive/manual steps, see
    docs/EDITOR_SETUP.md.

    ELEVATION: an elevated shell is preferred but NOT required. Registering
    the logon scheduled task needs admin rights; without them the script
    falls back to an HKCU Run entry that achieves the same thing, warns, and
    carries on. No step aborts the run.

.PARAMETER TailnetHost
    Tailnet hostname or IP of the NAS, e.g. "truenas.tailXXXX.ts.net" or a
    100.x.y.z address. Written into the rclone remote config stanza.

.PARAMETER EditorName
    This editor's TrueNAS username (matches what the admin set up via
    server/setup_editor_account.py). Lowercased automatically -- unix
    usernames are case-sensitive and a mismatch surfaces later as an opaque
    SSH auth error rather than anything pointing back at the typo.

.PARAMETER LocalRoot
    Local sync root. Defaults to C:\Creators_Club. Point this at a volume
    with plenty of headroom (video originals and proxies land here) -- see
    the free-space guidance in the onboarding docs.

.PARAMETER RemoteRoot
    Absolute path on the NAS under which project trees live. Must be
    absolute: the SFTP session lands in the editor's home directory, so a
    relative path would resolve under ~/ and silently miss the real tree.

.PARAMETER DriveLabel
    Explorer display name for the P: drive, default "TheCreatorsClub", so
    editors can tell it apart from their own drives at a glance. Set via the
    per-user DriveIcons registry key rather than `label`: P: is a subst
    drive, which has no volume label of its own, so `label P:` would rename
    the whole underlying volume (e.g. all of F:) instead.

.PARAMETER CompanionExePath
    Where ccsync-companion.exe should live and run from. Defaults to
    %LOCALAPPDATA%\ccsync\bin\ccsync-companion.exe -- the ONE canonical
    location every tool now agrees on (windows_upgrade.ps1, the onboarding
    wizard, and the companion's own self-upgrade all target the running
    exe's path). It used to default to the LocalRoot/P:\ tree root, which
    left machines with copies in two places and an autostart entry racing
    the subst logon task at boot; the onboarding wizard's clean-slate step
    removes those old copies.

.PARAMETER CompanionExeSource
    Optional path to a bundled ccsync-companion.exe to install to
    CompanionExePath if it isn't there yet (or is older/different -- e.g.
    onboard.exe passes its own bundled copy here). Leave blank to skip
    installing -- the exe must already exist at CompanionExePath, or
    autostart registration and the launch-now step below are skipped with
    a note instead of a hard failure.

.PARAMETER DryRun
    Print what would happen without installing anything or touching the
    filesystem/registry/scheduled tasks.

.EXAMPLE
    .\windows_bootstrap.ps1 -TailnetHost truenas.tailnet.ts.net -EditorName jsmith

.EXAMPLE
    .\windows_bootstrap.ps1 -TailnetHost 100.71.216.3 -EditorName jsmith -LocalRoot F:\Creators_Club
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$TailnetHost,

    [Parameter(Mandatory = $true)]
    [string]$EditorName,

    [string]$LocalRoot = "C:\Creators_Club",

    [string]$RemoteRoot = "/mnt/tank/TheCreatorsPool/Creators_Club",

    [string]$DriveLabel = "TheCreatorsClub",

    [string]$CompanionExePath = "$env:LOCALAPPDATA\ccsync\bin\ccsync-companion.exe",
    [string]$CompanionExeSource = "",

    # Sync dashboard (tailnet address is right for remote editors). The token
    # comes from the admin; without it reports/selection are rejected.
    [string]$DashboardUrl = "http://100.71.216.3:8480",
    [string]$DashboardToken = "",

    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

# PS 5.1 has no ternary/null-coalescing operators and no `&&`/`||` chaining --
# every branch below is written as a plain if/else.

function Write-Step {
    param([string]$Message)
    Write-Host "[ccsync] $Message"
}

function Write-Skip {
    param([string]$Message)
    Write-Host "[ccsync] SKIP: $Message" -ForegroundColor DarkGray
}

function Write-Warn2 {
    param([string]$Message)
    Write-Host "[ccsync] WARNING: $Message" -ForegroundColor Yellow
}

function Test-CommandExists {
    param([string]$Name)
    $cmd = Get-Command $Name -ErrorAction SilentlyContinue
    if ($cmd) { return $true }
    return $false
}

function Ensure-Dir {
    param([string]$Path)
    if (Test-Path -LiteralPath $Path) {
        Write-Skip "directory already exists: $Path"
    }
    else {
        if ($DryRun) {
            Write-Step "[dry-run] would create directory: $Path"
        }
        else {
            New-Item -ItemType Directory -Path $Path -Force | Out-Null
            Write-Step "created directory: $Path"
        }
    }
}

function Test-IsElevated {
    try {
        $id = [Security.Principal.WindowsIdentity]::GetCurrent()
        $principal = New-Object Security.Principal.WindowsPrincipal($id)
        return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    }
    catch {
        return $false
    }
}

# Register a hidden, no-elevation-required logon autostart via HKCU\...\Run.
# Goes through a .cmd (holds the real command line, normal quoting) launched
# by a one-line .vbs under wscript, which is what keeps the console window
# from flashing at every logon. Used directly for the Syncthing daemon, and
# as the fallback when Register-ScheduledTask is denied.
function Register-HiddenRunEntry {
    param(
        [string]$Name,        # base name for the .cmd/.vbs pair and the Run value
        [string]$CommandLine  # full command line to execute
    )
    $cmdPath = "$BinDir\$Name.cmd"
    $vbsPath = "$BinDir\$Name.vbs"
    $runKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"

    if ($DryRun) {
        Write-Step "[dry-run] would write $cmdPath and $vbsPath, and set $runKey\$Name"
        return $true
    }

    $cmdBody = "@echo off" + "`r`n" + $CommandLine + "`r`n"
    Set-Content -LiteralPath $cmdPath -Value $cmdBody -Encoding ASCII

    # VBS quoting: "" is a literal quote inside a VBS string literal.
    $vbsBody = "CreateObject(""WScript.Shell"").Run ""cmd /c """"$cmdPath"""""", 0, False"
    Set-Content -LiteralPath $vbsPath -Value $vbsBody -Encoding ASCII

    try {
        Set-ItemProperty -Path $runKey -Name $Name -Value "wscript.exe ""$vbsPath"""
        Write-Step "registered hidden autostart: $runKey\$Name"
        return $true
    }
    catch {
        Write-Warn2 "could not write autostart registry value ${Name}: $($_.Exception.Message)"
        return $false
    }
}

# TLS 1.2 for winget-less direct downloads on older Windows/.NET defaults.
try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
}
catch {
    Write-Warn2 "could not force TLS 1.2 on this .NET runtime; direct downloads may fail on older Windows"
}

# --------------------------------------------------------------------
# 0. Normalize / echo inputs
# --------------------------------------------------------------------
$EditorNameRaw = $EditorName
$EditorName = $EditorName.Trim().ToLowerInvariant()
if ($EditorName -cne $EditorNameRaw) {
    Write-Warn2 "normalized -EditorName '$EditorNameRaw' -> '$EditorName' (unix usernames are case-sensitive; a mismatch shows up later only as a generic SSH auth failure)"
}

if (-not $RemoteRoot.StartsWith("/")) {
    Write-Warn2 "-RemoteRoot '$RemoteRoot' is not absolute. The SFTP session starts in your home directory on the NAS, so a relative path resolves under ~/ and will not find the project tree. Prefix it with '/'."
}

$IsElevated = Test-IsElevated
Write-Step "configuring for editor '$EditorName', local root '$LocalRoot', NAS '$TailnetHost'"
if (-not $IsElevated) {
    Write-Step "running unelevated -- will fall back to an HKCU Run entry if scheduled-task registration is denied"
}

$BinDir = "$env:LOCALAPPDATA\ccsync\bin"
Ensure-Dir $BinDir

# --------------------------------------------------------------------
# 1. Tailscale
# --------------------------------------------------------------------
Write-Step "checking Tailscale..."
$tailscaleInstalled = $false
if (Test-CommandExists "tailscale") {
    $tailscaleInstalled = $true
}
elseif (Test-Path "$env:ProgramFiles\Tailscale\tailscale.exe") {
    $tailscaleInstalled = $true
}

if ($tailscaleInstalled) {
    Write-Skip "Tailscale already installed"
}
else {
    if (Test-CommandExists "winget") {
        if ($DryRun) {
            Write-Step "[dry-run] would run: winget install --id Tailscale.Tailscale -e --accept-source-agreements --accept-package-agreements"
        }
        else {
            Write-Step "installing Tailscale via winget..."
            winget install --id Tailscale.Tailscale -e --accept-source-agreements --accept-package-agreements
            if ($LASTEXITCODE -ne 0) {
                Write-Warn2 "winget install of Tailscale exited with code $LASTEXITCODE"
            }
            else {
                Write-Step "Tailscale installed"
            }
        }
    }
    else {
        Write-Warn2 "winget not available. Download and install Tailscale manually from https://tailscale.com/download/windows then re-run this script."
        exit 1
    }
}

# --------------------------------------------------------------------
# 2. rclone
# --------------------------------------------------------------------
Write-Step "checking rclone..."
$rclonePath = $null
if (Test-CommandExists "rclone") {
    $rclonePath = (Get-Command rclone).Source
}
elseif (Test-Path "$BinDir\rclone.exe") {
    $rclonePath = "$BinDir\rclone.exe"
}

if ($rclonePath) {
    Write-Skip "rclone already installed: $rclonePath"
}
else {
    $installed = $false
    if (Test-CommandExists "winget") {
        if ($DryRun) {
            Write-Step "[dry-run] would run: winget install --id Rclone.Rclone -e --accept-source-agreements --accept-package-agreements"
            $installed = $true
        }
        else {
            Write-Step "installing rclone via winget..."
            winget install --id Rclone.Rclone -e --accept-source-agreements --accept-package-agreements
            if ($LASTEXITCODE -eq 0) { $installed = $true }
            else { Write-Warn2 "winget install of rclone exited with code $LASTEXITCODE, trying next method" }
        }
    }
    if ((-not $installed) -and (Test-CommandExists "scoop")) {
        if ($DryRun) {
            Write-Step "[dry-run] would run: scoop install rclone"
            $installed = $true
        }
        else {
            Write-Step "installing rclone via scoop..."
            scoop install rclone
            if ($LASTEXITCODE -eq 0) { $installed = $true }
            else { Write-Warn2 "scoop install of rclone exited with code $LASTEXITCODE, falling back to direct download" }
        }
    }
    if (-not $installed) {
        $zipUrl = "https://downloads.rclone.org/rclone-current-windows-amd64.zip"
        $zipPath = "$env:TEMP\rclone-current-windows-amd64.zip"
        $extractDir = "$env:TEMP\rclone-extract"
        if ($DryRun) {
            Write-Step "[dry-run] would download $zipUrl to $zipPath, extract, and copy rclone.exe to $BinDir"
        }
        else {
            Write-Step "downloading rclone from $zipUrl ..."
            Invoke-WebRequest -Uri $zipUrl -OutFile $zipPath
            if (Test-Path $extractDir) { Remove-Item -Recurse -Force $extractDir }
            Expand-Archive -Path $zipPath -DestinationPath $extractDir -Force
            $exe = Get-ChildItem -Path $extractDir -Filter "rclone.exe" -Recurse | Select-Object -First 1
            if ($null -eq $exe) {
                Write-Warn2 "could not find rclone.exe inside the downloaded zip -- install rclone manually"
            }
            else {
                Copy-Item -Path $exe.FullName -Destination "$BinDir\rclone.exe" -Force
                Write-Step "installed rclone to $BinDir\rclone.exe"
            }
        }
    }
}

# Make sure BinDir is on this user's PATH (idempotent).
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($null -eq $userPath) { $userPath = "" }
if ($userPath -split ";" -contains $BinDir) {
    Write-Skip "$BinDir already on user PATH"
}
else {
    if ($DryRun) {
        Write-Step "[dry-run] would add $BinDir to user PATH"
    }
    else {
        $newPath = $BinDir
        if ($userPath.Length -gt 0) { $newPath = $userPath + ";" + $BinDir }
        [Environment]::SetEnvironmentVariable("Path", $newPath, "User")
        Write-Step "added $BinDir to user PATH (restart your terminal to pick it up)"
    }
}

# --------------------------------------------------------------------
# 3. Syncthing
# --------------------------------------------------------------------

# GitHub's /releases/latest/download/<name> alias only resolves when that
# EXACT filename exists in the release. Syncthing's assets are version-named
# (syncthing-windows-amd64-v2.1.2.zip), so the unversioned alias 404s. Two
# ways to learn the real name, API first, redirect-sniffing as a backstop
# (the unauthenticated API is rate-limited to 60 requests/hour per IP).
function Get-SyncthingZipUrl {
    $pattern = "syncthing-windows-amd64-*.zip"

    try {
        $release = Invoke-RestMethod -Uri "https://api.github.com/repos/syncthing/syncthing/releases/latest" `
            -Headers @{ "User-Agent" = "ccsync-bootstrap" } -TimeoutSec 30
        $asset = $release.assets | Where-Object { $_.name -like $pattern } | Select-Object -First 1
        if ($asset) {
            Write-Step "resolved Syncthing asset via GitHub API: $($asset.name)"
            return $asset.browser_download_url
        }
        Write-Warn2 "GitHub API returned no asset matching $pattern; trying redirect method"
    }
    catch {
        Write-Warn2 "GitHub API lookup failed ($($_.Exception.Message)); trying redirect method"
    }

    try {
        $resp = Invoke-WebRequest -Uri "https://github.com/syncthing/syncthing/releases/latest" `
            -UseBasicParsing -TimeoutSec 30
        $finalUrl = $resp.BaseResponse.ResponseUri.AbsoluteUri
        if ($finalUrl -match "/tag/(v[0-9][^/]*)$") {
            $tag = $Matches[1]
            Write-Step "resolved Syncthing version via release redirect: $tag"
            return "https://github.com/syncthing/syncthing/releases/download/$tag/syncthing-windows-amd64-$tag.zip"
        }
        Write-Warn2 "could not parse a version tag out of '$finalUrl'"
    }
    catch {
        Write-Warn2 "release redirect lookup failed: $($_.Exception.Message)"
    }

    return $null
}

Write-Step "checking Syncthing..."
$syncthingPath = $null
if (Test-CommandExists "syncthing") {
    $syncthingPath = (Get-Command syncthing).Source
}
elseif (Test-Path "$BinDir\syncthing.exe") {
    $syncthingPath = "$BinDir\syncthing.exe"
}
elseif (Test-Path "$env:ProgramFiles\Syncthing\syncthing.exe") {
    $syncthingPath = "$env:ProgramFiles\Syncthing\syncthing.exe"
}

if ($syncthingPath) {
    Write-Skip "Syncthing already installed: $syncthingPath"
}
else {
    $installed = $false
    if (Test-CommandExists "winget") {
        if ($DryRun) {
            Write-Step "[dry-run] would run: winget install --id Syncthing.Syncthing -e --accept-source-agreements --accept-package-agreements"
            $installed = $true
        }
        else {
            Write-Step "installing Syncthing via winget..."
            winget install --id Syncthing.Syncthing -e --accept-source-agreements --accept-package-agreements
            if ($LASTEXITCODE -eq 0) { $installed = $true }
            else { Write-Warn2 "winget install of Syncthing exited with code $LASTEXITCODE, falling back to direct download" }
        }
    }
    if (-not $installed) {
        if ($DryRun) {
            Write-Step "[dry-run] would resolve the latest syncthing-windows-amd64-<version>.zip via the GitHub API, download, extract, and copy syncthing.exe to $BinDir"
        }
        else {
            $zipUrl = Get-SyncthingZipUrl
            if ($null -eq $zipUrl) {
                Write-Warn2 "could not determine a Syncthing download URL -- install Syncthing manually from https://syncthing.net/downloads/ and re-run this script"
            }
            else {
                $zipPath = "$env:TEMP\syncthing-windows-amd64.zip"
                $extractDir = "$env:TEMP\syncthing-extract"
                Write-Step "downloading Syncthing from $zipUrl ..."
                Invoke-WebRequest -Uri $zipUrl -OutFile $zipPath
                if (Test-Path $extractDir) { Remove-Item -Recurse -Force $extractDir }
                Expand-Archive -Path $zipPath -DestinationPath $extractDir -Force
                $exe = Get-ChildItem -Path $extractDir -Filter "syncthing.exe" -Recurse | Select-Object -First 1
                if ($null -eq $exe) {
                    Write-Warn2 "could not find syncthing.exe inside the downloaded zip -- install Syncthing manually"
                }
                else {
                    Copy-Item -Path $exe.FullName -Destination "$BinDir\syncthing.exe" -Force
                    Write-Step "installed Syncthing to $BinDir\syncthing.exe"
                    $syncthingPath = "$BinDir\syncthing.exe"
                }
            }
        }
    }
}
if ($DryRun -and (-not $syncthingPath)) {
    $syncthingPath = "$BinDir\syncthing.exe"
}

# --------------------------------------------------------------------
# 4. Local sync root
# --------------------------------------------------------------------
$CCRoot = $LocalRoot
Ensure-Dir $CCRoot

# --------------------------------------------------------------------
# 5. Logon task: subst P: <LocalRoot> -- TEAR DOWN, then recreate
# --------------------------------------------------------------------
# Always tear down whatever mapping/autostart exists and recreate it fresh.
# The old skip-if-anything-exists behavior had two live failure modes: a
# machine bootstrapped unelevated kept its Run-entry fallback forever (never
# upgraded to the proper task even when re-run elevated), and an SMB-mapped
# P: (net use) is invisible to `subst`, so the old detection concluded "not
# mapped" and then failed to map over it.
#
# Register-ScheduledTask needs admin rights when a -Principal is supplied.
# The documented launch path ("Run with PowerShell") is unelevated, so this
# is the common case, not the exception -- it must warn and continue rather
# than take the rest of the script down with $ErrorActionPreference=Stop.
$TaskName = "CCSync-SubstP"
$SubstCommand = "subst P: $CCRoot"
$RunKeyPath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
$substFallbackName = "CCSyncSubstP"

if ($DryRun) {
    Write-Step "[dry-run] would remove any existing '$TaskName' task / '$substFallbackName' Run entry, unmount P: (subst /D + net use /delete), then re-register the logon task and run '$SubstCommand'"
}
else {
    # -- tear down: task, Run-entry fallback (+ its shim files), P: mapping --
    try {
        if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
            Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction Stop
            Write-Step "removed existing scheduled task '$TaskName'"
        }
    }
    catch {
        Write-Warn2 "could not remove existing task '$TaskName': $($_.Exception.Message) (re-run elevated to replace it)"
    }
    try {
        if ((Get-ItemProperty -Path $RunKeyPath -Name $substFallbackName -ErrorAction SilentlyContinue)) {
            Remove-ItemProperty -Path $RunKeyPath -Name $substFallbackName -ErrorAction Stop
            Write-Step "removed old '$substFallbackName' Run entry"
        }
    }
    catch {}
    foreach ($shim in @("$BinDir\$substFallbackName.cmd", "$BinDir\$substFallbackName.vbs")) {
        try { Remove-Item -LiteralPath $shim -Force -Confirm:$false -ErrorAction SilentlyContinue } catch {}
    }
    # Both unmap styles: subst for our own mapping, net use for a hand-made
    # SMB mapping subst can't see. Errors (not mapped) are expected noise.
    cmd /c "subst P: /D" 2>$null | Out-Null
    cmd /c "net use P: /delete /y" 2>$null | Out-Null

    # -- recreate: task (elevated) or Run-entry fallback, then map now --
    $taskRegistered = $false
    try {
        $action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c $SubstCommand"
        $trigger = New-ScheduledTaskTrigger -AtLogOn
        $principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive
        Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Force | Out-Null
        Write-Step "registered scheduled task '$TaskName'"
        $taskRegistered = $true
    }
    catch {
        Write-Warn2 "could not register scheduled task '$TaskName': $($_.Exception.Message)"
        Write-Warn2 "falling back to an HKCU Run entry (equivalent effect, no admin rights needed)"
    }
    if (-not $taskRegistered) {
        $okFallback = Register-HiddenRunEntry -Name $substFallbackName -CommandLine $SubstCommand
        if (-not $okFallback) {
            Write-Warn2 "P: will NOT be remapped automatically at logon. Re-run this script from an elevated PowerShell, or run '$SubstCommand' by hand after each reboot."
        }
    }

    subst P: $CCRoot
    if ($LASTEXITCODE -eq 0) {
        Write-Step "mapped P: -> $CCRoot"
    }
    else {
        Write-Warn2 "subst P: $CCRoot exited with code $LASTEXITCODE -- something may still have files open on the old P:"
    }
}

# --------------------------------------------------------------------
# 5b. Name the P: drive in Explorer
# --------------------------------------------------------------------
# `subst` drives inherit the underlying volume's label and have none of
# their own, so `label P: ...` would rename the whole host volume -- if
# LocalRoot is on F:, that renames all of F:. This per-user DriveIcons key
# changes only how Explorer *displays* P:, touches no volume, and needs no
# admin rights.
$DriveIconsKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\DriveIcons\P\DefaultLabel"
Write-Step "labelling the P: drive as '$DriveLabel' in Explorer..."
if ($DryRun) {
    Write-Step "[dry-run] would set $DriveIconsKey (default) = $DriveLabel"
}
else {
    try {
        $currentLabel = $null
        if (Test-Path -LiteralPath $DriveIconsKey) {
            $currentLabel = (Get-ItemProperty -LiteralPath $DriveIconsKey -ErrorAction SilentlyContinue).'(default)'
        }
        if ($currentLabel -eq $DriveLabel) {
            Write-Skip "P: already labelled '$DriveLabel' in Explorer"
        }
        else {
            New-Item -Path $DriveIconsKey -Force | Out-Null
            Set-ItemProperty -LiteralPath $DriveIconsKey -Name "(default)" -Value $DriveLabel
            Write-Step "labelled P: as '$DriveLabel'"
            # Explorer caches DriveIcons labels aggressively -- a live
            # SHChangeNotify broadcast is unreliable for this specific key in
            # practice (reported live: the label silently "did not take"
            # despite the registry write succeeding). Restarting explorer.exe
            # is the one method that reliably shows it immediately. Open
            # Explorer windows survive; the taskbar/desktop blinks out and
            # back for roughly a second.
            try {
                Get-Process -Name explorer -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction Stop
                Start-Sleep -Milliseconds 500
                Start-Process explorer.exe
                Write-Step "restarted Explorer so the new P: label shows immediately"
            }
            catch {
                Write-Warn2 "could not restart Explorer automatically: $($_.Exception.Message) -- log off and back on (or restart Explorer via Task Manager) to see the new P: label"
            }
        }
    }
    catch {
        Write-Warn2 "could not set the Explorer label for P:: $($_.Exception.Message) -- cosmetic only, everything else still works."
    }
}

# --------------------------------------------------------------------
# 6. Syncthing config, daemon autostart, and start-now
# --------------------------------------------------------------------
# Generating a config is not enough: without a running `syncthing serve`
# there is no REST API and lane C (audio/AE/subs/docs) never syncs at all.
$SyncthingHome = "$env:LOCALAPPDATA\ccsync\syncthing-config"

if ($DryRun) {
    Write-Step "[dry-run] would run: `"$syncthingPath`" generate --home=`"$SyncthingHome`" (if not already generated)"
    Write-Step "[dry-run] would register a hidden autostart running: `"$syncthingPath`" serve --no-browser --home=`"$SyncthingHome`""
    Write-Step "[dry-run] would start the Syncthing daemon now if it isn't already running"
}
else {
    if (-not (Test-Path -LiteralPath $SyncthingHome)) {
        Write-Step "generating Syncthing config at $SyncthingHome ..."
        & $syncthingPath generate --home="$SyncthingHome" | Out-Null
    }
    else {
        Write-Skip "Syncthing config already generated at $SyncthingHome"
    }

    $SyncthingServeCmd = "`"$syncthingPath`" serve --no-browser --home=`"$SyncthingHome`""
    $stRunName = "CCSyncSyncthing"
    $existingStRun = $null
    try {
        $existingStRun = (Get-ItemProperty -Path $RunKeyPath -Name $stRunName -ErrorAction SilentlyContinue).$stRunName
    }
    catch {
        $existingStRun = $null
    }

    if ($existingStRun) {
        Write-Skip "Syncthing autostart already registered: $RunKeyPath\$stRunName"
    }
    else {
        # HKCU Run (not a scheduled task) on purpose: never needs elevation,
        # so the daemon's autostart can't be the thing that fails to register.
        Register-HiddenRunEntry -Name $stRunName -CommandLine $SyncthingServeCmd | Out-Null
    }

    $stProc = Get-Process -Name "syncthing" -ErrorAction SilentlyContinue
    if ($stProc) {
        Write-Skip "Syncthing daemon already running (pid $($stProc[0].Id))"
    }
    else {
        try {
            Start-Process -FilePath $syncthingPath `
                -ArgumentList "serve", "--no-browser", "--home=$SyncthingHome" `
                -WindowStyle Hidden
            Write-Step "started the Syncthing daemon"
        }
        catch {
            Write-Warn2 "could not start the Syncthing daemon: $($_.Exception.Message)"
            Write-Warn2 "start it by hand with: $SyncthingServeCmd"
        }
    }
}

# --------------------------------------------------------------------
# 7. rclone remote config stanza
# --------------------------------------------------------------------
$RcloneConfDir = "$env:APPDATA\rclone"
$RcloneConfPath = "$RcloneConfDir\rclone.conf"
Ensure-Dir $RcloneConfDir

$RemoteName = "creators_club_sftp"
$KeyFilePath = "$env:USERPROFILE\.ssh\ccsync_ed25519"
$Stanza = @"
[$RemoteName]
type = sftp
host = $TailnetHost
user = $EditorName
port = 22
key_file = $KeyFilePath
shell_type = unix
"@

$hasSection = $false
if (Test-Path -LiteralPath $RcloneConfPath) {
    $existingConf = Get-Content -LiteralPath $RcloneConfPath -Raw
    if ($existingConf -match [Regex]::Escape("[$RemoteName]")) {
        $hasSection = $true
    }
}

if ($hasSection) {
    Write-Skip "rclone.conf already has a [$RemoteName] section: $RcloneConfPath"
}
else {
    if ($DryRun) {
        Write-Step "[dry-run] would append this stanza to $RcloneConfPath :"
        Write-Host $Stanza
    }
    else {
        Add-Content -LiteralPath $RcloneConfPath -Value "`r`n$Stanza`r`n"
        Write-Step "appended [$RemoteName] stanza to $RcloneConfPath"
    }
}

if (-not (Test-Path -LiteralPath $KeyFilePath)) {
    Write-Warn2 "SSH private key not found at $KeyFilePath -- generate a keypair (ssh-keygen -t ed25519 -f `"$KeyFilePath`"), send the .pub half to the admin for server/setup_editor_account.py, and this rclone remote will start working."
}

# --------------------------------------------------------------------
# 8. Companion config (seeded with what this script already knows)
# --------------------------------------------------------------------
# The companion's own first-run template leaves these blank, which silently
# yields a non-functional install -- notably `remote`, which must match the
# rclone remote name created above.
$CCSyncConfigDir = "$env:USERPROFILE\.ccsync"
$CCSyncConfigPath = "$CCSyncConfigDir\config.toml"
$LocalRootToml = $CCRoot -replace '\\', '\\'

if (Test-Path -LiteralPath $CCSyncConfigPath) {
    Write-Skip "companion config already exists: $CCSyncConfigPath"
    Write-Step "  confirm these values match, the companion will not fix them for you:"
    Write-Host "      editor_name = `"$EditorName`""
    Write-Host "      local_root  = `"$LocalRootToml`""
    Write-Host "      remote      = `"$RemoteName`""
    Write-Host "      remote_root = `"$RemoteRoot`""
}
else {
    $CompanionToml = @"
# ccsync-companion config -- seeded by windows_bootstrap.ps1.
# See companion/README.md for the full reference. Restart the companion
# after editing this file.

editor_name = "$EditorName"

# This machine's local copy of the project tree (P: maps here).
local_root = "$LocalRootToml"

# The shared-drive prefix used in Resolve's stored clip paths.
canonical_prefix = "P:\\"

# Must match the rclone remote name in %APPDATA%\rclone\rclone.conf.
remote = "$RemoteName"

# ABSOLUTE path on the NAS. The SFTP session starts in your home directory,
# so a relative value here would resolve under ~/ and miss the real tree.
remote_root = "$RemoteRoot"

# OPTIONAL. Lanes A and B replicate the whole local_root <-> remote_root
# tree, so every Projects/<year>/<series>/<project> folder syncs whatever
# these say. They only affect two things: active_project is the destination
# the popup fixer suggests for media you add from outside the tree, and
# projects pairs positionally with syncthing_folder_ids for lane C's
# folder-ID check. Example:
#   projects = ["Projects/2026/Creator Profiles/Season 1"]
#   active_project = "Projects/2026/Creator Profiles/Season 1"
projects = []
active_project = ""

poll_interval = 3
scan_interval_up = 300
scan_interval_down = 120
watch_debounce_seconds = 10
transfers = 4

syncthing_url = "http://127.0.0.1:8384"
syncthing_api_key = ""
syncthing_folder_ids = []

rclone_path = "rclone"

log_path = "~/.ccsync/companion.log"
log_level = "INFO"

# Sync dashboard: reporting, managed one-at-a-time sync, and the tray's
# "Open dashboard" link. Tailnet address; token from the admin.
dashboard_url = "$DashboardUrl"
dashboard_token = "$DashboardToken"
"@
    if ($DryRun) {
        Write-Step "[dry-run] would write seeded companion config to $CCSyncConfigPath"
    }
    else {
        Ensure-Dir $CCSyncConfigDir
        Set-Content -LiteralPath $CCSyncConfigPath -Value $CompanionToml -Encoding UTF8
        Write-Step "wrote seeded companion config: $CCSyncConfigPath"
        Write-Step "  the whole project tree syncs as-is; set active_project in that file only if you want popup-fixed media filed into a specific project."
    }
}

# --------------------------------------------------------------------
# 9. Companion: install (if a bundled source was given), autostart
#    registration, and launch-now with a liveness check
# --------------------------------------------------------------------
if ($CompanionExeSource) {
    if (-not (Test-Path -LiteralPath $CompanionExeSource)) {
        Write-Warn2 "-CompanionExeSource given but not found: $CompanionExeSource -- skipping install"
    }
    else {
        $needsCopy = -not (Test-Path -LiteralPath $CompanionExePath)
        if (-not $needsCopy) {
            # Cheap staleness check (size/mtime) rather than hashing -- good
            # enough to catch "bundled a newer build" without extra cost on
            # every idempotent re-run.
            $srcInfo = Get-Item -LiteralPath $CompanionExeSource
            $destInfo = Get-Item -LiteralPath $CompanionExePath
            $needsCopy = ($srcInfo.Length -ne $destInfo.Length) -or
                         ($srcInfo.LastWriteTimeUtc -gt $destInfo.LastWriteTimeUtc)
        }
        if (-not $needsCopy) {
            Write-Skip "companion app already up to date: $CompanionExePath"
        }
        elseif ($DryRun) {
            Write-Step "[dry-run] would copy $CompanionExeSource -> $CompanionExePath"
        }
        else {
            Copy-Item -LiteralPath $CompanionExeSource -Destination $CompanionExePath -Force
            Write-Step "installed companion app: $CompanionExePath"
        }
    }
}

Write-Step "checking companion app at $CompanionExePath..."
if (-not (Test-Path -LiteralPath $CompanionExePath)) {
    Write-Warn2 "companion exe not found at $CompanionExePath -- skipping autostart registration and launch. Install the companion app (or pass -CompanionExeSource) and re-run this script."
}
else {
    $RunValueName = "CCSyncCompanion"
    $existingValue = $null
    try {
        $existingValue = (Get-ItemProperty -Path $RunKeyPath -Name $RunValueName -ErrorAction SilentlyContinue).$RunValueName
    }
    catch {
        $existingValue = $null
    }

    if ($existingValue -eq $CompanionExePath) {
        Write-Skip "companion autostart already registered: $CompanionExePath"
    }
    else {
        if ($DryRun) {
            Write-Step "[dry-run] would set registry value $RunKeyPath\$RunValueName = $CompanionExePath"
        }
        else {
            Set-ItemProperty -Path $RunKeyPath -Name $RunValueName -Value $CompanionExePath
            Write-Step "registered companion autostart: $RunKeyPath\$RunValueName = $CompanionExePath"
        }
    }

    # Launch it now too -- autostart only takes effect at the NEXT logon;
    # an editor shouldn't have to log off/on (or hunt down the exe
    # themselves) just to get the tray icon up right after install.
    $companionProcName = [System.IO.Path]::GetFileNameWithoutExtension($CompanionExePath)
    $runningProc = Get-Process -Name $companionProcName -ErrorAction SilentlyContinue
    if ($runningProc) {
        Write-Skip "companion app already running (PID $($runningProc[0].Id))"
    }
    elseif ($DryRun) {
        Write-Step "[dry-run] would launch $CompanionExePath and verify it stays running"
    }
    else {
        try {
            $proc = Start-Process -FilePath $CompanionExePath -PassThru
            Write-Step "launched companion app (PID $($proc.Id)) -- watching to confirm it stays up..."
            Start-Sleep -Seconds 3
            $stillRunning = Get-Process -Id $proc.Id -ErrorAction SilentlyContinue
            if ($stillRunning) {
                Write-Step "companion app confirmed running (PID $($proc.Id)) -- all set"
            }
            else {
                Write-Warn2 "companion app exited within 3s of launch (PID $($proc.Id) is gone) -- check %USERPROFILE%\.ccsync\companion.log for why"
            }
        }
        catch {
            Write-Warn2 "could not launch companion app: $($_.Exception.Message) -- it will still start at next logon via autostart"
        }
    }
}

# --------------------------------------------------------------------
# 10. Print Syncthing device ID
# --------------------------------------------------------------------
# `syncthing --device-id` was removed in Syncthing v2 (exits 80, "unknown
# flag"). `generate` prints it on every run and is safe to re-run against an
# existing home ("Key exists; will not overwrite"), so parse it from there,
# keeping the old flag as a fallback for v1 installs.
function Get-SyncthingDeviceId {
    param([string]$ExePath, [string]$Home2)

    try {
        $genOutput = & $ExePath generate --home="$Home2" 2>&1 | Out-String
        $m = [regex]::Match($genOutput, "device=([A-Z0-9]{7}(?:-[A-Z0-9]{7}){7})")
        if ($m.Success) { return $m.Groups[1].Value }
    }
    catch {
        Write-Warn2 "syncthing generate failed: $($_.Exception.Message)"
    }

    try {
        $legacy = & $ExePath --device-id --home="$Home2" 2>&1 | Out-String
        $m2 = [regex]::Match($legacy, "([A-Z0-9]{7}(?:-[A-Z0-9]{7}){7})")
        if ($m2.Success) { return $m2.Groups[1].Value }
    }
    catch {
        # v2 removed the flag entirely -- nothing more to try.
    }

    return $null
}

Write-Step "determining this machine's Syncthing device ID..."
if ($DryRun) {
    Write-Step "[dry-run] would parse the device ID from: `"$syncthingPath`" generate --home=`"$SyncthingHome`""
    Write-Host ""
    Write-Host "=================================================================="
    Write-Host " Bootstrap complete (dry run). No changes were made."
    Write-Host "=================================================================="
}
else {
    $deviceId = Get-SyncthingDeviceId -ExePath $syncthingPath -Home2 $SyncthingHome

    Write-Host ""
    Write-Host "=================================================================="
    Write-Host " Bootstrap complete."
    Write-Host ""
    if ($null -eq $deviceId) {
        Write-Warn2 "could not determine the Syncthing device ID automatically."
        Write-Host " Get it from the Syncthing web UI (http://127.0.0.1:8384)"
        Write-Host " under Actions > Show ID, and send that to the admin."
    }
    else {
        Write-Host " Your Syncthing device ID is:"
        Write-Host ""
        Write-Host "     $deviceId" -ForegroundColor Cyan
        Write-Host ""
        Write-Host " Send this device ID to the admin so they can approve it with"
        Write-Host " server/accept_device.py for each project you're working on."
    }
    Write-Host ""
    Write-Host " Remaining manual steps (see docs/EDITOR_SETUP.md):"
    Write-Host "   1. tailscale up   (join the tailnet, one-time interactive login)"
    Write-Host "   2. generate an SSH keypair for rclone if you haven't already:"
    Write-Host "        ssh-keygen -t ed25519 -f `"$KeyFilePath`""
    Write-Host "      and send the .pub file to the admin"
    Write-Host "   3. connect DaVinci Resolve to the Project Server"
    Write-Host "   4. Playback > Proxy Handling > Prefer Proxies"
    Write-Host "   5. do NOT map any NAS share to another drive letter -- see the"
    Write-Host "      drive-letter warning in docs/EDITOR_SETUP.md"
    Write-Host "=================================================================="
}
