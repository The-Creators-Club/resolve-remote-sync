"""A failed clip, and a batch whose machine went away, both have a way back.

BROLL-5 / BROLL-8 / BROLL-18 of the usability + resilience sweep (2026-09-03),
built 2026-09-04.

  * **an upload failure was permanent.** `xhr.onerror` set `item.error` for the
    life of the page and the pump skipped that item for ever, so a wifi blip at
    95% of a 4 GB file cost the whole 200-clip drop - while the companion's
    `upload_slot` 409 says in as many words that "the SPA retries a dropped
    file after a reconnect", a retry nobody had written.
  * **a batch whose machine went away could be picked up by NOTHING.** Six
    fleet routes, every one keyed by a uid the caller must already hold, and a
    companion that never polls: the batch sat in `queued` for ever holding name
    reservations and permanently-`ingesting` rows, under a notice claiming
    another of the editor's machines could take it.
  * **`done_with_errors - 12 failed` was the end of the road.** The only
    affordance was `clips`, i.e. twelve names to transcribe by hand and
    re-drop, which the first attempt's `videos` rows then read as duplicates.

Nothing here dispatches work from the browser: retry-failed puts the clips back
in the queue and the PAGE tells its own companion to pick the batch up, which
is the plan's rule that the browser contributes a uid and nothing else.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app import ingest_batches
from tests.conftest import fleet_headers

INGEST_JS = (Path(__file__).resolve().parents[1] / "static" / "ingest.js").read_text(
    encoding="utf-8")

BASE = "/api/fleet/ingest/batches"


def _queue(client, editor="jsmith", n=2):
    client.headers.update({"X-CCSync-User": editor})
    items = [{"local_id": f"l{i}", "name": f"A00{i}.MP4", "size": 10 + i,
              "hash": None, "source": "upload", "rel_dir": ""} for i in range(n)]
    r = client.post("/api/ingest-batches",
                    json={"share": "E2E", "settings": {"tier": "good"},
                          "items": items})
    assert r.status_code == 200, r.text
    return r.json()["uid"]


def _claim(client, uid, editor="jsmith", machine="EDIT-01"):
    return client.post(f"{BASE}/{uid}/claim", headers=fleet_headers(editor, machine),
                       json={"machine": machine, "companion_version": "0.9.67",
                             "tier": "good", "capabilities": {}})


def _fail_one(client, conn, uid, machine="EDIT-01"):
    item = ingest_batches.list_items(conn, uid)[0]
    r = client.post(f"{BASE}/{uid}/items/{item['uid']}/status",
                    headers=fleet_headers("jsmith", machine),
                    json={"state": "failed", "error": "ffmpeg exited 1"})
    assert r.status_code == 200, r.text
    return item["uid"]


# --- BROLL-18: try the failed ones again ---------------------------------------

def test_a_finished_batch_with_failures_can_be_queued_again(client, conn):
    uid = _queue(client)
    assert _claim(client, uid).status_code == 200
    failed_uid = _fail_one(client, conn, uid)
    client.post(f"{BASE}/{uid}/release", headers=fleet_headers(),
                json={"state": "done"})
    assert ingest_batches.get_batch(conn, uid)["state"] == "done_with_errors"

    answer = client.post(f"/api/ingest-batches/{uid}/retry-failed").json()
    assert answer["retried"] == 1
    assert answer["items"] == [failed_uid], (
        "the uids that moved, in batch order: that is the body the companion's "
        "/broll/ingest/retry takes")
    assert answer["state"] == "queued"
    assert ingest_batches.get_item(conn, uid, failed_uid)["state"] == "pending"


def test_a_retry_keeps_the_name_the_first_attempt_allocated(client, conn):
    """The archive name and the `videos` row are already spoken for, and claim
    skips an item that has a video_id - so a retry re-uses the slot rather than
    allocating `A000_2`."""
    uid = _queue(client)
    _claim(client, uid)
    failed_uid = _fail_one(client, conn, uid)
    before = ingest_batches.get_item(conn, uid, failed_uid)
    client.post(f"{BASE}/{uid}/release", headers=fleet_headers(), json={"state": "done"})

    client.post(f"/api/ingest-batches/{uid}/retry-failed")
    after = ingest_batches.get_item(conn, uid, failed_uid)
    assert after["video_id"] == before["video_id"]
    assert after["archive_stem"] == before["archive_stem"]
    assert after["error"] is None, "the last failure is not carried into the retry"


def test_a_retry_never_moves_a_clip_that_is_already_in_the_archive(client, conn):
    uid = _queue(client)
    _claim(client, uid)
    items = ingest_batches.list_items(conn, uid)
    conn.execute("UPDATE ingest_items SET state = 'live' WHERE uid = ?",
                 (items[1]["uid"],))
    conn.commit()
    _fail_one(client, conn, uid)
    client.post(f"{BASE}/{uid}/release", headers=fleet_headers(), json={"state": "done"})

    client.post(f"/api/ingest-batches/{uid}/retry-failed")
    assert ingest_batches.get_item(conn, uid, items[1]["uid"])["state"] == "live", (
        "somebody may already have cut with it")


def test_retrying_a_batch_with_nothing_failed_is_answered_not_refused(client, conn):
    uid = _queue(client)
    r = client.post(f"/api/ingest-batches/{uid}/retry-failed")
    assert r.status_code == 200
    assert r.json()["retried"] == 0
    assert ingest_batches.get_batch(conn, uid)["state"] == "queued"


def test_another_editors_batch_cannot_be_retried(client, conn):
    uid = _queue(client, editor="jsmith")
    client.headers.update({"X-CCSync-User": "someone-else"})
    assert client.post(f"/api/ingest-batches/{uid}/retry-failed").status_code == 404


def test_a_retried_batch_can_be_claimed_and_finished(client, conn):
    """The point of the button: the batch is claimable again, by this machine
    or another of the editor's."""
    uid = _queue(client)
    _claim(client, uid)
    _fail_one(client, conn, uid)
    client.post(f"{BASE}/{uid}/release", headers=fleet_headers(), json={"state": "done"})
    client.post(f"/api/ingest-batches/{uid}/retry-failed")
    assert _claim(client, uid, machine="EDIT-02").status_code == 200


