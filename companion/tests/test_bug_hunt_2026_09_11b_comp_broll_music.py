"""Bug hunt 2026-09-11b, territory comp-broll-music (CR-253).

The hunt OF the fix pass: every test here is about the neighbour one of this
afternoon's fixes opened, so each of them fails at f1eeb42 and passes now.
The doubles come from the two ingest suites for the reason the CR-238 file
gives - a regression test for an orchestrator is only worth something when it
runs the real orchestrator.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

from ccsync_companion import broll_ingest, broll_server

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_broll_ingest import (FakeQueue, FakeServer,  # noqa: E402
                               make_ingestor, stage_one_clip)
import test_music_ingest as mi  # noqa: E402


def _old_iso(days: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ",
                         time.gmtime(time.time() - days * 86400.0))


# ---------------------------------------------------------------------------
# comp-broll-music-1 (companion half) - a claim with no staging id
# ---------------------------------------------------------------------------

def test_a_claim_with_no_staging_id_is_refused_when_this_machine_staged_it(tmp_path):
    """comp-broll-music-1: the page's RETRY FAILED posts
    `{batch_uid, staging_id: null}`, so `_item_from_manifest` builds every
    item with `local_path: ""` and `_crunch_item` fails all of them at once -
    twice each, and then the batch is released failed with the bytes still in
    staging. The page's half is the b-roll builder's; this side must refuse a
    claim it can see would fail wholesale rather than burning the drop."""
    server = FakeServer()
    ing = make_ingestor(tmp_path, server=server, queue=FakeQueue())
    stage_one_clip(ing, tmp_path)

    status, body = ing.run("b" * 32, "")

    assert status == 409, body
    assert ing._batch is None, "and it must not hold a batch it cannot crunch"
    assert "drop" in body["message"].lower() or "staged" in body["message"].lower()


def test_a_take_over_by_a_machine_that_staged_nothing_still_works(tmp_path):
    """The same guard must not break the real take-over: a SECOND machine has
    no staging entry for the batch, so an empty `local_path` there is the
    ordinary "fetch it from the archive" case, not a lost dispatch."""
    server = FakeServer()
    ing = make_ingestor(tmp_path, server=server, queue=FakeQueue())

    status, body = ing.run("b" * 32, "")

    assert status == 202, body


# ---------------------------------------------------------------------------
# comp-broll-music-2 - staging that can never be deleted
# ---------------------------------------------------------------------------

def _unrun_drop(ingestor, tmp_path):
    staging_id = stage_one_clip(ingestor, tmp_path)
    return staging_id, Path(ingestor.staging_dir(staging_id))


def test_the_retention_sweep_expires_a_drop_that_was_never_run(tmp_path):
    """comp-broll-music-2: `ended_at` is written only for a batch that was
    CLAIMED, so a drop that was staged and abandoned had none at any point in
    its life. This afternoon's `continue` therefore made those bytes
    permanent - and `prune_staging` is the only caller of rmtree in the whole
    ingest stack, so nothing else could ever remove them."""
    ingestor = make_ingestor(tmp_path)
    _sid, directory = _unrun_drop(ingestor, tmp_path)
    ingestor._staging[_sid]["at"] = _old_iso(400)
    old = time.time() - 400 * 86400.0
    for child in directory.iterdir():
        os.utime(child, (old, old))

    result = ingestor.prune_staging()

    assert result["removed"] == 1, "the retention has to reach an unrun drop"
    assert not directory.exists()


def test_a_drop_still_being_written_into_survives_the_sweep(tmp_path):
    """The reason the `at` fallback was removed in the first place: a 400-clip
    drop whose PUTs are still arriving has an `at` hours in the past and must
    not be deleted underneath the browser."""
    ingestor = make_ingestor(tmp_path)
    sid, directory = _unrun_drop(ingestor, tmp_path)
    ingestor._staging[sid]["at"] = _old_iso(400)
    # The bytes are arriving now, which is what the mtime says.
    for child in directory.iterdir():
        os.utime(child, None)

    assert ingestor.prune_staging()["removed"] == 0
    assert directory.exists()


def test_clear_finished_staging_still_leaves_an_unrun_drop_and_says_so(tmp_path):
    """FINISHED is the word on the button, so the tray's max_age_days=0 pass
    must still hold an unrun drop back - and it must now REPORT that it did,
    so the sentence that sent the editor to the button can stop doing it."""
    ingestor = make_ingestor(tmp_path)
    sid, directory = _unrun_drop(ingestor, tmp_path)
    ingestor._staging[sid]["at"] = _old_iso(400)

    result = ingestor.prune_staging(max_age_days=0)

    assert result["removed"] == 0
    assert directory.exists()
    assert result["held_unrun"] == 1


def test_the_space_refusal_does_not_name_a_button_that_cannot_act(tmp_path,
                                                                  monkeypatch):
    """comp-broll-music-2: the refusal counted every staging directory as
    "finished b-roll staging" and told the editor to press CLEAR FINISHED
    STAGING, which answers "There is no finished staging to clear on this
    computer." for the drop it was just blamed on."""
    ingestor = make_ingestor(tmp_path)
    _sid, directory = _unrun_drop(ingestor, tmp_path)
    (directory / "big.bin").write_bytes(b"x" * 4096)
    monkeypatch.setattr(broll_server, "_free_bytes_at", lambda _d: 1)

    message = ingestor._space_refusal(directory, 0)

    assert message
    assert "CLEAR FINISHED STAGING" not in message, (
        "nothing here is finished, so nothing that button can do would help")


