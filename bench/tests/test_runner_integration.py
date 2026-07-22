"""Integration tests against real binaries, when present on PATH. Any binary
that's missing is skipped cleanly with a one-line reason instead of failing
the suite -- this harness has to be runnable (and testable) on a machine that
only has some of the transport tools installed.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from ccbench import dataset as dataset_mod
from ccbench.runners import iperf3, rclone_sftp, robocopy_smb, syncthing


def _tiny_dataset(tmp_path: Path) -> Path:
    ds_dir = tmp_path / "large"
    dataset_mod.generate(ds_dir, "large", seed=1, large_count=1, large_size_bytes=256 * 1024)
    return ds_dir


def test_robocopy_availability_matches_shutil_which():
    ok, reason = robocopy_smb.available()
    if shutil.which("robocopy") is None:
        assert not ok
    else:
        assert ok, reason


@pytest.mark.skipif(shutil.which("robocopy") is None, reason="robocopy not found on PATH")
def test_robocopy_real_roundtrip(tmp_path):
    ds_dir = _tiny_dataset(tmp_path)
    remote_dir = tmp_path / "remote"
    dest_dir = tmp_path / "dest"

    up_result = robocopy_smb.run(
        ds_dir, "up", {"local_test_dir": str(remote_dir)}, {"mt": 4},
        dataset_name="large", verify=True, keep_remote_data=True,
    )
    assert up_result.ok, up_result.reason
    assert up_result.verified
    assert up_result.MB_s >= 0

    down_result = robocopy_smb.run(
        ds_dir, "down", {"local_test_dir": str(remote_dir)}, {"mt": 4},
        dataset_name="large", verify=True, dest_dir=dest_dir, keep_remote_data=False,
    )
    assert down_result.ok, down_result.reason
    assert down_result.verified


def test_rclone_sftp_availability():
    ok, reason = rclone_sftp.available()
    if shutil.which("rclone") is None:
        pytest.skip(f"rclone not found on PATH: {reason}")
    assert ok


@pytest.mark.skipif(shutil.which("rclone") is None, reason="rclone not found on PATH")
def test_rclone_sftp_local_test_dir_roundtrip(tmp_path):
    ds_dir = _tiny_dataset(tmp_path)
    remote_base = tmp_path / "rclone_remote"
    result = rclone_sftp.run(
        ds_dir, "up", {"local_test_dir": str(remote_base)}, {"transfers": 1, "multi_thread_streams": 0},
        dataset_name="large", verify=True, keep_remote_data=True,
    )
    assert result.ok, result.reason


def test_syncthing_availability_reports_reason_when_absent():
    ok, reason = syncthing.available({})
    if shutil.which("syncthing") is None:
        assert not ok
        assert reason
        pytest.skip(f"syncthing not found on PATH: {reason}")
    assert ok


def test_iperf3_availability_reports_reason_when_absent():
    ok, reason = iperf3.available()
    if shutil.which("iperf3") is None:
        assert not ok
        assert reason
        pytest.skip(f"iperf3 not found on PATH: {reason}")
    assert ok
