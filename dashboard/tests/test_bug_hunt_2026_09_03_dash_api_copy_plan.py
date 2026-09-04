"""bug-hunt 2026-09-03, dash-db-1's api half: copying a plan FROM a wired
computer.

A base rig holds no tick (CR-28), and since dash-db-1 it no longer inherits
the unassigned bucket either, so its plan reads empty. `db.copy_machine_plan`
raises rather than copying nothing; if this route did not catch that, "same as
the desktop, please" would be a 500 - and before the raise it was worse, a 200
saying "0 projects" that an admin reads as done.
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
        dbmod.upsert_project(conn, "p1", "2026/One", "/x", now)
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


def test_copying_from_a_wired_computer_is_a_409_not_a_500(env):
    client, conn = env
    _report(client, "ruskin", "BASE-RIG", mode="base")
    _report(client, "ruskin", "LAPTOP-1")
    assert ("ruskin", "BASE-RIG") in dbmod.base_machines(conn)

    r = client.post(
        "/api/v1/admin/machines/ruskin/LAPTOP-1/copy-plan?source=BASE-RIG")
    assert r.status_code == 409, r.text
    assert "wired to the server" in r.json()["detail"]
    assert "—" not in r.json()["detail"]
    # Nothing was written on the way to the refusal.
    assert dbmod.selections_for_machine(conn, "ruskin", "LAPTOP-1") == []


def test_a_copy_between_two_editor_machines_still_works(env):
    client, conn = env
    _report(client, "ruskin", "DESKTOP-1")
    _report(client, "ruskin", "LAPTOP-1")
    client.put("/api/v1/selection/ruskin/p1?machine=DESKTOP-1")

    r = client.post(
        "/api/v1/admin/machines/ruskin/LAPTOP-1/copy-plan?source=DESKTOP-1")
    assert r.status_code == 200, r.text
    assert r.json()["projects"] == 1
    assert [s["slug"] for s in
            dbmod.selections_for_machine(conn, "ruskin", "LAPTOP-1")] == ["p1"]
