#requires -Version 5.1
<#
.SYNOPSIS
    Uninstall CCSync (companion + Syncthing autostart + drive mapping) from an
    editor's Windows machine.

.DESCRIPTION
    Removes the CCSync software this machine runs. It never touches your
    synced media: your local tree folder and everything in it is left
    exactly as it is, in both modes. Two modes:

      (default) -- remove the CCSync app and its autostart entries, and keep
        your saved sign-in and Syncthing identity, so reinstalling is
        painless and the admin does not have to re-approve you. Removes: running
        processes, the three autostart entries, the tree drive mapping and
        its loopback share (plus the firewall rule that scoped it), and the
        program binaries under %LOCALAPPDATA%\ccsync\bin.

      -Full -- also remove your saved sign-in and Syncthing identity (a
        reinstall then needs the admin to re-approve you). Neither mode ever
        deletes your synced media under local_root, and neither mode
        deletes ~/.ccsync\state (the once-ever prompt answers and local
        caches -- see section 5).

    Never uninstalls Tailscale / rclone / Syncthing that were installed as
    system packages (winget/scoop) -- those may be shared with other tools;
    remove them from "Apps & features" yourself if wanted. The rclone SSH key
    in ~/.ssh is never deleted (shared location); -Full just notes it.

    Every step is guarded and idempotent -- safe to re-run. -DryRun prints
    what it would do and touches nothing.

.PARAMETER Full
    Also remove your saved sign-in and Syncthing identity (a reinstall then
    needs the admin to re-approve you). Your synced media is never touched, and
    ~/.ccsync\state is kept either way.

.PARAMETER DryRun
    Report actions without performing them.

.EXAMPLE
    .\windows_uninstall.ps1            # keep identity, ready to reinstall

.EXAMPLE
    .\windows_uninstall.ps1 -Full      # also drop the sign-in + device identity
#>
[CmdletBinding()]
param(
    # Which drive letter the tree is mounted as. Blank = read it out of
    # ~/.ccsync/config.toml's canonical_prefix, else P: (2026-08-17,
    # COMMERCIAL_READINESS.md item 11). The letter used to be a literal here
    # AND in every name this script removes -- CCSync-SubstP, CCSyncSubstP,
    # CCSync_P, ##localhost#CCSync_P -- so on a site that mounts the tree
    # somewhere else the uninstall silently removed nothing and reported
    # success. Read locally, never from the dashboard: an uninstall has to
    # work on a machine that is off the tailnet.
    [string]$DriveLetter = "",
    [switch]$Full,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

function Write-Step { param([string]$m) Write-Host "[uninstall] $m" }
function Write-Skip { param([string]$m) Write-Host "[uninstall] (skip) $m" -ForegroundColor DarkGray }
function Write-Warn2 { param([string]$m) Write-Host "[uninstall] WARNING: $m" -ForegroundColor Yellow }

# The tree-drive classification and the mount/unmount primitives, shared with
# windows_bootstrap.ps1 (OPS-8 / UX-23, resilience sweep 2026-08-28). This
# script used to decide "is this drive ours?" from Get-PSDrive + Test-Path,
# with a try/catch that turned any failure into a BLANK DisplayRoot -- which
# the ownership expression read as "a subst mapping, ours" and then ran
# `net use <drive> /delete /y` on. That is the inversion of the rule the
# bootstrap was fixed to obey (B21): unreadable means somebody else's.
#
# NOT fatal when absent, unlike in the bootstrap: removing the app, the
# autostart entries and the binaries is the bulk of an uninstall and needs no
# drive mapping at all. Without the library the mapping and share are LEFT
# ALONE and the two commands are printed.
$MappingLibLoaded = $false
$DriveMappingLib = Join-Path $PSScriptRoot "drive_mapping.ps1"
if (Test-Path -LiteralPath $DriveMappingLib) {
    try {
        . $DriveMappingLib
        $MappingLibLoaded = $true
    }
    catch {
        Write-Warn2 "could not load drive_mapping.ps1: $($_.Exception.Message)"
    }
}
$IsElevated = $false
if ($MappingLibLoaded) { $IsElevated = Test-IsElevated }

$RunKeyPath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
$CcsyncLocal = "$env:LOCALAPPDATA\ccsync"
$BinDir = "$CcsyncLocal\bin"
$SyncthingHome = "$CcsyncLocal\syncthing-config"
$CcsyncProfile = "$env:USERPROFILE\.ccsync"

if (-not $DriveLetter) {
    $cfg = "$CcsyncProfile\config.toml"
    if (Test-Path -LiteralPath $cfg) {
        $m = Select-String -Path $cfg -Pattern '^\s*canonical_prefix\s*=\s*"([A-Za-z]):' |
            Select-Object -First 1
        if ($m) { $DriveLetter = $m.Matches[0].Groups[1].Value }
    }
}
if (-not $DriveLetter) { $DriveLetter = "P" }
$DriveLetter = $DriveLetter.Substring(0, 1).ToUpperInvariant()
$DriveRoot = "${DriveLetter}:"
$ShareName = "CCSync_$DriveLetter"
$SubstTaskName = "CCSync-Subst$DriveLetter"
$SubstRunEntry = "CCSyncSubst$DriveLetter"
# Named exactly as windows_bootstrap.ps1's Set-SmbLoopbackFirewallRule creates
# it -- the block rule is ours and must go with the share it scoped.
$SmbFirewallRuleName = "CC Sync: block remote SMB (tree share is loopback-only)"

Write-Step "mode: $(if ($Full) { 'FULL (also removes your sign-in + Syncthing identity)' } else { 'keep sign-in + settings' })"
Write-Step "your synced media is never touched by this script -- only the CCSync app itself."
if ($DryRun) { Write-Step "DRY RUN -- nothing will be changed" }

# --- 1. stop running processes --------------------------------------------
foreach ($procName in @("ccsync-companion", "syncthing")) {
    $procs = Get-Process -Name $procName -ErrorAction SilentlyContinue
    if ($procs) {
        if ($DryRun) { Write-Step "[dry-run] would stop process: $procName ($($procs.Count))" }
        else {
            $procs | Stop-Process -Force -ErrorAction SilentlyContinue
            Write-Step "stopped process: $procName"
        }
    }
    else { Write-Skip "process not running: $procName" }
}
# The repo-from-source companion runs as pythonw launcher.py; stop those too.
$pyw = Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and $_.CommandLine -match "launcher\.py" }
if ($pyw) {
    if ($DryRun) { Write-Step "[dry-run] would stop $($pyw.Count) source-mode companion (pythonw launcher.py)" }
    else {
        $pyw | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
        Write-Step "stopped source-mode companion (pythonw launcher.py)"
    }
}

