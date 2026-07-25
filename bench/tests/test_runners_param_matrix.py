from __future__ import annotations

import pytest

from ccbench.runners import _rclone_common, iperf3, rclone_smb, rclone_sftp, robocopy_smb, syncthing


def test_rclone_sftp_param_matrix_up_pins_multithread_to_zero():
    cfg = {"transfers": [1, 4], "multi_thread_streams": [0, 4, 8], "sftp_chunk_size_kib": [32, 255]}
    combos = rclone_sftp.param_matrix(cfg, "up")
    # SFTP cannot multi-thread uploads, so "up" pins it to an explicit 0
    assert all(c["multi_thread_streams"] == 0 for c in combos)
    # transfers x chunk_size combos, deduped
    assert len(combos) == 2 * 2
    assert {"transfers": 1, "multi_thread_streams": 0, "sftp_chunk_size_kib": 32} in combos


def test_rclone_sftp_param_matrix_down_includes_multithread_sweep():
    cfg = {"transfers": [4], "multi_thread_streams": [0, 4, 8], "sftp_chunk_size_kib": [255]}
    combos = rclone_sftp.param_matrix(cfg, "down")
    mts_values = sorted(c["multi_thread_streams"] for c in combos)
    assert mts_values == [0, 4, 8]


def test_rclone_smb_sweeps_multithread_on_up_too():
    """SMB supports multi-thread uploads; zeroing it on 'up' would hand the
    lane-A SFTP-vs-SMB comparison to SFTP by construction."""
    cfg = {"transfers": [4], "multi_thread_streams": [0, 4, 8]}
    combos = rclone_smb.param_matrix(cfg, "up")
    assert sorted(c["multi_thread_streams"] for c in combos) == [0, 4, 8]


def test_rclone_sftp_chunk_size_is_kib_and_emits_ki_suffix():
    combos = rclone_sftp.param_matrix({"sftp_chunk_size_kib": [255]}, "up")
    assert combos[0]["sftp_chunk_size_kib"] == 255
    flags = _rclone_common._flags(combos[0])
    assert "--sftp-chunk-size" in flags
    assert flags[flags.index("--sftp-chunk-size") + 1] == "255Ki"
    # never the old megabyte suffix, which SFTP's 256 KiB packet cap rejects
    assert not any(f.endswith("M") for f in flags)


def test_rclone_chunk_size_default_is_the_sftp_maximum():
    combos = rclone_sftp.param_matrix({}, "up")
    assert combos[0]["sftp_chunk_size_kib"] == _rclone_common.MAX_SFTP_CHUNK_KIB == 255


def test_legacy_megabyte_chunk_key_is_rejected_loudly():
    with pytest.raises(ValueError) as exc:
        rclone_sftp.param_matrix({"sftp_chunk_size_mb": [4, 32]}, "up")
    assert "sftp_chunk_size_kib" in str(exc.value)


def test_rclone_smb_param_matrix_has_no_chunk_size_key():
    cfg = {"transfers": [1, 4], "multi_thread_streams": [0, 4]}
    combos = rclone_smb.param_matrix(cfg, "down")
    assert all("sftp_chunk_size_kib" not in c for c in combos)
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
