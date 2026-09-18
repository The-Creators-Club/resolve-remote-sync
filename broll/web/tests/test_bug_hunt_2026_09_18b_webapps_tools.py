"""The 2026-09-18b hunt: wire-1's server half (CR-290B).

The companion stages a clip live as soon as its PROXIES are on the NAS and
posts `/uploaded` a second time when the original finishes (plan section 5's
two stages, CR-288D). The first post used to write `live`, which is terminal:
an original whose upload then failed left a batch that said `done`, an item
nothing could retry, and a clip advertising an original the archive does not
hold. The first stage now writes `proxies_live` - visible, non-terminal,
retryable, and an error when the batch is released.

The bodies the companion posts are unchanged, so these drive the route exactly
as a 0.9.74 companion does.
"""
from __future__ import annotations

from pathlib import Path

from app import ingest_batches
from tests.conftest import fleet_headers
from tests.factories import insert_video  # noqa: F401  (fixture import parity)
from tests.test_fleet_ingest import (BASE, _claim, _queue, _result_body,
                                     _stage)

PROXY = "Creators_Club/E2E/Proxy/A000.mp4"
ORIGINAL = "Creators_Club/E2E/A000.MP4"


def _described(client, conn, data_root, *, with_original=False):
    """A claimed, described item whose proxies (and maybe original) are staged."""
    uid = _queue(client)
    manifest = _claim(client, uid).json()["items"][0]
    client.post(f"{BASE}/{uid}/items/{manifest['uid']}/result",
                json=_result_body(), headers=fleet_headers())
    vid = manifest["video_id"]
    staged = [(PROXY, 100), (f"posters/{vid}.jpg", 10), (f"sprites/{vid}.jpg", 20)]
    if with_original:
        staged.append((ORIGINAL, 1234))
    for rel, size in staged:
        _stage(data_root, rel, size)
    return uid, manifest


def _proxy_files(vid):
    return [{"rel": PROXY, "size": 100},
            {"rel": f"posters/{vid}.jpg", "size": 10},
            {"rel": f"sprites/{vid}.jpg", "size": 20}]


def _post_uploaded(client, uid, item_uid, files, original_uploaded):
    return client.post(f"{BASE}/{uid}/items/{item_uid}/uploaded",
                       json={"files": files,
                             "original_uploaded": original_uploaded},
                       headers=fleet_headers())


def _browse_ids(conn):
    """The ids a click on the folder returns, i.e. what the editor can see."""
    from app.search import search_videos

    results, _total = search_videos(conn, q="", category=None, flags=None,
                                    limit=50, offset=0)
    return [r["video"]["id"] for r in results]


def test_the_two_stages_end_live(client, conn, data_root):
    """Stage one publishes the clip; stage two is what makes the item done."""
    uid, manifest = _described(client, conn, data_root)
    vid = manifest["video_id"]

    first = _post_uploaded(client, uid, manifest["uid"], _proxy_files(vid), False)
    assert first.status_code == 200, first.text
    item = ingest_batches.get_item(conn, uid, manifest["uid"])
    assert item["state"] == "proxies_live"
    assert item["state"] not in ingest_batches.ITEM_TERMINAL
    # The whole point of the two stages: the editor can search it NOW.
    assert conn.execute("SELECT status FROM videos WHERE id = ?",
                        (vid,)).fetchone()["status"] == "indexed"
    assert vid in _browse_ids(conn)

    _stage(data_root, ORIGINAL, 1234)
    second = _post_uploaded(
        client, uid, manifest["uid"],
        _proxy_files(vid) + [{"rel": ORIGINAL, "size": 1234}], True)
    assert second.status_code == 200, second.text
    assert second.json()["live"] is True
    item = ingest_batches.get_item(conn, uid, manifest["uid"])
    assert item["state"] == "live"
    assert bool(item["original_uploaded"]) is True
    video = conn.execute("SELECT * FROM videos WHERE id = ?", (vid,)).fetchone()
    assert video["original_path"] == ORIGINAL
    assert ingest_batches.get_batch(conn, uid)["n_live"] == 1


def test_a_failed_original_leaves_a_visible_retryable_item(client, conn, data_root):
    """The wire-1 case: the original never lands, so the item is not done.

    It stays visible (its proxies ARE on the NAS), it is not terminal, the
    retry button can move it, and the batch ends `done_with_errors`.
    """
    uid, manifest = _described(client, conn, data_root)
    vid = manifest["video_id"]
    assert _post_uploaded(client, uid, manifest["uid"],
                          _proxy_files(vid), False).status_code == 200

    released = client.post(f"{BASE}/{uid}/release", json={"state": "done"},
                           headers=fleet_headers())
    assert released.status_code == 200, released.text
    assert released.json()["state"] == "done_with_errors", \
        "a batch that owes an original is not finished"

    # Still visible: the proxies are in the archive and an editor may already
    # have cut with them.
    assert conn.execute("SELECT status FROM videos WHERE id = ?",
                        (vid,)).fetchone()["status"] == "indexed"
    assert vid in _browse_ids(conn)

    # ...and retryable. `retry-failed` is the operator's one button.
    client.headers.update({"X-CCSync-User": "jsmith"})
    again = client.post(f"/api/ingest-batches/{uid}/retry-failed")
    assert again.status_code == 200, again.text
    assert again.json()["retried"] == 1
    assert ingest_batches.get_item(conn, uid, manifest["uid"])["state"] == "pending"
    assert ingest_batches.get_batch(conn, uid)["state"] == "queued"


