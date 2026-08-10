from __future__ import annotations

from tests.factories import insert_flag, insert_segment, insert_video


def _seed_basic(conn):
    v1 = insert_video(
        conn, share="broll", rel_path="military/naval/clip_0001.mov", category="military/naval"
    )
    insert_segment(
        conn,
        v1,
        t_start=0.0,
        t_end=8.5,
        description="Grey navy frigate moored at a concrete pier, sailors on deck",
        objects="navy ship, warship, frigate, military vessel, pier, sailors",
        setting="harbor, overcast daylight",
    )

    v2 = insert_video(
        conn, share="broll", rel_path="military/naval/clip_0002.mov", category="military/naval"
    )
    insert_segment(
        conn,
        v2,
        t_start=0.0,
        t_end=6.0,
        description="Sailors performing a harbor exercise drill on the pier",
        objects="sailors, drill, pier, harbor",
        setting="harbor, daytime",
    )
    insert_flag(conn, v2, "shaky")

    v3 = insert_video(
        conn, share="broll", rel_path="nature/ocean/clip_0003.mov", category="nature/ocean"
    )
    insert_segment(
        conn,
        v3,
        t_start=0.0,
        t_end=4.0,
        description="Sailors visiting a lighthouse near a rocky harbor shoreline at sunset",
        objects="lighthouse, rocks, sunset, sailors",
        setting="harbor shoreline, sunset",
    )

    v4 = insert_video(conn, share="other", rel_path="misc/clip_0004.mov", category=None)
    insert_segment(
        conn,
        v4,
        t_start=0.0,
        t_end=3.0,
        description="A city street with pedestrians walking",
        objects="street, pedestrians, city",
        setting="downtown, daytime",
    )
    return v1, v2, v3, v4


def test_multi_term_and_search(client, conn):
    v1, v2, v3, v4 = _seed_basic(conn)
    r = client.get("/api/search", params={"q": "sailors pier"})
    assert r.status_code == 200
    body = r.json()
    ids = {row["video"]["id"] for row in body["results"]}
    # v1 and v2 both mention "sailors" AND "pier"; v3 has sailors but not
    # pier, v4 has neither -> AND semantics must exclude both.
    assert ids == {v1, v2}
    assert body["total"] == 2


def test_phrase_search(client, conn):
    v1, v2, v3, v4 = _seed_basic(conn)
    r = client.get("/api/search", params={"q": '"harbor exercise"'})
    assert r.status_code == 200
    body = r.json()
    ids = {row["video"]["id"] for row in body["results"]}
    # Only v2 has "harbor exercise" as adjacent tokens (v1's "harbor" is in a
    # different segment column from "exercise" doesn't even appear).
    assert ids == {v2}


def test_hits_include_segment_and_snippet(client, conn):
    v1, v2, v3, v4 = _seed_basic(conn)
    r = client.get("/api/search", params={"q": "frigate"})
    body = r.json()
    assert body["total"] == 1
    hit = body["results"][0]["hits"][0]
    assert hit["t_start"] == 0.0
    assert hit["t_end"] == 8.5
    assert "segment_id" in hit
    assert "snippet" in hit and hit["snippet"]
    # Highlighting uses sentinel control chars, not raw HTML, so a
    # description containing "<"/"&" can never inject markup client-side.
    assert "\x01" in hit["snippet"] and "\x02" in hit["snippet"]


def test_category_prefix_filter(client, conn):
    v1, v2, v3, v4 = _seed_basic(conn)
    r = client.get("/api/search", params={"q": "sailors", "category": "military"})
    body = r.json()
    ids = {row["video"]["id"] for row in body["results"]}
    assert ids == {v1, v2}

    r2 = client.get("/api/search", params={"q": "sailors", "category": "nature/ocean"})
    ids2 = {row["video"]["id"] for row in r2.json()["results"]}
    assert ids2 == {v3}


def test_flags_csv_excludes_matching_videos(client, conn):
    v1, v2, v3, v4 = _seed_basic(conn)
    r = client.get("/api/search", params={"q": "pier", "flags": "shaky"})
    body = r.json()
    ids = {row["video"]["id"] for row in body["results"]}
    # v2 has the shaky flag and must be excluded even though it matches "pier".
    assert v2 not in ids
    assert v1 in ids


