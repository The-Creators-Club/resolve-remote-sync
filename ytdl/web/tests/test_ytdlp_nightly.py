"""CR-361 (2026-10-05): the server's yt-dlp on the NIGHTLY channel.

Owner decision: "accept any yt-dlp build, daily etc, to get the latest".
ytdlp_nightly installs the newest nightly from PyPI (`--pre`) into a fresh
versions/<v> directory under /data, proves it imports, and moves a `current`
pointer that run.sh resolves onto PYTHONPATH, shadowing the image's pinned
copy. No network here: pip is faked through the `run` seam. The import proof
(_VERIFY) runs for REAL, in a child interpreter, against a stand-in yt_dlp
package -- it is the step that decides whether anything gets activated.
"""
import json
import subprocess
import sys

import pytest

from ytdlweb import config, routes_api, routes_fleet, ytdlp_nightly as yn

NIGHTLY = '2026.09.27.232945'
NOW = 1_791_000_000.0


def _fake_package(target, version, *, broken=False):
    pkg = target / 'yt_dlp'
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / '__init__.py').write_text(
        'raise ImportError("a broken build")\n' if broken else
        'class YoutubeDL:\n'
        '    def __init__(self, opts):\n'
        '        self.opts = opts\n',
        encoding='utf-8')
    (pkg / 'version.py').write_text(f"__version__ = '{version}'\n", encoding='utf-8')


class _World:
    """pip and the base-version probe, faked; the verify step, real."""

    def __init__(self, offer=NIGHTLY, base='2026.08.19', pip_rc=0, broken=False):
        self.offer, self.base, self.pip_rc, self.broken = offer, base, pip_rc, broken
        self.pip_calls = []
        self.envs = []

    def run(self, argv, timeout, env):
        self.envs.append(env)
        if argv[1:3] == ['-m', 'pip']:
            self.pip_calls.append(list(argv))
            if self.pip_rc:
                return subprocess.CompletedProcess(argv, self.pip_rc, '',
                                                   'ERROR: No matching distribution')
            target = argv[argv.index('--target') + 1]
            from pathlib import Path
            _fake_package(Path(target), self.offer, broken=self.broken)
            return subprocess.CompletedProcess(argv, 0, '', '')
        if argv[1:3] == ['-c', yn._BASE_VERSION]:
            return subprocess.CompletedProcess(argv, 0, self.base + '\n', '')
        return yn._default_run(argv, timeout, env)


@pytest.fixture
def root(tmp_path, monkeypatch):
    base = tmp_path / 'ytdlp-nightly'
    monkeypatch.setenv(yn.ROOT_ENV, str(base))
    monkeypatch.delenv(yn.SWITCH_ENV, raising=False)
    return base


def _refresh(world, root, *, at=NOW, **kw):
    return yn.refresh(str(root), run=world.run, now=lambda: at, **kw)


# ---------------------------------------------------------------- install

def test_installs_the_newest_nightly_and_points_current_at_it(root):
    world = _World()
    marker = _refresh(world, root)
    assert marker['ok'] is True, marker
    assert marker['version'] == NIGHTLY
    assert yn.read_current(str(root)) == NIGHTLY
    assert (root / 'versions' / NIGHTLY / 'yt_dlp' / 'version.py').is_file()
    # --pre IS the nightly (PyPI carries them as .dev0); --target because
    # /venv is read-only in image mode (CR-84); --no-deps so only yt-dlp moves
    argv = world.pip_calls[0]
    for flag in ('--pre', '--upgrade', '--no-deps', '--target'):
        assert flag in argv, argv
    assert argv[-1] == 'yt-dlp'
    assert '==' not in ' '.join(argv), 'unpinned by design (owner, 2026-10-05)'
    assert not [p for p in root.iterdir() if p.name.startswith(yn.STAGING_PREFIX)]
    assert json.loads((root / yn.MARKER_NAME).read_text())['ok'] is True


def test_a_check_inside_the_interval_is_not_repeated(root):
    world = _World()
    _refresh(world, root)
    _refresh(world, root, at=NOW + 3600)
    assert len(world.pip_calls) == 1
    _refresh(world, root, at=NOW + yn.MIN_INTERVAL_SECONDS + 1)
    assert len(world.pip_calls) == 2


def test_a_failed_check_is_retried_on_the_next_wake(root):
    world = _World()
    _refresh(world, root)
    world.pip_rc = 1
    _refresh(world, root, at=NOW + yn.MIN_INTERVAL_SECONDS + 1)
    world.pip_rc = 0
    _refresh(world, root, at=NOW + yn.MIN_INTERVAL_SECONDS + 60)
    assert len(world.pip_calls) == 3


