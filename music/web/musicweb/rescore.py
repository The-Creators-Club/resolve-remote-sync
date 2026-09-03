"""Tags, axes and the source-bias directions -- computed here, not only on the GPU.

2026-08-18, docs/MUSIC_INGEST_PLAN.md step 2. Until now every one of these
numbers was produced on the base rig by `index_music.retag` and reached the
live index one of two ways: the whole `music.db` was shipped, or a drain bundle
carried the library-wide rows and `drain.apply_bundle` copied them in. Both of
those still work and neither changes.

What changed is that a THIRD producer exists. Dashboard music ingest has the
editor's own machine embed a dropped track with the exported CLAP **audio**
tower (`music/indexer/export_audio_encoder.py`), and the container turns that
embedding into tags itself -- because tagging needs only the **text** tower,
which this process already loads for every search query, and because
percentiles are library-relative and only the machine holding the whole library
can compute them.

So this module is the one definition of that computation, and it has three
callers:

  * `index_music.retag` on the base rig (through a `Clap`, whose `embed_text`
    is the same contract as the ONNX encoder's -- one interface, two backends);
  * `drain.apply_bundle`, which does not COMPUTE anything: a bundle already
    carries the base rig's rows, and `apply_bundle_rows` below is that copy,
    moved here unchanged so the two paths sit side by side;
  * the fleet ingest `result` route, via `apply_for_track`.

**Every score in this database is relative to the library it was computed
against.** `score_all` z-scores each label down the column and takes
percentiles across every track; `compute_directions` needs the whole embedding
matrix. That is why one new track re-scores all of them, and why there is no
"just tag this one" entry point -- there is no such thing.
"""
import os
import re
import threading
import time
from datetime import datetime, timezone

import numpy as np

from musicweb import db, vocab
from musicweb.projection import l2norm

# Below this many members a source group is noise, not a catalogue (the
# constant `music_index.debias` carried).
MIN_GROUP = 8


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


# ------------------------------------------------------------- label space

_label_space = None
_label_space_key = None
_label_space_lock = threading.Lock()


def build_label_space(encoder):
    """Embed every caption once; a label's vector is the mean of its captions.

    `encoder` is anything with `embed_text(list[str]) -> (N, D) unit vectors`:
    the container's `OnnxTextEncoder`, or the base rig's full `Clap`.
    """
    cats = {}
    for cat, labels in vocab.CATEGORIES.items():
        names, vecs = [], []
        for label, phrases in labels.items():
            e = encoder.embed_text(phrases)
            names.append(label)
            vecs.append(l2norm(e.mean(axis=0)))
        cats[cat] = (names, np.stack(vecs).astype(np.float32))

    axes = {}
    for axis, poles in vocab.AXES.items():
        hi = l2norm(encoder.embed_text(poles['high']).mean(axis=0))
        lo = l2norm(encoder.embed_text(poles['low']).mean(axis=0))
        axes[axis] = (hi.astype(np.float32), lo.astype(np.float32))
    return cats, axes


def label_space(encoder):
    """`build_label_space`, cached per (encoder, vocabulary).

    240 captions through the ONNX text tower is a second or two, and dashboard
    ingest asks for this once per track in a drop. The key includes
    `vocab.vocab_hash()` so editing the vocabulary in a live process (which is
    exactly what `eval.py --sweep` does to CALIBRATION, and what a hot reload
    would do to the labels) cannot serve a stale space; it includes the encoder
    identity because a test's fake and the real one are different answers.

    Locked, for `search.shared_encoder`'s reason: two cold ingest calls landing
    together on FastAPI's threadpool would otherwise both build it.
    """
    global _label_space, _label_space_key
    key = (id(encoder), vocab.vocab_hash())
    with _label_space_lock:
        if _label_space_key != key:
            _label_space = build_label_space(encoder)
            _label_space_key = key
        return _label_space


def _encoder_or_shared(encoder):
    """The caller's embedder, or the process-wide query one.

    Imported inside the function: `musicweb.search` builds matrices at import
    of an Index and is a heavier neighbour than this module wants at import
    time, and nothing here needs it when a caller passes its own.
    """
    if encoder is not None:
        return encoder
    from musicweb.search import shared_encoder
    return shared_encoder()


