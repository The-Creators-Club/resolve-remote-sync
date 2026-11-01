<#
.SYNOPSIS
    GL-27 and GL-28 (CR-372, 2026-10-07): the ~/.ccsync permissions fix and
    the pinned-first rclone/Syncthing install.

.DESCRIPTION
    GL-27: Protect-CCSyncPath ran `icacls <dir> /inheritance:r` with no
    (OI)(CI), which left every file and folder already inside the directory
    with an empty permission list. This test runs the script's OWN functions
    (taken from the AST) against a real sandbox that already holds a child
    file and a child folder, the exact shape of a real install, and asserts the
    children are readable and writable afterwards, and that a machine an OLD
    build already damaged is repaired.

    GL-28: structural checks, since winget and the network cannot run here:
    the pinned download is attempted before winget, a winget "success" is only
    trusted once an exe is located, Syncthing resolves our own copy before a
    versioned winget package folder, and the seeded config carries the
    absolute rclone path.

    Run:  powershell -NoProfile -ExecutionPolicy Bypass -File installer\tests\Test-StateAclAndWinget.ps1
#>
$ErrorActionPreference = "Stop"
$InstallerDir = Split-Path -Parent $PSScriptRoot
$Bootstrap = Join-Path $InstallerDir "windows_bootstrap.ps1"
$Upgrade = Join-Path $InstallerDir "windows_upgrade.ps1"

$fail = 0
function Ok  { param([string]$m) Write-Host "  PASS  $m" -ForegroundColor DarkGreen }
function Bad { param([string]$m) Write-Host "  FAIL  $m" -ForegroundColor Red; $script:fail++ }

function Get-Function {
    param([string]$Path, [string]$Name)
    $tokens = $null; $errors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseFile($Path, [ref]$tokens, [ref]$errors)
    if ($errors -and $errors.Count -gt 0) { Write-Host "FAIL: $Path does not parse" -ForegroundColor Red; exit 1 }
    $fn = $ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] }, $true) |
        Where-Object { $_.Name -eq $Name } | Select-Object -First 1
    if (-not $fn) { Write-Host "FAIL: $Path no longer defines $Name" -ForegroundColor Red; exit 1 }
    return $fn.Extent.Text
}

$DryRun = $false
function Write-Step  { param([string]$m) }
function Write-Warn2 { param([string]$m) Write-Host "    warn: $m" -ForegroundColor Yellow }

Invoke-Expression (Get-Function $Bootstrap "Protect-CCSyncPath")
Invoke-Expression (Get-Function $Bootstrap "Repair-CCSyncStateAcl")

$TempRoot = (Get-Item -LiteralPath $env:TEMP -Force).FullName
$Sandbox = Join-Path $TempRoot "ccsync-test-stateacl"

function New-Sandbox {
    if (Test-Path -LiteralPath $Sandbox) { Remove-Item -LiteralPath $Sandbox -Recurse -Force }
    New-Item -ItemType Directory -Path (Join-Path $Sandbox "state") -Force | Out-Null
    Set-Content -LiteralPath (Join-Path $Sandbox "eula_accepted.json") -Value "{}"
    Set-Content -LiteralPath (Join-Path $Sandbox "state\sync_halt.json") -Value "{}"
}
function Test-Writable {
    param([string]$Path)
    try { Add-Content -LiteralPath $Path -Value " " -ErrorAction Stop; return $true } catch { return $false }
}

