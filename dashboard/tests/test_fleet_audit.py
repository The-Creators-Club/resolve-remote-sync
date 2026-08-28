"""The fleet audit ledger, the plan-change undo, and the enforce freeze.

SYS-11 / DASH-8, resilience sweep 2026-08-28. Two admins and no history is
what made "who stopped this project syncing on Tuesday" unanswerable: a
removal DELETEd its row and wrote nothing anywhere. These pin that every
state-changing door writes one row, that the undo restores what was there
(not what somebody assumes was there), and that an undo inside its window
does not cost Syncthing an unshare/re-share pair.
"""
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
    db_path = tmp_path / "audit.db"
    settings = Settings(db_path=str(db_path), session_secret=SECRET,
                        report_token=TOKEN, admin_users=frozenset({"owen"}))
    app = create_app(settings)
    with TestClient(app) as client:
        conn = dbmod.connect(db_path)
        now = dbmod.utcnow_iso()
        dbmod.upsert_project(conn, "ff4", "2025/FF4", "/data/ff4", now)
        dbmod.upsert_project(conn, "ff5", "2026/FF5", "/data/ff5", now)
        conn.commit()
        client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "owen"))
        yield client, conn
        conn.close()


def report(client, editor, machine, **extra):
    body = {"editor_name": editor, "machine": machine,
            "reported_at": "2026-08-28T10:00:00+00:00", "lanes": []}
    body.update(extra)
    resp = client.post("/api/v1/report", json=body, headers={
        "X-CCSync-Token": TOKEN,
        "X-CCSync-Identity": auth.make_identity_token(SECRET, editor),
    })
    assert resp.status_code == 200, resp.text
    return resp


def actions(conn, **kw):
    return [r["action"] for r in dbmod.fetch_audit(conn, **kw)]


# ----------------------------------------------------------------- the rows

def test_a_tick_and_an_untick_are_both_recorded_with_who_did_it(env):
    client, conn = env
    assert client.put("/api/v1/selection/ruskin/ff4").status_code == 200
    assert client.delete("/api/v1/selection/ruskin/ff4").status_code == 200

    rows = dbmod.fetch_audit(conn)
    assert [r["action"] for r in rows] == [dbmod.AUDIT_UNTICK, dbmod.AUDIT_TICK]
    assert {r["actor"] for r in rows} == {"owen"}
    assert rows[0]["subject"] == "ff4"
    # The untick knows what was there, which is what makes the undo a restore.
    assert rows[0]["detail"]["before"] == [{"machine": "", "mode": "full"}]
    assert rows[0]["detail"]["after"] == []
    assert rows[1]["detail"]["before"] == []


def test_a_no_op_tick_writes_nothing(env):
    """The ledger is read by a human. A second identical tick is not an event."""
    client, conn = env
    client.put("/api/v1/selection/ruskin/ff4")
    client.put("/api/v1/selection/ruskin/ff4")
    assert actions(conn) == [dbmod.AUDIT_TICK]


def test_the_htmx_checkbox_is_not_a_softer_door_than_the_json_route(env):
    client, conn = env
    assert client.post("/partials/selection/ruskin/ff4/toggle").status_code == 200
    assert client.post("/partials/selection/ruskin/ff4/toggle").status_code == 200
    assert actions(conn) == [dbmod.AUDIT_UNTICK, dbmod.AUDIT_TICK]


def test_a_per_machine_tick_records_the_machine_and_the_mode(env):
    client, conn = env
    report(client, "ruskin", "EDIT-PC", machine_id="mid-1")
    assert client.put(
        "/api/v1/selection/ruskin/ff4?machine=EDIT-PC&mode=upload_only").status_code == 200
    row = dbmod.fetch_audit(conn)[0]
    assert row["detail"]["scope"] == "machine"
    assert row["detail"]["machine"] == "EDIT-PC"
    assert row["detail"]["after"] == [{"machine": "EDIT-PC", "mode": "upload_only"}]


def test_the_fleet_halt_is_recorded_from_both_doors(env):
    client, conn = env
    assert client.post("/api/v1/fleet/halt",
                       json={"active": True, "reason": "files vanishing"}).status_code == 200
    assert client.post("/partials/admin/fleet-halt",
                       data={"active": "0"}).status_code == 200
    assert actions(conn) == ["fleet.halt_clear", "fleet.halt_set"]
    assert dbmod.fetch_audit(conn)[1]["detail"]["reason"] == "files vanishing"


