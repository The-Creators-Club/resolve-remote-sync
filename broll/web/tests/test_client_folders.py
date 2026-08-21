"""Client folders: curate clips, hand out a link, let a stranger preview them.

docs/CLIENT_FOLDERS.md, 2026-08-18. Three parties and three doors:

  * the EDITOR (session identity stamped by the dashboard gate) curates
    through /api/client-folders -- app/routes_client_folders.py;
  * the CLIENT (no account, no cookie, a 128-bit token in the URL) previews
    through /share/{token}/... -- app/routes_share.py;
  * the OPERATOR publishes exactly one path prefix past the tailnet, so the
    viewer page must need nothing outside it.

What these pin, in order of how much it would hurt to lose:

  1. the public routes reveal nothing but the folder's own clips: no path, no
     share, no other folder, no clip that is not in this one -- and a revoked
     or expired link is the same 404 as a link that never existed;
  2. the ledger is a SEPARATE database file, so an index publish that
     replaces broll.db cannot take the folders with it;
  3. the viewer page and its assets are all reachable under the share
     prefix, mounted, with document-relative URLs;
  4. the editor's API needs the identity stamp, and the public base is
     admin-only;
  5. the classic scripts index.html and share.html load declare no name
     twice (a duplicate top-level `const` is a SyntaxError that blanks the
     page -- test_ingest_ui.py's lesson, extended to the two new files).
"""
from __future__ import annotations

import re
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import client_folders as cf
from app.main import app as broll_app
from tests.factories import insert_segment, insert_video

STATIC = Path(__file__).resolve().parent.parent / "static"


# --- fixtures ---------------------------------------------------------------------

@pytest.fixture()
def seeded(conn, data_root):
    """Two clips with a poster, a sprite and a proxy each, plus one that is in
    the index but will NOT be put in any folder."""
    ids = {}
    for name in ("harbor", "drone", "outsider"):
        vid = insert_video(conn, share="ff3", rel_path=f"day1/{name}.mov",
                           duration_s=42.0, width=1920, height=1080, fps=25.0,
                           shot_date="2026-05-03")
        insert_segment(conn, vid, t_start=0, t_end=10, description=f"{name} wide",
                       setting="harbour")
        ids[name] = vid
        for sub, ext, body in (("posters", "jpg", b"\xff\xd8\xff\xd9"),
                               ("sprites", "jpg", b"\xff\xd8\xff\xd9"),
                               ("proxies", "mp4", b"\x00\x00\x00\x18ftypmp42" + b"x" * 64)):
            d = data_root / sub
            d.mkdir(parents=True, exist_ok=True)
            (d / f"{vid}.{ext}").write_bytes(body)
    return ids


def _create(client, title="For Acme", **extra):
    r = client.post("api/client-folders", json={"title": title, **extra})
    assert r.status_code == 201, r.text
    return r.json()


def _add(client, folder_id, *video_ids):
    r = client.post(f"api/client-folders/{folder_id}/items", json={"video_ids": list(video_ids)})
    assert r.status_code == 200, r.text
    return r.json()


# --- 1. the public routes -----------------------------------------------------------

def test_a_client_sees_the_folder_and_only_the_folder(as_editor, seeded):
    folder = _create(as_editor, description="Harbour and drone shots",
                     contact="sales@example.com")
    _add(as_editor, folder["id"], seeded["harbor"], seeded["drone"])
    tok = folder["token"]

    # No session, no headers: a stranger with the link.
    anon = TestClient(broll_app)
    r = anon.get(f"/share/{tok}/api/folder")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["title"] == "For Acme"
    assert body["contact"] == "sales@example.com"
    assert [i["name"] for i in body["items"]] == ["harbor", "drone"]
    assert body["n_items"] == 2
    # The allow-list: what a buyer needs and nothing about our filesystem.
    item = body["items"][0]
    assert set(item) == set(cf.PUBLIC_VIDEO_COLUMNS) | {"name", "note"}
    text = r.text
    for secret in ("rel_path", "archive_path", "original_path", "day1/", "ff3", "share"):
        assert secret not in text, f"{secret!r} leaked to the public folder payload"
    # Headers a page for strangers carries.
    assert "noindex" in r.headers["x-robots-tag"]
    assert r.headers["referrer-policy"] == "no-referrer"


