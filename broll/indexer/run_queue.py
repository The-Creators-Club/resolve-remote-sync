"""Drive the full archive queue, stage by stage, resuming across rate limits.

Designed for a job measured in days: an account-wide rate limit WILL be hit
repeatedly, and that is normal rather than an error. `run_pipeline` raises
FatalRunError on an account-wide failure and leaves the queue untouched, so the
correct response is to wait for the reset and continue — not to fail videos.
(This was written against Claude Code session limits; since 2026-08-17 the calls
are Messages API requests, which hit the organisation's rate limits instead. The
shape of the problem, and the response to it, are identical — see
broll/docs/indexing-api.md.)

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

    python run_queue.py                  # --config defaults to private/broll/indexer/config.queue.yaml
    python run_queue.py --stages claude
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

from broll_index.claude_client import extract_reset_hint, is_rate_limited, seconds_until_reset
from broll_index.site_data import DEFAULT_QUEUE_CONFIG

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

# Ceiling on time spent in the rate-limit branch without the queue moving.
# A real session window is hours — claude_client.MAX_RESET_WAIT_S bounds a single
# parsed hint at six — so a stage that has waited this long and still cannot
# place one video is not waiting out a limit, it is stuck. Say so and stop
# instead of sleeping forever (BROLL-IDX-3, 2026-08-14). Reset whenever an
# attempt does move the queue, so a genuinely bursty multi-day run is unaffected.
MAX_LIMIT_WAIT_S = 6 * 3600

# How a child stage states that it aborted, as opposed to its progress chatter.
# The retry decision used to grep the WHOLE tee'd transcript for "429"/"rate
# limit", and parallel_claude's own progress lines print "429 videos to index"
# and "[429/2024] ... last=4291:ok" — so on a queue of that size ANY permanent
# failure (expired login, exhausted credit, a bad model name) read as a
# transient limit, and the run slept 15 minutes and relaunched, forever, burning
# a full set of concurrent auth-failing calls each time while the watchdog saw a
# live run_queue and stayed quiet (BROLL-IDX-3, 2026-08-14). Match only the line
# the child emits to explain itself:
#   * parallel_claude.py prints "claude stage aborted: <fatal>" and exits 1;
#   * the serial CLI lets FatalRunError out, so the traceback tail carries it.
_ABORT_PREFIXES = (
    "claude stage aborted:",
    "broll_index.pipeline.FatalRunError:",
    "FatalRunError:",
)


def abort_reason(out: str) -> str | None:
    """The child's own statement of why it aborted, or None if it never gave one.

    The LAST such line wins: a relaunch inside one invocation can print more
    than one, and the final word is the one that ended the stage.
    """
    reason: str | None = None
    for line in out.splitlines():
        stripped = line.strip()
        for prefix in _ABORT_PREFIXES:
            if stripped.startswith(prefix):
                reason = stripped[len(prefix):].strip()
    return reason


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
    ap.add_argument("--config", default=DEFAULT_QUEUE_CONFIG)
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
        waited_s = 0.0  # time slept on limits since the queue last moved
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

            # Only the child's own abort line decides this, never its whole
            # transcript — see _ABORT_PREFIXES (BROLL-IDX-3, 2026-08-14).
            reason = abort_reason(out)
            if reason is not None and is_rate_limited(reason):
                # Expected on a long run. The queue is intact; wait and resume.
                # Sleep until the reset the error itself names, when it names one:
                # retrying before then cannot succeed, and each attempt costs a
                # full set of concurrent calls (see RETRY_WAIT_S).
                if after < before:
                    # The attempt indexed videos before it hit the limit, so the
                    # waiting is working; don't count it against the ceiling.
                    waited_s = 0.0
                hint = extract_reset_hint(reason)
                wait = seconds_until_reset(hint)
                if wait is not None:
                    log.info("[%s] rate limited — resets %s, sleeping %.0f min, "
                             "queue untouched", label, hint, wait / 60)
                else:
                    wait = RETRY_WAIT_S
                    log.info("[%s] rate limited — no usable reset time%s, "
                             "waiting %d min, queue untouched",
                             label, f" in {hint!r}" if hint else "", wait // 60)
                if waited_s >= MAX_LIMIT_WAIT_S:
                    # Checked BEFORE adding this wait, so the first one is always
                    # taken however long the reset hint asks for.
                    log.error("[%s] waited %.1f h on rate limits without placing a "
                              "single video; stopping rather than sleeping on. Last "
                              "abort: %s", label, waited_s / 3600, reason)
                    return 1
                waited_s += wait
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
