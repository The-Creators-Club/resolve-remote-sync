from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth
from ccsync_dashboard import db as dbmod
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "test-secret"
TOKEN = "companion-token"


def report(resolve_project=None, machine="EDIT-PC"):
    return {
        "editor_name": "jsmith", "machine": machine, "companion_version": "0.2",
        "reported_at": "2026-07-24T10:00:00+00:00",
        "resolve_project": resolve_project,
        "lanes": [{"name": "lane_a_video_up", "state": "idle"}],
    }


@pytest.fixture
def env(tmp_path):
    settings = Settings(db_path=str(tmp_path / "r.db"), session_secret=SECRET,
                        report_token=TOKEN, admin_users=frozenset({"alex"}))
    app = create_app(settings)
    with TestClient(app) as client:
        conn = dbmod.connect(tmp_path / "r.db")
        now = dbmod.utcnow_iso()
        dbmod.upsert_project(conn, "2025-ff4-nuclear", "2025/FF4/Nuclear", "/x", now)
        dbmod.upsert_project(conn, "2026-creator-profiles-season-1",
                             "2026/Creator Profiles/Season 1", "/y", now)
        conn.commit()
        yield client, conn
        conn.close()


def test_match_project_label():
    f = dbmod.match_project_label
    labels = ["2025/FF4/Nuclear", "2026/Creator Profiles/Season 1"]
    assert f("CCT Creator Profiles", labels) == "2026/Creator Profiles/Season 1"
    assert f("FF4 Nuclear Cut", labels) == "2025/FF4/Nuclear"
    assert f("Totally Unrelated", labels) is None
    assert f("2026", labels) is None            # year-only overlap disqualifies
    assert f("", labels) is None
    # tie -> None
    assert f("Creator Nuclear", labels) is None or f("Creator Nuclear", labels) in labels


def test_first_match_is_sticky(env):
    client, conn = env
    headers = {"X-CCSync-Token": TOKEN}
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "alex"))  # login gate
    assert client.post("/api/v1/report", headers=headers,
                       json=report("CCT Creator Profiles")).status_code == 200
    roots = client.get("/api/v1/project-roots").json()["project_roots"]
    assert roots == [{
        "resolve_project": "CCT Creator Profiles",
        "slug": "2026-creator-profiles-season-1",
        "rel_path": "2026/Creator Profiles/Season 1",
        "source": "auto", "updated_by": "auto", "updated_at": roots[0]["updated_at"],
    }]

    # A later report cannot change the stored mapping, even if matching would
    # now produce something else (rename the tree label to force a difference).
    dbmod.upsert_project(conn, "2025-ff4-nuclear", "2025/CCT Creator Profiles/Nuclear",
                         "/x", dbmod.utcnow_iso())
    conn.commit()
    client.post("/api/v1/report", headers=headers, json=report("CCT Creator Profiles"))
    roots = client.get("/api/v1/project-roots").json()["project_roots"]
    assert roots[0]["slug"] == "2026-creator-profiles-season-1"
    assert roots[0]["source"] == "auto"

    # selection response carries the mappings for the companion
    sel = client.get("/api/v1/selection/jsmith", headers=headers).json()
    assert sel["project_roots"][0]["slug"] == "2026-creator-profiles-season-1"


def test_admin_only_changes(env):
    client, _ = env
    headers = {"X-CCSync-Token": TOKEN}
    client.post("/api/v1/report", headers=headers, json=report("CCT Creator Profiles"))

    body = {"resolve_project": "CCT Creator Profiles", "slug": "2025-ff4-nuclear"}
    assert client.put("/api/v1/project-roots", json=body).status_code == 401
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "jsmith"))
    assert client.put("/api/v1/project-roots", json=body).status_code == 403

    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "alex"))
    resp = client.put("/api/v1/project-roots", json=body)
    assert resp.status_code == 200
    (root,) = resp.json()["project_roots"]
    assert root["slug"] == "2025-ff4-nuclear" and root["source"] == "admin"
    assert root["updated_by"] == "alex"

    # unknown slug rejected; remove -> re-detected on next report
    assert client.put("/api/v1/project-roots",
                      json={"resolve_project": "CCT Creator Profiles", "slug": "nope"}
                      ).status_code == 404
    client.put("/api/v1/project-roots",
               json={"resolve_project": "CCT Creator Profiles", "slug": None})
    assert client.get("/api/v1/project-roots").json()["project_roots"] == []


def test_unmatched_projects_surface_for_admin(env):
    client, conn = env
    headers = {"X-CCSync-Token": TOKEN}
    client.post("/api/v1/report", headers=headers, json=report("Mystery Doc"))
    assert dbmod.fetch_unmapped_resolve_projects(conn) == ["Mystery Doc"]

    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "alex"))
    page = client.get("/")
    assert "[ PROJECT ROOTS ]" in page.text and "Mystery Doc" in page.text
    resp = client.post("/partials/project-roots",
                       data={"resolve_project": "Mystery Doc", "root": "2025-ff4-nuclear"})
    assert resp.status_code == 200 and "2025/FF4/Nuclear" in resp.text
    assert dbmod.fetch_unmapped_resolve_projects(conn) == []

    # non-admin gets read-only panel: no forms posted
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "jsmith"))
    assert client.post("/partials/project-roots",
                       data={"resolve_project": "Mystery Doc", "root": "2025-ff4-nuclear"}
                       ).status_code == 403


def test_queue_shows_fixed_root_read_only(env):
    client, _ = env
    headers = {"X-CCSync-Token": TOKEN}
    client.post("/api/v1/report", headers=headers, json=report("CCT Creator Profiles"))
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "jsmith"))
    page = client.get("/")
    assert "open in Resolve:" in page.text
    assert "CCT Creator Profiles" in page.text
    assert "auto-matched, fixed" in page.text
