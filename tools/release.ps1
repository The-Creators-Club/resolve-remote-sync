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
         the installer version constant is duplicated three ways --
         installer/windows_bootstrap.ps1, onboarding/steps.py and
         installer/macos_bootstrap.sh -- all mismatches are listed and the
         build refuses to start. The companion VERSION must also LOOK like
         1.2.3: the dashboard rejects anything else, so a "-rc1" would build
         fine here and 422 at the publish (SHIP-11).

         The same step also byte-compares the VENDORED files -- three pairs as
         of 2026-08-18, see $VendorPairs below. The companion's ytdl_common.py
         must match ytdl/web's (docs/YTDL_LOCAL_DOWNLOAD.md section 5); and
         broll/web's normalize.py and identity.py must match broll/indexer's
         and ytdl/web's (docs/BROLL_INGEST_PLAN.md section 3.1). Drift in any of
         them is not a wrong version number: it is two spellings of the same
         downloaded clip in one canonical tree, or a CJK search blob nothing
         matches, or two answers to "which editor is this companion".

         This script builds the WINDOWS artifact. PyInstaller does not
         cross-compile, so the macOS companion is built on the Mac by
         tools/release_macos.sh, which mirrors these steps and publishes to
         the same dashboard channel.
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
    No default since 2026-08-17 (WP0): it used to be one deployment's tailnet
    address. $env:CCSYNC_DASHBOARD_URL is used when the flag is absent, and
    with neither the block prints a placeholder instead of somebody's URL.

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
    [string]$DashboardUrl = ""
)

# Authenticode signing (COMMERCIAL_READINESS.md item 4, 2026-08-17). Set ONE
# of these in the release rig's environment; with neither, the build is
# stamped UNSIGNED and says so loudly:
#   $env:CCSYNC_SIGN_THUMBPRINT  -- SHA1 thumbprint of a cert in CurrentUser\My
#                                   (what an EV token/HSM presents)
#   $env:CCSYNC_SIGN_PFX + $env:CCSYNC_SIGN_PFX_PASSWORD  -- an OV .pfx on disk
# $env:CCSYNC_SIGN_TIMESTAMP_URL overrides the RFC3161 timestamp server. A
# timestamp is not optional: without one every signature this build ever made
# turns invalid the day the certificate expires.
$SignThumbprint = "$env:CCSYNC_SIGN_THUMBPRINT".Trim()
$SignPfx = "$env:CCSYNC_SIGN_PFX".Trim()
$SignPfxPassword = "$env:CCSYNC_SIGN_PFX_PASSWORD"
$SignTimestampUrl = "$env:CCSYNC_SIGN_TIMESTAMP_URL".Trim()
if (-not $SignTimestampUrl) { $SignTimestampUrl = "http://timestamp.digicert.com" }

