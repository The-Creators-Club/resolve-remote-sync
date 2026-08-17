#requires -Version 5.1
<#
.SYNOPSIS
    Assemble the CCSync editor onboarding package from the repo.

.DESCRIPTION
    The package handed to a new editor is just a folder of files copied out of
    this repo plus the built companion exe. It was previously assembled by
    hand, which meant it silently drifted: the copy on the Desktop was three
    weeks and eleven bug-fixes behind the repo, and nobody could tell by
    looking at it. This script makes the assembly reproducible and reports the
    provenance of what it produced.

    Every file it copies comes from the repo. The one thing it does NOT build
    is the exe -- pass -RebuildExe to run PyInstaller first, otherwise the
    existing companion/dist/ccsync-companion.exe is reused and its age is
    reported so a stale one can't slip through unnoticed.

.PARAMETER Destination
    Where to assemble the package. Defaults to the canonical location on the
    NAS, P:\Assets\Software\CC_Sync (the base rig's P: maps to
    \\<nas>\<share>\<tree> since 2026-07-26) -- the single
    source of truth for editor packages, so every update lands there and
    there is only ever one copy to reason about. An existing folder is
    overwritten file-by-file, not deleted.

    Note this path is NOT distributed by the sync lanes: lane B's filter only
    brings down Proxy/ contents, and the Syncthing folders are scoped to
    individual projects under Projects/, so Assets/ never leaves the NAS on
    its own. Editors get the package by being pointed at the share (or sent
    a copy) -- it will not appear in their own tree folder by magic.

.PARAMETER RebuildExe
    Run PyInstaller against companion/build.spec before assembling. Needed
    whenever anything under companion/src has changed.

