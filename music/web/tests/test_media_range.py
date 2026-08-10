"""HTTP Range on /api/audio. The player seeks with these, and a proxy that
rewrites or swallows them breaks scrubbing -- which is why the app is mounted
in-process rather than reverse-proxied."""
from tests.conftest import AUDIO_BYTES

SIZE = len(AUDIO_BYTES)


def test_full_body_without_range(client):
    r = client.get('/api/audio/1')
    assert r.status_code == 200
    assert r.content == AUDIO_BYTES


def test_partial_content(client):
    r = client.get('/api/audio/1', headers={'Range': 'bytes=0-99'})
    assert r.status_code == 206
    assert r.headers['content-range'] == f'bytes 0-99/{SIZE}'
    assert r.headers['content-length'] == '100'
    assert r.headers['accept-ranges'] == 'bytes'
    assert r.content == AUDIO_BYTES[:100]


def test_open_ended_range_runs_to_the_end(client):
    r = client.get('/api/audio/1', headers={'Range': f'bytes={SIZE - 10}-'})
    assert r.status_code == 206
    assert r.headers['content-range'] == f'bytes {SIZE - 10}-{SIZE - 1}/{SIZE}'
    assert r.content == AUDIO_BYTES[-10:]


def test_range_past_the_end_is_clamped(client):
    r = client.get('/api/audio/1', headers={'Range': f'bytes=0-{SIZE * 2}'})
    assert r.status_code == 206
    assert r.headers['content-range'] == f'bytes 0-{SIZE - 1}/{SIZE}'


def test_unsatisfiable_range_is_416(client):
    r = client.get('/api/audio/1', headers={'Range': f'bytes={SIZE + 10}-'})
    assert r.status_code == 416
    assert r.headers['content-range'] == f'bytes */{SIZE}'


def test_unknown_track_is_404(client):
    assert client.get('/api/audio/999').status_code == 404


def test_peaks_are_served_from_the_db(client):
    r = client.get('/api/peaks/1')
    assert r.status_code == 200
    assert r.content == bytes([0, 128, 255, 64])
