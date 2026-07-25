"""Matrix-level guarantees: one runner crash doesn't kill the matrix, the lane
is carried explicitly onto every row, and remote cleanup happens once at the
end rather than between two timed runs."""

from __future__ import annotations

import types

from ccbench import dataset as dataset_mod
from ccbench import guard, matrix
from ccbench.result import RunResult, read_results


def _silent(*_a, **_k) -> None:
    pass


def _cfg(tmp_path, dataset_dirs, lanes, repeats=1, **general):
    base_general = {
        "results_file": str(tmp_path / "results.jsonl"),
        "work_dir": str(tmp_path / "work"),
        "repeats": repeats,
        "verify": True,
        "keep_remote_data": False,
    }
    base_general.update(general)
    return {
        "general": base_general,
        "datasets": dataset_dirs,
        "lanes": lanes,
        "engines": {"include": ["fake"]},
        "endpoints": {"fake": {"remote_path": "Creators_Club/_bench"}},
        "params": {"fake": {}},
    }


def _register(monkeypatch, runner) -> None:
    monkeypatch.setitem(matrix.REGISTRY, "fake", runner)
    monkeypatch.setattr(matrix, "FILE_ENGINES", matrix.FILE_ENGINES + ["fake"])
    monkeypatch.setitem(matrix.PARAMS_KEY, "fake", "fake")
    monkeypatch.setitem(matrix.ENDPOINT_KEY, "fake", "fake")


def _dataset(tmp_path, name="large"):
    ds = tmp_path / name
    dataset_mod.generate(ds, "large", seed=1, large_count=1, large_size_bytes=1024)
    return ds


def test_a_crashing_runner_fails_one_cell_and_the_matrix_continues(tmp_path, monkeypatch):
    calls = {"n": 0}

    def run(dataset_dir, direction, endpoint, params, *, dataset_name="", verify=True,
            keep_remote_data=False, dest_dir=None, lane="", repeat_index=0):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("rclone runner exploded")
        return RunResult(
            engine="fake", dataset=dataset_name, direction=direction, params=params,
            seconds=1.0, num_bytes=100, MB_s=50.0, verified=True, lane=lane,
            repeat_index=repeat_index,
        )

    runner = types.SimpleNamespace(
        ENGINE="fake", available=lambda: (True, "fake"),
        param_matrix=lambda cfg, direction: [{"p": 1}], run=run,
    )
    _register(monkeypatch, runner)

    ds = _dataset(tmp_path)
    cfg = _cfg(tmp_path, {"large": str(ds)}, {"A": {"dataset": "large", "direction": "up"}}, repeats=2)

    results = matrix.run_matrix(cfg, progress=_silent)

    assert len(results) == 2  # the crash did not abort the remaining repeat
    crashed = [r for r in results if not r.ok]
    assert len(crashed) == 1
    assert "runner crashed: RuntimeError" in crashed[0].reason
    assert "rclone runner exploded" in crashed[0].stderr_tail
    assert crashed[0].lane == "A"
    # and the failure is persisted, not just returned
    assert any("runner crashed" in r.reason for r in read_results(tmp_path / "results.jsonl"))


def test_a_bad_params_section_fails_that_engine_only(tmp_path, monkeypatch):
    def param_matrix(cfg, direction):
        raise ValueError("sftp_chunk_size_mb is no longer supported")

    runner = types.SimpleNamespace(
        ENGINE="fake", available=lambda: (True, "fake"), param_matrix=param_matrix,
        run=lambda *a, **k: None,
    )
    _register(monkeypatch, runner)

    ds = _dataset(tmp_path)
    cfg = _cfg(tmp_path, {"large": str(ds)}, {"A": {"dataset": "large", "direction": "up"}})

    results = matrix.run_matrix(cfg, progress=_silent)
    assert len(results) == 1
    assert not results[0].ok
    assert "sftp_chunk_size_mb" in results[0].reason


