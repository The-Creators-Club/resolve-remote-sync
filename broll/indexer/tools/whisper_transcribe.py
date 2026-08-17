"""Transcribe one media file to an .srt with faster-whisper. The sidecar helper.

Runs in the environment `tools/make_whisper_env.ps1` / `.sh` builds, NOT in the
indexer's own environment, and is invoked as a subprocess by
`broll_index.transcribe.run_whisper`. That separation is deliberate and is
older than this file (see broll_index/transcribe.py): ctranslate2 loads CUDA and
cuDNN through plain LoadLibrary, pins its own CUDA runtime, and is painful to
make coexist with whatever else the indexer's interpreter has. A subprocess with
its own site-packages is the cheap answer, and the process boundary also means a
CUDA crash kills one clip rather than the run.

Until 2026-08-17 this script existed only outside the repo, at one operator's
`~/tools/whisper/transcribe.py`, and `whisper.python`/`whisper.script` defaulted
to that path -- so transcription was unreproducible for anyone else
(COMMERCIAL_READINESS.md item 14). This is that script, in the tree, with the
same command line, so an existing base rig can keep pointing at its own copy or
switch to this one without any other change.

    python whisper_transcribe.py <media> -o <out_dir> -m large-v3-turbo [-l zh]

Writes `<out_dir>/<stem>.srt` and prints its path. An input with no audio stream
gets an EMPTY .srt rather than an error: silent footage legitimately has no
transcript, and the pipeline treats a missing file as "not attempted" and would
retry it on every run forever.
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path


def add_cuda_dll_dirs():
    """Make pip-installed cuBLAS/cuDNN DLLs findable on Windows.

    ctranslate2 lazy-loads them with LoadLibrary, which respects PATH but
    ignores `os.add_dll_directory` -- so both are done. Mirrors
    batch_transcribe.py's copy, which loads the model once for a whole queue.
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


def has_audio_stream(src: Path) -> bool:
    """True if ffprobe finds an audio stream. Missing ffprobe -> assume yes.

    A lot of b-roll has no audio at all (Resolve renders, silent newsreels,
    background loops) and faster-whisper raises "tuple index out of range" on
    those once VAD has stripped everything. Assuming yes when ffprobe is absent
    keeps this helper usable without ffmpeg installed beside it -- the model
    call then fails, which is a worse message but not a wrong answer.
    """
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-select_streams", "a",
             "-show_entries", "stream=codec_name", "-of", "csv=p=0", str(src)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
    except OSError:
        return True
    return bool(r.stdout.strip())


def ts(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds - h * 3600 - m * 60
    return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", ",")


def to_srt(segments) -> str:
    lines = []
    for n, seg in enumerate(segments, 1):
        lines.append(f"{n}\n{ts(seg.start)} --> {ts(seg.end)}\n{seg.text.strip()}\n")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("src")
    ap.add_argument("-o", "--out-dir", required=True)
    ap.add_argument("-m", "--model", default="large-v3-turbo")
    ap.add_argument("-l", "--language", default=None,
                    help="force a language; omit to autodetect")
    ap.add_argument("--device", default=os.environ.get("CCSYNC_WHISPER_DEVICE", "auto"))
    ap.add_argument("--compute-type",
                    default=os.environ.get("CCSYNC_WHISPER_COMPUTE_TYPE", "float16"))
    args = ap.parse_args(argv)

    src = Path(args.src)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / (src.stem + ".srt")

    if not src.is_file():
        print(f"no such file: {src}", file=sys.stderr)
        return 2

    if not has_audio_stream(src):
        dest.write_text("", encoding="utf-8")
        print(dest)
        return 0

    add_cuda_dll_dirs()
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print("faster-whisper is not installed in this interpreter. Build the "
              "environment with tools/make_whisper_env.ps1 (or .sh) and point "
              "whisper.python at the python it prints.", file=sys.stderr)
        return 3

    device = args.device
    compute_type = args.compute_type
    if device == "auto":
        # CPU cannot do float16 in ctranslate2; int8 is the usable fallback and
        # is ~4x slower than the GPU rather than unusable.
        try:
            import ctranslate2
            device = "cuda" if ctranslate2.get_cuda_device_count() else "cpu"
        except Exception:                                          # noqa: BLE001
            device = "cpu"
    if device == "cpu" and compute_type == "float16":
        compute_type = "int8"

    # HF_HOME / HUGGINGFACE_HUB_CACHE are set by the caller when
    # whisper.model_dir is configured (broll_index.transcribe.whisper_child_env),
    # so nothing needs passing here for the model cache to be a mounted volume.
    model = WhisperModel(args.model, device=device, compute_type=compute_type)
    segments, _info = model.transcribe(str(src), vad_filter=True, beam_size=5,
                                       language=args.language)
    dest.write_text(to_srt(segments), encoding="utf-8")
    print(dest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
