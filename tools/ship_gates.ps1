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

function Get-RolloutPlatformName {
    <#
      One spelling for a machine's platform, whichever block of the health
      answer it came out of (server-tools-b-2, 2026-09-11b).

      machine_state.platform is NULLABLE - SCHEMA_V8 added it as a bare ALTER
      TABLE and record_report keeps a NULL with COALESCE - and the two blocks
      of ONE health body disagreed about such a row: db.rollout_status counts
      it as `windows` (str(... or "windows")), while _rollout_platforms_block
      reports it as `unknown`. This gate then found a platform with computers
      that no channel covers and refused -EmitKindExtras for ever, naming a
      platform that does not exist, about a machine that WAS checked inside
      the windows channel, with no command anywhere that could clear it.

      windows is the fallback because that is what the counting side has
      always used; the honest fix is on the dashboard, and until that ships
      this keeps the gate from refusing on a phantom.
    #>
    param([string]$Name)
    $p = "$Name".Trim().ToLower()
    if (-not $p -or $p -eq "unknown") { return "windows" }
    return $p
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
        $p = Get-RolloutPlatformName "$($prop.Name)"
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

function Get-CardsDeployVerdict {
    <#
      What check_deploy_drift.ps1 may say about /cards, given the facts it can
      gather locally (2026-09-11b). Pure, so the tools suite can feed it the
      states nobody can produce on a base rig with a live dashboard:

        server-tools-b-1  an uncommitted checkout is NOT OK. The snapshot
          deploy ships a commit, so the state it was written to prevent -
          half-finished work reaching the NAS - became a state nothing could
          see: finished work NOT reaching it. `head -eq commit` is exactly
          what an uncommitted wave looks like, and it used to print OK.
        server-tools-b-3  a record with no commit is the DIRECTORY override,
          and an absent commit must not be readable as an old commit.
        server-tools-b-4  a site with no Timeline Cards is not asked about
          them at all: a permanent "? NOT CHECKED" pointing at an internal
          runbook for a feature the customer does not have teaches an
          operator to ignore the doctor's ? lines, which is how the three
          real checks that use them stop being read.

      Returns @{ Kind = 'ok'|'drift'|'unknown'|'skip'; Text = <line> }.
    #>
    param(
        $Record,
        [string]$Head = "",
        [int]$Dirty = 0,
        [bool]$SiteHasCards = $true,
        [string]$RecordPath = "",
        [string]$Ahead = ""
    )
    $v = @{ Kind = "unknown"; Text = "" }
    if (-not $Record) {
        if (-not $SiteHasCards) {
            $v.Kind = "skip"
            $v.Text = "this site has no Timeline Cards ([timeline_cards] in site.toml), so there is nothing to check"
            return $v
        }
        $v.Text = "no cards deploy record at $RecordPath -- this machine has not shipped /cards since 2026-09-11 (docs\CARDS_DEPLOY.md). NOT CHECKED, not OK."
        return $v
    }
    $commit = "$($Record.commit)".Trim()
    $override = "$($Record.override)".Trim()
    if (-not $commit) {
        $where = if ($override) { $override } else { "an unnamed directory" }
        $v.Text = "/cards was last shipped as the DIRECTORY $where, not a commit -- nothing here can say which code that was. NOT CHECKED, not OK."
        return $v
    }
    $short = "$($Record.short)".Trim()
    if (-not $short) { $short = $commit.Substring(0, [Math]::Min(12, $commit.Length)) }
    $ref = "$($Record.ref)".Trim()
    if (-not $ref) { $ref = "main" }
    if (-not $Head) {
        $v.Text = "cannot read $ref in the Timeline Cards repo -- cannot compare"
        return $v
    }
    if ($Head -ne $commit) {
        $v.Kind = "drift"
        $count = ""
        if ($Ahead -and $Ahead -ne "0") { $count = " ($Ahead commits)" }
        $v.Text = "$ref is now $($Head.Substring(0, [Math]::Min(12, $Head.Length)))$count, ahead of the shipped $short"
        return $v
    }
    if ($Dirty -gt 0) {
        $v.Kind = "drift"
        $v.Text = "/cards was shipped from $ref at $short, which is still its head -- but $Dirty file(s) in that checkout are uncommitted, so THEY ARE NOT ON THE NAS. Commit them and re-ship."
        return $v
    }
    $v.Kind = "ok"
    $v.Text = "/cards was shipped from $ref at $short, which is still its head, and that checkout is clean"
    return $v
}
