"""Drive the full archive queue, stage by stage, resuming across rate limits.

Designed for a job measured in days on a subscription: the session limit WILL be
hit repeatedly, and that is normal rather than an error. `run_pipeline` raises
FatalRunError on an account-wide failure and leaves the queue untouched, so the
correct response is to wait for the reset and continue — not to fail videos.

Stage order matters:
  1. probe    — cheap, gets duration/fps so everything else can plan
  2. transcribe — GPU-local and free; do it early so it is done regardless of
                  how far the model-call stages get
  3. proxy    — I/O bound, no model calls
  4. frames   — CPU bound, no model calls
  5. claude   — the only rate-limited stage
  6. embed    — local, cheap, needs claude output to be useful

Everything before `claude` can run to completion without touching the API, so a
rate limit never blocks the parts that don't need it.

    python run_queue.py --config config.queue.yaml
    python run_queue.py --config config.queue.yaml --stages claude
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

from broll_index.claude_client import extract_reset_hint, seconds_until_reset

LOCAL_STAGES = ["probe", "transcribe", "proxy", "frames"]
API_STAGES = ["claude"]
POST_STAGES = ["embed"]

# The local stages are run by parallel_local.py, not by the serial CLI: one
# video at a time left a 24-core machine at ~20% CPU (0.7 videos/min vs 4.7
# with workers). Running them here first also means a single overnight command
# is correct even if the local phase is unfinished — otherwise `--stages claude`
# would index only what happened to be ready and silently stop.
PARALLEL_LOCAL = Path(__file__).parent / "parallel_local.py"

# The API stage is parallelised for the same reason: measured serial throughput
# was ~20 videos/hour (~84 s per call, ~2 calls per video, one at a time), which
# is >100 h for a 2,000-video queue. It is latency-bound, not usage-bound — the
# 2026-07-21 overnight run held that flat rate for ten hours before hitting any
# limit. See parallel_claude.py.
PARALLEL_CLAUDE = Path(__file__).parent / "parallel_claude.py"

# Fallback wait when the error carries no parseable reset time.
#
# This used to be the ONLY behaviour, justified by "a wasted attempt costs one
# request". That was true while the API stage was serial. It is not true now:
# each retry relaunches the stage with --api-workers concurrent calls, so ~26
# requests go out and every one of them 429s before the parent sees the failure
# and cancels the rest. On 2026-08-02 that ran 21 times against limits whose
# reset time was printed in the error string — roughly 546 calls spent learning
# nothing, out of the same budget that had just run out.
RETRY_WAIT_S = 15 * 60


def counts(db_path: str) -> dict:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = conn.execute("SELECT status, COUNT(*) n FROM videos GROUP BY status").fetchall()
        return {s: n for s, n in rows}
    finally:
        conn.close()


def remaining(db_path: str) -> int:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM videos WHERE status IN ('discovered','probed','proxied') "
            "AND duplicate_of IS NULL"
        ).fetchone()[0]
    finally:
        conn.close()


def run_cmd(cmd: list[str]) -> tuple[int, str]:
    """Run a child stage, streaming its output live AND returning it.

    Streaming matters: the API stage runs for hours, and capture_output() held
    every line until it exited. A nine-hour run that stalled after its first
    hour looked identical to a healthy one until it finally returned, so the
    only way to see progress was to poll the database. Tee instead.
    """
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
        cwd=str(Path(__file__).parent),
    )
    lines: list[str] = []
    assert proc.stdout is not None
    for line in proc.stdout:
        sys.stdout.write(line)
        sys.stdout.flush()
        lines.append(line)
    return proc.wait(), "".join(lines)


def stage_cmd(config: Path, stages: list[str], model: str, api_workers: int,
              deadline: str | None = None) -> list[str]:
    """The command that runs `stages`.

    The claude stage goes through parallel_claude.py (N concurrent calls); every
    other stage is cheap and local, so the serial CLI is fine.
    """
    if stages == API_STAGES and api_workers > 1:
        cmd = [
            sys.executable, "-u", str(PARALLEL_CLAUDE),
            "--config", str(config), "--model", model,
            "--workers", str(api_workers),
        ]
        if deadline:
            cmd += ["--deadline", deadline]
        return cmd
    return [
        sys.executable, "-u", "-m", "broll_index.cli",
        "--config", str(config), "run",
        "--stages", ",".join(stages), "--model", model,
    ]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.queue.yaml")
    ap.add_argument("--model", default="haiku")
    ap.add_argument("--stages", default=None, help="override; default runs local then API stages")
    ap.add_argument("--max-hours", type=float, default=None)
    ap.add_argument("--workers", type=int, default=4,
                    help="parallel workers for the local phase (ignored with --stages)")
    ap.add_argument("--api-workers", type=int, default=4,
                    help="concurrent claude calls; 1 restores the old serial behaviour")
    # --max-hours can only stop BETWEEN stage invocations, and the claude stage
    # runs the whole queue in one invocation — so it cannot end a run at a
    # given time. --deadline can: the stage stops starting new videos then,
    # lets the in-flight ones finish, and goes on to the local embed stage.
    ap.add_argument("--deadline", default=None,
                    help="local ISO time (e.g. 2026-07-31T16:00:00) after which the "
                         "API stage starts no new video")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S",
        stream=sys.stdout,
    )
    log = logging.getLogger("queue")

    config = Path(args.config)
    cfg = yaml.safe_load(config.read_text(encoding="utf-8"))
    db_path = cfg["db"]["path"]

    started = time.time()
    log.info("queue start — %s", counts(db_path))

    if args.stages:
        plan = [args.stages.split(",")]
    else:
        # Local phase runs in parallel workers, then the API phase, then embed.
        rc = subprocess.run(
            [sys.executable, "-u", str(PARALLEL_LOCAL),
             "--config", str(config), "--workers", str(args.workers)],
            cwd=str(Path(__file__).parent),
        ).returncode
        log.info("local phase (parallel, %d workers) finished rc=%s — %s",
                 args.workers, rc, counts(db_path))
        plan = [API_STAGES, POST_STAGES]

    for stages in plan:
        label = ",".join(stages)
        while True:
            if args.max_hours and (time.time() - started) / 3600 >= args.max_hours:
                log.info("max-hours reached; stopping cleanly")
                return 0

            before = remaining(db_path)
            rc, out = run_cmd(
                stage_cmd(config, stages, args.model, args.api_workers, args.deadline)
            )
            after = remaining(db_path)
            tail = out.strip().splitlines()[-1] if out.strip() else ""
            log.info("[%s] rc=%s remaining %d -> %d | %s", label, rc, before, after, tail[:110])

            if rc == 0:
                break

            lowered = out.lower()
            if any(k in lowered for k in ("session limit", "rate limit", "429", "usage limit")):
                # Expected on a long run. The queue is intact; wait and resume.
                # Sleep until the reset the error itself names, when it names one:
                # retrying before then cannot succeed, and each attempt costs a
                # full set of concurrent calls (see RETRY_WAIT_S).
                hint = extract_reset_hint(out)
                wait = seconds_until_reset(hint)
                if wait is not None:
                    log.info("[%s] rate limited — resets %s, sleeping %.0f min, "
                             "queue untouched", label, hint, wait / 60)
                else:
                    wait = RETRY_WAIT_S
                    log.info("[%s] rate limited — no usable reset time%s, "
                             "waiting %d min, queue untouched",
                             label, f" in {hint!r}" if hint else "", wait // 60)
                time.sleep(wait)
                continue

            if after < before:
                # Made progress before failing: worth another pass.
                log.info("[%s] failed but progressed; retrying", label)
                continue

            log.error("[%s] failed with no progress; stopping. Last output:\n%s", label, out[-800:])
            return 1

    log.info("queue complete — %s", counts(db_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
