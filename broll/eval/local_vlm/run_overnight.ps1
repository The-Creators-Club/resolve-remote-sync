<#
.SYNOPSIS
  Detached overnight launcher for the local-VLM eval on the base rig.

  powershell -NoProfile -ExecutionPolicy Bypass -File broll\eval\local_vlm\run_overnight.ps1
      -> spawns itself hidden (-Worker) and returns; the worker survives this shell.
  Flags: -Limit N (clips per arm, for a rehearsal), -SkipWait (do not wait for the GPU),
         -Foreground (run in this console instead of detaching).

  The worker:
   1. WAITS (poll 60 s, up to 8 h) until nvidia-smi shows >= 6 GB free AND no Resolve.exe
      is running -- Resolve holds ~9 of the 3080's 10 GB while open; the operator closes it
      when they leave. Every poll is logged ("waiting for Resolve to close").
   2. Runs arm A and B on all clips, arm C on 25, then score.py -> results\report.md.
   3. Everything goes to broll\eval\local_vlm\results\ (run.log, <arm>.jsonl, report.md,
      summary.json, DONE). A lock file stops a second launch. llama-server is killed at the
      end (run_eval.py already stops its own; this is belt and braces).
  Nothing here touches the indexer's config, DB or the archive; frames are read from
  E:\broll-queue\sheets read-only via clips.json.
#>
[CmdletBinding()]
param(
    [switch]$Worker,
    [switch]$Foreground,
    [switch]$SkipWait,
    [int]$Limit = 0,
    [int]$ClipsC = 25,
    [int]$MinFreeMB = 6000,
    [int]$MaxWaitHours = 8,
    [string]$Python = "",
    [string]$Config = "config.base-rig.json",
    [string]$ResultsDir = "results"
)

$ErrorActionPreference = "Continue"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $here
$results = Join-Path $here $ResultsDir
New-Item -ItemType Directory -Force -Path $results | Out-Null
$log = Join-Path $results "run.log"
$lock = Join-Path $results "run.lock"

if (-not $Python) {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) { $Python = $cmd.Source } else { $Python = "python" }
}

function Log([string]$msg) {
    $line = "{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
    Add-Content -Path $log -Value $line -Encoding utf8
    if ($Foreground -or -not $Worker) { Write-Host $line }
}

# ---------------------------------------------------------------- launcher
if (-not $Worker -and -not $Foreground) {
    if (Test-Path $lock) {
        $oldPid = Get-Content $lock -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($oldPid -and (Get-Process -Id $oldPid -ErrorAction SilentlyContinue)) {
            Write-Host "already running (worker pid $oldPid) -- see status.ps1"; exit 2
        }
        Remove-Item $lock -Force -ErrorAction SilentlyContinue
    }
    $args = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $MyInvocation.MyCommand.Path,
              "-Worker", "-Python", $Python, "-Config", $Config, "-ResultsDir", $ResultsDir,
              "-Limit", $Limit, "-ClipsC", $ClipsC, "-MinFreeMB", $MinFreeMB, "-MaxWaitHours", $MaxWaitHours)
    if ($SkipWait) { $args += "-SkipWait" }
    $p = Start-Process -FilePath "powershell.exe" -ArgumentList $args -WindowStyle Hidden -PassThru
    Write-Host ("launched detached worker pid {0}; log: {1}" -f $p.Id, $log)
    Write-Host "progress: powershell -NoProfile -ExecutionPolicy Bypass -File $here\status.ps1"
    exit 0
}

# ------------------------------------------------------------------ worker
Set-Content -Path $lock -Value $PID -Encoding ascii
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUNBUFFERED = "1"
Log "worker start pid=$PID python=$Python config=$Config limit=$Limit clipsC=$ClipsC"

function GpuFreeMB {
    try {
        $out = & nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits 2>$null
        return [int](($out | Select-Object -First 1).Trim())
    } catch { return -1 }
}
function ResolveRunning { return [bool](Get-Process -Name "Resolve" -ErrorAction SilentlyContinue) }

if (-not $SkipWait) {
    $deadline = (Get-Date).AddHours($MaxWaitHours)
    while ($true) {
        $free = GpuFreeMB
        $res = ResolveRunning
        if ($free -ge $MinFreeMB -and -not $res) { Log "GPU free ${free} MB, Resolve not running -> go"; break }
        if ((Get-Date) -gt $deadline) {
            Log "gave up waiting after $MaxWaitHours h (GPU free ${free} MB, Resolve running=$res)"
            Remove-Item $lock -Force -ErrorAction SilentlyContinue
            exit 3
        }
        if ($res) { Log "waiting for Resolve to close (GPU free ${free} MB)" }
        else { Log "waiting for GPU memory (${free} MB free < ${MinFreeMB})" }
        Start-Sleep -Seconds 60
    }
}

function RunStep([string]$label, [string[]]$argv) {
    Log ("== {0}: {1} {2}" -f $label, $Python, ($argv -join " "))
    $t0 = Get-Date
    & $Python @argv 2>&1 | ForEach-Object { Add-Content -Path $log -Value ("    " + $_) -Encoding utf8 }
    $code = $LASTEXITCODE
    Log ("== {0} exit {1} after {2:n0} min" -f $label, $code, ((Get-Date) - $t0).TotalMinutes)
    return $code
}

$limitArgs = @()
if ($Limit -gt 0) { $limitArgs = @("--limit", $Limit) }
$cLimit = $ClipsC
if ($Limit -gt 0 -and $Limit -lt $ClipsC) { $cLimit = $Limit }

$codes = @{}
$codes["A"] = RunStep "arm A" (@("run_eval.py", "--arm", "A", "--config", $Config, "--results-dir", $results) + $limitArgs)
$codes["B"] = RunStep "arm B" (@("run_eval.py", "--arm", "B", "--config", $Config, "--results-dir", $results) + $limitArgs)
$codes["C"] = RunStep "arm C" @("run_eval.py", "--arm", "C", "--config", $Config, "--results-dir", $results, "--limit", $cLimit)
$codes["score"] = RunStep "score" @("score.py", "--results-dir", $results)

# belt and braces: run_eval stops its own server; make sure nothing is left holding the GPU
Get-Process -Name "llama-server" -ErrorAction SilentlyContinue | ForEach-Object {
    Log ("killing leftover llama-server pid {0}" -f $_.Id); Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
}
$summary = ($codes.GetEnumerator() | ForEach-Object { "{0}={1}" -f $_.Key, $_.Value }) -join " "
Log "ALL DONE ($summary). report: $results\report.md"
Set-Content -Path (Join-Path $results "DONE") -Value ((Get-Date -Format "s") + " " + $summary) -Encoding utf8
Remove-Item $lock -Force -ErrorAction SilentlyContinue
