"""bench.toml loader.

Python 3.12 ships tomllib in the stdlib (read-only), so no third-party TOML
dependency is needed. Relative paths inside the config (dataset dirs, work
dir, results file, key_file, etc. that look like plain relative paths) are
resolved relative to the directory containing bench.toml, so the config can
be run from anywhere.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

DEFAULTS: dict[str, Any] = {
    "general": {
        "results_file": "results/results.jsonl",
        "repeats": 2,
        "keep_remote_data": False,
        "verify": True,
        "work_dir": "work",
    },
    "datasets": {},
    "lanes": {},
    "engines": {"include": ["rclone_sftp", "rclone_smb", "robocopy_smb", "syncthing", "iperf3"]},
    "endpoints": {},
    "params": {},
    "tailscale": {},
}


def _merge_defaults(cfg: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for section, default_value in DEFAULTS.items():
        provided = cfg.get(section, {})
        if isinstance(default_value, dict):
            merged_section = dict(default_value)
            merged_section.update(provided)
            merged[section] = merged_section
        else:
            merged[section] = provided if provided else default_value
    # carry over any sections not in DEFAULTS (forward-compat)
    for key, value in cfg.items():
        if key not in merged:
            merged[key] = value
    return merged


def _resolve_path(base_dir: Path, value: str) -> str:
    p = Path(value)
    if p.is_absolute():
        return str(p)
    return str((base_dir / p).resolve())


def load_config(config_path: Path) -> dict[str, Any]:
    config_path = Path(config_path)
    with open(config_path, "rb") as f:
        raw = tomllib.load(f)
    cfg = _merge_defaults(raw)

    base_dir = config_path.resolve().parent
    cfg["general"]["results_file"] = _resolve_path(base_dir, cfg["general"]["results_file"])
    cfg["general"]["work_dir"] = _resolve_path(base_dir, cfg["general"]["work_dir"])

    for name, path in list(cfg.get("datasets", {}).items()):
        if isinstance(path, str):
            cfg["datasets"][name] = _resolve_path(base_dir, path)

    return cfg


def dataset_dir_for(cfg: dict[str, Any], dataset_key: str) -> Path:
    try:
        return Path(cfg["datasets"][dataset_key])
    except KeyError as exc:
        raise KeyError(
            f"lane references dataset {dataset_key!r} but it is not defined in [datasets]"
        ) from exc
