"""The ingest panel's own API: `/api/ingest-batches` (plan §4.3, 2026-08-18).

Six routes the BROWSER drives, plus the ledger rules underneath them. What is
being pinned here, in order of how much it would hurt to get wrong:

  - **identity comes from a header this app does not mint.** No
    `X-CCSync-User` is 401, always. The dashboard's BrollGate strips any
    inbound copy and stamps the real one from the session cookie; if that ever
    stops happening, these tests say the sub-app still refuses rather than
    quietly serving whoever asked.
  - **another editor's batch is a 404, not a 403.** "That exists but is not
    yours" hands out a uid nobody was given, and a uid is the only thing
    between an editor and someone else's drop.
  - **`scope=all` needs an admin.** Seeing which machine every editor is
    sitting at, and stopping their work, is not an ordinary editor's business.
  - **nothing is allocated before a machine takes the work.** A queued batch
    leaves no `videos` rows and reserves no names, so a drop nobody ever ran
    cannot leave ghosts in the library.
"""
from __future__ import annotations

import json

import pytest

from app import ingest_batches
from tests.factories import insert_video


def _items(n=2, **kw):
    out = []
    for i in range(n):
        item = {"local_id": f"l{i}", "name": f"A00{i}.MP4", "size": 1000 + i,
                "hash": f"h{i}", "source": "upload", "rel_dir": ""}
        item.update(kw)
        out.append(item)
    return out


def _create(client, share="E2E-2026-08-18", items=None, **settings):
    body = {"share": share, "settings": {"tier": "good", "run_mode": "idle", **settings},
            "items": items if items is not None else _items()}
    return client.post("/api/ingest-batches", json=body)


# --- who is asking ------------------------------------------------------------

def test_every_route_refuses_a_request_with_no_identity_header(client):
    """login_gate answers this long before the sub-app sees it. This is the
    belt to that brace: reached directly, the app 401s rather than treating an
    anonymous caller as an editor."""
    assert client.post("/api/ingest-batches", json={"share": "s", "items": []}).status_code == 401
    assert client.get("/api/ingest-batches").status_code == 401
    assert client.get("/api/ingest-batches/abc").status_code == 401
    assert client.post("/api/ingest-batches/abc/cancel").status_code == 401
    assert client.post("/api/ingest-batches/abc/upload-paused",
                       json={"paused": True}).status_code == 401
    assert client.post("/api/ingest-batches/precheck",
                       json={"share": "s", "items": []}).status_code == 401


def test_an_empty_identity_header_is_not_an_editor(client):
    """The gate WITHHOLDS the header entirely for a name it cannot carry
    through a latin-1 round trip (a CJK username -- YTDL-29). An empty string
    must not become an editor whose batches every such person shares."""
    r = client.get("/api/ingest-batches", headers={"X-CCSync-User": "   "})
    assert r.status_code == 401


# --- create -------------------------------------------------------------------

def test_creating_a_batch_queues_it_and_touches_nothing_else(as_editor, conn):
    r = _create(as_editor)
    assert r.status_code == 200, r.text
    uid = r.json()["uid"]
    assert len(uid) == 32 and uid == uid.lower()

    batch = ingest_batches.get_batch(conn, uid)
    assert batch["editor"] == "jsmith"
    assert batch["state"] == "queued"
    assert batch["n_items"] == 2
    assert batch["machine"] is None and batch["lease_expires_at"] is None
    # Nothing in the library yet: no rows, no names, no share.
    assert conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM share_roots").fetchone()[0] == 0
    items = ingest_batches.list_items(conn, uid)
    assert [i["ord"] for i in items] == [0, 1]
    assert all(i["video_id"] is None and i["state"] == "pending" for i in items)


def test_two_batches_get_different_uids(as_editor):
    a = _create(as_editor).json()["uid"]
    b = _create(as_editor).json()["uid"]
    assert a != b


def test_a_shoot_name_windows_cannot_store_is_refused_with_the_name_it_should_be(as_editor):
    """Refused, not silently rewritten: an editor who typed `2026/07 shoot`
    should be told it will be `2026_07 shoot` rather than discover it later in
    a folder tree they cannot find their footage in."""
    r = _create(as_editor, share='bad:name?')
    assert r.status_code == 422
    assert r.json()["detail"]["suggestion"] == "bad_name_"


def test_a_shoot_name_cannot_escape_the_archive_root(as_editor):
    for share in ("../../etc", "a/b", "..\\..\\x"):
        assert _create(as_editor, share=share).status_code == 422, share