def test_lane_is_written_onto_every_row_from_bench_toml(tmp_path, monkeypatch):
    def run(dataset_dir, direction, endpoint, params, *, dataset_name="", verify=True,
            keep_remote_data=False, dest_dir=None, lane="", repeat_index=0):
        return RunResult(
            engine="fake", dataset=dataset_name, direction=direction, params=params,
            seconds=1.0, num_bytes=100, MB_s=50.0, verified=True, lane=lane,
            repeat_index=repeat_index,
        )

    runner = types.SimpleNamespace(
        ENGINE="fake", available=lambda: (True, "fake"),
        param_matrix=lambda cfg, direction: [{"p": 1}], run=run,
    )
    _register(monkeypatch, runner)

    # dataset dir deliberately named so substring classification would say "A"
    ds = _dataset(tmp_path, name="large")
    cfg = _cfg(tmp_path, {"large": str(ds)}, {"C": {"dataset": "large", "direction": "up"}})

    results = matrix.run_matrix(cfg, progress=_silent)
    assert [r.lane for r in results] == ["C"]


def test_download_destination_lives_under_a_bench_scratch_dir(tmp_path, monkeypatch):
    seen: dict[str, object] = {}

    def run(dataset_dir, direction, endpoint, params, *, dataset_name="", verify=True,
            keep_remote_data=False, dest_dir=None, lane="", repeat_index=0):
        seen["dest_dir"] = dest_dir
        return RunResult(
            engine="fake", dataset=dataset_name, direction=direction, params=params,
            seconds=1.0, num_bytes=100, MB_s=50.0, verified=True, lane=lane,
            repeat_index=repeat_index,
        )

    runner = types.SimpleNamespace(
        ENGINE="fake", available=lambda: (True, "fake"),
        param_matrix=lambda cfg, direction: [{"p": 1}], run=run,
    )
    _register(monkeypatch, runner)

    ds = _dataset(tmp_path)
    cfg = _cfg(tmp_path, {"large": str(ds)}, {"B": {"dataset": "large", "direction": "down"}})

    matrix.run_matrix(cfg, progress=_silent)
    assert guard.is_scratch_path(seen["dest_dir"])


def test_remote_cleanup_runs_once_after_the_matrix_not_between_runs(tmp_path, monkeypatch):
    order: list[str] = []

    def run(dataset_dir, direction, endpoint, params, *, dataset_name="", verify=True,
            keep_remote_data=False, dest_dir=None, lane="", repeat_index=0):
        order.append(f"run{repeat_index}")
        return RunResult(
            engine="fake", dataset=dataset_name, direction=direction, params=params,
            seconds=1.0, num_bytes=100, MB_s=50.0, verified=True, lane=lane,
            repeat_index=repeat_index,
        )

    runner = types.SimpleNamespace(
        ENGINE="fake", available=lambda: (True, "fake"),
        param_matrix=lambda cfg, direction: [{"p": 1}], run=run,
        cleanup_endpoint=lambda endpoint, dataset_name, direction: order.append("cleanup"),
    )
    _register(monkeypatch, runner)

    ds = _dataset(tmp_path)
    cfg = _cfg(tmp_path, {"large": str(ds)}, {"A": {"dataset": "large", "direction": "up"}}, repeats=3)

    matrix.run_matrix(cfg, progress=_silent)
    assert order == ["run0", "run1", "run2", "cleanup"]


def test_keep_remote_data_skips_cleanup_entirely(tmp_path, monkeypatch):
    order: list[str] = []
    runner = types.SimpleNamespace(
        ENGINE="fake", available=lambda: (True, "fake"),
        param_matrix=lambda cfg, direction: [{"p": 1}],
        run=lambda *a, **k: RunResult(
            engine="fake", dataset="large", direction="up", params={"p": 1},
            seconds=1.0, num_bytes=100, MB_s=50.0, verified=True, lane="A",
        ),
        cleanup_endpoint=lambda endpoint, dataset_name, direction: order.append("cleanup"),
    )
    _register(monkeypatch, runner)

    ds = _dataset(tmp_path)
    cfg = _cfg(
        tmp_path, {"large": str(ds)}, {"A": {"dataset": "large", "direction": "up"}},
        keep_remote_data=True,
    )

    matrix.run_matrix(cfg, progress=_silent)
    assert order == []


