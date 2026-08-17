# Build the faster-whisper sidecar environment this indexer shells out to.
#
# 2026-08-17, COMMERCIAL_READINESS.md item 14. Transcription used to require an
# environment that was not in this repo -- one operator's ~/tools/whisper, named
# as the DEFAULT of whisper.python/whisper.script -- so on any other machine the
# stage silently did nothing. This script builds it from pinned versions, and
# tools/whisper_transcribe.py is the helper it runs.
#
# It is a SEPARATE venv on purpose, not an extra of broll-indexer: ctranslate2
# pins its own CUDA runtime wheels and loads cuDNN through LoadLibrary, and
# putting that in the same interpreter as everything else is how the DLL wiring
# breaks. (`pip install -e .[transcribe]` exists for a machine that wants them
# in-process anyway -- see pyproject.toml.)
#
#   .\tools\make_whisper_env.ps1                 # GPU (default): CUDA 12 wheels
#   .\tools\make_whisper_env.ps1 -Cpu            # no NVIDIA card; int8 on CPU
#   .\tools\make_whisper_env.ps1 -Path D:\wenv   # somewhere other than .whisper-env
#
# Prints the two values to put in config.yaml. Nothing here touches config.yaml
# itself: the file is per-machine and may be mounted read-only in a container.
[CmdletBinding()]
param(
    [string]$Path = '',
    [switch]$Cpu,
    [string]$Python = '',
    [switch]$Force        # rebuild over an existing environment
)

$ErrorActionPreference = 'Stop'

# Pinned, because "whatever pip resolves today" is exactly the reproducibility
# hole this script exists to close. ctranslate2 and faster-whisper move
# together: a ctranslate2 built for a different CUDA major fails at LoadLibrary
# with a message that names no version at all.
$FasterWhisper = 'faster-whisper==1.1.1'
$CTranslate2   = 'ctranslate2==4.5.0'
# The CUDA 12 runtime wheels ctranslate2 4.5 loads on Windows. Installed
# explicitly rather than left to a torch install: this environment has no torch
# in it and should not grow one for two DLLs.
$CudaWheels    = @('nvidia-cublas-cu12==12.4.5.8', 'nvidia-cudnn-cu12==9.1.0.70')

$indexer = Split-Path -Parent $PSScriptRoot
if (-not $Path) { $Path = Join-Path $indexer '.whisper-env' }

if (Test-Path $Path) {
    if (-not $Force) {
        Write-Host "$Path already exists. Re-run with -Force to rebuild it." -ForegroundColor Yellow
        exit 1
    }
    Remove-Item -Recurse -Force $Path
}

if (-not $Python) {
    $Python = (Get-Command python.exe -ErrorAction SilentlyContinue).Source
}
if (-not $Python) {
    throw 'no python.exe found: pass -Python <path to a 3.12 interpreter>'
}

Write-Host "creating $Path with $Python ..."
& $Python -m venv $Path
if ($LASTEXITCODE -ne 0) { throw "venv creation failed ($LASTEXITCODE)" }

$venvPython = Join-Path $Path 'Scripts\python.exe'
& $venvPython -m pip install --upgrade pip | Out-Host

$packages = @($FasterWhisper, $CTranslate2)
if (-not $Cpu) { $packages += $CudaWheels }
Write-Host "installing: $($packages -join ', ')"
& $venvPython -m pip install @packages | Out-Host
if ($LASTEXITCODE -ne 0) { throw "pip install failed ($LASTEXITCODE)" }

# Import it once here rather than discovering at 2am that the DLLs do not load:
# the failure mode this guards is a successful pip install whose ctranslate2
# then cannot find cuBLAS, which only shows up on first use.
& $venvPython -c "import faster_whisper, ctranslate2; print('faster-whisper', faster_whisper.__version__, '/ ctranslate2', ctranslate2.__version__)" | Out-Host
if ($LASTEXITCODE -ne 0) { throw 'the environment installed but does not import' }

$script = Join-Path $indexer 'tools\whisper_transcribe.py'
Write-Host ''
Write-Host 'Put these in config.yaml (forward slashes are fine on Windows):' -ForegroundColor Green
Write-Host 'whisper:'
Write-Host ('  python: "{0}"' -f ($venvPython -replace '\\', '/'))
Write-Host ('  script: "{0}"' -f ($script -replace '\\', '/'))
Write-Host ''
Write-Host 'or export CCSYNC_WHISPER_PYTHON / CCSYNC_WHISPER_SCRIPT instead.'
Write-Host 'A first run downloads the model (~1.6 GB for large-v3-turbo); set'
Write-Host 'whisper.model_dir (CCSYNC_WHISPER_MODEL_DIR) to keep it somewhere durable.'
