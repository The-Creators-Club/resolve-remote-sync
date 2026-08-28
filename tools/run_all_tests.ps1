#requires -Version 5.1
<#
.SYNOPSIS
    Run every test suite in the repo with the interpreter each one needs.

.DESCRIPTION
    One command instead of ten, because the suites do not share a venv and
    three of them do not even have one: server/ borrows the dashboard's,
    onboarding/ and broll/indexer run on the system python, and broll/web
    still borrows the venv of the old standalone broll-platform checkout
    (the in-repo copy has none yet -- create one and update $Suites when
    that repo finally goes away).

    Every suite runs even when an earlier one fails; the summary table and
    the exit code (count of failed suites) come at the end. Run pytest via
    `python -m pytest` FROM the component dir so the in-repo package wins
    over any stale editable install pointing at the old checkout.

    Two things here are not incidental (OPS-6, 2026-08-11):

      - server/ runs THROUGH GIT'S BASH, exactly as tools\ship.ps1 does. 18 of
        its tests EXECUTE the generated remote scripts under a stub sudo, and
        where pytest is launched from decides what they mean: from PowerShell
        with no bash they SKIP SILENTLY and the table prints PASS. This
        wrapper used to do exactly that.
      - music/web is in the list. It was missing entirely, so
        test_mounted_prefix.py -- which pins the document-relative URLs the
        /music mount depends on, and which CLAUDE.md calls load-bearing --
        never ran here.
#>
$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent $PSScriptRoot

# E:\Projects\x -> /e/Projects/x. MSYS's own drive mapping, not WSL's /mnt/e
# (copied from ship.ps1, and for the same reason).
function ConvertTo-BashPath {
    param([string]$Path)
    $p = $Path -replace '\\', '/'
    if ($p -match '^([A-Za-z]):(.*)$') { return "/" + $Matches[1].ToLower() + $Matches[2] }
    return $p
}

# Git's own bash, derived from git.exe (Git\cmd\git.exe -> Git\bin\bash.exe),
# NOT whatever `bash` resolves to on PATH: on a machine with WSL that is
# System32\bash.exe, whose filesystem view makes every path here wrong. And
# NOT the bash inherited via PATH from PowerShell either -- the server harness
# prepends its stub dir with os.pathsep (';'), and a bash that inherits that
# Windows-style PATH resolves `chown` to MSYS's real one, which fails 5 tests
# falsely ("chown: invalid user: 'root:root'"). Measured 2026-08-10.
# Two candidates: git.exe resolves from Git\cmd in a normal window but from
# Git\mingw64\bin when PowerShell was launched out of a Git Bash (measured
# 2026-08-11) -- and only the second one's grandparent is the Git root.
$bashExe = ""
$gitCmd = (Get-Command git -ErrorAction SilentlyContinue).Source
if ($gitCmd) {
    $gitBase = Split-Path -Parent (Split-Path -Parent $gitCmd)
    foreach ($candidate in @((Join-Path $gitBase "bin\bash.exe"),
                             (Join-Path (Split-Path -Parent $gitBase) "bin\bash.exe"))) {
        if ($candidate -and (Test-Path $candidate)) { $bashExe = $candidate; break }
    }
}

