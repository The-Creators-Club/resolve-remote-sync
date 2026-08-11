"""Transcribe the whole queue in ONE process, loading Whisper once.

The pipeline's `transcribe` stage shells out per video, so it pays the model
load (~8-14 s) every time. Across 2,382 videos that is over five hours of pure
loading. This loads the model once and streams through the queue, writing the
same `DATA_ROOT/transcripts/{video_id}/{stem}.srt` files the stage already
reuses — so the pipeline then ingests them without re-transcribing anything.

Run it ALONGSIDE the pipeline's local stages, not ahead of them:

    python batch_transcribe.py --config config.queue.yaml

"Before" was the original instruction and it was wrong (BROLL-15, 2026-08-11).
The queue below skips `status='skipped'`, which is a verdict `probe` reaches —
run against a freshly scanned share, every row is still 'discovered' and nothing
has been discarded yet, so the multi-hour takes that max_duration_s is about to
throw away get transcribed in full on the way to being thrown away. Rows still
at 'discovered' are therefore excluded here as well: a clip is worth an hour of
GPU once probe has said it is worth keeping.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import yaml


def _add_cuda_dll_dirs() -> None:
    """Make the pip-installed cuBLAS/cuDNN DLLs discoverable on Windows.

    Mirrors ~/tools/whisper/transcribe.py — ctranslate2 lazy-loads via plain
    LoadLibrary, which respects PATH but ignores add_dll_directory.
    """
    if sys.platform != "win32":
        return
    try:
        import nvidia  # type: ignore
    except ImportError:
        return
    added = []
    for base_str in nvidia.__path__:
        base = Path(base_str)
        for sub in ("cublas/bin", "cudnn/bin", "cuda_nvrtc/bin"):
            p = base / sub
            if p.exists():
                os.add_dll_directory(str(p))
                added.append(str(p))
    if added:
        os.environ["PATH"] = ";".join(added) + ";" + os.environ.get("PATH", "")


def _has_audio_stream(src: Path) -> bool:
    """True if the file has at least one audio stream.

    A lot of b-roll has none — Resolve renders, vintage silent newsreels,
    digital background loops. faster-whisper raises "tuple index out of range"
    on these (VAD strips everything, then an internal index goes empty), so we
    check first and skip the model call entirely: a silent clip legitimately has
    no transcript, exactly like one whose audio is pure ambience.
    """
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-select_streams", "a",
         "-show_entries", "stream=codec_name", "-of", "csv=p=0", str(src)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return bool(r.stdout.strip())


# The queue, as a module constant so it can be exercised against a fixture DB
# rather than only by running a GPU job (tests/test_batch_transcribe_queue.py).
#
# 'discovered' is excluded alongside 'skipped' (BROLL-15, 2026-08-11): both
# 'skipped' verdicts are ones `probe` reaches, so on a freshly scanned share the
# filter matched everything and the multi-hour takes max_duration_s was about to
# discard got a full Whisper pass on the way out. See the module docstring.
TODO_SQL = (
    "SELECT id, share, rel_path, duration_s FROM videos "
    "WHERE status NOT IN ('skipped', 'discovered') "
    "AND duplicate_of IS NULL AND transcribed_at IS NULL "
    "ORDER BY duration_s"
)


def _ts(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds - h * 3600 - m * 60
    return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", ",")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.queue.yaml")
    ap.add_argument("--model", default="large-v3-turbo")
    ap.add_argument("--compute-type", default="float16")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    roots = {k: Path(v["root"]) for k, v in cfg["shares"].items()}
    data_root = Path(cfg["data_root"])
    db_path = cfg["db"]["path"]

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    videos = conn.execute(TODO_SQL).fetchall()
    conn.close()

    todo = []
    for v in videos:
        out_dir = data_root / "transcripts" / str(v["id"])
        if list(out_dir.glob("*.srt")):
            continue  # already done by an earlier pass
        todo.append(v)
    if args.limit:
        todo = todo[: args.limit]

    total_min = sum((v["duration_s"] or 0) for v in todo) / 60
    print(f"{len(todo)} videos to transcribe, {total_min/60:.1f} h of audio", flush=True)
    if not todo:
        return 0

    _add_cuda_dll_dirs()
    from faster_whisper import WhisperModel

    t0 = time.time()
    model = WhisperModel(args.model, device="cuda", compute_type=args.compute_type)
    print(f"model loaded in {time.time()-t0:.1f}s (once, not per video)", flush=True)

    done = failed = 0
    start = time.time()
    for i, v in enumerate(todo, 1):
        root = roots.get(v["share"])
        if root is None:
            continue
        src = root / v["rel_path"]
        if not src.is_file():
            print(f"[{i}/{len(todo)}] MISSING {src}", flush=True)
            failed += 1
            continue

        out_dir = data_root / "transcripts" / str(v["id"])
        out_dir.mkdir(parents=True, exist_ok=True)

        if not _has_audio_stream(src):
            # No audio at all — write an empty transcript so this counts as done
            # and is never retried, rather than failing every pass.
            (out_dir / f"{src.stem}.srt").write_text("", encoding="utf-8")
            done += 1
            continue

        t = time.time()
        # faster-whisper occasionally raises "tuple index out of range" under GPU
        # memory pressure — transient, not a bad file (the same file transcribes
        # fine on a second attempt). Retry once before giving up.
        last_err = None
        for attempt in range(2):
            try:
                segments, info = model.transcribe(str(src), vad_filter=True, beam_size=5)
                lines = []
                for n, seg in enumerate(segments, 1):
                    lines.append(f"{n}\n{_ts(seg.start)} --> {_ts(seg.end)}\n{seg.text.strip()}\n")
                (out_dir / f"{src.stem}.srt").write_text("\n".join(lines), encoding="utf-8")
                last_err = None
                break
            except Exception as e:  # noqa: BLE001 — one bad file must not stop the batch
                last_err = e
                time.sleep(1)
        if last_err is not None:
            print(f"[{i}/{len(todo)}] FAILED {src.name[:40]}: {str(last_err)[:90]}", flush=True)
            failed += 1
            continue

        done += 1
        el = time.time() - t
        dur = v["duration_s"] or 0
        if i % 10 == 0 or el > 30:
            rate = sum((x["duration_s"] or 0) for x in todo[:i]) / 60 / ((time.time() - start) / 60)
            print(f"[{i}/{len(todo)}] {dur/60:5.1f}min in {el:5.1f}s  "
                  f"(~{rate:.0f}x realtime overall)  {src.name[:38]}", flush=True)

    el = time.time() - start
    print(f"\ndone {done}, failed {failed} in {el/60:.1f} min "
          f"({total_min/(el/60):.0f}x realtime)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
