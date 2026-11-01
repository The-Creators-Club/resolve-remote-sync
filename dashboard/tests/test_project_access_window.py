"""The project page's access window (CR-368 follow-up, 2026-10-07): the
per-project grant had no UI, so an admin on a self-installed per-project site
could not let a wired editor (who cannot tick, CR-28) into a project without a
raw API call. These pin the window, its two buttons, the admin gate and the
audit row the JSON routes now share."""
from __future__ import annotations

from fastapi.testclient import TestClient

from ccsync_dashboard import auth
from ccsync_dashboard import db as dbmod
from ccsync_dashboard import project_groups
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

from conftest import HX

SECRET = "test-secret"
HDR = {"Origin": "http://testserver", **HX}


def _app(tmp_path, acl="per-project"):
    settings = Settings(db_path=str(tmp_path / "acc.db"), session_secret=SECRET,
                        admin_users=frozenset({"owen"}), project_acl=acl)
    return settings, create_app(settings)


def _seed(settings):
    c = dbmod.connect(settings.db_path)
    try:
        now = dbmod.utcnow_iso()
        dbmod.upsert_project(c, "alpha", "Alpha", "/projects/alpha", now)
        for e in ("wired", "bea"):
            dbmod.record_known_editor(c, e, "test", now)
        c.commit()
    finally:
        c.close()


def _as(client, user):
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, user))


def _grants(settings):
    c = dbmod.connect(settings.db_path)
    try:
        return project_groups.grants(c).get("alpha", [])
    finally:
        c.close()


def _audit(settings):
    c = dbmod.connect(settings.db_path)
    try:
        return [(r["action"], r["subject"], r["detail"].get("editor"))
                for r in dbmod.fetch_audit(c, actions=("project.access.grant",
                                                       "project.access.revoke"))]
    finally:
        c.close()


def test_an_admin_gives_and_removes_access_from_the_window(tmp_path):
    settings, app = _app(tmp_path)
    with TestClient(app) as client:
        _seed(settings)
        _as(client, "owen")
        r = client.get("/partials/project/alpha/access", headers=HDR)
        assert r.status_code == 200
        assert "Give access" in r.text and 'value="wired"' in r.text

        r = client.post("/partials/project/alpha/access", headers=HDR,
                        data={"editor": "wired", "action": "grant"})
        assert r.status_code == 200, r.text
        assert "access given" in r.text and "Remove" in r.text
        assert _grants(settings) == ["wired"]

        r = client.post("/partials/project/alpha/access", headers=HDR,
                        data={"editor": "wired", "action": "revoke"})
        assert "access removed" in r.text
        assert _grants(settings) == []
        assert _audit(settings) == [("project.access.revoke", "alpha", "wired"),
                                    ("project.access.grant", "alpha", "wired")]


def test_the_window_is_admin_only(tmp_path):
    settings, app = _app(tmp_path)
    with TestClient(app) as client:
        _seed(settings)
        _as(client, "bea")
        assert client.get("/partials/project/alpha/access", headers=HDR).status_code == 403
        r = client.post("/partials/project/alpha/access", headers=HDR,
                        data={"editor": "bea", "action": "grant"})
        assert r.status_code == 403
        assert _grants(settings) == []
        page = client.get("/project/alpha")
        assert 'id="project-access"' not in page.text


def test_an_admin_sees_the_window_on_the_project_page(tmp_path):
    settings, app = _app(tmp_path)
    with TestClient(app) as client:
        _seed(settings)
        _as(client, "owen")
        page = client.get("/project/alpha")
        assert page.status_code == 200
        assert 'hx-get="/partials/project/alpha/access"' in page.text


def test_a_refusal_is_a_banner_not_a_dead_swap(tmp_path):
    settings, app = _app(tmp_path)
    with TestClient(app) as client:
        _seed(settings)
        _as(client, "owen")
        r = client.post("/partials/project/alpha/access", headers=HDR,
                        data={"editor": "", "action": "grant"})
        assert r.status_code == 200 and "choose a person first" in r.text
        r = client.post("/partials/project/alpha/access", headers=HDR,
                        data={"editor": "nobody", "action": "grant"})
        assert r.status_code == 200 and "unknown editor" in r.text
        assert client.get("/partials/project/zzz/access", headers=HDR).status_code == 404


def test_a_shared_site_says_the_list_waits_for_per_project(tmp_path):
    settings, app = _app(tmp_path, acl="shared")
    with TestClient(app) as client:
        _seed(settings)
        _as(client, "owen")
        r = client.get("/partials/project/alpha/access", headers=HDR)
        assert "project access is set to shared" in r.text


def test_the_json_route_is_audited_too(tmp_path):
    settings, app = _app(tmp_path)
    with TestClient(app) as client:
        _seed(settings)
        _as(client, "owen")
        assert client.put("/api/v1/projects/alpha/access/wired",
                          headers={"Origin": "http://testserver"}).json()["changed"] is True
        assert _audit(settings) == [("project.access.grant", "alpha", "wired")]