def test_forgetting_a_computer_is_recorded(env):
    client, conn = env
    report(client, "ruskin", "EDIT-PC", machine_id="mid-1")
    assert client.delete("/api/v1/admin/machines/ruskin/EDIT-PC").status_code == 200
    row = dbmod.fetch_audit(conn)[0]
    assert (row["action"], row["actor"], row["subject"]) == (
        "machine.forget", "owen", "EDIT-PC")


def test_publishing_and_making_current_are_recorded(env):
    client, conn = env
    now = dbmod.utcnow_iso()
    # The publish ROUTE needs a signing key and a real body; the record it
    # writes is the same one this table is asked about, so drive the store.
    dbmod.insert_companion_package(
        conn, version="0.9.99", platform="windows", filename="ccsync-0.9.99.exe",
        sha256="a" * 64, size_bytes=10, published_by="ci", now=now)
    conn.commit()
    # The soak gate (REL-1, resilience sweep 2026-08-28) refuses a build no
    # machine has ever run; this test is about the AUDIT ROW, so it takes the
    # documented override, which is itself audited as forced.
    assert client.post(
        "/api/v1/admin/packages/windows/0.9.99/current"
        "?force=1&confirm=0.9.99").status_code == 200
    row = dbmod.fetch_audit(conn)[0]
    assert (row["action"], row["actor"]) == ("package.make_current", "owen")
    assert row["detail"]["platform"] == "windows"


def test_a_pushed_update_and_a_resume_are_recorded(env):
    client, conn = env
    report(client, "ruskin", "EDIT-PC", machine_id="mid-1")
    assert dbmod.request_machine_update(
        conn, "ruskin", "EDIT-PC", "0.9.99", "owen", dbmod.utcnow_iso()) is True
    assert dbmod.request_lane_b_resume(
        conn, "ruskin", "EDIT-PC", "owen", dbmod.utcnow_iso()) is True
    conn.commit()
    assert set(actions(conn)) == {"machine.update_push", "lane_b.resume_request"}


def test_the_timeline_filters_by_subject(env):
    client, conn = env
    client.put("/api/v1/selection/ruskin/ff4")
    client.put("/api/v1/selection/ruskin/ff5")
    assert [r["subject"] for r in dbmod.fetch_audit(conn, subject="ff5")] == ["ff5"]
    # ...and by who did it, because that is the other half of the question.
    assert len(dbmod.fetch_audit(conn, subject="owen")) == 2
    assert dbmod.fetch_audit(conn, subject="nothing-like-this") == []


def test_the_timeline_page_renders_the_rows_and_the_filter(env):
    client, conn = env
    client.put("/api/v1/selection/ruskin/ff4")
    page = client.get("/admin/audit")
    assert page.status_code == 200
    assert "[ WHAT CHANGED ]" in page.text
    assert "plan.tick" in page.text
    filtered = client.get("/partials/admin/audit?q=nothing-like-this")
    assert "nothing in the timeline matches" in filtered.text


def test_the_timeline_is_admins_only(env):
    client, conn = env
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "ruskin"))
    assert client.get("/admin/audit").status_code == 403
    assert client.get("/partials/plan-changes").status_code == 403


def test_the_ledger_is_pruned_at_180_days(env):
    client, conn = env
    old = "2026-01-01T00:00:00+00:00"
    dbmod.audit(conn, "owen", dbmod.AUDIT_UNTICK, "ff4", {"slug": "ff4"}, now=old)
    dbmod.audit(conn, "owen", dbmod.AUDIT_UNTICK, "ff5", {"slug": "ff5"})
    conn.commit()
    dbmod.prune(conn, dbmod.utcnow_iso())
    assert [r["subject"] for r in dbmod.fetch_audit(conn)] == ["ff5"]


# ------------------------------------------------------------------- undo