# --- 2. autostart entries -------------------------------------------------
$runEntries = @("CCSyncCompanion", "CCSyncSyncthing", $SubstRunEntry)
foreach ($name in $runEntries) {
    $exists = $null
    try { $exists = (Get-ItemProperty -Path $RunKeyPath -Name $name -ErrorAction SilentlyContinue).$name } catch {}
    if ($exists) {
        if ($DryRun) { Write-Step "[dry-run] would remove autostart: $RunKeyPath\$name" }
        else {
            Remove-ItemProperty -Path $RunKeyPath -Name $name -ErrorAction SilentlyContinue
            Write-Step "removed autostart: $name"
        }
    }
    else { Write-Skip "no autostart entry: $name" }
}

# scheduled-task variant of the mapping (used when bootstrap had admin rights)
$task = Get-ScheduledTask -TaskName $SubstTaskName -ErrorAction SilentlyContinue
if ($task) {
    if ($DryRun) { Write-Step "[dry-run] would unregister scheduled task: $SubstTaskName" }
    else {
        try { Unregister-ScheduledTask -TaskName $SubstTaskName -Confirm:$false -ErrorAction Stop; Write-Step "unregistered scheduled task: $SubstTaskName" }
        catch { Write-Warn2 "could not unregister task ${SubstTaskName}: $($_.Exception.Message)" }
    }
}
else { Write-Skip "no scheduled task: $SubstTaskName" }

# CCSync-OneShot-<hex> tasks: windows_bootstrap.ps1's Invoke-AtUserIntegrity
# registers one per mapping command to run it at the user's own integrity
# level, and unregisters it in a finally -- but only if the process survives
# that long. Its own 30s wait, an aborted run, or onboard.exe's bootstrap
# timeout killing the powershell leaves them behind, one per attempt, forever.
# This script only ever knew about the subst task, so -Full left them
# accumulating in Task Scheduler on every machine that ever hit the path.
$oneShots = @()
try {
    $oneShots = @(Get-ScheduledTask -TaskName "CCSync-OneShot-*" -ErrorAction SilentlyContinue)
}
catch { $oneShots = @() }
if ($oneShots.Count -gt 0) {
    foreach ($t in $oneShots) {
        if ($DryRun) { Write-Step "[dry-run] would unregister orphaned scheduled task: $($t.TaskName)" }
        else {
            try {
                Unregister-ScheduledTask -TaskName $t.TaskName -Confirm:$false -ErrorAction Stop
                Write-Step "unregistered orphaned scheduled task: $($t.TaskName)"
            }
            catch { Write-Warn2 "could not unregister task $($t.TaskName): $($_.Exception.Message)" }
        }
    }
}
else { Write-Skip "no orphaned CCSync-OneShot-* scheduled tasks" }