# ------------------------------------------------------------------ scoring

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
        pct = np.stack([db.percentile_ranks(z[:, j]) for j in range(z.shape[1])],
                       axis=1)
        tags[cat] = {'labels': names, 'score': probs, 'pct': pct}

    axvals = {}
    for axis, (hi, lo) in axes.items():
        raw = track_matrix @ hi - track_matrix @ lo
        axvals[axis] = {'raw': raw, 'pct': db.percentile_ranks(raw)}
    return tags, axvals


def write_scores(con, track_ids, tags, axvals):
    """Replace every tag and axis row. ONE transaction, always.

    MUSIC-1, 2026-09-04. This used to be a bare `DELETE FROM tags` / `DELETE
    FROM axes`, thousands of tuples built in Python, an executemany and a
    commit at the end -- and sqlite3 auto-begins on the first DML, so from the
    deletes until that commit there is an OPEN write transaction in which the
    library has no tags and no axes. A failure anywhere in between (SQLITE_FULL
    on a container whose data root filled, a MemoryError building ~9,000
    tuples) left that transaction open on the thread's CACHED connection
    (`db.con()`), holding the writer lock -- and the next write on that same
    threadpool thread, another `result` or an `/api/peaks` INSERT, committed
    the wipe. Empty facets, permanently, with the only evidence a log line.

    `with con:` is the whole fix: it commits on the way out and ROLLS BACK on
    an exception, so the worst case is "the tags are the ones from before".
    """
    with con:
        _write_scores_rows(con, track_ids, tags, axvals)


def _write_scores_rows(con, track_ids, tags, axvals):
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
    # No commit here: the caller's `with con:` owns the transaction, and this
    # function exists only so that the delete and the reinsert cannot be split.


# --------------------------------------------------------- source-bias axes
# Moved from `music_index/debias.py`, whose docstring has the measurements and
# the rejected alternatives; read it for WHY these axes exist. Only the "index
# time only, deliberately not duplicated into the web app" line has stopped
# being true (2026-08-18): the web app is now one of the places a track is
# added, so it is one of the places the axes have to be recomputed. Applying
# them to a vector is still `musicweb/projection.py`, per query, and still not
# duplicated.


def source_group(filename):
    """Which catalogue a file appears to come from, by naming convention."""
    stem = os.path.splitext(os.path.basename(filename))[0]
    if stem.upper().startswith('ES_'):
        return 'epidemic'
    if re.match(r'^[0-9a-f]{8}-[0-9a-f]{4}-', stem, re.I):
        return 'uuid'
    if re.match(r'^[0-9A-Z]{20,}$', stem):
        return 'ulid'
    if re.match(r'^\d{3,}([_\-]\d+)*$', stem) or re.match(r'^\d{4,}_\d', stem):
        return 'numeric-id'
    return 'other'


def compute_directions(mat, filenames, min_group=MIN_GROUP):
    """One orthogonal one-vs-rest axis per source group. -> (k, D) float32."""
    if mat is None or mat.size == 0:
        return np.zeros((0, 0), dtype=np.float32)
    groups = {}
    for i, name in enumerate(filenames):
        groups.setdefault(source_group(name), []).append(i)

    dirs = []
    for g in sorted(groups):
        members = groups[g]
        # A boolean mask, not `[i for i in range(n) if i not in set(members)]`
        # (MUSIC-11, 2026-08-14): that rebuilt the set on every one of the n
        # iterations, i.e. O(n * |members|) per group. Invisible at 376 tracks
        # and ~50M redundant insertions at 10,000, inside every --retag, which
        # is the cheap tuning path the whole workflow leans on.
        mask = np.zeros(mat.shape[0], dtype=bool)
        mask[members] = True
        if len(members) < min_group or mask.all():
            continue
        v = mat[mask].mean(axis=0) - mat[~mask].mean(axis=0)
        for u in dirs:                       # Gram-Schmidt
            v = v - np.dot(v, u) * u
        n = np.linalg.norm(v)
        if n > 1e-6:
            dirs.append(v / n)
    if not dirs:
        return np.zeros((0, mat.shape[1]), dtype=np.float32)
    return np.stack(dirs).astype(np.float32)


