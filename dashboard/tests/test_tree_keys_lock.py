"""canonical_prefix / tree_name / remote_root are read-only once any computer
exists (PR-GL19 / COM-H15 data-model-8, CR-368, 2026-10-07)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth
from ccsync_dashboard import db as dbmod
from ccsync_dashboard import site_store
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "test-secret"


@pytest.fixture
def env(tmp_path):
    db_path = tmp_path / "lock.db"
    settings = Settings(db_path=str(db_path), session_secret=SECRET,
                        admin_users=frozenset({"owen"}))
    app = create_app(settings)
    with TestClient(app) as client:
        client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "owen"))
        conn = dbmod.connect(db_path)
        yield client, conn, settings
        conn.close()


def _register_machine(conn):
    dbmod.upsert_machine(conn, "ed", "LAPTOP", dbmod.utcnow_iso())
    conn.commit()


def test_the_tree_keys_stay_editable_before_any_computer_exists(env):
    client, conn, settings = env
    assert site_store.tree_keys_locked(conn) is False
    resp = client.put("/api/v1/admin/site", json={"values": {"tree_name": "Studio_Tree"}})
    assert resp.status_code == 200
    assert resp.json()["tree_name"] == "Studio_Tree"


def test_a_change_to_a_tree_key_is_refused_once_a_machine_exists(env):
    client, conn, settings = env
    client.put("/api/v1/admin/site", json={"values": {"tree_name": "Before"}})
    _register_machine(conn)
    assert site_store.tree_keys_locked(conn) is True

    for key, value in (("tree_name", "After"), ("canonical_prefix", "Q:\\"),
                       ("remote_root", "/x/y")):
        resp = client.put("/api/v1/admin/site", json={"values": {key: value}})
        assert resp.status_code == 422, key
        assert "cannot be changed" in resp.json()["detail"]
    assert client.get("/api/v1/admin/site").json()["tree_name"] == "Before"


def test_saving_the_value_a_key_already_has_is_not_a_change(env):
    client, conn, settings = env
    client.put("/api/v1/admin/site", json={"values": {"tree_name": "Same"}})
    _register_machine(conn)
    resp = client.put("/api/v1/admin/site",
                      json={"values": {"tree_name": "Same", "org_name": "Renamed Org"}})
    assert resp.status_code == 200
    assert resp.json()["org_name"] == "Renamed Org"


def test_import_preview_and_apply_both_refuse_and_nothing_is_half_written(env):
    client, conn, settings = env
    _register_machine(conn)
    text = '[site]\norg_name = "Pasted Org"\n[tree]\ntree_name = "Pasted_Tree"\n'
    for path in ("/api/v1/admin/site/import?dry_run=1", "/api/v1/admin/site/import"):
        resp = client.post(path, json={"text": text})
        assert resp.status_code == 422, path
    assert client.get("/api/v1/admin/site").json()["org_name"] != "Pasted Org"


def test_the_owner_override_is_an_environment_switch_never_a_route(env, monkeypatch):
    client, conn, settings = env
    _register_machine(conn)
    monkeypatch.setenv(site_store.TREE_UNLOCK_ENV, "1")
    resp = client.put("/api/v1/admin/site", json={"values": {"tree_name": "Moved_On_Purpose"}})
    assert resp.status_code == 200


def test_non_tree_keys_are_never_locked(env):
    client, conn, settings = env
    _register_machine(conn)
    assert client.put("/api/v1/admin/site",
                      json={"values": {"org_name": "X"}}).status_code == 200


def test_the_settings_page_says_locked_only_when_the_keys_are_locked(env):
    client, conn, settings = env
    before = client.get("/admin/settings")
    assert before.status_code == 200
    assert 'sf-auto" title="Read from the running server, so the box is locked. Change the thing it comes from instead.">locked' not in before.text
    _register_machine(conn)
    after = client.get("/admin/settings")
    assert after.status_code == 200
    assert ">locked</span>: read-only now that computers have registered" in after.text


def test_the_boot_seed_still_runs_when_computers_exist(env, monkeypatch):
    """CR-368 follow-up (2026-10-07): the seed calls set_many with settings=None;
    the lock check dereferenced it, so the seed never ran on a site with a
    computer and logged an AttributeError on every boot."""
    client, conn, settings = env
    conn.execute("DELETE FROM site_settings")
    conn.commit()
    _register_machine(conn)
    monkeypatch.setenv("DASH_SITE_TREE_NAME", "Seeded_Tree")
    import dataclasses
    seeded = dataclasses.replace(settings, site_tree_name="Seeded_Tree")
    assert site_store._seed_from_env_once(conn, seeded) is True
    row = conn.execute("SELECT value FROM site_settings WHERE key='tree_name'").fetchone()
    assert row is not None and row[0] == "Seeded_Tree"