# --- 3. tree drive mapping -------------------------------------------------
# D-8: on the BASE rig, the tree drive and T: are real SMB mappings of the NAS itself that
# this installer never created (onboarding/steps.py's build_cleanup_plan
# deliberately guards the same thing with unmount_p=(role=="editor")). This
# script has no -Role switch, so detect instead: a subst mapping has no
# DisplayRoot and is always ours (the bootstrap's fallback style); a net-use
# mapping is only ours if it points at our own loopback share. Anything
# else -- a net-use mapping to a real host -- must be left alone.
#
# OPS-8 / UX-23 (resilience sweep 2026-08-28) replaced Get-PSDrive +
# Test-Path with the bootstrap's own Get-DriveMapping. Three things changed,
# each of them a real machine state this script used to get wrong:
#   $null (mappings unreadable) is FOREIGN, not "a subst mapping, ours".
#   A disconnected persistent mapping (NAS asleep, Tailscale down) is a
#   MAPPING; Test-Path called it absent and the ownership guard never ran.
#   The unmap goes through Invoke-MappingCommand, so an elevated uninstall
#   (which is the reasonable way to run one -- Remove-SmbShare needs it)
#   acts on the USER's device map instead of the elevated token's own.
Write-Step "tree drive: $DriveRoot (loopback share '$ShareName')"
# Gates the share removal below: the share must outlive a mapping that is
# still pointing at it. A user session left holding $DriveRoot after the share
# is gone has a drive letter that ERRORS on every access, which is worse than
# one that is cleanly still there.
$unmapSettled = $false
$mapping = $null
if (-not $MappingLibLoaded) {
    Write-Warn2 "drive_mapping.ps1 is not beside this script, so $DriveRoot cannot be classified. Leaving the mapping and the '$ShareName' share exactly as they are -- see the two commands printed below."
}
else {
    $mapping = Get-DriveMapping -Letter $DriveLetter
    if ($null -eq $mapping) {
        Write-Warn2 "could not read this logon session's drive mappings, so $DriveRoot is being treated as somebody else's and left alone. That is deliberate: guessing 'there is nothing mapped here' is how a real NAS mapping gets deleted (B21)."
    }
    elseif (-not $mapping.Mapped) {
        Write-Skip "$DriveRoot not mapped"
        $unmapSettled = $true
    }
    else {
        $target = $mapping.Target
        $ours = ($mapping.Kind -eq "subst") -or
                ($target -match ('^(?i)\\\\localhost\\' + [Regex]::Escape($ShareName) + '$'))
        if (-not $ours) {
            Write-Skip "$DriveRoot is mapped to '$target' -- not this installer's mapping (looks like a real NAS mapping, e.g. on the base rig). Leaving it alone; remove the share/label leftovers below only."
        }
        elseif ($DryRun) {
            Write-Step "[dry-run] would unmap $DriveRoot ($target, $($mapping.Kind))"
            $unmapSettled = $true
        }
        else {
            # subst and net use are separate mechanisms and exactly one of
            # them can succeed, so neither exit code is the signal: re-reading
            # the device map is. An unreadable re-read counts as "still
            # mapped", which keeps the share.
            Invoke-MappingCommand "subst $DriveRoot /D" | Out-Null
            Invoke-MappingCommand "net use $DriveRoot /delete /y" "unmapped $DriveRoot" | Out-Null
            $after = Get-DriveMapping -Letter $DriveLetter
            if ($null -ne $after -and -not $after.Mapped) {
                $unmapSettled = $true
                Write-Step "unmapped $DriveRoot (was $target)"
            }
            else {
                $still = if ($null -eq $after) { "could not be re-read" } else { "still points at $($after.Target)" }
                Write-Warn2 "$DriveRoot $still after the unmap. Keeping the '$ShareName' share, because a drive letter mapped to a share that no longer exists errors on every access instead of being cleanly gone."
            }
        }
    }
}