if (-not $DashboardUrl -and $env:CCSYNC_DASHBOARD_URL) { $DashboardUrl = $env:CCSYNC_DASHBOARD_URL }
if (-not $DashboardUrl) { $DashboardUrl = "<your-dashboard-url>" }

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
$BootstrapSh = Join-Path $RepoRoot "installer\macos_bootstrap.sh"
# The vendored-file parity pairs (docs/YTDL_LOCAL_DOWNLOAD.md section 5,
# 2026-08-14; docs/BROLL_INGEST_PLAN.md section 3.3, 2026-08-18). The OTHER
# tree's copy is the SOURCE OF TRUTH in every pair; the companion carries a
# header and then the same bytes, because the frozen exe has neither ytdlweb
# nor broll_index in it and never will.
$VendorMarker = "# --- vendored content below, byte-identical ---"
$VendorPairs = @(
    # ytdl: the two download executors must produce byte-identical artifacts.
    @{ Source = Join-Path $RepoRoot "ytdl\web\ytdlweb\ytdl_common.py"
       Vendored = Join-Path $CompanionDir "src\ccsync_companion\ytdl_common.py"
       Mode = "marker"
       Fix = "make the change in ytdl/web/ytdlweb/ytdl_common.py -- it is the source of truth -- and bump TEMPLATE_VERSION/SIDECAR_VERSION there if the shape changed" }
    # b-roll ingest: the companion indexes clips with the indexer's own local
    # backend. A drifted copy here means the SAME clip is described by two
    # different pipelines into one database -- silent index skew, discovered
    # (if ever) as "the search results depend on which machine indexed it".
    @{ Source = Join-Path $RepoRoot "broll\indexer\broll_index\local_models.py"
       Vendored = Join-Path $CompanionDir "src\ccsync_companion\broll_vlm\local_models.py"
       Mode = "marker"; Fix = "edit broll/indexer/broll_index/local_models.py, then re-copy it in" }
    @{ Source = Join-Path $RepoRoot "broll\indexer\broll_index\local_runtime.py"
       Vendored = Join-Path $CompanionDir "src\ccsync_companion\broll_vlm\local_runtime.py"
       Mode = "marker"; Fix = "edit broll/indexer/broll_index/local_runtime.py, then re-copy it in" }
    @{ Source = Join-Path $RepoRoot "broll\indexer\broll_index\local_vlm.py"
       Vendored = Join-Path $CompanionDir "src\ccsync_companion\broll_vlm\local_vlm.py"
       Mode = "marker"; Fix = "edit broll/indexer/broll_index/local_vlm.py, then re-copy it in" }
    @{ Source = Join-Path $RepoRoot "broll\indexer\broll_index\compact_format.py"
       Vendored = Join-Path $CompanionDir "src\ccsync_companion\broll_vlm\compact_format.py"
       Mode = "marker"; Fix = "edit broll/indexer/broll_index/compact_format.py, then re-copy it in" }
    @{ Source = Join-Path $RepoRoot "broll\indexer\broll_index\contract.py"
       Vendored = Join-Path $CompanionDir "src\ccsync_companion\broll_vlm\contract.py"
       Mode = "marker"; Fix = "edit broll/indexer/broll_index/contract.py, then re-copy it in" }
    # The prompt carries NO header: its bytes are what the model is sent, so a
    # header would be part of the prompt AND would differ between the two
    # pipelines. Whole-file equality instead -- a stricter check, not a weaker
    # one (companion/src/ccsync_companion/broll_vlm/__init__.py says the same).
    @{ Source = Join-Path $RepoRoot "broll\indexer\broll_index\prompts\index_clip_v7_compact.md"
       Vendored = Join-Path $CompanionDir "src\ccsync_companion\broll_vlm\prompts\index_clip_v7_compact.md"
       Mode = "exact"; Fix = "copy broll/indexer/broll_index/prompts/index_clip_v7_compact.md over the companion's copy whole -- it has no header" }
    # b-roll ingest (docs/BROLL_INGEST_PLAN.md section 3.1): two more pairs that
    # never involve the companion -- they cross from one deployed tree to
    # another inside the container, a gap no import can close.
    @{ Source = Join-Path $RepoRoot "broll\indexer\broll_index\normalize.py"
       Vendored = Join-Path $RepoRoot "broll\web\app\normalize.py"
       Mode = "marker"; Fix = "edit broll/indexer/broll_index/normalize.py (a search_norm built by a different tokenisation than the query path matches NOTHING), then re-copy it in" }
    @{ Source = Join-Path $RepoRoot "ytdl\web\ytdlweb\identity.py"
       Vendored = Join-Path $RepoRoot "broll\web\app\identity.py"
       Mode = "marker"; Fix = "edit ytdl/web/ytdlweb/identity.py (two verifiers that disagree about a token shape are two answers to 'which editor is this'), then re-copy it in" }
    # Music ingest (docs/MUSIC_INGEST_PLAN.md step 2): the THIRD copy of the
    # identity verifier, for the third fleet-token surface. musicweb can import
    # neither of the other two -- ytdl is feature-gated per site, and broll/web
    # is the tree deployed as top-level `app`, the one name musicweb must never
    # depend on.
    @{ Source = Join-Path $RepoRoot "ytdl\web\ytdlweb\identity.py"
       Vendored = Join-Path $RepoRoot "music\web\musicweb\identity.py"
       Mode = "marker"; Fix = "edit ytdl/web/ytdlweb/identity.py (three verifiers that disagree about a token shape are three answers to 'which editor is this'), then re-copy it in" }
)
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

