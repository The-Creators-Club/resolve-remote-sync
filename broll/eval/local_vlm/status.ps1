<#
.SYNOPSIS
  Progress of the overnight local-VLM eval: worker alive?, per-arm clip counts,
  GPU/Resolve state, tail of run.log.
  powershell -NoProfile -ExecutionPolicy Bypass -File broll\eval\local_vlm\status.ps1 [-Tail 20] [-ResultsDir results]
#>
param([int]$Tail = 20, [string]$ResultsDir = "results")
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$results = Join-Path $here $ResultsDir
$log = Join-Path $results "run.log"
$lock = Join-Path $results "run.lock"

$clipsTotal = 0
try {
    $cj = Get-Content (Join-Path $here "clips.json") -Raw -Encoding utf8 | ConvertFrom-Json
    $clipsTotal = @($cj.clips).Count
} catch {}

Write-Host "== local VLM eval status  ($(Get-Date -Format 'yyyy-MM-dd HH:mm:ss'))"
if (Test-Path $lock) {
    $wpid = Get-Content $lock | Select-Object -First 1
    $alive = [bool](Get-Process -Id $wpid -ErrorAction SilentlyContinue)
    Write-Host ("worker pid {0}: {1}" -f $wpid, $(if ($alive) { "RUNNING" } else { "NOT running (stale lock)" }))
} elseif (Test-Path (Join-Path $results "DONE")) {
    Write-Host ("DONE: " + (Get-Content (Join-Path $results "DONE")))
} else {
    Write-Host "no worker lock and no DONE marker (not launched, or crashed before writing anything)"
}
$srv = Get-Process -Name "llama-server" -ErrorAction SilentlyContinue
Write-Host ("llama-server: {0}" -f $(if ($srv) { "running (pid " + ($srv.Id -join ",") + ")" } else { "not running" }))
try {
    $free = (& nvidia-smi --query-gpu=memory.free,memory.used --format=csv,noheader,nounits) -join ""
    Write-Host "GPU free/used MB: $free"
} catch { Write-Host "nvidia-smi: n/a" }
Write-Host ("Resolve.exe: {0}" -f $(if (Get-Process -Name Resolve -ErrorAction SilentlyContinue) { "RUNNING" } else { "not running" }))

foreach ($arm in "A", "B", "C") {
    $f = Join-Path $results "$arm.jsonl"
    if (Test-Path $f) {
        $lines = @(Get-Content $f -Encoding utf8 | Where-Object { $_.Trim() })
        $ok = @($lines | Where-Object { $_ -match '"status": "ok"' }).Count
        $target = if ($arm -eq "C") { [Math]::Min(25, $clipsTotal) } else { $clipsTotal }
        Write-Host ("arm {0}: {1}/{2} clips recorded ({3} fully ok)" -f $arm, $lines.Count, $target, $ok)
    } else {
        Write-Host ("arm {0}: not started" -f $arm)
    }
}
foreach ($f in "report.md", "summary.json") {
    $p = Join-Path $results $f
    if (Test-Path $p) { Write-Host ("{0}: {1} ({2:n0} KB)" -f $f, (Get-Item $p).LastWriteTime, ((Get-Item $p).Length / 1KB)) }
}
if (Test-Path $log) {
    Write-Host "-- tail of run.log:"
    Get-Content $log -Tail $Tail -Encoding utf8
} else {
    Write-Host "no run.log yet"
}
