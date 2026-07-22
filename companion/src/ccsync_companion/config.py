"""Companion config file handling.

Config lives at ~/.ccsync/config.toml (TOML, read with stdlib tomllib — see
SPEC.md's Companion App section). tomllib is read-only, so on first run we
write out DEFAULT_TOML_TEXT verbatim (a hand-maintained, commented template)
rather than round-tripping through a serializer. After that, users edit the
file directly; load_config() only ever reads.

DEFAULTS below is the single source of truth for keys + fallback values —
DEFAULT_TOML_TEXT should be kept in sync with it (see test_config.py, which
asserts the two agree on keys).
"""

from __future__ import annotations

import sys

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - project targets 3.12
    import tomli as tomllib  # type: ignore[no-redef]

from pathlib import Path
from typing import Any

VERSION = "0.1.0"

CONFIG_DIR = Path.home() / ".ccsync"
CONFIG_PATH = CONFIG_DIR / "config.toml"

# Keys marked "addition" in the docstring/README are small, clearly-scoped
# extensions beyond SPEC.md's literal config list — see README.md's "SPEC
# deviations" section for the why on each.
DEFAULTS: dict[str, Any] = {
    "editor_name": "",
    "local_root": "",
    "canonical_prefix": "P:\\",
    "remote": "nas",
    "remote_root": "",
    "projects": [],
    # The project new editor media gets filed into (popup destinations are
    # prefixed with this) — rel path under local_root, e.g. "Projects/2025/FF4/Nuclear".
    "active_project": "",
    "poll_interval": 3,
    # SPEC.md lists a single `scan_interval` but gives Lane A and Lane B
    # different defaults (300s / 120s) — split into two keys (addition).
    "scan_interval_up": 300,
    "scan_interval_down": 120,
    # Debounce window for the Lane A watchdog file events (addition; SPEC.md
    # says "10s debounce" for lane A but doesn't name a config key for it).
    "watch_debounce_seconds": 10,
    "transfers": 4,
    "syncthing_url": "http://127.0.0.1:8384",
    "syncthing_api_key": "",
    # Expected Syncthing folder ID per entry in `projects` (addition; needed
    # to fulfil "verify the expected folder ID ... is configured + shared").
    # Leave empty to skip the folder-id check for a project.
    "syncthing_folder_ids": [],
    "rclone_path": "rclone",
    "log_path": "~/.ccsync/companion.log",
    "log_level": "INFO",
}

DEFAULT_TOML_TEXT = """\
# ccsync-companion config
# See companion/README.md for the full reference. Restart the companion
# after editing this file.

# Your name/handle — used to build the "B-roll/Editor Added/<editor_name>"
# destination suggested by the popup fixer.
editor_name = ""

# Absolute path to this machine's local copy of the project tree, e.g.
# "C:\\\\Creators_Club" (Windows) or "/Users/you/Creators_Club" (macOS).
local_root = ""

# The canonical shared-drive prefix used in Resolve's stored clip paths
# (Windows: the "P:" virtual drive letter from SPEC.md's Path canon). Used
# to detect BAD_PREFIX (mapping-health) situations.
canonical_prefix = "P:\\\\"

# Name of a pre-configured rclone remote (via `rclone config`) pointing at
# the NAS, e.g. an SFTP remote. ccsync-companion does not configure rclone
# remotes for you.
remote = "nas"

# Root path on the remote under which project trees live, e.g.
# "Creators_Club".
remote_root = ""

# Project relative paths to sync, e.g. ["Projects/2025/FF4/Nuclear"].
projects = []
active_project = ""

# Resolve timeline poll interval, in seconds.
poll_interval = 3

# Lane A (video originals, up) periodic full-pass interval, in seconds.
scan_interval_up = 300

# Lane B (proxies, down) periodic full-pass interval, in seconds.
scan_interval_down = 120

# Lane A watchdog file-stability debounce, in seconds.
watch_debounce_seconds = 10

# rclone --transfers (parallel stream count).
transfers = 4

# Local Syncthing REST API base URL and API key. Leave syncthing_api_key
# empty to read it from Syncthing's own config.xml (standard per-OS path).
syncthing_url = "http://127.0.0.1:8384"
syncthing_api_key = ""

# Expected Syncthing folder ID per project (same order/length as `projects`
# above). Leave as [] to skip the folder-id verification.
syncthing_folder_ids = []

# Path to the rclone binary. Defaults to "rclone" (must be on PATH).
rclone_path = "rclone"

# Log file (rotating) — console logging is always on in addition to this.
log_path = "~/.ccsync/companion.log"
log_level = "INFO"
"""


def ensure_config_exists(path: Path = CONFIG_PATH) -> None:
    """Write DEFAULT_TOML_TEXT to `path` if it doesn't exist yet."""
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(DEFAULT_TOML_TEXT, encoding="utf-8")


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    """Load config, creating it with defaults on first run.

    Malformed TOML falls back to defaults rather than crashing the app —
    matches the never-raise ethos used throughout this package.
    """
    ensure_config_exists(path)
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except (tomllib.TOMLDecodeError, OSError):
        data = {}

    merged = dict(DEFAULTS)
    if isinstance(data, dict):
        merged.update(data)

    # Defensive type coercion for list fields — a hand-edited TOML file can
    # easily get these wrong (e.g. a bare string instead of a one-item list).
    if not isinstance(merged.get("projects"), list):
        merged["projects"] = []
    if not isinstance(merged.get("syncthing_folder_ids"), list):
        merged["syncthing_folder_ids"] = []

    return merged


def resolved_log_path(cfg: dict[str, Any]) -> Path:
    return Path(cfg.get("log_path", DEFAULTS["log_path"])).expanduser()


def resolved_local_root(cfg: dict[str, Any]) -> Path:
    return Path(cfg.get("local_root", "")).expanduser()
