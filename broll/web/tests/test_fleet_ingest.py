"""The companion's half: `/api/fleet/ingest` (plan §4.2, 2026-08-18).

These calls happen with no browser open, while an editor is away from their
desk and their own machine crunches clips for an hour. What is pinned here:

  - **the fleet token FAILS CLOSED**, and it is NOT an identity: every
    companion in the fleet holds the same one, so the editor's name arrives as
    a SIGNED token and is verified before the batch's `editor` column is
    compared against it (H5, COMMERCIAL_READINESS.md item 7). A test that
    hand-waved the identity would be testing the hole rather than the fix.
  - **410, not 403, for every way a claim can end** -- expired, cancelled,
    taken by another machine, finished. The companion's answer to all of them
    is the same one, stop quietly; a 403 reads as "fix your credentials" and
    gets retried forever.
  - **claim mints the rows and allocates the names in ONE transaction**, and is
    idempotent for the machine that already holds the batch (a companion
    restarting mid-batch re-issues exactly that call).
  - **`uploaded` believes nothing.** The archive root IS a directory this
    process can read, so it reads it: present, and the right size, or 409 with
    the list of what to send again.
"""
from __future__ import annotations

import json

import pytest

from app import ingest_batches
from tests.conftest import FLEET_TOKEN, fleet_headers
from tests.factories import insert_video

BASE = "/api/fleet/ingest/batches"


def _queue(client, share="E2E", items=None, editor="jsmith", **settings):
    client.headers.update({"X-CCSync-User": editor})
    body = {"share": share, "settings": {"tier": "good", **settings},
            "items": items if items is not None else
            [{"local_id": "l0", "name": "A000.MP4", "size": 1234, "hash": "h0",
              "source": "upload", "rel_dir": ""}]}
    r = client.post("/api/ingest-batches", json=body)
    assert r.status_code == 200, r.text
    return r.json()["uid"]


def _claim(client, uid, editor="jsmith", machine="EDIT-01", **kw):
    body = {"machine": machine, "companion_version": "0.8.0", "tier": "good",
            "capabilities": {"vram_gb": 12}}
    body.update(kw)
    return client.post(f"{BASE}/{uid}/claim", json=body,
                       headers=fleet_headers(editor, machine))


# --- the two credentials -------------------------------------------------------

def test_no_fleet_token_no_entry(client, conn):
    uid = _queue(client)
    r = client.post(f"{BASE}/{uid}/claim", json={"machine": "EDIT-01"})
    assert r.status_code == 403
    assert conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0] == 0


def test_a_wrong_fleet_token_is_refused(client):
    uid = _queue(client)
    headers = fleet_headers()
    headers["X-CCSync-Token"] = "not-the-token"
    assert client.post(f"{BASE}/{uid}/claim", json={"machine": "E"},
                       headers=headers).status_code == 403


def test_a_junk_non_ascii_credential_is_refused_and_never_raises():
    """hmac.compare_digest raises TypeError on a str with any character above
    U+007F, and one non-ASCII byte in a header turned a refusal into a 500 and
    a traceback (DASH-5, 2026-08-11).

    Called directly rather than over the TestClient: httpx refuses to encode a
    non-latin-1 header at all, so the round trip cannot reach the code this is
    about -- but a real client, or a proxy, can put those bytes on the wire.
    """
    from app.fleet_auth import token_ok

    assert token_ok(FLEET_TOKEN, "tökén") is False
    assert token_ok(FLEET_TOKEN, "😀") is False
    assert token_ok("tökén", "tökén") is True
    assert token_ok(None, FLEET_TOKEN) is False
    assert token_ok(FLEET_TOKEN, "") is False


def test_an_unconfigured_server_refuses_rather_than_running_open(client, monkeypatch):
    """FAIL CLOSED. A deployment that lost DASH_REPORT_TOKEN should lose
    dashboard b-roll ingest entirely -- the archive keeps serving, search keeps
    working, and the base-rig indexer is untouched."""
    uid = _queue(client)
    monkeypatch.delenv("DASH_REPORT_TOKEN")
    assert _claim(client, uid).status_code == 403