# --- BROLL-8: discovery --------------------------------------------------------

def test_a_companion_can_ask_which_of_its_editors_batches_are_unfinished(client, conn):
    live = _queue(client)
    over = _queue(client)
    _claim(client, over)
    client.post(f"{BASE}/{over}/release", headers=fleet_headers(),
                json={"state": "done"})

    body = client.get(BASE, headers=fleet_headers()).json()
    uids = [b["uid"] for b in body["batches"]]
    assert live in uids and over not in uids
    assert body["editor"] == "jsmith"


def test_discovery_carries_the_heartbeat_and_the_words(client, conn):
    uid = _queue(client)
    _claim(client, uid)
    batch = client.get(BASE, headers=fleet_headers()).json()["batches"][0]
    assert batch["uid"] == uid
    assert batch["machine"] == "EDIT-01"
    assert batch["last_heartbeat_at"]
    assert batch["state_text"] == "starting on EDIT-01"


def test_discovery_is_scoped_to_the_verified_identity(client, conn):
    """The fleet token is held by every companion and is not an identity (H5),
    so a name in the query string must not be a way to read another editor's
    machines."""
    mine = _queue(client, editor="jsmith")
    theirs = _queue(client, editor="other")

    body = client.get(BASE, headers=fleet_headers("jsmith")).json()
    assert [b["uid"] for b in body["batches"]] == [mine]
    assert client.get(f"{BASE}?editor=other",
                      headers=fleet_headers("jsmith")).status_code == 403
    assert client.get(f"{BASE}?editor=jsmith",
                      headers=fleet_headers("jsmith")).status_code == 200


def test_discovery_needs_the_fleet_token(client, conn):
    _queue(client)
    assert client.get(BASE).status_code == 403


