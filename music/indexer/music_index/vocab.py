"""Moved to `musicweb/vocab.py` on 2026-08-18 (docs/MUSIC_INGEST_PLAN.md step 2).

Tagging stopped being a base-rig-only job: the container now scores an
embedding an editor's companion computed, using the CLAP text tower it already
runs for queries (`musicweb/rescore.py`), and it has no `music_index` to import
a vocabulary from. So the vocabulary lives in the tree both halves share --
the same reason `db.py` and `schema.sql` are over there.

`sys.modules[__name__] = _vocab` rather than a star-import, and it is
load-bearing: `eval/eval.py --sweep` re-scores the library at several
calibration strengths by ASSIGNING `vocab.CALIBRATION`, and the scorer reads
that attribute at call time. A star-import would make two module objects, the
sweep would mutate one and the scorer would go on reading the other -- which
is MUSIC-4's shape exactly (a sweep that silently wrote one alpha's scores
while reporting another's).
"""
import sys

from musicweb import vocab as _vocab

sys.modules[__name__] = _vocab