def test_a_valid_token_with_no_signed_identity_is_refused(client):
    """The token proves 'a fleet machine' and NOTHING about which editor."""
    uid = _queue(client)
    r = client.post(f"{BASE}/{uid}/claim", json={"machine": "E"},
                    headers={"X-CCSync-Token": FLEET_TOKEN})
    assert r.status_code == 403
    assert r.json()["detail"]["reason"] == "identity"


def test_an_identity_signed_with_the_wrong_secret_is_refused(client):
    from app import identity

    uid = _queue(client)
    r = client.post(f"{BASE}/{uid}/claim", json={"machine": "E"}, headers={
        "X-CCSync-Token": FLEET_TOKEN,
        "X-CCSync-Identity": identity.make_identity_token("some-other-secret", "jsmith")})
    assert r.status_code == 403


def test_a_server_that_cannot_verify_identities_refuses(client, monkeypatch):
    uid = _queue(client)
    monkeypatch.delenv("DASH_SESSION_SECRET")
    r = _claim(client, uid)
    assert r.status_code == 403
    assert r.json()["detail"]["reason"] == "identity_unconfigured"


def test_another_editors_machine_cannot_claim_this_batch(client, conn):
    """403 here and not 410 -- this one really is 'wrong credentials'. It is
    the hole H5 closed in ytdl: with only the shared token, any machine could
    claim someone else's work and then poison it."""
    uid = _queue(client, editor="jsmith")
    r = _claim(client, uid, editor="kchen")
    assert r.status_code == 403
    assert r.json()["detail"]["reason"] == "identity"
    assert conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0] == 0


# --- claim ---------------------------------------------------------------------

def test_claim_mints_the_rows_allocates_the_names_and_takes_the_lease(client, conn):
    uid = _queue(client)
    r = _claim(client, uid)
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["lease_seconds"] == 300 and body["heartbeat_seconds"] == 30
    assert body["archive_remote_rel"] == "Assets/B-roll Archive"
    item = body["items"][0]
    assert item["archive_dir"] == "Creators_Club/E2E"
    assert item["archive_stem"] == "A000"
    assert item["rel_path"] == "A000.MP4"
    assert item["share"] == "E2E"

    video = conn.execute("SELECT * FROM videos WHERE id = ?", (item["video_id"],)).fetchone()
    assert video["status"] == "ingesting", (
        "the row exists to reserve the name and hold segments -- there is no "
        "media on the NAS for hours yet")
    assert video["share"] == "E2E" and video["rel_path"] == "A000.MP4"
    assert video["hash"] == "h0" and video["size_bytes"] == 1234

    batch = ingest_batches.get_batch(conn, uid)
    assert batch["state"] == "claimed" and batch["machine"] == "EDIT-01"
    assert batch["companion_version"] == "0.8.0"
    assert batch["lease_expires_at"] is not None


def test_claim_records_the_share_as_own_footage(client, conn):
    """Without `share_roots.collection` this shoot would file under Downloads:
    creators_shares derives own-footage membership from source='proxies', and
    an ingested clip archives ORIGINALS."""
    from app import config, search

    uid = _queue(client, share="Whisky2026")
    _claim(client, uid)
    row = conn.execute("SELECT * FROM share_roots WHERE share = 'Whisky2026'").fetchone()
    assert row["root"] == f"ingest:{uid}"
    assert row["source"] == "originals"
    assert row["indexed"] == 1
    assert row["collection"] == config.COLLECTION_CREATORS
    assert "Whisky2026" in search.creators_shares(conn)


def test_claim_never_overwrites_an_existing_shares_root(client, conn):
    """The indexer owns `root`/`source` for the shares it pushes; ingest may
    only ever say which browse root a share belongs to."""
    conn.execute("INSERT INTO share_roots (share, root, source) VALUES ('E2E', 'Z:/ff3', "
                 "'proxies')")
    conn.commit()
    _claim(client, _queue(client, share="E2E"))
    row = conn.execute("SELECT * FROM share_roots WHERE share = 'E2E'").fetchone()
    assert row["root"] == "Z:/ff3" and row["source"] == "proxies"


def test_claim_allocates_around_a_name_already_published_in_that_folder(client, conn):
    """Settled against CLAIMED names, never against what is on disk
    (BROLL-IDX-5): the second machine must not write over a file already
    recorded on another row and already cut into a timeline."""
    insert_video(conn, share="other", rel_path="x.mov",
                 archive_path="Creators_Club/E2E/Proxy/A000.mp4")
    uid = _queue(client)
    item = _claim(client, uid).json()["items"][0]
    assert item["archive_stem"] == "A000_2"
    assert item["rel_path"] == "A000_2.MP4"