.PARAMETER RebuildOnboard
    Run PyInstaller against onboarding/build_onboard.spec before assembling
    (after the companion rebuild, so the bundle is never stale). Needed
    whenever onboarding/*.py, installer/windows_bootstrap.ps1, or the
    companion exe changed -- onboard.exe bundles all three. Shipping a
    stale onboard.exe is exactly how the 2026-07-25 rollout handed a new
    editor a companion that couldn't self-update.

.PARAMETER DryRun
    Report what would be copied, touch nothing.

.PARAMETER Publish
    After assembling, upload the companion exe to the dashboard's upgrade
    channel (PUT /api/v1/admin/packages/windows/<version>). The version is
    parsed from companion/src/ccsync_companion/config.py's VERSION and must
    match companion/pyproject.toml's; publishing refuses on drift, on a
    stale exe, and on a version the server already has (bump VERSION and
    rebuild). Prompts for the dashboard admin password.

    Also uploads onboarding/dist/onboard.exe as the kind=onboard package
    (version = $InstallerVersion from windows_bootstrap.ps1) -- that is what
    the dashboard's [ INSTALLER ] download serves. Skipped with a warning
    when onboard.exe is missing, older than the companion exe it should
    bundle, or already published at this installer version.

    The macOS side is NOT published from here (since 1.0.17): the macos
    kind=onboard package is the zipped onboarding wizard, and like the macOS
    companion it cannot be built on Windows -- both come from the Mac
    (tools/build_onboard_macos.sh --publish / tools/release_macos.sh
    --publish). What -Publish adds on the macOS side is the advisory when
    either macos channel -- installer or companion -- has fallen behind the
    repo version. The CR byte-scan of macos_bootstrap.sh is NOT part of it:
    that file is copied into the package on every run, so it is scanned on
    every run (SHIP-8).

.PARAMETER MakeCurrent
    With -Publish: immediately make the uploaded version the one offered to
    the fleet. Without it the build is staged and you flip [ MAKE CURRENT ]
    on the dashboard's admin page when ready.

.PARAMETER DashboardUrl
    Dashboard base URL. REQUIRED with -Publish -- there is no default any
    more (it used to be one deployment's tailnet address).
    $env:CCSYNC_DASHBOARD_URL is used when the flag is absent. Pass whichever
    address this machine reaches the dashboard on: the tailnet one remotely,
    the LAN one in the studio.

.PARAMETER AdminUser
    Dashboard admin username for -Publish (must be in DASH_ADMIN_USERS).
    REQUIRED with -Publish; $env:CCSYNC_ADMIN_USER when the flag is absent.
    No default -- it used to name one person's account.

.EXAMPLE
    .\build_editor_package.ps1 -RebuildExe

.EXAMPLE
    # Build, assemble, publish, and roll it out in one go:
    .\build_editor_package.ps1 -RebuildExe -Publish -MakeCurrent

.EXAMPLE
    # Somewhere else (e.g. to hand a one-off copy to someone off-network):
    .\build_editor_package.ps1 -Destination D:\tmp\CC_Sync
#>
[CmdletBinding()]
param(
    [string]$Destination = "P:\Assets\Software\CC_Sync",
    [switch]$RebuildExe,
    [switch]$RebuildOnboard,
    [switch]$DryRun,
    [switch]$Publish,
    [switch]$MakeCurrent,
    # Both REQUIRED for -Publish, and both without a default since 2026-08-17
    # (WP0): they used to name one deployment's dashboard and one person's
    # account. $env:CCSYNC_DASHBOARD_URL / $env:CCSYNC_ADMIN_USER are the
    # scripted-run route (tools\ship.ps1 passes them explicitly).
    [string]$DashboardUrl = "",
    [string]$AdminUser = ""
)

$ErrorActionPreference = "Stop"

function Write-Step { param([string]$m) Write-Host "[pkg] $m" }
function Write-Warn2 { param([string]$m) Write-Host "[pkg] WARNING: $m" -ForegroundColor Yellow }
function Write-Skip2 { param([string]$m) Write-Host "[pkg] (skip) $m" -ForegroundColor DarkGray }

# -Publish needs to know WHERE and AS WHOM, and neither has a default any
# more. Refused here, before PyInstaller runs and before anything is copied
# to the destination -- the same "fail before anything moves" rule
# tools\ship.ps1 applies to its secrets.
if (-not $DashboardUrl -and $env:CCSYNC_DASHBOARD_URL) { $DashboardUrl = $env:CCSYNC_DASHBOARD_URL }
if (-not $AdminUser -and $env:CCSYNC_ADMIN_USER) { $AdminUser = $env:CCSYNC_ADMIN_USER }
if ($DashboardUrl) { $DashboardUrl = $DashboardUrl.TrimEnd("/") }
# Deliberately NOT written as a plain -Publish block:
# onboarding/tests/test_release_gates.py locates the REAL publish block by the
# exact text of its opening line, to prove the macOS bootstrap's CR byte-scan
# runs outside it (SHIP-8) -- a second block of that shape earlier in the file
# would make the test find this one instead.
$missingPublishArgs = @()
if (-not $DashboardUrl) { $missingPublishArgs += "-DashboardUrl (or CCSYNC_DASHBOARD_URL)" }
if (-not $AdminUser) { $missingPublishArgs += "-AdminUser (or CCSYNC_ADMIN_USER)" }
if ($Publish -and $missingPublishArgs.Count -gt 0) {
    Write-Warn2 "-Publish needs $($missingPublishArgs -join ' and ') -- there is no default dashboard or admin account compiled in."
    exit 1
}

$RepoRoot = Split-Path -Parent $PSScriptRoot
$CompanionDir = Join-Path $RepoRoot "companion"
$ExePath = Join-Path $CompanionDir "dist\ccsync-companion.exe"

# The exit code this script finally reports. Everything below warns and carries
# on -- an incomplete package is still worth assembling, and one locked
# destination file must not abort the publish -- but "carried on" is NOT
# "succeeded", and tools\ship.ps1 gates step 3 solely on $LASTEXITCODE. Exiting
# 0 with a STALE package meant ship printed "ship complete" while every new
# editor still got the previous onboard.exe (B23, seen live 2026-07-25 when an
# editor had onboard.exe open off the share). Set this instead of exiting
# early, so the publish and the provenance report still run.
$script:FinalExitCode = 0

function Set-Failed {
    param([string]$Reason)
    $script:FinalExitCode = 1
    Write-Warn2 "FAILED: $Reason"
}

function Test-FileHasCr {
    # Byte-level CR scan -- the last line of defense before a Mac executes a
    # file this repo produced. A single 0x0D makes /bin/bash read the CR as
    # part of the last token on every line ("set -eu" -> "Illegal option -"),
    # which is exactly how dashboard/deploy/run.sh crash-looped the container
    # on 2026-07-26. .gitattributes marks *.sh eol=lf, but a checkout with a
    # stale index, a hand-edit in a Windows editor, or a copy through a tool
    # that "helpfully" normalises can all reintroduce it -- and the failure
    # surfaces on the editor's Mac, not here.
    param([string]$Path)
    try {
        $bytes = [System.IO.File]::ReadAllBytes($Path)
        return ([Array]::IndexOf($bytes, [byte]13) -ge 0)
    }
    catch {
        # Unreadable is not "clean": callers treat $true as "do not ship it".
        Write-Warn2 "could not read $Path for a CRLF check: $($_.Exception.Message)"
        return $true
    }
}

Write-Step "repo root: $RepoRoot"
Write-Step "destination: $Destination"

# --- optionally rebuild the companion exe ---------------------------------
# PyInstaller's exit code, kept for the restamp and the publish below (OPS-7).
# 0 also means "no rebuild was asked for", which is the state where dist\ and
# its manifest describe each other correctly.
$script:PyInstallerExit = 0
if ($RebuildExe) {
    $venvPython = Join-Path $CompanionDir ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $venvPython)) {
        Write-Warn2 "no venv at $venvPython -- falling back to 'python' on PATH"
        $venvPython = "python"
    }
    if ($DryRun) {
        Write-Step "[dry-run] would run: $venvPython -m PyInstaller build.spec --noconfirm (in $CompanionDir)"
    }
    else {
        Write-Step "rebuilding companion exe with PyInstaller (this takes a minute)..."
        Push-Location $CompanionDir
        # PyInstaller logs its INFO lines to stderr. Under PowerShell 5.1 with
        # $ErrorActionPreference='Stop', each of those becomes a terminating
        # NativeCommandError and aborts the build on the very first line. Drop
        # to Continue for the duration and judge success by $LASTEXITCODE.
        $prevEAP = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        try {
            & $venvPython -m PyInstaller build.spec --noconfirm 2>&1 |
                ForEach-Object { Write-Host "    $_" }
            $script:PyInstallerExit = $LASTEXITCODE
            if ($script:PyInstallerExit -ne 0) {
                Write-Warn2 "PyInstaller exited $script:PyInstallerExit -- the exe may be stale or missing"
            }
            else {
                Write-Step "exe rebuilt"
            }
        }
        finally {
            $ErrorActionPreference = $prevEAP
            Pop-Location
        }
        # Restamp dist\ccsync-release.json to describe THIS exe. Without it,
        # every rebuild here left the manifest describing the previous
        # tools\release.ps1 build, so publish and check_deploy_drift warned
        # about provenance on every single ship. tests_run=false is honest:
        # this path does not run the suites -- tools\release.ps1 remains the
        # tested-build path and overwrites this stamp with tests_run=true.
        #
        # ONLY after a build that actually succeeded (OPS-7). A failed
        # PyInstaller run leaves the PREVIOUS exe in dist\, and restamping the
        # manifest with the new version relabelled that old exe as the new
        # build -- taking the sha from the same stale file, so even the publish
        # provenance cross-check agreed with it.
        if ($script:PyInstallerExit -ne 0) {
            Set-Failed "PyInstaller exited $script:PyInstallerExit -- dist\ still holds the PREVIOUS exe, and its manifest was left describing it (not restamped)"
        }
        elseif (Test-Path -LiteralPath $ExePath) {
            try {
                $mVer = Select-String -Path (Join-Path $CompanionDir "src\ccsync_companion\config.py") -Pattern '^VERSION\s*=\s*"([^"]+)"'
                $stampVersion = if ($mVer) { $mVer.Matches[0].Groups[1].Value } else { "unknown" }
                $gitCommit = (cmd /c "git -C ""$RepoRoot"" rev-parse --short HEAD 2>nul")
                $gitDescribe = (cmd /c "git -C ""$RepoRoot"" describe --tags --always --dirty 2>nul")
                $gitDirty = [bool](cmd /c "git -C ""$RepoRoot"" status --porcelain 2>nul")
                $stampStamp = if ($gitDirty) { "$stampVersion+dirty" } else { $stampVersion }
                $exeItem = Get-Item -LiteralPath $ExePath
                $manifest = [ordered]@{
                    version        = $stampVersion
                    version_stamp  = $stampStamp
                    platform       = "windows"
                    artifact       = "ccsync-companion.exe"
                    sha256         = (Get-FileHash -Algorithm SHA256 -LiteralPath $ExePath).Hash.ToLower()
                    size_bytes     = $exeItem.Length
                    built_at       = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
                    artifact_mtime = $exeItem.LastWriteTime.ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
                    git_commit     = "$gitCommit".Trim()
                    git_describe   = "$gitDescribe".Trim()
                    git_dirty      = $gitDirty
                    tests_run      = $false
                    built_by       = "$env:USERNAME@$env:COMPUTERNAME"
                    built_with     = "installer/build_editor_package.ps1"
                }
                $utf8NoBom = New-Object System.Text.UTF8Encoding $false
                [System.IO.File]::WriteAllText((Join-Path $CompanionDir "dist\ccsync-release.json"),
                    ($manifest | ConvertTo-Json), $utf8NoBom)
                Write-Step "stamped dist\ccsync-release.json (v$stampStamp, tests_run=false)"
            }
            catch {
                Write-Warn2 "could not restamp ccsync-release.json: $($_.Exception.Message)"
            }
        }
    }
}

# --- optionally rebuild the onboarding installer --------------------------
$OnboardingDir = Join-Path $RepoRoot "onboarding"
$OnboardExePath = Join-Path $OnboardingDir "dist\onboard.exe"
# The onboard build's exit code, kept for the publish below -- the OPS-7 fix
# above, applied to the half it was never applied to (SHIP-1, 2026-08-14). 0
# also means "no rebuild was asked for".
$script:OnboardPyInstallerExit = 0
if ($RebuildOnboard) {
    $onboardPython = Join-Path $OnboardingDir ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $onboardPython)) {
        Write-Warn2 "no venv at $onboardPython -- falling back to 'python' on PATH"
        $onboardPython = "python"
    }
    if ($DryRun) {
        Write-Step "[dry-run] would run: $onboardPython -m PyInstaller build_onboard.spec --noconfirm (in $OnboardingDir)"
    }
    else {
        Write-Step "rebuilding onboard.exe with PyInstaller (this takes a minute)..."
        Push-Location $OnboardingDir
        $prevEAP = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        try {
            & $onboardPython -m PyInstaller build_onboard.spec --noconfirm 2>&1 |
                ForEach-Object { Write-Host "    $_" }
            $script:OnboardPyInstallerExit = $LASTEXITCODE
            if ($script:OnboardPyInstallerExit -ne 0) {
                Write-Warn2 "PyInstaller exited $script:OnboardPyInstallerExit -- onboard.exe may be stale or missing"
            }
            else {
                Write-Step "onboard.exe rebuilt"
            }
        }
        finally {
            $ErrorActionPreference = $prevEAP
            Pop-Location
        }
        # SHIP-1 (2026-08-14): a failed onboard build used to be a yellow
        # WARNING and nothing else, so the run carried on and -Publish uploaded
        # YESTERDAY'S onboard.exe under the NEW installer version. The only
        # thing standing in the way was the "older than the companion exe"
        # mtime test below, which passes whenever the companion was not rebuilt
        # in the same run -- i.e. exactly the R13 recovery invocation
        # (-RebuildOnboard -Publish -MakeCurrent, no -RebuildExe). That hands
        # every new editor a companion that cannot self-update (the 2026-07-25
        # rollout failure), and the channel refuses to reuse a version for
        # different bytes, so undoing it costs another version bump.
        if ($script:OnboardPyInstallerExit -ne 0) {
            Set-Failed "PyInstaller exited $script:OnboardPyInstallerExit for onboard.exe -- dist\ still holds the PREVIOUS installer"
        }
    }
}

# --- work out what goes in ------------------------------------------------
# source path (repo-relative) -> name inside the package
$Files = @(
    @{ Src = "installer\START_HERE.md";           Dst = "START_HERE.md" },
    @{ Src = "installer\FIRST_UPGRADE.md";        Dst = "FIRST_UPGRADE.md" },
    @{ Src = "installer\windows_bootstrap.ps1";   Dst = "windows_bootstrap.ps1" },
    @{ Src = "installer\windows_upgrade.ps1";     Dst = "windows_upgrade.ps1" },
    @{ Src = "installer\windows_uninstall.ps1";   Dst = "windows_uninstall.ps1" },
    @{ Src = "installer\macos_bootstrap.sh";      Dst = "macos_bootstrap.sh" },
    @{ Src = "installer\macos_uninstall.sh";      Dst = "macos_uninstall.sh" },
    @{ Src = "docs\EDITOR_SETUP.md";              Dst = "EDITOR_SETUP.md" },
    @{ Src = "companion\config.example.toml";     Dst = "config.example.toml" },
    @{ Src = "companion\dist\ccsync-companion.exe"; Dst = "ccsync-companion.exe" },
    # The one-click onboarding installer (bundles the companion exe + bootstrap
    # + account verification). This is the preferred path for a new editor;
    # the loose scripts/exe above remain for manual/repair use.
    @{ Src = "onboarding\dist\onboard.exe"; Dst = "onboard.exe" }
)

# Present only when the exe came out of tools\release.ps1 (which is the point
# -- see docs\RELEASE.md). It is what lets windows_upgrade.ps1 say WHICH
# version it just installed and lets tools\check_deploy_drift.ps1 name the
# installed build on a machine with no logs. Absence is not a broken package,
# so it is not in $Files: a missing entry there marks the package INCOMPLETE.
$OptionalFiles = @(
    @{ Src = "companion\dist\ccsync-release.json"; Dst = "ccsync-release.json" }
)

# --- LF guard on the one file a Mac executes ------------------------------
# macos_bootstrap.sh is $Files entry 6 and is copied to the share on EVERY
# run, so the CR scan belongs here and not (as it did until SHIP-8,
# 2026-08-14) inside `if ($Publish)`. The documented package-refresh
# invocation -- .\build_editor_package.ps1 -RebuildExe -RebuildOnboard, this
# script's own .EXAMPLE and CLAUDE.md's -- publishes nothing and pushed the
# .sh to P:\ completely unchecked; the failure then surfaced on the editor's
# Mac at line 1 ("set -eu" -> "Illegal option -"), not here.
$bootstrapSh = Join-Path $RepoRoot "installer\macos_bootstrap.sh"
if (-not (Test-Path -LiteralPath $bootstrapSh)) {
    # The copy loop below records the same file as a MISSING source; this says
    # it in the language of the thing that breaks.
    Set-Failed "no macos_bootstrap.sh at $bootstrapSh -- the editor package would ship without it"
}
elseif (Test-FileHasCr -Path $bootstrapSh) {
    Set-Failed "macos_bootstrap.sh contains CARRIAGE RETURNS -- a Mac's bash would fail on the first line. Fix the checkout (git add --renormalize installer/macos_bootstrap.sh, or re-clone with the .gitattributes rules in place); the copy in the editor package would be broken"
}
else {
    Write-Step "macos_bootstrap.sh is LF-clean"
}

if (-not $DryRun) {
    if (-not (Test-Path -LiteralPath $Destination)) {
        New-Item -ItemType Directory -Path $Destination -Force | Out-Null
        Write-Step "created $Destination"
    }
}

$missing = @()
$copyFailed = @()
foreach ($f in $Files) {
    $src = Join-Path $RepoRoot $f.Src
    $dst = Join-Path $Destination $f.Dst

    if (-not (Test-Path -LiteralPath $src)) {
        $missing += $f.Src
        Write-Warn2 "MISSING source: $($f.Src)"
        continue
    }

    $srcItem = Get-Item -LiteralPath $src
    if ($DryRun) {
        Write-Step "[dry-run] would copy $($f.Src) -> $($f.Dst)  ($([int]($srcItem.Length/1KB)) KB, modified $($srcItem.LastWriteTime))"
    }
    else {
        # One locked destination file (e.g. an editor running onboard.exe
        # straight off the share -- seen live 2026-07-25) must not abort the
        # rest of the package, nor the -Publish step below.
        try {
            Copy-Item -LiteralPath $src -Destination $dst -Force -ErrorAction Stop
            Write-Step "copied $($f.Dst)  ($([int]($srcItem.Length/1KB)) KB)"
        }
        catch {
            $copyFailed += $f.Dst
            Write-Warn2 "could NOT copy $($f.Dst): $($_.Exception.Message)"
        }
    }
}

foreach ($f in $OptionalFiles) {
    $src = Join-Path $RepoRoot $f.Src
    $dst = Join-Path $Destination $f.Dst
    if (-not (Test-Path -LiteralPath $src)) {
        Write-Skip2 "no $($f.Src) -- build with tools\release.ps1 so the package carries its provenance"
        continue
    }
    if ($DryRun) {
        Write-Step "[dry-run] would copy $($f.Src) -> $($f.Dst)"
        continue
    }
    try {
        Copy-Item -LiteralPath $src -Destination $dst -Force -ErrorAction Stop
        Write-Step "copied $($f.Dst)"
    }
    catch {
        Write-Warn2 "could NOT copy $($f.Dst): $($_.Exception.Message)"
    }
}

# --- provenance report ----------------------------------------------------
Write-Host ""
Write-Host "=================================================================="
if ($missing.Count -gt 0) {
    Write-Warn2 "$($missing.Count) source file(s) missing -- package is INCOMPLETE:"
    foreach ($m in $missing) { Write-Host "    $m" }
    Set-Failed "$($missing.Count) source file(s) missing -- the package on the share is INCOMPLETE"
}
if ($copyFailed.Count -gt 0) {
    Write-Warn2 "$($copyFailed.Count) file(s) could not be copied (locked?) -- package is STALE for:"
    foreach ($m in $copyFailed) { Write-Host "    $m" }
    Write-Warn2 "re-run this script once the lock clears to finish the package"
    Set-Failed "$($copyFailed.Count) file(s) could not be copied -- the package on the share is STALE"
}
if ($missing.Count -eq 0 -and $copyFailed.Count -eq 0) {
    Write-Step "package assembled: $($Files.Count) files"
}

# The exe is the one thing not generated from a text file in the repo, so its
# age relative to the companion sources is the thing most likely to be wrong.
if (Test-Path -LiteralPath $ExePath) {
    $exeTime = (Get-Item -LiteralPath $ExePath).LastWriteTime
    $newestSrc = Get-ChildItem -Path (Join-Path $CompanionDir "src") -Recurse -Filter *.py |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    Write-Host ""
    Write-Step "companion exe built:      $exeTime"
    if ($newestSrc) {
        Write-Step "newest companion source:  $($newestSrc.LastWriteTime)  ($($newestSrc.Name))"
        if ($newestSrc.LastWriteTime -gt $exeTime) {
            Write-Warn2 "THE EXE IS STALE -- companion source has changed since it was built."
            Write-Warn2 "Re-run this script with -RebuildExe before shipping the package."
        }
        else {
            Write-Step "exe is newer than all companion sources -- up to date"
        }
    }
}
else {
    Write-Warn2 "no companion exe at $ExePath -- run with -RebuildExe"
}

# onboard.exe bundles onboarding/*.py + the bootstrap script + the companion
# exe -- stale relative to ANY of those means new editors get old code.
if (Test-Path -LiteralPath $OnboardExePath) {
    $onboardTime = (Get-Item -LiteralPath $OnboardExePath).LastWriteTime
    $onboardInputs = @(Get-ChildItem -Path $OnboardingDir -Filter *.py -File) +
        @(Get-Item -LiteralPath (Join-Path $RepoRoot "installer\windows_bootstrap.ps1"))
    if (Test-Path -LiteralPath $ExePath) {
        $onboardInputs += Get-Item -LiteralPath $ExePath
    }
    $newestInput = $onboardInputs | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    Write-Host ""
    Write-Step "onboard.exe built:        $onboardTime"
    if ($newestInput -and $newestInput.LastWriteTime -gt $onboardTime) {
        Write-Step "newest onboard input:     $($newestInput.LastWriteTime)  ($($newestInput.Name))"
        Write-Warn2 "ONBOARD.EXE IS STALE -- re-run with -RebuildOnboard before shipping."
    }
    else {
        Write-Step "onboard.exe is newer than all of its inputs -- up to date"
    }
}
else {
    Write-Warn2 "no onboard.exe at $OnboardExePath -- run with -RebuildOnboard"
}

try {
    # Redirect INSIDE cmd, not at the PowerShell level: `& git ... 2>$null`
    # is native-command redirection, which under $ErrorActionPreference =
    # "Stop" turns git's first stderr line into a fatal NativeCommandError
    # (measured). Being inside this try, the only symptom was a silently
    # missing provenance line on every build run outside a git checkout.
    $gitDescribe = (cmd /c "git -C ""$RepoRoot"" rev-parse --short HEAD 2>nul")
    $gitDirty = (cmd /c "git -C ""$RepoRoot"" status --porcelain 2>nul")
    if ($gitDescribe) {
        Write-Host ""
        Write-Step "built from commit $gitDescribe$(if ($gitDirty) { ' (working tree has uncommitted changes)' })"
    }
}
catch {
    # git absent or not a repo -- provenance line is a nice-to-have
}
Write-Host "=================================================================="

# --- publish to the dashboard upgrade channel -----------------------------
if ($Publish) {
    Write-Host ""

    # The version single-source-of-truth is config.py's VERSION; pyproject
    # duplicates it, so drift there means somebody bumped one and not the
    # other -- refuse rather than publish an ambiguous build.
    $configPy = Join-Path $CompanionDir "src\ccsync_companion\config.py"
    $m = Select-String -Path $configPy -Pattern '^VERSION\s*=\s*"([^"]+)"'
    if (-not $m) {
        Write-Warn2 "could not parse VERSION from $configPy -- NOT publishing"
        exit 1
    }
    $version = $m.Matches[0].Groups[1].Value
    $pyproject = Join-Path $CompanionDir "pyproject.toml"
    $m2 = Select-String -Path $pyproject -Pattern '^version\s*=\s*"([^"]+)"'
    $pyprojectVersion = if ($m2) { $m2.Matches[0].Groups[1].Value } else { "" }
    if ($pyprojectVersion -ne $version) {
        Write-Warn2 "version drift: config.py says '$version', pyproject.toml says '$pyprojectVersion'"
        Write-Warn2 "set both to the same value, rebuild with -RebuildExe, and re-run -- NOT publishing"
        exit 1
    }

    if ($script:PyInstallerExit -ne 0) {
        # OPS-7: the exe in dist\ is the PREVIOUS build. Publishing it under the
        # new version number hands the fleet old bytes under a new name, and the
        # upgrade channel refuses to reuse a version for different bytes later --
        # so the mistake would be permanent without a version bump.
        Write-Warn2 "PyInstaller failed earlier in this run ($script:PyInstallerExit) -- the exe in dist\ is the PREVIOUS build; NOT publishing"
        exit 1
    }
    if (-not (Test-Path -LiteralPath $ExePath)) {
        Write-Warn2 "no exe at $ExePath -- run with -RebuildExe; NOT publishing"
        exit 1
    }
    $exeTime2 = (Get-Item -LiteralPath $ExePath).LastWriteTime
    $newestSrc2 = Get-ChildItem -Path (Join-Path $CompanionDir "src") -Recurse -Filter *.py |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($newestSrc2 -and $newestSrc2.LastWriteTime -gt $exeTime2) {
        Write-Warn2 "the exe is STALE (companion source changed since it was built)"
        Write-Warn2 "re-run with -RebuildExe -- NOT publishing"
        exit 1
    }

    $sha = (Get-FileHash -Algorithm SHA256 -LiteralPath $ExePath).Hash.ToLower()

    # Provenance cross-check against the manifest tools\release.ps1 writes.
    # Advisory only -- publishing must stay possible when the exe was built by
    # hand -- but "which commit is the fleet running?" should have an answer.
    $relManifest = Join-Path $CompanionDir "dist\ccsync-release.json"
    if (Test-Path -LiteralPath $relManifest) {
        try {
            $rel = Get-Content -LiteralPath $relManifest -Raw -Encoding UTF8 | ConvertFrom-Json
            if ("$($rel.sha256)" -ne $sha) {
                Write-Warn2 "ccsync-release.json describes a different exe than the one being published -- rebuild with tools\release.ps1"
            }
            elseif ($rel.git_dirty) {
                Write-Warn2 "publishing $($rel.version_stamp) -- built from an UNCOMMITTED tree ($($rel.git_describe)); nobody will be able to reproduce what the fleet runs"
            }
            else {
                Write-Step "provenance: v$($rel.version_stamp) built $($rel.built_at) from $($rel.git_describe)"
            }
        }
        catch {
            Write-Warn2 "could not read $relManifest -- continuing without provenance"
        }
    }
    else {
        Write-Warn2 "no ccsync-release.json in companion\dist -- this exe's provenance is unrecorded (build with tools\release.ps1)"
    }

    $mc = if ($MakeCurrent) { 1 } else { 0 }
    $uri = "$DashboardUrl/api/v1/admin/packages/windows/${version}?sha256=$sha&make_current=$mc"

    # --- the onboarding installer rides along as kind=onboard --------------
    # It bundles the companion exe, so a stale one hands new editors an old
    # companion (the 2026-07-25 rollout failure). Problems here only skip the
    # installer upload; the companion publish still proceeds.
    $onboardVersion = ""
    $onboardSha = ""
    $onboardUri = ""
    $onboardSkipReason = ""
    $bootstrapPs1 = Join-Path $RepoRoot "installer\windows_bootstrap.ps1"
    $mIv = Select-String -Path $bootstrapPs1 -Pattern '^\$InstallerVersion\s*=\s*"([^"]+)"'
    $stepsPy = Join-Path $RepoRoot "onboarding\steps.py"
    $mIv2 = Select-String -Path $stepsPy -Pattern '^INSTALLER_VERSION\s*=\s*"([^"]+)"'
    # Third copy of the same number: the macOS bootstrap ships in the same
    # editor package, and the macos onboard channel (the zipped wizard, built
    # on the Mac) carries the same number -- the advisory below compares
    # against it. ($bootstrapSh and its LF guard now live above the copy loop,
    # because that copy happens whether or not this run publishes -- SHIP-8.)
    $mIv3 = $null
    if (Test-Path -LiteralPath $bootstrapSh) {
        $mIv3 = Select-String -Path $bootstrapSh -Pattern '^INSTALLER_VERSION="([^"]+)"'
    }
    if ($script:OnboardPyInstallerExit -ne 0) {
        # FIRST in the chain, before any staleness heuristic (SHIP-1): the exe
        # in onboarding\dist is the PREVIOUS build, and its mtime says nothing
        # about that -- it is newer than the companion exe whenever the
        # companion was not rebuilt in this run.
        $onboardSkipReason = "PyInstaller exited $script:OnboardPyInstallerExit earlier in this run -- onboard.exe in dist\ is the PREVIOUS build"
    }
    elseif (-not $mIv -or -not $mIv2 -or -not $mIv3) {
        $onboardSkipReason = "could not parse the installer version from windows_bootstrap.ps1 / steps.py / macos_bootstrap.sh"
    }
    elseif ($mIv.Matches[0].Groups[1].Value -ne $mIv2.Matches[0].Groups[1].Value) {
        $onboardSkipReason = "installer version drift: windows_bootstrap.ps1 says '$($mIv.Matches[0].Groups[1].Value)', steps.py says '$($mIv2.Matches[0].Groups[1].Value)'"
    }
    elseif ($mIv.Matches[0].Groups[1].Value -ne $mIv3.Matches[0].Groups[1].Value) {
        $onboardSkipReason = "installer version drift: windows_bootstrap.ps1 says '$($mIv.Matches[0].Groups[1].Value)', macos_bootstrap.sh says '$($mIv3.Matches[0].Groups[1].Value)'"
    }
    elseif (-not (Test-Path -LiteralPath $OnboardExePath)) {
        $onboardSkipReason = "no onboard.exe at $OnboardExePath (build with -RebuildOnboard)"
    }
    elseif ((Get-Item -LiteralPath $OnboardExePath).LastWriteTime -lt (Get-Item -LiteralPath $ExePath).LastWriteTime) {
        $onboardSkipReason = "onboard.exe is OLDER than the companion exe it should bundle -- re-run with -RebuildOnboard"
    }
    else {
        $onboardVersion = $mIv.Matches[0].Groups[1].Value
        $onboardSha = (Get-FileHash -Algorithm SHA256 -LiteralPath $OnboardExePath).Hash.ToLower()
        $onboardUri = "$DashboardUrl/api/v1/admin/packages/windows/${onboardVersion}?kind=onboard&sha256=$onboardSha&make_current=$mc"
    }

    # --- the macOS installer is NOT published from here (since 1.0.17) ------
    # The macos kind=onboard package is the ZIPPED ONBOARDING WIZARD
    # (CCSync Onboarding.app), and PyInstaller does not cross-compile: it is
    # built and published from the Mac by tools/build_onboard_macos.sh
    # --publish --make-current. Publishing macos_bootstrap.sh into that slot
    # from here (the pre-1.0.17 behavior) would collide with the wizard at
    # the same shared version number and hand Macs a Terminal script instead
    # of the wizard. What remains here: the channel-staleness advisory further
    # down. (The LF guard on the .sh that ships INSIDE the editor package on
    # P:\ ran above, before the copy loop -- SHIP-8.)

    # A skipped installer upload is a FAILED ship, not a footnote: the whole
    # point of -Publish is that the dashboard's [ INSTALLER ] download serves
    # the build just made. Warning-and-continuing here (while ship.ps1 checked
    # only $LASTEXITCODE) is the same root cause as B23.
    if ($onboardSkipReason) {
        Set-Failed "the onboarding installer was NOT published: $onboardSkipReason"
    }

    if ($DryRun) {
        Write-Step "[dry-run] would publish v$version ($([int]((Get-Item -LiteralPath $ExePath).Length/1KB)) KB, sha256 $($sha.Substring(0,12))...) via PUT $uri as $AdminUser"
        if ($onboardSkipReason) {
            Write-Warn2 "[dry-run] installer upload would be SKIPPED: $onboardSkipReason"
        }
        else {
            Write-Step "[dry-run] would publish installer v$onboardVersion ($([int]((Get-Item -LiteralPath $OnboardExePath).Length/1KB)) KB, sha256 $($onboardSha.Substring(0,12))...) via PUT $onboardUri"
        }
        if (Test-Path -LiteralPath $bootstrapSh) {
            Write-Step "[dry-run] macos_bootstrap.sh ($([int]((Get-Item -LiteralPath $bootstrapSh).Length/1KB)) KB) ships inside the editor package (CR-scanned above); NOT published from here since 1.0.17"
        }
        Write-Step "[dry-run] would then check the macos INSTALLER and COMPANION channels against the repo versions (both are built on the Mac: tools/build_onboard_macos.sh --publish / tools/release_macos.sh --publish)"
    }
    else {
        $securePw = Read-Host "dashboard password for '$AdminUser'" -AsSecureString
        $pw = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
            [Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePw))
        try {
            $login = Invoke-RestMethod -Method Post -Uri "$DashboardUrl/api/v1/login" `
                -ContentType "application/json" `
                -Body (@{ username = $AdminUser; password = $pw } | ConvertTo-Json) `
                -SessionVariable dashSession
        }
        catch {
            Write-Warn2 "dashboard login failed: $($_.Exception.Message) -- NOT publishing"
            exit 1
        }
        if (-not $login.is_admin) {
            Write-Warn2 "'$AdminUser' is not a dashboard admin (DASH_ADMIN_USERS) -- NOT publishing"
            exit 1
        }
        $result = $null
        try {
            # -InFile streams the exe from disk under PS 5.1 -- no in-memory copy.
            $result = Invoke-RestMethod -Method Put -Uri $uri -InFile $ExePath `
                -ContentType "application/octet-stream" -WebSession $dashSession
        }
        catch {
            $status = 0
            try { $status = [int]$_.Exception.Response.StatusCode } catch {}
            if ($status -eq 409) {
                # Same version already on the server -- the same two cases the
                # installer upload below has always distinguished, and for the
                # same reason. Different bytes is a real stop. IDENTICAL bytes
                # is not: it means this exact build already published and a
                # LATER step failed, which is precisely the state a half-failed
                # ship leaves behind (2026-08-12: the companion published, the
                # installer 409'd on an unbumped version, and the rerun needed
                # to redo the installer alone -- exiting here made that
                # impossible without hand-rolling the PUT).
                $serverSha = ""
                try {
                    $cview = Invoke-RestMethod -Method Get -Uri "$DashboardUrl/api/v1/admin/packages" -WebSession $dashSession
                    $serverSha = ($cview.packages | Where-Object {
                        $_.kind -eq "companion" -and $_.platform -eq "windows" -and $_.version -eq $version
                    } | Select-Object -First 1).sha256
                } catch {}
                if ($serverSha -and $serverSha -eq $sha) {
                    Write-Step "companion v$version is already published (byte-identical) -- not republishing, continuing to the installer"
                    if ($MakeCurrent) {
                        Write-Step "NOTE: -MakeCurrent could not be applied by a skipped upload -- confirm v$version is CURRENT on the dashboard admin page"
                    }
                }
                else {
                    Write-Warn2 "version $version is ALREADY published on the server$(if ($serverSha) { ' WITH DIFFERENT CONTENT -- the fleet would keep the OLD build' })."
                    Write-Warn2 "bump VERSION in companion\src\ccsync_companion\config.py AND companion\pyproject.toml, then re-run with -RebuildExe -Publish"
                    exit 1
                }
            }
            else {
                Write-Warn2 "publish failed: $($_.Exception.Message)"
                exit 1
            }
        }
        if ($result) {
            Write-Step "published v$version to $DashboardUrl$(if ($MakeCurrent) { ' and made it CURRENT' })"
            try {
                $retained = ($result.view.packages | Where-Object { $_.platform -eq "windows" -and $_.kind -eq "companion" } |
                    ForEach-Object { "$($_.version)$(if ($_.is_current) { '*' })" }) -join ", "
                Write-Step "windows companion packages on server (* = current): $retained"
            } catch {}
        }
        if (-not $MakeCurrent) {
            Write-Step "NOTE: v$version is staged but NOT current -- flip [ MAKE CURRENT ] on the dashboard admin page (or re-run with -MakeCurrent)"
        }

        # --- upload the onboarding installer -------------------------------
        if ($onboardSkipReason) {
            Write-Warn2 "installer upload SKIPPED: $onboardSkipReason"
        }
        else {
            try {
                $null = Invoke-RestMethod -Method Put -Uri $onboardUri -InFile $OnboardExePath `
                    -ContentType "application/octet-stream" -WebSession $dashSession
                Write-Step "published installer v$onboardVersion (kind=onboard)$(if ($MakeCurrent) { ' and made it CURRENT' }) -- the dashboard's [ INSTALLER ] download now serves it"
            }
            catch {
                $status = 0
                try { $status = [int]$_.Exception.Response.StatusCode } catch {}
                if ($status -eq 409) {
                    # Same version already on the server. Fine when the exe is
                    # byte-identical; a silent trap when it was rebuilt without
                    # an INSTALLER_VERSION bump -- so compare hashes and say so.
                    $serverSha = ""
                    try {
                        $view = Invoke-RestMethod -Method Get -Uri "$DashboardUrl/api/v1/admin/packages" -WebSession $dashSession
                        $serverSha = ($view.packages | Where-Object {
                            $_.kind -eq "onboard" -and $_.platform -eq "windows" -and $_.version -eq $onboardVersion
                        } | Select-Object -First 1).sha256
                    } catch {}
                    if ($serverSha -and $serverSha -ne $onboardSha) {
                        Write-Warn2 "installer v$onboardVersion is already published WITH DIFFERENT CONTENT -- the server keeps the OLD build."
                        Write-Warn2 "bump `$InstallerVersion in installer\windows_bootstrap.ps1 AND INSTALLER_VERSION in onboarding\steps.py, then re-run with -RebuildOnboard -Publish"
                        Set-Failed "the installer the fleet serves is NOT the one just built"
                    }
                    else {
                        Write-Step "installer v$onboardVersion is already published (unchanged) -- nothing to do"
                    }
                }
                else {
                    Write-Warn2 "installer publish failed: $($_.Exception.Message)"
                    Set-Failed "the onboarding installer upload failed"
                }
            }
        }

        # --- advisory: is the macOS INSTALLER channel keeping up? -----------
        # Since 1.0.17 the macos onboard package is the zipped wizard, built
        # and published only from the Mac (tools/build_onboard_macos.sh
        # --publish --make-current). Advisory only, same reasoning as the
        # companion check below: this script cannot build the artifact, so
        # failing the Windows ship would just block what CAN ship from here.
        $packagesView = $null
        try { $packagesView = $result.view } catch {}
        if (-not $packagesView) {
            try {
                $packagesView = Invoke-RestMethod -Method Get -Uri "$DashboardUrl/api/v1/admin/packages" -WebSession $dashSession
            } catch {}
        }
        $repoInstallerVersion = ""
        if ($mIv3) { $repoInstallerVersion = $mIv3.Matches[0].Groups[1].Value }
        $macOnboardCurrent = ""
        $macOnboardCurrentFile = ""
        if ($packagesView) {
            try {
                $macOnboardRow = $packagesView.packages | Where-Object {
                    $_.platform -eq "macos" -and $_.kind -eq "onboard" -and $_.is_current
                } | Select-Object -First 1
                $macOnboardCurrent = "$($macOnboardRow.version)"
                $macOnboardCurrentFile = "$($macOnboardRow.filename)"
            } catch {}
        }
        if (-not $packagesView) {
            Write-Step "NOTE: could not read the packages view -- macos installer channel not checked"
        }
        elseif (-not $macOnboardCurrent) {
            Write-Warn2 "no macos installer (kind=onboard) is published at all -- a Mac's [ INSTALLER ] click 404s; build and publish the wizard on the Mac: tools/build_onboard_macos.sh --publish --make-current"
        }
        elseif ($macOnboardCurrent -ne $repoInstallerVersion) {
            Write-Warn2 "macos installer channel at v$macOnboardCurrent (repo installer v$repoInstallerVersion) -- Macs download the OLD one; republish from the Mac: tools/build_onboard_macos.sh --publish --make-current"
        }
        elseif ($macOnboardCurrentFile -like "*.sh") {
            Write-Warn2 "macos installer channel serves the Terminal script ($macOnboardCurrentFile), not the wizard -- publish the wizard from the Mac: tools/build_onboard_macos.sh --publish --make-current"
        }
        else {
            Write-Step "macos installer channel is at v$macOnboardCurrent ($macOnboardCurrentFile) -- level with this repo"
        }

        # --- advisory: is the macOS COMPANION channel keeping up? -----------
        # This script cannot build it (PyInstaller does not cross-compile), so
        # the Mac side goes stale silently while every Windows ship succeeds.
        # Advisory only -- it never changes the exit code.
        $macCurrent = ""
        if ($packagesView) {
            try {
                $macCurrent = "$(($packagesView.packages | Where-Object {
                    $_.platform -eq "macos" -and $_.kind -eq "companion" -and $_.is_current
                } | Select-Object -First 1).version)"
            } catch {}
        }
        if (-not $packagesView) {
            Write-Step "NOTE: could not read the packages view -- macos companion channel not checked"
        }
        elseif (-not $macCurrent) {
            Write-Warn2 "no macos companion package is published at all (repo v$version) -- Mac editors have nothing to install; run tools/release_macos.sh on the Mac"
        }
        elseif ($macCurrent -ne $version) {
            Write-Warn2 "macos companion channel at v$macCurrent (repo v$version) -- run tools/release_macos.sh on the Mac"
        }
        else {
            Write-Step "macos companion channel is at v$macCurrent -- level with this repo"
        }
    }
}

# --- final verdict --------------------------------------------------------
# tools\ship.ps1 gates the local upgrade (and its "ship complete" line) on this
# exit code and nothing else.
if ($script:FinalExitCode -ne 0) {
    Write-Host ""
    Write-Warn2 "=================================================================="
    Write-Warn2 "THIS RUN DID NOT FULLY SUCCEED -- see the FAILED line(s) above."
    Write-Warn2 "=================================================================="
}
exit $script:FinalExitCode