function Get-FileBytesAsText {
    # A file's bytes as a string whose chars ARE those bytes: Latin-1 (28591)
    # maps 0x00-0xFF one-to-one, so IndexOf/Substring/Equals below are byte
    # operations. Get-Content would decode UTF-8 and normalise line endings --
    # both of which would make a BYTE comparison lie (2026-08-14).
    param([string]$Path)
    return [System.Text.Encoding]::GetEncoding(28591).GetString(
        [System.IO.File]::ReadAllBytes($Path))
}

function Get-VendorParityProblem {
    <#
        Is the companion's vendored copy still byte-identical to its source?

        docs/YTDL_LOCAL_DOWNLOAD.md section 5: server and companion must produce
        byte-identical artifacts for the same clip -- same outtmpl, same
        sidecar, same fallback rung -- because they write into ONE canonical
        tree that syncs fleet-wide. A vendored copy that drifts does not throw;
        it quietly grows a second spelling of the same video, discovered months
        later. So this refuses the build the way the installer version drift
        check above does.

        The same reasoning covers the broll_vlm set (2026-08-18): the
        companion describes clips with the INDEXER's local backend, so a
        drifted copy has two pipelines writing differently-shaped index rows
        into one database.

        $Mode "exact" compares the WHOLE file instead of the part below the
        marker -- for a vendored copy that cannot carry a header at all (the
        VLM prompt: its bytes are what the model is sent).

        Returns "" when the two agree, or a one-line description of the
        problem. FAIL SAFE: a missing, unreadable or marker-less file is a
        problem, never a skip -- "I could not check" must not read as "fine".
    #>
    param([string]$SourcePath, [string]$VendoredPath, [string]$Marker,
          [string]$Mode = "marker")

    foreach ($p in @($SourcePath, $VendoredPath)) {
        if (-not (Test-Path -LiteralPath $p)) {
            return "cannot read $p (missing) -- refusing rather than skipping the check"
        }
    }
    try {
        $src = Get-FileBytesAsText -Path $SourcePath
        $vend = Get-FileBytesAsText -Path $VendoredPath
    }
    catch {
        return "cannot read the parity pair: $($_.Exception.Message)"
    }

    if ($Mode -eq "exact") {
        if ([string]::Equals($vend, $src, [StringComparison]::Ordinal)) { return "" }
        return ("the vendored copy has DRIFTED from its source: $($vend.Length) byte(s) " +
                "vs $($src.Length) in the source (this pair carries no header -- the whole " +
                "file must match)")
    }

    $first = $vend.IndexOf($Marker, [StringComparison]::Ordinal)
    if ($first -lt 0) {
        return "the vendored copy has no '$Marker' line -- that marker is what separates its header from the vendored bytes; restore it"
    }
    if ($vend.IndexOf($Marker, $first + $Marker.Length, [StringComparison]::Ordinal) -ge 0) {
        return "the vendored copy carries '$Marker' more than once -- ambiguous header end; leave exactly one, as the last line of the header"
    }

    # Strip the marker LINE, terminator and all, then compare what is left
    # against the whole source file.
    $rest = $vend.Substring($first + $Marker.Length)
    if ($rest.StartsWith("`r`n")) { $rest = $rest.Substring(2) }
    elseif ($rest.StartsWith("`n")) { $rest = $rest.Substring(1) }

    if ([string]::Equals($rest, $src, [StringComparison]::Ordinal)) { return "" }

    $n = [Math]::Min($rest.Length, $src.Length)
    $offset = $n
    for ($i = 0; $i -lt $n; $i++) {
        if ($rest[$i] -ne $src[$i]) { $offset = $i; break }
    }
    $line = ($src.Substring(0, [Math]::Min($offset, $src.Length)) -split "`n").Count
    return ("the vendored copy has DRIFTED from its source: $($rest.Length) byte(s) below the marker " +
            "vs $($src.Length) in the source, first difference at byte $offset (source line ~$line)")
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

function Install-CompanionEditable {
    <#
        Create the companion venv if it is missing and install the package
        EDITABLE into it, exactly as tools/release_macos.sh step 3/6 does.

        Why this exists: until 2026-08-04 nothing on Windows ever ran
        `pip install -e .`, because Get-VenvPython only LOCATES an
        interpreter and reuses whatever venv already sits in companion\.venv.
        Every Windows consumer of pyproject.toml reads it with a regex, so a
        UTF-8 BOM committed at 0f5d99d (PowerShell Set-Content's default)
        went unnoticed here and detonated on the first Mac that tried a clean
        install -- pip's binary tomllib.load rejects a BOM, so there was no
        way to build the companion at all. A release that never exercises an
        install cannot catch a broken package definition.

        ".[dev,tray]" mirrors the macOS script: dev is pytest, and tray
        carries pystray/Pillow, without which build.spec's import probe
        silently drops the tray and the editor gets a companion with no
        menu-bar icon.
    #>
    param([string]$ProjectDir)

    $py = Join-Path $ProjectDir ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $py)) {
        Write-Step "no venv at $py -- creating one"
        if ($DryRun) {
            Write-Step "[dry-run] would run: python -m venv .venv   (in $ProjectDir)"
        }
        else {
            $code = Invoke-Native -Exe "python" -ArgList @("-m", "venv", ".venv") -WorkingDir $ProjectDir
            if ($code -ne 0) {
                Write-Fail "python -m venv failed (exit $code) -- is python on PATH?"
                exit 1
            }
        }
    }

    if ($DryRun) {
        Write-Step "[dry-run] would run: $py -m pip install --disable-pip-version-check -e .[dev,tray]   (in $ProjectDir)"
        return
    }

    Write-Step "installing the companion (editable) + test/tray extras ..."
    $code = Invoke-Native -Exe $py -ArgList @(
        "-m", "pip", "install", "--disable-pip-version-check", "-e", ".[dev,tray]"
    ) -WorkingDir $ProjectDir
    if ($code -ne 0) {
        Write-Fail "pip install -e .[dev,tray] failed (exit $code) -- NOT building. A TOMLDecodeError on line 1 means pyproject.toml has a UTF-8 BOM; re-save it without one."
        exit 1
    }
    Write-Step "editable install OK"
}