def test_discovery_hands_back_a_batch_whose_machine_stopped_answering(client, conn):
    """A lease nobody renewed is what this route exists to surface: the batch
    is back in `queued` with its machine name still on it."""
    uid = _queue(client)
    _claim(client, uid)
    conn.execute("UPDATE ingest_batches SET lease_expires_at = '2000-01-01T00:00:00+00:00' "
                 "WHERE uid = ?", (uid,))
    conn.commit()
    batch = client.get(BASE, headers=fleet_headers()).json()["batches"][0]
    assert batch["state"] == "queued"
    assert batch["machine"] == "EDIT-01", "the name is what the sentence needs"


# --- the page ------------------------------------------------------------------

def test_a_network_failure_is_retried_with_backoff_before_it_is_a_failure():
    body = INGEST_JS[INGEST_JS.index("function ingestUploadFailed"):]
    body = body[:body.index("\n}\n")]
    assert "ING_UPLOAD_RETRIES" in body
    assert "Math.pow(2, attempt) * 1000" in body
    assert "upload interrupted, retrying" in body
    assert "retryable && attempt < ING_UPLOAD_RETRIES" in body, (
        "an HTTP refusal is the companion's considered answer: repeating it "
        "changes nothing")


def test_a_black_holed_connection_fails_on_a_stall_not_on_a_request_ceiling():
    body = INGEST_JS[INGEST_JS.index("function ingestUploadItem"):]
    body = body[:body.index("\n}\n")]
    assert "ING_UPLOAD_STALL_MS" in body and "xhr.abort()" in body
    assert "xhr.onabort" in body
    assert "xhr.timeout =" not in INGEST_JS, (
        "a legitimate 4 GB body takes an hour; any ceiling low enough to catch "
        "a black hole in minutes would kill it")


def test_the_pump_no_longer_skips_an_item_for_ever_once_it_is_retried():
    pump = INGEST_JS[INGEST_JS.index("function ingestPumpUploads"):]
    pump = pump[:pump.index("\n}\n")]
    assert "item.retryAt && item.retryAt > Date.now()" in pump, (
        "a backoff that has not elapsed, not a permanent skip")
    retry = INGEST_JS[INGEST_JS.index("function ingestRetryItem"):]
    retry = retry[:retry.index("\n}\n")]
    assert 'item.error = ""' in retry
    assert "item.uploadAttempt = 0" in retry
    assert "ingestPumpUploads()" in retry


def test_the_failed_row_and_the_whole_drop_both_offer_a_retry():
    assert "ingestRetryItem(item)" in INGEST_JS
    head = INGEST_JS[INGEST_JS.index("function ingestRenderHead"):]
    head = head[:head.index("\n}\n")]
    assert "retry all failed" in head
    assert "ingestRetryAllFailed" in head


def test_a_queued_batch_offers_to_be_taken_over_here():
    card = INGEST_JS[INGEST_JS.index("function ingestRenderBatches"):]
    card = card[:card.index("\n}\n")]
    assert "take over on this computer" in card
    assert 'batch.state === "queued" && ing.scope === "mine"' in card, (
        "this machine cannot index from another editor's staging")

    take = INGEST_JS[INGEST_JS.index("async function ingestTakeOver"):]
    take = take[:take.index("\n}\n")]
    assert '"/broll/ingest/run"' in take and "batch_uid: uid" in take
    assert "e.status === 409" in take, (
        "the claim settles possession: another machine's live lease is a "
        "refusal, not something this button overrides")


def test_the_batch_card_offers_the_failed_ones_again():
    card = INGEST_JS[INGEST_JS.index("function ingestRenderBatches"):]
    card = card[:card.index("\n}\n")]
    assert "try the ${batch.n_failed} failed again" in card

    again = INGEST_JS[INGEST_JS.index("async function ingestRetryFailedBatch"):]
    again = again[:again.index("\n}\n")]
    assert "retry-failed" in again, "the durable half first"
    assert '"/broll/ingest/retry"' in again
    assert "e.status === 404" in again, (
        "an older companion has no retry route: the run call reaches the same "
        "place through the claim")
