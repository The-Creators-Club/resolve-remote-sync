<#
.SYNOPSIS
    Table tests for windows_bootstrap.ps1's ConvertFrom-CanonicalPrefix and
    ConvertFrom-DriveMapReport, plus a live read of this machine's own tree
    drive mapping.

.DESCRIPTION
    ConvertFrom-DriveMapReport decides whether the tree drive belongs to this
    installer or to somebody else, and the answer gates a destructive teardown
    (`subst <drive> /D` + `net use <drive> /delete /y`). Getting it wrong on
    the base rig -- whose tree drive IS the NAS share every \Projects\... clip
    path in the Resolve database resolves through -- takes the whole tree
    offline (B21, INST-15).

    ConvertFrom-CanonicalPrefix turns the site manifest's `canonical_prefix`
    into the letter every one of those commands is built from (2026-08-17,
    COMMERCIAL_READINESS.md item 11). It has to REFUSE a prefix it cannot
    mount rather than fall back to P:, because a bad fallback mounts the tree
    behind a letter no stored clip path mentions -- and it has to accept a
    letter that is not P:, which is the whole point of the change.

    Both are pure text-in/object-out precisely so they can be checked here
    without a machine in any particular state. The `net use` status column is
    localised and sometimes blank, so the cases below cover OK / Unavailable /
    Disconnected / blank, both mapping styles, other drive letters, a non-P:
    site and a tree name that is not this deployment's.

    Run:  powershell -NoProfile -ExecutionPolicy Bypass -File installer\tests\Test-DriveMapParser.ps1
    Exits 1 on any failure.
#>
$ErrorActionPreference = "Stop"
# Pull just the parsers out of the bootstrap so they can be exercised
# standalone. The slice runs from the FIRST of the two functions to the
# comment that opens Get-DriveMapping (which needs a real machine).
$BootstrapPath = Join-Path (Split-Path -Parent $PSScriptRoot) "windows_bootstrap.ps1"
$src = Get-Content -Raw $BootstrapPath
$start = $src.IndexOf('function ConvertFrom-CanonicalPrefix')
$end = $src.IndexOf('# Reads the CURRENT USER''s DOS device map')
if ($start -lt 0 -or $end -lt 0 -or $end -le $start) {
    Write-Host "FAIL: could not slice the parsers out of $BootstrapPath -- did a function get renamed?" -ForegroundColor Red
    exit 1
}
Invoke-Expression $src.Substring($start, $end - $start)

