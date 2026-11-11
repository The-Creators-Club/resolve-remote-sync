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


def test_confident_match_needs_the_exact_name():
    """2026-07-25: one shared word ('Nuclear Family Reunion' -> 2025/FF4/
    Nuclear). 2026-10-31 (CR-379): two shared words ('Beyond Nights LUSTY'
    -> 2026/Beyond Nights). Only the project's own name may auto-map."""
    f = dbmod.match_project_label_confident
    labels = ["2025/FF4/Nuclear", "2026/Creator Profiles/Season 1", "2026/Beyond Nights"]

    # partial overlaps, one word or several, never map
    assert dbmod.match_project_label("Nuclear Family Reunion", labels) == "2025/FF4/Nuclear"
    assert f("Nuclear Family Reunion", labels) is None
    assert f("CCT Creator Profiles", labels) is None
    assert f("FF4 Nuclear Cut", labels) is None
    assert f("Beyond Nights LUSTY", labels) is None
    assert f("Season 1 Recap", labels) is None

    # the name IS the project: final segment or whole label, case, spacing,
    # '-' and '_' aside
    assert f("Nuclear", labels) == "2025/FF4/Nuclear"
    assert f("  nuclear  ", labels) == "2025/FF4/Nuclear"
    assert f("Season 1", labels) == "2026/Creator Profiles/Season 1"
    assert f("2025/FF4/Nuclear", labels) == "2025/FF4/Nuclear"
    assert f("beyond-nights", labels) == "2026/Beyond Nights"
    assert f("Season 2", labels) is None

    # two folders with that name: a human picks
    assert f("Shinto", ["2025/FF4/Shinto", "2026/FF5/Shinto"]) is None

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
                       json=report("Season 1")).status_code == 200
    roots = client.get("/api/v1/project-roots").json()["project_roots"]
    assert roots == [{
        "resolve_project": "Season 1",
        "slug": "2026-creator-profiles-season-1",
        "rel_path": "2026/Creator Profiles/Season 1",
        "source": "auto", "updated_by": "auto", "updated_at": roots[0]["updated_at"],
    }]

    # A later report cannot change the stored mapping, even if matching would
    # now produce something else (rename the tree label to force a difference).
    dbmod.upsert_project(conn, "2025-ff4-nuclear", "2025/Season 1/Nuclear",
                         "/x", dbmod.utcnow_iso())
    conn.commit()
    client.post("/api/v1/report", headers=headers, json=report("Season 1"))
    roots = client.get("/api/v1/project-roots").json()["project_roots"]
    assert roots[0]["slug"] == "2026-creator-profiles-season-1"
    assert roots[0]["source"] == "auto"

    # selection response carries the mappings for the companion
    sel = client.get("/api/v1/selection/jsmith", headers=headers).json()
    assert sel["project_roots"][0]["slug"] == "2026-creator-profiles-season-1"


def test_admin_only_changes(env):
    client, _ = env
    headers = report_headers()
    client.post("/api/v1/report", headers=headers, json=report("Season 1"))

    body = {"resolve_project": "Season 1", "slug": "2025-ff4-nuclear"}
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
                      json={"resolve_project": "Season 1", "slug": "nope"}
                      ).status_code == 404
    client.put("/api/v1/project-roots",
               json={"resolve_project": "Season 1", "slug": None})
    assert client.get("/api/v1/project-roots").json()["project_roots"] == []


def test_unmatched_projects_surface_for_admin(env):
    client, conn = env
    headers = report_headers()
    client.post("/api/v1/report", headers=headers, json=report("Mystery Doc"))
    assert dbmod.fetch_unmapped_resolve_projects(conn) == ["Mystery Doc"]

    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "owen"))
    # The project roots window lives on each project page (D7 of the UI
    # port), not on home: an unmatched Resolve project shows there with a
    # "no match" tag and, for an admin, the form that maps it.
    page = client.get("/project/2025-ff4-nuclear")
    assert page.status_code == 200
    assert 'id="roots"' in page.text and "Mystery Doc" in page.text
    assert 'aria-label="where Mystery Doc files into"' in page.text
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
    client.post("/api/v1/report", headers=headers, json=report("Season 1"))
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "jsmith"))
    page = client.get("/")
    assert "open in Resolve:" in page.text
    assert "Season 1" in page.text
    assert "matched by itself, then kept" in page.text
    # read-only for a non-admin: no form that changes the root on home
    assert 'hx-post="/partials/project-roots"' not in page.text


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


# --- CR-379 (2026-10-31): an unregistered folder that matches as well blocks
# the sticky auto-map. "Beyond Nights LUSTY" was mapped permanently into the
# registered "2026/Beyond Nights" while its own folder, "2026/Beyond Night
# LUSTY" (no marker yet), scored just as well and was never consulted.

def test_unregistered_rival_blocks_a_same_name_match():
    f = dbmod.unregistered_rivals
    assert f("Shinto", "2025/FF4/Shinto", ["2026", "2026/FF5", "2026/FF5/Shinto"]) == [
        "2026/FF5/Shinto"]
    assert f("Shinto", "2025/FF4/Shinto", ["2026/FF5/Shinto Recut"]) == []
    # a container of the match is never a rival
    assert f("FF4", "2025/FF4", ["2025"]) == []

def _marker(directory, slug):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / ".ccsync-project").write_text('{"slug": "%s"}' % slug, encoding="utf-8")