# Is the share gone AFTER the removal attempt? Pure, and separate, because
# it is what the firewall block below is allowed to depend on
# (bug-hunt-2026-09-03 install-onboard-3): a re-read that could not be done
# counts as "still published", the same fail-safe direction the unmap re-read
# above uses. A $null share with $ReadFailed means Get-SmbShare threw, not
# that there is no share.
function Test-SmbShareGone {
    param($ShareAfter, [bool]$ReadFailed)
    if ($ReadFailed) { return $false }
    return ($null -eq $ShareAfter)
}

# the loopback share behind the labelled net-use mapping (needs admin)
$share = $null
$shareReadFailed = $false
try { $share = Get-SmbShare -Name $ShareName -ErrorAction SilentlyContinue } catch { $shareReadFailed = $true }
# What the firewall block reads. It starts as "the share is still there"
# because every path below that does NOT prove otherwise must keep the rule.
$sharePublished = $true
if ($share -and -not $unmapSettled) {
    Write-Skip "keeping SMB share ${ShareName}: $DriveRoot was not unmapped (see above). To finish by hand, run these two, in this order:"
    Write-Host "    net use $DriveRoot /delete /y"
    Write-Host "    Remove-SmbShare -Name $ShareName -Force        (administrator PowerShell)"
}
elseif ($share) {
    if ($DryRun) {
        Write-Step "[dry-run] would remove SMB share $ShareName"
        $sharePublished = $false
    }
    else {
        try {
            Remove-SmbShare -Name $ShareName -Force -Confirm:$false -ErrorAction Stop
            Write-Step "removed SMB share $ShareName"
        }
        # Targeted command, not "re-run this script elevated": an elevated
        # run of this script sees a DIFFERENT device map than the user's
        # own session, so the unmount above would silently do nothing there.
        catch { Write-Warn2 "could not remove the share ${ShareName}: $($_.Exception.Message). To clear it, open an administrator PowerShell and run:  Remove-SmbShare -Name $ShareName -Force" }
        # The removal's own success is NOT the signal: it can report success
        # and leave the share, or throw with the share already gone. Ask the
        # machine.
        $shareAfter = $null
        $afterReadFailed = $false
        try { $shareAfter = Get-SmbShare -Name $ShareName -ErrorAction SilentlyContinue } catch { $afterReadFailed = $true }
        $sharePublished = -not (Test-SmbShareGone -ShareAfter $shareAfter -ReadFailed $afterReadFailed)
    }
}
elseif ($shareReadFailed) {
    Write-Warn2 "could not read this machine's SMB shares, so '$ShareName' may still be published. Keeping the inbound-SMB block rule; check with:  Get-SmbShare -Name $ShareName"
}
else {
    Write-Skip "no SMB share: $ShareName"
    $sharePublished = $false
}

# The inbound-SMB block rule the bootstrap installs alongside that share
# (2026-08-17, COMMERCIAL_READINESS.md item 15). It goes when the share goes:
# a vendor-named firewall rule left behind after an uninstall is how a machine
# ends up with SMB quietly blocked and nobody knowing why. It also STAYS when
# the share stays (OPS-8, 2026-08-28): the rule is what scopes that share to
# this machine, so dropping it while the share is still published would widen
# the exposure of the whole project tree.
#
# The gate is "$sharePublished", i.e. the share re-read AFTER the removal
# attempt, not "we deliberately kept it" (bug-hunt-2026-09-03
# install-onboard-3). It used to be `$share -and -not $unmapSettled`, so a
# clean unmap plus a Remove-SmbShare that threw (a handle open on the tree)
# dropped the machine-wide inbound 139/445 block while the share -- the
# editor's ENTIRE project tree -- stayed published, on every network that
# machine ever joins. Nothing re-applies the rule except a re-run of the
# bootstrap.
$smbRule = $null
try { $smbRule = Get-NetFirewallRule -DisplayName $SmbFirewallRuleName -ErrorAction SilentlyContinue } catch {}
if ($smbRule -and $sharePublished) {
    Write-Skip "keeping firewall rule '$SmbFirewallRuleName': it is what keeps the '$ShareName' share reachable only from this machine, and that share is still published."
}
elseif ($smbRule) {
    if ($DryRun) { Write-Step "[dry-run] would remove firewall rule '$SmbFirewallRuleName'" }
    else {
        try {
            Remove-NetFirewallRule -DisplayName $SmbFirewallRuleName -ErrorAction Stop
            Write-Step "removed firewall rule '$SmbFirewallRuleName'"
        }
        catch { Write-Warn2 "could not remove the firewall rule '$SmbFirewallRuleName': $($_.Exception.Message). To clear it, open an administrator PowerShell and run:  Remove-NetFirewallRule -DisplayName '$SmbFirewallRuleName'" }
    }
}
else { Write-Skip "no firewall rule: $SmbFirewallRuleName" }

