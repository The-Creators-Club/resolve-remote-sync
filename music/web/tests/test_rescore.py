"""`musicweb.rescore`: the scores, wherever they are computed.

Three producers write tags/axes/debias into this database now
(docs/MUSIC_INGEST_PLAN.md step 2): `index_music.retag` on the base rig,
`drain.apply_bundle` carrying the base rig's rows in, and -- new -- the fleet
ingest `result` route computing them here from an embedding the editor's
machine made. The point of this file is that they are the SAME numbers:

  * `test_a_bundle_carries_exactly_what_rescore_computes` scores a library,
    ships those rows through a bundle into a second index, and compares;
  * `test_apply_bundle_still_applies_the_library_wide_rescore` pins that the
    drain path is unchanged by the move (the function it calls now lives in
    rescore.py and its behaviour did not);
  * the rest hold the computation itself: percentiles are library-relative,
    the label space is cached but not stale, and the source-bias axes are the
    ones `music_index.debias` always produced.

Everything runs on a throwaway database with a fake text encoder: no torch, no
500 MB artefact, and the same `embed_text` contract the real ones satisfy.
"""
import sqlite3

import numpy as np
import pytest

from musicweb import config, db, drain, rescore, vocab

DIM = 8
NAMES = [
    'ES_Alpha.wav', 'ES_Beta.wav', 'ES_Gamma.wav', 'ES_Delta.wav',
    'ES_Epsilon.wav', 'ES_Zeta.wav', 'ES_Eta.wav', 'ES_Theta.wav',
    '01JBF47TBD7T37HMG3WXZ8HQA1.mp3', 'Ordinary Name.flac',
]


class FakeEncoder:
    """Deterministic per caption, unit length, DIM-wide. The one method
    `rescore` needs -- which is exactly why the ONNX text tower and the full
    CLAP are interchangeable in front of it."""

    def __init__(self):
        self.calls = 0

    def embed_text(self, texts):
        self.calls += 1
        out = []
        for t in texts:
            rng = np.random.default_rng(abs(hash(t)) % (2 ** 32))
            v = rng.normal(size=DIM).astype(np.float32)
            out.append(v / np.linalg.norm(v))
        return np.stack(out)


def _unit(seed):
    rng = np.random.default_rng(seed)
    v = rng.normal(size=DIM).astype(np.float32)
    return v / np.linalg.norm(v)


def _library(path, names=NAMES):
    """A fresh index holding `names`, each with an embedding and nothing else."""
    con = db.connect(path)
    db.init(con)
    for i, name in enumerate(names, start=1):
        con.execute(
            'INSERT INTO tracks(id, rel_path, filename, ext, bytes, duration, '
            'embedding, dim, model, analyzed_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
            (i, name, name, '.wav', 1000 + i, 60.0 + i, db.to_blob(_unit(i)),
             DIM, 'test-model', '2026-08-18T00:00:00+00:00'))
    con.commit()
    return con


@pytest.fixture()
def encoder(monkeypatch):
    """A fresh label-space cache per test: the cache keys on the encoder's
    identity, and a leftover entry from another test would hide a bug in the
    keying itself."""
    monkeypatch.setattr(rescore, '_label_space', None, raising=False)
    monkeypatch.setattr(rescore, '_label_space_key', None, raising=False)
    return FakeEncoder()


# --- what it computes ---------------------------------------------------------

def test_rescore_writes_every_category_and_axis(tmp_path, encoder):
    con = _library(tmp_path / 'lib.db')
    summary = rescore.rescore_library(con, encoder)

    assert summary['tracks'] == len(NAMES)
    cats = {r['category'] for r in con.execute('SELECT DISTINCT category FROM tags')}
    assert cats == set(vocab.CATEGORIES)
    axes = {r['axis'] for r in con.execute('SELECT DISTINCT axis FROM axes')}
    assert axes == set(vocab.AXES)
    # TOP_K per category per track, and one row per axis per track
    for cat, k in vocab.TOP_K.items():
        n = con.execute('SELECT COUNT(*) c FROM tags WHERE category=?',
                        (cat,)).fetchone()['c']
        assert n == k * len(NAMES), cat
    assert db.get_meta(con, 'vocab_hash') == vocab.vocab_hash()
    assert db.get_meta(con, 'tagged_at')


