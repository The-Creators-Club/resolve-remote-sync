"""RunResult: the common record type produced by every runner and stored in
results/results.jsonl (one JSON object per line, append-only)."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator


@dataclass
class RunResult:
    engine: str  # e.g. "rclone_sftp", "robocopy_smb", "syncthing", "iperf3"
    dataset: str  # dataset profile name, e.g. "large", "small"
    direction: str  # "up" | "down" | "bidirectional"
    params: dict[str, Any]  # engine-specific params for this run (e.g. transfers=8)
    seconds: float
    num_bytes: int
    MB_s: float
    verified: bool
    ok: bool = True
    skipped: bool = False
    reason: str = ""
    lane: str = ""  # "A" | "B" | "C" | "" (assigned by matrix.py from bench.toml)
    endpoint: str = ""  # short label for which endpoint config was used
    timestamp: float = field(default_factory=time.time)
    repeat_index: int = 0
    stderr_tail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True)

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "RunResult":
        known = {f for f in RunResult.__dataclass_fields__}
        filtered = {k: v for k, v in d.items() if k in known}
        return RunResult(**filtered)

    def key(self) -> str:
        """Stable identity used for resume/dedup: same engine+lane+dataset+direction
        +params+repeat_index means 'already ran this exact combo'."""
        return combo_key(
            self.engine, self.lane, self.dataset, self.direction, self.params, self.repeat_index
        )


def combo_key(
    engine: str,
    lane: str,
    dataset: str,
    direction: str,
    params: dict[str, Any],
    repeat_index: int = 0,
) -> str:
    return "|".join(
        [
            engine,
            lane or "",
            dataset,
            direction,
            json.dumps(params, sort_keys=True),
            str(repeat_index),
        ]
    )


def make_skipped(
    engine: str,
    dataset: str,
    direction: str,
    params: dict[str, Any],
    reason: str,
    lane: str = "",
    endpoint: str = "",
    repeat_index: int = 0,
) -> RunResult:
    return RunResult(
        engine=engine,
        dataset=dataset,
        direction=direction,
        params=params,
        seconds=0.0,
        num_bytes=0,
        MB_s=0.0,
        verified=False,
        ok=False,
        skipped=True,
        reason=reason,
        lane=lane,
        endpoint=endpoint,
        repeat_index=repeat_index,
    )


def append_result(path: Path, result: RunResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write(result.to_json())
        f.write("\n")


def read_results(path: Path) -> list[RunResult]:
    if not path.exists():
        return []
    out: list[RunResult] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            out.append(RunResult.from_dict(json.loads(line)))
    return out


def existing_keys(path: Path) -> set[str]:
    return {r.key() for r in read_results(path)}
