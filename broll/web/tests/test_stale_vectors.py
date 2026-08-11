"""Two ways a re-index left semantic search reading vectors that no longer mean
anything.

BROLL-13: `embeddings` cascades on video_id, and its source_id points at
segment rows with no foreign key at all. Re-ingesting a video replaced its
segments and orphaned their vectors, which kept scoring, resolved to nothing,
and spent the SEMANTIC_ONLY_MAX_VIDEOS budget -- so the clip's real content was
unreachable until stage_embed ran again.

BROLL-17: the matrix and vocabulary caches were keyed on a row COUNT, which a
re-index producing the same number of rows does not move. The cached vectors
then outlive the rows they were built from.
"""
from __future__ import annotations

import pytest

from app import fuzzy, semantic
from tests.factories import (
    insert_embedding,
    insert_segment,
    insert_transcript_segment,
    insert_video,
)


def _embeddings(conn, video_id):
    return {
        (r["source"], r["source_id"])
        for r in conn.execute(
            "SELECT source, source_id FROM embeddings WHERE video_id = ?", (video_id,)
        ).fetchall()
    }


def _index_payload(video_id, description):
    return {
        "video_id": video_id,
        "themes": [],
        "quality_flags": [],
        "category_hint": None,
        "segments": [{"t_start": 0.0, "t_end": 5.0, "description": description,
                      "objects": [], "setting": "", "motion": ""}],
    }


# ---------------------------------------------------------------------------
# BROLL-13
# ---------------------------------------------------------------------------

def test_re_ingesting_a_video_drops_its_segment_embeddings(client, conn):
    """Another video's segment is seeded ABOVE this one so the replacement
    cannot land back on the same rowid -- otherwise the orphan would be
    invisible by coincidence rather than absent by design (and that coincidence
    is the ordinary shape in an archive of tens of thousands of rows)."""
    vid = insert_video(conn, share="broll", rel_path="a.mov")
    seg = insert_segment(conn, vid, description="a harbour at dawn")
    insert_embedding(conn, source="segment", source_id=seg, video_id=vid, vec=[1.0, 0.0])
    other = insert_video(conn, share="broll", rel_path="b.mov")
    insert_segment(conn, other, description="another clip")

    r = client.post("/api/ingest/index", json=_index_payload(vid, "a city street"))
    assert r.status_code == 200

    live = {s["id"] for s in conn.execute(
        "SELECT id FROM segments WHERE video_id = ?", (vid,)).fetchall()}
    assert seg not in live  # atomic replace, as before
    assert _embeddings(conn, vid) == set()


def test_transcript_embeddings_are_left_alone(client, conn):
    """This endpoint owns segments, themes and flags. transcript_segments is
    written by a different pass and its vectors are still valid."""
    vid = insert_video(conn, share="broll", rel_path="a.mov")
    cue = insert_transcript_segment(conn, vid, text="he says something")
    insert_embedding(conn, source="transcript", source_id=cue, video_id=vid, vec=[0.0, 1.0])

    client.post("/api/ingest/index", json=_index_payload(vid, "a city street"))

    assert _embeddings(conn, vid) == {("transcript", cue)}


def test_another_videos_embeddings_are_untouched(client, conn):
    vid = insert_video(conn, share="broll", rel_path="a.mov")
    other = insert_video(conn, share="broll", rel_path="b.mov")
    other_seg = insert_segment(conn, other, description="a different clip")
    insert_embedding(conn, source="segment", source_id=other_seg, video_id=other,
                     vec=[1.0, 0.0])

    client.post("/api/ingest/index", json=_index_payload(vid, "a city street"))

    assert _embeddings(conn, other) == {("segment", other_seg)}


# ---------------------------------------------------------------------------
# BROLL-17
#
# The archive re-indexes one clip at a time out of tens of thousands of rows, so
# its replacement rows take ids above everything already there -- which is what
# the high-water mark in the cache key sees. It does NOT see a replacement that
# lands on the very same ids (possible only when the replaced rows were the
# highest in the table and exactly as many came back); nothing cheap does, and
# the staleness there ends at the next real write. Both are pinned below so the
# limit is a recorded fact rather than a surprise.
# ---------------------------------------------------------------------------

@pytest.mark.skipif(semantic.np is None, reason="numpy is not installed")
def test_the_matrix_cache_notices_a_same_size_re_embed(conn):
    """One row out, one row in, count unchanged: the cache used to serve the old
    vector until an unrelated write happened to move the count."""
    search = semantic.get_semantic_search()
    vid = insert_video(conn, share="broll", rel_path="a.mov")
    keeper = insert_segment(conn, vid, description="kept")
    insert_embedding(conn, source="segment", source_id=keeper, video_id=vid,
                     vec=[1.0, 0.0])
    stale = insert_segment(conn, vid, description="replaced")
    insert_embedding(conn, source="segment", source_id=stale, video_id=vid,
                     vec=[0.0, 1.0])

    first = search._ensure_index(conn)
    assert first is not None and len(first.rows) == 2

    conn.execute("DELETE FROM embeddings WHERE source_id = ?", (keeper,))
    conn.commit()
    fresh = insert_segment(conn, vid, description="fresh")
    insert_embedding(conn, source="segment", source_id=fresh, video_id=vid,
                     vec=[0.7, 0.7])

    second = search._ensure_index(conn)
    assert {r[1] for r in second.rows} == {stale, fresh}


def test_the_vocabulary_cache_notices_a_same_size_re_index(conn):
    """Same story for the typo-correction vocabulary: it kept steering queries
    towards words that had been deleted from the corpus."""
    cache = fuzzy.get_vocabulary_cache()
    vid = insert_video(conn, share="broll", rel_path="a.mov")
    stale = insert_segment(conn, vid, description="excavator")
    insert_segment(conn, vid, description="bulldozer")

    assert "excavator" in cache.get(conn)

    conn.execute("DELETE FROM segments WHERE id = ?", (stale,))
    conn.commit()
    insert_segment(conn, vid, description="helicopter")

    vocab = cache.get(conn)
    assert "helicopter" in vocab
    assert "excavator" not in vocab


def test_an_unchanged_corpus_is_not_rebuilt(conn):
    """The cache is still a cache: rebuilding the vocabulary (or the matrix) on
    every request is what the key exists to avoid."""
    cache = fuzzy.get_vocabulary_cache()
    vid = insert_video(conn, share="broll", rel_path="a.mov")
    insert_segment(conn, vid, description="bulldozer")

    first = cache.get(conn)
    assert cache.get(conn) is first  # same list object: no rebuild
