from __future__ import annotations

import types
from pathlib import Path

from ccbench import dataset as dataset_mod
from ccbench import matrix
from ccbench.result import RunResult, existing_keys, make_skipped, read_results


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


def _make_scripted_runner(outcomes: list[str], call_counter: dict) -> types.SimpleNamespace:
    """A runner whose Nth call produces outcomes[N]: "ok", "skipped" or
    "failed". Anything past the end of the list repeats the last outcome."""

    def available():
        return True, "fake"

    def param_matrix(cfg, direction):
        return [{"p": 1}]

    def run(
        dataset_dir, direction, endpoint, params, *,
        dataset_name="", verify=True, keep_remote_data=False, dest_dir=None, lane="", repeat_index=0,
    ):
        outcome = outcomes[min(call_counter["n"], len(outcomes) - 1)]
        call_counter["n"] += 1
        if outcome == "skipped":
            return make_skipped(
                "fake", dataset_name, direction, params,
                "'syncthing' not found on PATH", lane, "", repeat_index,
            )
        if outcome == "failed":
            return RunResult(
                engine="fake", dataset=dataset_name, direction=direction, params=params,
                seconds=0.0, num_bytes=0, MB_s=0.0, verified=False, ok=False,
                reason="timed out against a busy NAS", lane=lane, repeat_index=repeat_index,
            )
        return RunResult(
            engine="fake", dataset=dataset_name, direction=direction, params=params,
            seconds=1.0, num_bytes=100, MB_s=50.0, verified=True, lane=lane, repeat_index=repeat_index,
        )

    return types.SimpleNamespace(ENGINE="fake", available=available, param_matrix=param_matrix, run=run)


def _register_fake(monkeypatch, runner) -> None:
    monkeypatch.setitem(matrix.REGISTRY, "fake", runner)
    monkeypatch.setattr(matrix, "FILE_ENGINES", matrix.FILE_ENGINES + ["fake"])
    monkeypatch.setitem(matrix.PARAMS_KEY, "fake", "fake")
    monkeypatch.setitem(matrix.ENDPOINT_KEY, "fake", "fake")


def _cfg(tmp_path: Path, large_dir: Path, results_file: Path) -> dict:
    return {
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


def test_a_skipped_combo_is_retried_on_resume_not_treated_as_done(tmp_path, monkeypatch):
    """SHIP-6: run the matrix with no syncthing on PATH, install it, re-run.

    Every lane-C combo was recorded skipped=True, and a resume printed
    [skip-cached] for all of them and measured nothing -- while the report still
    said "No successful runs recorded for this lane yet."
    """
    counter = {"n": 0}
    _register_fake(monkeypatch, _make_scripted_runner(["skipped", "ok"], counter))

    large_dir = tmp_path / "large"
    dataset_mod.generate(large_dir, "large", seed=1, large_count=1, large_size_bytes=1024)
    results_file = tmp_path / "results.jsonl"
    cfg = _cfg(tmp_path, large_dir, results_file)

    first = matrix.run_matrix(cfg, rerun=False, progress=_silent)
    assert [(r.ok, r.skipped) for r in first] == [(False, True)]

    # the binary is now installed: a plain resume must re-attempt it
    second = matrix.run_matrix(cfg, rerun=False, progress=_silent)
    assert [(r.ok, r.skipped) for r in second] == [(True, False)]
    assert counter["n"] == 2

    # ...and now that there IS a measurement, a third resume leaves it alone
    third = matrix.run_matrix(cfg, rerun=False, progress=_silent)
    assert third == []
    assert counter["n"] == 2


def test_a_failed_combo_is_retried_on_resume(tmp_path, monkeypatch):
    """Same rule for ok=False rows (timeout, non-zero rclone, runner crash):
    an attempt that produced no number is not a completed cell."""
    counter = {"n": 0}
    _register_fake(monkeypatch, _make_scripted_runner(["failed", "ok"], counter))

    large_dir = tmp_path / "large"
    dataset_mod.generate(large_dir, "large", seed=1, large_count=1, large_size_bytes=1024)
    results_file = tmp_path / "results.jsonl"
    cfg = _cfg(tmp_path, large_dir, results_file)

    matrix.run_matrix(cfg, rerun=False, progress=_silent)
    second = matrix.run_matrix(cfg, rerun=False, progress=_silent)

    assert [r.ok for r in second] == [True]
    assert counter["n"] == 2
    assert len(read_results(results_file)) == 2  # both attempts kept: append-only


def test_existing_keys_counts_only_measured_rows(tmp_path):
    path = tmp_path / "results.jsonl"
    rows = [
        RunResult(engine="e", dataset="d", direction="up", params={}, seconds=1.0,
                  num_bytes=1, MB_s=1.0, verified=True, lane="A", repeat_index=0),
        make_skipped("e", "d", "up", {}, "no binary", "A", "", 1),
        RunResult(engine="e", dataset="d", direction="up", params={}, seconds=0.0,
                  num_bytes=0, MB_s=0.0, verified=False, ok=False, reason="boom",
                  lane="A", repeat_index=2),
    ]
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(r.to_json() + "\n")

    assert existing_keys(path) == {rows[0].key()}
    # the unfiltered view is still available for anything that wants "attempted"
    assert existing_keys(path, measured_only=False) == {r.key() for r in rows}


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
