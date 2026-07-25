"""Measurement-honesty tests for the rclone runners: bytes come from rclone's
own stats, the download destination is emptied before timing, a failed seed
fails the run, and an upload is verified by a remote listing rather than by
the exit code."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from ccbench import dataset as dataset_mod
from ccbench import guard
from ccbench.runners import _rclone_common


@pytest.fixture(autouse=True)
def _reset_override():
    guard.set_allow_destructive(False)
    yield
    guard.set_allow_destructive(False)


def _dataset(tmp_path: Path) -> Path:
    ds_dir = tmp_path / "large"
    dataset_mod.generate(ds_dir, "large", seed=1, large_count=1, large_size_bytes=64 * 1024)
    return ds_dir


def _json_stats_log(bytes_moved: int) -> str:
    return "\n".join(
        [
            json.dumps({"level": "info", "msg": "starting"}),
            json.dumps({"level": "info", "msg": "Transferred: ...", "stats": {"bytes": bytes_moved // 2}}),
            json.dumps({"level": "info", "msg": "Transferred: ...", "stats": {"bytes": bytes_moved}}),
        ]
    )


def test_parse_transferred_bytes_from_json_log():
    assert _rclone_common.parse_transferred_bytes(_json_stats_log(4_294_967_296)) == 4_294_967_296


def test_parse_transferred_bytes_from_human_summary():
    stderr = (
        "Transferred:   \t    1.500 GiB / 1.500 GiB, 100%, 60.000 MiB/s, ETA 0s\n"
        "Transferred:            3 / 3, 100%\n"
    )
    assert _rclone_common.parse_transferred_bytes(stderr) == int(1.5 * 1024**3)


def test_parse_transferred_bytes_returns_none_when_absent():
    assert _rclone_common.parse_transferred_bytes("no stats here at all") is None


def _fake_transfer(monkeypatch, *, rc=0, stderr="", seconds=2.0, on_call=None):
    def fake_run_subprocess(cmd, timeout=None):
        if on_call is not None:
            on_call(cmd)
        return rc, "", stderr, seconds

    monkeypatch.setattr(_rclone_common.base, "run_subprocess", fake_run_subprocess)


def _do_up(tmp_path, **kwargs):
    return _rclone_common.do_transfer(
        engine="rclone_sftp",
        dataset_name="large",
        dataset_dir=kwargs.pop("dataset_dir"),
        direction="up",
        params={"transfers": 4},
        remote_root=kwargs.pop("remote_root", str(tmp_path / "_bench" / "remote")),
        verify=kwargs.pop("verify", False),
        keep_remote_data=False,
        dest_dir=None,
        lane="A",
        endpoint_label="test",
        repeat_index=0,
        **kwargs,
    )


def test_num_bytes_comes_from_rclone_stats_not_the_manifest(tmp_path, monkeypatch):
    ds_dir = _dataset(tmp_path)
    monkeypatch.setattr(_rclone_common, "available", lambda: (True, "rclone"))
    monkeypatch.setattr(_rclone_common, "cleanup_remote", lambda *a, **k: None)
    _fake_transfer(monkeypatch, stderr=_json_stats_log(12_345_678), seconds=2.0)

    result = _do_up(tmp_path, dataset_dir=ds_dir)

    assert result.ok
    assert result.num_bytes == 12_345_678  # not the manifest's 64 KiB
    assert result.bytes_source == "rclone-stats"
    assert result.MB_s == pytest.approx(12_345_678 / 1e6 / 2.0)


def test_unparseable_stats_fall_back_to_manifest_and_say_so(tmp_path, monkeypatch):
    ds_dir = _dataset(tmp_path)
    monkeypatch.setattr(_rclone_common, "available", lambda: (True, "rclone"))
    monkeypatch.setattr(_rclone_common, "cleanup_remote", lambda *a, **k: None)
    _fake_transfer(monkeypatch, stderr="nothing parseable")

    result = _do_up(tmp_path, dataset_dir=ds_dir)

    assert result.ok
    assert result.bytes_source == "manifest-fallback"


def test_zero_bytes_moved_is_a_failed_measurement(tmp_path, monkeypatch):
    ds_dir = _dataset(tmp_path)
    monkeypatch.setattr(_rclone_common, "available", lambda: (True, "rclone"))
    monkeypatch.setattr(_rclone_common, "cleanup_remote", lambda *a, **k: None)
    _fake_transfer(monkeypatch, stderr=_json_stats_log(0))

    result = _do_up(tmp_path, dataset_dir=ds_dir)

    assert not result.ok
    assert "0 bytes" in result.reason


def test_up_refuses_to_run_when_the_remote_is_not_a_scratch_path(tmp_path, monkeypatch):
    ds_dir = _dataset(tmp_path)
    monkeypatch.setattr(_rclone_common, "available", lambda: (True, "rclone"))
    ran = []
    _fake_transfer(monkeypatch, on_call=ran.append)

    result = _do_up(
        tmp_path, dataset_dir=ds_dir, remote_root=":sftp,host=nas:Creators_Club/Projects/2026"
    )

    assert not result.ok
    assert "refused" in result.reason
    assert ran == []  # the timed copy never started


def test_down_empties_the_destination_before_timing(tmp_path, monkeypatch):
    ds_dir = _dataset(tmp_path)
    dest = tmp_path / "_bench_down" / "0"
    dest.mkdir(parents=True)
    (dest / "leftover.bin").write_bytes(b"warm cache from the previous repeat")

    monkeypatch.setattr(_rclone_common, "available", lambda: (True, "rclone"))
    monkeypatch.setattr(_rclone_common, "seed_remote", lambda *a, **k: None)

    seen: dict[str, list[str]] = {}

    def on_call(cmd):
        seen["dest_contents"] = [p.name for p in dest.iterdir()]

    _fake_transfer(monkeypatch, stderr=_json_stats_log(999), on_call=on_call)

    result = _rclone_common.do_transfer(
        engine="rclone_sftp", dataset_name="large", dataset_dir=ds_dir, direction="down",
        params={"transfers": 4}, remote_root=str(tmp_path / "_bench" / "remote"),
        verify=False, keep_remote_data=False, dest_dir=dest, lane="B",
        endpoint_label="test", repeat_index=0,
    )

    assert result.ok
    assert seen["dest_contents"] == []  # emptied before the timed copy started


def test_down_refuses_to_empty_a_non_scratch_destination(tmp_path, monkeypatch):
    ds_dir = _dataset(tmp_path)
    dest = tmp_path / "Creators_Club" / "Projects"
    dest.mkdir(parents=True)
    (dest / "keep.mov").write_bytes(b"real media")

    monkeypatch.setattr(_rclone_common, "available", lambda: (True, "rclone"))
    monkeypatch.setattr(_rclone_common, "seed_remote", lambda *a, **k: None)
    _fake_transfer(monkeypatch)

    result = _rclone_common.do_transfer(
        engine="rclone_sftp", dataset_name="large", dataset_dir=ds_dir, direction="down",
        params={"transfers": 4}, remote_root=str(tmp_path / "_bench" / "remote"),
        verify=False, keep_remote_data=False, dest_dir=dest, lane="B",
        endpoint_label="test", repeat_index=0,
    )

    assert not result.ok
    assert "refused" in result.reason
    assert (dest / "keep.mov").exists()


def test_seed_failure_fails_the_run_loudly(tmp_path, monkeypatch):
    ds_dir = _dataset(tmp_path)
    monkeypatch.setattr(_rclone_common, "available", lambda: (True, "rclone"))

    def failing_seed(*_a, **_k):
        raise _rclone_common.SeedFailed("seed copy exit 3: connection refused")

    monkeypatch.setattr(_rclone_common, "seed_remote", failing_seed)
    _fake_transfer(monkeypatch)

    result = _rclone_common.do_transfer(
        engine="rclone_sftp", dataset_name="large", dataset_dir=ds_dir, direction="down",
        params={"transfers": 4}, remote_root=str(tmp_path / "_bench" / "remote"),
        verify=False, keep_remote_data=False, dest_dir=tmp_path / "_bench_down" / "0",
        lane="B", endpoint_label="test", repeat_index=0,
    )

    assert not result.ok
    assert "seed failed" in result.reason


def test_seed_remote_raises_on_nonzero_exit(monkeypatch, tmp_path):
    monkeypatch.setattr(
        _rclone_common.base, "run_subprocess", lambda cmd, timeout=None: (7, "", "boom", 0.1)
    )
    with pytest.raises(_rclone_common.SeedFailed):
        _rclone_common.seed_remote(tmp_path, "remote:_bench", 10)


def test_seed_remote_raises_on_timeout(monkeypatch, tmp_path):
    def timeout(cmd, timeout=None):
        raise subprocess.TimeoutExpired(cmd, 5)

    monkeypatch.setattr(_rclone_common.base, "run_subprocess", timeout)
    with pytest.raises(_rclone_common.SeedFailed):
        _rclone_common.seed_remote(tmp_path, "remote:_bench", 5)


def test_upload_verification_uses_a_remote_listing_not_the_exit_code(tmp_path, monkeypatch):
    ds_dir = _dataset(tmp_path)
    manifest = dataset_mod.read_manifest(ds_dir)
    monkeypatch.setattr(_rclone_common, "available", lambda: (True, "rclone"))
    monkeypatch.setattr(_rclone_common, "cleanup_remote", lambda *a, **k: None)
    _fake_transfer(monkeypatch, stderr=_json_stats_log(manifest["total_bytes"]))

    full_listing = {f["path"].replace("\\", "/"): f["size"] for f in manifest["files"]}

    # remote listing matches the manifest -> verified. An extra remote file
    # (the dataset's own manifest.json) must not break it.
    monkeypatch.setattr(
        _rclone_common, "remote_listing",
        lambda *a, **k: {**full_listing, "manifest.json": 123},
    )
    ok_result = _do_up(tmp_path, dataset_dir=ds_dir, verify=True)
    assert ok_result.verified
    assert ok_result.verify_method == "remote-size-listing"

    # a short/truncated file at the remote -> NOT verified, though rclone exited 0
    truncated = dict(full_listing)
    truncated[next(iter(truncated))] = 1
    monkeypatch.setattr(_rclone_common, "remote_listing", lambda *a, **k: truncated)
    bad_result = _do_up(tmp_path, dataset_dir=ds_dir, verify=True)
    assert not bad_result.verified
    assert "mismatch" in bad_result.reason

    # nothing at the remote at all -> NOT verified
    monkeypatch.setattr(_rclone_common, "remote_listing", lambda *a, **k: {})
    empty_result = _do_up(tmp_path, dataset_dir=ds_dir, verify=True)
    assert not empty_result.verified

    # listing unavailable -> honest label, never a bare verified=True
    monkeypatch.setattr(_rclone_common, "remote_listing", lambda *a, **k: None)
    unknown = _do_up(tmp_path, dataset_dir=ds_dir, verify=True)
    assert not unknown.verified
    assert unknown.verify_method == "exit-code-only"


def test_no_purge_runs_after_a_timed_transfer(tmp_path, monkeypatch):
    """Cleanup must not sit between two timed runs -- purging GBs on the NAS
    warms its cache for whatever runs next."""
    ds_dir = _dataset(tmp_path)
    monkeypatch.setattr(_rclone_common, "available", lambda: (True, "rclone"))

    order: list[str] = []
    monkeypatch.setattr(_rclone_common, "cleanup_remote", lambda *a, **k: order.append("purge"))
    _fake_transfer(monkeypatch, stderr=_json_stats_log(1000), on_call=lambda cmd: order.append("copy"))

    _do_up(tmp_path, dataset_dir=ds_dir)

    assert order == ["purge", "copy"]  # pre-clean only; nothing after the timed copy
