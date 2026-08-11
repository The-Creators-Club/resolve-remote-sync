"""Query-time vector maths: L2 normalisation and the source-bias projection.

Only the *application* of the source-bias axes lives here. Finding them is an
index-time job and stays on the base rig in
`music/indexer/music_index/debias.py`, whose docstring carries the measured
reasoning (why the bias exists, what erasing it costs, what was rejected). The
axes themselves are read from the `debias` table, which the indexer refreshes
on every retag.

This module is deliberately free of torch/CLAP so the web app can start, search
by similarity and serve the UI on a host that has neither.
"""
import numpy as np


def l2norm(a):
    a = np.asarray(a, dtype=np.float32)
    n = np.linalg.norm(a, axis=-1, keepdims=True)
    return a / np.maximum(n, 1e-8)


def apply(vecs, dirs):
    """Project the source axes out and re-normalise.

    INDEX-SIDE AND SIMILARITY-ONLY: the only caller is `search.Index`, building
    the matrix /api/similar scores against. Text queries are NOT projected, and
    neither is the matrix text search scores against. That asymmetry is
    deliberate and measured (MUSIC-13, 2026-08-11 -- this docstring used to
    claim the opposite): erasing the source axes takes similarity from 53.7% to
    40.5% ES-seed->ES neighbours, but takes TEXT retrieval from 40% to 20%
    top-10, because those axes carry content text queries lean on and text sits
    on the far side of CLAP's modality gap. Applying this to queries "for
    symmetry" halves text search.
    """
    if dirs is None or dirs.size == 0 or vecs is None or vecs.size == 0:
        return vecs
    v = np.atleast_2d(np.asarray(vecs, dtype=np.float32))
    v = v - (v @ dirs.T) @ dirs
    v = v / np.maximum(np.linalg.norm(v, axis=1, keepdims=True), 1e-8)
    return v.reshape(np.shape(vecs)) if np.ndim(vecs) > 1 else v[0]
