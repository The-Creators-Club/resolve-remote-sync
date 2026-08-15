"""The shared search index: pooling guards and how a reload reaches readers.

No torch and no CLAP here -- `Index.encoder` is a lazy property, so a fake
embedder assigned to `_encoder` exercises the whole scoring path without the
model. That is the same reason the container can run this app at all.
"""
import threading
import time

import numpy as np
import pytest

from musicweb import db, search

DIM = 8


def _unit(seed):
    rng = np.random.default_rng(seed)
    v = rng.normal(size=DIM).astype(np.float32)
    return v / np.linalg.norm(v)


class FakeEncoder:
    """Answers every query with the same unit vector."""

    def __init__(self, seed=7):
        self.vec = _unit(seed)

    def embed_text(self, texts):
        return np.stack([self.vec for _ in texts])


def _index_over(path, windows=True, tracks=True):
    con = db.connect(path)
    db.init(con)
    if tracks:
        for i in range(1, 4):
            con.execute('INSERT INTO tracks(id,rel_path,filename,ext,embedding,'
                        'dim,file_hash,model) VALUES(?,?,?,?,?,?,?,?)',
                        (i, f'{i}.wav', f'{i}.wav', '.wav', db.to_blob(_unit(i)),
                         DIM, f'h{i}', 'test-model'))
            if windows:
                con.execute('INSERT INTO windows(track_id,idx,t0,t1,embedding) '
                            'VALUES(?,0,0.0,10.0,?)', (i, db.to_blob(_unit(i * 10))))
    con.commit()
    idx = search.Index(con)
    idx._encoder = FakeEncoder()
    return con, idx


# --- MUSIC-7: each pool guards the matrix it actually reads -------------------

def test_whole_track_search_works_without_window_rows(tmp_path):
    """A library with track embeddings but no `windows` rows -- an index built
    before windows existed, or one whose window pass was interrupted -- used to
    answer EVERY 'whole track' search with an empty result, which the UI shows
    as a genuine miss rather than as a broken index."""
    con, idx = _index_over(tmp_path / 'nowin.db', windows=False)
    try:
        assert idx.win_mat.size == 0
        hits = idx.text_search('anything', pool='mean')
        assert len(hits) == 3
        assert {h['id'] for h in hits} == {1, 2, 3}
    finally:
        con.close()


def test_any_moment_search_still_needs_windows(tmp_path):
    con, idx = _index_over(tmp_path / 'nowin2.db', windows=False)
    try:
        assert idx.text_search('anything', pool='max') == []
    finally:
        con.close()


def test_both_pools_are_empty_on_an_empty_library(tmp_path):
    con, idx = _index_over(tmp_path / 'empty.db', tracks=False)
    try:
        assert idx.text_search('anything', pool='mean') == []
        assert idx.text_search('anything', pool='max') == []
    finally:
        con.close()


def test_both_pools_answer_a_normal_index(tmp_path):
    con, idx = _index_over(tmp_path / 'full.db')
    try:
        assert len(idx.text_search('anything', pool='mean')) == 3
        assert len(idx.text_search('anything', pool='max')) == 3
    finally:
        con.close()


# --- MUSIC-10: refresh swaps a whole index, it does not mutate the live one ---

@pytest.fixture()
def isolated_index(monkeypatch):
    """Keep the module singleton out of the other tests' way."""
    monkeypatch.setattr(search, '_index', None)


def test_refresh_swaps_the_object_and_leaves_the_old_one_intact(tmp_path,
                                                                isolated_index):
    """`reload()` used to overwrite the live index statement by statement, so a
    request already holding it could read the new `sim_mat` against the old
    `pos` and answer /api/similar with a different track's neighbours."""
    con, _ = _index_over(tmp_path / 'swap.db')
    try:
        search._index = search.Index(con)
        before = search.index()
        snapshot = (list(before.track_ids), before.sim_mat.copy(), dict(before.pos))

        con.execute('INSERT INTO tracks(id,rel_path,filename,ext,embedding,dim,'
                    "file_hash,model) VALUES(4,'4.wav','4.wav','.wav',?,?,'h4',"
                    "'test-model')", (db.to_blob(_unit(4)), DIM))
        con.commit()

        after = search.refresh(con)
        assert after is not before
        assert search.index() is after
        assert len(after.track_ids) == 4 and 4 in after.pos

        # the object a concurrent request is still holding never changed
        assert list(before.track_ids) == snapshot[0]
        assert np.array_equal(before.sim_mat, snapshot[1])
        assert before.pos == snapshot[2]
    finally:
        con.close()


