"""One Unicode spelling for a media path (CR-90, 2026-08-28).

macOS hands filenames back decomposed. The NAS inventory walk and every
Windows machine spell the same name composed. The lane A/B backlog is a
rel_path diff of `nas_media` against `editor_media`, so an accented folder
made a Mac look permanently behind on files it already held: 12 proxies /
2.9 GB of FF5/Animals, under a lane B honestly reporting 0 transferred.
"""
from __future__ import annotations

import unicodedata

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth
from ccsync_dashboard import db as dbmod
from ccsync_dashboard.api import build_transfers_view
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "s"
TOKEN = "tok"

# The real pair off the NAS and off leso's MacBook, verified byte-identical.
NFC = "Interviewees/Pangolin/Matej Šimalčík/Proxy/A002_07161726_C048.mp4"
NFD = "Interviewees/Pangolin/Matej Šimalčík/Proxy/A002_07161726_C048.mp4"


@pytest.fixture
def env(tmp_path):
    settings = Settings(db_path=str(tmp_path / "u.db"), session_secret=SECRET,
                        report_token=TOKEN, admin_users=frozenset({"owen"}))
    with TestClient(create_app(settings)) as client:
        conn = dbmod.connect(tmp_path / "u.db")
        now = dbmod.utcnow_iso()
        dbmod.upsert_project(conn, "p1", "2026/FF5/Animals", "/x", now)
        conn.commit()
        client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "owen"))
        yield client, conn, now
        conn.close()


def _report(client, editor, machine):
    body = {"editor_name": editor, "machine": machine,
            "reported_at": "2026-08-28T10:00:00+00:00", "lanes": []}
    resp = client.post("/api/v1/report", json=body, headers={
        "X-CCSync-Token": TOKEN,
        "X-CCSync-Identity": auth.make_identity_token(SECRET, editor)})
    assert resp.status_code == 200, resp.text


def _tick(client, conn, machine):
    """The HTTP half FIRST and with nothing of ours open: one uncommitted
    write transaction on this connection and the app's own write blocks."""
    conn.commit()
    _report(client, "leso", machine)
    assert client.put(f"/api/v1/selection/leso/p1?machine={machine}").status_code == 200


def _manifest(conn, machine, files, now):
    dbmod.upsert_editor_media_project(
        conn, editor="leso", machine=machine, slug="p1", mode="editor",
        n_originals=0, bytes_originals=0, n_proxies=len(files), bytes_proxies=0,
        truncated=False, now=now)
    dbmod.replace_editor_media(conn, "leso", machine, "p1", files, now)
    conn.commit()


def _pid(conn):
    return conn.execute("SELECT id FROM projects WHERE slug='p1'").fetchone()["id"]


def test_media_rel_key_is_nfc():
    assert dbmod.media_rel_key(NFD) == NFC
    assert dbmod.media_rel_key(NFC) == NFC
    assert dbmod.media_rel_key(None) == ""
    # A name with no decomposed form is untouched: the CJK folders beside
    # this one always matched, which is why it read as a partial sync.
    assert dbmod.media_rel_key("Interviewees/Pangolin/臺北動物園/a.mov") == \
        "Interviewees/Pangolin/臺北動物園/a.mov"


def test_a_mac_holding_the_file_is_not_behind_on_it(env):
    """The bug: 12 files queued forever on a machine that had all 12."""
    client, conn, now = env
    dbmod.replace_nas_media(conn, _pid(conn), [(NFC, "proxy", ".mp4", 1431853821, 1)],
                            "sig", 1, now)
    _tick(client, conn, "MacBook-Pro.local")
    _manifest(conn, "MacBook-Pro.local", [(NFD, "proxy", 1431853821)], now)
    assert not [q for q in build_transfers_view(conn)["queues"]
                if q["slug"] == "p1" and not q.get("pending")]


def test_a_file_the_mac_really_lacks_is_still_queued(env):
    """The fix must not fold away a genuine backlog."""
    client, conn, now = env
    dbmod.replace_nas_media(conn, _pid(conn), [
        (NFC, "proxy", ".mp4", 1431853821, 1),
        ("Interviewees/Pangolin/Matej Šimalčík/Proxy/C049.mp4",
         "proxy", ".mp4", 500, 2),
    ], "sig", 1, now)
    _tick(client, conn, "MacBook-Pro.local")
    _manifest(conn, "MacBook-Pro.local", [(NFD, "proxy", 1431853821)], now)
    down = [q for q in build_transfers_view(conn)["queues"]
            if q["slug"] == "p1" and q["lane"] == "b"]
    assert len(down) == 1 and down[0]["n_files"] == 1
    assert down[0]["files"][0]["name"].endswith("C049.mp4")


def test_an_nfd_upload_the_nas_already_has_is_not_a_queue(env):
    """The diff is symmetric, so the same mismatch invented lane A uploads."""
    client, conn, now = env
    orig_nfc = NFC.replace("/Proxy/", "/").replace(".mp4", ".braw")
    orig_nfd = NFD.replace("/Proxy/", "/").replace(".mp4", ".braw")
    dbmod.replace_nas_media(conn, _pid(conn), [(orig_nfc, "original", ".braw", 99, 1)],
                            "sig", 1, now)
    _tick(client, conn, "MacBook-Pro.local")
    _manifest(conn, "MacBook-Pro.local", [(orig_nfd, "original", 99)], now)
    assert not [q for q in build_transfers_view(conn)["queues"]
                if q["slug"] == "p1" and q["lane"] == "a" and not q.get("pending")]


def test_stored_rows_carry_the_composed_spelling(env):
    """Both writers normalise, so the name a human reads off the queue is the
    NAS's own spelling whichever machine reported it."""
    client, conn, now = env
    dbmod.replace_nas_media(conn, _pid(conn), [(NFD, "proxy", ".mp4", 1, 1)], "sig", 1, now)
    _tick(client, conn, "MacBook-Pro.local")
    _manifest(conn, "MacBook-Pro.local", [(NFD, "proxy", 1)], now)
    for table in ("nas_media", "editor_media"):
        stored = conn.execute(f"SELECT rel_path FROM {table}").fetchone()["rel_path"]
        assert stored == NFC
        assert unicodedata.is_normalized("NFC", stored)


def test_a_file_mid_download_is_not_also_queued(env):
    """rclone names a file the way the Mac's filesystem spells it, so the
    in-flight subtraction had to fold the normalisations too."""
    client, conn, now = env
    dbmod.replace_nas_media(conn, _pid(conn), [
        (NFC, "proxy", ".mp4", 1431853821, 1),
        ("Interviewees/Pangolin/Matej Šimalčík/Proxy/C049.mp4",
         "proxy", ".mp4", 500, 2),
    ], "sig", 1, now)
    _tick(client, conn, "MacBook-Pro.local")
    _manifest(conn, "MacBook-Pro.local", [], now)
    dbmod.replace_active_transfers(conn, "leso", "MacBook-Pro.local", [
        {"lane": "lane_b_proxy_down", "name": NFD, "direction": "down",
         "percentage": 40.0, "speed_bps": 1000.0}], dbmod.utcnow_iso())
    conn.commit()
    down = [q for q in build_transfers_view(conn)["queues"]
            if q["slug"] == "p1" and q["lane"] == "b"]
    assert len(down) == 1 and down[0]["n_files"] == 1
    assert down[0]["files"][0]["name"].endswith("C049.mp4")
