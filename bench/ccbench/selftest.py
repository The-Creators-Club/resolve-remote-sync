"""`ccbench selftest` -- proves the harness end-to-end entirely locally, with
no network calls to any real endpoint:

- tiny dataset (a couple MB, not GB) generated via the real dataset generator
- rclone local<->local "remote" (via each rclone runner's local_test_dir
  escape hatch) if rclone is present
- robocopy to a local directory (Windows only, works identically to a UNC
  path) if robocopy is present
- an ephemeral Syncthing pair (already fully self-contained/localhost by
  design) if the syncthing binary is present
- a local iperf3 server + client pair (127.0.0.1) if iperf3 is present

Any binary that's absent is skipped with a one-line reason -- this command
never crashes just because some transport tooling isn't installed on the
machine it's run on. This is the harness's own acceptance test.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from ccbench import dataset, matrix, report
from ccbench.runners import base as runner_base
from ccbench.runners.iperf3 import available as iperf3_available


def run_selftest(
    base_dir: Path | None = None,
    keep: bool = False,
    progress: Any = print,
) -> dict[str, Any]:
    tmp_root = Path(base_dir) if base_dir else Path(tempfile.mkdtemp(prefix="ccbench-selftest-"))
    data_dir = tmp_root / "data"
    work_dir = tmp_root / "work"
    results_file = tmp_root / "results.jsonl"

    progress(f"selftest workspace: {tmp_root}")

    large_dir = data_dir / "large"
    small_dir = data_dir / "small"
    progress("generating tiny local datasets ...")
    dataset.generate(large_dir, "large", seed=1, large_count=2, large_size_bytes=2 * 1024 * 1024)
    dataset.generate(small_dir, "small", seed=1, small_count=20, small_min_bytes=10 * 1024, small_max_bytes=200 * 1024)

    cfg: dict[str, Any] = {
        "general": {
            "results_file": str(results_file),
            "repeats": 1,
            "verify": True,
            "keep_remote_data": False,
            "work_dir": str(work_dir),
        },
        "datasets": {"large": str(large_dir), "small": str(small_dir)},
        "lanes": {
            "A": {"dataset": "large", "direction": "up"},
            "B": {"dataset": "large", "direction": "down"},
            "C": {"dataset": "small", "direction": "both"},
        },
        "engines": {"include": ["rclone_sftp", "rclone_smb", "robocopy_smb", "syncthing", "iperf3"]},
        "endpoints": {
            "sftp": {"local_test_dir": str(work_dir / "sftp_target")},
            "smb": {"local_test_dir": str(work_dir / "smb_target")},
            "syncthing": {},
            "iperf3": {},
        },
        "params": {
            "rclone": {"transfers": [1, 4], "multi_thread_streams": [0, 4], "sftp_chunk_size_mb": [4]},
            "robocopy": {"mt": [1, 4]},
            "iperf3": {"parallel": [1], "duration_s": 2},
        },
    }

    iperf3_ok, iperf3_reason = iperf3_available()
    iperf3_server: subprocess.Popen | None = None
    if iperf3_ok:
        port = runner_base.free_port()
        progress(f"starting local iperf3 server on 127.0.0.1:{port} for selftest ...")
        iperf3_server = subprocess.Popen(
            ["iperf3", "-s", "-p", str(port)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        time.sleep(0.5)
        cfg["endpoints"]["iperf3"] = {"host": "127.0.0.1", "port": port}
    else:
        progress(f"iperf3 not available ({iperf3_reason}) -- iperf3 checks will show as skipped")

    try:
        results = matrix.run_matrix(cfg, rerun=True, progress=progress)
    finally:
        if iperf3_server is not None:
            iperf3_server.terminate()
            try:
                iperf3_server.wait(timeout=5)
            except Exception:  # noqa: BLE001
                iperf3_server.kill()

    report_md = report.render_report(results)
    report_path = tmp_root / "report.md"
    report_path.write_text(report_md, encoding="utf-8")

    progress("")
    progress(report_md)

    if not keep:
        shutil.rmtree(data_dir, ignore_errors=True)
        shutil.rmtree(work_dir, ignore_errors=True)

    return {
        "results": results,
        "report": report_md,
        "workspace": tmp_root,
        "results_file": results_file,
        "report_path": report_path,
    }


def add_subparser(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "selftest", help="run a miniature matrix entirely locally to prove the harness works"
    )
    p.add_argument("--workspace", help="use this directory instead of a temp dir (kept after the run)")
    p.add_argument("--keep", action="store_true", help="keep generated data/work dirs (results/report always kept)")
    p.set_defaults(func=_cli_run)


def _cli_run(args: argparse.Namespace) -> int:
    base_dir = Path(args.workspace) if args.workspace else None
    keep = args.keep or bool(args.workspace)
    outcome = run_selftest(base_dir=base_dir, keep=keep, progress=print)
    print(f"\nselftest artifacts: {outcome['results_file']}, {outcome['report_path']}")
    return 0
