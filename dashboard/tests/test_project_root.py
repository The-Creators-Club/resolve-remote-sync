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


def report_headers(editor="jsmith"):
    """Both companion headers -- X-CCSync-Identity is required on reports."""
    return {"X-CCSync-Token": TOKEN,
            "X-CCSync-Identity": auth.make_identity_token(SECRET, editor)}


@pytest.fixture
def env(tmp_path):
    settings = Settings(db_path=str(tmp_path / "r.db"), session_secret=SECRET,
                        report_token=TOKEN, admin_users=frozenset({"owen"}))
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


def test_match_project_label_ignores_trivial_numeric_tokens():
    """Regression (2026-07-25): 'Event 1.EXE Videos for Event' auto-matched
    '.../Season 1' on the shared bare token '1' alone, and the sticky
    mapping wedged a brand-new project under Creator Profiles. Short
    all-digit tokens must never count as match evidence."""
    f = dbmod.match_project_label
    labels = ["2025/FF4/Nuclear", "2026/Creator Profiles/Season 1"]
    assert f("Event 1.EXE Videos for Event", labels) is None
    assert f("Part 2 Cut 1", labels) is None
    # but a real word still matches even alongside numbers
    assert f("Season 1 Recap", labels) == "2026/Creator Profiles/Season 1"


def test_confident_match_needs_two_tokens_or_an_exact_name():
    """The live 2026-07-25 miss: 'Nuclear Family Reunion' auto-mapped itself
    permanently into '2025/FF4/Nuclear' on the single shared word 'nuclear',
    and every frame that editor shot then had a destination inside an
    unrelated project. One word is a coincidence, not a match."""
    f = dbmod.match_project_label_confident
    labels = ["2025/FF4/Nuclear", "2026/Creator Profiles/Season 1"]

    # the incident itself, and its shape in general
    assert dbmod.match_project_label("Nuclear Family Reunion", labels) == "2025/FF4/Nuclear"
    assert f("Nuclear Family Reunion", labels) is None
    assert f("Season 1 Recap", labels) is None          # one token: 'season'
    assert f("Profiles of Nobody", labels) is None

    # (a) two or more shared non-trivial tokens
    assert f("CCT Creator Profiles", labels) == "2026/Creator Profiles/Season 1"
    assert f("FF4 Nuclear Cut", labels) == "2025/FF4/Nuclear"

    # (b) the name IS the project: final path segment, or the whole label
    assert f("Nuclear", labels) == "2025/FF4/Nuclear"
    assert f("  nuclear  ", labels) == "2025/FF4/Nuclear"
    assert f("Season 1", labels) == "2026/Creator Profiles/Season 1"
    assert f("2025/FF4/Nuclear", labels) == "2025/FF4/Nuclear"

    # ...and everything match_project_label already refused stays refused
    assert f("Totally Unrelated", labels) is None
    assert f("2026", labels) is None
    assert f("", labels) is None


def test_report_does_not_sticky_map_a_single_token_match(env):
    client, conn = env
    headers = report_headers()
    resp = client.post("/api/v1/report", headers=headers,
                       json=report("Nuclear Family Reunion"))
    assert resp.status_code == 200
    # nothing written, and the editor is asked to pick instead
    assert resp.json()["resolve_project_unmapped"] == "Nuclear Family Reunion"
    assert conn.execute("SELECT COUNT(*) c FROM project_roots").fetchone()["c"] == 0


def test_media_tree_requires_an_explicit_mapping(env):
    """_slug_for_resolve_name used to fall back to the same loose matcher --
    and replace_media_tree WIPES the target project's whole bin tree for the
    reporting machine, so a coincidental word blew away another project's
    presence data. No mapping, no write."""
    client, conn = env
    headers = report_headers()
    payload = report("Nuclear Family Reunion")
    payload["media_tree"] = {"Nuclear Family Reunion": [
        {"bin_path": "", "clip_name": "a.braw", "file_path": "C:/a.braw", "present": True},
    ]}
    assert client.post("/api/v1/report", headers=headers, json=payload).status_code == 200
    assert conn.execute("SELECT COUNT(*) c FROM media_tree_clips").fetchone()["c"] == 0

    # with an explicit mapping the very same report lands
    dbmod.admin_set_project_root(conn, "Nuclear Family Reunion", "2025-ff4-nuclear",
                                 admin="owen", now=dbmod.utcnow_iso())
    conn.commit()
    assert client.post("/api/v1/report", headers=headers, json=payload).status_code == 200
    rows = conn.execute("SELECT project_slug FROM media_tree_clips").fetchall()
    assert [r[0] for r in rows] == ["2025-ff4-nuclear"]


