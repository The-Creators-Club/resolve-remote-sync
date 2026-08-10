"""Sanity-check tag quality against filenames that state their own content.

Not a benchmark -- the library has no ground-truth labels. But a track called
"Traditional Music of Japan" should come back 'east asian', and if it does not,
the vocabulary needs work. Each case asserts that an expected label appears in
the track's stored top-k for that category.
"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'web'))

from musicweb import config                       # noqa: E402

CASES = [
    # (filename fragment, category, one of these labels should be present)
    ('Traditional Music of Japan', 'genre', {'east asian', 'world folk', 'classical'}),
    ('Streets of saigon', 'genre', {'east asian', 'world folk'}),
    ('East Asian ambient', 'genre', {'east asian', 'ambient', 'world folk'}),
    ('Fright Night', 'mood', {'eerie', 'ominous', 'tense', 'dark'}),
    ('Riot in the Capital', 'mood', {'urgent', 'aggressive', 'tense', 'determined'}),
    ('Winter Rain', 'mood', {'peaceful', 'melancholy', 'contemplative', 'lonely'}),
    ('Empty Streets', 'mood', {'lonely', 'melancholy', 'contemplative', 'mysterious'}),
    ('Digital Future', 'genre', {'electronic', 'synthwave', 'ambient'}),
    ('Neon City', 'genre', {'electronic', 'synthwave'}),
    ('Ancient Discoveries', 'mood', {'mysterious', 'grand', 'contemplative', 'determined'}),
    ('Mysterious Forest', 'mood', {'mysterious', 'eerie', 'contemplative', 'peaceful'}),
    ('Tears in Rain', 'mood', {'melancholy', 'contemplative', 'lonely', 'nostalgic'}),
    ('Under Canopies', 'genre', {'ambient', 'post-rock', 'folk acoustic', 'orchestral'}),
    ('String Duets', 'instrument', {'strings', 'solo cello'}),
    ('Solo Piano', 'instrument', {'piano'}),
]


def main():
    con = sqlite3.connect(config.DB_PATH)
    con.row_factory = sqlite3.Row
    passed = failed = skipped = 0

    for frag, cat, expect in CASES:
        row = con.execute(
            'SELECT id, filename FROM tracks WHERE filename LIKE ? LIMIT 1',
            (f'%{frag}%',)).fetchone()
        if not row:
            print(f'  --  no track matching "{frag}"')
            skipped += 1
            continue
        labels = [r['label'] for r in con.execute(
            'SELECT label FROM tags WHERE track_id=? AND category=? ORDER BY rank',
            (row['id'], cat))]
        hit = expect & set(labels)
        mark = 'ok  ' if hit else 'MISS'
        if hit:
            passed += 1
        else:
            failed += 1
        print(f'  {mark} {row["filename"][:44]:46s} {cat:10s} -> {", ".join(labels)}')

    total = passed + failed
    print(f'\n{passed}/{total} plausible ({skipped} skipped, no matching file)')


if __name__ == '__main__':
    main()