def test_a_batch_whose_originals_all_landed_is_plain_done(client, conn, data_root):
    """The other direction: nothing owed, nothing invented."""
    uid, manifest = _described(client, conn, data_root, with_original=True)
    vid = manifest["video_id"]
    assert _post_uploaded(
        client, uid, manifest["uid"],
        _proxy_files(vid) + [{"rel": ORIGINAL, "size": 1234}], True).status_code == 200
    released = client.post(f"{BASE}/{uid}/release", json={"state": "done"},
                           headers=fleet_headers())
    assert released.json()["state"] == "done"


def test_an_older_companions_single_post_is_unchanged(client, conn, data_root):
    """A 0.9.74 companion posts once, with the original, and sees `live`
    exactly as it does today - the route learned a word, not a protocol."""
    uid, manifest = _described(client, conn, data_root, with_original=True)
    vid = manifest["video_id"]
    r = _post_uploaded(client, uid, manifest["uid"],
                       _proxy_files(vid) + [{"rel": ORIGINAL, "size": 1234}], True)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["live"] is True and body["archive_path"] == PROXY
    assert ingest_batches.get_item(conn, uid, manifest["uid"])["state"] == "live"


def test_the_panel_is_told_what_is_owed(client, conn, data_root):
    """`proxies_live` is jargon; the batch list carries the count the page
    turns into words and draws the retry button from."""
    uid, manifest = _described(client, conn, data_root)
    assert _post_uploaded(client, uid, manifest["uid"],
                          _proxy_files(manifest["video_id"]), False).status_code == 200
    client.headers.update({"X-CCSync-User": "jsmith"})
    listed = client.get("/api/ingest-batches?scope=mine").json()["batches"]
    row = next(b for b in listed if b["uid"] == uid)
    assert row["n_proxies_live"] == 1
    one = client.get(f"/api/ingest-batches/{uid}").json()["batch"]
    assert one["n_proxies_live"] == 1


def test_a_cancelled_batch_keeps_a_staged_item(client, conn, data_root):
    """Its media is in the archive, like a `live` one's: a cancel must not
    relabel it `cancelled` and delete the row an editor can already see."""
    uid, manifest = _described(client, conn, data_root)
    assert _post_uploaded(client, uid, manifest["uid"],
                          _proxy_files(manifest["video_id"]), False).status_code == 200
    r = client.post(f"{BASE}/{uid}/release", json={"state": "cancelled"},
                    headers=fleet_headers())
    assert r.status_code == 200, r.text
    assert ingest_batches.get_item(conn, uid, manifest["uid"])["state"] == "proxies_live"
    assert conn.execute("SELECT status FROM videos WHERE id = ?",
                        (manifest["video_id"],)).fetchone()["status"] == "indexed"


# --- the schema and the page ---------------------------------------------------