def test_pip_failing_keeps_the_active_build_and_records_pips_words(root):
    world = _World()
    _refresh(world, root)
    world.pip_rc = 1
    world.offer = '2026.10.04.232901'
    marker = _refresh(world, root, min_interval=0)
    assert marker['ok'] is False
    assert 'No matching distribution' in marker['error']
    assert marker['version'] == NIGHTLY          # what is still active
    assert yn.read_current(str(root)) == NIGHTLY
    assert (root / 'versions' / NIGHTLY).is_dir()
    assert not [p for p in root.iterdir() if p.name.startswith(yn.STAGING_PREFIX)]


def test_a_build_that_does_not_import_is_never_activated(root):
    marker = _refresh(_World(broken=True), root)
    assert marker['ok'] is False
    assert 'did not import' in marker['error']
    assert yn.read_current(str(root)) == ''
    assert not (root / 'versions' / NIGHTLY).exists()


def test_a_build_older_than_the_images_own_is_refused(root):
    marker = _refresh(_World(offer='2026.08.01.000000', base='2026.08.19'), root)
    assert marker['ok'] is False
    assert 'older than' in marker['error']
    assert yn.read_current(str(root)) == ''


def test_the_same_build_again_is_a_quiet_success(root):
    world = _World()
    _refresh(world, root)
    marker = _refresh(world, root, min_interval=0)
    assert marker['ok'] is True and 'already' in marker['note']
    assert sorted(p.name for p in (root / 'versions').iterdir()) == [NIGHTLY]


def test_a_refresh_never_deletes_the_build_a_live_process_imports(root):
    world = _World()
    _refresh(world, root)                                    # A
    world.offer = '2026.10.01.232901'
    _refresh(world, root, min_interval=0, keep=(NIGHTLY,))  # B, A in use
    world.offer = '2026.10.04.232901'
    _refresh(world, root, min_interval=0, keep=(NIGHTLY,))  # C, A still in use
    names = sorted(p.name for p in (root / 'versions').iterdir())
    # A: in use. B: the previous current, kept one generation. C: current.
    assert names == [NIGHTLY, '2026.10.01.232901', '2026.10.04.232901']
    world.offer = '2026.10.05.232901'
    _refresh(world, root, min_interval=0)                    # nothing in use
    names = sorted(p.name for p in (root / 'versions').iterdir())
    assert names == ['2026.10.04.232901', '2026.10.05.232901']


def test_an_existing_directory_for_the_same_build_is_reused_not_overwritten(root):
    """It may be what a live process imports from."""
    live = root / 'versions' / NIGHTLY
    _fake_package(live, NIGHTLY)
    (live / 'yt_dlp' / 'sentinel').write_text('the live copy')
    marker = _refresh(_World(), root)
    assert marker['ok'] is True
    assert (live / 'yt_dlp' / 'sentinel').read_text() == 'the live copy'
    assert yn.read_current(str(root)) == NIGHTLY


def test_children_never_see_a_nightly_on_their_path(root, monkeypatch):
    sep = __import__('os').pathsep
    monkeypatch.setenv('PYTHONPATH', sep.join(
        ['/app/src', str(root / 'versions' / NIGHTLY), '/ytdl-app']))
    env = yn._child_env(str(root))
    assert env['PYTHONPATH'].split(sep) == ['/app/src', '/ytdl-app']


@pytest.mark.parametrize('pointer', ['../x', '.', '..', 'abc', '', '2026.09.27/../x'])
def test_a_pointer_that_is_not_a_bare_version_reads_as_none(root, pointer):
    _fake_package(root / 'versions' / NIGHTLY, NIGHTLY)
    (root / 'current').write_text(pointer + '\n')
    assert yn.read_current(str(root)) == ''


def test_boot_install_retries_and_records_the_attempts(root):
    world = _World(pip_rc=1)
    slept = []
    marker = yn.boot_install(str(root), run=world.run, now=lambda: NOW,
                             sleep=slept.append)
    assert marker['ok'] is False and marker['attempts'] == 4
    assert slept == list(yn.BOOT_RETRY_DELAYS)
    assert json.loads((root / yn.MARKER_NAME).read_text())['attempts'] == 4