try {
    # --- the fixed Protect-CCSyncPath, with children that already exist -----
    New-Sandbox
    Protect-CCSyncPath -Path $Sandbox
    $eula = Join-Path $Sandbox "eula_accepted.json"
    $latch = Join-Path $Sandbox "state\sync_halt.json"
    if ((Test-Writable $eula) -and (Test-Writable $latch)) {
        Ok "children that existed before Protect-CCSyncPath stay writable"
    } else { Bad "a pre-existing child became unwritable after Protect-CCSyncPath (the GL-27 bug)" }
    Set-Content -LiteralPath (Join-Path $Sandbox "state\new.json") -Value "{}"
    Ok "a file created afterwards inside a pre-existing subfolder works"

    # --- a machine an OLD build already damaged ------------------------------
    New-Sandbox
    $me = "$env:USERDOMAIN\$env:USERNAME"
    cmd /c "icacls `"$Sandbox`" /inheritance:r /grant:r `"$me`":(F) `"*S-1-5-18`":(F) `"*S-1-5-32-544`":(F) >nul 2>&1"
    if (-not (Test-Writable $latch)) {
        Ok "reproduced: the OLD command leaves an existing child unwritable"
        Repair-CCSyncStateAcl -Dir $Sandbox
        if ((Test-Writable $eula) -and (Test-Writable $latch)) {
            Ok "Repair-CCSyncStateAcl makes the damaged children writable again"
        } else { Bad "Repair-CCSyncStateAcl did not repair the damaged children" }
    } else {
        Write-Host "  SKIP  this Windows build did not reproduce the lock; repair case not asserted" -ForegroundColor DarkGray
    }

    # --- the folder itself must stay restricted ------------------------------
    $acl = (cmd /c "icacls `"$Sandbox`"") -join "`n"
    if ($acl -match "Everyone|BUILTIN\\Users|Authenticated Users") {
        Bad "the repaired folder grants a broad group: $acl"
    } else { Ok "the repaired folder is still restricted to the owner, SYSTEM and Administrators" }
}
finally {
    if (Test-Path -LiteralPath $Sandbox) { Remove-Item -LiteralPath $Sandbox -Recurse -Force -ErrorAction SilentlyContinue }
}

# --- structure: the bootstrap and the upgrade both carry the repair ----------
$bt = Get-Content -LiteralPath $Bootstrap -Raw -Encoding UTF8
$ut = Get-Content -LiteralPath $Upgrade -Raw -Encoding UTF8
if ($bt -match 'Repair-CCSyncStateAcl -Dir \$CCSyncConfigDir') { Ok "the bootstrap repairs ~/.ccsync" } else { Bad "the bootstrap never calls the repair on ~/.ccsync" }
if ($ut -match 'Repair-CCSyncStateAcl -Dir "\$env:USERPROFILE\\\.ccsync"') { Ok "windows_upgrade.ps1 repairs ~/.ccsync" } else { Bad "windows_upgrade.ps1 does not repair ~/.ccsync" }
if ($ut -match '\(OI\)\(CI\)') { Ok "the upgrade's grant is inheritable" } else { Bad "the upgrade's grant lacks (OI)(CI)" }

# --- GL-28 ---------------------------------------------------------------------
$rcloneInstall = $bt.IndexOf('Install-PinnedBinary -What "rclone"')
$rcloneWinget = $bt.IndexOf('winget install --id Rclone.Rclone')
if ($rcloneInstall -gt 0 -and $rcloneWinget -gt $rcloneInstall) { Ok "rclone: the pinned download is tried before winget" } else { Bad "rclone: winget is not behind the pinned download" }
$stInstall = $bt.IndexOf('Install-PinnedBinary -What "Syncthing"')
$stWinget = $bt.IndexOf('winget install --id Syncthing.Syncthing')
if ($stInstall -gt 0 -and $stWinget -gt $stInstall) { Ok "Syncthing: the pinned download is tried before winget" } else { Bad "Syncthing: winget is not behind the pinned download" }
if ($bt -match 'Update-SessionPathFromRegistry' -and $bt -match 'WinGet\\Links') { Ok "a winget install is followed by a PATH refresh and a WinGet\Links probe" } else { Bad "no PATH refresh / Links probe after winget" }
if ($bt -match "rclone_path = '\`$RcloneConfigPath'") { Ok "the seeded config carries the located rclone path" } else { Bad "the seeded config still says rclone_path = rclone" }

# Syncthing resolution: ours first, never a versioned winget package folder.
$BinDir = Join-Path $TempRoot "ccsync-test-bin"
try {
    New-Item -ItemType Directory -Path $BinDir -Force | Out-Null
    Invoke-Expression (Get-Function $Bootstrap "Get-SyncthingExePath")
    Set-Content -LiteralPath (Join-Path $BinDir "syncthing.exe") -Value "MZ"
    $got = Get-SyncthingExePath
    if ($got -eq (Join-Path $BinDir "syncthing.exe")) { Ok "Get-SyncthingExePath prefers the pinned copy in the bin dir" } else { Bad "Get-SyncthingExePath returned $got" }
}
finally { if (Test-Path -LiteralPath $BinDir) { Remove-Item -LiteralPath $BinDir -Recurse -Force -ErrorAction SilentlyContinue } }

# CR-372 overseer defects 1-3: a versioned winget folder is never "installed",
# and the existing config's bare rclone_path is repaired.
$FakeLocal = Join-Path $TempRoot "ccsync-test-local"
$BinDir = Join-Path $TempRoot "ccsync-test-bin2"
$savedLocal = $env:LOCALAPPDATA; $savedPath = $env:Path
try {
    $pkgDir = Join-Path $FakeLocal "Microsoft\WinGet\Packages\Syncthing.Syncthing_x\syncthing-windows-amd64-v2.1.2"
    New-Item -ItemType Directory -Path $pkgDir, $BinDir -Force | Out-Null
    Set-Content -LiteralPath (Join-Path $pkgDir "syncthing.exe") -Value "MZ"
    $env:LOCALAPPDATA = $FakeLocal
    $env:Path = "$pkgDir;$env:Path"
    Invoke-Expression (Get-Function $Bootstrap "Test-WingetVersionedPath")
    Invoke-Expression (Get-Function $Bootstrap "Get-SyncthingExePath")
    $got = Get-SyncthingExePath
    if (-not $got) { Ok "a syncthing.exe only under WinGet\Packages is not returned as installed" } else { Bad "versioned winget path returned as installed: $got" }
    $got = Get-SyncthingExePath -AllowVersioned
    if ($got -like "*\WinGet\Packages\*") { Ok "-AllowVersioned finds it as a last resort" } else { Bad "-AllowVersioned returned $got" }
    $links = Join-Path $FakeLocal "Microsoft\WinGet\Links"
    New-Item -ItemType Directory -Path $links -Force | Out-Null
    Set-Content -LiteralPath (Join-Path $links "syncthing.exe") -Value "MZ"
    $got = Get-SyncthingExePath
    if ($got -eq (Join-Path $links "syncthing.exe")) { Ok "the stable WinGet\Links shim beats the versioned folder" } else { Bad "Links not preferred: $got" }

    # existing config repair
    Invoke-Expression (Get-Function $Bootstrap "Update-ConfigRclonePath")
    $cfg = Join-Path $TempRoot "ccsync-test-config.toml"
    $pinned = Join-Path $BinDir "rclone.exe"
    Set-Content -LiteralPath $cfg -Value "editor_name = `"x`"`r`nrclone_path = `"rclone`"`r`nlog_level = `"INFO`"`r`n"
    $r = Update-ConfigRclonePath -ConfigPath $cfg -NewPath $pinned
    $t = Get-Content -LiteralPath $cfg -Raw
    if ($r -and $t.Contains("rclone_path = '$pinned'") -and $t.Contains('log_level = "INFO"')) { Ok "an existing bare rclone_path is replaced by the pinned path" } else { Bad "bare rclone_path not repaired: $t" }
    $owner = Join-Path $BinDir "owner-rclone.exe"; Set-Content -LiteralPath $owner -Value "MZ"
    Set-Content -LiteralPath $cfg -Value "rclone_path = '$owner'`r`n"
    $r = Update-ConfigRclonePath -ConfigPath $cfg -NewPath $pinned
    if (-not $r -and (Get-Content -LiteralPath $cfg -Raw).Contains($owner)) { Ok "an owner-chosen existing path is left alone" } else { Bad "owner path was overwritten" }
    Set-Content -LiteralPath $cfg -Value "rclone_path = 'C:\gone\rclone.exe'`r`n"
    $r = Update-ConfigRclonePath -ConfigPath $cfg -NewPath $pinned
    if ($r) { Ok "a path naming a missing file is replaced" } else { Bad "dead rclone_path not replaced" }
    Set-Content -LiteralPath $cfg -Value "rclone_path = `"rclone`"`r`n"
    $r = Update-ConfigRclonePath -ConfigPath $cfg -NewPath "rclone"
    if (-not $r) { Ok "a bare fallback value never rewrites the config" } else { Bad "rewrote with bare name" }
    Set-Content -LiteralPath $cfg -Value "rclone_path = 'C:\gone\bin\rclone.exe'`r`n"
    $r = Update-ConfigRclonePath -ConfigPath $cfg -NewPath "rclone"
    if ($r -and (Get-Content -LiteralPath $cfg -Raw).Contains("rclone_path = 'rclone'")) { Ok "a dead absolute path is healed to the bare name" } else { Bad "dead absolute path kept with bare fallback" }
    Set-Content -LiteralPath $cfg -Value "rclone_path = '$owner'`r`n"
    $r = Update-ConfigRclonePath -ConfigPath $cfg -NewPath "rclone"
    if (-not $r) { Ok "a valid existing path is not replaced by the bare name" } else { Bad "valid path overwritten by bare name" }
    Remove-Item -LiteralPath $cfg -Force -ErrorAction SilentlyContinue
}
finally {
    $env:LOCALAPPDATA = $savedLocal; $env:Path = $savedPath
    foreach ($d in @($FakeLocal, $BinDir)) { if (Test-Path -LiteralPath $d) { Remove-Item -LiteralPath $d -Recurse -Force -ErrorAction SilentlyContinue } }
}
if ($bt -match 'Test-WingetVersionedPath \$RcloneConfigPath') { Ok "a versioned rclone path is never written to config" } else { Bad "config may bake a versioned rclone path" }

$dash = [string][char]0x2014
if (($bt + $ut) -match ("Write-(Step|Warn2) .*" + $dash)) { Bad "an em dash in a printed line" } else { Ok "no em dash in a printed line" }

Write-Host ""
if ($fail -gt 0) { Write-Host "$fail FAILED" -ForegroundColor Red; exit 1 }
Write-Host "all state-ACL and winget cases pass" -ForegroundColor Green
