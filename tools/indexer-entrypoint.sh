#!/usr/bin/env sh
# Entrypoint for tools/Dockerfile.indexer-gpu. Three verbs, nothing implicit.
#
# 2026-08-17, COMMERCIAL_READINESS.md item 14. Each verb is a long, expensive
# job (hours of GPU, and for `index` real money in model calls), so this
# deliberately has NO default: a container started with no arguments prints the
# usage and exits 0 rather than beginning to spend.
#
# POSIX sh, and `set -eu` without pipefail, because the base image's /bin/sh is
# dash. Kept LF-only by .gitattributes -- a CR here is read as an option
# character by dash and the container crash-loops (2026-07-26, run.sh).
set -eu

BROLL_DIR=${BROLL_INDEXER_DIR:-/app/broll/indexer}
MUSIC_DIR=${MUSIC_INDEXER_DIR:-/app/music/indexer}
# Mounted, not baked: it names the customer's shares and their roots.
CONFIG=${BROLL_CONFIG:-/config/config.yaml}

usage() {
    cat <<'EOF'
ccsync GPU indexer. Usage:

  index [args...]        b-roll: scan -> probe -> proxy -> frames -> claude -> embed
                         (broll-index run; --stages to do part of it)
  transcribe [args...]   b-roll: faster-whisper over the queue, model loaded once
  music-embed [args...]  music: decode -> CLAP -> DSP features -> tag
  drain [args...]        music: analyse the NAS ingest queue and export a result
                         bundle to apply to the live index (never a file push)
  shell                  an interactive shell in the environment
  help                   this

Mounts:
  /library   the media, read-only where the workflow allows
  /data      data_root: frames, proxies, posters, sprites, transcripts
  /index     the sqlite databases the web halves read
  /models    HuggingFace + fastembed caches (without it, every start re-downloads)
  /config    config.yaml for the b-roll indexer

Needs an NVIDIA runtime: `--gpus all`, or the compose file's
deploy.resources.reservations.devices. See docs/INDEXERS.md.
EOF
}

require_config() {
    if [ ! -f "$CONFIG" ]; then
        echo "no config at $CONFIG. Mount one at /config/config.yaml (start from" >&2
        echo "broll/indexer/config.example.yaml), or set BROLL_CONFIG." >&2
        exit 2
    fi
}

command=${1:-help}
[ $# -gt 0 ] && shift

case "$command" in
    index)
        require_config
        cd "$BROLL_DIR"
        exec broll-index --config "$CONFIG" run "$@"
        ;;
    transcribe)
        # batch_transcribe.py, not `broll-index transcribe`: it loads the model
        # ONCE for the whole queue instead of per clip, which across a real
        # archive is the difference between five hours of loading and eight
        # seconds of it (see its docstring).
        require_config
        cd "$BROLL_DIR"
        exec python batch_transcribe.py --config "$CONFIG" "$@"
        ;;
    music-embed)
        cd "$MUSIC_DIR"
        exec python index_music.py "$@"
        ;;
    drain)
        # --queue against the index named by MUSIC_DB_PATH (or --db). Pair it
        # with --export-drain: pushing the drained FILE back over the live one
        # discards everything queued while this ran.
        cd "$MUSIC_DIR"
        exec python index_music.py --queue "$@"
        ;;
    shell)
        exec /bin/sh "$@"
        ;;
    help|-h|--help)
        usage
        ;;
    *)
        echo "unknown command: $command" >&2
        usage >&2
        exit 2
        ;;
esac