def test_two_clips_of_one_drop_cannot_claim_the_same_slot(client, conn):
    items = [{"local_id": "a", "name": "A000.MP4", "source": "upload"},
             {"local_id": "b", "name": "A000.MP4", "source": "upload"}]
    uid = _queue(client, items=items)
    stems = [i["archive_stem"] for i in _claim(client, uid).json()["items"]]
    assert stems == ["A000", "A000_2"]


def test_sub_folders_become_archive_folders(client, conn):
    items = [{"local_id": "a", "name": "A000.MP4", "source": "upload",
              "rel_dir": "Day 1/A CAM"}]
    item = _claim(client, _queue(client, items=items)).json()["items"][0]
    assert item["archive_dir"] == "Creators_Club/E2E/Day 1/A CAM"
    assert item["rel_path"] == "Day 1/A CAM/A000.MP4"


def test_re_claiming_from_the_same_machine_is_idempotent(client, conn):
    """A companion restarting mid-batch re-issues exactly this call, and must
    get the same manifest back rather than a second set of rows and a second
    set of `_2` names."""
    uid = _queue(client)
    first = _claim(client, uid).json()["items"]
    second = _claim(client, uid).json()["items"]
    assert [i["video_id"] for i in first] == [i["video_id"] for i in second]
    assert [i["archive_stem"] for i in first] == [i["archive_stem"] for i in second]
    assert conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0] == 1


def test_a_second_machine_is_refused_while_the_lease_is_live(client, conn):
    uid = _queue(client)
    _claim(client, uid, machine="EDIT-01")
    r = _claim(client, uid, machine="LAPTOP-02")
    assert r.status_code == 409
    assert r.json()["detail"]["machine"] == "EDIT-01"


def test_another_machine_of_the_same_editor_may_claim_after_the_lease_expires(client, conn):
    uid = _queue(client)
    _claim(client, uid, machine="EDIT-01")
    conn.execute("UPDATE ingest_batches SET lease_expires_at = '2001-01-01T00:00:00+00:00' "
                 "WHERE uid = ?", (uid,))
    conn.commit()
    r = _claim(client, uid, machine="LAPTOP-02")
    assert r.status_code == 200
    assert ingest_batches.get_batch(conn, uid)["machine"] == "LAPTOP-02"
    # ...and it did not mint a second set of rows for the same clips.
    assert conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0] == 1


def test_a_cancelled_batch_answers_410(client, conn):
    uid = _queue(client)
    ingest_batches.cancel(conn, uid, "root")
    r = _claim(client, uid)
    assert r.status_code == 410
    assert r.json()["detail"]["reason"] == "cancelled"


def test_a_finished_batch_answers_410(client, conn):
    uid = _queue(client)
    conn.execute("UPDATE ingest_batches SET state = 'done' WHERE uid = ?", (uid,))
    conn.commit()
    assert _claim(client, uid).status_code == 410


def test_an_unknown_batch_is_404(client):
    assert _claim(client, "f" * 32).status_code == 404


# --- heartbeat -----------------------------------------------------------------

def test_the_heartbeat_extends_the_lease_and_carries_the_two_flags(client, conn):
    uid = _queue(client)
    _claim(client, uid)
    before = ingest_batches.get_batch(conn, uid)["lease_expires_at"]
    conn.execute("UPDATE ingest_batches SET lease_expires_at = '2100-01-01T00:00:00+00:00', "
                 "upload_paused = 1 WHERE uid = ?", (uid,))
    conn.commit()

    r = client.post(f"{BASE}/{uid}/heartbeat", json={}, headers=fleet_headers())
    assert r.status_code == 200
    assert r.json()["upload_paused"] is True
    assert r.json()["cancel_requested"] is False
    after = ingest_batches.get_batch(conn, uid)["lease_expires_at"]
    assert after != before and after < "2100"


