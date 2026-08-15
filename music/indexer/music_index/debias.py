"""Remove the 'which catalogue did this come from' signal from the embedding.

The problem, measured on this library: similarity was pulling far too many
tracks from the same source. Filenames are never fed to CLAP -- it only sees
decoded audio -- so this was not name matching. Two real causes:

  * every catalogue has a house sound and a mastering chain, and
  * source correlates hard with CODEC here (corr(is_ES, is_lossless) = +0.48;
    117 of 176 .wav files are Epidemic Sound, and none of the 89 .aac, 31
    .flac or 7 .ogg are). Lossy encoders lowpass the signal and CLAP sees that
    rolloff in the mel spectrogram.

Fix: find the axis that separates each source group from the rest, and project
those few axes out of every embedding. Measured on 376 tracks, erasing 4 axes
out of 512:

    ES-seed -> ES neighbours   53.7% -> 40.5%   (base rate 36%)
    lossless -> lossless       64.9% -> 56.7%   (base rate 55%)
    neighbour tag agreement    0.445 -> 0.419   (random pairs = 0.167)

So the source and codec bias is essentially gone while musical coherence is
retained at ~2.5x chance.

Rejected alternatives, all measured: whitening (hurt tag agreement to 0.38 and
barely moved the bias), MMR diversification (no effect -- diversifying inside
an already-monoculture neighbourhood still returns it), similarity over the tag
vector (49.6%; the tags inherit the same bias because they come from the same
embedding), and lowpassing all audio to a common bandwidth (would discard
genuine brightness, which is musically meaningful).

Note the grouping reads the SHAPE of a filename, never its words, and only at
index time to cancel a bias -- names play no part in ranking.

INDEX TIME ONLY. Finding the axes needs the whole library's embedding matrix
and its filenames, so it happens here, on the base rig, on every retag; the
result is stored in the `debias` table. Applying them to a vector is three
lines of numpy and happens per query, in `musicweb/projection.py`. The
computation is deliberately not duplicated into the web app.
"""
import os
import re

import numpy as np

MIN_GROUP = 8


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