def test_refused_cleanup_is_reported_and_does_not_raise(tmp_path, monkeypatch):
    def cleanup_endpoint(endpoint, dataset_name, direction):
        guard.assert_scratch_path("Creators_Club/Projects/2026", action="rclone purge")

    runner = types.SimpleNamespace(
        ENGINE="fake", available=lambda: (True, "fake"),
        param_matrix=lambda cfg, direction: [{"p": 1}],
        run=lambda *a, **k: RunResult(
            engine="fake", dataset="large", direction="up", params={"p": 1},
            seconds=1.0, num_bytes=100, MB_s=50.0, verified=True, lane="A",
        ),
        cleanup_endpoint=cleanup_endpoint,
    )
    _register(monkeypatch, runner)

    messages: list[str] = []
    ds = _dataset(tmp_path)
    cfg = _cfg(tmp_path, {"large": str(ds)}, {"A": {"dataset": "large", "direction": "up"}})

    matrix.run_matrix(cfg, progress=messages.append)
    assert any("refused" in m for m in messages)


def test_allow_destructive_endpoint_is_off_unless_configured(tmp_path, monkeypatch):
    runner = types.SimpleNamespace(
        ENGINE="fake", available=lambda: (True, "fake"),
        param_matrix=lambda cfg, direction: [{"p": 1}],
        run=lambda *a, **k: RunResult(
            engine="fake", dataset="large", direction="up", params={"p": 1},
            seconds=1.0, num_bytes=100, MB_s=50.0, verified=True, lane="A",
        ),
    )
    _register(monkeypatch, runner)
    guard.set_allow_destructive(True)  # leak from a previous run

    ds = _dataset(tmp_path)
    cfg = _cfg(tmp_path, {"large": str(ds)}, {"A": {"dataset": "large", "direction": "up"}})
    matrix.run_matrix(cfg, progress=_silent)
    assert guard.destructive_allowed() is False

    cfg["general"]["allow_destructive_endpoint"] = True
    matrix.run_matrix(cfg, rerun=True, progress=_silent)
    assert guard.destructive_allowed() is True
    guard.set_allow_destructive(False)


def test_cli_flag_sets_the_destructive_override(tmp_path, monkeypatch):
    import argparse

    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers()
    matrix.add_subparser(subparsers)

    args = parser.parse_args(["run", "--config", "bench.toml", "--allow-destructive-endpoint"])
    assert args.allow_destructive_endpoint is True

    args_default = parser.parse_args(["run", "--config", "bench.toml"])
    assert args_default.allow_destructive_endpoint is False


def test_iperf3_rows_carry_the_net_lane(tmp_path, monkeypatch):
    runner = types.SimpleNamespace(
        ENGINE="iperf3", available=lambda: (True, "iperf3"),
        param_matrix=lambda cfg, direction: [{"parallel": 1}],
        run=lambda dataset_dir, direction, endpoint, params, **kw: RunResult(
            engine="iperf3", dataset="network", direction=direction, params=params,
            seconds=1.0, num_bytes=100, MB_s=50.0, verified=True, lane=kw.get("lane", ""),
            repeat_index=kw.get("repeat_index", 0),
        ),
    )
    monkeypatch.setitem(matrix.REGISTRY, "iperf3", runner)

    cfg = _cfg(tmp_path, {}, {})
    cfg["engines"]["include"] = ["iperf3"]
    cfg["params"]["iperf3"] = {"parallel": [1]}
    cfg["endpoints"]["iperf3"] = {"host": "100.1.1.1"}

    results = matrix.run_matrix(cfg, progress=_silent)
    assert results
    assert all(r.lane == "net" for r in results)
