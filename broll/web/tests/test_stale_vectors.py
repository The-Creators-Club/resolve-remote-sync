"""Three ways a re-index left semantic search reading vectors that no longer mean
anything.

BROLL-13: `embeddings` cascades on video_id, and its source_id points at
segment rows with no foreign key at all. Re-ingesting a video replaced its
segments and orphaned their vectors, which kept scoring, resolved to nothing,
and spent the SEMANTIC_ONLY_MAX_VIDEOS budget -- so the clip's real content was
unreachable until stage_embed ran again.

BROLL-17: the matrix and vocabulary caches were keyed on a row COUNT, which a
re-index producing the same number of rows does not move. The cached vectors
then outlive the rows they were built from. Fixed by adding each table's
high-water mark to the key.

KNOWN_BUGS R2 (the BROLL-17 residual): that key is still blind to a replacement
whose rows were the highest in the table and came back in exactly the same
number -- SQLite hands out the same rowids, so count AND high-water mark are
unchanged while every vector is different. Closed by meta.search_generation
(migration 010), a counter the write paths bump in the same transaction as the
write. It is only as good as their discipline, so the bump is pinned per write
path here and in the indexer suite, and the data-derived key components stay.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app import fuzzy, semantic
from app.db import read_search_generation
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
# the high-water mark in the cache key sees. The replacement that lands on the
# very same ids (the replaced rows were the highest in the table and exactly as
# many came back) is invisible to it, and to the count beside it; that case is
# the R2 section further down.
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


# ---------------------------------------------------------------------------
# KNOWN_BUGS R2 -- the residual: same count, SAME rowids, different vectors
#
# One video whose rows are the only rows in the table is the smallest exact
# reproduction: the re-ingest deletes them and inserts the replacement inside
# one transaction, so SQLite reuses rowid 1, and the (count, MAX(rowid)) key is
# byte-for-byte what it was. Each test below asserts that precondition before
# asserting the result, so it cannot silently stop being the residual case (a
# stray extra row would make it the ordinary BROLL-17 case again and the test
# would pass for the wrong reason).
# ---------------------------------------------------------------------------

def _embedding_key_components(conn, model=semantic.DEFAULT_MODEL):
    """Exactly what SemanticSearch keyed on before the generation counter."""
    return tuple(
        conn.execute(
            "SELECT COUNT(*), COALESCE(MAX(rowid), 0) FROM embeddings WHERE model = ?",
            (model,),
        ).fetchone()
    )


def _vocabulary_key_components(conn):
    """Exactly what VocabularyCache keyed on before the generation counter."""
    return tuple(
        conn.execute(
            "SELECT (SELECT COUNT(*) FROM segments) "
            "+ (SELECT COUNT(*) FROM transcript_segments), "
            "COALESCE((SELECT MAX(id) FROM segments), 0), "
            "COALESCE((SELECT MAX(id) FROM transcript_segments), 0)"
        ).fetchone()
    )


@pytest.mark.skipif(semantic.np is None, reason="numpy is not installed")
def test_the_matrix_cache_notices_a_re_embed_onto_the_same_rowids(client, conn):
    """The residual, end to end: re-ingest, re-embed, and the served vector is
    the new one -- with the old cache key demonstrably unmoved."""
    search = semantic.get_semantic_search()
    vid = insert_video(conn, share="broll", rel_path="a.mov")
    seg = insert_segment(conn, vid, description="a harbour at dawn")
    insert_embedding(conn, source="segment", source_id=seg, video_id=vid, vec=[1.0, 0.0])

    before = _embedding_key_components(conn)
    first = search._ensure_index(conn)
    assert first is not None and first.matrix[0].tolist() == [1.0, 0.0]

    r = client.post("/api/ingest/index", json=_index_payload(vid, "a city street"))
    assert r.status_code == 200
    fresh_seg = conn.execute(
        "SELECT id FROM segments WHERE video_id = ?", (vid,)
    ).fetchone()["id"]
    insert_embedding(conn, source="segment", source_id=fresh_seg, video_id=vid,
                     vec=[0.0, 1.0])

    assert _embedding_key_components(conn) == before  # the residual's precondition

    second = search._ensure_index(conn)
    assert second is not None
    assert second.matrix[0].tolist() == [0.0, 1.0]
    assert [r[1] for r in second.rows] == [fresh_seg]


def test_the_vocabulary_cache_notices_a_re_index_onto_the_same_ids(client, conn):
    """Same residual on the typo-correction side: the replaced segment gets its
    id back, so nothing about the corpus's shape changed -- only its words."""
    cache = fuzzy.get_vocabulary_cache()
    vid = insert_video(conn, share="broll", rel_path="a.mov")
    insert_segment(conn, vid, description="excavator")

    before = _vocabulary_key_components(conn)
    assert "excavator" in cache.get(conn)

    r = client.post("/api/ingest/index", json=_index_payload(vid, "helicopter"))
    assert r.status_code == 200

    assert _vocabulary_key_components(conn) == before  # the residual's precondition

    vocab = cache.get(conn)
    assert "helicopter" in vocab
    assert "excavator" not in vocab


