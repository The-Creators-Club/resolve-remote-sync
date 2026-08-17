#!/usr/bin/env bash
# The Mac leg of the local-VLM eval: same harness, bigger models, Metal.
#
#   ./run_mac.sh --bundle ~/ccsync-eval-bundle.zip [--models 8b,30b,32b] [--limit N] [--q4] [--q8]
#                [--cache DIR] [--results DIR] [--clip-time-cap-32b SEC] [--skip-arms-bc]
#
# What it does, in order:
#   1. unpacks the frames bundle (make_bundle.py output) beside this script — the Mac
#      never sees E:\broll-queue; clips.json inside the bundle has a relative frames_root;
#   2. installs llama.cpp if absent: PATH llama-server, else `brew install llama.cpp`,
#      else the official macOS arm64 release tar.gz for LLAMA_TAG (pinned below, the same
#      tag as the base rig's CUDA build) into $CACHE/llama.cpp-$LLAMA_TAG;
#   3. sets the memory budget to Metal's default working-set limit (3/4 of RAM on a
#      36 GB Mac; raising it needs `sudo sysctl iogpu.wired_limit_mb`, i.e. a password)
#      and lets mac_models.py pick the largest quant of each model that fits
#      model + mmproj + KV + overhead into it (Q8_0 default for the 8B; the pick, quant
#      and source are written to <results>/<model>/pick.json); the 30B/32B files are
#      prefetched in the background while the 8B runs;
#   4. runs the models IN SEQUENCE, one llama-server at a time (run_eval.py starts and
#      stops its own; the script also kills any stray one between models):
#        8b   arm A on all clips, then arm B (all) and arm C (25)      -> results-mac/qwen3-vl-8b-<quant>/
#        30b  arm A only                                                -> results-mac/qwen3-vl-30b-a3b-<quant>/
#        32b  arm A only, LAST, with a per-clip time cap                -> results-mac/qwen3-vl-32b-<quant>/
#      then score.py per results dir (tfidf category here; re-score with --recategorize
#      on the base rig for fastembed) and compare.py across them.
#   Downloads resume (curl -C -) and their progress goes to <results>/download.log.
#
# Run it detached so a dropped SSH session cannot kill it, and keep the laptop awake:
#   cd ~/resolve-remote-sync/broll/eval/local_vlm && mkdir -p results-mac && \
#   caffeinate -i nohup nice -n 10 ./run_mac.sh --bundle ~/ccsync-eval-bundle.zip > results-mac/run.log 2>&1 &
# Progress:  tail -f ~/resolve-remote-sync/broll/eval/local_vlm/results-mac/run.log ; ./status_mac.sh
#
# bash 3.2 (macOS stock) — no associative arrays, no mapfile.
set -u
set -o pipefail

LLAMA_TAG="b10470"
LLAMA_URL="https://github.com/ggml-org/llama.cpp/releases/download/${LLAMA_TAG}/llama-${LLAMA_TAG}-bin-macos-arm64.tar.gz"
HF_BASE="https://huggingface.co"

HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"
BUNDLE=""
MODELS="8b,30b,32b"
LIMIT=0
PREFER=""
CACHE="${HOME}/.cache/ccsync-eval"
RESULTS="${HERE}/results-mac"
CAP32=900
SKIP_BC=0
CONFIG="${HERE}/config.mac.json"
PY="${PYTHON:-python3}"

while [ $# -gt 0 ]; do
  case "$1" in
    --bundle) BUNDLE="$2"; shift 2;;
    --models) MODELS="$2"; shift 2;;
    --limit) LIMIT="$2"; shift 2;;
    --q4) PREFER="q4"; shift;;
    --q8) PREFER="q8"; shift;;
    --cache) CACHE="$2"; shift 2;;
    --results) RESULTS="$2"; shift 2;;
    --clip-time-cap-32b) CAP32="$2"; shift 2;;
    --skip-arms-bc) SKIP_BC=1; shift;;
    -h|--help) sed -n '2,32p' "$0"; exit 0;;
    *) echo "unknown arg: $1" >&2; exit 2;;
  esac