$Suites = @(
    @{ Name = "companion";     Dir = "$repo\companion";     Py = "$repo\companion\.venv\Scripts\python.exe" },
    @{ Name = "dashboard";     Dir = "$repo\dashboard";     Py = "$repo\dashboard\.venv\Scripts\python.exe" },
    @{ Name = "server";        Dir = "$repo\server";        Py = "$repo\dashboard\.venv\Scripts\python.exe"; Bash = $true },
    @{ Name = "onboarding";    Dir = "$repo\onboarding";    Py = "python" },
    @{ Name = "bench";         Dir = "$repo\bench";         Py = "$repo\bench\.venv\Scripts\python.exe" },
    # broll/web has no venv of its own and still borrows the old standalone
    # broll-platform checkout's. That path exists on ONE machine (this one), so
    # since 2026-08-17 it falls back to the dashboard venv, which carries the
    # same deps -- otherwise this suite reads "NO INTERPRETER" on every other
    # clone, which is a silent skip of test_mounted_prefix.py.
    @{ Name = "broll/web";     Dir = "$repo\broll\web";     Py = "E:\Projects\broll-platform\web\.venv\Scripts\python.exe";
                                                            Fallback = "$repo\dashboard\.venv\Scripts\python.exe" },
    @{ Name = "broll/indexer"; Dir = "$repo\broll\indexer"; Py = "python" },
    @{ Name = "music/web";     Dir = "$repo\music\web";     Py = "$repo\music\web\.venv\Scripts\python.exe" },
    # music/indexer runs on the SYSTEM python, like broll/indexer: the real
    # pipeline needs the GPU and torch, but its suite is the path/config half
    # and is stdlib-only on purpose. It was the last tests/ directory in the
    # repo this wrapper did not run (2026-08-17 integration pass) -- and
    # test_config_paths.py is what stops the indexer writing a customer's
    # library path back into the shipped config.
    @{ Name = "music/indexer"; Dir = "$repo\music\indexer"; Py = "python" },
    # ytdl/web has no venv of its own; its suite runs under the dashboard venv
    # (the deployed reality: it is mounted in-process by the dashboard).
    # YTDL-14 (2026-08-11): the suite existed, passed, and was wired into
    # nothing -- the next regression would have shipped silently.
    @{ Name = "ytdl/web";      Dir = "$repo\ytdl\web";      Py = "$repo\dashboard\.venv\Scripts\python.exe" },
    # tools/ has no venv either -- it is stdlib-only by design (gen_notices.py
    # and check_licenses.py must run under ANY interpreter on this machine,
    # because the thing they audit is the dependency list). The dashboard venv
    # is the one with pytest and `packaging`, which check_licenses uses to
    # evaluate the lockfiles' platform markers (2026-08-17,
    # COMMERCIAL_READINESS.md item 13).
    @{ Name = "tools";         Dir = "$repo\tools";         Py = "$repo\dashboard\.venv\Scripts\python.exe" }
)

# A suite whose Py is the bare string "python" was never existence-checked
# (SHIP-5, 2026-08-14): the check below skipped exactly the two system-python
# suites, and `& python` with no python on PATH is a NON-TERMINATING
# CommandNotFoundException under $ErrorActionPreference='Continue'. PowerShell
# only sets $LASTEXITCODE when a native process actually RAN, so the table read
# the value the PREVIOUS suite left there and printed PASS for a suite that
# never executed -- OPS-6's defect, one line further down the same file.
# Resolve it once, here, so "python" is a path like every other Py.
$SystemPython = (Get-Command python -ErrorAction SilentlyContinue).Source

$results = @()
foreach ($s in $Suites) {
    Write-Host "`n=== $($s.Name) ===" -ForegroundColor Cyan
    $py = $s.Py
    if ($py -eq "python") { $py = $SystemPython }
    if (-not $py) {
        $results += @{ Name = $s.Name; Outcome = "NO INTERPRETER (no 'python' on PATH)" }
        continue
    }
    if (-not (Test-Path $py) -and $s.Fallback -and (Test-Path $s.Fallback)) {
        Write-Host "  (no $py -- falling back to $($s.Fallback))" -ForegroundColor Yellow
        $py = $s.Fallback
    }
    if (-not (Test-Path $py)) {
        $results += @{ Name = $s.Name; Outcome = "NO INTERPRETER ($py)" }
        continue
    }
    # 9999, never 0: a command that fails to start leaves $LASTEXITCODE alone,
    # and the value it would inherit is the previous suite's success (SHIP-5).
    $suiteOut = @()
    if ($s.Bash -and $bashExe) {
        $global:LASTEXITCODE = 9999
        & $bashExe -lc "cd '$(ConvertTo-BashPath $s.Dir)' && '$(ConvertTo-BashPath $py)' -m pytest tests -q" 2>&1 |
            Tee-Object -Variable suiteOut
        $outcome = $(if ($LASTEXITCODE -eq 0) { "PASS" } else { "FAIL (exit $LASTEXITCODE)" })
    }
    else {
        if ($s.Bash) {
            Write-Host "WARNING: no Git bash found -- the tests that EXECUTE the generated remote scripts will SKIP, not pass" -ForegroundColor Yellow
        }
        Push-Location $s.Dir
        $global:LASTEXITCODE = 9999
        & $py -m pytest tests -q 2>&1 | Tee-Object -Variable suiteOut
        $outcome = $(if ($LASTEXITCODE -ne 0) { "FAIL (exit $LASTEXITCODE)" }
                     elseif ($s.Bash) { "PASS* (no Git bash: the remote-script tests SKIPPED, not passed)" }
                     else { "PASS" })
        Pop-Location
    }
    # A SKIP IS NOT A PASS, and pytest reports one the same quiet way whether
    # it means "not applicable on this OS" or "the numeric gate on the
    # exported CLAP artefact only ever runs on one machine in the world"
    # (product-surface-7, 2026-08-21: companion/tests/test_music_clap_sidecar.py
    # is skipif'd on a hardcoded E:\ venv and P:\Assets\Music). Surfacing the
    # count in the summary is what makes "this suite is quietly smaller here
    # than on the base rig" visible at all.
    $skipped = 0
    $m = [regex]::Match(($suiteOut -join "`n"), '(\d+)\s+skipped')
    if ($m.Success) { $skipped = [int]$m.Groups[1].Value }
    if ($skipped -gt 0 -and $outcome -like "PASS*") { $outcome = "$outcome  [$skipped skipped]" }
    $results += @{ Name = $s.Name; Outcome = $outcome }
}