def test_the_ingest_endpoint_bumps_the_generation(client, conn):
    """The counter is only as good as the write paths' discipline -- so the
    bump, not just its effect, is pinned."""
    vid = insert_video(conn, share="broll", rel_path="a.mov")
    before = read_search_generation(conn)

    assert client.post(
        "/api/ingest/index", json=_index_payload(vid, "a city street")
    ).status_code == 200

    assert read_search_generation(conn) == before + 1


def test_a_failed_ingest_does_not_bump_the_generation(client, conn):
    """Bumping in the same transaction as the write is the whole contract: a
    rejected ingest changed nothing, so the caches must not be told otherwise."""
    before = read_search_generation(conn)

    assert client.post(
        "/api/ingest/index", json=_index_payload(9999, "no such video")
    ).status_code == 404

    assert read_search_generation(conn) == before


def test_reading_the_generation_survives_a_db_without_meta(tmp_path):
    """Query-path posture (see app.semantic/app.fuzzy docstrings): a DB that
    predates migration 010 degrades to generation 0 -- the count and high-water
    components keep working on their own -- rather than 500ing a search."""
    import sqlite3

    conn = sqlite3.connect(":memory:")
    try:
        assert read_search_generation(conn) == 0
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Cross-component parity. The indexer writes this same DB directly when it runs
# co-located (broll_index/storage/sqlite_backend.py), so a bump added on one
# side only leaves the other side's re-index invisible to the caches. The two
# suites run under different interpreters and cannot import each other, so this
# is a source check -- same shape as server/tests/test_cross_component.py's
# ignoreDelete guard.
# ---------------------------------------------------------------------------

# tests/ -> web/ -> broll/
_INDEXER_BACKEND = (
    Path(__file__).resolve().parents[2]
    / "indexer" / "broll_index" / "storage" / "sqlite_backend.py"
)

# Methods of SqliteBackend that insert/replace/delete `embeddings` or the
# segments/transcript_segments rows the fuzzy vocabulary is built from.
_INDEXER_WRITE_METHODS = (
    "write_index_result",
    "write_transcript",
    "upsert_embedding",
    "update_search_norm",
    "delete_video",
)


@pytest.mark.skipif(
    not _INDEXER_BACKEND.exists(),
    reason="indexer/ is not checked out beside web/ (web is deployed standalone)",
)
def test_the_indexer_twin_bumps_the_generation_too():
    source = _INDEXER_BACKEND.read_text(encoding="utf-8")
    bodies = {}
    current = None
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith("def "):
            current = stripped[4:].split("(")[0]
            bodies[current] = []
        elif current is not None:
            bodies[current].append(line)

    for method in _INDEXER_WRITE_METHODS:
        assert method in bodies, f"SqliteBackend.{method} has gone -- update this test"
        assert any("bump_search_generation" in line for line in bodies[method]), (
            f"SqliteBackend.{method} writes the search corpus without bumping "
            "meta.search_generation: the web app's matrix/vocabulary caches "
            "cannot see a same-count, same-rowid replacement without it "
            "(KNOWN_BUGS R2)"
        )
