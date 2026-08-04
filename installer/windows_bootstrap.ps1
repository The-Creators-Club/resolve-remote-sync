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

    ELEVATION: run this from a NORMAL, NON-ADMINISTRATOR PowerShell window.
    Windows keeps elevated and unelevated drive letters in separate device
    maps, so a P: created by an elevated process is INVISIBLE to the session
    DaVinci Resolve, Explorer and the companion actually run in -- while this
    script's own checks succeed, so the install looks perfect and Resolve
    shows every clip offline (INST-1). Exactly one step genuinely needs admin
    rights (creating the loopback SMB share); the script raises a single UAC
    prompt for that step alone and does the mapping itself at your normal
    integrity level. Registering the logon scheduled task also wants admin;
    without it the script falls back to an HKCU Run entry that achieves the
    same thing, warns, and carries on. No step aborts the run. If you DO run
    this elevated, it routes the mapping through a one-shot task at your own
    integrity level, and warns loudly if even that fails.

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

.PARAMETER NasSyncthingId
    The NAS Syncthing's device ID, seeded into this machine's Syncthing via
    REST once the daemon is up -- a fresh config knows no devices and drops
    every NAS connection as "unknown device" otherwise. The default is the
    production NAS; pass "" to skip seeding.

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
    # How long to wait for an open DaVinci Resolve to be quit before setting
    # its LUT/stills preferences. Resolve overwrites both preference files
    # when it exits, so an edit made while it is running is thrown away --
    # waiting is the only way to set them during an install. 0 skips the
    # wait entirely (the companion applies them later either way).
    [int]$ResolvePrefsWaitSeconds = 180,

    # Sync dashboard (tailnet address is right for remote editors). The token
    # comes from the admin; without it reports/selection are rejected.
    [string]$DashboardUrl = "http://100.71.216.3:8480",
    [string]$DashboardToken = "",

    # The NAS Syncthing's device ID, seeded into this machine's Syncthing so
    # the two can pair without a human accepting anything in either GUI. A
    # fresh `syncthing generate` config knows NO devices, so the NAS's
    # connection attempts are dropped as "unknown device" 1 second after
    # hello -- the alex_laptop reinstall flapping of 2026-07-26. Empty
    # string skips the seeding entirely.
    [string]$NasSyncthingId = "CPGHYGU-KI5UFOR-GPOGIEP-5EW6BIP-ZNJNVY3-Q5GI5PN-TGI346D-MTKBSQR",

    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

# The fleet token is a credential and a native process's command line is
# readable by ANY unprivileged process on the machine (Get-CimInstance
# Win32_Process), so onboard.exe hands it over in the environment instead of on
# argv -- see onboarding/steps.py's run_bootstrap, and server/common.py which
# pipes its secrets over stdin for the same reason (AUDIT SEC-2).
# -DashboardToken stays for hand-runs; the environment wins when the parameter
# is blank, and is cleared immediately so nothing this script launches inherits
# it.
if ([string]::IsNullOrEmpty($DashboardToken) -and $env:CCSYNC_DASHBOARD_TOKEN) {
    $DashboardToken = $env:CCSYNC_DASHBOARD_TOKEN
}
$env:CCSYNC_DASHBOARD_TOKEN = $null

# Bump this AND INSTALLER_VERSION in onboarding/steps.py AND
# INSTALLER_VERSION in installer/macos_bootstrap.sh together -- one installer
# number covers all three, and build_editor_package.ps1 / tools\release.ps1
# refuse on drift between any of them.
# 1.0.15: the fleet token moved off this script's command line into
# CCSYNC_DASHBOARD_TOKEN in its environment (see the block just above), which
# is a contract between this script and steps.py; they must ship as a pair.
# 1.0.19: MAC-9 -- the macOS bootstrap's rclone.conf rewrite destroyed the file
# (BWK awk + an unchecked empty result). Nothing changed in this script; the
# number is shared and moves when either platform's installer does.
# 1.0.18: onboard.py's worker->UI handoff moved to a main-thread queue pump;
# `root.after()` from a worker thread never fires on macOS/Tk 9 (MAC-8).
# onboard.py is shared, so this build changes too, but nothing in this
# script did; the number is shared and moves when either platform's does.
# 1.0.17: the onboarding wizard runs on macOS too (onboarding/steps.py darwin
# branches); macos_bootstrap.sh gained the wizard contract (CAPABILITY
# MISSING: markers, exit 3 summary, RESOLVE-MAPPING-STATUS marker, and the
# existing-config rclone_path repair). Nothing changed in this file; the
# number is shared, so it moves when either platform's installer does.
# 1.0.16: macOS caught up (SSD-aware bootstrap, Resolve Mapped Mount helper,
# macos_uninstall.sh). Nothing changed on the Windows side; the number is
# shared, so it moves when either platform's installer does.
$InstallerVersion = "1.0.19"

