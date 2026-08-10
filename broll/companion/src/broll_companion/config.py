"""Companion config file handling.

Config lives at ~/.broll-companion.json, per SPEC.md:
    {"server_url": "...", "mounts": {"broll": "B:/"}}

JSON can't hold comments, so on first run we also drop a plain-text README
snippet alongside it explaining the fields (see README_SNIPPET below).
"""

from __future__ import annotations

import json
from pathlib import Path

VERSION = "0.1.0"

CONFIG_PATH = Path.home() / ".broll-companion.json"
README_SNIPPET_PATH = Path.home() / ".broll-companion.README.txt"

DEFAULT_CONFIG: dict = {
    "server_url": "http://127.0.0.1:8000",
    "mounts": {},
}

README_SNIPPET = """BRoll Companion config — {config_path}

This file has no comments (it's plain JSON), so here's what each field means:

  server_url
      Base URL of the broll-platform web app. Not required for /insert to
      work, but the companion may use it in future for auth/version checks.

  mounts
      Maps each "share" slug used in the web UI to where that share is
      mounted on THIS machine, e.g.:
          {{"broll": "B:/"}}                (Windows, mapped drive)
          {{"broll": "/Volumes/broll"}}      (macOS)
      Add one entry per share you use. Ask whoever runs the indexer for the
      share names if you're not sure.

      On macOS, if a share has no entry here, the companion will also try
      /Volumes/<share>, /Volumes/<share>-1, /Volumes/<share>-2 automatically
      (handles Finder's "already mounted, try again" renaming) — so mounts is
      optional there, but explicit entries are always used first.

After editing this file, restart BRoll Companion for changes to take effect.
"""


def ensure_config_exists(
    path: Path = CONFIG_PATH, readme_path: Path = README_SNIPPET_PATH
) -> None:
    """Create the config file (and its README snippet) with defaults if missing."""
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(DEFAULT_CONFIG, indent=2) + "\n", encoding="utf-8")
    if not readme_path.exists():
        readme_path.parent.mkdir(parents=True, exist_ok=True)
        readme_path.write_text(
            README_SNIPPET.format(config_path=str(path)), encoding="utf-8"
        )


def load_config(path: Path = CONFIG_PATH) -> dict:
    """Load the config, creating it with defaults on first run.

    Malformed JSON falls back to defaults rather than crashing the server.
    """
    ensure_config_exists(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        data = {}

    merged = dict(DEFAULT_CONFIG)
    if isinstance(data, dict):
        merged.update(data)
    if not isinstance(merged.get("mounts"), dict):
        merged["mounts"] = {}
    return merged


def save_config(cfg: dict, path: Path = CONFIG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