# --- 1. version parity -----------------------------------------------------

Write-Host ""
Write-Step "--- step 1/5: version + vendored-file parity ---"

$Version = Get-Capture -Path $ConfigPy -Pattern '^VERSION\s*=\s*"([^"]+)"'
if (-not $Version) {
    Write-Fail "could not parse VERSION from $ConfigPy -- that file is the single source of truth; nothing else can proceed"
    exit 1
}
$PyprojectVersion = Get-Capture -Path $PyprojectToml -Pattern '^version\s*=\s*"([^"]+)"'
$BootstrapVersion = Get-Capture -Path $BootstrapPs1 -Pattern '^\$InstallerVersion\s*=\s*"([^"]+)"'
$OnboardVersion = Get-Capture -Path $OnboardSteps -Pattern '^INSTALLER_VERSION\s*=\s*"([^"]+)"'
# Third copy of the SAME installer number, on the macOS side. It ships in the
# editor package and is what a Mac install prints; drift here means the Mac
# and Windows installers claim to be the same release when they are not.
$MacBootstrapVersion = Get-Capture -Path $BootstrapSh -Pattern '^INSTALLER_VERSION="([^"]+)"'

Write-Step "companion VERSION (config.py, authoritative): $Version"
Write-Step "companion version (pyproject.toml):           $PyprojectVersion"
Write-Step "installer version (windows_bootstrap.ps1):    $BootstrapVersion"
Write-Step "installer version (onboarding/steps.py):      $OnboardVersion"
Write-Step "installer version (macos_bootstrap.sh):       $MacBootstrapVersion"

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
if (-not $MacBootstrapVersion) {
    $mismatches += "could not parse INSTALLER_VERSION from installer/macos_bootstrap.sh"
}
if ($BootstrapVersion -and $OnboardVersion -and ($BootstrapVersion -ne $OnboardVersion)) {
    # Three separate constants for one installer release: the Windows
    # bootstrap script, the onboard.exe that bundles it, and the macOS
    # bootstrap script shipped in the same editor package. Drift ships an
    # installer that reports a version it isn't.
    $mismatches += "installer version drift: windows_bootstrap.ps1 says '$BootstrapVersion', onboarding/steps.py says '$OnboardVersion'"
}
if ($BootstrapVersion -and $MacBootstrapVersion -and ($BootstrapVersion -ne $MacBootstrapVersion)) {
    $mismatches += "installer version drift: windows_bootstrap.ps1 says '$BootstrapVersion', installer/macos_bootstrap.sh says '$MacBootstrapVersion'"
}

