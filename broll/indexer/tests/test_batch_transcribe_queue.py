"""What the one-process Whisper batch is willing to transcribe.

Its docstring said "run it before the pipeline's local stages" while its queue
filtered on `status != 'skipped'` -- a verdict only `probe` ever reaches. Follow
the instruction on a freshly scanned share and every row is still 'discovered',
so nothing is filtered and every multi-hour interview take gets a full Whisper
pass on its way to being discarded by max_duration_s (BROLL-15, 2026-08-11).
config.queue.yaml has said the opposite of that docstring all along.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from batch_transcribe import TODO_SQL  # noqa: E402


def _queue(tmp_path: Path, schema_path: Path, rows: list[dict]) -> set[str]:
    conn = sqlite3.connect(str(tmp_path / "q.db"))
    conn.row_factory = sqlite3.Row
    conn.executescript(schema_path.read_text(encoding="utf-8"))
    for r in rows:
        conn.execute(
            f"INSERT INTO videos ({', '.join(r)}) VALUES ({', '.join('?' * len(r))})",
            list(r.values()),
        )
    conn.commit()
    try:
        return {r["rel_path"] for r in conn.execute(TODO_SQL).fetchall()}
    finally:
        conn.close()


def test_an_unprobed_clip_is_not_transcribed(tmp_path, schema_path):
    """The whole bug: probe has not run, so the duration cap has not run, so
    this may be a three-hour take nothing will ever index."""
    assert _queue(tmp_path, schema_path, [
        {"share": "s", "rel_path": "new.mov", "status": "discovered"},
    ]) == set()


def test_a_probed_clip_is_transcribed(tmp_path, schema_path):
    assert _queue(tmp_path, schema_path, [
        {"share": "s", "rel_path": "ok.mov", "status": "probed", "duration_s": 60.0},
    ]) == {"ok.mov"}


def test_a_discarded_clip_is_not_transcribed(tmp_path, schema_path):
    # The codec is load-bearing since broll-indexer-3: an over-length clip is
    # told from the audio-only one by having a codec AND a duration, the same
    # structural rule `skipped_for_length` uses. A row with neither is not a
    # shape probe can produce.
    assert _queue(tmp_path, schema_path, [
        {"share": "s", "rel_path": "long.mov", "status": "skipped",
         "codec": "h264", "duration_s": 9000.0},
    ]) == set()


def test_an_already_transcribed_clip_and_a_duplicate_are_left_alone(tmp_path, schema_path):
    assert _queue(tmp_path, schema_path, [
        {"share": "s", "rel_path": "done.mov", "status": "indexed",
         "transcribed_at": "2026-08-01T00:00:00Z"},
        {"share": "s", "rel_path": "canon.mov", "status": "indexed"},
        {"share": "s", "rel_path": "dupe.mov", "status": "indexed", "duplicate_of": 2},
    ]) == {"canon.mov"}


# broll-indexer-3 (2026-09-18b mediums): 'skipped' is three verdicts, not one,
# and only two of them mean "do not spend GPU on this". The audio-only one
# (probe found no video stream) is parked precisely so its SPEECH stays
# searchable, and this queue is the only thing in the tree that writes an .srt.
def test_an_audio_only_clip_is_transcribed(tmp_path, schema_path):
    """Its transcript is the only index it will ever have: no codec means no
    proxy, no sprite, no frames, so excluding it here indexes it as nothing."""
    assert _queue(tmp_path, schema_path, [
        {"share": "s", "rel_path": "podcast.mp4", "status": "skipped",
         "duration_s": 1800.0},
    ]) == {"podcast.mp4"}


def test_a_clip_with_no_duration_is_not_transcribed(tmp_path, schema_path):
    """The third 'skipped' verdict (broll-indexer-4): a video stream whose
    container carries no duration. It has a codec, so it is not the audio-only
    shape, and nothing here can sample it - leave it out."""
    assert _queue(tmp_path, schema_path, [
        {"share": "s", "rel_path": "stream.ts", "status": "skipped",
         "codec": "h264"},
    ]) == set()
