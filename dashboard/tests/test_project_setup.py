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


def reported(conn, name, editor="jsmith", machine="EDIT-PC"):
    """Model the real order of events: a companion reports the Resolve
    project it has open (that is what raises the NEW PROJECT prompt in the
    first place), and only THEN can that editor claim a folder for it.
    Non-admins may first-claim only names their own machines have reported --
    see api.may_first_claim."""
    dbmod.upsert_machine_state(conn, editor, machine, None, dbmod.utcnow_iso(),
                               resolve_project=name)
    conn.commit()


def report_headers(editor="jsmith"):
    """Both companion headers. X-CCSync-Identity is REQUIRED on every report
    now that the shared report token alone no longer proves who is reporting
    (see the report-endpoint identity finding)."""
    return {"X-CCSync-Token": TOKEN,
            "X-CCSync-Identity": auth.make_identity_token(SECRET, editor)}


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
    headers = report_headers()
    resp = client.post("/api/v1/report", headers=headers, json=report("Mystery Doc"))
    assert resp.json()["resolve_project_unmapped"] == "Mystery Doc"


def test_report_flag_absent_when_matched_or_mapped_or_no_project(env):
    client, conn, _pd = env
    headers = report_headers()
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


def test_report_ignores_scratch_resolve_projects(env):
    """'New Doc' (Blackmagic Proxy Generator) and 'Untitled Project' must never
    be flagged unmapped, sticky-matched, or stored in machine_state -- even
    when reported by an old companion with no client-side filter."""
    client, conn, _pd = env
    headers = report_headers()
    for name in (
        "New Doc", "new doc", "Untitled Project",
        # Resolve's numbered duplicates and sloppy whitespace -- same prefix
        # rule as the companion's config.is_ignored_project.
        "New Doc 1", "New Doc (3)", "New Doc_6", "Untitled Project 12",
        "New  Doc",
    ):
        resp = client.post("/api/v1/report", headers=headers, json=report(name))
        assert resp.status_code == 200
        assert "resolve_project_unmapped" not in resp.json(), name
    rows = conn.execute("SELECT * FROM project_roots").fetchall()
    assert rows == []
    state = conn.execute(
        "SELECT resolve_project FROM machine_state WHERE editor_username='jsmith'"
    ).fetchone()
    assert state["resolve_project"] is None


def test_report_similar_real_names_are_not_ignored(env):
    """'New Documentary' / 'New Doc Final' are real projects: only a trailing
    number may follow an ignored name."""
    client, _conn, _pd = env
    headers = report_headers()
    for name in ("New Documentary", "New Doc Final", "Untitled Projection"):
        resp = client.post("/api/v1/report", headers=headers, json=report(name))
        assert resp.status_code == 200
        assert resp.json().get("resolve_project_unmapped") == name


# -- tiered permission on PUT /project-roots -----------------------------


def test_editor_can_first_set_unmapped(env):
    client, conn, _pd = env
    reported(conn, "Fresh Doc")
    body = {"resolve_project": "Fresh Doc", "slug": "2025-ff4-nuclear"}
    assert client.put("/api/v1/project-roots", json=body).status_code == 401
    as_user(client, "jsmith")
    resp = client.put("/api/v1/project-roots", json=body)
    assert resp.status_code == 200
    (root,) = resp.json()["project_roots"]
    assert root["source"] == "editor"
    assert root["updated_by"] == "jsmith"


def test_first_set_is_scoped_to_your_own_reported_projects(env):
    """An editor could first-claim ANY unmapped Resolve project name --
    including one only somebody ELSE's companion had ever opened -- and
    permanently fix where that editor's media gets written. Non-admins may
    now only claim names their own machines have reported."""
    client, conn, _pd = env
    reported(conn, "Ruskins Doc", editor="ruskin", machine="RUSKIN-PC")
    body = {"resolve_project": "Ruskins Doc", "slug": "2025-ff4-nuclear"}

    as_user(client, "jsmith")
    resp = client.put("/api/v1/project-roots", json=body)
    assert resp.status_code == 403
    assert "any of your machines has reported" in resp.json()["detail"]
    assert conn.execute("SELECT COUNT(*) c FROM project_roots").fetchone()["c"] == 0

    # the owner can
    as_user(client, "ruskin")
    assert client.put("/api/v1/project-roots", json=body).status_code == 200

    # ...and an admin can first-set anything, reported or not
    conn.execute("DELETE FROM project_roots")
    conn.commit()
    as_user(client, "alex")
    resp = client.put("/api/v1/project-roots",
                      json={"resolve_project": "Never Reported", "slug": "2025-ff4-nuclear"})
    assert resp.status_code == 200


