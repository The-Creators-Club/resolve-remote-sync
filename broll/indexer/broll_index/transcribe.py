"""Local audio transcription via faster-whisper.

Speech is frequently the richest index a clip has, and on owned hardware it is
free: measured at 12.6x realtime on an RTX 3080 (see docs/indexing-findings.md).
A news package whose pictures index as "officials at a press conference" yields
names, an operation name, a date and a location from its audio — none of which
appear in any frame.

Because it costs no model quota, this stage runs over everything unconditionally,
and it is what makes long talking-head stretches cheap to index: the information
is in the words, so the visual sampler does not need to describe the same static
frame every four seconds.

We shell out to a faster-whisper environment rather than importing it, because that
environment needs CUDA/cuDNN DLL wiring on Windows which is painful to reproduce
in-process — and because ctranslate2 pins a CUDA runtime that the rest of the indexer
should not have to agree with. `tools/make_whisper_env.ps1` / `.sh` build that
environment from pinned versions and `tools/whisper_transcribe.py` is the helper it
runs; `whisper.python` / `whisper.script` say where they are (COMMERCIAL_READINESS.md
item 14, 2026-08-17 — before that they defaulted to one workstation's directory).
`run_whisper` is the single subprocess boundary — mock it in tests.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

_TS_RE = re.compile(
    r"(?P<h>\d{2}):(?P<m>\d{2}):(?P<s>\d{2})[,.](?P<ms>\d{3})\s*-->\s*"
    r"(?P<h2>\d{2}):(?P<m2>\d{2}):(?P<s2>\d{2})[,.](?P<ms2>\d{3})"
)


@dataclass(frozen=True)
class TranscriptCue:
    t_start: float
    t_end: float
    text: str


def _ts_to_seconds(h: str, m: str, s: str, ms: str) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def parse_srt(content: str) -> list[TranscriptCue]:
    """Parse an SRT into cues. Tolerant of BOM, CRLF, and missing trailing newline."""
    cues: list[TranscriptCue] = []
    blocks = re.split(r"\r?\n\r?\n", content.lstrip("﻿").strip())
    for block in blocks:
        lines = [ln for ln in re.split(r"\r?\n", block) if ln.strip()]
        if not lines:
            continue
        ts_line = next((ln for ln in lines if _TS_RE.search(ln)), None)
        if ts_line is None:
            continue
        m = _TS_RE.search(ts_line)
        assert m is not None
        text_lines = lines[lines.index(ts_line) + 1 :]
        text = " ".join(ln.strip() for ln in text_lines).strip()
        if not text:
            continue
        cues.append(
            TranscriptCue(
                t_start=_ts_to_seconds(m["h"], m["m"], m["s"], m["ms"]),
                t_end=_ts_to_seconds(m["h2"], m["m2"], m["s2"], m["ms2"]),
                text=text,
            )
        )
    return cues


def merge_cues(cues: list[TranscriptCue], max_gap_s: float = 1.0,
               max_duration_s: float = 30.0) -> list[TranscriptCue]:
    """Join adjacent cues into longer passages.

    Whisper emits short cues sized for subtitles; for search they fragment a
    sentence across rows so a phrase spanning two cues matches neither. Merging
    until a real pause (`max_gap_s`) or a length cap gives passages that read as
    units while still carrying a usable timestamp to seek to.
    """
    if not cues:
        return []
    merged = [cues[0]]
    for cue in cues[1:]:
        last = merged[-1]
        gap = cue.t_start - last.t_end
        would_span = cue.t_end - last.t_start
        if gap <= max_gap_s and would_span <= max_duration_s:
            merged[-1] = TranscriptCue(last.t_start, cue.t_end, f"{last.text} {cue.text}".strip())
        else:
            merged.append(cue)
    return merged


def whisper_child_env(model_dir: str = "") -> dict[str, str] | None:
    """This process's environment plus a pinned model cache, or None for "inherit".

    `model_dir` is passed through the ENVIRONMENT rather than argv because the
    helper on the other end is not necessarily ours: an operator may keep
    pointing `whisper.python`/`whisper.script` at a hand-built environment whose
    script never learned a `--model-dir` flag, while faster-whisper/huggingface
    honour these variables regardless. (2026-08-17, COMMERCIAL_READINESS.md
    item 14 — the image mounts a models volume and would otherwise re-download
    large-v3-turbo, ~1.6 GB, on every container start.)
    """
    if not model_dir:
        return None
    env = dict(os.environ)
    env["HF_HOME"] = model_dir
    env["HUGGINGFACE_HUB_CACHE"] = str(Path(model_dir) / "hub")
    env["CCSYNC_WHISPER_MODEL_DIR"] = model_dir
    return env


def run_whisper(
    src: Path, out_dir: Path, python_exe: str, script: str,
    model: str = "large-v3-turbo", language: str | None = None,
    timeout: int = 7200, *, model_dir: str = "",
) -> Path:
    """Invoke the external faster-whisper helper. Returns the produced .srt path.

    THE subprocess boundary for this module — mock this in tests.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [python_exe, script, str(src), "-o", str(out_dir), "-m", model]
    if language:
        cmd += ["-l", language]
    result = subprocess.run(
        cmd, capture_output=True, timeout=timeout,
        text=True, encoding="utf-8", errors="replace",
        env=whisper_child_env(model_dir),
    )
    if result.returncode != 0:
        raise RuntimeError(f"whisper exited {result.returncode}: {result.stderr.strip()[:400]}")

    srt = out_dir / (src.stem + ".srt")
    if not srt.is_file():
        # The helper names outputs after the input stem; if that ever changes,
        # fall back to the newest .srt rather than failing the whole clip.
        candidates = sorted(out_dir.glob("*.srt"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not candidates:
            raise RuntimeError(f"whisper produced no .srt in {out_dir}")
        srt = candidates[0]
    return srt


def transcribe_file(
    src: Path, out_dir: Path, python_exe: str, script: str,
    model: str = "large-v3-turbo", language: str | None = None,
    max_gap_s: float = 1.0, max_duration_s: float = 30.0,
    runner=run_whisper, model_dir: str = "",
) -> list[TranscriptCue]:
    """Transcribe `src` and return merged, search-sized cues.

    `model_dir` is only forwarded when it is set, so a runner written against
    the six-positional contract (every existing test double) still works.
    """
    extra = {"model_dir": model_dir} if model_dir else {}
    srt = runner(src, out_dir, python_exe, script, model, language, **extra)
    cues = parse_srt(Path(srt).read_text(encoding="utf-8", errors="replace"))
    return merge_cues(cues, max_gap_s=max_gap_s, max_duration_s=max_duration_s)
