"""Evaluate tagging and retrieval quality, and sweep the calibration setting.

Two things are measured, because they fail in different ways:

  bias      - how concentrated the rank-1 labels are across the library. If one
              mood is top for a third of all tracks, that label is winning on
              caption geometry rather than on the music.
  retrieval - for a handful of text queries, the rank of a track whose filename
              says it should match. This is the feature people actually use.

    python eval.py            # report current settings
    python eval.py --sweep    # compare calibration strengths
"""
import argparse
import collections
import sys
from pathlib import Path

import numpy as np

# eval/ sits beside both halves and needs both: the indexer for the vocabulary
# and the label space, the web tree for the storage layer and the query logic.
_MUSIC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_MUSIC / 'indexer'))

from music_index import tagging, vocab            # noqa: E402  (also puts web/ on sys.path)
from musicweb import db                           # noqa: E402

# (query, filename fragment that ought to rank highly)
RETRIEVAL = [
    ('eerie unsettling horror music', 'Fright Night'),
    ('traditional japanese music', 'Sakura'),
    ('retro neon synthwave', 'Neon City'),
    ('angry aggressive riot music', 'Riot in the Capital'),
    ('lonely empty city at night', 'Empty Streets'),
    ('gentle rain and quiet reflection', 'Winter Rain'),
    ('mysterious forest atmosphere', 'Mysterious Forest'),
    ('ancient historical discovery', 'Ancient Discoveries'),
    ('jazz with brass and drums', 'Under Canopies'),
    ('dark futuristic technology', 'Digital Future'),
]


def bias_report(con, top=6):
    print('  rank-1 label concentration (lower share = less caption bias)')
    worst = {}
    for cat in vocab.CATEGORIES:
        rows = con.execute(
            'SELECT label, COUNT(*) n FROM tags WHERE category=? AND rank=1 '
            'GROUP BY label ORDER BY n DESC', (cat,)).fetchall()
        total = sum(r['n'] for r in rows) or 1
        share = rows[0]['n'] / total if rows else 0
        worst[cat] = share
        head = ', '.join(f'{r["label"]} {r["n"]}' for r in rows[:top])
        print(f'    {cat:11s} top={share*100:4.1f}%  {head}')
    return sum(worst.values()) / len(worst)


def retrieval_report(index, con):
    ranks = []
    for query, frag in RETRIEVAL:
        row = con.execute('SELECT id FROM tracks WHERE filename LIKE ? LIMIT 1',
                          (f'%{frag}%',)).fetchone()
        if not row:
            continue
        hits = index.text_search(query, k=376)
        order = [h['id'] for h in hits]
        r = order.index(row['id']) + 1 if row['id'] in order else 999
        ranks.append(r)
        flag = 'ok  ' if r <= 10 else ('near' if r <= 30 else 'MISS')
        print(f'    {flag} #{r:<4d} {query[:38]:40s} -> {frag}')
    if not ranks:
        return 0, 0
    top10 = sum(1 for r in ranks if r <= 10) / len(ranks)
    mrr = float(np.mean([1 / r for r in ranks]))
    print(f'    top-10 hit rate {top10*100:.0f}%   MRR {mrr:.3f}   '
          f'median rank {int(np.median(ranks))}')
    return top10, mrr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sweep', action='store_true')
    args = ap.parse_args()

    con = db.connect()
    from musicweb.search import Index
    index = Index(con)

    if not args.sweep:
        print('\n=== tag bias ===')
        bias_report(con)
        print('\n=== retrieval ===')
        retrieval_report(index, con)
        print()
        return

    # Retrieval does not depend on calibration (it works off raw embeddings),
    # so the sweep only needs to re-score tags in memory.
    from music_index.clap_model import Clap
    clap = Clap()
    cats, axes = tagging.build_label_space(clap)
    ids, mat = db.load_matrix(con)

    print('\n=== calibration sweep ===')
    for alpha in (0.0, 0.25, 0.5, 0.75, 1.0):
        vocab.CALIBRATION = alpha
        tags, axvals = tagging.score_all(mat, cats, axes)
        tagging.write_scores(con, ids, tags, axvals)
        print(f'\n-- CALIBRATION = {alpha}')
        avg = bias_report(con, top=4)
        print(f'    mean top-label share across categories: {avg*100:.1f}%')

    print('\nRetrieval (independent of calibration):')
    retrieval_report(index, con)
    print()


if __name__ == '__main__':
    main()
