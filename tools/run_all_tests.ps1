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

.PARAMETER Changed
    Run only what the change needs (docs/MODULAR_UPDATES.md A.6, phase M1,
    2026-10-06). tools\select_suites.py reads tools\test_map.toml, prints the
    plan -- the tier (neutral / scoped / dashboard-wide / full), every changed
    file with the area that claimed it, and which suites and test files run --
    and this then runs exactly those, with the same interpreters and the same
    Git Bash rule for server\. Fails closed: no -Base, a base this clone does
    not have, an unmapped file, or a selector that will not run all mean
    every suite. With no -Changed, NOTHING below changes: all 13 suites.

.PARAMETER Base
    The commit(s) to diff against: the one live on the studio dashboard
    (/api/v1/health code.commit, once M0 adds it) and the last full-green
    commit. Several may be given; the older wins (A.4). Only meaningful with
    -Changed.

.EXAMPLE
    tools\run_all_tests.ps1 -Changed -Base 97d4366
#>
param(
    [switch]$Changed,
    [string[]]$Base = @()
)
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
    @{ Name = "broll/web";     Dir = "$repo\broll\web";     Py = "$repo\broll\web\.venv\Scripts\python.exe";
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

# -Changed (MODULAR_UPDATES.md A.6, 2026-10-06). $plan stays $null without
# the flag, and every `if ($plan)` below is then false: the no-flag run is
# the run it always was. With the flag, a plan that cannot be computed is
# ALSO $null -- i.e. every suite, said out loud -- never "nothing to run".
$plan = $null
if ($Base.Count -gt 0 -and -not $Changed) {
    Write-Host "-Base only means something with -Changed (tools\run_all_tests.ps1 -Changed -Base <ref>)" -ForegroundColor Red
    exit 2
}
if ($Changed) {
    # stdlib only, so any interpreter will do; the dashboard venv first
    # because it is the one every other tools\ row already runs under.
    $selPy = "$repo\dashboard\.venv\Scripts\python.exe"
    if (-not (Test-Path $selPy)) { $selPy = $SystemPython }
    $planFile = Join-Path ([System.IO.Path]::GetTempPath()) ("ccsync-plan-" + [guid]::NewGuid().ToString("N") + ".json")
    $selArgs = @("$repo\tools\select_suites.py", "--json-out", $planFile)
    foreach ($b in $Base) { $selArgs += @("--base", $b) }
    Write-Host "`n=== plan (tools\select_suites.py) ===" -ForegroundColor Cyan
    $global:LASTEXITCODE = 9999
    if ($selPy) { & $selPy @selArgs }
    if ($selPy -and $LASTEXITCODE -eq 0 -and (Test-Path $planFile)) {
        $plan = Get-Content -Raw -Encoding UTF8 $planFile | ConvertFrom-Json
        Remove-Item $planFile -ErrorAction SilentlyContinue
    }
    else {
        Write-Host "  the selector did not answer (exit $LASTEXITCODE) -- running EVERY suite" -ForegroundColor Yellow
    }
}

# -> $null (not selected), or the list of pytest targets relative to the
# suite dir: @("tests") for the whole suite, else the selected test files.
function Get-PlanTargets {
    param([string]$Name)
    if (-not $plan) { return ,@("tests") }
    $entry = @($plan.suites | Where-Object { $_.name -eq $Name }) | Select-Object -First 1
    if (-not $entry) { return $null }
    if ($entry.whole) { return ,@("tests") }
    return ,@($entry.tests)
}

$results = @()
$notSelected = @()
foreach ($s in $Suites) {
    $targets = Get-PlanTargets $s.Name
    if ($null -eq $targets) { $notSelected += $s.Name; continue }
    Write-Host "`n=== $($s.Name) ===" -ForegroundColor Cyan
    if ($plan -and $targets[0] -ne "tests") {
        Write-Host "  (selected by the plan: $($targets.Count) test file(s), not the whole suite)" -ForegroundColor DarkGray
    }
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
        $bashTargets = "tests"
        if ($plan -and $targets[0] -ne "tests") { $bashTargets = ($targets | ForEach-Object { "'$_'" }) -join " " }
        $global:LASTEXITCODE = 9999
        & $bashExe -lc "cd '$(ConvertTo-BashPath $s.Dir)' && '$(ConvertTo-BashPath $py)' -m pytest $bashTargets -q" 2>&1 |
            Tee-Object -Variable suiteOut
        $outcome = $(if ($LASTEXITCODE -eq 0) { "PASS" } else { "FAIL (exit $LASTEXITCODE)" })
    }
    else {
        if ($s.Bash) {
            Write-Host "WARNING: no Git bash found -- the tests that EXECUTE the generated remote scripts will SKIP, not pass" -ForegroundColor Yellow
        }
        Push-Location $s.Dir
        $global:LASTEXITCODE = 9999
        & $py -m pytest @targets -q 2>&1 | Tee-Object -Variable suiteOut
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

if ($null -ne (Get-PlanTargets "installer")) {
    Write-Host "`n=== installer (Pester-less table tests) ===" -ForegroundColor Cyan
    # ENUMERATED, never hand-listed (tests-2, 2026-09-11b). This row named its
    # scripts one by one and aggregated exactly those seven exit codes; the eighth
    # (Test-BinDirLeftovers.ps1, added the same afternoon) was in none of them, so
    # the gate the owner runs before a ship never executed it and a local green
    # meant less than it said. .github/workflows/ci.yml has always enumerated the
    # directory -- this does now too, so the row cannot drift again.
    # They are separate files because each slices its helpers out of a different
    # script; they are one "installer" row because a failure in any of them has to
    # fail the suite.
    $installerScripts = @(Get-ChildItem -Path (Join-Path $repo "installer\tests") -Filter "Test-*.ps1" -File |
        Sort-Object Name)
    $installerExit = 0
    if (@($installerScripts).Count -eq 0) {
        Write-Host "  no installer table tests found -- installer\tests is empty or missing" -ForegroundColor Red
        $installerExit = 1
    }
    foreach ($script in $installerScripts) {
        Write-Host "--- $($script.Name)" -ForegroundColor DarkGray
        $global:LASTEXITCODE = 9999
        powershell -NoProfile -ExecutionPolicy Bypass -File $script.FullName
        if ($LASTEXITCODE -ne 0 -and $installerExit -eq 0) { $installerExit = $LASTEXITCODE }
    }
    $results += @{ Name = "installer"; Outcome = $(if ($installerExit -eq 0) { "PASS" } else { "FAIL (exit $installerExit)" }) }
}
else { $notSelected += "installer" }

if ($null -ne (Get-PlanTargets "installer/macos")) {
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
        # bug-ops-4 / ui-onboarding-11 (2026-09-25): EVERY installer\tests\test_*.sh,
        # enumerated like the .ps1 row above. This row named one file, so
        # test_macos_uninstall_profile.sh and test_macos_first_steps.sh were
        # written, passed once on their author's machine, and gated nothing. All
        # run even after a failure (the first non-zero exit is the one reported),
        # and none found is a FAIL: a renamed directory must not read as green.
        $shTests = @(Get-ChildItem -Path (Join-Path $repo "installer\tests") -Filter "test_*.sh" -File -ErrorAction SilentlyContinue | Sort-Object Name)
        $macosExit = 0
        if ($shTests.Count -eq 0) {
            Write-Host "  FAIL: no installer\tests\test_*.sh found" -ForegroundColor Red
            $macosExit = 1
        }
        foreach ($shTest in $shTests) {
            Write-Host "  -- $($shTest.Name)"
            $global:LASTEXITCODE = 9999
            & $bashExe -lc "cd '$($repo -replace '\\','/')' && bash 'installer/tests/$($shTest.Name)'"
            if ($LASTEXITCODE -ne 0 -and $macosExit -eq 0) { $macosExit = $LASTEXITCODE }
        }
        $results += @{ Name = "installer/macos"; Outcome = $(if ($macosExit -eq 0) { "PASS" } else { "FAIL (exit $macosExit)" }) }
    }
}
else { $notSelected += "installer/macos" }

# The full gate's two non-pytest checks (A.1 tier 4), only under -Changed:
# the no-flag run has never run them and does not start now. From the repo
# root, under the dashboard venv, as CLAUDE.md's "part of the gate" says.
if ($plan) {
    foreach ($chk in @($plan.checks)) {
        Write-Host "`n=== $($chk.name) ===" -ForegroundColor Cyan
        $chkPy = "$repo\dashboard\.venv\Scripts\python.exe"
        if (-not (Test-Path $chkPy)) {
            $results += @{ Name = $chk.name; Outcome = "NO INTERPRETER ($chkPy)" }
            continue
        }
        Push-Location $repo
        $global:LASTEXITCODE = 9999
        & $chkPy @($chk.argv)
        $results += @{ Name = $chk.name; Outcome = $(if ($LASTEXITCODE -eq 0) { "PASS" } else { "FAIL (exit $LASTEXITCODE)" }) }
        Pop-Location
    }
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
if ($plan) {
    # Said, not implied: a scoped green is a statement about these suites
    # only, and the nightly full run is what answers for the rest (A.7).
    Write-Host ("gate tier: {0} ({1})" -f $plan.tier, $plan.reason) -ForegroundColor Cyan
    if ($notSelected.Count -gt 0) {
        Write-Host ("not run, not selected by the plan: " + ($notSelected -join ", ")) -ForegroundColor Yellow
    }
}
$anySkips = @($results | Where-Object { $_.Outcome -like "*skipped*" }).Count
if ($anySkips -gt 0) {
    # Named, not just counted: some of those skips are gates pinned to one
    # machine's filesystem (product-surface-7). `-rs` on the suite in question
    # says which.
    Write-Host "NOTE: some suites SKIPPED tests -- a skip is not a pass. Re-run that suite with -rs to see which, and why." -ForegroundColor Yellow
}
exit $failed
