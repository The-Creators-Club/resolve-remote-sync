"""Browse/filter/stats endpoints, and the facet ordering the sidebar relies on."""
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


def test_ui_is_served(client):
    assert '<title>Music Tagger</title>' in client.get('/').text
    assert client.get('/app.js').headers['content-type'].startswith('application/javascript')
    assert client.get('/style.css').headers['content-type'].startswith('text/css')
