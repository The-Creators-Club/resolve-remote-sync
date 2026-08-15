"""Browse/filter/stats endpoints, and the facet ordering the sidebar relies on."""
from musicweb import db, routes_api

from tests.conftest import CATEGORIES, TRACKS


def test_stats(client):
    s = client.get('/api/stats').json()
    assert s['tracks'] == len(TRACKS)
    assert s['model'] == 'test-model'
    assert s['music_root']


def test_facets_are_in_vocabulary_order(client):
    """The frontend renders facet sections in JSON key order (app.js
    paintFacets iterates Object.entries), so this order is load-bearing."""
    f = client.get('/api/facets').json()
    cats = [k for k in f if not k.startswith('_')]
    assert cats == ['genre', 'mood', 'instrument', 'use_case', 'texture']
    assert f['_axes'] == ['arousal', 'valence', 'tension', 'organic']
    assert f['_bpm'] == {'min': 70.0, 'max': 128.0}


def test_facet_counts(client):
    f = client.get('/api/facets').json()
    labels = {row['label']: row['count'] for row in f['genre']}
    assert labels == {c: len(TRACKS) for c in CATEGORIES['genre']}


def test_tracks_hydrates_tags_and_axes(client):
    rows = client.get('/api/tracks?limit=3').json()['tracks']
    assert len(rows) == 3
    r = rows[0]
    assert set(r['tags']) == set(CATEGORIES)
    assert set(r['axes']) == {'arousal', 'valence', 'tension', 'organic'}
    # sorted by filename by default
    assert [x['filename'] for x in rows] == sorted(x['filename'] for x in rows)


def test_tracks_filters(client):
    assert len(client.get('/api/tracks?bpm_min=100').json()['tracks']) == 1
    assert len(client.get('/api/tracks?dur_max=130').json()['tracks']) == 2
    hits = client.get('/api/tracks?category=genre&label=ambient').json()['tracks']
    assert len(hits) == len(TRACKS)
    assert client.get('/api/tracks?category=genre&label=nope').json()['tracks'] == []


def test_reload_drops_the_cached_connections_first(client, monkeypatch):
    """MUSIC-10 (2026-08-14): the route promises "a fresh index without
    restarting", but con() hands back a connection cached for the life of its
    thread and a sqlite3 connection is bound to an inode -- so after a deploy
    swapped music.db by rename it rebuilt the matrices from the unlinked old
    file and answered 200 with the old counts."""
    order = []
    real_invalidate, real_refresh = db.invalidate, routes_api.refresh
    monkeypatch.setattr(db, 'invalidate',
                        lambda: order.append('invalidate') or real_invalidate())
    monkeypatch.setattr(routes_api, 'refresh',
                        lambda con: order.append('refresh') or real_refresh(con))

    body = client.post('/api/reload').json()

    assert order == ['invalidate', 'refresh']
    assert body['tracks'] == len(TRACKS)


def test_ui_is_served(client):
    # Retitled from "Music Tagger" when the UI joined the dashboard theme
    # (2026-08-10): one product, one naming scheme (cf. CC SYNC // B-ROLL).
    assert '<title>CC SYNC // MUSIC</title>' in client.get('/').text
    assert client.get('/app.js').headers['content-type'].startswith('application/javascript')
    assert client.get('/style.css').headers['content-type'].startswith('text/css')
    assert client.get('/favicon.svg').headers['content-type'].startswith('image/svg')
