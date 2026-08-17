"""How the ingest route finds ffmpeg/ffprobe -- and what it no longer assumes.

2026-08-17, COMMERCIAL_READINESS.md item 10: `_tool()`'s last resort used to be
a literal `C:\\Users\\<operator>\\tools\\ffmpeg\\bin`, i.e. one person's home
directory compiled into shipped source. On every other host it resolved to
nothing, so the only thing it ever did was leak a name. The fallback is now
opt-in via MUSIC_FFMPEG_DIR and the search order is env -> PATH -> that.

These tests never invoke ffmpeg; they pin the resolution order and the absence
of the personal path.
"""
import ast
from pathlib import Path

import pytest

from musicweb import routes_ingest


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in ('FFMPEG', 'FFPROBE', 'MUSIC_FFMPEG_DIR'):
        monkeypatch.delenv(var, raising=False)


def test_no_hardcoded_operator_path_remains():
    """The whole point of the change: no home directory in an executable literal.

    Parsed rather than grepped, so the comment that explains *why* the path went
    away is allowed to name its shape while the code may not contain it.
    """
    src = Path(routes_ingest.__file__).read_text(encoding='utf-8')
    literals = [n.value for n in ast.walk(ast.parse(src))
                if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    assert not [s for s in literals if 'C:\\Users\\' in s]


def test_unset_and_not_on_path_resolves_to_nothing(monkeypatch):
    """Nothing is silently assumed -- _require_ffmpeg turns this into a 503."""
    monkeypatch.setattr(routes_ingest.shutil, 'which', lambda name: None)
    assert routes_ingest._tool('ffmpeg') is None
    assert routes_ingest._fallback_bin() is None


def test_path_is_preferred_over_the_fallback_dir(monkeypatch, tmp_path):
    """The container case: ffmpeg is a distro package, MUSIC_FFMPEG_DIR is unset
    and must never be needed there."""
    monkeypatch.setattr(routes_ingest.shutil, 'which', lambda name: '/usr/bin/' + name)
    monkeypatch.setenv('MUSIC_FFMPEG_DIR', str(tmp_path))
    assert routes_ingest._tool('ffmpeg') == '/usr/bin/ffmpeg'


def test_explicit_env_var_beats_path(monkeypatch):
    monkeypatch.setattr(routes_ingest.shutil, 'which', lambda name: '/usr/bin/' + name)
    monkeypatch.setenv('FFPROBE', '/opt/custom/ffprobe')
    assert routes_ingest._tool('ffprobe') == '/opt/custom/ffprobe'


def test_fallback_dir_is_used_only_when_it_really_holds_the_tool(monkeypatch, tmp_path):
    monkeypatch.setattr(routes_ingest.shutil, 'which', lambda name: None)
    monkeypatch.setenv('MUSIC_FFMPEG_DIR', str(tmp_path))
    assert routes_ingest._tool('ffmpeg') is None

    (tmp_path / 'ffmpeg.exe').write_bytes(b'')
    assert routes_ingest._tool('ffmpeg') == str(tmp_path / 'ffmpeg.exe')


def test_the_503_names_every_override_an_operator_could_set(monkeypatch):
    monkeypatch.setattr(routes_ingest.shutil, 'which', lambda name: None)
    with pytest.raises(Exception) as exc:
        routes_ingest._require_ffmpeg()
    detail = getattr(exc.value, 'detail', str(exc.value))
    assert 'MUSIC_FFMPEG_DIR' in detail
