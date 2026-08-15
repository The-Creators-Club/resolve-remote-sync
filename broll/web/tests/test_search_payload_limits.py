"""BROLL-WEB-3: what /api/search is allowed to fetch and to serialize.

None of the four per-table FTS queries had a LIMIT, and every row they returned
-- with its full description/text column and a snippet() -- became a meta
entry, an RRF rank-list entry and, for each of the 24 paged videos, an entry in
that video's `hits` array. Measured 2026-08-14 against the live 15,103-clip
archive: q="taiwan" pulled 4,899 segment + 1,771 transcript rows; q="the"
pulled 3,375 + 9,663, put up to 193 hits on a single video, and serialized
1.01 MB of hit text for one 24-card page. The grid reads hits[0]; the seekbar
draws a band per hit for the one clip that gets opened. The rest was
transferred and parsed for nothing, on a 250 ms-debounced search box over a
Tailscale link.

Both caps are deliberately observable through the API rather than asserted on
the SQL text: the row limit decides which videos exist at all, and the hit cap
decides the response's size.
"""
from __future__ import annotations

from app import search
from app.search import FTS_SOURCE_ROW_LIMIT, MAX_HITS_PER_VIDEO
from tests.factories import insert_segment, insert_video

DESCRIPTION = "A cargo freighter under way in the strait at first light"


def test_hits_per_video_are_capped(client, conn):
    """One video, far more matching segments than the cap. Every one of them
    still counts for fusion and for `total`; they just aren't all shipped."""
    video_id = insert_video(conn, rel_path="freighter.mov")
    for i in range(MAX_HITS_PER_VIDEO + 12):
        insert_segment(conn, video_id, t_start=float(i), t_end=float(i) + 1.0,
                       description=DESCRIPTION)

    body = client.get("/api/search", params={"q": "freighter"}).json()

    assert body["total"] == 1, "the cap is per video, it must not drop the video"
    hits = body["results"][0]["hits"]
    assert len(hits) == MAX_HITS_PER_VIDEO


def test_the_capped_hits_are_the_best_ranked_ones(client, conn):
    """hits[0] is the card's thumbnail frame and seek target, so the cut has to
    take from the bottom of the fused order, not the top."""
    video_id = insert_video(conn, rel_path="freighter.mov")
    for i in range(MAX_HITS_PER_VIDEO + 12):
        insert_segment(conn, video_id, t_start=float(i), t_end=float(i) + 1.0,
                       description=DESCRIPTION)
    best = insert_segment(
        conn, video_id, t_start=900.0, t_end=901.0,
        description="freighter freighter freighter",
    )

    body = client.get("/api/search", params={"q": "freighter"}).json()

    hits = body["results"][0]["hits"]
    assert hits[0]["segment_id"] == best, "the strongest match must survive the cut"


def test_a_source_query_stops_at_the_row_limit(client, conn, monkeypatch):
    """Patched down rather than seeded past FTS_SOURCE_ROW_LIMIT: the point is
    that the LIMIT is bound and applied, and seeding 1,000 committed segments
    would buy the same assertion for several seconds of test time."""
    monkeypatch.setattr(search, "FTS_SOURCE_ROW_LIMIT", 2)
    for i in range(6):
        video_id = insert_video(conn, rel_path=f"freighter_{i}.mov")
        insert_segment(conn, video_id, description=DESCRIPTION)

    body = client.get(
        "/api/search",
        params={"q": "freighter", "mode": "keyword", "fuzzy": "false", "limit": 100},
    ).json()

    assert body["total"] == 2, "only the best-ranked rows the limit allows"
    assert len(body["results"]) == 2


def test_the_row_limit_cut_is_deterministic(client, conn, monkeypatch):
    """bm25 ties are ordinary on short documents, so the ORDER BY carries an id
    tie-break -- without it the same query pages differently on consecutive
    requests and a card appears, disappears and reappears."""
    monkeypatch.setattr(search, "FTS_SOURCE_ROW_LIMIT", 3)
    for i in range(9):
        video_id = insert_video(conn, rel_path=f"freighter_{i}.mov")
        insert_segment(conn, video_id, description=DESCRIPTION)

    params = {"q": "freighter", "mode": "keyword", "fuzzy": "false", "limit": 100}
    first = client.get("/api/search", params=params).json()
    for _ in range(3):
        again = client.get("/api/search", params=params).json()
        assert [r["video"]["id"] for r in again["results"]] == [
            r["video"]["id"] for r in first["results"]
        ]


def test_an_ordinary_query_is_nowhere_near_either_cap(client, conn):
    """The caps exist for the pathological end of the corpus and must be
    invisible on a normal search -- this is the regression guard for retuning
    either constant downwards."""
    assert FTS_SOURCE_ROW_LIMIT >= 100 and MAX_HITS_PER_VIDEO >= 5
    for i in range(3):
        video_id = insert_video(conn, rel_path=f"freighter_{i}.mov")
        insert_segment(conn, video_id, description=DESCRIPTION)

    body = client.get("/api/search", params={"q": "freighter strait"}).json()

    assert body["total"] == 3
    assert all(len(row["hits"]) == 1 for row in body["results"])