# ------------------------------------------------------------- the whole job

# `meta` key: set when a rescore failed or was deferred, cleared when one
# lands. /api/stats returns it so the header can say the tags are behind
# instead of the editor seeing an untagged track and concluding the drop
# failed (MUSIC-1 / MUSIC-5, 2026-09-04).
SCORES_STALE = 'scores_stale'

# How rarely a fleet-ingest result may trigger a full library rescore
# (MUSIC-5). Every result used to do one: at 397 tracks that is a ~2.5 MB
# matrix read, a label-space scoring pass and ~8,700 row writes, so a 200-track
# album drop cost ~1.7M row writes -- serialised through the single-worker
# container's one SQLite writer, which is also serving /api/report for the
# whole fleet. The VALUE of a rescore per track is real (a percentile is a rank
# among the others); its FREQUENCY is not. Coalesced here and forced once at
# `release`, so a finished batch is fully tagged either way.
RESCORE_MIN_SECONDS = float(os.environ.get('MUSIC_RESCORE_MIN_SECONDS', '60'))

_rescore_lock = threading.Lock()
_last_rescore = None            # time.monotonic() of the last one, None = never


def note_rescored():
    global _last_rescore
    with _rescore_lock:
        _last_rescore = time.monotonic()


def rescore_due(now=None):
    """Has RESCORE_MIN_SECONDS passed since the last one?

    True the first time in a process, always: a container that has just started
    knows nothing about what the library's scores look like, and the very first
    drop after a restart is exactly the one an editor is watching.
    """
    now = time.monotonic() if now is None else now
    with _rescore_lock:
        return _last_rescore is None or (now - _last_rescore) >= RESCORE_MIN_SECONDS


def mark_scores_stale(con, when=None):
    """Record that the tags are behind the tracks. Never raises.

    Best-effort by design: it is called on the failure path, where the reason
    the rescore failed (a full disk, a locked database) is just as likely to
    stop this write. A marker that could turn one failure into two would be
    worse than no marker.
    """
    try:
        with con:
            db.set_meta(con, SCORES_STALE, when or _now())
    except Exception:                                           # noqa: BLE001
        pass


def scores_stale(con):
    """The ISO time the tags fell behind, or None."""
    return db.get_meta(con, SCORES_STALE)


def rescore_library(con, encoder=None):
    """Recompute the source-bias axes, the tags and the axes. -> a summary.

    Statement for statement what `index_music.retag` did (and now calls),
    because a library scored two ways is a library whose facets disagree with
    its search. Seconds on 376 tracks: nothing here decodes audio, it all comes
    off the stored embeddings.

    Any failure rolls back and leaves `scores_stale` behind (MUSIC-1,
    2026-09-04): the connection is a POOLED one and must never be handed back
    inside an open write transaction, and a rescore that did not happen has to
    be visible to somebody other than the log.
    """
    ids, mat = db.load_matrix(con)
    if not ids:
        return {'tracks': 0, 'labels': 0, 'axes': 0, 'debias': 0}

    try:
        # The source-bias axes depend on the library's composition, so they are
        # refreshed whenever it changes -- adding one track to a small library
        # can tip a group over MIN_GROUP.
        names = [r['filename'] for r in con.execute(
            'SELECT filename FROM tracks WHERE embedding IS NOT NULL ORDER BY id')]
        dirs = compute_directions(mat, names)
        db.save_debias(con, dirs)

        encoder = _encoder_or_shared(encoder)
        cats, axes = label_space(encoder)
        tags, axvals = score_all(mat, cats, axes)
        write_scores(con, ids, tags, axvals)
        with con:
            db.set_meta(con, 'vocab_hash', vocab.vocab_hash())
            db.set_meta(con, 'tagged_at', _now())
            con.execute('DELETE FROM meta WHERE key=?', (SCORES_STALE,))
    except BaseException:
        # Nothing above may leave a half-applied score set on a shared
        # connection. rollback() on a connection with no transaction open is a
        # no-op, so this is safe wherever the failure happened.
        con.rollback()
        mark_scores_stale(con)
        raise
    note_rescored()
    return {'tracks': len(ids),
            'labels': sum(len(v) for v in vocab.CATEGORIES.values()),
            'axes': len(vocab.AXES), 'debias': int(dirs.shape[0])}


