from __future__ import annotations

from pathlib import Path

from ccbench.config import dataset_dir_for, load_config

BENCH_DIR = Path(__file__).resolve().parents[1]
EXAMPLE_CONFIG = BENCH_DIR / "bench.toml.example"


def test_load_example_config_resolves_relative_paths():
    cfg = load_config(EXAMPLE_CONFIG)
    assert Path(cfg["general"]["results_file"]).is_absolute()
    assert Path(cfg["general"]["work_dir"]).is_absolute()
    assert Path(cfg["datasets"]["large"]).is_absolute()
    assert cfg["engines"]["include"] == [
        "rclone_sftp", "rclone_smb", "robocopy_smb", "syncthing", "iperf3",
    ]


def test_load_example_config_lanes_and_params():
    cfg = load_config(EXAMPLE_CONFIG)
    assert cfg["lanes"]["A"]["direction"] == "up"
    assert cfg["lanes"]["B"]["direction"] == "down"
    assert cfg["lanes"]["C"]["direction"] == "both"
    assert cfg["params"]["rclone"]["transfers"] == [1, 4, 8, 16, 32]
    assert cfg["params"]["robocopy"]["mt"] == [1, 8, 16, 32]


def test_example_config_sweeps_chunk_size_in_kib_not_megabytes():
    """SFTP's max total packet is 256 KiB: a megabyte-unit sweep can never
    express 255k, the one value that matters on a high-RTT link."""
    cfg = load_config(EXAMPLE_CONFIG)
    rclone_params = cfg["params"]["rclone"]
    assert "sftp_chunk_size_mb" not in rclone_params
    chunk_sizes = rclone_params["sftp_chunk_size_kib"]
    assert 255 in chunk_sizes
    assert all(1 <= v <= 255 for v in chunk_sizes)


def test_example_config_defaults_to_the_non_destructive_endpoint_guard():
    cfg = load_config(EXAMPLE_CONFIG)
    assert cfg["general"]["allow_destructive_endpoint"] is False
    assert "_bench" in cfg["endpoints"]["sftp"]["remote_path"]
    assert "_bench" in cfg["endpoints"]["smb"]["remote_subpath"]
    assert "_bench" in cfg["endpoints"]["smb"]["unc_path"]


def test_dataset_dir_for_missing_key_raises():
    cfg = {"datasets": {"large": "/tmp/large"}}
    try:
        dataset_dir_for(cfg, "missing")
        assert False, "expected KeyError"
    except KeyError:
        pass


def test_defaults_applied_for_minimal_config(tmp_path):
    minimal = tmp_path / "bench.toml"
    minimal.write_text(
        "[datasets]\nlarge = \"data/large\"\n",
        encoding="utf-8",
    )
    cfg = load_config(minimal)
    assert cfg["general"]["repeats"] == 2
    assert cfg["general"]["verify"] is True
    assert cfg["general"]["keep_remote_data"] is False