def test_the_heartbeat_is_how_a_cancel_reaches_a_busy_machine(client, conn):
    uid = _queue(client)
    _claim(client, uid)
    ingest_batches.cancel(conn, uid, "root")
    r = client.post(f"{BASE}/{uid}/heartbeat", json={}, headers=fleet_headers())
    assert r.status_code == 410
    assert r.json()["detail"]["reason"] == "cancelled"
    assert r.json()["detail"]["cancel_by"] == "root"


def test_a_machine_that_lost_the_lease_gets_410_not_403(client, conn):
    uid = _queue(client)
    _claim(client, uid, machine="EDIT-01")
    conn.execute("UPDATE ingest_batches SET lease_expires_at = '2001-01-01T00:00:00+00:00' "
                 "WHERE uid = ?", (uid,))
    conn.commit()
    r = client.post(f"{BASE}/{uid}/heartbeat", json={}, headers=fleet_headers())
    assert r.status_code == 410
    assert r.json()["detail"]["reason"] == "lease_expired"


def test_the_machine_that_no_longer_holds_it_gets_410(client, conn):
    uid = _queue(client)
    _claim(client, uid, machine="EDIT-01")
    r = client.post(f"{BASE}/{uid}/heartbeat", json={},
                    headers=fleet_headers(machine="LAPTOP-02"))
    assert r.status_code == 410
    assert r.json()["detail"]["reason"] == "other_machine"


# --- per-item status -----------------------------------------------------------

def _first_item(client, uid):
    return _claim(client, uid).json()["items"][0]["uid"]


def test_a_checkpoint_moves_the_item_and_starts_the_batch(client, conn):
    uid = _queue(client)
    iuid = _first_item(client, uid)
    r = client.post(f"{BASE}/{uid}/items/{iuid}/status",
                    json={"state": "proxying", "stage_percent": 30},
                    headers=fleet_headers())
    assert r.status_code == 200
    item = ingest_batches.get_item(conn, uid, iuid)
    assert item["state"] == "proxying" and item["stage_percent"] == 30
    batch = ingest_batches.get_batch(conn, uid)
    assert batch["state"] == "running", (
        "`running` is entered by the first item that STARTS, not by the claim: "
        "a batch blocked on the idle gate for three hours is honestly `claimed`")
    assert batch["current_item_uid"] == iuid


def test_an_item_cannot_go_backwards(client, conn):
    """A late-arriving retry of an earlier POST must not un-index a clip that
    has since been described."""
    uid = _queue(client)
    iuid = _first_item(client, uid)
    for state in ("proxying", "framing", "describing"):
        assert client.post(f"{BASE}/{uid}/items/{iuid}/status", json={"state": state},
                           headers=fleet_headers()).status_code == 200
    r = client.post(f"{BASE}/{uid}/items/{iuid}/status", json={"state": "proxying"},
                    headers=fleet_headers())
    assert r.status_code == 400
    assert r.json()["detail"]["reason"] == "illegal_transition"
    assert ingest_batches.get_item(conn, uid, iuid)["state"] == "describing"


def test_the_same_state_may_be_re_posted_for_progress(client, conn):
    uid = _queue(client)
    iuid = _first_item(client, uid)
    client.post(f"{BASE}/{uid}/items/{iuid}/status", json={"state": "proxying",
                                                          "stage_percent": 10},
                headers=fleet_headers())
    r = client.post(f"{BASE}/{uid}/items/{iuid}/status", json={"state": "proxying",
                                                              "stage_percent": 90},
                    headers=fleet_headers())
    assert r.status_code == 200
    assert ingest_batches.get_item(conn, uid, iuid)["stage_percent"] == 90


def test_failed_is_the_one_terminal_state_that_can_be_left_again(client, conn):
    """A proxy that did not decode is worth a second attempt; a cancelled batch
    is not."""
    uid = _queue(client)
    iuid = _first_item(client, uid)
    client.post(f"{BASE}/{uid}/items/{iuid}/status",
                json={"state": "failed", "error": "proxy did not decode", "attempts": 1},
                headers=fleet_headers())
    assert ingest_batches.get_batch(conn, uid)["n_failed"] == 1
    r = client.post(f"{BASE}/{uid}/items/{iuid}/status", json={"state": "proxying"},
                    headers=fleet_headers())
    assert r.status_code == 200
    assert ingest_batches.get_batch(conn, uid)["n_failed"] == 0


