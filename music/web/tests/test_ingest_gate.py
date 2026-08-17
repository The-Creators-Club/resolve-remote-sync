"""Who may write into the music library, and how much in one request.

Both halves of COMMERCIAL_READINESS.md item 15's music row, 2026-08-17:

  fail-closed   a STANDALONE musicweb has no login in front of it, so an
                unconfigured MUSIC_INGEST_TOKEN closes /api/ingest (503)
                instead of leaving an anonymous write path that lands files in
                the shared library and runs ffmpeg on them. Mounted in the
                dashboard the session is the credential and always was -- the
                mount declares that with config.set_login_gated(True).

  bounded       the dashboard's body_size_gate only makes a DECLARATION check
                on /music/api/ingest (the multipart body is spooled past it on
                purpose), so nothing counted the parts themselves.

The refusals are checked BEFORE anything is written: none of these tests needs
ffmpeg, and a leaked file in the library would be the failure.
"""
import io

import pytest
from fastapi.testclient import TestClient

from musicweb import config
from musicweb.main import app

FILE = ('cue.wav', b'\x00fake audio' * 10, 'audio/wav')


@pytest.fixture()
def bare(seeded_db):
    """A client with NO default ingest header, unlike conftest's."""
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def unconfigured(monkeypatch):
    """No token, and nothing authenticating the app: the standalone posture."""
    monkeypatch.delenv('MUSIC_INGEST_TOKEN', raising=False)
    monkeypatch.setattr(config, '_LOGIN_GATED', False)


def test_ingest_refuses_when_no_token_is_configured(bare, unconfigured):
    r = bare.post('/api/ingest', files={'files': FILE})
    assert r.status_code == 503
    assert 'MUSIC_INGEST_TOKEN' in r.json()['detail']


def test_ingest_refuses_a_wrong_token(bare, monkeypatch):
    monkeypatch.setenv('MUSIC_INGEST_TOKEN', 'the-real-token')
    monkeypatch.setattr(config, '_LOGIN_GATED', False)
    r = bare.post('/api/ingest', files={'files': FILE},
                  headers={'X-Ingest-Token': 'not-it'})
    assert r.status_code == 401


def test_a_non_ascii_token_is_a_401_not_a_500(bare, monkeypatch):
    """hmac.compare_digest raises TypeError above U+007F; the dashboard's own
    gate met this as DASH-5 and answered a refusal with a traceback."""
    monkeypatch.setenv('MUSIC_INGEST_TOKEN', 'the-real-token')
    monkeypatch.setattr(config, '_LOGIN_GATED', False)
    r = bare.post('/api/ingest', files={'files': FILE},
                  # bytes: httpx will not encode a non-ASCII str header at all,
                  # and starlette decodes what arrives as latin-1.
                  headers={'X-Ingest-Token': 'thé-real-token'.encode('utf-8')})
    assert r.status_code == 401


def test_the_dashboard_mount_makes_the_session_the_credential(bare, unconfigured):
    """Mounted, no token, no header -- and ingest is reachable.

    This is the fleet's posture: breaking it would take drag-and-drop away
    from every editor, since the SPA has no token to send.
    """
    config.set_login_gated(True)
    try:
        r = bare.post('/api/ingest', files={'files': FILE})
        # Past the credential check. What it answers next depends on whether
        # this host has ffmpeg (503) or lands the file (200); either way it is
        # NOT the 503 the unconfigured case raises, so assert on the detail.
        assert r.status_code != 401
        if r.status_code == 503:
            assert 'MUSIC_INGEST_TOKEN' not in r.json()['detail']
    finally:
        config.set_login_gated(False)


def test_too_many_files_in_one_request_is_refused(client, monkeypatch):
    monkeypatch.setattr(config, 'MAX_INGEST_FILES', 3)
    files = [('files', (f'cue{i}.wav', io.BytesIO(b'x' * 10), 'audio/wav'))
             for i in range(4)]
    r = client.post('/api/ingest', files=files)
    assert r.status_code == 413
    assert 'too many files' in r.json()['detail']


def test_an_oversized_file_is_refused(client, monkeypatch):
    monkeypatch.setattr(config, 'MAX_INGEST_FILE_BYTES', 16)
    r = client.post('/api/ingest',
                    files={'files': ('big.wav', b'x' * 64, 'audio/wav')})
    assert r.status_code == 413
    assert 'per-file limit' in r.json()['detail']


def test_an_oversized_batch_is_refused(client, monkeypatch):
    """Each part is legal on its own; the request as a whole is not."""
    monkeypatch.setattr(config, 'MAX_INGEST_FILE_BYTES', 64)
    monkeypatch.setattr(config, 'MAX_INGEST_TOTAL_BYTES', 100)
    files = [('files', (f'cue{i}.wav', io.BytesIO(b'x' * 60), 'audio/wav'))
             for i in range(3)]
    r = client.post('/api/ingest', files=files)
    assert r.status_code == 413
    assert 'ingest request is' in r.json()['detail']
