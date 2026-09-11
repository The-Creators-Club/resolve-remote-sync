"""Bug hunt 2026-09-11, territory comp-broll-music (CR-238).

One test per finding, each of them failing at 40f931a. The doubles come from
the two ingest suites rather than being re-invented here: a regression test
for "the item wedges in `uploading` for ever" is only worth anything if it
runs the REAL orchestrator against the queue model the rest of the suite
uses (the hunter's point about `FakeQueue` modelling the failure ledger but
not "it was never handed over at all").
"""

from __future__ import annotations

import logging
import sys
import threading
import time
from pathlib import Path

import pytest

from ccsync_companion import (broll_fetch, broll_ingest, broll_server,
                              broll_upload, music_ingest, music_server)

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_broll_ingest import (FakeMedia, FakeQueue, FakeServer,  # noqa: E402
                               make_ingestor, stage_one_clip)
import test_music_ingest as mi  # noqa: E402


# ---------------------------------------------------------------------------
# comp-broll-music-1 - a declared upload that was never queued
# ---------------------------------------------------------------------------

class _MediaThatLosesTheCard(FakeMedia):
    """The camera card is pulled between the proxy and the upload."""

    def __init__(self, victim):
        super().__init__()
        self.victim = Path(victim)

    def run_ffmpeg(self, cmd, timeout=None):
        result = super().run_ffmpeg(cmd, timeout)
        if cmd[0] == "sprite" and self.victim.exists():
            self.victim.unlink()
        return result


def test_a_clip_whose_file_vanished_ends_instead_of_wedging_the_machine(tmp_path):
    """comp-broll-music-1: the original is gone after `describe`, so the rel
    is declared and never enqueued. It can never land and can never fail, so
    the item sat in `uploading` for ever, the heartbeat held the lease and
    every later drop on this machine got the 409."""
    server = FakeServer()
    queue = FakeQueue()
    ing = make_ingestor(tmp_path, server=server, queue=queue)
    staging = stage_one_clip(ing, tmp_path)
    victim = Path(ing.staging_dir(staging)) / "c1.mp4"
    ing.media = _MediaThatLosesTheCard(victim)
    ing.run("b" * 32, staging, "foreground")
    item = ing._batch["items"][0]

    for _ in range(4):
        ing.tick()

    assert item["stage"] == broll_ingest.ITEM_FAILED
    assert server.released(), "the batch has to end, one way or the other"
    assert ing.status()["batch_uid"] == "", "and the machine has to be free"


def test_only_what_the_queue_took_is_declared_as_an_upload(tmp_path):
    """The same defect from the other side: `item['uploads']` is what
    `_pump_uploads` waits on, so a rel the queue never took must not be in
    it."""
    server = FakeServer()
    queue = FakeQueue()
    ing = make_ingestor(tmp_path, server=server, queue=queue)
    staging = stage_one_clip(ing, tmp_path)
    ing.run("b" * 32, staging, "foreground")
    item = ing._batch["items"][0]
    item["outputs"] = {"poster": str(tmp_path / "gone.jpg"),
                       "proxy": str(tmp_path / "proxy.mp4")}
    (tmp_path / "proxy.mp4").write_bytes(b"x")
    item["video_id"] = 4127
    item["archive_dir"] = "creators/x"
    item["archive_stem"] = "A001"
    item["final_name"] = "A001.MP4"
    item["local_path"] = str(tmp_path / "original-gone.MP4")

    ing._enqueue_uploads(item)

    assert "posters/4127.jpg" not in (item.get("uploads") or {}), (
        "a poster the queue never took can never land and can never fail")
    assert item["stage"] == broll_ingest.ITEM_FAILED, (
        "and a missing ORIGINAL is the end of the clip, not a wait")


class _TracklessQueue(FakeQueue):
    """A queue that answers "I have never heard of that rel" - what a worker
    thread that died mid-job leaves behind (comp-broll-music-7)."""

    def enqueue(self, local_path, remote_rel, kind, item_uid="", size_bytes=None):
        self.enqueued.append(remote_rel)

    def tracks(self, rels):
        return []


def test_a_rel_the_queue_forgot_does_not_hold_the_item_for_ever(tmp_path):
    """comp-broll-music-1, belt and braces: a rel that is neither landed nor
    failed, and that the queue does not have either, is a lost upload."""
    server = FakeServer()
    ing = make_ingestor(tmp_path, server=server, queue=_TracklessQueue())
    staging = stage_one_clip(ing, tmp_path)
    ing.run("b" * 32, staging, "foreground")
    item = ing._batch["items"][0]

    for _ in range(broll_ingest.LOST_UPLOAD_TICKS + 3):
        ing.tick()

    assert item["stage"] == broll_ingest.ITEM_FAILED
    assert server.released()


