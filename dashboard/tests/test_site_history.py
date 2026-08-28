"""site_settings history: the missing half of UX-21 (resilience sweep
2026-08-28). db.record_site_change / db.site_history already existed with no
callers; this pins the callers -- the import preview, the SAVE-path snapshot
for the three tree keys, and [ UNDO LAST IMPORT ]."""
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


@pytest.fixture
def env(tmp_path):
    db_path = tmp_path / "site-history.db"
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


# --------------------------------------------------------------- import diff

def test_import_dry_run_returns_the_diff_and_writes_nothing(env):
    client, conn, settings = env
    as_user(client, "owen")
    text = '[site]\norg_name = "Imported Studio"\n'
    resp = client.post("/api/v1/admin/site/import?dry_run=1", json={"text": text})
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["changes"] == [{"key": "org_name", "from": "", "to": "Imported Studio"}]

    # Nothing written: a plain GET still answers the built-in default.
    live = client.get("/api/v1/admin/site").json()
    assert live["org_name"] == ""
    assert dbmod.site_history(conn) == []


def test_import_dry_run_with_no_changes_reports_zero(env):
    client, conn, settings = env
    as_user(client, "owen")
    client.put("/api/v1/admin/site", json={"values": {"org_name": "Studio"}})
    resp = client.post(
        "/api/v1/admin/site/import?dry_run=1", json={"text": '[site]\norg_name = "Studio"\n'}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 0
    assert body["changes"] == []


def test_import_dry_run_refuses_bad_toml_the_same_way_the_apply_does(env):
    client, conn, settings = env
    as_user(client, "owen")
    resp = client.post("/api/v1/admin/site/import?dry_run=1", json={"text": "not = [valid"})
    assert resp.status_code == 422


def test_import_dry_run_requires_admin(env):
    client, conn, settings = env
    resp = client.post("/api/v1/admin/site/import?dry_run=1", json={"text": "[site]\n"})
    assert resp.status_code == 401


# ------------------------------------------------------- import records history

def test_import_records_history_with_the_previous_values(env):
    client, conn, settings = env
    as_user(client, "owen")
    client.put("/api/v1/admin/site", json={"values": {"org_name": "Old Name"}})

    resp = client.post(
        "/api/v1/admin/site/import", json={"text": '[site]\norg_name = "New Name"\n'}
    )
    assert resp.status_code == 200
    assert resp.json()["org_name"] == "New Name"

    entries = dbmod.site_history(conn)
    assert len(entries) == 1
    assert entries[0]["action"] == "import"
    assert entries[0]["actor"] == "owen"
    assert entries[0]["before"] == {"org_name": "Old Name"}
    assert entries[0]["after"] == {"org_name": "New Name"}


def test_import_with_no_actual_changes_records_no_history(env):
    client, conn, settings = env
    as_user(client, "owen")
    client.put("/api/v1/admin/site", json={"values": {"org_name": "Studio"}})
    resp = client.post(
        "/api/v1/admin/site/import", json={"text": '[site]\norg_name = "Studio"\n'}
    )
    assert resp.status_code == 200
    assert dbmod.site_history(conn) == []


# --------------------------------------------------------- save (tree keys)

def test_save_of_a_tree_key_records_history(env):
    client, conn, settings = env
    as_user(client, "owen")
    resp = client.put("/api/v1/admin/site", json={"values": {"canonical_prefix": "Q:\\"}})
    assert resp.status_code == 200

    entries = dbmod.site_history(conn)
    assert len(entries) == 1
    assert entries[0]["action"] == "save"
    assert entries[0]["before"] == {"canonical_prefix": "P:\\"}
    assert entries[0]["after"] == {"canonical_prefix": "Q:\\"}


def test_save_of_a_non_tree_key_records_no_history(env):
    client, conn, settings = env
    as_user(client, "owen")
    resp = client.put("/api/v1/admin/site", json={"values": {"org_name": "Studio"}})
    assert resp.status_code == 200
    assert dbmod.site_history(conn) == []


def test_save_that_touches_a_tree_key_without_changing_it_records_nothing(env):
    client, conn, settings = env
    as_user(client, "owen")
    # canonical_prefix left at its current (default) value -- nothing changed.
    resp = client.put("/api/v1/admin/site", json={"values": {"canonical_prefix": "P:\\"}})
    assert resp.status_code == 200
    assert dbmod.site_history(conn) == []


def test_a_bad_tree_key_save_leaves_no_half_taken_snapshot(env):
    client, conn, settings = env
    as_user(client, "owen")
    resp = client.put("/api/v1/admin/site", json={"values": {"canonical_prefix": "not-a-drive"}})
    assert resp.status_code == 422
    assert dbmod.site_history(conn) == []


# --------------------------------------------------------------- undo

def test_undo_restores_and_records(env):
    client, conn, settings = env
    as_user(client, "owen")
    client.put("/api/v1/admin/site", json={"values": {"canonical_prefix": "P:\\"}})
    client.put("/api/v1/admin/site", json={"values": {"canonical_prefix": "Q:\\"}})
    assert client.get("/api/v1/admin/site").json()["canonical_prefix"] == "Q:\\"

    resp = client.post("/api/v1/admin/site/undo-last-change")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["changes"] == [{"key": "canonical_prefix", "from": "Q:\\", "to": "P:\\"}]
    assert body["manifest"]["canonical_prefix"] == "P:\\"

    assert client.get("/api/v1/admin/site").json()["canonical_prefix"] == "P:\\"

    # The undo is itself a history entry, so undoing an undo works too.
    entries = dbmod.site_history(conn)
    assert len(entries) == 2
    assert entries[0]["action"] == "undo"
    assert entries[0]["before"] == {"canonical_prefix": "Q:\\"}
    assert entries[0]["after"] == {"canonical_prefix": "P:\\"}


def test_undo_of_an_undo_puts_it_back_again(env):
    client, conn, settings = env
    as_user(client, "owen")
    client.put("/api/v1/admin/site", json={"values": {"canonical_prefix": "Q:\\"}})
    client.post("/api/v1/admin/site/undo-last-change")
    assert client.get("/api/v1/admin/site").json()["canonical_prefix"] == "P:\\"

    resp = client.post("/api/v1/admin/site/undo-last-change")
    assert resp.status_code == 200
    assert client.get("/api/v1/admin/site").json()["canonical_prefix"] == "Q:\\"
    assert len(dbmod.site_history(conn)) == 3


def test_undo_with_empty_history_is_a_readable_404(env):
    client, conn, settings = env
    as_user(client, "owen")
    resp = client.post("/api/v1/admin/site/undo-last-change")
    assert resp.status_code == 404
    assert "no site setting change is recorded" in resp.json()["detail"]


def test_undo_requires_admin(env):
    client, conn, settings = env
    as_user(client, "editor1")
    resp = client.post("/api/v1/admin/site/undo-last-change")
    assert resp.status_code == 403


def test_undo_runs_through_the_same_validation_apply_uses(env):
    """If a value in history no longer validates (a product change dropped a
    once-legal value), undo refuses with the same 422 a save would give --
    it is not a second, less-checked write path."""
    client, conn, settings = env
    as_user(client, "owen")
    client.put("/api/v1/admin/site", json={"values": {"canonical_prefix": "Q:\\"}})
    dbmod.record_site_change(
        conn, "owen", "import",
        {"canonical_prefix": "not-a-drive"}, {"canonical_prefix": "Q:\\"},
    )
    conn.commit()
    resp = client.post("/api/v1/admin/site/undo-last-change")
    assert resp.status_code == 422


# ------------------------------------------------------------- history listing

def test_history_endpoint_lists_who_when_and_count_never_values(env):
    client, conn, settings = env
    as_user(client, "owen")
    client.put("/api/v1/admin/site", json={"values": {"canonical_prefix": "Q:\\"}})

    resp = client.get("/api/v1/admin/site/history")
    assert resp.status_code == 200
    entries = resp.json()["entries"]
    assert len(entries) == 1
    assert entries[0]["actor"] == "owen"
    assert entries[0]["action"] == "save"
    assert entries[0]["count"] == 1
    assert "at" in entries[0]
    assert set(entries[0]) == {"at", "actor", "action", "count"}


def test_history_endpoint_requires_admin(env):
    client, conn, settings = env
    resp = client.get("/api/v1/admin/site/history")
    assert resp.status_code == 401


def test_history_endpoint_empty_is_an_empty_list_not_an_error(env):
    client, conn, settings = env
    as_user(client, "owen")
    resp = client.get("/api/v1/admin/site/history")
    assert resp.status_code == 200
    assert resp.json()["entries"] == []


# --------------------------------------------------------------- secret masking

def test_a_secret_shaped_key_is_masked_in_the_diff(env, monkeypatch):
    """None of site_store.KEYS is secret-shaped today (see its docstring) --
    this proves the guard works if one ever is, without waiting for that to
    happen for real."""
    from ccsync_dashboard import site_store

    monkeypatch.setitem(site_store.KEYS, "org_name_token", "str")
    try:
        client, conn, settings = env
        as_user(client, "owen")

        changes = site_store.diff_against_current(
            conn, settings, {"org_name_token": "sk-abc123"}
        )
        assert changes == [{"key": "org_name_token", "from": "", "to": "sk-abc123"}]
        masked = site_store.mask_changes(changes)
        assert masked == [{"key": "org_name_token", "from": "", "to": "********"}]
    finally:
        site_store.KEYS.pop("org_name_token", None)
