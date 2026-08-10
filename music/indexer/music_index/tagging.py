"""Score track embeddings against the vocabulary.

Kept separate from indexing because tagging is cheap and re-runnable: editing
vocab.py and calling `index_music.py --retag` re-scores the library from stored
embeddings without touching a single audio file.
"""
import numpy as np

from music_index import vocab
from music_index.clap_model import l2norm


def build_label_space(clap):
    """Embed every caption once; a label's vector is the mean of its captions."""
    cats = {}
    for cat, labels in vocab.CATEGORIES.items():
        names, vecs = [], []
        for label, phrases in labels.items():
            e = clap.embed_text(phrases)
            names.append(label)
            vecs.append(l2norm(e.mean(axis=0)))
        cats[cat] = (names, np.stack(vecs).astype(np.float32))

    axes = {}
    for axis, poles in vocab.AXES.items():
        hi = l2norm(clap.embed_text(poles['high']).mean(axis=0))
        lo = l2norm(clap.embed_text(poles['low']).mean(axis=0))
        axes[axis] = (hi.astype(np.float32), lo.astype(np.float32))
    return cats, axes


def _softmax(x, temp):
    z = (x - x.max(axis=-1, keepdims=True)) / max(temp, 1e-6)
    e = np.exp(z)
    return e / e.sum(axis=-1, keepdims=True)


def score_all(track_matrix, cats, axes):
    """track_matrix: (N, D) unit vectors.

    Returns
      tags: {category: {'labels': [...], 'score': (N,L), 'pct': (N,L)}}
      axvals: {axis: {'raw': (N,), 'pct': (N,)}}

    Percentiles are computed down each column (across the library) because raw
    CLAP similarities occupy a narrow, poorly-calibrated band -- their ordering
    is trustworthy, their absolute value is not.
    """
    from musicweb.db import percentile_ranks

    tags = {}
    for cat, (names, mat) in cats.items():
        sims = track_matrix @ mat.T                      # (N, L)

        # Per-label calibration down the columns. Some captions sit closer to
        # the centroid of "music in general" than others, so on raw similarity
        # those labels win for nearly every track -- "romantic" was landing on
        # horror cues. Z-scoring each label across the library asks instead
        # "is this track unusually X *for this library*", which is the question
        # an editor is actually asking.
        mu = sims.mean(axis=0, keepdims=True)
        sd = sims.std(axis=0, keepdims=True) + 1e-6
        alpha = getattr(vocab, 'CALIBRATION', 1.0)
        z = (sims - mu) / (sd ** alpha)

        probs = _softmax(z, vocab.TEMPERATURE)
        pct = np.stack([percentile_ranks(z[:, j]) for j in range(z.shape[1])], axis=1)
        tags[cat] = {'labels': names, 'score': probs, 'pct': pct}

    axvals = {}
    for axis, (hi, lo) in axes.items():
        raw = track_matrix @ hi - track_matrix @ lo
        axvals[axis] = {'raw': raw, 'pct': percentile_ranks(raw)}
    return tags, axvals


def write_scores(con, track_ids, tags, axvals):
    con.execute('DELETE FROM tags')
    con.execute('DELETE FROM axes')

    for cat, d in tags.items():
        k = vocab.TOP_K.get(cat, 3)
        labels, score, pct = d['labels'], d['score'], d['pct']
        rows = []
        for i, tid in enumerate(track_ids):
            order = np.argsort(-score[i])[:k]
            for rank, j in enumerate(order, start=1):
                rows.append((tid, cat, labels[j], float(score[i, j]),
                             float(pct[i, j]), rank))
        con.executemany(
            'INSERT OR REPLACE INTO tags(track_id,category,label,score,pct,rank) '
            'VALUES(?,?,?,?,?,?)', rows)

    rows = []
    for axis, d in axvals.items():
        for i, tid in enumerate(track_ids):
            rows.append((tid, axis, float(d['raw'][i]), float(d['pct'][i])))
    con.executemany('INSERT OR REPLACE INTO axes(track_id,axis,raw,pct) '
                    'VALUES(?,?,?,?)', rows)
    con.commit()