done

mkdir -p "$RESULTS" "$CACHE"
DLOG="${RESULTS}/download.log"
log() { printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }
if [ "$(uname -s)" != "Darwin" ] || [ "$(uname -m)" != "arm64" ]; then
  log "refusing: this is the Apple Silicon launcher ($(uname -s) $(uname -m))"; exit 2
fi
echo $$ > "${RESULTS}/run.pid"
log "run_mac.sh start pid=$$ models=$MODELS limit=$LIMIT prefer=${PREFER:-auto} cache=$CACHE results=$RESULTS"
log "host: $(sysctl -n machdep.cpu.brand_string 2>/dev/null || echo '?'), $(( $(sysctl -n hw.memsize) / 1073741824 )) GiB, macOS $(sw_vers -productVersion), iogpu.wired_limit_mb=$(sysctl -n iogpu.wired_limit_mb 2>/dev/null || echo '?')"

# ---------------------------------------------------------------- 1. bundle
if [ -z "$BUNDLE" ]; then
  if [ -f "${HERE}/bundle/clips.json" ]; then BUNDLE="${HERE}/bundle"; else log "need --bundle <bundle.zip|dir>"; exit 2; fi
fi
if [ -d "$BUNDLE" ]; then
  BUNDLE_DIR="$BUNDLE"
else
  BUNDLE_DIR="${HERE}/bundle-mac"
  if [ ! -f "${BUNDLE_DIR}/clips.json" ]; then
    log "unzipping $BUNDLE -> $BUNDLE_DIR"
    rm -rf "$BUNDLE_DIR"; mkdir -p "$BUNDLE_DIR"
    unzip -q "$BUNDLE" -d "$BUNDLE_DIR" || { log "unzip failed"; exit 2; }
  fi
fi
CLIPS="${BUNDLE_DIR}/clips.json"
[ -f "$CLIPS" ] || { log "no clips.json in $BUNDLE_DIR"; exit 2; }
NCLIPS=$("$PY" -c "import json,sys; print(len(json.load(open(sys.argv[1]))['clips']))" "$CLIPS")
log "bundle: $CLIPS ($NCLIPS clips)"

# ------------------------------------------------------ 2. llama-server
LLAMA_SERVER="${LLAMA_SERVER:-}"
if [ -z "$LLAMA_SERVER" ] && command -v llama-server >/dev/null 2>&1; then
  LLAMA_SERVER="$(command -v llama-server)"; log "using llama-server on PATH: $LLAMA_SERVER"
fi
if [ -z "$LLAMA_SERVER" ] && [ -x "${CACHE}/llama.cpp-${LLAMA_TAG}/llama-server" ]; then
  LLAMA_SERVER="${CACHE}/llama.cpp-${LLAMA_TAG}/llama-server"
fi
if [ -z "$LLAMA_SERVER" ] && command -v brew >/dev/null 2>&1; then
  log "brew install llama.cpp"
  brew install llama.cpp && LLAMA_SERVER="$(command -v llama-server || true)"
fi
if [ -z "$LLAMA_SERVER" ]; then
  DEST="${CACHE}/llama.cpp-${LLAMA_TAG}"
  log "downloading llama.cpp ${LLAMA_TAG} macOS arm64: $LLAMA_URL"
  mkdir -p "$DEST"
  curl -L --fail --retry 5 -C - -o "${DEST}/llama.tar.gz" "$LLAMA_URL" >>"$DLOG" 2>&1 || { log "llama.cpp download failed (see $DLOG)"; exit 2; }
  tar -xzf "${DEST}/llama.tar.gz" -C "$DEST" || { log "untar failed"; exit 2; }
  FOUND="$(find "$DEST" -type f -name llama-server | head -1)"
  [ -n "$FOUND" ] || { log "no llama-server in the archive"; exit 2; }
  if [ "$FOUND" != "${DEST}/llama-server" ]; then
    cp -R "$(dirname "$FOUND")/." "$DEST/"     # keep the dylibs beside the binary
  fi
  chmod +x "${DEST}/llama-server"
  xattr -dr com.apple.quarantine "$DEST" 2>/dev/null || true
  LLAMA_SERVER="${DEST}/llama-server"
