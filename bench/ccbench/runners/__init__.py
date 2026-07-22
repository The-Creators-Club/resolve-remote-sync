"""Runner registry.

Every runner module exposes the common functional interface described in
ccbench/runners/base.py:

    ENGINE: str
    available() -> (bool, str)
    param_matrix(cfg: dict, direction: str) -> list[dict]
    run(dataset_dir, direction, endpoint, params, *, verify=True,
        keep_remote_data=False) -> RunResult

matrix.py looks runners up by name via REGISTRY.
"""

from __future__ import annotations

from types import ModuleType

from . import iperf3, rclone_smb, rclone_sftp, robocopy_smb, syncthing

REGISTRY: dict[str, ModuleType] = {
    rclone_sftp.ENGINE: rclone_sftp,
    rclone_smb.ENGINE: rclone_smb,
    robocopy_smb.ENGINE: robocopy_smb,
    syncthing.ENGINE: syncthing,
    iperf3.ENGINE: iperf3,
}

__all__ = ["REGISTRY"]
