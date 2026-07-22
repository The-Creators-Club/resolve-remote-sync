"""Raw SMB copy via robocopy (Windows only) -- the "no extra tooling"
baseline every other engine has to beat. Sweeps /MT:{1,8,16,32} against a UNC
path (or, for selftest, a plain local directory -- robocopy doesn't care).

endpoint config (bench.toml [endpoints.smb], reused for this runner too):
    unc_path  -- e.g. \\\\host\\share\\Creators_Club\\_bench
    local_test_dir  -- selftest escape hatch, see rclone_sftp.py

robocopy exit codes 0-7 are all "success" (bit flags for files
copied/skipped/mismatched); >=8 means at least one failure.
"""

from __future__ import annotations

import platform
import shutil
from pathlib import Path
from typing import Any

from ccbench.result import RunResult, make_skipped

from . import base

ENGINE = "robocopy_smb"

ROBOCOPY_FAILURE_THRESHOLD = 8


def available() -> tuple[bool, str]:
    if platform.system() != "Windows":
        return False, "robocopy is Windows-only"
    return base.which("robocopy")


def param_matrix(cfg: dict[str, Any], direction: str) -> list[dict[str, Any]]:
    mt_values = base.expand_sweep(cfg.get("mt"), [1, 8, 16, 32])
    return [{"mt": mt} for mt in mt_values]


def _target_root(endpoint: dict[str, Any], dataset_name: str, direction: str) -> Path:
    base_path = endpoint.get("local_test_dir") or endpoint.get("unc_path")
    if not base_path:
        raise ValueError("robocopy_smb endpoint needs 'unc_path' (or 'local_test_dir' for selftest)")
    return Path(base_path) / dataset_name / direction


def _robocopy(src: Path, dst: Path, mt: int, timeout: float | None) -> tuple[int, str, str, float]:
    dst.mkdir(parents=True, exist_ok=True)
    cmd = [
        "robocopy",
        str(src),
        str(dst),
        "/E",
        f"/MT:{mt}",
        "/R:1",
        "/W:1",
        "/NFL",
        "/NDL",
        "/NP",
        "/NJH",
    ]
    return base.run_subprocess(cmd, timeout=timeout)


def run(
    dataset_dir: Path,
    direction: str,
    endpoint: dict[str, Any],
    params: dict[str, Any],
    *,
    dataset_name: str = "",
    verify: bool = True,
    keep_remote_data: bool = False,
    dest_dir: Path | None = None,
    lane: str = "",
    repeat_index: int = 0,
    seed_timeout: float | None = 1800,
    transfer_timeout: float | None = 3600,
) -> RunResult:
    ok, reason = available()
    dataset_name = dataset_name or Path(dataset_dir).name
    if not ok:
        return make_skipped(ENGINE, dataset_name, direction, params, reason, lane, "", repeat_index)

    mt = int(params.get("mt", 8))
    dataset_dir = Path(dataset_dir)
    target_root = _target_root(endpoint, dataset_name, direction)
    label = str(endpoint.get("unc_path") or endpoint.get("local_test_dir") or "smb")

    verify_root: Path | None = None
    try:
        if direction == "up":
            if target_root.exists():
                shutil.rmtree(target_root, ignore_errors=True)  # pre-clean so repeats aren't "already there"
            rc, _out, err, seconds = _robocopy(dataset_dir, target_root, mt, transfer_timeout)
        elif direction == "down":
            # Untimed seed: make sure target_root has the dataset.
            _robocopy(dataset_dir, target_root, mt, seed_timeout)
            if dest_dir is None:
                raise ValueError("dest_dir required for 'down' direction")
            if dest_dir.exists():
                shutil.rmtree(dest_dir, ignore_errors=True)
            rc, _out, err, seconds = _robocopy(target_root, dest_dir, mt, transfer_timeout)
            verify_root = dest_dir
        else:
            return make_skipped(
                ENGINE, dataset_name, direction, params,
                f"unsupported direction for robocopy runner: {direction}", lane, label, repeat_index,
            )
    except Exception as exc:  # subprocess.TimeoutExpired and friends
        return RunResult(
            engine=ENGINE, dataset=dataset_name, direction=direction, params=params,
            seconds=0.0, num_bytes=0, MB_s=0.0, verified=False, ok=False,
            reason=f"exception: {exc}", lane=lane, endpoint=label, repeat_index=repeat_index,
        )

    success = rc < ROBOCOPY_FAILURE_THRESHOLD
    num_bytes = base.manifest_bytes(dataset_dir) if success else 0
    verified = False
    if success and verify:
        if verify_root is not None:
            manifest = base.manifest_files(dataset_dir)
            verified, _detail = base.spot_check(manifest, verify_root)
        else:
            verified = True  # "up": trust robocopy's own exit code (no independent remote read-back)

    result = RunResult(
        engine=ENGINE,
        dataset=dataset_name,
        direction=direction,
        params=params,
        seconds=seconds,
        num_bytes=num_bytes,
        MB_s=base.mb_per_s(num_bytes, seconds) if success else 0.0,
        verified=verified,
        ok=success,
        reason="" if success else f"robocopy exit {rc}",
        lane=lane,
        endpoint=label,
        repeat_index=repeat_index,
        stderr_tail=base.tail(err) if not success else "",
    )

    if not keep_remote_data:
        shutil.rmtree(target_root, ignore_errors=True)

    return result
