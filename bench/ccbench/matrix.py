"""Orchestrated benchmark matrix: reads bench.toml, runs every
engine x lane x param x repeat combination, appends each RunResult as a row
to results/results.jsonl (append-only, resumable -- combos already present
are skipped unless --rerun).

CLI: `ccbench run --config bench.toml [--rerun] [--engines e1,e2] [--lanes A,B,C]`
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path
from typing import Any

from ccbench.config import dataset_dir_for, load_config
from ccbench.result import RunResult, append_result, existing_keys
from ccbench.runners import REGISTRY

# Which bench.toml [params.<key>] / [endpoints.<key>] section each engine reads.
PARAMS_KEY = {
    "rclone_sftp": "rclone",
    "rclone_smb": "rclone",
    "robocopy_smb": "robocopy",
    "syncthing": "syncthing",
    "iperf3": "iperf3",
}
ENDPOINT_KEY = {
    "rclone_sftp": "sftp",
    "rclone_smb": "smb",
    "robocopy_smb": "smb",
    "syncthing": "syncthing",
    "iperf3": "iperf3",
}

FILE_ENGINES = ["rclone_sftp", "rclone_smb", "robocopy_smb", "syncthing"]
NETWORK_ENGINES = ["iperf3"]


def _resolve_engines(cfg: dict[str, Any], only: list[str] | None) -> list[str]:
    included = cfg.get("engines", {}).get("include", list(REGISTRY.keys()))
    engines = [e for e in included if e in REGISTRY]
    if only:
        engines = [e for e in engines if e in only]
    return engines


def _lane_directions(direction_cfg: str) -> list[str]:
    if direction_cfg == "both":
        return ["up", "down"]
    return [direction_cfg]


def run_matrix(
    cfg: dict[str, Any],
    *,
    rerun: bool = False,
    only_engines: list[str] | None = None,
    only_lanes: list[str] | None = None,
    progress: Any = print,
) -> list[RunResult]:
    results_file = Path(cfg["general"]["results_file"])
    work_dir = Path(cfg["general"]["work_dir"])
    repeats = int(cfg["general"].get("repeats", 2))
    verify = bool(cfg["general"].get("verify", True))
    keep_remote_data = bool(cfg["general"].get("keep_remote_data", False))

    engines = _resolve_engines(cfg, only_engines)
    known_keys = existing_keys(results_file)
    all_results: list[RunResult] = []

    lanes_cfg: dict[str, Any] = cfg.get("lanes", {})
    lane_names = [l for l in lanes_cfg if (only_lanes is None or l in only_lanes)]

    for lane in lane_names:
        lane_cfg = lanes_cfg[lane]
        dataset_key = lane_cfg["dataset"]
        dataset_dir = dataset_dir_for(cfg, dataset_key)
        dataset_name = dataset_dir.name
        directions = _lane_directions(lane_cfg.get("direction", "up"))

        for engine in engines:
            if engine not in FILE_ENGINES:
                continue
            runner = REGISTRY[engine]
            endpoint = cfg.get("endpoints", {}).get(ENDPOINT_KEY[engine], {})
            params_cfg = cfg.get("params", {}).get(PARAMS_KEY[engine], {})

            avail_fn = getattr(runner, "available", None)
            for direction in directions:
                combos = runner.param_matrix(params_cfg, direction)
                for params in combos:
                    for repeat_index in range(repeats):
                        key = RunResult(
                            engine=engine, dataset=dataset_name, direction=direction,
                            params=params, seconds=0, num_bytes=0, MB_s=0, verified=False,
                            lane=lane, repeat_index=repeat_index,
                        ).key()
                        if key in known_keys and not rerun:
                            progress(f"[skip-cached] lane={lane} {engine} {direction} {params} rep={repeat_index}")
                            continue

                        dest_dir = None
                        if direction == "down":
                            dest_dir = work_dir / "down" / engine / dataset_name / str(repeat_index)

                        progress(f"[run] lane={lane} {engine} {direction} {params} rep={repeat_index} ...")
                        result = runner.run(
                            dataset_dir,
                            direction,
                            endpoint,
                            params,
                            dataset_name=dataset_name,
                            verify=verify,
                            keep_remote_data=keep_remote_data,
                            dest_dir=dest_dir,
                            lane=lane,
                            repeat_index=repeat_index,
                        )
                        _report_one(result, progress)
                        append_result(results_file, result)
                        known_keys.add(result.key())
                        all_results.append(result)

                        if dest_dir is not None and dest_dir.exists():
                            shutil.rmtree(dest_dir, ignore_errors=True)

    # iperf3: not tied to a lane/dataset, just up + down against the configured host.
    if "iperf3" in engines:
        runner = REGISTRY["iperf3"]
        endpoint = cfg.get("endpoints", {}).get("iperf3", {})
        params_cfg = cfg.get("params", {}).get("iperf3", {})
        for direction in ("up", "down"):
            combos = runner.param_matrix(params_cfg, direction)
            for params in combos:
                for repeat_index in range(repeats):
                    key = RunResult(
                        engine="iperf3", dataset="network", direction=direction,
                        params=params, seconds=0, num_bytes=0, MB_s=0, verified=False,
                        lane="", repeat_index=repeat_index,
                    ).key()
                    if key in known_keys and not rerun:
                        progress(f"[skip-cached] iperf3 {direction} {params} rep={repeat_index}")
                        continue
                    progress(f"[run] iperf3 {direction} {params} rep={repeat_index} ...")
                    result = runner.run(
                        None, direction, endpoint, params,
                        dataset_name="network", verify=verify,
                        keep_remote_data=keep_remote_data, lane="", repeat_index=repeat_index,
                    )
                    _report_one(result, progress)
                    append_result(results_file, result)
                    known_keys.add(result.key())
                    all_results.append(result)

    return all_results


def _report_one(result: RunResult, progress: Any) -> None:
    if result.skipped:
        progress(f"    -> skipped: {result.reason}")
    elif not result.ok:
        progress(f"    -> FAILED: {result.reason}")
    else:
        progress(f"    -> {result.MB_s:.1f} MB/s in {result.seconds:.1f}s verified={result.verified}")


def add_subparser(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser("run", help="run the full benchmark matrix from bench.toml")
    p.add_argument("--config", required=True, help="path to bench.toml")
    p.add_argument("--rerun", action="store_true", help="re-run combos already present in results.jsonl")
    p.add_argument("--engines", help="comma-separated engine allowlist (default: all in bench.toml)")
    p.add_argument("--lanes", help="comma-separated lane allowlist, e.g. A,B,C (default: all in bench.toml)")
    p.set_defaults(func=_cli_run)


def _cli_run(args: argparse.Namespace) -> int:
    cfg = load_config(Path(args.config))
    only_engines = args.engines.split(",") if args.engines else None
    only_lanes = args.lanes.split(",") if args.lanes else None
    results = run_matrix(cfg, rerun=args.rerun, only_engines=only_engines, only_lanes=only_lanes)
    ok_count = sum(1 for r in results if r.ok)
    print(f"\n{ok_count}/{len(results)} runs completed ok. Results: {cfg['general']['results_file']}")
    return 0