def test_the_space_refusal_still_names_the_button_for_finished_staging(tmp_path,
                                                                       monkeypatch):
    ingestor = make_ingestor(tmp_path)
    sid, directory = _unrun_drop(ingestor, tmp_path)
    (directory / "big.bin").write_bytes(b"x" * 4096)
    ingestor._staging[sid]["ended_at"] = _old_iso(1)
    monkeypatch.setattr(broll_server, "_free_bytes_at", lambda _d: 1)

    assert "CLEAR FINISHED STAGING" in ingestor._space_refusal(directory, 0)


# ---------------------------------------------------------------------------
# comp-broll-music-3 - orphaned artifacts in the archive
# ---------------------------------------------------------------------------

def test_nothing_is_uploaded_for_a_clip_whose_original_vanished(tmp_path):
    """comp-broll-music-3: `_upload_plan` is poster -> sprite -> proxy ->
    original and dicts keep insertion order, so the first three were already
    handed to the queue by the time the missing original was noticed. The
    item then fails and `item["uploads"]` is cleared, so nothing ever posts
    `mark_uploaded` for them: three files in an editor-visible archive folder
    with no `live` row to own them and nothing that will ever clean up."""
    server = FakeServer()
    queue = FakeQueue()
    ing = make_ingestor(tmp_path, server=server, queue=queue)
    staging = stage_one_clip(ing, tmp_path)
    ing.run("b" * 32, staging, "foreground")
    item = ing._batch["items"][0]
    for name in ("poster.jpg", "sprite.jpg", "proxy.mp4"):
        (tmp_path / name).write_bytes(b"x")
    item["outputs"] = {"poster": str(tmp_path / "poster.jpg"),
                       "sprite": str(tmp_path / "sprite.jpg"),
                       "proxy": str(tmp_path / "proxy.mp4")}
    item["video_id"] = 4127
    item["archive_dir"] = "creators/x"
    item["archive_stem"] = "A001"
    item["final_name"] = "A001.MP4"
    item["local_path"] = str(tmp_path / "card-was-pulled.MP4")

    ing._enqueue_uploads(item)

    assert queue.enqueued == [], (
        "a clip with no original has nothing to archive, so none of its "
        "artifacts may be sent")
    assert item["stage"] == broll_ingest.ITEM_FAILED


# ---------------------------------------------------------------------------
# comp-broll-music-4 - "nothing to do" while a track waits out a retry
# ---------------------------------------------------------------------------

