#!/usr/bin/env bash
# Build the faster-whisper sidecar environment this indexer shells out to.
#
# The Linux/macOS half of tools/make_whisper_env.ps1 -- same pins, same output,
# same reason (2026-08-17, COMMERCIAL_READINESS.md item 14: the environment
# transcription needs was not in this repo, it was one operator's ~/tools/
# whisper named as a default). tools/whisper_transcribe.py is the helper it runs.
#
#   ./tools/make_whisper_env.sh              # GPU (default): CUDA 12 wheels
#   ./tools/make_whisper_env.sh --cpu        # no NVIDIA card; int8 on CPU
#   ./tools/make_whisper_env.sh --path /opt/whisper-env
#
# In tools/Dockerfile.indexer-gpu the CUDA libraries come from the image, so
# --cpu is the right flag there despite the GPU: it means "do not pip-install
# the CUDA wheels", not "do not use the GPU".
set -euo pipefail

# Pinned: "whatever pip resolves today" is the reproducibility hole this script
# closes. ctranslate2 and faster-whisper move together, and a ctranslate2 built
# for another CUDA major fails at dlopen with a message naming no version.
FASTER_WHISPER="faster-whisper==1.1.1"
CTRANSLATE2="ctranslate2==4.5.0"
CUDA_WHEELS=("nvidia-cublas-cu12==12.4.5.8" "nvidia-cudnn-cu12==9.1.0.70")

indexer="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
env_path="$indexer/.whisper-env"
python_bin="${PYTHON:-python3}"
cpu_only=0
force=0

while [ $# -gt 0 ]; do
    case "$1" in
        --cpu) cpu_only=1 ;;
        --force) force=1 ;;
        --path) env_path="$2"; shift ;;
        --python) python_bin="$2"; shift ;;
        -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
    shift
done

if [ -e "$env_path" ]; then
    if [ "$force" -eq 0 ]; then
        echo "$env_path already exists. Re-run with --force to rebuild it." >&2
        exit 1
    fi
    rm -rf "$env_path"
fi

echo "creating $env_path with $python_bin ..."
"$python_bin" -m venv "$env_path"
venv_python="$env_path/bin/python"
"$venv_python" -m pip install --upgrade pip

packages=("$FASTER_WHISPER" "$CTRANSLATE2")
[ "$cpu_only" -eq 0 ] && packages+=("${CUDA_WHEELS[@]}")
echo "installing: ${packages[*]}"
"$venv_python" -m pip install "${packages[@]}"

# Import once here rather than discovering at 2am that the libraries do not
# load: pip installing successfully and ctranslate2 finding cuBLAS are two
# different questions, and the second only gets asked on first use.
"$venv_python" -c "import faster_whisper, ctranslate2; print('faster-whisper', faster_whisper.__version__, '/ ctranslate2', ctranslate2.__version__)"

cat <<EOF

Put these in config.yaml:
whisper:
  python: "$venv_python"
  script: "$indexer/tools/whisper_transcribe.py"

or export CCSYNC_WHISPER_PYTHON / CCSYNC_WHISPER_SCRIPT instead.
A first run downloads the model (~1.6 GB for large-v3-turbo); set
whisper.model_dir (CCSYNC_WHISPER_MODEL_DIR) to keep it somewhere durable.
EOF