if ($mismatches.Count -gt 0) {
    Write-Host ""
    Write-Fail "version parity check failed -- $($mismatches.Count) mismatch(es):"
    foreach ($m in $mismatches) { Write-Host "    - $m" -ForegroundColor Red }
    Write-Host ""
    Write-Step "fix: set companion/src/ccsync_companion/config.py VERSION and companion/pyproject.toml version to the SAME value"
    Write-Step "     (installer version is its own number -- keep windows_bootstrap.ps1, onboarding/steps.py and installer/macos_bootstrap.sh in step)"
    exit 1
}

# Agreeing with itself is not enough: the dashboard rejects anything that is
# not exactly 1.2.3 (_PACKAGE_VERSION_RE -> 422 "version must look like
# 1.2.3"). A "0.7.9-rc1" set consistently in both files passes every check
# above, survives ship's dashboard deploy and both suites and a five-minute
# PyInstaller build, and only 422s at build_editor_package's PUT. The macOS
# twin has refused it in 20 ms since it was written -- this is the port
# (SHIP-11, 2026-08-14; tools/release_macos.sh step 2/6).
if ($Version -notmatch '^[0-9]+\.[0-9]+\.[0-9]+$') {
    Write-Host ""
    Write-Fail "VERSION '$Version' does not look like 1.2.3 -- the dashboard refuses to publish anything else"
    Write-Step "fix: use a plain three-number version in companion/src/ccsync_companion/config.py and companion/pyproject.toml"
    Write-Step "     (a suffix like -rc1/-dev would build fine here and 422 at the publish, after the whole build)"
    exit 1
}
Write-Step "version parity OK"

# --- vendored-file parity (docs/YTDL_LOCAL_DOWNLOAD.md section 5, 2026-08-14;
#     docs/BROLL_INGEST_PLAN.md section 3.3, 2026-08-18) --------------------
#
# Same class of failure as the installer version drift above, one layer down:
# code duplicated across two trees that cannot import each other. The
# consequence is worse, though -- an installer that reports the wrong version
# is embarrassing, a companion whose ytdl_common has drifted from the NAS
# worker's downloads the same YouTube clip under a second filename into the one
# canonical tree, and a companion whose broll_vlm has drifted from the indexer
# describes clips with a different prompt, parser or contract into the one
# search database. Neither throws; both are found months later, if at all.
# The exe about to be built BAKES IN whatever is in companion/src, so this is
# the last moment the copies can be compared.
$vendorFailed = $false
foreach ($pair in $VendorPairs) {
    $vendorProblem = Get-VendorParityProblem -SourcePath $pair.Source `
        -VendoredPath $pair.Vendored -Marker $VendorMarker -Mode $pair.Mode
    if ($vendorProblem) {
        $vendorFailed = $true
        Write-Host ""
        Write-Fail "vendored-file parity check failed:"
        Write-Host "    - $vendorProblem" -ForegroundColor Red
        Write-Host "      source   (edit THIS one): $($pair.Source)" -ForegroundColor Red
        Write-Host "      vendored (do not edit)  : $($pair.Vendored)" -ForegroundColor Red
        Write-Host ""
        Write-Step "fix: $($pair.Fix),"
        if ($pair.Mode -eq "exact") {
            Write-Step "     as a WHOLE-FILE copy (this pair carries no header)."
        }
        else {
            Write-Step "     re-copying that whole file into the companion BELOW the marker line"
            Write-Step "     `"$VendorMarker`", leaving the companion header above it untouched."
        }
    }
}
if ($vendorFailed) { exit 1 }
Write-Step "vendored parity OK ($($VendorPairs.Count) pairs: ytdl_common.py, the broll_vlm set, broll/web normalize.py + identity.py)"