def test_undoing_an_untick_puts_every_computer_back_in_its_own_mode(env):
    client, conn = env
    report(client, "ruskin", "EDIT-PC", machine_id="mid-1")
    report(client, "ruskin", "LAPTOP", machine_id="mid-2")
    client.put("/api/v1/selection/ruskin/ff4?machine=EDIT-PC&mode=upload_only")
    client.put("/api/v1/selection/ruskin/ff4?machine=LAPTOP")
    # The person-level untick: off both computers at once.
    assert client.delete("/api/v1/selection/ruskin/ff4").json()["changed"] is True
    assert dbmod.selection_placements(conn, "ruskin", "ff4") == []

    undo_id = dbmod.fetch_audit(conn, actions=(dbmod.AUDIT_UNTICK,))[0]["id"]
    resp = client.post(f"/partials/plan-changes/{undo_id}/undo")
    assert resp.status_code == 200
    assert dbmod.selection_placements(conn, "ruskin", "ff4") == [
        {"machine": "EDIT-PC", "mode": "upload_only"},
        {"machine": "LAPTOP", "mode": "full"},
    ]
    # The undo is itself an event, and the row it undid says so.
    undo_row = dbmod.fetch_audit(conn)[0]
    assert undo_row["action"] == dbmod.AUDIT_PLAN_UNDO
    assert undo_row["detail"]["undid"] == undo_id
    assert dbmod.recent_plan_changes(conn, dbmod.utcnow_iso())[0]["undone"] is True


def test_undoing_a_tick_removes_it_again(env):
    client, conn = env
    report(client, "ruskin", "EDIT-PC", machine_id="mid-1")
    client.put("/api/v1/selection/ruskin/ff4?machine=EDIT-PC")
    tick_id = dbmod.fetch_audit(conn)[0]["id"]
    assert client.post(f"/partials/plan-changes/{tick_id}/undo").status_code == 200
    assert dbmod.selection_placements(conn, "ruskin", "ff4") == []


def test_undoing_a_mode_switch_restores_the_mode_it_had(env):
    client, conn = env
    report(client, "ruskin", "EDIT-PC", machine_id="mid-1")
    client.put("/api/v1/selection/ruskin/ff4?machine=EDIT-PC")
    client.put("/api/v1/selection/ruskin/ff4?machine=EDIT-PC&mode=upload_only")
    switch_id = dbmod.fetch_audit(conn)[0]["id"]
    assert client.post(f"/partials/plan-changes/{switch_id}/undo").status_code == 200
    assert dbmod.selection_placements(conn, "ruskin", "ff4") == [
        {"machine": "EDIT-PC", "mode": "full"}]


def test_an_undo_of_something_else_is_refused_in_words(env):
    client, conn = env
    dbmod.audit(conn, "owen", "fleet.halt_set", "fleet", {})
    conn.commit()
    resp = client.post("/partials/plan-changes/1/undo")
    assert resp.status_code == 200
    assert "not a plan change this page can undo" in resp.text
    resp = client.post("/partials/plan-changes/9999/undo")
    assert "not a plan change this page can undo" in resp.text


def test_an_hour_old_change_is_no_longer_offered_as_an_undo(env):
    client, conn = env
    old = dbmod._iso_minus(dbmod.utcnow_iso(), dbmod.PLAN_UNDO_WINDOW_SECONDS + 60)
    audit_id = dbmod.audit(conn, "owen", dbmod.AUDIT_UNTICK, "ff4", {
        "editor": "ruskin", "slug": "ff4", "scope": "person",
        "before": [{"machine": "", "mode": "full"}], "after": [],
    }, now=old)
    conn.commit()
    resp = client.post(f"/partials/plan-changes/{audit_id}/undo")
    assert "no longer offered" in resp.text
    assert dbmod.selection_placements(conn, "ruskin", "ff4") == []
    # ...and it is not in the panel either.
    assert dbmod.recent_plan_changes(conn, dbmod.utcnow_iso()) == []


def test_the_fleet_page_carries_the_panel_only_for_an_admin(env):
    client, conn = env
    client.put("/api/v1/selection/ruskin/ff4")
    assert "/partials/plan-changes" in client.get("/").text
    panel = client.get("/partials/plan-changes")
    assert "[ RECENT PLAN CHANGES ]" in panel.text and "[ UNDO ]" in panel.text
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "ruskin"))
    assert "/partials/plan-changes" not in client.get("/").text