def test_create_and_link_refuse_an_unreported_resolve_project(env):
    """Same rule on the /project-setup create + link flows, which reach
    sticky_project_root through _register_project."""
    client, conn, projects_dir = env
    (projects_dir / "2026" / "CCT").mkdir(parents=True)
    (projects_dir / "2026" / "CCT" / "Someone Elses Show").mkdir()
    as_user(client, "jsmith")

    resp = client.post("/api/v1/projects", json=create_body(
        parent_rel="2026/CCT", name="Season 9", resolve_project="Not Mine"))
    assert resp.status_code == 422
    assert "any of your machines has reported" in resp.json()["detail"]
    assert not (projects_dir / "2026" / "CCT" / "Season 9").exists() or \
        conn.execute("SELECT COUNT(*) c FROM project_roots").fetchone()["c"] == 0

    resp = client.post("/api/v1/projects/link", json={
        "rel": "2026/CCT/Someone Elses Show", "resolve_project": "Not Mine"})
    assert resp.status_code == 422
    assert conn.execute("SELECT COUNT(*) c FROM project_roots").fetchone()["c"] == 0

    # once the editor's own companion has reported it, the same call works
    reported(conn, "Not Mine")
    resp = client.post("/api/v1/projects/link", json={
        "rel": "2026/CCT/Someone Elses Show", "resolve_project": "Not Mine"})
    assert resp.status_code == 200 and resp.json()["mapped"] is True


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
    body = {"parent_rel": "2026/Creator Profiles", "name": "Season 2",
            "resolve_project": "CP S2 Edit"}
    body.update(overrides)
    return body


def test_create_project_makes_template_and_maps(env):
    client, conn, projects_dir = env
    (projects_dir / "2026" / "Creator Profiles").mkdir(parents=True)  # parent must exist
    reported(conn, "CP S2 Edit")
    as_user(client, "jsmith")
    resp = client.post("/api/v1/projects", json=create_body())
    assert resp.status_code == 200
    body = resp.json()
    assert body["slug"] == "2026-creator-profiles-season-2"
    assert body["mapped"] is True

    target = projects_dir / "2026" / "Creator Profiles" / "Season 2"
    for sub in TEMPLATE_FOLDERS:
        assert (target / sub).is_dir(), f"missing template folder {sub}"
    from ccsync_dashboard import provision
    assert provision.read_marker(target) == body["slug"]  # marker = identity

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
    client, _conn, projects_dir = env
    (projects_dir / "2026" / "Creator Profiles").mkdir(parents=True)
    as_user(client, "jsmith")
    assert client.post("/api/v1/projects", json=create_body(name="a/b")).status_code == 422
    assert client.post("/api/v1/projects", json=create_body(name="..evil")).status_code == 422
    assert client.post("/api/v1/projects", json=create_body(name=".hidden")).status_code == 422
    assert client.post("/api/v1/projects",
                       json=create_body(parent_rel="../escape")).status_code == 422
    assert client.post("/api/v1/projects",
                       json=create_body(parent_rel="2026/Nope")).status_code == 422  # parent absent


def test_create_rejects_control_characters(env):
    """A NUL/control character used to reach Path.resolve(), which raises
    ValueError (not OSError) -- escaping the ProjectSetupError -> 422
    handling and surfacing a 500 traceback instead."""
    client, _conn, projects_dir = env
    (projects_dir / "2026" / "Creator Profiles").mkdir(parents=True)
    as_user(client, "jsmith")
    resp = client.post("/api/v1/projects", json=create_body(name="a\x00b"))
    assert resp.status_code == 422
    resp = client.post("/api/v1/projects", json=create_body(parent_rel="a\x01b"))
    assert resp.status_code == 422


