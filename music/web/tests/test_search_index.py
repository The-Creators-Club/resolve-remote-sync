"""The shared search index: pooling guards and how a reload reaches readers.

No torch and no CLAP here -- `Index.encoder` is a lazy property, so a fake
embedder assigned to `_encoder` exercises the whole scoring path without the
model. That is the same reason the container can run this app at all.
"""
import threading

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