# Explorer label leftovers. The MountPoints2 key is Windows' own per-user
# record of a mount point and carries more than our label (shell state,
# _CommentFromDesktopINI, ...) -- deleting the whole key recursively throws
# away data this installer never created. Remove only the ONE value we wrote.
$mpKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\MountPoints2\##localhost#$ShareName"
if (Test-Path -LiteralPath $mpKey) {
    $hasLabel = $null
    try { $hasLabel = (Get-ItemProperty -LiteralPath $mpKey -Name "_LabelFromReg" -ErrorAction SilentlyContinue)._LabelFromReg } catch {}
    if ($null -eq $hasLabel) {
        Write-Skip "no _LabelFromReg value on $mpKey"
    }
    elseif ($DryRun) {
        Write-Step "[dry-run] would delete only the _LabelFromReg value under $mpKey (leaving the key itself)"
    }
    else {
        try {
            Remove-ItemProperty -LiteralPath $mpKey -Name "_LabelFromReg" -ErrorAction Stop
            Write-Step "removed the _LabelFromReg value under $mpKey (key left in place -- it is Windows', not ours)"
        }
        catch { Write-Warn2 "could not remove _LabelFromReg: $($_.Exception.Message)" }
    }
}
else { Write-Skip "no MountPoints2 entry for the $ShareName mapping" }

# The legacy DriveIcons\P key WAS created wholesale by older installs (and
# never worked), so removing the key is correct there.
$driveIconsKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\DriveIcons\$DriveLetter"
if (Test-Path -LiteralPath $driveIconsKey) {
    if ($DryRun) { Write-Step "[dry-run] would delete $driveIconsKey" }
    else {
        try { Remove-Item -LiteralPath $driveIconsKey -Recurse -Force -ErrorAction Stop; Write-Step "removed $driveIconsKey" }
        catch { Write-Warn2 "could not remove ${driveIconsKey}: $($_.Exception.Message)" }
    }
}

# --- 4. program binaries --------------------------------------------------
if (Test-Path -LiteralPath $BinDir) {
    if ($DryRun) { Write-Step "[dry-run] would delete $BinDir (rclone, syncthing, companion exe)" }
    else {
        Remove-Item -LiteralPath $BinDir -Recurse -Force -ErrorAction SilentlyContinue
        Write-Step "removed program binaries: $BinDir"
    }
}
else { Write-Skip "no bin dir: $BinDir" }

