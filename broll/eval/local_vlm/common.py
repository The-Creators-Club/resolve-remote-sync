"""Shared helpers for the local-VLM eval (broll/eval/local_vlm).

Everything here is deliberately stdlib-only so the same files run unmodified on
the Windows base rig and on a Mac that only has a llama-server and Python 3.
`broll_index` (the indexer package) is imported for its contract functions —
validate_contract / parse_claude_response / merge_index_results /
build_index_prompt — never for I/O; the eval must not touch the indexer's
config, DB or archive.
"""
from __future__ import annotations

import base64
import json
import os
import platform
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
INDEXER_SRC = REPO / "broll" / "indexer"
if str(INDEXER_SRC) not in sys.path:
    sys.path.insert(0, str(INDEXER_SRC))

# The real indexer DB on the base rig. broll/web/data/broll.db is a 170 KB dev
# stub with no Haiku segments in it, so it is NOT the default; BROLL_DB_PATH
# (the indexer's own override, docs/INDEXERS.md) wins when set.
DEFAULT_DB = Path(os.environ.get("BROLL_DB_PATH") or r"E:\broll-queue\broll.db")
DEFAULT_DATA_ROOT = Path(os.environ.get("BROLL_DATA_ROOT") or r"E:\broll-queue")
DEFAULT_CLIPS = HERE / "clips.json"

# Sampler defaults for arms A/B (what the task asked for). Arm C reproduces the
# earlier prototype (run_llamacpp.py): temperature 0, no repeat penalty.
COMPACT_SAMPLER = {"temperature": 0.1, "repeat_penalty": 1.15}
V6_SAMPLER = {"temperature": 0.0}
FRAMES_PER_CALL = 9
SHEETS_PER_CALL = 4          # frames_per_call 36 // 9, the config default
MAX_SHEETS_PER_CLIP = 24     # sampling.max_sheets_per_video on the base rig
TOKENS_PER_FRAME_BUDGET = 150   # 120 hit finish=length on chyron-heavy news windows in the smoke test


def seconds_to_tc(s: float) -> str:
    s = max(0, int(round(s)))
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def data_url(path: Path) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(Path(path).read_bytes()).decode()


def load_clips(clips_path: Path | str = DEFAULT_CLIPS) -> dict[str, Any]:
    clips_path = Path(clips_path)
    doc = json.loads(clips_path.read_text(encoding="utf-8"))
    root = Path(doc["frames_root"])
    if not root.is_absolute():
        root = (clips_path.parent / root).resolve()
    doc["_frames_root"] = root
    doc["_path"] = clips_path
    return doc


def frame_abs(doc: dict[str, Any], rel: str) -> Path:
    return doc["_frames_root"] / rel


def host_label() -> str:
    return f"{platform.node()} ({platform.system()} {platform.machine()})"


def load_host_config(path: Path | str | None) -> dict[str, Any]:
    """`config.<host>.json` — llama-server binary, model + mmproj GGUF paths,
    port and extra server args. Missing file -> {} and the CLI flags must
    supply everything."""
    if path is None:
        return {}
    p = Path(path)
    if not p.exists():
        raise SystemExit(f"host config not found: {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not Path(path).exists():
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue  # a half-written last line after a kill; the clip reruns
    return out


def append_jsonl(path: Path, rec: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())