Write-Host "`n=== installer (Pester-less table tests) ===" -ForegroundColor Cyan
$global:LASTEXITCODE = 9999
powershell -NoProfile -ExecutionPolicy Bypass -File "$repo\installer\tests\Test-DriveMapParser.ps1"
$driveMapExit = $LASTEXITCODE
# windows_upgrade.ps1's licence-version compare (CR-22). Its own file rather
# than more cases in the drive-map one: they slice out of different scripts,
# and both are named in the summary as one "installer" row so a failure in
# either still fails the suite.
$global:LASTEXITCODE = 9999
powershell -NoProfile -ExecutionPolicy Bypass -File "$repo\installer\tests\Test-LicenceGate.ps1"
$licenceExit = $LASTEXITCODE
# The two renames that decide whether a build which will not start leaves the
# machine on the previous one or with no companion at all (REL-12, 2026-08-28).
$global:LASTEXITCODE = 9999
powershell -NoProfile -ExecutionPolicy Bypass -File "$repo\installer\tests\Test-PrevRollback.ps1"
$installerExit = @($driveMapExit, $licenceExit, $LASTEXITCODE) |
    Where-Object { $_ -ne 0 } | Select-Object -First 1
if ($null -eq $installerExit) { $installerExit = 0 }
$results += @{ Name = "installer"; Outcome = $(if ($installerExit -eq 0) { "PASS" } else { "FAIL (exit $installerExit)" }) }

# The macOS half of the same two checks -- the site-manifest reader, the
# canonical_prefix -> drive-letter rule and the pinned-download verifier
# (2026-08-17, COMMERCIAL_READINESS.md items 11 and 13). Pure string helpers
# sliced out of macos_bootstrap.sh, so they run here and not only on a Mac.
# Same $bashExe as the server suite, for the same reason.
Write-Host "`n=== installer/macos (bash table tests) ===" -ForegroundColor Cyan
if (-not $bashExe) {
    Write-Host "  SKIP: no Git bash found" -ForegroundColor Yellow
    $results += @{ Name = "installer/macos"; Outcome = "SKIP (no bash)" }
}
else {
    $global:LASTEXITCODE = 9999
    & $bashExe -lc "cd '$($repo -replace '\\','/')' && bash installer/tests/test_macos_site_values.sh"
    $results += @{ Name = "installer/macos"; Outcome = $(if ($LASTEXITCODE -eq 0) { "PASS" } else { "FAIL (exit $LASTEXITCODE)" }) }
}

Write-Host ""
Write-Host ("-" * 46)
foreach ($r in $results) { Write-Host ("{0,-16} {1}" -f $r.Name, $r.Outcome) }
# "PASS*" is a pass with a caveat printed beside it (see the server suite
# above); it must not read as a failure, and must not read as a clean pass
# either.
$failed = @($results | Where-Object { $_.Outcome -notlike "PASS*" }).Count
Write-Host ("-" * 46)
Write-Host ("{0} of {1} suites failed" -f $failed, $results.Count)
$anySkips = @($results | Where-Object { $_.Outcome -like "*skipped*" }).Count
if ($anySkips -gt 0) {
    # Named, not just counted: some of those skips are gates pinned to one
    # machine's filesystem (product-surface-7). `-rs` on the suite in question
    # says which.
    Write-Host "NOTE: some suites SKIPPED tests -- a skip is not a pass. Re-run that suite with -rs to see which, and why." -ForegroundColor Yellow
}
exit $failed
