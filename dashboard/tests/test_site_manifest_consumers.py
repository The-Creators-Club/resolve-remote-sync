"""The dashboard's OWN surfaces read the resolved site manifest, not the
deploy-time environment snapshot (product-surface-2 / dash-admin-3,
2026-08-21).

The wizard makes org_name, tree_name, canonical_prefix and template_folders
REQUIRED answers and `GET /api/v1/site` publishes them to every companion and
installer -- but the topbar the admin is looking at while they save, and the
folder list /project-setup previews, both read `settings.site_*` /
`provision.TEMPLATE_FOLDERS`, which on an appliance (no DASH_SITE_* anywhere
in compose.appliance.yaml) are the vendor defaults. So the page showed the
admin their edits "saved" with no visible effect anywhere.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth
from ccsync_dashboard import db as dbmod
from ccsync_dashboard import site_store
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "test-secret"


def as_user(client, user):
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, user))
    return client


@pytest.fixture
def env(tmp_path):
    projects_dir = tmp_path / "tree" / "Projects"
    projects_dir.mkdir(parents=True)
    db_path = tmp_path / "manifest.db"
    settings = Settings(
        db_path=str(db_path),
        session_secret=SECRET,
        admin_users=frozenset({"owen"}),
        projects_dir=str(projects_dir),
        report_token="companion-token",
    )
    app = create_app(settings)
    with TestClient(app) as client:
        conn = dbmod.connect(db_path)
        yield client, conn, settings, app
        conn.close()


def test_the_topbar_brand_comes_from_the_database(env):
    client, conn, settings, app = env
    as_user(client, "owen")
    assert "CC SYNC" in client.get("/").text          # the product default

    r = client.put("/api/v1/admin/site", json={"values": {"org_short": "Northlight"}})
    assert r.status_code == 200
    # No restart, no cache flush by hand: the write invalidates it.
    assert "NORTHLIGHT" in client.get("/").text


def test_an_imported_site_toml_repaints_the_brand_too(env):
    client, conn, settings, app = env
    as_user(client, "owen")
    r = client.post("/api/v1/admin/site/import",
                    json={"text": "[site]\norg_short = \"Second Edit\"\n"})
    assert r.status_code == 200
    assert "SECOND EDIT" in client.get("/").text


def test_project_setup_previews_the_manifest_template_not_the_env_default(env):
    client, conn, settings, app = env
    dbmod.upsert_machine_state(conn, "jsmith", "EDIT-PC", None, dbmod.utcnow_iso(),
                               resolve_project="Mystery Doc")
    conn.commit()
    as_user(client, "owen")
    site_store.set_many(conn, {"template_folders": "Footage, Audio, Graphics"},
                        updated_by="test")
    conn.commit()

    page = client.get("/project-setup?resolve_project=Mystery Doc")
    assert page.status_code == 200
    assert "Footage, Audio, Graphics" in page.text
    assert "Interviewees" not in page.text     # the documentary-shop default


def test_the_settings_page_offers_every_feature_flag_the_manifest_carries(env):
    """product-surface-5: auto_update was settable only by pasting a site.toml
    into the migration textarea."""
    client, conn, settings, app = env
    as_user(client, "owen")
    page = client.get("/admin/settings")
    assert page.status_code == 200
    assert 'name="features.auto_update"' in page.text
    assert 'name="features.youtube_download"' in page.text

    r = client.put("/api/v1/admin/site", json={"values": {"features.auto_update": "1"}})
    assert r.status_code == 200
    assert r.json()["features"]["auto_update"] is True
    assert client.get("/api/v1/site").json()["features"]["auto_update"] is True


def test_the_settings_page_offers_nas_kind_as_a_choice(env):
    client, conn, settings, app = env
    as_user(client, "owen")
    page = client.get("/admin/settings")
    assert '<select name="nas_kind">' in page.text
    # dash-admin-7: case is normalised to what nas.factory builds ...
    r = client.put("/api/v1/admin/site", json={"values": {"nas_kind": "TrueNAS"}})
    assert r.status_code == 200
    assert r.json()["nas_kind"] == "truenas"
    # ... and a kind no factory can build is refused, not published.
    r = client.put("/api/v1/admin/site", json={"values": {"nas_kind": "qnap"}})
    assert r.status_code == 422
    assert client.get("/api/v1/site").json()["nas_kind"] == "truenas"
