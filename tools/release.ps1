#requires -Version 5.1
<#
.SYNOPSIS
    Build a companion release: verify version parity, run the tests, run
    PyInstaller, and stamp a manifest describing exactly what came out.

.DESCRIPTION
    This project's recurring failure mode is not bad code, it is code that
    never reached the machines. On 2026-07-25 three rounds of fixes were
    "verified" against the repo (v0.4.5-dev) while the base rig had been
    running the v0.4.3 exe since 15:54 -- every conclusion drawn that
    afternoon was about a build nobody was running. See docs/RELEASE.md.

    The cure is a single command that always produces an artifact whose
    provenance is recorded next to it, so "which build is that?" is a
    question with an answer:

      1. VERSION PARITY. companion/src/ccsync_companion/config.py's VERSION is
         the single source of truth. companion/pyproject.toml must agree, and
         the installer version constant is duplicated between
         installer/windows_bootstrap.ps1 and onboarding/steps.py -- all
         mismatches are listed and the build refuses to start.
      2. TESTS. Both suites, each with its own venv python (-SkipTests to
         skip; the manifest records that you did).
      3. BUILD. PyInstaller against companion/build.spec, invoked exactly the
         way installer/build_editor_package.ps1 -RebuildExe invokes it.
      4. MANIFEST. companion/dist/ccsync-release.json: version, sha256, size,
         build time, git commit and dirty flag. windows_upgrade.ps1 copies
         this next to the installed exe, which is what makes
         tools/check_deploy_drift.ps1 able to name the installed build.
      5. NEXT STEPS. Publishing to the dashboard upgrade channel and
         installing locally are deliberately NOT done here -- they touch the
         fleet and the running companion. The exact commands are printed.

    This script never runs a git write command; it only reads status/rev-parse
    for provenance. A dirty working tree does not block the build (that would
    make the common case impossible), but it is called out loudly and the
    manifest version is stamped "<version>+dirty" so an artifact built from
    uncommitted work can never be mistaken for a released one.

.PARAMETER SkipTests
    Skip both test suites. Recorded in the manifest as tests_run=false.

.PARAMETER AllowDirty
    Acknowledge a dirty working tree: the multi-line warning banner is
    reduced to one line. The manifest is stamped "+dirty" either way.

.PARAMETER DryRun
    Print every step (including the exact PyInstaller command line) and
    change nothing. Use this to sanity-check the pipeline while other work
    is in flight.

.PARAMETER DashboardUrl
    Only used to render the publish command in the "what to do next" block.

.EXAMPLE
    .\tools\release.ps1

.EXAMPLE
    # quick rebuild while iterating, tests already green in another window
    .\tools\release.ps1 -SkipTests -AllowDirty
#>
[CmdletBinding()]
param(
    [switch]$SkipTests,
    [switch]$AllowDirty,
    [switch]$DryRun,
    [string]$DashboardUrl = "http://100.71.216.3:8480"
)

$ErrorActionPreference = "Stop"

function Write-Step { param([string]$m) Write-Host "[release] $m" }
function Write-Warn2 { param([string]$m) Write-Host "[release] WARNING: $m" -ForegroundColor Yellow }
function Write-Fail { param([string]$m) Write-Host "[release] FAILED: $m" -ForegroundColor Red }
function Write-Rule { Write-Host "==================================================================" }

$RepoRoot = Split-Path -Parent $PSScriptRoot
$CompanionDir = Join-Path $RepoRoot "companion"
$DashboardDir = Join-Path $RepoRoot "dashboard"
$ConfigPy = Join-Path $CompanionDir "src\ccsync_companion\config.py"
$PyprojectToml = Join-Path $CompanionDir "pyproject.toml"
$BootstrapPs1 = Join-Path $RepoRoot "installer\windows_bootstrap.ps1"
$OnboardSteps = Join-Path $RepoRoot "onboarding\steps.py"
$DistDir = Join-Path $CompanionDir "dist"
$ExePath = Join-Path $DistDir "ccsync-companion.exe"
$ManifestPath = Join-Path $DistDir "ccsync-release.json"

Write-Rule
Write-Step "repo root: $RepoRoot"
if ($DryRun) { Write-Step "DRY RUN -- nothing will be built or written" }

# --- helpers ---------------------------------------------------------------

function Get-Capture {
    # First capture group of the first matching line, or "" when absent.
    param([string]$Path, [string]$Pattern)
    if (-not (Test-Path -LiteralPath $Path)) { return "" }
    $m = Select-String -Path $Path -Pattern $Pattern
    if (-not $m) { return "" }
    return $m.Matches[0].Groups[1].Value
}

