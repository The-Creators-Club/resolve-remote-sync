<#
.SYNOPSIS
    Table tests for the Apps & features entry (OPS-17, usability + resilience
    sweep 2026-09-03).

.DESCRIPTION
    windows_uninstall.ps1 shipped inside the editor package zip and nowhere
    else, and the wizard path never delivers that zip. So an editor onboarded
    by onboard.exe had no copy of the uninstaller, and CC Sync appeared in no
    uninstall list on the machine: to that editor, to their own IT and to the
    next reviewer of this product, a background app with a tray icon and a
    firewall rule that cannot be removed.

    windows_bootstrap.ps1 now copies the uninstaller into
    %LOCALAPPDATA%\ccsync\bin and registers an HKCU uninstall entry pointing
    at it; windows_uninstall.ps1 removes that entry BEFORE it deletes the bin
    directory the entry names.

    Both halves are exercised for real against a SCRATCH key --
    HKCU:\Software\ccsync-test\Uninstall -- which is created and deleted here
    and is not the key Windows reads. The two functions are extracted with the
    PowerShell parser rather than dot-sourced, which would run the installer.

    Run:  powershell -NoProfile -ExecutionPolicy Bypass -File installer\tests\Test-UninstallEntry.ps1
    Exits 1 on any failure.
#>
$ErrorActionPreference = "Stop"
$InstallerDir = Split-Path -Parent $PSScriptRoot

function Get-Function {
    param([string]$Path, [string]$Name)
    if (-not (Test-Path -LiteralPath $Path)) {
        Write-Host "FAIL: no $Path" -ForegroundColor Red
        exit 1
    }
    $tokens = $null
    $errors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseFile(
        $Path, [ref]$tokens, [ref]$errors)
    if ($errors -and $errors.Count -gt 0) {
        Write-Host "FAIL: $Path does not parse: $($errors[0].Message)" -ForegroundColor Red
        exit 1
    }
    $fn = $ast.FindAll({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst]
    }, $true) | Where-Object { $_.Name -eq $Name } | Select-Object -First 1
    if (-not $fn) {
        Write-Host "FAIL: $Path no longer defines $Name" -ForegroundColor Red
        exit 1
    }
    return $fn.Extent.Text
}

Invoke-Expression (Get-Function (Join-Path $InstallerDir "windows_bootstrap.ps1") "Register-UninstallEntry")
Invoke-Expression (Get-Function (Join-Path $InstallerDir "windows_uninstall.ps1") "Unregister-UninstallEntry")

$fail = 0
function Ok  { param([string]$m) Write-Host "  PASS  $m" -ForegroundColor DarkGreen }
function Bad { param([string]$m) Write-Host "  FAIL  $m" -ForegroundColor Red; $script:fail++ }
function Check {
    param([string]$Label, $Expected, $Actual)
    if ("$Expected" -eq "$Actual") { Ok $Label } else { Bad "$Label`: got '$Actual' want '$Expected'" }
}

# The scratch root. NOT the real uninstall key: nothing in this file may put a
# CC Sync entry into a developer's own Apps & features list.
$Root = "HKCU:\Software\ccsync-test\Uninstall"
$Name = "CCSync"
$Key = Join-Path $Root $Name
$BinDir = Join-Path $env:TEMP "ccsync-test-bin"
$Script = Join-Path $BinDir "windows_uninstall.ps1"

