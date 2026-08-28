<#
.SYNOPSIS
    Drive-mapping primitives shared by windows_bootstrap.ps1 and
    windows_uninstall.ps1.

.DESCRIPTION
    These five functions decide whether the tree drive belongs to CC Sync or
    to somebody else, and then carry out the mount/unmount at the integrity
    level where it will actually be visible. Getting the first question wrong
    on the base rig -- whose tree drive IS the NAS share every
    <drive>:\Projects\... clip path in the Resolve database resolves
    through -- takes the whole tree offline (B21, INST-15).

    They lived in windows_bootstrap.ps1 alone until 2026-08-28, and the
    uninstaller had grown its own weaker copy: Get-PSDrive + Test-Path, with
    "could not tell" reading as "it is ours" -- the exact inversion of the
    rule the bootstrap was fixed to obey, and it gated `net use <drive>
    /delete /y` (OPS-8 / UX-23, resilience sweep 2026-08-28). One file, one
    rule: $null means somebody else's.

    Dot-sourced, not a module: the editor package is a flat folder of .ps1
    files copied to the editor's Downloads, so this file sits beside its two
    callers there exactly as it does in the repo (build_editor_package.ps1
    ships it). The functions read $IsElevated and call Write-Step /
    Write-Warn2 from the DOT-SOURCING script's scope -- both callers define
    all three before they source this file.
#>

# Runs one command line through cmd.exe at the user's NORMAL (unelevated,
# medium-integrity) level, even when this process is elevated. A one-shot
# scheduled task with -RunLevel Limited + -LogonType Interactive is the only
# mechanism in PS 5.1 that reliably does this without a shell round-trip.
#
# WHY it matters: drive letters live in a per-logon-session DOS device map
# that is ALSO split by UAC's linked tokens. A tree drive mapped by an elevated
# process does not exist for the unelevated session Resolve, Explorer and the
# companion run in -- and the elevated session's own Get-PSDrive happily
# reports success, which is what made this invisible (INST-1).
#
# Returns $true only when the task actually ran and exited 0.
function Invoke-AtUserIntegrity {
    param([string]$CommandLine)

    $taskName = "CCSync-OneShot-" + [Guid]::NewGuid().ToString("N").Substring(0, 8)
    try {
        $action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c $CommandLine"
        $principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" `
            -LogonType Interactive -RunLevel Limited
        Register-ScheduledTask -TaskName $taskName -Action $action -Principal $principal -Force | Out-Null
        Start-ScheduledTask -TaskName $taskName

        # 267009 = 0x41301 "task is currently running"; 267011 = 0x41303
        # "task has not yet run" (what a brand-new task reports until the
        # scheduler actually picks it up).
        $result = $null
        $deadline = (Get-Date).AddSeconds(30)
        while ((Get-Date) -lt $deadline) {
            Start-Sleep -Milliseconds 500
            $info = Get-ScheduledTaskInfo -TaskName $taskName -ErrorAction SilentlyContinue
            if ($info -and ($info.LastTaskResult -ne 267009) -and ($info.LastTaskResult -ne 267011)) {
                $result = $info.LastTaskResult
                break
            }
        }
        try { Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue } catch {}
        if ($null -eq $result) { return $false }
        return ($result -eq 0)
    }
    catch {
        try { Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue } catch {}
        return $false
    }
}

# Every tree-drive mount/unmount goes through here. Unelevated (the normal, and the
# documented, case) it just runs; elevated it is routed to the user's own
# integrity level so the mapping is visible where it needs to be.
function Invoke-MappingCommand {
    param([string]$CommandLine, [string]$What = "")

    if (-not $IsElevated) {
        # Redirection must happen INSIDE cmd: a PowerShell-level 2>$null
        # wraps native stderr in a NativeCommandError, fatal under
        # $ErrorActionPreference = 'Stop' when the drive isn't mapped.
        cmd /c "$CommandLine >nul 2>&1"
        return ($LASTEXITCODE -eq 0)
    }

    if (Invoke-AtUserIntegrity "$CommandLine >nul 2>&1") {
        if ($What) {
            Write-Step "$What (run at your normal integrity level via a one-shot task -- this elevated window deliberately cannot see the result)"
        }
        return $true
    }

    Write-Warn2 "could not run '$CommandLine' at your normal integrity level; running it in this elevated session instead."
    $script:MappedWhileElevated = $true
    cmd /c "$CommandLine >nul 2>&1"
    return ($LASTEXITCODE -eq 0)
}

