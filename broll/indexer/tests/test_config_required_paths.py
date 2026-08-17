"""Required-not-defaulted paths, and the whisper environment being in the repo.

2026-08-17, COMMERCIAL_READINESS.md item 14. `data_root`, `db.path` and the
faster-whisper environment used to default to one workstation's directories, so
a fresh install either wrote somewhere surprising or skipped a stage in silence.
Every one is now required and every refusal names the key AND the environment
variable that would supply it -- the container mounts config.yaml read-only, so
"edit the file" is not always an available instruction.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from broll_index import transcribe
from broll_index.config import ConfigError, WhisperConfig, load_config


def _write(tmp_path: Path, **overrides) -> Path:
    cfg = {
        "shares": {"broll": {"root": str(tmp_path / "broll_root")}},
        "data_root": str(tmp_path / "data"),
        "db": {"mode": "sqlite", "path": str(tmp_path / "broll.db")},
    }
    cfg.update(overrides)
    for key in [k for k, v in cfg.items() if v is None]:
        del cfg[key]
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return path


# ---------------------------------------------------------------- data_root

def test_a_missing_data_root_names_the_key_and_the_env_var(tmp_path, monkeypatch):
    monkeypatch.delenv("BROLL_DATA_ROOT", raising=False)
    with pytest.raises(ConfigError) as exc:
        load_config(_write(tmp_path, data_root=None))
    assert "data_root" in str(exc.value)
    assert "BROLL_DATA_ROOT" in str(exc.value)


def test_the_env_var_supplies_data_root_for_a_read_only_config(tmp_path, monkeypatch):
    monkeypatch.setenv("BROLL_DATA_ROOT", str(tmp_path / "from-env"))
    cfg = load_config(_write(tmp_path, data_root=None))
    assert cfg.data_root == tmp_path / "from-env"


def test_the_env_var_wins_over_the_file(tmp_path, monkeypatch):
    """The image sets it; the config it mounts belongs to the operator."""
    monkeypatch.setenv("BROLL_DATA_ROOT", str(tmp_path / "from-env"))
    cfg = load_config(_write(tmp_path))
    assert cfg.data_root == tmp_path / "from-env"


# ------------------------------------------------------------------ db.path

def test_sqlite_mode_without_a_path_is_refused(tmp_path, monkeypatch):
    monkeypatch.delenv("BROLL_DB_PATH", raising=False)
    with pytest.raises(ConfigError) as exc:
        load_config(_write(tmp_path, db={"mode": "sqlite"}))
    assert "db.path" in str(exc.value)
    assert "BROLL_DB_PATH" in str(exc.value)


def test_api_mode_without_a_url_is_refused(tmp_path, monkeypatch):
    monkeypatch.delenv("BROLL_DB_URL", raising=False)
    with pytest.raises(ConfigError) as exc:
        load_config(_write(tmp_path, db={"mode": "api"}))
    assert "db.url" in str(exc.value)


def test_api_mode_needs_no_sqlite_path(tmp_path, monkeypatch):
    monkeypatch.delenv("BROLL_DB_PATH", raising=False)
    cfg = load_config(_write(tmp_path, db={"mode": "api", "url": "http://x/api"}))
    assert cfg.db.path is None


def test_the_ingest_token_can_come_from_the_environment(tmp_path, monkeypatch):
    """A token in config.yaml is a secret in a file that gets pasted into
    support threads -- the same reasoning as anthropic.api_key_env."""
    monkeypatch.setenv("BROLL_DB_TOKEN", "from-env")
    cfg = load_config(_write(tmp_path, db={"mode": "api", "url": "http://x/api",
                                           "token": "in-the-file"}))
    assert cfg.db.token == "from-env"


# ------------------------------------------------------------------- whisper

def test_no_personal_path_is_left_in_the_whisper_defaults():
    """The literal thing item 14 asked for: nothing that only one machine has."""
    d = WhisperConfig()
    assert d.python == "" and d.script == "" and d.model_dir == ""


def test_an_unconfigured_whisper_refuses_by_name(tmp_path):
    cfg = load_config(_write(tmp_path))
    with pytest.raises(ConfigError) as exc:
        cfg.require_whisper()
    assert "whisper.python" in str(exc.value)
    assert "CCSYNC_WHISPER_PYTHON" in str(exc.value)
    assert "make_whisper_env" in str(exc.value)


def test_a_configured_whisper_that_is_not_on_disk_says_which_half(tmp_path):
    real = tmp_path / "python.exe"
    real.write_bytes(b"")
    cfg = load_config(_write(tmp_path, whisper={
        "python": str(real), "script": str(tmp_path / "gone.py")}))
    with pytest.raises(ConfigError, match="whisper.script"):
        cfg.require_whisper()


def test_require_whisper_returns_both_paths_when_they_exist(tmp_path):
    py, script = tmp_path / "python.exe", tmp_path / "whisper_transcribe.py"
    py.write_bytes(b"")
    script.write_bytes(b"")
    cfg = load_config(_write(tmp_path, whisper={"python": str(py),
                                                "script": str(script)}))
    assert cfg.require_whisper() == (py, script)


def test_the_environment_supplies_the_whisper_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("CCSYNC_WHISPER_PYTHON", "/opt/whisper-env/bin/python")
    monkeypatch.setenv("CCSYNC_WHISPER_SCRIPT", "/opt/indexer/tools/whisper_transcribe.py")
    monkeypatch.setenv("CCSYNC_WHISPER_MODEL_DIR", "/models")
    cfg = load_config(_write(tmp_path))
    assert cfg.whisper.python == "/opt/whisper-env/bin/python"
    assert cfg.whisper.script == "/opt/indexer/tools/whisper_transcribe.py"
    assert cfg.whisper.model_dir == "/models"


def test_the_repo_ships_the_helper_the_config_example_points_at():
    """`whisper.script` names a file in this repo now, not one outside it."""
    indexer = Path(__file__).resolve().parents[1]
    assert (indexer / "tools" / "whisper_transcribe.py").is_file()
    assert (indexer / "tools" / "make_whisper_env.ps1").is_file()
    assert (indexer / "tools" / "make_whisper_env.sh").is_file()


# -------------------------------------------------------------- model caches

def test_the_model_cache_reaches_the_whisper_child_process():
    """Passed through the ENVIRONMENT, not argv: the helper on the other end
    may be an operator's own script that never learned a --model-dir flag."""
    env = transcribe.whisper_child_env("/models")
    assert env["HF_HOME"] == "/models"
    assert env["HUGGINGFACE_HUB_CACHE"].replace("\\", "/") == "/models/hub"