def test_validate_tree_part_rejects_control_characters_directly():
    from ccsync_dashboard.api import ProjectSetupError, _validate_tree_part

    with pytest.raises(ProjectSetupError):
        _validate_tree_part("a\x00b", "name")
    with pytest.raises(ProjectSetupError):
        _validate_tree_part("a\x1fb", "name")
    assert _validate_tree_part("normal name", "name") == "normal name"


def test_create_at_any_depth_and_at_root(env):
    client, conn, projects_dir = env
    (projects_dir / "2026" / "CCT" / "Creator Profiles").mkdir(parents=True)
    reported(conn, "CP S2 Edit")
    as_user(client, "jsmith")
    resp = client.post("/api/v1/projects", json=create_body(
        parent_rel="2026/CCT/Creator Profiles", name="Season 2"))
    assert resp.status_code == 200
    assert resp.json()["slug"] == "2026-cct-creator-profiles-season-2"
    resp = client.post("/api/v1/projects", json=create_body(
        parent_rel="", name="OneOff", resolve_project=""))
    assert resp.status_code == 200
    assert resp.json()["slug"] == "oneoff"


def test_create_inside_project_rejected(env):
    client, _conn, projects_dir = env
    from ccsync_dashboard import provision
    outer = projects_dir / "2026" / "Show"
    outer.mkdir(parents=True)
    provision.write_marker(outer, "2026-show")
    as_user(client, "jsmith")
    resp = client.post("/api/v1/projects", json=create_body(
        parent_rel="2026/Show", name="Nested"))
    assert resp.status_code == 422
    assert "inside another project" in resp.json()["detail"]


def test_create_over_a_container_of_projects_rejected(env):
    """adopt_folder scans for marked descendants; create_tree_project only
    checked ancestors and mkdir(exist_ok=True) happily reused the directory.
    'Creating' 2026/CCT over a container that already holds real projects
    dropped a marker on the container: scan_project_dirs prunes at it, the
    real projects vanish from discovery, and a Syncthing folder gets
    provisioned whose path CONTAINS three other folders' paths."""
    client, _conn, projects_dir = env
    from ccsync_dashboard import provision
    container = projects_dir / "2026" / "CCT"
    (container / "Season 1").mkdir(parents=True)
    provision.write_marker(container / "Season 1", "2026-cct-season-1")
    as_user(client, "jsmith")

    resp = client.post("/api/v1/projects", json=create_body(parent_rel="2026", name="CCT"))
    assert resp.status_code == 422
    assert "already contains a project" in resp.json()["detail"]
    assert provision.read_marker(container) is None
    # the real project is still discoverable
    assert ("2026/CCT/Season 1", "2026-cct-season-1") in \
        provision.scan_project_dirs(projects_dir)


def test_create_over_existing_folder_offers_it_instead(env):
    """The double-nesting bug: 2026/CCT/Website Highlights was already on the
    NAS, the flow's only remaining action was 'type a new folder name', and
    the admin got .../Website Highlights/Website Highlights. Creating onto an
    existing folder is now refused with the folder's rel attached so the UI
    can offer it."""
    client, _conn, projects_dir = env
    from ccsync_dashboard import provision
    existing = projects_dir / "2026" / "CCT" / "Website Highlights"
    existing.mkdir(parents=True)
    as_user(client, "jsmith")

    resp = client.post("/api/v1/projects", json=create_body(
        parent_rel="2026/CCT", name="Website Highlights"))
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert "already exists" in detail and "USE THIS FOLDER" in detail
    # nothing was created or claimed
    assert not (existing / "Website Highlights").exists()
    assert not (existing / "B-roll").exists()
    assert provision.read_marker(existing) is None