def test_an_empty_batch_is_refused(as_editor):
    assert _create(as_editor, items=[]).status_code == 422


def test_a_batch_over_the_cap_is_refused_before_it_is_written(as_editor, conn):
    r = _create(as_editor, items=_items(1))
    assert r.status_code == 200
    huge = [{"local_id": str(i), "name": f"c{i}.mp4", "source": "upload"}
            for i in range(ingest_batches.MAX_ITEMS + 1)]
    assert _create(as_editor, items=huge).status_code == 422
    assert conn.execute("SELECT COUNT(*) FROM ingest_batches").fetchone()[0] == 1


@pytest.mark.parametrize("bad", [
    {"tier": "enormous"},
    {"run_mode": "whenever"},
    {"transcribe": True},
])
def test_settings_this_server_cannot_execute_are_refused(as_editor, bad):
    """A tier nobody has heard of is a model nobody can download, and the
    machine would sit in waiting-for-model forever with the editor watching a
    bar that never starts. Transcription is phase 2 and is refused rather than
    ignored."""
    assert _create(as_editor, **bad).status_code == 422


def test_the_run_mode_defaults_to_idle_and_foreground_is_accepted(as_editor, conn):
    """Owner review, 2026-08-18: 'start now' became a run MODE beside the tier.
    Idle is the proxy generator's behaviour and is the default."""
    uid = _create(as_editor).json()["uid"]
    assert json.loads(ingest_batches.get_batch(conn, uid)["settings_json"])["run_mode"] == "idle"
    uid2 = _create(as_editor, run_mode="foreground").json()["uid"]
    stored = json.loads(ingest_batches.get_batch(conn, uid2)["settings_json"])
    assert stored["run_mode"] == "foreground"
    assert stored["tier"] == "good" and stored["transcribe"] is False


def test_unticking_keep_subfolders_flattens_the_items_at_create_time(as_editor, conn):
    """Blanked here so nothing downstream has to consult the settings blob to
    know where a clip belongs."""
    items = _items(1, rel_dir="Day 1/A CAM")
    uid = _create(as_editor, items=items, keep_subfolders=False).json()["uid"]
    assert ingest_batches.list_items(conn, uid)[0]["rel_dir"] == ""
    uid2 = _create(as_editor, items=items, keep_subfolders=True).json()["uid"]
    assert ingest_batches.list_items(conn, uid2)[0]["rel_dir"] == "Day 1/A CAM"


def test_a_rel_dir_cannot_climb_out_of_the_shoot(as_editor, conn):
    uid = _create(as_editor, items=_items(1, rel_dir="../../../Projects")).json()["uid"]
    assert ingest_batches.list_items(conn, uid)[0]["rel_dir"] == "Projects"


# --- precheck -----------------------------------------------------------------

def test_precheck_names_the_duplicate_and_previews_the_final_name(as_editor, conn):
    existing = insert_video(conn, share="old", rel_path="x/A000.MP4", hash="h0",
                            archive_path="Creators_Club/old/Proxy/A000.mp4")
    r = as_editor.post("/api/ingest-batches/precheck", json={
        "share": "E2E", "keep_subfolders": True, "items": _items(2)})
    assert r.status_code == 200, r.text
    by_id = {i["local_id"]: i for i in r.json()["items"]}
    assert by_id["l0"]["duplicate_of"] == existing
    assert by_id["l0"]["duplicate_name"] == "A000.mp4"
    assert by_id["l1"]["duplicate_of"] is None
    assert by_id["l0"]["final_name"] == "A000.MP4"


def test_precheck_allocates_around_a_published_name_and_around_itself(as_editor, conn):
    insert_video(conn, share="E2E", rel_path="A000.MP4",
                 archive_path="Creators_Club/E2E/Proxy/A000.mp4")
    items = [{"local_id": "a", "name": "A000.MP4", "source": "upload"},
             {"local_id": "b", "name": "A000.MP4", "source": "upload"}]
    r = as_editor.post("/api/ingest-batches/precheck",
                       json={"share": "E2E", "items": items})
    names = [i["final_name"] for i in r.json()["items"]]
    assert names == ["A000_2.MP4", "A000_3.MP4"]


def test_precheck_reserves_nothing(as_editor, conn):
    """It runs while the editor is still ticking boxes. A name reserved here
    would be a name leaked by every abandoned drop."""
    as_editor.post("/api/ingest-batches/precheck", json={"share": "E2E", "items": _items()})
    assert conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM ingest_batches").fetchone()[0] == 0


