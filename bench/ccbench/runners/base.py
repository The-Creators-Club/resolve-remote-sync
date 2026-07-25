"""Shared helpers for runner implementations.

Common runner interface (duck-typed, no ABC to keep it simple to smoke-test):

    ENGINE: str
        short engine name, used as the "engine" field on RunResult and as the
        REGISTRY key / --engines filter value.

    available() -> (bool, str)
        Cheap local check (usually shutil.which) for whether this runner can
        run at all on this machine. Reason string explains a False result.
        MUST NOT touch the network.

    param_matrix(cfg: dict, direction: str) -> list[dict]
        Expand a runner's sweep config (from bench.toml [params.<engine>])
        into a list of concrete per-run param dicts, for the given direction.
        Must not crash on combinations that don't make sense for this engine/
        direction/backend -- silently drop them instead (e.g. multi-thread
        streams only apply when the local side is the write destination).

    run(dataset_dir, direction, endpoint, params, *, verify=True,
        keep_remote_data=False) -> RunResult
        Execute one concrete run and return a RunResult. Must never raise for
        "ordinary" failures (missing binary, transfer error, timeout) --
        catch and return a RunResult with ok=False / skipped=True and a
        reason instead. Only truly unexpected bugs should raise.
"""

from __future__ import annotations

import hashlib
import random
import shutil
import socket
import subprocess
import time
from pathlib import Path
from typing import Any, Sequence

from ccbench.dataset import read_manifest

STDERR_TAIL_CHARS = 2000


def free_port() -> int:
    """A currently-unused localhost TCP port (best-effort; there's an
    inherent TOCTOU race, but it's fine for spinning up ephemeral test
    servers/instances)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def which(binary: str) -> tuple[bool, str]:
    path = shutil.which(binary)
    if path:
        return True, path
    return False, f"'{binary}' not found on PATH"


def manifest_bytes(dataset_dir: Path) -> int:
    manifest = read_manifest(Path(dataset_dir))
    return int(manifest["total_bytes"])


def manifest_files(dataset_dir: Path) -> list[dict[str, Any]]:
    manifest = read_manifest(Path(dataset_dir))
    return manifest["files"]


def sha256_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def spot_check(
    manifest: Sequence[dict[str, Any]],
    check_root: Path,
    n: int = 3,
    seed: int | None = None,
) -> tuple[bool, str]:
    """Verify size+sha256 for up to n randomly-chosen files under check_root
    (the destination side after a transfer). Returns (verified, detail)."""
    if not manifest:
        return True, "empty manifest"
    rng = random.Random(seed)
    sample = rng.sample(list(manifest), k=min(n, len(manifest)))
    problems: list[str] = []
    for rec in sample:
        dest = check_root / rec["path"]
        if not dest.exists():
            problems.append(f"{rec['path']}: missing at destination")
            continue
        actual_size = dest.stat().st_size
        if actual_size != rec["size"]:
            problems.append(f"{rec['path']}: size {actual_size} != expected {rec['size']}")
            continue
        actual_sha = sha256_file(dest)
        if actual_sha != rec["sha256"]:
            problems.append(f"{rec['path']}: sha256 mismatch")
    if problems:
        return False, "; ".join(problems)
    return True, f"spot-checked {len(sample)} file(s) ok"


class Timer:
    """Context manager measuring wall-clock seconds."""

    def __enter__(self) -> "Timer":
        self._start = time.perf_counter()
        self.seconds = 0.0
        return self

    def __exit__(self, *exc: Any) -> None:
        self.seconds = time.perf_counter() - self._start


def run_subprocess(
    cmd: list[str],
    timeout: float | None = None,
) -> tuple[int, str, str, float]:
    """Run a subprocess, return (returncode, stdout, stderr, seconds)."""
    start = time.perf_counter()
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    seconds = time.perf_counter() - start
    return proc.returncode, proc.stdout, proc.stderr, seconds


def tail(s: str, n: int = STDERR_TAIL_CHARS) -> str:
    return s[-n:] if len(s) > n else s


def mb_per_s(num_bytes: int, seconds: float) -> float:
    """Throughput in **decimal** megabytes/second: bytes / 1e6 / seconds.

    One unit, used everywhere (RunResult.MB_s, the report tables, the
    Blackmagic-baseline comparison), so `60 Mbps -> 7.5 MB/s` is an exact
    conversion rather than a 4.9%-off MiB/s number wearing an MB/s label.
    Use `mib_per_s` when a binary unit is explicitly wanted.
    """
    if seconds <= 0:
        return 0.0
    return (num_bytes / 1_000_000) / seconds


def mib_per_s(num_bytes: int, seconds: float) -> float:
    """Throughput in binary mebibytes/second: bytes / 2**20 / seconds."""
    if seconds <= 0:
        return 0.0
    return (num_bytes / (1024 * 1024)) / seconds


_SIZE_UNITS = {
    "b": 1,
    "byte": 1,
    "bytes": 1,
    "k": 1024,
    "kb": 1000,
    "kib": 1024,
    "m": 1024**2,
    "mb": 1000**2,
    "mib": 1024**2,
    "g": 1024**3,
    "gb": 1000**3,
    "gib": 1024**3,
    "t": 1024**4,
    "tb": 1000**4,
    "tib": 1024**4,
}


def parse_size(value: str, unit: str) -> int | None:
    """Parse a '1.234' + 'GiB' pair (as printed by rclone/robocopy) to bytes."""
    factor = _SIZE_UNITS.get(unit.strip().lower())
    if factor is None:
        return None
    try:
        return int(float(value) * factor)
    except ValueError:
        return None


def expand_sweep(values: Any, default: list[Any]) -> list[Any]:
    """Normalize a bench.toml sweep entry (list, single value, or absent) to a list."""
    if values is None:
        return list(default)
    if isinstance(values, (list, tuple)):
        return list(values)
    return [values]
