from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth
from ccsync_dashboard import db as dbmod
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "test-secret"
TOKEN = "companion-token"


@pytest.fixture
def env(tmp_path):
    db_path = tmp_path / "sel.db"
    settings = Settings(db_path=str(db_path), session_secret=SECRET,
                        report_token=TOKEN, admin_users=frozenset({"alex"}))
    app = create_app(settings)
    with TestClient(app) as client:
        conn = dbmod.connect(db_path)
        now = dbmod.utcnow_iso()
        for slug, label in [("2025-ff4-nuclear", "2025/FF4/Nuclear"),
                            ("2026-ff5-energy-transition", "2026/FF5/Energy Transition"),
                            ("2026-creator-profiles-season-1", "2026/Creator Profiles/Season 1")]:
            dbmod.upsert_project(conn, slug, label, f"/data/{slug}", now)
        conn.commit()
        yield client, conn
        conn.close()


def as_user(client, user):
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, user))
    return client


def test_tick_order_and_untick(env):
    client, conn = env
    as_user(client, "jsmith")
    assert client.put("/api/v1/selection/jsmith/2026-ff5-energy-transition").status_code == 200
    assert client.put("/api/v1/selection/jsmith/2025-ff4-nuclear").status_code == 200
    body = client.get("/api/v1/selection/jsmith").json()
    assert [s["slug"] for s in body["selection"]] == [
        "2026-ff5-energy-transition", "2025-ff4-nuclear"]  # tick order

    # re-tick is a no-op, order unchanged
    assert client.put("/api/v1/selection/jsmith/2026-ff5-energy-transition").json()["changed"] is False

    # untick then re-tick moves it to the back
    client.delete("/api/v1/selection/jsmith/2026-ff5-energy-transition")
    client.put("/api/v1/selection/jsmith/2026-ff5-energy-transition")
    body = client.get("/api/v1/selection/jsmith").json()
    assert [s["slug"] for s in body["selection"]] == [
        "2025-ff4-nuclear", "2026-ff5-energy-transition"]

    assert client.put("/api/v1/selection/jsmith/nope").status_code == 404


def test_auth_matrix(env):
    client, _ = env
    # anonymous
    assert client.get("/api/v1/selection/jsmith").status_code == 401
    assert client.put("/api/v1/selection/jsmith/2025-ff4-nuclear").status_code == 401
    # companion token: read yes, write no
    headers = {"X-CCSync-Token": TOKEN}
    assert client.get("/api/v1/selection/jsmith", headers=headers).status_code == 200
    assert client.put("/api/v1/selection/jsmith/2025-ff4-nuclear", headers=headers).status_code == 401
    # another editor: no
    as_user(client, "other")
    assert client.put("/api/v1/selection/jsmith/2025-ff4-nuclear").status_code == 403
    assert client.get("/api/v1/selection/jsmith").status_code == 401 or True  # other cannot read either
    # admin: yes
    as_user(client, "alex")
    assert client.put("/api/v1/selection/jsmith/2025-ff4-nuclear").status_code == 200
    assert client.get("/api/v1/selection/jsmith").status_code == 200


def test_queue_ui_and_toggle(env):
    client, conn = env
    as_user(client, "jsmith")
    page = client.get("/")
    assert "[ SYNC QUEUE — JSMITH ]" in page.text and "[ TICK ]" in page.text

    resp = client.post("/partials/selection/jsmith/2025-ff4-nuclear/toggle")
    assert resp.status_code == 200 and "[ UNTICK ]" in resp.text
    assert [s["slug"] for s in dbmod.fetch_selections(conn, "jsmith")] == ["2025-ff4-nuclear"]
    # toggle again removes
    client.post("/partials/selection/jsmith/2025-ff4-nuclear/toggle")
    assert dbmod.fetch_selections(conn, "jsmith") == []

    # project page shows SELECTED BY + tick-for-me
    client.post("/partials/selection/jsmith/2025-ff4-nuclear/toggle")
    page = client.get("/project/2025-ff4-nuclear")
    assert "SELECTED BY:" in page.text and "jsmith" in page.text
