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
    # Every row carries the button label, so a client never has to know the
    # default (2026-08-18, Task.run_label).
    labels = {t["id"]: t["run_label"] for t in body["tasks"]}
    assert labels["storage"] == "DO IT"
    assert labels["software"] == "CHECK NOW"
    assert all(t["run_label"] for t in body["tasks"])


def test_no_task_reports_itself_unimplemented(env):
    """A shipped product does not tell a customer that five of its eleven
    setup steps are "not implemented in this build" (2026-08-18)."""
    client, conn, settings = env
    as_user(client, "owen")
    for task in client.get("/api/v1/setup/tasks").json()["tasks"]:
        state = client.post(f"/api/v1/setup/tasks/{task['id']}/check").json()
        assert "not implemented" not in state["detail"], task["id"]
        assert state["status"] != "fail", (task["id"], state["detail"])


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


def test_admin_site_put_accepts_and_refuses_the_indexer_model_tier(env):
    client, conn, settings = env
    as_user(client, "owen")

    ok = client.put("/api/v1/admin/site", json={"values": {"indexer_model_tier": "best"}})
    assert ok.status_code == 200
    assert ok.json()["indexer"]["model_tier"] == "best"

    bad = client.put("/api/v1/admin/site", json={"values": {"indexer_model_tier": "medium"}})
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


def test_settings_page_renders_both_indexer_model_tier_options(env):
    client, conn, settings = env
    as_user(client, "owen")
    resp = client.get("/admin/settings")
    assert resp.status_code == 200
    body = resp.text
    assert 'name="indexer_model_tier" value="good"' in body
    assert 'name="indexer_model_tier" value="best"' in body
    assert "aria-describedby=\"indexer-model-tier-good-help\"" in body
    assert "aria-describedby=\"indexer-model-tier-best-help\"" in body
    assert ">\n          Good\n" in body
    assert ">\n          Best\n" in body
    assert ("Qwen3-VL 4B" in body and "8 GB VRAM" in body and "16 GB" in body
            and "~20 s per clip on an RTX 3080" in body)
    assert ("Qwen3-VL 8B" in body and "12 GB VRAM" in body and "24 GB" in body
            and "sharper on on-screen text and vocabulary" in body)
    assert "reads this choice from the dashboard" in body
    # The default option ("good") is pre-checked for a fresh manifest, the
    # unselected one is not.
    good_start = body.index('name="indexer_model_tier" value="good"')
    good_end = body.index(">", good_start)
    assert "checked" in body[good_start:good_end]
    best_start = body.index('name="indexer_model_tier" value="best"')
    best_end = body.index(">", best_start)
    assert "checked" not in body[best_start:best_end]


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


def test_admin_settings_page_offers_the_tray_logo_field(env):
    """Rebranding a fleet is a Settings edit, not a reinstall (CR-23) -- so
    the field has to be ON the page, with the hover help that says what may
    go in it (a bare asset name, or a path on the editor's own machine)."""
    client, conn, settings = env
    as_user(client, "owen")
    resp = client.get("/admin/settings")
    assert resp.status_code == 200
    assert 'name="brand_logo"' in resp.text
    assert "TRAY LOGO" in resp.text
    assert "cc_mark_white.png" in resp.text


# ------------------------------------------ first-run window in local mode
# dash-admin-4 (2026-08-21): under DASH_AUTH_METHOD=local with no accounts
# nobody can sign in at all (verify_password needs a hash), so a shut window
# made /setup and every /api/v1/setup/* route unreachable while
# POST /api/v1/setup/admin -- the route the wizard's own step 2 calls -- sat
# there working. The only way in was curl.


@pytest.fixture
def local_env(tmp_path):
    db_path = tmp_path / "local-setup.db"
    settings = Settings(
        db_path=str(db_path),
        session_secret=SECRET,
        auth_method="local",
    )
    app = create_app(settings)
    with TestClient(app) as client:
        conn = dbmod.connect(db_path)
        yield client, conn, settings
        conn.close()


def test_local_mode_with_no_accounts_opens_the_wizard_to_an_anonymous_browser(local_env):
    client, conn, settings = local_env
    assert client.get("/api/v1/setup/tasks").status_code == 200
    assert client.get("/api/v1/setup/eula").status_code == 200
    page = client.get("/setup", follow_redirects=False)
    assert page.status_code == 200


def test_the_window_shuts_the_moment_the_first_admin_exists(local_env):
    client, conn, settings = local_env
    r = client.post("/api/v1/setup/admin",
                    json={"username": "owen", "password": "correct-horse-battery-staple"})
    assert r.status_code == 200
    clear_user(client)          # the wizard is signed in; a stranger is not
    assert client.get("/api/v1/setup/tasks").status_code == 401
    assert client.get("/setup", follow_redirects=False).status_code == 303


def test_the_window_stays_shut_on_smb_and_oidc(tmp_path):
    """A NAS or an IdP can already authenticate an admin there, so an
    anonymous window would be a second way in."""
    for method in ("smb", "oidc"):
        settings = Settings(
            db_path=str(tmp_path / f"{method}.db"),
            session_secret=SECRET,
            auth_method=method,
            admin_users=frozenset({"owen"}),
        )
        app = create_app(settings)
        with TestClient(app) as client:
            assert client.get("/api/v1/setup/tasks").status_code == 401
