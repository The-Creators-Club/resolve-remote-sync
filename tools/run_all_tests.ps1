#requires -Version 5.1
<#
.SYNOPSIS
    Run every test suite in the repo with the interpreter each one needs.

.DESCRIPTION
    One command instead of eight, because the suites do not share a venv and
    three of them do not even have one: server/ borrows the dashboard's,
    onboarding/ and broll/indexer run on the system python, and broll/web
    still borrows the venv of the old standalone broll-platform checkout
    (the in-repo copy has none yet -- create one and update $Suites when
    that repo finally goes away).

    Every suite runs even when an earlier one fails; the summary table and
    the exit code (count of failed suites) come at the end. Run pytest via
    `python -m pytest` FROM the component dir so the in-repo package wins
    over any stale editable install pointing at the old checkout.
#>
$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent $PSScriptRoot

$Suites = @(
    @{ Name = "companion";     Dir = "$repo\companion";     Py = "$repo\companion\.venv\Scripts\python.exe" },
    @{ Name = "dashboard";     Dir = "$repo\dashboard";     Py = "$repo\dashboard\.venv\Scripts\python.exe" },
    @{ Name = "server";        Dir = "$repo\server";        Py = "$repo\dashboard\.venv\Scripts\python.exe" },
    @{ Name = "onboarding";    Dir = "$repo\onboarding";    Py = "python" },
    @{ Name = "bench";         Dir = "$repo\bench";         Py = "$repo\bench\.venv\Scripts\python.exe" },
    @{ Name = "broll/web";     Dir = "$repo\broll\web";     Py = "E:\Projects\broll-platform\web\.venv\Scripts\python.exe" },
    @{ Name = "broll/indexer"; Dir = "$repo\broll\indexer"; Py = "python" }
)

$results = @()
foreach ($s in $Suites) {
    Write-Host "`n=== $($s.Name) ===" -ForegroundColor Cyan
    if (-not (Test-Path $s.Py) -and $s.Py -ne "python") {
        $results += @{ Name = $s.Name; Outcome = "NO INTERPRETER ($($s.Py))" }
        continue
    }
    Push-Location $s.Dir
    & $s.Py -m pytest tests -q
    $results += @{ Name = $s.Name; Outcome = $(if ($LASTEXITCODE -eq 0) { "PASS" } else { "FAIL (exit $LASTEXITCODE)" }) }
    Pop-Location
}

Write-Host "`n=== installer (Pester-less table tests) ===" -ForegroundColor Cyan
powershell -NoProfile -ExecutionPolicy Bypass -File "$repo\installer\tests\Test-DriveMapParser.ps1"
$results += @{ Name = "installer"; Outcome = $(if ($LASTEXITCODE -eq 0) { "PASS" } else { "FAIL (exit $LASTEXITCODE)" }) }

Write-Host ""
Write-Host ("-" * 46)
foreach ($r in $results) { Write-Host ("{0,-16} {1}" -f $r.Name, $r.Outcome) }
$failed = @($results | Where-Object { $_.Outcome -ne "PASS" }).Count
Write-Host ("-" * 46)
Write-Host ("{0} of {1} suites failed" -f $failed, $results.Count)
exit $failed
