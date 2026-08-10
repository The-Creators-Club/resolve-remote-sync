"""v2 dual-tokenizer search: on-screen text + the segments_fts/segments_cjk_fts
merge. See SPEC.md "Database" and docs/indexing-findings.md.
"""
from __future__ import annotations

from tests.factories import insert_segment, insert_video


def _seed_chyron_segment(conn):
    video_id = insert_video(
        conn, share="broll", rel_path="news/police_op/clip_0003.mov", category="news"
    )
    segment_id = insert_segment(
        conn,
        video_id,
        t_start=12.0,
        t_end=20.0,
        description="Police press briefing outside a courthouse",
        # Proper nouns read off the chyron must ALSO appear as discrete
        # objects entries in both scripts -- that's what rescues the
        # sub-3-char case (惡龍) that trigram can't reach.
        objects="police officer, press conference, courthouse, 惡龍, Evil Dragon",
        setting="urban, daytime",
        onscreen_text="華視新聞 | 警匪激烈槍戰 惡龍中彈落網",
        onscreen_text_en="CTS News | Fierce police shootout, suspect 'Evil Dragon' captured",
    )
    return video_id, segment_id


def test_cjk_trigram_substring_hit(client, conn):
    """3+ char CJK substring, present only in onscreen_text (trigram-only
    column) -- must be found via segments_cjk_fts."""
    video_id, _ = _seed_chyron_segment(conn)
    r = client.get("/api/search", params={"q": "激烈槍"})
    assert r.status_code == 200
    body = r.json()
    ids = {row["video"]["id"] for row in body["results"]}
    assert video_id in ids


def test_two_char_cjk_term_hits_via_discrete_objects_entry(conn, client):
    """惡龍 is below trigram's 3-char minimum, so segments_cjk_fts cannot
    reach it -- it must still hit via the discrete `objects` entry, which
    unicode61 tokenizes as an exact whole-run token."""
    video_id, _ = _seed_chyron_segment(conn)
    r = client.get("/api/search", params={"q": "惡龍"})
    assert r.status_code == 200
    body = r.json()
    ids = {row["video"]["id"] for row in body["results"]}
    assert video_id in ids


def test_english_gloss_of_chyron_hits(client, conn):
    video_id, _ = _seed_chyron_segment(conn)
    r = client.get("/api/search", params={"q": "Evil Dragon"})
    assert r.status_code == 200
    ids = {row["video"]["id"] for row in r.json()["results"]}
    assert video_id in ids


def test_cjk_only_hit_still_returns_a_snippet(client, conn):
    """A hit reachable only through segments_cjk_fts (not segments_fts) must
    still carry a usable, sentinel-escaped snippet -- built manually since
    segments_fts's snippet() has no bearing on a table it didn't match."""
    video_id, _ = _seed_chyron_segment(conn)
    r = client.get("/api/search", params={"q": "激烈槍"})
    body = r.json()
    row = next(r for r in body["results"] if r["video"]["id"] == video_id)
    assert row["hits"], "expected at least one hit"
    hit = row["hits"][0]
    assert hit["snippet"]
    # The fallback snippet uses the same sentinel markers as the primary
    # table's snippet() so the frontend's rendering path is uniform.
    assert "\x01" in hit["snippet"] and "\x02" in hit["snippet"]
    assert "激烈槍" in hit["snippet"].replace("\x01", "").replace("\x02", "")


def test_sub_three_char_query_does_not_raise(client, conn):
    _seed_chyron_segment(conn)
    for q in ["台", "ab", "惡", "槍"]:
        r = client.get("/api/search", params={"q": q})
        assert r.status_code == 200, f"query {q!r} broke search: {r.text}"


def test_english_stemming_regression(client, conn):
    """Porter stemming on segments_fts must still work post-migration:
    'ships' (query) matches 'ship' (indexed word) via the primary table."""
    video_id = insert_video(conn, share="broll", rel_path="cargo/clip_0009.mov")
    insert_segment(
        conn,
        video_id,
        description="A large cargo ship departing the harbor at dawn",
        objects="cargo ship, container ship, vessel, harbor",
        setting="harbor, dawn",
    )
    r = client.get("/api/search", params={"q": "ships"})
    assert r.status_code == 200
    ids = {row["video"]["id"] for row in r.json()["results"]}
    assert video_id in ids


def test_multi_term_query_with_mixed_lengths_does_not_raise(client, conn):
    """A query combining a short (<3 char) term with a longer one must not
    crash the trigram path -- only an ALL-short-terms query is skipped."""
    _seed_chyron_segment(conn)
    r = client.get("/api/search", params={"q": "ab courthouse"})
    assert r.status_code == 200
