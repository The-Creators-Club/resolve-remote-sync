from __future__ import annotations

import types
from pathlib import Path

from ccbench import dataset as dataset_mod
from ccbench import matrix
from ccbench.result import RunResult, read_results


def _make_fake_runner(call_counter: dict) -> types.SimpleNamespace:
    def available():
        return True, "fake"

    def param_matrix(cfg, direction):
        return [{"p": 1}]

    def run(
        dataset_dir, direction, endpoint, params, *,
        dataset_name="", verify=True, keep_remote_data=False, dest_dir=None, lane="", repeat_index=0,
    ):
        call_counter["n"] += 1
        return RunResult(
            engine="fake", dataset=dataset_name, direction=direction, params=params,
            seconds=1.0, num_bytes=100, MB_s=50.0, verified=True, lane=lane, repeat_index=repeat_index,
        )

    return types.SimpleNamespace(ENGINE="fake", available=available, param_matrix=param_matrix, run=run)


def _silent(*_a, **_k) -> None:
    pass


def test_run_matrix_resume_skips_existing_and_rerun_forces(tmp_path, monkeypatch):
    call_counter = {"n": 0}
    fake = _make_fake_runner(call_counter)
    monkeypatch.setitem(matrix.REGISTRY, "fake", fake)
    monkeypatch.setattr(matrix, "FILE_ENGINES", matrix.FILE_ENGINES + ["fake"])
    monkeypatch.setitem(matrix.PARAMS_KEY, "fake", "fake")
    monkeypatch.setitem(matrix.ENDPOINT_KEY, "fake", "fake")

    large_dir = tmp_path / "large"
    dataset_mod.generate(large_dir, "large", seed=1, large_count=1, large_size_bytes=1024)

    results_file = tmp_path / "results.jsonl"
    cfg = {
        "general": {
            "results_file": str(results_file),
            "work_dir": str(tmp_path / "work"),
            "repeats": 1,
            "verify": True,
            "keep_remote_data": False,
        },
        "datasets": {"large": str(large_dir)},
        "lanes": {"A": {"dataset": "large", "direction": "up"}},
        "engines": {"include": ["fake"]},
        "endpoints": {"fake": {}},
        "params": {"fake": {}},
    }

    results1 = matrix.run_matrix(cfg, rerun=False, progress=_silent)
    assert len(results1) == 1
    assert call_counter["n"] == 1

    # second run without --rerun should skip the already-recorded combo
    results2 = matrix.run_matrix(cfg, rerun=False, progress=_silent)
    assert len(results2) == 0
    assert call_counter["n"] == 1

    # --rerun forces it to run again
    results3 = matrix.run_matrix(cfg, rerun=True, progress=_silent)
    assert len(results3) == 1
    assert call_counter["n"] == 2

    all_rows = read_results(results_file)
    assert len(all_rows) == 2  # append-only: run1 appended, run2 skipped, run3 (--rerun) appended again


def test_run_matrix_respects_engine_and_lane_filters(tmp_path, monkeypatch):
    call_counter = {"n": 0}
    fake = _make_fake_runner(call_counter)
    monkeypatch.setitem(matrix.REGISTRY, "fake", fake)
    monkeypatch.setattr(matrix, "FILE_ENGINES", matrix.FILE_ENGINES + ["fake"])
    monkeypatch.setitem(matrix.PARAMS_KEY, "fake", "fake")
    monkeypatch.setitem(matrix.ENDPOINT_KEY, "fake", "fake")

    large_dir = tmp_path / "large"
    small_dir = tmp_path / "small"
    dataset_mod.generate(large_dir, "large", seed=1, large_count=1, large_size_bytes=1024)
    dataset_mod.generate(small_dir, "small", seed=1, small_count=3, small_min_bytes=256, small_max_bytes=512)

    cfg = {
        "general": {
            "results_file": str(tmp_path / "results.jsonl"),
            "work_dir": str(tmp_path / "work"),
            "repeats": 1,
            "verify": True,
            "keep_remote_data": False,
        },
        "datasets": {"large": str(large_dir), "small": str(small_dir)},
        "lanes": {
            "A": {"dataset": "large", "direction": "up"},
            "C": {"dataset": "small", "direction": "both"},
        },
        "engines": {"include": ["fake"]},
        "endpoints": {"fake": {}},
        "params": {"fake": {}},
    }

    results = matrix.run_matrix(cfg, rerun=False, only_lanes=["A"], progress=_silent)
    assert len(results) == 1
    assert results[0].lane == "A"

    results_other_engine = matrix.run_matrix(
        cfg, rerun=False, only_engines=["nonexistent"], only_lanes=["C"], progress=_silent
    )
    assert results_other_engine == []
