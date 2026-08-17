"""The fleet halt and the companion safety alarms
(COMMERCIAL_READINESS.md item 9, 2026-08-17).

Two halves that have to meet: the companion REPORTS its lane B breaker /
halt / trash state, and an admin SETS a fleet-wide stop that rides the report
reply back. Both are only useful if they reach the fleet grid, so the
rendering is pinned here too.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth
from ccsync_dashboard import db as dbmod
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "s"


def report_headers(editor="jsmith", token="sekrit"):
    return {"X-CCSync-Token": token,
            "X-CCSync-Identity": auth.make_identity_token(SECRET, editor)}


def payload(guard=None):
    body = {
        "editor_name": "JSmith",
        "machine": "EDIT-PC",
        "companion_version": "0.8.0",
        "reported_at": "2026-08-17T10:00:00+00:00",
        "lanes": [
            {"name": "lane_b_proxy_down", "state": "paused", "queued": 0,
             "transferring": 0, "last_error": None, "last_sync": None,
             "detail": "STOPPED (safety): the NAS listed the tree as EMPTY"},
        ],
    }
    if guard is not None:
        body["sync_guard"] = guard
    return body


@pytest.fixture
def env(tmp_path):
    app = create_app(Settings(
        db_path=str(tmp_path / "dash.db"), report_token="sekrit",
        session_secret=SECRET, admin_users=frozenset({"owen"}),
    ))
    with TestClient(app) as client:
        conn = dbmod.connect(tmp_path / "dash.db")
        yield client, conn
        conn.close()


def as_admin(client):
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "owen"))
    return client


def as_editor(client):
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "jsmith"))
    return client


# -- the reported alarm -----------------------------------------------------


def test_a_tripped_breaker_is_stored_and_shown_on_the_grid(env):
    client, conn = env
    resp = client.post("/api/v1/report", json=payload({
        "lane_b_breaker": {
            "tripped": True, "reason": "the NAS listed the tree as EMPTY",
            "tripped_at": "2026-08-17T09:59:00+00:00", "deletes": 41,
        },
        "trash": {"count": 120, "bytes": 9_000_000_000},
    }), headers=report_headers())
    assert resp.status_code == 200

    guards = dbmod.fetch_sync_guard_map(conn)
    assert guards[("jsmith", "EDIT-PC")]["breaker_tripped"] is True
    assert guards[("jsmith", "EDIT-PC")]["trash_bytes"] == 9_000_000_000

    page = as_admin(client).get("/partials/fleet")
    assert page.status_code == 200
    assert "PROXY DOWNLOAD STOPPED" in page.text
    assert "the NAS listed the tree as EMPTY" in page.text
    # ...and the fleet BANNER, not only the row chip: a row chip on a grid of
    # ten machines is not an alarm.
    assert "PROXY DOWNLOAD STOPPED on 1 machine(s)" in page.text


def test_a_breaker_that_clears_clears_the_alarm(env):
    client, conn = env
    client.post("/api/v1/report", json=payload({
        "lane_b_breaker": {"tripped": True, "reason": "boom"},
    }), headers=report_headers())
    client.post("/api/v1/report", json=payload({
        "lane_b_breaker": {"tripped": False},
    }), headers=report_headers())
    guards = dbmod.fetch_sync_guard_map(conn)
    assert guards[("jsmith", "EDIT-PC")]["breaker_tripped"] is False
    assert "PROXY DOWNLOAD STOPPED" not in as_admin(client).get("/partials/fleet").text


def test_a_report_without_a_guard_section_leaves_the_alarm_alone(env):
    # An older companion knows nothing about any of this; its silence must
    # not clear an alarm a newer one raised.
    client, conn = env
    client.post("/api/v1/report", json=payload({
        "lane_b_breaker": {"tripped": True, "reason": "boom"},
    }), headers=report_headers())
    client.post("/api/v1/report", json=payload(), headers=report_headers())
    assert dbmod.fetch_sync_guard_map(conn)[("jsmith", "EDIT-PC")]["breaker_tripped"]


def test_a_halted_machine_shows_on_the_grid(env):
    client, _conn = env
    client.post("/api/v1/report", json=payload({
        "halt": {"active": True, "scope": "local", "reason": "editor stopped it"},
    }), headers=report_headers())
    page = as_admin(client).get("/partials/fleet")
    assert "SYNC HALTED" in page.text
    assert "SYNCING STOPPED on 1 machine(s)" in page.text


def test_the_skipped_exists_counter_reaches_the_grid(env):
    client, _conn = env
    client.post("/api/v1/report", json=payload({
        "skipped_exists": {"count": 3, "samples": ["A001.mov"]},
    }), headers=report_headers())
    assert "WON'T UPLOAD: 3" in as_admin(client).get("/partials/fleet").text


def test_an_unknown_guard_field_does_not_422_the_report(env):
    # The forward-compatibility rule every diagnostic section here follows: a
    # newer companion must never take a whole machine off the grid.
    client, _conn = env
    resp = client.post("/api/v1/report", json=payload({
        "lane_b_breaker": {"tripped": False, "some_future_counter": 7},
        "a_whole_new_section": {"x": 1},
    }), headers=report_headers())
    assert resp.status_code == 200


# -- the fleet halt ---------------------------------------------------------


def test_the_report_reply_always_carries_the_halt_command(env):
    client, _conn = env
    resp = client.post("/api/v1/report", json=payload(), headers=report_headers())
    # Present in BOTH states: an absent key means "this dashboard is too old
    # to have an opinion", which must not read as a release.
    assert resp.json()["commands"]["halt"]["active"] is False


def test_an_admin_halts_the_fleet_and_every_companion_learns_on_its_next_report(env):
    client, conn = env
    resp = as_admin(client).post(
        "/api/v1/fleet/halt", json={"active": True, "reason": "restoring the pool"})
    assert resp.status_code == 200
    assert resp.json()["halt"]["active"] is True
    assert resp.json()["halt"]["set_by"] == "owen"

    client.cookies.clear()
    reply = client.post("/api/v1/report", json=payload(), headers=report_headers()).json()
    assert reply["commands"]["halt"]["active"] is True
    assert reply["commands"]["halt"]["reason"] == "restoring the pool"


def test_the_halt_is_reversible(env):
    client, _conn = env
    as_admin(client).post("/api/v1/fleet/halt", json={"active": True, "reason": "x"})
    as_admin(client).post("/api/v1/fleet/halt", json={"active": False, "reason": ""})
    client.cookies.clear()
    reply = client.post("/api/v1/report", json=payload(), headers=report_headers()).json()
    assert reply["commands"]["halt"]["active"] is False


def test_the_halt_survives_a_restart(env, tmp_path):
    client, _conn = env
    as_admin(client).post("/api/v1/fleet/halt", json={"active": True, "reason": "x"})
    app = create_app(Settings(db_path=str(tmp_path / "dash.db"), report_token="sekrit",
                              session_secret=SECRET, admin_users=frozenset({"owen"})))
    with TestClient(app) as fresh:
        reply = fresh.post("/api/v1/report", json=payload(),
                           headers=report_headers()).json()
        assert reply["commands"]["halt"]["active"] is True


def test_only_an_admin_may_set_the_halt(env):
    client, _conn = env
    assert client.post("/api/v1/fleet/halt",
                       json={"active": True, "reason": "x"}).status_code == 401
    assert as_editor(client).post(
        "/api/v1/fleet/halt", json={"active": True, "reason": "x"}).status_code == 403


def test_any_signed_in_user_may_read_the_halt(env):
    # An editor whose tray says "your admin stopped syncing" has to be able
    # to confirm that from the dashboard.
    client, _conn = env
    assert as_editor(client).get("/api/v1/fleet/halt").json()["halt"]["active"] is False
    client.cookies.clear()
    assert client.get("/api/v1/fleet/halt").status_code == 401


def test_the_fleet_banner_says_when_the_whole_fleet_is_halted(env):
    client, _conn = env
    client.post("/api/v1/report", json=payload(), headers=report_headers())
    as_admin(client).post("/api/v1/fleet/halt",
                          json={"active": True, "reason": "restoring the pool"})
    page = as_admin(client).get("/partials/fleet")
    assert "FLEET SYNC IS HALTED" in page.text
    assert "restoring the pool" in page.text


# -- the Users-page control -------------------------------------------------


def test_the_users_page_panel_halts_and_releases(env):
    client, conn = env
    resp = as_admin(client).post("/partials/admin/fleet-halt",
                                 data={"active": "1", "reason": "NAS maintenance"})
    assert resp.status_code == 200
    assert "SYNCING IS HALTED FLEET-WIDE" in resp.text
    assert dbmod.get_fleet_halt(conn)["active"] is True

    resp = as_admin(client).post("/partials/admin/fleet-halt", data={"active": "0"})
    assert "HALT ALL SYNCING" in resp.text
    assert dbmod.get_fleet_halt(conn)["active"] is False


def test_the_panel_refuses_a_halt_with_no_reason(env):
    # The reason is what every editor's tray shows; a halt without one
    # produces a fleet of people who cannot work and cannot find out why.
    client, conn = env
    resp = as_admin(client).post("/partials/admin/fleet-halt",
                                 data={"active": "1", "reason": "   "})
    assert "say why" in resp.text
    assert dbmod.get_fleet_halt(conn)["active"] is False


def test_the_alarm_rollups_never_name_someone_elses_machine(env):
    # The rollups carry editor + machine names, so they follow the same
    # redaction as the rows they summarise (§C L1).
    client, _conn = env
    client.post("/api/v1/report", json=payload({
        "lane_b_breaker": {"tripped": True, "reason": "boom"},
    }), headers=report_headers())
    other = {"X-CCSync-Token": "sekrit",
             "X-CCSync-Identity": auth.make_identity_token(SECRET, "editor2")}
    body = payload({"halt": {"active": True, "scope": "local", "reason": "x"}})
    body["editor_name"] = "editor2"
    body["machine"] = "EDITOR-PC-02"
    client.post("/api/v1/report", json=body, headers=other)

    view = as_editor(client).get("/api/v1/editors").json()
    assert [m["editor"] for m in view["breaker_tripped"]] == ["jsmith"]
    assert view["halted"] == []
    admin_view = as_admin(client).get("/api/v1/editors").json()
    assert len(admin_view["breaker_tripped"]) == 1 and len(admin_view["halted"]) == 1


def test_an_editor_still_sees_why_the_whole_fleet_stopped(env):
    # The FLEET halt is not redacted: it is the reason this editor's own sync
    # has stopped.
    client, _conn = env
    as_admin(client).post("/api/v1/fleet/halt",
                          json={"active": True, "reason": "restoring the pool"})
    view = as_editor(client).get("/api/v1/editors").json()
    assert view["fleet_halt"]["active"] is True
    assert view["fleet_halt"]["reason"] == "restoring the pool"


def test_the_panel_is_admin_only(env):
    client, _conn = env
    assert as_editor(client).get("/partials/admin/fleet-halt").status_code in (302, 303, 403)
