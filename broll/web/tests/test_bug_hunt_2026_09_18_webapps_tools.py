"""The 2026-09-18 hunt, the b-roll web app's half (webapps-tools, CR-286).

Every test here fails on the source before the fix beside it and passes after.
The ids are the hunt's (`docs/bug-hunt-2026-09-18/hunters/broll.md` and
`music.md`) and each one is cited at its code site.
"""
from __future__ import annotations

import unicodedata

from app import ingest_batches
from tests.factories import insert_video
from tests.test_fleet_ingest import _claim, _queue  # noqa: F401


def _detail_video(client, video_id):
    r = client.get(f"/api/videos/{video_id}")
    assert r.status_code == 200
    return r.json()["video"]


# --------------------------------------------------------------------------
# broll-3: the top-slot stem test is a comparison, so it goes through NFC
# --------------------------------------------------------------------------

def test_an_nfd_top_slot_is_still_found_beside_an_nfc_preview(client, conn,
                                                              data_root):
    """A Mac's rclone upload spells the name decomposed; the row holds it
    composed. Compared raw, the sibling is invisible and a clip that HAS an
    original degrades to a preview-only insert."""
    stem_nfc = unicodedata.normalize("NFC", "Matej Šimalčík A001")
    stem_nfd = unicodedata.normalize("NFD", stem_nfc)
    shoot = data_root / "Creators_Club" / "ff5" / "Day 1"
    (shoot / "Proxy").mkdir(parents=True, exist_ok=True)
    (shoot / f"{stem_nfd}.mov").write_bytes(b"top slot")
    (shoot / "Proxy" / f"{stem_nfc}.mp4").write_bytes(b"preview")

    vid = insert_video(
        conn, share="ff5", rel_path=f"x/{stem_nfc}.mov",
        archive_path=f"Creators_Club/ff5/Day 1/Proxy/{stem_nfc}.mp4")

    insert = _detail_video(client, vid)["insert"]

    assert insert["original_rel"] is not None, \
        "the NFD sibling was invisible to the stem test"
    assert insert["original_rel"].endswith(".mov")


# --------------------------------------------------------------------------
# broll-4: a preview must never be advertised as its own editing proxy
# --------------------------------------------------------------------------

def test_a_mov_preview_is_not_its_own_editing_proxy(client, conn, data_root):
    """`build_archive.preview_source` falls back to the TOP SLOT for an
    audio-only clip and keeps its suffix, so the preview can be `.mov` -- the
    exact name this route derives the editing proxy under."""
    shoot = data_root / "Creators_Club" / "ff5" / "Day 2"
    (shoot / "Proxy").mkdir(parents=True, exist_ok=True)
    (shoot / "Proxy" / "talk.mov").write_bytes(b"preview that is also the top slot")

    vid = insert_video(
        conn, share="ff5", rel_path="x/talk.mov",
        archive_path="Creators_Club/ff5/Day 2/Proxy/talk.mov")

    insert = _detail_video(client, vid)["insert"]

    assert insert["preview_rel"] == "Creators_Club/ff5/Day 2/Proxy/talk.mov"
    assert insert["edit_proxy_rel"] is None, \
        "the preview was advertised as its own editing proxy"


# --------------------------------------------------------------------------
# broll-5: a zero-byte file is a dead transfer, whichever slot it is
# --------------------------------------------------------------------------

def _uploaded(client, uid, item_uid, files, editor="jsmith",
              machine="EDIT-01"):
    from tests.conftest import fleet_headers
    return client.post(
        f"/api/fleet/ingest/batches/{uid}/items/{item_uid}/uploaded",
        json={"files": files},
        headers=fleet_headers(editor, machine))


def test_a_zero_byte_preview_does_not_take_the_clip_live(client, conn,
                                                         data_root):
    uid = _queue(client)
    r = _claim(client, uid)
    assert r.status_code == 200, r.text
    item = r.json()["items"][0]
    rel = item["archive_dir"] + "/Proxy/" + item["archive_stem"] + ".mp4"
    path = data_root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")

    # No declared size: the queue entry was rebuilt after a restart, which is
    # the shape that made the size check unreachable.
    r = _uploaded(client, uid, item["uid"], [{"rel": rel}])

    assert r.status_code == 409, r.text
    body = r.json()["detail"]
    assert body["reason"] == "not_uploaded"
    assert rel in body["missing"]


def test_a_preview_with_bytes_still_goes_live(client, conn, data_root):
    """The other half: the zero-byte rule must not become "a size must be
    declared", or a rebuilt queue entry 409-loops for ever."""
    uid = _queue(client)
    r = _claim(client, uid)
    item = r.json()["items"][0]
    rel = item["archive_dir"] + "/Proxy/" + item["archive_stem"] + ".mp4"
    path = data_root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"a real preview")

    r = _uploaded(client, uid, item["uid"], [{"rel": rel}])

    # It gets past the file checks (this item has posted no result yet, which
    # is a different refusal); what must not happen is "not_uploaded".
    if r.status_code != 200:
        assert r.json()["detail"]["reason"] != "not_uploaded", r.text


# --------------------------------------------------------------------------
# music-1's b-roll twin: a cancel racing lease expiry
# --------------------------------------------------------------------------

def test_a_cancel_after_the_lease_died_finalises_the_batch(client, conn):
    uid = _queue(client)
    assert _claim(client, uid).status_code == 200
    conn.execute("UPDATE ingest_batches SET state = 'running', "
                 "lease_expires_at = '2001-01-01T00:00:00+00:00' "
                 "WHERE uid = ?", (uid,))
    conn.commit()

    r = client.post(f"/api/ingest-batches/{uid}/cancel",
                    headers={"X-CCSync-User": "jsmith"})

    assert r.status_code == 200, r.text
    assert r.json()["state"] == "cancelled", r.json()
    batch = ingest_batches.get_batch(conn, uid)
    assert not (batch["state"] == "running"
                and batch["lease_expires_at"] is None), \
        "the batch is unreachable by any sweep and unclaimable for ever"