def test_a_cancelled_item_cannot_be_restarted(client, conn):
    uid = _queue(client)
    iuid = _first_item(client, uid)
    client.post(f"{BASE}/{uid}/items/{iuid}/status", json={"state": "cancelled"},
                headers=fleet_headers())
    assert client.post(f"{BASE}/{uid}/items/{iuid}/status", json={"state": "proxying"},
                       headers=fleet_headers()).status_code == 400


def test_an_unknown_state_is_refused(client):
    uid = _queue(client)
    iuid = _first_item(client, uid)
    assert client.post(f"{BASE}/{uid}/items/{iuid}/status", json={"state": "vibing"},
                       headers=fleet_headers()).status_code == 400


def test_a_probe_lands_on_both_the_item_and_its_video_row(client, conn):
    uid = _queue(client)
    manifest = _claim(client, uid).json()["items"][0]
    client.post(f"{BASE}/{uid}/items/{manifest['uid']}/status", json={
        "state": "proxying",
        "probe": {"duration_s": 12.5, "fps": 25.0, "width": 3840, "height": 2160,
                  "codec": "hevc", "shot_date": "2026-08-01"}},
        headers=fleet_headers())
    item = ingest_batches.get_item(conn, uid, manifest["uid"])
    assert item["duration_s"] == 12.5 and item["codec"] == "hevc"
    video = conn.execute("SELECT * FROM videos WHERE id = ?",
                         (manifest["video_id"],)).fetchone()
    assert video["width"] == 3840 and video["fps"] == 25.0


def test_an_item_of_another_batch_is_404(client):
    uid_a = _queue(client)
    iuid = _first_item(client, uid_a)
    uid_b = _queue(client, share="Other")
    _claim(client, uid_b)
    assert client.post(f"{BASE}/{uid_b}/items/{iuid}/status", json={"state": "proxying"},
                       headers=fleet_headers()).status_code == 404


# --- result --------------------------------------------------------------------

CJK = "警方在廈門堵車現場處理事故"


def _result_body(**kw):
    body = {
        "segments": [{"t_start": 0.0, "t_end": 8.0,
                      "description": "Grey frigate moored at a pier",
                      "objects": ["warship", "pier"], "setting": "harbour",
                      "motion": "slow pan", "onscreen_text": CJK,
                      "onscreen_text_en": "police handle a jam"}],
        "themes": ["naval"], "quality_flags": ["shaky"],
        "category_hint": "military/naval", "model": "qwen3-vl-4b",
        "duration_s": 8.0, "fps": 24.0, "width": 1920, "height": 1080,
        "codec": "h264", "sprite_cell_w": 240, "sprite_cell_h": 136,
        "sprite_cols": 10, "sprite_cells": 24, "sprite_interval_s": 2.0,
    }
    body.update(kw)
    return body


def test_the_result_writes_segments_themes_flags_and_geometry(client, conn):
    uid = _queue(client)
    manifest = _claim(client, uid).json()["items"][0]
    r = client.post(f"{BASE}/{uid}/items/{manifest['uid']}/result",
                    json=_result_body(), headers=fleet_headers())
    assert r.status_code == 200, r.text
    vid = manifest["video_id"]

    seg = conn.execute("SELECT * FROM segments WHERE video_id = ?", (vid,)).fetchone()
    assert seg["objects"] == "warship, pier", "stored ', '-joined, as the indexer does"
    assert seg["onscreen_text"] == CJK
    assert [r["text"] for r in conn.execute(
        "SELECT text FROM themes WHERE video_id = ?", (vid,))] == ["naval"]
    assert [r["flag"] for r in conn.execute(
        "SELECT flag FROM quality_flags WHERE video_id = ?", (vid,))] == ["shaky"]

    video = conn.execute("SELECT * FROM videos WHERE id = ?", (vid,)).fetchone()
    assert video["category_hint"] == "military/naval"
    assert video["model"] == "qwen3-vl-4b" and video["indexed_at"]
    assert video["sprite_cell_h"] == 136 and video["sprite_cells"] == 24
    assert video["duration_s"] == 8.0
    assert video["status"] == "ingesting", (
        "described but not uploaded: the media is still on the editor's laptop")
    assert ingest_batches.get_item(conn, uid, manifest["uid"])["state"] == "indexed"