def test_precheck_does_not_flag_a_row_that_is_only_half_ingested(as_editor, conn):
    """An `ingesting` row has no media behind it, so calling a new drop a
    duplicate of it would tell the editor to skip the only copy there is."""
    insert_video(conn, share="E2E", rel_path="A000.MP4", hash="h0", status="ingesting")
    r = as_editor.post("/api/ingest-batches/precheck",
                       json={"share": "E2E", "items": _items(1)})
    assert r.json()["items"][0]["duplicate_of"] is None


# --- list / get ---------------------------------------------------------------

def test_an_editor_sees_only_their_own_batches(client, conn):
    client.headers.update({"X-CCSync-User": "jsmith"})
    mine = _create(client).json()["uid"]
    client.headers.update({"X-CCSync-User": "kchen"})
    theirs = _create(client).json()["uid"]

    seen = [b["uid"] for b in client.get("/api/ingest-batches").json()["batches"]]
    assert seen == [theirs]
    assert client.get(f"/api/ingest-batches/{mine}").status_code == 404, (
        "another editor's batch must be a 404, never a 403 -- a 403 hands out a uid")


def test_scope_all_needs_an_admin(as_editor):
    r = as_editor.get("/api/ingest-batches", params={"scope": "all"})
    assert r.status_code == 403
    assert r.json()["detail"]["reason"] == "admin_only"


def test_an_admin_sees_every_machines_batches(client, conn):
    client.headers.update({"X-CCSync-User": "jsmith", "X-CCSync-Admin": ""})
    _create(client)
    client.headers.update({"X-CCSync-User": "kchen", "X-CCSync-Admin": ""})
    _create(client)

    client.headers.update({"X-CCSync-User": "root", "X-CCSync-Admin": "1"})
    body = client.get("/api/ingest-batches", params={"scope": "all"}).json()
    assert body["admin"] is True
    assert {b["editor"] for b in body["batches"]} == {"jsmith", "kchen"}
    # ...and the admin's own "mine" view is still only theirs, which is none.
    assert client.get("/api/ingest-batches").json()["batches"] == []


def test_an_unknown_scope_is_refused(as_editor):
    assert as_editor.get("/api/ingest-batches", params={"scope": "sideways"}).status_code == 422


def test_get_returns_the_batch_with_its_items_and_no_raw_settings_blob(as_editor):
    uid = _create(as_editor).json()["uid"]
    body = as_editor.get(f"/api/ingest-batches/{uid}").json()
    assert body["batch"]["uid"] == uid
    assert body["batch"]["settings"]["tier"] == "good"
    assert "settings_json" not in body["batch"]
    assert [i["orig_name"] for i in body["items"]] == ["A000.MP4", "A001.MP4"]


# --- cancel / upload-paused ----------------------------------------------------

def test_cancel_asks_and_takes_the_lease_away_rather_than_killing(as_editor, conn):
    """A REQUEST, not a kill: the companion is mid-ffmpeg somewhere and learns
    on its next heartbeat. Flipping the row to `cancelled` here would leave a
    machine crunching a batch the server has forgotten -- and uploading into
    archive paths nothing reserves any more."""
    uid = _create(as_editor).json()["uid"]
    conn.execute("UPDATE ingest_batches SET state = 'running', machine = 'EDIT-01', "
                 "lease_expires_at = '2999-01-01T00:00:00+00:00' WHERE uid = ?", (uid,))
    conn.commit()

    r = as_editor.post(f"/api/ingest-batches/{uid}/cancel")
    assert r.status_code == 200 and r.json()["cancel_requested"] is True
    batch = ingest_batches.get_batch(conn, uid)
    assert batch["cancel_requested"] == 1
    assert batch["cancel_by"] == "jsmith"
    assert batch["state"] == "running", "still running: the machine has not stopped yet"
    assert batch["lease_expires_at"] is None, "the lease goes at the same moment"


def test_cancel_is_idempotent_on_a_finished_batch(as_editor, conn):
    uid = _create(as_editor).json()["uid"]
    conn.execute("UPDATE ingest_batches SET state = 'done' WHERE uid = ?", (uid,))
    conn.commit()
    r = as_editor.post(f"/api/ingest-batches/{uid}/cancel")
    assert r.status_code == 200 and r.json()["already_finished"] is True
    assert ingest_batches.get_batch(conn, uid)["cancel_requested"] == 0


