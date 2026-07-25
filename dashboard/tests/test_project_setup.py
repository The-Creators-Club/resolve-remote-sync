"""New-project onboarding tests: the report response's unmapped flag, the
tiered first-set permission on project-roots, the /project-setup page +
create flow (template folders on disk), and the deactivation grace window."""
from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth
from ccsync_dashboard import db as dbmod
from ccsync_dashboard.app import create_app
from ccsync_dashboard.provision import TEMPLATE_FOLDERS
from ccsync_dashboard.settings import Settings

SECRET = "test-secret"
TOKEN = "companion-token"


def report(resolve_project=None):
    return {
        "editor_name": "jsmith", "machine": "EDIT-PC", "companion_version": "0.2.0",
        "reported_at": "2026-07-25T10:00:00+00:00",
        "resolve_project": resolve_project,
        "lanes": [{"name": "lane_a_video_up", "state": "idle"}],
    }


def as_user(client, user):
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, user))
    return client


@pytest.fixture
def env(tmp_path):
    projects_dir = tmp_path / "Projects"
    projects_dir.mkdir()
    settings = Settings(
        db_path=str(tmp_path / "s.db"), session_secret=SECRET, report_token=TOKEN,
        admin_users=frozenset({"alex"}), projects_dir=str(projects_dir),
    )
    app = create_app(settings)
    with TestClient(app) as client:
        conn = dbmod.connect(tmp_path / "s.db")
        now = dbmod.utcnow_iso()
        dbmod.upsert_project(conn, "2025-ff4-nuclear", "2025/FF4/Nuclear", "/x", now)
        conn.commit()
        yield client, conn, projects_dir
        conn.close()


# -- report response flag -----------------------------------------------


def test_report_flags_unmapped_project(env):
    client, _conn, _pd = env
    headers = {"X-CCSync-Token": TOKEN}
    resp = client.post("/api/v1/report", headers=headers, json=report("Mystery Doc"))
    assert resp.json()["resolve_project_unmapped"] == "Mystery Doc"


def test_report_flag_absent_when_matched_or_mapped_or_no_project(env):
    client, conn, _pd = env
    headers = {"X-CCSync-Token": TOKEN}
    # auto-match succeeds -> absent
    resp = client.post("/api/v1/report", headers=headers, json=report("FF4 Nuclear Cut"))
    assert "resolve_project_unmapped" not in resp.json()
    # explicitly mapped -> absent
    dbmod.admin_set_project_root(conn, "Mystery Doc", "2025-ff4-nuclear",
                                 admin="alex", now=dbmod.utcnow_iso())
    conn.commit()
    resp = client.post("/api/v1/report", headers=headers, json=report("Mystery Doc"))
    assert "resolve_project_unmapped" not in resp.json()
    # no project open -> absent
    resp = client.post("/api/v1/report", headers=headers, json=report(None))
    assert "resolve_project_unmapped" not in resp.json()


# -- tiered permission on PUT /project-roots -----------------------------


def test_editor_can_first_set_unmapped(env):
    client, _conn, _pd = env
    body = {"resolve_project": "Fresh Doc", "slug": "2025-ff4-nuclear"}
    assert client.put("/api/v1/project-roots", json=body).status_code == 401
    as_user(client, "jsmith")
    resp = client.put("/api/v1/project-roots", json=body)
    assert resp.status_code == 200
    (root,) = resp.json()["project_roots"]
    assert root["source"] == "editor"
    assert root["updated_by"] == "jsmith"


def test_editor_cannot_change_or_delete_existing(env):
    client, conn, _pd = env
    dbmod.admin_set_project_root(conn, "Fresh Doc", "2025-ff4-nuclear",
                                 admin="alex", now=dbmod.utcnow_iso())
    conn.commit()
    as_user(client, "jsmith")
    assert client.put("/api/v1/project-roots",
                      json={"resolve_project": "Fresh Doc", "slug": "2025-ff4-nuclear"}
                      ).status_code == 403
    assert client.put("/api/v1/project-roots",
                      json={"resolve_project": "Fresh Doc", "slug": None}
                      ).status_code == 403
    as_user(client, "alex")
    assert client.put("/api/v1/project-roots",
                      json={"resolve_project": "Fresh Doc", "slug": None}
                      ).status_code == 200


# -- create flow ---------------------------------------------------------


def create_body(**overrides):
    body = {"year": "2026", "series": "Creator Profiles", "project": "Season 2",
            "resolve_project": "CP S2 Edit"}
    body.update(overrides)
    return body


def test_create_project_makes_template_and_maps(env):
    client, conn, projects_dir = env
    as_user(client, "jsmith")
    resp = client.post("/api/v1/projects", json=create_body())
    assert resp.status_code == 200
    body = resp.json()
    assert body["slug"] == "2026-creator-profiles-season-2"
    assert body["mapped"] is True

    target = projects_dir / "2026" / "Creator Profiles" / "Season 2"
    for sub in TEMPLATE_FOLDERS:
        assert (target / sub).is_dir(), f"missing template folder {sub}"

    row = conn.execute("SELECT * FROM projects WHERE slug=?", (body["slug"],)).fetchone()
    assert row["active"] == 1
    assert row["label"] == "2026/Creator Profiles/Season 2"
    assert row["path"].endswith("/2026/Creator Profiles/Season 2")

    root = conn.execute("SELECT * FROM project_roots WHERE resolve_project=?",
                        ("CP S2 Edit",)).fetchone()
    assert root["project_slug"] == body["slug"]
    assert root["source"] == "editor"

    # idempotent re-post (partial-create convergence)
    assert client.post("/api/v1/projects", json=create_body()).status_code == 200