def test_the_public_media_routes_serve_members_and_404_everything_else(as_editor, seeded):
    folder = _create(as_editor)
    _add(as_editor, folder["id"], seeded["harbor"])
    tok = folder["token"]
    anon = TestClient(broll_app)
    member, outsider = seeded["harbor"], seeded["outsider"]

    for kind, ext in (("poster", "jpg"), ("sprite", "jpg"), ("proxy", "mp4")):
        ok = anon.get(f"/share/{tok}/media/{kind}/{member}.{ext}")
        assert ok.status_code == 200, (kind, ok.text)
        assert ok.headers["cache-control"].startswith("private")
        no = anon.get(f"/share/{tok}/media/{kind}/{outsider}.{ext}")
        assert no.status_code == 404, f"{kind}: a clip outside the folder was served"
    # Range still works through the extra gate (a <video> seeks with it).
    r = anon.get(f"/share/{tok}/media/proxy/{member}.mp4", headers={"Range": "bytes=0-3"})
    assert r.status_code == 206
    assert r.content == b"\x00\x00\x00\x18"
    # The clip detail is gated the same way.
    assert anon.get(f"/share/{tok}/api/videos/{member}").status_code == 200
    assert anon.get(f"/share/{tok}/api/videos/{outsider}").status_code == 404


def test_the_clip_detail_carries_segments_and_the_note_but_no_transcript(as_editor, seeded, conn):
    folder = _create(as_editor)
    _add(as_editor, folder["id"], seeded["harbor"])
    as_editor.put(f"api/client-folders/{folder['id']}/items/{seeded['harbor']}/note",
                  json={"note": "4K master available"})
    conn.execute("INSERT INTO transcript_segments (video_id, t_start, t_end, text) VALUES (?, 0, 3, ?)",
                 (seeded["harbor"], "secret spoken words"))
    conn.commit()
    anon = TestClient(broll_app)
    r = anon.get(f"/share/{folder['token']}/api/videos/{seeded['harbor']}")
    assert r.status_code == 200
    body = r.json()
    assert body["note"] == "4K master available"
    assert body["segments"][0]["description"] == "harbor wide"
    assert body["video"]["name"] == "harbor"
    assert "rel_path" not in body["video"]
    assert "secret spoken words" not in r.text
    assert "transcript" not in body


def test_revoked_expired_unknown_and_malformed_links_are_one_and_the_same_404(as_editor, seeded):
    folder = _create(as_editor)
    _add(as_editor, folder["id"], seeded["harbor"])
    tok = folder["token"]
    anon = TestClient(broll_app)
    media = f"/share/{tok}/media/poster/{seeded['harbor']}.jpg"
    assert anon.get(media).status_code == 200

    # Revoke: dead at once, on the page, the API and the media alike.
    r = as_editor.post(f"api/client-folders/{folder['id']}/revoke")
    assert r.status_code == 200 and r.json()["status"] == "revoked"
    assert anon.get(f"/share/{tok}/api/folder").status_code == 404
    assert anon.get(media).status_code == 404
    page = anon.get(f"/share/{tok}/")
    assert page.status_code == 404
    assert "not available" in page.text.lower()
    assert "<html" in page.text, "the PAGE route answers a person with a page, not JSON"

    # Reactivate: alive again.
    as_editor.post(f"api/client-folders/{folder['id']}/reactivate")
    assert anon.get(media).status_code == 200

    # Expire: same as revoked, without anyone pressing anything.
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    r = as_editor.patch(f"api/client-folders/{folder['id']}", json={"expires_at": past})
    assert r.json()["status"] == "expired"
    assert anon.get(media).status_code == 404
    # Clearing the expiry (an explicit null) brings it back.
    r = as_editor.patch(f"api/client-folders/{folder['id']}", json={"expires_at": None})
    assert r.json()["status"] == "live" and r.json()["expires_at"] is None
    assert anon.get(media).status_code == 200

    # Unknown and malformed: no different from the outside.
    assert anon.get("/share/AAAAAAAAAAAAAAAAAAAAAA/api/folder").status_code == 404
    assert anon.get("/share/not%20a%20token/api/folder").status_code == 404
    assert anon.get("/share/../api/search").status_code in (404, 200)  # never a folder


