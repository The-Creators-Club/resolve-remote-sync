from __future__ import annotations

from ccbench.runners import iperf3, rclone_smb, rclone_sftp, robocopy_smb, syncthing


def test_rclone_sftp_param_matrix_up_drops_multithread():
    cfg = {"transfers": [1, 4], "multi_thread_streams": [0, 4, 8], "sftp_chunk_size_mb": [4, 32]}
    combos = rclone_sftp.param_matrix(cfg, "up")
    # up direction: multi_thread_streams collapses to a single 0 regardless of sweep
    assert all(c["multi_thread_streams"] == 0 for c in combos)
    # transfers x chunk_size combos, deduped
    assert len(combos) == 2 * 2
    assert {"transfers": 1, "multi_thread_streams": 0, "sftp_chunk_size_mb": 4} in combos


def test_rclone_sftp_param_matrix_down_includes_multithread_sweep():
    cfg = {"transfers": [4], "multi_thread_streams": [0, 4, 8], "sftp_chunk_size_mb": [32]}
    combos = rclone_sftp.param_matrix(cfg, "down")
    mts_values = sorted(c["multi_thread_streams"] for c in combos)
    assert mts_values == [0, 4, 8]


def test_rclone_smb_param_matrix_has_no_chunk_size_key():
    cfg = {"transfers": [1, 4], "multi_thread_streams": [0, 4]}
    combos = rclone_smb.param_matrix(cfg, "down")
    assert all("sftp_chunk_size_mb" not in c for c in combos)
    assert len(combos) == 2 * 2


def test_rclone_defaults_when_cfg_empty():
    combos = rclone_sftp.param_matrix({}, "up")
    assert combos  # at least one default combo
    assert combos[0]["transfers"] == 4


def test_robocopy_param_matrix_sweeps_mt():
    combos = robocopy_smb.param_matrix({"mt": [1, 8, 16, 32]}, "up")
    assert [c["mt"] for c in combos] == [1, 8, 16, 32]


def test_robocopy_param_matrix_defaults():
    combos = robocopy_smb.param_matrix({}, "up")
    assert [c["mt"] for c in combos] == [1, 8, 16, 32]


def test_iperf3_param_matrix_sweeps_parallel_and_carries_duration():
    combos = iperf3.param_matrix({"parallel": [1, 4, 8], "duration_s": 5}, "up")
    assert [c["parallel"] for c in combos] == [1, 4, 8]
    assert all(c["duration_s"] == 5 for c in combos)


def test_syncthing_param_matrix_is_single_combo():
    assert syncthing.param_matrix({}, "up") == [{}]
    assert syncthing.param_matrix({"anything": 1}, "down") == [{}]
