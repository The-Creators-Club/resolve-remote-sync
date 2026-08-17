#!/usr/bin/env bash
# Progress of the Mac leg: is run_mac.sh alive, which model/arm, per-arm clip counts, tail of run.log.
#   ~/resolve-remote-sync/broll/eval/local_vlm/status_mac.sh [results-dir]
HERE="$(cd "$(dirname "$0")" && pwd)"
RESULTS="${1:-$HERE/results-mac}"
echo "== local VLM eval (Mac) status  $(date '+%Y-%m-%d %H:%M:%S')"
if [ -f "$RESULTS/run.pid" ] && kill -0 "$(cat "$RESULTS/run.pid")" 2>/dev/null; then
  echo "run_mac.sh: RUNNING (pid $(cat "$RESULTS/run.pid"))"
elif [ -f "$RESULTS/DONE" ]; then
  echo "DONE at $(cat "$RESULTS/DONE")"
else
  echo "run_mac.sh: not running (no live pid; no DONE marker)"
fi
if pgrep -x llama-server >/dev/null 2>&1; then
  echo "llama-server: running (pid $(pgrep -x llama-server | tr '\n' ' '), rss $(( $(ps -o rss= -p "$(pgrep -x llama-server | head -1)") / 1024 )) MB)"
else
  echo "llama-server: not running"
fi
echo "memory: $(top -l 1 -n 0 | grep PhysMem)"
for d in "$RESULTS"/*/; do
  [ -d "$d" ] || continue
  name="$(basename "$d")"
  for arm in A B C; do
    f="$d/$arm.jsonl"
    [ -f "$f" ] || continue
    n=$(grep -c '"id"' "$f"); ok=$(grep -c '"status": "ok"' "$f")
    echo "$name arm $arm: $n clips recorded ($ok fully ok)"
  done
  [ -f "$d/report.md" ] && echo "$name: report.md written $(date -r "$d/report.md" '+%H:%M')"
done
[ -f "$RESULTS/compare.md" ] && echo "compare.md written $(date -r "$RESULTS/compare.md" '+%Y-%m-%d %H:%M')"
if [ -f "$RESULTS/download.log" ]; then
  echo "-- download.log (last line):"; tail -c 300 "$RESULTS/download.log" | tr '\r' '\n' | tail -1; echo
fi
echo "-- tail of run.log:"
tail -n "${TAIL:-25}" "$RESULTS/run.log" 2>/dev/null