function Invoke-Native {
    # Run a native command whose INFO output goes to stderr (pytest,
    # PyInstaller) without $ErrorActionPreference='Stop' turning the first
    # stderr line into a terminating NativeCommandError -- the exact trap
    # documented in installer/build_editor_package.ps1. Success is judged by
    # the exit code, which is what this returns.
    # NOT named $Args: that is an automatic variable, and shadowing it inside
    # a function is a well-known way to get baffling argument binding.
    param([string]$Exe, [string[]]$ArgList, [string]$WorkingDir, [string]$Prefix = "    ")
    Push-Location $WorkingDir
    $prevEAP = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $Exe @ArgList 2>&1 | ForEach-Object { Write-Host "$Prefix$_" }
        return $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $prevEAP
        Pop-Location
    }
}

function Get-VenvPython {
    param([string]$ProjectDir, [string]$Label)
    $p = Join-Path $ProjectDir ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $p) { return $p }
    Write-Warn2 "no venv at $p -- falling back to 'python' on PATH for $Label"
    return "python"
}

# --- 1. version parity -----------------------------------------------------

Write-Host ""
Write-Step "--- step 1/5: version parity ---"

$Version = Get-Capture -Path $ConfigPy -Pattern '^VERSION\s*=\s*"([^"]+)"'
if (-not $Version) {
    Write-Fail "could not parse VERSION from $ConfigPy -- that file is the single source of truth; nothing else can proceed"
    exit 1
}
$PyprojectVersion = Get-Capture -Path $PyprojectToml -Pattern '^version\s*=\s*"([^"]+)"'
$BootstrapVersion = Get-Capture -Path $BootstrapPs1 -Pattern '^\$InstallerVersion\s*=\s*"([^"]+)"'
$OnboardVersion = Get-Capture -Path $OnboardSteps -Pattern '^INSTALLER_VERSION\s*=\s*"([^"]+)"'

Write-Step "companion VERSION (config.py, authoritative): $Version"
Write-Step "companion version (pyproject.toml):           $PyprojectVersion"
Write-Step "installer version (windows_bootstrap.ps1):    $BootstrapVersion"
Write-Step "installer version (onboarding/steps.py):      $OnboardVersion"

$mismatches = @()
if ($PyprojectVersion -ne $Version) {
    $mismatches += "companion/pyproject.toml says '$PyprojectVersion', companion/src/ccsync_companion/config.py says '$Version'"
}
if (-not $BootstrapVersion) {
    $mismatches += "could not parse `$InstallerVersion from installer/windows_bootstrap.ps1"
}
if (-not $OnboardVersion) {
    $mismatches += "could not parse INSTALLER_VERSION from onboarding/steps.py"
}
if ($BootstrapVersion -and $OnboardVersion -and ($BootstrapVersion -ne $OnboardVersion)) {
    # Two separate constants for one artifact pair: the bootstrap script and
    # the onboard.exe that bundles it. Drift here ships an installer that
    # reports a version it isn't.
    $mismatches += "installer version drift: windows_bootstrap.ps1 says '$BootstrapVersion', onboarding/steps.py says '$OnboardVersion'"
}

if ($mismatches.Count -gt 0) {
    Write-Host ""
    Write-Fail "version parity check failed -- $($mismatches.Count) mismatch(es):"
    foreach ($m in $mismatches) { Write-Host "    - $m" -ForegroundColor Red }
    Write-Host ""
    Write-Step "fix: set companion/src/ccsync_companion/config.py VERSION and companion/pyproject.toml version to the SAME value"
    Write-Step "     (installer version is its own number -- keep windows_bootstrap.ps1 and onboarding/steps.py in step)"
    exit 1
}
Write-Step "version parity OK"

# The dashboard ships separately (Docker) and carries its own VERSION; it is
# reported, never enforced against the companion's.
$DashboardVersion = Get-Capture -Path (Join-Path $DashboardDir "src\ccsync_dashboard\__init__.py") -Pattern '^VERSION\s*=\s*"([^"]+)"'
if ($DashboardVersion) { Write-Step "dashboard VERSION (ships separately):         $DashboardVersion" }

# --- git provenance (read-only) --------------------------------------------

# Redirect INSIDE cmd: `& git ... 2>$null` is native-command redirection,
# which under $ErrorActionPreference='Stop' makes git's first stderr line
# fatal (see build_editor_package.ps1).
$GitCommit = (cmd /c "git -C ""$RepoRoot"" rev-parse --short HEAD 2>nul")
$GitDescribe = (cmd /c "git -C ""$RepoRoot"" describe --tags --always --dirty 2>nul")
$GitStatus = (cmd /c "git -C ""$RepoRoot"" status --porcelain 2>nul")
$IsDirty = [bool]$GitStatus
$VersionStamp = $Version
if ($IsDirty) { $VersionStamp = "$Version+dirty" }