def test_create_use_existing_adopts_the_folder_in_place(env):
    """The explicit opt-in: reuse the directory (no nesting), leave its
    contents alone, add the standard subfolders + marker."""
    client, conn, projects_dir = env
    from ccsync_dashboard import provision
    existing = projects_dir / "2026" / "CCT" / "Website Highlights"
    existing.mkdir(parents=True)
    (existing / "footage.braw").write_text("x")
    reported(conn, "Website Highlights")
    as_user(client, "jsmith")

    resp = client.post("/api/v1/projects", json=create_body(
        parent_rel="2026/CCT", name="Website Highlights",
        resolve_project="Website Highlights", use_existing=True))
    assert resp.status_code == 200
    body = resp.json()
    assert body["slug"] == "2026-cct-website-highlights"
    assert not (existing / "Website Highlights").exists()   # no double nesting
    assert (existing / "footage.braw").read_text() == "x"   # contents untouched
    assert (existing / "B-roll").is_dir()
    assert provision.read_marker(existing) == body["slug"]
    row = conn.execute("SELECT label FROM projects WHERE slug=?", (body["slug"],)).fetchone()
    assert row["label"] == "2026/CCT/Website Highlights"


def test_create_slug_collision(env):
    client, _conn, projects_dir = env
    (projects_dir / "2025" / "FF4").mkdir(parents=True)
    as_user(client, "jsmith")
    # existing project 2025-ff4-nuclear has label 2025/FF4/Nuclear; a create
    # producing the same slug from a DIFFERENT rel must be rejected.
    resp = client.post("/api/v1/projects", json=create_body(
        parent_rel="2025/FF4", name="nuclear"))
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


def test_page_shows_folder_browser(env):
    client, _conn, projects_dir = env
    from ccsync_dashboard import provision
    nuclear = projects_dir / "2025" / "FF4" / "Nuclear"
    nuclear.mkdir(parents=True)
    provision.write_marker(nuclear, "2025-ff4-nuclear")
    as_user(client, "jsmith")
    page = client.get("/project-setup?resolve_project=Mystery Doc")
    assert page.status_code == 200
    assert "[ PICK THE FOLDER FOR THIS PROJECT ]" in page.text
    assert "[ OR CREATE A NEW PROJECT FOLDER HERE ]" in page.text
    assert "2025" in page.text  # top-level dir listed


def test_browse_drills_down_and_flags_projects(env):
    client, _conn, projects_dir = env
    from ccsync_dashboard import provision
    nuclear = projects_dir / "2025" / "FF4" / "Nuclear"
    nuclear.mkdir(parents=True)
    provision.write_marker(nuclear, "2025-ff4-nuclear")
    as_user(client, "jsmith")
    page = client.get("/partials/project-setup/browse?rel=2025/FF4&resolve_project=Doc")
    assert page.status_code == 200
    assert "[ PROJECT ]" in page.text     # Nuclear flagged as a project
    assert "Nuclear" in page.text


def test_browse_traversal_guard(env):
    client, _conn, _pd = env
    as_user(client, "jsmith")
    page = client.get("/partials/project-setup/browse?rel=../escape&resolve_project=Doc")
    assert page.status_code == 200        # banner-not-crash convention
    assert "must not start with" in page.text or "escape" in page.text


def test_page_shows_mapping_when_already_set(env):
    client, conn, _pd = env
    dbmod.admin_set_project_root(conn, "Mystery Doc", "2025-ff4-nuclear",
                                 admin="alex", now=dbmod.utcnow_iso())
    conn.commit()
    as_user(client, "jsmith")
    page = client.get("/project-setup?resolve_project=Mystery Doc")
    assert "[ ALREADY SET UP ]" in page.text
    assert "2025/FF4/Nuclear" in page.text


def test_partial_link_marked_folder_first_set(env):
    client, conn, projects_dir = env
    from ccsync_dashboard import provision
    nuclear = projects_dir / "2025" / "FF4" / "Nuclear"
    nuclear.mkdir(parents=True)
    provision.write_marker(nuclear, "2025-ff4-nuclear")
    reported(conn, "Mystery Doc")
    as_user(client, "jsmith")
    resp = client.post("/partials/project-setup/link",
                       data={"resolve_project": "Mystery Doc", "rel": "2025/FF4/Nuclear"})
    assert resp.status_code == 200
    root = conn.execute("SELECT * FROM project_roots WHERE resolve_project=?",
                        ("Mystery Doc",)).fetchone()
    assert root["project_slug"] == "2025-ff4-nuclear"
    assert root["source"] == "editor" and root["updated_by"] == "jsmith"


