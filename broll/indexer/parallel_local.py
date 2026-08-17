"""Run the local (no-API) stages across many videos concurrently.

The serial pipeline processes one video at a time, which left a 24-core machine
at ~20% CPU: probe, scene detection and contact-sheet tiling are all CPU work,
and NVENC proxy encoding is a fixed-function block that barely touches the CPU,
so running one video at a time wastes almost the whole machine. Measured serial
rate was ~0.7 videos/min (~59 h for the queue).

This drives probe -> proxy -> frames for each eligible video in a worker pool.
It deliberately does NOT run the `claude` stage — that is rate-limited and
belongs to run_queue.py, which this feeds. Each video is independent and writes
to its own DATA_ROOT subtree, so there is no shared-state contention beyond the
SQLite row updates (WAL mode handles those). Failures are isolated per video.

    python parallel_local.py --workers 6    # --config defaults to private/broll/indexer/config.queue.yaml
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import sqlite3
import sys
import time
from pathlib import Path

from broll_index import ffmpeg_tools
from broll_index.config import load_config
from broll_index.pipeline import (
    ORGANISED_STATUS, reopen_if_now_indexable, stage_frames, stage_probe,
    stage_proxy, stage_transcribe,
)
from broll_index.site_data import DEFAULT_QUEUE_CONFIG
from broll_index.storage.sqlite_backend import SqliteBackend

# `transcribe` is included only as an INGEST of .srt files batch_transcribe.py has
# already written — cheap CPU work with no GPU or model load. It is
# status-independent (additive enrichment) so it runs for every video regardless
# of where it sits in the probe->proxy->frames flow.
#
# It is called with ingest_only=True, and that is load-bearing rather than
# defensive. This comment used to assert "batch_transcribe.py has already written
# every .srt", which was true of the shares that existed when it was written and
# false the moment a new one was added: with no .srt, stage_transcribe falls
# through to running Whisper itself. On the FF4 share that turned a local pass
# into six saturated CPU workers transcribing multi-hour interview takes — ahead
# of stage_probe, so ahead of the max_duration_s cap that was about to discard
# them. Twelve minutes in, not one video had been probed.
LOCAL_STAGES = ("probe", "proxy", "frames")


def _process_one(cfg, share_roots, video_id: int) -> tuple[int, str]:
    """Own sqlite connection per worker — connections are not thread/process safe."""
    storage = SqliteBackend(cfg.db.path)
    try:
        video = storage.get_video(video_id)
        if video is None:
            return video_id, "gone"
        # A clip resting at 'organised' whose share is indexable again rejoins
        # the queue here — otherwise flipping index:true would strand it.
        video = reopen_if_now_indexable(cfg, storage, video)
        share = cfg.shares.get(video["share"])
        if share is None:
            storage.set_error(video_id, f"unknown share '{video['share']}'")
            return video_id, "error:share"
        src = Path(share.root) / video["rel_path"]

        # Ingest the already-written .srt first. Status-independent and never
        # fatal — stage_transcribe swallows its own failures.
        share_cfg = cfg.shares.get(video["share"])
        if not video["transcribed_at"] and getattr(share_cfg, "transcribe", True):
            try:
                stage_transcribe(cfg, storage, video, src, ingest_only=True)
            except Exception:  # noqa: BLE001 — enrichment must never fail a video
                pass

        # Advance through the local stages in order, re-reading status each time
        # so a resumed run skips what is already done.
        for stage in LOCAL_STAGES:
            v = storage.get_video(video_id)
            if stage == "probe" and v["status"] != "discovered":
                continue
            if stage == "proxy" and v["status"] != "probed":
                continue
            if stage == "frames" and v["status"] != "proxied":
                continue
            # Contact sheets are the images sent to the model, and nothing else
            # reads them. On an `index: false` share there is no model call, so
            # building them is a full scene-detection decode per clip for
            # output that will never be opened — the heaviest local stage,
            # spent on nothing. Stop at the proxy and mark the clip organised.
            if stage == "frames":
                share_cfg = cfg.shares.get(v["share"])
                if share_cfg is not None and not getattr(share_cfg, "index", True):
                    storage.update_video(video_id, status=ORGANISED_STATUS)
                    return video_id, "organised"
            try:
                if stage == "probe":
                    stage_probe(cfg, storage, v, src)
                elif stage == "proxy":
                    stage_proxy(cfg, storage, v, src)
                elif stage == "frames":
                    stage_frames(cfg, storage, v, src)
            except Exception as e:  # noqa: BLE001
                storage.set_error(video_id, f"{stage} failed: {e}")
                return video_id, f"error:{stage}"
        return video_id, "ok"
    finally:
        storage.close()


def eligible_ids(db_path: str) -> list[int]:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return [r[0] for r in conn.execute(
            # 'organised' is included so a share switched back to index:true is
            # picked up on the next run — _process_one reopens those to
            # 'proxied'. For a share still opted out they cost one dict lookup
            # and return immediately.
            "SELECT id FROM videos WHERE status IN "
            "('discovered','probed','proxied','organised') "
            "AND duplicate_of IS NULL ORDER BY id"
        )]
    finally:
        conn.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=DEFAULT_QUEUE_CONFIG)
    # NVENC on consumer GPUs limits concurrent encode sessions (~3-8 depending
    # on driver); scene detection and tiling scale with CPU cores. 6 is a safe
    # default for a 24-core box with one NVENC-capable GPU.
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    cfg = load_config(args.config)
    share_roots = {k: v.root for k, v in cfg.shares.items()}

    # Make sure the DB exists / is at the right schema before workers open it.
    SqliteBackend(cfg.db.path).close()

    ids = eligible_ids(cfg.db.path)
    print(f"{len(ids)} videos through local stages, {args.workers} workers", flush=True)
    if not ids:
        return 0

    start = time.time()
    done = errors = 0
    # Processes, not threads: ffmpeg is a subprocess anyway, but scene detection
    # parsing and tiling are Python/CPU and would contend on the GIL as threads.
    with cf.ProcessPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(_process_one, cfg, share_roots, vid): vid for vid in ids}
        for i, fut in enumerate(cf.as_completed(futs), 1):
            vid = futs[fut]
            try:
                _, status = fut.result()
            except Exception as e:  # noqa: BLE001
                status = f"crash:{e}"
            if status == "ok":
                done += 1
            elif status.startswith("error") or status.startswith("crash"):
                errors += 1
            if i % 25 == 0 or status.startswith(("error", "crash")):
                rate = i / ((time.time() - start) / 60)
                eta = (len(ids) - i) / rate / 60 if rate else 0
                print(f"[{i}/{len(ids)}] {rate:.1f}/min  eta {eta:.1f}h  "
                      f"ok={done} err={errors}  last={vid}:{status}", flush=True)

    el = time.time() - start
    print(f"\ndone {done}, errors {errors} in {el/60:.1f} min "
          f"({len(ids)/(el/60):.1f}/min)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
