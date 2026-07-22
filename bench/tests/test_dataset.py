from __future__ import annotations

import gzip
import io
from pathlib import Path

from ccbench import dataset


def test_generate_small_is_deterministic(tmp_path: Path) -> None:
    out1 = tmp_path / "a"
    out2 = tmp_path / "b"
    dataset.generate(out1, "small", seed=42, small_count=5, small_min_bytes=1024, small_max_bytes=4096)
    dataset.generate(out2, "small", seed=42, small_count=5, small_min_bytes=1024, small_max_bytes=4096)

    m1 = dataset.read_manifest(out1)
    m2 = dataset.read_manifest(out2)

    files1 = {f["path"]: (f["size"], f["sha256"]) for f in m1["files"]}
    files2 = {f["path"]: (f["size"], f["sha256"]) for f in m2["files"]}
    assert files1 == files2
    assert len(files1) == 5


def test_generate_different_seed_differs(tmp_path: Path) -> None:
    out1 = tmp_path / "a"
    out2 = tmp_path / "b"
    dataset.generate(out1, "small", seed=1, small_count=5, small_min_bytes=1024, small_max_bytes=4096)
    dataset.generate(out2, "small", seed=2, small_count=5, small_min_bytes=1024, small_max_bytes=4096)

    m1 = dataset.read_manifest(out1)
    m2 = dataset.read_manifest(out2)
    hashes1 = sorted(f["sha256"] for f in m1["files"])
    hashes2 = sorted(f["sha256"] for f in m2["files"])
    assert hashes1 != hashes2


def test_manifest_matches_files_on_disk(tmp_path: Path) -> None:
    out = tmp_path / "ds"
    dataset.generate(
        out, "both", seed=7,
        large_count=2, large_size_bytes=64 * 1024,
        small_count=10, small_min_bytes=1024, small_max_bytes=8192,
    )
    manifest = dataset.read_manifest(out)
    assert manifest["file_count"] == len(manifest["files"]) == 12
    assert manifest["total_bytes"] == sum(f["size"] for f in manifest["files"])

    for rec in manifest["files"]:
        path = out / rec["path"]
        assert path.exists(), f"missing {rec['path']}"
        assert path.stat().st_size == rec["size"]
        from ccbench.runners.base import sha256_file

        assert sha256_file(path) == rec["sha256"]

    # large/small profile prefixes present
    profiles = {rec["path"].split("/")[0] for rec in manifest["files"]}
    assert profiles == {"large", "small"}


def test_large_extensions_and_count(tmp_path: Path) -> None:
    out = tmp_path / "large_only"
    dataset.generate(out, "large", seed=3, large_count=3, large_size_bytes=32 * 1024)
    manifest = dataset.read_manifest(out)
    assert manifest["file_count"] == 3
    exts = sorted({Path(f["path"]).suffix for f in manifest["files"]})
    assert exts == [".braw", ".mov"]


def test_small_nested_three_levels_deep(tmp_path: Path) -> None:
    out = tmp_path / "small_only"
    dataset.generate(out, "small", seed=9, small_count=15, small_min_bytes=512, small_max_bytes=2048)
    manifest = dataset.read_manifest(out)
    for rec in manifest["files"]:
        parts = rec["path"].split("/")
        # small/<L1>/<L2>/<L3>/filename.ext == 5 path segments
        assert len(parts) == 5, rec["path"]
    exts = {Path(f["path"]).suffix for f in manifest["files"]}
    assert exts <= {".wav", ".png", ".aep", ".srt", ".psd"}


def test_data_is_incompressible(tmp_path: Path) -> None:
    """gzip a sample file; compressed size must stay close to original size
    (ratio > 0.99) -- proves it's not zeros/sparse and can't be faked by a
    transport that special-cases compressible or sparse data."""
    out = tmp_path / "sample"
    size = 4 * 1024 * 1024  # 4 MiB, big enough to be a meaningful gzip sample
    dataset.generate(out, "large", seed=123, large_count=1, large_size_bytes=size)
    manifest = dataset.read_manifest(out)
    sample_path = out / manifest["files"][0]["path"]

    raw = sample_path.read_bytes()
    assert len(raw) == size

    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=9) as gz:
        gz.write(raw)
    compressed_size = buf.tell()

    ratio = compressed_size / len(raw)
    assert ratio > 0.99, f"data compressed too well (ratio={ratio:.4f}), not incompressible enough"


def test_zeros_would_fail_the_incompressibility_bar() -> None:
    """Sanity check on the test itself: all-zero data (the thing we must NOT
    generate) compresses far below the 0.99 bar, so the assertion above is
    actually discriminating."""
    raw = bytes(4 * 1024 * 1024)
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=9) as gz:
        gz.write(raw)
    ratio = buf.tell() / len(raw)
    assert ratio < 0.05
