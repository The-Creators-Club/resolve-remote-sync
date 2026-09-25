<#
.SYNOPSIS
    Tests for build_editor_package.ps1's REL-7 refusal text
    (Test-SigningKeyTheFleetTrusts): what the operator is told to do when
    this rig's release key did not sign the build the fleet is on.

.DESCRIPTION
    logic-release-1 (2026-09-24, round 2 2026-09-25). The refusal used to say
    "A rotation costs an overlap release: bake --add, ship THAT build ... Pass
    -AllowKeyRotation if this IS that deliberate step." The overlap release is
    the one build that must be signed by the OLD key, so an operator who had
    just baked the new key in, and was refused because the new key was
    already signing, was told to pass the override and strand the fleet.
    docs\RELEASE.md "Rotating" is the procedure that works; this pins the
    refusal to it:

      * the overlap release is signed with the OLD key and never needs the
        override;
      * -AllowKeyRotation does not perform a rotation, and its one rotation
        use is the first build after the key switch;
      * the old "if this IS that deliberate step" invitation is gone;
      * no em dash in anything the operator reads (owner rule 2026-08-18).

    The function is sliced out of the script (the Test-DriveMapParser.ps1
    trick) with its `exit 1` turned into a throw, and the dashboard call is a
    stub, so nothing touches a network or a key.

    Run:  powershell -NoProfile -ExecutionPolicy Bypass -File installer\tests\Test-KeyRotationRefusal.ps1
    Exits 1 on any failure. -ScriptPath runs it against another copy of the
    script (how it was shown to fail on HEAD's).
#>
param([string]$ScriptPath = "")
$ErrorActionPreference = "Stop"

if (-not $ScriptPath) {
    $ScriptPath = Join-Path (Split-Path -Parent $PSScriptRoot) "build_editor_package.ps1"
}
$src = Get-Content -Raw $ScriptPath
$start = $src.IndexOf('function Test-SigningKeyTheFleetTrusts')
$end = $src.IndexOf('if ($Publish -and -not $DryRun) {', [Math]::Max($start, 0))
if ($start -lt 0 -or $end -lt 0 -or $end -le $start) {
    Write-Host "FAIL: could not slice Test-SigningKeyTheFleetTrusts out of $ScriptPath -- did it get renamed?" -ForegroundColor Red
    exit 1
}
$body = $src.Substring($start, $end - $start)
if ($body -notmatch '(?m)^\s*exit 1\s*$') {
    Write-Host "FAIL: the refusal no longer ends in 'exit 1'; this test's slice needs updating" -ForegroundColor Red
    exit 1
}
$body = [regex]::Replace($body, '(?m)^(\s*)exit 1\s*$', '$1throw "REL7-REFUSED"')
Invoke-Expression $body

$script:said = New-Object System.Collections.Generic.List[string]
function Write-Warn2 { param([string]$m) $script:said.Add($m) }
function Write-Step { param([string]$m) $script:said.Add("STEP " + $m) }

$OldKey = "0123456789abcdef"
$NewKey = "fedcba9876543210"
function Invoke-RestMethod {
    param($Method, $Uri, $WebSession)
    return [pscustomobject]@{
        packages = @([pscustomobject]@{
                platform = "windows"; kind = "companion"; is_current = $true
                version = "0.9.78"; pubkey_id = $OldKey
            })
    }
}

$failures = 0
function Check {
    param([string]$What, [bool]$Ok, [string]$Detail = "")
    if ($Ok) { Write-Host ("  ok   {0}" -f $What) }
    else {
        $script:failures++
        Write-Host ("  FAIL {0} {1}" -f $What, $Detail) -ForegroundColor Red
    }
}

function Run-Check {
    param([bool]$Allow)
    $script:said.Clear()
    $script:AllowKeyRotation = $Allow
    $refused = $false
    try { Test-SigningKeyTheFleetTrusts -Url "http://dash.invalid" -Session $null -SigningId $NewKey }
    catch {
        if ("$($_.Exception.Message)" -eq "REL7-REFUSED") { $refused = $true } else { throw }
    }
    return @{ Refused = $refused; Text = ($script:said -join "`n") }
}

$emDash = [string][char]0x2014

# --- the refusal, no override ----------------------------------------------
Write-Host "`n--- refusal (no -AllowKeyRotation) ---"
$r = Run-Check -Allow $false
$flat = ($r.Text -replace "\s+", " ")
Check "a mismatched key is refused" $r.Refused
Check "names the old key as the one that signed the current build" ($flat -match [regex]::Escape("was signed with $OldKey"))
Check "says the overlap release is signed with the OLD key" ($flat -match "overlap release .*signed with the OLD key \($OldKey\)") $flat
Check "says the overlap release never needs an override" ($flat -match "overlap release never needs an override") $flat
Check "says -AllowKeyRotation does not perform a rotation" ($flat -match "-AllowKeyRotation does not perform a rotation") $flat
Check "names the override's one rotation use: the first build after the switch" ($flat -match "FIRST build after the key switch") $flat
Check "points at the runbook" ($flat -match [regex]::Escape("docs\RELEASE.md, Rotating")) $flat
Check "no longer invites the override for the overlap build" (-not ($flat -match "deliberate step")) $flat
Check "no longer says a rotation is 'bake --add, ship THAT'" (-not ($flat -match "ship THAT build")) $flat
Check "no em dash in the refusal" (-not $r.Text.Contains($emDash))

# --- the override ----------------------------------------------------------
Write-Host "`n--- -AllowKeyRotation ---"
$r = Run-Check -Allow $true
$flat = ($r.Text -replace "\s+", " ")
Check "the override publishes (no refusal)" (-not $r.Refused)
Check "the override still says the fleet will refuse the build" ($flat -match "WILL REFUSE THIS BUILD")
Check "the override says when it is right: the first build after the switch" ($flat -match "FIRST build after a rotation's key switch") $flat
Check "no em dash in the override warning" (-not $r.Text.Contains($emDash))

# --- same key: nothing to say ----------------------------------------------
Write-Host "`n--- same key ---"
$script:said.Clear()
$script:AllowKeyRotation = $false
Test-SigningKeyTheFleetTrusts -Url "http://dash.invalid" -Session $null -SigningId $OldKey
Check "the key that signed the current build passes quietly" (($script:said -join "`n") -match "^STEP release key $OldKey also signed")

Write-Host ""
if ($failures) {
    Write-Host "$failures failure(s)" -ForegroundColor Red
    exit 1
}
Write-Host "all passed" -ForegroundColor Green
exit 0
