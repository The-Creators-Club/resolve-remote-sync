"""MUSIC-1 and MUSIC-5 (2026-09-04): the rescore's transaction, and its cost.

MUSIC-1. `write_scores` began `DELETE FROM tags` / `DELETE FROM axes`, built
every row in Python and committed at the end. sqlite3 auto-begins on the first
DML, so a failure in between left an OPEN write transaction, on the thread's
CACHED connection (`db.con()`), in which the library had no tags and no axes.
The fleet ingest handler caught the exception and LOGGED it without a rollback,
so the next write on that threadpool thread committed the wipe: empty facets,
for good, with the only evidence a log line. Every test in the first group
below asserts a property of that transaction rather than of the numbers.

MUSIC-5. Every `result` re-scored the whole library and rebuilt the whole
search index: ~8,700 row writes and a full matrix read per ingested track, so a
200-track album drop was ~1.7M row writes and 200 rebuilds through the
container's single SQLite writer. The rescore is now coalesced and forced once
at `release`, and a library whose tags are behind SAYS so (`/api/stats`).

    cd E:\\Projects\\resolve-remote-sync\\music\\web
    .venv\\Scripts\\python.exe -m pytest tests/test_rescore_transaction.py -q
"""
import numpy as np
import pytest

from musicweb import db, rescore, vocab
from tests.test_fleet_ingest import (FakeEncoder, claim, fake_encoder,  # noqa: F401
                                     fleet, headers, make_batch, result_body)

DIM = 8
NAMES = ['ES_Alpha.wav', 'ES_Beta.wav', 'Winter Rain.flac', '12345_67.aac']


def _unit(seed):
    rng = np.random.default_rng(seed)
    v = rng.normal(size=DIM).astype(np.float32)
    return v / np.linalg.norm(v)


def _library(path):
    con = db.connect(path)
    db.init(con)
    for i, name in enumerate(NAMES, start=1):
        con.execute(
            'INSERT INTO tracks(id, rel_path, filename, ext, bytes, duration, '
            'embedding, dim, model, analyzed_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
            (i, name, name, '.wav', 1000 + i, 60.0 + i, db.to_blob(_unit(i)),
             DIM, 'test-model', '2026-08-18T00:00:00+00:00'))
        con.execute('INSERT INTO tags(track_id,category,label,score,pct,rank) '
                    "VALUES(?,'genre','ambient',0.9,90.0,1)", (i,))
        con.execute("INSERT INTO axes(track_id,axis,raw,pct) "
                    "VALUES(?,'arousal',0.1,50.0)", (i,))
    con.execute('INSERT INTO debias(idx,vec) VALUES(0,?)', (db.to_blob(_unit(99)),))
    con.commit()
    return con


@pytest.fixture()
def encoder(monkeypatch):
    monkeypatch.setattr(rescore, '_label_space', None, raising=False)
    monkeypatch.setattr(rescore, '_label_space_key', None, raising=False)
    return FakeEncoder()


class Boom:
    """Raises the moment `write_scores` reaches the axes half, i.e. AFTER the
    two deletes and the tag inserts. Exactly where SQLITE_FULL or a MemoryError
    would land."""

    def __getitem__(self, i):
        raise RuntimeError('the data root filled up')


def _counts(con):
    return (con.execute('SELECT COUNT(*) c FROM tags').fetchone()['c'],
            con.execute('SELECT COUNT(*) c FROM axes').fetchone()['c'])


# --------------------------------------------------------------------------
# MUSIC-1: the transaction
# --------------------------------------------------------------------------

def test_a_failed_write_leaves_the_tags_that_were_there(tmp_path, encoder):
    con = _library(tmp_path / 'lib.db')
    before = _counts(con)

    with pytest.raises(RuntimeError):
        rescore.write_scores(con, [1, 2, 3, 4], {},
                             {'arousal': {'raw': Boom(), 'pct': Boom()}})

    assert not con.in_transaction, (
        'the connection is pooled: handing it back mid-transaction is the bug')
    assert _counts(con) == before


def test_the_next_write_on_that_connection_cannot_commit_the_wipe(
        tmp_path, encoder):
    """THE bug, end to end. The wipe used to sit uncommitted on the thread's
    cached connection until an unrelated write came past and committed it."""
    con = _library(tmp_path / 'lib.db')
    with pytest.raises(RuntimeError):
        rescore.write_scores(con, [1, 2, 3, 4], {},
                             {'arousal': {'raw': Boom(), 'pct': Boom()}})

    # Any later write on the same connection: another result, an /api/peaks
    # INSERT, a queue_add.
    db.set_meta(con, 'anything', 'at all')
    con.commit()

    assert _counts(con) == (4, 4)


def test_a_failed_rescore_rolls_back_and_says_the_scores_are_stale(
        tmp_path, encoder, monkeypatch):
    con = _library(tmp_path / 'lib.db')

    def explode(*a, **kw):
        raise MemoryError('9,000 tuples')

    monkeypatch.setattr(rescore, 'write_scores', explode)
    with pytest.raises(MemoryError):
        rescore.rescore_library(con, encoder)

    assert not con.in_transaction
    assert _counts(con) == (4, 4)
    assert rescore.scores_stale(con), (
        'a rescore that did not happen must be visible to somebody other than '
        'the log (/api/stats reads this)')


