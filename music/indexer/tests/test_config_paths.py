"""The indexer's required paths: what it refuses to guess, and what it names.

Deliberately torch-free so it runs on the system interpreter (the CLAP half
needs a GPU rig and is not a unit-testable surface). `music_index.config` is
the whole module under test: importing it puts ../web on sys.path but pulls in
nothing heavier than `musicweb.config`.

    cd music/indexer && python -m pytest tests -q
"""
import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from music_index import config                                    # noqa: E402


def _reloaded(monkeypatch, **env):
    """music_index.config re-imported under `env`. Paths are bound at import."""
    for key, value in env.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)
    import musicweb.config
    importlib.reload(musicweb.config)
    return importlib.reload(config)


@pytest.fixture(autouse=True)
def _restore_module_state(monkeypatch):
    """Put the real modules back: reload() mutates the ones everything shares."""
    yield
    import musicweb.config
    importlib.reload(musicweb.config)
    importlib.reload(config)


# ------------------------------------------------------------------ db path

def test_an_unnamed_index_is_refused_by_name(monkeypatch):
    """Guessing is how a drain reports "nothing to analyse" about the wrong
    database (MUSIC-3; COMMERCIAL_READINESS.md item 14, 2026-08-17)."""
    monkeypatch.delenv('MUSIC_DB_PATH', raising=False)
    monkeypatch.delenv('MUSIC_DATA_ROOT', raising=False)
    with pytest.raises(config.DbPathNotConfigured) as exc:
        config.require_db_path()
    assert 'MUSIC_DB_PATH' in str(exc.value)
    assert '--db' in str(exc.value)


def test_an_explicit_path_wins_over_everything(monkeypatch, tmp_path):
    monkeypatch.setenv('MUSIC_DB_PATH', str(tmp_path / 'env.db'))
    assert config.require_db_path(str(tmp_path / 'pulled.db')) == tmp_path / 'pulled.db'


def test_music_db_path_names_the_file_directly(monkeypatch, tmp_path):
    """The case a data root cannot express: a drain against a pulled-down copy
    whose proxies and staging still belong under the local data root."""
    cfg = _reloaded(monkeypatch, MUSIC_DB_PATH=str(tmp_path / 'nas' / 'music.db'),
                    MUSIC_DATA_ROOT=str(tmp_path / 'local'))
    assert cfg.require_db_path() == tmp_path / 'nas' / 'music.db'
    assert cfg.DATA_ROOT == tmp_path / 'local'


def test_a_data_root_alone_is_enough(monkeypatch, tmp_path):
    cfg = _reloaded(monkeypatch, MUSIC_DATA_ROOT=str(tmp_path), MUSIC_DB_PATH=None)
    assert cfg.require_db_path() == tmp_path / 'music.db'


# ------------------------------------------------------------------- ffmpeg

def test_the_fallback_is_the_bare_name_not_somebody_s_home_directory(monkeypatch):
    """The whole point of item 14's grep. The default must be resolvable
    everywhere or nowhere -- never a path only one machine has, which is what
    made a customer rig fail with a WinError 2 naming a stranger's directory.

    `which` is stubbed because a rig that HAS ffmpeg on PATH would otherwise be
    asserting about its own PATH rather than about this module.
    """
    monkeypatch.delenv('FFMPEG', raising=False)
    monkeypatch.delenv('FFPROBE', raising=False)
    monkeypatch.setattr(config.shutil, 'which', lambda _name: None)
    assert config._tool('ffmpeg') == 'ffmpeg'
    assert config._tool('ffprobe') == 'ffprobe'


def test_missing_tools_are_refused_before_a_run_decodes_anything(monkeypatch):
    monkeypatch.setattr(config.shutil, 'which', lambda _name: None)
    monkeypatch.delenv('FFMPEG', raising=False)
    monkeypatch.delenv('FFPROBE', raising=False)
    monkeypatch.setattr(config, 'FFMPEG', 'ffmpeg')
    monkeypatch.setattr(config, 'FFPROBE', 'ffprobe')
    with pytest.raises(config.FfmpegNotConfigured) as exc:
        config.require_tools()
    assert 'FFMPEG' in str(exc.value)


def test_an_env_override_is_taken_verbatim(monkeypatch, tmp_path):
    fake = tmp_path / 'ffmpeg.exe'
    fake.write_bytes(b'')
    cfg = _reloaded(monkeypatch, FFMPEG=str(fake), FFPROBE=str(fake))
    assert cfg.FFMPEG == str(fake)
    cfg.require_tools()


# ------------------------------------------------------------- model cache

def test_the_model_cache_is_exported_for_transformers(monkeypatch, tmp_path):
    """CLAP is loaded from three modules here, so the cache has to be process
    state rather than an argument threaded through each of them."""
    cfg = _reloaded(monkeypatch, MUSIC_MODEL_CACHE=str(tmp_path / 'models'),
                    HF_HOME=None)
    assert cfg.MODEL_CACHE == str(tmp_path / 'models')
    import os
    assert os.environ['HF_HOME'] == str(tmp_path / 'models')


def test_no_model_cache_leaves_the_environment_alone(monkeypatch):
    cfg = _reloaded(monkeypatch, MUSIC_MODEL_CACHE=None, HF_HOME=None)
    assert cfg.MODEL_CACHE == ''
    import os
    assert 'HF_HOME' not in os.environ
