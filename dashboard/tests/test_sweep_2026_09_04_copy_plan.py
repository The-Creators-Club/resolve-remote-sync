"""DCORE-2 (usability/resilience sweep 2026-09-04): "copy from ..." wiped a
computer's plan with no refusal, no audit row, no [ UNDO ] and no enforce-cycle
grace.

The UI half (a confirm naming both sides, and a client-side refusal of an empty
source) is in static/assignments.js. This is the server half, which is the one
that matters: a client-side refusal is one curl away from bypassed, and the
route DELETEs the target's whole plan before inserting the source's rows.

Three things are asserted here, and each of them failed before this file:
  * an EMPTY source is a 409, not a silent wipe answered "ok, 0 projects";
  * the copy writes one `plan.tick` / `plan.untick` row per project, in the
    shape ui.partial_plan_change_undo replays, so it shows in RECENT PLAN
    CHANGES with a working [ UNDO ] and no template change;
  * its REMOVALS reach db.recent_plan_change_devices, so the next enforce
    cycle leaves those shares alone for 60 s exactly as an untick's do.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth
from ccsync_dashboard import db as dbmod
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "test-secret-not-a-real-one"
TOKEN = "companion-token-not-a-real-one"


@pytest.fixture
def env(tmp_path):
    db_path = tmp_path / "m.db"
    settings = Settings(db_path=str(db_path), session_secret=SECRET,
                        report_token=TOKEN, admin_users=frozenset({"owen"}))
    app = create_app(settings)
    with TestClient(app) as client:
        conn = dbmod.connect(db_path)
        now = dbmod.utcnow_iso()
        for slug in ("p1", "p2", "p3"):
            dbmod.upsert_project(conn, slug, f"2026/{slug}", f"/x/{slug}", now)
        conn.commit()
        client.cookies.set(auth.COOKIE_NAME,
                           auth.make_session_cookie(SECRET, "owen"))
        yield client, conn
        conn.close()


def _report(client, editor, machine, mode="editor"):
    r = client.post("/api/v1/report", json={
        "editor_name": editor, "machine": machine, "mode": mode,
        "reported_at": dbmod.utcnow_iso(), "lanes": []},
        headers={"X-CCSync-Token": TOKEN,
                 "X-CCSync-Identity": auth.make_identity_token(SECRET, editor)})
    assert r.status_code == 200, r.text


def _two_machines(client):
    _report(client, "ruskin", "FF-DESK")
    _report(client, "ruskin", "LESO-MBP")


def _copy_rows(conn):
    """The copy's own rows in RECENT PLAN CHANGES (every tick in the setup is
    audited too, which is the point of the ledger)."""
    return [c for c in dbmod.recent_plan_changes(conn, dbmod.utcnow_iso())
            if c["detail"].get("via") == dbmod.AUDIT_PLAN_COPY]


def _copy(client, source="FF-DESK", target="LESO-MBP"):
    return client.post(f"/api/v1/admin/machines/ruskin/{target}/copy-plan"
                       f"?source={source}")


# ------------------------------------------------- 1. the empty-source wipe

def test_copying_an_empty_plan_is_refused_rather_than_emptying_the_target(env):
    client, conn = env
    _two_machines(client)
    client.put("/api/v1/selection/ruskin/p1?machine=LESO-MBP")
    client.put("/api/v1/selection/ruskin/p2?machine=LESO-MBP")

    resp = _copy(client)
    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    assert "FF-DESK has no projects ticked" in detail
    assert "LESO-MBP" in detail
    # Owner's rule 2026-08-18: a hyphen, never an em dash, in copy an admin
    # reads.
    assert "—" not in detail
    # The wipe is what the 409 exists to stop: the target keeps both.
    assert [s["slug"] for s in
            dbmod.selections_for_machine(conn, "ruskin", "LESO-MBP")] == ["p1", "p2"]
    # And nothing was recorded for the copy, because nothing happened (the
    # two ticks above are audited, as every tick is).
    assert _copy_rows(conn) == []
    assert dbmod.fetch_audit(conn, actions=(dbmod.AUDIT_PLAN_COPY,)) == []


def test_the_refusal_survives_the_target_having_no_plan_at_all(env):
    """Both sides empty is still a refusal, not a 200 saying "0 projects"."""
    client, conn = env
    _two_machines(client)
    resp = _copy(client)
    assert resp.status_code == 409, resp.text


# ------------------------------------------- 2. the audit row and the undo

def test_a_copy_writes_one_undoable_row_per_project(env):
    client, conn = env
    _two_machines(client)
    client.put("/api/v1/selection/ruskin/p1?machine=FF-DESK")
    client.put("/api/v1/selection/ruskin/p2?machine=FF-DESK&mode=upload_only")
    # The target holds one project the source does not: the removal.
    client.put("/api/v1/selection/ruskin/p3?machine=LESO-MBP")

    resp = _copy(client)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["projects"] == 2
    assert body["added"] == ["p1", "p2"] and body["removed"] == ["p3"]

    mine = _copy_rows(conn)
    assert {(c["action"], c["detail"]["slug"]) for c in mine} == {
        (dbmod.AUDIT_TICK, "p1"),
        (dbmod.AUDIT_TICK, "p2"),
        (dbmod.AUDIT_UNTICK, "p3"),
    }
    for row in mine:
        # The shape ui.partial_plan_change_undo replays: an action it accepts,
        # an editor, a slug and the placements either side.
        assert row["action"] in (dbmod.AUDIT_TICK, dbmod.AUDIT_UNTICK)
        assert row["detail"]["editor"] == "ruskin"
        assert row["detail"]["machine"] == "LESO-MBP"
        assert row["detail"]["scope"] == "machine"
        assert row["detail"]["copied_from"] == "FF-DESK"
        assert isinstance(row["detail"]["before"], list)
        assert isinstance(row["detail"]["after"], list)
        assert row["undone"] is False

    # The summary row is for the fleet timeline, beside them.
    summary = dbmod.fetch_audit(conn, actions=(dbmod.AUDIT_PLAN_COPY,))
    assert len(summary) == 1
    assert summary[0]["detail"]["source"] == "FF-DESK"
    assert summary[0]["detail"]["removed"] == ["p3"]


def test_the_undo_puts_back_a_project_the_copy_removed(env):
    client, conn = env
    _two_machines(client)
    client.put("/api/v1/selection/ruskin/p1?machine=FF-DESK")
    client.put("/api/v1/selection/ruskin/p3?machine=LESO-MBP&mode=upload_only")
    assert _copy(client).status_code == 200
    assert dbmod.selection_placements(conn, "ruskin", "p3") == []

    untick = [r for r in dbmod.fetch_audit(conn, actions=(dbmod.AUDIT_UNTICK,))
              if r["detail"]["slug"] == "p3"][0]
    assert client.post(f"/partials/plan-changes/{untick['id']}/undo").status_code == 200
    # Back on the same computer AND in the same mode: that is what makes the
    # record a restore rather than a re-tick.
    assert dbmod.selection_placements(conn, "ruskin", "p3") == [
        {"machine": "LESO-MBP", "mode": "upload_only"}]


def test_the_undo_can_also_remove_a_project_the_copy_added(env):
    client, conn = env
    _two_machines(client)
    client.put("/api/v1/selection/ruskin/p1?machine=FF-DESK")
    client.put("/api/v1/selection/ruskin/p2?machine=LESO-MBP")
    assert _copy(client).status_code == 200

    tick = [r for r in dbmod.fetch_audit(conn, actions=(dbmod.AUDIT_TICK,))
            if r["detail"]["slug"] == "p1"
            and r["detail"].get("via") == dbmod.AUDIT_PLAN_COPY][0]
    assert client.post(f"/partials/plan-changes/{tick['id']}/undo").status_code == 200
    assert dbmod.selection_placements(conn, "ruskin", "p1", machine="LESO-MBP") == []


def test_a_copy_that_changes_nothing_writes_no_plan_change_rows(env):
    """Two identical plans: the summary row is written, the panel is not
    filled with three rows that say nothing changed."""
    client, conn = env
    _two_machines(client)
    client.put("/api/v1/selection/ruskin/p1?machine=FF-DESK")
    client.put("/api/v1/selection/ruskin/p1?machine=LESO-MBP")
    assert _copy(client).status_code == 200
    assert _copy_rows(conn) == []
    assert len(dbmod.fetch_audit(conn, actions=(dbmod.AUDIT_PLAN_COPY,))) == 1


# ------------------------------------------------------ 3. the 60 s grace

def test_the_projects_a_copy_removed_get_the_grace_an_untick_gets(env):
    client, conn = env
    _two_machines(client)
    client.put("/api/v1/selection/ruskin/p1?machine=FF-DESK")
    client.put("/api/v1/selection/ruskin/p3?machine=LESO-MBP")
    assert _copy(client).status_code == 200

    devices = {("ruskin", "LESO-MBP"): "DEVICE-1", ("ruskin", "FF-DESK"): "DEVICE-2"}
    frozen = dbmod.recent_plan_change_devices(conn, dbmod.utcnow_iso(), devices)
    # p3's share on the wiped computer is left exactly as the cycle finds it,
    # so the undo above costs Syncthing nothing.
    assert "DEVICE-1" in frozen.get("p3", frozenset())
    # A project the copy ADDED is not frozen: undoing a tick just removes
    # what it added, which costs one cycle (the rule the function documents).
    assert "p1" not in frozen
