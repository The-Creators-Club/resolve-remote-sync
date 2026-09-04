"""The unblock plugin's install marker, and the in-process health snapshot.

YTWEB-5 and YTWEB-2 (usability + resilience sweep 2026-09-03).

The deployment's real PO-token path is a pip-installed plugin, not the sidecar
`pot_provider` reports on, and its boot install failing was invisible to every
health key: CR-73 (DNS not up in the container's first seconds) and CR-84
(`[Errno 13]` into a read-only /venv) each ran for days behind four WARNING
lines in a container log, while editors saw 1.8 MiB/s downloads and "the
downloaded file is empty". run.sh now writes the outcome down and this is what
reads it.

And the body of `GET /api/health` is now built by a plain function, so the
dashboard's self-diagnosis can ask in process rather than making an HTTP
request to its own single-worker uvicorn.
"""
import json

import pytest

from ytdlweb import routes_api


@pytest.fixture
def unblock_on(monkeypatch, tmp_path):
    monkeypatch.setenv('DASH_SITE_YOUTUBE_UNBLOCK', '1')
    marker = tmp_path / 'unblock-site' / 'plugin_install.json'
    monkeypatch.setenv(routes_api.PLUGIN_INSTALL_MARKER_ENV, str(marker))
    return marker


def test_the_feature_being_off_is_an_answer_not_a_silence(monkeypatch):
    monkeypatch.setenv('DASH_SITE_YOUTUBE_UNBLOCK', '0')
    state = routes_api._plugin_install_state()
    assert state['state'] == 'off'
    assert state['ok'] is None


def test_no_marker_is_not_checked_never_ok(unblock_on):
    """A boot that never got that far, or a run.sh too old to write one. Both
    have to be tellable from "installed fine" (the wave-4 rule)."""
    state = routes_api._plugin_install_state()
    assert state['ok'] is None
    assert state['state'] == 'unknown'


def test_a_successful_install_is_recorded_as_such(unblock_on):
    unblock_on.parent.mkdir(parents=True, exist_ok=True)
    unblock_on.write_text(json.dumps({
        'ok': True, 'at': '2026-09-04T10:00:00Z', 'attempts': 1,
        'error': '', 'version': '1.3.1'}), encoding='utf-8')
    state = routes_api._plugin_install_state()
    assert state['ok'] is True
    assert state['state'] == 'ok'
    assert state['version'] == '1.3.1'
    assert state['attempts'] == 1


def test_a_failed_install_carries_pips_own_last_words(unblock_on):
    """CR-84's diagnosis was in pip's stderr and nowhere a human looked."""
    unblock_on.parent.mkdir(parents=True, exist_ok=True)
    unblock_on.write_text(json.dumps({
        'ok': False, 'at': '2026-09-04T10:00:00Z', 'attempts': 4,
        'error': "[Errno 13] Permission denied: '/venv/.../yt_dlp_plugins'",
        'version': '1.3.1'}), encoding='utf-8')
    state = routes_api._plugin_install_state()
    assert state['ok'] is False
    assert state['state'] == 'failed'
    assert 'Permission denied' in state['error']
    assert state['attempts'] == 4


def test_a_corrupt_marker_never_raises(unblock_on):
    unblock_on.parent.mkdir(parents=True, exist_ok=True)
    unblock_on.write_text('{not json', encoding='utf-8')
    state = routes_api._plugin_install_state()
    assert state['ok'] is None
    assert state['state'] == 'unknown'


# ------------------------------------------------------- the health snapshot

def test_the_health_body_is_buildable_without_a_request():
    snap = routes_api.health_snapshot(None)
    for key in ('yt_dlp_stale', 'yt_dlp_age_days', 'pot_provider',
                'cookies_state', 'last_download', 'canary', 'claude',
                'worker_alive', 'plugin_install'):
        assert key in snap, key


def test_the_in_process_caller_never_probes_the_network(monkeypatch):
    """`allow_probe=False` is the dashboard's collector thread asking. A
    diagnosis that can make itself slow is one somebody turns off."""
    from ytdlweb.vendor import downloader

    monkeypatch.setenv(downloader.POT_BASE_URL_ENV, 'http://pot.invalid:4416')
    monkeypatch.setattr(routes_api, '_pot_cache', {'at': 0.0, 'state': ''})

    def never(_url):
        raise AssertionError('a probe ran on the no-probe path')

    monkeypatch.setattr(routes_api, '_probe_pot', never)
    assert routes_api._pot_provider_state(allow_probe=False) == 'unknown'
    assert routes_api.health_snapshot(None,
                                      allow_probe=False)['pot_provider'] == 'unknown'


def test_the_cached_answer_is_what_the_no_probe_path_returns(monkeypatch):
    from ytdlweb.vendor import downloader

    monkeypatch.setenv(downloader.POT_BASE_URL_ENV, 'http://pot.invalid:4416')
    monkeypatch.setattr(routes_api, '_pot_cache', {'at': 0.0, 'state': 'unreachable'})
    assert routes_api._pot_provider_state(allow_probe=False) == 'unreachable'


def test_the_route_still_probes(monkeypatch):
    """Nothing about an open page changes: the lazy one-second probe on the
    request path is what CR-73 needed and it stays."""
    from ytdlweb.vendor import downloader

    monkeypatch.setenv(downloader.POT_BASE_URL_ENV, 'http://pot.invalid:4416')
    monkeypatch.setattr(routes_api, '_pot_cache', {'at': 0.0, 'state': ''})
    monkeypatch.setattr(routes_api, '_probe_pot', lambda _url: 'ok')
    assert routes_api._pot_provider_state() == 'ok'