def test_a_track_whose_file_vanished_ends_instead_of_wedging_the_machine(tmp_path):
    """comp-broll-music-1 in `music_ingest`: one file, same wedge."""
    class _SidecarThatLosesTheFile(mi.FakeSidecar):
        def embed_file(self, path, **kw):
            analysis = super().embed_file(path, **kw)
            Path(path).unlink()
            return analysis

    server = mi.FakeServer()
    # A .wav is not transcoded, so the staged file IS the one file the item
    # owns: exactly the case `_enqueue_uploads` has to answer for.
    server.items[0]["orig_name"] = "Slow Burn.wav"
    queue = mi.FakeQueue()
    ing = mi.make_ingestor(tmp_path, server=server, queue=queue,
                           sidecar=_SidecarThatLosesTheFile())
    staging = mi.stage_one(ing, tmp_path, name="Slow Burn.wav")
    status, answer = ing.run("b" * 32, staging)
    assert status == 202, answer
    item = ing._batch["items"][0]

    for _ in range(3):
        ing.tick()

    assert item["stage"] == broll_ingest.ITEM_FAILED
    assert queue.jobs == []
    assert ing._batch is None, "the batch has to release"


# ---------------------------------------------------------------------------
# comp-broll-music-2 - CLEAR FINISHED STAGING and a drop that never ran
# ---------------------------------------------------------------------------

def _staged_not_run(ing, name="A001.MP4"):
    status, body = ing.prepare({"items": [
        {"local_id": "c1", "name": name, "size": 4, "source": "upload"}]})
    assert status == 202
    sid = body["staging_id"]
    directory = ing.staging_dir(sid)
    (directory / "c1.mp4").write_bytes(b"x" * 2048)
    return sid, directory


def test_clear_finished_staging_leaves_a_drop_that_has_not_run(tmp_path):
    """comp-broll-music-2: `max_age_days=0` is the tray's CLEAR FINISHED
    STAGING, and a drop the browser is still PUTting into has no `ended_at`.
    The `at` fallback made every past staging date older than "now"."""
    ing = make_ingestor(tmp_path)
    sid, directory = _staged_not_run(ing)
    ing._staging[sid]["at"] = "2026-09-10T09:00:00Z"

    result = ing.prune_staging(max_age_days=0)

    assert result["removed"] == 0
    assert directory.exists()
    assert sid in ing._staging, "and the upload slots still exist"


def test_the_retention_sweep_leaves_a_drop_still_being_written_into(tmp_path):
    """The same loss on a slower clock: an `at` in the past while the bytes
    are still arriving.

    Retitled by comp-broll-music-2 (2026-09-11b): holding an unrun drop back
    from the RETENTION sweep as well as from the button made those bytes
    permanent, because `ended_at` is written only for a batch that was
    claimed and this is the only rmtree in the ingest stack. What the sweep
    keeps now is a drop a byte landed in recently, which is what this staging
    directory is - the files were written a moment ago.
    """
    ing = make_ingestor(tmp_path)
    sid, directory = _staged_not_run(ing)
    ing._staging[sid]["at"] = "2020-01-01T00:00:00Z"

    assert ing.prune_staging()["removed"] == 0
    assert directory.exists()
    assert sid in ing._staging


# ---------------------------------------------------------------------------
# comp-broll-music-4 - "busy" must not be printable as a success
# ---------------------------------------------------------------------------

def _busy_fetcher(*a, **kw):
    return {"state": broll_fetch.STATE_BUSY, "message": broll_fetch.BUSY_MESSAGE,
            "retry_after": broll_fetch.BUSY_RETRY_AFTER_SECONDS}


def test_the_busy_message_cannot_be_read_as_sent(tmp_path):
    """comp-broll-music-4: a page holding a cached pre-2026-09-04 app.js
    prints `body.message` as a GREEN toast and stops polling, so the sentence
    itself has to say the clip has not gone in."""
    assert broll_fetch.BUSY_MESSAGE.lower().startswith("not sent yet")
    # The current page's `busyOld` branch still matches on this phrase.
    assert "already downloading" in broll_fetch.BUSY_MESSAGE


