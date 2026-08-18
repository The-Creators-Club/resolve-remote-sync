"""config.yaml `indexer:` section: the backend-default heuristic (new configs
default `local`; an existing config that already names `anthropic:` keeps
running unchanged), model_tier validation, and env overrides."""
from __future__ import annotations

from pathlib import Path

import pytest

from broll_index.config import ConfigError, load_config


def _write(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "config.yaml"
    p.write_text(
        f'data_root: "{(tmp_path / "data").as_posix()}"\n'
        f'db:\n  mode: sqlite\n  path: "{(tmp_path / "b.db").as_posix()}"\n'
        f"{body}",
        encoding="utf-8",
    )
    return p


def test_new_config_with_no_indexer_or_anthropic_section_defaults_to_local(tmp_path):
    cfg = load_config(_write(tmp_path, "shares:\n  broll:\n    root: /x\n"))
    assert cfg.indexer.backend == "local"
    assert cfg.indexer.model_tier == "good"
    assert cfg.indexer.model_tier_explicit is False


def test_config_naming_anthropic_but_not_backend_keeps_anthropic(tmp_path):
    """Every pre-2026-08-18 config.yaml has an `anthropic:` block and no
    `indexer:` block at all — it must keep behaving exactly as it did."""
    cfg = load_config(_write(tmp_path, "anthropic:\n  max_tokens: 4000\n"))
    assert cfg.indexer.backend == "anthropic"


def test_explicit_backend_wins_over_the_anthropic_heuristic(tmp_path):
    cfg = load_config(_write(
        tmp_path, "anthropic:\n  max_tokens: 4000\nindexer:\n  backend: local\n"))
    assert cfg.indexer.backend == "local"


def test_explicit_backend_anthropic_with_no_anthropic_section_is_honoured(tmp_path):
    cfg = load_config(_write(tmp_path, "indexer:\n  backend: anthropic\n"))
    assert cfg.indexer.backend == "anthropic"


def test_unknown_backend_is_refused(tmp_path):
    with pytest.raises(ValueError, match="indexer.backend"):
        load_config(_write(tmp_path, "indexer:\n  backend: bogus\n"))


def test_model_tier_explicit_flag_set_only_when_the_key_is_present(tmp_path):
    cfg = load_config(_write(tmp_path, "indexer:\n  backend: local\n  model_tier: best\n"))
    assert cfg.indexer.model_tier == "best"
    assert cfg.indexer.model_tier_explicit is True


def test_unknown_model_tier_is_refused(tmp_path):
    with pytest.raises(ValueError, match="indexer.model_tier"):
        load_config(_write(tmp_path, "indexer:\n  model_tier: ultra\n"))


def test_indexer_paths_default_empty_and_read_from_config(tmp_path):
    cfg = load_config(_write(
        tmp_path,
        'indexer:\n  local_cache_dir: "/cache"\n  llama_server_path: "/bin/llama-server"\n'
        '  dashboard_url: "https://dash.example.ts.net"\n  frames_per_call: 6\n  gpu_layers: 20\n'
        "  merge_similar_segments: false\n",
    ))
    assert cfg.indexer.local_cache_dir == "/cache"
    assert cfg.indexer.llama_server_path == "/bin/llama-server"
    assert cfg.indexer.dashboard_url == "https://dash.example.ts.net"
    assert cfg.indexer.frames_per_call == 6
    assert cfg.indexer.gpu_layers == 20
    assert cfg.indexer.merge_similar_segments is False


def test_env_overrides_win_over_config_yaml(tmp_path, monkeypatch):
    monkeypatch.setenv("BROLL_LOCAL_CACHE_DIR", "/env-cache")
    monkeypatch.setenv("BROLL_LLAMA_SERVER_PATH", "/env-bin/llama-server")
    monkeypatch.setenv("BROLL_DASHBOARD_URL", "https://env.example.ts.net")
    cfg = load_config(_write(
        tmp_path,
        'indexer:\n  local_cache_dir: "/cache"\n  llama_server_path: "/bin/llama-server"\n'
        '  dashboard_url: "https://dash.example.ts.net"\n',
    ))
    assert cfg.indexer.local_cache_dir == "/env-cache"
    assert cfg.indexer.llama_server_path == "/env-bin/llama-server"
    assert cfg.indexer.dashboard_url == "https://env.example.ts.net"


def test_default_indexer_config_merge_similar_segments_is_true(tmp_path):
    cfg = load_config(_write(tmp_path, ""))
    assert cfg.indexer.merge_similar_segments is True
    assert cfg.indexer.frames_per_call == 9
    assert cfg.indexer.gpu_layers == 99
