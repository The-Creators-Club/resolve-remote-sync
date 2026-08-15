#requires -Version 5.1
<#
.SYNOPSIS
    One command to ship everything: deploy the dashboard, publish the
    companion + installer, upgrade this machine, verify.

.DESCRIPTION
    Wraps the whole release cycle that was previously four hand-typed
    commands plus environment-variable setup:

      0. GATES      secrets present, working tree clean (a +dirty build must
         not reach the fleet -- docs/RELEASE.md), this companion version not
         already published, THIS INSTALLER VERSION not already published
         either (onboard.exe bundles the companion exe, so every ship changes
         the installer's bytes and needs its own new number -- SHIP-4), and
         the server/ + onboarding/ suites green.
         server/ is the code step 1 executes against the live NAS; the
         companion and dashboard suites run in step 2a, inside release.ps1.
      1. DASHBOARD  python server\install_dashboard_app.py  (code-only
         deploy; compose-level changes still need --recreate by hand),
         then POLLS /api/v1/health until it reports the repo's dashboard
         VERSION (a cold restart can take longer than one check).
      2. PUBLISH    tools\release.ps1 first -- version parity, the editable
         install (without which build.spec's import probe silently drops the
         tray), the COMPANION AND DASHBOARD SUITES, PyInstaller, and the
         provenance manifest -- and only then
         installer\build_editor_package.ps1 -RebuildOnboard -Publish
         -MakeCurrent to package and publish that exact artifact (prompts
         once for your dashboard admin password). Deliberately WITHOUT
         -RebuildExe: it would rebuild the exe untested and restamp the
         manifest tests_run=false, which is how ship published a companion
         to the whole fleet with the companion suite never executed (OPS-1).
         Then an ADVISORY check of the macOS companion channel -- that binary
         can only be built on a Mac (tools/release_macos.sh), so it goes
         stale silently otherwise. Warning only; it never gates the local
         upgrade.
      3. LOCAL      installer\windows_upgrade.ps1 with the exe just built,
         then tools\check_deploy_drift.ps1.

    Secrets come from user environment variables (set once with setx):
    TRUENAS_PW, DASH_REPORT_TOKEN, DASH_SESSION_SECRET, SYNCTHING_API_KEY.
    The script refuses to start with any of them missing rather than let
    install_dashboard_app.py fail halfway.

    Run it via tools\ship.cmd to skip the execution-policy dance.

.PARAMETER DashboardOnly
    Stop after step 1 (server-side template/API changes only).

.PARAMETER SkipLocalUpgrade
    Do steps 1-2 but leave this machine's companion alone.

.PARAMETER SkipTests
    Skip the server/ + onboarding/ suites in step 0. release.ps1's own
    -SkipTests is separate and is deliberately NOT implied by this: step 2a
    runs the companion and dashboard suites either way, because publishing an
    untested companion as CURRENT to the whole fleet is the failure this
    script exists to prevent (OPS-1).

.PARAMETER AllowDirty
    Publish from a dirty working tree. The build is stamped +dirty and
    nobody can reproduce what the fleet is running; use it for a deliberate
    hotfix, not out of habit.

.EXAMPLE
    .\tools\ship.cmd
.EXAMPLE
    .\tools\ship.cmd -DashboardOnly
#>
[CmdletBinding()]
param(
    [switch]$DashboardOnly,
    [switch]$SkipLocalUpgrade,
    [switch]$SkipTests,
    [switch]$AllowDirty
)

# "Continue", not "Stop": the deploy script prints an SSH host-key WARNING to
# stderr, and PS 5.1 + Stop turns any native stderr line into a terminating
# NativeCommandError (see GOTCHAS.md section 2). Success is judged by exit
# codes below.
$ErrorActionPreference = "Continue"

function Write-Step { param([string]$m) Write-Host "[ship] $m" }
function Write-Fail { param([string]$m) Write-Host "[ship] FAILED: $m" -ForegroundColor Red }

# E:\Projects\x -> /e/Projects/x, for the one command below that runs inside Git
# bash. MSYS's own drive mapping, not WSL's /mnt/e -- see step 0 for why this
# script pins Git's bash rather than whatever `bash` resolves to.
function ConvertTo-BashPath {
    param([string]$Path)
    $p = $Path -replace '\\', '/'
    if ($p -match '^([A-Za-z]):(.*)$') { return "/" + $Matches[1].ToLower() + $Matches[2] }
    return $p
}

# curl.exe is kept (it is the only thing here that reliably reports a bare HTTP
# status without downloading the body), but the fleet token NEVER rides on its
# command line: a native process's argv is readable by any unprivileged process
# via `Get-CimInstance Win32_Process`, and both calls below run while an editor
# may be logged in. `-K -` makes curl read its config -- headers included --
# from stdin instead. Same principle as server/common.py piping the sudo
# password over stdin (AUDIT SEC-2).
function Invoke-CurlWithToken {
    param(
        [string]$Uri,
        [string]$Token,
        [string[]]$ExtraArgs = @()
    )
    $config = "header = `"X-CCSync-Token: $Token`"" + "`n"
    return ($config | curl.exe -s -K - @ExtraArgs $Uri)
}

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot
Write-Step "repo root: $RepoRoot"

# --- secrets present? -------------------------------------------------------
$missing = @()
foreach ($name in @("TRUENAS_PW", "DASH_REPORT_TOKEN", "DASH_SESSION_SECRET", "SYNCTHING_API_KEY")) {
    if (-not [Environment]::GetEnvironmentVariable($name)) { $missing += $name }
}
if ($missing.Count -gt 0) {
    Write-Fail "missing environment variable(s): $($missing -join ', ')"
    Write-Step "set each once with:  setx <NAME> `"<value>`"  then open a NEW window"
    exit 1
}

# --- working tree clean? (only matters if we are going to publish) ----------
# release.ps1 stamps a dirty build "<version>+dirty" and warns -- but it warns
# in step 2, after step 1 has already deployed, and it does not stop. Nobody can
# reproduce what the fleet is running from a +dirty build, so the decision
# belongs HERE, before anything moves. Caught for real on 2026-08-10: an
# unstaged deletion left over from another session's work would have ridden
# into a fleet publish as "0.6.0+dirty".
if (-not $DashboardOnly) {
    $dirty = @(& git status --porcelain 2>$null | Where-Object { $_ -and $_.Trim() })
    if ($dirty.Count -gt 0 -and -not $AllowDirty) {
        Write-Fail "working tree is dirty -- a +dirty build must not reach the fleet (docs\RELEASE.md)"
        foreach ($line in $dirty) { Write-Host "        $line" }
        Write-Step "commit or stash the above, or re-run with -AllowDirty for a deliberate hotfix"
        exit 1
    }
    if ($dirty.Count -gt 0) {
        Write-Host "[ship] WARNING: publishing from a DIRTY tree (-AllowDirty) -- the build will be stamped +dirty" -ForegroundColor Yellow
    }
}

# --- repo versions (for the verify steps) ----------------------------------
$DashVersion = (Select-String -Path "dashboard\src\ccsync_dashboard\__init__.py" -Pattern 'VERSION\s*=\s*"([^"]+)"').Matches[0].Groups[1].Value
$CompanionVersion = (Select-String -Path "companion\src\ccsync_companion\config.py" -Pattern '^VERSION\s*=\s*"([^"]+)"').Matches[0].Groups[1].Value
Write-Step "repo says: dashboard v$DashVersion, companion v$CompanionVersion"

# --- fail fast if this companion version is already published ---------------
# The publish guard refuses to reuse a version number for different bytes --
# correctly -- but discovering that AFTER a five-minute PyInstaller build (and
# a password prompt) wasted a run twice on 2026-07-26. The download endpoint
# answers with the shared token, so check FIRST.
if (-not $DashboardOnly) {
    $pubCode = Invoke-CurlWithToken `
        -Uri "http://192.168.0.102:8480/api/v1/companion/package/windows/$CompanionVersion" `
        -Token $env:DASH_REPORT_TOKEN `
        -ExtraArgs @("-o", "NUL", "-w", "%{http_code}")
    if ($pubCode -eq "200") {
        Write-Fail "companion v$CompanionVersion is ALREADY published on the server."
        Write-Step "bump VERSION in companion\src\ccsync_companion\config.py AND companion\pyproject.toml"
        Write-Step "(and, if onboard.exe's contents changed, `$InstallerVersion in installer\windows_bootstrap.ps1 + onboarding\steps.py), then re-run"
        exit 1
    }

    # The SAME question about the OTHER artifact this ship publishes, which is
    # the one that must be bumped on EVERY ship (SHIP-4, 2026-08-14):
    # onboard.exe BUNDLES the companion exe, so a companion release changes the
    # installer's bytes by itself and an unbumped INSTALLER_VERSION is a
    # guaranteed different-bytes 409 (KNOWN_BUGS R13 -- "third time it has
    # bitten"). Without this the 409 arrives in step 2b, AFTER the dashboard
    # deploy, both suites, a five-minute PyInstaller build and the password
    # prompt, and AFTER the companion has been published and made CURRENT for
    # the whole fleet -- leaving the installer channel still serving bytes that
    # bundle the previous companion. The four copies of this number are checked
    # against EACH OTHER by step 0b and release.ps1; nothing but this asks the
    # server whether the number is still free.
    $mShipIv = Select-String -Path "installer\windows_bootstrap.ps1" -Pattern '^\$InstallerVersion\s*=\s*"([^"]+)"'
    if (-not $mShipIv) {
        Write-Fail "could not parse `$InstallerVersion from installer\windows_bootstrap.ps1 -- step 2b would refuse to publish the installer anyway"
        exit 1
    }
    $InstallerVersion = $mShipIv.Matches[0].Groups[1].Value
    Write-Step "repo says: installer v$InstallerVersion"
    # -r 0-0: the first byte is enough to answer "does this version exist" and
    # the route honours Range with a 206 (measured against the live dashboard,
    # 2026-08-14) -- so this costs one byte, not a whole onboard.exe.
    $ivCode = Invoke-CurlWithToken `
        -Uri "http://192.168.0.102:8480/api/v1/companion/package/windows/${InstallerVersion}?kind=onboard" `
        -Token $env:DASH_REPORT_TOKEN `
        -ExtraArgs @("-o", "NUL", "-r", "0-0", "--max-time", "20", "-w", "%{http_code}")
    if ($ivCode -eq "200" -or $ivCode -eq "206") {
        Write-Fail "installer v$InstallerVersion is ALREADY published on the server -- and this ship rebuilds onboard.exe around a NEW companion, so its bytes WILL differ and the upload will 409."
        Write-Step "bump `$InstallerVersion in installer\windows_bootstrap.ps1 AND INSTALLER_VERSION in onboarding\steps.py AND installer\macos_bootstrap.sh AND build_onboard_macos.spec's CFBundleShortVersionString, then re-run"
        exit 1
    }
}

