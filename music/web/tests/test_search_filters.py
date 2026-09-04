"""The left rail applies to a description search, and a NULL is not a "no".

MUSIC-4 (usability + resilience sweep, 2026-09-03): `SearchReq` carried
`{query, k, pool}` and nothing else, so an editor who set BPM 90-120, ticked
`mood: tense` and dragged an axis, then typed "driving synth for a chase", got
60 tracks scored on the text alone -- with the rail still showing every filter
lit. The two states contradicted each other on screen.

MUSIC-14: a track the fleet ingested has `bpm IS NULL` (KNOWN_BUGS MUSIC-ING-1:
no librosa on an editor's machine), and `t.bpm >= 90` is never true of a NULL,
so a tempo filter dropped every companion upload with nothing saying so. The
rule pinned here is: an UNSET filter matches them, a set one reports how many
it dropped, and `include_unknown` takes them back.

No torch anywhere: only `/api/search` embeds text, and these tests hand the
route its hits instead of loading CLAP.

**Nothing here asserts a seeded tags/axes number.** The seeded database is
session-scoped and shared on purpose (the connection and the Index are
process-wide singletons, exactly as in production), and `rescore_library`
opens with `DELETE FROM tags; DELETE FROM axes` and rewrites every `pct` from
the real percentile pass -- so conftest's synthetic percentiles are true only
until the first test in the session that rescores (test_rescore_transaction,
test_fleet_ingest). Every bound below is therefore read from the API first and
the expected id set computed from it, which is also the stronger assertion:
the filter is checked against the data the route is actually looking at.
"""
from __future__ import annotations

import pytest

from musicweb import routes_api

from tests.conftest import TRACKS

# conftest's fourth track: bpm None, key None -- the fleet-ingested shape.
NULL_BPM_ID = 4
NULL_BPM_NAME = TRACKS[NULL_BPM_ID - 1][0]


class _StubIndex:
    """Every track is a hit, best first. `text_search` is the only thing
    /api/search calls on the index, and calling the real one needs CLAP."""

    def __init__(self, ids):
        self.ids = list(ids)

    def text_search(self, query, k=50, pool='max'):
        return [{'id': i, 'match': 100.0 - n}
                for n, i in enumerate(self.ids[:k])]


@pytest.fixture()
def all_hits(monkeypatch):
    ids = list(range(1, len(TRACKS) + 1))
    monkeypatch.setattr(routes_api, 'index', lambda: _StubIndex(ids))
    return ids


def _search(client, **body):
    body.setdefault('query', 'anything')
    return client.post('/api/search', json=body).json()


def _seeded_rows(client):
    """The four seeded tracks as the API sees them RIGHT NOW.

    Ids 1..4 are the conftest fixtures; a test that ran earlier in the session
    may have added others (and will certainly have rewritten the axes), so the
    id filter is what keeps this module's arithmetic about its own rows.
    """
    rows = client.get('/api/tracks?limit=1000').json()['tracks']
    return [r for r in rows if r['id'] in set(range(1, len(TRACKS) + 1))]


def _arousal(client):
    """{track id: arousal percentile}, whatever the last rescore left."""
    return {r['id']: r['axes']['arousal'] for r in _seeded_rows(client)
            if 'arousal' in (r.get('axes') or {})}


# --- MUSIC-4: the rail reaches the search --------------------------------------

def test_search_with_no_filters_returns_every_hit(client, all_hits):
    out = _search(client)
    assert len(out['tracks']) == len(TRACKS)
    assert out['tracks'] == sorted(out['tracks'], key=lambda r: -r['match'])


def test_search_applies_the_bpm_filter(client, all_hits):
    out = _search(client, bpm_min=100)
    assert [t['filename'] for t in out['tracks']] == [TRACKS[0][0]]


def test_search_applies_the_facet_filter(client, all_hits):
    # The label comes from the facets rather than from conftest for the reason
    # in this module's docstring: a rescore rewrites `tags` from the real
    # vocabulary, so a seeded label is not guaranteed to still exist.
    facets = client.get('/api/facets').json()
    cat = next(k for k in facets if not k.startswith('_') and facets[k])
    label = facets[cat][0]['label']
    assert _search(client, category=cat, label=label)['tracks']
    assert _search(client, category=cat, label='no such label')['tracks'] == []


