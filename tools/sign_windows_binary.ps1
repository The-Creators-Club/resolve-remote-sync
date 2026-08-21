#requires -Version 5.1
<#
.SYNOPSIS
    Authenticode-sign ONE Windows binary with this rig's (or this runner's)
    configured signing identity. The single signtool call site.

.DESCRIPTION
    Factored out of tools/release.ps1 on 2026-08-21 (installer-onboard-tools-1).
    Until then release.ps1 was the ONLY thing in the repo that ever invoked
    signtool, and it signed companion\dist\ccsync-companion.exe and nothing
    else -- so onboard.exe, the binary a FRESH INSTALL actually double-clicks
    from the dashboard's [ INSTALLER ] link, shipped unsigned even once a
    certificate existed. That is precisely the "Windows protected your PC on
    first contact" case the certificate is bought to remove, and the manifest
    honestly recorded signed_binary=0 while no gate and no drift line said so.

    Two DIFFERENT signatures matter in this repo and they are not substitutes
    (COMMERCIAL_READINESS.md item 4):
      * the RELEASE RECORD signature (tools/sign_release.py, ed25519, offline
        key) stops the fleet installing a build the vendor did not make;
      * this one, Authenticode, stops SmartScreen and lets an enterprise
        allowlist the binary.

    Identity comes from the environment, exactly as release.ps1 read it:
      CCSYNC_SIGN_THUMBPRINT          SHA1 of a cert in CurrentUser\My
      CCSYNC_SIGN_PFX + _PASSWORD     a .pfx on disk
      CCSYNC_SIGN_TIMESTAMP_URL       optional RFC3161 override. A timestamp
                                      is not optional in substance: without
                                      one every signature goes invalid the day
                                      the certificate expires.

    NEVER FATAL WHEN NO IDENTITY IS CONFIGURED. Refusing would mean nobody can
    build anything until a certificate is bought. The caller records
    signed_binary=false, sign_release.py signs THAT into the record, and
    tools\ship.ps1 refuses -MakeCurrent without -AllowUnsignedBinary. A
    signtool that RAN and FAILED is a different matter and exits 1.

.PARAMETER Path
    The binary to sign.

.PARAMETER Quiet
    Suppress the per-file progress lines (the failure lines still print).

.OUTPUTS
    Exit code 0 = signed, or not attempted because no identity is configured
    (the caller decides what that means). Exit code 1 = signtool ran and
    failed, or the file is missing. The Authenticode status itself is NOT
    inferred from the exit code: callers read Get-AuthenticodeSignature, so a
    revoked or untrusted certificate cannot be reported as a good build.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Path,
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"

function Write-SignStep { param([string]$m) if (-not $Quiet) { Write-Host "[sign] $m" } }
function Write-SignWarn { param([string]$m) Write-Host "[sign] WARNING: $m" -ForegroundColor Yellow }

$SignThumbprint = "$env:CCSYNC_SIGN_THUMBPRINT".Trim()
$SignPfx = "$env:CCSYNC_SIGN_PFX".Trim()
$SignPfxPassword = "$env:CCSYNC_SIGN_PFX_PASSWORD"
$SignTimestampUrl = "$env:CCSYNC_SIGN_TIMESTAMP_URL".Trim()
if (-not $SignTimestampUrl) { $SignTimestampUrl = "http://timestamp.digicert.com" }

function Find-SignTool {
    $cmd = Get-Command signtool.exe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    # The SDK does not put signtool on PATH. Newest x64 build first.
    $roots = @("${env:ProgramFiles(x86)}\Windows Kits\10\bin", "$env:ProgramFiles\Windows Kits\10\bin")
    foreach ($root in $roots) {
        if (-not (Test-Path -LiteralPath $root)) { continue }
        $found = Get-ChildItem -Path $root -Filter signtool.exe -Recurse -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -match '\\x64\\' } |
            Sort-Object FullName -Descending | Select-Object -First 1
        if ($found) { return $found.FullName }
    }
    return ""
}

if (-not (Test-Path -LiteralPath $Path)) {
    Write-Host "[sign] FAILED: no file at $Path" -ForegroundColor Red
    exit 1
}

if (-not $SignThumbprint -and -not $SignPfx) {
    Write-SignStep "not signing $(Split-Path -Leaf $Path): no CCSYNC_SIGN_THUMBPRINT and no CCSYNC_SIGN_PFX in the environment"
    exit 0
}

$signtool = Find-SignTool
if (-not $signtool) {
    Write-SignWarn "signtool.exe not found (install the Windows 10/11 SDK 'Signing Tools' feature) -- $(Split-Path -Leaf $Path) is NOT signed"
    exit 0
}

$signArgs = @("sign", "/fd", "sha256", "/tr", $SignTimestampUrl, "/td", "sha256")
if ($SignThumbprint) {
    $signArgs += @("/sha1", $SignThumbprint)
}
else {
    $signArgs += @("/f", $SignPfx)
    if ($SignPfxPassword) { $signArgs += @("/p", $SignPfxPassword) }
}
$signArgs += $Path
Write-SignStep "signing $(Split-Path -Leaf $Path) with signtool ($(if ($SignThumbprint) { "thumbprint $SignThumbprint" } else { "pfx $SignPfx" }))..."
# NOT through a 2>&1 pipe: the password would end up in a transcript.
# signtool prints its own progress.
& $signtool @signArgs | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[sign] FAILED: signtool exited $LASTEXITCODE for $Path -- the binary is NOT signed. Fix the certificate (or unset CCSYNC_SIGN_* to build unsigned deliberately)." -ForegroundColor Red
    exit 1
}
exit 0
