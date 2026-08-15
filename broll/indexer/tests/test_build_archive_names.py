"""A clip's archive filename must never move once it has one.

The path is stored on the row, served by the web app and imported into editors'
timelines. dedupe() used to guarantee stability only by walking `videos` in id
order and resolving collisions against THIS run's claims — which holds while the
eligible set grows at the tail, and it does not: a 'discovered' or 'error' row
re-run to 'indexed', or a Downloads row that finally gets a category (the BROLL-7
carve-out), joins at its own LOW id. It then took the base name, every later
colliding clip shifted by one, write_paths rewrote their archive_path, and the
copy loop wrote the newcomer's bytes over a file another row already pointed at
(BROLL-IDX-5, 2026-08-14). 208 destinations on the live DB collide on
(folder, stem), and 61 stored paths already end in _2.._9.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from build_archive import (  # noqa: E402
    claim_key,
    claim_name,
    dest_rel,
    published_names,
)

FOLDER = "Downloads/society/government-politics"
TITLE = "How dictatorship built Taiwan's democracy"


def _video(vid: int, rel_path: str, category: str | None = "society/government-politics"):
    return {"id": vid, "share": "downloads", "rel_path": rel_path, "category": category,
            "status": "indexed"}


def test_two_new_clips_still_resolve_to_name_and_name_2():
    taken: set[str] = set()
    assert claim_name(FOLDER, TITLE, taken) == TITLE
    assert claim_name(FOLDER, TITLE, taken) == f"{TITLE}_2"
    assert claim_name(FOLDER, TITLE, taken) == f"{TITLE}_3"


def test_a_clip_that_already_has_a_name_keeps_it():
    """Its own claim, seeded from the DB, must not push it to _2."""
    published = (FOLDER, f"{TITLE}_2")
    taken = {claim_key(*published)}

    assert claim_name(FOLDER, TITLE, taken, published=published) == f"{TITLE}_2"


def test_a_newcomer_at_a_lower_id_cannot_take_a_published_clips_name():
    """The destructive case: clip 2050 retried out of 'error' walks first and,
    unclaimed, would take the base name that clip 3120 was shipped under —
    overwriting footage already cut into a timeline."""
    taken = {claim_key(FOLDER, TITLE), claim_key(FOLDER, f"{TITLE}_2")}  # 3120 and 9840

    newcomer = claim_name(FOLDER, TITLE, taken)

    assert newcomer == f"{TITLE}_3"


def test_the_top_slot_and_its_preview_share_one_name():
    """Keying claims on the whole path let them diverge whenever the extensions
    differed: `<folder>/name.mov` free while `<folder>/Proxy/name.mp4` was taken,
    so the original still landed on another clip's file."""
    v = _video(9840, "downloads/clip.mp4")
    taken: set[str] = {claim_key(FOLDER, TITLE)}

    name = claim_name(FOLDER, TITLE, taken)

    assert dest_rel(v, set(), ".mov", as_preview=False, stem=name) == \
        f"{FOLDER}/{TITLE}_2.mov"
    assert dest_rel(v, set(), ".mp4", as_preview=True, stem=name) == \
        f"{FOLDER}/Proxy/{TITLE}_2.mp4"


def test_dest_rel_without_a_stem_is_unchanged():
    v = _video(1, "downloads/some clip.mp4")
    assert dest_rel(v, set(), ".mp4", as_preview=True) == \
        f"{FOLDER}/Proxy/some clip.mp4"


def _db(tmp_path, rows) -> str:
    path = tmp_path / "b.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE videos (id INTEGER PRIMARY KEY, archive_path TEXT)")
    conn.executemany("INSERT INTO videos (id, archive_path) VALUES (?, ?)", rows)
    conn.commit()
    conn.close()
    return str(path)


def test_published_names_reads_the_folder_and_stem_off_stored_paths(tmp_path):
    db = _db(tmp_path, [
        (3120, f"{FOLDER}/Proxy/{TITLE}.mp4"),
        (9840, f"{FOLDER}/Proxy/{TITLE}_2.mp4"),
        (77, "Creators_Club/mofa/Day 1/A cam/Proxy/A001C002.mov"),
        (78, None),
        (79, ""),
    ])

    names = published_names(db)

    assert names[3120] == (FOLDER, TITLE)
    assert names[9840] == (FOLDER, f"{TITLE}_2")
    assert names[77] == ("Creators_Club/mofa/Day 1/A cam", "A001C002")
    assert 78 not in names and 79 not in names, "a row with no path claims nothing"


def test_the_whole_shape_a_second_build_must_reproduce(tmp_path):
    """End to end over the finding's own scenario: 3120 shipped as the base name
    and 9840 as _2; 2050 arrives from 'error' at a lower id. Both published
    clips must come out of the second build exactly where they went in."""
    db = _db(tmp_path, [
        (3120, f"{FOLDER}/Proxy/{TITLE}.mp4"),
        (9840, f"{FOLDER}/Proxy/{TITLE}_2.mp4"),
    ])
    published = published_names(db)
    taken = {claim_key(folder, stem) for folder, stem in published.values()}

    names = {
        vid: claim_name(FOLDER, TITLE, taken, published=published.get(vid))
        for vid in (2050, 3120, 9840)  # id order, exactly as main() walks them
    }

    assert names[3120] == TITLE
    assert names[9840] == f"{TITLE}_2"
    assert names[2050] == f"{TITLE}_3", "the newcomer takes the free name, not someone's"
    assert len(set(names.values())) == 3
