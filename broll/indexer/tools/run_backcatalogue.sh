#!/usr/bin/env bash
# Unattended back-catalogue ingest: FF2 + Disinformation + WCT Event Doc.
#
# Written 2026-08-19 for the three projects added to config.queue.yaml that
# day. Ordered rather than parallel on purpose -- every phase here contends for
# the same single GPU, and two phases sharing it is slower than either alone:
# the encodes saturate NVENC, the describe stage wants the SM and 5 GB of VRAM.
#
# Every step is resumable and idempotent, so killing this script and re-running
# it costs at most the one clip that was in flight. That is the whole reason it
# is a flat list of commands and not a state machine.
#
#   bash tools/run_backcatalogue.sh          # from broll/indexer
#
# Progress lands in run_backcatalogue.log; each phase also leaves its own
# ledger (proxy-prepass-*.jsonl) that survives a restart.
set -u

cd "$(dirname "$0")/.." || exit 1
export PYTHONIOENCODING=utf-8
CFG="../../private/broll/indexer/config.queue.yaml"
LOG="run_backcatalogue.log"

FF2_ROOT="Q:/FF2"
DIS_ROOT="R:/Project Backups/NAS Backup Projects-2023/Disinformation"
WCT_ROOT="R:/Project Backups/NAS Backup Projects-2022/2022/WCT Event Doc"

say() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

# 5 concurrent NVENC sessions measured at ~7 clips/min against 1.8 at 2, with
# the encoder block at 96% and no verification failures. Higher is not worth
# testing: the block is already saturated, and concurrent NVENC is exactly what
# produces the silently-damaged bitstreams verify_decodes exists to catch.
WORKERS=5

say "=== phase 1/6: encode missing proxies (FF2)"
python tools/make_own_proxies.py --root "$FF2_ROOT"  --preset ff2 \
       --apply --workers "$WORKERS" >>"$LOG" 2>&1

say "=== phase 2/6: encode missing proxies (Disinformation)"
python tools/make_own_proxies.py --root "$DIS_ROOT" --preset disinfo \
       --apply --workers "$WORKERS" >>"$LOG" 2>&1

say "=== phase 3/6: encode missing proxies (WCT Event Doc)"
python tools/make_own_proxies.py --root "$WCT_ROOT" --preset wct \
       --apply --workers "$WORKERS" >>"$LOG" 2>&1

# A .partial is an encode that was interrupted. Its clip has no proxy, so the
# next run of the pre-pass redoes it -- but leaving the stub inside a Proxy/
# folder puts a zero-value file in the tree the archive build later walks.
say "=== cleaning interrupted .partial stubs"
find "$FF2_ROOT" "$DIS_ROOT" "$WCT_ROOT" -name "*.mp4.partial" -delete 2>/dev/null

say "=== phase 4/6: scan the three shares"
for pair in "ff2|$FF2_ROOT" "disinfo|$DIS_ROOT" "wct|$WCT_ROOT"; do
    share="${pair%%|*}"; root="${pair#*|}"
    say "  scan $share"
    python -m broll_index.cli --config "$CFG" scan --share "$share" --root "$root" >>"$LOG" 2>&1
done

# probe -> proxy -> frames. CPU/ffmpeg work, so it wants many more workers than
# the NVENC phases above; the 540p browsing proxy it makes is a different file
# from the 1080p editor proxy phase 1-3 wrote, and lives in data_root.
say "=== phase 5/6: local stages (probe, proxy, frames)"
python parallel_local.py --workers 8 >>"$LOG" 2>&1

# The Qwen3-VL pass. Measured ~20 s/clip on this 3080 (broll/docs/
# indexing-local.md), and it wants ~5 GB of VRAM -- Resolve open would take
# 9.3 of the card's 10 GB and starve it, so keep Resolve closed while this runs.
say "=== phase 6/6: describe (Qwen3-VL local) then embed"
python -m broll_index.cli --config "$CFG" run --stages claude >>"$LOG" 2>&1
python -m broll_index.cli --config "$CFG" run --stages embed  >>"$LOG" 2>&1

say "=== DONE"
python - <<'PY' 2>&1 | tee -a "$LOG"
import sqlite3
c = sqlite3.connect("E:/broll-queue/broll.db")
for r in c.execute("select share, status, count(*) from videos "
                   "where share in ('ff2','disinfo','wct') group by share, status "
                   "order by share, status"):
    print("  %-10s %-12s %d" % r)
PY
