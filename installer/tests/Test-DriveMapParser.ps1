<#
.SYNOPSIS
    Table tests for windows_bootstrap.ps1's ConvertFrom-DriveMapReport, plus a
    live read of this machine's own P: mapping.

.DESCRIPTION
    ConvertFrom-DriveMapReport decides whether the P: drive belongs to this
    installer or to somebody else, and the answer gates a destructive teardown
    (`subst P: /D` + `net use P: /delete /y`). Getting it wrong on the base rig
    -- whose P: IS the NAS share every P:\Projects\... clip path in the Resolve
    database resolves through -- takes the whole tree offline (B21, INST-15).

    The parser is pure text-in/object-out precisely so it can be checked here
    without a machine in any particular state. The `net use` status column is
    localised and sometimes blank, so the cases below cover OK / Unavailable /
    Disconnected / blank, both mapping styles, and other drive letters.

    Run:  powershell -NoProfile -ExecutionPolicy Bypass -File installer\tests\Test-DriveMapParser.ps1
    Exits 1 on any failure.
#>
$ErrorActionPreference = "Stop"
# Pull just the parser out of the bootstrap so it can be exercised standalone.
$BootstrapPath = Join-Path (Split-Path -Parent $PSScriptRoot) "windows_bootstrap.ps1"
$src = Get-Content -Raw $BootstrapPath
$start = $src.IndexOf('function ConvertFrom-DriveMapReport')
$end = $src.IndexOf('# Reads the CURRENT USER''s DOS device map')
Invoke-Expression $src.Substring($start, $end - $start)

$UNC1 = [char]92 + [char]92 + 'localhost' + [char]92 + 'CCSync_P'
$UNC2 = [char]92 + [char]92 + 'nas' + [char]92 + 'Media'
$UNC3 = [char]92 + [char]92 + '10.0.0.5' + [char]92 + 'pool'
$UNC4 = [char]92 + [char]92 + 'nas' + [char]92 + 'share'

$cases = @(
  @{ n = 'subst mapping'; r = "P:\: => C:\Creators_Club`r`n"; m = $true; k = 'subst'; t = 'C:\Creators_Club' }
  @{ n = 'subst with space in path'; r = "P:\: => D:\Video Projects\Creators_Club`r`n"; m = $true; k = 'subst'; t = 'D:\Video Projects\Creators_Club' }
  @{ n = 'other letter subst only'; r = "Q:\: => C:\Other`r`n"; m = $false; k = 'none'; t = '' }
  @{ n = 'net use OK loopback'; r = "Status       Local     Remote                    Network`r`n`r`n-----------`r`nOK           P:        $UNC1      Microsoft Windows Network`r`nThe command completed successfully.`r`n"; m = $true; k = 'netuse'; t = $UNC1 }
  @{ n = 'net use Unavailable NAS'; r = "Unavailable  P:        $UNC2      Microsoft Windows Network`r`n"; m = $true; k = 'netuse'; t = $UNC2 }
  @{ n = 'net use Disconnected'; r = "Disconnected P:        $UNC3       Microsoft Windows Network`r`n"; m = $true; k = 'netuse'; t = $UNC3 }
  @{ n = 'net use blank status'; r = "             P:        $UNC4                Microsoft Windows Network`r`n"; m = $true; k = 'netuse'; t = $UNC4 }
  @{ n = 'net use other letters'; r = "OK           Z:        $UNC4                Microsoft Windows Network`r`n"; m = $false; k = 'none'; t = '' }
  @{ n = 'nothing at all'; r = "There are no entries in the list.`r`n"; m = $false; k = 'none'; t = '' }
  @{ n = 'empty'; r = ""; m = $false; k = 'none'; t = '' }
  @{ n = 'subst wins over a stale net row'; r = "P:\: => C:\Creators_Club`r`nOK           P:        $UNC4   Net`r`n"; m = $true; k = 'subst'; t = 'C:\Creators_Club' }
  @{ n = 'lowercase letter row'; r = "OK           p:        $UNC1      Microsoft Windows Network`r`n"; m = $true; k = 'netuse'; t = $UNC1 }
)

$fail = 0
foreach ($c in $cases) {
  $res = ConvertFrom-DriveMapReport -Report $c.r -Letter 'P'
  $okm = ($res.Mapped -eq $c.m); $okk = ($res.Kind -eq $c.k); $okt = ($res.Target -eq $c.t)
  if ($okm -and $okk -and $okt) { Write-Host "  PASS  $($c.n)" }
  else {
    $fail++
    Write-Host "  FAIL  $($c.n): got Mapped=$($res.Mapped) Kind=$($res.Kind) Target='$($res.Target)' want Mapped=$($c.m) Kind=$($c.k) Target='$($c.t)'" -ForegroundColor Red
  }
}
Write-Host ""
if ($fail -gt 0) { Write-Host "$fail FAILED" -ForegroundColor Red; exit 1 }
Write-Host "all ConvertFrom-DriveMapReport cases pass"

# --- and the live end-to-end probe on this machine -------------------------
Write-Host ""
$IsElevated = $false
$live = & {
  $src2 = $src.Substring($src.IndexOf('function Get-DriveMapping'), $src.IndexOf('function Test-IsElevated') - $src.IndexOf('function Get-DriveMapping'))
  Invoke-Expression $src2
  Get-DriveMapping -Letter 'P'
}
if ($null -eq $live) { Write-Host "live probe: could not determine (would be treated as FOREIGN)" }
else { Write-Host "live probe on this machine: Mapped=$($live.Mapped) Kind=$($live.Kind) Target='$($live.Target)'" }
