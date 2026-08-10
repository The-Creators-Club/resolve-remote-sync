"""Config file creation/loading — not explicitly requested by name but load-
bearing for /status's `mounts` and the first-run experience described in
SPEC.md and the task brief (defaults + README snippet on first run)."""

from __future__ import annotations

import json

from broll_companion import config as config_mod


def test_first_run_creates_config_with_defaults(tmp_path):
    cfg_path = tmp_path / ".broll-companion.json"
    readme_path = tmp_path / ".broll-companion.README.txt"
    assert not cfg_path.exists()

    loaded = config_mod.load_config(path=cfg_path)

    assert cfg_path.exists()
    assert loaded["mounts"] == {}
    assert "server_url" in loaded


def test_first_run_creates_readme_snippet_alongside(tmp_path):
    cfg_path = tmp_path / ".broll-companion.json"
    readme_path = tmp_path / ".broll-companion.README.txt"

    config_mod.ensure_config_exists(path=cfg_path, readme_path=readme_path)

    assert readme_path.exists()
    text = readme_path.read_text(encoding="utf-8")
    assert "mounts" in text
    assert str(cfg_path) in text


def test_existing_config_is_not_overwritten(tmp_path):
    cfg_path = tmp_path / ".broll-companion.json"
    readme_path = tmp_path / ".broll-companion.README.txt"
    custom = {"server_url": "http://example.com", "mounts": {"broll": "B:/"}}
    cfg_path.write_text(json.dumps(custom), encoding="utf-8")

    loaded = config_mod.load_config(path=cfg_path)

    assert loaded["mounts"] == {"broll": "B:/"}
    assert loaded["server_url"] == "http://example.com"


def test_malformed_config_falls_back_to_defaults_without_crashing(tmp_path):
    cfg_path = tmp_path / ".broll-companion.json"
    cfg_path.write_text("{not valid json", encoding="utf-8")

    loaded = config_mod.load_config(path=cfg_path)

    assert loaded["mounts"] == {}
    assert loaded["server_url"] == config_mod.DEFAULT_CONFIG["server_url"]