fi
log "llama-server: $LLAMA_SERVER  ($("$LLAMA_SERVER" --version 2>&1 | head -1 || echo 'version?'))"

# best effort: Pillow for the pixel exposure flags (not fatal without it)
"$PY" -c "import PIL" 2>/dev/null || { log "installing pillow (user) for pixel stats"; "$PY" -m pip install --user --quiet pillow || log "pillow install failed — quality flags will be empty on this host"; }

# ------------------------------------------------------- 3. downloads + budget
dl() { # dl <repo> <file> -> echoes the local path (resumable, safe to call twice)
  local repo="$1" file="$2" dir url
  dir="${CACHE}/models/$(echo "$repo" | tr '/' '_')"
  mkdir -p "$dir"
  url="${HF_BASE}/${repo}/resolve/main/${file}"
  if [ ! -s "${dir}/${file}" ] || [ -f "${dir}/${file}.part" ]; then
    log "downloading ${repo}/${file} -> $dir (progress in $DLOG)" >&2
    touch "${dir}/${file}.part"
    curl -L --fail --retry 8 --retry-delay 10 -C - -o "${dir}/${file}" "$url" >>"$DLOG" 2>&1 || { log "download failed: $url" >&2; return 1; }
    rm -f "${dir}/${file}.part"
    log "downloaded ${file} ($(du -h "${dir}/${file}" | cut -f1))" >&2
  fi
  echo "${dir}/${file}"
}

kill_servers() { if pkill -x llama-server 2>/dev/null; then log "killed stray llama-server"; fi; sleep 2; }

# Metal working-set budget. llama.cpp b10470 no longer logs recommendedMaxWorkingSetSize,
# and iogpu.wired_limit_mb=0 means the macOS default: 3/4 of RAM above 32 GB, 2/3 at or
# below (the 36 GB Macs report 28991 MB, 32 GB ones 22906 MB). Minus 0.5 GB margin.
MEM_GB=$("$PY" -c "import subprocess; print(int(subprocess.check_output(['sysctl','-n','hw.memsize']))/1e9)")
WIRED_MB=$(sysctl -n iogpu.wired_limit_mb 2>/dev/null || echo 0)
BUDGET_GB=$("$PY" -c "m=$MEM_GB; w=$WIRED_MB; print(round((w/1000.0 if w>0 else (m*0.75 if m>34 else m*2/3))-0.5,1))")
log "memory budget for model+mmproj+KV+overhead: ${BUDGET_GB} GB (RAM ${MEM_GB} GB, iogpu.wired_limit_mb=${WIRED_MB})"

