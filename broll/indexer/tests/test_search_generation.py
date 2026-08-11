"""meta.search_generation: the counter the web app's search caches key on.

web/app/semantic.py's embedding matrix and web/app/fuzzy.py's typo-correction
vocabulary are process-wide caches keyed on (row count, MAX(rowid)) as well as
this counter. Those two components cannot see a re-index whose replacement rows
were the highest in the table and came back in exactly the same number --
SQLite reuses the rowids, so nothing about the shape of the data moved while
every vector behind it changed (KNOWN_BUGS R2, the BROLL-17 residual).

The counter closes that, but only while every write path remembers to bump it,
in the same transaction as the write. This backend is one of the two write
paths (the other is the web app's /api/ingest/index, pinned in
web/tests/test_stale_vectors.py, which also carries the source-level parity
check that both twins bump). Hence a test per method here.
"""

from __future__ import annotations

import sqlite3

import pytest

from broll_index.storage.sqlite_backend import SEARCH_GENERATION_KEY

SEGMENT = {"t_start": 0.0, "t_end": 1.0, "description": "d", "objects": [],
           "setting": "", "motion": ""}


def _generation(storage) -> int:
    row = storage.conn.execute(
        "SELECT value FROM meta WHERE key = ?", (SEARCH_GENERATION_KEY,)
    ).fetchone()
    return int(row["value"])


def test_a_fresh_schema_seeds_the_counter(sqlite_storage_v4):
    assert _generation(sqlite_storage_v4) == 0


def test_write_index_result_bumps_the_counter(sqlite_storage_v4):
    vid = sqlite_storage_v4.upsert_video("broll", "clip.mov", status="proxied")
    before = _generation(sqlite_storage_v4)

    sqlite_storage_v4.write_index_result(
        vid, themes=[], quality_flags=[], category_hint=None, segments=[SEGMENT], model="m"
    )

    assert _generation(sqlite_storage_v4) == before + 1


def test_write_transcript_bumps_the_counter(sqlite_storage_v4):
    from broll_index.transcribe import TranscriptCue

    vid = sqlite_storage_v4.upsert_video("broll", "clip.mov", status="proxied")
    before = _generation(sqlite_storage_v4)

    sqlite_storage_v4.write_transcript(
        vid, [TranscriptCue(t_start=0.0, t_end=1.0, text="he says something")], "en"
    )

    assert _generation(sqlite_storage_v4) == before + 1


def test_upsert_embedding_bumps_the_counter_on_both_arms(sqlite_storage_v4):
    """The DO UPDATE arm is the exact residual shape: same row, same rowid, a
    different vector -- invisible to a count or a high-water mark."""
    vid = sqlite_storage_v4.upsert_video("broll", "clip.mov", status="proxied")
    sqlite_storage_v4.write_index_result(
        vid, themes=[], quality_flags=[], category_hint=None, segments=[SEGMENT], model="m"
    )
    seg_id = sqlite_storage_v4.get_segments(vid)[0]["id"]

    before = _generation(sqlite_storage_v4)
    sqlite_storage_v4.upsert_embedding("segment", seg_id, vid, "e5", 2, b"\x00" * 8)
    inserted = _generation(sqlite_storage_v4)
    assert inserted == before + 1

    sqlite_storage_v4.upsert_embedding("segment", seg_id, vid, "e5", 2, b"\x01" * 8)
    assert _generation(sqlite_storage_v4) == inserted + 1
    shape = sqlite_storage_v4.conn.execute(
        "SELECT COUNT(*), MAX(rowid) FROM embeddings"
    ).fetchone()
    assert tuple(shape) == (1, 1)  # nothing the old cache key looks at moved


def test_update_search_norm_bumps_the_counter(sqlite_storage_v4):
    """An UPDATE moves neither the count nor the high-water mark, and
    search_norm is one of the columns the vocabulary is built from."""
    vid = sqlite_storage_v4.upsert_video("broll", "clip.mov", status="proxied")
    sqlite_storage_v4.write_index_result(
        vid, themes=[], quality_flags=[], category_hint=None, segments=[SEGMENT], model="m"
    )
    seg_id = sqlite_storage_v4.get_segments(vid)[0]["id"]
    before = _generation(sqlite_storage_v4)

    sqlite_storage_v4.update_search_norm("segment", seg_id, "d")

    assert _generation(sqlite_storage_v4) == before + 1


def test_delete_video_bumps_the_counter(sqlite_storage_v4):
    vid = sqlite_storage_v4.upsert_video("broll", "clip.mov", status="proxied")
    sqlite_storage_v4.write_index_result(
        vid, themes=[], quality_flags=[], category_hint=None, segments=[SEGMENT], model="m"
    )
    before = _generation(sqlite_storage_v4)

    sqlite_storage_v4.delete_video(vid)

    assert _generation(sqlite_storage_v4) == before + 1


def test_a_rolled_back_write_takes_its_bump_with_it(sqlite_storage_v4):
    """Same transaction, not just same function: a write that never lands must
    not leave the caches believing something changed (and, more importantly, a
    bump that landed while the rows did not would be indistinguishable from a
    real re-index and cost a needless full rebuild)."""
    vid = sqlite_storage_v4.upsert_video("broll", "clip.mov", status="proxied")
    before = _generation(sqlite_storage_v4)

    with pytest.raises(sqlite3.IntegrityError):
        sqlite_storage_v4.write_index_result(
            vid, themes=[], quality_flags=["not_a_real_flag"], category_hint=None,
            segments=[SEGMENT], model="m",
        )
    sqlite_storage_v4.conn.rollback()

    assert _generation(sqlite_storage_v4) == before
