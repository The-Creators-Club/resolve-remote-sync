"""The link-authoring endpoints (SHARED_FOLDERS_PLAN.md WP5): the marker is
edited in place, every other key survives, and the project_links mirror
answers immediately."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth
from ccsync_dashboard import db as dbmod
from ccsync_dashboard import provision
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "test-secret"

BORROWER = "2026/FF5/Elections"
LENDER = "2026/FF5/Civil Defence"
SUB = "Interviewees/Aha Chu"
B_SLUG = "2026-ff5-elections"
L_SLUG = "2026-ff5-civil-defence"


@pytest.fixture
def env(tmp_path):
    projects = tmp_path / "Projects"
    for rel, slug in ((BORROWER, B_SLUG), (LENDER, L_SLUG)):
        d = projects / rel
        d.mkdir(parents=True)
        provision.write_marker(d, slug)
    (projects / LENDER / SUB).mkdir(parents=True)

    settings = Settings(db_path=str(tmp_path / "links.db"), session_secret=SECRET,
                        admin_users=frozenset({"owen"}),
                        projects_dir=str(projects))
    app = create_app(settings)
    with TestClient(app) as client:
        conn = dbmod.connect(tmp_path / "links.db")
        now = dbmod.utcnow_iso()
        dbmod.upsert_project(conn, B_SLUG, BORROWER, f"/data/{B_SLUG}", now)
        dbmod.upsert_project(conn, L_SLUG, LENDER, f"/data/{L_SLUG}", now)
        conn.commit()
        yield client, conn, projects
        conn.close()


def as_user(client, user):
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, user))
    return client


def marker(projects):
    return json.loads(
        (projects / BORROWER / provision.MARKER_FILENAME).read_text(encoding="utf-8"))


def test_admin_adds_and_removes_a_link(env):
    client, conn, projects = env
    as_user(client, "owen")
    r = client.post(f"/api/v1/projects/{B_SLUG}/links",
                    json={"path": f"Projects/{LENDER}/{SUB}"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["changed"] is True
    assert body["links"][0]["status"] == "ok"
    assert body["links"][0]["lender_slug"] == L_SLUG

    data = marker(projects)
    assert data["slug"] == B_SLUG                       # identity untouched
    assert data["includes"][0]["path"] == f"Projects/{LENDER}/{SUB}"
    assert data["includes"][0]["added_by"] == "owen"

    # re-add is a no-op
    r = client.post(f"/api/v1/projects/{B_SLUG}/links",
                    json={"path": f"Projects/{LENDER}/{SUB}"})
    assert r.json()["changed"] is False

    # remove: marker key cleared, mirror rows cleared
    r = client.request("DELETE", f"/api/v1/projects/{B_SLUG}/links",
                       params={"path": f"Projects/{LENDER}/{SUB}"})
    assert r.status_code == 200
    assert r.json()["changed"] is True
    assert "includes" not in marker(projects)
    assert dbmod.fetch_links_for_borrowers(conn) == {}


def test_label_spelling_is_accepted(env):
    # people paste what the sidebar shows ("2026/FF5/...") -- the Projects/
    # prefix is supplied for them
    client, conn, projects = env
    as_user(client, "owen")
    r = client.post(f"/api/v1/projects/{B_SLUG}/links",
                    json={"path": f"{LENDER}/{SUB}"})
    assert r.status_code == 200
    assert marker(projects)["includes"][0]["path"] == f"Projects/{LENDER}/{SUB}"


def test_refusals_carry_the_validators_reason(env):
    client, conn, projects = env
    as_user(client, "owen")
    r = client.post(f"/api/v1/projects/{B_SLUG}/links",
                    json={"path": f"Projects/{LENDER}/{SUB}/Proxy"})
    assert r.status_code == 422
    assert "Proxy" in r.json()["detail"]
    r = client.post(f"/api/v1/projects/{B_SLUG}/links",
                    json={"path": f"Projects/{LENDER}"})
    assert r.status_code == 422
    assert "tick both projects" in r.json()["detail"]
    # a folder that does not exist is not addable (missing links come from
    # the tree drifting later, not from authoring)
    r = client.post(f"/api/v1/projects/{B_SLUG}/links",
                    json={"path": f"Projects/{LENDER}/Interviewees/Nobody"})
    assert r.status_code == 422


def test_ticked_editor_may_edit_others_may_not(env):
    client, conn, projects = env
    dbmod.add_selection(conn, "jsmith", B_SLUG, "jsmith", dbmod.utcnow_iso())
    dbmod.record_known_editor(conn, "jsmith", "test", dbmod.utcnow_iso())
    conn.commit()
    as_user(client, "jsmith")
    r = client.post(f"/api/v1/projects/{B_SLUG}/links",
                    json={"path": f"Projects/{LENDER}/{SUB}"})
    assert r.status_code == 200

    as_user(client, "stranger")
    r = client.request("DELETE", f"/api/v1/projects/{B_SLUG}/links",
                       params={"path": f"Projects/{LENDER}/{SUB}"})
    assert r.status_code == 403


def test_marker_extra_keys_survive_the_edit(env):
    client, conn, projects = env
    d = projects / BORROWER
    data = provision.read_marker_data(d)
    data["future_key"] = {"kept": True}
    provision.write_marker_data(d, data)
    as_user(client, "owen")
    client.post(f"/api/v1/projects/{B_SLUG}/links",
                json={"path": f"Projects/{LENDER}/{SUB}"})
    assert marker(projects)["future_key"] == {"kept": True}
