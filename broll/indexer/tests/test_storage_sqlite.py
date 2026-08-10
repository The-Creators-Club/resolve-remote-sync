from __future__ import annotations

import sqlite3

import pytest

from broll_index.transcribe import TranscriptCue


def test_schema_applied_once(sqlite_storage):
    # schema.sql is a fresh-install script that lands a brand-new db straight on the
    # latest version — the stepped migrations only matter for pre-existing databases,
    # which is what broll_index.migrate / `broll-index migrate` is for. Asserted against
    # migrate.LATEST_VERSION rather than a literal so the two can never drift: a
    # migration added without bumping schema.sql (or vice versa) fails here.
    from broll_index.migrate import LATEST_VERSION

    version = sqlite_storage.conn.execute("PRAGMA user_version").fetchone()[0]
    assert version == LATEST_VERSION
    tables = {
        r[0]
        for r in sqlite_storage.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert {"videos", "segments", "themes", "quality_flags", "categories", "transcript_segments"} <= tables


def test_upsert_video_insert_and_update(sqlite_storage):
    vid = sqlite_storage.upsert_video("broll", "a/b.mov", status="discovered", size_bytes=100)
    row = sqlite_storage.get_video(vid)
    assert row["share"] == "broll"
    assert row["rel_path"] == "a/b.mov"
    assert row["status"] == "discovered"

    same_id = sqlite_storage.upsert_video("broll", "a/b.mov", status="probed", duration_s=12.5)
    assert same_id == vid
    row2 = sqlite_storage.get_video(vid)
    assert row2["status"] == "probed"
    assert row2["duration_s"] == 12.5
    assert row2["size_bytes"] == 100  # untouched field preserved


def test_get_video_by_path_missing_returns_none(sqlite_storage):
    assert sqlite_storage.get_video_by_path("broll", "nope.mov") is None


def test_videos_by_status_and_limit(sqlite_storage):
    for i in range(5):
        sqlite_storage.upsert_video("broll", f"clip{i}.mov", status="discovered")
    sqlite_storage.upsert_video("broll", "done.mov", status="indexed")

    discovered = sqlite_storage.videos_by_status(["discovered"])
    assert len(discovered) == 5

    limited = sqlite_storage.videos_by_status(["discovered"], limit=2)
    assert len(limited) == 2

    mixed = sqlite_storage.videos_by_status(["discovered", "indexed"])
    assert len(mixed) == 6


def test_set_error(sqlite_storage):
    vid = sqlite_storage.upsert_video("broll", "bad.mov", status="probed")
    sqlite_storage.set_error(vid, "ffprobe failed: no such file")
    row = sqlite_storage.get_video(vid)
    assert row["status"] == "error"
    assert "ffprobe failed" in row["error"]


def test_write_index_result_populates_segments_themes_flags(sqlite_storage):
    vid = sqlite_storage.upsert_video("broll", "clip.mov", status="proxied")
    sqlite_storage.write_index_result(
        vid,
        themes=["naval exercise", "harbor"],
        quality_flags=["shaky"],
        category_hint="military/naval",
        segments=[
            {
                "t_start": 0.0,
                "t_end": 8.5,
                "description": "Grey frigate at pier",
                "objects": ["navy ship", "warship", "frigate"],
                "setting": "harbor, overcast",
                "motion": "slow pan left",
            }
        ],
        model="claude-sonnet-5",
    )

    row = sqlite_storage.get_video(vid)
    assert row["status"] == "indexed"
    assert row["category_hint"] == "military/naval"
    assert row["indexed_at"] is not None
    assert row["model"] == "claude-sonnet-5"

    themes = sqlite_storage.all_themes()
    assert set(themes) == {"naval exercise", "harbor"}

    flags = sqlite_storage.conn.execute(
        "SELECT flag FROM quality_flags WHERE video_id = ?", (vid,)
    ).fetchall()
    assert [f[0] for f in flags] == ["shaky"]

    segs = sqlite_storage.conn.execute(
        "SELECT description, objects FROM segments WHERE video_id = ?", (vid,)
    ).fetchall()
    assert len(segs) == 1
    assert segs[0][0] == "Grey frigate at pier"
    assert segs[0][1] == "navy ship, warship, frigate"


def test_write_index_result_persists_onscreen_text(sqlite_storage):
    vid = sqlite_storage.upsert_video("broll", "clip.mov", status="proxied")
    sqlite_storage.write_index_result(
        vid,
        themes=["news"],
        quality_flags=[],
        category_hint="news/crime",
        segments=[
            {
                "t_start": 18.0,
                "t_end": 27.0,
                "description": "Officials address reporters outside a police compound.",
                "objects": ["press conference", "reporters", "惡龍", "Evil Dragon"],
                "setting": "police compound courtyard, daylight",
                "motion": "static with slow zoom",
                "onscreen_text": "華視新聞 | 警匪激烈槍戰 惡龍中彈落網",
                "onscreen_text_en": "CTS News | Fierce police shootout, suspect 'Evil Dragon' captured",
            }
        ],
        model="claude-sonnet-5",
    )

    segs = sqlite_storage.conn.execute(
        "SELECT onscreen_text, onscreen_text_en FROM segments WHERE video_id = ?", (vid,)
    ).fetchall()
    assert len(segs) == 1
    assert segs[0][0] == "華視新聞 | 警匪激烈槍戰 惡龍中彈落網"
    assert segs[0][1] == "CTS News | Fierce police shootout, suspect 'Evil Dragon' captured"


def test_write_index_result_defaults_missing_onscreen_text(sqlite_storage):
    # A segment that never went through claude_client.validate_contract (e.g. a caller
    # building segments directly, as several other tests in this file do) must not blow
    # up write_index_result — the columns default to '' same as schema.sql's DEFAULT ''.
    vid = sqlite_storage.upsert_video("broll", "clip2.mov", status="proxied")
    sqlite_storage.write_index_result(
        vid,
        themes=[],
        quality_flags=[],
        category_hint=None,
        segments=[
            {"t_start": 0.0, "t_end": 1.0, "description": "d", "objects": [], "setting": "", "motion": ""}
        ],
        model="m",
    )
    row = sqlite_storage.conn.execute(
        "SELECT onscreen_text, onscreen_text_en FROM segments WHERE video_id = ?", (vid,)
    ).fetchone()
    assert row[0] == ""
    assert row[1] == ""


def test_segments_cjk_fts_indexes_onscreen_text(sqlite_storage):
    vid = sqlite_storage.upsert_video("broll", "clip3.mov", status="proxied")
    sqlite_storage.write_index_result(
        vid,
        themes=[],
        quality_flags=[],
        category_hint=None,
        segments=[
            {
                "t_start": 0.0, "t_end": 1.0,
                "description": "d", "objects": [], "setting": "", "motion": "",
                "onscreen_text": "警匪激烈槍戰 惡龍中彈落網",
                "onscreen_text_en": "fierce shootout, Evil Dragon captured",
            }
        ],
        model="m",
    )
    # trigram substring match on a 3-char run (see docs/indexing-findings.md)
    rows = sqlite_storage.conn.execute(
        "SELECT rowid FROM segments_cjk_fts WHERE segments_cjk_fts MATCH '惡龍中'"
    ).fetchall()
    assert len(rows) == 1
    # english gloss reachable via the porter/unicode61 table with stemming
    rows_en = sqlite_storage.conn.execute(
        "SELECT rowid FROM segments_fts WHERE segments_fts MATCH 'shootout'"
    ).fetchall()
    assert len(rows_en) == 1


def test_write_index_result_replaces_existing_segments(sqlite_storage):
    vid = sqlite_storage.upsert_video("broll", "clip.mov", status="proxied")
    base_seg = {
        "t_start": 0.0, "t_end": 1.0, "description": "d", "objects": [], "setting": "", "motion": "",
    }
    sqlite_storage.write_index_result(
        vid, themes=["a"], quality_flags=[], category_hint=None, segments=[base_seg], model="m"
    )
    sqlite_storage.write_index_result(
        vid, themes=["b"], quality_flags=[], category_hint=None, segments=[base_seg, base_seg], model="m"
    )
    segs = sqlite_storage.conn.execute(
        "SELECT id FROM segments WHERE video_id = ?", (vid,)
    ).fetchall()
    assert len(segs) == 2  # old segments replaced, not accumulated
    assert sqlite_storage.all_themes() == ["b"]


def test_segments_fts_indexes_description(sqlite_storage):
    vid = sqlite_storage.upsert_video("broll", "clip.mov", status="proxied")
    sqlite_storage.write_index_result(
        vid,
        themes=[],
        quality_flags=[],
        category_hint=None,
        segments=[
            {
                "t_start": 0.0, "t_end": 1.0,
                "description": "grey navy frigate moored at a pier",
                "objects": ["frigate", "pier"], "setting": "harbor", "motion": "static",
            }
        ],
        model="m",
    )
    rows = sqlite_storage.conn.execute(
        "SELECT rowid FROM segments_fts WHERE segments_fts MATCH 'frigate'"
    ).fetchall()
    assert len(rows) == 1


def test_record_moved_updates_path_and_clears_inbox(sqlite_storage):
    vid = sqlite_storage.upsert_video(
        "broll", "inbox/clip.mov", status="indexed", in_inbox=1, category="military/naval"
    )
    sqlite_storage.record_moved(vid, "military/naval/clip.mov")
    row = sqlite_storage.get_video(vid)
    assert row["rel_path"] == "military/naval/clip.mov"
    assert row["in_inbox"] == 0
    assert row["status"] == "sorted"


def test_sortable_videos_filters_correctly(sqlite_storage):
    sqlite_storage.upsert_video("broll", "a.mov", status="indexed", in_inbox=1, category="cat/a")
    sqlite_storage.upsert_video("broll", "b.mov", status="indexed", in_inbox=1, category=None)
    sqlite_storage.upsert_video("broll", "c.mov", status="discovered", in_inbox=1, category="cat/a")
    sqlite_storage.upsert_video("broll", "d.mov", status="indexed", in_inbox=0, category="cat/a")

    sortable = sqlite_storage.sortable_videos()
    assert [v["rel_path"] for v in sortable] == ["a.mov"]


def test_apply_taxonomy_insert_and_update(sqlite_storage):
    sqlite_storage.apply_taxonomy(
        [{"slug": "military/naval", "label": "Naval", "description": "ships"}]
    )
    cats = sqlite_storage.get_categories()
    assert cats == [{"slug": "military/naval", "label": "Naval", "description": "ships"}]

    sqlite_storage.apply_taxonomy(
        [{"slug": "military/naval", "label": "Naval Ships", "description": "updated"}]
    )
    cats2 = sqlite_storage.get_categories()
    assert cats2[0]["label"] == "Naval Ships"
    assert cats2[0]["description"] == "updated"


def test_categories_check_constraint_rejects_bad_flag(sqlite_storage):
    vid = sqlite_storage.upsert_video("broll", "clip.mov", status="proxied")
    with pytest.raises(sqlite3.IntegrityError):
        sqlite_storage.conn.execute(
            "INSERT INTO quality_flags (video_id, flag) VALUES (?, ?)", (vid, "not_a_real_flag")
        )


# ---------------------------------------------------------------------------
# transcripts (v3)
# ---------------------------------------------------------------------------

def test_write_transcript_and_get_transcript_round_trip(sqlite_storage):
    vid = sqlite_storage.upsert_video("broll", "clip.mov", status="proxied")
    cues = [
        TranscriptCue(0.0, 2.48, "清晨九點半"),
        TranscriptCue(2.48, 5.12, "警方展開了第一波攻堅行動"),
    ]
    sqlite_storage.write_transcript(vid, cues, "zh")

    row = sqlite_storage.get_video(vid)
    assert row["transcribed_at"] is not None
    assert row["transcript_lang"] == "zh"
    assert row["status"] == "proxied"  # transcription must never touch videos.status

    got = sqlite_storage.get_transcript(vid)
    assert [c.text for c in got] == ["清晨九點半", "警方展開了第一波攻堅行動"]
    assert got[0].t_start == 0.0
    assert got[1].t_end == pytest.approx(5.12)


def test_write_transcript_replace_does_not_duplicate_and_keeps_fts_in_sync(sqlite_storage):
    vid = sqlite_storage.upsert_video("broll", "clip.mov", status="proxied")
    sqlite_storage.write_transcript(
        vid, [TranscriptCue(0.0, 1.0, "警匪激烈槍戰 惡龍中彈落網")], "zh"
    )
    sqlite_storage.write_transcript(
        vid, [TranscriptCue(0.0, 1.0, "shootout at the harbor, suspect captured")], "en"
    )

    rows = sqlite_storage.conn.execute(
        "SELECT text FROM transcript_segments WHERE video_id = ?", (vid,)
    ).fetchall()
    assert len(rows) == 1  # replaced, not accumulated
    assert rows[0][0] == "shootout at the harbor, suspect captured"

    row = sqlite_storage.get_video(vid)
    assert row["transcript_lang"] == "en"

    # old CJK cue is gone from the trigram table...
    old_hits = sqlite_storage.conn.execute(
        "SELECT rowid FROM transcript_cjk_fts WHERE transcript_cjk_fts MATCH '惡龍中'"
    ).fetchall()
    assert old_hits == []
    # ...and the new English text is reachable via both FTS tables.
    en_hits = sqlite_storage.conn.execute(
        "SELECT rowid FROM transcript_fts WHERE transcript_fts MATCH 'shootout'"
    ).fetchall()
    assert len(en_hits) == 1
    en_hits_cjk = sqlite_storage.conn.execute(
        "SELECT rowid FROM transcript_cjk_fts WHERE transcript_cjk_fts MATCH 'harbor'"
    ).fetchall()
    assert len(en_hits_cjk) == 1


def test_get_transcript_empty_when_none_written(sqlite_storage):
    vid = sqlite_storage.upsert_video("broll", "clip.mov", status="proxied")
    assert sqlite_storage.get_transcript(vid) == []
