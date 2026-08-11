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


# --- suffix ranges (MUSIC-1) --------------------------------------------------
# `bytes=-N` is "the LAST N bytes", not "bytes 0 through N". Players ask for
# them to read an mp3's ID3v1/Xing/LAME trailer or an m4a's moov atom; served
# from the front, the file's duration comes back wrong or seeking is refused.

def test_suffix_range_serves_the_tail(client):
    r = client.get('/api/audio/1', headers={'Range': 'bytes=-128'})
    assert r.status_code == 206
    assert r.headers['content-range'] == f'bytes {SIZE - 128}-{SIZE - 1}/{SIZE}'
    assert r.headers['content-length'] == '128'
    assert r.content == AUDIO_BYTES[-128:]


def test_suffix_range_bigger_than_the_file_is_the_whole_file(client):
    r = client.get('/api/audio/1', headers={'Range': f'bytes=-{SIZE * 3}'})
    assert r.status_code == 206
    assert r.headers['content-range'] == f'bytes 0-{SIZE - 1}/{SIZE}'
    assert r.content == AUDIO_BYTES


def test_zero_length_suffix_is_416(client):
    """`bytes=-0` asks for the last zero bytes: satisfiable by nothing."""
    r = client.get('/api/audio/1', headers={'Range': 'bytes=-0'})
    assert r.status_code == 416
    assert r.headers['content-range'] == f'bytes */{SIZE}'


# --- headers this app will not act on -----------------------------------------
# RFC 7233: an invalid or unrecognised Range is IGNORED, and the response is a
# plain 200 over the whole entity. A 206 claiming to satisfy a request the
# server never parsed is the worse failure -- the client believes the offsets.

def test_an_inverted_range_is_ignored(client):
    r = client.get('/api/audio/1', headers={'Range': 'bytes=200-100'})
    assert r.status_code == 200
    assert 'content-range' not in r.headers
    assert r.content == AUDIO_BYTES


def test_an_unparseable_range_is_ignored(client):
    for bad in ('bytes=abc-def', 'bytes=', 'items=0-10', 'garbage', 'bytes=-'):
        r = client.get('/api/audio/1', headers={'Range': bad})
        assert r.status_code == 200, bad
        assert 'content-range' not in r.headers, bad
        assert r.content == AUDIO_BYTES, bad


def test_a_multi_range_request_is_ignored(client):
    """This app answers one range; multipart/byteranges it does not do. A 200
    is the honest answer, and RFC 7233 allows it."""
    r = client.get('/api/audio/1', headers={'Range': 'bytes=0-9,20-29'})
    assert r.status_code == 200
    assert r.content == AUDIO_BYTES


def test_whitespace_around_the_range_is_tolerated(client):
    r = client.get('/api/audio/1', headers={'Range': ' bytes = 0 - 99 '})
    assert r.status_code == 206
    assert r.headers['content-range'] == f'bytes 0-99/{SIZE}'


def test_unknown_track_is_404(client):
    assert client.get('/api/audio/999').status_code == 404


def test_peaks_are_served_from_the_db(client):
    r = client.get('/api/peaks/1')
    assert r.status_code == 200
    assert r.content == bytes([0, 128, 255, 64])
