#requires -Version 5.1
<#
.SYNOPSIS
    Run every test suite in the repo with the interpreter each one needs.

.DESCRIPTION
    One command instead of nine, because the suites do not share a venv and
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
    @{ Name = "broll/web";     Dir = "$repo\broll\web";     Py = "E:\Projects\broll-platform\web\.venv\Scripts\python.exe" },
    @{ Name = "broll/indexer"; Dir = "$repo\broll\indexer"; Py = "python" },
    @{ Name = "music/web";     Dir = "$repo\music\web";     Py = "$repo\music\web\.venv\Scripts\python.exe" },
    # ytdl/web has no venv of its own; its suite runs under the dashboard venv
    # (the deployed reality: it is mounted in-process by the dashboard).
    # YTDL-14 (2026-08-11): the suite existed, passed, and was wired into
    # nothing -- the next regression would have shipped silently.
    @{ Name = "ytdl/web";      Dir = "$repo\ytdl\web";      Py = "$repo\dashboard\.venv\Scripts\python.exe" }
)

$results = @()
foreach ($s in $Suites) {
    Write-Host "`n=== $($s.Name) ===" -ForegroundColor Cyan
    if (-not (Test-Path $s.Py) -and $s.Py -ne "python") {
        $results += @{ Name = $s.Name; Outcome = "NO INTERPRETER ($($s.Py))" }
        continue
    }
    if ($s.Bash -and $bashExe) {
        & $bashExe -lc "cd '$(ConvertTo-BashPath $s.Dir)' && '$(ConvertTo-BashPath $s.Py)' -m pytest tests -q"
        $outcome = $(if ($LASTEXITCODE -eq 0) { "PASS" } else { "FAIL (exit $LASTEXITCODE)" })
    }
    else {
        if ($s.Bash) {
            Write-Host "WARNING: no Git bash found -- the tests that EXECUTE the generated remote scripts will SKIP, not pass" -ForegroundColor Yellow
        }
        Push-Location $s.Dir
        & $s.Py -m pytest tests -q
        $outcome = $(if ($LASTEXITCODE -ne 0) { "FAIL (exit $LASTEXITCODE)" }
                     elseif ($s.Bash) { "PASS* (no Git bash: the remote-script tests SKIPPED, not passed)" }
                     else { "PASS" })
        Pop-Location
    }
    $results += @{ Name = $s.Name; Outcome = $outcome }
}

Write-Host "`n=== installer (Pester-less table tests) ===" -ForegroundColor Cyan
powershell -NoProfile -ExecutionPolicy Bypass -File "$repo\installer\tests\Test-DriveMapParser.ps1"
$results += @{ Name = "installer"; Outcome = $(if ($LASTEXITCODE -eq 0) { "PASS" } else { "FAIL (exit $LASTEXITCODE)" }) }

Write-Host ""
Write-Host ("-" * 46)
foreach ($r in $results) { Write-Host ("{0,-16} {1}" -f $r.Name, $r.Outcome) }
# "PASS*" is a pass with a caveat printed beside it (see the server suite
# above); it must not read as a failure, and must not read as a clean pass
# either.
$failed = @($results | Where-Object { $_.Outcome -notlike "PASS*" }).Count
Write-Host ("-" * 46)
Write-Host ("{0} of {1} suites failed" -f $failed, $results.Count)
exit $failed