# --- release-key parity (COMMERCIAL_READINESS.md item 4, 2026-08-17) --------
# A companion built with an EMPTY RELEASE_PUBKEYS trusts nobody and can never
# be upgraded again -- it would refuse every offer, for ever, on machines with
# no other update path (the Run-key autostart is logon-only; nothing retries).
# Fail here, where it costs a minute, rather than on an editor's machine.
# The pubkey baked in must also be the one the signing key on THIS rig would
# produce, or the build ships trusting a key nobody can sign with.
$ReleasePubkeyPy = Join-Path $CompanionDir "src\ccsync_companion\release_pubkey.py"
$bakedKeys = @(Select-String -Path $ReleasePubkeyPy -Pattern '^\s*"([A-Za-z0-9+/=]{40,})",\s*$' |
    ForEach-Object { $_.Matches[0].Groups[1].Value })
if ($bakedKeys.Count -eq 0) {
    Write-Fail "no release public key is baked into $ReleasePubkeyPy."
    Write-Fail "A companion built like this refuses EVERY update, permanently."
    Write-Fail "Run:  python tools\release_key.py new   (once, ever)"
    Write-Fail "then: python tools\release_key.py bake"
    exit 1
}
Write-Step "release keys baked into the companion: $($bakedKeys.Count) ($($bakedKeys[0].Substring(0,12))...)"
$SigningKeyPath = "$env:CCSYNC_RELEASE_KEY".Trim()
if (-not $SigningKeyPath) { $SigningKeyPath = Join-Path $env:USERPROFILE ".ccsync-release\release.key" }
if (Test-Path -LiteralPath $SigningKeyPath) {
    $probePy = Get-VenvPython -ProjectDir $CompanionDir -Label "release-key check"
    $probe = & $probePy (Join-Path $PSScriptRoot "release_key.py") "pubkey" "--quiet" 2>$null
    $probe = "$probe".Trim()
    if ($probe -and ($bakedKeys -notcontains $probe)) {
        Write-Fail "the release key at $SigningKeyPath is NOT one this build trusts."
        Write-Fail "  signing key : $probe"
        Write-Fail "  baked keys  : $($bakedKeys -join ', ')"
        Write-Fail "Every editor would refuse the build you are about to publish."
        Write-Fail "Run: python tools\release_key.py bake        (replace)"
        Write-Fail "  or python tools\release_key.py bake --add  (rotation overlap)"
        exit 1
    }
}
else {
    Write-Warn2 "no release signing key at $SigningKeyPath -- the publish step will fail (python tools\release_key.py new)"
}

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

# The editable install runs even with -SkipTests: it is what proves the
# package definition is sound, and step 3 is about to build from this venv.
Install-CompanionEditable -ProjectDir $CompanionDir

