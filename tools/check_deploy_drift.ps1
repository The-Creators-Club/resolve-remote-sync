#requires -Version 5.1
<#
.SYNOPSIS
    Doctor: is the code in this repo actually the code running on this
    machine and being offered to the fleet? Read-only.

.DESCRIPTION
    Answers one question in one screen: WHICH BUILD IS ACTUALLY RUNNING?

    On 2026-07-25 three rounds of companion fixes were verified against the
    repo at v0.4.5 while %LOCALAPPDATA%\ccsync\bin\ccsync-companion.exe had
    been v0.4.3 since 15:54 that afternoon. Nothing was wrong with the fixes;
    they were simply not installed. This script is the 5-second check that
    would have caught it (docs/RELEASE.md).

    It reports, in order:

      REPO       companion VERSION (config.py, authoritative) + pyproject +
                 installer version constants + dashboard VERSION.
      BUILT      companion/dist/ccsync-companion.exe: manifest version (from
                 ccsync-release.json written by tools/release.ps1), sha256,
                 mtime, and whether companion/src has changed since.
      INSTALLED  %LOCALAPPDATA%\ccsync\bin\ccsync-companion.exe: mtime,
                 sha256, and its version. The exe has NO --version flag (it
                 is a windowed PyInstaller build with no argv handling in
                 launcher.py / app.run), and running an unknown build just to
                 ask it would start a second companion -- so the version is
                 established, in order of preference, from:
                   1. ccsync-release.json sitting next to the installed exe
                      (windows_upgrade.ps1 copies it there),
                   2. ~/.ccsync/state/last_version.txt (upgrade.py's
                      note_version_start marker, companion >= 0.4.5),
                   3. the last "ccsync-companion vX.Y.Z starting" line in
                      ~/.ccsync/companion.log -- i.e. what the running
                      process actually said about itself,
                   4. sha256 equality with the built artifact.
      RUNNING    is a ccsync-companion process alive, and does the HKCU Run
                 key point at the exe we just inspected?
      DASHBOARD  GET /api/v1/health -> "version" (unauthenticated; still
                 present if that response is ever trimmed to ok+version).
                 With -AdminUser, also the CURRENT published companion
                 package -- the version the fleet will self-upgrade to --
                 for windows AND macos, plus an advisory when the macOS
                 companion channel is behind the repo (that binary is built
                 on a Mac by tools/release_macos.sh; nothing here can).

    Changes nothing: no files, no registry, no processes, no git. The only
    network calls are GETs (plus a login POST if you pass -AdminUser).

.PARAMETER DashboardUrl
    Defaults to dashboard_url from ~/.ccsync/config.toml, else
    $env:CCSYNC_DASHBOARD_URL. There is no compiled-in address any more (WP0,
    2026-08-17); with none of the three, the DASHBOARD section says so and
    checks nothing rather than reporting on somebody else's deployment.

.PARAMETER AdminUser
    Optionally log in as this dashboard admin to also report the published /
    current companion package versions. Prompts for the password.

.PARAMETER Quiet
    Suppress the explanatory footer; print the facts only.

.EXAMPLE
    .\tools\check_deploy_drift.ps1

.EXAMPLE
    .\tools\check_deploy_drift.ps1 -AdminUser <your-dashboard-admin>