try {
    if (Test-Path -LiteralPath "HKCU:\Software\ccsync-test") {
        Remove-Item -LiteralPath "HKCU:\Software\ccsync-test" -Recurse -Force
    }
    New-Item -Path $Root -Force | Out-Null
    New-Item -ItemType Directory -Path $BinDir -Force | Out-Null
    Set-Content -LiteralPath $Script -Value "# stand-in for the real uninstaller" -Encoding UTF8

    # --- the bootstrap half ------------------------------------------------
    $registered = Register-UninstallEntry -KeyRoot $Root -KeyName $Name `
        -DisplayName "CC Sync (Acme Video)" -UninstallScript $Script `
        -Publisher "Acme Video" -Version "1.0.40" -InstallLocation $BinDir
    Check "the entry is written" $true $registered
    Check "the key exists" $true (Test-Path -LiteralPath $Key)

    $props = Get-ItemProperty -LiteralPath $Key
    # The name a person reads. It comes from the site manifest's org_name;
    # no customer's name is ever compiled into this installer (CLAUDE.md).
    Check "DisplayName is the site's brand" "CC Sync (Acme Video)" $props.DisplayName
    Check "Publisher is the site's brand" "Acme Video" $props.Publisher
    Check "DisplayVersion is the installer version" "1.0.40" $props.DisplayVersion
    Check "InstallLocation is the bin dir" $BinDir $props.InstallLocation
    # NoModify/NoRepair: the only supported change is re-running the
    # installer, so Windows must not offer buttons that do nothing.
    Check "NoModify is set" 1 $props.NoModify
    Check "NoRepair is set" 1 $props.NoRepair

    $cmd = "$($props.UninstallString)"
    if ($cmd -like "powershell.exe -NoProfile -ExecutionPolicy Bypass -File *") {
        Ok "UninstallString runs powershell -NoProfile -ExecutionPolicy Bypass"
    }
    else { Bad "UninstallString is '$cmd'" }
    # QUOTED: %LOCALAPPDATA% carries the user's name, and often a space in it.
    if ($cmd -like "*`"$Script`"") { Ok "the script path is quoted" }
    else { Bad "the script path is not quoted: $cmd" }
    if ($cmd -notmatch "-Full") { Ok "the entry does not remove the sign-in identity" }
    else { Bad "the entry passes -Full: an uninstall from Apps & features would drop the editor's identity" }

    # A re-run overwrites the ONE entry rather than adding a second.
    Register-UninstallEntry -KeyRoot $Root -KeyName $Name `
        -DisplayName "CC Sync" -UninstallScript $Script -Publisher "CC Sync" `
        -Version "1.0.41" -InstallLocation $BinDir | Out-Null
    Check "a re-run leaves one entry" 1 (@(Get-ChildItem -LiteralPath $Root).Count)
    Check "a re-run updates the version" "1.0.41" `
        ((Get-ItemProperty -LiteralPath $Key).DisplayVersion)
    # A vendor build with no org_name in the manifest says the product name.
    Check "with no site brand the name is the product" "CC Sync" `
        ((Get-ItemProperty -LiteralPath $Key).DisplayName)

    # An icon that is not on disk is left out rather than pointed at.
    Register-UninstallEntry -KeyRoot $Root -KeyName $Name -DisplayName "CC Sync" `
        -UninstallScript $Script -IconPath (Join-Path $BinDir "not-here.exe") | Out-Null
    Check "a missing icon is not recorded" $null `
        ((Get-ItemProperty -LiteralPath $Key).DisplayIcon)

    # --- the uninstaller half ---------------------------------------------
    Check "the entry is removed" $true (Unregister-UninstallEntry -KeyRoot $Root -KeyName $Name)
    Check "the key is gone" $false (Test-Path -LiteralPath $Key)
    # "Nothing to remove" and "removed" are the same end state: only a real
    # failure is worth telling anyone about, and a machine the bootstrap never
    # touched must not report one.
    Check "a second removal is still a success" $true `
        (Unregister-UninstallEntry -KeyRoot $Root -KeyName $Name)
    Check "a root that never existed is a success" $true `
        (Unregister-UninstallEntry -KeyRoot "HKCU:\Software\ccsync-test\nope" -KeyName $Name)
}
finally {
    if (Test-Path -LiteralPath "HKCU:\Software\ccsync-test") {
        Remove-Item -LiteralPath "HKCU:\Software\ccsync-test" -Recurse -Force
    }
    if (Test-Path -LiteralPath $BinDir) {
        Remove-Item -LiteralPath $BinDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}

Write-Host ""
if ($fail -gt 0) {
    Write-Host "$fail FAILED" -ForegroundColor Red
    exit 1
}
Write-Host "all uninstall-entry cases pass" -ForegroundColor Green
