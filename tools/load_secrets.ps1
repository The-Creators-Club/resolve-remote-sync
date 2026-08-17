#requires -Version 5.1
<#
.SYNOPSIS
    Load this deployment's operator secrets into the CURRENT PowerShell
    session, from a DPAPI-protected file -- instead of setx.

.DESCRIPTION
    tools\ship.ps1, server\install_dashboard_app.py and the rest of the
    server-side scripts read four secrets out of the environment:

        TRUENAS_PW           the NAS admin password (SSH sudo + REST)
        SYNCTHING_API_KEY    Syncthing's GUI API key
        DASH_REPORT_TOKEN    the fleet report token the companions send
        DASH_SESSION_SECRET  dashboard login sessions

    plus, optionally, BROLL_INGEST_TOKEN and the code-signing secrets.

    THE PROBLEM WITH setx (2026-08-17, docs/COMMERCIAL_READINESS.md item 15).
    Every doc in this repo told the operator to `setx TRUENAS_PW "..."` once
    and forget it. setx writes the value in CLEAR TEXT into HKCU\Environment,
    where it:
      * stays until somebody deletes it, long after the machine stops being
        a release box;
      * is readable by any process running as that user -- including anything
        an editor's browser, a build tool or an installer runs;
      * is inherited by EVERY process the user launches from then on, so a
        NAS password ends up in the environment of Resolve, of the companion,
        and of anything they in turn spawn;
      * travels with a roaming profile, a profile backup, and any image of
        the machine.
    It also survives into `Get-ChildItem env:` output pasted into a support
    thread, which is how these things actually leak.

    WHAT THIS DOES INSTEAD. -Save prompts for each secret with Read-Host
    -AsSecureString (so it is never echoed and never lands in the PSReadLine
    history file), then writes it with ConvertFrom-SecureString. That is
    DPAPI under CurrentUser scope: the ciphertext can only be decrypted by
    THIS Windows account on THIS machine -- copying the file to another box,
    or reading it as another user, yields nothing. Dot-sourcing this script
    with no flags decrypts them into $env: for the current window only; close
    the window and they are gone.

    This is not a secrets manager and does not pretend to be. It is the
    minimum that stops a NAS admin password living in the registry forever,
    with no extra module to install. A customer running this at any scale
    should put the four values in their own vault and export them into the
    shell that runs ship (see docs/SECRETS.md).

    DOT-SOURCE IT. A child process cannot set its parent's environment:

        . .\tools\load_secrets.ps1          <- note the leading dot
        .\tools\load_secrets.ps1 -Save      <- -Save may be run normally

.PARAMETER Save
    Prompt for each secret and write the encrypted store. Existing values are
    shown as "(set)" and kept when you press Enter on an empty prompt.

.PARAMETER Path
    Where the store lives. Default %LOCALAPPDATA%\ccsync\secrets\operator.xml.

.PARAMETER Clear
    Delete the store and remove the four variables from this session.

.EXAMPLE
    .\tools\load_secrets.ps1 -Save
    . .\tools\load_secrets.ps1
    .\tools\ship.cmd
#>
[CmdletBinding()]
param(
    [switch]$Save,
    [switch]$Clear,
    [string]$Path = "$env:LOCALAPPDATA\ccsync\secrets\operator.xml"
)

# The names are here, not in the caller, so ship.ps1 and the server scripts
# cannot drift from what this stores. BROLL_INGEST_TOKEN is optional: a site
# with no b-roll mount never sets it, and a blank value must not be written
# (routes_ingest.py fails closed on an unset token, open on an empty one).
$SecretNames = @(
    "TRUENAS_PW",
    "SYNCTHING_API_KEY",
    "DASH_REPORT_TOKEN",
    "DASH_SESSION_SECRET",
    "BROLL_INGEST_TOKEN"
)

function Write-Step { param([string]$m) Write-Host "[secrets] $m" }
function Write-Warn2 { param([string]$m) Write-Host "[secrets] WARNING: $m" -ForegroundColor Yellow }

if ($Clear) {
    if (Test-Path -LiteralPath $Path) {
        Remove-Item -LiteralPath $Path -Force
        Write-Step "removed $Path"
    }
    else { Write-Step "no store at $Path" }
    foreach ($n in $SecretNames) { Remove-Item -LiteralPath "env:$n" -ErrorAction SilentlyContinue }
    Write-Step "cleared from this session"
    return
}

if ($Save) {
    $dir = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    # Inheritance off, three principals. The ciphertext is DPAPI-bound to this
    # account already, so this is belt-and-braces -- but a file another local
    # user cannot even read is one fewer thing to reason about.
    cmd /c "icacls `"$dir`" /inheritance:r /grant:r `"$env:USERDOMAIN\$env:USERNAME`":(OI)(CI)F `"*S-1-5-18`":(OI)(CI)F >nul 2>&1"

    $store = @{}
    if (Test-Path -LiteralPath $Path) {
        try { $store = Import-Clixml -LiteralPath $Path } catch { $store = @{} }
    }
    foreach ($n in $SecretNames) {
        $already = if ($store.ContainsKey($n) -and $store[$n]) { " (set -- Enter keeps it)" } else { "" }
        $secure = Read-Host -Prompt "  $n$already" -AsSecureString
        $plain = [System.Runtime.InteropServices.Marshal]::PtrToStringUni(
            [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))
        if ([string]::IsNullOrEmpty($plain)) { continue }
        # ConvertFrom-SecureString == DPAPI, CurrentUser scope. The plaintext
        # never touches the disk and never enters PSReadLine's history.
        $store[$n] = ConvertFrom-SecureString -SecureString $secure
    }
    $store | Export-Clixml -LiteralPath $Path
    cmd /c "icacls `"$Path`" /inheritance:r /grant:r `"$env:USERDOMAIN\$env:USERNAME`":(F) `"*S-1-5-18`":(F) >nul 2>&1"
    Write-Step "wrote $Path (DPAPI, this account on this machine only)"
    Write-Step "load it into a window with:  . .\tools\load_secrets.ps1"
    return
}

if (-not (Test-Path -LiteralPath $Path)) {
    Write-Warn2 "no secret store at $Path -- run: .\tools\load_secrets.ps1 -Save"
    return
}
$store = Import-Clixml -LiteralPath $Path
$loaded = @()
foreach ($n in $SecretNames) {
    if (-not $store.ContainsKey($n)) { continue }
    if (-not $store[$n]) { continue }
    $secure = ConvertTo-SecureString -String $store[$n]
    Set-Item -LiteralPath "env:$n" -Value ([System.Runtime.InteropServices.Marshal]::PtrToStringUni(
        [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)))
    $loaded += $n
}
if ($loaded.Count -eq 0) {
    Write-Warn2 "$Path decrypted but held nothing -- re-run with -Save"
}
else {
    # Names only, never values.
    Write-Step "loaded into THIS session only: $($loaded -join ', ')"
}