#>
[CmdletBinding()]
param(
    [string]$DashboardUrl = "",
    [string]$AdminUser = "",
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"

function Write-Head { param([string]$m) Write-Host ""; Write-Host "-- $m " -ForegroundColor Cyan }
function Write-Row { param([string]$k, [string]$v) Write-Host ("  {0,-26} {1}" -f $k, $v) }
function Write-Ok { param([string]$m) Write-Host "  OK    $m" -ForegroundColor Green }
function Write-Drift { param([string]$m) Write-Host "  DRIFT $m" -ForegroundColor Yellow }
function Write-Unknown { param([string]$m) Write-Host "  ?     $m" -ForegroundColor DarkGray }

$RepoRoot = Split-Path -Parent $PSScriptRoot
$CompanionDir = Join-Path $RepoRoot "companion"
$ExeBuilt = Join-Path $CompanionDir "dist\ccsync-companion.exe"
$ManifestBuilt = Join-Path $CompanionDir "dist\ccsync-release.json"
$BinDir = Join-Path $env:LOCALAPPDATA "ccsync\bin"
$ExeInstalled = Join-Path $BinDir "ccsync-companion.exe"
$ManifestInstalled = Join-Path $BinDir "ccsync-release.json"
$CcsyncHome = Join-Path $env:USERPROFILE ".ccsync"
$ConfigToml = Join-Path $CcsyncHome "config.toml"
$LogPath = Join-Path $CcsyncHome "companion.log"
$VersionMarker = Join-Path $CcsyncHome "state\last_version.txt"
$RunKeyPath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"

function Get-Capture {
    param([string]$Path, [string]$Pattern)
    if (-not (Test-Path -LiteralPath $Path)) { return "" }
    $m = Select-String -Path $Path -Pattern $Pattern
    if (-not $m) { return "" }
    return $m.Matches[0].Groups[1].Value
}

function Get-Sha256 {
    param([string]$Path)
    try { return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLower() }
    catch { return "" }
}

function Read-Manifest {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    try { return (Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json) }
    catch { return $null }
}

function Format-Age {
    param($When)
    if (-not $When) { return "" }
    $span = (Get-Date) - $When
    if ($span.TotalDays -ge 1) { return "$([int]$span.TotalDays)d ago" }
    if ($span.TotalHours -ge 1) { return "$([int]$span.TotalHours)h ago" }
    return "$([int]$span.TotalMinutes)m ago"
}

Write-Host "=================================================================="
Write-Host " ccsync deploy drift check -- $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Host " repo: $RepoRoot"
Write-Host "=================================================================="

# --- REPO ------------------------------------------------------------------

Write-Head "REPO (what the source tree says)"

$RepoVersion = Get-Capture -Path (Join-Path $CompanionDir "src\ccsync_companion\config.py") -Pattern '^VERSION\s*=\s*"([^"]+)"'
$PyprojectVersion = Get-Capture -Path (Join-Path $CompanionDir "pyproject.toml") -Pattern '^version\s*=\s*"([^"]+)"'
$BootstrapVersion = Get-Capture -Path (Join-Path $RepoRoot "installer\windows_bootstrap.ps1") -Pattern '^\$InstallerVersion\s*=\s*"([^"]+)"'
$OnboardVersion = Get-Capture -Path (Join-Path $RepoRoot "onboarding\steps.py") -Pattern '^INSTALLER_VERSION\s*=\s*"([^"]+)"'
# One installer number, three copies -- the third is the macOS bootstrap that
# ships in the same editor package (the macos onboard slot itself carries the
# zipped wizard since 1.0.17, published from the Mac at this same number).
$MacBootstrapVersion = Get-Capture -Path (Join-Path $RepoRoot "installer\macos_bootstrap.sh") -Pattern '^INSTALLER_VERSION="([^"]+)"'
$DashRepoVersion = Get-Capture -Path (Join-Path $RepoRoot "dashboard\src\ccsync_dashboard\__init__.py") -Pattern '^VERSION\s*=\s*"([^"]+)"'

Write-Row "companion VERSION" $RepoVersion
Write-Row "  pyproject.toml" $PyprojectVersion
Write-Row "installer version" $BootstrapVersion
Write-Row "  onboarding/steps.py" $OnboardVersion
Write-Row "  macos_bootstrap.sh" $MacBootstrapVersion
Write-Row "dashboard VERSION" $DashRepoVersion

$gitDescribe = "$(cmd /c "git -C ""$RepoRoot"" describe --tags --always --dirty 2>nul")".Trim()
if ($gitDescribe) { Write-Row "git" $gitDescribe }

if ($RepoVersion -and ($RepoVersion -eq $PyprojectVersion)) { Write-Ok "companion version parity (config.py == pyproject.toml)" }
else { Write-Drift "companion version parity: config.py '$RepoVersion' vs pyproject.toml '$PyprojectVersion'" }
if ($BootstrapVersion -and ($BootstrapVersion -eq $OnboardVersion) -and ($BootstrapVersion -eq $MacBootstrapVersion)) {
    Write-Ok "installer version parity (windows bootstrap == onboarding == macos bootstrap)"
}
else {
    Write-Drift "installer version parity: windows_bootstrap.ps1 '$BootstrapVersion' vs onboarding/steps.py '$OnboardVersion' vs macos_bootstrap.sh '$MacBootstrapVersion'"
}

# --- BUILT -----------------------------------------------------------------

Write-Head "BUILT ARTIFACT (companion/dist)"

$builtSha = ""
$builtVersion = ""
$builtManifest = Read-Manifest -Path $ManifestBuilt
if (Test-Path -LiteralPath $ExeBuilt) {
    $builtItem = Get-Item -LiteralPath $ExeBuilt
    $builtSha = Get-Sha256 -Path $ExeBuilt
    Write-Row "path" $ExeBuilt
    Write-Row "built" "$($builtItem.LastWriteTime)  ($(Format-Age $builtItem.LastWriteTime))"
    Write-Row "size" "$([int]($builtItem.Length/1KB)) KB"
    Write-Row "sha256" $builtSha

    if ($builtManifest) {
        $builtVersion = "$($builtManifest.version_stamp)"
        Write-Row "manifest version" $builtVersion
        Write-Row "manifest commit" "$($builtManifest.git_describe)"
        Write-Row "manifest built_at" "$($builtManifest.built_at)"
        if ("$($builtManifest.sha256)" -ne $builtSha) {
            Write-Drift "the exe in dist/ is NOT the one ccsync-release.json describes (rebuilt without tools/release.ps1?)"
            $builtVersion = ""
        }
        elseif ("$($builtManifest.tests_run)" -eq "False") {
            Write-Drift "this artifact was built with -SkipTests"
        }
    }
    else {
        Write-Unknown "no ccsync-release.json next to the exe -- built by hand or by build_editor_package.ps1 -RebuildExe; version unprovable"
    }

    $newestSrc = Get-ChildItem -Path (Join-Path $CompanionDir "src") -Recurse -Filter *.py |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($newestSrc -and ($newestSrc.LastWriteTime -gt $builtItem.LastWriteTime)) {
        Write-Drift "STALE: $($newestSrc.Name) changed $($newestSrc.LastWriteTime), after this exe was built -- run tools\release.ps1"
    }
    else {
        Write-Ok "artifact is newer than every companion source file"
    }
}
else {
    Write-Unknown "no built exe at $ExeBuilt -- run tools\release.ps1"
}

# --- INSTALLED -------------------------------------------------------------

Write-Head "INSTALLED (this machine)"

$installedVersion = ""
$installedVersionSource = ""
$installedSha = ""
if (Test-Path -LiteralPath $ExeInstalled) {
    $instItem = Get-Item -LiteralPath $ExeInstalled
    $installedSha = Get-Sha256 -Path $ExeInstalled
    Write-Row "path" $ExeInstalled
    Write-Row "mtime" "$($instItem.LastWriteTime)  ($(Format-Age $instItem.LastWriteTime))"
    Write-Row "size" "$([int]($instItem.Length/1KB)) KB"
    Write-Row "sha256" $installedSha

    # 0. byte-identity with the freshly built artifact. This outranks every
    # text source: the state marker and the log line both lag one process
    # launch behind, so for the first seconds after an upgrade they still
    # name the PREVIOUS build -- which made this check cry DRIFT one second
    # after a successful ship (seen live 2026-07-26). Identical bytes ARE
    # the built version; no cache can contradict that.
    if ($builtSha -and ($builtSha -eq $installedSha) -and $builtVersion) {
        $installedVersion = $builtVersion
        $installedVersionSource = "sha256 is byte-identical to companion/dist"
    }

    # 1. sidecar manifest
    $instManifest = Read-Manifest -Path $ManifestInstalled
    if (-not $installedVersion) {
        if ($instManifest -and ("$($instManifest.sha256)" -eq $installedSha)) {
            $installedVersion = "$($instManifest.version_stamp)"
            $installedVersionSource = "ccsync-release.json beside the exe"
        }
    }
    if ($instManifest -and ("$($instManifest.sha256)" -ne $installedSha)) {
        Write-Unknown "ccsync-release.json beside the installed exe describes a DIFFERENT file (sha mismatch) -- ignoring it"
    }

    # 2. the upgrade.py version marker
    if (-not $installedVersion) {
        if (Test-Path -LiteralPath $VersionMarker) {
            # Get-Content -Raw returns $null (not "") for a ZERO-BYTE file, and
            # $null.Trim() is a terminating error under $ErrorActionPreference
            # = "Stop" -- so an empty marker took this whole script down before
            # it ever printed a VERDICT, and ship.ps1 runs it as its final
            # step. companion upgrade.py can leave a 0-byte marker behind.
            $rawMarker = Get-Content -LiteralPath $VersionMarker -Raw -Encoding UTF8
            $marker = "$rawMarker".Trim()
            if ($marker) {
                $installedVersion = $marker
                $installedVersionSource = "~/.ccsync/state/last_version.txt"
            }
        }
    }

    # 3. what the running process announced in the log
    if (-not $installedVersion) {
        if (Test-Path -LiteralPath $LogPath) {
            $line = Select-String -Path $LogPath -Pattern 'ccsync-companion v([0-9][^\s]*) starting' |
                Select-Object -Last 1
            if ($line) {
                $installedVersion = $line.Matches[0].Groups[1].Value
                $when = "$($line.Line)"
                if ($when.Length -ge 19) { $when = $when.Substring(0, 19) }
                $installedVersionSource = "last start line in companion.log ($when)"
            }
        }
    }

    # 4. sha equality with the built artifact
    if (-not $installedVersion -and $builtSha -and ($builtSha -eq $installedSha) -and $builtVersion) {
        $installedVersion = $builtVersion
        $installedVersionSource = "sha256 matches companion/dist artifact"
    }

    if ($installedVersion) {
        Write-Row "version" "$installedVersion   [$installedVersionSource]"
    }
    else {
        Write-Unknown "could not establish the installed version (no sidecar manifest, no state marker, no log line, sha does not match dist)"
    }
}
else {
    Write-Unknown "nothing installed at $ExeInstalled"
}

# process + autostart
$procs = @(Get-Process -Name ccsync-companion -ErrorAction SilentlyContinue)
if ($procs.Count -gt 0) {
    $p = $procs[0]
    # StartTime and Path both throw on processes we can't open (elevated,
    # exiting). Neither is worth aborting the check for.
    $started = $null
    try { $started = $p.StartTime } catch { $started = $null }
    if ($started) { Write-Row "process" "running, pid $($p.Id), started $started ($(Format-Age $started))" }
    else { Write-Row "process" "running, pid $($p.Id)" }
    $procPath = ""
    try { $procPath = $p.Path } catch { $procPath = "" }
    if ($procPath -and ($procPath -ne $ExeInstalled)) {
        Write-Drift "the running process is $procPath -- NOT the exe inspected above"
    }
    if ($started -and (Test-Path -LiteralPath $ExeInstalled)) {
        $instItem2 = Get-Item -LiteralPath $ExeInstalled
        if ($instItem2.LastWriteTime -gt $started) {
            Write-Drift "the exe on disk is NEWER than the running process -- a new build was installed but never restarted"
        }
    }
}
else {
    Write-Drift "no ccsync-companion process is running on this machine"
}

$runKeyValue = ""
try { $runKeyValue = (Get-ItemProperty -Path $RunKeyPath -Name "CCSyncCompanion" -ErrorAction Stop).CCSyncCompanion }
catch { $runKeyValue = "" }
if ($runKeyValue) {
    Write-Row "autostart (HKCU Run)" $runKeyValue
    if ($runKeyValue.Trim('"') -ne $ExeInstalled) {
        Write-Drift "autostart points somewhere other than $ExeInstalled"
    }
}
else {
    Write-Drift "no HKCU\...\Run 'CCSyncCompanion' value -- the companion will not start at logon"
}

# --- DASHBOARD -------------------------------------------------------------

Write-Head "DASHBOARD"

if (-not $DashboardUrl) {
    $DashboardUrl = Get-Capture -Path $ConfigToml -Pattern '^\s*dashboard_url\s*=\s*"([^"]+)"'
    if ($DashboardUrl) { Write-Row "url (from config.toml)" $DashboardUrl }
}
else {
    Write-Row "url" $DashboardUrl
}
if (-not $DashboardUrl -and $env:CCSYNC_DASHBOARD_URL) {
    $DashboardUrl = $env:CCSYNC_DASHBOARD_URL
    Write-Row "url (CCSYNC_DASHBOARD_URL)" $DashboardUrl
}
if (-not $DashboardUrl) {
    # No compiled-in address since 2026-08-17 (WP0) -- a doctor that quietly
    # health-checked somebody else's dashboard would report on the wrong
    # deployment. Say what is missing; check nothing.
    Write-Unknown "no dashboard url: pass -DashboardUrl, set CCSYNC_DASHBOARD_URL, or put dashboard_url in $ConfigToml"
}

# What the LIVE deployment says it is. The container name differs per NAS
# platform (TrueNAS's app runtime prefixes ix-; a Synology compose stack does
# not), so it is reported from the manifest rather than assumed -- WP5.
if ($DashboardUrl) {
    try {
        $site = Invoke-RestMethod -Method Get -Uri "$DashboardUrl/api/v1/site" -TimeoutSec 8
        $nasKind = "$($site.nas_kind)".Trim()
        if (-not $nasKind) { $nasKind = "unknown" }
        $expectedContainer = "ccsync-dashboard-1"
        if ($nasKind -eq "truenas") { $expectedContainer = "ix-ccsync-dashboard-1" }
        Write-Row "nas kind (/api/v1/site)" $nasKind
        Write-Row "expected container" $expectedContainer
        if ("$($site.org_name)".Trim()) { Write-Row "site" "$($site.org_name)" }
    }
    catch {
        # 404 = a dashboard older than the site manifest. Not drift by itself.
        Write-Unknown "no site manifest at $DashboardUrl/api/v1/site ($($_.Exception.Message)) -- container name unknown"
    }
}

$liveDashVersion = ""
if ($DashboardUrl) {
try {
    $health = Invoke-RestMethod -Method Get -Uri "$DashboardUrl/api/v1/health" -TimeoutSec 8
    $liveDashVersion = "$($health.version)"
    Write-Row "live version (/health)" $liveDashVersion
    # These keys may be trimmed from the unauthenticated response; absence is
    # not an error, so probe rather than assume.
    $reach = $health.PSObject.Properties["syncthing_reachable"]
    if ($reach) { Write-Row "syncthing_reachable" "$($reach.Value)" }
    $stale = $health.PSObject.Properties["collector_stale"]
    if ($stale) { Write-Row "collector_stale" "$($stale.Value)" }
}
catch {
    Write-Unknown "dashboard unreachable at $DashboardUrl ($($_.Exception.Message))"
}
}  # if ($DashboardUrl)

if ($liveDashVersion -and $DashRepoVersion) {
    if ($liveDashVersion -eq $DashRepoVersion) {
        Write-Ok "dashboard reports v$liveDashVersion, repo says v$DashRepoVersion"
    }
    else {
        Write-Drift "dashboard reports v$liveDashVersion but the repo is v$DashRepoVersion -- the container is behind (docker compose up -d --build)"
    }
}

if ($AdminUser -and $DashboardUrl) {
    try {
        $securePw = Read-Host "dashboard password for '$AdminUser'" -AsSecureString
        $pw = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
            [Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePw))
        $login = Invoke-RestMethod -Method Post -Uri "$DashboardUrl/api/v1/login" `
            -ContentType "application/json" `
            -Body (@{ username = $AdminUser; password = $pw } | ConvertTo-Json) `
            -SessionVariable dashSession -TimeoutSec 15
        if (-not $login.is_admin) {
            Write-Unknown "'$AdminUser' is not a dashboard admin -- cannot read the package channel"
        }
        else {
            $pkgs = Invoke-RestMethod -Method Get -Uri "$DashboardUrl/api/v1/admin/packages" `
                -WebSession $dashSession -TimeoutSec 15
            # `current` is platform -> version and only ever names the
            # COMPANION (build_packages_view); the onboard rows carry their own
            # is_current, so they are listed per kind below.
            $curWin = "$($pkgs.current.windows)"
            Write-Row "current windows package" $curWin
            $all = ($pkgs.packages | Where-Object { $_.platform -eq "windows" } |
                ForEach-Object { if ($_.is_current) { "$($_.version)*" } else { "$($_.version)" } }) -join ", "
            Write-Row "published (windows)" $all
            if ($curWin -and $RepoVersion) {
                if ($curWin -eq $RepoVersion) { Write-Ok "the fleet's current package matches the repo version" }
                else { Write-Drift "fleet is offered v$curWin but the repo is v$RepoVersion -- publish (see docs/RELEASE.md)" }
            }

            # macOS, same rows. The Mac binary is built by tools/release_macos.sh
            # ON A MAC (PyInstaller does not cross-compile), so nothing that runs
            # on this rig can keep this channel current -- which is exactly why it
            # is worth printing next to the Windows one.
            $curMac = "$($pkgs.current.macos)"
            if (-not $curMac) { $curMac = "(none published)" }
            Write-Row "current macos package" $curMac
            $allMacCompanion = ($pkgs.packages | Where-Object { $_.platform -eq "macos" -and $_.kind -eq "companion" } |
                ForEach-Object { if ($_.is_current) { "$($_.version)*" } else { "$($_.version)" } }) -join ", "
            $allMacOnboard = ($pkgs.packages | Where-Object { $_.platform -eq "macos" -and $_.kind -eq "onboard" } |
                ForEach-Object { if ($_.is_current) { "$($_.version)*" } else { "$($_.version)" } }) -join ", "
            if (-not $allMacCompanion) { $allMacCompanion = "(none)" }
            if (-not $allMacOnboard) { $allMacOnboard = "(none)" }
            Write-Row "published (macos)" "companion: $allMacCompanion | onboard: $allMacOnboard"
            # Advisory: never part of the VERDICT and never an exit code.
            if ($RepoVersion) {
                if ("$($pkgs.current.macos)" -eq $RepoVersion) {
                    Write-Ok "macos companion channel is level with the repo (v$RepoVersion)"
                }
                elseif ("$($pkgs.current.macos)") {
                    Write-Drift "macos companion current is v$($pkgs.current.macos), repo is v$RepoVersion -- Mac build lagging, run tools/release_macos.sh on the Mac (advisory)"
                }
                else {
                    Write-Drift "no macos companion package published at all (repo v$RepoVersion) -- Mac build lagging, run tools/release_macos.sh on the Mac (advisory)"
                }
            }
            foreach ($o in $pkgs.outdated_machines) {
                Write-Drift "machine behind: $($o.machine) ($($o.editor_username)) on v$($o.companion_version), last seen $($o.received_at)"
            }
        }
    }
    catch {
        Write-Unknown "package channel query failed: $($_.Exception.Message)"
    }
}

