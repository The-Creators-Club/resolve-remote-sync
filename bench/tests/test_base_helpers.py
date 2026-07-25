from __future__ import annotations

import shutil
from pathlib import Path

from ccbench import dataset as dataset_mod
from ccbench.runners import base


def test_expand_sweep_normalizes():
    assert base.expand_sweep(None, [1, 2]) == [1, 2]
    assert base.expand_sweep(5, [1, 2]) == [5]
    assert base.expand_sweep([5, 6], [1, 2]) == [5, 6]


def test_mb_per_s_is_decimal_megabytes():
    assert base.mb_per_s(0, 10) == 0.0
    assert base.mb_per_s(1_000_000, 0) == 0.0
    assert round(base.mb_per_s(10_000_000, 2), 3) == 5.0
    # 60 Mbps must convert exactly, which is the whole point of the unit choice
    assert round(base.mb_per_s(7_500_000, 1), 3) == 7.5


def test_mib_per_s_is_binary_and_labelled_separately():
    assert round(base.mib_per_s(10 * 1024 * 1024, 2), 3) == 5.0
    assert base.mib_per_s(1_000_000, 1) != base.mb_per_s(1_000_000, 1)


def test_parse_size_handles_rclone_and_robocopy_suffixes():
    assert base.parse_size("1.5", "GiB") == int(1.5 * 1024**3)
    assert base.parse_size("262.1", "k") == int(262.1 * 1024)
    assert base.parse_size("268435456", "b") == 268435456
    assert base.parse_size("1", "parsecs") is None


def test_spot_check_ok_and_detects_corruption(tmp_path: Path):
    ds_dir = tmp_path / "ds"
    dataset_mod.generate(ds_dir, "small", seed=1, small_count=5, small_min_bytes=256, small_max_bytes=1024)
    manifest = dataset_mod.read_manifest(ds_dir)

    dest = tmp_path / "dest"
    shutil.copytree(ds_dir, dest)

    ok, detail = base.spot_check(manifest["files"], dest, n=3, seed=1)
    assert ok, detail

    # corrupt one file
    target = dest / manifest["files"][0]["path"]
    target.write_bytes(b"corrupted")
    ok2, detail2 = base.spot_check(manifest["files"], dest, n=len(manifest["files"]), seed=1)
    assert not ok2
    assert "mismatch" in detail2 or "size" in detail2


def test_spot_check_missing_file(tmp_path: Path):
    ds_dir = tmp_path / "ds"
    dataset_mod.generate(ds_dir, "small", seed=2, small_count=3, small_min_bytes=256, small_max_bytes=1024)
    manifest = dataset_mod.read_manifest(ds_dir)

    empty_dest = tmp_path / "empty"
    empty_dest.mkdir()
    ok, detail = base.spot_check(manifest["files"], empty_dest, n=2, seed=1)
    assert not ok
    assert "missing" in detail