def test_search_applies_the_axis_filter(client, all_hits):
    """Also the ordering pin: the JOINs carry their own placeholders and the
    id set binds LAST, so a mis-ordered params list shows up here as the wrong
    id set rather than as a subtle difference."""
    pct = _arousal(client)
    assert pct, 'no axes rows to filter on'
    # The whole range takes everything with an arousal row ...
    got = _search(client, axis='arousal', axis_min=0, axis_max=100)['tracks']
    assert {t['id'] for t in got} == set(pct)
    # ... and a window takes exactly the rows inside it, computed from the same
    # numbers the route is reading (see this module's docstring: a rescore in
    # an earlier test rewrites every percentile).
    lo = min(pct.values())
    cut = (lo + max(pct.values())) / 2
    expect = {i for i, v in pct.items() if lo <= v <= cut}
    got = _search(client, axis='arousal', axis_min=lo, axis_max=cut)['tracks']
    assert {t['id'] for t in got} == expect
    # and a window above every value takes nothing
    above = max(pct.values()) + 1
    assert _search(client, axis='arousal', axis_min=above, axis_max=above + 1)['tracks'] == []


def test_search_keeps_the_clap_ranking_under_the_filter(client, monkeypatch):
    """The filter decides membership; CLAP still decides the order."""
    monkeypatch.setattr(routes_api, 'index', lambda: _StubIndex([3, 1, 2]))
    out = _search(client, dur_min=100)
    assert [t['id'] for t in out['tracks']] == [3, 1, 2]


def test_search_still_short_circuits_an_empty_query(client, all_hits):
    assert _search(client, query='  ', bpm_min=100) == {'tracks': []}


# --- MUSIC-14: NULL means unknown, not "no" ------------------------------------

def _library(client):
    """Every track the browse route can see, unfiltered."""
    return client.get('/api/tracks?limit=1000').json()['tracks']


def test_an_unset_filter_matches_a_track_with_no_bpm(client):
    names = [t['filename'] for t in _library(client)]
    assert NULL_BPM_NAME in names


def test_a_set_bpm_filter_reports_what_it_hid(client):
    """The count is derived, not seeded: a test earlier in the session may have
    landed tracks of its own, and every one of them has a null bpm too."""
    expect = sum(1 for t in _library(client) if t['bpm'] is None)
    assert expect >= 1
    out = client.get('/api/tracks?bpm_min=60').json()
    assert NULL_BPM_NAME not in [t['filename'] for t in out['tracks']]
    assert out['unknown_hidden'] == expect
    assert out['unknown_fields'] == ['bpm']


def test_include_unknown_takes_them_back(client):
    out = client.get('/api/tracks?bpm_min=60&include_unknown=true').json()
    names = [t['filename'] for t in out['tracks']]
    assert NULL_BPM_NAME in names
    # the range is still honoured for the tracks that HAVE a value
    assert TRACKS[2][0] in names            # 70 bpm
    assert out['unknown_hidden'] == 0


def test_include_unknown_still_excludes_a_track_outside_the_range(client):
    expect = {t['id'] for t in _library(client)
              if t['bpm'] is None or t['bpm'] >= 100}
    out = client.get('/api/tracks?bpm_min=100&include_unknown=true').json()
    assert {t['id'] for t in out['tracks']} == expect
    assert NULL_BPM_ID in expect            # the fleet-ingested shape is in it


def test_no_filter_reports_nothing_hidden(client):
    out = client.get('/api/tracks').json()
    assert out['unknown_hidden'] == 0
    assert out['unknown_fields'] == []


def test_the_hidden_count_is_about_the_filtered_list(client):
    """Counted against the rest of the filter, not against the library: a
    facet nothing matches hides nothing for a NULL either."""
    out = client.get('/api/tracks?bpm_min=60&category=genre&label=nope').json()
    assert out['tracks'] == []
    assert out['unknown_hidden'] == 0


def test_search_reports_the_hidden_count_too(client, all_hits):
    """And it is about the SEARCH'S OWN hits: the stub hands the route ids
    1..4, so a track another test added must not be counted here."""
    expect = sum(1 for t in _seeded_rows(client) if t['bpm'] is None)
    out = _search(client, bpm_min=60)
    assert out['unknown_hidden'] == expect == 1
    assert NULL_BPM_NAME not in [t['filename'] for t in out['tracks']]


def test_facets_publish_the_unknown_counts(client):
    rows = _library(client)
    bpms = [t['bpm'] for t in rows if t['bpm'] is not None]
    f = client.get('/api/facets').json()
    assert f['_unknown'] == {
        'bpm': sum(1 for t in rows if t['bpm'] is None),
        'duration': sum(1 for t in rows if t['duration'] is None),
    }
    # the existing shape is untouched: the rail reads both
    assert f['_bpm'] == {'min': min(bpms), 'max': max(bpms)}


def test_newest_sort_is_accepted(client):
    """MUSIC-9: the route has always supported it; nothing sent it."""
    rows = client.get('/api/tracks?sort=newest').json()['tracks']
    assert len(rows) >= len(TRACKS)