# --- VERDICT ---------------------------------------------------------------

Write-Head "VERDICT"

if ($installedVersion -and $RepoVersion) {
    $installedBase = $installedVersion -replace '\+dirty$', ''
    if ($installedBase -eq $RepoVersion) {
        Write-Ok "installed companion v$installedVersion == repo v$RepoVersion"
        if ($builtSha -and $installedSha -and ($builtSha -ne $installedSha)) {
            Write-Drift "...but the installed exe's sha256 differs from companion/dist -- same version number, different bytes"
        }
    }
    else {
        Write-Drift "installed companion is v$installedVersion, repo is v$RepoVersion"
        Write-Host "        => anything you 'verified' against this repo has NOT been tested on this machine." -ForegroundColor Yellow
        Write-Host "        => build:   .\tools\release.ps1" -ForegroundColor Yellow
        Write-Host "        => install: .\installer\windows_upgrade.ps1 -CompanionExe `"$ExeBuilt`"" -ForegroundColor Yellow
    }
}
else {
    Write-Unknown "cannot compare installed vs repo (version undetermined above)"
}

if (-not $Quiet) {
    Write-Host ""
    Write-Host "  Nothing was changed by this check. Runbook: docs\RELEASE.md"
}
Write-Host ""

# Explicit, like tools\release.ps1. Without this the exit code is whatever
# the last native command (git) happened to leave behind -- a clean run
# reported 128, so anything wrapping this doctor read "everything is fine"
# as a failure. The report is the output; the exit code says only that the
# check itself ran. Drift is NOT signalled here -- read the VERDICT line.
exit 0
