#requires -Version 5.1
<#
.SYNOPSIS
    Creators Club Sync -- Windows editor bootstrap.

.DESCRIPTION
    Idempotent setup for a remote Resolve editor's Windows machine:
      - Tailscale (winget, else prints download URL and exits)
      - rclone   (winget, else scoop, else direct zip to %LOCALAPPDATA%\ccsync\bin)
      - Syncthing (winget, else direct zip to the same bin folder)
      - C:\Creators_Club (the local sync root)
      - a logon scheduled task that runs `subst P: C:\Creators_Club`, run once now too
      - an rclone remote config stanza template in %APPDATA%\rclone\rclone.conf
      - a companion (ccsync-companion.exe) autostart entry, if the exe exists yet
      - prints this machine's Syncthing device ID at the end

    Every step checks current state before acting and prints a line saying
    what it did or what it skipped, so this script is safe to re-run.

    This script does NOT run `tailscale up` (joining the tailnet) or
    generate SSH keys -- those are one-time interactive/manual steps, see
    docs/EDITOR_SETUP.md.

.PARAMETER TailnetHost
    Tailnet hostname or IP of the NAS, e.g. "truenas.tailXXXX.ts.net" or a
    100.x.y.z address. Written into the rclone remote config stanza.

.PARAMETER EditorName
    This editor's TrueNAS username (matches what the admin set up via
    server/setup_editor_account.py). Written into the rclone remote config
    stanza and used to label the scheduled task / autostart entries.

.PARAMETER CompanionExePath
    Path to ccsync-companion.exe. Defaults under %LOCALAPPDATA%\ccsync\bin.
    The companion app may not exist yet (it's built separately, see
    companion/) -- if the file isn't there, autostart registration is
    skipped with a note, not a hard failure.

.PARAMETER DryRun
    Print what would happen without installing anything or touching the
    filesystem/registry/scheduled tasks.

.EXAMPLE
    .\windows_bootstrap.ps1 -TailnetHost truenas.tailnet.ts.net -EditorName jsmith
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$TailnetHost,

    [Parameter(Mandatory = $true)]
    [string]$EditorName,

    [string]$CompanionExePath = "$env:LOCALAPPDATA\ccsync\bin\ccsync-companion.exe",

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

