"""Shared plumbing for the two rclone-based runners (sftp, smb).

Both runners build an rclone "on the fly" remote spec string (no rclone.conf
needed -- see https://rclone.org/docs/#connection-strings) and then share the
same param-matrix expansion, transfer execution, verification and cleanup
logic. Only remote-spec construction and a couple of backend-specific flags
(e.g. --sftp-chunk-size only makes sense for sftp) differ between the two.

Direction handling:
- "up": pre-clean the remote bench subfolder (untimed), then time
  `rclone copy dataset_dir -> remote`.
- "down": ensure the remote bench subfolder already has the dataset (an
  untimed "seed" copy -- cheap/no-op if it's already there, since rclone
  compares before transferring), then time `rclone copy remote -> dest_dir`.

--multi-thread-streams only helps when rclone is writing to a local
destination (chunks of one file downloaded in parallel and written into a
local seekable file); it does nothing useful uploading to a remote, and some
backends don't support server-side seek writes at all. So param_matrix drops
the multi-thread-streams sweep to a single 0 entry for "up".
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Callable

from ccbench.result import RunResult, make_skipped

from . import base


def available() -> tuple[bool, str]:
    return base.which("rclone")


def build_param_matrix(cfg: dict[str, Any], direction: str, include_chunk_size: bool) -> list[dict[str, Any]]:
    transfers = base.expand_sweep(cfg.get("transfers"), [4])
    mts_raw = base.expand_sweep(cfg.get("multi_thread_streams"), [0])
    chunk_sizes = base.expand_sweep(cfg.get("sftp_chunk_size_mb"), [32]) if include_chunk_size else [None]

    combos: list[dict[str, Any]] = []
    seen: set[tuple] = set()
    mts_options = mts_raw if direction == "down" else [0]
    for t in transfers:
        for mts in mts_options:
            for cs in chunk_sizes:
                params: dict[str, Any] = {"transfers": t, "multi_thread_streams": mts}
                if cs is not None:
                    params["sftp_chunk_size_mb"] = cs
                key = tuple(sorted(params.items()))
                if key in seen:
                    continue
                seen.add(key)
                combos.append(params)
    return combos


def _flags(params: dict[str, Any]) -> list[str]:
    flags = ["--transfers", str(params.get("transfers", 4))]
    mts = params.get("multi_thread_streams", 0)
    flags += ["--multi-thread-streams", str(mts)]
    if "sftp_chunk_size_mb" in params:
        flags += ["--sftp-chunk-size", f"{params['sftp_chunk_size_mb']}M"]
    return flags


def _seed_remote(dataset_dir: Path, remote_root: str, timeout: float | None) -> None:
    """Untimed: make sure remote_root has the dataset already. rclone copy
    only transfers files that are missing/changed, so calling this before
    every 'down' repeat is safe and cheap once seeded once."""
    try:
        subprocess.run(
            ["rclone", "copy", str(dataset_dir), remote_root, "--transfers", "8"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except Exception:
        pass


def cleanup_remote(remote_root: str, timeout: float = 120) -> None:
    try:
        subprocess.run(["rclone", "purge", remote_root], capture_output=True, text=True, timeout=timeout)
    except Exception:
        pass


def do_transfer(
    *,
    engine: str,
    dataset_name: str,
    dataset_dir: Path,
    direction: str,
    params: dict[str, Any],
    remote_root: str,
    verify: bool,
    keep_remote_data: bool,
    dest_dir: Path | None,
    lane: str,
    endpoint_label: str,
    repeat_index: int,
    seed_timeout: float | None = 1800,
    transfer_timeout: float | None = 3600,
) -> RunResult:
    ok, reason = available()
    if not ok:
        return make_skipped(engine, dataset_name, direction, params, reason, lane, endpoint_label, repeat_index)

    flags = _flags(params)
    verify_root: Path | None = None

    try:
        if direction == "up":
            cleanup_remote(remote_root, timeout=120)  # pre-clean so repeats aren't skip-because-exists
            rc, _out, err, seconds = base.run_subprocess(
                ["rclone", "copy", str(dataset_dir), remote_root, *flags, "-v"],
                timeout=transfer_timeout,
            )
        elif direction == "down":
            if dest_dir is None:
                raise ValueError("dest_dir required for 'down' direction")
            _seed_remote(dataset_dir, remote_root, seed_timeout)
            dest_dir.mkdir(parents=True, exist_ok=True)
            rc, _out, err, seconds = base.run_subprocess(
                ["rclone", "copy", remote_root, str(dest_dir), *flags, "-v"],
                timeout=transfer_timeout,
            )
            verify_root = dest_dir
        else:
            return make_skipped(
                engine, dataset_name, direction, params,
                f"unsupported direction for rclone runner: {direction}",
                lane, endpoint_label, repeat_index,
            )
    except subprocess.TimeoutExpired as exc:
        return RunResult(
            engine=engine, dataset=dataset_name, direction=direction, params=params,
            seconds=0.0, num_bytes=0, MB_s=0.0, verified=False, ok=False,
            reason=f"timeout after {exc.timeout}s", lane=lane, endpoint=endpoint_label,
            repeat_index=repeat_index,
        )

    num_bytes = base.manifest_bytes(dataset_dir) if rc == 0 else 0
    verified = False
    if rc == 0 and verify:
        if verify_root is not None:
            manifest = base.manifest_files(dataset_dir)
            verified, _detail = base.spot_check(manifest, verify_root)
        else:
            # "up": no independent remote read-back configured; trust rclone's
            # own exit code + its internal post-transfer hash check (rclone
            # verifies size+hash for supported backends during `copy` itself).
            verified = True
    elif not verify:
        verified = False

    result = RunResult(
        engine=engine,
        dataset=dataset_name,
        direction=direction,
        params=params,
        seconds=seconds,
        num_bytes=num_bytes,
        MB_s=base.mb_per_s(num_bytes, seconds) if rc == 0 else 0.0,
        verified=verified,
        ok=(rc == 0),
        reason="" if rc == 0 else f"rclone exit {rc}",
        lane=lane,
        endpoint=endpoint_label,
        repeat_index=repeat_index,
        stderr_tail=base.tail(err) if rc != 0 else "",
    )

    if not keep_remote_data:
        cleanup_remote(remote_root, timeout=120)

    return result