def test_pagination_over_videos(client, conn):
    for i in range(5):
        v = insert_video(conn, share="broll", rel_path=f"pagetest/clip_{i}.mov")
        insert_segment(
            conn, v, description="generic stock footage clip for pagination testing"
        )

    r_all = client.get("/api/search", params={"q": "pagination", "limit": 100})
    assert r_all.json()["total"] == 5

    seen_ids: set[int] = set()
    for offset in (0, 2, 4):
        r = client.get(
            "/api/search", params={"q": "pagination", "limit": 2, "offset": offset}
        )
        body = r.json()
        assert body["total"] == 5
        page_ids = {row["video"]["id"] for row in body["results"]}
        assert not (page_ids & seen_ids), "pages must not overlap"
        seen_ids |= page_ids
    assert len(seen_ids) == 5


def test_empty_query_browses_all_videos(client, conn):
    _seed_basic(conn)
    r = client.get("/api/search")
    body = r.json()
    assert body["total"] == 4
    assert len(body["results"]) == 4
    for row in body["results"]:
        assert row["hits"] == []


def test_browse_hides_skipped_folders_and_duplicates(client, conn):
    """Browse must show the archive, not the videos table. The editor proxy
    folders and byte-duplicates are never indexed, so they have no poster or
    proxy on disk -- on the real archive they were 2,254 of 4,482 rows, i.e. a
    grid of mostly broken thumbnails and a library count twice its true size.
    """
    _seed_basic(conn)
    insert_video(conn, rel_path="proxies/editor_render.mov", status="skipped")
    original = insert_video(conn, rel_path="misc/original.mov")
    insert_video(conn, rel_path="misc/copy.mov", duplicate_of=original)

    body = client.get("/api/search").json()

    assert body["total"] == 5, "skipped and duplicate rows must not be browsable"
    paths = {r["video"]["rel_path"] for r in body["results"]}
    assert "proxies/editor_render.mov" not in paths
    assert "misc/copy.mov" not in paths
    assert "misc/original.mov" in paths, "the kept side of a duplicate pair stays"


def test_browse_exclusions_compose_with_category_filter(client, conn):
    """The new WHERE must not displace the existing filters."""
    _seed_basic(conn)
    insert_video(conn, rel_path="p/x.mov", status="skipped", category="military/naval")

    body = client.get("/api/search", params={"category": "military/naval"}).json()

    assert body["total"] == 2, "a skipped row must not slip in via a category filter"


def test_special_characters_do_not_break_fts_syntax(client, conn):
    _seed_basic(conn)
    # These would be invalid/dangerous raw FTS5 syntax if not sanitized.
    for q in ['pier:', 'pier*', 'pier OR', '"unterminated', "pier-harbor", "()"]:
        r = client.get("/api/search", params={"q": q})
        assert r.status_code == 200, f"query {q!r} broke search: {r.text}"


def test_video_detail_endpoint(client, conn):
    v1, v2, v3, v4 = _seed_basic(conn)
    r = client.get(f"/api/videos/{v1}")
    assert r.status_code == 200
    body = r.json()
    assert body["video"]["id"] == v1
    assert len(body["segments"]) == 1
    assert body["quality_flags"] == []

    r2 = client.get(f"/api/videos/{v2}")
    assert r2.json()["quality_flags"] == ["shaky"]

    r404 = client.get("/api/videos/999999")
    assert r404.status_code == 404


def test_categories_endpoint(client, conn):
    from tests.factories import insert_category

    insert_category(conn, "military/naval", "Military - Naval")
    r = client.get("/api/categories")
    assert r.status_code == 200
    assert r.json() == [
        {"slug": "military/naval", "label": "Military - Naval", "description": ""}
    ]


def test_shares_endpoint_parses_env(client, monkeypatch):
    monkeypatch.setenv(
        "BROLL_SHARES", "broll:Main b-roll archive;other:desc"
    )
    r = client.get("/api/shares")
    assert r.status_code == 200
    assert r.json() == [
        {"share": "broll", "description": "Main b-roll archive"},
        {"share": "other", "description": "desc"},
    ]
