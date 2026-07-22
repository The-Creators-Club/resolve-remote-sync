"""rclone against an SFTP remote, using an on-the-fly connection string
(https://rclone.org/sftp/) so editors don't need a pre-provisioned
rclone.conf. Sweeps --transfers, --sftp-chunk-size and (download-only)
--multi-thread-streams.

endpoint config (bench.toml [endpoints.sftp]):
    host, user, key_file, port (default 22), remote_path
    local_test_dir  -- selftest escape hatch: if set, skip the sftp spec
                       entirely and use this local directory as the "remote"
                       (proves the harness plumbing without a real sftp server)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ccbench.result import RunResult

from . import base
from ._rclone_common import available, build_param_matrix, do_transfer

ENGINE = "rclone_sftp"


def param_matrix(cfg: dict[str, Any], direction: str) -> list[dict[str, Any]]:
    return build_param_matrix(cfg, direction, include_chunk_size=True)


def _remote_spec(endpoint: dict[str, Any], dataset_name: str, direction: str) -> str:
    if endpoint.get("local_test_dir"):
        base_dir = Path(endpoint["local_test_dir"]) / "sftp_selftest" / dataset_name / direction
        base_dir.mkdir(parents=True, exist_ok=True)
        return str(base_dir)

    host = endpoint["host"]
    parts = [f"host={host}"]
    if endpoint.get("user"):
        parts.append(f"user={endpoint['user']}")
    if endpoint.get("key_file"):
        parts.append(f"key_file={endpoint['key_file']}")
    parts.append(f"port={endpoint.get('port', 22)}")
    conn = ",".join(parts)
    remote_path = endpoint.get("remote_path", "ccbench").rstrip("/")
    path = f"{remote_path}/{dataset_name}/{direction}"
    return f":sftp,{conn}:{path}"


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
    label = endpoint.get("host", endpoint.get("local_test_dir", "sftp"))
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