Write-Host ""
if ($IsDirty) {
    $dirtyCount = @($GitStatus | Where-Object { $_ }).Count
    if ($AllowDirty) {
        Write-Warn2 "working tree is DIRTY ($dirtyCount path(s)) -- manifest will be stamped $VersionStamp"
    }
    else {
        Write-Warn2 "############################################################"
        Write-Warn2 "# THE WORKING TREE IS DIRTY -- $dirtyCount uncommitted path(s)."
        Write-Warn2 "# The exe about to be built does NOT correspond to any commit."
        Write-Warn2 "# The manifest will be stamped '$VersionStamp'. Do not publish"
        Write-Warn2 "# a +dirty build to the fleet unless you are deliberately"
        Write-Warn2 "# testing it on your own machine."
        Write-Warn2 "############################################################"
        $companionChanges = @($GitStatus | Where-Object { $_ -match 'companion/src' })
        if ($companionChanges.Count -gt 0) {
            Write-Warn2 "uncommitted companion/src changes ($($companionChanges.Count)) -- these WILL be baked into the exe:"
            foreach ($c in ($companionChanges | Select-Object -First 12)) { Write-Host "      $c" -ForegroundColor Yellow }
            if ($companionChanges.Count -gt 12) { Write-Host "      ... and $($companionChanges.Count - 12) more" -ForegroundColor Yellow }
        }
    }
}
else {
    Write-Step "working tree clean at $GitCommit"
}

# --- 2. tests --------------------------------------------------------------

Write-Host ""
Write-Step "--- step 2/5: tests ---"

if ($SkipTests) {
    Write-Warn2 "-SkipTests: both suites skipped (recorded in the manifest as tests_run=false)"
}
else {
    $suites = @(
        @{ Name = "companion"; Dir = $CompanionDir },
        @{ Name = "dashboard"; Dir = $DashboardDir }
    )
    foreach ($s in $suites) {
        $py = Get-VenvPython -ProjectDir $s.Dir -Label $s.Name
        if ($DryRun) {
            Write-Step "[dry-run] would run: $py -m pytest -q   (in $($s.Dir))"
            continue
        }
        Write-Step "running $($s.Name) tests..."
        $code = Invoke-Native -Exe $py -ArgList @("-m", "pytest", "-q") -WorkingDir $s.Dir
        if ($code -ne 0) {
            Write-Host ""
            Write-Fail "$($s.Name) tests exited $code -- NOT building. Fix the tests, or re-run with -SkipTests if you know why."
            exit 1
        }
        Write-Step "$($s.Name) tests passed"
    }
}

# --- 3. build --------------------------------------------------------------

Write-Host ""
Write-Step "--- step 3/5: PyInstaller build ---"

$BuildPython = Get-VenvPython -ProjectDir $CompanionDir -Label "PyInstaller"
$buildArgs = @("-m", "PyInstaller", "build.spec", "--noconfirm")

if ($DryRun) {
    Write-Step "[dry-run] would run: $BuildPython $($buildArgs -join ' ')   (in $CompanionDir)"
}
else {
    Write-Step "building (this takes a minute)..."
    $code = Invoke-Native -Exe $BuildPython -ArgList $buildArgs -WorkingDir $CompanionDir
    if ($code -ne 0) {
        Write-Host ""
        Write-Fail "PyInstaller exited $code -- the exe in dist/ is stale or missing; NOT writing a manifest"
        exit 1
    }
    if (-not (Test-Path -LiteralPath $ExePath)) {
        Write-Fail "PyInstaller reported success but there is no exe at $ExePath"
        exit 1
    }
    Write-Step "built $ExePath"
}

# --- 4. manifest -----------------------------------------------------------

Write-Host ""
Write-Step "--- step 4/5: release manifest ---"

$Sha = ""
$SizeBytes = 0
$ExeTime = ""
if (Test-Path -LiteralPath $ExePath) {
    $exeItem = Get-Item -LiteralPath $ExePath
    $Sha = (Get-FileHash -Algorithm SHA256 -LiteralPath $ExePath).Hash.ToLower()
    $SizeBytes = $exeItem.Length
    $ExeTime = $exeItem.LastWriteTime.ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")

    # A build that "succeeded" against sources newer than the exe means the
    # exe on disk is not the one just described -- refuse to vouch for it.
    $newestSrc = Get-ChildItem -Path (Join-Path $CompanionDir "src") -Recurse -Filter *.py |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ((-not $DryRun) -and $newestSrc -and ($newestSrc.LastWriteTime -gt $exeItem.LastWriteTime)) {
        Write-Warn2 "companion source $($newestSrc.Name) is NEWER than the exe just built -- something changed mid-build; re-run"
    }
}
elseif (-not $DryRun) {
    Write-Fail "no exe at $ExePath"
    exit 1
}

