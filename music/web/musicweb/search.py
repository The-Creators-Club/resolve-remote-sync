"""Query logic. Embedding matrices are loaded once and cached in memory --
397 tracks x 512 floats is under a megabyte, so brute-force cosine beats any
index structure here.
"""
import threading
import time

import numpy as np

from musicweb import config, db, projection, text_encoder
from musicweb.projection import l2norm


class Index:
    """Built once and never mutated afterwards.

    Picking up a changed library builds a NEW Index and swaps the module
    reference (see `refresh`). It used to have a `reload()` that overwrote a
    live shared object statement by statement, which is MUSIC-10 (2026-08-11):
    a concurrent /api/similar could read the new `sim_mat` against the old
    `pos` and answer with the neighbours of a different track.
    """

    def __init__(self, con):
        self.track_ids, self.track_mat = db.load_matrix(con)
        self.win_tids, self.win_mat = db.load_window_matrix(con)
        # Project the source/codec axes out of the audio side. This is an
        # INDEX-SIDE, SIMILARITY-ONLY transform: text queries are deliberately
        # NOT projected (see the measurement below and projection.apply's
        # docstring), and text_search deliberately scores against the raw
        # matrices. The asymmetry looks like a bug and is not -- "fixing" it
        # halves text retrieval.
        self.dirs = db.load_debias(con)
        # Debias applies to SIMILARITY ONLY. Measured: erasing the source axes
        # takes ES-seed->ES neighbours from 53.7% to 40.5% (base 36%), but it
        # takes text retrieval from 40% to 20% top-10 -- those axes evidently
        # carry content that text queries lean on, and text lives on the far
        # side of CLAP's modality gap. So keep a raw copy for search.
        self.sim_mat = (projection.apply(self.track_mat, self.dirs)
                        if self.dirs.size else self.track_mat)
        self.pos = {tid: i for i, tid in enumerate(self.track_ids)}
        # What the library looked like when these matrices were built, so a
        # change made by ANOTHER process can be noticed without a restart
        # (music-2, 2026-08-21) -- see `index()`. Recorded from the live
        # database rather than from `con`, because the module-level index is
        # always the live one; an Index built over a copy (eval --sweep) is
        # never installed here and nothing reads this on it.
        self.built_from = (db.generation(), db.file_state())
        # Injection slots, not caches: both models live at module scope (see
        # shared_encoder/shared_clap). Left here because the tests assign a fake
        # embedder to an Index without loading anything.
        self._clap = None
        self._encoder = None

    @property
    def encoder(self):
        """Query-text embedder, loaded lazily so the server starts instantly
        and only pays the model cost when someone actually runs a text search.

        Normally this is the exported text tower run by onnxruntime (see
        musicweb/text_encoder.py): 125M of CLAP's 194M params, no torch, no
        audio tower. If the artefact has not been exported it falls back to the
        full ClapModel, which is what this used to do unconditionally -- so a
        dev checkout still searches, it just pays for torch to do it.

        The instance holds no cache of its own (MUSIC-8, 2026-08-14): `refresh`
        swaps a whole new Index in on every inline ingest and after every
        /api/reload, and caching the model on the Index threw away a 500 MB
        onnxruntime session (or a 777 MB ClapModel) each time it did.
        """
        if self._encoder is not None:
            return self._encoder
        return shared_encoder()

    @property
    def clap(self):
        """The FULL CLAP model, audio tower included. Lazy, and deliberately
        separate from `encoder`.

        Text search does not come through here any more, but ingest does:
        routes_ingest hands this to music_index.ingest to embed *audio*, which
        the text-only artefact cannot do and which only ever happens on the
        base rig. Keeping the two apart is what lets the container hold only
        the text half.
        """
        if self._clap is not None:
            return self._clap
        return shared_clap()

    def text_search(self, query, k=50, pool='max'):
        """Free-text search over the CLAP embedding space.

        pool='max'  -- score a track by its single best-matching 10s window.
                       Best overall in eval (40% top-10 vs 20% for the mean),
                       because a cue with a quiet intro and a huge finish still
                       surfaces for "epic climax".
        pool='mean' -- score by the whole-track embedding. Max-pooling is
                       biased toward tracks with one dramatic peak, which is
                       wrong for queries about sustained character: "sparse
                       ominous drone under an interview" wants a track that is
                       quiet *throughout*, not one with a quiet bar in it.

        The UI exposes this as "any moment" vs "whole track".
        """
        # Each pool reads a different matrix, so each guards its own (MUSIC-7,
        # 2026-08-11): one shared `win_mat` guard made a database with track
        # embeddings but no window rows answer EVERY whole-track search with an
        # empty result the UI shows as a genuine miss.
        if (self.track_mat if pool == 'mean' else self.win_mat).size == 0:
            return []
        q = l2norm(self.encoder.embed_text([query])[0])

        # ids must be plain Python ints: sqlite3 binds a numpy int64 as an
        # opaque value that matches no row, so a numpy id silently yields
        # zero results rather than an error
        best = {}
        if pool == 'mean':
            sims = self.track_mat @ q
            for tid, s in zip(self.track_ids, sims):
                best[int(tid)] = float(s)
        else:
            sims = self.win_mat @ q                              # (W,)
            for tid, s in zip(self.win_tids, sims):
                tid, s = int(tid), float(s)
                if s > best.get(tid, -9e9):
                    best[tid] = s
        ranked = sorted(best.items(), key=lambda kv: -kv[1])[:k]
        if not ranked:
            return []

        # min-max normalise to a 0-100 "match" for display only; CLAP's raw
        # cosine values are not meaningful to a human on their own
        vals = [v for _, v in ranked]
        lo, hi = min(vals), max(vals)
        span = (hi - lo) or 1.0
        return [{'id': tid, 'score': s, 'match': round((s - lo) / span * 100, 1)}
                for tid, s in ranked]

    def similar(self, track_id, k=20):
        """Nearest neighbours by overall character, with the source/codec axes
        projected out so results are not dominated by one catalogue."""
        if track_id not in self.pos or self.sim_mat.size == 0:
            return []
        v = self.sim_mat[self.pos[track_id]]
        sims = self.sim_mat @ v
        order = np.argsort(-sims)
        out = []
        for i in order:
            tid = int(self.track_ids[i])
            if tid == track_id:
                continue
            out.append({'id': tid, 'score': float(sims[i])})
            if len(out) >= k:
                break
        return out