pick_json() { "$PY" mac_models.py pick --model "$1" --budget-gb "$BUDGET_GB" --ctx 16384 ${PREFER:+--prefer $PREFER} --force; }
pf() { "$PY" -c "import json,sys
v=json.loads(sys.argv[1])
for k in sys.argv[2].split('.'): v=v[k]
print(v)" "$1" "$2"; }

# ------------------------------------------------------------- 4. run
LIMIT_ARGS=""
[ "$LIMIT" -gt 0 ] && LIMIT_ARGS="--limit $LIMIT"
CLIMIT=25; [ "$LIMIT" -gt 0 ] && [ "$LIMIT" -lt 25 ] && CLIMIT=$LIMIT
export PYTHONUNBUFFERED=1
DONE_DIRS=""
PROBED=0
PREFETCH_PID=""

run_arm() { # run_arm <arm> <resultsdir> <model> <mmproj> <label> <ctx> [extra...]
  local arm="$1" rdir="$2" model="$3" mmproj="$4" label="$5" ctx="$6" rc; shift 6
  log "== $label arm $arm -> $rdir"
  nice -n 10 "$PY" run_eval.py --arm "$arm" --clips "$CLIPS" --config "$CONFIG" \
      --llama-server "$LLAMA_SERVER" --model "$model" --mmproj "$mmproj" --model-label "$label" \
      --ctx "$ctx" --results-dir "$rdir" "$@"
  rc=$?
  log "== $label arm $arm exit $rc"
  kill_servers
  return $rc
}

for key in $(echo "$MODELS" | tr ',' ' '); do
  log "---- model $key ----"
  PICK=$(pick_json "$key") || { log "picker failed for $key"; continue; }
  REPO=$(pf "$PICK" repo); FILE=$(pf "$PICK" file); MREPO=$(pf "$PICK" mmproj.repo); MFILE=$(pf "$PICK" mmproj.file)
  if [ -n "$PREFETCH_PID" ]; then log "waiting for the background prefetch (pid $PREFETCH_PID)"; wait "$PREFETCH_PID" 2>/dev/null; PREFETCH_PID=""; fi
  MODEL_PATH=$(dl "$REPO" "$FILE") || continue
  MMPROJ_PATH=$(dl "$MREPO" "$MFILE") || continue
  if [ "$PROBED" -eq 0 ]; then
    PROBED=1
    # prefetch the OTHER models' files now, in the background, while this one runs
    OTHERS=""
    for k2 in $(echo "$MODELS" | tr ',' ' '); do [ "$k2" != "$key" ] && OTHERS="$OTHERS $k2"; done
    if [ -n "$OTHERS" ]; then
      (
        for k2 in $OTHERS; do
          P2=$(pick_json "$k2") || continue
          dl "$(pf "$P2" repo)" "$(pf "$P2" file)" >/dev/null || true
          dl "$(pf "$P2" mmproj.repo)" "$(pf "$P2" mmproj.file)" >/dev/null || true
        done
      ) &
      PREFETCH_PID=$!
      log "prefetching$OTHERS in the background (pid $PREFETCH_PID)"
    fi
  fi
  LABEL=$(pf "$PICK" label); CTX=$(pf "$PICK" ctx); RDIR="${RESULTS}/$(pf "$PICK" dir)"
  log "pick: $LABEL ($(pf "$PICK" source)) ctx=$CTX est=$(pf "$PICK" est_gb) GB budget=${BUDGET_GB} GB over_budget=$(pf "$PICK" over_budget)"
  log "files: $MODEL_PATH ($(du -h "$MODEL_PATH" | cut -f1)) + $MMPROJ_PATH ($(du -h "$MMPROJ_PATH" | cut -f1))"
  mkdir -p "$RDIR"
  echo "$PICK" > "${RDIR}/pick.json"
  EXTRA=""
  [ "$key" = "32b" ] && EXTRA="--clip-time-cap $CAP32"
  run_arm A "$RDIR" "$MODEL_PATH" "$MMPROJ_PATH" "$LABEL" "$CTX" $LIMIT_ARGS $EXTRA || log "arm A failed for $LABEL (continuing)"
  if [ "$key" = "8b" ] && [ "$SKIP_BC" -eq 0 ]; then
    run_arm B "$RDIR" "$MODEL_PATH" "$MMPROJ_PATH" "$LABEL" "$CTX" $LIMIT_ARGS || log "arm B failed for $LABEL"
    run_arm C "$RDIR" "$MODEL_PATH" "$MMPROJ_PATH" "$LABEL" "$CTX" --limit "$CLIMIT" || log "arm C failed for $LABEL"
  fi
  log "== scoring $RDIR"
  "$PY" score.py --results-dir "$RDIR" --clips "$CLIPS" || log "score failed for $RDIR"
  DONE_DIRS="$DONE_DIRS $RDIR"
done

kill_servers
if [ -n "$DONE_DIRS" ]; then
  log "== compare across:$DONE_DIRS"
  "$PY" compare.py $DONE_DIRS --out "${RESULTS}/compare.md" || log "compare failed"
fi
log "disk used by the model cache: $(du -sh "$CACHE" 2>/dev/null | cut -f1) in $CACHE (delete when done)"
log "ALL DONE. reports: ${RESULTS}/*/report.md, ${RESULTS}/compare.md"
date '+%Y-%m-%dT%H:%M:%S' > "${RESULTS}/DONE"
rm -f "${RESULTS}/run.pid"
