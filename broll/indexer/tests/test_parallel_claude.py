"""The parallel API stage must keep the guarantee the serial one had.

The whole point of FatalRunError is that an account-wide failure (session limit,
credit, auth) leaves the queue intact. Parallelising the stage adds a way to
lose that: a worker raising into a pool could be swallowed as a per-video crash,
and the run would march on burning the rest of the queue against a limit that
clears in an hour. These tests pin the two properties that matter — a fatal is
recognised as fatal, and the video's status is untouched when it happens.
"""
from __future__ import annotations

import time

import parallel_claude
from broll_index.pipeline import FatalRunError
from broll_index.storage.sqlite_backend import SqliteBackend


def _cfg(tmp_path, db_path):
    return type("C", (), {
        "shares": {"s": type("S", (), {"root": str(tmp_path)})()},
        "data_root": tmp_path,
        "db": type("D", (), {"path": str(db_path)})(),
    })()


def test_rate_limit_reports_fatal_and_leaves_the_video_queued(tmp_path, schema_path, monkeypatch):
    db_path = tmp_path / "b.db"
    db = SqliteBackend(db_path, schema_path=schema_path)
    vid = db.upsert_video("s", "clip.mp4", status="proxied", duration_s=10.0)
    db.close()

    def boom(*a, **kw):
        raise FatalRunError("API error 429: You've hit your session limit")

    monkeypatch.setattr(parallel_claude, "_process_video", boom)

    _, status = parallel_claude._process_one(_cfg(tmp_path, db_path), "haiku", vid)

    assert status.startswith("fatal:"), f"a session limit must be reported as fatal, got {status}"
    assert "429" in status
    db = SqliteBackend(db_path, schema_path=schema_path)
    assert db.get_video(vid)["status"] == "proxied", "the queue must stay resumable"
    db.close()


def test_per_video_failure_does_not_stop_the_run(tmp_path, schema_path, monkeypatch):
    """One unreadable clip is that clip's problem — it must not read as fatal."""
    db_path = tmp_path / "b.db"
    db = SqliteBackend(db_path, schema_path=schema_path)
    vid = db.upsert_video("s", "clip.mp4", status="proxied", duration_s=10.0)
    db.close()

    def boom(*a, **kw):
        raise RuntimeError("claude response is not valid JSON")

    monkeypatch.setattr(parallel_claude, "_process_video", boom)

    _, status = parallel_claude._process_one(_cfg(tmp_path, db_path), "haiku", vid)

    assert not status.startswith("fatal:")
    assert status.startswith("crash:")


def test_a_silently_errored_video_is_reported_as_an_error(tmp_path, schema_path, monkeypatch):
    """The failure mode that made three runs print `errors 0` while losing 27 clips.

    A per-video failure does NOT propagate out of _process_video: it catches the
    exception, calls set_error, and returns normally so one bad clip cannot stop
    the serial queue. Reporting that as `ok` meant a run could burn a call plus
    its retry, lose the clip, and still summarise clean — with the database the
    only place the loss was visible.
    """
    db_path = tmp_path / "b.db"
    db = SqliteBackend(db_path, schema_path=schema_path)
    vid = db.upsert_video("s", "clip.mp4", status="proxied", duration_s=10.0)
    db.close()

    def sets_error_and_returns_normally(cfg, storage, video, **kw):
        storage.set_error(video["id"], "claude failed: claude returned invalid JSON after one retry")

    monkeypatch.setattr(parallel_claude, "_process_video", sets_error_and_returns_normally)

    _, status = parallel_claude._process_one(_cfg(tmp_path, db_path), "haiku", vid)

    assert status.startswith("error"), f"a set_error'd video must not report ok, got {status!r}"

    db = SqliteBackend(db_path, schema_path=schema_path)
    assert db.get_video(vid)["status"] == "error"
    db.close()


def test_a_successful_video_is_still_reported_ok(tmp_path, schema_path, monkeypatch):
    """The guard must not turn healthy runs into false alarms."""
    db_path = tmp_path / "b.db"
    db = SqliteBackend(db_path, schema_path=schema_path)
    vid = db.upsert_video("s", "clip.mp4", status="proxied", duration_s=10.0)
    db.close()

    def succeeds(cfg, storage, video, **kw):
        storage.update_video(video["id"], status="indexed")

    monkeypatch.setattr(parallel_claude, "_process_video", succeeds)

    _, status = parallel_claude._process_one(_cfg(tmp_path, db_path), "haiku", vid)
    assert status == "ok"


def test_already_indexed_videos_are_not_re_called(tmp_path, schema_path, monkeypatch):
    """Two passes must never pay for the same video twice: the worker re-reads
    status at the moment it starts, not when the id list was built."""
    db_path = tmp_path / "b.db"
    db = SqliteBackend(db_path, schema_path=schema_path)
    vid = db.upsert_video("s", "clip.mp4", status="indexed", duration_s=10.0)
    db.close()

    called = []
    monkeypatch.setattr(parallel_claude, "_process_video",
                        lambda *a, **kw: called.append(1))

    _, status = parallel_claude._process_one(_cfg(tmp_path, db_path), "haiku", vid)

    assert status == "skip"
    assert not called, "an already-indexed video must not spend a model call"


