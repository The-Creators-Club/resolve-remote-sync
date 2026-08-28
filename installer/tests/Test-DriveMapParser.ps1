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
# The parsers used to be sliced out of windows_bootstrap.ps1 by string index.
# They live in installer/drive_mapping.ps1 since 2026-08-28 (OPS-8 / UX-23),
# shared with windows_uninstall.ps1, so this dot-sources the real file -- which
# also means a syntax error in it fails the suite instead of hiding until an
# editor runs an install.
$InstallerDir = Split-Path -Parent $PSScriptRoot
$BootstrapPath = Join-Path $InstallerDir "windows_bootstrap.ps1"
$UninstallPath = Join-Path $InstallerDir "windows_uninstall.ps1"
$LibPath = Join-Path $InstallerDir "drive_mapping.ps1"
if (-not (Test-Path -LiteralPath $LibPath)) {
    Write-Host "FAIL: no drive_mapping.ps1 at $LibPath" -ForegroundColor Red
    exit 1
}
$IsElevated = $false          # the library reads it; nothing here mounts anything
function Write-Step { param([string]$m) }
function Write-Warn2 { param([string]$m) }
. $LibPath
$src = Get-Content -Raw $BootstrapPath
foreach ($fn in @('ConvertFrom-CanonicalPrefix', 'ConvertFrom-DriveMapReport',
                  'Get-DriveMapping', 'Invoke-MappingCommand', 'Invoke-AtUserIntegrity',
                  'Test-IsElevated')) {
    if (-not (Get-Command $fn -ErrorAction SilentlyContinue)) {
        Write-Host "FAIL: drive_mapping.ps1 does not define $fn" -ForegroundColor Red
        exit 1
    }
}

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

# --- one classification, in one file, used by both scripts -----------------
# OPS-8 / UX-23 (resilience sweep 2026-08-28). windows_uninstall.ps1 decided
# "is this drive ours?" from Get-PSDrive + Test-Path inside a try/catch, and
# any failure there left $displayRoot BLANK -- which the ownership expression
# read as "a subst mapping, ours" and then ran `net use <drive> /delete /y` on.
# The bootstrap had already been fixed to treat "can't tell" as foreign (B21);
# the uninstaller inverted it. These cases pin the fix in place, because the
# machine states that trigger it (an elevated run, a disconnected persistent
# mapping) are the ones a manual test never has.
$uninst = Get-Content -Raw $UninstallPath
$uninstLines = @(Get-Content $UninstallPath | Where-Object { $_ -notmatch '^\s*#' })
$srcLines = @(Get-Content $BootstrapPath | Where-Object { $_ -notmatch '^\s*#' })

$sourceCases = @(
  @{ n = 'the uninstaller dot-sources the shared library'
     ok = ($uninstLines -match '^\s*\.\s+\$DriveMappingLib').Count -gt 0 }
  @{ n = 'the bootstrap dot-sources it too'
     ok = ($srcLines -match '^\s*\.\s+\$DriveMappingLib').Count -gt 0 }
  @{ n = 'neither script redefines the parsers'
     ok = -not ($srcLines -match 'function ConvertFrom-DriveMapReport') -and
          -not ($uninstLines -match 'function ConvertFrom-DriveMapReport') }
  @{ n = 'the uninstaller classifies with Get-DriveMapping'
     ok = ($uninstLines -match 'Get-DriveMapping').Count -gt 0 }
  @{ n = 'the uninstaller no longer asks Get-PSDrive/DisplayRoot whose drive it is'
     ok = -not ($uninstLines -match 'Get-PSDrive') -and -not ($uninstLines -match 'DisplayRoot') }
  @{ n = 'an unreadable mapping table is FOREIGN in the uninstaller'
     ok = $uninst -match '\$null -eq \$mapping' }
  @{ n = 'the unmap runs at the USER integrity level, not this token''s'
     ok = ($uninstLines -match 'Invoke-MappingCommand "net use \$DriveRoot /delete /y"').Count -gt 0 }
  @{ n = 'no raw cmd /c net use /delete survives in the uninstaller'
     ok = -not ($uninstLines -match 'cmd /c "net use \$DriveRoot /delete') }
  @{ n = 'the share is removed only after the unmap settled'
     ok = ($uninstLines -match '\$share -and -not \$unmapSettled').Count -gt 0 }
  @{ n = 'and the two by-hand commands are printed when it did not'
     ok = ($uninst -match 'net use \$DriveRoot /delete /y') -and
          ($uninst -match 'Remove-SmbShare -Name \$ShareName -Force') }
  @{ n = 'the bootstrap refuses to run without the library'
     ok = ($srcLines -match 'drive_mapping\.ps1 is missing').Count -gt 0 }
  @{ n = 'the editor package ships the library'
     ok = (Get-Content -Raw (Join-Path $InstallerDir "build_editor_package.ps1")) -match
          'installer\\drive_mapping\.ps1' }
  @{ n = 'onboard.exe bundles it beside the bootstrap it extracts'
     ok = (Get-Content -Raw (Join-Path (Split-Path -Parent $InstallerDir) "onboarding\build_onboard.spec")) -match
          'DRIVE_MAPPING_PS1' }
)
foreach ($c in $sourceCases) {
  if ($c.ok) { Write-Host "  PASS  $($c.n)" }
  else {
    $fail++
    Write-Host "  FAIL  $($c.n)" -ForegroundColor Red
  }
}

# A $null report is what Get-DriveMapping returns when the probe could not be
# read at all; the parser must never turn that into a mapping.
$nullRes = ConvertFrom-DriveMapReport -Report $null -Letter 'P'
if (-not $nullRes.Mapped -and $nullRes.Kind -eq 'none') { Write-Host "  PASS  an unreadable report is never a mapping" }
else { $fail++; Write-Host "  FAIL  an unreadable report parsed as a mapping" -ForegroundColor Red }

Write-Host ""
if ($fail -gt 0) { Write-Host "$fail FAILED" -ForegroundColor Red; exit 1 }
Write-Host "all ConvertFrom-CanonicalPrefix + ConvertFrom-DriveMapReport cases pass"

# --- and the live end-to-end probe on this machine -------------------------
Write-Host ""
$live = Get-DriveMapping -Letter 'P'
if ($null -eq $live) { Write-Host "live probe: could not determine (would be treated as FOREIGN)" }
# Not an assertion: what this machine has mapped is not the test's business.
else { Write-Host "live probe on this machine: Mapped=$($live.Mapped) Kind=$($live.Kind) Target='$($live.Target)'" }
