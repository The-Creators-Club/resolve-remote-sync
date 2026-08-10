"""The routes go through the resolver, not `MUSIC_ROOT / rel_path`.

A row is data, written by an indexer on another machine or by an upload, so a
rel_path that escapes the share has to be refused at the edge rather than
served. These tests plant such a row and check the route, because the
resolver's own unit tests cannot prove the route calls it.
"""
import pytest

from musicweb import db

BAD_ROWS = {
    901: '../../../../Windows/System32/config/SAM',
    902: r'C:\Windows\System32\config\SAM',
    903: '/etc/passwd',
}


@pytest.fixture()
def planted(seeded_db):
    """Rows whose rel_path is not a rel_path, removed again afterwards.

    Written on their own connection: the routes run on the TestClient's
    threadpool threads, which hold their own thread-local connections, and WAL
    makes the committed rows visible to all of them.
    """
    con = db.connect()
    try:
        for tid, rel in BAD_ROWS.items():
            con.execute("INSERT INTO tracks(id,share,rel_path,filename) "
                        "VALUES(?,'music',?,'evil.wav')", (tid, rel))
        con.commit()
        yield
        for tid in BAD_ROWS:
            con.execute('DELETE FROM tracks WHERE id=?', (tid,))
        con.commit()
    finally:
        con.close()


@pytest.mark.parametrize('track_id', sorted(BAD_ROWS))
def test_audio_refuses_a_path_that_escapes_the_share(client, planted, track_id):
    r = client.get(f'/api/audio/{track_id}')
    assert r.status_code == 400
    # the 404 branch would mean the join happened and only the file was missing
    assert r.status_code != 404


@pytest.mark.parametrize('track_id', sorted(BAD_ROWS))
def test_peaks_refuses_it_too(client, planted, track_id):
    assert client.get(f'/api/peaks/{track_id}').status_code == 400


@pytest.mark.parametrize('track_id', sorted(BAD_ROWS))
def test_reveal_refuses_it_too(client, planted, track_id):
    """reveal hands the path to Explorer, so an unvalidated join here opens an
    arbitrary folder on the host."""
    assert client.get(f'/api/reveal/{track_id}').status_code == 400


def test_a_good_row_still_resolves_and_streams(client):
    """The seeded tracks carry the default share and stream as before."""
    r = client.get('/api/audio/1', headers={'Range': 'bytes=0-9'})
    assert r.status_code == 206
    assert r.headers['content-range'].startswith('bytes 0-9/')


def test_every_seeded_row_has_the_share(seeded_db):
    con = db.connect()
    try:
        assert [r[0] for r in con.execute('SELECT DISTINCT share FROM tracks')] == ['music']
    finally:
        con.close()
