"""Run the `claude` (model-call) stage across many videos concurrently.

The local stages were parallelised long ago; the API stage was not, and it is
now the whole cost of the run. Measured on the real archive: ~84 s per call,
~2 calls per video, strictly serial — 20 videos/hour, i.e. >100 h for the 2,024
still queued.

The stage is LATENCY-bound, not usage-bound. The overnight run of 2026-07-21
indexed continuously for ten hours at that flat ~20/hour and only hit a session
limit at the very end, so the account had headroom the whole time and the
machine was simply waiting on one HTTP round-trip at a time.

`invoke_claude` is a stateless HTTPS request (no temp files, no shared state,
the contact sheets travel inside the request as image blocks), so N of them run
concurrently without interfering. If the extra concurrency does exhaust the
account's rate limit sooner, nothing is lost: a fatal error leaves every video's
status untouched and run_queue.py waits out the reset and resumes. So this is
either a ~4x win or throughput-neutral — it cannot be worse.

Threads, not processes (2026-08-17, COMMERCIAL_READINESS.md item 1): the work is
one HTTPS round trip per call, the `anthropic` client is thread-safe and pools
connections, and a shared process means `claude_client.set_max_concurrency` is a
real ceiling on requests in flight rather than one that each process re-applies
to itself. Each worker still opens its own sqlite connection — those are not
shareable across threads.

    python parallel_claude.py --workers 4    # --config defaults to private/broll/indexer/config.queue.yaml
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import sqlite3
import sys
import time
from datetime import datetime

from broll_index.claude_client import describe_auth, set_max_concurrency
from broll_index.config import load_config
from broll_index.pipeline import FatalRunError, _process_video
from broll_index.site_data import DEFAULT_QUEUE_CONFIG
from broll_index.storage.sqlite_backend import SqliteBackend

# 'proxied' is STAGE_PREREQ_STATUS['claude'] — a video is ready for the model
# once its proxy and contact sheets exist.
CLAUDE_PREREQ_STATUS = "proxied"


def _process_one(cfg, model: str, video_id: int,
                 deadline: float | None = None) -> tuple[int, str]:
    """Own sqlite connection per worker — connections are not thread-safe."""
    # A wall-clock stop has to be enforced HERE, at the moment a video would
    # start, rather than by killing the run: every call in flight when the axe
    # falls is a wasted request, and with a high --workers that is the whole
    # cost of stopping. Videos not yet started return instantly and stay
    # 'proxied'; videos already running finish and commit normally. The pool
    # then drains in seconds and the stage exits 0 with a real summary.
    if deadline is not None and time.time() >= deadline:
        return video_id, "deadline"

    storage = SqliteBackend(cfg.db.path)
    try:
        video = storage.get_video(video_id)
        if video is None:
            return video_id, "gone"
        if video["status"] != CLAUDE_PREREQ_STATUS:
            # Raced with another pass, or already done. Not an error.
            return video_id, "skip"
        try:
            _process_video(
                cfg, storage, video, model=model, requested_stages={"claude"},
            )
        except FatalRunError as e:
            # Account-wide (rate/session limit, credit, auth): every other
            # worker is about to fail the same way. Report it rather than
            # raising, so the parent can shut the whole run down cleanly — and
            # critically, leave this video's status untouched so it is retried.
            return video_id, f"fatal:{e}"

        # A per-video failure does NOT reach the except above. _process_video
        # catches it, calls set_error, and returns normally (pipeline.py, the
        # `else: storage.set_error(...); return` branch) — deliberately, so one
        # bad clip cannot stop the serial queue. The cost is that "returned
        # without raising" does not mean "succeeded", and reporting it as `ok`
        # made runs lie: on 2026-08-07 three passes each printed `errors 0`
        # while writing 27 failures to the database, every one of them a paid
        # call plus its retry. The database was the only place the loss showed.
        #
        # The row itself is the source of truth, so ask it rather than infer.
        final = storage.get_video(video_id)
        if final is not None and final["status"] == "error":
            return video_id, f"error:{(final['error'] or '').split(':')[0].strip() or 'claude'}"
        return video_id, "ok"
    except Exception as e:  # noqa: BLE001 - a crash must never take down the pool
        return video_id, f"crash:{e}"
    finally:
        storage.close()


def eligible_ids(db_path: str, skip_shares: "set[str] | None" = None,
                 only_shares: "set[str] | None" = None,
                 after_id: int | None = None) -> list[int]:
    """Videos ready for the model stage.

    `skip_shares` are shares configured `index: false` — our own shoots, which
    get every local stage and no paid one. Excluded here as well as in the
    pipeline so they never even appear in the run's total, rather than being
    counted, dispatched to a worker and rejected one round trip later.

    `only_shares` restricts the run to named shares. This matters whenever
    `--limit` is used: the ordering is by id, so a bare `--limit N` silently
    takes the N OLDEST queued videos, which is rarely the batch you meant when
    a new share has just been added at the end of the id range.

    `after_id` takes only ids above a cutoff, so a SECOND run can be added
    alongside one already in flight without the two fighting over the same
    clips. The queue is snapshotted once at launch, so a run started later sees
    everything the first one has not finished yet; both would dispatch those,
    and `_process_one`'s status re-check only catches the ones already committed
    — anything mid-flight gets described twice and paid for twice. Splitting on
    id is exact because the local stages advance in id order, so "what the
    running pass never saw" is precisely "ids above its highest".
    """
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        sql = "SELECT id FROM videos WHERE status = ? AND duplicate_of IS NULL"
        params: list = [CLAUDE_PREREQ_STATUS]
        if skip_shares:
            sql += f" AND share NOT IN ({', '.join('?' for _ in skip_shares)})"
            params += sorted(skip_shares)
        if only_shares:
            sql += f" AND share IN ({', '.join('?' for _ in only_shares)})"
            params += sorted(only_shares)
        if after_id is not None:
            sql += " AND id > ?"
            params.append(after_id)
        return [r[0] for r in conn.execute(sql + " ORDER BY id", params)]
    finally:
        conn.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=DEFAULT_QUEUE_CONFIG)
    ap.add_argument("--model", default="haiku")
    # 4 concurrent API calls: enough to hide most of the per-call latency
    # without turning a rate-limit hit into a thundering herd of wasted calls.
    # Each in-flight call at the moment of a limit is one wasted request, so the
    # cost of a stop scales with this number. Also becomes the client's own
    # in-flight ceiling (set_max_concurrency below).
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--share", action="append", default=None,
                    help="restrict to this share (repeatable). Pair with --limit "
                         "to index a batch of ONE share: without it, --limit takes "
                         "the lowest ids, which is the oldest queue, not the newest share")
    ap.add_argument("--deadline", default=None,
                    help="local ISO time (e.g. 2026-07-31T16:00:00) after which no "
                         "NEW video is started; those already running finish")
    ap.add_argument("--after-id", type=int, default=None,
                    help="only videos with id greater than this. Use it to add a "
                         "second run alongside one already in flight: pass the "
                         "running pass's highest id and the two sets cannot overlap")
    args = ap.parse_args()

    deadline = None
    if args.deadline:
        # Parsed here, in the parent, and passed to workers as an epoch float:
        # a naive local datetime means the same instant in every process, and
        # no worker has to re-parse or agree on a timezone.
        deadline = datetime.fromisoformat(args.deadline).timestamp()

    cfg = load_config(args.config)
    SqliteBackend(cfg.db.path).close()  # ensure schema before workers open it
    print(describe_auth(cfg.anthropic), flush=True)
    # The pool size is the ceiling the API client enforces: a worker that would
    # be the (N+1)th request in flight blocks on the semaphore instead of
    # opening a connection the account cannot serve.
    set_max_concurrency(args.workers)

    skip = {name for name, s in cfg.shares.items() if not s.index}
    only = set(args.share) if args.share else None
    if only:
        unknown = only - set(cfg.shares)
        if unknown:
            # A typo'd share name would otherwise select nothing and look like
            # "queue is empty" — an expensive silence when it is meant to start
            # an overnight run.
            print(f"unknown share(s): {', '.join(sorted(unknown))}", flush=True)
            print(f"known: {', '.join(sorted(cfg.shares))}", flush=True)
            return 2
    ids = eligible_ids(cfg.db.path, skip_shares=skip, only_shares=only,
                       after_id=args.after_id)
    if args.after_id is not None:
        print(f"restricted to ids above {args.after_id}", flush=True)
    if skip:
        print(f"skipping {len(skip)} share(s) configured index:false: "
              f"{', '.join(sorted(skip))}", flush=True)
    if only:
        print(f"restricted to share(s): {', '.join(sorted(only))}", flush=True)
    if args.limit:
        ids = ids[: args.limit]
    deadline_note = f", stopping at {args.deadline}" if deadline else ""
    print(f"{len(ids)} videos to index, {args.workers} workers{deadline_note}", flush=True)
    if not ids:
        return 0

    start = time.time()
    done = errors = skipped = stopped = 0
    fatal: str | None = None

    with cf.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(_process_one, cfg, args.model, vid, deadline): vid
                for vid in ids}
        for i, fut in enumerate(cf.as_completed(futs), 1):
            vid = futs[fut]
            try:
                _, status = fut.result()
            except Exception as e:  # noqa: BLE001
                status = f"crash:{e}"

            if status.startswith("fatal:"):
                if fatal is None:
                    fatal = status[len("fatal:"):]
                    # Cancel everything not yet started. Calls already in flight
                    # will finish (and almost certainly report the same fatal);
                    # their videos stay untouched either way.
                    cancelled = sum(1 for f in futs if f.cancel())
                    print(f"\nACCOUNT-WIDE FAILURE — stopping. {fatal}", flush=True)
                    print(f"cancelled {cancelled} queued videos; "
                          f"queue untouched and resumable", flush=True)
                continue

            if status == "ok":
                done += 1
            elif status == "deadline":
                if stopped == 0:
                    print("\nDEADLINE reached — starting no new videos; "
                          "those in flight will finish", flush=True)
                stopped += 1
                # Deliberately no per-video progress line: past the deadline
                # every remaining future returns at once, and printing them
                # would bury the run's actual result under a thousand lines.
                continue
            elif status in ("skip", "gone"):
                skipped += 1
            else:
                errors += 1

            if i % 5 == 0 or status.startswith("crash") or status == "ok":
                el = (time.time() - start) / 60
                rate = done / el if el else 0
                left = len(ids) - i
                eta = left / rate / 60 if rate else 0
                print(f"[{i}/{len(ids)}] {rate:.1f}/min  eta {eta:.1f}h  "
                      f"ok={done} err={errors} skip={skipped}  last={vid}:{status}",
                      flush=True)

    el = (time.time() - start) / 60
    print(f"\ndone {done}, errors {errors}, skipped {skipped}, "
          f"not-started {stopped} in {el:.1f} min "
          f"({done / el if el else 0:.2f}/min)", flush=True)

    if fatal:
        # Non-zero + the message on stdout: run_queue.py matches the message to
        # decide between "wait out the session limit" and "stop, something is
        # actually broken".
        print(f"claude stage aborted: {fatal}", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