def test_both_busy_routes_carry_that_sentence(tmp_path):
    for module in (broll_server, music_server):
        source = Path(module.__file__).read_text(encoding="utf-8")
        assert "poll on, which is the same behaviour" not in source, (
            "the comment claiming an old page polls on is what hid this")


# ---------------------------------------------------------------------------
# comp-broll-music-5 - port 0
# ---------------------------------------------------------------------------

def test_port_zero_is_not_a_port():
    """comp-broll-music-5: `0` means "any free port" to bind(), so the
    listener came up somewhere the web UI's hardcoded 8899 cannot find."""
    assert broll_server.configured_port({"broll_server_port": 0}) == broll_server.PORT
    assert broll_server.configured_port({"broll_server_port": "0"}) == broll_server.PORT
    assert broll_server.configured_port({"broll_server_port": 8901}) == 8901


# ---------------------------------------------------------------------------
# comp-app-6 - the bind failure is latched, not repeated every retry
# ---------------------------------------------------------------------------

def _bind_records(caplog):
    return [r for r in caplog.records if "could not listen on" in r.getMessage()]


def test_the_bind_warning_is_said_once_per_distinct_failure(monkeypatch, caplog):
    """comp-app-6: the app retries the bind with a backoff now, and this
    six-line WARNING on every attempt buries the log the editor is asked to
    send. The same fault is DEBUG after the first time; a DIFFERENT one, and
    the first failure after a good start, are loud again."""
    monkeypatch.setattr(broll_server, "_LAST_BIND_ERROR", "", raising=False)

    def taken(*a, **kw):
        raise OSError(98, "address already in use")

    monkeypatch.setattr(broll_server, "make_server", taken)
    caplog.set_level(logging.DEBUG, logger="ccsync.broll")

    caplog.clear()
    assert broll_server.start({"dashboard_url": "http://dash.example"}) is None
    first = _bind_records(caplog)
    assert len(first) == 1 and first[0].levelno == logging.WARNING

    caplog.clear()
    broll_server.start({"dashboard_url": "http://dash.example"})
    broll_server.start({"dashboard_url": "http://dash.example"})
    repeats = _bind_records(caplog)
    assert repeats and all(r.levelno == logging.DEBUG for r in repeats), (
        "the same refusal, over and over, is not news")

    def refused(*a, **kw):
        raise PermissionError(13, "permission denied")

    monkeypatch.setattr(broll_server, "make_server", refused)
    caplog.clear()
    broll_server.start({"dashboard_url": "http://dash.example"})
    changed = _bind_records(caplog)
    assert len(changed) == 1 and changed[0].levelno == logging.WARNING, (
        "a different fault deserves saying again")
    assert broll_server.last_bind_error().endswith("permission denied")


def test_a_bind_that_works_makes_the_next_failure_loud_again(monkeypatch, caplog):
    class _Served:
        server_address = ("127.0.0.1", 8899)
        allowed_origins = {"http://dash.example"}

        def serve_forever(self):
            time.sleep(0.01)

        def shutdown(self):
            pass

        def server_close(self):
            pass

    monkeypatch.setattr(broll_server, "_LAST_BIND_ERROR", "address already in use",
                        raising=False)
    monkeypatch.setattr(broll_server, "make_server", lambda *a, **kw: _Served())
    caplog.set_level(logging.DEBUG, logger="ccsync.broll")
    assert broll_server.start({"dashboard_url": "http://dash.example"}) is not None
    assert broll_server.last_bind_error() == ""

    def taken(*a, **kw):
        raise OSError(98, "address already in use")

    monkeypatch.setattr(broll_server, "make_server", taken)
    caplog.clear()
    broll_server.start({"dashboard_url": "http://dash.example"})
    records = _bind_records(caplog)
    assert len(records) == 1 and records[0].levelno == logging.WARNING, (
        "a bind that worked clears the latch, so the next fault is news again")

    caplog.clear()
    broll_server.start({"dashboard_url": "http://dash.example"})
    again = _bind_records(caplog)
    assert again and all(r.levelno == logging.DEBUG for r in again)


# ---------------------------------------------------------------------------
# comp-broll-music-6 - a download whose thread never starts
# ---------------------------------------------------------------------------

