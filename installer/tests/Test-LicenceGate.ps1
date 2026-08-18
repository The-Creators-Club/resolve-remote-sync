<#
.SYNOPSIS
    Table tests for windows_upgrade.ps1's Get-EulaVersion and
    Test-VersionAtLeast -- the two pure helpers step 6 decides on.

.DESCRIPTION
    Step 6 launches the setup wizard when this machine's licence acceptance
    is missing or older than the one the package brings (KNOWN_BUGS CR-22).
    Both halves of that decision are failure-shaped:

      * Say "current" when it is NOT and the editor is left with a companion
        that comes up and refuses to sync, which is the bug this step exists
        to fix.
      * Say "stale" when it is NOT and every editor is thrown back through a
        ten-minute wizard on every upgrade, forever -- which is worse,
        because it trains them to click past it.

    The second is why an UNPARSEABLE or ABSENT package version must never
    read as newer: a package built before EULA.md shipped beside it (every
    package before 2026-08-18) gives "" here.

    Test-VersionAtLeast mirrors companion/eula.py's version_at_least, and the
    numeric-vs-string cases are the point of it: as strings "1.10" sorts
    BELOW "1.9", so a tenth revision of the document would read as older than
    its predecessor and silently stop asking anyone to re-accept.

    Run:  powershell -NoProfile -ExecutionPolicy Bypass -File installer\tests\Test-LicenceGate.ps1
    Exits 1 on any failure.
#>
$ErrorActionPreference = "Stop"

# Same slicing trick as Test-DriveMapParser.ps1: pull the two pure functions
# out of the upgrade script so they run with no machine in any state.
$UpgradePath = Join-Path (Split-Path -Parent $PSScriptRoot) "windows_upgrade.ps1"
$src = Get-Content -Raw $UpgradePath
$start = $src.IndexOf('function Get-EulaVersion')
$end = $src.IndexOf('if (-not (Test-Path -LiteralPath $acceptancePath))')
if ($start -lt 0 -or $end -lt 0 -or $end -le $start) {
    Write-Host "FAIL: could not slice the licence helpers out of $UpgradePath -- did a function get renamed?" -ForegroundColor Red
    exit 1
}
Invoke-Expression $src.Substring($start, $end - $start)

$failures = 0
function Check {
    param([string]$What, $Expected, $Actual)
    if ($Expected -eq $Actual) {
        Write-Host ("  ok   {0}" -f $What)
    }
    else {
        $script:failures++
        Write-Host ("  FAIL {0}: expected [{1}], got [{2}]" -f $What, $Expected, $Actual) -ForegroundColor Red
    }
}

# --- Get-EulaVersion --------------------------------------------------------
Write-Host "`n--- Get-EulaVersion ---"

$tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("ccsync-eula-test-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tmp | Out-Null
try {
    $marked = Join-Path $tmp "EULA.md"
    Set-Content -LiteralPath $marked -Encoding utf8 -Value @(
        "# End User Licence Agreement",
        "<!-- EULA-VERSION: 1.0 -->",
        "",
        "Body text."
    )
    Check "reads the marker" "1.0" (Get-EulaVersion $marked)

    # The real document's own spelling, straight out of the shipped asset --
    # a marker this cannot parse is a step 6 that never fires.
    $shipped = Join-Path (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) `
                         "companion\src\ccsync_companion\assets\EULA.md"
    if (Test-Path -LiteralPath $shipped) {
        $v = Get-EulaVersion $shipped
        if ($v) { Write-Host ("  ok   parses the SHIPPED assets/EULA.md (v{0})" -f $v) }
        else {
            $failures++
            Write-Host "  FAIL could not parse the marker in the shipped assets/EULA.md" -ForegroundColor Red
        }
    }

    $spaced = Join-Path $tmp "spaced.md"
    Set-Content -LiteralPath $spaced -Encoding utf8 -Value "<!--   EULA-VERSION:   2.11   -->"
    Check "tolerates whitespace in the marker" "2.11" (Get-EulaVersion $spaced)

    $none = Join-Path $tmp "none.md"
    Set-Content -LiteralPath $none -Encoding utf8 -Value "no marker here"
    Check "no marker is blank, not an error" "" (Get-EulaVersion $none)

    Check "a missing file is blank, not an error" "" (Get-EulaVersion (Join-Path $tmp "gone.md"))
}
finally {
    Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue
}

# --- Test-VersionAtLeast ----------------------------------------------------
Write-Host "`n--- Test-VersionAtLeast ---"

$cases = @(
    @{ Have = "1.0";  Want = "1.0";  Expect = $true;  Why = "equal is current" },
    @{ Have = "1.1";  Want = "1.0";  Expect = $true;  Why = "newer is current" },
    @{ Have = "1.0";  Want = "1.1";  Expect = $false; Why = "older is stale" },
    # THE STRING-SORT TRAP. "1.10" < "1.9" as text; as versions it is newer.
    @{ Have = "1.10"; Want = "1.9";  Expect = $true;  Why = "1.10 is newer than 1.9" },
    @{ Have = "1.9";  Want = "1.10"; Expect = $false; Why = "1.9 is older than 1.10" },
    # Zero-padded to the longer: "1.0" and "1.0.0" are the same document.
    @{ Have = "1.0";    Want = "1.0.0"; Expect = $true; Why = "1.0 == 1.0.0" },
    @{ Have = "1.0.0";  Want = "1.0";   Expect = $true; Why = "1.0.0 == 1.0" },
    @{ Have = "1.0.1";  Want = "1.0";   Expect = $true; Why = "a third component can be newer" },
    @{ Have = "1.0";    Want = "1.0.1"; Expect = $false; Why = "...and older" },
    @{ Have = "2";      Want = "1.9";   Expect = $true; Why = "a bare major beats a minor" },
    # Unparseable components count as 0 rather than throwing -- eula.py's
    # version_tuple contract. "1.0-beta" is the 1.0 document.
    @{ Have = "1.0-beta"; Want = "1.0"; Expect = $true;  Why = "a suffix does not make it older" },
    @{ Have = "";         Want = "1.0"; Expect = $false; Why = "no recorded version is stale" },
    @{ Have = "1.0";      Want = "";    Expect = $true;  Why = "no PACKAGE version never re-asks" }
)
foreach ($c in $cases) {
    Check ("[{0}] >= [{1}] -- {2}" -f $c.Have, $c.Want, $c.Why) $c.Expect `
          (Test-VersionAtLeast $c.Have $c.Want)
}

Write-Host ""
if ($failures -gt 0) {
    Write-Host ("{0} FAILURE(S)" -f $failures) -ForegroundColor Red
    exit 1
}
Write-Host "all licence-gate cases passed" -ForegroundColor Green
exit 0