# Parses the combined output of `subst` + `net use` for ONE drive letter.
# Pure text in, object out, so it can be reasoned about without a machine.
#
#   subst   -> "P:\: => C:\CCSync"
#   net use -> "OK           P:        \\localhost\CCSync_P   Microsoft Windows Network"
#              "Unavailable  P:        \\nas\Share  Microsoft Windows Network"
#
# The letter is a PARAMETER, not a constant -- it comes from the site
# manifest's canonical_prefix (2026-08-17, COMMERCIAL_READINESS.md item 11).
#
# The `net use` status column is localised and is sometimes blank, so it is
# deliberately not matched -- the letter followed by a UNC path is the signal,
# and "Unavailable"/"Disconnected" rows count as MAPPED (that is the whole
# point: a persistent mapping to a sleeping NAS is still a mapping).
# The site manifest's `canonical_prefix` -> the bare drive LETTER, uppercase.
# Returns "" for anything this script cannot mount as a drive letter (a UNC, a
# POSIX path, an empty manifest field) -- the caller refuses rather than
# falling back to P:, because a site that publishes something else means it,
# and mapping P: anyway puts the tree behind a letter no clip path mentions.
#
# Pure string-in/string-out so installer/tests/Test-DriveMapParser.ps1 can
# exercise it without a machine in any particular state (2026-08-17,
# COMMERCIAL_READINESS.md item 11).
function ConvertFrom-CanonicalPrefix {
    param([string]$Prefix)

    if ([string]::IsNullOrWhiteSpace($Prefix)) { return "" }
    # Anchored, and the ':' is required: "P" alone, "\\nas\share" and
    # "/mnt/tank/tree" must all be refusals, not near-misses.
    $m = [regex]::Match($Prefix.Trim(), '^(?i)([A-Z]):')
    if (-not $m.Success) { return "" }
    return $m.Groups[1].Value.ToUpperInvariant()
}

function ConvertFrom-DriveMapReport {
    param([string]$Report, [string]$Letter = "P")

    $result = [PSCustomObject]@{ Mapped = $false; Kind = "none"; Target = "" }
    if ([string]::IsNullOrEmpty($Report)) { return $result }
    $L = [regex]::Escape($Letter)

    foreach ($line in ($Report -split "`r?`n")) {
        $trimmed = $line.Trim()
        if (-not $trimmed) { continue }

        $substMatch = [regex]::Match($trimmed, "(?i)^$L`:\\?:\s*=>\s*(.+)$")
        if ($substMatch.Success) {
            $result.Mapped = $true
            $result.Kind = "subst"
            $result.Target = $substMatch.Groups[1].Value.Trim()
            return $result
        }

        $netMatch = [regex]::Match($trimmed, "(?i)(^|\s)$L`:\s+(\\\\\S+)")
        if ($netMatch.Success) {
            $result.Mapped = $true
            $result.Kind = "netuse"
            $result.Target = $netMatch.Groups[2].Value.Trim()
            return $result
        }
    }
    return $result
}

# Reads the CURRENT USER's DOS device map for one drive letter, at the user's
# own integrity level. Returns $null when the state could NOT be determined --
# callers MUST treat $null as "somebody else's mapping" and refuse to touch it.
#
# WHY not `Test-Path "<drive>:\"` (B21, same root cause as INST-1/INST-15):
# drive letters live in a per-logon-session device map that UAC additionally
# splits between the linked tokens, so an ELEVATED run cannot see the mapping
# the unelevated session holds -- yet the teardown below runs via
# Invoke-AtUserIntegrity inside that very session. And Test-Path reports
# $false for a DISCONNECTED persistent mapping (NAS asleep, Tailscale not up
# -- both likely at bootstrap time) that is still in the device map and will
# reconnect. Both read as "there is nothing mapped here", after which the
# teardown deleted the base rig's real NAS mapping and section 5 recreated the
# letter as a loopback of a local folder, taking every \Projects\... clip path in the
# Resolve database offline.
function Get-DriveMapping {
    param([string]$Letter = "P")

    $tempRoot = $env:TEMP
    if ([string]::IsNullOrWhiteSpace($tempRoot)) { $tempRoot = [System.IO.Path]::GetTempPath() }
    $tmp = Join-Path $tempRoot ("ccsync-drivemap-" + [Guid]::NewGuid().ToString("N").Substring(0, 8) + ".txt")
    # Redirection happens INSIDE cmd: a PowerShell-level redirect wraps native
    # stderr in a NativeCommandError, fatal under $ErrorActionPreference='Stop'
    # when nothing is mapped at all.
    $cmdLine = "(subst & net use) > `"$tmp`" 2>&1"
    $report = $null
    try {
        if ($IsElevated) {
            # Read-only probe, so it runs even under -DryRun: without it an
            # elevated dry run would report the wrong verdict, which is the
            # bug this function exists to fix.
            Invoke-AtUserIntegrity $cmdLine | Out-Null
        }
        else {
            cmd /c $cmdLine
        }
        # The exit code is `net use`'s and is noise (non-zero when there are no
        # connections at all). The file is the signal.
        if (Test-Path -LiteralPath $tmp) {
            $report = Get-Content -LiteralPath $tmp -Raw -ErrorAction SilentlyContinue
            if ($null -eq $report) { $report = "" }
        }
    }
    catch {
        $report = $null
    }
    finally {
        try { Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue } catch {}
    }

    if ($null -eq $report) { return $null }
    return (ConvertFrom-DriveMapReport -Report $report -Letter $Letter)
}

function Test-IsElevated {
    try {
        $id = [Security.Principal.WindowsIdentity]::GetCurrent()
        $principal = New-Object Security.Principal.WindowsPrincipal($id)
        return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    }
    catch {
        return $false
    }
}
