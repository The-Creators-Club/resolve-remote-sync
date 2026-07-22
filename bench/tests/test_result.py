from __future__ import annotations

from pathlib import Path

from ccbench.result import RunResult, append_result, existing_keys, make_skipped, read_results


def _sample(engine="rclone_sftp", direction="up", repeat_index=0, MB_s=100.0) -> RunResult:
    return RunResult(
        engine=engine,
        dataset="large",
        direction=direction,
        params={"transfers": 4},
        seconds=10.0,
        num_bytes=1_000_000_000,
        MB_s=MB_s,
        verified=True,
        lane="A",
        repeat_index=repeat_index,
    )


def test_append_and_read_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "results.jsonl"
    r1 = _sample()
    r2 = _sample(repeat_index=1, MB_s=105.0)
    append_result(path, r1)
    append_result(path, r2)

    loaded = read_results(path)
    assert len(loaded) == 2
    assert loaded[0].engine == "rclone_sftp"
    assert loaded[0].MB_s == 100.0
    assert loaded[1].MB_s == 105.0


def test_read_results_missing_file_returns_empty(tmp_path: Path) -> None:
    assert read_results(tmp_path / "nope.jsonl") == []


def test_key_is_stable_and_distinguishes_params() -> None:
    r1 = _sample()
    r2 = _sample()
    assert r1.key() == r2.key()

    r3 = RunResult(
        engine="rclone_sftp", dataset="large", direction="up",
        params={"transfers": 8}, seconds=1, num_bytes=1, MB_s=1, verified=True,
        lane="A", repeat_index=0,
    )
    assert r1.key() != r3.key()


def test_key_distinguishes_repeat_index() -> None:
    r1 = _sample(repeat_index=0)
    r2 = _sample(repeat_index=1)
    assert r1.key() != r2.key()


def test_existing_keys_supports_resume(tmp_path: Path) -> None:
    path = tmp_path / "results.jsonl"
    r1 = _sample(repeat_index=0)
    append_result(path, r1)

    keys = existing_keys(path)
    assert r1.key() in keys

    r2 = _sample(repeat_index=1)
    assert r2.key() not in keys


def test_make_skipped() -> None:
    r = make_skipped("syncthing", "small", "up", {}, "syncthing not found on PATH", lane="C")
    assert r.skipped is True
    assert r.ok is False
    assert r.verified is False
    assert r.MB_s == 0.0
    assert "not found" in r.reason


def test_append_result_creates_parent_dir(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "dir" / "results.jsonl"
    append_result(path, _sample())
    assert path.exists()