def test_save_debias_is_one_transaction_too(tmp_path):
    """`db.save_debias` has the same DELETE-then-insert shape, and an empty
    `debias` is not an error anywhere: it is every query quietly scored without
    the source-bias axes from then on."""
    con = _library(tmp_path / 'lib.db')

    class BadDirs:
        size = 4

        def __iter__(self):
            raise RuntimeError('numpy said no')

    with pytest.raises(RuntimeError):
        db.save_debias(con, BadDirs())
    assert not con.in_transaction
    assert db.load_debias(con).shape[0] == 1


def test_a_rescore_that_works_clears_the_stale_marker(tmp_path, encoder):
    con = _library(tmp_path / 'lib.db')
    rescore.mark_scores_stale(con)
    assert rescore.scores_stale(con)
    rescore.rescore_library(con, encoder)
    assert rescore.scores_stale(con) is None


# --------------------------------------------------------------------------
# MUSIC-5: the frequency
# --------------------------------------------------------------------------

def test_the_second_track_in_a_drop_does_not_rescore_the_whole_library(
        tmp_path, encoder):
    con = _library(tmp_path / 'lib.db')
    first = rescore.apply_for_track(con, 1, encoder)
    assert not first.get('deferred')
    assert {t['category'] for t in first['tags']} == set(vocab.CATEGORIES)

    second = rescore.apply_for_track(con, 2, encoder)
    assert second['deferred'] is True
    assert second['track_id'] == 2
    assert rescore.scores_stale(con), 'and the library says the tags are behind'


def test_the_first_drop_after_a_restart_is_always_scored(tmp_path, encoder):
    """A container that has just started knows nothing about the library's
    scores, and the first drop after a restart is the one an editor is
    watching."""
    con = _library(tmp_path / 'lib.db')
    rescore._last_rescore = None
    assert rescore.rescore_due()
    assert not rescore.apply_for_track(con, 1, encoder).get('deferred')


def test_force_is_what_release_uses(tmp_path, encoder):
    con = _library(tmp_path / 'lib.db')
    rescore.apply_for_track(con, 1, encoder)
    assert rescore.apply_for_track(con, 2, encoder)['deferred'] is True
    forced = rescore.apply_for_track(con, 2, encoder, force=True)
    assert not forced.get('deferred')
    assert {a['axis'] for a in forced['axes_values']} == set(vocab.AXES)
    assert rescore.scores_stale(con) is None


def test_the_window_is_a_window(tmp_path, encoder, monkeypatch):
    con = _library(tmp_path / 'lib.db')
    monkeypatch.setattr(rescore, 'RESCORE_MIN_SECONDS', 0.0)
    assert not rescore.apply_for_track(con, 1, encoder).get('deferred')
    assert not rescore.apply_for_track(con, 2, encoder).get('deferred')


def test_stats_carries_the_stale_marker(client):
    conn = db.con()
    try:
        rescore.mark_scores_stale(conn, '2026-09-04T14:02:00+00:00')
        body = client.get('/api/stats').json()
        assert body['scores_stale'] == '2026-09-04T14:02:00+00:00'
    finally:
        conn.execute('DELETE FROM meta WHERE key=?', (rescore.SCORES_STALE,))
        conn.commit()
    assert client.get('/api/stats').json()['scores_stale'] is None


def test_a_batch_is_fully_tagged_by_the_time_it_is_released(fleet, fake_encoder):
    """The route half: the second result in a drop is deferred, and `release`
    settles it. An editor never ends a batch with untagged tracks."""
    uid = make_batch(fleet, names=('One.wav', 'Two.wav'))
    r = claim(fleet, uid)
    assert r.status_code == 200, r.text
    items = r.json()['items']

    posted = []
    for i, item in enumerate(items):
        rr = fleet.post(f'/api/fleet/ingest/batches/{uid}/items/{item["uid"]}/result',
                        json=result_body(seed=11 + i), headers=headers())
        assert rr.status_code == 200, rr.text
        posted.append(rr.json())

    assert not posted[0]['scores'].get('deferred')
    assert posted[1]['scores']['deferred'] is True
    conn = db.con()
    assert rescore.scores_stale(conn)
    second_id = posted[1]['track_id']
    assert conn.execute('SELECT COUNT(*) c FROM tags WHERE track_id=?',
                        (second_id,)).fetchone()['c'] == 0

    rr = fleet.post(f'/api/fleet/ingest/batches/{uid}/release',
                    json={'state': 'done'}, headers=headers())
    assert rr.status_code == 200, rr.text

    assert rescore.scores_stale(conn) is None
    assert conn.execute('SELECT COUNT(*) c FROM tags WHERE track_id=?',
                        (second_id,)).fetchone()['c'] > 0

    for row in posted:
        conn.execute('DELETE FROM tracks WHERE id=?', (row['track_id'],))
    conn.commit()