def test_rotating_the_link_kills_the_old_one_immediately(as_editor, seeded):
    folder = _create(as_editor)
    _add(as_editor, folder["id"], seeded["harbor"])
    old = folder["token"]
    anon = TestClient(broll_app)
    assert anon.get(f"/share/{old}/api/folder").status_code == 200
    r = as_editor.post(f"api/client-folders/{folder['id']}/rotate")
    new = r.json()["token"]
    assert new != old and cf.valid_token(new)
    assert anon.get(f"/share/{old}/api/folder").status_code == 404
    assert anon.get(f"/share/{new}/api/folder").status_code == 200


def test_opening_the_folder_counts_a_view_that_the_editor_can_see(as_editor, seeded):
    folder = _create(as_editor)
    anon = TestClient(broll_app)
    anon.get(f"/share/{folder['token']}/api/folder")
    anon.get(f"/share/{folder['token']}/api/folder")
    r = as_editor.get(f"api/client-folders/{folder['id']}")
    assert r.json()["view_count"] == 2
    assert r.json()["last_viewed_at"]


def test_the_page_route_redirects_to_the_trailing_slash_form(as_editor, seeded):
    """Every URL on the viewer page is document-relative, so it MUST be served
    at .../<token>/ -- one level up and `api/folder` would resolve to
    /share/api/folder. A relative Location, so it works through any prefix."""
    folder = _create(as_editor)
    anon = TestClient(broll_app)
    r = anon.get(f"/share/{folder['token']}", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == f"{folder['token']}/"
    page = anon.get(f"/share/{folder['token']}/")
    assert page.status_code == 200
    assert 'src="../assets/share.js"' in page.text


# --- 2. the ledger is its own file ---------------------------------------------------

def test_the_ledger_is_a_separate_database_that_survives_replacing_the_index(as_editor, seeded, data_root, conn):
    """server/publish_db.py swaps broll.db wholesale for a freshly built index.
    The client folders must not be in the file it swaps."""
    folder = _create(as_editor, title="Survivor")
    _add(as_editor, folder["id"], seeded["harbor"])
    assert (data_root / "client_shares.db").is_file()
    index_tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert not any(t.startswith("client_") for t in index_tables), (
        "client folder tables leaked into broll.db, where an index publish would drop them")

    # "Publish": a rebuilt index in which the same file has a NEW id.
    conn.execute("DELETE FROM videos")
    conn.commit()
    new_id = insert_video(conn, id=777, share="ff3", rel_path="day1/harbor.mov", duration_s=42.0)
    assert new_id != seeded["harbor"]
    (data_root / "posters" / f"{new_id}.jpg").write_bytes(b"\xff\xd8\xff\xd9")

    r = as_editor.get(f"api/client-folders/{folder['id']}")
    assert r.status_code == 200
    items = r.json()["items"]
    assert [i["name"] for i in items] == ["harbor"]
    assert items[0]["id"] == new_id, "re-resolved by (share, rel_path), not lost"
    anon = TestClient(broll_app)
    body = anon.get(f"/share/{folder['token']}/api/folder").json()
    assert body["items"][0]["id"] == new_id
    assert anon.get(f"/share/{folder['token']}/media/poster/{new_id}.jpg").status_code == 200


def test_a_rebuild_that_gives_the_old_id_to_another_clip_serves_none_of_it(
        as_editor, seeded, conn, data_root):
    """broll-1, 2026-08-21. The test above rebuilds with ids that no longer
    exist, which 404s by accident. A real rebuild REUSES the low numbers: the
    curated clip moves up, and its old id lands on some other clip. The page
    redraws correctly either way (resolve_items re-resolves by name), so the
    media and detail routes must not answer on the bare stored id either.
    """
    folder = _create(as_editor, title="Acme")
    _add(as_editor, folder["id"], seeded["harbor"])
    old_id, tok = seeded["harbor"], folder["token"]

    conn.execute("DELETE FROM videos")
    conn.commit()
    # The rebuilt index: harbor.mov renumbered, and its old id inherited by a
    # clip nobody curated into anything.
    new_id = insert_video(conn, id=4120, share="ff3", rel_path="day1/harbor.mov",
                          duration_s=42.0)
    intruder = insert_video(conn, id=old_id, share="broll",
                            rel_path="Downloads/politics/protest.mp4", duration_s=9.0)
    insert_segment(conn, intruder, t_start=0, t_end=9,
                   description="a protest nobody licensed", setting="street")
    for sub, ext, blob in (("posters", "jpg", b"\xff\xd8\xff\xd9"),
                           ("sprites", "jpg", b"\xff\xd8\xff\xd9"),
                           ("proxies", "mp4", b"\x00\x00\x00\x18ftypmp42" + b"x" * 64)):
        (data_root / sub / f"{new_id}.{ext}").write_bytes(blob)

    anon = TestClient(broll_app)
    # The folder still draws, under the clip's NEW id.
    body = anon.get(f"/share/{tok}/api/folder").json()
    assert [i["id"] for i in body["items"]] == [new_id]
    assert anon.get(f"/share/{tok}/api/videos/{new_id}").status_code == 200
    for kind, ext in (("poster", "jpg"), ("sprite", "jpg"), ("proxy", "mp4")):
        assert anon.get(f"/share/{tok}/media/{kind}/{new_id}.{ext}").status_code == 200

    # The old id is now somebody else's footage. The files for it are still on
    # disk (they were harbor's), so only the membership check stands between
    # the token holder and a clip that was never shared with them.
    detail = anon.get(f"/share/{tok}/api/videos/{old_id}")
    assert detail.status_code == 404, "an uncurated clip's segments went out"
    assert "protest" not in detail.text
    for kind, ext in (("poster", "jpg"), ("sprite", "jpg"), ("proxy", "mp4")):
        r = anon.get(f"/share/{tok}/media/{kind}/{old_id}.{ext}")
        assert r.status_code == 404, f"{kind}: an uncurated clip was served"


def test_a_rebuild_leaves_the_tick_on_and_a_second_add_makes_no_duplicate(
        as_editor, seeded, conn):
    """broll-4, 2026-08-21. The popover's ticks and add_items both used to
    compare the raw stored id, so after a renumbering rebuild a clip that IS
    in the folder showed as un-ticked and "+" filed it a second time --
    UNIQUE (folder_id, video_id) does not catch a second row with a new id --
    and the client's page then listed the clip twice."""
    folder = _create(as_editor)
    _add(as_editor, folder["id"], seeded["harbor"])
    conn.execute("DELETE FROM videos WHERE id = ?", (seeded["harbor"],))
    new_id = insert_video(conn, id=4120, share="ff3", rel_path="day1/harbor.mov",
                          duration_s=42.0)
    conn.commit()

    r = as_editor.get("api/client-folders", params={"video_id": new_id})
    assert r.status_code == 200, r.text
    mine = [f for f in r.json()["folders"] if f["id"] == folder["id"]]
    assert mine and mine[0]["contains"] is True, "the clip IS in the folder"

    again = _add(as_editor, folder["id"], new_id)
    assert again["added"] == [] and again["already"] == [new_id]
    items = as_editor.get(f"api/client-folders/{folder['id']}").json()["items"]
    assert [i["name"] for i in items] == ["harbor"]
    theirs = TestClient(broll_app).get(f"/share/{folder['token']}/api/folder").json()["items"]
    assert [i["id"] for i in theirs] == [new_id]


def test_a_folder_that_already_holds_the_same_clip_twice_draws_it_once(
        as_editor, seeded, conn):
    """The folders written before broll-4 was fixed: two rows, one clip. The
    second row cannot be made any more, but the ones that exist must not show
    the client a duplicate card."""
    folder = _create(as_editor)
    _add(as_editor, folder["id"], seeded["harbor"])
    conn.execute("DELETE FROM videos WHERE id = ?", (seeded["harbor"],))
    new_id = insert_video(conn, id=4120, share="ff3", rel_path="day1/harbor.mov",
                          duration_s=42.0)
    conn.commit()
    shares = cf.open_connection()
    shares.execute(
        "INSERT INTO client_folder_items (folder_id, video_id, share, rel_path, ord, "
        "added_by, added_at) VALUES (?, ?, 'ff3', 'day1/harbor.mov', 9, 'jsmith', ?)",
        (folder["id"], new_id, cf.now_iso()))
    shares.commit()

    theirs = TestClient(broll_app).get(
        f"/share/{folder['token']}/api/folder").json()
    assert [i["id"] for i in theirs["items"]] == [new_id]
    assert theirs["n_items"] == 1


def test_a_clip_that_left_the_index_is_reported_to_the_editor_and_hidden_from_the_client(as_editor, seeded, conn):
    folder = _create(as_editor)
    _add(as_editor, folder["id"], seeded["harbor"], seeded["drone"])
    conn.execute("DELETE FROM videos WHERE id = ?", (seeded["drone"],))
    conn.commit()
    mine = as_editor.get(f"api/client-folders/{folder['id']}").json()["items"]
    assert [i.get("missing", False) for i in mine] == [False, True]
    theirs = TestClient(broll_app).get(f"/share/{folder['token']}/api/folder").json()["items"]
    assert [i["name"] for i in theirs] == ["harbor"]


# --- 3. mounted under a prefix -------------------------------------------------------

@pytest.fixture()
def mounted(data_root, conn):
    parent = FastAPI()
    parent.mount("/broll", broll_app)
    with TestClient(parent) as c:
        yield c


def test_the_viewer_and_everything_it_needs_answer_under_the_share_prefix(mounted, seeded, conn):
    """The one prefix an operator publishes past the tailnet is /broll/share.
    The page, its assets, its API and its media all live under it."""
    cf.ensure_schema()
    folder = cf.create_folder(cf.open_connection(), title="Mounted", created_by="t")
    cf.add_items(cf.open_connection(), conn, folder["id"], [seeded["harbor"]], added_by="t")
    tok = folder["token"]
    for path in (f"/broll/share/{tok}/", f"/broll/share/{tok}/api/folder",
                 f"/broll/share/{tok}/api/videos/{seeded['harbor']}",
                 f"/broll/share/{tok}/media/poster/{seeded['harbor']}.jpg",
                 "/broll/share/assets/share.js", "/broll/share/assets/share.css",
                 "/broll/share/assets/sprite.js", "/broll/share/assets/style.css",
                 "/broll/share/assets/favicon.svg"):
        r = mounted.get(path)
        assert r.status_code == 200, f"{path} -> {r.status_code}"
    r = mounted.get(f"/broll/share/{tok}", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == f"{tok}/"


def test_the_share_assets_mount_carries_the_viewer_and_nothing_else(mounted, seeded):
    """broll-3, 2026-08-21. /broll/share is the ONE prefix an operator
    publishes past the tailnet with a Funnel, and the mount behind it points
    at the whole static tree -- which is also where the editors' SPA lives.
    An anonymous internet client must not be able to read app.js's API surface
    off it."""
    for name in ("app.js", "index.html", "ingest.js", "clientfolders.js"):
        r = mounted.get(f"/broll/share/assets/{name}")
        assert r.status_code == 404, f"{name} is served past the tailnet"
    # ...while the viewer's own files still answer (the test above pins the
    # rest of the page); the editors' door keeps serving them under /static.
    assert mounted.get("/broll/share/assets/brand_mark.png").status_code == 200
    assert mounted.get("/broll/static/app.js").status_code == 200


def test_the_viewer_page_and_script_use_only_document_relative_urls():
    """Under /broll/share/<token>/ a leading slash would leave the prefix; an
    absolute origin would leave the host. The SPA's rule, re-pinned here for
    the two new files (test_mounted_prefix.py covers the SPA's own)."""
    for name in ("share.html", "share.js", "share.css", "clientfolders.js"):
        text = (STATIC / name).read_text(encoding="utf-8")
        for m in re.finditer(r"""(?:src|href|url\(|fetch\(|fetchJson\()\s*=?\s*["'`]?(/[a-z][^"'`)\s]*)""", text):
            pytest.fail(f"{name}: root-relative URL {m.group(1)!r}")
        assert not re.search(r"https?://[\w.:@-]+", text), f"{name} names an absolute origin"
    share_js = (STATIC / "share.js").read_text(encoding="utf-8")
    for needle in ('fetchJson("api/folder")', "`api/videos/${", "`media/poster/${",
                   "url(media/sprite/${", "`media/proxy/${"):
        assert needle in share_js, needle
    html = (STATIC / "share.html").read_text(encoding="utf-8")
    assert 'href="../assets/style.css"' in html and 'src="../assets/sprite.js"' in html


# --- 4. the editor's API ---------------------------------------------------------------

def test_the_editor_api_needs_the_identity_stamp(client, seeded):
    """No X-CCSync-User (the dashboard gate's stamp) = 401, on every verb."""
    assert client.get("api/client-folders").status_code == 401
    assert client.post("api/client-folders", json={"title": "x"}).status_code == 401
    assert client.get("api/client-folders/1").status_code == 401


def test_the_public_base_is_admin_only_and_must_be_an_origin(as_editor, as_admin):
    """as_editor and as_admin share one TestClient; the last fixture's headers
    win, so this test drives the header by hand."""
    c = as_admin
    editor = {"X-CCSync-User": "jsmith", "X-CCSync-Admin": ""}
    admin = {"X-CCSync-User": "root", "X-CCSync-Admin": "1"}
    r = c.put("api/client-folders/settings", json={"public_base_url": "https://nas.example.ts.net:8443"},
              headers=editor)
    assert r.status_code == 403
    for bad in ("nas.example.ts.net", "https://nas.example.ts.net/broll", "ftp://x", "https://a b"):
        r = c.put("api/client-folders/settings", json={"public_base_url": bad}, headers=admin)
        assert r.status_code == 422, bad
    r = c.put("api/client-folders/settings", json={"public_base_url": "https://nas.example.ts.net:8443/"},
              headers=admin)
    assert r.status_code == 200 and r.json()["public_base_url"] == "https://nas.example.ts.net:8443"
    listing = c.get("api/client-folders", headers=editor).json()
    assert listing["public_base_url"] == "https://nas.example.ts.net:8443"
    assert listing["is_admin"] is False
    assert listing["share_path"] == "/share/"


def test_curation_round_trip(as_editor, seeded):
    folder = _create(as_editor, title="  Acme  ", contact="  ")
    assert folder["title"] == "Acme" and folder["status"] == "live"
    assert cf.valid_token(folder["token"]) and len(folder["token"]) == 22
    assert folder["share_path"] == f"/share/{folder['token']}/"

    # Adding is idempotent; the second press is not an error.
    r = _add(as_editor, folder["id"], seeded["harbor"], seeded["drone"])
    assert r == {"added": [seeded["harbor"], seeded["drone"]], "already": [], "n_items": 2}
    r = _add(as_editor, folder["id"], seeded["harbor"])
    assert r["added"] == [] and r["already"] == [seeded["harbor"]]
    # A clip that is not in the index is refused, by name.
    r = as_editor.post(f"api/client-folders/{folder['id']}/items", json={"video_ids": [999999]})
    assert r.status_code == 422 and "999999" in r.json()["detail"]

    # The membership ticks the card popover draws.
    listing = as_editor.get(f"api/client-folders?video_id={seeded['harbor']}").json()
    assert listing["folders"][0]["contains"] is True
    listing = as_editor.get(f"api/client-folders?video_id={seeded['outsider']}").json()
    assert listing["folders"][0]["contains"] is False

    # Reorder, caption, remove.
    r = as_editor.put(f"api/client-folders/{folder['id']}/order",
                      json={"video_ids": [seeded["drone"], seeded["harbor"], 424242]})
    assert r.status_code == 200
    items = as_editor.get(f"api/client-folders/{folder['id']}").json()["items"]
    assert [i["name"] for i in items] == ["drone", "harbor"]
    r = as_editor.put(f"api/client-folders/{folder['id']}/items/{seeded['drone']}/note",
                      json={"note": " golden hour "})
    assert r.status_code == 200
    r = as_editor.delete(f"api/client-folders/{folder['id']}/items/{seeded['harbor']}")
    assert r.status_code == 204
    detail = as_editor.get(f"api/client-folders/{folder['id']}").json()
    assert [(i["name"], i["note"]) for i in detail["items"]] == [("drone", "golden hour")]
    assert detail["n_items"] == 1

    # Update details; a bad expiry is refused, a title cannot be blanked.
    r = as_editor.patch(f"api/client-folders/{folder['id']}",
                        json={"description": "Two shots", "expires_at": "yesterday-ish"})
    assert r.status_code == 422
    r = as_editor.patch(f"api/client-folders/{folder['id']}", json={"title": "  "})
    assert r.status_code == 422
    future = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    r = as_editor.patch(f"api/client-folders/{folder['id']}",
                        json={"description": "Two shots", "expires_at": future})
    assert r.status_code == 200 and r.json()["status"] == "live"
    assert r.json()["expires_at"].endswith("+00:00")

    # Delete takes the items with it and the link dies.
    tok = folder["token"]
    assert as_editor.delete(f"api/client-folders/{folder['id']}").status_code == 204
    assert as_editor.get(f"api/client-folders/{folder['id']}").status_code == 404
    assert TestClient(broll_app).get(f"/share/{tok}/api/folder").status_code == 404
    with cf.open_connection() as ledger:
        assert ledger.execute("SELECT COUNT(*) FROM client_folder_items").fetchone()[0] == 0


def test_every_editor_sees_every_folder(as_editor, seeded):
    """A client folder is the studio's: a colleague must be able to find and
    fix the one somebody else sent out."""
    _create(as_editor, title="Made by jsmith")
    other = as_editor
    other.headers.update({"X-CCSync-User": "someone-else"})
    listing = other.get("api/client-folders").json()
    assert [f["title"] for f in listing["folders"]] == ["Made by jsmith"]
    assert listing["folders"][0]["created_by"] == "jsmith"
    assert other.post(f"api/client-folders/{listing['folders'][0]['id']}/revoke").status_code == 200


def test_the_folder_has_a_size_limit(as_editor, conn, monkeypatch):
    monkeypatch.setattr(cf, "MAX_ITEMS", 2)
    ids = [insert_video(conn, share="s", rel_path=f"c{i}.mov") for i in range(3)]
    folder = _create(as_editor)
    _add(as_editor, folder["id"], ids[0], ids[1])
    r = as_editor.post(f"api/client-folders/{folder['id']}/items", json={"video_ids": [ids[2]]})
    assert r.status_code == 422 and "at most 2" in r.json()["detail"]


# --- 5. the scripts -------------------------------------------------------------------------

_TOP_LEVEL = re.compile(
    r"^(?:function\s+([A-Za-z_$][\w$]*)"
    r"|(?:const|let|var)\s+([A-Za-z_$][\w$]*))", re.M)


def _top_level_names(name: str) -> set[str]:
    text = (STATIC / name).read_text(encoding="utf-8")
    return {m.group(1) or m.group(2) for m in _TOP_LEVEL.finditer(text)}


@pytest.mark.parametrize("a,b", [
    # index.html loads these four; every pair shares one global scope.
    ("sprite.js", "app.js"), ("sprite.js", "ingest.js"), ("sprite.js", "clientfolders.js"),
    ("app.js", "clientfolders.js"), ("ingest.js", "clientfolders.js"),
    # share.html loads these two.
    ("sprite.js", "share.js"),
])
def test_scripts_loaded_on_one_page_declare_no_name_twice(a, b):
    clash = _top_level_names(a) & _top_level_names(b)
    assert not clash, f"{a} and {b} both declare {sorted(clash)}: a SyntaxError that blanks the page"


def test_the_pages_load_their_scripts_in_dependency_order():
    index = (STATIC / "index.html").read_text(encoding="utf-8")
    order = [index.index(f'src="static/{n}"') for n in ("sprite.js", "app.js", "ingest.js", "clientfolders.js")]
    assert order == sorted(order), "sprite.js first (app.js reads its globals), clientfolders.js last (it reads app.js's)"
    share = (STATIC / "share.html").read_text(encoding="utf-8")
    assert share.index('src="../assets/sprite.js"') < share.index('src="../assets/share.js"')
    assert 'type="module"' not in index and 'type="module"' not in share


def test_the_spa_hooks_the_card_and_the_detail_view():
    app_js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert 'if (typeof cfDecorateCard === "function") cfDecorateCard(card, video);' in app_js
    index = (STATIC / "index.html").read_text(encoding="utf-8")
    for needle in ('id="cf-btn"', 'id="cf-add-detail-btn"', 'id="cf-panel"', 'id="cf-popover"'):
        assert needle in index, needle
    cf_js = (STATIC / "clientfolders.js").read_text(encoding="utf-8")
    assert "e.stopPropagation()" in cf_js, "the card's + must not also open the detail view"


def test_the_viewer_hides_the_download_affordance():
    """A deterrent, not a lock: previews are the licensee's to watch, not to
    keep, and the native download button is the one-click way to keep one."""
    html = (STATIC / "share.html").read_text(encoding="utf-8")
    assert 'controlslist="nodownload' in html
    assert '<meta name="robots" content="noindex' in html


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_the_new_scripts_parse():
    for name in ("sprite.js", "share.js", "clientfolders.js"):
        subprocess.run(["node", "--check", str(STATIC / name)], check=True,
                       capture_output=True, text=True)
