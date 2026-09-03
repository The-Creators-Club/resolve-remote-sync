"""The fleet halt and the companion safety alarms
(COMMERCIAL_READINESS.md item 9, 2026-08-17).

Two halves that have to meet: the companion REPORTS its lane B breaker /
halt / trash state, and an admin SETS a fleet-wide stop that rides the report
reply back. Both are only useful if they reach the fleet grid, so the
rendering is pinned here too.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth
from ccsync_dashboard import db as dbmod
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

DASHBOARD_ROOT = Path(__file__).resolve().parents[1]

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
    # UX-16 / UX-10 (usability sweep 2026-09-03): "computer", and the
    # noun agrees with the count.
    assert "PROXY DOWNLOAD STOPPED on 1 computer" in page.text


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
    assert "SYNCING STOPPED on 1 computer" in page.text  # UX-16 / UX-10


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
    as_admin(client).post("/api/v1/fleet/halt", json={"active": True, "reason": "checking the pool"})
    as_admin(client).post("/api/v1/fleet/halt", json={"active": False, "reason": ""})
    client.cookies.clear()
    reply = client.post("/api/v1/report", json=payload(), headers=report_headers()).json()
    assert reply["commands"]["halt"]["active"] is False


def test_the_halt_survives_a_restart(env, tmp_path):
    client, _conn = env
    as_admin(client).post("/api/v1/fleet/halt", json={"active": True, "reason": "checking the pool"})
    app = create_app(Settings(db_path=str(tmp_path / "dash.db"), report_token="sekrit",
                              session_secret=SECRET, admin_users=frozenset({"owen"})))
    with TestClient(app) as fresh:
        reply = fresh.post("/api/v1/report", json=payload(),
                           headers=report_headers()).json()
        assert reply["commands"]["halt"]["active"] is True


def test_only_an_admin_may_set_the_halt(env):
    client, _conn = env
    assert client.post("/api/v1/fleet/halt",
                       json={"active": True, "reason": "checking the pool"}).status_code == 401
    assert as_editor(client).post(
        "/api/v1/fleet/halt", json={"active": True, "reason": "checking the pool"}).status_code == 403


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


# -- UX-8 (resilience sweep 2026-08-28): expiry, extend, history, the banner


def test_a_halt_defaults_to_a_24_hour_expiry(env):
    client, conn = env
    as_admin(client).post("/api/v1/fleet/halt",
                          json={"active": True, "reason": "checking the pool"})
    halt = dbmod.get_fleet_halt(conn)
    assert halt["expires_at"]
    hours = (dbmod.parse_iso(halt["expires_at"]) - dbmod.parse_iso(halt["set_at"])).total_seconds() / 3600
    assert hours == pytest.approx(24, abs=0.01)


def test_a_custom_hours_is_honoured(env):
    client, conn = env
    as_admin(client).post("/api/v1/fleet/halt",
                          json={"active": True, "reason": "quick check", "hours": 2})
    halt = dbmod.get_fleet_halt(conn)
    hours = (dbmod.parse_iso(halt["expires_at"]) - dbmod.parse_iso(halt["set_at"])).total_seconds() / 3600
    assert hours == pytest.approx(2, abs=0.01)


def test_an_expired_halt_is_released_for_every_reader(env, monkeypatch):
    client, conn = env
    as_admin(client).post(
        "/api/v1/fleet/halt",
        json={"active": True, "reason": "restoring the pool", "hours": 1})
    assert dbmod.get_fleet_halt(conn)["active"] is True

    # Two hours later: the one-hour halt has ended on its own.
    future = "2099-01-01T00:00:00+00:00"
    monkeypatch.setattr(dbmod, "utcnow_iso", lambda: future)

    # 1) the companion-facing commands block treats it as released
    client.cookies.clear()
    reply = client.post("/api/v1/report", json=payload(), headers=report_headers()).json()
    assert reply["commands"]["halt"]["active"] is False

    # 2) the fleet grid no longer shows the halt banner
    grid = as_admin(client).get("/partials/fleet")
    assert "FLEET SYNC IS HALTED" not in grid.text

    # 3) the standing every-page banner reads it as expired, not active
    banner = as_admin(client).get("/partials/fleet-halt-banner")
    assert "SYNCING IS HALTED ON EVERY COMPUTER" not in banner.text
    assert "THE FLEET HALT HAS EXPIRED" in banner.text

    # ...and get_fleet_halt itself agrees
    assert dbmod.get_fleet_halt(conn)["active"] is False
    assert dbmod.get_fleet_halt(conn)["expired"] is True


def test_keep_halted_extends_and_carries_the_reason(env, monkeypatch):
    # The real [ KEEP HALTED ] button posts to the Users-page panel route
    # with no reason field at all (fleet_halt.html). The JSON twin used to
    # refuse the same call for want of a reason (bug-hunt-2026-09-03
    # dash-api-4); both doors exempt `extend` now, and the test below pins it.
    client, conn = env
    as_admin(client).post("/api/v1/fleet/halt",
                          json={"active": True, "reason": "restoring the pool"})
    first = dbmod.get_fleet_halt(conn)
    # An hour later, still well inside the 24h window (so the halt is still
    # ACTIVE, not expired) but a distinct clock so expires_at is provably
    # pushed out, not just re-stamped within the same wall-clock second.
    later = (dbmod.parse_iso(first["set_at"]) + dt.timedelta(hours=1)).isoformat()
    monkeypatch.setattr(dbmod, "utcnow_iso", lambda: later)
    resp = as_admin(client).post(
        "/partials/admin/fleet-halt", data={"active": "1", "extend": "1"})
    assert resp.status_code == 200
    extended = dbmod.get_fleet_halt(conn)
    assert extended["reason"] == "restoring the pool"
    assert extended["set_by"] == "owen"
    assert extended["set_at"] == first["set_at"]
    assert extended["expires_at"] > first["expires_at"]
    assert extended["extended"] == 1
    assert "kept on 1 time" in resp.text


def test_a_halt_with_a_short_reason_422s_but_a_release_needs_none(env):
    client, _conn = env
    resp = as_admin(client).post(
        "/api/v1/fleet/halt", json={"active": True, "reason": "ok"})
    assert resp.status_code == 422
    resp = as_admin(client).post(
        "/api/v1/fleet/halt", json={"active": False})
    assert resp.status_code == 200


def test_halt_history_records_who_when_why_and_released(env):
    client, conn = env
    as_admin(client).post("/api/v1/fleet/halt",
                          json={"active": True, "reason": "first look"})
    as_admin(client).post("/api/v1/fleet/halt", json={"active": False})
    as_admin(client).post("/api/v1/fleet/halt",
                          json={"active": True, "reason": "second look"})
    history = dbmod.fleet_halt_history(conn)
    assert len(history) >= 3
    latest = history[0]
    assert latest["by"] == "owen"
    assert latest["reason"] == "second look"
    assert latest["at"]
    actions = [h["action"] for h in history[:3]]
    assert actions == ["halt", "release", "halt"]

    page = as_admin(client).get("/partials/admin/fleet-halt")
    assert "PREVIOUS HALTS" in page.text
    assert "first look" in page.text
    assert "second look" in page.text


def test_the_banner_renders_hours_and_machines_on_a_non_fleet_page(env):
    client, _conn = env
    client.post("/api/v1/report", json=payload(), headers=report_headers())
    as_admin(client).post("/api/v1/fleet/halt",
                          json={"active": True, "reason": "restoring the pool"})
    # /transfers extends base.html same as every other page, and is not the
    # fleet grid: the banner has to reach it too.
    page = as_admin(client).get("/transfers")
    assert page.status_code == 200
    assert 'hx-get="/partials/fleet-halt-banner"' in page.text

    banner = as_admin(client).get("/partials/fleet-halt-banner")
    assert "SYNCING IS HALTED ON EVERY COMPUTER" in banner.text
    assert "1 computer" in banner.text or "computer in the fleet" in banner.text


# -- UX-8 seam (a): extend on an already-expired halt must not go blank -----


def test_extend_on_an_expired_halt_refuses_rather_than_going_blank(env, monkeypatch):
    # The scenario this seam closes: an admin leaves the Users page open
    # across the weekend, the halt they set expires on its own, and the
    # stale [ KEEP HALTED ] button (which sends no reason at all) is still
    # sitting there when they come back and click it.
    client, conn = env
    as_admin(client).post(
        "/api/v1/fleet/halt",
        json={"active": True, "reason": "restoring the pool", "hours": 1})
    prior = dbmod.get_fleet_halt(conn)

    future = "2099-01-01T00:00:00+00:00"
    monkeypatch.setattr(dbmod, "utcnow_iso", lambda: future)

    panel = as_admin(client).post(
        "/partials/admin/fleet-halt", data={"active": "1", "extend": "1"})
    assert panel.status_code == 200
    assert "already ended" in panel.text
    assert prior["expires_at"] in panel.text
    # Nothing was silently re-halted with a blank reason.
    assert dbmod.get_fleet_halt(conn)["active"] is False


def test_extend_on_an_expired_halt_raises_a_readable_error_at_the_db_layer(env, monkeypatch):
    # The seam itself, pinned directly on db.set_fleet_halt so it cannot
    # regress even if a future caller reaches it a different way than the
    # Users-page panel does.
    client, conn = env
    dbmod.set_fleet_halt(conn, True, "restoring the pool", "owen", hours=1,
                         now="2026-08-28T10:00:00+00:00")
    with pytest.raises(ValueError, match="already ended"):
        dbmod.set_fleet_halt(conn, True, "", "owen", extend=True,
                             now="2026-08-29T10:00:00+00:00")
    assert dbmod.get_fleet_halt(conn, now="2026-08-29T10:00:00+00:00")["active"] is False


def test_extend_on_an_expired_halt_with_a_real_reason_starts_a_fresh_one(env, monkeypatch):
    # extend=true with an actual reason is not the trap UX-8 closes: it reads
    # as "start a new halt", which is fine, and matches what the JSON route
    # already requires unconditionally (every active=True call needs a
    # reason of its own, regardless of extend).
    client, conn = env
    as_admin(client).post(
        "/api/v1/fleet/halt",
        json={"active": True, "reason": "restoring the pool", "hours": 1})
    future = "2099-01-01T00:00:00+00:00"
    monkeypatch.setattr(dbmod, "utcnow_iso", lambda: future)
    resp = as_admin(client).post(
        "/api/v1/fleet/halt",
        json={"active": True, "extend": True, "reason": "new incident"})
    assert resp.status_code == 200
    assert resp.json()["halt"]["reason"] == "new incident"
    assert dbmod.get_fleet_halt(conn)["active"] is True


def test_c2_halt_confirm_copy_is_pinned():
    text = (DASHBOARD_ROOT / "templates" / "partials" / "fleet_halt.html").read_text(
        encoding="utf-8")
    assert ("Stop syncing on EVERY computer in the fleet? Uploads, proxy downloads "
            "and shared project files stop everywhere until you start them again "
            "here. Nothing is deleted. Work done while the halt is on will not "
            "reach anyone until you release it.") in text


def test_a_blank_extend_cannot_start_a_halt_through_the_json_route(env):
    # `extend` is exempt from the reason floor since bug-hunt-2026-09-03
    # dash-api-4 (the htmx door always was), so what stops a script starting
    # a blank-reason halt here is db.set_fleet_halt: there is nothing to keep
    # going. The refusal says so rather than asking for a reason it would not
    # have used.
    client, _conn = env
    resp = as_admin(client).post(
        "/api/v1/fleet/halt", json={"active": True, "extend": True})
    assert resp.status_code == 422
    assert "no halt to keep going" in resp.json()["detail"]
    assert dbmod.get_fleet_halt(_conn)["active"] is False


def test_keep_halted_needs_no_reason_through_the_json_door(env, monkeypatch):
    """bug-hunt-2026-09-03 dash-api-4: [ KEEP HALTED ] was inexpressible
    through the API. `extend` carries the CURRENT halt's reason forward, so
    demanding a new one 422'd the operation - and the obvious workaround
    (resend with a reason) is a FRESH halt, which resets set_at and makes the
    banner report how long since the last click rather than how long the fleet
    has been stopped."""
    client, conn = env
    as_admin(client).post("/api/v1/fleet/halt",
                          json={"active": True, "reason": "restoring the pool"})
    first = dbmod.get_fleet_halt(conn)
    later = (dbmod.parse_iso(first["set_at"]) + dt.timedelta(hours=1)).isoformat()
    monkeypatch.setattr(dbmod, "utcnow_iso", lambda: later)
    resp = as_admin(client).post("/api/v1/fleet/halt",
                                 json={"active": True, "extend": True})
    assert resp.status_code == 200, resp.text
    kept = dbmod.get_fleet_halt(conn)
    assert kept["reason"] == "restoring the pool"
    assert kept["set_at"] == first["set_at"]        # the same halt, not a new one
    assert kept["expires_at"] > first["expires_at"]
    assert kept["extended"] == 1
    # A halt with no reason and no extend is still refused.
    assert as_admin(client).post("/api/v1/fleet/halt",
                                 json={"active": True}).status_code == 422


def test_a_non_admin_is_refused_in_words_about_permission(env):
    """bug-hunt-2026-09-03 dash-api-5: _require_admin gates ~45 routes and
    told every one of their callers that "destination roots are fixed once
    set" - a configuration sentence on a permission refusal."""
    client, _conn = env
    resp = as_editor(client).post("/api/v1/fleet/halt",
                                  json={"active": True, "reason": "not mine to set"})
    assert resp.status_code == 403
    assert resp.json()["detail"] == "admins only"