def test_no_model_cache_means_inherit_this_process_environment():
    assert transcribe.whisper_child_env("") is None


def test_transcribe_file_keeps_the_six_positional_runner_contract(tmp_path):
    """A runner written before model_dir existed must still be callable."""
    seen = {}

    def runner(src, out_dir, python_exe, script, model, language):
        seen.update(model=model, language=language)
        srt = tmp_path / "x.srt"
        srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n", encoding="utf-8")
        return srt

    cues = transcribe.transcribe_file(tmp_path / "clip.mov", tmp_path, "py", "s",
                                      model="m", language="zh", runner=runner)
    assert [c.text for c in cues] == ["hi"]
    assert seen == {"model": "m", "language": "zh"}


def test_model_dir_is_forwarded_only_when_it_is_set(tmp_path):
    seen = {}

    def runner(src, out_dir, python_exe, script, model, language, model_dir=""):
        seen["model_dir"] = model_dir
        srt = tmp_path / "y.srt"
        srt.write_text("", encoding="utf-8")
        return srt

    transcribe.transcribe_file(tmp_path / "clip.mov", tmp_path, "py", "s",
                               runner=runner, model_dir="/models")
    assert seen["model_dir"] == "/models"


def test_the_transcribe_subcommand_refuses_rather_than_reporting_zero(tmp_path,
                                                                     capsys,
                                                                     monkeypatch):
    """Inside a `run` the stage skips; asked for by name it must refuse.

    "transcribe: processed 12 video(s)" with no whisper anywhere is the failure
    this closes -- it reads as success and produced nothing.
    """
    from broll_index.cli import main

    monkeypatch.delenv("CCSYNC_WHISPER_PYTHON", raising=False)
    monkeypatch.delenv("CCSYNC_WHISPER_SCRIPT", raising=False)
    config_path = _write(tmp_path)
    (tmp_path / "broll_root").mkdir(parents=True)

    assert main(["--config", str(config_path), "transcribe"]) == 2
    assert "CCSYNC_WHISPER_PYTHON" in capsys.readouterr().err


def test_the_embedding_cache_dir_is_configurable(tmp_path, monkeypatch):
    monkeypatch.setenv("BROLL_MODEL_CACHE", str(tmp_path / "fastembed"))
    cfg = load_config(_write(tmp_path))
    assert cfg.embedding.cache_dir == str(tmp_path / "fastembed")