def test_a_video_not_started_by_the_deadline_stays_queued(tmp_path, schema_path, monkeypatch):
    """The point of a deadline over a kill: stopping costs nothing. A video that
    has not started spends no call and keeps its status, so the next run gets
    it."""
    db_path = tmp_path / "b.db"
    db = SqliteBackend(db_path, schema_path=schema_path)
    vid = db.upsert_video("s", "clip.mp4", status="proxied", duration_s=10.0)
    db.close()

    called = []
    monkeypatch.setattr(parallel_claude, "_process_video",
                        lambda *a, **kw: called.append(1))

    _, status = parallel_claude._process_one(
        _cfg(tmp_path, db_path), "haiku", vid, deadline=time.time() - 1,
    )

    assert status == "deadline"
    assert not called, "a video past the deadline must not spend a model call"
    db = SqliteBackend(db_path, schema_path=schema_path)
    assert db.get_video(vid)["status"] == "proxied", "the queue must stay resumable"
    db.close()


def test_a_video_started_before_the_deadline_runs_to_completion(tmp_path, schema_path,
                                                                monkeypatch):
    """The deadline gates STARTING, never interrupts. A call already in flight
    is already paid for — killing it would waste the request and leave the
    video unindexed."""
    db_path = tmp_path / "b.db"
    db = SqliteBackend(db_path, schema_path=schema_path)
    vid = db.upsert_video("s", "clip.mp4", status="proxied", duration_s=10.0)
    db.close()

    def slow_call(*a, **kw):
        # Crosses the deadline while running, exactly like a real call.
        time.sleep(0.05)

    monkeypatch.setattr(parallel_claude, "_process_video", slow_call)

    _, status = parallel_claude._process_one(
        _cfg(tmp_path, db_path), "haiku", vid, deadline=time.time() + 0.01,
    )

    assert status == "ok", "an in-flight video must finish, not be cut off"


def test_no_deadline_is_unchanged(tmp_path, schema_path, monkeypatch):
    """Overnight runs pass no deadline and must behave exactly as before."""
    db_path = tmp_path / "b.db"
    db = SqliteBackend(db_path, schema_path=schema_path)
    vid = db.upsert_video("s", "clip.mp4", status="proxied", duration_s=10.0)
    db.close()

    monkeypatch.setattr(parallel_claude, "_process_video", lambda *a, **kw: None)

    _, status = parallel_claude._process_one(_cfg(tmp_path, db_path), "haiku", vid)

    assert status == "ok"


def test_eligible_ids_excludes_duplicates(tmp_path, schema_path):
    """151 of this archive's rows are confirmed byte-duplicates. Describing
    footage already described is pure waste."""
    db_path = tmp_path / "b.db"
    db = SqliteBackend(db_path, schema_path=schema_path)
    keep = db.upsert_video("s", "a.mp4", status="proxied", duration_s=1.0)
    dupe = db.upsert_video("s", "b.mp4", status="proxied", duration_s=1.0)
    db.update_video(dupe, duplicate_of=keep)
    db.close()

    assert parallel_claude.eligible_ids(str(db_path)) == [keep]


def test_eligible_ids_after_id_splits_the_queue_for_a_concurrent_run(tmp_path, schema_path):
    """Two passes must be able to share the queue without describing a clip twice.

    The queue is snapshotted once at launch, so a second run started later sees
    every clip the first has not yet committed. `_process_one`'s status re-check
    catches only the finished ones — anything mid-flight would be paid for twice.
    """
    db_path = tmp_path / "b.db"
    db = SqliteBackend(db_path, schema_path=schema_path)
    ids = [db.upsert_video("s", f"{i}.mp4", status="proxied", duration_s=1.0)
           for i in range(5)]
    db.close()

    first, second = ids[:3], ids[3:]
    assert parallel_claude.eligible_ids(str(db_path), after_id=first[-1]) == second
    # The two halves partition the queue: nothing shared, nothing dropped.
    assert set(first) | set(parallel_claude.eligible_ids(str(db_path), after_id=first[-1])) == set(ids)
    assert not set(first) & set(parallel_claude.eligible_ids(str(db_path), after_id=first[-1]))


def test_eligible_ids_after_id_none_is_the_whole_queue(tmp_path, schema_path):
    db_path = tmp_path / "b.db"
    db = SqliteBackend(db_path, schema_path=schema_path)
    ids = [db.upsert_video("s", f"{i}.mp4", status="proxied", duration_s=1.0)
           for i in range(3)]
    db.close()

    assert parallel_claude.eligible_ids(str(db_path), after_id=None) == ids