def apply_for_track(con, track_id, encoder=None, force=False):
    """Score a newly ingested track -- by re-scoring the library around it.

    The fleet `result` route's call. There is no cheaper honest version of the
    computation: a track's `pct` is its rank among the others and its `score`
    is a softmax over labels z-scored down the library's own column, so the new
    row cannot be computed without touching every other row's numbers.

    There IS a cheaper frequency (MUSIC-5, 2026-09-04). Inside
    RESCORE_MIN_SECONDS of the last one this returns `deferred` instead,
    marking the library stale; `release` passes force=True, so a batch is
    always fully tagged by the time it finishes, and the editor is told the
    tags are catching up rather than shown a track with none.

    Returns the summary plus this track's own tags/axes, which the route hands
    back so the SPA can show what the drop was labelled without re-querying.
    """
    if not force and not rescore_due():
        mark_scores_stale(con)
        return {'deferred': True, 'scores_stale': scores_stale(con),
                'track_id': track_id, 'tags': [], 'axes_values': []}
    summary = rescore_library(con, encoder)
    summary['track_id'] = track_id
    summary['tags'] = [dict(r) for r in con.execute(
        'SELECT category, label, score, pct, rank FROM tags WHERE track_id = ? '
        'ORDER BY category, rank', (track_id,))]
    summary['axes_values'] = [dict(r) for r in con.execute(
        'SELECT axis, raw, pct FROM axes WHERE track_id = ? ORDER BY axis',
        (track_id,))]
    return summary


# --------------------------------------------------------- the bundle's copy

def apply_bundle_rows(con, bundle):
    """Library-wide tags/axes/debias FROM A DRAIN BUNDLE. -> tracks re-scored.

    Moved out of `drain._apply_rescore` unchanged (2026-08-18) so that the two
    ways this database gets its scores -- computed here, or carried in from the
    base rig -- are one file apart instead of one repository apart. It computes
    nothing: a bundle already holds the rows `rescore_library` would have
    produced, on the machine that had the GPU.

    Silently skips rel_paths this index does not have. That is not a failure: a
    bundle is drained from a copy of this index, and anything the copy held
    that is gone here was deleted deliberately (a prune, a rename) in the
    meantime.
    """
    ids = {r['rel_path']: r['id']
           for r in con.execute('SELECT id,rel_path FROM tracks')}
    touched = set()
    tags = {}
    for r in bundle.execute('SELECT rel_path,category,label,score,pct,rank '
                            'FROM bundle_tags'):
        tid = ids.get(r['rel_path'])
        if tid is None:
            continue
        tags.setdefault(tid, []).append((tid, r['category'], r['label'],
                                         r['score'], r['pct'], r['rank']))
    axes = {}
    for r in bundle.execute('SELECT rel_path,axis,raw,pct FROM bundle_axes'):
        tid = ids.get(r['rel_path'])
        if tid is None:
            continue
        axes.setdefault(tid, []).append((tid, r['axis'], r['raw'], r['pct']))

    for tid, rows in tags.items():
        con.execute('DELETE FROM tags WHERE track_id=?', (tid,))
        con.executemany('INSERT INTO tags(track_id,category,label,score,pct,rank) '
                        'VALUES(?,?,?,?,?,?)', rows)
        touched.add(tid)
    for tid, rows in axes.items():
        con.execute('DELETE FROM axes WHERE track_id=?', (tid,))
        con.executemany('INSERT INTO axes(track_id,axis,raw,pct) VALUES(?,?,?,?)',
                        rows)
        touched.add(tid)

    debias = bundle.execute('SELECT idx,vec FROM bundle_debias ORDER BY idx').fetchall()
    if debias:
        # All or nothing: the directions are an orthogonal set projected out of
        # every embedding together, so a half-replaced set is not a weaker
        # projection, it is a wrong one.
        con.execute('DELETE FROM debias')
        con.executemany('INSERT INTO debias(idx,vec) VALUES(?,?)',
                        [(r['idx'], r['vec']) for r in debias])
    return len(touched)
