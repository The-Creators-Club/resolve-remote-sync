"""Similarity must work with no torch installed.

Only /api/search embeds text, and it does so through a lazily-imported CLAP.
Everything else -- browse, filter, similarity, streaming, the UI -- runs off
embeddings the base rig already computed, which is the whole reason the web
half can live in a container without a GPU or a 2.5 GB torch wheel.
"""
import sys

import numpy as np

from musicweb import projection


def test_torch_is_not_imported_by_the_app():
    assert 'torch' not in sys.modules


def test_similar_returns_neighbours(client):
    rows = client.get('/api/similar/1?k=3').json()['tracks']
    assert len(rows) == 3
    assert all(r['id'] != 1 for r in rows)          # never itself
    assert rows == sorted(rows, key=lambda r: -r['match'])
    assert 'tags' in rows[0] and 'axes' in rows[0]


def test_similar_k_is_respected(client):
    assert len(client.get('/api/similar/1?k=1').json()['tracks']) == 1


def test_similar_unknown_track_is_empty(client):
    assert client.get('/api/similar/999').json()['tracks'] == []


def test_empty_query_short_circuits_before_clap(client):
    """A blank search must not load the model just to return nothing."""
    assert client.post('/api/search', json={'query': '   '}).json() == {'tracks': []}
    assert 'torch' not in sys.modules