def test_an_empty_hour_renders_no_panel_at_all(env):
    client, conn = env
    assert client.get("/partials/plan-changes").text.strip() == ""


# ------------------------------------------------------ the enforce freeze

def test_a_fresh_untick_keeps_its_share_for_one_cycle(env):
    """The undo window has to be free. An unshare followed by a re-share
    restarts the folder on every device that holds it."""
    client, conn = env
    now = dbmod.utcnow_iso()
    dbmod.upsert_machine(conn, "ruskin", "EDIT-PC", now, syncthing_device_id="DEV-A")
    dbmod.add_selection(conn, "ruskin", "ff4", "owen", now, machine="EDIT-PC")
    conn.commit()
    machine_devices = {("ruskin", "EDIT-PC"): "DEV-A"}

    dbmod.remove_selection(conn, "ruskin", "ff4", machine="EDIT-PC")
    dbmod.audit(conn, "owen", dbmod.AUDIT_UNTICK, "ff4", {
        "editor": "ruskin", "slug": "ff4", "machine": "EDIT-PC",
        "before": [{"machine": "EDIT-PC", "mode": "full"}], "after": [],
    })
    conn.commit()
    frozen = dbmod.recent_plan_change_devices(conn, dbmod.utcnow_iso(), machine_devices)
    assert frozen["ff4"] == frozenset({"DEV-A"})

    # A minute later the freeze has lifted and the unshare proceeds.
    later = dbmod._iso_minus(dbmod.utcnow_iso(), -(dbmod.PLAN_FREEZE_SECONDS + 5))
    assert dbmod.recent_plan_change_devices(conn, later, machine_devices) == {}


def test_a_tick_stamps_changed_at_and_a_mode_switch_restamps_it(env):
    """`created_at` cannot say when a tick last CHANGED; changed_at can. The
    enforce freeze deliberately does not read it (see
    db.recent_plan_change_devices): an upload-only tick writes a fresh row
    for a machine whose share must be removed."""
    client, conn = env
    now = dbmod.utcnow_iso()
    dbmod.upsert_machine(conn, "ruskin", "EDIT-PC", now, syncthing_device_id="DEV-A")
    dbmod.add_selection(conn, "ruskin", "ff4", "owen", now, machine="EDIT-PC")
    later = dbmod._iso_minus(now, -30)
    dbmod.add_selection(conn, "ruskin", "ff4", "owen", later, machine="EDIT-PC",
                        sync_mode=dbmod.SYNC_MODE_UPLOAD_ONLY)
    conn.commit()
    row = conn.execute(
        "SELECT created_at, changed_at FROM selections WHERE machine='EDIT-PC'").fetchone()
    assert (row["created_at"], row["changed_at"]) == (now, later)
    # A fresh tick freezes nothing: only an untick does.
    assert dbmod.recent_plan_change_devices(
        conn, later, {("ruskin", "EDIT-PC"): "DEV-A"}) == {}


# ------------------------------------------- the person-level untick confirm

def test_the_sidebar_confirm_names_the_computers_it_will_affect(env):
    """DASH-8: the checkbox is the PERSON, so unticking it stops the project
    on every computer they own. On the way OUT only: a confirm on a tick
    would be nonsense, and the same element does both."""
    client, conn = env
    report(client, "ruskin", "EDIT-PC", machine_id="mid-1")
    report(client, "ruskin", "LAPTOP", machine_id="mid-2")
    page = client.get("/?as=ruskin")
    assert page.status_code == 200
    assert "hx-confirm=\"This removes" not in page.text      # nothing ticked yet

    client.put("/api/v1/selection/ruskin/ff4")
    page = client.get("/?as=ruskin").text
    assert ("This removes 2025/FF4 from ruskin's 2 computers (EDIT-PC, LAPTOP)"
            in page)


def test_the_project_page_untick_button_carries_the_same_confirm(env):
    client, conn = env
    report(client, "ruskin", "EDIT-PC", machine_id="mid-1")
    client.put("/api/v1/selection/ruskin/ff4")
    page = client.get("/project/ff4?as=ruskin").text
    assert "[ UNTICK FOR RUSKIN ]" in page
    assert "This removes 2025/FF4 from ruskin's 1 computer (EDIT-PC)" in page