def test_a_download_whose_thread_will_not_start_is_not_downloading_for_ever(
        tmp_path, monkeypatch):
    """comp-broll-music-6: the job was registered before the spawn, so a
    spawn that raised left a registry entry nothing could ever make terminal
    - and one of the two fetch slots gone for the life of the process."""
    monkeypatch.setattr(broll_fetch.rclone_lane, "rclone_available",
                        lambda path, use_cache=True: (True, path))
    cfg = {"remote": "nas", "remote_root": "/mnt/tank/x", "rclone_path": "rclone",
           "local_root": str(tmp_path)}
    dest = str(tmp_path / "b.mp4")

    def refuses(job, cmd):
        raise RuntimeError("can't start new thread")

    with broll_fetch._JOBS_LOCK:
        broll_fetch._JOBS.clear()
    try:
        answer = broll_fetch.poll_fetch(cfg, "a/b.mp4", dest, runner=refuses)

        assert answer["state"] == broll_fetch.STATE_FAILED
        assert broll_fetch._running_count() == 0, "the fetch slot has to come back"
        with broll_fetch._JOBS_LOCK:
            assert dest.lower() not in [k.lower() for k in broll_fetch._JOBS]
    finally:
        with broll_fetch._JOBS_LOCK:
            broll_fetch._JOBS.clear()


# ---------------------------------------------------------------------------
# comp-broll-music-7 - the upload worker's supervisor
# ---------------------------------------------------------------------------

def test_the_upload_worker_survives_an_escaped_exception(monkeypatch):
    """comp-broll-music-7: one exception out of the loop body left `_active`
    set for ever, so `_next_job` refused every later job and nothing on the
    machine uploaded again."""
    monkeypatch.setattr(broll_upload.broll_fetch, "prereq_error", lambda cfg: None)
    seen: list = []

    def runner(queue, job, cmd):
        if job.remote_rel.endswith("boom.jpg"):
            raise RuntimeError("RcloneTuning blew up")
        seen.append(job.remote_rel)
        queue._finish(job, True)

    queue = broll_upload.UploadQueue(
        lambda: {"remote": "nas", "remote_root": "/mnt/tank/x"}, runner=runner)
    try:
        queue.enqueue("a.jpg", "posters/boom.jpg", broll_upload.KIND_POSTER)
        queue.enqueue("b.jpg", "posters/after.jpg", broll_upload.KIND_POSTER)
        deadline = time.time() + 5.0
        while time.time() < deadline and "posters/after.jpg" not in seen:
            time.sleep(0.01)
        assert "posters/after.jpg" in seen, "the queue never recovered"
        assert [f["rel"] for f in queue.failures()] == ["posters/boom.jpg"]
    finally:
        queue.stop_all()


# ---------------------------------------------------------------------------
# music-2 (web half's loopback) - "try the failed tracks again"
# ---------------------------------------------------------------------------

def test_a_retry_that_names_a_batch_runs_it_again_on_this_machine(monkeypatch):
    """music-2: the music page's new "try the failed tracks again" button
    calls this after the server has put the failed items back to `pending`.
    Re-arming the staging ledger alone would leave the batch `queued` with no
    machine holding it, which is comp-broll-music-3 all over again: the body
    names a batch, so the answer is the CLAIM."""
    import http.client
    import json as _json

    from ccsync_companion import loopback_guard, music_server

    calls: list = []

    class _Ingestor:
        def retry(self, body):
            calls.append(("retry", body.get("staging_id"), body.get("items")))
            return 200, {"ok": True, "retried": 2}

        def run(self, batch_uid, staging_id, run_mode):
            calls.append(("run", batch_uid, staging_id, run_mode))
            return 202, {"ok": True, "state": "running"}

    class _Deps:
        ingestor = _Ingestor()

    monkeypatch.setattr(music_server, "call",
                        lambda action, timeout=None, **kw: {"ok": True})
    srv = broll_server.make_server(
        {"mounts": {}}, host="127.0.0.1", port=0,
        ccsync_cfg={"dashboard_url": "http://100.64.0.1:8000"},
        ingest_deps=_Deps(), music_ingest_deps=_Deps())
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        payload = _json.dumps({"batch_uid": "b" * 32, "staging_id": "s1"}).encode()
        conn = http.client.HTTPConnection("127.0.0.1", srv.server_address[1],
                                          timeout=5)
        conn.request("POST", "/music/ingest/retry", body=payload,
                     headers={"Content-Type": "application/json",
                              "Content-Length": str(len(payload)),
                              loopback_guard.TOKEN_HEADER:
                                  loopback_guard.read_token() or ""})
        resp = conn.getresponse()
        body = _json.loads(resp.read())
        conn.close()
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5)

    assert resp.status == 202
    assert body["state"] == "running"
    assert body["retried"] == 2, "and it still says what it re-armed"
    assert calls == [("retry", "s1", None), ("run", "b" * 32, "s1", "")]


