#requires -Version 5.1
<#
.SYNOPSIS
    Upgrade an existing CCSync install to a newer companion build, in place.

.DESCRIPTION
    For a machine that already ran installer/windows_bootstrap.ps1. Swaps in
    the new companion and leaves EVERYTHING else alone -- the Syncthing device
    identity, the rclone SSH key + config, the tree drive mapping, and the
    editor's settings all survive, so there is nothing for the admin to
    re-approve. Steps:

      1. Stop the running companion (packaged exe or source-mode pythonw).
      2. Copy the new ccsync-companion.exe into %LOCALAPPDATA%\ccsync\bin.
      3. Re-register the companion autostart (points at that exe).
      4. Add any config keys the new version needs that the file is missing
         (never overwrites existing values) -- and set dashboard_token if you
         pass -DashboardToken.
      5. Relaunch the companion -- and confirm it is STILL RUNNING three
         seconds later. A build that dies on startup is a failed upgrade,
         not a completed one (SHIP-2); this script exits 1 for it.
      6. Launch the setup wizard IF the licence agreement has not been
         accepted on this machine, or the build brings a newer one. Since
         0.8.0 the companion refuses to start its sync lanes without a
         current acceptance, and nothing else on the upgrade path asks for
         one -- see the note above step 6 below.

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
    # <token> is the 48-hex fleet token your admin gave you. Deliberately NOT
    # a real value: this file ships to every editor inside the CC_Sync package
    # (build_editor_package.ps1), and a literal token in the help text is a
    # published credential. Note also that the value lands on this process's
    # command line, which any unprivileged process on the machine can read via
    # Get-CimInstance Win32_Process -- prefer letting onboard.exe write
    # dashboard_token into ~/.ccsync/config.toml and omitting this parameter.
    .\windows_upgrade.ps1 -DashboardToken <token>
