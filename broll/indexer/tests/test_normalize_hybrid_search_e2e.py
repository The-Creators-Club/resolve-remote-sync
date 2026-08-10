"""End-to-end test of migrations/004_hybrid_search.sql's whole point: a normalized
`search_norm` blob makes a Traditional 2-character query match a Simplified source,
via the real FTS5 tables (not just the string transform in isolation — see
tests/test_normalize.py for that).
"""

from __future__ import annotations

from broll_index import normalize


def test_traditional_query_matches_simplified_onscreen_text_via_segments_fts(sqlite_storage_v4):
    vid = sqlite_storage_v4.upsert_video("broll", "xiamen_dashcam.mov", status="proxied")
    sqlite_storage_v4.write_index_result(
        vid,
        themes=["traffic"],
        quality_flags=[],
        category_hint=None,
        segments=[
            {
                "t_start": 0.0,
                "t_end": 12.0,
                "description": "Dashcam footage of heavy traffic",
                "objects": ["car", "road", "traffic jam"],
                "setting": "urban street, daytime",
                "motion": "static, mounted dashcam",
                # verbatim Simplified onscreen text (mainland dashcam overlay)
                "onscreen_text": "厦门堵车现场 请耐心等待",
                "onscreen_text_en": "Xiamen traffic jam scene, please wait patiently",
            }
        ],
        model="claude-sonnet-5",
    )

    seg = sqlite_storage_v4.conn.execute(
        "SELECT id, description, objects, setting, onscreen_text, onscreen_text_en, search_norm "
        "FROM segments WHERE video_id = ?",
        (vid,),
    ).fetchone()
    assert seg["search_norm"] == ""  # not yet computed — this is what the embed stage does

    raw_text = " ".join(
        p for p in (
            seg["description"], seg["objects"], seg["setting"],
            seg["onscreen_text"], seg["onscreen_text_en"],
        ) if p
    )
    blob = normalize.searchable_blob(raw_text)
    sqlite_storage_v4.update_search_norm("segment", seg["id"], blob)

    # Before normalization this is exactly the miss documented in
    # docs/indexing-findings.md: 2 chars (below trigram's floor) in the wrong script.
    traditional_query_hits = sqlite_storage_v4.conn.execute(
        "SELECT rowid FROM segments_fts WHERE segments_fts MATCH '堵車'"
    ).fetchall()
    assert len(traditional_query_hits) == 1
    assert traditional_query_hits[0]["rowid"] == seg["id"]

    # A genuinely absent term still correctly misses (no false positives introduced).
    absent = sqlite_storage_v4.conn.execute(
        "SELECT rowid FROM segments_fts WHERE segments_fts MATCH '滑雪'"
    ).fetchall()
    assert absent == []


def test_traditional_3char_term_matches_simplified_onscreen_text_via_cjk_trigram_fts(sqlite_storage_v4):
    # segments_cjk_fts (trigram) has a 3-character floor (docs/indexing-findings.md), so
    # it can't rescue a 2-char query the way segments_fts's segmented search_norm tokens
    # do above — but it still benefits from search_norm carrying both script variants,
    # for terms >= 3 characters. 裝甲車 / 装甲车 (armoured vehicle) segments as one intact
    # 3-character jieba token in both scripts (verified against the real tokenizer), so
    # it's a genuine trigram substring in the opposite script's search_norm text.
    vid = sqlite_storage_v4.upsert_video("broll", "raid_footage.mov", status="proxied")
    sqlite_storage_v4.write_index_result(
        vid,
        themes=["news"],
        quality_flags=[],
        category_hint=None,
        segments=[
            {
                "t_start": 0.0, "t_end": 8.0,
                "description": "SWAT team surrounds the scene",
                "objects": ["armoured vehicle", "police"],
                "setting": "street, night",
                "motion": "static",
                "onscreen_text": "霹雳小组出动装甲车包围现场",  # Simplified source
                "onscreen_text_en": "SWAT deploys armoured vehicle, surrounds scene",
            }
        ],
        model="claude-sonnet-5",
    )
    seg = sqlite_storage_v4.conn.execute(
        "SELECT id, description, objects, setting, onscreen_text, onscreen_text_en "
        "FROM segments WHERE video_id = ?", (vid,),
    ).fetchone()
    raw_text = " ".join(
        p for p in (
            seg["description"], seg["objects"], seg["setting"],
            seg["onscreen_text"], seg["onscreen_text_en"],
        ) if p
    )
    sqlite_storage_v4.update_search_norm("segment", seg["id"], normalize.searchable_blob(raw_text))

    # Traditional 3-char query against a Simplified-sourced segment.
    hits = sqlite_storage_v4.conn.execute(
        "SELECT rowid FROM segments_cjk_fts WHERE segments_cjk_fts MATCH '裝甲車'"
    ).fetchall()
    assert len(hits) == 1
    assert hits[0]["rowid"] == seg["id"]


def test_traditional_query_matches_simplified_transcript_via_transcript_fts(sqlite_storage_v4):
    from broll_index.transcribe import TranscriptCue

    vid = sqlite_storage_v4.upsert_video("broll", "xiamen_dashcam2.mov", status="proxied")
    sqlite_storage_v4.write_transcript(
        vid, [TranscriptCue(0.0, 3.0, "厦门堵车情况严重")], "zh"
    )

    cue = sqlite_storage_v4.conn.execute(
        "SELECT id, text FROM transcript_segments WHERE video_id = ?", (vid,)
    ).fetchone()
    blob = normalize.searchable_blob(cue["text"])
    sqlite_storage_v4.update_search_norm("transcript", cue["id"], blob)

    hits = sqlite_storage_v4.conn.execute(
        "SELECT rowid FROM transcript_fts WHERE transcript_fts MATCH '堵車'"
    ).fetchall()
    assert len(hits) == 1
    assert hits[0]["rowid"] == cue["id"]