def test_an_admin_can_cancel_someone_elses_batch_and_a_peer_cannot(client, conn):
    client.headers.update({"X-CCSync-User": "jsmith"})
    uid = _create(client).json()["uid"]

    client.headers.update({"X-CCSync-User": "kchen"})
    assert client.post(f"/api/ingest-batches/{uid}/cancel").status_code == 404

    client.headers.update({"X-CCSync-User": "root", "X-CCSync-Admin": "1"})
    assert client.post(f"/api/ingest-batches/{uid}/cancel").status_code == 200
    assert ingest_batches.get_batch(conn, uid)["cancel_by"] == "root"


def test_upload_paused_toggles_without_touching_the_crunching(as_editor, conn):
    """Separate from cancel because they are separate problems: an editor on a
    metered connection wants the indexing to go on and the bytes to wait."""
    uid = _create(as_editor).json()["uid"]
    assert as_editor.post(f"/api/ingest-batches/{uid}/upload-paused",
                          json={"paused": True}).json()["upload_paused"] is True
    batch = ingest_batches.get_batch(conn, uid)
    assert batch["upload_paused"] == 1
    assert batch["cancel_requested"] == 0 and batch["state"] == "queued"
    as_editor.post(f"/api/ingest-batches/{uid}/upload-paused", json={"paused": False})
    assert ingest_batches.get_batch(conn, uid)["upload_paused"] == 0


# --- leases, opportunistically -------------------------------------------------

def test_listing_hands_back_a_batch_whose_machine_stopped_talking(as_editor, conn):
    """There is no timer in this app (uvicorn workers=1, a background thread
    would be one the fleet status page waits behind), so the list call is where
    a dead lease is noticed -- which is whenever anybody is looking."""
    uid = _create(as_editor).json()["uid"]
    conn.execute("UPDATE ingest_batches SET state = 'running', machine = 'EDIT-01', "
                 "lease_expires_at = '2001-01-01T00:00:00+00:00' WHERE uid = ?", (uid,))
    conn.commit()

    body = as_editor.get("/api/ingest-batches").json()
    assert body["batches"][0]["state"] == "queued"
    batch = ingest_batches.get_batch(conn, uid)
    assert batch["lease_expires_at"] is None
    assert batch["machine"] == "EDIT-01", (
        "the machine name stays so the page can still say 'waiting for EDIT-01'")


def test_a_live_lease_is_left_alone(as_editor, conn):
    uid = _create(as_editor).json()["uid"]
    conn.execute("UPDATE ingest_batches SET state = 'running', machine = 'EDIT-01', "
                 "lease_expires_at = '2999-01-01T00:00:00+00:00' WHERE uid = ?", (uid,))
    conn.commit()
    as_editor.get("/api/ingest-batches")
    assert ingest_batches.get_batch(conn, uid)["state"] == "running"


# --- the report-reply helper PR-I calls ----------------------------------------

def test_cancel_requested_for_lists_what_this_machine_should_stop(as_editor, conn):
    uid = _create(as_editor).json()["uid"]
    conn.execute("UPDATE ingest_batches SET machine = 'EDIT-01' WHERE uid = ?", (uid,))
    conn.commit()
    assert ingest_batches.cancel_requested_for(conn, "jsmith", "EDIT-01") == []

    ingest_batches.cancel(conn, uid, "root")
    assert ingest_batches.cancel_requested_for(conn, "jsmith", "EDIT-01") == [uid]
    # ...but not another editor's, and not another machine's.
    assert ingest_batches.cancel_requested_for(conn, "kchen", "EDIT-01") == []
    assert ingest_batches.cancel_requested_for(conn, "jsmith", "EDIT-02") == []


def test_cancel_requested_for_drops_a_batch_that_has_already_finished(as_editor, conn):
    uid = _create(as_editor).json()["uid"]
    ingest_batches.cancel(conn, uid, "root")
    conn.execute("UPDATE ingest_batches SET state = 'cancelled' WHERE uid = ?", (uid,))
    conn.commit()
    assert ingest_batches.cancel_requested_for(conn, "jsmith", None) == []


def test_cancel_requested_for_never_raises_on_an_old_database(conn):
    """It is called from the report handler, which must never fail: a report
    that 500s takes a machine's sync status off the fleet grid, which outranks
    every feature here."""
    conn.execute("DROP TABLE ingest_items")
    conn.execute("DROP TABLE ingest_batches")
    conn.commit()
    assert ingest_batches.cancel_requested_for(conn, "jsmith", "EDIT-01") == []
