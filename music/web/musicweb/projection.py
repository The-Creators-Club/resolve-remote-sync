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

    Applied to audio embeddings AND to text queries, so both live in the same
    subspace -- projecting only one side would silently distort every score.
    """
    if dirs is None or dirs.size == 0 or vecs is None or vecs.size == 0:
        return vecs
    v = np.atleast_2d(np.asarray(vecs, dtype=np.float32))
    v = v - (v @ dirs.T) @ dirs
    v = v / np.maximum(np.linalg.norm(v, axis=1, keepdims=True), 1e-8)
    return v.reshape(np.shape(vecs)) if np.ndim(vecs) > 1 else v[0]