def test_refresh_is_visible_to_every_thread(tmp_path, isolated_index):
    con, _ = _index_over(tmp_path / 'threads.db')
    try:
        search._index = search.Index(con)
        fresh = search.refresh(con)
        seen = []
        ts = [threading.Thread(target=lambda: seen.append(search.index()))
              for _ in range(4)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        assert all(s is fresh for s in seen)
    finally:
        con.close()


# --- MUSIC-5 / MUSIC-8: the models are per PROCESS, not per Index ------------

@pytest.fixture()
def no_models(monkeypatch):
    """Empty the module-level model cache, and put it back afterwards."""
    monkeypatch.setattr(search, '_encoder', None)
    monkeypatch.setattr(search, '_clap', None)


def test_two_cold_searches_build_one_encoder(no_models, monkeypatch):
    """MUSIC-5 (2026-08-14): the lazy load was an unguarded check-then-assign
    on the Index, and /api/search is a sync route -- so two requests arriving
    inside the ~2 s cold load both saw None and both built an
    ort.InferenceSession over the 500 MB artefact. Doubling the peak is the one
    thing the whole ONNX exercise exists to avoid, in a container that is also
    serving the fleet dashboard."""
    built = []
    loading = threading.Event()

    def slow_load(directory=None):
        loading.set()
        time.sleep(0.1)                    # the cold-load window
        enc = FakeEncoder(len(built))
        built.append(enc)
        return enc

    monkeypatch.setattr(search.text_encoder, 'load', slow_load)

    got = []
    first = threading.Thread(target=lambda: got.append(search.shared_encoder()))
    second = threading.Thread(target=lambda: got.append(search.shared_encoder()))
    first.start()
    assert loading.wait(timeout=5)         # the second arrives mid-load
    second.start()
    first.join(); second.join()

    assert len(built) == 1, f'{len(built)} encoders were loaded'
    assert got[0] is got[1] is built[0]


def test_the_encoder_is_loaded_once_for_the_whole_process(no_models, monkeypatch):
    loads = []
    monkeypatch.setattr(search.text_encoder, 'load',
                        lambda directory=None: loads.append(1) or FakeEncoder())
    first = search.shared_encoder()
    assert search.shared_encoder() is first
    assert len(loads) == 1


def test_refresh_keeps_the_loaded_models(tmp_path, isolated_index, no_models,
                                         monkeypatch):
    """MUSIC-8 (2026-08-14): both models were cached ON the Index, and
    `refresh` replaces the Index -- after every inline ingest and every
    /api/reload. Dropping three cues one at a time paid three full 777 MB
    ClapModel loads, and a reload made the next search pay the ONNX cold start
    again for nothing. Neither model depends on anything the Index holds."""
    loads = []
    monkeypatch.setattr(search.text_encoder, 'load',
                        lambda directory=None: loads.append(1) or FakeEncoder())
    con, _ = _index_over(tmp_path / 'keep.db')
    try:
        search._index = search.Index(con)
        encoder = search.index().encoder
        clap = object()
        monkeypatch.setattr(search, '_clap', clap)

        after = search.refresh(con)

        assert after.encoder is encoder
        assert after.clap is clap
        assert len(loads) == 1
    finally:
        con.close()


def test_an_index_still_takes_an_injected_encoder(tmp_path, no_models):
    """The tests' own escape hatch, and the reason `_encoder` survives on the
    instance at all: a fake assigned there must beat the shared one."""
    con, idx = _index_over(tmp_path / 'inject.db')
    try:
        assert idx._encoder is not None
        assert idx.encoder is idx._encoder
        assert search._encoder is None       # nothing was loaded to find that out
    finally:
        con.close()


def test_the_index_is_consistent_while_refreshes_run(tmp_path, isolated_index):
    """The property the swap exists for: whatever `index()` hands a request,
    its matrices and its position map describe the same library."""
    con, _ = _index_over(tmp_path / 'race.db')
    stop = threading.Event()
    bad = []

    def reader():
        while not stop.is_set():
            i = search.index()
            ids, pos, mat = i.track_ids, i.pos, i.sim_mat
            if len(ids) != mat.shape[0] or len(pos) != len(ids):
                bad.append((len(ids), mat.shape, len(pos)))

    try:
        search._index = search.Index(con)
        t = threading.Thread(target=reader)
        t.start()
        # a separate connection: the writer thread here is this one, and the
        # reader only ever touches numpy arrays (which is why index() is safe
        # across threads at all)
        for n in range(4, 12):
            con.execute('INSERT INTO tracks(id,rel_path,filename,ext,embedding,'
                        'dim,file_hash,model) VALUES(?,?,?,?,?,?,?,?)',
                        (n, f'{n}.wav', f'{n}.wav', '.wav', db.to_blob(_unit(n)),
                         DIM, f'h{n}', 'test-model'))
            con.commit()
            search.refresh(con)
        stop.set()
        t.join()
        assert not bad, bad
    finally:
        stop.set()
        con.close()
