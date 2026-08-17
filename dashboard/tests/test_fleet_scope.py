"""What a signed-in EDITOR may read about the rest of the fleet.

COMMERCIAL_READINESS.md §C L1 "unscoped fleet reads" (2026-08-17). Every read
here used to answer the whole fleet to anyone with a session: other editors'
machine names and companion builds, their per-project completion, and -- worst
-- the actual file paths missing from a named person's laptop. Next to the
telemetry the companion already sends (open Resolve project, media manifest,
bin tree; §3's GDPR note), that is one editor inventorying another's work.

The rule: an editor sees their own machines plus SUMMARY numbers, an admin
sees everything. The summary is deliberately still there -- "is anyone behind
on this project" is a question an editor is entitled to ask, and it names
nobody.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth
from ccsync_dashboard import db as dbmod
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "test-secret"
DEV_A = "EDITORA-EDITORA-EDITORA-EDITORA-EDITORA-EDITORA-EDITORA-EDITORA"
DEV_B = "EDITORB-EDITORB-EDITORB-EDITORB-EDITORB-EDITORB-EDITORB-EDITORB"


@pytest.fixture
def env(tmp_path):
    settings = Settings(db_path=str(tmp_path / "dash.db"), report_token="sekrit",
                        session_secret=SECRET, admin_users=frozenset({"admin"}))
    app = create_app(settings)
    with TestClient(app) as client:
        conn = dbmod.connect(settings.db_path)
        seed(conn)
        yield client, conn
        conn.close()


def seed(conn):
    """Two editors, one project, one machine and one device each."""
    now = dbmod.utcnow_iso()
    pid = dbmod.upsert_project(conn, "2025-ff4-nuclear", "2025/FF4/Nuclear", "/d/x", now)
    for device_id, user in ((DEV_A, "jsmith"), (DEV_B, "editor2")):
        did = dbmod.upsert_device(conn, device_id, user, False, now)
        dbmod.upsert_completion(conn, pid, did, completion=50.0, need_items=2,
                                need_bytes=10, need_deletes=0, global_items=4,
                                global_bytes=20, now=now)
        dbmod.replace_missing_files(
            conn, pid, did, [(f"Audio/{user}-secret-project.wav", 1)], False, now)
        dbmod.upsert_machine_state(conn, user, f"{user.upper()}-PC", None, now,
                                   companion_version="0.7.9")
    conn.commit()
    return pid


def login(client, user):
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, user))
    return client


def device_row_id(conn, device_id):
    return conn.execute("SELECT id FROM devices WHERE device_id = ?",
                        (device_id,)).fetchone()["id"]


# -------------------------------------------------------------- /api/editors

def test_an_editor_sees_only_their_own_machines(env):
    client, _conn = env
    body = login(client, "jsmith").get("/api/v1/editors").json()
    assert {m["editor_username"] for m in body["editors"]} == {"jsmith"}
    assert body["machines_hidden"] == 1


def test_an_editor_still_gets_fleet_summary_numbers(env):
    client, _conn = env
    body = login(client, "jsmith").get("/api/v1/editors").json()
    assert body["summary"]["machines_total"] == 2      # counts, not names
    assert "editor2" not in repr(body)


def test_an_admin_sees_every_machine(env):
    client, _conn = env
    body = login(client, "admin").get("/api/v1/editors").json()
    assert {m["editor_username"] for m in body["editors"]} == {"jsmith", "editor2"}
    assert body["summary"]["machines_total"] == 2


def test_an_admin_can_focus_one_editor_with_as(env):
    client, _conn = env
    body = login(client, "admin").get("/api/v1/editors?as=editor2").json()
    assert {m["editor_username"] for m in body["editors"]} == {"editor2"}


# ------------------------------------------------------------- /api/projects

def test_project_rows_hide_other_editors_devices(env):
    client, _conn = env
    body = login(client, "jsmith").get("/api/v1/projects").json()
    project = body["projects"][0]
    assert {e["editor_username"] for e in project["editors"]} == {"jsmith"}
    assert project["editors_hidden"] == 1
    # The project-level totals survive -- that is the summary an editor needs.
    assert project["editors_behind"] == 2


def test_project_detail_hides_other_editors(env):
    client, _conn = env
    body = login(client, "jsmith").get("/api/v1/projects/2025-ff4-nuclear").json()
    assert {e["editor_username"] for e in body["editors"]} == {"jsmith"}
    assert "editor2" not in repr(body["editors"])


# --------------------------------------------------------------- missing files

def test_missing_files_for_another_editor_are_a_404(env):
    """404, not 403: an editor must not even learn that device id exists here."""
    client, _conn = env
    login(client, "jsmith")
    r = client.get(f"/api/v1/projects/2025-ff4-nuclear/devices/{DEV_B}/missing")
    assert r.status_code == 404
    assert "editor2-secret-project" not in r.text


def test_an_editor_can_still_read_their_own_missing_files(env):
    client, _conn = env
    login(client, "jsmith")
    r = client.get(f"/api/v1/projects/2025-ff4-nuclear/devices/{DEV_A}/missing")
    assert r.status_code == 200
    assert "jsmith-secret-project" in r.text


def test_the_html_partial_applies_the_same_rule(env):
    client, _conn = env
    login(client, "jsmith")
    assert client.get(
        f"/partials/project/2025-ff4-nuclear/missing/{DEV_B}").status_code == 404
    assert client.get(
        f"/partials/project/2025-ff4-nuclear/missing/{DEV_A}").status_code == 200


def test_an_admin_reads_anybody_s_missing_files(env):
    client, _conn = env
    login(client, "admin")
    r = client.get(f"/api/v1/projects/2025-ff4-nuclear/devices/{DEV_B}/missing")
    assert r.status_code == 200


def test_the_fleet_page_renders_for_an_editor(env):
    """Scoping must not break the page it scopes."""
    client, _conn = env
    r = login(client, "jsmith").get("/")
    assert r.status_code == 200
    assert "EDITOR2-PC" not in r.text
    # ...and it still says how big the fleet is, without naming anyone.
    assert "other machine(s) in" in r.text


def test_the_fleet_page_shows_an_admin_everything_and_no_hidden_line(env):
    client, _conn = env
    r = login(client, "admin").get("/")
    assert r.status_code == 200
    assert "EDITOR2-PC" in r.text
    assert "other machine(s) in" not in r.text