# When our stdout is a pipe (onboard.exe captures it), PS 5.1 encodes it with
# the console OEM codepage -- so the wizard, which decodes UTF-8, would see
# mojibake for a `C:\Users\Jose` profile and, on some codepages, raise
# UnicodeDecodeError out of its worker thread AFTER clean-slate ran (S-6).
# Force UTF-8 only in that case; changing it for an interactive console would
# alter what the editor sees for no benefit.
try {
    if ([Console]::IsOutputRedirected) {
        [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
    }
}
catch {}

# PS 5.1 has no ternary/null-coalescing operators and no `&&`/`||` chaining --
# every branch below is written as a plain if/else.

# Hard-capability misses (rclone absent, Syncthing absent, no device ID).
# Each one means this machine can never sync something it is supposed to
# sync, so unlike every other warning here they must NOT end in exit 0 with
# the wizard showing a green DONE page (INST-5).
$script:CapabilityMisses = @()

# Set when a P: mount had to be made from an elevated token after all -- the
# editor then needs to log off and back on before Resolve can see it.
$script:MappedWhileElevated = $false

function Add-CapabilityMiss {
    param([string]$Message)
    $script:CapabilityMisses += $Message
    Write-Host "[ccsync] WARNING: CAPABILITY MISSING: $Message" -ForegroundColor Red
}

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

# Runs one command line through cmd.exe at the user's NORMAL (unelevated,
# medium-integrity) level, even when this process is elevated. A one-shot
# scheduled task with -RunLevel Limited + -LogonType Interactive is the only
# mechanism in PS 5.1 that reliably does this without a shell round-trip.
#
# WHY it matters: drive letters live in a per-logon-session DOS device map
# that is ALSO split by UAC's linked tokens. A P: mapped by an elevated
# process does not exist for the unelevated session Resolve, Explorer and the
# companion run in -- and the elevated session's own Get-PSDrive happily
# reports success, which is what made this invisible (INST-1).
#
# Returns $true only when the task actually ran and exited 0.
function Invoke-AtUserIntegrity {
    param([string]$CommandLine)

    $taskName = "CCSync-OneShot-" + [Guid]::NewGuid().ToString("N").Substring(0, 8)
    try {
        $action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c $CommandLine"
        $principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" `
            -LogonType Interactive -RunLevel Limited
        Register-ScheduledTask -TaskName $taskName -Action $action -Principal $principal -Force | Out-Null
        Start-ScheduledTask -TaskName $taskName

        # 267009 = 0x41301 "task is currently running"; 267011 = 0x41303
        # "task has not yet run" (what a brand-new task reports until the
        # scheduler actually picks it up).
        $result = $null
        $deadline = (Get-Date).AddSeconds(30)
        while ((Get-Date) -lt $deadline) {
            Start-Sleep -Milliseconds 500
            $info = Get-ScheduledTaskInfo -TaskName $taskName -ErrorAction SilentlyContinue
            if ($info -and ($info.LastTaskResult -ne 267009) -and ($info.LastTaskResult -ne 267011)) {
                $result = $info.LastTaskResult
                break
            }
        }
        try { Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue } catch {}
        if ($null -eq $result) { return $false }
        return ($result -eq 0)
    }
    catch {
        try { Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue } catch {}
        return $false
    }
}

# Every P: mount/unmount goes through here. Unelevated (the normal, and the
# documented, case) it just runs; elevated it is routed to the user's own
# integrity level so the mapping is visible where it needs to be.
function Invoke-MappingCommand {
    param([string]$CommandLine, [string]$What = "")

    if (-not $IsElevated) {
        # Redirection must happen INSIDE cmd: a PowerShell-level 2>$null
        # wraps native stderr in a NativeCommandError, fatal under
        # $ErrorActionPreference = 'Stop' when the drive isn't mapped.
        cmd /c "$CommandLine >nul 2>&1"
        return ($LASTEXITCODE -eq 0)
    }

    if (Invoke-AtUserIntegrity "$CommandLine >nul 2>&1") {
        if ($What) {
            Write-Step "$What (run at your normal integrity level via a one-shot task -- this elevated window deliberately cannot see the result)"
        }
        return $true
    }

    Write-Warn2 "could not run '$CommandLine' at your normal integrity level; running it in this elevated session instead."
    $script:MappedWhileElevated = $true
    cmd /c "$CommandLine >nul 2>&1"
    return ($LASTEXITCODE -eq 0)
}

# Parses the combined output of `subst` + `net use` for ONE drive letter.
# Pure text in, object out, so it can be reasoned about without a machine.
#
#   subst   -> "P:\: => C:\Creators_Club"
#   net use -> "OK           P:        \\localhost\CCSync_P   Microsoft Windows Network"
#              "Unavailable  P:        \\nas\TheCreatorsPool  Microsoft Windows Network"
#
# The `net use` status column is localised and is sometimes blank, so it is
# deliberately not matched -- the letter followed by a UNC path is the signal,
# and "Unavailable"/"Disconnected" rows count as MAPPED (that is the whole
# point: a persistent mapping to a sleeping NAS is still a mapping).
function ConvertFrom-DriveMapReport {
    param([string]$Report, [string]$Letter = "P")

    $result = [PSCustomObject]@{ Mapped = $false; Kind = "none"; Target = "" }
    if ([string]::IsNullOrEmpty($Report)) { return $result }
    $L = [regex]::Escape($Letter)

    foreach ($line in ($Report -split "`r?`n")) {
        $trimmed = $line.Trim()
        if (-not $trimmed) { continue }

        $substMatch = [regex]::Match($trimmed, "(?i)^$L`:\\?:\s*=>\s*(.+)$")
        if ($substMatch.Success) {
            $result.Mapped = $true
            $result.Kind = "subst"
            $result.Target = $substMatch.Groups[1].Value.Trim()
            return $result
        }

        $netMatch = [regex]::Match($trimmed, "(?i)(^|\s)$L`:\s+(\\\\\S+)")
        if ($netMatch.Success) {
            $result.Mapped = $true
            $result.Kind = "netuse"
            $result.Target = $netMatch.Groups[2].Value.Trim()
            return $result
        }
    }
    return $result
}

# Reads the CURRENT USER's DOS device map for one drive letter, at the user's
# own integrity level. Returns $null when the state could NOT be determined --
# callers MUST treat $null as "somebody else's mapping" and refuse to touch it.
#
# WHY not `Test-Path "P:\"` (B21, and the same root cause as INST-1/INST-15):
# drive letters live in a per-logon-session device map that UAC additionally
# splits between the linked tokens, so an ELEVATED run cannot see the mapping
# the unelevated session holds -- yet the teardown below runs via
# Invoke-AtUserIntegrity inside that very session. And Test-Path reports
# $false for a DISCONNECTED persistent mapping (NAS asleep, Tailscale not up
# -- both likely at bootstrap time) that is still in the device map and will
# reconnect. Both read as "there is no P: here", after which the teardown
# deleted the base rig's real NAS mapping and section 5 recreated P: as a
# loopback of a local folder, taking every P:\Projects\... clip path in the
# Resolve database offline.
function Get-DriveMapping {
    param([string]$Letter = "P")

    $tempRoot = $env:TEMP
    if ([string]::IsNullOrWhiteSpace($tempRoot)) { $tempRoot = [System.IO.Path]::GetTempPath() }
    $tmp = Join-Path $tempRoot ("ccsync-drivemap-" + [Guid]::NewGuid().ToString("N").Substring(0, 8) + ".txt")
    # Redirection happens INSIDE cmd: a PowerShell-level redirect wraps native
    # stderr in a NativeCommandError, fatal under $ErrorActionPreference='Stop'
    # when nothing is mapped at all.
    $cmdLine = "(subst & net use) > `"$tmp`" 2>&1"
    $report = $null
    try {
        if ($IsElevated) {
            # Read-only probe, so it runs even under -DryRun: without it an
            # elevated dry run would report the wrong verdict, which is the
            # bug this function exists to fix.
            Invoke-AtUserIntegrity $cmdLine | Out-Null
        }
        else {
            cmd /c $cmdLine
        }
        # The exit code is `net use`'s and is noise (non-zero when there are no
        # connections at all). The file is the signal.
        if (Test-Path -LiteralPath $tmp) {
            $report = Get-Content -LiteralPath $tmp -Raw -ErrorAction SilentlyContinue
            if ($null -eq $report) { $report = "" }
        }
    }
    catch {
        $report = $null
    }
    finally {
        try { Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue } catch {}
    }

    if ($null -eq $report) { return $null }
    return (ConvertFrom-DriveMapReport -Report $report -Letter $Letter)
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

# Writes a shim file (.cmd or .vbs) using the codepage the interpreter that
# reads it actually uses -- NOT ASCII, which silently replaces every
# non-ASCII character (e.g. in $CCRoot or $SyncthingHome, which contains
# %LOCALAPPDATA% and therefore the Windows username) with '?', pointing the
# logon shim at a nonexistent path with no error ever shown. cmd.exe parses
# .cmd/.bat files in the console's OEM codepage; wscript.exe parses .vbs
# files in the system's ANSI codepage -- they are frequently different
# codepages on the same machine, so each file needs its own encoding.
# Belt-and-braces: even the right codepage can't represent every character
# (e.g. CJK on an English-locale Windows), so round-trip the content and
# warn loudly rather than let a silently mangled path through.
function Write-ShimFile {
    param([string]$Path, [string]$Content, [int]$CodePage)
    $encoding = [System.Text.Encoding]::GetEncoding($CodePage)
    [System.IO.File]::WriteAllText($Path, $Content, $encoding)
    $roundTripped = $encoding.GetString($encoding.GetBytes($Content))
    if ($roundTripped -ne $Content) {
        Write-Warn2 "$Path contains characters outside codepage $CodePage -- the path it launches may be silently mangled. If autostart doesn't work, start it by hand or use an ASCII-only Windows user profile path."
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
    Write-ShimFile -Path $cmdPath -Content $cmdBody `
        -CodePage ([System.Globalization.CultureInfo]::CurrentCulture.TextInfo.OEMCodePage)

    # VBS quoting: "" is a literal quote inside a VBS string literal.
    $vbsBody = "CreateObject(""WScript.Shell"").Run ""cmd /c """"$cmdPath"""""", 0, False"
    Write-ShimFile -Path $vbsPath -Content $vbsBody `
        -CodePage ([System.Globalization.CultureInfo]::CurrentCulture.TextInfo.ANSICodePage)

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
# A double quote in -LocalRoot cannot survive the `cmd /c subst P: "<root>"`
# command line the logon remap runs through, and there is no escaping that
# fixes it -- so refuse up front rather than install a machine whose P: never
# comes back after a reboot (INST-2).
if ($LocalRoot -match '"') {
    Write-Host "[ccsync] ERROR: -LocalRoot contains a double-quote character: $LocalRoot" -ForegroundColor Red
    Write-Host "[ccsync] The logon remap runs 'subst P: `"<LocalRoot>`"' through cmd, which a quote breaks irrecoverably."
    Write-Host "[ccsync] Rename the folder (or pick a different one) and re-run."
    exit 2
}

$EditorNameRaw = $EditorName
$EditorName = $EditorName.Trim().ToLowerInvariant()
if ($EditorName -cne $EditorNameRaw) {
    Write-Warn2 "normalized -EditorName '$EditorNameRaw' -> '$EditorName' (unix usernames are case-sensitive; a mismatch shows up later only as a generic SSH auth failure)"
}

if (-not $RemoteRoot.StartsWith("/")) {
    Write-Warn2 "-RemoteRoot '$RemoteRoot' is not absolute. The SFTP session starts in your home directory on the NAS, so a relative path resolves under ~/ and will not find the project tree. Prefix it with '/'."
}

$IsElevated = Test-IsElevated
Write-Step "installer v$InstallerVersion -- configuring for editor '$EditorName', local root '$LocalRoot', NAS '$TailnetHost'"
if (-not $IsElevated) {
    Write-Step "running unelevated -- will fall back to an HKCU Run entry if scheduled-task registration is denied"
}
else {
    # UAC linked-token isolation: drive letters are per-logon-session AND
    # per-token, so a P: mapped by this elevated process does not exist in
    # the unelevated session Resolve and Explorer run in. Both mapping styles
    # (net use, subst) behave identically here. Section 5 works around it by
    # doing the mapping through an unelevated helper; this is the warning for
    # when that can't be done (INST-1).
    Write-Warn2 "this PowerShell window is ELEVATED (running as administrator)."
    Write-Warn2 "Drive letters mapped by an elevated process are INVISIBLE to your normal, unelevated session -- which is the one DaVinci Resolve runs in."
    Write-Warn2 "This script will try to create the P: mapping at your normal integrity level anyway (see section 5). If that fails, P: will not appear until you log off and back on."
    Write-Warn2 "Next time, run this from a NORMAL (non-administrator) PowerShell window -- it asks for elevation only for the one step that genuinely needs it."
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
            # -UseBasicParsing skips the IE DOM parser; SilentlyContinue on
            # $ProgressPreference removes PS 5.1's per-chunk progress render,
            # which costs an order of magnitude on a multi-MB download; and
            # -TimeoutSec stops a half-open TCP connection hanging until the
            # wizard's 1800s timeout kills the whole install (INST-19).
            $prevProgress = $ProgressPreference
            $ProgressPreference = 'SilentlyContinue'
            try {
                Invoke-WebRequest -Uri $zipUrl -OutFile $zipPath -UseBasicParsing -TimeoutSec 600
            }
            finally {
                $ProgressPreference = $prevProgress
            }
            if (Test-Path $extractDir) { Remove-Item -Recurse -Force $extractDir }
            Expand-Archive -Path $zipPath -DestinationPath $extractDir -Force
            $exe = Get-ChildItem -Path $extractDir -Filter "rclone.exe" -Recurse | Select-Object -First 1
            if ($null -eq $exe) {
                Write-Warn2 "could not find rclone.exe inside the downloaded zip"
            }
            else {
                Copy-Item -Path $exe.FullName -Destination "$BinDir\rclone.exe" -Force
                Write-Step "installed rclone to $BinDir\rclone.exe"
                $rclonePath = "$BinDir\rclone.exe"
            }
        }
    }
}

# Make sure BinDir is on this user's PATH (idempotent).
#
# Read through the registry, NOT [Environment]::GetEnvironmentVariable: that
# EXPANDS a REG_EXPAND_SZ value, while SetEnvironmentVariable writes back a
# plain REG_SZ -- so a user PATH containing "%USERPROFILE%\bin" would be
# permanently rewritten to the literal expansion of today's profile path,
# silently breaking that entry on a roamed/renamed profile. DoNotExpandEnvir-
# onmentNames gives the raw value, and the kind is preserved on write.
$userPathRaw = ""
$userPathKind = [Microsoft.Win32.RegistryValueKind]::ExpandString
try {
    $envKey = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey("Environment", $false)
    if ($envKey) {
        try {
            $raw = $envKey.GetValue("Path", "", [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
            if ($null -ne $raw) { $userPathRaw = "$raw" }
            $kind = $envKey.GetValueKind("Path")
            if ($kind) { $userPathKind = $kind }
        }
        finally {
            $envKey.Close()
        }
    }
}
catch {
    # No Environment key / no Path value yet -- a brand-new profile. "" and
    # ExpandString are the right starting point.
    $userPathRaw = ""
}

if ($userPathRaw -split ";" -contains $BinDir) {
    Write-Skip "$BinDir already on user PATH"
}
else {
    # Only the %VAR%-bearing case needs the raw registry write. Everywhere else
    # keep [Environment]::SetEnvironmentVariable, which additionally broadcasts
    # WM_SETTINGCHANGE so Explorer-launched processes pick the change up
    # without a logoff.
    $pathHasVars = ($userPathRaw -match '%[^%]+%')
    if ($DryRun) {
        if ($pathHasVars) {
            Write-Step "[dry-run] would add $BinDir to user PATH, writing it back as $userPathKind so the existing %VAR% entries stay unexpanded"
        }
        else {
            Write-Step "[dry-run] would add $BinDir to user PATH"
        }
    }
    else {
        $newPath = $BinDir
        if ($userPathRaw.Length -gt 0) { $newPath = $userPathRaw + ";" + $BinDir }
        try {
            if ($pathHasVars) {
                $envKeyW = [Microsoft.Win32.Registry]::CurrentUser.CreateSubKey("Environment")
                try {
                    $envKeyW.SetValue("Path", $newPath, $userPathKind)
                }
                finally {
                    $envKeyW.Close()
                }
                Write-Step "added $BinDir to user PATH, preserving its %VAR% entries (log off and back on to pick it up)"
            }
            else {
                [Environment]::SetEnvironmentVariable("Path", $newPath, "User")
                Write-Step "added $BinDir to user PATH (restart your terminal to pick it up)"
            }
        }
        catch {
            Write-Warn2 "could not update the user PATH: $($_.Exception.Message). Add $BinDir by hand (Settings > System > About > Advanced system settings > Environment Variables)."
        }
    }
}

# The REGISTRY PATH above only takes effect for processes started after the
# next logon. Section 9 launches the companion as a child of THIS process,
# with a config saying rclone_path = "rclone" -- without this line lanes A/B
# report "rclone not found on PATH" and the tray sits red until the editor
# next logs in, on a machine that is actually fine (INST-14).
if (-not (($env:Path -split ";") -contains $BinDir)) {
    $env:Path = "$env:Path;$BinDir"
    Write-Step "added $BinDir to this session's PATH (so the companion we launch below finds rclone now)"
}

# Authoritative check, after every install route: winget/scoop don't refresh
# this process's PATH, so re-probe rather than trust which branch ran.
if (-not $DryRun) {
    $rcloneFinal = $null
    if (Test-CommandExists "rclone") { $rcloneFinal = (Get-Command rclone).Source }
    elseif (Test-Path "$BinDir\rclone.exe") { $rcloneFinal = "$BinDir\rclone.exe" }
    if (-not $rcloneFinal) {
        Add-CapabilityMiss "rclone is NOT installed. Lanes A and B -- every video upload and every proxy download -- cannot run at all on this machine. Install rclone from https://rclone.org/downloads/ (or 'winget install Rclone.Rclone') and re-run this script."
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
function Get-SyncthingExePath {
    if (Test-CommandExists "syncthing") { return (Get-Command syncthing).Source }
    if (Test-Path "$BinDir\syncthing.exe") { return "$BinDir\syncthing.exe" }
    if (Test-Path "$env:ProgramFiles\Syncthing\syncthing.exe") { return "$env:ProgramFiles\Syncthing\syncthing.exe" }
    if (Test-Path "${env:ProgramFiles(x86)}\Syncthing\syncthing.exe") { return "${env:ProgramFiles(x86)}\Syncthing\syncthing.exe" }
    return $null
}

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
$syncthingPath = Get-SyncthingExePath

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
            if ($LASTEXITCODE -eq 0) {
                $installed = $true
                # winget doesn't tell us where it put the exe (and doesn't
                # refresh this process's PATH) -- re-probe the usual
                # locations rather than assuming a well-known path.
                $syncthingPath = Get-SyncthingExePath
                if (-not $syncthingPath) {
                    Write-Warn2 "winget reported success but Syncthing's exe could not be located afterwards -- open a new terminal (PATH may need a refresh) and re-run this script"
                }
            }
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
                # See the rclone download above for why all three of these
                # matter (INST-19).
                $prevProgress = $ProgressPreference
                $ProgressPreference = 'SilentlyContinue'
                try {
                    Invoke-WebRequest -Uri $zipUrl -OutFile $zipPath -UseBasicParsing -TimeoutSec 600
                }
                finally {
                    $ProgressPreference = $prevProgress
                }
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
if ((-not $DryRun) -and (-not $syncthingPath)) {
    Add-CapabilityMiss "Syncthing is NOT installed. Lane C -- audio, After Effects projects, graphics, subtitles, .drp project files and docs -- will never sync on this machine. Install Syncthing from https://syncthing.net/downloads/ (or 'winget install Syncthing.Syncthing') and re-run this script."
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
# Set when P: turns out to be somebody else's mapping (a real NAS share).
# Section 5 AND section 5b both bail out on it: relabelling a drive this
# installer did not create is the same class of mistake as remapping it.
$script:PIsForeign = $false
$TaskName = "CCSync-SubstP"
# QUOTED, always. This exact string is handed to `cmd /c` twice -- as the
# scheduled task's -Argument and inside the .cmd shim Register-HiddenRunEntry
# writes -- and cmd splits on spaces. Unquoted, a -LocalRoot of
# "D:\Video Projects\Creators_Club" becomes `subst P: D:\Video` at EVERY
# logon: "Path not found", no window, no log, no P:, Resolve fully offline,
# while the companion (which has the real path) reports green. The direct
# call at the bottom of this section is fine either way -- PowerShell
# auto-quotes an argument containing spaces -- which is exactly why the
# install looked successful and only reboots broke (INST-2, measured).
$SubstCommand = "subst P: `"$CCRoot`""
$RunKeyPath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
$substFallbackName = "CCSyncSubstP"
$ShareName = "CCSync_P"

# -- "is P: ours?" guard, BEFORE any teardown and before the dry-run split --
# Same test windows_uninstall.ps1 and steps.build_cleanup_plan already apply
# (D-8), which the bootstrap never got (INST-15). A subst mapping has no
# DisplayRoot and is always ours; a net-use mapping is ours only when it
# points at our own loopback share. Anything else is a real NAS mapping --
# replacing it with a loopback share of a local folder makes every
# P:\Projects\... path in the Resolve database resolve to a nearly-empty
# local tree. Detected outside the -DryRun branch on purpose, so a dry run
# reports the refusal instead of describing a remap that would never happen.
#
# Detection goes through Get-DriveMapping, NOT Test-Path (B21): Test-Path is
# blind to the unelevated session's mappings when this script runs elevated,
# and blind to a disconnected persistent mapping in every case -- the two
# situations where getting this wrong destroys the base rig. "Can't tell"
# counts as foreign.
$existingDisplayRoot = $null
$pMapping = Get-DriveMapping -Letter "P"
if ($null -eq $pMapping) {
    $script:PIsForeign = $true
    $existingDisplayRoot = "<could not be determined>"
    Write-Warn2 "could not read this logon session's drive mappings, so P: is being treated as somebody else's and left alone. That is deliberate: guessing 'there is no P:' here is how a real NAS mapping gets deleted."
}
elseif ($pMapping.Mapped) {
    $existingDisplayRoot = $pMapping.Target
    if ($pMapping.Kind -eq "subst") {
        Write-Step "P: is a subst mapping of '$existingDisplayRoot' -- this installer's own style, safe to replace"
    }
    elseif ($existingDisplayRoot -match '^(?i)\\\\localhost\\CCSync_P$') {
        Write-Step "P: is our own loopback share '$existingDisplayRoot' -- safe to replace"
    }
    else {
        $script:PIsForeign = $true
    }
}

if ($script:PIsForeign) {
    Write-Host "[ccsync] ERROR: P: is already mapped to '$existingDisplayRoot' -- that is not a mapping this installer created." -ForegroundColor Red
    Write-Warn2 "Leaving it exactly as it is. Replacing a real NAS mapping with a loopback share of a local folder would make every P:\Projects\... path in your Resolve database point at a nearly-empty local tree."
    Write-Warn2 "If this IS the machine that should get a local P:, disconnect that mapping yourself first (Explorer > This PC > right-click P: > Disconnect) and re-run."
    Write-Warn2 "If this is the base rig, you want the BASE role in onboard.exe -- it never touches drive mappings."
    Write-Warn2 "Skipping the whole P: mapping section; everything else below still runs."
}
elseif ($DryRun) {
    Write-Step "[dry-run] would remove any existing '$TaskName' task / '$substFallbackName' Run entry, unmount P: (subst /D + net use /delete), then remap P: (elevated: loopback share '\\localhost\$ShareName' -> $CCRoot via net use /persistent:yes; unelevated: logon task + '$SubstCommand')"
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
        # Not "re-run elevated" -- see INST-1. An admin Command Prompt is the
        # right tool for this one command; an admin install is not.
        Write-Warn2 "could not remove the old scheduled task '$TaskName': $($_.Exception.Message). Harmless -- the install continues. To clear it, open an administrator Command Prompt and run:  schtasks /Delete /TN $TaskName /F"
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
    # Routed through Invoke-MappingCommand so an elevated run tears down the
    # mapping in the session that actually holds it (the user's), not this
    # process's private view of it.
    Invoke-MappingCommand "subst P: /D" | Out-Null
    Invoke-MappingCommand "net use P: /delete /y" | Out-Null

    # -- recreate. Preferred style: a private loopback SMB share of the
    # local root, mapped with `net use /persistent:yes`. Explorer honors
    # _LabelFromReg display names for net-use drives (section 5b) but
    # ignores every known labelling mechanism for subst drives (DriveIcons
    # DefaultLabel under HKCU and HKLM, autorun.inf -- all tested dead on
    # Win11 26200), and a persistent mapping self-restores at logon with no
    # scheduled task at all.
    #
    # Split responsibilities carefully: creating the SHARE needs admin (one
    # UAC prompt when unelevated), but the `net use` MAPPING must run in
    # THIS process at the user's normal integrity level -- a drive mapped
    # by an elevated token is invisible to the user's unelevated session
    # (UAC linked-token isolation), which would leave Resolve staring at a
    # missing P: until the next logon. If the share can't be created (UAC
    # declined, SMB server off), fall back to the old subst + logon-task
    # style: everything works, the drive just shows the host volume's name.
    $script:PMappedViaShare = $false
    $shareReady = $false
    $existingShare = $null
    try { $existingShare = Get-SmbShare -Name $ShareName -ErrorAction SilentlyContinue } catch {}
    if ($existingShare -and $existingShare.Path -eq $CCRoot) {
        Write-Skip "loopback share '$ShareName' already -> $CCRoot"
        $shareReady = $true
    }
    elseif ($IsElevated) {
        try {
            if ($existingShare) {
                Remove-SmbShare -Name $ShareName -Force -Confirm:$false -ErrorAction Stop
                Write-Step "removed stale share '$ShareName' (pointed at $($existingShare.Path))"
            }
            New-SmbShare -Name $ShareName -Path $CCRoot -FullAccess "$env:USERDOMAIN\$env:USERNAME" -ErrorAction Stop | Out-Null
            Write-Step "created loopback share '$ShareName' -> $CCRoot"
            $shareReady = $true
        }
        catch {
            Write-Warn2 "could not create share '$ShareName': $($_.Exception.Message) -- falling back to subst"
        }
    }
    else {
        # One-off elevated helper for just the share. -File + argument array
        # keeps paths with spaces intact (no nested-quote surgery).
        try {
            $helperPath = Join-Path $env:TEMP "ccsync_make_share.ps1"
            @'
param([string]$Name, [string]$Path, [string]$Grantee)
$ErrorActionPreference = "Stop"
$existing = Get-SmbShare -Name $Name -ErrorAction SilentlyContinue
if ($existing -and $existing.Path -ne $Path) {
    Remove-SmbShare -Name $Name -Force -Confirm:$false
    $existing = $null
}
if (-not $existing) {
    New-SmbShare -Name $Name -Path $Path -FullAccess $Grantee | Out-Null
}
'@ | Set-Content -LiteralPath $helperPath -Encoding UTF8
            Write-Step "creating the '$ShareName' share needs administrator rights -- approve the UAC prompt..."
            $proc = Start-Process powershell -Verb RunAs -Wait -PassThru -ArgumentList @(
                "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $helperPath,
                "-Name", $ShareName, "-Path", $CCRoot, "-Grantee", "$env:USERDOMAIN\$env:USERNAME"
            )
            $madeShare = $null
            try { $madeShare = Get-SmbShare -Name $ShareName -ErrorAction SilentlyContinue } catch {}
            if ($proc.ExitCode -eq 0 -and $madeShare -and $madeShare.Path -eq $CCRoot) {
                Write-Step "created loopback share '$ShareName' -> $CCRoot"
                $shareReady = $true
            }
            else {
                Write-Warn2 "share helper exited with code $($proc.ExitCode) -- falling back to subst"
            }
        }
        catch {
            Write-Warn2 "UAC declined or share creation failed: $($_.Exception.Message) -- falling back to subst (P: will show the host volume's name in Explorer)"
        }
    }

    if ($shareReady) {
        $mappedOk = Invoke-MappingCommand "net use P: \\localhost\$ShareName /persistent:yes" `
            "mapped P: -> \\localhost\$ShareName (persistent -- no logon task needed)"
        if ($mappedOk) {
            if (-not $IsElevated) {
                Write-Step "mapped P: -> \\localhost\$ShareName (persistent -- no logon task needed)"
            }
            $script:PMappedViaShare = $true
        }
        else {
            Write-Warn2 "net use P: \\localhost\$ShareName failed -- falling back to subst"
        }
    }

    if (-not $script:PMappedViaShare) {
        # -- subst fallback: logon task (elevated) or Run-entry, then map now --
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
                Write-Warn2 "P: will NOT be remapped automatically at logon. Run '$SubstCommand' by hand after each reboot, or tell the admin -- do NOT re-run this script as administrator to try to fix it, that makes P: invisible to Resolve."
            }
        }

        $substOk = Invoke-MappingCommand $SubstCommand "mapped P: -> $CCRoot"
        if ($substOk) {
            if (-not $IsElevated) {
                Write-Step "mapped P: -> $CCRoot"
            }
        }
        else {
            Write-Warn2 "'$SubstCommand' failed -- something may still have files open on the old P:"
        }
    }
}  # end: P: is ours, safe to remap

if ($script:MappedWhileElevated) {
    Write-Host ""
    Write-Host "[ccsync] ******************************************************************" -ForegroundColor Red
    Write-Warn2 "P: HAD TO BE MAPPED FROM THIS ELEVATED WINDOW."
    Write-Warn2 "Windows keeps elevated and normal drive letters apart, so P: does NOT exist yet for DaVinci Resolve, Explorer, or the companion app."
    Write-Warn2 "LOG OFF AND BACK ON (or restart) BEFORE OPENING RESOLVE. After that P: is there for good."
    Write-Warn2 "Do not re-run this installer to 'fix' it -- it will report success from this window every time."
    Write-Host "[ccsync] ******************************************************************" -ForegroundColor Red
    Write-Host ""
}

# --------------------------------------------------------------------
# 5b. Name the P: drive in Explorer
# --------------------------------------------------------------------
# Only net-use (network-style) drives can be display-named: Explorer reads
# the per-user MountPoints2 _LabelFromReg value for them -- the same value
# it writes when a user F2-renames a network drive. For subst drives every
# known mechanism is ignored on current Windows 11 (DriveIcons DefaultLabel
# under both HKCU and HKLM, autorun.inf label= -- all verified dead on
# build 26200): they always show the host volume's label. That asymmetry is
# WHY section 5 prefers the loopback-share mapping.
Write-Step "labelling the P: drive as '$DriveLabel' in Explorer..."
if ($script:PIsForeign) {
    # Section 5 refused to touch this mapping; renaming it in Explorer is the
    # same mistake in cosmetic form -- and _LabelFromReg would then persist on
    # someone else's mount point long after this script is forgotten (INST-15).
    Write-Skip "P: is not this installer's mapping -- leaving its Explorer name alone too"
}
elseif ($DryRun) {
    Write-Step "[dry-run] would set MountPoints2 _LabelFromReg = $DriveLabel for P:'s UNC path (net-use mappings only)"
}
else {
    try {
        $displayRoot = $null
        try { $displayRoot = (Get-PSDrive -Name P -ErrorAction Stop).DisplayRoot } catch {}
        if ([string]::IsNullOrWhiteSpace($displayRoot) -and $script:PMappedViaShare) {
            # Elevated run: the mapping was deliberately made in the user's
            # own session, so it is invisible from here. We still know what
            # it points at, and the label key is per-user, not per-token.
            $displayRoot = "\\localhost\$ShareName"
        }
        if ([string]::IsNullOrWhiteSpace($displayRoot)) {
            # Deliberately does NOT say "re-run as administrator": an elevated
            # run maps P: into a token the editor's own session cannot see,
            # which is a far worse outcome than a drive showing the wrong
            # name (INST-1). The labelled mapping comes from approving the
            # one UAC prompt this script raises for the share, from a NORMAL
            # PowerShell window.
            Write-Warn2 "P: is a subst mapping, so Explorer will show the host volume's name instead of '$DriveLabel'. Cosmetic only -- everything syncs exactly the same. To get the nicer name, re-run this script from a NORMAL (non-administrator) PowerShell window and approve the single UAC prompt it raises for the '$ShareName' share."
        }
        else {
            # \\localhost\CCSync_P -> ##localhost#CCSync_P
            $mpName = "##" + $displayRoot.TrimStart("\").Replace("\", "#")
            $mpKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\MountPoints2\$mpName"
            $currentLabel = $null
            if (Test-Path -LiteralPath $mpKey) {
                $currentLabel = (Get-ItemProperty -LiteralPath $mpKey -ErrorAction SilentlyContinue)._LabelFromReg
            }
            if ($currentLabel -eq $DriveLabel) {
                Write-Skip "P: already labelled '$DriveLabel' in Explorer"
            }
            else {
                # New-Item -Force on a registry key that ALREADY EXISTS
                # deletes every other value under it (verified live) --
                # MountPoints2 entries carry more than just _LabelFromReg.
                # Only create the key when it's actually missing.
                if (-not (Test-Path -LiteralPath $mpKey)) {
                    New-Item -Path $mpKey -Force | Out-Null
                }
                Set-ItemProperty -LiteralPath $mpKey -Name "_LabelFromReg" -Value $DriveLabel
                Write-Step "labelled P: as '$DriveLabel' ($mpName)"
                # This used to force-kill explorer.exe to make the new name
                # show immediately. Never again: Stop-Process -Force kills
                # EVERY Explorer in reach (all sessions when elevated -- other
                # logged-in users lose their shell, and nothing restarts it),
                # and it aborts any Explorer file copy in flight mid-file,
                # leaving a truncated destination that lane A then uploads and,
                # thanks to --ignore-existing, never replaces (INST-18).
                # SHChangeNotify asks the shell to re-read the drive instead;
                # if that doesn't take, the name is correct at next sign-in.
                $refreshed = $false
                try {
                    if (-not ("CCSync.Shell32" -as [type])) {
                        Add-Type -Namespace CCSync -Name Shell32 -MemberDefinition @'
[System.Runtime.InteropServices.DllImport("shell32.dll")]
public static extern void SHChangeNotify(int eventId, uint flags, System.IntPtr item1, System.IntPtr item2);
'@ -ErrorAction Stop
                    }
                    # SHCNE_UPDATEDIR (0x1000) with SHCNF_PATHW (0x0005) on
                    # the drive root, then SHCNE_ASSOCCHANGED (0x08000000).
                    [CCSync.Shell32]::SHChangeNotify(0x08000000, 0x0000, [System.IntPtr]::Zero, [System.IntPtr]::Zero)
                    $refreshed = $true
                }
                catch {
                    $refreshed = $false
                }
                if ($refreshed) {
                    Write-Step "asked Explorer to refresh (SHChangeNotify) -- if P: still shows its old name, it will be correct at your next sign-in"
                }
                else {
                    Write-Step "the '$DriveLabel' name on P: will appear the next time you sign in (Explorer caches drive names; nothing else is affected)"
                }
            }
        }
    }
    catch {
        Write-Warn2 "could not set the Explorer label for P:: $($_.Exception.Message) -- cosmetic only, everything else still works."
    }
}

function Ensure-NasSyncthingDevice {
    # Make sure this machine's Syncthing knows the NAS as a device, via the
    # REST API of the RUNNING instance (an XML edit behind a live daemon is
    # silently overwritten). Without this entry a fresh `syncthing generate`
    # config drops every NAS connection as "unknown device" one second after
    # hello, in a permanent reconnect loop (alex_laptop, 2026-07-26).
    #
    # autoAcceptFolders stays FALSE on purpose: folder offers are accepted by
    # the companion's sequencer at the CORRECT local path. Syncthing's own
    # auto-accept sanitizes the slash-labelled folders this deployment uses
    # ("2026/CCT/..." -> "2026 CCT ...") into a flat dir at defaultFolderPath,
    # which nothing else in the system would recognize.
    #
    # Warns and returns on every failure -- never throws, never blocks the
    # remaining steps.
    param(
        [string]$ConfigXmlPath,
        [string]$DeviceId,
        [string]$NasHost
    )
    try {
        if (-not (Test-Path -LiteralPath $ConfigXmlPath)) {
            Write-Warn2 "no Syncthing config.xml at $ConfigXmlPath -- cannot seed the NAS device"
            return
        }
        [xml]$cfgXml = Get-Content -LiteralPath $ConfigXmlPath -Raw
        $apiKey = "$($cfgXml.configuration.gui.apikey)"
        $guiAddress = "$($cfgXml.configuration.gui.address)"
        if (-not $guiAddress) { $guiAddress = "127.0.0.1:8384" }
        if (-not $apiKey) {
            Write-Warn2 "no API key in $ConfigXmlPath -- cannot seed the NAS device"
            return
        }
        $base = "http://$guiAddress"
        $headers = @{ "X-API-Key" = $apiKey }

        $alive = $false
        for ($i = 0; $i -lt 20; $i++) {
            try {
                $null = Invoke-RestMethod -Headers $headers -Uri "$base/rest/system/ping" -TimeoutSec 3
                $alive = $true
                break
            }
            catch {
                $httpStatus = 0
                try { $httpStatus = [int]$_.Exception.Response.StatusCode } catch {}
                if ($httpStatus -eq 401 -or $httpStatus -eq 403) {
                    # Running, but it is NOT the instance this config belongs
                    # to -- another Syncthing home owns the port. Seeding
                    # would land in the wrong (or an ignored) config.
                    Write-Warn2 "the Syncthing at $base rejected this config's API key -- a Syncthing from a different home owns the port. NOT seeding the NAS device; lane C needs that untangled first."
                    return
                }
                Start-Sleep -Seconds 1
            }
        }
        if (-not $alive) {
            Write-Warn2 "Syncthing REST at $base did not come up within 20s -- NOT seeding the NAS device (re-run this script once it is running)"
            return
        }

        $devices = @(Invoke-RestMethod -Headers $headers -Uri "$base/rest/config/devices" -TimeoutSec 10)
        if ($devices | Where-Object { $_.deviceID -eq $DeviceId }) {
            Write-Skip "NAS device already in the Syncthing config ($($DeviceId.Substring(0,7))...)"
            return
        }
        $body = @{
            deviceID          = $DeviceId
            name              = "truenas"
            addresses         = @("tcp://${NasHost}:22000", "dynamic")
            compression       = "metadata"
            introducer        = $false
            paused            = $false
            autoAcceptFolders = $false
        } | ConvertTo-Json
        $null = Invoke-RestMethod -Method Post -Headers $headers -Uri "$base/rest/config/devices" `
            -Body $body -ContentType "application/json" -TimeoutSec 10
        Write-Step "seeded the NAS device ($($DeviceId.Substring(0,7))...) into Syncthing -- pairing needs no GUI clicks on either side"
    }
    catch {
        Write-Warn2 "could not seed the NAS Syncthing device: $($_.Exception.Message)"
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
    if ($NasSyncthingId) {
        Write-Step "[dry-run] would seed the NAS device $NasSyncthingId (addresses tcp://${TailnetHost}:22000, dynamic) into the running Syncthing via REST"
    }
}
elseif (-not $syncthingPath) {
    # A null path here would run `& $null generate ...`, a terminating error
    # under $ErrorActionPreference = "Stop" that aborts the whole script
    # AFTER _clean_slate has already removed the previous install (S-3).
    # Skip loudly instead -- steps 7-10 still run.
    Write-Warn2 "Syncthing executable path is unknown -- skipping config generation, daemon autostart, and launch. Install Syncthing manually (https://syncthing.net/downloads/) and re-run this script."
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

    # The Run value points at the .vbs shim, so it looks identical no matter
    # WHERE Syncthing was found -- the real command line lives in the .cmd
    # beside it. Checking only that the registry value exists reported "already
    # registered" for an entry whose .cmd still launched a syncthing.exe that
    # had since been uninstalled, moved by a winget upgrade, or replaced by a
    # different install path: Syncthing then never starts at logon and lane C
    # is silently dead, with a green install behind it. macOS already compares
    # the plist's Program against the detected binary (macos_bootstrap.sh);
    # Windows never got the same check. Compare the baked line, and repair.
    $stCmdPath = "$BinDir\$stRunName.cmd"
    $stBakedOk = $false
    if ($existingStRun -and (Test-Path -LiteralPath $stCmdPath)) {
        try {
            $stBaked = Get-Content -LiteralPath $stCmdPath -Raw -ErrorAction Stop
            if ("$stBaked" -match [regex]::Escape($syncthingPath)) { $stBakedOk = $true }
        }
        catch {
            $stBakedOk = $false
        }
    }

    if ($existingStRun -and $stBakedOk) {
        Write-Skip "Syncthing autostart already registered and pointing at $syncthingPath"
    }
    else {
        if ($existingStRun) {
            Write-Step "Syncthing autostart exists but its command line does not point at $syncthingPath -- rewriting it"
        }
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

    if ($NasSyncthingId) {
        Ensure-NasSyncthingDevice -ConfigXmlPath "$SyncthingHome\config.xml" `
            -DeviceId $NasSyncthingId -NasHost $TailnetHost
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
$stanzaMatches = $false
$existingHost = ""
$existingUser = ""
if (Test-Path -LiteralPath $RcloneConfPath) {
    # -Encoding UTF8 explicitly: this script APPENDS to rclone.conf as
    # no-BOM UTF-8 (below), and Get-Content with no -Encoding falls back to
    # the system ANSI codepage for a BOM-less file. A non-ASCII value then
    # reads back mangled, the -match duplicate detection misses, and a
    # SECOND [creators_club_sftp] block gets appended (INST-3).
    $existingConf = Get-Content -LiteralPath $RcloneConfPath -Raw -Encoding UTF8
    if ($null -eq $existingConf) { $existingConf = "" }
    if ($existingConf -match [Regex]::Escape("[$RemoteName]")) {
        $hasSection = $true
        # Pull host/user out of THIS stanza only: from its header up to the
        # next [section] header or end of file.
        # SINGLE-quoted fragments: in a double-quoted PowerShell string
        # "$(.*?)" is a subexpression, not a regex capture group.
        $sectionPattern = '(?ms)^\[' + [Regex]::Escape($RemoteName) + '\]\s*$(.*?)(?=^\[|\z)'
        $sectionMatch = [regex]::Match($existingConf, $sectionPattern)
        if ($sectionMatch.Success) {
            $body = $sectionMatch.Groups[1].Value
            $hostMatch = [regex]::Match($body, '(?m)^\s*host\s*=\s*(.*?)\s*$')
            if ($hostMatch.Success) { $existingHost = $hostMatch.Groups[1].Value }
            $userMatch = [regex]::Match($body, '(?m)^\s*user\s*=\s*(.*?)\s*$')
            if ($userMatch.Success) { $existingUser = $userMatch.Groups[1].Value }
        }
        $stanzaMatches = ($existingHost -ceq $TailnetHost) -and ($existingUser -ceq $EditorName)
    }
}

if ($hasSection -and $stanzaMatches) {
    Write-Skip "rclone.conf already has a correct [$RemoteName] section: $RcloneConfPath"
}
elseif ($hasSection) {
    # The single most likely reason to re-run this script is a typo'd
    # -EditorName -- and skipping the whole stanza whenever the section
    # exists made that re-run a silent no-op for the one file that carries
    # the username (INST-17). Rewrite this stanza in place; every other
    # remote in the file is preserved byte-for-byte.
    Write-Warn2 "rclone.conf's [$RemoteName] disagrees with the values you passed:"
    Write-Warn2 "  host: '$existingHost' -> '$TailnetHost'"
    Write-Warn2 "  user: '$existingUser' -> '$EditorName'"
    if ($DryRun) {
        Write-Step "[dry-run] would rewrite the [$RemoteName] stanza in $RcloneConfPath (other remotes untouched):"
        Write-Host $Stanza
    }
    else {
        $sectionPattern = '(?ms)^\[' + [Regex]::Escape($RemoteName) + '\]\s*$.*?(?=^\[|\z)'
        $replacement = $Stanza + "`r`n`r`n"
        # Instance Regex + a MatchEvaluator: the static Replace has no
        # count overload, and a literal replacement string would treat any
        # '$' in the editor name / host as a capture-group reference.
        $rx = New-Object System.Text.RegularExpressions.Regex($sectionPattern)
        $evaluator = [System.Text.RegularExpressions.MatchEvaluator]{ param($m) $replacement }
        $newConf = $rx.Replace($existingConf, $evaluator, 1)
        $utf8NoBom = New-Object System.Text.UTF8Encoding $false
        [System.IO.File]::WriteAllText($RcloneConfPath, $newConf, $utf8NoBom)
        Write-Step "rewrote the [$RemoteName] stanza in $RcloneConfPath (host=$TailnetHost, user=$EditorName)"
    }
}
else {
    if ($DryRun) {
        Write-Step "[dry-run] would append this stanza to $RcloneConfPath :"
        Write-Host $Stanza
    }
    else {
        # Add-Content with no -Encoding writes the system ANSI codepage: a
        # non-ASCII -TailnetHost/-EditorName lands mangled, and appending
        # ANSI bytes onto an existing UTF-8 rclone.conf mixes encodings in
        # one file. [IO.File]::AppendAllText with an explicit no-BOM UTF8
        # encoding avoids both.
        $utf8NoBom = New-Object System.Text.UTF8Encoding $false
        [System.IO.File]::AppendAllText($RcloneConfPath, "`r`n$Stanza`r`n", $utf8NoBom)
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
        # PS 5.1's Set-Content -Encoding UTF8 emits a BOM even for a new
        # file. tomllib.load rejects a BOM outright, and load_config swallows
        # that exception with no log line -- the companion silently runs on
        # DEFAULTS (blank local_root/remote_root/editor_name/token) while
        # config.toml looks perfectly correct to a human (S-2).
        $utf8NoBom = New-Object System.Text.UTF8Encoding $false
        [System.IO.File]::WriteAllText($CCSyncConfigPath, "$CompanionToml`r`n", $utf8NoBom)
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

        # Carry the release manifest (written by tools\release.ps1, shipped in
        # the package by build_editor_package.ps1) next to the installed exe.
        # Without it nothing on the machine can say WHICH build is installed --
        # the exe has no --version flag -- which is how a rig ran v0.4.3 for an
        # afternoon while every fix was being verified against v0.4.5
        # (2026-07-25; see docs\RELEASE.md). Copied only when it matches the
        # exe actually installed; a mismatched or absent manifest leaves no
        # claim rather than a false one.
        $srcManifest = Join-Path (Split-Path -Parent $CompanionExeSource) "ccsync-release.json"
        $destManifest = Join-Path (Split-Path -Parent $CompanionExePath) "ccsync-release.json"
        if ((Test-Path -LiteralPath $srcManifest) -and -not $DryRun) {
            try {
                $srcSha = (Get-FileHash -Algorithm SHA256 -LiteralPath $CompanionExeSource).Hash.ToLower()
                $rel = Get-Content -LiteralPath $srcManifest -Raw -Encoding UTF8 | ConvertFrom-Json
                if ("$($rel.sha256)" -eq $srcSha) {
                    Copy-Item -LiteralPath $srcManifest -Destination $destManifest -Force
                    Write-Step "companion build: v$($rel.version_stamp) (built $($rel.built_at))"
                }
                else {
                    Write-Warn2 "ccsync-release.json in the package describes a different exe -- not recording a version"
                }
            }
            catch {
                Write-Warn2 "could not record the companion build version: $($_.Exception.Message)"
            }
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
    # --- Resolve preferences: LUT library + shared gallery -----------------
    # Done BEFORE the companion is launched, and by the companion exe itself
    # (--setup-resolve-prefs), so there is ONE implementation of "edit
    # Resolve's two preference files correctly" rather than a second one in
    # PowerShell and a third in bash. It exits non-zero when it could not
    # apply them, which is deliberately not fatal here: the running companion
    # re-checks on its own schedule, so the worst case is that these arrive
    # the next time Resolve is closed.
    #
    # Resolve rewrites both preference files from memory when it exits, so an
    # edit made while it is running is silently discarded -- hence the wait
    # rather than a best-effort write. The exe prints the "please quit
    # Resolve" line itself and continues the moment it sees Resolve go.
    if ($DryRun) {
        Write-Step "[dry-run] would run: $CompanionExePath --setup-resolve-prefs"
    }
    elseif (Test-Path -LiteralPath $CompanionExePath) {
        Write-Step "pointing Resolve at the shared LUT library and stills folder..."
        try {
            & $CompanionExePath --setup-resolve-prefs --wait-for-resolve $ResolvePrefsWaitSeconds 2>&1 |
                ForEach-Object { Write-Host "    $_" }
            if ($LASTEXITCODE -ne 0) {
                Write-Warn2 "Resolve's LUT/stills preferences were not set now -- the companion will apply them the next time Resolve is closed"
            }
        }
        catch {
            Write-Warn2 "could not set Resolve's LUT/stills preferences: $($_.Exception.Message) -- the companion retries on its own"
        }
    }

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

    # NO PowerShell-level `2>&1` here. Under $ErrorActionPreference = "Stop"
    # it wraps the FIRST stderr line a native command writes in a fatal
    # NativeCommandError, so one ordinary progress line from `syncthing
    # generate` aborted the whole assignment and the editor was told the
    # device ID could not be determined (INST-16, measured). Un-redirected
    # stderr is harmless -- it just goes to the console. Syncthing prints the
    # ID on stdout, which is all we parse.
    try {
        $genOutput = & $ExePath generate --home="$Home2" | Out-String
        $m = [regex]::Match($genOutput, "device=([A-Z0-9]{7}(?:-[A-Z0-9]{7}){7})")
        if ($m.Success) { return $m.Groups[1].Value }
    }
    catch {
        Write-Warn2 "syncthing generate failed: $($_.Exception.Message)"
    }

    try {
        $legacy = & $ExePath --device-id --home="$Home2" | Out-String
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
    if (-not $syncthingPath) {
        # No `& $null generate ...` here (S-3's terminating RuntimeException)
        # -- the banner and remaining-steps list below still print.
        Write-Warn2 "Syncthing executable path is unknown -- cannot determine the device ID automatically."
        $deviceId = $null
    }
    else {
        $deviceId = Get-SyncthingDeviceId -ExePath $syncthingPath -Home2 $SyncthingHome
    }

    Write-Host ""
    Write-Host "=================================================================="
    Write-Host " Bootstrap complete."
    Write-Host ""
    if ($null -eq $deviceId) {
        Add-CapabilityMiss "the Syncthing device ID could NOT be determined. The admin cannot approve this machine without it, so lane C (audio, AE, graphics, subtitles, .drp project files, docs) will never sync. Get it from the Syncthing web UI at http://127.0.0.1:8384 under Actions > Show ID and send it to the admin."
    }
    else {
        Write-Host " Your Syncthing device ID is:"
        Write-Host ""
        Write-Host "     $deviceId" -ForegroundColor Cyan
        Write-Host ""
        Write-Host " Send this device ID to the admin so they can approve this machine"
        Write-Host " on the dashboard. There is no per-project sharing step for you to"
        Write-Host " do -- once you're approved, ticking a project on the dashboard"
        Write-Host " is what shares it."
    }
    Write-Host ""
    Write-Host " Remaining manual steps (see docs/EDITOR_SETUP.md):"
    Write-Host "   1. tailscale up   (join the tailnet, one-time interactive login)"
    Write-Host "   2. generate an SSH keypair for rclone if you haven't already:"
    Write-Host "        ssh-keygen -t ed25519 -f `"$KeyFilePath`""
    Write-Host "      and send the .pub file to the admin"
    Write-Host "   3. SIGN IN: right-click the CCSync tray icon (bottom-right of"
    Write-Host "      your taskbar) and choose `"Sign in...`", then enter the SAME"
    Write-Host "      TrueNAS username and password the admin gave you."
    Write-Host "      NOTHING SYNCS UNTIL YOU DO THIS -- the companion deliberately"
    Write-Host "      refuses to touch your files until it knows who you are, and"
    Write-Host "      signing in on the dashboard WEBSITE is not the same thing."
    Write-Host "      (If you installed via onboard.exe this is already done.)"
    Write-Host "   4. connect DaVinci Resolve to the Project Server"
    Write-Host "   5. Playback > Proxy Handling > Prefer Proxies"
    Write-Host "   6. do NOT map any NAS share to another drive letter -- see the"
    Write-Host "      drive-letter warning in docs/EDITOR_SETUP.md"
    Write-Host "=================================================================="
}

# --------------------------------------------------------------------
# 11. Exit code
# --------------------------------------------------------------------
# Everything above warns and carries on -- correct, because a half-installed
# machine beats an aborted one. But the script used to exit 0 regardless, so
# onboard.exe (which branches only on the exit code) showed a green DONE page
# for a machine with no rclone, no Syncthing and no device ID -- after
# clean-slate had already removed the previous working install (INST-5).
if ($script:CapabilityMisses.Count -gt 0) {
    Write-Host ""
    Write-Host "[ccsync] ==================================================================" -ForegroundColor Red
    Write-Host "[ccsync] THIS MACHINE IS NOT READY TO SYNC -- $($script:CapabilityMisses.Count) required piece(s) are missing:" -ForegroundColor Red
    $missIndex = 1
    foreach ($miss in $script:CapabilityMisses) {
        Write-Host "[ccsync]   $missIndex. $miss" -ForegroundColor Red
        $missIndex = $missIndex + 1
    }
    Write-Host "[ccsync] Everything else installed fine. Fix the above and re-run this script -- it is safe to re-run." -ForegroundColor Red
    Write-Host "[ccsync] Do NOT tell the admin you are set up yet." -ForegroundColor Red
    Write-Host "[ccsync] ==================================================================" -ForegroundColor Red
    exit 3
}
exit 0