def test_the_result_computes_search_norm_which_the_ingest_api_never_could(client, conn):
    """PR-D. Without this the clip is in the archive, indexed, and unreachable
    by the words on its own screen: a two-character CJK term is below trigram's
    floor and unicode61 makes an unbroken CJK run one token."""
    pytest.importorskip("jieba")
    uid = _queue(client)
    manifest = _claim(client, uid).json()["items"][0]
    client.post(f"{BASE}/{uid}/items/{manifest['uid']}/result",
                json=_result_body(), headers=fleet_headers())
    norm = conn.execute("SELECT search_norm FROM segments WHERE video_id = ?",
                        (manifest["video_id"],)).fetchone()["search_norm"]
    assert norm, "search_norm was left empty -- the whole point of PR-D"
    assert "堵車" in norm.split(), "the two-character term is not a standalone token"
    assert "堵车" in norm.split(), "the Simplified variant did not cross-match"
    # The joined objects string, not its list repr: brackets and quotes in the
    # blob would be segmented as if they were words.
    assert "[" not in norm


def test_the_result_bumps_the_search_generation(client, conn):
    """The only thing that can tell the semantic/fuzzy caches about a re-index
    landing the same number of rows on the same rowids (KNOWN_BUGS R2)."""
    from app.db import read_search_generation

    uid = _queue(client)
    manifest = _claim(client, uid).json()["items"][0]
    before = read_search_generation(conn)
    client.post(f"{BASE}/{uid}/items/{manifest['uid']}/result",
                json=_result_body(), headers=fleet_headers())
    assert read_search_generation(conn) > before


def test_a_second_result_replaces_rather_than_doubles(client, conn):
    uid = _queue(client)
    manifest = _claim(client, uid).json()["items"][0]
    client.post(f"{BASE}/{uid}/items/{manifest['uid']}/result",
                json=_result_body(), headers=fleet_headers())
    # A retry is only legal from `failed`, which is the shape a real retry has.
    client.post(f"{BASE}/{uid}/items/{manifest['uid']}/status",
                json={"state": "failed", "error": "upload died"}, headers=fleet_headers())
    client.post(f"{BASE}/{uid}/items/{manifest['uid']}/result",
                json=_result_body(), headers=fleet_headers())
    assert conn.execute("SELECT COUNT(*) FROM segments WHERE video_id = ?",
                        (manifest["video_id"],)).fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM themes WHERE video_id = ?",
                        (manifest["video_id"],)).fetchone()[0] == 1


def test_a_result_for_an_unclaimed_batch_is_410(client, conn):
    uid = _queue(client)
    manifest = _claim(client, uid).json()["items"][0]
    ingest_batches.cancel(conn, uid, "root")
    assert client.post(f"{BASE}/{uid}/items/{manifest['uid']}/result",
                       json=_result_body(), headers=fleet_headers()).status_code == 410


# --- uploaded ------------------------------------------------------------------

def _browse_all(conn):
    """The browse path search_videos takes with no query text -- i.e. exactly
    what a click on a folder returns."""
    from app.search import search_videos

    return search_videos(conn, q="", category=None, flags=None, limit=50, offset=0)


def _stage(data_root, rel, size):
    path = data_root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)


def test_a_clip_goes_live_only_once_the_server_has_stat_ed_the_files(
        client, conn, data_root):
    uid = _queue(client)
    manifest = _claim(client, uid).json()["items"][0]
    client.post(f"{BASE}/{uid}/items/{manifest['uid']}/result", json=_result_body(),
                headers=fleet_headers())
    proxy = "Creators_Club/E2E/Proxy/A000.mp4"
    original = "Creators_Club/E2E/A000.MP4"
    vid = manifest["video_id"]
    for rel, size in ((proxy, 100), (original, 1234),
                      (f"posters/{vid}.jpg", 10), (f"sprites/{vid}.jpg", 20)):
        _stage(data_root, rel, size)

    r = client.post(f"{BASE}/{uid}/items/{manifest['uid']}/uploaded", json={
        "files": [{"rel": proxy, "size": 100}, {"rel": original, "size": 1234},
                  {"rel": f"posters/{vid}.jpg", "size": 10},
                  {"rel": f"sprites/{vid}.jpg", "size": 20}],
        "original_uploaded": True}, headers=fleet_headers())
    assert r.status_code == 200, r.text
    assert r.json()["live"] is True

    video = conn.execute("SELECT * FROM videos WHERE id = ?", (vid,)).fetchone()
    assert video["status"] == "indexed"
    assert video["archive_path"] == proxy
    assert video["original_path"] == original
    assert video["original_size_bytes"] == 1234
    assert video["original_verified_at"]
    assert ingest_batches.get_item(conn, uid, manifest["uid"])["state"] == "live"
    assert ingest_batches.get_batch(conn, uid)["n_live"] == 1