def test_create_rejects_bad_input(env):
    client, _conn, _pd = env
    as_user(client, "jsmith")
    assert client.post("/api/v1/projects", json=create_body(year="26")).status_code == 422
    assert client.post("/api/v1/projects", json=create_body(series="a/b")).status_code == 422
    assert client.post("/api/v1/projects", json=create_body(project="..evil")).status_code == 422
    assert client.post("/api/v1/projects", json=create_body(project=".hidden")).status_code == 422


def test_create_slug_collision(env):
    client, _conn, _pd = env
    as_user(client, "jsmith")
    # existing project 2025-ff4-nuclear has label 2025/FF4/Nuclear; a create
    # producing the same slug from a DIFFERENT rel must be rejected.
    resp = client.post("/api/v1/projects", json=create_body(
        year="2025", series="FF4", project="nuclear"))
    # same slug, same normalized rel? "2025/FF4/nuclear" != "2025/FF4/Nuclear" label
    assert resp.status_code == 422
    assert "different project" in resp.json()["detail"]


def test_create_degrades_without_projects_dir(tmp_path):
    settings = Settings(db_path=str(tmp_path / "d.db"), session_secret=SECRET,
                        report_token=TOKEN, projects_dir="")
    app = create_app(settings)
    with TestClient(app) as client:
        as_user(client, "jsmith")
        resp = client.post("/api/v1/projects", json=create_body())
        assert resp.status_code == 422
        assert "setup_tree.py" in resp.json()["detail"]


# -- /project-setup page -------------------------------------------------


def test_page_redirects_anon_with_next(env):
    client, _conn, _pd = env
    resp = client.get("/project-setup?resolve_project=Mystery%20Doc",
                      follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/login?next=")
    assert "project-setup" in resp.headers["location"]


def test_page_shows_link_and_create_boxes(env):
    client, _conn, _pd = env
    as_user(client, "jsmith")
    page = client.get("/project-setup?resolve_project=Mystery Doc")
    assert page.status_code == 200
    assert "[ LINK TO AN EXISTING PROJECT ]" in page.text
    assert "[ OR CREATE A NEW PROJECT ]" in page.text
    assert "2025/FF4/Nuclear" in page.text


def test_page_shows_mapping_when_already_set(env):
    client, conn, _pd = env
    dbmod.admin_set_project_root(conn, "Mystery Doc", "2025-ff4-nuclear",
                                 admin="alex", now=dbmod.utcnow_iso())
    conn.commit()
    as_user(client, "jsmith")
    page = client.get("/project-setup?resolve_project=Mystery Doc")
    assert "[ ALREADY SET UP ]" in page.text
    assert "2025/FF4/Nuclear" in page.text


def test_partial_link_first_set(env):
    client, conn, _pd = env
    as_user(client, "jsmith")
    resp = client.post("/partials/project-setup/link",
                       data={"resolve_project": "Mystery Doc", "root": "2025-ff4-nuclear"})
    assert resp.status_code == 200
    assert "[ ALREADY SET UP ]" in resp.text
    root = conn.execute("SELECT * FROM project_roots WHERE resolve_project=?",
                        ("Mystery Doc",)).fetchone()
    assert root["source"] == "editor" and root["updated_by"] == "jsmith"


def test_partial_create_flow(env):
    client, _conn, projects_dir = env
    as_user(client, "jsmith")
    resp = client.post("/partials/project-setup/create", data={
        "resolve_project": "CP S2 Edit", "year": "2026",
        "series": "Creator Profiles", "project": "Season 2",
    })
    assert resp.status_code == 200
    assert "[ CREATED ]" in resp.text
    assert (projects_dir / "2026" / "Creator Profiles" / "Season 2" / "B-roll").is_dir()


# -- deactivation grace ---------------------------------------------------


def test_deactivate_missing_projects_grace(env):
    _client, conn, _pd = env
    now = dbmod.utcnow_iso()
    old = (dbmod.parse_iso(now) - dt.timedelta(hours=2)).isoformat()
    dbmod.upsert_project(conn, "fresh-project", "2026/X/Fresh", "/f", now)
    conn.execute("UPDATE projects SET last_seen=? WHERE slug=?", (old, "2025-ff4-nuclear"))
    conn.commit()

    dbmod.deactivate_missing_projects(conn, seen_slugs=[], now=now)
    conn.commit()
    fresh = conn.execute("SELECT active FROM projects WHERE slug='fresh-project'").fetchone()
    stale = conn.execute("SELECT active FROM projects WHERE slug='2025-ff4-nuclear'").fetchone()
    assert fresh["active"] == 1   # inside the grace window -- survives
    assert stale["active"] == 0   # genuinely missing -- deactivated
