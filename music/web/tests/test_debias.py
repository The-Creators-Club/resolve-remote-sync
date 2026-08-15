"""The source-bias axes: pure numpy, so this venv can run it.

`music_index.debias` needs nothing but numpy -- it is the one index-time module
that does -- and it runs inside every `--retag`, which the tuning workflow
leans on as the cheap path. MUSIC-11 (2026-08-14) rewrote its inner loop, so
what is pinned here is that the axes it produces did not move.
"""
import numpy as np
import pytest

from musicweb import config

if not config.add_indexer_to_path():
    pytest.skip('no indexer checked out here', allow_module_level=True)

from music_index import debias                    # noqa: E402

DIM = 16


def _library(n_es=12, n_other=10, n_uuid=9, seed=3):
    """A matrix and the filenames that put each row in a source group.

    Three groups, not two: with only two, each one's one-vs-rest axis is the
    other's negated, so Gram-Schmidt correctly leaves a single axis.
    """
    rng = np.random.default_rng(seed)
    mat = rng.normal(size=(n_es + n_other + n_uuid, DIM)).astype(np.float32)
    mat /= np.linalg.norm(mat, axis=1, keepdims=True)
    names = ([f'ES_Cue {i}.wav' for i in range(n_es)]
             + [f'Human Name {i}.wav' for i in range(n_other)]
             + [f'0000000{i}-abcd-4000-8000-000000000000.wav'
                for i in range(n_uuid)])
    return mat, names


def _directions_the_old_way(mat, filenames, min_group=debias.MIN_GROUP):
    """compute_directions as it was written before MUSIC-11: an index list
    rebuilt from `set(members)` on every one of the n iterations."""
    groups = {}
    for i, name in enumerate(filenames):
        groups.setdefault(debias.source_group(name), []).append(i)
    dirs = []
    for g in sorted(groups):
        members = groups[g]
        others = [i for i in range(mat.shape[0]) if i not in set(members)]
        if len(members) < min_group or not others:
            continue
        v = mat[members].mean(axis=0) - mat[others].mean(axis=0)
        for u in dirs:
            v = v - np.dot(v, u) * u
        n = np.linalg.norm(v)
        if n > 1e-6:
            dirs.append(v / n)
    if not dirs:
        return np.zeros((0, mat.shape[1]), dtype=np.float32)
    return np.stack(dirs).astype(np.float32)


def test_the_mask_gives_exactly_the_axes_the_index_list_gave():
    """The whole point of the change: same numbers, one pass instead of n."""
    mat, names = _library()
    assert np.allclose(debias.compute_directions(mat, names),
                       _directions_the_old_way(mat, names), atol=1e-6)


def test_a_group_smaller_than_min_group_gets_no_axis():
    """Three ES files are a coincidence, not a catalogue."""
    mat, names = _library(n_es=3, n_other=20, n_uuid=0)
    assert debias.compute_directions(mat, names).shape[0] == 1   # 'other' only
    assert np.allclose(debias.compute_directions(mat, names),
                       _directions_the_old_way(mat, names), atol=1e-6)


def test_a_library_from_one_source_has_no_axis_to_erase():
    """Every row a member means there is no 'rest' to separate it from."""
    mat, _ = _library()
    names = [f'ES_Cue {i}.wav' for i in range(mat.shape[0])]
    assert debias.compute_directions(mat, names).shape[0] == 0


def test_the_axes_are_orthonormal():
    mat, names = _library()
    dirs = debias.compute_directions(mat, names)
    assert dirs.shape[0] >= 2
    gram = dirs @ dirs.T
    assert np.allclose(gram, np.eye(dirs.shape[0]), atol=1e-5)


def test_an_empty_library_is_not_a_crash():
    assert debias.compute_directions(np.zeros((0, 0), dtype=np.float32), []).size == 0
