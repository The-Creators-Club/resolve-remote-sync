"""A tick is membership of proj-<slug> under per-project ACL (CR-368 follow-up,
GL-19 / COM-H15, 2026-10-07). The NAS is the repo's FakeTrueNAS; nothing here
needs a live NAS (the live check is the one deferred part)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from ccsync_dashboard import db as dbmod
from ccsync_dashboard import project_groups
from ccsync_dashboard.nas import TrueNASClient
from ccsync_dashboard.nas import truenas as truenas_mod
from ccsync_dashboard.settings import Settings

from fake_truenas import FakeTrueNAS


@pytest.fixture
def nas(monkeypatch):
    monkeypatch.setattr(truenas_mod.time, "sleep", lambda s: None)
    fake = FakeTrueNAS().start()
    client = TrueNASClient("h", "u", "p", base_url=fake.base_url, verify_ssl=False,
                           homes_parent="/mnt/t/homes")
    gid, _ = client.ensure_editors_group()
    for name in ("ed", "bea"):
        client.create_or_update_editor(name, "ssh-ed25519 AAAA " + name)
    yield client, fake
    fake.stop()


@pytest.fixture
def conn(tmp_path):
    c = dbmod.connect(tmp_path / "pg.db")
    dbmod.migrate(c)
    now = dbmod.utcnow_iso()
    for slug in ("alpha", "beta"):
        dbmod.upsert_project(c, slug, slug, f"/projects/{slug}", now)
    for editor in ("ed", "bea"):
        dbmod.record_known_editor(c, editor, "test", now)
    c.commit()
    yield c
    c.close()


def _settings(acl="per-project", root="/mnt/t/Projects"):
    return Settings(project_acl=acl, nas_projects_root=root)


def _members(fake, group):
    gid = next(g["id"] for g in fake.state["groups"] if g["group"] == group)
    return sorted(u["username"] for u in fake.state["users"] if gid in u["groups"])


def test_a_tick_adds_the_editor_to_the_project_group_and_an_untick_removes_it(nas, conn):
    client, fake = nas
    now = dbmod.utcnow_iso()
    dbmod.add_selection(conn, "ed", "alpha", "ed", now)
    dbmod.add_selection(conn, "ed", "beta", "ed", now)
    dbmod.add_selection(conn, "bea", "beta", "bea", now)
    conn.commit()
    res = project_groups.reconcile(conn, _settings(), nas=client)
    assert res["ran"] and res["errors"] == 0
    assert _members(fake, "proj-alpha") == ["ed"]
    assert _members(fake, "proj-beta") == ["bea", "ed"]
    # the editors group is still there: only proj- groups are managed
    ed = next(u for u in fake.state["users"] if u["username"] == "ed")
    egid = next(g["id"] for g in fake.state["groups"] if g["group"] == "editors")
    assert egid in ed["groups"] or ed["group"]["id"] == egid

    dbmod.remove_selection(conn, "ed", "beta")
    conn.commit()
    res = project_groups.reconcile(conn, _settings(), nas=client)
    assert res["removed"] == 1
    assert _members(fake, "proj-beta") == ["bea"]
    # an editor with no tick is in no project group and that is fine
    dbmod.remove_selection(conn, "bea", "beta")
    dbmod.remove_selection(conn, "ed", "alpha")
    conn.commit()
    assert project_groups.reconcile(conn, _settings(), nas=client)["errors"] == 0
    assert _members(fake, "proj-alpha") == [] and _members(fake, "proj-beta") == []


def test_a_group_the_dashboard_did_not_derive_is_never_touched(nas, conn):
    client, fake = nas
    # a hand-made group, and a proj- group for a project the dashboard has no row for
    for name in ("proj-handmade", "finance"):
        client.post("/group", {"name": name, "smb": False})
    ed = next(u for u in fake.state["users"] if u["username"] == "ed")
    for g in fake.state["groups"]:
        if g["group"] in ("proj-handmade", "finance"):
            ed["groups"].append(g["id"])
    before = sorted(ed["groups"])
    project_groups.reconcile(conn, _settings(), nas=client)
    assert sorted(ed["groups"]) == before


def test_a_shared_site_and_an_unconfigured_one_are_untouched(nas, conn):
    client, fake = nas
    dbmod.add_selection(conn, "ed", "alpha", "ed", dbmod.utcnow_iso())
    conn.commit()
    n_groups = len(fake.state["groups"])
    assert project_groups.reconcile(conn, _settings("shared"), nas=client)["ran"] is False
    assert project_groups.reconcile(conn, Settings(), nas=client)["ran"] is False
    assert len(fake.state["groups"]) == n_groups
    assert project_groups.enabled(Settings.from_env({})) is False
    assert project_groups.enabled(Settings.from_env({"DASH_PROJECT_ACL": "per-project"})) is True


def test_a_system_account_is_never_modified(nas, conn):
    client, fake = nas
    fake.state["users"].append({"id": 99, "uid": 0, "username": "root", "groups": [],
                                "group": {"id": 1}})
    with pytest.raises(Exception, match="system account"):
        client.set_editor_project_groups("root", {"proj-alpha"}, {"proj-alpha": {"id": 1, "gid": 2}})


def test_a_failing_nas_never_raises_out_of_the_reconcile(conn):
    class Boom:
        def project_groups_index(self):
            raise RuntimeError("nas down")
        ensure_project_group = set_editor_project_groups = lambda *a, **k: None

    res = project_groups.reconcile(conn, _settings(), nas=Boom())
    assert res["errors"] == 1 and res["ran"] is False


def test_a_backend_without_the_capability_is_inert(conn):
    class Dsm:
        pass

    assert project_groups.reconcile(conn, _settings(), nas=Dsm())["ran"] is False


def test_a_new_project_directory_is_closed_to_its_group(nas):
    client, fake = nas
    assert project_groups.close_new_project_dir(_settings(), "2026/Nuke", "2026-nuke", nas=client)
    assert any(g["group"] == "proj-2026-nuke" for g in fake.state["groups"])
    # inert on a shared site, or with no NAS-side root to point setperm at
    assert not project_groups.close_new_project_dir(_settings("shared"), "x", "x", nas=client)
    assert not project_groups.close_new_project_dir(_settings(root=""), "x", "x", nas=client)
    fake.state["fail_setperm"] = True
    assert not project_groups.close_new_project_dir(_settings(), "y", "y", nas=client)


def test_the_group_name_derivation_matches_the_base_rig_scripts():
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "server"))
    import common   # noqa: PLC0415

    for slug in ("alpha", "2026-ff4-nuclear", "x" * 60, "a-" * 20 + "b", "2026-taichung-drone-basic-camp"):
        assert project_groups.group_name(slug) == common.project_group_name(slug)


# ---- round 2 (CR-368, 2026-10-07): wired editors, manual membership -------

def test_an_explicit_grant_gives_a_wired_editor_a_project_without_a_tick(nas, conn):
    client, fake = nas
    # "ed" has no tick at all (a wired editor's tick is refused with a 409)
    assert project_groups.grant(conn, "alpha", "ed") is True
    assert project_groups.grant(conn, "alpha", "ed") is False
    conn.commit()
    project_groups.reconcile(conn, _settings(), nas=client)
    assert _members(fake, "proj-alpha") == ["ed"]
    # revoking removes it again, and only what the dashboard added
    assert project_groups.revoke(conn, "alpha", "ed") is True
    conn.commit()
    project_groups.reconcile(conn, _settings(), nas=client)
    assert _members(fake, "proj-alpha") == []


def test_a_membership_made_by_hand_or_by_the_cli_is_never_revoked(nas, conn):
    client, fake = nas
    meta = client.ensure_project_group("proj-alpha")
    # ed by the CLI; bea is added by the dashboard from her tick below
    client.set_editor_project_groups("ed", {"proj-alpha"}, {"proj-alpha": meta})
    assert _members(fake, "proj-alpha") == ["ed"]
    # a tick for bea only: ed's manual membership has no tick behind it
    dbmod.add_selection(conn, "bea", "alpha", "bea", dbmod.utcnow_iso())
    conn.commit()
    project_groups.reconcile(conn, _settings(), nas=client)
    assert _members(fake, "proj-alpha") == ["bea", "ed"]
    # ...but once bea's tick is gone, the dashboard takes back what it gave
    dbmod.remove_selection(conn, "bea", "alpha")
    conn.commit()
    project_groups.reconcile(conn, _settings(), nas=client)
    assert _members(fake, "proj-alpha") == ["ed"]


def test_a_grant_for_an_archived_project_is_dropped_from_the_group(nas, conn):
    client, fake = nas
    project_groups.grant(conn, "beta", "bea")
    conn.commit()
    project_groups.reconcile(conn, _settings(), nas=client)
    assert _members(fake, "proj-beta") == ["bea"]
    conn.execute("UPDATE projects SET archived_at=? WHERE slug='beta'", (dbmod.utcnow_iso(),))
    conn.commit()
    project_groups.reconcile(conn, _settings(), nas=client)
    assert _members(fake, "proj-beta") == []


def test_the_access_routes_are_admin_only_and_store_a_grant(tmp_path):
    from fastapi.testclient import TestClient
    from ccsync_dashboard import auth
    from ccsync_dashboard.app import create_app

    secret = "test-secret"
    settings = Settings(db_path=str(tmp_path / "acc.db"), session_secret=secret,
                        admin_users=frozenset({"owen"}))
    with TestClient(create_app(settings)) as client:
        c = dbmod.connect(settings.db_path)
        try:
            now = dbmod.utcnow_iso()
            dbmod.upsert_project(c, "alpha", "alpha", "/projects/alpha", now)
            dbmod.record_known_editor(c, "wired", "test", now)
            c.commit()
        finally:
            c.close()
        url = "/api/v1/projects/alpha/access/wired"
        assert client.put(url).status_code == 401
        client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(secret, "jsmith"))
        assert client.put(url).status_code == 403
        client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(secret, "owen"))
        hdr = {"Origin": "http://testserver"}
        assert client.put("/api/v1/projects/alpha/access/nobody", headers=hdr).status_code == 404
        assert client.put("/api/v1/projects/zzz/access/wired", headers=hdr).status_code == 404
        r = client.put(url, headers=hdr)
        assert r.status_code == 200 and r.json()["changed"] is True
        assert client.get("/api/v1/projects/alpha/access").json()["editors"] == ["wired"]
        assert client.delete(url, headers=hdr).json()["changed"] is True
        assert client.get("/api/v1/projects/alpha/access").json()["editors"] == []


# ---- round 2b (CR-368, 2026-10-07): ledger = what we added; creator grant --

def _cli_member(client, name="ed", group="proj-alpha"):
    meta = client.ensure_project_group(group)
    client.set_editor_project_groups(name, {group}, {group: meta})   # --project


def test_a_project_flag_membership_survives_tick_then_untick(nas, conn):
    client, fake = nas
    _cli_member(client)
    dbmod.add_selection(conn, "ed", "alpha", "ed", dbmod.utcnow_iso())
    conn.commit()
    project_groups.reconcile(conn, _settings(), nas=client)
    dbmod.remove_selection(conn, "ed", "alpha")
    conn.commit()
    project_groups.reconcile(conn, _settings(), nas=client)
    assert _members(fake, "proj-alpha") == ["ed"]


def test_a_project_flag_membership_survives_grant_then_revoke(nas, conn):
    client, fake = nas
    _cli_member(client)
    project_groups.grant(conn, "alpha", "ed")
    conn.commit()
    project_groups.reconcile(conn, _settings(), nas=client)
    project_groups.revoke(conn, "alpha", "ed")
    conn.commit()
    project_groups.reconcile(conn, _settings(), nas=client)
    assert _members(fake, "proj-alpha") == ["ed"]


def test_the_creator_of_a_project_gets_a_grant_on_a_per_project_site(conn, tmp_path):
    from ccsync_dashboard import api

    projects = tmp_path / "Projects"
    projects.mkdir()
    s = Settings(project_acl="per-project", projects_dir=str(projects))
    api.create_tree_project(s, conn, "", "Night", "", "ed")
    conn.commit()
    assert project_groups.grants(conn).get("night") == ["ed"]
    # shared site: no grant is recorded
    s2 = Settings(project_acl="shared", projects_dir=str(projects))
    api.create_tree_project(s2, conn, "", "Day", "", "bea")
    assert "day" not in project_groups.grants(conn)


def test_deleting_a_user_drops_their_grants_so_a_reused_name_gets_nothing(nas, conn):
    # CR-368 / GL-19 round 2 (2026-10-07): grants are a meta blob, not rows keyed
    # by editor, so forget_editor has to clear them itself.
    client, fake = nas
    dbmod.record_known_editor(conn, "bea", "test")
    project_groups.grant(conn, "alpha", "bea")
    project_groups.grant(conn, "alpha", "cy")
    conn.commit()
    project_groups.reconcile(conn, _settings(), nas=client)
    assert "bea" in _members(fake, "proj-alpha")
    out = dbmod.forget_editor(conn, "bea")
    conn.commit()
    assert out["deleted"]["project_grants"] == 1
    assert project_groups.grants(conn) == {"alpha": ["cy"]}
    dbmod.record_known_editor(conn, "bea", "test")     # the name is reused
    conn.commit()
    project_groups.reconcile(conn, _settings(), nas=client)
    # the NAS membership itself leaves with the NAS account (delete_user_everywhere);
    # what this pins is that the reused name holds no dashboard grant (CR-368 round 3).
    assert "bea" not in project_groups.grants(conn).get("alpha", [])


def test_only_the_creators_own_retry_is_granted_a_marked_unregistered_folder(conn, tmp_path):
    # CR-368 round 3 (2026-10-07): the retry branch used to grant any caller.
    from ccsync_dashboard import api, provision

    projects = tmp_path / "Projects"
    projects.mkdir()
    s = Settings(project_acl="per-project", projects_dir=str(projects))
    mine = projects / "Mine"
    mine.mkdir()
    provision.write_marker(mine, "mine", created_by="ed")
    api.create_tree_project(s, conn, "", "Mine", "", "ed")
    conn.commit()
    assert project_groups.grants(conn).get("mine") == ["ed"]

    secret = projects / "Secret"
    secret.mkdir()
    provision.write_marker(secret, "secret", created_by="setup_tree")
    api.create_tree_project(s, conn, "", "Secret", "", "bea")
    conn.commit()
    assert "secret" not in project_groups.grants(conn)
    # the stranger's POST does not erase who made the folder
    assert provision.read_marker_data(secret)["created_by"] == "setup_tree"


def test_deleting_a_user_clears_their_ledger_so_a_reused_name_keeps_a_cli_membership(nas, conn):
    client, fake = nas
    dbmod.record_known_editor(conn, "bea", "test")
    project_groups.grant(conn, "alpha", "bea")
    conn.commit()
    project_groups.reconcile(conn, _settings(), nas=client)
    dbmod.forget_editor(conn, "bea")
    conn.commit()
    assert "bea" not in (dbmod.meta_get_json(conn, project_groups.META_LEDGER) or {})
    dbmod.record_known_editor(conn, "bea", "test")     # reused name
    _cli_member(client, "bea")                          # setup_editor_account --project
    conn.commit()
    project_groups.reconcile(conn, _settings(), nas=client)
    assert "bea" in _members(fake, "proj-alpha")