def test_first_match_is_sticky(env):
    client, conn = env
    headers = report_headers()
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "owen"))  # login gate
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
    headers = report_headers()
    client.post("/api/v1/report", headers=headers, json=report("CCT Creator Profiles"))

    body = {"resolve_project": "CCT Creator Profiles", "slug": "2025-ff4-nuclear"}
    assert client.put("/api/v1/project-roots", json=body).status_code == 401
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "jsmith"))
    assert client.put("/api/v1/project-roots", json=body).status_code == 403

    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "owen"))
    resp = client.put("/api/v1/project-roots", json=body)
    assert resp.status_code == 200
    (root,) = resp.json()["project_roots"]
    assert root["slug"] == "2025-ff4-nuclear" and root["source"] == "admin"
    assert root["updated_by"] == "owen"

    # unknown slug rejected; remove -> re-detected on next report
    assert client.put("/api/v1/project-roots",
                      json={"resolve_project": "CCT Creator Profiles", "slug": "nope"}
                      ).status_code == 404
    client.put("/api/v1/project-roots",
               json={"resolve_project": "CCT Creator Profiles", "slug": None})
    assert client.get("/api/v1/project-roots").json()["project_roots"] == []


def test_unmatched_projects_surface_for_admin(env):
    client, conn = env
    headers = report_headers()
    client.post("/api/v1/report", headers=headers, json=report("Mystery Doc"))
    assert dbmod.fetch_unmapped_resolve_projects(conn) == ["Mystery Doc"]

    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "owen"))
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
    headers = report_headers()
    client.post("/api/v1/report", headers=headers, json=report("CCT Creator Profiles"))
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "jsmith"))
    page = client.get("/")
    assert "open in Resolve:" in page.text
    assert "CCT Creator Profiles" in page.text
    assert "auto-matched, fixed" in page.text


# -- FILES INTO folder browser (any folder, not only registered projects) ---


@pytest.fixture
def browse_env(tmp_path):
    projects_dir = tmp_path / "Projects"
    (projects_dir / "2026" / "CCT" / "Custom Folder").mkdir(parents=True)
    settings = Settings(db_path=str(tmp_path / "rb.db"), session_secret=SECRET,
                        report_token=TOKEN, admin_users=frozenset({"owen"}),
                        projects_dir=str(projects_dir))
    app = create_app(settings)
    with TestClient(app) as client:
        conn = dbmod.connect(tmp_path / "rb.db")
        yield client, conn
        conn.close()


def as_admin(client):
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "owen"))
    return client


def test_roots_browse_lists_folders_and_is_admin_only(browse_env):
    client, _conn = browse_env
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "jsmith"))
    assert client.get("/partials/project-roots/browse?resolve_project=Doc&rel=").status_code == 403

    r = as_admin(client).get("/partials/project-roots/browse?resolve_project=Doc&rel=2026/CCT")
    assert r.status_code == 200
    assert "Custom Folder" in r.text


def test_admin_sets_root_to_an_unregistered_folder(browse_env):
    """The browser may pick ANY folder under Projects/ -- the mapping stores
    the rel path, which is exactly what the companion's fixer consumes."""
    client, conn = browse_env
    r = as_admin(client).post("/partials/project-roots", data={
        "resolve_project": "My Documentary",
        "root_rel": "2026/CCT/Custom Folder",
    })
    assert r.status_code == 200
    row = conn.execute("SELECT * FROM project_roots WHERE resolve_project='My Documentary'").fetchone()
    assert row["project_slug"] == "2026/CCT/Custom Folder"
    assert row["source"] == "admin"

    # the companion-facing view serves the rel path verbatim
    from ccsync_dashboard.api import _project_roots_view
    (mapping,) = _project_roots_view(conn)
    assert mapping["rel_path"] == "2026/CCT/Custom Folder"


def test_root_rel_validation(browse_env):
    client, _conn = browse_env
    as_admin(client)
    assert client.post("/partials/project-roots", data={
        "resolve_project": "Doc", "root_rel": "../escape"}).status_code == 422
    assert client.post("/partials/project-roots", data={
        "resolve_project": "Doc", "root_rel": "2026/Nope"}).status_code == 404