def test_percentiles_are_library_relative(tmp_path, encoder):
    """The reason one new track re-scores all of them: `pct` is a rank among
    the others, so it cannot be computed for a track on its own."""
    con = _library(tmp_path / 'lib.db')
    rescore.rescore_library(con, encoder)
    before = {(r['category'], r['label']): r['pct'] for r in con.execute(
        'SELECT category, label, pct FROM tags WHERE track_id=1')}

    con.execute('INSERT INTO tracks(id, rel_path, filename, ext, embedding, dim) '
                "VALUES(99,'newcomer.wav','newcomer.wav','.wav',?,?)",
                (db.to_blob(_unit(99)), DIM))
    con.commit()
    rescore.rescore_library(con, encoder)
    after = {(r['category'], r['label']): r['pct'] for r in con.execute(
        'SELECT category, label, pct FROM tags WHERE track_id=1')}
    assert before != after


def test_apply_for_track_returns_that_tracks_own_rows(tmp_path, encoder):
    con = _library(tmp_path / 'lib.db')
    got = rescore.apply_for_track(con, 3, encoder)
    assert got['track_id'] == 3
    assert {t['category'] for t in got['tags']} == set(vocab.CATEGORIES)
    assert {a['axis'] for a in got['axes_values']} == set(vocab.AXES)
    stored = con.execute('SELECT COUNT(*) c FROM tags WHERE track_id=3').fetchone()
    assert stored['c'] == len(got['tags'])


def test_an_empty_library_is_not_an_error(tmp_path, encoder):
    con = db.connect(tmp_path / 'empty.db')
    db.init(con)
    assert rescore.rescore_library(con, encoder)['tracks'] == 0


def test_the_label_space_is_built_once_per_encoder(tmp_path, encoder):
    con = _library(tmp_path / 'lib.db')
    rescore.rescore_library(con, encoder)
    calls = encoder.calls
    rescore.rescore_library(con, encoder)
    assert encoder.calls == calls, 'the cached label space was rebuilt'
    # ... but a different encoder is a different answer, so it is not shared
    other = FakeEncoder()
    rescore.rescore_library(con, other)
    assert other.calls > 0


def test_a_changed_vocabulary_invalidates_the_cache(tmp_path, encoder, monkeypatch):
    """`eval.py --sweep` mutates the vocabulary in a live process; a cached
    label space keyed only on the encoder would serve the old one (MUSIC-4's
    shape)."""
    con = _library(tmp_path / 'lib.db')
    rescore.rescore_library(con, encoder)
    calls = encoder.calls
    monkeypatch.setitem(vocab.CATEGORIES['genre'], 'kazoo core',
                        ['a kazoo ensemble in full cry'])
    rescore.rescore_library(con, encoder)
    assert encoder.calls > calls


def test_the_source_bias_axes_are_the_ones_debias_always_found(tmp_path, encoder):
    """Eight ES_ files is exactly MIN_GROUP, so one axis is found; the other
    two groups are below it and are left alone."""
    con = _library(tmp_path / 'lib.db')
    rescore.rescore_library(con, encoder)
    dirs = db.load_debias(con)
    assert dirs.shape == (1, DIM)
    assert np.isclose(np.linalg.norm(dirs[0]), 1.0)
    assert rescore.source_group('ES_Alpha.wav') == 'epidemic'
    assert rescore.source_group('01JBF47TBD7T37HMG3WXZ8HQA1.mp3') == 'ulid'
    assert rescore.source_group('Ordinary Name.flac') == 'other'


def test_the_indexers_module_names_are_the_same_functions():
    """`music_index.tagging`/`debias` are the base rig's names for these. Two
    implementations of a score is two libraries."""
    if not config.add_indexer_to_path():
        pytest.skip('no music/indexer checkout beside this tree')
    from music_index import debias, tagging
    assert tagging.score_all is rescore.score_all
    assert tagging.build_label_space is rescore.build_label_space
    assert tagging.write_scores is rescore.write_scores
    assert debias.compute_directions is rescore.compute_directions


# --- the bundle path ----------------------------------------------------------

def _bundle_from(con, path):
    """A drain bundle carrying only the library-wide rescore rows.

    Built with drain's own schema and its own copy routine, so what is compared
    below is what a real drain would ship -- not a hand-rolled approximation of
    it.
    """
    out = sqlite3.connect(str(path))
    out.row_factory = sqlite3.Row
    out.executescript(drain._BUNDLE_SCHEMA)
    drain._copy_rescore(con, out)
    out.commit()
    return out


