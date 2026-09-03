"""YTWEB-6 (2026-09-04): the AI health cache must be able to go red again.

`_note_ok` was the only writer on the live-call path, so the cache could only
go GREEN. Once anything had ever succeeded, a key later revoked, rate limited
past its cap or paying against an exhausted balance left `claude: 'ok'` in the
cache for the life of the container: `loadHealth` painted the pip green,
`setBanner('health', null)` cleared the pre-submit warning, and every search
after that failed twenty minutes in with `claude_auth:` in `job.error`. The
worker's `recheck_health` could not help, because it begins "return unless the
cache is red".

YTDL-5 fixed the mirror image (one transient timeout must not pin the pip red)
and is pinned in test_claude_cli.py; this file is the other direction, and the
last test here is the pair of them: red, then green again, with no restart.

    cd E:\\Projects\\resolve-remote-sync\\ytdl\\web
    ..\\..\\dashboard\\.venv\\Scripts\\python.exe -m pytest tests/test_health_recovery.py -q
"""
import pytest

from ytdlweb import claude_cli, worker
from tests.test_claude_cli import (FakeAuthError, FakeMessage,  # noqa: F401
                                   FakeStatusError, FakeTimeout, run)


@pytest.fixture(autouse=True)
def _fresh_cache():
    """The cache is a module global, exactly as in the container."""
    claude_cli._health.update({'claude': 'unknown', 'checked_at': None,
                               'detail': '', 'provider': ''})
    yield
    claude_cli._health.update({'claude': 'unknown', 'checked_at': None,
                               'detail': '', 'provider': ''})


def _green(run):
    run.outcome = FakeMessage('{"terms": [1]}')
    claude_cli.ask_json('s', 'x')
    assert claude_cli.health()['claude'] == 'ok'


def test_a_revoked_key_takes_the_pip_off_green(run):
    """THE bug: a green pip over failing searches, until someone restarts the
    container."""
    _green(run)

    run.outcome = FakeAuthError('invalid x-api-key')
    with pytest.raises(claude_cli.ClaudeError):
        claude_cli.ask_json('s', 'x')

    state = claude_cli.health()
    assert state['claude'] == 'unauthenticated'
    assert state['detail'], 'and it says what happened, for the admin'


def test_every_classified_failure_is_recorded_the_way_the_probe_records_it(run):
    """The same mapping `refresh_health` uses, so the SPA's pip and its ops
    instruction do not depend on WHICH path noticed."""
    for outcome, expected in ((FakeAuthError('no key'), 'unauthenticated'),
                              (FakeTimeout('too slow'), 'timeout'),
                              (FakeStatusError(500, 'boom'), 'error')):
        _green(run)
        run.outcome = outcome
        with pytest.raises(claude_cli.ClaudeError):
            claude_cli.ask_json('s', 'x')
        assert claude_cli.health()['claude'] == expected, outcome


def test_a_failure_on_a_request_thread_counts_too(run):
    """The two worker call sites already called note_failure; every other
    caller (the routes, the pickers) recorded nothing, which is most of them.
    `_invoke` is where they all meet."""
    _green(run)
    run.outcome = FakeAuthError('invalid x-api-key')
    with pytest.raises(claude_cli.ClaudeError):
        claude_cli._invoke('system', 'user')
    assert claude_cli.health()['claude'] == 'unauthenticated'


def test_the_worker_only_rechecks_while_the_cache_is_red(run, monkeypatch):
    _green(run)
    assert worker.recheck_health() is False, (
        'a probe is a real billed call; a green cache must not pay for one')


def test_red_then_green_again_without_a_restart(run, monkeypatch):
    """The whole point of writing red down: `recheck_health` is the thing that
    heals it, and it only ever runs while the cache is red and the worker is
    idle."""
    # Both intervals, because both are real: the worker's 300 s between
    # probes, and claude_cli's own 60 s floor (UNHEALTHY_RECHECK is above it in
    # production, so this only matters to a test that wants the next second).
    monkeypatch.setattr(worker, 'UNHEALTHY_RECHECK', 0)
    monkeypatch.setattr(claude_cli, '_MIN_PROBE_INTERVAL', 0)
    _green(run)

    run.outcome = FakeAuthError('invalid x-api-key')
    with pytest.raises(claude_cli.ClaudeError):
        claude_cli.ask_json('s', 'x')
    assert claude_cli.health()['claude'] == 'unauthenticated'

    # The admin pastes a working key into Settings -> AI providers.
    run.outcome = FakeMessage('ok')
    assert worker.recheck_health() is True
    assert claude_cli.health()['claude'] == 'ok'
    assert claude_cli.health()['detail'] == ''