# --- 0. the suite that guards what step 1 is about to do --------------------
# Step 2a runs release.ps1, which runs the companion and dashboard suites, so
# those are covered -- but it does not run server/, and server/ is the code
# step 1 EXECUTES against the live NAS. (Until 2026-08-11 this comment was
# wrong in a way that mattered: step 2 went straight to
# build_editor_package.ps1 -RebuildExe, which runs PyInstaller and NO tests, so
# ship published a companion as CURRENT with the companion suite never
# executed -- OPS-1.) That gap is not theoretical: the 2026-08-10
# music deploy died inside install_dashboard_app.py's ffmpeg step, and the
# tests that would now catch its failure modes are in server/tests. It borrows
# the dashboard's venv (no venv of its own) -- see CLAUDE.md's test table.
if (-not $SkipTests) {
    Write-Host ""
    Write-Step "--- step 0: server tests (they guard the deploy script step 1 runs) ---"
    $serverPy = Join-Path $RepoRoot "dashboard\.venv\Scripts\python.exe"
    if (Test-Path $serverPy) {
        # WHERE pytest runs decides whether half this suite means anything. The
        # 18 tests that EXECUTE the generated remote scripts (every swap script,
        # the ffmpeg unpack, its checksum gate) are `needs_bash`, and they behave
        # three different ways (measured 2026-08-10):
        #   pytest from PowerShell, no bash      -> 18 SKIP, silently
        #   pytest from PowerShell, bash on PATH -> 5 FALSE FAILURES: the harness
        #       prepends its stub dir with os.pathsep (';'), and the bash that
        #       inherits that Windows-style PATH resolves `chown` to MSYS's real
        #       one instead of the stub -> "chown: invalid user: 'root:root'"
        #   pytest INSIDE a bash login shell     -> 214 pass, 1 skip. Correct.
        # So invoke it through bash when there is one. Git's own bash, derived
        # from git.exe (Git\cmd\git.exe -> Git\bin\bash.exe), NOT whatever `bash`
        # resolves to on PATH: on a machine with WSL that is System32\bash.exe,
        # whose filesystem view makes every path here wrong.
        # Two candidates, because WHERE git.exe resolves from depends on who
        # started this shell: Git\cmd\git.exe from a normal window, but
        # Git\mingw64\bin\git.exe when PowerShell was launched from a Git Bash
        # (measured 2026-08-11). Only the first was tried, so in the second
        # case the 18 tests silently went back to SKIPping.
        $bashExe = ""
        $gitCmd = (Get-Command git -ErrorAction SilentlyContinue).Source
        if ($gitCmd) {
            $gitBase = Split-Path -Parent (Split-Path -Parent $gitCmd)
            foreach ($candidate in @((Join-Path $gitBase "bin\bash.exe"),
                                     (Join-Path (Split-Path -Parent $gitBase) "bin\bash.exe"))) {
                if ($candidate -and (Test-Path $candidate)) { $bashExe = $candidate; break }
            }
        }
        if ($bashExe) {
            $bashServer = ConvertTo-BashPath (Join-Path $RepoRoot "server")
            $bashPy = ConvertTo-BashPath $serverPy
            & $bashExe -lc "cd '$bashServer' && '$bashPy' -m pytest tests -q"
            $testRc = $LASTEXITCODE
        }
        else {
            # Not fatal, but the gate is now the string-assertion half only, and
            # that must not read as a full pass.
            Write-Host "[ship] WARNING: no Git bash found -- the tests that EXECUTE the generated remote scripts will SKIP, not pass" -ForegroundColor Yellow
            Push-Location (Join-Path $RepoRoot "server")
            & $serverPy -m pytest tests -q
            $testRc = $LASTEXITCODE
            Pop-Location
        }
        if ($testRc -ne 0) {
            Write-Fail "server tests exited $testRc -- nothing has been deployed or published"
            exit 1
        }
    }
    else {
        # Not fatal: a machine without the dashboard venv can still ship. Said
        # out loud, because "no tests ran" must never look like "tests passed".
        Write-Step "NOTE: no dashboard venv at $serverPy -- server tests SKIPPED, not passed"
    }

    # onboarding/ guards the OTHER artifact step 2 publishes -- onboard.exe --
    # and holds the ONLY check on the fourth copy of the installer version
    # (build_onboard_macos.spec's CFBundleShortVersionString). release.ps1 and
    # build_editor_package.ps1 both check the other three and predate that one,
    # so a 1.0.19 -> 1.0.20 bump that missed the .spec would publish an
    # onboard.exe whose bundle disagrees with itself; only this suite noticed
    # on 2026-08-10. System python, no venv, ~0.3s.
    Write-Step "--- step 0b: onboarding tests (they guard onboard.exe) ---"
    # RESOLVE the interpreter, and never read a stale exit code (SHIP-5,
    # 2026-08-14). `& python` with no python on PATH is a NON-TERMINATING
    # CommandNotFoundException under $ErrorActionPreference='Continue', and
    # PowerShell only sets $LASTEXITCODE when a native process actually ran --
    # so $obRc was whatever the server suite left behind (0), and a suite that
    # never executed gated the ship as a pass. Same class as OPS-6.
    $obPython = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (-not $obPython) {
        Write-Fail "no 'python' on PATH -- the onboarding suite cannot run, and it is the ONLY check on build_onboard_macos.spec's copy of the installer version"
        Write-Step "install python (or re-run with -SkipTests if you accept shipping without that check)"
        exit 1
    }
    Push-Location (Join-Path $RepoRoot "onboarding")
    $global:LASTEXITCODE = 9999
    & $obPython -m pytest tests -q
    $obRc = $LASTEXITCODE
    Pop-Location
    if ($obRc -ne 0) {
        Write-Fail "onboarding tests exited $obRc -- nothing has been deployed or published"
        exit 1
    }
}
else {
    Write-Step "server + onboarding tests skipped (-SkipTests)"
}