def test_the_stepped_migration_takes_the_new_word_and_keeps_the_rows(tmp_path):
    """Migration 013 REBUILDS `ingest_items` (SQLite cannot alter a CHECK), so
    what has to be proved is that nothing is lost on the way through and that
    the rebuilt table accepts the new state a v12 one refuses."""
    import sqlite3

    from app.db import CURRENT_SCHEMA_VERSION, ensure_schema

    path = tmp_path / "broll.db"
    ensure_schema(path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    with conn:
        conn.execute(
            "INSERT INTO ingest_batches (uid, editor, share, state, n_items, "
            "settings_json, created_at) "
            "VALUES ('b1', 'jsmith', 'E2E', 'running', 1, '{}', '2026-09-18')")
        conn.execute(
            "INSERT INTO ingest_items (uid, batch_uid, ord, orig_name, source, "
            "state, attempts, original_uploaded) "
            "VALUES ('i1', 'b1', 0, 'A000.MP4', 'upload', 'uploading', 2, 0)")
        conn.execute("PRAGMA user_version = 12")  # the version before wire-1
    conn.close()

    ensure_schema(path)

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    assert conn.execute("PRAGMA user_version").fetchone()[0] == CURRENT_SCHEMA_VERSION
    row = conn.execute("SELECT * FROM ingest_items WHERE uid = 'i1'").fetchone()
    assert row["batch_uid"] == "b1" and row["orig_name"] == "A000.MP4"
    assert row["state"] == "uploading" and row["attempts"] == 2
    with conn:
        conn.execute("UPDATE ingest_items SET state = 'proxies_live' WHERE uid = 'i1'")
    assert conn.execute(
        "SELECT state FROM ingest_items WHERE uid = 'i1'").fetchone()["state"] \
        == "proxies_live"
    # ...and the CHECK still refuses a word nothing writes.
    try:
        with conn:
            conn.execute("UPDATE ingest_items SET state = 'nonsense' WHERE uid = 'i1'")
    except sqlite3.IntegrityError:
        pass
    else:  # pragma: no cover - the constraint is the point of the migration
        raise AssertionError("the rebuilt table lost its state CHECK")
    conn.close()


def test_the_panel_says_original_still_owed_rather_than_the_enum():
    """`proxies_live` is the server's word; the editor's is a sentence
    (BROLL-22's rule, applied to the state this fix adds)."""
    js = (Path(__file__).resolve().parents[1] / "static" / "ingest.js").read_text(
        encoding="utf-8")
    assert '"proxies_live": "original still owed"' in js
    assert "still to send the original" in js, \
        "the counts line has to say what is owed"
    assert "finish the ${owed} still uploading" in js, \
        "a batch with nothing FAILED still needs its retry button"


# --- overseer-1: the insert object during the upload window --------------------

def _insert(client, video_id):
    r = client.get(f"/api/videos/{video_id}")
    assert r.status_code == 200, r.text
    return r.json()["video"]["insert"]


def test_the_insert_object_names_the_original_that_is_still_coming(
        client, conn, data_root):
    """overseer-1: the whole point of staging a clip live early is that an
    editor can CUT with it, and the companion decides what to import from
    `original_rel`. Null reads as "this clip has no original", so the preview
    was imported at the original's own path, permanently, and nothing upgraded
    when the real file landed hours later.
    """
    uid, manifest = _described(client, conn, data_root)
    vid = manifest["video_id"]
    assert _post_uploaded(client, uid, manifest["uid"],
                          _proxy_files(vid), False).status_code == 200

    obj = _insert(client, vid)
    assert obj["original_rel"] == ORIGINAL, \
        "the path mark_uploaded will store on the second post"
    assert obj["original_pending"] is True
    assert obj["preview_rel"] == PROXY and obj["known"] is True

    # ...and once it has landed, the ordinary answer with no flag.
    _stage(data_root, ORIGINAL, 1234)
    assert _post_uploaded(
        client, uid, manifest["uid"],
        _proxy_files(vid) + [{"rel": ORIGINAL, "size": 1234}], True).status_code == 200
    obj = _insert(client, vid)
    assert obj["original_rel"] == ORIGINAL
    assert "original_pending" not in obj


def test_a_batch_that_never_sends_originals_owes_nothing(client, conn, data_root):
    """`upload_originals: false` is a deliberate proxies-only ingest. Such a
    clip has no original coming, so the insert object must not name one - and
    its item is DONE on the one post it will ever get, or the batch would end
    `done_with_errors` for ever with a retry that cannot succeed."""
    uid = _queue(client, upload_originals=False)
    manifest = _claim(client, uid).json()["items"][0]
    client.post(f"{BASE}/{uid}/items/{manifest['uid']}/result",
                json=_result_body(), headers=fleet_headers())
    vid = manifest["video_id"]
    for rel, size in ((PROXY, 100), (f"posters/{vid}.jpg", 10),
                      (f"sprites/{vid}.jpg", 20)):
        _stage(data_root, rel, size)
    assert _post_uploaded(client, uid, manifest["uid"],
                          _proxy_files(vid), False).status_code == 200

    assert ingest_batches.get_item(conn, uid, manifest["uid"])["state"] == "live"
    released = client.post(f"{BASE}/{uid}/release", json={"state": "done"},
                           headers=fleet_headers())
    assert released.json()["state"] == "done"

    obj = _insert(client, vid)
    assert obj["original_rel"] is None
    assert "original_pending" not in obj


def test_a_clip_with_no_ingest_item_is_unchanged(client, conn, data_root):
    """Everything the indexer archived before any of this existed."""
    from tests.factories import insert_video

    vid = insert_video(conn, share="broll", rel_path="Creators_Club/Old/Proxy/B001.mp4",
                       status="indexed")
    conn.execute("UPDATE videos SET archive_path = ? WHERE id = ?",
                 ("Creators_Club/Old/Proxy/B001.mp4", vid))
    conn.commit()
    (data_root / "Creators_Club" / "Old" / "Proxy").mkdir(parents=True, exist_ok=True)
    (data_root / "Creators_Club" / "Old" / "Proxy" / "B001.mp4").write_bytes(b"x")

    obj = _insert(client, vid)
    assert obj["original_rel"] is None
    assert "original_pending" not in obj