def test_a_missing_file_is_409_with_the_list_to_send_again(client, conn, data_root):
    """Which is what lets an interrupted rclone resume instead of restarting
    the clip."""
    uid = _queue(client)
    manifest = _claim(client, uid).json()["items"][0]
    _stage(data_root, f"posters/{manifest['video_id']}.jpg", 10)
    r = client.post(f"{BASE}/{uid}/items/{manifest['uid']}/uploaded", json={
        "files": [{"rel": f"posters/{manifest['video_id']}.jpg", "size": 10}],
        "original_uploaded": False}, headers=fleet_headers())
    assert r.status_code == 409
    assert r.json()["detail"]["missing"] == ["Creators_Club/E2E/Proxy/A000.mp4"]
    assert conn.execute("SELECT status FROM videos WHERE id = ?",
                        (manifest["video_id"],)).fetchone()["status"] == "ingesting"


def test_a_half_written_file_is_a_size_mismatch_not_a_live_clip(client, conn, data_root):
    uid = _queue(client)
    manifest = _claim(client, uid).json()["items"][0]
    proxy = "Creators_Club/E2E/Proxy/A000.mp4"
    _stage(data_root, proxy, 40)
    r = client.post(f"{BASE}/{uid}/items/{manifest['uid']}/uploaded",
                    json={"files": [{"rel": proxy, "size": 100}]},
                    headers=fleet_headers())
    assert r.status_code == 409
    assert r.json()["detail"]["size_mismatch"] == [
        {"rel": proxy, "declared": 100, "actual": 40}]


def test_the_proxy_is_required_even_if_the_companion_does_not_declare_it(
        client, conn, data_root):
    """The server verifies the path IT allocated, not the list it was handed --
    otherwise 'I uploaded nothing' would be a valid upload report."""
    uid = _queue(client)
    manifest = _claim(client, uid).json()["items"][0]
    r = client.post(f"{BASE}/{uid}/items/{manifest['uid']}/uploaded",
                    json={"files": []}, headers=fleet_headers())
    assert r.status_code == 409
    assert "Creators_Club/E2E/Proxy/A000.mp4" in r.json()["detail"]["missing"]


@pytest.mark.parametrize("rel", [
    "../../../etc/passwd", "/etc/passwd", "Creators_Club/../../x.mp4", "C:/Windows/x.mp4",
])
def test_a_path_outside_the_archive_root_is_400_not_409(client, conn, data_root, rel):
    """400, because a 409 invites a retry and no retry can fix a path that
    points outside the archive. It is a bug or an attack."""
    uid = _queue(client)
    manifest = _claim(client, uid).json()["items"][0]
    r = client.post(f"{BASE}/{uid}/items/{manifest['uid']}/uploaded",
                    json={"files": [{"rel": rel, "size": 1}]}, headers=fleet_headers())
    assert r.status_code == 400, rel
    assert r.json()["detail"]["reason"] == "outside_root"


def test_an_indexed_clip_becomes_browsable_only_after_the_upload(client, conn, data_root):
    """The end-to-end point of `status='ingesting'`: search and the folder tree
    must not offer a clip whose media is still on somebody's laptop."""
    uid = _queue(client)
    manifest = _claim(client, uid).json()["items"][0]
    client.post(f"{BASE}/{uid}/items/{manifest['uid']}/result", json=_result_body(),
                headers=fleet_headers())
    results, total = _browse_all(conn)
    assert total == 0, "an ingesting clip is not browsable"

    proxy = "Creators_Club/E2E/Proxy/A000.mp4"
    _stage(data_root, proxy, 100)
    client.post(f"{BASE}/{uid}/items/{manifest['uid']}/uploaded",
                json={"files": [{"rel": proxy, "size": 100}]}, headers=fleet_headers())
    results, total = _browse_all(conn)
    assert total == 1
    assert results[0]["video"]["id"] == manifest["video_id"]