# ---------------------------------------------------------------------------
# music-2 (companion half) - a retryable refusal of `result`
# ---------------------------------------------------------------------------

def _music_with_clock(tmp_path, server, clock):
    sidecar = mi.FakeSidecar()
    queue = mi.FakeQueue()
    ing = mi.make_ingestor(tmp_path, server=server, sidecar=sidecar, queue=queue,
                           clock=lambda: clock["t"])
    staging = mi.stage_one(ing, tmp_path)
    status, answer = ing.run("b" * 32, staging)
    assert status == 202, answer
    return ing, sidecar, queue


def test_a_503_on_result_waits_for_the_mount_instead_of_killing_the_track(tmp_path):
    """music-2: the NAS bind mount blips, `allocate_name` answers 503, and
    the companion used to mark every track of the drop permanently failed -
    with no retry route anywhere in music/web to get them back."""
    server = mi.FakeServer()
    server.result_status = 503
    server.result_body = {"detail": "the music library is not mounted here"}
    clock = {"t": 1000.0}
    ing, sidecar, queue = _music_with_clock(tmp_path, server, clock)
    item = ing._batch["items"][0]

    ing.tick()

    assert item["stage"] != broll_ingest.ITEM_FAILED
    assert ing._batch is not None, "a wait must not release the batch"
    assert queue.jobs == []

    # The mount comes back.
    server.result_status = 200
    server.result_body = {"ok": True, "state": "indexed", "track_id": 91,
                          "rel_path": "Slow Burn (2).mp3"}
    clock["t"] += 600.0
    ing.tick()

    assert queue.jobs and queue.jobs[0]["rel"] == "Slow Burn (2).mp3"
    assert len(sidecar.embedded) == 1, (
        "the re-POST must not pay for a second embedding")


def test_the_servers_own_retry_flag_is_what_decides(tmp_path):
    """music-2: `retry: true` is the shape musicweb answers a 503 and a 409
    name_race with. It outranks anything this side guesses from the status,
    and it is read at both levels - FastAPI wraps a raised HTTPException's
    payload in `detail`, a returned body is not wrapped."""
    server = mi.FakeServer()
    server.result_status = 400
    server.result_body = {"detail": {"detail": "the library is busy",
                                     "retry": True}}
    clock = {"t": 1000.0}
    ing, _sidecar, queue = _music_with_clock(tmp_path, server, clock)
    item = ing._batch["items"][0]

    ing.tick()

    assert item["stage"] != broll_ingest.ITEM_FAILED
    assert item["result_retries"] == 1
    assert queue.jobs == []


def test_a_name_race_is_retried_and_a_model_mismatch_is_not(tmp_path):
    server = mi.FakeServer()
    server.result_status = 409
    server.result_body = {"detail": {"detail": "another batch claimed that "
                                               "filename first; retry",
                                     "reason": "name_race"}}
    clock = {"t": 1000.0}
    ing, _sidecar, queue = _music_with_clock(tmp_path, server, clock)
    item = ing._batch["items"][0]
    ing.tick()
    assert item["stage"] != broll_ingest.ITEM_FAILED

    server.result_status = 409
    server.result_body = {"detail": {"detail": "different CLAP model version",
                                     "reason": "model_mismatch"}}
    clock["t"] += 600.0
    ing.tick()

    assert item["stage"] == broll_ingest.ITEM_FAILED
    assert queue.jobs == []


def test_a_library_that_never_comes_back_still_ends_the_batch(tmp_path):
    """The budget is bounded: a wait with no end is the wedge this fix is
    about, wearing a different hat."""
    server = mi.FakeServer()
    server.result_status = 503
    server.result_body = {"detail": "the music library is not mounted here"}
    clock = {"t": 1000.0}
    ing, _sidecar, _queue = _music_with_clock(tmp_path, server, clock)
    item = ing._batch["items"][0]

    for _ in range(music_ingest.MAX_RESULT_RETRIES + 2):
        clock["t"] += 3600.0
        ing.tick()

    assert item["stage"] == broll_ingest.ITEM_FAILED
    assert "not mounted" in item["error"]
    assert ing._batch is None