def test_the_cli_always_exits_zero(root, monkeypatch):
    """A failed nightly must never stop a boot: /ytdl runs on the pinned copy."""
    monkeypatch.setattr(yn, 'boot_install', lambda base: {'ok': False, 'error': 'x'})
    assert yn.main(['install', '--root', str(root)]) == 0
    monkeypatch.setenv(yn.SWITCH_ENV, '0')
    monkeypatch.setattr(yn, 'boot_install',
                        lambda base: pytest.fail('ran with the switch off'))
    assert yn.main(['install', '--root', str(root)]) == 0


def test_the_refresher_needs_a_run_sh_that_manages_the_nightly(monkeypatch):
    monkeypatch.delenv(yn.ROOT_ENV, raising=False)
    assert yn.ensure_refresher_started() is False
    monkeypatch.setenv(yn.ROOT_ENV, '/data/ytdlp-nightly')
    monkeypatch.setenv(yn.SWITCH_ENV, '0')
    assert yn.ensure_refresher_started() is False


# ---------------------------------------------------------------- health

def test_health_is_off_without_a_managing_run_sh(monkeypatch):
    monkeypatch.delenv(yn.ROOT_ENV, raising=False)
    state = yn.health_state('2026.08.19')
    assert state['state'] == 'off' and state['running'] == '2026.08.19'


def test_health_with_no_marker_is_not_checked_never_ok(root):
    assert yn.health_state('2026.08.19')['state'] == 'unknown'


def test_health_says_a_newer_build_waits_for_a_restart(root, monkeypatch):
    _refresh(_World(), root)
    state = yn.health_state('2026.08.19')
    assert state['state'] == 'ok'
    assert state['installed'] == NIGHTLY
    assert state['pending_restart'] is True
    assert yn.health_state(NIGHTLY)['pending_restart'] is False

    monkeypatch.setattr(routes_api, '_yt_dlp_version', lambda: '2026.08.19')
    snap = routes_api.health_snapshot(None, allow_probe=False)
    assert snap['yt_dlp_nightly']['pending_restart'] is True
    assert NIGHTLY in snap['yt_dlp_age_detail']
    assert 'next dashboard restart' in snap['yt_dlp_age_detail']
    assert '—' not in snap['yt_dlp_age_detail']


def test_health_reports_the_version_actually_imported(monkeypatch):
    monkeypatch.setattr(routes_api, '_yt_dlp_version', lambda: NIGHTLY)
    snap = routes_api.health_snapshot(None, allow_probe=False)
    assert snap['yt_dlp_version'] == NIGHTLY
    assert snap['yt_dlp_nightly']['running'] == NIGHTLY


# ------------------------------------------- a 4-part version everywhere

def test_a_nightly_version_ages_by_its_date(monkeypatch):
    import datetime as dt

    monkeypatch.setattr(routes_api, '_yt_dlp_version', lambda: NIGHTLY)

    class _Today(dt.date):
        @classmethod
        def today(cls):
            return cls(2026, 10, 5)

    monkeypatch.setattr(routes_api, 'date', _Today)
    assert routes_api._yt_dlp_age_days() == 8


@pytest.mark.parametrize('reported, floor, ok', [
    (NIGHTLY, '2026.08.19', True),             # nightly above a stable floor
    ('2026.08.19', NIGHTLY, False),
    ('2026.08.19.000001', '2026.08.19', True),  # same-day nightly after stable
    (NIGHTLY, NIGHTLY, True),
])
def test_the_fleet_floor_ranks_nightlies(reported, floor, ok):
    assert routes_fleet._version_at_least(reported, floor) is ok


def test_a_nightly_floor_is_a_valid_floor():
    assert config.version_rank(NIGHTLY) == (2026, 9, 27, 232945)
    assert config._validated_floor(NIGHTLY) == NIGHTLY
    assert yn.version_rank(NIGHTLY) == (2026, 9, 27, 232945)
    assert yn.version_rank('2026.9.27.232945.dev0') is None   # pip's spelling is not yt-dlp's


def test_the_verify_script_runs_on_this_interpreter(tmp_path):
    """_VERIFY is plain source text; prove it is valid Python and that it
    refuses a copy imported from anywhere but the staged directory."""
    staged = tmp_path / 'staged'
    _fake_package(staged, NIGHTLY)
    out = subprocess.run([sys.executable, '-c', yn._VERIFY, str(staged)],
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == NIGHTLY

    # nothing staged: whatever yt_dlp this interpreter finds (the venv's, or
    # none) is not the staged copy, and that is a refusal, never a pass
    empty = tmp_path / 'empty'
    empty.mkdir()
    out = subprocess.run([sys.executable, '-c', yn._VERIFY, str(empty)],
                         capture_output=True, text=True, timeout=60)
    assert out.returncode != 0