def test_a_track_waiting_out_a_result_retry_is_not_nothing_to_do(tmp_path):
    """comp-broll-music-4: `_next_item` skipping every item made `_drain`
    answer NOTHING_TO_DO, which in `tick` means stop the model server and
    publish "nothing to do" - for up to 300 s, while this machine holds a
    lease on a live batch and its heartbeat keeps renewing it. An editor
    reading the page re-drops the album."""
    server = mi.FakeServer()
    server.result_status = 503
    server.result_body = {"detail": "the music library is not mounted here"}
    clock = {"t": 1000.0}
    sidecar = mi.FakeSidecar()
    ing = mi.make_ingestor(tmp_path, server=server, sidecar=sidecar,
                           queue=mi.FakeQueue(), clock=lambda: clock["t"])
    staging = mi.stage_one(ing, tmp_path)
    assert ing.run("b" * 32, staging)[0] == 202
    ing.tick()
    stopped_before = sidecar.stopped

    # The wait is still running: nothing is crunchable this tick.
    clock["t"] += 1.0
    state = ing.tick()

    assert state != broll_ingest.STATE_NOTHING_TO_DO
    assert ing.status()["gate"] != broll_ingest.STATE_NOTHING_TO_DO
    assert sidecar.stopped == stopped_before, (
        "and the model must not be torn down and rebuilt every 15 s")


# ---------------------------------------------------------------------------
# comp-broll-music-5 - the deferred analysis outlives its batch
# ---------------------------------------------------------------------------

def test_a_cancel_drops_the_deferred_analysis(tmp_path):
    """comp-broll-music-5: entries were popped only in `_post_result`, so a
    cancel, a lost lease or a gate that closed mid-wait left ~25 kB per track
    in memory for the life of the tray process."""
    server = mi.FakeServer()
    server.result_status = 503
    server.result_body = {"detail": "the music library is not mounted here"}
    clock = {"t": 1000.0}
    ing = mi.make_ingestor(tmp_path, server=server, sidecar=mi.FakeSidecar(),
                           queue=mi.FakeQueue(), clock=lambda: clock["t"])
    staging = mi.stage_one(ing, tmp_path)
    assert ing.run("b" * 32, staging)[0] == 202
    ing.tick()
    assert ing._deferred_analysis, "the wait is what parks the vectors here"

    ing.cancel()

    assert ing._deferred_analysis == {}


def test_a_result_that_lands_resets_the_retry_budget(tmp_path):
    """comp-broll-music-5: `result_retries` was never reset, so a rel that
    recovered on try 5 started its NEXT refusal one away from the ceiling."""
    server = mi.FakeServer()
    server.result_status = 503
    server.result_body = {"detail": "not mounted"}
    clock = {"t": 1000.0}
    ing = mi.make_ingestor(tmp_path, server=server, sidecar=mi.FakeSidecar(),
                           queue=mi.FakeQueue(), clock=lambda: clock["t"])
    staging = mi.stage_one(ing, tmp_path)
    assert ing.run("b" * 32, staging)[0] == 202
    ing.tick()
    item = ing._batch["items"][0]
    assert item["result_retries"] == 1

    server.result_status = 200
    server.result_body = {"ok": True, "state": "indexed", "track_id": 91,
                          "rel_path": "Slow Burn (2).mp3"}
    clock["t"] += 600.0
    ing.tick()

    assert not item.get("result_retries")


# ---------------------------------------------------------------------------
# comp-broll-music-6 - a non-OSError bind failure
# ---------------------------------------------------------------------------

def test_a_non_oserror_start_failure_is_latched_and_recorded(tmp_path,
                                                             monkeypatch,
                                                             caplog):
    """comp-broll-music-6: the comp-app-6 fix latched the OSError branch and
    left the generic one below it logging a full traceback on every attempt of
    the new backoff loop - the exact flooding the latch was added to stop -
    while `_LAST_BIND_ERROR` still held the message of an older fault."""
    def _boom(*_a, **_kw):
        raise RuntimeError("mounts is not a mapping")

    monkeypatch.setattr(broll_server, "make_server", _boom)
    monkeypatch.setattr(broll_server, "_LAST_BIND_ERROR",
                        "OSError: address already in use", raising=False)
    cfg = {"local_root": str(tmp_path), "dashboard_url": "http://dash.example"}

    with caplog.at_level(logging.DEBUG, logger="ccsync"):
        assert broll_server.start(cfg) is None
        first = [r for r in caplog.records if "failed to start" in r.getMessage()]
        caplog.clear()
        assert broll_server.start(cfg) is None
        second = [r for r in caplog.records if "failed to start" in r.getMessage()]

    assert "RuntimeError" in broll_server._LAST_BIND_ERROR, (
        "a reader of that global must not be shown an older fault's message")
    assert first and first[0].levelno == logging.WARNING
    assert second and second[0].levelno == logging.DEBUG, (
        "the same fault, every 15 s, is what makes a log unreadable")