#>
[CmdletBinding()]
param(
    [string]$CompanionExe = "",
    [string]$DashboardToken = "",
    # Only used when config.toml has no dashboard_url yet (a machine that
    # predates the wizard). There is no compiled-in default any more -- it
    # used to be one deployment's tailnet IP (WP0, 2026-08-17) -- so with
    # neither this flag, $env:CCSYNC_DASHBOARD_URL, nor a URL already in the
    # file, the key is left absent and said out loud rather than invented.
    [string]$DashboardUrl = "",
    # Do not launch the setup wizard even when the licence agreement is
    # unaccepted (step 6). For an unattended re-run where a human is not
    # sitting in front of the machine to read it -- the machine stays
    # NOT SYNCING until somebody does, which the summary says out loud.
    [switch]$SkipWizard,
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
$DefaultDashboardUrl = $DashboardUrl
if (-not $DefaultDashboardUrl -and $env:CCSYNC_DASHBOARD_URL) {
    $DefaultDashboardUrl = $env:CCSYNC_DASHBOARD_URL
}

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

# The rest of the package travels with that exe, not with this script: -DryRun
# aside, ship.ps1 and check_deploy_drift.ps1 both pass -CompanionExe pointing
# into a staged package while running the copy of this script in the repo.
# onboard.exe and EULA.md are read from beside the BUILD (step 6).
$PackageDir = Split-Path -Parent (Resolve-Path -LiteralPath $CompanionExe)
$OnboardExe = Join-Path $PackageDir "onboard.exe"

# --- which version IS this? -----------------------------------------------
# The exe has no --version flag (it is a windowed PyInstaller build), so an
# upgrade used to be entirely version-blind: it reported a path and a
# timestamp and nothing about what it was actually installing. That is how a
# machine spent an afternoon on v0.4.3 while everyone believed it had v0.4.5
# (2026-07-25 -- see docs\RELEASE.md). tools\release.ps1 writes
# ccsync-release.json next to the exe and build_editor_package.ps1 ships it
# inside the package, so when it is there we can name the build, and we copy
# it alongside the installed exe so tools\check_deploy_drift.ps1 can name it
# later too. A package built before this existed simply says "unknown".
$SrcManifest = Join-Path (Split-Path -Parent $srcInfo.FullName) "ccsync-release.json"
$DestManifest = Join-Path $BinDir "ccsync-release.json"
$srcSha = (Get-FileHash -Algorithm SHA256 -LiteralPath $CompanionExe).Hash.ToLower()
$NewVersion = ""
if (Test-Path -LiteralPath $SrcManifest) {
    try {
        $rel = Get-Content -LiteralPath $SrcManifest -Raw -Encoding UTF8 | ConvertFrom-Json
        if ("$($rel.sha256)" -eq $srcSha) {
            $NewVersion = "$($rel.version_stamp)"
            Write-Step "version: v$NewVersion (built $($rel.built_at) from $($rel.git_describe))"
            if ($rel.git_dirty) { Write-Warn2 "this build came from an uncommitted tree -- fine for testing, not for the fleet" }
        }
        else {
            Write-Warn2 "ccsync-release.json next to the new exe describes a DIFFERENT file -- ignoring it; version unknown"
            $SrcManifest = ""
        }
    }
    catch {
        Write-Warn2 "could not read $SrcManifest -- version unknown"
        $SrcManifest = ""
    }
}
else {
    Write-Step "version: unknown (no ccsync-release.json beside the exe; build with tools\release.ps1)"
    $SrcManifest = ""
}
Write-Step "sha256: $srcSha"

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
# The companion was just force-killed above; if the 800ms wait wasn't enough
# (AV scanning the exe, a lingering handle -- seen live, see
# build_editor_package.ps1's notes), Copy-Item throws under
# $ErrorActionPreference = "Stop". Retry rather than let that abort the
# script here -- it would leave the editor with the companion already
# killed and steps 3-5 (autostart, config migration, relaunch) never run,
# i.e. strictly worse than not upgrading at all.
$copySucceeded = $false
if ($DryRun) {
    Write-Step "[dry-run] would copy new exe -> $CompanionExePath"
    $copySucceeded = $true
}
else {
    if (-not (Test-Path -LiteralPath $BinDir)) { New-Item -ItemType Directory -Path $BinDir -Force | Out-Null }
    $maxAttempts = 5
    for ($attempt = 1; $attempt -le $maxAttempts; $attempt++) {
        try {
            Copy-Item -LiteralPath $CompanionExe -Destination $CompanionExePath -Force -ErrorAction Stop
            Write-Step "installed new companion: $CompanionExePath"
            $copySucceeded = $true
            break
        }
        catch {
            if ($attempt -lt $maxAttempts) {
                Write-Warn2 "copy attempt $attempt/$maxAttempts failed ($($_.Exception.Message)) -- retrying in 2s"
                Start-Sleep -Seconds 2
            }
            else {
                Write-Warn2 "could not replace $CompanionExePath after $maxAttempts attempts ($($_.Exception.Message)) -- the OLD companion build is still in place. Close anything that might have it open (Explorer preview, AV scan) and re-run this script."
            }
        }
    }
}

# --- 2b. keep the provenance manifest with the exe it describes -----------
# Only after a successful copy: a manifest describing a build that is not
# actually installed is worse than none (it would make the drift check lie).
# When the new package has no manifest, drop any stale one left by a previous
# upgrade for the same reason.
if ($DryRun) {
    if ($SrcManifest) { Write-Step "[dry-run] would copy ccsync-release.json -> $DestManifest" }
}
elseif ($copySucceeded) {
    if ($SrcManifest) {
        try {
            Copy-Item -LiteralPath $SrcManifest -Destination $DestManifest -Force -ErrorAction Stop
            Write-Step "recorded provenance: $DestManifest"
        }
        catch {
            Write-Warn2 "could not write $DestManifest ($($_.Exception.Message)) -- the install is fine, only the version record is missing"
        }
    }
    elseif (Test-Path -LiteralPath $DestManifest) {
        try {
            Remove-Item -LiteralPath $DestManifest -Force -ErrorAction Stop
            Write-Step "removed the stale ccsync-release.json (it described the previous build)"
        }
        catch { }
    }
}

# --- 3. (re)register autostart ---------------------------------------------
# Always run this (and steps 4-5), even if the copy above ultimately failed:
# the companion was already killed, so re-registering autostart and
# relaunching whatever exe is actually at CompanionExePath (new or, if the
# copy failed, the surviving old one) leaves the machine no worse off.
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
    # -Encoding UTF8 is LOAD-BEARING. config.toml is written as UTF-8 with NO
    # BOM (see the WriteAllText below and windows_bootstrap.ps1's config
    # seeding), and Get-Content with no -Encoding auto-detects a BOM and
    # otherwise falls back to the system ANSI codepage. Reading UTF-8 as ANSI
    # and writing it back as UTF-8 double-encodes every non-ASCII value --
    # permanently, silently, and on EVERY upgrade run, because the result is
    # still valid UTF-8 and valid TOML. Measured: editor_name = "台北-editor"
    # became "å°åŒ—-editor", after which the editor's reports and project
    # selections go to a username that does not exist (INST-3). On READ,
    # PS 5.1's -Encoding UTF8 strips a BOM if present and decodes BOM-less
    # UTF-8 correctly; only writes add one.
    $lines = @(Get-Content -LiteralPath $ConfigPath -Encoding UTF8)
    $text = ($lines -join "`n")
    $added = @()

    function Test-Key { param([string]$key) return ($lines | Where-Object { $_ -match "^\s*$key\s*=" }).Count -gt 0 }

    # TOML keys belong to whatever [section] header precedes them. Appending
    # at EOF is fine for an installer-written config (which has no sections),
    # but ONE hand-added [section] anywhere in the file swallows every key we
    # append -- they then parse as section.mode / section.dashboard_url and
    # are silently ignored, with the file looking perfectly correct. Insert
    # before the first bracketed header instead, which is always top level.
    $firstSectionIndex = -1
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match '^\s*\[') { $firstSectionIndex = $i; break }
    }

    $pending = @()
    function Add-TopLevelKey {
        param([string]$Line)
        $script:pending += $Line
    }

    if (-not (Test-Key "dashboard_url")) {
        if ($DefaultDashboardUrl) {
            Add-TopLevelKey "dashboard_url = `"$DefaultDashboardUrl`""
            $added += "dashboard_url ($DefaultDashboardUrl)"
        }
        else {
            # Naming it beats inventing it: an upgrade that silently wrote
            # somebody else's dashboard URL into this file would point a
            # machine at a deployment it has no account on.
            Write-Warn2 "config.toml has no dashboard_url and none was given (-DashboardUrl / CCSYNC_DASHBOARD_URL) -- this companion will not report, will not take managed sync selections, and will never be offered another upgrade. Ask your admin for the URL and add it."
        }
    }
    if ($DashboardToken) {
        # set/replace the token line explicitly
        if (Test-Key "dashboard_token") {
            $lines = $lines | ForEach-Object { if ($_ -match "^\s*dashboard_token\s*=") { "dashboard_token = `"$DashboardToken`"" } else { $_ } }
        }
        else { Add-TopLevelKey "dashboard_token = `"$DashboardToken`"" }
        $added += "dashboard_token (set from -DashboardToken)"
    }
    elseif (-not (Test-Key "dashboard_token")) {
        Add-TopLevelKey 'dashboard_token = ""'
        $added += "dashboard_token (blank -- fleet reporting stays off until you set it)"
    }
    # mode: default editor; only add if absent so a base rig's mode="base" is
    # kept. Harmless even if wrong: once the editor signs in, the dashboard's
    # role (DASH_ADMIN_USERS) overrides this static value entirely -- see
    # companion app.py's _apply_identity_role()/effective_mode().
    if (-not (Test-Key "mode")) {
        Add-TopLevelKey 'mode = "editor"'
        $added += "mode (editor)"
    }

    if ($script:pending.Count -gt 0) {
        $block = @("", "# -- added by windows_upgrade.ps1 --") + $script:pending + @("")
        if ($firstSectionIndex -ge 0) {
            $head = @()
            if ($firstSectionIndex -gt 0) { $head = $lines[0..($firstSectionIndex - 1)] }
            $tail = $lines[$firstSectionIndex..($lines.Count - 1)]
            $lines = @($head) + @($block) + @($tail)
        }
        else {
            $lines = @($lines) + @($block)
        }
    }

    if ($added.Count -eq 0) {
        Write-Skip "config already has the new keys -- no changes"
    }
    elseif ($DryRun) {
        Write-Step "[dry-run] would add/update in ${ConfigPath}: $($added -join ', ')"
    }
    else {
        # PS 5.1's Set-Content -Encoding UTF8 emits a BOM even for a file
        # that started BOM-less. tomllib rejects it outright, and
        # load_config swallows that exception with no log line -- the
        # companion silently runs on blank DEFAULTS while config.toml looks
        # correct to a human (S-2).
        $utf8NoBom = New-Object System.Text.UTF8Encoding $false
        [System.IO.File]::WriteAllText($ConfigPath, (($lines -join "`r`n") + "`r`n"), $utf8NoBom)
        Write-Step "config updated ($ConfigPath): $($added -join ', ')"
    }
}

# Tighten the two files that hold the fleet token in clear text, on every
# upgrade -- that is how the machines provisioned before 2026-08-17 get the
# fix, since they will never run the bootstrap again (COMMERCIAL_READINESS.md
# item 15; macOS has chmod 600 on both, Windows set no ACL at all).
# Best-effort and quiet: a permissions cosmetic must never fail an upgrade
# that has already swapped the exe.
foreach ($secretFile in @($ConfigPath, "$env:USERPROFILE\.ccsync\identity.json")) {
    if (-not (Test-Path -LiteralPath $secretFile)) { continue }
    if ($DryRun) {
        Write-Step "[dry-run] would restrict $secretFile to $env:USERNAME + SYSTEM + Administrators"
        continue
    }
    try {
        # icacls, not Set-Acl: PS 5.1's Set-Acl needs a full SDDL round-trip to
        # drop inheritance. Redirection inside cmd, or a native stderr write is
        # fatal under $ErrorActionPreference = 'Stop'.
        $me = "$env:USERDOMAIN\$env:USERNAME"
        cmd /c "icacls `"$secretFile`" /inheritance:r /grant:r `"$me`":(F) `"*S-1-5-18`":(F) `"*S-1-5-32-544`":(F) >nul 2>&1"
        if ($LASTEXITCODE -ne 0) {
            Write-Warn2 "could not tighten the permissions on $secretFile (icacls exit $LASTEXITCODE) -- it holds your fleet token"
        }
    }
    catch {
        Write-Warn2 "could not tighten the permissions on $secretFile ($($_.Exception.Message)) -- it holds your fleet token"
    }
}

