"""(share, rel_path) -> a real path, and everything it must refuse.

The database never stores absolute paths: every track is a logical share name
plus a forward-slash relative path, translated at the edge. rel_path therefore
arrives from a row someone else wrote (the indexer, or an upload), so the
resolver is the only thing between a bad row and a file served from outside the
library. The validation mirrors ccsync_companion/broll_server.py's
_split_components/_validate_components on purpose; these tests are the music
half of that guard.
"""
import pytest

from musicweb import config


@pytest.fixture()
def share(tmp_path, monkeypatch):
    """A throwaway share root, so a passing join is checked against a real dir."""
    root = tmp_path / 'library'
    (root / 'sub dir').mkdir(parents=True)
    monkeypatch.setitem(config.SHARE_ROOTS, config.SHARE, root)
    return root


# ------------------------------------------------------------ what resolves
def test_a_normal_rel_path_resolves_under_the_share_root(share):
    got = config.resolve_path('music', 'ES_Tense Pulse.wav')
    assert got == share / 'ES_Tense Pulse.wav'


def test_nested_forward_slash_path(share):
    got = config.resolve_path('music', 'sub dir/Winter Rain.flac')
    assert got == share / 'sub dir' / 'Winter Rain.flac'
    assert got.parent == share / 'sub dir'


def test_backslashes_are_tolerated_as_separators(share):
    """rel_path is documented forward-slash, but a caller that used native
    separators must not silently produce a one-component filename."""
    assert (config.resolve_path('music', r'sub dir\Winter Rain.flac')
            == share / 'sub dir' / 'Winter Rain.flac')


def test_redundant_dot_components_are_dropped(share):
    assert config.resolve_path('music', './a/./b.wav') == share / 'a' / 'b.wav'


def test_resolve_path_does_not_require_the_file_to_exist(share):
    """The routes' own 404 reports a missing file; the resolver is not a probe."""
    assert not config.resolve_path('music', 'not-here.wav').exists()


# ------------------------------------------------------------ what it refuses
@pytest.mark.parametrize('rel', [
    '../secrets.wav',
    'a/../../secrets.wav',
    '..',
    r'..\secrets.wav',
    'sub dir/../../../../Windows/System32/config/SAM',
])
def test_traversal_is_rejected(share, rel):
    with pytest.raises(config.PathTraversalError):
        config.resolve_path('music', rel)


@pytest.mark.parametrize('rel', [
    '/etc/passwd',
    '/Assets/Music/x.wav',
    '//nas/share/x.wav',
    r'\\FILESERVER-1\web\x.wav',
])
def test_absolute_paths_are_rejected(share, rel):
    with pytest.raises(config.PathTraversalError):
        config.resolve_path('music', rel)


@pytest.mark.parametrize('rel', [
    r'C:\Windows\System32\config\SAM',
    'C:/Windows/System32/config/SAM',
    'C:x.wav',
    r'W:\Creators_Club\Assets\Music\x.wav',
])
def test_drive_letters_are_rejected(share, rel):
    with pytest.raises(config.PathTraversalError):
        config.resolve_path('music', rel)


def test_a_drive_letter_smuggled_in_as_a_segment_is_rejected(share):
    """Path.joinpath re-anchors on a drive component, so 'a/C:/x' would escape."""
    with pytest.raises(config.PathTraversalError):
        config.resolve_path('music', 'a/C:/x.wav')


@pytest.mark.parametrize('rel', ['', '   ', '/', './', None])
def test_empty_rel_path_is_rejected(share, rel):
    with pytest.raises(config.PathTraversalError):
        config.resolve_path('music', rel)


def test_an_unknown_share_raises_rather_than_falling_back(share):
    """Silently defaulting to the music root would serve the wrong tree."""
    with pytest.raises(config.UnknownShareError):
        config.resolve_path('broll', 'x.wav')


# ------------------------------------------------------------ the root mapping
def test_safe_join_takes_an_explicit_root(tmp_path):
    """index_music.py --root is a CLI argument, not a share."""
    assert config.safe_join(tmp_path, 'a/b.wav') == tmp_path / 'a' / 'b.wav'
    with pytest.raises(config.PathTraversalError):
        config.safe_join(tmp_path, '../b.wav')


def test_share_root_is_the_configured_root(share):
    assert config.share_root() == share
    assert config.share_root('music') == share


def test_the_editor_root_is_the_canonical_prefix_plus_the_fixed_leaf():
    """Assets/Music is fixed by the product; the prefix is P:\\ by fleet
    decision (CLAUDE.md). What is NOT here any more is a second, hardcoded
    root for one studio's indexing machine -- W:\\Creators_Club\\Assets\\Music
    was probed for until 2026-08-17 (COMMERCIAL_READINESS.md item 11), and an
    indexing host says where its mount is with MUSIC_LIBRARY_ROOT."""
    assert str(config.EDITOR_ROOT) == r'P:\Assets\Music'
    assert not hasattr(config, 'BASE_RIG_ROOT')


def test_an_indexing_host_names_its_own_mount(tmp_path, monkeypatch):
    monkeypatch.delenv('MUSIC_SHARE_ROOT', raising=False)
    monkeypatch.delenv('MUSIC_ROOT', raising=False)
    monkeypatch.setenv('MUSIC_LIBRARY_ROOT', str(tmp_path))
    assert config._default_share_root() == tmp_path


def test_with_nothing_set_it_is_the_editor_mount_not_a_guess(monkeypatch):
    for var in ('MUSIC_LIBRARY_ROOT', 'MUSIC_SHARE_ROOT', 'MUSIC_ROOT'):
        monkeypatch.delenv(var, raising=False)
    assert config._default_share_root() == config.EDITOR_ROOT


def test_env_overrides_the_probe(tmp_path, monkeypatch):
    monkeypatch.setenv('MUSIC_SHARE_ROOT', str(tmp_path))
    assert config._default_share_root() == tmp_path


def test_music_root_still_overrides_it(tmp_path, monkeypatch):
    """MUSIC_ROOT predates the share model; DEPLOY.md documents it and the
    tests point it at a temp library."""
    monkeypatch.delenv('MUSIC_SHARE_ROOT', raising=False)
    monkeypatch.setenv('MUSIC_ROOT', str(tmp_path))
    assert config._default_share_root() == tmp_path


def test_the_env_names_win_in_the_documented_order(tmp_path, monkeypatch):
    """There is no drive PROBE any more (2026-08-17, COMMERCIAL_READINESS.md
    item 11): "is W: mounted" only ever answered for one fleet. An indexing
    host names its mount, and the three accepted names have a fixed order so a
    machine carrying the old ones keeps working."""
    newest, older, oldest = tmp_path / 'a', tmp_path / 'b', tmp_path / 'c'
    monkeypatch.setenv('MUSIC_LIBRARY_ROOT', str(newest))
    monkeypatch.setenv('MUSIC_SHARE_ROOT', str(older))
    monkeypatch.setenv('MUSIC_ROOT', str(oldest))
    assert config._default_share_root() == newest

    monkeypatch.delenv('MUSIC_LIBRARY_ROOT')
    assert config._default_share_root() == older

    monkeypatch.delenv('MUSIC_SHARE_ROOT')
    assert config._default_share_root() == oldest