# --- 1. dashboard -----------------------------------------------------------
Write-Host ""
Write-Step "--- step 1: deploy dashboard ---"
python server\install_dashboard_app.py
if ($LASTEXITCODE -ne 0) {
    Write-Fail "install_dashboard_app.py exited $LASTEXITCODE -- stopping"
    exit 1
}
# POLL, don't peek (OPS-10). This was a fixed 8 s sleep plus a single check,
# and the container legitimately takes longer than that to answer: the venv
# revalidation in run.sh, a cold pool, a container that had to pull. Compose
# allows a 120 s start_period for exactly this reason -- so a one-shot read at
# 8 s turned a good deploy into "investigate before continuing" and aborted
# before the companion was ever published. First good answer wins; the ceiling
# is only reached when something is actually wrong.
$deadline = (Get-Date).AddSeconds(90)
$live = ""
$reported = $false
while ($true) {
    Start-Sleep -Seconds 3
    try {
        $health = Invoke-CurlWithToken -Uri "http://192.168.0.102:8480/api/v1/health" `
            -Token $env:DASH_REPORT_TOKEN | ConvertFrom-Json
        $live = "$($health.version)"
    }
    catch { $live = "" }
    if ($live -eq $DashVersion) { break }
    if ((Get-Date) -ge $deadline) { break }
    if (-not $reported) {
        Write-Step "waiting for the dashboard to come back up (up to 90s)..."
        $reported = $true
    }
}
if ($live -eq $DashVersion) {
    Write-Step "dashboard is LIVE at v$live"
}
else {
    Write-Fail "dashboard /health says '$live', repo says '$DashVersion' after 90s -- investigate before continuing"
    exit 1
}
if ($DashboardOnly) {
    Write-Step "done (-DashboardOnly)"
    exit 0
}

# --- 2a. build the companion THROUGH release.ps1 ----------------------------
# OPS-1 (2026-08-11): this step used to be build_editor_package.ps1
# -RebuildExe, which runs PyInstaller and NOTHING ELSE -- so THE ship command
# built and published a companion to the whole fleet as CURRENT with the
# companion suite never executed, and stamped the manifest tests_run=false to
# say so. release.ps1 is the tested-build path: version parity across the five
# copies of the two version numbers, `pip install -e .[dev,tray]` (without the
# tray extra, build.spec's import probe silently drops pystray and the editor
# gets a companion with no tray icon), the companion AND dashboard suites with
# CCSYNC_REQUIRE_RCLONE=1, PyInstaller, and the provenance manifest that
# windows_upgrade.ps1 and check_deploy_drift.ps1 read afterwards.
Write-Host ""
Write-Step "--- step 2a: build companion (release.ps1: parity, editable install, companion + dashboard suites, PyInstaller, manifest) ---"
$releaseArgs = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "tools\release.ps1")
if ($AllowDirty) { $releaseArgs += "-AllowDirty" }
& powershell @releaseArgs
if ($LASTEXITCODE -ne 0) {
    Write-Fail "release.ps1 exited $LASTEXITCODE -- nothing has been published; the dashboard deploy in step 1 stands"
    exit 1
}

# --- 2b. package + publish the artifact release.ps1 just built --------------
# NO -RebuildExe: the exe (and its manifest) came out of step 2a, and
# rebuilding here would replace a tested build with an untested one and restamp
# the manifest tests_run=false. -RebuildOnboard still runs, and must run AFTER
# the companion build, because onboard.exe bundles the companion exe.
Write-Host ""
Write-Step "--- step 2b: package + publish (password prompt is your DASHBOARD login) ---"
& powershell -NoProfile -ExecutionPolicy Bypass -File "installer\build_editor_package.ps1" `
    -RebuildOnboard -Publish -MakeCurrent
if ($LASTEXITCODE -ne 0) {
    Write-Fail "build_editor_package.ps1 exited $LASTEXITCODE -- stopping before the local upgrade"
    exit 1
}

# --- 2c. is the macOS companion channel keeping up? (advisory) --------------
# Nothing in this script can build it -- PyInstaller does not cross-compile, so
# the Mac binary comes from tools/release_macos.sh run on the Mac. Without this
# line the macOS channel goes stale in silence while every Windows ship reports
# success. Advisory ONLY: it never gates step 3 and never changes the exit code.
#
# GET, not HEAD: the route is registered GET-only and answers HEAD with 405
# (measured against the live dashboard, 2026-08-03 -- `allow: GET`). So ask
# for the first BYTE instead: FileResponse honours Range (206 + content-range,
# also measured), the X-CCSync-* headers ride along on the partial response,
# and a server that ignored the Range would at worst send a body we throw at
# NUL under a 15 s cap. -D - dumps the headers to stdout; the token still
# never touches curl's command line.
$macHeaders = ""
try {
    $macHeaders = Invoke-CurlWithToken `
        -Uri "http://192.168.0.102:8480/api/v1/companion/package/macos/current" `
        -Token $env:DASH_REPORT_TOKEN `
        -ExtraArgs @("-D", "-", "-o", "NUL", "-r", "0-0", "--max-time", "15")
}
catch {
    $macHeaders = ""
}
$macHeaderText = ($macHeaders | Out-String)
$macVersion = ""
$mMac = [regex]::Match($macHeaderText, '(?im)^X-CCSync-Version:\s*(\S+)\s*$')
if ($mMac.Success) { $macVersion = $mMac.Groups[1].Value }
if ($macVersion) {
    if ($macVersion -eq $CompanionVersion) {
        Write-Step "macos companion channel is at v$macVersion -- level with this repo"
    }
    else {
        # --make-current on BOTH (OPS-9): --publish alone uploads the build
        # STAGED (MC=0), so Mac editors keep downloading the old zip and
        # whoever ran it has no reason to think otherwise.
        Write-Host "[ship] WARNING: macos companion channel at v$macVersion (repo v$CompanionVersion) -- ON THE MAC: git pull && ./tools/release_macos.sh --publish --make-current  (and ./tools/build_onboard_macos.sh --publish --make-current for the wizard)" -ForegroundColor Yellow
    }
}
elseif ($macHeaderText -match '\s404\s') {
    Write-Step "NOTE: no macos companion package published yet -- Mac editors have nothing to install. ON THE MAC: git pull && ./tools/release_macos.sh --publish --make-current"
}
else {
    Write-Step "NOTE: could not read the macos companion channel -- not checked (this is advisory only)"
}

if ($SkipLocalUpgrade) {
    Write-Step "done (-SkipLocalUpgrade). Editors get the tray offer; this machine stays as-is."
    exit 0
}

# --- 3. upgrade this machine + verify --------------------------------------
Write-Host ""
Write-Step "--- step 3: upgrade this machine ---"
& powershell -NoProfile -ExecutionPolicy Bypass -File "installer\windows_upgrade.ps1" `
    -CompanionExe "companion\dist\ccsync-companion.exe"
if ($LASTEXITCODE -ne 0) {
    # A HARD STOP, and the message has to say what state the fleet is in
    # (OPS-4): v$CompanionVersion is already published and CURRENT, so the
    # editors take it while THIS machine is still running the previous build --
    # the "verified against a build nobody was running" state the drift check
    # exists to prevent.
    Write-Fail "windows_upgrade.ps1 exited $LASTEXITCODE -- v$CompanionVersion is PUBLISHED and CURRENT for the fleet but is NOT installed here"
    Write-Step "close whatever holds the exe (AV scan, Explorer preview) and re-run: installer\windows_upgrade.ps1 -CompanionExe companion\dist\ccsync-companion.exe"
    exit 1
}
# READ the doctor, don't just run it (SHIP-2, 2026-08-14). check_deploy_drift
# exits 0 by design -- "the report is the output; the exit code says only that
# the check itself ran" -- so ship printed "ship complete" over a VERDICT
# saying this machine is not running what the fleet was just offered. Only the
# LOCAL-state drift lines gate: the macos-lagging and other-machines-behind
# lines are advisory by design and fire on a perfectly good Windows ship.
# Colour is lost by capturing a child powershell's output; the text is not.
$driftLines = @(& powershell -NoProfile -ExecutionPolicy Bypass -File "tools\check_deploy_drift.ps1" 2>&1 |
    ForEach-Object { $line = "$_"; Write-Host $line; $line })
$localDrift = @($driftLines | Where-Object {
    $_ -match '^\s*DRIFT\s+(installed companion is v|no ccsync-companion process is running|the running process is |the exe on disk is NEWER)'
})
Write-Host ""
if ($localDrift.Count -gt 0) {
    Write-Fail "the drift doctor says THIS machine is not running v$CompanionVersion -- which is already PUBLISHED and CURRENT for the fleet:"
    foreach ($d in $localDrift) { Write-Host "        $($d.Trim())" -ForegroundColor Yellow }
    Write-Step "the fleet half of this ship stands; fix this machine before verifying anything against it (docs\RELEASE.md)"
    exit 1
}
Write-Step "ship complete. Editors' trays will offer v$CompanionVersion on their next report."
exit 0
