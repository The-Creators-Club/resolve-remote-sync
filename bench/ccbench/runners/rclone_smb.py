"""rclone against an SMB share, using an on-the-fly connection string
(https://rclone.org/smb/). Sweeps --transfers and (download-only)
--multi-thread-streams. No --sftp-chunk-size equivalent for this backend.

endpoint config (bench.toml [endpoints.smb]):
    host, share, user, password_env (name of an env var holding the plaintext
    password -- never put a plaintext password in bench.toml itself), domain
    (optional), remote_subpath
    local_test_dir  -- selftest escape hatch, see rclone_sftp.py
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

from ccbench.result import RunResult

from . import base
from ._rclone_common import available, build_param_matrix, do_transfer

ENGINE = "rclone_smb"


def param_matrix(cfg: dict[str, Any], direction: str) -> list[dict[str, Any]]:
    return build_param_matrix(cfg, direction, include_chunk_size=False)


def _obscure(password: str) -> str:
    try:
        proc = subprocess.run(
            ["rclone", "obscure", password], capture_output=True, text=True, timeout=15
        )
        if proc.returncode == 0:
            return proc.stdout.strip()
    except Exception:
        pass
    return password  # best-effort fallback; rclone will just fail auth cleanly


def _remote_spec(endpoint: dict[str, Any], dataset_name: str, direction: str) -> str:
    if endpoint.get("local_test_dir"):
        base_dir = Path(endpoint["local_test_dir"]) / "smb_selftest" / dataset_name / direction
        base_dir.mkdir(parents=True, exist_ok=True)
        return str(base_dir)

    host = endpoint["host"]
    parts = [f"host={host}"]
    if endpoint.get("user"):
        parts.append(f"user={endpoint['user']}")
    password_env = endpoint.get("password_env")
    if password_env and os.environ.get(password_env):
        parts.append(f"pass={_obscure(os.environ[password_env])}")
    if endpoint.get("domain"):
        parts.append(f"domain={endpoint['domain']}")
    conn = ",".join(parts)
    share = endpoint.get("share", "")
    remote_subpath = endpoint.get("remote_subpath", "ccbench").strip("/")
    path = "/".join(p for p in (share, remote_subpath, dataset_name, direction) if p)
    return f":smb,{conn}:{path}"


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
) -> RunResult:
    dataset_name = dataset_name or Path(dataset_dir).name
    remote_root = _remote_spec(endpoint, dataset_name, direction)
    label = endpoint.get("host", endpoint.get("local_test_dir", "smb"))
    return do_transfer(
        engine=ENGINE,
        dataset_name=dataset_name,
        dataset_dir=Path(dataset_dir),
        direction=direction,
        params=params,
        remote_root=remote_root,
        verify=verify,
        keep_remote_data=keep_remote_data,
        dest_dir=dest_dir,
        lane=lane,
        endpoint_label=str(label),
        repeat_index=repeat_index,
    )