# --- release -------------------------------------------------------------------

def test_release_done_with_a_failure_is_recorded_as_done_with_errors(client, conn):
    """The companion reports what it did; the SERVER decides what to call it,
    so a clip that failed cannot be summarised away."""
    items = [{"local_id": "a", "name": "A.MP4", "source": "upload"},
             {"local_id": "b", "name": "B.MP4", "source": "upload"}]
    uid = _queue(client, items=items)
    manifest = _claim(client, uid).json()["items"]
    client.post(f"{BASE}/{uid}/items/{manifest[0]['uid']}/status",
                json={"state": "failed", "error": "no decode"}, headers=fleet_headers())
    r = client.post(f"{BASE}/{uid}/release", json={"state": "done", "summary": {"ok": 1}},
                    headers=fleet_headers())
    assert r.status_code == 200
    assert r.json()["state"] == "done_with_errors"
    batch = ingest_batches.get_batch(conn, uid)
    assert batch["finished_at"] and batch["lease_expires_at"] is None
    assert json.loads(batch["error"]) == {"ok": 1}


def test_release_done_with_nothing_failed_is_plain_done(client, conn):
    uid = _queue(client)
    _claim(client, uid)
    assert client.post(f"{BASE}/{uid}/release", json={"state": "done"},
                       headers=fleet_headers()).json()["state"] == "done"


def test_a_cancelled_release_deletes_the_rows_that_never_got_media(
        client, conn, data_root):
    """`ingesting` rows have no media on the NAS and never will, so they are
    deleted rather than left as permanent invisible ghosts holding a name.
    `live` rows STAY -- somebody may already have cut with them (plan §6)."""
    items = [{"local_id": "a", "name": "A.MP4", "source": "upload"},
             {"local_id": "b", "name": "B.MP4", "source": "upload"}]
    uid = _queue(client, items=items)
    manifest = _claim(client, uid).json()["items"]
    proxy = "Creators_Club/E2E/Proxy/A.mp4"
    _stage(data_root, proxy, 7)
    client.post(f"{BASE}/{uid}/items/{manifest[0]['uid']}/uploaded",
                json={"files": [{"rel": proxy, "size": 7}]}, headers=fleet_headers())

    ingest_batches.cancel(conn, uid, "root")
    r = client.post(f"{BASE}/{uid}/release", json={"state": "cancelled"},
                    headers=fleet_headers())
    assert r.status_code == 200 and r.json()["state"] == "cancelled"

    ids = {row["id"] for row in conn.execute("SELECT id FROM videos")}
    assert manifest[0]["video_id"] in ids, "a live clip's row must survive a cancel"
    assert manifest[1]["video_id"] not in ids, "a half-made row must not linger"
    states = {i["uid"]: i["state"] for i in ingest_batches.list_items(conn, uid)}
    assert states[manifest[0]["uid"]] == "live"
    assert states[manifest[1]["uid"]] == "cancelled"


def test_a_cancelled_release_is_accepted_after_the_lease_was_taken_away(client, conn):
    """Cancelling is exactly the case where the dashboard has already expired
    the lease; refusing the release would leave the batch stuck in `running`
    with no machine behind it."""
    uid = _queue(client)
    _claim(client, uid)
    ingest_batches.cancel(conn, uid, "root")
    assert ingest_batches.get_batch(conn, uid)["lease_expires_at"] is None
    assert client.post(f"{BASE}/{uid}/release", json={"state": "cancelled"},
                       headers=fleet_headers()).status_code == 200


def test_another_editor_cannot_release_this_batch(client, conn):
    uid = _queue(client, editor="jsmith")
    _claim(client, uid)
    r = client.post(f"{BASE}/{uid}/release", json={"state": "done"},
                    headers=fleet_headers("kchen"))
    assert r.status_code == 410
    assert ingest_batches.get_batch(conn, uid)["state"] != "done"


def test_an_unknown_release_state_is_refused(client):
    uid = _queue(client)
    _claim(client, uid)
    assert client.post(f"{BASE}/{uid}/release", json={"state": "abandoned"},
                       headers=fleet_headers()).status_code == 422
