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

WHERE IT RUNS (updated 2026-08-18, docs/MUSIC_INGEST_PLAN.md step 2). Finding
the axes needs the whole library's embedding matrix and its filenames, so it
happens wherever a track is ADDED -- which used to mean the base rig alone and
now also means the NAS container, because dashboard music ingest writes a track
row there. The code therefore lives in `musicweb/rescore.py`, the tree both
halves share, and this module is the indexer's name for it. Applying the axes
to a vector is still three lines of numpy per query in `musicweb/projection.py`
and is still not duplicated.
"""
from musicweb.rescore import (  # noqa: F401
    MIN_GROUP, compute_directions, source_group,
)