# ...and the user PATH entry windows_bootstrap.ps1 added for it. Leaving a
# dangling PATH entry behind is what makes "uninstall then reinstall" produce
# a subtly different environment from a fresh machine.
#
# Read the RAW registry value, not [Environment]::GetEnvironmentVariable:
# that expands a REG_EXPAND_SZ Path, and SetEnvironmentVariable writes back a
# plain REG_SZ, so a "%USERPROFILE%\bin" entry gets permanently rewritten to
# today's literal profile path. This script inflicts that on any machine it is
# run on -- including one the bootstrap never touched, where the loop below
# finds nothing to remove but the rewrite happens anyway.
$userPath = ""
$userPathKind = [Microsoft.Win32.RegistryValueKind]::ExpandString
try {
    $envKey = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey("Environment", $false)
    if ($envKey) {
        try {
            $raw = $envKey.GetValue("Path", "", [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
            if ($null -ne $raw) { $userPath = "$raw" }
            $kind = $envKey.GetValueKind("Path")
            if ($kind) { $userPathKind = $kind }
        }
        finally { $envKey.Close() }
    }
}
catch { $userPath = "" }

$pathParts = @($userPath -split ";")
$keptParts = @($pathParts | Where-Object { $_ -and ($_.TrimEnd("\") -ne $BinDir.TrimEnd("\")) })
if ($pathParts.Count -eq $keptParts.Count) {
    Write-Skip "$BinDir is not on the user PATH"
}
elseif ($DryRun) {
    Write-Step "[dry-run] would remove $BinDir from the user PATH"
}
else {
    try {
        if ($userPath -match '%[^%]+%') {
            # Preserve the value kind so the surviving %VAR% entries stay
            # unexpanded. No WM_SETTINGCHANGE broadcast on this path.
            $envKeyW = [Microsoft.Win32.Registry]::CurrentUser.CreateSubKey("Environment")
            try { $envKeyW.SetValue("Path", ($keptParts -join ";"), $userPathKind) }
            finally { $envKeyW.Close() }
            Write-Step "removed $BinDir from the user PATH (log off and back on to pick it up)"
        }
        else {
            [Environment]::SetEnvironmentVariable("Path", ($keptParts -join ";"), "User")
            Write-Step "removed $BinDir from the user PATH"
        }
    }
    catch { Write-Warn2 "could not update the user PATH: $($_.Exception.Message)" }
}

# --- 5. identity + settings (kept unless -Full) ---------------------------
if ($Full) {
    if (Test-Path -LiteralPath $CcsyncLocal) {
        if ($DryRun) { Write-Step "[dry-run] would delete $CcsyncLocal" }
        else {
            Remove-Item -LiteralPath $CcsyncLocal -Recurse -Force -ErrorAction SilentlyContinue
            Write-Step "removed $CcsyncLocal"
        }
    }
    else { Write-Skip "already absent: $CcsyncLocal" }

    # ~/.ccsync loses config.toml, identity.json and the log -- but NOT
    # state\. That directory holds the questions this machine has already
    # answered once and for all: state\project_prompts.json is the
    # "Project '<X>' isn't set up on the server -- set it up now?" memory.
    # Deleting it makes every prompt the editor already dismissed come back
    # on the next install, which reads as "the fix didn't work" (that is
    # exactly how the Blackmagic Proxy Generator "New Doc" prompt kept
    # coming back; seen live 2026-07-25). It contains no identity, no
    # credentials and no media -- only local caches (lane filters,
    # selection) that regenerate themselves.
    if (Test-Path -LiteralPath $CcsyncProfile) {
        $keepNames = @("state")
        $doomed = @(Get-ChildItem -LiteralPath $CcsyncProfile -Force -ErrorAction SilentlyContinue |
            Where-Object { $keepNames -notcontains $_.Name })
        foreach ($item in $doomed) {
            if ($DryRun) { Write-Step "[dry-run] would delete $($item.FullName)" }
            else { Remove-Item -LiteralPath $item.FullName -Recurse -Force -ErrorAction SilentlyContinue }
        }
        if (-not $DryRun) {
            Write-Step "removed your sign-in and settings from $CcsyncProfile ($($doomed.Count) item(s))"
        }
        if (Test-Path -LiteralPath (Join-Path $CcsyncProfile "state")) {
            Write-Step "KEPT $CcsyncProfile\state -- the prompts you have already answered stay answered after a reinstall (no identity or credentials live there)."
        }
    }
    else { Write-Skip "already absent: $CcsyncProfile" }
    Write-Warn2 "FULL uninstall: your saved sign-in and Syncthing device identity are gone. A reinstall generates a NEW device ID -- send it to the admin so they can re-approve this machine on the dashboard before anything syncs again. Your media was not touched."
    $sshKey = "$env:USERPROFILE\.ssh\ccsync_ed25519"
    if (Test-Path -LiteralPath $sshKey) {
        Write-Step "NOTE: the rclone SSH key remains at $sshKey (left in place -- delete it manually if you want it gone; the admin would then re-run setup_editor_account.py)."
    }
}
else {
    if (Test-Path -LiteralPath $SyncthingHome) {
        Write-Step "KEPT Syncthing identity: $SyncthingHome (reinstall reuses the same device ID -- no re-approval needed)"
    }
    if (Test-Path -LiteralPath $CcsyncProfile) {
        Write-Step "KEPT your sign-in and settings: $CcsyncProfile (config.toml, state)"
    }
    Write-Step "run with -Full to also remove your sign-in and Syncthing identity."
}

Write-Host ""
Write-Host "=================================================================="
Write-Step "CCSync uninstall complete$(if ($DryRun) { ' (dry run -- nothing changed)' })."
Write-Step "Tailscale / rclone / Syncthing installed as system packages were left alone; remove them from Apps & features if wanted."
Write-Host "=================================================================="
