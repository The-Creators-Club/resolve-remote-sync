from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth
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


SECRET = "s"


def report_headers(editor="jsmith", token="sekrit"):
    """Both companion headers -- X-CCSync-Identity is required on reports."""
    return {"X-CCSync-Token": token,
            "X-CCSync-Identity": auth.make_identity_token(SECRET, editor)}


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
    resp = client.post("/api/v1/report", json=bad, headers=report_headers())
    assert resp.status_code == 422
    resp = client.post("/api/v1/report", json={"editor_name": "x"},
                       headers=report_headers())
    assert resp.status_code == 422


def test_report_drops_unknown_lane_names_without_rejecting_the_report(app_env):
    """SEC-4 says an unknown lane name must never create a permanent
    lane_report_current row -- but rejecting the MODEL threw away the three
    valid lanes with it, so any future 4th lane would make every companion
    shipping it go completely dark against an un-upgraded dashboard. Filter,
    don't reject (see new-defect 3)."""
    client, conn = app_env
    forward_compatible = payload()
    forward_compatible["lanes"].append({"name": "lane_z_made_up", "state": "idle"})
    resp = client.post("/api/v1/report", json=forward_compatible, headers=report_headers())
    assert resp.status_code == 200
    assert resp.json()["lanes"] == 3          # the unknown one was dropped
    lanes = {r[0] for r in conn.execute("SELECT DISTINCT lane FROM lane_report_current")}
    assert lanes == {"lane_a_video_up", "lane_b_proxy_down", "lane_c_syncthing"}

    # A report of ONLY unknown lanes still writes nothing.
    only_unknown = payload()
    only_unknown["lanes"] = [{"name": "lane_z_made_up", "state": "idle"}]
    resp = client.post("/api/v1/report", json=only_unknown, headers=report_headers())
    assert resp.status_code == 200 and resp.json()["lanes"] == 0
    assert "lane_z_made_up" not in {
        r[0] for r in conn.execute("SELECT DISTINCT lane FROM lane_report_current")}


def test_report_lanes_list_is_capped(app_env):
    """SEC-4: an unbounded lanes list could otherwise insert one permanent
    lane_report_current row per distinct (bogus) lane name."""
    client, _ = app_env
    bad = payload()
    bad["lanes"] = [{"name": "lane_a_video_up", "state": "idle"}] * 33
    resp = client.post("/api/v1/report", json=bad, headers=report_headers())
    assert resp.status_code == 422


def test_report_transfers_list_is_capped(app_env):
    client, _ = app_env
    bad = payload()
    bad["lanes"][0]["transfers"] = [
        {"name": f"f{i}.braw", "direction": "up"} for i in range(257)
    ]
    resp = client.post("/api/v1/report", json=bad, headers=report_headers())
    assert resp.status_code == 422


def test_report_upserts_and_transition_history(app_env):
    client, conn = app_env
    headers = report_headers()
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


# -- B17: transport_health crosses the wire and reaches the grid ------------


def transport_payload(**over):
    health = {
        "syncthing": {
            "devices": {"NASNASN-NASNASN": "relay-client"},
            "relayed": ["NASNASN-NASNASN"],
            "direct": [],
        },
        "orphans": {
            "lane_a": {"partials": {"count": 3, "bytes": 41_000_000_000},
                       "trash": {"count": 0, "bytes": 0}},
        },
        "express": {"enabled": True, "runs": 12, "files_uploaded": 40,
                    "dropped_over_cap": 7, "last_error": "rclone exit 1",
                    "last_run": "2026-07-26T08:00:00+00:00", "last_files": 2},
    }
    health.update(over)
    p = payload()
    p["transport_health"] = health
    return p


def test_transport_health_is_persisted_and_shown_on_the_fleet_grid(app_env):
    """B17: the companion computed transport_health every heavy tick and
    ReportIn dropped it (pydantic extra='ignore'), so `grep transport_health`
    over dashboard/ came back empty -- a RELAYED editor and a merely slow one
    stayed indistinguishable on the fleet grid, and the orphaned-.partial and
    express-failure counters that exist ONLY for server visibility reached
    nobody."""
    client, conn = app_env
    assert client.post("/api/v1/report", json=transport_payload(),
                       headers=report_headers()).status_code == 200

    row = conn.execute(
        """SELECT transport_relayed, transport_direct, orphan_partials,
                  orphan_partial_bytes, express_dropped, express_last_error,
                  transport_at
           FROM machine_state WHERE editor_username='jsmith'""").fetchone()
    assert row["transport_relayed"] == 1
    assert row["transport_direct"] == 0
    assert row["orphan_partials"] == 3
    assert row["orphan_partial_bytes"] == 41_000_000_000
    assert row["express_dropped"] == 7
    assert row["express_last_error"] == "rclone exit 1"
    assert row["transport_at"]

    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "admin"))
    entry = client.get("/api/v1/editors").json()["editors"][0]
    assert entry["transport"]["relayed"] == 1
    assert entry["transport"]["orphan_partials"] == 3

    page = client.get("/")
    assert page.status_code == 200
    assert "[ RELAYED: 1 ]" in page.text
    assert "[ ORPHANS: 3 ]" in page.text
    assert "[ EXPRESS FAILED ]" in page.text


def test_a_direct_only_machine_is_not_flagged_as_relayed(app_env):
    client, _ = app_env
    p = transport_payload(syncthing={"devices": {}, "relayed": [], "direct": ["A", "B"]},
                          orphans={}, express={"enabled": True, "dropped_over_cap": 0})
    assert client.post("/api/v1/report", json=p, headers=report_headers()).status_code == 200
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "admin"))
    page = client.get("/")
    assert "[ RELAYED" not in page.text
    assert "direct:2" in page.text


def test_a_light_report_does_not_wipe_the_stored_transport_state(app_env):
    """The companion only computes transport_health on HEAVY ticks; the LIGHT
    ticks in between must not clear what the last heavy one recorded."""
    client, conn = app_env
    client.post("/api/v1/report", json=transport_payload(), headers=report_headers())
    client.post("/api/v1/report", json=payload(), headers=report_headers())  # light
    row = conn.execute(
        "SELECT transport_relayed, express_last_error FROM machine_state").fetchone()
    assert row["transport_relayed"] == 1
    assert row["express_last_error"] == "rclone exit 1"


def test_an_unknown_transport_health_key_does_not_reject_the_report(app_env):
    """A companion that grows a new counter must never 422 its whole report
    against an older dashboard -- the whole reason this field was dropped
    silently in the first place."""
    client, _ = app_env
    p = transport_payload()
    p["transport_health"]["future_counter"] = {"a": 1}
    p["transport_health"]["express"]["brand_new"] = 5
    assert client.post("/api/v1/report", json=p,
                       headers=report_headers()).status_code == 200


def test_a_report_without_transport_health_still_works(app_env):
    client, _ = app_env
    assert client.post("/api/v1/report", json=payload(),
                       headers=report_headers()).status_code == 200