def test_link_bare_folder_adopts_it(env):
    client, conn, projects_dir = env
    from ccsync_dashboard import provision
    bare = projects_dir / "2026" / "CCT" / "Event 1.exe Videos for Event"
    bare.mkdir(parents=True)
    reported(conn, "Event 1.EXE Videos for Event")
    as_user(client, "jsmith")
    resp = client.post("/api/v1/projects/link", json={
        "rel": "2026/CCT/Event 1.exe Videos for Event",
        "resolve_project": "Event 1.EXE Videos for Event",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["slug"] == "2026-cct-event-1-exe-videos-for-event"
    # marker written = folder claimed
    assert provision.read_marker(bare) == body["slug"]
    row = conn.execute("SELECT active FROM projects WHERE slug=?", (body["slug"],)).fetchone()
    assert row["active"] == 1


def test_link_folder_with_existing_marker_keeps_identity(env):
    client, _conn, projects_dir = env
    from ccsync_dashboard import provision
    moved = projects_dir / "2026" / "CCT" / "Moved Show"
    moved.mkdir(parents=True)
    provision.write_marker(moved, "original-identity")
    as_user(client, "jsmith")
    resp = client.post("/api/v1/projects/link",
                       json={"rel": "2026/CCT/Moved Show", "resolve_project": ""})
    assert resp.status_code == 200
    assert resp.json()["slug"] == "original-identity"


def test_partial_create_flow(env):
    client, conn, projects_dir = env
    (projects_dir / "2026" / "CCT").mkdir(parents=True)
    reported(conn, "CP S2 Edit")
    as_user(client, "jsmith")
    resp = client.post("/partials/project-setup/create", data={
        "resolve_project": "CP S2 Edit", "parent_rel": "2026/CCT",
        "name": "Season 2",
    })
    assert resp.status_code == 200
    assert "[ DONE ]" in resp.text
    assert (projects_dir / "2026" / "CCT" / "Season 2" / "B-roll").is_dir()


def test_partial_create_of_existing_folder_offers_use_this_folder(env):
    """The picker's create form on an existing name comes back with a
    one-click [ USE Projects/... ] button instead of demanding another name."""
    client, _conn, projects_dir = env
    (projects_dir / "2026" / "CCT" / "Website Highlights").mkdir(parents=True)
    as_user(client, "jsmith")
    resp = client.post("/partials/project-setup/create", data={
        "resolve_project": "Website Highlights", "parent_rel": "2026/CCT",
        "name": "Website Highlights",
    })
    assert resp.status_code == 200
    assert "already exists" in resp.text
    assert "[ USE Projects/2026/CCT/Website Highlights ]" in resp.text
    assert 'name="rel" value="2026/CCT/Website Highlights"' in resp.text
    assert not (projects_dir / "2026" / "CCT" / "Website Highlights"
                / "Website Highlights").exists()


def test_browse_offers_the_current_folder(env):
    """Standing inside an already-existing folder must be pickable -- that
    missing button is what left 'create a new subfolder' as the only way out."""
    client, _conn, projects_dir = env
    (projects_dir / "2026" / "CCT" / "Website Highlights" / "B-roll").mkdir(parents=True)
    as_user(client, "jsmith")
    page = client.get("/partials/project-setup/browse"
                      "?rel=2026/CCT/Website Highlights&resolve_project=Website Highlights")
    assert page.status_code == 200
    assert "You are in Projects/2026/CCT/Website Highlights" in page.text
    assert 'name="rel" value="2026/CCT/Website Highlights"' in page.text


def test_browse_of_a_marked_project_offers_it(env):
    client, _conn, projects_dir = env
    from ccsync_dashboard import provision
    show = projects_dir / "2026" / "Show"
    show.mkdir(parents=True)
    provision.write_marker(show, "2026-show")
    as_user(client, "jsmith")
    page = client.get("/partials/project-setup/browse?rel=2026/Show&resolve_project=Doc")
    assert "You are in Projects/2026/Show" in page.text
    assert "This folder is already a project" in page.text


def test_browse_flags_the_same_named_folder(env):
    client, _conn, projects_dir = env
    (projects_dir / "2026" / "CCT" / "Website Highlights").mkdir(parents=True)
    (projects_dir / "2026" / "CCT" / "Other Thing").mkdir(parents=True)
    as_user(client, "jsmith")
    page = client.get("/partials/project-setup/browse"
                      "?rel=2026/CCT&resolve_project=website highlights")
    assert page.status_code == 200
    assert page.text.count("[ SAME NAME ]") == 1   # only the matching row
    # ...and both rows can be picked as they are
    assert 'name="rel" value="2026/CCT/Website Highlights"' in page.text
    assert 'name="rel" value="2026/CCT/Other Thing"' in page.text


def test_browse_root_has_no_current_folder_button(env):
    """The Projects root itself is never a project."""
    client, _conn, projects_dir = env
    (projects_dir / "2026").mkdir()
    as_user(client, "jsmith")
    page = client.get("/partials/project-setup/browse?rel=&resolve_project=Doc")
    assert "You are in Projects/" not in page.text


def test_browse_inside_other_project_hides_current_folder_button(env):
    """Projects can't nest: a subfolder of a marked project is not pickable."""
    client, _conn, projects_dir = env
    from ccsync_dashboard import provision
    show = projects_dir / "2026" / "Show"
    (show / "B-roll").mkdir(parents=True)
    provision.write_marker(show, "2026-show")
    as_user(client, "jsmith")
    page = client.get("/partials/project-setup/browse?rel=2026/Show/B-roll&resolve_project=Doc")
    assert "You are in Projects/" not in page.text   # no pick-this-folder bar
    assert "projects can't nest" in page.text


def test_link_current_existing_folder_leaves_contents_alone(env):
    """[ USE THIS FOLDER ] on a pre-populated folder: marker + mapping only,
    no template subfolders, nothing moved."""
    client, conn, projects_dir = env
    from ccsync_dashboard import provision
    existing = projects_dir / "2026" / "CCT" / "Website Highlights"
    (existing / "Renders").mkdir(parents=True)
    (existing / "footage.braw").write_text("x")
    reported(conn, "Website Highlights")
    as_user(client, "jsmith")
    resp = client.post("/partials/project-setup/link", data={
        "resolve_project": "Website Highlights", "rel": "2026/CCT/Website Highlights",
    })
    assert resp.status_code == 200
    assert "[ DONE ]" in resp.text
    assert provision.read_marker(existing) == "2026-cct-website-highlights"
    assert not (existing / "Website Highlights").exists()
    assert not (existing / "B-roll").exists()          # link never templates
    assert (existing / "footage.braw").read_text() == "x"
    root = conn.execute("SELECT * FROM project_roots WHERE resolve_project=?",
                        ("Website Highlights",)).fetchone()
    assert root["project_slug"] == "2026-cct-website-highlights"


def test_link_traversal_guard(env):
    client, conn, _pd = env
    as_user(client, "jsmith")
    resp = client.post("/partials/project-setup/link",
                       data={"resolve_project": "Doc", "rel": "../escape"})
    assert resp.status_code == 200        # banner-not-crash convention
    assert "must not start with" in resp.text or "escapes the Projects tree" in resp.text
    assert conn.execute("SELECT COUNT(*) c FROM project_roots").fetchone()["c"] == 0
    for bad in ("../escape", "/etc", "2026/../../escape", "2026/.hidden"):
        assert client.post("/api/v1/projects/link",
                           json={"rel": bad, "resolve_project": "Doc"}).status_code == 422
    assert client.post("/api/v1/projects", json=create_body(
        parent_rel="2026/CCT", name="..", use_existing=True)).status_code == 422


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