_index = None
_index_lock = threading.Lock()

# The two models, held PER PROCESS rather than per Index, each behind its own
# lock (MUSIC-5 and MUSIC-8, 2026-08-14). Neither depends on anything an Index
# holds -- the encoder is a pure function of the artefact directory and Clap of
# CLAP_MODEL -- so an Index has no business owning them:
#
#   * unguarded, two cold /api/search requests (a sync route, so FastAPI runs
#     them on the threadpool) both saw `None` and both built an
#     ort.InferenceSession over the ~500 MB artefact, doubling the peak in a
#     container whose whole reason for running ONNX is memory. On the CLAP
#     fallback the loser was a full 777 MB ClapModel.
#   * cached on the Index, `refresh()` discarded them on every inline ingest,
#     so drag-and-dropping three cues one at a time loaded CLAP three times.
#
# Separate locks on purpose: an ingest loading the 2.6 s audio tower must not
# hold up a search that only needs the text one.
_encoder = None
_encoder_lock = threading.Lock()
_clap = None
_clap_lock = threading.Lock()


def shared_encoder():
    """The process-wide query-text embedder. Built once, on first use."""
    global _encoder
    with _encoder_lock:
        if _encoder is None:
            _encoder = text_encoder.load()
        return _encoder


def shared_clap():
    """The process-wide FULL CLAP model (audio tower included).

    CLAP lives with the indexer, so the import needs music/indexer on sys.path
    -- see config.add_indexer_to_path. Only the base rig ever gets here.
    """
    global _clap
    with _clap_lock:
        if _clap is None:
            config.add_indexer_to_path()
            from music_index.clap_model import Clap
            _clap = Clap()
        return _clap


# How often the shared index is allowed to ask whether the database has moved
# under it. A stat of two files, so the check itself is nothing -- the interval
# is about the REBUILD it can trigger: during a burst of fleet ingest every
# write would otherwise re-read every embedding once per search.
STALE_CHECK_SECONDS = 2.0
_last_stale_check = 0.0


def _looks_stale(idx):
    """Has the database changed since `idx` was built, by anyone at all?

    music-2, 2026-08-21. The matrices were built once per process and only
    refresh() replaced them, and the only callers of refresh are this app's own
    write paths and /api/reload. So a `python -m musicweb.drain apply` on the
    NAS (DEPLOY.md 3a) landed tracks that browse and audio could see and text
    search and /api/similar could not, and a publish that renamed a new
    music.db into place was served entirely from the unlinked old inode -- both
    until someone POSTed a route no runbook mentioned. Rate-limited, and every
    failure to stat is "not stale" (the file is mid-swap; the next check gets
    it).
    """
    global _last_stale_check
    now = time.monotonic()
    with _index_lock:
        if now - _last_stale_check < STALE_CHECK_SECONDS:
            return False
        _last_stale_check = now
    state = db.file_state()
    return state is not None and idx.built_from != (db.generation(), state)


def index():
    """Shared search index. Holds numpy matrices, not a DB connection, so it is
    safe across threads; only its construction needs guarding.

    Rebuilt in place when the database it was built from has been changed by
    another process (music-2). db.con() inside refresh() is what reopens a
    REPLACED file, so the two halves of a publish -- new inode, new rows -- are
    both picked up by this one call.
    """
    global _index
    with _index_lock:
        if _index is None:
            _index = Index(db.con())
            return _index
        current = _index
    if _looks_stale(current):
        return refresh(db.con())
    return current


def refresh(con):
    """Pick up a changed library: build a new Index, then swap it in. -> it.

    The build happens OUTSIDE the lock and the swap is a single rebind, so a
    request holding the old index keeps a consistent one for its whole life and
    the next request gets the new one whole (MUSIC-10, 2026-08-11). It swaps
    only the DB-derived matrices: the models are module-level and survive it
    (MUSIC-8, 2026-08-14).
    """
    global _index
    fresh = Index(con)
    with _index_lock:
        _index = fresh
    return fresh