$manifest = [ordered]@{
    version        = $Version
    version_stamp  = $VersionStamp
    platform       = "windows"
    artifact       = "ccsync-companion.exe"
    sha256         = $Sha
    size_bytes     = $SizeBytes
    built_at       = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    artifact_mtime = $ExeTime
    git_commit     = "$GitCommit".Trim()
    git_describe   = "$GitDescribe".Trim()
    git_dirty      = $IsDirty
    tests_run      = (-not $SkipTests)
    built_by       = "$env:USERNAME@$env:COMPUTERNAME"
    built_with     = "tools/release.ps1"
}

if ($DryRun) {
    Write-Step "[dry-run] would write $ManifestPath :"
    ($manifest | ConvertTo-Json) -split "`n" | ForEach-Object { Write-Host "    $_" }
}
else {
    # UTF-8 without BOM: this file is read back by PowerShell AND (potentially)
    # by python's json module, which chokes on a BOM.
    $utf8NoBom = New-Object System.Text.UTF8Encoding $false
    [System.IO.File]::WriteAllText($ManifestPath, ($manifest | ConvertTo-Json), $utf8NoBom)
    Write-Step "wrote $ManifestPath"
    Write-Step "  version : $VersionStamp"
    Write-Step "  sha256  : $Sha"
    Write-Step "  size    : $([int]($SizeBytes/1KB)) KB"
    Write-Step "  commit  : $("$GitDescribe".Trim())"
}

# --- 5. what to do next ----------------------------------------------------

$shaShort = "<sha256>"
if ($Sha) { $shaShort = $Sha }

Write-Host ""
Write-Rule
Write-Step "--- step 5/5: NOTHING IS DEPLOYED YET. Two things left. ---"
Write-Rule
Write-Host ""
Write-Host "  A. PUBLISH to the dashboard upgrade channel (this is what the fleet"
Write-Host "     self-upgrades to; until you do it, every editor stays put):"
Write-Host ""
Write-Host "       .\installer\build_editor_package.ps1 -Publish -MakeCurrent"
Write-Host ""
Write-Host "     That assembles the editor package AND does the upload for you:"
Write-Host "       PUT $DashboardUrl/api/v1/admin/packages/windows/$Version" -ForegroundColor Gray
Write-Host "           ?sha256=$shaShort&make_current=1" -ForegroundColor Gray
Write-Host "       body = the raw exe bytes, session cookie from POST /api/v1/login" -ForegroundColor Gray
Write-Host "     Without -MakeCurrent the build is staged; flip [ MAKE CURRENT ] on"
Write-Host "     the dashboard admin page when you want the fleet to take it"
Write-Host "       (POST $DashboardUrl/api/v1/admin/packages/windows/$Version/current)." -ForegroundColor Gray
Write-Host "     A 409 means this version is already published -- bump VERSION."
if ($IsDirty) {
    Write-Host ""
    Write-Warn2 "     ^ this build is $VersionStamp. Publishing a +dirty build to the"
    Write-Warn2 "       fleet means nobody can ever reproduce what they are running."
}
Write-Host ""
Write-Host "  B. INSTALL LOCALLY (this machine keeps running the OLD exe until you"
Write-Host "     do -- the 2026-07-25 v0.4.3-vs-v0.4.5 incident in one sentence):"
Write-Host ""
Write-Host "       .\installer\windows_upgrade.ps1 -CompanionExe `"$ExePath`""
Write-Host ""
Write-Host "     which stops ccsync-companion.exe, copies into"
Write-Host "     %LOCALAPPDATA%\ccsync\bin, re-registers the HKCU\...\Run"
Write-Host "     `"CCSyncCompanion`" autostart, and relaunches it."
Write-Host ""
Write-Host "  THEN VERIFY -- do not skip this:"
Write-Host ""
Write-Host "       .\tools\check_deploy_drift.ps1"
Write-Host ""
Write-Host "     It must report the installed exe as v$Version. If it does not, the"
Write-Host "     thing you are about to test is not the thing you just built."
Write-Host ""
Write-Rule
if ($DryRun) { Write-Step "dry run complete -- nothing was built, written, published, or installed" }

# Say the exit code out loud. Invoke-Native pipes native stderr through
# 2>&1, and in Windows PowerShell 5.1 that wraps every stderr line in a
# NativeCommandError record -- pytest writes to stderr even on a clean run,
# so the script's IMPLICIT exit code came back -1/255 after a fully
# successful build. Failure paths above all exit non-zero explicitly and are
# unaffected; this only closes the success path, so a CI step or a wrapper
# script can trust "did release.ps1 succeed?" (2026-07-25).
exit 0
