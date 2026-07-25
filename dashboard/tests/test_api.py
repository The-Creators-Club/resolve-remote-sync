from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth
from ccsync_dashboard import db as dbmod
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

DEVICE_ID = "EDITORA-EDITORA-EDITORA-EDITORA-EDITORA-EDITORA-EDITORA-EDITORA"
T = "2026-07-24T10:00:00+00:00"
SECRET = "test-secret"


@pytest.fixture
def app_env(tmp_path):
    db_path = tmp_path / "dash.db"
    settings = Settings(db_path=str(db_path), report_token="sekrit",
                        session_secret=SECRET, admin_users=frozenset({"admin"}))
    app = create_app(settings)
    with TestClient(app) as client:
        # log in as an admin so reads see the whole fleet (the login gate now
        # forbids anonymous access)
        client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "admin"))
        conn = dbmod.connect(db_path)
        yield client, conn
        conn.close()


def seed(conn):
    now = dbmod.utcnow_iso()
    pid = dbmod.upsert_project(conn, "2025-ff4-nuclear", "2025/FF4/Nuclear", "/data/x", now)
    did = dbmod.upsert_device(conn, DEVICE_ID, "jsmith", False, now)
    dbmod.set_connections(conn, {DEVICE_ID: "100.1.2.3:22000"}, now)
    dbmod.upsert_completion(conn, pid, did, completion=62.5, need_items=45,
                            need_bytes=1_000_000, need_deletes=0,
                            global_items=120, global_bytes=5_000_000, now=now)
    dbmod.replace_missing_files(conn, pid, did, [("Audio/Music/track1.wav", 1234)], False, now)
    dbmod.record_poll_run(conn, "completion", now, now, True, None)
    conn.commit()
    return pid, did


def test_health_endpoint(app_env):
    client, conn = app_env
    body = client.get("/api/v1/health").json()
    assert body["syncthing_reachable"] is False and "version" in body
    seed(conn)
    body = client.get("/api/v1/health").json()
    assert body["syncthing_reachable"] is True
    assert body["last_polls"]["completion"]["ok"] is True


def test_projects_and_detail(app_env):
    client, conn = app_env
    seed(conn)
    body = client.get("/api/v1/projects").json()
    assert body["fleet_status"] == "amber"
    (project,) = body["projects"]
    assert project["slug"] == "2025-ff4-nuclear" and project["status"] == "amber"
    (editor,) = project["editors"]
    assert editor["display_name"] == "jsmith" and editor["unmapped"] is False
    assert editor["have_items"] == 75 and editor["connected"] is True

    detail = client.get("/api/v1/projects/2025-ff4-nuclear")
    assert detail.status_code == 200 and detail.json()["label"] == "2025/FF4/Nuclear"
    assert client.get("/api/v1/projects/nope").status_code == 404


def test_missing_endpoint(app_env):
    client, conn = app_env
    seed(conn)
    body = client.get(f"/api/v1/projects/2025-ff4-nuclear/devices/{DEVICE_ID}/missing").json()
    assert body["files"] == [{"name": "Audio/Music/track1.wav", "size": 1234}]
    assert body["truncated"] is False and body["need_items"] == 45
    assert client.get(f"/api/v1/projects/nope/devices/{DEVICE_ID}/missing").status_code == 404
    assert client.get("/api/v1/projects/2025-ff4-nuclear/devices/NOPE/missing").status_code == 404


def test_ui_pages_render(app_env):
    client, conn = app_env
    seed(conn)
    home = client.get("/")
    assert home.status_code == 200
    assert "CREATORS CLUB" in home.text and "2025/FF4/Nuclear" in home.text

    page = client.get("/project/2025-ff4-nuclear")
    assert page.status_code == 200
    assert "jsmith" in page.text and "62%" in page.text and "[ MISSING FILES ]" in page.text
    assert client.get("/project/nope").status_code == 404

    partial = client.get(f"/partials/project/2025-ff4-nuclear/missing/{DEVICE_ID}")
    assert partial.status_code == 200 and "Audio/Music/track1.wav" in partial.text
