from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import db as dbmod
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings


def payload(state="idle", error=None):
    return {
        "editor_name": "JSmith",
        "machine": "EDIT-PC",
        "companion_version": "0.1.0",
        "reported_at": "2026-07-24T10:00:00+00:00",
        "lanes": [
            {"name": "lane_a_video_up", "state": state, "queued": 3, "transferring": 1,
             "last_error": error, "last_sync": "2026-07-24T09:55:00+00:00", "detail": None},
            {"name": "lane_b_proxy_down", "state": "idle", "queued": 0, "transferring": 0,
             "last_error": None, "last_sync": None, "detail": None},
            {"name": "lane_c_syncthing", "state": "syncing", "queued": 12, "transferring": 0,
             "last_error": None, "last_sync": None, "detail": None},
        ],
    }


@pytest.fixture
def app_env(tmp_path):
    db_path = tmp_path / "dash.db"
    app = create_app(Settings(db_path=str(db_path), report_token="sekrit",
                              session_secret="s", admin_users=frozenset({"admin"})))
    with TestClient(app) as client:
        conn = dbmod.connect(db_path)
        yield client, conn
        conn.close()


def test_token_required(app_env):
    client, _ = app_env
    assert client.post("/api/v1/report", json=payload()).status_code == 401
    assert client.post("/api/v1/report", json=payload(),
                       headers={"X-CCSync-Token": "wrong"}).status_code == 401


def test_no_token_configured_rejects_unless_opted_out(tmp_path):
    app = create_app(Settings(db_path=str(tmp_path / "a.db")))
    with TestClient(app) as client:
        assert client.post("/api/v1/report", json=payload()).status_code == 401
    app = create_app(Settings(db_path=str(tmp_path / "b.db"), report_token_optional=True))
    with TestClient(app) as client:
        assert client.post("/api/v1/report", json=payload()).status_code == 200


def test_malformed_payload_422(app_env):
    client, _ = app_env
    bad = payload()
    bad["lanes"][0]["state"] = "exploded"
    resp = client.post("/api/v1/report", json=bad, headers={"X-CCSync-Token": "sekrit"})
    assert resp.status_code == 422
    resp = client.post("/api/v1/report", json={"editor_name": "x"},
                       headers={"X-CCSync-Token": "sekrit"})
    assert resp.status_code == 422


def test_report_rejects_unknown_lane_name(app_env):
    """SEC-4: an unknown lane name must never create a permanent
    lane_report_current row -- current companions send exactly the three
    names in LANE_LABELS, so rejecting anything else is safe."""
    client, conn = app_env
    bad = payload()
    bad["lanes"].append({"name": "lane_z_made_up", "state": "idle"})
    resp = client.post("/api/v1/report", json=bad, headers={"X-CCSync-Token": "sekrit"})
    assert resp.status_code == 422
    assert conn.execute("SELECT COUNT(*) FROM lane_report_current").fetchone()[0] == 0


def test_report_lanes_list_is_capped(app_env):
    """SEC-4: an unbounded lanes list could otherwise insert one permanent
    lane_report_current row per distinct (bogus) lane name."""
    client, _ = app_env
    bad = payload()
    bad["lanes"] = [{"name": "lane_a_video_up", "state": "idle"}] * 33
    resp = client.post("/api/v1/report", json=bad, headers={"X-CCSync-Token": "sekrit"})
    assert resp.status_code == 422


def test_report_transfers_list_is_capped(app_env):
    client, _ = app_env
    bad = payload()
    bad["lanes"][0]["transfers"] = [
        {"name": f"f{i}.braw", "direction": "up"} for i in range(257)
    ]
    resp = client.post("/api/v1/report", json=bad, headers={"X-CCSync-Token": "sekrit"})
    assert resp.status_code == 422


def test_report_upserts_and_transition_history(app_env):
    client, conn = app_env
    headers = {"X-CCSync-Token": "sekrit"}
    assert client.post("/api/v1/report", json=payload(), headers=headers).json()["lanes"] == 3
    # editor name is normalized to the username convention (lowercase)
    rows = conn.execute("SELECT DISTINCT editor_username FROM lane_report_current").fetchall()
    assert [r[0] for r in rows] == ["jsmith"]
    assert conn.execute("SELECT COUNT(*) FROM lane_report_current").fetchone()[0] == 3
    assert conn.execute("SELECT COUNT(*) FROM lane_report_history").fetchone()[0] == 3

    # same states again: no new history
    client.post("/api/v1/report", json=payload(), headers=headers)
    assert conn.execute("SELECT COUNT(*) FROM lane_report_history").fetchone()[0] == 3
    # error transition: exactly one new history row
    client.post("/api/v1/report", json=payload(state="error", error="rclone exit 1"), headers=headers)
    assert conn.execute("SELECT COUNT(*) FROM lane_report_history").fetchone()[0] == 4

    # fleet view surfaces the error (admin session required post-login-gate)
    from ccsync_dashboard import auth
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie("s", "admin"))
    editors = client.get("/api/v1/editors").json()["editors"]
    assert len(editors) == 1
    assert editors[0]["status"] == "red"
    lane_a = next(l for l in editors[0]["lanes"] if l["lane"] == "lane_a_video_up")
    assert lane_a["last_error"] == "rclone exit 1"
