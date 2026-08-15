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
    MB_s: float  # decimal megabytes/second (bytes / 1e6 / seconds) -- see base.mb_per_s
    verified: bool
    ok: bool = True
    skipped: bool = False
    reason: str = ""
    lane: str = ""  # "A" | "B" | "C" | "net" -- assigned by matrix.py from bench.toml
    endpoint: str = ""  # short label for which endpoint config was used
    timestamp: float = field(default_factory=time.time)
    repeat_index: int = 0
    stderr_tail: str = ""
    # How `num_bytes` was obtained. "rclone-stats"/"robocopy-summary" = the
    # tool's own accounting of what it actually moved; "manifest-fallback" =
    # the tool's stats couldn't be parsed and the dataset manifest total was
    # substituted (treat the throughput as an upper bound, not a measurement).
    bytes_source: str = "manifest"
    # How `verified` was established: "spot-check-sha256" (re-hashed files at
    # the destination), "remote-size-listing" (remote byte/file count matches
    # the manifest), "exit-code-only" (the tool said it worked and nothing
    # independent was checked -- do NOT read this as verified data), "none".
    verify_method: str = ""
    # True when both ends of this transfer were on this machine (loopback
    # syncthing pair, local_test_dir selftest runs). Such rows are NOT
    # comparable with rows measured over the real network.
    loopback: bool = False
    # How coarse this row's clock is, in seconds (SHIP-10, 2026-08-14). Runners
    # that bracket a child process with a Timer measure to the microsecond and
    # leave it 0.0; a runner that decides "started"/"finished" by POLLING (the
    # syncthing pair) can be a whole poll interval late at each end, and on a
    # ~2 s lane-C sync that is a material fraction of the number being
    # reported. Recorded so the report can say so instead of presenting
    # instrument error as run-to-run variance.
    timing_resolution_s: float = 0.0

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
    loopback: bool = False,
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
        bytes_source="none",
        verify_method="none",
        loopback=loopback,
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


def existing_keys(path: Path, *, measured_only: bool = True) -> set[str]:
    """The combos a resumed matrix should treat as ALREADY DONE.

    Only rows that actually produced a measurement count (SHIP-6, 2026-08-14).
    `key()` carries neither `ok` nor `skipped`, so this used to be every row in
    the file -- including the ones written by `make_skipped()` (no syncthing on
    PATH, unsupported direction, unsupported syncthing major) and every
    `ok=False` row (timeout, rclone non-zero, short transfer, runner crash).
    Installing the missing binary and re-running then printed `[skip-cached]`
    for every lane-C combo, measured nothing, and left the report still saying
    "No successful runs recorded for this lane yet." The only escape was
    `--rerun`, which also re-runs the rows that DID succeed -- and since the
    file is append-only, that blends the old and new measurements into one
    median (SHIP-7).
    """
    return {
        r.key()
        for r in read_results(path)
        if (not measured_only) or (r.ok and not r.skipped)
    }
