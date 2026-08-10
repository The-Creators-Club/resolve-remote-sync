# Restart the archive indexing run if it is not alive.
#
# Three runs on 2026-07-22 died because they were launched in the foreground of
# a session that later ended, and nothing noticed for fourteen hours. Windows is
# also free to reboot for updates between 1am and 9am (active hours are 9-1),
# which is exactly the window an overnight run needs.
#
# Safe to fire blindly: run_queue.py commits per video and resumes from wherever
# it stopped, so a spurious start costs nothing. Runs NON-elevated on purpose --
# the claude CLI's credentials are user-scoped, and an elevated process gets a
# different token that cannot see the mapped share drives.
#
#   .\watchdog.ps1                    # what the scheduled task runs
#   .\watchdog.ps1 -DryRun -Force     # exercise the restart path while a run is live
param(
    [switch]$DryRun,   # do everything except actually launch
    [switch]$Force     # skip the "already running" check
)

$ErrorActionPreference = 'Stop'
$log     = 'E:\broll-queue\watchdog.log'
$indexer = 'E:\Projects\broll-platform\indexer'
$python  = 'C:\Users\alex\AppData\Local\Programs\Python\Python312\python.exe'
$db      = 'E:\broll-queue\broll.db'

function Write-Log($msg) {
    "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $msg" | Add-Content -Path $log -Encoding utf8
}

try {
    # Already running? Nothing to do.
    $running = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.CommandLine -and $_.CommandLine -like '*run_queue.py*' }
    if ($running -and -not $Force) {
        Write-Log "ok - run_queue alive (PID $($running.ProcessId -join ','))"
        exit 0
    }

    # Nothing left to index? Don't respawn every 30 minutes forever.
    # Reuses run_queue.remaining() rather than restating the SQL, so the
    # definition of "remaining" cannot drift from the runner's. Note the
    # FORWARD slashes: sqlite's URI mode does not treat "\" as a separator, and
    # a backslash path here silently opened something without a videos table
    # instead of failing loudly.
    Push-Location $indexer
    $out = & $python -c "import run_queue; print(run_queue.remaining('$($db -replace '\\','/')'))"
    $ok = $?
    Pop-Location

    $remaining = $null
    if ($ok -and $out) { $remaining = $out | Select-Object -Last 1 }
    if ($null -ne $remaining -and $remaining -match '^\d+$') {
        if ([int]$remaining -eq 0) {
            Write-Log 'queue complete - nothing to restart'
            exit 0
        }
    } else {
        # Fail toward keeping the run alive: a spurious start is harmless
        # (run_queue is resumable and exits in seconds with nothing to do),
        # whereas a silently dead run costs a night.
        Write-Log "could not read remaining count ($out) - restarting anyway"
        $remaining = 'unknown'
    }

    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    if ($DryRun) {
        Write-Log "DRY-RUN - would restart, $remaining videos remaining"
        exit 0
    }
    Start-Process -FilePath $python `
        -ArgumentList '-u','run_queue.py','--config','config.queue.yaml',
                      '--model','haiku','--api-workers','12' `
        -WorkingDirectory $indexer `
        -RedirectStandardOutput "E:\broll-queue\claude-$stamp.log" `
        -RedirectStandardError  "E:\broll-queue\claude-$stamp.err" `
        -WindowStyle Hidden
    Write-Log "RESTARTED - $remaining videos remaining, log claude-$stamp.log"
}
catch {
    Write-Log "watchdog error: $_"
    exit 1
}