if ($SkipTests) {
    Write-Warn2 "-SkipTests: both suites skipped (recorded in the manifest as tests_run=false)"
}
else {
    $suites = @(
        @{ Name = "companion"; Dir = $CompanionDir },
        @{ Name = "dashboard"; Dir = $DashboardDir }
    )
    # pytest exits 0 when tests SKIP, so a missing rclone would silently drop
    # the 24 integration tests that prove lane A carries video up-only and
    # lane B carries **/Proxy/** down-only -- the most destructive thing in
    # the system to get backwards -- and still hand us a green suite. In a
    # release, absent rclone is a failure, not a skip (see
    # companion/tests/conftest.py::rclone_binary).
    $prevRequireRclone = $env:CCSYNC_REQUIRE_RCLONE
    $env:CCSYNC_REQUIRE_RCLONE = "1"
    try {
        foreach ($s in $suites) {
            $py = Get-VenvPython -ProjectDir $s.Dir -Label $s.Name
            if ($DryRun) {
                Write-Step "[dry-run] would run: $py -m pytest -q   (in $($s.Dir), CCSYNC_REQUIRE_RCLONE=1)"
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
    finally {
        $env:CCSYNC_REQUIRE_RCLONE = $prevRequireRclone
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

# --- 3b. Authenticode --------------------------------------------------------
# COMMERCIAL_READINESS.md item 4 (2026-08-17). Two DIFFERENT signatures matter
# here and they are not substitutes:
#   * the RELEASE RECORD signature (tools/sign_release.py, ed25519, offline
#     key) is what stops the fleet installing a build the vendor did not make;
#   * this one, Authenticode, is what stops SmartScreen telling an editor that
#     "Windows protected your PC" on every fresh install, and what lets an
#     enterprise allowlist the binary.
# The build proceeds without it -- refusing would mean nobody can build
# anything until a certificate is bought -- but the manifest records
# signed_binary=false, sign_release.py signs THAT into the record, and
# tools/ship.ps1 refuses -MakeCurrent for it without -AllowUnsignedBinary.

$SignedBinary = $false
$SignAdvisory = ""

function Find-SignTool {
    $cmd = Get-Command signtool.exe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    # The SDK does not put signtool on PATH. Newest x64 build first.
    $roots = @("${env:ProgramFiles(x86)}\Windows Kits\10\bin", "$env:ProgramFiles\Windows Kits\10\bin")
    foreach ($root in $roots) {
        if (-not (Test-Path -LiteralPath $root)) { continue }
        $found = Get-ChildItem -Path $root -Filter signtool.exe -Recurse -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -match '\\x64\\' } |
            Sort-Object FullName -Descending | Select-Object -First 1
        if ($found) { return $found.FullName }
    }
    return ""
}

if (-not $DryRun -and (Test-Path -LiteralPath $ExePath)) {
    if (-not $SignThumbprint -and -not $SignPfx) {
        $SignAdvisory = "no CCSYNC_SIGN_THUMBPRINT and no CCSYNC_SIGN_PFX in the environment"
    }
    else {
        $signtool = Find-SignTool
        if (-not $signtool) {
            $SignAdvisory = "signtool.exe not found (install the Windows 10/11 SDK 'Signing Tools' feature)"
        }
        else {
            $signArgs = @("sign", "/fd", "sha256", "/tr", $SignTimestampUrl, "/td", "sha256")
            if ($SignThumbprint) {
                $signArgs += @("/sha1", $SignThumbprint)
            }
            else {
                $signArgs += @("/f", $SignPfx)
                if ($SignPfxPassword) { $signArgs += @("/p", $SignPfxPassword) }
            }
            $signArgs += $ExePath
            Write-Step "signing with signtool ($(if ($SignThumbprint) { "thumbprint $SignThumbprint" } else { "pfx $SignPfx" }))..."
            # NOT through Invoke-Native's 2>&1 pipe: the password would end up
            # in a transcript. signtool prints its own progress.
            & $signtool @signArgs | Out-Null
            if ($LASTEXITCODE -ne 0) {
                Write-Fail "signtool exited $LASTEXITCODE -- the exe is NOT signed and this run stops. Fix the certificate (or unset CCSYNC_SIGN_* to build unsigned deliberately)."
                exit 1
            }
        }
    }
    $status = (Get-AuthenticodeSignature -LiteralPath $ExePath).Status
    $SignedBinary = ($status -eq "Valid")
    if ($SignedBinary) {
        $subject = (Get-AuthenticodeSignature -LiteralPath $ExePath).SignerCertificate.Subject
        Write-Step "Authenticode: Valid -- $subject"
    }
    else {
        Write-Warn2 "=================================================================="
        Write-Warn2 "UNSIGNED BUILD. Authenticode status: $status"
        if ($SignAdvisory) { Write-Warn2 "  ($SignAdvisory)" }
        Write-Warn2 "Every editor installing this will meet SmartScreen's 'Windows"
        Write-Warn2 "protected your PC' dialog, and some AV will quarantine it."
        Write-Warn2 "Buy an OV or EV Authenticode certificate and set"
        Write-Warn2 "CCSYNC_SIGN_THUMBPRINT (or CCSYNC_SIGN_PFX + _PASSWORD)."
        Write-Warn2 "See docs/RELEASE.md 'Code signing'. tools\ship.ps1 will refuse"
        Write-Warn2 "to make this build CURRENT without -AllowUnsignedBinary."
        Write-Warn2 "=================================================================="
    }
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
    # Authenticode, NOT the release-record signature (item 4, 2026-08-17).
    # build_editor_package.ps1 re-derives this from the file itself before it
    # signs the record -- the manifest is provenance, never the authority.
    signed_binary  = $SignedBinary
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
