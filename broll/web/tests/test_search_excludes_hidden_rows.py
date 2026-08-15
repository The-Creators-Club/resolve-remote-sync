"""BROLL-WEB-2: the search path must hide the same rows browse hides.

BROWSE_PREDICATE (status not skipped/excluded, duplicate_of IS NULL) was
applied by _browse and by /api/tree's counts, and by nothing on the keyword or
semantic path -- justified in _browse's own docstring with "search never
surfaced any of these anyway: with no segments and no transcript they cannot
match".

That is false for duplicates, and false by design. The indexer's
duplicates.pick_canonical ranks a group's members by status and then by SEGMENT
COUNT -- it exists precisely for the case where the losing copies are already
`indexed` -- and marking one writes only the `duplicate_of` column, leaving its
segments, transcript cues, embeddings and FTS entries exactly where they were.
So both copies came back as separate cards with identical thumbnails, and the
duplicate is the broken one: build_archive skips `duplicate_of IS NOT NULL`, so
it has no archive_path, its /media/proxy falls through to a flat path that does
not exist (404, black player) and "Send to Resolve" falls back to the ingest
share, which answers "no mount configured for share 'ff3'" -- the 2026-08-12
failure R12 exists to prevent.

migrations/005_duplicates.sql promised duplicates are excluded "from indexing,
from search results, and from the copy manifest"; two of the three held.
"""
from __future__ import annotations

import math

import numpy as np

from app import semantic
from tests.factories import (
    insert_embedding,
    insert_segment,
    insert_transcript_segment,
    insert_video,
)

MODEL = semantic.DEFAULT_MODEL
QUERY_VEC = [1.0, 0.0]


class FakeEncoder:
    """Returns a preset vector per exact query string; unknown queries get an
    all-zero vector (cosine similarity 0 against anything)."""

    def __init__(self, vectors: dict[str, list[float]]):
        self._vectors = vectors

    def embed(self, docs):
        for d in docs:
            yield np.array(self._vectors.get(d, [0.0, 0.0]), dtype=np.float32)


def _patch_encoder(monkeypatch, vectors: dict[str, list[float]]) -> None:
    monkeypatch.setattr(
        semantic, "_load_fastembed_encoder", lambda name: FakeEncoder(vectors)
    )


def _unit_2d_with_cosine(score: float) -> list[float]:
    return [score, math.sqrt(max(0.0, 1.0 - score * score))]


DESCRIPTION = "A nuclear reactor cooling tower venting steam at dawn"


def _seed_indexed_pair(conn):
    """The ordinary shape: the archive scanner swept two shares, both copies
    were indexed, then `broll-index duplicates --apply` marked the lower-ranked
    one. Both carry the same segment text -- that is what makes them
    duplicates."""
    canonical = insert_video(conn, share="ff3", rel_path="a/reactor.mov")
    insert_segment(conn, canonical, description=DESCRIPTION)
    copy = insert_video(
        conn, share="ff4", rel_path="b/reactor.mov", duplicate_of=canonical
    )
    copy_seg = insert_segment(conn, copy, description=DESCRIPTION)
    return canonical, copy, copy_seg


def test_keyword_search_returns_the_canonical_copy_only(client, conn):
    canonical, copy, _ = _seed_indexed_pair(conn)

    body = client.get("/api/search", params={"q": "nuclear reactor"}).json()

    ids = {row["video"]["id"] for row in body["results"]}
    assert ids == {canonical}, "the duplicate keeps every segment it was indexed with"
    assert body["total"] == 1, "and it must not be counted either"


def test_a_duplicate_is_hidden_from_semantic_search_too(client, conn, monkeypatch):
    """_allowed_video_ids is the semantic side of the same filter -- a vector
    surfaced from a duplicate row lands on the same dead proxy path."""
    _, copy, copy_seg = _seed_indexed_pair(conn)
    insert_embedding(
        conn, source="segment", source_id=copy_seg, video_id=copy,
        vec=_unit_2d_with_cosine(0.95), model=MODEL,
    )
    query = "wholly absent cooling apparatus footage"
    _patch_encoder(monkeypatch, {query: QUERY_VEC})

    body = client.get("/api/search", params={"q": query, "mode": "semantic"}).json()

    assert body["results"] == []
    assert body["total"] == 0


def test_skipped_and_excluded_rows_with_transcripts_stay_out_of_search(client, conn):
    """The other half of the predicate. 'skipped' is an editor proxy folder,
    'excluded' a proxies share's camera originals -- recorded for the conform
    manifest, never meant to be found. Neither is indexed, but a transcript
    pass can still have left cues on them (BROLL-14)."""
    kept = insert_video(conn, rel_path="keep/interview.mov")
    insert_transcript_segment(conn, kept, text="the typhoon made landfall at dawn")
    for status in ("skipped", "excluded"):
        ghost = insert_video(conn, rel_path=f"{status}/interview.mov", status=status)
        insert_transcript_segment(
            conn, ghost, text="the typhoon made landfall at dawn"
        )

    body = client.get("/api/search", params={"q": "typhoon"}).json()

    assert {row["video"]["id"] for row in body["results"]} == {kept}
    assert body["total"] == 1


def test_the_search_filter_composes_with_the_category_filter(client, conn):
    """The new fragment is appended to cat_clause; the existing filters must
    still apply rather than be displaced by it."""
    canonical, copy, _ = _seed_indexed_pair(conn)
    conn.execute(
        "UPDATE videos SET category = 'energy/nuclear' WHERE id IN (?, ?)",
        (canonical, copy),
    )
    conn.commit()

    hit = client.get(
        "/api/search", params={"q": "reactor", "category": "energy/nuclear"}
    ).json()
    assert {row["video"]["id"] for row in hit["results"]} == {canonical}

    miss = client.get(
        "/api/search", params={"q": "reactor", "category": "nature/ocean"}
    ).json()
    assert miss["results"] == []


def test_a_search_hit_the_folder_tree_counts_is_still_reachable(client, conn):
    """The predicate is shared with browse and with /api/tree's counts on
    purpose -- a count that disagrees with the click is worse than no count."""
    canonical, _, _ = _seed_indexed_pair(conn)

    searched = client.get("/api/search", params={"q": "reactor"}).json()
    browsed = client.get("/api/search").json()

    assert {r["video"]["id"] for r in searched["results"]} <= {
        r["video"]["id"] for r in browsed["results"]
    }
    assert canonical in {r["video"]["id"] for r in browsed["results"]}