# TLS 1.2 for winget-less direct downloads on older Windows/.NET defaults.
try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
}
catch {
    Write-Warn2 "could not force TLS 1.2 on this .NET runtime; direct downloads may fail on older Windows"
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
        $zipUrl = "https://github.com/syncthing/syncthing/releases/latest/download/syncthing-windows-amd64.zip"
        $zipPath = "$env:TEMP\syncthing-windows-amd64.zip"
        $extractDir = "$env:TEMP\syncthing-extract"
        if ($DryRun) {
            Write-Step "[dry-run] would download $zipUrl to $zipPath, extract, and copy syncthing.exe to $BinDir"
        }
        else {
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
if ($DryRun -and (-not $syncthingPath)) {
    $syncthingPath = "$BinDir\syncthing.exe"
}

# --------------------------------------------------------------------
# 4. C:\Creators_Club local sync root
# --------------------------------------------------------------------
$CCRoot = "C:\Creators_Club"
Ensure-Dir $CCRoot

# --------------------------------------------------------------------
# 5. Logon scheduled task: subst P: C:\Creators_Club
# --------------------------------------------------------------------
$TaskName = "CCSync-SubstP"
Write-Step "checking scheduled task '$TaskName'..."
$existingTask = $null
try {
    $existingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
}
catch {
    $existingTask = $null
}

if ($existingTask) {
    Write-Skip "scheduled task '$TaskName' already exists"
}
else {
    if ($DryRun) {
        Write-Step "[dry-run] would register scheduled task '$TaskName' to run 'subst P: $CCRoot' at logon"
    }
    else {
        $action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c subst P: $CCRoot"
        $trigger = New-ScheduledTaskTrigger -AtLogOn
        $principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive
        Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Force | Out-Null
        Write-Step "registered scheduled task '$TaskName'"
    }
}

# Run subst now too, if P: isn't already mapped correctly.
$substOutput = subst
$pLine = $substOutput | Where-Object { $_ -match "^P:\\" }
if ($pLine) {
    if ($pLine -match [Regex]::Escape($CCRoot)) {
        Write-Skip "P: already mapped to $CCRoot"
    }
    else {
        Write-Warn2 "P: is mapped to something other than $CCRoot -- not touching it: $pLine"
    }
}
else {
    if ($DryRun) {
        Write-Step "[dry-run] would run: subst P: $CCRoot"
    }
    else {
        subst P: $CCRoot
        if ($LASTEXITCODE -eq 0) {
            Write-Step "mapped P: -> $CCRoot"
        }
        else {
            Write-Warn2 "subst P: $CCRoot exited with code $LASTEXITCODE"
        }
    }
}

# --------------------------------------------------------------------
# 6. rclone remote config stanza
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
# 7. Companion autostart (guarded -- exe may not exist yet)
# --------------------------------------------------------------------
Write-Step "checking companion app at $CompanionExePath..."
if (-not (Test-Path -LiteralPath $CompanionExePath)) {
    Write-Warn2 "companion exe not found at $CompanionExePath -- skipping autostart registration. Install the companion app later and re-run this script to register autostart."
}
else {
    $RunKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
    $RunValueName = "CCSyncCompanion"
    $existingValue = $null
    try {
        $existingValue = (Get-ItemProperty -Path $RunKey -Name $RunValueName -ErrorAction SilentlyContinue).$RunValueName
    }
    catch {
        $existingValue = $null
    }

    if ($existingValue -eq $CompanionExePath) {
        Write-Skip "companion autostart already registered: $CompanionExePath"
    }
    else {
        if ($DryRun) {
            Write-Step "[dry-run] would set registry value $RunKey\$RunValueName = $CompanionExePath"
        }
        else {
            Set-ItemProperty -Path $RunKey -Name $RunValueName -Value $CompanionExePath
            Write-Step "registered companion autostart: $RunKey\$RunValueName = $CompanionExePath"
        }
    }
}

# --------------------------------------------------------------------
# 8. Print Syncthing device ID
# --------------------------------------------------------------------
Write-Step "determining this machine's Syncthing device ID..."
if ($DryRun) {
    Write-Step "[dry-run] would run: `"$syncthingPath`" generate --home=`"$env:LOCALAPPDATA\ccsync\syncthing-config`" (if not already generated)"
    Write-Step "[dry-run] would run: `"$syncthingPath`" --device-id --home=`"$env:LOCALAPPDATA\ccsync\syncthing-config`""
    Write-Host ""
    Write-Host "=================================================================="
    Write-Host " Bootstrap complete (dry run). No changes were made."
    Write-Host "=================================================================="
}
else {
    $SyncthingHome = "$env:LOCALAPPDATA\ccsync\syncthing-config"
    if (-not (Test-Path -LiteralPath $SyncthingHome)) {
        Write-Step "generating Syncthing config at $SyncthingHome ..."
        & $syncthingPath generate --home="$SyncthingHome" | Out-Null
    }
    else {
        Write-Skip "Syncthing config already generated at $SyncthingHome"
    }

    $deviceId = & $syncthingPath --device-id --home="$SyncthingHome" 2>$null
    Write-Host ""
    Write-Host "=================================================================="
    Write-Host " Bootstrap complete."
    Write-Host ""
    Write-Host " Your Syncthing device ID is:"
    Write-Host ""
    Write-Host "     $deviceId" -ForegroundColor Cyan
    Write-Host ""
    Write-Host " Send this device ID to the admin so they can approve it with"
    Write-Host " server/accept_device.py for each project you're working on."
    Write-Host ""
    Write-Host " Remaining manual steps (see docs/EDITOR_SETUP.md):"
    Write-Host "   1. tailscale up   (join the tailnet, one-time interactive login)"
    Write-Host "   2. generate an SSH keypair for rclone if you haven't already:"
    Write-Host "        ssh-keygen -t ed25519 -f `"$KeyFilePath`""
    Write-Host "      and send the .pub file to the admin"
    Write-Host "   3. connect DaVinci Resolve to the Project Server"
    Write-Host "   4. Playback > Proxy Handling > Prefer Proxies"
    Write-Host "=================================================================="
}
