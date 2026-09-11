#requires -Version 5.1
<#
.SYNOPSIS
    The parts of tools\ship.ps1's step 0a that can be exercised without a
    NAS, a dashboard or a PyInstaller build. Dot-sourced by ship.ps1.

.DESCRIPTION
    server-tools-1 (2026-09-11): the -EmitKindExtras gate lived entirely
    inside ship.ps1, where the only thing a test could assert was its source
    text -- and the defect was in the PowerShell semantics of one comparison,
    which no source-text assertion can see. The decision half lives here so
    tools/tests/test_release_scripts.py can run it, with real health payloads,
    through `powershell -NoProfile`. ship.ps1 keeps every message and every
    exit: this file answers, it never decides what the operator is told.

    Nothing in here touches the network, the filesystem or $env:.
#>

function Test-VersionAtLeast {
    param([string]$Have, [string]$Want)
    if (-not $Have -or -not $Want) { return $false }
    $a = @(); $b = @()
    foreach ($part in ($Have -split '\.')) { if ($part -notmatch '^\d+$') { return $false }; $a += [int]$part }
    foreach ($part in ($Want -split '\.')) { if ($part -notmatch '^\d+$') { return $false }; $b += [int]$part }
    for ($i = 0; $i -lt [Math]::Max($a.Count, $b.Count); $i++) {
        $x = 0; $y = 0
        if ($i -lt $a.Count) { $x = $a[$i] }
        if ($i -lt $b.Count) { $y = $b[$i] }
        if ($x -gt $y) { return $true }
        if ($x -lt $y) { return $false }
    }
    return $true
}

function Get-JsonProperty {
    <# $obj.name on a ConvertFrom-Json object cannot tell "the property is
       absent" from "the property is JSON null" -- both read as $null under
       Set-StrictMode off, and the first one THROWS under it. Ask the
       PSObject instead, and report the two apart. #>
    param($Object, [string]$Name)
    if ($null -eq $Object) { return [pscustomobject]@{ Present = $false; Value = $null } }
    $props = $Object.PSObject.Properties
    if ($null -eq $props -or $props.Match($Name).Count -eq 0) {
        return [pscustomobject]@{ Present = $false; Value = $null }
    }
    return [pscustomobject]@{ Present = $true; Value = $Object.$Name }
}

function Get-KindExtrasVerdict {
    <#
    .SYNOPSIS
        Is -EmitKindExtras safe against this /api/v1/health body?

    .DESCRIPTION
        Returns { Readable; Reason; Stragglers }. `Readable = $false` means
        THE FLEET COULD NOT BE ASSESSED, which is a refusal: a computer below
        $Floor refuses a record carrying the extra signed fields permanently,
        and the only recovery is a reinstall at that desk, so "we could not
        tell" is never "go ahead" here.

        server-tools-1 (2026-09-11) fixed two ways this answered "all clear"
        having checked nothing:

        1. the old guard was `if ($null -eq $health.rollout)`, and in
           PowerShell `$null -eq @()` is $FALSE. api._rollout_block returns
           [] on ANY exception with HTTP 200 (a locked DB, a column an older
           schema lacks, a collector mid-migration), so an empty array walked
           past the refusal, the foreach ran zero times and the gate passed.
           An empty rollout is now "could not tell", never "nobody is behind".

        2. it iterated CHANNELS, and db.rollout_status builds one channel per
           (kind, platform) that has a CURRENT build. A platform with real
           computers and no current companion package -- a fresh site, or a
           macOS channel nobody has pointed current -- contributed no channel
           and its machines were invisible even when the array was non-empty.
           That is the leso-Mac-on-0.9.2 shape exactly. So the count that
           decides is MACHINES PER PLATFORM (`rollout_platforms`), and a
           dashboard too old to report it is unreadable, not clear.
    #>
    param($Health, [string]$Floor)

    $verdict = [pscustomobject]@{ Readable = $false; Reason = ""; Stragglers = @() }
    if ($null -eq $Health) {
        $verdict.Reason = "the dashboard did not answer /api/v1/health, or the answer was not JSON"
        return $verdict
    }

    $rollout = Get-JsonProperty $Health "rollout"
    if (-not $rollout.Present -or $null -eq $rollout.Value) {
        $verdict.Reason = "its health answer carries no rollout block: the dashboard could not compute one"
        return $verdict
    }
    $channels = @($rollout.Value)
    if ($channels.Count -eq 0) {
        $verdict.Reason = "its rollout block is EMPTY, which means either that no companion build is current there or that computing the rollout raised. Those are two different facts and this answer cannot tell them apart"
        return $verdict
    }

    # Machines per platform, independent of which platforms have a current
    # package. Absent = a dashboard older than the one that reports it, and
    # on this gate that is a refusal (see 2. above).
    $platforms = Get-JsonProperty $Health "rollout_platforms"
    if (-not $platforms.Present -or $null -eq $platforms.Value) {
        $verdict.Reason = "this dashboard does not report how many computers each platform has (rollout_platforms), so a platform with computers and no current build cannot be counted"
        return $verdict
    }

    $verdict.Readable = $true
    $stragglers = @()
    $covered = @{}
    foreach ($c in $channels) {
        $p = "$($c.platform)".Trim().ToLower()
        if ($p) { $covered[$p] = $true }
        $cur = "$($c.current_version)"
        if (-not (Test-VersionAtLeast $cur $Floor)) {
            $stragglers += "$p computers are offered $cur, which is below $Floor"
        }
        elseif ([int]$c.behind -gt 0) {
            $stragglers += "$([int]$c.behind) $p computer(s) are behind $cur and could be below $Floor"
        }
    }
    foreach ($prop in $platforms.Value.PSObject.Properties) {
        $p = "$($prop.Name)".Trim().ToLower()
        $count = 0
        if (-not [int]::TryParse("$($prop.Value)", [ref]$count)) {
            $stragglers += "$p reported an unreadable computer count ($($prop.Value))"
            continue
        }
        if ($count -le 0) { continue }
        if (-not $covered.ContainsKey($p)) {
            $stragglers += "$count $p computer(s) have no current build on this dashboard, so their versions were never checked against $Floor"
        }
    }
    $verdict.Stragglers = @($stragglers)
    return $verdict
}