def test_a_bundle_carries_exactly_what_rescore_computes(tmp_path, encoder):
    """The two producers, compared row for row.

    Score a library here; ship those rows through a bundle into a second copy
    of the same library; the tags, the percentiles and the source-bias axes
    must be identical. If they ever are not, one of the three places tracks get
    scored has drifted, and search and facets would disagree about the same
    audio depending on which door it came in by.
    """
    rig = _library(tmp_path / 'rig.db')
    rescore.rescore_library(rig, encoder)
    bundle = _bundle_from(rig, tmp_path / 'bundle.db')

    nas = _library(tmp_path / 'nas.db')
    assert nas.execute('SELECT COUNT(*) c FROM tags').fetchone()['c'] == 0
    touched = rescore.apply_bundle_rows(nas, bundle)
    nas.commit()
    assert touched == len(NAMES)

    def rows(con, sql):
        return [tuple(r) for r in con.execute(sql)]

    tags_sql = ('SELECT t.rel_path, g.category, g.label, g.score, g.pct, g.rank '
                'FROM tags g JOIN tracks t ON t.id=g.track_id '
                'ORDER BY t.rel_path, g.category, g.label')
    axes_sql = ('SELECT t.rel_path, a.axis, a.raw, a.pct FROM axes a '
                'JOIN tracks t ON t.id=a.track_id ORDER BY t.rel_path, a.axis')
    assert rows(nas, tags_sql) == rows(rig, tags_sql)
    assert rows(nas, axes_sql) == rows(rig, axes_sql)
    assert np.array_equal(db.load_debias(nas), db.load_debias(rig))


def test_applying_a_bundle_twice_changes_nothing(tmp_path, encoder):
    """Every write is keyed and idempotent -- the property that lets a failed
    apply simply be re-run."""
    rig = _library(tmp_path / 'rig.db')
    rescore.rescore_library(rig, encoder)
    bundle = _bundle_from(rig, tmp_path / 'bundle.db')
    nas = _library(tmp_path / 'nas.db')
    rescore.apply_bundle_rows(nas, bundle)
    nas.commit()
    first = [tuple(r) for r in nas.execute('SELECT * FROM tags ORDER BY track_id, '
                                           'category, label')]
    rescore.apply_bundle_rows(nas, bundle)
    nas.commit()
    assert [tuple(r) for r in nas.execute('SELECT * FROM tags ORDER BY track_id, '
                                          'category, label')] == first


def test_a_track_the_live_index_no_longer_has_is_skipped(tmp_path, encoder):
    """A bundle is drained from a COPY, and anything the copy held that is gone
    here was deleted deliberately (a prune, a rename) in the meantime."""
    rig = _library(tmp_path / 'rig.db')
    rescore.rescore_library(rig, encoder)
    bundle = _bundle_from(rig, tmp_path / 'bundle.db')
    nas = _library(tmp_path / 'nas.db', names=NAMES[:3])
    assert rescore.apply_bundle_rows(nas, bundle) == 3


def test_apply_bundle_still_applies_the_library_wide_rescore(tmp_path, encoder):
    """The drain path end to end, through the public entry point, after the
    move: `drain.apply_bundle` -> `rescore.apply_bundle_rows`.

    The bundle is built by drain's own exporter off a journal row, which is the
    shape the base rig really produces.
    """
    rig = _library(tmp_path / 'rig.db')
    rescore.rescore_library(rig, encoder)
    uid = 'a' * 32
    rig.execute(
        'INSERT INTO ingest_queue(uid, rel_path, orig_name, bytes, duration, '
        "content_hash, state, queued_at) VALUES(?,?,?,?,?,?,'done',?)",
        (uid, NAMES[0], NAMES[0], 1001, 61.0, 'hash0',
         '2026-08-18T00:00:00+00:00'))
    rig.commit()
    report_path = tmp_path / 'drain.db'
    drain.export_bundle(rig, [uid], report_path, source='test')

    nas = _library(tmp_path / 'nas.db')
    nas.execute(
        'INSERT INTO ingest_queue(uid, rel_path, orig_name, bytes, duration, '
        "content_hash, state, queued_at) VALUES(?,?,?,?,?,?,'pending',?)",
        (uid, NAMES[0], NAMES[0], 1001, 61.0, 'hash0',
         '2026-08-18T00:00:00+00:00'))
    nas.commit()

    report = drain.apply_bundle(nas, report_path)
    assert report['applied'] == [uid]
    assert report['rescored_tracks'] == len(NAMES)
    assert nas.execute('SELECT COUNT(*) c FROM tags').fetchone()['c'] == (
        rig.execute('SELECT COUNT(*) c FROM tags').fetchone()['c'])
