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
    \\<nas>\TheCreatorsPool\Creators_Club since 2026-07-26) -- the single
    source of truth for editor packages, so every update lands there and
    there is only ever one copy to reason about. An existing folder is
    overwritten file-by-file, not deleted.

    Note this path is NOT distributed by the sync lanes: lane B's filter only
    brings down Proxy/ contents, and the Syncthing folders are scoped to
    individual projects under Projects/, so Assets/ never leaves the NAS on
    its own. Editors get the package by being pointed at the share (or sent
    a copy) -- it will not appear in their Creators_Club folder by magic.

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

.PARAMETER MakeCurrent
    With -Publish: immediately make the uploaded version the one offered to
    the fleet. Without it the build is staged and you flip [ MAKE CURRENT ]
    on the dashboard's admin page when ready.

.PARAMETER DashboardUrl
    Dashboard base URL for -Publish. Defaults to the tailnet address; on the
    base rig's LAN use http://192.168.0.102:8480.

.PARAMETER AdminUser
    Dashboard admin username for -Publish (must be in DASH_ADMIN_USERS).

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
    [string]$DashboardUrl = "http://100.71.216.3:8480",
    [string]$AdminUser = "alex"
)

$ErrorActionPreference = "Stop"

function Write-Step { param([string]$m) Write-Host "[pkg] $m" }
function Write-Warn2 { param([string]$m) Write-Host "[pkg] WARNING: $m" -ForegroundColor Yellow }
function Write-Skip2 { param([string]$m) Write-Host "[pkg] (skip) $m" -ForegroundColor DarkGray }

$RepoRoot = Split-Path -Parent $PSScriptRoot
$CompanionDir = Join-Path $RepoRoot "companion"
$ExePath = Join-Path $CompanionDir "dist\ccsync-companion.exe"

Write-Step "repo root: $RepoRoot"
Write-Step "destination: $Destination"

# --- optionally rebuild the companion exe ---------------------------------
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
            if ($LASTEXITCODE -ne 0) {
                Write-Warn2 "PyInstaller exited $LASTEXITCODE -- the exe may be stale or missing"
            }
            else {
                Write-Step "exe rebuilt"
            }
        }
        finally {
            $ErrorActionPreference = $prevEAP
            Pop-Location
        }
    }
}

# --- optionally rebuild the onboarding installer --------------------------
$OnboardingDir = Join-Path $RepoRoot "onboarding"
$OnboardExePath = Join-Path $OnboardingDir "dist\onboard.exe"
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
            if ($LASTEXITCODE -ne 0) {
                Write-Warn2 "PyInstaller exited $LASTEXITCODE -- onboard.exe may be stale or missing"
            }
            else {
                Write-Step "onboard.exe rebuilt"
            }
        }
        finally {
            $ErrorActionPreference = $prevEAP
            Pop-Location
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
}
if ($copyFailed.Count -gt 0) {
    Write-Warn2 "$($copyFailed.Count) file(s) could not be copied (locked?) -- package is STALE for:"
    foreach ($m in $copyFailed) { Write-Host "    $m" }
    Write-Warn2 "re-run this script once the lock clears to finish the package"
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
    if (-not $mIv -or -not $mIv2) {
        $onboardSkipReason = "could not parse the installer version from windows_bootstrap.ps1 / steps.py"
    }
    elseif ($mIv.Matches[0].Groups[1].Value -ne $mIv2.Matches[0].Groups[1].Value) {
        $onboardSkipReason = "installer version drift: windows_bootstrap.ps1 says '$($mIv.Matches[0].Groups[1].Value)', steps.py says '$($mIv2.Matches[0].Groups[1].Value)'"
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

    if ($DryRun) {
        Write-Step "[dry-run] would publish v$version ($([int]((Get-Item -LiteralPath $ExePath).Length/1KB)) KB, sha256 $($sha.Substring(0,12))...) via PUT $uri as $AdminUser"
        if ($onboardSkipReason) {
            Write-Warn2 "[dry-run] installer upload would be SKIPPED: $onboardSkipReason"
        }
        else {
            Write-Step "[dry-run] would publish installer v$onboardVersion ($([int]((Get-Item -LiteralPath $OnboardExePath).Length/1KB)) KB, sha256 $($onboardSha.Substring(0,12))...) via PUT $onboardUri"
        }
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
        try {
            # -InFile streams the exe from disk under PS 5.1 -- no in-memory copy.
            $result = Invoke-RestMethod -Method Put -Uri $uri -InFile $ExePath `
                -ContentType "application/octet-stream" -WebSession $dashSession
        }
        catch {
            $status = 0
            try { $status = [int]$_.Exception.Response.StatusCode } catch {}
            if ($status -eq 409) {
                Write-Warn2 "version $version is ALREADY published on the server."
                Write-Warn2 "bump VERSION in companion\src\ccsync_companion\config.py AND companion\pyproject.toml, then re-run with -RebuildExe -Publish"
            }
            else {
                Write-Warn2 "publish failed: $($_.Exception.Message)"
            }
            exit 1
        }
        Write-Step "published v$version to $DashboardUrl$(if ($MakeCurrent) { ' and made it CURRENT' })"
        try {
            $retained = ($result.view.packages | Where-Object { $_.platform -eq "windows" -and $_.kind -eq "companion" } |
                ForEach-Object { "$($_.version)$(if ($_.is_current) { '*' })" }) -join ", "
            Write-Step "windows companion packages on server (* = current): $retained"
        } catch {}
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
                    }
                    else {
                        Write-Step "installer v$onboardVersion is already published (unchanged) -- nothing to do"
                    }
                }
                else {
                    Write-Warn2 "installer publish failed: $($_.Exception.Message)"
                }
            }
        }
    }
}