def test_scan_unregistered_dirs_skips_projects_and_containers(tmp_path):
    from ccsync_dashboard import provision
    _marker(tmp_path / "2026" / "Beyond Nights", "2026-beyond-nights")
    (tmp_path / "2026" / "Beyond Nights" / "Footage").mkdir()
    (tmp_path / "2026" / "Beyond Night LUSTY").mkdir()
    (tmp_path / "2026" / ".hidden").mkdir()
    (tmp_path / "Loose").mkdir()
    assert provision.scan_unregistered_dirs(tmp_path) == [
        "2026/Beyond Night LUSTY", "Loose"]


@pytest.fixture
def tree_env(tmp_path):
    projects = tmp_path / "Projects"
    _marker(projects / "2026" / "Beyond Nights", "2026-beyond-nights")
    (projects / "2026" / "Beyond Night LUSTY").mkdir(parents=True)
    settings = Settings(db_path=str(tmp_path / "r.db"), session_secret=SECRET,
                        report_token=TOKEN, admin_users=frozenset({"owen"}),
                        projects_dir=str(projects))
    app = create_app(settings)
    with TestClient(app) as client:
        conn = dbmod.connect(tmp_path / "r.db")
        dbmod.upsert_project(conn, "2026-beyond-nights", "2026/Beyond Nights", "/x",
                             dbmod.utcnow_iso())
        conn.commit()
        yield client, conn, projects
        conn.close()


def test_report_asks_for_a_partial_name(tree_env):
    """The live case: 'Beyond Nights LUSTY' must never land in Beyond Nights."""
    client, conn, _ = tree_env
    resp = client.post("/api/v1/report", headers=report_headers(),
                       json=report("Beyond Nights LUSTY"))
    assert resp.status_code == 200
    assert resp.json()["resolve_project_unmapped"] == "Beyond Nights LUSTY"
    assert conn.execute("SELECT COUNT(*) c FROM project_roots").fetchone()["c"] == 0


def test_report_asks_when_an_unregistered_folder_has_the_same_name(tree_env):
    client, conn, projects = tree_env
    (projects / "2025" / "Beyond Nights").mkdir(parents=True)
    from ccsync_dashboard import api as apimod
    apimod._UNREGISTERED_CACHE.clear()
    resp = client.post("/api/v1/report", headers=report_headers(),
                       json=report("Beyond Nights"))
    assert resp.json()["resolve_project_unmapped"] == "Beyond Nights"
    assert conn.execute("SELECT COUNT(*) c FROM project_roots").fetchone()["c"] == 0


def test_report_still_auto_maps_the_exact_name(tree_env):
    client, conn, _ = tree_env
    from ccsync_dashboard import api as apimod
    apimod._UNREGISTERED_CACHE.clear()
    resp = client.post("/api/v1/report", headers=report_headers(),
                       json=report("Beyond Nights"))
    assert "resolve_project_unmapped" not in resp.json()
    row = conn.execute("SELECT project_slug FROM project_roots WHERE resolve_project=?",
                       ("Beyond Nights",)).fetchone()
    assert row["project_slug"] == "2026-beyond-nights"


def test_the_tree_is_walked_before_the_report_takes_the_write_lock(tree_env, monkeypatch):
    """Audit dash-api-2 (2026-11-11): on a cache miss the CR-379 rival check os.walked the
    Projects tree AFTER `BEGIN IMMEDIATE`, so every other report and click waited behind a
    directory listing on the NAS's pool, again every 60 s while a rival kept the name unmapped."""
    client, conn, projects = tree_env
    (projects / "2025" / "Beyond Nights").mkdir(parents=True)
    from ccsync_dashboard import api as apimod
    from ccsync_dashboard import provision
    apimod._UNREGISTERED_CACHE.clear()
    seen = []
    real = provision.scan_unregistered_dirs

    def scan(path, max_depth=8):
        probe = dbmod.connect(conn.execute("PRAGMA database_list").fetchone()["file"], busy_ms=0)
        try:
            probe.execute("BEGIN IMMEDIATE")        # only possible while NOBODY holds the write lock
            probe.execute("ROLLBACK")
            seen.append("free")
        except Exception:                           # sqlite3.OperationalError: database is locked
            seen.append("held")
        finally:
            probe.close()
        return real(path, max_depth=max_depth)

    monkeypatch.setattr(provision, "scan_unregistered_dirs", scan)
    resp = client.post("/api/v1/report", headers=report_headers(), json=report("Beyond Nights"))
    assert resp.json()["resolve_project_unmapped"] == "Beyond Nights"      # the rival still blocks it
    assert seen == ["free"], seen                                          # one walk, lock not held


def test_an_unreadable_tree_is_asked_once_a_minute_not_once_a_report(tree_env, monkeypatch):
    client, conn, _ = tree_env
    from ccsync_dashboard import api as apimod
    from ccsync_dashboard import provision
    apimod._UNREGISTERED_CACHE.clear()
    walks = []

    def scan(path, max_depth=8):
        walks.append(1)
        raise OSError("stale file handle")

    monkeypatch.setattr(provision, "scan_unregistered_dirs", scan)
    for _ in range(3):
        resp = client.post("/api/v1/report", headers=report_headers(), json=report("Beyond Nights"))
        assert resp.json()["resolve_project_unmapped"] == "Beyond Nights"  # doubt means ask
    assert len(walks) == 1
    assert conn.execute("SELECT COUNT(*) c FROM project_roots").fetchone()["c"] == 0
