"""The query-time half of the source-bias removal.

Finding the axes is index-time work and lives in
music/indexer/music_index/debias.py; this is only the projection, which has to
behave identically whether it is handed a document matrix or a single query
vector -- "debiasing documents and debiasing the query score identically, as
they must for an orthogonal projector".
"""
import numpy as np

from musicweb import projection


def _axes(k, d, seed=0):
    rng = np.random.default_rng(seed)
    q, _ = np.linalg.qr(rng.normal(size=(d, k)))
    return q.T.astype(np.float32)


def test_no_axes_is_a_no_op():
    v = np.eye(3, dtype=np.float32)
    assert projection.apply(v, np.zeros((0, 0), dtype=np.float32)) is v
    assert projection.apply(v, None) is v


def test_projection_erases_the_axes():
    dirs = _axes(2, 16)
    rng = np.random.default_rng(1)
    v = projection.l2norm(rng.normal(size=(20, 16)))
    out = projection.apply(v, dirs)
    assert np.abs(out @ dirs.T).max() < 1e-5


def test_output_is_unit_norm_and_shape_preserving():
    dirs = _axes(3, 16)
    rng = np.random.default_rng(2)
    v = projection.l2norm(rng.normal(size=(7, 16)))
    out = projection.apply(v, dirs)
    assert out.shape == v.shape
    assert np.allclose(np.linalg.norm(out, axis=1), 1.0, atol=1e-5)


def test_single_vector_matches_the_matrix_form():
    """A text query goes through one at a time, documents go through in bulk.
    Projecting only one side would put query and documents in different
    subspaces and silently distort every score, so the two must agree."""
    dirs = _axes(2, 16)
    rng = np.random.default_rng(3)
    v = projection.l2norm(rng.normal(size=16))
    one = projection.apply(v, dirs)
    many = projection.apply(v.reshape(1, -1), dirs)[0]
    assert one.shape == (16,)
    assert np.allclose(one, many, atol=1e-6)


def test_projector_is_idempotent():
    dirs = _axes(2, 16)
    rng = np.random.default_rng(4)
    v = projection.l2norm(rng.normal(size=(5, 16)))
    once = projection.apply(v, dirs)
    assert np.allclose(once, projection.apply(once, dirs), atol=1e-6)


def test_l2norm_survives_a_zero_vector():
    assert np.all(np.isfinite(projection.l2norm(np.zeros(4, dtype=np.float32))))
