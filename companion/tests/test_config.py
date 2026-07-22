"""Config file tests: first-run creation, TOML parsing, malformed fallback,
and DEFAULTS/DEFAULT_TOML_TEXT key parity."""

from __future__ import annotations

import re

from ccsync_companion import config as config_mod


def test_ensure_config_exists_writes_default_toml(tmp_path):
    path = tmp_path / "config.toml"
    assert not path.exists()
    config_mod.ensure_config_exists(path)
    assert path.exists()
    assert path.read_text(encoding="utf-8") == config_mod.DEFAULT_TOML_TEXT


def test_ensure_config_exists_does_not_overwrite(tmp_path):
    path = tmp_path / "config.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('editor_name = "custom"\n', encoding="utf-8")
    config_mod.ensure_config_exists(path)
    assert path.read_text(encoding="utf-8") == 'editor_name = "custom"\n'


def test_load_config_creates_defaults_on_first_run(tmp_path):
    path = tmp_path / "sub" / "config.toml"
    cfg = config_mod.load_config(path)
    assert path.exists()
    for key, value in config_mod.DEFAULTS.items():
        assert cfg[key] == value


def test_load_config_merges_user_overrides(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        'editor_name = "alex"\n'
        'local_root = "C:\\\\Creators_Club"\n'
        "poll_interval = 5\n",
        encoding="utf-8",
    )
    cfg = config_mod.load_config(path)
    assert cfg["editor_name"] == "alex"
    assert cfg["local_root"] == "C:\\Creators_Club"
    assert cfg["poll_interval"] == 5
    # Untouched keys still fall back to DEFAULTS.
    assert cfg["remote"] == config_mod.DEFAULTS["remote"]


def test_load_config_malformed_toml_falls_back_to_defaults(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("this is not valid TOML [[[", encoding="utf-8")
    cfg = config_mod.load_config(path)
    assert cfg == config_mod.DEFAULTS


def test_load_config_coerces_bad_list_fields(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('projects = "not-a-list"\n', encoding="utf-8")
    cfg = config_mod.load_config(path)
    assert cfg["projects"] == []


def test_resolved_log_path_expands_user(monkeypatch, tmp_path):
    cfg = {"log_path": "~/.ccsync/companion.log"}
    result = config_mod.resolved_log_path(cfg)
    assert not str(result).startswith("~")


def test_resolved_local_root(tmp_path):
    cfg = {"local_root": str(tmp_path)}
    assert config_mod.resolved_local_root(cfg) == tmp_path


def test_default_toml_text_documents_every_default_key():
    # Every key in DEFAULTS should appear as a `key =` assignment somewhere
    # in DEFAULT_TOML_TEXT, so the shipped template never drifts from the
    # code's actual fallback values.
    for key in config_mod.DEFAULTS:
        pattern = rf"^{re.escape(key)} = "
        assert re.search(pattern, config_mod.DEFAULT_TOML_TEXT, re.MULTILINE), (
            f"DEFAULT_TOML_TEXT is missing an assignment for '{key}'"
        )


def test_config_example_toml_matches_default_keys():
    # config.example.toml (shipped alongside pyproject.toml) should also
    # document every key — catches the file drifting from config.py.
    example_path = config_mod.CONFIG_DIR.parent  # not used; see below
    from pathlib import Path

    companion_root = Path(__file__).resolve().parent.parent
    example_text = (companion_root / "config.example.toml").read_text(encoding="utf-8")
    for key in config_mod.DEFAULTS:
        pattern = rf"^{re.escape(key)} = "
        assert re.search(pattern, example_text, re.MULTILINE), (
            f"config.example.toml is missing an assignment for '{key}'"
        )
