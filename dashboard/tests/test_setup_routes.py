"""setup_routes.py -- the wizard API and the admin site-manifest routes
(ZERO_TOUCH_PLAN.md WP D, 2026-08-17). Every route: happy path + refusal."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth
from ccsync_dashboard import db as dbmod
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "test-secret"


def as_user(client, user):
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, user))
    return client


def clear_user(client):
    client.cookies.delete(auth.COOKIE_NAME)
    return client


@pytest.fixture
def env(tmp_path):
    db_path = tmp_path / "setup.db"
    settings = Settings(
        db_path=str(db_path),
        session_secret=SECRET,
        admin_users=frozenset({"owen"}),
    )
    app = create_app(settings)
    with TestClient(app) as client:
        conn = dbmod.connect(db_path)
        yield client, conn, settings
        conn.close()


# ------------------------------------------------------------- /setup/tasks

def test_setup_tasks_requires_admin_in_this_worktree(env):
    """No identity module exists here (setup_engine.probe_admin_status
    returns None), so the anonymous first-run window never opens and every
    /api/v1/setup/* route is admin-only -- see setup_routes.py's module
    docstring for the handoff to WP C."""
    client, conn, settings = env
    resp = client.get("/api/v1/setup/tasks")
    assert resp.status_code == 401


def test_setup_tasks_refuses_a_non_admin_session(env):
    client, conn, settings = env
    as_user(client, "editor1")
    resp = client.get("/api/v1/setup/tasks")
    assert resp.status_code == 403


def test_setup_tasks_lists_every_registered_task_for_an_admin(env):
    client, conn, settings = env
    as_user(client, "owen")
    resp = client.get("/api/v1/setup/tasks")
    assert resp.status_code == 200
    body = resp.json()
    ids = {t["id"] for t in body["tasks"]}
    assert {"eula", "admin", "studio", "storage", "secrets", "syncthing", "done"} <= ids
    assert "eula" in body["outstanding_required"]


def test_check_and_run_and_skip_happy_paths(env):
    client, conn, settings = env
    as_user(client, "owen")

    check = client.post("/api/v1/setup/tasks/studio/check")
    assert check.status_code == 200
    assert check.json()["status"] == "todo"

    skip = client.post("/api/v1/setup/tasks/tailnet/skip")
    assert skip.status_code == 200
    assert skip.json()["status"] == "skipped"


def test_run_unknown_task_is_404(env):
    client, conn, settings = env
    as_user(client, "owen")
    resp = client.post("/api/v1/setup/tasks/not-a-real-task/check")
    assert resp.status_code == 404


def test_run_a_task_with_no_action_is_400(env):
    client, conn, settings = env
    as_user(client, "owen")
    resp = client.post("/api/v1/setup/tasks/admin/run")
    assert resp.status_code == 400


def test_skip_a_required_task_is_400(env):
    client, conn, settings = env
    as_user(client, "owen")
    resp = client.post("/api/v1/setup/tasks/studio/skip")
    assert resp.status_code == 400


def test_run_do_it_happy_path_on_storage(tmp_path):
    tree_root = tmp_path / "tree"
    (tree_root / "Projects").mkdir(parents=True)
    settings = Settings(
        db_path=str(tmp_path / "setup2.db"), session_secret=SECRET,
        admin_users=frozenset({"owen"}), projects_dir=str(tree_root / "Projects"),
    )
    with TestClient(create_app(settings)) as client:
        as_user(client, "owen")
        resp = client.post("/api/v1/setup/tasks/storage/run")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


# ------------------------------------------------------------------- eula

def test_eula_get_requires_admin(env):
    client, conn, settings = env
    resp = client.get("/api/v1/setup/eula")
    assert resp.status_code == 401


def test_eula_get_and_accept_happy_path(env):
    client, conn, settings = env
    as_user(client, "owen")
    get_resp = client.get("/api/v1/setup/eula")
    assert get_resp.status_code == 200
    assert "version" in get_resp.json()

    post_resp = client.post("/api/v1/setup/eula")
    assert post_resp.status_code == 200
    assert post_resp.json()["status"] == "ok"


# ------------------------------------------------------------- admin/site

def test_admin_site_get_requires_admin(env):
    client, conn, settings = env
    resp = client.get("/api/v1/admin/site")
    assert resp.status_code == 401
    as_user(client, "editor1")
    resp2 = client.get("/api/v1/admin/site")
    assert resp2.status_code == 403


def test_admin_site_get_happy_path(env):
    client, conn, settings = env
    as_user(client, "owen")
    resp = client.get("/api/v1/admin/site")
    assert resp.status_code == 200
    body = resp.json()
    assert body["canonical_prefix"] == "P:\\"
    assert "auto_derived" in body


def test_admin_site_put_happy_path_and_validation_refusal(env):
    client, conn, settings = env
    as_user(client, "owen")
    ok = client.put("/api/v1/admin/site", json={"values": {"org_name": "Studio"}})
    assert ok.status_code == 200
    assert ok.json()["org_name"] == "Studio"

    bad = client.put("/api/v1/admin/site", json={"values": {"sftp_port": "not-a-number"}})
    assert bad.status_code == 422


def test_admin_site_put_refuses_a_non_admin(env):
    client, conn, settings = env
    as_user(client, "editor1")
    resp = client.put("/api/v1/admin/site", json={"values": {"org_name": "x"}})
    assert resp.status_code == 403


def test_admin_site_export_happy_path(env):
    client, conn, settings = env
    as_user(client, "owen")
    client.put("/api/v1/admin/site", json={"values": {"org_name": "Studio"}})
    resp = client.get("/api/v1/admin/site/export")
    assert resp.status_code == 200
    assert 'org_name = "Studio"' in resp.text


def test_admin_site_export_requires_admin(env):
    client, conn, settings = env
    resp = client.get("/api/v1/admin/site/export")
    assert resp.status_code == 401


def test_admin_site_import_happy_path(env):
    client, conn, settings = env
    as_user(client, "owen")
    text = '[site]\norg_name = "Imported Studio"\n'
    resp = client.post("/api/v1/admin/site/import", json={"text": text})
    assert resp.status_code == 200
    assert resp.json()["org_name"] == "Imported Studio"


def test_admin_site_import_refuses_garbage_toml(env):
    client, conn, settings = env
    as_user(client, "owen")
    resp = client.post("/api/v1/admin/site/import", json={"text": "not = [valid"})
    assert resp.status_code == 422


def test_admin_site_import_requires_admin(env):
    client, conn, settings = env
    resp = client.post("/api/v1/admin/site/import", json={"text": "[site]\n"})
    assert resp.status_code == 401


# ----------------------------------------------------------------- /setup page

def test_setup_page_requires_a_session_in_this_worktree(env):
    client, conn, settings = env
    resp = client.get("/setup", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/login")


def test_setup_page_redirects_a_non_admin_to_the_grid(env):
    client, conn, settings = env
    as_user(client, "editor1")
    resp = client.get("/setup", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"


def test_setup_page_renders_for_an_admin(env):
    client, conn, settings = env
    as_user(client, "owen")
    resp = client.get("/setup")
    assert resp.status_code == 200
    assert "SETUP" in resp.text


# --------------------------------------------------------------- /admin/settings

def test_admin_settings_page_requires_admin(env):
    client, conn, settings = env
    resp = client.get("/admin/settings", follow_redirects=False)
    assert resp.status_code in (401, 303)
    as_user(client, "editor1")
    resp2 = client.get("/admin/settings")
    assert resp2.status_code == 403


def test_admin_settings_page_renders_for_an_admin(env):
    client, conn, settings = env
    as_user(client, "owen")
    resp = client.get("/admin/settings")
    assert resp.status_code == 200
    assert "SITE SETTINGS" in resp.text