# --- 5. relaunch ------------------------------------------------------------
# Always runs, even after a failed copy above -- see the note on step 3.
# GUARDED: where the copy failed all 5 times and no prior exe exists,
# Start-Process under $ErrorActionPreference = "Stop" is a terminating error
# that kills the script before the summary below -- i.e. the one place that
# would have explained why. Test first and carry on.
#
# AND CONFIRMED ALIVE (SHIP-2, 2026-08-14). Start-Process succeeding means
# CreateProcess succeeded and nothing more: a build that dies a second later
# (a frozen-build DLL/config failure, an unparseable config.toml) still
# produced "Upgrade complete -- now running v<X>" and exit 0, so ship.ps1 --
# which gates on this exit code alone -- printed "ship complete" for a machine
# with NO companion running at all, while the fleet was already offered the
# same build as CURRENT. Nothing retries: the Run key is logon-only. Same
# 3-second confirmation onboarding\steps.py has always done after ITS launch,
# and windows_bootstrap.ps1 after its companion step.
$RelaunchConfirmSeconds = 3
$relaunchAlive = $true
if ($DryRun) { Write-Step "[dry-run] would relaunch $CompanionExePath and confirm it is still running ${RelaunchConfirmSeconds}s later" }
elseif (-not (Test-Path -LiteralPath $CompanionExePath)) {
    Write-Warn2 "nothing to relaunch: no companion exe at $CompanionExePath (see the copy failure above)."
    $relaunchAlive = $false
}
else {
    $launched = $null
    try {
        $launched = Start-Process -FilePath $CompanionExePath -WorkingDirectory $BinDir -PassThru
        Write-Step "relaunched companion -- confirming it is still running in ${RelaunchConfirmSeconds}s..."
    }
    catch {
        Write-Warn2 "could not relaunch the companion: $($_.Exception.Message) -- start it from $CompanionExePath, or just log off and back on (autostart is registered)."
        $relaunchAlive = $false
    }
    if ($relaunchAlive) {
        Start-Sleep -Seconds $RelaunchConfirmSeconds
        # The launched process itself, not a name lookup: on a machine where a
        # stale companion survived the kill in step 1, Get-Process would find
        # THAT one and call this a success. Name lookup is only the fallback
        # for a Start-Process that returned nothing to hold on to.
        $stillUp = $false
        if ($launched) {
            try { $stillUp = -not $launched.HasExited } catch { $stillUp = $false }
        }
        else {
            $stillUp = [bool](Get-Process -Name ccsync-companion -ErrorAction SilentlyContinue)
        }
        if ($stillUp) {
            Write-Step "companion is running (pid $(if ($launched) { $launched.Id } else { 'unknown' }))"
        }
        else {
            $relaunchAlive = $false
            Write-Warn2 "the companion EXITED within ${RelaunchConfirmSeconds}s of being started -- this machine has NO companion running: no sync lanes, no Resolve bridge, no proxy generation, and nothing will retry before the next logon."
            Write-Warn2 "run it by hand to see why: `"$CompanionExePath`"  (then check $env:USERPROFILE\.ccsync\companion.log and config.toml)"
        }
    }
}

# --- 5b. the sync engine ---------------------------------------------------
# SYNC-17 (2026-08-18). This script does not touch syncthing.exe -- and that
# is exactly why this check is here. Syncthing is started by an HKCU Run
# entry, which fires at LOGON AND NEVER AGAIN, so a session that ended (a
# sign-out, a remote shell closing, a forced restart) leaves the machine with
# no sync engine until somebody logs in again. One editor spent eighteen
# hours in that state: the companion came back on its own, rclone came back,
# lane C carried nothing, and the fleet grid was green throughout. An upgrade
# is one of the few moments this machine is being looked at, so look.
#
# Companion 0.9.1+ supervises this itself (sync/syncthing_supervisor.py);
# this is the belt for the machine whose companion has not been upgraded yet,
# and for the window between the two.
$stShim = "$BinDir\CCSyncSyncthing.vbs"
$stRunning = [bool](Get-Process -Name "syncthing" -ErrorAction SilentlyContinue)
if ($DryRun) {
    Write-Step "[dry-run] would start the sync engine via $stShim if no syncthing process is running"
}
elseif ($stRunning) {
    Write-Skip "sync engine (Syncthing) is running"
}
elseif (-not (Test-Path -LiteralPath $stShim)) {
    Write-Warn2 "the sync engine (Syncthing) is NOT running and there is no autostart shim at $stShim -- lane C (audio, graphics, subtitles, project files) is carrying nothing on this machine. Re-run windows_bootstrap.ps1."
}
else {
    try {
        # Through the SAME shim the Run key uses, so this start and a logon
        # start are the same command line -- including the --home the .cmd
        # beside it bakes in, which a hand-rolled `syncthing serve` here
        # would get wrong and quietly point at an empty config.
        Start-Process -FilePath "wscript.exe" -ArgumentList "//B", "//Nologo", "`"$stShim`"" -WindowStyle Hidden | Out-Null
        Start-Sleep -Seconds 2
        if (Get-Process -Name "syncthing" -ErrorAction SilentlyContinue) {
            Write-Step "started the sync engine (Syncthing) -- it was not running"
        }
        else {
            Write-Warn2 "started the sync engine but no syncthing process appeared -- check $env:LOCALAPPDATA\ccsync\syncthing-config and the companion log; lane C is not syncing until it runs."
        }
    }
    catch {
        Write-Warn2 "could not start the sync engine: $($_.Exception.Message) -- lane C is not syncing on this machine."
    }
}

# --- 6. the licence agreement, and the wizard that takes it ----------------
# A COMPLETED UPGRADE THAT DOES NOT SYNC (2026-08-18). Companion 0.8.0 gates
# the sync lanes on ~/.ccsync/eula_accepted.json (CR-5, eula.acceptance_problem):
# with no current acceptance the sequencer never starts, and the tray renders
# that as the generic "this machine isn't set up yet" on all three lanes. The
# wizard is the only thing that writes the record -- and nothing on the upgrade
# path ran it, so every editor upgrading to 0.8.0 would have landed on a
# silently stopped companion. Seen live on the base rig the morning after the
# 0.8.0 build. So: ask here, where a human is already watching an upgrade.
#
# Deliberately AFTER the relaunch, not before: the companion coming back is the
# upgrade, and it must not wait on somebody reading a licence. It comes up
# not-syncing for as long as that takes, which is the honest state.
$wizardNeeded = $false
$wizardReason = ""
$acceptancePath = "$env:USERPROFILE\.ccsync\eula_accepted.json"
$packagedEula = Join-Path $PackageDir "EULA.md"

function Get-EulaVersion {
    param([string]$Path)
    # The `<!-- EULA-VERSION: x.y -->` marker, matching companion/eula.py's
    # _VERSION_MARKER_RE. "" when the file or the marker is absent.
    if (-not (Test-Path -LiteralPath $Path)) { return "" }
    try { $text = Get-Content -LiteralPath $Path -Raw -Encoding UTF8 } catch { return "" }
    $m = [regex]::Match($text, '<!--\s*EULA-VERSION:\s*([0-9][0-9A-Za-z.\-]*)\s*-->')
    if ($m.Success) { return $m.Groups[1].Value } else { return "" }
}

function Test-VersionAtLeast {
    param([string]$Have, [string]$Want)
    # Component-wise NUMERIC compare, zero-padded to the longer of the two --
    # eula.version_at_least's contract. As strings "1.10" sorts below "1.9",
    # which would make a tenth revision of the document read as older than its
    # predecessor and silently stop asking anyone to re-accept.
    $toParts = {
        param($v)
        @(("$v".Trim() -split '\.') | ForEach-Object {
            $digits = ($_ -replace '^(\d*).*$', '$1')
            if ($digits) { [int]$digits } else { 0 }
        })
    }
    $a = & $toParts $Have
    $b = & $toParts $Want
    $width = [Math]::Max($a.Count, $b.Count)
    for ($i = 0; $i -lt $width; $i++) {
        $x = if ($i -lt $a.Count) { $a[$i] } else { 0 }
        $y = if ($i -lt $b.Count) { $b[$i] } else { 0 }
        if ($x -ne $y) { return ($x -gt $y) }
    }
    return $true
}

if (-not (Test-Path -LiteralPath $acceptancePath)) {
    $wizardNeeded = $true
    $wizardReason = "the licence agreement has not been accepted on this machine"
}
else {
    $acceptedVersion = ""
    try {
        # -Encoding UTF8 for the same reason the config read above uses it, and
        # a BOM-tolerant trim: eula.read_acceptance reads this file as
        # utf-8-sig precisely because a PowerShell writer can leave one.
        $raw = (Get-Content -LiteralPath $acceptancePath -Raw -Encoding UTF8).TrimStart([char]0xFEFF)
        $acceptedVersion = ("" + (ConvertFrom-Json $raw).version).Trim()
    }
    catch { $acceptedVersion = "" }

    $bundledVersion = Get-EulaVersion $packagedEula
    if (-not $acceptedVersion) {
        $wizardNeeded = $true
        $wizardReason = "the licence acceptance record on this machine is unreadable"
    }
    elseif ($bundledVersion -and -not (Test-VersionAtLeast $acceptedVersion $bundledVersion)) {
        # Only when the PACKAGE says so. A package built before EULA.md was
        # shipped alongside it gives "" here, and an unknown version must not
        # be read as a newer one -- that would re-ask every editor on every
        # upgrade forever.
        $wizardNeeded = $true
        $wizardReason = ("the licence agreement has been updated (v$bundledVersion; " +
                         "this machine accepted v$acceptedVersion)")
    }
}

# The base rig is the one machine where re-running the wizard is worse than
# the problem: its config.toml is hand-tuned (mode = "base", a pinned
# active_project, no local sync) and tools\ship.cmd runs this script on it at
# the end of every release. Say what to do instead rather than walking the
# operator's own rig through an editor setup.
$isBaseRig = $false
if (Test-Path -LiteralPath $ConfigPath) {
    $isBaseRig = (Get-Content -LiteralPath $ConfigPath -Encoding UTF8 |
                  Where-Object { $_ -match '^\s*mode\s*=\s*"base"' }).Count -gt 0
}

$wizardLaunched = $false
if (-not $wizardNeeded) {
    Write-Skip "licence agreement already accepted on this machine"
}
elseif ($SkipWizard) {
    Write-Warn2 "$wizardReason -- the sync lanes will NOT start (all three tray lines read `"this machine isn't set up yet`"). -SkipWizard was passed; run onboard.exe when someone is at the machine."
}
elseif ($isBaseRig) {
    Write-Warn2 "$wizardReason -- the sync lanes will NOT start. This machine is mode = `"base`", so the wizard is NOT being launched over its hand-built config: accept from the tray (`"Accept the licence agreement to start syncing`"), or run onboard.exe deliberately."
}
elseif ($DryRun) {
    Write-Step "[dry-run] would launch $OnboardExe ($wizardReason)"
    $wizardLaunched = $true
}
elseif (-not (Test-Path -LiteralPath $OnboardExe)) {
    Write-Warn2 "$wizardReason -- the sync lanes will NOT start, and there is no onboard.exe beside this script to fix it. Get the current installer from the dashboard's [ INSTALLER ] link and run it."
}
else {
    Write-Step "$wizardReason -- launching the setup wizard..."
    try {
        # NOT -Wait: the wizard is a GUI the editor works through at their own
        # pace, and this script's caller (tools\ship.ps1, or an editor's own
        # console) must not block on it. The companion is already running and
        # will pick the acceptance up on its next start.
        Start-Process -FilePath $OnboardExe -WorkingDirectory $PackageDir | Out-Null
        $wizardLaunched = $true
    }
    catch {
        Write-Warn2 "could not launch the setup wizard ($($_.Exception.Message)) -- run `"$OnboardExe`" by hand, or the sync lanes will not start."
    }
}

Write-Host ""
Write-Host "=================================================================="
if (-not $copySucceeded) {
    Write-Step "Upgrade INCOMPLETE: the new companion build could not be installed (see the WARNING above); the previous build was relaunched instead."
    Write-Step "Exit code 1 -- an INCOMPLETE upgrade must not read as a success to whatever ran this."
}
elseif (-not $relaunchAlive) {
    # SHIP-2: the bytes are in place, so a re-run of this script fixes nothing
    # -- what is wrong is the build itself, and saying "complete" here is how
    # ship printed "ship complete" over a machine running no companion.
    Write-Step "Upgrade INSTALLED BUT NOT RUNNING: the new build is at $CompanionExePath and autostart points at it, but it did not stay up (see the WARNING above)."
    Write-Step "Exit code 1 -- a companion that is not running must not read as a success to whatever ran this."
}
else {
    $verSuffix = ""
    if ($NewVersion) { $verSuffix = " -- now running v$NewVersion" }
    Write-Step "Upgrade complete$(if ($DryRun) { ' (dry run -- nothing changed)' })$verSuffix."
}
Write-Step "Syncthing identity, rclone key, drive mapping, and settings were preserved."
if ($wizardLaunched) {
    Write-Step "The setup wizard is open: work through it to accept the licence agreement. UNTIL YOU DO, THIS MACHINE IS NOT SYNCING."
}
elseif ($wizardNeeded) {
    Write-Warn2 "THIS MACHINE IS NOT SYNCING: $wizardReason, and the companion will not start its sync lanes without one (all three tray lines read `"this machine isn't set up yet`")."
}
if (-not $DashboardToken -and (Test-Path -LiteralPath $ConfigPath)) {
    # -Encoding UTF8 for the same reason as the migration read above (INST-3).
    $hasToken = (Get-Content -LiteralPath $ConfigPath -Encoding UTF8 | Where-Object { $_ -match '^\s*dashboard_token\s*=\s*"\S' }).Count -gt 0
    if (-not $hasToken) { Write-Warn2 "dashboard_token is blank -- fleet reporting + project selection are off. Re-run with -DashboardToken <value> (ask the admin) to enable them." }
}
Write-Host "=================================================================="

# SAY IT IN THE EXIT CODE (OPS-4, 2026-08-11). This script used to fall off the
# end after all five copy attempts had failed -- implicit exit 0 -- and
# tools\ship.ps1 gates only on $LASTEXITCODE, so ship printed "ship complete.
# Editors' trays will offer v<X>" while this machine was still running the
# PREVIOUS build: the "verified against a build nobody was running" state of
# 2026-07-25, reached by way of a warning nobody's script could read. Same
# exit-code-vs-warning root cause as B23. A dry run sets $copySucceeded true.
#
# $relaunchAlive joins it for SHIP-2 (2026-08-14): copying the bytes is not the
# upgrade, RUNNING them is, and a build that exits on startup left ship saying
# "ship complete" over a machine with no companion. A dry run sets it true.
if (-not $copySucceeded) { exit 1 }
if (-not $relaunchAlive) { exit 1 }
exit 0
