"""Score track embeddings against the vocabulary.

The computation moved to `musicweb/rescore.py` on 2026-08-18
(docs/MUSIC_INGEST_PLAN.md step 2): the NAS container scores dashboard-ingested
tracks itself now, using the CLAP TEXT tower it already runs for queries, and
it has no `music_index` to import this from. One definition, in the tree both
halves share -- the same arrangement `db.py` and `schema.sql` have always had.

This module stays as the indexer's name for it, because `index_music.py` and
`eval/eval.py` call `tagging.build_label_space/score_all/write_scores` and
because the base rig passes a full `Clap` where the container passes the ONNX
text encoder: the two satisfy the same one-method contract (`embed_text`), and
that is the whole reason the split works.
"""
from musicweb.rescore import (  # noqa: F401
    build_label_space, score_all, write_scores,
)