# --- ConvertFrom-CanonicalPrefix -------------------------------------------
$prefixCases = @(
  @{ n = 'the default prefix';            p = 'P:\';                    want = 'P' }
  @{ n = 'a site that is not on P:';      p = 'W:\';                    want = 'W' }
  @{ n = 'lowercase is normalised';       p = 'q:\';                    want = 'Q' }
  @{ n = 'no trailing separator';         p = 'T:';                     want = 'T' }
  @{ n = 'leading/trailing whitespace';   p = '  R:\  ';                want = 'R' }
  @{ n = 'a deeper prefix still yields the letter'; p = 'S:\Tree\';     want = 'S' }
  @{ n = 'a UNC prefix is refused';       p = '\\nas\Pool\SomeTree';    want = '' }
  @{ n = 'a POSIX prefix is refused';     p = '/volume1/media/Tree';    want = '' }
  @{ n = 'a bare letter is refused';      p = 'P';                      want = '' }
  @{ n = 'a manifest with no value';      p = '';                       want = '' }
  @{ n = 'whitespace only';               p = '   ';                    want = '' }
)
$fail = 0
foreach ($c in $prefixCases) {
  $got = ConvertFrom-CanonicalPrefix -Prefix $c.p
  if ($got -eq $c.want) { Write-Host "  PASS  prefix: $($c.n)" }
  else {
    $fail++
    Write-Host "  FAIL  prefix: $($c.n): got '$got' want '$($c.want)'" -ForegroundColor Red
  }
}

$UNC1 = [char]92 + [char]92 + 'localhost' + [char]92 + 'CCSync_P'
$UNC2 = [char]92 + [char]92 + 'nas' + [char]92 + 'Media'
$UNC3 = [char]92 + [char]92 + '10.0.0.5' + [char]92 + 'pool'
$UNC4 = [char]92 + [char]92 + 'nas' + [char]92 + 'share'
# A second site: drive W:, tree "AcmeVideo", loopback share CCSync_W. Every
# name here is derived from the letter in windows_bootstrap.ps1, so if any of
# them ever goes back to a literal these cases stop matching.
$UNC5 = [char]92 + [char]92 + 'localhost' + [char]92 + 'CCSync_W'

$cases = @(
  @{ n = 'subst mapping'; r = "P:\: => C:\CCSync`r`n"; m = $true; k = 'subst'; t = 'C:\CCSync' }
  @{ n = 'subst with space in path'; r = "P:\: => D:\Video Projects\CCSync`r`n"; m = $true; k = 'subst'; t = 'D:\Video Projects\CCSync' }
  @{ n = 'subst of a tree name that is not this deployment (P:)'; r = "P:\: => E:\AcmeVideo`r`n"; m = $true; k = 'subst'; t = 'E:\AcmeVideo' }
  @{ n = 'other letter subst only'; r = "Q:\: => C:\Other`r`n"; m = $false; k = 'none'; t = '' }
  @{ n = 'net use OK loopback'; r = "Status       Local     Remote                    Network`r`n`r`n-----------`r`nOK           P:        $UNC1      Microsoft Windows Network`r`nThe command completed successfully.`r`n"; m = $true; k = 'netuse'; t = $UNC1 }
  @{ n = 'net use Unavailable NAS'; r = "Unavailable  P:        $UNC2      Microsoft Windows Network`r`n"; m = $true; k = 'netuse'; t = $UNC2 }
  @{ n = 'net use Disconnected'; r = "Disconnected P:        $UNC3       Microsoft Windows Network`r`n"; m = $true; k = 'netuse'; t = $UNC3 }
  @{ n = 'net use blank status'; r = "             P:        $UNC4                Microsoft Windows Network`r`n"; m = $true; k = 'netuse'; t = $UNC4 }
  @{ n = 'net use other letters'; r = "OK           Z:        $UNC4                Microsoft Windows Network`r`n"; m = $false; k = 'none'; t = '' }
  @{ n = 'nothing at all'; r = "There are no entries in the list.`r`n"; m = $false; k = 'none'; t = '' }
  @{ n = 'empty'; r = ""; m = $false; k = 'none'; t = '' }
  @{ n = 'subst wins over a stale net row'; r = "P:\: => C:\CCSync`r`nOK           P:        $UNC4   Net`r`n"; m = $true; k = 'subst'; t = 'C:\CCSync' }
  @{ n = 'lowercase letter row'; r = "OK           p:        $UNC1      Microsoft Windows Network`r`n"; m = $true; k = 'netuse'; t = $UNC1 }
)

foreach ($c in $cases) {
  $res = ConvertFrom-DriveMapReport -Report $c.r -Letter 'P'
  $okm = ($res.Mapped -eq $c.m); $okk = ($res.Kind -eq $c.k); $okt = ($res.Target -eq $c.t)
  if ($okm -and $okk -and $okt) { Write-Host "  PASS  $($c.n)" }
  else {
    $fail++
    Write-Host "  FAIL  $($c.n): got Mapped=$($res.Mapped) Kind=$($res.Kind) Target='$($res.Target)' want Mapped=$($c.m) Kind=$($c.k) Target='$($c.t)'" -ForegroundColor Red
  }
}

# --- the same parser on a site that is NOT on P: ---------------------------
# The letter is a parameter everywhere in windows_bootstrap.ps1 now; these
# pin that the parser follows it, including that a P: row must NOT be picked
# up when the site's tree drive is W: (that is how a foreign mapping would
# get torn down on a machine that has both).
$wCases = @(
  @{ n = 'W: subst of a non-Creators_Club tree'; r = "W:\: => D:\AcmeVideo`r`n"; m = $true; k = 'subst'; t = 'D:\AcmeVideo' }
  @{ n = 'W: our own loopback share'; r = "OK           W:        $UNC5      Microsoft Windows Network`r`n"; m = $true; k = 'netuse'; t = $UNC5 }
  @{ n = 'W: someone else NAS mapping'; r = "Unavailable  W:        $UNC2      Microsoft Windows Network`r`n"; m = $true; k = 'netuse'; t = $UNC2 }
  @{ n = 'W: unmapped while P: is mapped'; r = "P:\: => C:\CCSync`r`nOK           P:        $UNC1   Net`r`n"; m = $false; k = 'none'; t = '' }
  @{ n = 'W: lowercase row'; r = "OK           w:        $UNC5      Microsoft Windows Network`r`n"; m = $true; k = 'netuse'; t = $UNC5 }
)
foreach ($c in $wCases) {
  $res = ConvertFrom-DriveMapReport -Report $c.r -Letter 'W'
  $okm = ($res.Mapped -eq $c.m); $okk = ($res.Kind -eq $c.k); $okt = ($res.Target -eq $c.t)
  if ($okm -and $okk -and $okt) { Write-Host "  PASS  $($c.n)" }
  else {
    $fail++
    Write-Host "  FAIL  $($c.n): got Mapped=$($res.Mapped) Kind=$($res.Kind) Target='$($res.Target)' want Mapped=$($c.m) Kind=$($c.k) Target='$($c.t)'" -ForegroundColor Red
  }
}

# --- no tenant literal may creep back into the derived names ---------------
# windows_bootstrap.ps1 must build the task, Run-entry and share names FROM
# the letter. A literal "CCSync_P" / "CCSync-SubstP" outside a comment or an
# illustrative example means a non-P: site gets a P: share (item 11).
$codeLines = @(Get-Content $BootstrapPath | Where-Object { $_ -notmatch '^\s*#' })
foreach ($literal in @('"CCSync_P"', '"CCSync-SubstP"', '"CCSyncSubstP"')) {
  $hits = @($codeLines | Where-Object { $_ -match [Regex]::Escape($literal) })
  if ($hits.Count -eq 0) { Write-Host "  PASS  no $literal literal in bootstrap code" }
  else {
    $fail++
    Write-Host "  FAIL  $literal is still a literal in windows_bootstrap.ps1: $($hits[0].Trim())" -ForegroundColor Red
  }
}

# --- the WIZARD builds the same names the same way -------------------------
# installer-onboard-tools-3 (2026-08-21): this scan covered the bootstrap
# only, and onboarding/steps.py was found still carrying "CCSync-SubstP",
# "CCSyncSubstP" and \\localhost\CCSync_P as literals -- so on a non-P: site
# the wizard cleaned up a task nobody had registered and left the real one
# behind. The letter-derived helpers (subst_task_name / all_run_values /
# loopback_share_unc) are the only place those strings may be BUILT; the
# module-level P defaults are assignments from those helpers, which is why
# this looks for the quoted literal rather than the substring.
$StepsPath = Join-Path (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) "onboarding\steps.py"
if (-not (Test-Path -LiteralPath $StepsPath)) {
  $fail++
  Write-Host "  FAIL  no onboarding\steps.py at $StepsPath" -ForegroundColor Red
}
else {
  $stepsLines = @(Get-Content $StepsPath | Where-Object { $_ -notmatch '^\s*#' })
  foreach ($literal in @('"CCSync-SubstP"', '"CCSyncSubstP"', 'CCSync_P')) {
    $hits = @($stepsLines | Where-Object { $_ -match [Regex]::Escape($literal) })
    if ($hits.Count -eq 0) { Write-Host "  PASS  no $literal literal in onboarding\steps.py" }
    else {
      $fail++
      Write-Host "  FAIL  $literal is still a literal in onboarding\steps.py: $($hits[0].Trim())" -ForegroundColor Red
    }
  }
}

Write-Host ""
if ($fail -gt 0) { Write-Host "$fail FAILED" -ForegroundColor Red; exit 1 }
Write-Host "all ConvertFrom-CanonicalPrefix + ConvertFrom-DriveMapReport cases pass"

# --- and the live end-to-end probe on this machine -------------------------
Write-Host ""
$IsElevated = $false
$live = & {
  $src2 = $src.Substring($src.IndexOf('function Get-DriveMapping'), $src.IndexOf('function Test-IsElevated') - $src.IndexOf('function Get-DriveMapping'))
  Invoke-Expression $src2
  Get-DriveMapping -Letter 'P'
}
if ($null -eq $live) { Write-Host "live probe: could not determine (would be treated as FOREIGN)" }
# Not an assertion: what this machine has mapped is not the test's business.
else { Write-Host "live probe on this machine: Mapped=$($live.Mapped) Kind=$($live.Kind) Target='$($live.Target)'" }
